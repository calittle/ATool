"""Password login controls fit when the dialog first opens."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMainWindow, QStyleFactory

from atool_qt.migration_login import MigrationLoginDialog


class PasswordLoginLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_initial_size_fits_controls_with_platform_styles(self):
        original_style = self.app.style().objectName()
        self.addCleanup(self.app.setStyle, original_style)
        workspace = QMainWindow()
        workspace.comms = SimpleNamespace(migration_logins={})
        self.addCleanup(workspace.close)
        with patch('atool_qt.migration_login.saved_login_targets', return_value=({}, '')), \
                patch('atool_qt.migration_login.remembered_migration_login', return_value='user@example.com'):
            for style in QStyleFactory.keys():
                self.app.setStyle(style)
                for purpose in ('migration', 'conversion'):
                    with self.subTest(style=style, purpose=purpose):
                        dialog = MigrationLoginDialog(workspace, 'np', 'pp', purpose=purpose)
                        self.addCleanup(dialog.close)
                        dialog.show()
                        self.app.processEvents()
                        controls = [dialog.migration_username, dialog.migration_password,
                                    dialog.remember_migration_login, dialog.test_migration_login_button,
                                    dialog.forget_migration_login_button, *dialog.buttons.buttons()]
                        for control in controls:
                            self.assertTrue(control.isVisible())
                            self.assertGreaterEqual(control.height(), control.minimumSizeHint().height())
                            parent = control.parentWidget()
                            self.assertTrue(parent.rect().contains(control.geometry()))
                        self.assertGreater(dialog.migration_username.width(),
                                           dialog.migration_username.sizeHint().width())
                        dialog.close()
