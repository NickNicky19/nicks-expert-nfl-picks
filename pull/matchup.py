"""Matchup factors: how players similar to this one have done against this defense this season.

For a player at position P facing defense D, and one stat (receiving yards, say): take every game this season, before
this week, in which a player at P faced D. Compare what he did with his own average in his other games this season.
Only similar players count: their season average in that stat must be within half to double this player's (or, for a
player with no games yet, at least the category's smallest pickable line, so backups don't count).

  raw factor = total they did against D / total their averages said they would
  factor     = 1 + (raw - 1) x n / (n + 8)   (n = games: a few games barely move it), kept within 0.75 to 1.25

Last season is never used: rosters, coaches and schemes change too much.
"""
from collections import defaultdict

import scoring

PRIOR_GAMES = 8
LIMITS = (0.75, 1.25)


def played(entry):
    s = entry["stats"]
    return (s.get("gp") or 0) > 0 or (s.get("off_snp") or 0) > 0


class Matchups:
    def __init__(self, this_season_weeks, positions):
        """this_season_weeks: {week: {player_id: {"opp", "stats", ...}}} for this season's weeks before this one.
        positions: player_id -> position (skill players only)."""
        self.games = defaultdict(list)      # pid -> [(opp, stats)]
        for week in sorted(this_season_weeks):
            for pid, e in this_season_weeks[week].items():
                if pid in positions and e.get("opp") and played(e):
                    self.games[pid].append((e["opp"], e["stats"]))
        self.faced = defaultdict(list)      # (defense, position) -> [(pid, index into games[pid])]
        for pid, gl in self.games.items():
            for i, (opp, _) in enumerate(gl):
                self.faced[(opp, positions[pid])].append((pid, i))
        self.cache = {}

    def factor(self, opp, pos, key, target_avg):
        """(factor, games used) for this defense, position and stat."""
        cat = scoring.CATEGORIES[key]
        lo, hi = (0.5 * target_avg, 2 * target_avg) if target_avg else (cat["min_pick"] or 0.5, float("inf"))
        ck = (opp, pos, key, round(lo, 2), hi)
        if ck in self.cache:
            return self.cache[ck]
        did = expected = 0.0
        n = 0
        for pid, i in self.faced.get((opp, pos), []):
            gl = self.games[pid]
            if len(gl) < 2:
                continue  # no other games to say what was expected
            values = [scoring.stat_value(key, s) for _, s in gl]
            avg = (sum(values) - values[i]) / (len(values) - 1)
            if avg <= 0 or not lo <= avg <= hi:
                continue
            did += values[i]
            expected += avg
            n += 1
        if not n or expected <= 0:
            out = (1.0, 0)
        else:
            raw = did / expected
            f = 1 + (raw - 1) * n / (n + PRIOR_GAMES)
            out = (round(min(max(f, LIMITS[0]), LIMITS[1]), 3), n)
        self.cache[ck] = out
        return out
