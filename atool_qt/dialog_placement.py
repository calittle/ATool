"""Keep workspace dialogs reachable when their parent extends beyond a screen."""
from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog


def dialog_position(parent, size, screens):
    def overlap(screen):
        visible = screen.intersected(parent)
        return visible.width() * visible.height() if not visible.isEmpty() else 0

    def distance(screen):
        centre = parent.center()
        x = max(screen.left(), min(centre.x(), screen.right()))
        y = max(screen.top(), min(centre.y(), screen.bottom()))
        return (centre.x() - x) ** 2 + (centre.y() - y) ** 2

    screen = max(screens, key=lambda rect: (overlap(rect), -distance(rect)))
    # Leave room for the title bar and window borders.
    available = screen.adjusted(12, 32, -12, -12)
    x = parent.center().x() - size.width() // 2
    y = parent.center().y() - size.height() // 2
    return QPoint(max(available.left(), min(x, available.right() - size.width() + 1)),
                  max(available.top(), min(y, available.bottom() - size.height() + 1)))


class DialogPlacement(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Polish and isinstance(watched, QDialog):
            owner = watched.parentWidget()
            while owner is not None and owner.objectName() != 'atool-qt-workspace':
                owner = owner.parentWidget()
            if owner is None:
                return False
            screens = [screen.availableGeometry() for screen in QGuiApplication.screens()]
            if screens:
                parent = watched.parentWidget().window()
                size = watched.size().expandedTo(watched.sizeHint())
                watched.move(dialog_position(parent.frameGeometry(), size, screens))
        return False
