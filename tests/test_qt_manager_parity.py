"""Original manager path views and homogeneous layout clipboard workflows."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication
from atool_qt.editor import PackageEditor
from atool_qt.session import PackageSession
from atool_qt.user_settings import UserSettings


def session_fixture():
    return PackageSession.from_payload({'$$Id':'Pkg', 'Documents':[{'$$Id':'Doc','Layouts':[
        {'$$Id':'L1','Contents':[{'$$Id':'C1','Custom':'preserve','Iteration':{'$$Id':'I1','Path':'$.rows','Fields':[{'Name':'F1','Path':'$.value'}, {'Name':'F2','Path':'$.other'}]}}, {'$$Id':'C2'}]},
        {'Name':'L2','Contents':[]}, {'Id':'L3'}]}], 'Fields':[{'Name':'Amount','Path':'$.bill.amount','Mandatory':True}, {'Name':'Account','Path':'$.bill.account'}, {'Name':'AmountCopy','Path':'$.bill.amount'}]})


class ClipboardTests(unittest.TestCase):
    def test_layouts_insert_after_selected_ancestor_and_original_copy_names(self):
        session=session_fixture();editor=PackageEditor(session);doc=session.documents[0]
        clip=copy.deepcopy(doc['source']['Layouts'][:2])
        key=editor.paste_layout_items(doc,'Layout',clip,'layout/0/Contents/0/Iteration/Fields/0')
        self.assertEqual(key,'layout/1')
        self.assertEqual([item.get('$$Id') or item.get('Name') or item.get('Id') for item in session.documents[0]['source']['Layouts']],['L1','L1 Copy','L2 Copy','L2','L3'])
        self.assertEqual(len(editor.undo_stack),1)
        editor.undo();self.assertFalse(editor.dirty)
        editor.redo();self.assertEqual(len(session.documents[0]['source']['Layouts']),5)
        editor.paste_layout_items(session.documents[0],'Layout',clip,'layout/1')
        self.assertEqual(session.documents[0]['source']['Layouts'][2]['$$Id'],'L1 Copy 2')
        self.assertEqual(clip[0]['$$Id'],'L1')

    def test_content_and_fields_paste_after_sibling_with_unknown_keys(self):
        session=session_fixture();editor=PackageEditor(session);doc=session.documents[0]
        content=copy.deepcopy(doc['source']['Layouts'][0]['Contents'][0])
        key=editor.paste_layout_items(doc,'Content',[content],'layout/0/Contents/0')
        self.assertEqual(key,'layout/0/Contents/1')
        pasted=session.documents[0]['source']['Layouts'][0]['Contents'][1]
        self.assertEqual(pasted['$$Id'],'C1 Copy')
        self.assertEqual(pasted['Custom'],'preserve')
        doc=session.documents[0]
        fields=copy.deepcopy(doc['source']['Layouts'][0]['Contents'][0]['Iteration']['Fields'])
        key=editor.paste_layout_items(doc,'Field',fields,'layout/0/Contents/0/Iteration/Fields/0')
        self.assertEqual(key,'layout/0/Contents/0/Iteration/Fields/1')
        self.assertEqual([item['Name'] for item in session.documents[0]['source']['Layouts'][0]['Contents'][0]['Iteration']['Fields']],['F1','F1 Copy','F2 Copy','F2'])

    def test_iteration_pastes_once_and_invalid_destinations_do_not_change_model(self):
        session=session_fixture();editor=PackageEditor(session);doc=session.documents[0]
        iteration=copy.deepcopy(doc['source']['Layouts'][0]['Contents'][0]['Iteration'])
        before=editor.snapshot()
        for kind,key,clip in [('Iteration','layout/0/Contents/0',[iteration]),('Content',None,[{}]),('Field','layout/1',[{}]),('Iteration','layout/0/Contents/1',[iteration,iteration])]:
            with self.assertRaises(ValueError):editor.paste_layout_items(doc,kind,clip,key)
            self.assertEqual(editor.snapshot(),before)
        key=editor.paste_layout_items(doc,'Iteration',[iteration],'layout/0/Contents/1')
        self.assertEqual(key,'layout/0/Contents/1/Iteration')
        self.assertEqual(len(editor.undo_stack),1)
        self.assertEqual(session.documents[0]['source']['Layouts'][0]['Contents'][1]['Iteration'],iteration)

    def test_existing_lowercase_content_field_collections_are_used(self):
        session=session_fixture();doc=session.documents[0]
        layout=doc['source']['Layouts'][0];layout['content']=layout.pop('Contents')
        content=layout['content'][0];content['iteration']=content.pop('Iteration')
        iteration=content['iteration'];iteration['fields']=iteration.pop('Fields')
        editor=PackageEditor(session)
        key=editor.paste_layout_items(doc,'Field',[{'Name':'F1','Path':'$.value'}],'layout/0/content/0/Iteration')
        self.assertEqual(key,'layout/0/content/0/Iteration/fields/2')
        self.assertNotIn('Fields',iteration)
        editor.paste_layout_items(session.documents[0],'Content',[{'$$Id':'C1'}],'layout/0')
        self.assertNotIn('Contents',session.documents[0]['source']['Layouts'][0])


class ManagerInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.window=WorkspaceWindow(QSettings(str(root/'qt.ini'),QSettings.Format.IniFormat))
        settings=UserSettings(root/'user.json');settings.payload['application']['confirm_on_quit']=False
        self.window.comms.settings=settings
        self.window.set_session(session_fixture())
        self.addCleanup(self.close)
    def close(self):
        self.window.editor.saved=self.window.editor.snapshot()
        self.window.close()

    def test_field_path_view_groups_paths_preserves_selection_and_edits(self):
        panel=self.window.fields
        self.window.select_name(panel,'Amount')
        panel.field_view_toggle.click()
        self.assertEqual(panel.field_view,'path')
        self.assertEqual(len(list(panel.items())),3)
        self.assertEqual(panel.tree.topLevelItemCount(),1)
        self.assertEqual(panel.name.text(),'Amount')
        self.assertEqual(panel.path_hierarchy.text(),'$ > bill > amount')
        panel.name.setText('Charge');self.window.apply_record('fields')
        self.assertEqual(panel.name.text(),'Charge')
        panel.search.setText('account bill')
        visible=[item.text(0) for item in panel.items() if not item.isHidden()]
        self.assertEqual(visible,['Account'])
        self.assertFalse(panel.tree.topLevelItem(0).isHidden())
        panel.search.setText('missing');self.assertEqual(panel.count.text(),'0 of 3 fields')
        self.assertTrue(panel.tree.topLevelItem(0).isHidden())
        panel.search.clear()
        group=panel.tree.topLevelItem(0)
        panel.tree.setCurrentItem(group)
        self.assertIsNone(self.window.selected_record('fields'))
        self.window.apply_record('fields')
        panel.field_view_toggle.click()
        self.assertEqual(panel.field_view,'name')
        self.assertEqual(panel.tree.topLevelItemCount(),3)

    def test_multi_selection_clipboard_tree_order_child_copy_and_keyboard_controls(self):
        window=self.window
        window.select_layout_key('layout/1')
        items=list(window.layouts.items())
        for item in items:item.setSelected(False)
        for key in ('layout/1','layout/0'):
            next(item for item in items if item.data(0,Qt.ItemDataRole.UserRole)['key']==key).setSelected(True)
        window.copy_layout()
        self.assertEqual(window.layout_clipboard_kind,'Layout')
        self.assertEqual([item.get('$$Id') or item.get('Name') for item in window.layout_clipboard],['L1','L2'])
        window.paste_layout()
        layouts=window.session.documents[0]['source']['Layouts']
        self.assertEqual([item.get('$$Id') or item.get('Name') or item.get('Id') for item in layouts],['L1','L2','L1 Copy','L2 Copy','L3'])
        window.select_layout_key('layout/0/Contents/0')
        window.copy_layout();self.assertEqual(window.layout_clipboard_kind,'Content')
        window.paste_layout()
        self.assertEqual(window.layouts.name.text(),'C1 Copy')
        self.assertEqual({action.shortcut().toString() for action in window.layouts.tree.actions()},{'Ctrl+C','Ctrl+V','Del'})
        self.assertEqual(window.preview_action.shortcut().toString(),'Ctrl+P')
        self.assertEqual(window.email_action.shortcut().toString(),'Ctrl+E')

    def test_mixed_kind_copy_refuses_to_replace_clipboard(self):
        window=self.window
        window.select_layout_key('layout/0');window.copy_layout()
        before=copy.deepcopy(window.layout_clipboard)
        for key in ('layout/0','layout/0/Contents/0'):
            next(item for item in window.layouts.items() if item.data(0,Qt.ItemDataRole.UserRole)['key']==key).setSelected(True)
        with patch.object(window,'report_error') as error:window.copy_layout()
        error.assert_called_once()
        self.assertEqual(window.layout_clipboard,before)

    def test_document_toolbar_clear_mapping_preserves_edits_and_history(self):
        window=self.window
        window.session.map_data({'bill':{'amount':0,'account':False}},'Mapped fixture')
        window.set_session(window.session)
        window.select_name(window.fields,'Amount')
        window.fields.name.setText('Charge');window.apply_record('fields')
        before=window.editor.snapshot()
        history=copy.deepcopy(window.editor.undo_stack)
        self.assertEqual(window.document_map_action.text(),'Clear Map')
        window.document_map_action.trigger()
        self.assertFalse(window.session.mapped)
        self.assertIsNone(window.session.data)
        self.assertEqual(window.editor.snapshot(),before)
        self.assertEqual(window.editor.undo_stack,history)
        self.assertTrue(window.editor.dirty)
        self.assertEqual(window.document_map_action.text(),'Map')
        self.assertFalse(window.documents.matched_only.isEnabled())
        self.assertFalse(window.email_action.isEnabled())
        self.assertFalse(window.resolve_action.isEnabled())
        self.assertEqual(window.data.tree.topLevelItemCount(),0)
        self.assertTrue(all(not item.isHidden() for item in window.fields.items()))
        window.document_view_action.trigger()
        self.assertTrue(window.documents.hierarchy)
        self.assertEqual(window.document_view_action.text(),'Flat View')
        with patch.object(window,'choose_data') as choose:window.document_map_action.trigger()
        choose.assert_called_once()

    def test_context_and_transfer_guards_cover_manager_and_menu_controls(self):
        from types import SimpleNamespace
        window=self.window
        window.select_layout_key('layout/0/Contents/0')
        actions={action.text():action for action in window.layouts.authoring_toolbar.actions()}
        self.assertFalse(actions['Add Iteration'].isEnabled())
        self.assertFalse(actions['Add Field'].isEnabled())
        self.assertTrue(actions['Add Content'].isEnabled())
        window.select_layout_key('layout/0/Contents/0/Iteration')
        self.assertTrue(actions['Add Field'].isEnabled())
        self.assertFalse(actions['Up'].isEnabled())
        window.fields.toggle_field_view()
        window.fields.tree.setCurrentItem(window.fields.tree.topLevelItem(0))
        field_actions={action.text():action for action in window.fields.authoring_toolbar.actions()}
        self.assertFalse(field_actions['Remove'].isEnabled())
        self.assertFalse(field_actions['Apply'].isEnabled())
        window.package_download_jobs=[SimpleNamespace(done=False)]
        window.update_actions()
        self.assertFalse(window.map_action.isEnabled())
        self.assertFalse(window.convert_map_action.isEnabled())
        self.assertFalse(window.generate_action.isEnabled())
        self.assertFalse(window.model_actions['Generate all'].isEnabled())
        self.assertFalse(window.document_model_action.isEnabled())
        with patch('atool_qt.window.MappingJob') as job:window.map_file(Path('ignored.json'))
        job.assert_not_called()
        window.package_download_jobs=[]
        window.update_actions()

    def test_properties_follow_group_missing_and_no_selection_without_changing_payload(self):
        window=self.window
        before=copy.deepcopy(window.session.payload)
        window.fields.toggle_field_view()
        group=window.fields.tree.topLevelItem(0)
        window.fields.tree.setCurrentItem(group)
        self.assertTrue(window.fields.name.isReadOnly())
        self.assertTrue(window.fields.expression.isReadOnly())
        self.assertFalse(window.fields.required.isEnabled())
        window.select_name(window.fields,'Amount')
        self.assertFalse(window.fields.name.isReadOnly())
        self.assertFalse(window.fields.expression.isReadOnly())
        self.assertTrue(window.fields.required.isEnabled())
        window.layouts.search.setText('nothing matches this')
        self.assertTrue(window.layouts.name.isReadOnly())
        self.assertTrue(window.layouts.condition.isReadOnly())
        window.layouts.search.clear()
        self.assertFalse(window.layouts.name.isReadOnly())
        self.assertTrue(window.clauses.name.isReadOnly())
        window.add_clause()
        self.assertFalse(window.clauses.name.isReadOnly())
        window.clauses.search.setText('nothing matches this')
        self.assertTrue(window.clauses.expression.isReadOnly())
        # Fake a package-listed document absent from the AT, as session ingestion does.
        window.session.documents.append({'name':'Missing','source':{},'in_at':False,'condition':'','descr':'','associated':True,'always_trigger':False})
        window.set_session(window.session,preserve_selection=True)
        window.select_name(window.documents,'Missing')
        self.assertTrue(window.documents.name.isReadOnly())
        self.assertTrue(window.documents.description.isReadOnly())
        self.assertEqual(window.session.payload['Documents'],before['Documents'])
        window.select_name(window.documents,'Doc')
        self.assertFalse(window.documents.name.isReadOnly())

    def test_layout_add_and_remove_buttons_follow_all_parent_types_with_undo(self):
        from PySide6.QtWidgets import QMessageBox
        window=self.window
        actions={action.text():action for action in window.layouts.authoring_toolbar.actions()}
        kinds=[]
        for title,kind in [('Add Layout','Layout'),('Add Content','Content'),('Add Iteration','Iteration'),('Add Field','Field')]:
            self.assertTrue(actions[title].isEnabled(),title)
            window.layouts.authoring_toolbar.widgetForAction(actions[title]).click()
            node=window.layout_selection()[1]
            self.assertEqual(node['kind'],kind)
            kinds.append(node['key'])
        self.assertEqual(len(window.editor.undo_stack),4)
        field_key=kinds[-1]
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            window.layouts.authoring_toolbar.widgetForAction(actions['Remove']).click()
        self.assertFalse(any(item.data(0,Qt.ItemDataRole.UserRole)['key']==field_key for item in window.layouts.items()))
        window.undo_action.trigger()
        self.assertTrue(any(item.data(0,Qt.ItemDataRole.UserRole)['key']==field_key for item in window.layouts.items()))
        for _ in range(4):window.undo_action.trigger()
        self.assertEqual(len(window.session.payload['Documents'][0]['Layouts']),3)

    def test_document_remove_button_removes_only_descendants_and_can_cancel_or_undo(self):
        from PySide6.QtWidgets import QMessageBox
        window=self.window
        payload=copy.deepcopy(window.session.payload)
        payload['Documents'] += [{'$$Id':'Doc_A','Unknown':'parent'}, {'$$Id':'Doc_A_B','Unknown':'child'}, {'$$Id':'Doc_AB','Unknown':'sibling'}]
        window.set_session(PackageSession.from_payload(payload))
        before=copy.deepcopy(window.session.payload)
        window.select_name(window.documents,'Doc_A')
        remove=next(action for action in window.documents.authoring_toolbar.actions() if action.text()=='Remove')
        button=window.documents.authoring_toolbar.widgetForAction(remove)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):button.click()
        self.assertEqual(window.session.payload,before)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes) as confirmation:button.click()
        self.assertIn('Doc_A_B',confirmation.call_args.args[2])
        self.assertEqual([row['$$Id'] for row in window.session.payload['Documents']],['Doc','Doc_AB'])
        window.undo_action.trigger()
        self.assertEqual(window.session.payload,before)

    def test_field_path_expand_collapse_and_mapped_filter_buttons(self):
        from PySide6.QtWidgets import QPushButton
        window=self.window
        window.fields.field_view_toggle.click()
        parent=window.fields.tree.topLevelItem(0)
        collapse=next(button for button in window.fields.findChildren(QPushButton) if button.text()=='Collapse All')
        expand=next(button for button in window.fields.findChildren(QPushButton) if button.text()=='Expand All')
        collapse.click();self.assertFalse(parent.isExpanded())
        expand.click();self.assertTrue(parent.isExpanded())
        layout_parent=window.layouts.tree.topLevelItem(0)
        window.layouts.tree.expandAll()
        window.layouts.toggle_tree.click();self.assertFalse(layout_parent.isExpanded())
        window.layouts.toggle_tree.click();self.assertTrue(layout_parent.isExpanded())
        window.session.map_data({'bill':{'account':'123'}},'mapped')
        window.set_session(window.session)
        window.fields.matched_only.setChecked(True)
        self.assertEqual([item.text(0) for item in window.fields.items() if not item.isHidden()],['Account'])
        window.fields.matched_only.setChecked(False)
        self.assertEqual(len([item for item in window.fields.items() if not item.isHidden()]),3)

    def test_field_add_apply_remove_buttons_recompute_mapping_and_undo(self):
        from PySide6.QtWidgets import QMessageBox
        window=self.window
        window.session.map_data({'bill':{'amount':0,'account':'123'}},'mapped')
        window.set_session(window.session)
        actions={action.text():action for action in window.fields.authoring_toolbar.actions()}
        toolbar=window.fields.authoring_toolbar
        toolbar.widgetForAction(actions['Add']).click()
        added=window.selected_record('fields')
        self.assertTrue(added['name'].startswith('NewField'))
        window.fields.name.setText('NewAmount')
        window.fields.expression.setPlainText('$.bill.amount')
        window.fields.required.setChecked(True)
        toolbar.widgetForAction(actions['Apply']).click()
        added=window.selected_record('fields')
        self.assertEqual(added['name'],'NewAmount')
        self.assertEqual(added['mapped_values'],[0])
        self.assertTrue(added['mandatory'])
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            toolbar.widgetForAction(actions['Remove']).click()
        self.assertNotIn('NewAmount',[record['name'] for record in window.session.fields])
        window.undo_action.trigger()
        restored=next(record for record in window.session.fields if record['name']=='NewAmount')
        self.assertEqual(restored['mapped_values'],[0])
        self.assertTrue(restored['mandatory'])

    def test_layout_path_and_condition_buttons_browse_iteration_fields_and_root_conditions(self):
        window=self.window
        window.session.payload['Documents'][0]['Layouts'][0]['Condition']='@.enabled == true'
        window.session.payload['Documents'][0]['Layouts'][0]['Contents'][0]['Iteration']['Path']='$.rows[*]'
        window.editor.rebuild()
        window.session.map_data({'enabled':False,'rows':[{'value':0},{'value':3}]},'mapped')
        window.set_session(window.session)
        toolbar=window.layouts.authoring_toolbar
        actions={action.text():action for action in toolbar.actions()}
        window.select_layout_key('layout/0/Contents/0/Iteration/Fields/0')
        toolbar.widgetForAction(actions['Browse Path']).click()
        self.assertEqual(window.data.mode.currentText(),'JSONPath')
        self.assertEqual(window.data.search.text(),'$.rows[*].value')
        self.assertEqual(window.data.tree.topLevelItemCount(),2)
        self.assertEqual(window.data.path.text(),'$.rows[0].value')
        self.assertEqual(window.data.value.toPlainText(),'0')
        window.select_layout_key('layout/0/Contents/0/Iteration')
        toolbar.widgetForAction(actions['Browse Path']).click()
        self.assertEqual(window.data.search.text(),'$.rows[*]')
        window.select_layout_key('layout/0')
        toolbar.widgetForAction(actions['Evaluate Condition']).click()
        self.assertEqual(window.data.mode.currentText(),'Condition')
        self.assertEqual(window.data.search.text(),'@.enabled == true')
        self.assertEqual(window.data.status.text(),'Condition: FAIL')
        self.assertEqual(window.data.value.toPlainText(),'false')

    def test_clause_toolbar_add_save_rename_delete_and_undo(self):
        from PySide6.QtWidgets import QMessageBox
        window = self.window
        panel = window.clauses
        controls = {action.text(): panel.authoring_toolbar.widgetForAction(action) for action in panel.authoring_toolbar.actions()}
        controls['Add'].click()
        name = window.selected_clause()['name']
        panel.name.setText('Selected Renamed Clause')
        panel.description.setText('A saved description')
        panel.expression.setPlainText('@.enabled == true')
        controls['Save'].click()
        saved = next(row for row in window.session.clauses if row['name'] == 'Selected Renamed Clause')
        self.assertEqual(saved['expression'], '@.enabled == true')
        self.assertEqual(saved['description'], 'A saved description')
        self.assertEqual(panel.name.text(), 'Selected Renamed Clause')
        self.assertEqual(window.selected_clause()['name'], 'Selected Renamed Clause')
        self.assertNotIn(name, [row['name'] for row in window.session.clauses])
        with patch('atool_qt.authoring.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            controls['Delete'].click()
        self.assertIn(saved, window.session.clauses)
        with patch('atool_qt.authoring.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            controls['Delete'].click()
        self.assertNotIn(saved, window.session.clauses)
        window.undo_action.trigger()
        self.assertIn(saved, window.session.clauses)

    def test_clause_draft_can_save_empty_expression_and_original_numbered_name(self):
        import json
        window = self.window
        panel = window.clauses
        controls = {action.text(): panel.authoring_toolbar.widgetForAction(action) for action in panel.authoring_toolbar.actions()}
        controls['Add'].click()
        self.assertEqual(window.selected_clause()['name'], 'Clause1')
        panel.description.setText('Work in progress')
        with patch.object(window, 'report_error') as error:
            controls['Save'].click()
        error.assert_not_called()
        saved = window.session.clauses[0]
        self.assertEqual(saved['description'], 'Work in progress')
        self.assertEqual(saved['expression'], '')
        path = Path(self.temp.name) / 'draft.json'
        window.editor.save(path)
        self.assertEqual(json.loads(path.read_text())['Meta']['clause_library'][0]['expression'], '')
        controls['Add'].click()
        self.assertEqual(window.selected_clause()['name'], 'Clause2')
