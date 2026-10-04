"""Build this week's props, PPR projections and Top Overs/Unders into output/data/.

Run: python pull/build.py

Lines are self-generated (no paid odds): each player's per-game baseline, rounded to x.5. The projection is
Sleeper's (RotoWire) projected stat line. A lean is the projection against the line. Everything about a player's
history uses only weeks strictly before this one, so a line never sees the game it is for.
"""
import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import books
import grade
import scoring
import sources

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "output" / "data"
ARCHIVE = OUT / "archive"

HISTORY_GAMES = 8  # games behind each line, and shown in each prop's chart and hit rate
MIN_GAMES_FOR_LINE = 4  # with fewer games, the line comes from the projection and there is no lean
TOP_N = 12
MIN_PICK_SCORE = 0.35
# Top picks are for players with real roles, not backups whose odd projection makes a big gap
PICK_MIN_SNAP_SHARE = 0.5          # average share of the team's offensive snaps over his recent games
PICK_MIN_PROJ_PPR = {"QB": 10, "RB": 6, "WR": 6, "TE": 6}
PICK_PROJ_RANGE = (0.4, 2.5)       # projection vs the line outside this means Sleeper expects a different role  # how far (in typical spreads) the projection must be from the line to be a Top pick
UNAVAILABLE = {"Out", "IR", "PUP", "Suspended", "NA", "Doubtful", "COV", "DNR"}
REGULAR_SEASON_WEEKS = 18


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))


# ---------------------------------------------------------------- loading


def trim_stats(rows):
    out = {}
    for r in rows:
        s = r.get("stats") or {}
        kept = {k: s[k] for k in scoring.STAT_KEYS if s.get(k)}
        if kept:
            out[r["player_id"]] = {"team": r.get("team"), "opp": r.get("opponent"), "stats": kept}
            pos = (r.get("player") or {}).get("position")
            if pos in ("K", "DEF"):
                out[r["player_id"]]["pos"] = pos
    return out


def week_stats(season, week, refresh):
    """Weekly stats, cached on disk. Recent weeks are refetched each run to pick up stat corrections."""
    path = CACHE / f"stats_{season}_{week:02d}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    data = trim_stats(sources.week_stats(season, week))
    dump(path, data)
    return data


def load_players():
    """(skill players, kickers and team defenses) by Sleeper id. A team defense's id is its team code."""
    keep, kdef = {}, {}
    for pid, p in (sources.players() or {}).items():
        if p.get("position") in ("K", "DEF") and p.get("team") and (p.get("active", True) or p["position"] == "DEF"):
            name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            kdef[pid] = {"name": name, "pos": p["position"], "team": p["team"], "injury": p.get("injury_status"),
                         "injury_part": p.get("injury_body_part"), "depth": p.get("depth_chart_order"), "espn_id": p.get("espn_id")}
            continue
        if p.get("position") not in scoring.POSITION_CATEGORIES or not p.get("team"):
            continue
        keep[pid] = {
            "name": p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            "pos": p["position"],
            "team": p["team"],
            "injury": p.get("injury_status"),
            "injury_part": p.get("injury_body_part"),
            "depth": p.get("depth_chart_order"),
            "number": p.get("number"),
            "years": p.get("years_exp"),
            "espn_id": p.get("espn_id"),
        }
    return keep, kdef


def load_games(season, week):
    games = []
    for e in sources.scoreboard(season, week).get("events", []):
        comp = e["competitions"][0]
        status = comp["status"]["type"]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        score = lambda side: int(sides[side]["score"]) if status["state"] != "pre" and sides[side].get("score") not in (None, "") else None
        games.append({
            "id": e["id"],
            "kickoff": e["date"],
            "state": status["state"],  # pre, in, post
            "detail": status.get("shortDetail"),
            "home": sources.team_code(sides["home"]["team"]["abbreviation"]),
            "away": sources.team_code(sides["away"]["team"]["abbreviation"]),
            "home_score": score("home"),
            "away_score": score("away"),
            "venue": (comp.get("venue") or {}).get("fullName"),
            "tv": ", ".join(b for g in comp.get("broadcasts", []) for b in g.get("names", [])),
        })
    return sorted(games, key=lambda g: (g["kickoff"], g["id"]))


def projections(season, week):
    out = {}
    for r in sources.week_projections(season, week):
        s = r.get("stats") or {}
        if s.get("pts_ppr") is None:
            continue
        out[r["player_id"]] = {k: round(v, 2) for k, v in s.items() if k in scoring.STAT_KEYS or k in ("pts_ppr",)}
    return out


# ---------------------------------------------------------------- history and matchups


def played(entry):
    s = entry["stats"]
    return (s.get("gp") or 0) > 0 or (s.get("off_snp") or 0) > 0


def build_history(weeks_by_key):
    """player_id -> games in time order: [{season, week, team, opp, stats}], only games the player played."""
    history = defaultdict(list)
    for (season, week), rows in sorted(weeks_by_key.items()):
        for pid, entry in rows.items():
            if played(entry):
                history[pid].append({"season": season, "week": week, "team": entry["team"], "opp": entry["opp"], "stats": entry["stats"]})
    return history


def defense_ranks(this_season_weeks, players):
    """For each defense and position: PPR points allowed per game, ranked 1 (most allowed, softest) to 32."""
    totals = defaultdict(lambda: defaultdict(float))  # (defense, pos) -> week -> points
    for week, rows in this_season_weeks.items():
        for pid, entry in rows.items():
            pos = players.get(pid, {}).get("pos")
            if pos and entry.get("opp") and played(entry):
                totals[(entry["opp"], pos)][week] += scoring.ppr_points(entry["stats"])
    ranks = defaultdict(dict)
    for pos in scoring.POSITION_CATEGORIES:
        per_game = {d: statistics.mean(w.values()) for (d, p), w in totals.items() if p == pos and w}
        for i, (team, pts) in enumerate(sorted(per_game.items(), key=lambda kv: -kv[1]), start=1):
            ranks[team][pos] = {"rank": i, "allowed": round(pts, 1)}
    return ranks


def matchup(ranks, opp, pos, weeks_played):
    """Soft (top 8 most points allowed) or tough (bottom 8), shown as information only until it's validated."""
    r = ranks.get(opp, {}).get(pos)
    if not r or weeks_played < 2:
        return None
    label = "soft" if r["rank"] <= 8 else "tough" if r["rank"] >= 25 else "neutral"
    return {**r, "label": label}


# ---------------------------------------------------------------- props


def line_center(key, values):
    """shrink x the average of the last 8 played games (see scoring.CATEGORIES for why), or None if too few."""
    if len(values) < MIN_GAMES_FOR_LINE:
        return None
    return scoring.CATEGORIES[key]["shrink"] * statistics.mean(values[-HISTORY_GAMES:])


def player_props(player, proj, games, season):
    recent = games[-HISTORY_GAMES:]
    props = []
    for key in scoring.POSITION_CATEGORIES[player["pos"]]:
        cat = scoring.CATEGORIES[key]
        projection = round(scoring.stat_value(key, proj), 2) if proj else None
        values = [{"s": g["season"], "w": g["week"], "opp": g["opp"], "v": round(scoring.stat_value(key, g["stats"]), 2)} for g in recent]
        if key == "anytime_td":
            line = 0.5
            chance = round(scoring.td_probability(projection or 0), 3)
            lean = "over" if chance >= 0.5 else None
            source = "fixed"
        else:
            base = line_center(key, [scoring.stat_value(key, g["stats"]) for g in games])
            if base is None and projection is None:
                continue
            line = scoring.round_to_half(base if base is not None else projection)
            source = "history" if base is not None else "projection"
            chance = None
            lean = None
            if projection is not None and source == "history":
                # Compare on the same scale: the line is shrink x average, so shrink the projection (also an
                # average) the same way. A lean means Sleeper's projection differs from the player's recent average.
                diff = cat["shrink"] * projection - line
                lean = "over" if diff > cat["lean"] else "under" if diff < -cat["lean"] else None
        over = sum(1 for x in values if x["v"] > line)
        # The number the lean compares to the line (Sleeper's projection on the same scale as the line)
        adj = round(cat["shrink"] * projection, 1) if projection is not None and cat["shrink"] else None
        props.append({
            "key": key, "line": line, "proj": projection, "adj": adj, "lean": lean, "source": source,
            "over": over, "n": len(values), "values": values, **({"td_chance": chance} if chance is not None else {}),
        })
    return props


def apply_book(props, lines, picks_lines=None):
    """Use a real line wherever there is one: DraftKings first, then Sleeper Picks. Ours stays as our_line.

    Leans are then measured against that line, using our number (Sleeper's projection on the same scale as our
    line). DraftKings' pregame lines freeze at kickoff, so this is safe to run on games that have started.
    """
    picks_lines = picks_lines or {}
    for p in props:
        if p["key"] == "anytime_td":
            continue
        p.setdefault("our_line", p["line"])
        dk = lines.get(p["key"])
        slp = picks_lines.get(p["key"])
        if slp:
            p["sleeper"] = slp
        if dk:
            line = dk["close"]
            p.update(line=line, dk_open=dk["open"], line_from="dk")
        elif slp:
            line = slp["line"]
            p.update(line=line, line_from="sleeper")
        else:
            p["line_from"] = "ours"
            continue
        cat = scoring.CATEGORIES[p["key"]]
        diff = p["adj"] - line if p.get("adj") is not None else None
        p["lean"] = None if diff is None else "over" if diff > cat["lean"] else "under" if diff < -cat["lean"] else None
        p["over"] = sum(1 for x in p["values"] if x["v"] > line)
    return props


def snap_share(games):
    """Average share of the team's offensive snaps over his last 4 games played (None without snap data)."""
    shares = [g["stats"]["off_snp"] / g["stats"]["tm_off_snp"] for g in games[-4:]
              if g["stats"].get("tm_off_snp") and g["stats"].get("off_snp") is not None]
    return round(statistics.mean(shares), 2) if shares else None


def pick_candidates(entry):
    """The player's single best over and best under against DraftKings' lines, scored in typical spreads."""
    best = {}
    if entry.get("injury") in UNAVAILABLE or entry["games_this_season"] < 2:
        return best
    if (entry.get("snap_share") or 0) < PICK_MIN_SNAP_SHARE or (entry.get("proj_ppr") or 0) < PICK_MIN_PROJ_PPR[entry["pos"]]:
        return best
    for p in entry["props"]:
        if p["key"] not in scoring.PICKABLE or p["proj"] is None or p.get("line_from") not in ("dk", "sleeper") or not p["lean"]:
            continue
        if p["line"] < scoring.CATEGORIES[p["key"]]["min_pick"]:
            continue
        cat = scoring.CATEGORIES[p["key"]]
        if p["line"] > 0 and not PICK_PROJ_RANGE[0] <= p["proj"] / p["line"] <= PICK_PROJ_RANGE[1]:
            continue
        score = (cat["shrink"] * p["proj"] - p["line"]) / cat["scale"]
        side = p["lean"]
        if abs(score) < MIN_PICK_SCORE:
            continue
        if side not in best or abs(score) > abs(best[side]["score"]):
            best[side] = {"key": p["key"], "line": p["line"], "line_from": p["line_from"], "our_line": p.get("our_line"), "proj": p["proj"], "adj": p["adj"], "score": round(score, 2), "over": p["over"], "n": p["n"]}
    return best


def build_picks(entries, frozen_picks, started_games):
    picks = {"over": [], "under": []}
    for side in picks:
        # Picks in games that have kicked off stay exactly as they were
        # (only picks against real lines: picks made against our own lines before the switch are dropped)
        kept = [p for p in frozen_picks.get(side, []) if p["game_id"] in started_games and p.get("line_from") in ("dk", "sleeper")]
        fresh = []
        for e in entries:
            if e["game_id"] in started_games:
                continue
            c = pick_candidates(e).get(side)
            if c:
                fresh.append({"player_id": e["id"], "game_id": e["game_id"], "direction": side, **c})
        fresh.sort(key=lambda p: -abs(p["score"]))
        picks[side] = sorted((kept + fresh[: max(0, TOP_N - len(kept))])[:TOP_N], key=lambda p: -abs(p["score"]))
    return picks


# ---------------------------------------------------------------- main


def assemble(season, week, players, games, proj, history, ranks, weeks_played, previous, started, book, picks_lines):
    """Every player's props for one week, plus the Top picks. Entries in games that already started come from
    `previous` unchanged, so nothing about a game moves after kickoff."""
    prev_players = {p["id"]: p for p in previous.get("players", [])}
    game_of_team = {}
    for g in games:
        game_of_team[g["home"]] = (g, g["away"], True)
        game_of_team[g["away"]] = (g, g["home"], False)

    entries = []
    for pid, p in players.items():
        if p["team"] not in game_of_team:
            continue  # bye week
        g, opp, home = game_of_team[p["team"]]
        if g["id"] in started and pid in prev_players:
            entry = dict(prev_players[pid], injury=p["injury"])
            if any("line_from" not in x for x in entry["props"] if x["key"] != "anytime_td"):
                # Built before DraftKings lines were added: attach the closing lines (fixed at kickoff), leaving
                # the projection exactly as it was frozen
                apply_book(entry["props"], book.get(pid, {}))
            entries.append(entry)
            continue
        late = g["id"] in started  # first seen after kickoff: shown, but never graded
        hist = history.get(pid, [])
        pr = proj.get(pid)
        this_n = sum(1 for x in hist if x["season"] == season)
        if not pr and this_n == 0:
            continue  # nobody expects him to play
        if pr and (pr.get("pts_ppr") or 0) < 0.5 and this_n == 0:
            continue
        props = apply_book(player_props(p, pr, hist, season), book.get(pid, {}), picks_lines.get(pid, {}))
        if not props:
            continue
        entries.append({
            "id": pid, "name": p["name"], "pos": p["pos"], "team": p["team"], "number": p["number"],
            "opp": opp, "home": home, "game_id": g["id"],
            "injury": p["injury"], "injury_part": p["injury_part"], "depth": p["depth"],
            "proj_ppr": pr.get("pts_ppr") if pr else None,
            "proj": {k: v for k, v in (pr or {}).items() if k != "pts_ppr" and v},
            "games_this_season": this_n, "games_last_season": sum(1 for x in hist if x["season"] == season - 1),
            "snap_share": snap_share(hist),
            "avg_ppr": round(statistics.mean(scoring.ppr_points(x["stats"]) for x in hist if x["season"] == season), 2) if this_n else None,
            "matchup": matchup(ranks, opp, p["pos"], weeks_played),
            "props": props,
            **({"late": True} if late else {}),
        })
    entries.sort(key=lambda e: -(e["proj_ppr"] or 0))
    return entries, build_picks(entries, previous.get("picks", {}), started)


def kdef_entries(season, kdef, games, proj, history, previous, started):
    """Kickers and team defenses: fantasy points only (no props). Same freezing rule as everyone else."""
    prev_players = {p["id"]: p for p in previous.get("players", [])}
    sides = {}
    for g in games:
        sides[g["home"]] = (g, g["away"], True)
        sides[g["away"]] = (g, g["home"], False)
    out = []
    for pid, p in kdef.items():
        if p["team"] not in sides:
            continue
        g, opp, home = sides[p["team"]]
        if g["id"] in started and pid in prev_players:
            out.append(dict(prev_players[pid], injury=p["injury"]))
            continue
        pr = proj.get(pid)
        hist = [x for x in history.get(pid, []) if x["season"] == season]
        if not pr and not hist:
            continue
        pts = [scoring.fantasy_points(x["stats"], p["pos"], x["season"]) for x in hist]
        out.append({
            "id": pid, "name": p["name"], "pos": p["pos"], "team": p["team"], "opp": opp, "home": home, "game_id": g["id"],
            "injury": p["injury"], "injury_part": p["injury_part"], "depth": p["depth"],
            "proj_ppr": pr.get("pts_ppr") if pr else None, "games_this_season": len(hist),
            "avg_ppr": round(statistics.mean(pts), 2) if pts else None, "props": [],
            **({"late": True} if g["id"] in started else {}),
        })
    return out


def archive_of(season, week, entries, picks, now):
    return {
        "season": season, "week": week, "saved_at": now,
        "picks": picks,
        "players": [{
            "id": e["id"], "name": e["name"], "pos": e["pos"], "team": e["team"], "opp": e["opp"], "game_id": e["game_id"],
            "proj_ppr": e["proj_ppr"], "matchup": (e.get("matchup") or {}).get("label"), "late": e.get("late", False),
            "props": [{k: p[k] for k in ("key", "line", "proj", "lean", "source")} for p in e["props"]],
        } for e in entries],
    }


def load_stats_through(season, last_week, refresh_from):
    """Last season plus this season's weeks 1..last_week."""
    weeks_by_key = {}
    for w in range(1, REGULAR_SEASON_WEEKS + 1):
        weeks_by_key[(season - 1, w)] = week_stats(season - 1, w, refresh=refresh_from == 1)
    for w in range(1, last_week + 1):
        weeks_by_key[(season, w)] = week_stats(season, w, refresh=w >= refresh_from)
    return weeks_by_key


def point_in_time(weeks_by_key, season, week, players):
    """History and defense ranks using only weeks strictly before `week` of `season`."""
    before = {k: v for k, v in weeks_by_key.items() if k[0] < season or (k[0] == season and k[1] < week)}
    this_season = {w: rows for (s, w), rows in before.items() if s == season}
    return build_history(before), defense_ranks(this_season, players), len(this_season)


def run(refresh_all=False):
    state = sources.nfl_state()
    season = int(state["season"])
    week = int(state["week"]) if state.get("season_type") == "regular" else 1
    week = max(1, min(week, REGULAR_SEASON_WEEKS))
    print(f"Season {season}, week {week}")

    players, kdef = load_players()
    games = load_games(season, week)
    proj = projections(season, week)
    weeks_by_key = load_stats_through(season, week - 1, refresh_from=1 if refresh_all else week - 2)
    this_week_stats = week_stats(season, week, refresh=True)
    history, ranks, weeks_played = point_in_time(weeks_by_key, season, week, players)

    previous = {}
    prev_path = OUT / "week.json"
    if prev_path.exists():
        old = json.loads(prev_path.read_text())
        if old.get("season") == season and old.get("week") == week:
            previous = old
    now = iso(now_utc())
    started = {g["id"] for g in games if g["state"] != "pre" or g["kickoff"] <= now}

    try:
        espn_ids = {}
        book = books.week_lines(season, week, [g["id"] for g in games], players, espn_ids)
    except Exception as err:  # a DraftKings outage shouldn't stop the build; lines fall back to ours
        print("DraftKings lines unavailable:", err)
        book, espn_ids = {}, {}
    print(f"DraftKings lines for {len(book)} players")
    try:
        picks_lines = books.sleeper_lines()
    except Exception as err:
        print("Sleeper Picks lines unavailable:", err)
        picks_lines = {}
    print(f"Sleeper Picks lines for {len(picks_lines)} players")

    entries, picks = assemble(season, week, players, games, proj, history, ranks, weeks_played, previous, started, book, picks_lines)
    entries += kdef_entries(season, kdef, games, proj, history, previous, started)
    for e in entries:
        # ESPN's id lets the page match DraftKings' live lines to the player
        espn = espn_ids.get(e["id"]) or players.get(e["id"], {}).get("espn_id")
        if espn:
            e["espn_id"] = str(espn)
        actual = this_week_stats.get(e["id"])
        e["actual"] = {"stats": actual["stats"], "ppr": scoring.fantasy_points(actual["stats"], e["pos"], season)} if actual and played(actual) else None

    data = {
        "generated_at": now,
        "season": season,
        "week": week,
        "games": games,
        "players": entries,
        "picks": picks,
        "defense": ranks,
        "categories": {k: {"label": v["label"], "lean": v["lean"], "shrink": v["shrink"]} for k, v in scoring.CATEGORIES.items()},
        "scoring": scoring.PPR,
        "scoring_k": scoring.K_SCORING,
        "scoring_def": scoring.def_scoring(season),
    }
    dump(OUT / "week.json", data)
    # The page polls this small file to tell when a new build is out
    dump(OUT / "meta.json", {"generated_at": now, "season": season, "week": week})
    dump(ARCHIVE / f"{season}_w{week:02d}.json", archive_of(season, week, entries, picks, now))

    stats_for = lambda s, w: this_week_stats if (s, w) == (season, week) else week_stats(s, w, refresh=False)
    record = grade.grade_all(ARCHIVE, stats_for, current=(season, week), final_games={g["id"] for g in games if g["state"] == "post"})
    dump(OUT / "track_record.json", record)
    print(f"{len(entries)} players, {len(games)} games, {len(picks['over'])} top overs, {len(picks['under'])} top unders")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-all", action="store_true", help="refetch every cached week (both seasons)")
    args = parser.parse_args()
    run(refresh_all=args.refresh_all)
