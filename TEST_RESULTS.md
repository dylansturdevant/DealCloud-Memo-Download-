# Validation record

## Completed checks

- Six Python source files passed Python syntax/AST checks.
- **21 offline unittest cases passed**, with zero failures and zero errors.
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
