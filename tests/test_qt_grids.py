"""User resizing and sorting across manager grids without changing package order."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHeaderView, QTreeWidget, QTreeWidgetItem
from atool_qt.grids import configure_grid
from atool_qt.session import demo_session
from atool_qt.window import ClausePanel, WorkspaceWindow


class GridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_header_sort_is_opt_in_and_toggles_direction(self):
        tree = QTreeWidget()
        tree.setHeaderLabels(['Name', 'Value'])
        configure_grid(tree)
        tree.addTopLevelItems([QTreeWidgetItem(['Bravo', 'A']), QTreeWidgetItem(['Alpha', 'B'])])
        self.assertEqual(tree.topLevelItem(0).text(0), 'Bravo')
        tree.header().sectionClicked.emit(0)
        self.assertEqual(tree.topLevelItem(0).text(0), 'Alpha')
        tree.header().sectionClicked.emit(0)
        self.assertEqual(tree.topLevelItem(0).text(0), 'Bravo')
        tree.header().sectionClicked.emit(1)
        self.assertEqual(tree.topLevelItem(0).text(1), 'A')

    def test_grid_fills_spare_width_and_last_column_still_resizes(self):
        tree = QTreeWidget()
        tree.setHeaderLabels(['Name', 'Value'])
        configure_grid(tree)
        tree.resize(700, 200)
        tree.show()
        try:
            self.app.processEvents()
            self.assertEqual(tree.header().length(), tree.viewport().width())
            tree.header().resizeSection(1, 220)
            self.app.processEvents()
            self.assertEqual(tree.columnWidth(1), 220)
            tree.resize(800, 200)
            self.app.processEvents()
            self.assertEqual(tree.header().length(), tree.viewport().width())
            tree.resize(500, 200)
            self.app.processEvents()
            self.assertEqual(tree.header().length(), tree.viewport().width())
        finally:
            tree.close()

    def test_clause_columns_sort_on_mouse_click_and_keep_selection_on_refresh(self):
        panel = ClausePanel()
        session = demo_session()
        session.clauses = [
            {'name': 'Alpha', 'description': 'Zulu', 'expression': '@.alpha'},
            {'name': 'Bravo', 'description': 'Alpha', 'expression': '@.bravo'},
            {'name': 'Charlie', 'description': 'Middle', 'expression': '@.charlie'},
        ]
        panel.favorite_names = {'Bravo'}
        panel.resize(900, 800)
        panel.set_session(session)
        panel.show()
        self.app.processEvents()
        tree = panel.tree
        header = tree.header()

        def click(column):
            position = header.viewport().rect().center()
            position.setX(header.sectionViewportPosition(column) + header.sectionSize(column) // 2)
            QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=position)
            self.app.processEvents()

        def names():
            return [tree.topLevelItem(row).text(0) for row in range(tree.topLevelItemCount())]

        try:
            click(0)
            self.assertEqual(names(), ['Alpha', 'Bravo', 'Charlie'])
            click(0)
            self.assertEqual(names(), ['Charlie', 'Bravo', 'Alpha'])
            click(1)
            self.assertEqual(names(), ['Bravo', 'Charlie', 'Alpha'])
            click(1)
            self.assertEqual(names(), ['Alpha', 'Charlie', 'Bravo'])
            tree.setCurrentItem(tree.topLevelItem(1))
            panel.set_session(session)
            self.assertEqual(names(), ['Alpha', 'Charlie', 'Bravo'])
            self.assertEqual(panel.name.text(), 'Charlie')
            self.assertEqual(panel.expression.toPlainText(), '@.charlie')
            panel.search.setText('Middle')
            self.assertFalse(tree.currentItem().isHidden())
            panel.search.clear()
            click(2)
            self.assertEqual(names()[-1], 'Bravo')
            click(2)
            self.assertEqual(names()[0], 'Bravo')
            self.assertEqual([row['name'] for row in session.clauses], ['Alpha', 'Bravo', 'Charlie'])
        finally:
            panel.close()

    def test_all_manager_columns_resize_and_user_sort_survives_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            window = WorkspaceWindow(QSettings(str(Path(directory)/'qt.ini'), QSettings.Format.IniFormat))
            try:
                session = demo_session()
                window.set_session(session)
                source_order = [record['name'] for record in session.documents]
                for tree in window.findChildren(QTreeWidget):
                    for column in range(tree.columnCount()):
                        self.assertEqual(tree.header().sectionResizeMode(column), QHeaderView.ResizeMode.Interactive)
                        tree.header().resizeSection(column, 180+column*20)
                        self.assertEqual(tree.header().sectionSize(column), 180+column*20)
                    tree.header().sectionClicked.emit(0)
                    self.assertTrue(tree.isSortingEnabled())
                window.documents.tree.header().sectionClicked.emit(0)
                window.documents.set_session(session, preserve_selection=True)
                self.assertTrue(window.documents.tree.isSortingEnabled())
                self.assertEqual(window.documents.tree.header().sortIndicatorOrder(), Qt.SortOrder.DescendingOrder)
                self.assertEqual([record['name'] for record in session.documents], source_order)
            finally:
                with patch.object(window, 'confirm_quit', return_value=True), patch.object(window, 'confirm_discard', return_value=True):
                    window.close()
