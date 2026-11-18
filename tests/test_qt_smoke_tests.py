"""Smoke-test UI and CLI integration, using a local executable without remote requests."""
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from atool_qt.smoke_tests import smoke_plan
from atool_qt.user_settings import SettingsDialog, UserSettings


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.suite=self.root/'suite folder'/'suite.json'
        self.suite.parent.mkdir()
        (self.suite.parent/'input.json').write_text('{}')
        self.write_suite()
        self.window=WorkspaceWindow(QSettings(str(self.root/'qt.ini'),QSettings.Format.IniFormat))
        self.addCleanup(self.close)
        self.settings=UserSettings(self.root/'settings.json')
        self.settings.payload['application']['confirm_on_quit']=False
        self.settings.payload['occs'].update(cli_path=str(self.root/'fake-cli'),session_alias='unrelated-default')
        self.config=self.settings.payload['smoke_tests']
        self.config.update(suite_dir=str(self.suite.parent),output_dir=str(self.root/'output folder'),
                           request_timeout_seconds=73,run_timeout_minutes=5,
                           tools_path=str(self.root/'external tools'),browser_path=str(self.root/'Browser With Spaces'))
        self.settings.save()
        self.config=self.settings.payload['smoke_tests']
        self.window.comms.settings=self.settings
        cli=self.root/'fake-cli'
        cli.write_text(f'#!{sys.executable}\n'+'''import json, os, sys, time
from pathlib import Path
args=sys.argv[1:]
def option(name):return args[args.index(name)+1]
suite=json.loads(Path(option('--suite')).read_text())
package=suite['tests'][0]['package']
if package=='WAIT':time.sleep(20)
if package=='SETUPFAIL':
    print('Could not start previews',flush=True)
    sys.exit(2)
root=Path(option('--output')+'-2026-11-05_12-00-00-000')
root.mkdir(parents=True,exist_ok=True)
failed=package=='FAIL'
results=[{'status':'Fail' if failed else 'Pass'}]
if '--compare-tenancy' in args or '--compare-session' in args:
    results[0].update(comparison={'status':'Pass'},compare={'status':'Review' if package=='REVIEW' else 'Pass'})
(root/'smoke-results.json').write_text(json.dumps({'summary':{'passed':0 if failed else 1,'failed':1 if failed else 0},'results':results}))
(root/'smoke-report.html').write_text('<html>Smoke report</html>')
(root/'invocation.json').write_text(json.dumps({'args':args,'suite':suite,'path':os.environ['PATH'],'browser':os.environ.get('OCCS_SMOKE_BROWSER')}))
print('Output: '+str(root),flush=True)
print('Report: '+str(root/'smoke-report.html'),flush=True)
sys.exit(1 if failed else 0)
''')
        cli.chmod(0o755)

    def write_suite(self,package='Example'):
        self.suite.write_text(json.dumps({'name':'Smoke suite','session':'suite-session',
                                         'compareSession':'suite-compare','tenancy':'ignored',
                                         'tests':[{'package':package,'input':'input.json','output':'html'}]}))

    def close(self):
        if self.window.smoke_dialog and self.window.smoke_dialog.running:
            self.window.smoke_dialog.stop()
        self.window.comms.shutdown()
        self.app.processEvents()
        self.window.close()

    def until(self,condition):
        deadline=time.monotonic()+6
        while not condition() and time.monotonic()<deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(condition(),'Timed out waiting for the local fake CLI')

    def dialog(self):
        self.assertIn(self.window.smoke_action,self.window.package_menu.actions())
        self.window.smoke_action.trigger()
        self.assertIsNone(self.window.session)
        self.assertTrue(self.window.smoke_dialog.isVisible())
        return self.window.smoke_dialog

    def test_both_runs_preserve_suite_and_configure_environment_and_timeouts(self):
        before=self.suite.read_bytes()
        dialog=self.dialog()
        dialog.resume.setChecked(True)
        dialog.run_button.click()
        self.assertTrue(dialog.running)
        self.assertFalse(self.window.smoke_action.isEnabled())
        self.assertEqual(dialog.job.timeout_ms,300000)
        self.until(lambda:not dialog.running)
        self.assertEqual(dialog.failures,0)
        self.assertEqual(len(dialog.reports),2)
        self.assertTrue(dialog.report_button.isEnabled())
        self.assertTrue(self.window.smoke_action.isEnabled())
        self.assertEqual(self.suite.read_bytes(),before)
        self.assertIsNone(dialog.temporary)
        calls=[json.loads(path.parent.joinpath('invocation.json').read_text()) for path in dialog.reports]
        for call in calls:
            args=call['args']
            self.assertEqual(args[0],'smoke')
            self.assertNotIn('--json',args)
            self.assertNotIn('unrelated-default',args)
            self.assertIn('--resume',args)
            self.assertEqual(args[args.index('--timeout')+1],'73000')
            self.assertEqual(call['suite']['tests'][0]['input'],str((self.suite.parent/'input.json').resolve()))
            self.assertNotIn('session',call['suite'])
            self.assertNotIn('compareSession',call['suite'])
            self.assertEqual(call['browser'],self.config['browser_path'])
            self.assertTrue(call['path'].startswith(self.config['tools_path']+os.pathsep))
        self.assertIn('pre-prod',calls[0]['args'])
        self.assertNotIn('--compare-tenancy',calls[0]['args'])
        self.assertIn('non-prod',calls[1]['args'])
        self.assertIn('--compare-tenancy',calls[1]['args'])
        self.assertIn('0.01',calls[1]['args'])
        with patch('atool_qt.smoke_tests.QDesktopServices.openUrl',return_value=True) as opened:
            dialog.report_button.click()
        self.assertEqual(opened.call_count,2)

    def test_settings_tab_persists_and_validates_smoke_configuration(self):
        dialog=SettingsDialog(self.window)
        self.addCleanup(dialog.close)
        self.assertIn('Smoke Tests',[dialog.tabs.tabText(index) for index in range(dialog.tabs.count())])
        self.assertNotIn(('smoke_tests','suite_path'),dialog.controls)
        with patch('atool_qt.user_settings.QFileDialog.getExistingDirectory',return_value=str(self.suite.parent)) as browse:
            dialog.browse_controls[('smoke_tests','suite_dir')].click()
        browse.assert_called_once()
        dialog.controls[('smoke_tests','standard_session')].setText('pp')
        dialog.controls[('smoke_tests','comparison_threshold_percent')].setValue(2.5)
        dialog.controls[('smoke_tests','concurrency')].setValue(1)
        dialog.save()
        saved=UserSettings(self.settings.path).section('smoke_tests')
        self.assertEqual(saved['suite_dir'],str(self.suite.parent))
        self.assertEqual(saved['standard_session'],'pp')
        self.assertEqual(saved['comparison_threshold_percent'],2.5)
        self.assertEqual(saved['concurrency'],1)
        for key,value in (('request_timeout_seconds',0),('concurrency',3),('run_timeout_minutes',False),
                          ('comparison_threshold_percent',101),('comparison_threshold_percent',float('nan'))):
            payload=copy.deepcopy(self.settings.payload)
            payload['smoke_tests'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                self.settings.validate(payload)

    def test_legacy_file_setting_migrates_to_folder(self):
        payload=copy.deepcopy(self.settings.payload)
        payload['smoke_tests'].pop('suite_dir')
        payload['smoke_tests']['suite_path']=str(self.suite)
        path=self.root/'legacy-settings.json'
        path.write_text(json.dumps(payload))
        settings=UserSettings(path)
        self.assertEqual(settings.section('smoke_tests')['suite_dir'],str(self.suite.parent))
        self.assertNotIn('suite_path',settings.section('smoke_tests'))
        settings.save()
        self.assertEqual(UserSettings(path).section('smoke_tests')['suite_dir'],str(self.suite.parent))

    def test_named_suite_selection_ignores_data_and_invalid_json(self):
        other=self.suite.parent/'not-the-suite-name.JSON'
        suite=json.loads(self.suite.read_text())
        suite['name']='Another suite'
        suite['tests'][0]['package']='Selected package'
        other.write_text(json.dumps(suite),encoding='utf-8-sig')
        (self.suite.parent/'broken.json').write_text('not json')
        (self.suite.parent/'unnamed.json').write_text(json.dumps({'tests':suite['tests']}))
        dialog=self.dialog()
        self.assertEqual([dialog.suite_combo.itemText(i) for i in range(dialog.suite_combo.count())],
                         ['Another suite','Smoke suite'])
        self.assertIn('Skipped 3 JSON',dialog.suite_status.text())
        dialog.suite_combo.setCurrentIndex(0)
        dialog.refresh_button.click()
        self.assertEqual(dialog.suite_combo.currentData(),str(other.resolve()))
        dialog.start()
        self.assertFalse(dialog.suite_combo.isEnabled())
        self.assertFalse(dialog.refresh_button.isEnabled())
        self.until(lambda:not dialog.running)
        self.assertTrue(dialog.suite_combo.isEnabled())
        for report in dialog.reports:
            invocation=json.loads(report.with_name('invocation.json').read_text())
            self.assertEqual(invocation['suite']['name'],'Another suite')
            self.assertEqual(invocation['suite']['tests'][0]['package'],'Selected package')
            self.assertEqual(invocation['suite']['tests'][0]['input'],str((self.suite.parent/'input.json').resolve()))

    def test_empty_missing_and_changed_suite_folders(self):
        empty=self.root/'empty'
        empty.mkdir()
        self.config['suite_dir']=str(empty)
        dialog=self.dialog()
        self.assertFalse(dialog.run_button.isEnabled())
        self.assertIn('No named smoke suites',dialog.suite_status.text())
        self.config['suite_dir']=str(self.root/'missing')
        dialog.refresh_configuration()
        self.assertIn('Could not read smoke suite folder',dialog.suite_status.text())
        self.config['suite_dir']=str(self.suite.parent)
        dialog.refresh_configuration()
        self.assertTrue(dialog.run_button.isEnabled())
        self.assertEqual(dialog.suite_combo.currentText(),'Smoke suite')
        self.suite.unlink()
        dialog.refresh_button.click()
        self.assertFalse(dialog.run_button.isEnabled())
        with patch.object(self.window.comms,'submit') as submit:
            dialog.start()
        submit.assert_not_called()
        self.assertIn('Select a smoke suite',dialog.status.text())

    def test_session_overrides_and_separate_modes(self):
        self.config.update(standard_session='pp',comparison_source_session='np',comparison_target_session='pp')
        plan=smoke_plan(self.config,True,False,suite_path=self.suite)
        self.assertEqual(len(plan['runs']),1)
        self.assertEqual(plan['runs'][0]['args'][:2],['--session','pp'])
        plan=smoke_plan(self.config,False,True,suite_path=self.suite)
        self.assertEqual(len(plan['runs']),1)
        self.assertEqual(plan['runs'][0]['args'][:4],['--session','np','--compare-session','pp'])

    def test_invalid_suite_and_missing_inputs_never_start_a_process(self):
        dialog=self.dialog()
        for contents in ('{}','not json',json.dumps({'tests':[{'package':'Example','input':'absent.json'}]})):
            self.suite.write_text(contents)
            with patch.object(self.window.comms,'submit') as submit:
                dialog.start()
            self.assertFalse(dialog.running)
            submit.assert_not_called()
        self.config['suite_dir']=''
        dialog.start()
        self.assertIn('Suite JSON Folder',dialog.status.text())

    def test_preview_failures_keep_reports_and_continue_comparison(self):
        self.write_suite('FAIL')
        dialog=self.dialog()
        dialog.start()
        self.until(lambda:not dialog.running)
        self.assertEqual(len(dialog.reports),2)
        self.assertEqual(dialog.failures,2)
        self.assertIn('need attention',dialog.status.text())

    def test_visual_review_is_visible_even_when_cli_exits_successfully(self):
        self.write_suite('REVIEW')
        dialog=self.dialog()
        dialog.standard.setChecked(False)
        dialog.start()
        self.until(lambda:not dialog.running)
        self.assertEqual(dialog.failures,1)
        self.assertIn('1 comparisons need attention',dialog.output.toPlainText())
        self.assertEqual(len(dialog.reports),1)

    def test_setup_failure_stops_remaining_runs(self):
        self.write_suite('SETUPFAIL')
        dialog=self.dialog()
        dialog.start()
        self.until(lambda:not dialog.running)
        self.assertTrue(dialog.stopping)
        self.assertEqual(dialog.reports,[])
        self.assertEqual(dialog.failures,1)

    def test_cancel_kills_process_and_does_not_start_comparison(self):
        self.write_suite('WAIT')
        dialog=self.dialog()
        dialog.start()
        job=dialog.job
        self.until(lambda:job.process.processId()!=0)
        dialog.cancel_button.click()
        self.until(lambda:not dialog.running)
        self.assertTrue(job.cancelled)
        self.assertTrue(job.done)
        self.assertEqual(dialog.queue,[])
        self.assertIsNone(dialog.temporary)
        self.assertTrue(self.window.smoke_action.isEnabled())

    def test_timeout_stops_remaining_runs_and_releases_ui(self):
        self.write_suite('WAIT')
        dialog=self.dialog()
        dialog.start()
        job=dialog.job
        self.until(lambda:job.process.processId()!=0)
        job.timer.start(30)
        self.until(lambda:not dialog.running)
        self.assertTrue(job.timed_out)
        self.assertTrue(dialog.stopping)
        self.assertIsNone(dialog.temporary)
        self.assertFalse(self.window.package_busy())
