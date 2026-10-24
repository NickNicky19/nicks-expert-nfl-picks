"""Run the byte-identical retained builder and preserve its exact matchup inputs.

Instrumentation wraps its existing functions; no model/source/selection edits.
Frozen games retain a pointer to their original input receipt. Missing historical
proof is an error, never repaired by fetching a newer roster after the fact.
"""
import argparse
import copy
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pull"))
import build
from evidence import write
from offers import SOURCE, TARGETS
from reliability import IntegrityError, atomic_json, digest, engine_hashes, load_json, stamp, utc
from source_evidence import HASH_FORMAT, record_scoreboard
import data_integrity_v2 as corrected


def record_build(root=ROOT, run=None, *, mode="live", model="original_sleeper_matchup_baseline"):
    if mode not in ("live", "replay"):
        raise IntegrityError("Recorded build mode must be live or replay")
    root = Path(root)
    started = datetime.now(timezone.utc)
    hashes = engine_hashes(root, version=model)
    modern = model == corrected.MODEL
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
    projection_input_components = {}
    projection_url = None
    game_status = {}
    source_requests = []

    def record_source(url, params=None, *args, **kwargs):
        nonlocal projection_url
        try:
            response = original_get(url, params, *args, **kwargs)
        except Exception as err:
            if url == SOURCE:
                observation.update(status="unavailable", collected_at=stamp(datetime.now(timezone.utc)),
                                   error=type(err).__name__)
            raise
        collected = datetime.now(timezone.utc)
        response_hash = None
        if (url.endswith("/v1/players/nfl") or "/stats/nfl/" in url
                or "/projections/nfl/" in url):
            # This response is unchanged while its retained components are
            # copied below. Hash its actual bytes once per request, never once
            # per player or through a shared/concurrent request's list entry.
            response_hash = corrected.model_input_hash(response) if modern else digest(response)
            source_requests.append({"url": url, "params": copy.deepcopy(params),
                                    "collected_at": stamp(collected),
                                    "response_sha256": response_hash,
                                    "response_hash_format": corrected.MODEL_INPUT_HASH if modern else HASH_FORMAT})
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
                    if modern:
                        projection_input_components[str(row["player_id"])] = {
                            "stats": {key: build.scoring.retained_value(copy.deepcopy(value)) for key, value in (row.get("stats") or {}).items()
                                      if key in build.scoring.STAT_KEYS},
                            "collected_at": stamp(collected),
                            "source": url, "source_response_sha256": response_hash,
                            "claim": "RETAINED_MODEL_INPUT_COMPONENTS_NOT_INDEPENDENT_PROVIDER_AUTHENTICATION"}
        if url == build.sources.ESPN + "/scoreboard" and isinstance(response, dict) and isinstance(params, dict):
            key = f"{params.get('dates')}_{int(params.get('week', 0)):02d}"
            game_status.setdefault(key, record_scoreboard(response, params, collected, mode=mode, source=url))
        return response

    def instrument(weeks, positions):
        if recorded:
            raise IntegrityError("Ambiguous repeated Matchups initialization")
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
    completed = datetime.now(timezone.utc)
    data = load_json(previous_path)
    if not recorded:
        raise RuntimeError("Builder did not record matchup inputs")
    payload = {"schema_version": "matchup-inputs-v2", "mode": mode, "code_commit": os.environ.get("GITHUB_SHA"),
               "build_started_at": stamp(started), "recorded_at": stamp(completed),
               "season": data["season"], "week": data["week"],
               "output_sha256": digest(data), "engine_files": hashes,
               "positions": recorded["positions"], "weeks": {str(w): rows for w, rows in recorded["weeks"].items()},
               "inputs_observed_at": recorded["inputs_observed_at"], "week_data": data,
               "offer_observation": observation, "projection_metadata": projection_metadata,
               "game_status": game_status, "source_requests": source_requests}
    if modern:
        payload.update(schema_version=corrected.INPUTS, model=corrected.MODEL,
                       presence_contract=corrected.PRESENCE,
                       code_commit=corrected.recording_source(),
                       projection_input_components=projection_input_components)
    path = write(root, "verification", payload)
    name = path.relative_to(root).as_posix()
    prior_valid = (pointer.get("output_sha256") == digest(previous) and
                   (previous.get("season"), previous.get("week")) == (data["season"], data["week"]))
    origins = {}
    for game in data["games"]:
        frozen = (game["state"] != "pre" or utc(game["kickoff"]) <= utc(data["generated_at"])
                  or utc(game["kickoff"]) <= completed)
        origins[game["id"]] = pointer.get("game_origins", {}).get(game["id"]) if frozen and prior_valid else (None if frozen else name)
    atomic_json(pointer_path, {"schema_version": corrected.PROOF if modern else "matchup-proof-v1", "output_sha256": digest(data),
                              "latest_inputs": name, "game_origins": origins})
    atomic_json(root / "output/data/game-status.json", {"schema_version": "ESPN-game-status-v1", "weeks": game_status})
    print(f"Recorded {len(recorded['positions'])} matchup positions: {name}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-all", action="store_true")
    parser.add_argument("--model", choices=("original_sleeper_matchup_baseline", corrected.MODEL),
                        default="original_sleeper_matchup_baseline")
    args = parser.parse_args()
    record_build(run=lambda: build.run(refresh_all=args.refresh_all), model=args.model)


if __name__ == "__main__":
    main()
