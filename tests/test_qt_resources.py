"""Every resource category and model menu routes to the original CLI contract."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication
from atool_qt.occs import CommandResult
from atool_qt.resource_actions import RESOURCE_TYPES
from atool_qt.session import demo_session
from atool_qt.user_settings import UserSettings


class FakeJob(QObject):
    completed = Signal(object)
    def __init__(self):
        super().__init__()
        self.done, self.cancelled = False, False
    def cancel(self):
        self.done = self.cancelled = True
        self.completed.emit(CommandResult(-1, '', '', None, cancelled=True))


class ResourceModelTests(unittest.TestCase):
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
        settings.payload['occs'].update(comms_cache_dir=str(self.root / 'cache'), models_dir=str(self.root / 'models'))
        settings.save()
        self.window.comms.settings = settings
        self.window.set_session(demo_session())
        self.addCleanup(self.window.close)

    def test_all_resource_categories_commands_mru_and_independent_cancel(self):
        window, calls = self.window, []
        job = FakeJob()
        def command(title, args, callback=None, **kwargs):
            calls.append((args, kwargs))
            return job
        with patch.object(window, 'run_comms_operation', side_effect=command):
            for label, single, batch, folder in RESOURCE_TYPES:
                window.download_resource(label, 'Resource')
                self.assertEqual([single, 'Resource', '--output', str(self.root / 'cache' / folder)], calls[-1][0])
                self.assertEqual('resources', calls[-1][1]['channel'])
                window.download_resource(label)
                self.assertEqual([batch, '--output', str(self.root / 'cache' / folder)], calls[-1][0])
            self.assertEqual(5, len(window.comms.settings.get('resource_cache_mru')))
            window.download_all_resources()
            self.assertEqual(['get-everything', '--output', str(self.root / 'cache')], calls[-1][0])
            self.assertEqual('download_all', calls[-1][1]['channel'])
            self.assertTrue(window.cancel_download_all_action.isEnabled())
            before = len(calls)
            window.download_all_resources()
            self.assertEqual(before, len(calls))
            window.cancel_download_all_action.trigger()
            self.assertTrue(job.cancelled)
            self.assertFalse(window.cancel_download_all_action.isEnabled())

    def test_resource_picker_uses_recent_name_and_type(self):
        window = self.window
        window.comms.settings.payload['occs']['resource_cache_mru'] = [{'type': 'Content', 'name': 'Welcome'}]
        window.open_resource_download(single=True)
        dialog = window.resource_dialog
        dialog.recent.setCurrentIndex(1)
        self.assertEqual('Welcome', dialog.resource_name.text())
        self.assertEqual('Content', dialog.resource_type.currentText())
        with patch.object(window, 'download_resource') as download:
            dialog.submit()
        download.assert_called_once_with('Content', 'Welcome')

    def test_model_view_uses_cached_file_generate_regenerates_and_all_command(self):
        window = self.window
        cache = self.root / 'cache'
        cache.mkdir()
        (cache / 'resource.json').write_text('{}')
        output = self.root / 'models' / window.session.name / 'BILL-inspector.html'
        output.parent.mkdir(parents=True)
        output.write_text('<html>cached</html>')
        calls = []
        result = CommandResult(0, '', '', None)
        def command(title, args, callback=None, **kwargs):
            self.assertTrue(kwargs.get('close_on_success'))
            calls.append(args)
            if '--all' not in args:
                Path(args[args.index('--output') + 1]).write_text('<html>generated</html>')
            if callback:
                callback(result)
        with patch.object(window, 'open_output_file') as opener, patch.object(window, 'run_comms_operation', side_effect=command):
            window.document_model(open_after=True)
            opener.assert_called_once_with('HTML', output)
            self.assertFalse(calls)
            window.document_model(regenerate=True)
            self.assertEqual(['mockup', 'BILL', '--cache', str(cache), '--package', window.session.name, '--output', str(output)], calls[-1])
            window.generate_all_models()
            self.assertEqual(['mockup', '--package', window.session.name, '--all', '--cache', str(cache), '--output', str(output.parent)], calls[-1])
        self.assertEqual('<html>generated</html>', output.read_text())

    def test_model_completion_requires_output_and_empty_cache_blocks_command(self):
        window = self.window
        with patch.object(window, 'report_error') as error, patch.object(window, 'run_comms_operation') as command:
            window.document_model(regenerate=True)
        command.assert_not_called()
        self.assertIn('resources', error.call_args.args[1].lower())
        cache = self.root / 'cache'
        cache.mkdir()
        (cache / 'resource.json').write_text('{}')
        def command(title, args, callback=None, **kwargs):
            callback(CommandResult(0, '', '', None))
        with patch.object(window, 'report_error') as error, patch.object(window, 'run_comms_operation', side_effect=command):
            window.document_model(regenerate=True)
        self.assertIn('did not create', error.call_args.args[1])

    def test_resource_dialog_actual_submit_and_cancel_controls(self):
        from PySide6.QtWidgets import QDialogButtonBox
        window = self.window
        for single in (True, False):
            window.open_resource_download(single=single)
            dialog = window.resource_dialog
            buttons = dialog.findChild(QDialogButtonBox)
            submit = buttons.button(QDialogButtonBox.StandardButton.Save)
            self.assertEqual(submit.text(), 'Refresh Cache' if single else 'Download')
            if single:
                with patch.object(window, 'download_resource') as download:
                    submit.click()
                download.assert_not_called()
                self.assertIn('required', dialog.status.text())
                self.assertTrue(dialog.isVisible())
            dialog.resource_type.setCurrentText('Layout')
            dialog.resource_name.setText('  Header  ')
            with patch.object(window, 'download_resource') as download:
                submit.click()
            download.assert_called_once_with('Layout', 'Header' if single else None)
            self.assertFalse(dialog.isVisible())
            window.open_resource_download(single=single)
            with patch.object(window, 'download_resource') as download:
                window.resource_dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).click()
            download.assert_not_called()
            self.assertFalse(window.resource_dialog.isVisible())
