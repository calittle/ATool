"""Moving layout items keeps the current tree selection available for another move."""

import unittest
from unittest.mock import Mock

try:
    from ATool import AToolApp
except ImportError:  # pragma: no cover - environments without Tkinter
    AToolApp = None


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class LayoutMoveTests(unittest.TestCase):
    def _app(self, layouts, selected_node, selected_kind, selected_item, parent=""):
        app = AToolApp.__new__(AToolApp)
        app._active_layout_node_id = selected_node
        app._layout_node_details = {
            f"layout-{index}": {"node_kind": "layout", "source_ref": layout}
            for index, layout in enumerate(layouts)
        }
        if selected_kind == "content":
            app._layout_node_details[selected_node] = {"node_kind": "content", "source_ref": selected_item}
        document = {"source": {"Layouts": layouts}}
        app._get_selected_document_ref = Mock(return_value=document)
        app._touch_selected_document_updated = Mock()
        app._set_dirty = Mock()
        app._refresh_layouts_for_active_document = Mock()
        app.layouts_tree = Mock()
        app.layouts_tree.parent.return_value = parent
        return app

    def test_layout_can_move_twice_without_reselection(self):
        layouts = [{"$$Id": name} for name in ("First", "Second", "Third")]
        app = self._app(layouts, "layout-2", "layout", layouts[2])
        siblings = ["layout-0", "layout-1", "layout-2"]
        app.layouts_tree.get_children.side_effect = lambda _parent: tuple(siblings)

        def move(node, _parent, index):
            siblings.remove(node)
            siblings.insert(index, node)

        app.layouts_tree.move.side_effect = move

        app.move_selected_layout_item(-1)
        app.move_selected_layout_item(-1)
        self.assertEqual([layout["$$Id"] for layout in layouts], ["Third", "First", "Second"])
        self.assertEqual(siblings, ["layout-2", "layout-0", "layout-1"])

        app.move_selected_layout_item(1)
        app.move_selected_layout_item(1)

        self.assertEqual([layout["$$Id"] for layout in layouts], ["First", "Second", "Third"])
        self.assertEqual(siblings, ["layout-0", "layout-1", "layout-2"])
        self.assertEqual(app._active_layout_node_id, "layout-2")
        self.assertEqual(app.layouts_tree.move.call_count, 4)
        app._refresh_layouts_for_active_document.assert_not_called()

    def test_content_moves_within_its_layout(self):
        contents = [{"$$Id": name} for name in ("First", "Second", "Third")]
        layout = {"Contents": contents}
        app = self._app([layout], "content-1", "content", contents[1], parent="layout-0")
        app._layout_node_details.update({
            f"content-{index}": {"node_kind": "content", "source_ref": content}
            for index, content in enumerate(contents)
        })
        app.layouts_tree.get_children.return_value = ("content-0", "content-1", "content-2")

        app.move_selected_layout_item(-1)

        self.assertEqual([content["$$Id"] for content in contents], ["Second", "First", "Third"])
        app.layouts_tree.move.assert_called_once_with("content-1", "layout-0", 0)


if __name__ == "__main__":
    unittest.main()
