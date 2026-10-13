"""Clause-name completion for the condition composer."""
from __future__ import annotations

from PySide6.QtCore import Qt, QStringListModel
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QCompleter, QPlainTextEdit
from .clause_usage import clause_token


class ClauseComposeEdit(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.names = []
        self.completion_model = QStringListModel(self)
        self.completer = QCompleter(self.completion_model, self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.activated[str].connect(self.insert_completion)

    def set_clauses(self, entries):
        self.names = sorted({entry['name'] for entry in entries if entry.get('name')}, key=str.casefold)
        self.completer.popup().hide()

    def token_bounds(self):
        text, position = self.toPlainText(), self.textCursor().position()
        start = end = position
        def token_char(char):
            return char.isalnum() or char in '_-'
        while start and token_char(text[start - 1]):
            start -= 1
        while end < len(text) and token_char(text[end]):
            end += 1
        return start, end, text[start:position]

    def insert_completion(self, name):
        start, end, _ = self.token_bounds()
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(clause_token(name))
        self.setTextCursor(cursor)
        self.completer.popup().hide()

    def show_completions(self):
        _, _, prefix = self.token_bounds()
        if not prefix:
            self.completer.popup().hide()
            return
        starts = [name for name in self.names if name.casefold().startswith(prefix.casefold())]
        matches = starts or [name for name in self.names if prefix.casefold() in name.casefold()]
        self.completion_model.setStringList(matches[:20])
        # The model already contains the original's starts-with/contains matches.
        self.completer.setCompletionPrefix('')
        if matches:
            rectangle = self.cursorRect()
            rectangle.setWidth(max(220, self.completer.popup().sizeHintForColumn(0) + 30))
            self.completer.complete(rectangle)
            self.completer.popup().setCurrentIndex(self.completer.completionModel().index(0, 0))
        else:
            self.completer.popup().hide()

    def keyPressEvent(self, event):
        popup = self.completer.popup()
        if popup.isVisible():
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab):
                name = popup.currentIndex().data()
                if name:
                    self.insert_completion(name)
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
                popup.hide()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                model = self.completer.completionModel()
                step = 1 if event.key() == Qt.Key.Key_Down else -1
                row = max(0, min(model.rowCount() - 1, popup.currentIndex().row() + step))
                popup.setCurrentIndex(model.index(row, 0))
                event.accept()
                return
        if event.key() == Qt.Key.Key_Space and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.show_completions()
            return
        super().keyPressEvent(event)
        if event.text() and (event.text().isalnum() or event.text() in '_-'):
            self.show_completions()
        else:
            self.completer.popup().hide()
