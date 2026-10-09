"""Field clipboard controls preserve definitions, mapping and undo history."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from atool_qt.editor import PackageEditor
from atool_qt.session import PackageSession
from atool_qt.window import WorkspaceWindow


class FieldClipboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = WorkspaceWindow(QSettings(str(Path(self.temp.name)/'qt.ini'), QSettings.Format.IniFormat))
        self.app.clipboard().clear()
        self.session = PackageSession.from_payload({'$$Id':'Package', 'Documents':[], 'Fields':[
            {'Name':'Amount', 'Path':'$.amount', 'Descr':'Bill amount', 'Mandatory':True, 'Custom':{'keep':5}},
            {'Name':'Account', 'Path':'$.account', 'Mandatory':False}]})
        self.session.map_data({'amount':12, 'account':'A'},'fixture')
        self.window.set_session(self.session)
        self.addCleanup(self.close)

    def close(self):
        QTest.keyRelease(self.window.fields.tree,Qt.Key.Key_Control,Qt.KeyboardModifier.NoModifier)
        self.app.clipboard().clear()
        with patch.object(self.window,'confirm_discard',return_value=True), patch.object(self.window,'confirm_quit',return_value=True):
            self.window.close()

    def test_multi_field_buttons_duplicate_names_mapping_and_undo_redo(self):
        window = self.window
        original = copy.deepcopy(self.session.payload['Fields'])
        window.fields.tree.selectAll()
        window.field_copy_action.trigger()
        copied = json.loads(self.app.clipboard().text())['Fields']
        self.assertEqual({field['Name'] for field in copied},{'Amount','Account'})
        self.assertTrue(window.field_paste_action.isEnabled())
        window.field_paste_action.trigger()
        self.assertEqual({record['name'] for record in window.selected_fields()},{'Account_copy','Amount_copy'})
        amount = next(record for record in self.session.fields if record['name']=='Amount_copy')
        self.assertEqual(amount['mapped_values'],[12])
        self.assertEqual(amount['source']['Custom'],{'keep':5})
        self.assertTrue(amount['source']['Mandatory'])
        self.assertEqual(amount['source']['Descr'],'Bill amount')
        self.assertTrue(window.editor.dirty)
        window.field_paste_action.trigger()
        self.assertIn('Amount_copy2',[field['Name'] for field in self.session.payload['Fields']])
        window.undo_change()
        self.assertEqual(len(self.session.fields),4)
        window.redo_change()
        self.assertEqual(len(self.session.fields),6)
        window.undo_change()
        window.undo_change()
        self.assertEqual(self.session.payload['Fields'],original)
        self.assertFalse(window.editor.dirty)
        self.assertEqual(json.loads(self.app.clipboard().text())['Fields'],copied)

    def test_tree_keyboard_copy_paste_works_across_packages(self):
        window = self.window
        window.show()
        window.show_panel('fields')
        window.select_name(window.fields,'Amount')
        window.fields.tree.setFocus()
        self.app.processEvents()
        QTest.keyClick(window.fields.tree,Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(window.field_clipboard_sources()[0]['Name'],'Amount')
        target = PackageSession.from_payload({'$$Id':'Target','Documents':[],'Fields':[]})
        window.set_session(target)
        window.fields.tree.setFocus()
        self.app.processEvents()
        QTest.keyClick(window.fields.tree,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(target.fields[0]['name'],'Amount')
        self.assertEqual(target.fields[0]['source']['Custom'],{'keep':5})
        self.assertEqual(window.field_copy_action.shortcutContext(),Qt.ShortcutContext.WidgetShortcut)

    def test_invalid_batch_is_atomic_and_unrelated_clipboard_disables_paste(self):
        editor = PackageEditor(self.session)
        before = copy.deepcopy(self.session.payload)
        with self.assertRaises(ValueError):
            editor.paste_fields([{'Name':'Good','Path':'$.amount'},{'Name':'Bad','Path':''}])
        self.assertEqual(self.session.payload,before)
        self.assertEqual(editor.undo_stack,[])
        self.app.clipboard().setText('ordinary copied text')
        self.assertFalse(self.window.field_paste_action.isEnabled())
