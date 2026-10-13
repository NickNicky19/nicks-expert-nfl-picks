"""Fictional fixtures. These tests are software evidence, not prediction evidence."""
import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "pull"), str(ROOT / "tools")]
import grade
import gamemodel
from reliability import IntegrityError, capture, digest, immutable_write, load_json, make_payload, utc, validate

NOW = datetime(2026, 10, 10, 19, 0, tzinfo=timezone.utc)


def fixture():
    prop = {"key": "rec", "line": 4.5, "proj": 4.8, "adj": 5.2, "lean": "over", "source": "model", "line_from": "dk", "mf": 1.08,
            "values": [{"s": 2026, "w": 4, "v": 3}]}
    player = {"id": "fictional-1", "name": "Fictional Receiver", "game_id": "fictional-game", "team": "AAA", "pos": "WR", "props": [prop],
              "proj_ppr": 10, "matchup": "soft", "late": False}
    pick = {"player_id": player["id"], "game_id": player["game_id"], "key": "rec", "direction": "over", "line": 4.5, "proj": 4.8, "adj": 5.2, "line_from": "dk"}
    data = {"season": 2026, "week": 5, "generated_at": "2026-10-10T18:59:00Z", "categories": {"rec": {"label": "Receptions"}},
            "games": [{"id": "fictional-game", "home": "AAA", "away": "BBB", "kickoff": "2026-10-10T20:00:00Z", "state": "pre"}],
            "players": [player], "picks": {"over": [pick], "under": []}}
    meta = {k: data[k] for k in ("season", "week", "generated_at")}
    return data, meta


class GradingTests(unittest.TestCase):
    def test_over_win_and_loss(self):
        self.assertEqual(grade.result("over", 5, 4.5), "hit")
        self.assertEqual(grade.result("over", 4, 4.5), "miss")

    def test_under_win_and_loss(self):
        self.assertEqual(grade.result("under", 4, 4.5), "hit")
        self.assertEqual(grade.result("under", 5, 4.5), "miss")

    def test_push_both_directions(self):
        for side in ("over", "under"):
            self.assertEqual(grade.result(side, 4, 4), "push")

    def test_zero_and_negative_yards(self):
        self.assertEqual(grade.result("over", 0, -0.5), "hit")
        self.assertEqual(grade.result("under", -2, -0.5), "hit")
        self.assertEqual(grade.result("under", 0, 0), "push")

    def test_unknown_value_or_line(self):
        self.assertEqual(grade.result("over", None, 4.5), "unresolved")
        self.assertEqual(grade.result("over", 4, None), "unresolved")

    def test_invalid_number_rejected(self):
        for bad in (float("nan"), float("inf"), True, "4"):
            with self.assertRaises(ValueError):
                grade.result("over", bad, 4.5)

    def test_invalid_direction_rejected(self):
        with self.assertRaises(ValueError):
            grade.result("invalid", 4, 4.5)

    def test_hit_rate_excludes_unresolved_dnp_push(self):
        self.assertEqual(grade.tally(["hit", "miss", "push", "dnp", "unresolved"]),
                         {"hit": 1, "miss": 1, "push": 1, "dnp": 1, "unresolved": 1, "n_decided": 2, "pct": 50.0})

    def test_empty_hit_rate_is_null(self):
        self.assertIsNone(grade.tally([])["pct"])
        self.assertIsNone(grade.tally(["push", "unresolved"])["pct"])

    def test_unknown_grade_rejected(self):
        with self.assertRaises(ValueError):
            grade.tally(["win"])

    def test_missing_stats_is_not_dnp(self):
        data, _ = fixture()
        record = grade.grade_week(data, {}, {"fictional-game"})
        self.assertEqual(record["top_over"]["unresolved"], 1)
        self.assertEqual(record["top_over"]["dnp"], 0)
        self.assertEqual(record["leans"]["unresolved"], 1)
        self.assertFalse(record["complete"])

    def test_empty_and_zero_rows_are_unknown(self):
        for row in (None, {}, {"stats": {}}, {"stats": {"gp": 0, "off_snp": 0}}):
            self.assertEqual(grade.participation(row), "unresolved")

    def test_confirmed_dnp_requires_source(self):
        self.assertEqual(grade.participation({"participation_status": "dnp"}), "unresolved")
        self.assertEqual(grade.participation({"participation_status": "dnp", "participation_source": "fixture-confirmation"}), "dnp")

    def test_contradictory_participation_unresolved(self):
        self.assertEqual(grade.participation({"stats": {"gp": 1}, "participation_status": "dnp", "participation_source": "fixture"}), "unresolved")

    def test_invalid_participation_rejected(self):
        for value in (-1, float("nan"), "1"):
            with self.assertRaises(ValueError):
                grade.participation({"stats": {"gp": value}})

    def test_observed_zero_not_missing_player(self):
        data, _ = fixture()
        record = grade.grade_week(data, {"fictional-1": {"stats": {"gp": 1}}}, {"fictional-game"})
        self.assertEqual(record["top_over"]["picks"][0]["actual"], 0)
        self.assertEqual(record["top_over"]["miss"], 1)

    def test_both_projections_saved_without_mutation(self):
        data, _ = fixture()
        before = copy.deepcopy(data)
        record = grade.grade_week(data, {"fictional-1": {"stats": {"gp": 1, "rec": 5}}}, {"fictional-game"})
        pick = record["top_over"]["picks"][0]
        self.assertEqual(pick["proj"], 4.8)
        self.assertEqual(pick["adj"], 5.2)
        self.assertEqual(pick["decision_projection"], 5.2)
        self.assertEqual(data, before)

    def test_future_game_not_graded(self):
        data, _ = fixture()
        record = grade.grade_week(data, {"fictional-1": {"stats": {"gp": 1, "rec": 5}}}, set())
        self.assertEqual(record["top_over"]["n_decided"], 0)
        self.assertFalse(record["complete"])

    def test_late_player_not_graded(self):
        data, _ = fixture(); data["players"][0]["late"] = True
        record = grade.grade_week(data, {"fictional-1": {"stats": {"gp": 1, "rec": 5}}}, {"fictional-game"})
        self.assertEqual(record["top_over"]["n_decided"], 0)
        self.assertEqual(record["leans"]["n_decided"], 0)

    def test_venue_counts_not_mixed(self):
        data, _ = fixture()
        data["players"][0]["props"][0]["line_from"] = "sleeper"
        record = grade.grade_week(data, {"fictional-1": {"stats": {"gp": 1, "rec": 5}}}, {"fictional-game"})
        self.assertEqual(record["by_venue"]["sleeper"]["hit"], 1)
        self.assertNotIn("dk", record["by_venue"])

    def test_combine_preserves_all_status_counts(self):
        data, _ = fixture()
        one = grade.grade_week(data, {}, {"fictional-game"})
        two = grade.grade_week(data, {"fictional-1": {"stats": {"gp": 1, "rec": 5}}}, {"fictional-game"})
        total = grade.combine([one, two])
        self.assertEqual(total["top_over"]["hit"], 1)
        self.assertEqual(total["top_over"]["unresolved"], 1)
        self.assertEqual(total["leans"]["by_category"]["rec"]["unresolved"], 1)
        self.assertEqual(total["by_venue"]["dk"]["hit"], 1)

    def test_game_push_is_counted(self):
        archive = {"games": [{"id": "g", "home": "AAA", "away": "BBB", "ours": {"lean_spread": "AAA", "lean_total": "over"},
                              "odds": {"spread": -3, "total": 41}}]}
        record = grade.grade_games(archive, {"g": (22, 19)})
        self.assertEqual(record["spread"]["push"], 1)
        self.assertEqual(record["total"]["push"], 1)

    def test_old_week_needs_final_game_confirmation(self):
        data, _ = fixture()
        with tempfile.TemporaryDirectory() as d:
            Path(d, "archive.json").write_text(json.dumps(data))
            record = grade.grade_all(Path(d), lambda *args: {}, (2026, 6), set(), scores_for=lambda *args: {})
            self.assertEqual(len(record["weeks"]), 1)
            self.assertFalse(record["weeks"][0]["complete"])
            self.assertEqual(record["weeks"][0]["top_over"]["unresolved"], 0)

    def test_empty_stats_week_retained_as_unresolved(self):
        data, _ = fixture()
        with tempfile.TemporaryDirectory() as d:
            Path(d, "archive.json").write_text(json.dumps(data))
            record = grade.grade_all(Path(d), lambda *args: {}, (2026, 5), {"fictional-game"})
            self.assertEqual(record["cumulative"]["top_over"]["unresolved"], 1)


class CaptureTests(unittest.TestCase):
    def test_valid_fixture(self):
        data, meta = fixture()
        self.assertEqual(validate(data, meta, NOW)["real_line_props"], 1)

    def test_metadata_mismatch_fails(self):
        data, meta = fixture(); meta["week"] = 4
        with self.assertRaises(IntegrityError): validate(data, meta, NOW)

    def test_future_build_fails(self):
        data, meta = fixture()
        with self.assertRaises(IntegrityError): validate(data, meta, NOW - timedelta(minutes=2))

    def test_stale_build_fails(self):
        data, meta = fixture()
        with self.assertRaises(IntegrityError): validate(data, meta, NOW + timedelta(hours=3))

    def test_timezone_required(self):
        with self.assertRaises(IntegrityError): utc("2026-10-10T19:00:00")

    def test_duplicate_player_fails(self):
        data, meta = fixture(); data["players"].append(copy.deepcopy(data["players"][0]))
        with self.assertRaises(IntegrityError): validate(data, meta, NOW)

    def test_duplicate_game_fails(self):
        data, meta = fixture(); data["games"].append(copy.deepcopy(data["games"][0]))
        with self.assertRaises(IntegrityError): validate(data, meta, NOW)

    def test_unknown_team_fails(self):
        data, meta = fixture(); data["players"][0]["team"] = "CCC"
        with self.assertRaises(IntegrityError): validate(data, meta, NOW)

    def test_future_history_fails(self):
        data, meta = fixture(); data["players"][0]["props"][0]["values"][0]["w"] = 5
        with self.assertRaises(IntegrityError): validate(data, meta, NOW)

    def test_nonfinite_projection_fails(self):
        data, meta = fixture(); data["players"][0]["props"][0]["adj"] = float("nan")
        with self.assertRaises(IntegrityError): validate(data, meta, NOW)

    def test_contradictory_pick_fails(self):
        data, meta = fixture(); data["picks"]["over"][0]["adj"] = 4
        with self.assertRaises(IntegrityError): validate(data, meta, NOW)

    def test_estimated_line_not_a_selected_pick(self):
        data, meta = fixture(); data["picks"]["over"][0]["line_from"] = "ours"
        with self.assertRaises(IntegrityError): validate(data, meta, NOW)

    def test_non_top_forecasts_included(self):
        data, meta = fixture(); data["picks"]["over"] = []
        payload = make_payload(data, NOW, {"fixture": "not-production"}, "replay")
        self.assertEqual(len(payload["rows"]), 1)
        self.assertFalse(payload["rows"][0]["top_over"])

    def test_started_and_exact_kickoff_excluded(self):
        data, _ = fixture()
        self.assertEqual(len(make_payload(data, NOW + timedelta(hours=1), {}, "replay")["rows"]), 0)
        data["games"][0]["state"] = "in"
        self.assertEqual(len(make_payload(data, NOW, {}, "replay")["rows"]), 0)

    def test_late_forecast_excluded(self):
        data, _ = fixture(); data["players"][0]["late"] = True
        self.assertEqual(len(make_payload(data, NOW, {}, "replay")["rows"]), 0)

    def test_no_invented_probability_price_or_ev(self):
        data, _ = fixture()
        row = make_payload(data, NOW, {}, "replay")["rows"][0]
        for field in ("probability", "price", "expected_value"):
            self.assertIsNone(row[field])

    def test_replay_is_explicit_not_prospective(self):
        data, meta = fixture()
        with tempfile.TemporaryDirectory() as d:
            path, report = capture(data, meta, Path(d), NOW, {}, mode="replay")
            payload = json.loads(gzip.decompress(path.read_bytes()))["payload"]
            self.assertIn("data/replay", str(path))
            self.assertEqual(payload["evidence_label"], "REPLAY_TEST_NOT_PROSPECTIVE")
            self.assertFalse(report["source_timestamps_verified"])

    def test_retry_preserves_first_capture_bytes(self):
        data, meta = fixture()
        with tempfile.TemporaryDirectory() as d:
            path, _ = capture(data, meta, Path(d), NOW, {}, mode="replay")
            before = path.read_bytes()
            again, report = capture(data, meta, Path(d), NOW + timedelta(minutes=1), {}, mode="replay")
            self.assertEqual(again, path)
            self.assertFalse(report["capture_created"])
            self.assertEqual(before, path.read_bytes())

    def test_changed_snapshot_creates_new_receipt(self):
        data, meta = fixture()
        with tempfile.TemporaryDirectory() as d:
            p1, _ = capture(data, meta, Path(d), NOW, {}, mode="replay")
            data["players"][0]["props"][0]["proj"] = 4.9
            p2, _ = capture(data, meta, Path(d), NOW, {}, mode="replay")
            self.assertNotEqual(p1, p2)
            self.assertTrue(p1.exists())

    def test_corrupt_existing_receipt_fails(self):
        data, meta = fixture()
        with tempfile.TemporaryDirectory() as d:
            path, _ = capture(data, meta, Path(d), NOW, {}, mode="replay")
            content = json.loads(gzip.decompress(path.read_bytes()))
            content["payload"]["model"] = "corrupted"
            path.write_bytes(gzip.compress(json.dumps(content).encode()))
            with self.assertRaises(IntegrityError): capture(data, meta, Path(d), NOW, {}, mode="replay")

    def test_duplicate_json_key_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "bad.json"); p.write_text('{"week": 1, "week": 2}')
            with self.assertRaises(IntegrityError): load_json(p)

    def test_json_nan_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "bad.json"); p.write_text('{"x": NaN}')
            with self.assertRaises(IntegrityError): load_json(p)

    def test_invalid_mode_fails(self):
        data, _ = fixture()
        with self.assertRaises(IntegrityError): make_payload(data, NOW, {}, "unknown")

    def test_capture_never_mutates_input(self):
        data, meta = fixture(); before = copy.deepcopy(data)
        with tempfile.TemporaryDirectory() as d: capture(data, meta, Path(d), NOW, {}, mode="replay")
        self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
