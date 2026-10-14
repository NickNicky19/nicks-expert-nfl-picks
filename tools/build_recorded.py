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

    def instrument(weeks, positions):
        recorded.update(weeks=copy.deepcopy(weeks), positions=copy.deepcopy(positions),
                        inputs_observed_at=stamp(datetime.now(timezone.utc)))
        return original(weeks, positions)

    build.Matchups = instrument
    try:
        (run or build.run)()
    finally:
        build.Matchups = original
    data = load_json(previous_path)
    if not recorded:
        raise RuntimeError("Builder did not record matchup inputs")
    payload = {"schema_version": "matchup-inputs-v1", "season": data["season"], "week": data["week"],
               "output_sha256": digest(data), "engine_files": hashes,
               "positions": recorded["positions"], "weeks": {str(w): rows for w, rows in recorded["weeks"].items()},
               "inputs_observed_at": recorded["inputs_observed_at"], "week_data": data}
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
    print(f"Recorded {len(recorded['positions'])} matchup positions: {name}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-all", action="store_true")
    args = parser.parse_args()
    record_build(run=lambda: build.run(refresh_all=args.refresh_all))


if __name__ == "__main__":
    main()
