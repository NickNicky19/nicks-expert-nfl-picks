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


if __name__ == "__main__":
    unittest.main()
