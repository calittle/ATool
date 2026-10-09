"""Email controls, CLI contract and input lifecycle; no actual email delivery."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Signal
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
        self.dialog=EmailDialog(self.window)
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

    def test_generate_requires_dry_run_and_input_edits_invalidate(self):
        self.assertFalse(self.dialog.generate.isEnabled())
        self.dialog.submit(True)
        self.assertEqual(len(self.calls),0)
        self.assertIn('Run Dry Run',self.errors[-1])
        self.dialog.submit(False)
        self.assertNotIn('--send-email',self.calls[0]['args'])
        self.complete()
        self.assertTrue(self.dialog.generate.isEnabled())
        self.assertIn('No email was sent',self.dialog.status.text())
        self.dialog.config.setText('uuid-2')
        self.assertFalse(self.dialog.generate.isEnabled())
        self.dialog.submit(True)
        self.assertEqual(len(self.calls),1)
        self.dialog.submit(False);self.complete(1)
        self.assertTrue(self.dialog.generate.isEnabled())
        self.dialog.recipients.setText('other@example.test')
        self.assertFalse(self.dialog.generate.isEnabled())

    def test_dry_run_and_generate_contract_temp_cleanup_source_unchanged(self):
        original=self.source.read_bytes()
        original_payload=copy.deepcopy(self.payload)
        self.dialog.submit(False)
        args=self.calls[0]['args']
        self.assertEqual(args[:3],['preview','--session','nonprod'])
        self.assertEqual(args[args.index('--render-type')+1],'EMAIL')
        self.assertEqual(args[args.index('--email-config-uuid')+1],'uuid-1')
        path=Path(args[args.index('--input')+1])
        prepared=json.loads(path.read_text())
        self.assertEqual(prepared['billPrint']['billDetails']['cmElements']['eBill']['recipientEmails'],[{'email':'one@example.test'},{'email':'two@example.test'}])
        self.assertEqual(prepared['unknown'],[1])
        self.complete()
        self.assertFalse(path.exists())
        self.dialog.submit(True)
        self.assertTrue(self.dialog.closed)
        args=self.calls[1]['args']
        self.assertEqual(args[-1],'--send-email')
        path=Path(args[args.index('--input')+1])
        self.complete(1)
        self.assertFalse(path.exists())
        self.assertEqual(self.source.read_bytes(),original)
        self.assertEqual(self.payload,original_payload)

    def test_changed_inputs_during_dry_run_and_changed_file_before_generate(self):
        self.dialog.submit(False)
        self.dialog.recipients.setText('other@example.test')
        self.complete()
        self.assertFalse(self.dialog.generate.isEnabled())
        self.assertIn('changed during',self.dialog.status.text())
        self.dialog.submit(False);self.complete(1)
        self.source.write_text(json.dumps({'billPrint':{}}))
        self.dialog.submit(True)
        self.assertEqual(len(self.calls),2)
        self.assertFalse(self.dialog.generate.isEnabled())
        self.assertIn('Run Dry Run',self.errors[-1])

    def test_session_alias_and_remapping_invalidate_validation(self):
        self.dialog.submit(False);self.complete()
        self.window.comms.settings.payload['occs']['session_alias']='different'
        self.dialog.submit(True)
        self.assertEqual(len(self.calls),1)
        self.dialog.submit(False);self.complete(1)
        self.window.session.map_data(self.payload,str(self.source))
        self.dialog.submit(True)
        self.assertEqual(len(self.calls),2)

    def test_fail_cancel_and_dialog_close_cleanup_without_enabling_generate(self):
        self.dialog.submit(False)
        args=self.calls[0]['args'];path=Path(args[args.index('--input')+1])
        self.complete(result=CommandResult(1,'','failure',None))
        self.assertFalse(path.exists())
        self.assertFalse(self.dialog.generate.isEnabled())
        self.assertTrue(self.dialog.dry_run.isEnabled())
        self.assertIn('failure',self.dialog.status.text())
        self.dialog.submit(False)
        args=self.calls[1]['args'];path=Path(args[args.index('--input')+1])
        self.dialog.reject()
        self.assertTrue(self.calls[1]['job'].cancelled)
        self.complete(1,CommandResult(-1,'','',None,cancelled=True))
        self.assertFalse(path.exists())
        self.assertIsNone(self.dialog.verified)

    def test_existing_recipients_reuse_source_and_wrapped_input_extracts(self):
        self.payload['billPrint']['billDetails']['cmElements']['eBill']['recipientEmails']=[{'email':'json@example.test'}, {'email':''}, {}]
        self.source.write_text(json.dumps(self.payload))
        path,temporary=prepare_email_input(self.payload,self.source,'other@example.test')
        self.assertEqual(path,self.source)
        self.assertIsNone(temporary)
        self.assertEqual(email_recipients(self.payload),['json@example.test'])
        wrapped={'CommunicationInfo':{'CommunicationData':json.dumps(self.payload)}}
        self.assertEqual(email_payload(wrapped),self.payload)
        self.assertEqual(email_recipients(wrapped),['json@example.test'])
        del self.payload['billPrint']['billDetails']['cmElements']['eBill']['recipientEmails']
        for data in (self.payload,{'CommunicationInfo':{'CommunicationData':copy.deepcopy(self.payload)}}, {'CommunicationInfo':{'CommunicationData':json.dumps(self.payload)}}):
            path,temporary=prepare_email_input(data,self.source,'one@example.test')
            self.assertEqual(json.loads(path.read_text())['billPrint']['billDetails']['cmElements']['eBill']['recipientEmails'],[{'email':'one@example.test'}])
            temporary.cleanup()

    def test_invalid_payload_and_missing_inputs_never_start(self):
        self.dialog.recipients.clear();self.dialog.submit(False)
        self.assertEqual(self.calls,[])
        self.dialog.recipients.setText('one@example.test')
        self.dialog.config.clear();self.dialog.submit(False)
        self.assertEqual(self.calls,[])
        for payload in ([],{}, {'billPrint':{}}, {'billPrint':{'billDetails':{}}}, {'CommunicationInfo':{'CommunicationData':'invalid'}}, {'CommunicationInfo':{'CommunicationData':'[]'}}):
            with self.assertRaises(ValueError):
                prepare_email_input(payload,self.source,'one@example.test')
        self.window.session.map_data({},str(self.source))
        self.dialog.config.setText('uuid');self.dialog.submit(False)
        self.assertEqual(self.calls,[])


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
