"""Offline workbook parser and real-top-level UI smoke tests using a stub."""
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from openpyxl import Workbook
import excel_input as inputs
import test_ui_smoke

ROOT=Path(__file__).resolve().parent


def workbook(rows, sheet='Deals'):
    w=Workbook();w.active.title=sheet
    for row in rows:w.active.append(row)
    handle=io.BytesIO();w.save(handle);return handle.getvalue()


class ExcelInputTests(unittest.TestCase):
    def test_template_readable_and_has_expected_columns(self):
        headers,rows=inputs.read_sheet(inputs.template_bytes(),'Deals')
        self.assertEqual(headers,['Deal Name','Population','Client Name','Quarter','Memo Type'])
        self.assertEqual(len(rows),1)
    def test_normal_workbook_maps_mixed_populations_and_policies(self):
        data=workbook([['Deal Name','Structure','Client Name','Quarters','Memo Type'],['Exact Fund','Primary Partnership','Client','Q1 2026; Q2 2026','Final'],['Exact Deal','Direct Transaction','','Q2 2026','Follow-on']])
        headers,records=inputs.read_sheet(data,'Deals')
        rows,errors=inputs.validate_rows(records,inputs.suggested_mapping(headers),'Secondaries')
        self.assertFalse(errors);self.assertEqual(rows[0]['population'],'Primaries')
        self.assertEqual(rows[1]['population'],'CoInvestments');self.assertEqual(rows[1]['memo_type'],'Follow-On')
        self.assertEqual(rows[0]['quarters'],['Q1 2026','Q2 2026'])
    def test_deal_name_only_is_supported(self):
        headers,records=inputs.read_sheet(workbook([['Deal Name'],['Exact Fund']]),'Deals')
        rows,errors=inputs.validate_rows(records,inputs.suggested_mapping(headers),'Primaries')
        self.assertFalse(errors);self.assertEqual(rows[0]['memo_type'],'Use app setting');self.assertEqual(rows[0]['quarters'],[])
    def test_unknown_population_or_policy_is_not_silently_defaulted(self):
        headers,records=inputs.read_sheet(workbook([['Deal Name','Population','Memo Type'],['Exact Fund','Made Up','Final-ish']]),'Deals')
        rows,errors=inputs.validate_rows(records,inputs.suggested_mapping(headers),'Primaries')
        self.assertFalse(rows);self.assertEqual(len(errors),1)
    def test_formula_in_mapped_cell_rejected(self):
        headers,records=inputs.read_sheet(workbook([['Deal Name'],['="Fund"']]),'Deals')
        rows,errors=inputs.validate_rows(records,inputs.suggested_mapping(headers),'Primaries')
        self.assertFalse(rows);self.assertIn('formulas',errors[0]['Issue'])
    def test_formula_in_ignored_column_not_used(self):
        headers,records=inputs.read_sheet(workbook([['Deal Name','Ignored'],['Exact Fund','=1+1']]),'Deals')
        rows,errors=inputs.validate_rows(records,inputs.suggested_mapping(headers),'Primaries')
        self.assertFalse(errors);self.assertEqual(len(rows),1)
    def test_duplicate_headers_rejected(self):
        with self.assertRaises(ValueError):inputs.read_sheet(workbook([['Deal Name','Deal Name'],['A','B']]),'Deals')
    def test_bad_quarter_is_reported(self):
        with self.assertRaises(ValueError):inputs.parse_quarters('../outside')
        self.assertEqual(inputs.parse_quarters('Q3 2026;Q4 2026'),['Q3 2026','Q4 2026'])
    def test_unknown_sheet_and_invalid_file_rejected(self):
        with self.assertRaises(ValueError):inputs.read_sheet(workbook([['Deal Name'],['A']]),'Not There')
        with self.assertRaises(ValueError):inputs.sheet_names(b'not a zip')
    def test_header_row_and_actual_row_number_preserved(self):
        data=workbook([['Title'],[],['Deal Name'],['Exact Fund']])
        headers,rows=inputs.read_sheet(data,'Deals',3)
        self.assertEqual(rows[0]['source_row'],4)
    def test_uploaded_workbook_size_limit(self):
        with self.assertRaises(ValueError):inputs.sheet_names(b'x'*(inputs.MAX_UPLOAD_BYTES+1))


class StopUI(Exception):
    pass


class ExcelUIStub(test_ui_smoke.Stub):
    def __init__(self, excel=None, credentials=False, approved=False):
        super().__init__(upload=credentials)
        self.excel=excel
        if approved:self.session_state['excel_approved_preview']='not-current'
    def radio(self,label,options,**kwargs):
        return 'Excel deal list' if label=='Input mode' else options[kwargs.get('index',0)]
    def selectbox(self,label,options,**kwargs):
        return options[kwargs.get('index',0)]
    def file_uploader(self,label,**kwargs):
        data=None
        if label=='Private DealCloud credentials JSON' and self.upload:
            data=json.dumps(test_ui_smoke.CREDENTIALS).encode()
        if label=='Deal-list workbook (.xlsx)':data=self.excel
        return types.SimpleNamespace(size=len(data),getvalue=lambda:data) if data is not None else None
    def stop(self):
        raise StopUI()


class ExcelUIStartupTests(unittest.TestCase):
    def execute(self,**kwargs):
        import runpy
        stub=ExcelUIStub(**kwargs)
        with patch.dict(sys.modules,{'streamlit':stub}):
            # The UI module must bind to this stub each time.
            old=sys.modules.pop('excel_ui',None)
            try:
                try:runpy.run_path(str(ROOT/'app.py'),run_name='excel_ui_smoke')
                except StopUI:pass
            finally:
                sys.modules.pop('excel_ui',None)
                if old is not None:sys.modules['excel_ui']=old
        return stub
    def test_excel_mode_empty_startup(self):
        stub=self.execute()
        self.assertTrue(stub.buttons['Preview Excel list']['disabled'])
        self.assertTrue(stub.buttons['Download Excel-list memos']['disabled'])
    def test_valid_workbook_enables_preview_not_download(self):
        data=workbook([['Deal Name','Population'],['Exact Fund','Primaries']])
        stub=self.execute(excel=data,credentials=True)
        self.assertFalse(stub.buttons['Preview Excel list']['disabled'])
        self.assertTrue(stub.buttons['Download Excel-list memos']['disabled'])
    def test_invalid_rows_block_preview(self):
        stub=self.execute(excel=workbook([['Deal Name','Memo Type'],['Exact Fund','Wrong']]),credentials=True)
        self.assertTrue(stub.buttons['Preview Excel list']['disabled'])
    def test_stale_preview_does_not_authorize_new_upload(self):
        stub=self.execute(excel=workbook([['Deal Name'],['Exact Fund']]),credentials=True,approved=True)
        self.assertTrue(stub.buttons['Download Excel-list memos']['disabled'])


if __name__=='__main__':unittest.main(verbosity=2)
