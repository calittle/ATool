"""Configuration inventory selection, report display, and cancellation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMainWindow

from atool_qt.config_objects import ConfigObjectsDialog
from atool_qt.configuration import ConfigPicker, normalize_configs
from atool_qt.occs import CommandResult, CommsSettings


class Job(QObject):
    completed = Signal(object)
    done = False

    def cancel(self):
        self.done = True
        self.completed.emit(CommandResult(-1, '', '', None, cancelled=True))


class ConfigObjectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.workspace = QMainWindow()
        self.workspace.comms = type('Comms', (), {})()
        self.workspace.comms.settings = CommsSettings(Path(self.folder.name) / 'settings.json')
        self.calls = []
        self.workspace.run_comms_operation = self.operation
        self.addCleanup(self.workspace.close)
        self.config = normalize_configs({'configs': [{'id': '441', 'shortName': 'Test', 'status': 'Open'}]})[0]
        self.dialog = ConfigObjectsDialog(self.workspace, self.config, 'np')
        self.dialog.show()
        self.app.processEvents()
        self.addCleanup(self.dialog.close)

    def operation(self, title, args, callback=None, **kwargs):
        job = Job()
        self.calls.append(dict(args=args, callback=callback, job=job, **kwargs))
        return job

    def complete(self, value):
        call = self.calls[-1]
        result = CommandResult(0, '', '', value)
        call['job'].done = True
        call['callback'](result)
        call['job'].completed.emit(result)

    def test_session_scoped_read_only_scan_and_object_filter(self):
        args = self.calls[0]['args']
        self.assertEqual(args[0], 'preflight')
        self.assertEqual(args[args.index('--session') + 1], 'np')
        self.assertEqual(args[args.index('--config-id') + 1], '441')
        self.assertIn('--deep', args)
        self.assertTrue(self.calls[0]['require_json'])
        self.dialog.load_objects()
        self.assertEqual(len(self.calls), 1)
        self.complete({'ok': True, 'session': {'alias': 'np'}, 'results': [{
            'configurationId': '441', 'inflightCount': 1,
            'attachedRows': [{'domainNameDisplay': 'Package', 'name': 'Bills', 'versionName': '2.0',
                              'statusCode': 'Active', 'recUuid': 'package-version'}],
            'registryChanges': [{'label': 'Style', 'name': 'Body', 'operation': 'UPDATE', 'recUuid': 'style'}],
            'deepChains': [{'packageVersion': {'name': 'Bills', 'ownerShortName': 'Test'},
                            'documentVersion': {'name': 'Letter', 'ownerShortName': 'Other',
                                                'layouts': [{'name': 'Header', 'ownerShortName': 'Other'}]},
                            'externalOwner': True}],
        }]})
        self.assertEqual(self.dialog.objects.topLevelItem(0).text(1), 'Bills')
        self.assertEqual(self.dialog.changes.topLevelItem(0).text(1), 'Body')
        self.assertIn('1 in-flight', self.dialog.status.text())
        self.dialog.search.setText('Header')
        self.assertTrue(self.dialog.objects.topLevelItem(0).isHidden())
        package = self.dialog.dependencies.topLevelItem(0)
        self.assertFalse(package.isHidden())
        self.assertFalse(package.child(0).child(0).isHidden())
        self.assertEqual(package.child(0).text(2), 'Other')

    def test_mismatched_or_missing_report_is_rejected(self):
        for value in ({}, {'results': []}, {'results': [{'configurationId': '999'}]},
                      {'session': {'alias': 'pp'}, 'results': [{'configurationId': '441'}]},
                      {'session': {'alias': 'np'}, 'results': [{'configurationId': '441', 'attachedRows': None}]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.complete(value)
        self.assertEqual(self.dialog.objects.topLevelItemCount(), 0)

    def test_cancel_cleans_report_and_ignores_late_results(self):
        output = Path(self.dialog.report_folder.name)
        self.dialog.close()
        self.assertTrue(self.calls[0]['job'].done)
        self.assertFalse(output.exists())
        self.complete({'results': [{'configurationId': '441'}]})
        self.assertEqual(self.dialog.objects.topLevelItemCount(), 0)

    def test_view_objects_button_uses_selected_config_even_when_locked(self):
        self.workspace.lockouts = lambda: type('Locks', (), {'read': lambda self: {'locked_config_ids': ['441']}})()
        self.workspace.config_is_locked = lambda identity: True
        picker = ConfigPicker(self.workspace, [self.config], 'list', 'np')
        self.addCleanup(picker.close)
        self.assertFalse(picker.objects_button.isEnabled())
        picker.tree.setCurrentItem(picker.tree.topLevelItem(0))
        self.assertTrue(picker.objects_button.isEnabled())
        with patch('atool_qt.config_objects.ConfigObjectsDialog') as viewer:
            picker.objects_button.click()
        viewer.assert_called_once_with(self.workspace, self.config, 'np', parent=picker)

    def test_closing_objects_returns_to_existing_list_without_reloading(self):
        self.workspace.lockouts = lambda: type('Locks', (), {'read': lambda self: {'locked_config_ids': []}})()
        self.workspace.config_is_locked = lambda identity: False
        picker = ConfigPicker(self.workspace, [self.config], 'list', 'np')
        self.addCleanup(picker.close)
        picker.show()
        picker.search.setText('Test')
        selected = picker.tree.topLevelItem(0)
        picker.tree.setCurrentItem(selected)
        picker.objects_button.click()
        viewer = self.workspace.config_objects_dialog
        self.addCleanup(viewer.close)
        self.assertIs(viewer.parentWidget(), picker)
        calls_before_close = len(self.calls)
        with patch.object(picker, 'raise_') as raise_list, patch.object(picker, 'activateWindow') as activate_list:
            viewer.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Close).click()
        raise_list.assert_called_once()
        activate_list.assert_called_once()
        self.assertTrue(picker.isVisible())
        self.assertFalse(viewer.isVisible())
        self.assertEqual(picker.search.text(), 'Test')
        self.assertIs(picker.tree.currentItem(), selected)
        self.assertEqual(len(self.calls), calls_before_close)
