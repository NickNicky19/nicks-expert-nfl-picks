"""Grade archived weeks into a track record.

Each week's archive (output/data/archive/<season>_wNN.json) holds the picks and leans as they stood when each game
kicked off. A pick or lean is graded only once its game is final; a player with no stats (or no snaps) is a DNP,
not a miss.
"""
import json
import statistics

import scoring


def played(entry):
    s = entry["stats"]
    return (s.get("gp") or 0) > 0 or (s.get("off_snp") or 0) > 0


def result(direction, value, line):
    return "hit" if (value > line if direction == "over" else value < line) else "miss"


def tally(results):
    hit = sum(1 for r in results if r == "hit")
    miss = sum(1 for r in results if r == "miss")
    return {"hit": hit, "miss": miss, "dnp": sum(1 for r in results if r == "dnp"), "pct": round(100 * hit / (hit + miss), 1) if hit + miss else None}


def grade_week(archive, stats, final_games):
    """final_games: game ids known to be final (None means every game of the week is final)."""
    players = {p["id"]: p for p in archive["players"]}

    def done(game_id):
        return final_games is None or game_id in final_games

    def actual(pid):
        entry = stats.get(pid)
        return entry if entry and played(entry) else None

    out = {"season": archive["season"], "week": archive["week"]}
    for side in ("over", "under"):
        graded = []
        for p in archive["picks"].get(side, []):
            if not done(p["game_id"]):
                continue
            a = actual(p["player_id"])
            value = round(scoring.stat_value(p["key"], a["stats"]), 2) if a else None
            graded.append({
                "name": players.get(p["player_id"], {}).get("name", p["player_id"]), "key": p["key"], "line": p["line"],
                "proj": p["proj"], "direction": side, "actual": value, "result": result(side, value, p["line"]) if a else "dnp",
            })
        out[f"top_{side}"] = {**tally([g["result"] for g in graded]), "picks": graded}

    lean_results, by_cat, dk_results = [], {}, []
    ppr_errors, line_errors, bias = [], [], []
    match = {"soft": [], "neutral": [], "tough": []}
    for p in archive["players"]:
        if not done(p["game_id"]) or p.get("late"):
            continue
        a = actual(p["id"])
        if not a:
            continue
        for prop in p["props"]:
            dk = prop.get("line_from") in ("dk", "sleeper")  # a real line
            if prop["lean"] and (dk or prop["source"] == "history") and prop["key"] != "anytime_td":
                r = result(prop["lean"], scoring.stat_value(prop["key"], a["stats"]), prop["line"])
                lean_results.append(r)
                by_cat.setdefault(prop["key"], []).append(r)
                if dk:
                    dk_results.append((prop["lean"], r))
        points = scoring.ppr_points(a["stats"])
        fpts = next((x for x in p["props"] if x["key"] == "fpts" and x["source"] == "history"), None)
        if p.get("proj_ppr") is not None and fpts:
            ppr_errors.append(abs(p["proj_ppr"] - points))
            line_errors.append(abs(fpts["line"] - points))
            bias.append(p["proj_ppr"] - points)
        if fpts and p.get("matchup") in match:
            match[p["matchup"]].append(points - fpts["line"])

    out["leans"] = {**tally(lean_results), "by_category": {k: tally(v) for k, v in sorted(by_cat.items())}}
    out["dk_leans"] = {side: tally([r for d, r in dk_results if d == side]) for side in ("over", "under")}
    out["ppr"] = {
        "n": len(ppr_errors),
        "proj_mae": round(statistics.mean(ppr_errors), 2) if ppr_errors else None,
        "average_mae": round(statistics.mean(line_errors), 2) if line_errors else None,
        "proj_bias": round(statistics.mean(bias), 2) if bias else None,
    }
    out["matchup"] = {k: {"n": len(v), "vs_line": round(statistics.mean(v), 2) if v else None} for k, v in match.items()}
    out["complete"] = final_games is None
    return out


def combine(weeks):
    total = {"weeks": len(weeks)}
    for side in ("over", "under"):
        rs = [p["result"] for w in weeks for p in w[f"top_{side}"]["picks"]]
        total[f"top_{side}"] = tally(rs)
    cats = {}
    hit = miss = 0
    for w in weeks:
        hit += w["leans"]["hit"]
        miss += w["leans"]["miss"]
        for k, t in w["leans"]["by_category"].items():
            c = cats.setdefault(k, {"hit": 0, "miss": 0})
            c["hit"] += t["hit"]
            c["miss"] += t["miss"]
    pct = lambda h, m: round(100 * h / (h + m), 1) if h + m else None
    total["leans"] = {"hit": hit, "miss": miss, "pct": pct(hit, miss),
                      "by_category": {k: {**v, "pct": pct(v["hit"], v["miss"])} for k, v in sorted(cats.items())}}
    total["dk_leans"] = {}
    for side in ("over", "under"):
        h = sum(w.get("dk_leans", {}).get(side, {}).get("hit", 0) for w in weeks)
        m = sum(w.get("dk_leans", {}).get(side, {}).get("miss", 0) for w in weeks)
        total["dk_leans"][side] = {"hit": h, "miss": m, "pct": pct(h, m)}
    n = sum(w["ppr"]["n"] for w in weeks)
    wavg = lambda key: round(sum(w["ppr"][key] * w["ppr"]["n"] for w in weeks if w["ppr"][key] is not None) / n, 2) if n else None
    total["ppr"] = {"n": n, "proj_mae": wavg("proj_mae"), "average_mae": wavg("average_mae"), "proj_bias": wavg("proj_bias")}
    total["matchup"] = {}
    for k in ("soft", "neutral", "tough"):
        n_k = sum(w["matchup"][k]["n"] for w in weeks)
        total["matchup"][k] = {"n": n_k, "vs_line": round(sum((w["matchup"][k]["vs_line"] or 0) * w["matchup"][k]["n"] for w in weeks) / n_k, 2) if n_k else None}
    return total


def grade_all(archive_dir, stats_for, current, final_games):
    weeks = []
    for path in sorted(archive_dir.glob("*.json")):
        archive = json.loads(path.read_text())
        key = (archive["season"], archive["week"])
        is_current = key == current
        stats = stats_for(*key)
        if not stats:
            continue
        weeks.append(grade_week(archive, stats, final_games if is_current else None))
    weeks.sort(key=lambda w: (w["season"], w["week"]), reverse=True)
    return {"cumulative": combine(weeks), "weeks": weeks}
