"""Staged publish contract and recovery, without a real Comms write."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from atool_qt.occs import CommandResult
from atool_qt.shared_packages import encode, json_object
from atool_qt.user_settings import UserSettings


class FakeJob(QObject):
    completed=Signal(object)
    def __init__(self):
        super().__init__()
        self.done=False


class PublishTests(unittest.TestCase):
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
        settings.payload['occs'].update(shared_workspace_dir=str(self.root/'shared'),work_dir=str(self.root/'work'),config_source_session_alias='np',last_config_id='11',active_config_label='CFG11')
        self.window.comms.settings=settings
        source=self.root/'original'
        source.mkdir()
        values={'occs-package.json':dict(schemaVersion='occs-package-bundle/v1',package={'shortName':'Bill'},version={'shortName':'2'},files={},sourceHashes={'assemblyTemplate':'original'}),
                'assembly-template.json':{'$$Id':'Bill','Documents':[{'$$Id':'DOC','Condition':'','Layouts':[]}],'Fields':[{'Name':'Name','Path':'$.name'}]},
                'version-master.json':{},'document-associations.json':{'associations':[]}}
        for name,value in values.items():
            (source/name).write_bytes(encode(value))
        entry=self.window.shared_store().publish(source,initial=True,reason='retrievedFromComms')
        with patch.object(self.window,'require_shared_sync',return_value=True):
            self.assertTrue(self.window.open_shared_entry(entry,'edit'))
        self.calls,self.errors=[],[]
        self.runner=patch.object(self.window,'run_comms_operation',side_effect=self.command)
        self.runner.start()
        self.addCleanup(self.runner.stop)
        reporter=patch.object(self.window,'report_error',side_effect=lambda title,message:self.errors.append((title,message)))
        reporter.start()
        self.addCleanup(reporter.stop)
        self.addCleanup(self.close)

    def close(self):
        self.window.package_download_jobs=[]
        self.window.finish_publish()
        self.window.shared_package_dir=None
        self.window.shared_mode='local'
        if self.window.editor:
            self.window.editor.saved=self.window.editor.snapshot()
        self.window.close()

    def command(self,title,args,callback=None,**kwargs):
        self.assertTrue(kwargs.get('close_on_success'))
        job=FakeJob()
        self.calls.append(dict(args=args,callback=callback,options=kwargs,job=job))
        return job

    def complete(self,index,value=None,code=0,cancelled=False):
        call=self.calls[index]
        result=CommandResult(code,'','',value,cancelled=cancelled)
        call['job'].done=True
        if not cancelled and result.successful:
            if call['callback']:
                try:
                    call['callback'](result)
                except (OSError,ValueError) as error:
                    if call['options'].get('on_failure'):
                        call['options']['on_failure'](str(error))
                    else:
                        raise
        elif not cancelled and call['options'].get('on_failure'):
            call['options']['on_failure'](result.message)
        call['job'].completed.emit(result)

    def begin(self):
        self.assertTrue(self.window.publish_package())
        self.assertEqual(['list-configs','--session','np','--timeout','360000'],self.calls[0]['args'])
        self.complete(0,{'configs':[{'id':'12','shortName':'CLOSED','status':'Closed'},{'id':'11','shortName':'CFG11','status':'Open'}]})
        dialog=self.window.publish_config_dialog
        self.assertEqual(1,dialog.config.count())
        dialog.submit()
        self.assertEqual('11',self.window.comms.settings.get('last_config_id'))
        return self.window.publish_context

    def test_dry_run_uses_staged_snapshot_and_no_changes_never_publishes(self):
        context=self.begin()
        stage=context['stage']
        args=self.calls[1]['args']
        self.assertEqual(['package','--session','np','save',str(stage),'--config-id','11','--dry-run','--timeout','360000'],args)
        self.assertNotEqual(self.window.current_bundle_dir(),stage)
        self.assertFalse(self.window.documents.isEnabled())
        self.assertFalse(self.window.close_package())
        self.complete(1,{'changes':{'assemblyTemplate':False}})
        self.assertIsNone(self.window.publish_context)
        self.assertEqual(2,len(self.calls))
        self.assertFalse(stage.exists())
        self.assertTrue(self.window.documents.isEnabled())

    def test_declining_review_and_cancellation_clean_snapshot(self):
        context=self.begin()
        stage=context['stage']
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):
            self.complete(1,{'changes':{'assemblyTemplate':True}})
        self.assertEqual(2,len(self.calls))
        self.assertFalse(stage.exists())
        self.calls=[]
        self.assertTrue(self.window.publish_package())
        stage=self.window.publish_context['stage']
        self.complete(0,cancelled=True)
        self.assertIsNone(self.window.publish_context)
        self.assertFalse(stage.exists())

    def test_publish_keeps_undo_redo_without_reverting_refreshed_metadata(self):
        window = self.window
        window.editor.update_record(window.session.documents[0], {'Descr': 'Edited before publish'}, 'documents')
        window.refresh_edit()
        with patch.object(window, 'require_shared_sync', return_value=True):
            context = self.begin()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.complete(1, {'changes': {'assemblyTemplate': True}})
        template = json_object(context['stage'] / 'assembly-template.json')
        template['ServerStamp'] = 'fresh'
        template['Documents'][0]['ServerUuid'] = 'new-document-uuid'
        (context['stage'] / 'assembly-template.json').write_bytes(encode(template))
        manifest_value = json_object(context['stage'] / 'occs-package.json')
        manifest_value['sourceHashes']['assemblyTemplate'] = 'new-source-hash'
        (context['stage'] / 'occs-package.json').write_bytes(encode(manifest_value))
        with patch.object(window, 'require_shared_sync', return_value=True):
            self.complete(2, {'changes': {'assemblyTemplate': True}})
        self.assertFalse(window.editor.dirty)
        self.assertTrue(window.undo_action.isEnabled())
        window.undo_action.trigger()
        self.assertTrue(window.editor.dirty)
        self.assertNotIn('Descr', window.session.payload['Documents'][0])
        self.assertEqual(window.session.payload['Documents'][0]['ServerUuid'], 'new-document-uuid')
        self.assertEqual(window.session.payload['ServerStamp'], 'fresh')
        self.assertEqual(window.session.bundle['manifest']['sourceHashes']['assemblyTemplate'], 'new-source-hash')
        window.redo_action.trigger()
        self.assertEqual(window.session.payload['Documents'][0]['Descr'], 'Edited before publish')
        self.assertFalse(window.editor.dirty)
        window.undo_action.trigger()
        self.assertTrue(window.save_package())
        self.assertEqual(json_object(window.session.source)['ServerStamp'], 'fresh')
        self.assertEqual(self.errors, [])

    def test_publish_external_reference_uses_portable_stage_and_restores_original_location(self):
        from atool_qt.session import PackageSession
        root = self.window.current_bundle_dir()
        external = self.root / 'external-template.json'
        (root / 'assembly-template.json').rename(external)
        value = json_object(root / 'occs-package.json')
        value['files']['assemblyTemplate'] = str(external)
        value['bundlePath'] = str(root)
        (root / 'occs-package.json').write_bytes(encode(value))
        self.window.shared_store().publish(root, self.window.shared_package_dir)
        self.window.editor = None
        self.window.set_session(PackageSession.open(root))
        context = self.begin()
        copied = json_object(context['stage'] / 'occs-package.json')
        self.assertEqual(copied['files']['assemblyTemplate'], 'assembly-template.json')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.complete(1, {'changes': {'assemblyTemplate': True}})
        edited = json_object(context['stage'] / 'assembly-template.json')
        edited['ServerRefreshed'] = True
        (context['stage'] / 'assembly-template.json').write_bytes(encode(edited))
        with patch.object(self.window, 'require_shared_sync', return_value=True):
            self.complete(2, {'changes': {'assemblyTemplate': True}})
        self.assertEqual(self.errors, [])
        self.assertTrue(json_object(external)['ServerRefreshed'])
        self.assertEqual(json_object(root / 'occs-package.json')['files']['assemblyTemplate'], str(external))
        self.assertEqual(self.window.session.source.resolve(), external.resolve())
        self.assertTrue(self.window.shared_store().matches(root, self.window.shared_package_dir))

    def test_confirmed_publish_refreshes_local_shared_metadata_and_keeps_mapping(self):
        window=self.window
        window.session.map_data({'name':'Alice'},'input.json')
        revision=window.session.mapping_revision
        context=self.begin()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.complete(1,{'package':'Bill','version':'2','changes':{'assemblyTemplate':True},'uploadPlan':{'assemblyTemplate':True,'versionMaster':True}})
        self.assertNotIn('--dry-run',self.calls[2]['args'])
        self.assertEqual(str(context['stage']),self.calls[2]['args'][4])
        value=json_object(context['stage']/'occs-package.json')
        value['sourceHashes']['assemblyTemplate']='updated-by-cli'
        value['bundlePath']=str(context['stage'])
        (context['stage']/'occs-package.json').write_bytes(encode(value))
        with patch.object(window,'require_shared_sync',return_value=True):
            self.complete(2,{'package':'Bill','version':'2','changes':{'assemblyTemplate':True}})
        self.assertIsNone(window.publish_context)
        self.assertFalse(context['stage'].exists())
        self.assertEqual('updated-by-cli',window.session.bundle['manifest']['sourceHashes']['assemblyTemplate'])
        self.assertEqual(str(context['root']),window.session.bundle['manifest']['bundlePath'])
        self.assertTrue(window.session.mapped)
        self.assertEqual(revision,window.session.mapping_revision)
        self.assertEqual({'name':'Alice'},window.session.data)
        self.assertFalse(window.editor.dirty)
        entry=window.shared_store().entry(window.shared_package_dir)
        self.assertEqual('publishedToComms',entry['publication']['operation']['reason'])
        self.assertEqual('publishedToComms',json_object(context['root']/window.shared_store().BASELINE)['reason'])
        self.assertTrue(window.shared_store().matches(context['root'],window.shared_package_dir))
        self.assertFalse(hasattr(window,'publish_result_dialog'))
        self.assertIn('Package published to Comms',window.statusBar().currentMessage())

    def test_changed_local_or_stage_snapshot_blocks_actual_publish(self):
        context=self.begin()
        path=context['root']/'assembly-template.json'
        value=json_object(path)
        value['externalChange']=True
        path.write_bytes(encode(value))
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.complete(1,{'changes':{'assemblyTemplate':True}})
        self.assertEqual(2,len(self.calls))
        self.assertIsNone(self.window.publish_context)
        self.assertIn('changed after',self.errors[-1][1])
        self.assertTrue(json_object(path)['externalChange'])

    def test_locked_config_retry_resolves_source_config_and_revalidates(self):
        context=self.begin()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.complete(1,{'ok':False,'error':{'message':'SFD0375 - Item is locked for editing under ConfigId CFG22'}},code=1)
        self.assertEqual(['list-configs','--session','np','--timeout','360000'],self.calls[2]['args'])
        self.complete(2,{'configs':[{'id':'22','shortName':'CFG22','status':'Open'}]})
        self.assertIn('--dry-run',self.calls[3]['args'])
        self.assertEqual('22',self.calls[3]['args'][self.calls[3]['args'].index('--config-id')+1])
        self.assertEqual('22',self.window.comms.settings.get('last_config_id'))
        self.complete(3,{'changes':{}})
        self.assertFalse(context['stage'].exists())


    def test_config_list_failure_and_no_open_configs_never_publish(self):
        self.assertTrue(self.window.publish_package())
        context=self.window.publish_context
        self.complete(0,{'ok':False,'error':{'message':'unavailable'}},code=1)
        self.assertFalse(context['stage'].exists())
        self.assertEqual(1,len(self.calls))
        self.calls=[]
        self.assertTrue(self.window.publish_package())
        self.complete(0,{'configs':[{'id':'1','shortName':'Closed','status':'Closed'}]})
        self.assertIsNone(self.window.publish_context)
        self.assertIn('No valid open',self.errors[-1][1])

    def test_shared_sync_failure_after_publish_is_reported_without_false_remote_failure(self):
        context=self.begin()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.complete(1,{'changes':{'assemblyTemplate':True}})
        with patch.object(self.window,'require_shared_sync',return_value=False):
            self.complete(2,{'changes':{'assemblyTemplate':True}})
        self.assertIsNone(self.window.publish_context)
        text=self.window.publish_result_dialog.text()
        self.assertIn('Package published to Comms',text)
        self.assertIn('Shared storage warning',text)
        self.assertEqual('edit',self.window.shared_mode)

    def test_external_change_during_remote_write_keeps_recovery_copy(self):
        context=self.begin()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.complete(1,{'changes':{'assemblyTemplate':True}})
        local=context['root']/'assembly-template.json'
        value=json_object(local)
        value['external']='keep'
        local.write_bytes(encode(value))
        self.complete(2,{'changes':{'assemblyTemplate':True}})
        self.assertEqual('keep',json_object(local)['external'])
        self.assertIsNone(self.window.publish_context)
        recovery=next(context['root'].parent.glob(context['root'].name+'-published-recovery-*'))
        self.assertTrue((recovery/'occs-package.json').is_file())
        self.assertIn('Local Refresh Failed',self.errors[-1][0])
        self.assertIn(str(recovery),self.errors[-1][1])


    def test_reviewed_session_target_cannot_change_between_dry_run_and_publish(self):
        context=self.begin()
        self.window.comms.settings.payload['occs']['config_source_session_alias']='other-session'
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.complete(1,{'changes':{'assemblyTemplate':True}})
        self.assertEqual('np',self.calls[2]['args'][2])
        self.complete(2,cancelled=True)
        self.assertFalse(context['stage'].exists())
        self.assertIsNone(self.window.publish_context)


    def test_canceled_write_retains_cli_refreshed_snapshot_without_changing_local_files(self):
        context=self.begin()
        before=(context['root']/'occs-package.json').read_bytes()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.complete(1,{'changes':{'assemblyTemplate':True}})
        value=json_object(context['stage']/'occs-package.json')
        value['sourceHashes']['assemblyTemplate']='possibly-published'
        (context['stage']/'occs-package.json').write_bytes(encode(value))
        self.complete(2,cancelled=True)
        recovery=next(context['root'].parent.glob(context['root'].name+'-published-recovery-*'))
        self.assertEqual('possibly-published',json_object(recovery/'occs-package.json')['sourceHashes']['assemblyTemplate'])
        self.assertEqual(before,(context['root']/'occs-package.json').read_bytes())
        self.assertFalse(context['stage'].exists())
