"""Package membership controls integrated into Document Manager."""
from __future__ import annotations

import json
from pathlib import Path

from .grids import configure_grid

from PySide6.QtCore import Qt, QMimeData, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                              QMessageBox, QPlainTextEdit, QPushButton, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout)


from .package_responses import PackageResponses
from .validation import PayloadValidation


CATALOG_ALIASES = {
    'uuid': ('uuid', 'documentConfigUuid', 'CommunicationDocumentConfigUuid'),
    'shortName': ('shortName', 'documentShortName', 'ShortName'),
    'name': ('name', 'documentName', 'Name'),
    'description': ('description', 'documentDescription', 'Desc'),
    'configId': ('configId', 'documentConfigId', 'ConfigId'),
}


def document_item_name(item):
    return item.data(0, Qt.ItemDataRole.UserRole + 4) or item.text(0)


class PackageDocumentTree(QTreeWidget):
    reorder_requested = Signal(list, object)
    mime_type = 'application/x-atool-package-documents'

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def startDrag(self, supported_actions):
        items = self.selectedItems()
        if not items or any(not item.data(0, Qt.ItemDataRole.UserRole + 3) for item in items):
            return
        names = [document_item_name(item) for item in items]
        data = QMimeData()
        data.setData(self.mime_type, json.dumps(names).encode('utf-8'))
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.source() is self and event.mimeData().hasFormat(self.mime_type):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if event.source() is not self or not event.mimeData().hasFormat(self.mime_type):
            event.ignore()
            return
        names = json.loads(bytes(event.mimeData().data(self.mime_type)))
        item = self.itemAt(event.position().toPoint())
        if item and document_item_name(item) in names:
            event.ignore()
            return
        before = document_item_name(item) if item else None
        if item and event.position().y() > self.visualItemRect(item).center().y():
            following = self.itemBelow(item)
            before = document_item_name(following) if following else None
        self.reorder_requested.emit(names, before)
        event.acceptProposedAction()


def catalog_documents(payload):
    items = payload.get('documents') if isinstance(payload, dict) else payload
    result, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        row = {key: next((str(item[name]).strip() for name in names if item.get(name) not in (None, '')), '')
               for key, names in CATALOG_ALIASES.items()}
        if row['uuid'] and row['uuid'] not in seen:
            seen.add(row['uuid'])
            result.append(row)
    return sorted(result, key=lambda row: (row['shortName'].casefold(), row['name'].casefold()))


class CatalogDialog(QDialog):
    def __init__(self, service, cache_path=None, associate_name='', parent=None):
        super().__init__(parent)
        self.service = service
        self.cache_path = Path(cache_path or Path.home() / '.atool' / 'document-catalog.json')
        self.associate_name, self.job = associate_name, None
        self.setWindowTitle('Associate Document' if associate_name else 'Add Package Document')
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a document by short name, name, or description')
        self.search.setClearButtonEnabled(True)
        row = QHBoxLayout()
        row.addWidget(self.search, 1)
        self.refresh = QPushButton('Refresh from Comms')
        self.cancel_request = QPushButton('Cancel Refresh')
        self.cancel_request.setEnabled(False)
        row.addWidget(self.refresh)
        row.addWidget(self.cancel_request)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Short name', 'Name', 'Description'])
        configure_grid(self.tree)
        self.tree.setRootIsDecorated(False)
        layout.addWidget(self.tree, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add_button = buttons.addButton('Associate' if associate_name else 'Add', QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)
        buttons.rejected.connect(self.reject)
        self.add_button.clicked.connect(self.accept_selection)
        self.tree.itemDoubleClicked.connect(self.accept_selection)
        self.tree.currentItemChanged.connect(lambda: self.add_button.setEnabled(bool(self.tree.currentItem())))
        self.search.textChanged.connect(self.filter)
        self.refresh.clicked.connect(self.refresh_catalog)
        self.cancel_request.clicked.connect(lambda: self.job.cancel() if self.job else None)
        self.finished.connect(lambda: self.job.cancel() if self.job and not self.job.done else None)
        self.load_catalog()

    @property
    def selected_document(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def load_catalog(self):
        try:
            payload = json.loads(self.cache_path.read_text(encoding='utf-8')) if self.cache_path.exists() else []
            self.documents = catalog_documents(payload)
        except (ValueError, OSError) as error:
            self.status.setText(f'Could not read the document catalog: {error}')
            self.documents = []
        self.tree.clear()
        for document in self.documents:
            if self.associate_name and document['shortName'].casefold() != self.associate_name.casefold():
                continue
            item = QTreeWidgetItem([document['shortName'], document['name'], document['description']])
            item.setData(0, Qt.ItemDataRole.UserRole, document)
            self.tree.addTopLevelItem(item)
        self.filter()
        self.add_button.setEnabled(False)
        if not self.tree.topLevelItemCount():
            self.status.setText('No matching cached documents. Refresh from Comms to retrieve the catalog.')

    def filter(self):
        query = self.search.text().strip().casefold()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            item.setHidden(not PackageResponses()._fuzzy_text_match(query, ' '.join(item.text(column) for column in range(3))))
        current = self.tree.currentItem()
        if current and current.isHidden():
            self.tree.setCurrentItem(None)
        self.add_button.setEnabled(bool(self.selected_document))

    def accept_selection(self, *_):
        if self.selected_document and not self.tree.currentItem().isHidden():
            self.accept()

    def refresh_catalog(self):
        if self.job and not self.job.done:
            return
        self.refresh.setEnabled(False)
        self.cancel_request.setEnabled(True)
        self.status.setText('Refreshing document catalog…')
        args = ['documents', 'catalog', '--output', str(self.cache_path), '--timeout', str(self.service.settings.timeout_ms), '--json']
        if self.search.text().strip():
            args += ['--name', self.search.text().strip()]
        self.job = self.service.submit(args, self.refresh_finished)

    def refresh_finished(self, result):
        self.refresh.setEnabled(True)
        self.cancel_request.setEnabled(False)
        if result.successful and isinstance(result.value, dict):
            self.load_catalog()
            self.status.setText(f'{len(self.documents)} documents in the catalog.')
        else:
            self.status.setText(result.message if not result.successful else 'The catalog request did not return a valid JSON object.')


class PackageConditionDialog(QDialog):
    def __init__(self, workspace, record):
        super().__init__(workspace)
        self.workspace, self.session = workspace, workspace.session
        self.name, self.original = record['name'], str(record['source'].get('Condition') or '')
        self.setWindowTitle('Package Document Condition — ' + self.name)
        self.setModal(True)
        self.resize(720, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Condition for ' + self.name))
        self.condition = QPlainTextEdit(self.original)
        layout.addWidget(self.condition, 1)
        row = QHBoxLayout()
        row.addStretch()
        cancel, apply = QPushButton('Cancel'), QPushButton('Apply Condition')
        cancel.clicked.connect(self.reject)
        apply.clicked.connect(self.apply)
        row.addWidget(cancel)
        row.addWidget(apply)
        layout.addLayout(row)

    def apply(self):
        workspace = self.workspace
        text = self.condition.toPlainText()
        issues, warnings = PayloadValidation._at_condition_validation_messages(text)
        if issues:
            workspace.report_error('Invalid Condition', '\n'.join(issues))
            return
        if warnings and QMessageBox.question(self, 'Review Condition', '\n'.join(warnings) + '\n\nApply it anyway?') != QMessageBox.StandardButton.Yes:
            return
        current = next((record for record in workspace.session.documents if record['name'] == self.name), None) if workspace.session is self.session else None
        if not current or not current.get('in_at') or str(current['source'].get('Condition') or '') != self.original:
            workspace.report_error('Condition Changed', 'The document changed while this editor was open. Reopen its condition before applying.')
            return
        if workspace.edit(lambda: workspace.editor.update_record(current, {'Condition': text}, 'documents')):
            workspace.select_name(workspace.documents, self.name)
            self.accept()


class PackageDocumentActions:
    def install_package_document_actions(self):
        panel = self.documents
        from .controls import ManagerButtons
        panel.package_toolbar = ManagerButtons(panel)
        panel.package_toolbar.setMovable(False)
        panel.layout().insertWidget(1, panel.package_toolbar)
        self.package_actions = {}
        for title, callback in [('Move Up', lambda: self.move_package_document(-1)),
                                ('Move Down', lambda: self.move_package_document(1)),
                                ('Add Package Document', self.add_package_document),
                                ('Associate', lambda: self.add_package_document(associate=True)),
                                ('Remove Association', self.remove_package_association),
                                ('Edit Package Condition', self.edit_package_condition),
                                ('Refresh', self.refresh_package_documents)]:
            action = self.action(title, callback)
            action.setIconText({'Add Package Document': 'Add...', 'Associate': 'Associate...', 'Remove Association': 'Remove', 'Edit Package Condition': 'Edit Condition JSON'}.get(title, title))
            if title == 'Edit Package Condition':
                action.setText('Edit Condition JSON')
                action.setToolTip('Edit the package condition JSON.')
            else:
                panel.package_toolbar.addAction(action)
            self.package_actions[title] = action
        panel.authoring_toolbar.addActionGroup([self.trigger_clause_action, self.package_actions['Edit Package Condition']])
        panel.always_trigger.clicked.connect(self.set_document_always_trigger)
        panel.selected.connect(self.update_package_document_actions)
        panel.tree.reorder_requested.connect(self.reorder_package_documents)

    def reorder_package_documents(self, names, before_name):
        if self.edit(lambda: self.editor.reorder_associations(names, before_name)) and names:
            self.select_name(self.documents, names[0])

    def update_package_document_actions(self, *_):
        record = self.selected_record('documents')
        available = bool(self.editor and self.session.bundle and not self.package_busy())
        associated = bool(record and record.get('associated'))
        for title, action in self.package_actions.items():
            if title in {'Add Package Document', 'Refresh'}:
                enabled = available
            elif title in {'Associate', 'Edit Package Condition'}:
                enabled = available and bool(record and record.get('in_at')) and (not associated if title == 'Associate' else True)
            else:
                enabled = available and associated
            action.setEnabled(enabled)
        self.documents.always_trigger.setEnabled(available and associated)

    def refresh_package_documents(self):
        if self.editor and not self.package_busy():
            try:
                self.flush_properties()
                self.editor.rebuild()
                self.refresh_edit()
            except (ValueError, OSError) as error:
                self.report_error('Package Documents', str(error))

    def edit_package_condition(self):
        record = self.selected_record('documents')
        if record and record.get('in_at') and not self.package_busy():
            self.package_condition_dialog = PackageConditionDialog(self, record)
            self.package_condition_dialog.show()

    def set_document_always_trigger(self):
        record = self.selected_record('documents')
        if record:
            self.edit(lambda: self.editor.set_always_trigger(record, self.documents.always_trigger.isChecked()))

    def move_package_document(self, direction):
        record = self.selected_record('documents')
        if record:
            name = record['name']
            if self.edit(lambda: self.editor.move_association(record, direction)):
                self.select_name(self.documents, name)

    def remove_package_association(self):
        record = self.selected_record('documents')
        if record and QMessageBox.question(self, 'Remove Association',
                f"Remove {record['name']} from this package?") == QMessageBox.StandardButton.Yes:
            self.edit(lambda: self.editor.remove_association(record))

    def add_package_document(self, *, associate=False):
        if not self.session or not self.session.bundle:
            self.report_error('Package Documents', 'Open a package bundle first.')
            return
        record = self.selected_record('documents')
        name = record['name'] if associate and record else ''
        dialog = CatalogDialog(self.comms, associate_name=name, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            added_name = dialog.selected_document['shortName']
            if self.edit(lambda: self.editor.add_association(dialog.selected_document)):
                self.select_name(self.documents, added_name)
