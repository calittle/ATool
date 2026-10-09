"""Original lock/baseline/history protocol, with no real shared-folder mutation."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from atool_qt.shared_packages import SharedPackages, bundle_hashes, encode, json_object


class SharedPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = SharedPackages(self.root/'shared', self.root/'work', dict(user='alice', displayName='Alice', host='host-a'))
        self.original = self.root/'download'
        self.original.mkdir()
        values = {'occs-package.json': dict(schemaVersion='occs-package-bundle/v1', package={'shortName':'Bill'}, version={'shortName':'1.0'}, files={}, extra='preserved'),
                  'assembly-template.json': {'$$Id':'Bill', 'Documents':[], 'Fields':[]},
                  'version-master.json': {'unknown':'preserved'}, 'document-associations.json': {'associations':[]}}
        for name, value in values.items():
            (self.original/name).write_bytes(encode(value))
        self.entry = self.store.publish(self.original, initial=True, reason='downloadedFromComms')

    def test_schema_hashes_listing_and_testing_copy(self):
        entries = self.store.entries()
        self.assertEqual(('Bill','1.0'), (entries[0]['package_name'], entries[0]['version_name']))
        local = self.store.open_copy(self.entry, 'testing')
        baseline = json_object(local/self.store.BASELINE)
        self.assertEqual('atool-shared-baseline/v1', baseline['schemaVersion'])
        self.assertEqual('opened-testing', baseline['reason'])
        self.assertEqual(bundle_hashes(self.original), baseline['sharedHashes'])
        self.assertEqual('preserved', json_object(local/'occs-package.json')['extra'])
        self.assertFalse(self.store.lock_path(self.entry['package_dir']).exists())
        self.assertTrue(self.store.matches(local, self.entry['package_dir']))
        at = local/'assembly-template.json'
        at.write_text(json.dumps(json_object(at), indent=8))
        self.assertTrue(self.store.matches(local, self.entry['package_dir']))

    def test_edit_lock_resume_update_history_and_release(self):
        local = self.store.open_copy(self.entry, 'edit')
        entry = self.store.entry(self.entry['package_dir'])
        lock = entry['lock']
        self.assertEqual('atool-shared-lock/v1', lock['schemaVersion'])
        self.assertEqual(str(local), lock['bundleDir'])
        self.assertEqual(local, self.store.resume_path(entry))
        self.assertEqual((entry['package_dir'],'edit'), self.store.restore_context(local))
        for index in range(7):
            at = local/'assembly-template.json'
            value = json_object(at)
            value['edit'] = index
            at.write_bytes(encode(value))
            entry = self.store.publish(local, entry['package_dir'])
            self.assertEqual(lock['createdAt'], entry['lock']['createdAt'])
            self.assertTrue(self.store.matches(local, entry['package_dir']))
        history = entry['package_dir']/'published'/'history'
        self.assertEqual(5, len(list(history.iterdir())))
        self.assertEqual('updatedShared', json_object(local/self.store.BASELINE)['reason'])
        self.store.release(entry, expected=entry['lock'])
        self.assertEqual((entry['package_dir'],'testing'), self.store.restore_context(local))

    def test_foreign_lock_blocks_edits_and_initial_publish_but_testing_works(self):
        other = SharedPackages(self.store.shared_dir, self.root/'other', dict(user='bob',host='host-b'))
        local = self.store.open_copy(self.entry, 'edit')
        for action in (lambda:other.open_copy(self.entry,'edit'), lambda:other.publish(self.original,initial=True), lambda:other.release(self.entry)):
            with self.assertRaises(ValueError):
                action()
        testing = other.open_copy(self.entry, 'testing')
        self.assertTrue(testing.exists())
        self.assertTrue(local.exists())

    def test_stale_baseline_and_other_local_session_cannot_overwrite(self):
        local = self.store.open_copy(self.entry,'edit')
        published = self.entry['published_dir']/'assembly-template.json'
        published.write_bytes(encode({'$$Id':'Bill','Documents':[],'Fields':[], 'externalChange':True}))
        with self.assertRaisesRegex(ValueError, 'older shared'):
            self.store.publish(local,self.entry['package_dir'])
        second = self.store.open_copy(self.entry,'edit')
        with self.assertRaisesRegex(ValueError,'different local session'):
            self.store.publish(local,self.entry['package_dir'])
        self.assertTrue(self.store.matches(second,self.entry['package_dir']))

    def test_failed_copy_releases_new_lock_and_failed_publication_restores_current(self):
        with patch('atool_qt.shared_packages.shutil.copytree', side_effect=OSError('Injected copy failure')):
            with self.assertRaises(OSError):
                self.store.open_copy(self.entry,'edit')
        self.assertFalse(self.store.lock_path(self.entry['package_dir']).exists())
        local = self.store.open_copy(self.entry,'edit')
        current = bundle_hashes(self.entry['published_dir'])
        baseline = (local/self.store.BASELINE).read_bytes()
        at=local/'assembly-template.json'
        at.write_bytes(encode({'$$Id':'Bill','Documents':[],'Fields':[],'change':1}))
        with patch('atool_qt.shared_packages.write_files', side_effect=OSError('Injected metadata failure')):
            with self.assertRaises(OSError):
                self.store.publish(local,self.entry['package_dir'])
        self.assertEqual(current,bundle_hashes(self.entry['published_dir']))
        self.assertEqual(baseline,(local/self.store.BASELINE).read_bytes())
        self.assertEqual(1,len(list((self.entry['package_dir']/'published'/'history').iterdir())))

    def test_cleanup_protects_open_locked_and_symlinked_folders_and_rechecks(self):
        locked=self.store.open_copy(self.entry,'edit')
        current=self.store.open_copy(self.entry,'testing')
        removable=self.store.open_copy(self.entry,'testing')
        (self.store.work_dir/'linked').symlink_to(self.original, target_is_directory=True)
        entries=self.store.cleanup_entries(current)
        self.assertEqual(3,len(entries))
        self.assertTrue(next(item for item in entries if item['path']==locked)['protected'])
        self.assertTrue(next(item for item in entries if item['path']==current)['protected'])
        for path in (locked,current,self.store.work_dir/'linked'):
            with self.assertRaises(ValueError):
                self.store.delete_local([path],current)
        self.assertEqual([removable],self.store.delete_local([removable],current))
        self.assertTrue(self.original.exists())

    def test_corrupt_locks_and_missing_referenced_files_are_rejected(self):
        lock=self.store.lock_path(self.entry['package_dir'])
        lock.parent.mkdir(parents=True,exist_ok=True)
        lock.write_text('not-json')
        with self.assertRaises(ValueError):
            self.store.entry(self.entry['package_dir'])
        value=json_object(self.original/'occs-package.json')
        value['files']={'assemblyTemplate':'../outside.json'}
        (self.original/'occs-package.json').write_bytes(encode(value))
        with self.assertRaises(FileNotFoundError):
            bundle_hashes(self.original)

    def test_external_absolute_files_are_copied_and_remain_independent(self):
        from atool_qt.shared_packages import bundle_paths
        from atool_qt.session import PackageSession
        external = self.root / 'external'
        external.mkdir()
        value = json_object(self.original / 'occs-package.json')
        value['files'] = {}
        for key, filename in (('assemblyTemplate', 'assembly-template.json'), ('versionMaster', 'version-master.json'), ('documentAssociations', 'document-associations.json')):
            destination = external / filename
            destination.write_bytes((self.original / filename).read_bytes())
            value['files'][key] = str(destination)
        value['bundlePath'] = str(self.original)
        (self.original / 'occs-package.json').write_bytes(encode(value))
        original_bytes = (self.original / 'occs-package.json').read_bytes()
        entry = self.store.publish(self.original, initial=True)
        self.assertEqual((self.original / 'occs-package.json').read_bytes(), original_bytes)
        self.assertTrue(self.store.matches(self.original, entry['package_dir']))
        local = self.store.open_copy(entry, 'edit')
        for path in bundle_paths(local, json_object(local / 'occs-package.json')).values():
            self.assertTrue(path.is_relative_to(local.resolve()))
        import shutil
        shutil.rmtree(external)
        session = PackageSession.open(local)
        self.assertEqual(session.name, 'Bill')
        self.assertTrue(self.store.matches(local, entry['package_dir']))
        template = local / 'assembly-template.json'
        edited = json_object(template)
        edited['PortableEdit'] = True
        template.write_bytes(encode(edited))
        entry = self.store.publish(local, entry['package_dir'])
        self.assertTrue(json_object(entry['published_dir'] / 'assembly-template.json')['PortableEdit'])

    def test_absolute_internal_and_parent_relative_references_become_portable(self):
        from atool_qt.shared_packages import copy_bundle_files, bundle_paths
        value = json_object(self.original / 'occs-package.json')
        value['files'] = {'assemblyTemplate': str(self.original / 'assembly-template.json'),
                          'versionMaster': '../download/version-master.json'}
        (self.original / 'occs-package.json').write_bytes(encode(value))
        target = self.root / 'copy'
        copy_bundle_files(self.original, target)
        copied = json_object(target / 'occs-package.json')
        self.assertEqual(copied['files']['assemblyTemplate'], 'assembly-template.json')
        self.assertEqual(copied['files']['versionMaster'], 'version-master.json')
        self.assertTrue(all(path.is_relative_to(target.resolve()) for path in bundle_paths(target, copied).values()))


class SharedPackageInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from PySide6.QtCore import QSettings
        from atool_qt.window import WorkspaceWindow
        from atool_qt.user_settings import UserSettings
        from atool_qt.session import demo_session
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.window=WorkspaceWindow(QSettings(str(self.root/'qt.ini'),QSettings.Format.IniFormat))
        settings=UserSettings(self.root/'user.json')
        settings.payload['application']['confirm_on_quit']=False
        settings.payload['occs'].update(shared_workspace_dir=str(self.root/'shared'),work_dir=str(self.root/'work'),retain_lock_after_shared_update=True)
        self.window.comms.settings=settings
        self.window.set_session(demo_session())
        source=self.root/'original'
        source.mkdir()
        values={'occs-package.json':dict(schemaVersion='occs-package-bundle/v1',package={'shortName':'Invoice'},version={'shortName':'1'},files={}),
                'assembly-template.json':{'$$Id':'Invoice','Documents':[{'$$Id':'DOC','Condition':'','Layouts':[]}],'Fields':[]},
                'version-master.json':{},'document-associations.json':{'associations':[]}}
        for name,value in values.items():
            (source/name).write_bytes(encode(value))
        self.entry=self.window.shared_store().publish(source,initial=True,reason='downloadedFromComms')
        self.errors=[]
        reporter=patch.object(self.window,'report_error',side_effect=lambda title,message:self.errors.append((title,message)))
        reporter.start()
        self.addCleanup(reporter.stop)
        self.addCleanup(self.close)

    def close(self):
        self.window.shared_package_dir=None
        self.window.shared_mode='local'
        if self.window.editor:
            self.window.editor.saved=self.window.editor.snapshot()
        self.window.close()

    def test_reopening_same_bundle_refreshes_file_baseline_after_external_format_change(self):
        window=self.window
        root=self.root/'original'
        self.assertTrue(window.open_package(root))
        previous_editor=window.editor
        source=window.session.source
        source.write_text(json.dumps(json_object(source),indent=10))
        self.assertTrue(window.open_package(root))
        self.assertIsNot(window.editor,previous_editor)
        self.assertTrue(window.save_package())
        self.assertEqual(self.errors,[])

    def test_open_original_session_restores_bundle_alias_and_mapping_without_changing_original_state(self):
        window = self.window
        data = self.root / 'mapped.json'
        data.write_text('{"active":true}')
        state_path = self.root / '.atool.state.json'
        state = {'last_occs_bundle': str(self.root / 'original'), 'last_occs_session_alias': 'legacy-prod', 'last_data_file': str(data), 'unknown': 123}
        state_path.write_bytes(encode(state))
        before = state_path.read_bytes()
        with patch.object(window, 'map_file') as mapper:
            window.open_last_session()
            mapper.assert_called_once_with(data)
        self.assertEqual(window.current_bundle_dir().resolve(), (self.root / 'original').resolve())
        self.assertEqual(window.comms.settings.get('session_alias'), 'legacy-prod')
        self.assertEqual(window.settings.value('lastSessionAlias'), 'legacy-prod')
        self.assertEqual(state_path.read_bytes(), before)

    def test_qt_session_takes_precedence_and_restores_its_alias(self):
        window = self.window
        self.assertTrue(window.open_package(self.root / 'original'))
        window.settings.setValue('lastSessionAlias', 'saved-qt')
        window.comms.settings.payload['occs']['session_alias'] = 'current'
        (self.root / '.atool.state.json').write_bytes(encode({'last_occs_bundle': 'missing', 'last_occs_session_alias': 'legacy'}))
        window.open_last_session()
        self.assertEqual(window.comms.settings.get('session_alias'), 'saved-qt')
        self.assertEqual(window.current_bundle_dir().resolve(), (self.root / 'original').resolve())

    def test_missing_original_session_and_busy_session_do_not_change_alias(self):
        from PySide6.QtWidgets import QMessageBox
        window = self.window
        window.comms.settings.payload['occs']['session_alias'] = 'current'
        (self.root / '.atool.state.json').write_bytes(encode({'last_occs_bundle': str(self.root / 'missing'), 'last_occs_session_alias': 'legacy'}))
        window.open_last_session()
        self.assertEqual(window.comms.settings.get('session_alias'), 'current')
        self.assertTrue(self.errors)
        with patch.object(window, 'package_busy', return_value=True), patch.object(window, 'open_package') as opener:
            window.open_last_session()
            opener.assert_not_called()
        (self.root / '.atool.state.json').write_text('not JSON')
        with patch.object(QMessageBox, 'information') as info:
            window.open_last_session()
            info.assert_called_once()

    def test_external_template_open_session_restores_manifest_context_and_mru(self):
        window = self.window
        root = self.root / 'external-bundle'
        root.mkdir()
        import shutil
        shutil.copytree(self.root / 'original', root, dirs_exist_ok=True)
        external = self.root / 'outside-template.json'
        (root / 'assembly-template.json').rename(external)
        value = json_object(root / 'occs-package.json')
        value['files']['assemblyTemplate'] = str(external)
        (root / 'occs-package.json').write_bytes(encode(value))
        self.assertTrue(window.open_package(root))
        self.assertEqual(window.settings.value('lastPackageManifest'), str((root / 'occs-package.json').resolve()))
        self.assertEqual(window.comms.settings.get('package_mru')[0]['package'], 'Invoice')
        window.set_session(__import__('atool_qt.session', fromlist=['demo_session']).demo_session())
        window.open_last_session()
        self.assertEqual(window.current_bundle_dir().resolve(), root.resolve())
        self.assertEqual(window.session.source.resolve(), external.resolve())
        self.assertEqual(len(window.comms.settings.get('package_mru')), 1)

    def test_shared_save_as_clears_context_and_retains_resumable_original_lock(self):
        from PySide6.QtWidgets import QFileDialog
        window = self.window
        with patch.object(window, 'require_shared_sync', return_value=True):
            self.assertTrue(window.open_shared_entry(self.entry, 'edit'))
        local = window.current_bundle_dir()
        original = window.session.source.read_bytes()
        copy_path = self.root / 'standalone.json'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(copy_path), 'JSON')):
            self.assertTrue(window.save_package(save_as=True))
        self.assertIsNone(window.shared_package_dir)
        self.assertEqual(window.shared_mode, 'local')
        self.assertEqual(window.session.bundle, {})
        self.assertFalse(window.shared_release_action.isEnabled())
        self.assertEqual(window.settings.value('lastPackageManifest'), '')
        entry = window.shared_store().entry(self.entry['package_dir'])
        self.assertEqual(Path(entry['lock']['bundleDir']).resolve(), local.resolve())
        self.assertEqual((local / 'assembly-template.json').read_bytes(), original)
        window.open_last_session()
        self.assertEqual(window.session.source, copy_path.resolve())
        self.assertEqual(window.session.bundle, {})

    def test_cleanup_multiselect_space_toggle_and_refresh_preserve_choices(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from atool_qt.shared_actions import CleanupDialog
        window = self.window
        store = window.shared_store()
        protected = store.open_copy(self.entry, 'edit')
        first = store.open_copy(self.entry, 'testing')
        second = store.open_copy(self.entry, 'testing')
        dialog = CleanupDialog(window)
        dialog.show()
        self.addCleanup(dialog.close)
        items = {item.data(0,Qt.ItemDataRole.UserRole)['path'].resolve(): item for item in (dialog.tree.topLevelItem(index) for index in range(dialog.tree.topLevelItemCount()))}
        for path in (protected, first, second):
            items[path.resolve()].setSelected(True)
        dialog.tree.setFocus()
        self.app.processEvents()
        QTest.keyClick(dialog.tree, Qt.Key.Key_Space)
        self.assertEqual(items[first.resolve()].checkState(0), Qt.CheckState.Checked)
        self.assertEqual(items[second.resolve()].checkState(0), Qt.CheckState.Checked)
        self.assertEqual(items[protected.resolve()].checkState(0), Qt.CheckState.Unchecked)
        self.assertIn('Selected: 2 of 2', dialog.status.text())
        dialog.refresh()
        self.assertEqual(len(dialog.tree.selectedItems()), 3)
        self.assertEqual(sum(item.checkState(0)==Qt.CheckState.Checked for item in dialog.tree.selectedItems()), 2)
        dialog.toggle_selected()
        self.assertTrue(all(item.checkState(0)==Qt.CheckState.Unchecked for item in dialog.tree.selectedItems()))
        from PySide6.QtWidgets import QPushButton, QMessageBox
        import time
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        buttons['Select Removable'].click()
        self.assertIn('Selected: 2 of 2', dialog.status.text())
        buttons['Select None'].click()
        self.assertIn('Selected: 0 of 2', dialog.status.text())
        old = time.time() - 15 * 86400
        for path in [first, *first.rglob('*')]:
            os.utime(path, (old, old))
        buttons['Refresh'].click()
        buttons['Select Old'].click()
        self.assertIn('Selected: 1 of 2', dialog.status.text())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            buttons['Delete Selected…'].click()
        self.assertTrue(first.exists())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            buttons['Delete Selected…'].click()
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertTrue(protected.exists())
        dialog.close()
        self.assertFalse(dialog.isVisible())

    def test_failed_shared_save_as_keeps_active_context_and_last_session(self):
        from PySide6.QtWidgets import QFileDialog
        window = self.window
        with patch.object(window, 'require_shared_sync', return_value=True):
            self.assertTrue(window.open_shared_entry(self.entry, 'edit'))
        context = window.shared_package_dir
        source = window.settings.value('lastPackageManifest')
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(self.root / 'copy.json'), 'JSON')), patch.object(window.editor, 'save', side_effect=OSError('Write failed')):
            self.assertFalse(window.save_package(save_as=True))
        self.assertEqual(window.shared_package_dir, context)
        self.assertEqual(window.shared_mode, 'edit')
        self.assertEqual(window.settings.value('lastPackageManifest'), source)

    def test_open_edit_update_and_close_controls_clear_workspace(self):
        from PySide6.QtWidgets import QMessageBox
        window=self.window
        with patch.object(window,'require_shared_sync',return_value=True):
            self.assertTrue(window.open_shared_entry(self.entry,'edit'))
        local=window.current_bundle_dir()
        self.assertNotEqual(self.entry['published_dir'],local)
        self.assertEqual('edit',window.shared_mode)
        self.assertTrue(window.shared_update_action.isEnabled())
        self.assertEqual('🔒 ✏️',window.editable_label.text().strip())
        window.editor.update_record(window.session.documents[0],{'Descr':'Updated locally'},'documents')
        window.refresh_edit()
        with patch.object(window,'require_shared_sync',return_value=True):
            self.assertTrue(window.update_shared_package())
        self.assertEqual('Updated locally',json_object(self.entry['published_dir']/'assembly-template.json')['Documents'][0]['Descr'])
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes),patch.object(window,'require_shared_sync',return_value=True):
            self.assertTrue(window.close_package())
        self.assertIsNone(window.session)
        self.assertIsNone(window.editor)
        self.assertEqual(0,window.documents.tree.topLevelItemCount())
        self.assertEqual(0,window.fields.tree.topLevelItemCount())
        self.assertEqual(0,window.layouts.tree.topLevelItemCount())
        self.assertFalse(window.save_action.isEnabled())
        self.assertFalse(window.map_action.isEnabled())
        self.assertFalse(window.shared_store().lock_path(self.entry['package_dir']).exists())

    def test_picker_testing_copy_session_restore_and_cleanup_dialog(self):
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import Qt
        window=self.window
        window.show_shared_packages()
        picker=window.shared_picker
        self.assertEqual(1,picker.tree.topLevelItemCount())
        picker.filter.setText('missing')
        self.assertTrue(picker.tree.topLevelItem(0).isHidden())
        picker.filter.clear()
        picker.tree.setCurrentItem(picker.tree.topLevelItem(0))
        with patch.object(window,'require_shared_sync',return_value=True):
            picker.select('testing')
        self.assertEqual('testing',window.shared_mode)
        self.assertFalse(window.shared_update_action.isEnabled())
        # An edit copy can be restored from baseline and its still-owned lock.
        with patch.object(window,'require_shared_sync',return_value=True):
            self.assertTrue(window.open_shared_entry(self.entry,'edit'))
        local=window.current_bundle_dir()
        window.shared_package_dir=None
        window.shared_mode='local'
        window.open_last_session()
        self.assertEqual(local,window.current_bundle_dir())
        self.assertEqual('edit',window.shared_mode)
        window.show_cleanup()
        dialog=window.cleanup_dialog
        protected=[dialog.tree.topLevelItem(index).data(0,Qt.ItemDataRole.UserRole) for index in range(dialog.tree.topLevelItemCount())]
        self.assertTrue(next(item for item in protected if item['path']==local)['protected'])
        dialog.choose(True)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            dialog.delete()
        self.assertTrue(local.exists())
        self.assertEqual(1,dialog.tree.topLevelItemCount())

    def test_sync_failure_and_stale_baseline_leave_session_and_shared_files_intact(self):
        window=self.window
        with patch.object(window,'require_shared_sync',return_value=False):
            self.assertFalse(window.open_shared_entry(self.entry,'edit'))
        self.assertNotEqual('Invoice',window.session.name)
        self.assertFalse(window.shared_store().lock_path(self.entry['package_dir']).exists())
        with patch.object(window,'require_shared_sync',return_value=True):
            self.assertTrue(window.open_shared_entry(self.entry,'edit'))
        path=self.entry['published_dir']/'assembly-template.json'
        value=json_object(path)
        value['external']=True
        path.write_bytes(encode(value))
        with patch.object(window,'report_error') as error,patch.object(window,'require_shared_sync',return_value=True):
            self.assertFalse(window.update_shared_package(release=False))
        self.assertIn('older shared',error.call_args.args[1])
        self.assertTrue(json_object(path)['external'])
        self.assertEqual('edit',window.shared_mode)


class SharedPackageFailureTests(unittest.TestCase):
    setUp = SharedPackageTests.setUp
    def test_release_failure_restores_shared_and_local_baseline(self):
        local=self.store.open_copy(self.entry,'edit')
        original=bundle_hashes(self.entry['published_dir'])
        baseline=(local/self.store.BASELINE).read_bytes()
        lock_path=self.store.lock_path(self.entry['package_dir'])
        lock_bytes=lock_path.read_bytes()
        at=local/'assembly-template.json'
        at.write_bytes(encode({'$$Id':'Bill','Documents':[],'Fields':[],'new':True}))
        actual_unlink=Path.unlink
        def fail_release(path,*args,**kwargs):
            if path==lock_path:
                raise OSError('Injected release failure')
            return actual_unlink(path,*args,**kwargs)
        with patch('pathlib.Path.unlink',new=fail_release):
            with self.assertRaises(OSError):
                self.store.publish(local,self.entry['package_dir'],release=True)
        self.assertEqual(original,bundle_hashes(self.entry['published_dir']))
        self.assertEqual(baseline,(local/self.store.BASELINE).read_bytes())
        self.assertEqual(lock_bytes,lock_path.read_bytes())

    def test_bundle_without_file_map_uses_original_default_paths(self):
        from atool_qt.session import PackageSession
        value=json_object(self.original/'occs-package.json')
        value.pop('files')
        (self.original/'occs-package.json').write_bytes(encode(value))
        session=PackageSession.open(self.original)
        self.assertEqual('Bill',session.name)
        self.assertEqual('1.0',session.bundle['manifest']['version']['shortName'])
        self.assertEqual(bundle_hashes(self.original)['assemblyTemplate'],bundle_hashes(self.entry['published_dir'])['assemblyTemplate'])

    def test_late_lock_prevents_cleanup_of_previously_removable_copy(self):
        local=self.store.open_copy(self.entry,'testing')
        self.assertFalse(next(item for item in self.store.cleanup_entries() if item['path']==local)['protected'])
        self.store.acquire(self.entry,local)
        with self.assertRaisesRegex(ValueError,'protected'):
            self.store.delete_local([local])
        self.assertTrue(local.is_dir())
