"""Context commands for secondary dialogs; all writes use existing handlers."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QPushButton

from .context_menus import branch_actions, command, copy_action, tree_actions

ROLE = Qt.ItemDataRole.UserRole


def owner(widget):
    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, QDialog):
        parent = parent.parentWidget()
    return parent


def button_command(menu, dialog, title, *, enabled=True):
    button = next((button for button in dialog.findChildren(QPushButton) if button.text() == title), None)
    if button is not None:
        command(menu, title, lambda: button.click() if button.isEnabled() else None,
                enabled and button.isEnabled())


def identifiers(menu, value, keys):
    if isinstance(value, dict):
        for key, label in keys:
            if value.get(key) not in (None, ''):
                copy_action(menu, 'Copy ' + label, str(value[key]))


def populate_dialog_tree(menu, tree, item):
    dialog = owner(tree)
    if dialog is None:
        return
    kind = type(dialog).__name__
    value = item.data(0, ROLE) if item else None
    if kind == 'CatalogDialog':
        command(menu, 'Associate' if dialog.associate_name else 'Add', dialog.accept_selection,
                item is not None and dialog.add_button.isEnabled())
        identifiers(menu, value, [('shortName', 'Short Name'), ('uuid', 'UUID'), ('configId', 'Config ID')])
        button_command(menu, dialog, 'Refresh from Comms')
    elif kind == 'ResolveDialog':
        if item:
            command(menu, 'Refresh Item', dialog.refresh_item, dialog.refresh_item_button.isEnabled())
            copy_action(menu, 'Copy Item Name', item.text(0))
            copy_action(menu, 'Copy Resolved Value', item.toolTip(3) or item.text(3))
            if value is not None:
                copy_action(menu, 'Copy Node Details', value)
            branch_actions(menu, tree, item)
        else:
            tree_actions(menu, tree)
        command(menu, 'Save Resolution…', dialog.save, dialog.result is not None)
    elif kind == 'ConditionUsageDialog':
        if item:
            command(menu, 'Select Owner', dialog.select_owner)
            result = dialog.current()
            copy_action(menu, 'Copy Condition', result.get('old_condition', result['condition']))
            copy_action(menu, 'Copy Composed Expression', result.get('new_condition', result.get('compose_text', '')))
            copy_action(menu, 'Copy Matched Clauses', '\n'.join(result['matched_clauses']))
            if dialog.updates:
                for title in ('Apply Current', 'Skip'):
                    button_command(menu, dialog, title)
    elif kind == 'PackagePicker':
        for title in ('Get to Local…', 'Get to Shared/Edit…'):
            button_command(menu, dialog, title, enabled=item is not None)
        identifiers(menu, value, [('shortName', 'Short Name'), ('uuid', 'UUID'), ('configId', 'Config ID')])
    elif kind == 'VersionPicker':
        command(menu, 'Get to Shared/Edit' if dialog.shared else 'Get to Local', dialog.choose, item is not None)
        if item:
            copy_action(menu, 'Copy Version', item.text(0))
            copy_action(menu, 'Copy Effective Date', item.text(1))
    elif kind == 'SharedPicker':
        if item:
            if dialog.unlock:
                button_command(menu, dialog, 'Unlock…')
            else:
                for title in ('Open…', 'Open for Edit', 'Open Testing Copy'):
                    button_command(menu, dialog, title)
            identifiers(menu, value, [('package_name', 'Package Name'), ('version_name', 'Version'), ('package_dir', 'Folder Path')])
            if isinstance(value, dict):
                copy_action(menu, 'Copy Lock Details', value.get('lock') or {})
            copy_action(menu, 'Copy Owner', item.text(3))
        button_command(menu, dialog, 'Refresh')
    elif kind == 'CleanupDialog':
        selected = [row for row in tree.selectedItems() if not row.data(0, ROLE)['protected']]
        if item:
            def mark(checked):
                for row in selected:
                    row.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            command(menu, 'Mark for Deletion', lambda: mark(True), bool(selected))
            command(menu, 'Unmark for Deletion', lambda: mark(False), bool(selected))
            path = value['path']
            from .context_menus import WorkspaceContextMenus
            WorkspaceContextMenus.path_commands(menu, str(path))
        else:
            for title in ('Refresh', 'Select Old', 'Select Removable', 'Select None'):
                button_command(menu, dialog, title)
        # Deletion remains on the dialog button: checked rows, not highlighted rows.
    elif kind == 'ConfigPicker':
        if item:
            dialog.update_controls()
            button_command(menu, dialog, dialog.lock_button.text())
            button_command(menu, dialog, 'Close Configuration')
            identifiers(menu, value, [('id', 'Config ID'), ('shortName', 'Short Name'), ('status', 'Status')])
    elif kind == 'LockoutsDialog':
        button_command(menu, dialog, 'Add…')
        button_command(menu, dialog, 'Remove', enabled=item is not None)
        button_command(menu, dialog, 'Refresh')
        if item:
            copy_action(menu, 'Copy Window Details', value)


def populate_language_table(menu, table, index):
    dialog = owner(table)
    if dialog is not None and type(dialog).__name__ == 'SettingsDialog' and table is dialog.language_table:
        command(menu, 'Add Row', dialog.add_language_row)
        command(menu, 'Remove Selected Rows', dialog.remove_language_rows, index.isValid())


def populate_text_commands(menu, control):
    dialog = owner(control)
    if dialog is None:
        return
    kind = type(dialog).__name__
    if kind == 'SettingsDialog':
        for key, widget in dialog.controls.items():
            if control is widget and key in dialog.browse_controls:
                # These controls use the same file/folder picker as their Browse button.
                button = dialog.browse_controls[key]
                command(menu, 'Browse…', button.click, button.isEnabled())
                value = widget.text().strip()
                if value:
                    from .context_menus import WorkspaceContextMenus
                    WorkspaceContextMenus.path_commands(menu, value)
    elif kind == 'PackageConditionDialog':
        command(menu, 'Apply Condition', dialog.apply)
    elif kind == 'ResolveDialog' and control is dialog.report:
        command(menu, 'Save Resolution…', dialog.save, dialog.result is not None)
    elif kind == 'SampleDialog':
        button_command(menu, dialog, 'Save As…')
    elif kind == 'JSONPathAuditDialog':
        button_command(menu, dialog, 'Copy Report')
        button_command(menu, dialog, 'Save Report…')
    elif kind == 'OperationDialog':
        button_command(menu, dialog, 'Cancel Operation')
