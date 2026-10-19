"""Mapped JSON editing, history, and workspace mapping integration."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QLineEdit
from PySide6.QtTest import QTest
from atool_qt.data_editing import display_path, path_parts
from atool_qt.session import PackageSession
from atool_qt.window import DataPanel, WorkspaceWindow


class DataEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = DataPanel()
        self.messages = []
        self.panel.message.connect(self.messages.append)
        self.panel.set_data({'odd.key': [{'value': False}, {'value': 0}], 'null': None})
        self.addCleanup(self.panel.close)

    def select(self, parts):
        item = self.panel.tree.topLevelItem(0)
        for key in parts:
            item.setExpanded(True)
            target = f'{item.data(0, Qt.ItemDataRole.UserRole + 1)}[{json.dumps(key)}]'
            item = next(item.child(i) for i in range(item.childCount())
                        if item.child(i).data(0, Qt.ItemDataRole.UserRole + 1) == target)
        self.panel.tree.setCurrentItem(item)

    def inline_editor(self):
        self.panel.resize(800, 450)
        self.panel.show()
        self.app.processEvents()
        tree = self.panel.tree
        item = tree.currentItem()
        tree.scrollToItem(item)
        point = tree.visualRect(tree.indexFromItem(item, 1)).center()
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.app.processEvents()
        editor = next((editor for editor in tree.findChildren(QLineEdit) if editor.isVisible()), None)
        self.assertIsNotNone(editor)
        return editor

    def test_double_click_edits_full_string_without_quotes_and_supports_undo(self):
        original = 'CHINESE' + 'x' * 43
        self.panel.set_data({'language': original})
        self.select(['language'])
        with patch.object(self.panel, 'json_dialog') as dialog:
            editor = self.inline_editor()
            self.assertEqual(editor.text(), original)
            editor.setText('123')
            QTest.keyClick(editor, Qt.Key.Key_Return)
            QTest.qWait(10)
            dialog.assert_not_called()
        self.assertEqual(self.panel.payload['language'], '123')
        self.assertEqual(json.loads(self.panel.value.toPlainText()), '123')
        self.panel.undo_data()
        self.assertEqual(self.panel.payload['language'], original)

    def test_long_value_opens_modal_on_double_click(self):
        original = 'x' * 51
        self.panel.set_data({'long': original})
        self.select(['long'])
        self.panel.resize(800, 450)
        self.panel.show()
        self.app.processEvents()
        tree = self.panel.tree
        point = tree.visualRect(tree.indexFromItem(tree.currentItem(), 1)).center()
        with patch.object(self.panel, 'json_dialog', return_value=('', 'edited')) as dialog:
            QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
            self.app.processEvents()
            dialog.assert_called_once_with('Edit JSON Value', original)
        self.assertEqual(self.panel.payload['long'], 'edited')
        self.assertFalse(any(editor.isVisible() for editor in tree.findChildren(QLineEdit)))

    def test_compact_toolbar_has_icons_and_no_edit_value_button(self):
        toolbar = self.panel.edit_toolbar
        self.assertNotIn(self.panel.edit_actions['Edit Value…'], toolbar.buttons)
        for action, button in toolbar.buttons.items():
            self.assertEqual(button.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.assertFalse(action.icon().isNull())
            self.assertEqual(button.accessibleName(), action.text())
            self.assertTrue(button.toolTip())

    def test_save_existing_writes_without_a_picker_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'mapped.json'
            target.write_text('{}')
            self.panel.save_target = lambda: target
            self.panel.replace_value({'language': 'CHINESE'})
            with patch('atool_qt.data_editing.QFileDialog.getSaveFileName') as picker:
                self.panel.edit_actions['Save'].trigger()
                picker.assert_not_called()
            self.assertEqual(json.loads(target.read_text()), self.panel.payload)
            self.assertTrue(self.panel.undo_stack)

    def test_save_without_existing_source_uses_save_as(self):
        with patch.object(self.panel, 'save_json') as save_as:
            self.panel.save_existing()
            save_as.assert_called_once()

    def test_inline_escape_and_invalid_number_leave_data_unchanged(self):
        self.select(['odd.key', 1, 'value'])
        editor = self.inline_editor()
        editor.setText('123')
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertEqual(self.panel.payload['odd.key'][1]['value'], 0)
        editor = self.inline_editor()
        editor.setText('not a number')
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.qWait(10)
        self.assertEqual(self.panel.payload['odd.key'][1]['value'], 0)
        self.assertIn('Could not edit value', self.messages[-1])
        self.assertEqual(self.panel.undo_stack, [])

    def test_inline_number_and_boolean_keep_types(self):
        self.select(['odd.key', 1, 'value'])
        editor = self.inline_editor()
        editor.setText('42.5')
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.qWait(10)
        self.assertEqual(self.panel.payload['odd.key'][1]['value'], 42.5)
        self.select(['odd.key', 0, 'value'])
        editor = self.inline_editor()
        editor.setText('true')
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.qWait(10)
        self.assertIs(self.panel.payload['odd.key'][0]['value'], True)

    def test_inline_search_result_updates_its_source(self):
        self.panel.set_data({'language': 'CHINESE'})
        self.panel.search.setText('CHINESE')
        self.panel.run_search()
        editor = self.inline_editor()
        editor.setText('ENGLISH')
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.qWait(10)
        self.assertEqual(self.panel.payload, {'language': 'ENGLISH'})

    def test_path_labels_keep_nested_array_and_parent_context(self):
        path = '$.billPrint.premise.premList[1].cmElements["descr"]'
        self.assertEqual(display_path(path), '$..cmElements["descr"]')
        self.assertEqual(display_path('$.billPrint.premise.premList[1].value'), '$..premList[1]["value"]')
        self.assertEqual(display_path('$["root"]["odd.key"]["quote\\\"key"]'),
                         '$..["odd.key"]["quote\\\"key"]')

    def test_ambiguous_search_labels_keep_indices_and_edit_correct_element(self):
        self.panel.set_data({'premises': [
            {'cmElements': {'descr': 'Energy Charge'}},
            {'cmElements': {'descr': 'Other Charge'}}]})
        self.panel.mode.setCurrentText('Full Text')
        self.panel.search.setText('Charge')
        self.panel.run_search()
        first, second = [self.panel.tree.topLevelItem(i) for i in range(2)]
        self.assertEqual(first.text(0), '$..premises[0]..cmElements["descr"]')
        self.assertEqual(second.text(0), '$..premises[1]..cmElements["descr"]')
        full_path = '$.premises[1].cmElements.descr'
        self.panel.tree.setCurrentItem(second)
        self.assertEqual(self.panel.path.text(), full_path)
        self.assertEqual(second.toolTip(0), full_path)
        from PySide6.QtWidgets import QPushButton
        next(button for button in self.panel.findChildren(QPushButton) if button.text() == 'Copy Path').click()
        self.assertEqual(self.app.clipboard().text(), full_path)
        editor = self.inline_editor()
        editor.setText('Updated Charge')
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.qWait(10)
        self.assertEqual(self.panel.payload['premises'][0]['cmElements']['descr'], 'Energy Charge')
        self.assertEqual(self.panel.payload['premises'][1]['cmElements']['descr'], 'Updated Charge')

    def test_expanded_search_container_shows_names_and_keeps_exact_paths(self):
        self.panel.set_data({'premise': {'details': {'cmElements': {
            'descr': 'Energy Charge', 'language': 'CHINESE', 'nested': [{'value': 1}]}}}})
        self.panel.mode.setCurrentText('JSONPath')
        self.panel.search.setText('$.premise.details.cmElements')
        self.panel.run_search()
        container = self.panel.tree.topLevelItem(0)
        container.setExpanded(True)
        self.assertEqual([container.child(i).text(0) for i in range(container.childCount())],
                         ['descr', 'language', 'nested'])
        language = container.child(1)
        self.panel.tree.setCurrentItem(language)
        full_path = '$.premise.details.cmElements["language"]'
        self.assertEqual(self.panel.path.text(), full_path)
        self.assertEqual(language.toolTip(0), full_path)
        editor = self.inline_editor()
        editor.setText('ENGLISH')
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.qWait(10)
        self.assertEqual(self.panel.payload['premise']['details']['cmElements']['language'], 'ENGLISH')
        self.select(['premise', 'details', 'cmElements', 'nested', 0, 'value'])
        leaf = self.panel.tree.currentItem()
        self.assertEqual(leaf.text(0), 'value')
        self.assertEqual(leaf.parent().text(0), '[0]')
        self.assertEqual(leaf.parent().parent().text(0), 'nested')

    def test_single_search_result_uses_compact_tail_and_full_path(self):
        self.panel.set_data({'premise': {'details': {'cmElements': {'descr': 'Energy Charge'}}}})
        self.panel.search.setText('Energy Charge')
        self.panel.run_search()
        item = self.panel.tree.topLevelItem(0)
        self.assertEqual(item.text(0), '$..cmElements["descr"]')
        self.assertEqual(self.panel.path.text(), '$.premise.details.cmElements.descr')

    def test_objects_and_arrays_keep_json_dialog(self):
        self.select(['odd.key'])
        with patch.object(self.panel, 'json_dialog', return_value=None) as dialog:
            self.panel.edit_cell(self.panel.tree.currentItem(), 1)
            dialog.assert_called_once()

    def test_nested_copy_paste_is_independent_and_array_delete_reindexes(self):
        self.select(['odd.key', 0])
        self.panel.copy_value()
        self.select(['odd.key'])
        self.panel.paste_value()
        self.assertEqual([{'value': False}, {'value': 0}, {'value': False}], self.panel.payload['odd.key'])
        self.select(['odd.key', 2, 'value'])
        self.panel.replace_value(True)
        self.assertFalse(self.panel.payload['odd.key'][0]['value'])
        self.select(['odd.key', 0])
        self.panel.remove_value()
        self.assertEqual([{'value': 0}, {'value': True}], self.panel.payload['odd.key'])
        self.select(['odd.key', 1, 'value'])
        self.assertEqual('true', self.panel.value.toPlainText())
        self.panel.undo_data()
        self.assertEqual(3, len(self.panel.payload['odd.key']))
        self.panel.redo_data()
        self.assertEqual(2, len(self.panel.payload['odd.key']))

    def test_root_replacement_null_and_history_reset(self):
        self.panel.replace_value([])
        self.panel.insert_value(None)
        self.assertEqual([None], self.panel.payload)
        self.panel.undo_data()
        self.assertEqual([], self.panel.payload)
        self.panel.undo_data()
        self.assertIn('odd.key', self.panel.payload)
        self.panel.set_data({'new': True})
        self.assertEqual([], self.panel.undo_stack)
        self.assertFalse(self.panel.edit_actions['Undo'].isEnabled())
        self.assertFalse(self.panel.edit_actions['Remove'].isEnabled())

    def test_search_edits_real_data_and_condition_cannot_be_edited(self):
        self.panel.mode.setCurrentText('Full Text')
        self.panel.search.setText('null')
        self.panel.run_search()
        self.panel.replace_value('changed')
        self.assertEqual('changed', self.panel.payload['null'])
        self.assertEqual('', self.panel.search.text())
        self.panel.mode.setCurrentText('Condition')
        self.panel.search.setText('@.null == "changed"')
        self.panel.run_search()
        for name in ('Edit Value…', 'Add…', 'Remove', 'Copy', 'Paste…'):
            self.assertFalse(self.panel.edit_actions[name].isEnabled())

    def test_duplicate_key_and_invalid_clipboard_do_not_mutate(self):
        original = json.dumps(self.panel.payload)
        with self.assertRaises(ValueError):
            self.panel.insert_value([], 'null')
        QApplication.clipboard().setText('NaN')
        self.panel.paste_value()
        self.assertEqual(original, json.dumps(self.panel.payload))
        self.assertIn('Could not paste', self.messages[-1])
        self.assertEqual([], self.panel.undo_stack)

    def test_sorted_tree_selects_inserted_key(self):
        self.panel.tree.setSortingEnabled(True)
        self.panel.tree.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self.panel.insert_value([1, 2], 'a')
        self.assertEqual('$["a"]', self.panel.path.text())
        self.assertEqual([1, 2], json.loads(self.panel.value.toPlainText()))

    def test_save_and_failed_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'edited.json'
            with patch('atool_qt.data_editing.QFileDialog.getSaveFileName', return_value=(str(target), '')):
                self.panel.save_json()
            self.assertEqual(self.panel.payload, json.loads(target.read_text()))
        self.panel.on_change = lambda _: (_ for _ in ()).throw(ValueError('mapping failed'))
        self.assertFalse(self.panel.replace_value(None))
        self.assertIn('odd.key', self.panel.payload)
        self.assertFalse(self.panel.undo_stack)

    def test_concrete_path_special_keys(self):
        self.assertEqual(['odd.key', 'quote"\\', 10, 'value'], path_parts('$["odd.key"]["quote\\\"\\\\"][10].value'))

    def test_workspace_remaps_fields_and_document_matches_and_undo(self):
        with tempfile.TemporaryDirectory() as directory:
            window = WorkspaceWindow(QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat))
            window.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
            self.addCleanup(window.close)
            session = PackageSession.from_payload({'Documents': [{'$$Id': 'Notice', 'Condition': '@.enabled == true'}],
                                                   'Fields': [{'Name': 'Enabled', 'Path': '$.enabled'}]})
            session.map_data({'enabled': False}, 'input.json')
            window.set_session(session)
            window.show()
            window.default_layout_pending = False
            window.show_panel('data')
            self.app.processEvents()
            window.data.tree.setCurrentItem(window.data.tree.topLevelItem(0).child(0))
            window.data.tree.editItem(window.data.tree.currentItem(), 1)
            editor = window.data.tree.findChild(QLineEdit)
            self.assertIsNotNone(editor)
            editor.setText('true')
            QTest.keyClick(editor, Qt.Key.Key_Return)
            QTest.qWait(10)
            self.assertIn('refreshed field values and document matches: 1 of 1 documents matched',
                          window.activity.toPlainText())
            self.assertTrue(session.documents[0]['triggered'])
            self.assertEqual([True], session.fields[0]['mapped_values'])
            self.assertEqual(session.data, window.data.payload)
            window.data.undo_data()
            self.assertFalse(session.documents[0]['triggered'])
            self.assertEqual([False], session.fields[0]['mapped_values'])
            window.data.redo_data()
            self.assertTrue(session.documents[0]['triggered'])


if __name__ == '__main__':
    unittest.main()
