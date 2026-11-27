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

    def test_selector_advice_tracks_mapped_data_without_replacing_paths(self):
        path = "$.concat($.rows[*].amount, '')"
        self.open_template(path)
        window = self.window
        self.assertIn('Map a data file', window.activity.toPlainText())
        window.session.map_data({'rows': [{'amount': 10}]}, 'arrays.json')
        window.refresh_edit()
        self.assertIn('Prefer [0:]', window.activity.toPlainText())
        before = window.editor.snapshot()
        window.audit_jsonpaths()
        report = window.jsonpath_audit_dialog.report.toPlainText()
        self.assertIn('arrays.json', report)
        self.assertIn('Prefer [0:]', report)
        self.assertEqual(before, window.editor.snapshot())
        window.session.map_data({'rows': {'first': {'amount': 10}}}, 'objects.json')
        window.refresh_edit()
        self.assertIn('Keep [*]', window.activity.toPlainText())
        self.assertEqual(path, window.fields.expression.toPlainText())
        # Editing the expression refreshes the warning before applying it.
        window.fields.expression.setPlainText("$.concat($.rows[0:].amount, '')")
        self.assertIn('returns no matches', window.activity.toPlainText())
        window.fields.expression.setPlainText(path)
        window.data.mode.setCurrentText('JSONPath')
        window.data.search.setText('$.rows[*].amount')
        window.data.run_search()
        self.assertIn('Keep [*]', window.activity.toPlainText())
        window.data.search.setText('$.rows[0:].amount')
        window.data.run_search()
        self.assertIn('returns no matches', window.activity.toPlainText())
        self.assertEqual(0, window.data.tree.topLevelItemCount())

    def test_validation_activity_indicator_deduplication_and_resolution(self):
        path = "$.concat($.rows[*].amount, '')"
        self.open_template(path)
        window = self.window
        window.show()
        self.app.processEvents()
        self.assertFalse(window.validation_indicator.isHidden())
        self.assertEqual('!', window.validation_indicator.text())
        self.assertIn('Validation issues, see Activity panel', window.validation_indicator.toolTip())
        self.assertIn('color: #c52323', window.validation_indicator.styleSheet())
        for panel in (window.fields, window.documents, window.layouts, window.data):
            self.assertFalse(hasattr(panel, 'path_advice'))
        before = window.activity.toPlainText().count('Validation · $.Fields[0].Path:')
        window.refresh_edit()
        window.refresh_edit()
        self.assertEqual(before, window.activity.toPlainText().count('Validation · $.Fields[0].Path:'))
        window.activity.clear()
        window.validation_indicator.click()
        self.app.processEvents()
        self.assertTrue(window.docks['activity'].isVisible())
        self.assertIn('Validation · $.Fields[0].Path:', window.activity.toPlainText())
        window.session.map_data({'rows': [{'amount': 10}]}, 'arrays.json')
        window.refresh_edit()
        window.fields.expression.setPlainText("$.concat($.rows[0:].amount, '')")
        window.apply_record('fields')
        window.refresh_edit()
        self.assertTrue(window.validation_indicator.isHidden())
        # History remains available after the current issue is fixed.
        self.assertIn('Prefer [0:]', window.activity.toPlainText())
        window.data.mode.setCurrentText('JSONPath')
        window.data.search.setText('$.rows[*]')
        window.data.run_search()
        self.assertFalse(window.validation_indicator.isHidden())
        window.data.clear_search()
        self.assertTrue(window.validation_indicator.isHidden())
        window.data.search.setText('$. rows')
        window.data.run_search()
        self.assertFalse(window.validation_indicator.isHidden())
        window.data.clear_search()
        self.assertTrue(window.validation_indicator.isHidden())
        window.set_session(PackageSession.from_payload({'Fields': [], 'Documents': []}))
        self.assertEqual({}, window.validation_messages)
        self.assertTrue(window.validation_indicator.isHidden())

    def test_rejected_edit_reports_validation_in_activity_without_a_popup(self):
        self.open_template('$.amount')
        window = self.window
        original = window.session.fields[0]['path']
        window.fields.expression.setPlainText('$. amount')
        with patch('atool_qt.window.QMessageBox.warning') as popup:
            window.apply_record('fields')
        popup.assert_not_called()
        self.assertEqual(original, window.session.fields[0]['path'])
        self.assertIn('Whitespace', window.activity.toPlainText())
        self.assertFalse(window.validation_indicator.isHidden())
        window.fields.expression.setPlainText('$.amount')
        window.refresh_edit()
        self.assertTrue(window.validation_indicator.isHidden())

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
