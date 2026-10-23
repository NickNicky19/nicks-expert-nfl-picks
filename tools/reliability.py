"""Fail-closed structural checks and append-only, pregame baseline capture.

No network calls, no price fabrication, no forecasting changes. Live receipts prove
local observation before the recorded kickoff, NOT verified publication/execution.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATHS = ("pull/build.py", "pull/matchup.py", "pull/scoring.py", "pull/books.py", "pull/gamemodel.py", "pull/sources.py", "pull/news.py")
BASELINE_BLOBS = {
    "pull/build.py": "e691985174387ed0dc6ecdda1f35b55c1012499c",
    "pull/matchup.py": "3753d8e252513785dd1b9cf573f7d2616462945e",
    "pull/scoring.py": "0c532e695e7abefc2203f95344218ffc07bb4c0f",
    "pull/books.py": "406c24755aa9823311c01e3116662845854cf393",
    "pull/gamemodel.py": "9c94d3889402c702e6a7ad1d239ea8f4d22b2cdf",
    "pull/sources.py": "99b9029acf9a046a590589f001d99b242cc5576f",
    "pull/news.py": "b29edaa0cfe1df29c3ee4741d63225ab43fa8249",
}
SCHEMA_VERSION = "baseline-capture-v1"
MAX_BUILD_AGE_MINUTES = 120  # Operational freshness guard, NOT a quote-age guarantee.


class IntegrityError(ValueError):
    pass


def utc(value: str | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise IntegrityError("An explicit timezone is required")
    return value.astimezone(timezone.utc)


def stamp(value: datetime) -> str:
    return utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise IntegrityError(f"Duplicate JSON key: {key}")
        out[key] = value
    return out


def load_json(path: Path):
    def invalid(value):
        raise IntegrityError(f"Non-finite JSON value: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=invalid)


def finite(value, label, optional=True):
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise IntegrityError(f"{label} is not a finite number")


V2_HELPER_SHA256 = 'f60798eca7071525727bd883e6bd230fdb5422297efb6a7748a3457a212ab3e7'


def engine_hashes(root: Path, *, version="original_sleeper_matchup_baseline") -> dict[str, str]:
    if version == "sleeper-matchup-data-integrity-v2":
        import data_integrity_v2
        if hashlib.sha256(Path(data_integrity_v2.__file__).read_bytes()).hexdigest() != V2_HELPER_SHA256:
            raise IntegrityError("Corrected source dispatcher changed")
        return data_integrity_v2.engine_files(root)
    if version != "original_sleeper_matchup_baseline":
        raise IntegrityError("Unknown explicit engine contract")
    # Missing source files are a hard error in real runs. Tests may pass explicit hashes.
    hashes = {}
    for name in ENGINE_PATHS:
        content = (root / name).read_bytes()
        git_blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if git_blob != BASELINE_BLOBS[name]:
            raise IntegrityError(f"Original engine changed: {name}. Version the model explicitly before capture.")
        hashes[name] = hashlib.sha256(content).hexdigest()
    return hashes


def validate(data: dict, meta: dict, observed_at: datetime, max_age_minutes=MAX_BUILD_AGE_MINUTES) -> dict:
    observed_at = utc(observed_at)
    generated = utc(data["generated_at"])
    if generated > observed_at:
        raise IntegrityError("Build timestamp is in the future")
    finite(max_age_minutes, "max_age_minutes", False)
    if max_age_minutes <= 0:
        raise IntegrityError("Freshness window must be positive")
    age = (observed_at - generated).total_seconds() / 60
    if age > max_age_minutes:
        raise IntegrityError("Build is too old for new capture/publication")
    for key in ("season", "week", "generated_at"):
        if data.get(key) != meta.get(key):
            raise IntegrityError(f"week.json / meta.json mismatch: {key}")
    for key, lo, hi in (("season", 2000, 2200), ("week", 1, 18)):
        if type(data.get(key)) is not int or not lo <= data[key] <= hi:
            raise IntegrityError(f"Invalid {key}")
    games = {}
    for g in data["games"]:
        if not isinstance(g.get("id"), str) or not g["id"] or g["id"] in games:
            raise IntegrityError("Missing or duplicate game ID")
        if g.get("state") not in ("pre", "in", "post"):
            raise IntegrityError("Unknown game state")
        utc(g["kickoff"])
        games[g["id"]] = g
    players, real, estimates, prop_count = {}, 0, 0, 0
    for p in data["players"]:
        pid, gid = p.get("id"), p.get("game_id")
        if not isinstance(pid, str) or not pid or pid in players:
            raise IntegrityError("Missing or duplicate player ID")
        if gid not in games or p.get("team") not in (games[gid]["home"], games[gid]["away"]):
            raise IntegrityError("Player/game/team mismatch")
        props = {}
        for prop in p.get("props", []):
            key = prop.get("key")
            if key not in data["categories"] or key in props:
                raise IntegrityError("Unknown or duplicate prop category")
            for number in ("proj", "adj", "line", "mf", "score", "td_chance"):
                finite(prop.get(number), f"{pid}/{key}/{number}")
            if prop.get("td_chance") is not None and not 0 <= prop["td_chance"] <= 1:
                raise IntegrityError("Invalid TD probability")
            side = prop.get("lean")
            if side not in (None, "over", "under"):
                raise IntegrityError("Unknown lean direction")
            for value in prop.get("values", []):
                if value["s"] != data["season"] or value["w"] >= data["week"]:
                    raise IntegrityError("Prop history includes current/future week or another season")
                finite(value["v"], "historical stat", False)
            if prop.get("line_from") in ("dk", "sleeper"):
                finite(prop.get("line"), "real line", False)
                real += 1
                if side and prop.get("adj") is not None:
                    gap = prop["adj"] - prop["line"]
                    if gap == 0 or (side == "over") != (gap > 0):
                        raise IntegrityError("Lean contradicts adjusted projection")
            else:
                estimates += 1
            props[key] = prop
            prop_count += 1
        players[pid] = (p, props)
    seen = set()
    for side, picks in data["picks"].items():
        if side not in ("over", "under"):
            raise IntegrityError("Unknown pick list")
        for pick in picks:
            identity = (pick.get("player_id"), pick.get("key"), side)
            if identity in seen:
                raise IntegrityError("Duplicate selection")
            seen.add(identity)
            if pick.get("direction") != side or pick.get("player_id") not in players:
                raise IntegrityError("Invalid pick direction/player")
            p, props = players[pick["player_id"]]
            if pick.get("game_id") != p["game_id"] or pick.get("key") not in props or p.get("late"):
                raise IntegrityError("Pick has invalid game/category or was first seen after kickoff")
            if pick.get("line_from") not in ("dk", "sleeper"):
                raise IntegrityError("A selected pick requires a real line")
            for number in ("line", "adj"):
                finite(pick.get(number), "pick " + number, False)
            gap = pick["adj"] - pick["line"]
            if gap == 0 or (side == "over") != (gap > 0):
                raise IntegrityError("Selection contradicts its saved adjusted projection")
    if players and not games:
        raise IntegrityError("Players present without games")
    return {"schema_version": SCHEMA_VERSION, "status": "STRUCTURAL_CHECKS_PASSED",
            "checked_at": stamp(observed_at), "generated_at": data["generated_at"],
            "build_age_minutes": round(age, 2), "max_build_age_minutes": max_age_minutes,
            "players": len(players), "props": prop_count, "real_line_props": real,
            "reference_only_props": estimates, "source_timestamps_verified": False,
            "quote_freshness": "UNKNOWN", "probability_calibration": "NOT_ESTABLISHED",
            "profitability": "NOT_ESTABLISHED"}


def make_payload(data: dict, observed_at: datetime, hashes: dict, mode: str, *, model="original_sleeper_matchup_baseline") -> dict:
    if mode not in ("live", "replay"):
        raise IntegrityError("mode must be live or replay")
    games = {g["id"]: g for g in data["games"]}
    selected = {(p["player_id"], p["key"], side) for side, rows in data["picks"].items() for p in rows}
    rows = []
    skipped = set()
    for player in data["players"]:
        game = games[player["game_id"]]
        if game["state"] != "pre" or utc(game["kickoff"]) <= observed_at or player.get("late"):
            skipped.add(game["id"])
            continue
        for prop in player.get("props", []):
            if prop.get("proj") is None and prop.get("adj") is None:
                continue
            row = {"season": data["season"], "week": data["week"], "game_id": game["id"],
                   "kickoff": game["kickoff"], "player_id": player["id"], "name": player["name"],
                   "team": player["team"], "position": player["pos"], "category": prop["key"],
                   "raw_projection": prop.get("proj"), "adjusted_projection": prop.get("adj"),
                   "line": prop.get("line"), "line_from": prop.get("line_from", "ours"),
                   "lean": prop.get("lean"), "matchup_factor": prop.get("mf"),
                   "injury_at_capture": player.get("injury"),
                   "top_over": (player["id"], prop["key"], "over") in selected,
                   "top_under": (player["id"], prop["key"], "under") in selected,
                   "probability": None, "expected_value": None, "price": None,
                   "settlement_status": "NOT_VERIFIED",
                   "source_timestamps_verified": False}
            # Preserve known multipliers as observations, not as verified straight-bet prices.
            if prop.get("sleeper"):
                row["sleeper_observation"] = prop["sleeper"]
            rows.append(row)
    rows.sort(key=lambda r: (r["game_id"], r["player_id"], r["category"]))
    result = {"schema_version": SCHEMA_VERSION, "mode": mode,
            "evidence_label": "LOCAL_PRE_GAME_CAPTURE_PUBLICATION_NOT_VERIFIED" if mode == "live" else "REPLAY_TEST_NOT_PROSPECTIVE",
            "captured_at": stamp(observed_at), "forecast_generated_at": data["generated_at"],
            "input_sha256": digest(data), "engine_sha256": digest(hashes), "engine_files": hashes,
            "code_commit": os.environ.get("GITHUB_SHA"),
            "model": "original_sleeper_matchup_baseline", "rows": rows,
            "excluded_started_or_late_games": sorted(skipped)}
    if model != "original_sleeper_matchup_baseline":
        import data_integrity_v2 as corrected
        if model != corrected.MODEL or hashes != corrected.V2_SOURCE_SHA256 or not hashes:
            raise IntegrityError("Unsupported corrected capture source")
        result.update(schema_version=corrected.NATIVE, model=model, presence_contract=corrected.PRESENCE,
                      code_commit=corrected.recording_source())
    return result


def immutable_write(path: Path, payload: dict) -> bool:
    """Atomic create-only publication. Returns False for an identical existing receipt."""
    envelope = {"payload_sha256": digest(payload), "payload": payload}
    compressed = gzip.compress(canonical(envelope), mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise IntegrityError("Refusing symlink receipt")
    if path.exists():
        existing = json.loads(gzip.decompress(path.read_bytes()))
        if existing.get("payload_sha256") != digest(existing.get("payload")):
            raise IntegrityError("Existing receipt checksum mismatch")
        # The first capture timestamp wins; never rewrite it on retry.
        old, new = dict(existing["payload"]), dict(payload)
        for key in ("captured_at", "rows", "excluded_started_or_late_games", "code_commit"):
            old.pop(key, None)
            new.pop(key, None)
        if old != new:
            raise IntegrityError("Receipt identity conflict")
        return False
    fd, temp = tempfile.mkstemp(prefix=".capture-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(compressed)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)  # atomic create; never replace a pre-existing receipt
        except FileExistsError:
            return immutable_write(path, payload)
    finally:
        Path(temp).unlink(missing_ok=True)
    return True


def capture(data: dict, meta: dict, root: Path, observed_at: datetime, hashes: dict, mode="replay", max_age_minutes=MAX_BUILD_AGE_MINUTES,
            *, model="original_sleeper_matchup_baseline"):
    observed_at = utc(observed_at)
    health = validate(data, meta, observed_at, max_age_minutes)
    payload = make_payload(data, observed_at, hashes, mode, model=model)
    identity = digest({"data": digest(data), "engine": digest(hashes), "mode": mode})
    lane = "forward" if mode == "live" else "replay"
    path = root / "data" / lane / str(data["season"]) / f"w{data['week']:02d}" / (identity + ".json.gz")
    created = immutable_write(path, payload)
    stored = json.loads(gzip.decompress(path.read_bytes()))["payload"]
    health.update(capture_mode=mode, capture_created=created, receipt=str(path.relative_to(root)),
                  first_captured_at=stored["captured_at"], capture_rows=len(stored["rows"]))
    return path, health


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".json-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--mode", choices=("live", "replay"), required=True)
    parser.add_argument("--replay-at", help="An explicit test clock; forbidden in live mode")
    args = parser.parse_args()
    if args.mode == "live" and args.replay_at:
        parser.error("Live capture cannot use a supplied clock")
    now = utc(args.replay_at) if args.replay_at else datetime.now(timezone.utc)
    root = args.root.resolve()
    path, health = capture(load_json(root / "output/data/week.json"), load_json(root / "output/data/meta.json"),
                           root, now, engine_hashes(root), mode=args.mode)
    if args.mode == "live":
        atomic_json(root / "output/data/health.json", health)
    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"CRITICAL: {error}", file=sys.stderr)
        raise SystemExit(1)
