"""Offline tests for Excel-list mode; every SDK record and attachment is synthetic.

Run from this directory: python -m unittest -v test_excel_executor
Requires the application's ordinary pandas dependency. No DealCloud package,
credentials, downloader source tree, or network connection is needed.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import pandas as pd
import excel_executor as x


@dataclass
class Event:
    source: str
    event_id: str
    deal_id: str
    event_date: object
    stage_name: str
    internal_value: object = None
    internal_display: object = None
    internal_field: object = None
    client_ready_value: object = None
    client_ready_display: object = None
    client_ready_field: object = None

    @property
    def in_window(self):
        raise AssertionError("Excel mode must not evaluate the ordinary date window")


class FakeSDK:
    """Query-enforcing fake with no network methods or credentials."""
    def __init__(self):
        self.parents = {p: [] for p in x.POPULATIONS}
        self.memos = {p: [] for p in x.POPULATIONS}
        self.calls = []
        self.failed = set()
        self.missing_filename = set()
        self.supplementary_metadata = set()
        self.missing_fields = set()
        self.omitted_fields = set()
        self.parent_injection = None
        self.memo_injection = None
        self.mismatched_display_ids = False
        self.duplicate_memo_rows = False
        self.binary_error = False
        self.save_exception = False
        self.empty_saved_file = False
        self.unsafe_saved_file = None
        self.engine = None

    def add_parent(self, name="Synthetic Fund I", identifier="101", population="Primaries"):
        self.parents[population].append({"EntryId": identifier, self.engine.POPULATION_CONFIG[population]["names"][0]: name})

    def add_memo(self, event_id="501", parent_id="101", stage="Final", date="2026-01-15", internal="901", client=None,
                 population="Primaries", field=None, display=None):
        config = self.engine.POPULATION_CONFIG[population]
        row = {"EntryId": event_id, config["reference"]: [{"id": parent_id}], "ICDate": date, "Stage": stage,
               "RecommendationApprovedbyIC": "No", "Recommendation": "Decline"}
        for fields in (config["internal"], config["client"]):
            for name in fields:
                row[name] = None
        internal_field = field or config["internal"][0]
        if internal is not None:
            row[internal_field] = [{"id": internal, "name": display or "Synthetic memo.pdf"}] if not isinstance(internal, list) else internal
        if client is not None:
            row[config["client"][0]] = [{"id": client, "name": "Synthetic client.pdf"}]
        self.memos[population].append(row)

    def get_fields(self, object_name):
        self.calls.append(("schema", object_name))
        fields = []
        for config in self.engine.POPULATION_CONFIG.values():
            if config["parent"] == object_name:
                fields = config["names"]
            if config["memo_object"] == object_name:
                fields = [config["reference"], "ICDate", "Stage", *config["internal"], *config["client"]]
        return [f for f in fields if (object_name, f) not in self.missing_fields]

    def read_data(self, object_id, fields, query, resolve):
        query = json.loads(query)
        self.calls.append(("read", object_id, resolve, query, fields))
        assert len(query) == 1, "No date/approval/recommendation query permitted"
        field, operation = next(iter(query.items()))
        assert set(operation) == {"$in"}
        values = operation["$in"]
        assert values, "No broad/empty-ID query"
        population, config = next((p, c) for p, c in self.engine.POPULATION_CONFIG.items() if object_id in (c["parent"], c["memo_object"]))
        if object_id == config["parent"]:
            assert field == config["names"][0]
            assert resolve == "name"
            assert all(isinstance(v, str) for v in values)
            rows = [r.copy() for r in self.parents[population] if x.exact_name(r[field]) in {x.exact_name(v) for v in values}]
            if self.parent_injection:
                rows.append(self.parent_injection.copy())
        else:
            assert field == config["reference"]
            assert all(type(v) is int for v in values)
            assert not any(f in fields for f in ("RecommendationApprovedbyIC", "Recommendation"))
            rows = [r.copy() for r in self.memos[population] if set(self.engine.extract_reference_ids(r[field])).intersection(map(str, values))]
            if self.memo_injection:
                rows.append(self.memo_injection.copy())
            if self.duplicate_memo_rows and rows:
                rows.append(rows[0].copy())
            if resolve == "name":
                # IDs stay available; deliberately reverse records to test ID pairing.
                rows.reverse()
                if self.mismatched_display_ids and rows:
                    rows[0]["EntryId"] = "777777"
        columns = ["EntryId", *fields]
        columns = [c for c in columns if (object_id, c) not in self.omitted_fields]
        return pd.DataFrame(rows, columns=columns)

    def download_attachment_metadata(self, identifier):
        self.calls.append(("metadata", str(identifier)))
        if str(identifier) in self.missing_filename:
            return ""
        return "Synthetic appendix.pdf" if str(identifier) in self.supplementary_metadata else "Synthetic memo.pdf"

    def download_file(self, identifier, output_path):
        identifier = str(identifier)
        self.calls.append(("download", identifier, str(output_path)))
        if identifier in self.failed:
            raise OSError("Synthetic network failure https://private.invalid/?client_secret=DO_NOT_REPORT")
        Path(output_path).write_bytes(b"" if self.empty_saved_file else b"synthetic attachment")


class FakeEngine:
    POPULATION_CONFIG = {
        "Primaries": {"parent": "Fund", "names": ["FundName"], "memo_object": "DiligenceActivity", "reference": "Fund",
                      "internal": ["InternalMemo"], "client": ["ClientReadyMemo", "ClientVersionofMemo"]},
        "CoInvestments": {"parent": "CoInvestmentDeal", "names": ["ProjectName"], "memo_object": "CIMemo", "reference": "CIDeal",
                          "internal": ["InternalMemo"], "client": ["ClientReadyMemo"]},
        "Secondaries": {"parent": "SecondaryDeal", "names": ["DealName"], "memo_object": "SecondaryMemo", "reference": "SecondaryDeal",
                        "internal": ["INTERNALMEMO", "TeamDiscussionMemo"], "client": ["ClientMemo"]},
    }
    EVENT_FIELD_CANDIDATES = {"entry_id": ["EntryId", "DealCloud Entry ID"]}
    ATTACHMENT_OBJECT = "Attachment"
    ATTACHMENT_BINARY_FIELD = "BinaryFile"

    def __init__(self, dc):
        dc.engine = self
        self.REQUIRE_VERIFIABLE_FILENAME = "original sentinel"
        self.START_DATE = "2026-01-01"
        self.END_DATE_EXCLUSIVE = "2026-02-01"
        self.MEMO_APPROVED_BY_IC = ["Yes"]
        self.MEMO_RECOMMENDATIONS = ["Invest"]
        self.build_problems = []

    def api_field_selection(self, dc, obj, requested):
        present = dc.get_fields(obj)
        if not set(requested).issubset(present):
            raise KeyError("Missing synthetic field")
        return list(requested)

    def filtered_read(self, dc, obj, fields, query, resolve):
        return dc.read_data(obj, fields, json.dumps(query), resolve)

    @staticmethod
    def attach_field_schema_aliases(dc, obj, *frames):
        pass

    @staticmethod
    def find_column(frame, candidates):
        return next((c for c in candidates if c in frame.columns), None)

    @staticmethod
    def human_text(value):
        return str(value)

    @staticmethod
    def normalize_entry_id(value):
        return str(value)

    @staticmethod
    def is_missing(value):
        if isinstance(value, (list, dict, tuple)):
            return not value
        return value is None or bool(pd.isna(value))

    @staticmethod
    def extract_reference_ids(value):
        if isinstance(value, dict):
            return [str(value["id"])] if "id" in value else []
        if isinstance(value, list):
            return [i for v in value for i in FakeEngine.extract_reference_ids(v)]
        if isinstance(value, (str, int)) and str(value).isdigit():
            return [str(value)]
        return []

    @classmethod
    def first_reference_id(cls, value):
        refs = cls.extract_reference_ids(value)
        return refs[0] if refs else None

    @staticmethod
    def validate_event_pairing(names, raw):
        if names.empty and raw.empty:
            return
        for frame in (names, raw):
            if "EntryId" not in frame or frame["EntryId"].duplicated().any() or frame["EntryId"].isna().any():
                raise ValueError("Invalid synthetic pairing")
        if set(names["EntryId"]) != set(raw["EntryId"]):
            raise ValueError("Mismatched synthetic snapshot")

    def build_events(self, source, names, raw, reference_candidates, field_overrides):
        assert field_overrides["recommendation"] == []
        events = []
        display_lookup = {r["EntryId"]: r for r in names.to_dict("records")}
        for row in raw.to_dict("records"):
            if "ICDate" not in row or "Stage" not in row:
                raise KeyError("Missing required event column")
            display = display_lookup[row["EntryId"]]
            for parent_id in self.extract_reference_ids(row[reference_candidates[0]]):
                event = Event(source, row["EntryId"], parent_id, pd.to_datetime(display["ICDate"], errors="coerce"), display["Stage"])
                for key, prefix in (("internal_memo", "internal"), ("client_ready_memo", "client_ready")):
                    fields = field_overrides[key]
                    if fields:
                        setattr(event, prefix + "_value", row.get(fields[0]))
                        setattr(event, prefix + "_display", display.get(fields[0]))
                        setattr(event, prefix + "_field", fields[0])
                events.append(event)
        return events, self.build_problems

    @staticmethod
    def deduplicate_events(events):
        return events

    @staticmethod
    def memo_stage_priority(event):
        if "impact" in event.stage_name.casefold():
            return None
        aliases = {"Addendum": "Update", "Incremental": "Follow-On"}
        stage = aliases.get(event.stage_name, event.stage_name)
        return x.STAGES.index(stage) if stage in x.STAGES else None

    @staticmethod
    def attachment_field_items(raw, display):
        raws = raw if isinstance(raw, list) else [raw]
        displays = display if isinstance(display, list) else [display]
        return [(v, displays[i] if i < len(displays) else None) for i, v in enumerate(raws)]

    @staticmethod
    def is_supplementary_memo_text(value):
        return any(word in str(value).casefold() for word in ("appendix", "supplementary", "impact assessment"))

    def selected_memo_candidates(self, history):
        raise AssertionError("Excel mode must not inherit engine selection filters")

    def discover_attachment_binary_field(self, dc, obj, configured):
        dc.calls.append(("binary", obj))
        if dc.binary_error:
            raise RuntimeError("DO_NOT_REPORT client_secret=synthetic")
        return configured

    def save_candidate(self, dc, deal_id, deal_name, choice, memo_dir, binary, sources):
        dc.calls.append(("save", str(deal_id), choice[0].event_id, self.REQUIRE_VERIFIABLE_FILENAME))
        if dc.save_exception:
            raise RuntimeError("DO_NOT_REPORT client_secret=synthetic")
        if dc.unsafe_saved_file:
            return {"File": str(dc.unsafe_saved_file), "Status": "Downloaded"}
        identifier = self.first_reference_id(choice[2])
        if identifier and not binary:
            return {"File": "", "Status": "FAILED: Attachment binary field unavailable"}
        identifier = identifier or choice[0].event_id
        filename = dc.download_attachment_metadata(identifier)
        if not filename and self.REQUIRE_VERIFIABLE_FILENAME:
            return {"File": "", "Status": "SKIPPED: filename unavailable; strict filename setting enabled"}
        if self.is_supplementary_memo_text(filename):
            return {"File": "", "Status": "SKIPPED supplementary material"}
        path = memo_dir / ("m.pdf" if filename else "m.bin")
        try:
            dc.download_file(identifier, path)
        except OSError as exc:
            return {"File": "", "Status": f"FAILED: {exc}"}
        return {"File": str(path), "Status": "Downloaded" if filename else "Downloaded; filename unknown; REVIEW"}


class ExcelExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ex-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "run"
        self.root.mkdir()
        self.dc = FakeSDK()
        self.engine = FakeEngine(self.dc)

    def row(self, source_row=2, deal="Synthetic Fund I", population="Primaries", client="Synthetic Client", quarters=None, policy="Use app setting"):
        return {"source_row": source_row, "deal_name": deal, "population": population, "client": client,
                "quarters": [] if quarters is None else quarters, "memo_type": policy}

    def settings(self, rows=None, **kwargs):
        return {"rows": [self.row()] if rows is None else rows, "default_policy": "Priority fallback", "audience": "Internal then Client",
                "quarter_precedence": "Earliest", "strict_filename": True, "max_attempts": 5, **kwargs}

    def basic(self):
        self.dc.add_parent()
        self.dc.add_memo()

    def run_excel(self, settings=None, preview=False):
        return x.run_excel(self.dc, self.engine, settings or self.settings(), self.root, preview)

    def csv(self, name="excel_results.csv"):
        with (self.root / "Reports" / name).open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def downloads(self):
        return [c[1] for c in self.dc.calls if c[0] == "download"]

    def test_basic_download_portable_reports_and_restore_engine(self):
        self.basic()
        result = self.run_excel()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["output"], ".")
        self.assertEqual(result["excel_summary"]["memo_copies_written"], 1)
        self.assertEqual(result["excel_summary"]["unique_memos_downloaded"], 1)
        self.assertEqual(self.downloads(), ["901"])
        files = self.csv("downloaded_files.csv")
        self.assertTrue((self.root / files[0]["File"]).is_file())
        self.assertFalse(Path(files[0]["File"]).is_absolute())
        self.assertEqual(self.csv("candidate_attempts.csv")[0]["File"], files[0]["File"])
        self.assertEqual(self.engine.REQUIRE_VERIFIABLE_FILENAME, "original sentinel")
        self.assertEqual(self.engine.START_DATE, "2026-01-01")
        self.assertEqual(self.engine.MEMO_APPROVED_BY_IC, ["Yes"])
        self.assertEqual({p.name for p in (self.root / "Reports").iterdir()}, {"excel_results.csv", "downloaded_files.csv", "candidate_attempts.csv", "run_settings.json", "excel_issues.json"})
        for path in (self.root / "Reports").iterdir():
            text = path.read_text(encoding="utf-8-sig")
            self.assertNotIn(self.temporary.name, text)
            self.assertNotIn("DO_NOT_REPORT", text)

    def test_preview_reads_candidates_but_never_attachment_discovery_or_requests(self):
        self.basic()
        self.dc.add_memo(event_id="502", stage="Update", date="2030-01-01", internal="902")
        result = self.run_excel(preview=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["excel_summary"]["eligible_candidates"], 2)
        self.assertEqual(result["excel_summary"]["attempted_candidates"], 0)
        self.assertFalse(any(c[0] in ("metadata", "binary", "download", "save") for c in self.dc.calls))
        row = self.csv()[0]
        self.assertEqual(row["Memo Stage"], "Final")
        self.assertEqual(row["Event ID"], "501")
        self.assertEqual(row["Intended Attachment ID"], "901")
        self.assertEqual(row["File"], "")
        self.assertIn("not verified", row["Detail"])
        self.assertEqual(self.csv("candidate_attempts.csv"), [])
        self.assertEqual(self.csv("downloaded_files.csv"), [])

    def test_case_whitespace_matching_preserves_punctuation_and_numerals(self):
        self.dc.add_parent(name="  SYNTHETIC  Fund\tI ")
        self.dc.add_memo()
        rows = [self.row(deal="synthetic fund i"), self.row(3, deal="Synthetic Fund II"), self.row(4, deal="Synthetic-Fund I")]
        result = self.run_excel(self.settings(rows))
        self.assertEqual(result["status"], "partial")
        self.assertEqual([r["Status"] for r in self.csv()][1:], ["UNMATCHED", "UNMATCHED"])
        self.assertEqual(self.downloads(), ["901"])

    def test_ambiguous_name_never_guesses_id_or_reads_memos(self):
        self.dc.add_parent(identifier="101")
        self.dc.add_parent(identifier="102")
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertIn("AMBIGUOUS", self.csv()[0]["Status"])
        self.assertEqual(self.csv()[0]["Parent ID"], "")
        self.assertFalse(any(c[0] == "read" and c[1] == "DiligenceActivity" for c in self.dc.calls))

    def test_unrelated_parent_injection_fails_closed(self):
        self.basic()
        self.dc.parent_injection = {"EntryId": "999", "FundName": "Unrelated Synthetic Fund"}
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.csv()[0]["Status"], "POPULATION ERROR")
        self.assertEqual(self.downloads(), [])

    def test_invalid_parent_id_fails_closed(self):
        self.dc.add_parent(identifier="guessed-id")
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.downloads(), [])

    def test_unrelated_memo_reference_fails_closed(self):
        self.basic()
        self.dc.memo_injection = {"EntryId": "999", "Fund": [{"id": "9999"}], "ICDate": "2026-01-01", "Stage": "Final", "InternalMemo": "999"}
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.csv()[0]["Status"], "POPULATION ERROR")
        self.assertEqual(self.downloads(), [])

    def test_multi_reference_memo_must_not_include_unrequested_id(self):
        self.basic()
        self.dc.memos["Primaries"][0]["Fund"].append({"id": "9999"})
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.downloads(), [])

    def test_unparseable_reference_injection_fails_closed(self):
        self.basic()
        self.dc.memo_injection = {"EntryId": "999", "Fund": "Synthetic label not an ID", "ICDate": "2026-01-01", "Stage": "Final"}
        self.assertEqual(self.run_excel()["status"], "partial")
        self.assertEqual(self.downloads(), [])

    def test_display_snapshot_mismatch_fails_closed(self):
        self.basic()
        self.dc.mismatched_display_ids = True
        self.assertEqual(self.run_excel()["status"], "partial")
        self.assertEqual(self.downloads(), [])

    def test_duplicate_memo_ids_fail_closed(self):
        self.basic()
        self.dc.duplicate_memo_rows = True
        self.assertEqual(self.run_excel()["status"], "partial")
        self.assertEqual(self.downloads(), [])

    def test_priority_is_stage_then_internal_then_recency_with_fallback(self):
        self.dc.add_parent()
        self.dc.add_memo("501", stage="Screening", date="2030-01-01", internal="901")
        self.dc.add_memo("502", stage="Final", date="2020-01-01", internal="902", client="903")
        self.dc.add_memo("503", stage="Final", date="2021-01-01", internal="904", client="905")
        self.dc.failed.update({"904", "902"})
        self.run_excel()
        self.assertEqual(self.downloads(), ["904", "902", "905"])
        row = self.csv()[0]
        self.assertEqual((row["Memo Stage"], row["Audience"]), ("Final", "Client"))
        self.assertEqual(row["Candidates Tried"], "3")

    def test_each_fixed_stage_never_falls_back_to_other_stages(self):
        self.dc.add_parent()
        for i, stage in enumerate(x.STAGES):
            self.dc.add_memo(str(500 + i), stage=stage, internal=str(900 + i))
        rows = [self.row(2 + i, policy=s) for i, s in enumerate(x.STAGES)]
        result = self.run_excel(self.settings(rows, max_attempts=None))
        self.assertEqual(result["status"], "completed")
        self.assertEqual([r["Memo Stage"] for r in self.csv()], list(x.STAGES))
        self.assertEqual(len(self.downloads()), 4)

    def test_fixed_final_with_only_screening_is_no_eligible(self):
        self.dc.add_parent()
        self.dc.add_memo(stage="Screening")
        result = self.run_excel(self.settings(default_policy="Final"))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.csv()[0]["Status"], "NO ELIGIBLE DATED MEMO")
        self.assertEqual(self.downloads(), [])

    def test_latest_is_newest_across_stages_internal_breaks_date_tie(self):
        self.dc.add_parent()
        self.dc.add_memo("501", stage="Final", date="2020-01-01", internal="901")
        self.dc.add_memo("502", stage="Update", date="2030-01-01", internal="902")
        self.dc.add_memo("503", stage="Final", date="2030-01-01", internal=None, client="903")
        self.run_excel(self.settings(default_policy="Latest available"))
        self.assertEqual(self.downloads(), ["902"])
        self.assertEqual(self.csv()[0]["Memo Stage"], "Update")

    def test_internal_only_does_not_use_client(self):
        self.dc.add_parent()
        self.dc.add_memo(internal=None, client="902")
        result = self.run_excel(self.settings(audience="Internal only"))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.downloads(), [])
        queries = [c for c in self.dc.calls if c[0] == "read" and c[1] == "DiligenceActivity"]
        self.assertTrue(all("ClientReadyMemo" not in c[4] for c in queries))

    def test_client_only_skips_internal(self):
        self.dc.add_parent()
        self.dc.add_memo(internal="901", client="902")
        self.run_excel(self.settings(audience="Client only"))
        self.assertEqual(self.downloads(), ["902"])
        self.assertEqual(self.csv()[0]["Audience"], "Client")

    def test_update_and_addendum_are_supported(self):
        self.dc.add_parent()
        self.dc.add_memo(stage="Addendum")
        self.run_excel(self.settings(default_policy="Update"))
        self.assertEqual(self.csv()[0]["Memo Stage"], "Update")

    def test_no_date_window_or_ic_approval_recommendation_filter(self):
        self.dc.add_parent()
        self.dc.add_memo(date="1990-01-01")
        result = self.run_excel()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.csv()[0]["IC Date"], "1990-01-01")
        self.assertEqual(self.engine.MEMO_RECOMMENDATIONS, ["Invest"])

    def test_undated_eligible_events_visible_as_coverage_warning(self):
        self.dc.add_parent()
        self.dc.add_memo(date=None)
        result = self.run_excel(preview=True)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(any("undated" in w for w in result["population_results"][0]["source_warnings"]))
        self.assertEqual(self.csv()[0]["Eligible Candidates"], "0")

    def test_supplementary_display_is_not_eligible(self):
        self.dc.add_parent()
        self.dc.add_memo(display="Synthetic appendix.pdf")
        result = self.run_excel(preview=True)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.csv()[0]["Eligible Candidates"], "0")

    def test_supplementary_metadata_skip_falls_back(self):
        self.dc.add_parent()
        self.dc.add_memo("501", internal="901", date="2026-01-02")
        self.dc.add_memo("502", internal="902", date="2026-01-01")
        self.dc.supplementary_metadata.add("901")
        self.run_excel()
        self.assertEqual(self.downloads(), ["902"])
        self.assertIn("supplementary", self.csv("candidate_attempts.csv")[0]["Status"])

    def test_same_parent_policy_downloads_once_but_copies_per_row_client_quarter(self):
        self.basic()
        rows = [self.row(2, quarters=["Q1 2026", "Q2 2026", "Q1 2026"]),
                self.row(3, deal=" synthetic   fund i ", client="Another Synthetic Client", quarters=["Q2 2026"]),
                self.row(4, client="Third Synthetic Client", quarters=["Q1 2026"])]
        result = self.run_excel(self.settings(rows))
        self.assertEqual(len(self.downloads()), 1)
        self.assertEqual(result["excel_summary"]["unique_policy_jobs"], 1)
        self.assertEqual(result["excel_summary"]["memo_copies_written"], 3)
        self.assertEqual(result["excel_summary"]["suppressed_requests"], 1)
        self.assertEqual(len(self.csv()), 4)
        self.assertEqual(len(self.csv("downloaded_files.csv")), 3)

    def test_different_policies_do_not_share_download_job_or_quarter_suppression(self):
        self.basic()
        self.dc.add_memo("502", stage="Screening", internal="902")
        rows = [self.row(2, quarters=["Q1 2026"], policy="Final"), self.row(3, quarters=["Q2 2026"], policy="Screening")]
        result = self.run_excel(self.settings(rows))
        self.assertEqual(len(self.downloads()), 2)
        self.assertEqual(result["excel_summary"]["suppressed_requests"], 0)
        self.assertEqual(result["excel_summary"]["memo_copies_written"], 2)

    def test_effective_policy_dedupes_default_and_explicit(self):
        self.basic()
        rows = [self.row(2, policy="Use app setting"), self.row(3, policy="Final")]
        result = self.run_excel(self.settings(rows, default_policy="Final"))
        self.assertEqual(len(self.downloads()), 1)
        self.assertEqual(result["excel_summary"]["unique_policy_jobs"], 1)
        # Same client folder: both rows reference one saved copy.
        self.assertEqual(result["excel_summary"]["memo_copies_written"], 1)
        files = [r["File"] for r in self.csv()]
        self.assertTrue(files[0] and files[0] == files[1])

    def test_latest_quarter_rule_spans_all_four_quarters_per_client_deal_year(self):
        self.basic()
        rows = [self.row(2, quarters=["Q1 2026", "Q2 2026", "Q1 2025", "Q3 2026"]),
                self.row(3, client="Another Synthetic Client", quarters=["Q1 2026"]),
                self.row(4, quarters=["Q4 2026"])]
        result = self.run_excel(self.settings(rows, quarter_precedence="Latest"))
        # Synthetic Client 2026: Q1, Q2, Q3, Q4 listed -> only Q4 kept; 2025 and the other client untouched.
        kept = [r["Quarter"] for r in self.csv() if r["Status"] == "DOWNLOADED"]
        self.assertEqual(sorted(kept), ["Q1 2025", "Q1 2026", "Q4 2026"])
        self.assertEqual(sorted(r["Quarter"] for r in self.csv() if r["Status"].startswith("SUPPRESSED")), ["Q1 2026", "Q2 2026", "Q3 2026"])
        self.assertEqual(result["excel_summary"]["memo_copies_written"], 3)

    def test_earliest_quarter_rule_prefers_q3_over_q4(self):
        self.basic()
        rows = [self.row(2, quarters=["Q4 2026", "Q3 2026"])]
        self.run_excel(self.settings(rows, quarter_precedence="Earliest"))
        status = {r["Quarter"]: r["Status"] for r in self.csv()}
        self.assertEqual(status["Q3 2026"], "DOWNLOADED")
        self.assertTrue(status["Q4 2026"].startswith("SUPPRESSED"))

    def test_year_and_quarter_folders_are_nested(self):
        self.basic()
        rows = [self.row(2, quarters=["Q3 2026"]), self.row(3, quarters=["Q3"]), self.row(4, quarters=["2025"])]
        self.run_excel(self.settings(rows, quarter_precedence="Keep all", output_layout="grouped"))
        parents = [Path(r["File"]).parent.as_posix() for r in self.csv("downloaded_files.csv")]
        self.assertEqual(parents, ["Synthetic Client/2026/Q3", "Synthetic Client/Q3", "Synthetic Client/2025"])

    def test_keep_both_quarters_and_empty_quarters(self):
        self.basic()
        rows = [self.row(2, quarters=["Q1 2026", "Q2 2026"]), self.row(3)]
        result = self.run_excel(self.settings(rows, quarter_precedence="Keep all"))
        self.assertEqual(result["excel_summary"]["memo_copies_written"], 3)
        self.assertEqual(self.csv()[-1]["Quarter"], "")

    def test_q1_precedence_across_rows_normalized_client(self):
        self.basic()
        rows = [self.row(2, client="CLIENT", quarters=["Q1 2026"]), self.row(3, client=" client ", quarters=["Q2 2026"])]
        result = self.run_excel(self.settings(rows))
        self.assertEqual(result["excel_summary"]["memo_copies_written"], 1)
        self.assertTrue(self.csv()[1]["Status"].startswith("SUPPRESSED"))

    def test_population_is_part_of_identity_even_if_name_and_id_match(self):
        self.basic()
        self.dc.add_parent(population="CoInvestments")
        self.dc.add_memo(population="CoInvestments")
        rows = [self.row(2), self.row(3, population="CoInvestments")]
        result = self.run_excel(self.settings(rows))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.downloads()), 2)
        self.assertEqual(result["excel_summary"]["unique_policy_jobs"], 2)

    def test_secondary_multiple_internal_streams_and_client_fields(self):
        self.dc.add_parent(population="Secondaries")
        self.dc.add_memo("501", population="Secondaries", internal="901", field="INTERNALMEMO", date="2026-01-01")
        self.dc.add_memo("502", population="Secondaries", internal="902", field="TeamDiscussionMemo", date="2026-02-01")
        self.run_excel(self.settings([self.row(population="Secondaries")]))
        self.assertEqual(self.downloads(), ["902"])

    def test_optional_inaccessible_stream_is_visible_even_with_success(self):
        self.basic()
        self.dc.missing_fields.add(("DiligenceActivity", "ClientVersionofMemo"))
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.downloads(), ["901"])
        self.assertIn("source coverage is incomplete", result["population_results"][0]["source_warnings"][0])

    def test_unselected_audience_missing_field_does_not_reduce_coverage(self):
        self.basic()
        self.dc.missing_fields.add(("DiligenceActivity", "ClientVersionofMemo"))
        result = self.run_excel(self.settings(audience="Internal only"))
        self.assertEqual(result["status"], "completed")

    def test_schema_field_not_returned_is_visible(self):
        self.basic()
        self.dc.omitted_fields.add(("DiligenceActivity", "ClientVersionofMemo"))
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertTrue(any("not returned" in w for w in result["population_results"][0]["source_warnings"]))

    def test_all_attachment_fields_inaccessible_is_population_error(self):
        self.basic()
        for field in ("InternalMemo", "ClientReadyMemo", "ClientVersionofMemo"):
            self.dc.missing_fields.add(("DiligenceActivity", field))
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.csv()[0]["Status"], "POPULATION ERROR")

    def test_event_building_issues_surface_in_source_warnings_without_raw_message(self):
        self.basic()
        self.engine.build_problems = [{"Issue": "DO_NOT_REPORT client_secret=synthetic"}]
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        warnings = result["population_results"][0]["source_warnings"]
        self.assertTrue(any("event-building issue" in w for w in warnings))
        self.assertNotIn("DO_NOT_REPORT", json.dumps(result))

    def test_cap_stops_at_exact_candidate_budget_and_marks_remaining(self):
        self.dc.add_parent()
        for i in range(7):
            self.dc.add_memo(str(500 + i), date=f"2026-01-{i+1:02}", internal=str(900 + i))
            self.dc.failed.add(str(900 + i))
        result = self.run_excel()
        self.assertEqual(len(self.downloads()), 5)
        self.assertTrue(result["excel_summary"]["candidate_limit_reached"])
        row = self.csv()[0]
        self.assertEqual(row["Remaining Candidates"], "2")
        self.assertTrue(row["Status"].startswith("ATTEMPT LIMIT"))
        self.assertEqual(result["status"], "partial")

    def test_exact_exhaustion_is_not_incorrectly_reported_as_limit(self):
        self.basic()
        self.dc.failed.add("901")
        result = self.run_excel(self.settings(max_attempts=1))
        self.assertFalse(result["excel_summary"]["candidate_limit_reached"])
        self.assertEqual(self.csv()[0]["Status"], "NO DOWNLOAD: all eligible candidates exhausted")
        self.assertEqual(self.csv()[0]["Remaining Candidates"], "0")

    def test_success_at_budget_is_complete_when_no_more_jobs_need_attempts(self):
        self.basic()
        self.dc.add_memo("502", date="2020-01-01", internal="902")
        result = self.run_excel(self.settings(max_attempts=1))
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["excel_summary"]["candidate_limit_reached"])
        self.assertEqual(len(self.downloads()), 1)

    def test_later_policy_job_marked_not_attempted_when_population_cap_used(self):
        self.basic()
        self.dc.add_parent(name="Another Synthetic Fund", identifier="102")
        self.dc.add_memo("502", parent_id="102", internal="902")
        result = self.run_excel(self.settings([self.row(2), self.row(3, deal="Another Synthetic Fund")], max_attempts=1))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.csv()[1]["Status"], "NOT ATTEMPTED: population limit reached")
        self.assertEqual(self.csv()[1]["Candidates Tried"], "0")

    def test_cap_is_per_population_not_global(self):
        self.basic()
        self.dc.add_parent(population="Secondaries")
        self.dc.add_memo(population="Secondaries", internal="902")
        result = self.run_excel(self.settings([self.row(2), self.row(3, population="Secondaries")], max_attempts=1))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.downloads()), 2)

    def test_unlimited_attempts_can_reach_sixth_candidate(self):
        self.dc.add_parent()
        for i in range(6):
            self.dc.add_memo(str(500 + i), date=f"2026-01-{6-i:02}", internal=str(900 + i))
            if i < 5:
                self.dc.failed.add(str(900 + i))
        result = self.run_excel(self.settings(max_attempts=None))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.downloads()), 6)

    def test_preview_counts_not_limited_by_attempt_cap(self):
        self.dc.add_parent()
        for i in range(8):
            self.dc.add_memo(str(500 + i), internal=str(900 + i))
        result = self.run_excel(self.settings(max_attempts=1), preview=True)
        self.assertEqual(result["excel_summary"]["eligible_candidates"], 8)
        self.assertFalse(result["excel_summary"]["candidate_limit_reached"])
        self.assertEqual(result["status"], "completed")

    def test_repeated_attachment_deduplication_happens_after_policy_filter(self):
        self.dc.add_parent()
        self.dc.add_memo("501", stage="Final", internal="901")
        self.dc.add_memo("502", stage="Screening", internal="901")
        self.dc.add_memo("503", stage="Final", internal="901")
        self.run_excel(self.settings(default_policy="Screening"))
        self.assertEqual(self.downloads(), ["901"])
        self.assertEqual(self.csv()[0]["Memo Stage"], "Screening")
        self.assertEqual(self.csv()[0]["Eligible Candidates"], "1")

    def test_multifile_attachment_field_tries_next_attachment(self):
        self.dc.add_parent()
        self.dc.add_memo(internal=[{"id": "901", "name": "Synthetic one.pdf"}, {"id": "902", "name": "Synthetic two.pdf"}])
        self.dc.failed.add("901")
        self.run_excel()
        self.assertEqual(self.downloads(), ["901", "902"])

    def test_direct_file_field_needs_no_binary_discovery(self):
        self.dc.add_parent()
        self.dc.add_memo()
        self.dc.memos["Primaries"][0]["InternalMemo"] = "Synthetic direct memo.pdf"
        result = self.run_excel()
        self.assertEqual(result["status"], "completed")
        self.assertFalse(any(c[0] == "binary" for c in self.dc.calls))
        self.assertEqual(self.csv()[0]["Attachment ID"], "")

    def test_binary_discovery_error_is_audited(self):
        self.basic()
        self.dc.binary_error = True
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.downloads(), [])
        self.assertIn("binary field", self.csv("candidate_attempts.csv")[0]["Status"])
        self.assertNotIn("DO_NOT_REPORT", json.dumps(result))

    def test_strict_filename_skips_unknown_and_setting_restored(self):
        self.basic()
        self.dc.missing_filename.add("901")
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.downloads(), [])
        self.assertIn("strict filename", self.csv("candidate_attempts.csv")[0]["Status"])
        self.assertEqual(self.engine.REQUIRE_VERIFIABLE_FILENAME, "original sentinel")

    def test_non_strict_unknown_filename_downloads_with_visible_review_warning(self):
        self.basic()
        self.dc.missing_filename.add("901")
        result = self.run_excel(self.settings(strict_filename=False))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.downloads(), ["901"])
        self.assertTrue(self.csv()[0]["File"].endswith(".bin"))
        self.assertTrue(any("filename unknown" in w for w in result["population_results"][0]["source_warnings"]))

    def test_candidate_exception_is_counted_and_cannot_leak_credentials(self):
        self.basic()
        self.dc.save_exception = True
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["excel_summary"]["attempted_candidates"], 1)
        self.assertEqual(len(self.csv("candidate_attempts.csv")), 1)
        self.assertNotIn("DO_NOT_REPORT", (self.root / "Reports" / "run_settings.json").read_text())

    def test_empty_download_is_not_success(self):
        self.basic()
        self.dc.empty_saved_file = True
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.csv("downloaded_files.csv"), [])

    def test_download_file_outside_short_cache_rejected(self):
        self.basic()
        outside = Path(self.temporary.name) / "outside.pdf"
        outside.write_bytes(b"not a cache download")
        self.dc.unsafe_saved_file = outside
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.csv("downloaded_files.csv"), [])

    def test_cache_is_short_os_temp_and_removed_after_run(self):
        self.basic()
        self.run_excel()
        saved_path = Path(next(c[2] for c in self.dc.calls if c[0] == "download"))
        self.assertFalse(saved_path.is_relative_to(self.root))
        self.assertLess(len(saved_path.name), 20)
        self.assertFalse(saved_path.exists())

    def test_population_error_does_not_prevent_other_population(self):
        self.basic()
        self.dc.add_parent(population="CoInvestments")
        self.dc.add_memo(population="CoInvestments", internal="902")
        self.dc.missing_fields.add(("Fund", "FundName"))
        result = self.run_excel(self.settings([self.row(2), self.row(3, population="CoInvestments")]))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.downloads(), ["902"])
        self.assertEqual([p["status"] for p in result["population_results"]], ["partial", "completed"])

    def test_copy_failure_is_visible_and_not_counted_as_archived_success(self):
        self.basic()
        with mock.patch.object(x, "_copy", side_effect=OSError("DO_NOT_REPORT synthetic")):
            result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["excel_summary"]["memos_fetched"], 1)
        self.assertEqual(result["excel_summary"]["unique_memos_downloaded"], 0)
        self.assertEqual(result["excel_summary"]["memo_copies_written"], 0)
        self.assertEqual(self.csv("downloaded_files.csv"), [])
        self.assertTrue(self.csv()[0]["Status"].startswith("COPY FAILED"))

    def test_reports_reserved_name_and_case_collisions_are_safely_renamed(self):
        self.basic()
        rows = [self.row(2, client="Reports"), self.row(3, client="reports"), self.row(4, client="A/B"), self.row(5, client="A\\B")]
        result = self.run_excel(self.settings(rows))
        self.assertEqual(result["status"], "completed")
        files = self.csv("downloaded_files.csv")
        self.assertTrue(all(Path(r["File"]).parts[0].casefold() != "reports" for r in files))
        # "Reports"/"reports" are the same client, so they share one folder and one copy.
        self.assertEqual(len(files), 4)
        self.assertEqual(files[0]["File"], files[1]["File"])
        self.assertEqual(len({r["File"] for r in files}), 3)
        self.assertNotEqual(Path(files[2]["File"]).parts[0], Path(files[3]["File"]).parts[0])

    def test_excel_path_strings_are_data_never_filesystem_destinations(self):
        deal = "../../Synthetic / Fund : * " + "X" * 300
        self.dc.add_parent(name=deal)
        self.dc.add_memo()
        rows = [self.row(deal=deal, client="../../Reports", quarters=["../../elsewhere", "C:\\untrusted"])]
        result = self.run_excel(self.settings(rows, quarter_precedence="Keep all"))
        self.assertEqual(result["status"], "completed")
        for row in self.csv("downloaded_files.csv"):
            path = self.root / row["File"]
            self.assertTrue(path.resolve().is_relative_to(self.root))
            self.assertLessEqual(len(str(path)), 230)
            self.assertNotIn("..", Path(row["File"]).parts)

    def test_long_client_deal_and_quarter_names_fit_budget(self):
        deal = "Synthetic Deal " + "X" * 500
        self.dc.add_parent(name=deal)
        self.dc.add_memo()
        rows = [self.row(deal=deal, client="Client" + "Y" * 500, quarters=["Quarter" + "Z" * 500])]
        result = self.run_excel(self.settings(rows))
        self.assertEqual(result["status"], "completed")
        self.assertLessEqual(len(str(self.root / self.csv()[0]["File"])), 230)

    def test_very_long_output_root_fails_before_any_sdk_calls(self):
        long_root = self.root / ("x" * 100) / ("y" * 100)
        long_root.mkdir(parents=True)
        with self.assertRaises(OSError):
            x.run_excel(self.dc, self.engine, self.settings(), long_root, False)
        self.assertEqual(self.dc.calls, [])

    def test_existing_reports_refused_and_no_overwrite(self):
        reports = self.root / "Reports"
        reports.mkdir()
        sentinel = reports / "sentinel.txt"
        sentinel.write_text("keep")
        with self.assertRaises(FileExistsError):
            self.run_excel()
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertEqual(self.dc.calls, [])

    def test_destination_symlink_cannot_escape_root(self):
        self.basic()
        other = Path(self.temporary.name) / "other"
        other.mkdir()
        label = x._labels(["Synthetic Client"], 36, ["Reports"])["Synthetic Client"]
        try:
            (self.root / label).symlink_to(other, target_is_directory=True)
        except OSError:
            self.skipTest("Directory symlinks unavailable")
        result = self.run_excel()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(list(other.iterdir()), [])

    def test_csv_formula_injection_is_neutralized(self):
        self.dc.add_parent(name="=SYNTHETIC(1)")
        self.dc.add_memo()
        rows = [self.row(deal="=SYNTHETIC(1)", client="@synthetic", quarters=["+synthetic"])]
        self.run_excel(self.settings(rows))
        row = self.csv()[0]
        self.assertEqual(row["Deal"], "'=SYNTHETIC(1)")
        self.assertEqual(row["Client"], "'@synthetic")
        self.assertEqual(row["Quarter"], "'+synthetic")

    def test_defaults_and_optional_blank_client(self):
        self.basic()
        row = {"source_row": 2, "deal_name": "Synthetic Fund I", "population": "Primaries", "quarters": []}
        result = self.run_excel({"rows": [row]})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.csv()[0]["Client"], "")
        self.assertEqual(result["excel_summary"]["max_attempts"], 5)

    def test_invalid_settings_rejected_before_io(self):
        cases = [
            None, [], {}, {"rows": []}, {"rows": "not a list"},
            self.settings(max_attempts=0), self.settings(max_attempts=-1), self.settings(max_attempts=True),
            self.settings(max_attempts=1.5), self.settings(max_attempts="Unlimited"),
            self.settings(default_policy="Use app setting"), self.settings(default_policy="All"),
            self.settings(audience="Everyone"), self.settings(quarter_precedence="Q3"),
            self.settings(strict_filename="false"), self.settings(client_secret="DO_NOT_REPORT"),
            self.settings([self.row(source_row=True)]), self.settings([self.row(source_row=0)]),
            self.settings([self.row(source_row=1048577)]), self.settings([self.row(), self.row()]),
            self.settings([self.row(deal=" ")]), self.settings([self.row(deal=101)]),
            self.settings([self.row(population="Funds")]), self.settings([self.row(policy="Anything")]),
            self.settings([{**self.row(), "quarters": "Q1 2026"}]), self.settings([self.row(quarters=[42])]),
            self.settings([self.row(client=None)]), self.settings([{**self.row(), "arbitrary_path": "/tmp"}]),
        ]
        for settings in cases:
            with self.subTest(settings=repr(settings)[:80]):
                with self.assertRaises(ValueError):
                    x.run_excel(self.dc, self.engine, settings, self.root, False)
                self.assertFalse((self.root / "Reports").exists())
        self.assertEqual(self.dc.calls, [])

    def test_preview_must_be_boolean(self):
        with self.assertRaises(ValueError):
            x.run_excel(self.dc, self.engine, self.settings(), self.root, "false")
        self.assertEqual(self.dc.calls, [])

    def test_parent_queries_are_batched_by_50_not_unscoped(self):
        names = []
        for i in range(51):
            name = f"Synthetic Fund {i}"
            names.append(name)
            self.dc.add_parent(name=name, identifier=str(100 + i))
        result = x.read_parents(self.dc, self.engine, "Primaries", names)
        self.assertEqual(len(result), 51)
        calls = [c for c in self.dc.calls if c[0] == "read"]
        self.assertEqual([len(c[3]["FundName"]["$in"]) for c in calls], [50, 1])

    def test_parent_query_validates_against_its_own_batch_not_whole_list(self):
        names = [f"Synthetic Fund {i}" for i in range(51)]
        self.dc.parent_injection = {"EntryId": "999", "FundName": names[-1]}
        with self.assertRaises(ValueError):
            x.read_parents(self.dc, self.engine, "Primaries", names)

    def test_memo_queries_batched_by_100_and_both_resolutions(self):
        ids = [str(100 + i) for i in range(101)]
        names, raw, _ = x.read_memos(self.dc, self.engine, "Primaries", ids, [])
        self.assertTrue(names.empty and raw.empty)
        calls = [c for c in self.dc.calls if c[0] == "read"]
        self.assertEqual([len(c[3]["Fund"]["$in"]) for c in calls], [100, 100, 1, 1])
        self.assertEqual([c[2] for c in calls], ["id", "name", "id", "name"])

    def test_device_names_and_dot_components_are_sanitized(self):
        for value in ("CON", "NUL.txt", "COM1", "LPT9"):
            self.assertTrue(x._safe(value, 50).startswith("_"))
        self.assertEqual(x._safe("..", 20), "Unassigned")
        self.assertNotIn("/", x._safe("a/b", 20))
        self.assertNotIn("\\", x._safe("a\\b", 20))

    def test_grouped_same_deal_many_clients_downloads_once_one_copy_per_client(self):
        self.basic()
        rows = [self.row(2, client="Client Alpha"), self.row(3, client="Client Beta"),
                self.row(4, client="client alpha"), self.row(5, client="Client Gamma")]
        result = self.run_excel(self.settings(rows, output_layout="grouped"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.downloads()), 1)
        summary = result["excel_summary"]
        self.assertEqual(summary["unique_memos_downloaded"], 1)
        self.assertEqual(summary["memo_copies_written"], 3)
        self.assertEqual(summary["client_folders"], 3)
        files = self.csv("downloaded_files.csv")
        folders = [Path(r["File"]).parts[0] for r in files]
        # Readable first-seen spelling, not a casefolded key.
        self.assertEqual(folders, ["Client Alpha", "Client Beta", "Client Alpha", "Client Gamma"])
        self.assertEqual(files[0]["File"], files[2]["File"])
        for row in files:
            self.assertTrue((self.root / row["File"]).is_file())

    def test_grouped_blank_client_uses_no_client_folder_without_merging_named_client(self):
        self.basic()
        rows = [self.row(2, client=""), self.row(3, client="Unassigned")]
        self.run_excel(self.settings(rows, output_layout="grouped"))
        folders = [Path(r["File"]).parts[0] for r in self.csv("downloaded_files.csv")]
        self.assertEqual(folders, ["No Client", "Unassigned"])

    def test_flat_layout_ignores_client_and_writes_one_copy(self):
        self.basic()
        rows = [self.row(2, client="Client Alpha"), self.row(3, client="Client Beta")]
        result = self.run_excel(self.settings(rows, output_layout="flat"))
        self.assertEqual(result["excel_summary"]["memo_copies_written"], 1)
        files = self.csv("downloaded_files.csv")
        self.assertEqual(len(Path(files[0]["File"]).parts), 1)
        self.assertNotIn("Client", files[0])

    def test_grouped_long_client_name_stays_readable_without_quarters(self):
        self.basic()
        long_root = self.root / ("r" * 60)
        long_root.mkdir()
        name = "Pennsylvania Public School Employees Retirement"
        rows = [self.row(2, client=name)]
        x.run_excel(self.dc, self.engine, self.settings(rows, output_layout="grouped"), long_root, False)
        with (long_root / "Reports" / "downloaded_files.csv").open(encoding="utf-8-sig", newline="") as stream:
            file = next(csv.DictReader(stream))["File"]
        self.assertEqual(Path(file).parts[0], name)
        self.assertLessEqual(len(str(long_root / file)), 230)
    def test_long_similar_client_names_stay_distinguishable_and_readable(self):
        self.basic()
        long_root = self.root / ("r" * 75)   # about the length of a real Windows batch path
        long_root.mkdir()
        clients = ["Hamilton Lane Global Private Assets Fund (Lux) SICAV Feeder I",
                   "Hamilton Lane Global Private Assets Fund (Lux) SICAV Feeder II",
                   "Hamilton Lane Secondary Fund V LP", "Hamilton Lane Secondary Fund VI LP"]
        rows = [self.row(i + 2, client=c, quarters=["Q3 2026"]) for i, c in enumerate(clients)]
        x.run_excel(self.dc, self.engine, self.settings(rows, output_layout="grouped"), long_root, False)
        with (long_root / "Reports" / "downloaded_files.csv").open(encoding="utf-8-sig", newline="") as stream:
            files = [r["File"] for r in csv.DictReader(stream)]
        folders = [Path(f).parts[0] for f in files]
        self.assertEqual(len(set(folders)), 4)
        self.assertEqual(folders[2:], ["Hamilton Lane Secondary Fund V LP", "Hamilton Lane Secondary Fund VI LP"])
        for folder in folders[:2]:
            self.assertTrue(folder.startswith("Hamilton Lane"), folder)
            self.assertNotRegex(folder, r"-[0-9a-f]{8}$")   # no random code when names differ
        self.assertTrue(folders[0].endswith("Feeder I") and folders[1].endswith("Feeder II"))
        for f in files:
            self.assertLessEqual(len(str(long_root / f)), 230)

    def test_file_names_have_no_random_code(self):
        self.basic()
        self.run_excel()
        name = Path(self.csv("downloaded_files.csv")[0]["File"]).name
        self.assertEqual(name, "Synthetic Fund I - 2026-01-15 - Final - Internal.pdf")

    def test_shorten_keeps_whole_words_from_both_ends(self):
        self.assertEqual(x._shorten("Hamilton Lane Strategic Opportunities Fund VIII (Offshore) LP", 40),
                         "Hamilton Lane~Fund VIII (Offshore) LP")
        self.assertEqual(x._shorten("Short name", 40), "Short name")
        self.assertLessEqual(len(x._shorten("Supercalifragilisticexpialidociousfundname", 20)), 20)



class ExcelPeriodParsingTests(unittest.TestCase):
    def test_quarter_formats_and_year_column(self):
        from excel_input import parse_quarters
        cases = [("Q3 2026", None, ["Q3 2026"]), ("2026 Q3", None, ["Q3 2026"]), ("q3-26", None, ["Q3 2026"]),
                 ("3Q26", None, ["Q3 2026"]), ("Quarter 4 2025", None, ["Q4 2025"]), ("Q3 FY26", None, ["Q3 2026"]),
                 ("Q1; Q4", 2026, ["Q1 2026", "Q4 2026"]), (3, 2026, ["Q3 2026"]), ("Q2", None, ["Q2"]),
                 (None, 2025, ["2025"]), ("2026", None, ["2026"]),
                 ("Q1 2026; Q2 2026; Q3 2026; Q4 2026; Q1 2026", None, ["Q1 2026", "Q2 2026", "Q3 2026", "Q4 2026"])]
        for value, year, expected in cases:
            self.assertEqual(parse_quarters(value, year), expected, (value, year))

    def test_bad_quarters_and_conflicting_year_are_errors(self):
        from excel_input import parse_quarters, parse_year
        for value, year in [("Q5", None), ("third quarter", None), ("Q3 2025", 2026)]:
            with self.assertRaises(ValueError):
                parse_quarters(value, year)
        self.assertEqual([parse_year(v) for v in (2026, 2026.0, "FY26", "FY2026", None)], [2026, 2026, 2026, 2026, None])
        with self.assertRaises(ValueError):
            parse_year("next year")

    def test_validate_rows_combines_year_and_quarter_columns(self):
        from excel_input import validate_rows
        records = [{"source_row": 2, "formula_columns": [],
                    "values": {"Deal": "Fund A", "Client": "Acme", "Year": 2026, "Qtr": "Q1; Q3"}}]
        valid, errors = validate_rows(records, {"deal_name": "Deal", "client": "Client", "year": "Year", "quarters": "Qtr"}, "Primaries")
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["quarters"], ["Q1 2026", "Q3 2026"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
