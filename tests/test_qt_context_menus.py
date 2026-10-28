"""Behavioral coverage for manager, dialog, and keyboard context-menu targets."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QContextMenuEvent, QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QTreeWidgetItem, QWidget

from atool_qt.context_menus import select_target
from atool_qt.session import PackageSession
from atool_qt.user_settings import SettingsDialog, UserSettings
from atool_qt.window import WorkspaceWindow


def action(menu, label):
    return next(entry for entry in menu.actions() if entry.text() == label)


class ContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        popup = patch('atool_qt.context_menus.WorkspaceContextMenus.exec_menu', return_value=None)
        popup.start()
        self.addCleanup(popup.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.window = WorkspaceWindow(QSettings(str(root / 'qt.ini'), QSettings.Format.IniFormat))
        self.window.comms.settings = UserSettings(root / 'user.json')
        self.window.comms.settings.payload['application']['confirm_on_quit'] = False
        self.session = PackageSession.from_payload({
            '$$Id': 'Context Fixture',
            'Documents': [{ '$$Id': 'Notice', 'Descr': 'A document description', 'Condition': '@.ok',
                'Layouts': [{ '$$Id': 'Header', 'Contents': [{ '$$Id': 'Body',
                    'Iteration': {'$$Id': 'Rows', 'Path': '$.rows', 'Type': 'Iterator',
                                  'Fields': [{'Name': 'RowValue', 'Path': '$.value'}]}}]},
                            {'$$Id': 'Footer', 'Contents': []}]}],
            'Fields': [{'Name': 'Amount', 'Path': '$.amount', 'Descr': 'Amount description'},
                       {'Name': 'Account', 'Path': '$.account'}],
            'Meta': {'clause_library': [{'name': 'is_ok', 'expression': '@.ok', 'description': 'OK'}]},
        })
        self.session.map_data({'ok': True, 'amount': 'x' * 300, 'account': 'A', 'rows': [{'value': 3}]}, 'fixture.json')
        self.window.set_session(self.session)
        self.window.layouts.matched_only.setChecked(False)
        self.window.show()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.app.clipboard().clear()
        with patch.object(self.window, 'confirm_discard', return_value=True):
            self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def menu(self, tree, item, column=0, *, select=True):
        if select:
            select_target(tree, item)
        menu = self.window.context_menus.tree_menu(tree, item, column)
        self.addCleanup(menu.deleteLater)
        return menu

    def layout(self, name):
        return next(row for row in self.window.layouts.items() if row.data(0, Qt.ItemDataRole.UserRole + 4) == name)

    def test_right_press_preserves_multi_selection_and_does_not_activate(self):
        tree = self.window.fields.tree
        tree.selectAll()
        selected = set(tree.selectedItems())
        clicked = []
        tree.itemClicked.connect(lambda *_: clicked.append(True))
        self.window.show_panel('fields')
        self.app.processEvents()
        item = tree.topLevelItem(0)
        QTest.mousePress(tree.viewport(), Qt.MouseButton.RightButton, pos=tree.visualItemRect(item).center())
        QTest.mouseRelease(tree.viewport(), Qt.MouseButton.RightButton, pos=tree.visualItemRect(item).center())
        self.assertEqual(set(tree.selectedItems()), selected)
        self.assertEqual(clicked, [])

    def test_blank_document_menu_cannot_remove_previous_document(self):
        tree = self.window.documents.tree
        menu = self.menu(tree, None)
        self.assertIsNone(tree.currentItem())
        self.assertNotIn('Remove from Assembly Template…', [entry.text() for entry in menu.actions()])
        self.assertTrue(action(menu, 'Add Assembly Template Document').isEnabled())

    def test_copy_full_values_ignores_display_truncation_and_tooltip_description(self):
        tree = self.window.fields.tree
        item = next(row for row in self.window.fields.items() if row.data(0, Qt.ItemDataRole.UserRole + 4) == 'Amount')
        menu = self.menu(tree, item, 0)
        action(menu, 'Copy Cell').trigger()
        self.assertEqual(self.app.clipboard().text(), 'Amount')
        menu = self.menu(tree, item, 1)
        action(menu, 'Copy Cell').trigger()
        self.assertEqual(json.loads(self.app.clipboard().text()), ['x' * 300])

    def test_sorted_row_commands_use_record_identity(self):
        tree = self.window.fields.tree
        header = self.window.context_menus.header_menu(tree.header(), 0)
        self.addCleanup(header.deleteLater)
        original = copy.deepcopy(self.session.payload)
        action(header, 'Sort Descending').trigger()
        menu = self.menu(tree, tree.topLevelItem(0))
        action(menu, 'Copy Names').trigger()
        self.assertEqual(self.app.clipboard().text(), 'Amount')
        self.assertEqual(self.session.payload, original)

    def test_multi_field_definition_copy_then_blank_space_paste_and_undo(self):
        tree = self.window.fields.tree
        tree.selectAll()
        menu = self.menu(tree, tree.currentItem())
        self.assertFalse(action(menu, 'Remove Field…').isEnabled())
        action(menu, 'Copy Field Definitions').trigger()
        self.assertEqual(len(json.loads(self.app.clipboard().text())['Fields']), 2)
        original = copy.deepcopy(self.session.payload['Fields'])
        menu = self.menu(tree, None)
        action(menu, 'Paste Field Definitions').trigger()
        self.assertEqual(len(self.session.fields), 4)
        self.window.undo_change()
        self.assertEqual(self.session.payload['Fields'], original)

    def test_multi_favorite_command_writes_once_and_does_not_edit_package(self):
        tree = self.window.fields.tree
        tree.selectAll()
        menu = self.menu(tree, tree.currentItem())
        with patch.object(self.window.comms.settings, 'save', wraps=self.window.comms.settings.save) as save:
            action(menu, 'Add to Favorites').trigger()
            self.assertEqual(save.call_count, 1)
        self.assertEqual(set(self.window.package_favorites()['fields']), {'Account', 'Amount'})
        self.assertFalse(self.window.editor.dirty)
        self.assertEqual(self.window.favorites.tree.topLevelItemCount(), 2)

    def test_layout_moves_disable_sibling_boundaries(self):
        tree = self.window.layouts.tree
        menu = self.menu(tree, self.layout('Header'))
        self.assertFalse(action(menu, 'Move Up').isEnabled())
        self.assertTrue(action(menu, 'Move Down').isEnabled())
        menu = self.menu(tree, self.layout('Footer'))
        self.assertTrue(action(menu, 'Move Up').isEnabled())
        self.assertFalse(action(menu, 'Move Down').isEnabled())

    def test_layout_paste_rejects_missing_parent_and_second_iteration(self):
        w = self.window
        select_target(w.layouts.tree, self.layout('RowValue'))
        w.copy_layout()
        menu = self.menu(w.layouts.tree, self.layout('Header'))
        self.assertFalse(action(menu, 'Paste Items').isEnabled())
        menu = self.menu(w.layouts.tree, self.layout('Rows'))
        self.assertTrue(action(menu, 'Paste Items').isEnabled())
        w.copy_layout()
        menu = self.menu(w.layouts.tree, self.layout('Body'))
        self.assertFalse(action(menu, 'Paste Items').isEnabled())
        menu = self.menu(w.layouts.tree, self.layout('Footer'))
        self.assertFalse(action(menu, 'Paste Items').isEnabled())  # Iterator cannot be attached to a layout.

    def test_layout_mixed_selection_copy_is_disabled(self):
        tree = self.window.layouts.tree
        select_target(tree, self.layout('Header'))
        self.layout('Body').setSelected(True)
        menu = self.menu(tree, self.layout('Header'))
        self.assertFalse(action(menu, 'Copy Items').isEnabled())
        self.assertFalse(action(menu, 'Remove Layout…').isEnabled())

    def test_stale_menu_does_not_remove_or_copy_a_refreshed_target(self):
        tree = self.window.fields.tree
        menu = self.menu(tree, tree.topLevelItem(0))
        self.window.refresh_edit()
        self.app.clipboard().setText('unchanged')
        action(menu, 'Copy Names').trigger()
        self.assertEqual(self.app.clipboard().text(), 'unchanged')
        with patch('atool_qt.authoring.QMessageBox.question') as confirm:
            action(menu, 'Remove Field…').trigger()
            confirm.assert_not_called()

    def test_data_blank_menu_and_synthetic_condition_result_cannot_edit_old_node(self):
        panel = self.window.data
        menu = self.menu(panel.tree, None)
        self.assertNotIn('Edit Value…', [entry.text() for entry in menu.actions()])
        self.assertFalse(panel.edit_actions['Remove'].isEnabled())
        panel.mode.setCurrentText('Condition')
        panel.search.setText('@.ok')
        panel.run_search()
        menu = self.menu(panel.tree, panel.tree.topLevelItem(0))
        self.assertNotIn('Edit Value…', [entry.text() for entry in menu.actions()])
        action(menu, 'Copy Result').trigger()
        self.assertEqual(json.loads(self.app.clipboard().text()), True)

    def test_native_property_menu_and_popup_focus_leave_draft_unchanged(self):
        panel = self.window.fields
        panel.description.setPlainText('draft description')
        old = copy.deepcopy(self.session.payload)
        menu = self.window.context_menus.control_menu(panel.description)
        self.addCleanup(menu.deleteLater)
        with patch.object(self.window, 'apply_record') as apply:
            self.window.eventFilter(panel.description, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.PopupFocusReason))
            apply.assert_not_called()
        self.assertEqual(self.session.payload, old)
        self.assertEqual(panel.description.toPlainText(), 'draft description')
        self.assertTrue(any('Paste' in entry.text() for entry in menu.actions()))

    def test_right_click_row_change_commits_previous_property_to_its_original_record(self):
        panel = self.window.fields
        self.window.show_panel('fields')
        self.window.select_name(panel, 'Amount')
        panel.description.setFocus()
        self.app.processEvents()
        panel.description.setPlainText('Updated Amount description')
        account = next(row for row in panel.items() if row.data(0, Qt.ItemDataRole.UserRole + 4) == 'Account')
        self.window.context_menus.select_tree_target(panel.tree, account)
        self.assertEqual(self.window.selected_record('fields')['name'], 'Account')
        amount = next(record for record in self.session.fields if record['name'] == 'Amount')
        account = next(record for record in self.session.fields if record['name'] == 'Account')
        self.assertEqual(amount['descr'], 'Updated Amount description')
        self.assertEqual(account['descr'], '')

    def test_menu_cannot_act_after_current_row_changes_without_a_rebuild(self):
        tree = self.window.fields.tree
        menu = self.menu(tree, tree.topLevelItem(0))
        select_target(tree, tree.topLevelItem(1))
        self.app.clipboard().setText('unchanged')
        action(menu, 'Copy Names').trigger()
        self.assertEqual(self.app.clipboard().text(), 'unchanged')

    def test_keyboard_menu_targets_current_row(self):
        tree = self.window.fields.tree
        tree.setFocus()
        labels = []
        with patch.object(self.window.context_menus, 'exec_menu', lambda menu, *_: labels.extend(entry.text() for entry in menu.actions())):
            QTest.keyClick(tree, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyRelease(tree, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier)
        self.assertIn('Copy Field Definitions', labels)

    def test_new_dialog_controls_receive_context_events(self):
        dialog = SettingsDialog(self.window)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        table = dialog.language_table
        target = table.viewport()
        point = target.rect().center()
        labels = []
        with patch.object(self.window.context_menus, 'exec_menu', lambda menu, *_: labels.extend(entry.text() for entry in menu.actions())):
            self.app.sendEvent(target, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, target.mapToGlobal(point)))
        self.assertIn('Add Row', labels)
        self.assertIn(table, self.window.context_menus._targets)

    def test_context_event_on_header_viewport_opens_header_menu(self):
        header = self.window.fields.tree.header()
        point = header.rect().center()
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, header.mapToGlobal(point))
        labels = []
        with patch.object(self.window.context_menus, 'exec_menu', lambda menu, *_: labels.extend(entry.text() for entry in menu.actions())):
            self.app.sendEvent(header.viewport(), event)
        self.assertIn('Sort Ascending', labels)

    def test_language_dialog_add_remove_rows_through_menu(self):
        dialog = SettingsDialog(self.window)
        self.addCleanup(dialog.deleteLater)
        table = dialog.language_table
        before = table.rowCount()
        menu = self.window.context_menus.table_menu(table, table.model().index(-1, -1))
        self.addCleanup(menu.deleteLater)
        action(menu, 'Add Row').trigger()
        self.assertEqual(table.rowCount(), before + 1)
        table.selectRow(before)
        self.assertTrue(table.selectedIndexes(), str(QApplication.keyboardModifiers()))
        menu = self.window.context_menus.table_menu(table, table.model().index(before, 0))
        self.addCleanup(menu.deleteLater)
        action(menu, 'Remove Selected Rows').trigger()
        self.assertEqual(table.rowCount(), before)

    def test_content_browser_load_uses_existing_discard_flow(self):
        panel = self.window.content
        row = QTreeWidgetItem(['Example', 'Text'])
        panel.browser.addTopLevelItem(row)
        menu = self.menu(panel.browser, row)
        with patch.object(panel, 'confirm_discard', return_value=False) as discard:
            action(menu, 'Load Content').trigger()
            discard.assert_called_once()
        self.assertFalse(panel.loading)

    def test_activity_copy_all_flushes_pending_output(self):
        activity = self.window.activity
        activity.clear()
        activity.appendPlainText('Pending output')
        activity.menu_actions['copy_all'].trigger()
        self.assertIn('Pending output', self.app.clipboard().text())

    def test_no_package_disables_authoring_entries_in_blank_menus(self):
        other = WorkspaceWindow(QSettings(str(Path(self.temp.name) / 'empty.ini'), QSettings.Format.IniFormat))
        other.comms.settings = self.window.comms.settings
        self.addCleanup(other.deleteLater)
        for tree, title in ((other.documents.tree, 'Add Assembly Template Document'),
                            (other.fields.tree, 'Add Field'), (other.layouts.tree, 'Add Layout'),
                            (other.clauses.tree, 'Add')):
            menu = other.context_menus.tree_menu(tree, None)
            self.addCleanup(menu.deleteLater)
            self.assertFalse(action(menu, title).isEnabled())
        other.close()

    def test_catalog_and_package_dialog_menus_route_to_existing_selection_handlers(self):
        from atool_qt.package_documents import CatalogDialog
        from atool_qt.package_downloads import PackagePicker, VersionPicker
        catalog_path = Path(self.temp.name) / 'catalog.json'
        catalog_path.write_text(json.dumps([{'uuid': 'document-uuid', 'shortName': 'Notice', 'configId': '42'}]))
        dialog = CatalogDialog(self.window.comms, catalog_path, parent=self.window)
        self.addCleanup(dialog.deleteLater)
        menu = self.menu(dialog.tree, dialog.tree.topLevelItem(0))
        action(menu, 'Copy UUID').trigger()
        self.assertEqual(self.app.clipboard().text(), 'document-uuid')
        action(menu, 'Add').trigger()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)

        dialog = PackagePicker(self.window, [{'shortName': 'Package', 'name': 'Package', 'description': 'Description', 'uuid': 'p-uuid'}])
        self.addCleanup(dialog.deleteLater)
        menu = self.menu(dialog.tree, dialog.tree.topLevelItem(0))
        with patch.object(self.window, 'list_package_versions') as versions:
            action(menu, 'Get to Shared/Edit…').trigger()
            versions.assert_called_once_with('Package', shared=True)

        dialog = VersionPicker(self.window, 'Package', [{'shortName': '1.0'}])
        self.addCleanup(dialog.deleteLater)
        menu = self.menu(dialog.tree, dialog.tree.topLevelItem(0))
        with patch.object(self.window, 'download_package', return_value=False) as download:
            action(menu, 'Get to Local').trigger()
            download.assert_called_once_with('Package', '1.0', shared=False)

    def test_resolve_and_clause_usage_dialogs_copy_full_values_and_retain_navigation(self):
        from atool_qt.data_actions import ResolveDialog
        from atool_qt.clause_usage import ConditionUsageDialog, usage_results
        with patch.object(ResolveDialog, 'refresh_layouts'):
            dialog = ResolveDialog(self.window)
        self.addCleanup(dialog.deleteLater)
        row = QTreeWidgetItem(['Content', 'Content', 'PASS', 'truncated'])
        row.setData(0, Qt.ItemDataRole.UserRole, {'kind': 'content', 'name': 'Content', 'rendered': 'full\nvalue'})
        row.setToolTip(3, 'full\nvalue')
        dialog.tree.addTopLevelItem(row)
        menu = self.menu(dialog.tree, row)
        action(menu, 'Copy Resolved Value').trigger()
        self.assertEqual(self.app.clipboard().text(), 'full\nvalue')
        self.assertFalse(action(menu, 'Save Resolution…').isEnabled())
        dialog.refresh_item_button.setEnabled(False)
        menu = self.menu(dialog.tree, row)
        self.assertFalse(action(menu, 'Refresh Item').isEnabled())

        dialog = ConditionUsageDialog(self.window, usage_results(self.session, 'is_ok'), 'Usage')
        self.addCleanup(dialog.deleteLater)
        menu = self.menu(dialog.tree, dialog.tree.topLevelItem(0))
        action(menu, 'Copy Condition').trigger()
        self.assertEqual(self.app.clipboard().text(), '@.ok')
        action(menu, 'Select Owner').trigger()
        self.assertEqual(self.window.active_document['name'], 'Notice')

    def test_settings_browse_menu_and_readonly_report_keep_native_copy(self):
        from atool_qt.jsonpath_audit import JSONPathAuditDialog
        dialog = SettingsDialog(self.window)
        self.addCleanup(dialog.deleteLater)
        control = dialog.controls[('occs', 'comms_cache_dir')]
        menu = self.window.context_menus.control_menu(control)
        self.addCleanup(menu.deleteLater)
        self.assertTrue(action(menu, 'Browse…').isEnabled())
        report = JSONPathAuditDialog(self.window, [])
        self.addCleanup(report.deleteLater)
        menu = self.window.context_menus.control_menu(report.report)
        self.addCleanup(menu.deleteLater)
        action(menu, 'Copy Report').trigger()
        self.assertIn('JSONPath length audit', self.app.clipboard().text())
        self.assertFalse(any(entry.text().replace('&', '') == 'Cut' for entry in menu.actions()))

    def test_rich_menu_copies_original_chip_markup_and_guards_new_document(self):
        from atool_qt.rich_content import RichContentEditor
        from unittest.mock import Mock
        # Build the real native menu without starting WebEngine's renderer.
        view = QWidget(self.window)
        view.generation = 7
        page = Mock()
        view.page = lambda: page
        target = {'generation': 7, 'request': 3, 'undo': True, 'redo': False, 'selection': True,
                  'chipKind': 'data', 'chipMarkup': '<comms-data>$Data{"Id":"Amount","Keep":true}</comms-data>',
                  'cell': False, 'link': None}
        menu = RichContentEditor.context_menu(view, target)
        self.addCleanup(menu.deleteLater)
        action(menu, 'Copy').trigger()
        self.assertEqual(self.app.clipboard().text(), target['chipMarkup'])
        action(menu, 'Cut').trigger()
        self.assertIn('runContextCommand("removeChip",7,3)', page.runJavaScript.call_args.args[0])
        page.reset_mock()
        view.generation = 8
        action(menu, 'Remove Field Chip').trigger()
        page.runJavaScript.assert_not_called()

    def test_rich_table_menu_uses_target_merge_eligibility(self):
        from atool_qt.rich_content import RichContentEditor
        from unittest.mock import Mock
        view = QWidget(self.window)
        view.generation = 2
        page = Mock()
        view.page = lambda: page
        target = {'generation': 2, 'request': 1, 'undo': False, 'redo': True, 'selection': False,
                  'chipKind': None, 'cell': True, 'link': 'https://example.com/',
                  'merge': {'left': False, 'right': True, 'up': False, 'down': True}}
        menu = RichContentEditor.context_menu(view, target)
        self.addCleanup(menu.deleteLater)
        table = action(menu, 'Table').menu()
        self.assertFalse(action(table, 'Merge Left').isEnabled())
        action(table, 'Merge Right').trigger()
        self.assertIn('runContextCommand("mergeRight",2,1)', page.runJavaScript.call_args.args[0])
        action(menu, 'Copy Link Address').trigger()
        self.assertEqual(self.app.clipboard().text(), 'https://example.com/')


if __name__ == '__main__':
    unittest.main()
