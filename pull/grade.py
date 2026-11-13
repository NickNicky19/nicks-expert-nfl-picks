"""Versioned statistical grading of saved forecasts, not sportsbook settlement.

Forecast archives are read-only here. Missing participation evidence is unresolved,
not DNP. Equality is a statistical push; venue-specific payout rules are not inferred.
The public keys used by the original UI remain available.
"""
import json
import hashlib
import os
import tempfile
from pathlib import Path
import math
import statistics
from collections import Counter
from functools import lru_cache
from datetime import datetime
import gzip
import io
import re

import gamemodel
import scoring

GRADING_VERSION = "statistical-presence-verified-int-v7-20261112"
INT_OUTCOME_VERSION = "pass-int-final-passing-boxscore-v2-20261112"
INT_INDEX_SHA256 = "89d755d633f6d3e939b997c2ee7cf638c56be8f3f2ad263e0506d3fce58c1164"
RESULTS = ("hit", "miss", "push", "dnp", "unresolved")


@lru_cache(maxsize=1)
def verified_int_outcomes():
    """Offline, reviewed final-outcome evidence; never a forecast/history input.

    The immutable source corpus is copied with existing output/data staging.
    Missing/corrupt evidence fails publication instead of restoring a partial
    accuracy headline. Unknown sparse-provider fields themselves stay unknown.
    """
    root = Path(__file__).resolve().parents[1] / "output/data/verified-int-v1"
    path = root / "index-v2.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 524288:
        raise ValueError("VERIFIED_INT_INDEX_REQUIRED")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != INT_INDEX_SHA256:
        raise ValueError("VERIFIED_INT_INDEX_IDENTITY")
    index = json.loads(body)
    if index.get("schema_version") != "verified-passing-interceptions-v1" or index.get("outcome_version") != INT_OUTCOME_VERSION:
        raise ValueError("VERIFIED_INT_OUTCOME_VERSION")

    def source(ref):
        name = ref["path"]
        if not re.fullmatch(r"sources/[a-f0-9]{64}\.json\.gz", name):
            raise ValueError("VERIFIED_INT_SOURCE_PATH")
        file = root / name
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 8 << 20:
            raise ValueError("VERIFIED_INT_SOURCE_REQUIRED")
        packed = file.read_bytes()
        if hashlib.sha256(packed).hexdigest() != ref["gzip_SHA256"]:
            raise ValueError("VERIFIED_INT_PACKED_SOURCE_IDENTITY")
        with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
            raw = stream.read((32 << 20) + 1)
        if len(raw) != ref["raw_bytes"] or len(raw) > 32 << 20 or hashlib.sha256(raw).hexdigest() != ref["raw_SHA256"]:
            raise ValueError("VERIFIED_INT_RAW_SOURCE_IDENTITY")
        return json.loads(raw)

    # The reviewed composite bridges require more than a name match.
    identities = index["identity_sources"]
    roster = source(identities["sleeper"])
    for pid, aid, bio_key, code, team_id in [("13425", "4596472", "jalon", "TB", "27"), ("11256", "4434153", "tyson", "CHI", "3"), ("12545", "4360689", "shough", "NO", "18")]:
        player, bio = roster[pid], source(identities[bio_key])
        if not (player["player_id"] == pid and bio["id"] == aid
                and player["full_name"] == bio["displayName"]
                and player["birth_date"] == bio["dateOfBirth"][:10]
                and player["position"] == bio["position"]["abbreviation"] == "QB"
                and player["team"] == code and f"/teams/{team_id}?" in bio["team"]["$ref"]):
            raise ValueError("VERIFIED_INT_COMPOSITE_IDENTITY")
    if str(roster["3163"].get("espn_id")) != "3046779":
        raise ValueError("VERIFIED_INT_DIRECT_IDENTITY")
    del roster

    aliases = {"WSH": "WAS", "LA": "LAR"}
    output = {}
    for case in index["cases"]:
        data = source(index["game_sources"][case["game_id"]])
        header = data["header"]
        competitions = header["competitions"]
        if not (header["id"] == case["game_id"] and header["season"]["year"] == case["season"]
                and header["season"]["type"] == 2 and header["week"] == case["week"] and len(competitions) == 1):
            raise ValueError("VERIFIED_INT_EVENT_IDENTITY")
        game = competitions[0]
        status = game["status"]["type"]
        teams = {aliases.get(c["team"]["abbreviation"], c["team"]["abbreviation"]) for c in game["competitors"]}
        instant = lambda x: datetime.fromisoformat(x.replace("Z", "+00:00"))
        if not (game["id"] == case["game_id"] and status["completed"] is True and status["state"] == "post"
                and re.fullmatch(r"Final(?:/\d*OT)?", status["detail"])
                and teams == {case["team"], case["opponent"]}
                and instant(game["date"]) == instant(case["recorded_kickoff"]) and case["position"] == "QB"):
            raise ValueError("VERIFIED_INT_FINAL_GAME_CONTRACT")
        match = re.fullmatch(r"/boxscore/players/(\d+)/statistics/(\d+)/athletes/(\d+)/stats/(\d+)", case["source"]["json_pointer"])
        if not match:
            raise ValueError("VERIFIED_INT_FIELD_POINTER")
        ti, si, ai, column = map(int, match.groups())
        team_row = data["boxscore"]["players"][ti]
        group = team_row["statistics"][si]
        athlete = group["athletes"][ai]
        value = athlete["stats"][column]
        if not (aliases.get(team_row["team"]["abbreviation"], team_row["team"]["abbreviation"]) == case["team"]
                and group["name"] == "passing" and group["labels"].count("INT") == 1
                and group["labels"][column] == "INT" and len(athlete["stats"]) == len(group["labels"])
                and str(athlete["athlete"]["id"]) == case["source"]["espn_athlete_id"]
                and type(value) is str and re.fullmatch(r"0|[1-9]\d*", value)
                and type(case["verified_value"]) is int and int(value) == case["verified_value"]):
            raise ValueError("VERIFIED_INT_EXPLICIT_THROWN_OUTCOME")
        archive = output.setdefault(case["archive_SHA256"], {})
        key = (case["game_id"], case["player_id"])
        if key in archive:
            raise ValueError("VERIFIED_INT_DUPLICATE_PLAYER_GAME")
        archive[key] = int(value)
    if sum(map(len, output.values())) != 88 or len(output) != 6:
        raise ValueError("VERIFIED_INT_FROZEN_POPULATION")
    return output


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Expected a finite numeric value, got {value!r}")
    return value


def played(entry):
    s = entry.get("stats") or {}
    return (s.get("gp") or 0) > 0 or (s.get("off_snp") or 0) > 0


def participation(entry):
    """Require explicit, attributed evidence for DNP; absent/empty stats are unknown.

    Existing trimmed Sleeper data usually cannot prove DNP. A future adapter may
    supply participation_status='dnp' and participation_source=<nonempty source>.
    Contradictory played/DNP evidence stays unresolved for investigation.
    """
    if not isinstance(entry, dict):
        return "unresolved"
    stats = entry.get("stats") or {}
    if not isinstance(stats, dict):
        return "unresolved"
    for key in ("gp", "off_snp"):
        if stats.get(key) is not None:
            try:
                if _number(stats[key]) < 0 or "_presence" in stats and int(stats[key]) != stats[key]:
                    raise ValueError("Negative participation count")
            except ValueError:
                if "_presence" in stats:
                    return "unresolved"
                raise
    is_played = played(entry)
    is_dnp = entry.get("participation_status") == "dnp" and bool(entry.get("participation_source"))
    if is_played and is_dnp:
        return "unresolved"
    return "played" if is_played else "dnp" if is_dnp else "unresolved"


def result(direction, value, line):
    if direction not in ("over", "under"):
        raise ValueError(f"Invalid direction: {direction!r}")
    if value is None or line is None:
        return "unresolved"
    value, line = _number(value), _number(line)
    if value == line:
        return "push"
    return "hit" if (value > line if direction == "over" else value < line) else "miss"


def tally(results):
    counts = Counter(results)
    unknown = set(counts) - set(RESULTS)
    if unknown:
        raise ValueError(f"Unknown grading outcomes: {sorted(unknown)}")
    out = {key: counts[key] for key in RESULTS}
    n = out["hit"] + out["miss"]
    out.update(n_decided=n, pct=round(100 * out["hit"] / n, 1) if n else None)
    return out


def combine_tallies(tallies):
    tallies = list(tallies)
    out = {key: sum(t.get(key, 0) for t in tallies) for key in RESULTS}
    n = out["hit"] + out["miss"]
    out.update(n_decided=n, pct=round(100 * out["hit"] / n, 1) if n else None)
    return out


def grade_games(archive, scores):
    spread, total = [], []
    for g in archive.get("games", []):
        if not g.get("ours") or g.get("ours_late") or g["id"] not in scores:
            continue
        home, away = scores[g["id"]]
        if home is None or away is None:
            if g["ours"].get("lean_spread"):
                spread.append("unresolved")
            if g["ours"].get("lean_total"):
                total.append("unresolved")
            continue
        _number(home)
        _number(away)
        s_res, t_res = gamemodel.grade(g, g["ours"], home, away)
        if s_res:
            spread.append(s_res)
        if t_res:
            total.append(t_res)
    return {"spread": tally(spread), "total": tally(total)}


def _bound_stats(archive, player, entry, *, game_id=None):
    """Reject recorded identity contradictions without inventing legacy evidence."""
    gid = player.get("game_id")
    if game_id is not None and game_id != gid:
        return None
    matches = [game for game in archive.get("games", []) if game.get("id") == gid]
    if archive.get("games") and len(matches) != 1:
        return None
    game = matches[0] if matches else {}
    team, opponent = player.get("team"), player.get("opp")
    home, away = game.get("home"), game.get("away")
    if home is not None and away is not None:
        if team not in (home, away) or home == away:
            return None
        expected = away if team == home else home
        if opponent is not None and opponent != expected:
            return None
        opponent = expected
    if not isinstance(entry, dict):
        return entry
    if (entry.get("team") is not None and team is not None and entry["team"] != team
            or entry.get("opp") is not None and opponent is not None and entry["opp"] != opponent):
        return None
    stats = entry.get("stats")
    if isinstance(stats, dict) and "_presence" in stats:
        metadata = stats["_presence"]
        if not isinstance(metadata, dict):
            return None
        original, context = metadata.get("original_row"), metadata.get("source_context")
        if (metadata.get("version") != getattr(scoring, "PRESENCE_VERSION", None) or metadata.get("kind") != "actual"
                or not isinstance(original, dict) or not isinstance(context, dict)
                or original.get("player_id") != player["id"]
                or original.get("team") != team or original.get("opponent") != opponent
                or (context.get("season"), context.get("week")) != (archive["season"], archive["week"])
                or original.get("stats") != {key: value for key, value in stats.items() if key != "_presence"}):
            return None
    return entry



def preserve_issued_record(path):
    """Keep exact previously issued bytes before a caller replaces its pointer.

    Original grading versions and historical results remain inside their
    original bytes. These snapshots are prior publications, not new forecasts.
    A corrupt existing history object fails before the live pointer is written.
    Temporary partial writes never occupy the final content-addressed path.
    """
    path = Path(path)
    if not path.exists():
        return None
    issued = path.read_bytes()
    target = path.parent / "grading-history" / (hashlib.sha256(issued).hexdigest() + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".issued-grading-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(issued)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != issued:
                raise ValueError("Previously issued grading history checksum mismatch")
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return target



def _prop_result(prop, direction, entry, verified_value=None):
    status = participation(entry)
    if status != "played":
        return None, status
    # Participation does not certify absent outcome components as zero.
    raw = scoring.stat_value(prop["key"], entry["stats"])
    if prop["key"] == "pass_int" and verified_value is not None:
        raw = verified_value
    if raw is None:
        return None, "unresolved"
    value = round(raw, 2)
    return value, result(direction, value, prop.get("line"))


def grade_week(archive, stats, final_games, verified_int=None):
    """None explicitly means all final; a set means only those confirmed final."""
    players = {p["id"]: p for p in archive["players"]}
    done = lambda gid: final_games is None or gid in final_games
    out = {"season": archive["season"], "week": archive["week"], "grading_version": GRADING_VERSION}
    verified_int = verified_int or {}
    actual_for = lambda who, prop: verified_int.get((who["game_id"], who["id"])) if prop["key"] == "pass_int" else None
    for side in ("over", "under"):
        graded = []
        for p in archive["picks"].get(side, []):
            who = players.get(p["player_id"])
            if not who or who.get("late") or not done(p["game_id"]):
                continue
            if p.get("line_from") not in ("dk", "sleeper"):
                continue
            value, outcome = _prop_result(p, side, _bound_stats(archive, who, stats.get(p["player_id"]), game_id=p["game_id"]), actual_for(who, p))
            graded.append({
                "player_id": p["player_id"], "game_id": p["game_id"], "name": who.get("name", p["player_id"]),
                "key": p["key"], "line": p["line"], "line_from": p.get("line_from"),
                "proj": p.get("proj"), "adj": p.get("adj"),
                "decision_projection": p.get("adj"), "direction": side,
                "actual": value, "result": outcome,
                "settlement_status": "STATISTICAL_ONLY_NOT_VENUE_VERIFIED",
            })
        out[f"top_{side}"] = {**tally(g["result"] for g in graded), "picks": graded}

    lean_results, by_cat, by_venue = [], {}, {}
    real_results = []
    ppr_errors, adjusted_errors, bias = [], [], []
    match = {"soft": [], "neutral": [], "tough": []}
    for p in archive["players"]:
        if not done(p["game_id"]) or p.get("late"):
            continue
        entry = _bound_stats(archive, p, stats.get(p["id"]))
        for prop in p["props"]:
            venue, side = prop.get("line_from"), prop.get("lean")
            if side and venue in ("dk", "sleeper") and prop["key"] != "anytime_td":
                _, outcome = _prop_result(prop, side, entry, actual_for(p, prop))
                lean_results.append(outcome)
                by_cat.setdefault(prop["key"], []).append(outcome)
                by_venue.setdefault(venue, []).append(outcome)
                real_results.append((side, outcome))
        if participation(entry) != "played":
            continue
        points = scoring.ppr_points(entry["stats"])
        fpts = next((x for x in p["props"] if x["key"] == "fpts" and x.get("adj") is not None and x.get("source") == "model"), None)
        if points is not None and p.get("proj_ppr") is not None and fpts:
            raw = _number(p["proj_ppr"])
            adj = _number(fpts["adj"])
            ppr_errors.append(abs(raw - points))
            adjusted_errors.append(abs(adj - points))
            bias.append(raw - points)
            label = p.get("matchup")
            if label in match:
                match[label].append(points - raw)
    out["leans"] = {**tally(lean_results), "by_category": {k: tally(v) for k, v in sorted(by_cat.items())}}
    out["by_venue"] = {k: tally(v) for k, v in sorted(by_venue.items())}
    # Compatibility alias: historically this key included both real-line sources.
    out["dk_leans"] = {side: tally(r for d, r in real_results if d == side) for side in ("over", "under")}
    out["dk_leans_scope"] = "all_real_line_sources_use_by_venue_for_book_breakdown"
    n = len(ppr_errors)
    out["ppr"] = {
        "n": n,
        "proj_mae": round(statistics.mean(ppr_errors), 2) if n else None,
        "average_mae": round(statistics.mean(adjusted_errors), 2) if n else None,
        "adjusted_mae": round(statistics.mean(adjusted_errors), 2) if n else None,
        "proj_bias": round(statistics.mean(bias), 2) if n else None,
        "sums": {"raw_abs": sum(ppr_errors), "adjusted_abs": sum(adjusted_errors), "bias": sum(bias)},
    }
    out["matchup"] = {k: {"n": len(v), "vs_line": round(statistics.mean(v), 2) if v else None} for k, v in match.items()}
    ids = {g["id"] for g in archive.get("games", [])} or {p["game_id"] for p in archive["players"]}
    all_final = final_games is None or (bool(ids) and ids <= set(final_games))
    out["games_complete"] = all_final
    out["complete"] = all_final and out["leans"]["unresolved"] == 0 and all(out[f"top_{s}"]["unresolved"] == 0 for s in ("over", "under"))
    return out


def combine(weeks):
    total = {"weeks": len(weeks)}
    for side in ("over", "under"):
        total[f"top_{side}"] = combine_tallies(w[f"top_{side}"] for w in weeks)
    total["leans"] = combine_tallies(w["leans"] for w in weeks)
    cats = sorted({k for w in weeks for k in w["leans"]["by_category"]})
    total["leans"]["by_category"] = {k: combine_tallies(w["leans"]["by_category"].get(k, {}) for w in weeks) for k in cats}
    venues = sorted({k for w in weeks for k in w.get("by_venue", {})})
    total["by_venue"] = {k: combine_tallies(w.get("by_venue", {}).get(k, {}) for w in weeks) for k in venues}
    total["dk_leans"] = {s: combine_tallies(w.get("dk_leans", {}).get(s, {}) for w in weeks) for s in ("over", "under")}
    total["games"] = {k: combine_tallies(w.get("games", {}).get(k, {}) for w in weeks) for k in ("spread", "total")}
    n = sum(w["ppr"]["n"] for w in weeks)
    def error_mean(key, fallback):
        summed = sum(w["ppr"].get("sums", {}).get(key, (w["ppr"].get(fallback) or 0) * w["ppr"]["n"]) for w in weeks)
        return round(summed / n, 2) if n else None
    total["ppr"] = {"n": n, "proj_mae": error_mean("raw_abs", "proj_mae"),
                    "average_mae": error_mean("adjusted_abs", "average_mae"),
                    "adjusted_mae": error_mean("adjusted_abs", "average_mae"), "proj_bias": error_mean("bias", "proj_bias")}
    total["matchup"] = {}
    for k in ("soft", "neutral", "tough"):
        count = sum(w["matchup"][k]["n"] for w in weeks)
        total["matchup"][k] = {"n": count, "vs_line": round(sum((w["matchup"][k]["vs_line"] or 0) * w["matchup"][k]["n"] for w in weeks) / count, 2) if count else None}
    return total


def grade_all(archive_dir, stats_for, current, final_games, scores_for=None):
    weeks = []
    for path in sorted(archive_dir.glob("*.json")):
        raw = path.read_bytes()
        archive = json.loads(raw)
        key = (archive["season"], archive["week"])
        stats = stats_for(*key) or {}
        scores = scores_for(*key) if scores_for else {}
        # Older week does not imply every game is final (postponements exist).
        finals = final_games if key == current else set(scores)
        verified = None
        canonical_archive = Path(__file__).resolve().parents[1] / "output/data/archive"
        if archive_dir.resolve() == canonical_archive.resolve() and archive["season"] == 2026 and 4 <= archive["week"] <= 9:
            digest = hashlib.sha256(raw).hexdigest()
            registry = verified_int_outcomes()
            if digest not in registry:
                raise ValueError("VERIFIED_INT_ARCHIVE_CHANGED")
            verified = registry[digest]
        week = grade_week(archive, stats, finals, verified)
        if verified:
            week["verified_pass_int"] = {"outcome_version": INT_OUTCOME_VERSION, "player_games": len(verified), "index_sha256": INT_INDEX_SHA256}
        if scores_for:
            week["games"] = grade_games(archive, scores)
        weeks.append(week)
    weeks.sort(key=lambda w: (w["season"], w["week"]), reverse=True)
    return {"grading_version": GRADING_VERSION,
            "settlement_status": "STATISTICAL_ONLY_NOT_VENUE_VERIFIED",
            "provenance_note": "Historical regrades are not new prospective predictions.",
            "cumulative": combine(weeks), "weeks": weeks}
