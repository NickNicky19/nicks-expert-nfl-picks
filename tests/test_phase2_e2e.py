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
import textwrap
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
import point_challenger
import selection_publication
from selection_publication import publish_selection_report, validate_publication
from selection_report import run_report, summarize
from test_offers import offer_fixture
from test_reliability import NOW, fixture as reliability_fixture
from reliability import capture as capture_baseline, engine_hashes, immutable_write
from test_point_challenger import saved_outcome
from test_scorecard import setup
from test_source_evidence import fictional_response, fictional_status


class ReplayClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def prepare(root, source_unavailable=False, *, mode="replay", at=NOW, kickoff_hours=1, all_ten=False, week=5):
    for path in ENGINE_PATHS:
        target = root / path; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / path, target)
    (root / "config").mkdir(exist_ok=True)
    for path in ("phase2.json", "release-mode.json", "sleeper-rules-provenance.json", "timing-policy.json"):
        shutil.copyfile(ROOT / "config" / path, root / "config" / path)
    data, _, policy = setup()
    data["week"] = week
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
            return fictional_response(data["games"], week=week)
        if "/projections/nfl/" in url:
            rows = copy.deepcopy(source_rows)
            if url.endswith(f"/{week + 1}"):
                rows[0]["game_id"] = "future-game-that-must-not-overwrite-current-mapping"
            return rows
        if source_unavailable:
            raise TimeoutError("fictional unavailable source")
        return observed["markets"]
    def fake_build():
        build.sources.get_json(build.sources.ESPN + "/scoreboard", {"dates": 2026, "week": week, "seasontype": 2})
        build.sources.get_json(f"https://api.sleeper.app/projections/nfl/2026/{week}")
        try:
            build.sources.get_json("https://api.sleeper.app/lines/available")
        except TimeoutError:
            pass  # Mirrors the retained builder's explicit fallback, recorded above.
        build.Matchups({4: {"fictional-1": {"opp": "CCC", "stats": {"gp": 1, "rec": 3}}}}, {"fictional-1": "WR"})
        build.sources.get_json(f"https://api.sleeper.app/projections/nfl/2026/{week + 1}")
        atomic_json(root / "output/data/week.json", data)
        atomic_json(root / "output/data/meta.json", {k: data[k] for k in ("season", "week", "generated_at")})
        atomic_json(root / f"data/cache/stats_2026_{week:02d}.json", {"fictional-1": {"team": "AAA", "opp": "BBB", "stats": actual_stats}})
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
            self.assertFalse((root / "data/verification/matchup-checks").exists())

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

    def run_live(self, root, at=None, *, registered_policy=None):
        at = at or self.AT
        kickoff_hours = (self.AT + timedelta(hours=25) - at).total_seconds() / 3600
        prepare(root, mode="live", at=at, kickoff_hours=kickoff_hours, all_ten=True)
        if registered_policy is not None:
            atomic_json(root / "config/evaluation-policy.json", registered_policy)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return at
        with patch.object(phase2_capture, "datetime", Clock), patch("requests.sessions.Session.request", side_effect=AssertionError("No live HTTP")):
            return run_capture(root, mode="live")

    def assert_saved_matchup_check(self, root, health):
        name = health["phase2"]["matchup_verification_receipt"]
        self.assertTrue(name.startswith("data/verification/matchup-checks/2026/w05/"), name)
        path = root / name
        check = read(path)
        self.assertEqual(path.name, digest(check) + ".json.gz")
        self.assertEqual(check["schema_version"], "matchup-verification-v1")
        self.assertEqual(check["mode"], "live")
        self.assertEqual((check["season"], check["week"]), (2026, 5))
        pointer = load_json(root / "output/data/matchup-proof.json")
        inputs = read(root / check["latest_inputs"])
        self.assertEqual(check["latest_inputs"], pointer["latest_inputs"])
        self.assertEqual(check["latest_inputs_sha256"], digest(inputs))
        self.assertEqual(check["engine_files"], inputs["engine_files"])
        self.assertEqual(check["engine_files"], engine_hashes(root))
        self.assertEqual(check["game_origins"], pointer["game_origins"])
        for origin in check["game_origins"].values():
            self.assertEqual(read(root / origin)["engine_files"], check["engine_files"])
        self.assertEqual(check["output_sha256"], pointer["output_sha256"])
        self.assertEqual(check["output_sha256"], digest(load_json(root / "output/data/week.json")))
        self.assertEqual(check["baseline_receipt"], health["receipt"])
        self.assertEqual(check["baseline_payload_sha256"], digest(read(root / health["receipt"])))
        self.assertEqual(check["checked_factors"], 10)
        return path

    def test_live_matchup_checks_preserve_bindings_forecasts_and_all_old_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, first = self.run_live(root)
            first_path = self.assert_saved_matchup_check(root, first)
            # Fictional pre-existing live/replay receipts stay at their old paths.
            legacy = write(root, "matchup_checks", read(first_path))
            replay = write(root, "matchup_checks_replay", dict(read(first_path), mode="replay"))
            saved = {path: path.read_bytes() for path in (root / "data").rglob("*.json.gz")}
            forecasts = load_json(root / "output/data/week.json")
            engine = {path: (root / path).read_bytes() for path in ENGINE_PATHS}
            registered = load_json(root / "config/evaluation-policy.json")
            _, second = self.run_live(root, self.AT + timedelta(minutes=5), registered_policy=registered)
            second_path = self.assert_saved_matchup_check(root, second)
            self.assertNotEqual(second_path, first_path)
            for path, original in saved.items():
                self.assertEqual(path.read_bytes(), original, str(path))
            self.assertTrue(legacy.exists())
            self.assertTrue(replay.exists())
            later = load_json(root / "output/data/week.json")
            for key in ("players", "picks", "games"):
                self.assertEqual(later[key], forecasts[key], key)
            self.assertEqual({path: (root / path).read_bytes() for path in ENGINE_PATHS}, engine)

    def test_actual_updater_staging_keeps_health_checks_in_successive_clean_checkouts(self):
        # Run the actual staging block, not an independently maintained lane list.
        workflow = (ROOT / ".github/workflows/hourly.yml").read_text()
        start = workflow.index("          git add output/data data/cache\n")
        end = workflow.index("          if ! git diff --cached --quiet;", start)
        staging = textwrap.dedent(workflow[start:end])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "writer"
            root.mkdir()
            _, first = self.run_live(root)
            first_path = self.assert_saved_matchup_check(root, first)
            legacy = write(root, "matchup_checks", read(first_path))
            original_legacy = legacy.read_bytes()

            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True,
                                      capture_output=True, text=True).stdout

            git("init", "-q")
            git("config", "user.name", "Fictional persistence test")
            git("config", "user.email", "fixture@example.invalid")
            git("add", "--", *ENGINE_PATHS, "config", legacy.relative_to(root).as_posix())
            git("commit", "-qm", "Fictional existing code and historical receipt")
            saved = {}
            registered = load_json(root / "config/evaluation-policy.json")
            for index, at in enumerate((self.AT, self.AT + timedelta(minutes=5))):
                if index:
                    self.run_live(root, at, registered_policy=registered)
                health = load_json(root / "output/data/health.json")
                name = self.assert_saved_matchup_check(root, health).relative_to(root).as_posix()
                subprocess.run(["bash", "-eu", "-c", staging], cwd=root, check=True,
                               capture_output=True, text=True)
                self.assertIn(name, git("diff", "--cached", "--name-only").splitlines())
                git("commit", "-qm", f"Fictional generated update {index + 1}")
                checkout = Path(directory) / f"checkout-{index}"
                git("clone", "--quiet", "--no-hardlinks", str(root), str(checkout))
                restored = load_json(checkout / "output/data/health.json")
                restored_path = self.assert_saved_matchup_check(checkout, restored)
                self.assertEqual(restored_path.read_bytes(), (root / name).read_bytes())
                self.assertEqual((checkout / legacy.relative_to(root)).read_bytes(), original_legacy)
                for previous, original in saved.items():
                    self.assertEqual((checkout / previous).read_bytes(), original, previous)
                saved.update({path.relative_to(checkout).as_posix(): path.read_bytes()
                              for path in (checkout / "data").rglob("*.json.gz")})
                self.assertEqual(git("status", "--porcelain", "--untracked-files=no"), "")

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


class CandidateRecordingPipelineTests(unittest.TestCase):
    """Fictional native-file updater integration; no live collection or release."""
    AT = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    KICKOFF = datetime(2026, 10, 23, 0, 15, tzinfo=timezone.utc)
    REGISTRATION_SHA256 = "0ffd81a0d2708418d1d1b072cf9ce7750f42c554f04c2456f2a5206be199e0c6"

    def registration(self, root):
        path = root / "tools/rec_half_registration_v1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "tools/rec_half_registration_v1.json", path)
        return load_json(path)

    def native(self, root, *, at=None, kickoff=None, week=7, raw=4.8, adjusted=5.2, no_lean=False):
        """Use the retained real fixture and real native capture, never rename."""
        for name in (*ENGINE_PATHS, "config/evaluation-policy.json"):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        at = at or self.AT
        data, _ = reliability_fixture()
        data.update(week=week, generated_at=stamp(at - timedelta(minutes=1)))
        data["games"][0]["kickoff"] = stamp(kickoff or self.KICKOFF)
        prop = data["players"][0]["props"][0]
        prop.update(proj=raw, adj=adjusted)
        data["picks"]["over"][0].update(proj=raw, adj=adjusted)
        if no_lean:
            prop.update(lean=None, line=None, line_from="ours")
            data["picks"] = {"over": [], "under": []}
        meta = {key: data[key] for key in ("season", "week", "generated_at")}
        path, health = capture_baseline(data, meta, root, at, engine_hashes(ROOT), mode="live")
        return path, health, data

    def run_hook(self, root, path, *, created=True, at=None, completed=None):
        at = at or self.AT + timedelta(seconds=1)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return completed or at
        with patch.object(phase2_capture, "datetime", Clock), patch.object(point_challenger, "datetime") as clock, \
                patch("requests.sessions.Session.request", side_effect=AssertionError("No live HTTP")):
            clock.now.side_effect = [at, completed or at]
            return phase2_capture.run_point_candidate(root, path, baseline_created=created,
                                                      code_commit="a" * 40)

    def run_live(self, root, at=None):
        at = at or self.AT
        self.registration(root)
        prepare(root, mode="live", at=at, kickoff_hours=(self.KICKOFF - at).total_seconds() / 3600,
                all_ten=True, week=7)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return at
        with patch.object(phase2_capture, "datetime", Clock), patch.object(point_challenger, "datetime", Clock), \
                patch("requests.sessions.Session.request", side_effect=AssertionError("No live HTTP")):
            return run_capture(root, mode="live")

    def candidate_paths(self, root):
        return sorted((root / "data/verification/point-candidates/2026/w07").glob("*.json.gz"))

    def test_official_registration_is_unchanged_not_regenerated(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self.registration(Path(directory))
            self.assertEqual(digest(registry), self.REGISTRATION_SHA256)
            self.assertEqual(registry["registered_at"], "2026-10-16T19:36:46.224755Z")
            self.assertEqual(registry["protocol"]["window"]["weeks"], list(range(7, 15)))
            self.assertEqual(registry["recording_status"], "OFFLINE_NOT_ACTIVATED")
            self.assertEqual(registry["protocol"]["recording"], "OFFLINE_ONLY_NO_UPDATER_HOOK")

    def test_cli01_native_filename_reproduces_but_supported_saved_file_hook_works(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.registration(root)
            path, health, _ = self.native(root)
            original = path.read_bytes()
            payload = read(path)
            native_name = digest({"data": payload["input_sha256"], "engine": payload["engine_sha256"],
                                  "mode": payload["mode"]}) + ".json.gz"
            self.assertEqual(path.name, native_name)
            self.assertNotEqual(path.name, digest(payload) + ".json.gz")
            with self.assertRaisesRegex(ValueError, "Receipt filename digest mismatch"):
                point_challenger._receipt(path)  # Frozen standalone CLI limitation stays visible.
            self.assertEqual(phase2_capture.read_native_baseline(path, root, expected_hashes=engine_hashes(ROOT),
                                                               now=self.AT), payload)
            report, status = self.run_hook(root, path, created=health["capture_created"])
            self.assertEqual(status["status"], "RECORDED")
            candidate = read(root / status["candidate_receipt"])
            self.assertEqual(candidate["baseline_payload_sha256"], digest(payload))
            self.assertEqual(candidate["rows"][0]["candidate_projection"], 5.0)
            self.assertEqual(report["coverage"]["unique_opportunities"], 1)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(status["continuous_recording_operational"])

    def test_retry_reuses_first_saved_recording_and_actual_calculation_clocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.registration(root); path, _, _ = self.native(root)
            _, first = self.run_hook(root, path)
            candidate_path = root / first["candidate_receipt"]; before = candidate_path.read_bytes()
            with patch.object(point_challenger, "make_candidate", side_effect=AssertionError("Must not recalculate retry")):
                _, retry = self.run_hook(root, path, created=False, at=self.AT + timedelta(minutes=5))
            self.assertEqual(retry["status"], "REUSED_FIRST_RECORDING")
            self.assertEqual(retry["candidate_receipt"], first["candidate_receipt"])
            self.assertEqual(candidate_path.read_bytes(), before)
            self.assertEqual(len(self.candidate_paths(root)), 1)
            self.assertEqual(read(candidate_path)["calculation_started_at"], stamp(self.AT + timedelta(seconds=1)))

    def test_restart_gap_is_explicitly_missed_and_next_new_observation_can_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.registration(root); path, _, _ = self.native(root)
            with patch.object(point_challenger, "make_candidate", side_effect=AssertionError("Never backfill old baseline")):
                report, missed = self.run_hook(root, path, created=False, at=self.AT + timedelta(minutes=5))
            self.assertEqual(missed["status"], "MISSED_NOT_BACKFILLED")
            self.assertIsNone(missed["candidate_receipt"])
            self.assertEqual(report["status"], "NOT_RECORDED")
            later_path, health, _ = self.native(root, at=self.AT + timedelta(minutes=10))
            self.assertTrue(health["capture_created"])
            _, recorded = self.run_hook(root, later_path, at=self.AT + timedelta(minutes=10, seconds=1))
            self.assertEqual(recorded["status"], "RECORDED")
            self.assertEqual(len(self.candidate_paths(root)), 1)
            self.assertEqual(read(root / recorded["candidate_receipt"])["captured_at"], stamp(self.AT + timedelta(minutes=10)))

    def test_successive_real_updater_entrypoints_persist_forecasts_without_rank_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, health = self.run_live(root)
            prediction_bytes = (root / "output/data/week.json").read_bytes()
            old_baseline = (root / health["receipt"]).read_bytes()
            first_candidate = root / health["phase2"]["point_candidate"]["candidate_receipt"]
            before = first_candidate.read_bytes()
            self.assertEqual(first["point_candidate"]["coverage"]["unique_opportunities"], 1)
            self.assertEqual(set(first["categories"]), {"rec", "rush_att", "pass_yd"})
            expected_picks = load_json(root / "output/data/week.json")["picks"]
            _, retry = self.run_hook(root, root / health["receipt"], created=False,
                                     at=self.AT + timedelta(minutes=1))
            self.assertEqual(retry["status"], "REUSED_FIRST_RECORDING")
            self.assertEqual((root / "output/data/week.json").read_bytes(), prediction_bytes)
            second, latest = self.run_live(root, self.AT + timedelta(minutes=10))
            self.assertEqual(len(self.candidate_paths(root)), 2)
            self.assertEqual(first_candidate.read_bytes(), before)
            self.assertEqual((root / health["receipt"]).read_bytes(), old_baseline)
            self.assertEqual(load_json(root / "output/data/week.json")["picks"], expected_picks)
            self.assertEqual(second["point_candidate"]["coverage"]["unique_opportunities"], 1)
            self.assertEqual(second["point_candidate"]["coverage"]["repeated_capture_rows"], 1)
            self.assertFalse(latest["phase2"]["point_candidate"]["continuous_recording_operational"])
            self.assertFalse(second["point_candidate"]["predictive_improvement_established"])
            self.assertEqual(engine_hashes(root), engine_hashes(ROOT))

    def test_saved_outcome_and_correction_re_evaluate_without_new_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.registration(root); path, _, _ = self.native(root)
            _, first = self.run_hook(root, path)
            candidate_path = root / first["candidate_receipt"]; original = candidate_path.read_bytes()
            final_at = self.KICKOFF + timedelta(hours=5)
            snapshot = saved_outcome(read(path), actual=6, collected=final_at)
            write(root, "outcomes", snapshot)
            report, status = self.run_hook(root, path, created=False, at=final_at)
            self.assertEqual(status["status"], "REUSED_FIRST_RECORDING")
            self.assertEqual(report["categories"]["rec"]["candidate"]["n"], 1)
            self.assertEqual(report["categories"]["rec"]["candidate"]["mae"], 1.0)
            self.assertEqual(read(root / status["report_receipt"]), report)
            write(root, "outcomes", saved_outcome(read(path), actual=7, collected=final_at + timedelta(minutes=5)))
            changed, newer = self.run_hook(root, path, created=False, at=final_at + timedelta(minutes=5))
            self.assertEqual(changed["categories"]["rec"]["candidate"]["mae"], 2.0)
            self.assertNotEqual(newer["report_receipt"], status["report_receipt"])
            self.assertTrue((root / status["report_receipt"]).exists())
            self.assertEqual(candidate_path.read_bytes(), original)
            self.assertEqual(len(self.candidate_paths(root)), 1)

    def test_missing_registration_preserves_baseline_only_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path, _, _ = self.native(root); original = path.read_bytes()
            report, status = self.run_hook(root, path)
            self.assertIsNone(report)
            self.assertEqual(status["status"], "NOT_CONFIGURED")
            self.assertIsNone(status["candidate_receipt"])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(self.candidate_paths(root), [])

    def test_missing_registration_does_not_interrupt_existing_live_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); prepare(root, mode="live", at=self.AT, all_ten=True, week=7)
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None): return CandidateRecordingPipelineTests.AT
            with patch.object(phase2_capture, "datetime", Clock), patch("requests.sessions.Session.request", side_effect=AssertionError("No live HTTP")):
                report, health = run_capture(root, mode="live")
            self.assertEqual(health["phase2"]["point_candidate"]["status"], "NOT_CONFIGURED")
            self.assertEqual(report["coverage"]["unique_opportunities"], 3)
            self.assertTrue((root / "output/data/selection-grading/latest.json").exists())

    def test_present_but_altered_or_malformed_registration_fails_closed(self):
        for malformed in (False, True):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); registry = self.registration(root); path, _, _ = self.native(root)
                target = root / "tools/rec_half_registration_v1.json"
                if malformed:
                    target.write_text("{broken", encoding="utf-8")
                else:
                    registry["recording_status"] = "ACTIVATED"
                    atomic_json(target, registry)
                with self.assertRaises(ValueError): self.run_hook(root, path)
                self.assertEqual(self.candidate_paths(root), [])

    def test_native_generic_filename_and_wrong_lane_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.registration(root); path, _, _ = self.native(root)
            payload = read(path)
            generic = path.with_name(digest(payload) + ".json.gz")
            immutable_write(generic, payload)
            with self.assertRaises(ValueError):
                phase2_capture.read_native_baseline(generic, root, expected_hashes=engine_hashes(ROOT), now=self.AT)
            replay_path = root / "data/replay/2026/w07" / path.name
            replay_path.parent.mkdir(parents=True); shutil.copyfile(path, replay_path)
            with self.assertRaises(ValueError):
                phase2_capture.read_native_baseline(replay_path, root, expected_hashes=engine_hashes(ROOT), now=self.AT)

    def test_native_envelope_and_missing_file_fail_without_candidate(self):
        for broken in (False, True):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); self.registration(root); path, _, _ = self.native(root)
                if broken: path.write_bytes(b"FICTIONAL invalid gzip")
                else: path.unlink()  # Disposable fixture simulates interrupted evidence persistence.
                with self.assertRaises((ValueError, OSError, EOFError)):
                    self.run_hook(root, path)
                self.assertEqual(self.candidate_paths(root), [])

    def test_native_rehashed_wrong_engine_duplicate_identity_and_future_clock_rejected(self):
        for alteration in ("engine", "duplicate", "future", "schema"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); self.registration(root); path, _, _ = self.native(root)
                payload = read(path)
                if alteration == "engine": payload.update(engine_files={"foreign": "engine"}, engine_sha256=digest({"foreign": "engine"}))
                elif alteration == "duplicate": payload["rows"].append(copy.deepcopy(payload["rows"][0]))
                elif alteration == "future": payload["captured_at"] = stamp(self.AT + timedelta(days=1))
                else: payload["schema_version"] = "unknown-baseline"
                path.unlink()  # Rehashed malicious fixture, never a real historical receipt.
                bad = path.with_name(digest({"data": payload["input_sha256"], "engine": payload["engine_sha256"],
                                            "mode": payload["mode"]}) + ".json.gz")
                immutable_write(bad, payload)
                with self.assertRaises(ValueError): self.run_hook(root, bad)
                self.assertEqual(self.candidate_paths(root), [])

    def test_exact_or_after_kickoff_completion_is_retained_as_exclusion_not_forecast(self):
        for late in (timedelta(), timedelta(seconds=1)):
            with self.subTest(late=late), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); self.registration(root); path, _, _ = self.native(root)
                report, status = self.run_hook(root, path, at=self.KICKOFF - timedelta(seconds=1),
                                              completed=self.KICKOFF + late)
                self.assertEqual(status["status"], "RECORDED_NO_ELIGIBLE_RECEPTIONS")
                candidate = read(root / status["candidate_receipt"])
                self.assertEqual(candidate["rows"], [])
                self.assertEqual(candidate["coverage"]["excluded"], {"calculation_not_pregame": 1})
                self.assertEqual(candidate["calculation_completed_at"], stamp(self.KICKOFF + late))
                self.assertEqual(report["coverage"]["unique_opportunities"], 0)

    def test_outside_window_does_not_silently_shift_registered_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); registry = self.registration(root)
            path, _, _ = self.native(root, week=6)
            _, status = self.run_hook(root, path)
            self.assertEqual(status["status"], "OUTSIDE_FIXED_WINDOW")
            self.assertEqual(self.candidate_paths(root), [])
            self.assertEqual(load_json(root / "tools/rec_half_registration_v1.json"), registry)

    def test_corrupted_saved_candidate_or_unavailable_original_blocks_evaluation(self):
        for missing_source in (False, True):
            with self.subTest(missing_source=missing_source), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); self.registration(root); path, _, _ = self.native(root)
                _, status = self.run_hook(root, path)
                if missing_source:
                    path.unlink()
                else:
                    (root / status["candidate_receipt"]).write_bytes(b"FICTIONAL invalid saved candidate")
                with self.assertRaises((ValueError, OSError, EOFError)):
                    self.run_hook(root, path, created=False, at=self.AT + timedelta(minutes=1))

    def test_replay_pipeline_never_calls_or_activates_point_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.registration(root); prepare(root)
            with patch.object(phase2_capture, "run_point_candidate", side_effect=AssertionError("Replay must not record candidate")):
                report, health = run_capture(root, mode="replay", replay_at=stamp(NOW))
            self.assertEqual(report["evidence"], "REPLAY_TEST_NOT_PROSPECTIVE")
            self.assertEqual(self.candidate_paths(root), [])
            self.assertFalse((root / "data/forward").exists())

    def test_no_lean_reference_forecast_retains_fraction_and_same_original_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.registration(root)
            path, _, data = self.native(root, raw=.25, adjusted=1.0, no_lean=True)
            report, status = self.run_hook(root, path)
            row = read(root / status["candidate_receipt"])["rows"][0]
            self.assertEqual(row["candidate_projection"], .625)
            self.assertEqual(report["coverage"]["unique_opportunities"], 1)
            self.assertIsNone(read(path)["rows"][0]["lean"])
            self.assertEqual(read(path)["input_sha256"], digest(data))

    def test_pre_registration_observation_is_not_relabelled_prospective(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.registration(root)
            path, _, _ = self.native(root, at=datetime(2026, 10, 15, 12, tzinfo=timezone.utc))
            report, status = self.run_hook(root, path)
            self.assertEqual(status["status"], "PRIOR_REGISTRATION_OBSERVATION")
            self.assertEqual(report["status"], "NOT_RECORDED")
            self.assertEqual(self.candidate_paths(root), [])

    def test_competing_substantive_candidate_for_same_observation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); registry = self.registration(root); path, _, _ = self.native(root)
            _, status = self.run_hook(root, path)
            first = root / status["candidate_receipt"]; original = first.read_bytes()
            with patch.object(point_challenger, "datetime") as clock:
                clock.now.side_effect = [self.AT + timedelta(seconds=2), self.AT + timedelta(seconds=3)]
                competing = point_challenger.make_candidate(read(path), registry, code_commit="a" * 40)
            write(root, "verification/point-candidates", competing)
            with self.assertRaisesRegex(ValueError, "Multiple candidate recordings"):
                self.run_hook(root, path, created=False, at=self.AT + timedelta(seconds=4))
            self.assertEqual(first.read_bytes(), original)

    def test_candidate_is_calculated_before_shadow_and_heavy_outcome_reporting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); events = []
            original_hook, original_shadow = phase2_capture.run_point_candidate, phase2_capture.make_shadow
            original_scorecard = phase2_capture.build_scorecard
            def hook(*args, **kwargs):
                events.append("point")
                self.assertFalse(kwargs["evaluate_saved"])
                return original_hook(*args, **kwargs)
            def shadow(*args, **kwargs):
                events.append("shadow")
                return original_shadow(*args, **kwargs)
            def scorecard(*args, **kwargs):
                events.append("outcomes")
                return original_scorecard(*args, **kwargs)
            with patch.object(phase2_capture, "run_point_candidate", side_effect=hook), \
                    patch.object(phase2_capture, "make_shadow", side_effect=shadow), \
                    patch.object(phase2_capture, "build_scorecard", side_effect=scorecard):
                self.run_live(root)
            self.assertEqual(events[:3], ["point", "shadow", "outcomes"])

    def test_saved_unreadable_outcome_prevents_new_comparison_without_recalculating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.registration(root); path, _, _ = self.native(root)
            _, status = self.run_hook(root, path)
            candidate = root / status["candidate_receipt"]; original = candidate.read_bytes()
            bad = root / "data/outcomes/2026/w07" / ("0" * 64 + ".json.gz")
            bad.parent.mkdir(parents=True); bad.write_bytes(b"FICTIONAL invalid outcome gzip")
            with patch.object(point_challenger, "make_candidate", side_effect=AssertionError("Never recalculate")):
                with self.assertRaises((ValueError, OSError, EOFError)):
                    self.run_hook(root, path, created=False, at=self.KICKOFF + timedelta(hours=5))
            self.assertEqual(candidate.read_bytes(), original)

    def test_rehashed_invalid_candidate_sibling_cannot_hide_behind_valid_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.registration(root); path, _, _ = self.native(root)
            _, status = self.run_hook(root, path)
            original = read(root / status["candidate_receipt"])
            invalid = copy.deepcopy(original)
            invalid["protocol_version"] = "unsupported-protocol"
            write(root, "verification/point-candidates", invalid)
            with self.assertRaises(ValueError):
                self.run_hook(root, path, created=False, at=self.AT + timedelta(minutes=1))
            self.assertEqual(read(root / status["candidate_receipt"]), original)

    def test_public_candidate_summary_is_bound_but_excludes_private_row_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); report, health = self.run_live(root)
            local = read(root / health["phase2"]["point_candidate"]["report_receipt"])
            public = report["point_candidate"]
            self.assertEqual(public["report_payload_sha256"], digest(local))
            self.assertEqual(public["coverage"], local["coverage"])
            self.assertEqual(len(local["rows"]), 1)
            self.assertNotIn("rows", public)  # Aggregate sample_context.rows is an allowed count.
            self.assertEqual(public["schema_version"], "point-candidate-evaluation-summary-v1")
            self.assertEqual(public["source_report_schema_version"], local["schema_version"])
            for forbidden in ("outcome_observations", "selected_outcome_provenance", "cache_path", "source_observations"):
                self.assertNotIn('"' + forbidden + '"', json.dumps(public))
            self.assertNotIn("/workspace/", json.dumps(public))
            self.assertEqual(load_json(root / "output/data/forecast-scorecard.json")["point_candidate"], public)


    def test_supported_void_remains_visible_in_public_aggregate_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.registration(root)
            path, health, _ = self.native(root)
            self.run_hook(root, path, created=health["capture_created"])
            final_at = self.KICKOFF + timedelta(hours=5)
            write(root, "outcomes", saved_outcome(read(path), status="void", collected=final_at))
            report, _ = self.run_hook(root, path, created=False, at=final_at)
            public = phase2_capture._point_summary(report)
            self.assertEqual(report["outcome_status"], {"void": 1})
            self.assertEqual(public["outcome_status"], report["outcome_status"])
            self.assertEqual(public["weekly"][0]["outcome_status"], {"void": 1})
            self.assertEqual(public["categories"]["rec"]["candidate"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
