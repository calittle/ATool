"""Activity history with one live timing line per OCCS operation."""
from pathlib import Path
import json
from atool_core.activity_output import activity_text, HTTP_TRACE_PREFIX, sanitized_http_value

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPlainTextEdit


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
        self.output_buffers = {}
        self.debug_jobs = set()
        self.discovery_reads = {}
        self.operation_number = 0
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh_operations)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        clear_action = menu.addAction('Clear Activity', self.clear)
        save_action = menu.addAction('Save Activity…', self.save_contents)
        clear_action.setEnabled(not self.document().isEmpty())
        save_action.setEnabled(not self.document().isEmpty())
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()

    def clear(self):
        # Old timing blocks must not overwrite new messages after a clear.
        self.operations.clear()
        self.output_buffers.clear()
        self.debug_jobs.clear()
        self.discovery_reads.clear()
        self.timer.stop()
        super().clear()

    def save_contents(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save Activity', 'activity.log', 'Log Files (*.log);;Text Files (*.txt);;All Files (*)')
        if not path:
            return
        try:
            Path(path).write_text(self.toPlainText(), encoding='utf-8')
        except OSError as error:
            QMessageBox.warning(self, 'Save Activity', f'Could not save the activity log.\n\n{error}')

    def track_operation(self, job):
        self.operation_number += 1
        # Show command verbs only; CLI arguments can contain credentials or data.
        verbs = []
        for argument in job.args[:2]:
            if str(argument).startswith('-'):
                break
            verbs.append(str(argument))
        label = f'OCCS #{self.operation_number} · {" ".join(verbs) or "operation"}'
        if '--send-email' in job.args:
            label = f'OCCS #{self.operation_number} · Send Email'
        self.appendPlainText(f'{label} · Queued')
        self.operations[job] = (self.document().lastBlock(), label)
        debug = bool(job.settings.payload.get('diagnostics', {}).get('debug_logging'))
        if debug and job.args[:1] != ['login']:
            self.debug_jobs.add(job)
            self.log_request(job, label)
            job.http_trace.connect(lambda line: self.append_http_trace(job, line))
        if (debug or '--send-email' in job.args) and job.args[:1] != ['login']:
            self.output_buffers[job] = ''
            job.output.connect(lambda chunk: self.append_output(job, chunk))
        job.completed.connect(lambda result: self.finish_operation(job, result))
        self.timer.start()

    def log_request(self, job, label):
        fields = []
        for flag, name in (('--session', 'Session'), ('--package', 'Package'), ('--render-type', 'Render'),
                           ('--email-config-uuid', 'Email UUID'), ('--recipient', 'Recipients'),
                           ('--communication-config-uuid', 'Communication UUID'),
                           ('--communication-transaction-type', 'Transaction type'),
                           ('--communication-user-defined-transaction-type', 'Transaction'),
                           ('--input', 'Input'), ('--output', 'Output'), ('--timeout', 'Timeout ms')):
            try:
                fields.append(f'{name}: {job.args[job.args.index(flag) + 1]}')
            except (ValueError, IndexError):
                if flag == '--session':
                    fields.append('Session: ' + str(job.settings.get('session_alias') or 'OCCS default'))
        fields.insert(0, 'CLI: ' + job.settings.cli)
        self.appendPlainText(activity_text(f'{label} · Request\n' + '\n'.join(fields)))

    def append_output(self, job, chunk, *, flush=False):
        if job not in self.operations or job not in self.output_buffers:
            return
        pending = self.output_buffers[job] + chunk
        lines = pending.replace('\r', '\n').split('\n')
        self.output_buffers[job] = '' if flush else lines.pop()
        label = self.operations[job][1]
        for line in lines:
            if line.startswith(HTTP_TRACE_PREFIX):
                self.append_http_trace(job, line)
                continue
            if '--json' in job.args:
                continue
            text = activity_text(line)
            # Machine-readable results may contain entire documents or payloads.
            # Keep those in the operation result rather than copying them to Activity.
            try:
                structured = isinstance(json.loads(line), (dict, list))
            except ValueError:
                structured = False
            if text and not structured:
                self.appendPlainText(f'{label} · {text}')

    def append_http_trace(self, job, line):
        if job not in self.operations or job not in self.debug_jobs:
            return
        label = self.operations[job][1]
        try:
            event = json.loads(line[len(HTTP_TRACE_PREFIX):])
            # Email routing discovery is background work, not the send payload.
            # Also keep older CLI builds from flooding Activity with master records.
            if '--send-email' in job.args and event.get('method') == 'GET':
                if event.get('type') == 'request':
                    self.discovery_reads[job] = self.discovery_reads.get(job, 0) + 1
                return
            self.flush_discovery_summary(job)
            event = sanitized_http_value(event)
            kind = 'HTTP ' + str(event.get('type', 'diagnostic')).title()
            self.appendPlainText(f'{label} · {kind}\n' + json.dumps(event, ensure_ascii=False, indent=2))
        except (ValueError, AttributeError, RecursionError):
            self.appendPlainText(f'{label} · Invalid HTTP diagnostic record (content omitted).')

    def flush_discovery_summary(self, job):
        count = self.discovery_reads.pop(job, 0)
        if count and job in self.operations:
            label = self.operations[job][1]
            self.appendPlainText(f'{label} · Routing lookup: {count} configuration reads.')

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
        if job not in self.operations:
            return
        _, label = self.operations[job]
        status = ('Cancelled' if result.cancelled else 'Timed out' if result.timed_out
                  else 'Completed' if result.successful else 'Failed')
        self.replace_line(job, f'{label} · {status} · Total {duration_text(job.elapsed_seconds)}')
        self.append_output(job, '', flush=True)
        self.flush_discovery_summary(job)
        self.output_buffers.pop(job, None)
        self.debug_jobs.discard(job)
        if not result.successful and not result.cancelled:
            detail = activity_text(result.message) if job.args[:1] != ['login'] else 'Comms login failed.'
            self.appendPlainText(f'{label} · Exit status {result.code}\n{detail}')
        del self.operations[job]
        if not self.operations:
            self.timer.stop()
