"""Settings and configuration behavior; remote commands are captured locally."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox
from atool_qt.configuration import ConfigLockouts, ConfigPicker, filtered_configs, lockout_window, login_args, normalize_configs
from atool_qt.occs import CommandResult
from atool_qt.session import demo_session
from atool_qt.user_settings import SettingsDialog, UserSettings


def config_result():
    return {'configs': [{'id': '10', 'shortName': 'Alpha', 'name': 'A', 'status': 'Open'},
                        {'id': '20', 'shortName': 'Beta', 'status': 'Open'},
                        {'id': '30', 'shortName': 'Old', 'status': 'Closed'}]}


class SettingsStorageTests(unittest.TestCase):
    def test_defaults_unknown_settings_validation_and_external_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'settings.json'
            path.write_text(json.dumps({'occs': {'session_alias': 'np', 'custom': [1]}, 'extra': {'keep': True}}))
            settings = UserSettings(path)
            self.assertTrue(settings.section('application')['confirm_on_quit'])
            self.assertEqual('pp', settings.get('config_target_session_alias'))
            changed = copy.deepcopy(settings.payload)
            changed['occs']['config_id_filter'] = '['
            with self.assertRaisesRegex(ValueError, 'regular expression'):
                settings.save(changed)
            settings.payload['occs']['request_timeout_seconds'] = 120
            settings.save()
            saved = json.loads(path.read_text())
            self.assertEqual({'keep': True}, saved['extra'])
            self.assertEqual([1], saved['occs']['custom'])
            self.assertEqual(120000, settings.timeout_ms)
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'changed outside'):
                settings.save()
            self.assertEqual('{}', path.read_text())

    def test_locks_windows_boundaries_and_concurrent_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigLockouts(Path(temporary) / 'lockouts.json')
            payload = store.read()
            payload['locked_config_ids'] = ['AbC']
            payload['extra'] = 'preserved'
            payload['lockout_windows'].append(lockout_window('2026-10-08', '10:00', 'America/New_York', 60))
            store.save(payload)
            self.assertIn('locked', store.message('abc', 'Alpha'))
            self.assertIn('window', store.message('other', now=datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)))
            self.assertEqual('', store.message('other', now=datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)))
            self.assertEqual('preserved', store.read()['extra'])
            store.path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'changed'):
                store.save(payload)
            with self.assertRaisesRegex(ValueError, 'Duration'):
                lockout_window('2026-10-08', '10:00', 'UTC', 0)

    def test_config_normalization_filter_and_saved_login_target(self):
        configs = normalize_configs(config_result())
        self.assertEqual(['Alpha', 'Beta'], [config['shortName'] for config in filtered_configs(configs)])
        self.assertEqual(['Alpha'], [config['shortName'] for config in filtered_configs(configs, 'Alpha|10')])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'session.json'
            path.write_text(json.dumps({'aliases': {'pp': 'target'}, 'sessions': {'target': {
                'customer': 'Customer', 'region': 'Region', 'tenancy': 'Tenancy', 'token': 'not-read'}}}))
            self.assertEqual(['login', '--session', 'pp', '--customer', 'Customer', '--region', 'Region', '--tenancy', 'Tenancy'], login_args('pp', path))
            self.assertNotIn('not-read', str(login_args('pp', path)))


class SettingsConfigInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from atool_qt.window import WorkspaceWindow
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.window = WorkspaceWindow(QSettings(str(self.root / 'qt.ini'), QSettings.Format.IniFormat))
        settings = UserSettings(self.root / 'user.json')
        settings.payload['application']['confirm_on_quit'] = False
        settings.payload['occs'].update(shared_workspace_dir=str(self.root / 'shared'), session_alias='default', config_source_session_alias='np', config_target_session_alias='pp')
        settings.save()
        self.window.comms.settings = settings
        self.window.set_session(demo_session())
        self.addCleanup(self.finish)

    def finish(self):
        self.window.comms.settings.payload['application']['confirm_on_quit'] = False
        with patch('atool_qt.authoring.QMessageBox.question', return_value=QMessageBox.StandardButton.Discard):
            self.window.close()

    def test_settings_dialog_persists_hierarchy_and_quit_cancel(self):
        window = self.window
        window.documents.matched_only.setChecked(False)
        dialog = SettingsDialog(window)
        dialog.controls[('document_display', 'collapse')].setChecked(True)
        dialog.controls[('occs', 'session_alias')].setText('new')
        dialog.controls[('occs', 'request_timeout_seconds')].setValue(90)
        dialog.save()
        self.assertEqual('new', window.comms.settings.get('session_alias'))
        self.assertTrue(window.documents.hierarchy)
        self.assertEqual(1, window.documents.tree.topLevelItemCount())
        self.assertEqual(4, len(list(window.documents.items())))
        window.select_name(window.documents, 'BILL_CREDIT')
        self.assertEqual('BILL_CREDIT', window.selected_record('documents')['name'])
        self.assertTrue(window.documents.tree.topLevelItem(0).isExpanded())
        window.documents.search.setText('credit')
        self.assertFalse(window.documents.tree.topLevelItem(0).isHidden())
        window.comms.settings.payload['application']['confirm_on_quit'] = True
        with patch('atool_qt.user_settings.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(window.close())
        window.comms.settings.payload['application']['confirm_on_quit'] = False
        self.assertTrue(window.confirm_quit())
        self.assertEqual(90, json.loads((self.root / 'user.json').read_text())['occs']['request_timeout_seconds'])

    def test_lock_blocks_close_and_migration_even_when_command_uses_short_name(self):
        window = self.window
        self.assertTrue(window.set_active_config({'id': '10', 'shortName': 'Alpha'}))
        with patch('atool_qt.configuration.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), patch.object(window, 'require_shared_sync', return_value=True):
            self.assertTrue(window.toggle_config_lock('10', 'Alpha'))
        self.assertEqual('Unlock', window.config_actions['Lock'].text())
        with patch.object(window, 'report_error') as error, patch.object(window, 'run_comms_operation') as command:
            self.assertFalse(window.close_config('np', 'Alpha', 'Alpha', protection_id='10'))
            window.migrate_config(confirm=False)
        command.assert_not_called()
        self.assertEqual(2, error.call_count)
        with patch('atool_qt.configuration.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), patch.object(window, 'require_shared_sync', return_value=False):
            self.assertFalse(window.toggle_config_lock('10', 'Alpha'))
        self.assertTrue(window.config_is_locked('10'))

    def test_create_list_selection_close_and_migration_command_contracts(self):
        window = self.window
        calls = []
        result = CommandResult(0, '', '', config_result())
        def command(title, args, callback=None, **kwargs):
            calls.append(args)
            if callback:
                callback(result)
        with patch.object(window, 'run_comms_operation', side_effect=command):
            window.load_configs('set')
            self.assertEqual(['list-configs', '--timeout', '360000'], calls[-1])
            window.config_dialog.picker.setCurrentIndex(1)
            window.config_dialog.submit()
            self.assertEqual('20', window.comms.settings.get('last_config_id'))
            window.load_configs('close')
            self.assertIn('np', calls[-1])
            dialog = window.config_dialog
            dialog.picker.setCurrentIndex(0)
            # Yes for close; No for the follow-up migration question.
            with patch('atool_qt.configuration.QMessageBox.question', side_effect=[QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No]):
                dialog.submit()
            self.assertEqual(['close-config', '--session', 'np', '--config-id', 'Alpha'], calls[-1])
            window.migrate_config(confirm=False)
            self.assertEqual(['pp', 'np', 'default'], [args[args.index('--session') + 1] for args in calls[-4:-1]])
            self.assertEqual(['migrate', '--source-session', 'np', '--target-session', 'pp'], calls[-1])
        window.create_config()
        dialog = window.create_config_dialog
        dialog.short_name.setText('Created')
        dialog.description.setText('Description')
        created = CommandResult(0, '', '', {'config': {'id': '99', 'shortName': 'Created'}})
        def create_command(title, args, callback=None, **kwargs):
            calls.append(args)
            callback(created)
        with patch.object(window, 'run_comms_operation', side_effect=create_command), patch('atool_qt.configuration.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.submit()
        self.assertEqual(['create-config', '--short-name', 'Created', '--name', 'Created', '--desc', 'Description', '--timeout', '360000'], calls[-1])
        self.assertEqual('99', window.comms.settings.get('last_config_id'))
        self.assertEqual('Active: Created', window.active_config_action.text())

    def test_add_remove_lockout_dialog_updates_same_shared_store(self):
        window = self.window
        window.open_config_lockouts()
        dialog = window.lockouts_dialog
        dialog.add()
        with patch.object(window, 'require_shared_sync', return_value=True):
            dialog.add_dialog.save()
        self.assertEqual(1, dialog.tree.topLevelItemCount())
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
        with patch.object(window, 'require_shared_sync', return_value=True), patch('atool_qt.configuration.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.remove()
        self.assertEqual([], window.lockouts().read()['lockout_windows'])
        dialog.close()

    def test_open_settings_cancel_preserves_active_settings_and_manual_view(self):
        from PySide6.QtWidgets import QDialogButtonBox
        window=self.window
        window.toggle_document_view()
        hierarchy=window.documents.hierarchy
        active=window.comms.settings
        before=copy.deepcopy(active.payload)
        original=active.path.read_bytes()
        window.open_user_settings()
        dialog=window.user_settings_dialog
        self.assertIs(window.comms.settings,active)
        self.assertEqual(window.documents.hierarchy,hierarchy)
        self.assertEqual(dialog.controls[('document_display','collapse')].isChecked(),hierarchy)
        dialog.controls[('occs','session_alias')].setText('cancelled')
        dialog.controls[('document_display','collapse')].setChecked(not hierarchy)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).click()
        self.assertIs(window.comms.settings,active)
        self.assertEqual(active.payload,before)
        self.assertEqual(active.path.read_bytes(),original)
        self.assertEqual(window.documents.hierarchy,hierarchy)

    def test_settings_all_browse_buttons_update_only_their_draft_field(self):
        from PySide6.QtWidgets import QFileDialog
        dialog=SettingsDialog(self.window)
        directory_keys={'work_dir','shared_workspace_dir','models_dir','comms_cache_dir'}
        for key,button in dialog.browse_controls.items():
            widget=dialog.controls[key]
            old=widget.text()
            choice=str(self.root/(key[1]+' chosen'))
            with patch.object(QFileDialog,'getExistingDirectory',return_value=choice) as directory,patch.object(QFileDialog,'getOpenFileName',return_value=(choice,'')) as file:
                button.click()
                self.assertEqual(widget.text(),choice)
                (directory if key[1] in directory_keys else file).assert_called_once()
            with patch.object(QFileDialog,'getExistingDirectory',return_value=''),patch.object(QFileDialog,'getOpenFileName',return_value=('','')):
                button.click()
                self.assertEqual(widget.text(),choice)
        self.assertGreaterEqual(len(dialog.browse_controls),7)
        dialog.reject()

    def test_settings_save_installs_validated_draft_and_reopen_can_resolve_file_conflict(self):
        from PySide6.QtWidgets import QDialogButtonBox
        window=self.window
        active=window.comms.settings
        window.open_user_settings()
        dialog=window.user_settings_dialog
        dialog.controls[('occs','session_alias')].setText('new-alias')
        payload=json.loads(active.path.read_text());payload['external_unknown']={'keep':True}
        active.path.write_text(json.dumps(payload))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        self.assertIn('changed',dialog.status.text())
        self.assertIs(window.comms.settings,active)
        dialog.reject()
        window.open_user_settings()
        dialog=window.user_settings_dialog
        dialog.controls[('occs','session_alias')].setText('new-alias')
        dialog.controls[('document_display','collapse')].setChecked(True)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        self.assertIs(window.comms.settings,dialog.store)
        self.assertEqual(window.comms.settings.get('session_alias'),'new-alias')
        self.assertTrue(window.settings.value('documentHierarchy',type=bool))
        self.assertEqual(json.loads(active.path.read_text())['external_unknown'],{'keep':True})

    def test_lockout_calendar_timezone_duration_and_actual_save_cancel_buttons(self):
        from PySide6.QtCore import QDate, QTime
        from PySide6.QtWidgets import QDialogButtonBox, QPushButton
        window = self.window
        window.open_config_lockouts()
        dialog = window.lockouts_dialog
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        buttons['Add…'].click()
        draft = dialog.add_dialog
        draft.date.setDate(QDate(2026, 12, 31))
        calendar = draft.date.calendarWidget()
        calendar.setCurrentPage(2026, 12)
        calendar.showNextMonth()
        self.assertEqual((2027, 1), (calendar.yearShown(), calendar.monthShown()))
        calendar.showPreviousMonth()
        self.assertEqual((2026, 12), (calendar.yearShown(), calendar.monthShown()))
        draft.time.setTime(QTime(23, 30))
        draft.zone.setCurrentText('America/New_York')
        draft.minutes.setValue(120)
        self.assertEqual({'start': '2026-12-31T23:30:00-05:00', 'end': '2027-01-01T01:30:00-05:00',
                          'timezone': 'America/New_York'}, draft.value())
        self.assertIn('Your local time', draft.status.text())
        save = draft.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save)
        with patch.object(window, 'require_shared_sync', return_value=False):
            save.click()
        self.assertTrue(draft.isVisible())
        self.assertEqual([], window.lockouts().read()['lockout_windows'])
        with patch.object(window, 'require_shared_sync', return_value=True):
            save.click()
        self.assertFalse(draft.isVisible())
        self.assertEqual(1, dialog.tree.topLevelItemCount())
        original = window.lockouts().path.read_bytes()
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
        with patch('atool_qt.configuration.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            buttons['Remove'].click()
        self.assertEqual(original, window.lockouts().path.read_bytes())
        buttons['Add…'].click()
        dialog.add_dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).click()
        self.assertEqual(original, window.lockouts().path.read_bytes())
        buttons['Refresh'].click()
        self.assertEqual(1, dialog.tree.topLevelItemCount())
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
        with patch('atool_qt.configuration.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), patch.object(window, 'require_shared_sync', return_value=True):
            buttons['Remove'].click()
        self.assertEqual([], window.lockouts().read()['lockout_windows'])
        dialog.close()
        self.assertFalse(dialog.isVisible())

    def test_config_list_actual_buttons_filter_selection_and_lock_state(self):
        window = self.window
        dialog = ConfigPicker(window, filtered_configs(normalize_configs(config_result())), 'list', 'np')
        dialog.show()
        self.assertFalse(dialog.lock_button.isEnabled())
        self.assertFalse(dialog.submit_button.isEnabled())
        self.assertEqual('Beta', dialog.tree.topLevelItem(0).text(1))
        selected = dialog.tree.topLevelItem(0)
        dialog.tree.setCurrentItem(selected)
        with patch('atool_qt.configuration.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), patch.object(window, 'require_shared_sync', return_value=True):
            dialog.lock_button.click()
        self.assertEqual('Unlock Configuration', dialog.lock_button.text())
        self.assertEqual('Beta', dialog.current()['shortName'])
        self.assertTrue(window.config_is_locked('20'))
        with patch.object(window, 'report_error') as error, patch.object(window, 'run_comms_operation') as command:
            dialog.submit_button.click()
        command.assert_not_called()
        error.assert_called_once()
        dialog.search.setText('Alpha')
        self.assertIsNone(dialog.current())
        self.assertFalse(dialog.lock_button.isEnabled())
        self.assertFalse(dialog.submit_button.isEnabled())
        dialog.search.clear()
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
        with patch('atool_qt.configuration.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), patch.object(window, 'require_shared_sync', return_value=True):
            dialog.lock_button.click()
        self.assertFalse(window.config_is_locked('20'))
        self.assertEqual('Lock Configuration', dialog.lock_button.text())
        with patch.object(window, 'close_config', return_value=True) as close:
            dialog.submit_button.click()
        close.assert_called_once_with('np', '20', 'Beta', protection_id='20')
        self.assertFalse(dialog.isVisible())
