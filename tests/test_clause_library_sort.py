"""Clause library sorting preserves editor identity and the stored library order."""
import unittest
from unittest.mock import Mock

from ATool import AToolApp


class ClauseLibrarySortTests(unittest.TestCase):
    def test_headers_toggle_sort_and_filter_preserves_selected_clause(self):
        app = AToolApp.__new__(AToolApp)
        app._condition_library_entries = [
            {'name': 'Alpha', 'description': 'zulu', 'expression': '@.a'},
            {'name': 'Bravo', 'description': 'Alpha', 'expression': '@.b'},
            {'name': 'Charlie', 'description': 'middle', 'expression': '@.c'},
        ]
        app._active_condition_library_index = 1
        app._condition_library_sort_column = 'name'
        app._condition_library_sort_desc = False
        app.condition_clause_filter_var = Mock()
        app.condition_clause_filter_var.get.return_value = ''
        tree = app.condition_library_list = Mock()
        tree.get_children.return_value = ()
        tree.insert.side_effect = lambda *args, **kwargs: kwargs['text']

        def rendered_names():
            names = [call.kwargs['text'] for call in tree.insert.call_args_list]
            tree.insert.reset_mock()
            return names

        app._set_condition_library_sort('description')
        self.assertEqual(rendered_names(), ['Bravo', 'Charlie', 'Alpha'])
        self.assertEqual(app._condition_library_node_to_index['Bravo'], 1)
        tree.selection_set.assert_called_with('Bravo')
        tree.heading.assert_any_call('description', text='Description ▲')
        app._set_condition_library_sort('description')
        self.assertEqual(rendered_names(), ['Alpha', 'Charlie', 'Bravo'])
        app.condition_clause_filter_var.get.return_value = '@.b'
        app._render_condition_library_list()
        self.assertEqual(rendered_names(), ['Bravo'])
        self.assertEqual(app._condition_library_sort_desc, True)
        app.condition_clause_filter_var.get.return_value = ''
        app._set_condition_library_sort('name')
        self.assertEqual(rendered_names(), ['Alpha', 'Bravo', 'Charlie'])
        app._set_condition_library_sort('name')
        self.assertEqual(rendered_names(), ['Charlie', 'Bravo', 'Alpha'])
        self.assertEqual([entry['name'] for entry in app._condition_library_entries],
                         ['Alpha', 'Bravo', 'Charlie'])
