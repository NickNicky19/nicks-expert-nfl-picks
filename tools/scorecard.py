"""Matched forward comparison. Repeated captures never create new outcomes."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import random
import statistics
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pull"))
import grade
import week_population
from evidence import read, write
from reliability import IntegrityError, atomic_json, digest, engine_hashes, finite, load_json, stamp, utc
from source_evidence import verified_status

# Retain this v1 implementation for its saved receipts. Future adapters need
# separate reviewed implementations/dispatch entries, not a changed v1 file.
POPULATION_V1_SHA256 = "1e50c60ce2636f4534a63f517341c393bac19b8df7cbd2b1fcba1e9eed16c40e"


def _population_document(population):
    contract = (population.get("schema_version"), population.get("adapter_version"),
                population.get("adapter_code_sha256"))
    if contract != ("week-game-population-v1", "week-population-espn-nfl-v1", POPULATION_V1_SHA256):
        raise IntegrityError("UNSUPPORTED_POPULATION_CONTRACT")
    try:
        available = week_population.code_sha256() == POPULATION_V1_SHA256
    except OSError as err:
        raise IntegrityError("RETAINED_POPULATION_VALIDATOR_UNAVAILABLE") from err
    if not available:
        raise IntegrityError("RETAINED_POPULATION_VALIDATOR_UNAVAILABLE")
    return week_population.validate_receipt(population)


def _read_populations(root, season, week):
    """Optional population failures cannot erase independently valid statistics."""
    directory = root / "data/week_populations" / str(season) / f"w{week:02d}"
    populations, errors = [], []
    for path in sorted(directory.glob("*.json.gz")):
        raw_sha = None
        try:
            raw_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            payload = read(path)
            if path.name != digest(payload) + ".json.gz":
                raise IntegrityError("POPULATION_FILENAME_CHECKSUM_MISMATCH")
        except (OSError, EOFError, zlib.error, ValueError, TypeError, AttributeError) as err:
            errors.append({"path": path.relative_to(root).as_posix(),
                           "error_type": type(err).__name__, "raw_file_sha256": raw_sha})
        else:
            # Semantic-invalid but readable evidence is retained for inspection.
            populations.append({"payload_sha256": digest(payload), "payload": payload})
    return populations, errors


def identity(row):
    return tuple(row[k] for k in ("season", "week", "game_id", "player_id", "category"))


def paired_forecasts(receipts, policy, expected_hashes, allow_replay=False):
    chosen = {}
    exclusions = Counter()
    observations = 0
    for payload in sorted(receipts, key=lambda p: (utc(p["captured_at"]), digest(p))):
        if payload.get("schema_version") != "baseline-capture-v1" or payload.get("model") != policy["baseline"]:
            raise IntegrityError("Unexpected forecast schema/model")
        if payload.get("engine_files") != expected_hashes:
            raise IntegrityError("Forecast engine does not match retained baseline")
        if payload.get("mode") != "live" and not (allow_replay and payload.get("mode") == "replay"):
            exclusions["non_live_receipt"] += 1
            continue
        captured, generated = utc(payload["captured_at"]), utc(payload["forecast_generated_at"])
        if generated > captured:
            raise IntegrityError("Forecast generated after capture")
        seen = set()
        for row in payload["rows"]:
            if row["category"] not in policy["targets"]:
                continue
            key = identity(row)
            if key in seen:
                raise IntegrityError("Duplicate opportunity within a receipt")
            seen.add(key)
            if captured >= utc(row["kickoff"]):
                exclusions["not_pregame"] += 1
                continue
            if row.get("raw_projection") is None or row.get("adjusted_projection") is None:
                exclusions["missing_pair"] += 1
                continue
            finite(row["raw_projection"], "raw projection", optional=False)
            finite(row["adjusted_projection"], "clone projection", optional=False)
            observations += 1
            if key not in chosen:
                chosen[key] = {**row, "captured_at": payload["captured_at"],
                               "forecast_generated_at": payload["forecast_generated_at"],
                               "baseline_payload_sha256": digest(payload)}
    return chosen, {"paired_capture_rows": observations, "unique_opportunities": len(chosen),
                    "repeated_capture_rows": observations - len(chosen), "excluded": dict(exclusions)}


def _game_kickoffs(games):
    """Reject empty/duplicate populations instead of silently collapsing IDs."""
    if not isinstance(games, list) or not games:
        return None
    result = {}
    for game in games:
        if not isinstance(game, dict) or not isinstance(game.get("id"), str) or not game["id"].strip():
            return None
        if game["id"] in result or not game.get("kickoff"):
            return None
        result[game["id"]] = utc(game["kickoff"])
    return result


def _verified_week_complete(payload):
    """Validate only frozen population/status evidence inside this receipt."""
    try:
        season, week, mode = payload["season"], payload["week"], payload["mode"]
        if type(season) is not int or type(week) is not int or not 1 <= week <= 18 or mode not in ("live", "replay"):
            return False
        observed = utc(payload["collected_at"])
        read_errors = payload.get("week_population_read_errors", [])
        if not isinstance(read_errors, list) or read_errors:
            return False
        populations = payload.get("week_game_populations")
        if not isinstance(populations, list) or not populations:
            return False
        expected = membership = None
        for envelope in populations:
            population = envelope["payload"]
            if envelope["payload_sha256"] != digest(population):
                return False
            if (population.get("schema_version") != "week-game-population-v1"
                    or population.get("mode") != mode
                    or population.get("season") != season or population.get("week") != week
                    or population.get("population_scope") != "FULL_NFL_REGULAR_SEASON_WEEK"
                    or not isinstance(population.get("source"), str) or not population["source"].strip()):
                return False
            document = _population_document(population)
            if (population.get("source_document_sha256") != digest(document)
                    or document.get("season") != season or document.get("week") != week):
                return False
            games = _game_kickoffs(document.get("games"))
            if games is None:
                return False
            collected = utc(population["collected_at"])
            if collected >= min(games.values()) or collected > observed:
                return False
            if population.get("source_timestamp") and utc(population["source_timestamp"]) > collected:
                return False
            if expected is not None and games != expected:
                return False
            members = sorted((g["id"], g["nfl_id"], g["away"], g["home"], utc(g["kickoff"]))
                             for g in document["games"])
            if membership is not None and members != membership:
                return False
            membership = members
            expected = games
        board = payload.get("games")
        if _game_kickoffs(board) != expected:
            return False
        status = payload["source_game_status"]
        sourced_games = verified_status(status, season, week, mode, observed)
        if set(sourced_games) != set(expected):
            return False
        status_time = utc(status["collected_at"])
        if status_time > observed:
            return False
        for game in board:
            raw = sourced_games[game["id"]]
            kickoff = expected[game["id"]]
            if (game.get("state") != "post" or not str(game.get("detail", "")).lower().startswith("final")
                    or raw.get("state") != "post" or raw.get("completed") is not True
                    or not str(raw.get("detail", "")).lower().startswith("final")
                    or utc(raw["kickoff"]) != kickoff or kickoff >= status_time):
                return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


COUNT_STATS = frozenset(("pass_td", "pass_cmp", "pass_att", "pass_int", "rush_att", "rec"))
PICKABLE_STATS = COUNT_STATS | frozenset(("pass_yd", "rush_yd", "rec_yd", "rush_rec_yd"))


def source_statistic(category, stats):
    """Called only after participation is confirmed; absent sparse values are zero.

    The provider's combined yards contract uses components, never an aggregate
    plus those components. Explicit null is unknown, including either component.
    """
    keys = ("rush_yd", "rec_yd") if category == "rush_rec_yd" else (category,)
    values = [stats.get(key, 0) for key in keys]
    for key, value in zip(keys, values):
        if value is None:
            continue
        finite(value, "source statistic", optional=False)
        if int(value) != value or key in COUNT_STATS and value < 0:
            raise IntegrityError("Invalid integer/count outcome")
    return None if any(value is None for value in values) else sum(values)


def _outcome_identity(payload, row, entry):
    """Check recorded bindings only; missing legacy mappings remain explicit.

    This is shared by fresh snapshots and immutable saved-outcome consumption.
    Contradictions quarantine the observation, not unrelated valid players.
    No provider-specific event-ID crosswalk or absent opponent is invented.
    """
    reasons, missing = [], []
    games = payload.get("games")
    if games is not None and not isinstance(games, list):
        raise IntegrityError("Malformed saved game population")
    if any(not isinstance(game, dict) for game in games or []):
        raise IntegrityError("Malformed saved game record")
    matches = [game for game in games or [] if game.get("id") == row["game_id"]]
    if len(matches) > 1:
        reasons.append("duplicate_recorded_game_identity")
    game = matches[0] if len(matches) == 1 else None
    if game is None:
        # Old receipts may have retained only row-level final-game evidence.
        # A present nonempty board contradicting the row is different.
        if games:
            reasons.append("recorded_game_not_found")
        else:
            missing.append("recorded_game_mapping_unavailable")
    elif game.get("kickoff") and row.get("kickoff"):
        if utc(game["kickoff"]) != utc(row["kickoff"]):
            reasons.append("recorded_game_kickoff_mismatch")
    else:
        missing.append("recorded_kickoff_binding_unavailable")
    home, away = (game.get("home"), game.get("away")) if game else (None, None)
    clubs = [club for club in (home, away) if club is not None]
    if any(not isinstance(club, str) or not club.strip() for club in clubs):
        reasons.append("malformed_recorded_club_identity")
    elif len(clubs) == 2 and (home == away or row.get("team") not in clubs):
        reasons.append("player_team_absent_from_recorded_game")
    elif len(clubs) < 2:
        missing.append("recorded_club_mapping_incomplete")
    if isinstance(entry, dict):
        team, opponent = entry.get("team"), entry.get("opp")
        if team is not None and team != row.get("team"):
            reasons.append("statistics_team_mismatch")
        if team is None:
            missing.append("statistics_team_unavailable")
        if opponent is not None and len(clubs) == 2 and row.get("team") in clubs:
            if opponent != (away if row["team"] == home else home):
                reasons.append("statistics_opponent_mismatch")
        elif opponent is None:
            missing.append("statistics_opponent_unavailable")
    else:
        missing.append("statistics_identity_unavailable")
    return {"outcome_identity_status": "quarantined" if reasons else "partial_legacy" if missing else "bound_to_recorded_game",
            "outcome_identity_reasons": sorted(set(reasons or missing))}


def snapshot_outcomes(root, pairs, observed_at, mode="live", *, output_root=None, derived_context=None,
                      include_populations=True):
    """Snapshot sourced final status and sparse statistics; never infer DNP."""
    root, observed_at = Path(root), utc(observed_at)
    if (output_root is None) != (derived_context is None):
        raise IntegrityError("External outcomes require explicit derived-source provenance")
    if derived_context is not None and (not isinstance(derived_context, dict) or not derived_context):
        raise IntegrityError("Missing derived input identity")
    if output_root is not None:
        sink, source = Path(output_root).resolve(), root.resolve()
        if sink.is_relative_to(source) or source.is_relative_to(sink) or sink.is_relative_to(ROOT):
            raise IntegrityError("Derived output sink must be outside source/input roots")
    groups = defaultdict(list)
    for row in pairs.values():
        groups[(row["season"], row["week"])].append(row)
    current = load_json(root / "output/data/week.json")
    status_path = root / "output/data/game-status.json"
    observed_status = load_json(status_path).get("weeks", {}) if status_path.exists() else {}
    paths = []
    for (season, week), rows in sorted(groups.items()):
        board_path = root / ("output/data/week.json" if (current["season"], current["week"]) == (season, week)
                             else f"output/data/weeks/{season}_w{week:02d}.json")
        cache_path = root / f"data/cache/stats_{season}_{week:02d}.json"
        board = load_json(board_path) if board_path.exists() else {"games": []}
        cache = load_json(cache_path) if cache_path.exists() else {}
        games = {g["id"]: g for g in board["games"]}
        source_status = observed_status.get(f"{season}_{week:02d}")
        def confirmed_final(game):
            if game.get("state") != "post":
                return False
            if source_status is not None:
                raw = source_status["games"].get(game["id"], {})
                return raw.get("state") == "post" and raw.get("completed") is True and raw.get("kickoff") == game["kickoff"]
            # Legacy ESPN snapshots have a saved Final/Final-OT detail but did
            # not retain completed. A bare post flag can also mean cancelled.
            return str(game.get("detail", "")).lower().startswith("final")
        if include_populations:
            populations, population_errors = _read_populations(root, season, week)
        else:
            populations, population_errors = [], [{"error_type": "POPULATION_NOT_CONSUMED_BY_OFFLINE_REPORT"}]
        week_evidence = {"season": season, "week": week, "mode": mode, "collected_at": stamp(observed_at),
                         "games": board["games"], "source_game_status": source_status,
                         "week_game_populations": populations,
                         "week_population_read_errors": population_errors}
        week_complete = _verified_week_complete(week_evidence)
        outcomes = []
        for row in rows:
            game = games.get(row["game_id"])
            status, actual, reason = "pending", None, "game_not_confirmed_final"
            entry = cache.get(row["player_id"])
            binding = _outcome_identity({"games": board["games"]}, row, entry)
            if game and confirmed_final(game):
                if utc(game["kickoff"]) >= observed_at:
                    raise IntegrityError("Final-game evidence has a future kickoff")
                status = grade.participation(entry)
                reason = "participation_not_confirmed"
                if status == "dnp":
                    reason = "explicit_sourced_dnp"
                elif status == "played":
                    status, reason = "resolved", "played_sparse_stats"
                    value = source_statistic(row["category"], entry.get("stats", {}))
                    if binding["outcome_identity_status"] == "quarantined":
                        status, reason = "unresolved", "saved_player_game_identity_mismatch"
                    elif value is None:
                        status, reason = "unresolved", "explicit_null_stat"
                    else:
                        actual = value
                if status != "resolved":
                    actual = None
            if binding["outcome_identity_status"] == "quarantined":
                status, actual, reason = "unresolved", None, "saved_player_game_identity_mismatch"
            outcomes.append({k: row[k] for k in ("season", "week", "game_id", "player_id", "category", "team")} |
                            {"status": status, "actual": actual, "reason": reason,
                             "kickoff": game.get("kickoff") if game else None, "stats_entry": entry,
                             "game_state": game.get("state") if game else None,
                             "final_confirmed": bool(game and confirmed_final(game)), "week_confirmed_complete": week_complete,
                             **binding})
        payload = {"schema_version": "forecast-outcomes-v1", "mode": mode, "season": season, "week": week,
                   "collected_at": stamp(observed_at), "source_timestamp": None,
                   "source": "existing_Sleeper_stats_cache_and_ESPN_final_game_snapshot",
                   "cache_path": cache_path.relative_to(root).as_posix(), "cache_sha256": digest(cache),
                   "game_snapshot_path": board_path.relative_to(root).as_posix(), "game_snapshot_sha256": digest(board),
                   "games": board["games"], "source_game_status": source_status,
                   "week_game_populations": populations,
                   "week_population_read_errors": population_errors, "rows": outcomes,
                   "settlement_scope": "STATISTICAL_ONLY_NOT_VENUE_SETTLEMENT"}
        if derived_context is None:
            paths.append(write(root, "outcomes" if mode == "live" else "outcomes_replay", payload))
        else:
            payload.update(source="git_pinned_saved_cache_statistical_regrade", derived_context=derived_context)
            # A run clock alone is not a new observation. Retain the first actual
            # derivation clock, rather than backdating a new observation.
            material = {k: v for k, v in payload.items() if k != "collected_at"}
            payload["derived_substantive_sha256"] = digest(material)
            directory = Path(output_root) / "data/outcomes_derived" / str(season) / f"w{week:02d}"
            existing = None
            for path in sorted(directory.glob("*.json.gz")):
                old = read(path)
                if old.get("derived_substantive_sha256") == payload["derived_substantive_sha256"]:
                    if {k: v for k, v in old.items() if k not in ("collected_at", "derived_substantive_sha256")} != material:
                        raise IntegrityError("Conflicting derived outcome identity")
                    if utc(old["collected_at"]) > observed_at:
                        raise IntegrityError("Derived outcome is from the future")
                    existing = path
                    break
            paths.append(existing or write(output_root, "outcomes_derived", payload))
    return paths


def _past_final(row, collected):
    return (row.get("game_state") == "post" and row.get("final_confirmed") is True
            and row.get("kickoff") is not None and utc(row["kickoff"]) < collected)


def _outcome_record(payload, row, payload_sha, week_complete=False):
    """Keep only recorded provenance; no current-cache lookup or source-time guess."""
    collected = utc(payload["collected_at"])
    source = payload.get("source")
    path = payload.get("cache_path")
    if ((source is not None and not isinstance(source, str))
            or (path is not None and not isinstance(path, str))):
        raise IntegrityError("Invalid outcome source identity")
    source_time = utc(payload["source_timestamp"]) if payload.get("source_timestamp") else None
    if source_time is not None and source_time > collected:
        raise IntegrityError("Outcome source timestamp is after collection")
    cache_sha = payload.get("cache_sha256")
    if cache_sha is not None and (not isinstance(cache_sha, str) or len(cache_sha) != 64
                                 or any(c not in "0123456789abcdef" for c in cache_sha)):
        raise IntegrityError("Invalid outcome cache digest")
    entry = row.get("stats_entry")
    if entry is not None and not isinstance(entry, dict):
        raise IntegrityError("Invalid saved statistics entry")
    past_final = _past_final(row, collected)
    binding = _outcome_identity(payload, row, entry)
    week_complete = bool(week_complete and (row.get("season"), row.get("week")) ==
                         (payload.get("season"), payload.get("week")) and row.get("kickoff")
                         and any(game["id"] == row.get("game_id") and utc(game["kickoff"]) == utc(row["kickoff"])
                                 for game in payload["games"]))
    status = row["status"]
    if status not in ("pending", "unresolved", "resolved", "dnp", "void"):
        raise IntegrityError("Unexpected outcome status")
    if status == "resolved":
        if not past_final:
            raise IntegrityError("Outcome lacks confirmed past final")
        actual = row["actual"]
        finite(actual, "outcome", optional=False)
        if int(actual) != actual or row["category"] in COUNT_STATS and actual < 0:
            raise IntegrityError("Invalid integer/count outcome")
        if isinstance(entry, dict):
            if grade.participation(entry) != "played":
                raise IntegrityError("Resolved outcome has contradictory participation")
            observed = source_statistic(row["category"], entry.get("stats", {}))
            finite(observed, "saved source statistic", optional=False)
            if observed != actual:
                raise IntegrityError("Resolved outcome differs from its saved source statistic")
    attributed = bool(source and source.strip())
    terminal = status == "resolved" or (past_final and attributed and
                (status == "void" or status == "dnp" and grade.participation(entry) == "dnp"))
    normalized = dict(row)
    if not terminal:
        normalized["actual"] = None
        if status in ("dnp", "void"):
            normalized.update(status="unresolved", reason="unconfirmed_exclusion")
    normalized.update(binding)
    if binding["outcome_identity_status"] == "quarantined":
        normalized.update(status="unresolved", actual=None, reason="saved_player_game_identity_mismatch")
        terminal, week_complete = False, False
    derived = payload.get("derived_context")
    if derived is not None and (not isinstance(derived, dict) or not derived
                               or payload.get("source") != "git_pinned_saved_cache_statistical_regrade"):
        raise IntegrityError("Invalid derived outcome provenance")
    origin = (payload.get("mode"), source, path)
    if derived is not None:
        # Different pinned sources cannot acquire correction precedence from a
        # newer derivation clock. Disagreement across origins stays unresolved.
        origin += (digest(derived), cache_sha, payload.get("game_snapshot_sha256"))
    provenance = {"outcome_snapshot_sha256": payload_sha, "outcome_row_sha256": digest(row),
                  "collected_at": payload["collected_at"], "source": source, "cache_path": path,
                  "cache_sha256": cache_sha, "source_timestamp": payload.get("source_timestamp"),
                  "game_snapshot_sha256": payload.get("game_snapshot_sha256"),
                  "status": status, "actual": row.get("actual"), "team": row.get("team"),
                  "kickoff": row.get("kickoff"), "final_confirmed": row.get("final_confirmed"),
                  "week_confirmed_complete": row.get("week_confirmed_complete", False),
                  "week_completion_verified": week_complete}
    provenance.update(binding)
    if derived is not None:
        provenance["derived_context"] = derived
    return {"row": normalized, "provenance": provenance, "collected": collected,
            "source_time": source_time, "origin": origin,
            "attributed": attributed,
            "version": cache_sha or (digest(entry) if isinstance(entry, dict) else None),
            "terminal": terminal, "past_final": past_final, "week_complete": week_complete}


def _confirmed_frontier(records):
    """Compare source versions within origins; never rank disagreeing sources."""
    origins = defaultdict(list)
    for record in records:
        if record["terminal"]:
            origins[record["origin"]].append(record)
    frontier = []
    for observations in origins.values():
        # Unknown origin/version cannot justify replacing a different final.
        if not all(r["attributed"] and r["version"] for r in observations):
            frontier.extend(observations)
            continue
        versions = defaultdict(list)
        for record in observations:
            versions[record["version"]].append(record)
        sourced_clock = all(r["source_time"] is not None for r in observations)
        if sourced_clock:
            order = {v: max(r["source_time"] for r in rs) for v, rs in versions.items()}
        else:
            # First observation orders distinct saved versions, not source
            # freshness. An older content version reappearing later is ambiguous.
            order = {v: min(r["collected"] for r in rs) for v, rs in versions.items()}
        newest = max(order.values())
        for version, candidates in versions.items():
            reappeared = (not sourced_clock and order[version] < newest
                          and any(r["collected"] >= newest for r in candidates))
            if order[version] == newest or reappeared:
                frontier.extend(candidates)
    return frontier


def latest_outcomes(snapshots, allow_replay=False):
    observations = defaultdict(list)
    seen = set()
    for payload in sorted(snapshots, key=lambda p: (utc(p["collected_at"]), digest(p))):
        if payload.get("schema_version") != "forecast-outcomes-v1":
            raise IntegrityError("Unexpected outcome schema")
        if payload.get("mode") != "live" and not (allow_replay and payload.get("mode") == "replay"):
            continue
        if payload.get("derived_context") is not None:
            material = {k: v for k, v in payload.items() if k not in ("collected_at", "derived_substantive_sha256")}
            if payload.get("derived_substantive_sha256") != digest(material):
                raise IntegrityError("Derived substantive outcome checksum mismatch")
        payload_sha = digest(payload)
        week_complete = _verified_week_complete(payload)
        for row in payload["rows"]:
            record = _outcome_record(payload, row, payload_sha, week_complete)
            reference = (payload_sha, record["provenance"]["outcome_row_sha256"])
            if reference not in seen:
                seen.add(reference)
                observations[identity(row)].append(record)
    latest = {}
    for key, records in observations.items():
        frontier = _confirmed_frontier(records)
        signatures = {(r["row"]["status"], r["row"].get("actual"), r["row"].get("team"),
                       utc(r["row"]["kickoff"])) for r in frontier}
        # A new source version may correct a number, but cannot establish that
        # earlier confirmed participation was invalid. Retain both receipts.
        participation = {r["row"]["status"] for r in records
                         if r["terminal"] and r["row"]["status"] in ("resolved", "dnp")}
        conflict = len(signatures) > 1 or participation == {"resolved", "dnp"}
        # Records already have deterministic parsed-time/content order. A tie
        # can choose a representative only when every active final agrees.
        fallback = [r for r in records if r["past_final"]] or records
        if frontier and all(r["source_time"] is not None for r in frontier):
            selected = max(frontier, key=lambda r: r["source_time"])
        else:
            selected = frontier[0] if frontier else fallback[-1]
        result = {**selected["row"], "outcome_snapshot_sha256": selected["provenance"]["outcome_snapshot_sha256"],
                  "collected_at": selected["provenance"]["collected_at"],
                  "outcome_observations": [r["provenance"] for r in records],
                  "outcome_conflict": conflict,
                  "outcome_selection": "confirmed" if frontier else "incomplete_observation"}
        # Bind reporting provenance to this exact selected source record. The
        # first historical observation need not be the selected correction.
        result["selected_outcome_provenance"] = selected["provenance"]
        result["selected_outcome_provenance_sha256"] = digest(selected["provenance"])
        result["selected_outcome_row_sha256"] = selected["provenance"]["outcome_row_sha256"]
        result["outcome_active_observations"] = sorted({digest(r["provenance"]) for r in frontier})
        sources = {r["provenance"].get("source") for r in frontier}
        result["outcome_source_mix"] = ("unknown_source" if not sources or None in sources or "" in sources else
                                         "mixed_agreeing_sources" if len(sources) > 1 else "single_source")
        versions = defaultdict(set)
        for record in records:
            if record["terminal"] and record["attributed"] and record["version"]:
                versions[record["origin"]].add((record["row"]["status"], record["row"].get("actual")))
        result["outcome_revision"] = any(len(values) > 1 for values in versions.values())
        if conflict:
            result.update(status="unresolved", actual=None, stats_entry=None,
                          reason="conflicting_confirmed_outcomes", outcome_snapshot_sha256=None,
                          outcome_selection="conflict", collected_at=records[-1]["provenance"]["collected_at"],
                          selected_outcome_provenance=None, selected_outcome_provenance_sha256=None,
                          selected_outcome_row_sha256=None,
                          outcome_source_mix="conflicting_sources")
        # Completion proof is separate from the statistic's selected receipt.
        # A later missing stat may still document a confirmed complete week.
        completion = [r["provenance"]["outcome_snapshot_sha256"] for r in records
                      if r["past_final"] and r["week_complete"]
                      and r["row"].get("team") == selected["row"].get("team")
                      and utc(r["row"]["kickoff"]) == utc(selected["row"]["kickoff"])]
        result["week_confirmed_complete"] = bool(completion)
        result["week_completion_snapshot_sha256"] = sorted(set(completion))
        latest[key] = result
    return latest


def metrics(rows, field):
    errors = [r[field] - r["actual"] for r in rows]
    return {"n": len(errors), "mae": statistics.mean(abs(e) for e in errors) if errors else None,
            "rmse": math.sqrt(statistics.mean(e * e for e in errors)) if errors else None,
            "mean_error": statistics.mean(errors) if errors else None}


def cluster_interval(rows, policy):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["season"], row["week"])].append(row)
    rule = policy["uncertainty"]
    completed = sorted(key for key, group in groups.items()
                       if all(r.get("week_confirmed_complete") is True for r in group))
    blocks = []
    for key in completed:
        differences = [abs(r["adjusted_projection"] - r["actual"]) -
                       abs(r["raw_projection"] - r["actual"]) for r in groups[key]]
        for value in differences:
            finite(value, "completed-week paired error", optional=False)
        blocks.append((math.fsum(differences), len(differences)))
    n = sum(count for _, count in blocks)
    coverage = {"completed_weeks": len(completed), "observed_week_clusters": len(groups),
                "resampled_week_clusters": len(completed), "resampled_outcomes": n,
                "excluded_incomplete_week_clusters": len(groups) - len(completed),
                "excluded_incomplete_outcomes": len(rows) - n, "cluster": "season_week",
                "interval_population": "completed_weeks_only",
                "completed_week_mae_delta_clone_minus_raw": math.fsum(total for total, _ in blocks) / n if n else None}
    if len(completed) < rule["minimum_completed_weeks"]:
        return {**coverage, "status": "insufficient_completed_weeks", "interval": None}
    rng = random.Random(rule["seed"])
    means = []
    for _ in range(rule["bootstrap_replicates"]):
        sampled = [blocks[rng.randrange(len(blocks))] for _ in blocks]
        means.append(math.fsum(total for total, _ in sampled) / sum(count for _, count in sampled))
    means.sort()
    tail = (1 - rule["simultaneous_confidence"]) / 2
    return {**coverage, "status": "available", "confidence": rule["simultaneous_confidence"],
            "interval": [means[int(tail * len(means))], means[min(len(means) - 1, int((1 - tail) * len(means)))]]}


def score(pairs, outcomes, coverage, policy):
    by_category = {key: [] for key in policy["targets"]}
    statuses = Counter()
    lead_times = Counter()
    injuries = Counter()
    detail = []
    for key, row in sorted(pairs.items()):
        outcome = outcomes.get(key, {"status": "pending", "actual": None})
        status = outcome["status"]
        if utc(row["kickoff"]) <= utc(policy["registered_at"]):
            status = "excluded_pre_registration_game"
        elif outcome.get("kickoff") and utc(outcome["kickoff"]) != utc(row["kickoff"]):
            status = "excluded_schedule_changed"
        statuses[status] += 1
        hours = (utc(row["kickoff"]) - utc(row["captured_at"])).total_seconds() / 3600
        lead_times["under_24h" if hours < 24 else "24_to_72h" if hours <= 72 else "over_72h"] += 1
        injuries[row.get("injury_at_capture") or "no_designation_reported"] += 1
        item = {**row, "evaluation_status": status, "actual": outcome.get("actual"),
                "outcome_snapshot_sha256": outcome.get("outcome_snapshot_sha256"),
                "outcome_observations": outcome.get("outcome_observations", []),
                "outcome_conflict": outcome.get("outcome_conflict", False),
                "outcome_selection": outcome.get("outcome_selection"),
                "week_completion_snapshot_sha256": outcome.get("week_completion_snapshot_sha256", []),
                "week_confirmed_complete": outcome.get("week_confirmed_complete", False)}
        detail.append(item)
        if status == "resolved":
            by_category[row["category"]].append(item)
    categories = {}
    for key, rows in by_category.items():
        raw, clone = metrics(rows, "raw_projection"), metrics(rows, "adjusted_projection")
        categories[key] = {"raw_sleeper": raw, "unchanged_clone": clone,
                           "paired_mae_delta_clone_minus_raw": clone["mae"] - raw["mae"] if rows else None,
                           "uncertainty": cluster_interval(rows, policy)}
    return {"schema_version": "forecast-scorecard-v1", "policy_version": policy["version"], "policy_sha256": digest(policy),
            "evidence": "LOCAL_PREGAME_OBSERVATIONS_SOURCE_ASOF_NOT_VERIFIED", "coverage": coverage,
            "outcome_status": dict(statuses), "lead_time_coverage": dict(lead_times), "injury_coverage": dict(injuries),
            "categories": categories, "rows": detail, "production_model": policy["baseline"],
            "promotion": {"enabled": False, "status": "REQUIRES_FORWARD_HOLDOUT_REVIEW_AND_EXPLICIT_APPROVAL"},
            "calibration": "NOT_ESTABLISHED", "profitability": "NOT_ESTABLISHED"}


def _additional_pairs(requested, primary, receipts, now, allow_replay):
    """Accept only original pregame identities; never fabricate extra outcomes."""
    if not isinstance(requested, dict):
        raise IntegrityError("Additional outcome identities must be a mapping")
    original = set()
    for payload in receipts:
        if payload.get("mode") != "live" and not (allow_replay and payload.get("mode") == "replay"):
            continue
        captured = utc(payload["captured_at"])
        if captured > utc(now):
            continue
        for row in payload["rows"]:
            if row["category"] in PICKABLE_STATS and captured < utc(row["kickoff"]):
                original.add((identity(row), row["team"], utc(row["kickoff"])))
    result = {}
    for key, row in requested.items():
        try:
            valid = (isinstance(row, dict) and key == identity(row) and row["category"] in PICKABLE_STATS
                     and type(row["season"]) is int and type(row["week"]) is int and 1 <= row["week"] <= 18
                     and all(isinstance(row[name], str) and row[name].strip()
                             for name in ("game_id", "player_id", "team"))
                     and (key, row["team"], utc(row["kickoff"])) in original)
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise IntegrityError("Additional outcome identity is not an original saved pregame observation")
        if key in primary:
            if row["team"] != primary[key]["team"] or utc(row["kickoff"]) != utc(primary[key]["kickoff"]):
                raise IntegrityError("Additional outcome conflicts with primary identity")
        else:
            result[key] = row
    return result


def build_scorecard(root=ROOT, observed_at=None, mode="live", allow_replay=False, *, additional_outcome_pairs=None):
    root = Path(root)
    now = observed_at or datetime.now(timezone.utc)
    policy = load_json(root / "config/evaluation-policy.json")
    lane = "forward" if mode == "live" else "replay"
    receipts = [read(p) for p in sorted((root / "data" / lane).rglob("*.json.gz"))]
    pairs, coverage = paired_forecasts(receipts, policy, engine_hashes(root), allow_replay=allow_replay)
    additional = (_additional_pairs(additional_outcome_pairs, pairs, receipts, now, allow_replay)
                  if additional_outcome_pairs is not None else {})
    paths = snapshot_outcomes(root, pairs, now, mode=mode)
    if additional:
        # The primary call and registered scoring population stay intact.
        # Extra descriptive categories cannot certify a completed week.
        paths.extend(snapshot_outcomes(root, additional, now, mode=mode, include_populations=False))
    outcome_lane = "outcomes" if mode == "live" else "outcomes_replay"
    outcomes = latest_outcomes([read(p) for p in (root / "data" / outcome_lane).rglob("*.json.gz")], allow_replay)
    report = score(pairs, outcomes, coverage, policy)
    report["generated_at"] = stamp(now)
    if allow_replay:
        report["evidence"] = "REPLAY_TEST_NOT_PROSPECTIVE"
    return report, paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    report, _ = build_scorecard(args.root)
    atomic_json(args.root / "output/data/forecast-scorecard.json", report)
    print({"coverage": report["coverage"], "outcomes": report["outcome_status"]})


if __name__ == "__main__":
    main()
