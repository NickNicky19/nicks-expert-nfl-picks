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
from evidence import read, write
from phase2_capture import probability_report, run_capture
from reliability import ENGINE_PATHS, atomic_json, digest, load_json, stamp
from scorecard import build_scorecard
from test_offers import offer_fixture
from test_reliability import NOW
from test_scorecard import setup
from test_source_evidence import fictional_response, fictional_status


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
    data["generated_at"] = stamp(NOW)
    atomic_json(root / "config/evaluation-policy.json", policy)
    player, prop = data["players"][0], data["players"][0]["props"][0]
    player.update(opp="BBB", snap_share=.8, games_this_season=2)
    prop.update(mf=1, mf_n=0, adj=prop["proj"])
    data["picks"]["over"][0]["adj"] = prop["proj"]
    _, observed, meta, _ = offer_fixture()
    source_rows = [{"player_id": "fictional-1", **meta["fictional-1"], "stats": {"rec": 4.8}}]
    def responses(url, *args, **kwargs):
        if url == build.sources.ESPN + "/scoreboard":
            return fictional_response(data["games"])
        if "/projections/nfl/" in url:
            rows = copy.deepcopy(source_rows)
            if url.endswith("/6"):
                rows[0]["game_id"] = "future-game-that-must-not-overwrite-current-mapping"
            return rows
        if source_unavailable:
            raise TimeoutError("fictional unavailable source")
        return observed["markets"]
    def fake_build():
        build.sources.get_json(build.sources.ESPN + "/scoreboard", {"dates": 2026, "week": 5, "seasontype": 2})
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
        build_recorded.record_build(root, run=fake_build, mode="replay")
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
                build.sources.get_json(build.sources.ESPN + "/scoreboard", {"dates": 2026, "week": 5, "seasontype": 2})
                build.Matchups({4: {"fictional-1": {"opp": "CCC", "stats": {"gp": 1, "rec": 999}}}}, {"fictional-1": "WR"})
                atomic_json(root / "output/data/week.json", data)
            class LaterClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return NOW + timedelta(hours=5)
            with patch.object(build_recorded, "datetime", LaterClock), patch.object(
                    build.sources, "get_json", side_effect=lambda *a, **k: fictional_response(data["games"])):
                build_recorded.record_build(root, run=later_build, mode="replay")
            second = load_json(root / "output/data/matchup-proof.json")
            self.assertEqual(second["game_origins"], first["game_origins"])
            self.assertNotEqual(second["latest_inputs"], first["latest_inputs"])
            with patch.object(verify, "ROOT", root):
                verify.problems.clear(); verify.check_point_in_time(data, second)
                self.assertEqual(verify.problems, [])

    def assert_rejected_without_writes(self, root, **kwargs):
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        with self.assertRaises(ValueError):
            run_capture(root, **({"mode": "replay", "replay_at": stamp(NOW)} | kwargs))
        after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)

    def test_missing_game_origin_stops_all_capture_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); prepare(root)
            path = root / "output/data/matchup-proof.json"
            pointer = load_json(path); pointer["game_origins"]["fictional-game"] = None
            atomic_json(path, pointer)
            self.assert_rejected_without_writes(root)

    def test_wrong_latest_input_hash_leaves_no_partial_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); prepare(root)
            path = root / "output/data/matchup-proof.json"
            pointer = load_json(path); inputs = read(root / pointer["latest_inputs"])
            inputs["output_sha256"] = "0" * 64
            pointer["latest_inputs"] = write(root, "verification", inputs).relative_to(root).as_posix()
            atomic_json(path, pointer)
            self.assert_rejected_without_writes(root)

    def test_game_without_modeled_props_still_requires_a_valid_original_origin(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, _ = prepare(root)
            data["games"].append({"id": "fictional-no-props", "home": "CCC", "away": "DDD",
                                  "state": "pre", "kickoff": stamp(NOW + timedelta(hours=2))})
            path = root / "output/data/matchup-proof.json"
            pointer = load_json(path); inputs = read(root / pointer["latest_inputs"])
            inputs.update(week_data=copy.deepcopy(data), output_sha256=digest(data))
            inputs["game_status"]["2026_05"] = fictional_status(data["games"], mode="replay", collected_at=NOW)
            name = write(root, "verification", inputs).relative_to(root).as_posix()
            pointer.update(output_sha256=digest(data), latest_inputs=name, game_origins={
                "fictional-game": name, "fictional-no-props": "data/verification/2026/w05/" + "0" * 64 + ".json.gz"})
            atomic_json(path, pointer); atomic_json(root / "output/data/week.json", data)
            self.assert_rejected_without_writes(root)

    def test_invalid_latest_schema_engine_mode_clock_and_source_fail_before_writes(self):
        for alteration in ("legacy", "engine", "mode", "clock", "source"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as d:
                root = Path(d); prepare(root)
                path = root / "output/data/matchup-proof.json"
                pointer = load_json(path); inputs = read(root / pointer["latest_inputs"])
                if alteration == "legacy":
                    inputs["schema_version"] = "matchup-inputs-v1"
                elif alteration == "engine":
                    inputs["engine_files"]["pull/matchup.py"] = "0" * 64
                elif alteration == "mode":
                    inputs["mode"] = "live"
                elif alteration == "clock":
                    inputs["recorded_at"] = stamp(NOW + timedelta(seconds=1))
                else:
                    inputs["game_status"]["2026_05"]["response_sha256"] = "0" * 64
                pointer["latest_inputs"] = write(root, "verification", inputs).relative_to(root).as_posix()
                atomic_json(path, pointer)
                self.assert_rejected_without_writes(root)

    def test_qualifying_origin_must_match_original_kickoff_even_with_current_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, _ = prepare(root)
            data["games"][0]["kickoff"] = stamp(NOW + timedelta(hours=2))
            atomic_json(root / "output/data/week.json", data)
            path = root / "output/data/matchup-proof.json"
            pointer = load_json(path); pointer["output_sha256"] = digest(data)
            self.assertIsNotNone(pointer["game_origins"]["fictional-game"])
            atomic_json(path, pointer)
            self.assert_rejected_without_writes(root)

    def test_future_offer_clock_fails_before_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); prepare(root)
            path = root / "output/data/matchup-proof.json"
            pointer = load_json(path); inputs = read(root / pointer["latest_inputs"])
            inputs["offer_observation"]["collected_at"] = stamp(NOW + timedelta(seconds=1))
            pointer["latest_inputs"] = write(root, "verification", inputs).relative_to(root).as_posix()
            atomic_json(path, pointer)
            self.assert_rejected_without_writes(root)

    def test_full_offline_ppr_check_is_required_before_capture(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); prepare(root)
            atomic_json(root / "data/cache/stats_2026_04.json", {
                "fictional-1": {"stats": {"gp": 1, "rec": 3, "pts_ppr": 42}}})
            self.assert_rejected_without_writes(root)

    def test_full_offline_shape_check_is_required_before_capture(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, _ = prepare(root)
            data["players"][0]["props"][0]["our_line"] = 4.4
            path = root / "output/data/matchup-proof.json"
            pointer = load_json(path); inputs = read(root / pointer["latest_inputs"])
            inputs.update(week_data=copy.deepcopy(data), output_sha256=digest(data))
            name = write(root, "verification", inputs).relative_to(root).as_posix()
            pointer.update(output_sha256=digest(data), latest_inputs=name, game_origins={"fictional-game": name})
            atomic_json(path, pointer); atomic_json(root / "output/data/week.json", data)
            self.assert_rejected_without_writes(root)

    def test_verification_receipt_links_exact_inputs_and_baseline_in_replay_lane(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, _ = prepare(root)
            _, health = run_capture(root, mode="replay", replay_at=stamp(NOW))
            name = health["phase2"]["matchup_verification_receipt"]
            self.assertIn("data/matchup_checks_replay/", name)
            check = read(root / name)
            baseline = read(root / health["receipt"])
            self.assertEqual(check["baseline_payload_sha256"], digest(baseline))
            self.assertEqual(check["output_sha256"], digest(data))
            self.assertEqual(check["latest_inputs_sha256"], digest(read(root / check["latest_inputs"])))
            self.assertEqual(check["checked_factors"], 1)
            self.assertFalse((root / "data/forward").exists())
            self.assertFalse((root / "data/matchup_checks").exists())

    def test_replay_original_inputs_are_not_live_qualification(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); prepare(root)
            self.assert_rejected_without_writes(root, mode="live", replay_at=None)

    def test_build_completed_at_kickoff_cannot_invent_an_original_origin(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, _ = prepare(root)
            (root / "output/data/matchup-proof.json").unlink()
            class AtKickoffClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return NOW + timedelta(hours=1)
            def fake_build():
                build.Matchups({}, {"fictional-1": "WR"})
                atomic_json(root / "output/data/week.json", data)
            with patch.object(build_recorded, "datetime", AtKickoffClock):
                build_recorded.record_build(root, run=fake_build, mode="replay")
            self.assertIsNone(load_json(root / "output/data/matchup-proof.json")["game_origins"]["fictional-game"])
            self.assert_rejected_without_writes(root)

    def test_ambiguous_repeated_matchup_initialization_restores_original_hooks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); prepare(root)
            original, original_get = build.Matchups, build.sources.get_json
            def fake_build():
                build.Matchups({}, {"fictional-1": "WR"})
                build.Matchups({}, {"fictional-1": "WR"})
            with self.assertRaises(ValueError):
                build_recorded.record_build(root, run=fake_build, mode="replay")
            self.assertIs(build.Matchups, original)
            self.assertIs(build.sources.get_json, original_get)


if __name__ == "__main__":
    unittest.main()
