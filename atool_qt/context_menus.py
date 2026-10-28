"""Workspace-scoped context menus, shared by managers and their dialogs.

Commands are proxies for existing actions/buttons, never copies of their business
logic. Menus are built on demand so clipboard and operation state stay current.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, QPersistentModelIndex, Qt, QUrl
from PySide6.QtGui import QContextMenuEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDockWidget,
    QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton,
    QTableWidget, QTabBar, QTextEdit, QTreeWidget, QWidget,
)
from shiboken6 import isValid

ROLE = Qt.ItemDataRole.UserRole


def command(menu, label, callback, enabled=True, *, checked=None):
    action = menu.addAction(label)
    action.setEnabled(bool(enabled))
    if checked is not None:
        action.setCheckable(True)
        action.setChecked(bool(checked))

    def run():
        if action.isEnabled() and getattr(menu, '_context_valid', lambda: True)():
            callback()
    action.triggered.connect(run)
    return action


def proxy(menu, source, label=None, enabled=True):
    def available():
        widgets = [widget for widget in source.associatedObjects() if isinstance(widget, QWidget)]
        return source.isEnabled() and (not widgets or any(widget.isEnabled() for widget in widgets))
    return command(menu, label or source.text(),
                   lambda: source.trigger() if available() else None,
                   enabled and available(),
                   checked=source.isChecked() if source.isCheckable() else None)


def copy_action(menu, label, value, enabled=True):
    # Capture the full value before a menu's nested event loop can refresh a grid.
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return command(menu, label, lambda: QApplication.clipboard().setText(text), enabled)


def select_target(tree, item):
    """Do not collapse a multi-selection or emit itemClicked on a right press."""
    if item is None:
        tree.clearSelection()
        tree.setCurrentItem(None)
    elif item.isSelected():
        tree.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
    else:
        tree.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.ClearAndSelect)


def branch_actions(menu, tree, item):
    if item is not None and item.childCount():
        command(menu, 'Expand Branch', lambda: expand_branch(tree, item, True))
        command(menu, 'Collapse Branch', lambda: expand_branch(tree, item, False))


def expand_branch(tree, item, expanded):
    # Expanding can populate lazy data nodes; inspect children afterwards.
    item.setExpanded(expanded)
    for row in range(item.childCount()):
        expand_branch(tree, item.child(row), expanded)


def tree_actions(menu, tree):
    command(menu, 'Expand All', tree.expandAll, tree.topLevelItemCount())
    command(menu, 'Collapse All', tree.collapseAll, tree.topLevelItemCount())


def toolbar_action(panel, text):
    return next(action for action in panel.authoring_toolbar.actions() if action.text() == text)


def populate_data_menu(menu, panel, tree, item):
    panel.update_edit_actions()
    path = item.data(0, ROLE + 1) if item else None
    actual = path in panel.values and str(path).startswith('$')
    if actual:
        for title in ('Edit Value…', 'Add…', 'Paste…', 'Copy'):
            proxy(menu, panel.edit_actions[title], 'Copy JSON Value' if title == 'Copy' else title)
        copy_action(menu, 'Copy Path', path)
        if panel.search.text():
            command(menu, 'Reveal in Full Data Tree', lambda: panel.refresh_data(panel.selected_parts()))
        branch_actions(menu, tree, item)
        proxy(menu, panel.edit_actions['Remove'], 'Remove…')
    elif item and path in panel.values:
        copy_action(menu, 'Copy Result', panel.values[path])
    menu.addSeparator()
    for title in ('Undo', 'Redo', 'Save', 'Save JSON As…'):
        proxy(menu, panel.edit_actions[title], title + ' Data Edit' if title in ('Undo', 'Redo') else title)
    command(menu, 'Clear Search', panel.clear_search)
    tree_actions(menu, tree)


class WorkspaceContextMenus(QObject):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        QApplication.instance().installEventFilter(self)

    def belongs(self, widget):
        while isinstance(widget, QWidget):
            if widget is self.workspace:
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (QEvent.Type.MouseButtonPress, QEvent.Type.ContextMenu, QEvent.Type.KeyPress) or not self.belongs(watched):
            return False
        if kind == QEvent.Type.KeyPress:
            if (event.key() == Qt.Key.Key_Menu or
                    event.key() == Qt.Key.Key_F10 and event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                target = watched.viewport() if isinstance(watched, (QTreeWidget, QTableWidget, QPlainTextEdit, QTextEdit)) else watched
                request = QContextMenuEvent(QContextMenuEvent.Reason.Keyboard, target.rect().center(), target.mapToGlobal(target.rect().center()))
                return self.eventFilter(target, request)
            return False
        parent = watched.parentWidget()
        grid = parent if isinstance(parent, (QTreeWidget, QTableWidget)) and watched is parent.viewport() else None
        if kind == QEvent.Type.MouseButtonPress:
            context_press = (event.button() == Qt.MouseButton.RightButton or
                             sys.platform == 'darwin' and event.button() == Qt.MouseButton.LeftButton
                             and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))
            if grid and grid.isEnabled() and context_press:
                if isinstance(grid, QTreeWidget):
                    self.select_tree_target(grid, grid.itemAt(event.position().toPoint()))
                else:
                    self.select_table_target(grid, grid.indexAt(event.position().toPoint()))
                return True
            return False
        if not watched.isEnabled():
            return False
        if grid:
            keyboard = event.reason() == event.Reason.Keyboard
            if isinstance(grid, QTreeWidget):
                item = grid.currentItem() if keyboard else grid.itemAt(event.pos())
                item = self.select_tree_target(grid, item)
                column = grid.currentColumn() if keyboard else grid.columnAt(event.pos().x())
                menu = self.tree_menu(grid, item, max(0, column))
            else:
                index = grid.currentIndex() if keyboard else grid.indexAt(event.pos())
                self.select_table_target(grid, index)
                menu = self.table_menu(grid, index)
            point = (grid.viewport().mapToGlobal(grid.visualRect(grid.currentIndex()).center())
                     if keyboard and grid.currentIndex().isValid() else event.globalPos())
        elif isinstance(watched, QHeaderView) or isinstance(parent, QHeaderView):
            header = watched if isinstance(watched, QHeaderView) else parent
            menu = self.header_menu(header, header.logicalIndexAt(event.pos()))
            point = event.globalPos()
        else:
            menu = self.control_menu(watched, event.pos())
            point = event.globalPos()
        if menu is None:
            return False
        try:
            self.exec_menu(menu, point)
        finally:
            menu.deleteLater()
        event.accept()
        return True

    @staticmethod
    def exec_menu(menu, point):
        menu.exec(point)

    def select_tree_target(self, tree, item):
        w = self.workspace
        if item is not tree.currentItem() and tree in (w.documents.tree, w.fields.tree, w.layouts.tree, w.clauses.tree):
            role = ROLE + 1 if tree is w.layouts.tree else ROLE
            identity = item.data(0, role) if item else None
            # A deliberate row change follows the existing property-commit flow.
            # Do this before changing the target, so a draft cannot be written to
            # the new row or silently replaced by its details. A popup on the same
            # row does not take focus from its property editor.
            tree.setFocus(Qt.FocusReason.MouseFocusReason)
            if item is not None and not isValid(item):
                item = next((row for row in tree.findItems('*', Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive)
                             if row.data(0, role) == identity), None)
        select_target(tree, item)
        return item

    @staticmethod
    def select_table_target(table, index):
        if not index.isValid():
            table.clearSelection()
            table.setCurrentIndex(index)
        elif table.selectionModel().isSelected(index):
            table.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        else:
            table.setCurrentCell(index.row(), index.column(),
                                 QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)

    def tree_menu(self, tree, item, column=0):
        w = self.workspace
        menu = QMenu(tree)
        session = w.session
        document_name = w.active_document['name'] if w.active_document else None
        index = QPersistentModelIndex(tree.indexFromItem(item)) if item else None
        menu._context_valid = lambda: (
            w.session is session and (w.active_document['name'] if w.active_document else None) == document_name
            and (not tree.currentIndex().isValid() if index is None else
                 index.isValid() and index == tree.currentIndex().siblingAtColumn(0)))
        providers = {w.documents.tree: self.documents, w.layouts.tree: self.layouts,
                     w.fields.tree: self.fields, w.clauses.tree: self.clauses,
                     w.data.tree: self.data, w.favorites.tree: self.favorites,
                     w.content.browser: self.content_browser, w.content.fields: self.content_fields,
                     w.content.styles: self.content_styles, w.documents.clauses_tree: self.document_clauses,
                     w.layouts.mapped_values: self.mapped_values}
        provider = providers.get(tree)
        if provider:
            provider(menu, tree, item)
        else:
            from .dialog_context_menus import populate_dialog_tree
            populate_dialog_tree(menu, tree, item)
        if item:
            if menu.actions():
                menu.addSeparator()
            copy_action(menu, 'Copy Cell', self.cell_value(tree, item, column))
            rows = [row for row in tree.selectedItems() if not row.isHidden()]
            copy_action(menu, 'Copy Rows' if len(rows) > 1 else 'Copy Row',
                        '\n'.join('\t'.join(self.cell_value(tree, row, col) for col in range(tree.columnCount()))
                                  for row in rows or [item]))
        return menu

    def cell_value(self, tree, item, column):
        w = self.workspace
        if tree is w.fields.tree and item.data(0, ROLE) is not None:
            record = w.fields.records()[item.data(0, ROLE)]
            return record['name'] if column == 0 else json.dumps(record.get('mapped_values', []), ensure_ascii=False) if column == 1 else item.text(column)
        if tree in (w.documents.tree, w.layouts.tree) and column == 0:
            return str(item.data(0, ROLE + 4) or item.text(column))
        if tree is w.data.tree:
            path = item.data(0, ROLE + 1)
            if path in w.data.values:
                return path if column == 0 else json.dumps(w.data.values[path], ensure_ascii=False, indent=2)
        if tree is w.layouts.mapped_values and column == 1:
            return item.toolTip(column) or item.text(column)
        if type(tree.window()).__name__ == 'ResolveDialog' and column == 3:
            return item.toolTip(column) or item.text(column)
        return item.text(column)

    def header_menu(self, header, column):
        tree = header.parentWidget()
        if not isinstance(tree, (QTreeWidget, QTableWidget)) or header.orientation() != Qt.Orientation.Horizontal:
            return None
        menu = QMenu(header)
        if 0 <= column < header.count():
            if isinstance(tree, QTreeWidget):
                def sort(order):
                    tree._grid_user_sort = (column, order)
                    tree.setSortingEnabled(True)
                    tree.sortByColumn(column, order)
                    header.setSortIndicatorShown(True)
                command(menu, 'Sort Ascending', lambda: sort(Qt.SortOrder.AscendingOrder))
                command(menu, 'Sort Descending', lambda: sort(Qt.SortOrder.DescendingOrder))
            command(menu, 'Resize Column to Contents', lambda: tree.resizeColumnToContents(column))
        command(menu, 'Resize All Columns to Contents', lambda: [tree.resizeColumnToContents(col) for col in range(header.count())])
        return menu

    def panel_actions(self, menu, tree, panel):
        tree_actions(menu, tree)
        command(menu, 'Clear Filters', lambda: self.clear_filters(panel))

    @staticmethod
    def clear_filters(panel):
        panel.search.clear()
        if hasattr(panel, 'matched_only'):
            panel.matched_only.setChecked(False)

    def documents(self, menu, tree, item):
        w, panel = self.workspace, self.workspace.documents
        w.update_package_document_actions()
        w.update_manager_controls()
        w.update_model_actions()
        record = w.selected_record('documents') if item else None
        single = bool(record and len(tree.selectedItems()) == 1)
        if record:
            proxy(menu, w.trigger_clause_action, enabled=single)
            proxy(menu, w.package_actions['Edit Package Condition'], enabled=single)
            command(menu, 'Always Trigger', panel.always_trigger.click, single and panel.always_trigger.isEnabled(), checked=record.get('always_trigger', False))
            menu.addSeparator()
            proxy(menu, w.document_model_action, 'Open Model', single)
            proxy(menu, w.model_actions['Generate'], 'Regenerate Model', single)
            proxy(menu, w.resolve_action, enabled=single)
            menu.addSeparator()
            for title in ('Associate', 'Remove Association', 'Move Up', 'Move Down'):
                enabled = single
                if title.startswith('Move') and single:
                    records = sorted((row for row in w.session.documents if row.get('associated')),
                                     key=lambda row: (row.get('order') is None, row.get('order') or 0))
                    position = next((i for i, row in enumerate(records) if row['name'] == record['name']), -1)
                    enabled = position > 0 if title == 'Move Up' else 0 <= position < len(records) - 1
                proxy(menu, w.package_actions[title], enabled=enabled)
            menu.addSeparator()
            copy_action(menu, 'Copy Names', '\n'.join(str(row.data(0, ROLE + 4)) for row in tree.selectedItems()))
            copy_action(menu, 'Copy Condition', record.get('condition', ''), single)
            branch_actions(menu, tree, item)
            proxy(menu, toolbar_action(panel, 'Remove'), 'Remove from Assembly Template…', single)
        else:
            proxy(menu, toolbar_action(panel, 'Add'), 'Add Assembly Template Document')
            proxy(menu, w.package_actions['Add Package Document'], 'Add Package Document…')
            proxy(menu, w.package_actions['Refresh'], 'Refresh Package Documents')
            proxy(menu, w.document_view_action)
            self.panel_actions(menu, tree, panel)

    def fields(self, menu, tree, item):
        w, panel = self.workspace, self.workspace.fields
        w.update_manager_controls()
        records = w.selected_fields() if item else []
        if records:
            proxy(menu, toolbar_action(panel, 'Browse Path'), enabled=len(records) == 1)
            proxy(menu, w.field_copy_action, 'Copy Field Definitions')
            copy_action(menu, 'Copy Names', '\n'.join(record['name'] for record in records))
            if len(records) == 1:
                record = records[0]
                for label, value in (('Copy Field Path', record['path']), ('Copy Mapping Path', record['true_path']),
                                     ('Copy Mapped Values', record.get('mapped_values', []))):
                    copy_action(menu, label, value, label != 'Copy Mapped Values' or w.session.mapped)
            self.favorite_actions(menu, 'fields', [record['name'] for record in records])
            proxy(menu, toolbar_action(panel, 'Remove'), 'Remove Field…', len(records) == 1)
        elif item:
            branch_actions(menu, tree, item)
            parts, parent = [], item
            while parent:
                parts.insert(0, parent.text(0))
                parent = parent.parent()
            copy_action(menu, 'Copy Hierarchy Path', ' > '.join(parts))
        else:
            proxy(menu, toolbar_action(panel, 'Add'), 'Add Field')
            proxy(menu, w.field_paste_action, 'Paste Field Definitions')
            command(menu, 'View by Name' if panel.field_view == 'path' else 'View by Path', panel.toggle_field_view)
            self.panel_actions(menu, tree, panel)

    def favorite_actions(self, menu, kind, names):
        w = self.workspace
        favorites = w.package_favorites().get(kind, [])
        command(menu, 'Add to Favorites', lambda: w.set_favorite_names(kind, names, True), any(name not in favorites for name in names))
        command(menu, 'Remove from Favorites', lambda: w.set_favorite_names(kind, names, False), any(name in favorites for name in names))

    def layouts(self, menu, tree, item):
        w, panel = self.workspace, self.workspace.layouts
        w.update_manager_controls()
        node = item.data(0, ROLE) if item else None
        single = bool(node and len(tree.selectedItems()) == 1)
        if node:
            for title in ('Add Content', 'Add Iteration', 'Add Field'):
                action = toolbar_action(panel, title)
                if action.isEnabled():
                    proxy(menu, action, enabled=single)
            menu.addSeparator()
            proxy(menu, toolbar_action(panel, 'Copy'), 'Copy Items')
            proxy(menu, toolbar_action(panel, 'Paste'), 'Paste Items')
            for title in ('Up', 'Down'):
                proxy(menu, toolbar_action(panel, title), 'Move ' + title, single)
            menu.addSeparator()
            if node['source'].get('Path'):
                proxy(menu, toolbar_action(panel, 'Browse Path'), enabled=single)
                copy_action(menu, 'Copy Path', node['source']['Path'], single)
            if node['source'].get('Condition'):
                command(menu, 'Edit Condition in Clause Manager', lambda: w.show_panel('clauses'), single)
                proxy(menu, toolbar_action(panel, 'Evaluate Condition'), enabled=single)
                copy_action(menu, 'Copy Condition', node['source']['Condition'], single)
            copy_action(menu, 'Copy Names', '\n'.join(str(row.data(0, ROLE + 4)) for row in tree.selectedItems()))
            copy_action(menu, 'Copy Source JSON', node['source'], single)
            branch_actions(menu, tree, item)
            menu.addSeparator()
            proxy(menu, toolbar_action(panel, 'Remove'), 'Remove ' + node['kind'] + '…', single)
        else:
            proxy(menu, toolbar_action(panel, 'Add Layout'))
            proxy(menu, toolbar_action(panel, 'Paste'), 'Paste Layouts', w.layout_clipboard_kind == 'Layout')
            self.panel_actions(menu, tree, panel)

    def clauses(self, menu, tree, item):
        w, panel = self.workspace, self.workspace.clauses
        w.update_manager_controls()
        record = w.selected_clause() if item else None
        if record:
            for title in ('Insert Name', 'Find Usage'):
                proxy(menu, toolbar_action(panel, title))
            copy_action(menu, 'Copy Name', record['name'])
            copy_action(menu, 'Copy Expression', record['expression'])
            self.favorite_actions(menu, 'clauses', [record['name']])
            menu.addSeparator()
            proxy(menu, toolbar_action(panel, 'Delete'), 'Delete Clause…')
        else:
            for title in ('Add', 'Find Raw', 'Update Triggers'):
                proxy(menu, toolbar_action(panel, title))
            command(menu, 'Clear Filter', panel.search.clear)

    def data(self, menu, tree, item):
        populate_data_menu(menu, self.workspace.data, tree, item)

    def favorites(self, menu, tree, item):
        w = self.workspace
        if item:
            kind, name = item.data(0, ROLE)
            command(menu, 'Open in ' + ('Field' if kind == 'fields' else 'Clause') + ' Manager', lambda: w.open_favorite(kind, name))
            copy_action(menu, 'Copy Name', name)
            copy_action(menu, 'Copy Result / Value', item.text(2))
            if item.toolTip(2) != item.text(2):
                copy_action(menu, 'Copy Error Details', item.toolTip(2))
            command(menu, 'Remove from Favorites', lambda: w.set_favorite_names(kind, [name], False))
        else:
            for label, index in (('Show All', 2), ('Show Pass / Mapped', 0), ('Show Fail / Unmapped', 1)):
                command(menu, label, lambda index=index: w.favorites.filter.setCurrentIndex(index), checked=w.favorites.filter.currentIndex() == index)

    def content_browser(self, menu, tree, item):
        panel = self.workspace.content
        panel.update_save_availability()
        if item:
            command(menu, 'Load Content', panel.load_selected, panel.load.isEnabled())
            copy_action(menu, 'Copy Short Name', item.text(0))
            copy_action(menu, 'Copy Type', item.text(1))
        else:
            busy = panel.loading or panel.saving
            command(menu, 'New Content', panel.new_content, not busy)
            command(menu, 'List from Config', lambda: panel.list_contents('config', True), not busy and bool(self.workspace.comms.settings.get('last_config_id')))
            command(menu, 'List…', lambda: panel.list_contents('all'), not busy)
            command(menu, 'List All…', lambda: panel.list_contents('all', True), not busy)
            command(menu, 'Clear Filter', panel.filter.clear)

    def content_fields(self, menu, tree, item):
        if item:
            panel = self.workspace.content
            command(menu, 'Insert Field', panel.insert_field, panel.editor_panel.isEnabled())
            for column, title in enumerate(('Copy Name', 'Copy Scope', 'Copy Path')):
                copy_action(menu, title, item.text(column))

    def content_styles(self, menu, tree, item):
        if item:
            copy_action(menu, 'Copy Style Name', item.text(0))
            copy_action(menu, 'Copy CSS Classes', item.text(1))

    def document_clauses(self, menu, tree, item):
        if item:
            w = self.workspace
            name = item.text(0)
            if w.session and any(row['name'] == name for row in w.session.clauses):
                command(menu, 'Open in Clause Manager', lambda: w.open_favorite('clauses', name))
                copy_action(menu, 'Copy Clause Name', name)
            copy_action(menu, 'Copy Result', item.text(1))
            copy_action(menu, 'Copy Condition Details', item.toolTip(0))
            branch_actions(menu, tree, item)
        else:
            tree_actions(menu, tree)

    def mapped_values(self, menu, tree, item):
        if item:
            copy_action(menu, 'Copy Full Mapped Values', item.toolTip(1) or item.text(1))

    def table_menu(self, table, index):
        from .dialog_context_menus import populate_language_table
        menu = QMenu(table)
        persistent = QPersistentModelIndex(index)
        menu._context_valid = lambda: not index.isValid() or persistent.isValid()
        populate_language_table(menu, table, index)
        if index.isValid():
            item = table.item(index.row(), index.column())
            copy_action(menu, 'Copy Cell', item.text() if item else '')
            rows = sorted({cell.row() for cell in table.selectedIndexes()}) or [index.row()]
            copy_action(menu, 'Copy Rows', '\n'.join('\t'.join(table.item(row, col).text() if table.item(row, col) else ''
                                                               for col in range(table.columnCount())) for row in rows))
        return menu

    def control_menu(self, widget, point=None):
        from .dialog_context_menus import populate_text_commands
        w = self.workspace
        # Text edits receive ContextMenu on their viewport, line edits on themselves.
        control = widget.parentWidget() if isinstance(widget.parentWidget(), (QPlainTextEdit, QTextEdit)) else widget
        if isinstance(control, (QPlainTextEdit, QTextEdit, QLineEdit)):
            if control is w.activity:
                return None  # Activity already shares its native menu with the menu bar.
            menu = control.createStandardContextMenu()
            if isinstance(control, QLineEdit) and control.echoMode() != QLineEdit.EchoMode.Normal:
                return menu
            text = control.text() if isinstance(control, QLineEdit) else control.toPlainText()
            menu.addSeparator()
            copy_action(menu, 'Copy Full Value' if isinstance(control, QLineEdit) else 'Copy All', text, bool(text))
            self.text_commands(menu, control)
            populate_text_commands(menu, control)
            return menu
        if isinstance(control, QTabBar):
            tab = control.tabAt(point) if point is not None else control.currentIndex()
            dock = next((dock for dock in w.docks.values() if dock.windowTitle() == control.tabText(tab)), None)
            if dock is not None:
                control = dock
        if isinstance(control, QDockWidget):
            menu = QMenu(control)
            command(menu, 'Dock This Panel' if control.isFloating() else 'Float This Panel', lambda: control.setFloating(not control.isFloating()))
            command(menu, 'Hide This Panel', control.hide)
            panels = menu.addMenu('Panels')
            for dock in w.docks.values():
                proxy(panels, dock.toggleViewAction())
            return menu
        if isinstance(control, QLabel) and control.text():
            menu = QMenu(control)
            copy_action(menu, 'Copy Full Message', control.toolTip() or control.text())
            if control in (w.package_label, w.data_label):
                copy_action(menu, 'Copy Name', control.text().partition(': ')[2])
                path = control.toolTip()
                if path:
                    self.path_commands(menu, path)
            elif control is w.clauses.target_label:
                command(menu, 'Go to Target', lambda: w.show_panel('documents' if control.text().startswith('Target: Document') else 'layouts'), w.active_document is not None)
            return menu
        if control in (w.fields.required, w.documents.always_trigger):
            menu = QMenu(control)
            command(menu, control.text(), control.click, control.isEnabled(), checked=control.isChecked())
            return menu
        if control is w.clauses.clause_picker:
            menu = QMenu(control)
            for title in ('Insert Name', 'Find Usage'):
                proxy(menu, toolbar_action(w.clauses, title))
            copy_action(menu, 'Copy Clause Name', control.currentText())
            return menu
        if control is w.content.version:
            menu = QMenu(control)
            copy_action(menu, 'Copy Version', control.currentText())
            proxy(menu, w.content.new_version, 'New Version…')
            return menu
        if control is w.favorites.filter:
            menu = QMenu(control)
            self.favorites(menu, w.favorites.tree, None)
            return menu
        if isinstance(control, QComboBox):
            menu = QMenu(control)
            copy_action(menu, 'Copy Full Value', control.currentText(), bool(control.currentText()))
            return menu
        return None

    def text_commands(self, menu, control):
        w = self.workspace
        for panel in (w.documents, w.fields, w.layouts, w.clauses, w.data):
            if control is panel.search:
                command(menu, 'Clear Search' if panel is w.data else 'Clear Filter', panel.search.clear)
                if panel is w.data:
                    command(menu, 'Run Search', panel.run_search, panel.mapped)
            if panel in (w.fields, w.layouts):
                path_control = panel.expression if panel is w.fields else panel.path
                if control is path_control:
                    proxy(menu, toolbar_action(panel, 'Browse Path'))
        if control is w.layouts.condition:
            proxy(menu, toolbar_action(w.layouts, 'Evaluate Condition'))
            command(menu, 'Edit in Clause Manager', lambda: w.show_panel('clauses'), w.layout_selection()[1] is not None)
        if control is w.fields.true_path:
            proxy(menu, toolbar_action(w.fields, 'Browse Path'))
        if control is w.clauses.compose:
            for title in ('Insert Name', 'Apply Composed'):
                proxy(menu, toolbar_action(w.clauses, title))
            command(menu, 'Show Clause Suggestions', control.show_completions, not control.isReadOnly())
        if control in (w.clauses.name, w.clauses.description, w.clauses.expression):
            proxy(menu, toolbar_action(w.clauses, 'Save'), 'Save Clause')
        if control is w.content.source:
            command(menu, 'Open HTML…', w.content.open_html)
            command(menu, 'Save HTML As…', w.content.save_html)
        if control is w.content.version.lineEdit():
            proxy(menu, w.content.new_version, 'New Version…')
        if control in (w.content.filter, w.content.field_filter):
            command(menu, 'Clear Filter', control.clear)

    @staticmethod
    def path_commands(menu, value):
        copy_action(menu, 'Copy Path', value)
        path = Path(value).expanduser()
        folder = path if path.is_dir() else path.parent
        command(menu, 'Show Folder', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))), path.exists())
