"""Fictional replay: recorded builder through saved forecasts and final scoring.

No network, remote writes, public release or real prediction-performance claims.
"""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
import build
import build_recorded
import verify
from evidence import read
from phase2_capture import probability_report, run_capture
from reliability import ENGINE_PATHS, atomic_json, digest, load_json, stamp
from scorecard import build_scorecard
from test_offers import offer_fixture
from test_reliability import NOW
from test_scorecard import setup


class ReplayClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def prepare(root, source_unavailable=False):
    for path in ENGINE_PATHS:
        target = root / path; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / path, target)
    (root / "config").mkdir()
    for path in ("phase2.json", "release-mode.json", "sleeper-rules-provenance.json"):
        shutil.copyfile(ROOT / "config" / path, root / "config" / path)
    data, _, policy = setup()
    atomic_json(root / "config/evaluation-policy.json", policy)
    player, prop = data["players"][0], data["players"][0]["props"][0]
    player.update(opp="BBB", snap_share=.8, games_this_season=2)
    prop.update(mf=1, mf_n=0, adj=prop["proj"])
    data["picks"]["over"][0]["adj"] = prop["proj"]
    _, observed, meta, _ = offer_fixture()
    source_rows = [{"player_id": "fictional-1", **meta["fictional-1"], "stats": {"rec": 4.8}}]
    def responses(url, *args, **kwargs):
        if "/projections/nfl/" in url:
            rows = copy.deepcopy(source_rows)
            if url.endswith("/6"):
                rows[0]["game_id"] = "future-game-that-must-not-overwrite-current-mapping"
            return rows
        if source_unavailable:
            raise TimeoutError("fictional unavailable source")
        return observed["markets"]
    def fake_build():
        build.sources.get_json("https://api.sleeper.app/projections/nfl/2026/5")
        try:
            build.sources.get_json("https://api.sleeper.app/lines/available")
        except TimeoutError:
            pass  # Mirrors the retained builder's explicit fallback, recorded above.
        build.Matchups({4: {"fictional-1": {"opp": "CCC", "stats": {"gp": 1, "rec": 3}}}}, {"fictional-1": "WR"})
        build.sources.get_json("https://api.sleeper.app/projections/nfl/2026/6")
        atomic_json(root / "output/data/week.json", data)
        atomic_json(root / "output/data/meta.json", {k: data[k] for k in ("season", "week", "generated_at")})
        atomic_json(root / "data/cache/stats_2026_05.json", {"fictional-1": {"team": "AAA", "stats": {"gp": 1, "rec": 5}}})
    with patch.object(build.sources, "get_json", side_effect=responses), patch.object(build_recorded, "datetime", ReplayClock):
        build_recorded.record_build(root, run=fake_build)
    return data, policy


class PipelineTests(unittest.TestCase):
    def test_full_replay_then_final_then_correction_preserves_all_forecasts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, policy = prepare(root)
            before = (root / "output/data/week.json").read_bytes()
            proof = load_json(root / "output/data/matchup-proof.json")
            with patch.object(verify, "ROOT", root):
                verify.problems.clear(); verify.check_point_in_time(data, proof); verify.check_shape(data)
                self.assertEqual(verify.problems, [])
            report, health = run_capture(root, mode="replay", replay_at=stamp(NOW))
            self.assertEqual(report["evidence"], "REPLAY_TEST_NOT_PROSPECTIVE")
            self.assertEqual(report["outcome_status"], {"pending": 1})
            self.assertEqual(report["offers"]["coverage"], {"complete_selection_capture": 1, "no_offer": 1})
            self.assertEqual(report["shadow"]["unique_matched_opportunities"], 1)
            self.assertEqual((root / "output/data/week.json").read_bytes(), before)
            self.assertFalse((root / "output/data/forecast-scorecard.json").exists())
            baseline = root / health["receipt"]
            shadow = root / health["phase2"]["shadow_receipt"]
            forecast_bytes = baseline.read_bytes(), shadow.read_bytes()
            again, retry = run_capture(root, mode="replay", replay_at=stamp(NOW + timedelta(minutes=1)))
            self.assertFalse(retry["capture_created"])
            self.assertIsNone(retry["phase2"]["shadow_receipt"])
            self.assertEqual((baseline.read_bytes(), shadow.read_bytes()), forecast_bytes)
            data["games"][0]["state"] = "post"
            data["games"][0]["detail"] = "Final"
            atomic_json(root / "output/data/game-status.json", {"weeks": {"2026_05": {"games": {
                "fictional-game": {"kickoff": data["games"][0]["kickoff"], "state": "post", "completed": True}}}}})
            atomic_json(root / "output/data/week.json", data)
            final, _ = build_scorecard(root, NOW + timedelta(hours=5), mode="replay", allow_replay=True)
            probabilities = probability_report(root, policy, mode="replay")
            self.assertEqual(final["outcome_status"], {"resolved": 1})
            self.assertEqual(probabilities["categories"]["rec"]["challenger"]["n"], 1)
            atomic_json(root / "data/cache/stats_2026_05.json", {"fictional-1": {"team": "AAA", "stats": {"gp": 1, "rec": 6}}})
            corrected, _ = build_scorecard(root, NOW + timedelta(hours=6), mode="replay", allow_replay=True)
            self.assertAlmostEqual(corrected["categories"]["rec"]["raw_sleeper"]["mae"], 1.2)
            self.assertEqual((baseline.read_bytes(), shadow.read_bytes()), forecast_bytes)
            self.assertEqual(len(list((root / "data/outcomes_replay").rglob("*.json.gz"))), 4)

    def test_original_recovery_mode_and_live_supplied_clock_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); prepare(root)
            with self.assertRaises(ValueError): run_capture(root, mode="live", replay_at=stamp(NOW))
            atomic_json(root / "config/release-mode.json", {"mode": "original"})
            with self.assertRaises(ValueError): run_capture(root, mode="replay", replay_at=stamp(NOW))
            self.assertFalse((root / "data/replay").exists())

    def test_source_outage_is_saved_without_changing_production_forecast(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); prepare(root, source_unavailable=True)
            before = (root / "output/data/week.json").read_bytes()
            report, health = run_capture(root, mode="replay", replay_at=stamp(NOW))
            self.assertEqual(report["offers"]["coverage"], {"source_unavailable": 2})
            offer = read(root / health["phase2"]["offer_receipt"])
            self.assertEqual(offer["source_error"], "TimeoutError")
            self.assertEqual((root / "output/data/week.json").read_bytes(), before)

    def test_changed_retained_engine_stops_capture(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); prepare(root)
            with (root / "pull/matchup.py").open("a") as handle:
                handle.write("\n# fictional changed engine\n")
            with self.assertRaises(ValueError): run_capture(root, mode="replay", replay_at=stamp(NOW))
            self.assertFalse((root / "data/replay").exists())

    def test_frozen_game_keeps_original_receipt_after_stats_correction(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, _ = prepare(root)
            first = load_json(root / "output/data/matchup-proof.json")
            def later_build():
                data["games"][0]["state"] = "post"
                data["generated_at"] = stamp(NOW + timedelta(hours=5))
                build.Matchups({4: {"fictional-1": {"opp": "CCC", "stats": {"gp": 1, "rec": 999}}}}, {"fictional-1": "WR"})
                atomic_json(root / "output/data/week.json", data)
            with patch.object(build_recorded, "datetime", ReplayClock):
                build_recorded.record_build(root, run=later_build)
            second = load_json(root / "output/data/matchup-proof.json")
            self.assertEqual(second["game_origins"], first["game_origins"])
            self.assertNotEqual(second["latest_inputs"], first["latest_inputs"])
            with patch.object(verify, "ROOT", root):
                verify.problems.clear(); verify.check_point_in_time(data, second)
                self.assertEqual(verify.problems, [])


if __name__ == "__main__":
    unittest.main()
