"""Field authoring must validate input before the resolver trims segments."""
import unittest
import tempfile
from pathlib import Path

from ATool import AToolApp
from atool_core.field_path_validation import iteration_path_error, iteration_path_issues
from atool_qt.data_queries import DataQueries
from atool_qt.editor import PackageEditor
from atool_qt.session import PackageSession


BILL_PATH = (
    "$.billPrint.premise.premList[*].serviceAgreement.saList[?(@.saType != 'E-FIT')]"
    ".billSegment.bsegList[*].bsegSQ.bsegSQList[?(@.uom == 'KWH' && @.sqi == 'BILL')].billSq"
)


class IteratorPathValidationTests(unittest.TestCase):
    def make_editor(self):
        session = PackageSession.from_payload({'Documents': [{'$$Id': 'Doc', 'Layouts': [
            {'Contents': [{'Iteration': {'Type': 'Iterator', 'Path': '$.rows[*]', 'Fields': [
                {'Name': 'Joined', 'Path': "$.concat($.values[*], ', ')"}]}}]}]}], 'Fields': []})
        return session, PackageEditor(session)

    def test_concat_calls_rejected_but_literal_text_and_collection_paths_allowed(self):
        for path in ("$.concat($.rows[*], '')", "$.concat ($.rows[*], '')",
                     "$.length($.concat($.rows[*], ''))"):
            with self.subTest(path=path):
                self.assertIn('cannot use concat', iteration_path_error(path))
        for path in ('$', '$.rows[*]', "$['concat(foo)']", '$.rows[?(@.name == "concat(foo)")]',
                     '$.concatItems[*]'):
            with self.subTest(path=path):
                self.assertEqual('', iteration_path_error(path))

    def test_invalid_edit_and_paste_leave_model_and_history_untouched(self):
        session, editor = self.make_editor()
        before = editor.snapshot()
        document = session.documents[0]
        with self.assertRaisesRegex(ValueError, 'cannot use concat'):
            editor.update_layout(document, 'layout/0/Contents/0/Iteration', {'Path': "$.concat($.rows[*], '')"})
        for kind, clipboard in (
            ('Iteration', [{'Path': "$.concat($.rows[*], '')"}]),
            ('Content', [{'iteration': {'Path': "$.concat($.rows[*], '')"}}]),
            ('Layout', [{'Contents': [{'Iteration': {'Path': "$.concat($.rows[*], '')"}}]}])):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'cannot use concat'):
                editor.paste_layout_items(document, kind, clipboard, 'layout/0')
        self.assertEqual(before, editor.snapshot())
        self.assertEqual([], editor.undo_stack)

    def test_iterator_fields_allow_concat_and_save_round_trip(self):
        session, editor = self.make_editor()
        editor.update_layout(session.documents[0], 'layout/0/Contents/0/Iteration/Fields/0',
                             {'Path': "$.concat($.values[*], ' / ')"})
        self.assertEqual([], iteration_path_issues(session.payload))
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'AT.json'
            editor.save(target)
            reopened = PackageSession.open(target)
            iteration = reopened.payload['Documents'][0]['Layouts'][0]['Contents'][0]['Iteration']
            self.assertEqual('$.rows[*]', iteration['Path'])
            self.assertEqual("$.concat($.values[*], ' / ')", iteration['Fields'][0]['Path'])

    def test_save_rejects_imported_iterator_concat_without_writing(self):
        session, editor = self.make_editor()
        session.payload['Documents'][0]['Layouts'][0]['Contents'][0]['Iteration']['Path'] = "$.concat($.rows[*], '')"
        before = editor.snapshot()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'AT.json'
            with self.assertRaisesRegex(ValueError, 'cannot use concat'):
                editor.save(target)
            self.assertFalse(target.exists())
        self.assertEqual(before, editor.snapshot())


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
        paths = [f"$.concat({BILL_PATH}, '')", '$', '$..bill', "$.concat($.rows[*].amount, '')", '$.rows[0].amount',
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

    def test_array_wildcards_require_an_enclosing_concat_or_length_call(self):
        paths = [BILL_PATH, '$.rows[*].amount', '$.rows[ * ].amount',
                 '$.length($.good) + $.rows[*].amount',
                 "$.concat($.good, '[*]') + $.rows[*].amount",
                 "$.concat($.good, '') + $.rows[*].amount"]
        for validator in self.validators():
            for path in paths:
                with self.subTest(validator=type(validator).__name__, path=path):
                    valid, reason = validator._validate_field_path(path)
                    self.assertFalse(valid)
                    self.assertIn('must use concat or length', reason)
            self.assertFalse(validator._validate_field_path("$.notconcat($.rows[*].amount, '')")[0])
            self.assertFalse(validator._validate_field_path('$.notlength($.rows[*])')[0])

    def test_concat_and_length_handle_wildcards_without_matching_literal_text(self):
        paths = ["$.concat($.rows[*].amount, ', ')",
                 "$.concat($.rows[ * ].amount, '')",
                 "$.concat($.groups[*].rows[*].amount, '')",
                 "$.length($.concat($.rows[*].amount, ''))",
                 '$.length($.rows[*])',
                 '$.length($.rows[ * ].amount)',
                 '$.length($.groups[*].rows[*].amount)',
                 f'$.length({BILL_PATH})',
                 "$.concat($.length($.rows[*]), '')",
                 "$['literal[*]']", '$.rows[?(@.name == "[*]")].amount']
        for validator in self.validators():
            for path in paths:
                with self.subTest(validator=type(validator).__name__, path=path):
                    self.assertEqual(validator._validate_field_path(path), (True, ''))
            self.assertEqual(validator._validate_field_path('$.rows[*].amount', require_concat=False), (True, ''))

    def test_apply_and_paste_enforce_concat_atomically(self):
        session = PackageSession.from_payload({'Documents': [], 'Fields': [
            {'Name': 'Amount', 'Path': '$.bill.amount'}]})
        editor = PackageEditor(session)
        original = editor.snapshot()
        with self.assertRaisesRegex(ValueError, 'must use concat'):
            editor.update_record(session.fields[0], {'Path': '$.rows[*].amount'}, 'fields')
        with self.assertRaisesRegex(ValueError, 'must use concat'):
            editor.paste_fields([{'Name': 'Good', 'Path': '$.good'},
                                 {'Name': 'Bad', 'Path': '$.rows[*].amount'}])
        self.assertEqual(editor.snapshot(), original)
        self.assertEqual(editor.undo_stack, [])
        editor.update_record(session.fields[0], {'Path': "$.concat($.rows[*].amount, '')"}, 'fields')
        self.assertEqual(session.fields[0]['source']['Path'], "$.concat($.rows[*].amount, '')")

    def test_apply_and_paste_allow_length_with_array_wildcards(self):
        session = PackageSession.from_payload({'Documents': [], 'Fields': [
            {'Name': 'Count', 'Path': '$.count'}]})
        editor = PackageEditor(session)
        editor.update_record(session.fields[0], {'Path': '$.length($.rows[*])'}, 'fields')
        self.assertEqual(session.fields[0]['source']['Path'], '$.length($.rows[*])')
        editor.paste_fields([{'Name': 'ItemCount', 'Path': '$.length($.groups[*].items[*])'}])
        self.assertEqual(session.fields[-1]['source']['Path'], '$.length($.groups[*].items[*])')
        self.assertTrue(editor.dirty)
