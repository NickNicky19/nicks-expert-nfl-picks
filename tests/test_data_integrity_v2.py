"""Fictional presence/source controls. No live requests or performance claims."""
import copy
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
import build
import build_recorded
import data_integrity_v2 as corrected
import grade
import matchup
import phase2_capture
import reliability
import release_mode
import scorecard
import scoring
import selection_report
from evidence import read, write
from test_reliability import NOW, fixture
from test_scorecard import setup

DI_NOW = NOW + timedelta(days=8)  # Fictional modern era, after the unchanged registrations.


def corrected_fixture(root):
    """Actual corrected builder/recorder inputs; wholly fictional HTTP and clocks."""
    from test_partial_week import status, response
    copy_corrected_engine(root)
    (root / "config").mkdir(exist_ok=True)
    for name in ("release-mode.json", "timing-policy.json", "sleeper-rules-provenance.json", "evaluation-policy.json"):
        shutil.copyfile(ROOT / "config" / name, root / "config" / name)
    (root / "tools").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "tools/rec_half_registration_v1.json", root / "tools/rec_half_registration_v1.json")
    (root / "output").mkdir(exist_ok=True)
    for name in ("app.js", "index.html", "style.css", "reliability-ui.js", "recovery.html"):
        shutil.copyfile(ROOT / "output" / name, root / "output" / name)
    data, _, _ = setup()
    data.update(week=6, generated_at=reliability.stamp(DI_NOW), scoring=scoring.PPR, categories=scoring.CATEGORIES)
    data["games"][0].update(kickoff=reliability.stamp(DI_NOW + timedelta(hours=2)), detail="Scheduled")
    data["picks"] = {"over": [], "under": []}
    player = data["players"][0]
    player.update(opp="BBB", snap_share=.8, injury=None, games_this_season=2)
    raw = {"rec": 4.876, "rec_yd": 22.227, "rush_yd": 0, "rush_td": .004, "rec_td": .004,
           "pts_ppr": None, "rush_att": True}
    history = {4: {"fictional-1": actual_row({"gp": 1, "rec": None, "rec_yd": -2, "rush_yd": 0})}}
    history[4]["fictional-1"]["stats"]["_presence"]["source_context"]["week"] = 4
    projected = build.projection_components(raw)
    player["props"] = build.player_props(player, projected,
        build.build_history({(2026, 4): history[4]}).get(player["id"], []), 2026, "BBB", matchup.Matchups(history, {player["id"]: "WR"}))
    actual_history = build.build_history({(2026, 4): history[4]}).get(player["id"], [])
    player.update(proj={k:v for k,v in projected.items() if k != "pts_ppr"},proj_ppr=projected.get("pts_ppr"),
                  proj_half=projected.get("pts_half_ppr"),games_this_season=len(actual_history),
                  snap_share=build.snap_share(actual_history),avg_ppr=build.known_average(actual_history,"WR"),
                  avg_half=build.known_average(actual_history,"WR",half=True),log=build.game_log("WR",actual_history))
    kicker = {**copy.deepcopy(player), "id": "fictional-kicker", "pos": "K", "props": []}
    data["players"].append(kicker)
    source = [{"player_id": player["id"], "game_id": "fictional-game", "stats": raw}]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return DI_NOW
    def replies(url, *args, **kwargs):
        return response(data) if url.endswith("/scoreboard") else copy.deepcopy(source)
    def run():
        build.sources.get_json(build.sources.ESPN + "/scoreboard", {"dates": 2026, "week": 6, "seasontype": 2})
        build.sources.get_json("https://api.sleeper.app/projections/nfl/2026/6")
        build.Matchups(history, {player["id"]: "WR"})
        reliability.atomic_json(root / "output/data/week.json", data)
        reliability.atomic_json(root / "output/data/meta.json", {key: data[key] for key in ("season", "week", "generated_at")})
    with patch.object(build_recorded, "datetime", Clock), patch.object(build.sources, "get_json", side_effect=replies):
        original = build_recorded.record_build(root, run=run, model=corrected.MODEL)
    baseline = status(data, DI_NOW - timedelta(minutes=2))
    write(root, "verification/partial-schedule-baselines", {"schema_version": "partial-schedule-baseline-v1",
          "season": 2026, "week": 6, "status": baseline})
    plan = {"schema_version": corrected.PLAN, "plan_id": "FICTIONAL_CORRECTED_PLAN_NOT_ACTIVATION",
            "model": corrected.MODEL, "season": 2026, "week": 6,
            "plan_prepared_at": reliability.stamp(DI_NOW - timedelta(minutes=1)),
            "effective_not_before": reliability.stamp(DI_NOW - timedelta(minutes=1)),
            "expires_at": reliability.stamp(DI_NOW + timedelta(days=3)), "validator_contract": corrected.VALIDATOR,
            "engine_files": corrected.engine_files(root), "initial_complete_board_sha256": reliability.digest(data),
            "games": [{key: game[key] for key in ("id", "home", "away", "kickoff")} for game in data["games"]],
            "legacy_exemptions": [], "completion_status_max_age_seconds": 60,
            "full_board_verified": False, "complete_week_qualified": False, "experimental_recording_enabled": False,
            "schedule_status_payload_sha256": reliability.digest(baseline),
            "schedule_status_observed_at": baseline["collected_at"]}
    spec = {"plan": plan, "plan_sha256": reliability.digest(plan), "validator_sha256": corrected.code_sha256(),
            "owner_authorization": "FICTIONAL_ONLY_NOT_REAL_PERMISSION"}
    original_board = write(root, "verification/partial-plan-boards", {"schema_version": "partial-plan-board-v1",
                           "season": 2026, "week": 6, "board": copy.deepcopy(data)})
    spec["initial_board_receipt"] = original_board.relative_to(root).as_posix()
    config = {"capture_enabled": True, "experimental_recording_enabled": False,
              "challenger_production_enabled": False, "production_model": corrected.MODEL,
              "verification_mode": corrected.VALIDATOR, "partial_week": spec}
    reliability.atomic_json(root / "config/phase2.json", config)
    reliability.atomic_json(root / "data/cache/stats_2026_06.json", {})
    registration, _ = corrected.register_plan(root, spec, DI_NOW, source_sha=corrected.recording_source(), initial_board=data)
    return data, reliability.load_json(root / "output/data/matchup-proof.json"), spec, registration.relative_to(root).as_posix(), original


def actual_row(stats, *, context=True):
    source = {"player_id": "fictional-1", "team": "AAA", "opponent": "BBB", "stats": stats}
    attribution = {"adapter": "sleeper-week-stats-v1", "season": 2026, "week": 5} if context else None
    return build.trim_stats([source], source_context=attribution)["fictional-1"]


def copy_corrected_engine(root):
    for name in corrected.V2_PATHS:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())


class PresenceTests(unittest.TestCase):
    def test_history_display_retains_presence_and_invalid_snap_share_stays_unknown(self):
        entry = actual_row({"gp": 1, "rec": None, "off_snp": "unknown", "tm_off_snp": 50}, context=False)
        games = [{"season": 2026, "week": 5, "opp": "BBB", "stats": entry["stats"]}]
        log = build.game_log("WR", games)[0]
        self.assertIn("_presence", log["st"])
        self.assertIsNone(log["pts"])
        self.assertIsNone(scoring.ppr_points(log["st"]))
        self.assertIsNone(build.snap_share(games))

    def test_future_projection_output_keeps_zero_null_and_known_siblings(self):
        rows = [{"player_id":"fictional-1","team":"AAA","opponent":"BBB",
                 "stats":{"rec":None,"rec_yd":0,"rush_yd":2.25,"pts_ppr":None}}]
        with patch.object(build.sources, "week_projections", return_value=rows):
            result = build.future_weeks(2026, 17, [{"id":"fictional-1"}], {"fictional-1":{"team":"AAA","pos":"WR","name":"Fictional"}})
        record = result["players"]["fictional-1"][0]
        self.assertIsNone(record["st"]["rec"])
        self.assertEqual(record["st"]["rec_yd"], 0)
        self.assertEqual(record["st"]["rush_yd"], 2.25)
        self.assertIn("_presence", record["st"])
        self.assertIsNone(scoring.ppr_points(record["st"], projection=True))

    def test_invalid_actual_domains_do_not_cancel_into_known_totals(self):
        for invalid in (-1, .5, True, "bad", float("inf")):
            stats = actual_row({"gp": 1, "rec": invalid})["stats"]
            self.assertEqual(scoring.component(stats, "rec")["state"], "invalid_value")
            self.assertIsNone(scoring.stat_value("fpts", stats))
        self.assertIsNone(scoring.stat_value("anytime_td", actual_row({"gp": 1, "rush_td": -1, "rec_td": 1})["stats"]))
        self.assertEqual(scoring.component({"rec": .5}, "rec", projection=True)["value"], .5)

    def test_invalid_participation_is_local_to_modern_row(self):
        for value in (True, "bad", -1, .5):
            invalid = actual_row({"gp": value, "rec": 2})
            self.assertEqual(grade.participation(invalid), "unresolved")
        self.assertEqual(grade.participation(actual_row({"gp": 1, "rec": 2})), "played")

    def test_nonfinite_original_components_have_lossless_invalid_representation(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            entry = actual_row({"gp": 1, "rec": value})
            self.assertEqual(scoring.component(entry["stats"], "rec")["state"], "invalid_value")
            reliability.digest(entry)
            self.assertNotEqual(corrected.model_input_hash({"rec": value}), corrected.model_input_hash({"rec": scoring.retained_value(value)}))
    def test_trim_keeps_reported_zero_null_negative_and_source_presence(self):
        stats = {"gp": 1, "rec": None, "rush_yd": -2, "rec_yd": 0}
        entry = actual_row(stats)
        for key, value in stats.items():
            self.assertEqual(entry["stats"][key], value)
        self.assertEqual(entry["stats"]["_presence"]["original_row"]["stats"], stats)
        self.assertIsNone(scoring.stat_value("rec", entry["stats"]))
        self.assertEqual(scoring.stat_value("rec_yd", entry["stats"]), 0)

    def test_cache_roundtrip_preserves_unknown_and_zero_without_refetch(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build, "CACHE", Path(directory)):
            rows = [{"player_id": "fictional-1", "team": "AAA", "opponent": "BBB",
                     "stats": {"gp": 1, "rec": None, "rush_yd": 0}}]
            with patch.object(build.sources, "week_stats", return_value=rows):
                fresh = build.week_stats(2026, 5, True)
            original = (Path(directory) / "stats_2026_05.json").read_bytes()
            with patch.object(build.sources, "week_stats", side_effect=AssertionError("No refetch")):
                saved = build.week_stats(2026, 5, False)
            self.assertEqual(fresh, saved)
            self.assertEqual(original, (Path(directory) / "stats_2026_05.json").read_bytes())
            self.assertIsNone(scoring.stat_value("rec", saved["fictional-1"]["stats"]))

    def test_legacy_sparse_assumption_is_distinct_from_supported_attributed_adapter(self):
        legacy = scoring.component({"gp": 1}, "rec")
        self.assertEqual(legacy["value"], 0)
        self.assertIn("legacy_assumption", legacy["state"])
        self.assertIsNone(scoring.component(actual_row({"gp": 1}, context=False)["stats"], "rec")["value"])
        supported = scoring.component(actual_row({"gp": 1})["stats"], "rec")
        self.assertEqual(supported["value"], 0)
        self.assertNotEqual(supported["state"], "reported_zero")
        self.assertEqual(scoring.component({"rec": 0}, "rec")["state"], "reported_zero")

    def test_label_or_participation_alone_does_not_authenticate_zero(self):
        for metadata in ({"version": corrected.PRESENCE}, {"version": corrected.PRESENCE,
                         "sparse_contract": scoring.LEGACY_SPARSE_ASSUMPTION, "complete": True}):
            self.assertIsNone(scoring.component({"gp": 1, "_presence": metadata}, "rec")["value"])
        row = actual_row({"gp": 1})
        row["stats"]["_presence"]["original_row"]["stats"]["rec"] = None
        self.assertIsNone(scoring.component(row["stats"], "rec")["value"])

    def test_projection_missing_ppr_preserves_numeric_siblings_and_invalid_components(self):
        rows = [{"player_id": "a", "stats": {"pts_ppr": None, "rec": 2.5, "rec_yd": 21}},
                {"player_id": "b", "stats": {"pts_ppr": 12, "rec": None, "rush_yd": True}}]
        with patch.object(build.sources, "week_projections", return_value=rows):
            values = build.projections(2026, 6)
        self.assertEqual(values["a"]["rec"], 2.5)
        self.assertIsNone(values["b"]["rec"])
        self.assertIn("rush_yd", values["b"]["_presence"]["invalid_fields"])
        self.assertIsNone(scoring.stat_value("rush_att", values["a"], projection=True))
        self.assertIsNone(scoring.stat_value("fpts", values["a"], projection=True))

    def test_component_completeness_direct_provider_total_and_signed_ppr(self):
        self.assertIsNone(scoring.stat_value("rush_rec_yd", {"rush_yd": None, "rec_yd": 20}))
        self.assertEqual(scoring.stat_value("rec_yd", {"rush_yd": None, "rec_yd": 20}), 20)
        self.assertIsNone(scoring.ppr_points({"rec": None, "rec_yd": 20, "pts_ppr": 2}))
        self.assertEqual(scoring.ppr_points({"rush_yd": -2, "fum_lost": 1}), -2.2)
        self.assertEqual(scoring.ppr_points({"gp": 1, "rec": 0}), 0)

    def test_projection_absence_and_td_zero_remain_distinct(self):
        player = {"pos": "WR"}
        for raw, probability in (({}, None), ({"rush_td": None, "rec_td": 0}, None),
                                 ({"rush_td": 0, "rec_td": 0}, 0.0)):
            props = build.player_props(player, raw, [], 2026, "BBB", matchup.Matchups({}, {}))
            td = next(prop for prop in props if prop["key"] == "anytime_td")
            self.assertEqual(td["td_chance"], probability)

    def test_unknown_history_does_not_inflate_category_sample_or_become_zero(self):
        weeks = {1: {"a": {"opp": "BBB", "stats": {"gp": 1, "rec": None, "rec_yd": 20}}},
                 2: {"a": {"opp": "CCC", "stats": {"gp": 1, "rec": 4, "rec_yd": 20}}}}
        model = matchup.Matchups(weeks, {"a": "WR"})
        self.assertEqual(model.factor("BBB", "WR", "rec", 4), (1.0, 0))
        self.assertEqual(model.factor("BBB", "WR", "rec_yd", 20), (1.0, 1))


class SelectorContractTests(unittest.TestCase):
    def test_closed_selector_preserves_legacy_and_rejects_invalid_combinations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(release_mode.read_phase2(root))
            path = root / "config/phase2.json"
            legacy = {"capture_enabled": True, "production_model": "original_sleeper_matchup_baseline",
                      "challenger_production_enabled": False}
            for enabled in (True, False):
                reliability.atomic_json(path, dict(legacy, capture_enabled=enabled))
                self.assertIs(release_mode.read_phase2(root), enabled)
            modern = dict(legacy, production_model=corrected.MODEL, verification_mode=corrected.VALIDATOR,
                          experimental_recording_enabled=False)
            for enabled in (True, False):
                reliability.atomic_json(path, dict(modern, capture_enabled=enabled))
                self.assertIs(release_mode.read_phase2(root), enabled)
            for value in ({}, [], dict(legacy, capture_enabled=1), dict(legacy, capture_enabled="false"),
                          dict(legacy, challenger_production_enabled=True), dict(legacy, production_model="unknown"),
                          dict(legacy, verification_mode=corrected.VALIDATOR),
                          dict(modern, verification_mode="strict-full-board-v1"),
                          dict(modern, experimental_recording_enabled=True),
                          dict(modern, challenger_production_enabled=True)):
                reliability.atomic_json(path, value)
                with self.assertRaises(ValueError):
                    release_mode.read_phase2(root)

    def test_cli_recovery_output_and_checked_in_configuration_remain_original(self):
        for path in ("config/phase2.json", "config/release-mode.json"):
            self.assertEqual((ROOT / path).read_bytes(), corrected._legacy_blob(path))
        self.assertIs(reliability.load_json(ROOT / "config/phase2.json")["experimental_recording_enabled"], False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            shutil.copyfile(ROOT / "tools/release_mode.py", root / "tools/release_mode.py")
            for mode, enabled in (("phase1", "true"), ("original", "false")):
                reliability.atomic_json(root / "config/release-mode.json", {"mode": mode})
                reliability.atomic_json(root / "config/phase2.json", {"capture_enabled": True,
                    "production_model": "original_sleeper_matchup_baseline", "challenger_production_enabled": False})
                result = subprocess.check_output([sys.executable, "-B", str(root / "tools/release_mode.py")], text=True)
                self.assertEqual(result, f"mode={mode}\nphase2_enabled={enabled}\n")

    def test_invalid_optional_component_keeps_independent_observation(self):
        for invalid in (True, "bad", float("inf"), float("nan")):
            self.assertIsNone(scoring.stat_value("rec", {"rec": invalid}))
            self.assertEqual(scoring.stat_value("rec_yd", {"rec": invalid, "rec_yd": -2}), -2)


class CrossRecordTests(unittest.TestCase):
    def inputs(self):
        _, receipt, policy = setup()
        pairs, coverage = scorecard.paired_forecasts([receipt], policy, {"test": "fixture"})
        key, forecast = next(iter(pairs.items()))
        outcome = dict(forecast, status="resolved", actual=3, week_confirmed_complete=True)
        return pairs, coverage, policy, key, forecast, outcome

    def test_every_identity_field_and_wrong_map_key_is_quarantined(self):
        for field in ("season", "week", "game_id", "player_id", "category", "team"):
            pairs, coverage, policy, key, forecast, outcome = self.inputs()
            outcome[field] = outcome[field] + 1 if type(outcome[field]) is int else outcome[field] + "-other"
            original = copy.deepcopy(outcome)
            report = scorecard.score(pairs, {key: outcome}, coverage, policy)
            row = report["rows"][0]
            self.assertEqual(row["evaluation_status"], "unresolved", field)
            self.assertIsNone(row["actual"])
            self.assertFalse(row["week_confirmed_complete"])
            self.assertEqual(outcome, original)
        pairs, coverage, policy, key, forecast, outcome = self.inputs()
        wrong = (2027, *key[1:])
        self.assertEqual(scorecard.score({wrong: forecast}, {wrong: outcome}, coverage, policy)["rows"][0]["evaluation_status"], "unresolved")

    def test_schedule_classification_only_after_full_identity_and_equal_utc(self):
        _, _, _, key, forecast, outcome = self.inputs()
        outcome["kickoff"] = reliability.utc(forecast["kickoff"]).isoformat()
        self.assertEqual(scorecard.cross_record_binding(forecast, outcome, key=key)["status"], "bound")
        outcome["kickoff"] = reliability.stamp(reliability.utc(forecast["kickoff"]) + timedelta(minutes=1))
        self.assertEqual(scorecard.cross_record_binding(forecast, outcome, key=key)["status"], "schedule_changed")
        outcome["team"] = "OTHER"
        self.assertEqual(scorecard.cross_record_binding(forecast, outcome, key=key)["status"], "identity_mismatch")
        for missing in (None, "2026-10-10T20:00:00"):
            outcome.update(team=forecast["team"], kickoff=missing)
            self.assertEqual(scorecard.cross_record_binding(forecast, outcome, key=key)["status"], "identity_mismatch")

    def test_all_category_and_selection_consumers_reject_the_same_wrong_outcome(self):
        pairs, _, _, key, forecast, outcome = self.inputs()
        outcome["team"] = "OTHER"
        extended = scorecard.evaluate_descriptive(pairs, pairs, {key: outcome}, {})
        self.assertEqual(extended["rows"][0]["evaluation_status"], "unresolved")
        decision = dict(forecast, action="SELECT", side="over", line=4.5)
        rows = selection_report.grade_decisions([decision], {key: outcome})
        self.assertEqual(rows[0]["result"], "unresolved")
        self.assertEqual(rows[0]["outcome_provenance"], "identity_quarantined")
        self.assertFalse(rows[0]["week_confirmed_complete"])


class SourceVersionTests(unittest.TestCase):
    def test_amended_names_and_original_validator_bytes_are_distinct(self):
        self.assertEqual(corrected.INPUTS, "matchup-inputs-v3")
        for name in ("tools/verify.py", "tools/partial_week.py", "tools/point_challenger.py", "tools/rec_half_registration_v1.json"):
            self.assertEqual((ROOT / name).read_bytes(), corrected._legacy_blob(name))
        with self.assertRaises(reliability.IntegrityError):
            reliability.engine_hashes(ROOT)
        self.assertEqual(reliability.engine_hashes(ROOT, version=corrected.MODEL), corrected.V2_SOURCE_SHA256)

    def test_same_size_restored_mtime_mutation_cannot_inherit_source_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_corrected_engine(root)
            self.assertEqual(corrected.engine_files(root), corrected.V2_SOURCE_SHA256)
            path = root / "pull/scoring.py"
            before, stat = path.read_bytes(), path.stat()
            path.write_bytes(before.replace(b"import math", b"import cmath", 1)[:len(before)])
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            with self.assertRaises(reliability.IntegrityError):
                corrected.engine_files(root)

    def test_legacy_original_inputs_use_retained_source_process(self):
        from test_matchup_proof import fixture as proof_fixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, _, inputs, _ = proof_fixture(root)
            inputs["engine_files"] = corrected.legacy_engine_hashes()
            path = write(root, "verification", inputs)
            result = corrected.legacy_recorded_inputs(root, path.relative_to(root).as_posix(), 2026, 3,
                                                       mode="replay", observed_at=NOW)
            self.assertEqual(result, inputs)
            changed = dict(inputs, schema_version=corrected.INPUTS)
            path = write(root, "verification", changed)
            with self.assertRaises(reliability.IntegrityError):
                corrected.legacy_recorded_inputs(root, path.relative_to(root).as_posix(), 2026, 3, mode="replay", observed_at=NOW)

    def test_new_native_identity_is_not_admitted_to_registered_comparator(self):
        data, meta = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_corrected_engine(root)
            path, _ = reliability.capture(data, meta, root, NOW, corrected.engine_files(root), mode="live", model=corrected.MODEL)
            native = phase2_capture.read_native_baseline(path, root, now=NOW)
            self.assertEqual(native["schema_version"], corrected.NATIVE)
            _, _, policy = setup()
            pairs, coverage = scorecard.paired_forecasts([native], policy, corrected.legacy_engine_hashes())
            self.assertFalse(pairs)
            self.assertEqual(coverage["excluded"]["corrected_model_outside_registered_experiment"], len(native["rows"]))
            malformed = dict(native, schema_version="baseline-capture-v1")
            with self.assertRaises(reliability.IntegrityError):
                corrected.native_contract(malformed)

    def test_shadow_saved_evaluation_is_unqualified_and_cannot_feed_public_metrics(self):
        data, _ = fixture()
        _, _, policy = setup()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = {"categories": {"rec": {"n": 999}}, "promotion": {"enabled": True}, "completed_weeks": 100}
            with patch.object(phase2_capture, "evaluate", return_value=copy.deepcopy(fake)):
                diagnostic = phase2_capture.probability_report(root, policy, include_registry=False)
            self.assertEqual(diagnostic["qualification"], "KNOWN_UNGUARDED_JOIN / NOT_CERTIFIED")
            self.assertFalse(diagnostic["qualified_accuracy"])
            self.assertFalse(diagnostic["promotion_eligible"])
            base = {"categories": {}, "coverage": {}, "outcome_status": {}}
            before = phase2_capture.public_scorecard(base, data, "a" * 40)
            after = phase2_capture.public_scorecard(dict(base, shadow=diagnostic), data, "a" * 40)
            self.assertNotEqual(before.pop("report_sha256"), after.pop("report_sha256"))
            self.assertEqual(before, after)


class CorrectedOperationalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data, self.proof, self.spec, self.registration, self.original = corrected_fixture(self.root)

    def record(self, at=DI_NOW, clock=None):
        from test_partial_week import status
        return corrected.record_bundle(self.root, self.data, self.proof, status(self.data, at), self.spec,
                                       self.registration, clock=clock or (lambda: at))

    def test_actual_inputs_native_scope_clean_restart_and_local_numeric_pairing(self):
        from test_partial_week import status
        inputs = corrected.recorded_inputs(self.root, self.original.relative_to(self.root).as_posix(), 2026, 6, mode="live", observed_at=DI_NOW)
        self.assertEqual(inputs["schema_version"], "matchup-inputs-v3")
        self.assertEqual(inputs["projection_input_components"]["fictional-1"]["stats"]["rec"], 4.876)
        native, _, completion, scope = self.record()
        captured = phase2_capture.read_native_baseline(native, self.root, now=DI_NOW)
        first, pairs, _ = scorecard.descriptive_forecasts([captured], corrected.V2_SOURCE_SHA256, DI_NOW, model_version=corrected.MODEL)
        self.assertIn((2026, 6, "fictional-game", "fictional-1", "rec"), pairs)
        self.assertEqual(first[(2026, 6, "fictional-game", "fictional-1", "anytime_td")]["raw_projection"], 0)
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "restart"
            shutil.copytree(self.root, clone)
            self.assertEqual(corrected.read_bundle(clone, completion.relative_to(self.root).as_posix(), self.spec, now=DI_NOW)[1], scope)
        before = native.read_bytes(), completion.read_bytes()
        again, health, saved, _ = self.record(DI_NOW + timedelta(seconds=5))
        self.assertFalse(health["capture_created"])
        self.assertEqual((again.read_bytes(), saved.read_bytes()), before)
        public = corrected.public_scope(scope, read(completion))
        self.assertEqual(public["schema_version"], "partial-week-public-scope-v1")
        self.assertEqual(public["output_sha256"], reliability.digest(self.data))

    def test_mixed_original_frozen_corrected_new_and_legacy_missing_proof(self):
        import test_partial_week as old
        with tempfile.TemporaryDirectory() as directory:
            prior = Path(directory)
            original_setup = old.setup
            def renamed():
                data, receipt, policy = original_setup()
                data["games"][0]["id"] = "v1-frozen-game"
                data["players"][0].update(id="v1-frozen-player",game_id="v1-frozen-game")
                for picks in data["picks"].values():
                    for pick in picks: pick.update(player_id="v1-frozen-player",game_id="v1-frozen-game")
                return data, receipt, policy
            with patch.object(old, "setup", side_effect=renamed):
                legacy, legacy_proof, legacy_spec, legacy_registration = old.fixture(prior)
            _, _, old_completion, _ = old.partial.record_bundle(prior, legacy, legacy_proof, old.status(legacy,NOW),
                legacy_spec, legacy_registration, phase2_capture.read_native_baseline, clock=lambda:NOW)
            corrected.legacy_bundle(prior,old_completion.relative_to(prior).as_posix(),legacy_spec,now=DI_NOW)
            preserved = {}
            for path in (prior / "data").rglob("*"):
                if not path.is_file(): continue
                target = self.root / path.relative_to(prior)
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists(): self.assertEqual(target.read_bytes(),path.read_bytes())
                else: target.write_bytes(path.read_bytes())
                preserved[target.relative_to(self.root)] = target.read_bytes()
            mixed = copy.deepcopy(self.data)
            mixed["games"] += copy.deepcopy(legacy["games"])
            next(g for g in mixed["games"] if g["id"]=="v1-frozen-game").update(state="post",detail="Final")
            mixed["players"] += copy.deepcopy(legacy["players"])
            for side in mixed["picks"]: mixed["picks"][side] += copy.deepcopy(legacy["picks"][side])
            raw = read(self.original)
            raw.update(week_data=mixed,output_sha256=reliability.digest(mixed))
            raw["game_status"]["2026_06"] = old.status(mixed,DI_NOW)
            latest = write(self.root,"verification",raw).relative_to(self.root).as_posix()
            proof = {"schema_version":corrected.PROOF,"output_sha256":reliability.digest(mixed),"latest_inputs":latest,
                     "game_origins":{"fictional-game":latest,"v1-frozen-game":legacy_proof["game_origins"]["v1-frozen-game"],"legacy-game":None}}
            plan = copy.deepcopy(self.spec["plan"])
            schedule = old.status(mixed,DI_NOW-timedelta(minutes=2))
            write(self.root,"verification/partial-schedule-baselines",{"schema_version":"partial-schedule-baseline-v1",
                  "season":2026,"week":6,"status":schedule})
            plan.update(plan_id="FICTIONAL_MIXED_VERSION_PLAN",initial_complete_board_sha256=reliability.digest(mixed),
                games=[{k:g[k] for k in ("id","home","away","kickoff")} for g in mixed["games"]],
                legacy_exemptions=copy.deepcopy(legacy_spec["plan"]["legacy_exemptions"]),
                schedule_status_payload_sha256=reliability.digest(schedule),schedule_status_observed_at=schedule["collected_at"])
            spec = dict(self.spec,plan=plan,plan_sha256=reliability.digest(plan))
            registration,_=corrected.register_plan(self.root,spec,DI_NOW,source_sha=corrected.recording_source(),initial_board=mixed)
            reliability.atomic_json(self.root/"output/data/week.json",mixed)
            with patch.object(corrected,"legacy_bundle",wraps=corrected.legacy_bundle) as dispatch:
                native,_,completed,scope=corrected.record_bundle(self.root,mixed,proof,old.status(mixed,DI_NOW),spec,
                    registration.relative_to(self.root).as_posix(),clock=lambda:DI_NOW)
                corrected.read_bundle(self.root,completed.relative_to(self.root).as_posix(),spec,now=DI_NOW)
                self.assertGreater(dispatch.call_count,0)
            self.assertEqual({r["game_id"] for r in read(native)["rows"]},{"fictional-game"})
            self.assertEqual({r["classification"] for r in scope["game_population"]},
                {"new_pregame_original_inputs_verified","frozen_original_inputs_verified","retained_legacy_original_proof_missing"})
            frozen=next(r for r in scope["game_population"] if r["game_id"]=="v1-frozen-game")
            self.assertEqual(frozen["completed_origin_receipt"],old_completion.relative_to(prior).as_posix())
            for name,bytes_ in preserved.items(): self.assertEqual((self.root/name).read_bytes(),bytes_)
            corrupt=copy.deepcopy(mixed)
            next(p for p in corrupt["players"] if p["id"]=="v1-frozen-player")["props"][0]["line"] += 1
            with self.assertRaises(reliability.IntegrityError):
                corrected.verify_scope(self.root,corrupt,proof,old.status(corrupt,DI_NOW),spec,registration.relative_to(self.root).as_posix(),DI_NOW)

    def test_rehashed_component_provenance_and_source_are_rejected(self):
        for field, value in (("collected_at", reliability.stamp(DI_NOW + timedelta(seconds=1))),
                             ("source", "https://invalid.example/other"), ("source_response_sha256", "f" * 64)):
            changed = read(self.original)
            changed["projection_input_components"]["fictional-1"][field] = value
            path = write(self.root, "verification", changed)
            with self.assertRaises(reliability.IntegrityError):
                corrected.recorded_inputs(self.root, path.relative_to(self.root).as_posix(), 2026, 6, observed_at=DI_NOW)

    def test_rehashed_provider_and_eligibility_metadata_cannot_replace_unknown_inputs(self):
        from test_partial_week import status
        for field,value in (("proj_ppr",99),("snap_share",.9),("games_this_season",99),
                            ("proj",{"rec":99})):
            saved = read(self.original)
            saved["week_data"]["players"][0][field] = value
            saved["output_sha256"] = reliability.digest(saved["week_data"])
            latest = write(self.root,"verification",saved).relative_to(self.root).as_posix()
            proof = dict(self.proof,latest_inputs=latest,output_sha256=saved["output_sha256"],
                         game_origins={"fictional-game":latest})
            with self.assertRaises(reliability.IntegrityError):
                corrected.verify_scope(self.root,saved["week_data"],proof,status(self.data,DI_NOW),self.spec,self.registration,DI_NOW)

    def test_unknown_or_started_closing_status_cannot_create_new_claim(self):
        from test_partial_week import status
        for state in ("in", "post"):
            changed = copy.deepcopy(self.data)
            changed["games"][0]["state"] = state
            closing = status(changed, DI_NOW)
            with self.assertRaises(reliability.IntegrityError):
                corrected.verify_scope(self.root, self.data, self.proof, closing, self.spec, self.registration, DI_NOW)

    def test_expensive_completion_cutoff_failure_stays_unqualified(self):
        clocks = iter([DI_NOW, DI_NOW, DI_NOW, DI_NOW, DI_NOW + timedelta(hours=2)] + [DI_NOW + timedelta(hours=2)] * 5)
        with self.assertRaises(reliability.IntegrityError):
            self.record(clock=lambda: next(clocks))
        for path in (self.root / "data/verification/partial-completions").rglob("*.json.gz"):
            with self.assertRaises(reliability.IntegrityError):
                corrected.read_bundle(self.root, path.relative_to(self.root).as_posix(), self.spec, now=DI_NOW + timedelta(hours=2))

    def test_corrected_updater_report_health_and_recorders_remain_separate(self):
        from test_partial_week import status
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return DI_NOW
        with patch.object(phase2_capture, "datetime", Clock), \
                patch.object(phase2_capture, "_closing_status", return_value=status(self.data, DI_NOW)), \
                patch.object(phase2_capture, "run_point_candidate", side_effect=AssertionError("inactive point recorder")), \
                patch.object(phase2_capture, "make_shadow", side_effect=AssertionError("inactive shadow recorder")):
            report, health = phase2_capture.run_capture(self.root)
        self.assertIsNone(health["phase2"]["shadow_receipt"])
        self.assertEqual(health["phase2"]["production_model"], corrected.MODEL)
        self.assertFalse(report["shadow"]["qualified_accuracy"])
        phase2_capture.validate_generation(self.root)
        self.assertEqual((self.root / "tools/rec_half_registration_v1.json").read_bytes(), (ROOT / "tools/rec_half_registration_v1.json").read_bytes())

    def test_modern_fresh_saved_unknowns_and_missing_source_never_become_zero(self):
        native, _, _, _ = self.record()
        first, pairs, _ = scorecard.descriptive_forecasts([read(native)], corrected.V2_SOURCE_SHA256, DI_NOW, model_version=corrected.MODEL)
        wanted = {key: row for key, row in pairs.items() if key[-1] in ("rec", "rec_yd")}
        board = copy.deepcopy(self.data)
        board["games"][0].update(state="post", detail="Final")
        reliability.atomic_json(self.root / "output/data/week.json", board)
        at = DI_NOW + timedelta(hours=3)
        from test_partial_week import status
        reliability.atomic_json(self.root / "output/data/game-status.json", {"schema_version":"ESPN-game-status-v1",
                               "weeks":{"2026_06":status(board, at)}})
        for value in (None, True, -1, .5, "bad"):
            entry = actual_row({"gp": 1, "rec": value, "rec_yd": 0})
            entry["stats"]["_presence"]["source_context"]["week"] = 6
            reliability.atomic_json(self.root / "data/cache/stats_2026_06.json", {"fictional-1": entry})
            receipt = read(scorecard.snapshot_outcomes(self.root, wanted, at)[0])
            rows = scorecard.latest_outcomes([receipt])
            self.assertEqual(rows[(2026, 6, "fictional-game", "fictional-1", "rec")]["status"], "unresolved")
            self.assertEqual(rows[(2026, 6, "fictional-game", "fictional-1", "rec_yd")]["actual"], 0)
        # A self-consistently rehashed modern row still needs its original stats.
        for missing in (None, {}):
            forged = copy.deepcopy(receipt)
            good = next(row for row in forged["rows"] if row["category"] == "rec_yd")
            good["stats_entry"] = missing
            good.pop("statistic_presence", None)
            normalized = scorecard.latest_outcomes([forged])[(2026, 6, "fictional-game", "fictional-1", "rec_yd")]
            self.assertEqual(normalized["status"], "unresolved")
            self.assertIsNone(normalized["actual"])
        forged = copy.deepcopy(receipt)
        for row in forged["rows"]:
            row["stats_entry"]["stats"]["_presence"]["kind"] = "projection"
        self.assertTrue(all(row["status"] == "unresolved" for row in scorecard.latest_outcomes([forged]).values()))
        with self.assertRaises(reliability.IntegrityError):
            scorecard.evaluate_descriptive(first, pairs, {}, {}, model_version="original_sleeper_matchup_baseline")
        mislabeled = copy.deepcopy(first)
        for row in mislabeled.values():
            row["model_version"] = "original_sleeper_matchup_baseline"
        with self.assertRaisesRegex(reliability.IntegrityError, "incompatible engine"):
            scorecard.evaluate_descriptive(mislabeled, {}, {}, {})

    def test_format_compatible_recovery_and_two_successive_mocked_updates(self):
        from test_partial_week import status
        snapshot = {}
        for step in range(3):
            at = DI_NOW + timedelta(seconds=step * 5)
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return at
            with patch.object(phase2_capture, "datetime", Clock), \
                    patch.object(phase2_capture, "_closing_status", return_value=status(self.data, at)), \
                    patch.object(phase2_capture, "run_point_candidate", side_effect=AssertionError("inactive")), \
                    patch.object(phase2_capture, "make_shadow", side_effect=AssertionError("inactive")):
                phase2_capture.run_capture(self.root)
            phase2_capture.validate_generation(self.root)
            for name, raw in snapshot.items():
                self.assertEqual((self.root / name).read_bytes(), raw)
            snapshot.update({path.relative_to(self.root):path.read_bytes() for path in (self.root / "data").rglob("*.json.gz")})
            if step == 0:
                # Fresh independently copied recovery root, not a shared cache.
                restored = self.root.parent / (self.root.name + '-recovery')
                shutil.copytree(self.root, restored)
                self.addCleanup(shutil.rmtree, restored)
                self.root = restored
        self.assertTrue(snapshot)


if __name__ == "__main__":
    unittest.main()
