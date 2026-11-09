# v4 validation record

## Completed

**140 offline tests passed, zero failures and zero errors.** The combined suite was run after integration of the Excel UI, isolated worker action, shared engine, portable file paths and ZIP handling.

- 48 existing regression tests for filter mode, option loading, Secondary optional fields, semicolon-separated attachment IDs, and stubbed UI startup.
- 68 Excel executor tests for defensive request validation, scoped exact matching, all supported populations, mixed policies, stage priority versus newest-date selection, audience preferences, deduplication, Q1/Q2 precedence, file copies, strict filenames, attempt caps, safe paths, errors and audits.
- 15 Excel parser/stub-UI tests for template reading, mapping, population aliases, per-row rules, formulas, invalid rows, workbook bounds, actual source-row numbers, empty startup, preview enablement and stale authorization blocking.
- 4 worker dispatch/redaction tests for the Excel action, partial-result handling, invalid job paths and masking of literal test secrets.
- 5 cross-module tests using the real shared engine and a fake SDK transport: preview with the worker's precreated Reports folder, no preview attachment requests, semicolon-ID supplementary exclusion, actual Follow-On filenames, Q1 suppression, relative-path ZIP packaging, worker-to-real-executor dispatch, and preview authorization rules.

The user's existing Client_Deal_Summary workbook was parsed in memory: all 162 source rows validated with zero mapped-row errors. No client names, source workbook or private request list from that check is included in the app ZIP. This checks formatting/mapping, not live tenant matching or file access.

All distributed Python sources were syntax/AST checked. The blank workbook template and package ZIP are verified during packaging. Windows launchers are stored with Windows line endings.

## Test boundaries

No real tenant credentials, live DealCloud authentication, tenant data reads or memo downloads were performed by the developer for v4. All SDK test responses use fake transports. Synthetic file bytes are not actual investment memos.

Streamlit was not installed in the analysis runtime. UI regression tests execute top-level code against a lightweight stub; they are NOT actual Streamlit browser tests. The tests do not verify Windows .bat execution, browser widget behavior, real file-dialog behavior, the installed SDK's live network/file semantics, Windows subprocess cancellation, orphan-worker handling, concurrent sessions, or package resolution on the user's computer.

No production security audit, penetration test or shared-server deployment validation was performed. Performance on large lists or histories is not established.

## First live validation

1. Upgrade all v4 files, run setup.bat to install openpyxl, then restart launch.bat.
2. Use an approved local Windows computer and private credentials JSON.
3. Start with two or three known deals, explicit populations and the default 5-attempt cap per population.
4. Test Final-only, one fallback example, and Latest available separately; compare the selected stage/date/audience with DealCloud.
5. Preview must make no attachment downloads. Review matched IDs, unresolved names and coverage warnings before authorizing.
6. Verify output files open correctly and their stage/date labels match the actual source; verify Q1/Q2 precedence and client folders using a known duplicate.
7. Prepare a ZIP and confirm the referenced memos and reports are included but credentials, original upload and worker logs are absent. Review reports for secrets before sharing.
8. Disable the attempt cap only after the small pilot is correct. Validate and pin your organization's known-working package versions before broad distribution.
