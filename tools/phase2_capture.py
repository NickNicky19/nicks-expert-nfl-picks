"""Baseline receipt -> contemporaneous shadow -> offers -> outcomes -> scorecard.

Live CLI uses the actual clock. Replay writes only separate evidence lanes.
No branch update, website deployment or production-model promotion occurs here.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re

from evidence import read, write
from offers import capture_offers
import point_challenger
from release_mode import read_mode, read_phase2
from reliability import IntegrityError, atomic_json, capture, digest, engine_hashes, load_json, stamp, utc
from scorecard import build_scorecard, identity, latest_outcomes
from scoring import CATEGORIES
from selection_publication import all_ten_outcome_identities, publish_selection_report
from shadow import evaluate, make_shadow
from verify import require_offline

ROOT = Path(__file__).resolve().parents[1]
REC_HALF_REGISTRATION_SHA256 = "0ffd81a0d2708418d1d1b072cf9ce7750f42c554f04c2456f2a5206be199e0c6"


def _point_location(root, path, lane):
    """Keep supported evidence paths in their original, nonsymlinked lane."""
    root, path = Path(root).resolve(), Path(path)
    if not path.is_absolute():
        path = root / path
    directory = root / "data" / lane
    try:
        parts = path.relative_to(directory).parts
        if (len(parts) != 3 or not re.fullmatch(r"[0-9]{4}", parts[0])
                or not re.fullmatch(r"w(?:0[1-9]|1[0-8])", parts[1])
                or not re.fullmatch(r"[0-9a-f]{64}\.json\.gz", parts[2])
                or not path.resolve().is_relative_to(directory.resolve())):
            raise IntegrityError("Invalid point-candidate evidence location")
        for parent in (path, *path.parents):
            if parent == root:
                break
            if parent.is_symlink():
                raise IntegrityError("Refusing symlink point-candidate evidence")
        return path, int(parts[0]), int(parts[1][1:])
    except ValueError as err:
        raise IntegrityError("Point-candidate evidence is outside its lane") from err


def read_native_baseline(path, root=ROOT, *, expected_hashes=None, now=None):
    """Read the original v1 filename contract, without renaming a receipt.

    This checks saved local baseline integrity. The updater separately requires
    exact-root original-input verification before creating this native file.
    It is not independent source authentication or proof of public publication.
    """
    now = utc(now or datetime.now(timezone.utc))
    expected_hashes = engine_hashes(Path(root)) if expected_hashes is None else expected_hashes
    path, season, week = _point_location(root, path, "forward")
    payload = read(path)
    try:
        if (payload["schema_version"] != "baseline-capture-v1"
                or payload["model"] != point_challenger.BASELINE_MODEL or payload["mode"] != "live"
                or payload["engine_files"] != expected_hashes
                or payload["engine_sha256"] != digest(expected_hashes)
                or not isinstance(payload["input_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", payload["input_sha256"])):
            raise IntegrityError("Unsupported native baseline schema/model/mode/engine")
        native_identity = digest({"data": payload["input_sha256"],
                                  "engine": payload["engine_sha256"], "mode": payload["mode"]})
        if path.name != native_identity + ".json.gz":
            raise IntegrityError("Native baseline filename digest mismatch")
        if not utc(payload["forecast_generated_at"]) <= utc(payload["captured_at"]) <= now:
            raise IntegrityError("Invalid native baseline generation/capture clocks")
        if not isinstance(payload["rows"], list):
            raise IntegrityError("Malformed native baseline population")
        seen = set()
        for row in payload["rows"]:
            if (type(row["season"]) is not int or type(row["week"]) is not int
                    or (row["season"], row["week"]) != (season, week)
                    or row["category"] not in CATEGORIES
                    or any(not isinstance(row.get(key), str) or not row[key].strip()
                           for key in ("game_id", "player_id", "team"))):
                raise IntegrityError("Invalid native baseline opportunity identity")
            utc(row["kickoff"])
            key = identity(row)
            if key in seen:
                raise IntegrityError("Duplicate native baseline opportunity")
            seen.add(key)
        return payload
    except (KeyError, TypeError, AttributeError) as err:
        raise IntegrityError("Malformed native baseline receipt") from err


def _point_registration(root, now):
    path = Path(root) / "tools/rec_half_registration_v1.json"
    if path.is_symlink() or path.parent.is_symlink():
        raise IntegrityError("Refusing symlink candidate registration")
    if not path.exists():
        return None
    registration = load_json(path)
    if digest(registration) != REC_HALF_REGISTRATION_SHA256:
        raise IntegrityError("Official fixed candidate registration digest mismatch")
    point_challenger.validate_registration(registration, engine_hashes(Path(root)), now=now)
    return registration


def _point_receipt(root, path, lane):
    path, season, week = _point_location(root, path, lane)
    payload = read(path)
    if (not isinstance(payload, dict) or path.name != digest(payload) + ".json.gz"
            or type(payload.get("season")) is not int or type(payload.get("week")) is not int
            or (payload["season"], payload["week"]) != (season, week)):
        raise IntegrityError("Point-candidate evidence filename/period mismatch")
    return payload


def _write_point_receipt(root, lane, payload):
    expected = (Path(root) / "data" / lane / str(payload["season"])
                / f"w{payload['week']:02d}" / (digest(payload) + ".json.gz"))
    _point_location(root, expected, lane)
    path = write(root, lane, payload)
    if _point_receipt(root, path, lane) != payload:
        raise IntegrityError("Point-candidate evidence readback mismatch")
    return path


def _point_candidate_report(root):
    """Evaluate saved native files; no calculation, provider request or backfill."""
    now = datetime.now(timezone.utc)
    registration = _point_registration(root, now)
    if registration is None:
        return None, None
    hashes = engine_hashes(Path(root))
    baselines = [read_native_baseline(path, root, expected_hashes=hashes, now=now)
                 for path in sorted((Path(root) / "data/forward").rglob("*.json.gz"))]
    candidate_root = Path(root) / "data/verification/point-candidates"
    candidates = [_point_receipt(root, path, "verification/point-candidates")
                  for path in sorted(candidate_root.glob("[0-9][0-9][0-9][0-9]/w[0-9][0-9]/*.json.gz"))]
    outcomes = [_point_receipt(root, path, "outcomes")
                for path in sorted((Path(root) / "data/outcomes").rglob("*.json.gz"))]
    report = point_challenger.evaluate(candidates, baselines, outcomes, registration, now=now,
                                      policy=load_json(Path(root) / "config/evaluation-policy.json"))
    path = _write_point_receipt(root, "verification/point-candidate-reports", report)
    return report, path


def _point_summary(report):
    """Whitelist aggregate comparison fields; retain rich rows only as evidence."""
    def fields(value, names):
        return {name: value[name] for name in names if name in value}

    def context(value):
        return fields(value, ("rows", "unique_players", "unique_games", "unique_weeks"))

    def scores(value):
        result = {role: fields(value[role], ("n", "mae", "rmse", "mean_error"))
                  for role in ("raw_sleeper", "unchanged_website", "candidate")}
        result.update(fields(value, ("paired_mae_delta_candidate_minus_raw_sleeper",
                                     "paired_rmse_delta_candidate_minus_raw_sleeper",
                                     "paired_mae_delta_candidate_minus_unchanged_website",
                                     "paired_rmse_delta_candidate_minus_unchanged_website")))
        return result

    statuses = ("resolved", "pending", "unresolved", "dnp", "void", "missing_outcome",
                "excluded_schedule_changed", "excluded_team_mismatch", "excluded_opponent_mismatch")
    result = fields(report, ("candidate_id", "protocol_version", "registration_sha256",
                             "model_code_sha256", "generated_at", "status", "recording_operational",
                             "production_enabled", "predictive_improvement_established",
                             "probability_accuracy", "profitability"))
    result["schema_version"] = "point-candidate-evaluation-summary-v1"
    result["source_report_schema_version"] = report["schema_version"]
    result["report_payload_sha256"] = digest(report)
    result["window"] = fields(report["window"], ("season", "weeks", "first_kickoff",
                                                   "first_kickoffs_by_week", "shift_or_extension_allowed",
                                                   "schedule_changes"))
    result["coverage"] = fields(report["coverage"], ("unique_candidate_receipts", "duplicate_candidate_receipts",
                                                       "eligible_capture_rows", "repeated_capture_rows",
                                                       "unique_opportunities"))
    result["coverage"]["excluded"] = fields(report["coverage"]["excluded"], (
        "source_not_pregame", "outside_fixed_window", "calculation_not_pregame", "missing_pair",
        "development_descriptive_rows"))
    result["outcome_status"] = fields(report["outcome_status"], statuses)
    for name in ("sample_context", "forecast_context"):
        result[name] = context(report[name])
    result["categories"] = {"rec": scores(report["categories"]["rec"])}
    for name in ("season_to_date", "cumulative"):
        result[name] = scores(report[name])
    result["weekly"] = [{**fields(week, ("season", "week")), "metrics": scores(week["metrics"]),
                         "sample_context": context(week["sample_context"]),
                         "forecast_context": context(week["forecast_context"]),
                         "outcome_status": fields(week["outcome_status"], statuses)} for week in report["weekly"]]
    uncertainty_fields = ("completed_weeks", "observed_week_clusters", "resampled_week_clusters",
                          "resampled_outcomes", "excluded_incomplete_week_clusters", "excluded_incomplete_outcomes",
                          "cluster", "interval_population", "completed_week_mae_delta_candidate_minus_comparator",
                          "status", "confidence", "interval", "comparator", "scope")
    result["uncertainty"] = {role: fields(report["uncertainty"][role], uncertainty_fields)
                             for role in ("raw_sleeper", "unchanged_website")}
    return result


def run_point_candidate(root, baseline_path, *, baseline_created, code_commit=None, evaluate_saved=True):
    """Supported native-file integration; the frozen standalone CLI is separate.

    The updater calls this immediately after verified original baseline capture.
    `baseline_created` is its actual create-only result, never a replay override.
    A retry may reuse a recorded candidate, but cannot backfill a missed one.
    """
    root = Path(root).resolve()
    if type(baseline_created) is not bool:
        raise IntegrityError("Candidate recording requires the actual baseline create result")
    now = datetime.now(timezone.utc)
    baseline = read_native_baseline(baseline_path, root, now=now)
    registration = _point_registration(root, now)
    status = {"status": "NOT_CONFIGURED", "registration_sha256": None,
              "candidate_receipt": None, "candidate_payload_sha256": None, "report_receipt": None,
              "continuous_recording_operational": False, "production_enabled": False,
              "hook_version": "rec-half-updater-v1", "original_standalone_cli": "CLI-01_NOT_CORRECTED"}
    if registration is None:
        return None, status
    status["registration_sha256"] = digest(registration)
    baseline_sha = digest(baseline)
    matches = []
    # Candidate payloads have their own generic content-addressed names. Only
    # original baseline receipts use the schema-specific filename above.
    _, season, week = _point_location(root, baseline_path, "forward")
    directory = root / "data/verification/point-candidates" / str(season) / f"w{week:02d}"
    for path in sorted(directory.glob("*.json.gz")):
        payload = _point_receipt(root, path, "verification/point-candidates")
        if payload.get("baseline_payload_sha256") == baseline_sha and payload.get("mode") == "prospective":
            point_challenger.validate_candidate(payload, baseline, registration, now=now)
            matches.append((path, payload))
    if len(matches) > 1:
        raise IntegrityError("Multiple candidate recordings for one original observation")
    if matches:
        path, payload = matches[0]
        status["status"] = "REUSED_FIRST_RECORDING"
    elif not baseline_created:
        path, payload = None, None
        status["status"] = "MISSED_NOT_BACKFILLED"
    elif not any(row["category"] == "rec" and row["season"] == point_challenger.WINDOW_SEASON
                 and row["week"] in point_challenger.WINDOW_WEEKS for row in baseline["rows"]):
        path, payload = None, None
        status["status"] = "OUTSIDE_FIXED_WINDOW"
    elif utc(baseline["captured_at"]) <= utc(registration["registered_at"]):
        path, payload = None, None
        status["status"] = "PRIOR_REGISTRATION_OBSERVATION"
    else:
        # The retained direct API samples real start and completion clocks and
        # excludes every calculation completed at or after the saved kickoff.
        payload = point_challenger.make_candidate(baseline, registration, mode="prospective", code_commit=code_commit)
        path = _write_point_receipt(root, "verification/point-candidates", payload)
        status["status"] = "RECORDED" if payload["rows"] else "RECORDED_NO_ELIGIBLE_RECEPTIONS"
    if path is not None:
        status["candidate_receipt"] = path.relative_to(root).as_posix()
        status["candidate_payload_sha256"] = digest(payload)
    report, report_path = _point_candidate_report(root) if evaluate_saved else (None, None)
    if report_path is not None:
        status["report_receipt"] = report_path.relative_to(root).as_posix()
    return report, status


def probability_report(root, policy, mode="live", include_registry=True):
    forecast_lane = "forward" if mode == "live" else "replay"
    shadow_lane = "shadow" if mode == "live" else "shadow_replay"
    outcome_lane = "outcomes" if mode == "live" else "outcomes_replay"
    shadows = [read(p) for p in (root / "data" / shadow_lane).rglob("*.json.gz")]
    baselines = [read(p) for p in (root / "data" / forecast_lane).rglob("*.json.gz")]
    outcomes = latest_outcomes([read(p) for p in (root / "data" / outcome_lane).rglob("*.json.gz")], mode == "replay")
    report = evaluate(shadows, baselines, outcomes, policy, allow_replay=mode == "replay")
    if include_registry:
        report["retained_versions"] = {}
        for path in sorted((root / "config/policies").glob("*.json")):
            old_policy = load_json(path)
            if digest(old_policy) != digest(policy):
                report["retained_versions"][old_policy["challenger"]["version"]] = evaluate(
                    shadows, baselines, outcomes, old_policy, allow_replay=mode == "replay")
    return report


def run_capture(root=ROOT, mode="live", replay_at=None):
    root = Path(root).resolve()
    if mode not in ("live", "replay") or (mode == "live" and replay_at is not None):
        raise IntegrityError("Live capture cannot use a supplied clock")
    if read_mode(root) != "phase1" or not read_phase2(root):
        raise IntegrityError("Phase 2 capture is disabled by recovery mode")
    data = load_json(root / "output/data/week.json")
    pointer = load_json(root / "output/data/matchup-proof.json")
    policy = load_json(root / "config/evaluation-policy.json")
    rules = load_json(root / "config/sleeper-rules-provenance.json")
    now = utc(replay_at) if replay_at else datetime.now(timezone.utc)
    verification = require_offline(root, data, pointer, mode, now)
    inputs = verification["inputs"]
    observation = dict(inputs["offer_observation"], mode=mode)
    if utc(observation["collected_at"]) > now:
        raise IntegrityError("Offer collection time is in the future")
    if utc(policy["registered_at"]) > now:
        raise IntegrityError("Evaluation policy was not registered before capture")
    offer_payload = capture_offers(data, observation, inputs["projection_metadata"], rules)
    # Validation itself takes time. A live capture cannot backdate its clock to
    # the start of preflight, including when a game starts during that check.
    now = now if mode == "replay" else datetime.now(timezone.utc)
    baseline_path, health = capture(data, load_json(root / "output/data/meta.json"), root,
                                    now, engine_hashes(root), mode=mode)
    baseline = read(baseline_path)
    check_path = write(root, "verification/matchup-checks" if mode == "live" else "matchup_checks_replay", {
        "schema_version": "matchup-verification-v1", "season": data["season"], "week": data["week"],
        "mode": mode, "verified_at": stamp(now), "output_sha256": digest(data),
        "engine_files": inputs["engine_files"], "latest_inputs": pointer["latest_inputs"],
        "latest_inputs_sha256": digest(inputs), "game_origins": pointer["game_origins"],
        "checked_factors": verification["checked_factors"],
        "baseline_receipt": baseline_path.relative_to(root).as_posix(), "baseline_payload_sha256": digest(baseline),
        "scope": "LOCAL_ORIGINAL_INPUT_REPRODUCTION_PUBLICATION_AND_PROVIDER_ASOF_NOT_VERIFIED"})
    # Record a genuinely new candidate before shadow/outcome/report work can
    # consume its remaining pregame time. Saved evaluation follows statistics.
    point_status = None
    if mode == "live":
        _, point_status = run_point_candidate(root, baseline_path,
                                              baseline_created=health["capture_created"],
                                              code_commit=os.environ.get("GITHUB_SHA"), evaluate_saved=False)
    shadow_path = None
    if health["capture_created"]:
        payload = make_shadow(baseline, inputs, policy, now, code_commit=os.environ.get("GITHUB_SHA"))
        completed = utc(replay_at) if replay_at else datetime.now(timezone.utc)
        # Never call a calculation completed after kickoff a prospective forecast.
        payload["rows"] = [r for r in payload["rows"] if utc(r["kickoff"]) > completed]
        payload["calculation_completed_at"] = stamp(completed)
        shadow_path = write(root, "shadow" if mode == "live" else "shadow_replay", payload)
    offer_path = write(root, "offers" if mode == "live" else "offers_replay", offer_payload)
    additional_coverage = {}
    additional = all_ten_outcome_identities(root, now, coverage=additional_coverage) if mode == "live" else None
    report, _ = build_scorecard(root, now, mode=mode, allow_replay=mode == "replay",
                               additional_outcome_pairs=additional)
    report["shadow"] = probability_report(root, policy, mode)
    report["offers"] = {"coverage": offer_payload["coverage"], "collected_at": observation["collected_at"],
                        "source_status": offer_payload["source_status"], "complete_executable_entries": 0,
                        "quote_freshness": "NOT_ESTABLISHED"}
    health["phase2"] = {"matchup_verification_receipt": check_path.relative_to(root).as_posix(),
                        "shadow_receipt": shadow_path.relative_to(root).as_posix() if shadow_path else None,
                        "shadow_retry": "new_forecast" if shadow_path else "existing_baseline_not_backdated",
                        "offer_receipt": offer_path.relative_to(root).as_posix(),
                        "production_model": policy["baseline"], "offer_coverage": offer_payload["coverage"],
                        "unique_forecast_opportunities": report["coverage"]["unique_opportunities"]}
    if mode == "live":
        point_report, point_report_path = _point_candidate_report(root)
        if point_report is not None:
            report["point_candidate"] = _point_summary(point_report)
            point_status["report_receipt"] = point_report_path.relative_to(root.resolve()).as_posix()
        health["phase2"]["point_candidate"] = point_status
        health["phase2"]["selection_outcome_identity_coverage"] = additional_coverage
        publication = publish_selection_report(root, now)
        health["phase2"]["selection_report_sha256"] = publication["report_id"]
        health["phase2"]["selection_report_generated_at"] = publication["generated_at"]
        atomic_json(root / "output/data/forecast-scorecard.json", report)
        atomic_json(root / "output/data/offer-capture.json", report["offers"])
        atomic_json(root / "output/data/health.json", health)
    else:
        write(root, "replay_reports", {"season": data["season"], "week": data["week"], "mode": "replay", "report": report})
    return report, health


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("live", "replay"), required=True)
    parser.add_argument("--replay-at")
    args = parser.parse_args()
    if args.mode == "live" and args.replay_at:
        parser.error("Live capture cannot use a supplied clock")
    report, health = run_capture(mode=args.mode, replay_at=args.replay_at)
    print({"baseline_receipt": health["receipt"], "phase2": health["phase2"], "outcomes": report["outcome_status"]})


if __name__ == "__main__":
    main()
