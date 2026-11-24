"""Browser sign-in UI and saved login metadata; credentials stay in OCCS CLI."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                              QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout)

from atool_core.activity_output import activity_text


def saved_login_targets(session_path=None):
    path = Path(session_path or Path.home() / '.occs-session.json')
    try:
        store = json.loads(path.read_text(encoding='utf-8'))
        sessions = store.get('sessions')
        if not isinstance(sessions, dict):
            parts = [str(store.get(key) or '').strip() for key in ('customer', 'region', 'tenancy')]
            key = f'{parts[0]}.{parts[1]}/{parts[2]}' if all(parts) else ''
            sessions = {key: store} if key else {}
        targets = {}
        for key, session in sessions.items():
            if not isinstance(session, dict):
                continue
            target = {field: str(session.get(field) or '').strip() for field in ('customer', 'region', 'tenancy')}
            if all(target.values()):
                target['authType'] = 'sso' if session.get('authType') == 'sso' else 'password'
                targets[key] = target
        aliases = store.get('aliases', {})
        if isinstance(aliases, dict):
            for alias, key in aliases.items():
                if isinstance(key, str) and key in targets:
                    targets[alias] = dict(targets[key])
        current = str(store.get('currentSessionKey') or '')
        return targets, current if current in targets else next(iter(targets), '')
    except (ValueError, OSError, AttributeError):
        return {}, ''


def login_args(alias, session_path=None):
    alias = str(alias or '').strip()
    targets, current = saved_login_targets(session_path)
    target = targets.get(alias or current, {})
    args = ['login'] + (['--sso'] if target.get('authType') == 'sso' else [])
    if alias:
        args += ['--session', alias]
    for key in ('customer', 'region', 'tenancy'):
        if target.get(key):
            args += [f'--{key}', target[key]]
    return args


def sso_expired_error(message):
    text = message.casefold()
    return 'occs_sso_expired' in text or 'sso session expired' in text or 'sso session has expired' in text


class CommsLoginDialog(QDialog):
    def __init__(self, workspace, session_path=None):
        super().__init__(workspace)
        self.workspace = workspace
        self.session_path = session_path
        self.job = None
        self.targets, current = saved_login_targets(session_path)
        self.setWindowTitle('Sign In to Comms')
        self.resize(580, 430)
        layout = QVBoxLayout(self)
        self.help_text = QLabel()
        self.help_text.setWordWrap(True)
        layout.addWidget(self.help_text)
        form = QFormLayout()
        self.alias = QComboBox()
        self.alias.setEditable(True)
        self.alias.addItems(sorted(self.targets))
        self.alias.setCurrentText(str(workspace.comms.settings.get('session_alias') or current or 'comms'))
        form.addRow('Session alias', self.alias)
        self.method = QComboBox()
        self.method.addItem('Password', 'password')
        self.method.addItem('Browser SSO', 'sso')
        form.addRow('Credential pathway', self.method)
        self.fields = {}
        for key, title, hint in [('customer', 'Customer', 'Customer short name'),
                                 ('region', 'Region / environment', 'For example: sin-fscloud'),
                                 ('tenancy', 'Tenancy', 'For example: non-prod')]:
            field = QLineEdit()
            field.setPlaceholderText(hint)
            self.fields[key] = field
            form.addRow(title, field)
        self.username=QLineEdit()
        self.password=QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.remember_password=QCheckBox('Remember password login')
        self.remember_password.setChecked(True)
        self.password_form=QFormLayout()
        self.password_form.addRow('Username',self.username)
        self.password_form.addRow('Password',self.password)
        self.password_form.addRow(self.remember_password)
        form.addRow(self.password_form)
        layout.addLayout(form)
        routing_info=QLabel('Both pathways can be remembered for the same environment.')
        routing_info.setWordWrap(True)
        layout.addWidget(routing_info)
        self.status = QLabel('Requires OCCS CLI 1.4.0 or later and Chrome, Edge or Chromium. '
                             'Browser and sign-in timeout options are in User Settings → Comms.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setMinimumWidth(0)
        layout.addWidget(self.status)
        self.diagnostics_toggle = QPushButton('Show diagnostics')
        self.diagnostics_toggle.setCheckable(True)
        self.diagnostics_toggle.hide()
        layout.addWidget(self.diagnostics_toggle)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setFixedHeight(150)
        self.diagnostics.hide()
        layout.addWidget(self.diagnostics)
        self.diagnostics_toggle.toggled.connect(self.toggle_diagnostics)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.sign_in = QPushButton('Sign In')
        self.sign_in.setDefault(True)
        self.close_button = QPushButton('Close')
        buttons.addWidget(self.sign_in)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.alias.currentTextChanged.connect(self.select_target)
        self.method.currentIndexChanged.connect(self.update_method_help)
        self.select_target(self.alias.currentText())
        self.sign_in.clicked.connect(self.start_login)
        self.close_button.clicked.connect(self.reject)

    def toggle_diagnostics(self, expanded):
        self.diagnostics.setVisible(expanded)
        self.diagnostics_toggle.setText('Hide diagnostics' if expanded else 'Show diagnostics')
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())

    def clear_diagnostics(self):
        self.diagnostics_toggle.setChecked(False)
        self.diagnostics_toggle.hide()
        self.diagnostics.clear()
        self.diagnostics.hide()

    def select_target(self, alias):
        target = self.targets.get(alias, {})
        self.method.setCurrentIndex(1 if target.get('authType') == 'sso' else 0)
        self.update_method_help()
        for key, field in self.fields.items():
            field.setText(target.get(key, ''))
        from .migration_login import migration_login_key, remembered_migration_login
        try:
            key=migration_login_key(alias)
            state=self.workspace.comms.migration_logins.get(key,{})
            saved=remembered_migration_login(key)
            self.username.setText(state.get('username') or saved)
            self.password.setText(state.get('password',''))
            self.remember_password.setChecked(state.get('remember',True))
        except ValueError:
            self.username.clear()
            self.password.clear()

    def update_method_help(self):
        password_mode=self.method.currentData()=='password'
        for row in range(self.password_form.rowCount()):
            self.password_form.setRowVisible(row,password_mode)
        if self.method.currentData() == 'sso':
            self.status.setText('Requires OCCS CLI 1.4.0 or later and Chrome, Edge or Chromium. '
                                'Browser and sign-in timeout options are in User Settings → Comms.')
            self.help_text.setText('Complete browser and phone/passkey approval. SSO is used for normal operations; '
                                   'the separate Password pathway is preserved for XML conversion and migration source tokens.')
        else:
            self.status.setText('Enter a username and password, or reuse a remembered password login.')
            self.help_text.setText('The password pathway is used for all operations when SSO is not configured. When both pathways '
                                   'are available, SSO handles normal operations and Password handles XML conversion and migration source tokens.')

    def set_running(self, running):
        self.alias.setEnabled(not running)
        self.method.setEnabled(not running)
        for field in self.fields.values():
            field.setEnabled(not running)
        self.sign_in.setEnabled(not running)
        self.username.setEnabled(not running)
        self.password.setEnabled(not running)
        self.remember_password.setEnabled(not running)
        self.close_button.setText('Cancel Sign-In' if running else 'Close')

    def start_login(self):
        if self.job is not None and not self.job.done:
            return
        self.clear_diagnostics()
        alias = self.alias.currentText().strip()
        target = {key: field.text().strip() for key, field in self.fields.items()}
        if not alias or not all(target.values()):
            self.status.setText('Enter a session alias, customer, region and tenancy.')
            return
        if not all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?', value) for value in target.values()):
            self.status.setText('Customer, region and tenancy must contain letters, numbers or hyphens.')
            return
        self.login_alias = alias
        self.login_method = self.method.currentData()
        args = ['login'] + (['--sso'] if self.login_method == 'sso' else []) + ['--session', alias]
        for key, value in target.items():
            args += [f'--{key}', value]
        private_input=None
        self.pending_password=None
        if self.login_method=='password':
            from .migration_login import migration_login_key, remembered_migration_login
            username=self.username.text().strip()
            password=self.password.text()
            try:
                saved=remembered_migration_login(f"{target['customer']}.{target['region']}/{target['tenancy']}")
            except ValueError as error:
                self.status.setText(str(error))
                return
            if username and (password or saved==username):
                if not password and not self.remember_password.isChecked():
                    self.status.setText('Enter the password to keep it only until ATool closes, or leave Remember enabled to reuse the saved login.')
                    return
                private_input={'username':username,'password':password,'remember':self.remember_password.isChecked()}
                args=['migration-login','signin',*args[1:]]
            elif self.targets.get(alias,{}).get('authType')!='password':
                self.status.setText('Enter a username and password for the Password pathway.')
                return
        self.set_running(True)
        self.status.setText('Complete sign-in in the browser, including phone/passkey approval. '
                            'You can cancel here or close the sign-in browser.' if self.login_method == 'sso'
                            else 'Signing in using the Password pathway…')
        if self.login_method=='sso' and self.targets.get(alias,{}).get('authType')=='password':
            def preserved(result):
                if not result.successful:
                    self.login_finished(result)
                    return
                self.job=self.workspace.comms.submit(args,self.login_finished)
            self.job=self.workspace.comms.submit(['migration-login','preserve','--session',alias],preserved)
        else:
            if private_input is not None:
                key=f"{target['customer']}.{target['region']}/{target['tenancy']}"
                self.pending_password=(key,{**private_input,'enabled':True})
            options={'private_input':private_input} if private_input is not None else {}
            self.job = self.workspace.comms.submit(args, self.login_finished,**options)

    def login_finished(self, result):
        self.set_running(False)
        self.clear_diagnostics()
        if result.cancelled:
            self.status.setText('Sign-in cancelled. You can try again when ready.')
        elif result.timed_out:
            self.status.setText('Sign-in timed out. Click Sign In to try again.')
        elif not result.successful:
            message = activity_text(result.message)
            details = message
            lowered = message.casefold()
            if self.method.currentData() != 'sso':
                message = ('Password sign-in failed. Check the username, password and environment here, then retry. Expand diagnostics for details.')
            elif ('target page, context or browser has been closed' in lowered
                    or 'browser closed or disconnected' in lowered
                    or 'browser was closed' in lowered):
                message = ('The sign-in browser closed or disconnected before sign-in completed. '
                           'Click Sign In to retry and keep the browser open until sign-in is confirmed. '
                           'If this repeats, try another browser under User Settings → Comms → SSO Browser Executable.')
            elif 'sso sign-in timed out' in lowered:
                message = 'SSO sign-in timed out. Click Sign In to try again.'
            elif 'unknown option' in lowered and '--sso' in message:
                message = ('The configured OCCS CLI does not support SSO sign-in. Update to OCCS CLI 1.4.0 or later, '
                           'then select it under User Settings → Comms → CLI Path.')
            else:
                message = 'SSO sign-in failed. Click Sign In to retry. Expand diagnostics for details.'
            self.status.setText(message)
            self.diagnostics.setPlainText(details)
            self.diagnostics_toggle.show()
        else:
            if getattr(self,'pending_password',None) is not None:
                key,value=self.pending_password
                self.workspace.comms.migration_logins[key]=value
            self.targets, _ = saved_login_targets(self.session_path)
            settings = self.workspace.comms.settings
            payload = copy.deepcopy(settings.payload)
            payload.setdefault('occs', {})['session_alias'] = self.login_alias
            try:
                settings.save(payload)
            except (ValueError, OSError) as error:
                self.status.setText(f'Signed in, but the default session setting could not be saved: {error}')
                return
            self.status.setText('Password pathway ready. SSO remains in use for normal operations.'
                                if self.login_method=='password' and result.value and result.value.get('normalAuthType')=='sso'
                                else 'Signed in. Your Comms session is ready.')
            self.sign_in.setText('Sign In Again')

    def reject(self):
        if self.job is not None and not self.job.done:
            self.job.cancel()
        super().reject()
