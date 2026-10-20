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

# Kickers and team defenses use ESPN's standard scoring (they aren't in the Sleeper league this was built for).
# Checked against ESPN's own default-league totals: every kicker and defense matched in 2026 weeks 1-3.
K_SCORING = {
    "fgm_0_19": 3, "fgm_20_29": 3, "fgm_30_39": 3, "fgm_40_49": 4, "fgm_50_59": 5, "fgm_60p": 6,
    "xpm": 1, "fgmiss": -1,                      # ESPN doesn't take a point off for a missed extra point
}
DEF_SCORING = {
    "sack": 1, "int": 2, "fum_rec": 2, "def_st_fum_rec": 2, "blk_kick": 2, "safe": 2, "def_td": 6, "def_st_td": 6,
}
# (most allowed, points) tiers
PTS_ALLOWED = [(0, 5), (6, 4), (13, 3), (17, 1), (27, 0), (34, -1), (45, -3), (10 ** 6, -5)]
YDS_ALLOWED = [(99, 5), (199, 3), (299, 2), (349, 0), (399, -1), (449, -3), (499, -5), (549, -6), (10 ** 6, -7)]

# The raw stats kept from Sleeper (everything else is dropped to keep files small)
STAT_KEYS = sorted(set(PPR) | set(K_SCORING) | set(DEF_SCORING)
                   | {"pass_cmp", "pass_att", "rush_att", "rec_tgt", "gp", "off_snp", "pts_ppr", "pts_half_ppr", "idp_fum_rec",
                      "pts_allow", "yds_allow", "tm_off_snp", "fgm_50p"})


PRESENCE_VERSION = "nfl-data-presence-v2"
LEGACY_SPARSE_ASSUMPTION = "legacy-played-sparse-stat-assumption-v1"
ACTUAL_COUNTS = (set(PPR) - {"pass_yd", "rush_yd", "rec_yd"}) | {
    "pass_cmp", "pass_att", "rush_att", "rec_tgt", "gp", "off_snp", "tm_off_snp", "idp_fum_rec"}


def retained_value(value):
    """JSON-safe representation of invalid nonfinite model-input components.

    A tagged invalid component remains invalid; it is never a numeric/null zero.
    Ordinary finite values, explicit nulls and invalid strings/bools stay exact.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return {"invalid_numeric_encoding": "nfl-nonfinite-v1",
                "value": "nan" if math.isnan(value) else "+infinity" if value > 0 else "-infinity"}
    return value


def component(stats, key, *, projection=False):
    """Value and evidence state; inferred sparse zero is never reported zero.

    Unversioned saved stats retain the explicitly labeled legacy sparse adapter
    assumption. A modern sparse row must retain its actual attributed source
    row and context. A metadata label, HTTP success or participation alone is
    insufficient. Projection absence is never covered by this assumption.
    """
    if not isinstance(stats, dict):
        return {"value": None, "state": "unsupported_absence"}
    metadata = stats.get("_presence")
    projection = projection or isinstance(metadata, dict) and metadata.get("kind") == "projection"
    if key in stats:
        value = stats[key]
        if isinstance(metadata, dict) and key in metadata.get("invalid_fields", []):
            return {"value": None, "state": "invalid_value"}
        if value is None:
            return {"value": None, "state": "explicit_unknown"}
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return {"value": None, "state": "invalid_value"}
        if not projection and ((key in ACTUAL_COUNTS and value < 0)
                               or key in ACTUAL_COUNTS | {"pass_yd", "rush_yd", "rec_yd"} and int(value) != value):
            return {"value": None, "state": "invalid_value"}
        return {"value": value, "state": "reported_zero" if value == 0 else "reported_value"}
    if projection:
        return {"value": None, "state": "unsupported_absence"}
    if metadata is None and "_presence" not in stats:
        return {"value": 0, "state": "inferred_sparse_zero_legacy_assumption"}
    if not isinstance(metadata, dict) or metadata.get("version") != PRESENCE_VERSION:
        return {"value": None, "state": "unsupported_absence"}
    source, context = metadata.get("original_row"), metadata.get("source_context")
    supported = (metadata.get("sparse_contract") == LEGACY_SPARSE_ASSUMPTION
                 and isinstance(source, dict) and isinstance(source.get("stats"), dict)
                 and all(isinstance(source.get(k), str) and source[k] for k in ("player_id", "team", "opponent"))
                 and isinstance(context, dict) and context.get("adapter") == "sleeper-week-stats-v1"
                 and type(context.get("season")) is int and type(context.get("week")) is int
                 and 1 <= context["week"] <= 18)
    if supported:
        original = source["stats"]
        # Reconcile every retained modeled value to the original row, rather
        # than accepting a caller's completeness label.
        supported = set(stats) - {"_presence"} == set(original) and all(stats[k] == original[k] for k in original)
        supported = supported and key not in original and any(
            type(original.get(k)) in (int, float) and math.isfinite(original[k]) and original[k] > 0 and int(original[k]) == original[k]
            for k in ("gp", "off_snp"))
    return {"value": 0 if supported else None,
            "state": "inferred_sparse_zero_legacy_assumption" if supported else "unsupported_absence"}


def _sum_components(stats, weights, *, projection=False):
    values = [component(stats, key, projection=projection)["value"] for key in weights]
    return None if any(value is None for value in values) else sum(
        weight * value for weight, value in zip(weights.values(), values))


def _legacy_ppr_points(stats):
    total = sum(w * (stats.get(k) or 0) for k, w in PPR.items())
    if stats.get("idp_fum_rec"):
        # Sleeper scores a fumble-return TD as defense (not PPR) when the recovery is credited as a defensive one
        total -= PPR["fum_rec_td"] * (stats.get("fum_rec_td") or 0)
    return round(total, 2)


def ppr_points(stats, *, projection=False):
    total = _sum_components(stats, PPR, projection=projection)
    defensive = component(stats, "idp_fum_rec", projection=projection)["value"]
    if total is None or defensive is None:
        return None
    if defensive:
        value = component(stats, "fum_rec_td", projection=projection)["value"]
        if value is None:
            return None
        total -= PPR["fum_rec_td"] * value
    return round(total, 2)


def _tier(value, tiers):
    return next(points for most, points in tiers if value <= most)


def kicker_points(stats):
    s = dict(stats)
    # Sleeper's 50+ count includes 60+, and it reports only one of the two splits; derive the other. Projections
    # have neither split, so their 50+ kicks count as 50-59.
    fifty = s.get("fgm_50p") or 0
    if s.get("fgm_60p") is None:
        s["fgm_60p"] = fifty - s["fgm_50_59"] if s.get("fgm_50_59") is not None else 0
    if s.get("fgm_50_59") is None:
        s["fgm_50_59"] = max(0, fifty - s["fgm_60p"])
    return sum(w * (s.get(k) or 0) for k, w in K_SCORING.items())


def defense_points(stats):
    return (sum(w * (stats.get(k) or 0) for k, w in DEF_SCORING.items())
            + _tier(stats.get("pts_allow") or 0, PTS_ALLOWED) + _tier(stats.get("yds_allow") or 0, YDS_ALLOWED))


def fantasy_points(stats, pos, season=None, half=False):
    """Fantasy points: Sleeper's standard PPR (or half PPR) for skill players, ESPN's standard scoring for K and DEF."""
    if pos == "K":
        return round(_legacy_ppr_points(stats) + kicker_points(stats), 2)
    if pos == "DEF":
        return round(defense_points(stats), 2)
    points = ppr_points(stats)
    receptions = component(stats, "rec")["value"] if half else 0
    return None if points is None or receptions is None else round(points - 0.5 * receptions, 2)


def stat_value(key, stats, *, projection=False):
    """The value of one prop category from a stat line (Sleeper field names)."""
    s = stats
    if key == "rush_rec_yd":
        return _sum_components(s, {"rush_yd": 1, "rec_yd": 1}, projection=projection)
    if key == "anytime_td":
        return _sum_components(s, {"rush_td": 1, "rec_td": 1}, projection=projection)
    if key == "fpts":
        return ppr_points(s, projection=projection)
    return component(s, key, projection=projection)["value"]


# label; lean: how far our projection must be from the line to call a lean; scale: a typical spread, used to compare
# gaps across categories when ranking the top picks; min_pick: the smallest line that can be a top pick
CATEGORIES = {
    "pass_yd": {"label": "Passing Yards", "lean": 8, "scale": 30, "min_pick": 150.5},
    "pass_td": {"label": "Passing TDs", "lean": 0.15, "scale": 0.6, "min_pick": 0.5},
    "pass_cmp": {"label": "Completions", "lean": 0.8, "scale": 2.5, "min_pick": 12.5},
    "pass_att": {"label": "Pass Attempts", "lean": 1.0, "scale": 3, "min_pick": 20.5},
    "pass_int": {"label": "Interceptions", "lean": 0.12, "scale": 0.5, "min_pick": 0.5},
    "rush_yd": {"label": "Rushing Yards", "lean": 4, "scale": 12, "min_pick": 15.5},
    "rush_att": {"label": "Rush Attempts", "lean": 0.8, "scale": 3, "min_pick": 6.5},
    "rec": {"label": "Receptions", "lean": 0.3, "scale": 1.2, "min_pick": 1.5},
    "rec_yd": {"label": "Receiving Yards", "lean": 4, "scale": 12, "min_pick": 15.5},
    "rush_rec_yd": {"label": "Rush + Rec Yards", "lean": 5, "scale": 15, "min_pick": 25.5},
    "anytime_td": {"label": "Anytime TD", "lean": 0, "scale": 1, "min_pick": None},
    "fpts": {"label": "Fantasy Points (PPR)", "lean": 1.0, "scale": 4, "min_pick": None},
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
