"""Keyboard shortcuts with shifted and unshifted actions."""

import unittest
from unittest.mock import Mock

try:
    from ATool import AToolApp
except ImportError:  # pragma: no cover - environments without Tkinter
    AToolApp = None


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class ShortcutTests(unittest.TestCase):
    def test_shift_command_p_shows_package_documents_instead_of_preview(self):
        app = AToolApp.__new__(AToolApp)
        app.show_package_documents_manager = Mock()
        app.preview_occs_package = Mock()

        self.assertEqual(app._preview_event(Mock(state=0x0001)), "break")

        app.show_package_documents_manager.assert_called_once_with()
        app.preview_occs_package.assert_not_called()

    def test_command_p_still_previews(self):
        app = AToolApp.__new__(AToolApp)
        app.show_package_documents_manager = Mock()
        app.preview_occs_package = Mock()

        self.assertEqual(app._preview_event(Mock(state=0)), "break")

        app.preview_occs_package.assert_called_once_with()
        app.show_package_documents_manager.assert_not_called()


if __name__ == "__main__":
    unittest.main()
