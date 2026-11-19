import unittest
from copy import deepcopy
from pathlib import Path

from atool_core.td_profile import normalize_plan, group_document_plans
from atool_core.td_comparison import classified_metadata_changes
from tools.td_generator.td_generator import declared_baselines, metadata_changes, scenario_delta_lines, AToolConditionEvaluator


class SharedTemplateTests(unittest.TestCase):
    def profile(self):
        return {'baselines': [
            {'case': 'CO1', 'documents': ['RT_BILL', 'Backpage'], 'scenario': 'Regular', 'input': 'one.xml',
             'variants': [{'scenario': 'Prorate', 'input': 'partial.xml'}]},
            {'case': 'CO3', 'documents': ['RT_BILL', 'Backpage'], 'scenario': 'Regular', 'input': 'staff.xml'}],
            'document_references': {'RT_BILL': 'CO1', 'Backpage': 'CO3'}}

    def test_legacy_and_explicit_reference_validation(self):
        cases, refs = normalize_plan({'baselines': [{'document': 'OldDoc'}]})
        self.assertEqual(cases[0]['case'], 'OldDoc')
        self.assertEqual(cases[0]['documents'], ['OldDoc'])
        self.assertEqual(refs, {'OldDoc': 'OldDoc'})
        profile = self.profile()
        del profile['document_references']['RT_BILL']
        with self.assertRaisesRegex(ValueError, 'Choose a reference case for RT_BILL'):
            normalize_plan(profile)
        profile['document_references']['RT_BILL'] = 'Unknown'
        with self.assertRaises(ValueError):
            normalize_plan(profile)

    def test_shared_cases_keep_own_variants_and_document_references(self):
        profile = self.profile()
        specs = declared_baselines(profile, [
            {'name': 'Regular', 'inputs': [Path('one.xml'), Path('staff.xml')]},
            {'name': 'Prorate', 'inputs': [Path('partial.xml')]}])
        self.assertEqual(len(specs), 4)
        plans = [{'spec': s, 'baseline': s['input'], 'variants': s['variants']} for s in specs]
        grouped = group_document_plans(plans, profile['document_references'])
        self.assertEqual([p['spec']['document'] for p in grouped], ['RT_BILL', 'Backpage'])
        self.assertEqual(grouped[0]['baseline'], 'one.xml')
        self.assertEqual(grouped[1]['baseline'], 'staff.xml')
        self.assertEqual(len(grouped[0]['cases']), 2)
        self.assertEqual(grouped[0]['cases'][0]['variants'][0]['input'], 'partial.xml')
        self.assertEqual(grouped[0]['cases'][1]['variants'], [])

    def test_deep_metadata_changes_without_trigger_changes(self):
        doc = {'Name': 'RT_BILL', 'Layouts': [{'Name': 'Main', 'Layouts': [
            {'Name': 'Body', 'Contents': [{'Name': 'Detail', 'Fields': {'charge': '10'}}]}]}]}
        before = {'payload': 'one.json', 'payload_data': {}, 'scenario': 'Regular',
                  'rendered_documents': {'RT_BILL'}, 'metadata_documents': {'RT_BILL': [doc]}}
        after = deepcopy(before)
        after['payload'] = 'two.json'
        after['metadata_documents']['RT_BILL'][0]['Layouts'][0]['Layouts'][0]['Contents'][0]['Fields']['charge'] = '20'
        lines = scenario_delta_lines('RT_BILL', [], [], before, [after], AToolConditionEvaluator())
        self.assertIn('1 metadata differences', '\n'.join(lines))
        self.assertIn('Data-only: 1', '\n'.join(lines))
        self.assertNotIn('no metadata differences', '\n'.join(lines))
        same = scenario_delta_lines('RT_BILL', [], [], before, [before], AToolConditionEvaluator())
        self.assertIn('no metadata differences', '\n'.join(same))

    def test_metadata_added_removed_reordered_and_other_document_ignored(self):
        first = [{'Name': 'A'}, {'Name': 'B'}]
        self.assertIn('document: order changed', metadata_changes(first, first[::-1]))
        changes = metadata_changes(first, [{'Name': 'B'}, {'Name': 'C'}])
        self.assertTrue(any('A [1]: removed' in item for item in changes))
        self.assertTrue(any('C [1]: added' in item for item in changes))
        before = {'payload': 'a', 'payload_data': {}, 'scenario': 'Regular', 'rendered_documents': {'RT_BILL', 'Backpage'},
                  'metadata_documents': {'RT_BILL': [{'Name': 'RT_BILL'}], 'Backpage': [{'Name': 'Backpage', 'Text': 'one'}]}}
        after = deepcopy(before)
        after['metadata_documents']['Backpage'][0]['Text'] = 'two'
        result = scenario_delta_lines('RT_BILL', [], [], before, [after], AToolConditionEvaluator())
        self.assertIn('no metadata differences', '\n'.join(result))

    def test_document_only_requires_no_reference_but_keeps_mapping(self):
        profile = self.profile()
        profile['document_comparisons'] = {'Backpage': 'document_only'}
        del profile['document_references']['Backpage']
        cases, refs = normalize_plan(profile)
        self.assertIsNone(refs['Backpage'])
        plans = [{'spec': {'case': c['case'], 'document': d}, 'baseline': c['input'], 'variants': []}
                 for c in cases for d in c['documents']]
        grouped = group_document_plans(plans, refs)
        self.assertEqual(grouped[1]['comparison'], 'document_only')
        self.assertEqual(len(grouped[1]['cases']), 2)
        profile['document_comparisons']['Backpage'] = 'invalid'
        with self.assertRaises(ValueError):
            normalize_plan(profile)

    def test_render_classification_preserves_conditions_and_authored_text(self):
        def compare(a, b):
            return classified_metadata_changes({'Render': a}, {'Render': b})
        a = '<p>Balance <comms-data name="amount" value="10">10</comms-data></p>'
        b = '<p>Balance <comms-data name="amount" value="20">20</comms-data></p>'
        self.assertEqual(len(compare(a, b)['data']), 1)
        self.assertFalse(compare(a, b)['structural'])
        self.assertEqual(len(compare(a, b.replace('Balance', 'Amount due'))['unclassified']), 1)
        self.assertEqual(len(compare(a, b.replace('name="amount"', 'name="other"'))['structural']), 1)
        self.assertEqual(len(compare('<comms-cond Content="A" value="A"></comms-cond>',
                                     '<comms-cond Content="A"></comms-cond>')['structural']), 1)
        self.assertEqual(len(compare('<img src="A.png">', '<img src="B.png">')['structural']), 1)
        self.assertEqual(len(compare('<comms-data name="x">10', '<comms-data name="x">20')['unclassified']), 1)
        self.assertEqual(len(compare('<comms-data name="x"><b>10</b></comms-data>',
                                     '<comms-data name="x"><i>20</i></comms-data>')['structural']), 1)
        self.assertEqual(len(compare('<comms-data name="x" BarcodeType="Code39"><img src="one" alt="1"></comms-data>',
                                     '<comms-data name="x" BarcodeType="Code39"><img src="two" alt="2"></comms-data>')['data']), 1)

    def test_document_only_reports_coverage_without_comparisons(self):
        from tools.td_generator.td_generator import document_only_lines
        sample = {'payload': 'one', 'scenario': 'Regular', 'rendered_documents': {'Backpage'},
                  'metadata_documents': {'Backpage': [{'Name': 'Backpage', 'Layouts': [{'Contents': [{'Name': 'A'}]}]}]}}
        plan = {'spec': {'case': 'CO1'}, 'baseline': sample, 'variants': []}
        structure = [{'name': 'Backpage', 'contents': [{'name': 'A', 'condition': '$[?(@.backpage=="A")]'},
                                                    {'name': 'B', 'condition': '$[?(@.backpage=="B")]'}]}]
        text = '\n'.join(document_only_lines('Backpage', plan, structure, {'A', 'B'}, {}))
        self.assertIn('Rendered in 1 of 1', text)
        self.assertIn('CO1 / Regular', text)
        self.assertIn('Not observed in supplied metadata', text)
        self.assertIn('@.backpage=="B"', text)
        self.assertNotIn('Compared with', text)


if __name__ == '__main__':
    unittest.main()
