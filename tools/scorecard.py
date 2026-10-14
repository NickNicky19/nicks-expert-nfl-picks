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
    for payload in sorted(receipts, key=lambda p: (utc(p["captured_at"]), digest(p))):
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
    status_path = root / "output/data/game-status.json"
    observed_status = load_json(status_path).get("weeks", {}) if status_path.exists() else {}
    paths = []
    for (season, week), rows in sorted(groups.items()):
        board_path = root / ("output/data/week.json" if (current["season"], current["week"]) == (season, week)
                             else f"output/data/weeks/{season}_w{week:02d}.json")
        cache_path = root / f"data/cache/stats_{season}_{week:02d}.json"
        board = load_json(board_path) if board_path.exists() else {"games": []}
        cache = load_json(cache_path) if cache_path.exists() else {}
        games = {g["id"]: g for g in board["games"]}
        source_status = observed_status.get(f"{season}_{week:02d}")
        def confirmed_final(game):
            if game.get("state") != "post":
                return False
            if source_status is not None:
                raw = source_status["games"].get(game["id"], {})
                return raw.get("state") == "post" and raw.get("completed") is True and raw.get("kickoff") == game["kickoff"]
            # Legacy ESPN snapshots have a saved Final/Final-OT detail but did
            # not retain completed. A bare post flag can also mean cancelled.
            return str(game.get("detail", "")).lower().startswith("final")
        week_complete = bool(games) and all(confirmed_final(g) for g in games.values())
        outcomes = []
        for row in rows:
            game = games.get(row["game_id"])
            status, actual, reason = "pending", None, "game_not_confirmed_final"
            entry = cache.get(row["player_id"])
            if game and confirmed_final(game):
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
                             "game_state": game.get("state") if game else None,
                             "final_confirmed": bool(game and confirmed_final(game)), "week_confirmed_complete": week_complete})
        payload = {"schema_version": "forecast-outcomes-v1", "mode": mode, "season": season, "week": week,
                   "collected_at": stamp(observed_at), "source_timestamp": None,
                   "source": "existing_Sleeper_stats_cache_and_ESPN_final_game_snapshot",
                   "cache_path": cache_path.relative_to(root).as_posix(), "cache_sha256": digest(cache),
                   "game_snapshot_path": board_path.relative_to(root).as_posix(), "game_snapshot_sha256": digest(board),
                   "games": board["games"], "source_game_status": source_status, "rows": outcomes,
                   "settlement_scope": "STATISTICAL_ONLY_NOT_VENUE_SETTLEMENT"}
        paths.append(write(root, "outcomes" if mode == "live" else "outcomes_replay", payload))
    return paths


def _past_final(row, collected):
    return (row.get("game_state") == "post" and row.get("final_confirmed") is True
            and row.get("kickoff") is not None and utc(row["kickoff"]) < collected)


def _outcome_record(payload, row, payload_sha):
    """Keep only recorded provenance; no current-cache lookup or source-time guess."""
    collected = utc(payload["collected_at"])
    source = payload.get("source")
    path = payload.get("cache_path")
    if ((source is not None and not isinstance(source, str))
            or (path is not None and not isinstance(path, str))):
        raise IntegrityError("Invalid outcome source identity")
    source_time = utc(payload["source_timestamp"]) if payload.get("source_timestamp") else None
    if source_time is not None and source_time > collected:
        raise IntegrityError("Outcome source timestamp is after collection")
    cache_sha = payload.get("cache_sha256")
    if cache_sha is not None and (not isinstance(cache_sha, str) or len(cache_sha) != 64
                                 or any(c not in "0123456789abcdef" for c in cache_sha)):
        raise IntegrityError("Invalid outcome cache digest")
    entry = row.get("stats_entry")
    if entry is not None and not isinstance(entry, dict):
        raise IntegrityError("Invalid saved statistics entry")
    past_final = _past_final(row, collected)
    status = row["status"]
    if status not in ("pending", "unresolved", "resolved", "dnp", "void"):
        raise IntegrityError("Unexpected outcome status")
    if status == "resolved":
        if not past_final:
            raise IntegrityError("Outcome lacks confirmed past final")
        actual = row["actual"]
        finite(actual, "outcome", optional=False)
        if int(actual) != actual or row["category"] in ("rec", "rush_att") and actual < 0:
            raise IntegrityError("Invalid integer/count outcome")
        if isinstance(entry, dict):
            if grade.participation(entry) != "played" or entry.get("team") != row["team"]:
                raise IntegrityError("Resolved outcome has contradictory participation/team")
            observed = entry.get("stats", {}).get(row["category"], 0)
            finite(observed, "saved source statistic", optional=False)
            if observed != actual:
                raise IntegrityError("Resolved outcome differs from its saved source statistic")
    attributed = bool(source and source.strip())
    terminal = status == "resolved" or (past_final and attributed and
                (status == "void" or status == "dnp" and grade.participation(entry) == "dnp"))
    normalized = dict(row)
    if not terminal:
        normalized["actual"] = None
        if status in ("dnp", "void"):
            normalized.update(status="unresolved", reason="unconfirmed_exclusion")
    provenance = {"outcome_snapshot_sha256": payload_sha, "outcome_row_sha256": digest(row),
                  "collected_at": payload["collected_at"], "source": source, "cache_path": path,
                  "cache_sha256": cache_sha, "source_timestamp": payload.get("source_timestamp"),
                  "game_snapshot_sha256": payload.get("game_snapshot_sha256"),
                  "status": status, "actual": row.get("actual"), "team": row.get("team"),
                  "kickoff": row.get("kickoff"), "final_confirmed": row.get("final_confirmed"),
                  "week_confirmed_complete": row.get("week_confirmed_complete", False)}
    return {"row": normalized, "provenance": provenance, "collected": collected,
            "source_time": source_time, "origin": (payload.get("mode"), source, path),
            "attributed": attributed,
            "version": cache_sha or (digest(entry) if isinstance(entry, dict) else None),
            "terminal": terminal, "past_final": past_final}


def _confirmed_frontier(records):
    """Compare source versions within origins; never rank disagreeing sources."""
    origins = defaultdict(list)
    for record in records:
        if record["terminal"]:
            origins[record["origin"]].append(record)
    frontier = []
    for observations in origins.values():
        # Unknown origin/version cannot justify replacing a different final.
        if not all(r["attributed"] and r["version"] for r in observations):
            frontier.extend(observations)
            continue
        versions = defaultdict(list)
        for record in observations:
            versions[record["version"]].append(record)
        sourced_clock = all(r["source_time"] is not None for r in observations)
        if sourced_clock:
            order = {v: max(r["source_time"] for r in rs) for v, rs in versions.items()}
        else:
            # First observation orders distinct saved versions, not source
            # freshness. An older content version reappearing later is ambiguous.
            order = {v: min(r["collected"] for r in rs) for v, rs in versions.items()}
        newest = max(order.values())
        for version, candidates in versions.items():
            reappeared = (not sourced_clock and order[version] < newest
                          and any(r["collected"] >= newest for r in candidates))
            if order[version] == newest or reappeared:
                frontier.extend(candidates)
    return frontier


def latest_outcomes(snapshots, allow_replay=False):
    observations = defaultdict(list)
    seen = set()
    for payload in sorted(snapshots, key=lambda p: (utc(p["collected_at"]), digest(p))):
        if payload.get("schema_version") != "forecast-outcomes-v1":
            raise IntegrityError("Unexpected outcome schema")
        if payload.get("mode") != "live" and not (allow_replay and payload.get("mode") == "replay"):
            continue
        payload_sha = digest(payload)
        for row in payload["rows"]:
            record = _outcome_record(payload, row, payload_sha)
            reference = (payload_sha, record["provenance"]["outcome_row_sha256"])
            if reference not in seen:
                seen.add(reference)
                observations[identity(row)].append(record)
    latest = {}
    for key, records in observations.items():
        frontier = _confirmed_frontier(records)
        signatures = {(r["row"]["status"], r["row"].get("actual"), r["row"].get("team"),
                       utc(r["row"]["kickoff"])) for r in frontier}
        conflict = len(signatures) > 1
        # Records already have deterministic parsed-time/content order. A tie
        # can choose a representative only when every active final agrees.
        fallback = [r for r in records if r["past_final"]] or records
        if frontier and all(r["source_time"] is not None for r in frontier):
            selected = max(frontier, key=lambda r: r["source_time"])
        else:
            selected = frontier[0] if frontier else fallback[-1]
        result = {**selected["row"], "outcome_snapshot_sha256": selected["provenance"]["outcome_snapshot_sha256"],
                  "collected_at": selected["provenance"]["collected_at"],
                  "outcome_observations": [r["provenance"] for r in records],
                  "outcome_conflict": conflict,
                  "outcome_selection": "confirmed" if frontier else "incomplete_observation"}
        if conflict:
            result.update(status="unresolved", actual=None, stats_entry=None,
                          reason="conflicting_confirmed_outcomes", outcome_snapshot_sha256=None,
                          outcome_selection="conflict", collected_at=records[-1]["provenance"]["collected_at"])
        # Completion proof is separate from the statistic's selected receipt.
        # A later missing stat may still document a confirmed complete week.
        completion = [r["provenance"]["outcome_snapshot_sha256"] for r in records
                      if r["past_final"] and r["row"].get("week_confirmed_complete") is True
                      and r["row"].get("team") == selected["row"].get("team")
                      and utc(r["row"]["kickoff"]) == utc(selected["row"]["kickoff"])]
        result["week_confirmed_complete"] = bool(completion)
        result["week_completion_snapshot_sha256"] = sorted(set(completion))
        latest[key] = result
    return latest


def metrics(rows, field):
    errors = [r[field] - r["actual"] for r in rows]
    return {"n": len(errors), "mae": statistics.mean(abs(e) for e in errors) if errors else None,
            "rmse": math.sqrt(statistics.mean(e * e for e in errors)) if errors else None,
            "mean_error": statistics.mean(errors) if errors else None}


def cluster_interval(rows, policy):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["season"], row["week"])].append(row)
    rule = policy["uncertainty"]
    completed = sorted(key for key, group in groups.items()
                       if all(r.get("week_confirmed_complete") is True for r in group))
    blocks = []
    for key in completed:
        differences = [abs(r["adjusted_projection"] - r["actual"]) -
                       abs(r["raw_projection"] - r["actual"]) for r in groups[key]]
        for value in differences:
            finite(value, "completed-week paired error", optional=False)
        blocks.append((math.fsum(differences), len(differences)))
    n = sum(count for _, count in blocks)
    coverage = {"completed_weeks": len(completed), "observed_week_clusters": len(groups),
                "resampled_week_clusters": len(completed), "resampled_outcomes": n,
                "excluded_incomplete_week_clusters": len(groups) - len(completed),
                "excluded_incomplete_outcomes": len(rows) - n, "cluster": "season_week",
                "interval_population": "completed_weeks_only",
                "completed_week_mae_delta_clone_minus_raw": math.fsum(total for total, _ in blocks) / n if n else None}
    if len(completed) < rule["minimum_completed_weeks"]:
        return {**coverage, "status": "insufficient_completed_weeks", "interval": None}
    rng = random.Random(rule["seed"])
    means = []
    for _ in range(rule["bootstrap_replicates"]):
        sampled = [blocks[rng.randrange(len(blocks))] for _ in blocks]
        means.append(math.fsum(total for total, _ in sampled) / sum(count for _, count in sampled))
    means.sort()
    tail = (1 - rule["simultaneous_confidence"]) / 2
    return {**coverage, "status": "available", "confidence": rule["simultaneous_confidence"],
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
                "outcome_snapshot_sha256": outcome.get("outcome_snapshot_sha256"),
                "outcome_observations": outcome.get("outcome_observations", []),
                "outcome_conflict": outcome.get("outcome_conflict", False),
                "outcome_selection": outcome.get("outcome_selection"),
                "week_completion_snapshot_sha256": outcome.get("week_completion_snapshot_sha256", []),
                "week_confirmed_complete": outcome.get("week_confirmed_complete", False)}
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
