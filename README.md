# DealCloud Memo Downloader — Local Streamlit App

A local browser interface for the supplied v11 downloader, with uploaded JSON credentials, interactive filters, a preview step, and a Windows double-click launcher.

**Status:** implementation and simulated tests only. No live DealCloud connection has been made. The Windows launcher and browser experience must be checked on a Windows computer. Package versions are not a live-tested lockfile.

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
7. Enter parent-record filters, one actual tenant value per line. Empty = unrestricted. Multiple values within a field mean OR; filters across fields mean AND. Optional advanced filters use a JSON object of field names to lists.
8. Click **Preview eligible deals and counts**. Preview authenticates and reads schema, memo records, and linked parents. It does **not** request attachment metadata or download attachment files. Local preview CSVs and settings are still written.
9. Review the preview, check the authorization box, and click **Download memos**. Changing settings or credentials requires a new successful preview. Partial or failed previews do not authorize downloading.
10. Inspect counts, CSV logs, and any failures. Open the local output folder or optionally prepare a results ZIP.
11. Click **Clear uploaded credentials** when finished, then stop the server. This does not erase your original JSON file from disk or promise forensic memory erasure.

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

## 4. Outputs

Each preview or download has its own local folder:

```text
DealCloud_Memo_Streamlit\
├── app.py
├── launch.bat
├── setup.bat
├── requirements.txt
├── credentials.template.json
├── dealcloud-memo-venv\
└── runs\
    └── <timestamp>_<random id>\
        ├── worker.log
        ├── result.json
        ├── results.zip                 # only if explicitly prepared
        └── output\
            └── <engine timestamp>\
                ├── run_settings.json
                └── <population>\
                    ├── Memos\
                    ├── download_summary.csv
                    ├── downloaded_files.csv
                    ├── candidate_attempts.csv
                    ├── event_issues.csv
                    └── population_error.txt   # only after a population error
```

Preview folders contain no downloaded memos. `event_issues.csv` records source events with unextractable parent references; it is not a complete exclusion log. Filesystem paths in CSVs refer to the producing computer and are not rewritten when a ZIP is moved. The browser displays up to 2,000 summary rows per population; local CSVs contain the full result.

Preparing a browser ZIP is optional and restricted to results totaling at most **150 MiB of source files**. Larger runs remain available in the local output folder; use approved local file-handling methods. This ZIP cap does not limit downloads. Credentials files, source code, and worker logs are not included by the result-packaging function.

**No automatic retention cleanup is performed.** Memos and logs may be confidential. Apply your organization's retention rules and delete old run folders when appropriate. Stopping a job may leave partial files/logs; review or delete that incomplete run before relying on it. Previous runs are not overwritten or removed.

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

Upload valid credentials, select a population and valid date range/timezone, complete a fully successful preview for the current settings, and check the authorization checkbox. An active worker also disables new launches. Changed settings/credentials require another preview.

### No files downloaded, or only some populations completed

Review `population_results`, `population_error.txt`, `download_summary.csv`, and `candidate_attempts.csv`. Check IC dates, filters, approval/recommendation values, filename rules, and the attempt cap. Partial preview success does not enable downloading. Reduce to one population and a narrow date window for diagnosis.

### Browser closed during a run

A worker can continue after the browser disconnects. Reconnecting may not restore its session controls. Check local run folders and use Windows Task Manager if necessary to stop an orphaned Python worker, identifying the relevant process carefully. Abrupt stopping can leave partial outputs.

## 7. Tests and source files

- `original_downloader_v11.py`: original pasted script retained unchanged as a reference. Do not run this file to launch the UI.
- `downloader_engine.py`: supplied engine with a preview-only branch and manifest indicator. Download-selection, retries, and naming behavior are reused.
- `worker.py`: isolated execution, stdin credential transfer, defensive redaction, result status.
- `ui_support.py`: input validation and safe result packaging.
- `app.py`: Streamlit controls and worker monitoring.
- `test_app.py`: offline unittest suite using a fake SDK. No tenant credentials are required.
- `TEST_RESULTS.md`: records the checks performed for this package.

Run offline tests after installation:

```powershell
.\dealcloud-memo-venv\Scripts\python.exe -m unittest -v test_app.py
```

Simulated tests cannot validate your tenant's schema, actual SDK/network behavior, file permissions, Windows launcher behavior, or browser interactions. Begin live validation with one population, a narrow IC window, strict filename checks if required, and the 5-attempt cap enabled.
