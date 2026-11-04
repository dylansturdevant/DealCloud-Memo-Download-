"""Regression coverage for SDK semicolon-delimited multi-reference cells."""
import unittest
from unittest.mock import patch
import pandas as pd
import test_app

engine = test_app.engine


class MultiReferenceTests(unittest.TestCase):
    def test_numeric_semicolon_ids(self):
        self.assertEqual(engine.extract_reference_ids('1001; 1002'), ['1001', '1002'])
    def test_whitespace_and_decimal_normalization(self):
        self.assertEqual(engine.extract_reference_ids(' 1001.0 ;1002 ; 1001 '), ['1001', '1002'])
    def test_numbers_in_filename_are_not_ids(self):
        for value in ['Fund 1001; Memo 1002.pdf', 'report-2026.pdf', '1001; unknown', '1001.pdf; 1002.pdf']:
            self.assertEqual(engine.extract_reference_ids(value), [])
    def test_alignment_keeps_supplementary_file_separate(self):
        pairs = engine.attachment_field_items('1001; 1002', 'Final Report.pdf; Supplementary Materials.pdf')
        self.assertEqual(len(pairs), 2)
        self.assertEqual(engine.first_reference_id(pairs[0][0]), '1001')
        self.assertEqual(pairs[0][1], 'Final Report.pdf')
        self.assertTrue(engine.is_supplementary_memo_text(pairs[1][1]))
    def make_history(self):
        event = engine.Event(source='DiligenceActivity/InternalMemo', event_id='123', deal_id='456',
            event_date=pd.Timestamp('2026-10-26'), event_type='Final', stage_name='Final', recommendation='Approved',
            internal_value='1001; 1002', internal_display='Final Report.pdf; Supplementary Materials.pdf', internal_field='InternalMemo')
        event.ic_approved = 'Yes'
        return engine.DealHistory('456', [event])
    def test_priority_uses_internal_attachment_and_skips_supplement(self):
        with patch.multiple(engine, START_DATE=pd.Timestamp('2026-01-01'), END_DATE_EXCLUSIVE=pd.Timestamp('2027-01-01'),
                            MEMO_STAGES=['Final'], MEMO_AUDIENCES=[], MEMO_APPROVED_BY_IC=['Yes'], MEMO_RECOMMENDATIONS=[], DOWNLOAD_MODE='priority'):
            choices = engine.selected_memo_candidates(self.make_history())
        self.assertEqual(len(choices), 1)
        self.assertEqual(engine.first_reference_id(choices[0][2]), '1001')
    def test_all_mode_still_excludes_supplement(self):
        with patch.multiple(engine, START_DATE=pd.Timestamp('2026-01-01'), END_DATE_EXCLUSIVE=pd.Timestamp('2027-01-01'),
                            MEMO_STAGES=['Final'], MEMO_AUDIENCES=[], MEMO_APPROVED_BY_IC=['Yes'], MEMO_RECOMMENDATIONS=[], DOWNLOAD_MODE='all'):
            choices = engine.selected_memo_candidates(self.make_history())
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0][4], 'Final Report.pdf')
    def test_raw_id_and_name_reads_build_correct_attachment(self):
        names = pd.DataFrame([{'EntryId': 123, 'Fund': 456, 'ICDate': '2026-10-26', 'Stage': 'Final', 'Recommendation': 'Approved', 'InternalMemo': 'Final Report.pdf; Supplementary Materials.pdf'}])
        raw = names.copy(); raw['InternalMemo'] = ['1001; 1002']
        events, issues = engine.build_events('DiligenceActivity/InternalMemo', names, raw, reference_candidates=['Fund'],
            field_overrides={'date': ['ICDate'], 'stage': ['Stage'], 'recommendation': ['Recommendation'], 'internal_memo': ['InternalMemo'], 'client_ready_memo': []})
        self.assertEqual(issues, [])
        events[0].ic_approved = 'Yes'
        with patch.multiple(engine, START_DATE=pd.Timestamp('2026-01-01'), END_DATE_EXCLUSIVE=pd.Timestamp('2027-01-01'),
                            MEMO_STAGES=['Final'], MEMO_AUDIENCES=[], MEMO_APPROVED_BY_IC=['Yes'], MEMO_RECOMMENDATIONS=[], DOWNLOAD_MODE='priority'):
            choices = engine.selected_memo_candidates(engine.DealHistory('456', events))
        self.assertEqual(engine.first_reference_id(choices[0][2]), '1001')


if __name__ == '__main__':
    unittest.main(verbosity=2)
