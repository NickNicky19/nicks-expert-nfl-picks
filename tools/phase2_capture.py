"""Baseline receipt -> contemporaneous shadow -> offers -> outcomes -> scorecard.

Live CLI uses the actual clock. Replay writes only separate evidence lanes.
No branch update, website deployment or production-model promotion occurs here.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path

from evidence import read, write
from offers import capture_offers
from release_mode import read_mode, read_phase2
from reliability import IntegrityError, atomic_json, capture, digest, engine_hashes, load_json, stamp, utc
from scorecard import build_scorecard, latest_outcomes
from selection_publication import all_ten_outcome_identities, publish_selection_report
from shadow import evaluate, make_shadow
from verify import require_offline

ROOT = Path(__file__).resolve().parents[1]


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
    root = Path(root)
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
    check_path = write(root, "matchup_checks" if mode == "live" else "matchup_checks_replay", {
        "schema_version": "matchup-verification-v1", "season": data["season"], "week": data["week"],
        "mode": mode, "verified_at": stamp(now), "output_sha256": digest(data),
        "engine_files": inputs["engine_files"], "latest_inputs": pointer["latest_inputs"],
        "latest_inputs_sha256": digest(inputs), "game_origins": pointer["game_origins"],
        "checked_factors": verification["checked_factors"],
        "baseline_receipt": baseline_path.relative_to(root).as_posix(), "baseline_payload_sha256": digest(baseline),
        "scope": "LOCAL_ORIGINAL_INPUT_REPRODUCTION_PUBLICATION_AND_PROVIDER_ASOF_NOT_VERIFIED"})
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
