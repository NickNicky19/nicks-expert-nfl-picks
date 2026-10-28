"""Fictional offline research evidence; assertions do not prove better forecasts."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
import data_integrity_v2 as corrected

import point_challenger as challenger
from evidence import read
from reliability import digest, engine_hashes, make_payload, stamp
from scorecard import identity, snapshot_outcomes
from test_reliability import fixture


FREEZE = datetime(2026, 10, 16, 19, 25, 29, tzinfo=timezone.utc)
CAPTURE = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
START = CAPTURE + timedelta(minutes=1)
FINISH = START + timedelta(seconds=1)
KICKOFF = datetime(2026, 10, 23, 0, 15, tzinfo=timezone.utc)
FINAL = KICKOFF + timedelta(hours=5)
ENGINE = corrected.legacy_engine_hashes(ROOT)
COMMIT = "a" * 40


def baseline(*, captured=CAPTURE, kickoff=KICKOFF, week=7, raw=2.0, adjusted=4.0,
             player="fictional-1", game="fictional-game", no_lean=False):
    data, _ = fixture()
    data.update(week=week, generated_at=stamp(captured - timedelta(minutes=1)))
    data["games"][0].update(id=game, kickoff=stamp(kickoff))
    data["players"][0].update(id=player, game_id=game)
    prop = data["players"][0]["props"][0]
    prop.update(proj=raw, adj=adjusted)
    data["picks"] = {"over": [], "under": []}
    if no_lean:
        prop.update(lean=None, line=None, line_from="ours")
    payload = make_payload(data, captured, ENGINE, "live")
    payload["code_commit"] = COMMIT
    return payload


def registration():
    with patch.object(challenger, "datetime") as clock:
        clock.now.return_value = FREEZE
        return challenger.make_registration(ENGINE, source_commit=COMMIT)


def candidate(receipt=None, registry=None, *, started=START, finished=FINISH, mode="prospective"):
    with patch.object(challenger, "datetime") as clock:
        clock.now.side_effect = [started, finished]
        return challenger.make_candidate(receipt or baseline(), registry or registration(),
                                         mode=mode, code_commit=COMMIT)


def saved_outcome(receipt=None, *, actual=3, status="resolved", collected=FINAL,
                  source="fictional_source_A", opponent="BBB"):
    row = copy.deepcopy((receipt or baseline())["rows"][0])
    entry = {"team": row["team"], "opp": opponent, "stats": {"gp": 1, "rec": actual}}
    if status == "dnp":
        entry = {"team": row["team"], "opp": opponent,
                 "participation_status": "dnp", "participation_source": "fictional_dnp"}
    elif status in ("pending", "unresolved"):
        entry = None
    row.update(status=status, actual=actual if status == "resolved" else None,
               game_state="pre" if status == "pending" else "post",
               final_confirmed=status != "pending", stats_entry=entry,
               week_confirmed_complete=False)
    return {"schema_version": "forecast-outcomes-v1", "mode": "live", "season": row["season"],
            "week": row["week"], "collected_at": stamp(collected), "source": source,
            "source_timestamp": None, "cache_path": "data/cache/fictional.json",
            "cache_sha256": digest({row["player_id"]: entry}),
            "game_snapshot_sha256": digest({"kickoff": row["kickoff"], "state": row["game_state"]}),
            "games": [{"id": row["game_id"], "kickoff": row["kickoff"], "home": "AAA", "away": "BBB",
                       "state": row["game_state"], "detail": "Scheduled" if status == "pending" else "Final"}],
            "rows": [row]}


class FixedPointTests(unittest.TestCase):
    def test_fixed_formula_changes_center(self):
        self.assertEqual(challenger.point(2, 4), 3)
        self.assertEqual(challenger.point(4, 2), 3)
        with self.assertRaises(TypeError):
            challenger.point(2, 4, weight=.9)

    def test_fractional_forecasts_are_preserved(self):
        self.assertEqual(challenger.point(.25, 1.0), .625)
        self.assertEqual(challenger.point(0, 0), 0)
        self.assertEqual(challenger.point(2.1, 2.1), 2.1)

    def test_invalid_values_cannot_become_a_forecast(self):
        for value in (None, True, "2", -1, float("nan"), float("inf")):
            for values in ((value, 2), (2, value)):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    challenger.point(*values)


class CandidateContractTests(unittest.TestCase):
    def setUp(self):
        retained = self.enterContext(corrected.legacy_source(ROOT))
        self.enterContext(patch.object(challenger, "ROOT", retained))
        self.baseline = baseline()
        self.registry = registration()

    def validate(self, value, receipt=None, registry=None, now=FINISH):
        return challenger.validate_candidate(value, receipt or self.baseline,
                                              registry or self.registry, now=now)

    def test_valid_same_receipt_fractional_candidate_preserves_inputs(self):
        before = copy.deepcopy(self.baseline)
        result = candidate(self.baseline, self.registry)
        self.validate(result)
        self.assertEqual(self.baseline, before)
        self.assertEqual(result["baseline_payload_sha256"], digest(self.baseline))
        self.assertEqual(result["rows"][0]["candidate_projection"], 3)
        self.assertEqual(result["rows"][0]["raw_projection"], 2)
        self.assertEqual(result["rows"][0]["adjusted_projection"], 4)

    def test_no_lean_and_reference_only_are_point_eligible(self):
        receipt = baseline(no_lean=True)
        result = candidate(receipt, self.registry)
        self.validate(result, receipt)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["candidate_projection"], 3)

    def test_unknown_baseline_schema_model_engine_and_digest_rejected(self):
        changes = [("schema_version", "unknown"), ("model", "replacement_model"),
                   ("engine_sha256", "0" * 64), ("input_sha256", "invalid"),
                   ("engine_files", {"other": "engine"})]
        for key, value in changes:
            receipt = copy.deepcopy(self.baseline)
            receipt[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                candidate(receipt, self.registry)

    def test_coherently_rehashed_foreign_engine_is_rejected_by_consumers(self):
        receipt = copy.deepcopy(self.baseline)
        registry = copy.deepcopy(self.registry)
        foreign = {"fixture": "different-engine"}
        registry.update(expected_engine_files=foreign, engine_sha256=digest(foreign))
        receipt.update(engine_files=foreign, engine_sha256=digest(foreign))
        with self.assertRaises(ValueError):
            candidate(receipt, registry)
        with self.assertRaises(ValueError):
            challenger.evaluate([], [receipt], [], registry, now=FINAL)

    def test_replay_is_not_original_live_capture(self):
        receipt = copy.deepcopy(self.baseline)
        receipt["mode"] = "replay"
        with self.assertRaises(ValueError):
            candidate(receipt, self.registry)

    def test_duplicate_opportunity_in_baseline_fails(self):
        receipt = copy.deepcopy(self.baseline)
        receipt["rows"].append(copy.deepcopy(receipt["rows"][0]))
        with self.assertRaises(ValueError):
            candidate(receipt, self.registry)

    def test_header_generation_after_capture_rejected(self):
        receipt = copy.deepcopy(self.baseline)
        receipt["forecast_generated_at"] = stamp(CAPTURE + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            candidate(receipt, self.registry)

    def test_source_observation_cannot_be_future_to_calculation(self):
        with self.assertRaises(ValueError):
            candidate(self.baseline, self.registry, started=CAPTURE - timedelta(seconds=1),
                      finished=CAPTURE)

    def test_naive_registration_clock_and_future_registration_rejected(self):
        bad = copy.deepcopy(self.registry)
        bad["registered_at"] = "2026-10-16T19:25:29"
        with self.assertRaises(ValueError):
            challenger.validate_registration(bad, ENGINE, now=FINISH)
        with self.assertRaises(ValueError):
            challenger.validate_registration(self.registry, ENGINE, now=FREEZE - timedelta(seconds=1))

    def test_registration_cannot_change_fixed_protocol(self):
        bad = copy.deepcopy(self.registry)
        bad["protocol"]["candidate_id"] = "tuned-candidate"
        bad["protocol_sha256"] = digest(bad["protocol"])
        with self.assertRaises(ValueError):
            challenger.validate_registration(bad, ENGINE, now=FINISH)

    def test_code_freeze_digest_and_order_are_enforced(self):
        for field, value in (("model_code_sha256", "0" * 64),
                             ("code_frozen_at", stamp(FREEZE + timedelta(seconds=1)))):
            bad = copy.deepcopy(self.registry)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                challenger.validate_registration(bad, ENGINE, now=FINISH)

    def test_invalid_identity_and_numeric_pair_fail_closed(self):
        for key, value in (("player_id", ""),
                           ("game_id", ""), ("team", ""), ("season", True),
                           ("raw_projection", -1), ("adjusted_projection", float("inf"))):
            receipt = copy.deepcopy(self.baseline)
            receipt["rows"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                candidate(receipt, self.registry)

    def test_other_categories_do_not_block_original_all_category_receipt(self):
        receipt = copy.deepcopy(self.baseline)
        non_reception = copy.deepcopy(receipt["rows"][0])
        non_reception.update(category="rush_yd", raw_projection=20, adjusted_projection=25)
        receipt["rows"].append(non_reception)
        result = candidate(receipt, self.registry)
        self.assertEqual([r["category"] for r in result["rows"]], ["rec"])

    def test_unknown_category_and_conflicting_optional_period_are_rejected(self):
        receipt = copy.deepcopy(self.baseline)
        receipt["rows"][0]["category"] = "unknown"
        with self.assertRaises(ValueError):
            candidate(receipt, self.registry)
        receipt = copy.deepcopy(self.baseline)
        receipt.update(season=2026, week=8)
        with self.assertRaises(ValueError):
            candidate(receipt, self.registry)

    def test_missing_pairs_are_excluded_not_joined_across_observations(self):
        first, second = copy.deepcopy(self.baseline), copy.deepcopy(self.baseline)
        first["rows"][0]["adjusted_projection"] = None
        second["rows"][0]["raw_projection"] = None
        records = [candidate(first, self.registry), candidate(second, self.registry)]
        self.assertEqual([r["coverage"]["excluded"] for r in records], [{"missing_pair": 1}] * 2)
        result = challenger.evaluate(records, [first, second], [], self.registry, now=FINAL)
        self.assertEqual(result["sample_context"]["rows"], 0)
        self.assertEqual(result["coverage"]["excluded"]["missing_pair"], 2)

    def test_observation_at_or_before_registration_cannot_be_prospective(self):
        for captured in (FREEZE - timedelta(seconds=1), FREEZE):
            with self.subTest(captured=captured), self.assertRaises(ValueError):
                candidate(baseline(captured=captured), self.registry)

    def test_source_capture_at_kickoff_is_excluded(self):
        receipt = copy.deepcopy(self.baseline)
        receipt["rows"][0]["kickoff"] = receipt["captured_at"]
        result = candidate(receipt, self.registry)
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["coverage"]["excluded"], {"source_not_pregame": 1})

    def test_calculation_at_or_after_kickoff_is_excluded(self):
        for completed in (KICKOFF, KICKOFF + timedelta(seconds=1)):
            result = candidate(self.baseline, self.registry, started=START, finished=completed)
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["coverage"]["excluded"], {"calculation_not_pregame": 1})

    def test_fixed_window_is_weeks_seven_through_fourteen_without_extension(self):
        self.assertEqual(self.registry["protocol"]["window"]["weeks"], list(range(7, 15)))
        self.assertIs(self.registry["protocol"]["window"]["shift_or_extension_allowed"], False)
        for week in (6, 15):
            receipt = baseline(week=week)
            result = candidate(receipt, self.registry)
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["coverage"]["excluded"], {"outside_fixed_window": 1})
        last = baseline(week=14, kickoff=KICKOFF + timedelta(weeks=7))
        self.assertEqual(len(candidate(last, self.registry)["rows"]), 1)

    def test_old_observation_can_only_be_a_labeled_development_example(self):
        old = baseline(captured=FREEZE - timedelta(days=1), week=6,
                       kickoff=FREEZE - timedelta(hours=1))
        record = candidate(old, self.registry, mode="development_descriptive")
        self.assertEqual(record["evidence_label"], "DEVELOPMENT_DESCRIPTIVE_NOT_PROSPECTIVE")
        result = challenger.evaluate([record], [old], [], self.registry, now=FINAL)
        self.assertEqual(result["status"], "NOT_RECORDED")
        self.assertEqual(result["coverage"]["excluded"]["development_descriptive_rows"], 1)
        self.assertEqual(result["sample_context"]["rows"], 0)

    def test_candidate_cannot_be_rebound_to_different_original_observation(self):
        result = candidate(self.baseline, self.registry)
        altered = copy.deepcopy(self.baseline)
        altered["rows"][0]["raw_projection"] = 99
        with self.assertRaises(ValueError):
            self.validate(result, altered)

    def test_candidate_center_cannot_be_tampered_even_with_rehashed_receipt(self):
        result = candidate(self.baseline, self.registry)
        result["rows"][0]["candidate_projection"] = 99
        with self.assertRaises(ValueError):
            self.validate(result)

    def test_future_completed_candidate_is_rejected_at_saved_consumption(self):
        result = candidate(self.baseline, self.registry)
        with self.assertRaises(ValueError):
            self.validate(result, now=START)

    def test_reversed_actual_calculation_clocks_rejected(self):
        with self.assertRaises(ValueError):
            candidate(self.baseline, self.registry, started=FINISH, finished=START)

    def test_create_only_receipt_retry_retains_identical_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(challenger, "datetime") as clock:
                clock.now.side_effect = [START, FINISH]
                path = challenger.capture_candidate(Path(temp), self.baseline, self.registry, code_commit=COMMIT)
            old_bytes = path.read_bytes()
            saved = read(path)
            with patch.object(challenger, "datetime") as clock:
                clock.now.side_effect = [START, FINISH]
                retried = challenger.capture_candidate(Path(temp), self.baseline, self.registry, code_commit=COMMIT)
            self.assertEqual(path, retried)
            self.assertEqual(path.read_bytes(), old_bytes)
            self.assertEqual(read(retried), saved)
            self.assertEqual(self.baseline, baseline())

    def test_corrupted_existing_candidate_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(challenger, "datetime") as clock:
                clock.now.side_effect = [START, FINISH]
                path = challenger.capture_candidate(Path(temp), self.baseline, self.registry, code_commit=COMMIT)
            damaged = path.read_bytes()[:-5]
            path.write_bytes(damaged)
            with patch.object(challenger, "datetime") as clock:
                clock.now.side_effect = [START, FINISH]
                with self.assertRaises((ValueError, EOFError, OSError)):
                    challenger.capture_candidate(Path(temp), self.baseline, self.registry, code_commit=COMMIT)
            self.assertEqual(path.read_bytes(), damaged)


class CandidateEvaluationTests(unittest.TestCase):
    def setUp(self):
        retained = self.enterContext(corrected.legacy_source(ROOT))
        self.enterContext(patch.object(challenger, "ROOT", retained))
        self.baseline = baseline()
        self.registry = registration()
        self.record = candidate(self.baseline, self.registry)

    def evaluate(self, *outcomes, candidates=None, baselines=None, now=FINAL + timedelta(days=1), policy=None):
        return challenger.evaluate(candidates if candidates is not None else [self.record],
                                   baselines if baselines is not None else [self.baseline],
                                   list(outcomes), self.registry, now=now, policy=policy)

    def test_empty_evidence_has_no_scores_or_invented_accuracy(self):
        result = self.evaluate(candidates=[], baselines=[])
        self.assertEqual(result["status"], "NOT_RECORDED")
        self.assertEqual(result["sample_context"], {"rows": 0, "unique_players": 0,
                                                  "unique_games": 0, "unique_weeks": 0})
        for role in ("raw_sleeper", "unchanged_website", "candidate"):
            self.assertEqual(result["categories"]["rec"][role],
                             {"n": 0, "mae": None, "rmse": None, "mean_error": None})
        self.assertIs(result["recording_operational"], False)
        self.assertIs(result["predictive_improvement_established"], False)
        self.assertIs(result["production_enabled"], False)

    def test_missing_pending_unresolved_and_confirmed_dnp_have_separate_coverage(self):
        missing = self.evaluate()
        self.assertEqual(missing["outcome_status"], {"missing_outcome": 1})
        for status in ("pending", "unresolved", "dnp"):
            with self.subTest(status=status):
                result = self.evaluate(saved_outcome(status=status))
                self.assertEqual(result["outcome_status"], {status: 1})
                self.assertEqual(result["categories"]["rec"]["candidate"]["n"], 0)
                self.assertEqual(result["forecast_context"]["rows"], 1)

    def test_all_pending_week_remains_visible_with_unavailable_scores(self):
        result = self.evaluate(saved_outcome(status="pending"))
        self.assertEqual(len(result["weekly"]), 1)
        week = result["weekly"][0]
        self.assertEqual((week["season"], week["week"]), (2026, 7))
        self.assertEqual(week["outcome_status"], {"pending": 1})
        self.assertEqual(week["forecast_context"]["rows"], 1)
        self.assertEqual(week["sample_context"]["rows"], 0)
        self.assertIsNone(week["metrics"]["candidate"]["mae"])

    def test_actual_zero_is_scored_with_saved_participation_evidence(self):
        result = self.evaluate(saved_outcome(actual=0))
        self.assertEqual(result["outcome_status"], {"resolved": 1})
        self.assertEqual(result["categories"]["rec"]["candidate"]["mae"], 3)
        self.assertEqual(result["rows"][0]["actual"], 0)

    def test_unattributed_or_missing_legacy_statistics_remain_unresolved_for_candidate(self):
        for remove in ("source", "stats_entry"):
            outcome = saved_outcome()
            if remove == "source":
                outcome["source"] = None
            else:
                outcome["rows"][0].pop("stats_entry")
            before = copy.deepcopy(outcome)
            with self.subTest(remove=remove):
                result = self.evaluate(outcome)
                self.assertEqual(result["outcome_status"], {"unresolved": 1})
                self.assertEqual(result["categories"]["rec"]["candidate"]["n"], 0)
                self.assertEqual(result["rows"][0]["evaluation_reason"], "legacy_missing_source_or_stats")
                self.assertEqual(outcome, before)

    def test_unknown_provider_asof_clock_does_not_erase_attributed_saved_statistics(self):
        outcome = saved_outcome()
        self.assertIsNone(outcome["source_timestamp"])
        result = self.evaluate(outcome)
        self.assertEqual(result["outcome_status"], {"resolved": 1})
        self.assertIsNone(result["rows"][0]["selected_outcome_provenance"]["source_timestamp"])

    def test_known_common_row_metrics_and_summary_reconcile(self):
        second = baseline(raw=5, adjusted=1, player="fictional-2", game="fictional-game-2")
        other_record = candidate(second, self.registry)
        result = self.evaluate(saved_outcome(actual=1), saved_outcome(second, actual=4),
                               candidates=[other_record, self.record], baselines=[second, self.baseline])
        metrics = result["categories"]["rec"]
        self.assertEqual(metrics["raw_sleeper"], {"n": 2, "mae": 1, "rmse": 1, "mean_error": 1})
        self.assertEqual(metrics["unchanged_website"], {"n": 2, "mae": 3, "rmse": 3, "mean_error": 0})
        self.assertEqual(metrics["candidate"]["mae"], 1.5)
        self.assertAlmostEqual(metrics["candidate"]["rmse"], (2.5) ** .5)
        self.assertEqual(metrics["candidate"]["mean_error"], .5)
        self.assertEqual(metrics["paired_mae_delta_candidate_minus_raw_sleeper"], .5)
        self.assertEqual(metrics["paired_mae_delta_candidate_minus_unchanged_website"], -1.5)
        self.assertEqual(result["sample_context"], {"rows": 2, "unique_players": 2,
                                                  "unique_games": 2, "unique_weeks": 1})
        self.assertEqual(result["weekly"][0]["metrics"], metrics)
        self.assertEqual(result["season_to_date"], metrics)
        self.assertEqual(result["cumulative"], metrics)
        self.assertEqual(sum(result["outcome_status"].values()), len(result["rows"]))
        self.assertEqual(len(result["rows"]), metrics["candidate"]["n"])
        self.assertIs(result["predictive_improvement_established"], False)

    def test_repeated_capture_and_duplicate_receipt_add_no_samples(self):
        later = baseline(captured=CAPTURE + timedelta(minutes=2), raw=99, adjusted=99)
        later_record = candidate(later, self.registry, started=START + timedelta(minutes=3),
                                 finished=FINISH + timedelta(minutes=3))
        result = self.evaluate(saved_outcome(), candidates=[later_record, self.record, self.record],
                               baselines=[later, self.baseline])
        self.assertEqual(result["categories"]["rec"]["candidate"]["n"], 1)
        self.assertEqual(result["rows"][0]["candidate_projection"], 3)
        self.assertEqual(result["rows"][0]["baseline_payload_sha256"], digest(self.baseline))
        self.assertEqual(result["coverage"]["repeated_capture_rows"], 1)
        self.assertEqual(result["coverage"]["duplicate_candidate_receipts"], 1)

    def test_candidate_requires_exact_original_baseline_at_consumption(self):
        with self.assertRaises(ValueError):
            self.evaluate(baselines=[])

    def test_selected_correction_preserves_outcome_history_and_original_forecast(self):
        first = saved_outcome(actual=1)
        corrected = saved_outcome(actual=3, collected=FINAL + timedelta(hours=1))
        before = copy.deepcopy((self.baseline, self.record, first))
        result = self.evaluate(first, corrected)
        row = result["rows"][0]
        self.assertEqual(row["actual"], 3)
        self.assertEqual(row["outcome_snapshot_sha256"], digest(corrected))
        self.assertEqual(row["selected_outcome_provenance"]["outcome_snapshot_sha256"], digest(corrected))
        self.assertEqual(len(row["outcome_observations"]), 2)
        self.assertIs(row["outcome_revision"], True)
        self.assertEqual((self.baseline, self.record, first), before)

    def test_conflicting_sources_are_not_cherry_picked_as_an_actual(self):
        result = self.evaluate(saved_outcome(actual=1),
                               saved_outcome(actual=3, source="fictional_source_B"))
        self.assertEqual(result["outcome_status"], {"unresolved": 1})
        self.assertEqual(result["categories"]["rec"]["candidate"]["n"], 0)
        self.assertIs(result["rows"][0]["outcome_conflict"], True)
        self.assertIsNone(result["rows"][0]["selected_outcome_provenance"])

    def test_agreeing_sources_stay_one_sample_with_explicit_provenance(self):
        a = saved_outcome()
        b = saved_outcome(source="fictional_source_B")
        result = self.evaluate(a, b, a)
        self.assertEqual(result["sample_context"]["rows"], 1)
        self.assertEqual(result["rows"][0]["outcome_source_mix"], "mixed_agreeing_sources")
        self.assertEqual(len(result["rows"][0]["outcome_observations"]), 2)

    def test_invalid_saved_outcome_integrity_is_not_suppressed(self):
        bad = saved_outcome()
        bad["rows"][0]["stats_entry"]["stats"]["rec"] = 99
        with self.assertRaises(ValueError):
            self.evaluate(bad)

    def test_future_outcome_or_source_clock_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate(saved_outcome(), now=FINAL - timedelta(seconds=1))
        bad = saved_outcome()
        bad["source_timestamp"] = stamp(FINAL + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            self.evaluate(bad)

    def test_schedule_team_and_opponent_conflicts_do_not_score(self):
        changed_schedule = saved_outcome()
        changed_schedule["rows"][0]["kickoff"] = stamp(KICKOFF + timedelta(hours=1))
        changed_schedule["games"][0]["kickoff"] = changed_schedule["rows"][0]["kickoff"]
        changed_team = saved_outcome()
        changed_team["rows"][0]["team"] = "BBB"
        changed_team["rows"][0]["stats_entry"].update(team="BBB", opp="AAA")
        wrong_opponent = saved_outcome(opponent="CCC")
        for outcome in (changed_schedule, changed_team, wrong_opponent):
            with self.subTest(outcome=outcome):
                result = self.evaluate(outcome)
                self.assertEqual(result["categories"]["rec"]["candidate"]["n"], 0)

    def test_arbitrary_saved_complete_flag_does_not_unlock_uncertainty(self):
        outcome = saved_outcome()
        outcome["rows"][0]["week_confirmed_complete"] = True
        policy = json.loads((ROOT / "config/evaluation-policy.json").read_text())
        result = self.evaluate(outcome, policy=policy)
        self.assertIs(result["rows"][0]["week_confirmed_complete"], False)
        for comparator in ("raw_sleeper", "unchanged_website"):
            self.assertIsNone(result["uncertainty"][comparator]["interval"])
            self.assertEqual(result["uncertainty"][comparator]["completed_weeks"], 0)
            self.assertEqual(result["uncertainty"][comparator]["comparator"], comparator)
            self.assertIn("completed_week_mae_delta_candidate_minus_comparator", result["uncertainty"][comparator])
            self.assertNotIn("completed_week_mae_delta_clone_minus_raw", result["uncertainty"][comparator])
        changed_policy = copy.deepcopy(policy)
        changed_policy["uncertainty"]["minimum_completed_weeks"] = 1
        with self.assertRaises(ValueError):
            self.evaluate(outcome, policy=changed_policy)

    def test_eight_qualified_fictional_weeks_retain_both_comparator_intervals(self):
        from test_source_evidence import fictional_status
        from test_week_population import fictional_receipt
        baselines, records, outcomes = [], [], []
        for offset, week in enumerate(range(7, 15)):
            first = KICKOFF + timedelta(weeks=offset)
            capture = CAPTURE + timedelta(weeks=offset)
            receipt = baseline(captured=capture, kickoff=first, week=week, game="10000")
            records.append(candidate(receipt, self.registry, started=capture + timedelta(minutes=1),
                                     finished=capture + timedelta(minutes=1, seconds=1)))
            baselines.append(receipt)
            observed = first + timedelta(hours=5)
            outcome = saved_outcome(receipt, actual=3, collected=observed)
            population = fictional_receipt(first=first, week=week, captured_at=capture,
                                            spacing=timedelta(minutes=1))
            games = [{**game, "state": "post", "detail": "Final"}
                     for game in population["source_document"]["games"]]
            games[0].update(home="AAA", away="BBB")
            outcome.update(games=games,
                           week_game_populations=[{"payload_sha256": digest(population), "payload": population}],
                           source_game_status=fictional_status(games, week=week, collected_at=observed))
            outcomes.append(outcome)
        result = challenger.evaluate(records, baselines, outcomes, self.registry,
                                     now=KICKOFF + timedelta(weeks=8))
        self.assertEqual(result["sample_context"]["unique_weeks"], 8)
        for role in ("raw_sleeper", "unchanged_website"):
            interval = result["uncertainty"][role]
            self.assertEqual(interval["completed_weeks"], 8)
            self.assertEqual(interval["interval"], [-1, -1])
            self.assertEqual(interval["completed_week_mae_delta_candidate_minus_comparator"], -1)
            self.assertEqual(interval["confidence"], 1 - .05 / 3)
        seven = challenger.evaluate(records[:7], baselines[:7], outcomes[:7], self.registry,
                                    now=KICKOFF + timedelta(weeks=8))
        self.assertIsNone(seven["uncertainty"]["raw_sleeper"]["interval"])
        self.assertEqual(seven["uncertainty"]["raw_sleeper"]["completed_weeks"], 7)

    def test_actual_saved_snapshot_path_reports_points_without_full_week_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "output/data").mkdir(parents=True)
            (root / "data/cache").mkdir(parents=True)
            row = self.baseline["rows"][0]
            board = {"season": 2026, "week": 7,
                     "games": [{"id": row["game_id"], "kickoff": row["kickoff"], "home": "AAA", "away": "BBB",
                                "state": "post", "detail": "Final"}]}
            (root / "output/data/week.json").write_text(json.dumps(board))
            (root / "data/cache/stats_2026_07.json").write_text(json.dumps({row["player_id"]:
                {"team": "AAA", "opp": "BBB", "stats": {"gp": 1, "rec": 3}}}))
            paths = snapshot_outcomes(root, {identity(row): row}, FINAL)
            original_bytes = [path.read_bytes() for path in paths]
            result = self.evaluate(*(read(path) for path in paths))
            self.assertEqual(result["outcome_status"], {"resolved": 1})
            self.assertEqual(result["categories"]["rec"]["candidate"]["mae"], 0)
            self.assertIs(result["rows"][0]["week_confirmed_complete"], False)
            self.assertEqual(result["rows"][0]["outcome_identity_status"], "bound_to_recorded_game")
            self.assertEqual([path.read_bytes() for path in paths], original_bytes)


if __name__ == "__main__":
    unittest.main()
