"""Shared Package menus and local-copy lifecycle in the unified workspace."""
import getpass
import socket
from datetime import datetime
from pathlib import Path

from .grids import configure_grid

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from .session import PackageSession
from .shared_packages import SharedPackages


class SharedPicker(QDialog):
    def __init__(self, workspace, unlock=False):
        super().__init__(workspace)
        self.workspace, self.unlock = workspace, unlock
        self.setWindowTitle('Manual Shared Package Unlock' if unlock else 'Open Shared Package')
        self.resize(960, 560)
        layout=QVBoxLayout(self)
        self.filter=QLineEdit()
        self.filter.setPlaceholderText('Filter package, version, owner, or status')
        layout.addWidget(self.filter)
        self.tree=QTreeWidget()
        self.tree.setHeaderLabels(['Package','Version','Updated','Owner','Lock / Status'])
        configure_grid(self.tree)
        for column,width in enumerate((160,90,230,140)):
            self.tree.setColumnWidth(column,width)
        self.tree.setSortingEnabled(True)
        self.tree.sortItems(0,Qt.SortOrder.AscendingOrder)
        layout.addWidget(self.tree,1)
        self.status=QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row=QHBoxLayout()
        refresh=QPushButton('Refresh')
        row.addWidget(refresh)
        row.addStretch()
        retrieve=QPushButton('Retrieve from Comms…')
        row.addWidget(retrieve)
        retrieve.clicked.connect(self.retrieve)
        self.open_button=QPushButton('Unlock…' if unlock else 'Open…')
        row.addWidget(self.open_button)
        if not unlock:
            edit,testing=QPushButton('Open for Edit'),QPushButton('Open Testing Copy')
            row.addWidget(edit)
            row.addWidget(testing)
            edit.clicked.connect(lambda:self.select('edit'))
            testing.clicked.connect(lambda:self.select('testing'))
        layout.addLayout(row)
        self.filter.textChanged.connect(self.apply_filter)
        refresh.clicked.connect(self.refresh)
        self.open_button.clicked.connect(lambda:self.select(None))
        self.tree.itemDoubleClicked.connect(lambda *_:self.select(None))
        self.refresh()

    def retrieve(self):
        self.workspace.list_comms_packages()
        self.accept()

    def refresh(self):
        self.tree.clear()
        try:
            entries=self.workspace.shared_store().entries()
        except (OSError,ValueError) as error:
            self.status.setText(str(error))
            return
        for entry in entries:
            lock=entry.get('lock')
            if self.unlock and not lock:
                continue
            publication=entry.get('publication',{})
            owner=publication.get('owner',{})
            lock_owner=lock.get('owner',{}) if lock else {}
            status=entry.get('unavailable_reason') or ('Locked: '+str(lock_owner.get('displayName') or lock_owner.get('user') or '(unknown)') if lock else 'Available')
            item=QTreeWidgetItem([entry['package_name'],entry['version_name'],str(publication.get('publishedAt') or entry['manifest'].get('createdAt') or ''),
                str(owner.get('displayName') or owner.get('user') or ''),status])
            item.setData(0,Qt.ItemDataRole.UserRole,entry)
            for column in range(5):
                item.setToolTip(column,item.text(column))
            self.tree.addTopLevelItem(item)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(next((self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(index).data(0,Qt.ItemDataRole.UserRole)['package_dir']==self.workspace.shared_package_dir),self.tree.topLevelItem(0)))
        self.status.setText(f'{self.tree.topLevelItemCount()} shared package versions. '+str(self.workspace.shared_store().shared_dir))
        self.apply_filter()

    def apply_filter(self,*_):
        query=self.filter.text().casefold()
        for index in range(self.tree.topLevelItemCount()):
            item=self.tree.topLevelItem(index)
            item.setHidden(query not in ' '.join(item.text(column) for column in range(5)).casefold())

    def select(self,mode):
        item=self.tree.currentItem()
        if not item:
            return
        entry=item.data(0,Qt.ItemDataRole.UserRole)
        success=self.workspace.unlock_shared_entry(entry) if self.unlock else self.workspace.open_shared_entry(entry,mode)
        if success:
            self.accept()
        else:
            self.refresh()


class CleanupDialog(QDialog):
    def __init__(self,workspace):
        super().__init__(workspace)
        self.workspace=workspace
        self.setWindowTitle('Clean Local Packages')
        self.resize(1000,560)
        layout=QVBoxLayout(self)
        self.status=QLabel('Default selection includes removable copies at least 14 days old. Open packages and copies referenced by active locks are protected.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tree=QTreeWidget()
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.toggle_shortcut=QShortcut(QKeySequence('Space'), self.tree)
        self.toggle_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.toggle_shortcut.activated.connect(self.toggle_selected)
        self.tree.itemDoubleClicked.connect(lambda *_:self.toggle_selected())
        self.tree.itemChanged.connect(self.update_summary)
        self.tree.setHeaderLabels(['Delete','Package','Version','Modified','Age','Size','Status','Folder'])
        configure_grid(self.tree)
        layout.addWidget(self.tree,1)
        row=QHBoxLayout()
        for title,callback in [('Refresh',self.refresh),('Toggle',self.toggle_selected),('Select Old',self.choose_old),('Select Removable',lambda:self.choose(True)),('Select None',lambda:self.choose(False)),('Delete Selected…',self.delete)]:
            button=QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        previous={}
        selected=set()
        for index in range(self.tree.topLevelItemCount()):
            item=self.tree.topLevelItem(index)
            key=item.data(0,Qt.ItemDataRole.UserRole)['path'].resolve()
            previous[key]=item.checkState(0)
            if item.isSelected():
                selected.add(key)
        self.tree.clear()
        try:
            entries=self.workspace.shared_store().cleanup_entries(self.workspace.current_bundle_dir())
        except (OSError,ValueError) as error:
            self.status.setText(str(error))
            return
        for entry in entries:
            item=QTreeWidgetItem(['',entry['package'],entry['version'],datetime.fromtimestamp(entry['modified']).strftime('%Y-%m-%d %H:%M'),f"{int(entry['age'])}d",f"{entry['size']/1024:.1f} KB",entry['status'],entry['path'].name])
            item.setData(0,Qt.ItemDataRole.UserRole,entry)
            if not entry['protected']:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0,previous.get(entry['path'].resolve(),Qt.CheckState.Checked if entry['default_selected'] else Qt.CheckState.Unchecked))
            item.setToolTip(7,str(entry['path']))
            self.tree.addTopLevelItem(item)
            item.setSelected(entry['path'].resolve() in selected)
        self.update_summary()

    def toggle_selected(self):
        for item in self.tree.selectedItems():
            if not item.data(0,Qt.ItemDataRole.UserRole)['protected']:
                item.setCheckState(0,Qt.CheckState.Unchecked if item.checkState(0)==Qt.CheckState.Checked else Qt.CheckState.Checked)

    def update_summary(self,*_):
        entries=[self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount())]
        removable=[item for item in entries if not item.data(0,Qt.ItemDataRole.UserRole)['protected']]
        checked=[item for item in removable if item.checkState(0)==Qt.CheckState.Checked]
        size=sum(item.data(0,Qt.ItemDataRole.UserRole)['size'] for item in checked)
        self.status.setText(f'Default cleanup selects removable copies at least 14 days old. Selected: {len(checked)} of {len(removable)} removable, {size/1024:.1f} KB. Open packages and copies referenced by active locks are protected.')

    def choose_old(self):
        for index in range(self.tree.topLevelItemCount()):
            item=self.tree.topLevelItem(index)
            entry=item.data(0,Qt.ItemDataRole.UserRole)
            if not entry['protected']:
                item.setCheckState(0,Qt.CheckState.Checked if entry['default_selected'] else Qt.CheckState.Unchecked)

    def choose(self,checked):
        for index in range(self.tree.topLevelItemCount()):
            item=self.tree.topLevelItem(index)
            if not item.data(0,Qt.ItemDataRole.UserRole)['protected']:
                item.setCheckState(0,Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def delete(self):
        paths=[self.tree.topLevelItem(index).data(0,Qt.ItemDataRole.UserRole)['path'] for index in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(index).checkState(0)==Qt.CheckState.Checked]
        if not paths:
            return
        if QMessageBox.question(self,'Delete Local Packages',f'Delete these {len(paths)} local package copies?\n\n'+'\n'.join(str(path) for path in paths),QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
            return
        try:
            removed=self.workspace.shared_store().delete_local(paths,self.workspace.current_bundle_dir())
            self.status.setText(f'Deleted {len(removed)} local copies.')
        except (ValueError,OSError) as error:
            self.workspace.report_error('Clean Local Packages',str(error))
        self.refresh()


class SharedPackageActions:
    def install_shared_actions(self):
        self.shared_package_dir,self.shared_mode=None,'local'
        self.package_menu=self.menuBar().addMenu('&Package')
        self.open_action.setShortcut(QKeySequence())
        self.shared_open_action=self.action('Open Shared Package…',self.show_shared_packages,QKeySequence.StandardKey.Open)
        self.shared_close_action=self.action('Close Package',self.close_package)
        self.shared_update_action=self.action('Update Shared Package',self.update_shared_package,'Ctrl+U')
        self.shared_release_action=self.action('Release Shared Package Lock',self.release_shared_lock)
        self.package_menu.addActions([self.shared_open_action,self.shared_close_action])
        self.package_menu.addSeparator()
        self.package_menu.addAction(self.shared_update_action)
        self.package_menu.addAction(self.action('Check Shared Folder Sync…',self.check_shared_sync))
        self.package_menu.addSeparator()
        self.package_menu.addAction(self.shared_release_action)
        self.package_menu.addAction(self.action('Manual Shared Package Unlock…',lambda:self.show_shared_packages(unlock=True)))
        advanced=self.package_menu.addMenu('Advanced')
        advanced.addActions([self.bundle_action,self.open_action])
        advanced.addSeparator()
        advanced.addAction(self.action('Clean Local Packages…',self.show_cleanup))
        self.package_menu.aboutToShow.connect(self.update_shared_actions)

    def shared_store(self):
        settings=self.comms.settings
        return SharedPackages(settings.shared_dir,settings.work_dir,dict(user=getpass.getuser(),displayName=str(settings.get('user_name') or getpass.getuser()),host=socket.gethostname()))

    def current_bundle_dir(self):
        return self.session.bundle.get('root') if self.session else None

    def update_shared_actions(self):
        if not hasattr(self,'shared_close_action'):
            return
        busy=self.package_busy()
        self.shared_close_action.setEnabled(bool(self.session) and not busy)
        self.shared_update_action.setEnabled(self.shared_mode=='edit' and bool(self.current_bundle_dir()) and not busy)
        self.shared_release_action.setEnabled(bool(self.shared_package_dir) and not busy)
        self.shared_open_action.setEnabled(not busy)
        if hasattr(self,'get_packages_action'):
            self.get_packages_action.setEnabled(not busy)
        for action in (self.save_action,self.save_as_action):
            action.setEnabled(bool(self.session) and not busy and self.shared_mode!='testing')
        self.update_package_status()

    def show_shared_packages(self,*,unlock=False):
        self.shared_picker=SharedPicker(self,unlock)
        self.shared_picker.show()

    def show_cleanup(self):
        self.cleanup_dialog=CleanupDialog(self)
        self.cleanup_dialog.show()

    def open_shared_entry(self,entry,mode=None):
        if self.package_busy():
            return False
        store=self.shared_store()
        try:
            entry=store.entry(entry['package_dir'])
            if not entry or entry['unavailable_reason']:
                raise ValueError('This shared package version is unavailable.')
            lock=entry.get('lock')
            if mode!='testing' and lock and not store.owned(lock,store.owner):
                if QMessageBox.question(self,'Open Shared Package','This version is locked by another user. Open a local testing copy?',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                    return False
                mode='testing'
            if mode!='testing' and lock and store.owned(lock,store.owner):
                resume=store.resume_path(entry)
                if resume and QMessageBox.question(self,'Resume Shared Edit',f'Resume your existing local edit copy?\n\n{resume}',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                    if self.current_bundle_dir() and self.current_bundle_dir().resolve()==resume.resolve():
                        return True
                    return self.open_package(resume)
            if mode is None:
                mode='edit' if QMessageBox.question(self,'Open Shared Package','Lock this version for edit? Choose No to open a testing copy.',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes else 'testing'
            if not self.confirm_discard() or not self.prepare_shared_exit():
                return False
            if mode=='edit' and not self.require_shared_sync('create this shared package lock'):
                return False
            local=store.open_copy(entry,mode)
            session=PackageSession.open(local)
            self.editor=None
            self.set_session(session)
            self.shared_package_dir,self.shared_mode=entry['package_dir'],mode
            self.remember_package_session()
            self.settings.setValue('lastDirectory',str(local))
            self.update_shared_actions()
            self.statusBar().showMessage('Opened '+entry['package_name']+' '+entry['version_name']+' ('+mode+')',5000)
            return True
        except (OSError,ValueError) as error:
            self.report_error('Open Shared Package',str(error))
            return False

    def update_shared_package(self,*,release=None):
        if self.shared_mode!='edit' or not self.shared_package_dir:
            self.report_error('Update Shared Package','Open a shared package for edit before updating it.')
            return False
        try:
            self.flush_properties()
            if self.editor.dirty and not self.save_package():
                return False
            if not self.require_shared_sync('update this shared package'):
                return False
            if release is None:
                release=False if self.comms.settings.get('retain_lock_after_shared_update') else QMessageBox.question(self,'Update Shared Package','Release the edit lock after updating the shared version?',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
            self.shared_store().publish(self.current_bundle_dir(),self.shared_package_dir,release=release)
            if release:
                self.shared_mode='testing'
            self.update_shared_actions()
            self.statusBar().showMessage('Shared package updated; lock '+('released' if release else 'retained')+'.',5000)
            return True
        except (OSError,ValueError) as error:
            self.report_error('Update Shared Package',str(error))
            return False

    def warn_unshared(self,action):
        if self.shared_mode=='edit' and self.shared_package_dir and not self.shared_store().matches(self.current_bundle_dir(),self.shared_package_dir):
            return QMessageBox.question(self,'Unshared Local Changes',f'The local edit copy differs from shared storage. {action} leaves these changes in this local folder:\n\n{self.current_bundle_dir()}\n\nContinue without updating shared storage?',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
        return True

    def prepare_shared_exit(self):
        if not self.shared_package_dir or not self.current_bundle_dir():
            return True
        store=self.shared_store()
        if self.shared_mode=='edit' and not store.matches(self.current_bundle_dir(),self.shared_package_dir):
            answer=QMessageBox.question(self,'Close Shared Package','This local edit copy differs from shared storage. Update the shared version before continuing?',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if answer==QMessageBox.StandardButton.Cancel:
                return False
            if answer==QMessageBox.StandardButton.Yes:
                return self.update_shared_package()
            if not self.warn_unshared('Closing this package'):
                return False
        try:
            entry=store.entry(self.shared_package_dir)
            if entry and entry.get('lock') and store.owned(entry['lock'],store.owner):
                if QMessageBox.question(self,'Close Shared Package','Release your edit lock before continuing?',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                    if not self.require_shared_sync('release this shared package lock'):
                        return False
                    store.release(entry,expected=entry['lock'])
                    self.shared_mode='testing'
                    self.update_shared_actions()
            return True
        except (OSError,ValueError) as error:
            self.report_error('Close Shared Package',str(error))
            return False

    def unlock_shared_entry(self,entry):
        store=self.shared_store()
        try:
            entry=store.entry(entry['package_dir'])
            if not entry or not entry.get('lock'):
                return True
            lock=entry['lock']
            owner=lock.get('owner',{})
            if QMessageBox.question(self,'Manual Shared Package Unlock',f"Release the lock held by {owner.get('displayName') or owner.get('user')} on {owner.get('host')}?\n\nContinue only after confirming that the owner is no longer editing.",QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                return False
            if not self.warn_unshared('Releasing this lock') or not self.require_shared_sync('release this shared package lock'):
                return False
            store.release(entry,force=True,expected=lock)
            if self.shared_package_dir==entry['package_dir']:
                self.shared_mode='testing'
                self.update_shared_actions()
            return True
        except (OSError,ValueError) as error:
            self.report_error('Shared Package Unlock',str(error))
            return False

    def release_shared_lock(self):
        if not self.shared_package_dir:
            return
        store=self.shared_store()
        try:
            entry=store.entry(self.shared_package_dir)
            if not entry or not entry.get('lock'):
                return
            if store.owned(entry['lock'],store.owner):
                if not self.warn_unshared('Releasing this lock') or not self.require_shared_sync('release this shared package lock'):
                    return
                store.release(entry,expected=entry['lock'])
                self.shared_mode='testing'
                self.update_shared_actions()
            elif not self.unlock_shared_entry(entry):
                return
            if QMessageBox.question(self,'Shared Lock Released','Close this package now?',QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                self.close_package()
        except (OSError,ValueError) as error:
            self.report_error('Release Shared Package Lock',str(error))

    def close_package(self):
        if self.package_busy() or not self.confirm_discard() or not self.prepare_shared_exit():
            return False
        empty=PackageSession.from_payload({'$$Id':'(none)','Documents':[],'Fields':[]})
        self.set_session(empty)
        self.session=self.editor=None
        self.shared_package_dir,self.shared_mode=None,'local'
        self.content.refresh_fields()
        self.setWindowTitle('ATool Qt[*]')
        self.update_package_status()
        self.update_actions()
        self.update_shared_actions()
        if hasattr(self,'cleanup_dialog'):
            self.cleanup_dialog.refresh()
        return True
