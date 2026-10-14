"""Package reservations must exclude other processes and survive failed opens."""
import subprocess
import os
import sys
import tempfile
import unittest
from pathlib import Path

from atool_qt.package_guard import PackageGuard, session_package_name


class PackageGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.first = PackageGuard(self.directory)
        self.second = PackageGuard(self.directory)
        self.addCleanup(self.first.release)
        self.addCleanup(self.second.release)

    def test_duplicate_is_blocked_but_other_packages_and_own_refresh_are_allowed(self):
        with self.first.reserve('Invoice') as commit:
            commit()
        with self.assertRaisesRegex(ValueError, 'already open'):
            with self.second.reserve(' invoice '):
                self.fail('Duplicate reservation succeeded')
        with self.first.reserve('Invoice') as commit:
            commit()
        with self.second.reserve('Other') as commit:
            commit()
        self.first.release()
        with self.second.reserve('Invoice') as commit:
            commit()

    def test_cancelled_or_failed_replacement_keeps_previous_package_reserved(self):
        with self.first.reserve('Invoice') as commit:
            commit()
        with self.first.reserve('Other'):
            pass  # Cancel before committing.
        with self.assertRaises(RuntimeError):
            with self.first.reserve('Other'):
                raise RuntimeError('Open failed')
        with self.assertRaises(ValueError):
            with self.second.reserve('Invoice'):
                pass
        with self.second.reserve('Other') as commit:
            commit()

    def test_replacement_releases_previous_package(self):
        for name in ('Invoice', 'Other'):
            with self.first.reserve(name) as commit:
                commit()
        with self.second.reserve('Invoice') as commit:
            commit()

    def test_live_reservations_do_not_expire_with_age(self):
        with self.first.reserve('Invoice') as commit:
            commit()
        os.utime(self.first.lock.fileName(), (1, 1))
        with self.assertRaises(ValueError):
            with self.second.reserve('Invoice'):
                pass

    def test_package_identity_uses_manifest_name_across_copies_and_versions(self):
        from atool_qt.session import PackageSession
        for version in ('1', '2'):
            session = PackageSession.from_payload({'$$Id':'Template-' + version, 'Documents':[]})
            session.bundle = {'manifest': {'package': {'shortName':'Invoice'}, 'version': {'shortName':version}}}
            self.assertEqual(session_package_name(session), 'Invoice')
        session.bundle = {}
        self.assertEqual(session_package_name(session), 'Template-2')

    def test_other_process_blocks_open_and_crash_does_not_leave_package_locked(self):
        script = '''
import sys
from atool_qt.package_guard import PackageGuard
guard = PackageGuard(sys.argv[1])
with guard.reserve('Invoice') as commit:
    commit()
print('reserved', flush=True)
sys.stdin.read()
'''
        child = subprocess.Popen([sys.executable, '-c', script, str(self.directory)],
                                 cwd=Path(__file__).resolve().parents[1],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'reserved')
            with self.assertRaisesRegex(ValueError, 'already open'):
                with self.first.reserve('Invoice'):
                    pass
            child.kill()
            child.communicate(timeout=10)
            with self.first.reserve('Invoice') as commit:
                commit()
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
