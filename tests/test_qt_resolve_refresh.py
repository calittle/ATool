"""Resolve item refresh uses OCCS downloads and displays the new cached data."""
import json
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QDate, QSettings, Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from atool_qt.data_actions import ResolveDialog
from atool_qt.occs import CommandResult
from atool_qt.session import PackageSession
from atool_qt.window import WorkspaceWindow
from tests import test_layout_resolver as resolver_fixtures


class ResolveRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        fixture = resolver_fixtures.LayoutResolverTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.cache = fixture.cache
        template = json.loads((self.cache / 'packages/Pkg/versions/v1/AssemblyTemplate.json').read_text())
        template['$$Id'] = 'Pkg'
        session = PackageSession.from_payload(template)
        session.map_data({'show': True, 'name': 'Alice', 'address': '123 Main St'}, 'data')
        self.window = WorkspaceWindow(QSettings(str(self.cache / 'qt.ini'), QSettings.Format.IniFormat))
        self.window.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
        # The dialog's cache entry, rather than the global setting, is used.
        self.window.comms.settings.payload['occs'] = {'comms_cache_dir': str(self.cache / 'other')}
        self.window.set_session(session)
        self.dialog = ResolveDialog(self.window)
        self.dialog.show()
        self.addCleanup(self.window.close)
        self.addCleanup(self.dialog.close)
        self.assertFalse(self.dialog.refresh_item_button.isEnabled())
        self.dialog.cache.setText(str(self.cache))
        self.dialog.date.setDate(QDate(2026, 10, 8))
        self.dialog.refresh_layouts()
        self.dialog.resolve()
        self.wait_for_jobs()

    def wait_for_jobs(self):
        deadline = time.monotonic() + 5
        while (self.window.local_jobs or self.dialog.refresh_job is not None) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertFalse(self.window.local_jobs)
        self.assertIsNone(self.dialog.refresh_job)

    def test_selection_commands_failure_and_close_cancellation(self):
        dialog = self.dialog
        document = dialog.tree.topLevelItem(0)
        layout = document.child(0)
        content = layout.child(0)
        for item, command, name, directory in (
            (document, 'get-document', 'Doc', 'documents'),
            (layout, 'get-layout', 'header', 'layouts'),
            (content, 'get-content', 'header-content', 'contents'),
        ):
            dialog.tree.setCurrentItem(item)
            self.assertTrue(dialog.refresh_item_button.isEnabled())
            with patch.object(self.window.comms, 'submit') as submit:
                dialog.refresh_item_button.click()
                submit.assert_called_once()
                self.assertEqual([command, name, '--output', str(self.cache / directory)], submit.call_args.args[0])
                self.assertEqual('resources', submit.call_args.kwargs['channel'])
                self.assertFalse(dialog.refresh_item_button.isEnabled())
                self.assertFalse(dialog.run_button.isEnabled())
                dialog.refresh_item()
                self.assertEqual(1, submit.call_count)
                submit.call_args.args[1](CommandResult(1, '', 'Download failed', None))
            self.assertEqual('Download failed', dialog.status.text())
            self.assertTrue(dialog.refresh_item_button.isEnabled())
            self.assertTrue(dialog.run_button.isEnabled())
            self.assertIn('Alice', str(dialog.result))

        for kind in ('condition', 'field', 'warning', 'loop', 'iteration'):
            item = QTreeWidgetItem([kind])
            item.setData(0, Qt.ItemDataRole.UserRole, {'kind': kind, 'name': 'test'})
            dialog.tree.addTopLevelItem(item)
            dialog.tree.setCurrentItem(item)
            self.assertFalse(dialog.refresh_item_button.isEnabled())
        dialog.tree.setCurrentItem(document)
        dialog.tree.clearSelection()
        self.assertFalse(dialog.refresh_item_button.isEnabled())
        with patch.object(self.window.comms, 'submit') as submit:
            dialog.refresh_item()
            submit.assert_not_called()
            dialog.tree.setCurrentItem(content)
            dialog.refresh_item_button.click()
            job = submit.return_value
            job.done = False
            dialog.close()
            job.cancel.assert_called_once()
            submit.call_args.args[1](CommandResult(-1, '', '', None, cancelled=True))
            self.assertIsNone(dialog.refresh_job)

    def test_download_updates_cache_and_resolved_tree(self):
        executable = self.cache / 'fake-occs'
        executable.write_text(
            '#!/usr/bin/env python3\n'
            'import sys, shutil\nfrom pathlib import Path\n'
            'args = sys.argv[1:]\n'
            'assert args[0:2] == ["get-content", "header-content"]\n'
            'cache = Path(args[args.index("--output") + 1])\n'
            f'shutil.copytree({str(self.cache / "contents/header-content")!r}, cache / "header-content")\n'
            'blob = cache / "header-content/versions/1.0/header-content.blob"\n'
            'blob.parent.mkdir(parents=True, exist_ok=True)\n'
            'blob.write_text("<p>Latest resource</p>")\n'
            'print("{\\"ok\\": true}")\n')
        executable.chmod(0o755)
        self.window.comms.settings.payload['occs']['cli_path'] = str(executable)
        dialog = self.dialog
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0).child(0).child(0))
        dialog.refresh_item_button.click()
        self.wait_for_jobs()
        self.assertIn('Latest resource', str(dialog.result))
        self.assertIn('Latest resource', dialog.report.toPlainText())
        self.assertEqual('header-content', dialog.tree.currentItem().text(0))
        self.assertTrue(dialog.refresh_item_button.isEnabled())
        self.assertTrue(dialog.save_button.isEnabled())


if __name__ == '__main__':
    unittest.main()
