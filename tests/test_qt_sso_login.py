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
from atool_qt.user_settings import SettingsActions
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
elif mode in ('missing', 'missing-json'):
    message = 'Session not found. Run `occs login` first.'
    if mode == 'missing-json':
        print(json.dumps({{'ok': False, 'error': {{'message': message}}}}))
        sys.exit(0)
    print(message, file=sys.stderr)
    sys.exit(1)
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
        self.assertIn('browser closed or disconnected', dialog.status.text())
        self.assertTrue(dialog.sign_in.isEnabled())
        self.assertEqual(self.settings.get('session_alias'), 'np')

    def test_browser_failure_diagnostics_are_collapsed_bounded_and_cleared_on_retry(self):
        dialog = self.dialog()
        dialog.show()
        details = ('SSO login failed: browserContext.cookies: Target page, context or browser has been closed\n'
                   'Browser logs:\n' + '--browser-argument ' * 1000
                   + '\nAuthorization: Bearer SYNTHETIC_LOGIN_SECRET')
        dialog.login_finished(Mock(cancelled=False, timed_out=False, successful=False, message=details))
        self.app.processEvents()
        self.assertIn('keep the browser open', dialog.status.text())
        self.assertNotIn('Browser logs', dialog.status.text())
        self.assertFalse(dialog.diagnostics.isVisible())
        self.assertTrue(dialog.diagnostics_toggle.isVisible())
        dialog.diagnostics_toggle.click()
        self.app.processEvents()
        self.assertTrue(dialog.diagnostics.isVisible())
        self.assertGreater(dialog.sign_in.y(), dialog.diagnostics.geometry().bottom())
        self.assertIn('browserContext.cookies', dialog.diagnostics.toPlainText())
        self.assertNotIn('SYNTHETIC_LOGIN_SECRET', dialog.diagnostics.toPlainText())
        self.assertLess(dialog.minimumSizeHint().width(), 1000)
        self.assertLess(dialog.minimumSizeHint().height(), 800)
        dialog.diagnostics_toggle.click()
        self.assertFalse(dialog.diagnostics.isVisible())
        dialog.sign_in.click()
        self.assertTrue(dialog.diagnostics_toggle.isHidden())
        self.assertEqual(dialog.diagnostics.toPlainText(), '')
        self.until(lambda: dialog.job.done)
        self.assertIn('Signed in.', dialog.status.text())
        self.assertTrue(dialog.diagnostics_toggle.isHidden())

    def test_other_login_errors_are_plain_text_and_available_in_diagnostics(self):
        dialog = self.dialog()
        details = '<b>unrecognised failure</b>\n' + 'details ' * 1000
        dialog.login_finished(Mock(cancelled=False, timed_out=False, successful=False, message=details))
        self.assertIn('SSO sign-in failed.', dialog.status.text())
        self.assertNotIn('<b>', dialog.status.text())
        self.assertEqual(dialog.diagnostics.toPlainText(), details.strip())

    def test_sso_expiry_never_opens_browser_or_replays_operation(self):
        self.mode.write_text('expired')
        results = []
        requested = []
        self.workspace.comms.sign_in_required.connect(requested.append)
        self.workspace.comms.submit(['preview', '--session', 'sso'], results.append)
        self.until(lambda: bool(results))
        self.assertFalse(results[0].successful)
        self.assertIn('Settings → Sign In to Comms', results[0].message)
        self.assertEqual(len(self.recorded()), 1)
        self.assertFalse(self.workspace.comms.logins)
        self.assertEqual(requested, ['sso'])

    def test_missing_session_opens_sign_in_with_requested_alias_without_replay(self):
        for mode, args, alias in (
            ('missing-json', ['package', 'list', '--json'], 'np'),
            ('missing', ['package', '--session', 'other', 'list'], 'other'),
        ):
            with self.subTest(mode=mode):
                self.mode.write_text(mode)
                results = []
                self.workspace.comms.sign_in_required.connect(
                    lambda requested: SettingsActions.open_comms_login(self.workspace, requested))
                self.workspace.comms.submit(args, results.append)
                self.until(lambda: bool(results))
                self.assertFalse(results[0].successful)
                dialog = self.workspace.comms_login_dialog
                self.addCleanup(dialog.close)
                self.assertTrue(dialog.isVisible())
                self.assertEqual(dialog.alias.currentText(), alias)
                self.assertIsNone(dialog.job)
                self.assertFalse(self.workspace.comms.logins)
                # Concurrent failures reuse the visible sign-in window.
                SettingsActions.open_comms_login(self.workspace, alias)
                self.assertIs(self.workspace.comms_login_dialog, dialog)
                dialog.close()
                self.workspace.comms.sign_in_required.disconnect()
        self.assertEqual([args[0] for args in self.recorded()], ['package', 'package'])

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
        self.assertIn('Sign In to Comms', results[0].message)

    def test_generic_unauthorized_for_saved_sso_does_not_fall_back_to_password_login(self):
        self.mode.write_text('password')
        results = []
        with patch('atool_qt.comms_login.login_args', return_value=['login', '--sso', '--session', 'sso']):
            self.workspace.comms.submit(['package', '--session', 'sso', 'list'], results.append)
            self.until(lambda: bool(results))
        self.assertFalse(results[0].successful)
        self.assertIn('Sign In to Comms', results[0].message)
        self.assertEqual(len(self.recorded()), 1)

    def test_password_target_never_adds_sso_and_keeps_password_guidance(self):
        store = json.loads(self.sessions.read_text())
        store['sessions']['example.region/non-prod']['authType'] = 'password'
        self.sessions.write_text(json.dumps(store))
        dialog = self.dialog()
        self.assertEqual(dialog.method.currentData(), 'password')
        self.assertIn('password', dialog.help_text.text())
        dialog.sign_in.click()
        self.until(lambda: dialog.job.done)
        self.assertNotIn('--sso', self.recorded()[0])
        self.assertEqual(self.recorded()[0][:3], ['login', '--session', 'sso'])

    def test_unknown_alias_defaults_to_password_and_method_can_be_chosen(self):
        dialog = self.dialog()
        self.assertEqual(dialog.method.currentData(), 'sso')
        dialog.alias.setCurrentText('new-password')
        self.assertEqual(dialog.method.currentData(), 'password')
        self.assertNotIn('SSO sign-in', dialog.status.text())
        dialog.method.setCurrentIndex(1)
        self.assertEqual(dialog.method.currentData(), 'sso')

    def test_password_failure_does_not_tell_user_to_fix_sso(self):
        dialog = self.dialog()
        dialog.method.setCurrentIndex(0)
        self.mode.write_text('failure')
        dialog.sign_in.click()
        self.until(lambda: dialog.job.done)
        self.assertIn('Password sign-in failed', dialog.status.text())
        self.assertNotIn('--sso', self.recorded()[0])

    def test_xml_conversion_can_select_password_without_changing_default(self):
        from atool_qt.data_actions import XmlConversionDialog
        self.workspace.session = None
        self.workspace.settings = Mock()
        self.settings.payload['occs']['session_alias'] = 'browser'
        targets = {'browser': {'authType': 'sso'}, 'password': {'authType': 'password'}}
        with patch('atool_qt.data_actions.saved_login_targets', return_value=(targets, 'browser')):
            dialog = XmlConversionDialog(self.workspace)
        self.addCleanup(dialog.close)
        self.assertIn('uses SSO', dialog.login_info.text())
        dialog.session_alias.setCurrentText('password')
        self.assertIn('password login', dialog.login_info.text())
        xml = self.root / 'convert.xml'
        xml.write_text('<bill/>')
        dialog.xml.setText(str(xml))
        with patch.object(self.workspace.comms, 'submit', return_value=Mock(done=True)) as submit:
            dialog.run_conversion()
        args = submit.call_args.args[0]
        self.assertEqual(args[args.index('--session') + 1], 'password')
        self.assertNotIn('--sso', args)
        command = self.settings.command(args)
        self.assertEqual(command.count('--session'), 1)
        self.assertEqual(self.settings.get('session_alias'), 'browser')

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
