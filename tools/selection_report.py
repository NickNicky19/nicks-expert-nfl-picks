"""Offline, immutable selection/timing decisions and row-reconciled grading.

Reads saved observations only. No provider requests, forecasting, production
publication, scheduler, venue settlement or inference/promotion decisions.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import html
import io
import itertools
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

from evidence import read, write
from reliability import IntegrityError, canonical, digest, engine_hashes, finite, load_json, stamp, utc
from scorecard import (identity, bind_outcome, latest_outcomes, paired_forecasts, score, snapshot_outcomes,
                       DERIVED_STAT_SCHEMA, EXTRA_CATEGORIES, descriptive_contract,
                       descriptive_forecasts, evaluate_descriptive, outcome_provenance)
import grade
import data_integrity_v2 as corrected

ROOT = Path(__file__).resolve().parents[1]
VERSION = "selection-report-v3"
LEGACY_VERSION = "selection-report-v2"
CHICAGO = ZoneInfo("America/Chicago")
RESULTS = ("win", "loss", "push", "dnp", "pending", "unresolved", "excluded", "no_action", "not_due")
PATTERNS = ("data/forward/**/*.json.gz", "data/outcomes/**/*.json.gz",
            "data/offers/**/*.json.gz", "data/cache/stats_*.json",
            "output/data/archive/*.json", "output/data/weeks/*.json",
            "output/data/week.json", "output/data/game-status.json")


def weekday(value):
    return utc(value).astimezone(CHICAGO).strftime("%A") if value else None


def _lead_bucket(seconds, policy):
    if seconds is None:
        return None
    for rule in policy["lead_time_buckets"]:
        if seconds >= rule["minimum_seconds"] and (rule["maximum_seconds"] is None
                                                   or seconds < rule["maximum_seconds"]):
            return rule["id"]
    return None


def _snapshots(receipts, policy, as_of, expected_hashes):
    """Validate the retained version; readable unknown contracts stay excluded."""
    snapshots, excluded, seen = [], Counter(), set()
    for payload in sorted(receipts, key=digest):
        sha = digest(payload)
        if sha in seen:
            excluded["duplicate_receipt"] += 1
            continue
        seen.add(sha)
        modern = payload.get("schema_version") == corrected.NATIVE
        if modern:
            corrected.native_contract(payload)
        if not modern and (payload.get("schema_version") != "baseline-capture-v1"
                or payload.get("model") != policy["model"]):
            excluded["unsupported_forecast_contract"] += 1
            continue
        expected = corrected.V2_SOURCE_SHA256 if modern else expected_hashes
        if payload.get("engine_files") != expected or payload.get("engine_sha256") != digest(expected):
            excluded["unrecognized_engine"] += 1
            continue
        if payload.get("mode") != "live":
            excluded["non_live_receipt"] += 1
            continue
        captured, generated = utc(payload["captured_at"]), utc(payload["forecast_generated_at"])
        if captured > as_of or generated > captured:
            excluded["future_or_reversed_clock"] += 1
            continue
        periods = {(row["season"], row["week"]) for row in payload["rows"]}
        # Original baseline-v1 stores the period on each row, not necessarily
        # at envelope level. Read that recorded period, never today's week.
        if not periods:
            excluded["empty_snapshot_without_recorded_period"] += 1
            continue
        if len(periods) != 1:
            raise IntegrityError("Mixed periods in one original baseline receipt")
        season, week = next(iter(periods))
        if (type(season) is not int or type(week) is not int or not 1 <= week <= 18
                or payload.get("season", season) != season or payload.get("week", week) != week):
            raise IntegrityError("Forecast period differs from original rows")
        rows = {}
        for original in payload["rows"]:
            if original["category"] not in policy["categories"]:
                continue
            key = identity(original)
            if ((original["season"], original["week"]) != (season, week)
                    or any(not isinstance(original[k], str) or not original[k]
                           for k in ("game_id", "player_id", "team"))):
                raise IntegrityError("Forecast opportunity identity differs from receipt")
            if captured >= utc(original["kickoff"]):
                excluded["not_pregame_row"] += 1
                continue
            for name in ("raw_projection", "adjusted_projection", "line"):
                finite(original.get(name), name)
            if original.get("lean") not in (None, "over", "under"):
                raise IntegrityError("Unknown saved lean")
            if any(type(original.get(flag)) is not bool for flag in ("top_over", "top_under")):
                raise IntegrityError("Missing/invalid recorded Top membership")
            row = dict(original, observation_row_sha256=digest(original))
            if key in rows:
                rows[key]["invalid_reason"] = "duplicate_opportunity_in_receipt"
                continue
            if (row["top_over"] and row["top_under"]
                    or row["top_over"] and row.get("lean") != "over"
                    or row["top_under"] and row.get("lean") != "under"):
                row["invalid_reason"] = "contradictory_recorded_top_membership"
            rows[key] = row
        snapshots.append({"payload_sha256": sha, "captured_at": stamp(captured),
                          "forecast_generated_at": payload["forecast_generated_at"],
                          "season": season, "week": week,
                          "model": payload["model"], "engine_sha256": payload["engine_sha256"],
                          "engine_files": payload["engine_files"], "rows": rows})
    # Equal collection instants with disagreeing contents are not resolved by
    # a digest tie-break. Keep their union for coverage, quarantine the snapshot.
    grouped = defaultdict(list)
    for snapshot in snapshots:
            grouped[(snapshot["season"], snapshot["week"], snapshot["captured_at"], snapshot["model"], snapshot["engine_sha256"])].append(snapshot)
    result = []
    for group in grouped.values():
        first = group[0]
        signatures = {digest([r for _, r in sorted(s["rows"].items())]) for s in group}
        merged = dict(first, rows=dict(first["rows"]), receipt_refs=sorted(s["payload_sha256"] for s in group),
                      snapshot_conflict=len(signatures) > 1)
        merged["ambiguous_kickoff_keys"] = {key for key in set().union(*(s["rows"] for s in group))
                                            if len({utc(s["rows"][key]["kickoff"]) for s in group
                                                    if key in s["rows"]}) > 1}
        for item in group[1:]:
            for key, row in item["rows"].items():
                merged["rows"].setdefault(key, row)
        result.append(merged)
    return sorted(result, key=lambda s: (utc(s["captured_at"]), s["payload_sha256"])), dict(excluded)


def _selected(row, cohort):
    if row.get("invalid_reason") or row.get("line_from") not in ("dk", "sleeper") or row.get("line") is None:
        return False
    if row.get("lean") not in ("over", "under"):
        return False
    return cohort == "all_qualifying_leans" or row["top_" + row["lean"]]


def _decision(template, snapshot, row, cohort, checkpoint, policy, *, boundary=None,
              reason=None, action=None, schedule_conflict=False):
    saved = row or template
    kickoff = template["kickoff"] if checkpoint != "history" else saved["kickoff"]
    observed = snapshot["captured_at"] if snapshot else None
    if action is None:
        if snapshot and snapshot.get("snapshot_conflict"):
            action, reason = "EXCLUDED", "conflicting_same_time_snapshots"
        elif row and row.get("invalid_reason"):
            action, reason = "EXCLUDED", row["invalid_reason"]
        elif row and _selected(row, cohort):
            action, reason = "SELECT", "recorded_membership"
        else:
            action = "NO_ACTION"
            if reason is None:
                reason = ("missing_row_in_latest_snapshot" if row is None else
                          "real_offer_not_recorded_source_unknown" if row.get("line_from") not in ("dk", "sleeper")
                          or row.get("line") is None else
                          "observed_no_lean" if row.get("lean") is None else "not_recorded_top")
    clock = observed if row is not None else None
    lead = (utc(kickoff) - utc(clock)).total_seconds() if clock and kickoff else None
    record = {k: saved.get(k) for k in ("season", "week", "game_id", "player_id", "category", "team", "name",
                                       "raw_projection", "adjusted_projection", "line", "line_from")}
    if row is None:
        # A prior row identifies the opportunity, not its unobserved later offer.
        record.update(raw_projection=None, adjusted_projection=None, line=None, line_from=None)
    record.update(schema_version="selection-decision-v1", provenance_class="local_pregame_membership_observation",
                  model_version=snapshot["model"] if snapshot else template.get("_model", policy["model"]),
                  engine_sha256=snapshot["engine_sha256"] if snapshot else template["_engine"],
                  engine_files=snapshot["engine_files"] if snapshot else template["_engine_files"],
                  policy_version=policy["version"], policy_sha256=digest(policy), cohort=cohort,
                  checkpoint=checkpoint, checkpoint_at=stamp(boundary) if boundary else None,
                  kickoff=kickoff, observation_saved_kickoff=row.get("kickoff") if row else None,
                  schedule_conflict=schedule_conflict, action=action, reason=reason,
                  side=row.get("lean") if row else None,
                  top_over=row["top_over"] if row else None, top_under=row["top_under"] if row else None,
                  top_at_decision=bool(row and row.get("lean") in ("over", "under") and row["top_" + row["lean"]]),
                  recorded_selection_at=clock, original_selection_created_at=None,
                  selection_clock_basis="LOCAL_PREGAME_MEMBERSHIP_OBSERVATION" if clock else "UNKNOWN",
                  forecast_generated_at=snapshot["forecast_generated_at"] if snapshot else None,
                  collected_at=observed, selection_weekday=weekday(clock), kickoff_weekday=weekday(kickoff),
                  seconds_to_kickoff=lead, lead_time_bucket=_lead_bucket(lead, policy),
                  observation_age_seconds=(boundary - utc(observed)).total_seconds() if boundary and observed else None,
                  observation_receipt_sha256=snapshot["payload_sha256"] if snapshot else None,
                  observation_receipt_refs=snapshot.get("receipt_refs", []) if snapshot else [],
                  observation_row_sha256=row.get("observation_row_sha256") if row else None,
                  policy_application_mode="DESCRIPTIVE_FIRST_RECORDED_PER_COHORT" if checkpoint == "history" else
                                          "OFFLINE_DERIVED_FROM_ORIGINAL_PREGAME_OBSERVATIONS",
                  source_coverage="UNKNOWN_LEGACY_RESPONSE_STATUS", provider_quote_clock=None,
                  period=None, full_contract_verification="NOT_ESTABLISHED",
                  settlement_status="STATISTICAL_ONLY_NOT_VENUE_VERIFIED")
    record["decision_key"] = digest({k: record[k] for k in
                                    ("season", "week", "game_id", "player_id", "category", "model_version",
                                     "engine_sha256", "policy_sha256", "cohort", "checkpoint", "kickoff",
                                     "provenance_class")})
    record["decision_sha256"] = digest(record)
    return record


def build_decisions(receipts, policy, as_of, expected_hashes):
    as_of, registered = utc(as_of), utc(policy["registered_at"])
    snapshots, excluded = _snapshots(receipts, policy, as_of, expected_hashes)
    groups, observations = defaultdict(list), defaultdict(list)
    for snapshot in snapshots:
        groups[(snapshot["season"], snapshot["week"], snapshot["model"], snapshot["engine_sha256"])].append(snapshot)
        for key, row in snapshot["rows"].items():
            observations[key + (snapshot["model"], snapshot["engine_sha256"])].append((snapshot, row))
    records, universe, schedules = [], [], []
    for key, seen in sorted(observations.items()):
        first, original = seen[0]
        opportunity = key[:5]
        template = dict(original, _engine=first["engine_sha256"], _engine_files=first["engine_files"], _model=first["model"])
        kickoffs = {utc(row["kickoff"]) for _, row in seen}
        schedule_conflict = len(kickoffs) > 1
        if schedule_conflict:
            schedules.append({"opportunity": list(key), "saved_kickoffs": sorted(stamp(k) for k in kickoffs)})
        if opportunity in first["ambiguous_kickoff_keys"]:
            template["kickoff"] = None
            for cohort in policy["cohorts"]:
                for checkpoint in ("history", *(c["id"] for c in policy["checkpoints"])):
                    records.append(_decision(template, None, None, cohort, checkpoint, policy, action="EXCLUDED",
                                             reason="ambiguous_original_saved_kickoff", schedule_conflict=True))
            continue
        for cohort in policy["cohorts"]:
            selected = [(s, r) for s, r in seen if not s["snapshot_conflict"] and _selected(r, cohort)]
            chosen, row = selected[0] if selected else seen[0]
            history_conflict = len({utc(r["kickoff"]) for s, r in seen
                                    if utc(s["captured_at"]) <= utc(chosen["captured_at"])}) > 1
            records.append(_decision(template, chosen, row, cohort, "history", policy,
                                     schedule_conflict=history_conflict))
        for rule in policy["checkpoints"]:
            boundary = utc(original["kickoff"]) - timedelta(seconds=rule["seconds_before_kickoff"])
            for cohort in policy["cohorts"]:
                if boundary > as_of:
                    records.append(_decision(template, None, None, cohort, rule["id"], policy, boundary=boundary,
                                             action="NOT_DUE", reason="checkpoint_not_yet_reached",
                                             schedule_conflict=schedule_conflict))
                    continue
                # No opportunity is invented from a later first observation.
                if not any(utc(s["captured_at"]) <= boundary for s, _ in seen):
                    universe.append({"opportunity": list(key), "checkpoint": rule["id"],
                                     "reason": "not_in_observed_universe_before_boundary"})
                    continue
                eligible = [s for s in groups[key[:2] + key[5:]] if registered < utc(s["captured_at"]) <= boundary]
                known_conflict = len({utc(r["kickoff"]) for s, r in seen
                                      if utc(s["captured_at"]) <= boundary}) > 1
                chosen = eligible[-1] if eligible else None
                row = chosen["rows"].get(opportunity) if chosen else None
                action = reason = None
                if boundary <= registered:
                    action, reason = "EXCLUDED", "checkpoint_not_after_registration"
                    chosen, row = None, None
                elif chosen is None:
                    reason = "missing_registered_snapshot"
                elif (boundary - utc(chosen["captured_at"])).total_seconds() > policy["maximum_snapshot_age_seconds"]:
                    reason, row = "stale_snapshot", None
                elif row and utc(row["kickoff"]) != utc(original["kickoff"]):
                    action, reason = "EXCLUDED", "saved_schedule_conflict"
                records.append(_decision(template, chosen, row, cohort, rule["id"], policy, boundary=boundary,
                                         action=action, reason=reason, schedule_conflict=known_conflict))
    return records, {"valid_snapshot_instants": len(snapshots), "unique_observed_opportunities": len(observations),
                     "receipt_exclusions": excluded, "unobserved_checkpoint_opportunities": universe,
                     "schedule_conflicts": schedules,
                     "universe_scope": "OBSERVED_UNION_ONLY_ENTIRELY_UNOBSERVED_UNIVERSE_UNKNOWN"}


def archive_decisions(archives, policy):
    """Readable inherited/unclocked history stays separate from local captures."""
    records, seen = [], set()
    for archive in sorted(archives, key=digest):
        sha = digest(archive)
        if sha in seen:
            continue
        seen.add(sha)
        def unique(items, key, label):
            values = {}
            for item in items:
                ident = key(item)
                if ident in values:
                    raise IntegrityError("Duplicate/conflicting archive " + label)
                values[ident] = item
            return values
        games = unique(archive.get("games", []), lambda g: g["id"], "game identity")
        players = unique(archive["players"], lambda p: p["id"], "player identity")
        picks = {}
        for side, members in archive["picks"].items():
            for pick in members:
                key = (pick["player_id"], pick["key"], side)
                who = players.get(pick["player_id"])
                if (key in picks or who is None or pick.get("game_id") != who.get("game_id")
                        or pick.get("game_id") not in games):
                    raise IntegrityError("Ambiguous/unbound archive Top contract")
                picks[key] = pick
        for player in players.values():
            if player.get("late"):
                continue
            game = games.get(player["game_id"])
            if game is None:
                raise IntegrityError("Archive player lacks recorded game")
            props = unique(player.get("props", []), lambda p: p["key"], "prop contract")
            # A recorded Top selection missing its corresponding player prop is
            # an integrity error, not an opportunity silently dropped from n.
            if any(pid == player["id"] and category not in props
                   for pid, category, _ in picks):
                raise IntegrityError("Archive Top lacks corresponding recorded prop")
            for prop in props.values():
                if prop["key"] not in policy["categories"]:
                    continue
                side = prop.get("lean")
                row = {"season": archive["season"], "week": archive["week"], "game_id": player["game_id"],
                       "player_id": player["id"], "team": player["team"], "name": player.get("name"),
                       "category": prop["key"], "kickoff": game["kickoff"], "line": prop.get("line"),
                       "line_from": prop.get("line_from"), "lean": side, "raw_projection": prop.get("proj"),
                       "adjusted_projection": prop.get("adj"), "top_over": False, "top_under": False}
                for direction in ("over", "under"):
                    pick = picks.get((player["id"], prop["key"], direction))
                    if pick and pick.get("line") == prop.get("line") and pick.get("line_from") == prop.get("line_from"):
                        row["top_" + direction] = True
                for cohort in policy["cohorts"]:
                    saved = dict(row)
                    if cohort == "top_picks":
                        selected = [(d, picks[(player["id"], prop["key"], d)]) for d in ("over", "under")
                                    if (player["id"], prop["key"], d) in picks]
                        if len(selected) > 1:
                            raise IntegrityError("Conflicting archive Top selections")
                        if selected:
                            direction, pick = selected[0]
                            saved.update(line=pick.get("line"), line_from=pick.get("line_from"), lean=direction,
                                         raw_projection=pick.get("proj"), adjusted_projection=pick.get("adj"))
                            saved["top_" + direction] = True
                    template = dict(saved, _engine=None, _engine_files=None)
                    item = _decision(template, None, saved, cohort, "history", policy)
                    item.update(provenance_class="inherited_or_unclocked_archive", model_version="archive_engine_unverified",
                                engine_sha256=None, engine_files=None, archive_payload_sha256=sha,
                                archive_saved_at=archive.get("saved_at"), selection_clock_basis="UNKNOWN_ARCHIVE_CLOCK",
                                observation_receipt_sha256=sha, observation_row_sha256=digest(saved),
                                policy_application_mode="UNCLOCKED_ARCHIVED_MEMBERSHIP_NOT_CHECKPOINT_EVIDENCE")
                    # _decision uses row membership, but no clock is fabricated.
                    item["decision_key"] = digest({"archive": sha, "opportunity": list(identity(saved)), "cohort": cohort})
                    item.pop("decision_sha256")
                    item["decision_sha256"] = digest(item)
                    records.append(item)
    # Different archive versions are not extra independent decisions. Without
    # original clocks we cannot select a favorable version or infer chronology.
    by_opportunity = defaultdict(list)
    for record in records:
        by_opportunity[(identity(record), record["cohort"])].append(record)
    reconciled = []
    ignored = {"archive_payload_sha256", "archive_saved_at", "observation_receipt_sha256",
               "decision_key", "decision_sha256"}
    for (key, cohort), alternatives in sorted(by_opportunity.items()):
        signatures = {digest({k: v for k, v in row.items() if k not in ignored}) for row in alternatives}
        row = dict(alternatives[0])
        row["archive_receipt_refs"] = sorted({r["archive_payload_sha256"] for r in alternatives})
        row["archive_saved_at_clocks"] = sorted({r["archive_saved_at"] for r in alternatives if r["archive_saved_at"]})
        if len(signatures) > 1:
            row.update(action="EXCLUDED", reason="conflicting_unclocked_archive_versions")
        row["decision_key"] = digest({"unclocked_archive_opportunity": list(key), "cohort": cohort})
        row.pop("decision_sha256")
        row["decision_sha256"] = digest(row)
        reconciled.append(row)
    return reconciled


def final_outcome_records(outcomes):
    """Minimal derived outcome interface; never copy cache entries or paths."""
    fields = ("season", "week", "game_id", "player_id", "category", "team", "kickoff", "status", "actual", "reason",
              "game_state", "final_confirmed", "collected_at", "outcome_snapshot_sha256", "outcome_selection",
              "outcome_conflict", "outcome_identity_status", "outcome_identity_reasons", "outcome_source_mix",
              "outcome_revision", "selected_outcome_provenance_sha256")
    records = []
    for _, outcome in sorted(outcomes.items()):
        row = {key: outcome.get(key) for key in fields}
        row["final_confirmed"] = outcome.get("final_confirmed") is True
        row["outcome_conflict"] = outcome.get("outcome_conflict") is True
        selected = outcome.get("selected_outcome_provenance") or {}
        row.update(selected_outcome_row_sha256=selected.get("outcome_row_sha256"),
                   outcome_provenance=outcome_provenance(outcome))
        records.append(row)
    return records


def grade_decisions(records, outcomes):
    rows = []
    for decision in records:
        row = dict(decision)
        outcome = outcomes.get(identity(row))
        binding = None
        if row["action"] == "SELECT":
            outcome, binding = bind_outcome(row, outcome, key=identity(row))
        status, reason, actual = "pending", "no_saved_final_outcome", None
        if row["action"] != "SELECT":
            status = {"NO_ACTION": "no_action", "NOT_DUE": "not_due", "EXCLUDED": "excluded"}[row["action"]]
            reason = row["reason"]
        elif outcome:
            status, reason = outcome["status"], outcome.get("reason")
            if binding["status"] in ("identity_mismatch", "schedule_changed"):
                status, reason = "unresolved", outcome["reason"]
            elif outcome.get("outcome_conflict"):
                status, reason = "unresolved", "conflicting_confirmed_outcomes"
            elif status == "resolved":
                actual = outcome["actual"]
                status = {"hit": "win", "miss": "loss", "push": "push"}[grade.result(row["side"], actual, row["line"])]
            elif status == "void":
                status, reason = "unresolved", "venue_void_settlement_not_supported"
        row.update(result=status, outcome_reason=reason, actual=actual,
                   outcome_snapshot_sha256=outcome.get("outcome_snapshot_sha256") if outcome else None,
                   outcome_observations=[digest(observation) for observation in
                                         outcome.get("outcome_observations", [])] if outcome else [],
                   outcome_collected_at=outcome.get("collected_at") if outcome else None,
                   week_confirmed_complete=bool(outcome and outcome.get("week_confirmed_complete")),
                   outcome_provenance=outcome_provenance(outcome),
                   selected_outcome_provenance_sha256=outcome.get("selected_outcome_provenance_sha256") if outcome else None,
                   selected_outcome_row_sha256=(outcome.get("selected_outcome_provenance") or {}).get("outcome_row_sha256") if outcome else None,
                   outcome_selection=outcome.get("outcome_selection") if outcome else None,
                   outcome_conflict=bool(outcome and outcome.get("outcome_conflict")),
                   outcome_source_mix=outcome.get("outcome_source_mix") if outcome else None,
                   outcome_revision=bool(outcome and outcome.get("outcome_revision")),
                   outcome_identity_status=outcome.get("outcome_identity_status") if outcome else None,
                   outcome_identity_reasons=outcome.get("outcome_identity_reasons", []) if outcome else [])
        rows.append(row)
    return rows


def _tally(rows):
    counts = Counter(row["result"] for row in rows)
    if set(counts) - set(RESULTS):
        raise IntegrityError("Unknown report outcome")
    decided = counts["win"] + counts["loss"]
    selected_rows = [r for r in rows if r["action"] == "SELECT"]
    decided_rows = [r for r in rows if r["result"] in ("win", "loss")]
    return {**{k: counts[k] for k in RESULTS}, "rows": len(rows), "selected": sum(r["action"] == "SELECT" for r in rows),
            "decided": decided, "hit_rate": counts["win"] / decided if decided else None,
            "unique_players": len({r["player_id"] for r in rows}),
            "unique_games": len({(r["season"], r["game_id"]) for r in rows}),
            "unique_weeks": len({(r["season"], r["week"]) for r in rows}),
            "selected_unique_players": len({r["player_id"] for r in selected_rows}),
            "selected_unique_games": len({(r["season"], r["game_id"]) for r in selected_rows}),
            "decided_unique_players": len({r["player_id"] for r in decided_rows}),
            "decided_unique_games": len({(r["season"], r["game_id"]) for r in decided_rows}),
            "decided_unique_weeks": len({(r["season"], r["week"]) for r in decided_rows}),
            "row_ids": [r["decision_sha256"] for r in rows]}


def summarize(rows, *, contract=VERSION):
    if contract not in (VERSION, LEGACY_VERSION):
        raise IntegrityError("Unsupported selection-summary contract")
    context = ("provenance_class", "model_version", "engine_sha256")
    if contract == VERSION:
        context += ("policy_version", "policy_sha256")
    context += ("view", "checkpoint")
    if contract == VERSION:
        context += ("line_source_scope",)
    groups = defaultdict(list)
    dimensions = ("category", "side", "venue", "selection_weekday", "kickoff_weekday", "lead_time_bucket",
                  "checkpoint", "selection_clock_basis", "category_side")
    for row in rows:
        views = [row["cohort"]]
        if row["cohort"] == "all_qualifying_leans" and row["action"] == "SELECT":
            views.append("top_at_all_lean_decision" if row["top_at_decision"] else "non_top_at_all_lean_decision")
        for view in views:
            for period in ("cumulative", f"{row['season']}-w{row['week']:02d}"):
                # The exact-source tables are joint decision populations, never
                # reconstructed from marginal category or venue counts.
                scopes = ("all",) if contract == LEGACY_VERSION else ("all", row.get("line_from") or "unknown")
                for source in scopes:
                    values = dict(row, view=view, line_source_scope=source)
                    base = tuple(values.get(key) for key in context)
                    groups[(base, period, "overall", "all")].append(row)
                    scoped_dimensions = dimensions if source == "all" else ("category", "category_side")
                    for dimension in scoped_dimensions:
                        value = (row["line_from"] if dimension == "venue" else
                                 f"{row['category']}:{row['side']}" if dimension == "category_side" else row.get(dimension))
                        groups[(base, period, dimension, value)].append(row)
    tables = []
    for (base, period, dimension, value), members in sorted(groups.items(), key=lambda item: repr(item[0])):
        table = dict(zip(context, base))
        table.update(period=period, dimension=dimension, value=value, **_tally(members))
        table["summary_id"] = digest({k: v for k, v in table.items() if k != "row_ids"})
        assert sum(table[k] for k in RESULTS) == table["rows"]
        tables.append(table)
    # Check the disjoint SELECT partition, independently of overlapping cohorts.
    partitions = defaultdict(lambda: [set(), set(), set()])
    for row in rows:
        if row["cohort"] == "all_qualifying_leans" and row["action"] == "SELECT":
            key = (row["provenance_class"], row["model_version"], row["checkpoint"])
            partitions[key][0].add(row["decision_sha256"])
            partitions[key][1 if row["top_at_decision"] else 2].add(row["decision_sha256"])
    for whole, top, other in partitions.values():
        assert not top & other and whole == top | other
    return {"tables": tables, "disjoint_selected_partitions_reconciled": True,
            "warning": "Cohorts, checkpoint policies and dimensions overlap; never add them as independent samples."}


def matched_checkpoints(rows):
    by_key = defaultdict(dict)
    for row in rows:
        if row["checkpoint"] != "history" and row["action"] not in ("NOT_DUE", "EXCLUDED"):
            by_key[(row["cohort"], row["model_version"], row["engine_sha256"], identity(row))][row["checkpoint"]] = row
    matches = []
    for values in by_key.values():
        for left, right in itertools.combinations(sorted(values), 2):
            a, b = values[left], values[right]
            selected = a["action"] == b["action"] == "SELECT"
            matches.append({"left_row": a["decision_sha256"], "right_row": b["decision_sha256"],
                            "left_checkpoint": left, "right_checkpoint": right,
                            "common_observed_opportunity": True, "both_selected": selected,
                            "same_venue": a["line_from"] == b["line_from"] and a["line_from"] in ("dk", "sleeper"),
                            "matched_selected": selected and a["line_from"] == b["line_from"],
                            "left_line": a["line"], "right_line": b["line"], "left_side": a["side"], "right_side": b["side"],
                            "line_changed": selected and a["line"] != b["line"],
                            "direction_flipped": selected and a["side"] != b["side"]})
    return matches


def _input_pin(root, pins):
    if pins and str(root) in pins:
        return pins[str(root)]
    if (root / ".git").exists():
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    return None


def _inventory(roots, input_pins=None):
    manifest, data = [], {"forward": [], "outcomes": [], "offers": [], "archives": []}
    visited = set()
    for root in roots:
        pin = _input_pin(root, input_pins)
        blobs = {}
        if pin and (root / ".git").exists():
            tree = subprocess.check_output(["git", "-C", str(root), "ls-tree", "-r", pin], text=True)
            blobs = {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2]
                     for line in tree.splitlines()}
        for pattern in PATTERNS:
            for path in sorted(root.glob(pattern)):
                if path.resolve() in visited:
                    continue
                visited.add(path.resolve())
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise IntegrityError("Input evidence path escapes its root")
                raw = path.read_bytes()
                value = read(path) if path.suffix == ".gz" else load_json(path)
                name = path.relative_to(root).as_posix()
                blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                if name in blobs and blobs[name] != blob_sha:
                    raise IntegrityError("Input bytes differ from their declared Git pin")
                if name.startswith("data/forward/") and value.get("schema_version") == "baseline-capture-v1":
                    capture_id = digest({"data": value["input_sha256"], "engine": value["engine_sha256"],
                                         "mode": value["mode"]})
                    if path.name != capture_id + ".json.gz":
                        raise IntegrityError("Baseline capture filename identity mismatch")
                elif name.startswith(("data/outcomes/", "data/offers/")) and path.name != digest(value) + ".json.gz":
                    raise IntegrityError("Saved evidence filename identity mismatch")
                manifest.append({"root": str(root), "path": name, "bytes": len(raw),
                                 "sha256": hashlib.sha256(raw).hexdigest(), "payload_sha256": digest(value),
                                 "input_git_pin": pin, "git_blob_sha": blob_sha,
                                 "pin_binding": "LOCAL_GIT_BLOB_VERIFIED" if name in blobs else
                                                "EXTERNAL_PIN_REFERENCE_ONLY" if pin else "CONTENT_ADDRESSED_UNPINNED"})
                for prefix, lane in (("data/forward/", "forward"), ("data/outcomes/", "outcomes"),
                                     ("data/offers/", "offers"), ("output/data/archive/", "archives")):
                    if name.startswith(prefix):
                        data[lane].append(value)
    return manifest, data


def _original_boards(paths, roots, pins):
    """Explicit read-only documents, never provider refetches or historical replay."""
    records, manifest, visited = [], [], set()
    for supplied in sorted(paths, key=str):
        path = Path(supplied).absolute()
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise IntegrityError("Original board symlink refused")
        path = path.resolve()
        if path in visited:
            continue
        visited.add(path)
        if not path.is_file():
            raise IntegrityError("Original board must be an existing JSON file")
        raw, board = path.read_bytes(), load_json(path)
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        pin = None
        for root in roots:
            if path.is_relative_to(root) and (root / ".git").exists():
                pin = _input_pin(root, pins)
                expected = subprocess.check_output(["git", "-C", str(root), "rev-parse",
                                                     f"{pin}:{path.relative_to(root).as_posix()}"], text=True).strip()
                if expected != blob:
                    raise IntegrityError("Original board differs from declared Git pin")
                break
        item = {"root": str(path.parent), "path": path.name, "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(), "payload_sha256": digest(board),
                "git_blob_sha": blob, "input_git_pin": pin,
                "pin_binding": "LOCAL_GIT_BLOB_VERIFIED" if pin else "EXACT_DOCUMENT_HASH_BINDING_REQUIRED",
                "record_type": "optional_original_forecast_board"}
        manifest.append(item)
        records.append({"document": board, "document_sha256": digest(board),
                        "file_sha256": item["sha256"], "git_blob_sha1": blob,
                        **({"git_commit": pin} if pin else {})})
    return records, manifest


def _descriptive_report(roots, output, inputs, outcomes, expected_hashes, now, pins, boards, *, model_version="original_sleeper_matchup_baseline"):
    modern = model_version == corrected.MODEL
    contract = descriptive_contract(presence_aware=modern)
    first, pairs, coverage = descriptive_forecasts(inputs["forward"], corrected.V2_SOURCE_SHA256 if modern else expected_hashes,
                                                  now, model_version=model_version)
    extra = {key: row for key, row in first.items() if row["category"] in EXTRA_CATEGORIES}
    sink = output / "descriptive-evaluation"
    for root in roots:
        if (root / "output/data/week.json").exists():
            snapshot_outcomes(root, extra, now, output_root=sink,
                derived_context={"statistic_contract": contract["version"],
                                 "scope": "saved_input_bytes_only_not_provider_observation",
                                 "input_git_pin": _input_pin(root, pins)},
                include_populations=False, statistic_contract=contract)
    saved, unsupported = [], []
    for payload in inputs["outcomes"] + [read(path) for path in (sink / "data/outcomes_derived").rglob("*.json.gz")]:
        if payload.get("schema_version") in ("forecast-outcomes-v1", corrected.OUTCOMES):
            # Existing ten-category evidence is consumed through the unchanged
            # map. Old unsupported fpts/TD rows are not silently reinterpreted.
            if any(row.get("category") in EXTRA_CATEGORIES for row in payload.get("rows", [])):
                unsupported.append({"payload_sha256": digest(payload), "reason": "unsupported_legacy_extra_statistic"})
            continue
        if (payload.get("schema_version") not in (DERIVED_STAT_SCHEMA, corrected.DESCRIPTIVE_OUTCOMES) or
                not isinstance(payload.get("statistic_contract"), dict) or
                payload["statistic_contract"].get("version") not in (descriptive_contract()["version"],
                                                                       descriptive_contract(presence_aware=True)["version"])):
            unsupported.append({"payload_sha256": digest(payload), "reason": "unsupported_descriptive_outcome_contract"})
            continue
        if utc(payload["collected_at"]) > now:
            raise IntegrityError("Saved descriptive outcome is in the future")
        saved.append(payload)
    result = evaluate_descriptive(first, pairs, outcomes, latest_outcomes(saved), original_boards=boards, model_version=model_version)
    result.update(capture_coverage=coverage, unsupported_outcome_receipts=unsupported)
    return result


def _descriptive_html(report, prefix):
    value = report.get("descriptive_all_categories")
    if value is None:
        return ""
    rows = []
    for category, item in value["categories"].items():
        pair = item["paired"]
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in
            (category, item["coverage"]["opportunities"], item["paired_coverage"]["opportunities"],
             pair["raw"]["n"], pair["raw"]["mae"], pair["adjusted"]["mae"],
             pair["raw"]["rmse"], pair["adjusted"]["rmse"],
             pair["raw"]["bias"], pair["adjusted"]["bias"], pair["helps"], pair["hurts"], pair["ties"])) + "</tr>")
    td = value["categories"]["anytime_td"]["probability"]
    return ('<h2>All-category descriptive forecast evaluation</h2>'
            '<p>Separate from the registered three-target experiment. Units are category-specific. '
            'PPR raw below is component-derived; direct provider PPR is a distinct comparator in the JSON. '
            'Repeated captures and categories are not independent games.</p><div class="scroll"><table><thead><tr>' +
            "".join(f"<th>{name}</th>" for name in ("Category", "Saved", "Pairs", "Resolved pairs", "Raw MAE", "Adjusted MAE",
                "Raw RMSE", "Adjusted RMSE", "Raw bias", "Adjusted bias", "Helps", "Hurts", "Ties")) +
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>' +
            f'<p>Anytime rushing/receiving TD: {td["n"]} resolved; {td["events"]} events; Brier {td["brier"]}; '
            f'log loss {td["log_loss"]} ({td["log_loss_state"]}). Saved versus re-derived probability provenance, '
            'fixed calibration bins, coverage and complete rows are separate in '
            f'<a href="{prefix}descriptive-evaluation.json">evaluation JSON</a>; '
            f'<a href="{prefix}descriptive-pairs.csv">paired CSV</a>, '
            f'<a href="{prefix}descriptive-forecasts.csv">all saved forecasts CSV</a>, '
            f'<a href="{prefix}descriptive-td.csv">TD CSV</a>.</p>')


def _frozen_decisions(output, records, at):
    previous, seen_history = {}, set()
    for path in sorted((output / "data/selection_decisions").rglob("*.json.gz")):
        payload = read(path)
        if (payload.get("schema_version") != "derived-selection-ledger-v1"
                or utc(payload["derived_at"]) > utc(at) or not isinstance(payload.get("rows"), list)):
            raise IntegrityError("Unsupported or future frozen decision ledger")
        for row in payload["rows"]:
            if (not isinstance(row, dict) or row.get("schema_version") != "selection-decision-v1"
                    or row.get("decision_sha256") != digest({k: v for k, v in row.items() if k != "decision_sha256"})):
                raise IntegrityError("Frozen decision content identity mismatch")
            if row["checkpoint"] == "history":
                seen_history.add(row["decision_sha256"])
                continue
            old = previous.setdefault(row["decision_key"], row)
            if old != row:
                raise IntegrityError("Conflicting frozen decision ledger")
    stable, conflicts = [], []
    current_keys = {record["decision_key"] for record in records}
    for record in records:
        old = previous.get(record["decision_key"]) if record["checkpoint"] != "history" else None
        if old and old != record and record["action"] != "NOT_DUE":
            conflicts.append({"decision_key": record["decision_key"], "frozen": old["decision_sha256"],
                              "proposed": record["decision_sha256"]})
            record = dict(old, action="EXCLUDED", reason="conflict_with_frozen_derived_decision")
            record["frozen_decision_sha256"] = old["decision_sha256"]
            record.pop("decision_sha256")
            record["decision_sha256"] = digest(record)
        stable.append(record)
    # Prior frozen decisions are observations in their own right. A later
    # partial input root cannot silently erase them from the public report.
    stable.extend(row for key, row in sorted(previous.items()) if key not in current_keys)
    by_week = defaultdict(list)
    for row in stable:
        if (row["action"] in ("SELECT", "NO_ACTION") and row["decision_key"] not in previous
                and row["decision_sha256"] not in seen_history):
            by_week[(row["season"], row["week"])].append(row)
    for (season, week), members in by_week.items():
        write(output, "selection_decisions", {"schema_version": "derived-selection-ledger-v1", "season": season,
                                             "week": week, "derived_at": stamp(at), "rows": members})
    return stable, conflicts


def _create_file(path, content):
    raw = content.encode("utf-8") if isinstance(content, str) else content
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise IntegrityError("Refusing symlink output")
    if path.exists():
        if path.read_bytes() != raw:
            raise IntegrityError("Derived output conflict")
    else:
        with path.open("xb") as handle:
            handle.write(raw)


def render_html(report, group=None):
    escape = lambda value: html.escape(str(value)) if value is not None else "unknown"
    summary = []
    tables = [group] if group else report["summary"]["tables"]
    for table in tables:
        label = " / ".join(str(table[k]) for k in ("period", "provenance_class", "view", "checkpoint",
                                                   "dimension", "value"))
        links = (f'<a data-summary-id="{table["summary_id"]}" href="groups/{table["summary_id"]}.html">'
                 f'Inspect all {table["rows"]} underlying rows</a>' if group is None else
                 '<a href="../index.html">Back to every summary</a>')
        rate = f'{100 * table["hit_rate"]:.1f}%' if table["hit_rate"] is not None else "unavailable"
        summary.append(f'<details><summary>{escape(label)}: {table["win"]}W {table["loss"]}L; {rate}; '
                       f'{table["selected"]} selected / {table["rows"]} observed rows; '
                       f'{table["decided_unique_games"]} decided games / {table["decided_unique_weeks"]} weeks</summary>'
                       f'<pre>{escape(json.dumps({k: table[k] for k in RESULTS}))}</pre>{links}</details>')
    body = []
    fields = ("week", "name", "category", "cohort", "checkpoint", "line_from", "line", "side",
              "recorded_selection_at", "selection_weekday", "kickoff_weekday", "observation_age_seconds",
              "action", "result", "actual", "outcome_reason")
    if group:
        refs = set(group["row_ids"])
        displayed = [row for row in report["rows"] if row["decision_sha256"] in refs]
    else:
        displayed = sorted(report["rows"], key=lambda r: (r["action"] != "SELECT", r["checkpoint"] != "history",
                                                          r["provenance_class"] != "local_pregame_membership_observation"))[:50]
    for row in displayed:
        body.append(f'<tr id="row-{escape(row["decision_sha256"])}">' +
                    "".join(f"<td>{escape(row.get(k))}</td>" for k in fields) + "</tr>")
    prefix = "../" if group else ""
    preview = (f'<p>Preview: {len(displayed)} of {len(report["rows"])} decision/coverage rows; '
               'use each summary’s drill-down for its complete population.</p>' if not group else
               f'<p>Complete drill-down: {len(displayed)} rows, exactly the summary population.</p>')
    anchor = f'<a href="#row-{displayed[0]["decision_sha256"]}">Jump to rows</a>' if displayed else ""
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>Nick’s NFL selection grading — local descriptive report</title>'
            '<style>body{font:16px system-ui;margin:1.2rem;max-width:100%}details{margin:.7rem 0}'
            '.scroll{overflow:auto}table{border-collapse:collapse;font-size:13px}td,th{padding:.5rem;'
            'border:1px solid #bbb;white-space:nowrap}a{margin:.2rem}:target{background:#fff2ab}'
            'pre,summary{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
            '<h1>Nick’s NFL selection grading</h1><p>Offline descriptive report. Not deployed; '
            'not venue settlement, profitability or confirmed predictive improvement.</p>'
            '<p>Top Picks overlap all leans. Disjoint views refer to Top membership at that all-lean decision. '
            'Historical archives lack original clocks. Local observation clocks do not prove publication.</p>'
            '<p>Whole-week uncertainty and confirmation unavailable. Original Week 6 matchup proof is missing; '
            'independent original-capture evidence review remains pending.</p>'
            '<p>All category/side/day/timing/venue tables and full provenance: '
            f'<a href="{prefix}summary.json">summary JSON</a>, <a href="{prefix}rows.json">auditable rows JSON</a>, '
            f'<a href="{prefix}rows.csv">CSV</a>, <a href="{prefix}manifest.json">input/code/policy manifest</a>.</p>' +
            _descriptive_html(report, prefix) + "".join(summary) + '<h2>Auditable rows</h2>' + preview + anchor + '<div class="scroll"><table><thead><tr>' +
            "".join(f"<th>{escape(k)}</th>" for k in fields) + "</tr></thead><tbody>" +
            "".join(body) + "</tbody></table></div></html>")


def run_report(input_roots, output_root, *, now=None, expected_hashes=None, policy=None, input_pins=None,
               include_descriptive=False, original_board_paths=(), report_version=VERSION,
               descriptive_model="original_sleeper_matchup_baseline"):
    if report_version not in (VERSION, LEGACY_VERSION):
        raise IntegrityError("Unsupported selection-report contract")
    now = utc(now or datetime.now(timezone.utc))
    roots = sorted({Path(root).resolve() for root in input_roots})
    output = Path(output_root).resolve()
    if not roots or any(not root.is_dir() for root in roots):
        raise IntegrityError("Existing read-only input roots required")
    if output.is_relative_to(ROOT) or any(output.is_relative_to(root) or root.is_relative_to(output) for root in roots):
        raise IntegrityError("Output must be outside source and input roots")
    policy = policy or load_json(ROOT / "config/timing-policy.json")
    expected_hashes = expected_hashes or corrected.legacy_engine_hashes()
    manifest, inputs = _inventory(roots, input_pins)
    if original_board_paths and not include_descriptive:
        raise IntegrityError("Original boards require explicit all-category evaluation")
    boards, board_manifest = _original_boards(original_board_paths, roots, input_pins) if include_descriptive else ([], [])
    manifest.extend(board_manifest)
    decisions, coverage = build_decisions(inputs["forward"], policy, now, expected_hashes)
    decisions.extend(archive_decisions(inputs["archives"], policy))
    # Unknown schemas are inventoried, not silently upgraded to qualified data.
    saved, unsupported = [], []
    for payload in inputs["outcomes"]:
        if payload.get("schema_version") not in ("forecast-outcomes-v1", corrected.OUTCOMES):
            unsupported.append(digest(payload))
        elif utc(payload["collected_at"]) <= now:
            saved.append(payload)
        else:
            raise IntegrityError("Saved outcome observation is in the future")
    all_opportunities = {}
    for row in decisions:
        all_opportunities.setdefault(identity(row), row)
    derived = []
    for root in roots:
        if not (root / "output/data/week.json").exists():
            continue
        paths = snapshot_outcomes(root, all_opportunities, now, output_root=output,
                                  derived_context={"statistic_contract": "ten-pickable-source-stats-v1",
                                                   "scope": "saved_input_bytes_only_not_provider_observation",
                                                   "input_git_pin": _input_pin(root, input_pins)},
                                  include_populations=False)
        derived.extend(read(path) for path in paths)
    # Include previously derived observations so conflicts/revisions remain visible.
    derived.extend(read(path) for path in (output / "data/outcomes_derived").rglob("*.json.gz"))
    outcomes = latest_outcomes(saved + derived)
    decisions, conflicts = _frozen_decisions(output, decisions, now)
    rows = grade_decisions(decisions, outcomes)
    summary = summarize(rows, contract=report_version)
    sources = []
    for payload in {digest(p): p for p in inputs["offers"]}.values():
        sources.append({"receipt_sha256": digest(payload), "schema_version": payload.get("schema_version"),
                        "source_status": payload.get("source_status", "unknown"),
                        "collected_at": payload.get("collected_at"), "coverage": payload.get("coverage"),
                        "bound_to_decisions": False, "limitation": "No exact observation/contract join inferred."})
    primary_policy = load_json(ROOT / "config/evaluation-policy.json")
    unique_forecasts = {digest(p): p for p in inputs["forward"]}
    pairs, paired_coverage = paired_forecasts([p for p in unique_forecasts.values()
                                              if p.get("schema_version") == "baseline-capture-v1"
                                              and p.get("model") == primary_policy["baseline"]
                                              and p.get("engine_files") == expected_hashes
                                              and utc(p["captured_at"]) <= now],
                                             primary_policy, expected_hashes)
    primary = score(pairs, outcomes, paired_coverage, primary_policy)
    coverage.update(source_observations=sources, unsupported_outcome_receipts=unsupported,
                    frozen_decision_conflicts=conflicts,
                    original_archive_count=len({digest(a) for a in inputs["archives"]}),
                    weeks_with_decided_selections=len({(r["season"], r["week"]) for r in rows
                                                       if r["result"] in ("win", "loss")}),
                    independently_qualified_completed_weeks=sorted({(r["season"], r["week"]) for r in rows
                                                                   if r["week_confirmed_complete"]}))
    code = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in
            (Path(__file__), ROOT / "tools/scorecard.py", ROOT / "pull/grade.py")}
    report = {"schema_version": report_version, "rows": rows, "summary": summary, "coverage": coverage,
              "final_outcomes": final_outcome_records(outcomes),
              "outcome_observation_index": {digest(observation): observation for outcome in outcomes.values()
                                            for observation in outcome.get("outcome_observations", [])},
              "matched_checkpoints": matched_checkpoints(rows),
              "primary_raw_vs_adjusted": primary, "uncertainty": {"status": "DESCRIPTIVE_ONLY_TIMING_INFERENCE_NOT_IMPLEMENTED",
              "interval": None, "minimum_completed_weeks": policy["uncertainty"]["minimum_completed_weeks"],
              "confirmed_findings": []},
              "limitations": ["Original Week 6 matchup-proof/input evidence missing; not reconstructed.",
                              "Original captured-population independent evidence review pending.",
                              "Provider/quote freshness, full contract and venue settlement unverified.",
                              "Inherited/unclocked history, offline checkpoint derivation and original captures are separate.",
                              "No model fitted/promoted; report derivation alone does not establish publication or deployment."],
              "input_manifest_sha256": digest(manifest), "code_sha256": code,
              "timing_policy_sha256": digest(policy), "evaluation_policy_sha256": digest(primary_policy)}
    if include_descriptive:
        report["descriptive_all_categories"] = _descriptive_report(roots, output, inputs, outcomes,
                                                                  expected_hashes, now, input_pins, boards, model_version=descriptive_model)
    # Outputs are content-addressed; operational clocks live in a separate run receipt.
    report_id = digest(report)
    directory = output / "reports" / report_id
    _create_file(directory / "rows.json", canonical(rows) + b"\n")
    _create_file(directory / "summary.json", canonical({k: v for k, v in report.items() if k != "rows"}) + b"\n")
    _create_file(directory / "manifest.json", canonical({"inputs": manifest, "code": code, "policy": policy}) + b"\n")
    columns = sorted({key for row in rows for key in row})
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    _create_file(directory / "rows.csv", stream.getvalue())
    if include_descriptive:
        value = report["descriptive_all_categories"]
        _create_file(directory / "descriptive-evaluation.json", canonical(value) + b"\n")
        for label, records in (("forecasts", value["rows"]), ("pairs", value["paired_rows"]), ("td", value["td_rows"])):
            columns = sorted({key for row in records for key in row})
            data = io.StringIO(newline="")
            writer = csv.DictWriter(data, fieldnames=columns)
            writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()} for row in records)
            _create_file(directory / f"descriptive-{label}.csv", data.getvalue())
    _create_file(directory / "index.html", render_html(report))
    for group in summary["tables"]:
        _create_file(directory / "groups" / (group["summary_id"] + ".html"), render_html(report, group))
    run = {"schema_version": "selection-report-run-v1", "season": 0, "week": 0,
           "generated_at": stamp(now), "report_sha256": report_id, "input_manifest_sha256": digest(manifest)}
    write(output, "selection_report_runs", run)
    # Verify every original byte again after the complete pipeline.
    for item in manifest:
        if hashlib.sha256((Path(item["root"]) / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise IntegrityError("Original input changed during report")
    return report, directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", action="append", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--input-pin", action="append", default=[], metavar="ROOT=GIT_SHA",
                        help="Optional frozen input reference; local Git blobs are verified when available.")
    parser.add_argument("--all-category-evaluation", action="store_true",
                        help="Opt-in local descriptive evaluation; primary/public-v1 behavior stays unchanged.")
    parser.add_argument("--descriptive-model", choices=("original_sleeper_matchup_baseline", corrected.MODEL),
                        default="original_sleeper_matchup_baseline",
                        help="Explicit local all-category model cohort; never pools original and corrected forecasts.")
    parser.add_argument("--original-board", action="append", type=Path, default=[],
                        help="Optional exact original full forecast JSON; never substitute a later board.")
    args = parser.parse_args()
    pins = {}
    for value in args.input_pin:
        name, separator, sha = value.rpartition("=")
        if not separator or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            parser.error("--input-pin requires ROOT=40-character Git SHA")
        pins[str(Path(name).resolve())] = sha
    report, directory = run_report(args.input_root, args.output_root, input_pins=pins,
                                  include_descriptive=args.all_category_evaluation,
                                  descriptive_model=args.descriptive_model,
                                  original_board_paths=args.original_board)
    print(json.dumps({"report": str(directory / "index.html"), "rows": len(report["rows"]),
                      "selected_decision_rows_overlapping": sum(r["action"] == "SELECT" for r in report["rows"]),
                      "status": "LOCAL_DESCRIPTIVE_ONLY_NOT_DEPLOYED"}))


if __name__ == "__main__":
    main()
