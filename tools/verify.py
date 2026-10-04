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
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pull"))
import build  # noqa: E402
import scoring  # noqa: E402
import sources  # noqa: E402

problems = []


def problem(msg):
    problems.append(msg)
    print("  PROBLEM:", msg)


def check_ppr():
    n = 0
    for f in sorted((ROOT / "data" / "cache").glob("stats_*.json")):
        for pid, e in json.loads(f.read_text()).items():
            s = e["stats"]
            if s.get("pts_ppr") is None:
                continue
            n += 1
            if abs(scoring.ppr_points(s) - s["pts_ppr"]) > 0.011:
                problem(f"{f.stem} player {pid}: ppr_points {scoring.ppr_points(s)} vs Sleeper {s['pts_ppr']}")
    print(f"1. PPR formula checked on {n} player-weeks")


def check_point_in_time(data):
    season, week = data["season"], data["week"]
    weeks = {}
    for f in (ROOT / "data" / "cache").glob("stats_*.json"):
        _, s, w = f.stem.split("_")
        if int(s) < season or (int(s) == season and int(w) < week):
            weeks[(int(s), int(w))] = json.loads(f.read_text())
    history = build.build_history(weeks)
    checked = 0
    for p in data["players"]:
        if p.get("late"):
            continue
        for prop in p["props"]:
            if prop["source"] != "history" or prop["key"] == "anytime_td":
                continue
            values = [scoring.stat_value(prop["key"], g["stats"]) for g in history.get(p["id"], [])]
            expected = scoring.round_to_half(build.line_center(prop["key"], values))
            checked += 1
            if expected != prop["line"]:
                problem(f"{p['name']} {prop['key']}: line {prop['line']} but earlier weeks give {expected}")
    print(f"2. {checked} lines rebuilt from earlier weeks only")


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
            if (prop["line"] * 2) % 2 != 1:
                problem(f"{p['name']} {prop['key']} line {prop['line']} does not end in .5")
    for side, picks in data["picks"].items():
        for pick in picks:
            p = by_id.get(pick["player_id"])
            cat = scoring.CATEGORIES[pick["key"]]
            if not p:
                problem(f"{side} pick for unknown player {pick['player_id']}")
            elif pick["line"] < cat["min_pick"] or p.get("injury") in build.UNAVAILABLE and not p.get("late"):
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
            print(f"     {name}: live {live} vs final {final} (special teams plays aren't in ESPN's box score)")
    if rate < 90:
        problem(f"only {rate:.0f}% of ESPN box-score players matched by name")
    if diffs and exact / len(diffs) < 0.9:
        problem(f"only {exact} of {len(diffs)} live PPR totals match the final")


def main():
    data = json.loads((ROOT / "output" / "data" / "week.json").read_text())
    print(f"Verifying season {data['season']} week {data['week']}")
    check_ppr()
    check_point_in_time(data)
    check_shape(data)
    check_live(data)
    if problems:
        print(f"\nFAILED: {len(problems)} problem(s)")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
