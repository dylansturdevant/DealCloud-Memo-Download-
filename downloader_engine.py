"""DealCloud memo downloader — a read-only, single-file teaching example.

INSTALL: python -m pip install dealcloud-sdk pandas tzdata
SET locally: DEALCLOUD_SITE_URL, DEALCLOUD_CLIENT_ID, DEALCLOUD_CLIENT_SECRET
RUN: python download_dealcloud_memos_v11.py

Edit only the SETTINGS section to change dates and deal filters.
Object/field discovery and SDK value handling are kept below the main example.
Tenant schema mappings are explicit for all three populations; Attachment discovery is retained.
No DealCloud connection was used to test this file.
"""
from __future__ import annotations

import ast
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from dealcloud_sdk import DealCloud


# =============================================================================
# 1. SETTINGS — edit these dates and filters.
# =============================================================================
START_IC_DATE = "2026-01-01"
END_IC_DATE = "TODAY"                 # Or, for example, "2025-12-31".

# "all": download EVERY matching memo; no seniority/fallback selection.
# "priority": download ONE per deal using the original priority/fallback order.
DOWNLOAD_MODE = "priority"

# [] = all supported stages. Pick any combination, e.g. ["Final", "Screening"].
# Supported: "Final", "Screening", "Follow-On", "Update" (includes Addendum).
MEMO_STAGES = ["Final"]

# PRIMARY MEMO: the actual "Approved by IC?" Yes/No flag shown in the UI.
# ["Yes"] = true; ["No"] = explicit false; [] = either, including blanks.
# Missing/unknown values are NOT treated as No. Applies to Primaries ONLY:
# no equivalent flag has been verified for the other two populations.
MEMO_APPROVED_BY_IC = ["Yes"]

# Optional separate Recommendation filter. Leave [] if you ONLY want the
# Yes/No flag above. For example, ["Approved"] would add another restriction.
MEMO_RECOMMENDATIONS = []

# Source field per population. Change Primaries to "Recommendation" if you
# want the proposed recommendation rather than the IC-confirmed recommendation.
# Other populations retain their original fields; no unverified IC field alias.
RECOMMENDATION_FIELD_BY_POPULATION = {
    "Primaries": "Recommendation",
    "CoInvestments": "Recommendation",
    "Secondaries": "Recommendation",
}

# Optional test cap applies independently to EACH selected population.
# None means unlimited; set 5 for a small test before a larger download.
# This is a file-count safeguard, NOT a byte/storage limit or API-read limit.
MAX_CANDIDATE_ATTEMPTS_PER_POPULATION = None

POPULATIONS = ["Primaries"]

# Each population has its OWN parent-record filters. [] means unrestricted.
# Fund structure values must come from actual data; schema does not enumerate
# reference-field values. To require the exact value you see in DealCloud,
# set e.g. "Structure": ["Primary Partnership"] under Primaries.
# The default Primaries stream includes ALL Fund structures with eligible
# DiligenceActivity memos; it is not a verified Primary Partnership-only subset.
FILTERS_BY_POPULATION = {
    "Primaries": {
        "Structure": [],
        "AssetClass": [],
        "Strategy": [],
        "SubStrategy": [],
    },
    "CoInvestments": {
        "Structure Type": [],
        "AssetClass": ["Private Equity"],
        "Strategy": [],
        "SubStrategy": [],
        "Status": [],
    },
    "Secondaries": {
        "Structure": ["Secondary Transaction"],
        "AssetClass": [],
        "Strategy_1": [],  # API name for the active field displayed as Strategy.
        "SubStrategy": [],
        "Status": [],
    },
}
# Enter actual tenant values in quotes; [] means no restriction.
# OR within each field's list; AND across active fields.
# AssetClass/SubStrategy are the parent record fields, NOT memo calculations
# or the separate Private Markets Asset Class field.
# Active fields are requested on the linked-parent reads and filtered locally.
# This can reduce downloads, not the initial IC-window memo-query volume.

# Mappings from the supplied tenant schema. Active missing fields fail clearly.
# Use API name Strategy_1 for secondaries: Strategy is marked DO NOT USE.
# Fund has no exact Status field in the supplied schema; add a status filter
# only using the actual API/display field you intend, not an invented alias.
POPULATION_CONFIG = {
    "Primaries": {"parent": "Fund", "names": ["FundName"],
        "memo_object": "DiligenceActivity", "reference": "Fund",
        "internal": ["InternalMemo"], "client": ["ClientReadyMemo", "ClientVersionofMemo"]},
    "CoInvestments": {"parent": "CoInvestmentDeal", "names": ["ProjectName"],
        "memo_object": "CIMemo", "reference": "CIDeal",
        "internal": ["InternalMemo"], "client": ["ClientReadyMemo"]},
    "Secondaries": {"parent": "SecondaryDeal", "names": ["DealName"],
        "memo_object": "SecondaryMemo", "reference": "SecondaryDeal",
        "internal": ["INTERNALMEMO", "TeamDiscussionMemo"], "client": ["ClientMemo"]},
}

# Match the original script: metadata is optional. A filename from the memo
# field is used if metadata is missing. With neither, download as .bin and
# mark it for review; filename-based supplementary exclusion cannot be verified.
# Set True if unknown filenames must instead be skipped.
REQUIRE_VERIFIABLE_FILENAME = False

# [] = both. Or choose ["Internal"] or ["Client"].
MEMO_AUDIENCES = []

# In BOTH modes: apply the IC-date window, skip undated events, and exclude
# known supplementary/impact-assessment materials. Unknown filenames are logged
# for review when REQUIRE_VERIFIABLE_FILENAME is False. "all" does not mean all file types
# in DealCloud: it means all eligible memo attachments in these memo streams.

# Legacy helper compatibility; actual filters are FILTERS_BY_POPULATION.
DEAL_FILTERS = {}

SITE_TIMEZONE = os.getenv("DEALCLOUD_SITE_TIMEZONE", "America/New_York").strip()
OUTPUT_ROOT = Path(__file__).resolve().parent / "DealCloud_Memo_Downloads"
# Each run gets its own folder. Prior downloads are never removed.


# =============================================================================
# 2. MAIN EXAMPLE — connect, read, filter, select, download.
#    Helpers below handle the SDK/schema details from the original script.
# =============================================================================
# Only the fields used for linking, selection, filenames and active filters
# are requested. No unfiltered fallback if the tenant rejects a query.
PARENT_ID_BATCH_SIZE = 100


def api_field_selection(dc, object_name, requested):
    fields = schema_items(dc.get_fields(object_name), ("fields", "items", "data", "rows", "root"))
    aliases = {}
    for item in fields:
        api = metadata_value(item, ["apiName", "api_name", "fieldApiName", "field_api_name"])
        display = metadata_value(item, ["displayName", "display_name", "name", "fieldName", "label"])
        identifier = metadata_value(item, ["id", "fieldId", "field_id"])
        if api:
            for label in (api, display, identifier):
                if label:
                    aliases.setdefault(normalize_name(label), api)
    selected = []
    for label in requested:
        api = aliases.get(normalize_name(label))
        if not api:
            raise KeyError(f"Required field {label!r} missing on {object_name}")
        if api not in selected:
            selected.append(api)
    return selected


def filtered_read(dc, object_name, fields, query, resolve):
    started = time.monotonic()
    print(f"Reading FILTERED {object_name} ({resolve}), {len(fields)} fields...", flush=True)
    last_report = [0.0]
    def progress(current_rows, estimated_total):
        now = time.monotonic()
        if now - last_report[0] >= 3:
            print(f"  {object_name}: received {current_rows:,} rows (estimate {estimated_total:,})", flush=True)
            last_report[0] = now
    # 'name' is the documented resolution for this installed SDK; unlike the
    # prior display/name retry loop, no unsupported 'display' request is made.
    frame = as_dataframe(dc.read_data(
        object_id=object_name, output="pandas", resolve=resolve,
        fields=fields, query=json.dumps(query), include_nulls=True,
        column_headers="api", progress_callback=progress,
    ))
    if frame.empty:
        # APIs can return no columns for an empty result.
        frame = pd.DataFrame(columns=["DealCloud Entry ID", *fields])
    print(f"  {object_name}: {len(frame):,} rows in {time.monotonic()-started:.1f}s", flush=True)
    return frame


def enforce_local_ic_window(frame, object_name, resolution):
    """Keep valid rows even when the server returns extra dates or nulls.

    No out-of-window or undated record can become a download candidate.
    An empty result is reported, not interpreted as proof of an empty tenant.
    """
    if frame.empty:
        return frame
    date_col = find_column(frame, ["ICDate"])
    if not date_col:
        raise KeyError(f"ICDate missing from {object_name} query result")
    parsed = frame[date_col].map(parse_event_date)
    keep = parsed.map(lambda d: not pd.isna(d) and START_DATE <= d < END_DATE_EXCLUSIVE)
    nulls = int(parsed.isna().sum())
    outside = int((~keep & parsed.notna()).sum())
    if nulls or outside:
        print(f"WARNING: {object_name} ({resolution}) query returned {outside:,} out-of-window and {nulls:,} undated rows; excluding those rows, NOT aborting the population.", flush=True)
        valid = parsed.dropna()
        if not valid.empty:
            print(f"  Returned IC Date span: {valid.min():%Y-%m-%d} through {valid.max():%Y-%m-%d}. Server filtering is not fully verified; actual speed benefit may be reduced.", flush=True)
    selected = frame.loc[keep].copy()
    print(f"  IC-date check ({resolution}): kept {len(selected):,} / {len(frame):,} rows", flush=True)
    return selected


def recommendation_field_for_object(object_name):
    for population, config in POPULATION_CONFIG.items():
        if config["memo_object"] == object_name:
            field_name = RECOMMENDATION_FIELD_BY_POPULATION.get(population)
            if not isinstance(field_name, str) or not field_name.strip():
                raise ValueError(f"Set a recommendation field for {population}")
            return field_name
    raise ValueError(f"No recommendation mapping for {object_name}")


def read_windowed_memos(dc, config):
    obj = config["memo_object"]
    recommendation_fields = [recommendation_field_for_object(obj)]
    if obj == "SecondaryMemo":
        recommendation_fields.append("TeamDiscussionRecommendation")
    if obj == "DiligenceActivity":
        recommendation_fields.append("RecommendationApprovedbyIC")
    fields = api_field_selection(dc, obj, [config["reference"], "ICDate", "Stage", *recommendation_fields, *config["internal"], *config["client"]])
    # Convert local inclusive calendar days to [start, next-day) UTC bounds.
    # Localizing each boundary separately accounts for daylight saving changes.
    start = START_DATE.tz_localize(SITE_TIMEZONE).tz_convert("UTC").isoformat().replace("+00:00", "Z")
    end = END_DATE_EXCLUSIVE.tz_localize(SITE_TIMEZONE).tz_convert("UTC").isoformat().replace("+00:00", "Z")
    # Explicit AND avoids relying on the server/SDK to combine two operators
    # stored in one field condition. Local filtering remains authoritative.
    query = {"$and": [{"ICDate": {"$gte": start}}, {"ICDate": {"$lt": end}}]}
    print(f"Requested server IC Date bounds: {start} <= ICDate < {end}", flush=True)
    raw = filtered_read(dc, obj, fields, query, "id")
    attach_field_schema_aliases(dc, obj, raw)
    raw = enforce_local_ic_window(raw, obj, "id")
    if raw.empty:
        return raw.copy(), raw
    names = filtered_read(dc, obj, fields, query, "name")
    attach_field_schema_aliases(dc, obj, names)
    names = enforce_local_ic_window(names, obj, "name")
    validate_event_pairing(names, raw)
    return names, raw


def read_linked_parents(dc, config, raw, filters):
    obj = config["parent"]
    # Empty filters do not require the corresponding field to exist.
    requested = [config["names"][0]] + [name for name, values in filters.items() if values]
    fields = api_field_selection(dc, obj, requested)
    ref_col = find_column(raw, [config["reference"]])
    if ref_col is None:
        raise KeyError(f"Memo reference {config['reference']} missing")
    ids = sorted({ref for cell in raw[ref_col] for ref in extract_reference_ids(cell)}, key=int)
    print(f"Fetching only {len(ids):,} linked {obj} records, in batches of {PARENT_ID_BATCH_SIZE}", flush=True)
    frames = []
    for offset in range(0, len(ids), PARENT_ID_BATCH_SIZE):
        batch = ids[offset:offset+PARENT_ID_BATCH_SIZE]
        query = {"EntryId": {"$in": [int(value) for value in batch]}}
        frame = filtered_read(dc, obj, fields, query, "name")
        attach_field_schema_aliases(dc, obj, frame)
        id_col = find_column(frame, EVENT_FIELD_CANDIDATES["entry_id"])
        if id_col is None:
            raise KeyError(f"EntryId missing from {obj} result")
        actual = set(frame[id_col].map(normalize_entry_id))
        if not actual.issubset(set(batch)):
            raise ValueError(f"{obj} returned unrelated parent IDs; stopping rather than reading the full object")
        frames.append(frame)
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        id_col = find_column(combined, EVENT_FIELD_CANDIDATES["entry_id"])
        if len(combined) < len(ids):
            print(f"WARNING: {len(ids)-len(combined)} linked parent records were not returned; check permissions", flush=True)
    else:
        combined = pd.DataFrame(columns=["DealCloud Entry ID", *fields])
    attach_field_schema_aliases(dc, obj, combined)
    return combined


PREVIEW_ONLY = False
FIXED_OUTPUT_DIRECTORY = None


def main() -> None:
    validate_settings()
    if len(set(POPULATIONS)) != len(POPULATIONS) or any(p not in POPULATION_CONFIG for p in POPULATIONS):
        raise ValueError("POPULATIONS must contain unique supported population names")
    if not POPULATIONS:
        raise ValueError("Choose at least one population")
    if MAX_CANDIDATE_ATTEMPTS_PER_POPULATION is not None and (
        isinstance(MAX_CANDIDATE_ATTEMPTS_PER_POPULATION, bool)
        or not isinstance(MAX_CANDIDATE_ATTEMPTS_PER_POPULATION, int)
        or MAX_CANDIDATE_ATTEMPTS_PER_POPULATION < 1
    ):
        raise ValueError("Attempt limit must be a positive integer or None")
    dc = connect_to_dealcloud()
    output = Path(FIXED_OUTPUT_DIRECTORY) if FIXED_OUTPUT_DIRECTORY else OUTPUT_ROOT / pd.Timestamp.now(tz=SITE_TIMEZONE).strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=bool(FIXED_OUTPUT_DIRECTORY))
    reports_root = output / "Reports"
    reports_root.mkdir(exist_ok=True)
    manifest = {
        "start_ic_date": str(START_DATE.date()), "end_ic_date": str(END_DATE_INCLUSIVE.date()),
        "site_timezone": SITE_TIMEZONE, "populations": POPULATIONS,
        "filters": FILTERS_BY_POPULATION, "download_mode": DOWNLOAD_MODE,
        "memo_stages": MEMO_STAGES, "memo_audiences": MEMO_AUDIENCES,
        "memo_recommendations": MEMO_RECOMMENDATIONS,
        "primary_memo_approved_by_ic": MEMO_APPROVED_BY_IC,
        "recommendation_fields": RECOMMENDATION_FIELD_BY_POPULATION,
        "max_candidate_attempts_per_population": MAX_CANDIDATE_ATTEMPTS_PER_POPULATION,
        "require_verifiable_filename": REQUIRE_VERIFIABLE_FILENAME,
        "mapping": POPULATION_CONFIG, "server_filtered_reads": True, "preview_only": PREVIEW_ONLY, "population_results": [],
    }
    def write_manifest():
        (reports_root / "run_settings.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_manifest()
    binary_field = None
    binary_checked = False
    total_downloaded = 0
    for population in POPULATIONS:
        config = POPULATION_CONFIG[population]
        print(f"\n=== {population.upper()} ===", flush=True)
        memo_dir = output if len(POPULATIONS) == 1 else output / population
        memo_dir.mkdir(parents=True, exist_ok=True)
        folder = reports_root if len(POPULATIONS) == 1 else reports_root / population
        folder.mkdir(parents=True, exist_ok=True)
        summary, attempts, issues = [], [], []
        try:
            # Server-side IC-date filter FIRST. No full Fund/object read.
            names, raw = read_windowed_memos(dc, config)
            ic_flags = {}
            if population == "Primaries":
                flag_column = find_column(raw, ["RecommendationApprovedbyIC"])
                id_column = find_column(raw, EVENT_FIELD_CANDIDATES["entry_id"])
                if flag_column is None or id_column is None:
                    raise KeyError("Primary memo IC-approval flag or EntryId missing; cannot apply Yes/No filter")
                ic_flags = {normalize_entry_id(row[id_column]): normalize_ic_approval(row[flag_column]) for _, row in raw.iterrows()}
                print(f"Approved by IC? counts: Yes={sum(v == 'Yes' for v in ic_flags.values())}, No={sum(v == 'No' for v in ic_flags.values())}, Blank/unknown={sum(v is None for v in ic_flags.values())}", flush=True)
                print(f"Approved by IC? filter: {MEMO_APPROVED_BY_IC or 'all, including blanks'}", flush=True)
            entities = read_linked_parents(dc, config, raw, FILTERS_BY_POPULATION.get(population, {}))
            matching = filter_population(entities, config["names"], FILTERS_BY_POPULATION.get(population, {}))
            print(f"Matched {len(matching):,} / {len(entities):,} linked parent records")
            histories = {key: DealHistory(key) for key in matching.index}
            source_objects = {}
            # Read the memo object once in each resolution. Build each mapped
            # attachment field as its own stream so all-mode does not silently
            # coalesce away a second Internal/Client memo field.
            if not matching.empty:
                for audience, fields in (("Internal", config["internal"]), ("Client", config["client"])):
                    for file_field in fields:
                        if not find_column(names, [file_field]) and not find_column(raw, [file_field]):
                            raise KeyError(f"Mapped memo field {file_field!r} not found on {config['memo_object']}")
                        source = f"{config['memo_object']}/{file_field}"
                        source_objects[source] = config["memo_object"]
                        overrides = {
                            "date": ["ICDate"], "stage": ["Stage"],
                            "internal_memo": [file_field] if audience == "Internal" else [],
                            "client_ready_memo": [file_field] if audience == "Client" else [],
                            "recommendation": ["TeamDiscussionRecommendation"] if file_field == "TeamDiscussionMemo" else [RECOMMENDATION_FIELD_BY_POPULATION[population]],
                        }
                        events, problems = build_events(source, names, raw,
                            reference_candidates=[config["reference"]], field_overrides=overrides)
                        issues.extend(problems)
                        for event in deduplicate_events(events):
                            event.ic_approved = ic_flags.get(event.event_id)
                            if event.deal_id in histories:
                                histories[event.deal_id].events.append(event)
            observed = sorted({e.recommendation or "(blank)" for h in histories.values() for e in h.events if e.in_window and memo_stage_priority(e) is not None})
            print(f"Memo recommendation field: {config['memo_object']}.{RECOMMENDATION_FIELD_BY_POPULATION[population]}", flush=True)
            if population == "Secondaries":
                print("TeamDiscussionMemo uses TeamDiscussionRecommendation", flush=True)
            print(f"Memo recommendation values in window: {observed}", flush=True)
            print(f"Recommendation filter: {MEMO_RECOMMENDATIONS or 'all (including blank)'}", flush=True)
            candidate_lists = {key: selected_memo_candidates(history) for key, history in histories.items()}
            count = sum(len(choices) for choices in candidate_lists.values())
            print(f"Eligible candidates after date/stage/audience filters: {count:,}")
            if PREVIEW_ONLY:
                for deal_id, deal in matching.iterrows():
                    choices = candidate_lists[deal_id]
                    summary.append({"Population": population, "Deal ID": deal_id,
                        "Deal": deal["_deal_name"],
                        "Status": "Preview: candidates found" if choices else "Preview: no eligible candidate",
                        "Eligible Candidates": len(choices), "Candidates Tried": 0, "Files Downloaded": 0})
                manifest["population_results"].append({"population": population,
                    "matched_parents": len(matching), "eligible_candidates": count,
                    "attempted_candidates": 0, "downloaded": 0})
                print(f"PREVIEW ONLY: {count:,} candidates; no attachment metadata or file downloads requested.", flush=True)
                continue
            if count and not binary_checked:
                binary_checked = True
                try:
                    binary_field = discover_attachment_binary_field(dc, ATTACHMENT_OBJECT, ATTACHMENT_BINARY_FIELD)
                except Exception as exc:
                    print(f"WARNING: Attachment binary field unavailable: {exc}")
            for deal_id, deal in matching.iterrows():
                name = deal["_deal_name"]
                choices = candidate_lists[deal_id]
                saved, tried = 0, 0
                for number, choice in enumerate(choices, start=1):
                    if MAX_CANDIDATE_ATTEMPTS_PER_POPULATION is not None and len(attempts) >= MAX_CANDIDATE_ATTEMPTS_PER_POPULATION:
                        break
                    event, kind, _, parent_field, _ = choice
                    result = save_candidate(dc, deal_id, name, choice, memo_dir, binary_field, source_objects)
                    attempts.append({"Population": population, "Deal ID": deal_id, "Deal": name,
                                     "Candidate": number, "Source": event.source, "Event ID": event.event_id,
                                     "Memo IC Date": event.event_date.strftime("%Y-%m-%d"),
                                     "Stage": event.stage_name, "Recommendation": event.recommendation, "Approved by IC?": getattr(event, "ic_approved", None), "Field": parent_field, "Audience": kind, **result})
                    print(f"  {name} / {parent_field}: {result['Status']}", flush=True)
                    tried += 1
                    if result["File"]:
                        saved += 1
                        if DOWNLOAD_MODE == "priority":
                            break
                if not choices:
                    status = "No eligible memo matching date/stage/audience settings"
                elif not tried:
                    status = "Not attempted: population candidate limit reached"
                elif not saved:
                    status = "No download; see candidate_attempts.csv"
                elif tried < len(choices) and DOWNLOAD_MODE == "all":
                    status = "Downloaded partial batch; population candidate limit reached"
                else:
                    status = "Downloaded"
                summary.append({"Population": population, "Deal ID": deal_id, "Deal": name, "Status": status,
                                "Eligible Candidates": len(choices), "Candidates Tried": tried, "Files Downloaded": saved})
            downloaded = sum(row["Files Downloaded"] for row in summary)
            total_downloaded += downloaded
            manifest["population_results"].append({"population": population, "matched_parents": len(matching),
                "eligible_candidates": count, "attempted_candidates": len(attempts), "downloaded": downloaded})
            print(f"{population}: downloaded {downloaded:,}; attempted {len(attempts):,}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            (folder / "population_error.txt").write_text(error, encoding="utf-8")
            manifest["population_results"].append({"population": population, "error": error})
            print(f"ERROR in {population}: {error}; continuing with other populations", flush=True)
        finally:
            write_csv(summary, folder / "download_summary.csv", ["Population", "Deal ID", "Deal", "Status",
                      "Eligible Candidates", "Candidates Tried", "Files Downloaded"])
            columns = ["Population", "Deal ID", "Deal", "Candidate", "Source", "Event ID", "Memo IC Date",
                       "Stage", "Recommendation", "Approved by IC?", "Field", "Audience", "Status", "File"]
            write_csv(attempts, folder / "candidate_attempts.csv", columns)
            write_csv([row for row in attempts if row["File"]], folder / "downloaded_files.csv", columns)
            write_csv(issues, folder / "event_issues.csv", ["Source", "Event ID", "Issue", "Stage", "Date"])
            write_manifest()
    print(f"\nDone: {total_downloaded:,} memos downloaded. Output: {output}")
    if any("error" in r for r in manifest["population_results"]):
        print("Some populations failed; inspect population_error.txt and run_settings.json.")



# =============================================================================
# 3. SUPPORTING HELPERS — normally no changes needed below this line.
# =============================================================================
DEALCLOUD_SITE_URL = os.getenv("DEALCLOUD_SITE_URL", "").strip()
DEALCLOUD_CLIENT_ID = os.getenv("DEALCLOUD_CLIENT_ID", "").strip()
DEALCLOUD_CLIENT_SECRET = os.getenv("DEALCLOUD_CLIENT_SECRET", "").strip()
SECONDARY_DEAL_OBJECT = os.getenv("DEALCLOUD_SECONDARY_DEAL_OBJECT", "SecondaryDeal").strip()
SECONDARY_IC_MEMO_OBJECT = os.getenv("DEALCLOUD_SECONDARY_IC_MEMO_OBJECT", "").strip()
SECONDARY_TEAM_DISCUSSION_OBJECT = os.getenv("DEALCLOUD_SECONDARY_TEAM_DISCUSSION_OBJECT", "").strip()
ATTACHMENT_OBJECT = os.getenv("DEALCLOUD_ATTACHMENT_OBJECT", "Attachment").strip()
ATTACHMENT_BINARY_FIELD = os.getenv("DEALCLOUD_ATTACHMENT_BINARY_FIELD", "").strip()
# Optional environment overrides above are only for ambiguous tenant schemas.
RUN_DATE = pd.Timestamp.now(tz=SITE_TIMEZONE).tz_localize(None).normalize()
START_DATE = pd.Timestamp(START_IC_DATE).normalize()
END_DATE_INCLUSIVE = RUN_DATE if END_IC_DATE.upper() == "TODAY" else pd.Timestamp(END_IC_DATE).normalize()
END_DATE_EXCLUSIVE = END_DATE_INCLUSIVE + timedelta(days=1)
ATTACHMENT_DOWNLOAD_MAX_ATTEMPTS = 4
ATTACHMENT_RETRY_BASE_SECONDS = 2.0
ATTACHMENT_RETRY_MAX_SECONDS = 20.0
ATTACHMENT_REQUEST_PAUSE_SECONDS = 0.15
DEALCLOUD_CONNECTION_MAX_ATTEMPTS = 5
DEALCLOUD_CONNECTION_RETRY_BASE_SECONDS = 3.0
DEALCLOUD_CONNECTION_RETRY_MAX_SECONDS = 30.0
INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


def validate_settings() -> None:
    for key in ("DEALCLOUD_SITE_URL", "DEALCLOUD_CLIENT_ID", "DEALCLOUD_CLIENT_SECRET"):
        if not os.getenv(key, "").strip():
            raise ValueError(f"Set the {key} environment variable before running.")
    if pd.isna(START_DATE) or pd.isna(END_DATE_INCLUSIVE) or START_DATE > END_DATE_INCLUSIVE:
        raise ValueError("Choose a valid start/end date range.")
    if START_DATE.tzinfo is not None or END_DATE_INCLUSIVE.tzinfo is not None:
        raise ValueError("Use date-only settings, e.g. 2025-12-31.")
    if DOWNLOAD_MODE not in {"all", "priority"}:
        raise ValueError('DOWNLOAD_MODE must be "all" or "priority".')
    for label, chosen, allowed in (
        ("MEMO_STAGES", MEMO_STAGES, {"final", "screening", "followon", "update", "addendum"}),
        ("MEMO_AUDIENCES", MEMO_AUDIENCES, {"internal", "client"}),
    ):
        if not isinstance(chosen, list) or any(not isinstance(v, str) or normalize_name(v) not in allowed for v in chosen):
            raise ValueError(f"Invalid {label}; use [] or supported values: {sorted(allowed)}")
    if not isinstance(MEMO_RECOMMENDATIONS, list) or any(not isinstance(v, str) or not normalize_name(v) for v in MEMO_RECOMMENDATIONS):
        raise ValueError("MEMO_RECOMMENDATIONS must be a list of nonempty labels, or []")
    if not isinstance(MEMO_APPROVED_BY_IC, list) or any(not isinstance(v, str) or v.casefold() not in {"yes", "no"} for v in MEMO_APPROVED_BY_IC):
        raise ValueError('MEMO_APPROVED_BY_IC must be ["Yes"], ["No"], ["Yes", "No"], or []')
    if not isinstance(DEAL_FILTERS, dict):
        raise ValueError("DEAL_FILTERS must be a dictionary of field names to lists.")
    for name, accepted in DEAL_FILTERS.items():
        if not isinstance(accepted, list) or any(not isinstance(v, str) or not normalize_name(v) for v in accepted):
            raise ValueError(f"Filter {name!r} must be a list of nonempty text values, or [].")


def normalize_ic_approval(value):
    """Normalize boolean SDK cells without confusing blank/unknown with false."""
    if is_missing(value):
        return None
    value = parse_structured(value)
    if isinstance(value, dict):
        for key in ("value", "name", "displayName", "label"):
            if key in value:
                return normalize_ic_approval(value[key])
        return None
    text = str(value).strip().casefold()
    if text in {"true", "yes", "1", "1.0"}:
        return "Yes"
    if text in {"false", "no", "0", "0.0"}:
        return "No"
    return None


def selected_memo_candidates(history):
    # Reuse the original eligibility checks; all-mode does NOT use tier order.
    choices = priority_memo_candidates(history)
    wanted_stages = {normalize_name(v) for v in MEMO_STAGES}
    if "addendum" in wanted_stages:
        wanted_stages.add("update")
    wanted_audiences = {normalize_name(v) for v in MEMO_AUDIENCES}
    selected = []
    for choice in choices:
        event, kind, _, _, _ = choice
        stage = ("final", "screening", "followon", "update")[memo_stage_priority(event)]
        audience = "internal" if kind == "InternalMemo" else "client"
        if wanted_stages and stage not in wanted_stages:
            continue
        if wanted_audiences and audience not in wanted_audiences:
            continue
        if event.source.startswith("DiligenceActivity/") and MEMO_APPROVED_BY_IC:
            wanted_ic = {v.casefold() for v in MEMO_APPROVED_BY_IC}
            actual_ic = getattr(event, "ic_approved", None)
            if actual_ic is None or actual_ic.casefold() not in wanted_ic:
                continue
        if MEMO_RECOMMENDATIONS:
            wanted = {normalize_name(v) for v in MEMO_RECOMMENDATIONS}
            actual = {normalize_name(v) for v in human_values(event.recommendation)}
            if not wanted.intersection(actual):
                continue
        selected.append(choice)
    if DOWNLOAD_MODE == "all":
        # Chronological processing only; no stage/audience seniority or fallback.
        selected.sort(key=lambda c: (-c[0].event_date.value, c[0].source,
                                     c[0].event_id, c[1]))
    # The same attachment linked multiple times is downloaded once per deal.
    unique, seen = [], set()
    for choice in selected:
        event, _, raw, field_name, _ = choice
        ref = first_reference_id(raw)
        key = ("attachment", ref) if ref else ("direct", event.source, event.event_id, field_name)
        if key not in seen:
            unique.append(choice)
            seen.add(key)
    return unique


def filter_population(frame, name_candidates, filters):
    id_col = find_column(frame, EVENT_FIELD_CANDIDATES["entry_id"])
    name_col = find_column(frame, name_candidates)
    if not id_col or not name_col:
        raise KeyError(f"Missing parent EntryId or name. Columns: {list(frame.columns)}")
    if not isinstance(filters, dict):
        raise ValueError("Population filters must be a dictionary")
    selected = frame.copy()
    for field_name, accepted in filters.items():
        if not isinstance(accepted, list) or any(not isinstance(v, str) or not normalize_name(v) for v in accepted):
            raise ValueError(f"Filter {field_name} must be a list of nonempty strings or []")
        if not accepted:
            continue
        column = find_column(frame, [field_name])
        if column is None:
            raise KeyError(f"Active filter field {field_name!r} not found; not substituting another field")
        wanted = {normalize_name(v) for v in accepted}
        observed = sorted({v for cell in frame[column] for v in human_values(cell)})
        print(f"Filter {field_name} [{column}]: {accepted}")
        if not any(normalize_name(v) in wanted for v in observed):
            print(f"WARNING: no accepted values found. Observed {field_name} values: {observed[:60]}")
        selected = selected.loc[selected[column].map(lambda cell: bool(wanted.intersection(normalize_name(v) for v in human_values(cell))))].copy()
    selected.index = selected[id_col].map(normalize_entry_id)
    if any(not value for value in selected.index) or not selected.index.is_unique:
        raise ValueError("Parent IDs missing or duplicated")
    selected["_deal_name"] = selected[name_col].map(human_text)
    if selected["_deal_name"].eq("").any():
        raise ValueError("A matching parent record has a blank name")
    return selected



def validate_event_pairing(names: pd.DataFrame, raw: pd.DataFrame) -> None:
    if names.empty and raw.empty:
        return
    keys = []
    for frame in (names, raw):
        col = find_column(frame, EVENT_FIELD_CANDIDATES["entry_id"])
        if not col:
            raise KeyError("Memo reads must expose EntryId.")
        values = frame[col].map(normalize_entry_id)
        if values.eq("").any() or values.duplicated().any():
            raise ValueError("Memo reads contain missing or duplicate EntryIds.")
        keys.append(set(values))
    if keys[0] != keys[1]:
        raise ValueError("Memo display/ID reads differ; rerun for a consistent snapshot.")


def write_csv(rows: list, path: Path, columns: list[str]) -> None:
    frame = pd.DataFrame(rows, columns=columns)
    def safe(value):
        if isinstance(value, str):
            value = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", value)
            if value.lstrip().startswith(("=", "+", "-", "@")):
                return "'" + value
        return value
    for column in frame.columns:
        frame[column] = frame[column].map(safe)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def candidate_filename(value):
    """Accept structured filename values and plain display strings with an extension."""
    value = parse_structured(value)
    if isinstance(value, dict):
        for key in ("fileName", "filename", "name", "displayName"):
            if key in value and not is_missing(value[key]):
                return str(value[key])
    elif isinstance(value, (list, tuple)):
        for item in value:
            name = candidate_filename(item)
            if name:
                return name
    elif isinstance(value, str):
        name = clean_display_text(value)
        if re.search(r"\.[A-Za-z0-9]{1,12}$", name):
            return name
    return ""


def save_candidate(dc, deal_id, deal_name, choice, memo_dir, binary_field, source_objects):
    event, kind, value, parent_field, display = choice
    attachment_id = first_reference_id(value)
    if attachment_id:
        if not binary_field:
            return {"Status": "FAILED: Attachment binary field unavailable", "File": ""}
        owner, entry_id, file_field = ATTACHMENT_OBJECT, attachment_id, binary_field
    else:
        owner, entry_id, file_field = source_objects[event.source], event.event_id, parent_field
    path = None
    try:
        # Original behavior: optional metadata, then filename from the memo field.
        filename = candidate_filename(display) or candidate_filename(value)
        metadata_note = ""
        try:
            metadata, _ = run_attachment_request_with_retry(
                lambda: dc.download_attachment_metadata(object_id=owner, entry_id=entry_id, field_id=file_field),
                label=f"metadata {entry_id}")
            if hasattr(metadata, "model_dump"):
                metadata = metadata.model_dump(mode="json")
            filename = metadata_value(metadata, ["fileName", "filename", "name"]) or filename
        except Exception as exc:
            metadata_note = f"metadata unavailable ({type(exc).__name__}); "
        if not filename:
            if REQUIRE_VERIFIABLE_FILENAME:
                return {"Status": "SKIPPED: filename unavailable; strict filename setting enabled", "File": ""}
            metadata_note += "filename unknown; REVIEW supplementary exclusion; "
        elif metadata_note:
            metadata_note += "using memo field filename; "
        if is_supplementary_memo_text(filename):
            return {"Status": f"SKIPPED supplementary material: {filename}", "File": ""}
        extension = Path(filename.replace("\\", "/")).suffix
        if not re.fullmatch(r"\.[A-Za-z0-9]{1,12}", extension):
            extension = ".bin"
        # Human-readable names; record IDs stay in the CSV logs, not filenames.
        # Different files with the same readable name receive (2), (3), etc.
        tier = memo_stage_priority(event)
        stage = ("Final", "Screening", "Follow-On", "Update")[tier] if tier is not None else safe_filename(event.stage_name, 25)
        audience = "Internal" if kind == "InternalMemo" else "Client"
        title = safe_filename(deal_name, max_length=105)
        stem = f"{title} - {event.event_date:%Y-%m-%d} - {stage} - {audience}"
        extension = extension.lower()
        path = memo_dir / f"{stem}{extension}"
        suffix = 2
        while path.exists():
            path = memo_dir / f"{stem} ({suffix}){extension}"
            suffix += 1
        def download():
            path.unlink(missing_ok=True)
            dc.download_file(entry_id=entry_id, field_id=file_field, output_path=str(path))
            if not path.is_file() or path.stat().st_size == 0:
                raise IOError("Download returned no file or an empty file")
        _, count = run_attachment_request_with_retry(download, label=f"file {entry_id}", cleanup_path=path)
        return {"Status": f"Downloaded ({count} request attempt(s)); {metadata_note}".rstrip("; "), "File": str(path)}
    except Exception as exc:
        if path is not None:
            path.unlink(missing_ok=True)
        return {"Status": f"FAILED: {type(exc).__name__}: {exc}", "File": ""}



SECONDARY_EVENT_REFERENCE_CANDIDATES = [
    "SecondaryDeal",
    "Secondary Deal",
]

EVENT_FIELD_CANDIDATES = {
    "entry_id": ["DealCloud Entry ID", "EntryId", "Entry ID", "Id", "ID"],
    # Replaced with strict population-specific candidates in build_events().
    "deal_reference": [],
    "date": [
        "ICDate",
        "IC Date",
        "TeamDiscussionDate",
        "Team Discussion Date",
        "MemoDate",
        "Memo Date",
        "DiligenceDate",
        "Diligence Date",
        "EventDate",
        "Date",
    ],
    "stage": [
        "Stage",
        "TeamDiscussionStage",
        "Team Discussion Stage",
        "MemoStage",
        "Memo Stage",
        "DiligenceStage",
        "Diligence Stage",
        "EventType",
        "Event Type",
        "Type",
    ],
    "recommendation": [
        "Recommendation",
        "ScreeningRecommendation",
        "Screening Recommendation",
        "ScreeningRecCI",
        "Screening Rec CI",
        "Decision",
    ],
    "client_ready_memo": [
        "ClientReadyMemo",
        "Client Ready Memo",
        "ClientMemo",
        "Client Memo",
    ],
    "internal_memo": [
        "InternalMemo",
        "Internal Memo",
        "TeamDiscussionMemo",
        "Team Discussion Memo",
        "Memo",
        "MemoFile",
    ],
}

SECONDARY_IC_FIELD_OVERRIDES = {
    "date": ["ICDate", "IC Date"],
    "stage": ["Stage", "MemoStage", "Memo Stage"],
}

SECONDARY_TEAM_FIELD_OVERRIDES = {
    "date": ["ICDate", "IC Date"],
    "stage": [
        "TeamDiscussionStage",
        "Team Discussion Stage",
        "Stage",
    ],
    "internal_memo": [
        "TeamDiscussionMemo",
        "Team Discussion Memo",
        "InternalMemo",
        "Internal Memo",
        "Memo",
    ],
}

def normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())

def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().lower() in {"nan", "nat", "none"}
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False

def parse_structured(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(text)
        except Exception:
            continue
        if isinstance(parsed, (dict, list, tuple, set)):
            return parsed
    return value

def unique_preserving_order(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            output.append(cleaned)
            seen.add(key)
    return output

def clean_display_text(value: Any) -> str:
    """Decode HTML entities, remove tags, and normalize visible whitespace."""
    text = html.unescape(str(value))
    text = re.sub(r"<\s*br\s*/?\s*>", " | ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip(" |\t\r\n")

def human_values(value: Any) -> list[str]:
    """Extract readable names without discarding ordinary text."""
    if is_missing(value):
        return []
    value = parse_structured(value)

    if isinstance(value, dict):
        for key in ("name", "displayName", "display", "label", "fileName", "filename"):
            if key in value and not is_missing(value[key]):
                return human_values(value[key])
        collected: list[str] = []
        for item in value.values():
            if isinstance(item, (dict, list, tuple, set)):
                collected.extend(human_values(item))
        return unique_preserving_order(collected)

    if isinstance(value, (list, tuple, set)):
        collected = []
        for item in value:
            collected.extend(human_values(item))
        return unique_preserving_order(collected)

    text = clean_display_text(value)
    if not text:
        return []

    # Handle SDK strings such as "{'id': 1, 'name': 'New York'}; {...}".
    matches = re.findall(
        r"[\"'](?:name|displayName|label)[\"']\s*:\s*"
        r"(?:\"([^\"]*)\"|'([^']*)')",
        text,
    )
    if matches:
        return unique_preserving_order(
            clean_display_text(first or second) for first, second in matches
        )

    # Multi-select display values are commonly semicolon-delimited.
    if ";" in text and not re.search(r"\bhttps?://", text, flags=re.I):
        return unique_preserving_order(
            clean_display_text(part) for part in text.split(";")
        )
    return [text]

def human_text(value: Any, separator: str = " | ") -> str:
    return separator.join(human_values(value))

def extract_reference_ids(value: Any) -> list[str]:
    """Extract reference entry IDs from scalar or structured SDK values."""
    if is_missing(value):
        return []
    value = parse_structured(value)

    if isinstance(value, dict):
        ids: list[str] = []
        for key in ("id", "Id", "ID", "entryId", "EntryId", "entry_id"):
            if key in value and not is_missing(value[key]):
                ids.extend(extract_reference_ids(value[key]))
        if ids:
            return unique_preserving_order(ids)
        for item in value.values():
            if isinstance(item, (dict, list, tuple, set)):
                ids.extend(extract_reference_ids(item))
        return unique_preserving_order(ids)

    if isinstance(value, (list, tuple, set)):
        ids: list[str] = []
        for item in value:
            ids.extend(extract_reference_ids(item))
        return unique_preserving_order(ids)

    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [str(value)]
    if isinstance(value, float) and value.is_integer():
        return [str(int(value))]

    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.0)?", text):
        return [re.sub(r"\.0$", "", text)]

    keyed = re.findall(
        r"[\"']?(?:id|entryId|EntryId|entry_id)[\"']?\s*[:=]\s*[\"']?(\d+)",
        text,
    )
    return unique_preserving_order(keyed)

def first_reference_id(value: Any) -> str | None:
    ids = extract_reference_ids(value)
    return ids[0] if ids else None

def find_column(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    lookup: dict[str, str] = {}
    for column in frame.columns:
        lookup.setdefault(normalize_name(column), str(column))
    # read_data commonly returns API-name columns, while business users know
    # the display names. Schema aliases connect both names to the same column.
    for alias, column in frame.attrs.get("column_aliases", {}).items():
        if column in frame.columns:
            lookup.setdefault(normalize_name(alias), str(column))
    for candidate in candidates:
        found = lookup.get(normalize_name(candidate))
        if found is not None:
            return found
    return None

def find_columns(frame: pd.DataFrame, candidates: Iterable[str]) -> list[str]:
    """Return every matching column in candidate priority order."""
    output: list[str] = []
    for candidate in candidates:
        column = find_column(frame, [candidate])
        if column is not None and column not in output:
            output.append(column)
    return output

def normalize_entry_id(value: Any) -> str:
    if is_missing(value):
        return ""
    return re.sub(r"\.0$", "", str(value).strip())

def as_dataframe(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        frame = value.copy()
    elif hasattr(value, "to_pandas"):
        frame = value.to_pandas()
    elif hasattr(value, "to_dataframe"):
        frame = value.to_dataframe()
    elif hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, dict) and "rows" in dumped:
            dumped = dumped["rows"]
        frame = pd.json_normalize(dumped)
    else:
        frame = pd.DataFrame(value)

    recognized_ids = [
        "DealCloud Entry ID",
        "EntryId",
        "Entry ID",
        "entry_id",
        "EntryId_from_index",
    ]
    if not isinstance(frame.index, pd.RangeIndex):
        existing_id = find_column(frame, recognized_ids)
        if existing_id:
            frame = frame.reset_index(drop=True)
        else:
            index_name = frame.index.name or "EntryId_from_index"
            frame = frame.reset_index().rename(columns={"index": index_name})

    entry_column = find_column(frame, recognized_ids)
    if entry_column and entry_column != "DealCloud Entry ID":
        frame.rename(columns={entry_column: "DealCloud Entry ID"}, inplace=True)
    return frame

def read_object(dc: DealCloud, object_name: str, resolve: str) -> pd.DataFrame:
    """Read an object, tolerating SDK v1 signature/resolution differences."""
    resolve_values = [resolve]
    if resolve == "display":
        resolve_values.append("name")

    attempts = []
    for resolve_value in unique_preserving_order(resolve_values):
        attempts.extend(
            [
                lambda rv=resolve_value: dc.read_data(
                    object_name, resolve=rv, output="pandas"
                ),
                lambda rv=resolve_value: dc.read_data(
                    object_id=object_name, resolve=rv, output="pandas"
                ),
            ]
        )

    errors: list[str] = []
    for number, attempt in enumerate(attempts, start=1):
        try:
            frame = as_dataframe(attempt())
            print(
                f"    {object_name} ({resolve}): "
                f"{len(frame):,} rows x {len(frame.columns):,} columns"
            )
            return frame
        except Exception as exc:
            errors.append(f"attempt {number}: {type(exc).__name__}: {exc}")
    raise RuntimeError(f"Unable to read {object_name} ({resolve}): " + " | ".join(errors))

def metadata_value(item: Any, names: Iterable[str]) -> str:
    if hasattr(item, "model_dump"):
        item = item.model_dump(mode="json")
    if isinstance(item, dict):
        for name in names:
            if name in item and not is_missing(item[name]):
                return str(item[name])
    for name in names:
        if hasattr(item, name):
            value = getattr(item, name)
            if not is_missing(value):
                return str(value)
    return ""

def attach_field_schema_aliases(
    dc: DealCloud,
    object_name: str,
    *frames: pd.DataFrame,
) -> None:
    """Map each field's API name, display name, and ID to returned columns."""
    try:
        fields: Any = dc.get_fields(object_name)
        if hasattr(fields, "model_dump"):
            fields = fields.model_dump(mode="json")
        if isinstance(fields, dict):
            extracted = None
            for key in ("fields", "items", "data", "rows", "root"):
                if key in fields and isinstance(fields[key], (list, dict)):
                    extracted = fields[key]
                    break
            fields = extracted if extracted is not None else list(fields.values())
        if isinstance(fields, dict):
            fields = list(fields.values())
        if not isinstance(fields, list):
            raise TypeError(f"get_fields returned {type(fields).__name__}")

        alias_counts: list[int] = []
        for frame in frames:
            column_lookup = {
                normalize_name(column): str(column) for column in frame.columns
            }
            aliases = dict(frame.attrs.get("column_aliases", {}))

            for field_metadata in fields:
                api_name = metadata_value(
                    field_metadata,
                    ["apiName", "api_name", "fieldApiName", "field_api_name"],
                )
                display_name = metadata_value(
                    field_metadata,
                    [
                        "displayName",
                        "display_name",
                        "name",
                        "fieldName",
                        "field_name",
                        "label",
                    ],
                )
                field_id = metadata_value(
                    field_metadata, ["id", "fieldId", "field_id"]
                )
                identifiers = unique_preserving_order(
                    [api_name, display_name, field_id]
                )
                actual_column = next(
                    (
                        column_lookup[normalize_name(identifier)]
                        for identifier in identifiers
                        if normalize_name(identifier) in column_lookup
                    ),
                    None,
                )
                if actual_column is None:
                    continue
                for identifier in identifiers:
                    aliases.setdefault(normalize_name(identifier), actual_column)

            frame.attrs["column_aliases"] = aliases
            alias_counts.append(len(aliases))

        if alias_counts:
            print(
                f"    {object_name}: attached field-schema aliases "
                + "/".join(f"{count:,}" for count in alias_counts)
            )
    except Exception as exc:
        # Direct API-name matching remains available if schema field lookup is
        # unavailable to this API client.
        print(
            f"    WARNING: Could not load field aliases for {object_name}: "
            f"{type(exc).__name__}: {exc}"
        )

def schema_items(value: Any, collection_keys: Iterable[str]) -> list[Any]:
    """Normalize SDK schema responses to a list of metadata records."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        for key in collection_keys:
            if key in value and isinstance(value[key], (list, dict)):
                value = value[key]
                break
        else:
            value = list(value.values())
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, list):
        raise TypeError(f"Schema response was {type(value).__name__}, not a list")
    return value

def object_schema_choices(dc: DealCloud) -> list[dict[str, str]]:
    choices: list[dict[str, str]] = []
    for item in schema_items(
        dc.get_objects(), ("objects", "items", "data", "rows", "root")
    ):
        api_name = metadata_value(
            item, ["apiName", "api_name", "name", "objectId", "id"]
        )
        if not api_name:
            continue
        choices.append(
            {
                "api": api_name,
                "display": metadata_value(
                    item, ["displayName", "display_name", "name"]
                ),
                "singular": metadata_value(
                    item, ["singularName", "singular_name"]
                ),
                "plural": metadata_value(item, ["pluralName", "plural_name"]),
            }
        )
    return choices

def field_schema_identifiers(dc: DealCloud, object_name: str) -> set[str]:
    identifiers: set[str] = set()
    fields = schema_items(
        dc.get_fields(object_name),
        ("fields", "items", "data", "rows", "root"),
    )
    for item in fields:
        for value in (
            metadata_value(
                item,
                ["apiName", "api_name", "fieldApiName", "field_api_name"],
            ),
            metadata_value(
                item,
                [
                    "displayName",
                    "display_name",
                    "name",
                    "fieldName",
                    "field_name",
                    "label",
                ],
            ),
        ):
            if value:
                identifiers.add(normalize_name(value))
    return identifiers

def raw_metadata_value(item: Any, names: Iterable[str]) -> Any:
    if hasattr(item, "model_dump"):
        item = item.model_dump(mode="json")
    if isinstance(item, dict):
        for name in names:
            if name in item and not is_missing(item[name]):
                return item[name]
    for name in names:
        if hasattr(item, name):
            value = getattr(item, name)
            if not is_missing(value):
                return value
    return None

def discover_attachment_binary_field(
    dc: DealCloud,
    object_name: str,
    configured_field: str,
) -> str:
    """Resolve the Attachment object's binary/document field ID."""
    fields = schema_items(
        dc.get_fields(object_name),
        ("fields", "items", "data", "rows", "root"),
    )
    candidates: list[tuple[int, str, str, str]] = []
    configured_key = normalize_name(configured_field)

    for item in fields:
        field_id = metadata_value(item, ["id", "fieldId", "field_id"])
        api_name = metadata_value(
            item, ["apiName", "api_name", "fieldApiName", "field_api_name"]
        )
        display_name = metadata_value(
            item,
            ["displayName", "display_name", "name", "fieldName", "label"],
        )
        identifiers = {
            normalize_name(value)
            for value in (field_id, api_name, display_name)
            if value
        }
        field_type = raw_metadata_value(
            item,
            ["fieldType", "field_type", "fieldTypeId", "field_type_id", "type"],
        )
        if isinstance(field_type, dict):
            field_type_text = " ".join(str(value) for value in field_type.values())
        else:
            field_type_text = str(field_type or "")
        type_key = normalize_name(field_type_text)
        name_key = normalize_name(f"{api_name} {display_name}")
        is_binary_type = bool(
            re.search(r"(^|\D)13($|\D)", field_type_text)
            or any(word in type_key for word in ("binary", "document", "file"))
        )

        if configured_key and configured_key in identifiers:
            if not is_binary_type:
                raise RuntimeError(
                    f"Configured attachment field {configured_field!r} exists "
                    f"but is not a binary/document field (type={field_type_text})."
                )
            resolved = field_id or api_name or configured_field
            print(
                f"    Attachment binary field confirmed: {resolved} "
                f"({display_name or api_name})"
            )
            return resolved

        score = 0
        # DealCloud field type 13 is binary/document. Type 16 is image and is
        # accepted only as a lower-priority fallback.
        if re.search(r"(^|\D)13($|\D)", field_type_text):
            score += 200
        elif re.search(r"(^|\D)16($|\D)", field_type_text):
            score += 50
        if any(word in type_key for word in ("binary", "document", "file")):
            score += 150
        if any(word in name_key for word in ("file", "document", "binary", "content")):
            score += 30
        if score and (field_id or api_name):
            candidates.append(
                (score, field_id or api_name, display_name or api_name, field_type_text)
            )

    if configured_field:
        raise RuntimeError(
            f"Configured attachment binary field {configured_field!r} was not "
            f"found on {object_name}. Remove the override to auto-discover it."
        )
    if not candidates:
        raise RuntimeError(
            f"Could not find a binary/document field on {object_name}. Set "
            "DEALCLOUD_ATTACHMENT_BINARY_FIELD to its API name or numeric ID."
        )

    candidates.sort(key=lambda item: (-item[0], str(item[1])))
    best_score = candidates[0][0]
    best = [item for item in candidates if item[0] == best_score]
    if len(best) != 1:
        descriptions = ", ".join(
            f"{field_id} ({name}; type={field_type})"
            for _, field_id, name, field_type in best
        )
        raise RuntimeError(
            "Multiple attachment binary fields matched equally: "
            + descriptions
            + ". Set DEALCLOUD_ATTACHMENT_BINARY_FIELD explicitly."
        )
    _, resolved, name, field_type = best[0]
    print(
        f"    Discovered attachment binary field: {resolved} "
        f"({name}; type={field_type})"
    )
    return resolved

def schema_has_any(identifiers: set[str], candidates: Iterable[str]) -> bool:
    return any(normalize_name(candidate) in identifiers for candidate in candidates)

@dataclass
class Event:
    source: str
    event_id: str
    deal_id: str
    event_date: pd.Timestamp | pd.NaT
    event_type: str
    stage_name: str
    recommendation: str
    client_ready_value: Any = None
    internal_value: Any = None
    client_ready_display: Any = None
    internal_display: Any = None
    client_ready_field: str | None = None
    internal_field: str | None = None

    @property
    def in_window(self) -> bool:
        return (
            not pd.isna(self.event_date)
            and self.event_date >= START_DATE
            and self.event_date < END_DATE_EXCLUSIVE
        )

@dataclass
class DealHistory:
    deal_id: str
    events: list[Event] = field(default_factory=list)

    def events_of_type(self, types: set[str]) -> list[Event]:
        return [event for event in self.events if event.event_type in types]

def parse_event_date(value: Any) -> pd.Timestamp | pd.NaT:
    if is_missing(value):
        return pd.NaT
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return pd.NaT
    if isinstance(parsed, pd.DatetimeIndex):
        if len(parsed) == 0:
            return pd.NaT
        parsed = parsed[0]
    timestamp = pd.Timestamp(parsed)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(SITE_TIMEZONE).tz_localize(None)
    return timestamp.normalize()

def classify_event(stage_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", stage_name.lower()).strip()
    if not normalized:
        return ""
    if "screen" in normalized:
        return "Screening"
    if (
        "follow on" in normalized
        or "followon" in normalized.replace(" ", "")
        or "incremental" in normalized
    ):
        return "Follow-On"
    if "final" in normalized:
        return "Final"
    if "update" in normalized or "addendum" in normalized:
        return "Update"
    return ""

def pair_frames(
    display_frame: pd.DataFrame, id_frame: pd.DataFrame
) -> list[tuple[pd.Series, pd.Series]]:
    display_id_column = find_column(display_frame, EVENT_FIELD_CANDIDATES["entry_id"])
    id_id_column = find_column(id_frame, EVENT_FIELD_CANDIDATES["entry_id"])

    if not display_id_column or not id_id_column:
        raise KeyError(
            "Display and ID reads must both expose EntryId; refusing unsafe "
            "position-based row matching."
        )

    id_lookup: dict[str, pd.Series] = {}
    for _, row in id_frame.iterrows():
        key = normalize_entry_id(row.get(id_id_column))
        if key:
            id_lookup[key] = row

    pairs: list[tuple[pd.Series, pd.Series]] = []
    for _, display_row in display_frame.iterrows():
        key = normalize_entry_id(display_row.get(display_id_column))
        id_row = id_lookup.get(key, pd.Series(dtype=object))
        pairs.append((display_row, id_row))
    return pairs

def first_populated_row_value(
    row: pd.Series,
    columns: Iterable[str],
) -> tuple[Any, str | None]:
    for column in columns:
        value = row.get(column)
        if not is_missing(value):
            return value, column
    return None, None

def coalesce_candidate_values(
    preferred_row: pd.Series,
    preferred_columns: Iterable[str],
    fallback_row: pd.Series,
    fallback_columns: Iterable[str],
) -> tuple[Any, str | None]:
    value, column = first_populated_row_value(preferred_row, preferred_columns)
    if is_missing(value):
        value, column = first_populated_row_value(fallback_row, fallback_columns)
    return value, column

def aligned_attachment_value(
    id_row: pd.Series,
    id_frame: pd.DataFrame,
    display_row: pd.Series,
    display_frame: pd.DataFrame,
    candidates: Iterable[str],
) -> tuple[Any, str | None, Any]:
    """Select raw attachment and display name from the same candidate field."""
    for candidate in candidates:
        id_column = find_column(id_frame, [candidate])
        display_column = find_column(display_frame, [candidate])
        raw_value = id_row.get(id_column) if id_column else None
        display_value = (
            display_row.get(display_column) if display_column else None
        )
        if is_missing(raw_value):
            raw_value = display_value
        if not is_missing(raw_value):
            if is_missing(display_value):
                display_value = raw_value
            return raw_value, id_column or display_column, display_value
    return None, None, None

def build_events(
    source: str,
    display_frame: pd.DataFrame,
    id_frame: pd.DataFrame,
    *,
    reference_candidates: Iterable[str],
    field_overrides: dict[str, list[str]] | None = None,
) -> tuple[list[Event], list[dict[str, Any]]]:
    field_candidates = {
        **EVENT_FIELD_CANDIDATES,
        "deal_reference": list(reference_candidates),
    }
    field_candidates.update(field_overrides or {})

    if display_frame.empty and id_frame.empty:
        print(f"    {source}: no source rows; continuing with zero events")
        return [], []
    display_columns = {
        key: find_columns(display_frame, candidates)
        for key, candidates in field_candidates.items()
    }
    id_columns = {
        key: find_columns(id_frame, candidates)
        for key, candidates in field_candidates.items()
    }

    required_missing = [
        name
        for name in ("deal_reference", "date", "stage")
        if not display_columns[name] and not id_columns[name]
    ]
    if required_missing:
        raise KeyError(
            f"{source} is missing required event fields {required_missing}. "
            f"Display columns: {list(display_frame.columns)}; "
            f"ID columns: {list(id_frame.columns)}"
        )

    events: list[Event] = []
    diagnostics: list[dict[str, Any]] = []
    for display_row, id_row in pair_frames(display_frame, id_frame):
        event_id_value, _ = coalesce_candidate_values(
            display_row,
            display_columns["entry_id"],
            id_row,
            id_columns["entry_id"],
        )
        event_id = normalize_entry_id(event_id_value)

        deal_value, _ = coalesce_candidate_values(
            id_row,
            id_columns["deal_reference"],
            display_row,
            display_columns["deal_reference"],
        )
        deal_ids = extract_reference_ids(deal_value)

        date_value, _ = coalesce_candidate_values(
            display_row, display_columns["date"], id_row, id_columns["date"]
        )
        stage_value, _ = coalesce_candidate_values(
            display_row, display_columns["stage"], id_row, id_columns["stage"]
        )
        recommendation_value, _ = coalesce_candidate_values(
            display_row,
            display_columns["recommendation"],
            id_row,
            id_columns["recommendation"],
        )

        stage_name = human_text(stage_value)
        event_type = classify_event(stage_name)
        event_date = parse_event_date(date_value)
        recommendation = human_text(recommendation_value)

        client_value, client_field, client_display = aligned_attachment_value(
            id_row,
            id_frame,
            display_row,
            display_frame,
            field_candidates["client_ready_memo"],
        )
        internal_value, internal_field, internal_display = aligned_attachment_value(
            id_row,
            id_frame,
            display_row,
            display_frame,
            field_candidates["internal_memo"],
        )

        if not deal_ids:
            diagnostics.append(
                {
                    "Source": source,
                    "Event ID": event_id,
                    "Issue": "No deal reference ID could be extracted",
                    "Stage": stage_name,
                    "Date": event_date,
                }
            )
            continue
        if not event_type:
            # Non-Screening/Final/Follow-On records do not drive this review.
            continue

        for deal_id in deal_ids:
            events.append(
                Event(
                    source=source,
                    event_id=event_id,
                    deal_id=deal_id,
                    event_date=event_date,
                    event_type=event_type,
                    stage_name=stage_name,
                    recommendation=recommendation,
                    client_ready_value=client_value,
                    internal_value=internal_value,
                    client_ready_display=client_display,
                    internal_display=internal_display,
                    client_ready_field=client_field,
                    internal_field=internal_field,
                )
            )

    print(f"    {source}: built {len(events):,} relevant linked events")
    return events, diagnostics

def deduplicate_events(events: list[Event]) -> list[Event]:
    """Remove exact source-record duplicates without merging distinct events."""
    groups: dict[tuple[str, str, str, str, str], Event] = {}
    for event in events:
        date_key = "" if pd.isna(event.event_date) else event.event_date.strftime("%Y-%m-%d")
        key = (
            event.source,
            event.event_id,
            event.deal_id,
            event.event_type,
            date_key,
        )
        if key not in groups:
            groups[key] = event
    return list(groups.values())

def safe_filename(value: str, max_length: int = 180) -> str:
    cleaned = INVALID_FILENAME_CHARACTERS.sub("_", value).strip(" ._")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or "memo")[:max_length]

def is_retryable_attachment_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".casefold()
    retryable_markers = (
        "connecterror",
        "connectionerror",
        "timeout",
        "timed out",
        "ssl",
        "unexpected_eof",
        "eof occurred",
        "connection reset",
        "connection aborted",
        "remoteprotocolerror",
        "temporarily unavailable",
        "too many requests",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    )
    return any(marker in text for marker in retryable_markers)

def run_attachment_request_with_retry(
    operation: Any,
    *,
    label: str,
    cleanup_path: Path | None = None,
) -> tuple[Any, int]:
    """Run one attachment request with bounded exponential backoff."""
    attempts = max(int(ATTACHMENT_DOWNLOAD_MAX_ATTEMPTS), 1)
    for attempt in range(1, attempts + 1):
        try:
            result = operation()
            if ATTACHMENT_REQUEST_PAUSE_SECONDS > 0:
                time.sleep(ATTACHMENT_REQUEST_PAUSE_SECONDS)
            return result, attempt
        except Exception as exc:
            if cleanup_path is not None:
                cleanup_path.unlink(missing_ok=True)
            retryable = is_retryable_attachment_error(exc) or isinstance(exc, IOError)
            if not retryable or attempt >= attempts:
                raise
            delay = min(
                ATTACHMENT_RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
                ATTACHMENT_RETRY_MAX_SECONDS,
            )
            print(
                f"        {label}: transient {type(exc).__name__}; "
                f"retrying in {delay:.1f}s ({attempt + 1}/{attempts})"
            )
            time.sleep(delay)
    raise RuntimeError(f"Unreachable retry state for {label}")

SUPPLEMENTARY_MEMO_TERMS = (
    "supplementary",
    "supplemental",
    "impact assessment",
    "appendix",
    "supporting material",
    "supporting document",
)

def is_supplementary_memo_text(value: Any) -> bool:
    text = " ".join(human_values(value)).lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", text).strip()
    compact = normalized.replace(" ", "")
    return any(
        re.sub(r"[^a-z0-9]+", " ", term).strip() in normalized
        or re.sub(r"[^a-z0-9]+", "", term) in compact
        for term in SUPPLEMENTARY_MEMO_TERMS
    )

def memo_stage_priority(event: Event) -> int | None:
    """Return the memo tier; lower numbers have greater priority."""
    stage = re.sub(r"[^a-z0-9]+", " ", event.stage_name.lower()).strip()

    # Exclude a supplementary/impact-assessment stage entirely. Attachment
    # names are evaluated separately so an unused supplementary field cannot
    # disqualify a valid attachment on the same event.
    if is_supplementary_memo_text(stage):
        return None

    if "final" in stage:
        return 0
    if "screen" in stage:
        return 1
    if (
        "follow on" in stage
        or "followon" in stage.replace(" ", "")
        or "incremental" in stage
    ):
        return 2
    if "update" in stage or "addendum" in stage:
        return 3
    return None

def attachment_field_items(raw_value: Any, display_value: Any) -> list[tuple[Any, Any]]:
    """Split a multi-file field into aligned raw-ID and display-name items."""
    raw_parsed = parse_structured(raw_value)
    display_parsed = parse_structured(display_value)

    if isinstance(raw_parsed, (list, tuple, set)):
        raw_items = list(raw_parsed)
    else:
        raw_ids = extract_reference_ids(raw_parsed)
        raw_items = [{"id": item} for item in raw_ids] if len(raw_ids) > 1 else [raw_parsed]

    if isinstance(display_parsed, (list, tuple, set)):
        display_items = list(display_parsed)
    else:
        display_names = human_values(display_parsed)
        display_items = display_names if len(display_names) > 1 else [display_parsed]

    return [
        (raw_item, display_items[index] if index < len(display_items) else None)
        for index, raw_item in enumerate(raw_items)
    ]

def priority_memo_candidates(
    history: DealHistory,
) -> list[tuple[Event, str, Any, str, Any]]:
    """Final/Internal -> Final/Client -> Screening/Internal -> Screening/Client,
    then Follow-On/Internal -> Follow-On/Client -> Update/Internal -> Update/Client.
    Within each stage/field tier, newest IC Date wins. Only in-window events qualify.
    """
    candidates = []
    for event in history.events:
        if not event.in_window:
            continue
        priority = memo_stage_priority(event)
        if priority is None:
            continue
        for field_rank, kind, value, display, field_name in (
            (0, "InternalMemo", event.internal_value, event.internal_display, event.internal_field),
            (1, "ClientReadyMemo", event.client_ready_value, event.client_ready_display, event.client_ready_field),
        ):
            if is_missing(value):
                continue
            for raw_item, display_item in attachment_field_items(value, display):
                label = display_item if not is_missing(display_item) else raw_item
                if is_supplementary_memo_text(label):
                    continue
                candidates.append((priority, field_rank, event, kind, raw_item,
                                   field_name or kind, display_item))
    candidates.sort(key=lambda c: (
        c[0], c[1], -c[2].event_date.value, c[2].source, c[2].event_id,
    ))
    return [(event, kind, raw, field_name, display)
            for _, _, event, kind, raw, field_name, display in candidates]

def connect_to_dealcloud() -> DealCloud:
    """Authenticate with retries for transient TLS/network failures."""
    attempts = max(int(DEALCLOUD_CONNECTION_MAX_ATTEMPTS), 1)
    for attempt in range(1, attempts + 1):
        try:
            dc = DealCloud(
                site_url=DEALCLOUD_SITE_URL,
                client_id=DEALCLOUD_CLIENT_ID,
                client_secret=DEALCLOUD_CLIENT_SECRET,
            )
            print("Authentication succeeded.")
            return dc
        except Exception as exc:
            retryable = is_retryable_attachment_error(exc) or isinstance(exc, IOError)
            if not retryable or attempt >= attempts:
                raise
            delay = min(
                DEALCLOUD_CONNECTION_RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
                DEALCLOUD_CONNECTION_RETRY_MAX_SECONDS,
            )
            print(
                f"    Authentication hit a transient {type(exc).__name__}; "
                f"retrying in {delay:.1f}s ({attempt + 1}/{attempts})"
            )
            time.sleep(delay)
    raise RuntimeError("Unreachable DealCloud authentication retry state")

def discover_secondary_review_sources(dc: DealCloud) -> list[tuple[str, str, list[str], dict[str, list[str]]]]:
    """Discover IC-dated, transaction-linked sources; never substitute other dates."""
    choices = object_schema_choices(dc)
    qualified = []
    overrides = {normalize_name(v) for v in (SECONDARY_IC_MEMO_OBJECT, SECONDARY_TEAM_DISCUSSION_OBJECT) if v}
    for choice in choices:
        text = normalize_name(" ".join(choice.values()))
        if not (any(v in text for v in ("secondary", "memo", "teamdiscussion"))
                or normalize_name(choice["api"]) in overrides):
            continue
        try:
            fields = field_schema_identifiers(dc, choice["api"])
        except Exception:
            if normalize_name(choice["api"]) in overrides:
                raise
            continue
        if not schema_has_any(fields, SECONDARY_EVENT_REFERENCE_CANDIDATES):
            continue
        if not schema_has_any(fields, ["ICDate", "IC Date"]):
            continue
        if not schema_has_any(fields, EVENT_FIELD_CANDIDATES["stage"]):
            continue
        if not schema_has_any(fields, EVENT_FIELD_CANDIDATES["internal_memo"] + EVENT_FIELD_CANDIDATES["client_ready_memo"]):
            continue
        score = (100 if "icmemo" in text or "investmentcommittee" in text else 0) + (40 if "secondary" in text else 0) - (100 if "teamdiscussion" in text else 0)
        qualified.append((choice["api"], text, score))
    def validate_override(name: str) -> str:
        matches = [api for api, _, _ in qualified if normalize_name(api) == normalize_name(name)]
        if len(matches) != 1:
            raise RuntimeError(f"Configured memo object {name!r} must expose a Secondary Deal reference, ICDate/IC Date, stage, and memo field. Check its API name/schema.")
        return matches[0]
    if SECONDARY_IC_MEMO_OBJECT:
        ic = validate_override(SECONDARY_IC_MEMO_OBJECT)
    else:
        ranked = sorted((item for item in qualified if "teamdiscussion" not in item[1]), key=lambda c: (-c[2], c[0]))
        if not ranked or (len(ranked) > 1 and ranked[0][2] == ranked[1][2]):
            raise RuntimeError(f"Cannot uniquely identify Secondary IC Memo object. IC-dated candidates: {[c[0] for c in ranked]}. Set DEALCLOUD_SECONDARY_IC_MEMO_OBJECT.")
        ic = ranked[0][0]
    sources = [("Secondary IC Memo", ic, SECONDARY_EVENT_REFERENCE_CANDIDATES, SECONDARY_IC_FIELD_OVERRIDES)]
    if SECONDARY_TEAM_DISCUSSION_OBJECT:
        team = validate_override(SECONDARY_TEAM_DISCUSSION_OBJECT)
    else:
        teams = [api for api, text, _ in qualified if "teamdiscussion" in text and normalize_name(api) != normalize_name(ic)]
        if len(teams) > 1:
            raise RuntimeError(f"Multiple IC-dated team-discussion objects: {teams}. Set DEALCLOUD_SECONDARY_TEAM_DISCUSSION_OBJECT.")
        team = teams[0] if teams else ""
    if team:
        if normalize_name(team) == normalize_name(ic):
            raise RuntimeError("IC and Team Discussion memo objects must be different.")
        sources.append(("Team Discussion Memo (IC Date)", team, SECONDARY_EVENT_REFERENCE_CANDIDATES, SECONDARY_TEAM_FIELD_OVERRIDES))
    else:
        print("No IC-dated Team Discussion source discovered; using Secondary IC Memo only.")
    print(f"Memo sources using IC Date: {[source[1] for source in sources]}")
    return sources

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
