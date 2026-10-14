"""Native runtimes work without system Python, Node, or a writable app folder."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atool_qt.occs import CommsSettings
from atool_qt.runtime import bundled_runtime, start_new_instance


class NativeRuntimeTests(unittest.TestCase):
    def test_new_native_instance_uses_executable_and_independent_environment(self):
        from PySide6.QtCore import QProcessEnvironment
        environment = QProcessEnvironment()
        environment.insert('ATOOL_TEST_SETTING', 'preserved')
        with patch('sys.frozen', True, create=True), patch('sys.executable', '/Apps/ATool App/ATool'), \
                patch('PySide6.QtCore.QProcess') as process_class, \
                patch('PySide6.QtCore.QProcessEnvironment.systemEnvironment', return_value=environment):
            process = process_class.return_value
            process.startDetached.return_value = True
            self.assertTrue(start_new_instance())
            process.setProgram.assert_called_once_with('/Apps/ATool App/ATool')
            process.setArguments.assert_not_called()
            actual = process.setProcessEnvironment.call_args.args[0]
            self.assertEqual(actual.value('PYINSTALLER_RESET_ENVIRONMENT'), '1')
            self.assertEqual(actual.value('ATOOL_TEST_SETTING'), 'preserved')

    def test_new_source_instance_uses_absolute_entrypoint_without_current_package_arguments(self):
        with patch('sys.frozen', False, create=True), patch('sys.executable', '/Python Path/python'), \
                patch('sys.argv', ['ATool_Qt.py', '--package', 'existing.json']), \
                patch('PySide6.QtCore.QProcess') as process_class:
            process = process_class.return_value
            process.startDetached.return_value = False
            self.assertFalse(start_new_instance())
            process.setProgram.assert_called_once_with('/Python Path/python')
            process.setArguments.assert_called_once_with([str(Path(__file__).resolve().parents[1] / 'ATool_Qt.py')])
            process.setProcessEnvironment.assert_not_called()

    def test_frozen_cli_and_node_use_bundle_paths_with_spaces_and_writable_user_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'ATool Application' / 'runtime'
            user = root / 'user'
            user.mkdir()
            settings = CommsSettings(root / 'absent.json')
            with patch('atool_qt.occs.bundled_runtime', return_value=runtime), patch.object(Path, 'home', return_value=user):
                command = settings.command(['package', 'list'])
                self.assertEqual(str(runtime / 'node' / ('node.exe' if os.name == 'nt' else 'node')), command[0])
                self.assertEqual(str(runtime / 'occs-cli/bin/occs.js'), command[1])
                self.assertEqual(['package', 'list'], command[2:])
                self.assertEqual(str(user / '.atool/cli-work'), settings.cwd)
                self.assertTrue(Path(settings.cwd).is_dir())
                self.assertFalse(runtime.exists())

    def test_configured_cli_override_and_session_alias_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'settings.json'
            custom_cli = root / 'custom CLI' / 'occs.js'
            path.write_text(json.dumps({'occs': {'cli_path': str(custom_cli), 'session_alias': 'chosen'}}))
            settings = CommsSettings(path)
            with patch('atool_qt.occs.bundled_runtime', return_value=root / 'runtime'):
                self.assertEqual(str(custom_cli), settings.cli)
                self.assertEqual(['package', '--session', 'chosen', 'list'], settings.command(['package', 'list'])[2:])
            with patch('atool_qt.occs.bundled_runtime', return_value=None):
                self.assertEqual('node', settings.command(['package'])[0])

    def test_bundle_root_is_used_only_for_frozen_executables(self):
        with patch('sys.frozen', True, create=True), patch('sys._MEIPASS', '/native/root', create=True):
            self.assertEqual(Path('/native/root/runtime'), bundled_runtime())
        with patch('sys.frozen', False, create=True):
            self.assertIsNone(bundled_runtime())
