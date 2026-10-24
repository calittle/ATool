"""Installed-app audit action, independent of preflight and edit permission."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from atool_qt.session import PackageSession
from atool_qt.user_settings import UserSettings


class JSONPathAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.window = WorkspaceWindow(QSettings(str(self.root / 'qt.ini'), QSettings.Format.IniFormat))
        settings = UserSettings(self.root / 'user.json')
        settings.payload['application']['confirm_on_quit'] = False
        self.window.comms.settings = settings
        self.addCleanup(self.close)

    def close(self):
        if self.window.editor:
            self.window.editor.saved = self.window.editor.snapshot()
        self.window.close()

    def open_template(self, path='$..rows.length()'):
        source = self.root / 'AT.json'
        source.write_text(json.dumps({'Fields': [{'Name': 'Count', 'Path': path}],
                                     'Meta': {'clause_library': [{'name': 'Clause', 'expression': '@.rows.length() > 0'}]}}))
        self.window.set_session(PackageSession.open(source))
        return source

    def test_menu_audits_with_preflight_off_and_testing_access_without_saving(self):
        window = self.window
        self.assertFalse(window.jsonpath_audit_action.isEnabled())
        source = self.open_template()
        window.shared_mode = 'testing'
        self.assertIs(False, window.comms.settings.get('check_jsonpath_length'))
        window.session.clauses[0]['expression'] = '$.rows.length() > 0'
        window.clauses.set_session(window.session)
        before = window.editor.snapshot()
        original = source.read_bytes()
        with patch.object(window, 'run_comms_operation') as remote:
            window.jsonpath_audit_action.trigger()
        report = window.jsonpath_audit_dialog.report.toPlainText()
        self.assertIn(window.jsonpath_audit_action, window.package_menu.actions())
        self.assertEqual('1 expression to review.', window.jsonpath_audit_dialog.summary.text())
        for expected in ('Count', '$.Fields[0].Path', '$..rows.length()', 'not confirmed defects'):
            self.assertIn(expected, report)
        self.assertNotIn('$.clause_library[0]', report)
        self.assertEqual(before, window.editor.snapshot())
        self.assertEqual(original, source.read_bytes())
        remote.assert_not_called()
        window.jsonpath_audit_dialog.copy_button.click()
        self.assertEqual(report, QApplication.clipboard().text())
        destination = self.root / 'report.txt'
        with patch('atool_qt.jsonpath_audit.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            window.jsonpath_audit_dialog.save_button.click()
        self.assertEqual(report + '\n', destination.read_text())

    def test_clean_audit_and_busy_guard(self):
        self.open_template('$.rows.length()')
        self.window.session.clauses = []
        self.window.clauses.set_session(self.window.session)
        with patch.object(self.window, 'package_busy', return_value=True):
            self.window.update_actions()
            self.assertFalse(self.window.jsonpath_audit_action.isEnabled())
            self.window.audit_jsonpaths()
        self.assertFalse(hasattr(self.window, 'jsonpath_audit_dialog'))
        self.window.update_actions()
        self.window.jsonpath_audit_action.trigger()
        self.assertIn('No matching', self.window.jsonpath_audit_dialog.summary.text())

    def test_audit_includes_pending_field_edit_and_cannot_export_over_template(self):
        source = self.open_template('$.rows.length()')
        self.window.select_name(self.window.fields, 'Count')
        self.window.fields.expression.setPlainText('$..pending.length()')
        self.window.jsonpath_audit_action.trigger()
        dialog = self.window.jsonpath_audit_dialog
        self.assertIn('$..pending.length()', dialog.report.toPlainText())
        original = source.read_bytes()
        with patch('atool_qt.jsonpath_audit.QFileDialog.getSaveFileName', return_value=(str(source), '')), \
                patch.object(self.window, 'report_error') as error:
            dialog.save_report()
        error.assert_called_once()
        self.assertEqual(original, source.read_bytes())
        with patch('atool_qt.jsonpath_audit.QFileDialog.getSaveFileName', return_value=('', '')):
            dialog.save_report()


if __name__ == '__main__':
    unittest.main()
