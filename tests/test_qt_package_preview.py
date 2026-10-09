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
        if self.window.preview_job and not self.window.preview_job.done:
            self.complete(CommandResult(-1,'','',None,cancelled=True))
        self.window.close()

    def command(self, title, args, callback=None, **kwargs):
        job = FakeJob()
        self.calls.append(dict(args=args,callback=callback,options=kwargs,job=job))
        return job

    def complete(self,result):
        call=self.calls[-1]
        call['job'].done=True
        if result.successful:
            with patch.object(QMessageBox,'information'):
                call['callback'](result)
        call['job'].completed.emit(result)

    def start(self, **kwargs):
        return self.window.start_package_preview(str(self.source),['PDF','HTML'],400,'2026-10-08',open_after=False,**kwargs)

    def test_preview_contract_alias_timeout_preferences_and_menu_states(self):
        self.assertTrue(self.start(pre=True))
        args=self.calls[-1]['args']
        self.assertEqual(args[:5],['preview','--session','pre','--package','Bill'])
        self.assertEqual(args[args.index('--timeout')+1],'400000')
        self.assertEqual(self.calls[-1]['options']['channel'],'preview')
        self.assertTrue(self.calls[-1]['options']['close_on_success'])
        self.assertEqual(self.calls[-1]['options']['timeout_ms'],430000)
        self.assertEqual(args[-3:],['--render-type','PDF','HTML'])
        self.assertFalse(self.window.preview_action.isEnabled())
        self.assertTrue(self.window.cancel_preview_action.isEnabled())
        self.assertEqual(self.window.comms.settings.get('last_preview_render_types'),['PDF','HTML'])
        self.assertFalse(self.start())
        self.window.cancel_package_preview()
        self.assertTrue(self.calls[-1]['job'].cancelled)
        self.complete(CommandResult(-1,'','',None,cancelled=True))
        self.assertTrue(self.window.preview_action.isEnabled())
        self.assertFalse(self.window.cancel_preview_action.isEnabled())

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
