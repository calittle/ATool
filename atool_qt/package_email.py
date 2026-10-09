"""Mapped-data email requests with Dry Run before Generate."""
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout


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


def email_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('Mapped JSON must be an object to send email.')
    info = payload.get('CommunicationInfo')
    data = info.get('CommunicationData') if isinstance(info, dict) else None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as error:
            raise ValueError('CommunicationData must contain a JSON object.') from error
        if not isinstance(data, dict):
            raise ValueError('CommunicationData must contain a JSON object.')
    return data if isinstance(data, dict) else payload


def email_elements(payload):
    value = email_payload(payload)
    path = []
    for key in ('billPrint', 'billDetails', 'cmElements'):
        path.append(key)
        value = value.get(key)
        if not isinstance(value, dict):
            raise ValueError('Mapped JSON must contain a ' + '.'.join(path) + ' object to send email.')
    return value


def email_recipients(payload):
    try:
        bill = email_elements(payload).get('eBill')
        values = bill.get('recipientEmails') if isinstance(bill, dict) else None
    except ValueError:
        return []
    return [str(item.get('email', '')).strip() for item in values if isinstance(item, dict) and str(item.get('email', '')).strip()] if isinstance(values, list) else []


def prepare_email_input(payload, source, recipients):
    """Return input path plus an owned temporary directory, if one is needed."""
    elements = email_elements(payload)
    bill = elements.get('eBill')
    if isinstance(bill, dict) and isinstance(bill.get('recipientEmails'), list):
        return Path(source), None
    addresses = [value.strip() for value in recipients.split(',') if value.strip()]
    if not addresses:
        raise ValueError('Recipient email is required.')
    prepared = copy.deepcopy(email_payload(payload))
    elements = email_elements(prepared)
    if not isinstance(elements.get('eBill'), dict):
        elements['eBill'] = {}
    elements['eBill']['recipientEmails'] = [{'email': value} for value in addresses]
    temporary = tempfile.TemporaryDirectory(prefix='atool-email-')
    path = Path(temporary.name) / 'input.json'
    try:
        path.write_text(json.dumps(prepared, ensure_ascii=False), encoding='utf-8')
    except OSError:
        temporary.cleanup()
        raise
    return path, temporary


class EmailDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        self.setWindowTitle('Send Email')
        self.setModal(True)
        self.resize(660, 300)
        self.source = workspace.mapped_data_path()
        self.session = workspace.session
        self.verified = None
        self.job = None
        self.closed = False
        layout = QVBoxLayout(self)
        form = QFormLayout()
        path = QLabel(str(self.source))
        path.setWordWrap(True)
        form.addRow('Mapped JSON', path)
        recipients = QLabel(', '.join(email_recipients(self.session.data)) or '(none in mapped JSON)')
        recipients.setWordWrap(True)
        form.addRow('JSON recipients', recipients)
        defaults = email_defaults(workspace.comms.settings)
        self.recipients = QLineEdit(defaults['recipients'])
        self.config = QLineEdit(defaults['config_uuid'])
        self.recipients.setToolTip('Separate multiple addresses with commas. Defaults to OCCS_EMAIL_RECIPIENTS when configured.')
        self.config.setToolTip('Defaults to OCCS_EMAIL_CONFIG_UUID when configured.')
        form.addRow('Recipient email(s)', self.recipients)
        form.addRow('Config UUID', self.config)
        layout.addLayout(form)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        cancel, self.dry_run, self.generate = QPushButton('Cancel'), QPushButton('Dry Run'), QPushButton('Generate')
        self.dry_run.setDefault(True)
        self.generate.setEnabled(False)
        for button in (cancel, self.dry_run, self.generate):
            row.addWidget(button)
        layout.addLayout(row)
        cancel.clicked.connect(self.reject)
        self.dry_run.clicked.connect(lambda: self.submit(False))
        self.generate.clicked.connect(lambda: self.submit(True))
        self.recipients.textChanged.connect(self.reset_validation)
        self.config.textChanged.connect(self.reset_validation)
        self.finished.connect(self.close_request)

    def reset_validation(self):
        self.verified = None
        self.generate.setEnabled(False)
        self.generate.setDefault(False)
        self.dry_run.setDefault(True)
        self.status.clear()

    def snapshot(self):
        if self.workspace.session is not self.session or self.workspace.mapped_data_path() != self.source:
            raise ValueError('Mapped data changed. Open Send Email again.')
        return (self.recipients.text().strip(), self.config.text().strip(),
                self.session.mapping_revision, hashlib.sha256(self.source.read_bytes()).hexdigest(),
                json.dumps(self.session.data, sort_keys=True, ensure_ascii=False),
                str(self.workspace.comms.settings.get('session_alias') or '').strip())

    def submit(self, send):
        if self.closed or (self.job and not self.job.done):
            return
        temporary = None
        try:
            snapshot = self.snapshot()
            recipients, config = snapshot[:2]
            if not recipients or not config:
                raise ValueError('Recipient email and Config UUID are required.')
            if send and self.verified != snapshot:
                self.reset_validation()
                raise ValueError('Run Dry Run with the current recipient, Config UUID and mapped data before generating email.')
            path, temporary = prepare_email_input(self.session.data, self.source, recipients)
            args = ['preview', '--input', str(path), '--render-type', 'EMAIL', '--email-config-uuid', config, '--recipient', recipients]
            if snapshot[-1]:
                args[1:1] = ['--session', snapshot[-1]]
            if send:
                args.append('--send-email')
            self.generate.setEnabled(False)
            self.dry_run.setEnabled(False)
            self.status.setText('Submitting email…' if send else 'Running dry run…')
            def passed(result):
                if send:
                    self.workspace.log('Email submitted to OCCS.')
                    self.workspace.statusBar().showMessage('Email submitted to OCCS.', 7000)
                elif not self.closed:
                    try:
                        valid = self.snapshot() == snapshot
                    except (ValueError, OSError):
                        valid = False
                    if valid:
                        self.verified = snapshot
                        self.generate.setEnabled(True)
                        self.generate.setDefault(True)
                        self.dry_run.setDefault(False)
                        self.status.setText(f'Dry run passed. Recipients: {recipients}\nConfig UUID: {config}\nNo email was sent.')
                    else:
                        self.status.setText('Inputs or mapped data changed during the dry run. Run it again.')
            job = self.workspace.run_comms_operation('Sending email through OCCS' if send else 'Validating email request through OCCS', args, passed)
            self.job = job
            def finished(result):
                if temporary:
                    temporary.cleanup()
                if not self.closed:
                    self.dry_run.setEnabled(True)
                    if not result.successful:
                        self.verified = None
                        self.generate.setEnabled(False)
                        self.status.setText('Dry run failed: ' + result.message)
            job.completed.connect(finished)
            if send:
                self.accept()
        except (ValueError, OSError) as error:
            if temporary:
                temporary.cleanup()
            self.workspace.report_error('Send Email', str(error))

    def close_request(self, result):
        self.closed = True
        # Generate transfers ownership to the visible operation dialog.
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
