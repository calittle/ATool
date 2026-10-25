"""Release publication must require acceptance, stapling, and Gatekeeper checks."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.notarize_macos import notarize


class NotarizationTests(unittest.TestCase):
    def run_submission(self, status, code=0):
        def run(command, **kwargs):
            if command[:3] == ['xcrun', 'notarytool', 'submit']:
                return subprocess.CompletedProcess(command, code, json.dumps({'id': 'test-id', 'status': status}), 'service unavailable' if code else '')
            return subprocess.CompletedProcess(command, 0)
        return run

    def test_accepted_submission_staples_before_final_assessment(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / 'ATool.app'
            bundle.mkdir()
            with patch('tools.notarize_macos.subprocess.run', side_effect=self.run_submission('Accepted')) as run:
                notarize(bundle, Path(directory) / 'signing.keychain-db')
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(['xcrun', 'stapler', 'staple', str(bundle)], commands[3])
            self.assertEqual(['xcrun', 'stapler', 'validate', str(bundle)], commands[4])
            self.assertEqual('spctl', commands[-1][0])
            archive = Path(commands[2][3])
            self.assertFalse(archive.parent.exists())

    def test_rejected_or_pending_submission_never_staples_or_assesses(self):
        for status in ('Invalid', 'Rejected', 'In Progress'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                bundle = Path(directory) / 'ATool.app'
                bundle.mkdir()
                with patch('tools.notarize_macos.subprocess.run', side_effect=self.run_submission(status)) as run:
                    with self.assertRaisesRegex(RuntimeError, 'must not be published'):
                        notarize(bundle, Path(directory) / 'signing.keychain-db')
                commands = [call.args[0] for call in run.call_args_list]
                self.assertTrue(any(command[:3] == ['xcrun', 'notarytool', 'log'] for command in commands))
                self.assertFalse(any('stapler' in command or command[0] == 'spctl' for command in commands))

    def test_service_failure_never_staples(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / 'ATool.app'
            bundle.mkdir()
            with patch('tools.notarize_macos.subprocess.run', side_effect=self.run_submission(None, code=1)) as run:
                with self.assertRaisesRegex(RuntimeError, 'submission failed'):
                    notarize(bundle, Path(directory) / 'signing.keychain-db')
            self.assertEqual(3, run.call_count)

    def test_signature_failure_stops_before_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / 'ATool.app'
            bundle.mkdir()
            with patch('tools.notarize_macos.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'codesign')) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    notarize(bundle, Path(directory) / 'signing.keychain-db')
            self.assertEqual(1, run.call_count)
