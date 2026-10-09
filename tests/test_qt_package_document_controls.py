"""Integrated package condition controls, refresh, and catalog filtering."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from atool_qt.occs import CommandResult, CommsService
from atool_qt.package_documents import CatalogDialog, PackageConditionDialog
from atool_qt.session import PackageSession
from atool_qt.shared_packages import encode
from atool_qt.user_settings import UserSettings


class PackageDocumentControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.window=WorkspaceWindow(QSettings(str(self.root/'qt.ini'),QSettings.Format.IniFormat))
        settings=UserSettings(self.root/'user.json');settings.payload['application']['confirm_on_quit']=False
        self.window.comms.settings=settings
        bundle=self.root/'bundle';bundle.mkdir()
        values={'occs-package.json':{'schemaVersion':'occs-package-bundle/v1','package':{'shortName':'Pkg'},'version':{'shortName':'1'},'files':{}},
                'assembly-template.json':{'Documents':[{'$$Id':'Doc','Condition':'$[?(@.flag == true)]','Layouts':[]}],'Fields':[]},
                'version-master.json':{},'document-associations.json':{'associations':[{'documentShortName':'Doc','documentConfigUuid':'uuid-doc','documentRelIndex':1},{'documentShortName':'Ghost','documentConfigUuid':'uuid-ghost','documentRelIndex':2}]}}
        for name,value in values.items():(bundle/name).write_bytes(encode(value))
        session=PackageSession.open(bundle)
        session.map_data({'flag':True},'fixture')
        self.window.set_session(session)
        self.window.documents.matched_only.setChecked(False)
        self.window.select_name(self.window.documents,'Doc')
        self.addCleanup(self.close)
    def close(self):
        self.window.editor.saved=self.window.editor.snapshot()
        self.window.close()

    def test_condition_dialog_applies_valid_condition_refreshes_mapping_undo_and_keeps_tabs(self):
        self.window.package_actions['Edit Package Condition'].trigger()
        dialog=self.window.package_condition_dialog
        dialog.condition.setPlainText('$[?(@.flag == false)]')
        dialog.apply()
        self.assertEqual(self.window.session.documents[0]['condition'],'$[?(@.flag == false)]')
        self.assertFalse(self.window.session.documents[0]['triggered'])
        self.assertTrue(self.window.editor.dirty)
        self.assertEqual(len(self.window.editor.undo_stack),1)
        self.assertEqual([self.window.documents.tabs.tabText(index) for index in range(3)],['Properties','Source JSON','Match Details'])
        self.window.undo_change()
        self.assertTrue(self.window.session.documents[0]['triggered'])
        self.assertFalse(self.window.editor.dirty)
        dialog.reject()

    def test_invalid_warning_and_stale_condition_do_not_replace_source(self):
        dialog=PackageConditionDialog(self.window,self.window.selected_record('documents'))
        before=self.window.editor.snapshot()
        with patch.object(self.window,'report_error') as error:
            dialog.condition.setPlainText('@.flag == false');dialog.apply()
            error.assert_called_once()
        self.assertEqual(self.window.editor.snapshot(),before)
        with patch('atool_qt.package_documents.PayloadValidation._at_condition_validation_messages',return_value=([],['Review this'])),patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):
            dialog.condition.setPlainText('$[?(@.flag == false)]');dialog.apply()
        self.assertEqual(self.window.editor.snapshot(),before)
        self.window.editor.update_record(self.window.selected_record('documents'),{'Condition':''},'documents')
        with patch.object(self.window,'report_error') as error:dialog.apply()
        error.assert_called_once()
        self.assertEqual(self.window.session.documents[0]['condition'],'')
        dialog.reject()

    def test_refresh_retains_memory_edits_and_ghost_condition_button_disabled(self):
        self.window.documents.description.setPlainText('Pending description')
        self.window.package_actions['Refresh'].trigger()
        self.assertEqual(self.window.session.documents[0]['descr'],'Pending description')
        self.assertTrue(self.window.editor.dirty)
        history=copy.deepcopy(self.window.editor.undo_stack)
        self.window.package_actions['Refresh'].trigger()
        self.assertEqual(self.window.editor.undo_stack,history)
        self.window.select_name(self.window.documents,'Ghost')
        self.assertFalse(self.window.package_actions['Edit Package Condition'].isEnabled())

    def test_catalog_fuzzy_filter_hidden_selection_and_json_contract(self):
        cache=self.root/'catalog.json';cache.write_bytes(encode({'documents':[{'uuid':'a','shortName':'Bill','name':'Electric Bill','description':'Customer statement'}, {'uuid':'b','shortName':'Welcome','name':'Welcome','description':'Greeting'}]}))
        dialog=CatalogDialog(self.window.comms,cache,parent=self.window)
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
        dialog.search.setText('statement electric')
        self.assertFalse(dialog.tree.topLevelItem(0).isHidden())
        dialog.search.setText('welcome')
        self.assertIsNone(dialog.selected_document)
        self.assertFalse(dialog.add_button.isEnabled())
        self.assertTrue(dialog.search.isClearButtonEnabled())
        with patch.object(self.window.comms,'submit') as submit:
            dialog.refresh_catalog()
            self.assertIn('--json',submit.call_args.args[0])
            self.assertEqual(submit.call_args.args[0][-2:],['--name','welcome'])
        dialog.refresh_finished(CommandResult(0,'not json','',None))
        self.assertIn('valid JSON',dialog.status.text())
        dialog.job=None;dialog.reject()

    def test_catalog_add_associate_remove_buttons_update_integrated_documents(self):
        from PySide6.QtCore import QTimer
        from test_qt_bundle import make_bundle
        bundle = self.root / 'catalog-bundle'
        bundle.mkdir()
        self.window.set_session(make_bundle(bundle))
        cache = self.root / 'choices.json'
        cache.write_bytes(encode({'documents': [
            {'uuid': 'uuid-local', 'shortName': 'Local', 'name': 'Local document', 'description': 'Associate AT document'},
            {'uuid': 'uuid-new', 'shortName': 'New', 'name': 'New document', 'description': 'Package only'}]}))
        original_dialog = CatalogDialog
        chosen = []
        def choose_dialog(service, associate_name='', parent=None):
            dialog = original_dialog(service, cache, associate_name, parent)
            target = associate_name or 'New'
            def accept():
                item = next(dialog.tree.topLevelItem(index) for index in range(dialog.tree.topLevelItemCount()) if dialog.tree.topLevelItem(index).text(0) == target)
                dialog.tree.setCurrentItem(item)
                self.assertTrue(dialog.add_button.isEnabled())
                chosen.append(dialog.add_button.text())
                dialog.add_button.click()
            QTimer.singleShot(0, accept)
            return dialog
        window = self.window
        controls = {action.text(): window.documents.package_toolbar.widgetForAction(action) for action in window.documents.package_toolbar.actions()}
        window.select_name(window.documents, 'Local')
        with patch('atool_qt.package_documents.CatalogDialog', side_effect=choose_dialog):
            controls['Associate'].click()
        self.assertTrue(window.selected_record('documents')['associated'])
        self.assertEqual(window.selected_record('documents')['name'], 'Local')
        with patch('atool_qt.package_documents.CatalogDialog', side_effect=choose_dialog):
            controls['Add Package Document'].click()
        self.assertEqual(chosen, ['Associate', 'Add'])
        record = window.selected_record('documents')
        self.assertEqual(record['name'], 'New')
        self.assertTrue(record['in_at'])
        self.assertTrue(record['associated'])
        before = [row['name'] for row in window.session.documents]
        controls['Move Up'].click()
        self.assertNotEqual(before, [row['name'] for row in window.session.documents])
        controls['Move Down'].click()
        self.assertEqual(before, [row['name'] for row in window.session.documents])
        with patch('atool_qt.package_documents.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            controls['Remove Association'].click()
        self.assertIn('New', [row['name'] for row in window.session.documents])
        with patch('atool_qt.package_documents.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            controls['Remove Association'].click()
        removed = next(row for row in window.session.documents if row['name'] == 'New')
        self.assertFalse(removed['associated'])
        self.assertTrue(removed['in_at'])
        window.undo_action.trigger()
        self.assertTrue(next(row for row in window.session.documents if row['name'] == 'New')['associated'])
