"""Native runtimes work without system Python, Node, or a writable app folder."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atool_qt.occs import CommsSettings
from atool_qt.runtime import bundled_runtime


class NativeRuntimeTests(unittest.TestCase):
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
            path.write_text(json.dumps({'occs': {'cli_path': '/custom/occs.js', 'session_alias': 'chosen'}}))
            settings = CommsSettings(path)
            with patch('atool_qt.occs.bundled_runtime', return_value=root / 'runtime'):
                self.assertEqual('/custom/occs.js', settings.cli)
                self.assertEqual(['package', '--session', 'chosen', 'list'], settings.command(['package', 'list'])[2:])
            with patch('atool_qt.occs.bundled_runtime', return_value=None):
                self.assertEqual('node', settings.command(['package'])[0])

    def test_bundle_root_is_used_only_for_frozen_executables(self):
        with patch('sys.frozen', True, create=True), patch('sys._MEIPASS', '/native/root', create=True):
            self.assertEqual(Path('/native/root/runtime'), bundled_runtime())
        with patch('sys.frozen', False, create=True):
            self.assertIsNone(bundled_runtime())
