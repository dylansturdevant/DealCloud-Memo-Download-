"""Local-only Streamlit interface for the supplied DealCloud v11 downloader."""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from ui_support import parse_credentials, fingerprint, lines, output_directory, create_archive, batch_name, allocate_batch

ROOT = Path(__file__).resolve().parent
DOWNLOADS = ROOT / 'Downloads'
PREVIEWS = ROOT / 'Previews'
st.set_page_config(page_title='DealCloud Memo Downloader', page_icon='📄', layout='wide')
st.title('DealCloud Memo Downloader')
st.caption('Local browser interface · Preview first · Read-only DealCloud operations in the supplied downloader')
st.warning('Local use only. Do not expose this app to the internet or a shared network without an IT security review. No live tenant connection has been tested in this package.')


def active_job():
    job = st.session_state.get('job')
    return job if job and job['process'].poll() is None else None


def launch(preview, settings, timezone, credentials, signature):
    if active_job():
        raise RuntimeError('A job is already running in this browser session.')
    parent = PREVIEWS if preview else DOWNLOADS
    job_dir = allocate_batch(parent, batch_name(settings, dt.datetime.now(ZoneInfo(timezone))))
    (job_dir / 'Reports').mkdir()
    # No credential file, settings file containing credentials, or secret command argument.
    log_handle = (job_dir / 'Reports' / 'worker.log').open('w', encoding='utf-8')
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    process = None
    try:
        process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'worker.py'), str(job_dir)],
            stdin=subprocess.PIPE, stdout=log_handle, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', cwd=str(ROOT), **kwargs)
        payload = {'preview': preview, 'settings': settings, 'timezone': timezone,
                   'credentials': credentials}
        process.stdin.write(json.dumps(payload))
        process.stdin.close()
    except Exception:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        raise
    finally:
        log_handle.close()
    st.session_state['job'] = {'process': process, 'directory': str(job_dir),
                              'preview': preview, 'signature': signature, 'handled': False}
    if not preview:
        st.session_state.pop('approved_preview', None)


left, right = st.columns([1, 2])
with left:
    st.subheader('1 · Connection')
    st.write('Upload your own JSON credentials file. It is used in memory and is not copied into the run output.')
    key = st.session_state.get('upload_key', 0)
    uploaded = st.file_uploader('DealCloud credentials (.json)', type=['json'], key=f'credentials_{key}',
        help='Exactly three keys: site_url, client_id, client_secret. Keep this plaintext file secure.')
    credentials = None
    if uploaded is not None:
        try:
            if uploaded.size > 65536:
                raise ValueError('Credentials file must be smaller than 64 KiB.')
            credentials = parse_credentials(uploaded.getvalue())
            st.success('Credentials file format accepted. Authentication is checked during preview.')
            st.caption('Client ID and secret are deliberately not displayed.')
        except ValueError as exc:
            st.error(str(exc))
    if st.button('Clear uploaded credentials', disabled=bool(active_job())):
        # Rotate the widget key; Streamlit removes the old widget state on rerun.
        st.session_state['upload_key'] = key + 1
        st.session_state.pop('approved_preview', None)
        st.rerun()
    st.download_button('Download blank credentials template',
        data=(ROOT / 'credentials.template.json').read_bytes(),
        file_name='dealcloud_credentials.template.json', mime='application/json')
    st.caption('The template has placeholders only. Never email a completed credentials file or commit it to source control. Clearing the upload does not erase your original file from disk.')
    timezone = st.text_input('DealCloud site timezone', value='America/New_York')
    try:
        zone = ZoneInfo(timezone.strip())
        today = dt.datetime.now(zone).date()
        timezone_ok = True
    except (ValueError, KeyError):
        st.error('Enter a valid IANA timezone, such as America/New_York.')
        today = dt.date.today()
        timezone_ok = False

with right:
    st.subheader('2 · Memo selection')
    d1, d2 = st.columns(2)
    start = d1.date_input('Start IC date (inclusive)', value=dt.date(2026, 1, 1))
    use_today = d2.checkbox('End today in site timezone', value=True)
    end = d2.date_input('End IC date (inclusive)', value=today, disabled=use_today)
    if use_today:
        end = today
    populations = st.multiselect('Populations', ['Primaries', 'CoInvestments', 'Secondaries'], default=['Primaries'])
    c1, c2 = st.columns(2)
    mode_label = c1.radio('Download mode', ['One priority-selected memo per deal', 'All eligible memos'])
    mode = 'priority' if mode_label.startswith('One') else 'all'
    stages = c2.multiselect('Memo stages (empty = all supported)', ['Final', 'Screening', 'Follow-On', 'Update'], default=['Final'])
    audiences = st.multiselect('Audiences (empty = Internal and Client)', ['Internal', 'Client'])
    approval = st.selectbox('Primaries only · Approved by IC?',
        ['Yes', 'No', 'Yes or No (exclude blanks)', 'Any (include blank/unknown)'])
    approved = {'Yes': ['Yes'], 'No': ['No'], 'Yes or No (exclude blanks)': ['Yes', 'No'],
                'Any (include blank/unknown)': []}[approval]
    recommendations = lines(st.text_area('Optional recommendation values — one exact label per line',
        help='Empty = no recommendation filter. Spaces, punctuation and case are normalized; similar labels are not guessed.'))
    strict = st.checkbox('Skip files whose filenames cannot be verified', value=False)
    limited = st.checkbox('Limit candidate attempts per population (recommended for initial tests)', value=True)
    cap = int(st.number_input('Maximum candidate attempts per population', min_value=1, max_value=100000,
                             value=5, step=1, disabled=not limited)) if limited else None
    st.caption('The initial attempt cap defaults to 5 for safety (the supplied script default was unlimited). It is not a byte, storage, or API-read limit. Preview still counts all eligible candidates before this cap.')

st.subheader('3 · Parent-record filters')
st.caption('One tenant value per line. Empty = unrestricted. OR within a field, AND across active fields. These filter linked parent records, not memo calculations. Values are not fetched as dropdowns.')
filter_fields = {
    'Primaries': [('Structure', ''), ('AssetClass', ''), ('Strategy', ''), ('SubStrategy', '')],
    'CoInvestments': [('Structure Type', ''), ('AssetClass', 'Private Equity'), ('Strategy', ''), ('SubStrategy', ''), ('Status', '')],
    'Secondaries': [('Structure', 'Secondary Transaction'), ('AssetClass', ''), ('Strategy_1', ''), ('SubStrategy', ''), ('Status', '')],
}
filters = {}
for population in populations:
    with st.expander(f'{population} filters', expanded=len(populations) == 1):
        if population == 'Primaries':
            st.caption('Uses Fund → DiligenceActivity. No verified Fund Status alias is assumed. An unrestricted Structure includes all linked Fund structures, not only Primary Partnership.')
        if population == 'Secondaries':
            st.caption('Strategy_1 is the active Strategy API field from the supplied mapping, not the legacy Strategy field.')
        columns = st.columns(3)
        filters[population] = {}
        for i, (field, default) in enumerate(filter_fields[population]):
            value = columns[i % 3].text_area(field, value=default, key=f'filter_{population}_{field}', height=100)
            filters[population][field] = lines(value)
        extra = st.text_area('Optional additional parent filters (JSON object of field names to lists)', value='{}', key=f'extra_{population}',
            help='Advanced: actual API/display field names only. Example: {"YourField": ["YourValue"]}. Active missing fields fail rather than being silently ignored.')
        try:
            extras = json.loads(extra)
            if not isinstance(extras, dict) or any(not isinstance(k, str) or not k.strip() or not isinstance(v, list)
                  or any(not isinstance(x, str) or not x.strip() for x in v) for k, v in extras.items()):
                raise ValueError()
            if set(extras).intersection(filters[population]):
                raise ValueError()
            filters[population].update(extras)
        except (ValueError, TypeError):
            st.error(f'{population}: additional filters must be a valid JSON object with nonempty field names and lists of nonempty strings; do not repeat fields shown above.')
            filters[population]['__invalid__'] = True

with st.expander('Selection rules and limitations'):
    st.markdown('''- Priority: Internal Final → Client Final → Internal Screening → Client Screening → Internal Follow-On → Client Follow-On → Internal Update → Client Update; newest IC date within each tier. Stops after one successful file per parent.
- All mode downloads eligible candidates without the priority stop. Repeated attachment IDs are deduplicated per parent, not across populations.
- Update includes Addendum. Undated and out-of-window events are excluded.
- Approved-by-IC Yes/No applies only to Primaries. Blank/unknown is not No.
- Filename and stage checks exclude known supplementary material; file contents are not inspected. Unknown filenames may be downloaded as `.bin` for review unless strict mode is enabled.
- Preview reads tenant schema, memo records and linked parents; it does not request attachment metadata or download files. Later metadata checks can reduce actual downloads.
- A download makes fresh API reads: changes in DealCloud after preview can change the result. Preview is not a frozen snapshot.
- Attempt caps do not constrain data-read volume or bytes. Preview counts are candidates, not promised successful downloads.
- Downloads and logs remain on this computer until you delete their run folder. Closing the browser does not reliably stop a running worker.''')

settings = {'START_IC_DATE': start.isoformat(), 'END_IC_DATE': end.isoformat(),
    'DOWNLOAD_MODE': mode, 'MEMO_STAGES': stages, 'MEMO_AUDIENCES': audiences,
    'MEMO_APPROVED_BY_IC': approved, 'MEMO_RECOMMENDATIONS': recommendations,
    'POPULATIONS': populations, 'FILTERS_BY_POPULATION': filters,
    'RECOMMENDATION_FIELD_BY_POPULATION': {p: 'Recommendation' for p in ['Primaries', 'CoInvestments', 'Secondaries']},
    'MAX_CANDIDATE_ATTEMPTS_PER_POPULATION': cap, 'REQUIRE_VERIFIABLE_FILENAME': strict}
valid = bool(credentials and timezone_ok and populations and start <= end
             and not any('__invalid__' in f for f in filters.values()))
if start > end:
    st.error('Start IC date must be on or before end IC date.')
signature = fingerprint(settings, timezone.strip(), credentials) if valid else None
preview_matches = valid and st.session_state.get('approved_preview') == signature
st.subheader('4 · Preview, then download')
if valid:
    st.caption('Downloads save to: ' + str(DOWNLOADS / batch_name(settings, dt.datetime.now(zone))))
    st.caption('Memos go directly inside the batch folder; reports are separate. Preview batches are stored under Previews. Name shown is illustrative until the job starts.')
b1, b2 = st.columns(2)
if b1.button('Preview eligible deals and counts', type='primary', disabled=not valid or bool(active_job())):
    try:
        launch(True, settings, timezone.strip(), credentials, signature)
        st.rerun()
    except (OSError, RuntimeError) as exc:
        st.error(f'Unable to start local worker: {type(exc).__name__}. Check Python and folder permissions.')
confirmed = b2.checkbox('I have reviewed the preview and authorize downloading to this computer', value=False)
if b2.button('Download memos', disabled=not (preview_matches and confirmed) or bool(active_job())):
    try:
        launch(False, settings, timezone.strip(), credentials, signature)
        st.rerun()
    except (OSError, RuntimeError):
        st.error('Unable to start the local worker. Check Python and folder permissions.')
if not preview_matches:
    st.caption('A successful preview with the current settings and credentials is required before downloading.')


@st.fragment(run_every=1)
def job_panel():
    job = st.session_state.get('job')
    if not job:
        return
    process = job['process']
    directory = Path(job['directory'])
    running = process.poll() is None
    st.subheader(('Preview' if job['preview'] else 'Download') + (' running…' if running else ' results'))
    if running:
        st.info('Working locally. Settings edits will not change this in-flight job.')
        if st.button('Stop current job'):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            job['stopped'] = True
            job['handled'] = True
            st.session_state.pop('approved_preview', None)
            st.rerun()
    if job.get('stopped'):
        st.warning('Stopped. Partial files may remain. Treat this run as incomplete and review or delete its local folder. Prior runs are untouched.')
    result_path = directory / 'Reports' / 'result.json'
    result = None
    if not running and result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            st.warning('Result status could not be read. Review the local log.')
    if not running and not job.get('handled'):
        job['handled'] = True
        if result and result.get('status') == 'completed' and job['preview'] and not job.get('stopped'):
            st.session_state['approved_preview'] = job['signature']
        st.rerun()
    if result:
        status = result.get('status')
        if status == 'completed' and not job.get('stopped'):
            st.success('Preview completed — no attachment files downloaded.' if job['preview'] else 'Download run completed. Review counts and candidate-level skips/failures below.')
        elif status == 'partial':
            st.warning('One or more populations failed. Review errors and any partial results. A partial preview does not authorize downloading.')
        elif status == 'failed':
            st.error('Run failed. Review the redacted log below.')
        results = result.get('population_results', [])
        if results:
            st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)
        output = output_directory(directory, result)
        if output:
            for population in ['Primaries', 'CoInvestments', 'Secondaries']:
                selected_populations = [r.get('population') for r in results]
                report_folder = output / 'Reports' if len(selected_populations) == 1 else output / 'Reports' / population
                summary = report_folder / 'download_summary.csv'
                if population not in selected_populations:
                    continue
                if summary.exists():
                    with st.expander(f'{population} · deal results', expanded=True):
                        try:
                            st.dataframe(pd.read_csv(summary, dtype={'Deal ID': str}).head(2000), hide_index=True, use_container_width=True)
                            st.caption('Table display is limited to the first 2,000 rows. Full results are in the local CSV.')
                        except (ValueError, OSError):
                            st.warning('Could not display this summary. Open the local CSV.')
            st.write('Local output folder:')
            st.code(str(output), language=None)
            if os.name == 'nt' and st.button('Open local output folder'):
                os.startfile(str(output))
            if st.button('Prepare results ZIP (up to 150 MiB of source files)'):
                try:
                    create_archive(output, directory / 'Reports' / 'results.zip')
                except (ValueError, OSError) as exc:
                    st.warning(str(exc))
            archive = directory / 'Reports' / 'results.zip'
            if archive.exists():
                with archive.open('rb') as handle:
                    st.download_button('Save results ZIP', data=handle, file_name=f'{directory.name}.zip', mime='application/zip')
    elif not running and not job.get('stopped'):
        st.error('Worker exited without a result manifest. Check the log and installed dependencies.')
    log = directory / 'Reports' / 'worker.log'
    if log.exists():
        with log.open('rb') as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 60000))
            text = handle.read().decode('utf-8', errors='replace')
        with st.expander('Live diagnostic log (last 60 KB)', expanded=running):
            st.code(text, language=None)
    st.caption(f'Local run folder: {directory}. No automatic deletion is performed.')

job_panel()
