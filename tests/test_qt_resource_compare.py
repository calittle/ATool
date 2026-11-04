"""Comparison UI delegates to CLI, handles partial evidence and keeps editing untouched."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem
from atool_qt.occs import CommandResult, CommsSettings
from atool_qt.resource_compare import ResourceCompareDialog
from atool_qt.session import demo_session
from atool_qt.user_settings import UserSettings
from atool_qt.window import WorkspaceWindow


class FakeJob:
    done = False
    cancelled = False
    def cancel(self):
        self.cancelled = True


class ResourceCompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.window = WorkspaceWindow(QSettings(str(self.root / 'qt.ini'), QSettings.Format.IniFormat))
        self.window.comms.settings = UserSettings(self.root / 'user.json')
        self.window.comms.settings.payload['application']['confirm_on_quit'] = False
        self.window.set_session(demo_session())
        self.calls = []
        self.runner = patch.object(self.window.comms, 'submit', side_effect=self.submit)
        self.runner.start()
        self.addCleanup(self.runner.stop)
        self.addCleanup(self.close)

    def submit(self, args, callback, **options):
        job = FakeJob()
        self.calls.append(dict(args=args, callback=callback, job=job, options=options))
        return job

    def close(self):
        for dialog in getattr(self.window, 'comparison_dialogs', []):
            dialog.close()
        self.window.confirm_discard = lambda: True
        self.window.close()
        self.app.clipboard().clear()

    def dialog(self, resource_type='Content', name='Example'):
        dialog = ResourceCompareDialog(self.window, resource_type, name)
        self.addCleanup(dialog.close)
        return dialog

    def complete(self, index, value, code=0):
        call = self.calls[index]
        call['job'].done = True
        call['callback'](CommandResult(code, '', '', value))

    def versions(self, index=0, names=('1.0', '2.0')):
        self.complete(index, {'ok': True, 'versions': [{'shortName': name} for name in names]})

    def result(self, index, complete=True):
        self.complete(index, {'ok': True, 'markdown': '# Resource comparison\n\nChanged content.\n',
                             'report': {'schemaVersion': 'occs-resource-comparison/v1', 'complete': complete,
                                        'result': 'different' if complete else 'incomplete'}}, 0 if complete else 2)

    def test_live_versions_report_copy_save_and_selected_session(self):
        d = self.dialog()
        self.assertFalse(d.compare_button.isEnabled())
        d.load_versions()
        self.assertEqual(['compare', 'content', 'Example', '--list-versions', '--json'], self.calls[0]['args'])
        self.versions()
        self.assertEqual('1.0', d.before_version.currentText())
        self.assertEqual('2.0', d.after_version.currentText())
        d.compare()
        self.assertEqual(['compare', 'content', 'Example', '--from-version', '1.0', '--to-version', '2.0', '--json'], self.calls[1]['args'])
        self.assertEqual('read', self.calls[1]['options']['channel'])
        self.result(1)
        self.assertIn('Changed content', d.report.toPlainText())
        d.copy_button.click()
        self.assertEqual(d.markdown, self.app.clipboard().text())
        output = self.root / 'report.md'
        with patch('atool_qt.resource_compare.QFileDialog.getSaveFileName', return_value=(str(output), '')):
            d.save_report()
        self.assertEqual(d.markdown, output.read_text())
        settings = CommsSettings(self.root / 'isolated.json')
        settings.payload = {'occs': {'session_alias': 'my tenancy'}}
        args = settings.command(self.calls[1]['args'])
        self.assertEqual('my tenancy', args[args.index('--session') + 1])
        self.assertEqual('Sample billing package', self.window.session.name)

    def test_technical_appendix_is_opt_in_and_requests_fresh_report(self):
        d = self.dialog()
        d.load_versions()
        self.versions()
        d.compare()
        self.assertNotIn('--include-technical', self.calls[1]['args'])
        self.result(1)
        d.include_technical.setChecked(True)
        self.assertEqual('', d.markdown)
        self.assertFalse(d.save_button.isEnabled())
        d.compare()
        self.assertIn('--include-technical', self.calls[2]['args'])

    def test_context_version_prefers_a_useful_pair(self):
        d = ResourceCompareDialog(self.window, 'Content', 'Example', '1.0')
        self.addCleanup(d.close)
        d.load_versions()
        self.versions(0, ('1.0', '2.0', '3.0'))
        self.assertEqual('1.0', d.before_version.currentText())
        self.assertEqual('3.0', d.after_version.currentText())
        d.preferred_version = '2.0'
        d.load_versions()
        self.versions(1, ('1.0', '2.0', '3.0'))
        self.assertEqual('1.0', d.before_version.currentText())
        self.assertEqual('2.0', d.after_version.currentText())

    def test_snapshot_modes_and_partial_evidence_report(self):
        d = self.dialog('Layout')
        self.assertEqual('snapshots', d.mode.currentData())
        self.assertFalse(d.mode.isEnabled())
        d.before_cache.setText('/before')
        d.after_cache.setText('/after')
        d.compare()
        self.assertEqual(['compare', 'layout', 'Example', '--from-cache', '/before', '--to-cache', '/after', '--json'], self.calls[0]['args'])
        self.result(0, False)
        self.assertIn('incomplete', d.status.text())
        self.assertTrue(d.save_button.isEnabled())
        d = self.dialog('Document')
        d.mode.setCurrentIndex(2)
        d.before_cache.setText('/before')
        d.after_cache.setText('/after')
        d.load_versions()
        self.assertIn('/before', self.calls[1]['args'])
        self.assertIn('/after', self.calls[2]['args'])
        self.versions(2, ('2.0', '3.0'))
        self.assertFalse(d.compare_button.isEnabled())
        self.versions(1, ('1.0',))
        self.assertEqual('1.0', d.before_version.currentText())
        self.assertEqual('3.0', d.after_version.currentText())
        d.compare()
        self.assertIn('--from-cache', self.calls[3]['args'])
        self.assertIn('--to-version', self.calls[3]['args'])

    def test_cancel_source_changes_and_invalid_cli_responses_do_not_show_stale_results(self):
        d = self.dialog()
        d.load_versions()
        d.cancel()
        self.assertTrue(self.calls[0]['job'].cancelled)
        self.versions()
        self.assertEqual(0, d.before_version.count())
        d.load_versions()
        self.versions(1)
        d.compare()
        d.resource_name.setText('Different')
        self.result(2)
        self.assertEqual('', d.markdown)
        d.load_versions()
        self.complete(3, {'ok': False, 'error': "unknown command 'compare'"}, 1)
        self.assertIn('updated CLI', d.status.text())
        d.load_versions()
        self.complete(4, {'versions': 'invalid'})
        self.assertIn('invalid version list', d.status.text())

    def test_context_menus_supply_resource_names_and_disable_mixed_selection(self):
        w = self.window
        w.layouts.show_cached.setChecked(False)
        w.layouts.matched_only.setChecked(False)
        entries = [(w.documents.tree, w.documents.tree.topLevelItem(0), 'Document')]
        entries += [(w.layouts.tree, item, item.data(0, Qt.ItemDataRole.UserRole)['kind'])
                    for item in w.layouts.items() if item.data(0, Qt.ItemDataRole.UserRole)['kind'] in ('Layout', 'Content')]
        content = QTreeWidgetItem(['Remote Content', 'Text'])
        w.content.browser.addTopLevelItem(content)
        entries.append((w.content.browser, content, 'Content'))
        for tree, item, resource_type in entries:
            tree.clearSelection()
            tree.setCurrentItem(item)
            menu = w.context_menus.tree_menu(tree, item, 0)
            action = next(action for action in menu.actions() if action.text() == 'Compare Versions…')
            with patch.object(w, 'compare_versions') as compare:
                action.trigger()
            compare.assert_called_once_with(resource_type, item.text(0), '')
        rows = [item for item in w.layouts.items() if item.data(0, Qt.ItemDataRole.UserRole)['kind'] == 'Layout']
        w.layouts.tree.clearSelection()
        w.layouts.tree.setCurrentItem(rows[0])
        rows[1].setSelected(True)
        menu = w.context_menus.tree_menu(w.layouts.tree, rows[0], 0)
        action = next(action for action in menu.actions() if action.text() == 'Compare Versions…')
        self.assertFalse(action.isEnabled())
