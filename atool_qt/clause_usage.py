"""Clause usage and trigger updates, independent of mapped transaction data."""
from __future__ import annotations

import copy
import re

from .grids import configure_grid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QMessageBox,
                              QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout)
from .clauses import ClauseComposer


def clause_token(name):
    return name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', name) else f'CLAUSE{{{name}}}'


def condition_targets(session):
    targets = []
    def add(document, source, kind, key, owner):
        condition = str(source.get('Condition', '')).strip()
        if condition:
            targets.append({'document_name': document['name'], 'kind': kind, 'key': key,
                            'owner': owner, 'condition': condition, 'source': source})
        groups = (('Layouts', 'Layout'), ('Contents', 'Content'), ('Content', 'Content'),
                  ('contents', 'Content'), ('content', 'Content'), ('Fields', 'Field'), ('fields', 'Field'))
        seen = set()
        for property_name, child_kind in groups:
            children = source.get(property_name)
            if not isinstance(children, list) or child_kind in seen:
                continue
            seen.add(child_kind)
            for index, child in enumerate(children):
                if not isinstance(child, dict):
                    continue
                name = str(child.get('$$Id') or child.get('Name') or child.get('Id') or f'{child_kind} {index + 1}')
                child_key = f'layout/{index}' if kind == 'Document' else f'{key}/{property_name}/{index}'
                add(document, child, child_kind, child_key, f'{owner} > {child_kind}: {name}')
        iteration = source.get('Iteration', source.get('iteration'))
        if isinstance(iteration, dict):
            name = str(iteration.get('$$Id') or iteration.get('Name') or 'Iteration')
            add(document, iteration, 'Iteration', f'{key}/Iteration', f'{owner} > Iteration: {name}')
    for document in session.documents:
        if document.get('in_at', True):
            add(document, document['source'], 'Document', None, document['name'])
    return targets


def usage_results(session, clause_name='', raw_only=False):
    composer = ClauseComposer()
    names = {clause_name} if clause_name else set()
    while True:
        additional = {entry['name'] for entry in session.clauses if
                      set(composer._extract_embedded_clause_references(entry['expression'])) & names}
        if additional <= names:
            break
        names |= additional
    results = []
    for target in condition_targets(session):
        try:
            compose, exact, unmatched = composer.compose(target['condition'], session.clauses)
        except ValueError:
            continue
        used = composer._clause_names_in_compose_text(compose)
        raw = composer._raw_fragments_in_compose_text(compose)
        matched = sorted(used & names, key=str.casefold)
        if not (raw if raw_only else matched):
            continue
        match_type = 'Raw fragment' if raw_only else composer._classify_clause_usage_match(compose, matched, clause_name)
        results.append({**target, 'compose_text': compose, 'matched_clauses': matched, 'raw_fragments': raw,
                        'exact': exact, 'unmatched_count': unmatched, 'match_type': match_type})
    return results


def trigger_proposals(session, old_entries, new_entries, changed_name):
    composer = ClauseComposer()
    impacted = composer._find_impacted_clause_names(old_entries, new_entries, changed_clause_name=changed_name)
    proposals = []
    for target in condition_targets(session):
        if target['kind'] != 'Document':
            continue
        try:
            compose, _, _ = composer.compose(target['condition'], old_entries)
        except ValueError:
            continue
        matched = composer._clause_names_in_compose_text(compose) & impacted
        if not matched:
            continue
        new_condition = composer._render_composed_condition_with_entries(compose, new_entries)
        if composer._canonical_condition_expression(new_condition) == composer._canonical_condition_expression(target['condition']):
            continue
        proposals.append({**target, 'old_condition': target['condition'], 'new_condition': new_condition,
                          'compose_text': compose, 'matched_clauses': sorted(matched, key=str.casefold),
                          'match_type': composer._classify_clause_trigger_match(compose, matched, changed_clause_name=changed_name),
                          'status': 'Pending'})
    return proposals


class ConditionUsageDialog(QDialog):
    def __init__(self, workspace, results, title, updates=False):
        super().__init__(workspace)
        self.workspace, self.results, self.updates = workspace, results, updates
        self.source_editor = workspace.editor
        self.source_clauses = copy.deepcopy(workspace.session.clauses)
        self.buttons = {}
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self.resize(960, 650)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.kind_filter = QComboBox()
        self.kind_filter.addItems(['All Types', *sorted({result['kind'] for result in results})])
        header = QHBoxLayout()
        header.addWidget(self.summary, 1)
        header.addWidget(self.kind_filter)
        layout.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels(['Owner', 'Type', 'Match', 'Matched clauses', 'Status' if updates else 'Raw'])
        configure_grid(self.tree)
        self.tree.setSortingEnabled(True)
        splitter.addWidget(self.tree)
        details = QSplitter()
        self.condition, self.compose = QPlainTextEdit(), QPlainTextEdit()
        for text in (self.condition, self.compose):
            text.setReadOnly(True)
            details.addWidget(text)
        splitter.addWidget(details)
        layout.addWidget(splitter, 1)
        actions = QHBoxLayout()
        for title, callback in [('Previous', lambda: self.step(-1)), ('Next', lambda: self.step(1)), ('Select Owner', self.select_owner)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        if updates:
            for title, callback in [('Apply Current', self.apply_current), ('Skip', self.skip_current), ('Apply All', self.apply_all)]:
                button = QPushButton(title)
                button.clicked.connect(callback)
                self.buttons[title] = button
                actions.addWidget(button)
        if updates:
            cancel = QPushButton('Cancel')
            cancel.clicked.connect(self.close)
            actions.addWidget(cancel)
        layout.addLayout(actions)
        self.kind_filter.currentTextChanged.connect(self.populate)
        self.tree.currentItemChanged.connect(self.display)
        self.populate()

    def populate(self, *_):
        previous=self.tree.currentItem()
        selected=previous.data(0, Qt.ItemDataRole.UserRole) if previous else None
        self.tree.clear()
        for index, result in enumerate(self.results):
            if self.kind_filter.currentIndex() and result['kind'] != self.kind_filter.currentText():
                continue
            item = QTreeWidgetItem([result['owner'], result['kind'], result['match_type'], ', '.join(result['matched_clauses']),
                                   result['status'] if self.updates else str(len(result['raw_fragments']))])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            self.tree.addTopLevelItem(item)
        restored=next((self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(index).data(0,Qt.ItemDataRole.UserRole)==selected),self.tree.topLevelItem(0))
        self.tree.setCurrentItem(restored)
        pending = sum(result.get('status') == 'Pending' for result in self.results)
        self.summary.setText(f'{len(self.results)} document triggers; {pending} pending' if self.updates else f'{self.tree.topLevelItemCount()} condition owners')
        self.display()

    def current(self):
        item = self.tree.currentItem()
        return self.results[item.data(0, Qt.ItemDataRole.UserRole)] if item else None

    def display(self, *_):
        result = self.current()
        self.condition.setPlainText(result.get('old_condition', result['condition']) if result else '')
        self.compose.setPlainText(result['new_condition'] if result and self.updates else
                                 result['compose_text'] + '\n\n' + '\n'.join(result['raw_fragments']) if result else '')
        if self.updates:
            for title in ('Apply Current','Skip'):
                self.buttons[title].setEnabled(bool(result and result['status']=='Pending'))
            self.buttons['Apply All'].setEnabled(any(row['status']=='Pending' for row in self.results))

    def step(self, direction):
        index = self.tree.indexOfTopLevelItem(self.tree.currentItem()) + direction
        if 0 <= index < self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(index))

    def select_owner(self):
        if not self.valid_context():
            return
        result = self.current()
        if result:
            targets=condition_targets(self.workspace.session)
            target=next((row for row in targets if row['source'] is result['source']),None)
            if target is None:
                target=next((row for row in targets if row['owner']==result['owner'] and row['kind']==result['kind'] and row['document_name']==result['document_name']),None)
            if target is None:
                self.workspace.report_error('Clause Usage','This condition owner no longer exists. Refresh the usage results.')
                return
            self.workspace.select_name(self.workspace.documents, target['document_name'])
            self.workspace.show_panel('documents' if target['kind'] == 'Document' else 'layouts')
            if target['key']:
                self.workspace.select_layout_key(target['key'])

    def valid_context(self):
        if self.workspace.package_busy():
            self.workspace.report_error('Clause Manager','A package operation is in progress. Try again when it finishes.')
            return False
        if self.workspace.editor is not self.source_editor or not self.workspace.session:
            self.workspace.report_error('Clause Manager', 'The active package changed. Reopen this dialog for the current package.')
            return False
        if self.updates and self.workspace.session.clauses != self.source_clauses:
            self.workspace.report_error('Update Triggers', 'The clause library changed. Rebuild these proposals before applying.')
            return False
        return True

    def current_trigger(self, result):
        record=next((row for row in self.workspace.session.documents if row['name']==result['document_name'] and row.get('in_at',True)),None)
        return str(record['source'].get('Condition','')) if record else None

    def select_next_pending(self):
        count=self.tree.topLevelItemCount()
        start=self.tree.indexOfTopLevelItem(self.tree.currentItem())
        for offset in range(1,count+1):
            item=self.tree.topLevelItem((start+offset)%count)
            if self.results[item.data(0,Qt.ItemDataRole.UserRole)]['status']=='Pending':
                self.tree.setCurrentItem(item)
                return

    def apply_results(self, results):
        if not self.valid_context():
            return False
        pending = [result for result in results if result['status'] == 'Pending']
        if pending and self.workspace.edit(lambda: self.workspace.editor.apply_trigger_proposals(pending)):
            for result in pending:
                result['status'] = 'Applied'
                original=next((row for row in self.results if row['document_name']==result['document_name']),None)
                if original is not None:
                    original['status']='Applied'
            self.populate()
            self.select_next_pending()
            return True
        return False

    def apply_current(self):
        result = self.current()
        if not result or result['status']!='Pending' or not self.valid_context():
            return
        current=self.current_trigger(result)
        if current is None:
            self.workspace.report_error('Update Triggers','The document no longer exists. Rebuild these proposals.')
            return
        canonical=ClauseComposer._canonical_condition_expression
        proposal=result
        if canonical(current)!=canonical(result['old_condition']):
            if QMessageBox.question(self,'Update Document Triggers',f"The trigger for {result['document_name']} changed after this preview. Apply the proposed trigger anyway?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                return
            proposal={**result,'old_condition':current}
        self.apply_results([proposal])

    def skip_current(self):
        result = self.current()
        if result and result['status'] == 'Pending':
            result['status'] = 'Skipped'
            self.populate()
            self.select_next_pending()

    def apply_all(self):
        if not self.valid_context():
            return
        canonical=ClauseComposer._canonical_condition_expression
        pending=[result for result in self.results if result['status']=='Pending']
        valid=[result for result in pending if self.current_trigger(result) is not None and canonical(self.current_trigger(result))==canonical(result['old_condition'])]
        stale=len(pending)-len(valid)
        self.apply_results(valid)
        if stale:
            QMessageBox.warning(self,'Update Document Triggers',f'Skipped {stale} trigger updates because their current triggers no longer match the preview. Rebuild proposals or review each changed trigger.')


class ClauseUsageActions:
    def find_clause_usage(self, *, raw_only=False):
        self.flush_properties()
        record = self.selected_clause()
        if not self.session or (not raw_only and not record):
            return
        results = usage_results(self.session, record['name'] if record else '', raw_only)
        dialog = ConditionUsageDialog(self, results, 'Conditions with Raw Fragments' if raw_only else f"Clause Usage: {record['name']}")
        self.usage_dialog = dialog
        dialog.show()

    def update_clause_triggers(self):
        record = self.selected_clause()
        if not record:
            return
        old_entries = copy.deepcopy(self.session.clauses)
        new_name = self.clauses.name.text().strip()
        if new_name != record['name']:
            self.report_error('Update Triggers', 'Save a clause rename before updating its expression and triggers.')
            return
        new_entries = copy.deepcopy(old_entries)
        next(entry for entry in new_entries if entry['name'] == record['name']).update(
            expression=self.clauses.expression.toPlainText(), description=self.clauses.description.text())
        try:
            proposals = trigger_proposals(self.session, old_entries, new_entries, record['name'])
        except ValueError as error:
            self.report_error('Update Triggers', str(error))
            return
        if not self.edit(lambda: self.editor.save_clause(record['name'], new_name, self.clauses.description.text(), self.clauses.expression.toPlainText())):
            return
        dialog = ConditionUsageDialog(self, proposals, f'Update Document Triggers: {new_name}', updates=True)
        self.trigger_dialog = dialog
        dialog.show()
