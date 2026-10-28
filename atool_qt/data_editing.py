"""Editing mapped JSON without changing the original input file."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile, QTimer, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QFileDialog,
                              QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                              QMenu, QPlainTextEdit, QStyle, QVBoxLayout)
from .grids import StatusDelegate
from .controls import ManagerButtons

INLINE_VALUE_LIMIT = 50


def use_value_dialog(value):
    return isinstance(value, (dict, list)) or len(value if isinstance(value, str) else json.dumps(value)) > INLINE_VALUE_LIMIT


def path_parts(path):
    """Decode the concrete dot/bracket paths produced by the browser queries."""
    if not path.startswith('$'):
        raise ValueError('Select a data node.')
    parts, offset = [], 1
    decoder = json.JSONDecoder()
    while offset < len(path):
        if path[offset] == '.':
            match = re.match(r'\.([A-Za-z_][A-Za-z0-9_]*)', path[offset:])
            if not match:
                raise ValueError('Select a concrete data node.')
            parts.append(match[1])
            offset += len(match[0])
        elif path[offset] == '[':
            key, end = decoder.raw_decode(path, offset + 1)
            if type(key) not in (str, int) or end >= len(path) or path[end] != ']':
                raise ValueError('Select a concrete data node.')
            parts.append(key)
            offset = end + 1
        else:
            raise ValueError('Select a concrete data node.')
    return parts


def display_path(path):
    """Show the last two property names, retaining their array indices."""
    try:
        parts = path_parts(path)
    except ValueError:
        return path
    properties = [index for index, key in enumerate(parts) if isinstance(key, str)]
    if len(properties) <= 2:
        return path
    tail = parts[properties[-2]:]
    first = tail[0]
    label = '$..' + (first if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', first)
                      else f'[{json.dumps(first, ensure_ascii=False)}]')
    return label + ''.join(f'[{json.dumps(key, ensure_ascii=False)}]' for key in tail[1:])


def display_paths(paths):
    """Add compact ancestor context when sibling labels would be ambiguous."""
    labels = {path: display_path(path) for path in paths}
    groups = {}
    for path, label in labels.items():
        groups.setdefault(label, []).append(path)
    for label, group in groups.items():
        if len(group) < 2 or not label.startswith('$..'):
            continue
        prefixes = []
        for path in group:
            parts = path_parts(path)
            properties = [i for i, key in enumerate(parts) if isinstance(key, str)]
            prefixes.append(parts[:properties[-2]])
        common = 0
        while (all(len(prefix) > common for prefix in prefixes)
               and all(prefix[-1-common] == prefixes[0][-1-common] for prefix in prefixes)):
            common += 1
        contexts = [prefix[:-common] if common else prefix for prefix in prefixes]
        for path, context in zip(group, contexts):
            if not context:
                labels[path] = path
                continue
            start = len(context) - 1
            while start > 0:
                if isinstance(context[start], int):
                    start -= 1
                    continue
                suffix = context[start:]
                if sum(other[-len(suffix):] == suffix for other in contexts) == 1:
                    break
                start -= 1
            suffix = context[start:]
            first = suffix[0]
            ancestor = (first if isinstance(first, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', first)
                        else f'[{json.dumps(first, ensure_ascii=False)}]')
            ancestor += ''.join(f'[{json.dumps(key, ensure_ascii=False)}]' for key in suffix[1:])
            labels[path] = '$..' + ancestor + '..' + label[3:]
    # A compact contextual label can coincide with another result's own label.
    # Retain the exact path in those rare cases instead of hiding a distinction.
    for label in set(labels.values()):
        matching = [path for path in labels if labels[path] == label]
        if len(matching) > 1:
            for path in matching:
                labels[path] = path
    return labels


def at_path(payload, parts):
    for key in parts:
        payload = payload[key]
    return payload


def parse_json(text):
    def invalid(value):
        raise ValueError(f'{value} is not a JSON value.')
    return json.loads(text, parse_constant=invalid)


class DataValueDelegate(StatusDelegate):
    """Edit scalar values using their full value and preserve JSON types."""
    def __init__(self, panel):
        super().__init__(panel.tree)
        self.panel = panel

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if index.column() == 0:
            option.textElideMode = Qt.TextElideMode.ElideLeft

    def createEditor(self, parent, option, index):
        path = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole + 1)
        if (index.column() != 1 or not self.panel.mapped or not self.panel.isEnabled()
                or not path or not path.startswith('$') or path not in self.panel.values
                or use_value_dialog(self.panel.values[path])):
            return None
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        path = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole + 1)
        value = self.panel.values[path]
        editor.setText(value if isinstance(value, str) else json.dumps(value))
        editor.setToolTip('Enter text without quotes. Enter applies; Escape cancels.' if isinstance(value, str)
                          else 'Enter a JSON value. Enter applies; Escape cancels.')
        editor.selectAll()

    def setModelData(self, editor, model, index):
        path = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole + 1)
        original = self.panel.values[path]
        try:
            value = editor.text() if isinstance(original, str) else parse_json(editor.text())
            if isinstance(original, bool) and type(value) is not bool:
                raise ValueError('Enter true or false for a boolean value.')
            if type(original) in (int, float) and type(value) not in (int, float):
                raise ValueError('Enter a JSON number for a numeric value.')
            if isinstance(value, (dict, list)):
                raise ValueError('Use Edit Value… from the context menu to enter an object or array.')
        except ValueError as error:
            self.panel.report_message(f'Could not edit value: {error}')
            return
        if type(value) is type(original) and value == original:
            return
        payload = self.panel.payload
        # Close the cell editor before the mapped-data refresh rebuilds its tree.
        def commit():
            if self.panel.payload is payload:
                self.panel.replace_value(value, parts=path_parts(path))
        QTimer.singleShot(0, self.panel, commit)


class DataEditing:
    def install_editing(self, layout):
        self.undo_stack, self.redo_stack = [], []
        self.on_change = None
        self.on_saved = None
        self.save_target = lambda: None
        self.edit_toolbar = ManagerButtons(self)
        layout.addWidget(self.edit_toolbar)
        icons = {
            'Add…': ('list-add', QStyle.StandardPixmap.SP_FileDialogNewFolder),
            'Remove': ('edit-delete', QStyle.StandardPixmap.SP_TrashIcon),
            'Copy': ('edit-copy', QStyle.StandardPixmap.SP_FileIcon),
            'Paste…': ('edit-paste', QStyle.StandardPixmap.SP_DialogOpenButton),
            'Undo': ('edit-undo', QStyle.StandardPixmap.SP_ArrowBack),
            'Redo': ('edit-redo', QStyle.StandardPixmap.SP_ArrowForward),
            'Save': ('document-save', QStyle.StandardPixmap.SP_DialogSaveButton),
            'Save JSON As…': ('document-save-as', QStyle.StandardPixmap.SP_DialogSaveButton),
        }
        self.edit_actions = {}
        for title, callback, shortcut in (
            ('Edit Value…', self.edit_value, None), ('Add…', self.add_value, None),
            ('Remove', self.remove_value, 'Delete'), ('Copy', self.copy_value, QKeySequence.StandardKey.Copy),
            ('Paste…', self.paste_value, QKeySequence.StandardKey.Paste),
            ('Undo', self.undo_data, QKeySequence.StandardKey.Undo),
            ('Redo', self.redo_data, QKeySequence.StandardKey.Redo),
            ('Save', self.save_existing, QKeySequence.StandardKey.Save),
            ('Save JSON As…', self.save_json, QKeySequence.StandardKey.SaveAs),
        ):
            action = QAction(title, self.tree)
            action.triggered.connect(callback)
            if shortcut is not None:
                action.setShortcut(QKeySequence(shortcut))
                action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            self.tree.addAction(action)
            action.setToolTip(title)
            self.edit_actions[title] = action
            if title in icons:
                theme, fallback = icons[title]
                icon = QIcon.fromTheme(theme, self.style().standardIcon(fallback))
                if title == 'Save JSON As…' and not QIcon.hasThemeIcon(theme):
                    image = icon.pixmap(24, 24)
                    painter = QPainter(image)
                    painter.fillRect(13, 12, 11, 12, self.palette().base())
                    painter.setPen(self.palette().text().color())
                    painter.drawText(13, 12, 11, 12, Qt.AlignmentFlag.AlignCenter, '+')
                    painter.end()
                    icon = QIcon(image)
                action.setIcon(icon)
                self.edit_toolbar.addAction(action)
                button = self.edit_toolbar.widgetForAction(action)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                button.setAccessibleName(title)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.edit_menu)
        self.tree.setItemDelegate(DataValueDelegate(self))
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                  QAbstractItemView.EditTrigger.EditKeyPressed)
        self.tree.itemDoubleClicked.connect(self.edit_cell)
        QApplication.clipboard().dataChanged.connect(self.update_edit_actions)
        self.update_edit_actions()

    def edit_cell(self, item, column):
        path = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if path not in self.values or not path.startswith('$'):
            return
        if column != 1 or use_value_dialog(self.values[path]):
            self.edit_value()

    def edit_menu(self, point):
        from .context_menus import populate_data_menu, select_target
        item = self.tree.itemAt(point)
        select_target(self.tree, item)
        menu = QMenu(self)
        populate_data_menu(menu, self, self.tree, item)
        try:
            menu.exec(self.tree.viewport().mapToGlobal(point))
        finally:
            menu.deleteLater()

    def selected_parts(self):
        return path_parts(self.path.text())

    def update_edit_actions(self):
        if not hasattr(self, 'edit_actions'):
            return
        selected = self.mapped and self.path.text().startswith('$')
        for title, action in self.edit_actions.items():
            enabled = selected
            if title == 'Remove':
                enabled = selected and self.path.text() != '$'
            elif title in ('Add…', 'Paste…'):
                enabled = selected and isinstance(self.values.get(self.path.text()), (dict, list))
                if title == 'Paste…':
                    enabled = enabled and bool(QApplication.clipboard().text().strip())
            elif title == 'Undo':
                enabled = bool(self.undo_stack) and self.mapped
            elif title == 'Redo':
                enabled = bool(self.redo_stack) and self.mapped
            elif title in ('Save', 'Save JSON As…'):
                enabled = self.mapped
            action.setEnabled(bool(enabled))

    def json_dialog(self, title, value, *, needs_key=False):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(560, 400)
        layout = QVBoxLayout(dialog)
        key = QLineEdit()
        if needs_key:
            form = QFormLayout()
            form.addRow('Property name', key)
            layout.addLayout(form)
        layout.addWidget(QLabel('Enter JSON: "text", a number, true, false, null, {…}, or […].'))
        editor = QPlainTextEdit(json.dumps(value, ensure_ascii=False, indent=2))
        layout.addWidget(editor)
        error = QLabel()
        error.setWordWrap(True)
        layout.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        result = []
        def accept():
            try:
                parsed = parse_json(editor.toPlainText())
                if needs_key and key.text() in at_path(self.payload, self.selected_parts()):
                    raise ValueError('That property already exists. Choose another name or edit the existing node.')
                result.append((key.text(), parsed))
                dialog.accept()
            except ValueError as problem:
                error.setText(str(problem))
        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        return result[0] if dialog.exec() == QDialog.DialogCode.Accepted else None

    def commit_data(self, candidate, parts=()):
        previous = self.payload
        # Mapping is computed before publishing the new browser state.
        if self.on_change is not None:
            try:
                self.on_change(candidate)
            except Exception as error:
                self.report_message(f'Could not edit data: {error}')
                return False
        self.payload = candidate
        self.undo_stack.append(previous)
        self.redo_stack.clear()
        self.refresh_data(parts)
        return True

    def refresh_data(self, parts=()):
        undo, redo = self.undo_stack, self.redo_stack
        self.search.clear()
        self.set_data(self.payload, mapped=True, fields=self.fields)
        self.undo_stack, self.redo_stack = undo, redo
        item = self.tree.topLevelItem(0)
        for key in parts:
            item.setExpanded(True)
            child_path = f'{item.data(0, Qt.ItemDataRole.UserRole + 1)}[{json.dumps(key, ensure_ascii=False)}]'
            item = next(item.child(index) for index in range(item.childCount())
                        if item.child(index).data(0, Qt.ItemDataRole.UserRole + 1) == child_path)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        if self.on_change is None:
            self.report_message('Matches refreshed. Changes are in memory; use Save or Save As to write them to a file.')
        self.update_edit_actions()

    def replace_value(self, value, *, parts=None):
        parts = self.selected_parts() if parts is None else parts
        candidate = copy.deepcopy(self.payload)
        if parts:
            at_path(candidate, parts[:-1])[parts[-1]] = copy.deepcopy(value)
        else:
            candidate = copy.deepcopy(value)
        return self.commit_data(candidate, parts)

    def edit_value(self):
        if not self.edit_actions['Edit Value…'].isEnabled():
            return
        result = self.json_dialog('Edit JSON Value', at_path(self.payload, self.selected_parts()))
        if result is not None:
            self.replace_value(result[1])

    def insert_value(self, value, key=None):
        parts = self.selected_parts()
        candidate = copy.deepcopy(self.payload)
        target = at_path(candidate, parts)
        if isinstance(target, dict):
            if key is None or key in target:
                raise ValueError('Choose a new property name.')
            target[key] = copy.deepcopy(value)
        elif isinstance(target, list):
            key = len(target)
            target.append(copy.deepcopy(value))
        else:
            raise ValueError('Select an object or array to add to.')
        return self.commit_data(candidate, [*parts, key])

    def add_value(self):
        if not self.edit_actions['Add…'].isEnabled():
            return
        target = at_path(self.payload, self.selected_parts())
        result = self.json_dialog('Add Property' if isinstance(target, dict) else 'Append Array Item', None,
                                  needs_key=isinstance(target, dict))
        if result is not None:
            self.insert_value(result[1], result[0])

    def remove_value(self):
        if not self.edit_actions['Remove'].isEnabled():
            return
        parts = self.selected_parts()
        candidate = copy.deepcopy(self.payload)
        del at_path(candidate, parts[:-1])[parts[-1]]
        self.commit_data(candidate, parts[:-1])

    def copy_value(self):
        if self.edit_actions['Copy'].isEnabled():
            QApplication.clipboard().setText(json.dumps(at_path(self.payload, self.selected_parts()), ensure_ascii=False, indent=2))

    def paste_value(self):
        if not self.edit_actions['Paste…'].isEnabled():
            return
        try:
            value = parse_json(QApplication.clipboard().text())
            target = at_path(self.payload, self.selected_parts())
            key = None
            if isinstance(target, dict):
                key, accepted = QInputDialog.getText(self, 'Paste JSON', 'New property name:')
                if not accepted:
                    return
            self.insert_value(value, key)
        except ValueError as error:
            self.report_message(f'Could not paste JSON: {error}')

    def restore_data(self, source, destination):
        if not source:
            return
        candidate = source[-1]
        if self.on_change is not None:
            try:
                self.on_change(candidate)
            except Exception as error:
                self.report_message(f'Could not restore data: {error}')
                return
        destination.append(self.payload)
        self.payload = source.pop()
        self.refresh_data()

    def undo_data(self):
        self.restore_data(self.undo_stack, self.redo_stack)

    def redo_data(self):
        self.restore_data(self.redo_stack, self.undo_stack)

    def save_existing(self):
        if not self.mapped:
            return
        path = self.save_target()
        if path is None:
            self.save_json()
        else:
            self.write_json(path)

    def write_json(self, filename):
        try:
            path = Path(filename).expanduser().resolve()
            encoded = (json.dumps(self.payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
            output = QSaveFile(str(path))
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(output.errorString())
            if output.write(encoded) != len(encoded):
                output.cancelWriting()
                raise OSError(output.errorString())
            if not output.commit():
                raise OSError(output.errorString())
            if self.on_saved is not None:
                self.on_saved(path)
            self.report_message(f'Saved mapped data: {path}. This file is now the mapped data source.')
        except (OSError, ValueError) as error:
            self.report_message(f'Could not save JSON: {error}')

    def save_json(self):
        if not self.mapped:
            return
        target = self.save_target()
        filename, _ = QFileDialog.getSaveFileName(self, 'Save Mapped JSON As',
                                                 str(target or 'edited-data.json'), 'JSON (*.json);;All Files (*)')
        if filename:
            self.write_json(filename)
