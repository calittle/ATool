"""Exercise composer completion through real keyboard and mouse events."""
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from atool_qt.clause_completion import ClauseComposeEdit


class ClauseCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def editor(self, prefix='Do_No'):
        widget = ClauseComposeEdit()
        self.addCleanup(widget.close)
        widget.set_clauses([{'name': 'Do_Normal'}, {'name': 'Do_Not_Print'}, {'name': 'Has Flag'}])
        widget.show()
        widget.setFocus()
        QTest.keyClicks(widget, prefix)
        self.app.processEvents()
        self.assertTrue(widget.completer.popup().isVisible())
        return widget

    def test_first_suggestion_accepts_enter_and_tab_from_popup_or_editor(self):
        for target in ('popup', 'editor'):
            for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                with self.subTest(target=target, key=key):
                    widget = self.editor()
                    popup = widget.completer.popup()
                    self.assertEqual('Do_Normal', popup.currentIndex().data())
                    QTest.keyClick(popup if target == 'popup' else widget, key)
                    self.assertEqual('Do_Normal', widget.toPlainText())
                    self.assertFalse(popup.isVisible())
                    widget.undo()
                    self.assertEqual('Do_No', widget.toPlainText())
                    widget.close()

    def test_arrow_navigation_and_escape_from_popup_or_editor(self):
        for target in ('popup', 'editor'):
            with self.subTest(target=target):
                widget = self.editor()
                popup = widget.completer.popup()
                receiver = popup if target == 'popup' else widget
                QTest.keyClick(receiver, Qt.Key.Key_Down)
                self.assertEqual('Do_Not_Print', popup.currentIndex().data())
                QTest.keyClick(receiver, Qt.Key.Key_Up)
                self.assertEqual('Do_Normal', popup.currentIndex().data())
                QTest.keyClick(receiver, Qt.Key.Key_Down)
                QTest.keyClick(receiver, Qt.Key.Key_Return)
                self.assertEqual('Do_Not_Print', widget.toPlainText())
                widget.close()
                widget = self.editor()
                popup = widget.completer.popup()
                QTest.keyClick(popup if target == 'popup' else widget, Qt.Key.Key_Escape)
                self.assertEqual('Do_No', widget.toPlainText())
                self.assertFalse(popup.isVisible())
                widget.close()

    def test_click_accepts_contains_match_with_space_safe_name(self):
        widget = self.editor('Do_Normal + Flag')
        popup = widget.completer.popup()
        index = widget.completer.completionModel().index(0, 0)
        self.assertEqual('Has Flag', index.data())
        QTest.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton,
                         pos=popup.visualRect(index).center())
        self.assertEqual('Do_Normal + CLAUSE{Has Flag}', widget.toPlainText())
        self.assertFalse(popup.isVisible())


if __name__ == '__main__':
    unittest.main()
