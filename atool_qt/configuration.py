"""Configuration lifecycle, local shared locks, and lockout controls."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from .grids import configure_grid

from PySide6.QtCore import QDate, QTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTimeEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout)
from .storage import write_files


def normalize_configs(value):
    if not isinstance(value.get('configs'), list):
        return []
    return [{key: str(item.get(key) or '').strip() for key in ('id', 'shortName', 'name', 'description', 'status', 'effectiveAt')}
            for item in value.get('configs', []) if isinstance(item, dict) and item.get('id')]


def config_label(config):
    return str(config.get('shortName') or config.get('name') or '').strip()


def filtered_configs(configs, pattern=''):
    expression = re.compile(pattern) if pattern else None
    return [config for config in configs if config['status'].casefold() != 'closed' and
            (not expression or expression.search(' '.join(config.get(key, '') for key in ('shortName', 'name', 'id'))))]


def login_args(alias, session_path=None):
    args = ['login']
    alias = str(alias or '').strip()
    if not alias:
        return args
    args += ['--session', alias]
    path = Path(session_path or Path.home() / '.occs-session.json')
    try:
        store = json.loads(path.read_text())
        sessions, aliases = store.get('sessions'), store.get('aliases')
        if not isinstance(sessions, dict):
            key = '.'.join(str(store.get(key) or '').strip() for key in ('customer', 'region'))
            tenancy = str(store.get('tenancy') or '').strip()
            sessions = {f'{key}/{tenancy}': store} if key and tenancy else {}
        session_key = aliases.get(alias, alias) if isinstance(aliases, dict) else alias
        session = sessions.get(session_key, {})
        if isinstance(session, dict) and all(session.get(key) for key in ('customer', 'region', 'tenancy')):
            for key in ('customer', 'region', 'tenancy'):
                args += [f'--{key}', str(session[key]).strip()]
    except (ValueError, OSError, AttributeError):
        pass
    return args


class ConfigLockouts:
    def __init__(self, path):
        self.path = Path(path)
        self.original = None

    def read(self):
        self.original = self.path.read_bytes() if self.path.exists() else None
        value = json.loads(self.original) if self.original is not None else {'version': 1, 'locked_config_ids': [], 'lockout_windows': []}
        if not isinstance(value, dict) or not isinstance(value.get('locked_config_ids', []), list) or not isinstance(value.get('lockout_windows', []), list):
            raise ValueError('The shared Config lockout file has invalid contents.')
        value.setdefault('version', 1)
        value.setdefault('locked_config_ids', [])
        value.setdefault('lockout_windows', [])
        return value

    def save(self, payload):
        actual = self.path.read_bytes() if self.path.exists() else None
        if actual != self.original:
            raise ValueError('Config lockouts changed while this operation was open. Refresh and try again.')
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        write_files({self.path: encoded})
        self.original = encoded

    def message(self, config_id, name='', now=None):
        payload = self.read()
        normalized = str(config_id or '').strip().casefold()
        if normalized and any(normalized == str(item).strip().casefold() for item in payload['locked_config_ids']):
            return f"Config {name or 'the selected configuration'} is locked in the shared ATool lockout file."
        now = now or datetime.now(timezone.utc)
        for window in payload['lockout_windows']:
            if not isinstance(window, dict):
                continue
            try:
                start = datetime.fromisoformat(str(window.get('start', '')).replace('Z', '+00:00'))
                end = datetime.fromisoformat(str(window.get('end', '')).replace('Z', '+00:00'))
                if start.tzinfo and end.tzinfo and start <= now < end:
                    return 'A shared Config lockout window is active until ' + end.astimezone().strftime('%Y-%m-%d %H:%M %Z') + '.'
            except ValueError:
                continue
        return ''


def lockout_window(date_text, time_text, zone_name, minutes):
    if int(minutes) < 1:
        raise ValueError('Duration must be greater than zero.')
    zone = ZoneInfo(zone_name)
    start = datetime.strptime(f'{date_text} {time_text}', '%Y-%m-%d %H:%M').replace(tzinfo=zone)
    end = start + timedelta(minutes=int(minutes))
    return {'start': start.isoformat(), 'end': end.isoformat(), 'timezone': zone_name}


class AddLockoutDialog(QDialog):
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.callback = callback
        self.setWindowTitle('Add Config Lockout')
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.date, self.time, self.zone, self.minutes = QDateEdit(), QTimeEdit(), QComboBox(), QSpinBox()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('yyyy-MM-dd')
        self.date.setDate(QDate.currentDate())
        self.time.setDisplayFormat('HH:mm')
        self.time.setTime(QTime.currentTime())
        self.zone.addItems(sorted(available_timezones()))
        local_zone = getattr(datetime.now().astimezone().tzinfo, 'key', '')
        self.zone.setCurrentText(local_zone if local_zone in available_timezones() else 'UTC')
        self.minutes.setRange(1, 5256000)
        self.minutes.setValue(60)
        for title, widget in [('Date', self.date), ('Time (24 hour)', self.time), ('Timezone', self.zone), ('Duration (minutes)', self.minutes)]:
            form.addRow(title, widget)
        layout.addLayout(form)
        self.status = QLabel()
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for signal in (self.date.dateChanged, self.time.timeChanged, self.zone.currentTextChanged, self.minutes.valueChanged):
            signal.connect(self.preview)
        self.preview()

    def value(self):
        return lockout_window(self.date.date().toString('yyyy-MM-dd'), self.time.time().toString('HH:mm'), self.zone.currentText(), self.minutes.value())

    def preview(self, *_):
        value = self.value()
        times = [datetime.fromisoformat(value[key]).astimezone().strftime('%Y-%m-%d %H:%M %Z') for key in ('start', 'end')]
        self.status.setText('Your local time:\nStart: ' + times[0] + '\nEnd: ' + times[1])

    def save(self):
        if self.callback(self.value()):
            self.accept()


class LockoutsDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        self.setWindowTitle('Config Lockouts')
        self.resize(780, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Shared lockout windows block every Config close and migration while active.'))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Start', 'End', 'Timezone', 'Duration'])
        configure_grid(self.tree)
        self.tree.setRootIsDecorated(False)
        layout.addWidget(self.tree, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        for title, callback in [('Refresh', self.refresh), ('Add…', self.add), ('Remove', self.remove)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        self.tree.clear()
        try:
            payload = self.workspace.lockouts().read()
            for value in payload['lockout_windows']:
                if not isinstance(value, dict):
                    continue
                try:
                    start, end = (datetime.fromisoformat(str(value[key]).replace('Z', '+00:00')) for key in ('start', 'end'))
                    zone = ZoneInfo(str(value.get('timezone', 'UTC')))
                    item = QTreeWidgetItem([start.astimezone(zone).strftime('%Y-%m-%d %H:%M'), end.astimezone(zone).strftime('%Y-%m-%d %H:%M'), str(zone), str(end - start)])
                    item.setData(0, Qt.ItemDataRole.UserRole, value)
                    if end.astimezone(timezone.utc) <= datetime.now(timezone.utc):
                        for index in range(4):
                            item.setForeground(index, QColor('#888888'))
                    self.tree.addTopLevelItem(item)
                except (ValueError, KeyError):
                    continue
            self.status.setText(str(self.workspace.lockouts().path))
        except (OSError, ValueError) as error:
            self.status.setText(str(error))

    def mutate(self, operation, description):
        try:
            store = self.workspace.lockouts()
            payload = store.read()
            operation(payload)
            if not self.workspace.require_shared_sync(description):
                return False
            store.save(payload)
            self.refresh()
            return True
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return False

    def add(self):
        dialog = AddLockoutDialog(self, lambda window: self.mutate(lambda payload: payload['lockout_windows'].append(window), 'add this shared Config lockout'))
        self.add_dialog = dialog
        dialog.show()

    def remove(self):
        item = self.tree.currentItem()
        if item and QMessageBox.question(self, 'Remove Lockout', 'Remove the selected shared lockout window?') == QMessageBox.StandardButton.Yes:
            value = item.data(0, Qt.ItemDataRole.UserRole)
            self.mutate(lambda payload: payload.__setitem__('lockout_windows', [row for row in payload['lockout_windows'] if row != value]), 'remove this shared Config lockout')


class ConfigPicker(QDialog):
    def __init__(self, workspace, configs, mode, session_alias):
        super().__init__(workspace)
        self.workspace, self.configs, self.mode, self.session_alias = workspace, configs, mode, session_alias
        self.setWindowTitle({'set': 'Set Active Config', 'list': 'Open Configurations', 'close': 'Close Config'}[mode])
        self.resize(1050 if mode == 'list' else 660, 480 if mode == 'list' else 240)
        layout = QVBoxLayout(self)
        self.status = QLabel(f'Session: {session_alias or "OCCS default session"}')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        if mode == 'list':
            self.search = QLineEdit()
            self.search.setPlaceholderText('Filter configurations')
            layout.addWidget(self.search)
            self.tree = QTreeWidget()
            self.tree.setHeaderLabels(['Lock', 'Short name', 'Name', 'Description', 'Status', 'Effective at'])
            configure_grid(self.tree)
            self.tree.setRootIsDecorated(False)
            layout.addWidget(self.tree, 1)
            self.search.textChanged.connect(self.populate)
            self.tree.currentItemChanged.connect(self.update_controls)
        else:
            self.picker = QComboBox()
            self.picker.setEditable(mode == 'close')
            for config in configs:
                self.picker.addItem(config_label(config), config)
            last = str(workspace.comms.settings.get('last_config_id') or '').casefold()
            for index, config in enumerate(configs):
                if last and last in {config[key].casefold() for key in ('id', 'shortName', 'name')}:
                    self.picker.setCurrentIndex(index)
                    break
            layout.addWidget(self.picker)
        row = QHBoxLayout()
        row.addStretch()
        self.lock_button = None
        if mode == 'list':
            self.lock_button = QPushButton('Lock Configuration')
            self.lock_button.clicked.connect(self.toggle_lock)
            row.addWidget(self.lock_button)
        self.submit_button = QPushButton('Set Config' if mode == 'set' else 'Close Configuration')
        self.submit_button.clicked.connect(self.submit)
        row.addWidget(self.submit_button)
        if mode != 'list':
            cancel = QPushButton('Cancel')
            cancel.clicked.connect(self.close)
            row.addWidget(cancel)
        layout.addLayout(row)
        if mode == 'list':
            self.populate()
        else:
            self.submit_button.setEnabled(bool(configs) or mode == 'close')

    def current(self):
        if self.mode == 'list':
            item = self.tree.currentItem()
            return item.data(0, Qt.ItemDataRole.UserRole) if item else None
        config = self.picker.currentData()
        return config if config and self.picker.currentText() == config_label(config) else None

    def populate(self, *_):
        previous = self.current()
        self.tree.clear()
        try:
            locked = {str(value).casefold() for value in self.workspace.lockouts().read()['locked_config_ids']}
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            locked = set()
        def key(config):
            try:
                return (1, int(config['id']))
            except ValueError:
                return (0, config['id'].casefold())
        for config in sorted(self.configs, key=key, reverse=True):
            if self.search.text().strip().casefold() not in ' '.join(config.values()).casefold():
                continue
            item = QTreeWidgetItem(['Locked' if config['id'].casefold() in locked else '', *[config[key] for key in ('shortName', 'name', 'description', 'status', 'effectiveAt')]])
            item.setData(0, Qt.ItemDataRole.UserRole, config)
            self.tree.addTopLevelItem(item)
            if config == previous:
                self.tree.setCurrentItem(item)
        self.update_controls()

    def update_controls(self, *_):
        config = self.current()
        self.submit_button.setEnabled(bool(config))
        if self.lock_button:
            self.lock_button.setEnabled(bool(config))
            if config:
                try:
                    locked = self.workspace.config_is_locked(config['id'])
                    self.lock_button.setText('Unlock Configuration' if locked else 'Lock Configuration')
                except (ValueError, OSError) as error:
                    self.status.setText(str(error))
                    self.lock_button.setEnabled(False)

    def toggle_lock(self):
        config = self.current()
        if config and self.workspace.toggle_config_lock(config['id'], config_label(config)):
            self.populate()

    def submit(self):
        config = self.current()
        if self.mode == 'set':
            if config and self.workspace.set_active_config(config):
                self.accept()
            return
        # The standalone Close dialog uses the short name, as in the original;
        # the configurations list uses its numeric id.
        identity = (config['id'] if self.mode == 'list' else config['shortName'] or config['id']) if config else self.picker.currentText().strip()
        name = config_label(config) if config else identity
        if identity and self.workspace.close_config(self.session_alias, identity, name, protection_id=config['id'] if config else identity):
            self.accept()


class CreateConfigDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        self.setWindowTitle('Create Config')
        self.resize(640, 280)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Session: ' + (workspace.comms.settings.get('session_alias') or 'OCCS default session')))
        form = QFormLayout()
        self.short_name, self.name, self.description = QLineEdit(), QLineEdit(), QLineEdit()
        for title, widget in [('Short name', self.short_name), ('Name', self.name), ('Description', self.description)]:
            form.addRow(title, widget)
        layout.addLayout(form)
        self.status = QLabel()
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Create')
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def submit(self):
        short = self.short_name.text().strip()
        if not short:
            self.status.setText('A Config short name is required.')
            return
        alias = self.workspace.comms.settings.get('session_alias') or 'OCCS default session'
        if QMessageBox.question(self, 'Confirm Create Config', f'Create open configuration in {alias}?\n\n{short}') != QMessageBox.StandardButton.Yes:
            return
        args = ['create-config', '--short-name', short, '--name', self.name.text().strip() or short,
                '--desc', self.description.text().strip(), '--timeout', str(self.workspace.comms.settings.timeout_ms)]
        def complete(result):
            config = result.value.get('config')
            if not isinstance(config, dict) or not (config.get('id') or config.get('shortName')):
                raise ValueError('Comms did not return the created configuration identity.')
            self.workspace.set_active_config(config)
        self.workspace.run_comms_operation('Create Config', args, complete, require_json=True)
        self.accept()


class ConfigurationActions:
    def install_config_actions(self):
        menu = self.menuBar().addMenu('&Config')
        self.config_actions = {}
        for title, callback in [('Set…', lambda: self.load_configs('set')), ('Lock', self.toggle_active_config_lock),
                                ('Lockouts…', self.open_config_lockouts), ('Create…', self.create_config),
                                ('List', lambda: self.load_configs('list')), ('Close…', lambda: self.load_configs('close')),
                                ('Migrate', self.migrate_config)]:
            action = self.action(title, callback)
            self.config_actions[title] = action
            if title in {'Create…', 'Close…'}:
                menu.addSeparator()
            menu.addAction(action)
        menu.addSeparator()
        self.active_config_action = self.action('Active: (not set)', lambda: None)
        self.active_config_action.setEnabled(False)
        menu.addAction(self.active_config_action)
        self.update_config_actions()

    def lockouts(self):
        return ConfigLockouts(self.comms.settings.shared_dir / 'config-lockouts.json')

    def config_is_locked(self, config_id):
        return any(str(value).strip().casefold() == str(config_id).strip().casefold() for value in self.lockouts().read()['locked_config_ids'])

    def update_config_actions(self):
        name = self.comms.settings.get('active_config_label') or ''
        identity = self.comms.settings.get('last_config_id') or ''
        self.active_config_action.setText('Active: ' + (name or '(not set)'))
        self.config_actions['Lock'].setEnabled(bool(name and identity))
        try:
            self.config_actions['Lock'].setText('Unlock' if identity and self.config_is_locked(identity) else 'Lock')
        except (ValueError, OSError):
            self.config_actions['Lock'].setText('Lock')

    def set_active_config(self, config):
        identity = str(config.get('id') or config.get('shortName') or '').strip()
        if not identity:
            self.report_error('Set Config', 'The selected Config has no usable identifier.')
            return False
        payload = copy.deepcopy(self.comms.settings.payload)
        payload.setdefault('occs', {}).update(last_config_id=identity, last_config_protection_id=identity, active_config_label=config_label(config))
        try:
            self.comms.settings.save(payload)
        except (ValueError, OSError) as error:
            self.report_error('Set Config', str(error))
            return False
        self.update_config_actions()
        self.statusBar().showMessage('Active Config set to ' + config_label(config), 5000)
        if hasattr(self, 'content'):
            self.content.update_save_availability()
        return True

    def load_configs(self, mode):
        alias = self.comms.settings.get('config_source_session_alias', 'np') if mode == 'close' else self.comms.settings.get('session_alias') or ''
        args = ['list-configs', '--timeout', str(self.comms.settings.timeout_ms)]
        if mode == 'close':
            args += ['--session', alias]
        def complete(result):
            configs = normalize_configs(result.value)
            if mode in ('set', 'close'):
                try:
                    configs = filtered_configs(configs, self.comms.settings.get('config_id_filter') or '')
                except re.error as error:
                    self.report_error('Configuration Filter', str(error))
                    configs = filtered_configs(configs)
            dialog = ConfigPicker(self, configs, mode, alias)
            self.config_dialog = dialog
            dialog.show()
        def failed(message):
            if mode == 'close' and QMessageBox.question(self, 'Close Config',
                    f'Could not load open configurations from {alias}.\n\n{message}\n\nContinue with manual configuration entry?') == QMessageBox.StandardButton.Yes:
                self.config_dialog = ConfigPicker(self, [], mode, alias)
                self.config_dialog.show()
        return self.run_comms_operation('Load Configurations', args, complete, require_json=True, on_failure=failed)

    def toggle_active_config_lock(self):
        self.toggle_config_lock(self.comms.settings.get('last_config_id') or '', self.comms.settings.get('active_config_label') or '')

    def toggle_config_lock(self, identity, name=''):
        if not identity:
            return False
        try:
            store = self.lockouts()
            payload = store.read()
            existing = next((value for value in payload['locked_config_ids'] if str(value).strip().casefold() == identity.strip().casefold()), None)
            if QMessageBox.question(self, 'Unlock Config' if existing else 'Lock Config',
                    f"{'Unlock' if existing else 'Lock'} {name or 'the selected configuration'}?" + ('' if existing else '\n\nATool will prevent closing or migrating it.')) != QMessageBox.StandardButton.Yes:
                return False
            payload['locked_config_ids'] = [value for value in payload['locked_config_ids'] if str(value).strip().casefold() != identity.strip().casefold()] if existing else [*payload['locked_config_ids'], identity.strip()]
            if not self.require_shared_sync('update this shared Config lock'):
                return False
            store.save(payload)
            self.update_config_actions()
            return True
        except (ValueError, OSError) as error:
            self.report_error('Config Lockouts', str(error))
            return False

    def open_config_lockouts(self):
        self.lockouts_dialog = LockoutsDialog(self)
        self.lockouts_dialog.show()

    def create_config(self):
        self.create_config_dialog = CreateConfigDialog(self)
        self.create_config_dialog.show()

    def config_lifecycle_allowed(self, identity, name=''):
        try:
            message = self.lockouts().message(identity, name)
        except (ValueError, OSError) as error:
            message = str(error)
        if message:
            self.report_error('Config Protected', message)
            return False
        return True

    def close_config(self, alias, identity, name='', *, protection_id=None):
        if not self.config_lifecycle_allowed(protection_id or identity, name):
            return False
        if QMessageBox.question(self, 'Confirm Close Config', f'Close configuration in {alias or "OCCS default session"}?\n\n{name or identity}') != QMessageBox.StandardButton.Yes:
            return False
        payload = copy.deepcopy(self.comms.settings.payload)
        payload.setdefault('occs', {})['last_config_id'] = identity
        payload['occs']['last_config_protection_id'] = protection_id or identity
        try:
            self.comms.settings.save(payload)
        except (ValueError, OSError) as error:
            self.report_error('Close Config', str(error))
            return False
        args = ['close-config'] + (['--session', alias] if alias else []) + ['--config-id', identity]
        def complete(result):
            if QMessageBox.question(self, 'Close Config', f'{name or "Configuration"} closed.\n\nMigrate now?') == QMessageBox.StandardButton.Yes:
                self.migrate_config(confirm=False)
        self.run_comms_operation('Close Config', args, complete)
        return True

    def migrate_config(self, *, confirm=True):
        settings = self.comms.settings
        source, target = settings.get('config_source_session_alias', 'np'), settings.get('config_target_session_alias', 'pp')
        identity = settings.get('last_config_protection_id') or settings.get('last_config_id') or ''
        if not self.config_lifecycle_allowed(identity):
            return
        if confirm and QMessageBox.question(self, 'Confirm Migrate Config', f'Run OCCS migrate?\n\nSource: {source}\nTarget: {target}') != QMessageBox.StandardButton.Yes:
            return
        aliases = list(dict.fromkeys(alias for alias in (target, source, settings.get('session_alias')) if alias))
        def refresh(remaining):
            if remaining:
                return self.run_comms_operation('Refresh Comms Session ' + remaining[0], login_args(remaining[0]), lambda result: refresh(remaining[1:]))
            if self.config_lifecycle_allowed(identity):
                self.run_comms_operation('Migrate Config', ['migrate', '--source-session', source, '--target-session', target])
        refresh(aliases)
