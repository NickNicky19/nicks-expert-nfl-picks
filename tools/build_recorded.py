"""Run the byte-identical retained builder and preserve its exact matchup inputs.

Instrumentation wraps its existing functions; no model/source/selection edits.
Frozen games retain a pointer to their original input receipt. Missing historical
proof is an error, never repaired by fetching a newer roster after the fact.
"""
import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pull"))
import build
from evidence import write
from offers import SOURCE, TARGETS
from reliability import atomic_json, digest, engine_hashes, load_json, stamp


def record_build(root=ROOT, run=None):
    root = Path(root)
    hashes = engine_hashes(root)
    previous_path = root / "output/data/week.json"
    previous = load_json(previous_path) if previous_path.exists() else {}
    pointer_path = root / "output/data/matchup-proof.json"
    pointer = load_json(pointer_path) if pointer_path.exists() else {}
    recorded = {}
    original = build.Matchups
    original_get = build.sources.get_json
    observation = {"status": "unavailable", "collected_at": stamp(datetime.now(timezone.utc)),
                   "markets": None, "error": "existing_feed_request_not_observed"}
    projection_metadata = {}
    projection_url = None
    game_status = {}

    def record_source(url, params=None, *args, **kwargs):
        nonlocal projection_url
        try:
            response = original_get(url, params, *args, **kwargs)
        except Exception as err:
            if url == SOURCE:
                observation.update(status="unavailable", collected_at=stamp(datetime.now(timezone.utc)),
                                   error=type(err).__name__)
            raise
        if url == SOURCE:
            # Retain exact rows in the permitted NFL/three-statistic scope. The
            # digest fingerprints the full response without storing other sports.
            if isinstance(response, list):
                scoped = [m for m in response if not isinstance(m, dict) or
                          (m.get("sport") == "nfl" and m.get("wager_type") in TARGETS) or
                          any(isinstance(o, dict) and o.get("sport") == "nfl" and o.get("wager_type") in TARGETS
                              for o in (m.get("options") or []))]
            else:
                scoped = response
            observation.update(status="available", collected_at=stamp(datetime.now(timezone.utc)),
                               markets=copy.deepcopy(scoped), response_sha256=digest(response), error=None)
        if "/projections/nfl/" in url and projection_url is None and isinstance(response, list):
            # The first request is the current-week baseline input. Later ROS
            # requests must not replace its event/timestamp mapping.
            projection_url = url
            for row in response:
                if row.get("player_id"):
                    projection_metadata[str(row["player_id"])] = {k: row.get(k) for k in
                        ("game_id", "season", "week", "team", "opponent", "date", "updated_at", "last_modified")}
        if url == build.sources.ESPN + "/scoreboard" and isinstance(response, dict) and isinstance(params, dict):
            key = f"{params.get('dates')}_{int(params.get('week', 0)):02d}"
            if key not in game_status:
                game_status[key] = {"collected_at": stamp(datetime.now(timezone.utc)), "response_sha256": digest(response),
                                   "games": {}}
                for event in response.get("events", []):
                    status = event["competitions"][0]["status"]["type"]
                    game_status[key]["games"][event["id"]] = {"kickoff": event["date"], "state": status.get("state"),
                        "completed": status.get("completed"), "detail": status.get("shortDetail")}
        return response

    def instrument(weeks, positions):
        recorded.update(weeks=copy.deepcopy(weeks), positions=copy.deepcopy(positions),
                        inputs_observed_at=stamp(datetime.now(timezone.utc)))
        return original(weeks, positions)

    build.Matchups = instrument
    build.sources.get_json = record_source
    try:
        (run or build.run)()
    finally:
        build.Matchups = original
        build.sources.get_json = original_get
    data = load_json(previous_path)
    if not recorded:
        raise RuntimeError("Builder did not record matchup inputs")
    payload = {"schema_version": "matchup-inputs-v1", "season": data["season"], "week": data["week"],
               "output_sha256": digest(data), "engine_files": hashes,
               "positions": recorded["positions"], "weeks": {str(w): rows for w, rows in recorded["weeks"].items()},
               "inputs_observed_at": recorded["inputs_observed_at"], "week_data": data,
               "offer_observation": observation, "projection_metadata": projection_metadata,
               "game_status": game_status}
    path = write(root, "verification", payload)
    name = path.relative_to(root).as_posix()
    prior_valid = (pointer.get("output_sha256") == digest(previous) and
                   (previous.get("season"), previous.get("week")) == (data["season"], data["week"]))
    origins = {}
    for game in data["games"]:
        frozen = game["state"] != "pre" or game["kickoff"] <= data["generated_at"]
        origins[game["id"]] = pointer.get("game_origins", {}).get(game["id"]) if frozen and prior_valid else (None if frozen else name)
    atomic_json(pointer_path, {"schema_version": "matchup-proof-v1", "output_sha256": digest(data),
                              "latest_inputs": name, "game_origins": origins})
    atomic_json(root / "output/data/game-status.json", {"schema_version": "ESPN-game-status-v1", "weeks": game_status})
    print(f"Recorded {len(recorded['positions'])} matchup positions: {name}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-all", action="store_true")
    args = parser.parse_args()
    record_build(run=lambda: build.run(refresh_all=args.refresh_all))


if __name__ == "__main__":
    main()
