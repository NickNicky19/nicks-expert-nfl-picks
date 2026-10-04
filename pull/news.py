"""ESPN's league-wide injury report: status, notes and expected return for every injured player.

It's about 9 MB, so the hourly build fetches it and keeps only this week's players. The page adds game-day news
from each game's feed on top (see applyInjuries in app.js), and loads a player's latest notes when he's opened.
"""
import re

import sources
from books import norm_name

URL = f"{sources.ESPN}/injuries"


def _espn_id(athlete):
    for link in athlete.get("links") or []:
        m = re.search(r"/id/(\d+)", link.get("href") or "")
        if m:
            return m.group(1)
    return None


def injury_report(entries):
    """{sleeper_id: report} for entries ({id, name, team, espn_id}) that ESPN lists as injured."""
    data = sources.get_json(URL) or {}
    by_espn = {str(e["espn_id"]): e["id"] for e in entries if e.get("espn_id")}
    by_name = {(norm_name(e["name"]), e["team"]): e["id"] for e in entries}
    out = {}
    for team in data.get("injuries", []):
        for i in team.get("injuries", []):
            a = i.get("athlete") or {}
            abbr = sources.team_code((a.get("team") or {}).get("abbreviation") or "")
            pid = by_espn.get(_espn_id(a) or "") or by_name.get((norm_name(a.get("displayName") or ""), abbr))
            if not pid:
                continue
            d = i.get("details") or {}
            report = {
                "status": i.get("status"), "date": i.get("date"),
                "short": i.get("shortComment"), "long": i.get("longComment"),
                "part": d.get("type"), "detail": d.get("detail"), "side": d.get("side"),
                "ret": d.get("returnDate"), "fantasy": (d.get("fantasyStatus") or {}).get("description"),
            }
            # keep the newest note if ESPN lists a player twice
            if pid not in out or (report["date"] or "") > (out[pid]["date"] or ""):
                out[pid] = {k: v for k, v in report.items() if v}
    return out
