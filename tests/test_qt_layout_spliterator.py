"""Layout repetition authoring, persistence, and scoped preview regression checks."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from atool_qt.content import content_fields
from atool_qt.editor import PackageEditor
from atool_qt.session import PackageSession
from tests.test_qt_mapping_details import flatten


def fixture():
    return PackageSession.from_payload({'$$Id': 'Package', 'Documents': [
        {'$$Id': 'Doc', 'Layouts': [{'$$Id': 'Charges', 'Contents': [
            {'$$Id': 'ChargeText', 'Condition': '$[?(@.charge > 0)]'},
            {'$$Id': 'Details', 'Iteration': {'$$Id': 'DetailsLoop', 'Type': 'Iterator',
                'Path': '$.details[*]', 'Fields': [{'Name': 'Detail', 'Path': '$.value'}]}}]},
            {'$$Id': 'Other', 'Contents': [{'$$Id': 'OtherText'}]}]}]})


def add_loop(session):
    editor = PackageEditor(session)
    key = editor.add_layout_item(session.documents[0], 'Iteration', 'layout/0')
    editor.update_layout(session.documents[0], key, {'$$Id': 'ChargeLayoutLoop', 'Path': '$.chargeRows[*]'})
    field = editor.add_layout_item(session.documents[0], 'Field', key)
    editor.update_layout(session.documents[0], field, {'Name': 'charge', 'Path': '$.charge'})
    return editor, key


class LayoutSpliteratorTests(unittest.TestCase):
    def test_create_edit_save_reload_and_undo(self):
        session = fixture()
        editor, key = add_loop(session)
        loop = editor.layout_source(session.documents[0], key)[0]
        self.assertEqual('Spliterator', loop['Type'])
        before = editor.snapshot()
        with self.assertRaisesRegex(ValueError, 'Spliterator'):
            editor.update_layout(session.documents[0], key, {'Type': 'Iterator'})
        with self.assertRaisesRegex(ValueError, 'already has'):
            editor.add_layout_item(session.documents[0], 'Iteration', 'layout/0')
        self.assertEqual(before, editor.snapshot())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'AT.json'
            editor.save(path)
            saved = json.loads(path.read_text())['Documents'][0]['Layouts'][0]
            self.assertEqual(loop, saved['Iteration'])
            self.assertEqual('ChargeText', saved['Contents'][0]['$$Id'])
            reloaded = PackageSession.open(path)
            self.assertEqual(loop, reloaded.documents[0]['source']['Layouts'][0]['Iteration'])
        editor.remove_layout_item(session.documents[0], key)
        editor.undo()
        self.assertEqual(loop, editor.layout_source(session.documents[0], key)[0])
        editor.redo()
        self.assertNotIn('Iteration', session.documents[0]['source']['Layouts'][0])

    def test_paste_layout_iteration_and_fields(self):
        session = fixture()
        editor, key = add_loop(session)
        loop = copy.deepcopy(editor.layout_source(session.documents[0], key)[0])
        pasted = editor.paste_layout_items(session.documents[0], 'Iteration', [loop], 'layout/1')
        self.assertEqual('layout/1/Iteration', pasted)
        self.assertEqual(loop, editor.layout_source(session.documents[0], pasted)[0])
        self.assertIsNot(loop, editor.layout_source(session.documents[0], pasted)[0])
        field = editor.paste_layout_items(session.documents[0], 'Field', [{'Name': 'rate', 'Path': '$.rate'}], pasted)
        self.assertEqual('layout/1/Iteration/Fields/1', field)
        editor.remove_layout_item(session.documents[0], pasted)
        with self.assertRaisesRegex(ValueError, 'Spliterator'):
            editor.paste_layout_items(session.documents[0], 'Iteration', [dict(loop, Type='Iterator')], 'layout/1')

    def test_layout_rows_scope_content_conditions_and_nested_iterations(self):
        session = fixture()
        add_loop(session)
        session.map_data({'chargeRows': [{'charge': 0, 'details': [{'value': 4}]},
                                        {'charge': 7, 'details': [{'value': 8}, {'value': 9}]}]}, 'data')
        nodes = {node['key']: node for node in flatten(session.layouts_for(session.documents[0]))}
        self.assertTrue(nodes['layout/0']['state'])
        self.assertTrue(nodes['layout/0/Contents/0']['state'])
        self.assertEqual([[0], [7]], [row['values'] for row in nodes['layout/0/Iteration/Fields/0']['rows']])
        details = nodes['layout/0/Contents/1/Iteration/Fields/0']['rows']
        self.assertEqual(['1.1', '2.1', '2.2'], [row['row'] for row in details])
        self.assertEqual([[4], [8], [9]], [row['values'] for row in details])
        for data in ({'chargeRows': []}, {}):
            session.map_data(data, 'empty')
            nodes = list(flatten(session.layouts_for(session.documents[0])))
            self.assertTrue(all(not node['state'] for node in nodes if node['key'].startswith('layout/0')))

    def test_layout_condition_suppresses_iteration_and_content(self):
        session = fixture()
        editor, _ = add_loop(session)
        editor.update_layout(session.documents[0], 'layout/0', {'Condition': '$[?(@.enabled == true)]'})
        session.map_data({'enabled': False, 'chargeRows': [{'charge': 7}]}, 'data')
        nodes = list(flatten(session.layouts_for(session.documents[0])))
        self.assertTrue(all(not node['state'] for node in nodes if node['key'].startswith('layout/0')))

    def test_content_palette_inherits_fields_without_a_comms_loop(self):
        session = fixture()
        add_loop(session)
        fields, loops = content_fields(session, 'ChargeText')
        self.assertEqual(['charge'], [field['name'] for field in fields])
        self.assertEqual([], loops)
        fields, loops = content_fields(session, 'Details')
        self.assertEqual({'charge', 'Detail'}, {field['name'] for field in fields})
        self.assertEqual(['DetailsLoop'], [loop['name'] for loop in loops])
        self.assertEqual(([], []), content_fields(session, 'OtherText'))
