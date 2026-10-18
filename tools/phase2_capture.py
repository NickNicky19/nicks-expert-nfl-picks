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
from reliability import IntegrityError, atomic_json, capture, digest, engine_hashes, load_json, stamp, utc
from scorecard import build_scorecard, identity, latest_outcomes
from scoring import CATEGORIES
from selection_publication import all_ten_outcome_identities, publish_selection_report
from shadow import evaluate, make_shadow
from verify import require_offline
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


def _run_capture(root=ROOT, mode="live", replay_at=None, *, source_sha=None, initial_board=None):
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
    route = partial_week.dispatch(config, data, now) if mode == "live" else "strict"
    scope = completion_path = None
    if route == "partial":
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
    if route != "partial":
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
    if health["capture_created"] and (mode == "replay" or experimental):
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
        publication = publish_selection_report(root, now, source_sha=source_sha)
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
            atomic_json(root / "output/data/verification-scope.json", partial_week.public_scope(scope, read(completion_path)))
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
    else:
        write(root, "replay_reports", {"season": data["season"], "week": data["week"], "mode": "replay", "report": report})
    return report, health


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
        partial_week.read_bundle(stage, matches[0], spec, read_native_baseline,
                                 now=datetime.now(timezone.utc))
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
                    if (config.get("verification_mode") == partial_week.VERSION
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


def _promote(stage, root):
    """Validate first, then publish. Restore overwritten outputs on I/O failure."""
    _copy_evidence(stage, root)
    journal = {}
    try:
        for directory in ("data/cache", "output/data"):
            paths = sorted((stage / directory).rglob("*"), key=lambda p: (p.name == "latest.json", str(p)))
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
        validate_generation(root)
    except BaseException:
        for target, old in reversed(list(journal.items())):
            if old is not None:
                target.write_bytes(old)
            elif "selection-grading" not in target.parts or target.name == "latest.json":
                # Restore prior absence of mutable files; immutable originals
                # and unreachable new report assets remain preserved.
                target.unlink(missing_ok=True)
        raise


def run_capture(root=ROOT, mode="live", replay_at=None, *, build_first=False):
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
    if build_first and config.get("verification_mode") == partial_week.VERSION:
        import build
        # Observe the builder's own selector once, before registration/build.
        # The unchanged builder consumes this exact response; no forced week.
        selected_state = build.sources.nfl_state()
        week = int(selected_state["week"]) if selected_state.get("season_type") == "regular" else 1
        selected_period = (int(selected_state["season"]), max(1, min(week, build.REGULAR_SEASON_WEEKS)))
        partial_week.dispatch(config, {"season": selected_period[0], "week": selected_period[1]}, datetime.now(timezone.utc))
    needs_initial = (config.get("verification_mode") == partial_week.VERSION
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
            if needs_initial:
                partial_week.register_plan(stage, config["partial_week"], datetime.now(timezone.utc),
                                           source_sha=source_sha, initial_board=initial)
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
                    build_recorded.record_build(stage, mode="live")
                finally:
                    for key, value in saved.items():
                        setattr(build, key, value)
                    build.books.ATHLETES = athlete_cache
                    build.sources.nfl_state = state_reader
            result = _run_capture(stage, mode, source_sha=source_sha, initial_board=initial)
            validate_generation(stage)
            _promote(stage, root)
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


def validate_generation(root):
    root = Path(root)
    generation = load_json(root / "output/data/release-identity.json")
    core = {key: value for key, value in generation.items() if key != "generation_sha256"}
    health = load_json(root / "output/data/health.json")
    if (generation.get("schema_version") != "website-generation-v1" or digest(core) != generation["generation_sha256"]
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
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise IntegrityError("Publication generation content mismatch")
    board = load_json(root / "output/data/week.json")
    if generation["board_sha256"] != digest(board):
        raise IntegrityError("Generation board checksum mismatch")
    baseline = read_native_baseline(root / health["receipt"], root)
    if digest(baseline) != generation["baseline_payload_sha256"] or baseline["input_sha256"] != digest(board):
        raise IntegrityError("Generation/native baseline mismatch")
    from selection_publication import validate_publication
    pointer = load_json(root / "output/data/selection-grading/latest.json")
    validate_publication(root / "output/data/selection-grading", pointer)
    if pointer["report_id"] != generation["selection_report_id"]:
        raise IntegrityError("Generation/report identity mismatch")
    completion = health["phase2"].get("partial_completion_receipt")
    if completion:
        completed, scope, native = partial_week.read_bundle(root, completion, load_json(root / "config/phase2.json")["partial_week"], read_native_baseline)
        if scope["output_sha256"] != digest(board) or digest(native) != digest(baseline):
            raise IntegrityError("Generation scope/native binding mismatch")
        if load_json(root / "output/data/verification-scope.json") != partial_week.public_scope(scope, completed):
            raise IntegrityError("Public scope differs from retained source validation")
        if health["phase2"].get("strict_full_board_verified") is not False:
            raise IntegrityError("Partial generation overclaims strict verification")
    else:
        require_offline(root, board, load_json(root / "output/data/matchup-proof.json"), "live", health["checked_at"])
        if health["phase2"].get("strict_full_board_verified") is not True:
            raise IntegrityError("Strict generation lacks source validation")
    rich = partial_week._saved(root, health["phase2"]["rich_scorecard_receipt"], "verification/report-originals")
    public = load_json(root / "output/data/forecast-scorecard.json")
    if (rich.get("schema_version") != "rich-scorecard-evidence-v1" or rich["report_sha256"] != digest(rich["report"])
            or rich["board_sha256"] != digest(board) or rich["source_sha"] != generation["source_sha"]
            or public != public_scorecard(rich["report"], board, generation["source_sha"])):
        raise IntegrityError("Public scorecard differs from its retained rich report")
    return generation


def stage_pages(root, destination):
    """Bounded output staging; GitHub originals remain unmodified and public."""
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(root / "output"):
        raise IntegrityError("Pages staging requires a fresh external destination")
    output = root / "output"
    if any(path.is_symlink() for path in output.rglob("*")):
        raise IntegrityError("Refusing symlink Pages asset")
    if read_phase2(root):
        validate_generation(root)
    excluded = {"data/game-status.json", "data/matchup-proof.json", "data/matchup-diagnostics.json"}
    for path in output.rglob("*"):
        if not path.is_file() or path.relative_to(output).as_posix() in excluded:
            continue
        relative = path.relative_to(output)
        # Output is an explicit static/public contract, not a scratch wildcard.
        name = relative.as_posix()
        public_data = {"data/week.json", "data/meta.json", "data/future.json", "data/teams.json", "data/track_record.json",
                       "data/dk_backtest.json", "data/forecast-scorecard.json", "data/offer-capture.json", "data/health.json",
                       "data/release-identity.json", "data/verification-scope.json"}
        allowed = (name in {"app.js", "index.html", "style.css", "reliability-ui.js", "recovery.html"}
                   or name in public_data or re.fullmatch(r"data/(?:archive|weeks)/[0-9]{4}_w[0-9]{2}\.json", name)
                   or re.fullmatch(r"data/selection-grading/(?:latest\.json|[0-9a-f]{64}/(?:summary|outcomes|rows-[0-9]{4})\.json)", name))
        if (not allowed or any(part.startswith(".") for part in relative.parts)
                or path.suffix not in (".js", ".css", ".html", ".json", ".png", ".svg", ".ico", ".txt")):
            raise IntegrityError("Unclassified Pages asset")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("live", "replay"), required=True)
    parser.add_argument("--replay-at")
    parser.add_argument("--build-and-capture", action="store_true")
    parser.add_argument("--stage-pages", type=Path)
    parser.add_argument("--validate-generation", action="store_true")
    args = parser.parse_args()
    if args.mode == "live" and args.replay_at:
        parser.error("Live capture cannot use a supplied clock")
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
