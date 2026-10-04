"""Sportsbook player prop lines: DraftKings, as carried by ESPN's odds API.

ESPN keeps each game's DraftKings props after the game ("open" and "current" lines; provider 100 is the pregame
book, so "current" on a finished game is the closing line). Only lines are published, not prices.

ESPN identifies players by ESPN athlete id. Sleeper only lists ESPN ids for some players, so the rest are matched
by name and team; ESPN athlete lookups are cached in data/cache/espn_athletes.json.
"""
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sources

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
PREGAME = "100"   # DraftKings pregame; 200 is DraftKings live
ATHLETES = Path(__file__).resolve().parent.parent / "data" / "cache" / "espn_athletes.json"

# ESPN prop names -> our categories (full-game lines only, overtime included like our stats)
MARKETS = {
    "Total Passing Yards (incl. overtime)": "pass_yd",
    "Total Pass Completions (incl. overtime)": "pass_cmp",
    "Total Passing Attempts (incl. overtime)": "pass_att",
    "Total Passing Touchdowns (incl. overtime)": "pass_td",
    "Total Passing Interceptions (incl. overtime)": "pass_int",
    "Total Rushing Yards (incl. overtime)": "rush_yd",
    "Total Carries (incl. overtime)": "rush_att",
    "Total Receptions (incl. overtime)": "rec",
    "Total Receiving Yards (incl. overtime)": "rec_yd",
    "Total Rushing Plus Receiving Yards (incl. overtime)": "rush_rec_yd",
}


def norm_name(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[.'’,]", "", name)
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
    return re.sub(r"\s+", " ", name).strip()


def _ref_id(ref, kind):
    m = re.search(rf"/{kind}/(\d+)", ref or "")
    return m.group(1) if m else None


def game_props(game_id):
    """[(espn_athlete_id, key, open_line, close_line)] for one game's DraftKings props. Empty if none posted."""
    url = f"{CORE}/events/{game_id}/competitions/{game_id}/odds/{PREGAME}/propBets"
    try:
        data = sources.get_json(url, {"limit": 1000})
    except Exception:
        return []
    out = []
    for item in (data or {}).get("items", []):
        key = MARKETS.get(item.get("type", {}).get("name"))
        athlete = _ref_id(item.get("athlete", {}).get("$ref"), "athletes")
        current = (item.get("current") or {}).get("target", {}).get("value")
        if not key or not athlete or current is None:
            continue
        opened = (item.get("open") or {}).get("target", {}).get("value")
        out.append((athlete, key, opened, current))
    return out


def _load_athletes():
    try:
        return json.loads(ATHLETES.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _fetch_athlete(season, espn_id):
    try:
        a = sources.get_json(f"{CORE}/seasons/{season}/athletes/{espn_id}")
    except Exception:
        return espn_id, None
    return espn_id, {"name": a.get("displayName"), "team_id": _ref_id(a.get("team", {}).get("$ref"), "teams")}


def athlete_lookup(season, espn_ids):
    """ESPN athlete id -> {name, team_id}, fetching (in parallel) only ids not already cached."""
    cache = _load_athletes()
    missing = [i for i in espn_ids if i not in cache]
    if missing:
        with ThreadPoolExecutor(8) as pool:
            for espn_id, info in pool.map(lambda i: _fetch_athlete(season, i), missing):
                if info:
                    cache[espn_id] = info
        ATHLETES.parent.mkdir(parents=True, exist_ok=True)
        ATHLETES.write_text(json.dumps(cache, separators=(",", ":"), sort_keys=True))
    return cache


def espn_team_codes(season, week):
    """ESPN team id -> team code (Sleeper's), from that week's scoreboard."""
    codes = {}
    for e in sources.scoreboard(season, week).get("events", []):
        for c in e["competitions"][0]["competitors"]:
            codes[c["team"]["id"]] = sources.team_code(c["team"]["abbreviation"])
    return codes


def week_lines(season, week, game_ids, players, espn_ids=None):
    """{sleeper_id: {key: {"open": x, "close": y}}} for the given games.

    players: Sleeper id -> {"name", "team", "espn_id" (optional)}.
    espn_ids: if given, filled with Sleeper id -> ESPN athlete id for every player matched.
    """
    with ThreadPoolExecutor(8) as pool:
        per_game = list(pool.map(game_props, game_ids))
    rows = [r for g in per_game for r in g]
    if not rows:
        return {}
    by_espn = {str(p["espn_id"]): pid for pid, p in players.items() if p.get("espn_id")}
    by_name = {(norm_name(p["name"]), p["team"]): pid for pid, p in players.items() if p.get("name")}
    unknown = sorted({a for a, *_ in rows if a not in by_espn})
    info = athlete_lookup(season, unknown) if unknown else {}
    teams = espn_team_codes(season, week)
    out = {}
    for athlete, key, opened, current in rows:
        pid = by_espn.get(athlete)
        if not pid and athlete in info:
            a = info[athlete]
            pid = by_name.get((norm_name(a["name"] or ""), teams.get(a["team_id"])))
        if pid:
            out.setdefault(pid, {})[key] = {"open": opened, "close": current}
            if espn_ids is not None:
                espn_ids[pid] = athlete
    return out


# ---------------------------------------------------------------- Sleeper Picks

SLEEPER_LINES = "https://api.sleeper.app/lines/available"
SLEEPER_MARKETS = {
    "passing_yards": "pass_yd", "pass_completions": "pass_cmp", "passing_attempts": "pass_att",
    "passing_touchdowns": "pass_td", "interceptions": "pass_int", "rushing_yards": "rush_yd",
    "rushing_attempts": "rush_att", "receptions": "rec", "receiving_yards": "rec_yd",
    "rushing_and_receiving_yards": "rush_rec_yd",
}


def sleeper_lines():
    """{sleeper_id: {key: {"line": x, "over": payout, "under": payout}}} for NFL games not yet started.

    Sleeper Picks takes lines down at kickoff, so these only exist before each game; the hourly build saves them
    then, and they stay frozen with the rest of the game's entries.
    """
    data = sources.get_json(SLEEPER_LINES, {"dynamic": "true", "include_preseason": "true", "eg": "15.control"}) or []
    out = {}
    for market in data:
        opts = market.get("options") or []
        if not opts or opts[0].get("sport") != "nfl" or opts[0].get("subject_type") != "player":
            continue
        o = opts[0]
        key = SLEEPER_MARKETS.get(o.get("wager_type"))
        if not key or o.get("line_type") != "normal" or o.get("game_status") != "pre_game":
            continue
        if key == "pass_int" and o.get("subject_position") != "QB":
            continue  # defensive interceptions use the same market name
        by_side = {x.get("outcome"): x for x in opts}
        line = by_side.get("over", o).get("outcome_value")
        if line is None:
            continue
        mult = lambda side: float(by_side[side]["payout_multiplier"]) if side in by_side and by_side[side].get("payout_multiplier") else None
        out.setdefault(str(o["subject_id"]), {})[key] = {"line": line, "over": mult("over"), "under": mult("under")}
    return out
