"""Email payload formats, using synthetic notification data."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from atool_core.email_input import email_recipients, prepare_email_input


class NotificationEmailTests(unittest.TestCase):
    def test_plain_and_wrapped_notification_override_preserves_input(self):
        payload = {'sendDetail': {
            'accountId': 'synthetic',
            'deliveryInfo': {'deliveryType': 'EMAI', 'contactValue': 'original@example.test', 'templateName': 'test'},
            'templateParm': [{'key': 'name', 'value': 'Example'}],
        }, 'other': [1]}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'data.json'
            for data in (payload, {'CommunicationInfo': {'CommunicationData': payload}},
                         {'CommunicationInfo': {'CommunicationData': json.dumps(payload)}}):
                with self.subTest(wrapped='CommunicationInfo' in data):
                    source.write_text(json.dumps(data))
                    original = copy.deepcopy(data)
                    self.assertEqual(email_recipients(data), ['original@example.test'])
                    path, temporary = prepare_email_input(data, source, ' test@example.test ')
                    try:
                        prepared = json.loads(path.read_text())
                        self.assertEqual(prepared['sendDetail']['deliveryInfo']['contactValue'], 'test@example.test')
                        prepared['sendDetail']['deliveryInfo']['contactValue'] = 'original@example.test'
                        self.assertEqual(prepared, payload)
                        self.assertEqual(data, original)
                        self.assertEqual(json.loads(source.read_text()), original)
                    finally:
                        temporary.cleanup()
                    self.assertFalse(path.exists())

    def test_missing_contact_can_be_added_and_invalid_inputs_are_rejected(self):
        payload = {'sendDetail': {'deliveryInfo': {}}}
        self.assertEqual(email_recipients(payload), [])
        path, temporary = prepare_email_input(payload, 'unused.json', 'test@example.test')
        try:
            self.assertEqual(json.loads(path.read_text())['sendDetail']['deliveryInfo']['contactValue'], 'test@example.test')
        finally:
            temporary.cleanup()
        for detail in (None, [], {}, {'deliveryInfo': []}, {'deliveryInfo': 'invalid'}):
            with self.subTest(detail=detail), self.assertRaisesRegex(ValueError, 'sendDetail.deliveryInfo'):
                prepare_email_input({'sendDetail': detail}, 'unused.json', 'test@example.test')
        for recipients in ('', 'a@example.test,b@example.test'):
            with self.subTest(recipients=recipients), self.assertRaises(ValueError):
                prepare_email_input(payload, 'unused.json', recipients)

    def test_legacy_uses_same_notification_preparation(self):
        try:
            from ATool import AToolApp
        except ImportError:
            self.skipTest('Tkinter is not installed')
        app = AToolApp.__new__(AToolApp)
        app.current_data_payload = {'sendDetail': {'deliveryInfo': {'contactValue': 'original@example.test'}}}
        self.assertEqual(app._occs_email_recipients_from_payload(app.current_data_payload), ['original@example.test'])
        path = app._build_occs_email_input(Path('unused.json'), 'test@example.test')
        try:
            self.assertEqual(json.loads(path.read_text())['sendDetail']['deliveryInfo']['contactValue'], 'test@example.test')
        finally:
            path.unlink()
