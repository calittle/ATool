"""Manager toolbar behavior and context-sensitive control states."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from .data_queries import DataQueries


class ManagerControlActions:
    def install_manager_controls(self):
        toolbar = self.documents.authoring_toolbar
        self.document_view_action = self.action('Hierarchy View', self.toggle_document_view)
        self.document_model_action = self.action('Model', lambda: self.document_model(open_after=True,
            regenerate=bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)))
        self.document_model_action.setToolTip('Open the selected document model. Shift-click to regenerate first.')
        self.document_map_action = self.action('Map', self.toggle_mapping)
        self.document_map_action.setToolTip('Map a data file or clear the current map. Shift-click to remap.')
        toolbar.addActions([self.document_view_action, self.document_model_action, self.resolve_action, self.document_map_action])
        # Keep descriptive action names for shortcuts and state handling; buttons
        # use the same compact labels as the original managers.
        labels = {
            'documents': {'Add': '➕ 📄', 'Remove': '➖ 📄', 'Hierarchy View': '📋', 'Flat View': '📋', 'Resolve…': 'Resolve'},
            'fields': {'Add': 'Add Field', 'Remove': 'Remove Field'},
            'layouts': {'Add Layout': '➕ 🧩', 'Add Content': '➕ 📝', 'Up': '⬆️', 'Down': '⬇️',
                        'Add Iteration': '➕ 🔁', 'Add Field': '➕ 🏷️', 'Remove': '➖'},
        }
        for key, mapping in labels.items():
            for action in getattr(self, key).authoring_toolbar.actions():
                if action.text() in mapping:
                    action.setToolTip(action.toolTip() or action.text())
                    action.setIconText(mapping[action.text()])
        self.documents.authoring_toolbar.reorder(['Hierarchy View', 'Model', 'Resolve…', 'Map', 'Add', 'Remove', 'Apply'])
        self.layouts.authoring_toolbar.reorder(['Add Layout', 'Add Content', 'Up', 'Down', 'Add Iteration', 'Add Field', 'Remove', 'Copy', 'Paste', 'Apply', 'Browse Path', 'Evaluate Condition'])
        self.fields.authoring_toolbar.reorder(['Add', 'Remove', 'Copy', 'Paste', 'Apply', 'Browse Path'])
        for action in self.clauses.authoring_toolbar.actions():
            if action.text() in {'Find Usage', 'Find Raw', 'Update Triggers'}:
                action.setIconText(action.text() + '...')
        self.document_view_action.setToolTip('Switch between hierarchy and flat document views.')
        for panel in (self.documents, self.fields):
            panel.selected.connect(self.update_manager_controls)
        self.layouts.tree.currentItemChanged.connect(self.update_manager_controls)
        self.layouts.tree.itemSelectionChanged.connect(self.update_manager_controls)
        self.clauses.tree.currentItemChanged.connect(self.update_manager_controls)
        self.clauses.clause_picker.currentTextChanged.connect(self.update_manager_controls)

    def toggle_document_view(self):
        self.documents.set_hierarchy(not self.documents.hierarchy)
        self.settings.setValue('documentHierarchy', self.documents.hierarchy)
        self.update_manager_controls()

    def toggle_mapping(self):
        if self.package_busy() or not self.session:
            return
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.remap_data()
        elif self.session.mapped:
            self.session.mapped = False
            self.session.data = None
            self.session.data_name = 'No data mapped'
            self.session.mapping_revision += 1
            self.editor.rebuild()
            self.set_session(self.session, preserve_selection=True)
        else:
            self.choose_data()

    def update_manager_controls(self, *_):
        if not hasattr(self, 'document_view_action'):
            return
        available = bool(self.session) and not self.package_busy()
        self.field_copy_action.setEnabled(available and bool(self.selected_fields()))
        self.field_paste_action.setEnabled(available and bool(self.field_clipboard_sources()))
        document = self.selected_record('documents')
        document_editable = available and bool(document and document.get('in_at', True))
        self.document_view_action.setText('Flat View' if self.documents.hierarchy else 'Hierarchy View')
        self.document_view_action.setIconText('📋')
        self.document_view_action.setEnabled(available)
        self.document_model_action.setEnabled(document_editable)
        self.trigger_clause_action.setEnabled(document_editable)
        self.document_map_action.setText('Clear Map' if self.session and self.session.mapped else 'Map')
        self.document_map_action.setEnabled(available)
        for kind in ('documents', 'fields'):
            panel = getattr(self, kind)
            record = self.selected_record(kind)
            selected = available and bool(record and record.get('in_at', True))
            for widget in (panel.name, panel.description):
                widget.setReadOnly(not selected)
            if kind == 'fields':
                panel.expression.setReadOnly(not selected)
                panel.required.setEnabled(selected)
            for action in panel.authoring_toolbar.actions():
                if action.text() in {'Remove', 'Apply', 'Browse Path'}:
                    action.setEnabled(selected)
        _, node = self.layout_selection()
        selected = document_editable and bool(node)
        ancestors = {kind: self.layout_ancestor(kind) for kind in ('Layout', 'Content', 'Iteration')}
        content = self.editor.layout_source(document, ancestors['Content'])[0] if document_editable and ancestors['Content'] else None
        accepts_iteration = bool(content is not None and not isinstance(content.get('Iteration', content.get('iteration')), dict))
        path = str(node['source'].get('Path') or '') if node else ''
        valid_path = DataQueries()._validate_field_path(path)[0] if path else False
        states = {'Add Layout': document_editable, 'Add Content': document_editable and bool(ancestors['Layout']),
                  'Add Iteration': document_editable and accepts_iteration, 'Add Field': document_editable and bool(ancestors['Iteration']),
                  'Remove': selected, 'Apply': selected, 'Up': selected and node['kind'] in {'Layout', 'Content', 'Field'} if node else False,
                  'Down': selected and node['kind'] in {'Layout', 'Content', 'Field'} if node else False,
                  'Copy': selected, 'Paste': document_editable and bool(self.layout_clipboard),
                  'Browse Path': selected and valid_path,
                  'Evaluate Condition': selected and bool(str(node['source'].get('Condition') or '').strip()) if node else False}
        for action in self.layouts.authoring_toolbar.actions():
            if action.text() in states:
                action.setEnabled(states[action.text()])
        clause = self.selected_clause()
        for widget in (self.clauses.name, self.clauses.description, self.clauses.expression):
            widget.setReadOnly(not (available and bool(clause)))
        for action in self.clauses.authoring_toolbar.actions():
            if action.text() in {'Save', 'Delete', 'Find Usage'}:
                action.setEnabled(available and bool(clause))
            elif action.text() == 'Insert Name':
                action.setEnabled(available and bool(self.clauses.clause_picker.currentText()))
            elif action.text() == 'Apply Composed':
                action.setEnabled(document_editable)
