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

from atool_qt.guided_migration import GuidedMigrationDialog, TargetVerificationDialog, smoke_passed
from atool_qt.migration_record import MigrationRecord, eligible_batch
from atool_qt.user_settings import UserSettings


class GuidedMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        remembered=patch('atool_qt.migration_login.remembered_migration_login',return_value='')
        remembered.start()
        self.addCleanup(remembered.stop)
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
elif args[0]=='login':
    if control.get('login_failure')==option('--session'):
        print('status code 401 Unauthorized',file=sys.stderr)
        sys.exit(2)
    print('Session refreshed')
elif args[0]=='migrate':
    if control.get('expect_migration_login'):
        credentials=json.load(sys.stdin)
        if (credentials.get('username')!='migration-user' or credentials.get('password')!='temporary-secret'
                or '--atool-migration-login' not in args):sys.exit(3)
    if control.get('already_migrated'):
        print('ConfigId 10 was not returned in the eligible movement list. eligible: []',file=sys.stderr)
        sys.exit(1)
    if control.get('batch_unauthorized') or (control.get('movement_unauthorized') and '--dry-run' not in args):
        print('status code 401 Unauthorized',file=sys.stderr)
        sys.exit(2)
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
        self.settings.payload['occs'].update(cli_path=str(self.cli),work_dir=str(self.root/'work'),shared_workspace_dir=str(self.root/'shared'),session_alias='unrelated-default',user_name='Migration Tester')
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
        with patch('atool_qt.guided_migration.login_args',side_effect=lambda alias:['login','--session',alias]),patch('atool_qt.guided_migration.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
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
        self.assertEqual(saved.data['reviewed_by']['displayName'],'Migration Tester')
        self.assertEqual(saved.data['completion_verification']['verified_by']['displayName'],'Migration Tester')
        report=saved.folder.joinpath('migration-report.md').read_text()
        self.assertIn('Expected timestamp change; amounts and layout match.',report)
        self.assertIn('Email reported sent by Migration Tester',report)

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

    def test_refreshes_target_and_source_before_dry_run_then_confirms_movement(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.migrate()
        calls=[json.loads(line) for line in self.control.with_suffix('.calls.jsonl').read_text().splitlines()]
        movement=[call for call in calls if call[0] in ('login','migrate')]
        self.assertEqual([call[0] for call in movement],['login','login','migrate','migrate'])
        self.assertEqual(movement[0],['login','--session','pp'])
        self.assertEqual(movement[1],['login','--session','np'])
        self.assertIn('--dry-run',movement[2])
        self.assertNotIn('--dry-run',movement[3])
        self.assertEqual(record.data['stage'],'awaiting_completion')

    def test_separate_login_migrates_with_sso_and_keeps_secrets_out_of_evidence(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.configure(expect_migration_login=True)
        self.dialog.separate_migration_login.setChecked(True)
        self.dialog.migration_username.setText('migration-user')
        self.dialog.migration_password.setText('temporary-secret')
        self.dialog.remember_migration_login.setChecked(True)
        original_command=self.settings.command
        def command(args):
            if '--atool-migration-login' in args:
                return [str(self.cli),*args]
            return original_command(args)
        with patch.object(self.settings,'command',side_effect=command), \
                patch('atool_qt.guided_migration.login_args',side_effect=lambda alias:['login','--sso','--session',alias]), \
                patch('atool_qt.guided_migration.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            self.dialog.migrate()
            self.until(lambda:not self.dialog.busy)
        self.assertEqual('awaiting_completion',record.data['stage'])
        calls=[json.loads(line) for line in self.control.with_suffix('.calls.jsonl').read_text().splitlines()]
        logins=[call for call in calls if call[0]=='login']
        self.assertEqual([['login','--sso','--session','pp','--sso-timeout','300000']],logins)
        migrations=[call for call in calls if call[0]=='migrate']
        self.assertEqual(2,len(migrations))
        self.assertIn('--dry-run',migrations[0])
        self.assertNotIn('--dry-run',migrations[1])
        for evidence in (record.path.read_text(),self.control.with_suffix('.calls.jsonl').read_text(),self.window.activity.toPlainText()):
            self.assertNotIn('temporary-secret',evidence)
        self.assertEqual('unrelated-default',self.settings.get('session_alias'))
        self.assertTrue(any(event['kind']=='migration_source_login_selected' and event['username']=='migration-user'
                            for event in record.data['events']))

    def test_remembered_migration_login_reappears_and_forget_clears_memory(self):
        self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        with patch('atool_qt.migration_login.remembered_migration_login',return_value='saved-user'):
            self.dialog.render()
            self.assertTrue(self.dialog.separate_migration_login.isChecked())
            self.assertTrue(self.dialog.remember_migration_login.isChecked())
            self.assertEqual({'username':'saved-user','password':'','remember':True},self.dialog.migration_login_input())
        self.dialog.migration_password.setText('temporary-secret')
        self.dialog.remember_migration_login.setChecked(False)
        self.dialog.render()
        self.assertEqual('temporary-secret',self.dialog.migration_password.text())
        self.assertFalse(self.dialog.remember_migration_login.isChecked())
        from unittest.mock import Mock
        operation=Mock()
        with patch.object(self.dialog,'operation',operation):
            self.dialog.forget_migration_login()
        operation.call_args.args[2]({'ok':True})
        self.assertEqual('',self.dialog.migration_username.text())
        self.assertEqual('',self.dialog.migration_password.text())
        self.assertFalse(self.dialog.remember_migration_login.isChecked())

    def test_separate_login_required_fields_block_before_refresh(self):
        self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.dialog.separate_migration_login.setChecked(True)
        with patch.object(self.dialog,'operation') as operation:
            with self.assertRaisesRegex(ValueError,'username and password'):
                self.dialog.migrate()
        operation.assert_not_called()

    def test_login_button_passes_credentials_privately_and_does_not_save_user_settings(self):
        self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.dialog.separate_migration_login.setChecked(True)
        self.dialog.migration_username.setText('migration-user')
        self.dialog.migration_password.setText('temporary-secret')
        self.dialog.remember_migration_login.setChecked(True)
        with patch.object(self.dialog,'operation') as operation:
            self.dialog.test_migration_login_button.click()
        title,args,callback=operation.call_args.args
        self.assertEqual('Test Migration Source Login',title)
        self.assertNotIn('temporary-secret',args)
        self.assertEqual({'username':'migration-user','password':'temporary-secret','remember':True},
                         operation.call_args.kwargs['private_input'])
        callback({'ok':True})
        self.assertIn('Login remembered',self.dialog.status.text())
        self.settings.save()
        self.assertNotIn('temporary-secret',self.settings.path.read_text())

    def test_failed_target_refresh_does_not_check_or_initiate_movement(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.configure(login_failure='pp')
        self.migrate()
        self.assertEqual(record.data['stage'],'migrate')
        self.assertIsNone(record.data['pending'])
        calls=[json.loads(line) for line in self.control.with_suffix('.calls.jsonl').read_text().splitlines()]
        self.assertFalse(any(call[0]=='migrate' for call in calls))
        self.assertIn('Refresh Migration Session pp',self.dialog.status.text())
        self.assertIn('No migration request was submitted',self.dialog.status.text())

    def test_unauthorized_batch_check_does_not_replay_or_mark_movement_uncertain(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.configure(batch_unauthorized=True)
        self.migrate()
        self.assertEqual(record.data['stage'],'migrate')
        self.assertIsNone(record.data['pending'])
        self.assertEqual(record.data['closed'],['10'])
        calls=[json.loads(line) for line in self.control.with_suffix('.calls.jsonl').read_text().splitlines()]
        moves=[call for call in calls if call[0]=='migrate']
        self.assertEqual(len(moves),1)
        self.assertIn('--dry-run',moves[0])
        self.assertIn('No migration request was submitted',self.dialog.status.text())
        self.assertNotIn('interrupted remote write',self.dialog.status.text())

    def test_unauthorized_movement_is_not_replayed_and_requires_outcome_check(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.configure(movement_unauthorized=True)
        self.migrate()
        self.assertEqual(record.data['pending'],'migration')
        calls=[json.loads(line) for line in self.control.with_suffix('.calls.jsonl').read_text().splitlines()]
        self.assertEqual(len([call for call in calls if call[0]=='migrate' and '--dry-run' not in call]),1)
        self.assertIn('Check Comms',self.dialog.status.text())

    def test_already_migrated_batch_points_to_manual_verification_and_does_not_initiate(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        self.configure(already_migrated=True)
        self.migrate()
        self.assertEqual(record.data['stage'],'migrate')
        self.assertIsNone(record.data['pending'])
        self.assertIn('I Verified Migration in Target',self.dialog.status.text())
        self.assertIn('earlier attempts',self.dialog.status.text())
        self.assertEqual(record.data['events'][-1]['kind'],'operation_failed')
        self.assertEqual(record.data['events'][-1]['category'],'not_eligible')
        self.assertFalse(record.data['events'][-1]['remote_write'])
        self.assertTrue(any(event['kind']=='migration_batch_check_started' and event['dry_run'] for event in record.data['events']))
        calls=[json.loads(line) for line in self.control.with_suffix('.calls.jsonl').read_text().splitlines()]
        self.assertFalse(any(call[0]=='migrate' and '--dry-run' not in call for call in calls))

    def test_manual_target_verification_resumes_to_comparison_without_remote_requests(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        preflight=copy.deepcopy(record.data['preflight'])
        for stage,pending in (('migrate',None),('migrate','migration'),('awaiting_completion',None)):
            with self.subTest(stage=stage,pending=pending):
                record.data.update(stage=stage,pending=pending)
                record.event('test_resume_setup')
                self.dialog.record=MigrationRecord.load(record.path)
                with patch.object(self.dialog,'confirmation_note',return_value='Verified BillsFix in PP; migration complete.'),patch.object(self.window.comms,'submit') as submit:
                    self.dialog.external_completion()
                submit.assert_not_called()
                saved=MigrationRecord.load(record.path)
                self.assertEqual(saved.data['stage'],'postflight')
                self.assertIsNone(saved.data['pending'])
                self.assertEqual(saved.data['preflight'],preflight)
                verification=saved.data['completion_verification']
                self.assertEqual(verification['method'],'manual_target_verification')
                self.assertEqual(verification['target'],'pp')
                self.assertEqual(verification['configs'][0]['id'],'10')
                self.assertEqual(verification['previous_pending'],pending)
                self.assertFalse(verification['initiation_receipt'])
                self.assertTrue(verification['verified_at'])
                self.assertEqual(saved.data['events'][-2]['kind'],'target_migration_verified')
                record=self.dialog.record
        with self.assertRaises(ValueError):
            self.dialog.complete()
        self.smoke(True)
        self.assertEqual(self.dialog.record.data['stage'],'review')

    def test_cancelled_or_empty_manual_verification_does_not_advance(self):
        record=self.start_record()
        self.smoke()
        self.skip_sync()
        self.close_configs()
        before=record.path.read_bytes()
        with patch.object(self.dialog,'confirmation_note',return_value=None),patch.object(self.window.comms,'submit') as submit:
            self.dialog.external_completion()
        submit.assert_not_called()
        self.assertEqual(record.path.read_bytes(),before)
        with patch.object(self.dialog,'confirmation_note',return_value='  '),self.assertRaises(ValueError):
            self.dialog.external_completion()
        self.assertEqual(record.path.read_bytes(),before)

    def test_target_verification_dialog_requires_every_config_and_note(self):
        dialog=TargetVerificationDialog(self.dialog,'Verify in target pp',[dict(id='10',shortName='A'),dict(id='20',shortName='B')])
        self.addCleanup(dialog.close)
        dialog.submit()
        self.assertEqual(dialog.result(),dialog.DialogCode.Rejected)
        dialog.note.setPlainText('Verified in target PP Config list and migration history.')
        dialog.configs.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.submit()
        self.assertEqual(dialog.result(),dialog.DialogCode.Rejected)
        dialog.configs.item(1).setCheckState(Qt.CheckState.Checked)
        dialog.note.clear()
        dialog.submit()
        self.assertEqual(dialog.result(),dialog.DialogCode.Rejected)
        dialog.note.setPlainText('Verified in PP.')
        dialog.submit()
        self.assertEqual(dialog.result(),dialog.DialogCode.Accepted)

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

    def test_configured_records_folder_contains_all_new_migration_evidence(self):
        custom=self.root/'shared migration records'
        self.settings.payload['smoke_tests']['migration_records_dir']=str(custom)
        self.dialog.render_setup()
        self.assertEqual(self.dialog.records_folder.text(),str(custom.resolve()))
        record=self.start_record()
        self.assertEqual(record.folder.parent,custom.resolve())
        self.assertTrue(record.path.is_file())
        self.assertTrue((record.folder/'suite.json').is_file())
        self.assertTrue((record.folder/'inputs'/'1.json').is_file())
        self.assertTrue((record.folder/'migration-report.md').is_file())
        self.smoke()
        self.assertTrue(Path(record.data['preflight']['runs'][0]['report']).is_relative_to(custom.resolve()))
        self.assertEqual(self.dialog.root,custom.resolve())

    def test_per_migration_folder_override_is_remembered_for_resume_without_changing_default(self):
        custom=self.root/'one off records'
        original_default=self.dialog.default_root
        with patch('atool_qt.guided_migration.QFileDialog.getExistingDirectory',return_value=str(custom)):
            self.dialog.browse_records_button.click()
        record=self.start_record()
        self.assertEqual(record.folder.parent,custom.resolve())
        self.assertEqual(self.settings.section('smoke_tests')['migration_records_dir'],'')
        self.dialog.reset()
        self.assertEqual(self.dialog.root,original_default)
        index=self.dialog.resume_combo.findData(str(record.path))
        self.assertGreaterEqual(index,0)
        self.dialog.resume_combo.setCurrentIndex(index)
        self.dialog.resume()
        self.assertEqual(self.dialog.record.path,record.path)
        self.smoke()
        self.assertTrue(Path(self.dialog.record.data['preflight']['runs'][0]['report']).is_relative_to(custom.resolve()))

    def test_default_change_keeps_old_record_available_and_does_not_relocate_it(self):
        record=self.start_record()
        original_folder=record.folder
        original_settings=copy.deepcopy(record.data['settings'])
        new_default=self.root/'new default'
        self.settings.payload['smoke_tests']['migration_records_dir']=str(new_default)
        self.dialog.reset()
        self.assertEqual(self.dialog.root,new_default.resolve())
        index=self.dialog.resume_combo.findData(str(record.path.resolve()))
        self.assertGreaterEqual(index,0)
        self.dialog.resume_combo.setCurrentIndex(index)
        self.dialog.resume()
        self.assertEqual(self.dialog.record.folder,original_folder)
        self.assertEqual(self.dialog.record.data['settings'],original_settings)
        self.assertFalse(new_default.exists())

    def test_open_saved_record_from_another_folder_and_cancel_browsing(self):
        custom=self.root/'elsewhere'
        self.dialog.records_folder.setText(str(custom))
        record=self.start_record()
        self.dialog.reset()
        self.window.settings.remove('migration/lastRecordsDir')
        self.dialog.refresh_saved_migrations()
        self.assertEqual(self.dialog.resume_combo.count(),0)
        with patch('atool_qt.guided_migration.QFileDialog.getOpenFileName',return_value=(str(record.path),'')):
            self.dialog.open_saved_record()
        self.assertEqual(self.dialog.record.path,record.path)
        self.dialog.reset()
        selected=self.dialog.records_folder.text()
        with patch('atool_qt.guided_migration.QFileDialog.getExistingDirectory',return_value=''):
            self.dialog.choose_records_folder()
        self.assertEqual(self.dialog.records_folder.text(),selected)

    def test_invalid_records_destination_does_not_create_a_migration(self):
        invalid=self.root/'file-not-folder'
        invalid.write_text('keep')
        self.dialog.records_folder.setText(str(invalid))
        with self.assertRaises(OSError):
            self.start_record()
        self.assertIsNone(self.dialog.record)
        self.assertEqual(invalid.read_text(),'keep')

    def test_operator_and_report_follow_new_actions_without_overwriting_creator(self):
        self.assertEqual(self.dialog.operator_name.text(),'Migration Tester')
        record=self.start_record()
        self.assertEqual(record.data['performed_by']['displayName'],'Migration Tester')
        self.assertEqual(record.data['created_by']['displayName'],'Migration Tester')
        self.assertTrue(record.data['events'][0]['actor']['user'])
        path=record.folder/'migration-report.md'
        self.assertTrue(path.is_file())
        self.assertIn('Migration Tester',path.read_text())
        with patch('atool_qt.guided_migration.QDesktopServices.openUrl') as opened:
            self.dialog.open_report()
        self.assertEqual(opened.call_args.args[0].toLocalFile(),str(path.resolve()))
        self.dialog.reset()
        self.dialog.operator_name.setText('Second Operator')
        self.dialog.resume()
        record=self.dialog.record
        self.assertEqual(record.data['created_by']['displayName'],'Migration Tester')
        self.assertEqual(record.data['performed_by']['displayName'],'Migration Tester')
        self.assertEqual(record.data['events'][-1]['kind'],'resumed')
        self.assertEqual(record.data['events'][-1]['actor']['displayName'],'Second Operator')
        self.assertIn('Second Operator',path.read_text())

    def test_legacy_operator_is_explicitly_recorded_without_backfilling_events(self):
        record=self.start_record()
        record.data.pop('performed_by')
        record.data.pop('created_by')
        for event in record.data['events']:
            event.pop('actor',None)
        record.save()
        self.dialog.render()
        before=record.path.read_bytes()
        with patch('PySide6.QtWidgets.QInputDialog.getText',return_value=('Original Migrator',False)):
            self.dialog.record_operator()
        self.assertEqual(before,record.path.read_bytes())
        with patch('PySide6.QtWidgets.QInputDialog.getText',return_value=('Original Migrator',True)):
            self.dialog.record_operator()
        self.assertEqual(record.data['performed_by']['displayName'],'Original Migrator')
        self.assertNotIn('created_by',record.data)
        self.assertNotIn('actor',record.data['events'][0])
        self.assertEqual(record.data['events'][-1]['actor']['displayName'],'Migration Tester')
        self.assertIn('Original Migrator',record.folder.joinpath('migration-report.md').read_text())

    def test_report_failure_does_not_lose_successfully_saved_progress(self):
        record=self.start_record()
        with patch('atool_qt.migration_record.write_migration_report',side_effect=OSError('Disk unavailable')):
            record.event('test_report_failure')
        self.assertIn('Disk unavailable',record.report_error)
        saved=MigrationRecord.load(record.path)
        self.assertEqual(saved.data['events'][-1]['kind'],'test_report_failure')
        self.assertTrue(record.write_report().is_file())

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
