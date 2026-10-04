"""Fit and check the line adjustments (the "shrink" factors in pull/scoring.py).

Run: python tools/calibrate.py

For every player-game with 4+ earlier games (point-in-time: only games before it), the line is
round_to_half(k x average of the last 8 games). k is fit per category on the earlier season so the actual result
lands under the line about 50% of the time, then checked on the later season, which the fit never saw. Only
players who would get a real line are used (their average clears the category's minimum pick line).

This tests the lines only. Leans can't be backtested here: Sleeper's projections for past weeks were last updated
after kickoff, so grading them retroactively would use information nobody had before the game.
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pull"))
import scoring  # noqa: E402

CATS = ["pass_yd", "pass_td", "pass_cmp", "pass_att", "pass_int", "rush_yd", "rush_att", "rec", "rec_yd", "rush_rec_yd", "fpts"]
GRID = [round(0.70 + 0.01 * i, 2) for i in range(41)]


def load_tests():
    weeks = {}
    for f in sorted((ROOT / "data" / "cache").glob("stats_*.json")):
        _, season, week = f.stem.split("_")
        weeks[(int(season), int(week))] = json.loads(f.read_text())
    played = lambda e: (e["stats"].get("gp") or 0) > 0
    history, tests = defaultdict(list), []
    for key in sorted(weeks):
        for pid, e in weeks[key].items():
            if played(e) and len(history[pid]) >= 4:
                tests.append((key[0], list(history[pid]), e["stats"]))
        for pid, e in weeks[key].items():
            if played(e):
                history[pid].append(e["stats"])
    return tests, sorted({s for s, _ in weeks})


def under_rate(tests, cat, k, season):
    minimum = scoring.CATEGORIES[cat]["min_pick"] or 8.5
    under = n = 0
    for s, prior, actual in tests:
        if s != season:
            continue
        values = [scoring.stat_value(cat, x) for x in prior]
        if statistics.mean(values[-8:]) < minimum:
            continue
        line = scoring.round_to_half(k * statistics.mean(values[-8:]))
        n += 1
        under += scoring.stat_value(cat, actual) < line
    return (100 * under / n if n else None), n


def main():
    tests, seasons = load_tests()
    fit_season, check_season = seasons[0], seasons[-1]
    print(f"Fit on {fit_season}, checked on {check_season} ({len(tests)} player-games)\n")
    print(f"{'category':<13}{'current k':>10}{'fitted k':>10}{f'{fit_season} under':>14}{f'{check_season} under':>14}{'n':>6}")
    fitted = {}
    for cat in CATS:
        k = min(GRID, key=lambda kk: abs((under_rate(tests, cat, kk, fit_season)[0] or 0) - 50))
        fitted[cat] = k
        fit, _ = under_rate(tests, cat, k, fit_season)
        chk, n = under_rate(tests, cat, k, check_season)
        print(f"{cat:<13}{scoring.CATEGORIES[cat]['shrink']:>10}{k:>10}{fit:>13.1f}%{(chk if chk is not None else float('nan')):>13.1f}%{n:>6}")
    print("\nFitted factors:", json.dumps(fitted))


if __name__ == "__main__":
    main()
