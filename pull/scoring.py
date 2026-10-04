"""PPR scoring and the prop categories.

PPR uses Sleeper's standard settings. ppr_points() reproduces Sleeper's own pts_ppr exactly on every
player-week checked (tools/verify.py re-checks it on each run).
"""
import math

PPR = {
    "pass_yd": 0.04, "pass_td": 4, "pass_int": -1, "pass_2pt": 2,
    "rush_yd": 0.1, "rush_td": 6, "rush_2pt": 2,
    "rec": 1, "rec_yd": 0.1, "rec_td": 6, "rec_2pt": 2,
    "fum_lost": -2,
    # Special teams plays by offensive players, which Sleeper's standard PPR also counts
    "st_td": 6, "st_fum_rec": 1, "st_ff": 1,
    # A fumble recovered by an offensive player and returned for a TD, and a kick blocked by one
    "fum_rec_td": 6, "idp_blk_kick": 2,
}

# Kickers (on top of the offensive scoring above, for the odd run or catch)
K_SCORING = {
    "fgm_0_19": 3, "fgm_20_29": 3, "fgm_30_39": 3, "fgm_40_49": 4, "fgm_50p": 5,
    "xpm": 1, "fgmiss": -1, "xpmiss": -1,
}

# Team defense and special teams. Sleeper scored 14-20 points allowed as 0 in 2025 and 1 from 2026.
DEF_SCORING = {
    "sack": 1, "int": 2, "fum_rec": 2, "def_td": 6, "def_st_td": 6, "safe": 2, "blk_kick": 2,
    "ff": 1, "def_st_ff": 1, "def_st_fum_rec": 1,
    "pts_allow_0": 10, "pts_allow_1_6": 7, "pts_allow_7_13": 4, "pts_allow_14_20": 1,
    "pts_allow_21_27": 0, "pts_allow_28_34": -1, "pts_allow_35p": -4,
}

# The raw stats kept from Sleeper (everything else is dropped to keep files small)
STAT_KEYS = sorted(set(PPR) | set(K_SCORING) | set(DEF_SCORING)
                   | {"pass_cmp", "pass_att", "rush_att", "rec_tgt", "gp", "off_snp", "pts_ppr", "idp_fum_rec", "pts_allow", "tm_off_snp"})


def ppr_points(stats):
    total = sum(w * (stats.get(k) or 0) for k, w in PPR.items())
    if stats.get("idp_fum_rec"):
        # Sleeper scores a fumble-return TD as defense (not PPR) when the recovery is credited as a defensive one
        total -= PPR["fum_rec_td"] * (stats.get("fum_rec_td") or 0)
    return round(total, 2)


def def_scoring(season):
    return {**DEF_SCORING, "pts_allow_14_20": 0} if season and season <= 2025 else DEF_SCORING


def fantasy_points(stats, pos, season=None):
    """Sleeper's standard PPR for any position, including kickers and team defenses."""
    if pos == "K":
        return round(ppr_points(stats) + sum(w * (stats.get(k) or 0) for k, w in K_SCORING.items()), 2)
    if pos == "DEF":
        return round(sum(w * (stats.get(k) or 0) for k, w in def_scoring(season).items()), 2)
    return ppr_points(stats)


def stat_value(key, stats):
    """The value of one prop category from a stat line (Sleeper field names)."""
    s = stats
    if key == "rush_rec_yd":
        return (s.get("rush_yd") or 0) + (s.get("rec_yd") or 0)
    if key == "anytime_td":
        return (s.get("rush_td") or 0) + (s.get("rec_td") or 0)
    if key == "fpts":
        return ppr_points(s)
    return s.get(key) or 0


# label, how far the projection must be from the line to call a lean, and a typical spread used to compare
# edges across categories when ranking the top picks
# min_pick: the smallest line that can be a Top pick (books don't post 0.5-yard lines for backups)
# shrink: the line is shrink x the player's average over his last 8 games. Averages sit above a typical game
# (big games pull them up; injury exits and lost roles pull actual games down), so an unadjusted average put the
# actual result under the line about 63% of the time. These factors were fit on 2025 to make it 50/50 and then
# checked on 2026 games the fit never saw (tools/calibrate.py reruns both steps).
CATEGORIES = {
    "pass_yd": {"label": "Passing Yards", "lean": 8, "scale": 30, "min_pick": 150.5, "shrink": 0.99},
    "pass_td": {"label": "Passing TDs", "lean": 0.15, "scale": 0.6, "min_pick": 0.5, "shrink": 0.84},
    "pass_cmp": {"label": "Completions", "lean": 0.8, "scale": 2.5, "min_pick": 12.5, "shrink": 0.97},
    "pass_att": {"label": "Pass Attempts", "lean": 1.0, "scale": 3, "min_pick": 20.5, "shrink": 0.96},
    "pass_int": {"label": "Interceptions", "lean": 0.12, "scale": 0.5, "min_pick": 0.5, "shrink": 0.7},
    "rush_yd": {"label": "Rushing Yards", "lean": 4, "scale": 12, "min_pick": 15.5, "shrink": 0.89},
    "rush_att": {"label": "Rush Attempts", "lean": 0.8, "scale": 3, "min_pick": 6.5, "shrink": 0.94},
    "rec": {"label": "Receptions", "lean": 0.3, "scale": 1.2, "min_pick": 1.5, "shrink": 0.85},
    "rec_yd": {"label": "Receiving Yards", "lean": 4, "scale": 12, "min_pick": 15.5, "shrink": 0.77},
    "rush_rec_yd": {"label": "Rush + Rec Yards", "lean": 5, "scale": 15, "min_pick": 25.5, "shrink": 0.84},
    "anytime_td": {"label": "Anytime TD", "lean": 0, "scale": 1, "min_pick": None, "shrink": None},
    "fpts": {"label": "Fantasy Points (PPR)", "lean": 1.0, "scale": 4, "min_pick": None, "shrink": 0.86},
}

POSITION_CATEGORIES = {
    "QB": ["pass_yd", "pass_td", "pass_cmp", "pass_att", "pass_int", "rush_yd", "fpts"],
    "RB": ["rush_yd", "rush_att", "rec", "rec_yd", "rush_rec_yd", "anytime_td", "fpts"],
    "WR": ["rec", "rec_yd", "rush_rec_yd", "anytime_td", "fpts"],
    "TE": ["rec", "rec_yd", "anytime_td", "fpts"],
}

# Categories that can be a Top Over/Under pick (yes/no TD props and fantasy points are shown, not ranked)
PICKABLE = {"pass_yd", "pass_td", "pass_cmp", "pass_att", "pass_int", "rush_yd", "rush_att", "rec", "rec_yd", "rush_rec_yd"}


def round_to_half(x):
    """floor(x) + 0.5: lines always end in .5, so there are no pushes. (round() would use banker's rounding.)"""
    return math.floor(x) + 0.5


def td_probability(expected_tds):
    """Chance of at least one touchdown if TDs are Poisson with this mean."""
    return 1 - math.exp(-max(expected_tds, 0))
