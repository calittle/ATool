"""Original menu routing, platform accelerators and build identity."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from atool_qt.build_info import about_text, build_info
from atool_qt.user_settings import UserSettings


class BuildInfoTests(unittest.TestCase):
    def test_packaged_release_build_contact_and_unknown_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'BUILD_INFO.txt').write_text('release_tag=v1.2\ncommit=abcdef123456\nsource=release\nbuilt_at=today\nartifact=ATool.zip\nextra=preserved\n')
            info = build_info(root)
            self.assertEqual(info['extra'], 'preserved')
            text = about_text(root)
            for part in ('ATool for OCCS', 'Qt workspace', 'Release: v1.2', 'Source: release', 'Built: today', 'Artifact: ATool.zip', 'andy.little@oracle.com'):
                self.assertIn(part, text)

    def test_git_dirty_commit_and_missing_git_fallback(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            outputs = ['abcdef123\n', '', '?? Qt.py\n']
            with patch('atool_qt.build_info.subprocess.run', side_effect=[subprocess.CompletedProcess([], 0, value, '') for value in outputs]):
                self.assertEqual(build_info(temporary)['build_label'], 'abcdef1-dirty')
            with patch('atool_qt.build_info.subprocess.run', side_effect=FileNotFoundError):
                self.assertEqual(build_info(temporary)['build_label'], 'local')


class MenuParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.window = WorkspaceWindow(QSettings(str(root / 'qt.ini'), QSettings.Format.IniFormat))
        settings = UserSettings(root / 'user.json')
        settings.payload['application']['confirm_on_quit'] = False
        settings.payload['occs'].update(work_dir=str(root / 'work'), shared_workspace_dir=str(root / 'shared'))
        self.window.comms.settings = settings
        self.addCleanup(self.window.close)

    @staticmethod
    def shortcuts(action):
        return [key.toString(QKeySequence.SequenceFormat.PortableText) for key in action.shortcuts()]

    def test_original_shortcuts_have_unique_open_owner_and_windows_alt_bindings(self):
        window = self.window
        window.restore_original_shortcuts(platform='win32')
        self.assertEqual(self.shortcuts(window.open_action), [])
        self.assertEqual(self.shortcuts(window.shared_open_action), ['Alt+O', 'Ctrl+O'])
        self.assertEqual(self.shortcuts(window.save_action), ['Alt+S', 'Ctrl+S'])
        self.assertEqual(self.shortcuts(window.map_action), ['Alt+M', 'Ctrl+M'])
        self.assertIn('Ctrl+Shift+Z', self.shortcuts(window.redo_action))
        window.restore_original_shortcuts(platform='darwin')
        self.assertEqual(self.shortcuts(window.shared_open_action), ['Ctrl+O'])
        self.assertEqual(self.shortcuts(window.map_action), ['Ctrl+M'])
        self.assertEqual(self.shortcuts(window.redo_action), ['Ctrl+Shift+Z'])

    def test_package_menu_order_and_advanced_controls_match_original(self):
        names = [action.text().replace('…', '...') for action in self.window.package_menu.actions() if not action.isSeparator()]
        self.assertEqual(names, ['Preview...', 'Send Email...', 'Cancel Preview', 'Open Shared Package...', 'Close Package', 'Get Packages from Comms...', 'Update Shared Package', 'Publish Package to Comms...', 'Check Shared Folder Sync...', 'Release Shared Package Lock', 'Manual Shared Package Unlock...', 'Advanced'])
        advanced = self.window.package_menu.actions()[-1].menu()
        self.assertEqual([action.text() for action in advanced.actions() if not action.isSeparator()], ['Open Local Package…', 'Open Raw AT…', 'Clean Local Packages…'])

    def test_about_is_available_in_file_menu_and_shows_actual_build_details(self):
        window = self.window
        file_menu = window.menuBar().actions()[0].menu()
        self.assertIn(window.about_action, file_menu.actions())
        self.assertEqual(window.about_action.menuRole(), QAction.MenuRole.AboutRole)
        with patch('atool_qt.build_info.about_text', return_value='verified build info'), patch.object(QMessageBox, 'information') as info:
            window.about_action.trigger()
            info.assert_called_once_with(window, 'About ATool', 'verified build info')

    def test_open_keyboard_shortcut_opens_shared_picker(self):
        window = self.window
        window.show()
        window.activateWindow()
        self.app.processEvents()
        QTest.keyClick(window, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertTrue(window.shared_picker.isVisible())
        self.addCleanup(window.shared_picker.close)

    def test_clause_picker_inserts_independently_and_survives_refresh(self):
        from atool_qt.session import demo_session
        window = self.window
        session = demo_session()
        session.clauses = [{'name': 'A', 'expression': '@.flag == true', 'description': ''},
                           {'name': 'Name With Spaces', 'expression': '@.value > 0', 'description': ''}]
        window.set_session(session)
        window.clauses.clause_picker.setCurrentText('Name With Spaces')
        selected = window.selected_clause()['name']
        window.clauses.compose.clear()
        insert = next(action for action in window.clauses.authoring_toolbar.actions() if action.text() == 'Insert Name')
        insert.trigger()
        self.assertEqual(window.clauses.compose.toPlainText(), 'CLAUSE{Name With Spaces}')
        self.assertEqual(window.selected_clause()['name'], selected)
        window.set_session(session, preserve_selection=True)
        self.assertEqual(window.clauses.clause_picker.currentText(), 'Name With Spaces')
        window.clauses.search.setText('no clause matches this')
        self.assertFalse(insert.isEnabled())
        window.clauses.clause_picker.setCurrentText('A')
        self.assertTrue(insert.isEnabled())

    def test_clause_composer_help_button_describes_original_syntax(self):
        panel = self.window.clauses
        with patch.object(QMessageBox, 'information') as info:
            panel.compose_help.click()
            title, message = info.call_args.args[1:]
            self.assertEqual(title, 'Composer Help')
            for syntax in ('AND', 'OR', 'RAW{...}', 'CLAUSE{name}', 'Tab or Enter', 'Ctrl+Space'):
                self.assertIn(syntax, message)

    def test_show_local_storage_opens_package_folder_and_reports_browser_errors(self):
        window = self.window
        directory = window.comms.settings.work_dir
        self.assertFalse(directory.exists())
        with patch('atool_qt.authoring.QDesktopServices.openUrl', return_value=True) as browser:
            window.storage_action.trigger()
        self.assertTrue(directory.is_dir())
        self.assertEqual(str(directory), browser.call_args.args[0].toLocalFile())
        with patch('atool_qt.authoring.QDesktopServices.openUrl', return_value=False), patch.object(window, 'report_error') as error:
            window.storage_action.trigger()
        self.assertIn('system file browser', error.call_args.args[1])
        with patch.object(Path, 'mkdir', side_effect=OSError('Folder unavailable')), patch('atool_qt.authoring.QDesktopServices.openUrl') as browser, patch.object(window, 'report_error') as error:
            window.storage_action.trigger()
        browser.assert_not_called()
        self.assertIn('Folder unavailable', error.call_args.args[1])

    def test_window_menu_shows_every_manager_and_arrange_restores_default_tabs(self):
        window = self.window
        window.show()
        menu = next(action.menu() for action in window.menuBar().actions() if action.text() == '&Window')
        actions = {action.text(): action for action in menu.actions()}
        for name, key in [('Document Manager', 'documents'), ('Field Manager', 'fields'), ('Clause Manager', 'clauses'), ('Layout Manager', 'layouts'), ('Data Browser', 'data'), ('Content Manager', 'content')]:
            dock = window.docks[key]
            dock.hide()
            actions[name].trigger()
            self.app.processEvents()
            self.assertFalse(dock.isHidden(), name)
            self.assertTrue(dock.isVisible(), name)
        window.docks['fields'].setFloating(True)
        window.docks['fields'].hide()
        actions['Arrange'].trigger()
        self.app.processEvents()
        self.assertFalse(window.docks['fields'].isFloating())
        self.assertFalse(window.docks['fields'].isHidden())
        tabs = window.tabifiedDockWidgets(window.docks['fields'])
        self.assertIn(window.docks['clauses'], tabs)
        self.assertIn(window.docks['data'], tabs)
        self.assertTrue(window.docks['content'].isHidden())

    def test_remap_menu_reloads_last_input_file_in_current_package(self):
        import json, time
        from atool_qt.session import demo_session
        window = self.window
        path = window.comms.settings.path.parent / 'mapped.json'
        path.write_text(json.dumps({'balance': 1, 'customer': {'name': 'Before'}}))
        window.settings.setValue('lastDataFile', str(path))
        window.set_session(demo_session())
        self.assertTrue(window.remap_action.isEnabled())
        path.write_text(json.dumps({'balance': 0, 'customer': {'name': 'After'}}))
        window.remap_action.trigger()
        deadline = time.monotonic() + 5
        while window.job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertIsNone(window.job)
        self.assertEqual(window.session.data['customer']['name'], 'After')
        self.assertEqual(next(row for row in window.session.fields if row['name'] == 'Balance')['mapped_values'], [0])
        self.assertTrue(window.remap_action.isEnabled())
