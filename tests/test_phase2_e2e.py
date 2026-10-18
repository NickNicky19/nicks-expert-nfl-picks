"""Fictional replay: recorded builder through saved forecasts and final scoring.

No network, remote writes, public release or real prediction-performance claims.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import gzip
import json
import os
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
from reliability import ENGINE_PATHS, IntegrityError, atomic_json, digest, load_json, stamp, utc
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


def fixture_part(base, descriptor, filename):
    return selection_publication._partition_asset(base, descriptor, filename, encoded=descriptor.get("encoding") == "gzip")


def replace_fixture_part(base, descriptor, filename, payload):
    raw = selection_publication.canonical(payload) + b"\n"
    checksum = hashlib.sha256(raw).hexdigest()
    stored = gzip.compress(raw, mtime=0) if descriptor.get("encoding") == "gzip" else raw
    physical = hashlib.sha256(stored).hexdigest()
    selection_publication._create_file(base / physical / filename, stored)
    descriptor.update(path=physical + "/" + filename, sha256=checksum, decoded_bytes=len(raw))
    if descriptor.get("encoding") == "gzip":
        descriptor.update(encoded_sha256=physical, encoded_bytes=len(stored))


class ReplayClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def prepare(root, source_unavailable=False, *, mode="replay", at=NOW, kickoff_hours=1, all_ten=False, week=5):
    for path in ENGINE_PATHS:
        target = root / path; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / path, target)
    (root / "output").mkdir(exist_ok=True)
    for name in ("app.js", "index.html"):
        shutil.copyfile(ROOT / "output" / name, root / "output" / name)
    (root / "config").mkdir(exist_ok=True)
    for path in ("phase2.json", "release-mode.json", "sleeper-rules-provenance.json", "timing-policy.json"):
        shutil.copyfile(ROOT / "config" / path, root / "config" / path)
    # Legacy positive controls explicitly exercise the retained strict/candidate
    # interface; production cutover activation is tested separately below.
    atomic_json(root / "config/phase2.json", {"capture_enabled": True,
                "production_model": "original_sleeper_matchup_baseline", "challenger_production_enabled": False,
                "verification_mode": "strict-full-board-v1", "experimental_recording_enabled": True})
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
        summary, rows, outcomes = selection_publication.publication_contents(base, pointer)
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
            summary = load_json(path)
            part = summary["summary_partitions"][0]
            value = fixture_part(base, part, "summary.json"); value["tables"][0]["unique_games"] += 1
            replace_fixture_part(base, part, "summary.json", value)
            atomic_json(path, summary)
            altered["summary"].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), decoded_bytes=len(path.read_bytes()))
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

    def locality_report(self, root, analysis):
        self.run_live(root)
        report, _ = run_report([root], analysis, now=self.AT,
                               expected_hashes=selection_publication.engine_hashes(root))
        template = next(row for row in report["rows"] if row["action"] == "SELECT")
        rows = []
        # Twenty logical blocks, forty opportunities each: exercise
        # every key field and 250-row boundaries without a large test population.
        for index in range(800):
            block, member = divmod(index, 40)
            result = ("win", "loss", "push", "dnp", "pending", "unresolved", "no_action")[member % 7]
            side = None if result == "no_action" else ("over" if member % 2 else "under")
            top = block % 3 == 0 and side is not None
            row = dict(template, player_id=f"fictional-layout-{index}",
                       game_id=f"fictional-layout-game-{block % 14}",
                       provenance_class=("local_pregame_membership_observation" if block < 10
                                         else "inherited_archive_decision"),
                       model_version=f"fictional-layout-model-{block % 2}",
                       engine_sha256=None if block % 5 == 0 else digest({"fictional_engine": block % 2}),
                       season=2025 + block % 2, week=5 + block % 3,
                       cohort="top_picks" if block % 3 == 0 else "all_qualifying_leans",
                       checkpoint=("history", "24h", "6h", "90m")[block % 4],
                       category=("rec", "rush_att", "pass_yd")[block % 3],
                       side=side, top_over=bool(top and side == "over"),
                       top_under=bool(top and side == "under"), top_at_decision=top,
                       action="NO_ACTION" if result == "no_action" else "SELECT",
                       reason="source_unavailable" if result == "no_action" else "recorded_membership",
                       result=result, line=None if side is None else 4.0 if result == "push" else 4.5,
                       actual=(4 if result == "push" else
                               (6 if side == "over" else 3) if result == "win" else
                               (3 if side == "over" else 6) if result == "loss" else None))
            row.pop("decision_sha256")
            row["decision_sha256"] = digest(row)
            rows.append(row)
        report.update(rows=rows, summary=summarize(rows))
        return report

    @staticmethod
    def legacy_layout(projected):
        """Independent test-only re-encoding of the retained decision-ID layout."""
        summary, original_rows, outcomes, _, _ = copy.deepcopy(projected)
        rows = sorted(original_rows, key=lambda row: row["decision_sha256"])
        positions = {row["decision_sha256"]: index for index, row in enumerate(rows)}
        for table in summary["summary"]["tables"]:
            members = [original_rows[position]["decision_sha256"] for position in table["row_positions"]]
            table["row_positions"] = sorted(positions[member] for member in members)
            table["row_chunks"] = sorted({position // selection_publication.CHUNK_SIZE
                                           for position in table["row_positions"]})
            table["row_ids_sha256"] = digest([rows[position]["decision_sha256"]
                                               for position in table["row_positions"]])
        chunks = [rows[index:index + selection_publication.CHUNK_SIZE]
                  for index in range(0, len(rows), selection_publication.CHUNK_SIZE)]
        public_id = digest({"summary": summary, "rows": rows, "outcomes": outcomes})
        return summary, rows, outcomes, chunks, public_id

    @staticmethod
    def write_layout(base, projected, at):
        """Write ordinary v1 assets; validation is the unchanged real reader."""
        summary, rows, outcomes, chunks, public_id = projected
        def save(name, value):
            raw = selection_publication.canonical(value) + b"\n"
            selection_publication._create_file(base / public_id / name, raw)
            return {"path": public_id + "/" + name, "sha256": hashlib.sha256(raw).hexdigest()}
        descriptors = [dict(save(f"rows-{index:04d}.json", {
            "schema_version": selection_publication.ROWS_VERSION,
            "report_id": public_id, "rows": chunk}), count=len(chunk))
            for index, chunk in enumerate(chunks)]
        pointer = {"schema_version": selection_publication.POINTER_VERSION,
                   "report_id": public_id, "generated_at": stamp(at), "row_count": len(rows),
                   "summary": save("summary.json", dict(summary, report_id=public_id)),
                   "rows": descriptors,
                   "outcomes": save("outcomes.json", {
                       "schema_version": selection_publication.OUTCOMES_VERSION,
                       "report_id": public_id, "outcomes": outcomes})}
        validate_publication(base, pointer)
        return pointer

    def test_logical_layout_is_deterministic_and_v1_memberships_are_equivalent(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as analysis:
            root = Path(directory)
            report = self.locality_report(root, Path(analysis))
            kwargs = {"source_sha": "1" * 40, "input_digest": "2" * 64}
            grouped = selection_publication._projection(report, **kwargs)
            for permutation in (list(reversed(report["rows"])), report["rows"][237:] + report["rows"][:237]):
                permuted = dict(report, rows=permutation, summary=summarize(permutation))
                self.assertEqual(selection_publication._projection(permuted, **kwargs), grouped)
            legacy = self.legacy_layout(grouped)
            summary, rows, outcomes, chunks, public_id = grouped
            self.assertEqual(len(rows), 800)
            self.assertEqual([len(chunk) for chunk in chunks], [250, 250, 250, 50])
            self.assertNotEqual([row["decision_sha256"] for row in rows],
                                [row["decision_sha256"] for row in legacy[1]])
            self.assertNotEqual(public_id, legacy[4])
            self.assertEqual({row["decision_sha256"]: row for row in rows},
                             {row["decision_sha256"]: row for row in legacy[1]})
            self.assertTrue(any(row["engine_sha256"] is None for row in rows))
            self.assertTrue(any(row["side"] is None for row in rows))
            source_by_id = {row["decision_sha256"]: row for row in report["rows"]}
            for row in rows:
                self.assertEqual(row, {key: value for key, value in source_by_id[row["decision_sha256"]].items()
                                       if key in selection_publication.ROW_FIELDS})
            self.assertEqual(outcomes, legacy[2])
            old_tables = {table["summary_id"]: table for table in legacy[0]["summary"]["tables"]}
            physical = {"row_positions", "row_chunks", "row_ids_sha256"}
            for table in summary["summary"]["tables"]:
                old = old_tables[table["summary_id"]]
                self.assertEqual({key: value for key, value in table.items() if key not in physical},
                                 {key: value for key, value in old.items() if key not in physical})
                expected = {legacy[1][position]["decision_sha256"] for position in old["row_positions"]}
                retrieved = [rows[position] for position in table["row_positions"]]
                self.assertEqual({row["decision_sha256"] for row in retrieved}, expected)
                self.assertEqual(digest([row["decision_sha256"] for row in retrieved]), table["row_ids_sha256"])
                self.assertEqual(table["row_chunks"], sorted({position // 250 for position in table["row_positions"]}))
                # Read precisely the declared chunks, as the browser does; then
                # select positions. Physical order cannot change a group grade.
                loaded = {chunk_id * 250 + offset: row
                          for chunk_id in table["row_chunks"]
                          for offset, row in enumerate(chunks[chunk_id])}
                self.assertEqual([loaded[position] for position in table["row_positions"]], retrieved)
                self.assertLessEqual(len(table["row_chunks"]), 4)
            base = root / "fictional-layout-assets"
            old_pointer = self.write_layout(base, legacy, self.AT)
            old_bytes = {path: path.read_bytes() for path in (base / legacy[4]).glob("*.json")}
            new_pointer = self.write_layout(base, grouped, self.AT)
            validate_publication(base, old_pointer)
            validate_publication(base, new_pointer)
            self.assertTrue(all(path.read_bytes() == raw for path, raw in old_bytes.items()))

    def test_real_publisher_retains_legacy_assets_and_pointer_when_advancing_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_live(root)
            actual_projection = selection_publication._projection
            def legacy_projection(*args, **kwargs):
                return self.legacy_layout(actual_projection(*args, **kwargs))
            with patch.object(selection_publication, "_projection", side_effect=legacy_projection):
                publish_selection_report(root, self.AT, source_sha="1" * 40)
            base = root / "output/data/selection-grading"
            old_pointer = load_json(base / "latest.json")
            old_bytes = {path: path.read_bytes() for path in (base / old_pointer["report_id"]).glob("*.json")}
            _, _, old_rows, old_outcomes = self.assets(root)
            publish_selection_report(root, self.AT, source_sha="1" * 40)
            pointer, _, rows, outcomes = self.assets(root)
            self.assertNotEqual(pointer["report_id"], old_pointer["report_id"])
            self.assertEqual({row["decision_sha256"]: row for row in rows},
                             {row["decision_sha256"]: row for row in old_rows})
            self.assertEqual(outcomes, old_outcomes)
            self.assertTrue(all(path.read_bytes() == raw for path, raw in old_bytes.items()))
            validate_publication(base, old_pointer)

    def test_representative_groups_have_exact_bounded_logical_chunk_requests(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as analysis:
            root = Path(directory)
            report = self.locality_report(root, Path(analysis))
            template = report["rows"][0]
            rows = []
            for checkpoint in ("history", "24h"):
                for category in ("rec", "rush_att", "pass_yd"):
                    for index in range(100):
                        side = "over" if index % 2 else "under"
                        win = index % 3 != 0
                        top = index < 12
                        row = dict(template, player_id=f"fictional-bounded-{checkpoint}-{category}-{index}",
                                   season=2026, week=6, provenance_class="local_pregame_membership_observation",
                                   model_version="original_sleeper_matchup_baseline", engine_sha256=digest({"fictional_engine": 1}),
                                   cohort="all_qualifying_leans", checkpoint=checkpoint, category=category,
                                   action="SELECT", reason="recorded_membership", side=side, line=4.5,
                                   result="win" if win else "loss", actual=6 if (side == "over") == win else 3,
                                   top_at_decision=top, top_over=top and side == "over", top_under=top and side == "under")
                        row.pop("decision_sha256")
                        row["decision_sha256"] = digest(row)
                        rows.append(row)
            report.update(rows=rows, summary=summarize(rows))
            grouped = selection_publication._projection(report, source_sha="1" * 40, input_digest="2" * 64)
            legacy = self.legacy_layout(grouped)
            old = {table["summary_id"]: table for table in legacy[0]["summary"]["tables"]}
            self.assertEqual([len(chunk) for chunk in grouped[3]], [250, 250, 100])
            dimensions, improved = set(), 0
            for table in grouped[0]["summary"]["tables"]:
                if (table["view"] != "all_qualifying_leans" or table["period"] != "2026-w06"
                        or table["dimension"] not in ("overall", "category", "side", "checkpoint")):
                    continue
                dimensions.add(table["dimension"])
                self.assertLessEqual(len(table["row_chunks"]), 2)
                improved += len(table["row_chunks"]) < len(old[table["summary_id"]]["row_chunks"])
                loaded = {chunk_id * 250 + offset: row
                          for chunk_id in table["row_chunks"]
                          for offset, row in enumerate(grouped[3][chunk_id])}
                retrieved = [loaded[position] for position in table["row_positions"]]
                self.assertEqual(len(retrieved), table["rows"])
                self.assertEqual({row["decision_sha256"] for row in retrieved},
                                 {legacy[1][position]["decision_sha256"]
                                  for position in old[table["summary_id"]]["row_positions"]})
                self.assertEqual(digest([row["decision_sha256"] for row in retrieved]), table["row_ids_sha256"])
            self.assertEqual(dimensions, {"overall", "category", "side", "checkpoint"})
            self.assertGreater(improved, 0)


class PartitionedPublicationTests(unittest.TestCase):
    AT = PublicSelectionPipelineTests.AT
    run_live = PublicSelectionPipelineTests.run_live
    locality_report = PublicSelectionPipelineTests.locality_report
    assets = PublicSelectionPipelineTests.assets
    # Inherit fixtures only; unittest's normal discovery also retains all original
    # end-to-end checks on the production publisher above.
    def projection(self, directory):
        root = Path(directory) / "inputs"
        report = self.locality_report(root, Path(directory) / "analysis")
        return root, selection_publication._projection(report, source_sha="1" * 40, input_digest="2" * 64)

    def test_partition_roundtrip_exact_semantics_determinism_and_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            root, projected = self.projection(directory)
            summary, rows, outcomes, chunks, _ = projected
            base = root / "output/data/selection-grading"
            old = selection_publication.prepare_publication(base, summary, rows, outcomes, chunks, self.AT, partitioned=False)
            retained = {p: p.read_bytes() for p in base.rglob("*.json")}
            new = selection_publication.prepare_publication(base, summary, rows, outcomes, chunks, self.AT)
            self.assertNotEqual(old["report_id"], new["report_id"])
            expected = dict(validate_publication(base, old)); expected.pop("report_id")
            actual = dict(validate_publication(base, new)); actual.pop("report_id")
            self.assertEqual(actual, expected)
            permuted = dict(summary, summary=dict(summary["summary"], tables=list(reversed(summary["summary"]["tables"]))))
            self.assertEqual(selection_publication.prepare_publication(base, permuted, rows, list(reversed(outcomes)), chunks, self.AT), new)
            self.assertTrue(all(p.read_bytes() == raw for p, raw in retained.items()))
            index = load_json(base / new["summary"]["path"])
            for part in index["summary_partitions"]:
                self.assertEqual(part["path"], part["sha256"] + "/summary.json")
                self.assertLessEqual(part["decoded_bytes"], selection_publication.SUMMARY_LIMIT)
            self.assertLessEqual(new["summary"]["decoded_bytes"], selection_publication.INDEX_LIMIT)
            # Exercise the legacy no-working-set allowlist on a public-only
            # fixture. The active updater fixture has a separate sealed pointer;
            # replacing that pointer here would manufacture a mixed generation.
            public_root = root / "legacy-public"
            public_base = public_root / "output/data/selection-grading"
            shutil.copytree(base, public_base)
            (public_base / "hosting.json").unlink(missing_ok=True)
            with patch.object(phase2_capture, "read_phase2", return_value=False):
                staged = phase2_capture.stage_pages(public_root, root / "pages")
            for path in public_base.rglob("*.json"):
                self.assertEqual((staged / path.relative_to(public_root / "output")).read_bytes(), path.read_bytes())
            cold = root / "clean-copy"; shutil.copytree(base, cold)
            self.assertEqual(validate_publication(cold, new), validate_publication(base, new))

    def test_producer_checks_every_partition_and_rejects_tampered_contexts(self):
        with tempfile.TemporaryDirectory() as directory:
            root, projected = self.projection(directory); base = root / "assets"
            pointer = selection_publication.prepare_publication(base, *projected[:4], self.AT)
            descriptor = pointer["summary"]; path = base / descriptor["path"]
            original = path.read_bytes(); index = load_json(path)
            # A cold producer must reject corruption even in a non-default part.
            part = index["summary_partitions"][-1]; target = base / part["path"]; raw = target.read_bytes()
            for replacement in (b"{}", raw + b" "):
                target.write_bytes(replacement)
                with self.assertRaises(IntegrityError): validate_publication(base, pointer)
            target.unlink()
            with self.assertRaises(FileNotFoundError): validate_publication(base, pointer)
            target.write_bytes(raw)
            for change in ("duplicate", "period", "context", "generation", "membership"):
                altered = copy.deepcopy(index)
                if change == "duplicate": altered["summary_partitions"].append(altered["summary_partitions"][0])
                else:
                    part = altered["summary_partitions"][-1]
                    payload = load_json(base / part["path"])
                    if change == "period": payload["period"] = "2026-w18"
                    elif change == "context": payload["context_id"] = "0" * 64
                    elif change == "generation": payload["report_id"] = "0" * 64
                    else: payload["tables"][0]["row_positions"] = []
                    body = selection_publication.canonical(payload) + b"\n"; sha = hashlib.sha256(body).hexdigest()
                    selection_publication._create_file(base / sha / "summary.json", body)
                    part.update(path=sha + "/summary.json", sha256=sha, decoded_bytes=len(body))
                atomic_json(path, altered); changed = copy.deepcopy(pointer)
                changed["summary"].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), decoded_bytes=len(path.read_bytes()))
                with self.assertRaises(IntegrityError): validate_publication(base, changed)
            path.write_bytes(original)
            validate_publication(base, pointer)

    def test_outcome_period_indexes_validate_all_records_and_exact_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root)
            pointer, _, _, _ = self.assets(root); base = root / "output/data/selection-grading"
            indexpath = base / pointer["outcomes"]["path"]; original = indexpath.read_bytes(); index = load_json(indexpath)
            self.assertTrue(index["periods"])
            for change in ("duplicate", "wrong_week", "bool_week", "wrong_generation", "wrong_count"):
                altered = copy.deepcopy(index)
                if change == "duplicate": altered["periods"].append(altered["periods"][0])
                elif change == "wrong_count": altered["outcome_count"] += 1
                else:
                    part = altered["periods"][0]; payload = fixture_part(base, part, "outcomes.json")
                    if change == "wrong_week": payload["week"] = 18
                    elif change == "bool_week": payload["week"] = True
                    else: payload["report_id"] = "0" * 64
                    replace_fixture_part(base, part, "outcomes.json", payload)
                atomic_json(indexpath, altered); changed = copy.deepcopy(pointer)
                changed["outcomes"].update(sha256=hashlib.sha256(indexpath.read_bytes()).hexdigest(), decoded_bytes=len(indexpath.read_bytes()))
                with self.assertRaises(IntegrityError): validate_publication(base, changed)
            indexpath.write_bytes(original); validate_publication(base, pointer)

    def test_partition_bounds_do_not_advance_previous_coherent_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.run_live(root)
            base = root / "output/data/selection-grading"; pointer = (base / "latest.json").read_bytes()
            for constant in ("INDEX_LIMIT", "SUMMARY_LIMIT", "ROW_LIMIT"):
                with patch.object(selection_publication, constant, 128), self.assertRaises(IntegrityError):
                    publish_selection_report(root, self.AT + timedelta(seconds=1), source_sha="1" * 40)
                self.assertEqual((base / "latest.json").read_bytes(), pointer)
            summary = validate_publication(base, load_json(base / "latest.json"))
            with self.assertRaisesRegex(IntegrityError, "chunk count"):
                selection_publication.prepare_publication(base, summary, [], [], [[]] * 4001, self.AT)
            validate_publication(base, load_json(base / "latest.json"))


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
            # v1 aggregate publication deliberately excludes research records;
            # the complete earlier comparison remains durable evidence.
            aggregate = load_json(root / "output/data/forecast-scorecard.json")
            self.assertEqual(aggregate["schema_version"], "forecast-scorecard-public-summary-v1")
            self.assertNotIn("point_candidate", aggregate)
            rich = read(root / health["phase2"]["rich_scorecard_receipt"])
            self.assertEqual(rich["report"]["point_candidate"], public)


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


class PartialOperationalPipelineTests(unittest.TestCase):
    def configure(self, root):
        from test_partial_week import fixture
        data, proof, spec, registration = fixture(root)
        for name in ("release-mode.json", "timing-policy.json", "sleeper-rules-provenance.json"):
            target = root / "config" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "config" / name, target)
        _, _, policy = setup()
        atomic_json(root / "config/evaluation-policy.json", policy)
        spec["initial_board_receipt"] = read(root / registration)["initial_board_receipt"]
        config = {"capture_enabled": True, "production_model": "original_sleeper_matchup_baseline",
                  "challenger_production_enabled": False, "experimental_recording_enabled": False,
                  "verification_mode": phase2_capture.partial_week.VERSION, "partial_week": spec}
        atomic_json(root / "config/phase2.json", config)
        for name in ("app.js", "index.html", "style.css", "reliability-ui.js", "recovery.html"):
            shutil.copyfile(ROOT / "output" / name, root / "output" / name)
        (root / "data/cache").mkdir(exist_ok=True)
        atomic_json(root / "data/cache/stats_2026_06.json", {})
        return data, proof, spec, registration

    def run_partial(self, root, at=NOW):
        from test_partial_week import status
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return at
        data = load_json(root / "output/data/week.json")
        with patch.object(phase2_capture, "datetime", Clock), \
                patch.object(phase2_capture, "_closing_status", return_value=status(data, at)), \
                patch.object(phase2_capture, "run_point_candidate", side_effect=AssertionError("Recording is inactive")), \
                patch.object(phase2_capture, "make_shadow", side_effect=AssertionError("Shadow recording is inactive")):
            return run_capture(root)

    def test_complete_partial_updater_and_retry_are_coherent_and_experiments_inactive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, proof, spec, _ = self.configure(root)
            board = (root / "output/data/week.json").read_bytes()
            report, first = self.run_partial(root)
            generation = phase2_capture.validate_generation(root)
            self.assertEqual(generation["board_sha256"], digest(data))
            self.assertEqual((root / "output/data/week.json").read_bytes(), board)
            self.assertEqual(first["phase2"]["verification_mode"], "partial")
            self.assertFalse(first["phase2"]["strict_full_board_verified"])
            self.assertEqual(first["phase2"]["point_candidate"]["status"], "INACTIVE_OWNER_ACTIVATION_REQUIRED")
            self.assertIsNone(first["phase2"]["shadow_receipt"])
            originals = {path.relative_to(root): path.read_bytes() for path in (root / "data").rglob("*.json.gz")}
            _, again = self.run_partial(root, NOW + timedelta(seconds=5))
            self.assertFalse(again["capture_created"])
            for name, raw in originals.items():
                self.assertEqual((root / name).read_bytes(), raw)
            summary = validate_publication(root / "output/data/selection-grading",
                                           load_json(root / "output/data/selection-grading/latest.json"))
            self.assertEqual((summary["schema_version"], summary["report_schema_version"]),
                             ("selection-public-report-v2", "selection-report-v3"))
            aggregate = load_json(root / "output/data/forecast-scorecard.json")
            rich = read(root / again["phase2"]["rich_scorecard_receipt"])
            self.assertEqual(aggregate["report_sha256"], digest(rich["report"]))
            self.assertEqual(set(aggregate["categories"]), {"rec", "rush_att", "pass_yd"})
            self.assertNotIn("rows", aggregate)

    def test_failed_active_generation_retains_last_publication_and_failed_originals(self):
        from test_partial_week import save_build
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, _, _, _ = self.configure(root)
            self.run_partial(root)
            original_health = (root / "output/data/health.json").read_bytes()
            pointer = (root / "output/data/selection-grading/latest.json").read_bytes()
            # A genuine new recorded board with an invalid active contract.
            at = NOW + timedelta(seconds=5)
            data["generated_at"] = stamp(at)
            data["players"][0]["props"][0]["mf"] = 1.3
            save_build(root, data, at)
            with self.assertRaises(IntegrityError):
                self.run_partial(root, at)
            self.assertEqual((root / "output/data/health.json").read_bytes(), original_health)
            self.assertEqual((root / "output/data/selection-grading/latest.json").read_bytes(), pointer)
            self.assertTrue(list((root / "data/verification/partial-failures").rglob("*.json.gz")))

    def test_actual_staging_then_clean_git_checkout_revalidates_required_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "writer"
            root.mkdir()
            _, _, spec, _ = self.configure(root)
            _, health = self.run_partial(root)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
            git("init", "-q"); git("config", "user.name", "Fictional test"); git("config", "user.email", "fixture@example.invalid")
            git("add", "pull", "config", "output/app.js", "output/index.html", "output/style.css", "output/reliability-ui.js", "output/recovery.html")
            workflow = (ROOT / ".github/workflows/hourly.yml").read_text()
            start = workflow.index("          git add output/data data/cache\n")
            end = workflow.index("          if ! git diff --cached --quiet;", start)
            subprocess.run(["bash", "-eu", "-c", textwrap.dedent(workflow[start:end])], cwd=root, check=True)
            git("commit", "-qm", "Fictional durable generation")
            checkout = Path(directory) / "clean"
            git("clone", "--quiet", "--no-hardlinks", str(root), str(checkout))
            shutil.rmtree(root)
            phase2_capture.validate_generation(checkout)
            completion = health["phase2"]["partial_completion_receipt"]
            phase2_capture.partial_week.read_bundle(checkout, completion, spec, phase2_capture.read_native_baseline)

    def test_pages_copy_excludes_backend_originals_and_rejects_unclassified_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            self.configure(root)
            self.run_partial(root)
            originals = {name: (root / "output/data" / name).read_bytes() for name in ("matchup-proof.json", "game-status.json")}
            destination = Path(directory) / "pages"
            phase2_capture.stage_pages(root, destination)
            for name, raw in originals.items():
                self.assertFalse((destination / "data" / name).exists())
                self.assertEqual((root / "output/data" / name).read_bytes(), raw)
            self.assertTrue((destination / "data/verification-scope.json").exists())
            atomic_json(root / "output/data/private-transcript.json", {"not": "a public contract"})
            with self.assertRaises(IntegrityError):
                phase2_capture.stage_pages(root, Path(directory) / "rejected")

    def test_legacy_and_new_public_contracts_use_unchanged_rows_with_explicit_validation(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as analysis:
            root = Path(directory)
            self.configure(root)
            self.run_partial(root)
            new, _ = run_report([root], Path(analysis) / "new", now=NOW, expected_hashes=engine_hashes(root))
            old, _ = run_report([root], Path(analysis) / "old", now=NOW, expected_hashes=engine_hashes(root),
                                report_version="selection-report-v2")
            self.assertEqual(new["rows"], old["rows"])
            self.assertEqual(new["primary_raw_vs_adjusted"], old["primary_raw_vs_adjusted"])
            for report, version in ((old, "selection-public-report-v1"), (new, "selection-public-report-v2")):
                projected = selection_publication._projection(report, source_sha="a" * 40, input_digest="b" * 64)
                self.assertEqual(projected[0]["schema_version"], version)
            bad = dict(new, schema_version="selection-report-unknown")
            with self.assertRaises(IntegrityError):
                selection_publication._projection(bad, source_sha="a" * 40, input_digest="b" * 64)

    def test_summary_size_failure_preserves_latest_and_immutable_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.configure(root)
            self.run_partial(root)
            pointer = root / "output/data/selection-grading/latest.json"
            original = pointer.read_bytes()
            with patch.object(selection_publication, "SUMMARY_LIMIT", 128), self.assertRaises(IntegrityError):
                publish_selection_report(root, NOW + timedelta(seconds=1), source_sha="a" * 40)
            self.assertEqual(pointer.read_bytes(), original)
            current = load_json(pointer)
            summary = root / "output/data/selection-grading" / current["summary"]["path"]
            raw = summary.read_bytes()
            # Exercise the actual 12 MiB reader bound, independently of JSON or hash checks.
            summary.write_bytes(raw + b" " * selection_publication.SUMMARY_LIMIT)
            changed = copy.deepcopy(current)
            changed["summary"]["sha256"] = hashlib.sha256(summary.read_bytes()).hexdigest()
            with self.assertRaisesRegex(IntegrityError, "size limit"):
                validate_publication(root / "output/data/selection-grading", changed)
            summary.write_bytes(raw)
            validate_publication(root / "output/data/selection-grading", current)

    def test_unknown_source_or_policy_cannot_publish_an_unreadable_new_summary(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as analysis:
            root = Path(directory)
            self.configure(root)
            self.run_partial(root)
            report, _ = run_report([root], Path(analysis), now=NOW, expected_hashes=engine_hashes(root))
            for field, value in (("line_from", "unrecognized_source"), ("policy_sha256", None), ("policy_version", "")):
                altered = copy.deepcopy(report)
                altered["rows"][0][field] = value
                altered["summary"] = summarize(altered["rows"])
                with self.subTest(field=field), self.assertRaises(IntegrityError):
                    selection_publication._projection(altered, source_sha="a" * 40, input_digest="b" * 64)

    def test_week_rollover_remains_strict_and_new_experimental_recording_stays_off(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, spec, _ = self.configure(root)
            prepare(root, mode="live", at=NOW, week=7)
            config = load_json(root / "config/phase2.json")
            config.update(verification_mode=phase2_capture.partial_week.VERSION, partial_week=spec, experimental_recording_enabled=False)
            atomic_json(root / "config/phase2.json", config)
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None): return NOW
            with patch.object(phase2_capture, "datetime", Clock), \
                    patch.object(phase2_capture, "_closing_status", side_effect=AssertionError("Rollover must select strict")), \
                    patch.object(phase2_capture, "run_point_candidate", side_effect=AssertionError("Inactive")):
                _, health = run_capture(root)
            self.assertTrue(health["phase2"]["strict_full_board_verified"])
            self.assertEqual(health["phase2"]["point_candidate"]["status"], "INACTIVE_OWNER_ACTIVATION_REQUIRED")
            self.assertIsNone(health["phase2"]["shadow_receipt"])

    def test_connected_builder_registers_before_forecasts_and_rebinds_every_output_cache(self):
        from test_partial_week import status
        import partial_week
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, _, _, _ = self.configure(root)
            shutil.rmtree(root / "data/verification/partial-registrations")
            old_paths = {key: getattr(build, key) for key in ("ROOT", "OUT", "CACHE", "ARCHIVE", "WEEKS")}
            old_athletes = build.books.ATHLETES
            def recorded(stage, mode):
                self.assertEqual(mode, "live")
                self.assertTrue(list((stage / "data/verification/partial-registrations").rglob("*.json.gz")))
                self.assertEqual(build.ROOT, stage)
                self.assertEqual(build.OUT, stage / "output/data")
                self.assertEqual(build.ARCHIVE, stage / "output/data/archive")
                self.assertEqual(build.WEEKS, stage / "output/data/weeks")
                self.assertEqual(build.books.ATHLETES, stage / "data/cache/espn_athletes.json")
                self.assertEqual(build.sources.nfl_state()["week"], 6)
                atomic_json(build.books.ATHLETES, {"fictional": "stage-only lookup"})
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None): return NOW
            with patch.object(phase2_capture, "datetime", Clock), \
                    patch.object(build.sources, "nfl_state", return_value={"season": "2026", "week": 6, "season_type": "regular"}) as selector, \
                    patch.object(build_recorded, "record_build", side_effect=recorded), \
                    patch.object(phase2_capture, "_closing_status", return_value=status(data, NOW)):
                run_capture(root, build_first=True)
                self.assertEqual(selector.call_count, 1)
            self.assertEqual({key: getattr(build, key) for key in old_paths}, old_paths)
            self.assertEqual(build.books.ATHLETES, old_athletes)
            self.assertEqual(load_json(root / "data/cache/espn_athletes.json"), {"fictional": "stage-only lookup"})


class FailedNativeRecoveryConsumerTests(unittest.TestCase):
    configure = PartialOperationalPipelineTests.configure
    run_partial = PartialOperationalPipelineTests.run_partial

    def test_failed_native_is_preserved_but_never_becomes_a_report_observation(self):
        from test_partial_week import status
        from selection_report import build_decisions
        for barrier in (2, 4):
            with self.subTest(barrier=barrier), tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as analysis:
                root = Path(directory)
                data, _, _, _ = self.configure(root)
                original = phase2_capture.partial_week.record_bundle
                captured = []
                def crossed(*args, **kwargs):
                    times = iter([NOW] * barrier + [NOW + timedelta(hours=2)] * 10)
                    kwargs["clock"] = lambda: next(times)
                    try:
                        return original(*args, **kwargs)
                    finally:
                        captured.extend(path.read_bytes() for path in (args[0] / "data/forward").rglob("*.json.gz"))
                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None): return NOW
                with patch.object(phase2_capture, "datetime", Clock), \
                        patch.object(phase2_capture, "_closing_status", return_value=status(data, NOW)), \
                        patch.object(phase2_capture.partial_week, "record_bundle", side_effect=crossed):
                    with self.assertRaises(IntegrityError): run_capture(root)
                self.assertEqual(list((root / "data/forward").rglob("*.json.gz")), [])
                saved = list((root / "data/verification/partial-unqualified-native").rglob("*.json.gz"))
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0].read_bytes(), captured[0])
                records, coverage = build_decisions([], load_json(root / "config/timing-policy.json"),
                                                   NOW + timedelta(hours=3), engine_hashes(root))
                self.assertEqual(coverage["unique_observed_opportunities"], 0)
                self.assertEqual(records, [])
                report, _ = run_report([root], Path(analysis), now=NOW + timedelta(hours=3),
                                        expected_hashes=engine_hashes(root))
                self.assertEqual(report["rows"], [])
                self.assertEqual(report["primary_raw_vs_adjusted"]["coverage"]["unique_opportunities"], 0)

    def test_completed_native_remains_usable_when_only_report_publication_fails(self):
        from test_partial_week import status
        from selection_report import build_decisions
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, _, _, _ = self.configure(root)
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None): return NOW
            with patch.object(phase2_capture, "datetime", Clock), \
                    patch.object(phase2_capture, "_closing_status", return_value=status(data, NOW)), \
                    patch.object(phase2_capture, "publish_selection_report", side_effect=IntegrityError("fictional report-only failure")):
                with self.assertRaisesRegex(IntegrityError, "report-only"):
                    run_capture(root)
            paths = list((root / "data/forward").rglob("*.json.gz"))
            self.assertEqual(len(paths), 1)
            self.assertEqual(list((root / "data/verification/partial-unqualified-native").rglob("*.json.gz")), [])
            rows, coverage = build_decisions([read(paths[0])], load_json(root / "config/timing-policy.json"),
                                             NOW + timedelta(minutes=1), engine_hashes(root))
            self.assertEqual(coverage["unique_observed_opportunities"], 1)
            self.assertTrue(any(row["action"] == "SELECT" for row in rows))

    def test_failed_native_clean_checkout_keeps_bytes_outside_canonical_consumers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "writer"; root.mkdir()
            data, _, spec, registration = self.configure(root)
            # Deliberately incomplete NEW native; the failure-only persistence
            # path must not turn it into a completed forecast on restart.
            stage = Path(directory) / "stage"
            shutil.copytree(root, stage)
            path, _ = capture_baseline(data, load_json(stage / "output/data/meta.json"), stage, NOW,
                                       engine_hashes(stage), mode="live")
            original = path.read_bytes()
            phase2_capture._copy_evidence(stage, root, failed_generation=True)
            git = lambda *args: subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
            git("init", "-q"); git("config", "user.name", "Fictional test"); git("config", "user.email", "fixture@example.invalid")
            git("add", "pull", "config")
            workflow = (ROOT / ".github/workflows/hourly.yml").read_text()
            start = workflow.index("          git add output/data data/cache\n")
            end = workflow.index("          if ! git diff --cached --quiet;", start)
            subprocess.run(["bash", "-eu", "-c", textwrap.dedent(workflow[start:end])], cwd=root, check=True)
            git("commit", "-qm", "Fictional failed evidence only")
            clone = Path(directory) / "clean"; git("clone", "--quiet", "--no-hardlinks", str(root), str(clone))
            shutil.rmtree(root); shutil.rmtree(stage)
            self.assertEqual(list((clone / "data/forward").rglob("*.json.gz")), [])
            saved = list((clone / "data/verification/partial-unqualified-native").rglob("*.json.gz"))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].read_bytes(), original)

    def test_new_failed_native_does_not_move_or_rewrite_existing_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "saved"; root.mkdir()
            data, _, _, _ = self.configure(root)
            old = copy.deepcopy(data)
            old["generated_at"] = stamp(NOW - timedelta(minutes=5))
            old_path, _ = capture_baseline(old, {key: old[key] for key in ("season", "week", "generated_at")},
                                          root, NOW - timedelta(minutes=5), engine_hashes(root), mode="live")
            original = old_path.read_bytes()
            stage = Path(directory) / "failed-generation"; shutil.copytree(root, stage)
            new_path, _ = capture_baseline(data, load_json(stage / "output/data/meta.json"), stage, NOW,
                                          engine_hashes(stage), mode="live")
            failed_bytes = new_path.read_bytes()
            phase2_capture._copy_evidence(stage, root, failed_generation=True)
            self.assertEqual(old_path.read_bytes(), original)
            self.assertEqual(list((root / "data/forward").rglob("*.json.gz")), [old_path])
            preserved = list((root / "data/verification/partial-unqualified-native").rglob("*.json.gz"))
            self.assertEqual(len(preserved), 1)
            self.assertEqual(preserved[0].read_bytes(), failed_bytes)





class EncodedHostingTests(unittest.TestCase):
    # Past fictional clock keeps saved restart checks independent of wall time.
    AT = datetime(2026, 10, 17, 11, tzinfo=timezone.utc)
    run_live = PublicSelectionPipelineTests.run_live
    locality_report = PublicSelectionPipelineTests.locality_report
    projection = PartitionedPublicationTests.projection

    def test_gzip_is_deterministic_lossless_and_legacy_assets_stay_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            root, projected = self.projection(directory); base = root / "assets"
            summary, rows, outcomes, chunks, _ = projected
            plain = selection_publication.prepare_publication(base, *projected[:4], self.AT)
            original = {p: p.read_bytes() for p in base.rglob("*") if p.is_file()}
            compressed = selection_publication.prepare_publication(base, *projected[:4], self.AT, encoding="gzip")
            self.assertNotEqual(plain["report_id"], compressed["report_id"])
            old = list(selection_publication.publication_contents(base, plain))
            new = list(selection_publication.publication_contents(base, compressed))
            old[0].pop("report_id"); new[0].pop("report_id")
            self.assertEqual(old, new)
            permuted = dict(summary, summary=dict(summary["summary"], tables=list(reversed(summary["summary"]["tables"]))))
            again = selection_publication.prepare_publication(base, permuted, rows, list(reversed(outcomes)), chunks, self.AT, encoding="gzip")
            self.assertEqual(again, compressed)
            other = root / "independent"
            self.assertEqual(selection_publication.prepare_publication(other, *projected[:4], self.AT, encoding="gzip"), compressed)
            for path in base.rglob("*"):
                if path.is_file() and path not in original:
                    self.assertEqual(path.read_bytes(), (other / path.relative_to(base)).read_bytes())
            self.assertTrue(all(path.read_bytes() == raw for path, raw in original.items()))
            value = compressed["rows"][0]
            stored = (base / value["path"]).read_bytes()
            self.assertEqual(stored[:8], b"\x1f\x8b\x08\x00\x00\x00\x00\x00")
            self.assertEqual(hashlib.sha256(stored).hexdigest(), value["encoded_sha256"])
            self.assertGreater(len(compressed["rows"]), 1)

    def test_streamed_encoded_and_decoded_limits_and_corruption(self):
        import io
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); raw = b'{"fictional":true}\n'
            buffer = io.BytesIO()
            with gzip.GzipFile(fileobj=buffer, filename="", mode="wb", mtime=0) as handle: handle.write(raw)
            good = buffer.getvalue(); path = root / "payload"
            def descriptor(stored=good, decoded=raw):
                return {"encoding":"gzip", "encoded_sha256":hashlib.sha256(stored).hexdigest(), "encoded_bytes":len(stored),
                        "sha256":hashlib.sha256(decoded).hexdigest(), "decoded_bytes":len(decoded)}
            path.write_bytes(good)
            self.assertEqual(selection_publication._read_asset_bytes(path, descriptor(), 2048, encoded=True), raw)
            cases = [(good[:-3], descriptor(good[:-3])), (good + good, descriptor(good + good)),
                     (good, dict(descriptor(), encoded_sha256="0" * 64)), (good, dict(descriptor(), sha256="0" * 64)),
                     (good, dict(descriptor(), encoded_bytes=len(good)-1)), (good, dict(descriptor(), decoded_bytes=1)),
                     (good, dict(descriptor(), decoded_bytes=2049)), (good, dict(descriptor(), encoded_bytes=2049)),
                     (good, dict(descriptor(), encoding="br"))]
            for stored, desc in cases:
                with self.subTest(desc=desc):
                    path.write_bytes(stored)
                    with self.assertRaises(IntegrityError): selection_publication._read_asset_bytes(path, desc, 2048, encoded=True)
            expanded = b"A" * (3 * 1024 * 1024); bomb = gzip.compress(expanded, mtime=0); path.write_bytes(bomb)
            desc = descriptor(bomb, b"A" * 16)
            with self.assertRaisesRegex(IntegrityError, "decoded size limit"):
                selection_publication._read_asset_bytes(path, desc, 2 * 1024 * 1024, encoded=True)

    def test_every_encoded_context_and_outcome_is_validated_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root, projected = self.projection(directory); base = root / "assets"
            pointer = selection_publication.prepare_publication(base, *projected[:4], self.AT, encoding="gzip")
            indexpath = base / pointer["summary"]["path"]; original = indexpath.read_bytes()
            index = load_json(indexpath); part = index["summary_partitions"][-1]
            payload = fixture_part(base, part, "summary.json"); payload["period"] = "2026-w18"
            replace_fixture_part(base, part, "summary.json", payload)
            atomic_json(indexpath, index); changed = copy.deepcopy(pointer)
            changed["summary"].update(sha256=hashlib.sha256(indexpath.read_bytes()).hexdigest(), decoded_bytes=len(indexpath.read_bytes()))
            with self.assertRaisesRegex(IntegrityError, "identity/context/period"):
                validate_publication(base, changed)
            indexpath.write_bytes(original); validate_publication(base, pointer)
            bad = copy.deepcopy(pointer); bad["rows"][0]["encoding"] = "identity"
            with self.assertRaises(IntegrityError): validate_publication(base, bad)
            bad = copy.deepcopy(pointer); bad["rows"][0]["path"] = "../private.json"
            with self.assertRaises(IntegrityError): validate_publication(base, bad)

    def git(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE, text=True).strip()

    def git_fixture(self, root):
        self.git(root, "init", "-q"); self.git(root, "config", "user.name", "Fictional hosting test")
        self.git(root, "config", "user.email", "fixture@example.invalid")
        self.git(root, "commit", "--allow-empty", "-qm", "Fictional baseline")
        for name in ("style.css", "reliability-ui.js", "recovery.html"):
            target = root/"output"/name; target.parent.mkdir(exist_ok=True)
            shutil.copyfile(ROOT/"output"/name, target)
        # Exact actions/checkout remote spelling (without .git).
        self.git(root, "remote", "add", "origin", "https://github.com/NickNicky19/nicks-expert-nfl-picks")

    def commit_fixture(self, root, label):
        self.git(root, "add", "pull", "config", "output/app.js", "output/index.html", "output/style.css", "output/reliability-ui.js", "output/recovery.html")
        workflow = (ROOT / ".github/workflows/hourly.yml").read_text()
        start = workflow.index("          git add output/data data/cache\n")
        end = workflow.index("          if ! git diff --cached --quiet;", start)
        subprocess.run(["bash", "-eu", "-c", textwrap.dedent(workflow[start:end])], cwd=root, check=True)
        self.git(root, "commit", "-qm", "Fictional hosting " + label)
        return self.git(root, "rev-parse", "HEAD")

    def test_four_successive_updater_generations_archive_actual_commits_and_cold_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "writer"; root.mkdir(); self.git_fixture(root)
            manifests, preserved = [], {}
            for n in range(4):
                self.run_live(root, self.AT + timedelta(minutes=10*n))
                working = load_json(root / "output/data/selection-grading/hosting.json")
                manifests.append(working["latest"])
                self.assertEqual(working["previous"], manifests[n-1] if n else None)
                self.assertTrue(all(path.read_bytes() == raw for path, raw in preserved.items()))
                preserved.update({p:p.read_bytes() for p in (root / "data").rglob("*.gz")})
                pin = self.commit_fixture(root, str(n))
                with patch.object(phase2_capture, "_public_archive_commit") as public:
                    stage = phase2_capture.stage_pages(root, Path(directory) / ("pages"+str(n)))
                if n >= 2: public.assert_called_once_with(pin, self.git(root, "rev-parse", pin+"^{tree}"))
                delivered = load_json(stage / "data/selection-grading/hosting.json")
                self.assertEqual(delivered["latest"], manifests[-1])
                self.assertEqual(delivered["previous"], manifests[-2] if n else None)
                self.assertTrue((root / "output/data/selection-grading" / manifests[0]["path"]).exists())
                if n >= 2:
                    self.assertFalse((stage / "data/selection-grading" / manifests[0]["path"]).exists())
                    records = {}
                    for shard in delivered["archive_index"]:
                        records.update(load_json(stage / "data/selection-grading" / shard["asset"]["path"])["reports"])
                    key = digest(phase2_capture._manifest(root / "output/data/selection-grading", manifests[0])[0]["pointer"])
                    self.assertEqual(records[key]["git_ref"], pin)
                    self.assertEqual(records[key]["manifest"], manifests[0])
            self.git(root, "clone", "--quiet", "--no-hardlinks", str(root), str(Path(directory)/"cold"))
            cold = Path(directory)/"cold"; phase2_capture.validate_generation(cold)
            self.git(cold, "remote", "set-url", "origin", "https://github.com/NickNicky19/nicks-expert-nfl-picks")
            with patch.object(phase2_capture, "_public_archive_commit"):
                phase2_capture.stage_pages(cold, Path(directory)/"cold-pages")
            for relative in ("output/data/selection-grading/hosting.json", "output/data/release-identity.json", "output/data/health.json"):
                self.assertEqual((cold/relative).read_bytes(), (root/relative).read_bytes())
            self.assertEqual(engine_hashes(root), engine_hashes(ROOT))

    def test_missing_or_corrupt_retained_archive_and_nonpublic_commit_fail_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/"writer";root.mkdir();self.git_fixture(root)
            for n in range(3):
                self.run_live(root, self.AT+timedelta(minutes=10*n)); self.commit_fixture(root,str(n))
            previous=(root/"output/data/selection-grading/hosting.json").read_bytes()
            with patch.object(phase2_capture,"_public_archive_commit",side_effect=IntegrityError("Unpublished fictional commit")):
                with self.assertRaisesRegex(IntegrityError,"Unpublished"):
                    phase2_capture.stage_pages(root,Path(directory)/"notpublic")
            working=load_json(root/"output/data/selection-grading/hosting.json")
            records=phase2_capture._registry(root/"output/data/selection-grading",working)
            selected={digest(phase2_capture._manifest(root/"output/data/selection-grading",d)[0]["pointer"]) for d in (working['latest'],working['previous'])}
            descriptor=records[next(iter(set(records)-selected))]
            path=root/"output/data/selection-grading"/descriptor['path'];raw=path.read_bytes();path.write_bytes(raw+b' ')
            with patch.object(phase2_capture,"_public_archive_commit"):
                with self.assertRaises(IntegrityError):phase2_capture.stage_pages(root,Path(directory)/"corrupt")
            path.write_bytes(raw)
            self.assertEqual((root/"output/data/selection-grading/hosting.json").read_bytes(),previous)

    def test_same_finalized_retry_does_not_rotate_and_later_clock_is_a_new_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.run_live(root)
            base=root/"output/data/selection-grading";working=(base/"hosting.json").read_bytes()
            phase2_capture.finalize_hosting(root,self.AT+timedelta(minutes=1))
            self.assertEqual((base/"hosting.json").read_bytes(),working)
            first=load_json(base/"hosting.json")['latest']
            pointer=load_json(base/"latest.json");pointer['generated_at']=stamp(self.AT+timedelta(minutes=1));atomic_json(base/"latest.json",pointer)
            generation=load_json(root/"output/data/release-identity.json");generation.pop('generation_sha256');generation['bindings']['data/selection-grading/latest.json']=hashlib.sha256((base/"latest.json").read_bytes()).hexdigest()
            gid=digest(generation);atomic_json(root/"output/data/release-identity.json",dict(generation,generation_sha256=gid));health=load_json(root/"output/data/health.json");health['generation_sha256']=gid;atomic_json(root/"output/data/health.json",health)
            phase2_capture.finalize_hosting(root,self.AT+timedelta(minutes=1))
            changed=load_json(base/"hosting.json");self.assertEqual(changed['previous'],first);self.assertNotEqual(changed['latest'],first)
            phase2_capture.validate_generation(root)

    def test_budget_failure_preserves_working_publication_and_all_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'writer';root.mkdir();self.run_live(root)
            before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(phase2_capture,'STAGING_BUDGET',1):
                with self.assertRaisesRegex(IntegrityError,'900000000-byte budget'):
                    phase2_capture.stage_pages(root,Path(directory)/'too-large')
            self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
            staged=phase2_capture.stage_pages(root,Path(directory)/'valid')
            self.assertEqual(staged.stat().st_mode & 0o777,0o755)
            self.assertTrue(all((p.stat().st_mode & 0o777)==(0o755 if p.is_dir() else 0o644) for p in staged.rglob('*')))
            # Untrusted oversized allowed-path input is rejected by actual 900MB
            # budget before materializing its sparse bytes in the new stage.
            huge=root/'output/data/archive/2000_w01.json';huge.parent.mkdir(exist_ok=True)
            with huge.open('wb') as handle:
                handle.write(b'SYNTHETIC_OVERSIZED_LIMIT_CONTROL_NOT_A_FORECAST')
                handle.truncate(phase2_capture.STAGING_BUDGET+1)
            failed=Path(directory)/'actual-oversized'
            with self.assertRaisesRegex(IntegrityError,'900000000-byte budget'):
                phase2_capture.stage_pages(root,failed)
            self.assertFalse((failed/'data/archive/2000_w01.json').exists())
            self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))

    def test_delivery_metadata_is_hash_bound_and_missing_part_is_not_previous_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'writer';root.mkdir();self.run_live(root)
            stage=phase2_capture.stage_pages(root,Path(directory)/'pages');base=stage/'data/selection-grading';working=load_json(base/'hosting.json')
            altered=copy.deepcopy(working);altered['delivery_sha256']='0'*64
            with self.assertRaises(IntegrityError):phase2_capture._registry(base,altered)
            altered=copy.deepcopy(working);altered['archive_index']=[{'prefix':'z','asset':{}}];altered['delivery_sha256']=digest({k:v for k,v in altered.items() if k!='delivery_sha256'})
            with self.assertRaises(IntegrityError):phase2_capture._registry(base,altered)
            before=(root/'output/data/selection-grading/hosting.json').read_bytes()
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):return self.AT+timedelta(minutes=5)
            with patch.object(selection_publication,'SUMMARY_LIMIT',128), patch.object(phase2_capture,'datetime',Clock):
                with self.assertRaises(IntegrityError):run_capture(root,mode='live')
            self.assertEqual((root/'output/data/selection-grading/hosting.json').read_bytes(),before)
            phase2_capture.validate_generation(root)

    def plain_original(self, root):
        self.run_live(root)
        base=root/'output/data/selection-grading'
        summary,rows,outcomes=selection_publication.publication_contents(base,load_json(base/'latest.json'))
        chunks=[rows[n:n+250] for n in range(0,len(rows),250)]
        pointer=selection_publication.prepare_publication(base,summary,rows,outcomes,chunks,self.AT)
        atomic_json(base/'latest.json',pointer)
        generation=load_json(root/'output/data/release-identity.json');generation.pop('generation_sha256')
        generation['selection_report_id']=pointer['report_id']
        generation['bindings']['data/selection-grading/latest.json']=hashlib.sha256((base/'latest.json').read_bytes()).hexdigest()
        gid=digest(generation);atomic_json(root/'output/data/release-identity.json',dict(generation,generation_sha256=gid))
        health=load_json(root/'output/data/health.json');health['generation_sha256']=gid
        health['phase2']['selection_report_sha256']=pointer['report_id'];atomic_json(root/'output/data/health.json',health)
        # Versioned fictional legacy input, not a modification of real history.
        (base/'hosting.json').unlink()
        phase2_capture.validate_generation(root)
        return pointer

    def test_saved_packaging_retains_original_clocks_complete_previous_and_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'copy';root.mkdir();old_pointer=self.plain_original(root)
            original=load_json(root/'output/data/release-identity.json')
            originals={p:p.read_bytes() for p in (root/'data').rglob('*.gz')}
            frozen={n:(root/'output'/n).read_bytes() for n in ('data/week.json','data/meta.json','data/verification-scope.json')}
            with patch('requests.sessions.Session.request',side_effect=AssertionError('Packaging cannot collect')):
                packaged=phase2_capture.repackage_generation(root,source_root=ROOT)
            self.assertEqual(packaged['schema_version'],'website-packaging-generation-v1')
            self.assertEqual(packaged['capture_generation_sha256'],original['generation_sha256'])
            self.assertEqual(packaged['capture_source_sha'],original['source_sha'])
            self.assertEqual(packaged['source_sha'],self.git(ROOT,'rev-parse','HEAD'))
            self.assertGreater(utc(packaged['packaged_at']),self.AT)
            self.assertTrue(all(p.read_bytes()==raw for p,raw in originals.items()))
            self.assertTrue(all((root/'output'/n).read_bytes()==raw for n,raw in frozen.items()))
            base=root/'output/data/selection-grading';working=load_json(base/'hosting.json')
            self.assertEqual(phase2_capture._manifest(base,working['previous'],root=root)[0]['pointer'],old_pointer)
            before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(phase2_capture.repackage_generation(root,source_root=ROOT),packaged)
            self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
            staged=phase2_capture.stage_pages(root,Path(directory)/'pages')
            self.assertTrue((staged/'data/selection-grading'/old_pointer['summary']['path']).exists())
            generation_path=root/'output/data/release-identity.json';health_path=root/'output/data/health.json'
            bad=copy.deepcopy(packaged);bad.pop('generation_sha256');bad['capture_source_sha']='0'*40
            gid=digest(bad);atomic_json(generation_path,dict(bad,generation_sha256=gid))
            health=load_json(health_path);health['generation_sha256']=gid;health['capture_source_sha']='0'*40;atomic_json(health_path,health)
            with self.assertRaisesRegex(IntegrityError,'retained rich|capture/packaging'):
                phase2_capture.validate_generation(root)

    def test_encoded_unchanged_saved_packaging_is_noop_and_dirty_source_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'copy';root.mkdir();self.run_live(root)
            before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            original=phase2_capture.validate_generation(root)
            self.assertEqual(phase2_capture.repackage_generation(root,source_root=ROOT),original)
            self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
            dirty=Path(directory)/'dirty-source'
            self.git(ROOT,'clone','--quiet','--shared',str(ROOT),str(dirty))
            with (dirty/'output/app.js').open('a') as handle:handle.write('\n// Fictional uncommitted control\n')
            with self.assertRaisesRegex(IntegrityError,'not the identified committed source'):
                phase2_capture.repackage_generation(root,source_root=dirty)
            self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))

    def test_staging_validates_each_complete_graph_once_per_operation_and_rechecks_later(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'writer';root.mkdir();self.run_live(root)
            self.run_live(root,self.AT+timedelta(minutes=5))
            original_validator=selection_publication.validate_publication
            calls=[]
            def checked(base,pointer):
                calls.append((str(Path(base).resolve()),digest(pointer)))
                return original_validator(base,pointer)
            with patch.object(selection_publication,'validate_publication',side_effect=checked):
                phase2_capture.stage_pages(root,Path(directory)/'pages')
            self.assertEqual(len(calls),4)  # latest+previous, source+fresh destination
            self.assertEqual(len(calls),len(set(calls)))
            base=root/'output/data/selection-grading';pointer=load_json(base/'latest.json')
            index=load_json(base/pointer['summary']['path']);part=index['summary_partitions'][-1]
            target=base/part['path'];raw=target.read_bytes();target.write_bytes(raw[:-1])
            with self.assertRaises(IntegrityError):
                phase2_capture.stage_pages(root,Path(directory)/'recheck')
            target.write_bytes(raw);phase2_capture.validate_generation(root)

    def test_existing_workflow_advisory_health_append_does_not_change_qualified_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'writer';root.mkdir();self.run_live(root)
            base=root/'output/data/selection-grading';original=(base/'hosting.json').read_bytes()
            workflow=(ROOT/'.github/workflows/hourly.yml').read_text()
            advisory=workflow.split('      - name: Record advisory outcomes',1)[1].split('      - name: Commit validated data',1)[0]
            script=textwrap.dedent(advisory.split("          python - <<'PY'\n",1)[1].rsplit('          PY',1)[0])
            subprocess.run([sys.executable,'-c',script],cwd=root,check=True,
                           env=dict(os.environ,LEGACY_OUTCOME='failure',COMPARISON_OUTCOME='success'))
            phase2_capture.validate_generation(root)
            phase2_capture.finalize_hosting(root)
            self.assertEqual((base/'hosting.json').read_bytes(),original)
            phase2_capture.stage_pages(root,Path(directory)/'pages')
            health_path=root/'output/data/health.json';health=load_json(health_path)
            health['unexpected_advisory_extension']='NOT_ALLOWED';atomic_json(health_path,health)
            with self.assertRaisesRegex(IntegrityError,'snapshot differs'):
                phase2_capture.validate_generation(root)


if __name__ == "__main__":
    unittest.main()
