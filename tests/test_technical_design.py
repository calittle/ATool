import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QSettings, QEventLoop, QTimer
from atool_qt.occs import CommsSettings
from atool_qt.technical_design import GenerationJob, TechnicalDesignDialog, prepare_profile
from tools.td_generator import td_generator as td
from atool_qt.td_profile_editor import ProfilePlanEditor


class TechnicalDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_profile_paths_and_settings_do_not_modify_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'profiles').mkdir()
            (root / 'samples').mkdir()
            (root / 'cache').mkdir()
            path = root / 'profiles' / 'test.json'
            original = json.dumps({'baselines': [{'document': 'D'}], 'scenarios': 'samples', 'comms': {'resource_cache': '../cache'}})
            path.write_text(original)
            settings = CommsSettings(root / 'settings.json')
            settings.payload = {'occs': {'cli_path': '/runtime/occs.js', 'session_alias': 'test'}}
            profile = prepare_profile(path, '', settings)
            self.assertEqual(profile['scenarios'], str((root / 'samples').resolve()))
            self.assertEqual(profile['comms']['resource_cache'], str((root / 'cache').resolve()))
            self.assertEqual(profile['occs']['session'], 'test')
            self.assertEqual(path.read_text(), original)

    def test_bundled_runtime_without_system_node(self):
        with patch.object(td.sys, 'frozen', True, create=True), patch.object(td.sys, '_MEIPASS', '/bundle', create=True):
            self.assertEqual(str(td.default_occs_cli()), '/bundle/runtime/occs-cli/bin/occs.js')
            self.assertIn('/bundle/runtime/node/node', td.node_executable())

    def test_worker_reports_errors(self):
        job = GenerationJob({}, None)
        results = []
        job.outcome.connect(results.append)
        with patch.object(td, 'generate', side_effect=ValueError('missing baseline')):
            job.run()
        self.assertEqual(results, ['missing baseline'])

    def test_missing_metadata_exposes_only_matching_input_error(self):
        errors = [{'scenario': 'rt', 'file': Path('CO1.xml'), 'error': 'billCharacteristicTypes path not found'},
                  {'scenario': 'rt', 'file': Path('CO2.xml'), 'error': 'unrelated failure'}]
        message = td.missing_metadata_message('Baseline', 'CO-G1-CO1', 'rt', 'CO1.xml', errors)
        self.assertIn('billCharacteristicTypes path not found', message)
        self.assertNotIn('unrelated failure', message)
        self.assertIn('No matching metadata output', td.missing_metadata_message('Variant', 'CO1', 'Other', 'x.xml', errors))

    def test_dialog_defaults(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        parent = QWidget()
        parent.settings = QSettings(str(Path(temp.name) / 'qt.ini'), QSettings.Format.IniFormat)
        parent.comms = SimpleNamespace(settings=CommsSettings(Path(temp.name) / 'settings.json'))
        dialog = TechnicalDesignDialog(parent)
        self.assertTrue(dialog.formats['md'].isChecked())
        self.assertFalse(dialog.formats['pdf'].isChecked())
        self.assertEqual(dialog.evidence.currentData(), 'metadata')
        self.assertEqual(dialog.xml.currentData(), 'auto')
        dialog.close()
        parent.close()

    def test_editor_roundtrip_and_reordering(self):
        editor = ProfilePlanEditor()
        plan = {'family': 'Bills', 'scenarios': '/old/samples', 'occs': {'cli': 'old'},
                'comms': {'package': 'Bills', 'effective_date': '2026-11-19', 'resource_cache': '/old/cache'},
                'custom': 'preserved', 'baselines': [
                    {'document': 'CO1', 'scenario': 'Regular', 'input': 'one.xml', 'custom': 42,
                     'variants': [{'scenario': 'Prorate', 'input': 'two.xml', 'label': 'Partial'}]},
                    {'document': 'CO2', 'scenario': 'Regular', 'input': 'three.xml'}]}
        editor.load(plan)
        editor.tree.setCurrentItem(editor.tree.topLevelItem(1))
        editor.move(-1)
        saved = editor.plan(validate=True)
        self.assertEqual([r['case'] for r in saved['baselines']], ['CO2', 'CO1'])
        self.assertEqual(saved['baselines'][1]['variants'][0]['label'], 'Partial')
        self.assertEqual(saved['baselines'][1]['custom'], 42)
        self.assertEqual(saved['custom'], 'preserved')
        self.assertNotIn('scenarios', saved)
        self.assertNotIn('occs', saved)
        self.assertNotIn('resource_cache', saved['comms'])
        editor.close()

    def test_local_preferences_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / 'samples').mkdir()
            (root / 'cache').mkdir()
            profile_path = root / 'profile.json'
            profile_path.write_text(json.dumps({'family': 'Bills', 'scenarios': 'samples',
                'comms': {'package': 'Bills', 'effective_date': '2026-11-19', 'resource_cache': 'cache'},
                'baselines': [{'document': 'CO1', 'scenario': 'Regular', 'input': 'one.xml'}]}))
            parent = QWidget()
            parent.settings = QSettings(str(root / 'qt.ini'), QSettings.Format.IniFormat)
            parent.comms = SimpleNamespace(settings=CommsSettings(root / 'settings.json'))
            dialog = TechnicalDesignDialog(parent)
            dialog.load_profile(profile_path)
            self.assertEqual(dialog.samples.text(), str(root / 'samples'))
            dialog.output.setText(str(root / 'report.md'))
            dialog.xml.setCurrentIndex(dialog.xml.findData('never'))
            self.assertTrue(dialog.save_profile())
            saved = json.loads(profile_path.read_text())
            self.assertNotIn('scenarios', saved)
            self.assertNotIn('resource_cache', saved['comms'])
            dialog.close()
            reopened = TechnicalDesignDialog(parent)
            self.assertEqual(reopened.profile.text(), str(profile_path.resolve()))
            self.assertEqual(reopened.samples.text(), str(root / 'samples'))
            self.assertEqual(reopened.output.text(), str(root / 'report.md'))
            self.assertEqual(reopened.xml.currentData(), 'never')
            reopened.close()
            parent.close()

    def test_last_profile_missing_or_invalid_falls_back(self):
        for contents in (None, '{not valid JSON'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                profile = root / 'missing-or-invalid.json'
                if contents is not None:
                    profile.write_text(contents)
                parent = QWidget()
                parent.settings = QSettings(str(root / 'qt.ini'), QSettings.Format.IniFormat)
                parent.settings.setValue('technicalDesignLastProfile', str(profile))
                parent.comms = SimpleNamespace(settings=CommsSettings(root / 'settings.json'))
                dialog = TechnicalDesignDialog(parent)
                self.assertEqual(dialog.profile.text(), '')
                self.assertIn('Could not reopen the last profile', dialog.log.toPlainText())
                self.assertEqual(dialog.editor.tree.topLevelItemCount(), 0)
                dialog.close()
                parent.close()

    def test_editor_shared_mapping_reference_roundtrip(self):
        editor = ProfilePlanEditor()
        editor.load({'family': 'RT', 'comms': {'package': 'Bills'}, 'baselines': [
            {'case': 'CO1', 'documents': ['RT_BILL', 'Backpage'], 'scenario': 'Regular', 'input': 'one.xml'},
            {'case': 'CO3', 'documents': ['RT_BILL', 'Backpage'], 'scenario': 'Regular', 'input': 'staff.xml'}],
            'document_references': {'RT_BILL': 'CO3', 'Backpage': 'CO1'}})
        result = editor.plan(validate=True)
        self.assertEqual(result['document_references'], {'RT_BILL': 'CO3', 'Backpage': 'CO1'})
        self.assertEqual(result['baselines'][0]['documents'], ['RT_BILL', 'Backpage'])
        editor.tree.setCurrentItem(editor.tree.topLevelItem(1))
        editor.remove()
        self.assertEqual(editor.plan(validate=True)['document_references']['RT_BILL'], 'CO1')
        editor.close()

    def test_document_only_editor_disables_reference_and_roundtrips(self):
        editor = ProfilePlanEditor()
        editor.load({'family': 'RT', 'comms': {'package': 'Bills'}, 'baselines': [
            {'case': 'CO1', 'documents': ['Backpage'], 'scenario': 'Regular', 'input': 'one.xml'},
            {'case': 'CO3', 'documents': ['Backpage'], 'scenario': 'Regular', 'input': 'staff.xml'}],
            'document_comparisons': {'Backpage': 'document_only'}})
        item = editor.references.topLevelItem(0)
        self.assertFalse(editor.references.itemWidget(item, 1).isEnabled())
        plan = editor.plan(validate=True)
        self.assertEqual(plan['document_comparisons'], {'Backpage': 'document_only'})
        self.assertEqual(plan['document_references'], {})
        mode = editor.references.itemWidget(item, 2)
        mode.setCurrentIndex(mode.findData('compare'))
        self.assertTrue(editor.references.itemWidget(item, 1).isEnabled())
        with self.assertRaisesRegex(ValueError, 'Choose a reference case'):
            editor.plan(validate=True)
        editor.close()

    def test_cli_accepts_local_path_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / 'plan.json'
            profile.write_text('{"family":"Test","comms":{}}')
            with patch.object(td.sys, 'argv', ['td', 'generate', '--profile', str(profile), '--out', str(root / 'out.md'),
                      '--samples-root', str(root / 'samples'), '--resource-cache', str(root / 'cache')]), patch.object(td, 'generate') as run:
                td.main()
            resolved = run.call_args.kwargs['profile_override']
            self.assertEqual(resolved['scenarios'], str((root / 'samples').resolve()))
            self.assertEqual(resolved['comms']['resource_cache'], str((root / 'cache').resolve()))

    def test_docx_export_in_process(self):
        from tools.td_generator.render_td import export_formats
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'design.md'
            source.write_text('# Technical Design\n\nExample document.\n')
            export_formats(source, root / 'design.docx')
            self.assertTrue((root / 'design.docx').is_file())

    def test_export_dependency_failure_happens_before_profile_processing(self):
        import builtins
        original_import = builtins.__import__
        def missing_export(name, *args, **kwargs):
            if name == 'tools.td_generator.render_td':
                raise ModuleNotFoundError("No module named 'docx'", name='docx')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=missing_export):
            with self.assertRaisesRegex(RuntimeError, 'pip install'):
                td.generate(Path('/missing-profile.json'), Path('/unused.md'), formats={'md', 'docx'})

    def test_generate_button_worker_lifecycle(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                (root / 'samples' / 'Regular').mkdir(parents=True)
                (root / 'samples' / 'Regular' / 'bill.json').write_text('{}')
                (root / 'cache').mkdir()
                parent = QWidget()
                parent.settings = QSettings(str(root / 'qt.ini'), QSettings.Format.IniFormat)
                parent.comms = SimpleNamespace(settings=CommsSettings(root / 'settings.json'))
                dialog = TechnicalDesignDialog(parent)
                dialog.editor.load({'family': 'Test', 'comms': {'package': 'Bills'},
                    'baselines': [{'document': 'CO1', 'scenario': 'Regular', 'input': 'bill.json'}]})
                dialog.saved_plan = dialog.editor.plan()
                dialog.samples.setText(str(root / 'samples'))
                dialog.cache.setText(str(root / 'cache'))
                dialog.output.setText(str(root / 'report.md'))
                def generate(**options):
                    options['progress']('Worker started')
                    if fail:
                        raise ValueError('Test generation failure')
                    options['output_path'].write_text('# Test')
                with patch.object(td, 'generate', side_effect=generate), patch('atool_qt.technical_design.QMessageBox.warning') as warning:
                    dialog.start.click()
                    loop = QEventLoop()
                    timer = QTimer()
                    timer.setSingleShot(True)
                    timer.timeout.connect(loop.quit)
                    dialog.job.finished.connect(loop.quit)
                    timer.start(3000)
                    loop.exec()
                    timer.stop()
                    self.assertTrue(dialog.job.wait(1000))
                    self.app.processEvents()
                    warning.assert_not_called()
                    self.assertTrue(dialog.start.isEnabled())
                    self.assertTrue(dialog.tabs.isEnabled())
                    self.assertIn('Test generation failure' if fail else 'Generation complete.', dialog.log.toPlainText())
                    self.assertEqual(dialog.open_output.isEnabled(), not fail)
                dialog.close()
                parent.close()


if __name__ == '__main__':
    unittest.main()
