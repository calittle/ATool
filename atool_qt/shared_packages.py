"""Original shared-bundle protocol with local copies and conflict-aware publication."""
from __future__ import annotations

import copy
import errno
import logging
import getpass
import hashlib
import json
import os
import re
import shutil
import socket
import tempfile
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .storage import write_files


FILES = {'manifest': 'occs-package.json', 'assemblyTemplate': 'assembly-template.json',
         'versionMaster': 'version-master.json', 'documentAssociations': 'document-associations.json'}


def retry_shared_operation(operation, description='shared folder operation'):
    """Retry the original OneDrive hydration timeout, with the original backoff."""
    for attempt, delay in enumerate((1, 2, 4, None)):
        try:
            return operation()
        except OSError as error:
            if error.errno != errno.ETIMEDOUT or delay is None:
                raise
            logging.getLogger('atool_qt').debug('Shared folder operation timed out; retrying in %s seconds (%s/3): %s', delay, attempt + 1, description)
            time.sleep(delay)


def json_object(path, *, optional=False):
    try:
        value = json.loads(retry_shared_operation(lambda: Path(path).read_text(encoding='utf-8-sig'), 'read shared JSON'))
        if not isinstance(value, dict):
            raise ValueError('Expected a JSON object')
        return value
    except (OSError, ValueError) as error:
        if optional:
            return {}
        raise ValueError(f'Could not read {path}: {error}') from error


def manifest(root):
    value = json_object(Path(root) / FILES['manifest'])
    if value.get('schemaVersion') != 'occs-package-bundle/v1':
        raise ValueError('Unsupported OCCS bundle manifest: ' + str(root))
    return value


def names(value):
    package, version = value.get('package', {}), value.get('version', {})
    return (str(package.get('shortName') or package.get('name') or '').strip() if isinstance(package, dict) else '',
            str(version.get('shortName') or '').strip() if isinstance(version, dict) else '')


def segment(value):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', str(value).strip()).strip('._-') or 'unnamed'


def timestamp():
    return datetime.now().astimezone().isoformat()


def encode(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def bundle_paths(root, value):
    root = Path(root).resolve()
    files = value.get('files', {})
    files = files if isinstance(files, dict) else {}
    result = {}
    for key, fallback in FILES.items():
        path = Path(str(files.get(key) or fallback))
        resolved = (root / path).resolve()
        result[key] = resolved
    return result


def bundle_hashes(root, value=None, *, portable=False):
    value = value or manifest(root)
    paths = bundle_paths(root, value)
    hashes = {}
    for key, path in paths.items():
        if key == 'documentAssociations' and not path.exists():
            continue
        data = json.loads(retry_shared_operation(lambda: path.read_text(encoding='utf-8-sig'), 'read package file'))
        if portable and key == 'manifest':
            data = copy.deepcopy(data)
            data.pop('bundlePath', None)
            paths_value = data.get('files', {})
            extra_paths = {name: item for name, item in paths_value.items() if name not in FILES} if isinstance(paths_value, dict) else {}
            data['files'] = extra_paths
        stable = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        hashes[key] = hashlib.sha256(stable.encode('utf-8')).hexdigest()
    return hashes


def copy_bundle_files(source_root, target_root):
    """Copy declared JSON files, making location-dependent manifests portable.

    The original manifest and files stay untouched. Exact hashes remain available
    for concurrency checks; portable hashes compare logical bundle contents.
    """
    source_root, target_root = Path(source_root).resolve(), Path(target_root).resolve()
    value = manifest(source_root)
    sources = bundle_paths(source_root, value)
    before = bundle_hashes(source_root, value)
    relocate = any(not path.is_relative_to(source_root) for path in sources.values())
    copied = copy.deepcopy(value)
    declared = copied.get('files')
    declared = dict(declared) if isinstance(declared, dict) else {}
    for key, source in sources.items():
        relative = Path(FILES[key]) if relocate or key == 'manifest' else source.relative_to(source_root)
        if key in declared or relocate:
            declared[key] = relative.as_posix()
        if key == 'manifest' or (key == 'documentAssociations' and not source.exists()):
            continue
        target = target_root / relative
        retry_shared_operation(lambda: target.parent.mkdir(parents=True, exist_ok=True), 'create package copy folder')
        retry_shared_operation(lambda: shutil.copy2(source, target), 'copy package file')
    if declared or 'files' in copied:
        copied['files'] = declared
    if 'bundlePath' in copied:
        # Relative to the copied manifest, so a later rename stays portable.
        copied['bundlePath'] = '.'
    retry_shared_operation(lambda: target_root.mkdir(parents=True, exist_ok=True), 'create package copy folder')
    retry_shared_operation(lambda: (target_root / FILES['manifest']).write_bytes(encode(copied)), 'write copied package manifest')
    if bundle_hashes(source_root) != before or bundle_hashes(target_root, portable=True) != bundle_hashes(source_root, portable=True):
        raise ValueError('The package changed while preparing its copy.')
    return sources


class SharedPackages:
    HISTORY_LIMIT = 5
    BASELINE = '.atool-shared-baseline.json'

    def __init__(self, shared_dir, work_dir, owner=None):
        self.shared_dir, self.work_dir = Path(shared_dir).expanduser().resolve(), Path(work_dir).expanduser().resolve()
        self.owner = owner or dict(user=getpass.getuser(), displayName=getpass.getuser(), host=socket.gethostname())

    @staticmethod
    def lock_path(package_dir):
        return Path(package_dir) / 'locks' / 'package.lock.json'

    @staticmethod
    def owned(lock, owner):
        identity = lock.get('owner', {}) if isinstance(lock, dict) else {}
        return bool(identity) and identity.get('user') == owner.get('user') and identity.get('host') == owner.get('host')

    def package_dir(self, value):
        package, version = names(value)
        if not package or not version:
            raise ValueError('Package manifest is missing package or version metadata.')
        return self.shared_dir / 'packages' / segment(package) / segment(version)

    def entry(self, package_dir):
        package_dir = Path(package_dir)
        published = package_dir / 'published' / 'current'
        if not (published / FILES['manifest']).is_file():
            return None
        value = {}
        error = ''
        try:
            value = manifest(published)
        except ValueError as failure:
            error = str(failure)
        lock_path = self.lock_path(package_dir)
        lock = json_object(lock_path) if lock_path.exists() else None
        package, version = names(value)
        return dict(workspace_dir=self.shared_dir, package_dir=package_dir, published_dir=published,
            package_name=package or package_dir.parent.name, version_name=version or package_dir.name,
            manifest=value, publication=json_object(published / 'publication.json', optional=True), lock=lock, unavailable_reason=error)

    def entries(self):
        root = self.shared_dir / 'packages'
        if not root.exists():
            return []
        return [entry for package in sorted(root.iterdir()) if package.is_dir()
                for version in sorted(package.iterdir()) if version.is_dir()
                if (entry := self.entry(version)) is not None]

    def baseline(self, local, entry, reason):
        return dict(schemaVersion='atool-shared-baseline/v1', capturedAt=timestamp(), reason=reason,
            package=entry['package_name'], version=entry['version_name'], publishedDir=str(entry['published_dir']),
            publishedAt=entry['publication'].get('publishedAt', ''), sharedHashes=bundle_hashes(entry['published_dir'], entry['manifest']))

    def lock_payload(self, entry, local=None, previous=None):
        now = timestamp()
        payload = copy.deepcopy(previous or {})
        payload.update(schemaVersion='atool-shared-lock/v1', createdAt=payload.get('createdAt') or now, updatedAt=now,
            scope=dict(type='package-version', package=entry['package_name'], version=entry['version_name']),
            lock=dict(mode='edit', supportsFutureScopes=True), package=entry['package_name'], version=entry['version_name'],
            owner=self.owner, bundleDir=str(local or entry['published_dir']), sourceHashes=entry['manifest'].get('sourceHashes', {}),
            sharedBaselineHashes=bundle_hashes(entry['published_dir'], entry['manifest']))
        payload.setdefault('lockToken', uuid4().hex)
        return payload

    def acquire(self, entry, local=None):
        path = self.lock_path(entry['package_dir'])
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            previous_bytes = path.read_bytes()
            previous = json_object(path)
            if not self.owned(previous, self.owner):
                raise ValueError('This package version is locked by another user.')
            payload = self.lock_payload(entry, local, previous)
            if path.read_bytes() != previous_bytes:
                raise ValueError('The shared lock changed. Refresh before continuing.')
            write_files({path: encode(payload)})
        else:
            payload = self.lock_payload(entry, local)
            with path.open('xb') as stream:
                stream.write(encode(payload))
                stream.flush()
                os.fsync(stream.fileno())
        return payload

    def release(self, entry, *, force=False, expected=None):
        path = self.lock_path(entry['package_dir'])
        if not path.exists():
            return
        original = path.read_bytes()
        lock = json_object(path)
        if expected is not None and lock != expected:
            raise ValueError('The shared lock changed. Refresh before unlocking.')
        if not force and not self.owned(lock, self.owner):
            raise ValueError('This package version is locked by another user.')
        if path.read_bytes() != original:
            raise ValueError('The shared lock changed. Refresh before unlocking.')
        path.unlink()

    def open_copy(self, entry, mode):
        entry = self.entry(entry['package_dir'])
        if not entry or entry['unavailable_reason']:
            raise ValueError('The shared package version is unavailable.')
        if mode not in ('edit', 'testing'):
            raise ValueError('Unknown shared package mode.')
        from .session import PackageSession
        PackageSession.open(entry['published_dir'])
        hashes = bundle_hashes(entry['published_dir'], entry['manifest'])
        self.work_dir.mkdir(parents=True, exist_ok=True)
        local = self.work_dir / f"{segment(entry['package_name'])}-{segment(entry['version_name'])}-{mode}-{datetime.now():%Y%m%d_%H%M%S_%f}"
        lock_before = None
        acquired = False
        try:
            if mode == 'edit':
                lock_path = self.lock_path(entry['package_dir'])
                lock_before = lock_path.read_bytes() if lock_path.exists() else None
                self.acquire(entry, local)
                acquired = True
            retry_shared_operation(lambda: shutil.copytree(entry['published_dir'], local, dirs_exist_ok=True), 'copy shared package to local folder')
            copy_bundle_files(entry['published_dir'], local)
            if bundle_hashes(local, portable=True) != bundle_hashes(entry['published_dir'], portable=True) or bundle_hashes(entry['published_dir']) != hashes:
                raise ValueError('The shared package changed while its local copy was being created. Refresh and retry.')
            write_files({local / self.BASELINE: encode(self.baseline(local, entry, 'opened-' + mode))})
            return local
        except BaseException:
            if local.exists():
                shutil.rmtree(local)
            if acquired:
                lock_path = self.lock_path(entry['package_dir'])
                current = json_object(lock_path, optional=True)
                if self.owned(current, self.owner) and current.get('bundleDir') == str(local):
                    if lock_before is None:
                        lock_path.unlink(missing_ok=True)
                    else:
                        write_files({lock_path: lock_before})
            raise

    def resumable(self, local, entry):
        local = Path(local).expanduser()
        try:
            value = manifest(local)
            baseline = json_object(local / self.BASELINE)
            return (local.resolve() != entry['published_dir'].resolve() and names(value) == (entry['package_name'], entry['version_name'])
                and baseline.get('reason') in ('opened-edit', 'updatedShared', 'publishedToComms')
                and (baseline.get('package'), baseline.get('version')) == names(value))
        except (ValueError, OSError):
            return False

    def resume_path(self, entry):
        candidates = []
        if (entry.get('lock') or {}).get('bundleDir'):
            candidates.append(Path(entry['lock']['bundleDir']).expanduser())
        if self.work_dir.is_dir():
            candidates += sorted((path for path in self.work_dir.iterdir() if path.is_dir()), key=lambda path:path.stat().st_mtime, reverse=True)
        return next((path for path in candidates if self.resumable(path, entry)), None)

    def restore_context(self, local):
        baseline = json_object(Path(local) / self.BASELINE, optional=True)
        published = Path(str(baseline.get('publishedDir') or ''))
        if published.name != 'current' or published.parent.name != 'published':
            return None, 'local'
        entry = self.entry(published.parent.parent)
        if not entry or not self.resumable(local, entry):
            return None, 'local'
        lock = entry.get('lock')
        editing = self.owned(lock, self.owner) and str(Path(lock.get('bundleDir', '')).expanduser().resolve()) == str(Path(local).resolve())
        return entry['package_dir'], 'edit' if editing else 'testing'

    def matches(self, local, package_dir):
        try:
            entry = self.entry(package_dir)
            return bool(entry) and bundle_hashes(local, portable=True) == bundle_hashes(entry['published_dir'], entry['manifest'], portable=True)
        except (ValueError, OSError):
            return False

    def verify_update(self, local, entry):
        lock_path = self.lock_path(entry['package_dir'])
        lock = json_object(lock_path)
        if not self.owned(lock, self.owner):
            raise ValueError('An edit lock owned by you is required to update this package.')
        if lock.get('bundleDir') and Path(lock['bundleDir']).expanduser().resolve() != Path(local).resolve():
            raise ValueError('The edit lock belongs to a different local session.')
        baseline = json_object(Path(local) / self.BASELINE)
        if (baseline.get('package'), baseline.get('version')) != (entry['package_name'], entry['version_name']):
            raise ValueError('The local baseline does not match this package and version.')
        current = bundle_hashes(entry['published_dir'], entry['manifest'])
        if baseline.get('sharedHashes') != current:
            raise ValueError('This local copy is based on an older shared version. Open the latest copy before updating.')
        return lock, current

    def publish(self, local, package_dir=None, *, reason='updateFromLocal', release=False, initial=False):
        """Stage current/history first; restore the prior version if any commit step fails."""
        local = Path(local)
        value = manifest(local)
        package_dir = Path(package_dir or self.package_dir(value))
        entry = self.entry(package_dir)
        if not initial:
            if not entry:
                raise ValueError('The shared package version no longer exists.')
            lock, expected_hashes = self.verify_update(local, entry)
        else:
            lock = json_object(self.lock_path(package_dir), optional=True)
            if lock and not self.owned(lock, self.owner):
                raise ValueError('Another user holds this package version lock.')
            expected_hashes = bundle_hashes(entry['published_dir']) if entry else None
        if entry and names(value) != (entry['package_name'], entry['version_name']):
            raise ValueError('Local and shared package/version identities differ.')
        original_lock = self.lock_path(package_dir).read_bytes() if self.lock_path(package_dir).exists() else None
        publication = dict(schemaVersion='atool-publication/v1', publishedAt=timestamp(),
            scope=dict(type='package-version', package=names(value)[0], version=names(value)[1]),
            operation=dict(reason=reason, supportsFutureScopes=True), package=names(value)[0], version=names(value)[1],
            owner=self.owner, sourceBundleDir=str(local), sourceManifest={key:value.get(key, {}) for key in ('createdAt', 'bundlePath', 'source', 'sourceHashes')})
        published = package_dir / 'published'
        retry_shared_operation(lambda: published.mkdir(parents=True, exist_ok=True), 'create shared publication folder')
        stage = Path(tempfile.mkdtemp(prefix='.atool-stage-', dir=published))
        backup = published / ('.atool-previous-' + uuid4().hex)
        history = published / 'history' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '-' + segment(self.owner['user']))
        current = published / 'current'
        current_replaced = False
        moved_previous = False
        metadata_committed = False
        baseline_path = local / self.BASELINE
        baseline_before = baseline_path.read_bytes() if baseline_path.exists() else None
        try:
            copy_bundle_files(local, stage)
            retry_shared_operation(lambda: (stage / 'publication.json').write_bytes(encode(publication)), 'write shared publication metadata')
            if (bundle_hashes(current) if current.exists() else None) != expected_hashes:
                raise ValueError('The shared package changed while preparing this update.')
            lock_path = self.lock_path(package_dir)
            if (lock_path.read_bytes() if lock_path.exists() else None) != original_lock:
                raise ValueError('The shared edit lock changed while preparing this update.')
            retry_shared_operation(lambda: history.parent.mkdir(parents=True, exist_ok=True), 'create shared history folder')
            retry_shared_operation(lambda: shutil.copytree(stage, history, dirs_exist_ok=True), 'copy shared history snapshot')
            if current.exists():
                os.replace(current, backup)
                moved_previous = True
            os.replace(stage, current)
            current_replaced = True
            fresh_entry = self.entry(package_dir)
            writes = {local / self.BASELINE: encode(self.baseline(local, fresh_entry, 'updatedShared' if not initial else reason))}
            if lock and not release:
                writes[lock_path] = encode(self.lock_payload(fresh_entry, local, lock))
            write_files(writes)
            metadata_committed = True
            if release and lock:
                lock_path.unlink()
            # Cleanup failures must not undo an already committed publication.
            result = self.entry(package_dir)
            current_replaced = moved_previous = metadata_committed = False
            try:
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
                for stale in sorted((path for path in history.parent.iterdir() if path.is_dir()), reverse=True)[self.HISTORY_LIMIT:]:
                    shutil.rmtree(stale, ignore_errors=True)
            except OSError:
                pass
            return result
        except BaseException:
            if metadata_committed:
                restore = {}
                if baseline_before is None:
                    baseline_path.unlink(missing_ok=True)
                else:
                    restore[baseline_path] = baseline_before
                if original_lock is not None:
                    restore[self.lock_path(package_dir)] = original_lock
                if restore:
                    write_files(restore)
            if current_replaced and current.exists():
                shutil.rmtree(current)
            if moved_previous and backup.exists():
                os.replace(backup, current)
            if history.exists():
                shutil.rmtree(history)
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def cleanup_entries(self, current=None):
        if not self.work_dir.is_dir():
            return []
        protected = {}
        if current:
            protected[Path(current).resolve()] = 'Current open package'
        packages = self.shared_dir / 'packages'
        if packages.exists():
            for path in packages.rglob('package.lock.json'):
                lock = json_object(path)
                if lock.get('bundleDir'):
                    protected.setdefault(Path(lock['bundleDir']).expanduser().resolve(), 'Referenced by active shared lock')
        entries = []
        for path in self.work_dir.iterdir():
            if not path.is_dir() or path.is_symlink() or path.resolve().parent != self.work_dir.resolve() or not (path / FILES['manifest']).is_file():
                continue
            try:
                package, version = names(manifest(path))
            except ValueError:
                package = version = '(unreadable)'
            files = [file for file in path.rglob('*') if file.is_file() and not file.is_symlink()]
            modified = max([path.stat().st_mtime] + [file.stat().st_mtime for file in files])
            age = max(0, (time.time() - modified) / 86400)
            status = protected.get(path.resolve(), '')
            entries.append(dict(path=path, package=package, version=version, modified=modified, age=age,
                size=sum(file.stat().st_size for file in files), protected=bool(status),
                status=status or ('Old cleanup candidate' if age >= 14 else 'Removable'), default_selected=not status and age >= 14))
        return sorted(entries, key=lambda entry:(entry['protected'], -entry['age'], entry['path'].name))

    def delete_local(self, paths, current=None):
        # Re-read active locks and current-session protection immediately before each deletion.
        removed = []
        for selected in paths:
            selected = Path(selected)
            fresh = next((entry for entry in self.cleanup_entries(current) if entry['path'] == selected), None)
            if not fresh or fresh['protected']:
                raise ValueError('This local package is protected or no longer a direct work-folder child: ' + str(selected))
            shutil.rmtree(selected)
            removed.append(selected)
        return removed
