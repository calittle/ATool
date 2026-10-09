"""Real Qt integration checks; run with QT_QPA_PLATFORM=offscreen."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

from atool_qt.session import PackageSession, demo_session


class SessionTests(unittest.TestCase):
    def test_bundle_mapping_does_not_change_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "AT.json"
            template.write_text(json.dumps({"$$Id": "RealPackage", "Documents": [
                {"$$Id": "Notice", "Condition": "$[?(@.balance > 0)]"}], "Fields": [
                {"Name": "Balance", "Path": "$.balance", "Mandatory": "false"},
                {"Name": "Balance", "Path": "$.balance", "Mandatory": "false"},
                {"Name": "Count", "Path": "$.length($.charges)"}]}))
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"files": {"assemblyTemplate": "AT.json"}}))
            before = hashlib.sha256(template.read_bytes()).digest()
            session = PackageSession.open(root)
            self.assertEqual("RealPackage", session.name)
            self.assertEqual(2, len(session.fields))
            self.assertFalse(session.fields[0]["mandatory"])
            self.assertEqual("$.charges", session.fields[1]["true_path"])
            session.map_data({"balance": 20, "charges": [1, 2]}, "data.json")
            self.assertEqual([20], session.fields[0]["mapped_values"])
            self.assertTrue(session.documents[0]["triggered"])
            self.assertEqual(before, hashlib.sha256(template.read_bytes()).digest())

    def test_tolerant_json_loading_and_invalid_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AT.json"
            path.write_text('{"Documents": [], "Fields": [],}')
            session = PackageSession.open(path)
            self.assertEqual([], session.documents)
        for value in ({"Documents": {}}, {"Fields": "oops"}, [], {"something": 1}):
            with self.assertRaises(ValueError):
                PackageSession.from_payload(value)

    def test_demo_uses_real_condition_engine(self):
        session = demo_session()
        self.assertEqual([True, True, False, False], [doc["triggered"] for doc in session.documents])
        self.assertEqual(["Monthly service", "Usage"], session.fields[3]["mapped_values"])


@unittest.skipIf(QApplication is None, "Install requirements-qt.txt to run Qt integration checks")
class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings = QSettings(str(Path(self.temporary.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.window = WorkspaceWindow(self.settings)
        self.window.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
        self.window.show()
        self.window.set_session(demo_session())
        self.app.processEvents()
        self.addCleanup(self.window.close)

    def test_filters_selection_and_inspection(self):
        panel = self.window.documents
        self.assertTrue(panel.matched_only.isChecked())
        panel.matched_only.setChecked(False)
        panel.search.setText("credit")
        self.assertEqual("BILL_CREDIT", panel.name.text())
        self.assertIn("FAIL Document trigger", panel.result.toPlainText())
        self.assertIn("Found: left values", panel.result.toPlainText())
        panel.matched_only.setChecked(True)
        self.assertEqual("", panel.name.text())
        self.assertEqual("", self.window.layouts.source.toPlainText())
        panel.search.clear()
        self.assertIn(panel.name.text(), ("BILL", "BILL_NOTICE"))
        field = self.window.fields
        field.search.setText("CustomerName")
        self.assertEqual("CustomerName", field.name.text())
        self.assertIn("Alex Morgan", field.result.toPlainText())
        field.search.setText("absent")
        self.assertEqual("", field.true_path.text())

    def test_layout_manager_tracks_document_and_nested_selection(self):
        layouts = self.window.layouts
        items = list(layouts.items())
        self.assertEqual(7, len(items))
        amount = next(item for item in items if item.text(0) == "Amount")
        layouts.tree.setCurrentItem(amount)
        self.assertEqual("Field", layouts.kind.text())
        self.assertEqual("$.charges[*].amount", layouts.path.text())
        self.assertIn('"Name": "Amount"', layouts.source.toPlainText())
        # Mapping refreshes keep the selected layout item in the same document.
        self.window.set_session(self.window.session, preserve_selection=True)
        self.assertEqual("Amount", layouts.name.text())
        layouts.search.setText("amount")
        visible = [item.text(0) for item in layouts.items() if not item.isHidden()]
        self.assertEqual(["charges", "charge_rows", "Charges", "Amount"], visible)
        self.window.documents.matched_only.setChecked(False)
        self.window.documents.search.setText("credit")
        self.assertEqual(0, layouts.tree.topLevelItemCount())
        self.assertEqual("", layouts.name.text())
        self.assertEqual("No layouts in this document", layouts.count.text())
        self.window.documents.search.setText("Main customer")
        self.assertGreater(layouts.tree.topLevelItemCount(), 0)

    def test_default_places_layouts_between_narrower_documents_and_fields(self):
        self.window.reset_layout()
        self.app.processEvents()
        doc, layouts, fields = [self.window.docks[key] for key in ("documents", "layouts", "fields")]
        self.assertTrue(all(dock.isVisible() for dock in (doc, layouts, fields)))
        self.assertLess(doc.x(), layouts.x())
        self.assertLess(layouts.x(), fields.x())
        self.assertLess(doc.width(), layouts.width())
        self.assertLess(doc.width(), fields.width())

    def test_docking_tabs_hide_restore_and_reset(self):
        from atool_qt.window import WorkspaceWindow
        doc, fields = self.window.docks["documents"], self.window.docks["fields"]
        self.window.tab_managers()
        self.assertIn(fields, self.window.tabifiedDockWidgets(doc))
        fields.setFloating(True)
        fields.hide()
        self.window.close()
        restored = WorkspaceWindow(self.settings)
        restored.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
        self.addCleanup(restored.close)
        restored.show()
        self.app.processEvents()
        self.assertTrue(restored.docks["fields"].isFloating())
        self.assertTrue(restored.docks["fields"].isHidden())
        restored.reset_layout()
        self.app.processEvents()
        self.assertFalse(restored.docks["fields"].isFloating())
        self.assertFalse(restored.docks["fields"].isHidden())
        self.assertFalse(restored.tabifiedDockWidgets(restored.docks["documents"]))

    def test_async_mapping_and_failed_open_keep_session(self):
        path = Path(self.temporary.name) / "data.json"
        path.write_text('{"balance": -5, "customer": {"name": "New Customer"}}')
        self.window.fields.search.setText("CustomerName")
        self.window.map_file(path)
        self.assertFalse(self.window.map_action.isEnabled())
        for _ in range(100):
            if self.window.job is None:
                break
            QTest.qWait(20)
        self.assertIsNone(self.window.job)
        self.assertEqual("data.json", self.window.session.data_name)
        self.assertTrue(self.window.session.documents[2]["triggered"])
        self.assertIn("New Customer", self.window.fields.result.toPlainText())
        previous = self.window.session
        with patch("atool_qt.window.QMessageBox.warning"):
            self.assertFalse(self.window.open_package(Path(self.temporary.name) / "missing.json"))
        self.assertIs(previous, self.window.session)

    def test_failed_mapping_and_close_during_job(self):
        path = Path(self.temporary.name) / "invalid.json"
        path.write_text("invalid")
        previous = self.window.session
        with patch("atool_qt.window.QMessageBox.warning"):
            self.window.map_file(path)
            self.window.close()
            for _ in range(100):
                if self.window.job is None:
                    break
                QTest.qWait(20)
        self.assertIsNone(self.window.job)
        self.assertIs(previous, self.window.session)
        self.assertFalse(self.window.isVisible())


if __name__ == "__main__":
    unittest.main()
