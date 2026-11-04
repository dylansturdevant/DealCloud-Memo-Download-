"""Offline top-level UI regression checks using a lightweight Streamlit stub.
These execute app.py but do not replace testing in a real Streamlit browser.
"""
import datetime as dt
import io
import json
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from ui_support import fingerprint

ROOT = Path(__file__).resolve().parent
CREDENTIALS = {'site_url': 'https://example.dealcloud.com', 'client_id': 'offline-id', 'client_secret': 'offline-secret'}


class Stub(types.ModuleType):
    def __init__(self, upload=False, loaded=False):
        super().__init__('streamlit')
        self.session_state = {}
        self.buttons = {}
        self.upload = upload
        self.populations = ['Primaries', 'CoInvestments', 'Secondaries']
        if loaded:
            settings = {'START_IC_DATE': '2026-01-01', 'END_IC_DATE': dt.datetime.now(ZoneInfo('America/New_York')).date().isoformat(), 'POPULATIONS': self.populations}
            signature = fingerprint(settings, 'America/New_York', CREDENTIALS)
            from filter_options import FILTER_FIELDS
            self.session_state['filter_cache'] = {'signature': signature, 'options': {
                p: {'values': {field: default for field, default in fields}, 'unavailable': {}, 'linked_parents': 1, 'memo_rows': 1}
                for p, fields in FILTER_FIELDS.items()}}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def __getattr__(self, name):
        return lambda *args, **kwargs: None
    def columns(self, count):
        return [self] * (count if isinstance(count, int) else len(count))
    def expander(self, *args, **kwargs):
        return self
    def fragment(self, **kwargs):
        return lambda function: function
    def file_uploader(self, *args, **kwargs):
        if not self.upload:
            return None
        data = json.dumps(CREDENTIALS).encode()
        return types.SimpleNamespace(size=len(data), getvalue=lambda: data)
    def text_input(self, label, value='', **kwargs):
        return value
    def text_area(self, label, value='', **kwargs):
        return value
    def date_input(self, label, value=None, **kwargs):
        return value
    def checkbox(self, label, value=False, **kwargs):
        return value
    def multiselect(self, label, options, default=None, **kwargs):
        return self.populations if label == 'Populations' else list(default or [])
    def radio(self, label, options, **kwargs):
        return options[0]
    selectbox = radio
    def number_input(self, label, value=None, **kwargs):
        return value
    def button(self, label, **kwargs):
        self.buttons[label] = kwargs
        return False


class UIStartupTests(unittest.TestCase):
    def execute(self, upload=False, loaded=False):
        stub = Stub(upload=upload, loaded=loaded)
        with patch.dict(sys.modules, {'streamlit': stub}):
            namespace = runpy.run_path(str(ROOT / 'app.py'), run_name='ui_smoke_test')
        return stub, namespace
    def test_startup_without_credentials(self):
        stub, namespace = self.execute()
        self.assertFalse(namespace['option_valid'])
        self.assertTrue(stub.buttons['Preview eligible deals and counts']['disabled'])
    def test_credentials_can_load_options_before_options_exist(self):
        stub, namespace = self.execute(upload=True)
        self.assertTrue(namespace['option_valid'])
        self.assertFalse(namespace['options_ready'])
        self.assertFalse(stub.buttons['Load / Refresh filter options from DealCloud']['disabled'])
        self.assertTrue(stub.buttons['Preview eligible deals and counts']['disabled'])
    def test_loaded_options_enable_preview_for_all_populations(self):
        stub, namespace = self.execute(upload=True, loaded=True)
        self.assertTrue(namespace['options_ready'])
        self.assertTrue(namespace['valid'])
        self.assertFalse(stub.buttons['Preview eligible deals and counts']['disabled'])
        self.assertEqual(namespace['filters']['CoInvestments']['AssetClass'], ['Private Equity'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
