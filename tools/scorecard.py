"""Matched forward comparison. Repeated captures never create new outcomes."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import math
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pull"))
import grade
from evidence import read, write
from reliability import IntegrityError, atomic_json, digest, engine_hashes, finite, load_json, stamp, utc


def identity(row):
    return tuple(row[k] for k in ("season", "week", "game_id", "player_id", "category"))


def paired_forecasts(receipts, policy, expected_hashes, allow_replay=False):
    chosen = {}
    exclusions = Counter()
    observations = 0
    for payload in sorted(receipts, key=lambda p: (p["captured_at"], digest(p))):
        if payload.get("schema_version") != "baseline-capture-v1" or payload.get("model") != policy["baseline"]:
            raise IntegrityError("Unexpected forecast schema/model")
        if payload.get("engine_files") != expected_hashes:
            raise IntegrityError("Forecast engine does not match retained baseline")
        if payload.get("mode") != "live" and not (allow_replay and payload.get("mode") == "replay"):
            exclusions["non_live_receipt"] += 1
            continue
        captured, generated = utc(payload["captured_at"]), utc(payload["forecast_generated_at"])
        if generated > captured:
            raise IntegrityError("Forecast generated after capture")
        seen = set()
        for row in payload["rows"]:
            if row["category"] not in policy["targets"]:
                continue
            key = identity(row)
            if key in seen:
                raise IntegrityError("Duplicate opportunity within a receipt")
            seen.add(key)
            if captured >= utc(row["kickoff"]):
                exclusions["not_pregame"] += 1
                continue
            if row.get("raw_projection") is None or row.get("adjusted_projection") is None:
                exclusions["missing_pair"] += 1
                continue
            finite(row["raw_projection"], "raw projection", optional=False)
            finite(row["adjusted_projection"], "clone projection", optional=False)
            observations += 1
            if key not in chosen:
                chosen[key] = {**row, "captured_at": payload["captured_at"],
                               "forecast_generated_at": payload["forecast_generated_at"],
                               "baseline_payload_sha256": digest(payload)}
    return chosen, {"paired_capture_rows": observations, "unique_opportunities": len(chosen),
                    "repeated_capture_rows": observations - len(chosen), "excluded": dict(exclusions)}


def snapshot_outcomes(root, pairs, observed_at, mode="live"):
    """Snapshot sourced final status and sparse statistics; never infer DNP."""
    root, observed_at = Path(root), utc(observed_at)
    groups = defaultdict(list)
    for row in pairs.values():
        groups[(row["season"], row["week"])].append(row)
    current = load_json(root / "output/data/week.json")
    paths = []
    for (season, week), rows in sorted(groups.items()):
        board_path = root / ("output/data/week.json" if (current["season"], current["week"]) == (season, week)
                             else f"output/data/weeks/{season}_w{week:02d}.json")
        cache_path = root / f"data/cache/stats_{season}_{week:02d}.json"
        board = load_json(board_path) if board_path.exists() else {"games": []}
        cache = load_json(cache_path) if cache_path.exists() else {}
        games = {g["id"]: g for g in board["games"]}
        outcomes = []
        for row in rows:
            game = games.get(row["game_id"])
            status, actual, reason = "pending", None, "game_not_confirmed_final"
            entry = cache.get(row["player_id"])
            if game and game.get("state") == "post":
                if utc(game["kickoff"]) >= observed_at:
                    raise IntegrityError("Final-game evidence has a future kickoff")
                status = grade.participation(entry)
                reason = "participation_not_confirmed"
                if status == "dnp":
                    reason = "explicit_sourced_dnp"
                elif status == "played":
                    status, reason = "resolved", "played_sparse_stats"
                    if entry.get("team") != row["team"]:
                        status, reason = "unresolved", "player_team_mismatch"
                    elif entry.get("stats", {}).get(row["category"], 0) is None:
                        status, reason = "unresolved", "explicit_null_stat"
                    else:
                        actual = entry["stats"].get(row["category"], 0)
                        finite(actual, "actual statistic", optional=False)
                        if int(actual) != actual or (row["category"] in ("rec", "rush_att") and actual < 0):
                            raise IntegrityError("Invalid integer/count outcome")
                if status != "resolved":
                    actual = None
            outcomes.append({k: row[k] for k in ("season", "week", "game_id", "player_id", "category", "team")} |
                            {"status": status, "actual": actual, "reason": reason,
                             "kickoff": game.get("kickoff") if game else None, "stats_entry": entry,
                             "game_state": game.get("state") if game else None})
        payload = {"schema_version": "forecast-outcomes-v1", "mode": mode, "season": season, "week": week,
                   "collected_at": stamp(observed_at), "source_timestamp": None,
                   "source": "existing_Sleeper_stats_cache_and_ESPN_final_game_snapshot",
                   "cache_path": cache_path.relative_to(root).as_posix(), "cache_sha256": digest(cache),
                   "game_snapshot_path": board_path.relative_to(root).as_posix(), "game_snapshot_sha256": digest(board),
                   "games": board["games"], "rows": outcomes,
                   "settlement_scope": "STATISTICAL_ONLY_NOT_VENUE_SETTLEMENT"}
        paths.append(write(root, "outcomes" if mode == "live" else "outcomes_replay", payload))
    return paths


def latest_outcomes(snapshots, allow_replay=False):
    latest = {}
    for payload in sorted(snapshots, key=lambda p: (p["collected_at"], digest(p))):
        if payload.get("schema_version") != "forecast-outcomes-v1":
            raise IntegrityError("Unexpected outcome schema")
        if payload.get("mode") != "live" and not (allow_replay and payload.get("mode") == "replay"):
            continue
        for row in payload["rows"]:
            if row["status"] == "resolved":
                if row.get("game_state") != "post" or utc(row["kickoff"]) >= utc(payload["collected_at"]):
                    raise IntegrityError("Outcome lacks confirmed past final")
                finite(row["actual"], "outcome", optional=False)
            latest[identity(row)] = {**row, "outcome_snapshot_sha256": digest(payload), "collected_at": payload["collected_at"]}
    return latest


def metrics(rows, field):
    errors = [r[field] - r["actual"] for r in rows]
    return {"n": len(errors), "mae": statistics.mean(abs(e) for e in errors) if errors else None,
            "rmse": math.sqrt(statistics.mean(e * e for e in errors)) if errors else None,
            "mean_error": statistics.mean(errors) if errors else None}


def cluster_interval(rows, policy):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["season"], row["week"])].append(abs(row["adjusted_projection"] - row["actual"]) -
                                                        abs(row["raw_projection"] - row["actual"]))
    rule = policy["uncertainty"]
    if len(groups) < rule["minimum_completed_weeks"]:
        return {"status": "insufficient_completed_weeks", "completed_weeks": len(groups), "interval": None}
    blocks = list(groups.values())
    rng = random.Random(rule["seed"])
    means = []
    for _ in range(rule["bootstrap_replicates"]):
        sampled = [blocks[rng.randrange(len(blocks))] for _ in blocks]
        means.append(sum(sum(x) for x in sampled) / sum(len(x) for x in sampled))
    means.sort()
    tail = (1 - rule["simultaneous_confidence"]) / 2
    return {"status": "available", "completed_weeks": len(groups), "cluster": "season_week",
            "confidence": rule["simultaneous_confidence"],
            "interval": [means[int(tail * len(means))], means[min(len(means) - 1, int((1 - tail) * len(means)))]]}


def score(pairs, outcomes, coverage, policy):
    by_category = {key: [] for key in policy["targets"]}
    statuses = Counter()
    lead_times = Counter()
    injuries = Counter()
    detail = []
    for key, row in sorted(pairs.items()):
        outcome = outcomes.get(key, {"status": "pending", "actual": None})
        status = outcome["status"]
        if utc(row["kickoff"]) <= utc(policy["registered_at"]):
            status = "excluded_pre_registration_game"
        elif outcome.get("kickoff") and utc(outcome["kickoff"]) != utc(row["kickoff"]):
            status = "excluded_schedule_changed"
        statuses[status] += 1
        hours = (utc(row["kickoff"]) - utc(row["captured_at"])).total_seconds() / 3600
        lead_times["under_24h" if hours < 24 else "24_to_72h" if hours <= 72 else "over_72h"] += 1
        injuries[row.get("injury_at_capture") or "no_designation_reported"] += 1
        item = {**row, "evaluation_status": status, "actual": outcome.get("actual"),
                "outcome_snapshot_sha256": outcome.get("outcome_snapshot_sha256")}
        detail.append(item)
        if status == "resolved":
            by_category[row["category"]].append(item)
    categories = {}
    for key, rows in by_category.items():
        raw, clone = metrics(rows, "raw_projection"), metrics(rows, "adjusted_projection")
        categories[key] = {"raw_sleeper": raw, "unchanged_clone": clone,
                           "paired_mae_delta_clone_minus_raw": clone["mae"] - raw["mae"] if rows else None,
                           "uncertainty": cluster_interval(rows, policy)}
    return {"schema_version": "forecast-scorecard-v1", "policy_version": policy["version"], "policy_sha256": digest(policy),
            "evidence": "LOCAL_PREGAME_OBSERVATIONS_SOURCE_ASOF_NOT_VERIFIED", "coverage": coverage,
            "outcome_status": dict(statuses), "lead_time_coverage": dict(lead_times), "injury_coverage": dict(injuries),
            "categories": categories, "rows": detail, "production_model": policy["baseline"],
            "promotion": {"enabled": False, "status": "REQUIRES_FORWARD_HOLDOUT_REVIEW_AND_EXPLICIT_APPROVAL"},
            "calibration": "NOT_ESTABLISHED", "profitability": "NOT_ESTABLISHED"}


def build_scorecard(root=ROOT, observed_at=None, mode="live", allow_replay=False):
    root = Path(root)
    now = observed_at or datetime.now(timezone.utc)
    policy = load_json(root / "config/evaluation-policy.json")
    lane = "forward" if mode == "live" else "replay"
    receipts = [read(p) for p in sorted((root / "data" / lane).rglob("*.json.gz"))]
    pairs, coverage = paired_forecasts(receipts, policy, engine_hashes(root), allow_replay=allow_replay)
    paths = snapshot_outcomes(root, pairs, now, mode=mode)
    outcome_lane = "outcomes" if mode == "live" else "outcomes_replay"
    outcomes = latest_outcomes([read(p) for p in (root / "data" / outcome_lane).rglob("*.json.gz")], allow_replay)
    report = score(pairs, outcomes, coverage, policy)
    report["generated_at"] = stamp(now)
    if allow_replay:
        report["evidence"] = "REPLAY_TEST_NOT_PROSPECTIVE"
    return report, paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    report, _ = build_scorecard(args.root)
    atomic_json(args.root / "output/data/forecast-scorecard.json", report)
    print({"coverage": report["coverage"], "outcomes": report["outcome_status"]})


if __name__ == "__main__":
    main()
