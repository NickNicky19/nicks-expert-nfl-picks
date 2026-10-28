"""Capture existing Sleeper NFL normal-line selection contracts without inventing entry economics."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from reliability import IntegrityError, digest, finite, stamp, utc

TARGETS = {"receptions": "rec", "rushing_attempts": "rush_att", "passing_yards": "pass_yd"}
SOURCE = "https://api.sleeper.app/lines/available"
PARAMS = {"dynamic": "true", "include_preseason": "true", "eg": "15.control"}


def source_time(value, collected_at):
    """Preserve raw epoch milliseconds; field semantics are not quote freshness."""
    if value is None:
        return {"field": "updated_at", "raw": None, "utc": None, "status": "not_supplied"}
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"field": "updated_at", "raw": value, "utc": None, "status": "invalid"}
    try:
        timestamp = datetime.fromtimestamp(value / 1000, timezone.utc)
        if value < 0 or timestamp > utc(collected_at):
            raise ValueError("Invalid/future source timestamp")
        return {"field": "updated_at", "raw": value, "utc": stamp(timestamp),
                "status": "source_reported_field_not_verified_quote_time"}
    except (ValueError, OverflowError, OSError):
        return {"field": "updated_at", "raw": value, "utc": None, "status": "invalid"}


def capture_offers(data, observation, projection_metadata, rules):
    at = observation["collected_at"]
    candidates = {}
    for player in data["players"]:
        game = next(g for g in data["games"] if g["id"] == player["game_id"])
        if player.get("late") or game["state"] != "pre" or utc(game["kickoff"]) <= utc(at):
            continue
        for prop in player["props"]:
            if prop["key"] in TARGETS.values():
                for side in ("over", "under"):
                    candidates[(player["id"], prop["key"], side)] = (player, game)
    raw = observation.get("markets")
    source_status = observation["status"]
    if source_status == "available" and not isinstance(raw, list):
        source_status = "missing_information"
    by_key = {}
    schema_issues = []
    if source_status == "available":
        for market in raw:
            if not isinstance(market, dict):
                schema_issues.append("non_object_market")
                continue
            options = market.get("options")
            if not isinstance(options, list):
                schema_issues.append("missing_options")
                continue
            for option in options:
                if not isinstance(option, dict):
                    schema_issues.append("non_object_option")
                    continue
                sport = option.get("sport", market.get("sport"))
                wager = option.get("wager_type", market.get("wager_type"))
                if sport != "nfl" or wager not in TARGETS:
                    continue
                if option.get("game_status") != "pre_game" or option.get("line_type") != "normal":
                    continue
                if market.get("status") != "active" or option.get("status") != "active":
                    continue
                if option.get("subject_type") != "player" or option.get("outcome_type") != "over_under":
                    schema_issues.append("unsupported_target_contract")
                    continue
                pid, side = option.get("subject_id"), option.get("outcome")
                if pid is None or side not in ("over", "under"):
                    schema_issues.append("missing_selection_identity")
                    continue
                key = (str(pid), TARGETS[wager], side)
                by_key.setdefault(key, []).append((market, option))
    rows = []
    for (pid, category, side), (player, game) in sorted(candidates.items()):
        row = {"season": data["season"], "week": data["week"], "game_id": game["id"],
               "kickoff": game["kickoff"], "player_id": pid, "name": player["name"], "team": player["team"],
               "category": category, "side": side, "collected_at": at, "source": "sleeper_picks",
               "collection_status": "no_offer", "line": None, "price_or_payout": None,
               "source_timestamp": {"field": "updated_at", "raw": None, "utc": None, "status": "not_supplied"},
               "settlement_rule_provenance": rules, "settlement_status": "NOT_VERIFIED",
               "entry_economics_complete": False, "expected_value": None,
               "missing_information": []}
        options = by_key.get((pid, category, side), [])
        if source_status != "available":
            row["collection_status"] = "source_unavailable" if source_status == "unavailable" else "missing_information"
            row["missing_information"] = ["source_response"]
        elif not options:
            if schema_issues:
                row["collection_status"] = "missing_information"
                row["missing_information"] = ["ambiguous_source_schema"]
        else:
            if len(options) != 1:
                row["collection_status"] = "missing_information"
                row["missing_information"] = ["ambiguous_multiple_normal_selections"]
                row["raw_alternatives"] = [o for _, o in options]
                rows.append(row)
                continue
            market, option = options[0]
            row["raw_option"] = option
            row["source_game_id"] = option.get("game_id")
            row["source_line_id"] = option.get("line_id")
            row["source_market_type"] = option.get("market_type")
            row["source_timestamp"] = source_time(market.get("updated_at"), at)
            row["line"] = option.get("outcome_value")
            missing = []
            try:
                finite(row["line"], "offer line", optional=False)
            except IntegrityError:
                missing.append("valid_line")
            multiplier = option.get("payout_multiplier")
            try:
                amount = Decimal(str(multiplier))
                if not amount.is_finite() or amount <= 0:
                    raise InvalidOperation
                row["price_or_payout"] = {"type": "offered_selection_multiplier", "raw": multiplier,
                                          "standalone_bet_price": False, "complete_entry_payout": False}
            except (InvalidOperation, ValueError):
                missing.append("selection_multiplier")
            meta = projection_metadata.get(pid)
            if not meta or (str(meta.get("season")), meta.get("week"), meta.get("game_id"), meta.get("team"), meta.get("opponent")) != (
                    str(data["season"]), data["week"], option.get("game_id"), player["team"], player["opp"]):
                missing.append("verified_game_mapping")
            else:
                row["game_mapping_provenance"] = meta
            if not row["source_line_id"]:
                missing.append("source_line_id")
            if option.get("market_type") != f"{option.get('wager_type')}_over_under_player_{pid}":
                missing.append("verified_full_game_market_type")
            if str(option.get("season")) != str(data["season"]) or option.get("season_type") != "regular":
                missing.append("source_season_scope")
            if option.get("subject_team") != player["team"]:
                missing.append("source_player_team")
            if row["source_timestamp"]["status"] == "invalid":
                missing.append("valid_source_timestamp")
            if not rules.get("documents"):
                missing.append("rule_provenance")
            row["contract"] = {"sport": "nfl", "subject": "player", "statistic": category, "side": side,
                               "line_type": "normal", "period": "full_game_including_overtime",
                               "period_provenance": "Sleeper_Player_Picks_rules_scope", "source_game_id": option.get("game_id")}
            row["collection_status"] = "missing_information" if missing else "complete_selection_capture"
            row["missing_information"] = missing + ["entry_format", "complete_entry_payout_table",
                                                    "entry_context_and_acceptance", "entry_specific_settlement_binding"]
        rows.append(row)
    counts = Counter(r["collection_status"] for r in rows)
    return {"schema_version": "sleeper-selection-offers-v1", "mode": observation.get("mode", "live"),
            "season": data["season"], "week": data["week"], "collected_at": at,
            "source_url": SOURCE, "source_params": PARAMS, "source_status": source_status,
            "response_sha256": observation.get("response_sha256"), "raw_scope_markets": raw,
            "schema_issues": schema_issues, "source_error": observation.get("error"),
            "rule_provenance_sha256": digest(rules), "rows": rows, "coverage": dict(counts),
            "complete_executable_entries": 0, "quote_freshness": "NOT_ESTABLISHED",
            "access_scope": "reuse_existing_repository_public_read_only_request_no_new_endpoint",
            "licensing_scope": "commercial_or_expanded_use_not_established"}
