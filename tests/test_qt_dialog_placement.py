"""Dialog placement for offscreen parents and multiple monitor arrangements."""
import unittest
from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow
from atool_qt.dialog_placement import DialogPlacement, dialog_position


class DialogPlacementTests(unittest.TestCase):
    def test_new_dialog_is_positioned_before_display(self):
        app = QApplication.instance() or QApplication([])
        workspace = QMainWindow()
        workspace.setObjectName('atool-qt-workspace')
        placement = DialogPlacement(app)
        app.installEventFilter(placement)
        try:
            workspace.move(3500, 700)
            dialog = QDialog(workspace)
            dialog.resize(480, 120)
            dialog.show()
            app.processEvents()
            self.assertTrue(app.primaryScreen().availableGeometry().contains(dialog.frameGeometry()))
            dialog.close()
        finally:
            app.removeEventFilter(placement)
            workspace.close()

    def test_partly_offscreen_parent_keeps_dialog_on_visible_monitor(self):
        screens = [QRect(0, 0, 1920, 1080), QRect(1920, 0, 1920, 1080)]
        size = QSize(660, 240)
        point = dialog_position(QRect(3400, 600, 1440, 900), size, screens)
        self.assertTrue(screens[1].contains(QRect(point, size)))

    def test_removed_monitor_uses_nearest_remaining_screen(self):
        screen = QRect(0, 0, 1920, 1080)
        size = QSize(480, 120)
        point = dialog_position(QRect(3492, 635, 1440, 900), size, [screen])
        self.assertTrue(screen.contains(QRect(point, size)))

    def test_monitor_with_negative_coordinates_is_preserved(self):
        screens = [QRect(-1920, -200, 1920, 1080), QRect(0, 0, 1920, 1080)]
        size = QSize(660, 240)
        point = dialog_position(QRect(-1800, -100, 1200, 800), size, screens)
        self.assertTrue(screens[0].contains(QRect(point, size)))
