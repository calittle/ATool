"""Asynchronous OCCS CLI transport, using the original application's contracts."""
from __future__ import annotations

import json
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class CommsSettings:
    def __init__(self, path=None):
        self.path = Path(path or Path.home() / '.atool' / '.settings.json')
        self.payload = {}
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                raise ValueError('User settings must be a JSON object.')
            self.payload = value

    def get(self, key, default=None):
        settings = self.payload.get('occs', {})
        return settings.get(key, default) if isinstance(settings, dict) else default

    @property
    def cli(self):
        sibling = Path(__file__).resolve().parents[2] / 'ccs-tools' / 'OCCS-CLI' / 'bin' / 'occs.js'
        return str(Path(self.get('cli_path') or (sibling if sibling.exists() else 'occs')).expanduser())

    @property
    def timeout_ms(self):
        try:
            return max(1000, int(float(self.get('request_timeout_seconds', 360)) * 1000))
        except (TypeError, ValueError):
            return 360000

    def command(self, args):
        args = [str(arg) for arg in args]
        alias = str(self.get('session_alias', '') or '').strip()
        if args and alias and '--session' not in args and args[0] in {'package', 'content', 'preview', 'convertxml', 'list-configs', 'create-config'}:
            args = [args[0], '--session', alias, *args[1:]]
        return ['node', self.cli, *args] if self.cli.endswith('.js') else [self.cli, *args]

    @property
    def cwd(self):
        path = Path(self.cli)
        if not path.exists():
            return None
        return str(path.parent.parent if path.parent.name == 'bin' else path.parent)


@dataclass
class CommandResult:
    code: int
    stdout: str
    stderr: str
    value: dict | None
    cancelled: bool = False
    timed_out: bool = False

    @property
    def successful(self):
        return self.code == 0 and not self.cancelled and not self.timed_out and not (self.value and (self.value.get('success') is False or self.value.get('ok') is False))

    @property
    def message(self):
        if self.cancelled:
            return 'Cancelled.'
        if self.timed_out:
            return 'The Comms request timed out.'
        if self.value:
            error = self.value.get('error')
            if isinstance(error, dict) and error.get('message'):
                message = str(error['message'])
                details = error.get('details')
                if isinstance(details, dict):
                    message += '\n' + '\n'.join(f'{key}: {value}' for key, value in details.items())
                return message
            if self.value.get('message'):
                return str(self.value['message'])
        return self.stderr.strip() or f'OCCS CLI exited with status {self.code}.'


class CommandJob(QObject):
    completed = Signal(object)
    output = Signal(str)

    def __init__(self, settings, args, parent=None, timeout_ms=None):
        super().__init__(parent)
        self.settings, self.args = settings, args
        self.process = QProcess(self)
        if os.name != 'nt':
            parameters = QProcess.UnixProcessParameters()
            parameters.flags = QProcess.UnixProcessFlag.CreateNewSession
            self.process.setUnixProcessParameters(parameters)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timeout_ms = timeout_ms or settings.timeout_ms + 30000
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.cancelled = self.timed_out = self.done = False
        self.phase = 'original'
        self.login_attempted = self.read_retried = False
        self.login_alias = None
        self.original_failure = None
        self.service = parent
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.finish)
        self.process.errorOccurred.connect(self.process_error)
        self.timer.timeout.connect(self.timeout)

    def start(self):
        self.start_command(self.args)

    def start_command(self, args, timeout_ms=None):
        if self.done:
            return
        if self.cancelled:
            self.finish(-1)
            return
        self.stdout.clear()
        self.stderr.clear()
        command = self.settings.command(args)
        if self.settings.cwd:
            self.process.setWorkingDirectory(self.settings.cwd)
        self.process.start(command[0], command[1:])
        self.process.closeWriteChannel()
        self.timer.start(timeout_ms or self.timeout_ms)

    def read_stdout(self):
        if not self.process.isOpen():
            return
        chunk = bytes(self.process.readAllStandardOutput())
        self.stdout.extend(chunk)
        if self.phase == 'original' and self.args[:1] != ['login']:
            self.output.emit(chunk.decode('utf-8', errors='replace'))

    def read_stderr(self):
        if not self.process.isOpen():
            return
        chunk = bytes(self.process.readAllStandardError())
        self.stderr.extend(chunk)
        if self.phase == 'original' and self.args[:1] != ['login']:
            self.output.emit(chunk.decode('utf-8', errors='replace'))

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.stderr.extend(self.process.errorString().encode())
            self.finish(-1)

    def timeout(self):
        self.timed_out = True
        self.stop_process()

    def cancel(self):
        self.cancelled = True
        self.stop_process()

    def stop_process(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.finish(-1)
        else:
            if os.name != 'nt' and self.process.processId():
                try:
                    os.killpg(int(self.process.processId()), signal.SIGKILL)
                except ProcessLookupError:
                    self.process.kill()
            else:
                self.process.kill()
            QTimer.singleShot(1000, self.kill_if_running)

    def kill_if_running(self):
        if not self.done and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def finish(self, code, *_):
        if self.done:
            return
        self.timer.stop()
        self.read_stdout()
        self.read_stderr()
        stdout = self.stdout.decode('utf-8', errors='replace')
        stderr = self.stderr.decode('utf-8', errors='replace')
        try:
            value = json.loads(stdout)
        except ValueError:
            value = None
        if not isinstance(value, dict):
            value = None
        result = CommandResult(code, stdout, stderr, value, self.cancelled, self.timed_out)
        if self.phase == 'login':
            self.service.release_login(self)
            if result.successful:
                self.phase = 'original'
                QTimer.singleShot(0, self.start)
                return
            if not result.cancelled and not result.timed_out:
                result = CommandResult(-1, '', self.original_failure.message + '\n\nAutomatic login failed: ' + result.message, None)
        elif not result.successful and not self.cancelled and not self.timed_out:
            if not self.login_attempted and self.args[:1] != ['login'] and unauthorized_error(result.message):
                self.login_attempted = True
                self.original_failure = result
                try:
                    self.login_alias = str(self.args[self.args.index('--session') + 1])
                except (ValueError, IndexError):
                    self.login_alias = str(self.settings.get('session_alias') or '')
                self.phase = 'login_wait'
                self.output.emit('Session expired. Refreshing Comms login…\n')
                self.service.acquire_login(self)
                return
            if getattr(self, 'channel', '') == 'read' and not self.read_retried and transient_error(result.message):
                self.read_retried = True
                QTimer.singleShot(2000, self.start)
                return
        self.done = True
        self.completed.emit(result)

    def start_login(self):
        from .configuration import login_args
        self.phase = 'login'
        self.start_command(login_args(self.login_alias), self.settings.timeout_ms)


def unauthorized_error(message):
    normalized = message.casefold()
    if '401' in normalized and any(marker in normalized for marker in ('unauthorized', 'authorization required', 'status code 401', 'status: 401')):
        return True
    return 'unauthorized' in normalized and any(marker in normalized for marker in ('token may have expired', 'session may have expired', 'occs login', 'please log in again'))


def transient_error(message):
    return any(marker in message.casefold() for marker in ('etimedout', 'econnreset', 'econnrefused', 'eai_again', 'socket hang up'))


class CommsService(QObject):
    """Bounded command queue; job-specific and all-job cancellation."""
    changed = Signal()

    def __init__(self, settings=None, parent=None, concurrency=4):
        super().__init__(parent)
        self.settings = settings or CommsSettings()
        self.concurrency = concurrency
        self.channel_limits = {'regular': concurrency, 'read': 4, 'resources': 4, 'download_all': 1, 'preview': 1}
        self.active, self.pending = [], []
        self.logins = {}
        self.login_waiters = {}

    def submit(self, args, callback=None, timeout_ms=None, *, channel='regular', exclusive_key=None):
        if channel not in self.channel_limits:
            raise ValueError('Unknown Comms operation channel.')
        job = CommandJob(self.settings, args, self, timeout_ms)
        job.channel = channel
        job.exclusive_key = exclusive_key or self.operation_key(args)
        if callback:
            job.completed.connect(callback)
        job.completed.connect(lambda result: self.finished(job))
        self.pending.append(job)
        logging.getLogger('atool_qt').debug('Comms operation queued: %s (%s)', str(args[0]) if args else '(empty)', channel)
        QTimer.singleShot(0, self.drain)
        self.changed.emit()
        return job

    def drain(self):
        while self.pending:
            job = next((candidate for candidate in self.pending if
                        sum(active.channel == candidate.channel for active in self.active) < self.channel_limits[candidate.channel] and
                        (not candidate.exclusive_key or all(active.exclusive_key != candidate.exclusive_key for active in self.active))), None)
            if job is None:
                break
            self.pending.remove(job)
            self.active.append(job)
            job.start()
        self.changed.emit()

    @staticmethod
    def operation_key(args):
        args = [str(arg) for arg in args]
        def option(name):
            try:
                return args[args.index(name) + 1].strip().casefold()
            except (ValueError, IndexError):
                return ''
        config = option('--config-id')
        if config and ((args[:1] == ['package'] and 'save' in args) or args[:1] in (['content'], ['close-config'])):
            return 'config:' + config
        if args[:1] == ['migrate']:
            return 'migration:' + option('--source-session') + ':' + option('--target-session')
        return None

    def finished(self, job):
        logging.getLogger('atool_qt').debug('Comms operation finished: %s (%s)', str(job.args[0]) if job.args else '(empty)', job.channel)
        self.release_login(job)
        if job in self.active:
            self.active.remove(job)
        if job in self.pending:
            self.pending.remove(job)
        QTimer.singleShot(0, self.drain)
        self.changed.emit()

    def acquire_login(self, job):
        alias = job.login_alias
        if alias in self.logins:
            self.login_waiters.setdefault(alias, []).append(job)
        else:
            self.logins[alias] = job
            QTimer.singleShot(0, job.start_login)

    def release_login(self, job):
        alias = job.login_alias
        waiters = self.login_waiters.get(alias, [])
        if job in waiters:
            waiters.remove(job)
        if self.logins.get(alias) is job:
            self.logins.pop(alias)
            next_job = next((candidate for candidate in waiters if not candidate.done and not candidate.cancelled), None)
            if next_job:
                waiters.remove(next_job)
                self.logins[alias] = next_job
                QTimer.singleShot(0, next_job.start_login)

    def cancel_all(self):
        for job in list(self.pending) + list(self.active):
            job.cancel()

    def shutdown(self):
        self.cancel_all()
        for job in list(self.active):
            if not job.process.waitForFinished(1000):
                job.process.kill()
                job.process.waitForFinished(1000)
