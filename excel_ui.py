"""Excel-list user interface. API work occurs only in the isolated worker."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from excel_input import sheet_names, read_sheet, suggested_mapping, validate_rows, template_bytes, POLICIES, POPULATIONS, MAX_UPLOAD_BYTES
from ui_support import parse_credentials, fingerprint, allocate_batch, create_archive, output_directory, excel_preview_usable


def render(root, results_root):
    st.subheader('Excel deal-list mode')
    st.caption('Save memos either once each in one batch folder, or into a folder per client (the same deal can be listed for many clients; it downloads once and is copied to each client folder).')
    st.caption('A separate input mode: existing date/population filters are not applied. No memo-date window, IC-approval or recommendation filter. Only the uploaded names are queried.')
    key=st.session_state.get('excel_upload_key',0)
    def busy():
        job=st.session_state.get('job')
        return bool(job and job['process'].poll() is None)
    left,right=st.columns([1,2])
    credentials=None;timezone_ok=False
    with left:
        st.markdown('### 1 · Connection')
        credential_file=st.file_uploader('Private DealCloud credentials JSON',type=['json'],key=f'excel_credentials_{key}')
        if credential_file is not None:
            try:
                if credential_file.size>65536:raise ValueError('Credentials file must be smaller than 64 KiB.')
                credentials=parse_credentials(credential_file.getvalue())
                st.success('Credentials format accepted. Preview will test authentication.')
            except ValueError as exc:st.error(str(exc))
        if st.button('Clear Excel-mode credentials',disabled=busy()):
            st.session_state['excel_upload_key']=key+1
            st.session_state.pop('excel_approved_preview',None)
            st.rerun()
        st.caption('Credentials are used in memory and passed over stdin, not copied to a file. The original JSON is a plaintext secret: keep it private.')
        timezone=st.text_input('Site timezone',value='America/New_York',key='excel_timezone')
        try:zone=ZoneInfo(timezone.strip());timezone_ok=True
        except (ValueError,KeyError):st.error('Enter an IANA timezone such as America/New_York.')
        st.markdown('### 2 · Selection rule')
        default_policy=st.selectbox('Default memo rule',POLICIES,key='excel_policy',help='A specific stage never falls back to a different stage. Priority fallback and Latest available are different rules.')
        audience=st.selectbox('Audience preference',['Internal then Client','Internal only','Client only'],key='excel_audience')
        strict=st.checkbox('Skip files without verifiable filenames',value=True,key='excel_strict')
        limited=st.checkbox('Limit candidate attempts (recommended for first live test)',value=True,key='excel_limited')
        cap=int(st.number_input('Maximum candidate attempts per population',min_value=1,max_value=100000,value=5,step=1,key='excel_cap',disabled=not limited))
        if not limited:cap=None
        st.caption('Attempt cap counts attempted candidates, including failed/skipped ones. It is not a byte, storage or API-read limit. Preview counts all eligible candidates.')
        st.markdown('### Save layout')
        layout_label=st.radio('How should memos be saved?',['One folder (unique memos)','Folder per client'],key='excel_layout',
            help='One folder: each deal/memo saved once. Folder per client: map a Client column; a deal listed for several clients is downloaded once and copied into each client\'s folder.')
        layout='grouped' if layout_label=='Folder per client' else 'flat'
        precedence='Keep all'
    rows=[];errors=[];file_signature=None;mapping={};sheet=None
    with right:
        st.markdown('### 3 · Workbook and column mapping')
        st.download_button('Download Excel template',data=template_bytes(),file_name='DealCloud_Deal_List_Template.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        uploaded=st.file_uploader('Deal-list workbook (.xlsx)',type=['xlsx'],key='excel_deal_workbook',help='10 MiB maximum, up to 3,000 rows / 100 columns. No formulas in mapped columns.')
        if uploaded is not None:
            try:
                if uploaded.size>MAX_UPLOAD_BYTES:raise ValueError('Workbook exceeds 10 MiB. Upload a small dedicated deal list.')
                data=uploaded.getvalue();file_signature=hashlib.sha256(data).hexdigest()
                sheets=sheet_names(data)
                sheet=st.selectbox('Worksheet',sheets,index=sheets.index('Client_Deal_Summary') if 'Client_Deal_Summary' in sheets else 0,key=f'excel_sheet_{file_signature}')
                header=int(st.number_input('Header row',min_value=1,max_value=50,value=1,step=1,key=f'excel_header_{file_signature}_{sheet}'))
                headers,records=read_sheet(data,sheet,header);suggested=suggested_mapping(headers)
                default_population=st.selectbox('Default population for blank/unmapped cells',POPULATIONS,key='excel_default_population')
                cols=st.columns(2)
                fields=[('deal_name','Deal Name (required)'),('population','Population / Structure'),('memo_type','Memo Type (optional)')]
                if layout=='grouped':
                    fields+=[('client','Client / Fund folder (required for this layout)'),('year','Year subfolder (optional)'),('quarters','Quarter subfolder (optional)')]
                for i,(field,label) in enumerate(fields):
                    options=['Not mapped']+headers
                    selected=suggested.get(field)
                    value=cols[i%2].selectbox(label,options,index=options.index(selected) if selected else 0,key=f'excel_map_{file_signature}_{sheet}_{header}_{field}')
                    mapping[field]=None if value=='Not mapped' else value
                if layout=='grouped' and not mapping.get('client'):
                    raise ValueError('Folder per client needs a Client column. Map it above, or switch the save layout to One folder.')
                if layout=='grouped' and (mapping.get('year') or mapping.get('quarters')):
                    st.caption('Folders: Client / Year / Quarter (e.g. `Acme Pension/2026/Q3/`). Year-only rows save to `Client/2026/`.')
                if layout=='grouped' and mapping.get('quarters'):
                    precedence=st.selectbox('If a client lists the same deal in several quarters of one year',['Keep all','Earliest','Latest'],
                        format_func={'Keep all':'Save a copy in every quarter listed','Earliest':'Only the earliest quarter (e.g. Q1 over Q3)','Latest':'Only the latest quarter (e.g. Q4 over Q2)'}.get,
                        key='excel_quarter_rule',help='Applies across Q1–Q4 within the same year, per client, deal and memo rule. Different years and different clients are always kept.')
                rows,errors=validate_rows(records,mapping,default_population)
                st.write(f'{len(rows):,} valid request rows; {len(errors):,} invalid rows.')
                if layout=='grouped' and rows:
                    client_keys={' '.join(r['client'].split()).casefold() for r in rows}
                    deal_keys={(r['population'],' '.join(r['deal_name'].split()).casefold()) for r in rows}
                    blank=sum(not r['client'] for r in rows)
                    st.info(f'{len(client_keys):,} client folders · {len(deal_keys):,} unique deals to download · {len(rows):,} client/deal rows. Each deal downloads once and is copied into every client folder that lists it.')
                    if blank:st.warning(f'{blank:,} rows have a blank client and will be saved in a "No Client" folder.')
                if errors:
                    st.error('Fix invalid rows in Excel or correct the mapping. The app will not silently skip invalid rows.')
                    st.dataframe(pd.DataFrame(errors),hide_index=True,use_container_width=True)
                if rows:
                    st.dataframe(pd.DataFrame(rows).head(100),hide_index=True,use_container_width=True)
                    st.caption('First 100 mapped rows shown; all valid mapped rows are submitted. Worksheet IDs and unmapped columns are ignored. No upload file is saved to disk by this app; mapped deal/client data is included in run reports. '
                               +('Duplicate deal/policy rows for the same client reuse one copy.' if layout=='grouped' else 'Client/quarter columns are ignored in this layout; duplicate deal/policy rows reuse one saved memo.'))
            except (ValueError,OSError) as exc:
                st.error(str(exc));rows=[]
    with st.expander('How the memo rules work — read before downloading'):
        st.markdown('''- **Final / Screening / Follow-On / Update:** only that stage; Internal then Client (if selected), newest within each audience. “Addendum” is treated as Update.
- **Priority fallback:** Final Internal → Final Client → Screening Internal → Screening Client → Follow-On Internal → Follow-On Client → Update Internal → Update Client. Older eligible candidates within a tier may be tried after failures. Stops after one successful file per deal/policy.
- **Latest available:** newest IC date across the four supported stages; audience preference is a tie-break for the same date, not an Internal-first override of date. Stops after one successful file per deal/policy; older eligible candidates can be tried after a failure.
- An optional **Memo Type** cell overrides the app default for that row. Blank uses the app default. Different policies for the same deal can intentionally produce multiple files.
- Names must resolve uniquely in their population. Case and whitespace are normalized locally; punctuation/legal suffixes are preserved. No fuzzy matches, guessed fund aliases or workbook IDs used as API IDs.
- **One folder (unique memos):** every selected memo saves once, directly in the batch folder. Client/quarter columns are ignored.
- **Folder per client:** one folder per Client value (case and extra spaces ignored; blank → `No Client`), with optional Year and Quarter subfolders (`Client/2026/Q3/`). Quarters can be Q1–Q4 in common formats (`Q3 2026`, `2026 Q3`, `Q3-26`, `3Q26`, or `3` with a Year column); separate several with semicolons. If one client lists the same deal in several quarters of a year, you can keep every quarter, or only the earliest or latest. List a deal once per client that needs it: the memo is selected and downloaded **once**, then copied into each client folder. The audit CSV shows one row per client/quarter request. Client folders are local organisation only — an Internal memo in a client folder is **not** automatically approved for that client.
- Folders are never based on IC date.
- Preview makes schema/record reads but no attachment metadata/file requests. Download makes fresh reads; it is not a frozen preview snapshot. A candidate is not a promised successful file.
- Unknown stages and undated records are excluded. Known supplementary material is excluded by stage/filename, not content. Coverage warnings indicate accessible mapped streams only.
- Short OS-temp cache names and bounded final paths avoid the earlier deep-path issue. Output is under your user folder’s `DealCloud Memos`; no automatic retention cleanup. Stopping can leave a partial cache/batch.
''')
    settings={'rows':rows,'default_policy':default_policy,'audience':audience,'quarter_precedence':precedence,'output_layout':layout,'strict_filename':strict,'max_attempts':cap}
    valid=bool(credentials and timezone_ok and rows and not errors)
    signature=fingerprint({'excel':settings,'workbook_hash':file_signature,'sheet':sheet,'mapping':mapping},timezone.strip(),credentials) if valid else None
    def launch(preview):
        if busy():raise RuntimeError('Another job is running.')
        parent=results_root/('Previews' if preview else 'Downloads')
        # Kept short: every character here is taken from client/deal names in the 230-character path budget.
        label=f"{'By client' if layout=='grouped' else 'Excel deals'} - {default_policy} - {dt.datetime.now(zone):%Y-%m-%d %H%M}"
        directory=allocate_batch(parent,label);reports=directory/'Reports';reports.mkdir()
        process=None
        try:
            with (reports/'worker.log').open('w',encoding='utf-8') as log:
                kwargs={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
                process=subprocess.Popen([sys.executable,'-u',str(root/'worker.py'),str(directory)],stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,text=True,encoding='utf-8',cwd=str(root),**kwargs)
                payload={'action':'excel','preview':preview,'settings':settings,'timezone':timezone.strip(),'credentials':credentials}
                process.stdin.write(json.dumps(payload));process.stdin.close()
        except Exception:
            if process and process.poll() is None:process.terminate();process.wait(timeout=10)
            raise
        st.session_state['job']={'process':process,'directory':str(directory),'action':'excel','preview':preview,'signature':signature,'handled':False}
        st.session_state.pop('approved_preview',None)
        if not preview:st.session_state.pop('excel_approved_preview',None)
    st.markdown('### 4 · Preview and download')
    st.caption('Save location: '+str(results_root/'Downloads'/(('By client - <rule> - <date time>' + os.sep + '<Client>') if layout=='grouped' else 'Excel deals - <rule> - <timestamp>')))
    col1,col2=st.columns(2)
    if col1.button('Preview Excel list',type='primary',disabled=not valid or busy()):
        try:launch(True);st.rerun()
        except (OSError,RuntimeError):st.error('Could not launch the worker. Check folder permissions and installation.')
    matched=valid and st.session_state.get('excel_approved_preview')==signature
    confirmed=col2.checkbox('I reviewed this preview and authorize these downloads',value=False,key='excel_confirm')
    if col2.button('Download Excel-list memos',disabled=not(matched and confirmed) or busy()):
        try:launch(False);st.rerun()
        except (OSError,RuntimeError):st.error('Could not launch the worker. Check folder permissions and installation.')
    if not matched:st.caption('A completed preview for exactly these rows, settings and credentials is required. Population-level errors block authorization; unmatched individual names remain explicit audit rows.')

    @st.fragment(run_every=1)
    def panel():
        job=st.session_state.get('job')
        if not job or job.get('action')!='excel':return
        directory=Path(job['directory']);reports=directory/'Reports';process=job['process'];running=process.poll() is None
        st.subheader(('Excel preview' if job['preview'] else 'Excel download')+(' running…' if running else ' results'))
        if running and st.button('Stop Excel-list job'):
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
            job.update(stopped=True,handled=True);st.session_state.pop('excel_approved_preview',None);st.rerun()
        result=None
        if not running and (reports/'result.json').exists():
            try:result=json.loads((reports/'result.json').read_text())
            except (ValueError,OSError):st.error('Could not read worker result. Review the log.')
        if not running and not job.get('handled'):
            job['handled']=True
            if result and excel_preview_usable(result) and job['preview'] and not job.get('stopped'):
                st.session_state['excel_approved_preview']=job['signature']
            st.rerun()
        if job.get('stopped'):st.warning('Stopped. Treat partial files/logs as incomplete; previous batches are unchanged.')
        if result:
            if result.get('status')=='completed':st.success('Processing completed. Review unmatched/skipped/missing rows and coverage warnings; completed does not mean every requested file exists.')
            elif job['preview'] and excel_preview_usable(result):st.info('Preview is ready for review, with some missing candidates or coverage warnings. This is not a download failure. Available candidates can be downloaded after you authorize below; missing rows remain in the audit.')
            else:st.warning('Processing failed or was partial. Review the report and log. Population-level errors or zero eligible candidates block preview authorization.')
            if result.get('error'):st.error(result['error'])
            if result.get('excel_summary'):
                summary=result['excel_summary']
                if job['preview']:
                    st.info(f"Preview only — no files were meant to download yet. {summary.get('eligible_candidates',0):,} eligible candidates across {summary.get('unique_policy_jobs',0):,} matched deal/policy requests. Review the row statuses below, then authorize download.")
                else:
                    folders=f" across {summary['client_folders']:,} client folders" if 'client_folders' in summary else ''
                    st.info(f"{summary.get('unique_memos_downloaded',0):,} deal/policy memos downloaded; {summary.get('memo_copies_written',0):,} output files{folders}. Review any incomplete requests below.")
                with st.expander('Technical run summary',expanded=False):st.json(summary)
            for row in result.get('population_results',[]):
                for warning in row.get('source_warnings',[]):st.warning(f"{row.get('population')}: {warning}")
                if row.get('error'):st.error(f"{row.get('population')}: {row['error']}")
            audit=reports/'excel_results.csv'
            if audit.exists():
                try:st.dataframe(pd.read_csv(audit,dtype=str).fillna('').head(2000),hide_index=True,use_container_width=True)
                except (OSError,ValueError):st.warning('Open the local CSV to review results.')
            st.caption('Display limited to 2,000 audit rows; full audit is saved locally.')
            output=output_directory(directory,result)
            if output:
                st.code(str(output),language=None)
                if os.name=='nt' and st.button('Open Excel-results folder'):os.startfile(str(output))
                if st.button('Prepare Excel results ZIP (150 MiB limit)'):
                    try:create_archive(output,reports/'results.zip')
                    except (ValueError,OSError) as exc:st.warning(str(exc))
                if (reports/'results.zip').exists():
                    with (reports/'results.zip').open('rb') as handle:st.download_button('Save Excel results ZIP',data=handle,file_name=directory.name+'.zip',mime='application/zip')
        elif not running and not job.get('stopped'):st.error('Worker exited without a result. Review the log and installed packages.')
        if (reports/'worker.log').exists():
            with (reports/'worker.log').open('rb') as handle:
                handle.seek(0,2);handle.seek(max(0,handle.tell()-60000));text=handle.read().decode('utf-8',errors='replace')
            with st.expander('Excel job log (last 60 KB)',expanded=running):st.code(text,language=None)
        st.caption('Local run folder: '+str(directory))
    panel()
