"""Exercise transport contracts with a local fake CLI; no remote mutations."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication
from atool_qt.occs import CommsSettings, CommsService
from atool_qt.package_documents import CatalogDialog, catalog_documents


class CommsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cli = root / 'fake-cli'
        import sys
        self.cli.write_text(f'#!{sys.executable}\n' + '''import json, sys, time
args = sys.argv[1:]
if 'slow' in args:
    time.sleep(10)
if '--output' in args:
    from pathlib import Path
    Path(args[args.index('--output') + 1]).write_text(json.dumps({'documents': [{'uuid': 'doc', 'shortName': 'DOC'}]}))
if 'fail' in args:
    print(json.dumps({'success': False, 'error': {'message': 'Expected failure', 'details': {'status': 403}}}))
    sys.exit(2)
print(json.dumps({'success': True, 'args': args}))
''')
        self.cli.chmod(0o755)
        path = root / 'settings.json'
        path.write_text(json.dumps({'occs': {'cli_path': str(self.cli), 'session_alias': 'test'}}))
        self.settings = CommsSettings(path)
        self.service = CommsService(self.settings, concurrency=1)
        self.addCleanup(self.service.shutdown)

    def until(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(condition())

    def test_command_alias_contract_and_error_details(self):
        self.assertEqual(['package', '--session', 'test', 'open'], self.settings.command(['package', 'open'])[1:])
        self.assertEqual(['documents', 'catalog'], self.settings.command(['documents', 'catalog'])[1:])
        self.assertEqual(['preview', '--session', 'other'], self.settings.command(['preview', '--session', 'other'])[1:])
        results = []
        self.service.submit(['package', 'open'], results.append)
        self.until(lambda: bool(results))
        self.assertTrue(results[0].successful)
        self.assertEqual(['package', '--session', 'test', 'open'], results[0].value['args'])
        self.service.submit(['fail'], results.append)
        self.until(lambda: len(results) == 2)
        self.assertFalse(results[1].successful)
        self.assertIn('status: 403', results[1].message)

    def test_pending_and_running_cancel_and_timeout(self):
        results = []
        self.service.submit(['slow'], results.append)
        self.service.submit(['queued'], results.append)
        self.until(lambda: bool(self.service.active))
        self.service.cancel_all()
        self.until(lambda: len(results) == 2)
        self.assertTrue(all(result.cancelled for result in results))
        self.assertFalse(self.service.active)
        self.assertFalse(self.service.pending)
        self.service.submit(['slow'], results.append, timeout_ms=30)
        self.until(lambda: len(results) == 3)
        self.assertTrue(results[2].timed_out)
        self.assertFalse(results[2].successful)

    def test_catalog_refresh_selection_and_associate_filter(self):
        path = Path(self.temp.name) / 'catalog.json'
        dialog = CatalogDialog(self.service, path, associate_name='doc')
        dialog.refresh_catalog()
        self.until(lambda: dialog.tree.topLevelItemCount() == 1)
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
        self.assertTrue(dialog.add_button.isEnabled())
        self.assertEqual('DOC', dialog.selected_document['shortName'])
        self.assertIn('--timeout', dialog.job.args)
        self.assertNotIn('--session', dialog.job.args)
        dialog.close()

    def test_catalog_aliases_deduplicate_uuid_and_keep_identity(self):
        documents = catalog_documents({'documents': [
            {'CommunicationDocumentConfigUuid': 'one', 'ShortName': 'B', 'Name': 'Bee'},
            {'uuid': 'one', 'shortName': 'duplicate'}, {'uuid': 'two', 'documentShortName': 'a'}, 'invalid']})
        self.assertEqual(['a', 'B'], [row['shortName'] for row in documents])

    def test_download_and_read_channels_run_while_regular_channel_is_full(self):
        results = []
        regular = self.service.submit(['slow'], results.append)
        queued = self.service.submit(['slow', 'queued'], results.append)
        download = self.service.submit(['slow', 'download'], results.append, channel='download_all')
        read = self.service.submit(['slow', 'read'], results.append, channel='read')
        self.until(lambda: len(self.service.active) == 3)
        self.assertIn(queued, self.service.pending)
        download.cancel()
        self.until(lambda: download.done)
        self.assertTrue(download.cancelled)
        self.assertFalse(regular.done)
        self.assertFalse(read.done)
        self.assertFalse(queued.done)
        self.service.cancel_all()
        self.until(lambda: len(results) == 4)

    def test_writes_to_same_configuration_are_serialized(self):
        self.service.channel_limits['regular'] = 2
        first = self.service.submit(['content', 'slow', '--config-id', '10'])
        second = self.service.submit(['close-config', 'slow', '--config-id', '10'])
        unrelated = self.service.submit(['content', 'slow', '--config-id', '20'])
        self.until(lambda: len(self.service.active) == 2)
        self.assertIn(first, self.service.active)
        self.assertIn(unrelated, self.service.active)
        self.assertIn(second, self.service.pending)
        self.assertEqual('config:10', first.exclusive_key)
        self.service.cancel_all()
        self.until(lambda: not self.service.active)

    def test_expired_session_refreshes_once_without_exposing_login_output(self):
        script = self.cli.read_text()
        insertion = '''from pathlib import Path
marker = Path(__file__).with_name('logged-in')
if args and args[0] == 'login':
    marker.write_text('yes')
    print(json.dumps({'success': True, 'token': 'SECRET_LOGIN_OUTPUT'}))
    sys.exit(0)
if 'auth-once' in args and not marker.exists():
    print('status code 401 unauthorized; token may have expired', file=sys.stderr)
    sys.exit(1)
if 'auth-always' in args:
    print('status code 401 unauthorized; token may have expired', file=sys.stderr)
    sys.exit(1)
'''
        self.cli.write_text(script.replace("if 'slow' in args:", insertion + "if 'slow' in args:"))
        results, displayed = [], []
        job = self.service.submit(['package', 'auth-once'], results.append)
        job.output.connect(displayed.append)
        self.until(lambda: bool(results))
        self.assertTrue(results[0].successful)
        self.assertTrue(job.login_attempted)
        self.assertEqual('test', job.login_alias)
        self.assertNotIn('SECRET_LOGIN_OUTPUT', ''.join(displayed))
        self.assertNotIn('SECRET_LOGIN_OUTPUT', results[0].stdout)
        self.service.submit(['package', 'auth-always'], results.append)
        self.until(lambda: len(results) == 2)
        self.assertFalse(results[1].successful)
        self.assertIn('401', results[1].message)
        self.assertFalse(self.service.logins)

    def test_parallel_read_retries_transient_network_error_once(self):
        script = self.cli.read_text()
        insertion = '''from pathlib import Path
marker = Path(__file__).with_name('retried')
if 'network-once' in args and not marker.exists():
    marker.write_text('first failed')
    print('ECONNRESET', file=sys.stderr)
    sys.exit(1)
'''
        self.cli.write_text(script.replace("if 'slow' in args:", insertion + "if 'slow' in args:"))
        results = []
        job = self.service.submit(['network-once'], results.append, channel='read')
        self.until(lambda: bool(results))
        self.assertTrue(results[0].successful)
        self.assertTrue(job.read_retried)

    @unittest.skipIf(__import__('os').name == 'nt', 'Unix process group cancellation')
    def test_cancel_terminates_cli_child_processes(self):
        root = Path(self.temp.name)
        marker, started = root / 'child-wrote', root / 'child-started'
        child = root / 'child.py'
        child.write_text("import time\nfrom pathlib import Path\ntime.sleep(0.4)\nPath(" + repr(str(marker)) + ").write_text('child survived')\n")
        script = self.cli.read_text()
        insertion = 'import subprocess\n' + "if 'spawn-child' in args:\n    subprocess.Popen([sys.executable, " + repr(str(child)) + "])\n    from pathlib import Path\n    Path(" + repr(str(started)) + ").write_text('started')\n    time.sleep(10)\n"
        self.cli.write_text(script.replace("if 'slow' in args:", insertion + "if 'slow' in args:"))
        job = self.service.submit(['spawn-child'])
        self.until(started.exists)
        job.cancel()
        self.until(lambda: job.done)
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertFalse(marker.exists())
