"""Resumable migration guide joining smoke tests, package sync, and Config movement."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget)

from .comms_login import login_args, saved_login_targets
from .configuration import config_label, normalize_configs
from .migration_record import MigrationRecord, eligible_batch, operator_identity, timestamp
from .migration_report import identity
from .occs import unauthorized_error
from .shared_actions import SharedPicker
from .shared_packages import names
from .smoke_tests import SmokeTestDialog, discover_smoke_suites, suite_standard_target


STEPS={'preflight':'1. Test non-prod','sync':'2. Sync and publish','close':'3. Close Configs',
       'migrate':'4. Review and migrate','awaiting_completion':'4. Confirm migration completion',
       'postflight':'5. Compare environments','review':'6. Review and hand off','complete':'Migration complete'}
RECIPIENTS=('andy.little@oracle.com','derrick.phillips@oracle.com','leo.h.wu@accenture.cn',
            'chetan.saxena@clp.com.hk','anusha.kannan@clp.com.hk')


def smoke_passed(outcome):
    runs=outcome.get('runs',[])
    return (not outcome.get('stopped',True) and len(runs)==1 and runs[0].get('valid') is True and
            runs[0].get('successful') is True and not runs[0].get('cancelled') and
            not runs[0].get('timed_out') and runs[0].get('failed')==0 and runs[0].get('passed',0)>0)


class TargetVerificationDialog(QDialog):
    """Record human verification without sending a movement request."""
    def __init__(self,parent,prompt,configs):
        super().__init__(parent)
        self.setWindowTitle('Verify Migration in Target')
        self.resize(700,430)
        layout=QVBoxLayout(self)
        label=QLabel(prompt)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)
        self.configs=QListWidget()
        for config in configs:
            item=QListWidgetItem(f"{config_label(config) or config['id']} [source ID: {config['id']}]")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.configs.addItem(item)
        layout.addWidget(self.configs,1)
        self.note=QTextEdit()
        self.note.setPlaceholderText('Record how you verified completion, including the target Config identity or reference.')
        layout.addWidget(self.note)
        self.status=QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Continue to Comparison')
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def submit(self):
        if not self.configs.count() or any(self.configs.item(index).checkState()!=Qt.CheckState.Checked for index in range(self.configs.count())):
            self.status.setText('Verify and tick every selected Config in the target environment before continuing.')
            return
        if not self.note.toPlainText().strip():
            self.status.setText('Record how you verified successful migration before continuing.')
            return
        self.accept()


class GuidedMigrationDialog(QDialog):
    def __init__(self,workspace):
        super().__init__(workspace)
        self.workspace=workspace
        self.record=None
        self.busy=False
        self.lifecycle_busy=False
        self.operation_token=None
        self.smoke=None
        self.setWindowTitle('Guided Migration')
        self.resize(820,680)
        layout=QVBoxLayout(self)
        self.main_layout=layout
        self.heading=QLabel('Guided Migration')
        self.heading.setStyleSheet('font-size: 18px; font-weight: bold;')
        layout.addWidget(self.heading)
        self.summary=QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.body=QWidget()
        self.body_layout=QVBoxLayout(self.body)
        layout.addWidget(self.body,1)
        self.status=QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        footer=QHBoxLayout()
        self.folder_button=QPushButton('Open Migration Folder')
        self.folder_button.clicked.connect(lambda:self.open_path(self.record.folder) if self.record else None)
        footer.addWidget(self.folder_button)
        self.report_button=QPushButton('Open Migration Report')
        self.report_button.clicked.connect(self.guard(self.open_report))
        footer.addWidget(self.report_button)
        self.new_button=QPushButton('New / Resume…')
        self.new_button.clicked.connect(self.reset)
        footer.addWidget(self.new_button)
        footer.addStretch()
        close=QPushButton('Save and Close')
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.render_setup()

    @property
    def default_root(self):
        configured=self.workspace.comms.settings.section('smoke_tests').get('migration_records_dir','').strip()
        return Path(configured).expanduser().resolve() if configured else (self.workspace.comms.settings.work_dir/'migrations').resolve()

    @property
    def root(self):
        if self.record is not None:
            return self.record.folder.parent.resolve()
        field=getattr(self,'records_folder',None)
        selected=field.text().strip() if field is not None else ''
        return Path(selected).expanduser().resolve() if selected else self.default_root

    def guard(self,callback):
        def invoke(*_):
            try:
                if self.busy or self.workspace.package_busy() or self.copy_pending():
                    self.status.setText('Finish the current operation or Copy To dialog before continuing.')
                    return
                callback()
            except (OSError,ValueError,KeyError,TypeError) as error:
                self.status.setText(str(error))
        return invoke

    def require_stage(self,*stages):
        if not self.record or self.record.data['stage'] not in stages:
            raise ValueError('Complete the preceding migration steps before using this action.')

    def button(self,text,callback):
        control=QPushButton(text)
        control.clicked.connect(self.guard(callback))
        self.body_layout.addWidget(control)
        return control

    def note(self,text):
        control=QLabel(text)
        control.setWordWrap(True)
        control.setTextFormat(Qt.TextFormat.PlainText)
        self.body_layout.addWidget(control)
        return control

    def clear(self):
        previous=self.body
        self.body=QWidget()
        self.body_layout=QVBoxLayout(self.body)
        item=self.main_layout.replaceWidget(previous,self.body)
        del item
        previous.hide()
        previous.deleteLater()
        self.status.clear()

    def set_busy(self,value,*,lifecycle=False):
        self.busy=value
        self.lifecycle_busy=value and lifecycle
        self.body.setEnabled(not value)
        self.new_button.setEnabled(not value)
        self.workspace.update_actions()

    def reset(self):
        if self.busy or self.workspace.package_busy() or self.copy_pending():
            self.status.setText('Finish or close the current operation before changing migration records.')
            return
        self.record=None
        self.render_setup()

    def copy_pending(self):
        return bool(getattr(self,'copy_picker',None) and self.copy_picker.isVisible())

    def render_setup(self):
        self.targets_ack=None
        self.records_folder=None
        self.clear()
        self.heading.setText('Guided Migration — Setup')
        self.summary.setText('Select a test suite and the complete Config batch. Choose where to save migration records, reports, snapshots, and smoke outputs.')
        self.folder_button.setEnabled(False)
        self.report_button.setEnabled(False)
        form=QFormLayout()
        self.operator_name=QLineEdit(operator_identity(self.workspace.comms.settings.get('user_name'))['displayName'])
        self.operator_name.setToolTip('Name of the current operator. Prefilled from User Settings → User Name, or the local login. New actions also record the local login.')
        form.addRow('Current operator',self.operator_name)
        folder_row=QWidget()
        folder_layout=QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0,0,0,0)
        self.records_folder=QLineEdit(str(self.default_root))
        self.records_folder.setToolTip('Parent folder for this new migration. A unique subfolder contains all evidence. Existing records stay in their original locations.')
        folder_layout.addWidget(self.records_folder,1)
        self.browse_records_button=QPushButton('Browse…')
        self.browse_records_button.clicked.connect(self.guard(self.choose_records_folder))
        folder_layout.addWidget(self.browse_records_button)
        form.addRow('Migration records folder',folder_row)
        self.resume_combo=QComboBox()
        self.refresh_saved_migrations()
        self.records_folder.editingFinished.connect(self.refresh_saved_migrations)
        form.addRow('Saved migrations',self.resume_combo)
        self.body_layout.addLayout(form)
        self.button('Resume Selected Migration',self.resume)
        self.button('Open Saved Migration Record…',self.open_saved_record)
        self.suite_combo=QComboBox()
        try:
            suites,_=discover_smoke_suites(self.workspace.comms.settings.section('smoke_tests'))
            for label,path in suites:
                self.suite_combo.addItem(label,str(path))
        except ValueError as error:
            self.note(str(error))
        self.source=QLineEdit(str(self.workspace.comms.settings.get('config_source_session_alias') or 'np'))
        self.target=QLineEdit(str(self.workspace.comms.settings.get('config_target_session_alias') or 'pp'))
        self.source_package=QLineEdit('CLP_bills')
        self.target_package=QLineEdit('print_bulk')
        form=QFormLayout()
        for label,control in [('Test suite',self.suite_combo),('Source session',self.source),('Target session',self.target),
                              ('Package to sync from',self.source_package),('Package to sync to',self.target_package)]:
            form.addRow(label,control)
        self.body_layout.addLayout(form)
        self.suite_target=self.note('')
        self.suite_combo.currentIndexChanged.connect(self.show_suite_target)
        self.show_suite_target()
        self.configs=QListWidget()
        self.configs.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.body_layout.addWidget(self.configs,1)
        self.button('Load Source Configs',self.load_configs)
        self.source.textChanged.connect(self.configs.clear)
        self.source.textChanged.connect(lambda:self.targets_ack.setChecked(False))
        self.target.textChanged.connect(lambda:self.targets_ack.setChecked(False))
        self.loaded_source=None
        self.note('Verify that the suite Standard Test target and source session are non-prod, and the target session is pre-prod.')
        self.targets_ack=QCheckBox('I verified these environment selections.')
        self.body_layout.addWidget(self.targets_ack)
        self.button('Start Guided Migration',self.create_record)

    def choose_records_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Migration Records Folder',str(self.root))
        if folder:
            self.records_folder.setText(folder)
            self.refresh_saved_migrations()

    def refresh_saved_migrations(self):
        selected=self.resume_combo.currentData()
        self.resume_combo.clear()
        recent=str(self.workspace.settings.value('migration/lastRecordsDir','') or '').strip()
        roots={self.root,self.default_root,(self.workspace.comms.settings.work_dir/'migrations').resolve()}
        if recent:
            roots.add(Path(recent).expanduser().resolve())
        paths=set()
        for root in roots:
            try:
                paths.update(path.resolve() for path in root.glob('*/migration.json'))
            except OSError:
                continue
        for path in sorted(paths,reverse=True):
            try:
                record=MigrationRecord.load(path)
                self.resume_combo.addItem(f"{record.data['created_at']} — {record.data['suite_name']} — {STEPS[record.data['stage']]}",str(path))
                self.resume_combo.setItemData(self.resume_combo.count()-1,str(path),Qt.ItemDataRole.ToolTipRole)
            except (OSError,ValueError,KeyError,TypeError):
                continue
        index=self.resume_combo.findData(selected)
        if index>=0:
            self.resume_combo.setCurrentIndex(index)

    def open_saved_record(self):
        path,_=QFileDialog.getOpenFileName(self,'Open Saved Migration Record',str(self.root),'Migration records (migration.json);;JSON files (*.json)')
        if path:
            self.resume_path(path)

    def show_suite_target(self):
        try:
            path=self.suite_combo.currentData()
            label,_=suite_standard_target(json.loads(Path(path).read_text(encoding='utf-8-sig'))) if path else ('(select a suite)',[])
            self.suite_target.setText('Standard Test target from JSON: '+label)
        except (OSError,ValueError,TypeError,AttributeError) as error:
            self.suite_target.setText(str(error))
        if getattr(self,'targets_ack',None) is not None:
            self.targets_ack.setChecked(False)

    def operation(self,title,args,callback,*,require_json=True,remote_write=False):
        token=object()
        self.operation_token=token
        self.set_busy(True,lifecycle=True)
        def release():
            if self.operation_token is token:
                self.operation_token=None
                self.set_busy(False)
                return True
            return False
        def show_error(message):
            authentication_failed=unauthorized_error(message)
            not_eligible='eligible movement list' in message or 'No eligible ConfigIds' in message
            if self.record:
                try:
                    self.record.event('operation_failed',operation=title,remote_write=remote_write,
                                      category='authentication' if authentication_failed else 'not_eligible' if not_eligible else 'command_failure',
                                      pending=self.record.data.get('pending'))
                except (OSError,ValueError) as error:
                    message+=' Could not save the failure record: '+str(error)
            if self.record and self.record.data.get('pending'):
                self.render()
            if authentication_failed:
                message='Authentication was rejected (401/Unauthorized). Refresh the source and target sessions before retrying.'
            if self.record and title=='Review Migration Batch' and not_eligible:
                message+=' The Configs may already be migrated. Verify them in target '+self.record.data['target']+' and use I Verified Migration in Target to continue.'
            suffix=(' Check Comms before retrying this remote write.' if remote_write else
                    ' No migration request was submitted by this step; this does not establish the outcome of earlier attempts.')
            self.status.setText(title+': '+message+suffix)
        def failed(message):
            if release():
                show_error(message)
        def success(result):
            if release():
                try:
                    callback(result.value)
                except (OSError,ValueError,KeyError,TypeError) as error:
                    show_error(str(error))
        job=self.workspace.run_comms_operation(title,args,success,require_json=require_json,on_failure=failed)
        job.completed.connect(lambda result:failed('Operation canceled or did not return valid evidence.') if self.operation_token is token else None)
        return job

    def load_configs(self):
        alias=self.source.text().strip()
        if not alias:
            raise ValueError('Enter a source session alias.')
        def loaded(value):
            self.configs.clear()
            self.loaded_source=alias
            configs=normalize_configs(value)
            for config in configs:
                if config['status'].casefold() not in ('open','closed'):
                    continue
                item=QListWidgetItem(f"{config_label(config)} [{config['id']}] — {config['status']}")
                item.setData(Qt.ItemDataRole.UserRole,config)
                self.configs.addItem(item)
            self.status.setText('Select every Config intended for this migration. Include already closed Configs if they are eligible to move.')
        self.operation('Load Guided Migration Configs',['list-configs','--session',alias,'--timeout',str(self.workspace.comms.settings.timeout_ms)],loaded)

    def create_record(self):
        if not self.operator_name.text().strip():
            raise ValueError('Enter the migration operator name.')
        if not self.targets_ack.isChecked():
            raise ValueError('Verify the Standard Test, source, and target environments before starting.')
        source,target=self.source.text().strip(),self.target.text().strip()
        if self.loaded_source!=source:
            raise ValueError('Load Configs from the selected source session first.')
        configs=[item.data(Qt.ItemDataRole.UserRole) for item in self.configs.selectedItems()]
        source_package,target_package=self.source_package.text().strip(),self.target_package.text().strip()
        if not source_package or not target_package or source_package.casefold()==target_package.casefold():
            raise ValueError('Choose different source and target package short names for the optional sync.')
        suite_path=self.suite_combo.currentData()
        if not suite_path:
            raise ValueError('Select a smoke test suite. Configure Suite JSON Folder in User Settings if no suites are listed.')
        suite=json.loads(Path(suite_path).read_text(encoding='utf-8-sig'))
        label,args=suite_standard_target(suite)
        targets,_=saved_login_targets()
        source_info,target_info=targets.get(source),targets.get(target)
        suite_info=targets.get(label) if args[0]=='--session' else None
        if source_info and ((suite_info and any(source_info[k]!=suite_info[k] for k in ('customer','region','tenancy'))) or
                            (args[0]=='--session' and not suite_info and label!=source) or
                            (args[0]=='--tenancy' and source_info['tenancy']!=label)):
            raise ValueError('The suite Standard Test target does not match the selected source session.')
        if source_info and target_info and all(source_info[k]==target_info[k] for k in ('customer','region','tenancy')):
            raise ValueError('The source and target aliases refer to the same environment.')
        self.record=MigrationRecord.create(self.root,self.workspace.comms.settings.section('smoke_tests'),suite_path,
                                           configs,source,target,source_package,target_package,
                                           actor=operator_identity(self.operator_name.text()))
        self.workspace.settings.setValue('migration/lastRecordsDir',str(self.record.folder.parent))
        self.render()

    def resume(self):
        path=self.resume_combo.currentData()
        if not path:
            raise ValueError('No saved migration is selected.')
        self.resume_path(path)

    def resume_path(self,path):
        if not self.operator_name.text().strip():
            raise ValueError('Enter the current operator name before resuming.')
        self.record=MigrationRecord.load(path,actor=operator_identity(self.operator_name.text()))
        self.record.event('resumed')
        self.workspace.settings.setValue('migration/lastRecordsDir',str(self.record.folder.parent))
        self.render()

    def render(self):
        self.clear()
        data=self.record.data
        stage=data['stage']
        self.heading.setText(STEPS[stage])
        self.folder_button.setEnabled(True)
        self.report_button.setEnabled(True)
        configs=', '.join(f"{config_label(c) or c['id']} [{c['id']}]" for c in data['configs'])
        self.summary.setText(f"{data['suite_name']} | {data['source']} → {data['target']}\nConfigs: {configs}\n"
                             f"Migration operator: {identity(data.get('performed_by'))} | Current operator: {identity(self.record.actor)}")
        if not data.get('performed_by'):
            self.note('This older record has no migration operator. Record the person who performed the migration for the report.')
            self.button('Record Migration Operator…',self.record_operator)
        if data.get('pending'):
            self.note('An operation was started without a saved completion receipt: '+str(data['pending'])+
                      '. Check Comms before retrying a remote write. Closing an already closed Config is safe to retry.')
        getattr(self,'render_'+stage)()
        self.body_layout.addStretch()
        if self.record.report_error:
            self.status.setText('Progress saved, but the Markdown report could not be refreshed: '+self.record.report_error+'. Use Open Migration Report to retry.')

    def record_operator(self):
        from PySide6.QtWidgets import QInputDialog
        name,accepted=QInputDialog.getText(self,'Migration Operator','Who performed this migration? Historical actions retain their original attribution.',
                                         text=self.record.actor['displayName'])
        if not accepted:
            return
        if not name.strip():
            raise ValueError('Enter the name of the person who performed the migration.')
        # Historical attribution is an explicit annotation, not inferred from
        # the login of whoever happens to reopen an older record.
        operator=dict(displayName=name.strip())
        self.record.data['performed_by']=operator
        self.record.event('migration_operator_recorded',operator=operator)
        self.render()

    def open_report(self):
        if not self.record:
            raise ValueError('Start or resume a migration before opening its report.')
        path=self.record.write_report()
        self.record.report_error=''
        self.open_path(path)

    def render_preflight(self):
        self.note('Run Standard Test against the suite JSON target in non-prod. All previews must pass before package sync or migration.')
        self.button('Run Pre-Migration Standard Test',lambda:self.run_smoke(False))

    def render_sync(self):
        data=self.record.data
        self.note(f"If {data['source_package']} changed, open it in ATool and copy it to the latest {data['target_package']} version. "
                  'Publish the copy to one of the selected Configs. The existing copy and publish dialogs retain their review steps.')
        self.button('Copy Package and Publish…',self.copy_package)
        if data.get('copied_target'):
            self.note('Copied target: '+data['copied_target'])
            self.button('Publish Copied Target…',self.publish_copied)
        self.skip_sync=QCheckBox(f"{data['source_package']} has no changes requiring a sync to {data['target_package']}.")
        self.body_layout.addWidget(self.skip_sync)
        if data.get('published'):
            p=data['published']
            self.note(f"Verified {p['package']} {p['version']} in Config {p['config_id']} ({'already matched Comms' if p.get('no_changes') else 'published'}).")
        self.button('Continue to Config Closure',self.sync_complete)

    def publish_options(self):
        data=self.record.data
        return dict(source_alias=data['source'],config_ids=[c['id'] for c in data['configs']],on_success=self.published)

    def copy_package(self):
        self.require_stage('sync')
        data=self.record.data
        workspace=self.workspace
        if not workspace.session or not workspace.session.bundle or names(workspace.session.bundle['manifest'])[0]!=data['source_package']:
            raise ValueError('Open '+data['source_package']+' in ATool before copying. You can save and close this guide, then resume it.')
        self.record.verify_inputs()
        self.copy_picker=SharedPicker(workspace,copy_to=True,publish_options=self.publish_options(),on_copied=self.copied)
        index=self.copy_picker.target_package.findText(data['target_package'])
        if index<0:
            self.copy_picker.close()
            raise ValueError('The target package is not available in shared storage: '+data['target_package'])
        self.copy_picker.target_package.setCurrentIndex(index)
        self.copy_picker.target_package.setEnabled(False)
        self.copy_picker.show()

    def copied(self,entry):
        self.require_stage('sync')
        if entry['package_name']!=self.record.data['target_package']:
            raise ValueError('The copied package does not match this migration target.')
        self.record.data.update(copied_target=str(entry['package_dir']),published=None)
        self.record.event('package_copied',package=entry['package_name'],version=entry['version_name'])
        self.render()

    def publish_copied(self):
        self.require_stage('sync')
        entry=self.workspace.shared_store().entry(self.record.data['copied_target'])
        if not entry or entry['package_name']!=self.record.data['target_package']:
            raise ValueError('The copied target is no longer available in shared storage.')
        self.workspace.publish_package(target_entry=entry,**self.publish_options())

    def published(self,receipt):
        self.require_stage('sync')
        data=self.record.data
        if (data['stage']!='sync' or receipt['package']!=data['target_package'] or
                receipt['config_id'] not in {c['id'] for c in data['configs']} or receipt['source']!=data['source']):
            raise ValueError('The publish receipt does not match this migration.')
        data['published']=receipt
        self.record.event('package_publish_verified',**receipt)
        self.render()

    def sync_complete(self):
        self.require_stage('sync')
        if not self.record.data.get('published') and not self.skip_sync.isChecked():
            raise ValueError('Publish the copied target, or confirm no package sync is required.')
        self.record.advance('close',sync_skipped=not bool(self.record.data.get('published')))
        self.render()

    def protected(self):
        self.record.verify_inputs()
        for config in self.record.data['configs']:
            if not self.workspace.config_lifecycle_allowed(config['id'],config_label(config)):
                return True
        return False

    def render_close(self):
        self.note('Close the selected Configs in the source environment. Shared Config locks and lockout windows are checked before every write.')
        self.note('Closed in this record: '+(', '.join(self.record.data['closed']) or 'none'))
        self.button('Review and Close Selected Configs…',self.close_configs)

    def close_configs(self):
        self.require_stage('close')
        if self.protected():
            return
        data=self.record.data
        remaining=[c for c in data['configs'] if c['id'] not in data['closed']]
        text='Close these Configs in '+data['source']+'?\n\n'+'\n'.join(f"{config_label(c)} [{c['id']}]" for c in remaining)
        if remaining and QMessageBox.question(self,'Confirm Config Closure',text)!=QMessageBox.StandardButton.Yes:
            return
        self.close_next()

    def close_next(self):
        self.require_stage('close')
        data=self.record.data
        remaining=[c for c in data['configs'] if c['id'] not in data['closed']]
        if not remaining:
            self.record.advance('migrate')
            self.render()
            return
        if self.protected():
            return
        config=remaining[0]
        data['pending']='close '+config['id']
        self.record.event('close_started',config_id=config['id'])
        def closed(value):
            if (value.get('ok') is not True or not (value.get('closed') is True or value.get('alreadyClosed') is True) or
                    not isinstance(value.get('config'),dict) or str(value['config'].get('id'))!=config['id']):
                raise ValueError('The CLI did not confirm Config closure. Check Comms before retrying.')
            data['closed'].append(config['id'])
            data['pending']=None
            self.record.event('config_closed',config_id=config['id'])
            self.close_next()
        self.operation('Close Migration Config',['close-config','--session',data['source'],'--config-id',config['id'],
                                                 '--timeout',str(self.workspace.comms.settings.timeout_ms)],closed,remote_write=True)

    def render_migrate(self):
        self.note('Review the eligible Config batch before movement. The CLI moves every eligible Config; the guide blocks a batch that differs from your selection. '
                  'Keep other migration work paused between review and initiation.')
        if self.record.data.get('pending')=='migration':
            self.note('A previous migration attempt has an uncertain outcome. Do not initiate it again without checking Comms.')
            self.button('I Verified Movement Did Not Start…',self.clear_uncertain_migration)
            self.button('I Verified Migration in Target…',self.external_completion)
        else:
            self.button('Refresh Migration Sessions',self.refresh_migration_sessions)
            self.button('Check Batch and Migrate…',self.migrate)
            self.button('I Verified Migration in Target…',self.external_completion)
        self.note('If the Configs are already migrated, verify successful completion in the target environment and choose I Verified Migration in Target. '
                  'This records your confirmation and continues to comparison testing without submitting another migration. '
                  'A password-authenticated source session is required for CLI migration.')

    def clear_uncertain_migration(self):
        self.require_stage('migrate')
        note=self.confirmation_note('Explain how you verified that movement did not start. Check the target environment before allowing another attempt.')
        if note is None:
            return
        self.record.data['pending']=None
        self.record.event('movement_not_started_verified',note=note)
        self.render()

    def refresh_migration_sessions(self,callback=None):
        self.require_stage('migrate')
        data=self.record.data
        if '--sso' in login_args(data['source']):
            raise ValueError('The migration source uses SSO. Use a password-authenticated source, or migrate externally and record completion here.')
        aliases=list(dict.fromkeys((data['target'],data['source'])))
        def refresh(remaining):
            if remaining:
                alias=remaining[0]
                self.operation('Refresh Migration Session '+alias,login_args(alias),
                               lambda _:refresh(remaining[1:]),require_json=False)
                return
            self.record.event('migration_sessions_refreshed',aliases=aliases)
            if callback:
                callback()
            else:
                self.status.setText('Source and target sessions refreshed. You can check the migration batch now.')
        refresh(aliases)

    def migrate(self):
        self.require_stage('migrate')
        if self.record.data.get('pending')=='migration':
            raise ValueError('Verify the outcome of the previous migration attempt before retrying.')
        if self.protected():
            return
        data=self.record.data
        if '--sso' in login_args(data['source']):
            raise ValueError('The migration source uses SSO. Use a password-authenticated source, or migrate externally and record completion here.')
        args=['migrate','--source-session',data['source'],'--target-session',data['target'],
              '--config-id',data['configs'][0]['id'],'--timeout',str(self.workspace.comms.settings.timeout_ms)]
        def reviewed(value):
            if value.get('ok') is not True or value.get('dryRun') is not True:
                raise ValueError('The CLI did not confirm a migration dry run.')
            batch=eligible_batch(data['configs'],value)
            self.record.event('migration_batch_review',eligible=batch)
            text=f"Move the full eligible batch from {data['source']} to {data['target']}?\n\n"+'\n'.join(c.get('shortName') or c.get('name') or c.get('id','') for c in batch)
            if QMessageBox.question(self,'Confirm Migration Batch',text)!=QMessageBox.StandardButton.Yes:
                return
            if self.protected():
                return
            data['pending']='migration'
            self.record.event('migration_started',eligible=batch)
            def initiated(receipt):
                if receipt.get('ok') is not True or receipt.get('initiated') is not True:
                    raise ValueError('Movement was not confirmed as initiated. Check Comms before retrying.')
                actual=receipt.get('eligible',[])
                self.record.advance('awaiting_completion',movement=dict(eligible=actual,initiated=True),performed_by=copy.deepcopy(self.record.actor))
                self.render()
                try:
                    eligible_batch(data['configs'],receipt)
                except ValueError:
                    self.record.event('movement_batch_changed',eligible=actual)
                    self.status.setText('The movement batch changed after review. Check every moved Config in Comms before confirming completion.')
            self.operation('Initiate Guided Migration',args,initiated,remote_write=True)
        def check_batch():
            self.record.event('migration_batch_check_started',dry_run=True,source=data['source'],target=data['target'])
            self.operation('Review Migration Batch',args+['--dry-run'],reviewed)
        self.refresh_migration_sessions(check_batch)

    def render_awaiting_completion(self):
        self.note('Movement was initiated. The CLI does not wait for completion. Verify that the selected Configs finished migrating successfully in Comms before continuing.')
        if self.record.data.get('movement'):
            self.note('Movement batch: '+json.dumps(self.record.data['movement']['eligible'],ensure_ascii=False))
        self.button('Confirm Migration Completed…',self.external_completion)

    def confirmation_note(self,prompt,*,configs=None):
        if configs is not None:
            dialog=TargetVerificationDialog(self,prompt,configs)
            if dialog.exec()!=QDialog.DialogCode.Accepted:
                return None
            return dialog.note.toPlainText().strip()
        from PySide6.QtWidgets import QInputDialog
        note,accepted=QInputDialog.getMultiLineText(self,'Migration Verification',prompt+'\n\nRecord the verification or reference:')
        if not accepted:
            return None
        if not note.strip():
            raise ValueError('Enter a verification note before continuing.')
        return note.strip()

    def external_completion(self):
        self.require_stage('migrate','awaiting_completion')
        data=self.record.data
        note=self.confirmation_note(f"Verify that every selected Config is present in target {data['target']} and its migration from {data['source']} completed successfully. "
                                    'Check the Config identity and migration outcome, then tick each Config below. '
                                    'Continuing records your verification; it does not submit a migration request.',configs=data['configs'])
        if note is None:
            return
        if not note.strip():
            raise ValueError('Record how you verified successful migration before continuing.')
        verification=dict(method='manual_target_verification',source=data['source'],target=data['target'],
                          configs=copy.deepcopy(data['configs']),note=note.strip(),verified_at=timestamp(),
                          verified_by=copy.deepcopy(self.record.actor),
                          previous_stage=data['stage'],previous_pending=data.get('pending'),
                          initiation_receipt=bool(data.get('movement',{}).get('initiated')))
        self.record.event('target_migration_verified',verification=verification)
        self.record.advance('postflight',completion_note=note.strip(),completion_verification=verification)
        self.render()

    def render_postflight(self):
        self.note('Compare the same saved suite and input snapshots in the source and target environments. Failed previews block handoff; visual differences require explicit review.')
        self.button('Run Post-Migration Comparison',lambda:self.run_smoke(True))

    def run_smoke(self,comparison):
        self.require_stage('postflight' if comparison else 'preflight')
        self.record.verify_inputs()
        data=self.record.data
        settings=copy.deepcopy(data['settings'])
        settings.update(run_standard=not comparison,run_comparison=comparison)
        self.smoke=SmokeTestDialog(self.workspace,settings=settings,locked=True)
        self.workspace.smoke_dialog=self.smoke
        self.smoke.run_finished.connect(lambda outcome:self.smoke_completed(comparison,outcome))
        self.smoke.show()
        self.smoke.start()
        if self.smoke.running:
            self.set_busy(True)
        else:
            self.status.setText(self.smoke.status.text())

    def smoke_completed(self,comparison,outcome):
        self.set_busy(False)
        try:
            self.require_stage('postflight' if comparison else 'preflight')
            self.record.verify_inputs()
            self.record.data['postflight' if comparison else 'preflight']=outcome
            self.record.event('postflight_result' if comparison else 'preflight_result',outcome=outcome)
            if smoke_passed(outcome):
                self.record.advance('review' if comparison else 'sync')
                self.render()
            else:
                self.render()
                self.status.setText('Testing did not pass. Review the report. Resolve failed previews or setup issues before continuing; after migration, fix defects in non-prod under a new Config and start a new migration record.')
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.status.setText(str(error))

    def render_review(self):
        outcome=self.record.data['postflight']
        run=outcome['runs'][0]
        self.note(f"{run['passed']} previews passed; {run['failed']} failed; {run['reviews']} comparisons need review.")
        self.button('Open Comparison Report',lambda:self.open_path(Path(run['report'])))
        self.button('Open Smoke Email Draft',self.open_email)
        self.note('Recipients: '+', '.join(RECIPIENTS))
        self.review_ack=QCheckBox('I inspected the report and accepted every comparison marked for review.')
        self.body_layout.addWidget(self.review_ack)
        self.review_note=QTextEdit()
        self.review_note.setPlaceholderText('Record why the visual differences are acceptable (required when comparisons need review).')
        self.body_layout.addWidget(self.review_note)
        self.button('Differences Not Accepted — Start a New Migration',self.reject_differences)
        self.button('Accept Results and Prepare Handoff',self.complete)

    def open_email(self):
        run=self.record.data['postflight']['runs'][0]
        path=Path(run['report']).with_name('smoke-email.eml')
        if not path.is_file():
            raise ValueError('No smoke-email.eml was produced. Open the migration folder to review the report instead.')
        self.open_path(path)

    def reject_differences(self):
        self.record.event('comparison_rejected',note=self.review_note.toPlainText().strip())
        self.status.setText('Do not send the handoff. Fix the differences in non-prod under a new Config, then use New / Resume to start a new migration record.')

    def complete(self):
        self.require_stage('review')
        self.record.verify_inputs()
        outcome=self.record.data['postflight']
        if not smoke_passed(outcome) or not self.review_ack.isChecked():
            raise ValueError('Inspect the report and explicitly accept all comparisons before completing.')
        note=self.review_note.toPlainText().strip()
        if outcome['runs'][0]['reviews'] and not note:
            raise ValueError('Record why the comparison differences are acceptable.')
        self.record.advance('complete',review_note=note,reviewed_at=timestamp(),reviewed_by=copy.deepcopy(self.record.actor))
        self.render()

    def render_complete(self):
        self.note('All checks were completed and comparison results accepted. Open the smoke email draft, review its contents, and send it to the recipients below. ATool does not send it automatically.')
        if self.record.data.get('performed_by'):
            self.button('Correct Migration Operator…',self.record_operator)
        self.note('Recipients: '+', '.join(RECIPIENTS))
        self.button('Open Smoke Email Draft',self.open_email)
        self.handoff_sent=QCheckBox('I sent the reviewed handoff email to the listed recipients.')
        self.body_layout.addWidget(self.handoff_sent)
        self.button('Record Email Sent',self.record_sent)
        if self.record.data.get('email_sent'):
            self.note('Email handoff recorded.')

    def record_sent(self):
        self.require_stage('complete')
        if not self.handoff_sent.isChecked():
            raise ValueError('Confirm that you sent the email before recording the handoff.')
        self.record.data['email_sent']=True
        self.record.event('handoff_sent',recipients=list(RECIPIENTS))
        self.render()

    @staticmethod
    def open_path(path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def reject(self):
        if self.busy or self.workspace.package_busy() or self.copy_pending():
            self.status.setText('Finish or cancel the current operation before closing the guide. Progress is already saved.')
            return
        super().reject()


class GuidedMigrationActions:
    def install_migration_actions(self):
        self.migration_dialog=None
        self.migration_action=self.action('Guided Migration…',self.show_guided_migration)
        self.package_menu.addAction(self.migration_action)
        self.package_menu.aboutToShow.connect(self.update_migration_actions)

    def update_migration_actions(self):
        if hasattr(self,'migration_action'):
            self.migration_action.setEnabled(not self.package_busy())

    def show_guided_migration(self):
        current=self.migration_dialog
        if current and current.isVisible():
            current.raise_()
            current.activateWindow()
            return
        if self.package_busy():
            return
        self.migration_dialog=GuidedMigrationDialog(self)
        self.migration_dialog.show()
