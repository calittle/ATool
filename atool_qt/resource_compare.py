"""Read-only resource comparisons delegated to OCCS CLI."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTabWidget, QTextBrowser,
    QVBoxLayout, QWidget,
)

VERSIONED_TYPES = {'Content', 'Document', 'Package', 'Chart'}
RESOURCE_TYPES = ('Content', 'Document', 'Package', 'Layout', 'Style', 'Font', 'Chart')


class ResourceCompareDialog(QDialog):
    def __init__(self, workspace, resource_type='Content', name='', version=''):
        super().__init__(workspace)
        self.workspace = workspace
        self.jobs = []
        self.revision = 0
        self.busy = False
        self.markdown = ''
        self.preferred_version = version
        self.setWindowTitle('Compare Versions')
        self.resize(950, 760)
        layout = QVBoxLayout(self)
        self.inputs = QWidget()
        form = QFormLayout(self.inputs)
        self.resource_type = QComboBox()
        self.resource_type.addItems(RESOURCE_TYPES)
        self.resource_type.setCurrentText(resource_type)
        self.resource_name = QLineEdit(name)
        self.mode = QComboBox()
        for label, value in (('Live Comms versions', 'live'), ('Versions in one cache', 'cache'), ('Two cache snapshots', 'snapshots')):
            self.mode.addItem(label, value)
        form.addRow('Resource type', self.resource_type)
        form.addRow('Short name', self.resource_name)
        form.addRow('Source', self.mode)
        self.before_cache, self.after_cache = QLineEdit(), QLineEdit()
        cache = str(workspace.comms.settings.get('comms_cache_dir') or '')
        self.before_cache.setText(cache)
        self.after_cache.setText(cache)
        self.cache_rows = []
        for label, box in (('Before / shared cache', self.before_cache), ('After cache', self.after_cache)):
            row = QWidget()
            controls = QHBoxLayout(row)
            controls.setContentsMargins(0, 0, 0, 0)
            controls.addWidget(box, 1)
            browse = QPushButton('Browse…')
            browse.clicked.connect(lambda checked=False, box=box: self.browse_cache(box))
            controls.addWidget(browse)
            form.addRow(label, row)
            self.cache_rows.append(row)
        versions = QWidget()
        row = QHBoxLayout(versions)
        row.setContentsMargins(0, 0, 0, 0)
        self.before_version, self.after_version = QComboBox(), QComboBox()
        self.load_button = QPushButton('Load Versions')
        for widget in (QLabel('Before'), self.before_version, QLabel('After'), self.after_version, self.load_button):
            row.addWidget(widget)
        self.version_row = versions
        form.addRow('Versions', versions)
        self.include_technical = QCheckBox('Include technical appendix')
        self.include_technical.setToolTip('Append exact identifiers, JSON paths and source values after the contextual report.')
        form.addRow('Report options', self.include_technical)
        layout.addWidget(self.inputs)
        self.hint = QLabel('Compares saved Comms versions or downloaded snapshots. Unsaved ATool edits are not included.')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.status = QLabel('Choose a resource and load its versions.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        self.report = QTextBrowser()
        self.report.setOpenExternalLinks(False)
        self.report.setOpenLinks(False)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.tabs.addTab(self.report, 'Report')
        self.tabs.addTab(self.raw, 'Markdown')
        layout.addWidget(self.tabs, 1)
        buttons = QHBoxLayout()
        self.compare_button = QPushButton('Compare')
        self.cancel_button = QPushButton('Cancel Operation')
        self.copy_button = QPushButton('Copy Markdown')
        self.save_button = QPushButton('Save Markdown…')
        close = QPushButton('Close')
        for button in (self.compare_button, self.cancel_button, self.copy_button, self.save_button, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.include_technical.toggled.connect(self.version_changed)
        self.load_button.clicked.connect(self.load_versions)
        self.compare_button.clicked.connect(self.compare)
        self.cancel_button.clicked.connect(self.cancel)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.markdown))
        self.save_button.clicked.connect(self.save_report)
        close.clicked.connect(self.close)
        self.finished.connect(self.cancel)
        self.resource_type.currentTextChanged.connect(self.source_changed)
        self.resource_name.textChanged.connect(self.source_changed)
        self.mode.currentIndexChanged.connect(self.source_changed)
        self.before_cache.textChanged.connect(self.source_changed)
        self.after_cache.textChanged.connect(self.source_changed)
        self.before_version.currentIndexChanged.connect(self.version_changed)
        self.after_version.currentIndexChanged.connect(self.version_changed)
        self.source_changed()

    @property
    def versioned(self):
        return self.resource_type.currentText() in VERSIONED_TYPES

    def browse_cache(self, box):
        directory = QFileDialog.getExistingDirectory(self, 'Choose Resource Cache', box.text())
        if directory:
            box.setText(directory)

    def clear_report(self):
        self.markdown = ''
        self.raw.clear()
        self.report.clear()
        self.copy_button.setEnabled(False)
        self.save_button.setEnabled(False)

    def version_changed(self, *_):
        self.clear_report()
        self.update_buttons()

    def source_changed(self, *_):
        self.cancel()
        if not self.versioned:
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(2)
            self.mode.blockSignals(False)
        self.mode.setEnabled(self.versioned)
        mode = self.mode.currentData()
        for index, row in enumerate(self.cache_rows):
            visible = mode != 'live' and (index == 0 or mode == 'snapshots')
            row.setVisible(visible)
            self.inputs.layout().labelForField(row).setVisible(visible)
        self.version_row.setVisible(self.versioned)
        self.inputs.layout().labelForField(self.version_row).setVisible(self.versioned)
        self.before_version.clear()
        self.after_version.clear()
        self.clear_report()
        self.status.setText('Load versions to compare.' if self.versioned else
                            'This resource has no explicit versions. Choose two exported cache snapshots.')
        self.update_buttons()

    def update_buttons(self):
        valid = bool(self.resource_name.text().strip())
        mode = self.mode.currentData()
        valid = valid and (mode == 'live' or bool(self.before_cache.text().strip()))
        valid = valid and (mode != 'snapshots' or bool(self.after_cache.text().strip()))
        self.load_button.setEnabled(valid and self.versioned and not self.busy)
        self.compare_button.setEnabled(valid and not self.busy and
                                       (not self.versioned or bool(self.before_version.count() and self.after_version.count())))
        self.cancel_button.setEnabled(self.busy)
        self.inputs.setEnabled(not self.busy)

    def base_args(self):
        return ['compare', self.resource_type.currentText().lower(), self.resource_name.text().strip()]

    def submit(self, args, callback):
        revision = self.revision
        def finished(result):
            if revision != self.revision:
                return
            callback(result)
        self.jobs.append(self.workspace.comms.submit([*args, '--json'], finished, channel='read'))

    def failure(self, result):
        self.busy = False
        message = result.message
        if 'unknown command' in message.casefold() or 'unknown option' in message.casefold():
            message = 'The configured OCCS CLI does not support resource comparison. Select an updated CLI in User Settings.'
        if result.successful:
            message = 'The CLI did not return a supported resource comparison response.'
        self.status.setText(message)
        self.update_buttons()

    def load_versions(self):
        self.cancel()
        self.clear_report()
        self.before_version.clear()
        self.after_version.clear()
        self.busy = True
        self.status.setText('Loading resource versions…')
        self.update_buttons()
        mode = self.mode.currentData()
        sources = [None] if mode == 'live' else [self.before_cache.text().strip()]
        if mode == 'snapshots':
            sources.append(self.after_cache.text().strip())
        loaded = {}
        def received(index, result):
            if not result.successful or not isinstance(result.value, dict):
                self.cancel()
                self.failure(result)
                return
            versions = result.value.get('versions')
            if not isinstance(versions, list) or any(not isinstance(row, dict) or not row.get('shortName') for row in versions):
                self.cancel()
                self.status.setText('The CLI returned an invalid version list.')
                return
            loaded[index] = versions
            if len(loaded) < len(sources):
                return
            self.busy = False
            before, after = loaded[0], loaded.get(1, loaded[0])
            for combo, rows in ((self.before_version, before), (self.after_version, after)):
                combo.addItems([str(row['shortName']) for row in rows])
            if before:
                self.before_version.setCurrentIndex(max(0, len(before) - (2 if mode != 'snapshots' else 1)))
            if after:
                self.after_version.setCurrentIndex(len(after) - 1)
                preferred = self.after_version.findText(self.preferred_version) if self.preferred_version else -1
                if preferred >= 0:
                    self.after_version.setCurrentIndex(preferred)
                    if mode != 'snapshots':
                        if preferred > 0:
                            self.before_version.setCurrentIndex(preferred - 1)
                        elif len(after) > 1:
                            self.before_version.setCurrentIndex(0)
                            self.after_version.setCurrentIndex(len(after) - 1)
            self.status.setText('Ready to compare.' if before and after else 'No versions available on one or both sides.')
            self.update_buttons()
        for index, cache in enumerate(sources):
            args = self.base_args() + (['--cache', cache] if cache else []) + ['--list-versions']
            self.submit(args, lambda result, index=index: received(index, result))

    def compare(self):
        if not self.compare_button.isEnabled():
            return
        self.cancel()
        self.clear_report()
        args = self.base_args()
        if self.include_technical.isChecked():
            args += ['--include-technical']
        mode = self.mode.currentData()
        if mode == 'cache':
            args += ['--cache', self.before_cache.text().strip()]
        elif mode == 'snapshots':
            args += ['--from-cache', self.before_cache.text().strip(), '--to-cache', self.after_cache.text().strip()]
        if self.versioned:
            args += ['--from-version', self.before_version.currentText(), '--to-version', self.after_version.currentText()]
        self.busy = True
        self.status.setText('Comparing resource versions…')
        self.update_buttons()
        def received(result):
            value = result.value if isinstance(result.value, dict) else {}
            report = value.get('report') if isinstance(value, dict) else None
            if (result.cancelled or result.timed_out or result.code not in (0, 2)
                    or value.get('ok') is not True or not isinstance(report, dict)
                    or report.get('schemaVersion') != 'occs-resource-comparison/v1'
                    or not isinstance(value.get('markdown'), str)):
                self.failure(result)
                return
            self.busy = False
            self.markdown = value['markdown']
            self.raw.setPlainText(self.markdown)
            self.report.setMarkdown(self.markdown)
            self.status.setText('Comparison incomplete — review Completeness and scope in the report.' if not report.get('complete') else
                                'Comparison complete — ' + str(report.get('result', '')).capitalize() + '.')
            self.copy_button.setEnabled(True)
            self.save_button.setEnabled(True)
            self.update_buttons()
        self.submit(args, received)

    def cancel(self, *_):
        was_busy = self.busy
        self.revision += 1
        self.busy = False
        for job in self.jobs:
            if not job.done:
                job.cancel()
        self.jobs.clear()
        if hasattr(self, 'cancel_button'):
            if was_busy:
                self.status.setText('Comparison operation cancelled.')
            self.update_buttons()

    def save_report(self):
        if not self.markdown:
            return
        filename, _ = QFileDialog.getSaveFileName(self, 'Save Comparison Report', 'comparison.md', 'Markdown (*.md)')
        if filename:
            try:
                Path(filename).write_text(self.markdown, encoding='utf-8')
                self.status.setText('Report saved: ' + filename)
            except OSError as error:
                self.status.setText('Could not save report: ' + str(error))
