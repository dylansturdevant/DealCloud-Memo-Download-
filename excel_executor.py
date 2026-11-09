"""Read-only Excel-list execution; no tenant configuration or credentials here.

``engine`` is the application's downloader_engine module (dependency injected).
Only filtered name and memo-reference reads are permitted. Selection is local:
no IC-date window, approval or recommendation restriction, including when the
engine's ordinary UI mode has such restrictions enabled. Undated records cannot
be ranked and are audited as coverage warnings.

The candidate-attempt budget is PER POPULATION, not per row, attachment HTTP
request, or retry. None means unlimited; the default is 5. Preview never consumes
that budget and never discovers attachment binary fields or requests metadata.
The parent application owns job/process isolation and must supply a unique,
trusted output directory. Every persistent File value is relative to that root.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

POPULATIONS = ("Primaries", "CoInvestments", "Secondaries")
STAGES = ("Final", "Screening", "Follow-On", "Update")
POLICIES = (*STAGES, "Priority fallback", "Latest available")
AUDIENCES = ("Internal then Client", "Internal only", "Client only")
# When one client lists the same deal/policy in several quarters of one year:
# keep a copy in every listed quarter, or only the earliest / latest of them.
QUARTER_RULES = ("Keep all", "Earliest", "Latest")
QUARTER_LABEL = re.compile(r"Q([1-4])(?:\s+(\d{4}))?", re.IGNORECASE)
YEAR_LABEL = re.compile(r"\d{4}")
PATH_BUDGET = 230
# Room kept after the folders for the file name: a readable deal name (>= 24
# chars) plus the longest suffix " - YYYY-MM-DD - Follow-On - Internal-9999.<ext>".
FILE_RESERVE = 79
RESULT_COLUMNS = [
    "Source Row", "Deal", "Population", "Client", "Quarter", "Policy", "Status",
    "Parent ID", "Memo Stage", "IC Date", "Audience", "File", "Eligible Candidates",
    "Candidates Tried", "Remaining Candidates", "Event ID", "Attachment ID",
    "Intended Event ID", "Intended Attachment ID", "Detail",
]
ATTEMPT_COLUMNS = [
    "Population", "Deal", "Parent ID", "Policy", "Candidate", "Event ID", "IC Date",
    "Memo Stage", "Audience", "Source", "Field", "Attachment ID", "Status", "File",
]


def exact_name(value: str) -> str:
    """Exact modulo case and runs of whitespace; punctuation stays significant."""
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def _text(value: Any, label: str, *, blank: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 4000 or "\x00" in value:
        raise ValueError(f"{label} must be a string of at most 4000 characters.")
    value = re.sub(r"\s+", " ", value).strip()
    if not value and not blank:
        raise ValueError(f"{label} must not be blank.")
    return value


def validate_settings(settings: dict, preview: bool) -> dict:
    """Fail before API reads or output creation; whitelist all persisted inputs."""
    if not isinstance(preview, bool):
        raise ValueError("preview must be a boolean.")
    allowed = {"rows", "default_policy", "audience", "quarter_precedence", "strict_filename", "max_attempts", "output_layout"}
    if not isinstance(settings, dict) or set(settings) - allowed:
        raise ValueError("Excel settings contain unsupported keys or are not a dictionary.")
    result = {
        "output_layout": settings.get("output_layout", "grouped"),
        "default_policy": settings.get("default_policy", "Priority fallback"),
        "audience": settings.get("audience", "Internal then Client"),
        "quarter_precedence": settings.get("quarter_precedence", "Keep all"),
        "strict_filename": settings.get("strict_filename", True),
        "max_attempts": settings.get("max_attempts", 5),
    }
    if result["output_layout"] not in {"flat", "grouped"}:
        raise ValueError("Unsupported output_layout.")
    if result["default_policy"] not in POLICIES:
        raise ValueError("Unsupported default_policy.")
    if result["audience"] not in AUDIENCES:
        raise ValueError("Unsupported audience.")
    if result["quarter_precedence"] not in QUARTER_RULES:
        raise ValueError("Unsupported quarter_precedence.")
    if not isinstance(result["strict_filename"], bool):
        raise ValueError("strict_filename must be a boolean.")
    cap = result["max_attempts"]
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1):
        raise ValueError("max_attempts must be a positive integer or None (unlimited).")
    rows = settings.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows must be a nonempty list.")
    normalized, seen = [], set()
    for row in rows:
        row_keys = {"source_row", "deal_name", "population", "client", "quarters", "memo_type"}
        if not isinstance(row, dict) or set(row) - row_keys:
            raise ValueError("An Excel row contains unsupported keys or is not a dictionary.")
        source_row = row.get("source_row")
        if isinstance(source_row, bool) or not isinstance(source_row, int) or not 1 <= source_row <= 1048576:
            raise ValueError("source_row must be a valid positive Excel row number.")
        if source_row in seen:
            raise ValueError("source_row values must be unique.")
        seen.add(source_row)
        population = row.get("population")
        if population not in POPULATIONS:
            raise ValueError("Unsupported row population.")
        policy = row.get("memo_type", "Use app setting")
        if policy not in ("Use app setting", *POLICIES):
            raise ValueError("Unsupported row memo_type.")
        quarters = row.get("quarters", [])
        if not isinstance(quarters, list):
            raise ValueError("quarters must be a list of strings.")
        quarters = list(dict.fromkeys(_text(q, "Quarter") for q in quarters))
        normalized.append({
            "source_row": source_row, "deal_name": _text(row.get("deal_name"), "Deal name"),
            "population": population, "client": _text(row.get("client", ""), "Client", blank=True),
            "quarters": quarters, "memo_type": policy,
        })
    if result["output_layout"] == "flat":
        for row in normalized:
            row["client"] = ""
            row["quarters"] = []
        result["quarter_precedence"] = "Keep all"
    result["rows"] = normalized
    return result


def read_parents(dc, e, population: str, requested: list[str]) -> dict:
    """Subset of the reusable one-off helper; scoped queries, no broad fallback."""
    config = e.POPULATION_CONFIG[population]
    api = e.api_field_selection(dc, config["parent"], config["names"][:1])
    matched = defaultdict(dict)
    for offset in range(0, len(requested), 50):
        batch = requested[offset:offset + 50]
        frame = e.filtered_read(dc, config["parent"], api, {api[0]: {"$in": batch}}, "name")
        e.attach_field_schema_aliases(dc, config["parent"], frame)
        if frame.empty:
            continue
        id_col = e.find_column(frame, e.EVENT_FIELD_CANDIDATES["entry_id"])
        name_col = e.find_column(frame, config["names"])
        if id_col is None or name_col is None:
            raise KeyError("Parent read did not expose ID and mapped name.")
        wanted = {exact_name(name) for name in batch}
        for _, row in frame.iterrows():
            label = e.human_text(row[name_col])
            name = exact_name(label)
            if name not in wanted:
                raise ValueError("Parent query returned an unrelated name; broad fallback forbidden.")
            identifier = e.normalize_entry_id(row[id_col])
            if not re.fullmatch(r"[0-9]+", identifier) or int(identifier) <= 0:
                raise ValueError("Parent query returned an invalid ID.")
            matched[name][identifier] = label
    return dict(matched)


def read_memos(dc, e, population: str, ids: list[str], warnings: list[str], audience: str = "Internal then Client"):
    """Read each mapped attachment stream; validate IDs before building events."""
    import pandas as pd
    config = e.POPULATION_CONFIG[population]
    obj = config["memo_object"]
    required = e.api_field_selection(dc, obj, [config["reference"], "ICDate", "Stage"])
    available = {"Internal": [], "Client": []}
    for label, fields in (("Internal", config["internal"]), ("Client", config["client"])):
        if (audience == "Internal only" and label == "Client") or (audience == "Client only" and label == "Internal"):
            continue
        for field in fields:
            try:
                required += e.api_field_selection(dc, obj, [field])
                available[label].append(field)
            except KeyError:
                warnings.append(f"{obj}.{field} inaccessible in schema; source coverage is incomplete.")
    if not any(available.values()):
        raise ValueError("No mapped memo attachment fields accessible for the selected audience.")
    reference_api = e.api_field_selection(dc, obj, [config["reference"]])[0]
    raw_frames, name_frames = [], []
    for offset in range(0, len(ids), 100):
        batch = ids[offset:offset + 100]
        query = {reference_api: {"$in": [int(x) for x in batch]}}
        frames = []
        for resolution in ("id", "name"):
            frame = e.filtered_read(dc, obj, list(dict.fromkeys(required)), query, resolution)
            e.attach_field_schema_aliases(dc, obj, frame)
            frames.append(frame)
        raw, names = frames
        ref_col = e.find_column(raw, [config["reference"]])
        if not raw.empty:
            if ref_col is None:
                raise KeyError("Memo read is missing the mapped parent reference.")
            for cell in raw[ref_col]:
                refs = set(e.extract_reference_ids(cell))
                if not refs or not refs.issubset(set(batch)):
                    raise ValueError("Memo query returned unrelated or unparseable parent references.")
        e.validate_event_pairing(names, raw)
        raw_frames.append(raw)
        name_frames.append(names)
    if not raw_frames:
        return pd.DataFrame(), pd.DataFrame(), available
    raw, names = pd.concat(raw_frames, ignore_index=True), pd.concat(name_frames, ignore_index=True)
    e.attach_field_schema_aliases(dc, obj, raw, names)
    e.validate_event_pairing(names, raw)
    return names, raw, available


def _collect(dc, e, population: str, ids: list[str], warnings: list[str], audience: str):
    config = e.POPULATION_CONFIG[population]
    names, raw, available = read_memos(dc, e, population, ids, warnings, audience)
    choices = {identifier: [] for identifier in ids}
    sources = {}
    for label, fields in available.items():
        for field in fields:
            if raw.empty and names.empty:
                continue
            if e.find_column(names, [field]) is None and e.find_column(raw, [field]) is None:
                warnings.append(f"{config['memo_object']}.{field} not returned; source coverage is incomplete.")
                continue
            source = config["memo_object"] + "/" + field
            sources[source] = config["memo_object"]
            events, problems = e.build_events(
                source, names, raw, reference_candidates=[config["reference"]],
                field_overrides={"date": ["ICDate"], "stage": ["Stage"], "recommendation": [],
                                 "internal_memo": [field] if label == "Internal" else [],
                                 "client_ready_memo": [field] if label == "Client" else []},
            )
            if problems:
                # Do not persist raw SDK diagnostics: they may contain secrets/URLs.
                warnings.append(f"{source}: {len(problems)} event-building issue(s); source coverage is incomplete.")
            undated = 0
            for event in e.deduplicate_events(events):
                if event.deal_id not in choices:
                    raise ValueError("Event builder produced an unrelated parent ID.")
                tier = e.memo_stage_priority(event)
                if tier is None:
                    continue
                if tier not in range(4):
                    raise ValueError("Unsupported memo stage rank from engine.")
                kind = "InternalMemo" if label == "Internal" else "ClientReadyMemo"
                value = event.internal_value if label == "Internal" else event.client_ready_value
                display = event.internal_display if label == "Internal" else event.client_ready_display
                file_field = event.internal_field if label == "Internal" else event.client_ready_field
                if e.is_missing(value):
                    continue
                if e.is_missing(event.event_date):
                    undated += 1
                    continue
                # Deliberately do not call event.in_window or selected_memo_candidates.
                for raw_item, display_item in e.attachment_field_items(value, display):
                    if e.is_missing(raw_item):
                        continue
                    text = raw_item if e.is_missing(display_item) else display_item
                    if e.is_supplementary_memo_text(text):
                        continue
                    choices[event.deal_id].append((event, kind, raw_item, file_field or field, display_item))
            if undated:
                warnings.append(f"{source}: {undated} undated eligible-stage event(s) excluded; recency cannot be determined.")
    return choices, sources


def _rank(e, choices: list, policy: str) -> list:
    if policy in STAGES:
        choices = [c for c in choices if STAGES[e.memo_stage_priority(c[0])] == policy]
    if policy == "Latest available":
        key = lambda c: (-c[0].event_date.value, c[1] != "InternalMemo", e.memo_stage_priority(c[0]), c[0].source, c[0].event_id)
    else:
        key = lambda c: (e.memo_stage_priority(c[0]), c[1] != "InternalMemo", -c[0].event_date.value, c[0].source, c[0].event_id)
    unique, seen = [], set()
    for choice in sorted(choices, key=key):
        event, _, value, field, _ = choice
        ref = e.first_reference_id(value)
        identity = ("attachment", ref) if ref else ("direct", event.source, event.event_id, field)
        if identity not in seen:
            seen.add(identity)
            unique.append(choice)
    return unique


def _safe(value: str, limit: int) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", str(value))
    value = re.sub(r"\s+", " ", value).strip(" .") or "Unassigned"
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "_" + value
    if len(value) > limit:
        value = value[:limit - 9].rstrip(" .") + "-" + hashlib.sha256(value.encode()).hexdigest()[:8]
    return value


def _shorten(value: str, limit: int) -> str:
    """Filesystem-safe name of at most ``limit`` chars, shortened in the MIDDLE.

    Long names in one family usually share a prefix ("Hamilton Lane Secondary
    Fund V" / "... Fund VI"), so keeping both ends keeps them distinguishable:
    "Hamilton Lane Secondary~Fund VI LP". No random code is added; callers
    resolve the rare remaining collisions.
    """
    value = _safe(value, 10 ** 6)
    if len(value) <= limit:
        return value
    keep = limit - 1
    words = value.split(" ")
    # Always keep the trailing words that fit in half the space (fund numbers,
    # "LP", "(Lux)" live there) and the leading words that fit in a third
    # (the family name); then pick the whole-word split that keeps the most text.
    tail_from = len(words) - 1
    while tail_from > 1 and len(" ".join(words[tail_from - 1:])) <= keep // 2:
        tail_from -= 1
    head_to = 1
    while head_to < tail_from and len(" ".join(words[:head_to + 1])) <= keep // 3:
        head_to += 1
    best, head, tail = (-1, -1), "", ""
    for minimum_head, maximum_tail in ((head_to, tail_from), (1, len(words) - 1)):
        for i in range(minimum_head, len(words)):
            start_text = " ".join(words[:i]).rstrip(" .-,")
            for j in range(maximum_tail, i - 1, -1):
                end_text = " ".join(words[j:]).lstrip(" .-,")
                if len(start_text) + len(end_text) > keep:
                    break
                score = (len(start_text) + len(end_text), len(end_text))
                if start_text and end_text and score > best:
                    best, head, tail = score, start_text, end_text
        if head:
            break
    if not head or not tail:
        # A single very long word: fall back to a plain character cut.
        tail = value[len(value) - keep // 2:].lstrip(" .-,")
        head = value[:keep - len(tail)].rstrip(" .-,")
    return _safe(f"{head}~{tail}", limit)


def _labels(values, limit: int, reserved=(), display=None, shorten=_safe) -> dict:
    """Unique, filesystem-safe folder label per value; ``display`` maps a value to its readable text."""
    labels, used = {}, {x.casefold() for x in reserved}
    for value in sorted(set(values)):
        text = display[value] if display else value
        base = shorten(text, limit)
        candidate = base
        number = 0
        while candidate.casefold() in used:
            digest = hashlib.sha256((value + str(number)).encode()).hexdigest()[:8]
            candidate = shorten(text, limit - 9).rstrip(" .") + "-" + digest
            number += 1
        labels[value] = candidate
        used.add(candidate.casefold())
    return labels


def _client_display_names(rows: list) -> dict:
    """Normalized client key -> first-seen workbook spelling (keeps readable casing).

    Rows whose client differs only by case/whitespace share one folder, named
    after the first spelling in workbook order. Blank clients share one
    "No Client" folder.
    """
    display = {}
    for row in sorted(rows, key=lambda r: r["source_row"]):
        display.setdefault(exact_name(row["client"]), row["client"].strip() or "No Client")
    return display


def _period_parts(label: str):
    """Folder components for a normalized period label, or None if nonstandard."""
    match = QUARTER_LABEL.fullmatch(label)
    if match:
        return [match[2], f"Q{match[1]}"] if match[2] else [f"Q{match[1]}"]
    if YEAR_LABEL.fullmatch(label):
        return [label]
    return None


def _directories(output: Path, rows: list):
    room = PATH_BUDGET - len(str(output))
    # Standard periods become short nested folders: "Q3 2026" -> 2026/Q3,
    # "2026" -> 2026, "Q3" -> Q3. Anything else is one sanitized folder name.
    custom = _labels((q for r in rows for q in r["quarters"] if _period_parts(q) is None),
                     min(36, max(12, (room - FILE_RESERVE) // 2)))
    periods = {q: _period_parts(q) or [custom[q]] for r in rows for q in r["quarters"]}
    period_room = max((sum(len(p) + 1 for p in parts) for parts in periods.values()), default=0)
    # The client folder gets everything the period folders and file name don't need.
    limit = min(80, max(12, room - FILE_RESERVE - period_room - 1))
    display = _client_display_names(rows)
    clients = _labels(display, limit, ("Reports",), display, shorten=_shorten)
    dirs = {}
    for row in rows:
        for quarter in row["quarters"] or [""]:
            directory = output / clients[exact_name(row["client"])]
            for part in periods.get(quarter, []):
                directory /= part
            if len(str(directory)) + FILE_RESERVE > PATH_BUDGET:
                raise OSError("Output root is too long for the 230-character destination budget; choose a shorter root.")
            dirs[(row["source_row"], quarter)] = directory
    return dirs


def _copy(output: Path, directory: Path, source: Path, row: dict, quarter: str, policy: str, memo: dict) -> str:
    if not directory.resolve().is_relative_to(output):
        raise OSError("Unsafe destination directory.")
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(output):
        raise OSError("Unsafe destination directory.")
    extension = source.suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,12}", extension):
        extension = ".bin"
    # Readable name: "<Deal> - <IC date> - <Stage> - <Audience>.pdf". Each folder
    # gets one copy per deal/policy, so a "-1" suffix appears only if two policies
    # pick the same memo for the same folder.
    for number in range(10000):
        collision = "" if not number else f"-{number}"
        suffix = f" - {memo['date']} - {memo['stage']} - {memo['audience']}{collision}{extension}"
        space = min(80, PATH_BUDGET - len(str(directory)) - 1 - len(suffix))
        if space < 12:
            raise OSError("Destination exceeds the safe path budget.")
        destination = directory / (_shorten(row["deal_name"], space) + suffix)
        if len(str(destination)) > PATH_BUDGET:
            raise OSError("Destination exceeds the safe path budget.")
        try:
            # Exclusive creation prevents overwriting an existing file or symlink.
            target = destination.open("xb")
        except FileExistsError:
            continue
        try:
            with target, source.open("rb") as incoming:
                shutil.copyfileobj(incoming, target)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return destination.relative_to(output).as_posix()
    raise OSError("Destination collision limit reached.")


def _suppressed(rows: list, outcomes: dict, rule: str) -> set:
    """(source_row, quarter) pairs to skip under the Earliest/Latest quarter rule.

    Grouped per client, population, resolved deal, effective policy and year
    (quarters without a year form their own group). Year-only and nonstandard
    labels are never suppressed.
    """
    if rule == "Keep all":
        return set()
    groups = defaultdict(set)
    keys = {}
    for row in rows:
        outcome = outcomes[row["source_row"]]
        identity = outcome.get("parent_id") or ("name", exact_name(row["deal_name"]))
        keys[row["source_row"]] = (exact_name(row["client"]), row["population"], identity, outcome["policy"])
        for q in row["quarters"]:
            match = QUARTER_LABEL.fullmatch(q)
            if match:
                groups[(keys[row["source_row"]], match[2])].add(int(match[1]))
    result = set()
    for row in rows:
        for q in row["quarters"]:
            match = QUARTER_LABEL.fullmatch(q)
            if not match:
                continue
            listed = groups[(keys[row["source_row"]], match[2])]
            keep = min(listed) if rule == "Earliest" else max(listed)
            if int(match[1]) != keep:
                result.add((row["source_row"], q))
    return result


def _write_csv(path: Path, rows: list, columns: list) -> None:
    def cell(value):
        if isinstance(value, str):
            value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
            if value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
        return value
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: cell(row.get(k, "")) for k in columns} for row in rows)


@contextmanager
def _filename_setting(engine, strict: bool):
    sentinel = object()
    old = getattr(engine, "REQUIRE_VERIFIABLE_FILENAME", sentinel)
    engine.REQUIRE_VERIFIABLE_FILENAME = strict
    try:
        yield
    finally:
        if old is sentinel:
            delattr(engine, "REQUIRE_VERIFIABLE_FILENAME")
        else:
            engine.REQUIRE_VERIFIABLE_FILENAME = old


def _intended(e, choice) -> dict:
    event, kind, value, _, _ = choice
    return {"stage": STAGES[e.memo_stage_priority(event)], "date": event.event_date.strftime("%Y-%m-%d"),
            "audience": "Internal" if kind == "InternalMemo" else "Client", "event_id": str(event.event_id),
            "attachment_id": e.first_reference_id(value) or ""}


def _status(raw: Any, success: bool) -> str:
    """Never copy SDK exception messages, tenant URLs or metadata into reports."""
    text = str(raw).casefold()
    if success:
        return "DOWNLOADED: filename unknown; review required" if "filename unknown" in text else "DOWNLOADED"
    if "supplementary" in text:
        return "SKIPPED: supplementary material"
    if "filename unavailable" in text:
        return "SKIPPED: filename unavailable (strict filename)"
    if "binary field" in text:
        return "FAILED: attachment binary field unavailable"
    return "FAILED: candidate could not be saved"


def run_excel(dc, engine, settings, output: Path, preview: bool) -> dict:
    """Execute a validated Excel list and write portable, credential-free reports.

    Returns status completed/partial, output '.', population_results and an
    excel_summary. Unknown/ambiguous names, missing memos, exhausted candidates,
    cap-limited jobs, population errors, copy errors, or coverage warnings make
    the run partial. Preview success means an intended candidate, not a verified
    downloadable file. Suppressed quarters alone do not make a run partial.
    """
    settings = validate_settings(settings, preview)
    rows = settings["rows"]
    output = Path(output).resolve()
    if not output.is_dir():
        raise ValueError("The trusted output root must already exist.")
    directories = ({(row["source_row"], ""): output for row in rows} if settings["output_layout"] == "flat" else _directories(output, rows))
    reports = output / "Reports"
    # The parent worker creates Reports/worker.log before execution. Permit only
    # that file (or an empty directory), never reuse completed result reports.
    reports.mkdir(exist_ok=True)
    if any(p.name != 'worker.log' or not p.is_file() or p.is_symlink() for p in reports.iterdir()):
        raise FileExistsError('This batch already contains report files; allocate a new batch.')
    requested = defaultdict(dict)
    outcomes, jobs, populations, attempts = {}, {}, [], []
    for row in rows:
        requested[row["population"]][exact_name(row["deal_name"])] = row["deal_name"]
        outcomes[row["source_row"]] = {"policy": settings["default_policy"] if row["memo_type"] == "Use app setting" else row["memo_type"], "status": "NOT PROCESSED", "parent_id": ""}
    binary, binary_checked = None, False
    with tempfile.TemporaryDirectory(prefix="dcm-") as temporary, _filename_setting(engine, settings["strict_filename"]):
        cache = Path(temporary).resolve()
        for population, names in requested.items():
            warnings = []
            pop = {"population": population, "status": "completed", "requested_names": len(names),
                   "matched_parents": 0, "unique_policy_jobs": 0, "eligible_candidates": 0,
                   "attempted_candidates": 0, "downloaded": 0, "memos_fetched": 0,
                   "memo_copies_written": 0, "candidate_limit_reached": False, "source_warnings": warnings}
            populations.append(pop)
            pop_rows = [r for r in rows if r["population"] == population]
            try:
                parents = read_parents(dc, engine, population, list(names.values()))
                resolved = set()
                for row in pop_rows:
                    outcome = outcomes[row["source_row"]]
                    matches = parents.get(exact_name(row["deal_name"]), {})
                    if len(matches) != 1:
                        outcome["status"] = "UNMATCHED" if not matches else "AMBIGUOUS: multiple parent IDs"
                        warnings.append(f"Source row {row['source_row']}: {outcome['status']}; no guessed ID or fuzzy match used.")
                        continue
                    identifier = next(iter(matches))
                    resolved.add(identifier)
                    outcome["parent_id"] = identifier
                    key = (population, identifier, outcome["policy"])
                    outcome["job_key"] = key
                    if key not in jobs:
                        jobs[key] = {"parent_id": identifier, "policy": outcome["policy"], "deal": row["deal_name"],
                                     "status": "MATCHED", "choices": [], "tried": 0, "file": "", "copied_files": []}
                pop["matched_parents"] = len(resolved)
                pop_jobs = [(key, job) for key, job in jobs.items() if key[0] == population]
                pop["unique_policy_jobs"] = len(pop_jobs)
                if not resolved:
                    continue
                collected, sources = _collect(dc, engine, population, sorted(resolved, key=int), warnings, settings["audience"])
                for _, job in pop_jobs:
                    job["choices"] = _rank(engine, collected[job["parent_id"]], job["policy"])
                    choices = job["choices"]
                    pop["eligible_candidates"] += len(choices)
                    if choices:
                        job["intended"] = _intended(engine, choices[0])
                    if not choices:
                        job["status"] = "NO ELIGIBLE DATED MEMO"
                        continue
                    if preview:
                        job["status"] = "PREVIEW: candidates found (not download verified)"
                        continue
                    for number, choice in enumerate(choices, 1):
                        cap = settings["max_attempts"]
                        if cap is not None and pop["attempted_candidates"] >= cap:
                            job["status"] = "ATTEMPT LIMIT: candidates remain" if job["tried"] else "NOT ATTEMPTED: population limit reached"
                            pop["candidate_limit_reached"] = True
                            break
                        if engine.first_reference_id(choice[2]) and not binary_checked:
                            binary_checked = True
                            try:
                                binary = engine.discover_attachment_binary_field(dc, engine.ATTACHMENT_OBJECT, engine.ATTACHMENT_BINARY_FIELD)
                            except Exception as exc:
                                warnings.append(f"Attachment binary field discovery failed ({type(exc).__name__}); coverage is incomplete.")
                        jobcache = cache / str(len(attempts) + 1)
                        jobcache.mkdir()
                        saved = {"Status": "FAILED", "File": ""}
                        try:
                            saved = engine.save_candidate(dc, job["parent_id"], "M", choice, jobcache, binary, sources)
                            if not isinstance(saved, dict):
                                raise TypeError("Unexpected candidate result.")
                            if saved.get("File"):
                                source = Path(saved["File"]).resolve()
                                if not source.is_relative_to(jobcache) or not source.is_file() or not source.stat().st_size:
                                    raise OSError("Invalid or empty cache result.")
                                job["file"] = str(source)
                        except Exception:
                            saved = {"Status": "FAILED", "File": ""}
                        job["tried"] += 1
                        pop["attempted_candidates"] += 1
                        intended = _intended(engine, choice)
                        status = _status(saved.get("Status", ""), bool(job["file"]))
                        attempt = {"Population": population, "Deal": job["deal"], "Parent ID": job["parent_id"], "Policy": job["policy"],
                                   "Candidate": number, "Event ID": intended["event_id"], "IC Date": intended["date"],
                                   "Memo Stage": intended["stage"], "Audience": intended["audience"], "Source": choice[0].source,
                                   "Field": choice[3], "Attachment ID": intended["attachment_id"], "Status": status, "File": ""}
                        attempts.append(attempt)
                        if job["file"]:
                            job.update(intended)
                            job["status"] = status
                            job["successful_attempt"] = attempt
                            pop["memos_fetched"] += 1
                            if "review required" in status:
                                warnings.append(f"Parent ID {job['parent_id']}: downloaded filename unknown; supplementary exclusion requires review.")
                            break
                    else:
                        job["status"] = "NO DOWNLOAD: all eligible candidates exhausted"
                if pop["candidate_limit_reached"]:
                    warnings.append("Population candidate-attempt limit reached; some requested policy jobs remain incomplete.")
            except Exception as exc:
                # Error class only: SDK error bodies may disclose credentials.
                pop["error"] = f"Population read/selection failed ({type(exc).__name__})."
                warnings.append(pop["error"])
                for row in pop_rows:
                    outcome = outcomes[row["source_row"]]
                    if outcome["status"] == "NOT PROCESSED":
                        outcome["status"] = "POPULATION ERROR"
                    if "job_key" in outcome:
                        jobs[outcome["job_key"]]["status"] = "POPULATION ERROR"

        suppressed = _suppressed(rows, outcomes, settings["quarter_precedence"])
        results = []
        # One file per (deal/policy job, destination folder): duplicate rows for
        # the same client (or every row in the flat layout) reuse the saved copy.
        placed = {}
        for row in rows:
            outcome = outcomes[row["source_row"]]
            job = jobs.get(outcome.get("job_key"), {})
            status = job.get("status", outcome["status"])
            pop = next(p for p in populations if p["population"] == row["population"])
            for quarter in row["quarters"] or [""]:
                target, row_status = "", status
                if (row["source_row"], quarter) in suppressed:
                    row_status = f"SUPPRESSED: only the {settings['quarter_precedence'].lower()} quarter of the year is kept"
                elif job.get("file"):
                    try:
                        directory = directories[(row["source_row"], quarter)]
                        place_key = (outcome.get("job_key"), str(directory).casefold())
                        if place_key in placed:
                            target = placed[place_key]
                        else:
                            target = _copy(output, directory, Path(job["file"]), row, quarter, outcome["policy"], job)
                            pop["memo_copies_written"] += 1
                            job["copied_files"].append(target)
                            placed[place_key] = target
                        if not job["successful_attempt"]["File"]:
                            job["successful_attempt"]["File"] = target
                    except Exception as exc:
                        row_status = f"COPY FAILED ({type(exc).__name__})"
                        pop["source_warnings"].append(f"Source row {row['source_row']}: destination copy failed ({type(exc).__name__}).")
                intended = job.get("intended", {})
                selected = intended if preview else job
                results.append({
                    "Source Row": row["source_row"], "Deal": row["deal_name"], "Population": row["population"],
                    "Client": row["client"], "Quarter": quarter, "Policy": outcome["policy"], "Status": row_status,
                    "Parent ID": outcome["parent_id"], "Memo Stage": selected.get("stage", ""), "IC Date": selected.get("date", ""),
                    "Audience": selected.get("audience", ""), "File": target, "Eligible Candidates": len(job.get("choices", [])),
                    "Candidates Tried": job.get("tried", 0), "Remaining Candidates": max(0, len(job.get("choices", [])) - job.get("tried", 0)),
                    "Event ID": selected.get("event_id", ""), "Attachment ID": selected.get("attachment_id", ""),
                    "Intended Event ID": intended.get("event_id", ""), "Intended Attachment ID": intended.get("attachment_id", ""),
                    "Detail": "Preview selection is an intention only; metadata, strict filenames and downloads are not verified." if preview else "",
                })
        good = lambda status: status.startswith(("DOWNLOADED", "PREVIEW: candidates found", "SUPPRESSED:"))
        for pop in populations:
            relevant = [r for r in results if r["Population"] == pop["population"]]
            pop["downloaded"] = sum(bool(j["copied_files"]) for key, j in jobs.items() if key[0] == pop["population"])
            pop["incomplete_requests"] = sum(not good(r["Status"]) for r in relevant)
            pop["source_warnings"] = list(dict.fromkeys(pop["source_warnings"]))
            if pop["source_warnings"] or pop["incomplete_requests"]:
                pop["status"] = "partial"
        summary = {
            "preview": preview, "source_rows": len(rows), "unique_requested_names": sum(len(n) for n in requested.values()),
            "unique_policy_jobs": len(jobs), "client_quarter_requests": len(results), "suppressed_requests": len(suppressed),
            "eligible_candidates": sum(p["eligible_candidates"] for p in populations),
            "attempted_candidates": len(attempts), "max_attempts": settings["max_attempts"], "attempt_limit_scope": "per population",
            "candidate_limit_reached": any(p["candidate_limit_reached"] for p in populations),
            "unique_memos_downloaded": sum(p["downloaded"] for p in populations),
            "memos_fetched": sum(p["memos_fetched"] for p in populations),
            "memo_copies_written": sum(p["memo_copies_written"] for p in populations),
            "incomplete_requests": sum(p["incomplete_requests"] for p in populations),
            "status_counts": dict(Counter(r["Status"] for r in results)),
            "matching": "Exact case-insensitive whitespace-normalized names within mapped population; no guessed IDs or fuzzy matching.",
            "date_filter": None, "approval_recommendation_filters": None,
            "preview_note": "Eligible counts and intended candidates only; no metadata, binary-field discovery or file downloads. Not a download guarantee." if preview else "",
            "quarter_policy": {"Keep all": "A copy is saved in every quarter listed.",
                               "Earliest": "Only the earliest listed quarter (Q1-Q4) is kept per client, deal, policy and year.",
                               "Latest": "Only the latest listed quarter (Q1-Q4) is kept per client, deal, policy and year."}[settings["quarter_precedence"]],
        }
        result = {"status": "partial" if any(p["status"] == "partial" for p in populations) else "completed",
                  "output": ".", "population_results": populations, "excel_summary": summary}
        if settings["output_layout"] == "grouped":
            summary["client_folders"] = len({exact_name(r["client"]) for r in rows})
            summary["output_layout"] = ("One folder per client, with Year and Quarter subfolders when given (Client/2026/Q3). "
                                        "Each deal/policy memo is downloaded once and copied into every client folder that requested it; "
                                        "duplicate rows for the same client folder reuse one copy.")
        if settings["output_layout"] == "flat":
            summary["request_rows"] = summary.pop("client_quarter_requests")
            summary.pop("quarter_policy", None)
            summary["output_layout"] = "Flat batch folder; no client, quarter or IC-date grouping. Duplicate deal/policy rows reference the same saved file."
        result_columns = [c for c in RESULT_COLUMNS if c not in {"Client", "Quarter"}] if settings["output_layout"] == "flat" else RESULT_COLUMNS
        _write_csv(reports / "excel_results.csv", results, result_columns)
        _write_csv(reports / "downloaded_files.csv", [r for r in results if r["File"]], result_columns)
        _write_csv(reports / "candidate_attempts.csv", attempts, ATTEMPT_COLUMNS)
        manifest = {"mode": "Excel list", "settings": settings, "preview_only": preview, **result}
        (reports / "excel_issues.json").write_text(json.dumps([{'population': p['population'], 'source_warnings': p['source_warnings'], 'error': p.get('error')} for p in populations], indent=2), encoding='utf-8')
        (reports / "run_settings.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
