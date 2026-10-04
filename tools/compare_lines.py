"""Compare our lines with DraftKings' real lines (via ESPN) on finished weeks.

Run: python tools/compare_lines.py [--json output/data/dk_backtest.json]

For every finished 2026 week, each DraftKings player prop is matched to the player's actual result and to the
line we would have set before that week (point-in-time: only earlier games). It reports, per category:
  - how far our line sits from DraftKings' closing line
  - how often the result went under each line (a fair line is about 50%)
  - which line was closer to the result
  - whether the gap is a signal: when our line is well above DraftKings', did the over hit? Well below, the under?

Sleeper's projections can't be tested this way: its numbers for past weeks were revised after kickoff.
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pull"))
import books  # noqa: E402
import build  # noqa: E402
import scoring  # noqa: E402
import sources  # noqa: E402

GAP = 0.5   # a gap counts as a signal when it's at least this many of the category's typical spreads


def load_weeks():
    weeks = {}
    for f in sorted((ROOT / "data" / "cache").glob("stats_*.json")):
        _, s, w = f.stem.split("_")
        weeks[(int(s), int(w))] = json.loads(f.read_text())
    return weeks


def rows_for_week(season, week, weeks, all_players):
    stats = weeks[(season, week)]
    earlier = {k: v for k, v in weeks.items() if k < (season, week)}
    history = build.build_history(earlier)
    games = [e["id"] for e in sources.scoreboard(season, week).get("events", []) if e["status"]["type"]["completed"]]
    players = {pid: {"name": all_players.get(pid, {}).get("full_name"), "team": e.get("team"), "espn_id": all_players.get(pid, {}).get("espn_id")}
               for pid, e in stats.items()}
    lines = books.week_lines(season, week, games, players)
    rows = []
    for pid, props in lines.items():
        entry = stats.get(pid)
        if not entry or not build.played(entry):
            continue
        past = history.get(pid, [])
        for key, dk in props.items():
            values = [scoring.stat_value(key, g["stats"]) for g in past]
            center = build.line_center(key, values)
            ours = scoring.round_to_half(center) if center is not None else None
            rows.append({"week": week, "pid": pid, "key": key, "dk": dk["close"], "dk_open": dk["open"], "ours": ours,
                         "actual": scoring.stat_value(key, entry["stats"])})
    return rows, len(games), len(lines)


def pct(a, b):
    return f"{100 * a / b:5.1f}%" if b else "    -"


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="also write a summary for the site to this path")
    args = parser.parse_args()
    weeks = load_weeks()
    all_players = sources.players()
    season = max(s for s, _ in weeks)
    state = sources.nfl_state()
    current = int(state["week"]) if int(state["season"]) == season else 99
    done = sorted(w for s, w in weeks if s == season and w <= current)
    rows = []
    for week in done:
        r, n_games, n_players = rows_for_week(season, week, weeks, all_players)
        print(f"{season} week {week}: {n_games} games, {n_players} players with DraftKings props matched, {len(r)} props graded")
        rows += r
    if not rows:
        print("No DraftKings lines found.")
        return

    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["key"]].append(r)

    print(f"\n{'category':<13}{'n':>5}{'ours-DK':>9}{'|gap|':>7}{'DK under':>10}{'our under':>11}{'DK closer':>11}{'gap>0 over':>12}{'gap<0 under':>13}")
    totals = defaultdict(int)
    table = []
    for key in scoring.CATEGORIES:
        rs = [r for r in by_cat.get(key, []) if r["ours"] is not None]
        if not rs:
            continue
        scale = scoring.CATEGORIES[key]["scale"]
        diff = [r["ours"] - r["dk"] for r in rs]
        dk_under = sum(r["actual"] < r["dk"] for r in rs)
        dk_decided = sum(r["actual"] != r["dk"] for r in rs)
        our_under = sum(r["actual"] < r["ours"] for r in rs)
        dk_closer = sum(abs(r["dk"] - r["actual"]) < abs(r["ours"] - r["actual"]) for r in rs)
        ties = sum(abs(r["dk"] - r["actual"]) == abs(r["ours"] - r["actual"]) for r in rs)
        hi = [r for r in rs if r["ours"] - r["dk"] >= GAP * scale and r["actual"] != r["dk"]]
        lo = [r for r in rs if r["dk"] - r["ours"] >= GAP * scale and r["actual"] != r["dk"]]
        hi_hit = sum(r["actual"] > r["dk"] for r in hi)
        lo_hit = sum(r["actual"] < r["dk"] for r in lo)
        totals["hi"] += len(hi); totals["hi_hit"] += hi_hit; totals["lo"] += len(lo); totals["lo_hit"] += lo_hit
        totals["n"] += len(rs); totals["dk_closer"] += dk_closer; totals["ties"] += ties
        table.append({"key": key, "n": len(rs), "gap": round(statistics.mean(diff), 1),
                      "dk_under": round(100 * dk_under / dk_decided, 1) if dk_decided else None,
                      "dk_closer": round(100 * dk_closer / (len(rs) - ties), 1) if len(rs) > ties else None,
                      "below_n": len(lo), "below_under": round(100 * lo_hit / len(lo), 1) if lo else None,
                      "above_n": len(hi), "above_over": round(100 * hi_hit / len(hi), 1) if hi else None})
        totals["dk_under"] += dk_under; totals["dk_decided"] += dk_decided
        print(f"{key:<13}{len(rs):>5}{statistics.mean(diff):>+9.1f}{statistics.mean(map(abs, diff)):>7.1f}"
              f"{pct(dk_under, dk_decided):>10}{pct(our_under, len(rs)):>11}{pct(dk_closer, len(rs) - ties):>11}"
              f"{pct(hi_hit, len(hi)):>8} /{len(hi):<3}{pct(lo_hit, len(lo)):>9} /{len(lo):<3}")
    print(f"\nDraftKings' line was closer to the result {pct(totals['dk_closer'], totals['n'] - totals['ties']).strip()} of the time ({totals['n']} props, ties left out).")
    print(f"When our line was well above DraftKings', the over hit {pct(totals['hi_hit'], totals['hi']).strip()} ({totals['hi']} props).")
    print(f"When our line was well below DraftKings', the under hit {pct(totals['lo_hit'], totals['lo']).strip()} ({totals['lo']} props).")
    if args.json:
        r1 = lambda a, b: round(100 * a / b, 1) if b else None
        Path(args.json).write_text(json.dumps({
            "season": season, "weeks": done, "props": totals["n"],
            "dk_closer": r1(totals["dk_closer"], totals["n"] - totals["ties"]),
            "dk_under": r1(totals["dk_under"], totals["dk_decided"]),
            "below_under": r1(totals["lo_hit"], totals["lo"]), "below_n": totals["lo"],
            "above_over": r1(totals["hi_hit"], totals["hi"]), "above_n": totals["hi"],
            "categories": table,
        }, separators=(",", ":")))
        print("Wrote", args.json)
    no_line = sum(1 for r in rows if r["ours"] is None)
    if no_line:
        print(f"({no_line} props had no line of ours: fewer than 4 earlier games.)")


if __name__ == "__main__":
    main()
