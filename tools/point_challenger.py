"""Offline fixed receptions challenger; never changes production forecasts.

Saved v1 candidates are checked against this retained v1 implementation, their
registration and their original baseline receipt at every consumption. A future
candidate implementation needs a separate version/validator, not a rewritten v1
file or a permissive hash fallback. Local clocks establish local recording, not
provider as-of time or public publication. No HTTP or updater hook exists here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from evidence import read, write
from reliability import IntegrityError, digest, engine_hashes, finite, load_json, stamp, utc
from scorecard import cluster_interval, identity, latest_outcomes, metrics
from scoring import CATEGORIES


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_ID = "rec-half-adjustment-v1"
PROTOCOL_VERSION = "rec-half-protocol-v1"
REGISTRATION_SCHEMA = "point-candidate-registration-v1"
SCHEMA_VERSION = "point-candidate-v1"
BASELINE_MODEL = "original_sleeper_matchup_baseline"
WINDOW_SEASON = 2026
WINDOW_WEEKS = tuple(range(7, 15))
# A registration records week labels, not invented complete-week populations.
# Eligibility still requires the original saved kickoff and complete-week proof
# remains the authoritative scorecard's separate requirement.
WINDOW_START = "2026-10-23T00:15:00Z"
WINDOW_FIRST_KICKOFFS = {
    "7": WINDOW_START, "8": "2026-10-30T00:15:00Z", "9": "2026-11-06T01:15:00Z",
    "10": "2026-11-13T01:15:00Z", "11": "2026-11-20T01:15:00Z", "12": "2026-11-26T01:00:00Z",
    "13": "2026-12-04T01:15:00Z", "14": "2026-12-11T01:15:00Z"}
SCHEDULE_REFERENCE = {
    "source_commit": "52d068326045c010c9e3bb89f23188f9153ab151",
    "path": "output/data/teams.json", "generated_at": "2026-10-14T01:10:09Z",
    "file_sha256": "84a85e361cb0d2f01a1e5f0be8e2072d854b386d4753e29e4b1fff496a23ea7e",
    "purpose": "EXISTING_PLANNING_SCHEDULE_NOT_INDEPENDENT_FULL_WEEK_PROOF"}
MODES = ("prospective", "development_descriptive")


def code_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def protocol_contract():
    return {"candidate_id": CANDIDATE_ID, "version": PROTOCOL_VERSION,
            "target": "rec", "formula": "raw + 0.5 * (unchanged_adjusted - raw)",
            "weight": 0.5, "fitting": False, "tuning_budget": 0,
            "baseline_model": BASELINE_MODEL, "same_original_receipt": True,
            "selection": "earliest_eligible_common_triple_by_capture_then_completion_then_digest",
            "window": {"season": WINDOW_SEASON, "weeks": list(WINDOW_WEEKS),
                       "first_kickoff": WINDOW_START, "first_kickoffs_by_week": dict(WINDOW_FIRST_KICKOFFS),
                       "schedule_reference": dict(SCHEDULE_REFERENCE), "shift_or_extension_allowed": False,
                       "schedule_changes": "retain_original_membership_and_kickoffs; flag_changes; never_shift_window"},
            "production_promotion": False,
            "recording": "OFFLINE_ONLY_NO_UPDATER_HOOK",
            "publication": "LOCAL_OBSERVATION_NOT_VERIFIED_PUBLICATION"}


def point(raw, adjusted):
    for value, label in ((raw, "raw reception point"), (adjusted, "adjusted reception point")):
        finite(value, label, optional=False)
        if value < 0:
            raise IntegrityError("Reception point forecasts must be nonnegative")
    value = raw + 0.5 * (adjusted - raw)
    finite(value, "candidate reception point", optional=False)
    return value


def _sha(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise IntegrityError(f"Invalid {label}")


def _commit(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value)):
        raise IntegrityError("Invalid source commit")


def _hashes(value):
    if (not isinstance(value, dict) or not value or any(not isinstance(k, str) or not k
            or not isinstance(v, str) or not v for k, v in value.items())):
        raise IntegrityError("Invalid baseline engine identities")


def _period(baseline):
    """Original v1 receipts record season/week on rows, not their header."""
    try:
        rows = baseline["rows"]
        if not isinstance(rows, list) or not rows:
            raise IntegrityError("Original receipt has no recorded opportunity population")
        periods = {(row["season"], row["week"]) for row in rows}
        if len(periods) != 1:
            raise IntegrityError("Original receipt mixes season/week identities")
        season, week = next(iter(periods))
        if type(season) is not int or type(week) is not int or not 2000 <= season <= 2200 or not 1 <= week <= 18:
            raise IntegrityError("Invalid source season/week")
        if (("season" in baseline and baseline["season"] != season)
                or ("week" in baseline and baseline["week"] != week)):
            raise IntegrityError("Original header differs from its recorded row period")
        return season, week
    except (KeyError, TypeError, AttributeError) as err:
        raise IntegrityError("Malformed original receipt period") from err


def make_registration(expected_hashes, *, source_commit=None):
    """Freeze actual current code/protocol clocks, without fitting or collecting."""
    now = datetime.now(timezone.utc)
    _hashes(expected_hashes)
    _commit(source_commit)
    contract = protocol_contract()
    payload = {"schema_version": REGISTRATION_SCHEMA, "candidate_id": CANDIDATE_ID,
               "protocol_version": PROTOCOL_VERSION, "protocol": contract,
               "protocol_sha256": digest(contract), "registered_at": stamp(now),
               "code_frozen_at": stamp(now), "model_code_sha256": code_sha256(),
               "expected_engine_files": copy.deepcopy(expected_hashes),
               "engine_sha256": digest(expected_hashes), "source_commit": source_commit,
               "production_enabled": False, "recording_status": "OFFLINE_NOT_ACTIVATED"}
    validate_registration(payload, expected_hashes, now=now)
    return payload


def validate_registration(registration, expected_hashes=None, *, now=None):
    now = utc(now or datetime.now(timezone.utc))
    expected_hashes = engine_hashes(ROOT) if expected_hashes is None else expected_hashes
    try:
        fields = {"schema_version", "candidate_id", "protocol_version", "protocol", "protocol_sha256",
                  "registered_at", "code_frozen_at", "model_code_sha256", "expected_engine_files",
                  "engine_sha256", "source_commit", "production_enabled", "recording_status"}
        if (set(registration) != fields or registration["schema_version"] != REGISTRATION_SCHEMA
                or registration["candidate_id"] != CANDIDATE_ID
                or registration["protocol_version"] != PROTOCOL_VERSION
                or registration["protocol"] != protocol_contract()
                or registration["protocol_sha256"] != digest(protocol_contract())
                or registration["model_code_sha256"] != code_sha256()
                or registration["production_enabled"] is not False
                or registration["recording_status"] != "OFFLINE_NOT_ACTIVATED"):
            raise IntegrityError("Unsupported or altered fixed candidate registration")
        _hashes(registration["expected_engine_files"])
        if registration["engine_sha256"] != digest(registration["expected_engine_files"]):
            raise IntegrityError("Registration engine digest mismatch")
        if expected_hashes is not None and registration["expected_engine_files"] != expected_hashes:
            raise IntegrityError("Registration does not match retained baseline engine")
        _commit(registration["source_commit"])
        frozen, registered = utc(registration["code_frozen_at"]), utc(registration["registered_at"])
        if not frozen <= registered <= now or registered >= utc(WINDOW_START):
            raise IntegrityError("Registration is future, reversed or too late for the fixed window")
        return registration
    except (KeyError, TypeError, AttributeError) as err:
        raise IntegrityError("Malformed candidate registration") from err


def _source_rows(baseline, registration, started, completed, mode):
    """Re-derive the entire admitted population from its unchanged source."""
    try:
        if (baseline["schema_version"] != "baseline-capture-v1" or baseline["model"] != BASELINE_MODEL
                or baseline["mode"] != "live" or baseline["engine_files"] != registration["expected_engine_files"]
                or baseline["engine_sha256"] != digest(registration["expected_engine_files"])):
            raise IntegrityError("Unsupported baseline schema/model/mode/engine")
        _sha(baseline["input_sha256"], "original input digest")
        season, week = _period(baseline)
        generated, captured = utc(baseline["forecast_generated_at"]), utc(baseline["captured_at"])
        if not generated <= captured <= started <= completed:
            raise IntegrityError("Invalid original generation/capture/calculation clocks")
        if mode == "prospective" and captured <= utc(registration["registered_at"]):
            raise IntegrityError("Prospective candidate requires a new original observation after registration")
        if not isinstance(baseline["rows"], list):
            raise IntegrityError("Malformed original forecast population")
        rows, seen, exclusions, observed = [], set(), Counter(), 0
        for row in baseline["rows"]:
            if row.get("category") not in CATEGORIES:
                raise IntegrityError("Unknown original forecast category")
            key = identity(row)
            if key in seen:
                raise IntegrityError("Duplicate opportunity within original receipt")
            seen.add(key)
            if row["category"] != "rec":
                continue
            observed += 1
            if ((row["season"], row["week"]) != (season, week)
                    or any(not isinstance(row.get(k), str) or not row[k].strip() for k in ("game_id", "player_id", "team"))):
                raise IntegrityError("Invalid same-receipt opportunity identity")
            kickoff = utc(row["kickoff"])
            if generated >= kickoff or captured >= kickoff:
                exclusions["source_not_pregame"] += 1
                continue
            if mode == "prospective" and (season != WINDOW_SEASON or week not in WINDOW_WEEKS
                                          or kickoff < utc(WINDOW_START)):
                exclusions["outside_fixed_window"] += 1
                continue
            if mode == "prospective" and completed >= kickoff:
                exclusions["calculation_not_pregame"] += 1
                continue
            raw, adjusted = row.get("raw_projection"), row.get("adjusted_projection")
            if raw is None or adjusted is None:
                exclusions["missing_pair"] += 1
                continue
            candidate = point(raw, adjusted)
            saved = {k: copy.deepcopy(row[k]) for k in ("season", "week", "game_id", "player_id", "category", "team", "kickoff")}
            # No line/lean or Top membership is required for numeric forecasts.
            saved.update(raw_projection=raw, adjusted_projection=adjusted,
                         candidate_projection=candidate, baseline_row_sha256=digest(row))
            for key in ("opponent", "opp"):
                if key in row:
                    saved[key] = copy.deepcopy(row[key])
            rows.append(saved)
        rows.sort(key=lambda row: identity(row))
        return rows, {"reception_rows_observed": observed, "admitted_rows": len(rows),
                      "excluded": dict(sorted(exclusions.items()))}
    except (KeyError, TypeError, AttributeError) as err:
        raise IntegrityError("Malformed original baseline receipt") from err


def make_candidate(baseline, registration, *, mode="prospective", code_commit=None):
    """Calculate now. Caller cannot request a backdated clock through this API."""
    started = datetime.now(timezone.utc)
    validate_registration(registration, now=started)
    if mode not in MODES:
        raise IntegrityError("Unknown candidate evidence mode")
    _commit(code_commit)
    # Calculate before sampling completion; validating saved rows re-derives the
    # same arithmetic and all completion-dependent exclusions below.
    _source_rows(baseline, registration, started, started, mode)
    completed = datetime.now(timezone.utc)
    rows, coverage = _source_rows(baseline, registration, started, completed, mode)
    season, week = _period(baseline)
    payload = {"schema_version": SCHEMA_VERSION, "candidate_id": CANDIDATE_ID,
               "protocol_version": PROTOCOL_VERSION, "protocol_sha256": registration["protocol_sha256"],
               "registration_sha256": digest(registration), "model_code_sha256": code_sha256(),
               "code_commit": code_commit, "season": season, "week": week,
               "mode": mode, "evidence_label": "LOCAL_ORIGINAL_PREGAME_CANDIDATE_PUBLICATION_NOT_VERIFIED"
               if mode == "prospective" else "DEVELOPMENT_DESCRIPTIVE_NOT_PROSPECTIVE",
               "baseline_payload_sha256": digest(baseline),
               "forecast_generated_at": baseline["forecast_generated_at"], "captured_at": baseline["captured_at"],
               "calculation_started_at": stamp(started), "calculation_completed_at": stamp(completed),
               "rows": rows, "coverage": coverage, "production_enabled": False}
    validate_candidate(payload, baseline, registration, now=completed)
    return payload


def validate_candidate(candidate, baseline, registration, *, now=None):
    now = utc(now or datetime.now(timezone.utc))
    validate_registration(registration, now=now)
    try:
        expected = {"schema_version", "candidate_id", "protocol_version", "protocol_sha256", "registration_sha256",
                    "model_code_sha256", "code_commit", "season", "week", "mode", "evidence_label",
                    "baseline_payload_sha256", "forecast_generated_at", "captured_at", "calculation_started_at",
                    "calculation_completed_at", "rows", "coverage", "production_enabled"}
        mode = candidate["mode"]
        label = ("LOCAL_ORIGINAL_PREGAME_CANDIDATE_PUBLICATION_NOT_VERIFIED" if mode == "prospective"
                 else "DEVELOPMENT_DESCRIPTIVE_NOT_PROSPECTIVE")
        if (set(candidate) != expected or candidate["schema_version"] != SCHEMA_VERSION
                or candidate["candidate_id"] != CANDIDATE_ID or candidate["protocol_version"] != PROTOCOL_VERSION
                or candidate["protocol_sha256"] != registration["protocol_sha256"]
                or candidate["registration_sha256"] != digest(registration)
                or candidate["model_code_sha256"] != registration["model_code_sha256"]
                or candidate["production_enabled"] is not False or mode not in MODES
                or candidate["evidence_label"] != label
                or candidate["baseline_payload_sha256"] != digest(baseline)
                or (candidate["season"], candidate["week"]) != _period(baseline)
                or candidate["forecast_generated_at"] != baseline["forecast_generated_at"]
                or candidate["captured_at"] != baseline["captured_at"]):
            raise IntegrityError("Unsupported or altered saved candidate contract")
        _commit(candidate["code_commit"])
        started, completed = utc(candidate["calculation_started_at"]), utc(candidate["calculation_completed_at"])
        if completed > now or started < utc(registration["code_frozen_at"]):
            raise IntegrityError("Candidate calculation is future or before its code freeze")
        rows, coverage = _source_rows(baseline, registration, started, completed, mode)
        if candidate["rows"] != rows or candidate["coverage"] != coverage:
            raise IntegrityError("Saved candidate differs from its original source or fixed formula")
        return candidate["rows"]
    except (KeyError, TypeError, AttributeError) as err:
        raise IntegrityError("Malformed saved candidate") from err


def capture_candidate(output_root, baseline, registration, **kwargs):
    """Create-only local evidence. Repeated identical writes retain original bytes."""
    payload = make_candidate(baseline, registration, **kwargs)
    return write(output_root, "verification/point-candidates", payload)


def _scores(rows):
    roles = {"raw_sleeper": "raw_projection", "unchanged_website": "adjusted_projection", "candidate": "candidate_projection"}
    result = {role: metrics(rows, field) for role, field in roles.items()}
    candidate = result["candidate"]
    for role in ("raw_sleeper", "unchanged_website"):
        result[f"paired_mae_delta_candidate_minus_{role}"] = candidate["mae"] - result[role]["mae"] if rows else None
        result[f"paired_rmse_delta_candidate_minus_{role}"] = candidate["rmse"] - result[role]["rmse"] if rows else None
    return result


def _context(rows):
    return {"rows": len(rows), "unique_players": len({r["player_id"] for r in rows}),
            "unique_games": len({(r["season"], r["week"], r["game_id"]) for r in rows}),
            "unique_weeks": len({(r["season"], r["week"]) for r in rows})}


def evaluate(candidates, baselines, outcome_snapshots, registration, *, now=None, policy=None):
    """Consume retained saved evidence, never fetch statistics or infer outcomes."""
    now = utc(now or datetime.now(timezone.utc))
    validate_registration(registration, now=now)
    sources = {digest(payload): payload for payload in baselines}
    candidate_hashes, chosen = set(), {}
    coverage, exclusions = Counter(), Counter()
    ordered = sorted(candidates, key=lambda p: (utc(p["captured_at"]), utc(p["calculation_completed_at"]), digest(p)))
    for payload in ordered:
        payload_sha = digest(payload)
        if payload_sha in candidate_hashes:
            coverage["duplicate_candidate_receipts"] += 1
            continue
        candidate_hashes.add(payload_sha)
        baseline = sources.get(payload.get("baseline_payload_sha256"))
        if baseline is None:
            raise IntegrityError("Candidate's original baseline receipt is unavailable")
        rows = validate_candidate(payload, baseline, registration, now=now)
        coverage["unique_candidate_receipts"] += 1
        for reason, count in payload["coverage"]["excluded"].items():
            exclusions[reason] += count
        if payload["mode"] != "prospective":
            exclusions["development_descriptive_rows"] += len(rows)
            continue
        coverage["eligible_capture_rows"] += len(rows)
        for row in rows:
            key = identity(row)
            if key in chosen:
                coverage["repeated_capture_rows"] += 1
                continue
            chosen[key] = {**copy.deepcopy(row), "candidate_payload_sha256": payload_sha,
                           "baseline_payload_sha256": payload["baseline_payload_sha256"],
                           "registration_sha256": payload["registration_sha256"],
                           "captured_at": payload["captured_at"], "forecast_generated_at": payload["forecast_generated_at"],
                           "calculation_started_at": payload["calculation_started_at"],
                           "calculation_completed_at": payload["calculation_completed_at"]}
    snapshots = list(outcome_snapshots)
    if any(utc(p["collected_at"]) > now for p in snapshots):
        raise IntegrityError("Outcome observation is from the future")
    outcomes = latest_outcomes(snapshots)
    statuses, detail, resolved = Counter(), [], []
    for key, forecast in sorted(chosen.items()):
        outcome = outcomes.get(key)
        status = outcome["status"] if outcome else "missing_outcome"
        reason = outcome.get("reason") if outcome else "no_saved_outcome_for_common_opportunity"
        if outcome:
            if outcome.get("kickoff") and utc(outcome["kickoff"]) != utc(forecast["kickoff"]):
                status = "excluded_schedule_changed"
            elif outcome.get("team") != forecast["team"]:
                status = "excluded_team_mismatch"
            elif outcome.get("outcome_identity_status") == "quarantined":
                status = "unresolved"
            entry = outcome.get("stats_entry")
            selected = outcome.get("selected_outcome_provenance") or {}
            source = selected.get("source")
            if status == "resolved" and (not isinstance(source, str) or not source.strip()
                                          or not isinstance(entry, dict)):
                # The shared consumer keeps legacy numeric rows readable. A
                # new prospective candidate must not acquire sourced evidence
                # merely because such a legacy row contains an actual number.
                status, reason = "unresolved", "legacy_missing_source_or_stats"
            opponent = forecast.get("opponent", forecast.get("opp"))
            if opponent is not None and isinstance(entry, dict) and entry.get("opp") is not None and entry["opp"] != opponent:
                status = "excluded_opponent_mismatch"
        item = {**forecast, "evaluation_status": status, "evaluation_reason": reason,
                "actual": outcome.get("actual") if outcome and status == "resolved" else None,
                "outcome_snapshot_sha256": outcome.get("outcome_snapshot_sha256") if outcome else None,
                "selected_outcome_provenance": outcome.get("selected_outcome_provenance") if outcome else None,
                "selected_outcome_provenance_sha256": outcome.get("selected_outcome_provenance_sha256") if outcome else None,
                "outcome_observations": outcome.get("outcome_observations", []) if outcome else [],
                "outcome_source_mix": outcome.get("outcome_source_mix") if outcome else None,
                "outcome_conflict": outcome.get("outcome_conflict", False) if outcome else False,
                "outcome_revision": outcome.get("outcome_revision", False) if outcome else False,
                "outcome_identity_status": outcome.get("outcome_identity_status") if outcome else None,
                "forecast_opponent_recorded": "opponent" in forecast or "opp" in forecast,
                "week_confirmed_complete": outcome.get("week_confirmed_complete", False) if outcome else False,
                "week_completion_snapshot_sha256": outcome.get("week_completion_snapshot_sha256", []) if outcome else []}
        statuses[status] += 1
        detail.append(item)
        if status == "resolved":
            actual = item["actual"]
            finite(actual, "reception outcome", optional=False)
            if actual < 0 or int(actual) != actual:
                raise IntegrityError("Invalid reception count outcome")
            item["absolute_error_delta_candidate_minus_raw"] = abs(item["candidate_projection"] - actual) - abs(item["raw_projection"] - actual)
            item["absolute_error_delta_candidate_minus_unchanged"] = abs(item["candidate_projection"] - actual) - abs(item["adjusted_projection"] - actual)
            resolved.append(item)
    coverage["unique_opportunities"] = len(chosen)
    by_week = defaultdict(list)
    for row in detail:
        by_week[(row["season"], row["week"])].append(row)
    weeks = [{"season": season, "week": week,
              "metrics": _scores([r for r in rows if r["evaluation_status"] == "resolved"]),
              "sample_context": _context([r for r in rows if r["evaluation_status"] == "resolved"]),
              "forecast_context": _context(rows),
              "outcome_status": dict(Counter(r["evaluation_status"] for r in rows))}
             for (season, week), rows in sorted(by_week.items())]
    # Retain the registered uncertainty settings without modifying its original
    # experiment. Reuse its implementation separately for each comparison, then
    # label the transformed statistic according to its actual new meaning.
    registered_policy = load_json(ROOT / "config/evaluation-policy.json")
    policy = registered_policy if policy is None else policy
    if policy.get("uncertainty") != registered_policy["uncertainty"]:
        raise IntegrityError("Registered uncertainty rules changed")
    uncertainty = {}
    for role, field in (("raw_sleeper", "raw_projection"), ("unchanged_website", "adjusted_projection")):
        pairs = [{**r, "raw_projection": r[field], "adjusted_projection": r["candidate_projection"]} for r in resolved]
        interval = cluster_interval(pairs, policy)
        interval["completed_week_mae_delta_candidate_minus_comparator"] = interval.pop("completed_week_mae_delta_clone_minus_raw")
        interval["comparator"] = role
        interval["scope"] = "DESCRIPTIVE_CANDIDATE_COMPARISON_NOT_ORIGINAL_PROMOTION_EXPERIMENT"
        uncertainty[role] = interval
    for field in ("unique_candidate_receipts", "duplicate_candidate_receipts", "eligible_capture_rows",
                  "repeated_capture_rows", "unique_opportunities"):
        coverage.setdefault(field, 0)
    return {"schema_version": "point-candidate-evaluation-v1", "season": WINDOW_SEASON, "week": WINDOW_WEEKS[0],
            "candidate_id": CANDIDATE_ID, "protocol_version": PROTOCOL_VERSION,
            "registration_sha256": digest(registration), "model_code_sha256": registration["model_code_sha256"],
            "generated_at": stamp(now), "window": copy.deepcopy(registration["protocol"]["window"]),
            "status": "NOT_RECORDED" if not chosen else "DESCRIPTIVE_ONLY_NO_IMPROVEMENT_ESTABLISHED",
            "coverage": {**dict(coverage), "excluded": dict(exclusions)}, "outcome_status": dict(statuses),
            "sample_context": _context(resolved), "forecast_context": _context(detail),
            "categories": {"rec": _scores(resolved)}, "weekly": weeks,
            "season_to_date": _scores(resolved), "cumulative": _scores(resolved),
            "uncertainty": uncertainty, "rows": detail, "recording_operational": False,
            "production_enabled": False, "predictive_improvement_established": False,
            "probability_accuracy": "NOT_PROVIDED_POINT_CANDIDATE", "profitability": "UNAVAILABLE"}


def _receipt(path):
    path = Path(path)
    payload = read(path)
    if path.name != digest(payload) + ".json.gz":
        raise IntegrityError("Receipt filename digest mismatch")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register", help="Freeze current code/protocol locally; no collection")
    register.add_argument("--output-root", type=Path, required=True)
    register.add_argument("--source-commit")
    capture = sub.add_parser("capture", help="Calculate from a saved original receipt now, offline")
    capture.add_argument("--output-root", type=Path, required=True)
    capture.add_argument("--registration", type=Path, required=True)
    capture.add_argument("--baseline", type=Path, required=True)
    capture.add_argument("--code-commit")
    capture.add_argument("--mode", choices=MODES, default="prospective")
    evaluation = sub.add_parser("evaluate", help="Describe saved common triples and saved outcomes")
    evaluation.add_argument("--output-root", type=Path, required=True)
    evaluation.add_argument("--registration", type=Path, required=True)
    evaluation.add_argument("--baseline", type=Path, action="append", default=[])
    evaluation.add_argument("--candidate", type=Path, action="append", default=[])
    evaluation.add_argument("--outcome", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    if args.output_root.resolve().is_relative_to(ROOT.resolve()):
        parser.error("Offline validation output must be outside the source repository")
    if args.command == "register":
        payload = make_registration(engine_hashes(ROOT), source_commit=args.source_commit)
        # Store the strict semantic document without unrelated lane metadata.
        from reliability import immutable_write
        path = args.output_root / "data/verification/point-candidates/registrations" / (digest(payload) + ".json.gz")
        immutable_write(path, payload)
    elif args.command == "capture":
        registration = _receipt(args.registration)
        validate_registration(registration, engine_hashes(ROOT))
        path = capture_candidate(args.output_root, _receipt(args.baseline), registration,
                                 mode=args.mode, code_commit=args.code_commit)
    else:
        registration = _receipt(args.registration)
        validate_registration(registration, engine_hashes(ROOT))
        payload = evaluate([_receipt(p) for p in args.candidate], [_receipt(p) for p in args.baseline],
                           [_receipt(p) for p in args.outcome], registration,
                           policy=load_json(ROOT / "config/evaluation-policy.json"))
        path = write(args.output_root, "point_candidate_reports", payload)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
