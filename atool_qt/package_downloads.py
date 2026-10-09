"""Comms package retrieval, with original version probing and shared-lock rules."""
import copy
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .grids import configure_grid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from .package_responses import PackageResponses
from .session import PackageSession
from .shared_packages import json_object, manifest, names, segment, timestamp


class PackagePicker(QDialog):
    def __init__(self, workspace, packages):
        super().__init__(workspace)
        self.workspace,self.packages=workspace,packages
        self.setWindowTitle('Get Packages from Comms')
        self.resize(920,530)
        layout=QVBoxLayout(self)
        row=QHBoxLayout()
        self.filter=QLineEdit()
        self.filter.setPlaceholderText('Filter short name, name, description, Config ID, or UUID')
        row.addWidget(self.filter,1)
        clear=QPushButton('Clear')
        row.addWidget(clear)
        layout.addLayout(row)
        self.tree=QTreeWidget()
        self.tree.setHeaderLabels(['Short Name','Name','Description'])
        configure_grid(self.tree)
        self.tree.setColumnWidth(0,190)
        self.tree.setColumnWidth(1,250)
        layout.addWidget(self.tree,1)
        self.status=QLabel()
        layout.addWidget(self.status)
        row=QHBoxLayout()
        row.addStretch()
        for title,callback in [('Get to Local…',lambda:self.choose(False)),('Get to Shared/Edit…',lambda:self.choose(True))]:
            button=QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        clear.clicked.connect(self.filter.clear)
        self.filter.textChanged.connect(self.render)
        self.tree.itemDoubleClicked.connect(lambda *_:self.choose(False))
        self.render()

    def render(self,*_):
        self.tree.clear()
        responses=PackageResponses()
        for package in self.packages:
            if not responses._fuzzy_text_match(self.filter.text(), ' '.join(str(value) for value in package.values())):
                continue
            item=QTreeWidgetItem([package['shortName'],package['name'],package['description']])
            item.setData(0,Qt.ItemDataRole.UserRole,package)
            for column in range(3):
                item.setToolTip(column,item.text(column))
            self.tree.addTopLevelItem(item)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.status.setText(f'Showing {self.tree.topLevelItemCount()} of {len(self.packages)} packages.')

    def choose(self,shared):
        item=self.tree.currentItem()
        if item:
            self.workspace.list_package_versions(item.text(0),shared=shared)
            self.accept()


class VersionPicker(QDialog):
    def __init__(self,workspace,package,versions,shared=False):
        super().__init__(workspace)
        self.workspace,self.package,self.shared=workspace,package,shared
        self.setWindowTitle('Select Package Version')
        self.resize(840,460)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel(package))
        self.tree=QTreeWidget()
        self.tree.setHeaderLabels(['Version','Effective','Description'])
        configure_grid(self.tree)
        self.tree.setColumnWidth(0,170)
        self.tree.setColumnWidth(1,230)
        layout.addWidget(self.tree,1)
        versions=PackageResponses._sort_occs_package_versions(versions)
        fallback=not versions
        for version in versions or [dict(shortName='latest',effectiveAt='',description='Current version from Comms')]:
            item=QTreeWidgetItem([version['shortName'],version.get('effectiveAt',''),version.get('description','')])
            for column in range(3):
                item.setToolTip(column,item.text(column))
            self.tree.addTopLevelItem(item)
        self.tree.setCurrentItem(self.tree.topLevelItem(0))
        status=QLabel('Comms did not return a version list; latest requests the current version.' if fallback else f'{len(versions)} package versions.')
        status.setWordWrap(True)
        layout.addWidget(status)
        row=QHBoxLayout()
        row.addStretch()
        cancel,get=QPushButton('Cancel'),QPushButton('Get to Shared/Edit' if shared else 'Get to Local')
        row.addWidget(cancel)
        row.addWidget(get)
        layout.addLayout(row)
        cancel.clicked.connect(self.close)
        get.clicked.connect(self.choose)
        self.tree.itemDoubleClicked.connect(lambda *_:self.choose())

    def choose(self):
        item=self.tree.currentItem()
        if item and self.workspace.download_package(self.package,item.text(0),shared=self.shared):
            self.accept()


class PackageDownloadActions:
    def install_download_actions(self):
        self.package_download_jobs=[]
        self.package_installing=False
        self.package_query_revision=0
        self.package_download_authorization=None
        self.get_packages_action=self.action('Get Packages from Comms…',self.list_comms_packages)
        self.package_menu.insertAction(self.shared_update_action,self.get_packages_action)
        self.package_menu.insertSeparator(self.shared_update_action)

    def package_busy(self):
        return self.job is not None or (not getattr(self,'package_installing',False) and (getattr(self,'publish_context',None) is not None or any(not job.done for job in getattr(self,'package_download_jobs',[]))))

    def list_comms_packages(self):
        self.package_query_revision+=1
        revision=self.package_query_revision
        def listed(result):
            if revision!=self.package_query_revision:
                return
            self.comms_package_picker=PackagePicker(self,PackageResponses._normalize_occs_packages(result.value))
            self.comms_package_picker.show()
        self.run_comms_operation('List Comms Packages',['package','list','--timeout',str(self.comms.settings.timeout_ms)],listed,require_json=True,close_on_success=True)

    def list_package_versions(self,package,*,shared=False):
        if self.package_busy() or not package.strip() or not self.confirm_discard():
            return
        self.package_download_authorization=(self.session,self.editor.snapshot() if self.editor else None)
        self.package_query_revision+=1
        revision=self.package_query_revision
        def loaded(result):
            if revision!=self.package_query_revision:
                return
            versions=PackageResponses._normalize_occs_package_versions(result.value,package)
            if versions:
                self.show_package_versions(package,versions,shared)
            else:
                self.probe_package_versions(package,shared,revision)
        self.run_comms_operation('List Package Versions',['package','list',package,'--timeout',str(self.comms.settings.timeout_ms)],loaded,require_json=True,close_on_success=True)

    def show_package_versions(self,package,versions,shared):
        self.package_version_picker=VersionPicker(self,package,versions,shared)
        self.package_version_picker.show()

    def probe_package_versions(self,package,shared,revision):
        probe=Path(tempfile.gettempdir())/f'atool-version-probe-{time.time_ns()}'
        args=['package','get',package,'--package-version',f'__atool_version_probe_{time.time_ns()}__','--output',str(probe),'--timeout',str(self.comms.settings.timeout_ms),'--json']
        def completed(result):
            if revision==self.package_query_revision:
                available=PackageResponses._available_versions_from_occs_error(result.value or {})
                self.show_package_versions(package,PackageResponses._normalize_occs_package_versions({'versions':available},package),shared)
        job=self.run_comms_operation('Probe Package Versions',args,completed,require_json=True,close_on_success=True,
            accept_result=lambda result:bool(PackageResponses._available_versions_from_occs_error(result.value or {})),
            on_failure=lambda _:self.show_package_versions(package,[],shared) if revision==self.package_query_revision else None)
        job.completed.connect(lambda _:shutil.rmtree(probe,ignore_errors=True) if probe.is_dir() else None)

    def may_download_shared(self,package,version):
        if version.casefold()=='latest':
            return True
        store=self.shared_store()
        path=store.shared_dir/'packages'/segment(package)/segment(version)
        lock_path=store.lock_path(path)
        lock=json_object(lock_path) if lock_path.exists() else None
        if lock and not store.owned(lock,store.owner):
            self.report_error('Get Package from Comms','Another user holds this version’s edit lock. Use Get to Local, or wait for the lock to be released.')
            return False
        return True

    def download_package(self,package,version='latest',*,shared=False):
        package,version=package.strip(),version.strip() or 'latest'
        if not package or self.package_busy():
            return False
        try:
            authorized=self.package_download_authorization
            already_confirmed=bool(authorized and authorized[0] is self.session and authorized[1]==(self.editor.snapshot() if self.editor else None))
            if not already_confirmed and not self.confirm_discard():
                return False
            if shared and not self.may_download_shared(package,version):
                return False
            work=self.comms.settings.work_dir.resolve()
            work.mkdir(parents=True,exist_ok=True)
            output=work/f'{segment(package)}-{segment(version)}-{datetime.now():%Y%m%d_%H%M%S_%f}'
            args=['package','get',package,'--package-version',version,'--output',str(output),'--timeout',str(self.comms.settings.timeout_ms)]
            def downloaded(result):
                self.package_installing=True
                try:
                    self.install_download(result.value,output,shared)
                finally:
                    self.package_installing=False
            job=self.run_comms_operation('Get Comms Package',args,downloaded,require_json=True,close_on_success=True)
            self.package_download_jobs.append(job)
            def finished(_):
                if job in self.package_download_jobs:
                    self.package_download_jobs.remove(job)
                self.update_actions()
            job.completed.connect(finished)
            if job.done:
                finished(None)
            self.update_actions()
            return True
        except (OSError,ValueError) as error:
            self.report_error('Get Package from Comms',str(error))
            return False

    def install_download(self,result,requested,shared):
        root=Path(str(result.get('bundlePath') or requested)).expanduser().resolve()
        value=manifest(root)
        session=PackageSession.open(root)
        store=self.shared_store()
        if shared:
            package_dir=store.package_dir(value)
            lock_path=store.lock_path(package_dir)
            lock=json_object(lock_path) if lock_path.exists() else None
            if lock and not store.owned(lock,store.owner):
                if QMessageBox.question(self,'Shared Package Locked','The downloaded version is locked by another user. Open the downloaded bundle locally instead?',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                    shared=False
                else:
                    return
            elif lock and QMessageBox.question(self,'Replace Shared Package','You hold the edit lock for this version. Retrieving it from Comms replaces the shared copy. Continue?',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                return
        if not self.prepare_shared_exit():
            return
        if shared:
            if not self.require_shared_sync('write this package to the shared folder'):
                return
            entry=store.publish(root,initial=True,reason='retrievedFromComms')
            local=store.open_copy(entry,'edit')
            session=PackageSession.open(local)
            context,mode=entry['package_dir'],'edit'
        else:
            context,mode=store.restore_context(root)
        self.editor=None
        self.set_session(session)
        self.shared_package_dir,self.shared_mode=context,mode
        self.remember_package_session()
        self.settings.setValue('lastDirectory',str(session.bundle['root']))
        self.update_shared_actions()
        self.statusBar().showMessage('Retrieved '+names(value)[0]+' '+names(value)[1]+(' for shared editing.' if shared else ' locally.'),5000)

    def record_package_mru(self,package,version):
        if not package or not version:
            return
        previous=self.comms.settings.get('package_mru',[])
        previous=previous if isinstance(previous,list) else []
        entries=[dict(package=package,version=version,lastOpenedAt=timestamp())]+[item for item in previous if isinstance(item,dict) and (str(item.get('package','')).casefold(),str(item.get('version','')).casefold())!=(package.casefold(),version.casefold())]
        payload=copy.deepcopy(self.comms.settings.payload)
        payload['occs']['package_mru']=entries[:5]
        try:
            self.comms.settings.save(payload)
        except (OSError,ValueError) as error:
            self.report_error('Package History',str(error))
