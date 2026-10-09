"""Qt authoring actions shared by managers and application menus."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QEvent, QMimeData
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import QApplication, QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QMessageBox, QSpinBox, QDoubleSpinBox, QToolBar

from .clauses import ClauseComposer
from .editor import PackageEditor
from .data_queries import DataQueries
from .package_documents import PackageDocumentActions
from .occs import CommsService, CommsSettings
from .clause_usage import ClauseUsageActions, clause_token
from .data_actions import DataMenuActions
from .user_settings import SettingsActions, UserSettings
from .configuration import ConfigurationActions
from .operations import OperationActions
from .shared_sync import SharedFolderActions
from .resource_actions import ResourceModelActions
from .content import ContentPanel, ContentDock
from .shared_actions import SharedPackageActions
from .package_downloads import PackageDownloadActions
from .package_publish import PackagePublishActions
from .package_preview import PackagePreviewActions
from .package_email import PackageEmailActions
from .manager_controls import ManagerControlActions


from .status import WorkspaceStatus

class AuthoringActions(WorkspaceStatus, PackageDocumentActions, ClauseUsageActions, DataMenuActions, SettingsActions, ConfigurationActions, OperationActions, SharedFolderActions, ResourceModelActions, SharedPackageActions, PackageDownloadActions, PackagePublishActions, PackagePreviewActions, PackageEmailActions, ManagerControlActions):
    def install_authoring(self):
        self.editor = None
        self.refreshing = False
        self.layout_clipboard = []
        self.layout_clipboard_kind = None
        comms_settings = UserSettings()
        self.comms = CommsService(comms_settings, self)
        if comms_settings.load_error:
            self.log('Could not read User Settings: ' + comms_settings.load_error)
        file_menu = self.menuBar().actions()[0].menu()
        self.save_action = self.action("Save", self.save_package, QKeySequence.StandardKey.Save)
        self.save_as_action = self.action("Save As…", lambda: self.save_package(save_as=True), QKeySequence.StandardKey.SaveAs)
        self.session_action = self.action("Open Session", self.open_last_session, "Ctrl+Shift+O")
        self.storage_action = self.action("Show Local Storage", self.show_local_storage)
        for action in reversed((self.save_action, self.save_as_action, self.session_action, self.storage_action)):
            file_menu.insertAction(file_menu.actions()[0], action)
        edit_menu = self.menuBar().addMenu("&Edit")
        self.undo_action = self.action("Undo", self.undo_change, QKeySequence.StandardKey.Undo)
        self.redo_action = self.action("Redo", self.redo_change, QKeySequence.StandardKey.Redo)
        edit_menu.addActions([self.undo_action, self.redo_action])
        for kind in ("documents", "fields"):
            panel = getattr(self, kind)
            panel.name.setReadOnly(False)
            panel.description.setReadOnly(False)
            self.add_controls(panel, [("Add", lambda checked=False, kind=kind: self.add_record(kind)),
                                      ("Remove", lambda checked=False, kind=kind: self.remove_record(kind)),
                                      ("Apply", lambda checked=False, kind=kind: self.apply_record(kind))])
            if kind == "documents":
                self.trigger_clause_action = self.action("Edit Trigger Clause", lambda: self.show_panel("clauses"))
            else:
                panel.authoring_toolbar.addAction(self.action("Browse Path", self.browse_field_path))
            panel.name.editingFinished.connect(lambda kind=kind: self.apply_record(kind))
            panel.description.installEventFilter(self)
        self.fields.expression.setReadOnly(False)
        self.fields.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.field_copy_action = self.action('Copy', self.copy_fields, QKeySequence.StandardKey.Copy)
        self.field_paste_action = self.action('Paste', self.paste_fields, QKeySequence.StandardKey.Paste)
        for action in (self.field_copy_action, self.field_paste_action):
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            self.fields.tree.addAction(action)
            self.fields.authoring_toolbar.addAction(action)
        self.fields.tree.itemSelectionChanged.connect(self.update_manager_controls)
        QApplication.clipboard().dataChanged.connect(self.update_manager_controls)
        self.fields.required = QCheckBox("Required")
        self.fields.splitter.widget(1).layout().addRow("", self.fields.required)
        self.fields.selected.connect(lambda record: self.fields.required.setChecked(bool(record and record.get("mandatory"))))
        self.fields.expression.installEventFilter(self)
        self.fields.required.clicked.connect(lambda: self.apply_record("fields"))
        self.add_controls(self.layouts, [("Add Layout", lambda: self.add_layout_item("Layout")),
                                         ("Add Content", lambda: self.add_layout_item("Content")),
                                         ("Add Iteration", lambda: self.add_layout_item("Iteration")),
                                         ("Add Field", lambda: self.add_layout_item("Field")),
                                         ("Remove", self.remove_layout_item), ("Up", lambda: self.move_layout_item(-1)),
                                         ("Down", lambda: self.move_layout_item(1)), ("Copy", self.copy_layout),
                                         ("Paste", self.paste_layout), ("Apply", self.apply_layout)])
        for title, callback, shortcut in (('Copy layout items', self.copy_layout, QKeySequence.StandardKey.Copy),
                                          ('Paste layout items', self.paste_layout, QKeySequence.StandardKey.Paste),
                                          ('Remove layout item', self.remove_layout_item, 'Delete')):
            action = self.action(title, callback, shortcut)
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            self.layouts.tree.addAction(action)
        self.layouts.authoring_toolbar.addAction(self.action("Browse Path", self.browse_layout_path))
        self.layouts.authoring_toolbar.addAction(self.action("Evaluate Condition", self.browse_layout_condition))
        self.layouts.details_ready.connect(self.enable_layout_properties)
        self.layouts.name.editingFinished.connect(self.apply_layout)
        self.layouts.path.editingFinished.connect(self.apply_layout)
        self.layouts.condition.installEventFilter(self)
        self.add_controls(self.clauses, [("Add", self.add_clause), ("Delete", self.delete_clause),
                                         ("Save", self.save_clause), ("Find Usage", self.find_clause_usage),
                                         ("Find Raw", lambda: self.find_clause_usage(raw_only=True)),
                                         ("Update Triggers", self.update_clause_triggers),
                                         ("Insert Name", self.insert_clause), ("Apply Composed", self.apply_composed)])
        for widget in (self.clauses.name, self.clauses.description, self.clauses.expression, self.clauses.compose):
            widget.setReadOnly(False)
        data_menu = next(action.menu() for action in self.menuBar().actions() if action.text() == "&Data")
        self.remap_action = self.action("Remap", self.remap_data, "Ctrl+Alt+M")
        data_menu.addAction(self.remap_action)
        self.install_data_actions(data_menu)
        window_menu = self.menuBar().addMenu("&Window")
        for key, title, shortcut in (("documents", "Document Manager", "Ctrl+Shift+P"), ("fields", "Field Manager", "Ctrl+Shift+F"),
                                     ("clauses", "Clause Manager", "Ctrl+Shift+C"), ("layouts", "Layout Manager", "Ctrl+Shift+L"),
                                     ("data", "Data Browser", "Ctrl+Shift+D")):
            window_menu.addAction(self.action(title, lambda checked=False, key=key: self.show_panel(key), shortcut))
        window_menu.addAction(self.action("Arrange", self.reset_layout))
        for panel in (self.documents, self.fields, self.layouts, self.clauses, self.data):
            def focus_search(checked=False, panel=panel):
                panel.search.setFocus()
                panel.search.selectAll()
            action = self.action('Find', focus_search, QKeySequence.StandardKey.Find)
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            panel.addAction(action)

        self.install_package_document_actions()
        self.install_settings_actions()
        self.install_config_actions()
        self.install_resource_model_actions()
        self.content = ContentPanel(self)
        dock = ContentDock('Content Manager', self)
        dock.setObjectName('panel-content')
        dock.setWidget(self.content)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.docks['content'] = dock
        self.tabifyDockWidget(self.docks['layouts'], dock)
        dock.hide()
        self.install_shared_actions()
        self.install_download_actions()
        self.install_publish_actions()
        self.install_preview_actions()
        self.install_email_actions()
        self.install_manager_controls()
        self.restore_original_shortcuts()
        self.restore_original_package_menu()
        window_menu.addAction(self.action('Package Documents', lambda: self.show_panel('documents')))
        window_menu.addAction(self.action('Content Manager', lambda: self.show_panel('content'), 'Ctrl+Shift+H'))
        view_menu = next(action.menu() for action in self.menuBar().actions() if action.text() == '&View')
        view_menu.actions()[0].menu().addAction(dock.toggleViewAction())
        menus = {action.text().replace('&', ''): action for action in self.menuBar().actions()}
        for action in menus.values():
            self.menuBar().removeAction(action)
        for title in ('File', 'Edit', 'Package', 'Resources', 'Model', 'Config', 'Data', 'Settings', 'Window', 'View', 'Help'):
            if title in menus:
                self.menuBar().addAction(menus[title])

    def restore_original_package_menu(self):
        actions = self.package_menu.actions()
        by_text = {action.text().replace('…', '...'): action for action in actions}
        advanced = next(action for action in actions if action.menu() and action.text() == 'Advanced')
        for action in actions:
            self.package_menu.removeAction(action)
        for title in ('Preview...', 'Send Email...', 'Cancel Preview', None,
                      'Open Shared Package...', 'Close Package', None, 'Get Packages from Comms...', None,
                      'Update Shared Package', 'Publish Package to Comms...', 'Check Shared Folder Sync...', None,
                      'Release Shared Package Lock', 'Manual Shared Package Unlock...', None, 'Advanced'):
            if title is None:
                self.package_menu.addSeparator()
            else:
                self.package_menu.addAction(advanced if title == 'Advanced' else by_text[title])

    def restore_original_shortcuts(self, *, platform=None):
        platform = platform or sys.platform
        # Qt maps Ctrl to Command on macOS. Preserve the original Windows Alt
        # bindings alongside familiar Qt defaults, with one owner per shortcut.
        self.open_action.setShortcuts([])
        for action, original, default in ((self.shared_open_action, 'Alt+O', 'Ctrl+O'),
                                           (self.save_action, 'Alt+S', 'Ctrl+S'),
                                           (self.map_action, 'Alt+M', 'Ctrl+M')):
            action.setShortcuts([default] if platform == 'darwin' else [original, default])
        self.redo_action.setShortcuts(['Ctrl+Shift+Z'] if platform == 'darwin' else ['Ctrl+Shift+Z', 'Ctrl+Y'])

    def add_controls(self, panel, actions):
        from .controls import ManagerButtons
        toolbar = ManagerButtons(panel)
        toolbar.setMovable(False)
        for title, callback in actions:
            toolbar.addAction(self.action(title, callback))
        panel.layout().insertWidget(0, toolbar)
        panel.authoring_toolbar = toolbar

    def prepare_editor(self, session):
        if self.editor is None or self.editor.session is not session:
            if self.editor and session.source == self.editor.session.source and session.payload == self.editor.session.payload and session.clauses == self.editor.session.clauses and session.bundle == self.editor.session.bundle:
                self.editor.session = session
            else:
                self.editor = PackageEditor(session)

    def update_authoring_actions(self):
        available = self.session is not None and not self.package_busy()
        for action in (self.save_action, self.save_as_action):
            action.setEnabled(available and self.shared_mode != 'testing')
        self.undo_action.setEnabled(available and bool(self.editor and self.editor.undo_stack))
        self.redo_action.setEnabled(available and bool(self.editor and self.editor.redo_stack))
        self.remap_action.setEnabled(available and bool(self.settings.value("lastDataFile", "")))
        for panel in (self.documents, self.fields, self.layouts, self.clauses):
            panel.authoring_toolbar.setEnabled(available)
        self.update_package_document_actions()
        self.update_data_actions()
        self.update_model_actions()
        self.update_shared_actions()
        self.update_publish_actions()
        self.update_preview_actions()
        self.update_email_actions()
        self.update_manager_controls()
        for panel in (self.documents,self.fields,self.layouts,self.clauses):
            panel.setEnabled(not self.package_busy())
        if self.session:
            self.setWindowTitle(f"{self.session.name} — ATool[*]")
        self.setWindowModified(bool(self.editor and self.editor.dirty))
        self.update_package_status()

    def refresh_edit(self):
        self.set_session(self.session, preserve_selection=True)
        self.enable_layout_properties(self.layouts.tree.currentItem())

    def edit(self, operation):
        if not self.editor or self.package_busy() or self.refreshing:
            return False
        try:
            operation()
            self.refresh_edit()
            return True
        except (ValueError, KeyError, IndexError, OSError) as error:
            self.report_error("Could not apply change", str(error))
            return False

    def selected_record(self, kind):
        panel = getattr(self, kind)
        current = panel.tree.currentItem()
        if current is None or current.data(0, Qt.ItemDataRole.UserRole) is None:
            return None
        index=current.data(0,Qt.ItemDataRole.UserRole)
        records=panel.records()
        return records[index] if isinstance(index,int) and 0<=index<len(records) else None

    def selected_fields(self):
        records = self.fields.records()
        selected = set(self.fields.tree.selectedItems())
        result = []
        for item in self.fields.items():
            index = item.data(0, Qt.ItemDataRole.UserRole)
            if item in selected and not item.isHidden() and isinstance(index, int) and 0 <= index < len(records):
                result.append(records[index])
        return result

    @staticmethod
    def field_clipboard_sources():
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return []
        try:
            text = bytes(mime.data('application/x-atool-fields+json')).decode('utf-8') if mime.hasFormat('application/x-atool-fields+json') else mime.text()
            value = json.loads(text)
        except (ValueError, UnicodeError):
            return []
        sources = value.get('Fields') if isinstance(value, dict) else value
        return sources if isinstance(sources, list) and sources and all(isinstance(item, dict) and isinstance(item.get('Name'), str) and isinstance(item.get('Path'), str) for item in sources) else []

    def copy_fields(self):
        sources = [copy.deepcopy(record['source']) for record in self.selected_fields()]
        if not sources:
            return
        text = json.dumps({'Fields': sources}, ensure_ascii=False, indent=2)
        mime = QMimeData()
        mime.setData('application/x-atool-fields+json', text.encode('utf-8'))
        mime.setText(text)
        QApplication.clipboard().setMimeData(mime)
        self.log(f'Copied {len(sources)} field(s).')

    def paste_fields(self):
        sources = self.field_clipboard_sources()
        if not sources:
            return
        names = []
        if self.edit(lambda: names.extend(self.editor.paste_fields(sources))):
            self.select_name(self.fields, names[0])
            self.fields.tree.clearSelection()
            for item in self.fields.items():
                if item.data(0, Qt.ItemDataRole.UserRole + 4) in names:
                    item.setSelected(True)

    def select_name(self, panel, name):
        panel.search.clear()
        panel.matched_only.setChecked(False)
        for item in panel.items():
            if item.data(0, Qt.ItemDataRole.UserRole + 4) == name:
                panel.tree.setCurrentItem(item)
                parent = item.parent()
                while parent:
                    parent.setExpanded(True)
                    parent = parent.parent()
                return

    def add_record(self, kind):
        if self.editor:
            name = self.editor.add_record(kind)
            self.refresh_edit()
            self.select_name(getattr(self, kind), name)

    def remove_record(self, kind):
        record = self.selected_record(kind)
        if not record or not record.get("in_at", True):
            return
        descendants = sorted(self.editor.document_descendants(record['name']) - {record['name']}) if kind == 'documents' else []
        detail = '\n\nDescendants will also be removed:\n' + '\n'.join(descendants) if descendants else ''
        if QMessageBox.question(self, "Remove", f"Remove {record['name']} from the Assembly Template?{detail}") != QMessageBox.StandardButton.Yes:
            return
        self.edit(lambda: self.editor.remove_record(record, kind))

    def apply_record(self, kind):
        if self.refreshing or not self.editor:
            return
        record = self.selected_record(kind)
        if not record or not record.get("in_at", True):
            return
        panel = getattr(self, kind)
        values = {"$$Id" if kind == "documents" else "Name": panel.name.text(), "Descr": panel.description.toPlainText()}
        if kind == "fields":
            values.update(Path=panel.expression.toPlainText(), Mandatory=panel.required.isChecked())
        values = self.changed_record_values(record, values)
        if values:
            self.edit(lambda: self.editor.update_record(record, values, kind))

    @staticmethod
    def changed_record_values(record, values):
        keys = {"$$Id": "name", "Name": "name", "Descr": "descr", "Path": "path", "Mandatory": "mandatory", "Condition": "condition"}
        return {key: value for key, value in values.items() if value != record.get(keys.get(key, key), "")}

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusOut and not self.refreshing and self.editor:
            if watched is self.documents.description:
                self.apply_record("documents")
            elif watched in (self.fields.description, self.fields.expression):
                self.apply_record("fields")
            elif watched is self.layouts.condition:
                self.apply_layout()
        return super().eventFilter(watched, event)

    def layout_selection(self):
        item = self.layouts.tree.currentItem()
        return item, item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def layout_ancestor(self, kind):
        item, _ = self.layout_selection()
        while item:
            node = item.data(0, Qt.ItemDataRole.UserRole)
            if node["kind"] == kind:
                return node["key"]
            item = item.parent()
        return None

    def select_layout_key(self, key):
        self.layouts.search.clear()
        self.layouts.matched_only.setChecked(False)
        for item in self.layouts.items():
            if item.data(0, Qt.ItemDataRole.UserRole)["key"] == key:
                self.layouts.tree.setCurrentItem(item)
                self.layouts.tree.scrollToItem(item)
                return

    def add_layout_item(self, kind):
        if not self.active_document or not self.active_document.get("in_at", True):
            return
        parent_kind = {"Content": "Layout", "Iteration": "Content", "Field": "Iteration"}.get(kind)
        parent = self.layout_ancestor(parent_kind) if parent_kind else None
        if parent_kind and not parent:
            self.report_error("Select a parent", f"Select a {parent_kind.lower()} before adding a {kind.lower()}.")
            return
        try:
            key = self.editor.add_layout_item(self.active_document, kind, parent)
            self.refresh_edit()
            self.select_layout_key(key)
        except ValueError as error:
            self.report_error("Could not add item", str(error))

    def remove_layout_item(self):
        _, node = self.layout_selection()
        if node and QMessageBox.question(self, "Remove", "Remove this layout item and its children?") == QMessageBox.StandardButton.Yes:
            self.edit(lambda: self.editor.remove_layout_item(self.active_document, node["key"]))

    def move_layout_item(self, direction):
        _, node = self.layout_selection()
        if node:
            key = self.editor.move_layout_item(self.active_document, node["key"], direction)
            self.refresh_edit()
            self.select_layout_key(key)

    def copy_layout(self):
        selected = set(self.layouts.tree.selectedItems())
        current, _ = self.layout_selection()
        if not selected and current:
            selected.add(current)
        nodes = [item.data(0, Qt.ItemDataRole.UserRole) for item in self.layouts.items() if item in selected]
        kinds = {node['kind'] for node in nodes}
        if len(kinds) != 1 or ('Iteration' in kinds and len(nodes) != 1):
            self.report_error('Copy layout items', 'Select items of the same kind, or one iteration, to copy.')
            return
        self.layout_clipboard_kind = kinds.pop()
        self.layout_clipboard = [copy.deepcopy(self.editor.layout_source(self.active_document, node['key'])[0]) for node in nodes]
        self.log(f'Copied {len(nodes)} {self.layout_clipboard_kind.lower()} item(s).')
        self.update_manager_controls()

    def paste_layout(self):
        if not self.layout_clipboard or not self.active_document or not self.active_document.get('in_at', True):
            return
        _, node = self.layout_selection()
        result = []
        def paste():
            result.append(self.editor.paste_layout_items(self.active_document, self.layout_clipboard_kind,
                                                       self.layout_clipboard, node['key'] if node else None))
        if self.edit(paste):
            self.select_layout_key(result[0])

    def enable_layout_properties(self, current, *_):
        panel = self.layouts
        document = self.selected_record('documents')
        editable = bool(current and document and document.get('in_at', True) and self.session and not self.package_busy())
        for widget in (panel.name, panel.condition, panel.path):
            widget.setReadOnly(not editable)
        for key, widget in panel.property_controls.items():
            if isinstance(widget, QCheckBox):
                widget.setEnabled(editable)
            elif isinstance(widget, QComboBox):
                widget.setEnabled(editable)
                if key == "Type":
                    _, node = self.layout_selection()
                    iteration = bool(node and node['kind'] == 'Iteration')
                    widget.setEditable(not iteration)
                    for name in ("Iterator", "Spliterator") if iteration else ():
                        if widget.findText(name) < 0:
                            widget.addItem(name)
            elif hasattr(widget, "setReadOnly"):
                widget.setReadOnly(not editable)
            if not widget.property("authoringConnected"):
                if isinstance(widget, QCheckBox):
                    widget.clicked.connect(self.apply_layout)
                elif isinstance(widget, QComboBox):
                    widget.activated.connect(self.apply_layout)
                    if widget.isEditable():
                        widget.lineEdit().editingFinished.connect(self.apply_layout)
                elif hasattr(widget, "editingFinished"):
                    widget.editingFinished.connect(self.apply_layout)
                widget.setProperty("authoringConnected", True)
        panel.property_baseline = self.layout_values()

    def layout_values(self):
        _, node = self.layout_selection()
        if not node:
            return {}
        source = node["source"]
        name_key = "$$Id" if "$$Id" in source else "Name" if "Name" in source else "Id"
        values = {name_key: self.layouts.name.text(), "Condition": self.layouts.condition.toPlainText()}
        if "Path" in source or node["kind"] in {"Field", "Iteration"}:
            values["Path"] = self.layouts.path.text()
        for key, widget in self.layouts.property_controls.items():
            values[key] = (widget.isChecked() if isinstance(widget, QCheckBox) else widget.currentText() if isinstance(widget, QComboBox)
                           else widget.value() if isinstance(widget, (QSpinBox, QDoubleSpinBox)) else widget.text())
        return values

    def apply_layout(self):
        if self.refreshing or not self.editor:
            return
        item, node = self.layout_selection()
        if not node:
            return
        values = {key: value for key, value in self.layout_values().items()
                  if value != getattr(self.layouts, "property_baseline", {}).get(key)}
        if values:
            self.edit(lambda: self.editor.update_layout(self.active_document, node["key"], values))

    def selected_clause(self):
        item = self.clauses.tree.currentItem()
        return self.clauses.records[item.data(0, Qt.ItemDataRole.UserRole)] if item else None

    def add_clause(self):
        if self.editor:
            name = self.editor.add_clause()
            self.refresh_edit()
            self.clauses.search.setText(name)

    def save_clause(self):
        record = self.selected_clause()
        if record:
            name = self.clauses.name.text().strip()
            if self.edit(lambda: self.editor.save_clause(record["name"], name, self.clauses.description.text(),
                                                         self.clauses.expression.toPlainText())):
                for row in range(self.clauses.tree.topLevelItemCount()):
                    item = self.clauses.tree.topLevelItem(row)
                    if item.text(0) == name:
                        if item.isHidden():
                            self.clauses.search.clear()
                        self.clauses.tree.setCurrentItem(item)
                        self.clauses.tree.scrollToItem(item)
                        break

    def delete_clause(self):
        record = self.selected_clause()
        if record and QMessageBox.question(self, "Delete Clause", f"Delete {record['name']}?") == QMessageBox.StandardButton.Yes:
            self.edit(lambda: self.editor.remove_clause(record["name"]))

    def insert_clause(self):
        name = self.clauses.clause_picker.currentText().strip()
        if name and name in self.clauses.compose.names:
            current = self.clauses.compose.toPlainText().strip()
            token = clause_token(name)
            separator = " " if current.endswith("(") or current.upper().endswith(" OR") else " + "
            self.clauses.compose.setPlainText(current + separator + token if current else token)

    def apply_composed(self):
        try:
            condition = ClauseComposer()._render_composed_condition_with_entries(self.clauses.compose.toPlainText(), self.session.clauses)
        except ValueError as error:
            self.report_error("Invalid composed condition", str(error))
            return
        if self.clauses.target_label.text().startswith("Target: Document"):
            if self.active_document:
                self.edit(lambda: self.editor.update_record(self.active_document, {"Condition": condition}, "documents"))
        else:
            _, node = self.layout_selection()
            if node:
                self.edit(lambda: self.editor.update_layout(self.active_document, node["key"], {"Condition": condition}))


    def undo_change(self):
        if self.editor:
            self.editor.undo()
            self.refresh_edit()

    def redo_change(self):
        if self.editor:
            self.editor.redo()
            self.refresh_edit()

    def confirm_discard(self):
        if self.editor and not self.refreshing:
            try:
                self.flush_properties()
            except ValueError as error:
                self.report_error("Invalid property", str(error))
                return False
        if not self.editor or not self.editor.dirty:
            return True
        answer = QMessageBox.question(self, "Unsaved Changes", "Save changes before continuing?",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_package()
        return answer == QMessageBox.StandardButton.Discard

    def save_package(self, *, save_as=False):
        if self.shared_mode == 'testing':
            self.report_error('Save', 'Testing copies are read-only. Open this shared package for edit before saving changes.')
            return False
        if not self.editor:
            return False
        try:
            self.flush_properties()
        except ValueError as error:
            self.report_error("Could not save", str(error))
            return False
        path = None
        if save_as or self.session.source is None:
            filename, _ = QFileDialog.getSaveFileName(self, "Save Assembly Template", str(self.session.source or "assembly-template.json"), "JSON (*.json)")
            if not filename:
                return False
            path = Path(filename)
        try:
            destination = self.editor.save(path)
        except (OSError, ValueError) as error:
            self.report_error("Could not save", str(error))
            return False
        self.log(f"Saved {destination}")
        if not self.session.bundle:
            self.shared_package_dir, self.shared_mode = None, 'local'
        self.remember_package_session()
        self.refresh_edit()
        return True

    def flush_properties(self):
        # Capture all forms before a model rebuild changes the selected records.
        document = self.selected_record("documents")
        field = self.selected_record("fields")
        _, node = self.layout_selection()
        doc_values = {"$$Id": self.documents.name.text(), "Descr": self.documents.description.toPlainText()}
        field_values = {"Name": self.fields.name.text(), "Descr": self.fields.description.toPlainText(),
                        "Path": self.fields.expression.toPlainText(), "Mandatory": self.fields.required.isChecked()}
        if document and document.get("in_at", True):
            values = self.changed_record_values(document, doc_values)
            if values:
                self.editor.update_record(document, values, "documents")
        if field:
            values = self.changed_record_values(field, field_values)
            if values:
                self.editor.update_record(field, values, "fields")
        if node:
            values = {key: value for key, value in self.layout_values().items()
                      if value != getattr(self.layouts, "property_baseline", {}).get(key)}
            if values:
                self.editor.update_layout(document, node["key"], values)

    def open_last_session(self):
        if self.package_busy():
            return
        path = self.settings.value("lastPackageManifest", "") or self.settings.value("lastPackageFile", "")
        alias = self.settings.value('lastSessionAlias', '')
        data = self.settings.value('lastDataFile', '')
        if not path:
            # Read the original app's session alongside its settings, without
            # modifying it or importing its separate-window geometry.
            state_path = self.comms.settings.path.parent / '.atool.state.json'
            try:
                state = json.loads(state_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                state = {}
            if isinstance(state, dict):
                path = str(state.get('last_occs_bundle') or '').strip()
                alias = str(state.get('last_occs_session_alias') or '').strip()
                data = str(state.get('last_data_file') or '').strip()
        if not path:
            QMessageBox.information(self, "Open Session", "No previous package session is saved.")
            return
        if self.open_package(Path(path).expanduser()):
            if alias:
                self.comms.settings.payload.setdefault('occs', {})['session_alias'] = alias
                self.remember_package_session()
            if data and Path(data).expanduser().is_file():
                self.map_file(Path(data).expanduser())
                self.statusBar().showMessage('Opened last session; mapping last data file.', 5000)
            else:
                self.statusBar().showMessage('Opened last package; '+('previous JSON file was not found.' if data else 'no previous JSON file to map.'), 5000)

    def show_local_storage(self):
        directory = self.comms.settings.work_dir
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
                raise OSError('The system file browser could not open this folder.')
        except OSError as error:
            self.report_error('Show Local Storage', f'Could not open local storage:\n\n{directory}\n\n{error}')

    def remap_data(self):
        path = self.settings.value("lastDataFile", "")
        if path:
            self.map_file(Path(path))

    def browse_query(self, query, mode):
        if not query:
            return
        self.show_panel("data")
        self.data.mode.setCurrentText(mode)
        self.data.search.setText(query)
        self.data.run_search()

    def browse_field_path(self):
        self.browse_query(DataQueries()._field_path_for_data_browser(self.fields.expression.toPlainText()), "JSONPath")

    def browse_layout_path(self):
        _, node = self.layout_selection()
        if not node or node["kind"] not in {"Iteration", "Field"}:
            return
        query = DataQueries()._field_path_for_data_browser(self.layouts.path.text())
        parent = self.layout_ancestor("Iteration") if node["kind"] == "Field" else None
        if parent:
            iteration = self.editor.layout_source(self.active_document, parent)[0]
            query = DataQueries()._layout_field_browser_path(query, str(iteration.get("Path", "")))
        self.browse_query(query, "JSONPath")

    def browse_layout_condition(self):
        self.browse_query(self.layouts.condition.toPlainText(), "Condition")
