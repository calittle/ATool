"""Original ETIMEDOUT backoff and idempotent recovery of shared copies."""
import errno
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from atool_qt.shared_packages import retry_shared_operation, json_object, bundle_hashes
from atool_qt.validation import PayloadValidation


class SharedRetryTests(unittest.TestCase):
    def fixture(self):
        from test_qt_shared_packages import SharedPackageTests
        fixture=SharedPackageTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_original_backoff_bounded_and_other_errors_not_retried(self):
        timeout=OSError(errno.ETIMEDOUT,'OneDrive hydration timeout')
        with patch('atool_qt.shared_packages.time.sleep') as sleep:
            operation=unittest.mock.Mock(side_effect=[timeout,timeout,timeout,'done'])
            self.assertEqual(retry_shared_operation(operation),'done')
            self.assertEqual([call.args[0] for call in sleep.call_args_list],[1,2,4])
            sleep.reset_mock()
            operation=unittest.mock.Mock(side_effect=timeout)
            with self.assertRaises(OSError):retry_shared_operation(operation)
            self.assertEqual(operation.call_count,4)
            self.assertEqual([call.args[0] for call in sleep.call_args_list],[1,2,4])
        for error in (PermissionError(errno.EACCES,'Denied'),FileNotFoundError(errno.ENOENT,'Missing'),ValueError('Invalid JSON')):
            operation=unittest.mock.Mock(side_effect=error)
            with patch('atool_qt.shared_packages.time.sleep') as sleep:
                with self.assertRaises(type(error)):retry_shared_operation(operation)
                self.assertEqual(operation.call_count,1)
                sleep.assert_not_called()

    def test_manifest_read_retries_hydration_before_interpreting_optional_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'manifest.json';path.write_text('{"preserved":true}')
            read=Path.read_text
            attempts=[]
            def hydrated(candidate,*args,**kwargs):
                attempts.append(candidate)
                if len(attempts)==1:raise OSError(errno.ETIMEDOUT,'Not hydrated')
                return read(candidate,*args,**kwargs)
            with patch.object(Path,'read_text',hydrated),patch('atool_qt.shared_packages.time.sleep') as sleep:
                self.assertEqual(json_object(path),{'preserved':True})
                sleep.assert_called_once_with(1)
                self.assertEqual(len(attempts),2)

    def test_publication_copy_retry_keeps_conflict_hashes_and_lock_protocol(self):
        fixture=self.fixture()
        local=fixture.store.open_copy(fixture.entry,'edit')
        source=local/'assembly-template.json';source.write_text('{"Documents":[],"Fields":[],"Extra":1}')
        copy=shutil.copy2
        attempts=[]
        def hydrated(source,target,*args,**kwargs):
            attempts.append((source,target))
            if len(attempts)==1:raise OSError(errno.ETIMEDOUT,'Write delayed')
            return copy(source,target,*args,**kwargs)
        with patch('atool_qt.shared_packages.shutil.copy2',hydrated),patch('atool_qt.shared_packages.time.sleep') as sleep:
            fixture.store.publish(local)
            sleep.assert_called_once_with(1)
        self.assertTrue(fixture.store.matches(local,fixture.entry['package_dir']))
        self.assertEqual(json_object(fixture.entry['published_dir']/'assembly-template.json')['Extra'],1)
        self.assertEqual(fixture.store.entry(fixture.entry['package_dir'])['lock']['bundleDir'],str(local))

    def test_partial_local_tree_copy_retries_without_losing_acquired_lock(self):
        fixture=self.fixture()
        copy=shutil.copytree
        attempts=[]
        def hydrated(source,target,*args,**kwargs):
            attempts.append(target)
            if len(attempts)==1:
                Path(target).mkdir()
                shutil.copy2(Path(source)/'occs-package.json',Path(target)/'occs-package.json')
                raise OSError(errno.ETIMEDOUT,'Partial hydration')
            return copy(source,target,*args,**kwargs)
        with patch('atool_qt.shared_packages.shutil.copytree',hydrated),patch('atool_qt.shared_packages.time.sleep') as sleep:
            local=fixture.store.open_copy(fixture.entry,'edit')
            sleep.assert_called_once_with(1)
        self.assertEqual(bundle_hashes(local),bundle_hashes(fixture.entry['published_dir']))
        self.assertEqual(fixture.store.entry(fixture.entry['package_dir'])['lock']['bundleDir'],str(local))

    def test_terminal_copy_timeout_rolls_back_new_lock_and_partial_local_folder(self):
        fixture=self.fixture()
        with patch('atool_qt.shared_packages.shutil.copytree',side_effect=OSError(errno.ETIMEDOUT,'Unavailable')),patch('atool_qt.shared_packages.time.sleep') as sleep:
            with self.assertRaises(OSError):fixture.store.open_copy(fixture.entry,'edit')
            self.assertEqual(sleep.call_count,3)
        self.assertFalse(fixture.store.lock_path(fixture.entry['package_dir']).exists())
        self.assertEqual(list(fixture.store.work_dir.iterdir()),[])

    def test_condition_path_validation_warns_only_for_actual_pathless_comparison(self):
        for body in ('@.flag == false', '@.amount == 0', "@['amount'] == 0", '$.flag == true'):
            self.assertEqual(PayloadValidation._at_condition_validation_messages('$[?('+body+')]'),([],[]))
        issues,warnings=PayloadValidation._at_condition_validation_messages('$[?(true == false)]')
        self.assertEqual(issues,[])
        self.assertTrue(warnings)
        self.assertTrue(PayloadValidation._at_condition_validation_messages('@.flag == false')[0])
