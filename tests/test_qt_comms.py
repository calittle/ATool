"""Exercise transport contracts with a local fake CLI; no remote mutations."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from atool_qt.activity import ActivityLog, duration_text
from atool_qt.occs import CommandResult, CommsSettings, CommsService
from atool_core.activity_output import activity_text, sanitized_http_value, mask_email_address
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

    def activity_log(self):
        activity = ActivityLog()
        self.addCleanup(activity.close)
        self.service.submitted.connect(activity.track_operation)
        return activity

    def test_email_activity_retains_live_output_request_and_failure(self):
        self.settings.payload['diagnostics'] = {'debug_logging': True}
        script = self.cli.read_text()
        insertion = '''if 'diagnostic-email' in args:
    print('→ EMAIL POST https://example.invalid/api/Communication/v1/CommunicationRec', flush=True)
    print('Authorization: Bearer SECRET_TOKEN', flush=True)
    print('Waiting for Comms response...', flush=True)
    time.sleep(0.25)
    print('HTTP 400: Communication Email not found', file=sys.stderr, flush=True)
    sys.exit(2)
'''
        self.cli.write_text(script.replace("if 'slow' in args:", insertion + "if 'slow' in args:"))
        activity = self.activity_log()
        job = self.service.submit(['preview', 'diagnostic-email', '--render-type', 'EMAIL',
            '--email-config-uuid', 'EMAIL-PARENT', '--recipient', 'test@example.test', '--send-email'])
        self.until(lambda: 'EMAIL POST' in activity.toPlainText())
        self.assertFalse(job.done)
        self.assertIn('Email UUID: EMAIL-PARENT', activity.toPlainText())
        self.assertIn('Session: test', activity.toPlainText())
        self.until(lambda: job.done)
        text = activity.toPlainText()
        self.assertIn('OCCS #1 · Send Email · Failed', text)
        self.assertIn('Exit status 2', text)
        self.assertIn('HTTP 400: Communication Email not found', text)
        self.assertNotIn('SECRET_TOKEN', text)

    def test_failure_detail_is_retained_without_debug(self):
        activity = self.activity_log()
        job = self.service.submit(['fail'])
        self.until(lambda: job.done)
        self.assertIn('Expected failure', activity.toPlainText())
        self.assertIn('status: 403', activity.toPlainText())

    def test_split_output_is_redacted_and_clear_drops_pending_output(self):
        self.settings.payload['diagnostics'] = {'debug_logging': True}
        activity = self.activity_log()
        job = self.service.submit(['slow'])
        job.output.emit('Authorization: Bearer SPLIT_')
        job.output.emit('SECRET\n')
        self.assertNotIn('SPLIT_SECRET', activity.toPlainText())
        self.assertIn('[redacted]', activity.toPlainText())
        activity.clear()
        job.output.emit('late diagnostic\n')
        self.assertEqual(activity.toPlainText(), '')
        job.cancel()

    def test_error_messages_and_activity_redaction(self):
        self.assertEqual(CommandResult(1, '', '', {'ok': False, 'error': 'Lookup failed'}).message, 'Lookup failed')
        self.assertEqual(CommandResult(1, 'API error on stdout', '', None).message, 'API error on stdout')
        cleaned = activity_text('\x1b[31mHTTP 400\x1b[0m\nAuthorization: Bearer SECRET\n'
            + json.dumps({'password': 'PASSWORD', 'CommunicationData': json.dumps({'name': 'customer'})}))
        self.assertIn('HTTP 400', cleaned)
        self.assertNotIn('SECRET', cleaned)
        self.assertNotIn('PASSWORD', cleaned)
        self.assertNotIn('customer', cleaned)

    def test_debug_http_dumps_are_pretty_printed_and_sanitized_in_json_mode(self):
        self.settings.payload['diagnostics'] = {'debug_logging': True}
        events = [
            {'id': 'HTTP-1', 'type': 'request', 'method': 'POST', 'url': 'https://example.invalid/api',
             'headers': {'Authorization': 'Bearer SECRET'},
             'body': {'CommunicationInfo': {'CommunicationConfigUuid': 'COMM-1',
                 'CommunicationData': json.dumps({'sendDetail': {'deliveryInfo': {'firstName': 'Alice', 'contactValue': 'customer@example.test'}}})}}},
            {'id': 'HTTP-1', 'type': 'response', 'status': 400, 'headers': {'Set-Cookie': 'COOKIE-SECRET'},
             'body': {'messageCode': 'SFD0671', 'executionId': 'EXEC-ID', 'message': 'BucketNotFound'}},
        ]
        script = self.cli.read_text()
        insertion = "import os\nif os.environ.get('OCCS_HTTP_DEBUG') == '1':\n"
        for event in events:
            insertion += f"    print('@OCCS_HTTP@' + json.dumps({event!r}), file=sys.stderr, flush=True)\n"
        self.cli.write_text(script.replace("if 'slow' in args:", insertion + "if 'slow' in args:"))
        activity = self.activity_log()
        job = self.service.submit(['list-emails', '--json'])
        self.until(lambda: job.done)
        text = activity.toPlainText()
        self.assertIn('HTTP Request', text)
        self.assertIn('HTTP Response', text)
        self.assertIn('"CommunicationConfigUuid": "COMM-1"', text)
        self.assertIn('"messageCode": "SFD0671"', text)
        self.assertIn('"executionId": "EXEC-ID"', text)
        self.assertIn('"status": 400', text)
        for secret in ('Bearer SECRET', 'COOKIE-SECRET', 'Alice', 'customer@example.test'):
            self.assertNotIn(secret, text)
        self.assertIn('cu***@example.test', text)
        self.assertTrue(json.loads(job.stdout)['success'])
        activity.clear()
        self.settings.payload['diagnostics']['debug_logging'] = False
        quiet = self.service.submit(['list-emails', '--json'])
        self.until(lambda: quiet.done)
        self.assertNotIn('HTTP Request', activity.toPlainText())
        self.assertNotIn('@OCCS_HTTP@', quiet.stderr.decode())

    def test_http_traces_do_not_replace_the_failure_message(self):
        result = CommandResult(1, '', '@OCCS_HTTP@{"type":"response","status":400}\nActual server failure', None)
        self.assertEqual(result.message, 'Actual server failure')

    def test_address_diagnostics_remain_useful_through_both_sanitizers(self):
        self.assertEqual(mask_email_address('customer@example.test'), 'cu***@example.test')
        self.assertEqual(mask_email_address(''), '[empty address]')
        self.assertIn('no @', mask_email_address('not-an-address'))
        self.assertIsNone(mask_email_address(None))
        payload = {'CommunicationData': json.dumps({'sendDetail': {
            'deliveryInfo': {'contactValue': 'customer@example.test', 'templateName': 'CO-G10-CO63', 'deliveryType': 'EMAI', 'firstName': 'Alice'},
            'templateParm': [{'key': 'SEND_AT_VALUE', 'value': '12'}],
        }})}
        masked = sanitized_http_value(payload)
        data = json.loads(masked['CommunicationData'])['sendDetail']
        self.assertEqual(data['deliveryInfo']['contactValue'], 'cu***@example.test')
        self.assertEqual(data['deliveryInfo']['templateName'], 'CO-G10-CO63')
        self.assertEqual(data['templateParm'][0]['key'], 'SEND_AT_VALUE')
        self.assertEqual(data['templateParm'][0]['value'], '[masked: string, 2 chars]')
        self.assertNotIn('Alice', json.dumps(masked))
        self.assertEqual(sanitized_http_value(masked), masked)
        self.assertIn('cu***@example.test', activity_text('Recipient: customer@example.test'))

    def test_http_records_are_not_interleaved_with_machine_stdout(self):
        self.settings.payload['diagnostics'] = {'debug_logging': True}
        activity = self.activity_log()
        job = self.service.submit(['list-emails', '--json'])
        displayed = []
        job.output.connect(displayed.append)
        record = '@OCCS_HTTP@' + json.dumps({'id': 'split-http', 'type': 'response', 'status': 200,
            'body': {'executionId': 'INTACT-RESPONSE', 'message': 'x' * 70000}})
        job.display_stderr(record[:33000])
        job.output.emit('{"ok":true,"emails":[]}\n')
        job.display_stderr(record[33000:] + '\n')
        self.assertIn('INTACT-RESPONSE', activity.toPlainText())
        self.assertNotIn('Invalid HTTP diagnostic record', activity.toPlainText())
        self.assertFalse(any('@OCCS_HTTP@' in line for line in displayed))
        job.cancel()

    def test_send_email_hides_legacy_discovery_dumps_and_keeps_send_pair(self):
        self.settings.payload['diagnostics'] = {'debug_logging': True}
        activity = self.activity_log()
        job = self.service.submit(['preview', '--send-email'])
        for number in range(37):
            for kind in ('request', 'response'):
                event = {'type': kind, 'method': 'GET', 'url': 'https://example.invalid/config',
                         'body': {'UnrelatedMetadata': 'x' * 20000}}
                job.http_trace.emit('@OCCS_HTTP@' + json.dumps(event))
        for kind in ('request', 'response'):
            event = {'type': kind, 'method': 'POST', 'url': 'https://example.invalid/api/Communication/v1/CommunicationRec',
                     'status': 201, 'body': {'message': 'Relevant send result'}}
            job.http_trace.emit('@OCCS_HTTP@' + json.dumps(event))
        text = activity.toPlainText()
        self.assertIn('Routing lookup: 37 configuration reads.', text)
        self.assertNotIn('UnrelatedMetadata', text)
        self.assertEqual(text.count('HTTP Request'), 1)
        self.assertEqual(text.count('HTTP Response'), 1)
        self.assertIn('Relevant send result', text)
        self.assertLess(len(text), 5000)
        job.cancel()

    def test_activity_timer_runs_without_adding_lines_and_freezes_on_cancel(self):
        activity = self.activity_log()
        job = self.service.submit(['package', 'slow'])
        activity.appendPlainText('Other activity while the CLI runs')
        self.until(lambda: job.started_at is not None)
        self.until(lambda: 'Elapsed 00:00:01' in activity.toPlainText())
        text = activity.toPlainText()
        self.assertIn('OCCS #1 · package slow · Running · Elapsed 00:00:01', text)
        self.assertEqual(2, activity.document().blockCount())
        self.assertIn('Other activity while the CLI runs', text)
        job.cancel()
        self.until(lambda: job.done)
        self.assertIn('Cancelled · Total 00:00:01', activity.toPlainText())
        duration = job.elapsed_seconds
        text = activity.toPlainText()
        QTest.qWait(300)
        self.assertEqual(duration, job.elapsed_seconds)
        self.assertEqual(text, activity.toPlainText())
        self.assertFalse(activity.timer.isActive())
        self.assertFalse(activity.operations)

    def test_activity_tracks_concurrent_and_queued_operations_independently(self):
        activity = self.activity_log()
        running = self.service.submit(['package', 'slow'])
        queued = self.service.submit(['package', 'queued'])
        concurrent = self.service.submit(['content', 'slow'], channel='read')
        self.until(lambda: len(self.service.active) == 2)
        QTest.qWait(300)
        self.assertIn('OCCS #1 · package slow · Running', activity.toPlainText())
        self.assertIn('OCCS #2 · package queued · Queued', activity.toPlainText())
        self.assertIn('OCCS #3 · content slow · Running', activity.toPlainText())
        queued.cancel()
        self.assertIsNone(queued.started_at)
        self.assertIn('OCCS #2 · package queued · Cancelled · Total 00:00:00', activity.toPlainText())
        self.service.cancel_all()
        self.until(lambda: running.done and concurrent.done)
        self.assertEqual(3, activity.document().blockCount())
        self.assertFalse(activity.timer.isActive())

    def test_clearing_activity_during_operation_preserves_new_messages(self):
        activity = self.activity_log()
        job = self.service.submit(['package', 'slow'])
        self.until(lambda: job.started_at is not None)
        activity.clear()
        self.assertEqual('', activity.toPlainText())
        activity.appendPlainText('New activity after clearing')
        activity.refresh_operations()
        job.cancel()
        self.until(lambda: job.done)
        self.assertEqual('New activity after clearing', activity.toPlainText())
        self.assertFalse(activity.timer.isActive())

    def test_activity_retains_success_failure_timeout_and_failed_start_totals(self):
        activity = self.activity_log()
        for args, status, timeout in [(['package', 'open'], 'Completed', None),
                                      (['fail'], 'Failed', None),
                                      (['slow'], 'Timed out', 30)]:
            job = self.service.submit(args, timeout_ms=timeout)
            self.until(lambda: job.done)
            self.assertIn(f'{status} · Total {duration_text(job.elapsed_seconds)}', activity.toPlainText())
        self.settings.payload['occs']['cli_path'] = str(Path(self.temp.name) / 'missing-cli')
        job = self.service.submit(['package', 'open'])
        self.until(lambda: job.done)
        self.assertIn('OCCS #4 · package open · Failed · Total', activity.toPlainText())
        self.assertFalse(activity.operations)
        self.assertEqual('01:01:01', duration_text(3661.9))

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
        activity = self.activity_log()
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
        self.assertGreaterEqual(job.elapsed_seconds, 2)
        self.assertEqual(1, activity.document().blockCount())
        self.assertIn('Completed · Total', activity.toPlainText())

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
