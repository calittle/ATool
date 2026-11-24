"""Readable migration evidence, missing attribution, safe Markdown, and CLI export."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from atool_qt.migration_report import migration_report, write_migration_report


class MigrationReportTests(unittest.TestCase):
    def test_separate_migration_account_is_reported_without_credentials(self):
        record=self.record()
        record['events'].append(dict(at='2026-11-19T04:05:00Z',kind='migration_source_login_selected',
                                     username='migration-user',password='DO_NOT_EXPORT',token='DO_NOT_EXPORT'))
        report=migration_report(record,Path('/migration'))
        self.assertIn('Separate migration source login: migration-user',report)
        self.assertNotIn('DO_NOT_EXPORT',report)

    def record(self):
        actor=dict(displayName='Jane Operator',user='joperator')
        return dict(version=1,stage='complete',created_at='2026-11-19T04:00:00+00:00',
            created_by=actor,performed_by=actor,source='np',target='pp',suite_name='POC 5 Bills',
            original_suite='/suites/POC 5 Bills.json',configs=[dict(id='431',shortName='BillsFix',name='Bill changes')],
            closed=['431'],pending=None,settings=dict(comparison_threshold_percent=1.0,password='DO_NOT_EXPORT'),
            hashes={'suite.json':'abc123','inputs/1.json':'def456'},
            published=dict(package='print_bulk',version='3.0',config_id='431',source='np',no_changes=False),
            completion_verification=dict(target='pp',verified_by=actor,verified_at='2026-11-19T04:15:00Z',
                previous_stage='migrate',previous_pending='migration',note='Verified Config BillsFix in PP.'),
            postflight=dict(stopped=False,runs=[dict(label='Comparison: np → pp',report='reports/smoke-report.html',
                valid=True,successful=True,passed=5,failed=0,reviews=1)]),
            reviewed_by=actor,reviewed_at='2026-11-19T04:20:00Z',review_note='Expected timestamp difference.',
            email_sent=True,events=[dict(at='2026-11-19T04:00:00Z',kind='created',actor=actor),
                dict(at='2026-11-19T04:15:00Z',kind='target_migration_verified',actor=actor,
                    verification=dict(note='Verified Config BillsFix in PP.')),
                dict(at='2026-11-19T04:22:00Z',kind='handoff_sent',actor=actor,recipients=['reviewer@example.test'])])

    def test_complete_report_contains_operator_results_verification_and_handoff(self):
        report=migration_report(self.record(),Path('/migration'))
        for content in ('# Migration Report','Jane Operator','joperator','POC 5 Bills','431','print','3.0',
                        'Verified Config BillsFix in PP.','Expected timestamp difference.',
                        '2026-11-19 04:15:00 UTC','comparison(s) flagged for review','reviewer@example.test',
                        '## Action history','abc123','def456','reports/smoke-report.html','reports/smoke-email.eml'):
            with self.subTest(content=content):
                self.assertIn(content,report)
        self.assertNotIn('DO_NOT_EXPORT',report)
        self.assertIn('No CLI initiation receipt recorded',report)
        self.assertIn('does not establish whether an earlier attempt moved',report)

    def test_old_record_does_not_invent_operator_or_action_users(self):
        data=self.record()
        for key in ('created_by','performed_by','reviewed_by','completion_verification'):
            data.pop(key,None)
        data['completion_note']='Verified target manually.'
        for event in data['events']:
            event.pop('actor',None)
        report=migration_report(data,Path('/migration'))
        self.assertIn('| Migration operator | Not recorded |',report)
        self.assertIn('| Started by | Not recorded |',report)
        self.assertIn('Verification user and time were not recorded',report)
        self.assertIn('| Not recorded | Migration record created |',report)
        self.assertNotIn('Jane Operator',report)

    def test_pending_or_failed_reports_cannot_claim_completion(self):
        data=self.record()
        for key in ('reviewed_at','reviewed_by','completion_verification','email_sent'):
            data.pop(key,None)
        data.update(stage='migrate',pending='migration',postflight=dict(stopped=False,runs=[
            dict(valid=True,successful=True,failed=1,passed=5,reviews=1)]))
        report=migration_report(data,Path('/migration'))
        self.assertIn('Unresolved operation',report)
        self.assertIn('Failed previews; not passed',report)
        self.assertIn('Successful completion has not been verified',report)
        self.assertIn('Final comparison acceptance has not been recorded',report)
        self.assertIn('Email sending has not been recorded',report)

    def test_record_values_are_escaped_without_breaking_markdown_tables(self):
        data=self.record()
        data['performed_by']['displayName']='Name | <script>alert(1)</script>\n# Forged heading'
        data['review_note']='[click](https://example.invalid) **approved**'
        report=migration_report(data,Path('/migration'))
        self.assertNotIn('<script>',report)
        self.assertIn('&lt;script&gt;',report)
        self.assertIn('Name \\|',report)
        self.assertNotIn('\n# Forged heading',report)
        self.assertNotIn('[click](https://example.invalid)',report)

    def test_convert_cli_and_exported_evidence_links_preserve_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            folder=root/'Migration with spaces'
            folder.mkdir()
            data=self.record()
            data['postflight']['runs'][0]['report']=str(folder/'reports'/'smoke report.html')
            source=folder/'migration.json'
            encoded=json.dumps(data)
            source.write_text(encoded)
            output=write_migration_report(source)
            self.assertEqual(output.name,'migration-report.md')
            self.assertIn('reports/smoke%20report.html',output.read_text())
            exported=root/'exports'/'report.md'
            result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'tools'/'migration_report.py'),str(source),'-o',str(exported)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            text=exported.read_text()
            self.assertIn('../Migration%20with%20spaces/migration.json',text)
            self.assertIn('../Migration%20with%20spaces/reports/smoke%20report.html',text)
            self.assertEqual(source.read_text(),encoded)
            data['postflight']['runs'][0]['report']='reports/smoke report.html'
            source.write_text(json.dumps(data))
            write_migration_report(source,exported)
            self.assertIn('../Migration%20with%20spaces/reports/smoke%20report.html',exported.read_text())

    def test_invalid_records_and_source_overwrite_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'migration.json'
            source.write_text(json.dumps(self.record()))
            before=source.read_bytes()
            with self.assertRaises(ValueError):
                write_migration_report(source,source)
            self.assertEqual(source.read_bytes(),before)
            source.write_text('{}')
            with self.assertRaises(ValueError):
                write_migration_report(source)
            self.assertFalse(source.with_name('migration-report.md').exists())


if __name__=='__main__':
    unittest.main()
