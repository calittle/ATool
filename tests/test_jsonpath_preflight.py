"""PD's length restriction must be enforced without mistaking filter scope for count scope."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from atool_core.jsonpath_preflight import audit_length_paths, length_path_issues
from atool_qt.editor import PackageEditor
from atool_qt.session import PackageSession
from atool_qt.validation import PayloadValidation

try:
    from ATool import AToolApp
except ImportError:
    AToolApp = None


class LengthPreflightTests(unittest.TestCase):
    def test_forbidden_count_paths(self):
        for expression in (
            '@.items.length()', 'length(@.items)', '$.length(@.items)',
            'items.length()', 'length(items)', '$..items.length()',
            '$.length($..items)', '$.root..items.length()',
            '$[?(@.items.length() > 0)]',
            '$.items[?(@.children.length() > 0)].name',
            '$.length($..billCalcLineList[?(@.type == \'FCC\')].cmElements).length())',
            'length ( @ [ "items" ] )',
            '@.items . length ()', '$ .. items . length ()',
            "['items'].length()", "length(['items'])",
        ):
            with self.subTest(expression=expression):
                self.assertTrue(length_path_issues(expression))

    def test_allowed_expressions_and_literals(self):
        for expression in (
            '$.items.length()', '$.length($.items)', 'length($.items)',
            '$.length($.items[?(@.active == true)].length())',
            '$..items', '@.items empty false',
            '$[?(@.label == "@.items.length()")]',
            r'$[?(@.label =~ /@.items.length\(\)/)]',
            '$["a..b"].length()', '$["length(@.x)"].length()',
            '$[?(@.note == \'can\\\'t use length(@.x)\')].length()',
            '$[?(@.active)].items.length() > 0 && @.enabled',
            '$[?(@.enabled && $.items.length() > 0)]',
            '$[?(@.value == "length(@.x)" && $.items.length() > 0)]',
        ):
            with self.subTest(expression=expression):
                self.assertEqual([], length_path_issues(expression))

    def test_locations_include_fields_iterations_conditions_and_clauses(self):
        payload = {'Documents': [{'$$Id': 'Doc', 'Condition': '$[?(@.items.length() > 0)]',
                    'Layouts': [{'$$Id': 'Loop', 'Path': '$..rows.length()'}]}],
                   'Fields': [{'$$Id': 'Count', 'Path': '$.length($..rows)'}],
                   'Meta': {'clause_library': [{'name': 'CountClause', 'expression': '@.rows.length() > 0'}]},
                   'Description': 'length(@.text)'}
        findings = audit_length_paths(payload)
        self.assertEqual(4, len(findings))
        self.assertEqual(['Doc', 'Loop'], findings[1]['owners'])
        self.assertEqual('$.Fields[0].Path', findings[2]['path'])
        self.assertEqual(4, len(PayloadValidation._payload_condition_validation_issues(payload, check_length_paths=True)))

    def test_condition_authoring_preflight(self):
        issues, _ = PayloadValidation._at_condition_validation_messages('$[?(@.items.length() > 0)]', check_length_paths=True)
        self.assertTrue(any('relative JSONPaths' in issue for issue in issues))
        self.assertEqual([], PayloadValidation._at_condition_validation_messages('$[?(@.items.length() > 0)]')[0])
        self.assertTrue(PayloadValidation._at_condition_validation_messages('invalid wrapper')[0])

    def test_length_check_defaults_off_for_save(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'AT.json'
            payload = {'Fields': [{'Name': 'Count', 'Path': '$..rows.length()'}]}
            source.write_text(json.dumps(payload))
            self.assertEqual([], PayloadValidation._payload_condition_validation_issues(payload))
            editor = PackageEditor(PackageSession.open(source))
            editor.save()
            self.assertEqual('$..rows.length()', json.loads(source.read_text())['Fields'][0]['Path'])

    def test_save_and_save_as_refuse_invalid_paths_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'AT.json'
            source.write_text(json.dumps({'Fields': [{'$$Id': 'Count', 'Path': '$..rows.length()'}]}))
            before = source.read_bytes()
            editor = PackageEditor(PackageSession.open(source))
            for destination in (source, source.with_name('copy.json')):
                with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, 'recursive JSONPath'):
                    editor.save(destination, check_length_paths=True)
            self.assertEqual(before, source.read_bytes())
            self.assertEqual([source], list(source.parent.iterdir()))

    def test_external_clause_library_is_checked_before_save(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'AT.json'
            source.write_text('{"Fields": []}')
            editor = PackageEditor(PackageSession.open(source))
            editor.session.clauses = [{'name': 'bad', 'expression': '$..rows.length() > 0'}]
            with self.assertRaisesRegex(ValueError, 'recursive JSONPath'):
                editor.save(check_length_paths=True)
            self.assertEqual('{"Fields": []}', source.read_text())

    def test_correcting_a_clause_allows_save(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'AT.json'
            source.write_text(json.dumps({'Fields': [], 'Meta': {'clause_library': [
                {'name': 'count', 'expression': '$..rows.length() > 0'}]}}))
            editor = PackageEditor(PackageSession.open(source))
            editor.session.clauses[0]['expression'] = '$.rows.length() > 0'
            editor.save(check_length_paths=True)
            self.assertEqual('$.rows.length() > 0', json.loads(source.read_text())['Meta']['clause_library'][0]['expression'])

    @unittest.skipIf(AToolApp is None, 'Tkinter is not installed')
    def test_legacy_preflight_checks_persisted_file_and_validation_matches_qt(self):
        payload = {'Fields': [{'Name': 'Count', 'Path': '$..rows.length()'}]}
        self.assertEqual(PayloadValidation._payload_condition_validation_issues(payload, check_length_paths=True),
                         AToolApp._payload_condition_validation_issues(payload, check_length_paths=True))
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'assembly-template.json'
            source.write_text(json.dumps(payload))
            app = AToolApp.__new__(AToolApp)
            app.user_settings = {'occs': {'check_jsonpath_length': True}}
            app.current_payload = {'Fields': []}
            app.current_occs_bundle_dir = temporary
            with patch('ATool.messagebox.showerror') as error:
                self.assertFalse(app._length_path_publish_preflight())
            self.assertIn('recursive JSONPath', error.call_args.args[1])
            app.user_settings['occs']['check_jsonpath_length'] = False
            with patch('ATool.messagebox.showerror') as error:
                self.assertTrue(app._length_path_publish_preflight())
            error.assert_not_called()

    def test_cli_audit_exit_codes_and_report(self):
        from contextlib import redirect_stdout, redirect_stderr
        from io import StringIO
        from tools.audit_jsonpath_length import main
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            source = Path(temporary) / 'AT.json'
            report = source.with_name('audit.json')
            source.write_text(json.dumps({'Fields': [{'Name': 'Count', 'Path': '$..rows.length()'}]}))
            before = source.read_bytes()
            self.assertEqual(1, main([str(source), str(source), '--output', str(report)]))
            results = json.loads(report.read_text())
            self.assertEqual(1, len(results))
            self.assertEqual(['Count'], results[0]['findings'][0]['owners'])
            self.assertEqual(before, source.read_bytes())
            source.write_text('{"Fields": []}')
            self.assertEqual(0, main([str(source)]))
            self.assertEqual(2, main([str(source.with_name('missing.json'))]))


if __name__ == '__main__':
    unittest.main()
