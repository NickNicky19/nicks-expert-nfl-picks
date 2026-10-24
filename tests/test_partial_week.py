"""Fictional source/cutover/restart controls. HTTP is mocked; no real proof."""
import copy
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
import data_integrity_v2 as corrected
import build
import build_recorded
import partial_week as partial
import verify
from evidence import read, write
from phase2_capture import read_native_baseline
from reliability import ENGINE_PATHS, IntegrityError, atomic_json, digest, engine_hashes, load_json, stamp
from source_evidence import record_scoreboard
from test_reliability import NOW
from test_scorecard import setup
from test_source_evidence import fictional_response


def response(data):
    value = fictional_response(data["games"], week=data["week"])
    for event, game in zip(value["events"], data["games"]):
        event["competitions"][0]["competitors"] = [
            {"homeAway": side, "team": {"abbreviation": game[side]}} for side in ("home", "away")]
    return value


def save_build(root, data, at):
    def fake():
        build.sources.get_json(build.sources.ESPN + "/scoreboard", {"dates": 2026, "seasontype": 2, "week": 6})
        build.Matchups({4: {"fictional-1": {"opp": "BBB", "stats": {"gp": 1, "rec": 3}}}},
                       {player["id"]: player["pos"] for player in data["players"]})
        atomic_json(root / "output/data/week.json", data)
        atomic_json(root / "output/data/meta.json", {key: data[key] for key in ("season", "week", "generated_at")})
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at
    with patch.object(build_recorded, "datetime", Clock), patch.object(build.sources, "get_json", return_value=response(data)):
        build_recorded.record_build(root, run=fake, mode="live")
    return load_json(root / "output/data/matchup-proof.json")


def status(data, at):
    return record_scoreboard(response(data), {"dates": data["season"], "week": data["week"], "seasontype": 2}, at)


def fixture(root):
    for name in ENGINE_PATHS:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(corrected._legacy_blob(name, ROOT))
    data, _, _ = setup()
    data.update(week=6, generated_at=stamp(NOW))
    data["games"][0].update(kickoff=stamp(NOW + timedelta(hours=2)), detail="Scheduled")
    player = data["players"][0]
    player.update(opp="BBB", snap_share=.8, games_this_season=3, injury=None)
    player["props"][0].update(mf=1, mf_n=0, adj=4.8)
    data["picks"]["over"][0]["adj"] = 4.8
    old = copy.deepcopy(player)
    old.update(id="legacy-1", game_id="legacy-game", team="CCC", opp="DDD")
    data["players"].append(old)
    data["games"].append({"id": "legacy-game", "home": "CCC", "away": "DDD", "state": "post", "detail": "Final",
                          "kickoff": stamp(NOW - timedelta(hours=2))})
    pick = copy.deepcopy(data["picks"]["over"][0])
    pick.update(player_id="legacy-1", game_id="legacy-game")
    data["picks"]["over"].append(pick)
    plan = {"schema_version": partial.PLAN_VERSION, "plan_id": "FICTIONAL_FIXED_PLAN",
            "plan_prepared_at": stamp(NOW - timedelta(minutes=1)), "effective_not_before": stamp(NOW - timedelta(minutes=1)),
            "authorization_status": "PROPOSED_NOT_REGISTERED_OR_ACTIVATED", "season": 2026, "week": 6,
            "validator_contract": partial.VERSION, "engine_files": engine_hashes(root),
            "initial_complete_board_sha256": digest(data), "initial_data_pin": "a" * 40,
            "games": [{key: game[key] for key in ("id", "home", "away", "kickoff")} for game in data["games"]],
            "legacy_exemptions": [{"game_id": "legacy-game", "reason": "fictional missing origin",
                                   "forecast_contract_sha256": digest(partial.game_contract(data, "legacy-game"))}],
            "completion_status_max_age_seconds": 60, "expires_at": stamp(NOW + timedelta(days=3)),
            "full_board_verified": False, "complete_week_qualified": False, "experimental_recording_enabled": False}
    baseline_status = status(data, NOW - timedelta(minutes=2))
    plan.update(schedule_status_payload_sha256=digest(baseline_status),
                schedule_status_observed_at=baseline_status["collected_at"])
    write(root, "verification/partial-schedule-baselines", {"schema_version": "partial-schedule-baseline-v1",
          "season": 2026, "week": 6, "status": baseline_status})
    spec = {"plan": plan, "plan_sha256": digest(plan), "validator_sha256": partial.code_sha256(),
            "owner_authorization": "FICTIONAL_OWNER_AUTHORIZATION_NOT_A_REAL_APPROVAL"}
    proof = save_build(root, data, NOW)
    registration, _ = partial.register_plan(root, spec, NOW, source_sha="a" * 40, initial_board=data)
    return data, proof, spec, registration.relative_to(root).as_posix()


class PartialWeekTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data, self.proof, self.spec, self.registration = fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def record(self, at=NOW, clocks=None):
        clock = (lambda: next(clocks)) if clocks is not None else (lambda: at)
        return partial.record_bundle(self.root, self.data, self.proof, status(self.data, at), self.spec,
                                     self.registration, read_native_baseline, clock=clock)

    def consume(self, path, now=NOW):
        return partial.read_bundle(self.root, path.relative_to(self.root).as_posix(), self.spec, read_native_baseline, now=now)

    def test_legacy_plus_pregame_preserves_complete_board_and_strict_failure(self):
        original = copy.deepcopy(self.data)
        native, health, completion, scope = self.record()
        self.assertTrue(health["capture_created"])
        self.assertEqual(self.data, original)
        self.assertFalse(scope["full_board_verified"])
        self.assertFalse(scope["complete_week_qualified"])
        self.assertEqual({game["classification"] for game in scope["game_population"]},
                         {"retained_legacy_original_proof_missing", "new_pregame_original_inputs_verified"})
        self.assertEqual({row["game_id"] for row in read(native)["rows"]}, {"fictional-game"})
        self.consume(completion)
        with self.assertRaisesRegex(IntegrityError, "frozen matchup inputs missing"):
            verify.require_offline(self.root, self.data, self.proof, "live", NOW)

    def test_exact_retry_preserves_first_bytes_and_clocks(self):
        native, _, completion, _ = self.record()
        before = native.read_bytes(), completion.read_bytes()
        again, health, saved, _ = self.record(NOW + timedelta(seconds=10))
        self.assertEqual((again, saved), (native, completion))
        self.assertFalse(health["capture_created"])
        self.assertEqual((native.read_bytes(), completion.read_bytes()), before)

    def test_orphan_native_is_not_backfilled(self):
        from reliability import capture
        capture(self.data, load_json(self.root / "output/data/meta.json"), self.root, NOW, engine_hashes(self.root), "live")
        with self.assertRaisesRegex(IntegrityError, "no backfill"):
            self.record()

    def test_clock_crossing_capture_validation_scope_and_final_persistence(self):
        for crossing in (1, 2, 3, 4):
            with self.subTest(crossing=crossing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                data, proof, spec, registration = fixture(root)
                clocks = iter([NOW] * crossing + [NOW + timedelta(hours=2)] * 8)
                with self.assertRaises(IntegrityError):
                    partial.record_bundle(root, data, proof, status(data, NOW), spec, registration,
                                          read_native_baseline, clock=lambda: next(clocks))
                for completed in (root / "data" / partial.COMPLETION_LANE).rglob("*.json.gz"):
                    with self.assertRaises(IntegrityError):
                        partial.read_bundle(root, completed.relative_to(root).as_posix(), spec, read_native_baseline,
                                            now=NOW + timedelta(hours=2))

    def test_reversed_completion_clock_fails(self):
        times = iter([NOW, NOW, NOW, NOW - timedelta(seconds=1), NOW])
        with self.assertRaises(IntegrityError):
            self.record(clocks=times)

    def test_missing_corrupt_or_rehashed_originals_fail_saved_consumption(self):
        _, _, completion, _ = self.record()
        path = self.root / self.proof["latest_inputs"]
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(OSError):
            self.consume(completion)
        path.write_bytes(b"broken")
        with self.assertRaises((OSError, ValueError)):
            self.consume(completion)
        path.write_bytes(original)
        self.consume(completion)
        altered = read(path)
        altered["positions"]["fictional-1"] = "QB"
        changed = write(self.root, "verification", altered)
        self.proof["latest_inputs"] = changed.relative_to(self.root).as_posix()
        self.proof["game_origins"]["fictional-game"] = self.proof["latest_inputs"]
        with self.assertRaises(IntegrityError):
            partial.verify_scope(self.root, self.data, self.proof, status(self.data, NOW), self.spec, self.registration, NOW)

    def test_source_request_body_status_and_schedule_failures(self):
        for mutate in (
            lambda value: value["request"].update(week=5),
            lambda value: value.update(response={}),
            lambda value: value.update(collected_at=stamp(NOW - timedelta(seconds=61))),
            lambda value: value["response"]["events"][0].update(date=stamp(NOW + timedelta(hours=3))),
            lambda value: value["response"]["events"][0]["competitions"][0]["status"]["type"].update(state="unknown"),
        ):
            closing = status(self.data, NOW)
            mutate(closing)
            with self.subTest(closing=closing.get("week")), self.assertRaises((IntegrityError, KeyError)):
                partial.verify_scope(self.root, self.data, self.proof, closing, self.spec, self.registration, NOW)

    def test_legacy_contract_and_membership_cannot_change(self):
        for mutate in (
            lambda data: data["players"][1]["props"][0].update(line=3.5),
            lambda data: data["picks"]["over"].pop(),
        ):
            data = copy.deepcopy(self.data)
            mutate(data)
            proof = save_build(self.root, data, NOW)
            with self.assertRaises(IntegrityError):
                partial.verify_scope(self.root, data, proof, status(data, NOW), self.spec, self.registration, NOW)

    def test_no_dynamic_exemption_or_saved_pass_trust(self):
        _, _, completion, scope = self.record()
        modified = read(completion)
        modified["evidence_completed_at"] = stamp(NOW + timedelta(hours=2))
        modified["status"] = "PASS"
        path = write(self.root, partial.COMPLETION_LANE, modified)
        with self.assertRaises(IntegrityError):
            self.consume(path, NOW + timedelta(hours=2))
        bad = copy.deepcopy(self.spec)
        bad["plan"]["legacy_exemptions"].append({"game_id": "fictional-game", "forecast_contract_sha256": "0" * 64})
        with self.assertRaises(IntegrityError):
            partial.validate_plan(bad["plan"], bad["plan_sha256"])

    def test_frozen_successive_update_revalidates_original_and_keeps_outcomes_mutable(self):
        native, _, completion, _ = self.record()
        original = native.read_bytes(), completion.read_bytes()
        at = NOW + timedelta(hours=3)
        self.data["generated_at"] = stamp(at)
        self.data["games"][0].update(state="post", detail="Final")
        self.data["players"][0]["actual"] = {"stats": {"gp": 1, "rec": 5}}
        self.proof = save_build(self.root, self.data, at)
        _, _, next_completion, scope = self.record(at)
        self.assertIn("frozen_original_inputs_verified", [game["classification"] for game in scope["game_population"]])
        self.consume(next_completion, at)
        self.assertEqual((native.read_bytes(), completion.read_bytes()), original)
        self.data["players"][0]["actual"]["stats"]["rec"] = 6
        self.proof = save_build(self.root, self.data, at)
        _, _, corrected, _ = self.record(at)
        self.consume(corrected, at)
        self.assertEqual((native.read_bytes(), completion.read_bytes()), original)

    def test_cold_restart_requires_accessible_originals(self):
        _, _, completion, _ = self.record()
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "clean-checkout"
            shutil.copytree(self.root, clone)
            name = completion.relative_to(self.root).as_posix()
            partial.read_bundle(clone, name, self.spec, read_native_baseline, now=NOW)
            (clone / self.proof["latest_inputs"]).unlink()
            with self.assertRaises(OSError):
                partial.read_bundle(clone, name, self.spec, read_native_baseline, now=NOW)

    def test_dispatch_expiry_rollover_unknown_and_code_binding(self):
        config = {"verification_mode": partial.VERSION, "partial_week": self.spec, "experimental_recording_enabled": False}
        self.assertEqual(partial.dispatch(config, self.data, NOW), "partial")
        with self.assertRaises(IntegrityError):
            partial.dispatch(config, self.data, NOW + timedelta(days=3))
        next_week = dict(self.data, week=7)
        self.assertEqual(partial.dispatch(config, next_week, NOW + timedelta(days=5)), "strict")
        with self.assertRaises(IntegrityError):
            partial.dispatch(dict(config, verification_mode="guess-after-strict-failure"), self.data, NOW)
        config["partial_week"] = dict(self.spec, validator_sha256="0" * 64)
        with self.assertRaises(IntegrityError):
            partial.dispatch(config, self.data, NOW)

    def test_registration_actual_clock_and_original_bytes_are_preserved(self):
        plan_before = copy.deepcopy(self.spec["plan"])
        path, registration = partial.register_plan(self.root, self.spec, NOW + timedelta(seconds=5),
                                                    source_sha="b" * 40, initial_board=self.data)
        self.assertEqual(path.relative_to(self.root).as_posix(), self.registration)
        self.assertEqual(registration["registered_at"], stamp(NOW))
        self.assertEqual(self.spec["plan"], plan_before)
        wrong = copy.deepcopy(self.data)
        wrong["players"][1]["props"][0]["line"] = 2.5
        with self.assertRaises(IntegrityError):
            partial.register_plan(self.root, self.spec, NOW, source_sha="a" * 40, initial_board=wrong)

    def test_retry_rejects_current_origin_corruption_and_contradictory_status(self):
        self.record()
        proof = copy.deepcopy(self.proof)
        proof["game_origins"]["fictional-game"] = None
        with self.assertRaises(IntegrityError):
            partial.record_bundle(self.root, self.data, proof, status(self.data, NOW), self.spec,
                                  self.registration, read_native_baseline, clock=lambda: NOW)
        contradictory = copy.deepcopy(self.data)
        closing = status(contradictory, NOW)
        closing["response"]["events"][0]["competitions"][0]["status"]["type"]["completed"] = True
        closing = record_scoreboard(closing["response"], closing["request"], NOW)
        with self.assertRaises(IntegrityError):
            partial.record_bundle(self.root, self.data, self.proof, closing, self.spec,
                                  self.registration, read_native_baseline, clock=lambda: NOW)

    def test_saved_completion_cannot_move_to_a_different_period(self):
        _, _, path, _ = self.record()
        completion = read(path)
        completion.update(season=2027, week=9)
        moved = write(self.root, partial.COMPLETION_LANE, completion)
        with self.assertRaisesRegex(IntegrityError, "period"):
            self.consume(moved)

    def test_required_original_fixed_schedule_source_is_not_a_digest_only(self):
        registration = read(self.root / self.registration)
        source = self.root / registration["schedule_status_receipt"]
        raw = source.read_bytes()
        source.unlink()
        with self.assertRaises(OSError):
            partial._registration(self.root, self.registration, self.spec, NOW)
        source.write_bytes(b"corrupt")
        with self.assertRaises((ValueError, OSError)):
            partial._registration(self.root, self.registration, self.spec, NOW)
        source.write_bytes(raw)
        partial._registration(self.root, self.registration, self.spec, NOW)

    def test_frozen_injury_change_does_not_rewrite_historical_top_eligibility(self):
        self.record()
        at = NOW + timedelta(hours=3)
        self.data["generated_at"] = stamp(at)
        self.data["games"][0].update(state="post", detail="Final")
        self.data["players"][0].update(injury="Out", snap_share=0, proj_ppr=0)
        self.proof = save_build(self.root, self.data, at)
        _, _, completed, _ = self.record(at)
        self.consume(completed, at)
        self.assertEqual(self.data["players"][0]["injury"], "Out")
        self.assertEqual(len(self.data["picks"]["over"]), 2)


if __name__ == "__main__":
    unittest.main()
