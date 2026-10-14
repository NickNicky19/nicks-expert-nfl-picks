"""Paired times, unique outcomes, final/participation evidence and uncertainty."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
from reliability import digest, make_payload, stamp
from scorecard import cluster_interval, latest_outcomes, paired_forecasts, score, snapshot_outcomes
from evidence import read
from test_reliability import fixture, NOW


def setup():
    data, _ = fixture()
    payload = make_payload(data, NOW, {"test": "fixture"}, "live")
    policy = json.loads((ROOT / "config/evaluation-policy.json").read_text())
    policy["registered_at"] = stamp(NOW - timedelta(days=1))
    return data, payload, policy


class ScorecardTests(unittest.TestCase):
    def test_repeated_receipts_use_first_matched_pair_once(self):
        _, first, policy = setup()
        second = copy.deepcopy(first); second["captured_at"] = stamp(NOW + timedelta(minutes=1))
        second["rows"][0].update(raw_projection=99, adjusted_projection=88)
        pairs, coverage = paired_forecasts([second, first, first], policy, {"test": "fixture"})
        self.assertEqual(len(pairs), 1)
        self.assertEqual(coverage["repeated_capture_rows"], 2)
        row = next(iter(pairs.values()))
        self.assertEqual(row["raw_projection"], 4.8)
        self.assertEqual(row["adjusted_projection"], 5.2)
        self.assertEqual(row["baseline_payload_sha256"], digest(first))

    def test_missing_pair_not_compared_against_different_time(self):
        _, a, policy = setup(); b = copy.deepcopy(a)
        a["rows"][0]["adjusted_projection"] = None
        b["rows"][0]["raw_projection"] = None
        pairs, coverage = paired_forecasts([a, b], policy, {"test": "fixture"})
        self.assertFalse(pairs)
        self.assertEqual(coverage["excluded"]["missing_pair"], 2)

    def test_mixed_timestamp_precision_orders_actual_instants(self):
        _, older, policy = setup(); newer = copy.deepcopy(older)
        older["captured_at"] = "2026-10-10T19:00:00Z"
        newer["captured_at"] = "2026-10-10T19:00:00.900000Z"
        newer["rows"][0]["raw_projection"] = 99
        pairs, _ = paired_forecasts([newer, older], policy, {"test": "fixture"})
        self.assertEqual(next(iter(pairs.values()))["raw_projection"], 4.8)
        row = next(iter(pairs.values()))
        a = {"schema_version": "forecast-outcomes-v1", "mode": "live", "collected_at": "2026-10-10T23:00:00Z",
             "rows": [{**row, "status": "resolved", "actual": 3, "game_state": "post", "final_confirmed": True}]}
        b = copy.deepcopy(a); b["collected_at"] = "2026-10-10T23:00:00.900000Z"; b["rows"][0]["actual"] = 5
        # A correction needs an explicit fictional source and distinct saved versions.
        for snapshot in (a, b):
            snapshot.update(source="fictional_correction_source", cache_path="data/cache/fictional.json",
                            cache_sha256=digest({"rec": snapshot["rows"][0]["actual"]}))
        self.assertEqual(next(iter(latest_outcomes([a, b]).values()))["actual"], 5)

    def test_replay_and_started_receipts_excluded(self):
        _, p, policy = setup(); replay = copy.deepcopy(p); replay["mode"] = "replay"
        late = copy.deepcopy(p); late["captured_at"] = p["rows"][0]["kickoff"]
        pairs, coverage = paired_forecasts([late, replay], policy, {"test": "fixture"})
        self.assertFalse(pairs)
        self.assertEqual(coverage["excluded"], {"non_live_receipt": 1, "not_pregame": 1})

    def test_duplicate_row_and_wrong_engine_fail(self):
        _, p, policy = setup()
        with self.assertRaises(ValueError): paired_forecasts([p], policy, {"wrong": "engine"})
        p["rows"].append(copy.deepcopy(p["rows"][0]))
        with self.assertRaises(ValueError): paired_forecasts([p], policy, {"test": "fixture"})

    def outcomes(self, entry, final=True):
        data, p, policy = setup()
        pairs, coverage = paired_forecasts([p], policy, {"test": "fixture"})
        if final:
            data["games"][0]["state"] = "post"
            data["games"][0]["detail"] = "Final"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "output/data").mkdir(parents=True); (root / "data/cache").mkdir(parents=True)
            (root / "output/data/week.json").write_text(json.dumps(data))
            cache = {} if entry is None else {"fictional-1": entry}
            (root / "data/cache/stats_2026_05.json").write_text(json.dumps(cache))
            paths = snapshot_outcomes(root, pairs, NOW + timedelta(hours=5))
            outcomes = latest_outcomes([read(x) for x in paths])
            report = score(pairs, outcomes, coverage, policy)
            return report, read(paths[0])

    def test_pending_and_missing_participation_do_not_become_zero(self):
        report, _ = self.outcomes({"team": "AAA", "stats": {"gp": 1, "rec": 5}}, final=False)
        self.assertEqual(report["outcome_status"], {"pending": 1})
        self.assertIsNone(report["categories"]["rec"]["raw_sleeper"]["mae"])
        for entry in (None, {"team": "AAA", "stats": {}}):
            report, _ = self.outcomes(entry)
            self.assertEqual(report["outcome_status"], {"unresolved": 1})

    def test_played_sparse_zero_and_signed_errors(self):
        report, snapshot = self.outcomes({"team": "AAA", "stats": {"gp": 1}})
        self.assertEqual(report["outcome_status"], {"resolved": 1})
        self.assertEqual(report["categories"]["rec"]["raw_sleeper"]["mae"], 4.8)
        self.assertEqual(report["categories"]["rec"]["unchanged_clone"]["mean_error"], 5.2)
        self.assertEqual(snapshot["rows"][0]["actual"], 0)

    def test_explicit_dnp_separate_and_null_stat_unresolved(self):
        report, _ = self.outcomes({"participation_status": "dnp", "participation_source": "fictional_confirmation"})
        self.assertEqual(report["outcome_status"], {"dnp": 1})
        report, _ = self.outcomes({"team": "AAA", "stats": {"gp": 1, "rec": None}})
        self.assertEqual(report["outcome_status"], {"unresolved": 1})

    def test_team_mismatch_unresolved(self):
        report, _ = self.outcomes({"team": "BBB", "stats": {"gp": 1, "rec": 5}})
        self.assertEqual(report["outcome_status"], {"unresolved": 1})

    def test_pre_registration_games_excluded_from_primary(self):
        _, p, policy = setup(); policy["registered_at"] = p["rows"][0]["kickoff"]
        pairs, coverage = paired_forecasts([p], policy, {"test": "fixture"})
        report = score(pairs, {}, coverage, policy)
        self.assertEqual(report["outcome_status"], {"excluded_pre_registration_game": 1})

    def test_corrections_keep_forecasts_and_prior_outcomes(self):
        _, p, policy = setup(); pairs, coverage = paired_forecasts([p], policy, {"test": "fixture"})
        row = next(iter(pairs.values()))
        a = {"schema_version": "forecast-outcomes-v1", "mode": "live", "collected_at": stamp(NOW + timedelta(hours=5)),
             "rows": [{**row, "status": "resolved", "actual": 3, "game_state": "post", "final_confirmed": True}]}
        b = copy.deepcopy(a); b.update(collected_at=stamp(NOW + timedelta(hours=6))); b["rows"][0]["actual"] = 5
        for snapshot in (a, b):
            snapshot.update(source="fictional_correction_source", cache_path="data/cache/fictional.json",
                            cache_sha256=digest({"rec": snapshot["rows"][0]["actual"]}))
        before = copy.deepcopy(p)
        report = score(pairs, latest_outcomes([b, a]), coverage, policy)
        self.assertAlmostEqual(report["categories"]["rec"]["raw_sleeper"]["mae"], .2)
        self.assertEqual(a["rows"][0]["actual"], 3)
        self.assertEqual(p, before)

    def test_week_cluster_uncertainty_requires_eight_weeks(self):
        _, _, policy = setup()
        rows = [{"season": 2026, "week": w, "raw_projection": 5, "adjusted_projection": 4, "actual": 3,
                 "week_confirmed_complete": True} for w in range(1, 9)]
        self.assertIsNone(cluster_interval(rows[:7], policy)["interval"])
        self.assertEqual(cluster_interval(rows, policy)["interval"], [-1, -1])
        rows[-1]["week_confirmed_complete"] = False
        self.assertIsNone(cluster_interval(rows, policy)["interval"])

    def test_cancelled_post_flag_does_not_establish_a_final(self):
        data, p, policy = setup(); data["games"][0].update(state="post", detail="Cancelled")
        pairs, _ = paired_forecasts([p], policy, {"test": "fixture"})
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "output/data").mkdir(parents=True); (root / "data/cache").mkdir(parents=True)
            (root / "output/data/week.json").write_text(json.dumps(data))
            (root / "data/cache/stats_2026_05.json").write_text(json.dumps({"fictional-1": {"team": "AAA", "stats": {"gp": 1, "rec": 5}}}))
            paths = snapshot_outcomes(root, pairs, NOW + timedelta(hours=5))
            outcome = read(paths[0])["rows"][0]
            self.assertEqual(outcome["status"], "pending")
            self.assertIsNone(outcome["actual"])
            self.assertFalse(outcome["week_confirmed_complete"])


class OutcomePrecedenceRegressionTests(unittest.TestCase):
    """Fictional final observations exercise precedence without changing evidence."""

    def snapshot(self, actual=3, status="resolved", hour=5, source="fictional_stats_A", complete=False):
        _, baseline, policy = setup()
        pairs, _ = paired_forecasts([baseline], policy, {"test": "fixture"})
        row = copy.deepcopy(next(iter(pairs.values())))
        entry = {"team": row["team"], "stats": {"gp": 1, row["category"]: actual}}
        if status == "dnp":
            entry = {"participation_status": "dnp", "participation_source": "fictional_dnp_confirmation"}
        if status in ("pending", "unresolved", "void"):
            entry = None
        row.update(status=status, actual=actual if status == "resolved" else None,
                   game_state="pre" if status == "pending" else "post",
                   final_confirmed=status != "pending", stats_entry=entry,
                   week_confirmed_complete=complete)
        return {"schema_version": "forecast-outcomes-v1", "mode": "live",
                "collected_at": stamp(NOW + timedelta(hours=hour)), "source": source,
                "source_timestamp": None, "cache_path": "data/cache/fictional_2026_05.json",
                "cache_sha256": digest({row["player_id"]: entry}),
                "game_snapshot_sha256": digest({"kickoff": row["kickoff"], "state": row["game_state"]}),
                "rows": [row]}

    def chosen(self, *snapshots):
        return next(iter(latest_outcomes(list(snapshots)).values()))

    def test_confirmed_final_survives_later_pending_and_missing(self):
        final = self.snapshot()
        for status in ("pending", "unresolved"):
            with self.subTest(status=status):
                later = self.snapshot(status=status, hour=6)
                result = self.chosen(later, final)
                self.assertEqual((result["status"], result["actual"]), ("resolved", 3))
                self.assertEqual(result["outcome_snapshot_sha256"], digest(final))
                self.assertEqual({x["outcome_snapshot_sha256"] for x in result["outcome_observations"]},
                                 {digest(final), digest(later)})

    def test_missing_then_sourced_final_resolves_in_any_input_order(self):
        missing = self.snapshot(status="unresolved", hour=4)
        final = self.snapshot(hour=5)
        self.assertEqual(self.chosen(missing, final), self.chosen(final, missing))
        self.assertEqual(self.chosen(missing, final)["actual"], 3)

    def test_sourced_statistical_correction_retains_both_observations(self):
        first, corrected = self.snapshot(3), self.snapshot(5, hour=6)
        before = copy.deepcopy([first, corrected])
        result = self.chosen(corrected, first)
        self.assertEqual(result["actual"], 5)
        self.assertEqual(result["outcome_snapshot_sha256"], digest(corrected))
        self.assertEqual([x["actual"] for x in result["outcome_observations"]], [3, 5])
        self.assertEqual([first, corrected], before)

    def test_disagreeing_final_sources_are_quarantined_from_scoring(self):
        a, b = self.snapshot(3), self.snapshot(9, source="fictional_stats_B", hour=6)
        result = self.chosen(a, b)
        self.assertEqual(result["status"], "unresolved")
        self.assertIsNone(result["actual"])
        self.assertTrue(result["outcome_conflict"])
        _, baseline, policy = setup()
        pairs, coverage = paired_forecasts([baseline], policy, {"test": "fixture"})
        report = score(pairs, latest_outcomes([a, b]), coverage, policy)
        self.assertEqual(report["categories"]["rec"]["raw_sleeper"]["n"], 0)
        self.assertTrue(report["rows"][0]["outcome_conflict"])
        self.assertEqual(len(report["rows"][0]["outcome_observations"]), 2)

    def test_same_source_same_cache_version_cannot_have_two_actuals(self):
        a, b = self.snapshot(3), self.snapshot(5, hour=6)
        b["cache_sha256"] = a["cache_sha256"]
        result = self.chosen(a, b)
        self.assertTrue(result["outcome_conflict"])
        self.assertIsNone(result["actual"])

    def test_equal_timestamp_conflicting_versions_have_no_digest_winner(self):
        a, b = self.snapshot(3), self.snapshot(5)
        self.assertEqual(self.chosen(a, b), self.chosen(b, a))
        self.assertTrue(self.chosen(a, b)["outcome_conflict"])
        self.assertIsNone(self.chosen(a, b)["actual"])

    def test_agreeing_final_sources_are_one_scored_outcome(self):
        a, b = self.snapshot(3), self.snapshot(3, source="fictional_stats_B", hour=6)
        result = self.chosen(a, b)
        self.assertEqual(result["actual"], 3)
        self.assertFalse(result["outcome_conflict"])
        self.assertEqual(len(result["outcome_observations"]), 2)

    def test_later_same_source_correction_can_reconcile_cross_source_conflict(self):
        a, b = self.snapshot(3), self.snapshot(5, source="fictional_stats_B", hour=6)
        corrected = self.snapshot(5, hour=7)
        result = self.chosen(a, b, corrected)
        self.assertEqual((result["status"], result["actual"]), ("resolved", 5))
        self.assertFalse(result["outcome_conflict"])
        self.assertEqual([x["actual"] for x in result["outcome_observations"]], [3, 5, 5])

    def test_old_cache_reappearance_without_source_time_cannot_choose_a_winner(self):
        original, corrected = self.snapshot(3), self.snapshot(5, hour=6)
        old_return = self.snapshot(3, hour=7)
        result = self.chosen(original, corrected, old_return)
        self.assertEqual(result["status"], "unresolved")
        self.assertIsNone(result["actual"])
        self.assertTrue(result["outcome_conflict"])
        self.assertEqual(len(result["outcome_observations"]), 3)

    def test_fresh_sourced_timestamp_can_confirm_a_legitimate_value_reversion(self):
        original, corrected, reverted = self.snapshot(3), self.snapshot(5, hour=6), self.snapshot(3, hour=7)
        for p, hour in zip((original, corrected, reverted), (4, 5, 6)):
            p["source_timestamp"] = stamp(NOW + timedelta(hours=hour))
        result = self.chosen(original, corrected, reverted)
        self.assertEqual(result["actual"], 3)
        self.assertFalse(result["outcome_conflict"])
        self.assertEqual(result["outcome_snapshot_sha256"], digest(reverted))

    def test_supplied_source_timestamp_orders_versions_before_collection_time(self):
        first, later_collection = self.snapshot(3), self.snapshot(5, hour=6)
        first["source_timestamp"] = stamp(NOW + timedelta(hours=4))
        later_collection["source_timestamp"] = stamp(NOW + timedelta(hours=3))
        self.assertEqual(self.chosen(first, later_collection)["actual"], 3)

    def test_unattributed_disagreeing_finals_cannot_be_called_a_correction(self):
        a, b = self.snapshot(3, source=None), self.snapshot(5, hour=6, source=None)
        result = self.chosen(a, b)
        self.assertIsNone(result["actual"])
        self.assertTrue(result["outcome_conflict"])

    def test_sourced_dnp_and_recorded_void_survive_incomplete_observations(self):
        for status in ("dnp", "void"):
            with self.subTest(status=status):
                final = self.snapshot(status=status)
                missing = self.snapshot(status="unresolved", hour=6)
                result = self.chosen(final, missing)
                self.assertEqual(result["status"], status)
                self.assertIsNone(result["actual"])

    def test_nonfinal_dnp_does_not_override_a_confirmed_statistic(self):
        final, unsupported = self.snapshot(3), self.snapshot(status="dnp", hour=6)
        unsupported["rows"][0]["final_confirmed"] = False
        self.assertEqual(self.chosen(final, unsupported)["actual"], 3)

    def test_duplicate_receipts_and_identical_rows_do_not_add_observations(self):
        final = self.snapshot(3)
        duplicate = copy.deepcopy(final)
        duplicate["rows"].append(copy.deepcopy(duplicate["rows"][0]))
        one = self.chosen(final, final)
        self.assertEqual(len(one["outcome_observations"]), 1)
        self.assertEqual(len(self.chosen(duplicate)["outcome_observations"]), 1)

    def test_confirmed_week_completion_survives_later_outage(self):
        final, outage = self.snapshot(3, complete=True), self.snapshot(status="unresolved", hour=6)
        result = self.chosen(final, outage)
        self.assertTrue(result["week_confirmed_complete"])
        self.assertEqual(result["actual"], 3)

    def test_later_final_week_proof_can_complete_an_earlier_resolved_row(self):
        early = self.snapshot(3)
        missing_stat = self.snapshot(status="unresolved", hour=6, complete=True)
        result = self.chosen(early, missing_stat)
        self.assertEqual(result["actual"], 3)
        self.assertTrue(result["week_confirmed_complete"])

    def test_missing_stats_final_survives_an_outage_with_missing_game_mapping(self):
        final = self.snapshot(status="unresolved", complete=True)
        outage = self.snapshot(status="pending", hour=6)
        outage["rows"][0]["kickoff"] = None
        result = self.chosen(final, outage)
        self.assertEqual(result["status"], "unresolved")
        self.assertTrue(result["week_confirmed_complete"])
        self.assertIsNone(result["actual"])

    def test_future_source_timestamp_is_not_a_valid_correction(self):
        bad = self.snapshot(5)
        bad["source_timestamp"] = stamp(NOW + timedelta(hours=7))
        with self.assertRaises(ValueError):
            self.chosen(self.snapshot(3), bad)

    def test_malformed_saved_source_version_fails_closed(self):
        bad = self.snapshot(5)
        bad["cache_sha256"] = "not-a-recorded-digest"
        with self.assertRaises(ValueError):
            self.chosen(bad)

    def test_resolved_value_must_match_its_provided_saved_statistic(self):
        for entry in ({"team": "AAA", "stats": {"gp": 1, "rec": 99}}, "not-a-statistics-entry"):
            with self.subTest(entry=entry):
                bad = self.snapshot(3)
                bad["rows"][0]["stats_entry"] = entry
                with self.assertRaises(ValueError):
                    self.chosen(bad)

    def test_different_values_without_saved_versions_stay_unresolved(self):
        a, b = self.snapshot(3), self.snapshot(5, hour=6)
        for p in (a, b):
            p.pop("cache_sha256")
            p["rows"][0].pop("stats_entry")
        result = self.chosen(a, b)
        self.assertTrue(result["outcome_conflict"])
        self.assertIsNone(result["actual"])

    def test_dnp_without_attributed_participation_cannot_replace_final(self):
        unsupported = self.snapshot(status="dnp", hour=6)
        unsupported["rows"][0]["stats_entry"] = None
        self.assertEqual(self.chosen(self.snapshot(3), unsupported)["actual"], 3)

    def test_negative_integer_passing_yards_remain_valid(self):
        p = self.snapshot(3)
        row = p["rows"][0]
        row.update(category="pass_yd", actual=-4)
        row["stats_entry"]["stats"] = {"gp": 1, "pass_yd": -4}
        p["cache_sha256"] = digest({row["player_id"]: row["stats_entry"]})
        self.assertEqual(self.chosen(p)["actual"], -4)

    def test_invalid_confirmed_values_still_fail_closed(self):
        for value in (float("nan"), float("inf"), -1, 1.5, True):
            with self.subTest(value=value):
                p = self.snapshot(3)
                p["rows"][0]["actual"] = value
                with self.assertRaises(ValueError):
                    self.chosen(p)


class CompletedWeekRegressionTests(unittest.TestCase):
    def rows(self):
        return [{"season": 2026, "week": week, "raw_projection": 5,
                 "adjusted_projection": 4, "actual": 3,
                 "week_confirmed_complete": True} for week in range(1, 9)]

    def test_incomplete_week_cannot_change_primary_interval(self):
        _, _, policy = setup()
        complete = self.rows()
        extra = {**complete[0], "week": 9, "adjusted_projection": 999,
                 "week_confirmed_complete": False}
        before, after = cluster_interval(complete, policy), cluster_interval([extra] + complete, policy)
        self.assertEqual(before["interval"], [-1, -1])
        self.assertEqual(after["interval"], before["interval"])
        self.assertEqual(after["resampled_week_clusters"], 8)
        self.assertEqual(after["resampled_outcomes"], 8)
        self.assertEqual(after["excluded_incomplete_week_clusters"], 1)

    def test_mixed_completion_flags_do_not_open_the_eight_week_gate(self):
        _, _, policy = setup()
        rows = self.rows()
        rows.append({**rows[-1], "week_confirmed_complete": False})
        result = cluster_interval(rows, policy)
        self.assertEqual(result["status"], "insufficient_completed_weeks")
        self.assertEqual(result["completed_weeks"], 7)
        self.assertIsNone(result["interval"])

    def test_reordered_input_has_identical_seeded_complete_week_interval(self):
        _, _, policy = setup()
        rows = self.rows()
        for i, row in enumerate(rows):
            row["adjusted_projection"] = 3 + i * i
        rows.extend([{**rows[0], "adjusted_projection": 9}, {**rows[-1], "adjusted_projection": 1}])
        self.assertEqual(cluster_interval(rows, policy), cluster_interval(list(reversed(rows)), policy))

    def test_all_rows_of_a_week_resample_as_one_cluster(self):
        _, _, policy = setup()
        rows = []
        for week in range(1, 9):
            rows.extend([{"season": 2026, "week": week, "actual": 0,
                          "raw_projection": 0, "adjusted_projection": 9,
                          "week_confirmed_complete": True},
                         {"season": 2026, "week": week, "actual": 0,
                          "raw_projection": 9, "adjusted_projection": 0,
                          "week_confirmed_complete": True}])
        result = cluster_interval(rows, policy)
        self.assertEqual(result["interval"], [0, 0])
        self.assertEqual(result["resampled_outcomes"], 16)

    def test_completed_week_denominator_weights_paired_outcomes(self):
        _, _, policy = setup()
        rows = [{"season": 2026, "week": 1, "raw_projection": 0, "adjusted_projection": 0,
                 "actual": 0, "week_confirmed_complete": True} for _ in range(100)]
        rows.extend({"season": 2026, "week": w, "raw_projection": 0, "adjusted_projection": 10,
                     "actual": 0, "week_confirmed_complete": True} for w in range(2, 9))
        result = cluster_interval(rows, policy)
        self.assertEqual(result["resampled_outcomes"], 107)
        self.assertAlmostEqual(result["completed_week_mae_delta_clone_minus_raw"], 70 / 107)

    def test_empty_population_and_insufficient_weeks_keep_gate_and_counts(self):
        _, _, policy = setup()
        result = cluster_interval([], policy)
        self.assertEqual(result["status"], "insufficient_completed_weeks")
        self.assertEqual(result["completed_weeks"], 0)
        self.assertEqual(result["resampled_outcomes"], 0)
        self.assertIsNone(result["interval"])



if __name__ == "__main__":
    unittest.main()
