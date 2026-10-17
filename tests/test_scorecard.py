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
from scorecard import build_scorecard, cluster_interval, latest_outcomes, paired_forecasts, score, snapshot_outcomes
from evidence import read
from test_reliability import fixture, NOW
from test_source_evidence import fictional_status


def setup(*, population=False):
    data, _ = fixture()
    # The recognized ESPN population contract requires numeric event IDs.
    # Bind every fixture forecast/selection to the same fictional event.
    # Keep the shared default used by unrelated end-to-end/shadow tests.
    if population:
        data["games"][0]["id"] = "10000"
        for player in data["players"]:
            player["game_id"] = "10000"
        for picks in data["picks"].values():
            for pick in picks:
                pick["game_id"] = "10000"
    payload = make_payload(data, NOW, {"test": "fixture"}, "live")
    policy = json.loads((ROOT / "config/evaluation-policy.json").read_text())
    policy["registered_at"] = stamp(NOW - timedelta(days=1))
    return data, payload, policy


def fictional_week_population(week=5):
    """A source-valid full fictional slate; never a bare self-certified document."""
    import test_week_population as population_fixtures
    return population_fixtures.fictional_receipt(first=NOW + timedelta(hours=1), week=week,
                                                captured_at=NOW, spacing=timedelta(minutes=1))


def final_games(population):
    games = [{**game, "state": "post", "detail": "Final"}
             for game in population["source_document"]["games"]]
    # The forecast/cache fixtures use AAA/BBB. Bind those recorded board codes
    # explicitly instead of accidentally claiming AAA is Arizona or Atlanta.
    games[0].update(home="AAA", away="BBB")
    return games


class ScorecardTests(unittest.TestCase):
    def test_repeated_receipts_use_first_matched_pair_once(self):
        _, first, policy = setup(population=True)
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
        _, a, policy = setup(population=True); b = copy.deepcopy(a)
        a["rows"][0]["adjusted_projection"] = None
        b["rows"][0]["raw_projection"] = None
        pairs, coverage = paired_forecasts([a, b], policy, {"test": "fixture"})
        self.assertFalse(pairs)
        self.assertEqual(coverage["excluded"]["missing_pair"], 2)

    def test_mixed_timestamp_precision_orders_actual_instants(self):
        _, older, policy = setup(population=True); newer = copy.deepcopy(older)
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
        _, p, policy = setup(population=True); replay = copy.deepcopy(p); replay["mode"] = "replay"
        late = copy.deepcopy(p); late["captured_at"] = p["rows"][0]["kickoff"]
        pairs, coverage = paired_forecasts([late, replay], policy, {"test": "fixture"})
        self.assertFalse(pairs)
        self.assertEqual(coverage["excluded"], {"non_live_receipt": 1, "not_pregame": 1})

    def test_duplicate_row_and_wrong_engine_fail(self):
        _, p, policy = setup(population=True)
        with self.assertRaises(ValueError): paired_forecasts([p], policy, {"wrong": "engine"})
        p["rows"].append(copy.deepcopy(p["rows"][0]))
        with self.assertRaises(ValueError): paired_forecasts([p], policy, {"test": "fixture"})

    def outcomes(self, entry, final=True):
        data, p, policy = setup(population=True)
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
        _, p, policy = setup(population=True); policy["registered_at"] = p["rows"][0]["kickoff"]
        pairs, coverage = paired_forecasts([p], policy, {"test": "fixture"})
        report = score(pairs, {}, coverage, policy)
        self.assertEqual(report["outcome_status"], {"excluded_pre_registration_game": 1})

    def test_corrections_keep_forecasts_and_prior_outcomes(self):
        _, p, policy = setup(population=True); pairs, coverage = paired_forecasts([p], policy, {"test": "fixture"})
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
        _, _, policy = setup(population=True)
        rows = [{"season": 2026, "week": w, "raw_projection": 5, "adjusted_projection": 4, "actual": 3,
                 "week_confirmed_complete": True} for w in range(1, 9)]
        self.assertIsNone(cluster_interval(rows[:7], policy)["interval"])
        self.assertEqual(cluster_interval(rows, policy)["interval"], [-1, -1])
        rows[-1]["week_confirmed_complete"] = False
        self.assertIsNone(cluster_interval(rows, policy)["interval"])

    def test_cancelled_post_flag_does_not_establish_a_final(self):
        data, p, policy = setup(population=True); data["games"][0].update(state="post", detail="Cancelled")
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
        _, baseline, policy = setup(population=True)
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
        result = {"schema_version": "forecast-outcomes-v1", "mode": "live",
                "collected_at": stamp(NOW + timedelta(hours=hour)), "source": source,
                "source_timestamp": None, "cache_path": "data/cache/fictional_2026_05.json",
                "cache_sha256": digest({row["player_id"]: entry}),
                "game_snapshot_sha256": digest({"kickoff": row["kickoff"], "state": row["game_state"]}),
                "rows": [row]}
        if complete:
            population = fictional_week_population()
            games = final_games(population)
            result.update(season=2026, week=5, games=games,
                          week_game_populations=[{"payload_sha256": digest(population), "payload": population}],
                          source_game_status=fictional_status(games, collected_at=result["collected_at"]))
        return result

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
        _, baseline, policy = setup(population=True)
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
        _, _, policy = setup(population=True)
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
        _, _, policy = setup(population=True)
        rows = self.rows()
        rows.append({**rows[-1], "week_confirmed_complete": False})
        result = cluster_interval(rows, policy)
        self.assertEqual(result["status"], "insufficient_completed_weeks")
        self.assertEqual(result["completed_weeks"], 7)
        self.assertIsNone(result["interval"])

    def test_reordered_input_has_identical_seeded_complete_week_interval(self):
        _, _, policy = setup(population=True)
        rows = self.rows()
        for i, row in enumerate(rows):
            row["adjusted_projection"] = 3 + i * i
        rows.extend([{**rows[0], "adjusted_projection": 9}, {**rows[-1], "adjusted_projection": 1}])
        self.assertEqual(cluster_interval(rows, policy), cluster_interval(list(reversed(rows)), policy))

    def test_all_rows_of_a_week_resample_as_one_cluster(self):
        _, _, policy = setup(population=True)
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
        _, _, policy = setup(population=True)
        rows = [{"season": 2026, "week": 1, "raw_projection": 0, "adjusted_projection": 0,
                 "actual": 0, "week_confirmed_complete": True} for _ in range(100)]
        rows.extend({"season": 2026, "week": w, "raw_projection": 0, "adjusted_projection": 10,
                     "actual": 0, "week_confirmed_complete": True} for w in range(2, 9))
        result = cluster_interval(rows, policy)
        self.assertEqual(result["resampled_outcomes"], 107)
        self.assertAlmostEqual(result["completed_week_mae_delta_clone_minus_raw"], 70 / 107)

    def test_empty_population_and_insufficient_weeks_keep_gate_and_counts(self):
        _, _, policy = setup(population=True)
        result = cluster_interval([], policy)
        self.assertEqual(result["status"], "insufficient_completed_weeks")
        self.assertEqual(result["completed_weeks"], 0)
        self.assertEqual(result["resampled_outcomes"], 0)
        self.assertIsNone(result["interval"])



class ParticipationContradictionRegressionTests(unittest.TestCase):
    def snapshot(self, *args, **kwargs):
        return OutcomePrecedenceRegressionTests().snapshot(*args, **kwargs)

    def chosen(self, *snapshots):
        return next(iter(latest_outcomes(snapshots).values()))

    def test_same_source_final_played_then_dnp_is_quarantined_in_any_input_order(self):
        for actual in (0, 3):
            with self.subTest(actual=actual):
                played, dnp = self.snapshot(actual), self.snapshot(status="dnp", hour=6)
                originals = copy.deepcopy([played, dnp])
                self.assertNotEqual(played["cache_sha256"], dnp["cache_sha256"])
                result = self.chosen(played, dnp)
                self.assertEqual(result, self.chosen(dnp, played))
                self.assertEqual(result["status"], "unresolved")
                self.assertIsNone(result["actual"])
                self.assertIsNone(result["outcome_snapshot_sha256"])
                self.assertTrue(result["outcome_conflict"])
                self.assertEqual([p["status"] for p in result["outcome_observations"]], ["resolved", "dnp"])
                self.assertEqual({p["outcome_snapshot_sha256"] for p in result["outcome_observations"]},
                                 {digest(played), digest(dnp)})
                self.assertEqual([played, dnp], originals)

    def test_same_source_final_dnp_then_played_also_requires_investigation(self):
        result = self.chosen(self.snapshot(status="dnp"), self.snapshot(3, hour=6))
        self.assertEqual(result["status"], "unresolved")
        self.assertTrue(result["outcome_conflict"])

    def test_new_source_timestamp_cannot_invalidate_earlier_played_evidence(self):
        played, dnp = self.snapshot(3), self.snapshot(status="dnp", hour=6)
        played["source_timestamp"], dnp["source_timestamp"] = (stamp(NOW + timedelta(hours=h)) for h in (4, 5))
        result = self.chosen(played, dnp)
        self.assertIsNone(result["actual"])
        self.assertTrue(result["outcome_conflict"])

    def test_participation_contradiction_does_not_auto_clear_on_another_version(self):
        records = [self.snapshot(3), self.snapshot(status="dnp", hour=6), self.snapshot(4, hour=7)]
        result = self.chosen(*records)
        self.assertEqual(result["status"], "unresolved")
        self.assertTrue(result["outcome_conflict"])
        self.assertEqual(len(result["outcome_observations"]), 3)

    def test_contradictory_participation_is_excluded_from_point_scores(self):
        _, baseline, policy = setup(population=True)
        pairs, coverage = paired_forecasts([baseline], policy, {"test": "fixture"})
        records = [self.snapshot(3), self.snapshot(status="dnp", hour=6)]
        result = score(pairs, latest_outcomes(records), coverage, policy)
        self.assertEqual(result["outcome_status"], {"unresolved": 1})
        self.assertEqual(result["categories"]["rec"]["raw_sleeper"]["n"], 0)
        self.assertIsNone(result["categories"]["rec"]["raw_sleeper"]["mae"])


class SavedWeekPopulationRegressionTests(unittest.TestCase):
    def world(self, week=5):
        board, baseline, policy = setup(population=True)
        board["week"], baseline["week"] = week, week
        for row in baseline["rows"]:
            row["week"] = week
        population = fictional_week_population(week)
        board["games"] = final_games(population)
        return {"board": board, "baseline": baseline, "policy": policy,
                "status": fictional_status(board["games"], week),
                "populations": [population]}

    def capture(self, world):
        from evidence import write
        pairs, coverage = paired_forecasts([world["baseline"]], world["policy"], {"test": "fixture"})
        week = world["board"]["week"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "output/data").mkdir(parents=True)
            (root / "data/cache").mkdir(parents=True)
            (root / "output/data/week.json").write_text(json.dumps(world["board"]))
            if world["status"] is not None:
                (root / "output/data/game-status.json").write_text(json.dumps({"weeks": {f"2026_{week:02d}": world["status"]}}))
            (root / f"data/cache/stats_2026_{week:02d}.json").write_text(json.dumps({
                "fictional-1": {"team": "AAA", "stats": {"gp": 1, "rec": 3}}}))
            for population in world["populations"]:
                write(root, "week_populations", population)
            path, = snapshot_outcomes(root, pairs, NOW + timedelta(hours=5))
            payload = read(path)
        # Re-read immutable outcome data without access to the now-removed files.
        selected = next(iter(latest_outcomes([payload]).values()))
        return payload, selected, pairs, coverage

    def test_full_sourced_frozen_population_and_reconciled_finals_complete_week(self):
        world = self.world()
        payload, result, pairs, coverage = self.capture(world)
        self.assertTrue(payload["rows"][0]["week_confirmed_complete"])
        self.assertTrue(result["week_confirmed_complete"])
        self.assertEqual(result["week_completion_snapshot_sha256"], [digest(payload)])
        self.assertEqual(result["actual"], 3)
        self.assertEqual(score(pairs, {next(iter(pairs)): result}, coverage, world["policy"])["categories"]["rec"]["raw_sleeper"]["n"], 1)

    def test_truncated_board_is_incomplete_even_when_all_saved_games_are_final(self):
        world = self.world()
        world["board"]["games"].pop()
        payload, result, _, _ = self.capture(world)
        self.assertFalse(payload["rows"][0]["week_confirmed_complete"])
        self.assertFalse(result["week_confirmed_complete"])
        self.assertEqual(result["actual"], 3)

    def test_truncated_board_and_status_cannot_certify_each_other(self):
        world = self.world()
        removed = world["board"]["games"].pop()
        world["status"]["games"].pop(removed["id"])
        _, result, _, _ = self.capture(world)
        self.assertFalse(result["week_confirmed_complete"])

    def test_missing_board_population_is_not_zero_or_complete(self):
        world = self.world()
        world["board"]["games"] = []
        _, result, _, _ = self.capture(world)
        self.assertFalse(result["week_confirmed_complete"])
        self.assertEqual(result["status"], "pending")
        self.assertIsNone(result["actual"])

    def test_absent_frozen_population_keeps_valid_point_result_but_not_completion(self):
        world = self.world()
        world["populations"] = []
        _, result, pairs, coverage = self.capture(world)
        self.assertFalse(result["week_confirmed_complete"])
        report = score(pairs, {next(iter(pairs)): result}, coverage, world["policy"])
        self.assertEqual(report["categories"]["rec"]["raw_sleeper"]["n"], 1)
        self.assertEqual(report["categories"]["rec"]["uncertainty"]["completed_weeks"], 0)

    def test_legacy_true_flag_without_population_proof_is_not_reused(self):
        payload = OutcomePrecedenceRegressionTests().snapshot(3)
        payload["rows"][0]["week_confirmed_complete"] = True
        before = copy.deepcopy(payload)
        result = next(iter(latest_outcomes([payload]).values()))
        self.assertFalse(result["week_confirmed_complete"])
        self.assertEqual(result["actual"], 3)
        self.assertTrue(result["outcome_observations"][0]["week_confirmed_complete"])
        self.assertEqual(payload, before)

    def test_unverified_or_wrong_period_population_does_not_establish_completion(self):
        variants = [
            {"source": ""}, {"population_scope": "OBSERVED_GAMES_ONLY"},
            {"source_document_sha256": None}, {"season": 2025}, {"week": 6},
            {"collected_at": stamp(NOW + timedelta(hours=3))},
            {"source_timestamp": stamp(NOW + timedelta(minutes=1))}, {"mode": "replay"}]
        for change in variants:
            with self.subTest(change=change):
                world = self.world()
                world["populations"][0].update(change)
                _, result, _, _ = self.capture(world)
                self.assertFalse(result["week_confirmed_complete"])

    def test_document_digest_empty_or_duplicate_expected_games_fail_closed(self):
        for alteration in ("digest", "empty", "duplicate", "period"):
            with self.subTest(alteration=alteration):
                world = self.world()
                p = world["populations"][0]
                if alteration == "digest":
                    p["source_document_sha256"] = "0" * 64
                elif alteration == "empty":
                    p["source_document"]["games"] = []
                elif alteration == "duplicate":
                    p["source_document"]["games"].append(copy.deepcopy(p["source_document"]["games"][0]))
                else:
                    p["source_document"]["week"] = 6
                if alteration != "digest":
                    p["source_document_sha256"] = digest(p["source_document"])
                _, result, _, _ = self.capture(world)
                self.assertFalse(result["week_confirmed_complete"])

    def test_disagreeing_frozen_populations_have_no_latest_or_digest_winner(self):
        world = self.world()
        other = copy.deepcopy(world["populations"][0])
        other["source_document"]["games"][1]["id"] = "fictional-conflicting-game"
        other["source_document_sha256"] = digest(other["source_document"])
        world["populations"].append(other)
        _, result, _, _ = self.capture(world)
        self.assertFalse(result["week_confirmed_complete"])

    def test_same_game_count_with_wrong_expected_ids_is_incomplete(self):
        world = self.world()
        p = world["populations"][0]
        p["source_document"]["games"][1]["id"] = "fictional-wrong-id"
        p["source_document_sha256"] = digest(p["source_document"])
        _, result, _, _ = self.capture(world)
        self.assertFalse(result["week_confirmed_complete"])

    def test_duplicate_board_id_does_not_collapse_into_a_complete_slate(self):
        world = self.world()
        world["board"]["games"].append(copy.deepcopy(world["board"]["games"][0]))
        _, result, _, _ = self.capture(world)
        self.assertFalse(result["week_confirmed_complete"])

    def test_missing_extra_or_mismatched_status_game_is_incomplete(self):
        for alteration in ("missing", "extra", "kickoff", "unavailable", "future_clock"):
            with self.subTest(alteration=alteration):
                world = self.world()
                raw = world["status"]["games"]
                if alteration == "missing":
                    raw.pop(world["board"]["games"][1]["id"])
                elif alteration == "extra":
                    raw["fictional-extra-game"] = copy.deepcopy(raw[world["board"]["games"][1]["id"]])
                elif alteration == "kickoff":
                    raw[world["board"]["games"][1]["id"]]["kickoff"] = stamp(NOW + timedelta(hours=3))
                elif alteration == "unavailable":
                    world["status"] = None
                else:
                    world["status"]["collected_at"] = stamp(NOW + timedelta(hours=6))
                _, result, _, _ = self.capture(world)
                self.assertFalse(result["week_confirmed_complete"])

    def test_changed_board_kickoff_does_not_rewrite_frozen_population(self):
        world = self.world()
        world["board"]["games"][1]["kickoff"] = stamp(NOW + timedelta(hours=3))
        world["status"]["games"][world["board"]["games"][1]["id"]]["kickoff"] = world["board"]["games"][1]["kickoff"]
        _, result, _, _ = self.capture(world)
        self.assertFalse(result["week_confirmed_complete"])

    def test_postponed_or_cancelled_game_does_not_complete_a_week(self):
        for detail, state in (("Postponed", "pre"), ("Postponed", "post"), ("Cancelled", "post")):
            with self.subTest(detail=detail, state=state):
                world = self.world()
                world["board"]["games"][1].update(state=state, detail=detail)
                # Even an inconsistent completed:true flag is insufficient.
                world["status"]["games"][world["board"]["games"][1]["id"]].update(state=state, detail=detail)
                _, result, _, _ = self.capture(world)
                self.assertFalse(result["week_confirmed_complete"])

    def test_nonfinal_or_future_final_game_cannot_establish_completion(self):
        for alteration in ("nonfinal", "future"):
            with self.subTest(alteration=alteration):
                world = self.world()
                raw = world["status"]["games"][world["board"]["games"][1]["id"]]
                if alteration == "nonfinal":
                    world["board"]["games"][1].update(state="pre", detail="Scheduled")
                    raw.update(state="pre", completed=False, detail="Scheduled")
                else:
                    kickoff = stamp(NOW + timedelta(hours=7))
                    world["board"]["games"][1]["kickoff"] = kickoff
                    raw["kickoff"] = kickoff
                    p = world["populations"][0]
                    p["source_document"]["games"][1]["kickoff"] = kickoff
                    p["source_document_sha256"] = digest(p["source_document"])
                _, result, _, _ = self.capture(world)
                self.assertFalse(result["week_confirmed_complete"])

    def test_eight_truncated_weeks_keep_interval_unavailable_and_point_n_eight(self):
        rows, pairs_all, outcomes_all = [], {}, {}
        for week in range(1, 9):
            world = self.world(week)
            removed = world["board"]["games"].pop()
            world["status"]["games"].pop(removed["id"])
            _, outcome, pairs, coverage = self.capture(world)
            key = next(iter(pairs))
            pairs_all.update(pairs)
            outcomes_all[key] = outcome
        report = score(pairs_all, outcomes_all, coverage, world["policy"])
        category = report["categories"]["rec"]
        self.assertEqual(category["raw_sleeper"]["n"], 8)
        self.assertEqual(category["uncertainty"]["completed_weeks"], 0)
        self.assertEqual(category["uncertainty"]["excluded_incomplete_outcomes"], 8)
        self.assertEqual(category["uncertainty"]["status"], "insufficient_completed_weeks")
        self.assertIsNone(category["uncertainty"]["interval"])

    def test_eight_fully_verified_weeks_still_open_the_original_interval_gate(self):
        rows = []
        for week in range(1, 9):
            world = self.world(week)
            _, outcome, _, _ = self.capture(world)
            rows.append({**outcome, "raw_projection": 5, "adjusted_projection": 4})
        result = cluster_interval(rows, world["policy"])
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["completed_weeks"], 8)
        self.assertEqual(result["resampled_outcomes"], 8)
        self.assertEqual(result["interval"], [-1, -1])

    def test_embedded_population_or_row_target_cannot_be_changed_to_reuse_completion(self):
        world = self.world()
        payload, _, _, _ = self.capture(world)
        # Supply the declared receipt format explicitly so the same corrupt-
        # receipt cases also exercise older readers lacking a population writer.
        payload["week_game_populations"] = [{"payload_sha256": digest(p), "payload": p}
                                             for p in world["populations"]]
        for alteration in ("digest", "row_game", "row_week", "row_kickoff"):
            with self.subTest(alteration=alteration):
                forged = copy.deepcopy(payload)
                if alteration == "digest":
                    forged["week_game_populations"][0]["payload_sha256"] = "0" * 64
                elif alteration == "row_game":
                    forged["rows"][0]["game_id"] = "fictional-unverified-game"
                elif alteration == "row_week":
                    forged["rows"][0]["week"] = 6
                else:
                    forged["rows"][0]["kickoff"] = stamp(NOW + timedelta(minutes=90))
                result = next(iter(latest_outcomes([forged]).values()))
                self.assertFalse(result["week_confirmed_complete"])


class AllPickableOutcomeTests(unittest.TestCase):
    def snapshot(self, stats, *, output=None, context=None):
        data, baseline, _ = setup()
        row = baseline["rows"][0]
        categories = json.loads((ROOT / "config/timing-policy.json").read_text())["categories"]
        pairs = {tuple([row["season"], row["week"], row["game_id"], row["player_id"], category]):
                 {**row, "category": category} for category in categories}
        data["games"][0].update(state="post", detail="Final")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "output/data").mkdir(parents=True)
        (root / "data/cache").mkdir(parents=True)
        (root / "output/data/week.json").write_text(json.dumps(data))
        (root / "data/cache/stats_2026_05.json").write_text(json.dumps({
            row["player_id"]: {"team": row["team"], "stats": {"gp": 1, **stats}}}))
        paths = snapshot_outcomes(root, pairs, NOW + timedelta(hours=5),
                                  output_root=output, derived_context=context)
        return read(paths[0]), paths, root, pairs

    def test_all_ten_categories_fresh_and_saved_component_contract(self):
        stats = {"pass_yd": 100, "pass_td": 1, "pass_cmp": 10, "pass_att": 15, "pass_int": 0,
                 "rush_yd": 10, "rush_att": 3, "rec": 2, "rec_yd": 20, "rush_rec_yd": 999}
        payload, _, _, _ = self.snapshot(stats)
        actual = {row["category"]: row["actual"] for row in payload["rows"]}
        self.assertEqual(actual, {**{k: stats[k] for k in stats if k != "rush_rec_yd"}, "rush_rec_yd": 30})
        saved = latest_outcomes([payload])
        self.assertEqual({key[-1]: value["actual"] for key, value in saved.items()}, actual)
        self.assertEqual({r["status"] for r in payload["rows"]}, {"resolved"})

    def test_combined_explicit_null_is_unresolved_not_zero(self):
        payload, _, _, _ = self.snapshot({"rush_yd": None, "rec_yd": 20})
        combined = next(r for r in payload["rows"] if r["category"] == "rush_rec_yd")
        self.assertEqual((combined["status"], combined["actual"]), ("unresolved", None))
        payload, _, _, _ = self.snapshot({"rec_yd": 20})
        self.assertEqual(next(r["actual"] for r in payload["rows"] if r["category"] == "rush_rec_yd"), 20)

    def test_null_does_not_mask_malformed_other_component(self):
        with self.assertRaises(ValueError):
            self.snapshot({"rush_yd": None, "rec_yd": "invalid"})

    def test_negative_yards_allowed_but_every_negative_count_rejected(self):
        payload, _, _, _ = self.snapshot({"rush_yd": -2, "rec_yd": -3})
        self.assertEqual(next(r["actual"] for r in payload["rows"] if r["category"] == "rush_rec_yd"), -5)
        for category in ("pass_td", "pass_cmp", "pass_att", "pass_int", "rush_att", "rec"):
            with self.subTest(category=category), self.assertRaises(ValueError):
                self.snapshot({category: -1})

    def test_bad_legacy_combined_value_not_reinterpreted_or_rewritten(self):
        payload, _, _, _ = self.snapshot({"rush_yd": 10, "rec_yd": 20})
        row = next(r for r in payload["rows"] if r["category"] == "rush_rec_yd")
        row["actual"] = 0
        before = copy.deepcopy(payload)
        with self.assertRaisesRegex(ValueError, "differs from its saved source"):
            latest_outcomes([payload])
        self.assertEqual(payload, before)

    def test_external_regrade_is_isolated_and_substantively_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = Path(directory)
            payload, paths, root, pairs = self.snapshot({"rec": 3}, output=sink,
                                                       context={"input_git_pin": "a" * 40})
            self.assertFalse((root / "data/outcomes").exists())
            self.assertTrue(paths[0].is_relative_to(sink / "data/outcomes_derived"))
            again = snapshot_outcomes(root, pairs, NOW + timedelta(hours=6), output_root=sink,
                                      derived_context={"input_git_pin": "a" * 40})
            self.assertEqual(again, paths)
            self.assertEqual(read(again[0]), payload)
            self.assertEqual(len(list((sink / "data/outcomes_derived").rglob("*.json.gz"))), 1)

    def test_old_pinned_regrade_cannot_supersede_saved_live_correction(self):
        with tempfile.TemporaryDirectory() as directory:
            derived, _, _, _ = self.snapshot({"rec": 3}, output=Path(directory),
                                             context={"input_git_pin": "a" * 40})
            live = copy.deepcopy(derived)
            live.pop("derived_context")
            live.pop("derived_substantive_sha256")
            live.update(source="existing_Sleeper_stats_cache_and_ESPN_final_game_snapshot",
                        collected_at=stamp(NOW + timedelta(hours=4)))
            for row in live["rows"]:
                if row["category"] == "rec":
                    row["actual"] = 5
                    row["stats_entry"]["stats"]["rec"] = 5
            result = latest_outcomes([derived, live])
            rec = next(value for key, value in result.items() if key[-1] == "rec")
            self.assertEqual(rec["status"], "unresolved")
            self.assertTrue(rec["outcome_conflict"])
            self.assertEqual(derived["rows"][0]["stats_entry"]["stats"]["rec"], 3)

    def test_external_sink_cannot_omit_derived_provenance(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            self.snapshot({}, output=Path(directory))

    def test_unsafe_external_sink_and_changed_substantive_id_rejected(self):
        payload, _, root, pairs = self.snapshot({"rec": 3})
        with self.assertRaisesRegex(ValueError, "outside"):
            snapshot_outcomes(root, pairs, NOW + timedelta(hours=5), output_root=root / "report",
                              derived_context={"input_git_pin": "a" * 40})
        with tempfile.TemporaryDirectory() as directory:
            paths = snapshot_outcomes(root, pairs, NOW + timedelta(hours=5), output_root=Path(directory),
                                      derived_context={"input_git_pin": "a" * 40})
            forged = read(paths[0])
            forged["derived_substantive_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "substantive"):
                latest_outcomes([forged])

    def test_offline_report_does_not_open_separate_population_files(self):
        from unittest.mock import patch
        _, _, root, pairs = self.snapshot({"rec": 3})
        with tempfile.TemporaryDirectory() as directory, patch("scorecard._read_populations",
                                                              side_effect=AssertionError("Unapproved source read")):
            paths = snapshot_outcomes(root, pairs, NOW + timedelta(hours=5), output_root=Path(directory),
                                      derived_context={"input_git_pin": "a" * 40}, include_populations=False)
            result = latest_outcomes([read(paths[0])])
            self.assertTrue(all(not r["week_confirmed_complete"] for r in result.values()))
            self.assertTrue(all(r["status"] == "resolved" for r in result.values()))


class SelectedOutcomeProvenanceRegressionTests(unittest.TestCase):
    def snapshot(self, *args, **kwargs):
        return OutcomePrecedenceRegressionTests().snapshot(*args, **kwargs)

    def test_selected_provenance_is_the_exact_numeric_record_not_first_observation(self):
        old, correction = self.snapshot(3), self.snapshot(5, hour=6)
        result = next(iter(latest_outcomes([correction, old]).values()))
        selected = result["selected_outcome_provenance"]
        self.assertEqual((result["actual"], selected["actual"]), (5, 5))
        self.assertEqual(selected["outcome_snapshot_sha256"], digest(correction))
        self.assertEqual(selected["outcome_row_sha256"], digest(correction["rows"][0]))
        self.assertEqual(result["selected_outcome_row_sha256"], digest(correction["rows"][0]))
        self.assertEqual(result["selected_outcome_provenance_sha256"], digest(selected))
        self.assertEqual(result["outcome_active_observations"], [digest(selected)])
        self.assertNotEqual(selected, result["outcome_observations"][0])
        self.assertTrue(result["outcome_revision"])
        self.assertEqual(result["outcome_source_mix"], "single_source")
        self.assertEqual(result, next(iter(latest_outcomes([old, correction]).values())))

    def test_agreeing_sources_and_conflicts_have_explicit_distinct_contracts(self):
        a, b = self.snapshot(3), self.snapshot(3, hour=6, source="fictional_stats_B")
        agreed = next(iter(latest_outcomes([b, a]).values()))
        self.assertEqual(agreed["outcome_source_mix"], "mixed_agreeing_sources")
        self.assertEqual(len(agreed["outcome_active_observations"]), 2)
        self.assertIsNotNone(agreed["selected_outcome_provenance"])
        b = self.snapshot(5, hour=6, source="fictional_stats_B")
        conflict = next(iter(latest_outcomes([a, b]).values()))
        self.assertEqual(conflict["outcome_source_mix"], "conflicting_sources")
        self.assertFalse(conflict["outcome_revision"])
        for field in ("selected_outcome_provenance", "selected_outcome_provenance_sha256",
                      "selected_outcome_row_sha256", "outcome_snapshot_sha256"):
            self.assertIsNone(conflict[field])
        self.assertEqual(conflict["status"], "unresolved")


class OutcomeIdentityBindingRegressionTests(unittest.TestCase):
    def saved(self, *, team="AAA", opponent="BBB", clubs=True):
        payload = OutcomePrecedenceRegressionTests().snapshot(3)
        row = payload["rows"][0]
        row["stats_entry"].update(team=team, opp=opponent)
        payload["games"] = [{"id": row["game_id"], "kickoff": row["kickoff"],
                             "state": "post", "detail": "Final"}]
        if clubs:
            payload["games"][0].update(home="AAA", away="BBB")
        return payload

    def fresh(self, payload):
        from unittest.mock import patch
        row = payload["rows"][0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "output/data").mkdir(parents=True)
            (root / "data/cache").mkdir(parents=True)
            (root / "output/data/week.json").write_text(json.dumps({"season": 2026, "week": 5,
                                                                     "games": payload["games"]}))
            (root / "data/cache/stats_2026_05.json").write_text(json.dumps({item["player_id"]: item["stats_entry"]
                                                                            for item in payload["rows"]}))
            with patch("requests.sessions.Session.request", side_effect=AssertionError("HTTP forbidden")):
                path, = snapshot_outcomes(root, {tuple(item[k] for k in
                    ("season", "week", "game_id", "player_id", "category")): item for item in payload["rows"]}, NOW + timedelta(hours=5),
                                          include_populations=False)
            return read(path)

    def test_fresh_and_saved_present_opponent_or_club_contradictions_are_quarantined(self):
        for alteration in ("opponent", "clubs", "statistics_team"):
            payload = self.saved()
            if alteration == "opponent":
                payload["rows"][0]["stats_entry"]["opp"] = "WRONG"
            elif alteration == "clubs":
                payload["games"][0].update(home="CCC", away="DDD")
            else:
                payload["rows"][0]["stats_entry"]["team"] = "WRONG"
            before = copy.deepcopy(payload)
            for source in (payload, self.fresh(payload)):
                with self.subTest(alteration=alteration, source=source.get("source")):
                    result = next(iter(latest_outcomes([source]).values()))
                    self.assertEqual((result["status"], result["actual"]), ("unresolved", None))
                    self.assertEqual(result["outcome_identity_status"], "quarantined")
                    self.assertFalse(result["week_confirmed_complete"])
            self.assertEqual(payload, before)

    def test_complete_and_partial_legacy_bindings_remain_distinct_valid_controls(self):
        full = next(iter(latest_outcomes([self.saved()]).values()))
        self.assertEqual((full["actual"], full["outcome_identity_status"]), (3, "bound_to_recorded_game"))
        legacy = self.saved(clubs=False)
        legacy["rows"][0]["stats_entry"].pop("opp")
        result = next(iter(latest_outcomes([legacy]).values()))
        self.assertEqual((result["actual"], result["outcome_identity_status"]), (3, "partial_legacy"))
        self.assertIn("recorded_club_mapping_incomplete", result["outcome_identity_reasons"])

    def test_malformed_present_clubs_and_duplicate_game_identity_cannot_qualify(self):
        for clubs in (("AAA", "AAA"), (0, "BBB"), ("", "BBB")):
            payload = self.saved()
            payload["games"][0].update(home=clubs[0], away=clubs[1])
            with self.subTest(clubs=clubs):
                result = next(iter(latest_outcomes([payload]).values()))
                self.assertEqual((result["status"], result["actual"]), ("unresolved", None))
                self.assertEqual(result["outcome_identity_status"], "quarantined")
        payload = self.saved()
        payload["games"].append(copy.deepcopy(payload["games"][0]))
        result = next(iter(latest_outcomes([payload]).values()))
        self.assertEqual(result["outcome_identity_status"], "quarantined")

    def test_quarantined_observation_does_not_override_independent_valid_result(self):
        good, bad = self.saved(), self.saved(opponent="WRONG")
        bad["collected_at"] = stamp(NOW + timedelta(hours=6))
        result = next(iter(latest_outcomes([bad, good]).values()))
        self.assertEqual((result["status"], result["actual"]), ("resolved", 3))
        self.assertEqual(len(result["outcome_observations"]), 2)
        self.assertEqual(sum(p["outcome_identity_status"] == "quarantined" for p in result["outcome_observations"]), 1)
        self.assertEqual(len(result["outcome_active_observations"]), 1)

    def test_quarantine_is_per_observation_and_does_not_remove_valid_sibling_points(self):
        payload = self.saved(opponent="WRONG")
        sibling = copy.deepcopy(payload["rows"][0])
        sibling["player_id"] = "fictional-unrelated-valid-player"
        sibling["stats_entry"]["opp"] = "BBB"
        payload["rows"].append(sibling)
        for source in (payload, self.fresh(payload)):
            outcomes = latest_outcomes([source])
            valid = next(value for key, value in outcomes.items() if key[3] == sibling["player_id"])
            bad = next(value for key, value in outcomes.items() if key[3] != sibling["player_id"])
            self.assertEqual((valid["status"], valid["actual"]), ("resolved", 3))
            self.assertEqual((bad["status"], bad["actual"]), ("unresolved", None))

    def test_identity_quarantine_does_not_suppress_unrelated_malformed_statistics(self):
        payload = self.saved(opponent="WRONG")
        payload["rows"][0]["stats_entry"]["stats"]["rec"] = "malformed"
        with self.assertRaises(ValueError):
            latest_outcomes([payload])
        with self.assertRaises(ValueError):
            self.fresh(payload)


class AdditionalOutcomePairsRegressionTests(unittest.TestCase):
    def fixture(self, root):
        from evidence import write
        board, baseline, policy = setup()
        base = baseline["rows"][0]
        categories = json.loads((ROOT / "config/timing-policy.json").read_text())["categories"]
        baseline["rows"] = [{**base, "category": category} for category in categories]
        baseline.update(season=board["season"], week=board["week"])
        board["games"][0].update(state="post", detail="Final")
        (root / "config").mkdir()
        (root / "output/data").mkdir(parents=True)
        (root / "data/cache").mkdir(parents=True)
        (root / "config/evaluation-policy.json").write_text(json.dumps(policy))
        (root / "output/data/week.json").write_text(json.dumps(board))
        (root / "data/cache/stats_2026_05.json").write_text(json.dumps({base["player_id"]: {
            "team": "AAA", "opp": "BBB", "stats": {"gp": 1, **{category: 1 for category in categories}}}}))
        write(root, "forward", baseline)
        return {tuple(row[k] for k in ("season", "week", "game_id", "player_id", "category")): row
                for row in baseline["rows"]}

    def test_all_ten_extra_path_preserves_primary_metrics_and_cannot_qualify_whole_week(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            additional = self.fixture(root)
            with patch("scorecard.engine_hashes", return_value={"test": "fixture"}):
                primary, primary_paths = build_scorecard(root, NOW + timedelta(hours=5))
                expanded, paths = build_scorecard(root, NOW + timedelta(hours=5), additional_outcome_pairs=additional)
            self.assertEqual(expanded["categories"], primary["categories"])
            self.assertEqual(expanded["coverage"], primary["coverage"])
            self.assertEqual(len(paths), len(primary_paths) + 1)
            extra = read(paths[-1])
            self.assertEqual(len(extra["rows"]), 7)
            self.assertTrue(all(row["category"] not in ("rec", "rush_att", "pass_yd") for row in extra["rows"]))
            self.assertEqual(extra["week_population_read_errors"], [{"error_type": "POPULATION_NOT_CONSUMED_BY_OFFLINE_REPORT"}])
            self.assertFalse(any(row["week_confirmed_complete"] for row in extra["rows"]))
            outcomes = latest_outcomes([read(path) for path in (root / "data/outcomes").rglob("*.json.gz")])
            self.assertEqual(len(outcomes), 10)

    def test_unsaved_or_conflicting_additional_identity_is_rejected(self):
        from unittest.mock import patch
        for change in ("player", "team", "kickoff", "key", "category"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                additional = self.fixture(root)
                key, row = next(iter(additional.items()))
                row = dict(row)
                if change == "player": row["player_id"] = "not-original"
                elif change == "team": row["team"] = "WRONG"
                elif change == "kickoff": row["kickoff"] = stamp(NOW + timedelta(days=5))
                elif change == "category": row["category"] = "unsupported"
                if change != "key": key = tuple(row[k] for k in ("season", "week", "game_id", "player_id", "category"))
                else: key = (2026, 5, "wrong", row["player_id"], row["category"])
                with patch("scorecard.engine_hashes", return_value={"test": "fixture"}), self.assertRaises(ValueError):
                    build_scorecard(root, NOW + timedelta(hours=5), additional_outcome_pairs={key: row})


def descriptive_fixture():
    """Native fictional pregame values plus the retained offensive scoring."""
    from reliability import engine_hashes
    import scoring
    data, _ = fixture()
    player = data["players"][0]
    player.update(opp="BBB", proj={"rec": 4.8, "rec_yd": 10, "rush_td": .1, "rec_td": .56}, proj_ppr=10.1)
    raw = scoring.ppr_points(player["proj"])
    player["props"].extend([
        {"key": "fpts", "proj": raw, "adj": 9.5, "line": 9.5, "line_from": "ours", "lean": None},
        {"key": "anytime_td", "proj": .66, "adj": None, "line": .5, "line_from": "ours", "lean": None,
         "td_chance": .483},
    ])
    data["scoring"] = dict(scoring.PPR)
    hashes = engine_hashes(ROOT)
    payload = make_payload(data, NOW, hashes, "live")
    return data, payload, hashes


class DescriptiveCategoryContracts(unittest.TestCase):
    def pipeline(self, stats=None, *, entry=None, final=True):
        from scorecard import descriptive_contract, descriptive_forecasts
        data, payload, hashes = descriptive_fixture()
        first, pairs, coverage = descriptive_forecasts([payload], hashes, NOW)
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        root, output = Path(d.name) / "input", Path(d.name) / "derived"
        (root / "output/data").mkdir(parents=True); (root / "data/cache").mkdir(parents=True)
        board = copy.deepcopy(data)
        if final:
            board["games"][0].update(state="post", detail="Final")
        (root / "output/data/week.json").write_text(json.dumps(board))
        if entry is None and stats is not None:
            entry = {"team": "AAA", "opp": "BBB", "pos": "WR", "stats": stats}
        cache = {} if entry is None else {"fictional-1": entry}
        (root / "data/cache/stats_2026_05.json").write_text(json.dumps(cache))
        extra = {key: row for key, row in first.items() if row["category"] in ("fpts", "anytime_td")}
        paths = snapshot_outcomes(root, extra, NOW + timedelta(hours=5), output_root=output,
            derived_context={"test": "FICTIONAL_SAVED_CACHE_ONLY"}, include_populations=False,
            statistic_contract=descriptive_contract())
        payload = read(paths[0])
        return root, output, data, first, pairs, payload, latest_outcomes([payload]), coverage

    def test_fractional_negative_ppr_survives_fresh_saved_consumption(self):
        from scorecard import DERIVED_STAT_SCHEMA
        _, _, _, _, _, payload, outcomes, _ = self.pipeline(
            {"gp": 1, "pass_yd": 1, "rec": 1, "rec_yd": -2, "fum_lost": 1, "fpts": 999})
        ppr = next(v for k, v in outcomes.items() if k[-1] == "fpts")
        self.assertEqual(payload["schema_version"], DERIVED_STAT_SCHEMA)
        self.assertEqual((ppr["status"], ppr["actual"]), ("resolved", -1.16))
        self.assertEqual(ppr["outcome_identity_status"], "bound_to_recorded_game")
        self.assertFalse(ppr["week_confirmed_complete"])
        self.assertEqual(ppr["selected_outcome_provenance"]["outcome_schema"], DERIVED_STAT_SCHEMA)

    def test_sparse_zero_absent_null_and_dnp_are_distinct(self):
        cases = [({"gp": 1}, None, "resolved", 0), (None, None, "unresolved", None),
                 ({"pts_ppr": 0}, None, "unresolved", None),
                 ({"gp": 1, "rec": None}, None, "unresolved", None),
                 (None, {"participation_status": "dnp", "participation_source": "fictional"}, "dnp", None),
                 (None, {"stats": {"gp": 1}, "participation_status": "dnp", "participation_source": "fictional"}, "unresolved", None)]
        for stats, entry, status, actual in cases:
            with self.subTest(stats=stats, entry=entry):
                *_, outcomes, _ = self.pipeline(stats, entry=entry)
                ppr = next(v for k, v in outcomes.items() if k[-1] == "fpts")
                self.assertEqual((ppr["status"], ppr["actual"]), (status, actual))

    def test_pending_game_never_consumes_statistics_as_final(self):
        *_, outcomes, _ = self.pipeline({"gp": 1, "rec": 1}, final=False)
        self.assertTrue(all(r["status"] == "pending" and r["actual"] is None for r in outcomes.values()))

    def test_td_event_is_rushing_plus_receiving_not_passing_or_returns(self):
        for stats, expected in [({"gp": 1, "pass_td": 4, "st_td": 1, "fum_rec_td": 1}, 0),
                                ({"gp": 1, "rush_td": 1}, 1), ({"gp": 1, "rec_td": 1}, 1),
                                ({"gp": 1, "rush_td": 1, "rec_td": 2}, 3)]:
            with self.subTest(stats=stats):
                *_, outcomes, _ = self.pipeline(stats)
                td = next(v for k, v in outcomes.items() if k[-1] == "anytime_td")
                self.assertEqual(td["actual"], expected)
        *_, outcomes, _ = self.pipeline({"gp": 1, "rush_td": 1, "rec_td": None})
        self.assertEqual(next(v for k, v in outcomes.items() if k[-1] == "anytime_td")["status"], "unresolved")

    def test_component_validation_including_null_with_malformed_sibling(self):
        from scorecard import descriptive_statistic
        for key, value in [("rec", True), ("rec_td", -1), ("rush_td", .5), ("pass_yd", float("nan")), ("fum_lost", "1")]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                descriptive_statistic("fpts", {"rec_yd": None, key: value})
        self.assertEqual(descriptive_statistic("fpts", {"gp": 1, "idp_fum_rec": 1, "fum_rec_td": 1}), 0)
        self.assertEqual(descriptive_statistic("fpts", {"gp": 1, "fum_rec_td": 1}), 6)

    def test_saved_contract_position_source_component_and_actual_tampering_fail(self):
        *_, saved, _, _ = self.pipeline({"gp": 1, "rec": 1})
        # Rehash after corruption, as required for semantic rather than envelope checks.
        for mutation in (lambda p: p["statistic_contract"].update(scoring_sha256="0" * 64),
                         lambda p: p["rows"][0].update(position="K"),
                         lambda p: p["rows"][0].update(actual=123),
                         lambda p: p["rows"][0].update(stats_entry=None)):
            broken = copy.deepcopy(saved); mutation(broken)
            broken["derived_substantive_sha256"] = digest({k: v for k, v in broken.items() if k not in ("collected_at", "derived_substantive_sha256")})
            with self.assertRaises(ValueError): latest_outcomes([broken])

    def test_saved_identity_and_changed_schedule_remain_quarantined(self):
        *_, saved, _, _ = self.pipeline({"gp": 1, "rec": 1})
        for mutation in (lambda p: p["rows"][0]["stats_entry"].update(opp="WRONG"),
                         lambda p: p["rows"][0].update(forecast_kickoff=stamp(NOW + timedelta(hours=2)))):
            changed = copy.deepcopy(saved); mutation(changed)
            changed["derived_substantive_sha256"] = digest({k: v for k, v in changed.items() if k not in ("collected_at", "derived_substantive_sha256")})
            result = latest_outcomes([changed])
            affected = result[tuple(changed["rows"][0][k] for k in ("season", "week", "game_id", "player_id", "category"))]
            self.assertEqual(affected["status"], "unresolved")
            self.assertEqual(affected["outcome_identity_status"], "quarantined")

    def test_typed_period_and_source_position_are_bound(self):
        *_, saved, _, _ = self.pipeline({"gp": 1, "rec": 1})
        bad = copy.deepcopy(saved); bad.update(season=2025, week=1)
        bad["derived_substantive_sha256"] = digest({k: v for k, v in bad.items() if k not in ("collected_at", "derived_substantive_sha256")})
        with self.assertRaisesRegex(ValueError, "period"):
            latest_outcomes([bad])
        for position in ("K", "DEF", "QB", None):
            changed = copy.deepcopy(saved)
            for row in changed["rows"]: row["stats_entry"]["pos"] = position
            changed["derived_substantive_sha256"] = digest({k: v for k, v in changed.items() if k not in ("collected_at", "derived_substantive_sha256")})
            result = latest_outcomes([changed])
            self.assertTrue(all(r["status"] == ("resolved" if position is None else "unresolved") for r in result.values()))
            self.assertTrue(all(r["outcome_identity_status"] == ("partial_legacy" if position is None else "quarantined") for r in result.values()))

    def test_legacy_unsupported_categories_do_not_gain_new_meaning(self):
        *_, saved, _, _ = self.pipeline({"gp": 1, "rec": 1})
        legacy = copy.deepcopy(saved); legacy.update(schema_version="forecast-outcomes-v1")
        legacy.pop("statistic_contract"); legacy.pop("derived_context"); legacy.pop("derived_substantive_sha256")
        result = latest_outcomes([legacy])
        self.assertTrue(all(r["status"] == "unresolved" and r["actual"] is None for r in result.values()))
        self.assertTrue(all(r["reason"] == "unsupported_legacy_statistic_contract" for r in result.values()))

    def test_descriptive_snapshots_cannot_write_native_or_certify_whole_week(self):
        from scorecard import descriptive_contract
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                snapshot_outcomes(Path(d), {}, NOW, statistic_contract=descriptive_contract())

    def test_corrections_agreement_conflicts_and_new_missing_keep_shared_precedence(self):
        *_, derived, _, _ = self.pipeline({"gp": 1, "rec": 1})
        a = copy.deepcopy(derived)
        a.pop("derived_context"); a.pop("derived_substantive_sha256")
        a["source"] = "FICTIONAL_VERSIONED_PROVIDER_A"
        b = copy.deepcopy(a); b["collected_at"] = stamp(NOW + timedelta(hours=6))
        for row in b["rows"]:
            row["stats_entry"]["stats"]["rec"] = 2
            if row["category"] == "fpts": row["actual"] = 2
        b["cache_sha256"] = digest({"fictional": "version2"})
        selected = latest_outcomes([a, b, a])
        ppr = next(v for k, v in selected.items() if k[-1] == "fpts")
        self.assertEqual(ppr["actual"], 2)
        self.assertTrue(ppr["outcome_revision"])
        pending = copy.deepcopy(b); pending["collected_at"] = stamp(NOW + timedelta(hours=7))
        for row in pending["rows"]: row.update(status="unresolved", actual=None, stats_entry=None)
        self.assertEqual(next(v for k, v in latest_outcomes([a, b, pending]).items() if k[-1] == "fpts")["actual"], 2)
        agreeing = copy.deepcopy(b); agreeing["source"] = "FICTIONAL_PROVIDER_B"
        self.assertEqual(next(v for k, v in latest_outcomes([b, agreeing]).items() if k[-1] == "fpts")["outcome_source_mix"], "mixed_agreeing_sources")
        disagreeing = copy.deepcopy(a); disagreeing["source"] = "FICTIONAL_PROVIDER_B"
        conflict = next(v for k, v in latest_outcomes([b, disagreeing]).items() if k[-1] == "fpts")
        self.assertEqual((conflict["status"], conflict["actual"]), ("unresolved", None))
        with_derived = next(v for k, v in latest_outcomes([derived, b]).items() if k[-1] == "fpts")
        self.assertEqual(with_derived["status"], "unresolved", "a new clock cannot replace another pinned derivation")


class DescriptiveForecastAndProbabilityTests(unittest.TestCase):
    def test_same_receipt_pair_selection_duplicate_clocks_and_kickoff(self):
        from scorecard import descriptive_forecasts
        _, first, hashes = descriptive_fixture()
        before = copy.deepcopy(first)
        second = copy.deepcopy(first); second["captured_at"] = stamp(NOW + timedelta(minutes=1))
        target = next(r for r in first["rows"] if r["category"] == "rec")
        target["raw_projection"] = None
        next(r for r in second["rows"] if r["category"] == "rec")["adjusted_projection"] = None
        population, pairs, cov = descriptive_forecasts([second, first, first], hashes, NOW + timedelta(minutes=2))
        key = tuple(target[k] for k in ("season", "week", "game_id", "player_id", "category"))
        self.assertNotIn(key, pairs)
        self.assertIn(key, population)
        self.assertEqual(cov["duplicate_receipts"], 1)
        third = copy.deepcopy(before); third["captured_at"] = stamp(NOW + timedelta(minutes=2))
        _, pairs, _ = descriptive_forecasts([first, second, third], hashes, NOW + timedelta(minutes=3))
        self.assertEqual(pairs[key]["captured_at"], third["captured_at"])
        late = copy.deepcopy(before); late["captured_at"] = late["rows"][0]["kickoff"]
        self.assertFalse(descriptive_forecasts([late], hashes, NOW + timedelta(hours=2))[0])
        self.assertFalse(descriptive_forecasts([third], hashes, NOW)[0])
        duplicate = copy.deepcopy(before); duplicate["rows"].append(copy.deepcopy(duplicate["rows"][0]))
        with self.assertRaises(ValueError): descriptive_forecasts([duplicate], hashes, NOW)

    def test_no_lean_reference_values_and_positions(self):
        from scorecard import descriptive_forecasts
        _, receipt, hashes = descriptive_fixture()
        rows, pairs, _ = descriptive_forecasts([receipt], hashes, NOW)
        self.assertEqual(len(rows), 3); self.assertEqual(len(pairs), 2)
        bad = copy.deepcopy(receipt)
        for row in bad["rows"]: row["position"] = "DEF"
        self.assertFalse(descriptive_forecasts([bad], hashes, NOW)[0])
        invalid_early = copy.deepcopy(receipt)
        for r in invalid_early["rows"]: r["position"] = "K"
        later = copy.deepcopy(receipt); later["captured_at"] = stamp(NOW + timedelta(minutes=1))
        valid_first, valid_pairs, _ = descriptive_forecasts([invalid_early, later], hashes, NOW + timedelta(minutes=2))
        self.assertEqual(len(valid_pairs), 2)
        self.assertTrue(all(r["baseline_payload_sha256"] == digest(later) for r in valid_pairs.values()))
        wrong = copy.deepcopy(receipt); wrong["forecast_generated_at"] = stamp(NOW + timedelta(seconds=1))
        with self.assertRaises(ValueError): descriptive_forecasts([wrong], hashes, NOW + timedelta(minutes=1))

    def test_original_board_vs_rederived_probability_and_ppr_roles(self):
        from scorecard import descriptive_forecasts, evaluate_descriptive
        board, receipt, hashes = descriptive_fixture()
        population, pairs, _ = descriptive_forecasts([receipt], hashes, NOW)
        original = copy.deepcopy(board)
        actuals = {k: {"status": "resolved", "actual": 0, "kickoff": row["kickoff"], "team": row["team"]} for k, row in population.items()}
        no_board = evaluate_descriptive(population, pairs, actuals, actuals)
        with_board = evaluate_descriptive(population, pairs, actuals, actuals, original_boards=[{"document": board}])
        a, b = no_board["td_rows"][0], with_board["td_rows"][0]
        self.assertEqual((a["probability"], b["probability"]), (.483, .483))
        self.assertTrue(a["probability_provenance"].startswith("rederived"))
        self.assertEqual(b["probability_provenance"], "originally_recorded_probability")
        self.assertIsNone(b["adjusted_probability"])
        ppr = next(r for r in with_board["paired_rows"] if r["category"] == "fpts")
        self.assertEqual(ppr["provider_ppr"], 10.1)
        self.assertNotEqual(ppr["provider_ppr"], ppr["raw_projection"])
        self.assertEqual(board, original)

    def test_original_board_contract_and_selected_outcome_team_cannot_drift(self):
        from scorecard import descriptive_forecasts, evaluate_descriptive
        board, receipt, hashes = descriptive_fixture()
        population, pairs, _ = descriptive_forecasts([receipt], hashes, NOW)
        for field, value in (("line", 999), ("line_from", "other"), ("lean", "under"),
                             ("top_over", True), ("matchup_factor", 9)):
            changed = copy.deepcopy(population)
            for r in changed.values(): r[field] = value
            result = evaluate_descriptive(changed, {}, {}, {}, original_boards=[{"document": board}])
            self.assertEqual(result["td_rows"][0]["original_board"]["status"], "invalid_exact_original_board")
            self.assertIsNone(result["td_rows"][0]["probability"])
        actuals = {k: {"status": "resolved", "actual": 0, "team": "WRONG", "kickoff": r["kickoff"]} for k, r in population.items()}
        result = evaluate_descriptive(population, pairs, actuals, actuals)
        self.assertTrue(all(r["evaluation_status"] == "unresolved" and r["actual"] is None for r in result["rows"]))
        self.assertEqual(result["categories"]["rec"]["paired"]["raw"]["n"], 0)

    def test_wrong_original_board_cannot_supply_saved_comparator(self):
        from scorecard import descriptive_forecasts, evaluate_descriptive
        board, receipt, hashes = descriptive_fixture()
        population, pairs, _ = descriptive_forecasts([receipt], hashes, NOW)
        for change in ("clock", "identity", "forecast", "scoring"):
            bad = copy.deepcopy(board)
            if change == "clock": bad["generated_at"] = stamp(NOW + timedelta(minutes=1))
            elif change == "identity": bad["players"][0]["team"] = "WRONG"
            elif change == "forecast": bad["players"][0]["props"][-1]["td_chance"] = .9
            else: bad["scoring"]["rec"] = .5
            # A later/altered complete board's new digest cannot match this receipt.
            result = evaluate_descriptive(population, pairs, {}, {}, original_boards=[{"document": bad}])
            self.assertEqual(result["td_rows"][0]["original_board"]["status"], "missing_exact_original_board")
            self.assertTrue(result["td_rows"][0]["probability_provenance"].startswith("rederived"))
        forged = copy.deepcopy(board); forged["players"][0]["team"] = "WRONG"
        for row in population.values(): row["baseline_input_sha256"] = digest(forged)
        result = evaluate_descriptive(population, pairs, {}, {}, original_boards=[{"document": forged}])
        self.assertIsNone(result["td_rows"][0]["probability"])
        self.assertEqual(result["td_rows"][0]["original_board"]["status"], "invalid_exact_original_board")

    def test_duplicate_original_identities_and_unknown_formula_engine_rejected(self):
        from scorecard import original_board_index, descriptive_forecasts
        board, receipt, hashes = descriptive_fixture()
        for kind in ("players", "games"):
            bad = copy.deepcopy(board); bad[kind].append(copy.deepcopy(bad[kind][0]))
            with self.assertRaises(ValueError): original_board_index([{"document": bad}])
        bad = copy.deepcopy(board); bad["players"][0]["props"].append(copy.deepcopy(bad["players"][0]["props"][0]))
        with self.assertRaises(ValueError): original_board_index([{"document": bad}])
        changed = dict(hashes, **{"pull/scoring.py": "0" * 64})
        receipt.update(engine_files=changed, engine_sha256=digest(changed))
        with self.assertRaises(ValueError): descriptive_forecasts([receipt], changed, NOW)

    def test_binary_extreme_losses_are_json_safe_and_calibration_includes_one(self):
        from scorecard import probability_scores, _td_metrics
        from reliability import canonical
        rows = []
        for p, y in ((0, 0), (1, 1), (0, 1), (1, 0)):
            value = probability_scores(p, y)
            if p == y:
                self.assertEqual((value["brier"], value["log_loss"]), (0, 0))
            else:
                self.assertIsNone(value["log_loss"])
                self.assertEqual(value["log_loss_state"], "positive_infinity")
            rows.append({"season": 2026, "week": 6, "game_id": "fictional", "player_id": str(len(rows)),
                         "evaluation_status": "resolved", "probability": p, "actual_event": y,
                         "raw_projection": p, "actual": y, "probability_provenance": "fictional", **value})
        report = _td_metrics(rows)
        self.assertEqual(report["infinite_log_loss_count"], 2)
        self.assertEqual(report["log_loss_state"], "positive_infinity")
        self.assertIsNone(report["log_loss"])
        self.assertEqual(sum(b["n"] for b in report["calibration"]), 4)
        self.assertEqual(report["calibration"][-1]["n"], 2)
        self.assertEqual(json.loads(canonical(report))["infinite_log_loss_count"], 2)


if __name__ == "__main__":
    unittest.main()
