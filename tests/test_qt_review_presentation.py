"""Original menus, visible editing buttons, and package status presentation."""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QSettings, Qt, QRect, QPoint
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication
from atool_qt.session import PackageSession
from atool_qt.shared_packages import SharedPackages, bundle_hashes, encode
from atool_qt.window import WorkspaceWindow


class ReviewPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.window = WorkspaceWindow(settings=QSettings(str(self.root/'qt.ini'), QSettings.Format.IniFormat))
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        with patch.object(self.window, 'confirm_discard', return_value=True), patch.object(self.window, 'prepare_shared_exit', return_value=True), patch.object(self.window, 'confirm_quit', return_value=True):
            self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_menu_commands_match_original_and_are_visible_in_workspace(self):
        original = ast.parse(Path('ATool.py').read_text())
        method = next(node for node in ast.walk(original) if isinstance(node, ast.FunctionDef) and node.name == '_build_app_menu')
        actual = {action.text().replace('&',''): action.menu() for action in self.window.menuBar().actions()}
        for variable, title in [('package_menu','Package'), ('settings_menu','Settings'), ('config_menu','Config'), ('resources_menu','Resources'), ('model_menu','Model')]:
            expected = []
            for node in ast.walk(method):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == variable and node.func.attr == 'add_command':
                    label = next((k.value for k in node.keywords if k.arg == 'label'), None)
                    if isinstance(label, ast.Constant):
                        expected.append(label.value)
            labels = [a.text().replace('…','...') for a in actual[title].actions() if not a.isSeparator()]
            for label in expected:
                self.assertIn(label, labels, title)
            self.assertTrue(actual[title].menuAction().isVisible())
        self.assertFalse(self.window.menuBar().isNativeMenuBar())
        self.assertTrue(self.window.menuBar().isVisible())

    def test_startup_is_empty_without_sample_or_read_only_notes(self):
        self.assertIsNone(self.window.session)
        self.assertEqual('Package: (none)', self.window.package_label.text())
        self.assertEqual('Data: (none)', self.window.data_label.text())
        self.assertEqual('Mode: (none)', self.window.editable_label.text())
        labels = [a.text() for a in self.window.findChildren(QAction)]
        self.assertFalse(any('Load Sample' in text for text in labels))
        entry = ast.parse(Path('ATool_Qt.py').read_text())
        self.assertFalse(any(isinstance(node, ast.Attribute) and node.attr == 'load_sample' for node in ast.walk(entry)))

    def test_edit_buttons_wrap_and_remain_visible_in_narrow_panels(self):
        for key in ('documents','fields','layouts','clauses'):
            self.window.show_panel(key)
            self.app.processEvents()
            panel = getattr(self.window, key)
            toolbar = panel.authoring_toolbar
            toolbar.resize(250, toolbar.heightForWidth(250))
            toolbar.layout().setGeometry(toolbar.rect())
            self.app.processEvents()
            buttons = list(toolbar.buttons.values())
            self.assertTrue(all(button.isVisible() for button in buttons), key)
            self.assertGreater(len({button.geometry().y() for button in buttons}), 1, key)
            self.assertTrue(all(toolbar.rect().contains(QRect(button.mapTo(toolbar, QPoint(0, 0)), button.size())) for button in buttons), key)
        labels = [button.text() for button in self.window.layouts.authoring_toolbar.buttons.values()]
        for text in ('➕ 🧩','➕ 📝','⬆️','⬇️','➕ 🔁','➕ 🏷️','➖'):
            self.assertIn(text, labels)

    def test_original_icons_edit_undo_and_data_labels(self):
        session = PackageSession.from_payload({'$$Id':'MyAT','Documents':[{'$$Id':'Doc'}],'Fields':[]})
        self.window.set_session(session)
        self.assertEqual('🔓 ✏️', self.window.editable_label.text())
        self.window.edit(lambda: self.window.editor.add_record('fields'))
        self.assertIn('🟡', self.window.editable_label.text())
        self.window.undo_change()
        self.assertNotIn('🟡', self.window.editable_label.text())
        session.map_data({'value':0}, 'input.json')
        self.window.set_session(session)
        self.assertEqual('Data: input.json', self.window.data_label.text())
        self.assertEqual('Package: MyAT', self.window.package_label.text())
        self.assertNotIn('documents', self.window.package_label.text())
        self.window.shared_mode = 'testing'
        self.window.update_package_status()
        self.assertEqual('🔓 👁', self.window.editable_label.text())

    def test_saved_bundle_changes_use_original_publish_indicator(self):
        values = {'occs-package.json': {'schemaVersion':'occs-package-bundle/v1','package':{'shortName':'Pack'},'version':{'shortName':'v1'},'files':{}},
                  'assembly-template.json':{'$$Id':'AT','Documents':[],'Fields':[]},
                  'version-master.json':{},'document-associations.json':{'associations':[]}}
        for name, value in values.items():
            (self.root/name).write_bytes(encode(value))
        manifest = values['occs-package.json']
        manifest['sourceHashes'] = {key:value for key,value in bundle_hashes(self.root).items() if key != 'manifest'}
        (self.root/'occs-package.json').write_bytes(encode(manifest))
        session = PackageSession.open(self.root)
        self.window.set_session(session)
        self.assertEqual('Package: Pack [v1]', self.window.package_label.text())
        self.assertNotIn('☁️', self.window.editable_label.text())
        (self.root/'version-master.json').write_text('{"modified":true}')
        self.window.update_package_status()
        self.assertIn('☁️', self.window.editable_label.text())
        self.assertIn('Publish the shared package to Comms.', self.window.editable_label.toolTip())
        published = self.root/'published'
        published.mkdir()
        for name, value in values.items():
            (published/name).write_bytes(encode(value))
        owner = {'user':'review','host':'test'}
        entry = {'published_dir':published,'manifest':manifest,'lock':{'owner':owner}}
        store = SimpleNamespace(owner=owner, owned=SharedPackages.owned, entry=lambda _:entry)
        self.window.shared_package_dir = self.root/'shared'
        self.window.shared_mode = 'edit'
        with patch.object(self.window, 'shared_store', return_value=store):
            self.window.update_package_status()
            self.assertEqual('🔒 ✏️ ➡️☁️', self.window.editable_label.text())
            self.assertIn('Update shared storage, then publish to Comms.', self.window.editable_label.toolTip())
            self.window.editor.associations = [{'documentShortName':'New'}]
            self.window.update_package_status()
            self.assertIn('⬆️', self.window.editable_label.text())


    def test_per_item_markers_counts_undo_save_and_raw_names(self):
        payload = {'$$Id':'Package','Documents':[{'$$Id':'Doc','Layouts':[
            {'$$Id':'Main','Contents':[]},{'$$Id':'Other','Contents':[]}]}],
            'Fields':[{'Name':'Amount','Path':'$.items[*].amount'}, {'Name':'Single','Path':'$.single'}]}
        path = self.root/'AT.json'
        path.write_text(json.dumps(payload))
        session = PackageSession.open(path)
        session.map_data({'items':[{'amount':0},{'amount':False},{'amount':7}], 'single':1}, 'data.json')
        window = self.window
        window.set_session(session)
        def labels(panel):
            return {item.data(0, Qt.ItemDataRole.UserRole + 4):item.text(0) for item in panel.items() if item.data(0, Qt.ItemDataRole.UserRole + 4)}
        self.assertEqual('Amount x3', labels(window.fields)['Amount'])
        self.assertEqual('Single', labels(window.fields)['Single'])
        window.edit(lambda: window.editor.update_record(session.fields[0], {'Name':'Renamed'}, 'fields'))
        self.assertEqual('Renamed x3 *', labels(window.fields)['Renamed'])
        self.assertEqual('Single', labels(window.fields)['Single'])
        window.select_name(window.fields, 'Renamed')
        self.assertEqual('Renamed', window.fields.name.text())
        window.undo_change()
        self.assertEqual('Amount x3', labels(window.fields)['Amount'])
        window.redo_change()
        self.assertEqual('Renamed x3 *', labels(window.fields)['Renamed'])
        doc = session.documents[0]
        window.edit(lambda: window.editor.update_layout(doc, 'layout/0', {'$$Id':'Changed'}))
        window.select_layout_key('layout/0')
        self.assertEqual('Changed *', labels(window.layouts)['Changed'])
        self.assertEqual('Other', labels(window.layouts)['Other'])
        self.assertEqual('Doc *', labels(window.documents)['Doc'])
        self.assertEqual('Changed', window.layouts.name.text())
        window.apply_layout()
        self.assertEqual('Changed', doc['source']['Layouts'][0]['$$Id'])
        self.assertTrue(window.save_package())
        self.assertEqual('Renamed x3', labels(window.fields)['Renamed'])
        self.assertEqual('Changed', labels(window.layouts)['Changed'])
        self.assertEqual('Doc', labels(window.documents)['Doc'])
        saved = json.loads(path.read_text())
        self.assertEqual('Renamed', saved['Fields'][0]['Name'])
        self.assertEqual('Changed', saved['Documents'][0]['Layouts'][0]['$$Id'])
        window.fields.field_view_toggle.click()
        self.assertEqual('Renamed x3', labels(window.fields)['Renamed'])

    def test_clause_manager_has_three_vertical_stacks_and_ignores_old_column_state(self):
        clauses = self.window.clauses
        self.window.show_panel('clauses')
        self.app.processEvents()
        self.assertEqual(Qt.Orientation.Vertical, clauses.splitter.orientation())
        self.assertEqual(3, clauses.splitter.count())
        self.assertIs(clauses.tree, clauses.splitter.widget(0))
        rectangles = [clauses.splitter.widget(index).geometry() for index in range(3)]
        self.assertTrue(all(rectangles[index].bottom() < rectangles[index+1].top() for index in range(2)))
        self.assertEqual(1, len({rectangle.x() for rectangle in rectangles}))
        from PySide6.QtWidgets import QSplitter
        old = QSplitter(Qt.Orientation.Horizontal)
        self.window.settings.setValue('clauses/splitter', old.saveState())
        self.window.settings.setValue('clauses/librarySplitter', old.saveState())
        reopened = WorkspaceWindow(settings=self.window.settings)
        self.assertEqual(Qt.Orientation.Vertical, reopened.clauses.splitter.orientation())
        self.assertEqual(3, reopened.clauses.splitter.count())
        with patch.object(reopened, 'confirm_quit', return_value=True):
            reopened.close()
        reopened.deleteLater()
