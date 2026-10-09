"""Package association edits must round trip without losing bundle metadata."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atool_qt.editor import PackageEditor, relationship_info
from atool_qt.session import PackageSession
from atool_qt.storage import write_files


def make_bundle(root):
    rows = [{"documentConfigUuid": name.lower(), "documentShortName": name,
             "documentRelIndex": order, "documentAlwaysTriggerInd": False,
             "packageVersionConfigUuid": "version", "extra": name}
            for name, order in (("A", 10), ("B", 30), ("Missing", 50))]
    relations = [{"CommunicationPackageVersionConfigCommunicationDocumentConfigRelRec": {
        "CommunicationPackageVersionConfigCommunicationDocumentConfigRelInfo": {
            "CommunicationPackageVersionConfigUuid": "version", "CommunicationDocumentConfigUuid": row["documentConfigUuid"],
            "DocumentRelIndex": row["documentRelIndex"], "DocumentAlwaysTriggerInd": False, "Keep": "metadata"}}}
        for row in rows]
    values = {"occs-package.json": {"version": {"uuid": "version"}, "custom": 7, "files": {
        "assemblyTemplate": "AT.json", "versionMaster": "master.json", "documentAssociations": "helper.json"}},
        "AT.json": {"Documents": [{"$$Id": "A", "Condition": "$[?(@.active == true)]"}, {"$$Id": "B"}, {"$$Id": "Local"}], "Fields": []},
        "helper.json": {"associations": rows, "custom": "helper"},
        "master.json": {"CommunicationPackageVersionDocuments": relations + [{"opaque": True}], "custom": "master"}}
    for name, value in values.items():
        (root / name).write_text(json.dumps(value))
    return PackageSession.open(root)


class BundleTests(unittest.TestCase):
    def test_order_trigger_membership_and_unknown_metadata_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = make_bundle(root)
            session.map_data({"active": False}, "mapped")
            editor = PackageEditor(session)
            editor.set_always_trigger(session.documents[0], True)
            self.assertTrue(session.documents[0]["triggered"])
            editor.reorder_associations(["B", "Missing"], "A")
            self.assertEqual(["B", "Missing", "A", "Local"], [row["name"] for row in session.documents])
            self.assertEqual([10, 30, 50], [row["order"] for row in session.documents[:3]])
            editor.remove_association(session.documents[1])
            editor.add_association({"uuid": "new", "shortName": "New", "description": "new document"})
            editor.save()
            reopened = PackageSession.open(root)
            self.assertEqual(["B", "A", "New", "Local"], [row["name"] for row in reopened.documents])
            self.assertTrue(next(row for row in reopened.documents if row["name"] == "A")["always_trigger"])
            self.assertTrue(next(row for row in reopened.documents if row["name"] == "New")["in_at"])
            self.assertEqual("helper", reopened.bundle["helper"]["custom"])
            self.assertEqual("master", reopened.bundle["master"]["custom"])
            self.assertIn({"opaque": True}, reopened.bundle["master"]["CommunicationPackageVersionDocuments"])
            self.assertEqual(7, reopened.bundle["manifest"]["custom"])
            old = [relationship_info(row) for row in reopened.bundle["master"]["CommunicationPackageVersionDocuments"]]
            self.assertEqual("metadata", next(row for row in old if row and row["CommunicationDocumentConfigUuid"] == "a")["Keep"])
            self.assertEqual(4, len(list(root.glob('*_backup_*.json'))))
            self.assertFalse(editor.dirty)

    def test_rename_keeps_package_identity_and_undo_restores_association(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = make_bundle(Path(temporary))
            editor = PackageEditor(session)
            editor.update_record(session.documents[0], {"$$Id": "Renamed"}, "documents")
            self.assertFalse(session.documents[0]["in_at"])
            self.assertEqual("A", session.documents[0]["name"])
            self.assertFalse(next(row for row in session.documents if row["name"] == "Renamed")["associated"])
            editor.undo()
            self.assertTrue(session.documents[0]["in_at"])
            editor.move_association(session.documents[0], 1)
            editor.undo()
            self.assertFalse(editor.dirty)

    def test_external_metadata_change_prevents_every_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = make_bundle(root)
            editor = PackageEditor(session)
            editor.set_always_trigger(session.documents[0], True)
            before = (root / "AT.json").read_bytes()
            (root / "helper.json").write_text('{}')
            with self.assertRaisesRegex(ValueError, 'changed outside'):
                editor.save()
            self.assertEqual(before, (root / "AT.json").read_bytes())
            self.assertFalse(list(root.glob('*_backup_*.json')))

    def test_failed_second_replacement_rolls_back_all_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {root / "a.json": b'new a', root / "b.json": b'new b'}
            for path in files:
                path.write_bytes(path.name.encode())
            original_replace = os.replace
            count = 0
            def replacement(source, target):
                nonlocal count
                count += 1
                if count == 2:
                    raise OSError('simulated disk failure')
                return original_replace(source, target)
            with patch('atool_qt.storage.os.replace', side_effect=replacement):
                with self.assertRaisesRegex(OSError, 'simulated'):
                    write_files(files)
            for path in files:
                self.assertEqual(path.name.encode(), path.read_bytes())
            self.assertFalse(list(root.glob('.atool-*')))

    def test_save_as_detaches_bundle_and_retains_original_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = make_bundle(root)
            editor = PackageEditor(session)
            original = (root / "helper.json").read_bytes()
            editor.set_always_trigger(session.documents[0], True)
            editor.save(root / "copy.json")
            self.assertEqual({}, session.bundle)
            self.assertEqual(original, (root / "helper.json").read_bytes())
            editor.undo()
            self.assertEqual({}, session.bundle)
            self.assertIsNone(editor.associations)


class PackageControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_buttons_trigger_order_and_drop_update_shared_model(self):
        from PySide6.QtCore import QSettings
        from atool_qt.window import WorkspaceWindow
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window = WorkspaceWindow(QSettings(str(root / 'qt.ini'), QSettings.Format.IniFormat))
            window.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
            window.set_session(make_bundle(root))
            self.assertTrue(window.documents.always_trigger.isEnabled())
            window.documents.always_trigger.click()
            self.assertTrue(window.session.documents[0]['always_trigger'])
            window.package_actions['Move Down'].trigger()
            self.assertEqual('B', window.session.documents[0]['name'])
            self.assertEqual('A', window.selected_record('documents')['name'])
            window.documents.tree.reorder_requested.emit(['A', 'Missing'], 'B')
            self.assertEqual(['A', 'Missing', 'B', 'Local'], [row['name'] for row in window.session.documents])
            window.select_name(window.documents, 'Local')
            self.assertTrue(window.package_actions['Associate'].isEnabled())
            self.assertFalse(window.documents.always_trigger.isEnabled())
            self.assertFalse(window.package_actions['Remove Association'].isEnabled())
            window.editor.save()
            window.editor.saved = window.editor.snapshot()
            window.close()

    def test_invalid_condition_save_leaves_files_and_model_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = make_bundle(root)
            editor = PackageEditor(session)
            session.documents[0]['source']['Condition'] = '$[?(@.enabled == true && (@.count > 0)]'
            original = (root / 'AT.json').read_bytes()
            snapshot = editor.snapshot()
            with self.assertRaisesRegex(ValueError, 'Invalid Conditions'):
                editor.save()
            self.assertEqual(snapshot, editor.snapshot())
            self.assertEqual(original, (root / 'AT.json').read_bytes())
            self.assertFalse(list(root.glob('*_backup_*.json')))

    def test_save_normalizes_iteration_fields_and_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = make_bundle(root)
            source = session.documents[0]['source']
            source['Descr'] = 'Cafe\u0301\nline'
            source['Layouts'] = [{'Contents': [{'Iteration': {'fields': [{'Name': 'optional', 'Path': '$.value'}]}}]}]
            editor = PackageEditor(session)
            editor.save()
            saved = json.loads((root / 'AT.json').read_text())
            self.assertEqual('Café line', saved['Documents'][0]['Descr'])
            self.assertFalse(saved['Documents'][0]['Layouts'][0]['Contents'][0]['Iteration']['fields'][0]['Mandatory'])
