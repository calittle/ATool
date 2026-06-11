#!/usr/bin/env python3
"""Build a distributable ATool zip and optionally copy it to a local destination."""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path


PACKAGE_FILES = (
    "ATool.py",
    "Run_ATool.bat",
    "Run_ATool.zsh",
    "README.md",
)
LOCAL_CONFIG_FILE = ".atool-build.local.json"


def run_git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def find_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip()).resolve()
    return Path(__file__).resolve().parents[1]


def git_value(repo_root: Path, *args: str, default: str = "") -> str:
    result = run_git(repo_root, *args, check=False)
    if result.returncode != 0:
        return default
    return result.stdout.strip() or default


def git_output(repo_root: Path, *args: str, default: str = "") -> str:
    result = run_git(repo_root, *args, check=False)
    if result.returncode != 0:
        return default
    return result.stdout.rstrip() or default


def load_local_config(repo_root: Path) -> dict[str, object]:
    config_path = repo_root / LOCAL_CONFIG_FILE
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as source:
        config = json.load(source)
    if not isinstance(config, dict):
        raise ValueError(f"{LOCAL_CONFIG_FILE} must contain a JSON object.")
    return config


def resolve_destination(args: argparse.Namespace, config: dict[str, object]) -> Path | None:
    configured = args.dest or os.environ.get("ATOOL_ARTIFACT_DIR") or config.get("sharepoint_dir")
    if configured is None:
        return None
    destination = Path(str(configured)).expanduser()
    return destination.resolve()


def compile_app(repo_root: Path, source: str) -> None:
    if source == "worktree":
        py_compile.compile(str(repo_root / "ATool.py"), doraise=True)
        return

    app_source = git_value(repo_root, "show", "HEAD:ATool.py")
    if not app_source:
        raise RuntimeError("Could not read ATool.py from HEAD.")
    with tempfile.TemporaryDirectory(prefix="atool-build-") as temp_dir:
        temp_app = Path(temp_dir) / "ATool.py"
        temp_app.write_text(app_source, encoding="utf-8")
        py_compile.compile(str(temp_app), doraise=True)


def read_package_file(repo_root: Path, relative_path: str, source: str) -> bytes:
    file_path = repo_root / relative_path
    if source == "worktree":
        return file_path.read_bytes()

    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"HEAD:{relative_path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        return result.stdout
    return file_path.read_bytes()


def read_release_notes_body(repo_root: Path, source: str) -> str:
    notes_path = repo_root / "NOTES.MD"
    raw = ""
    if source == "worktree":
        if notes_path.exists():
            raw = notes_path.read_text(encoding="utf-8")
    else:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "show", "HEAD:NOTES.MD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            raw = result.stdout
        elif notes_path.exists():
            raw = notes_path.read_text(encoding="utf-8")

    lines = raw.strip().splitlines()
    if lines and lines[0].strip().lower() == "# atool release notes":
        lines = lines[1:]
    return "\n".join(lines).strip()


def build_release_notes(
    repo_root: Path,
    *,
    artifact_name: str,
    source: str,
    built_at: str,
    full_commit_sha: str,
) -> str:
    short_commit_sha = git_value(repo_root, "rev-parse", "--short", "HEAD", default="local")
    commit_snippet = git_output(
        repo_root,
        "show",
        "--stat",
        "--no-renames",
        "--date=iso-strict",
        "--format=commit %H%nAuthor: %an <%ae>%nDate: %ad%n%n    %s%n%n%b",
        "HEAD",
        default="Commit details are unavailable.",
    )
    lines = [
        "# ATool Release Notes",
        "",
        f"- Artifact: `{artifact_name}`",
        f"- Source: `{source}`",
        f"- Commit: `{full_commit_sha}`",
        f"- Built at: `{built_at}`",
        "",
        "## Commit Snippet",
        "",
        "```text",
        commit_snippet,
        "```",
    ]

    notes_body = read_release_notes_body(repo_root, source)
    if notes_body:
        lines.extend(
            [
                "",
                "## User-Facing Change Notes",
                "",
                notes_body,
            ]
        )

    if source == "worktree":
        status = git_output(repo_root, "status", "--short", default="")
        diffstat = git_output(repo_root, "diff", "--stat", default="")
        lines.extend(
            [
                "",
                "## Worktree Snapshot",
                "",
                f"The artifact was built from the working tree at `{short_commit_sha}`.",
            ]
        )
        if status:
            lines.extend(["", "### Uncommitted Status", "", "```text", status, "```"])
        if diffstat:
            lines.extend(["", "### Uncommitted Diffstat", "", "```text", diffstat, "```"])
        if not status and not diffstat:
            lines.append("")
            lines.append("No uncommitted worktree changes were detected.")

    lines.append("")
    return "\n".join(lines)


def build_zip(repo_root: Path, dist_dir: Path, source: str) -> Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    commit_sha = git_value(repo_root, "rev-parse", "--short", "HEAD", default="local")
    is_dirty_worktree = source == "worktree" and bool(git_output(repo_root, "status", "--short", default=""))
    build_id = f"{commit_sha}-dirty" if is_dirty_worktree and commit_sha != "local" else commit_sha
    artifact_path = dist_dir / f"ATool-{timestamp}-{build_id}.zip"
    full_commit_sha = git_value(repo_root, "rev-parse", "HEAD", default="local")
    built_at = datetime.now().isoformat(timespec="seconds")

    with zipfile.ZipFile(artifact_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path in PACKAGE_FILES:
            archive.writestr(relative_path, read_package_file(repo_root, relative_path, source))
        archive.writestr(
            "NOTES.MD",
            build_release_notes(
                repo_root,
                artifact_name=artifact_path.name,
                source=source,
                built_at=built_at,
                full_commit_sha=full_commit_sha,
            ),
        )
        archive.writestr(
            "BUILD_INFO.txt",
            "\n".join(
                [
                    f"artifact={artifact_path.name}",
                    f"source={source}",
                    f"commit={full_commit_sha}",
                    f"dirty={str(is_dirty_worktree).lower()}",
                    f"built_at={built_at}",
                ]
            )
            + "\n",
        )
    return artifact_path


def copy_to_destination(artifact_path: Path, destination: Path, latest_name: str | None) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    copied_paths = [destination / artifact_path.name]
    shutil.copy2(artifact_path, copied_paths[0])
    if latest_name:
        latest_path = destination / latest_name
        shutil.copy2(artifact_path, latest_path)
        copied_paths.append(latest_path)
    return copied_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("head", "worktree"),
        default="head",
        help="Build from the committed HEAD snapshot or the current worktree.",
    )
    parser.add_argument(
        "--dest",
        help="Directory to copy the artifact to. Defaults to ATOOL_ARTIFACT_DIR or .atool-build.local.json.",
    )
    parser.add_argument(
        "--dist-dir",
        help="Local artifact output directory. Defaults to <repo>/dist.",
    )
    parser.add_argument(
        "--latest-name",
        default="ATool-latest.zip",
        help="Optional stable filename to update in the destination directory.",
    )
    parser.add_argument(
        "--no-latest",
        action="store_true",
        help="Do not write a stable latest artifact filename in the destination directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = find_repo_root()
    config = load_local_config(repo_root)
    dist_dir = Path(args.dist_dir).expanduser().resolve() if args.dist_dir else repo_root / "dist"
    latest_name = None if args.no_latest else args.latest_name

    compile_app(repo_root, args.source)
    artifact_path = build_zip(repo_root, dist_dir, args.source)
    print(f"Built {artifact_path}")

    destination = resolve_destination(args, config)
    if destination is None:
        print(
            "No SharePoint destination configured. Set ATOOL_ARTIFACT_DIR "
            f"or {LOCAL_CONFIG_FILE} to enable copying."
        )
        return 0

    copied_paths = copy_to_destination(artifact_path, destination, latest_name)
    for copied_path in copied_paths:
        print(f"Copied {copied_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Build failed: {error}", file=sys.stderr)
        raise SystemExit(1)
