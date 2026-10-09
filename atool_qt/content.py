"""Dockable Comms Content browser, version editor, and scoped field palette."""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

from .grids import configure_grid

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDockWidget, QFileDialog, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


def content_fields(session, content_name):
    """AT globals plus iterator fields belonging to this particular Content."""
    definitions = {}
    def name(value):
        return str(value.get('name') or value.get('Name') or value.get('$$Id') or value.get('Id') or '').strip()
    def walk(value):
        if isinstance(value, dict):
            iteration = value.get('Iteration', value.get('iteration'))
            if name(value) == content_name and isinstance(iteration, dict) and name(iteration):
                values = iteration.get('Fields', iteration.get('fields', []))
                values = values if isinstance(values, list) else []
                fields = [{'name': name(field), 'scope': 'Iteration', 'path': str(field.get('Path', ''))}
                          for field in values if isinstance(field, dict) and name(field)]
                definitions.setdefault(name(iteration), dict(name=name(iteration), path=str(iteration.get('Path', '')),
                    condition=str(iteration.get('Condition', '')), type=str(iteration.get('Type', '')), fields=fields))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(session.payload if session else {})
    fields = [{'name': str(field['name']), 'scope': 'AT', 'path': str(field.get('path', ''))}
              for field in (session.fields if session else [])]
    fields.extend(field for definition in definitions.values() for field in definition['fields'])
    unique = {(field['name'], field['scope']): field for field in fields}
    return sorted(unique.values(), key=lambda field: (field['name'].casefold(), field['scope'])), list(definitions.values())


class ContentDock(QDockWidget):
    def closeEvent(self, event):
        if self.widget().confirm_discard('hiding Content Manager'):
            super().closeEvent(event)
        else:
            event.ignore()


class ContentPanel(QWidget):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        self.mode, self.baseline, self.loading, self.saving = 'create', None, False, False
        self.request_revision = self.list_revision = 0
        self.restore_state = None
        self.rich = None
        outer = QVBoxLayout(self)
        self.splitter = QSplitter()
        outer.addWidget(self.splitter, 1)
        browser = QWidget()
        browser.setMinimumWidth(200)
        browser.setMaximumWidth(310)
        browser_layout = QVBoxLayout(browser)
        row = QHBoxLayout()
        self.list_config, self.list_all = QPushButton('List from Config'), QPushButton('List…')
        self.new, self.load = QPushButton('New'), QPushButton('Load')
        for button in (self.list_config, self.list_all):
            row.addWidget(button)
        browser_layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.new)
        row.addWidget(self.load)
        browser_layout.addLayout(row)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Filter content (required for List; Shift lists all)')
        browser_layout.addWidget(self.filter)
        self.content_type = QComboBox()
        self.content_type.addItems(['All', 'Text', 'Image', 'Link', 'Chart'])
        browser_layout.addWidget(self.content_type)
        self.browser = QTreeWidget()
        self.browser.setHeaderLabels(['Short Name', 'Type'])
        configure_grid(self.browser)
        self.browser.setSortingEnabled(True)
        self.browser.sortItems(0, Qt.SortOrder.AscendingOrder)
        browser_layout.addWidget(self.browser, 1)
        self.browser_status = QLabel('List content to browse available resources.')
        self.browser_status.setWordWrap(True)
        browser_layout.addWidget(self.browser_status)
        self.splitter.addWidget(browser)
        self.editor_panel = QWidget()
        self.editor_panel.setMinimumWidth(480)
        editor_layout = QVBoxLayout(self.editor_panel)
        form = QFormLayout()
        self.short_name, self.name, self.description = QLineEdit(), QLineEdit(), QLineEdit()
        self.version, self.version_description, self.effective_date = QComboBox(), QLineEdit(), QLineEdit()
        self.version.setEditable(True)
        for title, control in [('Short Name', self.short_name), ('Name', self.name), ('Description', self.description),
                               ('Version', self.version), ('Version Description', self.version_description), ('Effective Date', self.effective_date)]:
            form.addRow(title, control)
        editor_layout.addLayout(form)
        toolbar = QToolBar()
        self.new_version = toolbar.addAction('New Version', self.prompt_new_version)
        self.save_button = toolbar.addAction('Save to Comms', self.save_content)
        toolbar.addAction('Open HTML…', self.open_html)
        toolbar.addAction('Save HTML As…', self.save_html)
        editor_layout.addWidget(toolbar)
        self.tabs = QTabWidget()
        self.rich_placeholder = QWidget()
        QVBoxLayout(self.rich_placeholder)
        self.tabs.addTab(self.rich_placeholder, 'Rich HTML')
        self.source = QPlainTextEdit()
        self.source.setPlaceholderText('HTML source, including Comms field, condition, and loop markup')
        self.tabs.addTab(self.source, 'Source HTML')
        # WebEngine starts only when this panel's rich editor is actually requested.
        self.tabs.setCurrentIndex(1)
        editor_layout.addWidget(self.tabs, 1)
        self.palette = QTabWidget()
        self.palette.setMaximumHeight(220)
        self.fields = QTreeWidget()
        self.fields.setHeaderLabels(['Name', 'Scope', 'Path'])
        configure_grid(self.fields)
        fields_panel = QWidget()
        fields_layout = QVBoxLayout(fields_panel)
        self.field_filter = QLineEdit()
        self.field_filter.setPlaceholderText('Filter fields')
        fields_layout.addWidget(self.field_filter)
        fields_layout.addWidget(self.fields)
        insert = QPushButton('Insert Field')
        fields_layout.addWidget(insert)
        self.palette.addTab(fields_panel, 'Fields')
        self.styles = QTreeWidget()
        self.styles.setHeaderLabels(['Style', 'Classes'])
        configure_grid(self.styles)
        self.palette.addTab(self.styles, 'Styles')
        self.metadata = QPlainTextEdit()
        self.metadata.setReadOnly(True)
        self.palette.addTab(self.metadata, 'Metadata')
        editor_layout.addWidget(self.palette)
        self.status = QLabel()
        self.status.setWordWrap(True)
        editor_layout.addWidget(self.status)
        self.splitter.addWidget(self.editor_panel)
        self.splitter.setSizes([280, 720])
        self.list_config.clicked.connect(lambda: self.list_contents('config', True))
        self.list_all.clicked.connect(lambda: self.list_contents('all', bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)))
        self.filter.returnPressed.connect(lambda: self.list_contents('all'))
        self.new.clicked.connect(self.new_content)
        self.load.clicked.connect(self.load_selected)
        self.browser.itemDoubleClicked.connect(lambda *_: self.load_selected())
        self.browser.itemSelectionChanged.connect(self.update_save_availability)
        self.version.activated.connect(self.select_version)
        self.short_name.textChanged.connect(self.refresh_fields)
        for control in (self.short_name, self.name, self.description, self.version_description, self.effective_date):
            control.textChanged.connect(self.update_save_availability)
        self.version.editTextChanged.connect(self.update_save_availability)
        self.source.textChanged.connect(self.source_changed)
        self.field_filter.textChanged.connect(self.filter_fields)
        insert.clicked.connect(self.insert_field)
        self.fields.itemDoubleClicked.connect(lambda *_: self.insert_field())
        self.tabs.currentChanged.connect(self.ensure_rich)
        self.reset_new()

    def snapshot(self):
        return tuple(control.text().strip() for control in (self.short_name, self.name)) + (
            self.version.currentText().strip(), self.effective_date.text().strip(), self.description.text().strip(),
            self.version_description.text().strip(), self.source.toPlainText())

    @property
    def dirty(self):
        return self.baseline is not None and self.snapshot() != self.baseline

    def confirm_discard(self, action='continuing'):
        if self.saving or self.loading:
            self.status.setText('Wait for the current Content operation, or cancel it, before ' + action + '.')
            return False
        if not self.dirty:
            return True
        return QMessageBox.question(self, 'Unsaved Content', 'Discard Content changes before ' + action + '?',
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def update_save_availability(self, *_):
        if not hasattr(self, 'save_button'):
            return
        busy = self.loading or self.saving
        config = bool(self.workspace.comms.settings.get('last_config_id'))
        self.save_button.setEnabled(config and self.dirty and not busy)
        self.save_button.setToolTip('Active Config: ' + str(self.workspace.comms.settings.get('active_config_label') or self.workspace.comms.settings.get('last_config_id') or '(none)'))
        self.new_version.setEnabled(config and self.mode == 'version' and bool(self.short_name.text()) and bool(self.version.currentText()) and not busy)
        self.load.setEnabled(bool(self.browser.currentItem()) and not busy)
        self.new.setEnabled(not busy)
        self.editor_panel.setEnabled(not busy)

    def reset_new(self):
        self.request_revision += 1
        self.mode = 'create'
        for control in (self.short_name, self.name, self.description, self.version_description):
            control.clear()
        self.version.clear()
        self.version.addItem('1.0')
        self.effective_date.setText(date.today().isoformat())
        self.source.setPlainText('')
        self.styles.clear()
        self.metadata.clear()
        self.refresh_fields()
        self.baseline = self.snapshot()
        self.status.setText('New Content. Save to Comms uses the active Config.')
        self.update_save_availability()

    def new_content(self):
        if self.confirm_discard('creating new Content'):
            self.reset_new()

    def list_contents(self, scope='all', bypass=False):
        config = str(self.workspace.comms.settings.get('last_config_id') or '')
        if scope == 'config' and not config:
            self.error('Set an active Config before listing its Content.')
            return
        query = self.filter.text().strip()
        if scope == 'all' and not query and not bypass:
            self.error('Enter a filter, or hold Shift while selecting List to list all Content.')
            return
        args = ['content', 'list', '--timeout', str(self.workspace.comms.settings.timeout_ms)]
        if scope == 'config':
            args += ['--config-id', config]
        if query:
            args += ['--filter', query]
        if self.content_type.currentText() != 'All':
            args += ['--type', self.content_type.currentText()]
        self.list_revision += 1
        revision = self.list_revision
        self.browser_status.setText('Listing Content…')
        def loaded(result):
            if revision != self.list_revision:
                return
            contents = result.value.get('contents', [])
            if not isinstance(contents, list):
                raise ValueError('Content list returned an invalid contents array.')
            self.browser.clear()
            for content in contents:
                if not isinstance(content, dict) or not content.get('shortName'):
                    continue
                item = QTreeWidgetItem([str(content['shortName']), str(content.get('contentType', ''))])
                item.setData(0, Qt.ItemDataRole.UserRole, content)
                self.browser.addTopLevelItem(item)
            count = self.browser.topLevelItemCount()
            self.browser_status.setText(f'Showing first {count} Content items. Refine the filter for more.' if result.value.get('truncated') else f'{count} Content items')
            resolved = result.value.get('configId')
            if scope == 'config' and isinstance(resolved, dict):
                identity = str(resolved.get('id') or resolved.get('resolved') or '')
                label = str(resolved.get('shortName') or resolved.get('name') or '')
                if identity.casefold() == config.casefold() and config == str(self.workspace.comms.settings.get('last_config_id') or '') and label:
                    self.workspace.comms.settings.payload['occs']['active_config_label'] = label
                    try:
                        self.workspace.comms.settings.save()
                    except (OSError, ValueError) as error:
                        self.error(str(error))
                    self.workspace.update_config_actions()
            self.update_save_availability()
            if self.rich:
                self.rich.set_context(self.available_fields, self.iterations)
        self.read_operation('List Content', args, loaded, require_json=True, channel='read',
            on_failure=lambda message: self.browser_status.setText(message) if revision == self.list_revision else None)

    def load_selected(self):
        item = self.browser.currentItem()
        if item:
            self.inspect_content(item.text(0))

    def inspect_content(self, short_name):
        if not self.confirm_discard('loading ' + short_name):
            return
        self.restore_state = self.capture_state()
        self.request_revision += 1
        revision = self.request_revision
        self.loading = True
        self.update_save_availability()
        def loaded(result):
            if revision != self.request_revision:
                return
            content, versions = result.value.get('content'), result.value.get('versions', [])
            if not isinstance(content, dict) or not content.get('shortName') or not isinstance(versions, list):
                self.read_failed('Invalid Content metadata response.', revision)
                return
            self.mode = 'version'
            self.short_name.setText(str(content['shortName']))
            self.name.setText(str(content.get('name') or ''))
            self.description.setText(str(content.get('description') or ''))
            self.version.clear()
            self.version.addItems([str(item['shortName']) for item in versions if isinstance(item, dict) and item.get('shortName')])
            self.metadata.setPlainText(json.dumps(result.value, indent=2, ensure_ascii=False))
            if self.version.count():
                self.read_version(self.short_name.text(), self.version.currentText())
            else:
                self.loading = False
                self.source.clear()
                self.version_description.clear()
                self.effective_date.clear()
                self.styles.clear()
                self.baseline = self.snapshot()
                self.status.setText('This Content has no versions.')
                self.update_save_availability()
        self.read_operation('Inspect Content', ['content', 'inspect', short_name, '--timeout', str(self.workspace.comms.settings.timeout_ms)],
            loaded, require_json=True, channel='read', on_failure=lambda message: self.read_failed(message, revision))

    def select_version(self, *_):
        selected = self.version.currentText().strip()
        # Choosing a version alone must not make the previous version look edited.
        previous = self.baseline[2] if self.baseline else ''
        self.version.setCurrentText(previous)
        if self.confirm_discard('loading version ' + selected):
            self.version.setCurrentText(selected)
            self.read_version(self.short_name.text().strip(), selected)

    def read_operation(self, title, args, callback, **kwargs):
        failure = kwargs.get('on_failure')
        job = self.workspace.run_comms_operation(title, args, callback, **kwargs)
        def finished(result):
            if failure and (result.cancelled or (result.successful and not isinstance(result.value, dict))):
                failure(result.message if result.cancelled else 'The command did not return a JSON object.')
        job.completed.connect(finished)
        return job

    def capture_state(self):
        return dict(snapshot=self.snapshot(), baseline=self.baseline, mode=self.mode,
            versions=[self.version.itemText(index) for index in range(self.version.count())],
            metadata=self.metadata.toPlainText(),
            styles=[[self.styles.topLevelItem(index).text(column) for column in range(2)] for index in range(self.styles.topLevelItemCount())])

    def read_failed(self, message, revision):
        if revision == self.request_revision:
            self.request_revision += 1
            if self.restore_state:
                state = self.restore_state
                short_name, name, version, effective, description, version_description, html = state['snapshot']
                self.short_name.setText(short_name)
                self.name.setText(name)
                self.description.setText(description)
                self.version.clear()
                self.version.addItems(state['versions'])
                self.version.setCurrentText(version)
                self.effective_date.setText(effective)
                self.version_description.setText(version_description)
                self.source.setPlainText(html)
                self.baseline, self.mode = state['baseline'], state['mode']
                self.metadata.setPlainText(state['metadata'])
                self.styles.clear()
                for values in state['styles']:
                    QTreeWidgetItem(self.styles, values)
            self.loading = False
            self.status.setText(message)
            self.update_save_availability()

    def read_version(self, short_name, version):
        if not self.loading:
            self.restore_state = self.capture_state()
            if self.baseline and self.short_name.text() == self.baseline[0]:
                saved = self.restore_state['snapshot']
                self.restore_state['snapshot'] = saved[:2] + (self.baseline[2],) + saved[3:]
        self.request_revision += 1
        revision = self.request_revision
        self.loading = True
        self.update_save_availability()
        self.status.setText(f'Loading {short_name} version {version}…')
        self.styles.clear()
        def loaded(result):
            if revision != self.request_revision:
                return
            metadata = result.value.get('version')
            html = result.value.get('html')
            if not isinstance(metadata, dict) or not isinstance(html, str):
                self.read_failed('Invalid Content version response.', revision)
                return
            self.version.setCurrentText(str(metadata.get('shortName') or version))
            self.version_description.setText(str(metadata.get('description') or ''))
            self.effective_date.setText(str(metadata.get('effectiveDate') or '').split('T')[0])
            self.source.setPlainText(html)
            self.loading = False
            self.baseline = self.snapshot()
            self.status.setText(f'Loaded {short_name} version {version}.')
            self.update_save_availability()
        def styles_loaded(result):
            if revision != self.request_revision:
                return
            self.styles.clear()
            for style in result.value.get('styles', []):
                if isinstance(style, dict):
                    QTreeWidgetItem(self.styles, [str(style.get('shortName') or style.get('name') or style.get('styleUuid') or '(style)'),
                        ', '.join(map(str, style.get('classNames', [])))])
        timeout = ['--timeout', str(self.workspace.comms.settings.timeout_ms)]
        self.read_operation('Read Content', ['content', 'read', short_name, version] + timeout, loaded,
            require_json=True, channel='read', on_failure=lambda message: self.read_failed(message, revision))
        self.read_operation('Content Styles', ['content', 'styles', short_name, version] + timeout, styles_loaded,
            require_json=True, channel='read', on_failure=lambda _: QTreeWidgetItem(self.styles, ['Unavailable', '']) if revision == self.request_revision else None)

    def refresh_fields(self, *_):
        self.available_fields, self.iterations = content_fields(getattr(self.workspace, 'session', None), self.short_name.text().strip())
        self.fields.clear()
        for field in self.available_fields:
            QTreeWidgetItem(self.fields, [field['name'], field['scope'], field['path']])
        self.filter_fields()
        if self.rich:
            self.rich.set_context(self.available_fields, self.iterations)

    def filter_fields(self, *_):
        query = self.field_filter.text().casefold()
        for index in range(self.fields.topLevelItemCount()):
            item = self.fields.topLevelItem(index)
            item.setHidden(query not in ' '.join(item.text(column) for column in range(3)).casefold())

    def insert_field(self):
        item = self.fields.currentItem()
        if not item or self.loading or self.saving:
            return
        markup = '<comms-data>$Data' + json.dumps({'Id': item.text(0)}, ensure_ascii=False, separators=(',', ':')) + '</comms-data>'
        if self.tabs.currentIndex() == 0 and self.rich:
            self.rich.insert_markup(markup)
        else:
            self.source.insertPlainText(markup)

    def source_changed(self):
        if self.rich and not self.rich.updating_source:
            self.rich.set_html(self.source.toPlainText())
        self.update_save_availability()

    def ensure_rich(self, index):
        if index != 0:
            return
        if self.rich is None:
            from .rich_content import RichContentEditor
            self.rich = RichContentEditor(self)
            self.rich_placeholder.layout().addWidget(self.rich)
        self.rich.set_context(self.available_fields, self.iterations)
        self.rich.set_html(self.source.toPlainText())

    def apply_settings(self, settings=None):
        settings = (settings or self.workspace.comms.settings).section('content_editor')
        self.source.setFont(QFont(str(settings.get('font_family') or 'Menlo'), int(settings.get('font_size') or 12)))
        if self.rich:
            self.rich.set_context(self.available_fields, self.iterations)
        self.update_save_availability()

    def open_html(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Open Content HTML', '', 'HTML (*.html *.htm);;All Files (*)')
        if filename:
            try:
                self.source.setPlainText(Path(filename).read_text(encoding='utf-8'))
                self.status.setText('Loaded ' + Path(filename).name)
            except (OSError, UnicodeError) as error:
                self.error(str(error))

    def save_html(self):
        def save():
            filename, _ = QFileDialog.getSaveFileName(self, 'Save Content HTML', self.short_name.text() + '.html', 'HTML (*.html *.htm)')
            if filename:
                try:
                    Path(filename).write_text(self.source.toPlainText(), encoding='utf-8')
                except OSError as error:
                    self.error(str(error))
        self.capture(save)

    def capture(self, callback):
        if self.rich and self.tabs.currentIndex() == 0:
            self.rich.capture(callback)
        else:
            callback()

    def error(self, message):
        self.workspace.report_error('Content Manager', message)

    def save_content(self):
        self.capture(self.submit_save)

    def valid_upload(self, snapshot):
        config = str(self.workspace.comms.settings.get('last_config_id') or '')
        if not config:
            raise ValueError('Set an active Config before saving Content.')
        if not snapshot[0] or not snapshot[2] or not snapshot[3] or not snapshot[6].strip():
            raise ValueError('Short Name, Version, Effective Date, and HTML are required.')
        try:
            if date.fromisoformat(snapshot[3]).isoformat() != snapshot[3]:
                raise ValueError()
        except ValueError:
            raise ValueError('Effective Date must be a valid date in YYYY-MM-DD format.')
        return config

    def submit_save(self):
        if self.loading or self.saving:
            return
        snapshot = self.snapshot()
        try:
            config = self.valid_upload(snapshot)
        except ValueError as error:
            self.error(str(error))
            return
        if QMessageBox.question(self, 'Confirm Content Save', f'Save {snapshot[0]} version {snapshot[2]} using Config {config}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        temporary = self.upload_file(snapshot[6])
        if not temporary:
            return
        short_name, name, version, effective, description, version_description, _ = snapshot
        if self.mode == 'create':
            args = ['content', 'create', short_name, '--config-id', config, '--html', str(temporary), '--version', version]
            if name:
                args += ['--name', name]
            if description:
                args += ['--desc', description]
            args += ['--effective-date', effective]
        else:
            args = ['content', 'save', short_name, version, '--config-id', config, '--html', str(temporary),
                '--short-name', short_name, '--name', name, '--desc', description, '--version-desc', version_description]
        args += ['--timeout', str(self.workspace.comms.settings.timeout_ms)]
        def saved(_):
            self.mode = 'version'
            self.baseline = snapshot
            self.status.setText(f'Saved {short_name} version {version}.')
        self.run_upload('Save Content', args, temporary, saved)

    def upload_file(self, html):
        path = None
        try:
            with tempfile.NamedTemporaryFile(prefix='atool-content-', suffix='.html', mode='w', encoding='utf-8', delete=False) as stream:
                path = Path(stream.name)
                stream.write(html)
            return path
        except OSError as error:
            if path:
                path.unlink(missing_ok=True)
            self.error(str(error))
            return None

    def run_upload(self, title, args, temporary, callback):
        self.saving = True
        self.update_save_availability()
        self.status.setText(title + '…')
        def finish(result):
            temporary.unlink(missing_ok=True)
            self.saving = False
            if not result.successful or not isinstance(result.value, dict):
                self.status.setText(result.message if not result.successful else 'The command did not return a JSON object.')
            self.update_save_availability()
        try:
            job = self.workspace.run_comms_operation(title, args, callback, require_json=True)
            job.completed.connect(finish)
            # Also supports immediate completion by a local/test command adapter.
            if job.done:
                temporary.unlink(missing_ok=True)
                self.saving = False
                self.update_save_availability()
        except Exception:
            temporary.unlink(missing_ok=True)
            self.saving = False
            self.update_save_availability()
            raise

    def prompt_new_version(self):
        new_version, accepted = QInputDialog.getText(self, 'New Content Version', 'Version name:')
        if not accepted or not new_version.strip():
            return
        effective, accepted = QInputDialog.getText(self, 'New Content Version', 'Effective date (YYYY-MM-DD):', text=date.today().isoformat())
        if accepted:
            self.capture(lambda: self.create_version(new_version.strip(), effective.strip()))

    def create_version(self, new_version, effective):
        if self.loading or self.saving:
            return
        snapshot = self.snapshot()
        if self.mode == 'create' or not snapshot[0] or not snapshot[2]:
            self.error('Load or save Content before creating a new version.')
            return
        try:
            config = self.valid_upload(snapshot[:2] + (new_version, effective) + snapshot[4:])
        except ValueError as error:
            self.error(str(error))
            return
        if not new_version or new_version == snapshot[2]:
            self.error('Enter a new version name.')
            return
        if QMessageBox.question(self, 'Create Content Version', f'Create {new_version} from {snapshot[2]} for {snapshot[0]} using Config {config}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        temporary = self.upload_file(snapshot[6])
        if not temporary:
            return
        args = ['content', 'version', snapshot[0], new_version, '--config-id', config, '--from-version', snapshot[2],
                '--html', str(temporary), '--effective-date', effective]
        def created(_):
            self.version.setCurrentText(new_version)
            self.read_version(snapshot[0], new_version)
        self.run_upload('Create Content Version', args, temporary, created)
