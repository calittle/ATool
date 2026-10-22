"""Bounded background writes and size-based rotation for sanitized Activity logs."""
from collections import deque
from datetime import datetime
from pathlib import Path
import threading
import time

from PySide6.QtCore import QLockFile


def utf8_tail(text, limit):
    return text.encode('utf-8')[-limit:].decode('utf-8', errors='ignore')


class ActivityFile:
    def __init__(self, directory, max_bytes, backups, queue_bytes=1024 * 1024):
        self.path = Path(directory) / 'atool.log'
        self.max_bytes, self.backups = max_bytes, backups
        self.queue_limit = queue_bytes
        self.queue = deque()
        self.pending_bytes = 0
        self.dropped = 0
        self.error = ''
        self.last_error = ''
        self.condition = threading.Condition()
        self.stopping = self.busy = False
        self.thread = threading.Thread(target=self._run, name='ATool log writer', daemon=True)
        self.thread.start()

    def append(self, text):
        stamp = datetime.now().astimezone().isoformat(timespec='milliseconds')
        record = f'{stamp} {text}\n'.encode('utf-8')
        limit = min(self.max_bytes, self.queue_limit)
        if len(record) > limit:
            marker = b'\n[Log entry truncated to the configured size limit]\n'
            record = record[:max(0, limit - len(marker))].decode('utf-8', errors='ignore').encode('utf-8') + marker
        with self.condition:
            if self.stopping:
                return
            while self.queue and self.pending_bytes + len(record) > self.queue_limit:
                self.pending_bytes -= len(self.queue.popleft())
                self.dropped += 1
            self.queue.append(record)
            self.pending_bytes += len(record)
            self.condition.notify()

    def _write(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Separate application processes share the same bounded log set safely.
        lock = QLockFile(str(self.path) + '.lock')
        if not lock.tryLock(1000):
            raise OSError('The Activity log is busy in another application.')
        try:
            for candidate in self.path.parent.glob(self.path.name + '.*'):
                suffix = candidate.name[len(self.path.name) + 1:]
                if suffix.isdigit() and int(suffix) > self.backups:
                    candidate.unlink(missing_ok=True)
            size = self.path.stat().st_size if self.path.exists() else 0
            stream = None
            try:
                for record in records:
                    if size and size + len(record) > self.max_bytes:
                        if stream:
                            stream.close()
                            stream = None
                        self.path.with_name(self.path.name + f'.{self.backups}').unlink(missing_ok=True)
                        for number in range(self.backups - 1, 0, -1):
                            previous = self.path.with_name(self.path.name + f'.{number}')
                            if previous.exists():
                                previous.replace(self.path.with_name(self.path.name + f'.{number + 1}'))
                        self.path.replace(self.path.with_name(self.path.name + '.1'))
                        size = 0
                    if stream is None:
                        stream = self.path.open('ab')
                    stream.write(record)
                    size += len(record)
            finally:
                if stream:
                    stream.close()
        finally:
            lock.unlock()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.queue or self.stopping)
                if not self.queue and self.stopping:
                    return
                # Coalesce bursts before touching the filesystem.
                deadline = time.monotonic() + 0.05
                while not self.stopping and (remaining := deadline - time.monotonic()) > 0:
                    self.condition.wait(timeout=remaining)
                records = list(self.queue)
                self.queue.clear()
                self.pending_bytes = 0
                if self.dropped:
                    records.insert(0, f'[Log backlog full: {self.dropped} older entries omitted]\n'.encode())
                    self.dropped = 0
                self.busy = True
            try:
                self._write(records)
                with self.condition:
                    self.last_error = ''
            except (OSError, ValueError) as error:
                with self.condition:
                    self.error = str(error)
                    self.last_error = str(error)
            finally:
                with self.condition:
                    self.busy = False
                    self.condition.notify_all()

    def take_error(self):
        with self.condition:
            error, self.error = self.error, ''
            return error

    def write_error(self):
        with self.condition:
            return self.last_error

    def flush(self, timeout=2):
        deadline = time.monotonic() + timeout
        with self.condition:
            self.condition.notify()
            return self.condition.wait_for(lambda: not self.queue and not self.busy,
                                           timeout=max(0, deadline - time.monotonic()))

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        self.thread.join(timeout=2)
