"""Worker dispatch regression tests; no subprocess, network, or credentials used."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import worker
import test_app

ROOT=Path(__file__).resolve().parent


class WorkerDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT)
        self.home=Path(self.temp.name)
        self.job=self.home/'DealCloud Memos'/'Previews'/'Excel batch';self.job.mkdir(parents=True)
        self.credentials={'site_url':'https://example.dealcloud.com','client_id':'fake-client-for-test','client_secret':'fake-secret-for-test'}
    def tearDown(self):self.temp.cleanup()
    def call(self,executor,preview=True):
        module=types.ModuleType('excel_executor');module.run_excel=executor
        payload={'action':'excel','preview':preview,'timezone':'America/New_York','settings':{'rows':[]},'credentials':self.credentials}
        with patch.object(worker.Path,'home',return_value=self.home),patch.dict(sys.modules,{'downloader_engine':test_app.engine,'excel_executor':module}),patch.object(test_app.engine,'connect_to_dealcloud',return_value='fake-dc'),patch.object(sys,'stdin',io.StringIO(json.dumps(payload))),patch.object(sys,'argv',['worker.py',str(self.job)]),patch.object(sys,'stdout',io.StringIO()),patch.object(sys,'stderr',io.StringIO()),patch.dict(os.environ,{},clear=False):
            code=worker.main()
        return code,json.loads((self.job/'Reports'/'result.json').read_text())
    def test_excel_worker_preview_dispatch(self):
        calls=[]
        def execute(dc,engine,settings,output,preview):
            calls.append((dc,output,preview))
            return {'status':'completed','output':'.','population_results':[],'excel_summary':{'preview':preview}}
        code,result=self.call(execute)
        self.assertEqual(code,0);self.assertTrue(result['excel_summary']['preview'])
        self.assertEqual(calls,[('fake-dc',self.job,True)])
    def test_excel_population_partial_remains_partial(self):
        code,result=self.call(lambda *args:{'status':'partial','output':'.','population_results':[{'population':'Primaries','error':'schema issue'}]})
        self.assertEqual(code,2);self.assertEqual(result['status'],'partial')
    def test_excel_exception_and_reports_are_masked(self):
        secret=self.credentials['client_secret']
        def execute(dc,engine,settings,output,preview):
            (output/'Reports'/'excel_results.csv').write_text('error,'+secret)
            raise ValueError(secret)
        code,result=self.call(execute)
        self.assertEqual(code,1);self.assertNotIn(secret,json.dumps(result))
        self.assertNotIn(secret,(self.job/'Reports'/'excel_results.csv').read_text())
    def test_invalid_worker_directory_rejected(self):
        other=self.home/'wrong';other.mkdir()
        with patch.object(worker.Path,'home',return_value=self.home),patch.object(sys,'argv',['worker.py',str(other)]):
            with self.assertRaises(ValueError):worker.main()


if __name__=='__main__':unittest.main(verbosity=2)
