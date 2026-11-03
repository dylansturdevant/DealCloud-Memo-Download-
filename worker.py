"""Isolated local worker. Credentials arrive via stdin, never command arguments/files."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class RedactedStream:
    def __init__(self, stream, secrets):
        self.stream = stream
        self.secrets = [x for x in secrets if x]
        self.buffer = ''
    def write(self, value):
        # Buffer partial writes so a secret split across writes is still redacted.
        self.buffer += str(value)
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            self.stream.write(self.clean(line) + '\n')
            self.stream.flush()
        return len(value)
    def clean(self, text):
        for secret in self.secrets:
            text = text.replace(secret, '[REDACTED]')
        return text
    def flush(self):
        # Do not flush incomplete lines: they may contain partial credentials.
        self.stream.flush()
    def finish(self):
        if self.buffer:
            self.stream.write(self.clean(self.buffer))
            self.buffer = ''
        self.stream.flush()


def main():
    job_dir = Path(sys.argv[1]).resolve()
    # Workers can only write to a batch below the app's dedicated results roots.
    if job_dir.parent not in {(ROOT / 'Downloads').resolve(), (ROOT / 'Previews').resolve()} or not job_dir.is_dir():
        raise ValueError('Invalid run directory')
    reports = job_dir / 'Reports'
    reports.mkdir(exist_ok=True)
    payload = json.load(sys.stdin)
    credentials = payload.pop('credentials')
    secrets = [credentials['client_secret'], credentials['client_id']]
    out, err = RedactedStream(sys.stdout, secrets), RedactedStream(sys.stderr, secrets)
    sys.stdout, sys.stderr = out, err
    result = {'status': 'failed', 'preview': bool(payload['preview']), 'output': None}
    exit_code = 1
    try:
        # This environment belongs ONLY to this worker process, not the Streamlit server.
        for key, value in [('DEALCLOUD_SITE_URL', credentials['site_url']),
                           ('DEALCLOUD_CLIENT_ID', credentials['client_id']),
                           ('DEALCLOUD_CLIENT_SECRET', credentials['client_secret']),
                           ('DEALCLOUD_SITE_TIMEZONE', payload['timezone'])]:
            os.environ[key] = value
        import pandas as pd
        import downloader_engine as engine
        cfg = payload['settings']
        for name in ['DOWNLOAD_MODE', 'MEMO_STAGES', 'MEMO_AUDIENCES',
                     'MEMO_APPROVED_BY_IC', 'MEMO_RECOMMENDATIONS', 'POPULATIONS',
                     'FILTERS_BY_POPULATION', 'RECOMMENDATION_FIELD_BY_POPULATION',
                     'MAX_CANDIDATE_ATTEMPTS_PER_POPULATION', 'REQUIRE_VERIFIABLE_FILENAME']:
            setattr(engine, name, cfg[name])
        engine.START_IC_DATE = cfg['START_IC_DATE']
        engine.END_IC_DATE = cfg['END_IC_DATE']
        engine.START_DATE = pd.Timestamp(cfg['START_IC_DATE']).normalize()
        engine.END_DATE_INCLUSIVE = pd.Timestamp(cfg['END_IC_DATE']).normalize()
        engine.END_DATE_EXCLUSIVE = engine.END_DATE_INCLUSIVE + pd.Timedelta(days=1)
        engine.OUTPUT_ROOT = job_dir
        engine.FIXED_OUTPUT_DIRECTORY = job_dir
        engine.PREVIEW_ONLY = payload['preview']
        engine.main()
        manifests = list(engine.OUTPUT_ROOT.glob('Reports/run_settings.json'))
        if len(manifests) != 1:
            raise RuntimeError('Expected one run manifest')
        manifest = json.loads(manifests[0].read_text(encoding='utf-8'))
        results = manifest.get('population_results', [])
        if len(results) != len(cfg['POPULATIONS']):
            raise RuntimeError('Run did not report all selected populations')
        result.update(output='.',
                      population_results=results)
        # Engine may catch a population error and continue; don't call that full success.
        result['status'] = 'partial' if any('error' in row for row in results) else 'completed'
        exit_code = 0 if result['status'] == 'completed' else 2
    except Exception as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        result['error'] = err.clean(f'{type(exc).__name__}: {exc}')
    finally:
        # Defensive redaction for diagnostic text produced by SDK exceptions.
        # Binary memo contents are not opened or modified.
        for path in reports.rglob('*'):
            if path.is_file() and 'Memos' not in path.parts and path.suffix.lower() in {'.csv', '.json', '.txt'}:
                try:
                    text = path.read_text(encoding='utf-8-sig')
                    clean = out.clean(text)
                    if clean != text:
                        path.write_text(clean, encoding='utf-8-sig' if path.suffix == '.csv' else 'utf-8')
                except (UnicodeError, OSError):
                    pass
        result = json.loads(out.clean(json.dumps(result)))
        (reports / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        out.finish()
        err.finish()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
