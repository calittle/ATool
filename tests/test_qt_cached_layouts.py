"""Cached relationship visibility, AT placement merging and read-only UI guards."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from atool_qt.cached_layouts import cached_document_layouts
from atool_qt.session import PackageSession

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


def cache_fixture(root):
    def save(path, value):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))
    active = {'Items': [{'StatusCode': 'Active', 'EffDtTm': '2026-01-01'}]}
    save('documents/Doc/Doc_master.json', {'CommunicationDocumentMasterVersions': [
        {'CommunicationDocumentVersionConfigRec': {'CommunicationDocumentVersionConfigInfo': {'ShortName': '1'}, 'Status': active}},
        {'CommunicationDocumentVersionConfigRec': {'CommunicationDocumentVersionConfigInfo': {'ShortName': '2'},
                                                 'Status': {'Items': [{'StatusCode': 'Active', 'EffDtTm': '2027-01-01'}]}}}]})
    def roots(names):
        return {'CommunicationDocumentVersionLayouts': [
            {'CommunicationLayoutConfigRec': {'CommunicationLayoutConfigUuid': name,
                                             'CommunicationLayoutConfigInfo': {'ShortName': name}},
             'CommunicationDocumentVersionConfigCommunicationLayoutConfigRelRec': {
                 'CommunicationDocumentVersionConfigCommunicationLayoutConfigRelInfo': {'LayoutRelIndex': i, 'LayoutAlwaysTriggerInd': True}}}
            for i, name in enumerate(names)]}
    save('documents/Doc/versions/1.json', roots(['Root', 'Root', 'Missing']))
    save('documents/Doc/versions/2.json', roots(['Future']))
    def layout(name, children=(), contents=()):
        save(f'layouts/{name}/{name}.json', {
            'CommunicationLayoutConfigRec': {'CommunicationLayoutConfigUuid': name},
            'CommunicationLayoutLayouts': [
                {'ShortName': child, 'CommunicationLayoutConfigCommunicationLayoutConfigRelRec': {
                    'CommunicationLayoutConfigCommunicationLayoutConfigRelInfo': {
                        'RelCommunicationLayoutConfigUuid': child, 'LayoutRelIndex': i, 'LayoutAlwaysTriggerInd': True}}}
                for i, child in enumerate(children)],
            'CommunicationLayoutContents': [
                {'ShortName': child, 'CommunicationLayoutConfigCommunicationContentConfigRelRec': {
                    'CommunicationLayoutConfigCommunicationContentConfigRelInfo': {'ContentRelIndex': i, 'ContentAlwaysTriggerInd': True}}}
                for i, child in enumerate(contents)]})
    layout('Root', ['Nested'], ['Static'])
    layout('Nested', contents=['Dynamic'])
    layout('Future')
    save('contents/Static/Static_master.json', {'CommunicationContentMasterVersions': [
        {'CommunicationContentVersionConfigRec': {'CommunicationContentVersionConfigInfo': {'ShortName': '1'}, 'Status': active}}]})
    body = root / 'contents/Static/versions/1/body.blob'
    body.parent.mkdir(parents=True)
    body.write_text('<p>Hello cached world</p>')
    return save, layout


def session_fixture():
    return PackageSession.from_payload({'$$Id': 'Package', 'Documents': [{'$$Id': 'Doc', 'Layouts': [
        {'$$Id': 'Nested', 'Contents': [{'$$Id': 'Dynamic', 'Condition': '$[?(@.show == true)]',
                                      'Iteration': {'Type': 'Iterator', 'Path': '$.rows[*]', 'Fields': [{'Name': 'Value', 'Path': '$.value'}]}}]},
        {'$$Id': 'ATOnly'}]}]})


class CachedLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)
        self.save, self.layout = cache_fixture(self.cache)
        self.session = session_fixture()

    def tree(self, date='2026-11-03'):
        return cached_document_layouts(self.cache, 'Doc', self.session.layouts_for(self.session.documents[0]), date)

    def test_flat_at_catalog_merges_at_nested_placements_without_mutation(self):
        before = copy.deepcopy(self.session.payload)
        nodes, status, warnings = self.tree()
        self.assertEqual(['Root', 'Root', 'Missing', 'ATOnly'], [n['source']['$$Id'] for n in nodes])
        for root in nodes[:2]:
            nested = root['children'][0]
            self.assertEqual('layout/0', nested['key'])
            self.assertEqual('AT + Cache', nested['origin'])
            content = nested['children'][0]
            self.assertEqual('layout/0/Contents/0', content['key'])
            self.assertEqual('Iteration', content['children'][0]['kind'])
            self.assertTrue(root['readonly'])
            self.assertEqual('Always included · when parent is included', root['cache_status'])
        self.assertNotEqual(nodes[0]['display_key'], nodes[1]['display_key'])
        self.assertIn('version 1', status)
        self.assertTrue(warnings)
        self.assertEqual(before, self.session.payload)

    def test_future_versions_missing_cache_and_cycles(self):
        nodes, status, _ = self.tree('2027-02-01')
        self.assertEqual('Future', nodes[0]['source']['$$Id'])
        self.assertIn('version 2', status)
        self.layout('Root', ['Root'])
        _, _, warnings = self.tree()
        self.assertTrue(any('cycle' in warning for warning in warnings))
        nodes, status, _ = cached_document_layouts(self.cache, 'Absent', self.session.layouts_for(self.session.documents[0]), '2026-11-03')
        self.assertEqual(2, len(nodes))
        self.assertIn('unavailable', status)

    def test_missing_at_document_and_invalid_cache_do_not_hide_structure(self):
        nodes, _, _ = cached_document_layouts(self.cache, 'Doc', [], '2026-11-03')
        self.assertEqual(['Root', 'Root', 'Missing'], [node['source']['$$Id'] for node in nodes])
        self.assertTrue(all(node['readonly'] for node in nodes))
        self.save('layouts/Root/Root.json', {'CommunicationLayoutLayouts': 'bad shape'})
        nodes, _, warnings = self.tree()
        self.assertTrue(warnings)
        self.assertEqual('Root', nodes[0]['source']['$$Id'])
        self.assertEqual('Nested', nodes[-2]['source']['$$Id'])
        self.save('documents/Doc/Doc_master.json', {'CommunicationDocumentMasterVersions': None})
        nodes, status, _ = self.tree()
        self.assertEqual(2, len(nodes))
        self.assertIn('unavailable', status)


@unittest.skipIf(QApplication is None, "Install requirements-qt.txt")
class CachedLayoutInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cache_rows_are_visible_and_all_edit_paths_preserve_at(self):
        from PySide6.QtCore import QDate, QSettings, Qt
        from atool_qt.window import WorkspaceWindow
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache_fixture(root)
            window = WorkspaceWindow(QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat))
            window.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
            window.report_error = lambda title, message: self.fail(title + ': ' + message)
            window.confirm_discard = lambda: True
            self.addCleanup(window.close)
            window.comms.settings.payload.setdefault('occs', {})['comms_cache_dir'] = str(root)
            session = session_fixture()
            session.map_data({'show': True, 'rows': [{'value': 1}]}, 'data.json')
            window.set_session(session)
            panel = window.layouts
            panel.cache_date.setDate(QDate(2026, 11, 3))
            original = copy.deepcopy(session.payload)
            static = next(item for item in panel.items() if item.text(0) == 'Static')
            self.assertFalse(static.isHidden())
            panel.tree.setCurrentItem(static)
            self.assertTrue(panel.name.isReadOnly())
            self.assertIn('Hello cached world', panel.cached_content.toPlainText())
            actions = {action.text(): action for action in panel.authoring_toolbar.actions()}
            for title in ('Remove', 'Apply', 'Up', 'Down', 'Copy', 'Paste', 'Add Content', 'Add Iteration', 'Add Field'):
                self.assertFalse(actions[title].isEnabled(), title)
            panel.name.setText('Should never be saved')
            window.apply_layout()
            window.flush_properties()
            window.move_layout_item(1)
            window.remove_layout_item()
            window.copy_layout()
            window.clauses.compose.setPlainText('RAW{@.show == false}')
            window.apply_composed()
            self.assertEqual(original, session.payload)
            nested = next(item for item in panel.items() if item.text(0) == 'Nested')
            panel.tree.setCurrentItem(nested)
            self.assertFalse(panel.name.isReadOnly())
            panel.name.setText('Renamed')
            window.apply_layout()
            self.assertEqual('Renamed', session.payload['Documents'][0]['Layouts'][0]['$$Id'])
            panel.show_cached.setChecked(False)
            self.assertEqual(2, panel.tree.topLevelItemCount())
            self.assertFalse(any(item.data(0, Qt.ItemDataRole.UserRole).get('readonly') for item in panel.items()))
