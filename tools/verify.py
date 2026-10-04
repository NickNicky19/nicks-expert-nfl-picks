"""Check the build. Run after pull/build.py:  python tools/verify.py

1. PPR: ppr_points() must equal Sleeper's own pts_ppr on every cached player-week.
2. Point in time: rebuild a sample of lines from the cache using only earlier weeks; they must match week.json.
3. Lines end in .5, players are unique, every game's teams are known, Top picks follow the pick rules.
4. Live scoring: for games that are final, PPR computed from ESPN's box score (the same way the browser does it
   live) must match Sleeper's final PPR for the same players, and nearly every ESPN player must be matched by name.
Exits 1 on any failure.
"""
import json
import re

import requests
import statistics
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pull"))
import build  # noqa: E402
import matchup  # noqa: E402
import scoring  # noqa: E402
import sources  # noqa: E402

problems = []


def problem(msg):
    problems.append(msg)
    print("  PROBLEM:", msg)


def check_ppr():
    """Skill players: our PPR and half PPR must equal Sleeper's own totals on every cached player-week."""
    n = 0
    for f in sorted((ROOT / "data" / "cache").glob("stats_*.json")):
        for pid, e in json.loads(f.read_text()).items():
            s = e["stats"]
            if e.get("pos") in ("K", "DEF") or s.get("pts_ppr") is None:
                continue
            n += 1
            for half, theirs in ((False, s.get("pts_ppr")), (True, s.get("pts_half_ppr"))):
                if theirs is None:
                    continue
                mine = scoring.fantasy_points(s, None, half=half)
                if abs(mine - theirs) > 0.011:
                    problem(f"{f.stem} {pid}: ours {mine} vs Sleeper {theirs} ({'half PPR' if half else 'PPR'})")
    print(f"1. PPR and half PPR checked on {n} player-weeks")


def check_espn_kdef(data):
    """Kickers and defenses: our ESPN-standard points must equal ESPN's own default-league totals (last finished week)."""
    week = data["week"] - 1
    if week < 1:
        return
    try:
        url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{data['season']}/segments/0/leaguedefaults/3"
        flt = {"players": {"filterSlotIds": {"value": [16, 17]}, "limit": 150, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}}
        r = requests.get(url, params={"view": "kona_player_info", "scoringPeriodId": week},
                         headers={"X-Fantasy-Filter": json.dumps(flt), "User-Agent": "Mozilla/5.0"}, timeout=60)
        players = r.json()["players"]
    except Exception as err:
        print(f"1b. ESPN kicker/defense totals unavailable ({err}); skipped")
        return
    teams = {}
    for e in sources.scoreboard(data["season"], week)["events"]:
        for c in e["competitions"][0]["competitors"]:
            teams[int(c["team"]["id"])] = sources.team_code(c["team"]["abbreviation"])
    espn = {}
    for x in players:
        pl = x["player"]
        st = next((s for s in pl.get("stats", []) if s.get("scoringPeriodId") == week and s.get("seasonId") == data["season"]
                   and s.get("statSourceId") == 0 and s.get("statSplitTypeId") == 1), None)
        if st is not None:
            team = teams.get(pl.get("proTeamId"))
            espn[("DEF", team) if pl.get("defaultPositionId") == 16 else ("K", norm_name(pl["fullName"]), team)] = st["appliedTotal"]
    cache = json.loads((ROOT / "data" / "cache" / f"stats_{data['season']}_{week:02d}.json").read_text())
    names = {p["id"]: p["name"] for p in data["players"]}
    same = total = 0
    for pid, e in cache.items():
        if e.get("pos") not in ("K", "DEF") or not e["stats"].get("gp"):
            continue
        key = ("DEF", pid) if e["pos"] == "DEF" else ("K", norm_name(names.get(pid, "")), e.get("team"))
        if key not in espn:
            continue
        total += 1
        mine = scoring.fantasy_points(e["stats"], e["pos"])
        if abs(mine - espn[key]) < 0.011:
            same += 1
        else:
            print(f"     {key}: ours {mine} vs ESPN {espn[key]}")
    print(f"1b. Kickers and defenses, week {week}: {same} of {total} match ESPN's standard scoring")
    if total and same < total:
        problem(f"{total - same} kicker/defense scores differ from ESPN's")


def check_point_in_time(data):
    """Matchup factors rebuilt from this season's earlier weeks only must match; no game from last season or from
    this week may appear in a player's chart."""
    season, week = data["season"], data["week"]
    weeks = {}
    for f in (ROOT / "data" / "cache").glob(f"stats_{season}_*.json"):
        w = int(f.stem.split("_")[2])
        if w < week:
            weeks[w] = json.loads(f.read_text())
    positions = {p["id"]: p["pos"] for p in data["players"] if p["pos"] in scoring.POSITION_CATEGORIES}
    mx = matchup.Matchups(weeks, positions)
    checked = 0
    for p in data["players"]:
        for prop in p["props"]:
            if any(v["s"] != season or v["w"] >= week for v in prop.get("values", [])):
                problem(f"{p['name']} {prop['key']}: chart includes a game from another season or this week")
            if p.get("late") or "mf" not in prop:
                continue
            avg = statistics.mean(v["v"] for v in prop["values"]) if prop["values"] else None
            f, n = mx.factor(p["opp"], p["pos"], prop["key"], avg)
            checked += 1
            if (f, n) != (prop["mf"], prop["mf_n"]):
                problem(f"{p['name']} {prop['key']}: matchup factor {prop['mf']} ({prop['mf_n']} games) but earlier weeks give {f} ({n})")
    print(f"2. {checked} matchup factors rebuilt from this season's earlier weeks only")


def check_lean_balance(data):
    """A guard against a biased projection: leans against real lines shouldn't be nearly all one way."""
    leans = [x["lean"] for p in data["players"] if not p.get("late") for x in p["props"]
             if x.get("line_from") in ("dk", "sleeper") and x["lean"]]
    if len(leans) >= 40:
        share = max(leans.count("over"), leans.count("under")) / len(leans)
        print(f"5. Leans against real lines: {leans.count('over')} over, {leans.count('under')} under")
        if share > 0.8:
            problem(f"{share:.0%} of leans go one way: the projection may be biased")
    else:
        print(f"5. Only {len(leans)} leans against real lines in unstarted games; balance not checked")


def check_shape(data):
    ids = [p["id"] for p in data["players"]]
    if len(ids) != len(set(ids)):
        problem("duplicate players in week.json")
    teams = {g["home"] for g in data["games"]} | {g["away"] for g in data["games"]}
    by_id = {p["id"]: p for p in data["players"]}
    for p in data["players"]:
        if p["team"] not in teams:
            problem(f"{p['name']} plays for {p['team']}, which has no game")
        for prop in p["props"]:
            ours = prop.get("our_line", prop["line"])
            if (ours * 2) % 2 != 1:
                problem(f"{p['name']} {prop['key']} our line {ours} does not end in .5")
            if prop.get("line_from") in ("dk", "sleeper") and prop["lean"] and prop.get("adj") is not None:
                gap = prop["adj"] - prop["line"]
                if (prop["lean"] == "over") != (gap > 0):
                    problem(f"{p['name']} {prop['key']}: lean {prop['lean']} but our number {prop['adj']} vs DraftKings {prop['line']}")
    for side, picks in data["picks"].items():
        for pick in picks:
            p = by_id.get(pick["player_id"])
            cat = scoring.CATEGORIES[pick["key"]]
            if not p:
                problem(f"{side} pick for unknown player {pick['player_id']}")
            elif ((p.get("snap_share") or 0) < build.PICK_MIN_SNAP_SHARE or (p.get("proj_ppr") or 0) < build.PICK_MIN_PROJ_PPR[p["pos"]]) and not p.get("late"):
                problem(f"{side} pick for a part-time player: {p['name']} (snap share {p.get('snap_share')}, proj {p.get('proj_ppr')})")
            elif pick.get("line_from") not in ("dk", "sleeper") or pick["line"] < cat["min_pick"] or p.get("injury") in build.UNAVAILABLE and not p.get("late"):
                problem(f"{side} pick breaks the rules: {p['name']} {pick['key']} {pick['line']}")
            if pick["direction"] != side:
                problem(f"{side} list holds a {pick['direction']} pick")
    print(f"3. Shape checked: {len(ids)} players, {len(data['games'])} games, {sum(len(v) for v in data['picks'].values())} picks")


def norm_name(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[.'’,]", "", name)
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
    return re.sub(r"\s+", " ", name).strip()


def espn_box(summary):
    """Per-player stat lines from an ESPN game summary, in Sleeper's field names (mirrors liveStatsFromSummary in app.js)."""
    players = {}
    for team in summary.get("boxscore", {}).get("players", []):
        abbr = sources.team_code(team["team"]["abbreviation"])
        for group in team.get("statistics", []):
            labels = group.get("labels", [])
            for a in group.get("athletes", []):
                key = (norm_name(a["athlete"]["displayName"]), abbr)
                s = players.setdefault(key, {})
                vals = dict(zip(labels, a.get("stats", [])))
                num = lambda k: float(vals.get(k, "0").replace("--", "0") or 0)
                if group["name"] == "passing":
                    cmp_, att = (vals.get("C/ATT", "0/0").split("/") + ["0"])[:2]
                    s.update(pass_cmp=float(cmp_), pass_att=float(att), pass_yd=num("YDS"), pass_td=num("TD"), pass_int=num("INT"))
                elif group["name"] == "rushing":
                    s.update(rush_att=num("CAR"), rush_yd=num("YDS"), rush_td=num("TD"))
                elif group["name"] == "receiving":
                    s.update(rec=num("REC"), rec_yd=num("YDS"), rec_td=num("TD"), rec_tgt=num("TGTS"))
                elif group["name"] == "fumbles":
                    s.update(fum_lost=num("LOST"))
    for play in summary.get("scoringPlays", []):
        abbr = sources.team_code(play["team"]["abbreviation"])
        for field, name in two_point_scorers(play.get("text", "")):
            s = players.setdefault((norm_name(name), abbr), {})
            s[field] = s.get(field, 0) + 1
    return players


def two_point_scorers(text):
    """(field, name) pairs for a successful 2-point conversion in an ESPN scoring play (mirrors twoPointScorers in app.js)."""
    m = re.search(r"\(([^()]+?) pass to ([^()]+?) for two-point conversion\)", text, re.I)
    if m:
        return [("pass_2pt", m.group(1)), ("rec_2pt", m.group(2))]
    m = re.search(r"\(([^()]+?) run for two-point conversion\)", text, re.I)
    if m:
        return [("rush_2pt", m.group(1))]
    return []


def check_live(data):
    finals = [g for g in data["games"] if g["state"] == "post"]
    if not finals:
        print("4. No final games yet this week; live scoring not checked")
        return
    by_key = {(norm_name(p["name"]), p["team"]): p for p in data["players"]}
    matched = unmatched = 0
    diffs = []
    for g in finals:
        summary = sources.get_json(f"{sources.ESPN}/summary", {"event": g["id"]})
        for key, stats in espn_box(summary).items():
            if not any(k in stats for k in ("pass_yd", "rush_yd", "rec")):
                continue
            p = by_key.get(key)
            if not p:
                unmatched += 1
                continue
            matched += 1
            if p.get("actual"):
                diffs.append((abs(scoring.ppr_points(stats) - p["actual"]["ppr"]), p["name"], scoring.ppr_points(stats), p["actual"]["ppr"]))
    rate = 100 * matched / max(1, matched + unmatched)
    exact = sum(1 for d in diffs if d[0] < 0.011)
    print(f"4. Live scoring on {len(finals)} final games: {matched} ESPN players matched by name ({rate:.0f}%), "
          f"{exact} of {len(diffs)} match Sleeper's final PPR exactly")
    for d, name, live, final in sorted(diffs, reverse=True)[:5]:
        if d >= 0.011:
            print(f"     {name}: live {live} vs final {final} (ESPN's and Sleeper's stat feeds sometimes credit a few yards differently)")
    if rate < 90:
        problem(f"only {rate:.0f}% of ESPN box-score players matched by name")
    if diffs and exact / len(diffs) < 0.9:
        problem(f"only {exact} of {len(diffs)} live PPR totals match the final")


def main():
    data = json.loads((ROOT / "output" / "data" / "week.json").read_text())
    print(f"Verifying season {data['season']} week {data['week']}")
    check_ppr()
    check_espn_kdef(data)
    check_point_in_time(data)
    check_shape(data)
    check_live(data)
    check_lean_balance(data)
    if problems:
        print(f"\nFAILED: {len(problems)} problem(s)")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
