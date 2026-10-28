"""Activity history with one live timing line per OCCS operation."""
from pathlib import Path
from collections import deque
import json
from atool_core.activity_output import activity_text, HTTP_TRACE_PREFIX, sanitized_http_value

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QTextCursor
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QPlainTextEdit
from .activity_file import ActivityFile, utf8_tail

MAX_ACTIVITY_BLOCKS = 10000


def recent_lines(text):
    lines = text.rsplit('\n', MAX_ACTIVITY_BLOCKS - 1)
    lines[0] = lines[0].rsplit('\n', 1)[-1]
    return '\n'.join(lines)


def duration_text(seconds):
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


class ActivityLog(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setMinimumHeight(55)
        self.operations = {}
        self.file_operations = {}
        self.output_buffers = {}
        self.discard_output = set()
        self.debug_jobs = set()
        self.discovery_reads = {}
        self.operation_number = 0
        self.backlog_bytes = 1024 * 1024
        self.pending = deque()
        self.pending_bytes = self.text_bytes = 0
        self.file_log = None
        self.file_config = None
        self.log_warning_shown = False
        self.batch_timer = QTimer(self)
        self.batch_timer.setSingleShot(True)
        self.batch_timer.setInterval(100)
        self.batch_timer.timeout.connect(self.flush_pending)
        self.file_status_timer = QTimer(self)
        self.file_status_timer.setInterval(1000)
        self.file_status_timer.timeout.connect(self.flush_pending)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh_operations)
        self.menu_actions = {}
        for key, title, callback in (
                ('copy', 'Copy', self.copy),
                ('copy_all', 'Copy All Activity', lambda: QApplication.clipboard().setText(self.toPlainText())),
                ('select_all', 'Select All', self.selectAll),
                ('open_log', 'Open Current Log', self.open_current_log),
                ('show_folder', 'Show Log Folder', self.show_log_folder),
                ('save', 'Save Activity…', self.save_contents), ('clear', 'Clear Activity', self.clear)):
            action = QAction(title, self)
            action.triggered.connect(callback)
            self.menu_actions[key] = action

    def populate_menu(self, menu):
        for key in ('copy', 'copy_all', 'select_all', None, 'open_log', 'show_folder', None, 'save', 'clear'):
            menu.addSeparator() if key is None else menu.addAction(self.menu_actions[key])
        menu.aboutToShow.connect(self.update_menu_actions)
        self.update_menu_actions()

    def update_menu_actions(self):
        self.flush_pending()
        has_text = not self.document().isEmpty()
        self.menu_actions['copy'].setEnabled(self.textCursor().hasSelection())
        for key in ('copy_all', 'select_all', 'save', 'clear'):
            self.menu_actions[key].setEnabled(has_text)
        for key in ('open_log', 'show_folder'):
            self.menu_actions[key].setEnabled(self.file_log is not None)

    def open_current_log(self):
        self.open_log_location(folder=False)

    def show_log_folder(self):
        self.open_log_location(folder=True)

    def open_log_location(self, *, folder):
        title = 'Show Log Folder' if folder else 'Open Current Log'
        try:
            self.flush_pending()
            sink = self.file_log
            if sink is None:
                raise OSError('Activity file logging is not configured.')
            if not folder and not sink.path.exists():
                sink.append('Activity log opened.')
            if not sink.flush():
                raise OSError('The log file is still being written. Try again shortly.')
            error = sink.take_error() or sink.write_error()
            if error:
                raise OSError(error)
            target = sink.path.parent if folder else sink.path
            if folder:
                target.mkdir(parents=True, exist_ok=True)
            elif not target.is_file():
                raise OSError('The current log file could not be created.')
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve()))):
                raise OSError('No application could open this location.')
        except OSError as error:
            QMessageBox.warning(self, title, activity_text(str(error)))

    def configure(self, diagnostics, default_directory=None):
        def integer(key, default, minimum=1):
            try:
                return max(minimum, int(diagnostics.get(key, default)))
            except (ValueError, TypeError):
                return default
        self.backlog_bytes = integer('activity_backlog_kib', 1024) * 1024
        directory = Path(diagnostics.get('log_directory') or default_directory or Path.home() / '.atool' / 'logs').expanduser()
        config = (directory, integer('log_file_max_mib', 10) * 1024 * 1024,
                  integer('log_backup_count', 5))
        if config != self.file_config:
            if self.file_log:
                self.file_log.close()
            self.file_log = ActivityFile(*config)
            self.file_config = config
            self.log_warning_shown = False
        self.file_status_timer.start()
        self.flush_pending()
        self.trim_backlog()
        self.update_menu_actions()

    def appendPlainText(self, text):
        self.append_entry(activity_text(str(text)))

    def append_entry(self, text, summary=None):
        if self.file_log:
            self.file_log.append(text)
            if summary is not None:
                text = summary
            elif len(text) > 8192:
                text = text[:2048] + '\n[Full sanitized details saved to the Activity log file]'
        self.queue_display(text)

    def queue_display(self, text):
        text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\u2028', '\n').replace('\u2029', '\n')
        if not text:
            return
        text = utf8_tail(text, self.backlog_bytes - 1)
        text = recent_lines(text)
        size = len(text.encode('utf-8')) + 1
        while self.pending and (self.pending_bytes + size > self.backlog_bytes or len(self.pending) >= 4096):
            self.pending_bytes -= len(self.pending.popleft().encode('utf-8')) + 1
        self.pending.append(text)
        self.pending_bytes += size
        if not self.batch_timer.isActive():
            self.batch_timer.start()

    def flush_pending(self):
        self.batch_timer.stop()
        if self.file_log and not self.log_warning_shown:
            error = self.file_log.take_error()
            if error:
                self.log_warning_shown = True
                self.queue_display(activity_text('Activity file logging failed: ' + error))
        if self.pending:
            text = recent_lines('\n'.join(self.pending))
            self.pending.clear()
            self.pending_bytes = 0
            separator = 0 if self.document().isEmpty() else 1
            super().appendPlainText(text)
            self.text_bytes += len(text.encode('utf-8')) + separator
            self.trim_backlog()

    def trim_backlog(self):
        block = self.document().firstBlock()
        blocks = self.document().blockCount()
        removed_bytes = 0
        end = 0
        while (self.text_bytes - removed_bytes > self.backlog_bytes or blocks > MAX_ACTIVITY_BLOCKS) and block.next().isValid():
            removed_bytes += len(block.text().encode('utf-8')) + 1
            block = block.next()
            end = block.position()
            blocks -= 1
        if self.text_bytes - removed_bytes > self.backlog_bytes:
            text = block.text()
            tail = utf8_tail(text, self.backlog_bytes)
            prefix = text[:len(text) - len(tail)]
            end += len(prefix.encode('utf-16-le')) // 2
            removed_bytes += len(prefix.encode('utf-8'))
        if end:
            cursor = QTextCursor(self.document())
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            self.text_bytes -= removed_bytes

    def toPlainText(self):
        self.flush_pending()
        return super().toPlainText()

    def shutdown(self):
        self.file_status_timer.stop()
        self.flush_pending()
        if self.file_log:
            self.file_log.close()
            self.file_log = None
            self.file_config = None
        self.batch_timer.stop()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        self.populate_menu(menu)
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()

    def clear(self):
        # Old timing blocks must not overwrite new messages after a clear.
        self.operations.clear()
        self.output_buffers.clear()
        self.discard_output.clear()
        self.debug_jobs.clear()
        self.discovery_reads.clear()
        self.timer.stop()
        self.pending.clear()
        self.pending_bytes = self.text_bytes = 0
        self.batch_timer.stop()
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
        self.flush_pending()
        self.operations[job] = (self.document().lastBlock(), label)
        debug = bool(job.settings.payload.get('diagnostics', {}).get('debug_logging'))
        self.file_operations[job] = (label, debug)
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
        if '--json' in job.args:
            return
        pending = self.output_buffers[job] + chunk
        lines = pending.replace('\r', '\n').split('\n')
        tail = '' if flush else lines.pop()
        if job in self.discard_output:
            if lines:
                lines[0] = '[Oversized output line omitted]'
                self.discard_output.discard(job)
            else:
                tail = ''
        if len(tail.encode('utf-8')) > 65536:
            tail = ''
            self.discard_output.add(job)
        self.output_buffers[job] = tail
        label = self.operations[job][1]
        for line in lines:
            if line.startswith(HTTP_TRACE_PREFIX):
                self.append_http_trace(job, line)
                continue
            if len(line.encode('utf-8')) > 65536:
                line = '[Oversized output line omitted]'
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
        file_only = job not in self.operations and self.file_log and self.file_operations.get(job, ('', False))[1]
        if not file_only and (job not in self.operations or job not in self.debug_jobs):
            return
        label = self.file_operations[job][0]
        try:
            event = json.loads(line[len(HTTP_TRACE_PREFIX):])
            # Email routing discovery is background work, not the send payload.
            # Also keep older CLI builds from flooding Activity with master records.
            if '--send-email' in job.args and event.get('method') == 'GET':
                if not file_only and event.get('type') == 'request':
                    self.discovery_reads[job] = self.discovery_reads.get(job, 0) + 1
                return
            self.flush_discovery_summary(job)
            event = sanitized_http_value(event)
            kind = 'HTTP ' + str(event.get('type', 'diagnostic')).title()
            full = f'{label} · {kind}\n' + json.dumps(event, ensure_ascii=False, indent=2)
            if file_only:
                self.file_log.append(full)
                return
            details = [str(event[key]) for key in ('method', 'url', 'status') if key in event]
            if 'durationMs' in event:
                details.append(f'{event["durationMs"]} ms')
            summary = f'{label} · {kind} · ' + ' · '.join(details)
            self.append_entry(full, summary=summary.strip())
        except (ValueError, AttributeError, RecursionError):
            message = f'{label} · Invalid HTTP diagnostic record (content omitted).'
            if file_only:
                self.file_log.append(message)
            else:
                self.appendPlainText(message)

    def flush_discovery_summary(self, job):
        count = self.discovery_reads.pop(job, 0)
        if count and job in self.operations:
            label = self.operations[job][1]
            self.appendPlainText(f'{label} · Routing lookup: {count} configuration reads.')

    def replace_line(self, job, text):
        self.flush_pending()
        block, label = self.operations[job]
        if not block.isValid() or not block.text().startswith(label + ' ·'):
            return False
        scrollbar = self.verticalScrollBar()
        position = scrollbar.value()
        at_bottom = position == scrollbar.maximum()
        cursor = QTextCursor(block)
        old_bytes = len(block.text().encode('utf-8'))
        cursor.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.text_bytes += len(text.encode('utf-8')) - old_bytes
        self.trim_backlog()
        scrollbar.setValue(scrollbar.maximum() if at_bottom else position)
        return True

    def refresh_operations(self):
        for job, (_, label) in self.operations.items():
            if job.started_at is not None:
                self.replace_line(job, f'{label} · Running · Elapsed {duration_text(job.elapsed_seconds)}')

    def finish_operation(self, job, result):
        tracked = self.file_operations.get(job)
        if job not in self.operations:
            self.file_operations.pop(job, None)
            if tracked and self.file_log:
                label = tracked[0]
                status = ('Cancelled' if result.cancelled else 'Timed out' if result.timed_out
                          else 'Completed' if result.successful else 'Failed')
                self.file_log.append(f'{label} · {status} · Total {duration_text(job.elapsed_seconds)}')
                if not result.successful and not result.cancelled:
                    self.file_log.append(activity_text(result.message) if job.args[:1] != ['login'] else 'Comms login failed.')
            return
        _, label = self.operations[job]
        status = ('Cancelled' if result.cancelled else 'Timed out' if result.timed_out
                  else 'Completed' if result.successful else 'Failed')
        final = f'{label} · {status} · Total {duration_text(job.elapsed_seconds)}'
        if self.file_log:
            self.file_log.append(final)
        if not self.replace_line(job, final):
            self.queue_display(final)
        self.append_output(job, '', flush=True)
        self.flush_discovery_summary(job)
        self.output_buffers.pop(job, None)
        self.discard_output.discard(job)
        self.debug_jobs.discard(job)
        if not result.successful and not result.cancelled:
            detail = activity_text(result.message) if job.args[:1] != ['login'] else 'Comms login failed.'
            self.appendPlainText(f'{label} · Exit status {result.code}\n{detail}')
        del self.operations[job]
        self.file_operations.pop(job, None)
        if not self.operations:
            self.timer.stop()
