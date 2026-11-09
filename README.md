# DealCloud Memo Downloader

A small app that runs on your own computer and downloads investment memos from DealCloud in bulk. You give it a list of deals (an Excel file) or pick filters, it shows you what it found, and then it saves the memo files to a folder on your computer, either all together or sorted into a folder per client.

You don't need to know any Python. You install it once, then you just double-click a file to open the app in your web browser.

---

## First-time setup (about 15 minutes, once per computer)

### What you need

| Item | Needed? | Where to get it |
|---|---|---|
| **Python** | **Yes** | Company Portal (search "Python") |
| **This app's folder** | **Yes** | From whoever sent you this README |
| **Your DealCloud API credentials** | **Yes** | Your DealCloud admin (see Step 4) |
| Microsoft Excel | Yes, for deal lists | Already on your laptop |
| ODBC Driver 18 | **No** | Not used. The app connects to DealCloud over the web, not through a database driver. |
| VS Code | **No** | Not needed. You never open or edit code. Notepad is enough for the one file you fill in. |

**What is Python?** It's the program that runs this app, the way Excel runs a spreadsheet. You install it, but you never have to open it or write anything in it.

### Step 1: Install Python

1. Open **Company Portal**, search for **Python**, and install it. If there are several versions, choose a Python 3 version (3.11, 3.12 or newer). If you don't see Python at all, ask IT to install it; mention you need the **`py` launcher** (or "Python Install Manager"), because the setup script uses it.
2. **Restart your computer** after it installs. This makes sure Windows can find it.
3. Check it worked: press the **Windows key**, type **cmd**, press **Enter**. In the black window that opens, type the following and press Enter:

   ```text
   py --version
   ```

   You should see something like `Python 3.12.x`. If you see *"'py' is not recognized"*, Python isn't installed correctly yet. Ask IT and mention the `py` launcher. Close the black window when you're done.

### Step 2: Put the app folder in the right place

Where the folder lives matters. Windows has a limit on how long file paths can be, and putting the app somewhere deep (like inside OneDrive) makes setup fail with *"The filename or extension is too long"*.

1. If you received a **.zip** file, right-click it → **Extract All…**. Don't run anything from inside the zip; double-clicking files inside a zip without extracting won't work.
2. Move the extracted folder (the one containing `app.py`, `setup.bat` and `launch.bat`) to a short location that is **not** in OneDrive, for example:

   ```text
   C:\Users\<your name>\DCMemo
   ```

   Avoid your **Desktop** and **Documents** folders too; on most work laptops those are synced to OneDrive.

### Step 3: Run setup (once)

1. Open the app folder and double-click **`setup.bat`**.
2. A black window opens and fills with text while it downloads what the app needs. This takes a few minutes. That's normal.
3. When it says **"Setup complete"**, press any key to close it.

This creates a folder called `dealcloud-memo-venv` inside the app folder. That's the app's private copy of everything it needs. Leave it alone; don't move, rename or delete it.

If it says **"Setup failed"**, see *Troubleshooting* below. If Windows shows a security warning or blocks the file, check with IT rather than overriding it.

### Step 4: Create your credentials file

The app logs in to DealCloud with API credentials: a site address, a client ID and a client secret. These are personal, like a password. Get your own from your DealCloud administrator; don't borrow someone else's.

1. In the app folder, find **`credentials.template.json`**. Copy it and paste the copy somewhere private on your computer, **outside the app folder** (so it never gets passed along when the app is shared) and outside OneDrive/shared folders. For example, `C:\Users\<your name>\DealCloud Memos\my-dealcloud-credentials.json` (create the folder if it doesn't exist).
2. Right-click your copy → **Open with** → **Notepad**.
3. Replace the three placeholder values, keeping the quote marks:

   ```json
   {
     "site_url": "https://your-site.dealcloud.com",
     "client_id": "your-client-id",
     "client_secret": "your-client-secret"
   }
   ```

4. Save and close.

Treat this file like a password: don't email it, put it in Teams/SharePoint, or share it.

### Step 5: Open the app (every time you use it)

1. Double-click **`launch.bat`** in the app folder.
2. A black window opens, and the app opens in your web browser at **http://127.0.0.1:8501**. If the browser doesn't open by itself, copy that address into your browser.
3. **Keep the black window open** while you use the app. It *is* the app running in the background. Closing it closes the app.
4. When you're finished, close the black window (or click in it and press **Ctrl+C**).

The app only runs on your computer. Nobody else can open your copy.

---

## Using it: downloading memos from an Excel list

1. At the top of the app, choose **Excel deal list**.
2. **Connection:** upload your credentials file from Step 4. Leave the timezone as `America/New_York` unless told otherwise.
3. **Memo rule:** *Priority fallback* is a good default. It takes the Final memo if there is one, otherwise Screening, then Follow-On, then Update.
4. **Save layout:**
   - **One folder (unique memos):** every memo saved once, all in one folder.
   - **Folder per client:** a folder for each client, each holding every memo that client needs. A deal shared by several clients is downloaded once and copied into each client's folder.
5. **Workbook:** click **Download Excel template**, fill it in (one deal per row; for *Folder per client*, one row per client + deal), save it, and upload it. Deal names must match DealCloud exactly; capital letters and extra spaces don't matter.
6. Click **Preview Excel list**. Nothing is downloaded yet; it checks every name and shows what it would download. Look for rows marked **UNMATCHED** (name not found) or **AMBIGUOUS** (more than one match), and fix those names in your spreadsheet if needed.
7. Tick **"I reviewed this preview…"** and click **Download Excel-list memos**.
8. When it finishes, click **Open Excel-results folder**. Each run gets its own new folder, so nothing old is ever overwritten.

**Where files are saved:** `C:\Users\<your name>\DealCloud Memos\Downloads\`. The **Reports** folder inside each run has a spreadsheet (`excel_results.csv`) listing what happened to every row.

**First time?** Leave **"Limit candidate attempts"** ticked and try a list of 3–5 deals first. Once that works, untick it for full lists.

---

## Troubleshooting

| What you see | What to do |
|---|---|
| *"'py' is not recognized"* or *"Python launcher not found"* | Python isn't installed, or the computer hasn't been restarted since. Restart; if it still fails, ask IT for Python with the `py` launcher. |
| *"The filename or extension is too long"* during setup | The app folder is too deep (usually in OneDrive). Move it to `C:\Users\<your name>\DCMemo`, delete the half-made `dealcloud-memo-venv` folder, and run `setup.bat` again. |
| *"Setup failed"* with network/proxy/SSL errors | Setup couldn't download packages. Make sure you're on the company network/VPN. If it still fails, send IT the full error text. |
| Double-clicking does nothing, or the window flashes and closes | Make sure you extracted the zip (Step 2) and are clicking inside the extracted folder. |
| *"port 8501 is occupied"* | The app is already open in another black window. Use that one, or close it and launch again. |
| *"Credentials format accepted"* but Preview fails to log in | The values in your credentials file are wrong or expired. Check them with your DealCloud admin. |
| *"Replace the template placeholders…"* | You uploaded the template itself. Fill in your real values (Step 4). |
| A deal shows **UNMATCHED** | The name doesn't exactly match DealCloud. Copy the name from DealCloud into your spreadsheet. |

## Getting a newer version of the app

When someone sends you updated files, close the app, then copy the new files into your existing app folder, replacing the old ones. **Keep your `dealcloud-memo-venv` folder**; don't delete it. Run `setup.bat` once more if `requirements.txt` changed (it's quick if nothing new is needed), then use `launch.bat` as usual.

---

# Reference: technical details

The rest of this document is detailed reference material: exact matching rules, file layout, reports and safety notes. You don't need it to use the app day to day.

## Upgrading from v3.3 (existing users only)

1. Stop the active job in the app, then stop the server with Ctrl+C in the launcher window.
2. Extract the v4 ZIP to a temporary folder. Copy **all files from its inner `DealCloud_Memo_Streamlit` folder** into the existing folder that contains `app.py` and `launch.bat`, replacing old source/launcher/documentation files. Do not create another nested app folder.
3. **Keep your existing `dealcloud-memo-venv`, private credentials and old downloads.** Do not move or rename the virtual environment. No credentials or private client list is included in this package.
4. Run **`setup.bat` once** to install the updated requirements, including `openpyxl` for Excel reading. This uses the existing environment if present. Organizational package permissions still apply.
5. Run **`launch.bat`**. Open http://127.0.0.1:8501 if the browser does not open automatically. Select the input mode at the top.

There is no environment activation step and no execution-policy change. If installing fresh, obtain an approved Python 3.10+ installation and Windows `py` launcher, then run setup and launch. Python 3.11/3.12 is a reasonable initial choice subject to package compatibility; dependencies are not a live-tested lockfile.

### Files changed / added

Changed runtime files: `app.py`, `worker.py`, `ui_support.py`, `downloader_engine.py`, `requirements.txt`, `launch.bat`.

New runtime files: `excel_input.py`, `excel_ui.py`, `excel_executor.py`. New template: `DealCloud_Deal_List_Template.xlsx`. Documentation and test files are also updated/added. `setup.bat` still installs `requirements.txt` and remains the existing setup route.

The original one-off workbook request list is **not embedded**. This app reads the file users upload. The one-off tool can remain separate and is not overwritten by these app files.

## Output location changed to keep paths shorter

Both modes now save new jobs beneath:

```text
%USERPROFILE%\DealCloud Memos\Downloads\<readable batch name>
%USERPROFILE%\DealCloud Memos\Previews\<readable batch name>
```

For the example user, the base is `C:\Users\dsturdevant\DealCloud Memos`. This is not the app's nested extraction folder. Old app-local `Downloads`, `Previews` or `runs` folders are not moved/deleted. The app displays the exact new path and offers an Open folder button on Windows.

Excel mode uses short OS-user-temp cache paths and bounded readable destination names. All client/quarter labels are sanitized; no Excel cell is treated as an arbitrary filesystem path. Too-long destinations are reported rather than changing Windows system policies. Local missing-path/permission failures are not retried as transient attachment network failures. Interrupted jobs may leave confidential temporary/partial files; review and delete them under your retention policy.

## Credentials — both modes

Upload your existing local JSON with exactly these keys:

```json
{
  "site_url": "https://your-site.dealcloud.com",
  "client_id": "your-client-id",
  "client_secret": "your-client-secret"
}
```

Use the HTTPS tenant base URL with no path, query, embedded login or custom port. A valid-format upload does not prove authentication or file-read permission. The blank JSON template is also included.

Credentials stay in the local app/worker processes and are passed to the worker through stdin, not file or command-line arguments. Only the child worker's environment is set for authentication; the Streamlit process environment is not changed. The uploaded file is not intentionally copied to run output. A completed JSON is nevertheless a **plaintext secret** on disk: restrict access, never upload it to this chat/GitHub/email, and follow organizational policy. “Clear credentials” removes the current UI upload, not the original disk file or forensic memory traces.

Literal client ID/secret redaction of worker stdout/stderr and known diagnostics is defensive best effort, not a guarantee against encoded SDK errors, other logs, crash dumps or interrupted cleanup. Inspect outputs before sharing. Binary memo contents are not modified by redaction.

## Excel deal-list mode — recommended workflow

1. Choose **Excel deal list** at the top.
2. Upload private credentials JSON and choose site timezone.
3. Download the blank Excel template or upload an existing `.xlsx`.
4. Choose worksheet/header row and map the columns. Review mapped rows and fix any validation errors; invalid rows block the job rather than disappearing silently.
5. Choose default memo rule, audience preference and **save layout** (see below). With *Folder per client*, map the Client column, and optionally Year and Quarter for `Client/Year/Quarter` subfolders. Optional Memo Type cells override only their rows.
6. Click **Preview Excel list**. This reads schema/records for the requested names and linked histories, but performs no attachment metadata or file-download calls.
7. Review preview audit rows, matched IDs, intended stages, unmatched/ambiguous names, missing candidates and coverage warnings.
8. Check the authorization box, then click **Download Excel-list memos**. A completed preview for the exact credentials, workbook/mapping and settings is required. Changing these inputs invalidates authorization. Population-level read/selection errors or zero eligible candidates block authorization. Coverage warnings or individual unmatched/ambiguous names can mark the result partial without blocking matched candidates: review those warnings before authorizing.
9. Review the download CSV and counts. Candidate availability does not guarantee file access. “Processing completed” means the run finished, not that every request succeeded.

**Initial safety cap:** 5 candidate attempts per population (not 5 per deal). Attempts include failures/skips; copies to multiple clients do not trigger extra API downloads for the same deal/policy. Uncheck the limit after a small verified test if you want the full list. The cap is not a byte quota or API-read limit, and preview counts all eligible candidates before the cap.

Preview and download make fresh reads; the preview is not a frozen transactional snapshot. Credentials and tenant data must still be authorized for each operation.

### Save layout: one folder vs. folder per client

| Layout | Result |
|---|---|
| **One folder (unique memos)** — default | Each unique deal/memo-policy is saved once, directly in the batch folder. Client/Quarter columns are not shown or used. |
| **Folder per client** | One folder per Client value, each holding every memo requested for that client (optional `Quarter` subfolder). |

For *Folder per client*, put one row per client/deal pair — e.g. if five clients hold Fund A, list Fund A five times with each client name. Fund A is matched, selected and **downloaded once**, then copied into all five client folders; the audit CSV keeps one row per client request. Client names are grouped ignoring case and extra spaces (the folder uses the first spelling in the workbook); a numeric client code is treated as text; blank clients go to a `No Client` folder. Duplicate rows for the same client + deal + policy (+ quarter) share one copy rather than creating near-identical files. The attempt cap counts download attempts, not copies.

### Excel format and column mapping

Only **Deal Name** is required. A name-only list uses the default population selected in the app. For mixed types, include Population/Structure.

| Column | Required? | Behavior |
|---|---|---|
| Deal Name | Yes | Exact DealCloud deal/fund name. No fuzzy matching or guessed aliases. |
| Population / Structure | Optional | Primaries, CoInvestments, Secondaries; supported aliases include Primary Partnership, Direct Transaction, Secondary Transaction. Blank/unmapped uses app default. |
| Client Name | Required for *Folder per client*; ignored otherwise | Local folder name only. Blank → `No Client` folder. Does not affect tenant matching or permissions. |
| Year | Optional, *Folder per client* only | e.g. `2026`, `FY2026`. Adds a year subfolder and fills in the year for quarters typed without one. |
| Quarter(s) | Optional, *Folder per client* only | Q1–Q4 in common formats, e.g. `Q3 2026`, `2026 Q3`, `3Q26`; several separated by semicolons. Adds a quarter subfolder, never an IC-date filter. |
| Memo Type | Optional | Specific stage, Priority fallback, or Latest available. Blank = app default. |

Unrelated columns—including source workbook Deal Entry IDs, amounts, status and compliance columns—are ignored unless mapped. **Workbook IDs are never assumed to be DealCloud IDs.** Use the worksheet dropdown to avoid exception/exclusion sheets. Automatic suggestions help but must be reviewed; users can map differently named headers manually.

Limits: `.xlsx` only; at most 10 MiB compressed, 80 MiB declared expanded ZIP contents, 3,000 data rows and 100 columns per selected list sheet. Header row may be 1–50. No passwords, macros, duplicate headers or formulas in mapped cells. Paste values first. Large formatted empty ranges may exceed limits; copy the list into a clean sheet. This is bounded parsing, not a security guarantee for arbitrary untrusted spreadsheets.

The raw workbook is not intentionally written to disk. Mapped deal/client/quarter requests and source row numbers **are saved in run reports**, so treat those as confidential. The template contains fictional placeholder data only; replace/delete its sample row before use.

### Memo selection — an explicit choice, not a guessed default

Default Excel rule: **Priority fallback**. Users may choose another rule, or set Memo Type per row.

| Rule | What is eligible / what wins |
|---|---|
| Final | Final only; no Screening/Follow-On/Update fallback. |
| Screening | Screening only. |
| Follow-On | Follow-On only. |
| Update | Update/Addendum only. Addendum is an alias for the combined group. |
| Priority fallback | Final → Screening → Follow-On → Update; within each stage Internal then Client, newest IC date within each audience. |
| Latest available | Newest IC date across all four supported stages. With both audiences enabled, Internal wins only as a same-date tie-break, not over a newer Client memo. |

Audience choices: **Internal then Client**, **Internal only**, **Client only**. In a specific stage, the first means newest Internal first, then older Internal candidates, then Client fallback. Priority fallback respects stage before audience. Latest available respects date before audience.

All Excel rules stop after one successfully downloaded memo per unique population/parent/effective-policy combination. Failures/skips can fall through to older eligible candidates. Different policies for the same deal intentionally can produce multiple files. Repeated requests for the same deal/policy reuse the selected source memo and copy it to the requested destinations.

Unknown stages, undated events and known supplementary/impact-assessment materials remain excluded. Filename exclusions are not content inspection. Strict filename verification is **on by default in Excel mode**. Source extensions are preserved; files are not converted to PDF. Filenames and CSV audit show the **actual selected stage**—a Screening memo is never labeled Final.

**Unlike the recent one-off script, Excel Priority fallback includes Update/Addendum as the fourth stage.** If you only want one stage, choose it explicitly. There is no independent custom fallback-order editor in this version.

No Excel memo-date window, IC-approved flag, recommendation, current status, asset-class or other filter-based settings are applied. Quarter columns describe folder placement, not memo eligibility or a historical as-of cutoff. A Q1 folder can contain a memo issued after Q1.

### Year and quarter folders

With *Folder per client*, optional **Year** and **Quarter** columns add subfolders: `Client/2026/Q3/`. A Year with no Quarter saves to `Client/2026/`; a Quarter with no year saves to `Client/Q3/`.

Quarter cells accept Q1–Q4 in common formats, all saved as the same folder: `Q3 2026`, `2026 Q3`, `Q3-26`, `Q3'26`, `3Q26`, `Q3 FY26`, `Quarter 3 2026`, or just `Q3` / `3` when a Year column supplies the year. Separate several with semicolons (`Q1; Q3`). Year cells accept `2026`, `FY2026` or `FY26`. A quarter whose year disagrees with the Year column is flagged as an invalid row.

If one client lists the same deal (same memo rule) in more than one quarter of the same year, choose:

- **Save a copy in every quarter listed** (default).
- **Only the earliest quarter**, e.g. Q1 over Q2/Q3/Q4.
- **Only the latest quarter**, e.g. Q4 over Q1/Q2/Q3.

Skipped quarters appear in the audit as `SUPPRESSED` rows and do not make the run partial. Different years, different clients and different memo rules are always kept independently. The memo itself is still downloaded only once.

Folders describe where you want the memo filed, not when it was written. Year/Quarter never filter memos by IC date, so a `2026/Q1` folder can contain a memo dated later.

### Exact matching and safety

Names are queried in the mapped population and must resolve to a unique accessible parent ID. Local comparison ignores case/repeated whitespace but preserves punctuation, legal suffixes and fund numerals. Server name comparisons may still cause a nonmatch before local normalization; review the audit, do not assume a near-match is intended.

Populations use the supplied mapping: Fund/DiligenceActivity, CoInvestmentDeal/CIMemo, SecondaryDeal/SecondaryMemo. These are tenant-specific mappings to validate. Name queries and parent-reference memo reads are scoped; unrelated returned names/IDs cause an error rather than silently broadening to full objects. No unfiltered fallback is issued. Missing/unreturned memo streams produce coverage warnings: counts describe accessible mapped streams, not proof of complete tenant history. Required matching/linkage fields still fail clearly.

No create/update/delete API operations are part of Excel execution. Client grouping is not an entitlement check. An Internal memo in a client-named folder is **not** automatically approved for distribution to that client.

## Existing filter-based search

Select **Filter-based search** at the top to keep the existing workflow:

1. Upload credentials and choose timezone, inclusive IC dates and populations.
2. Choose priority (one successful memo per parent) or all eligible files, stages and audiences.
3. Set Primaries-only Approved by IC? (blank/unknown is not No) and optional Recommendation values.
4. Load/refresh available parent-filter dropdown values, choose Structure/Asset Class/Strategy/SubStrategy/Status filters where mapped, then preview.
5. Review the preview and authorize download.

Dropdown labels come from accessible parents linked to memos in the chosen IC window, **not every configured tenant choice**. They are not cascading filters. Empty = unrestricted; OR within each field, AND across fields. Active missing fields fail rather than being silently ignored. Existing defaults are retained: Primaries Final/Approved by IC = Yes; CoInvestments AssetClass = Private Equity; Secondaries Structure = Secondary Transaction. A selected default unobserved in the window remains active with a warning until cleared.

The attempt cap defaults to 5 **per population in both modes**. Old filter-mode selection logic is retained, including Internal Final → Client Final → Internal Screening → Client Screening → Internal Follow-On → Client Follow-On → Internal Update/Addendum → Client Update/Addendum. All mode does not stop at one successful file. Approval filtering applies only to Primaries. Unknown filename handling remains the filter mode's own checkbox/default, not Excel's.

The v3.3 semicolon-separated attachment-ID fix remains in the shared engine. Optional Secondary TeamDiscussionMemo absence is warned and excluded instead of blocking canonical fields; it is not silently declared covered. Canonical mapped fields remain required in filter-mode execution. Server IC-window queries are checked locally and linked parents fetched in batches.

## Output and audit

Excel batches contain selected files plus a `Reports` folder: directly in the batch folder for *One folder*, or under `<Client>/[<Year>/][<Quarter>/]` for *Folder per client* (batch named “By client - …”). Client folder names get up to about 48 characters with your normal Windows profile path (more without Year/Quarter folders). Longer names are shortened in the middle on whole words, so the family name and the distinguishing ending both survive: `Hamilton Lane Strategic Opportunities Fund VIII (Offshore) LP` → `Hamilton Lane~Fund VIII (Offshore) LP`. Files are named `<Deal> - <IC date> - <Stage> - <Audience>.pdf`, with no random code.

Excel reports:

- `excel_results.csv`: row-level matching, policy, candidate count, actual/intended stage/date/audience, status, file path, client/quarter and original source row.
- `downloaded_files.csv`: successful local destinations used to construct the optional result ZIP.
- `candidate_attempts.csv`: actual attempted event/attachment details and results.
- `run_settings.json`: mapped requests/settings and audit summary, no intentionally persisted credentials.
- `excel_issues.json`: source/data-quality notes where available; not an exhaustive exclusion log.
- `worker.log`, `result.json`: internal diagnostics/status, not included in the results ZIP.

Filter batches retain `download_summary.csv`, `downloaded_files.csv`, `candidate_attempts.csv`, `event_issues.csv`, `run_settings.json`, optional `population_error.txt`, and worker diagnostics. Multiple populations may have separate report folders.

Browser result ZIP creation is optional and limited to **150 MiB of source files**, not a download quota. Known reports plus files referenced in download logs are included, not credentials, original uploads, arbitrary dropped-in files or internal worker logs/status. Larger outputs remain available locally. Excel CSV File paths are relative to the batch root and remain usable after extracting its ZIP. Filter-mode CSV paths retain their original local absolute paths. Browser tables show at most 2,000 audit rows; full CSVs are saved locally.

## Local-only security, cancellation and retention

The launcher binds to **127.0.0.1** and disables Streamlit usage telemetry. Loopback is not authentication and does not isolate users/apps on a shared computer. Do not expose this app to LAN/internet or host it remotely as-is. No organizational login, TLS, central secret manager, per-user authorization or reviewed server retention is implemented. An approved shared deployment needs separate design/security review.

One job at a time is allowed per browser session and mode switching is disabled while it runs. There is no machine-wide concurrency cap. Use one session at a time. Changing settings during a job does not change its submitted payload. Use the Stop button before stopping the server. Closing the browser can orphan a worker and reconnection may not restore controls; carefully identify the relevant Python process in Task Manager if necessary. Interrupted jobs leave incomplete files/logs and possibly OS-temp caches. Review/delete under approved retention rules; prior batches are not deleted.

Do not publicly publish uploaded client lists, credentials, downloaded memos or diagnostics containing tenant data. The distributed package/template has no actual client list or credentials. Tests use invented labels and simulated file bytes only.

## Troubleshooting (technical)

- **No new Excel mode / upload still limited to 1 MiB:** confirm all v4 files replaced the files beside the launcher you actually run; stop/restart the server using the new `launch.bat` (10 MiB uploader setting). Do not launch an older nested copy.
- **openpyxl missing:** rerun `setup.bat`, or `.\dealcloud-memo-venv\Scripts\python.exe -m pip install -r requirements.txt` in that app folder.
- **Download disabled:** fix invalid mapped rows/credentials, run a completed preview for current input/settings and check authorization. Partial population-level preview errors block download. The 5-attempt cap can intentionally leave candidates unattempted.
- **No match / ambiguous:** verify exact tenant name and mapped population. IDs in the workbook are not used as shortcuts. Audit unmatched rows instead of broad/fuzzy matching.
- **No candidates:** check requested stage, missing/undated histories, audience and accessible schema/files. This does not prove a memo does not exist. A Follow-On in the deal name does not make an event's Stage Follow-On.
- **HTTP 404 vs FileNotFoundError:** HTTP file-not-found can mean unavailable attachment/route/permissions; local FileNotFoundError can be a save-path problem. Review the actual diagnostic. Excel mode uses short cache paths; an unusually long profile/output destination can still fail with a clear path warning.
- **Port 8501 in use:** close the other local app or change the launcher's port and browser URL consistently.
- **Package install/proxy/certificate errors:** retain the full error, use approved repositories/network settings, and check version compatibility. Never disable certificate verification as a workaround.

## Tests

Run all distributed tests from the app folder:

```powershell
.\dealcloud-memo-venv\Scripts\python.exe -m unittest discover -v -p "test_*.py"
```

No live developer connection/download is performed by this command. Offline parser/SDK simulation/stub-UI checks do not establish live tenant schema, actual SDK network/file behavior, Windows .bat execution or real Streamlit browser correctness. Start with a small known list and the default 5-attempt cap, compare a sample of downloaded files to the tenant, then disable the cap for a full verified run. See `TEST_RESULTS.md` for the checks actually completed.
