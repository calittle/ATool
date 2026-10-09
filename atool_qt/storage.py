"""Rollback-capable multi-file saves for a local package bundle."""
from __future__ import annotations

import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path


def stage_bytes(path, encoded):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".atool-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        return Path(temporary)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_files(files):
    """Stage every file, back up originals, and restore writes if a replacement fails.

    A crash across replacements cannot be made atomic by the filesystem; the
    original-byte backups provide recovery in addition to exception rollback.
    """
    originals = {Path(path): Path(path).read_bytes() if Path(path).exists() else None for path in files}
    staged, replaced = {}, []
    try:
        for path, encoded in files.items():
            staged[Path(path)] = stage_bytes(path, encoded)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
        for path, original in originals.items():
            if original is not None:
                backup = path.with_name(f"{path.stem}_backup_{stamp}{path.suffix}")
                with backup.open("xb") as stream:
                    stream.write(original)
        for path, temporary in staged.items():
            os.replace(temporary, path)
            replaced.append(path)
    except BaseException:
        for path in reversed(replaced):
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                temporary = stage_bytes(path, original)
                try:
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
