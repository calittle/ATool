#!/usr/bin/env python3
"""Build a distributable Technical Design Generator ZIP."""

from __future__ import annotations

import argparse
import py_compile
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import build_artifact as artifact


TD_ROOT = "tools/td_generator/"
LOCAL_CONFIG_FILE = ".atool-build.local.json"
TD_DESTINATION_KEY = "td_generator_artifact_dir"
TD_DEPENDENCIES = {
    "atool_core/__init__.py",
    "atool_core/condition_evaluator.py",
    "atool_core/td_evidence.py",
}
TRIGGER_PATHS = {"tools/build_td_artifact.py", ".githooks/post-commit", *TD_DEPENDENCIES}


def changed_paths(repo_root: Path) -> set[str]:
    output = artifact.git_output(
        repo_root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "HEAD", default=""
    )
    return {line for line in output.splitlines() if line}


def is_relevant_change(paths: set[str]) -> bool:
    return any(path.startswith(TD_ROOT) or path in TRIGGER_PATHS for path in paths)


def package_files(repo_root: Path, source: str) -> list[str]:
    if source == "head":
        candidates = artifact.git_output(
            repo_root, "ls-tree", "-r", "--name-only", "HEAD", "--", TD_ROOT, "atool_core", default=""
        ).splitlines()
    else:
        candidates = [
            str(path.relative_to(repo_root))
            for root in (repo_root / "tools" / "td_generator", repo_root / "atool_core")
            if root.exists()
            for path in root.rglob("*")
            if path.is_file()
        ]
    included: list[str] = []
    for path in candidates:
        normalized = path.replace("\\", "/")
        if normalized.startswith("tools/td_generator/generated/"):
            continue
        if normalized.endswith((".pyc", ".DS_Store")) or "/__pycache__/" in normalized:
            continue
        if normalized.startswith("tools/td_generator/samples/") and "-preview-" in normalized and normalized.endswith(".html"):
            continue
        if normalized.startswith(TD_ROOT) or normalized in TD_DEPENDENCIES:
            included.append(normalized)
    return sorted(set(included), key=str.casefold)


def compile_sources(repo_root: Path, files: list[str], source: str) -> None:
    with tempfile.TemporaryDirectory(prefix="td-generator-build-") as temp_dir:
        temporary_root = Path(temp_dir)
        for relative_path in (path for path in files if path.endswith(".py")):
            target = temporary_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(artifact.read_package_file(repo_root, relative_path, source))
            py_compile.compile(str(target), doraise=True)


def build_zip(repo_root: Path, dist_dir: Path, source: str) -> Path:
    files = package_files(repo_root, source)
    if not files:
        raise RuntimeError("No Technical Design Generator files were found to package.")
    compile_sources(repo_root, files, source)
    dist_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    commit = artifact.git_value(repo_root, "rev-parse", "HEAD", default="local")
    short_commit = artifact.git_value(repo_root, "rev-parse", "--short", "HEAD", default="local")
    dirty = source == "worktree" and bool(artifact.git_output(repo_root, "status", "--short", default=""))
    build_id = f"{short_commit}-dirty" if dirty else short_commit
    output = dist_dir / f"TD-Generator-{timestamp}-{build_id}.zip"
    notes = [
        "# Technical Design Generator Release Notes",
        "",
        f"- Artifact: `{output.name}`",
        f"- Source: `{source}`",
        f"- Commit: `{commit}`",
        "",
        "## Included files",
        "",
        *[f"- `{path}`" for path in files],
        "",
    ]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path in files:
            archive.writestr(relative_path, artifact.read_package_file(repo_root, relative_path, source))
        archive.writestr("NOTES.MD", "\n".join(notes))
        archive.writestr("BUILD_INFO.txt", f"artifact={output.name}\nsource={source}\ncommit={commit}\nbuilt_at={datetime.now().isoformat(timespec='seconds')}\n")
    return output


def resolve_destination(repo_root: Path, configured: str | None) -> Path | None:
    if configured:
        return Path(configured).expanduser().resolve()
    config = artifact.load_local_config(repo_root)
    destination = config.get(TD_DESTINATION_KEY)
    return Path(str(destination)).expanduser().resolve() if destination else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("head", "worktree"), default="head")
    parser.add_argument("--if-relevant", action="store_true", help="Exit without building unless HEAD changes TD source or a shared dependency.")
    parser.add_argument("--dist-dir", type=Path, help="Local output directory. Defaults to <repo>/dist/td-generator.")
    parser.add_argument("--dest", help=f"Directory to copy the artifact to. Defaults to {TD_DESTINATION_KEY} in {LOCAL_CONFIG_FILE}.")
    parser.add_argument("--no-copy", action="store_true", help="Keep the artifact in the local output directory only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = artifact.find_repo_root()
    if args.if_relevant and not is_relevant_change(changed_paths(repo_root)):
        print("No Technical Design Generator source changes in HEAD; artifact not built.")
        return 0
    dist_dir = args.dist_dir.expanduser().resolve() if args.dist_dir else repo_root / "dist" / "td-generator"
    output = build_zip(repo_root, dist_dir, args.source)
    print(f"Built {output}")
    if args.no_copy:
        return 0
    destination = resolve_destination(repo_root, args.dest)
    if destination is None:
        print(f"No TD artifact destination configured. Set {TD_DESTINATION_KEY} in {LOCAL_CONFIG_FILE} or pass --dest.")
        return 0
    for copied in artifact.copy_to_destination(output, destination, "TD-Generator-latest.zip"):
        print(f"Copied {copied}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"TD Generator build failed: {error}", file=sys.stderr)
        raise SystemExit(1)
