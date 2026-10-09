"""State, save, and user-control checks for the editable Qt workspace."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atool_qt.editor import PackageEditor
from atool_qt.session import PackageSession

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:
    QApplication = None


def editable_session():
    return PackageSession.from_payload({"$$Id": "Package", "Unknown": {"preserve": True}, "Documents": [
        {"$$Id": "Doc", "Condition": "$[?(@.enabled == true)]", "Layouts": [{"$$Id": "L1", "Contents": []}, {"$$Id": "L2"}]}],
        "Fields": [{"Name": "Amount", "Path": "$.amount", "Mandatory": False, "Custom": 5}],
        "Meta": {"Other": 42, "clause_library": [{"name": "enabled", "expression": "@.enabled == true"}]}})


class EditorTests(unittest.TestCase):
    def test_edits_undo_redo_and_mapping_keep_one_model(self):
        session = editable_session()
        session.map_data({"enabled": True, "amount": 0}, "data")
        editor = PackageEditor(session)
        self.assertFalse(editor.dirty)
        revision = session.mapping_revision
        editor.update_record(session.fields[0], {"Name": "Charge", "Mandatory": True}, "fields")
        self.assertEqual([0], session.fields[0]["mapped_values"])
        self.assertEqual(revision, session.mapping_revision)
        self.assertTrue(editor.dirty)
        self.assertEqual("Charge", session.fields[0]["name"])
        editor.undo()
        self.assertFalse(editor.dirty)
        self.assertEqual("Amount", session.fields[0]["name"])
        editor.redo()
        self.assertEqual("Charge", session.fields[0]["name"])
        editor.update_record(session.documents[0], {"Condition": "@.enabled == false"}, "documents")
        self.assertFalse(session.documents[0]["triggered"])

    def test_save_preserves_unknown_fields_backup_and_concurrent_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "AT.json"
            session = editable_session()
            editor = PackageEditor(session)
            editor.save(path)
            saved = json.loads(path.read_text())
            self.assertEqual({"preserve": True}, saved["Unknown"])
            self.assertEqual(42, saved["Meta"]["Other"])
            self.assertEqual(5, saved["Fields"][0]["Custom"])
            editor.add_record("fields")
            before = path.read_bytes()
            editor.save()
            backups = list(path.parent.glob("AT_backup_*.json"))
            self.assertEqual(1, len(backups))
            self.assertEqual(before, backups[0].read_bytes())
            self.assertFalse(editor.dirty)
            path.write_text('{"Documents": []}')
            with self.assertRaisesRegex(ValueError, "changed outside"):
                editor.save()
            self.assertEqual('{"Documents": []}', path.read_text())

    def test_layout_crud_move_and_iteration_preserve_structure(self):
        session = editable_session()
        editor = PackageEditor(session)
        doc = session.documents[0]
        key = editor.move_layout_item(doc, "layout/1", -1)
        self.assertEqual("layout/0", key)
        self.assertEqual("L2", doc["source"]["Layouts"][0]["$$Id"])
        key = editor.add_layout_item(session.documents[0], "Content", "layout/0")
        iteration = editor.add_layout_item(session.documents[0], "Iteration", key)
        field = editor.add_layout_item(session.documents[0], "Field", iteration)
        editor.update_layout(session.documents[0], field, {"Path": "$.amount"})
        self.assertEqual("$.amount", editor.layout_source(session.documents[0], field)[0]["Path"])
        editor.remove_layout_item(session.documents[0], iteration)
        self.assertNotIn("Iteration", editor.layout_source(session.documents[0], key)[0])
        editor.undo()
        self.assertEqual("$.amount", editor.layout_source(session.documents[0], field)[0]["Path"])

    def test_invalid_change_rolls_back_and_clause_cycles_do_not_commit(self):
        session = editable_session()
        editor = PackageEditor(session)
        original = editor.snapshot()
        with self.assertRaises(ValueError):
            editor.update_record(session.fields[0], {"Name": ""}, "fields")
        with self.assertRaisesRegex(ValueError, "cycle"):
            editor.save_clause("enabled", "enabled", "", "CLAUSE{enabled}")
        self.assertEqual(original, editor.snapshot())
        self.assertEqual([], editor.undo_stack)


@unittest.skipIf(QApplication is None, "Install requirements-qt.txt")
class AuthoringInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = WorkspaceWindow(QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat))
        self.window.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
        self.window.show()
        self.window.set_session(editable_session())
        self.addCleanup(self.finish)

    def finish(self):
        with patch("atool_qt.authoring.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard):
            self.window.close()

    def test_buttons_edit_records_and_menu_undo_redo_save(self):
        window = self.window
        panel = window.fields
        panel.name.setText("Charge")
        panel.required.setChecked(True)
        next(action for action in panel.authoring_toolbar.actions() if action.text() == "Apply").trigger()
        self.assertEqual("Charge", window.session.fields[0]["name"])
        self.assertTrue(window.session.fields[0]["mandatory"])
        window.undo_action.trigger()
        self.assertEqual("Amount", window.session.fields[0]["name"])
        window.redo_action.trigger()
        self.assertEqual("Charge", window.session.fields[0]["name"])
        path = Path(self.temp.name) / "saved.json"
        with patch("atool_qt.authoring.QFileDialog.getSaveFileName", return_value=(str(path), "JSON")):
            window.save_action.trigger()
        self.assertEqual("Charge", json.loads(path.read_text())["Fields"][0]["Name"])
        self.assertFalse(window.editor.dirty)

    def test_composer_applies_to_document_and_can_undo(self):
        window = self.window
        window.clauses.compose.setPlainText("enabled OR RAW{@.amount > 0}")
        window.apply_composed()
        self.assertEqual("$[?(@.enabled == true || @.amount > 0)]", window.session.documents[0]["condition"])
        window.undo_change()
        self.assertEqual("$[?(@.enabled == true)]", window.session.documents[0]["condition"])

    def test_dirty_close_can_cancel_without_losing_changes(self):
        self.window.add_record("fields")
        with patch("atool_qt.authoring.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.window.close())
        self.assertTrue(self.window.editor.dirty)
        self.assertEqual(2, len(self.window.session.fields))

    def test_save_commits_visible_property_forms_without_apply(self):
        window = self.window
        window.fields.name.setText("UncommittedCharge")
        window.layouts.name.setText("EditedLayout")
        path = Path(self.temp.name) / "saved.json"
        with patch("atool_qt.authoring.QFileDialog.getSaveFileName", return_value=(str(path), "JSON")):
            self.assertTrue(window.save_package())
        saved = json.loads(path.read_text())
        self.assertEqual("UncommittedCharge", saved["Fields"][0]["Name"])
        self.assertEqual("EditedLayout", saved["Documents"][0]["Layouts"][0]["$$Id"])

    def test_property_focus_commit_and_checkbox_update_model(self):
        from PySide6.QtTest import QTest
        window = self.window
        window.show_panel("fields")
        self.app.processEvents()
        window.fields.name.setFocus()
        window.fields.name.setText("AutoCharge")
        window.fields.search.setFocus()
        QTest.qWait(10)
        self.assertEqual("AutoCharge", window.session.fields[0]["name"])
        window.fields.required.click()
        self.assertTrue(window.session.fields[0]["mandatory"])
        window.fields.description.setFocus()
        window.fields.description.setPlainText("Saved on focus change")
        window.fields.search.setFocus()
        QTest.qWait(10)
        self.assertEqual("Saved on focus change", window.session.fields[0]["descr"])

    def test_data_search_modes_and_manager_path_controls(self):
        window = self.window
        session = editable_session()
        session.map_data({"enabled": True, "amount": 0, "rows": [{"label": "Alpha"}, {"label": "Beta"}]}, "data")
        window.set_session(session)
        browser = window.data
        from PySide6.QtWidgets import QPushButton
        controls = {button.text(): button for button in browser.findChildren(QPushButton)}
        browser.mode.setCurrentText("JSONPath")
        browser.search.setText("$.rows[*].label")
        controls['Search'].click()
        self.assertEqual(2, browser.tree.topLevelItemCount())
        self.assertEqual("$.rows[0].label", browser.path.text())
        self.assertEqual('"Alpha"', browser.value.toPlainText())
        browser.mode.setCurrentText("Full Text")
        browser.search.setText("beta")
        controls['Search'].click()
        self.assertEqual("$.rows[1].label", browser.path.text())
        browser.mode.setCurrentText("Condition")
        browser.search.setText("@.amount == 0")
        controls['Search'].click()
        self.assertEqual("Condition: PASS", browser.status.text())
        self.assertEqual("true", browser.value.toPlainText())
        window.browse_field_path()
        self.assertEqual("JSONPath", browser.mode.currentText())
        self.assertEqual("$.amount", browser.search.text())
        self.assertEqual("0", browser.value.toPlainText())
        controls['Copy Path'].click()
        self.assertEqual(QApplication.clipboard().text(), '$.amount')
        controls['Clear'].click()
        self.assertEqual("$", browser.path.text())

    def test_layout_controls_copy_move_and_paste_preserve_selection(self):
        window = self.window
        window.select_layout_key("layout/1")
        window.move_layout_item(-1)
        self.assertEqual("L2", window.layouts.name.text())
        window.copy_layout()
        window.paste_layout()
        self.assertEqual(3, len(window.session.payload["Documents"][0]["Layouts"]))
        self.assertEqual("L2 Copy", window.layouts.name.text())

    def test_initial_layout_properties_are_editable_and_iteration_type_validated(self):
        window = self.window
        doc = window.session.documents[0]
        window.editor.update_layout(doc, 'layout/0', {'Type': 'Block'})
        window.refresh_edit()
        box = window.layouts.property_controls['Type']
        self.assertTrue(box.isEnabled())
        self.assertTrue(box.isEditable())
        self.assertEqual('Block', box.currentText())
        content = window.editor.add_layout_item(window.session.documents[0], 'Content', 'layout/0')
        iteration = window.editor.add_layout_item(window.session.documents[0], 'Iteration', content)
        before = window.editor.snapshot()
        with self.assertRaisesRegex(ValueError, 'Iteration Type'):
            window.editor.update_layout(window.session.documents[0], iteration, {'Type': 'Array'})
        self.assertEqual(before, window.editor.snapshot())
        window.refresh_edit()
        window.select_layout_key(iteration)
        box = window.layouts.property_controls['Type']
        self.assertTrue(box.isEnabled())
        self.assertFalse(box.isEditable())
        # The original creates Array iterations but offers Iterator/Spliterator
        # when changing the type. Keep the current legacy value visible.
        self.assertEqual({'Array', 'Iterator', 'Spliterator'}, {box.itemText(i) for i in range(box.count())})


class PublishHistoryValueTests(unittest.TestCase):
    def test_reorder_remove_and_add_retain_refreshed_named_item_metadata(self):
        from atool_qt.editor import rebase_history_value
        base = [{'Name': 'A', 'value': 1}, {'Name': 'B', 'value': 2}]
        refreshed = [{'Name': 'A', 'value': 1, 'uuid': 'new-a'}, {'Name': 'B', 'value': 2, 'uuid': 'new-b'}, {'Name': 'ServerOnly', 'value': 3}]
        historical = [{'Name': 'B', 'value': 9}, {'Name': 'Added', 'value': 4}]
        result = rebase_history_value(base, historical, refreshed)
        self.assertEqual([item['Name'] for item in result], ['B', 'Added', 'ServerOnly'])
        self.assertEqual(result[0], {'Name': 'B', 'value': 9, 'uuid': 'new-b'})
        self.assertEqual(refreshed[0]['uuid'], 'new-a')

    def test_unchanged_and_deleted_keys_and_positional_nested_collections(self):
        from atool_qt.editor import rebase_history_value
        base = {'kept': 1, 'removed': 2, 'rows': [{'value': 1}]}
        historical = {'kept': 1, 'rows': [{'value': 5}]}
        refreshed = {'kept': 7, 'removed': 2, 'new': 3, 'rows': [{'value': 1, 'uuid': 'server'}]}
        self.assertEqual(rebase_history_value(base, historical, refreshed), {'kept': 7, 'new': 3, 'rows': [{'value': 5, 'uuid': 'server'}]})


if __name__ == "__main__":
    unittest.main()
