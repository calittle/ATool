"""Original package/version retrieval contracts, probe errors, and shared handoff."""
import tempfile
import io
import logging
from contextlib import redirect_stderr
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from atool_qt.occs import CommandResult
from atool_qt.package_responses import PackageResponses
from atool_qt.session import demo_session
from atool_qt.shared_packages import encode, json_object
from atool_qt.user_settings import UserSettings


class FakeJob(QObject):
    completed=Signal(object)
    def __init__(self):
        super().__init__()
        self.done=False


class ResponseTests(unittest.TestCase):
    def test_original_aliases_nested_version_shapes_and_numeric_sort(self):
        versions=PackageResponses._normalize_occs_package_versions({'packages':[{'shortName':'Bill','CommunicationPackageMasterVersions':[
            {'CommunicationPackageVersionConfigRec':{'CommunicationPackageVersionConfigInfo':{'ShortName':'2.10','Desc':'nested'},'CommunicationPackageVersionConfigUuid':'uuid','ConfigurationStatus':{'Items':[{'EffDtTm':'2026-10-08'}]}}},
            {'versionName':'10.0'},'2.9','2.10',None]}]},'Bill')
        self.assertEqual(['10.0','2.10','2.9'],[item['shortName'] for item in versions])
        self.assertEqual('uuid',versions[1]['versionUuid'])
        self.assertEqual('nested',versions[1]['description'])
        packages=PackageResponses._normalize_occs_packages({'packages':[{'shortName':'Z','configuration':{'id':4}},{'shortName':'a','ConfigId':7},None]})
        self.assertEqual(['a','Z'],[item['shortName'] for item in packages])
        self.assertEqual('4',packages[1]['configId'])
        self.assertTrue(PackageResponses()._fuzzy_text_match('bl letter','Billing Letter'))

    def test_ok_false_never_counts_as_success(self):
        self.assertFalse(CommandResult(0,'','',{'ok':False}).successful)
        self.assertFalse(CommandResult(0,'','',{'success':False}).successful)
        self.assertTrue(CommandResult(0,'','',{'ok':True}).successful)


class PackageDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.window=WorkspaceWindow(QSettings(str(self.root/'qt.ini'),QSettings.Format.IniFormat))
        settings=UserSettings(self.root/'user.json')
        settings.payload['application']['confirm_on_quit']=False
        settings.payload['occs'].update(work_dir=str(self.root/'work'),shared_workspace_dir=str(self.root/'shared'))
        self.window.comms.settings=settings
        self.window.set_session(demo_session())
        self.calls=[]
        self.runner=patch.object(self.window,'run_comms_operation',side_effect=self.command)
        self.runner.start()
        self.addCleanup(self.runner.stop)
        self.errors=[]
        reporter=patch.object(self.window,'report_error',side_effect=lambda title,message:self.errors.append((title,message)))
        reporter.start()
        self.addCleanup(reporter.stop)
        self.addCleanup(self.close)

    def close(self):
        self.window.package_download_jobs=[]
        self.window.shared_package_dir=None
        self.window.shared_mode='local'
        if self.window.editor:
            self.window.editor.saved=self.window.editor.snapshot()
        self.window.close()

    def command(self,title,args,callback=None,**kwargs):
        job=FakeJob()
        self.calls.append(dict(args=args,callback=callback,options=kwargs,job=job))
        return job

    def complete(self,index,value=None,code=0,cancelled=False):
        call=self.calls[index]
        result=CommandResult(code,'','',value,cancelled=cancelled)
        accepted=call['options'].get('accept_result')
        if not cancelled and (result.successful or (accepted and accepted(result))):
            if call['callback']:
                call['callback'](result)
        elif not cancelled and call['options'].get('on_failure'):
            call['options']['on_failure'](result.message)
        call['job'].done=True
        call['job'].completed.emit(result)

    def make_bundle(self,path,package='Bill',version='2.0'):
        path.mkdir(parents=True,exist_ok=True)
        values={'occs-package.json':dict(schemaVersion='occs-package-bundle/v1',package={'shortName':package},version={'shortName':version},files={}),
                'assembly-template.json':{'$$Id':package,'Documents':[{'$$Id':'DOC','Condition':'','Layouts':[]}],'Fields':[]},
                'version-master.json':{},'document-associations.json':{'associations':[]}}
        for name,value in values.items():
            (path/name).write_bytes(encode(value))
        return path

    def test_package_picker_filters_and_loads_selected_versions(self):
        window=self.window
        window.list_comms_packages()
        self.assertEqual(['package','list','--timeout','360000'],self.calls[0]['args'])
        self.complete(0,{'packages':[{'shortName':'Other','name':'Other'},{'shortName':'Bill','name':'Billing Letter','description':'Monthly','configuration':{'id':9}}]})
        picker=window.comms_package_picker
        self.assertEqual('Bill',picker.tree.topLevelItem(0).text(0))
        picker.filter.setText('bl monthly')
        self.assertEqual(1,picker.tree.topLevelItemCount())
        picker.choose(True)
        self.assertEqual(['package','list','Bill','--timeout','360000'],self.calls[1]['args'])
        self.complete(1,{'package':{'versions':['1.0','2.0']}})
        versions=window.package_version_picker
        self.assertTrue(versions.shared)
        self.assertEqual('2.0',versions.tree.topLevelItem(0).text(0))

    def test_missing_version_list_probes_expected_error_and_latest_fallback(self):
        window=self.window
        window.list_package_versions('Bill')
        self.complete(0,{'packages':[{'shortName':'Bill'}]})
        probe=self.calls[1]
        self.assertEqual(['package','get','Bill','--package-version'],probe['args'][:4])
        self.assertTrue(probe['args'][4].startswith('__atool_version_probe_'))
        self.assertIn('--json',probe['args'])
        self.complete(1,{'ok':False,'error':{'details':{'availableVersions':['1.0','3.0']}}},code=1)
        self.assertEqual('3.0',window.package_version_picker.tree.topLevelItem(0).text(0))
        window.list_package_versions('Bill')
        self.complete(2,{})
        self.complete(3,None,code=1)
        self.assertEqual('latest',window.package_version_picker.tree.topLevelItem(0).text(0))
        before=window.package_version_picker
        window.list_package_versions('Bill')
        self.complete(4,{})
        self.complete(5,cancelled=True)
        self.assertIs(before,window.package_version_picker)

    def test_local_download_disables_switching_and_installs_validated_bundle(self):
        window=self.window
        self.assertTrue(window.download_package('Bill','2.0'))
        args=self.calls[0]['args']
        self.assertEqual(['package','get','Bill','--package-version','2.0'],args[:5])
        output=Path(args[args.index('--output')+1])
        self.assertEqual(window.comms.settings.work_dir.resolve(),output.parent)
        self.assertFalse(window.open_action.isEnabled())
        self.assertFalse(window.documents.isEnabled())
        self.assertFalse(window.open_package(output))
        self.assertFalse(window.close_package())
        self.make_bundle(output)
        self.complete(0,{'bundlePath':str(output),'ok':True})
        self.assertEqual('Bill',window.session.name)
        self.assertEqual('local',window.shared_mode)
        self.assertTrue(window.documents.isEnabled())
        self.assertEqual('2.0',window.comms.settings.get('package_mru')[0]['version'])
        self.assertEqual(str(window.session.source),window.settings.value('lastPackageFile'))

    def test_cancel_retains_current_session_and_invalid_download_does_not_install(self):
        window=self.window
        previous=window.session
        window.download_package('Bill','2.0')
        self.complete(0,cancelled=True)
        self.assertIs(previous,window.session)
        self.assertTrue(window.open_action.isEnabled())
        window.download_package('Bill','2.0')
        output=Path(self.calls[1]['args'][self.calls[1]['args'].index('--output')+1])
        output.mkdir()
        (output/'occs-package.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Unsupported'):
            self.complete(1,{'bundlePath':str(output)})
        self.assertIs(previous,window.session)
        # The visible OperationDialog catches this callback exception in production.
        self.calls[1]['job'].done=True
        self.calls[1]['job'].completed.emit(CommandResult(0,'','',{}))

    def test_shared_download_publication_edit_handoff_and_late_foreign_lock(self):
        window=self.window
        with patch.object(window,'require_shared_sync',return_value=True):
            self.assertTrue(window.download_package('Bill','latest',shared=True))
            output=Path(self.calls[0]['args'][self.calls[0]['args'].index('--output')+1])
            self.make_bundle(output,version='4.0')
            self.complete(0,{'bundlePath':str(output)})
        self.assertEqual('edit',window.shared_mode)
        entry=window.shared_store().entry(window.shared_package_dir)
        self.assertEqual('retrievedFromComms',entry['publication']['operation']['reason'])
        self.assertEqual(str(window.current_bundle_dir()),entry['lock']['bundleDir'])
        self.assertEqual('4.0',window.comms.settings.get('package_mru')[0]['version'])
        window.shared_package_dir=None
        window.shared_mode='local'
        # Late lock on the actual version returned by latest is checked after download.
        self.assertTrue(window.download_package('Bill','latest',shared=True))
        output=Path(self.calls[1]['args'][self.calls[1]['args'].index('--output')+1])
        self.make_bundle(output,version='4.0')
        lock=entry['lock']
        lock['owner']={'user':'different','host':'different'}
        window.shared_store().lock_path(entry['package_dir']).write_bytes(encode(lock))
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.complete(1,{'bundlePath':str(output)})
        self.assertEqual('local',window.shared_mode)
        self.assertEqual('different',json_object(window.shared_store().lock_path(entry['package_dir']))['owner']['user'])

    def test_preflight_foreign_lock_shared_retrieve_control_and_mru_limit(self):
        window=self.window
        source=self.make_bundle(self.root/'source')
        entry=window.shared_store().publish(source,initial=True,reason='retrievedFromComms')
        lock_path=window.shared_store().lock_path(entry['package_dir'])
        lock_path.parent.mkdir(parents=True)
        lock_path.write_bytes(encode({'owner':{'user':'other','host':'other'}}))
        self.assertFalse(window.download_package('Bill','2.0',shared=True))
        self.assertFalse(self.calls)
        self.assertIn('edit lock',self.errors[-1][1])
        window.show_shared_packages()
        window.shared_picker.retrieve()
        self.assertEqual('list',self.calls[-1]['args'][1])
        for index in range(7):
            window.record_package_mru('Bill',str(index))
        self.assertEqual(5,len(window.comms.settings.get('package_mru')))
        self.assertEqual('6',window.comms.settings.get('package_mru')[0]['version'])

    def test_testing_copy_cannot_save_and_preserves_source(self):
        window=self.window
        source=self.make_bundle(self.root/'source')
        entry=window.shared_store().publish(source,initial=True,reason='retrievedFromComms')
        self.assertTrue(window.open_shared_entry(entry,'testing'))
        original=window.session.source.read_bytes()
        self.assertFalse(window.save_action.isEnabled())
        self.assertFalse(window.save_package())
        self.assertEqual(original,window.session.source.read_bytes())
        self.assertIn('read-only',self.errors[-1][1])


    def test_visible_operations_request_json_and_handle_ok_false_and_probe_results(self):
        from atool_qt.operations import OperationDialog
        executable=self.root/'fake-cli'
        executable.write_text("#!/usr/bin/env python3\nimport json,sys\nargs=sys.argv[1:]\nif '--json' not in args:\n print('Human-readable output')\nelif 'probe' in args:\n print(json.dumps({'ok':False,'error':{'details':{'availableVersions':['1','2']}}}))\n sys.exit(1)\nelif 'fail' in args:\n print(json.dumps({'ok':False,'error':{'message':'rejected'}}))\nelse:\n print(json.dumps({'ok':True,'args':args}))\n")
        executable.chmod(0o755)
        self.window.comms.settings.payload['occs']['cli_path']=str(executable)
        successes,failures=[],[]
        dialog=OperationDialog(self.window,'JSON test',['package','list'],successes.append,require_json=True)
        dialog.show()
        self.wait_job(dialog.job)
        self.assertEqual(['package','list','--json'],successes[0].value['args'])
        self.assertTrue(dialog.auto_closed)
        self.assertFalse(dialog.isVisible())
        dialog.close()
        failure=OperationDialog(self.window,'Failure test',['fail'],successes.append,require_json=True,on_failure=failures.append)
        failure.show()
        self.wait_job(failure.job)
        self.assertEqual(['rejected'],failures)
        self.assertTrue(failure.isVisible())
        self.assertEqual(1,len(successes))
        failure.close()
        probe=OperationDialog(self.window,'Expected probe error',['probe','--json'],successes.append,require_json=True,
            accept_result=lambda result:bool(PackageResponses._available_versions_from_occs_error(result.value or {})))
        self.wait_job(probe.job)
        self.assertEqual(['1','2'],PackageResponses._available_versions_from_occs_error(successes[-1].value))
        self.assertEqual(1,probe.job.args.count('--json'))
        probe.close()

    def test_download_flow_closes_every_completed_operation_window(self):
        from atool_qt.operations import OperationDialog
        self.runner.stop()
        source = self.make_bundle(self.root/'downloaded', version='2.0')
        executable = self.root/'download-cli'
        executable.write_text(
            "#!/usr/bin/env python3\nimport json,sys\na=sys.argv[1:]\n"
            "if any('__atool_version_probe_' in item for item in a):\n"
            " print(json.dumps({'ok':False,'error':{'details':{'availableVersions':['2.0']}}}));sys.exit(1)\n"
            "elif 'get' in a:\n print(json.dumps({'ok':True,'bundlePath':" + repr(str(source)) + "}))\n"
            "elif 'Bill' in a:\n print(json.dumps({'ok':True,'packages':[{'shortName':'Bill'}]}))\n"
            "else:\n print(json.dumps({'ok':True,'packages':[{'shortName':'Bill','name':'Bill'}]}))\n")
        executable.chmod(0o755)
        self.window.comms.settings.payload['occs']['cli_path'] = str(executable)
        self.window.list_comms_packages()
        listed = self.window.operation_dialog
        self.wait_job(listed.job)
        self.assertFalse(listed.isVisible())
        self.assertTrue(self.window.comms_package_picker.isVisible())
        self.window.comms_package_picker.choose(True)
        versions = self.window.operation_dialog
        self.wait_job(versions.job)
        probe = self.window.operation_dialog
        self.assertIsNot(probe, versions)
        self.wait_job(probe.job)
        self.assertFalse(versions.isVisible())
        self.assertFalse(probe.isVisible())
        self.assertTrue(self.window.package_version_picker.isVisible())
        with patch.object(self.window, 'require_shared_sync', return_value=True):
            self.window.package_version_picker.choose()
            download = self.window.operation_dialog
            self.wait_job(download.job)
        self.assertFalse(download.isVisible())
        self.assertFalse(self.window.comms_package_picker.isVisible())
        self.assertFalse(self.window.package_version_picker.isVisible())
        self.assertFalse(any(dialog.isVisible() for dialog in self.window.findChildren(OperationDialog)))
        self.assertEqual('edit', self.window.shared_mode)
        self.assertTrue((self.window.shared_package_dir/'published/current/occs-package.json').exists())
        self.assertEqual([], self.errors)

    def test_compact_operation_keeps_failure_details_and_debug_stays_in_activity(self):
        from atool_qt.operations import OperationDialog
        executable = self.root/'failure-cli'
        executable.write_text("#!/usr/bin/env python3\nimport json\nprint(json.dumps({'ok':False,'error':{'message':'Download failed'}}))\n")
        executable.chmod(0o755)
        self.window.comms.settings.payload['occs']['cli_path'] = str(executable)
        self.window.comms.settings.payload['diagnostics']['debug_logging'] = True
        self.window.apply_user_settings()
        terminal = io.StringIO()
        with redirect_stderr(terminal):
            logging.getLogger('atool_qt').debug('Diagnostic retained in Activity')
            dialog = OperationDialog(self.window, 'Get Comms Package', ['package','get'], require_json=True, close_on_success=True)
            dialog.show()
            self.assertFalse(dialog.output.isVisible())
            self.wait_job(dialog.job)
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.output.isVisible())
        self.assertEqual('Download failed', dialog.status.text())
        self.assertIn('Diagnostic retained in Activity', self.window.activity.toPlainText())
        self.assertIn('Comms operation finished', self.window.activity.toPlainText())
        self.assertEqual('', terminal.getvalue())
        dialog.close()

    def wait_job(self,job):
        deadline=time.monotonic()+5
        while not job.done and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(job.done,'Local Comms test did not complete')
