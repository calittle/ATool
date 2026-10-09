"""Staged Comms publish: Config selection, dry run, review, commit, and shared sync."""
import copy
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout

from .configuration import config_label, filtered_configs, normalize_configs
from .session import PackageSession
from .shared_packages import bundle_hashes, bundle_paths, copy_bundle_files, encode, manifest, names
from .storage import write_files


class PublishConfigDialog(QDialog):
    def __init__(self,workspace,configs):
        super().__init__(workspace)
        self.workspace=workspace
        self.setWindowTitle('Publish Package to Comms')
        self.resize(660,240)
        layout=QVBoxLayout(self)
        form=QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form.addRow('Package',QLabel(' '.join(names(workspace.session.bundle['manifest']))))
        folder=QPlainTextEdit(str(workspace.current_bundle_dir()))
        folder.setReadOnly(True)
        folder.setFixedHeight(folder.fontMetrics().lineSpacing()*3+16)
        form.addRow('Package Folder',folder)
        self.config=QComboBox()
        for config in configs:
            self.config.addItem(f"{config_label(config) or config['id']} [{config['id']}]",config)
        current=str(workspace.comms.settings.get('last_config_id') or '')
        for index in range(self.config.count()):
            if self.config.itemData(index)['id']==current:
                self.config.setCurrentIndex(index)
                break
        form.addRow('Configuration',self.config)
        layout.addLayout(form)
        layout.addStretch()
        row=QHBoxLayout()
        row.addStretch()
        cancel,submit=QPushButton('Cancel'),QPushButton('Dry Run')
        row.addWidget(cancel)
        row.addWidget(submit)
        layout.addLayout(row)
        cancel.clicked.connect(self.reject)
        submit.clicked.connect(self.submit)
        self.finished.connect(lambda _:workspace.finish_publish() if workspace.publish_context and not workspace.publish_context.get('started') else None)

    def submit(self):
        config=self.config.currentData()
        if config and self.workspace.set_active_config(config):
            self.workspace.publish_context['started']=True
            self.accept()
            self.workspace.publish_dry_run(config['id'])


class PackagePublishActions:
    def install_publish_actions(self):
        self.publish_context=None
        self.publish_action=self.action('Publish Package to Comms…',self.publish_package,'Ctrl+Shift+U')
        before=next(action for action in self.package_menu.actions() if action.text()=='Check Shared Folder Sync…')
        self.package_menu.insertAction(before,self.publish_action)
        self.package_menu.aboutToShow.connect(self.update_publish_actions)

    def update_publish_actions(self):
        if hasattr(self,'publish_action'):
            self.publish_action.setEnabled(self.shared_mode=='edit' and bool(self.current_bundle_dir()) and not self.package_busy())

    def publish_package(self):
        if self.package_busy() or not self.current_bundle_dir() or self.shared_mode!='edit' or not self.shared_package_dir:
            self.report_error('Publish Package to Comms','Open a shared package for edit before publishing to Comms.')
            return False
        try:
            self.flush_properties()
            if self.editor.dirty and not self.save_package():
                return False
            store=self.shared_store()
            if not store.matches(self.current_bundle_dir(),self.shared_package_dir):
                if not self.update_shared_package(release=False):
                    return False
            store.verify_update(self.current_bundle_dir(),store.entry(self.shared_package_dir))
            temporary=tempfile.TemporaryDirectory(prefix='atool-publish-')
            stage=(Path(temporary.name)/'bundle').resolve()
            root=self.current_bundle_dir().resolve()
            hashes=bundle_hashes(root)
            original_manifest=copy.deepcopy(manifest(root))
            shutil.copytree(root,stage)
            source_paths=copy_bundle_files(root,stage)
            if bundle_hashes(root)!=hashes:
                temporary.cleanup()
                raise ValueError('The package changed while preparing its publish snapshot.')
            self.publish_context=dict(temporary=temporary,stage=stage,root=root,shared_dir=self.shared_package_dir,
                source_paths=source_paths,original_manifest=original_manifest,source_hashes=hashes,stage_hashes=bundle_hashes(stage),session=self.session,started=False,retried_configs=set(),
                source_alias=str(self.comms.settings.get('config_source_session_alias') or 'np'))
            self.update_actions()
            alias=self.publish_context['source_alias']
            def listed(result):
                try:
                    configs=filtered_configs(normalize_configs(result.value),str(self.comms.settings.get('config_id_filter') or ''))
                except re.error as error:
                    self.publish_failed(str(error),'','configs')
                    return
                if not configs:
                    self.publish_failed('No valid open configurations are available. Check the Configuration Filter.','','configs')
                    return
                self.publish_config_dialog=PublishConfigDialog(self,configs)
                self.publish_config_dialog.show()
            self.publish_operation('List Publish Configs',['list-configs','--session',alias,'--timeout',str(self.comms.settings.timeout_ms)],listed,
                on_failure=lambda message:self.publish_failed(message,'','configs'))
            return True
        except (OSError,ValueError) as error:
            self.finish_publish()
            self.report_error('Publish Package to Comms',str(error))
            return False

    def publish_operation(self,title,args,callback,*,on_failure=None):
        context=self.publish_context
        def completed(result):
            if self.publish_context is context:
                callback(result)
        def failed(message):
            if self.publish_context is context and on_failure:
                on_failure(message)
        job=self.run_comms_operation(title,args,completed,require_json=True,on_failure=failed,close_on_success=True)
        self.package_download_jobs.append(job)
        def finished(result):
            if job in self.package_download_jobs:
                self.package_download_jobs.remove(job)
            if result.cancelled and self.publish_context is context:
                if '--dry-run' not in args and args[:1] == ['package']:
                    try:
                        changed = bundle_hashes(context['stage']) != context['stage_hashes']
                    except (ValueError, OSError):
                        changed = True
                    if changed:
                        try:
                            recovery = self.preserve_publish_snapshot(context)
                            self.statusBar().showMessage('Publish canceled; refreshed files retained at ' + str(recovery), 10000)
                        except OSError as error:
                            self.report_error('Canceled Publish Recovery', str(error))
                self.finish_publish()
            self.update_actions()
        job.completed.connect(finished)
        if job.done:
            self.package_download_jobs.remove(job)
        self.update_actions()
        return job

    def verify_publish_snapshot(self):
        context=self.publish_context
        if not context or self.session is not context['session'] or self.current_bundle_dir()!=context['root']:
            raise ValueError('The active package changed. Start a new publish dry run.')
        if bundle_hashes(context['root'])!=context['source_hashes']:
            raise ValueError('Local package files changed after the dry-run snapshot. Start a new dry run.')
        if bundle_hashes(context['stage'])!=context['stage_hashes']:
            raise ValueError('The reviewed publish snapshot changed. Start a new dry run.')
        entry=self.shared_store().entry(context['shared_dir'])
        if not entry:
            raise ValueError('The shared package version is no longer available.')
        self.shared_store().verify_update(context['root'],entry)
        return context

    def publish_args(self,config,dry_run):
        context=self.verify_publish_snapshot()
        args=['package','--session',context['source_alias'],'save',str(context['stage']),'--config-id',str(config)]
        if dry_run:
            args+=['--dry-run']
        return args+['--timeout',str(self.comms.settings.timeout_ms)]

    def publish_dry_run(self,config):
        try:
            args=self.publish_args(config,True)
        except (OSError,ValueError) as error:
            self.publish_failed(str(error),config,'validation')
            return
        def reviewed(result):
            self.verify_publish_snapshot()
            changes=result.value.get('changes')
            changed=[str(key) for key,value in changes.items() if value] if isinstance(changes,dict) else []
            if not changed:
                self.statusBar().showMessage('Comms dry run complete: no changes.',5000)
                self.finish_publish()
                return
            summary=self.publish_summary(result.value)
            if QMessageBox.question(self,'Confirm Comms Publish',summary+'\n\nPublish these changes to Comms?',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                self.finish_publish()
                return
            self.publish_commit(config)
        self.publish_operation('Comms Publish Dry Run',args,reviewed,on_failure=lambda message:self.publish_failed(message,config,'dry-run'))

    def publish_commit(self,config):
        try:
            args=self.publish_args(config,False)
        except (OSError,ValueError) as error:
            self.publish_failed(str(error),config,'validation')
            return
        self.publish_operation('Publish Package to Comms',args,self.publish_completed,
            on_failure=lambda message:self.publish_failed(message,config,'publish'))

    def publish_summary(self,value):
        context=self.publish_context
        package,version=names(manifest(context['root'])) if context else ('','')
        lines=[f"Package: {value.get('package',package)}",f"Version: {value.get('version',version)}"]
        config=value.get('configId')
        if isinstance(config,dict):
            lines.append('Configuration: '+' - '.join(str(config.get(key) or '') for key in ('shortName','name','resolved') if config.get(key)))
        changes=value.get('changes')
        changed=[str(key) for key,flag in changes.items() if flag] if isinstance(changes,dict) else []
        lines.append('Changed: '+(', '.join(changed) or 'none'))
        plan=value.get('uploadPlan')
        planned=[str(key) for key,flag in plan.items() if flag] if isinstance(plan,dict) else []
        if planned and planned!=changed:
            lines.append('Will upload: '+', '.join(planned))
        return '\n'.join(lines)

    def publish_completed(self,result):
        context=self.publish_context
        warning=''
        try:
            if bundle_hashes(context['root'])!=context['source_hashes']:
                raise ValueError('Comms was updated, but local files changed during publishing. The updated bundle is retained at '+str(context['stage']))
            value=manifest(context['stage'])
            files={}
            for key,path in bundle_paths(context['stage'],value).items():
                if key=='documentAssociations' and not path.exists():
                    continue
                destination=context['source_paths'][key]
                files[destination]=path.read_bytes()
            for key in ('files','bundlePath'):
                if key in context['original_manifest']:
                    value[key]=copy.deepcopy(context['original_manifest'][key])
                elif key=='bundlePath' and value.get(key)==str(context['stage']):
                    value[key]=str(context['root'])
                elif key=='files':
                    value.pop(key,None)
            files[context['source_paths']['manifest']]=encode(value)
            write_files(files)
            previous=self.session
            refreshed=PackageSession.open(context['root'])
            if previous.mapped:
                refreshed.map_data(previous.data,previous.data_name)
                refreshed.mapping_revision=previous.mapping_revision
            previous_editor=self.editor
            from .editor import PackageEditor
            self.editor=PackageEditor(refreshed)
            if previous_editor:
                self.editor.retain_history(previous_editor)
            self.set_session(refreshed,preserve_selection=True)
            context['session']=refreshed
            try:
                if not self.require_shared_sync('update this shared package after publishing'):
                    raise ValueError('Shared storage was not updated because sync could not be confirmed.')
                self.shared_store().publish(context['root'],context['shared_dir'],reason='publishedToComms',release=False)
                baseline=context['root']/self.shared_store().BASELINE
                from .shared_packages import json_object
                metadata=json_object(baseline)
                metadata['reason']='publishedToComms'
                write_files({baseline:encode(metadata)})
            except (OSError,ValueError) as error:
                warning=str(error)
            self.record_package_mru(*names(refreshed.bundle['manifest']))
            message='Package published to Comms.\n\n'+self.publish_summary(result.value)
            if warning:
                message+='\n\nShared storage warning:\n'+warning
            self.statusBar().showMessage('Package published to Comms.'+(' Shared storage needs attention.' if warning else ''),7000)
            self.log(message)
            if warning:
                self.publish_result_dialog=QMessageBox(QMessageBox.Icon.Warning,'Comms Publish Result',message,QMessageBox.StandardButton.Ok,self)
                self.publish_result_dialog.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.publish_result_dialog.show()
        except (OSError,ValueError) as error:
            # Preserve the server-refreshed snapshot for recovery after a successful remote write.
            try:
                recovery=self.preserve_publish_snapshot(context)
            except OSError:
                warning=' The refreshed publish snapshot could not be retained in local storage.'
            else:
                warning=' Refreshed files are available at '+str(recovery)
            self.report_error('Published to Comms; Local Refresh Failed',str(error)+warning)
        finally:
            self.finish_publish()

    def preserve_publish_snapshot(self,context):
        recovery=context['root'].parent/(context['root'].name+'-published-recovery-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        shutil.copytree(context['stage'],recovery)
        return recovery

    def publish_failed(self,message,config,stage):
        context=self.publish_context
        match=re.search(r'SFD0375\s*-\s*Item is locked for editing under ConfigId\s+([^\s\'".,;]+)',message)
        locked=match.group(1).strip() if match else ''
        if context and locked and stage in ('dry-run','publish') and locked.casefold()!=str(config).casefold() and locked.casefold() not in context['retried_configs']:
            if QMessageBox.question(self,'Package Locked',f'Package is locked under Config {locked}. Resolve that Config and retry with a new dry run?',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                context['retried_configs'].add(locked.casefold())
                alias=context['source_alias']
                def resolved(result):
                    configs=normalize_configs(result.value)
                    target=next((item for item in configs if locked.casefold() in {str(item.get(key) or '').casefold() for key in ('id','shortName','name')}),dict(id=locked,shortName=locked))
                    if self.set_active_config(target):
                        self.publish_dry_run(target['id'])
                    else:
                        self.finish_publish()
                self.publish_operation('Resolve Locked Publish Config',['list-configs','--session',alias,'--timeout',str(self.comms.settings.timeout_ms)],resolved,
                    on_failure=lambda error:self.publish_failed(error,locked,'configs'))
                return
        self.finish_publish()
        self.report_error('Publish Package to Comms',message)

    def finish_publish(self):
        context=self.publish_context
        self.publish_context=None
        if context:
            context['temporary'].cleanup()
        if hasattr(self,'publish_config_dialog') and self.publish_config_dialog.isVisible():
            self.publish_config_dialog.reject()
        if hasattr(self,'publish_action'):
            self.update_actions()
