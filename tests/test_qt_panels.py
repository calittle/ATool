"""User-facing panel workflows and mapping-dependent defaults."""
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from atool_qt.session import PackageSession
from test_qt_mapping_details import nested_session

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "Install requirements-qt.txt")
class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.window = WorkspaceWindow(settings)
        self.window.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
        self.window.show()
        self.addCleanup(self.window.close)

    def test_content_and_clause_library_splitters_restore(self):
        from atool_qt.window import WorkspaceWindow
        settings = self.window.settings
        self.window.content.splitter.setSizes([210, 550])
        self.window.clauses.splitter.setSizes([220, 240, 260])
        content_state = self.window.content.splitter.saveState()
        clause_state = self.window.clauses.splitter.saveState()
        self.window.close()
        self.assertEqual(settings.value('content/splitter'), content_state)
        self.assertEqual(settings.value('clauses/stackedSplitter'), clause_state)
        reopened = WorkspaceWindow(settings)
        reopened.comms.settings.payload['application']['confirm_on_quit'] = False
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.content.splitter.saveState(), content_state)
        self.assertEqual(reopened.clauses.splitter.saveState(), clause_state)

    def test_defaults_depend_on_mapping_and_keep_user_choice_until_remap(self):
        session = nested_session()
        session.documents.append(dict(session.documents[0], name="Other"))
        self.window.set_session(session)
        documents, layouts = self.window.documents, self.window.layouts
        self.assertFalse(documents.matched_only.isChecked())
        self.assertFalse(layouts.matched_only.isChecked())
        self.assertFalse(layouts.matched_only.isEnabled())
        self.assertEqual("—", documents.clauses_tree.topLevelItem(0).text(1))
        self.assertEqual(0, self.window.data.tree.topLevelItemCount())
        session.map_data({"enabled": True, "show": True, "rows": [{"flag": False}]}, "data")
        self.window.set_session(session)
        self.assertTrue(documents.matched_only.isChecked())
        self.assertTrue(layouts.matched_only.isChecked())
        amount = next(item for item in layouts.items() if item.text(0) == "Amount")
        self.assertTrue(amount.isHidden())
        layouts.matched_only.setChecked(False)
        documents.matched_only.setChecked(False)
        documents.tree.setCurrentItem(documents.tree.topLevelItem(1))
        self.assertFalse(layouts.matched_only.isChecked())
        self.window.set_session(session, preserve_selection=True)
        self.assertFalse(documents.matched_only.isChecked())
        self.assertFalse(layouts.matched_only.isChecked())
        session.map_data({"enabled": True, "show": False}, "new data")
        self.window.set_session(session)
        self.assertTrue(documents.matched_only.isChecked())
        self.assertTrue(layouts.matched_only.isChecked())
        self.assertTrue(all(item.isHidden() for item in list(layouts.items())[1:]))

    def test_document_tabs_source_and_every_clause_branch(self):
        from atool_qt.window import BLUE, RED
        condition = '$[?(@.amount > 0 || @.customer not empty)]'
        session = PackageSession.from_payload({"$$Id": "Package", "Documents": [
            {"$$Id": "Notice", "Descr": "Description", "Condition": condition}], "Meta": {"clause_library": [
                {"name": "positive", "expression": "@.amount > 0"},
                {"name": "customer", "expression": "@.customer not empty"}]}})
        session.map_data({"amount": 3}, "data")
        self.window.set_session(session)
        panel = self.window.documents
        self.assertEqual(["Properties", "Source JSON", "Match Details"],
                         [panel.tabs.tabText(index) for index in range(panel.tabs.count())])
        self.assertEqual(0, panel.tabs.currentIndex())
        self.assertEqual("Description", panel.description.toPlainText())
        self.assertIn("Package", panel.package_status.text())
        self.assertEqual({"Condition": condition}, json.loads(panel.source.toPlainText()))
        root = panel.clauses_tree.topLevelItem(0)
        self.assertEqual("OR", root.text(0))
        self.assertEqual(2, root.childCount())
        self.assertEqual("positive", root.child(0).text(0))
        self.assertEqual(BLUE, root.child(0).foreground(0).color().name())
        self.assertEqual(RED, root.child(1).foreground(0).color().name())
        panel.search.setText("absent")
        self.assertEqual(0, panel.clauses_tree.topLevelItemCount())
        self.assertEqual("", panel.source.toPlainText())

    def test_named_compound_clauses_are_leaves_and_match_details_remain_expanded(self):
        from atool_qt.window import condition_details, BLUE, RED
        expression = '(@.amount > 0 && @.customer not empty) || @.raw > 0'
        session = PackageSession.from_payload({'Documents':[{'$$Id':'Notice','Condition':expression}],
            'Meta':{'clause_library':[{'name':'ELDERLY_is','expression':'@.amount > 0 && @.customer not empty'}]}})
        session.map_data({'amount':3,'customer':'Alice','raw':0},'data.json')
        self.window.set_session(session)
        panel = self.window.documents
        root = panel.clauses_tree.topLevelItem(0)
        clause = root.child(0)
        self.assertEqual('ELDERLY_is', clause.text(0))
        self.assertEqual(0, clause.childCount())
        self.assertEqual('PASS', clause.text(1))
        self.assertEqual(BLUE, clause.foreground(0).color().name())
        self.assertEqual('@.raw > 0', root.child(1).text(0))
        self.assertEqual(RED, root.child(1).foreground(0).color().name())
        full = condition_details(session, expression)
        self.assertEqual(2, len(full['children'][0]['children']))
        self.assertIn('@.customer not empty', panel.result.toPlainText())
        self.assertIn('@.amount > 0', panel.result.toPlainText())

    def test_clause_library_is_independent_of_mapping(self):
        session = PackageSession.from_payload({"Documents": [], "Meta": {"clause_library": [
            {"name": "positive", "expression": "@.amount > 0", "description": "Positive amount"},
            {"name": "both", "expression": "CLAUSE{positive} && @.customer not empty"},
            {"name": "cycle", "expression": "CLAUSE{cycle}"}]}})
        panel = self.window.clauses
        with patch("atool_qt.diagnostics.ConditionDiagnostics.explain", side_effect=AssertionError("Must not evaluate data")):
            self.window.set_session(session)
            panel.search.setText("positive")
            panel.tree.setCurrentItem(next(panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
                                           if panel.tree.topLevelItem(i).text(0) == "positive"))
            self.assertEqual("Positive amount", panel.description.text())
            self.assertEqual("@.amount > 0", panel.expression.toPlainText())
            self.assertEqual("Description", panel.tree.headerItem().text(1))
            before = [(panel.tree.topLevelItem(i).text(0), panel.tree.topLevelItem(i).text(1))
                      for i in range(panel.tree.topLevelItemCount())]
            session.map_data({"amount": 2}, "data")
            self.window.set_session(session)
            after = [(panel.tree.topLevelItem(i).text(0), panel.tree.topLevelItem(i).text(1))
                     for i in range(panel.tree.topLevelItemCount())]
            self.assertEqual(before, after)
            self.assertFalse(hasattr(panel, "result"))
            self.assertFalse(hasattr(panel, "clauses_tree"))
            panel.search.setText("cycle")
            self.assertEqual("CLAUSE{cycle}", panel.expression.toPlainText())
            panel.search.setText("absent")
            self.assertEqual("", panel.expression.toPlainText())

    def test_composer_follows_document_and_layout_targets_not_library_selection(self):
        session = PackageSession.from_payload({"Documents": [
            {"$$Id": "Notice", "Condition": "@.amount > 0 && @.customer not empty", "Layouts": [
                {"$$Id": "Block", "Condition": "@.amount > 0"}]},
            {"$$Id": "Other", "Condition": "@.amount > 0 || @.other == true"},
            {"$$Id": "NoCondition"}], "Meta": {"clause_library": [
                {"name": "positive", "expression": "@.amount > 0"},
                {"name": "customer", "expression": "@.customer not empty"}]}})
        self.window.set_session(session)
        panel = self.window.clauses
        self.assertEqual("Target: Document Notice", panel.target_label.text())
        self.assertEqual("positive + customer", panel.compose.toPlainText())
        self.assertEqual("Auto-compose: exact clause match.", panel.compose_status.text())
        panel.search.setText("positive")
        self.assertEqual("positive + customer", panel.compose.toPlainText())
        self.window.layouts.tree.setCurrentItem(None)
        self.window.layouts.tree.setCurrentItem(self.window.layouts.tree.topLevelItem(0))
        self.assertEqual("Target: Layout Block", panel.target_label.text())
        self.assertEqual("positive", panel.compose.toPlainText())
        self.window.documents.tree.setCurrentItem(self.window.documents.tree.topLevelItem(1))
        self.assertEqual("Target: Document Other", panel.target_label.text())
        self.assertEqual("positive OR RAW{@.other == true}", panel.compose.toPlainText())
        self.assertIn("1 raw fragment", panel.compose_status.text())
        self.window.documents.tree.setCurrentItem(self.window.documents.tree.topLevelItem(2))
        self.assertEqual("Target: Document NoCondition", panel.target_label.text())
        self.assertEqual("", panel.compose.toPlainText())
        self.assertEqual("Target has no condition.", panel.compose_status.text())
        self.window.documents.search.setText("absent")
        self.assertEqual("Target: (none selected)", panel.target_label.text())
        self.assertEqual("", panel.compose.toPlainText())

    def test_raw_conditions_do_not_become_fake_library_entries(self):
        self.window.set_session(nested_session())
        panel = self.window.clauses
        self.assertEqual(0, panel.tree.topLevelItemCount())
        self.assertEqual("RAW{@.enabled == true}", panel.compose.toPlainText())
        self.assertIn("No saved clause library", panel.count.text())

    def test_data_browser_paths_and_default_docks(self):
        session = PackageSession.from_payload({"Documents": []})
        data = {"odd.key": [{"value": False}, {"value": 0}], "null": None, "huge": 10**30}
        session.map_data(data, "data")
        self.window.set_session(session)
        self.app.processEvents()
        fields = self.window.docks["fields"]
        for key in ("clauses", "data"):
            self.assertIn(self.window.docks[key], self.window.tabifiedDockWidgets(fields))
            self.assertFalse(self.window.docks[key].isHidden())
            self.assertFalse(self.window.docks[key].isFloating())
        browser = self.window.data
        root = browser.tree.topLevelItem(0)
        self.assertEqual('$["odd.key"]', root.child(0).text(0))
        array = root.child(0)
        array.setExpanded(True)
        first = array.child(0)
        first.setExpanded(True)
        leaf = first.child(0)
        browser.tree.setCurrentItem(leaf)
        self.assertEqual('$["odd.key"][0]["value"]', browser.path.text())
        self.assertEqual(False, json.loads(browser.value.toPlainText()))
        browser.tree.setCurrentItem(root)
        self.assertEqual(data, json.loads(browser.value.toPlainText()))
        self.window.docks["data"].hide()
        self.window.docks["data"].toggleViewAction().trigger()
        self.assertTrue(self.window.docks["data"].isVisible())


if __name__ == "__main__":
    unittest.main()
