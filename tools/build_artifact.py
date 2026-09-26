#!/usr/bin/env python3
"""Build the distributable ATool ZIP in GitHub Actions."""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path


PACKAGE_FILES = (
    "ATool.py",
    "atool_web_editor.py",
    "Run_ATool.bat",
    "Run_ATool.zsh",
    "README.md",
    "requirements.txt",
    "tools/resolve_layout.py",
)
PACKAGE_DIRECTORIES = (
    "atool_core",
)


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


def package_directory_files(repo_root: Path, source: str) -> tuple[str, ...]:
    """Return every tracked/runtime file in package directories for the release zip."""
    if source == "head":
        relative_paths = git_output(
            repo_root,
            "ls-tree",
            "-r",
            "--name-only",
            "HEAD",
            "--",
            *PACKAGE_DIRECTORIES,
            default="",
        ).splitlines()
        return tuple(path for path in relative_paths if path)

    relative_paths: list[str] = []
    for directory in PACKAGE_DIRECTORIES:
        directory_path = repo_root / directory
        if not directory_path.is_dir():
            raise RuntimeError(f"Required package directory is missing: {directory}")
        relative_paths.extend(
            str(path.relative_to(repo_root))
            for path in directory_path.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    return tuple(sorted(relative_paths))


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
    release_tag = git_value(repo_root, "describe", "--tags", "--exact-match", "HEAD")
    built_at = datetime.now().isoformat(timespec="seconds")

    with zipfile.ZipFile(artifact_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path in PACKAGE_FILES:
            archive.writestr(relative_path, read_package_file(repo_root, relative_path, source))
        for relative_path in package_directory_files(repo_root, source):
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
                    f"release_tag={release_tag}",
                    f"dirty={str(is_dirty_worktree).lower()}",
                    f"built_at={built_at}",
                ]
            )
            + "\n",
        )
    return artifact_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("head", "worktree"),
        default="head",
        help="Build from the committed HEAD snapshot or the current worktree.",
    )
    parser.add_argument(
        "--dist-dir",
        help="Local artifact output directory. Defaults to <repo>/dist.",
    )
    return parser.parse_args()


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Release artifacts are built only by GitHub Actions.")
    args = parse_args()
    repo_root = find_repo_root()
    dist_dir = Path(args.dist_dir).expanduser().resolve() if args.dist_dir else repo_root / "dist"
    compile_app(repo_root, args.source)
    artifact_path = build_zip(repo_root, dist_dir, args.source)
    print(f"Built {artifact_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Build failed: {error}", file=sys.stderr)
        raise SystemExit(1)
