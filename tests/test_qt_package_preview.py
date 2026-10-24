"""Preview command contracts and temporary input lifecycle without remote rendering."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from atool_qt.occs import CommandResult
from atool_qt.package_preview import PreviewDialog, exclude_charts, preview_outputs
from atool_qt.shared_packages import encode
from atool_qt.user_settings import UserSettings


class FakeJob(QObject):
    completed = Signal(object)
    def __init__(self):
        super().__init__()
        self.done = False
        self.cancelled = False
    def cancel(self):
        self.cancelled = True


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.window = WorkspaceWindow(QSettings(str(self.root/'qt.ini'), QSettings.Format.IniFormat))
        settings = UserSettings(self.root/'settings.json')
        settings.payload['application']['confirm_on_quit'] = False
        settings.payload['occs']['pre_prod_session_alias'] = 'pre'
        self.window.comms.settings = settings
        bundle = self.root/'bundle'
        bundle.mkdir()
        for name, value in {'occs-package.json':dict(schemaVersion='occs-package-bundle/v1', package={'shortName':'Bill'}, version={'shortName':'2'}, files={}),
                            'assembly-template.json':{'Documents':[], 'Fields':[]}, 'version-master.json':{}}.items():
            (bundle/name).write_bytes(encode(value))
        self.window.open_package(bundle/'occs-package.json')
        self.source = self.root/'data.json'
        self.payload = {'charts':[1], 'nested':[{'charts':[2], 'value':3}], 'Charts':[4]}
        self.source.write_bytes(encode(self.payload))
        self.calls = []
        self.runner = patch.object(self.window,'run_comms_operation', side_effect=self.command)
        self.runner.start()
        self.addCleanup(self.runner.stop)
        self.addCleanup(self.close)

    def close(self):
        for index, call in enumerate(self.calls):
            if not call['job'].done:
                self.complete(CommandResult(-1,'','',None,cancelled=True), index)
        self.window.close()

    def command(self, title, args, callback=None, **kwargs):
        job = FakeJob()
        self.calls.append(dict(title=title,args=args,callback=callback,options=kwargs,job=job))
        return job

    def complete(self,result,index=-1):
        call=self.calls[index]
        call['job'].done=True
        if result.successful:
            with patch.object(QMessageBox,'information'):
                call['callback'](result)
        call['job'].completed.emit(result)

    def start(self, renders=None, **kwargs):
        return self.window.start_package_preview(str(self.source),renders or ['PDF'],400,'2026-10-08',open_after=False,**kwargs)

    def language_data(self, value='ENGLISH'):
        self.payload['billPrint'] = {'billDetails': {'cmElements': {'billLanguagePreference': value}}}
        self.source.write_bytes(encode(self.payload))

    def test_language_dialog_matches_input_and_refreshes_when_file_changes(self):
        self.language_data()
        dialog = PreviewDialog(self.window)
        self.addCleanup(dialog.close)
        dialog.input.setText(str(self.source))
        self.assertEqual(dialog.languages['ENGLISH'].text(), 'English *')
        self.assertTrue(dialog.languages['ENGLISH'].isChecked())
        self.assertFalse(dialog.languages['CHINESE'].isChecked())
        dialog.languages['CHINESE'].setChecked(True)
        dialog.open_after.setChecked(False)
        dialog.submit()
        self.assertEqual(len(self.calls), 2)
        self.assertIn('-EN-', self.calls[0]['args'][self.calls[0]['args'].index('--output') + 1])
        self.assertIn('-ZF-', self.calls[1]['args'][self.calls[1]['args'].index('--output') + 1])
        alternate = self.root / 'chinese.json'
        self.language_data('CHINESE')
        alternate.write_bytes(self.source.read_bytes())
        dialog.input.setText(str(alternate))
        self.assertFalse(dialog.languages['ENGLISH'].isChecked())
        self.assertEqual(dialog.languages['ENGLISH'].text(), 'English')
        self.assertEqual(dialog.languages['CHINESE'].text(), 'Chinese *')
        self.assertTrue(dialog.languages['CHINESE'].isChecked())
        dialog.languages['CHINESE'].setChecked(False)
        with patch.object(self.window, 'report_error') as error:
            dialog.submit()
        error.assert_called_once()
        self.assertEqual(len(self.calls), 2)

    def test_languages_cross_render_types_preserve_original_and_clean_after_all_jobs(self):
        self.language_data()
        original = self.source.read_bytes()
        self.assertTrue(self.start(renders=['PDF', 'HTML', 'METADATA'], languages=['ENGLISH', 'CHINESE'], exclude=True))
        self.assertEqual(len(self.calls), 6)
        paths = []
        for index, call in enumerate(self.calls):
            args = call['args']
            path = Path(args[args.index('--input') + 1])
            paths.append(path)
            payload = json.loads(path.read_text())
            expected = 'ENGLISH' if index < 3 else 'CHINESE'
            short = 'EN' if index < 3 else 'ZF'
            self.assertEqual(payload['billPrint']['billDetails']['cmElements']['billLanguagePreference'], expected)
            self.assertNotIn('charts', payload)
            self.assertNotIn('charts', payload['nested'][0])
            output = Path(args[args.index('--output') + 1])
            self.assertIn(f'-{short}-', output.name)
            for unwanted in ('English', 'Chinese', 'ENGLISH', 'CHINESE'):
                self.assertNotIn(unwanted, output.name)
        self.assertEqual(len(set(paths)), 2)
        self.assertEqual(self.source.read_bytes(), original)
        for index in range(5):
            self.complete(CommandResult(1, '', 'render failed', None), index)
            self.assertTrue(all(path.exists() for path in paths))
        self.window.cancel_package_preview()
        self.assertTrue(self.calls[5]['job'].cancelled)
        self.complete(CommandResult(-1, '', '', None, cancelled=True), 5)
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual(self.source.read_bytes(), original)

    def test_default_language_uses_original_and_alternate_uses_copy(self):
        self.language_data()
        self.assertTrue(self.start(languages=['ENGLISH', 'CHINESE']))
        inputs = [Path(call['args'][call['args'].index('--input') + 1]) for call in self.calls]
        self.assertEqual(inputs[0], self.source)
        self.assertNotEqual(inputs[1], self.source)
        self.assertEqual(json.loads(inputs[1].read_text())['billPrint']['billDetails']['cmElements']['billLanguagePreference'], 'CHINESE')
        self.complete(CommandResult(0, '', '', None), 1)
        self.assertTrue(inputs[1].exists())
        self.complete(CommandResult(0, '', '', None), 0)
        self.assertFalse(inputs[1].exists())
        self.assertTrue(self.source.exists())

    def test_unknown_language_and_missing_mapping_are_explicit(self):
        self.language_data('OTHER')
        dialog = PreviewDialog(self.window)
        self.addCleanup(dialog.close)
        dialog.input.setText(str(self.source))
        self.assertFalse(any(check.isChecked() for check in dialog.languages.values()))
        self.assertIn('OTHER', dialog.language_status.text())
        self.assertTrue(self.start(languages=['CHINESE']))
        self.window.comms.settings.payload['language']['mapping'] = '$.missing'
        with patch.object(self.window, 'report_error') as error:
            self.assertFalse(self.start(languages=['CHINESE']))
            self.assertFalse(self.start(languages=['UNKNOWN']))
            self.assertFalse(self.start(languages=[]))
        self.assertEqual(error.call_count, 3)
        self.assertEqual(len(self.calls), 1)

    def test_custom_mapping_value_and_short_name(self):
        self.window.comms.settings.payload['language'] = {
            'mapping': '$.bills[0]["print language"]',
            'display_mapping': [{'label': 'Chinese', 'data': 'ZF', 'short_name': 'zh_HK'}]}
        self.source.write_bytes(encode({'bills': [{'print language': 'ENGLISH', 'other': 42}]}))
        self.assertTrue(self.start(languages=['ZF']))
        args = self.calls[0]['args']
        self.assertIn('-zh_HK-', args[args.index('--output') + 1])
        self.assertEqual(json.loads(Path(args[args.index('--input') + 1]).read_text()),
                         {'bills': [{'print language': 'ZF', 'other': 42}]})

    def test_partial_language_batch_start_failure_keeps_inputs_until_cancelled(self):
        self.language_data()
        def launch(title, args, callback=None, **kwargs):
            if self.calls:
                raise OSError('Could not start render')
            return self.command(title, args, callback, **kwargs)
        with patch.object(self.window, 'run_comms_operation', side_effect=launch), \
                patch.object(self.window, 'report_error') as error:
            self.assertFalse(self.start(renders=['PDF', 'HTML'], languages=['CHINESE']))
        error.assert_called_once()
        self.assertTrue(self.calls[0]['job'].cancelled)
        args = self.calls[0]['args']
        path = Path(args[args.index('--input') + 1])
        self.assertTrue(path.exists())
        self.complete(CommandResult(-1, '', '', None, cancelled=True), 0)
        self.assertFalse(path.exists())

    def test_data_save_as_switches_source_and_preview_input(self):
        session = self.window.session
        session.map_data(self.payload, self.source.name)
        self.window.settings.setValue('lastDataFile', str(self.source))
        self.window.set_session(session)
        edited = {'changed': True, 'amount': 42}
        self.window.data.replace_value(edited)
        revision = session.mapping_revision
        saved = (self.root / 'saved' / 'edited.json').resolve()
        saved.parent.mkdir()
        with patch('atool_qt.data_editing.QFileDialog.getSaveFileName', return_value=(str(saved), '')):
            self.window.data.save_json()
        self.assertEqual(json.loads(saved.read_text()), edited)
        self.assertEqual(json.loads(self.source.read_text()), self.payload)
        self.assertEqual(session.data_name, saved.name)
        self.assertEqual(self.window.data_label.text(), 'Data: edited.json')
        self.assertEqual(self.window.data_label.toolTip(), str(saved))
        self.assertEqual(self.window.settings.value('lastDataFile'), str(saved))
        self.assertEqual(self.window.settings.value('lastMappingDirectory'), str(saved.parent))
        self.assertEqual(self.window.mapped_data_path(), saved)
        self.assertEqual(session.mapping_revision, revision)
        dialog = PreviewDialog(self.window)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.input.text(), str(saved))
        dialog.open_after.setChecked(False)
        dialog.submit()
        args = self.calls[-1]['args']
        self.assertEqual(args[args.index('--input') + 1], str(saved))
        self.window.data.undo_data()
        self.assertEqual(session.data, self.payload)
        self.assertEqual(session.data_name, saved.name)
        self.assertEqual(self.window.mapped_data_path(), saved)

    def test_save_current_updates_the_file_used_by_preview(self):
        session = self.window.session
        session.map_data(self.payload, self.source.name)
        self.window.settings.setValue('lastDataFile', str(self.source))
        self.window.set_session(session)
        edited = {'language': 'CHINESE'}
        self.window.data.replace_value(edited)
        revision = session.mapping_revision
        with patch('atool_qt.data_editing.QFileDialog.getSaveFileName') as picker:
            self.window.data.edit_actions['Save'].trigger()
            picker.assert_not_called()
        self.assertEqual(json.loads(self.source.read_text()), edited)
        self.assertEqual(session.mapping_revision, revision)
        dialog = PreviewDialog(self.window)
        self.addCleanup(dialog.close)
        self.assertEqual(Path(dialog.input.text()).resolve(), self.source.resolve())
        self.assertIn('Saved mapped data:', self.window.activity.toPlainText())
        self.assertEqual(self.window.activity.toPlainText().count('Saved mapped data:'), 1)

    def test_cancelled_or_failed_save_keeps_original_source(self):
        session = self.window.session
        session.map_data(self.payload, self.source.name)
        self.window.settings.setValue('lastDataFile', str(self.source))
        self.window.set_session(session)
        for filename in ('', str(self.root / 'missing' / 'edited.json')):
            with patch('atool_qt.data_editing.QFileDialog.getSaveFileName', return_value=(filename, '')):
                self.window.data.save_json()
            self.assertEqual(session.data_name, self.source.name)
            self.assertEqual(self.window.settings.value('lastDataFile'), str(self.source))
            self.assertEqual(self.window.mapped_data_path(), self.source)
        self.assertIn('Data Manager: Could not save JSON:', self.window.activity.toPlainText())

    def test_preview_contract_alias_timeout_preferences_and_menu_states(self):
        self.assertTrue(self.start(renders=['PDF','HTML'], pre=True))
        self.assertEqual(len(self.calls), 2)
        args=self.calls[-1]['args']
        self.assertEqual(args[:5],['preview','--session','pre','--package','Bill'])
        self.assertEqual(args[args.index('--timeout')+1],'400000')
        self.assertEqual(self.calls[-1]['options']['channel'],'regular')
        self.assertTrue(self.calls[-1]['options']['close_on_success'])
        self.assertEqual(self.calls[-1]['options']['timeout_ms'],430000)
        self.assertEqual([call['args'][-2:] for call in self.calls],
                         [['--render-type','PDF'], ['--render-type','HTML']])
        self.assertEqual([call['title'] for call in self.calls],
                         ['Preview Package (PDF)', 'Preview Package (HTML)'])
        self.assertTrue(self.window.preview_action.isEnabled())
        self.assertTrue(self.window.cancel_preview_action.isEnabled())
        self.assertEqual(self.window.comms.settings.get('last_preview_render_types'),['PDF','HTML'])
        self.window.cancel_package_preview()
        self.assertTrue(all(call['job'].cancelled for call in self.calls))
        self.complete(CommandResult(-1,'','',None,cancelled=True))
        self.assertTrue(self.window.cancel_preview_action.isEnabled())
        self.complete(CommandResult(-1,'','',None,cancelled=True), 0)
        self.assertTrue(self.window.preview_action.isEnabled())
        self.assertFalse(self.window.cancel_preview_action.isEnabled())

    def test_render_jobs_finish_independently_and_keep_shared_input_until_all_done(self):
        self.assertTrue(self.window.start_package_preview(str(self.source), ['PDF','HTML','TEXT'],
            400, '2026-10-08', pre=True, exclude=True, open_after=True))
        self.assertEqual(len(self.calls), 3)
        inputs = [Path(call['args'][call['args'].index('--input')+1]) for call in self.calls]
        outputs = [call['args'][call['args'].index('--output')+1] for call in self.calls]
        self.assertEqual(len(set(inputs)), 1)
        self.assertEqual(len(set(outputs)), 3)
        path = inputs[0]
        with patch.object(self.window, 'open_output_file') as opener:
            self.complete(CommandResult(0, 'Preview written [HTML] to /tmp/fast.html', '', None), 1)
            opener.assert_called_once_with('HTML', '/tmp/fast.html')
            self.assertTrue(path.exists())
            self.assertEqual(len(self.window.preview_jobs), 2)
            self.complete(CommandResult(1, '', 'PDF render failed', None), 0)
            self.assertTrue(path.exists())
            self.window.cancel_package_preview()
            self.assertTrue(self.calls[2]['job'].cancelled)
            self.complete(CommandResult(-1, '', '', None, cancelled=True), 2)
            self.assertFalse(path.exists())
            self.assertEqual(self.window.preview_jobs, [])
            self.assertEqual(json.loads(self.source.read_text()), self.payload)

    def test_overlapping_previews_own_outputs_inputs_and_cancellation(self):
        for _ in range(3):
            self.assertTrue(self.start(exclude=True))
        jobs = [call['job'] for call in self.calls]
        outputs = [call['args'][call['args'].index('--output')+1] for call in self.calls]
        inputs = [Path(call['args'][call['args'].index('--input')+1]) for call in self.calls]
        self.assertEqual(len(set(outputs)), 3)
        self.assertEqual(len(set(inputs)), 3)
        self.complete(CommandResult(0,'','',None), 1)
        self.assertFalse(inputs[1].exists())
        self.assertTrue(inputs[0].exists())
        self.assertTrue(inputs[2].exists())
        self.assertEqual(self.window.preview_jobs, [jobs[0], jobs[2]])
        self.assertTrue(self.window.cancel_preview_action.isEnabled())
        self.window.cancel_package_preview()
        self.assertTrue(jobs[0].cancelled)
        self.assertFalse(jobs[1].cancelled)
        self.assertTrue(jobs[2].cancelled)
        for index in (2, 0):
            self.complete(CommandResult(-1,'','',None,cancelled=True), index)
        self.assertFalse(any(path.exists() for path in inputs))
        self.assertEqual(self.window.preview_jobs, [])
        self.assertFalse(self.window.cancel_preview_action.isEnabled())

    def test_previews_share_four_slots_with_regular_operations_and_queue_excess(self):
        executable = self.root/'slow-preview'
        executable.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n')
        executable.chmod(0o755)
        self.window.comms.settings.payload['occs']['cli_path'] = str(executable)
        self.runner.stop()
        regular = self.window.comms.submit(['package', 'list'])
        self.assertTrue(self.start(renders=['PDF','HTML','TEXT','CSV','JSON','METADATA'], exclude=True))
        jobs = list(self.window.preview_jobs)
        outputs = [Path(job.args[job.args.index('--output')+1]) for job in jobs]
        self.assertEqual(len({path.stem for path in outputs}), 6)
        self.assertEqual([path.suffix for path in outputs], ['.pdf','.html','.txt','.csv','.json','.json'])
        for path in outputs[:5]:
            self.assertRegex(path.name, r'-[0-9a-f]{8}\.(pdf|html|txt|csv|json)$')
        self.assertRegex(outputs[5].name, r'-[0-9a-f]{8}-metadata\.json$')
        deadline = time.monotonic()+5
        while len(self.window.comms.active) < 4 and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertEqual(self.window.comms.active, [regular, *jobs[:3]])
        self.assertEqual(self.window.comms.pending, jobs[3:])
        jobs[1].cancel()
        deadline = time.monotonic()+5
        while jobs[3] not in self.window.comms.active and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(jobs[1].cancelled)
        self.assertIn(jobs[3], self.window.comms.active)
        self.assertEqual(len(self.window.comms.active), 4)
        self.assertFalse(jobs[0].done)
        self.window.cancel_package_preview()
        deadline = time.monotonic()+5
        while self.window.preview_jobs and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertEqual(self.window.preview_jobs, [])
        self.assertFalse(regular.done)
        regular.cancel()

    def test_chart_removal_preserves_input_and_cleans_on_every_result(self):
        for result in [CommandResult(0,'','',None),CommandResult(1,'','failed',None),CommandResult(-1,'','',None,cancelled=True)]:
            original=self.source.read_bytes()
            self.assertTrue(self.start(exclude=True))
            args=self.calls[-1]['args']
            path=Path(args[args.index('--input')+1])
            self.assertEqual(json.loads(path.read_text()),{'nested':[{'value':3}], 'Charts':[4]})
            self.assertEqual(self.source.read_bytes(),original)
            self.complete(result)
            self.assertFalse(path.exists())
            self.assertEqual(self.source.read_bytes(),original)

    def test_validation_and_unpublished_confirmation_prevent_render(self):
        with patch.object(self.window,'report_error') as error:
            self.assertFalse(self.window.start_package_preview('', ['PDF'],20,'2026-10-08'))
            self.assertFalse(self.window.start_package_preview(str(self.source), [],20,'2026-10-08'))
            self.assertFalse(self.window.start_package_preview(str(self.source), ['PDF'],20,'bad'))
            self.window.comms.settings.payload['occs']['pre_prod_session_alias']=''
            self.assertFalse(self.start(pre=True))
            self.assertEqual(error.call_count,4)
        with patch.object(self.window,'preview_unpublished_reasons',return_value=['Unsaved changes']),patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.start())
        self.assertEqual(self.calls,[])

    def test_debug_preview_captures_response_context_on_every_result(self):
        self.window.comms.settings.payload['diagnostics']['debug_logging'] = True
        response = self.root/'preview.response.json'
        response.write_text(json.dumps({'executionId':'exec-123', 'duration':42,
            'CommunicationAssemblyInfo':{'AssemblyRenderOutput':'encoded-document', 'status':'done'}}))
        stdout = f'\x1b[90m→ Response JSON[PDF]: {response}\x1b[0m\n'
        for result in [CommandResult(0,stdout,'server context',None),
                       CommandResult(1,stdout,'server context',None),
                       CommandResult(-1,stdout,'server context',None,cancelled=True),
                       CommandResult(-1,stdout,'server context',None,timed_out=True)]:
            self.window.activity.clear()
            self.assertTrue(self.start(pre=True, exclude=True))
            self.assertIn('--verbose', self.calls[-1]['args'])
            self.complete(result)
            activity = self.window.activity.toPlainText()
            for text in ['exec-123', '"duration": 42', '"status": "done"', 'server context',
                         '"session": "pre"', '"exclude_charts": true', f'exit_code={result.code}']:
                self.assertIn(text, activity)
            self.assertNotIn('encoded-document', activity)

    def test_preview_diagnostics_are_disabled_by_default(self):
        self.window.activity.clear()
        self.assertTrue(self.start())
        self.assertNotIn('--verbose', self.calls[-1]['args'])
        self.complete(CommandResult(0,'Preview written [PDF] to /tmp/a.pdf','debug-only stderr',None))
        activity = self.window.activity.toPlainText()
        self.assertIn('Preview complete.', activity)
        self.assertNotIn('Preview debug', activity)
        self.assertNotIn('debug-only stderr', activity)

    def test_debug_preview_reads_error_response_and_handles_missing_sidecar(self):
        self.window.comms.settings.payload['diagnostics']['debug_logging'] = True
        response = self.root/'preview.response.error.500.json'
        response.write_text(json.dumps({'executionId':'failed-123', 'error':{'message':'Render failed'}}))
        self.assertTrue(self.start())
        self.complete(CommandResult(1,'',f'Saved detailed preview error response to {response}',None))
        self.assertIn('failed-123', self.window.activity.toPlainText())
        response.unlink()
        self.assertTrue(self.start(exclude=True))
        path = Path(self.calls[-1]['args'][self.calls[-1]['args'].index('--input')+1])
        self.complete(CommandResult(1,'',f'Saved detailed preview error response to {response}',None))
        self.assertIn('Could not read preview response context', self.window.activity.toPlainText())
        self.assertFalse(path.exists())

    def test_parses_output_and_uses_configured_opener(self):
        stdout='\x1b[32mPreview written [HTML] [main] to /tmp/a b.html\x1b[0m\nPreview written [PDF] to /tmp/a.pdf\nPreview written [PDF] to /tmp/a.pdf'
        self.assertEqual(preview_outputs(stdout),[{'renderType':'HTML','path':'/tmp/a b.html'},{'renderType':'PDF','path':'/tmp/a.pdf'}])
        self.assertTrue(self.window.start_package_preview(str(self.source),['HTML'],20,'2026-10-08',open_after=True))
        with patch.object(self.window,'open_output_file') as opener:
            self.complete(CommandResult(0,stdout,'',None))
            self.assertEqual(opener.call_count,2)
            opener.assert_any_call('HTML','/tmp/a b.html')

    def test_dialog_defaults_readonly_mapped_file_and_calendar(self):
        self.window.session.map_data(self.payload,str(self.source))
        dialog=PreviewDialog(self.window)
        self.assertTrue(dialog.input.isReadOnly())
        self.assertEqual(dialog.input.text(),str(self.source))
        self.assertTrue(dialog.renders['PDF'].isChecked())
        self.assertTrue(dialog.open_after.isChecked())
        self.assertTrue(dialog.effective.calendarPopup())
        dialog.reject()
        self.assertEqual(exclude_charts(self.payload),{'nested':[{'value':3}], 'Charts':[4]})
        self.assertIn('charts',self.payload)

    def test_dialog_defaults_to_loaded_file_when_mapping_stores_only_filename(self):
        self.window.session.map_data(self.payload,self.source.name)
        self.window.settings.setValue('lastDataFile',str(self.source))
        dialog=PreviewDialog(self.window)
        self.assertEqual(dialog.input.text(),str(self.source))
        dialog.reject()
        self.window.settings.setValue('lastDataFile',str(self.root/'other.json'))
        self.assertIsNone(self.window.mapped_data_path())

    def test_successful_preview_closes_progress_without_another_success_window(self):
        executable=self.root/'fake-preview'
        executable.write_text('#!/usr/bin/env python3\nprint("Preview written [HTML] to /tmp/preview.html")\n')
        executable.chmod(0o755)
        self.window.comms.settings.payload['occs']['cli_path']=str(executable)
        self.runner.stop()
        with patch.object(QMessageBox,'information') as information:
            self.assertTrue(self.start())
            dialog=self.window.operation_dialog
            deadline=time.monotonic()+5
            while not dialog.job.done and time.monotonic()<deadline:
                self.app.processEvents()
                QTest.qWait(10)
            self.assertTrue(dialog.job.done)
            self.assertTrue(dialog.auto_closed)
            self.assertFalse(dialog.isVisible())
            information.assert_not_called()
