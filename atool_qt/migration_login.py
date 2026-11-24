"""Shared password login controls for migration and XML conversion."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                              QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from .comms_login import saved_login_targets


def migration_login_key(alias):
    targets, _ = saved_login_targets()
    target = targets.get(alias, {})
    if all(target.get(field) for field in ('customer', 'region', 'tenancy')):
        return f"{target['customer']}.{target['region']}/{target['tenancy']}"
    return alias


def remembered_migration_login(key):
    path = Path.home() / '.occs-cli' / 'atool-migration-logins.json'
    try:
        entry = json.loads(path.read_text(encoding='utf-8'))['logins'].get(key, {})
        return str(entry['username']) if entry.get('passwordEnc') else ''
    except FileNotFoundError:
        return ''
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError('The saved password login file could not be read. Restore it before using saved password credentials.') from error


def selected_password_login(comms, alias):
    """Return a shared remembered/in-memory login, or None for the normal session."""
    key=migration_login_key(alias)
    saved=remembered_migration_login(key)
    state=comms.migration_logins.get(key,{'enabled':bool(saved),'username':saved,'password':'','remember':bool(saved)})
    if not state['username'] and not state['password'] and not saved:
        return None
    username,password=state['username'],state['password']
    if not username or (not password and (saved!=username or not state['remember'])):
        raise ValueError('Enter the separate username and password, then test the login.')
    return {'username':username,'password':password,'remember':state['remember']}


class MigrationLoginActions:
    """Shared password login form for migrations and XML conversion."""
    def render_migration_login(self):
        self.note('Password pathway for this environment')
        key=migration_login_key(self.migration_source)
        cache=self.workspace.comms.migration_logins
        try:
            saved=remembered_migration_login(key)
        except ValueError as error:
            saved=''
            self.note(str(error))
        state=cache.get(key,{'enabled':bool(saved),'username':saved,'password':'','remember':bool(saved)})
        self.migration_login_key=key
        self.separate_migration_login=QCheckBox('Use a separate password login for migration and XML conversion')
        self.separate_migration_login.setChecked(state['enabled'])
        self.separate_migration_login.hide()
        self.body_layout.addWidget(self.separate_migration_login)
        self.migration_login_fields=QWidget()
        form=QFormLayout(self.migration_login_fields)
        self.migration_username=QLineEdit(state['username'])
        self.migration_password=QLineEdit(state['password'])
        self.migration_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.migration_password.setPlaceholderText('Saved password available' if saved else 'Password for the separate account')
        self.remember_migration_login=QCheckBox('Remember password login')
        self.remember_migration_login.setChecked(state['remember'])
        self.remember_migration_login.setToolTip('Save this login separately using the OCCS CLI encrypted credential mechanism. Normal SSO sessions are unchanged.')
        form.addRow('Username',self.migration_username)
        form.addRow('Password',self.migration_password)
        form.addRow('',self.remember_migration_login)
        buttons=QHBoxLayout()
        self.test_migration_login_button=QPushButton('Test Login')
        self.test_migration_login_button.clicked.connect(self.guard(self.test_migration_login))
        buttons.addWidget(self.test_migration_login_button)
        self.forget_migration_login_button=QPushButton('Forget Saved Login')
        self.forget_migration_login_button.clicked.connect(self.guard(self.forget_migration_login))
        buttons.addWidget(self.forget_migration_login_button)
        form.addRow(buttons)
        self.body_layout.addWidget(self.migration_login_fields)
        self.migration_login_fields.setEnabled(True)
        def changed(*_):
            if self.migration_username.text().strip() or self.migration_password.text():
                self.separate_migration_login.setChecked(True)
            cache[key]={'enabled':self.separate_migration_login.isChecked(),'username':self.migration_username.text().strip(),
                        'password':self.migration_password.text(),'remember':self.remember_migration_login.isChecked()}
        self.separate_migration_login.toggled.connect(changed)
        self.migration_username.textChanged.connect(changed)
        self.migration_password.textChanged.connect(changed)
        self.remember_migration_login.toggled.connect(changed)
        self.note('This login supplies tokens for migration and Oracle-hosted XML conversion in this environment. Normal ATool work keeps using your usual sessions. '
                  'Remembered credentials are saved after successful password authentication. Without Remember, they remain available until ATool closes.')

    def migration_login_input(self):
        if not self.separate_migration_login.isChecked():
            return None
        username=self.migration_username.text().strip()
        password=self.migration_password.text()
        if not username or (not password and remembered_migration_login(self.migration_login_key)!=username):
            raise ValueError('Enter the separate username and password, then test the login.')
        if not password and not self.remember_migration_login.isChecked():
            raise ValueError('Enter the password to keep this login only until ATool closes, or use Forget Saved Login to remove it.')
        return {'username':username,'password':password,'remember':self.remember_migration_login.isChecked()}

    def test_migration_login(self):
        credentials=self.migration_login_input()
        if credentials is None:
            raise ValueError('Enter the username and password for the Password pathway first.')
        def tested(value):
            if value.get('ok') is not True:
                raise ValueError('The password login was not confirmed.')
            self.status.setText('Password login succeeded. '+('Login remembered.' if credentials['remember'] else 'Login available until ATool closes.'))
        self.operation('Test Password Login',['migration-login','test','--session',self.migration_source,
                       '--timeout',str(self.workspace.comms.settings.timeout_ms)],tested,private_input=credentials)

    def forget_migration_login(self):
        def forgotten(value):
            if value.get('ok') is not True:
                raise ValueError('The saved password login was not removed.')
            self.workspace.comms.migration_logins.pop(self.migration_login_key,None)
            self.migration_username.clear()
            self.migration_password.clear()
            self.remember_migration_login.setChecked(False)
            self.migration_password.setPlaceholderText('Password for the separate account')
            self.status.setText('Saved password login forgotten. Normal SSO sessions are unchanged.')
        self.operation('Forget Password Login',['migration-login','forget','--session',self.migration_source],forgotten)


class MigrationLoginDialog(MigrationLoginActions, QDialog):
    """Select and manage the source login before a Config menu migration."""
    def __init__(self, workspace, source, target='', *, source_uses_sso=False, purpose='migration'):
        super().__init__(workspace)
        self.workspace=workspace
        self.comms=workspace.comms
        self.migration_source=source
        self.source_uses_sso=source_uses_sso
        self.credentials=None
        self.busy=False
        self.login_operation=None
        self.setWindowTitle('Password Login')
        self.resize(700,360)
        layout=QVBoxLayout(self)
        label=QLabel(f'Environment: {source}' if purpose=='conversion' else f'Source: {source}\nTarget: {target}')
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)
        self.body=QWidget()
        self.body_layout=QVBoxLayout(self.body)
        layout.addWidget(self.body)
        self.status=QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.render_migration_login()
        if source_uses_sso:
            self.separate_migration_login.setChecked(True)
        layout.addWidget(self.status)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Continue')
        self.buttons.accepted.connect(self.guard(self.submit))
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def note(self, text):
        label=QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        self.body_layout.addWidget(label)

    def guard(self, callback):
        def invoke(*_):
            if self.busy:
                return
            try:
                callback()
            except (OSError,ValueError,KeyError,TypeError) as error:
                self.status.setText(str(error))
        return invoke

    def submit(self):
        credentials=self.migration_login_input()
        if credentials is None and self.source_uses_sso:
            raise ValueError('Enter the username and password for the Password pathway. Your normal session uses SSO.')
        self.credentials=credentials
        self.accept()

    def operation(self, title, args, callback, *, private_input=None):
        from .operations import OperationDialog
        self.busy=True
        self.body.setEnabled(False)
        self.buttons.setEnabled(False)
        def complete(result):
            callback(result.value)
        def release(_):
            self.busy=False
            self.body.setEnabled(True)
            self.buttons.setEnabled(True)
        operation=OperationDialog(self,title,args,complete,require_json=True,
                                  on_failure=self.status.setText,private_input=private_input)
        self.login_operation=operation
        operation.job.completed.connect(release)
        operation.show()
        return operation.job

    def reject(self):
        if self.login_operation and not self.login_operation.job.done:
            self.login_operation.job.cancel()
        super().reject()

