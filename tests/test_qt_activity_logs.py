"""Bounded Activity rendering and real rotating files; no remote requests."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from atool_qt.activity import ActivityLog
from atool_qt.activity_file import ActivityFile
from atool_qt.occs import CommandResult
from atool_qt.user_settings import UserSettings


class Job(QObject):
    output = Signal(str)
    http_trace = Signal(str)
    completed = Signal(object)
    args = ['preview', '--send-email']
    started_at = None
    elapsed_seconds = 1
    settings = SimpleNamespace(payload={'diagnostics': {'debug_logging': True}},
                               cli='test-cli', get=lambda key: 'np')


class ActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.activity = ActivityLog()
        self.activity.configure({'log_directory': str(self.root)})
        self.addCleanup(self.activity.close)

    def test_burst_batches_screen_updates_and_caps_unicode_backlog(self):
        self.activity.backlog_bytes = 256
        for number in range(500):
            self.activity.appendPlainText(f'entry {number} ' + '漢😀' * 10)
        self.assertTrue(self.activity.document().isEmpty())
        self.assertLessEqual(self.activity.pending_bytes, 256)
        text = self.activity.toPlainText()
        self.assertIn('entry 499', text)
        self.assertLessEqual(len(text.encode('utf-8')), 256)
        self.activity.appendPlainText('😀' * 10000)
        self.assertLessEqual(len(self.activity.toPlainText().encode('utf-8')), 256)
        self.activity.configure({'activity_backlog_kib': 1, 'log_directory': str(self.root)})
        self.assertLessEqual(len(self.activity.toPlainText().encode('utf-8')), 1024)

    def test_both_menus_share_actions_and_open_only_after_all_pending_writes(self):
        first, second = QMenu(), QMenu()
        self.activity.populate_menu(first)
        self.activity.populate_menu(second)
        self.assertEqual([action for action in first.actions() if not action.isSeparator()],
                         [action for action in second.actions() if not action.isSeparator()])
        self.assertEqual([action.text() for action in first.actions() if not action.isSeparator()],
                         ['Copy', 'Copy All Activity', 'Select All', 'Open Current Log', 'Show Log Folder', 'Save Activity…', 'Clear Activity'])
        for menu in (first, second):
            self.activity.appendPlainText('pending latest detail')
            def opened(url):
                self.assertEqual(Path(url.toLocalFile()), (self.root / 'atool.log').resolve())
                self.assertIn('pending latest detail', Path(url.toLocalFile()).read_text())
                self.assertEqual(self.activity.file_log.pending_bytes, 0)
                self.assertFalse(self.activity.file_log.busy)
                return True
            with patch('atool_qt.activity.QDesktopServices.openUrl', side_effect=opened) as launch:
                self.activity.menu_actions['open_log'].trigger()
                launch.assert_called_once()

    def test_show_folder_and_open_failure_or_flush_timeout(self):
        with patch('atool_qt.activity.QDesktopServices.openUrl', return_value=True) as launch:
            self.activity.show_log_folder()
            self.assertEqual(Path(launch.call_args.args[0].toLocalFile()), self.root.resolve())
        for outcome in ('timeout', 'launch'):
            with patch('atool_qt.activity.QDesktopServices.openUrl', return_value=False) as launch, \
                 patch.object(QMessageBox, 'warning') as warning:
                if outcome == 'timeout':
                    with patch.object(self.activity.file_log, 'flush', return_value=False):
                        self.activity.open_current_log()
                    launch.assert_not_called()
                else:
                    self.activity.open_current_log()
                    launch.assert_called_once()
                warning.assert_called_once()

    def test_write_failure_prevents_opening_a_stale_file(self):
        self.activity.appendPlainText('previously persisted')
        self.assertTrue(self.activity.file_log.flush())
        with patch.object(self.activity.file_log, '_write', side_effect=OSError('Disk full')):
            self.activity.appendPlainText('pending cannot be persisted')
            self.assertTrue(self.activity.file_log.flush())
            self.activity.flush_pending()  # consumes the on-screen error notification
            with patch('atool_qt.activity.QDesktopServices.openUrl') as launch, \
                 patch.object(QMessageBox, 'warning') as warning:
                self.activity.open_current_log()
                launch.assert_not_called()
                self.assertIn('Disk full', warning.call_args.args[2])

    def test_http_details_go_to_file_summary_stays_in_activity_and_clear_keeps_file(self):
        job = Job()
        self.activity.track_operation(job)
        job.http_trace.emit('@OCCS_HTTP@' + json.dumps({
            'type': 'response', 'method': 'POST', 'status': 400, 'durationMs': 45,
            'headers': {'Authorization': 'Bearer SECRET'}, 'body': {'message': 'server detail', 'executionId': 'EXEC-1'}}))
        screen = self.activity.toPlainText()
        self.assertIn('HTTP Response', screen)
        self.assertNotIn('server detail', screen)
        self.activity.appendPlainText('Authorization: Bearer ANOTHER_SECRET')
        job.completed.emit(CommandResult(1, '', 'server detail', None))
        self.assertTrue(self.activity.file_log.flush())
        text = (self.root / 'atool.log').read_text()
        self.assertIn('server detail', text)
        self.assertIn('EXEC-1', text)
        self.assertIn('Failed · Total', text)
        self.assertNotIn('SECRET', text)
        self.activity.clear()
        self.assertEqual(self.activity.toPlainText(), '')
        self.assertEqual((self.root / 'atool.log').read_text(), text)

    def test_many_tiny_lines_do_not_create_unbounded_qt_blocks(self):
        self.activity.queue_display('\n'.join(f'line-{number}' for number in range(20000)))
        self.assertIn('line-19999', self.activity.toPlainText())
        self.assertLessEqual(self.activity.document().blockCount(), 10000)

    def test_clear_during_operation_preserves_later_file_diagnostics(self):
        job = Job()
        self.activity.track_operation(job)
        self.activity.clear()
        job.http_trace.emit('@OCCS_HTTP@' + json.dumps({
            'type': 'response', 'method': 'POST', 'status': 400, 'body': {'executionId': 'AFTER-CLEAR'}}))
        job.completed.emit(CommandResult(1, '', 'Failed after clear', None))
        self.assertEqual(self.activity.toPlainText(), '')
        self.assertTrue(self.activity.file_log.flush())
        text = self.activity.file_log.path.read_text()
        self.assertIn('AFTER-CLEAR', text)
        self.assertIn('Failed after clear', text)

    def test_pruning_running_line_does_not_overwrite_other_messages(self):
        self.activity.backlog_bytes = 150
        job = Job()
        self.activity.track_operation(job)
        self.activity.appendPlainText('other ' * 25)
        self.activity.toPlainText()
        job.started_at = 1
        self.activity.refresh_operations()
        self.assertIn('other', self.activity.toPlainText())
        job.completed.emit(CommandResult(0, '', '', None))
        self.assertIn('Completed · Total', self.activity.toPlainText())
        self.assertLessEqual(len(self.activity.toPlainText().encode()), 150)

    def test_oversized_split_output_is_discarded_without_leaking_fragments(self):
        job = Job()
        self.activity.track_operation(job)
        job.output.emit('Authorization: Bearer ' + 'S' * 70000)
        self.assertEqual(self.activity.output_buffers[job], '')
        job.output.emit('SECRET_SUFFIX\nnormal progress\n')
        self.assertIn('normal progress', self.activity.toPlainText())
        self.assertTrue(self.activity.file_log.flush())
        text = self.activity.file_log.path.read_text()
        self.assertIn('Oversized output line omitted', text)
        self.assertNotIn('SECRET_SUFFIX', text)

    def test_unwritable_directory_is_visible_and_does_not_break_activity(self):
        path = self.root / 'file'
        path.write_text('not a directory')
        self.activity.configure({'log_directory': str(path)})
        self.activity.appendPlainText('still working')
        self.activity.file_log.flush()
        self.assertIn('Activity file logging failed', self.activity.toPlainText())


class FileTests(unittest.TestCase):
    def test_two_writers_share_one_log_without_losing_records(self):
        with tempfile.TemporaryDirectory() as folder:
            first = ActivityFile(folder, max_bytes=1024 * 1024, backups=2)
            second = ActivityFile(folder, max_bytes=1024 * 1024, backups=2)
            try:
                for index in range(30):
                    first.append(f'first-{index}')
                    second.append(f'second-{index}')
                self.assertTrue(first.flush())
                self.assertTrue(second.flush())
                text = first.path.read_text()
                self.assertEqual(len(text.splitlines()), 60)
                self.assertIn('first-29', text)
                self.assertIn('second-29', text)
            finally:
                first.close()
                second.close()

    def test_rotation_obeys_size_and_backup_count_and_reduction(self):
        with tempfile.TemporaryDirectory() as folder:
            sink = ActivityFile(folder, max_bytes=256, backups=2)
            try:
                for index in range(15):
                    sink.append(f'entry-{index} ' + '漢' * 40)
                self.assertTrue(sink.flush())
                files = list(Path(folder).glob('atool.log*'))
                self.assertEqual(len(files), 3)
                self.assertTrue(all(file.stat().st_size <= 256 for file in files))
                self.assertIn('entry-14', sink.path.read_text())
            finally:
                sink.close()
            sink = ActivityFile(folder, max_bytes=256, backups=1)
            sink.append('new settings')
            sink.close()
            self.assertFalse((Path(folder) / 'atool.log.2').exists())

    def test_slow_writer_has_bounded_queue_and_reports_dropped_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            entered, release = threading.Event(), threading.Event()
            original = ActivityFile._write
            def slow(sink, records):
                entered.set()
                release.wait(timeout=2)
                original(sink, records)
            with patch.object(ActivityFile, '_write', slow):
                sink = ActivityFile(folder, max_bytes=1024, backups=5, queue_bytes=256)
                try:
                    sink.append('first')
                    self.assertTrue(entered.wait(timeout=1))
                    for number in range(100):
                        sink.append(f'queued-{number} ' + 'x' * 80)
                    self.assertLessEqual(sink.pending_bytes, 256)
                    release.set()
                    self.assertTrue(sink.flush())
                    self.assertIn('backlog full', sink.path.read_text())
                    self.assertIn('queued-99', sink.path.read_text())
                finally:
                    release.set()
                    sink.close()

    def test_setting_defaults_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = UserSettings(Path(folder) / 'settings.json')
            values = store.payload['diagnostics']
            self.assertEqual(values['activity_backlog_kib'], 1024)
            self.assertEqual(values['log_file_max_mib'], 10)
            self.assertEqual(values['log_backup_count'], 5)
            for key, invalid in [('activity_backlog_kib', 0), ('log_file_max_mib', -1), ('log_backup_count', 'bad')]:
                previous = values[key]
                values[key] = invalid
                with self.assertRaises(ValueError):
                    store.validate(store.payload)
                values[key] = previous
