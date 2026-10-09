"""Shared original settings, with Qt controls and conflict-aware persistence."""
from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFontComboBox,
                              QFormLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSpinBox, QTabWidget,
                              QToolButton, QVBoxLayout, QWidget, QMessageBox)
from .occs import CommsSettings
from .storage import write_files

class ActivityLogBridge(QObject):
    message = Signal(str)


class ActivityLogHandler(logging.Handler):
    """Keep diagnostics in the workspace, including messages from worker threads."""
    def __init__(self, workspace):
        super().__init__()
        self.bridge = ActivityLogBridge(workspace)
        self.bridge.message.connect(workspace.log)

    def emit(self, record):
        try:
            self.bridge.message.emit(self.format(record))
        except RuntimeError:
            # The owning workspace may already have closed.
            pass


DEFAULTS = json.loads(Path(__file__).with_name('settings_defaults.json').read_text())


def merge_settings(defaults, payload):
    result = copy.deepcopy(defaults)
    for key, value in payload.items():
        result[key] = merge_settings(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else copy.deepcopy(value)
    return result


class UserSettings(CommsSettings):
    def __init__(self, path=None):
        self.load_error = ''
        try:
            super().__init__(path)
        except (ValueError, OSError) as error:
            self.path = Path(path or Path.home() / '.atool' / '.settings.json')
            self.payload = {}
            self.load_error = str(error)
        self.payload = merge_settings(DEFAULTS, self.payload)
        self.original_bytes = self.path.read_bytes() if self.path.exists() else None

    def section(self, name):
        value = self.payload.get(name, {})
        return value if isinstance(value, dict) else {}

    @property
    def work_dir(self):
        return Path(self.get('work_dir') or Path.home() / '.atool' / 'occs-bundles').expanduser()

    @property
    def shared_dir(self):
        parent = Path.home() / 'clp-working'
        default = parent / 'ATool' if parent.is_dir() else Path.home() / '.atool' / 'shared-workspace'
        return Path(self.get('shared_workspace_dir') or default).expanduser()

    def validate(self, payload):
        for section in DEFAULTS:
            if not isinstance(payload.get(section, {}), dict):
                raise ValueError(f'{section} settings must be a JSON object.')
        occs = payload.get('occs', {})
        try:
            timeout = int(occs.get('request_timeout_seconds', 360))
        except (ValueError, TypeError):
            raise ValueError('Request Timeout must be a positive number of seconds.')
        if timeout < 1:
            raise ValueError('Request Timeout must be a positive number of seconds.')
        pattern = str(occs.get('config_id_filter') or '').strip()
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f'Configuration Filter is not a valid regular expression: {error}') from error
        if occs.get('use_static_xsd_conversion'):
            path = str(occs.get('static_xsd_path') or '').strip()
            if not path or not Path(path).expanduser().is_file():
                raise ValueError('Select an existing XSD before enabling local XML conversion.')

    def save(self, payload=None):
        value = copy.deepcopy(self.payload if payload is None else payload)
        self.validate(value)
        actual = self.path.read_bytes() if self.path.exists() else None
        if actual != self.original_bytes:
            raise ValueError('User settings changed outside ATool. Reopen User Settings before saving.')
        encoded = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        write_files({self.path: encoded})
        self.original_bytes, self.payload = encoded, value


class SettingsDialog(QDialog):
    def __init__(self, workspace, store=None):
        super().__init__(workspace)
        self.workspace, self.store = workspace, store if store is not None else workspace.comms.settings
        self.controls = {}
        self.browse_controls = {}
        self.setWindowTitle('User Settings')
        self.resize(770, 650)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        general = self.add_tab('General')
        self.add_control(general, 'application', 'confirm_on_quit', 'Confirm on Quit', bool)
        self.add_control(general, 'document_display', 'collapse', 'Collapse Documents', bool)
        self.add_control(general, 'content_editor', 'font_family', 'HTML Font', 'font')
        self.add_control(general, 'diagnostics', 'debug_logging', 'Debug Logging', bool)
        comms = self.add_tab('Comms')
        entries = [('cli_path', 'CLI Path', 'file'), ('work_dir', 'Local Package Folder', 'directory'),
                   ('request_timeout_seconds', 'Request Timeout (seconds)', int),
                   ('session_alias', 'Non-Prod Session Alias', str), ('pre_prod_session_alias', 'Pre-Prod Session Alias', str),
                   ('config_source_session_alias', 'Migrate Source Alias', str), ('config_target_session_alias', 'Migrate Target Alias', str),
                   ('config_id_filter', 'Configuration Filter', str), ('shared_workspace_dir', 'Shared Package Folder', 'directory'),
                   ('models_dir', 'Models Folder', 'directory'), ('comms_cache_dir', 'Comms Cache Folder', 'directory'),
                   ('user_name', 'User Name', str), ('retain_lock_after_shared_update', 'Retain Lock After Shared Update', bool),
                   ('use_static_xsd_conversion', 'Use Local XSD Conversion', bool), ('static_xsd_path', 'Static XSD Path', 'file')]
        for key, title, kind in entries:
            self.add_control(comms, 'occs', key, title, kind)
        preview = self.add_tab('Preview Programs')
        for render_type in DEFAULTS['occs']['preview_open_programs']:
            self.add_control(preview, 'preview_open_programs', render_type, render_type, 'file')
        self.status = QLabel(f'Settings file: {self.store.path}')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_tab(self, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, title)
        return form

    def add_control(self, form, section, key, title, kind):
        section_payload = self.store.section('occs').get(section, {}) if section == 'preview_open_programs' else self.store.section(section)
        value = section_payload.get(key, '')
        if kind is bool:
            widget = QCheckBox()
            widget.setChecked(bool(value))
        elif kind is int:
            widget = QSpinBox()
            widget.setRange(1, 2147483)
            try:
                widget.setValue(int(value))
            except (ValueError, TypeError):
                widget.setValue(360)
        elif kind == 'font':
            widget = QFontComboBox()
            widget.insertItem(0, 'System Default')
            widget.setCurrentText(str(value or 'System Default'))
        else:
            widget = QLineEdit(str(value or ''))
            if section == 'occs':
                defaults = {'cli_path': self.store.cli, 'work_dir': str(self.store.work_dir), 'shared_workspace_dir': str(self.store.shared_dir)}
                widget.setPlaceholderText(defaults.get(key, ''))
        self.controls[(section, key)] = widget
        if kind in ('file', 'directory'):
            row = QHBoxLayout()
            row.addWidget(widget)
            browse = QToolButton()
            browse.setText('Browse…')
            self.browse_controls[(section,key)] = browse
            def choose():
                selected = QFileDialog.getExistingDirectory(self, title, widget.text()) if kind == 'directory' else QFileDialog.getOpenFileName(self, title, widget.text(), 'All Files (*)')[0]
                if selected:
                    widget.setText(selected)
            browse.clicked.connect(choose)
            row.addWidget(browse)
            form.addRow(title, row)
        else:
            form.addRow(title, widget)

    def save(self):
        payload = copy.deepcopy(self.store.payload)
        for (section, key), widget in self.controls.items():
            value = widget.isChecked() if isinstance(widget, QCheckBox) else widget.value() if isinstance(widget, QSpinBox) else widget.currentText() if isinstance(widget, QComboBox) else widget.text().strip()
            if section == 'content_editor' and value == 'System Default':
                value = ''
            if section == 'preview_open_programs':
                if not isinstance(payload.get('occs'), dict):
                    payload['occs'] = {}
                if not isinstance(payload['occs'].get(section), dict):
                    payload['occs'][section] = {}
                target = payload['occs'][section]
            else:
                if not isinstance(payload.get(section), dict):
                    payload[section] = {}
                target = payload[section]
            target[key] = value
        try:
            self.store.save(payload)
            self.workspace.comms.settings = self.store
            self.workspace.settings.setValue('documentHierarchy', bool(self.store.section('document_display').get('collapse',False)))
            self.workspace.apply_user_settings()
            self.accept()
        except (ValueError, OSError) as error:
            self.status.setText(str(error))


class SettingsActions:
    def install_settings_actions(self):
        menu = self.menuBar().addMenu('&Settings')
        self.settings_action = self.action('User Settings…', self.open_user_settings)
        menu.addAction(self.settings_action)
        self.apply_user_settings()

    def open_user_settings(self):
        current = getattr(self, 'user_settings_dialog', None)
        if current and current.isVisible():
            current.raise_()
            current.activateWindow()
            return
        try:
            draft = UserSettings(self.comms.settings.path)
            draft.payload['document_display']['collapse'] = self.documents.hierarchy
        except OSError as error:
            self.report_error('User Settings', str(error))
            return
        dialog = SettingsDialog(self,draft)
        self.user_settings_dialog = dialog
        dialog.show()

    def apply_user_settings(self):
        previous = self.refreshing
        self.refreshing = True
        try:
            self.documents.set_hierarchy(self.comms.settings.section('document_display').get('collapse', False))
        finally:
            self.refreshing = previous
        logger = logging.getLogger('atool_qt')
        if not hasattr(self, '_activity_log_handler'):
            for handler in list(logger.handlers):
                if isinstance(handler, ActivityLogHandler) or type(handler) is logging.StreamHandler:
                    logger.removeHandler(handler)
            self._activity_log_handler = ActivityLogHandler(self)
            logger.addHandler(self._activity_log_handler)
        logger.propagate = False
        logger.setLevel(logging.DEBUG if self.comms.settings.section('diagnostics').get('debug_logging') else logging.INFO)
        if hasattr(self, 'content'):
            self.content.apply_settings(self.comms.settings)
        if hasattr(self, 'config_actions'):
            self.update_config_actions()

    def confirm_quit(self):
        if self.comms.settings.section('application').get('confirm_on_quit', True):
            return QMessageBox.question(self, 'Quit ATool', 'Quit ATool?',
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Ok
        return True
