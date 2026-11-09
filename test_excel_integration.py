"""Cross-module tests with the real shared engine and a fake SDK transport."""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import pandas as pd
import test_app
import worker
from excel_executor import run_excel
from ui_support import create_archive, excel_preview_usable

ROOT=Path(__file__).resolve().parent
engine=test_app.engine


class Transport:
    def __init__(self):self.downloads=[];self.metadata=0
    def get_fields(self,obj):
        if obj=='Attachment':return [{'id':'2105','apiName':'File','displayName':'File','fieldType':13}]
        names=['FundName'] if obj=='Fund' else ['Fund','ICDate','Stage','InternalMemo','ClientReadyMemo','ClientVersionofMemo']
        return [{'id':i+1,'apiName':name,'displayName':name} for i,name in enumerate(names)]
    def read_data(self,**kwargs):
        query=json.loads(kwargs['query'])
        if kwargs['object_id']=='Fund':
            assert query=={'FundName':{'$in':['Synthetic Fund']}}
            return pd.DataFrame([{'DealCloud Entry ID':101,'FundName':'Synthetic Fund'}])
        assert query=={'Fund':{'$in':[101]}}
        row={'DealCloud Entry ID':201,'Fund':101,'ICDate':'2026-03-01','Stage':'Follow-On',
             'InternalMemo':'301; 302','ClientReadyMemo':None,'ClientVersionofMemo':None}
        if kwargs['resolve']=='name':row['InternalMemo']='Follow-On Memo.pdf; Supplementary materials.pdf'
        return pd.DataFrame([row])
    def download_attachment_metadata(self,**kwargs):self.metadata+=1;return {'fileName':'Follow-On Memo.pdf'}
    def download_file(self,**kwargs):
        self.downloads.append(str(kwargs['entry_id']));Path(kwargs['output_path']).write_bytes(b'%PDF-synthetic')


def settings():
    return {'rows':[{'source_row':2,'deal_name':'Synthetic Fund','population':'Primaries','client':'Synthetic Client','quarters':['Q1 2026','Q2 2026'],'memo_type':'Use app setting'}],
            'default_policy':'Priority fallback','audience':'Internal then Client','quarter_precedence':'Q1','strict_filename':True,'max_attempts':5}


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.base=Path(self.temp.name)
        self.patcher=patch('tempfile.tempdir',str(self.base));self.patcher.start()
        self.pause=patch.object(engine,'ATTACHMENT_REQUEST_PAUSE_SECONDS',0);self.pause.start()
    def tearDown(self):self.pause.stop();self.patcher.stop();self.temp.cleanup()
    def execute(self,preview):
        output=self.base/'batch';output.mkdir();(output/'Reports').mkdir();(output/'Reports'/'worker.log').write_text('synthetic log')
        transport=Transport()
        with contextlib.redirect_stdout(io.StringIO()):result=run_excel(transport,engine,settings(),output,preview)
        return output,transport,result
    def test_real_engine_preview_with_precreated_worker_reports(self):
        output,transport,result=self.execute(True)
        self.assertEqual(result['status'],'completed');self.assertTrue(excel_preview_usable(result))
        self.assertEqual(transport.downloads,[]);self.assertEqual(transport.metadata,0)
        with (output/'Reports'/'excel_results.csv').open(encoding='utf-8-sig') as stream:rows=list(csv.DictReader(stream))
        self.assertEqual(rows[0]['Memo Stage'],'Follow-On');self.assertEqual(rows[1]['Status'],'SUPPRESSED: Q1 precedence')
    def test_real_download_route_stage_and_portable_zip(self):
        output,transport,result=self.execute(False)
        self.assertEqual(transport.downloads,['301'])
        self.assertEqual(result['excel_summary']['memo_copies_written'],1)
        with (output/'Reports'/'downloaded_files.csv').open(encoding='utf-8-sig') as stream:row=next(csv.DictReader(stream))
        self.assertFalse(Path(row['File']).is_absolute());self.assertTrue((output/row['File']).is_file());self.assertIn('Follow-On',row['File'])
        archive=create_archive(output,output/'Reports'/'results.zip')
        with zipfile.ZipFile(archive) as zipped:
            self.assertIn(row['File'],zipped.namelist());self.assertNotIn('Reports/worker.log',zipped.namelist())
            self.assertIn('Reports/excel_results.csv',zipped.namelist())
    def test_worker_to_real_excel_executor(self):
        home=self.base/'home';directory=home/'DealCloud Memos'/'Previews'/'Excel job';directory.mkdir(parents=True)
        credentials={'site_url':'https://example.dealcloud.com','client_id':'fake-id','client_secret':'fake-secret'}
        payload={'action':'excel','preview':True,'settings':settings(),'credentials':credentials,'timezone':'America/New_York'}
        with patch.object(worker.Path,'home',return_value=home),patch.dict(sys.modules,{'downloader_engine':engine}),patch.object(engine,'connect_to_dealcloud',return_value=Transport()),patch.object(sys,'stdin',io.StringIO(json.dumps(payload))),patch.object(sys,'argv',['worker.py',str(directory)]),patch.object(sys,'stdout',io.StringIO()),patch.object(sys,'stderr',io.StringIO()),patch.dict(os.environ,{},clear=False):
            code=worker.main()
        self.assertEqual(code,0)
        result=json.loads((directory/'Reports'/'result.json').read_text())
        self.assertTrue(excel_preview_usable(result));self.assertEqual(result['action'],'excel')
    def test_coverage_warning_preview_can_authorize_but_read_error_cannot(self):
        result={'status':'partial','population_results':[{'population':'Primaries','source_warnings':['optional unavailable']}],
                'excel_summary':{'preview':True,'eligible_candidates':1}}
        self.assertTrue(excel_preview_usable(result))
        result['population_results'][0]['error']='read failed'
        self.assertFalse(excel_preview_usable(result))
    def test_zero_candidates_and_download_result_do_not_authorize(self):
        result={'status':'partial','population_results':[{'population':'Primaries'}],'excel_summary':{'preview':True,'eligible_candidates':0}}
        self.assertFalse(excel_preview_usable(result));result['excel_summary'].update(preview=False,eligible_candidates=1)
        self.assertFalse(excel_preview_usable(result))


if __name__=='__main__':unittest.main(verbosity=2)
