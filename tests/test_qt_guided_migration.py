"""Guided migration gates, durable evidence, and CLI orchestration without remote writes."""
import copy
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from atool_qt.guided_migration import GuidedMigrationDialog, smoke_passed
from atool_qt.migration_record import MigrationRecord, eligible_batch
from atool_qt.user_settings import UserSettings


class GuidedMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.suites=self.root/'suites'
        self.suites.mkdir()
        self.input=self.suites/'input.json'
        self.input.write_text('{"bill":1}')
        self.suite=self.suites/'suite.json'
        self.suite.write_text(json.dumps(dict(name='POC 5 Bills',tenancy='non-prod',tests=[dict(package='CLP_bills',input='input.json',output='html')],compareSession='unwanted')))
        self.control=self.root/'control.json'
        self.control.write_text('{}')
        self.cli=self.root/'fake-cli'
        self.cli.write_text(f'#!{sys.executable}\nCONTROL={str(self.control)!r}\n'+'''import json, sys, uuid
from pathlib import Path
args=sys.argv[1:]
control=json.loads(Path(CONTROL).read_text())
with Path(CONTROL).with_suffix('.calls.jsonl').open('a') as log:log.write(json.dumps(args)+'\\n')
config={'id':'10','shortName':'BillsFix','name':'Bill change','status':'Open'}
def option(key):return args[args.index(key)+1]
def emit(value):print(json.dumps(value))
if args[0]=='list-configs':emit({'configs':[config]+([dict(config,id='20',shortName='OtherFix',name='Other change')] if control.get('two_configs') else [])})
elif args[0]=='close-config':
    if control.get('close_failure') or control.get('close_failure_id')==option('--config-id'):sys.exit(2)
    emit({'ok':True,'closed':True,'config':dict(config,id='wrong' if control.get('wrong_close') else option('--config-id'))})
elif args[0]=='migrate':
    eligible=[{'shortName':'BillsFix','name':'Bill change'}]
    if control.get('extra_config'):eligible.append({'shortName':'Unexpected'})
    if control.get('migration_failure') and '--dry-run' not in args:sys.exit(2)
    emit({'ok':True,'dryRun':'--dry-run' in args,'initiated':'--dry-run' not in args,'eligible':eligible})
elif args[0]=='smoke':
    suite=json.loads(Path(option('--suite')).read_text())
    root=Path(option('--output')+'-'+uuid.uuid4().hex)
    root.mkdir(parents=True)
    failed=control.get('smoke_failure',False)
    row={'status':'Fail' if failed else 'Pass'}
    comparison='--compare-session' in args
    if comparison:
        row['comparison']={'status':'Fail' if control.get('target_failure') else 'Pass'}
        row['compare']={'status':'Review' if control.get('review') else 'Pass'}
    data={'summary':{'passed':0 if failed else 1,'failed':1 if failed else 0},'results':[row]}
    if control.get('malformed'):data['summary']={'passed':0,'failed':0}
    (root/'smoke-results.json').write_text(json.dumps(data))
    (root/'smoke-report.html').write_text('<html>Smoke report</html>')
    (root/'smoke-email.eml').write_text('Subject: Smoke results\\n\\nSaved report')
    (root/'invocation.json').write_text(json.dumps({'args':args,'suite':suite,'input':Path(suite['tests'][0]['input']).read_text()}))
    print('Report: '+str(root/'smoke-report.html'))
    sys.exit(1 if failed else 0)
''')
        self.cli.chmod(0o755)
        self.window=WorkspaceWindow(QSettings(str(self.root/'qt.ini'),QSettings.Format.IniFormat))
        self.settings=UserSettings(self.root/'settings.json')
        self.settings.payload['application']['confirm_on_quit']=False
        self.settings.payload['occs'].update(cli_path=str(self.cli),work_dir=str(self.root/'work'),shared_workspace_dir=str(self.root/'shared'),session_alias='unrelated-default')
        self.settings.payload['smoke_tests'].update(suite_dir=str(self.suites))
        self.window.comms.settings=self.settings
        self.addCleanup(self.close)
        self.dialog=GuidedMigrationDialog(self.window)
        self.window.migration_dialog=self.dialog
        self.dialog.show()

    def close(self):
        if self.window.smoke_dialog and self.window.smoke_dialog.running:
            self.window.smoke_dialog.stop()
        self.window.comms.shutdown()
        self.window.close()
        self.app.processEvents()

    def until(self,condition):
        deadline=time.monotonic()+8
        while not condition() and time.monotonic()<deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(condition(),'Timed out waiting for the fake CLI')

    def start_record(self,select_all=False):
        d=self.dialog
        d.load_configs()
        self.until(lambda:not d.busy)
        d.configs.item(0).setSelected(True)
        if select_all:
            d.configs.selectAll()
        d.targets_ack.setChecked(True)
        with patch('atool_qt.guided_migration.saved_login_targets',return_value=({},'')):
            d.create_record()
        return d.record

    def smoke(self,comparison=False):
        self.dialog.run_smoke(comparison)
        self.until(lambda:not self.dialog.busy)

    def skip_sync(self):
        self.dialog.skip_sync.setChecked(True)
        self.dialog.sync_complete()

    def close_configs(self):
        with patch('atool_qt.guided_migration.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            self.dialog.close_configs()
            self.until(lambda:not self.dialog.busy)

    def migrate(self):
        with patch('atool_qt.guided_migration.login_args',return_value=['login','--session','np']),patch('atool_qt.guided_migration.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            self.dialog.migrate()
            self.until(lambda:not self.dialog.busy)

    def configure(self,**values):
        self.control.write_text(json.dumps(values))

    def test_complete_flow_uses_frozen_suite_and_requires_reviews(self):
        self.assertIn(self.window.migration_action,self.window.package_menu.actions())
        record=self.start_record()
        with self.assertRaises(ValueError):
            self.dialog.complete()
        self.input.write_text('{"bill":999}')
        self.suite.unlink()
        self.smoke()
        self.assertEqual(record.data['stage'],'sync')
        with self.assertRaises(ValueError):
            self.dialog.sync_complete()
        self.skip_sync()
        self.close_configs()
        self.assertEqual(record.data['stage'],'migrate')
        self.migrate()
        self.assertEqual(record.data['stage'],'awaiting_completion')
        self.assertEqual(record.data['movement']['initiated'],True)
        with patch.object(self.dialog,'confirmation_note',return_value='Verified target movement completed'):
            self.dialog.external_completion()
        self.configure(review=True)
        self.smoke(True)
        self.assertEqual(record.data['stage'],'review')
        self.assertEqual(record.data['postflight']['runs'][0]['reviews'],1)
        with self.assertRaises(ValueError):
            self.dialog.complete()
        self.dialog.review_ack.setChecked(True)
        with self.assertRaises(ValueError):
            self.dialog.complete()
        self.dialog.review_note.setPlainText('Expected timestamp change; amounts and layout match.')
        self.dialog.complete()
        self.assertEqual(record.data['stage'],'complete')
        self.assertNotIn('email_sent',record.data)
        for mode in ('preflight','postflight'):
            report=Path(record.data[mode]['runs'][0]['report'])
            call=json.loads(report.with_name('invocation.json').read_text())
            self.assertEqual(call['input'],'{"bill":1}')
            self.assertNotIn('compareSession',call['suite'])
            self.assertNotIn('unrelated-default',call['args'])
            if mode=='preflight':
                self.assertIn('--tenancy',call['args'])
                self.assertNotIn('--compare-session',call['args'])
            else:
                self.assertIn('--compare-session',call['args'])
                self.assertIn('np',call['args'])
                self.assertIn('pp',call['args'])
        with patch('atool_qt.guided_migration.QDesktopServices.openUrl') as opened:
            self.dialog.open_email()
        self.assertTrue(opened.call_args.args[0].toLocalFile().endswith('smoke-email.eml'))
        self.dialog.handoff_sent.setChecked(True)
        self.dialog.record_sent()
        saved=MigrationRecord.load(record.path)
        self.assertTrue(saved.data['email_sent'])
        self.assertEqual(saved.data['events'][-1]['kind'],'handoff_sent')

    def test_failed_and_malformed_smoke_cannot_advance_and_retry_is_single_use(self):
        record=self.start_record()
        for values in ({'smoke_failure':True},{'malformed':True}):
            self.configure(**values)
            self.smoke()
            self.assertEqual(record.data['stage'],'preflight')
            smoke=self.dialog.smoke
            self.assertFalse(smoke.run_button.isEnabled())
            self.assertFalse(smoke.suite_combo.isEnabled())
            with patch.object(self.window.comms,'submit') as submit:
                smoke.start()
            submit.assert_not_called()
        self.configure()
        self.smoke()
        self.assertEqual(record.data['stage'],'sync')

    def test_target_preview_failure_blocks_acceptance_even_if_cli_exits_successfully(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        with patch.object(self.dialog,'confirmation_note',return_value='Verified external migration completion'):
            self.dialog.external_completion()
        self.configure(target_failure=True)
        self.smoke(True)
        self.assertEqual(record.data['stage'],'postflight')
        self.assertTrue(record.data['postflight']['runs'][0]['successful'])
        self.assertEqual(record.data['postflight']['runs'][0]['failed'],1)
        with self.assertRaises(ValueError):
            self.dialog.complete()

    def test_resumes_without_repeating_completed_remote_operations(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.migrate()
        resumed=GuidedMigrationDialog(self.window)
        self.addCleanup(resumed.close)
        resumed.resume_combo.setCurrentIndex(0)
        with patch.object(self.window.comms,'submit') as submit:
            resumed.resume()
        submit.assert_not_called()
        self.assertEqual(resumed.record.data['stage'],'awaiting_completion')
        self.assertEqual(resumed.record.data['closed'],['10'])
        record.verify_inputs()
        (record.folder/'inputs'/'1.json').write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):
            record.verify_inputs()

    def test_extra_eligible_configs_block_movement(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.configure(extra_config=True)
        self.migrate()
        self.assertEqual(record.data['stage'],'migrate')
        self.assertNotIn('movement',record.data)
        self.assertIn('differs',self.dialog.status.text())
        self.assertFalse(any(e['kind']=='migration_started' for e in record.data['events']))

    def test_failed_migration_is_uncertain_and_does_not_retry_on_resume(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.configure(migration_failure=True)
        self.migrate()
        self.assertEqual(record.data['pending'],'migration')
        saved=MigrationRecord.load(record.path)
        self.assertEqual(saved.data['stage'],'migrate')
        with self.assertRaisesRegex(ValueError,'previous migration'):
            self.dialog.migrate()
        self.dialog.record=saved
        with patch.object(self.window.comms,'submit') as submit:
            self.dialog.render()
        submit.assert_not_called()
        with patch.object(self.dialog,'confirmation_note',return_value='Target shows no movement; source Configs remain eligible.'):
            self.dialog.clear_uncertain_migration()
        self.assertIsNone(saved.data['pending'])

    def test_lockouts_and_wrong_close_receipt_block_progress(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        with patch.object(self.window,'config_lifecycle_allowed',return_value=False),patch.object(self.window.comms,'submit') as submit:
            self.dialog.close_configs()
        submit.assert_not_called()
        self.configure(wrong_close=True)
        self.close_configs()
        self.assertEqual(record.data['stage'],'close')
        self.assertEqual(record.data['closed'],[])
        self.assertIn('did not confirm',self.dialog.status.text())

    def test_partial_config_closure_resumes_without_reclosing_successful_configs(self):
        self.configure(two_configs=True,close_failure_id='20')
        record=self.start_record(select_all=True)
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.assertEqual(record.data['stage'],'close')
        self.assertEqual(record.data['closed'],['10'])
        self.assertEqual(record.data['pending'],'close 20')
        self.dialog.record=MigrationRecord.load(record.path)
        self.configure(two_configs=True)
        self.close_configs()
        self.assertEqual(self.dialog.record.data['stage'],'migrate')
        calls=[json.loads(line) for line in self.control.with_suffix('.calls.jsonl').read_text().splitlines()]
        ids=[call[call.index('--config-id')+1] for call in calls if call[0]=='close-config']
        self.assertEqual(ids,['10','20','20'])

    def test_only_matching_publish_receipt_satisfies_sync(self):
        record=self.start_record()
        self.smoke()
        receipt=dict(package='print_bulk',version='3.0',config_id='wrong',source='np',no_changes=False)
        with self.assertRaises(ValueError):
            self.dialog.published(receipt)
        receipt['config_id']='10'
        self.dialog.published(receipt)
        self.dialog.sync_complete()
        self.assertEqual(record.data['stage'],'close')
        self.assertFalse(record.data['sync_skipped'])

    def test_record_concurrent_updates_are_rejected(self):
        record=self.start_record()
        other=MigrationRecord.load(record.path)
        record.event('one_window')
        with self.assertRaisesRegex(ValueError,'another window'):
            other.event('second_window')

    def test_migration_dry_run_requires_exact_unambiguous_batch(self):
        configs=[dict(id='1',shortName='A'),dict(id='2',shortName='B')]
        for items in ([],[dict(shortName='A')],[dict(shortName='A'),dict(shortName='B'),dict(shortName='C')]):
            with self.subTest(items=items),self.assertRaises(ValueError):
                eligible_batch(configs,dict(eligible=items))
        self.assertEqual(len(eligible_batch(configs,dict(eligible=[dict(shortName='B'),dict(shortName='A')]))),2)

    def test_smoke_gate_requires_evidence_and_success(self):
        self.assertFalse(smoke_passed({}))
        outcome=dict(stopped=False,runs=[dict(valid=True,successful=True,failed=0,passed=1,reviews=1)])
        self.assertTrue(smoke_passed(outcome))
        for key,value in [('valid',False),('successful',False),('failed',1),('passed',0),('cancelled',True),('timed_out',True)]:
            broken=copy.deepcopy(outcome)
            broken['runs'][0][key]=value
            self.assertFalse(smoke_passed(broken))


if __name__=='__main__':
    unittest.main()
