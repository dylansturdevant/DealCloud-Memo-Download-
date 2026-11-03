"""Offline simulated tests. Never creates a real DealCloud client."""
from __future__ import annotations
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile
import pandas as pd

ROOT = Path(__file__).resolve().parent
# Stub the SDK before importing the engine: these tests cannot authenticate.
sdk = types.ModuleType('dealcloud_sdk')
sdk.DealCloud = lambda *a, **k: (_ for _ in ()).throw(AssertionError('Live SDK access prohibited in tests'))
spec = importlib.util.spec_from_file_location('offline_test_engine', ROOT / 'downloader_engine.py')
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
with patch.dict(sys.modules, {'dealcloud_sdk': sdk}):
    spec.loader.exec_module(engine)

from ui_support import parse_credentials, fingerprint, lines, output_directory, create_archive
from worker import RedactedStream


class FakeDC:
    def __init__(self):
        self.downloads = []
        self.metadata_calls = 0
        self.reads = []
        self.rows = [
            {'DealCloud Entry ID': 11, 'Fund': 101, 'ICDate': '2026-01-15', 'Stage': 'Final',
             'Recommendation': 'Approved', 'RecommendationApprovedbyIC': True, 'InternalMemo': {'id': 501, 'name': 'final.pdf'}, 'ClientReadyMemo': None, 'ClientVersionofMemo': None},
            {'DealCloud Entry ID': 12, 'Fund': 101, 'ICDate': '2026-02-15', 'Stage': 'Screening',
             'Recommendation': 'Approved', 'RecommendationApprovedbyIC': False, 'InternalMemo': {'id': 502, 'name': 'screen.pdf'}, 'ClientReadyMemo': None, 'ClientVersionofMemo': None},
            {'DealCloud Entry ID': 13, 'Fund': 102, 'ICDate': '2026-01-16', 'Stage': 'Final',
             'Recommendation': 'Approved', 'RecommendationApprovedbyIC': None, 'InternalMemo': {'id': 503, 'name': 'other.pdf'}, 'ClientReadyMemo': None, 'ClientVersionofMemo': None},
            {'DealCloud Entry ID': 14, 'Fund': 101, 'ICDate': '2025-12-01', 'Stage': 'Final',
             'Recommendation': 'Approved', 'RecommendationApprovedbyIC': True, 'InternalMemo': {'id': 504, 'name': 'old.pdf'}, 'ClientReadyMemo': None, 'ClientVersionofMemo': None},
        ]
    def get_fields(self, obj):
        if obj == 'Attachment':
            return [{'id': 999, 'apiName': 'File', 'displayName': 'File', 'fieldType': 13}]
        fields = list(self.rows[0]) if obj == 'DiligenceActivity' else ['FundName', 'Structure', 'AssetClass']
        return [{'id': i + 1, 'apiName': field, 'displayName': field} for i, field in enumerate(fields)]
    def read_data(self, **kwargs):
        self.reads.append(kwargs)
        if kwargs['object_id'] == 'DiligenceActivity':
            return pd.DataFrame(self.rows)
        if kwargs['object_id'] == 'Fund':
            requested = json.loads(kwargs['query'])['EntryId']['$in']
            return pd.DataFrame([{'DealCloud Entry ID': i, 'FundName': f'Fund {i}', 'Structure': 'Primary Partnership', 'AssetClass': 'Private Equity'} for i in requested])
        raise AssertionError('Unexpected object read')
    def download_attachment_metadata(self, **kwargs):
        self.metadata_calls += 1
        return {'fileName': f"memo_{kwargs['entry_id']}.pdf"}
    def download_file(self, **kwargs):
        self.downloads.append(kwargs)
        Path(kwargs['output_path']).write_bytes(b'%PDF-simulated-not-a-real-document')


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.directory = Path(self.temp.name)
        self.settings = patch.multiple(engine,
            START_DATE=pd.Timestamp('2026-01-01'), END_DATE_INCLUSIVE=pd.Timestamp('2026-12-31'),
            END_DATE_EXCLUSIVE=pd.Timestamp('2027-01-01'), SITE_TIMEZONE='America/New_York',
            POPULATIONS=['Primaries'], DOWNLOAD_MODE='priority', MEMO_STAGES=['Final'], MEMO_AUDIENCES=[],
            MEMO_APPROVED_BY_IC=['Yes'], MEMO_RECOMMENDATIONS=[],
            FILTERS_BY_POPULATION={'Primaries': {'Structure': []}},
            MAX_CANDIDATE_ATTEMPTS_PER_POPULATION=None, REQUIRE_VERIFIABLE_FILENAME=False,
            OUTPUT_ROOT=self.directory / 'output', PREVIEW_ONLY=False)
        self.settings.start()
        self.environment = patch.dict(os.environ, {'DEALCLOUD_SITE_URL': 'https://example.dealcloud.com',
            'DEALCLOUD_CLIENT_ID': 'offline-client', 'DEALCLOUD_CLIENT_SECRET': 'offline-secret'})
        self.environment.start()
    def tearDown(self):
        self.settings.stop()
        self.environment.stop()
        self.temp.cleanup()
    def run_engine(self, fake):
        with patch.object(engine, 'connect_to_dealcloud', return_value=fake), patch('sys.stdout', new_callable=io.StringIO):
            engine.main()
        manifest_path = next((self.directory / 'output').glob('*/run_settings.json'))
        return json.loads(manifest_path.read_text()), manifest_path.parent
    def event(self, stage='Final', date='2026-02-02', audience='internal', id='1', attachment=501):
        values = {'internal_value': {'id': attachment}, 'internal_display': 'memo.pdf', 'internal_field': 'InternalMemo'} if audience == 'internal' else {'client_ready_value': {'id': attachment}, 'client_ready_display': 'memo.pdf', 'client_ready_field': 'ClientReadyMemo'}
        e = engine.Event(source='CIMemo/InternalMemo', event_id=id, deal_id='101', event_date=pd.Timestamp(date), event_type=stage, stage_name=stage, recommendation='Approved', **values)
        return e
    def test_preview_never_downloads_or_requests_metadata(self):
        fake = FakeDC()
        engine.PREVIEW_ONLY = True
        manifest, output = self.run_engine(fake)
        self.assertEqual(fake.downloads, [])
        self.assertEqual(fake.metadata_calls, 0)
        self.assertFalse(list(output.rglob('*.pdf')))
        self.assertEqual(manifest['population_results'][0]['eligible_candidates'], 1)
        self.assertEqual(manifest['population_results'][0]['attempted_candidates'], 0)
        self.assertTrue(manifest['preview_only'])
    def test_download_uses_original_engine_selection(self):
        fake = FakeDC()
        manifest, output = self.run_engine(fake)
        self.assertEqual(len(fake.downloads), 1)
        self.assertEqual(fake.downloads[0]['entry_id'], '501')
        self.assertEqual(manifest['population_results'][0]['downloaded'], 1)
        self.assertEqual(len(list(output.rglob('*.pdf'))), 1)
    def test_server_query_and_parent_reads_are_scoped(self):
        fake = FakeDC()
        engine.PREVIEW_ONLY = True
        self.run_engine(fake)
        query = json.loads(fake.reads[0]['query'])
        self.assertIn('$and', query)
        self.assertEqual(fake.reads[0]['resolve'], 'id')
        parent = [r for r in fake.reads if r['object_id'] == 'Fund'][0]
        self.assertEqual(json.loads(parent['query'])['EntryId']['$in'], [101, 102])
    def test_priority_and_all_mode_order(self):
        engine.MEMO_STAGES = []
        h = engine.DealHistory('101', [self.event('Screening', '2026-03-01', id='2', attachment=502), self.event('Final', '2026-01-01', 'client', id='3', attachment=503), self.event('Final', '2026-02-01', id='4', attachment=504)])
        choices = engine.selected_memo_candidates(h)
        self.assertEqual([c[0].event_id for c in choices], ['4', '3', '2'])
        engine.DOWNLOAD_MODE = 'all'
        self.assertEqual([c[0].event_id for c in engine.selected_memo_candidates(h)], ['2', '4', '3'])
    def test_attachment_deduplication(self):
        h = engine.DealHistory('101', [self.event(id='1'), self.event(id='2')])
        self.assertEqual(len(engine.selected_memo_candidates(h)), 1)
    def test_approval_blank_is_not_no(self):
        self.assertIsNone(engine.normalize_ic_approval(None))
        self.assertEqual(engine.normalize_ic_approval(False), 'No')
        self.assertEqual(engine.normalize_ic_approval({'value': True}), 'Yes')
    def test_primary_approval_filter_does_not_apply_to_coinvestments(self):
        event = self.event()
        event.ic_approved = None
        self.assertEqual(len(engine.selected_memo_candidates(engine.DealHistory('101', [event]))), 1)
        event.source = 'DiligenceActivity/InternalMemo'
        self.assertEqual(len(engine.selected_memo_candidates(engine.DealHistory('101', [event]))), 0)
        engine.MEMO_APPROVED_BY_IC = []
        self.assertEqual(len(engine.selected_memo_candidates(engine.DealHistory('101', [event]))), 1)
    def test_supplementary_and_undated_exclusion(self):
        engine.MEMO_STAGES = []
        e = self.event(); e.internal_display = 'impact assessment.pdf'
        u = self.event(id='2'); u.event_date = pd.NaT
        self.assertEqual(engine.selected_memo_candidates(engine.DealHistory('101', [e, u])), [])
    def test_unknown_filename_strict_skip(self):
        e = self.event(); e.internal_display = None
        class NoMetadata(FakeDC):
            def download_attachment_metadata(self, **kwargs):
                raise ValueError('no metadata')
        fake = NoMetadata()
        engine.REQUIRE_VERIFIABLE_FILENAME = True
        c = engine.selected_memo_candidates(engine.DealHistory('101', [e]))[0]
        result = engine.save_candidate(fake, '101', 'Fund', c, self.directory, '999', {e.source: 'CIMemo'})
        self.assertTrue(result['Status'].startswith('SKIPPED'))
        self.assertEqual(fake.downloads, [])
    def test_population_attempt_cap(self):
        fake = FakeDC()
        engine.MEMO_APPROVED_BY_IC = []
        engine.MAX_CANDIDATE_ATTEMPTS_PER_POPULATION = 1
        manifest, _ = self.run_engine(fake)
        self.assertEqual(manifest['population_results'][0]['attempted_candidates'], 1)
    def test_population_error_is_recorded(self):
        fake = FakeDC()
        engine.FILTERS_BY_POPULATION = {'Primaries': {'UnknownField': ['x']}}
        manifest, output = self.run_engine(fake)
        self.assertIn('error', manifest['population_results'][0])
        self.assertTrue((output / 'Primaries' / 'population_error.txt').exists())
    def test_active_filter_matching_and_missing_field(self):
        frame = pd.DataFrame([{'EntryId': 1, 'FundName': 'One', 'AssetClass': 'Private Equity'}, {'EntryId': 2, 'FundName': 'Two', 'AssetClass': 'Credit'}])
        with patch('sys.stdout', new_callable=io.StringIO):
            selected = engine.filter_population(frame, ['FundName'], {'AssetClass': ['private-equity']})
        self.assertEqual(list(selected.index), ['1'])
        with self.assertRaises(KeyError):
            engine.filter_population(frame, ['FundName'], {'Missing': ['yes']})
    def test_csv_formula_sanitization(self):
        target = self.directory / 'test.csv'
        engine.write_csv([{'name': '=SUM(1,2)'}], target, ['name'])
        self.assertEqual(pd.read_csv(target).iloc[0]['name'], "'=SUM(1,2)")
    def test_timezone_date_window(self):
        self.assertEqual(engine.parse_event_date('2026-01-02T02:00:00Z'), pd.Timestamp('2026-01-01'))


class SupportTests(unittest.TestCase):
    def test_credentials_validation(self):
        valid = {'site_url': 'https://example.dealcloud.com/', 'client_id': 'abc', 'client_secret': 'secret-example'}
        parsed = parse_credentials(json.dumps(valid).encode())
        self.assertEqual(parsed['site_url'], 'https://example.dealcloud.com')
        for change in [{'site_url': 'http://example.com'}, {'client_secret': ''}, {'extra': 'no'}, {'site_url': 'https://user:pass@example.com'}, {'site_url': 'https://example.com/path'}]:
            with self.assertRaises(ValueError):
                parse_credentials(json.dumps({**valid, **change}).encode())
    def test_credentials_template_rejected(self):
        with self.assertRaises(ValueError):
            parse_credentials((ROOT / 'credentials.template.json').read_bytes())
    def test_fingerprint_changes_when_inputs_change(self):
        self.assertNotEqual(fingerprint({'a': 1}, 'UTC', {'key': 'x'}), fingerprint({'a': 2}, 'UTC', {'key': 'x'}))
        self.assertNotEqual(fingerprint({}, 'UTC', {'key': 'x'}), fingerprint({}, 'UTC', {'key': 'y'}))
    def test_one_value_per_line(self):
        self.assertEqual(lines('A, B\n C \n\nC'), ['A, B', 'C'])
    def test_stream_redacts_secret_split_between_writes(self):
        output = io.StringIO()
        stream = RedactedStream(output, ['abcSECRET'])
        stream.write('value=abc')
        stream.flush()
        stream.write('SECRET\n')
        stream.finish()
        self.assertEqual(output.getvalue(), 'value=[REDACTED]\n')
    def test_zip_excludes_credentials_and_logs(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as name:
            root = Path(name); output = root / 'output'; memos = output / 'Primaries' / 'Memos'; memos.mkdir(parents=True)
            (memos / 'memo.pdf').write_bytes(b'simulated')
            (output / 'run_settings.json').write_text('{}')
            (output / 'credentials.json').write_text('do not include')
            (output / 'worker.log').write_text('do not include')
            destination = create_archive(output, root / 'result.zip')
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(set(archive.namelist()), {'Primaries/Memos/memo.pdf', 'run_settings.json'})
    def test_output_path_cannot_escape_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as name:
            with self.assertRaises(ValueError):
                output_directory(Path(name), {'output': '../'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
