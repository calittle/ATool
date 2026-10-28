"""Comms JSONPath triggers, including their mapping and diagnostic consumers."""
from __future__ import annotations

import unittest

from atool_core.condition_evaluator import ConditionEvaluator
from atool_qt.diagnostics import ConditionDiagnostics
from atool_qt.session import PackageSession
from atool_qt.validation import PayloadValidation
from atool_qt.layout_mapping import layout_nodes


BILL_CHARS = '@.billPrint.billDetails.cmElements.billChars'
INSERT_TRIGGER = (
    BILL_CHARS + "[?(@.billCharacteristicType =~ /^CM-.*$/ && "
    "(@.billCharacteristicValue == 'TDInsert_1' || "
    "@.billCharacteristicValue == 'TDInsert_2'))].billCharacteristicValue empty false"
)
ORIGINAL_TRIGGER = (
    BILL_CHARS + "[?(" + ' || '.join(
        f"@.billCharacteristicType == 'CM-BDGT{slot}'" for slot in range(1, 5)
    ) + ")].billCharacteristicValue empty false"
)


def bill_payload(*rows):
    return {'billPrint': {'billDetails': {'cmElements': {'billChars': [
        {'billCharacteristicType': slot, 'billCharacteristicValue': value}
        for slot, value in rows
    ]}}}}


class ConditionEvaluatorTests(unittest.TestCase):
    def test_bare_filtered_paths_follow_jayway_existence_checks(self):
        # Verified against Jayway 2.8.0 and 2.9.0: a defined empty result
        # passes, but REQUIRE_PROPERTIES rejects missing traversed members.
        path = '@.rows[?(@.value == 1)]'
        for payload, bare, leaf in (
            ({}, False, False),
            ({'rows': []}, True, True),
            ({'rows': [{'value': 2}]}, True, True),
            ({'rows': [{'value': 1}]}, True, False),
            ({'rows': [{'value': 1, 'leaf': 'ok'}]}, True, True),
            ({'rows': [{'value': 1, 'leaf': 'ok'}, {'value': 1}]}, True, False),
            ({'rows': None}, False, False),
            ({'rows': 'text'}, False, False),
        ):
            for suffix, expected in (('', bare), ('.leaf', leaf)):
                with self.subTest(payload=payload, suffix=suffix):
                    condition = f'$[?({path}{suffix})]'
                    self.assertEqual(expected, ConditionEvaluator()._evaluate_document_condition(condition, payload))
                    self.assertEqual(expected, ConditionDiagnostics().explain(condition, payload)['passed'])

    def test_bare_wildcard_and_recursive_existence_checks(self):
        for path, payload, expected in (
            ('@.rows[*].leaf', {}, False),
            ('@.rows[*].leaf', {'rows': []}, True),
            ('@.rows[*].leaf', {'rows': [{'leaf': 'ok'}, {}]}, False),
            ('@.rows[*].leaf', {'rows': [{'leaf': None}]}, True),
            ('@..rows[?(@.value == 1)].leaf', {}, True),
            ('@..rows[?(@.value == 1)].leaf', {'nested': {'rows': [{'value': 2}]}}, True),
            ('@..rows[?(@.value == 1)].leaf', {'nested': {'rows': [{'value': 1}]}}, False),
            ("@['rows'][?(@.value == 1)]['leaf']", {'rows': [{'value': 1}]}, False),
        ):
            with self.subTest(path=path, payload=payload):
                self.assertEqual(expected, ConditionEvaluator()._evaluate_document_condition(path, payload))

    def test_calculation_details_empty_optin_triggers_and_explains_comms_behavior(self):
        optin = ("@.billPrint.billDetails.cmElements.accountChars"
                 "[?(@.acctCharacteristicType == 'CM-RSEXP' && @.acctCharacteristicValue == 'Y')]")
        condition = f'$[?({optin} && (@.nonRT == true || (@.res == true && @.staff == false)))]'
        payload = {'billPrint': {'billDetails': {'cmElements': {'accountChars': [
            {'acctCharacteristicType': 'CM-BLLNG', 'acctCharacteristicValue': 'CHINESE'},
        ]}}}, 'nonRT': True, 'res': False, 'staff': False}
        session = PackageSession.from_payload({
            'Documents': [{'$$Id': 'Calculation Details', 'Condition': condition}], 'Fields': [],
        })
        session.clauses = [{'name': 'CalcDetails_OptIn', 'expression': optin}]
        session.map_data(payload, 'synthetic-bill.json')
        self.assertTrue(session.documents[0]['triggered'])
        details = session.document_details(session.documents[0])
        gate = details['children'][0]['children'][0]
        self.assertTrue(gate['passed'])
        self.assertEqual('CalcDetails_OptIn', gate['clause_name'])
        self.assertIn("Add 'empty false'", ' '.join(gate['details']))
        self.assertIn('empty result can pass', ' '.join(gate['details']))
        warnings = []
        self.assertTrue(ConditionEvaluator()._evaluate_document_condition(condition, payload, warnings=warnings))
        self.assertIn('result is empty', warnings[0])
        self.assertFalse(ConditionEvaluator()._evaluate_document_condition(
            condition, payload, comms_compatible=False))
        self.assertFalse(ConditionEvaluator()._evaluate_document_condition(f'!({optin})', payload))
        self.assertEqual([], ConditionEvaluator()._evaluate_condition_operand(payload, optin))
        fixed = condition.replace(optin, optin + ' empty false', 1)
        self.assertFalse(ConditionEvaluator()._evaluate_document_condition(fixed, payload))
        payload['billPrint']['billDetails']['cmElements']['accountChars'].append(
            {'acctCharacteristicType': 'CM-RSEXP', 'acctCharacteristicValue': 'Y'})
        self.assertTrue(ConditionEvaluator()._evaluate_document_condition(fixed, payload))
        self.assertFalse(ConditionEvaluator()._evaluate_document_condition(f'!({optin})', payload))

    def test_misplaced_root_marker_cannot_trigger_content_with_iterator_rows(self):
        path = '$.billPrint.$.billPrint.billDetails.cmElements.consumptionRemarks'
        payload = {'billPrint': {'billDetails': {'cmElements': {
            'consumptionRemarks': 'Remarks: populated', 'proratedEnergyCharge': 'false',
        }}}, 'rows': [{'amount': 1}]}
        condition = f"$[?({path} empty true && $.billPrint.billDetails.cmElements.proratedEnergyCharge == 'false')]"
        document = {'triggered': True, 'source': {'Layouts': [{'Contents': [{
            'Condition': condition, 'Iteration': {'Path': '$.rows[*]'},
        }]}]}}
        content = layout_nodes(document, payload, True, [], [])[0]['children'][0]
        self.assertFalse(content['state'])
        self.assertFalse(content['children'][0]['state'])
        self.assertIn('Invalid JSON path', content['details'][0]['details'][0])
        self.assertTrue(PayloadValidation._payload_condition_validation_issues(document))

    def test_malformed_paths_fail_before_negation_and_short_circuiting(self):
        for atom in ('$.billPrint.$.value empty true', '@.billPrint.@.value empty true'):
            for body in (atom, f'!({atom})', f'$.active == true || {atom}',
                         f'$.rows[?({atom})] empty true', f'{atom} || $.active == true'):
                with self.subTest(body=body):
                    warnings = []
                    condition = f'$[?({body})]'
                    self.assertFalse(ConditionEvaluator()._evaluate_document_condition(
                        condition, {'active': True, 'rows': [{}]}, warnings=warnings))
                    self.assertIn('Invalid JSON path', warnings[0])
                    self.assertTrue(PayloadValidation._at_condition_validation_messages(condition)[0])
                    detail = ConditionDiagnostics().explain(condition, {'active': True})
                    self.assertFalse(detail['passed'])
                    self.assertIn('Invalid JSON path', detail['details'][0])

    def test_path_validation_preserves_literals_quoted_keys_and_filter_roots(self):
        payload = {'$': {'value': 'ok'}, '@': 'ok', 'value': '.$.',
                   'rows': [{'enabled': True}]}
        for body in ("$['$'].value == 'ok'", "$['@'] == 'ok'",
                     "$.value == '.$.'", '$.value =~ /[.][$][.]/',
                     '$.rows[?(@.enabled == true)] empty false',
                     '$.rows[?($.enabled == true)] empty false'):
            with self.subTest(body=body):
                condition = f'$[?({body})]'
                self.assertEqual([], PayloadValidation._at_condition_validation_messages(condition)[0])
                self.assertTrue(ConditionEvaluator()._evaluate_document_condition(condition, payload))

    def test_insert_trigger_matches_either_value_in_any_cm_slot(self):
        for slot in ('CM-BDGT1', 'CM-BDGT2', 'CM-BDGT3', 'CM-BDGT4', 'CM-OTHER'):
            for value in ('TDInsert_1', 'TDInsert_2'):
                with self.subTest(slot=slot, value=value):
                    payload = bill_payload(('CM-BDGT1', 'Other'), (slot, value))
                    self.assertTrue(ConditionEvaluator()._evaluate_document_condition(INSERT_TRIGGER, payload))

    def test_insert_trigger_rejects_nonmatches_and_missing_data(self):
        for payload in (
            bill_payload(), {}, bill_payload(('XX-BDGT1', 'TDInsert_1')),
            bill_payload(('CM-BDGT1', 'TDInsert_3')),
            bill_payload(('CM-BDGT1', 'prefix TDInsert_1')),
            bill_payload(('CM-BDGT1', 'Other'), ('XX-BDGT1', 'TDInsert_1')),
        ):
            with self.subTest(payload=payload):
                self.assertFalse(ConditionEvaluator()._evaluate_document_condition(INSERT_TRIGGER, payload))

    def test_original_four_slot_trigger_still_matches_each_slot(self):
        for slot in range(1, 5):
            with self.subTest(slot=slot):
                self.assertTrue(ConditionEvaluator()._evaluate_document_condition(
                    ORIGINAL_TRIGGER, bill_payload((f'CM-BDGT{slot}', 'TDInsert_1'))))
        self.assertFalse(ConditionEvaluator()._evaluate_document_condition(
            ORIGINAL_TRIGGER, bill_payload(('CM-OTHER', 'TDInsert_1'))))

    def test_regex_full_match_flags_and_invalid_patterns(self):
        for expression, value, expected in (
            ('@.value =~ /CM-.*/', 'CM-OTHER', True),
            ('@.value =~ /CM-.*/', 'prefix CM-OTHER', False),
            ('@.value =~ /cm-.*/i', 'CM-OTHER', True),
            ('@.value =~ /cm-.*/', 'CM-OTHER', False),
            (r'@.value =~ /CM-\d+/', 'CM-123', True),
            ('@.value =~ /a.b/s', 'a\nb', True),
            ('@.value =~ /x/', 123, False),
            ('@.value =~ /x/', None, False),
            ('@.value =~ /[/', 'x', False),
            ('@.value =~ /x/z', 'x', False),
            ('@.value =~ /unterminated', 'x', False),
            ('@.missing =~ /x/', 'x', False),
        ):
            with self.subTest(expression=expression, value=value):
                self.assertEqual(expected, ConditionEvaluator()._evaluate_document_condition(
                    expression, {'value': value}))

    def test_regex_punctuation_is_not_condition_or_path_syntax(self):
        patterns = (
            (r"/[)'\"]+/", ")'\""),
            (r'/a\|\|b&&c/', 'a||b&&c'),
            (r'/a\/b/', 'a/b'),
            (r'/.* size .*/', 'a size b'),
            (r'/\[\?\(.*\)\]/', '[?(hello)]'),
        )
        for regex, value in patterns:
            with self.subTest(regex=regex):
                condition = f'@.rows[?(@.value =~ {regex} && @.enabled == true)].value empty false'
                payload = {'rows': [{'value': value, 'enabled': True}]}
                evaluator = ConditionEvaluator()
                self.assertTrue(evaluator._evaluate_document_condition(f'$[?({condition})]', payload))
                self.assertEqual([value], evaluator._extract_values_by_path(payload, '$.rows[?(@.value =~ ' + regex + ')].value'))
                self.assertEqual([], PayloadValidation._at_condition_validation_messages(f'$[?({condition})]')[0])
                self.assertTrue(ConditionDiagnostics().explain(condition, payload)['passed'])
                # Regex text must also stay intact in a top-level comparison.
                self.assertTrue(ConditionDiagnostics().explain(
                    f'(@.value =~ {regex}) && @.enabled == true', payload['rows'][0])['passed'])

    def test_mapping_updates_document_trigger_and_clause_result(self):
        session = PackageSession.from_payload({
            'Documents': [{'$$Id': 'Inserts', 'Condition': f'$[?({INSERT_TRIGGER})]'}],
            'Fields': [],
        })
        session.clauses = [{'name': 'hasInserts_Portrait', 'expression': INSERT_TRIGGER}]
        for payload, expected in (
            (bill_payload(('CM-BDGT4', 'TDInsert_2')), True),
            (bill_payload(('CM-BDGT4', 'Other')), False),
            (bill_payload(('CM-OTHER', 'TDInsert_1')), True),
        ):
            session.map_data(payload, 'bill.json')
            self.assertEqual(expected, session.documents[0]['triggered'])
            details = session.document_details(session.documents[0])
            self.assertEqual(expected, details['passed'])
            self.assertEqual('hasInserts_Portrait', details['children'][0]['clause_name'])
            self.assertEqual(expected, details['children'][0]['passed'])


if __name__ == '__main__':
    unittest.main()
