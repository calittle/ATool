"""Data menu workflows exercise original engines and Qt controls."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QPushButton
from atool_qt.data_actions import XmlConversionDialog, conversion_args, converted_paths, xml_bill_ids
from atool_qt.occs import CommsSettings
from atool_qt.user_settings import UserSettings
from atool_qt.sample_data import SampleBuilder
from atool_qt.session import PackageSession
from tests import test_layout_resolver as resolver_fixtures


class DataActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_synthesis_satisfies_document_condition_and_materializes_fields(self):
        builder = SampleBuilder()
        payload, report = builder._generate_sample_input_payload('@.enabled == true && @.amount > 10 && @.name empty false', [
            {'path': '$.amount', 'name': 'Amount'}, {'path': '$.name', 'name': 'Name'}, {'path': '$.rows[*].code', 'name': 'Code'}])
        self.assertTrue(builder._evaluate_document_condition('@.enabled == true && @.amount > 10 && @.name empty false', payload))
        self.assertTrue(builder._extract_values_by_path(payload, '$.rows[*].code'))
        self.assertIn('Document condition: satisfied.', report)

    def test_conversion_bill_ids_static_schema_and_output_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            xml = root / 'input.xml'
            xml.write_text('<x xmlns="urn:test"><billId>one</billId><billId>two</billId><billId>one</billId></x>')
            self.assertEqual(['one', 'two'], xml_bill_ids(xml))
            settings = CommsSettings(root / 'nonexistent.json')
            args = conversion_args(settings, xml, 'root', 'two')
            self.assertEqual('billId=two', args[args.index('--extract') + 1])
            self.assertIn('--reroot', args)
            self.assertEqual(xml.with_suffix('.json'), Path(args[args.index('--output') + 1]))
            settings.payload = {'occs': {'use_static_xsd_conversion': True, 'static_xsd_path': str(root / 'schema.xsd')}}
            with self.assertRaisesRegex(ValueError, 'XSD'):
                conversion_args(settings, xml)
            (root / 'schema.xsd').write_text('<schema/>')
            self.assertIn('--xsd', conversion_args(settings, xml, bill_id='All'))
            self.assertNotIn('--extract', conversion_args(settings, xml, bill_id='All'))
            output = xml.with_suffix('.json')
            self.assertEqual([root / 'one.json', output], converted_paths('Converted XML to JSON [billId=one]: one.json', output))

    def test_sample_and_resolve_menu_states_dialog_and_report_save(self):
        from atool_qt.window import WorkspaceWindow
        fixture = resolver_fixtures.LayoutResolverTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = fixture.cache
        template_path = root / 'packages/Pkg/versions/v1/AssemblyTemplate.json'
        template = json.loads(template_path.read_text())
        template['$$Id'] = 'Pkg'
        session = PackageSession.from_payload(template)
        window = WorkspaceWindow(QSettings(str(root / 'qt.ini'), QSettings.Format.IniFormat))
        window.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
        window.comms.settings.payload['occs'] = {'comms_cache_dir': str(root)}
        window.set_session(session)
        self.assertTrue(window.generate_action.isEnabled())
        self.assertFalse(window.resolve_action.isEnabled())
        window.generate_action.trigger()
        self.assertIn('Document condition:', window.sample_dialog.report.toPlainText())
        saved_sample = root / 'sample.json'
        window.sample_dialog.json.setPlainText('{"editable": true}')
        with patch('atool_qt.data_actions.QFileDialog.getSaveFileName', return_value=(str(saved_sample), '')):
            next(button for button in window.sample_dialog.findChildren(QPushButton) if button.text() == 'Save As…').click()
        self.assertEqual({'editable': True}, json.loads(saved_sample.read_text()))
        window.sample_dialog.close()
        session.map_data({'show': True, 'name': 'Alice', 'address': '123 Main St'}, 'data')
        window.set_session(session)
        self.assertTrue(window.resolve_action.isEnabled())
        window.resolve_action.trigger()
        dialog = window.resolve_dialog
        controls = {button.text(): button for button in dialog.findChildren(QPushButton)}
        with patch('atool_qt.data_actions.QFileDialog.getExistingDirectory', return_value=str(root)):
            controls['Browse…'].click()
        self.assertEqual(dialog.cache.text(), str(root))
        from PySide6.QtCore import QDate
        dialog.date.setDate(QDate(2026, 10, 8))
        self.assertTrue(dialog.date.calendarPopup())
        dialog.date.calendarWidget().showNextMonth()
        self.assertEqual(dialog.date.calendarWidget().monthShown(), 11)
        controls['Refresh'].click()
        self.assertEqual('header', dialog.layout_picker.currentText())
        controls['Resolve'].click()
        deadline = time.monotonic() + 5
        while window.local_jobs and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertFalse(window.local_jobs)
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertIn('Alice', str(dialog.result))
        root_item = dialog.tree.topLevelItem(0)
        self.assertEqual(root_item.text(1), 'Document')
        self.assertEqual(root_item.text(2), 'PASS')
        layout_item = root_item.child(0)
        self.assertEqual(layout_item.text(0), 'header')
        self.assertGreater(layout_item.childCount(), 0)
        controls['Collapse All'].click()
        self.assertFalse(root_item.isExpanded())
        controls['Expand All'].click()
        self.assertTrue(root_item.isExpanded())
        self.assertTrue(layout_item.isExpanded())
        dialog.tree.setCurrentItem(layout_item)
        self.assertIn('header', dialog.report.toPlainText())
        saved = root / 'evidence.json'
        with patch('atool_qt.data_actions.QFileDialog.getSaveFileName', return_value=(str(saved), '')):
            controls['Save…'].click()
        self.assertEqual(dialog.result, json.loads(saved.read_text()))
        report = root / 'report.txt'
        with patch('atool_qt.data_actions.QFileDialog.getSaveFileName', return_value=(str(report), '')):
            controls['Save…'].click()
        from atool_core.layout_resolver import format_report
        self.assertEqual(report.read_text(), format_report(dialog.result))
        with patch('atool_qt.data_actions.QFileDialog.getSaveFileName', return_value=('', '')):
            controls['Save…'].click()
        dialog.close()
        window.close()

    def test_conversion_completion_maps_first_existing_generated_file(self):
        from atool_qt.window import WorkspaceWindow
        from atool_qt.occs import CommandResult
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window = WorkspaceWindow(QSettings(str(root / 'qt.ini'), QSettings.Format.IniFormat))
            window.comms.settings.payload.setdefault('application', {})['confirm_on_quit'] = False
            window.set_session(PackageSession.from_payload({'Documents': [], 'Fields': []}))
            dialog = XmlConversionDialog(window, map_after=True)
            generated = root / 'bill.json'
            generated.write_text('{"bill": true}')
            with patch.object(window, 'map_file') as mapping:
                dialog.conversion_finished(CommandResult(0, 'Converted XML to JSON [billId=one]: bill.json', '', None), root / 'input.json')
            mapping.assert_called_once_with(generated, on_complete=dialog.mapping_finished)
            window.set_session(PackageSession.from_payload({'Documents': [], 'Fields': []}))
            with patch.object(window, 'map_file') as mapping:
                dialog.conversion_finished(CommandResult(0, '', '', None), generated)
            mapping.assert_not_called()
            self.assertIn('package changed', dialog.status.text())
            dialog.close()
            window.close()

    def test_conversion_actual_browse_run_cancel_and_close_controls(self):
        from PySide6.QtCore import QObject, Signal
        from atool_qt.occs import CommandResult
        from atool_qt.user_settings import UserSettings
        from atool_qt.window import WorkspaceWindow
        class Job(QObject):
            output = Signal(str)
            def __init__(self, callback):
                super().__init__()
                self.done = False
                self.callback = callback
            def cancel(self):
                self.done = True
                self.callback(CommandResult(-1, '', '', None, cancelled=True))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window = WorkspaceWindow(QSettings(str(root / 'qt.ini'), QSettings.IniFormat))
            settings = UserSettings(root / 'user.json')
            settings.payload['application']['confirm_on_quit'] = False
            window.comms.settings = settings
            self.addCleanup(window.close)
            window.set_session(PackageSession.from_payload({'Documents': [], 'Fields': []}))
            window.convert_action.trigger()
            dialog = window.conversion_dialog
            buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
            with patch.object(window.comms, 'submit') as submit:
                buttons['Convert'].click()
            submit.assert_not_called()
            self.assertIn('existing XML', dialog.status.text())
            xml = root / 'one.xml'
            xml.write_text('<root><billId>one</billId></root>')
            with patch('atool_qt.data_actions.QFileDialog.getOpenFileName', return_value=(str(xml), '')):
                buttons['Browse…'].click()
            self.assertEqual(dialog.xml.text(), str(xml))
            self.assertEqual(dialog.bill.currentText(), 'one')
            with patch('atool_qt.data_actions.QFileDialog.getOpenFileName', return_value=('', '')):
                buttons['Browse…'].click()
            self.assertEqual(dialog.xml.text(), str(xml))
            jobs = []
            def submit(args, callback):
                jobs.append(Job(callback))
                return jobs[-1]
            with patch.object(window.comms, 'submit', side_effect=submit) as command:
                buttons['Convert'].click()
            self.assertIn('billId=one', command.call_args.args[0])
            self.assertFalse(buttons['Convert'].isEnabled())
            self.assertTrue(buttons['Cancel Conversion'].isEnabled())
            jobs[-1].output.emit('Progress from local fake CLI\n')
            self.assertIn('Progress', dialog.log.toPlainText())
            buttons['Cancel Conversion'].click()
            self.assertTrue(jobs[-1].done)
            self.assertTrue(buttons['Convert'].isEnabled())
            self.assertFalse(buttons['Cancel Conversion'].isEnabled())
            with patch.object(window.comms, 'submit', side_effect=submit):
                buttons['Convert'].click()
            dialog.close()
            self.assertTrue(jobs[-1].done)
            self.assertFalse(dialog.isVisible())

    def test_convert_and_map_opens_picker_in_remembered_folder_and_cancel_dismisses(self):
        from atool_qt.window import WorkspaceWindow
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window = WorkspaceWindow(QSettings(str(root/'qt.ini'), QSettings.IniFormat))
            window.comms.settings = UserSettings(root/'user.json')
            window.comms.settings.payload['application']['confirm_on_quit'] = False
            self.addCleanup(window.close)
            window.set_session(PackageSession.from_payload({'Documents':[],'Fields':[]}))
            folder = root/'xml'
            folder.mkdir()
            xml = folder/'bill.xml'
            xml.write_text('<root><billId>794123456789</billId></root>')
            window.settings.setValue('lastConversionDirectory', str(folder))
            with patch('atool_qt.data_actions.QFileDialog.getOpenFileName', return_value=(str(xml), '')) as picker:
                window.convert_map_action.trigger()
                self.app.processEvents()
            self.assertEqual(str(folder), picker.call_args.args[2])
            self.assertEqual(str(xml), window.conversion_dialog.xml.text())
            self.assertEqual('794123456789', window.conversion_dialog.bill.currentText())
            self.assertFalse(any(button.text() == 'Close' for button in window.conversion_dialog.findChildren(QPushButton)))
            window.conversion_dialog.close()
            with patch('atool_qt.data_actions.QFileDialog.getOpenFileName', return_value=('', '')):
                window.convert_map_action.trigger()
                self.app.processEvents()
            self.assertFalse(window.conversion_dialog.isVisible())
            self.assertEqual(str(folder.resolve()), window.settings.value('lastConversionDirectory'))

    def test_conversion_and_mapping_auto_close_only_after_success(self):
        from atool_qt.occs import CommandResult
        from atool_qt.window import WorkspaceWindow
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            window = WorkspaceWindow(QSettings(str(root/'qt.ini'), QSettings.IniFormat))
            window.comms.settings = UserSettings(root/'user.json')
            window.comms.settings.payload['application']['confirm_on_quit'] = False
            self.addCleanup(window.close)
            window.set_session(PackageSession.from_payload({'Documents':[{'$$Id':'Doc','Condition':'@.enabled == true'}],'Fields':[]}))
            executable = root/'conversion-cli'
            executable.write_text("#!/usr/bin/env python3\nimport sys,json\nfrom pathlib import Path\na=sys.argv[1:]\np=Path(a[a.index('--output')+1])\np.write_text(json.dumps({'enabled':True}))\nprint('Converted XML to JSON: '+str(p))\n")
            executable.chmod(0o755)
            window.comms.settings.payload['occs']['cli_path'] = str(executable)
            xml = root/'input.xml'
            xml.write_text('<root><billId>794</billId></root>')
            dialog = XmlConversionDialog(window, map_after=True)
            dialog.xml.setText(str(xml))
            dialog.refresh_bill_ids()
            dialog.show()
            dialog.run_button.click()
            deadline = time.monotonic()+5
            while (dialog.isVisible() or window.job is not None) and time.monotonic()<deadline:
                self.app.processEvents()
                time.sleep(.005)
            self.assertFalse(dialog.isVisible())
            self.assertTrue(window.session.mapped)
            self.assertTrue(window.session.documents[0]['triggered'])
            self.assertEqual(str(root.resolve()), window.settings.value('lastConversionDirectory'))
            failure = XmlConversionDialog(window, map_after=True)
            failure.show()
            failure.conversion_finished(CommandResult(1,'','',{'ok':False,'error':{'message':'Conversion failed'}}),root/'bad.json')
            self.assertTrue(failure.isVisible())
            self.assertEqual('Conversion failed', failure.status.text())
            invalid = root/'invalid.json'
            invalid.write_text('invalid JSON')
            with patch.object(window,'report_error'):
                failure.conversion_finished(CommandResult(0,'','',None),invalid)
                deadline = time.monotonic()+5
                while window.job is not None and time.monotonic()<deadline:
                    self.app.processEvents()
                    time.sleep(.005)
            self.assertTrue(failure.isVisible())
            self.assertIn('Mapping failed:', failure.status.text())
            failure.close()
