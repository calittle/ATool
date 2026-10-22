"""Favorites summarize each transaction without changing package metadata."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from atool_qt.session import PackageSession

try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


def package(name='Billing'):
    return PackageSession.from_payload({
        '$$Id': name,
        'Fields': [{'Name': field, 'Path': '$.' + field} for field in
                   ('billingLanguagePreference', 'missing', 'empty', 'null', 'zero', 'flag', 'container')],
        'Meta': {'clause_library': [
            {'name': 'Scn_RegCyclic', 'expression': '@.scenario == "cyclic"'},
            {'name': 'Other', 'expression': '@.scenario == "other"'},
            {'name': 'Nested', 'expression': 'CLAUSE{Scn_RegCyclic}'},
            {'name': 'Broken', 'expression': 'CLAUSE{Absent}'}]},
        'Documents': []})


@unittest.skipIf(QApplication is None, 'Install requirements-qt.txt')
class FavoritesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.user_settings import UserSettings
        from atool_qt.window import WorkspaceWindow
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = UserSettings(Path(self.temp.name) / '.settings.json')
        self.store.payload['application']['confirm_on_quit'] = False
        with patch('atool_qt.authoring.UserSettings', return_value=self.store):
            self.window = WorkspaceWindow(QSettings(str(Path(self.temp.name) / 'ui.ini'), QSettings.Format.IniFormat))
        self.window.show()
        self.addCleanup(self.window.close)
        self.session = package()
        self.window.set_session(self.session)

    def favorite(self, kind, name, checked=True):
        panel = getattr(self.window, kind)
        items = panel.items() if kind == 'fields' else (
            panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount()))
        for item in items:
            raw = item.data(0, Qt.ItemDataRole.UserRole + 4) if kind == 'fields' else item.text(0)
            if raw == name:
                item.setCheckState(3 if kind == 'fields' else 2,
                                   Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                return
        self.fail('Missing manager item: ' + name)

    def rows(self):
        tree = self.window.favorites.tree
        return {tree.topLevelItem(i).text(0): tree.topLevelItem(i).text(2)
                for i in range(tree.topLevelItemCount())}

    def map(self, **values):
        self.session.map_data(values, 'transaction.json')
        self.window.set_session(self.session)

    def test_filters_values_clauses_and_remapping(self):
        for field in self.session.fields:
            self.favorite('fields', field['name'])
        for name in ('Scn_RegCyclic', 'Other', 'Nested', 'Broken'):
            self.favorite('clauses', name)
        self.assertEqual(set(self.rows().values()), {'No data loaded'})
        self.map(billingLanguagePreference='Chinese', scenario='cyclic', empty='', null=None,
                 zero=0, flag=False, container={})
        self.assertEqual(self.rows(), {'billingLanguagePreference': 'Chinese', 'zero': '0',
                                      'flag': 'false', 'Scn_RegCyclic': 'PASS', 'Nested': 'PASS'})
        self.window.favorites.filter.setCurrentIndex(1)
        self.assertEqual(self.rows(), {'missing': 'Unmapped', 'empty': 'Unmapped', 'null': 'Unmapped',
                                      'container': 'Unmapped', 'Other': 'FAIL'})
        self.window.favorites.filter.setCurrentIndex(2)
        self.assertEqual(self.rows()['Broken'], 'ERROR')
        self.map(billingLanguagePreference='English', scenario='other')
        self.assertEqual(self.rows()['billingLanguagePreference'], 'English')
        self.assertEqual(self.rows()['Other'], 'PASS')
        self.assertEqual(self.rows()['Scn_RegCyclic'], 'FAIL')

    def test_local_persistence_package_isolation_and_missing_names(self):
        from atool_qt.user_settings import UserSettings
        original = copy.deepcopy(self.session.payload)
        self.favorite('fields', 'billingLanguagePreference')
        self.favorite('clauses', 'Scn_RegCyclic')
        saved = UserSettings(self.store.path)
        self.assertEqual(saved.section('favorites')['Billing'], {
            'fields': ['billingLanguagePreference'], 'clauses': ['Scn_RegCyclic']})
        self.assertEqual(self.session.payload, original)
        self.assertFalse(self.window.editor.dirty)
        self.window.set_session(package('OtherPackage'))
        self.assertEqual(self.rows(), {})
        self.window.comms.settings = saved
        self.window.set_session(package())
        self.assertEqual(len(self.rows()), 2)
        self.window.session.fields.clear()
        self.window.refresh_edit()
        self.assertEqual(set(self.rows()), {'Scn_RegCyclic'})

    def test_unchecking_and_path_view_keep_checks(self):
        self.favorite('fields', 'billingLanguagePreference')
        self.window.fields.toggle_field_view()
        item = next(item for item in self.window.fields.items()
                    if item.data(0, Qt.ItemDataRole.UserRole + 4) == 'billingLanguagePreference')
        self.assertEqual(item.checkState(3), Qt.CheckState.Checked)
        item.setCheckState(3, Qt.CheckState.Unchecked)
        self.assertEqual(self.rows(), {})
        self.assertEqual(json.loads(self.store.path.read_text())['favorites']['Billing']['fields'], [])

    def test_click_opens_raw_name_and_clears_manager_filters(self):
        self.favorite('fields', 'missing')
        self.favorite('clauses', 'Other')
        self.map(scenario='cyclic')
        self.window.favorites.filter.setCurrentIndex(2)
        self.window.fields.search.setText('hidden')
        self.window.fields.matched_only.setChecked(True)
        self.window.fields.toggle_field_view()
        item = next(self.window.favorites.tree.topLevelItem(i)
                    for i in range(self.window.favorites.tree.topLevelItemCount())
                    if self.window.favorites.tree.topLevelItem(i).text(0) == 'missing')
        self.window.favorites.open_row(item)
        self.assertEqual(self.window.fields.name.text(), 'missing')
        self.assertFalse(self.window.fields.tree.currentItem().isHidden())
        self.window.clauses.search.setText('hidden')
        self.window.open_favorite('clauses', 'Other')
        self.assertEqual(self.window.clauses.name.text(), 'Other')

    def test_failed_save_restores_checkbox(self):
        with patch.object(self.store, 'save', side_effect=OSError('Read only')), \
                patch.object(self.window, 'report_error') as report:
            self.favorite('fields', 'missing')
        report.assert_called_once()
        self.assertEqual(self.rows(), {})
        item = next(item for item in self.window.fields.items()
                    if item.data(0, Qt.ItemDataRole.UserRole + 4) == 'missing')
        self.assertEqual(item.checkState(3), Qt.CheckState.Unchecked)

    def test_favorites_dock_shares_managers_and_restores_hidden_state(self):
        from atool_qt.window import WorkspaceWindow
        dock = self.window.docks['favorites']
        self.assertIn(dock, self.window.tabifiedDockWidgets(self.window.docks['fields']))
        dock.hide()
        self.window.close()
        with patch('atool_qt.authoring.UserSettings', return_value=self.store):
            reopened = WorkspaceWindow(self.window.settings)
        self.addCleanup(reopened.close)
        self.assertTrue(reopened.docks['favorites'].isHidden())
