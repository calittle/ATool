"""Email controls, CLI contract and input lifecycle; no actual email delivery."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Signal, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from atool_qt.occs import CommandResult, CommsSettings
from atool_qt.package_email import EmailDialog, email_defaults, email_payload, email_recipients, prepare_email_input
from atool_qt.session import demo_session
from atool_qt.user_settings import UserSettings


class FakeJob(QObject):
    completed = Signal(object)
    def __init__(self):
        super().__init__()
        self.done = False
        self.cancelled = False
    def cancel(self):
        self.cancelled = True


class EmailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.window=WorkspaceWindow(QSettings(str(self.root/'qt.ini'),QSettings.Format.IniFormat))
        settings=UserSettings(self.root/'settings.json')
        settings.payload['application']['confirm_on_quit']=False
        settings.payload['occs']['session_alias']='nonprod'
        self.window.comms.settings=settings
        self.target = {'sessionKey': 'test.local/nonprod', 'baseUrl': 'https://example.invalid/nonprod'}
        target = patch('atool_qt.package_email.email_session_target', return_value=self.target)
        target.start();self.addCleanup(target.stop)
        self.payload={'billPrint':{'billDetails':{'cmElements':{'eBill':{'keep':'value'}}}}, 'unknown':[1]}
        self.source=self.root/'data.json'
        self.source.write_text(json.dumps(self.payload))
        session=demo_session()
        session.map_data(self.payload,str(self.source))
        self.window.set_session(session)
        self.calls=[]
        runner=patch.object(self.window,'run_comms_operation',side_effect=self.command)
        runner.start();self.addCleanup(runner.stop)
        self.errors=[]
        reporter=patch.object(self.window,'report_error',side_effect=lambda title,message:self.errors.append(message))
        reporter.start();self.addCleanup(reporter.stop)
        defaults=patch('atool_qt.package_email.email_defaults',return_value={'recipients':'one@example.test, two@example.test','config_uuid':'uuid-1'})
        defaults.start();self.addCleanup(defaults.stop)
        self.cache = self.root / 'comms-cache'
        (self.cache / 'email-routes').mkdir(parents=True)
        (self.cache / 'email-routes' / 'index.json').write_text(json.dumps(self.catalog_result()))
        settings.payload['occs']['comms_cache_dir'] = str(self.cache)
        self.dialog=EmailDialog(self.window)
        self.dialog.config_picker.setCurrentIndex(0)
        self.addCleanup(self.close)

    def close(self):
        for call in self.calls:
            if not call['job'].done:
                call['job'].done=True
                call['job'].completed.emit(CommandResult(-1,'','',None,cancelled=True))
        self.dialog.reject()
        self.window.editor.saved=self.window.editor.snapshot()
        self.window.close()

    def command(self,title,args,callback=None,**kwargs):
        job=FakeJob()
        self.calls.append(dict(args=args,callback=callback,options=kwargs,job=job))
        return job

    def complete(self,index=0,result=None):
        call=self.calls[index]
        result=result or CommandResult(0,'Completed','',None)
        call['job'].done=True
        if result.successful:
            with patch.object(QMessageBox,'information'):
                call['callback'](result)
        call['job'].completed.emit(result)

    def catalog_result(self, *, uuid='uuid-1', name='Billing Email'):
        return {'ok': True, 'count': 1,
                'routes': [{'shortName': 'Bill_Email', 'name': name, 'uuid': uuid,
                            'transactionType': 'User Defined', 'userDefinedTransactionType': 'Bill_Email'}],
                'session': {**self.target, 'alias': ''}, 'fetchedAt': '2026-10-20T12:00:00Z'}

    def test_one_click_send_uses_lookup_uuid_and_cleans_input(self):
        original = self.source.read_bytes()
        self.assertTrue(self.dialog.send_button.isEnabled())
        self.dialog.send_button.click()
        self.assertEqual(len(self.calls), 1)
        args = self.calls[0]['args']
        self.assertEqual(args[:3], ['preview', '--session', 'nonprod'])
        self.assertEqual(args[args.index('--communication-config-uuid') + 1], 'uuid-1')
        self.assertEqual(args[args.index('--render-type') + 1], 'EMAIL')
        self.assertNotIn('--email-config-uuid', args)
        self.assertEqual(args[args.index('--communication-user-defined-transaction-type') + 1], 'Bill_Email')
        self.assertEqual(args[-1], '--send-email')
        path = Path(args[args.index('--input') + 1])
        prepared = json.loads(path.read_text())
        self.assertEqual(prepared['billPrint']['billDetails']['cmElements']['eBill']['recipientEmails'],
                         [{'email': 'one@example.test'}, {'email': 'two@example.test'}])
        self.assertTrue(self.dialog.closed)
        self.assertFalse(self.calls[0]['job'].cancelled)
        self.complete()
        self.assertFalse(path.exists())
        self.assertEqual(self.source.read_bytes(), original)

    def test_debug_enables_verbose_email_diagnostics(self):
        self.window.comms.settings.payload['diagnostics']['debug_logging'] = True
        self.dialog.submit()
        self.assertIn('--verbose', self.calls[0]['args'])
        self.assertIn('--send-email', self.calls[0]['args'])

    def test_distribution_uuid_overrides_obsolete_uuid_history_and_remembers_distribution(self):
        key = json.dumps(self.target, sort_keys=True)
        self.window.comms.settings.payload['occs']['email_send_mru'] = {
            key: {'uuids': ['C9176FFB4B2E4DFFBE3C541C8D97DCD5']}}
        self.dialog.submit()
        args = self.calls[0]['args']
        self.assertEqual(args[args.index('--communication-config-uuid') + 1], 'uuid-1')
        self.complete(result=CommandResult(1, '', 'Comms rejected request', None))
        reopened = EmailDialog(self.window)
        try:
            self.assertEqual(reopened.selected_route()['userDefinedTransactionType'], 'Bill_Email')
            self.assertFalse(hasattr(reopened, 'config'))
            self.assertFalse(hasattr(reopened, 'uuid_picker'))
            self.assertNotIn('uuids', reopened.routing_history())
        finally:
            reopened.reject()

    def test_same_parent_transactions_remain_separate_lookup_choices(self):
        payload = self.catalog_result()
        payload['routes'].append({**payload['routes'][0], 'userDefinedTransactionType': 'Letter_DA_Email'})
        self.dialog.refresh_emails()
        self.complete(result=CommandResult(0, '', '', payload))
        self.assertEqual(self.dialog.config_picker.count(), 2)
        self.dialog.config_picker.setCurrentIndex(1)
        self.assertEqual(self.dialog.selected_uuid(), 'uuid-1')
        self.assertEqual(self.dialog.transaction.text(), 'User Defined / Letter_DA_Email')
        self.assertTrue(self.dialog.transaction.isReadOnly())
        self.dialog.submit()
        args = self.calls[-1]['args']
        self.assertEqual(args[args.index('--communication-user-defined-transaction-type') + 1], 'Letter_DA_Email')
        self.assertEqual(args[args.index('--communication-transaction-type') + 1], 'User Defined')

    def test_lookup_only_no_manual_defaults_or_saved_aliases(self):
        self.assertFalse(self.dialog.config_picker.isEditable())
        self.assertFalse(hasattr(self.dialog, 'config'))
        self.assertFalse(hasattr(self.dialog, 'uuid_picker'))
        self.assertFalse(hasattr(self.dialog, 'dry_run'))
        self.assertFalse(hasattr(self.dialog, 'save_config_button'))
        self.assertFalse(self.dialog.status.isVisible())
        self.window.comms.settings.payload['occs']['email_config_profiles'] = {
            'nonprod': [{'name': 'Old saved alias', 'uuid': 'manual-uuid'}]}
        (self.cache / 'email-routes' / 'index.json').write_text(json.dumps(self.catalog_result(uuid='other-uuid')))
        reopened = EmailDialog(self.window)
        try:
            self.assertEqual(reopened.config_picker.count(), 1)
            self.assertEqual(reopened.config_picker.currentIndex(), -1)
            self.assertEqual(reopened.selected_uuid(), '')
            self.assertFalse(reopened.send_button.isEnabled())
            reopened.submit()
            self.assertEqual(self.calls, [])
            self.assertIn('from the lookup', self.errors[-1])
            reopened.config_picker.setCurrentIndex(0)
            self.assertEqual(reopened.selected_uuid(), 'other-uuid')
            self.assertTrue(reopened.send_button.isEnabled())
        finally:
            reopened.reject()

    def test_unconfigured_cache_uses_atool_for_refresh_and_reopening(self):
        self.window.comms.settings.payload['occs']['comms_cache_dir'] = ''
        with patch('atool_qt.package_email.Path.home', return_value=self.root):
            dialog = EmailDialog(self.window)
            try:
                target = self.root / '.atool' / 'email-routes' / 'index.json'
                self.assertEqual(dialog.email_cache_path(), target)
                dialog.refresh_emails()
                args = self.calls[0]['args']
                self.assertEqual(args[args.index('--output') + 1], str(target.parent))
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps(self.catalog_result()))
                self.complete(result=CommandResult(0, '', '', self.catalog_result()))
            finally:
                dialog.reject()
            reopened = EmailDialog(self.window)
            try:
                self.assertEqual(reopened.config_picker.count(), 1)
                self.assertEqual(reopened.catalog[0]['uuid'], 'uuid-1')
                self.assertEqual(len(self.calls), 1)
            finally:
                reopened.reject()

    def test_no_cache_requires_refresh_and_selection(self):
        (self.cache / 'email-routes' / 'index.json').unlink()
        reopened = EmailDialog(self.window)
        try:
            self.assertEqual(reopened.config_picker.count(), 0)
            self.assertFalse(reopened.send_button.isEnabled())
            reopened.submit()
            self.assertEqual(self.calls, [])
            self.assertIn('Refresh from Comms', reopened.status.text())
        finally:
            reopened.reject()

    def test_recipient_popup_multiple_selection_and_typing(self):
        picker = self.dialog.recipient_picker
        self.dialog.show()
        picker.showPopup()
        self.app.processEvents()
        row = picker.view().visualRect(picker.model().index(0, 0)).center()
        QTest.mouseClick(picker.view().viewport(), Qt.MouseButton.LeftButton, pos=row)
        self.assertEqual(self.dialog.recipients.text(), 'two@example.test')
        self.assertTrue(picker.view().isVisible())
        QTest.mouseClick(picker.view().viewport(), Qt.MouseButton.LeftButton, pos=row)
        self.assertEqual(self.dialog.recipients.text(), 'two@example.test, one@example.test')
        picker.hidePopup()
        self.dialog.recipients.clear()
        self.assertFalse(self.dialog.send_button.isEnabled())
        self.dialog.recipients.setText('typed@example.test')
        self.assertTrue(self.dialog.send_button.isEnabled())
        self.dialog.submit()
        args = self.calls[0]['args']
        self.assertEqual(args[args.index('--recipient') + 1], 'typed@example.test')

    def test_history_saved_after_successful_send_only(self):
        self.dialog.recipients.setText('New@example.test, new@example.test, second@example.test')
        self.dialog.submit()
        self.assertEqual(self.window.comms.settings.get('email_recipient_mru'), [])
        self.complete()
        stored = UserSettings(self.root / 'settings.json')
        self.assertEqual(stored.get('email_recipient_mru'), ['New@example.test', 'second@example.test'])
        self.window.comms.settings = stored
        reopened = EmailDialog(self.window)
        try:
            choices = [reopened.recipient_picker.itemText(row) for row in range(reopened.recipient_picker.count())]
            self.assertIn('New@example.test', choices)
        finally:
            reopened.reject()

    def test_failure_and_cancellation_clean_temporary_input(self):
        for result in (CommandResult(1, '', 'failure', None), CommandResult(-1, '', '', None, cancelled=True)):
            dialog = EmailDialog(self.window)
            dialog.config_picker.setCurrentIndex(0)
            dialog.submit()
            args = self.calls[-1]['args']
            path = Path(args[args.index('--input') + 1])
            self.assertTrue(path.exists())
            self.complete(len(self.calls) - 1, result)
            self.assertFalse(path.exists())
        self.assertEqual(self.window.comms.settings.get('email_recipient_mru'), [])

    def test_environment_change_and_remapping_cannot_send(self):
        self.window.comms.settings.payload['occs']['session_alias'] = 'preprod'
        self.dialog.submit()
        self.assertEqual(self.calls, [])
        self.assertIn('environment changed', self.errors[-1])
        self.window.comms.settings.payload['occs']['session_alias'] = 'nonprod'
        self.window.session = demo_session()
        self.dialog.submit()
        self.assertEqual(self.calls, [])
        self.assertIn('Mapped data changed', self.errors[-1])

    def test_notification_supports_one_recipient_and_preserves_original(self):
        payload = {'sendDetail': {'deliveryInfo': {'contactValue': 'original@example.test'}}}
        self.window.session.map_data(payload, str(self.source))
        dialog = EmailDialog(self.window)
        dialog.config_picker.setCurrentIndex(0)
        try:
            self.assertFalse(dialog.recipient_picker.multiple)
            dialog.submit()
            self.assertEqual(self.calls, [])
            self.assertIn('exactly one', self.errors[-1])
            dialog.recipients.setText('test@example.test')
            dialog.submit()
            args = self.calls[0]['args']
            path = Path(args[args.index('--input') + 1])
            self.assertEqual(json.loads(path.read_text())['sendDetail']['deliveryInfo']['contactValue'], 'test@example.test')
            self.assertEqual(payload['sendDetail']['deliveryInfo']['contactValue'], 'original@example.test')
            self.complete()
            self.assertFalse(path.exists())
        finally:
            dialog.reject()

    def test_existing_recipients_and_wrapped_data_preparation(self):
        self.payload['billPrint']['billDetails']['cmElements']['eBill']['recipientEmails'] = [{'email': 'json@example.test'}]
        path, temporary = prepare_email_input(self.payload, self.source, 'other@example.test')
        self.assertEqual(path, self.source)
        self.assertIsNone(temporary)
        self.assertEqual(email_recipients(self.payload), ['json@example.test'])
        wrapped = {'CommunicationInfo': {'CommunicationData': json.dumps(self.payload)}}
        self.assertEqual(email_payload(wrapped), self.payload)
        del self.payload['billPrint']['billDetails']['cmElements']['eBill']['recipientEmails']
        wrapped = {'CommunicationInfo': {'CommunicationData': json.dumps(self.payload)}}
        path, temporary = prepare_email_input(wrapped, self.source, 'one@example.test')
        self.assertEqual(json.loads(path.read_text())['billPrint']['billDetails']['cmElements']['eBill']['recipientEmails'], [{'email': 'one@example.test'}])
        temporary.cleanup()

    def test_other_environment_cache_is_not_offered(self):
        payload = self.catalog_result()
        payload['session']['baseUrl'] = 'https://example.invalid/preprod'
        (self.cache / 'email-routes' / 'index.json').write_text(json.dumps(payload))
        reopened = EmailDialog(self.window)
        try:
            self.assertEqual(reopened.config_picker.count(), 0)
            self.assertIn('another OCCS environment', reopened.status.text())
            self.assertFalse(reopened.send_button.isEnabled())
        finally:
            reopened.reject()

    def test_refresh_uses_cli_and_clears_removed_selection(self):
        self.dialog.refresh_emails()
        call = self.calls[0]
        self.assertEqual(call['args'][:2], ['list-email-routes', '--json'])
        self.assertEqual(call['args'][call['args'].index('--session') + 1], 'nonprod')
        self.assertEqual(call['args'][call['args'].index('--output') + 1], str(self.cache / 'email-routes'))
        self.assertTrue(call['options']['require_json'])
        self.assertFalse(self.dialog.send_button.isEnabled())
        self.dialog.submit()
        self.assertEqual(len(self.calls), 1)
        self.complete(result=CommandResult(0, '', '', self.catalog_result(uuid='new-uuid')))
        self.assertEqual(self.dialog.config_picker.currentIndex(), -1)
        self.assertEqual(self.dialog.selected_uuid(), '')
        self.assertFalse(self.dialog.send_button.isEnabled())
        self.dialog.config_picker.setCurrentIndex(0)
        self.assertTrue(self.dialog.send_button.isEnabled())
        self.assertEqual(self.dialog.selected_uuid(), 'new-uuid')
        self.assertEqual(self.dialog.status.text(), '')

    def test_failed_refresh_retains_selection_and_can_cancel(self):
        self.dialog.refresh_emails()
        self.calls[0]['options']['on_failure']('unknown command list-emails')
        self.complete(result=CommandResult(1, '', 'unknown command', None))
        self.assertEqual(self.dialog.selected_uuid(), 'uuid-1')
        self.assertTrue(self.dialog.send_button.isEnabled())
        self.dialog.refresh_emails()
        self.dialog.reject()
        self.assertTrue(self.calls[1]['job'].cancelled)

    def test_invalid_data_and_missing_file_never_send(self):
        self.window.session.map_data({}, str(self.source))
        self.dialog.submit()
        self.assertEqual(self.calls, [])
        self.window.session.map_data(self.payload, str(self.source))
        self.source.unlink()
        self.dialog.submit()
        self.assertEqual(self.calls, [])
        self.assertIn('not found', self.errors[-1])

    def test_cli_list_email_session_injection(self):
        args = self.window.comms.settings.command(['list-email-routes', '--json'])
        self.assertEqual(args[-4:], ['list-email-routes', '--session', 'nonprod', '--json'])


class EmailDefaultsTests(unittest.TestCase):
    def test_original_env_file_precedence_and_process_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'.occs-cli').mkdir();(root/'cli').mkdir()
            cli=root/'cli'/'occs';cli.write_text('')
            settings=CommsSettings(root/'settings.json');settings.payload={'occs':{'cli_path':str(cli)}}
            (root/'explicit.env').write_text('OCCS_EMAIL_CONFIG_UUID=explicit\n')
            (root/'.occs.env').write_text('export OCCS_EMAIL_CONFIG_UUID="home"\nOCCS_EMAIL_RECIPIENTS=home@example.test\n')
            (root/'.occs-cli'/'.env').write_text("OCCS_EMAIL_CONFIG_UUID='global'\n")
            (root/'cli'/'.env').write_text('OCCS_EMAIL_CONFIG_UUID=cli\n')
            self.assertEqual(email_defaults(settings,home=root,environ={'OCCS_ENV_FILE':str(root/'explicit.env')}),{'config_uuid':'cli','recipients':'home@example.test'})
            self.assertEqual(email_defaults(settings,home=root,environ={'OCCS_EMAIL_CONFIG_UUID':'override','OCCS_EMAIL_RECIPIENTS':'env@example.test'}),{'config_uuid':'override','recipients':'env@example.test'})
