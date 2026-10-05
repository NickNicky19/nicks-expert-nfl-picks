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


def update_timeline(path, entries, reports, now):
    """ESPN and Sleeper only show a player's latest injury status, so each build records changes here, building
    each player's injury timeline over the season: [{t, status, part, note}], newest last, up to 12 per player."""
    import json
    try:
        log = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        log = {}
    for e in entries:
        r = reports.get(e["id"], {})
        status = e.get("injury") or (r.get("status") if r.get("status") not in (None, "Active") else None)
        note = r.get("short")
        last = (log.get(e["id"]) or [{}])[-1]
        if status is None and not last:
            continue   # healthy and never hurt: nothing to record
        if (status, note) == (last.get("status"), last.get("note")):
            continue
        log.setdefault(e["id"], []).append({k: v for k, v in {"t": now, "status": status or "Active", "part": e.get("injury_part") or r.get("part"), "note": note}.items() if v})
        log[e["id"]] = log[e["id"]][-12:]
    path.write_text(json.dumps(log, separators=(",", ":"), sort_keys=True))
    return log
