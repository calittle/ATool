"""Copy and paste layout tree items into their valid parent nodes."""

import unittest
from unittest.mock import Mock

try:
    from ATool import AToolApp
except ImportError:  # pragma: no cover - environments without Tkinter
    AToolApp = None


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class LayoutClipboardTests(unittest.TestCase):
    def _app(self, nodes, parents, selected):
        app = AToolApp.__new__(AToolApp)
        app._layout_node_details = {
            node_id: {"node_kind": kind, "source_ref": source}
            for node_id, (kind, source) in nodes.items()
        }
        app._active_layout_node_id = selected[0]
        app._layout_clipboard = []
        app._layout_clipboard_kind = ""
        app.layouts_tree = Mock()
        app.layouts_tree.selection.side_effect = lambda: tuple(selected)
        app.layouts_tree.get_children.side_effect = lambda parent="": tuple(
            node_id for node_id in nodes if parents[node_id] == parent
        )
        app.layouts_tree.parent.side_effect = lambda node_id: parents[node_id]
        app._show_temporary_status = Mock()
        app._touch_selected_document_updated = Mock()
        app._set_dirty = Mock()
        app._refresh_layouts_for_active_document = Mock()
        app._select_layout_node_for_source = Mock()
        return app

    def test_content_copy_keeps_children_and_deduplicates_name(self):
        content = {"$$Id": "Message", "Iteration": {"$$Id": "Rows", "Fields": []}}
        layout = {"$$Id": "Page", "Contents": [content]}
        app = self._app(
            {"layout": ("layout", layout), "content": ("content", content)},
            {"layout": "", "content": "layout"},
            ["content"],
        )

        app.copy_selected_layout_items()
        content["Iteration"]["$$Id"] = "Changed"
        app.paste_copied_layout_items()

        pasted = layout["Contents"][1]
        self.assertEqual(pasted["$$Id"], "Message Copy")
        self.assertEqual(pasted["Iteration"]["$$Id"], "Rows")
        app._set_dirty.assert_called_once_with(True)
        app._select_layout_node_for_source.assert_called_once_with(pasted, preferred_kind="content")

    def test_field_pastes_into_selected_iteration(self):
        field = {"Name": "Amount", "Path": "$.amount"}
        source_iteration = {"Fields": [field]}
        target_iteration = {"Fields": [{"Name": "Amount"}]}
        app = self._app(
            {
                "source": ("iteration", source_iteration),
                "field": ("field", field),
                "target": ("iteration", target_iteration),
            },
            {"source": "", "field": "source", "target": ""},
            ["field"],
        )

        app.copy_selected_layout_items()
        app._active_layout_node_id = "target"
        app.paste_copied_layout_items()

        self.assertEqual(target_iteration["Fields"][1], {"Name": "Amount Copy", "Path": "$.amount"})

    def test_iteration_paste_does_not_replace_existing_iteration(self):
        iteration = {"$$Id": "Rows", "Fields": []}
        source_content = {"Iteration": iteration}
        target_content = {"Iteration": {"$$Id": "Existing"}}
        app = self._app(
            {
                "source": ("content", source_content),
                "iteration": ("iteration", iteration),
                "target": ("content", target_content),
            },
            {"source": "", "iteration": "source", "target": ""},
            ["iteration"],
        )

        app.copy_selected_layout_items()
        app._active_layout_node_id = "target"
        app.paste_copied_layout_items()

        self.assertEqual(target_content["Iteration"], {"$$Id": "Existing"})
        app._set_dirty.assert_not_called()

    def test_iteration_pastes_into_empty_content(self):
        iteration = {"$$Id": "Rows", "Fields": [{"Name": "Amount"}]}
        source_content = {"Iteration": iteration}
        target_content = {"$$Id": "Target"}
        app = self._app(
            {
                "source": ("content", source_content),
                "iteration": ("iteration", iteration),
                "target": ("content", target_content),
            },
            {"source": "", "iteration": "source", "target": ""},
            ["iteration"],
        )

        app.copy_selected_layout_items()
        app._active_layout_node_id = "target"
        app.paste_copied_layout_items()

        self.assertEqual(target_content["Iteration"], iteration)
        self.assertIsNot(target_content["Iteration"], iteration)
        app._set_dirty.assert_called_once_with(True)

    def test_multiple_fields_keep_tree_order(self):
        first = {"Name": "First"}
        second = {"Name": "Second"}
        iteration = {"Fields": [first, second]}
        app = self._app(
            {"iteration": ("iteration", iteration), "first": ("field", first), "second": ("field", second)},
            {"iteration": "", "first": "iteration", "second": "iteration"},
            ["second", "first"],
        )

        app.copy_selected_layout_items()
        app._active_layout_node_id = "second"
        app.paste_copied_layout_items()

        self.assertEqual(
            [field["Name"] for field in iteration["Fields"]],
            ["First", "Second", "First Copy", "Second Copy"],
        )

    def test_shift_copy_shortcut_shows_clause_manager(self):
        layout = {"$$Id": "Page"}
        app = self._app({"layout": ("layout", layout)}, {"layout": ""}, ["layout"])
        app._show_condition_library_window = Mock()

        self.assertEqual(app._copy_selected_layouts_event(Mock(state=0x0001)), "break")

        app._show_condition_library_window.assert_called_once_with()
        self.assertEqual(app._layout_clipboard, [])


if __name__ == "__main__":
    unittest.main()
