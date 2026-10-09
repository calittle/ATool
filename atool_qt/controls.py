"""Manager buttons wrap with their panel instead of disappearing into overflow."""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLayout, QToolButton, QWidget


class ButtonFlow(QLayout):
    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(4)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QRect(0, 0, width, 0), False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, True)

    def arrange(self, rect, apply):
        x, y, height = rect.x(), rect.y(), 0
        for item in self.items:
            if item.widget().isHidden():
                continue
            size = item.sizeHint()
            if x > rect.x() and x + size.width() > rect.right() + 1:
                x, y, height = rect.x(), y + height + self.spacing(), 0
            if apply:
                item.setGeometry(QRect(x, y, size.width(), size.height()))
            x += size.width() + self.spacing()
            height = max(height, size.height())
        return y - rect.y() + height

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def sizeHint(self):
        return self.minimumSize()


class ActionButtonGroup(QWidget):
    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action

    def defaultAction(self):
        return self.action


class ManagerButtons(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.flow = ButtonFlow(self)
        self.buttons = {}

    def setMovable(self, _):
        pass

    def addAction(self, action):
        super().addAction(action)
        button = QToolButton(self)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setDefaultAction(action)
        button.setAutoRaise(False)
        self.flow.addWidget(button)
        self.buttons[action] = button
        action.changed.connect(self.flow.invalidate)
        return action

    def addActionGroup(self, actions):
        group = ActionButtonGroup(actions[0], self)
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(self.flow.spacing())
        for action in actions:
            super().addAction(action)
            button = QToolButton(group)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setDefaultAction(action)
            button.setAutoRaise(False)
            row.addWidget(button)
            self.buttons[action] = button
            action.changed.connect(self.flow.invalidate)
        self.flow.addWidget(group)
        self.setMinimumWidth(max(self.minimumWidth(), group.sizeHint().width()))

    def reorder(self, titles):
        order = {title: index for index, title in enumerate(titles)}
        self.flow.items.sort(key=lambda item: order.get(item.widget().defaultAction().text(), len(order)))
        self.flow.invalidate()

    def widgetForAction(self, action):
        return self.buttons.get(action)

    def addActions(self, actions):
        for action in actions:
            self.addAction(action)
