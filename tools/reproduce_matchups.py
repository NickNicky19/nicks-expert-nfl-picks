"""Replay a saved diagnostic/input envelope without fetching a newer source.

The published-population option is a negative control reproducing the old bug.
This is a diagnostic replay; release verification also checks frozen origins.
"""
import argparse
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pull"))
import matchup
import scoring
from evidence import read
from reliability import IntegrityError, engine_hashes


def reproduce(payload, published_population=False):
    data = payload["week_data"]
    weeks = {int(w): rows for w, rows in payload["weeks"].items()}
    if any(w < 1 or w >= data["week"] for w in weeks):
        raise IntegrityError("Saved inputs contain current/future weeks")
    positions = ({p["id"]: p["pos"] for p in data["players"] if p["pos"] in scoring.POSITION_CATEGORIES}
                 if published_population else payload["positions"])
    model = matchup.Matchups(weeks, positions)
    checked, failures = 0, []
    for player in data["players"]:
        for prop in player["props"]:
            if any(v["s"] != data["season"] or v["w"] >= data["week"] for v in prop.get("values", [])):
                failures.append({"player_id": player["id"], "category": prop["key"], "reason": "future_or_other_season_history"})
            if player.get("late") or "mf" not in prop:
                continue
            avg = statistics.mean(v["v"] for v in prop["values"]) if prop["values"] else None
            factor, count = model.factor(player["opp"], player["pos"], prop["key"], avg)
            checked += 1
            if (factor, count) != (prop["mf"], prop["mf_n"]):
                failures.append({"player_id": player["id"], "category": prop["key"], "recorded": [prop["mf"], prop["mf_n"]],
                                 "reproduced": [factor, count]})
    return {"checked": checked, "population": len(positions), "failure_count": len(failures), "failures": failures,
            "input_provenance": payload.get("roster_status", "EXACT_RECORDED_BUILDER_INPUTS"),
            "control": "published_subset" if published_population else "full_recorded_population"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--published-population", action="store_true")
    args = parser.parse_args()
    engine_hashes(ROOT)
    result = reproduce(read(args.recording), args.published_population)
    print({k: v for k, v in result.items() if k != "failures"})
    raise SystemExit(1 if result["failure_count"] else 0)


if __name__ == "__main__":
    main()
