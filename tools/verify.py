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
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pull"))
import build  # noqa: E402
import matchup  # noqa: E402
import scoring  # noqa: E402
import sources  # noqa: E402
from evidence import referenced  # noqa: E402
from reliability import IntegrityError, atomic_json, digest, engine_hashes, load_json, utc  # noqa: E402
from source_evidence import HASH_FORMAT, verified_status  # noqa: E402

problems = []


def problem(msg):
    problems.append(msg)
    print("  PROBLEM:", msg)


def check_ppr(*, root=None, report=None):
    """Skill players: our PPR and half PPR must equal Sleeper's own totals on every cached player-week."""
    root, report = Path(root) if root is not None else ROOT, report or problem
    n = 0
    for f in sorted((root / "data" / "cache").glob("stats_*.json")):
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
                    report(f"{f.stem} {pid}: ours {mine} vs Sleeper {theirs} ({'half PPR' if half else 'PPR'})")
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


def _indexed(rows, key, label):
    if not isinstance(rows, list):
        raise IntegrityError(f"Missing {label}")
    result = {}
    for row in rows:
        value = row.get(key) if isinstance(row, dict) else None
        if not isinstance(value, str) or not value or value in result:
            raise IntegrityError(f"Missing or duplicate {label}")
        result[value] = row
    return result


def recorded_inputs(root, name, season, week, hashes, *, mode=None, observed_at=None):
    """Qualify a saved original input, without consulting today's roster/cache."""
    inputs = referenced(root, name, "verification")
    expected = f"data/verification/{season}/w{week:02d}/{digest(inputs)}.json.gz"
    if name != expected:
        raise IntegrityError("Matchup input content address/period does not match its payload")
    if (inputs.get("schema_version") != "matchup-inputs-v2"
            or inputs.get("mode") not in ("live", "replay")
            or (mode is not None and inputs["mode"] != mode)):
        raise IntegrityError("Original inputs lack qualified schema/live-replay provenance")
    saved = inputs["week_data"]
    if ((inputs["season"], inputs["week"]) != (season, week)
            or (saved["season"], saved["week"]) != (season, week)
            or inputs["engine_files"] != hashes):
        raise IntegrityError("Wrong season/week or engine in matchup inputs")
    if inputs["output_sha256"] != digest(saved):
        raise IntegrityError("Recorded output checksum mismatch")
    started, observed, recorded = (utc(inputs[k]) for k in
                                   ("build_started_at", "inputs_observed_at", "recorded_at"))
    generated = utc(saved["generated_at"])
    # pull/build.py truncates its generation clock to seconds. Compare the
    # observation's generation second, while keeping exact observation/seal
    # instants for the strict before-kickoff checks below.
    if not started <= observed <= recorded or observed.replace(microsecond=0) > generated or generated > recorded:
        raise IntegrityError("Inconsistent original input/build clocks")
    if observed_at is not None and recorded > utc(observed_at):
        raise IntegrityError("Original input receipt was completed after verification/capture")
    weeks = inputs["weeks"]
    if (not isinstance(weeks, dict) or any(not str(w).isdigit() or str(int(w)) != w
                                         or not 1 <= int(w) < week for w in weeks)):
        raise IntegrityError("Matchup inputs contain a current/future week or ambiguous week key")
    positions = inputs["positions"]
    if (not isinstance(positions, dict) or not positions
            or any(not isinstance(pid, str) or not pid or pos not in scoring.POSITION_CATEGORIES
                   for pid, pos in positions.items())):
        raise IntegrityError("Invalid recorded full player population")
    games = _indexed(saved["games"], "id", "original games")
    players = _indexed(saved["players"], "id", "original players")
    for player in players.values():
        _indexed(player["props"], "key", "original props")
    for request in inputs["source_requests"]:
        if (not isinstance(request.get("url"), str)
                or request.get("response_hash_format") != HASH_FORMAT
                or not re.fullmatch(r"[0-9a-f]{64}", request.get("response_sha256", ""))
                or not started <= utc(request["collected_at"]) <= recorded):
            raise IntegrityError("Invalid saved source-request observation")
    status = inputs["game_status"][f"{season}_{week:02d}"]
    if utc(status["collected_at"]) < started:
        raise IntegrityError("Game-status source predates this recorded build")
    sourced = verified_status(status, season, week, inputs["mode"], recorded)
    if set(sourced) != set(games) or any(utc(sourced[gid]["kickoff"]) != utc(game["kickoff"])
                                       or sourced[gid]["state"] != game["state"]
                                       for gid, game in games.items()):
        raise IntegrityError("Original games differ from the recorded source response")
    return inputs


def _original_game(inputs, game):
    original = _indexed(inputs["week_data"]["games"], "id", "original games")[game["id"]]
    kickoff = utc(game["kickoff"])
    if (utc(original["kickoff"]) != kickoff
            or (original["home"], original["away"]) != (game["home"], game["away"])):
        raise IntegrityError("Original game/kickoff/team mapping changed")
    if (original["state"] != "pre"
            or max(utc(inputs["inputs_observed_at"]), utc(inputs["recorded_at"]),
                   utc(inputs["week_data"]["generated_at"])) >= kickoff):
        raise IntegrityError("Original input/forecast receipt is not proven before kickoff")


def check_point_in_time(data, proof=None, *, root=None, report=None, mode=None,
                        observed_at=None, require_latest=False):
    """Rebuild factors from full original inputs; qualify original pregame clocks."""
    root, report = Path(root) if root is not None else ROOT, report or problem
    season, week = data["season"], data["week"]
    latest = None
    input_cache = {}
    try:
        proof = proof if proof is not None else load_json(root / "output/data/matchup-proof.json")
        if proof.get("output_sha256") != digest(data):
            raise IntegrityError("Matchup proof belongs to a different output")
        current_hashes = engine_hashes(root)
        games = _indexed(data["games"], "id", "current games")
        if require_latest:
            if proof.get("schema_version") != "matchup-proof-v1" or set(proof["game_origins"]) != set(games):
                raise IntegrityError("Missing or mismatched original game-origin population")
            latest = recorded_inputs(root, proof["latest_inputs"], season, week, current_hashes,
                                     mode=mode, observed_at=observed_at)
            if latest["output_sha256"] != digest(data):
                raise IntegrityError("Latest original input receipt belongs to a different output")
            if any(not name for name in proof["game_origins"].values()):
                raise IntegrityError("Original frozen matchup inputs missing")
            input_cache[proof["latest_inputs"]] = latest
            # An origin for a game without modeled props still cannot be an
            # unchecked/fabricated reference. Qualify the full game population.
            for gid, origin in proof["game_origins"].items():
                if origin not in input_cache:
                    input_cache[origin] = recorded_inputs(root, origin, season, week, current_hashes,
                                                          mode=mode, observed_at=observed_at)
                _original_game(input_cache[origin], games[gid])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
        report(f"matchup inputs unavailable or invalid: {err}; run tools/build_recorded.py")
        return
    models = {}
    checked = 0
    for p in data["players"]:
        for prop in p["props"]:
            if any(v["s"] != season or v["w"] >= week for v in prop.get("values", [])):
                report(f"{p['name']} {prop['key']}: chart includes a game from another season or this week")
            if p.get("late"):
                continue
            if "mf" not in prop:
                if require_latest and prop.get("adj") is not None:
                    report(f"{p['name']} {prop['key']}: adjusted forecast lacks a matchup factor")
                continue
            origin = proof.get("game_origins", {}).get(p["game_id"])
            if not origin:
                report(f"{p['name']} {prop['key']}: original frozen matchup inputs missing")
                continue
            try:
                if origin not in models:
                    inputs = input_cache.get(origin)
                    if inputs is None:
                        inputs = recorded_inputs(root, origin, season, week, current_hashes,
                                                 mode=mode, observed_at=observed_at)
                    models[origin] = (matchup.Matchups({int(w): rows for w, rows in inputs["weeks"].items()},
                                                      inputs["positions"]), inputs,
                                      _indexed(inputs["week_data"]["players"], "id", "original players"))
                mx, inputs, old_players = models[origin]
                old_player, game = old_players[p["id"]], games[p["game_id"]]
                old_prop = _indexed(old_player["props"], "key", "original props")[prop["key"]]
                _original_game(inputs, game)
                if (inputs["positions"].get(p["id"]) != p["pos"] or old_player["pos"] != p["pos"]
                        or old_player["opp"] != p["opp"] or old_player["game_id"] != p["game_id"]
                        or old_player["team"] != p["team"] or p["team"] not in (game["home"], game["away"])
                        or p["opp"] not in (game["home"], game["away"]) or p["opp"] == p["team"]):
                    raise IntegrityError("Recorded player/position/game/team/opponent does not match")
                if any(old_prop.get(k) != prop.get(k) for k in ("proj", "adj", "mf", "mf_n", "values")):
                    raise IntegrityError("Frozen forecast changed since its input receipt")
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
                report(f"{p['name']} {prop['key']}: invalid matchup evidence: {err}")
                continue
            avg = statistics.mean(v["v"] for v in prop["values"]) if prop["values"] else None
            f, n = mx.factor(p["opp"], p["pos"], prop["key"], avg)
            checked += 1
            if (f, n) != (prop["mf"], prop["mf_n"]):
                report(f"{p['name']} {prop['key']}: matchup factor {prop['mf']} ({prop['mf_n']} games) but earlier weeks give {f} ({n})")
    print(f"2. {checked} matchup factors rebuilt from this season's earlier weeks only")
    return {"inputs": latest, "checked_factors": checked}


def require_offline(root, data, proof, mode, observed_at):
    """Same required offline checks as the CLI, before any capture write."""
    errors = []
    try:
        check_ppr(root=root, report=errors.append)
        result = check_point_in_time(data, proof, root=root, report=errors.append, mode=mode,
                                     observed_at=observed_at, require_latest=True)
        check_shape(data, report=errors.append)
        check_lean_balance(data, report=errors.append)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
        errors.append(f"Malformed offline evidence: {err}")
    if errors:
        raise IntegrityError("Required offline verification failed: " + "; ".join(errors))
    return result


def check_lean_balance(data, *, report=None):
    """A guard against a biased projection: leans against real lines shouldn't be nearly all one way."""
    report = report or problem
    leans = [x["lean"] for p in data["players"] if not p.get("late") for x in p["props"]
             if x.get("line_from") in ("dk", "sleeper") and x["lean"]]
    if len(leans) >= 40:
        share = max(leans.count("over"), leans.count("under")) / len(leans)
        print(f"5. Leans against real lines: {leans.count('over')} over, {leans.count('under')} under")
        if share > 0.8:
            report(f"{share:.0%} of leans go one way: the projection may be biased")
    else:
        print(f"5. Only {len(leans)} leans against real lines in unstarted games; balance not checked")


def check_shape(data, *, report=None):
    report = report or problem
    ids = [p["id"] for p in data["players"]]
    if len(ids) != len(set(ids)):
        report("duplicate players in week.json")
    teams = {g["home"] for g in data["games"]} | {g["away"] for g in data["games"]}
    by_id = {p["id"]: p for p in data["players"]}
    for p in data["players"]:
        if p["team"] not in teams:
            report(f"{p['name']} plays for {p['team']}, which has no game")
        for prop in p["props"]:
            ours = prop.get("our_line", prop["line"])
            if (ours * 2) % 2 != 1:
                report(f"{p['name']} {prop['key']} our line {ours} does not end in .5")
            if prop.get("line_from") in ("dk", "sleeper") and prop["lean"] and prop.get("adj") is not None:
                gap = prop["adj"] - prop["line"]
                if (prop["lean"] == "over") != (gap > 0):
                    report(f"{p['name']} {prop['key']}: lean {prop['lean']} but our number {prop['adj']} vs DraftKings {prop['line']}")
    for side, picks in data["picks"].items():
        for pick in picks:
            p = by_id.get(pick["player_id"])
            cat = scoring.CATEGORIES[pick["key"]]
            if not p:
                report(f"{side} pick for unknown player {pick['player_id']}")
            elif ((p.get("snap_share") or 0) < build.PICK_MIN_SNAP_SHARE or (p.get("proj_ppr") or 0) < build.PICK_MIN_PROJ_PPR[p["pos"]]) and not p.get("late"):
                report(f"{side} pick for a part-time player: {p['name']} (snap share {p.get('snap_share')}, proj {p.get('proj_ppr')})")
            elif pick.get("line_from") not in ("dk", "sleeper") or pick["line"] < cat["min_pick"] or p.get("injury") in build.UNAVAILABLE and not p.get("late"):
                report(f"{side} pick breaks the rules: {p['name']} {pick['key']} {pick['line']}")
            if pick["direction"] != side:
                report(f"{side} list holds a {pick['direction']} pick")
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Required deterministic checks; use recorded inputs, no HTTP")
    parser.add_argument("--json", type=Path, help="Write the diagnostic results")
    args = parser.parse_args()
    problems.clear()
    data = json.loads((ROOT / "output" / "data" / "week.json").read_text())
    print(f"Verifying season {data['season']} week {data['week']}")
    check_ppr()
    if not args.offline:
        check_espn_kdef(data)
    check_point_in_time(data, mode="live", observed_at=datetime.now(timezone.utc), require_latest=True)
    check_shape(data)
    if not args.offline:
        check_live(data)
    check_lean_balance(data)
    if args.json:
        atomic_json(args.json, {"offline": args.offline, "problems": problems,
                               "status": "failure" if problems else "success"})
    if problems:
        print(f"\nFAILED: {len(problems)} problem(s)")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
