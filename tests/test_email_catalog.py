import json
import tempfile
import unittest
from pathlib import Path

from atool_core.email_catalog import email_catalog_profiles, email_route_profiles, email_session_target


class EmailCatalogTests(unittest.TestCase):
    def test_routes_keep_transactions_distinct_and_reject_email_only_cache(self):
        route = {'uuid': 'parent', 'name': 'Letters', 'transactionType': 'User Defined',
                 'userDefinedTransactionType': 'Letter_DA_Email'}
        payload = {'ok': True, 'session': {'alias': 'np'}, 'routes': [route,
                   {**route, 'userDefinedTransactionType': 'Another_Email'}]}
        profiles = email_route_profiles(payload, 'np', {})
        self.assertNotEqual(profiles[0]['key'], profiles[1]['key'])
        self.assertEqual(profiles[0]['uuid'], profiles[1]['uuid'])
        self.assertEqual(profiles[0]['userDefinedTransactionType'], 'Letter_DA_Email')
        with self.assertRaises(ValueError):
            email_route_profiles({**payload, 'routes': [{**route, 'userDefinedTransactionType': ''}]}, 'np', {})
        with self.assertRaises(ValueError):
            email_route_profiles({'ok': True, 'session': {'alias': 'np'}, 'emails': []}, 'np', {})

    def test_resolves_alias_and_default_without_reading_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sessions.json'
            path.write_text(json.dumps({'currentSessionKey': 'cust.region/nonprod',
                'aliases': {'np': 'cust.region/nonprod'},
                'sessions': {'cust.region/nonprod': {'baseUrl': 'https://example.invalid/nonprod/', 'token': 'secret'}}}))
            expected = {'sessionKey': 'cust.region/nonprod', 'baseUrl': 'https://example.invalid/nonprod'}
            self.assertEqual(email_session_target('np', path), expected)
            self.assertEqual(email_session_target('', path), expected)
            self.assertEqual(email_session_target('other', path), {})

    def test_unknown_default_session_does_not_reuse_a_cache(self):
        payload = {'ok': True, 'emails': [], 'session': {'alias': ''}}
        with self.assertRaisesRegex(ValueError, 'another OCCS environment'):
            email_catalog_profiles(payload, '', {})
        payload['session']['alias'] = 'np'
        self.assertEqual(email_catalog_profiles(payload, 'np', {}), [])

    def test_rejects_failed_or_malformed_lists(self):
        for payload in ({'ok': False}, {'ok': True, 'emails': []},
                        {'ok': True, 'emails': [{'name': 'No UUID'}], 'session': {'alias': 'np'}}):
            with self.assertRaises(ValueError):
                email_catalog_profiles(payload, 'np', {})
