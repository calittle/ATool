"""Full array slices and sample-based advice across the mapping consumers."""
import copy
import unittest

from ATool import AToolApp
from atool_core.condition_evaluator import ConditionEvaluator
from atool_core.jsonpath_recommendations import audit_selector_paths, selector_recommendations
from atool_qt.data_queries import DataQueries
from atool_qt.editor import PackageEditor
from atool_qt.session import PackageSession


class SliceSupportTests(unittest.TestCase):
    def test_validation_and_multivalue_rules_match_wildcards(self):
        for validator in (DataQueries(), AToolApp.__new__(AToolApp)):
            for selector in ('[*]', '[0:]', '[ 0 : ]'):
                path = f'$.rows{selector}.amount'
                self.assertEqual((True, ''), validator._validate_field_path(path, require_concat=False))
                self.assertIn('must use concat or length', validator._validate_field_path(path)[1])
                for wrapper in ('concat', 'length'):
                    self.assertTrue(validator._validate_field_path(f'$.{wrapper}({path})')[0])
            for selector in ('[0::]', '[0:abc]', '[1:]', '[0:2]'):
                self.assertFalse(validator._validate_field_path('$.rows' + selector, require_concat=False)[0])

    def test_values_and_concrete_paths_preserve_array_order_and_object_difference(self):
        data = {'rows': [{'amount': 2}, {'amount': 0}, {'amount': None}], 'obj': {'a': 2, 'b': 3}}
        for evaluator in (ConditionEvaluator(), DataQueries(), AToolApp.__new__(AToolApp)):
            for selector in ('[*]', '[0:]', '[ 0 : ]'):
                self.assertEqual([2, 0, None], evaluator._extract_values_by_path(data, '$.rows' + selector + '.amount'))
            self.assertEqual([], evaluator._extract_values_by_path(data, '$.obj[0:]'))
            self.assertEqual([2, 3], evaluator._extract_values_by_path(data, '$.obj[*]'))
        for evaluator in (DataQueries(), AToolApp.__new__(AToolApp)):
            self.assertEqual([('$.rows[0].amount', 2), ('$.rows[1].amount', 0), ('$.rows[2].amount', None)],
                             evaluator._extract_values_and_paths_by_path(data, '$.rows[0:].amount'))

    def test_filters_recursion_and_empty_bare_condition_semantics(self):
        data = {'rows': [{'values': [0, 3]}, {'values': [1]}]}
        evaluator = ConditionEvaluator()
        self.assertEqual([0, 3], evaluator._extract_values_by_path(data, '$.rows[?(@.values[0:] size 2)].values[0:]'))
        self.assertEqual([0, 3, 1], evaluator._extract_values_by_path(data, '$..values[0:]'))
        for selector in ('[*]', '[0:]'):
            self.assertTrue(evaluator._evaluate_document_condition('$.rows' + selector, {'rows': []}))
            self.assertFalse(evaluator._evaluate_document_condition('$.rows' + selector + ' empty false', {'rows': []}))

    def test_edit_paste_mapping_and_save_preserve_authored_selectors(self):
        import tempfile
        from pathlib import Path
        session = PackageSession.from_payload({'Fields': [{'Name': 'Joined', 'Path': "$.concat($.rows[*].x, '')"}]})
        session.map_data({'rows': [{'x': 1}, {'x': 2}]}, 'sample')
        editor = PackageEditor(session)
        path = "$.concat($.rows[0:].x, '')"
        editor.update_record(session.fields[0], {'Path': path}, 'fields')
        self.assertEqual([1, 2], session.fields[0]['mapped_values'])
        editor.paste_fields([{'Name': 'Wildcard', 'Path': "$.concat($.rows[*].x, '')"}])
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'AT.json'
            editor.save(destination)
            reopened = PackageSession.open(destination)
            self.assertEqual(path, reopened.fields[0]['path'])
            self.assertIn('[*]', reopened.fields[1]['path'])


class SelectorAdviceTests(unittest.TestCase):
    def advice(self, path, data):
        return '\n'.join(selector_recommendations(path, data, mapped=True))

    def test_target_types_empty_arrays_and_unknowns(self):
        self.assertIn('Prefer [0:]', self.advice('$.rows[*]', {'rows': []}))
        self.assertIn('Keep [*]', self.advice('$.rows[*]', {'rows': {}}))
        self.assertIn('mixed target types', self.advice('$.groups[*].rows[*]', {'groups': [{'rows': []}, {'rows': {}}]}))
        for data in ({}, {'rows': None}, {'rows': 2}):
            self.assertIn('cannot recommend', self.advice('$.rows[*]', data))
        self.assertIn('Map a data file', selector_recommendations('$.rows[*]')[0])
        self.assertEqual([], selector_recommendations('$.rows[0:]', {'rows': []}, mapped=True))
        self.assertIn('returns no matches', self.advice('$.rows[0:]', {'rows': {}}))

    def test_each_occurrence_functions_quoted_keys_and_nested_filter_contexts(self):
        data = {'groups': [{'rows': [{'values': {'a': 2}}]}]}
        path = '$.groups[?(@.rows[?(@.values[*] == 2)])]'
        self.assertIn('Keep [*]', self.advice(path, data))
        self.assertIn('Keep [*]', self.advice(path.replace('[?(', '[ ?('), data))
        path = "$.concat($.groups[*].rows[*].values[*], '[*]')"
        messages = selector_recommendations(path, data, mapped=True)
        self.assertEqual(3, len(messages))
        self.assertIn('Prefer [0:]', messages[0])
        self.assertIn('Prefer [0:]', messages[1])
        self.assertIn('Keep [*]', messages[2])
        self.assertIn('Keep [*]', self.advice("$['a b'][*]", {'a b': {}}))
        for path in ("$['literal[*]']", '$.rows[?(@.name == "[*]")]', '$.rows[?(@.name =~ /a[*]/)]'):
            self.assertEqual([], selector_recommendations(path, data, mapped=True))

    def test_audit_scopes_iterator_fields_and_never_mutates_inputs(self):
        payload = {'Iteration': {'Path': '$.rows[0:]', 'Fields': [
            {'Name': 'Values', 'Path': '$.rows[0:].values[*]'}]}}
        data = {'rows': [{'values': []}, {'values': {}}], 'values': []}
        before = copy.deepcopy((payload, data))
        findings = audit_selector_paths(payload, data, mapped=True)
        self.assertEqual(1, len(findings))
        self.assertEqual('$.Iteration.Fields[0].Path', findings[0]['path'])
        self.assertIn('mixed target types', '\n'.join(findings[0]['issues']))
        self.assertEqual(before, (payload, data))
        self.assertIn('Other input files', '\n'.join(findings[0]['issues']))


if __name__ == '__main__':
    unittest.main()
