"""Bounded public projection of saved statistical grading; no provider requests.

The existing updater invokes this only after its required capture checks. It is
not a deployment command. Rich private reports stay in a disposable external
directory; only an explicit field contract and safe frozen decisions survive.
"""
from collections import Counter, defaultdict, OrderedDict
from datetime import datetime, timezone
import hashlib
import copy
import gzip
import io
import json
import sys
import types
import zlib
from pathlib import Path
import re
import subprocess
import tempfile

from evidence import read, write
from reliability import _pairs, ENGINE_PATHS, IntegrityError, canonical, digest, engine_hashes, load_json, stamp, utc
from scorecard import identity
import data_integrity_v2 as corrected
import classic_model_v1 as classic
import accuracy_publication
import selection_strategies
from selection_report import (PATTERNS, RESULTS, _create_file, _tally, build_decisions, run_report, summarize, weekday)

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_VERSION = "selection-public-report-v2"
REPORT_CONTRACTS = {"selection-report-v2": "selection-public-report-v1",
                    "selection-report-v3": PUBLIC_VERSION, "selection-report-v4": "selection-public-report-v6"}
SUMMARY_LIMIT = 12 * 1024 * 1024
ROW_LIMIT = 2 * 1024 * 1024
POINTER_VERSION = "selection-publication-pointer-v1"
ROWS_VERSION = "selection-public-rows-v1"
OUTCOMES_VERSION = "selection-final-outcomes-v1"
CHUNK_SIZE = 250
INDEX_LIMIT = 1024 * 1024
PARTITION_POINTER_VERSION = "selection-publication-pointer-v2"
PARTITION_PUBLIC_VERSION = "selection-public-report-v3"
SUMMARY_PART_VERSION = "selection-public-summary-partition-v1"
OUTCOME_INDEX_VERSION = "selection-final-outcome-index-v1"
OUTCOME_PART_VERSION = "selection-final-outcome-period-v1"
LAYOUT_VERSION = "exact-context-period-and-week-outcomes-v1"
GZIP_POINTER_VERSION = "selection-publication-pointer-v3"
GZIP_PUBLIC_VERSION = "selection-public-report-v4"
GZIP_LAYOUT_VERSION = "gzip-context-period-v1"
SHARED_POINTER_VERSION = "selection-publication-pointer-v4"
SHARED_PUBLIC_VERSION = "selection-public-report-v5"
EXTENDED_PUBLIC_VERSION = "selection-public-report-v6"
SHARED_LAYOUT_VERSION = "shared-payload-context-period-v1"
SHARED_ROWS_VERSION = "selection-public-rows-v2"
SHARED_SUMMARY_VERSION = "selection-public-summary-partition-v2"
SHARED_OUTCOME_VERSION = "selection-final-outcome-period-v2"
SHARED_OUTCOME_INDEX_VERSION = "selection-final-outcome-index-v2"
ENCODED_FIELDS = {"encoding", "encoded_sha256", "encoded_bytes"}
CONTEXT_FIELDS = ("provenance_class", "model_version", "engine_sha256", "policy_version",
                  "policy_sha256", "view", "checkpoint", "line_source_scope")
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
STRATEGY_FIELDS = frozenset(("strategy_version", "strategy_policy_sha256", "strategy_receipt_sha256", "strategy_rank"))
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
TABLE_FIELDS_V2 = TABLE_FIELDS | {"policy_version", "policy_sha256", "line_source_scope"}
COVERAGE_FIELDS = frozenset("""
valid_snapshot_instants unique_observed_opportunities receipt_exclusions unobserved_checkpoint_opportunities
schedule_conflicts universe_scope original_archive_count weeks_with_decided_selections
independently_qualified_completed_weeks
""".split())
METRIC_FIELDS = frozenset(("n", "mae", "rmse", "mean_error"))
HASH_LIST_FIELDS = frozenset(("observation_receipt_refs", "archive_receipt_refs", "outcome_observations",
                              "outcome_active_observations"))
TEXT_LIST_FIELDS = frozenset(("archive_saved_at_clocks", "outcome_identity_reasons"))

# Optional operation-local memo, independent of every public reader/file limit.
PREPARED_LIMIT = 384 * 1024 * 1024
PREPARED_ENTRIES = 8


class _PreparedPublications:
    """Private immutable values only; no qualification survives the operation."""
    def __init__(self):
        self.entries = OrderedDict()
        self.serialized_bytes = self.peak_serialized_bytes = 0
        self.hits = self.misses = self.evictions = 0

    def get(self, key):
        value = self.entries.get(key)
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
            self.entries.move_to_end(key)
        return value

    def put(self, key, value):
        size = sum(map(len, value))
        if key in self.entries:
            self.serialized_bytes -= sum(map(len, self.entries.pop(key)))
        while self.entries and (len(self.entries) >= PREPARED_ENTRIES
                                or self.serialized_bytes + size > PREPARED_LIMIT):
            _, previous = self.entries.popitem(last=False)
            self.serialized_bytes -= sum(map(len, previous))
            self.evictions += 1
        if size <= PREPARED_LIMIT and PREPARED_ENTRIES > 0:
            self.entries[key] = value
            self.serialized_bytes += size
            self.peak_serialized_bytes = max(self.peak_serialized_bytes, self.serialized_bytes)


def _publication_helpers():
    """Fresh installed bytes AND live callable/contract identities, not HEAD/mtime.

    A changed helper also gets a fresh lower decode/semantic memo. Public graph
    reuse must not accidentally borrow an older helper's parsed or semantic PASS.
    """
    parts = []
    # The new registry is an actual helper dependency, not a caller-supplied
    # digest or a filesystem timestamp. Changing it cannot inherit cached trust.
    registry = Path(selection_strategies.__file__).resolve().with_name("selection-strategies-v1.json")
    try:
        parts.append((str(registry), hashlib.sha256(registry.read_bytes()).hexdigest()))
    except OSError:
        return None
    try:
        # Reuse also depends on the actual retained Git bytes and installed
        # strategy policy. A pathname/previous engine digest is not fresh trust.
        parts.append(("strategy-row-context", _strategy_row_context()))
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None  # Unsupported memo closure; complete validation still runs.
    for name in (__name__, "selection_report", "selection_strategies", "accuracy_publication", "scorecard", "reliability", "evidence", "data_integrity_v2", "classic_model_v1", "grade", "scoring"):
        module = sys.modules.get(name)
        try:
            path = Path(module.__file__).resolve()
            checksum = hashlib.sha256()
            with path.open("rb") as handle:
                while block := handle.read(65536):
                    checksum.update(block)
        except (AttributeError, TypeError, OSError):
            # Optional reuse is unavailable; the complete validator still runs
            # with a fresh local memo. Outer source qualification is unchanged.
            return None
        parts.append((name, str(path), checksum.hexdigest()))
        for key, value in sorted(vars(module).items()):
            if isinstance(value, types.FunctionType):
                # Code objects are immutable. Their identity also catches a live
                # __code__ replacement; marshal's interned-string flags are not
                # stable as CPython executes code and must not be a cache key.
                parts.append((name, key, id(value), id(value.__code__),
                              repr(value.__defaults__), repr(value.__kwdefaults__)))
            elif callable(value):
                parts.append((name, key, id(value)))
            elif key.isupper() and isinstance(value, (str, int, tuple, list, set, frozenset, dict, re.Pattern)):
                parts.append((name, key, repr(value)))
    # Imported callables may be replaced by a test/instrumentation wrapper. Their
    # identities are relevant too; do not inspect unstable bound __call__ objects.
    for name in ("_safe_value", "_row", "_outcome", "_record_identity", "_record_fields",
                 "_json_bytes", "_pairs", "canonical", "digest", "identity", "summarize", "_tally",
                 "utc", "load_json", "_validate_legacy_publication", "_read_partitions"):
        value = globals()[name]
        parts.append((name, id(value)))
    return digest(parts)


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
            corrected_engine = (record.get("model_version") in corrected.PRESENCE_MODELS
                                and value == corrected.source_hashes(record["model_version"]))
            classic_engine = record.get("model_version") == classic.MODEL and value == classic.ENGINE
            if not isinstance(value, dict) or set(value) - set(ENGINE_PATHS) and not (corrected_engine or classic_engine):
                raise IntegrityError("Unrecognized engine hash mapping")
            for reference in value.values():
                _hash(reference)
        elif isinstance(value, (dict, list)):
            raise IntegrityError("Nested metadata outside public record contract")
        elif key.endswith("sha256"):
            _hash(value)


def _strategy_row_context():
    """Private immutable values, freshly derived once per bounded row batch."""
    engines = {"original_sleeper_matchup_baseline": digest(corrected.legacy_engine_hashes())}
    engines.update({model: digest(corrected.source_hashes(model)) for model in corrected.PRESENCE_MODELS})
    return engines, digest(selection_strategies.policy())


def _row(row, *, extended=False, _strategy_context=None):
    modern = extended and row.get("schema_version") == "selection-decision-v2"
    if extended and row.get("schema_version") not in ("selection-decision-v1", "selection-decision-v2"):
        raise IntegrityError("Unknown modern decision schema")
    if not modern and (set(row) & STRATEGY_FIELDS or row.get("cohort") in selection_strategies.STRATEGIES):
        raise IntegrityError("Ranked membership requires its typed prospective decision contract")
    if row.get("schema_version") == "selection-decision-v2" and not extended:
        raise IntegrityError("Strategy row outside its explicit enclosing contract")
    result = _project(row, ROW_FIELDS | STRATEGY_FIELDS if modern else ROW_FIELDS)
    if modern:
        engines, strategy_policy = (_strategy_row_context()
            if _strategy_context is None else _strategy_context)
        if (result.get("strategy_version") != "ranked-selection-policy-v1" or result.get("strategy_policy_sha256") != strategy_policy
                or result.get("cohort") not in selection_strategies.STRATEGIES
                or result.get("model_version") not in engines or result.get("engine_sha256") != engines[result["model_version"]]
                or result.get("provenance_class") != "completed_prospective_ranked_selection"
                or result.get("strategy_rank") is not None and (type(result["strategy_rank"]) is not int or not 1 <= result["strategy_rank"] <= 12)
                or result.get("action") == "SELECT" and (result.get("strategy_rank") is None or not result.get("strategy_receipt_sha256"))):
            raise IntegrityError("Unsupported public strategy row")
        if result.get("action") == "SELECT" and (result.get("side") not in ("over", "under") or result.get("line_from") not in ("dk", "sleeper")
                or result.get("selection_clock_basis") != "LOCAL_COMPLETED_RANKED_SELECTION"
                or result.get("recorded_selection_at") != result.get("original_selection_created_at")
                or not result.get("collected_at") or not result.get("original_selection_created_at")
                or not utc(result["forecast_generated_at"]) <= utc(result["collected_at"]) <= utc(result["original_selection_created_at"]) < utc(result["kickoff"])):
            raise IntegrityError("Ranked public selection clocks/offer differ")
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
    contract = report.get("schema_version")
    if contract not in REPORT_CONTRACTS:
        raise IntegrityError("Unsupported source selection report")
    fields = TABLE_FIELDS_V2 if contract != "selection-report-v2" else TABLE_FIELDS
    strategy_context = _strategy_row_context() if contract == "selection-report-v4" else None
    if contract != "selection-report-v2":
        for row in report["rows"]:
            if (row.get("line_from") not in (None, "dk", "sleeper", "ours", "unknown")
                    or not isinstance(row.get("policy_version"), str) or not row["policy_version"].strip()
                    or not HEX.fullmatch(row.get("policy_sha256") or "")):
                raise IntegrityError("Unsupported public-v2 source or policy identity")
    # Physical locality only; recommendation membership and ranking stay recorded.
    rows = sorted((_row(row, extended=contract == "selection-report-v4", _strategy_context=strategy_context) for row in report["rows"]), key=lambda row: (
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
    expected_tables = {table["summary_id"]: table for table in summarize(report["rows"], contract=contract)["tables"]}
    if len(expected_tables) != len(report["summary"]["tables"]):
        raise IntegrityError("Source report summary groups do not reconcile")
    for original in report["summary"]["tables"]:
        if expected_tables.get(original.get("summary_id")) != original:
            raise IntegrityError("Source report group identity/membership does not reconcile")
        table = _project(original, fields)
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
    summary = {"schema_version": REPORT_CONTRACTS[contract], "report_schema_version": contract,
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
    if contract == "selection-report-v4":
        summary["forecast_accuracy"] = copy.deepcopy(accuracy_publication.validate_accuracy(report["forecast_accuracy"]))
        summary["limitations"][3] = "Scoped original-model-input archive review completed; different or later artifacts need delta review."
    public_id = digest({"summary": summary, "rows": rows, "outcomes": outcomes})
    if strategy_context is not None and _strategy_row_context() != strategy_context:
        raise IntegrityError("Ranked row dependencies changed during projection")
    return summary, rows, outcomes, chunks, public_id


def _validate_legacy_publication(base, pointer, *, _partitioned=None, _row_reader=None, _layout=None, _checked=None, _prepared=None):
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
        if _row_reader is not None and name.startswith("rows-"):
            return _row_reader(descriptor, name)
        if set(descriptor) != ({"path", "sha256", "count"} if name.startswith("rows-") else {"path", "sha256"}):
            raise IntegrityError("Unknown public asset fields")
        if descriptor["path"] != report_id + "/" + name:
            raise IntegrityError("Unsafe public asset path")
        _hash(descriptor["sha256"])
        path = base / descriptor["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
            raise IntegrityError("Public asset escaped its root")
        raw = path.read_bytes()
        limit = ROW_LIMIT if name.startswith("rows-") else SUMMARY_LIMIT
        if len(raw) > limit:
            raise IntegrityError("Public asset exceeds the supported reader size limit")
        if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
            raise IntegrityError("Public asset byte checksum mismatch")
        return load_json(path)

    summary = _partitioned[0] if _partitioned is not None else asset(pointer["summary"], "summary.json")
    expected_summary_fields = {"schema_version", "report_schema_version", "report_id", "row_count", "source_sha",
                               "input_binding", "input_content_sha256", "summary", "coverage",
                               "primary_raw_vs_adjusted", "uncertainty", "limitations"}
    if summary.get("report_schema_version") == "selection-report-v4": expected_summary_fields.add("forecast_accuracy")
    if set(summary) != expected_summary_fields:
        raise IntegrityError("Unknown public summary fields")
    contract = summary.get("report_schema_version")
    strategy_context = _strategy_row_context() if contract == "selection-report-v4" else None
    if contract == "selection-report-v4" and (_partitioned is None or _layout != SHARED_LAYOUT_VERSION):
        raise IntegrityError("Extended report requires shared gzip partition validation")
    if (contract not in REPORT_CONTRACTS or summary.get("schema_version") != REPORT_CONTRACTS[contract]
            or summary.get("report_id") != report_id):
        raise IntegrityError("Malformed public summary identity")
    if summary.get("input_binding") != "NOT_YET_GIT_COMMITTED":
        raise IntegrityError("Unsupported public source/binding contract")
    fields = TABLE_FIELDS_V2 if contract != "selection-report-v2" else TABLE_FIELDS
    if contract == "selection-report-v4": accuracy_publication.validate_accuracy(summary["forecast_accuracy"])
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
            if _row(row, extended=contract == "selection-report-v4", _strategy_context=strategy_context) != row:
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
    # Pure semantic work can be shared only after all actual rows/parts were
    # freshly read, hash checked, structurally checked and clock checked above.
    semantic_key = ("summary-semantics", str(base.resolve()), contract,
                    digest({"rows": rows, "tables": summary["summary"]["tables"]}))
    if _checked is None or semantic_key not in _checked:
        expected_tables = {table["summary_id"]: table for table in summarize(rows, contract=contract)["tables"]}
        if len(expected_tables) != len(summary["summary"]["tables"]):
            raise IntegrityError("Public summary groups do not reconcile")
        for table in summary["summary"]["tables"]:
            if contract != "selection-report-v2" and (
                    not isinstance(table.get("policy_version"), str) or not table["policy_version"].strip()
                    or not HEX.fullmatch(table.get("policy_sha256") or "")
                    or table.get("line_source_scope") not in ("all", "dk", "sleeper", "ours", "unknown")
                    or contract == "selection-report-v3" and table["line_source_scope"] != "all" and table["dimension"] not in ("overall", "category", "category_side")):
                raise IntegrityError("Unsupported public-v2 summary context")
            if set(table) - (fields - {"row_ids"}) - {"row_chunks", "coverage_reason_counts", "row_positions", "row_ids_sha256"}:
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
        if _checked is not None:
            _checked[semantic_key] = True
    final = _partitioned[1] if _partitioned is not None else asset(pointer["outcomes"], "outcomes.json")
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
    content = {"summary": core, "rows": rows, "outcomes": final["outcomes"]}
    if _partitioned is not None:
        content["layout"] = _layout or LAYOUT_VERSION
    if digest(content) != report_id:
        raise IntegrityError("Public content identity mismatch")
    _safe_value(summary)
    if strategy_context is not None and _strategy_row_context() != strategy_context:
        raise IntegrityError("Ranked row dependencies changed during complete validation")
    if _prepared is not None:
        _prepared.extend((summary, rows, sorted(final["outcomes"], key=identity)))
    return summary


def _context(table):
    return {key: table.get(key) for key in CONTEXT_FIELDS}


def _table_order(table):
    # Exactly the registered summarizer's order, independent of shard load order.
    return repr((tuple(table.get(key) for key in CONTEXT_FIELDS), table["period"],
                 table["dimension"], table["value"]))


def _json_bytes(raw):
    def invalid(_):
        raise IntegrityError("Nonfinite public JSON")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=invalid)
    except (UnicodeError, ValueError) as exc:
        raise IntegrityError("Malformed public JSON") from exc


def _fresh_stored_bytes(path, descriptor, limit, *, encoded=False):
    """Hash bounded actual bytes even when decode/semantic work is cached."""
    size = descriptor.get("encoded_bytes" if encoded else "decoded_bytes")
    if type(size) is not int or not 0 < size <= limit:
        raise IntegrityError("Public asset exceeds stored size limit")
    if Path(path).is_symlink() or not Path(path).is_file():
        raise IntegrityError("Invalid cached public asset type")
    checksum, total = hashlib.sha256(), 0
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(min(65536, size - total + 1))
            if not block:
                break
            total += len(block)
            if total > size:
                raise IntegrityError("Public asset exceeds stored size limit")
            checksum.update(block)
    expected = descriptor.get("encoded_sha256" if encoded else "sha256")
    if total != size or checksum.hexdigest() != expected:
        raise IntegrityError("Public asset actual bytes changed or corrupt")
    return checksum.hexdigest()


def _read_asset_bytes(path, descriptor, limit, *, encoded=False, _checked=None):
    """Bound on-disk input and expanded output before allocating/parsing them."""
    if _checked is not None:
        actual = _fresh_stored_bytes(path, descriptor, limit, encoded=encoded)
        key = ("decoded-bytes", str(Path(path).resolve()), digest(descriptor), actual, limit, encoded)
        if key not in _checked:
            _checked[key] = _read_asset_bytes(path, descriptor, limit, encoded=encoded)
        return _checked[key]  # immutable bytes; actual stored bytes rehashed above
    size = descriptor.get("decoded_bytes")
    if type(size) is not int or not 0 < size <= limit:
        raise IntegrityError("Public asset exceeds decoded size limit")
    cap = size
    encoded_size = descriptor.get("encoded_bytes") if encoded else size
    if encoded:
        if (descriptor.get("encoding") != "gzip" or type(encoded_size) is not int
                or not 0 < encoded_size <= limit):
            raise IntegrityError("Unsupported encoding or encoded size limit")
        _hash(descriptor.get("encoded_sha256"))
    expected = descriptor["encoded_sha256"] if encoded else descriptor["sha256"]
    parts, count, checksum = [], 0, hashlib.sha256()
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoded else None
    expanded = 0
    try:
        with Path(path).open("rb") as handle:
            while True:
                block = handle.read(min(65536, encoded_size - count + 1))
                if not block:
                    break
                count += len(block)
                if count > encoded_size:
                    raise IntegrityError("Public asset exceeds encoded/declared size limit")
                checksum.update(block)
                if decoder is None:
                    parts.append(block)
                else:
                    data = block
                    while data:
                        result = decoder.decompress(data, cap - expanded + 1)
                        expanded += len(result)
                        if expanded > cap:
                            raise IntegrityError("Public gzip exceeds decoded size limit")
                        parts.append(result)
                        data = decoder.unconsumed_tail
                    if decoder.unused_data:
                        raise IntegrityError("Trailing or concatenated public gzip")
    except zlib.error as exc:
        raise IntegrityError("Corrupt or truncated public gzip") from exc
    if count != encoded_size or checksum.hexdigest() != expected:
        raise IntegrityError("Public asset encoded byte checksum/size mismatch")
    if decoder is not None and not decoder.eof:
        raise IntegrityError("Truncated public gzip")
    raw = b"".join(parts)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
        raise IntegrityError("Public asset decoded byte checksum/size mismatch")
    return raw


def _partition_asset(base, descriptor, filename, *, index=False, report_id=None, encoded=False, row=False, shared=False, _checked=None):
    allowed = {"path", "sha256", "decoded_bytes", "context_id", "period", "table_count", "season", "week", "count"}
    if encoded:
        allowed |= ENCODED_FIELDS
    if not isinstance(descriptor, dict) or set(descriptor) - allowed:
        raise IntegrityError("Unknown partition descriptor fields")
    _hash(descriptor.get("sha256"))
    if encoded and not ENCODED_FIELDS <= set(descriptor):
        raise IntegrityError("Missing explicit gzip descriptor")
    namespace = report_id if index or row and not shared else descriptor["encoded_sha256"] if encoded else descriptor["sha256"]
    if descriptor.get("path") != namespace + "/" + filename:
        raise IntegrityError("Unsafe partition asset path")
    path = Path(base) / descriptor["path"]
    _no_symlinks(path, Path(base))
    if not path.resolve().is_relative_to(Path(base).resolve()):
        raise IntegrityError("Partition asset escaped its root")
    limit = ROW_LIMIT if row else INDEX_LIMIT if index else SUMMARY_LIMIT
    raw = _read_asset_bytes(path, descriptor, limit, encoded=encoded, _checked=_checked)
    key = ("parsed-asset", str(Path(base).resolve()), filename, digest(descriptor), hashlib.sha256(raw).hexdigest(), index, row, shared)
    if _checked is None:
        return _json_bytes(raw)
    if key not in _checked:
        _checked[key] = _json_bytes(raw)
    return copy.deepcopy(_checked[key])


def _read_partitions(base, pointer, *, _checked=None, _prepared=None):
    """Reconstruct every part before the existing complete semantic validation."""
    shared = pointer.get("schema_version") == SHARED_POINTER_VERSION
    encoded = shared or pointer.get("schema_version") == GZIP_POINTER_VERSION
    if (set(pointer) != {"schema_version", "report_id", "generated_at", "row_count", "summary", "rows", "outcomes"}
            or pointer.get("schema_version") not in (PARTITION_POINTER_VERSION, GZIP_POINTER_VERSION, SHARED_POINTER_VERSION)
            or len(canonical(pointer) + b"\n") > INDEX_LIMIT):
        raise IntegrityError("Unsupported partitioned publication pointer")
    _hash(pointer.get("report_id"))
    report_id = pointer["report_id"]
    utc(pointer["generated_at"])
    if (type(pointer["row_count"]) is not int or not 0 <= pointer["row_count"] <= 250 * 4000
            or not isinstance(pointer["rows"], list) or len(pointer["rows"]) > 4000):
        raise IntegrityError("Partitioned row population exceeds supported bounds")
    for key in ("summary", "outcomes"):
        if set(pointer[key]) != {"path", "sha256", "decoded_bytes"}:
            raise IntegrityError("Malformed partition index descriptor")
    index = _partition_asset(base, pointer["summary"], "summary.json", index=True, report_id=report_id, _checked=_checked)
    fields = {"schema_version", "report_schema_version", "report_id", "row_count", "source_sha",
              "input_binding", "input_content_sha256", "summary", "coverage", "primary_raw_vs_adjusted",
              "uncertainty", "limitations", "contexts", "summary_partitions"}
    extended = index.get("report_schema_version") == "selection-report-v4"
    if extended: fields.add("forecast_accuracy")
    if (set(index) != fields or index["schema_version"] != (EXTENDED_PUBLIC_VERSION if extended else SHARED_PUBLIC_VERSION if shared else GZIP_PUBLIC_VERSION if encoded else PARTITION_PUBLIC_VERSION)
            or index["report_schema_version"] not in ("selection-report-v3", "selection-report-v4") or extended and not shared or index["report_id"] != report_id
            or index["row_count"] != pointer["row_count"]
            or set(index["summary"]) != {"warning", "disjoint_selected_partitions_reconciled"}
            or not isinstance(index["contexts"], dict) or not isinstance(index["summary_partitions"], list)):
        raise IntegrityError("Malformed partitioned summary index")
    _safe_value(index)
    for cid, context in index["contexts"].items():
        if set(context) != set(CONTEXT_FIELDS) or digest(context) != cid:
            raise IntegrityError("Invalid exact publication context")
    tables, groups, ids, used_contexts = [], set(), set(), set()
    for descriptor in index["summary_partitions"]:
        if set(descriptor) != ({"context_id", "period", "path", "sha256", "decoded_bytes", "table_count"} | (ENCODED_FIELDS if encoded else set())):
            raise IntegrityError("Malformed summary partition descriptor")
        cid, period = descriptor["context_id"], descriptor["period"]
        if (cid not in index["contexts"] or not isinstance(period, str)
                or not (period == "cumulative" or re.fullmatch(r"[0-9]{4}-w(?:0[1-9]|1[0-8])", period))
                or (cid, period) in groups or type(descriptor["table_count"]) is not int
                or descriptor["table_count"] < 1):
            raise IntegrityError("Duplicate or invalid summary context/period")
        groups.add((cid, period)); used_contexts.add(cid)
        part = _partition_asset(base, descriptor, "summary.json", encoded=encoded, _checked=_checked)
        if (set(part) != ({"schema_version", "context_id", "period", "tables"} | (set() if shared else {"report_id"}))
                or part["schema_version"] != (SHARED_SUMMARY_VERSION if shared else SUMMARY_PART_VERSION) or not shared and part["report_id"] != report_id
                or part["context_id"] != cid or part["period"] != period
                or not isinstance(part["tables"], list) or len(part["tables"]) != descriptor["table_count"]):
            raise IntegrityError("Mixed summary partition identity/context/period")
        for table in part["tables"]:
            if (_context(table) != index["contexts"][cid] or table.get("period") != period
                    or table.get("summary_id") in ids):
                raise IntegrityError("Mixed or duplicate partition summary")
            ids.add(table.get("summary_id")); tables.append(table)
    if used_contexts != set(index["contexts"]):
        raise IntegrityError("Unreferenced publication context")
    normalized = {key: value for key, value in index.items() if key not in ("contexts", "summary_partitions")}
    normalized["schema_version"] = REPORT_CONTRACTS[index["report_schema_version"]]
    normalized["summary"] = dict(index["summary"], tables=sorted(tables, key=_table_order))
    final_index = _partition_asset(base, pointer["outcomes"], "outcomes.json", index=True, report_id=report_id, _checked=_checked)
    if (set(final_index) != {"schema_version", "report_id", "outcome_count", "periods"}
            or final_index["schema_version"] != (SHARED_OUTCOME_INDEX_VERSION if shared else OUTCOME_INDEX_VERSION) or final_index["report_id"] != report_id
            or type(final_index["outcome_count"]) is not int or final_index["outcome_count"] < 0
            or not isinstance(final_index["periods"], list)):
        raise IntegrityError("Malformed outcome period index")
    outcomes, periods, identities = [], set(), set()
    for descriptor in final_index["periods"]:
        if (set(descriptor) != ({"season", "week", "path", "sha256", "decoded_bytes", "count"} | (ENCODED_FIELDS if encoded else set()))
                or type(descriptor["season"]) is not int or not 2000 <= descriptor["season"] <= 2200
                or type(descriptor["week"]) is not int or not 1 <= descriptor["week"] <= 18
                or type(descriptor["count"]) is not int or descriptor["count"] < 1):
            raise IntegrityError("Invalid outcome period descriptor")
        period = descriptor["season"], descriptor["week"]
        if period in periods:
            raise IntegrityError("Duplicate outcome period")
        periods.add(period)
        part = _partition_asset(base, descriptor, "outcomes.json", encoded=encoded, _checked=_checked)
        if (set(part) != ({"schema_version", "season", "week", "outcomes"} | (set() if shared else {"report_id"}))
                or part["schema_version"] != (SHARED_OUTCOME_VERSION if shared else OUTCOME_PART_VERSION) or not shared and part["report_id"] != report_id
                or type(part["season"]) is not int or type(part["week"]) is not int
                or (part["season"], part["week"]) != period
                or not isinstance(part["outcomes"], list) or len(part["outcomes"]) != descriptor["count"]):
            raise IntegrityError("Mixed outcome partition identity/period")
        for row in part["outcomes"]:
            key = identity(row)
            if (row.get("season"), row.get("week")) != period or key in identities:
                raise IntegrityError("Mixed or duplicate outcome identity")
            identities.add(key); outcomes.append(row)
    if len(outcomes) != final_index["outcome_count"]:
        raise IntegrityError("Outcome partition population differs")
    final = {"schema_version": OUTCOMES_VERSION, "report_id": report_id,
             "outcomes": sorted(outcomes, key=identity)}
    virtual = dict(pointer, schema_version=POINTER_VERSION)
    row_reader = None
    if encoded:
        def row_reader(descriptor, name):
            if set(descriptor) != {"path", "sha256", "decoded_bytes", "count"} | ENCODED_FIELDS:
                raise IntegrityError("Malformed gzip row descriptor")
            part = _partition_asset(base, descriptor, "rows.json" if shared else name, report_id=report_id,
                                    encoded=True, row=True, shared=shared, _checked=_checked)
            if shared:
                if set(part) != {"schema_version", "rows"} or part["schema_version"] != SHARED_ROWS_VERSION:
                    raise IntegrityError("Malformed shared row payload")
                return dict(part, schema_version=ROWS_VERSION, report_id=report_id)
            return part
    return _validate_legacy_publication(base, virtual, _partitioned=(normalized, final),
                                       _row_reader=row_reader, _layout=SHARED_LAYOUT_VERSION if shared else GZIP_LAYOUT_VERSION if encoded else None, _checked=_checked, _prepared=_prepared)


def _publication_graph(base, pointer):
    """Fresh bounded actual-byte closure, including ALL non-default/plain assets.

    Unchanged exact bytes inherit their previous complete structural/semantic
    check; this pass never establishes one. Indexes are read again to discover
    the complete declared graph. Historical supplied pointers are intentional:
    the outer generation validator, not this reader, qualifies the mutable alias.
    """
    base = Path(base)
    if base.is_symlink():
        raise IntegrityError("Symlinked publication root")
    version = pointer.get("schema_version")
    if version not in (POINTER_VERSION, PARTITION_POINTER_VERSION, GZIP_POINTER_VERSION, SHARED_POINTER_VERSION):
        raise IntegrityError("Unknown public pointer version")
    if set(pointer) != {"schema_version", "report_id", "generated_at", "row_count", "summary", "rows", "outcomes"}:
        raise IntegrityError("Unknown public pointer fields")
    if (len(canonical(pointer) + b"\n") > INDEX_LIMIT or type(pointer["row_count"]) is not int
            or not 0 <= pointer["row_count"] <= CHUNK_SIZE * 4000 or not isinstance(pointer["rows"], list)
            or len(pointer["rows"]) != (pointer["row_count"] + CHUNK_SIZE - 1) // CHUNK_SIZE):
        raise IntegrityError("Public graph exceeds supported bounds")
    _hash(pointer["report_id"]); utc(pointer["generated_at"])
    report_id = pointer["report_id"]
    shared = version == SHARED_POINTER_VERSION
    encoded = shared or version == GZIP_POINTER_VERSION
    graph = []

    def asset(descriptor, name, *, index=False, row=False, plain=False):
        if not isinstance(descriptor, dict):
            raise IntegrityError("Malformed public asset descriptor")
        fields = {"path", "sha256"}
        if plain:
            fields |= {"count"} if row else set()
        elif index:
            fields |= {"decoded_bytes"}
        elif row:
            fields |= {"decoded_bytes", "count"} | ENCODED_FIELDS
        elif name == "summary.json":
            fields |= {"decoded_bytes", "context_id", "period", "table_count"} | (ENCODED_FIELDS if encoded else set())
        else:
            fields |= {"decoded_bytes", "season", "week", "count"} | (ENCODED_FIELDS if encoded else set())
        if set(descriptor) != fields:
            raise IntegrityError("Unknown public graph descriptor fields")
        _hash(descriptor["sha256"])
        compressed = encoded and not (index or plain)
        if compressed:
            _hash(descriptor.get("encoded_sha256"))
            if descriptor.get("encoding") != "gzip":
                raise IntegrityError("Unsupported public graph encoding")
        namespace = report_id if index or plain or row and not shared else descriptor["encoded_sha256"] if compressed else descriptor["sha256"]
        if descriptor.get("path") != namespace + "/" + name:
            raise IntegrityError("Unsafe public graph path")
        path = base / descriptor["path"]
        _no_symlinks(path, base)
        if not path.resolve().is_relative_to(base.resolve()) or not path.is_file():
            raise IntegrityError("Invalid public graph asset type/root")
        limit = ROW_LIMIT if row else INDEX_LIMIT if index else SUMMARY_LIMIT
        if plain:
            # Legacy row descriptors have NO byte size. Read to the real cap;
            # stat, mtime and filename identity cannot substitute for this hash.
            checksum, size = hashlib.sha256(), 0
            with path.open("rb") as handle:
                while True:
                    block = handle.read(min(65536, limit - size + 1))
                    if not block:
                        break
                    size += len(block)
                    if size > limit:
                        raise IntegrityError("Public graph asset exceeds size limit")
                    checksum.update(block)
            actual = checksum.hexdigest()
            if actual != descriptor["sha256"]:
                raise IntegrityError("Public graph actual byte checksum mismatch")
        else:
            if type(descriptor.get("decoded_bytes")) is not int or not 0 < descriptor["decoded_bytes"] <= limit:
                raise IntegrityError("Public graph exceeds decoded size limit")
            actual = _fresh_stored_bytes(path, descriptor, limit, encoded=compressed)
        graph.append((name, descriptor, actual))
        if index:
            # Small bounded index; fresh parse discovers all contexts/periods.
            return _json_bytes(_read_asset_bytes(path, descriptor, limit))

    for number, descriptor in enumerate(pointer["rows"]):
        asset(descriptor, "rows.json" if shared else f"rows-{number:04d}.json", row=True, plain=not encoded)
    if version == POINTER_VERSION:
        asset(pointer["summary"], "summary.json", plain=True)
        asset(pointer["outcomes"], "outcomes.json", plain=True)
    else:
        index = asset(pointer["summary"], "summary.json", index=True)
        final = asset(pointer["outcomes"], "outcomes.json", index=True)
        # Exact index schemas, context and semantic constraints are still checked
        # by the complete validator on every first/changed graph.
        for field, value in (("summary_partitions", index), ("periods", final)):
            if not isinstance(value, dict) or not isinstance(value.get(field), list):
                raise IntegrityError("Malformed public graph index")
        for descriptor in index["summary_partitions"]:
            asset(descriptor, "summary.json")
        for descriptor in final["periods"]:
            asset(descriptor, "outcomes.json")
    return digest({"pointer": pointer, "assets": graph})


def _complete_publication(base, pointer, checked):
    values = []
    if pointer.get("schema_version") in (PARTITION_POINTER_VERSION, GZIP_POINTER_VERSION, SHARED_POINTER_VERSION):
        _read_partitions(Path(base), pointer, _checked=checked, _prepared=values)
    else:
        _validate_legacy_publication(base, pointer, _checked=checked, _prepared=values)
    return values


def _prepared_publication(base, pointer, _checked):
    """Complete validation first; fresh graph equality is necessary for reuse."""
    _checked = {} if _checked is None else _checked
    helper = _publication_helpers()
    if helper is None:
        return tuple(canonical(value) for value in _complete_publication(base, pointer, {}))
    context = _checked.get(("publisher-context",))
    if context is None or context[0] != helper:
        context = (helper, {})
        _checked[("publisher-context",)] = context
    local = context[1]
    memo = local.setdefault(("prepared-publications",), _PreparedPublications())
    before = _publication_graph(base, pointer)
    if _publication_helpers() != helper:
        raise IntegrityError("Public helper changed during fresh graph check")
    key = (str(Path(base).resolve()), helper, before)
    prepared = memo.get(key)
    if prepared is not None:
        if _publication_helpers() != helper:
            raise IntegrityError("Public helper changed during prepared reuse")
        return prepared
    values = _complete_publication(base, pointer, local)
    # Never seed a success assembled across changing leaves or helper code.
    if _publication_graph(base, pointer) != before or _publication_helpers() != helper:
        raise IntegrityError("Public graph/helper changed during complete validation")
    prepared = tuple(canonical(value) for value in values)
    memo.put(key, prepared)
    return prepared


def validate_publication(base, pointer, *, _checked=None):
    """Version dispatch is explicit; unsupported data never falls back."""
    return _json_bytes(_prepared_publication(base, pointer, _checked)[0])


def prepare_publication(base, summary, rows, outcomes, chunks, generated_at, *, partitioned=True, encoding=None, shared=False, _checked=None):
    """Create immutable assets and fully validate; caller alone advances latest."""
    base = Path(base)
    if len(chunks) > 4000:
        raise IntegrityError("Public row-chunk count exceeds supported bounds")
    use_parts = partitioned and summary["report_schema_version"] in ("selection-report-v3", "selection-report-v4")
    if summary["report_schema_version"] == "selection-report-v4" and not (use_parts and shared and encoding == "gzip"):
        raise IntegrityError("Extended report requires the existing shared gzip partition layout")
    if encoding not in (None, "gzip") or encoding == "gzip" and not use_parts:
        raise IntegrityError("Unsupported publication encoding contract")
    encoded = encoding == "gzip"
    if shared and not (use_parts and encoded):
        raise IntegrityError("Shared payloads require explicit gzip partition contract")
    summary = {key: value for key, value in summary.items() if key != "report_id"}
    summary = dict(summary, summary=dict(summary["summary"]))
    outcomes = sorted(outcomes, key=identity)
    if use_parts:
        summary["summary"]["tables"] = sorted(summary["summary"]["tables"], key=_table_order)
    core = {"summary": summary, "rows": rows, "outcomes": outcomes}
    if use_parts:
        core["layout"] = SHARED_LAYOUT_VERSION if shared else GZIP_LAYOUT_VERSION if encoded else LAYOUT_VERSION
    public_id = digest(core)

    def save(name, payload, limit, *, content_addressed=False, compress=False):
        raw = canonical(payload) + b"\n"
        if len(raw) > limit:
            raise IntegrityError("Public asset exceeds the supported reader size limit")
        checksum = hashlib.sha256(raw).hexdigest()
        stored = raw
        extra = {}
        if compress and encoded:
            buffer = io.BytesIO()
            with gzip.GzipFile(filename="", fileobj=buffer, mode="wb", compresslevel=6, mtime=0) as handle:
                handle.write(raw)
            stored = buffer.getvalue()
            if len(stored) > limit:
                raise IntegrityError("Public asset exceeds encoded size limit")
            extra = {"encoding": "gzip", "encoded_sha256": hashlib.sha256(stored).hexdigest(), "encoded_bytes": len(stored)}
        namespace = (extra.get("encoded_sha256") or checksum) if content_addressed else public_id
        path = base / namespace / name
        _no_symlinks(path, base)
        _create_file(path, stored)
        return {"path": namespace + "/" + name, "sha256": checksum, "decoded_bytes": len(raw), **extra}

    descriptors = []
    for number, chunk in enumerate(chunks):
        payload = {"schema_version": SHARED_ROWS_VERSION if shared else ROWS_VERSION, "rows": chunk}
        if not shared:
            payload["report_id"] = public_id
        value = save("rows.json" if shared else f"rows-{number:04d}.json", payload,
                     ROW_LIMIT, content_addressed=shared, compress=True)
        descriptors.append(dict(value, count=len(chunk)) if encoded else {"path": value["path"], "sha256": value["sha256"], "count": len(chunk)})
    if use_parts:
        contexts, groups = {}, defaultdict(list)
        for table in summary["summary"]["tables"]:
            context = _context(table); cid = digest(context); contexts[cid] = context
            groups[(cid, table["period"])].append(table)
        parts = []
        for (cid, period), tables in sorted(groups.items()):
            payload = {"schema_version": SHARED_SUMMARY_VERSION if shared else SUMMARY_PART_VERSION,
                       "context_id": cid, "period": period, "tables": tables}
            if not shared:
                payload["report_id"] = public_id
            value = save("summary.json", payload, SUMMARY_LIMIT, content_addressed=True, compress=True)
            parts.append(dict(value, context_id=cid, period=period, table_count=len(tables)))
        index = dict(summary, schema_version=EXTENDED_PUBLIC_VERSION if summary["report_schema_version"] == "selection-report-v4" else SHARED_PUBLIC_VERSION if shared else GZIP_PUBLIC_VERSION if encoded else PARTITION_PUBLIC_VERSION, report_id=public_id,
                     summary={key: value for key, value in summary["summary"].items() if key != "tables"},
                     contexts=contexts, summary_partitions=parts)
        summary_descriptor = save("summary.json", index, INDEX_LIMIT)
        by_period = defaultdict(list)
        for row in outcomes:
            by_period[(row["season"], row["week"])].append(row)
        periods = []
        for (season, week), members in sorted(by_period.items()):
            payload = {"schema_version": SHARED_OUTCOME_VERSION if shared else OUTCOME_PART_VERSION,
                       "season": season, "week": week, "outcomes": members}
            if not shared:
                payload["report_id"] = public_id
            value = save("outcomes.json", payload, SUMMARY_LIMIT, content_addressed=True, compress=True)
            periods.append(dict(value, season=season, week=week, count=len(members)))
        final_descriptor = save("outcomes.json", {"schema_version": SHARED_OUTCOME_INDEX_VERSION if shared else OUTCOME_INDEX_VERSION, "report_id": public_id,
                               "outcome_count": len(outcomes), "periods": periods}, INDEX_LIMIT)
    else:
        summary_descriptor = save("summary.json", dict(summary, report_id=public_id), SUMMARY_LIMIT)
        final_descriptor = save("outcomes.json", {"schema_version": OUTCOMES_VERSION, "report_id": public_id,
                                "outcomes": outcomes}, SUMMARY_LIMIT)
        summary_descriptor.pop("decoded_bytes"); final_descriptor.pop("decoded_bytes")
    pointer = {"schema_version": (SHARED_POINTER_VERSION if shared else GZIP_POINTER_VERSION if encoded else PARTITION_POINTER_VERSION) if use_parts else POINTER_VERSION,
               "report_id": public_id, "generated_at": stamp(utc(generated_at)), "row_count": len(rows),
               "summary": summary_descriptor, "rows": descriptors, "outcomes": final_descriptor}
    if use_parts and len(canonical(pointer) + b"\n") > INDEX_LIMIT:
        raise IntegrityError("Public pointer exceeds the supported reader size limit")
    validate_publication(base, pointer, _checked=_checked)
    return pointer


def publication_contents(base, pointer, *, _checked=None):
    """Validated complete public values; never a partially loaded browser page."""
    return tuple(_json_bytes(value) for value in _prepared_publication(base, pointer, _checked))


def repack_publication(base, pointer, *, packaged_at=None, _checked=None):
    _checked = {} if _checked is None else _checked
    summary, rows, outcomes = publication_contents(base, pointer, _checked=_checked)
    chunks = [rows[n:n + CHUNK_SIZE] for n in range(0, len(rows), CHUNK_SIZE)]
    # This is a new packaging/publication clock, not a new football capture.
    return prepare_publication(base, summary, rows, outcomes, chunks,
                               packaged_at or pointer["generated_at"], encoding="gzip", shared=True, _checked=_checked)


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
    decisions, _ = build_decisions(receipts, policy, observed_at, corrected.legacy_engine_hashes())
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
        expected_engine = (hashes if row.get("model_version") == policy["model"] else
                           corrected.source_hashes(row["model_version"])
                           if row.get("model_version") in corrected.PRESENCE_MODELS else
                           classic.ENGINE if row.get("model_version") == classic.MODEL else None)
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
                or expected_engine is None
                or row.get("engine_files") != expected_engine or row.get("engine_sha256") != digest(expected_engine)
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


def publish_selection_report(root, observed_at=None, *, source_sha=None, _checked=None):
    """Prepare assets for the existing updater, never commit/upload/deploy them."""
    root = Path(root).resolve()
    observed_at = utc(observed_at or datetime.now(timezone.utc))
    source_sha = _source_sha(root, source_sha)
    policy, hashes = load_json(root / "config/timing-policy.json"), corrected.legacy_engine_hashes()
    originals = {}
    with tempfile.TemporaryDirectory(prefix="nfl-selection-publication-") as temporary:
        stage, analysis = Path(temporary) / "saved-inputs", Path(temporary) / "private-analysis"
        stage.mkdir()
        # No .git or separate population/raw-capture lanes. Changed generated
        # files are bound to these exact bytes, never falsely asserted at HEAD.
        patterns = list(PATTERNS)
        has_ranked = any((root / "data" / selection_strategies.COMPLETE_LANE).rglob("*.json.gz"))
        if has_ranked:
            # A copied report root is a separate trust namespace. Carry its
            # original source/evidence closure, not a cached qualification.
            patterns += ["data/verification/**/*.json.gz", "pull/**/*", "tools/**/*", "config/**/*",
                         "output/data/meta.json", "output/data/matchup-proof.json", "output/data/verification-scope.json"]
        else:
            patterns += ["data/verification/[0-9][0-9][0-9][0-9]/w[0-9][0-9]/*.json.gz"]
        for pattern in patterns:
            for path in sorted(root.glob(pattern)):
                if path.is_dir() or "__pycache__" in path.parts or path.suffix == ".pyc": continue
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
        written = set()
        def fresh_inputs():
            names = set()
            for pattern in patterns:
                for path in root.glob(pattern):
                    if "__pycache__" in path.parts or path.suffix == ".pyc": continue
                    _no_symlinks(path, root)
                    if path.is_file(): names.add(path.relative_to(root).as_posix())
            if set(originals) - names or names - set(originals) - written:
                raise IntegrityError("Saved input dependency inventory changed during publication")
            if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != sha for name, sha in originals.items()):
                raise IntegrityError("Saved input changed during public report")
        board_paths = []
        for path in sorted((stage / "data/verification").glob("[0-9][0-9][0-9][0-9]/w[0-9][0-9]/*.json.gz")):
            original = read(path)
            if original.get("schema_version") not in ("matchup-inputs-v2", corrected.INPUTS): continue
            board = original.get("week_data")
            if not isinstance(board, dict) or original.get("output_sha256") != digest(board):
                raise IntegrityError("Saved original board/input digest differs")
            board_path = stage / "saved-original-boards" / (digest(board) + ".json")
            _create_file(board_path, canonical(board) + b"\n"); board_paths.append(board_path)
        input_digest = digest(originals)
        state = root / "data/verification/selection-grading/decisions"
        _no_symlinks(state, root)
        for path in sorted(state.rglob("*.json.gz")):
            if path.is_symlink():
                raise IntegrityError("Unsafe persistent decision path")
            _no_symlinks(path, root)
            payload = _ledger(read(path), policy, hashes, observed_at)
            write(analysis, "selection_decisions", payload)
        import partial_week
        ranked_state = root / "data/verification/ranked-selection-decisions"
        for path in sorted(ranked_state.rglob("*.json.gz")):
            payload = partial_week._saved(root, path.relative_to(root).as_posix(), "verification/ranked-selection-decisions")
            write(analysis, "ranked_selection_decisions", payload)
        report, _ = run_report([stage], analysis, now=observed_at,
                              policy=policy, expected_hashes=hashes, report_version="selection-report-v4",
                              original_board_paths=board_paths, diagnostic_exports=False)
        summary, rows, outcomes, chunks, public_id = _projection(report, source_sha=source_sha,
                                                               input_digest=input_digest)
        base = root / "output/data/selection-grading"
        directory = base / public_id
        _no_symlinks(directory, root)
        _no_symlinks(base / "latest.json", root)

        checked = {} if _checked is None else _checked
        pointer = prepare_publication(base, summary, rows, outcomes, chunks, observed_at,
                                      encoding="gzip", shared=True, _checked=checked)
        public_id = pointer["report_id"]
        # Recheck every source byte before publishing either persistent state or
        # latest. Failure may leave unreachable content-addressed assets only.
        fresh_inputs()
        for path in sorted((analysis / "data/selection_decisions").rglob("*.json.gz")):
            payload = read(path)
            checkpoint_rows = [row for row in payload["rows"] if row["checkpoint"] != "history"]
            if checkpoint_rows:
                saved_path = _state_write(root, "verification/selection-grading/decisions",
                             _ledger(dict(payload, rows=checkpoint_rows), policy, hashes, observed_at))
                written.add(saved_path.relative_to(root).as_posix())
        for path in sorted((analysis / "data/ranked_selection_decisions").rglob("*.json.gz")):
            saved_path = _state_write(root, "verification/ranked-selection-decisions", read(path))
            written.add(saved_path.relative_to(root).as_posix())
        data = load_json(root / "output/data/week.json")
        saved_path = _state_write(root, "verification/selection-grading/runs", {
            "schema_version": "selection-publication-run-v1", "season": data["season"], "week": data["week"],
            "generated_at": stamp(observed_at), "source_sha": source_sha,
            "input_content_sha256": input_digest, "public_report_sha256": public_id,
            "input_binding": "NOT_YET_GIT_COMMITTED"})
        written.add(saved_path.relative_to(root).as_posix())
        from reliability import atomic_json
        # Rehash the complete produced graph at the last publication boundary.
        # A typed/semantic cache never substitutes for fresh physical bytes.
        validate_publication(base, pointer, _checked=checked)
        fresh_inputs()
        atomic_json(base / "latest.json", pointer)
        return pointer
