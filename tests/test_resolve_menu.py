"""Enable Resolve only for a selected document with mapped data."""

from __future__ import annotations

import unittest

try:
    import tkinter as tk
    from ATool import AToolApp
except ModuleNotFoundError:  # Some CLI Python installations omit Tk.
    tk = None
    AToolApp = None


class FakeMenu:
    def __init__(self) -> None:
        self.state = None

    def entryconfig(self, _index: int, *, state: str) -> None:
        self.state = state


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class ResolveMenuTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = AToolApp.__new__(AToolApp)
        self.app.current_payload = {"Documents": []}
        self.app.current_package_name = "Pkg"
        self.app.current_data_payload = {"sample": True}
        self.app._mapping_in_progress = False
        self.app._active_document_node_id = "doc-node"
        self.app._document_node_details = {"doc-node": {"document_ref": {"name": "Doc"}}}
        self.menu = FakeMenu()
        self.app._data_menu_entries = [(self.menu, 0, "resolve")]

    def test_selection_mapping_and_package_are_required(self) -> None:
        self.app._update_data_menu_states()
        self.assertEqual(tk.NORMAL, self.menu.state)

        self.app.current_data_payload = None
        self.app._update_data_menu_states()
        self.assertEqual(tk.DISABLED, self.menu.state)

        self.app.current_data_payload = {}
        self.app._active_document_node_id = None
        self.app._update_data_menu_states()
        self.assertEqual(tk.DISABLED, self.menu.state)

        self.app._active_document_node_id = "doc-node"
        self.app.current_payload = None
        self.app._update_data_menu_states()
        self.assertEqual(tk.DISABLED, self.menu.state)


if __name__ == "__main__":
    unittest.main()
