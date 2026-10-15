"""Comms JSONPath triggers, including their mapping and diagnostic consumers."""
from __future__ import annotations

import unittest

from atool_core.condition_evaluator import ConditionEvaluator
from atool_qt.diagnostics import ConditionDiagnostics
from atool_qt.session import PackageSession
from atool_qt.validation import PayloadValidation


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
