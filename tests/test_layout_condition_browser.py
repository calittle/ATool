"""Layout conditions can be evaluated from the Data Browser."""

import unittest
from unittest.mock import Mock

try:
    from ATool import AToolApp
except ImportError:  # pragma: no cover - environments without Tkinter
    AToolApp = None


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class LayoutConditionBrowserTests(unittest.TestCase):
    def test_layout_field_browser_search_includes_parent_iterator(self):
        app = AToolApp.__new__(AToolApp)
        app._active_layout_node_id = "field-node"
        iterator_path = "$..billCalcLineList[?(@.cmElements.chargeType == 'EC')]"
        app._layout_node_details = {
            "field-node": {"node_kind": "field", "source_ref": {"Path": "$.cmElements.calcAmt"}},
            "iterator-node": {"node_kind": "iteration", "source_ref": {"Path": iterator_path}},
        }
        app.layouts_tree = Mock()
        app.layouts_tree.parent.side_effect = lambda node: {"field-node": "iterator-node", "iterator-node": ""}[node]
        app.data_browser_search_mode_var = Mock()
        app.data_browser_search_var = Mock()
        app._show_data_browser_window = Mock()
        app._search_data_browser = Mock()

        app._open_selected_layout_path_in_data_browser()

        app.data_browser_search_mode_var.set.assert_called_once_with("JSONPath")
        app.data_browser_search_var.set.assert_called_once_with(iterator_path + ".cmElements.calcAmt")
        app._search_data_browser.assert_called_once_with()

    def test_full_layout_field_path_is_not_prefixed_again(self):
        app = AToolApp.__new__(AToolApp)
        self.assertEqual(
            "$.orders[*].amount",
            app._layout_field_browser_path("$.orders[*].amount", "$.orders[*]"),
        )

    def test_selected_condition_opens_browser_and_runs_search(self):
        app = AToolApp.__new__(AToolApp)
        app._active_layout_node_id = "condition-node"
        app._layout_node_details = {
            "condition-node": {"node_kind": "condition", "source_ref": {"Condition": "@.active == true"}}
        }
        app.layout_condition_edit_var = Mock()
        app.layout_condition_edit_var.get.return_value = "  @.active == true  "
        app.data_browser_search_mode_var = Mock()
        app.data_browser_search_var = Mock()
        app._show_data_browser_window = Mock()
        app._search_data_browser = Mock()

        app._open_selected_layout_condition_in_data_browser()

        app._show_data_browser_window.assert_called_once_with()
        app.data_browser_search_mode_var.set.assert_called_once_with("Condition")
        app.data_browser_search_var.set.assert_called_once_with("@.active == true")
        app._search_data_browser.assert_called_once_with()

    def test_condition_search_reports_evaluation_result(self):
        app = AToolApp.__new__(AToolApp)
        app._loaded_fields = []
        app.current_data_payload = {"active": True}
        app.data_browser_search_var = Mock()
        app.data_browser_search_var.get.return_value = "@.active == true"
        app.data_browser_search_mode_var = Mock()
        app.data_browser_search_mode_var.get.return_value = "Condition"
        app.data_browser_tree = Mock()
        app.data_browser_tree.get_children.return_value = ()
        app.data_browser_tree.insert.return_value = "result"
        app.data_browser_details = Mock()
        app.data_browser_selected_path_var = Mock()
        app.data_browser_status_var = Mock()
        app._set_readonly_text_widget_value = Mock()
        app._search_data_browser()

        app.data_browser_tree.insert.assert_called_once_with("", "end", text="Condition", values=("PASS",))
        self.assertIs(app._data_browser_node_values["result"], True)
        app.data_browser_status_var.set.assert_called_once_with("Condition: PASS.")

        app.current_data_payload = {"active": False}
        app.data_browser_tree.insert.reset_mock()
        app.data_browser_status_var.set.reset_mock()
        app._search_data_browser()
        app.data_browser_tree.insert.assert_called_once_with("", "end", text="Condition", values=("FAIL",))
        self.assertIs(app._data_browser_node_values["result"], False)
        app.data_browser_status_var.set.assert_called_once_with("Condition: FAIL.")


if __name__ == "__main__":
    unittest.main()
