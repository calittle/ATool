"""Library usage and trigger edits are structural, not data-dependent."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from atool_qt.session import PackageSession
from atool_qt.editor import PackageEditor
from atool_qt.clause_usage import condition_targets, trigger_proposals, usage_results


def clause_session():
    return PackageSession.from_payload({'Documents': [
        {'$$Id': 'Exact', 'Condition': '@.flag == true', 'Layouts': [{'$$Id': 'L', 'Condition': '@.flag == true',
            'Contents': [{'$$Id': 'C', 'Condition': '@.unknown == true', 'Iteration': {'Path': '$.rows',
                'Condition': '@.flag == true', 'Fields': [{'Name': 'F', 'Path': '$.value', 'Condition': '@.flag == true'}]}}]}]},
        {'$$Id': 'Dependent', 'Condition': '(@.flag == true) && @.balance > 0'},
        {'$$Id': 'Embedded', 'Condition': '@.flag == true && @.other == true'}], 'Fields': [],
        'Meta': {'clause_library': [{'name': 'Has Flag', 'expression': '@.flag == true'},
            {'name': 'Payable', 'expression': 'CLAUSE{Has Flag} && @.balance > 0'}]}})


class ClauseUsageTests(unittest.TestCase):
    def test_usage_finds_dependencies_all_owners_and_raw_without_mapping(self):
        session = clause_session()
        with patch('atool_qt.diagnostics.ConditionDiagnostics.explain', side_effect=AssertionError('No mapping')):
            results = usage_results(session, 'Has Flag')
        self.assertEqual({'Document', 'Layout', 'Iteration', 'Field'}, {row['kind'] for row in results})
        doc_types = {row['document_name']: row['match_type'] for row in results if row['kind'] == 'Document'}
        self.assertEqual({'Exact': 'Exact clause', 'Dependent': 'Dependent clause', 'Embedded': 'Embedded clause'}, doc_types)
        self.assertTrue(next(row for row in results if row['document_name'] == 'Exact')['exact'])
        self.assertEqual({'Content', 'Document'}, {row['kind'] for row in usage_results(session, raw_only=True)})
        self.assertEqual(7, len(condition_targets(session)))

    def test_update_proposals_preserve_raw_and_only_update_documents(self):
        session = clause_session()
        editor = PackageEditor(session)
        old = copy.deepcopy(session.clauses)
        new = copy.deepcopy(old)
        new[0]['expression'] = '@.flag == false'
        proposals = trigger_proposals(session, old, new, 'Has Flag')
        self.assertEqual(3, len(proposals))
        self.assertTrue(all(row['kind'] == 'Document' for row in proposals))
        self.assertIn('@.other == true', proposals[2]['new_condition'])
        editor.save_clause('Has Flag', 'Has Flag', '', '@.flag == false')
        editor.apply_trigger_proposals(proposals)
        self.assertIn('@.flag == false', session.documents[0]['condition'])
        self.assertEqual('@.flag == true', session.documents[0]['source']['Layouts'][0]['Condition'])
        editor.undo()
        self.assertEqual('@.flag == true', session.documents[0]['condition'])
        self.assertEqual('@.flag == false', session.clauses[0]['expression'])
        editor.undo()
        self.assertFalse(editor.dirty)

    def test_changed_trigger_conflict_is_detected_before_any_mutation(self):
        session = clause_session()
        editor = PackageEditor(session)
        new = copy.deepcopy(session.clauses)
        new[0]['expression'] = '@.flag == false'
        proposals = trigger_proposals(session, session.clauses, new, 'Has Flag')
        editor.update_record(session.documents[1], {'Condition': '@.different == true'}, 'documents')
        before = editor.snapshot()
        with self.assertRaisesRegex(ValueError, 'changed'):
            editor.apply_trigger_proposals(proposals)
        self.assertEqual(before, editor.snapshot())


class ClauseUsageInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_usage_navigates_to_nested_owner_and_trigger_dialog_apply_skip(self):
        from atool_qt.window import WorkspaceWindow
        with tempfile.TemporaryDirectory() as temporary:
            window = WorkspaceWindow(QSettings(str(Path(temporary) / 'qt.ini'), QSettings.Format.IniFormat))
            window.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
            window.set_session(clause_session())
            window.clauses.tree.setCurrentItem(window.clauses.tree.topLevelItem(0))
            window.find_clause_usage()
            dialog = window.usage_dialog
            field_item = next(dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())
                              if dialog.tree.topLevelItem(i).text(1) == 'Field')
            dialog.tree.setCurrentItem(field_item)
            dialog.select_owner()
            self.assertEqual('Field', window.layout_selection()[1]['kind'])
            dialog.close()
            window.clauses.expression.setPlainText('@.flag == false')
            window.update_clause_triggers()
            dialog = window.trigger_dialog
            self.assertEqual(3, dialog.tree.topLevelItemCount())
            dialog.skip_current()
            dialog.apply_all()
            self.assertEqual(1, sum(row['status'] == 'Skipped' for row in dialog.results))
            self.assertEqual(2, sum(row['status'] == 'Applied' for row in dialog.results))
            dialog.close()
            window.editor.saved = window.editor.snapshot()
            window.close()

    def dialog_fixture(self, updates=True):
        from atool_qt.window import WorkspaceWindow
        from atool_qt.user_settings import UserSettings
        from atool_qt.clause_usage import ConditionUsageDialog
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        window=WorkspaceWindow(QSettings(str(root/'qt.ini'),QSettings.Format.IniFormat))
        settings=UserSettings(root/'user.json');settings.payload['application']['confirm_on_quit']=False
        window.comms.settings=settings
        window.set_session(clause_session())
        if updates:
            old=copy.deepcopy(window.session.clauses)
            new=copy.deepcopy(old);new[0]['expression']='@.flag == false'
            results=trigger_proposals(window.session,old,new,'Has Flag')
        else:
            results=usage_results(window.session,'Has Flag')
        dialog=ConditionUsageDialog(window,results,'Audit',updates=updates)
        self.addCleanup(dialog.close)
        def close():
            window.editor.saved=window.editor.snapshot();window.close()
        self.addCleanup(close)
        return window,dialog

    def test_trigger_buttons_advance_pending_and_disable_when_finished(self):
        window,dialog=self.dialog_fixture()
        first=dialog.current()
        dialog.buttons['Skip'].click()
        self.assertEqual(first['status'],'Skipped')
        self.assertIsNot(dialog.current(),first)
        second=dialog.current()
        dialog.buttons['Apply Current'].click()
        self.assertEqual(second['status'],'Applied')
        self.assertEqual(dialog.current()['status'],'Pending')
        dialog.buttons['Apply All'].click()
        self.assertFalse(dialog.buttons['Apply Current'].isEnabled())
        self.assertFalse(dialog.buttons['Skip'].isEnabled())
        self.assertFalse(dialog.buttons['Apply All'].isEnabled())

    def test_apply_all_updates_valid_triggers_and_reports_changed_preview(self):
        from PySide6.QtWidgets import QMessageBox
        window,dialog=self.dialog_fixture()
        stale=dialog.results[0]
        record=next(row for row in window.session.documents if row['name']==stale['document_name'])
        window.editor.update_record(record,{'Condition':'@.changed == true'},'documents')
        with patch.object(QMessageBox,'warning') as warning:dialog.buttons['Apply All'].click()
        warning.assert_called_once()
        self.assertEqual(stale['status'],'Pending')
        self.assertEqual(sum(row['status']=='Applied' for row in dialog.results),2)
        self.assertEqual(next(row for row in window.session.documents if row['name']==stale['document_name'])['condition'],'@.changed == true')

    def test_changed_current_trigger_requires_explicit_override_and_keeps_undo(self):
        from PySide6.QtWidgets import QMessageBox
        window,dialog=self.dialog_fixture()
        selected=dialog.current()
        record=next(row for row in window.session.documents if row['name']==selected['document_name'])
        window.editor.update_record(record,{'Condition':'@.changed == true'},'documents')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):dialog.buttons['Apply Current'].click()
        self.assertEqual(selected['status'],'Pending')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):dialog.buttons['Apply Current'].click()
        self.assertEqual(selected['status'],'Applied')
        self.assertEqual(dialog.current()['status'],'Pending')
        window.undo_change()
        self.assertEqual(next(row for row in window.session.documents if row['name']==selected['document_name'])['condition'],'@.changed == true')

    def test_usage_filter_select_owner_and_old_dialog_reject_new_package(self):
        from PySide6.QtWidgets import QPushButton
        window,dialog=self.dialog_fixture(updates=False)
        dialog.kind_filter.setCurrentText('Field')
        self.assertEqual(dialog.tree.topLevelItemCount(),1)
        button=next(button for button in dialog.findChildren(QPushButton) if button.text()=='Select Owner')
        button.click()
        self.assertEqual(window.layout_selection()[1]['kind'],'Field')
        window.set_session(PackageSession.from_payload({'Documents':[{'$$Id':'Exact','Condition':'@.flag == true'}]}))
        with patch.object(window,'report_error') as report:button.click()
        report.assert_called_once()
        self.assertEqual(window.session.documents[0]['condition'],'@.flag == true')

    def test_usage_navigation_follows_moved_owner_and_refuses_removed_owner(self):
        from PySide6.QtCore import Qt
        window,dialog=self.dialog_fixture(updates=False)
        dialog.kind_filter.setCurrentText('Field')
        selected=dialog.current()
        source=selected['source']
        layouts=window.session.payload['Documents'][0]['Layouts']
        layouts.insert(0,{'$$Id':'Inserted','Condition':'@.other == true'})
        window.editor.rebuild();window.refresh_edit()
        dialog.select_owner()
        self.assertEqual(window.layout_selection()[1]['source'],source)
        self.assertTrue(window.layout_selection()[1]['key'].startswith('layout/1/'))
        window.editor.remove_layout_item(window.active_document,window.layout_selection()[1]['key'])
        window.refresh_edit()
        with patch.object(window,'report_error') as report:dialog.select_owner()
        report.assert_called_once()

    def test_trigger_dialog_cannot_apply_during_package_operation(self):
        window,dialog=self.dialog_fixture()
        before=window.editor.snapshot()
        with patch.object(window,'package_busy',return_value=True),patch.object(window,'report_error') as report:
            dialog.buttons['Apply All'].click()
        report.assert_called_once()
        self.assertEqual(window.editor.snapshot(),before)
        self.assertTrue(all(row['status']=='Pending' for row in dialog.results))

    def test_old_trigger_dialog_rejects_new_package_or_changed_library(self):
        window,dialog=self.dialog_fixture()
        window.editor.save_clause('Has Flag','Has Flag','','@.other == true')
        with patch.object(window,'report_error') as report:dialog.buttons['Apply All'].click()
        report.assert_called_once()
        self.assertTrue(all(row['status']=='Pending' for row in dialog.results))
        window.set_session(clause_session())
        with patch.object(window,'report_error') as report:dialog.buttons['Apply Current'].click()
        report.assert_called_once()

    def test_completion_replaces_current_token_with_space_safe_name(self):
        from atool_qt.clause_completion import ClauseComposeEdit
        widget = ClauseComposeEdit()
        widget.set_clauses([{'name': 'Has Flag'}, {'name': 'Payable'}])
        widget.setPlainText('Payable + Ha')
        cursor = widget.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        widget.setTextCursor(cursor)
        widget.insert_completion('Has Flag')
        self.assertEqual('Payable + CLAUSE{Has Flag}', widget.toPlainText())
        widget.close()
