"""Baseline receipt -> contemporaneous shadow -> offers -> outcomes -> scorecard.

Live CLI uses the actual clock. Replay writes only separate evidence lanes.
No branch update, website deployment or production-model promotion occurs here.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from evidence import read, write
from offers import capture_offers
import point_challenger
from release_mode import read_mode, read_phase2
from reliability import canonical, IntegrityError, atomic_json, capture, digest, engine_hashes, load_json, stamp, utc
from scorecard import build_scorecard, identity, latest_outcomes
from scoring import CATEGORIES
import selection_publication as publication
from selection_publication import all_ten_outcome_identities, publish_selection_report
from shadow import evaluate, make_shadow
from verify import require_offline
import data_integrity_v2 as corrected
import partial_week
from source_evidence import record_scoreboard

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
    path, season, week = _point_location(root, path, "forward")
    payload = read(path)
    modern = payload.get("schema_version") == corrected.NATIVE
    if modern:
        recognized = corrected.native_contract(payload)
        if expected_hashes is not None and expected_hashes != recognized:
            raise IntegrityError("Wrong explicitly requested corrected engine")
        expected_hashes = recognized
    elif expected_hashes is None:
        expected_hashes = corrected.legacy_engine_hashes()
    try:
        if (payload["schema_version"] != (corrected.NATIVE if modern else "baseline-capture-v1")
                or payload["model"] != (corrected.MODEL if modern else point_challenger.BASELINE_MODEL) or payload["mode"] != "live"
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
    point_challenger.validate_registration(registration, corrected.legacy_engine_hashes(), now=now)
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
    hashes = corrected.legacy_engine_hashes()
    baselines = []
    for path in sorted((Path(root) / "data/forward").rglob("*.json.gz")):
        native = read_native_baseline(path, root, now=now)
        if native["schema_version"] == "baseline-capture-v1" and native["engine_files"] == hashes:
            baselines.append(native)
    candidate_root = Path(root) / "data/verification/point-candidates"
    candidates = [_point_receipt(root, path, "verification/point-candidates")
                  for path in sorted(candidate_root.glob("[0-9][0-9][0-9][0-9]/w[0-9][0-9]/*.json.gz"))]
    outcomes = [_point_receipt(root, path, "outcomes")
                for path in sorted((Path(root) / "data/outcomes").rglob("*.json.gz"))]
    outcomes = [payload for payload in outcomes if payload.get("schema_version") == "forecast-outcomes-v1"]
    policy = load_json(Path(root) / "config/evaluation-policy.json")
    # The unchanged candidate module's default ROOT is part of its V1 contract.
    # A corrected source never lends it a changed root under an original label.
    if (Path(root) / "pull/build.py").is_file() and hashlib.sha256((Path(root) / "pull/build.py").read_bytes()).hexdigest() == corrected.V2_SOURCE_SHA256["pull/build.py"]:
        report = corrected.legacy_candidate_evaluation(candidates, baselines, outcomes, registration, policy, now)
    else:
        report = point_challenger.evaluate(candidates, baselines, outcomes, registration, now=now, policy=policy)
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
    legacy_hashes = corrected.legacy_engine_hashes()
    baselines = [p for p in baselines if p.get("schema_version") == "baseline-capture-v1"
                 and p.get("model") == point_challenger.BASELINE_MODEL and p.get("engine_files") == legacy_hashes
                 and p.get("engine_sha256") == digest(legacy_hashes)]
    outcomes = latest_outcomes([p for path in (root / "data" / outcome_lane).rglob("*.json.gz")
                               if (p := read(path)).get("schema_version") == "forecast-outcomes-v1"], mode == "replay")
    report = evaluate(shadows, baselines, outcomes, policy, allow_replay=mode == "replay")
    if include_registry:
        report["retained_versions"] = {}
        for path in sorted((root / "config/policies").glob("*.json")):
            old_policy = load_json(path)
            if digest(old_policy) != digest(policy):
                report["retained_versions"][old_policy["challenger"]["version"]] = evaluate(
                    shadows, baselines, outcomes, old_policy, allow_replay=mode == "replay")
    for diagnostic in (report, *report.get("retained_versions", {}).values()):
        diagnostic.update(qualification="KNOWN_UNGUARDED_JOIN / NOT_CERTIFIED", qualified_accuracy=False,
                          completed_week_qualification=False, promotion_eligible=False)
    return report


def _closing_status(data):
    # Existing supported scoreboard path; this response and actual clock are
    # required source evidence, not a new provider or background collector.
    import sources
    params = {"dates": data["season"], "seasontype": 2, "week": data["week"]}
    response = sources.get_json(sources.ESPN + "/scoreboard", params)
    return record_scoreboard(response, params, datetime.now(timezone.utc), mode="live")


def _initial_board(root, spec):
    # Full-history checkout is already required by the serial updater. Keep the
    # approved historical board retrievable; a current board is no substitute.
    name = spec.get("initial_board_receipt")
    if name:
        return partial_week._saved(root, name, "verification/partial-plan-boards")["board"]
    raw = subprocess.check_output(["git", "-C", str(root), "show",
                                   spec["plan"]["initial_data_pin"] + ":output/data/week.json"])
    from writer_gate import strict_json
    return strict_json(raw.decode("utf-8"))


def public_scorecard(report, data, source_sha):
    """Versioned aggregate only. The intact rich report remains in verification."""
    def counts(value):
        if not isinstance(value, dict) or any(type(n) is not int or n < 0 for n in value.values()):
            raise IntegrityError("Invalid public scorecard counts")
        return dict(value)
    categories = {}
    for category in ("rec", "rush_att", "pass_yd"):
        values = report.get("categories", {}).get(category, {})
        categories[category] = {}
        for model in ("raw_sleeper", "unchanged_clone"):
            metrics = {key: values.get(model, {}).get(key) for key in ("n", "mae", "rmse", "mean_error")}
            if metrics["n"] is None:
                metrics = {"n": 0, "mae": None, "rmse": None, "mean_error": None}
            if type(metrics["n"]) is not int or metrics["n"] < 0:
                raise IntegrityError("Invalid public metric sample")
            for key in ("mae", "rmse", "mean_error"):
                value = metrics[key]
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                          or key != "mean_error" and value < 0):
                    raise IntegrityError("Invalid public metric")
            digest(metrics)  # nonfinite values fail
            categories[category][model] = metrics
    coverage = {key: report.get("coverage", {}).get(key, 0) for key in
                ("paired_capture_rows", "unique_opportunities", "repeated_capture_rows")}
    counts(coverage)
    coverage["excluded"] = counts(report.get("coverage", {}).get("excluded", {}))
    return {"schema_version": "forecast-scorecard-public-summary-v1", "source_sha": source_sha,
            "source_report_schema_version": report.get("schema_version"), "report_sha256": digest(report),
            "board_sha256": digest(data), "policy_version": report.get("policy_version"),
            "coverage": coverage, "outcome_status": counts(report.get("outcome_status", {})),
            "categories": categories,
            "scope": "REGISTERED_THREE_TARGET_COMPARISON_SEPARATE_FROM_SELECTION_FILTERS",
            "limitations": ["Descriptive aggregate; no predictive improvement or financial return established.",
                             "Original full-board Week 6 proof remains incomplete."]}


def _verification_route(config, data, at):
    if config.get("verification_mode") != corrected.VALIDATOR:
        return partial_week.dispatch(config, data, at)
    if config.get("production_model") != corrected.MODEL or config.get("experimental_recording_enabled") is not False:
        raise IntegrityError("Corrected dispatch requires its explicit model and inactive recorders")
    corrected.validate_plan(config.get("partial_week", {}), data, at)
    return corrected.VALIDATOR


def _run_capture(root=ROOT, mode="live", replay_at=None, *, source_sha=None, initial_board=None, _checked=None):
    _checked = {} if _checked is None else _checked
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
    config = load_json(root / "config/phase2.json")
    route = _verification_route(config, data, now) if mode == "live" else "strict"
    scope = completion_path = None
    if route == corrected.VALIDATOR:
        spec = config["partial_week"]
        registration, _ = corrected.register_plan(root, spec, now, source_sha=source_sha, initial_board=initial_board)
        closing = _closing_status(data)
        baseline_path, health, completion_path, scope = corrected.record_bundle(
            root, data, pointer, closing, spec, registration.relative_to(root).as_posix(),
            clock=lambda: datetime.now(timezone.utc))
        verification = {"inputs": corrected.recorded_inputs(root, pointer["latest_inputs"], data["season"], data["week"],
                         mode="live", observed_at=datetime.now(timezone.utc)), "checked_factors": scope["checked_factors"]}
    elif route == "partial":
        spec = config["partial_week"]
        registration, _ = partial_week.register_plan(root, spec, now, source_sha=source_sha,
                                                      initial_board=initial_board)
        closing = _closing_status(data)
        baseline_path, health, completion_path, scope = partial_week.record_bundle(
            root, data, pointer, closing, spec, registration.relative_to(root).as_posix(),
            read_native_baseline, clock=lambda: datetime.now(timezone.utc))
        verification = {"inputs": partial_week.verify.recorded_inputs(
            root, pointer["latest_inputs"], data["season"], data["week"], engine_hashes(root),
            mode="live", observed_at=datetime.now(timezone.utc)), "checked_factors": scope["checked_factors"]}
    else:
        verification = corrected.legacy_offline(root, data, pointer, mode, now)
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
    if route not in ("partial", corrected.VALIDATOR):
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
    if mode == "live":
        import selection_strategies
        selection_strategies.record(root, {
            "verification_mode": route, "board_sha256": digest(data), "proof": pointer,
            "matchup_check_receipt": check_path.relative_to(root).as_posix(),
            "native_receipt": baseline_path.relative_to(root).as_posix(), "native_payload_sha256": digest(baseline),
            "partial_completion_receipt": completion_path.relative_to(root).as_posix() if completion_path else None,
            "partial_completion_payload_sha256": digest(read(completion_path)) if completion_path else None}, source_sha, clock=lambda: datetime.now(timezone.utc))
        # Reporting observes genuinely completed selections, not the earlier
        # native capture clock. Original input/native clocks stay unchanged.
        now = datetime.now(timezone.utc)
    # Record a genuinely new candidate before shadow/outcome/report work can
    # consume its remaining pregame time. Saved evaluation follows statistics.
    experimental = config.get("experimental_recording_enabled", True)
    if type(experimental) is not bool:
        raise IntegrityError("Experimental recording needs an explicit boolean")
    point_status = {"status": "INACTIVE_OWNER_ACTIVATION_REQUIRED", "continuous_recording_operational": False,
                    "production_enabled": False, "registration_unchanged": True}
    if mode == "live" and experimental:
        _, point_status = run_point_candidate(root, baseline_path,
                                              baseline_created=health["capture_created"],
                                              code_commit=os.environ.get("GITHUB_SHA"), evaluate_saved=False)
    shadow_path = None
    if baseline.get("schema_version") == "baseline-capture-v1" and health["capture_created"] and (mode == "replay" or experimental):
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
                        "production_model": baseline["model"], "offer_coverage": offer_payload["coverage"],
                        "unique_forecast_opportunities": report["coverage"]["unique_opportunities"]}
    if mode == "live":
        point_report, point_report_path = _point_candidate_report(root)
        if point_report is not None:
            report["point_candidate"] = _point_summary(point_report)
            point_status["report_receipt"] = point_report_path.relative_to(root.resolve()).as_posix()
        health["phase2"]["point_candidate"] = point_status
        health["phase2"]["selection_outcome_identity_coverage"] = additional_coverage
        publication = publish_selection_report(root, now, source_sha=source_sha, _checked=_checked)
        health["phase2"]["selection_report_sha256"] = publication["report_id"]
        health["phase2"]["selection_report_generated_at"] = publication["generated_at"]
        rich = write(root, "verification/report-originals", {"schema_version": "rich-scorecard-evidence-v1",
                     "season": data["season"], "week": data["week"], "report": report,
                     "report_sha256": digest(report), "board_sha256": digest(data), "source_sha": source_sha})
        health["phase2"]["rich_scorecard_receipt"] = rich.relative_to(root).as_posix()
        health["phase2"]["verification_mode"] = route
        health["phase2"]["strict_full_board_verified"] = route == "strict"
        health["phase2"]["partial_completion_receipt"] = completion_path.relative_to(root).as_posix() if completion_path else None
        if scope is not None:
            scope_reader = corrected.public_scope if route == corrected.VALIDATOR else partial_week.public_scope
            atomic_json(root / "output/data/verification-scope.json", scope_reader(scope, read(completion_path)))
        else:
            atomic_json(root / "output/data/verification-scope.json", {
                "schema_version": "strict-full-board-public-scope-v1", "output_sha256": digest(data),
                "full_board_verified": True, "complete_week_qualified": False,
                "claim": "RETAINED_ORIGINAL_MODEL_INPUT_REPRODUCTION_ONLY"})
        atomic_json(root / "output/data/forecast-scorecard.json", public_scorecard(report, data, source_sha))
        atomic_json(root / "output/data/offer-capture.json", report["offers"])
        bindings = {name: hashlib.sha256((root / "output" / name).read_bytes()).hexdigest()
                    for name in ("app.js", "index.html") if (root / "output" / name).exists()}
        bindings.update({name: hashlib.sha256((root / "output" / name).read_bytes()).hexdigest() for name in
                         ("data/week.json", "data/meta.json", "data/verification-scope.json",
                          "data/forecast-scorecard.json", "data/selection-grading/latest.json")})
        generation = {"schema_version": "website-generation-v1", "source_sha": source_sha,
                      "board_sha256": digest(data), "bindings": bindings,
                      "baseline_payload_sha256": digest(baseline), "selection_report_id": publication["report_id"]}
        generation_id = digest(generation)
        health["generation_sha256"] = generation_id
        health["board_sha256"] = digest(data)
        health["source_sha"] = source_sha
        atomic_json(root / "output/data/release-identity.json", dict(generation, generation_sha256=generation_id))
        atomic_json(root / "output/data/health.json", health)
        finalize_hosting(root, now, _checked=_checked)
    else:
        write(root, "replay_reports", {"season": data["season"], "week": data["week"], "mode": "replay", "report": report})
    return report, health



# Public delivery metadata is separate from immutable original model evidence.
HOSTING_VERSION = "selection-hosting-working-set-v1"
MANIFEST_VERSION = "selection-hosting-generation-v1"
STAGING_BUDGET = 900_000_000  # Conservative published-file budget below Pages 1 GB.
PUBLIC_REPOSITORY = "NickNicky19/nicks-expert-nfl-picks"
HOST_SNAPSHOTS = ("app.js", "index.html", "data/week.json", "data/meta.json", "data/verification-scope.json",
                  "data/forecast-scorecard.json", "data/selection-grading/latest.json",
                  "data/health.json", "data/release-identity.json")


def _public_blob(base, name, raw, limit=publication.INDEX_LIMIT):
    if not 0 < len(raw) <= limit:
        raise IntegrityError("Hosting metadata/snapshot exceeds supported limit")
    sha = hashlib.sha256(raw).hexdigest()
    path = Path(base) / sha / name
    publication._no_symlinks(path, Path(base))
    from selection_report import _create_file
    _create_file(path, raw)
    return {"path": sha + "/" + name, "sha256": sha, "decoded_bytes": len(raw)}


def _public_read(base, descriptor, name, limit=publication.INDEX_LIMIT):
    if (not isinstance(descriptor, dict) or set(descriptor) != {"path", "sha256", "decoded_bytes"}
            or not publication.HEX.fullmatch(descriptor.get("sha256") or "")
            or descriptor.get("path") != descriptor["sha256"] + "/" + name):
        raise IntegrityError("Invalid immutable hosting descriptor")
    path = Path(base) / descriptor["path"]
    publication._no_symlinks(path, Path(base))
    return publication._read_asset_bytes(path, descriptor, limit)


def _dependency_closure(root):
    """Conservative fresh inventory: includes negative evidence and discovery.

    Never use filesystem clocks or a saved flag as evidence identity. Streaming
    hashing bounds memory even for originals larger than public-asset limits.
    """
    root = Path(root).resolve()
    corrected.dispatcher_identity()
    members = [("retained-approved-source-objects", digest(corrected.legacy_dependency_inventory(evidence_root=root)))]
    for lane in ("pull", "tools", "config", "data"):
        base = root / lane
        if not base.exists():
            members.append((lane, None))
            continue
        for path in sorted(base.rglob("*")):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.is_symlink():
                raise IntegrityError("Symlink validation dependency")
            if path.is_file():
                h = hashlib.sha256()
                with path.open("rb") as handle:
                    for block in iter(lambda: handle.read(65536), b""):
                        h.update(block)
                members.append((path.relative_to(root).as_posix(), h.hexdigest()))
    for name in ("week.json", "meta.json", "matchup-proof.json", "verification-scope.json", "game-status.json"):
        path = root / "output/data" / name
        if path.is_symlink():
            raise IntegrityError("Symlink board/proof dependency")
        members.append(("output/data/" + name, hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None))
    # Temporary runtime roots intentionally omit tools. The imported validator
    # and wrapper may therefore execute from another checkout; inventory those
    # actual source directories too, rather than trusting runtime HEAD or files.
    source_dirs = {Path(__file__).resolve().parent, Path(partial_week.__file__).resolve().parent,
                   Path(corrected.__file__).resolve().parent,
                   Path(publication.__file__).resolve().parent, Path(require_offline.__code__.co_filename).resolve().parent,
                   Path(__file__).resolve().parents[1] / "pull"}
    for directory in sorted(source_dirs):
        for path in sorted(directory.rglob("*")):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.is_symlink():
                raise IntegrityError("Symlink imported-source dependency")
            if path.is_file():
                members.append(("imported:" + str(path), hashlib.sha256(path.read_bytes()).hexdigest()))
    return digest(members)


def _strategy_qualification(root, qualification, cutoff, *, _checked=None):
    """Pin original forecast evidence; this does not select a new release plan."""
    from reliability import make_payload
    q = qualification; root = Path(root).resolve(); cutoff = utc(cutoff)
    fields = {"verification_mode", "board_sha256", "proof", "matchup_check_receipt", "native_receipt",
              "native_payload_sha256", "partial_completion_receipt", "partial_completion_payload_sha256"}
    if not isinstance(q, dict) or set(q) != fields or q["verification_mode"] not in ("strict", "partial", corrected.VALIDATOR):
        raise IntegrityError("Unsupported ranked qualification route")
    before = _dependency_closure(root)
    # Read the pinned content-addressed original, never today's mutable board.
    inputs = partial_week._saved(root, q["proof"]["latest_inputs"], "verification")
    board = inputs["week_data"]
    if digest(board) != q["board_sha256"] or q["proof"]["output_sha256"] != digest(board):
        raise IntegrityError("Ranked original board/proof mismatch")
    if q["verification_mode"] == "strict":
        if q["partial_completion_receipt"] is not None or q["partial_completion_payload_sha256"] is not None:
            raise IntegrityError("Strict ranked origin carries an incompatible completion")
        verified = corrected.legacy_offline(root, board, q["proof"], "live", cutoff)
        if verified["inputs"] != inputs:
            raise IntegrityError("Ranked strict original input differs")
        native = read_native_baseline(root / q["native_receipt"], root, now=cutoff)
        if native.get("schema_version") != "baseline-capture-v1" or native.get("model") != "original_sleeper_matchup_baseline":
            raise IntegrityError("Strict ranked origin requires the retained original model")
        if native["rows"] != make_payload(board, utc(native["captured_at"]), native["engine_files"], "live")["rows"]:
            raise IntegrityError("Ranked strict native rows differ from original board")
    else:
        completed = partial_week._saved(root, q["partial_completion_receipt"], partial_week.COMPLETION_LANE)
        scope = partial_week._saved(root, completed["scope_receipt"], "verification/partial-scopes")
        spec = corrected._saved_spec(root, scope)
        complete, reproduced, native = _qualified_bundle(root, q["partial_completion_receipt"], spec, {} if _checked is None else _checked)
        expected_schema = "partial-completion-data-integrity-v2" if q["verification_mode"] == corrected.VALIDATOR else partial_week.COMPLETION_VERSION
        if (complete.get("schema_version") != expected_schema or digest(complete) != q["partial_completion_payload_sha256"]
                or complete["baseline_receipt"] != q["native_receipt"] or utc(complete["evidence_completed_at"]) > cutoff
                or reproduced["proof"] != q["proof"] or reproduced["latest_inputs_sha256"] != digest(inputs)):
            raise IntegrityError("Ranked pinned completion/source/clock mismatch")
    check = partial_week._saved(root, q["matchup_check_receipt"], "verification/matchup-checks")
    if (check.get("schema_version") != "matchup-verification-v1" or check["mode"] != "live"
            or (check["season"], check["week"]) != (board["season"], board["week"])
            or not utc(native["captured_at"]) <= utc(check["verified_at"]) <= cutoff
            or utc(native["forecast_generated_at"]) > utc(native["captured_at"])
            or check["output_sha256"] != digest(board) or native["input_sha256"] != digest(board)
            or check["latest_inputs"] != q["proof"]["latest_inputs"] or check["latest_inputs_sha256"] != digest(inputs)
            or check["game_origins"] != q["proof"]["game_origins"] or check["engine_files"] != native["engine_files"]
            or inputs["engine_files"] != native["engine_files"]
            or check["baseline_receipt"] != q["native_receipt"] or check["baseline_payload_sha256"] != digest(native)
            or digest(native) != q["native_payload_sha256"]):
        raise IntegrityError("Ranked verification/native/input binding mismatch")
    if _dependency_closure(root) != before:
        raise IntegrityError("Ranked evidence changed during qualification")
    return board, native


def _qualified_bundle(root, completion, spec, checked):
    """Memoize only the identical bundle under a freshly read full closure."""
    before = _dependency_closure(root)
    key = ("qualified-bundle", str(Path(root).resolve()), completion, digest(spec), before)
    now = datetime.now(timezone.utc)
    if key in checked:
        result = copy.deepcopy(checked[key])
        if utc(result[0]["evidence_completed_at"]) > now or utc(result[2]["captured_at"]) > now:
            raise IntegrityError("Cached bundle clock is in the future")
    else:
        saved = partial_week._saved(root, completion, partial_week.COMPLETION_LANE)
        if saved.get("schema_version") == "partial-completion-data-integrity-v2":
            result = corrected.read_bundle(root, completion, spec, now=now)
        elif saved.get("schema_version") == partial_week.COMPLETION_VERSION:
            result = corrected.legacy_bundle(root, completion, spec, now=now)
        else:
            raise IntegrityError("Unsupported completed-bundle schema")
        if _dependency_closure(root) != before:
            raise IntegrityError("Source evidence changed during bundle verification")
        checked[key] = copy.deepcopy(result)
    return result


def _validated_publication(base, pointer, checked):
    # Actual bounded leaf bytes are rehashed on every access. Only typed decode
    # and pure reconciliation work is shared, within this operation and base.
    return publication.validate_publication(base, pointer, _checked=checked)


def _source_assets(root, source_sha, assets, checked):
    """Bind retained packaging bytes to retrievable exact source objects."""
    if not publication.SOURCE_HEX.fullmatch(source_sha or "") or set(assets) != {"app.js", "index.html"}:
        raise IntegrityError("Invalid retained packaging source")
    for repository in dict.fromkeys((Path(root).resolve(), ROOT.resolve())):
        try:
            tree = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "--verify", source_sha + "^{tree}"], stderr=subprocess.PIPE, text=True).strip()
        except subprocess.CalledProcessError:
            continue
        for name, raw in assets.items():
            raw = raw.encode() if isinstance(raw, str) else raw
            key = ("packaging-source", str(repository), source_sha, tree, name, hashlib.sha256(raw).hexdigest())
            if key not in checked:
                actual = subprocess.check_output(["git", "-C", str(repository), "show", source_sha + ":output/" + name], stderr=subprocess.PIPE)
                if actual != raw:
                    raise IntegrityError("Retained packaging app/shell differs from exact source")
                checked[key] = True
        return
    raise IntegrityError("Retained packaging source commit is unavailable")


def _manifest(base, descriptor, *, root=None, _checked=None):
    _checked = {} if _checked is None else _checked
    key = ("manifest", str(Path(base).resolve()), digest(descriptor), str(Path(root).resolve()) if root is not None else None)
    manifest = publication._json_bytes(_public_read(base, descriptor, "manifest.json"))
    if (set(manifest) != {"schema_version", "report_id", "pointer", "generation_sha256", "capture_generation_sha256",
                         "source_sha", "capture_source_sha", "packaged_at", "snapshots", "verification_receipt"}
            or manifest["schema_version"] != MANIFEST_VERSION
            or manifest["report_id"] != manifest["pointer"].get("report_id")
            or set(manifest["snapshots"]) != set(HOST_SNAPSHOTS)):
        raise IntegrityError("Malformed complete hosting generation")
    for field in ("generation_sha256", "capture_generation_sha256"):
        publication._hash(manifest[field])
    for field in ("source_sha", "capture_source_sha"):
        if not publication.SOURCE_HEX.fullmatch(manifest[field]):
            raise IntegrityError("Invalid hosting source identity")
    utc(manifest["packaged_at"])
    snapshots = {name: _public_read(base, item, "snapshot-" + name.replace("/", "_"), publication.SUMMARY_LIMIT)
                 for name, item in manifest["snapshots"].items()}
    if publication._json_bytes(snapshots["data/selection-grading/latest.json"]) != manifest["pointer"]:
        raise IntegrityError("Hosting pointer snapshot differs")
    _validated_publication(base, manifest["pointer"], _checked)
    if root is not None:
        proof = partial_week._saved(root, manifest["verification_receipt"], "verification/hosting-generation-proof")
        if (proof.get("schema_version") != "hosting-generation-proof-v1"
                or proof["board_sha256"] != publication._json_bytes(snapshots["data/release-identity.json"])["board_sha256"]
                or proof["capture_source_sha"] != manifest["capture_source_sha"]):
            raise IntegrityError("Retained generation proof binding mismatch")
        generation = _validate_generation(root, snapshots, legacy_proof=proof["proof"], _checked=_checked)
        if (generation["generation_sha256"] != manifest["generation_sha256"]
                or generation.get("capture_generation_sha256", generation["generation_sha256"]) != manifest["capture_generation_sha256"]
                or generation["source_sha"] != manifest["source_sha"]
                or generation.get("capture_source_sha", generation["source_sha"]) != manifest["capture_source_sha"]
                or generation.get("packaged_at", manifest["packaged_at"]) != manifest["packaged_at"]):
            raise IntegrityError("Hosting manifest/capture generation mismatch")
    _checked[key] = (manifest, snapshots)
    return manifest, snapshots


def _registry(base, working, *, _checked=None):
    _checked = {} if _checked is None else _checked
    if (set(working) != {"schema_version", "latest", "previous", "registry", "archive_index", "delivery_sha256"}
            or working["schema_version"] != HOSTING_VERSION or not isinstance(working["registry"], list)
            or len(working["registry"]) > 16):
        raise IntegrityError("Invalid hosting working set")
    if working["delivery_sha256"] is None:
        if working["archive_index"] != []:
            raise IntegrityError("Unbound source-form archive metadata")
    else:
        if (working["delivery_sha256"] != digest({key: value for key, value in working.items() if key != "delivery_sha256"})
                or not isinstance(working["archive_index"], list) or len(working["archive_index"]) > 16):
            raise IntegrityError("Invalid Pages delivery identity")
        prefixes = set()
        for item in working["archive_index"]:
            if (set(item) != {"prefix", "asset"} or not re.fullmatch("[0-9a-f]", item["prefix"])
                    or item["prefix"] in prefixes):
                raise IntegrityError("Invalid archive shard prefix")
            prefixes.add(item["prefix"])
            shard = publication._json_bytes(_public_read(base, item["asset"], "archive.json"))
            if (set(shard) != {"schema_version", "prefix", "repository", "reports"}
                    or shard["schema_version"] != "selection-hosting-archive-v1"
                    or shard["prefix"] != item["prefix"] or shard["repository"] != PUBLIC_REPOSITORY
                    or not isinstance(shard["reports"], dict)):
                raise IntegrityError("Malformed Pages archive index")
            for key, value in shard["reports"].items():
                if (not publication.HEX.fullmatch(key) or not key.startswith(item["prefix"])
                        or set(value) != {"git_ref", "manifest"} or not re.fullmatch("[0-9a-f]{40}", value["git_ref"])
                        or set(value["manifest"]) != {"path", "sha256", "decoded_bytes"}
                        or value["manifest"]["path"] != value["manifest"]["sha256"] + "/manifest.json"
                        or not publication.HEX.fullmatch(value["manifest"]["sha256"])
                        or type(value["manifest"]["decoded_bytes"]) is not int
                        or not 0 < value["manifest"]["decoded_bytes"] <= publication.INDEX_LIMIT):
                    raise IntegrityError("Malformed immutable archive locator")
    result, prefixes = {}, set()
    for item in working["registry"]:
        if set(item) != {"prefix", "asset"} or not re.fullmatch("[0-9a-f]", item["prefix"]) or item["prefix"] in prefixes:
            raise IntegrityError("Duplicate/invalid hosting registry shard")
        prefixes.add(item["prefix"])
        shard = publication._json_bytes(_public_read(base, item["asset"], "registry.json"))
        if (set(shard) != {"schema_version", "prefix", "reports"} or shard["schema_version"] != "selection-hosting-registry-v1"
                or shard["prefix"] != item["prefix"] or not isinstance(shard["reports"], dict)):
            raise IntegrityError("Malformed hosting registry")
        for rid, descriptor in shard["reports"].items():
            if not publication.HEX.fullmatch(rid) or not rid.startswith(item["prefix"]) or rid in result:
                raise IntegrityError("Invalid/duplicate registered report")
            if (set(descriptor) != {"path", "sha256", "decoded_bytes"}
                    or not publication.HEX.fullmatch(descriptor.get("sha256") or "")
                    or descriptor.get("path") != descriptor["sha256"] + "/manifest.json"
                    or type(descriptor.get("decoded_bytes")) is not int
                    or not 0 < descriptor["decoded_bytes"] <= publication.INDEX_LIMIT):
                raise IntegrityError("Invalid registered manifest locator")
            result[rid] = descriptor
    latest, _ = _manifest(base, working["latest"], _checked=_checked)
    previous = _manifest(base, working["previous"], _checked=_checked)[0] if working["previous"] is not None else None
    if result.get(digest(latest["pointer"])) != working["latest"] or (previous and result.get(digest(previous["pointer"])) != working["previous"]):
        raise IntegrityError("Working set absent from registered generations")
    if previous and previous["pointer"] == latest["pointer"]:
        raise IntegrityError("Retry rotated the previous generation")
    if working["delivery_sha256"] is not None:
        archived = {}
        for item in working["archive_index"]:
            archived.update(publication._json_bytes(_public_read(base, item["asset"], "archive.json"))["reports"])
        selected = {digest(latest["pointer"])} | ({digest(previous["pointer"])} if previous else set())
        if set(archived) != set(result) - selected or any(value["manifest"] != result[key] for key, value in archived.items()):
            raise IntegrityError("Incomplete or mismatched immutable archive coverage")
    return result


def finalize_hosting(root, at=None, *, _checked=None):
    """Seal only an actually validated complete generation; no source collection."""
    root = Path(root); base = root / "output/data/selection-grading"
    checked = {} if _checked is None else _checked
    generation = _validate_generation(root, _checked=checked)
    pointer = load_json(base / "latest.json")
    previous_working = load_json(base / "hosting.json") if (base / "hosting.json").exists() else None
    records = _registry(base, previous_working, _checked=checked) if previous_working else {}
    if previous_working:
        old, _ = _manifest(base, previous_working["latest"], root=root, _checked=checked)
        if old["pointer"] == pointer and old["generation_sha256"] == generation["generation_sha256"]:
            return previous_working
    at = utc(at or datetime.now(timezone.utc))
    snapshots = {name: _public_blob(base, "snapshot-" + name.replace("/", "_"),
                      (root / "output" / name).read_bytes(), publication.SUMMARY_LIMIT) for name in HOST_SNAPSHOTS}
    proof_receipt = write(root, "verification/hosting-generation-proof", {
        "schema_version": "hosting-generation-proof-v1", "season": load_json(root / "output/data/meta.json")["season"],
        "week": load_json(root / "output/data/meta.json")["week"], "board_sha256": generation["board_sha256"],
        "capture_source_sha": generation.get("capture_source_sha", generation["source_sha"]),
        "proof": load_json(root / "output/data/matchup-proof.json")})
    manifest = {"schema_version": MANIFEST_VERSION, "report_id": pointer["report_id"], "pointer": pointer,
                "verification_receipt": proof_receipt.relative_to(root).as_posix(),
                "generation_sha256": generation["generation_sha256"],
                "capture_generation_sha256": generation.get("capture_generation_sha256", generation["generation_sha256"]),
                "source_sha": generation["source_sha"], "capture_source_sha": generation.get("capture_source_sha", generation["source_sha"]),
                "packaged_at": generation.get("packaged_at", stamp(at)), "snapshots": snapshots}
    descriptor = _public_blob(base, "manifest.json", canonical(manifest) + b"\n")
    _manifest(base, descriptor, root=root, _checked=checked)
    publication_id = digest(pointer)
    if publication_id in records and records[publication_id] != descriptor:
        raise IntegrityError("Immutable publication manifest conflict")
    records[publication_id] = descriptor
    shards = []
    for prefix in "0123456789abcdef":
        members = {key: value for key, value in sorted(records.items()) if key.startswith(prefix)}
        if members:
            item = _public_blob(base, "registry.json", canonical({"schema_version": "selection-hosting-registry-v1", "prefix": prefix, "reports": members}) + b"\n")
            shards.append({"prefix": prefix, "asset": item})
    working = {"schema_version": HOSTING_VERSION, "latest": descriptor,
               "previous": previous_working["latest"] if previous_working else None,
               "registry": shards, "archive_index": [], "delivery_sha256": None}
    _registry(base, working, _checked=checked)
    # Immutable snapshots do not certify a newly changed source alias/evidence
    # tree. Seal the current source again immediately before advancing hosting.
    sealed = _validate_generation(root, _checked=checked)
    if sealed != generation or any(not _same_generation_snapshot(name, (root / "output" / name).read_bytes(),
                _public_read(base, snapshots[name], "snapshot-" + name.replace("/", "_"), publication.SUMMARY_LIMIT)) for name in HOST_SNAPSHOTS):
        raise IntegrityError("Source generation changed before hosting advancement")
    atomic_json(base / "hosting.json", working)
    return working


def _publication_files(base, pointer, *, _checked=None):
    _checked = {} if _checked is None else _checked
    _validated_publication(base, pointer, _checked)
    paths = {pointer["summary"]["path"], pointer["outcomes"]["path"]} | {row["path"] for row in pointer["rows"]}
    if pointer["schema_version"] in (publication.PARTITION_POINTER_VERSION, publication.GZIP_POINTER_VERSION, publication.SHARED_POINTER_VERSION):
        summary = load_json(Path(base) / pointer["summary"]["path"])
        outcomes = load_json(Path(base) / pointer["outcomes"]["path"])
        paths |= {item["path"] for item in summary["summary_partitions"]}
        paths |= {item["path"] for item in outcomes["periods"]}
    return paths


def _manifest_files(base, descriptor, *, root=None, _checked=None):
    _checked = {} if _checked is None else _checked
    manifest, _ = _manifest(base, descriptor, root=root, _checked=_checked)
    return {descriptor["path"]} | {item["path"] for item in manifest["snapshots"].values()} | _publication_files(base, manifest["pointer"], _checked=_checked)


def _git_archive(root, records, excluded, *, verify_public=True, _checked=None):
    """Never use a source-only/future commit as a generated-asset locator."""
    if not excluded:
        return {}
    root = Path(root)
    _checked = {} if _checked is None else _checked
    try:
        ref = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        if not re.fullmatch(r"[0-9a-f]{40}", ref):
            raise IntegrityError("Missing exact archival Git pin")
        tree = subprocess.check_output(["git", "-C", str(root), "rev-parse", ref + "^{tree}"], text=True).strip()
        remote = subprocess.check_output(["git", "-C", str(root), "remote", "get-url", "origin"], text=True).strip()
        if verify_public:
            if remote not in ("https://github.com/" + PUBLIC_REPOSITORY, "https://github.com/" + PUBLIC_REPOSITORY + ".git"):
                raise IntegrityError("Unexpected public archive repository")
            public_key = ("public-commit", ref, tree)
            if public_key not in _checked:
                _public_archive_commit(ref, tree)
                _checked[public_key] = True
        base = root / "output/data/selection-grading"
        retained_tree = subprocess.check_output(["git", "-C", str(root), "ls-tree", "-r", ref, "--", "data"], text=True)
        blobs = {line.split("\t", 1)[1]: line.split()[2] for line in retained_tree.splitlines()}
        for lane in ("forward", "history", "verification", "shadow", "offers", "outcomes"):
            for path in (root / "data" / lane).rglob("*"):
                if path.is_file():
                    raw = path.read_bytes(); name = path.relative_to(root).as_posix()
                    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                    if blobs.get(name) != blob:
                        raise IntegrityError("Required retained original is absent from the archival commit")
        result, required = {}, set()
        for rid in sorted(excluded):
            descriptor = records[rid]
            required.update(_manifest_files(base, descriptor, root=root, _checked=_checked))
            result[rid] = {"git_ref": ref, "manifest": descriptor}
        listing = subprocess.check_output(["git", "-C", str(root), "ls-tree", "-r", ref, "--", "output/data/selection-grading"], text=True)
        objects = {}
        for line in listing.splitlines():
            meta, name = line.split("\t", 1)
            mode, kind, blob = meta.split()
            if mode == "100644" and kind == "blob":
                objects[name] = blob
        pending = {}
        for relative in sorted(required):
            path = base / relative
            publication._no_symlinks(path, base)
            raw = path.read_bytes()
            blob = objects.get("output/data/selection-grading/" + relative)
            if blob != hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest():
                raise IntegrityError("Archive commit lacks the exact complete report asset")
            key = ("git-blob", str(root.resolve()), ref, tree, blob, hashlib.sha256(raw).hexdigest())
            if key not in _checked:
                if blob in pending and pending[blob][0] != raw:
                    raise IntegrityError("Conflicting archive content for one Git object")
                pending.setdefault(blob, (raw, []))[1].append(key)
        if pending:
            # One exact-object read per unique blob, not one git process per
            # archived graph edge. Hash Git's actual returned bytes as well.
            process = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                for blob, (expected, keys) in pending.items():
                    process.stdin.write((blob + "\n").encode()); process.stdin.flush()
                    fields = process.stdout.readline().decode().strip().split()
                    if fields != [blob, "blob", str(len(expected))]:
                        raise IntegrityError("Unexpected archival Git object type or size")
                    actual = process.stdout.read(len(expected))
                    if process.stdout.read(1) != b"\n" or actual != expected:
                        raise IntegrityError("Archive Git object differs from retained bytes")
                    if hashlib.sha1(b"blob " + str(len(actual)).encode() + b"\0" + actual).hexdigest() != blob:
                        raise IntegrityError("Archive Git object identity differs")
                    for key in keys:
                        _checked[key] = True
            finally:
                process.stdin.close(); process.stdout.close()
                if process.wait() != 0:
                    raise IntegrityError("Archive Git batch failed")
        return result
    except subprocess.CalledProcessError as exc:
        raise IntegrityError("Required report archive is uncommitted or unavailable") from exc


def _public_archive_commit(ref, tree):
    import requests
    response = requests.get("https://api.github.com/repos/" + PUBLIC_REPOSITORY + "/git/commits/" + ref, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if payload.get("sha") != ref or payload.get("tree", {}).get("sha") != tree:
        raise IntegrityError("Public archival commit/tree mismatch")


def _repackage_generation(root, *, source_root=ROOT, _checked=None):
    """Package a SAVED qualified bundle. Never invoke builder/provider/candidate."""
    _checked = {} if _checked is None else _checked
    root, source_root = Path(root).resolve(), Path(source_root).resolve()
    source_sha = subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True).strip()
    # Packaging source must truthfully identify committed bytes, including this code.
    for name in ("tools/phase2_capture.py", "tools/selection_publication.py", "output/app.js", "output/index.html"):
        saved = subprocess.check_output(["git", "-C", str(source_root), "show", source_sha + ":" + name], stderr=subprocess.PIPE)
        if saved != (source_root / name).read_bytes():
            raise IntegrityError("Packaging code is not the identified committed source")
    original = validate_generation(root, _checked=_checked)
    if original.get("schema_version") in ("website-packaging-generation-v1", "website-packaging-generation-v2") and original["source_sha"] == source_sha and load_json(root / "output/data/selection-grading/latest.json")["schema_version"] == publication.SHARED_POINTER_VERSION:
        return original
    if original.get("schema_version") not in ("website-generation-v1", "website-packaging-generation-v1", "website-packaging-generation-v2"):
        raise IntegrityError("Unsupported saved packaging source generation")
    # An already identical encoded app/report needs no manufactured generation.
    # Validation time is not a new capture or packaging source identity.
    saved_pointer = load_json(root / "output/data/selection-grading/latest.json")
    if (saved_pointer.get("schema_version") == publication.SHARED_POINTER_VERSION
            and all((root / "output" / name).read_bytes() == (source_root / "output" / name).read_bytes()
                    for name in ("app.js", "index.html"))):
        if not (root / "output/data/selection-grading/hosting.json").exists():
            finalize_hosting(root, datetime.now(timezone.utc), _checked=_checked)
        return validate_generation(root, _checked=_checked)
    at = datetime.now(timezone.utc)
    # Migration seals the already complete original before changing any alias.
    # It is the previous complete generation, not a failed-attempt placeholder.
    if not (root / "output/data/selection-grading/hosting.json").exists():
        finalize_hosting(root, at, _checked=_checked)
    health = load_json(root / "output/data/health.json")
    pointer = load_json(root / "output/data/selection-grading/latest.json")
    if original["schema_version"] == "website-generation-v1":
        origin = {"schema_version": "hosting-capture-original-v1", "season": load_json(root / "output/data/meta.json")["season"],
                  "week": load_json(root / "output/data/meta.json")["week"], "generation": original, "health": health,
                  "pointer": pointer, "proof": load_json(root / "output/data/matchup-proof.json"),
                  "source_assets": {name: (root / "output" / name).read_text() for name in ("app.js", "index.html")}}
        receipt = write(root, "verification/hosting-capture-originals", origin)
    else:
        receipt = root / original["capture_original_receipt"]
        origin = partial_week._saved(root, original["capture_original_receipt"], "verification/hosting-capture-originals")
    captured = origin["generation"]
    if origin.get("schema_version") != "hosting-capture-original-v1" or captured["schema_version"] != "website-generation-v1":
        raise IntegrityError("Missing flat root capture origin")
    previous_assets = {name: (root / "output" / name).read_text() for name in ("app.js", "index.html")}
    for source, assets in ((captured["source_sha"], origin["source_assets"]), (original["source_sha"], previous_assets)):
        for name, raw in assets.items():
            saved = subprocess.check_output(["git", "-C", str(source_root), "show", source + ":output/" + name], stderr=subprocess.PIPE)
            if saved != raw.encode():
                raise IntegrityError("Saved source app/shell mismatch")
    transition = write(root, "verification/hosting-capture-originals", {
        "schema_version": "hosting-packaging-transition-v1", "season": origin["season"], "week": origin["week"],
        "root_capture_original_receipt": receipt.relative_to(root).as_posix(),
        "previous_generation": original, "previous_health": health, "previous_pointer": pointer,
        "previous_source_assets": previous_assets})
    base = root / "output/data/selection-grading"
    new_pointer = publication.repack_publication(base, pointer, packaged_at=at, _checked=_checked)
    for name in ("app.js", "index.html"):
        shutil.copyfile(source_root / "output" / name, root / "output" / name)
    atomic_json(base / "latest.json", new_pointer)
    bindings = {name: hashlib.sha256((root / "output" / name).read_bytes()).hexdigest() for name in original["bindings"]}
    generation = {"schema_version": "website-packaging-generation-v2", "source_sha": source_sha,
                  "capture_source_sha": captured["source_sha"], "capture_generation_sha256": captured["generation_sha256"],
                  "capture_original_receipt": receipt.relative_to(root).as_posix(),
                  "prior_packaging_receipt": transition.relative_to(root).as_posix(), "packaged_at": stamp(at),
                  "board_sha256": original["board_sha256"], "baseline_payload_sha256": original["baseline_payload_sha256"],
                  "selection_report_id": new_pointer["report_id"], "bindings": bindings}
    gid = digest(generation)
    health = copy.deepcopy(health)
    health.update(generation_sha256=gid, source_sha=source_sha, capture_source_sha=captured["source_sha"],
                  capture_generation_sha256=captured["generation_sha256"], packaged_at=stamp(at))
    health["phase2"]["selection_report_sha256"] = new_pointer["report_id"]
    atomic_json(root / "output/data/release-identity.json", dict(generation, generation_sha256=gid))
    atomic_json(root / "output/data/health.json", health)
    _validate_generation(root, _checked=_checked)
    finalize_hosting(root, at, _checked=_checked)
    return validate_generation(root, _checked=_checked)


def repackage_generation(root, *, source_root=ROOT):
    _checked = {}
    root, source_root = Path(root).resolve(), Path(source_root).resolve()
    if root == source_root:
        raise IntegrityError("Saved packaging requires a separate local copy")
    with tempfile.TemporaryDirectory(prefix="nfl-saved-packaging-") as temporary:
        stage = Path(temporary) / "generation"
        for name in ("pull", "tools", "config", "data", "output"):
            if (root / name).exists():
                if any(path.is_symlink() for path in (root / name).rglob("*")):
                    raise IntegrityError("Symlink saved-package source")
                shutil.copytree(root / name, stage / name, ignore=shutil.ignore_patterns("__pycache__"))
        result = _repackage_generation(stage, source_root=source_root, _checked=_checked)
        _promote(stage, root, packaging=True, _checked=_checked)
        return result


def _completed_partial_native(stage, path, spec):
    name = path.relative_to(stage).as_posix()
    matches = []
    try:
        for candidate in (stage / "data" / partial_week.COMPLETION_LANE).rglob("*.json.gz"):
            payload = read(candidate)
            if payload.get("baseline_receipt") == name:
                matches.append(candidate.relative_to(stage).as_posix())
        if len(matches) != 1:
            return False
        _qualified_bundle(stage, matches[0], spec, {})
        return True
    except (OSError, ValueError, KeyError, TypeError):
        # This rejects only native qualification. The original generation
        # failure still propagates; statistics/board/report errors are not hidden.
        return False


def _copy_evidence(stage, root, *, failed_generation=False):
    """Create-only evidence transfer; failure never deletes original evidence."""
    for lane in ("forward", "history", "verification", "shadow", "offers", "outcomes"):
        for path in sorted((stage / "data" / lane).rglob("*")):
            if not path.is_file():
                continue
            destination = root / path.relative_to(stage)
            if destination.exists():
                if destination.read_bytes() != path.read_bytes():
                    raise IntegrityError("Immutable generation evidence conflict")
            else:
                if failed_generation and lane == "forward":
                    config = load_json(stage / "config/phase2.json")
                    spec = config.get("partial_week", {})
                    plan = spec.get("plan", {})
                    relative = path.relative_to(stage / "data/forward")
                    partial_period = (str(plan.get("season")), f"w{plan.get('week', 0):02d}")
                    if (config.get("verification_mode") in (partial_week.VERSION, corrected.VALIDATOR)
                            and relative.parts[:2] == partial_period
                            and not _completed_partial_native(stage, path, spec)):
                        # Preserve exact NEW failed bytes outside the canonical
                        # observation lane. No historical receipt is moved.
                        raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                        destination = (root / "data/verification/partial-unqualified-native"
                                       / relative.parent / raw_hash / path.name)
                        write(root, "verification/partial-failures", {
                            "schema_version": "unqualified-native-preservation-v1",
                            "season": plan["season"], "week": plan["week"],
                            "original_forward_name": path.relative_to(stage).as_posix(),
                            "retained_name": destination.relative_to(root).as_posix(),
                            "native_file_sha256": raw_hash,
                            "failed_at": stamp(datetime.now(timezone.utc)),
                            "qualification": "NO_COMPLETED_PARTIAL_BUNDLE_NOT_A_PREGAME_OBSERVATION"})
                        if destination.exists():
                            if destination.read_bytes() != path.read_bytes():
                                raise IntegrityError("Conflicting preserved failed native bytes")
                            continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Source files are already fsynced immutable evidence. Link is
                # create-only; copy fallback handles a separate filesystem.
                try:
                    os.link(path, destination)
                except OSError:
                    with destination.open("xb") as handle:
                        handle.write(path.read_bytes()); handle.flush(); os.fsync(handle.fileno())


def _promote(stage, root, *, packaging=False, _checked=None):
    """Validate first, then publish. Restore overwritten outputs on I/O failure."""
    _checked = {} if _checked is None else _checked
    evidence_before = _dependency_closure(stage)
    _copy_evidence(stage, root)
    if _dependency_closure(stage) != evidence_before:
        raise IntegrityError("Staged evidence changed during promotion")
    journal = {}
    try:
        directories = (("output/app.js", "output/index.html") if packaging else ()) + ("data/cache", "output/data")
        for directory in directories:
            paths = [stage / directory] if (stage / directory).is_file() else sorted((stage / directory).rglob("*"), key=lambda p: (p.name in ("latest.json", "hosting.json"), str(p)))
            for path in paths:
                if not path.is_file():
                    continue
                target = root / path.relative_to(stage)
                raw = path.read_bytes()
                if target.exists() and target.read_bytes() == raw:
                    continue
                journal[target] = target.read_bytes() if target.exists() else None
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                    handle.write(raw); handle.flush(); os.fsync(handle.fileno()); temp = Path(handle.name)
                try:
                    os.replace(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
        validate_generation(root, _checked=_checked)
    except BaseException:
        for target, old in reversed(list(journal.items())):
            if old is not None:
                target.write_bytes(old)
            elif "selection-grading" not in target.parts or target.name in ("latest.json", "hosting.json"):
                # Restore prior absence of mutable files; immutable originals
                # and unreachable new report assets remain preserved.
                target.unlink(missing_ok=True)
        raise


def run_capture(root=ROOT, mode="live", replay_at=None, *, build_first=False):
    _checked = {}
    root = Path(root).resolve()
    if mode != "live":
        if build_first:
            raise IntegrityError("Recorded live build cannot use a replay clock")
        return _run_capture(root, mode, replay_at)
    if replay_at is not None:
        raise IntegrityError("Live capture cannot use a supplied clock")
    if read_mode(root) != "phase1" or not read_phase2(root):
        raise IntegrityError("Phase 2 capture is disabled by recovery mode")
    source_sha = os.environ.get("GITHUB_SHA")
    if source_sha is None:
        git_root = root if (root / ".git").exists() else ROOT
        source_sha = subprocess.check_output(["git", "-C", str(git_root), "rev-parse", "HEAD"], text=True).strip()
    config = load_json(root / "config/phase2.json")
    current = load_json(root / "output/data/week.json")
    plan = config.get("partial_week", {}).get("plan", {})
    selected_state = None
    selected_period = (current["season"], current["week"])
    if build_first and config.get("verification_mode") in (partial_week.VERSION, corrected.VALIDATOR):
        import build
        # Observe the builder's own selector once, before registration/build.
        # The unchanged builder consumes this exact response; no forced week.
        selected_state = build.sources.nfl_state()
        week = int(selected_state["week"]) if selected_state.get("season_type") == "regular" else 1
        selected_period = (int(selected_state["season"]), max(1, min(week, build.REGULAR_SEASON_WEEKS)))
        if config.get("verification_mode") == corrected.VALIDATOR:
            if selected_period != (plan.get("season"), plan.get("week")):
                raise IntegrityError("Corrected rollover needs its own approved source/plan transition")
            _verification_route(config, current, datetime.now(timezone.utc))
        else:
            partial_week.dispatch(config, {"season": selected_period[0], "week": selected_period[1]}, datetime.now(timezone.utc))
    needs_initial = (config.get("verification_mode") in (partial_week.VERSION, corrected.VALIDATOR)
                     and selected_period == (plan.get("season"), plan.get("week")))
    initial = _initial_board(root, config["partial_week"]) if needs_initial else None
    with tempfile.TemporaryDirectory(prefix="phase2-coherent-generation-") as directory:
        stage = Path(directory) / "generation"
        for name in ("pull", "tools", "config", "data", "output"):
            source = root / name
            if source.exists():
                if any(path.is_symlink() for path in source.rglob("*")):
                    raise IntegrityError("Symlink generation source is unsupported")
                shutil.copytree(source, stage / name, ignore=shutil.ignore_patterns("__pycache__"))
        try:
            # One-time migration of a fully validated existing publication.
            # A malformed existing generation fails here; it is not silently
            # replaced or promoted as previous-successful evidence.
            if ((stage / "output/data/release-identity.json").exists()
                    and not (stage / "output/data/selection-grading/hosting.json").exists()):
                finalize_hosting(stage, datetime.now(timezone.utc), _checked=_checked)
            if needs_initial:
                registrar = corrected.register_plan if config.get("verification_mode") == corrected.VALIDATOR else partial_week.register_plan
                registrar(stage, config["partial_week"], datetime.now(timezone.utc), source_sha=source_sha, initial_board=initial)
            if build_first:
                import build_recorded
                import build
                saved = {key: getattr(build, key) for key in ("ROOT", "OUT", "CACHE", "ARCHIVE", "WEEKS")}
                athlete_cache = build.books.ATHLETES
                state_reader = build.sources.nfl_state
                try:
                    build.ROOT, build.OUT, build.CACHE = stage, stage / "output/data", stage / "data/cache"
                    build.ARCHIVE, build.WEEKS = build.OUT / "archive", build.OUT / "weeks"
                    build.books.ATHLETES = build.CACHE / "espn_athletes.json"
                    if selected_state is not None:
                        build.sources.nfl_state = lambda: copy.deepcopy(selected_state)
                    build_recorded.record_build(stage, mode="live", model=config.get("production_model", point_challenger.BASELINE_MODEL))
                finally:
                    for key, value in saved.items():
                        setattr(build, key, value)
                    build.books.ATHLETES = athlete_cache
                    build.sources.nfl_state = state_reader
            result = _run_capture(stage, mode, source_sha=source_sha, initial_board=initial, _checked=_checked)
            validate_generation(stage, _checked=_checked)
            _promote(stage, root, _checked=_checked)
            return result
        except BaseException as err:
            _copy_evidence(stage, root, failed_generation=True)
            board_path = stage / "output/data/week.json"
            if board_path.exists() and (needs_initial or build_first):
                board = load_json(board_path)
                write(root, "verification/partial-failures", {"schema_version": "generation-failure-v1",
                      "season": board["season"], "week": board["week"], "failed_at": stamp(datetime.now(timezone.utc)),
                      "output_sha256": digest(board), "error_type": type(err).__name__})
            raise


def _validate_generation(root, snapshots=None, *, legacy_proof=None, _checked=None, _verify_prior=True):
    _checked = {} if _checked is None else _checked
    root = Path(root)
    def raw(name):
        return snapshots[name] if snapshots is not None else (root / "output" / name).read_bytes()
    def output(name):
        return publication._json_bytes(raw(name))
    generation = output("data/release-identity.json")
    core = {key: value for key, value in generation.items() if key != "generation_sha256"}
    health = output("data/health.json")
    packaging = generation.get("schema_version") in ("website-packaging-generation-v1", "website-packaging-generation-v2")
    if (generation.get("schema_version") not in ("website-generation-v1", "website-packaging-generation-v1", "website-packaging-generation-v2") or digest(core) != generation["generation_sha256"]
            or health.get("generation_sha256") != generation["generation_sha256"]
            or health.get("board_sha256") != generation["board_sha256"] or health.get("source_sha") != generation["source_sha"]):
        raise IntegrityError("Health/publication generation mismatch")
    if set(generation["bindings"]) != {"app.js", "index.html", "data/week.json", "data/meta.json",
                                        "data/verification-scope.json", "data/forecast-scorecard.json",
                                        "data/selection-grading/latest.json"}:
        raise IntegrityError("Incomplete source/app/shell/generation binding")
    for name, expected in generation["bindings"].items():
        if name not in ("app.js", "index.html", "data/week.json", "data/meta.json", "data/verification-scope.json",
                        "data/forecast-scorecard.json", "data/selection-grading/latest.json"):
            raise IntegrityError("Unrecognized generation binding")
        path = root / "output" / name
        actual = hashlib.sha256(raw(name)).hexdigest()
        if actual != expected:
            raise IntegrityError("Publication generation content mismatch")
    board = output("data/week.json")
    if generation["board_sha256"] != digest(board):
        raise IntegrityError("Generation board checksum mismatch")
    baseline = read_native_baseline(root / health["receipt"], root)
    if digest(baseline) != generation["baseline_payload_sha256"] or baseline["input_sha256"] != digest(board):
        raise IntegrityError("Generation/native baseline mismatch")
    pointer = output("data/selection-grading/latest.json")
    _validated_publication(root / "output/data/selection-grading", pointer, _checked)
    if pointer["report_id"] != generation["selection_report_id"]:
        raise IntegrityError("Generation/report identity mismatch")
    completion = health["phase2"].get("partial_completion_receipt")
    if completion:
        completed, scope, native = _qualified_bundle(root, completion, load_json(root / "config/phase2.json")["partial_week"], _checked)
        if scope["output_sha256"] != digest(board) or digest(native) != digest(baseline):
            raise IntegrityError("Generation scope/native binding mismatch")
        public_scope = corrected.public_scope if scope.get("validator_contract") == corrected.VALIDATOR else partial_week.public_scope
        if output("data/verification-scope.json") != public_scope(scope, completed):
            raise IntegrityError("Public scope differs from retained source validation")
        if health["phase2"].get("strict_full_board_verified") is not False:
            raise IntegrityError("Partial generation overclaims strict verification")
    else:
        corrected.legacy_offline(root, board, legacy_proof if legacy_proof is not None else load_json(root / "output/data/matchup-proof.json"), "live", health["checked_at"])
        if health["phase2"].get("strict_full_board_verified") is not True:
            raise IntegrityError("Strict generation lacks source validation")
    rich = partial_week._saved(root, health["phase2"]["rich_scorecard_receipt"], "verification/report-originals")
    public = output("data/forecast-scorecard.json")
    if (rich.get("schema_version") != "rich-scorecard-evidence-v1" or rich["report_sha256"] != digest(rich["report"])
            or rich["board_sha256"] != digest(board) or rich["source_sha"] != generation.get("capture_source_sha", generation["source_sha"])
            or public != public_scorecard(rich["report"], board, generation.get("capture_source_sha", generation["source_sha"]))):
        raise IntegrityError("Public scorecard differs from its retained rich report")
    if packaging:
        origin = partial_week._saved(root, generation["capture_original_receipt"], "verification/hosting-capture-originals")
        if (origin.get("schema_version") != "hosting-capture-original-v1"
                or origin["generation"]["schema_version"] != "website-generation-v1"
                or origin["generation"]["generation_sha256"] != generation["capture_generation_sha256"]
                or origin["generation"]["source_sha"] != generation["capture_source_sha"]
                or utc(generation["packaged_at"]) < utc(origin["health"]["checked_at"])
                or health.get("packaged_at") != generation["packaged_at"]
                or health.get("capture_source_sha") != generation["capture_source_sha"]
                or health.get("capture_generation_sha256") != generation["capture_generation_sha256"]):
            raise IntegrityError("Invalid original capture/packaging binding")
        original_snapshots = {name: raw(name) for name in HOST_SNAPSHOTS}
        original_snapshots.update({"data/release-identity.json": canonical(origin["generation"]),
                                  "data/health.json": canonical(origin["health"]),
                                  "data/selection-grading/latest.json": canonical(origin["pointer"])})
        original_snapshots.update({name: value.encode() for name, value in origin["source_assets"].items()})
        _validate_generation(root, original_snapshots, legacy_proof=origin["proof"], _checked=_checked)
        old_summary, old_rows, old_outcomes = publication.publication_contents(root / "output/data/selection-grading", origin["pointer"], _checked=_checked)
        new_summary, new_rows, new_outcomes = publication.publication_contents(root / "output/data/selection-grading", pointer, _checked=_checked)
        old_summary.pop("report_id", None); new_summary.pop("report_id", None)
        if (old_summary, old_rows, old_outcomes) != (new_summary, new_rows, new_outcomes):
            raise IntegrityError("Packaging changed captured public semantics")
        if generation["schema_version"] == "website-packaging-generation-v2":
            _source_assets(root, generation["source_sha"], {name: raw(name) for name in ("app.js", "index.html")}, _checked)
            _source_assets(root, origin["generation"]["source_sha"], origin["source_assets"], _checked)
            prior = partial_week._saved(root, generation["prior_packaging_receipt"], "verification/hosting-capture-originals")
            if (set(prior) != {"schema_version", "season", "week", "root_capture_original_receipt", "previous_generation", "previous_health", "previous_pointer", "previous_source_assets"}
                    or prior["schema_version"] != "hosting-packaging-transition-v1"
                    or prior["root_capture_original_receipt"] != generation["capture_original_receipt"]
                    or (prior["season"], prior["week"]) != (origin["season"], origin["week"])
                    or set(prior["previous_source_assets"]) != {"app.js", "index.html"}):
                raise IntegrityError("Invalid flat packaging transition")
            previous = prior["previous_generation"]
            _source_assets(root, previous["source_sha"], prior["previous_source_assets"], _checked)
            if (previous["generation_sha256"] == generation["generation_sha256"]
                    or previous["board_sha256"] != generation["board_sha256"]
                    or previous["baseline_payload_sha256"] != generation["baseline_payload_sha256"]
                    or utc(previous.get("packaged_at", prior["previous_health"]["checked_at"])) > utc(generation["packaged_at"])):
                raise IntegrityError("Packaging transition changed capture or reversed clocks")
            if previous["schema_version"] != "website-generation-v1" and (
                    previous.get("capture_original_receipt") != generation["capture_original_receipt"]
                    or previous.get("capture_source_sha") != generation["capture_source_sha"]
                    or previous.get("capture_generation_sha256") != generation["capture_generation_sha256"]):
                raise IntegrityError("Packaging transition lost root capture")
            if _verify_prior:
                previous_snapshots = dict(original_snapshots)
                previous_snapshots.update({"data/release-identity.json": canonical(previous),
                                           "data/health.json": canonical(prior["previous_health"]),
                                           "data/selection-grading/latest.json": canonical(prior["previous_pointer"])})
                previous_snapshots.update({name: value.encode() for name, value in prior["previous_source_assets"].items()})
                # Root capture is independently reproduced for each packaging
                # generation; immediate provenance is bounded, not nested replay.
                _validate_generation(root, previous_snapshots, legacy_proof=origin["proof"], _checked=_checked, _verify_prior=False)
    return generation


def _same_generation_snapshot(name, actual, captured):
    if name != "data/health.json":
        return actual == captured
    current, saved = publication._json_bytes(actual), publication._json_bytes(captured)
    # Existing hourly workflow appends these advisory step outcomes AFTER the
    # qualified capture. They neither change required health nor rotate a report.
    for field in ("legacy_verifier", "historical_comparison"):
        if current.get(field) != saved.get(field) and current.get(field) not in {"success", "failure", "cancelled", "skipped"}:
            return False
        current.pop(field, None); saved.pop(field, None)
    return current == saved


def validate_generation(root, *, _checked=None):
    _checked = {} if _checked is None else _checked
    generation = _validate_generation(root, _checked=_checked)
    base = Path(root) / "output/data/selection-grading"
    if (base / "hosting.json").exists():
        working = load_json(base / "hosting.json")
        _registry(base, working, _checked=_checked)
        current, snapshots = _manifest(base, working["latest"], root=Path(root), _checked=_checked)
        if current["generation_sha256"] != generation["generation_sha256"]:
            raise IntegrityError("Hosting/current generation mismatch")
        if any(not _same_generation_snapshot(name, (Path(root) / "output" / name).read_bytes(), value) for name, value in snapshots.items()):
            raise IntegrityError("Hosting/current snapshot differs from root alias")
        if working["previous"] is not None:
            _manifest(base, working["previous"], root=Path(root), _checked=_checked)
    return generation


def stage_pages(root, destination):
    """Fresh bounded Pages projection. Never delete GitHub originals/old assets."""
    root, destination = Path(root).resolve(), Path(destination).resolve()
    _checked = {}
    evidence_before = _dependency_closure(root)
    if destination.exists() or destination.is_relative_to(root / "output"):
        raise IntegrityError("Pages staging requires a fresh external destination")
    output = root / "output"
    if any(path.is_symlink() for path in output.rglob("*")):
        raise IntegrityError("Refusing symlink Pages asset")
    if read_phase2(root):
        validate_generation(root, _checked=_checked)
    initial_generation = (root / "output/data/release-identity.json").read_bytes() if read_phase2(root) else None
    base = output / "data/selection-grading"
    working = load_json(base / "hosting.json") if (base / "hosting.json").exists() else None
    retained, archives = None, {}
    if working is not None:
        records = _registry(base, working, _checked=_checked)
        retained, selected = set(), set()
        for descriptor in (working["latest"], working["previous"]):
            if descriptor is not None:
                manifest, _ = _manifest(base, descriptor, root=root, _checked=_checked)
                selected.add(digest(manifest["pointer"]))
                retained |= _manifest_files(base, descriptor, root=root, _checked=_checked)
        retained |= {item["asset"]["path"] for item in working["registry"]}
        # At actual deployment this HEAD is the already-pushed generated-data
        # commit. Source-only or uncommitted files fail; no future pin is invented.
        archives = _git_archive(root, records, set(records) - selected, _checked=_checked)
    excluded = {"data/game-status.json", "data/matchup-proof.json", "data/matchup-diagnostics.json"}
    public_data = {"data/week.json", "data/meta.json", "data/future.json", "data/teams.json", "data/track_record.json",
                   "data/dk_backtest.json", "data/forecast-scorecard.json", "data/offer-capture.json", "data/health.json",
                   "data/release-identity.json", "data/verification-scope.json"}
    staged_bytes = 0
    for path in output.rglob("*"):
        if not path.is_file() or path.relative_to(output).as_posix() in excluded:
            continue
        relative = path.relative_to(output); name = relative.as_posix()
        report_asset = re.fullmatch(r"data/selection-grading/(?:latest\.json|hosting\.json|[0-9a-f]{64}/(?:summary|outcomes|rows|rows-[0-9]{4}|manifest|registry|archive)\.json|[0-9a-f]{64}/snapshot-(?:app\.js|index\.html|data_(?:week|meta|verification-scope|forecast-scorecard|health|release-identity)\.json|data_selection-grading_latest\.json))", name)
        allowed = (name in {"app.js", "index.html", "style.css", "reliability-ui.js", "recovery.html"}
                   or name in public_data or re.fullmatch(r"data/(?:archive|weeks)/[0-9]{4}_w[0-9]{2}\.json", name) or report_asset)
        if (not allowed or any(part.startswith(".") for part in relative.parts)
                or path.suffix not in (".js", ".css", ".html", ".json", ".png", ".svg", ".ico", ".txt")):
            raise IntegrityError("Unclassified Pages asset")
        if working is not None and name.startswith("data/selection-grading/"):
            report_name = path.relative_to(base).as_posix()
            if report_name == "hosting.json" or report_name != "latest.json" and report_name not in retained:
                continue
        # Reject an oversized allowed-path file before copying/allocating it.
        if staged_bytes + path.stat().st_size > STAGING_BUDGET:
            raise IntegrityError("Complete Pages stage exceeds conservative 900000000-byte budget")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        staged_bytes += target.stat().st_size
    if working is not None:
        delivery = copy.deepcopy(working); delivery["archive_index"] = []
        delivery_base = destination / "data/selection-grading"
        for prefix in "0123456789abcdef":
            members = {rid: item for rid, item in archives.items() if rid.startswith(prefix)}
            if members:
                item = _public_blob(delivery_base, "archive.json", canonical({"schema_version": "selection-hosting-archive-v1",
                                     "prefix": prefix, "repository": PUBLIC_REPOSITORY, "reports": members}) + b"\n")
                delivery["archive_index"].append({"prefix": prefix, "asset": item})
        delivery["delivery_sha256"] = digest({key: value for key, value in delivery.items() if key != "delivery_sha256"})
        if len(canonical(delivery) + b"\n") > publication.INDEX_LIMIT:
            raise IntegrityError("Pages hosting pointer exceeds supported limit")
        atomic_json(delivery_base / "hosting.json", delivery)
        _registry(delivery_base, delivery, _checked=_checked)
        for descriptor in (delivery["latest"], delivery["previous"]):
            if descriptor:
                _manifest(delivery_base, descriptor, _checked=_checked)
    if working is not None:
        latest, snapshots = _manifest(delivery_base, delivery["latest"], _checked=_checked)
        for name in HOST_SNAPSHOTS:
            if not _same_generation_snapshot(name, (destination / name).read_bytes(), snapshots[name]):
                raise IntegrityError("Staged alias changed from its complete generation")
    if _dependency_closure(root) != evidence_before:
        raise IntegrityError("Retained source evidence changed during Pages staging")
    if read_phase2(root):
        validate_generation(root, _checked=_checked)
        if (root / "output/data/release-identity.json").read_bytes() != initial_generation:
            raise IntegrityError("Source generation changed during Pages staging")
    total = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
    if total > STAGING_BUDGET:
        raise IntegrityError("Complete Pages stage exceeds conservative 900000000-byte budget")
    # GitHub Pages reads the new public stage, including atomic-json metadata.
    # Do not inherit a private local umask or alter any original source/evidence.
    destination.chmod(0o755)
    for path in destination.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("live", "replay"), required=True)
    parser.add_argument("--replay-at")
    parser.add_argument("--build-and-capture", action="store_true")
    parser.add_argument("--stage-pages", type=Path)
    parser.add_argument("--validate-generation", action="store_true")
    parser.add_argument("--package-saved-root", type=Path, help="Packaging-only external copy; no provider or capture calls")
    args = parser.parse_args()
    if args.mode == "live" and args.replay_at:
        parser.error("Live capture cannot use a supplied clock")
    if args.package_saved_root:
        if args.mode != "live" or args.build_and_capture or args.replay_at:
            parser.error("Saved packaging does not collect or accept replay clocks")
        print(repackage_generation(args.package_saved_root)["generation_sha256"])
        return
    if args.stage_pages:
        print(stage_pages(ROOT, args.stage_pages))
        return
    if args.validate_generation:
        print(validate_generation(ROOT)["generation_sha256"])
        return
    report, health = run_capture(mode=args.mode, replay_at=args.replay_at, build_first=args.build_and_capture)
    print({"baseline_receipt": health["receipt"], "phase2": health["phase2"], "outcomes": report["outcome_status"]})


if __name__ == "__main__":
    main()
