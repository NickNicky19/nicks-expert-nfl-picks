"""Matched forward comparison. Repeated captures never create new outcomes."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
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
import scoring
import week_population
import data_integrity_v2 as corrected
import classic_model_v1 as classic
from evidence import read, write
from reliability import IntegrityError, atomic_json, digest, engine_hashes, finite, load_json, stamp, utc
from source_evidence import verified_status

# Retain this v1 implementation for its saved receipts. Future adapters need
# separate reviewed implementations/dispatch entries, not a changed v1 file.
POPULATION_V1_SHA256 = "1e50c60ce2636f4534a63f517341c393bac19b8df7cbd2b1fcba1e9eed16c40e"
DESCRIPTIVE_VERSION = "all-category-descriptive-v1"
DERIVED_STAT_SCHEMA = "descriptive-statistic-outcomes-v1"
SCORING_V1_SHA256 = "31672c10d526d591db8951157b0ecd669b4d02b412a75deec337618bff18dab2"
EXTRA_CATEGORIES = frozenset(("fpts", "anytime_td"))


def descriptive_contract(*, presence_aware=False, model=None):
    """Retained scoring, not a new forecast or a permissive generic-stat reader."""
    if presence_aware:
        return corrected.statistic_contract(descriptive=True, model=model)
    if model not in (None, "original_sleeper_matchup_baseline", classic.MODEL):
        raise IntegrityError("Unsupported legacy descriptive model")
    retained = classic.scoring() if model == classic.MODEL else corrected.legacy_scoring()
    return {"version": "offensive-ppr-rush-rec-td-v1", "scoring_sha256": classic.ENGINE["pull/scoring.py"] if model == classic.MODEL else SCORING_V1_SHA256,
            "ppr_weights": dict(retained.PPR), "ppr_defensive_fumble_exclusion": "idp_fum_rec",
            "td_event": "rush_td+rec_td>=1", "td_probability": "round(1-exp(-max(count,0)),3)"}


def descriptive_statistic(category, stats, *, presence_aware=False, model=None):
    if category not in EXTRA_CATEGORIES or not isinstance(stats, dict):
        raise IntegrityError("Unsupported descriptive source statistic")
    if presence_aware:
        return corrected.presence_scoring(model).stat_value(category, stats)
    keys = set(scoring.PPR) | {"idp_fum_rec"} if category == "fpts" else {"rush_td", "rec_td"}
    missing = False
    for key in keys:
        if key not in stats:
            continue  # Sparse zeros are permitted only after the caller proves played.
        value = stats[key]
        if value is None:
            missing = True
            continue
        finite(value, "descriptive statistic component", optional=False)
        if int(value) != value or key not in {"pass_yd", "rush_yd", "rec_yd"} and value < 0:
            raise IntegrityError("Invalid descriptive statistic component")
    if missing:
        return None
    retained = classic.scoring() if model == classic.MODEL else corrected.legacy_scoring()
    return retained.ppr_points(stats) if category == "fpts" else stats.get("rush_td", 0) + stats.get("rec_td", 0)


def _legacy_descriptive_model(contract):
    if not isinstance(contract, dict):
        raise IntegrityError("Unsupported legacy descriptive source contract")
    source = contract.get("scoring_sha256")
    if source == SCORING_V1_SHA256:
        model = None
    elif source == classic.ENGINE["pull/scoring.py"]:
        model = classic.MODEL
    else:
        raise IntegrityError("Unsupported legacy descriptive source contract")
    if digest(contract) != digest(descriptive_contract(model=model)):
        raise IntegrityError("Unsupported legacy descriptive source contract")
    return model


def _validate_descriptive_outcome(payload, row=None):
    modern = payload.get("schema_version") == corrected.DESCRIPTIVE_OUTCOMES
    if payload.get("schema_version") not in (DERIVED_STAT_SCHEMA, corrected.DESCRIPTIVE_OUTCOMES):
        raise IntegrityError("Unsupported descriptive outcome contract")
    if modern:
        corrected.statistic_model(payload.get("statistic_contract"), descriptive=True)
    else:
        _legacy_descriptive_model(payload.get("statistic_contract"))
    if (not isinstance(payload.get("source"), str) or not payload["source"].strip()
            or not payload.get("cache_path") and "rows" in payload
            or payload.get("source") == "git_pinned_saved_cache_statistical_regrade"
            and payload.get("derived_context") is None):
        raise IntegrityError("Descriptive outcomes require attributed source evidence")
    if row is not None:
        allowed = {"QB", "RB", "WR", "TE"} if row.get("category") == "fpts" else {"RB", "WR", "TE"}
        if row.get("category") not in EXTRA_CATEGORIES or row.get("position") not in allowed:
            raise IntegrityError("Unsupported descriptive category/position")
        if (type(payload.get("season")) is not int or type(payload.get("week")) is not int
                or not 1 <= payload["week"] <= 18
                or (row.get("season"), row.get("week")) != (payload["season"], payload["week"])
                or type(row.get("season")) is not int or type(row.get("week")) is not int
                or any(not isinstance(row.get(k), str) or not row[k].strip()
                       for k in ("game_id", "player_id", "team"))):
            raise IntegrityError("Descriptive outcome period/identity mismatch")


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


def cross_record_binding(forecast, outcome, *, key=None):
    """Validate a consumer's join independently of either record's validity.

    This does not select outcomes or qualify their sources. Identity errors take
    priority over schedule changes. Neither original record is modified.
    """
    fields = ("season", "week", "game_id", "player_id", "category")
    reasons = []

    def checked(record, label):
        if not isinstance(record, dict):
            reasons.append(label + "_record_invalid")
            return None
        for name in ("season", "week"):
            if type(record.get(name)) is not int:
                reasons.append(label + "_" + name + "_invalid")
        for name in ("game_id", "player_id", "category", "team"):
            if not isinstance(record.get(name), str) or not record[name].strip():
                reasons.append(label + "_" + name + "_missing")
        return tuple(record.get(name) for name in fields)

    expected = checked(forecast, "forecast")
    if key is not None and key != expected:
        reasons.append("forecast_map_key_mismatch")
    if outcome is None:
        return {"status": "identity_mismatch" if reasons else "missing", "reasons": sorted(set(reasons))}
    actual = checked(outcome, "outcome")
    if isinstance(forecast, dict) and isinstance(outcome, dict):
        reasons.extend("forecast_outcome_" + name + "_mismatch" for name in fields + ("team",)
                       if forecast.get(name) != outcome.get(name))
        if forecast.get("opponent") is not None and outcome.get("opponent") is not None:
            if forecast["opponent"] != outcome["opponent"]:
                reasons.append("forecast_outcome_opponent_mismatch")
    if key is not None and actual != key:
        reasons.append("outcome_map_key_mismatch")
    if reasons:
        return {"status": "identity_mismatch", "reasons": sorted(set(reasons))}
    clocks = {}
    for label, record in (("forecast", forecast), ("outcome", outcome)):
        try:
            clocks[label] = utc(record.get("kickoff"))
        except (TypeError, ValueError, OverflowError):
            reasons.append(label + "_kickoff_missing_or_invalid")
    if reasons:
        return {"status": "identity_mismatch", "reasons": sorted(set(reasons))}
    return {"status": "bound" if clocks["forecast"] == clocks["outcome"] else "schedule_changed",
            "reasons": [] if clocks["forecast"] == clocks["outcome"] else ["forecast_outcome_kickoff_mismatch"]}


def bind_outcome(forecast, outcome, *, key=None):
    """Return an isolated derived binding; preserve original source evidence."""
    binding = cross_record_binding(forecast, outcome, key=key)
    if binding["status"] in ("bound", "missing"):
        return dict(outcome or {"status": "pending", "actual": None, "reason": "no_saved_outcome"}), binding
    derived = dict(outcome or {})
    derived.update(status="unresolved", actual=None,
                   reason="forecast_outcome_identity_mismatch" if binding["status"] == "identity_mismatch"
                          else "forecast_outcome_schedule_changed",
                   outcome_identity_status="quarantined",
                   outcome_identity_reasons=binding["reasons"], week_confirmed_complete=False,
                   week_completion_snapshot_sha256=[])
    return derived, binding


def paired_forecasts(receipts, policy, expected_hashes, allow_replay=False, *, row_eligible=None):
    chosen = {}
    exclusions = Counter()
    observations = 0
    for payload in sorted(receipts, key=lambda p: (utc(p["captured_at"]), digest(p))):
        if payload.get("schema_version") in (corrected.NATIVE, classic.CAPTURE):
            (classic.native_contract(payload) if payload["schema_version"] == classic.CAPTURE
             else corrected.native_contract(payload))
            exclusions["corrected_model_outside_registered_experiment"] += len(payload["rows"])
            continue
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
            if row_eligible is not None and not row_eligible(row):
                continue
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


def source_statistic(category, stats, *, presence_aware=False, model=None):
    """Called only after participation is confirmed; absent sparse values are zero.

    The provider's combined yards contract uses components, never an aggregate
    plus those components. Explicit null is unknown, including either component.
    """
    keys = ("rush_yd", "rec_yd") if category == "rush_rec_yd" else (category,)
    modern = presence_aware or "_presence" in stats
    if modern and model == classic.MODEL:
        return None  # Old Classic never emitted the corrected presence contract.
    reader = corrected.presence_scoring(corrected.MODEL if model is None else model) if modern else None
    values = [reader.component(stats, key)["value"] if modern else stats.get(key, 0) for key in keys]
    for key, value in zip(keys, values):
        if value is None:
            continue
        try:
            finite(value, "source statistic", optional=False)
        except IntegrityError:
            if modern:
                return None
            raise
        if int(value) != value or key in COUNT_STATS and value < 0:
            if modern:
                return None
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
        stats = entry.get("stats")
        if isinstance(stats, dict) and "_presence" in stats:
            metadata = stats["_presence"]
            if (not isinstance(metadata, dict) or metadata.get("version") != corrected.PRESENCE
                    or metadata.get("kind") != "actual"):
                reasons.append("unsupported_statistics_presence_contract")
            else:
                original, context = metadata.get("original_row"), metadata.get("source_context")
                if (not isinstance(original, dict) or not isinstance(context, dict)
                        or original.get("player_id") != row["player_id"] or original.get("team") != row.get("team")
                        or original.get("opponent") != entry.get("opp")
                        or (context.get("season"), context.get("week")) != (row.get("season"), row.get("week"))
                        or not isinstance(original.get("stats"), dict)
                        or {k: v for k, v in stats.items() if k != "_presence"} != original["stats"]):
                    reasons.append("statistics_presence_source_identity_mismatch")
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
                      include_populations=True, statistic_contract=None):
    """Snapshot sourced final status and sparse statistics; never infer DNP."""
    root, observed_at = Path(root), utc(observed_at)
    if (output_root is None) != (derived_context is None):
        raise IntegrityError("External outcomes require explicit derived-source provenance")
    if derived_context is not None and (not isinstance(derived_context, dict) or not derived_context):
        raise IntegrityError("Missing derived input identity")
    extended = statistic_contract is not None
    if extended:
        if isinstance(statistic_contract, dict) and statistic_contract.get("version") == "offensive-ppr-rush-rec-td-presence-v2":
            corrected.statistic_model(statistic_contract, descriptive=True)
        else:
            _legacy_descriptive_model(statistic_contract)
        if output_root is None or include_populations:
            raise IntegrityError("Extended statistics require the versioned isolated local contract")
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
        name = f"stats_{season}_{week:02d}.json"
        candidates = [(root / "data/cache/stat-keys-presence-fgm-v2" / name, corrected.CLASSIC_MODEL),
                      (root / "data/cache/stat-keys-fgm-v1" / name, classic.MODEL),
                      (root / "data/cache" / name, None)]
        cache_path, statistic_model = next(((path, model) for path, model in candidates if path.exists()), candidates[-1])
        board = load_json(board_path) if board_path.exists() else {"games": []}
        cache = load_json(cache_path) if cache_path.exists() else {}
        if statistic_model is None and cache_path.parent.name == "cache" and any(
                isinstance(entry, dict) and isinstance(entry.get("stats"), dict)
                and "_presence" in entry["stats"] for entry in cache.values()):
            statistic_model = corrected.MODEL
        presence_aware = statistic_model in corrected.PRESENCE_MODELS
        outcome_schema = corrected.DESCRIPTIVE_OUTCOMES if extended and presence_aware else (
            DERIVED_STAT_SCHEMA if extended else corrected.OUTCOMES if presence_aware else "forecast-outcomes-v1")
        local_contract = descriptive_contract(presence_aware=presence_aware, model=statistic_model) if extended else (
            corrected.statistic_contract(model=statistic_model) if presence_aware else None)
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
            if extended:
                _validate_descriptive_outcome({"schema_version": outcome_schema,
                    "statistic_contract": local_contract, "derived_context": derived_context,
                    "source": "git_pinned_saved_cache_statistical_regrade", "season": season, "week": week}, row)
            elif row["category"] not in PICKABLE_STATS:
                raise IntegrityError("Legacy outcome snapshot supports ten pickable statistics only")
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
                    reader = descriptive_statistic if extended else source_statistic
                    value = reader(row["category"], entry.get("stats", {}), presence_aware=presence_aware, model=statistic_model)
                    metadata = entry.get("stats", {}).get("_presence")
                    if statistic_model == corrected.CLASSIC_MODEL and (not isinstance(metadata, dict)
                            or metadata.get("version") != corrected.PRESENCE or metadata.get("kind") != "actual"):
                        value = None
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
            if extended:
                outcomes[-1].update(position=row["position"], forecast_kickoff=row["kickoff"])
            if presence_aware and isinstance(entry, dict) and isinstance(entry.get("stats"), dict):
                outcomes[-1]["statistic_presence"] = corrected.statistic_presence(row["category"], entry["stats"], model=statistic_model)
                if actual is None and status == "unresolved" and reason == "explicit_null_stat":
                    states = sorted({value["state"] for value in outcomes[-1]["statistic_presence"].values()
                                     if value["value"] is None})
                    outcomes[-1]["reason"] = "unknown_statistic_components:" + ",".join(states)
        payload = {"schema_version": outcome_schema, "mode": mode, "season": season, "week": week,
                   "collected_at": stamp(observed_at), "source_timestamp": None,
                   "source": "existing_Sleeper_stats_cache_and_ESPN_final_game_snapshot",
                   "cache_path": cache_path.relative_to(root).as_posix(), "cache_sha256": digest(cache),
                   "game_snapshot_path": board_path.relative_to(root).as_posix(), "game_snapshot_sha256": digest(board),
                   "games": board["games"], "source_game_status": source_status,
                   "week_game_populations": populations,
                   "week_population_read_errors": population_errors, "rows": outcomes,
                   "settlement_scope": "STATISTICAL_ONLY_NOT_VENUE_SETTLEMENT"}
        if extended:
            payload.update(statistic_contract=local_contract)
        elif presence_aware:
            payload.update(statistic_contract=local_contract)
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
    extended = payload.get("schema_version") in (DERIVED_STAT_SCHEMA, corrected.DESCRIPTIVE_OUTCOMES)
    modern = payload.get("schema_version") in (corrected.OUTCOMES, corrected.DESCRIPTIVE_OUTCOMES)
    statistic_model = corrected.statistic_model(payload.get("statistic_contract"), descriptive=extended) if modern else (
        _legacy_descriptive_model(payload.get("statistic_contract")) if extended else None)
    if extended:
        _validate_descriptive_outcome(payload, row)
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
    if extended and isinstance(entry, dict):
        source_position = entry.get("pos")
        if source_position is not None and source_position != row["position"]:
            binding = {"outcome_identity_status": "quarantined",
                       "outcome_identity_reasons": sorted(set(binding["outcome_identity_reasons"] +
                                                              ["statistics_position_mismatch"]))}
        elif source_position is None and binding["outcome_identity_status"] != "quarantined":
            binding = {"outcome_identity_status": "partial_legacy",
                       "outcome_identity_reasons": sorted(set(binding["outcome_identity_reasons"] +
                                                              ["statistics_position_unavailable"]))}
    if extended and (not row.get("forecast_kickoff") or not row.get("kickoff")
                     or utc(row["forecast_kickoff"]) != utc(row["kickoff"])):
        binding = {"outcome_identity_status": "quarantined",
                   "outcome_identity_reasons": sorted(set(binding["outcome_identity_reasons"] +
                                                          ["forecast_kickoff_differs_from_recorded_game"]))}
    week_complete = bool(not extended and week_complete and (row.get("season"), row.get("week")) ==
                         (payload.get("season"), payload.get("week")) and row.get("kickoff")
                         and any(game["id"] == row.get("game_id") and utc(game["kickoff"]) == utc(row["kickoff"])
                                 for game in payload["games"]))
    status = row["status"]
    if status not in ("pending", "unresolved", "resolved", "dnp", "void"):
        raise IntegrityError("Unexpected outcome status")
    if extended and status != "resolved" and row.get("actual") is not None:
        raise IntegrityError("Undecided descriptive outcome carries a statistic")
    unsupported_legacy = not extended and row["category"] not in PICKABLE_STATS
    if unsupported_legacy:
        status = "unresolved"
    if modern and status == "resolved" and (not isinstance(entry, dict) or not isinstance(entry.get("stats"), dict)):
        binding = {"outcome_identity_status": "quarantined",
                   "outcome_identity_reasons": sorted(set(binding["outcome_identity_reasons"] +
                                                          ["missing_original_source_statistics"]))}
        status = "unresolved"
    if modern and isinstance(entry, dict) and isinstance(entry.get("stats"), dict):
        metadata = entry["stats"].get("_presence")
        if statistic_model == corrected.CLASSIC_MODEL and (not isinstance(metadata, dict)
                or metadata.get("version") != corrected.PRESENCE or metadata.get("kind") != "actual"):
            binding = {"outcome_identity_status": "quarantined",
                       "outcome_identity_reasons": sorted(set(binding["outcome_identity_reasons"] +
                                                              ["missing_corrected_source_presence"]))}
        expected_presence = corrected.statistic_presence(row["category"], entry["stats"], model=statistic_model)
        if row.get("statistic_presence") != expected_presence:
            binding = {"outcome_identity_status": "quarantined",
                       "outcome_identity_reasons": sorted(set(binding["outcome_identity_reasons"] +
                                                              ["statistic_presence_differs_from_source"]))}
        if status == "resolved":
            reader = descriptive_statistic if extended else source_statistic
            try:
                observed = reader(row["category"], entry["stats"], presence_aware=True, model=statistic_model)
                consistent = observed is not None and grade.participation(entry) == "played" and observed == row.get("actual")
            except (TypeError, ValueError):
                consistent = False
            if not consistent:
                binding = {"outcome_identity_status": "quarantined",
                           "outcome_identity_reasons": sorted(set(binding["outcome_identity_reasons"] +
                                                                  ["unsupported_or_inconsistent_source_statistic"]))}
        if binding["outcome_identity_status"] == "quarantined":
            status = "unresolved"
    if status == "resolved":
        if not past_final:
            raise IntegrityError("Outcome lacks confirmed past final")
        actual = row["actual"]
        finite(actual, "outcome", optional=False)
        if ((not extended or row["category"] != "fpts") and int(actual) != actual
                or row["category"] in COUNT_STATS | {"anytime_td"} and actual < 0):
            raise IntegrityError("Invalid integer/count outcome")
        if extended and not isinstance(entry, dict):
            raise IntegrityError("Descriptive result lacks original source statistics")
        if isinstance(entry, dict):
            if grade.participation(entry) != "played":
                raise IntegrityError("Resolved outcome has contradictory participation")
            reader = descriptive_statistic if extended else source_statistic
            observed = reader(row["category"], entry.get("stats", {}), presence_aware=modern, model=statistic_model)
            finite(observed, "saved source statistic", optional=False)
            if observed != actual:
                raise IntegrityError("Resolved outcome differs from its saved source statistic")
    attributed = bool(source and source.strip())
    terminal = status == "resolved" or (past_final and attributed and
                (status == "void" or status == "dnp" and grade.participation(entry) == "dnp"))
    normalized = dict(row)
    if modern and binding["outcome_identity_status"] == "quarantined":
        normalized.update(status="unresolved", actual=None, reason="unsupported_or_mismatched_source_statistic")
    if unsupported_legacy:
        normalized.update(status="unresolved", actual=None, reason="unsupported_legacy_statistic_contract")
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
    if extended:
        provenance.update(outcome_schema=payload["schema_version"], statistic_contract=payload["statistic_contract"])
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
        if payload.get("schema_version") not in ("forecast-outcomes-v1", DERIVED_STAT_SCHEMA, corrected.OUTCOMES, corrected.DESCRIPTIVE_OUTCOMES):
            raise IntegrityError("Unexpected outcome schema")
        if payload.get("schema_version") in (DERIVED_STAT_SCHEMA, corrected.DESCRIPTIVE_OUTCOMES):
            _validate_descriptive_outcome(payload)
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


def outcome_provenance(outcome):
    """Classify only the validated record selected for the numeric outcome.

    A historical observation, cached flag or copied source string cannot supply
    this binding. Conflicts deliberately have no selected-source provenance.
    """
    if not outcome:
        return "missing"
    if outcome.get("outcome_identity_status") == "quarantined":
        return "identity_quarantined"
    if outcome.get("outcome_conflict") or outcome.get("outcome_selection") == "conflict":
        return "conflicting_outcome_evidence"
    selected = outcome.get("selected_outcome_provenance")
    if (not isinstance(selected, dict)
            or digest(selected) != outcome.get("selected_outcome_provenance_sha256")
            or selected.get("outcome_snapshot_sha256") != outcome.get("outcome_snapshot_sha256")
            or not selected.get("outcome_row_sha256")
            or selected.get("outcome_row_sha256") != outcome.get("selected_outcome_row_sha256")
            or digest(selected) not in {digest(observation) for observation in outcome.get("outcome_observations", [])}):
        return "unknown_unverified"
    if selected.get("source") == "git_pinned_saved_cache_statistical_regrade":
        return "saved_cache_descriptive_regrade"
    if selected.get("source") == "existing_Sleeper_stats_cache_and_ESPN_final_game_snapshot":
        return "recorded_outcome_receipt"
    return "unknown_unverified"


def descriptive_forecasts(receipts, expected_hashes, observed_at, *, model_version="original_sleeper_matchup_baseline"):
    """Same native receipt selection as paired_forecasts; no policy mutation."""
    first, references, excluded = {}, {}, Counter()
    unique = {digest(payload): payload for payload in receipts}
    captures, paired_captures = Counter(), Counter()
    valid = []
    categories = PICKABLE_STATS | EXTRA_CATEGORIES
    supported = []
    modern = model_version in corrected.PRESENCE_MODELS
    classic_saved = model_version == classic.MODEL
    if model_version not in ("original_sleeper_matchup_baseline", classic.MODEL, *corrected.PRESENCE_MODELS):
        raise IntegrityError("Unsupported descriptive model selector")
    if classic_saved and expected_hashes != classic.ENGINE:
        raise IntegrityError("Classic descriptive source must match the closed manifest")
    if modern and expected_hashes != corrected.source_hashes(model_version):
        raise IntegrityError("Corrected descriptive source must match the closed manifest")
    for sha, payload in unique.items():
        if (payload.get("schema_version") != (corrected.NATIVE if modern else classic.CAPTURE if classic_saved else "baseline-capture-v1")
                or payload.get("model") != model_version
                or payload.get("engine_files") != expected_hashes
                or payload.get("engine_sha256") != digest(expected_hashes)):
            excluded["unsupported_forecast_contract_or_engine"] += 1
            continue
        if modern:
            corrected.native_contract(payload)
        elif classic_saved:
            classic.native_contract(payload)
        supported.append((sha, payload))
    for sha, payload in sorted(supported, key=lambda item: (utc(item[1]["captured_at"]), item[0])):
        if payload.get("mode") != "live":
            excluded["non_live_receipt"] += 1
            continue
        captured, generated = utc(payload["captured_at"]), utc(payload["forecast_generated_at"])
        if generated > captured:
            raise IntegrityError("Forecast generated after capture")
        if captured > utc(observed_at):
            excluded["future_receipt"] += 1
            continue
        if not modern and not classic_saved and expected_hashes.get("pull/scoring.py") != SCORING_V1_SHA256:
            raise IntegrityError("Unrecognized original descriptive scoring engine")
        valid.append(payload)
        references[sha] = payload
        periods = {(row["season"], row["week"]) for row in payload["rows"]}
        if len(periods) > 1 or any(payload.get(k, value) != value for period in periods
                                   for k, value in zip(("season", "week"), period)):
            raise IntegrityError("Descriptive forecast period differs from original rows")
        seen = set()
        for row in payload["rows"]:
            if row["category"] not in categories:
                excluded["unsupported_category"] += 1
                continue
            key = identity(row)
            if key in seen:
                raise IntegrityError("Duplicate opportunity within a receipt")
            seen.add(key)
            if (type(row["season"]) is not int or type(row["week"]) is not int or not 1 <= row["week"] <= 18
                    or any(not isinstance(row.get(k), str) or not row[k].strip()
                           for k in ("game_id", "player_id", "team"))):
                raise IntegrityError("Malformed descriptive forecast identity")
            if row["category"] not in scoring.POSITION_CATEGORIES.get(row.get("position"), ()):
                excluded["unsupported_category_position"] += 1
                continue
            if captured >= utc(row["kickoff"]):
                excluded["not_pregame"] += 1
                continue
            for name in ("raw_projection", "adjusted_projection"):
                finite(row.get(name), name)
            if row.get("raw_projection") is None and row.get("adjusted_projection") is None:
                excluded["missing_forecast"] += 1
                continue
            if row["category"] == "anytime_td" and (row.get("raw_projection") is None
                                                     or row["raw_projection"] < 0):
                raise IntegrityError("Missing/negative saved TD expectation")
            captures[row["category"]] += 1
            paired_captures[row["category"]] += (row.get("raw_projection") is not None
                                                and row.get("adjusted_projection") is not None)
            first.setdefault(key, {**row, "captured_at": payload["captured_at"],
                "forecast_generated_at": payload["forecast_generated_at"], "baseline_payload_sha256": sha,
                "baseline_input_sha256": payload["input_sha256"], "engine_sha256": payload["engine_sha256"],
                "model_version": payload["model"],
                "observation_row_sha256": digest(row)})
    if modern or classic_saved:
        # The registered primary selector intentionally rejects these models.
        # Preserve the same earliest eligible paired-observation rule locally.
        pairs = {}
        for payload in valid:
            for row in payload["rows"]:
                key = identity(row)
                if (key in first and row["category"] != "anytime_td"
                        and utc(payload["captured_at"]) < utc(row["kickoff"])
                        and row.get("raw_projection") is not None and row.get("adjusted_projection") is not None):
                    pairs.setdefault(key, {**row, "captured_at": payload["captured_at"],
                        "forecast_generated_at": payload["forecast_generated_at"], "baseline_payload_sha256": digest(payload)})
    else:
        pairs, _ = paired_forecasts(valid, {"baseline": "original_sleeper_matchup_baseline",
                                        "targets": sorted(PICKABLE_STATS | {"fpts"})}, expected_hashes,
                               row_eligible=lambda row: row["category"] in
                                   scoring.POSITION_CATEGORIES.get(row.get("position"), ()))
    pairs = {key: {**row, "baseline_input_sha256": references[row["baseline_payload_sha256"]]["input_sha256"],
                   "engine_sha256": references[row["baseline_payload_sha256"]]["engine_sha256"],
                   "model_version": references[row["baseline_payload_sha256"]]["model"],
                   "observation_row_sha256": digest({k: v for k, v in row.items() if k not in
                       ("captured_at", "forecast_generated_at", "baseline_payload_sha256")})}
             for key, row in pairs.items() if key in first
             and row["category"] in scoring.POSITION_CATEGORIES.get(row.get("position"), ())}
    return first, pairs, {"unique_receipts": len(unique), "duplicate_receipts": len(receipts) - len(unique),
        "eligible_capture_rows": dict(captures), "paired_capture_rows": dict(paired_captures),
        "excluded": dict(excluded)}


def original_board_index(records):
    """Hash actual complete documents once; a locator or validation flag is insufficient."""
    result = {}
    for record in records:
        board = record["document"]
        if not isinstance(board, dict) or not isinstance(board.get("players"), list) or not isinstance(board.get("games"), list):
            raise IntegrityError("Malformed original forecast board")
        sha = digest(board)
        if record.get("document_sha256", sha) != sha:
            raise IntegrityError("Original board document checksum mismatch")
        players, games = {}, {}
        for game in board["games"]:
            if not isinstance(game.get("id"), str) or game["id"] in games:
                raise IntegrityError("Duplicate/malformed original board game")
            games[game["id"]] = game
        for player in board["players"]:
            if not isinstance(player.get("id"), str) or player["id"] in players:
                raise IntegrityError("Duplicate/malformed original board player")
            props = player.get("props")
            if not isinstance(props, list) or len({p["key"] for p in props}) != len(props):
                raise IntegrityError("Duplicate/malformed original board category")
            players[player["id"]] = player
        source = {key: record[key] for key in ("file_sha256", "git_blob_sha1", "git_commit") if record.get(key)}
        result.setdefault(sha, {"document": board, "players": players, "games": games, "source": source})
    return result


def bind_original_board(row, boards):
    record = boards.get(row["baseline_input_sha256"])
    if record is None:
        return {"status": "missing_exact_original_board"}
    board, player = record["document"], record["players"].get(row["player_id"])
    game = record["games"].get(row["game_id"])
    try:
        model = row.get("model_version", "original_sleeper_matchup_baseline")
        if model in corrected.PRESENCE_MODELS:
            source_scoring = corrected.presence_scoring(model)
        elif model in ("original_sleeper_matchup_baseline", classic.MODEL):
            source_scoring = classic.scoring() if model == classic.MODEL else corrected.legacy_scoring()
        else:
            raise IntegrityError("Unsupported original-board model")
        if ((board["season"], board["week"]) != (row["season"], row["week"])
                or utc(board["generated_at"]) != utc(row["forecast_generated_at"])
                or utc(board["generated_at"]) > utc(row["captured_at"])
                or board.get("scoring") != scoring.PPR or not player or not game
                or player.get("game_id") != row["game_id"] or player.get("team") != row["team"]
                or player.get("pos") != row["position"] or player.get("late")
                or game.get("state") != "pre"
                or utc(game["kickoff"]) != utc(row["kickoff"])
                or utc(row["captured_at"]) >= utc(game["kickoff"])
                or row["team"] not in (game.get("home"), game.get("away"))):
            raise IntegrityError("Original board identity/clock/scoring mismatch")
        if player.get("opp") is not None and player["opp"] != (game["away"] if row["team"] == game["home"] else game["home"]):
            raise IntegrityError("Original board opponent mismatch")
        props = [p for p in player["props"] if p["key"] == row["category"]]
        if len(props) != 1:
            raise IntegrityError("Original board category missing")
        prop = props[0]
        fields = {"proj": "raw_projection", "adj": "adjusted_projection", "line": "line",
                  "lean": "lean", "mf": "matchup_factor"}
        if (any(prop.get(source) != row.get(target) for source, target in fields.items())
                or prop.get("line_from", "ours") != row.get("line_from")):
            raise IntegrityError("Original board forecast differs from receipt")
        for side in ("over", "under"):
            selected = any(p["player_id"] == row["player_id"] and p["key"] == row["category"]
                           for p in board["picks"][side])
            if type(row.get("top_" + side)) is not bool or row["top_" + side] != selected:
                raise IntegrityError("Original board Top membership differs from receipt")
        if row["category"] == "fpts" and row.get("raw_projection") is not None:
            # Projection components are fractional; validate, then use the exact
            # retained scoring function (actual component counts are stricter).
            projection = player.get("proj")
            if not isinstance(projection, dict) or not projection:
                raise IntegrityError("Original PPR projection components missing")
            for key in set(scoring.PPR) | {"idp_fum_rec"}:
                if key in projection:
                    finite(projection[key], "original PPR projection component", optional=False)
            value = (source_scoring.ppr_points(projection, projection=True) if model in corrected.PRESENCE_MODELS
                     else source_scoring.ppr_points(projection))
            if value != row["raw_projection"]:
                raise IntegrityError("Original component PPR differs from receipt")
        if row["category"] == "anytime_td":
            projection = player.get("proj")
            if not isinstance(projection, dict):
                raise IntegrityError("Original TD projection components missing")
            for key in ("rush_td", "rec_td"):
                finite(projection.get(key, 0), "original TD projection component", optional=False)
            value = (source_scoring.stat_value("anytime_td", projection, projection=True) if model in corrected.PRESENCE_MODELS
                     else source_scoring.stat_value("anytime_td", projection))
            if round(value, 2) != row["raw_projection"]:
                raise IntegrityError("Original TD expectation differs from receipt")
        provider = player.get("proj_ppr") if row["category"] == "fpts" else None
        probability = prop.get("td_chance") if row["category"] == "anytime_td" else None
        finite(provider, "saved provider fantasy total")
        finite(probability, "saved TD probability")
        if probability is not None and (not 0 <= probability <= 1 or
                probability != round(source_scoring.td_probability(row["raw_projection"]), 3)):
            raise IntegrityError("Saved TD probability differs from retained formula")
    except (KeyError, TypeError, ValueError) as err:
        return {"status": "invalid_exact_original_board", "reason": str(err),
                "document_sha256": row["baseline_input_sha256"], **record["source"]}
    return {"status": "bound_exact_original_board", "document_sha256": row["baseline_input_sha256"],
            "prop_sha256": digest(prop), "provider_ppr": provider, "recorded_probability": probability,
            **record["source"]}


def _sample_context(rows):
    return {"opportunities": len(rows), "unique_players": len({r["player_id"] for r in rows}),
            "unique_games": len({(r["season"], r["week"], r["game_id"]) for r in rows}),
            "unique_weeks": len({(r["season"], r["week"]) for r in rows})}


def _point_metrics(rows, field):
    result = metrics(rows, field)
    errors = [Decimal(str(r[field])) - Decimal(str(r["actual"])) for r in rows]
    result.update(bias=result["mean_error"], absolute_error_sum=float(sum(map(abs, errors))),
                  squared_error_sum=float(sum(e * e for e in errors)), signed_error_sum=float(sum(errors)))
    return result


def _paired_metrics(rows, raw="raw_projection"):
    changes = [abs(Decimal(str(r["adjusted_projection"])) - Decimal(str(r["actual"]))) -
               abs(Decimal(str(r[raw])) - Decimal(str(r["actual"]))) for r in rows]
    return {"raw": _point_metrics(rows, raw), "adjusted": _point_metrics(rows, "adjusted_projection"),
            "helps": sum(v < 0 for v in changes), "hurts": sum(v > 0 for v in changes),
            "ties": sum(v == 0 for v in changes), "absolute_error_change_sum": float(sum(changes)),
            "sample": _sample_context(rows)}


def probability_scores(probability, event):
    finite(probability, "probability", optional=False)
    if not 0 <= probability <= 1 or type(event) is not int or event not in (0, 1):
        raise IntegrityError("Invalid binary probability/event")
    impossible = probability == 0 and event == 1 or probability == 1 and event == 0
    return {"brier": (probability - event) ** 2,
            "log_loss": None if impossible else -math.log(probability) if event else -math.log1p(-probability),
            "log_loss_state": "positive_infinity" if impossible else "finite"}


def _td_metrics(rows):
    resolved = [r for r in rows if r["evaluation_status"] == "resolved" and r.get("probability") is not None]
    infinite = sum(r["log_loss_state"] == "positive_infinity" for r in resolved)
    finite_losses = [r["log_loss"] for r in resolved if r["log_loss_state"] == "finite"]
    bins = []
    for i in range(10):
        group = [r for r in resolved if min(int(r["probability"] * 10), 9) == i]
        bins.append({"lower": i / 10, "upper": (i + 1) / 10, "upper_inclusive": i == 9,
                     "n": len(group), "events": sum(r["actual_event"] for r in group),
                     "predicted_mean": statistics.mean(r["probability"] for r in group) if group else None,
                     "event_rate": statistics.mean(r["actual_event"] for r in group) if group else None,
                     "sample": _sample_context(group)})
    return {"n": len(resolved), "events": sum(r["actual_event"] for r in resolved),
            "sample": _sample_context(resolved), "brier_sum": math.fsum(r["brier"] for r in resolved),
            "brier": statistics.mean(r["brier"] for r in resolved) if resolved else None,
            "finite_log_loss_sum": math.fsum(finite_losses), "infinite_log_loss_count": infinite,
            "log_loss": None if infinite or not resolved else math.fsum(finite_losses) / len(resolved),
            "log_loss_state": "positive_infinity" if infinite else "finite" if resolved else "unavailable",
            "probability_provenance": dict(Counter(r["probability_provenance"] for r in rows)),
            "expected_count": _point_metrics([dict(r, actual=r["actual"]) for r in rows
                                               if r["evaluation_status"] == "resolved"], "raw_projection"),
            "calibration": bins}


def evaluate_descriptive(first, pairs, numeric_outcomes, extra_outcomes, *, original_boards=(),
                         model_version="original_sleeper_matchup_baseline"):
    """Local additive metrics. Never promotes, pools units or edits an observation."""
    if model_version not in ("original_sleeper_matchup_baseline", classic.MODEL, *corrected.PRESENCE_MODELS):
        raise IntegrityError("Unsupported descriptive report model")
    rows = list(first.values()) + list(pairs.values())
    original_engine = (digest(corrected.legacy_engine_hashes())
                       if model_version == "original_sleeper_matchup_baseline"
                       and any(row.get("engine_sha256") is not None for row in rows) else None)
    for row in rows:
        if row.get("model_version", model_version) != model_version:
            raise IntegrityError("Descriptive report cannot mix or relabel model cohorts")
        if model_version in corrected.PRESENCE_MODELS and row.get("engine_sha256") != digest(corrected.source_hashes(model_version)):
            raise IntegrityError("Corrected descriptive row lacks the closed engine identity")
        if model_version == classic.MODEL and row.get("engine_sha256") != digest(classic.ENGINE):
            raise IntegrityError("Classic descriptive row lacks the closed engine identity")
        if (model_version == "original_sleeper_matchup_baseline" and row.get("engine_sha256") is not None
                and row["engine_sha256"] != original_engine):
            raise IntegrityError("Original descriptive row has an incompatible engine identity")
    boards = original_board_index(original_boards)
    def outcome_row(key, row):
        outcomes = extra_outcomes if row["category"] in EXTRA_CATEGORIES else numeric_outcomes
        outcome, binding = bind_outcome(row, outcomes.get(key), key=key)
        status = outcome.get("status", "pending")
        reason = outcome.get("reason", "no_saved_outcome")
        if binding["status"] == "schedule_changed":
            status = "excluded_schedule_changed"
        elif outcome.get("outcome_conflict"):
            status, reason = "unresolved", "conflicting_outcome_evidence"
        item = {**row, "evaluation_status": status,
                "actual": outcome.get("actual") if status == "resolved" else None,
                "outcome_reason": reason,
                "outcome_conflict": outcome.get("outcome_conflict", False),
                "outcome_source_mix": outcome.get("outcome_source_mix"),
                "outcome_selection": outcome.get("outcome_selection"),
                "outcome_identity_status": outcome.get("outcome_identity_status"),
                "selected_outcome_provenance": outcome.get("selected_outcome_provenance"),
                "outcome_observations": outcome.get("outcome_observations", []),
                "outcome_revision": outcome.get("outcome_revision", False),
                "forecast_provenance": "original_recorded_pregame_observation",
                "outcome_provenance": outcome_provenance(outcome)}
        if item["category"] == "fpts":
            binding = bind_original_board(row, boards)
            item.update(original_board=binding, provider_ppr=binding.get("provider_ppr"),
                        raw_comparator="saved_component_derived_offensive_PPR" if row.get("raw_projection") is not None else "missing_raw_forecast",
                        adjusted_comparator="saved_component_PPR_times_original_matchup_factor" if row.get("raw_projection") is not None
                                            else "saved_season_average_PPR_times_original_matchup_factor")
        if item["evaluation_status"] == "resolved":
            for field in ("raw_projection", "adjusted_projection", "provider_ppr"):
                if item.get(field) is not None:
                    error = Decimal(str(item[field])) - Decimal(str(item["actual"]))
                    item[field + "_error"] = float(error)
                    item[field + "_absolute_error"] = float(abs(error))
                    item[field + "_squared_error"] = float(error * error)
            if item.get("raw_projection") is not None and item.get("adjusted_projection") is not None:
                delta = Decimal(str(item["adjusted_projection_absolute_error"])) - Decimal(str(item["raw_projection_absolute_error"]))
                item.update(absolute_error_delta=float(delta), adjustment_effect="helps" if delta < 0 else "hurts" if delta > 0 else "ties")
        return item
    population = [outcome_row(key, row) for key, row in sorted(first.items())]
    paired = [outcome_row(key, row) for key, row in sorted(pairs.items())]
    td_rows = []
    for row in population:
        if row["category"] != "anytime_td":
            continue
        binding = bind_original_board(row, boards)
        probability, provenance = None, "invalid_exact_original_board"
        if binding["status"] != "invalid_exact_original_board":
            probability = binding.get("recorded_probability")
            provenance = "originally_recorded_probability" if probability is not None else "rederived_from_original_count_retained_formula"
            if probability is None:
                probability = round((corrected.presence_scoring(model_version) if model_version in corrected.PRESENCE_MODELS
                                     else classic.scoring() if model_version == classic.MODEL else corrected.legacy_scoring()).td_probability(row["raw_projection"]), 3)
        item = dict(row, original_board=binding, probability=probability,
                    probability_provenance=provenance, adjusted_probability=None, actual_event=None)
        if row["evaluation_status"] == "resolved" and probability is not None:
            item["actual_event"] = int(row["actual"] >= 1)
            item.update(probability_scores(probability, item["actual_event"]))
        td_rows.append(item)
    categories = {}
    for category in sorted(PICKABLE_STATS | EXTRA_CATEGORIES):
        group = [r for r in population if r["category"] == category]
        matched = [r for r in paired if r["category"] == category]
        final = [r for r in matched if r["evaluation_status"] == "resolved"]
        unpaired = [r for r in group if identity(r) not in pairs and category != "anytime_td"]
        final_unpaired = [r for r in unpaired if r["evaluation_status"] == "resolved" and r.get("adjusted_projection") is not None]
        value = {"coverage": _sample_context(group), "outcome_status": dict(Counter(r["evaluation_status"] for r in group)),
                 "paired_coverage": _sample_context(matched), "paired_status": dict(Counter(r["evaluation_status"] for r in matched)),
                 "paired_no_lean": sum(r.get("lean") is None for r in matched),
                 "paired_reference_only": sum(r.get("line_from") not in ("dk", "sleeper") for r in matched),
                 "paired": _paired_metrics(final), "unpaired_coverage": _sample_context(unpaired),
                 "unpaired_status": dict(Counter(r["evaluation_status"] for r in unpaired)),
                 "adjusted_only": _point_metrics(final_unpaired, "adjusted_projection"),
                 "unpaired_missingness": dict(Counter("raw_missing" if r.get("raw_projection") is None else
                                                       "adjusted_missing" for r in unpaired)),
                 "positions": {pos: _paired_metrics([r for r in final if r["position"] == pos]) for pos in sorted({r["position"] for r in matched})}}
        if category == "fpts":
            direct = [r for r in final if r.get("provider_ppr") is not None]
            value["direct_provider_vs_adjusted_component_PPR"] = _paired_metrics(direct, "provider_ppr")
            value["direct_provider_forecast_coverage"] = sum(r.get("provider_ppr") is not None for r in matched)
        if category == "anytime_td":
            value["probability"] = _td_metrics(td_rows)
        categories[category] = value
    unpaired_rows = [r for r in population if identity(r) not in pairs and r["category"] != "anytime_td"]
    if model_version not in ("original_sleeper_matchup_baseline", classic.MODEL, *corrected.PRESENCE_MODELS):
        raise IntegrityError("Unsupported descriptive model selector")
    return {"schema_version": DESCRIPTIVE_VERSION, "statistic_contract": descriptive_contract(presence_aware=model_version in corrected.PRESENCE_MODELS, model=model_version if model_version in (*corrected.PRESENCE_MODELS, classic.MODEL) else None),
            "model_version": model_version,
            "scope": "DESCRIPTIVE_EXTENSION_NOT_REGISTERED_PRIMARY_EXPERIMENT",
            "observation_selection": "earliest_eligible_same_receipt_values_by_capture_time_then_payload_digest",
            "coverage": _sample_context(population), "outcome_status": dict(Counter(r["evaluation_status"] for r in population)),
            "paired_coverage": _sample_context(paired), "categories": categories,
            "rows": population, "paired_rows": paired, "unpaired_rows": unpaired_rows,
            "adjusted_only_rows": [r for r in unpaired_rows if r.get("adjusted_projection") is not None], "td_rows": td_rows,
            "limitations": ["No original Week 6 matchup proof reconstructed; whole-week qualification is separate.",
                            "Inherited/unclocked archives are excluded from this original-observation comparison.",
                            "No mixed-unit metric, fitting, promotion, profitability or production activation.",
                            "Originally recorded and formula-rederived probabilities remain distinct."]}


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
        outcome, binding = bind_outcome(row, outcomes.get(key), key=key)
        status = outcome["status"]
        if utc(row["kickoff"]) <= utc(policy["registered_at"]):
            status = "excluded_pre_registration_game"
        elif binding["status"] == "schedule_changed":
            status = "excluded_schedule_changed"
        statuses[status] += 1
        hours = (utc(row["kickoff"]) - utc(row["captured_at"])).total_seconds() / 3600
        lead_times["under_24h" if hours < 24 else "24_to_72h" if hours <= 72 else "over_72h"] += 1
        injuries[row.get("injury_at_capture") or "no_designation_reported"] += 1
        item = {**row, "evaluation_status": status, "actual": outcome.get("actual"),
                "outcome_reason": outcome.get("reason"),
                "outcome_identity_status": outcome.get("outcome_identity_status"),
                "outcome_identity_reasons": outcome.get("outcome_identity_reasons", []),
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
    return {"schema_version": "forecast-scorecard-v2", "policy_version": policy["version"], "policy_sha256": digest(policy),
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
    receipt_roots = [root / "data" / lane]
    if mode == "live":
        receipt_roots.append(root / "data/current-classic")
    receipts = [read(p) for directory in receipt_roots for p in sorted(directory.rglob("*.json.gz"))]
    current_model = any(all((root / name).is_file() and not (root / name).is_symlink()
                           and hashlib.sha256((root / name).read_bytes()).hexdigest() == value
                           for name, value in corrected.source_hashes(model).items())
                        for model in corrected.PRESENCE_MODELS)
    hashes = corrected.legacy_engine_hashes() if current_model else engine_hashes(root)
    pairs, coverage = paired_forecasts(receipts, policy, hashes, allow_replay=allow_replay)
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
