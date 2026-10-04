"""Free, keyless public data sources.

Sleeper (api.sleeper.app): players, injuries, weekly stats, weekly projections (including PPR fantasy points).
ESPN (site.api.espn.com): the week's schedule and scores. The browser polls ESPN directly for live data.
"""
import time

import requests

SLEEPER = "https://api.sleeper.app"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

# ESPN and Sleeper agree on every team code except Washington
ESPN_TO_SLEEPER = {"WSH": "WAS"}

_session = requests.Session()
_session.headers["User-Agent"] = "nfl-player-props (https://github.com/joshuam0y/nfl-player-props)"


def get_json(url, params=None, tries=3):
    for attempt in range(tries):
        try:
            r = _session.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return None


def _position_params(extra=None):
    return [("season_type", "regular"), *[("position[]", p) for p in POSITIONS], *(extra or [])]


def nfl_state():
    return get_json(f"{SLEEPER}/v1/state/nfl")


def players():
    """Every NFL player (about 14 MB). Callers keep only what they need."""
    return get_json(f"{SLEEPER}/v1/players/nfl")


def week_stats(season, week):
    return get_json(f"{SLEEPER}/stats/nfl/{season}/{week}", _position_params()) or []


def week_projections(season, week):
    return get_json(f"{SLEEPER}/projections/nfl/{season}/{week}", _position_params([("order_by", "pts_ppr")])) or []


def scoreboard(season, week):
    return get_json(f"{ESPN}/scoreboard", {"seasontype": 2, "week": week, "dates": season}) or {}


def team_code(espn_abbrev):
    return ESPN_TO_SLEEPER.get(espn_abbrev, espn_abbrev)
