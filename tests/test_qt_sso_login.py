"""SSO UI and process contracts using synthetic metadata and a local fake CLI."""
import copy
import json
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QMainWindow

from atool_qt.activity import ActivityLog
from atool_qt.comms_login import CommsLoginDialog, login_args, saved_login_targets
from atool_qt.occs import CommsService
from atool_qt.user_settings import UserSettings
from atool_core.activity_output import sanitized_http_value


class SsoLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = self.root / 'calls.jsonl'
        self.mode = self.root / 'mode'
        self.mode.write_text('success')
        self.terminated = self.root / 'terminated'
        self.cli = self.root / 'fake-cli'
        self.cli.write_text(f'#!{sys.executable}\n' + f'''
import json, pathlib, signal, sys, time
args = sys.argv[1:]
with open({str(self.calls)!r}, 'a') as f: f.write(json.dumps(args)+'\\n')
mode = pathlib.Path({str(self.mode)!r}).read_text()
if mode == 'slow':
    def stop(*_):
        pathlib.Path({str(self.terminated)!r}).write_text('closed')
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    print('ready', flush=True)
    time.sleep(10)
elif mode == 'expired':
    print('SSO session expired or was rejected. Run occs login --sso and retry.', file=sys.stderr)
    sys.exit(1)
elif mode == 'expired-json':
    print(json.dumps({{'ok': False, 'error': {{'message': 'SSO session expired or was rejected.'}}}}))
    sys.exit(0)
elif mode == 'password':
    marker = pathlib.Path({str(self.root / 'authenticated')!r})
    if args[0] == 'login': marker.touch()
    elif not marker.exists():
        print('Unauthorized: Your token may have expired. Please run occs login again.', file=sys.stderr)
        sys.exit(1)
elif mode == 'failure':
    print('Sign-in browser was closed.', file=sys.stderr)
    sys.exit(1)
elif mode == 'unsupported':
    print("error: unknown option '--sso'", file=sys.stderr)
    sys.exit(1)
print('Authorization: Bearer SYNTHETIC_LOGIN_SECRET', flush=True)
print(json.dumps({{'ok': True, 'args': args}}))
''')
        self.cli.chmod(0o755)
        self.settings = UserSettings(self.root / 'settings.json')
        self.settings.payload['occs'].update(cli_path=str(self.cli), session_alias='np')
        self.settings.save()
        self.workspace = QMainWindow()
        self.workspace.comms = CommsService(self.settings, self.workspace)
        self.addCleanup(self.workspace.close)
        self.addCleanup(self.app.processEvents)
        self.addCleanup(self.workspace.comms.shutdown)
        self.sessions = self.root / 'sessions.json'
        self.sessions.write_text(json.dumps({
            'currentSessionKey': 'example.region/non-prod',
            'aliases': {'sso': 'example.region/non-prod'},
            'sessions': {'example.region/non-prod': {
                'customer': 'example', 'region': 'region', 'tenancy': 'non-prod', 'authType': 'sso',
                'token': 'not-read', 'cookieJarEnc': 'not-read', 'credentials': {'passwordEnc': 'not-read'},
            }},
        }))

    def until(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(condition())

    def dialog(self):
        dialog = CommsLoginDialog(self.workspace, self.sessions)
        dialog.alias.setCurrentText('sso')
        self.addCleanup(dialog.close)
        return dialog

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def test_metadata_and_reauthentication_keep_method_without_copying_secrets(self):
        targets, current = saved_login_targets(self.sessions)
        self.assertEqual(current, 'example.region/non-prod')
        self.assertNotIn('not-read', str(targets))
        expected = ['login', '--sso', '--session', 'sso', '--customer', 'example', '--region', 'region', '--tenancy', 'non-prod']
        self.assertEqual(login_args('sso', self.sessions), expected)
        self.assertIn('--sso', login_args('', self.sessions))
        self.assertEqual(login_args('new', self.sessions), ['login', '--session', 'new'])
        self.sessions.write_text(json.dumps({'customer': 'old', 'region': 'region', 'tenancy': 'prod', 'token': 'not-read'}))
        self.assertNotIn('--sso', login_args('', self.sessions))
        self.assertIn('prod', login_args('', self.sessions))

    def test_sso_options_and_separate_timeout_settings(self):
        self.settings.payload['occs'].update(request_timeout_seconds=1, sso_timeout_seconds=12, sso_browser_path='~/browser')
        args = self.settings.command(['login', '--sso', '--session', 'sso'])
        self.assertIn('12000', args)
        self.assertIn(str(Path('~/browser').expanduser()), args)
        explicit = self.settings.command(['login', '--sso', '--sso-timeout', '42', '--browser-executable', '/explicit'])
        self.assertEqual(explicit.count('--sso-timeout'), 1)
        self.assertEqual(explicit.count('--browser-executable'), 1)
        self.assertNotIn('--sso-timeout', self.settings.command(['login', '--session', 'password']))
        for value in (0, 'bad'):
            payload = copy.deepcopy(self.settings.payload)
            payload['occs']['sso_timeout_seconds'] = value
            with self.assertRaisesRegex(ValueError, 'SSO Sign-In Timeout'):
                self.settings.validate(payload)

    def test_dialog_signs_in_with_target_and_sets_alias_only_after_success(self):
        dialog = self.dialog()
        self.assertEqual(dialog.fields['customer'].text(), 'example')
        self.assertNotIn('not-read', dialog.status.text())
        activity = ActivityLog()
        self.addCleanup(activity.close)
        self.workspace.comms.submitted.connect(activity.track_operation)
        dialog.sign_in.click()
        self.assertFalse(dialog.sign_in.isEnabled())
        self.assertEqual(self.settings.get('session_alias'), 'np')
        self.until(lambda: dialog.job.done)
        self.assertEqual(UserSettings(self.settings.path).get('session_alias'), 'sso')
        self.assertIn('Signed in.', dialog.status.text())
        args = self.recorded()[0]
        self.assertEqual(args[:4], ['login', '--sso', '--session', 'sso'])
        self.assertIn('--customer', args)
        self.assertNotIn('SYNTHETIC_LOGIN_SECRET', activity.toPlainText())

    def test_dialog_validation_and_browser_failure_preserve_settings(self):
        dialog = self.dialog()
        dialog.fields['customer'].clear()
        dialog.sign_in.click()
        self.assertIsNone(dialog.job)
        dialog.fields['customer'].setText('../invalid')
        dialog.sign_in.click()
        self.assertIsNone(dialog.job)
        dialog.fields['customer'].setText('example')
        self.mode.write_text('failure')
        dialog.sign_in.click()
        self.until(lambda: dialog.job.done)
        self.assertIn('browser was closed', dialog.status.text())
        self.assertTrue(dialog.sign_in.isEnabled())
        self.assertEqual(self.settings.get('session_alias'), 'np')

    def test_sso_expiry_never_opens_browser_or_replays_operation(self):
        self.mode.write_text('expired')
        results = []
        self.workspace.comms.submit(['preview', '--session', 'sso'], results.append)
        self.until(lambda: bool(results))
        self.assertFalse(results[0].successful)
        self.assertIn('Settings → Sign In to Comms (SSO)', results[0].message)
        self.assertEqual(len(self.recorded()), 1)
        self.assertFalse(self.workspace.comms.logins)

    def test_password_login_recovery_still_retries_once(self):
        self.mode.write_text('password')
        results = []
        with patch('atool_qt.comms_login.login_args', return_value=['login', '--session', 'np']):
            self.workspace.comms.submit(['package', 'list'], results.append)
            self.until(lambda: bool(results))
        self.assertTrue(results[0].successful)
        self.assertEqual([args[0] for args in self.recorded()], ['package', 'login', 'package'])

    def test_structured_sso_failure_cannot_become_success_when_process_exits_zero(self):
        self.mode.write_text('expired-json')
        results = []
        self.workspace.comms.submit(['package', '--session', 'sso', 'list', '--json'], results.append)
        self.until(lambda: bool(results))
        self.assertFalse(results[0].successful)
        self.assertIn('Sign In to Comms (SSO)', results[0].message)

    def test_generic_unauthorized_for_saved_sso_does_not_fall_back_to_password_login(self):
        self.mode.write_text('password')
        results = []
        with patch('atool_qt.comms_login.login_args', return_value=['login', '--sso', '--session', 'sso']):
            self.workspace.comms.submit(['package', '--session', 'sso', 'list'], results.append)
            self.until(lambda: bool(results))
        self.assertFalse(results[0].successful)
        self.assertIn('Sign In to Comms (SSO)', results[0].message)
        self.assertEqual(len(self.recorded()), 1)

    def test_sso_source_migration_stops_before_refreshing_sessions(self):
        from atool_qt.configuration import ConfigurationActions
        self.workspace.report_error = Mock()
        self.workspace.run_comms_operation = Mock()
        with patch('atool_qt.configuration.login_args', return_value=['login', '--sso', '--session', 'sso']):
            ConfigurationActions.migrate_config(self.workspace, confirm=False)
        self.workspace.report_error.assert_called_once()
        self.assertIn('source uses SSO', self.workspace.report_error.call_args.args[1])
        self.workspace.run_comms_operation.assert_not_called()

    def test_old_cli_shows_update_guidance(self):
        self.mode.write_text('unsupported')
        dialog = self.dialog()
        dialog.sign_in.click()
        self.until(lambda: dialog.job.done)
        self.assertIn('OCCS CLI 1.4.0', dialog.status.text())
        self.assertIn('CLI Path', dialog.status.text())

    def test_cancel_closes_login_process_and_keeps_original_alias(self):
        self.mode.write_text('slow')
        self.settings.payload['occs'].update(request_timeout_seconds=1, sso_timeout_seconds=9)
        dialog = self.dialog()
        dialog.sign_in.click()
        self.until(lambda: bool(dialog.job.stdout))
        self.assertEqual(dialog.job.timer.interval(), 39000)
        dialog.reject()
        self.until(lambda: dialog.job.done)
        self.assertTrue(dialog.job.cancelled)
        self.assertEqual(dialog.job.process.state(), QProcess.ProcessState.NotRunning)
        self.assertTrue(self.terminated.exists())
        self.assertEqual(self.settings.get('session_alias'), 'np')

    def test_timeout_is_reported_without_changing_default_session(self):
        self.mode.write_text('slow')
        dialog = self.dialog()
        dialog.sign_in.click()
        self.until(lambda: bool(dialog.job.stdout))
        dialog.job.timeout()
        self.until(lambda: dialog.job.done)
        self.assertTrue(dialog.job.timed_out)
        self.assertIn('timed out', dialog.status.text())
        self.assertTrue(dialog.sign_in.isEnabled())
        self.assertEqual(self.settings.get('session_alias'), 'np')

    def test_session_identifiers_are_redacted(self):
        self.assertEqual(sanitized_http_value({'idcs_session_id': 'secret', 'access_info': 'secret'}),
                         {'idcs_session_id': '[redacted]', 'access_info': '[redacted]'})


if __name__ == '__main__':
    unittest.main()
