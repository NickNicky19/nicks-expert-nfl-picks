"""Our game projection: every player's projected points, rolled up into team scores.

A team's score is the touchdowns and 2-point conversions Sleeper projects for its players (passing TDs from the QB,
rushing TDs from everyone, so receiving TDs aren't counted twice), its kicker's field goals and extra points, and its
defense's touchdowns and safeties. Projections leave out scoring from unprojected players and returns, so the scores
are scaled to this season's actual average points per team (finished games only; last season's average in week 1).

From the two scores: spread, total, the home team's chance to win (margin over a 13.5-point spread of outcomes) and
fair moneylines. A lean is called when we differ from DraftKings by 2+ points on the spread or 3+ on the total.
"""
import math

SPREAD_SD = 13.5
LEAN_SPREAD = 2.0
LEAN_TOTAL = 3.0


def rollup(proj, pos_team):
    """{team: raw projected points} from player projections. pos_team: player_id -> (position, team)."""
    pts = {}
    for pid, s in proj.items():
        pos, team = pos_team.get(pid, (None, None))
        if not team:
            continue
        if pos == "DEF":
            add = 6 * (s.get("def_td") or 0) + 2 * (s.get("safe") or 0)
        elif pos == "K":
            add = 3 * (s.get("fgm") or 0) + (s.get("xpm") or 0)
        elif pos in ("QB", "RB", "WR", "TE"):
            add = 6 * ((s.get("pass_td") or 0) + (s.get("rush_td") or 0)) + 2 * ((s.get("pass_2pt") or 0) + (s.get("rush_2pt") or 0))
        else:
            continue
        pts[team] = pts.get(team, 0) + add
    return pts


def american(p):
    """Fair American odds for a win probability."""
    p = min(max(p, 0.01), 0.99)
    if abs(p - 0.5) < 0.005:
        return 100   # a true coin flip is even money for both sides
    return round(-100 * p / (1 - p)) if p > 0.5 else round(100 * (1 - p) / p)


def project(game, raw, league_avg):
    """Our numbers for one game, or None without projections for both teams."""
    h, a = raw.get(game["home"]), raw.get(game["away"])
    if not h or not a:
        return None
    return {"home_raw": h, "away_raw": a, "league_avg": league_avg}


def finish(games, raw, league_avg):
    """Scale every game's raw scores to the league average and add the derived numbers."""
    teams = [v for g in games for v in (raw.get(g["home"]), raw.get(g["away"])) if v]
    if not teams:
        return {}
    scale = league_avg / (sum(teams) / len(teams))
    out = {}
    for g in games:
        h, a = raw.get(g["home"]), raw.get(g["away"])
        if not h or not a:
            continue
        home, away = round(h * scale, 1), round(a * scale, 1)
        p_home = 0.5 * (1 + math.erf((home - away) / (SPREAD_SD * math.sqrt(2))))
        ours = {"home_pts": home, "away_pts": away, "spread": round(away - home, 1), "total": round(home + away, 1),
                "home_win": round(p_home, 3), "ml_home": american(p_home), "ml_away": american(1 - p_home)}
        odds = g.get("odds")
        if odds:
            gap = odds["spread"] - ours["spread"]          # positive: we like the home team more than DraftKings does
            ours["lean_spread"] = g["home"] if gap >= LEAN_SPREAD else g["away"] if gap <= -LEAN_SPREAD else None
            tgap = ours["total"] - odds["total"]
            ours["lean_total"] = "over" if tgap >= LEAN_TOTAL else "under" if tgap <= -LEAN_TOTAL else None
        out[g["id"]] = ours
    return out


def grade(game, ours, home_score, away_score):
    """(spread result, total result) for a finished game: 'hit', 'miss', 'push' or None (no lean)."""
    odds = game.get("odds") or {}
    res_s = res_t = None
    if ours.get("lean_spread") and odds.get("spread") is not None:
        margin = home_score - away_score + odds["spread"]       # home side covers when > 0
        if margin == 0:
            res_s = "push"
        else:
            res_s = "hit" if (margin > 0) == (ours["lean_spread"] == game["home"]) else "miss"
    if ours.get("lean_total") and odds.get("total") is not None:
        total = home_score + away_score
        if total == odds["total"]:
            res_t = "push"
        else:
            res_t = "hit" if (total > odds["total"]) == (ours["lean_total"] == "over") else "miss"
    return res_s, res_t
