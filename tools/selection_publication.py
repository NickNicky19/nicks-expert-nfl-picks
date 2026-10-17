"""Bounded public projection of saved statistical grading; no provider requests.

The existing updater invokes this only after its required capture checks. It is
not a deployment command. Rich private reports stay in a disposable external
directory; only an explicit field contract and safe frozen decisions survive.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile

from evidence import read, write
from reliability import ENGINE_PATHS, IntegrityError, canonical, digest, engine_hashes, load_json, stamp, utc
from scorecard import identity
from selection_report import (PATTERNS, RESULTS, _create_file, _tally, build_decisions, run_report, summarize, weekday)

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_VERSION = "selection-public-report-v1"
POINTER_VERSION = "selection-publication-pointer-v1"
ROWS_VERSION = "selection-public-rows-v1"
OUTCOMES_VERSION = "selection-final-outcomes-v1"
CHUNK_SIZE = 250
HEX = re.compile(r"[0-9a-f]{64}\Z")
SOURCE_HEX = re.compile(r"[0-9a-f]{40}\Z")
PRIVATE_TEXT = re.compile(r"(?:https?://|file://|/workspace/|/tmp/|[A-Za-z]:\\|\bBearer\s|\bgh[pousr]_|\bgithub_pat_)", re.I)
PRIVATE_KEYS = re.compile(r"(?:authorization|cookie|password|credential|token|secret|api[_-]?key)", re.I)

# These are the exact decision fields needed to preserve the accepted immutable
# ledger. Unknown extensions are refused rather than persisted indiscriminately.
DECISION_FIELDS = frozenset("""
season week game_id player_id category team name raw_projection adjusted_projection line line_from
schema_version provenance_class model_version engine_sha256 engine_files policy_version policy_sha256
cohort checkpoint checkpoint_at kickoff observation_saved_kickoff schedule_conflict action reason side
top_over top_under top_at_decision recorded_selection_at original_selection_created_at selection_clock_basis
forecast_generated_at collected_at selection_weekday kickoff_weekday seconds_to_kickoff lead_time_bucket
observation_age_seconds observation_receipt_sha256 observation_receipt_refs observation_row_sha256
policy_application_mode source_coverage provider_quote_clock period full_contract_verification settlement_status
decision_key decision_sha256 archive_payload_sha256 archive_saved_at archive_receipt_refs archive_saved_at_clocks
frozen_decision_sha256
""".split())
ROW_FIELDS = DECISION_FIELDS - {"engine_files"} | frozenset("""
result outcome_reason actual outcome_snapshot_sha256 outcome_observations outcome_collected_at
week_confirmed_complete outcome_provenance selected_outcome_provenance_sha256 outcome_source_mix outcome_conflict
outcome_identity_status outcome_identity_reasons outcome_selection outcome_revision
selected_outcome_snapshot_sha256 selected_outcome_row_sha256 outcome_active_observations
""".split())
OUTCOME_FIELDS = frozenset("""
season week game_id player_id category team kickoff status actual reason game_state final_confirmed
outcome_conflict outcome_selection outcome_source_mix outcome_identity_status outcome_identity_reasons
collected_at outcome_collected_at outcome_snapshot_sha256 outcome_row_sha256
selected_outcome_snapshot_sha256 selected_outcome_row_sha256 selected_outcome_provenance_sha256
outcome_provenance source_class outcome_revision revision observation_count
""".split())
TABLE_FIELDS = frozenset("""
provenance_class model_version engine_sha256 view checkpoint period dimension value summary_id row_ids
rows selected hit_rate unique_players unique_games unique_weeks selected_unique_players selected_unique_games
decided_unique_players decided_unique_games decided_unique_weeks decided
""".split()) | frozenset(RESULTS)
COVERAGE_FIELDS = frozenset("""
valid_snapshot_instants unique_observed_opportunities receipt_exclusions unobserved_checkpoint_opportunities
schedule_conflicts universe_scope original_archive_count weeks_with_decided_selections
independently_qualified_completed_weeks
""".split())
METRIC_FIELDS = frozenset(("n", "mae", "rmse", "mean_error"))
HASH_LIST_FIELDS = frozenset(("observation_receipt_refs", "archive_receipt_refs", "outcome_observations",
                              "outcome_active_observations"))
TEXT_LIST_FIELDS = frozenset(("archive_saved_at_clocks", "outcome_identity_reasons"))


def _safe_value(value):
    """Primitive JSON only, with bounded strings; no metadata pass-through."""
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        canonical(value)  # Reject NaN and infinities.
        return value
    if isinstance(value, str):
        if len(value) > 400 or any(ord(c) < 32 for c in value) or PRIVATE_TEXT.search(value):
            raise IntegrityError("Nonpublic or malformed publication string")
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) or PRIVATE_KEYS.search(key) for key in value):
            raise IntegrityError("Nonpublic metadata key")
        return {_safe_value(key): _safe_value(item) for key, item in value.items()}
    raise IntegrityError("Unsupported publication value")


def _project(value, fields):
    if not isinstance(value, dict):
        raise IntegrityError("Malformed public record")
    return {key: _safe_value(value[key]) for key in sorted(fields & value.keys())}


def _hash(value, *, optional=False):
    if value is None and optional:
        return
    if not isinstance(value, str) or HEX.fullmatch(value) is None:
        raise IntegrityError("Malformed public evidence digest")


def _record_identity(row):
    if (type(row.get("season")) is not int or not 2000 <= row["season"] <= 2200
            or type(row.get("week")) is not int or not 1 <= row["week"] <= 18):
        raise IntegrityError("Malformed public season/week")
    for key in ("game_id", "player_id", "category", "team"):
        if not isinstance(row.get(key), str) or not row[key] or len(row[key]) > 120:
            raise IntegrityError("Missing public opportunity identity")
    if row.get("kickoff") is None:
        if row.get("action") != "EXCLUDED":
            raise IntegrityError("Missing saved kickoff")
    else:
        utc(row["kickoff"])


def _record_fields(record):
    for key, value in record.items():
        if value is None:
            continue
        if key in HASH_LIST_FIELDS:
            if not isinstance(value, list):
                raise IntegrityError("Malformed evidence-reference list")
            for reference in value:
                _hash(reference)
        elif key in TEXT_LIST_FIELDS:
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise IntegrityError("Malformed public reason/clock list")
        elif key == "engine_files":
            if not isinstance(value, dict) or set(value) - set(ENGINE_PATHS):
                raise IntegrityError("Unrecognized engine hash mapping")
            for reference in value.values():
                _hash(reference)
        elif isinstance(value, (dict, list)):
            raise IntegrityError("Nested metadata outside public record contract")
        elif key.endswith("sha256"):
            _hash(value)


def _row(row):
    result = _project(row, ROW_FIELDS)
    _record_identity(result)
    _record_fields(result)
    _hash(result.get("decision_sha256"))
    if result.get("result") not in RESULTS or result.get("action") not in ("SELECT", "NO_ACTION", "NOT_DUE", "EXCLUDED"):
        raise IntegrityError("Malformed public decision status")
    if type(result.get("outcome_conflict")) is not bool:
        raise IntegrityError("Missing public outcome conflict flag")
    if result["result"] in ("win", "loss", "push"):
        if isinstance(result.get("actual"), bool) or not isinstance(result.get("actual"), (int, float)):
            raise IntegrityError("Decided public row lacks a statistic")
    return result


def _outcome(row):
    result = _project(row, OUTCOME_FIELDS)
    _record_identity(result)
    _record_fields(result)
    if type(result.get("final_confirmed")) is not bool or type(result.get("outcome_conflict")) is not bool:
        raise IntegrityError("Missing public final/conflict flags")
    if result.get("status") == "void":
        result.update(status="unresolved", actual=None, reason="venue_void_settlement_not_supported")
    if result.get("status") not in ("resolved", "dnp", "pending", "unresolved", "void"):
        raise IntegrityError("Malformed public outcome status")
    if result["status"] in ("resolved", "dnp"):
        if (result.get("final_confirmed") is not True or result.get("outcome_conflict") is not False
                or result.get("game_state") != "post" or result.get("outcome_selection") != "confirmed"
                or result.get("outcome_source_mix") == "conflicting_sources"
                or result.get("outcome_identity_status") == "quarantined"):
            raise IntegrityError("Public final outcome lacks confirmed evidence")
        if not result.get("collected_at") or utc(result["kickoff"]) >= utc(result["collected_at"]):
            raise IntegrityError("Final outcome was not observed after kickoff")
        for key in ("outcome_snapshot_sha256", "selected_outcome_row_sha256", "selected_outcome_provenance_sha256"):
            _hash(result.get(key))
    if result["status"] == "resolved":
        if isinstance(result.get("actual"), bool) or not isinstance(result.get("actual"), (int, float)):
            raise IntegrityError("Resolved public outcome lacks a statistic")
    elif result.get("actual") is not None:
        raise IntegrityError("Undecided public outcome carries a statistic")
    # Do not add a source body or unrestricted selected-provenance object here.
    return result


def _primary(report):
    return {"schema_version": report.get("schema_version"),
            "policy_version": report.get("policy_version"),
            "categories": {category: {
                model: _project(values.get(model, {}), METRIC_FIELDS)
                for model in ("raw_sleeper", "unchanged_clone")}
                for category, values in report.get("categories", {}).items()},
            "outcome_status": _safe_value(report.get("outcome_status", {}))}


def _coverage(coverage):
    value = _project(coverage, COVERAGE_FIELDS)
    for key in ("unobserved_checkpoint_opportunities", "schedule_conflicts"):
        value[key] = len(coverage.get(key, []))
    exclusions = value.get("receipt_exclusions", {})
    if not isinstance(exclusions, dict) or any(type(count) is not int or count < 0 for count in exclusions.values()):
        raise IntegrityError("Invalid public coverage counts")
    for week in value.get("independently_qualified_completed_weeks", []):
        if not isinstance(week, (list, tuple)) or len(week) != 2 or any(type(n) is not int for n in week):
            raise IntegrityError("Invalid completed-week coverage")
    source_statuses = Counter()
    for observation in coverage.get("source_observations", []):
        status = observation.get("source_status")
        source_statuses[status if status in ("available", "unavailable", "missing_information") else "unknown"] += 1
    value["offer_source_observation_status_counts"] = dict(source_statuses)
    value["offer_source_observation_scope"] = "THREE_TARGET_REQUEST_OBSERVATIONS_UNBOUND_TO_TEN_CATEGORY_DECISIONS"
    return value


def _projection(report, *, source_sha, input_digest):
    if report.get("schema_version") != "selection-report-v2":
        raise IntegrityError("Unsupported source selection report")
    # Physical locality only; recommendation membership and ranking stay recorded.
    rows = sorted((_row(row) for row in report["rows"]), key=lambda row: (
        row["provenance_class"], row["model_version"], row.get("engine_sha256") or "",
        row["season"], row["week"], row["cohort"], row["checkpoint"],
        row["category"], row.get("side") or "", row["decision_sha256"]))
    row_ids = [row["decision_sha256"] for row in rows]
    if len(set(row_ids)) != len(row_ids):
        raise IntegrityError("Duplicate public decision identity")
    chunks = [rows[index:index + CHUNK_SIZE] for index in range(0, len(rows), CHUNK_SIZE)]
    positions = {row["decision_sha256"]: index for index, row in enumerate(rows)}
    tables = []
    by_id = {row["decision_sha256"]: row for row in rows}
    expected_tables = {table["summary_id"]: table for table in summarize(report["rows"])["tables"]}
    if len(expected_tables) != len(report["summary"]["tables"]):
        raise IntegrityError("Source report summary groups do not reconcile")
    for original in report["summary"]["tables"]:
        if expected_tables.get(original.get("summary_id")) != original:
            raise IntegrityError("Source report group identity/membership does not reconcile")
        table = _project(original, TABLE_FIELDS)
        _hash(table.get("summary_id"))
        refs = table.get("row_ids", [])
        if len(refs) != len(set(refs)) or any(ref not in positions for ref in refs):
            raise IntegrityError("Public summary references missing/duplicate rows")
        table["row_positions"] = sorted(positions[ref] for ref in refs)
        table["row_ids_sha256"] = digest([rows[position]["decision_sha256"] for position in table["row_positions"]])
        table.pop("row_ids")
        table["row_chunks"] = sorted({positions[ref] // CHUNK_SIZE for ref in refs})
        table["coverage_reason_counts"] = dict(Counter(by_id[ref]["reason"] for ref in refs
                                                     if by_id[ref]["action"] == "NO_ACTION"))
        tables.append(table)
    unknown_kickoffs = [row for row in report.get("final_outcomes", [])
                        if row.get("kickoff") is None and row.get("status") in ("pending", "unresolved")]
    outcomes = sorted((_outcome(row) for row in report.get("final_outcomes", []) if row not in unknown_kickoffs),
                      key=lambda row: identity(row))
    if len({identity(row) for row in outcomes}) != len(outcomes):
        raise IntegrityError("Duplicate public outcome identity")
    summary = {"schema_version": PUBLIC_VERSION, "report_schema_version": report["schema_version"],
               "row_count": len(rows), "source_sha": source_sha,
               "input_binding": "NOT_YET_GIT_COMMITTED", "input_content_sha256": input_digest,
               "summary": {"tables": tables,
                           "disjoint_selected_partitions_reconciled": report["summary"]["disjoint_selected_partitions_reconciled"],
                           "warning": _safe_value(report["summary"]["warning"])},
               "coverage": _coverage(report["coverage"]),
               "primary_raw_vs_adjusted": _primary(report.get("primary_raw_vs_adjusted", {})),
               "uncertainty": {"status": "DESCRIPTIVE_ONLY", "interval": None,
                               "minimum_completed_weeks": report.get("uncertainty", {}).get("minimum_completed_weeks", 8)},
               "limitations": ["Statistical grading, not verified venue settlement or ROI.",
                               "Saved-cache regrades, inherited history and original pregame observations are separate.",
                               "Original Week 6 matchup proof is missing; not reconstructed.",
                               "Original captured-population evidence review remains pending and restricted.",
                               "Quote freshness, full contracts and the entirely unobserved opportunity universe are unverified.",
                               "Local recorded membership time does not prove website publication or original selection creation."]}
    summary["coverage"]["outcome_index_omitted_unknown_kickoff"] = len(unknown_kickoffs)
    public_id = digest({"summary": summary, "rows": rows, "outcomes": outcomes})
    return summary, rows, outcomes, chunks, public_id


def validate_publication(base, pointer):
    """Read the exact written assets before advancing a mutable latest pointer."""
    base = Path(base)
    if set(pointer) != {"schema_version", "report_id", "generated_at", "row_count", "summary", "rows", "outcomes"}:
        raise IntegrityError("Unknown public pointer fields")
    if pointer["schema_version"] != POINTER_VERSION:
        raise IntegrityError("Unknown public pointer version")
    _hash(pointer["report_id"])
    utc(pointer["generated_at"])
    report_id = pointer["report_id"]

    def asset(descriptor, name):
        if set(descriptor) != ({"path", "sha256", "count"} if name.startswith("rows-") else {"path", "sha256"}):
            raise IntegrityError("Unknown public asset fields")
        if descriptor["path"] != report_id + "/" + name:
            raise IntegrityError("Unsafe public asset path")
        _hash(descriptor["sha256"])
        path = base / descriptor["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
            raise IntegrityError("Public asset escaped its root")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
            raise IntegrityError("Public asset byte checksum mismatch")
        return load_json(path)

    summary = asset(pointer["summary"], "summary.json")
    expected_summary_fields = {"schema_version", "report_schema_version", "report_id", "row_count", "source_sha",
                               "input_binding", "input_content_sha256", "summary", "coverage",
                               "primary_raw_vs_adjusted", "uncertainty", "limitations"}
    if set(summary) != expected_summary_fields:
        raise IntegrityError("Unknown public summary fields")
    if summary.get("schema_version") != PUBLIC_VERSION or summary.get("report_id") != report_id:
        raise IntegrityError("Malformed public summary identity")
    if summary.get("report_schema_version") != "selection-report-v2" or summary.get("input_binding") != "NOT_YET_GIT_COMMITTED":
        raise IntegrityError("Unsupported public source/binding contract")
    if SOURCE_HEX.fullmatch(summary.get("source_sha", "")) is None:
        raise IntegrityError("Malformed public source commit")
    _hash(summary.get("input_content_sha256"))
    if type(pointer["row_count"]) is not int or pointer["row_count"] < 0 or type(summary["row_count"]) is not int:
        raise IntegrityError("Malformed public row count")
    if set(summary["summary"]) != {"tables", "warning", "disjoint_selected_partitions_reconciled"}:
        raise IntegrityError("Unknown public summary-group fields")
    rows = []
    locations = {}
    if not isinstance(pointer["rows"], list) or len(pointer["rows"]) != (pointer["row_count"] + CHUNK_SIZE - 1) // CHUNK_SIZE:
        raise IntegrityError("Public row-chunk count does not reconcile")
    for index, descriptor in enumerate(pointer["rows"]):
        payload = asset(descriptor, f"rows-{index:04d}.json")
        if set(payload) != {"schema_version", "report_id", "rows"} or payload["schema_version"] != ROWS_VERSION or payload["report_id"] != report_id:
            raise IntegrityError("Malformed public row chunk")
        if (type(descriptor["count"]) is not int or len(payload["rows"]) != descriptor["count"]
                or not 0 < len(payload["rows"]) <= CHUNK_SIZE
                or index < len(pointer["rows"]) - 1 and len(payload["rows"]) != CHUNK_SIZE):
            raise IntegrityError("Invalid public row chunk size")
        for row in payload["rows"]:
            if _row(row) != row:
                raise IntegrityError("Nonpublic field in row chunk")
            if row["decision_sha256"] in locations:
                raise IntegrityError("Duplicate public row identity")
            locations[row["decision_sha256"]] = len(rows)
            rows.append(row)
            for key in ("forecast_generated_at", "collected_at", "recorded_selection_at", "outcome_collected_at"):
                if row.get(key) and utc(row[key]) > utc(pointer["generated_at"]):
                    raise IntegrityError("Public row clock is after report generation")
    if len(rows) != pointer["row_count"] or len(rows) != summary["row_count"]:
        raise IntegrityError("Public row count does not reconcile")
    by_id = {row["decision_sha256"]: row for row in rows}
    expected_tables = {table["summary_id"]: table for table in summarize(rows)["tables"]}
    if len(expected_tables) != len(summary["summary"]["tables"]):
        raise IntegrityError("Public summary groups do not reconcile")
    for table in summary["summary"]["tables"]:
        if set(table) - (TABLE_FIELDS - {"row_ids"}) - {"row_chunks", "coverage_reason_counts", "row_positions", "row_ids_sha256"}:
            raise IntegrityError("Nonpublic field in summary")
        positions = table["row_positions"]
        if any(type(position) is not int or not 0 <= position < len(rows) for position in positions):
            raise IntegrityError("Invalid public summary row positions")
        if positions != sorted(set(positions)):
            raise IntegrityError("Public summary positions are not unique and ordered")
        refs = [rows[position]["decision_sha256"] for position in positions]
        if table["row_ids_sha256"] != digest(refs):
            raise IntegrityError("Public summary row-ID digest does not reconcile")
        if len(refs) != len(set(refs)) or any(ref not in by_id for ref in refs):
            raise IntegrityError("Invalid public summary row references")
        members = [by_id[ref] for ref in refs]
        expected = _tally(members)
        if any(table.get(key) != value for key, value in expected.items() if key != "row_ids"):
            raise IntegrityError("Public summary population/sample context does not reconcile")
        if table["summary_id"] != digest({key: value for key, value in table.items()
                                          if key not in ("row_ids", "row_positions", "row_ids_sha256", "row_chunks", "coverage_reason_counts", "summary_id")}):
            raise IntegrityError("Public summary content identity mismatch")
        group = expected_tables.get(table["summary_id"])
        if group is None or any(table.get(key) != value for key, value in group.items() if key != "row_ids") or set(group["row_ids"]) != set(refs):
            raise IntegrityError("Public group identity/membership does not reconcile")
        reasons = dict(Counter(row["reason"] for row in members if row["action"] == "NO_ACTION"))
        if table.get("coverage_reason_counts") != reasons:
            raise IntegrityError("Public abstention/coverage reasons do not reconcile")
        counts = Counter(row["result"] for row in members)
        if any(table[result] != counts[result] for result in RESULTS) or table["rows"] != len(refs):
            raise IntegrityError("Public summary outcomes do not reconcile")
        decided = counts["win"] + counts["loss"]
        if table["hit_rate"] != (counts["win"] / decided if decided else None):
            raise IntegrityError("Public hit-rate denominator does not reconcile")
        if table["selected"] != sum(row["action"] == "SELECT" for row in members):
            raise IntegrityError("Public selected population does not reconcile")
        if table["row_chunks"] != sorted({locations[ref] // CHUNK_SIZE for ref in refs}):
            raise IntegrityError("Public summary chunk mapping does not reconcile")
    final = asset(pointer["outcomes"], "outcomes.json")
    if set(final) != {"schema_version", "report_id", "outcomes"} or final["schema_version"] != OUTCOMES_VERSION or final["report_id"] != report_id:
        raise IntegrityError("Malformed public final-outcome index")
    if any(_outcome(row) != row for row in final["outcomes"]):
        raise IntegrityError("Nonpublic field in final-outcome index")
    if any(not row.get("collected_at") or utc(row["collected_at"]) > utc(pointer["generated_at"])
           for row in final["outcomes"]):
        raise IntegrityError("Public outcome collection is after report generation")
    if len({identity(row) for row in final["outcomes"]}) != len(final["outcomes"]):
        raise IntegrityError("Duplicate final-outcome identity")
    core = {key: value for key, value in summary.items() if key != "report_id"}
    if digest({"summary": core, "rows": rows, "outcomes": final["outcomes"]}) != report_id:
        raise IntegrityError("Public content identity mismatch")
    _safe_value(summary)
    return summary


def _source_sha(root, source_sha):
    if source_sha is None:
        git_root = root if (root / ".git").exists() else ROOT
        source_sha = subprocess.check_output(["git", "-C", str(git_root), "rev-parse", "HEAD"], text=True).strip()
    if not isinstance(source_sha, str) or SOURCE_HEX.fullmatch(source_sha) is None:
        raise IntegrityError("Exact source commit required for public report")
    return source_sha


def all_ten_outcome_identities(root, observed_at, *, coverage=None):
    """Validated recorded opportunities, independent of lean/Top qualification."""
    root = Path(root)
    policy = load_json(root / "config/timing-policy.json")
    receipts = [read(path) for path in sorted((root / "data/forward").rglob("*.json.gz"))]
    decisions, _ = build_decisions(receipts, policy, observed_at, engine_hashes(root))
    groups, result, excluded = defaultdict(list), {}, Counter()
    for decision in decisions:
        groups[identity(decision)].append(decision)
    for key, members in groups.items():
        # Explicitly unbound/excluded identities must not prevent independent
        # valid observations. Their original decision rows remain in reports.
        if any(row.get("kickoff") is None for row in members):
            excluded["ambiguous_saved_kickoff"] += 1
            continue
        if any(not isinstance(row.get("team"), str) or not row["team"].strip() for row in members):
            excluded["unknown_recorded_team"] += 1
            continue
        if len({row["team"] for row in members}) != 1 or len({utc(row["kickoff"]) for row in members}) != 1:
            excluded["conflicting_recorded_team_or_kickoff"] += 1
            continue
        bound = [row for row in members if HEX.fullmatch(row.get("observation_receipt_sha256") or "")
                 and HEX.fullmatch(row.get("observation_row_sha256") or "")]
        if not bound:
            excluded["no_bound_original_observation"] += 1
            continue
        result[key] = bound[0]
    if coverage is not None:
        coverage.update(unique_recorded_identities=len(groups), eligible_snapshot_identities=len(result),
                        excluded_unbound_identities=dict(excluded))
    return result


def _ledger(payload, policy, hashes, observed_at):
    if set(payload) != {"schema_version", "season", "week", "derived_at", "rows"} or payload["schema_version"] != "derived-selection-ledger-v1":
        raise IntegrityError("Unknown persisted public decision envelope")
    if type(payload["season"]) is not int or type(payload["week"]) is not int:
        raise IntegrityError("Invalid frozen envelope period")
    if utc(payload["derived_at"]) > observed_at:
        raise IntegrityError("Frozen decision envelope is from the future")
    rules = {rule["id"]: rule for rule in policy["checkpoints"]}
    for row in payload["rows"]:
        if set(row) - DECISION_FIELDS:
            raise IntegrityError("Nonpublic field in persistent decision ledger")
        _safe_value(row)
        _record_identity(row)
        _record_fields(row)
        if row.get("checkpoint") == "history":
            raise IntegrityError("Historical derivations are not frozen checkpoint state")
        if (row.get("schema_version") != "selection-decision-v1"
                or row.get("policy_version") != policy["version"]
                or row.get("policy_sha256") != digest(policy)
                or row.get("model_version") != policy["model"]
                or row.get("engine_files") != hashes or row.get("engine_sha256") != digest(hashes)
                or row.get("provenance_class") != "local_pregame_membership_observation"
                or row.get("category") not in policy["categories"]
                or (row.get("season"), row.get("week")) != (payload["season"], payload["week"])
                or row.get("checkpoint") not in rules or row.get("cohort") not in policy["cohorts"]
                or row.get("action") not in ("SELECT", "NO_ACTION")
                or row.get("policy_application_mode") != "OFFLINE_DERIVED_FROM_ORIGINAL_PREGAME_OBSERVATIONS"
                or row.get("original_selection_created_at") is not None):
            raise IntegrityError("Unrecognized frozen decision contract")
        from datetime import timedelta
        boundary = utc(row["kickoff"]) - timedelta(seconds=rules[row["checkpoint"]]["seconds_before_kickoff"])
        if utc(row["checkpoint_at"]) != boundary or not utc(policy["registered_at"]) < boundary <= observed_at:
            raise IntegrityError("Frozen checkpoint violates registration/observation boundary")
        collected, selected = row.get("collected_at"), row.get("recorded_selection_at")
        if collected:
            clock = utc(collected)
            if not utc(policy["registered_at"]) < clock <= boundary:
                raise IntegrityError("Frozen observation is after its checkpoint or before registration")
            if row.get("observation_age_seconds") != (boundary - clock).total_seconds():
                raise IntegrityError("Frozen observation age does not reconcile")
            generated = row.get("forecast_generated_at")
            if not generated or utc(generated) > clock:
                raise IntegrityError("Frozen forecast clock does not precede collection")
        elif row.get("observation_age_seconds") is not None:
            raise IntegrityError("Unknown observation cannot have a known age")
        if selected:
            if not collected or utc(selected) != utc(collected) or row.get("selection_weekday") != weekday(selected):
                raise IntegrityError("Frozen decision clock/weekday does not reconcile")
            if row.get("seconds_to_kickoff") != (utc(row["kickoff"]) - utc(selected)).total_seconds():
                raise IntegrityError("Frozen lead time does not reconcile")
            if row.get("selection_clock_basis") != "LOCAL_PREGAME_MEMBERSHIP_OBSERVATION":
                raise IntegrityError("Unsupported frozen selection-clock basis")
            if any(type(row.get(flag)) is not bool for flag in ("top_over", "top_under", "top_at_decision")):
                raise IntegrityError("Frozen recorded membership is not boolean")
            for key in ("observation_receipt_sha256", "observation_row_sha256"):
                _hash(row.get(key))
            if row["observation_receipt_sha256"] not in row.get("observation_receipt_refs", []):
                raise IntegrityError("Frozen decision receipt is absent from its references")
            if not row.get("observation_saved_kickoff") or utc(row["observation_saved_kickoff"]) != utc(row["kickoff"]):
                raise IntegrityError("Frozen observation has a different saved kickoff")
            if row["top_at_decision"] != bool(row.get("side") in ("over", "under") and row.get("top_" + row["side"])):
                raise IntegrityError("Frozen recorded Top membership does not reconcile")
        elif row.get("selection_weekday") is not None or row.get("seconds_to_kickoff") is not None:
            raise IntegrityError("Unknown selection clock cannot have a weekday/lead time")
        elif row.get("selection_clock_basis") != "UNKNOWN":
            raise IntegrityError("Unknown frozen selection has an attributed clock")
        elif row.get("top_over") is not None or row.get("top_under") is not None or row.get("top_at_decision") is not False:
            raise IntegrityError("Unknown frozen selection has invented Top membership")
        if row.get("kickoff_weekday") != weekday(row["kickoff"]):
            raise IntegrityError("Frozen kickoff weekday does not reconcile")
        if row["action"] == "SELECT" and (not selected or row["observation_age_seconds"] > policy["maximum_snapshot_age_seconds"]
                                            or row.get("line_from") not in ("dk", "sleeper")
                                            or row.get("side") not in ("over", "under")
                                            or row.get("line") is None):
            raise IntegrityError("Frozen selection lacks an eligible saved observation")
        if (row.get("top_over") and row.get("top_under")
                or row["action"] == "SELECT" and row["cohort"] == "top_picks"
                and row.get("top_" + row["side"]) is not True):
            raise IntegrityError("Frozen Top membership is inconsistent")
        expected_key = digest({key: row[key] for key in ("season", "week", "game_id", "player_id", "category",
                              "model_version", "engine_sha256", "policy_sha256", "cohort", "checkpoint", "kickoff",
                              "provenance_class")})
        if expected_key != row.get("decision_key"):
            raise IntegrityError("Frozen decision key does not match recorded identity")
        _hash(row.get("decision_sha256"))
        if digest({key: value for key, value in row.items() if key != "decision_sha256"}) != row["decision_sha256"]:
            raise IntegrityError("Persistent decision identity mismatch")
    return payload


def _no_symlinks(path, root):
    path, root = Path(path), Path(root)
    if not path.is_relative_to(root):
        raise IntegrityError("Publication path outside authorized root")
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise IntegrityError("Symlink in publication/state path")


def _state_write(root, lane, payload):
    target = root / "data" / lane / str(payload["season"]) / f"w{payload['week']:02d}" / (digest(payload) + ".json.gz")
    _no_symlinks(target, root)
    return write(root, lane, payload)


def publish_selection_report(root, observed_at=None, *, source_sha=None):
    """Prepare assets for the existing updater, never commit/upload/deploy them."""
    root = Path(root).resolve()
    observed_at = utc(observed_at or datetime.now(timezone.utc))
    source_sha = _source_sha(root, source_sha)
    policy, hashes = load_json(root / "config/timing-policy.json"), engine_hashes(root)
    originals = {}
    with tempfile.TemporaryDirectory(prefix="nfl-selection-publication-") as temporary:
        stage, analysis = Path(temporary) / "saved-inputs", Path(temporary) / "private-analysis"
        stage.mkdir()
        # No .git or separate population/raw-capture lanes. Changed generated
        # files are bound to these exact bytes, never falsely asserted at HEAD.
        for pattern in PATTERNS:
            for path in sorted(root.glob(pattern)):
                name = path.relative_to(root).as_posix()
                if name in originals:
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise IntegrityError("Saved input escaped the authorized root")
                raw = path.read_bytes()
                originals[name] = hashlib.sha256(raw).hexdigest()
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        input_digest = digest(originals)
        state = root / "data/verification/selection-grading/decisions"
        _no_symlinks(state, root)
        for path in sorted(state.rglob("*.json.gz")):
            if path.is_symlink():
                raise IntegrityError("Unsafe persistent decision path")
            _no_symlinks(path, root)
            payload = _ledger(read(path), policy, hashes, observed_at)
            write(analysis, "selection_decisions", payload)
        report, _ = run_report([stage], analysis, now=observed_at,
                              policy=policy, expected_hashes=hashes)
        summary, rows, outcomes, chunks, public_id = _projection(report, source_sha=source_sha,
                                                               input_digest=input_digest)
        base = root / "output/data/selection-grading"
        directory = base / public_id
        _no_symlinks(directory, root)
        _no_symlinks(base / "latest.json", root)

        def save(name, payload):
            raw = canonical(payload) + b"\n"
            _create_file(directory / name, raw)
            return {"path": public_id + "/" + name, "sha256": hashlib.sha256(raw).hexdigest()}

        descriptors = []
        for index, chunk in enumerate(chunks):
            descriptor = save(f"rows-{index:04d}.json", {"schema_version": ROWS_VERSION,
                                                       "report_id": public_id, "rows": chunk})
            descriptors.append(dict(descriptor, count=len(chunk)))
        pointer = {"schema_version": POINTER_VERSION, "report_id": public_id,
                   "generated_at": stamp(observed_at), "row_count": len(rows),
                   "summary": save("summary.json", dict(summary, report_id=public_id)),
                   "rows": descriptors,
                   "outcomes": save("outcomes.json", {"schema_version": OUTCOMES_VERSION,
                                                       "report_id": public_id, "outcomes": outcomes})}
        validate_publication(base, pointer)
        # Recheck every source byte before publishing either persistent state or
        # latest. Failure may leave unreachable content-addressed assets only.
        if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != sha for name, sha in originals.items()):
            raise IntegrityError("Saved input changed during public report")
        for path in sorted((analysis / "data/selection_decisions").rglob("*.json.gz")):
            payload = read(path)
            checkpoint_rows = [row for row in payload["rows"] if row["checkpoint"] != "history"]
            if checkpoint_rows:
                _state_write(root, "verification/selection-grading/decisions",
                             _ledger(dict(payload, rows=checkpoint_rows), policy, hashes, observed_at))
        data = load_json(root / "output/data/week.json")
        _state_write(root, "verification/selection-grading/runs", {
            "schema_version": "selection-publication-run-v1", "season": data["season"], "week": data["week"],
            "generated_at": stamp(observed_at), "source_sha": source_sha,
            "input_content_sha256": input_digest, "public_report_sha256": public_id,
            "input_binding": "NOT_YET_GIT_COMMITTED"})
        from reliability import atomic_json
        atomic_json(base / "latest.json", pointer)
        return pointer
