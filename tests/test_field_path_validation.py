"""Field authoring must validate input before the resolver trims segments."""
import unittest

from ATool import AToolApp
from atool_qt.data_queries import DataQueries
from atool_qt.editor import PackageEditor
from atool_qt.session import PackageSession


BILL_PATH = (
    "$.billPrint.premise.premList[*].serviceAgreement.saList[?(@.saType != 'E-FIT')]"
    ".billSegment.bsegList[*].bsegSQ.bsegSQList[?(@.uom == 'KWH' && @.sqi == 'BILL')].billSq"
)


class FieldPathValidationTests(unittest.TestCase):
    def validators(self):
        return (DataQueries(), AToolApp.__new__(AToolApp))

    def test_rejects_whitespace_after_dot_at_root_nested_and_filter_paths(self):
        paths = [BILL_PATH.replace('$.billPrint', '$. billPrint'),
                 '$.bill. amount', '$.. bill', '$.bill.\tamount', '$.bill.\namount',
                 '$.bill.\u00a0amount', '$.rows[?(@. amount > 0)].value',
                 '$.length($. bill)', "$.concat($.good, $. bad)"]
        for validator in self.validators():
            for path in paths:
                with self.subTest(validator=type(validator).__name__, path=path):
                    valid, reason = validator._validate_field_path(path)
                    self.assertFalse(valid)
                    self.assertIn('Whitespace', reason)

    def test_rejects_repeated_or_trailing_dots(self):
        for validator in self.validators():
            for path in ('$...bill', '$.bill....amount', '$.bill.', '$..', '$.length($.bill.)'):
                with self.subTest(validator=type(validator).__name__, path=path):
                    self.assertFalse(validator._validate_field_path(path)[0])

    def test_preserves_supported_paths_and_literal_spaces_and_dots(self):
        paths = [BILL_PATH, '$', '$..bill', '$.rows[*].amount', '$.rows[0].amount',
                 "$['bill amount']", '$["a. b...c"]',
                 '$.rows[?(@.amount > 1.25 && @.name == "A. B...")].amount',
                 '$.length($.bill)', "$.concat($.bill, ' . ... ')", '  $.bill  ']
        for validator in self.validators():
            for path in paths:
                with self.subTest(validator=type(validator).__name__, path=path):
                    self.assertEqual(validator._validate_field_path(path), (True, ''))

    def test_apply_and_paste_reject_bad_paths_without_mutating_fields(self):
        session = PackageSession.from_payload({'Documents': [], 'Fields': [
            {'Name': 'Amount', 'Path': '$.bill.amount'}]})
        editor = PackageEditor(session)
        original = editor.snapshot()
        with self.assertRaisesRegex(ValueError, 'Whitespace'):
            editor.update_record(session.fields[0], {'Path': '$. bill.amount'}, 'fields')
        with self.assertRaisesRegex(ValueError, 'Whitespace'):
            editor.paste_fields([{'Name': 'Good', 'Path': '$.good'},
                                 {'Name': 'Bad', 'Path': '$. bill.amount'}])
        self.assertEqual(editor.snapshot(), original)
        self.assertFalse(editor.dirty)
        self.assertEqual(editor.undo_stack, [])
