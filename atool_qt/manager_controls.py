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
        owner_key = ancestors['Content'] or ancestors['Layout']
        content = self.editor.layout_source(document, owner_key)[0] if document_editable and owner_key else None
        accepts_iteration = bool(content is not None and not isinstance(content.get('Iteration', content.get('iteration')), dict))
        path = str(node['source'].get('Path') or '') if node else ''
        valid_path = DataQueries()._validate_field_path(path)[0] if path else False
        nodes = [item.data(0, Qt.ItemDataRole.UserRole) for item in self.layouts.tree.selectedItems() if not item.isHidden()]
        copy_kinds = {node['kind'] for node in nodes}
        copyable = bool(nodes) and len(copy_kinds) == 1 and (copy_kinds != {'Iteration'} or len(nodes) == 1)
        up = down = False
        if selected:
            try:
                _, siblings, index = self.editor.layout_source(document, node['key'])
            except (KeyError, IndexError, TypeError):
                # Selection signals can fire between a mutation and tree rebuild.
                siblings, index = None, 0
            if isinstance(siblings, list):
                up, down = index > 0, index < len(siblings) - 1
        states = {'Add Layout': document_editable, 'Add Content': document_editable and bool(ancestors['Layout']),
                  'Add Iteration': document_editable and accepts_iteration, 'Add Field': document_editable and bool(ancestors['Iteration']),
                  'Remove': selected, 'Apply': selected, 'Up': up, 'Down': down,
                  'Copy': selected and copyable, 'Paste': document_editable and self.can_paste_layout(),
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
                layout_target = not self.clauses.target_label.text().startswith('Target: Document')
                action.setEnabled(document_editable and (not layout_target or bool(node)))

    def can_paste_layout(self):
        """Check destination eligibility without modifying the editor or its history."""
        kind = self.layout_clipboard_kind
        if not self.layout_clipboard or kind not in {'Layout', 'Content', 'Iteration', 'Field'}:
            return False
        if kind == 'Layout':
            return True
        parent = self.layouts.tree.currentItem()
        wanted = {'Content': {'Layout'}, 'Iteration': {'Content', 'Layout'}, 'Field': {'Iteration'}}[kind]
        while parent is not None:
            node = parent.data(0, Qt.ItemDataRole.UserRole)
            if node['kind'] in wanted:
                if kind != 'Iteration':
                    return True
                source = node['source']
                return (len(self.layout_clipboard) == 1
                        and not isinstance(source.get('Iteration', source.get('iteration')), dict)
                        and (node['kind'] != 'Layout' or self.layout_clipboard[0].get('Type') == 'Spliterator'))
            parent = parent.parent()
        return False
