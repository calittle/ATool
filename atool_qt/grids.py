"""Consistent interactive columns without changing source order on initial display."""
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QColor, QPalette, QPen
from PySide6.QtWidgets import QHeaderView, QStyle, QStyledItemDelegate

SELECTION_COLOR = '#E3D2FF'
SELECTION_OUTLINE = '#7950B3'


class GridColumnFill(QObject):
    """Fill spare width without locking the last column into Qt's Stretch mode."""
    def __init__(self, tree):
        super().__init__(tree)
        self.tree = tree
        self.adjusting = False
        self.widths = {column: tree.columnWidth(column) for column in range(tree.columnCount())}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fill)
        tree.installEventFilter(self)
        tree.viewport().installEventFilter(self)
        tree.header().sectionResized.connect(self.column_resized)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize):
            self.timer.start(0)
        return False

    def column_resized(self, column, old, width):
        if not self.adjusting:
            self.widths[column] = width
            if column != self.tree.columnCount() - 1:
                self.timer.start(0)

    def fill(self):
        header = self.tree.header()
        visible = [header.logicalIndex(i) for i in range(header.count()) if not header.isSectionHidden(header.logicalIndex(i))]
        if not visible or not self.tree.isVisible():
            return
        last = visible[-1]
        width = max(self.widths.get(last, header.defaultSectionSize()),
                    self.tree.viewport().width() - sum(header.sectionSize(column) for column in visible[:-1]))
        self.adjusting = True
        try:
            header.resizeSection(last, width)
        finally:
            self.adjusting = False


class StatusDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        option.palette.setColor(QPalette.ColorRole.HighlightedText,
                                foreground.color() if foreground is not None else QColor('#1f2937'))
        option.palette.setColor(QPalette.ColorRole.Highlight, QColor(SELECTION_COLOR))

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            painter.setPen(QPen(QColor(SELECTION_OUTLINE), 1))
            rect = option.rect.adjusted(0, 0, -1, -1)
            painter.drawLine(rect.topLeft(), rect.topRight())
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())
            header = self.parent().header()
            visible = [header.logicalIndex(i) for i in range(header.count()) if not header.isSectionHidden(header.logicalIndex(i))]
            if index.column() == visible[0]:
                painter.drawLine(rect.topLeft(), rect.bottomLeft())
            if index.column() == visible[-1]:
                painter.drawLine(rect.topRight(), rect.bottomRight())
            painter.restore()


def configure_grid(tree):
    tree.setItemDelegate(StatusDelegate(tree))
    tree.setStyleSheet(f'QTreeView::item:selected {{ background-color: {SELECTION_COLOR}; }}')
    header = tree.header()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(False)
    header.setSectionsClickable(True)
    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
    header.setSortIndicatorShown(False)
    tree._grid_column_fill = GridColumnFill(tree)

    def sort_column(column):
        previous = getattr(tree, '_grid_user_sort', None)
        order = (Qt.SortOrder.DescendingOrder if previous == (column, Qt.SortOrder.AscendingOrder)
                 else Qt.SortOrder.AscendingOrder)
        tree._grid_user_sort = (column, order)
        tree.setSortingEnabled(True)
        tree.sortByColumn(column, order)
        header.setSortIndicatorShown(True)

    header.sectionClicked.connect(sort_column)
