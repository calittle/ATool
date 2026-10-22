"""Send mapped data using a Communication distribution route selected from Comms."""
import copy
import json
import os
from pathlib import Path

from atool_core.email_input import email_payload, email_recipients, prepare_email_input
from atool_core.email_catalog import email_route_profiles, email_session_target

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QStandardItem, QTextOption
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListView, QMessageBox, QPlainTextEdit, QPushButton, QStyledItemDelegate, QVBoxLayout


def recipient_addresses(text):
    """Keep entered order while treating address casing as insignificant."""
    addresses = {}
    for address in text.split(','):
        address = address.strip()
        if address:
            addresses.setdefault(address.casefold(), address)
    return list(addresses.values())


class RecipientPicker(QComboBox):
    """Editable recipients with a popup that stays open for multiple choices."""
    def __init__(self, addresses, text, *, multiple=True):
        super().__init__()
        self.multiple = multiple
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumContentsLength(38)
        self.setMaxVisibleItems(12)
        self.setView(QListView())
        self.setItemDelegate(QStyledItemDelegate(self))
        # Completion would replace the entire comma-separated recipient list.
        self.setCompleter(None)
        for address in addresses:
            item = QStandardItem(address)
            if multiple:
                item.setCheckable(True)
            self.model().appendRow(item)
        self.setCurrentIndex(-1)
        self.setEditText(text)
        self.lineEdit().setPlaceholderText('Type email addresses, separated by commas')
        if multiple:
            self.view().viewport().installEventFilter(self)
            self.view().installEventFilter(self)

    def showPopup(self):
        if self.multiple:
            selected = {value.casefold() for value in recipient_addresses(self.currentText())}
            for row in range(self.count()):
                self.model().item(row).setCheckState(
                    Qt.CheckState.Checked if self.itemText(row).casefold() in selected else Qt.CheckState.Unchecked)
        super().showPopup()

    def toggle_recipient(self, row):
        if not 0 <= row < self.count():
            return
        address = self.itemText(row)
        addresses = recipient_addresses(self.currentText())
        if address.casefold() in {value.casefold() for value in addresses}:
            addresses = [value for value in addresses if value.casefold() != address.casefold()]
            checked = False
        else:
            addresses.append(address)
            checked = True
        self.model().item(row).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.setEditText(', '.join(addresses))

    def eventFilter(self, watched, event):
        if watched is self.view().viewport() and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            if event.button() == Qt.MouseButton.LeftButton:
                index = self.view().indexAt(event.position().toPoint())
                if index.isValid():
                    if event.type() == QEvent.Type.MouseButtonRelease:
                        self.toggle_recipient(index.row())
                    return True
        if watched is self.view() and event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle_recipient(self.view().currentIndex().row())
            return True
        return super().eventFilter(watched, event)


def email_defaults(settings, *, home=None, environ=None):
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    candidates = [home / '.occs.env', home / '.occs-cli' / '.env']
    if settings.cwd:
        candidates.append(Path(settings.cwd) / '.env')
    if environ.get('OCCS_ENV_FILE', '').strip():
        candidates.insert(0, Path(environ['OCCS_ENV_FILE']).expanduser())
    values = {}
    for path in candidates:
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:].strip()
            key, separator, value = line.partition('=')
            if separator and key.strip() in {'OCCS_EMAIL_CONFIG_UUID', 'OCCS_EMAIL_RECIPIENTS'}:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[key.strip()] = value
    return {name: environ.get(key, values.get(key, '')).strip() for name, key in
            [('config_uuid', 'OCCS_EMAIL_CONFIG_UUID'), ('recipients', 'OCCS_EMAIL_RECIPIENTS')]}


class EmailDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        self.setWindowTitle('Send Email')
        self.setModal(True)
        self.resize(760, 320)
        self.source = workspace.mapped_data_path()
        self.session = workspace.session
        self.job = None
        self.catalog_job = None
        self.catalog = []
        self.cache_error = ''
        self.closed = False
        self.config_session = str(workspace.comms.settings.get('session_alias') or '').strip()
        self.config_target = email_session_target(self.config_session)
        self.load_cached_emails()
        defaults = email_defaults(workspace.comms.settings)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        path = QPlainTextEdit(str(self.source))
        path.setReadOnly(True)
        path.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        path.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        path.setFixedHeight(path.fontMetrics().lineSpacing() * 3 + 16)
        path.setToolTip(str(self.source))
        path.setAccessibleName('Mapped JSON path')
        form.addRow('Mapped JSON', path)
        recipients = QLabel(', '.join(email_recipients(self.session.data)) or '(none in mapped JSON)')
        recipients.setWordWrap(True)
        form.addRow('JSON recipients', recipients)
        try:
            notification = 'sendDetail' in email_payload(self.session.data)
        except ValueError:
            notification = False
        history = workspace.comms.settings.get('email_recipient_mru', [])
        history = history if isinstance(history, list) else []
        choices = recipient_addresses(','.join(
            [value for value in history if isinstance(value, str)] + [defaults['recipients']]
            + email_recipients(self.session.data)))
        self.recipient_picker = RecipientPicker(choices, defaults['recipients'], multiple=not notification)
        self.recipients = self.recipient_picker.lineEdit()
        self.recipient_picker.setToolTip('Enter one recipient address.' if notification else
                                         'Type comma-separated addresses or select multiple addresses from the dropdown.')
        form.addRow('Recipient email(s)', self.recipient_picker)
        self.config_picker = QComboBox()
        self.config_picker.setPlaceholderText('Select an email distribution route')
        self.refresh_config_button = QPushButton('Refresh from Comms')
        config_row = QHBoxLayout()
        config_row.addWidget(self.config_picker, 1)
        config_row.addWidget(self.refresh_config_button)
        form.addRow('Distribution', config_row)
        history = self.routing_history()
        self.transaction = QLineEdit()
        self.transaction.setReadOnly(True)
        form.addRow('Transaction', self.transaction)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        layout.addWidget(self.status)
        layout.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton('Cancel')
        self.send_button = QPushButton('Send Email')
        self.send_button.setDefault(True)
        row.addWidget(cancel)
        row.addWidget(self.send_button)
        layout.addLayout(row)
        cancel.clicked.connect(self.reject)
        self.send_button.clicked.connect(self.submit)
        self.recipients.textChanged.connect(self.update_send_state)
        self.config_picker.currentIndexChanged.connect(self.select_config_name)
        self.refresh_config_button.clicked.connect(self.refresh_emails)
        self.finished.connect(self.close_request)
        recent = history.get('distributions', [])
        recent = recent if isinstance(recent, list) else []
        self.load_config_names(next((key for key in recent if any(profile['key'] == key for profile in self.catalog)), ''))
        if self.cache_error:
            self.set_status(self.cache_error)
        elif not self.catalog:
            self.set_status('Refresh from Comms to load email distribution routes.')

    def set_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def selected_route(self):
        key = self.config_picker.currentData()
        return next((profile for profile in self.catalog if profile['key'] == key), None)

    def selected_uuid(self):
        route = self.selected_route()
        return route['uuid'] if route else ''

    def update_send_state(self):
        busy = (self.job and not self.job.done) or (self.catalog_job and not self.catalog_job.done)
        self.send_button.setEnabled(bool(not self.closed and not busy and self.recipients.text().strip()
                                         and self.selected_uuid()))

    def routing_history(self):
        histories = self.workspace.comms.settings.get('email_send_mru', {})
        key = json.dumps(self.config_target or {'alias': self.config_session}, sort_keys=True)
        history = histories.get(key, {}) if isinstance(histories, dict) else {}
        if not isinstance(history, dict):
            return {}
        return {field: values[:5] for field in ('distributions',)
                if isinstance(values := history.get(field), list)}

    def email_cache_path(self):
        folder = str(self.workspace.comms.settings.get('comms_cache_dir') or '').strip()
        root = Path(folder).expanduser() if folder else Path.home() / '.atool'
        return root / 'email-routes' / 'index.json'

    def load_cached_emails(self):
        path = self.email_cache_path()
        if path is None or not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            self.catalog = email_route_profiles(payload, self.config_session, self.config_target)
        except (ValueError, OSError) as error:
            self.cache_error = str(error)

    def refresh_emails(self):
        if self.closed or (self.catalog_job and not self.catalog_job.done) or (self.job and not self.job.done):
            return
        if str(self.workspace.comms.settings.get('session_alias') or '').strip() != self.config_session:
            self.workspace.report_error('email distribution routes', 'OCCS session changed. Open Send Email again.')
            return
        self.refresh_config_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.set_status('Loading email distribution routes…')
        args = ['list-email-routes', '--json', '--timeout', str(self.workspace.comms.settings.timeout_ms)]
        if self.config_session:
            args += ['--session', self.config_session]
        path = self.email_cache_path()
        if path:
            args += ['--output', str(path.parent)]

        def loaded(result):
            if self.closed:
                return
            if str(self.workspace.comms.settings.get('session_alias') or '').strip() != self.config_session:
                raise ValueError('OCCS session changed. Open Send Email again.')
            target = email_session_target(self.config_session)
            catalog = email_route_profiles(result.value, self.config_session, target)
            uuid = self.config_picker.currentData()
            self.catalog = catalog
            self.config_target = target
            self.load_config_names(uuid)
            self.set_status('' if self.catalog else 'No email distribution routes found.')

        def failed(message):
            if not self.closed:
                self.set_status('Could not refresh email distribution routes. ' + message)

        try:
            self.catalog_job = self.workspace.run_comms_operation('List email distribution routes', args, loaded,
                require_json=True, on_failure=failed, channel='read')
        except (OSError, ValueError) as error:
            self.refresh_config_button.setEnabled(True)
            self.update_send_state()
            failed(str(error))
            return

        def finished(result):
            if not self.closed:
                self.refresh_config_button.setEnabled(True)
                self.update_send_state()
                if result.cancelled:
                    self.set_status('Refresh cancelled.')
        self.catalog_job.completed.connect(finished)

    def load_config_names(self, uuid=''):
        recent = self.routing_history().get('distributions', [])
        recent = recent if isinstance(recent, list) else []
        ordered = sorted(self.catalog, key=lambda profile: recent.index(profile['key']) if profile['key'] in recent else len(recent))
        self.config_picker.blockSignals(True)
        self.config_picker.clear()
        for profile in ordered:
            self.config_picker.addItem(profile['name'], profile['key'])
            self.config_picker.setItemData(self.config_picker.count() - 1, profile['uuid'], Qt.ItemDataRole.ToolTipRole)
        self.config_picker.setCurrentIndex(self.config_picker.findData(uuid) if uuid else -1)
        self.config_picker.blockSignals(False)
        self.select_config_name()

    def select_config_name(self, _index=None):
        route = self.selected_route()
        self.transaction.setText(' / '.join(filter(None, [route['transactionType'], route['userDefinedTransactionType']])) if route else '')
        self.update_send_state()

    def remember_routing(self, route):
        settings = self.workspace.comms.settings
        payload = copy.deepcopy(settings.payload)
        occs = payload.setdefault('occs', {})
        histories = occs.get('email_send_mru', {})
        histories = histories if isinstance(histories, dict) else {}
        key = json.dumps(self.config_target or {'alias': self.config_session}, sort_keys=True)
        previous = self.routing_history()
        def recent(field, value):
            items = previous.get(field, [])
            items = items if isinstance(items, list) else []
            return [value] + [item for item in items if isinstance(item, str) and item != value][:4]
        histories[key] = {'distributions': recent('distributions', route['key'])}
        occs['email_send_mru'] = histories
        try:
            settings.save(payload)
        except (OSError, ValueError) as error:
            self.workspace.log(f'Could not save recent email routing choices: {error}')

    def remember_recipients(self, recipients):
        settings = self.workspace.comms.settings
        history = settings.get('email_recipient_mru', [])
        history = history if isinstance(history, list) else []
        addresses = recipient_addresses(','.join([recipients] + [value for value in history if isinstance(value, str)]))[:30]
        payload = copy.deepcopy(settings.payload)
        payload.setdefault('occs', {})['email_recipient_mru'] = addresses
        try:
            settings.save(payload)
        except (OSError, ValueError) as error:
            self.workspace.log(f'Could not save recent email recipients: {error}')

    def submit(self):
        if self.closed or (self.job and not self.job.done) or (self.catalog_job and not self.catalog_job.done):
            return
        temporary = None
        try:
            if not self.source.is_file():
                raise ValueError('Mapped JSON file not found. Map a JSON data file again.')
            if self.workspace.session is not self.session or self.workspace.mapped_data_path() != self.source:
                raise ValueError('Mapped data changed. Open Send Email again.')
            alias = str(self.workspace.comms.settings.get('session_alias') or '').strip()
            if alias != self.config_session or email_session_target(alias) != self.config_target:
                raise ValueError('OCCS environment changed. Open Send Email again.')
            recipients, config = self.recipients.text().strip(), self.selected_uuid()
            if not recipients:
                raise ValueError('Recipient email is required.')
            if not self.selected_route():
                raise ValueError('Select an email distribution route from the lookup.')
            path, temporary = prepare_email_input(self.session.data, self.source, recipients)
            route = self.selected_route()
            args = ['preview', '--input', str(path), '--render-type', 'EMAIL',
                    '--communication-config-uuid', config,
                    '--communication-transaction-type', route['transactionType']]
            if route['userDefinedTransactionType']:
                args += ['--communication-user-defined-transaction-type', route['userDefinedTransactionType']]
            args += ['--recipient', recipients, '--send-email']
            if self.workspace.comms.settings.payload.get('diagnostics', {}).get('debug_logging'):
                args.append('--verbose')
            if alias:
                args[1:1] = ['--session', alias]
            self.send_button.setEnabled(False)

            def passed(_result):
                self.remember_recipients(recipients)
                self.workspace.log('Email request accepted by OCCS; delivery is not confirmed.')
                self.workspace.statusBar().showMessage('Email request accepted by OCCS.', 7000)

            self.job = self.workspace.run_comms_operation('Sending email through OCCS', args, passed)
            self.remember_routing(route)
            self.job.completed.connect(lambda _result: temporary.cleanup() if temporary else None)
            self.accept()
        except (ValueError, OSError) as error:
            if temporary:
                temporary.cleanup()
            self.update_send_state()
            self.workspace.report_error('Send Email', str(error))

    def close_request(self, result):
        self.closed = True
        if self.catalog_job and not self.catalog_job.done:
            self.catalog_job.cancel()
        # Send Email transfers ownership to the visible operation dialog.
        if result != QDialog.DialogCode.Accepted and self.job and not self.job.done:
            self.job.cancel()


class PackageEmailActions:
    def install_email_actions(self):
        self.email_action = self.action('Send Email…', self.send_email, 'Ctrl+E')
        self.package_menu.insertAction(self.cancel_preview_action, self.email_action)
        self.package_menu.aboutToShow.connect(self.update_email_actions)

    def update_email_actions(self):
        if hasattr(self, 'email_action'):
            self.email_action.setEnabled(bool(self.mapped_data_path()) and not self.package_busy())

    def send_email(self):
        if not self.mapped_data_path() or self.package_busy():
            self.report_error('Send Email', 'Map a JSON data file before sending email.')
            return
        self.email_dialog = EmailDialog(self)
        self.email_dialog.show()
