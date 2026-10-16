"""Fictional replay: recorded builder through saved forecasts and final scoring.

No network, remote writes, public release or real prediction-performance claims.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
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
import phase2_capture
import selection_publication
from selection_publication import publish_selection_report, validate_publication
from selection_report import run_report, summarize
from test_offers import offer_fixture
from test_reliability import NOW
from test_scorecard import setup
from test_source_evidence import fictional_response, fictional_status


class ReplayClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def prepare(root, source_unavailable=False, *, mode="replay", at=NOW, kickoff_hours=1, all_ten=False):
    for path in ENGINE_PATHS:
        target = root / path; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / path, target)
    (root / "config").mkdir(exist_ok=True)
    for path in ("phase2.json", "release-mode.json", "sleeper-rules-provenance.json", "timing-policy.json"):
        shutil.copyfile(ROOT / "config" / path, root / "config" / path)
    data, _, policy = setup()
    data["generated_at"] = stamp(at)
    data["games"][0]["kickoff"] = stamp(at + timedelta(hours=kickoff_hours))
    if at != NOW:
        policy["registered_at"] = stamp(at - timedelta(days=2))
    atomic_json(root / "config/evaluation-policy.json", policy)
    player, prop = data["players"][0], data["players"][0]["props"][0]
    player.update(opp="BBB", snap_share=.8, games_this_season=2)
    prop.update(mf=1, mf_n=0, adj=prop["proj"])
    data["picks"]["over"][0]["adj"] = prop["proj"]
    projected_stats = {"rec": 4.8}
    actual_stats = {"gp": 1, "rec": 5}
    if all_ten:
        projected_stats.update(pass_yd=250.2, pass_td=1.8, pass_cmp=22.2, pass_att=33.2, pass_int=.6,
                               rush_yd=55.2, rush_att=12.2, rec_yd=52.3)
        actual_stats.update(pass_yd=251, pass_td=2, pass_cmp=23, pass_att=34, pass_int=0,
                            rush_yd=56, rush_att=13, rec_yd=55)
        for category in json.loads((ROOT / "config/timing-policy.json").read_text())["categories"]:
            if category == "rec":
                continue
            value = 107.5 if category == "rush_rec_yd" else projected_stats[category]
            extra = copy.deepcopy(prop)
            extra.update(key=category, proj=value, adj=value, line=int(value) - .5,
                         lean=None if category == "pass_int" else "over", values=[])
            player["props"].append(extra)
            data["categories"][category] = {"label": category}
    _, observed, meta, _ = offer_fixture()
    source_rows = [{"player_id": "fictional-1", **meta["fictional-1"], "stats": projected_stats}]
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
        atomic_json(root / "data/cache/stats_2026_05.json", {"fictional-1": {"team": "AAA", "opp": "BBB", "stats": actual_stats}})
    class BuildClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at
    with patch.object(build.sources, "get_json", side_effect=responses), patch.object(build_recorded, "datetime", BuildClock):
        build_recorded.record_build(root, run=fake_build, mode=mode)
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


class PublicSelectionPipelineTests(unittest.TestCase):
    AT = datetime(2026, 10, 24, 11, tzinfo=timezone.utc)

    def run_live(self, root, at=None):
        at = at or self.AT
        kickoff_hours = (self.AT + timedelta(hours=25) - at).total_seconds() / 3600
        prepare(root, mode="live", at=at, kickoff_hours=kickoff_hours, all_ten=True)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return at
        with patch.object(phase2_capture, "datetime", Clock), patch("requests.sessions.Session.request", side_effect=AssertionError("No live HTTP")):
            return run_capture(root, mode="live")

    def assets(self, root):
        base = root / "output/data/selection-grading"
        pointer = load_json(base / "latest.json")
        summary = validate_publication(base, pointer)
        rows = [row for descriptor in pointer["rows"] for row in load_json(base / descriptor["path"])["rows"]]
        outcomes = load_json(base / pointer["outcomes"]["path"])["outcomes"]
        return pointer, summary, rows, outcomes

    def test_existing_live_pipeline_updates_all_ten_and_freezes_checkpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, _ = self.run_live(root)
            pointer, _, _, outcomes = self.assets(root)
            original_assets = {path: path.read_bytes() for path in (root / "output/data/selection-grading" / pointer["report_id"]).glob("*.json")}
            self.assertEqual(set(first["categories"]), {"rec", "rush_att", "pass_yd"})
            self.assertEqual(len(outcomes), 10)
            self.assertIn("pass_int", {row["category"] for row in outcomes})  # Recorded No Lean is still observed.
            normal = [read(path) for path in (root / "data/outcomes").rglob("*.json.gz")]
            self.assertEqual(sorted(len(payload["rows"]) for payload in normal), [3, 7])
            self.assertEqual([payload["week_game_populations"] for payload in normal if len(payload["rows"]) == 7], [[]])
            second, health = self.run_live(root, self.AT + timedelta(minutes=90))
            latest, summary, rows, _ = self.assets(root)
            self.assertNotEqual(pointer["report_id"], latest["report_id"])
            self.assertEqual(health["phase2"]["selection_report_sha256"], latest["report_id"])
            self.assertEqual(second["coverage"]["unique_opportunities"], 3)
            self.assertEqual(summary["input_binding"], "NOT_YET_GIT_COMMITTED")
            self.assertTrue(all(path.read_bytes() == raw for path, raw in original_assets.items()))
            frozen = [row for path in (root / "data/verification/selection-grading/decisions").rglob("*.json.gz") for row in read(path)["rows"]]
            self.assertEqual(len(frozen), 20)
            self.assertEqual({row["checkpoint"] for row in frozen}, {"24h"})
            self.assertTrue(all(row["observation_age_seconds"] == 3600 for row in frozen))
            self.assertTrue(all(row["checkpoint"] != "history" for row in frozen))
            self.assertEqual(sum(row["checkpoint"] == "24h" for row in rows), 20)
            self.assertFalse((root / "data/week_populations").exists())

    def test_all_ten_saved_finals_and_no_lean_appear_in_minimal_outcome_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root)
            data = load_json(root / "output/data/week.json")
            data["games"][0].update(state="post", detail="Final")
            atomic_json(root / "output/data/week.json", data)
            final_at = self.AT + timedelta(hours=30)
            atomic_json(root / "output/data/game-status.json", {"weeks": {"2026_05": fictional_status(data["games"], collected_at=final_at)}})
            identities = selection_publication.all_ten_outcome_identities(root, final_at)
            report, _ = build_scorecard(root, final_at, additional_outcome_pairs=identities)
            self.assertEqual(set(report["categories"]), {"rec", "rush_att", "pass_yd"})
            publish_selection_report(root, final_at)
            _, summary, rows, outcomes = self.assets(root)
            self.assertEqual(len(outcomes), 10)
            self.assertTrue(all(row["status"] == "resolved" for row in outcomes))
            self.assertTrue(all(row["final_confirmed"] is True and row["outcome_conflict"] is False for row in outcomes))
            self.assertTrue(all(row["selected_outcome_row_sha256"] for row in outcomes))
            self.assertTrue(any(row["category"] == "pass_int" for row in outcomes))
            self.assertTrue(any(row["result"] in ("win", "loss", "push") for row in rows))
            self.assertEqual(summary["coverage"]["independently_qualified_completed_weeks"], [])

    def test_dirty_generated_git_inputs_use_exact_staged_bytes(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            root = Path(directory); self.run_live(root)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "output/data/week.json"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Fictional Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Fictional input pin"], check=True)
            data = load_json(root / "output/data/week.json"); data["fixture_uncommitted"] = True
            atomic_json(root / "output/data/week.json", data)
            before = (root / "output/data/week.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "declared Git pin"):
                run_report([root], Path(external), now=self.AT)
            publish_selection_report(root, self.AT)
            _, summary, _, _ = self.assets(root)
            self.assertEqual(summary["input_binding"], "NOT_YET_GIT_COMMITTED")
            self.assertEqual((root / "output/data/week.json").read_bytes(), before)

    def test_frozen_decisions_remain_reportable_when_original_input_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root); self.run_live(root, self.AT + timedelta(minutes=90))
            before = self.assets(root)[2]
            frozen_ids = {row["decision_sha256"] for row in before if row["checkpoint"] == "24h"}
            for path in (root / "data/forward").rglob("*.json.gz"):
                path.unlink()  # Fictional loss simulation, never real evidence.
            publish_selection_report(root, self.AT + timedelta(hours=2))
            after = self.assets(root)[2]
            self.assertEqual({row["decision_sha256"] for row in after}, frozen_ids)

    def test_unreadable_mandatory_outcome_keeps_latest_bytes_and_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root)
            pointer = root / "output/data/selection-grading/latest.json"
            before = pointer.read_bytes()
            (root / "data/outcomes/2026/w05/unreadable.json.gz").write_bytes(b"FICTIONAL invalid gzip")
            with self.assertRaises((ValueError, OSError, EOFError)):
                publish_selection_report(root, self.AT + timedelta(minutes=1))
            self.assertEqual(pointer.read_bytes(), before)

    def test_nested_private_metadata_is_never_exported_and_poisoned_fields_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root)
            pointer = root / "output/data/selection-grading/latest.json"
            before = pointer.read_bytes()
            original = selection_publication.run_report
            def poisoned(*args, **kwargs):
                report, path = original(*args, **kwargs)
                report["rows"][0]["outcome_observations"] = [{"cookie": "FICTIONAL_PRIVATE_VALUE"}]
                return report, path
            with patch.object(selection_publication, "run_report", side_effect=poisoned):
                with self.assertRaises(ValueError):
                    publish_selection_report(root, self.AT)
            self.assertEqual(pointer.read_bytes(), before)
            exported = b"".join(path.read_bytes() for path in (root / "output/data/selection-grading").rglob("*.json"))
            self.assertNotIn(b"FICTIONAL_PRIVATE_VALUE", exported)
            self.assertNotIn(b"/workspace/", exported)
            self.assertNotIn(b"stats_entry", exported)
            self.assertNotIn(b"source_observations", exported)

    def test_rehashed_future_frozen_state_cannot_advance_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root); self.run_live(root, self.AT + timedelta(minutes=90))
            latest = root / "output/data/selection-grading/latest.json"; before = latest.read_bytes()
            path = next((root / "data/verification/selection-grading/decisions").rglob("*.json.gz"))
            payload = read(path)
            payload["rows"][0]["collected_at"] = stamp(self.AT + timedelta(days=10))
            payload["rows"][0].pop("decision_sha256")
            payload["rows"][0]["decision_sha256"] = digest(payload["rows"][0])
            write(root, "verification/selection-grading/decisions", payload)
            with self.assertRaises(ValueError):
                publish_selection_report(root, self.AT + timedelta(hours=2))
            self.assertEqual(latest.read_bytes(), before)

    def test_asset_path_traversal_and_rehashed_bad_summary_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root)
            base = root / "output/data/selection-grading"; pointer = load_json(base / "latest.json")
            altered = copy.deepcopy(pointer); altered["summary"]["path"] = "../private.json"
            with self.assertRaises(ValueError): validate_publication(base, altered)
            altered = copy.deepcopy(pointer)
            path = base / pointer["summary"]["path"]; original = path.read_bytes()
            summary = load_json(path); summary["summary"]["tables"][0]["unique_games"] += 1
            atomic_json(path, summary)
            altered["summary"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(ValueError): validate_publication(base, altered)
            path.write_bytes(original)  # Restore disposable malicious-fixture bytes only.

    def test_symlinked_state_or_publication_parents_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory); prepare(root, mode="live", at=self.AT, all_ten=True)
            target = root / "data/verification/selection-grading"
            target.symlink_to(Path(outside), target_is_directory=True)
            with self.assertRaises(ValueError): publish_selection_report(root, self.AT)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_rehashed_state_cannot_change_category_evidence_membership_or_period(self):
        for alteration in ("category", "evidence", "period", "boolean_membership", "clock_basis"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); self.run_live(root); self.run_live(root, self.AT + timedelta(minutes=90))
                latest = root / "output/data/selection-grading/latest.json"; before = latest.read_bytes()
                payload = read(next((root / "data/verification/selection-grading/decisions").rglob("*.json.gz")))
                row = next(row for row in payload["rows"] if row["action"] == "SELECT")
                if alteration == "category": row["category"] = "not_pickable"
                elif alteration == "evidence":
                    row.update(observation_receipt_sha256=None, observation_row_sha256=None, observation_receipt_refs=[])
                elif alteration == "period": payload["week"] = 9
                elif alteration == "boolean_membership": row["top_over"] = "true"
                else: row["selection_clock_basis"] = "ARCHIVE_COMMIT_TIME"
                row.pop("decision_sha256"); row["decision_sha256"] = digest(row)
                write(root, "verification/selection-grading/decisions", payload)
                with self.assertRaises(ValueError): publish_selection_report(root, self.AT + timedelta(hours=2))
                self.assertEqual(latest.read_bytes(), before)

    def test_final_index_without_selected_evidence_cannot_advance_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root)
            latest = root / "output/data/selection-grading/latest.json"; before = latest.read_bytes()
            original = selection_publication.run_report
            def unbound(*args, **kwargs):
                report, path = original(*args, **kwargs)
                record = report["final_outcomes"][0]
                record.update(status="resolved", actual=1, game_state="post", final_confirmed=True,
                              outcome_conflict=False, outcome_selection="confirmed",
                              selected_outcome_provenance_sha256=None,
                              collected_at=stamp(self.AT + timedelta(hours=30)))
                return report, path
            with patch.object(selection_publication, "run_report", side_effect=unbound):
                with self.assertRaises(ValueError): publish_selection_report(root, self.AT)
            self.assertEqual(latest.read_bytes(), before)

    def test_realistic_population_uses_compact_exact_membership_and_bounded_chunks(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as analysis:
            root = Path(directory); self.run_live(root)
            report, _ = run_report([root], Path(analysis), now=self.AT,
                                   expected_hashes=selection_publication.engine_hashes(root))
            template = next(row for row in report["rows"] if row["action"] == "SELECT")
            categories = json.loads((ROOT / "config/timing-policy.json").read_text())["categories"]
            rows = []
            for index in range(18292):
                row = dict(template, player_id=f"fictional-population-{index}",
                           game_id=f"fictional-game-{index % 14}", category=categories[index % 10],
                           checkpoint=("history", "24h", "6h", "90m")[index % 4],
                           side="over" if index % 2 else "under", top_at_decision=index % 12 == 0)
                row["decision_sha256"] = digest(row)
                rows.append(row)
            report.update(rows=rows, summary=summarize(rows))
            summary, projected, _, chunks, _ = selection_publication._projection(
                report, source_sha="1" * 40, input_digest="2" * 64)
            self.assertEqual(len(projected), 18292)
            self.assertLess(len(selection_publication.canonical(summary)), 12 * 1024 * 1024)
            self.assertTrue(all(len(selection_publication.canonical(chunk)) < 2 * 1024 * 1024 for chunk in chunks))
            for table in summary["summary"]["tables"]:
                self.assertNotIn("row_ids", table)
                refs = [projected[position]["decision_sha256"] for position in table["row_positions"]]
                self.assertEqual(digest(refs), table["row_ids_sha256"])
                self.assertEqual(len(refs), table["rows"])
                self.assertEqual(table["row_positions"], sorted(set(table["row_positions"])))
                self.assertEqual(sum(table["coverage_reason_counts"].values()), table["no_action"])

    def test_equivalent_saved_clock_formats_preserve_frozen_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root); self.run_live(root, self.AT + timedelta(minutes=90))
            payload = read(next((root / "data/verification/selection-grading/decisions").rglob("*.json.gz")))
            row = next(row for row in payload["rows"] if row["action"] == "SELECT")
            row["observation_saved_kickoff"] = row["kickoff"].replace("Z", "+00:00")
            row.pop("decision_sha256"); row["decision_sha256"] = digest(row)
            selection_publication._ledger(payload, load_json(root / "config/timing-policy.json"),
                                          selection_publication.engine_hashes(root), self.AT + timedelta(hours=2))

    def test_unbound_additional_identities_do_not_block_valid_siblings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root)
            original = selection_publication.build_decisions
            def unbound(*args, **kwargs):
                decisions, coverage = original(*args, **kwargs)
                template = decisions[0]
                bad = [dict(template, player_id="fictional-ambiguous", kickoff=None),
                       dict(template, player_id="fictional-team-unknown", team=None),
                       dict(template, player_id="fictional-unbound", observation_receipt_sha256=None,
                            observation_row_sha256=None)]
                return decisions + bad, coverage
            coverage = {}
            with patch.object(selection_publication, "build_decisions", side_effect=unbound):
                identities = selection_publication.all_ten_outcome_identities(root, self.AT, coverage=coverage)
            self.assertEqual(len(identities), 10)
            self.assertEqual(coverage["unique_recorded_identities"], 13)
            self.assertEqual(coverage["excluded_unbound_identities"], {
                "ambiguous_saved_kickoff": 1, "unknown_recorded_team": 1, "no_bound_original_observation": 1})


if __name__ == "__main__":
    unittest.main()
