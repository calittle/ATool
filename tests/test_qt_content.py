"""Content workflows use original CLI contracts and protect unsaved HTML."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from atool_qt.content import content_fields
from atool_qt.occs import CommandResult
from atool_qt.session import demo_session
from atool_qt.user_settings import UserSettings


class FakeJob(QObject):
    completed = Signal(object)
    def __init__(self):
        super().__init__()
        self.done = False


class ContentTests(unittest.TestCase):
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
        settings.payload['occs']['last_config_id'] = '42'
        self.window.comms.settings = settings
        self.window.set_session(demo_session())
        self.panel = self.window.content
        self.calls = []
        self.runner = patch.object(self.window, 'run_comms_operation', side_effect=self.command)
        self.runner.start()
        self.addCleanup(self.runner.stop)
        self.addCleanup(self.close)

    def close(self):
        self.panel.loading = self.panel.saving = False
        self.panel.baseline = self.panel.snapshot()
        self.window.editor.saved = self.window.editor.snapshot()
        self.window.close()

    def command(self, title, args, callback=None, **kwargs):
        job = FakeJob()
        self.calls.append(dict(args=args, callback=callback, job=job, options=kwargs))
        return job

    def complete(self, index, value=None, cancelled=False):
        call = self.calls[index]
        result = CommandResult(-1 if cancelled else 0, '', '', value, cancelled=cancelled)
        if not cancelled and isinstance(value, dict) and call['callback']:
            call['callback'](result)
        call['job'].done = True
        call['job'].completed.emit(result)

    def load_fixture(self):
        self.panel.inspect_content('Welcome')
        self.complete(0, {'content': {'shortName': 'Welcome', 'name': 'Welcome letter', 'description': 'First page'},
                         'versions': [{'shortName': '1.0'}, {'shortName': '2.0'}]})
        html = '<p class="unfamiliar" data-custom="keep">Hello <comms-data>$Data{"Id":"Account"}</comms-data></p>'
        self.complete(1, {'version': {'shortName': '1.0', 'effectiveDate': '2026-10-08T00:00:00.000000Z', 'description': 'Initial'}, 'html': html})
        self.complete(2, {'styles': [{'shortName': 'Body', 'classNames': ['body', 'large']}]})
        return html

    def test_dock_menu_and_content_listing_filters(self):
        self.assertIn('content', self.window.docks)
        self.assertTrue(any(action.text() == 'Content Manager' for menu in self.window.menuBar().actions() if menu.menu() for action in menu.menu().actions()))
        with patch.object(self.window, 'report_error') as error:
            self.panel.list_contents()
        self.assertFalse(self.calls)
        self.assertIn('filter', error.call_args.args[1])
        self.panel.filter.setText('Welcome')
        self.panel.content_type.setCurrentText('Text')
        self.panel.list_contents('config', True)
        self.assertEqual(['content', 'list', '--timeout', '360000', '--config-id', '42', '--filter', 'Welcome', '--type', 'Text'], self.calls[-1]['args'])
        self.assertEqual('read', self.calls[-1]['options']['channel'])
        self.complete(0, {'contents': [{'shortName': 'Welcome', 'contentType': 'Text'}, None]})
        self.assertEqual(1, self.panel.browser.topLevelItemCount())
        self.assertEqual('Welcome', self.panel.browser.topLevelItem(0).text(0))

    def test_inspect_version_styles_source_unchanged_and_cancel(self):
        html = self.load_fixture()
        self.assertEqual(html, self.panel.source.toPlainText())
        self.assertFalse(self.panel.dirty)
        self.assertEqual('2026-10-08', self.panel.effective_date.text())
        self.assertEqual('body, large', self.panel.styles.topLevelItem(0).text(1))
        self.assertEqual(['content', 'inspect', 'Welcome', '--timeout', '360000'], self.calls[0]['args'])
        self.assertEqual(['content', 'read', 'Welcome', '1.0', '--timeout', '360000'], self.calls[1]['args'])
        self.assertEqual(['content', 'styles', 'Welcome', '1.0', '--timeout', '360000'], self.calls[2]['args'])
        self.panel.source.insertPlainText('edited')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.panel.version.setCurrentText('2.0')
            self.panel.select_version()
            self.assertEqual('1.0', self.panel.version.currentText())
            self.assertFalse(self.panel.confirm_discard('quitting'))
        self.panel.baseline = self.panel.snapshot()
        self.panel.read_version('Welcome', '2.0')
        self.complete(3, cancelled=True)
        self.assertFalse(self.panel.loading)
        self.assertEqual('1.0', self.panel.version.currentText())
        self.assertTrue(self.panel.editor_panel.isEnabled())
        # A later revision invalidates callbacks from old reads and old style requests.
        self.panel.request_revision += 1
        self.complete(3, {'version': {'shortName': 'old'}, 'html': 'stale'})
        self.assertNotEqual('stale', self.panel.source.toPlainText())

    def test_scoped_fields_include_only_matching_content_and_escape_names(self):
        session = self.window.session
        session.payload['extra'] = [
            {'Name': 'Welcome', 'Iteration': {'Name': 'Bills', 'Path': '$.Bills', 'Fields': [{'Name': 'A"B', 'Path': '$.x'}]}},
            {'Name': 'Different', 'Iteration': {'Name': 'Other', 'Fields': [{'Name': 'Wrong'}]}}]
        fields, definitions = content_fields(session, 'Welcome')
        self.assertIn('A"B', [field['name'] for field in fields])
        self.assertNotIn('Wrong', [field['name'] for field in fields])
        self.assertEqual(['Bills'], [item['name'] for item in definitions])
        self.panel.short_name.setText('Welcome')
        for index in range(self.panel.fields.topLevelItemCount()):
            item = self.panel.fields.topLevelItem(index)
            if item.text(0) == 'A"B':
                self.panel.fields.setCurrentItem(item)
                break
        self.panel.insert_field()
        self.assertIn('$Data{"Id":"A\\"B"}', self.panel.source.toPlainText())
        self.assertTrue(self.panel.dirty)

    def test_create_save_and_version_uploads_cleanup_on_success_and_cancel(self):
        panel = self.panel
        panel.short_name.setText('NewLetter')
        panel.name.setText('New letter')
        panel.description.setText('Description')
        panel.version_description.setText('Version description')
        panel.effective_date.setText('2026-10-08')
        panel.source.setPlainText('<p>Exact upload</p>')
        self.assertTrue(panel.save_button.isEnabled())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            panel.submit_save()
        create = self.calls[-1]['args']
        upload = Path(create[create.index('--html') + 1])
        self.assertEqual('<p>Exact upload</p>', upload.read_text())
        self.assertEqual(['content', 'create', 'NewLetter', '--config-id', '42'], create[:5])
        self.assertIn('--effective-date', create)
        self.assertNotIn('--version-desc', create)
        self.assertFalse(panel.editor_panel.isEnabled())
        self.complete(0, {'success': True})
        self.assertFalse(upload.exists())
        self.assertFalse(panel.dirty)
        self.assertEqual('version', panel.mode)
        panel.description.setText('Edited')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            panel.submit_save()
        save = self.calls[-1]['args']
        upload = Path(save[save.index('--html') + 1])
        self.assertEqual(['content', 'save', 'NewLetter', '1.0'], save[:4])
        self.assertIn('--version-desc', save)
        self.assertNotIn('--effective-date', save)
        self.complete(1, cancelled=True)
        self.assertFalse(upload.exists())
        self.assertTrue(panel.dirty)
        self.assertFalse(panel.saving)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            panel.create_version('2.0', '2026-10-09')
        version = self.calls[-1]['args']
        upload = Path(version[version.index('--html') + 1])
        self.assertEqual(['content', 'version', 'NewLetter', '2.0', '--config-id', '42', '--from-version', '1.0'], version[:8])
        self.assertNotIn('--timeout', version)
        self.complete(2, {'success': True})
        self.assertFalse(upload.exists())
        self.assertEqual('2.0', panel.version.currentText())
        self.assertEqual('read', self.calls[-2]['args'][1])
        self.assertEqual('styles', self.calls[-1]['args'][1])

    def test_failed_load_restores_previous_metadata_and_html(self):
        html = self.load_fixture()
        self.panel.inspect_content('Different')
        self.complete(3, {'content': {'shortName': 'Different', 'name': 'Other'}, 'versions': [{'shortName': '3.0'}]})
        self.assertTrue(self.panel.loading)
        self.complete(4, {'version': None, 'html': None})
        self.assertFalse(self.panel.loading)
        self.assertEqual('Welcome', self.panel.short_name.text())
        self.assertEqual('1.0', self.panel.version.currentText())
        self.assertEqual(html, self.panel.source.toPlainText())
        self.assertFalse(self.panel.dirty)
        self.assertEqual('Body', self.panel.styles.topLevelItem(0).text(0))
        self.complete(5, {'styles': [{'shortName': 'stale', 'classNames': []}]})
        self.assertEqual('Body', self.panel.styles.topLevelItem(0).text(0))

    def test_partial_new_edits_are_dirty_and_bad_dates_never_upload(self):
        self.panel.description.setText('Partial draft')
        self.assertTrue(self.panel.dirty)
        self.panel.short_name.setText('Draft')
        self.panel.source.setPlainText('<p>Draft</p>')
        self.panel.effective_date.setText('2026-02-30')
        with patch.object(self.window, 'report_error') as error:
            self.panel.submit_save()
        self.assertFalse(self.calls)
        self.assertIn('valid date', error.call_args.args[1])
        self.panel.loading = True
        self.assertFalse(self.panel.confirm_discard('quitting'))
        self.panel.loading = False
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.window.docks['content'].close())
