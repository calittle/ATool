"""Local process reservations, separate from synchronized shared edit locks."""
from contextlib import contextmanager
import hashlib
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths

from .shared_packages import names


def session_package_name(session):
    if session.bundle:
        name = names(session.bundle['manifest'])[0]
        if name:
            return name
    return session.name


class PackageGuard:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
        ) / 'atool-open-packages'
        self.key = None
        self.lock = None

    @contextmanager
    def reserve(self, name):
        """Keep the previous reservation until the new package opens successfully."""
        key = hashlib.sha256(str(name).strip().casefold().encode('utf-8')).hexdigest()
        if key == self.key:
            yield lambda: None
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(self.directory / (key + '.lock')))
        # A live workspace must never expire simply because it has been open a while.
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            if lock.error() == QLockFile.LockError.LockFailedError:
                raise ValueError(f'{name} is already open in another ATool window. Close that package there before opening it here.')
            raise OSError('Could not reserve this package locally. Check access to the temporary folder.')
        committed = False

        def commit():
            nonlocal committed
            self.release()
            self.key, self.lock = key, lock
            committed = True

        try:
            yield commit
        finally:
            if not committed:
                lock.unlock()

    def release(self):
        if self.lock is not None:
            self.lock.unlock()
        self.key = self.lock = None
