"""Mapping semantics and diagnostics for the Qt managers."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atool_qt.session import PackageSession
from atool_qt.diagnostics import ConditionDiagnostics

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QSpinBox
except ImportError:
    QApplication = None


def nested_session():
    return PackageSession.from_payload({"$$Id": "Scoped", "Documents": [{"$$Id": "Doc", "Condition": "$[?(@.enabled == true)]",
        "Layouts": [{"$$Id": "Layout", "Type": "Block", "Descr": "Charge table", "Priority": 2, "Mandatory": False,
                     "Contents": [{"$$Id": "Rows", "Condition": "$[?(@.show == true)]",
                         "Iteration": {"Name": "Rows", "Path": "$.rows[*]", "Fields": [
                             {"Name": "Amount", "Path": "$.rows[*].amount", "Mandatory": True},
                             {"Name": "Flag", "Path": "$.flag", "Mandatory": False}]} }]}]}], "Fields": [
        {"Name": "GlobalAmount", "Path": "$.globalAmount"}, {"Name": "Missing", "Path": "$.missing"}]})


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node["children"])


class MappingSemanticsTests(unittest.TestCase):
    def test_scoped_row_values_and_presence_of_zero_false(self):
        session = nested_session()
        session.map_data({"enabled": True, "show": True, "globalAmount": 99,
                          "rows": [{"amount": 0, "flag": False}, {"flag": True}]}, "rows.json")
        nodes = {node["source"].get("Name", node["source"].get("$$Id")): node
                 for node in flatten(session.layouts_for(session.documents[0]))}
        amount = nodes["Amount"]
        self.assertEqual([[0], []], [row["values"] for row in amount["rows"]])
        self.assertEqual([True, False], [row["passed"] for row in amount["rows"]])
        self.assertFalse(amount["state"])
        self.assertEqual([[False], [True]], [row["values"] for row in nodes["Flag"]["rows"]])
        self.assertTrue(nodes["Flag"]["state"])
        self.assertTrue(nodes["Rows"]["state"])
        self.assertEqual([99], session.fields[0]["mapped_values"])

    def test_parent_condition_suppresses_values_and_empty_iteration_suppresses_content(self):
        session = nested_session()
        for data in ({"enabled": False, "show": True, "rows": [{"amount": 3}]},
                     {"enabled": True, "show": False, "rows": [{"amount": 3}]},
                     {"enabled": True, "show": True, "rows": []}):
            session.map_data(data, "data")
            nodes = list(flatten(session.layouts_for(session.documents[0])))
            self.assertFalse(nodes[1]["state"])
            self.assertFalse(nodes[2]["state"])
            self.assertFalse(nodes[3]["state"])
            self.assertFalse(any(row["values"] for row in nodes[3]["rows"]))

    def test_nested_iterators_keep_row_context(self):
        session = PackageSession.from_payload({"Documents": [{"$$Id": "Doc", "Layouts": [{"$$Id": "Layout", "Contents": [
            {"$$Id": "Outer", "Iteration": {"Path": "$.orders[*]", "Fields": [
                {"Name": "Nested", "Iteration": {"Path": "$.orders[*].items[*]", "Fields": [
                    {"Name": "Amount", "Path": "$.orders[*].items[*].amount"}]}}]}}]}]}]})
        session.map_data({"orders": [{"items": [{"amount": 3}, {"amount": 4}]}, {"items": [{"amount": 5}]}]}, "data")
        amount = next(node for node in flatten(session.layouts_for(session.documents[0])) if node["source"].get("Name") == "Amount")
        self.assertEqual(["1.1", "1.2", "2.1"], [row["row"] for row in amount["rows"]])
        self.assertEqual([[3], [4], [5]], [row["values"] for row in amount["rows"]])

    def test_or_and_not_diagnostics_include_all_branches_and_clause_names(self):
        entries = [{"name": "positive", "expression": "@.amount > 0"},
                   {"name": "customer_present", "expression": "@.customer not empty"},
                   {"name": "both", "expression": "CLAUSE{positive} && CLAUSE{customer_present}"}]
        diagnostic = ConditionDiagnostics().explain("$[?((@.amount > 0 && @.customer not empty) || !(@.credit == true))]",
                                                    {"amount": 4, "credit": True}, entries)
        self.assertFalse(diagnostic["passed"])
        left, right = diagnostic["children"]
        self.assertEqual("both (AND)", left["label"])
        self.assertEqual("positive", left["children"][0]["label"])
        self.assertTrue(left["children"][0]["passed"])
        self.assertFalse(left["children"][1]["passed"])
        self.assertEqual("NOT", right["label"])
        self.assertTrue(right["children"][0]["passed"])
        passing_or = ConditionDiagnostics().explain("@.amount > 0 || @.missing > 0", {"amount": 4})
        self.assertTrue(passing_or["passed"])
        self.assertFalse(passing_or["children"][1]["passed"])

    def test_bundle_order_missing_at_and_always_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "AT.json"
            template.write_text(json.dumps({"$$Id": "Package", "Documents": [
                {"$$Id": "Zulu", "Condition": "@.missing > 0"}, {"$$Id": "Alpha"}, {"$$Id": "ATOnly"}]}))
            manifest = root / "occs-package.json"
            manifest.write_text(json.dumps({"files": {"assemblyTemplate": "AT.json", "documentAssociations": "associations.json",
                                                     "versionMaster": "master.json"}}))
            helper = {"associations": [
                {"documentShortName": "Alpha", "documentConfigUuid": "a", "documentRelIndex": 1},
                {"documentShortName": "zulu", "documentConfigUuid": "z", "documentRelIndex": 2},
                {"documentShortName": "NoAT", "documentConfigUuid": "n", "documentRelIndex": 3}]}
            (root / "associations.json").write_text(json.dumps(helper))
            master = {"CommunicationPackageVersionDocuments": []}
            for uuid, order, always in (("z", 1, True), ("n", 2, False), ("a", 3, False)):
                master["CommunicationPackageVersionDocuments"].append({
                    "CommunicationPackageVersionConfigCommunicationDocumentConfigRelRec": {
                        "CommunicationPackageVersionConfigCommunicationDocumentConfigRelInfo": {
                            "CommunicationDocumentConfigUuid": uuid, "DocumentRelIndex": order,
                            "DocumentAlwaysTriggerInd": always}}})
            (root / "master.json").write_text(json.dumps(master))
            before = {path: hashlib.sha256(path.read_bytes()).digest() for path in root.iterdir()}
            session = PackageSession.open(root)
            self.assertEqual(["Zulu", "NoAT", "Alpha", "ATOnly"], [doc["name"] for doc in session.documents])
            self.assertFalse(session.documents[1]["in_at"])
            self.assertIn("Missing from AT", session.documents[1]["status"])
            session.map_data({}, "data")
            self.assertTrue(session.documents[0]["triggered"])
            self.assertFalse(session.document_details(session.documents[0])["children"][0]["passed"])
            self.assertFalse(session.documents[1]["triggered"])
            self.assertFalse(session.documents[3]["triggered"])
            self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).digest() for path in root.iterdir()})

    def test_raw_at_unknown_associations_and_saved_clause_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".atool").mkdir()
            (root / ".atool" / ".a_b.meta.json").write_text(json.dumps({"clause_library": [
                {"name": "saved_positive", "expression": "@.amount > 0"}]}))
            template = root / "AT.json"
            template.write_text(json.dumps({"$$Id": "A--B", "Documents": [{"$$Id": "Z", "Condition": "@.amount > 0"}, {"$$Id": "A"}]}))
            with patch("atool_qt.session.Path.home", return_value=root):
                session = PackageSession.open(template)
            self.assertEqual(["Z", "A"], [doc["name"] for doc in session.documents])
            self.assertIsNone(session.documents[0]["associated"])
            session.map_data({"amount": 2}, "data")
            self.assertEqual("saved_positive", session.document_details(session.documents[0])["children"][0]["label"])


@unittest.skipIf(QApplication is None, "Install requirements-qt.txt")
class MappingInterfaceTests(unittest.TestCase):
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
        self.addCleanup(self.window.close)
        self.window.show()
        self.session = nested_session()
        self.session.map_data({"enabled": True, "show": True, "globalAmount": 0, "rows": [{"amount": 0, "flag": False}, {"flag": True}]}, "data")
        self.window.set_session(self.session)
        self.app.processEvents()

    def test_controls_row_values_and_colors_clear_on_new_package(self):
        from atool_qt.window import BLUE, RED
        panel = self.window.layouts
        panel.matched_only.setChecked(False)
        nodes = list(panel.items())
        root = nodes[0]
        panel.tree.setCurrentItem(root)
        self.assertFalse(hasattr(panel, "other"))
        self.assertIsInstance(panel.property_controls["Type"], QComboBox)
        self.assertIsInstance(panel.property_controls["Mandatory"], QCheckBox)
        self.assertIsInstance(panel.property_controls["Priority"], QSpinBox)
        self.assertEqual(2, panel.property_controls["Priority"].value())
        amount = next(item for item in nodes if item.text(0) == "Amount")
        panel.tree.setCurrentItem(amount)
        self.assertEqual(2, panel.mapped_values.topLevelItemCount())
        self.assertEqual(BLUE, panel.mapped_values.topLevelItem(0).foreground(0).color().name())
        self.assertEqual(RED, amount.foreground(0).color().name())
        self.assertEqual(RED, panel.mapped_values.topLevelItem(1).foreground(0).color().name())
        colors = {item.text(0): item.foreground(0).color().name() for item in
                  (self.window.fields.tree.topLevelItem(i) for i in range(self.window.fields.tree.topLevelItemCount()))}
        self.assertEqual(BLUE, colors["GlobalAmount"])
        self.assertEqual(RED, colors["Missing"])
        unmapped = nested_session()
        self.window.set_session(unmapped)
        self.assertEqual(0, panel.mapped_values.topLevelItemCount())
        self.assertEqual("—", panel.tree.topLevelItem(0).text(2))

    def test_document_order_missing_at_and_html_escaping(self):
        from atool_qt.window import RED
        self.session.incorporate_package_documents({"associations": [
            {"documentShortName": "NoAT", "documentRelIndex": 1}, {"documentShortName": "Doc", "documentRelIndex": 2}]})
        self.session.map_data({"enabled": True, "show": True, "rows": []}, "data")
        self.window.set_session(self.session)
        docs = self.window.documents
        docs.matched_only.setChecked(False)
        docs.tree.setCurrentItem(docs.tree.topLevelItem(0))
        self.assertEqual("NoAT", docs.tree.topLevelItem(0).text(0))
        self.assertEqual("Missing AT", docs.tree.topLevelItem(0).text(2))
        self.assertEqual(RED, docs.tree.topLevelItem(0).foreground(0).color().name())
        self.assertIn("missing from the Assembly Template", docs.result.toPlainText())
        self.assertEqual(0, self.window.layouts.tree.topLevelItemCount())
        docs.result.show_diagnostic({"label": "<script>example</script>", "passed": False, "details": ["a < b"]})
        self.assertIn("<script>example</script>", docs.result.toPlainText())
        self.assertIn("a < b", docs.result.toPlainText())
        self.assertIn("#c52323", docs.result.toHtml())


if __name__ == "__main__":
    unittest.main()
