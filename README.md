# DealCloud Memo Downloader — Local Streamlit App

A local browser interface for the supplied v11 downloader, with uploaded JSON credentials, interactive filters, a preview step, and a Windows double-click launcher.

**Status:** implementation and simulated tests only. No live DealCloud connection has been made. The Windows launcher and browser experience must be checked on a Windows computer. Package versions are not a live-tested lockfile.

## Multi-attachment parsing fix (v3.3)

The SDK may return multiple attachment references as a semicolon-separated numeric string. The engine now splits that complete ID sequence and pairs each ID with its corresponding display filename. Previously the unsplit cell could be mistaken for a direct file field, causing a file-not-found response or preventing the intended internal memo from being considered correctly. Known supplementary files remain excluded individually. No credentials, selection defaults, output paths or dependency changes are needed.

**Updating from v3.2:** stop the active job and server, replace only `downloader_engine.py` beside `app.py`, and restart `launch.bat`. Refresh options and run a new preview before downloading. Older versions should use the full package, preserving the existing environment and private credentials. Old downloads are not moved or deleted. No live download has been performed by the developer to verify the corrected route.

Offline verification: `test_multireference.py` covers numeric multi-reference parsing, filename alignment, supplementary exclusion, priority/all modes and paired ID/name reads. Run all tests with:

```powershell
.\dealcloud-memo-venv\Scripts\python.exe -m unittest -v test_app.py test_ui_smoke.py test_secondary.py test_multireference.py
```

## Secondary memo compatibility fix (v3.2)

`SecondaryMemo.TeamDiscussionMemo` is now treated as an additional optional stream. If the field is absent from the accessible schema or from both returned resolutions, the app continues processing the mapped `INTERNALMEMO` and `ClientMemo` fields, with an explicit coverage warning in the UI, log and `run_settings.json`. It does not claim that Team Discussion coverage is complete or move it to another object by guessing a mapping. Have your administrator verify schema and permissions if you need that stream.

Canonical mapped fields remain required: their absence still produces an error. When TeamDiscussionMemo is available, its existing selection behavior and TeamDiscussionRecommendation mapping are retained. Counts may be lower when an optional stream cannot be read. The app does not infer that a missing column means there are no underlying attachments.

To apply only this runtime fix to v3/v3.1, replace **both `downloader_engine.py` and `app.py`**, then restart the app, refresh options and rerun preview. No dependency or credential change is required. The full ZIP also includes `test_secondary.py`; run it with the existing test suite for offline verification.

## 1. First-time setup

1. Extract the entire ZIP into a writable local folder. Do not run it from inside the ZIP. A short path is preferable because Windows path-length limits can affect downloads.
2. Install Python through your organization's approved process, including the `py` Windows launcher. Python 3.10+ is needed; 3.11 or 3.12 is a reasonable initial choice, subject to current package compatibility.
3. Double-click **`setup.bat`**. This creates **`dealcloud-memo-venv`** and installs `requirements.txt`. It needs access to your approved Python package repository.
4. Double-click **`launch.bat`**. Your browser should open the local app at **http://127.0.0.1:8501**. If not, open that URL manually.

No environment activation, PowerShell script execution, administrator rights, or execution-policy change is required by these launchers. Organizational software restrictions still apply.

Keep the launcher window open while using the app. To stop the server, use Ctrl+C in that window. Stop an active download with the app's **Stop current job** button first; closing the browser or server is not a reliable way to stop the separate worker.

### PowerShell equivalents

From the extracted folder:

```powershell
py -m venv dealcloud-memo-venv
.\dealcloud-memo-venv\Scripts\python.exe -m pip install -r requirements.txt
.\dealcloud-memo-venv\Scripts\python.exe -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --server.maxUploadSize=1 --server.fileWatcherType=none --browser.gatherUsageStats=false
```

Create the environment only once. Package installation need not be repeated unless dependencies change. The launcher automatically offers setup if the environment or imports are missing. Run `setup.bat` manually after dependency updates.

## 2. Prepare your credentials file

Copy `credentials.template.json` to a private location **outside the shared app folder**, rename it to something such as `my_dealcloud_credentials.json`, and replace the placeholders:

```json
{
  "site_url": "https://your-site.dealcloud.com",
  "client_id": "your-client-id",
  "client_secret": "your-client-secret"
}
```

The JSON must contain exactly these three keys, with nonempty string values. Use the tenant's HTTPS base URL, without a path, query, embedded login, or custom port. The app accepts a UTF-8 JSON file under 64 KiB. Standard JSON escaping applies if a secret contains a backslash or quote.

This script uses **client ID + client secret + site URL**, not a single API-key field. Ask your DealCloud administrator for an API client with the necessary schema, record, and file-read permissions.

**A JSON file is not encryption.** A completed file contains a reusable plaintext secret. Restrict its filesystem access; do not email it, place it in a shared folder, upload it to this chat, include it in a ZIP, or commit it to source control. Follow your organization's credential-storage policy. The included `.gitignore` is only a convenience, not a security control. Never disable security controls to make setup work.

## 3. Use the app

1. **Upload your credentials JSON** in the Connection section. The app does not display the client ID or secret. File-format acceptance is not proof that authentication will work.
2. Choose the site timezone and inclusive IC-date range. “End today” is resolved in that timezone when the job is submitted.
3. Select one or more **Primaries, CoInvestments, Secondaries** populations.
4. Choose **priority** (one successful memo per parent) or **all** eligible memo attachments.
5. Select memo stages and audiences. Empty selections mean all supported stages or both audiences.
6. Set the optional Primaries-only **Approved by IC?** filter and optional recommendation filter.
7. Click **Load / Refresh filter options from DealCloud**. After it completes, use the searchable multi-select dropdowns for Structure/Structure Type, Asset Class, Strategy, SubStrategy, and Status where mapped. Empty = unrestricted. Multiple values within a field mean OR; filters across fields mean AND. Additional JSON filters are tucked into each population's **Advanced** section.
8. Click **Preview eligible deals and counts**. Preview authenticates and reads schema, memo records, and linked parents. It does **not** request attachment metadata or download attachment files. Local preview CSVs and settings are still written.
9. Review the preview, check the authorization box, and click **Download memos**. Changing settings or credentials requires a new successful preview. Partial or failed previews do not authorize downloading.
10. Inspect counts, CSV logs, and any failures. Open the local output folder or optionally prepare a results ZIP.
11. Click **Clear uploaded credentials** when finished, then stop the server. This does not erase your original JSON file from disk or promise forensic memory erasure.

### How the dropdown values are loaded

- All three populations use searchable multi-select parent filters. The optional memo Recommendation filter remains a free-text list; memo stages, audiences and primary approval already have selection controls.
- Values come from **actual accessible parent records linked to memos in the selected IC-date window**, using the supplied mappings and human-readable SDK values. The loader does not read every Fund/deal record, invent reference labels, or claim to enumerate every configured schema choice.
- Options are loaded before applying parent, memo-stage, audience, recommendation or IC-approval filters. They are not cascading dropdowns: selecting a Strategy does not narrow SubStrategy options. A selectable label is not a guarantee that a memo will pass the later filters.
- Loading authenticates and reads memo records and linked parents, so a broad date range may take time. It does not fetch attachment metadata, download memos, or write to DealCloud. Progress appears in the job log. Use Stop current job to cancel.
- Changing credentials, selected populations, dates or timezone requires reloading options. Refreshing options invalidates the download authorization preview; run Preview again. Changing a parent filter does not reload options but does require a new preview before downloading.
- Empty means no restriction. Defaults from the original script are retained. If a default or previously selected value is not observed in the current window, it remains explicitly selected with a warning rather than silently broadening the filter. Clear it if you do not want that restriction.
- Missing/inaccessible fields are identified in the UI. They may remain unrestricted, but an active selection on an unavailable field blocks preview until cleared. A population read failure is reported as an error, not shown as an empty successful list.
- Loaded labels are cached in the current browser session and are also saved in the options job's `Reports/result.json` under `Previews/Filter options - <batch name>`. These are tenant data: protect them and delete old options batches according to your retention policy. Credentials are not intentionally saved in these files.

### Initial defaults

The interface starts with the supplied script's 2026-01-01 start date, today as end date, Primaries, priority mode, Final memos, Approved by IC = Yes, no recommendation restriction, and both audiences. Parent-filter defaults match the supplied script: unrestricted Primaries, CoInvestments AssetClass = Private Equity, Secondaries Structure = Secondary Transaction.

**One deliberate safety change:** the UI initially caps attempts at **5 candidates per population**, whereas the supplied script default is unlimited. Turn off the cap only after reviewing a small live test. The cap counts attempts, including failures/skips; it is not a byte limit, storage quota, or API-read limit. Preview shows eligible candidates before this cap, not the exact number of files that will download.

### Selection behavior retained from v11

- Inclusive **IC dates**, not deal creation or Team Discussion dates. Undated and out-of-window events are excluded locally even if server filtering returns extra rows.
- Explicit populations: Fund/DiligenceActivity, CoInvestmentDeal/CIMemo, and SecondaryDeal/SecondaryMemo. These mappings came from the supplied code; your live tenant must match.
- Parent filters use the linked parent fields. Unrestricted Primaries includes all linked Fund structures, not a verified Primary Partnership-only subset. Secondaries uses the active `Strategy_1` mapping. No invented Fund Status alias is added.
- Primaries “Approved by IC?” is separate from Recommendation. Explicit No does not include blank/unknown. The flag does not apply to the other populations.
- Recommendation uses `Recommendation` for all populations; Secondary TeamDiscussionMemo uses `TeamDiscussionRecommendation`. The UI does not offer arbitrary recommendation-field remapping; the supplied mapping remains in the engine.
- Priority order: Internal Final, Client Final, Internal Screening, Client Screening, Internal Follow-On, Client Follow-On, Internal Update/Addendum, Client Update/Addendum; newest IC date within a tier. Failed candidates can fall back, with bounded retries for qualifying transient attachment errors.
- All mode does not stop after the first successful file. Attachment IDs repeated for the same parent are deduplicated; different IDs are not content-deduplicated.
- Known supplementary/impact-assessment materials are excluded by stage or filename, not by inspecting contents. Update includes Addendum. Unknown stages are excluded.
- Filename metadata is optional by default. If no filename is available from metadata or the memo field, a `.bin` may be saved with a review note. Strict filename mode skips these files instead.
- Memo queries request the IC window and linked parents are fetched in ID batches. Active missing filter fields fail rather than silently being ignored. Actual tenant/SDK behavior still needs verification.

### Preview is not a frozen snapshot

Downloading re-reads the API. Tenant data or permissions may change after preview. Metadata and filename checks happen during downloading and can remove candidates that were counted in preview. Zero successful files can result from failures or skips, not necessarily zero eligible records. A run marked completed means the processing finished without a population-level error, not that every candidate downloaded successfully.

## 4. Outputs — simplified in this version

Download batches now use a short, readable name based on population, selected memo stages and timestamp in the site timezone. Full filters remain in `Reports/run_settings.json` rather than making the pathname enormous.

For a single population:

```text
Downloads/
└── Primaries - Final - 2026-11-03 17.00.00/
    ├── Fund Name - 2026-09-15 - Final - Internal.pdf
    ├── Another Fund - 2026-10-20 - Final - Client.pdf
    └── Reports/
        ├── download_summary.csv
        ├── downloaded_files.csv
        ├── candidate_attempts.csv
        ├── event_issues.csv
        ├── run_settings.json
        ├── worker.log
        └── result.json
```

No `runs/random-id/output/second-timestamp/Primaries/Memos` chain. Only when multiple populations are selected are memo files separated into `Primaries`, `CoInvestments` and/or `Secondaries` folders directly under the batch. In that case, per-population CSVs go under `Reports/<population>` and the run settings/log/status remain directly under `Reports`.

- `Downloads` lives beside `app.py`, not necessarily in the Windows Downloads known folder. The app shows the full path and has an **Open local output folder** button.
- Preview batches are stored separately under `Previews`, with the same readable naming convention and no memo downloads.
- Duplicate batch names get `(2)`, `(3)`, etc.; earlier runs are never overwritten.
- Individual memo filenames and selection rules are unchanged.
- Packaging a results ZIP puts it inside `Reports`. Its browser download name matches the readable batch name. The archive includes downloaded files recorded in the CSV logs and known report files, not credentials, worker logs, or internal worker status.
- Browser ZIP preparation is limited to 150 MiB of source files; this does not limit local downloads.
- The summary table displays the first 2,000 rows; local CSVs contain all rows.
- CSV paths refer to the producing computer and are not rewritten when the ZIP is moved. `event_issues.csv` is not an exhaustive exclusion log.
- No automatic deletion is performed. Review or delete incomplete batches after stopping a job, and apply your organization's retention rules.

### Updating an existing installation

Stop the current job and server first. Extract this ZIP to a temporary folder, then copy its source, launcher and documentation files into the existing app folder, replacing the old files. Leave your existing `dealcloud-memo-venv`, private credentials, and old downloads untouched. Restart `launch.bat`. This version does not move or rename old run folders; the new layout applies to future jobs only.

The duplicated app-folder name in an existing path comes from ZIP extraction, not the worker. If desired, use a single app folder at a short path when setting up a new installation. Do not move or rename an existing virtual environment; recreate it using setup if you relocate the app.

## 5. Credential handling and deployment limits

- The uploaded JSON is processed in the local Streamlit process's memory; the app does not intentionally copy it into an output file or persist it as a settings file.
- Credentials pass to a separate worker over stdin, not command-line arguments or a credential file. Only the worker receives credential environment variables. The Streamlit process's environment is not modified for authentication.
- Workers use a separate process and uniquely named run folder for each job; engine settings are not changed globally across jobs in the UI process.
- Literal client ID and client secret values are redacted from worker console output, result status, and known diagnostic text files on normal completion. This is defensive, best-effort masking—not a guarantee against every SDK encoding, log sink, crash dump, or malicious response. Inspect logs before sharing them. Binary memo contents are not altered.
- Secrets necessarily exist in process memory and the worker's environment while it runs. Local administrators, other processes with sufficient privileges, OS diagnostics, or malicious software can potentially access them.
- The launcher binds to **127.0.0.1 only** and disables Streamlit usage telemetry. Loopback binding is not authentication and does not isolate users who share the same computer. Other local applications/users may still access the port. Do not use it on an untrusted or shared computer.
- No custom TLS, user login, per-user authorization, approved central secret manager, or production retention controls are included. **Do not deploy this package to a shared server or expose it to a LAN/internet as-is.**
- Each browser session can run one worker at a time; the package does not impose a machine-wide concurrency limit. Use one local session at a time to avoid unnecessary API load.

For a future shared internal app, use organizational authentication and a reviewed credential/authorization design instead of casually uploading long-lived secrets to a remote server.

## 6. Troubleshooting

### Python launcher missing

Install Python and the `py` launcher through IT. If `python` works, you can create the environment manually with `python -m venv dealcloud-memo-venv`, then run `setup.bat`.

### Package installation fails

Keep the full error, check approved repository/proxy/certificate settings, and confirm Python/package compatibility. Do not disable TLS verification. The dependency ranges are not a tested lockfile. After a successful live pilot, pin the versions your organization validates.

### Activation scripts blocked

No activation is used. Do not run `Activate.ps1` or change execution policy. Use the launchers or the explicit environment executable shown above.

### Port 8501 is in use

Close the other local app. Alternatively, change `--server.port=8501` to another free port in `launch.bat`, then use the matching localhost URL.

### JSON upload rejected

Use the exact three keys, valid JSON, UTF-8 encoding, an HTTPS tenant base URL, and actual values instead of template placeholders. Do not add comments to JSON. The file remains a plaintext secret even when the UI masks it.

### Authentication, schema, or file access fails

Confirm the tenant URL, client credentials, read permissions, and the supplied population mappings with your administrator. Do not include secrets in screenshots or support messages. Preview does not test attachment-download permissions; validate those with a small live download.

### Download button disabled

Upload valid credentials, select a population and valid date range/timezone, load filter options successfully for all selected populations, complete a fully successful preview for the current settings, and check the authorization checkbox. An active worker also disables new launches. Changed settings/credentials require another preview.

### No files downloaded, or only some populations completed

Review `population_results`, `population_error.txt`, `download_summary.csv`, and `candidate_attempts.csv`. Check IC dates, filters, approval/recommendation values, filename rules, and the attempt cap. Partial preview success does not enable downloading. Reduce to one population and a narrow date window for diagnosis.

### Browser closed during a run

A worker can continue after the browser disconnects. Reconnecting may not restore its session controls. Check local run folders and use Windows Task Manager if necessary to stop an orphaned Python worker, identifying the relevant process carefully. Abrupt stopping can leave partial outputs.

## 7. Tests and source files

- `original_downloader_v11.py`: original pasted script retained unchanged as a reference. Do not run this file to launch the UI.
- `downloader_engine.py`: supplied engine with a preview-only branch, manifest indicator and simplified output layout. Download-selection, retries, and naming behavior are reused.
- `worker.py`: isolated execution, stdin credential transfer, defensive redaction, result status.
- `ui_support.py`: input validation and safe result packaging.
- `filter_options.py`: actual observed parent-filter labels for all three populations, scoped to the chosen IC-date window; missing-field and per-population error reporting.
- `app.py`: Streamlit controls and worker monitoring.
- `test_app.py`: offline unittest suite using a fake SDK. No tenant credentials are required.
- `TEST_RESULTS.md`: records the checks performed for this package.

Run offline tests after installation:

```powershell
.\dealcloud-memo-venv\Scripts\python.exe -m unittest -v test_app.py test_ui_smoke.py
```

Simulated tests cannot validate your tenant's schema, actual SDK/network behavior, file permissions, Windows launcher behavior, or browser interactions. Begin live validation with one population, a narrow IC window, strict filename checks if required, and the 5-attempt cap enabled.
