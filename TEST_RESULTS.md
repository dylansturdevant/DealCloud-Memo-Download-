# Validation record

## Completed checks

- Ten Python source files passed Python syntax/AST checks.
- **48 offline tests passed**, with zero failures and zero errors.
- Seven multi-reference regression tests cover semicolon-delimited numeric IDs, normalization, rejection of numbers in filenames, alignment with individual display filenames, supplementary exclusion, candidate selection and event building.
- The three supplied diagnostic ID/name pairs were checked in memory: each yielded one retained memo attachment and one excluded supplementary attachment. No diagnostic tenant data is included in the distribution, and no live attachment download was performed.
- Six Secondary regression cases verify missing optional schema/returned columns produce explicit coverage warnings, available TeamDiscussion streams remain included, required canonical field absence still fails, and canonical downloads work without the optional stream.
- Startup hotfix: corrected the initial option-loading check to avoid referring to options_ready/missing_active before assignment; the later preview check now requires loaded options and no active unavailable fields.
- Three additional regression tests execute app.py with a lightweight Streamlit stub: no credentials, credentials before options are loaded, and loaded options for all populations. These are not real browser tests.
- Dropdown tests cover observed tenant labels, missing-field reporting, population read failures, unfiltered linked-parent option scope, population validation, and per-population mappings for Primaries, CoInvestments and Secondaries.
- Additional output-layout tests cover flat single-population memo placement, removal of nested output/timestamp layers, readable filesystem-safe batch names, collision-safe naming, and the batch itself as the output directory.
- Test runtime: Python 3.14.8, pandas 3.0.6. This is the analysis runtime, not a recommendation to use that Python version on Windows.
- DealCloud SDK access was replaced with a fake in the offline tests; no actual credentials, authentication, tenant reads, or real memo downloads were used.

## Covered by simulated tests

- Preview makes no attachment metadata or file-download requests.
- Download branch applies the supplied engine's primary approval and memo selection logic.
- Memo reads use an IC-window query; parent reads are scoped to linked IDs.
- Priority tier ordering versus chronological all-mode ordering.
- Per-parent attachment-ID deduplication.
- Blank/unknown approval is not treated as No; primary approval restriction does not apply to CoInvestments.
- Supplementary and undated candidate exclusion; strict unknown-filename skipping.
- Population attempt cap, population-error reporting, parent filters, and missing active fields.
- CSV formula-prefix neutralization and timezone conversion.
- Credentials file structure and URL validation; template placeholder rejection.
- Preview fingerprint changes when inputs change.
- Literal credential redaction across split console writes.
- Results ZIP excludes credential files and worker logs.
- Worker output-directory validation prevents escaping the job directory.

## Not validated here

- Windows `.bat` execution, installed-package resolution on a user's machine, and the complete Streamlit browser workflow.
- Subprocess lifecycle, cancellation, session reconnect behavior, or simultaneous browser sessions under Windows.
- Live DealCloud schema, actual SDK signatures/responses, API rate limits, authentication, permissions, or real file transfers.
- Byte-for-byte memo correctness or throughput on large runs.
- Production security, penetration testing, or shared-server deployment.

## Recommended first live check

Use an approved Windows computer, one population, a narrow date range and the 5-attempt cap. Upload a locally stored credentials JSON, preview, download a small batch, verify downloaded memos and CSVs manually, inspect logs for sensitive values before sharing, and confirm credentials are absent from the result archive. Validate package versions in that environment before distributing broadly.
