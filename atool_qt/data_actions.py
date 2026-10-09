"""Conversion, generated sample input, and cached layout resolution dialogs."""
from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                              QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                              QTreeWidget, QTreeWidgetItem, QVBoxLayout)
from atool_core.layout_resolver import LayoutResolver, format_report
from .sample_data import SampleBuilder
from .grids import configure_grid


def xml_bill_ids(path):
    result, seen = [], set()
    try:
        for _, element in ElementTree.iterparse(path, events=('end',)):
            if str(element.tag).rsplit('}', 1)[-1] == 'billId':
                value = (element.text or '').strip()
                if value and value not in seen:
                    result.append(value)
                    seen.add(value)
            element.clear()
    except ElementTree.ParseError:
        return []
    return result


def conversion_args(settings, xml_path, reroot='', bill_id=''):
    xml_path = Path(xml_path).expanduser()
    if not xml_path.is_file():
        raise ValueError('Select an existing XML file.')
    args = ['convertxml', '--input', str(xml_path), '--output', str(xml_path.with_suffix('.json')),
            '--timeout', str(settings.timeout_ms)]
    if reroot.strip():
        args += ['--reroot', reroot.strip()]
    if bill_id.strip() and bill_id.strip().casefold() != 'all':
        args += ['--extract', bill_id.strip() if '=' in bill_id else f'billId={bill_id.strip()}']
    if settings.get('use_static_xsd_conversion', False):
        xsd = Path(str(settings.get('static_xsd_path', '') or '')).expanduser()
        if not xsd.is_file():
            raise ValueError('Local XSD conversion is enabled, but the configured XSD file does not exist. Update User Settings.')
        args += ['--xsd', str(xsd)]
    return args


def converted_paths(stdout, output):
    paths = []
    for line in stdout.splitlines():
        match = re.search(r'Converted XML to JSON(?:\s+\[[^\]]+\])?:\s+(.+\.json)\s*$', line)
        if match:
            candidate = Path(match.group(1).strip()).expanduser()
            paths.append(candidate if candidate.is_absolute() else output.parent / candidate)
    return list(dict.fromkeys([*paths, output]))


class LocalJob(QThread):
    completed = Signal(object, str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            result = self.operation()
            self.completed.emit(result, '')
        except Exception as error:
            self.completed.emit(None, str(error))


class XmlConversionDialog(QDialog):
    def __init__(self, workspace, map_after=False):
        super().__init__(workspace)
        self.workspace, self.map_after, self.job = workspace, map_after, None
        self.source_session = workspace.session
        self.setWindowTitle('Convert and Map' if map_after else 'Convert XML')
        self.resize(700, 340)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.xml, self.reroot = QLineEdit(), QLineEdit()
        self.bill = QComboBox()
        self.bill.setEditable(True)
        self.bill.setMinimumContentsLength(20)
        self.bill.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.bill.addItem('All')
        row = QHBoxLayout()
        row.addWidget(self.xml, 1)
        browse = QPushButton('Browse…')
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        form.addRow('XML File', row)
        form.addRow('Reroot (auto)', self.reroot)
        form.addRow('Bill ID', self.bill)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)
        buttons = QHBoxLayout()
        self.run_button = QPushButton('Convert and Map' if map_after else 'Convert')
        self.cancel_button = QPushButton('Cancel Conversion')
        self.cancel_button.setEnabled(False)
        for button in (self.run_button, self.cancel_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.run_button.clicked.connect(self.run_conversion)
        self.cancel_button.clicked.connect(lambda: self.job.cancel() if self.job else None)
        self.xml.editingFinished.connect(self.refresh_bill_ids)
        self.finished.connect(lambda: self.job.cancel() if self.job and not self.job.done else None)

    def browse(self, *, initial=False):
        settings = self.workspace.settings
        directory = settings.value('lastConversionDirectory', '') or settings.value('lastMappingDirectory', '')
        if not directory:
            previous = settings.value('lastDataFile', '')
            directory = str(Path(previous).expanduser().parent) if previous else ''
        selected, _ = QFileDialog.getOpenFileName(self, 'Select XML File', directory, 'XML (*.xml *.XML);;All Files (*)')
        if selected:
            settings.setValue('lastConversionDirectory', str(Path(selected).expanduser().resolve().parent))
            self.xml.setText(selected)
            self.refresh_bill_ids()
        elif initial:
            self.reject()

    def refresh_bill_ids(self):
        try:
            path = Path(self.xml.text()).expanduser()
            values = xml_bill_ids(path) if path.is_file() else []
        except OSError as error:
            self.status.setText(str(error))
            return
        self.bill.clear()
        self.bill.addItems(['All', *values])
        if len(values) == 1:
            self.bill.setCurrentIndex(1)

    def run_conversion(self):
        try:
            args = conversion_args(self.workspace.comms.settings, self.xml.text(), self.reroot.text(), self.bill.currentText())
        except ValueError as error:
            self.status.setText(str(error))
            return
        output = Path(args[args.index('--output') + 1])
        if self.bill.currentText().casefold() == 'all' and self.bill.count() > 2:
            if QMessageBox.question(self, self.windowTitle(), f'File contains {self.bill.count() - 1} Bill IDs. Convert all?') != QMessageBox.StandardButton.Yes:
                return
        if output.exists() and QMessageBox.question(self, self.windowTitle(), f'Overwrite {output}?') != QMessageBox.StandardButton.Yes:
            return
        self.workspace.settings.setValue('lastConversionDirectory', str(Path(self.xml.text()).expanduser().resolve().parent))
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText('Converting XML…')
        self.log.clear()
        self.job = self.workspace.comms.submit(args, lambda result: self.conversion_finished(result, output))
        self.job.output.connect(self.log.insertPlainText)

    def conversion_finished(self, result, output):
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if not result.successful:
            self.status.setText(result.message)
            return
        paths = [path for path in converted_paths(result.stdout, output) if path.is_file()]
        if not paths:
            self.status.setText('Conversion completed, but no generated JSON file was found.')
            return
        self.status.setText('Converted files:\n' + '\n'.join(str(path) for path in paths))
        if self.map_after:
            if self.workspace.session is not self.source_session:
                self.status.setText('Conversion completed. The open package changed; map the generated JSON from the Data menu.')
                return
            if self.workspace.job is not None:
                self.status.setText('Conversion completed. A mapping run is already active; map the generated JSON when it finishes.')
                return
            self.run_button.setEnabled(False)
            self.status.setText('Mapping converted JSON…')
            if not self.workspace.map_file(paths[0], on_complete=self.mapping_finished):
                self.run_button.setEnabled(True)
                self.status.setText('Conversion completed, but mapping could not start. Map the generated JSON from the Data menu.')
        else:
            self.accept()

    def mapping_finished(self, session, error):
        self.run_button.setEnabled(True)
        if error:
            self.status.setText('Mapping failed: ' + error)
        else:
            self.accept()


class SampleDialog(QDialog):
    def __init__(self, workspace, document, payload, report):
        super().__init__(workspace)
        self.setWindowTitle(f"Sample Input — {document['name']}")
        self.resize(860, 640)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Generation Report'))
        self.report = QPlainTextEdit('\n'.join(report))
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(150)
        layout.addWidget(self.report)
        layout.addWidget(QLabel('Generated JSON'))
        self.json = QPlainTextEdit(json.dumps(payload, ensure_ascii=False, indent=2))
        layout.addWidget(self.json, 1)
        row = QHBoxLayout()
        save = QPushButton('Save As…')
        save.clicked.connect(self.save)
        row.addStretch()
        row.addWidget(save)
        layout.addLayout(row)
        self.default_name = re.sub(r'[^A-Za-z0-9]+', '_', document['name']).strip('_').lower() + '_sample_input.json'

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save Generated Sample Input', self.default_name, 'JSON (*.json);;All Files (*)')
        if path:
            try:
                Path(path).write_text(self.json.toPlainText(), encoding='utf-8')
            except OSError as error:
                QMessageBox.critical(self, 'Save Error', str(error))


class ResolveDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        session = workspace.session
        self.document = copy.deepcopy(workspace.selected_record('documents'))
        self.package = session.name
        self.template, self.data = copy.deepcopy(session.payload), copy.deepcopy(session.data)
        self.result, self.job = None, None
        self.setWindowTitle(f"Resolve Layout — {self.document['name']}")
        self.resize(930, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Package: {self.package}    Document: {self.document['name']}"))
        form = QFormLayout()
        self.cache = QLineEdit(str(workspace.comms.settings.get('comms_cache_dir', '') or ''))
        row = QHBoxLayout()
        row.addWidget(self.cache)
        browse = QPushButton('Browse…')
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        form.addRow('Comms cache', row)
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('yyyy-MM-dd')
        from PySide6.QtCore import QDate
        self.date.setDate(QDate.currentDate())
        form.addRow('Effective date', self.date)
        self.page, self.grid_page = QSpinBox(), QSpinBox()
        for widget in (self.page, self.grid_page):
            widget.setRange(1, 2147483647)
            widget.setValue(1)
        form.addRow('PackagePageNum', self.page)
        form.addRow('GRIDPAGENUMBER', self.grid_page)
        row = QHBoxLayout()
        self.layout_picker = QComboBox()
        self.layout_picker.setEditable(True)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self.refresh_layouts)
        row.addWidget(self.layout_picker)
        row.addWidget(refresh)
        form.addRow('Layout', row)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        tree_controls = QHBoxLayout()
        collapse, expand = QPushButton('Collapse All'), QPushButton('Expand All')
        tree_controls.addWidget(collapse)
        tree_controls.addWidget(expand)
        tree_controls.addStretch()
        layout.addLayout(tree_controls)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Layout / Content', 'Kind', 'Match', 'Resolved value'])
        configure_grid(self.tree)
        for column, width in enumerate((320, 100, 65, 220)):
            self.tree.setColumnWidth(column, width)
        self.tree.setAlternatingRowColors(True)
        self.tree.currentItemChanged.connect(self.show_resolved_node)
        collapse.clicked.connect(self.tree.collapseAll)
        expand.clicked.connect(self.tree.expandAll)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.report)
        splitter.setSizes([400, 120])
        layout.addWidget(splitter, 1)
        row = QHBoxLayout()
        self.run_button, self.save_button = QPushButton('Resolve'), QPushButton('Save…')
        self.save_button.setEnabled(False)
        self.run_button.clicked.connect(self.resolve)
        self.save_button.clicked.connect(self.save)
        row.addStretch()
        for button in (self.run_button, self.save_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.date.dateChanged.connect(self.refresh_layouts)
        self.cache.editingFinished.connect(self.refresh_layouts)
        self.refresh_layouts()

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose Comms Cache Directory', self.cache.text())
        if path:
            self.cache.setText(path)
            self.refresh_layouts()

    def resolver(self):
        if not self.cache.text().strip() or not Path(self.cache.text()).expanduser().is_dir():
            raise ValueError('Choose a valid Comms cache directory.')
        return LayoutResolver(Path(self.cache.text()).expanduser(), self.package, self.document['name'], self.data,
                              effective_date=self.date.date().toString('yyyy-MM-dd'),
                              system_fields={'PackagePageNum': self.page.value(), 'GRIDPAGENUMBER': self.grid_page.value()},
                              assembly_template=self.template)

    def refresh_layouts(self, *_):
        try:
            version, names = self.resolver().available_layouts()
            previous = self.layout_picker.currentText()
            self.layout_picker.clear()
            self.layout_picker.addItems(names)
            if previous in names:
                self.layout_picker.setCurrentText(previous)
            self.status.setText(f'{len(names)} layouts from cached version {version}.')
        except (OSError, ValueError, StopIteration) as error:
            self.status.setText(f'Layout choices unavailable: {error}')

    def resolve(self):
        if self.job and self.job.isRunning():
            return
        try:
            resolver = self.resolver()
            name = self.layout_picker.currentText().strip()
            if not name:
                raise ValueError('Choose a layout.')
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return
        self.run_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.result = None
        self.tree.clear()
        self.report.clear()
        self.status.setText(f'Resolving {name}…')
        self.job = self.workspace.run_local_job(lambda: resolver.resolve(name), self.resolved)

    def resolved(self, result, error):
        self.job = None
        self.run_button.setEnabled(True)
        if error:
            self.status.setText(error)
            return
        self.result = result
        self.tree.clear()
        def add_node(node, parent=None):
            kind = node.get('kind', 'condition' if 'expression' in node else 'item')
            name = str(node.get('name') or node.get('expression') or node.get('raw') or kind)
            passed = node.get('passed')
            match = 'PASS' if passed is True else 'FAIL' if passed is False else 'Unknown'
            value = str(node.get('rendered', ''))
            if not value and 'values' in node:
                value = json.dumps(node['values'], ensure_ascii=False)
            item = QTreeWidgetItem([name, kind.title(), match, ' '.join(value.split())])
            item.setData(0, Qt.ItemDataRole.UserRole, node)
            for column in range(4):
                item.setToolTip(column, value if column == 3 else str(node.get('warning') or node.get('path') or item.text(column)))
                if passed is not None:
                    item.setForeground(column, QColor('#0057d9' if passed else '#c52323'))
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            for child in [*node.get('children', []), *node.get('parts', [])]:
                add_node(child, item)
            return item
        document = {key: value for key, value in result.items() if key not in ('layout', 'warnings')}
        document.update(kind='document', name=result['document'], passed=result['document_triggered'], children=[result['layout']])
        root = add_node(document)
        if result.get('warnings'):
            add_node(dict(kind='warnings', name='Warnings', children=[dict(kind='warning', name=warning, warning=warning) for warning in result['warnings']]))
        self.tree.expandToDepth(1)
        self.tree.setCurrentItem(root)
        self.save_button.setEnabled(True)
        self.status.setText(f"Resolved; {len(result.get('warnings', []))} warnings.")

    def show_resolved_node(self, item, previous=None):
        node = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self.report.setPlainText(json.dumps({key: value for key, value in node.items() if key not in ('children', 'parts')}, ensure_ascii=False, indent=2) if node else '')

    def save(self):
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Save Layout Resolution', '', 'Text report (*.txt);;JSON evidence (*.json);;All Files (*)')
        if path:
            output = json.dumps(self.result, ensure_ascii=False, indent=2) + '\n' if Path(path).suffix.lower() == '.json' else format_report(self.result)
            try:
                Path(path).write_text(output, encoding='utf-8')
                self.status.setText(f'Saved {Path(path).name}.')
            except OSError as error:
                self.status.setText(str(error))


class DataMenuActions:
    def install_data_actions(self, menu):
        self.local_jobs = []
        self.convert_action = self.action('Convert…', self.convert_xml)
        self.convert_map_action = self.action('Convert and Map…', lambda: self.convert_xml(map_after=True), 'Ctrl+Shift+M')
        self.generate_action = self.action('Generate Sample…', self.generate_sample)
        self.resolve_action = self.action('Resolve…', self.resolve_layout)
        menu.addActions([self.convert_action, self.convert_map_action])
        menu.addSeparator()
        menu.addActions([self.generate_action, self.resolve_action])
        self.documents.selected.connect(self.update_data_actions)
        self.comms.changed.connect(self.update_data_actions)

    def update_data_actions(self, *_):
        record = self.selected_record('documents')
        available = self.session is not None and not self.package_busy()
        self.convert_map_action.setEnabled(available)
        self.generate_action.setEnabled(available and bool(record and record.get('in_at')))
        self.resolve_action.setEnabled(available and self.session.mapped and bool(record and record.get('in_at')))

    def convert_xml(self, *, map_after=False):
        dialog = XmlConversionDialog(self, map_after)
        self.conversion_dialog = dialog
        dialog.show()
        if map_after:
            QTimer.singleShot(0, lambda: dialog.browse(initial=True) if dialog.isVisible() else None)

    def generate_sample(self):
        record = self.selected_record('documents')
        if not record or not record.get('in_at'):
            return
        self.flush_properties()
        record = self.selected_record('documents')
        fields = [{'path': row['path'], 'name': row['name'], 'descr': row['descr']} for row in self.session.fields]
        builder = SampleBuilder()
        condition = builder._resolve_clause_expression_text_from_entries(self.session.clauses, record['condition'])
        payload, report = builder._generate_sample_input_payload(condition, fields)
        dialog = SampleDialog(self, record, payload, report)
        self.sample_dialog = dialog
        dialog.show()

    def resolve_layout(self):
        if self.session and self.session.mapped and self.selected_record('documents'):
            dialog = ResolveDialog(self)
            self.resolve_dialog = dialog
            dialog.show()

    def run_local_job(self, operation, callback):
        job = LocalJob(operation, self)
        self.local_jobs.append(job)
        job.completed.connect(callback)
        def finished():
            self.local_jobs.remove(job)
            job.deleteLater()
            if self.close_pending and not self.local_jobs:
                self.close()
        job.finished.connect(finished)
        job.start()
        return job
