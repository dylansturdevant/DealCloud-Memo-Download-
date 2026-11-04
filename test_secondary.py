"""Regression tests for optional Secondary TeamDiscussionMemo coverage."""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import pandas as pd
import test_app

engine = test_app.engine


class SecondaryDC(test_app.FakeDC):
    def __init__(self, team_schema=True, team_returned=False, canonical_schema=True, canonical_returned=True):
        super().__init__()
        self.team_schema = team_schema
        self.canonical_schema = canonical_schema
        self.rows = [{'DealCloud Entry ID': 11, 'SecondaryDeal': 101,
                      'ICDate': '2026-01-15', 'Stage': 'Final', 'Recommendation': 'Approved',
                      'ClientMemo': None, 'TeamDiscussionRecommendation': 'Approved'}]
        if canonical_returned:
            self.rows[0]['INTERNALMEMO'] = {'id': 501, 'name': 'internal.pdf'}
        if team_returned:
            self.rows[0]['TeamDiscussionMemo'] = {'id': 601, 'name': 'team.pdf'}
    def get_fields(self, obj):
        if obj == 'SecondaryMemo':
            fields = ['SecondaryDeal', 'ICDate', 'Stage', 'Recommendation', 'ClientMemo', 'TeamDiscussionRecommendation']
            if self.canonical_schema:
                fields.append('INTERNALMEMO')
            if self.team_schema:
                fields.append('TeamDiscussionMemo')
            return [{'id': i+1, 'apiName': f, 'displayName': f} for i,f in enumerate(fields)]
        if obj == 'SecondaryDeal':
            return [{'id': 1, 'apiName': 'DealName', 'displayName': 'DealName'}]
        return super().get_fields(obj)
    def read_data(self, **kwargs):
        self.reads.append(kwargs)
        if kwargs['object_id'] == 'SecondaryMemo':
            return pd.DataFrame(self.rows)
        if kwargs['object_id'] == 'SecondaryDeal':
            ids = json.loads(kwargs['query'])['EntryId']['$in']
            return pd.DataFrame([{'DealCloud Entry ID': i, 'DealName': f'Secondary {i}'} for i in ids])
        raise AssertionError('Unexpected read')


class SecondaryTests(unittest.TestCase):
    setUp = test_app.DownloaderTests.setUp
    tearDown = test_app.DownloaderTests.tearDown
    run_engine = test_app.DownloaderTests.run_engine
    def configure(self, preview=True):
        engine.POPULATIONS = ['Secondaries']
        engine.FILTERS_BY_POPULATION = {'Secondaries': {}}
        engine.PREVIEW_ONLY = preview
    def test_optional_field_absent_from_returned_columns(self):
        self.configure()
        manifest, output = self.run_engine(SecondaryDC())
        row = manifest['population_results'][0]
        self.assertNotIn('error', row)
        self.assertEqual(row['eligible_candidates'], 1)
        self.assertTrue(row['source_warnings'])
        self.assertIn('TeamDiscussionMemo', row['source_warnings'][0])
    def test_optional_field_absent_from_schema(self):
        self.configure()
        dc = SecondaryDC(team_schema=False)
        manifest, _ = self.run_engine(dc)
        row = manifest['population_results'][0]
        self.assertNotIn('error', row)
        self.assertTrue(row['source_warnings'])
        self.assertNotIn('TeamDiscussionMemo', dc.reads[0]['fields'])
    def test_available_team_stream_is_not_removed(self):
        self.configure()
        manifest, _ = self.run_engine(SecondaryDC(team_returned=True))
        row = manifest['population_results'][0]
        self.assertEqual(row['eligible_candidates'], 2)
        self.assertEqual(row['source_warnings'], [])
    def test_required_canonical_missing_schema_still_fails(self):
        self.configure()
        manifest, _ = self.run_engine(SecondaryDC(canonical_schema=False))
        self.assertIn('error', manifest['population_results'][0])
    def test_required_canonical_missing_column_still_fails(self):
        self.configure()
        manifest, _ = self.run_engine(SecondaryDC(canonical_returned=False))
        self.assertIn('error', manifest['population_results'][0])
    def test_can_download_canonical_without_optional_stream(self):
        self.configure(preview=False)
        dc = SecondaryDC()
        manifest, output = self.run_engine(dc)
        row = manifest['population_results'][0]
        self.assertEqual(row['downloaded'], 1)
        self.assertTrue(row['source_warnings'])
        self.assertEqual(len(list(output.glob('*.pdf'))), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
