"""Activity history with one live timing line per OCCS operation."""
from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit


def duration_text(seconds):
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


class ActivityLog(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMinimumHeight(55)
        self.operations = {}
        self.operation_number = 0
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh_operations)

    def track_operation(self, job):
        self.operation_number += 1
        # Show command verbs only; CLI arguments can contain credentials or data.
        verbs = []
        for argument in job.args[:2]:
            if str(argument).startswith('-'):
                break
            verbs.append(str(argument))
        label = f'OCCS #{self.operation_number} · {" ".join(verbs) or "operation"}'
        self.appendPlainText(f'{label} · Queued')
        self.operations[job] = (self.document().lastBlock(), label)
        job.completed.connect(lambda result: self.finish_operation(job, result))
        self.timer.start()

    def replace_line(self, job, text):
        block, _ = self.operations[job]
        if not block.isValid():
            return
        scrollbar = self.verticalScrollBar()
        position = scrollbar.value()
        at_bottom = position == scrollbar.maximum()
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        scrollbar.setValue(scrollbar.maximum() if at_bottom else position)

    def refresh_operations(self):
        for job, (_, label) in self.operations.items():
            if job.started_at is not None:
                self.replace_line(job, f'{label} · Running · Elapsed {duration_text(job.elapsed_seconds)}')

    def finish_operation(self, job, result):
        _, label = self.operations[job]
        status = ('Cancelled' if result.cancelled else 'Timed out' if result.timed_out
                  else 'Completed' if result.successful else 'Failed')
        self.replace_line(job, f'{label} · {status} · Total {duration_text(job.elapsed_seconds)}')
        del self.operations[job]
        if not self.operations:
            self.timer.stop()
