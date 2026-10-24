"""Fictional decoded-provider provenance; never real historical NFL proof."""
import copy
from datetime import timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
from reliability import IntegrityError, digest, stamp
from source_evidence import SCOREBOARD_URL, record_scoreboard, verified_status
from test_reliability import NOW


def fictional_response(games, week=5, season=2026):
    return {"fixture_only": True, "season": {"year": season, "type": 2}, "week": {"number": week},
            "events": [{"id": g["id"], "date": g["kickoff"], "competitions": [{"status": {"type": {
                "state": g["state"], "completed": g["state"] == "post",
                "shortDetail": g.get("detail", "Final" if g["state"] == "post" else "Scheduled")}}}]}
                       for g in games]}


def fictional_status(games, week=5, *, season=2026, mode="live", collected_at=None):
    return record_scoreboard(fictional_response(games, week, season),
                            {"dates": season, "week": week, "seasontype": 2},
                            collected_at or NOW + timedelta(hours=5), mode=mode)


class SourceEvidenceTests(unittest.TestCase):
    def complete_payload(self):
        # Import the module, not its TestCase, so discovery does not duplicate
        # unrelated existing tests when this fixture is imported elsewhere.
        import test_scorecard as fixtures
        return fixtures.OutcomePrecedenceRegressionTests().snapshot(3, complete=True)

    def assert_incomplete_point_preserved(self, payload):
        from scorecard import _verified_week_complete, latest_outcomes
        before = copy.deepcopy(payload)
        self.assertFalse(_verified_week_complete(payload))
        chosen = next(iter(latest_outcomes([payload]).values()))
        self.assertFalse(chosen["week_confirmed_complete"])
        self.assertEqual(chosen["actual"], 3)
        self.assertEqual(payload, before)

    def test_full_decoded_response_hash_is_distinct_from_normalized_games(self):
        from scorecard import _verified_week_complete, latest_outcomes
        payload = self.complete_payload()
        status = payload["source_game_status"]
        self.assertEqual(status["response_sha256"], digest(status["response"]))
        self.assertNotEqual(status["response_sha256"], digest(status["games"]))
        self.assertTrue(_verified_week_complete(payload))
        self.assertTrue(next(iter(latest_outcomes([payload]).values()))["week_confirmed_complete"])

    def test_zero_status_digest_rejected_by_predicate_and_saved_reader(self):
        payload = self.complete_payload()
        payload["source_game_status"]["response_sha256"] = "0" * 64
        self.assert_incomplete_point_preserved(payload)

    def test_normalized_games_digest_cannot_replace_provider_response_digest(self):
        payload = self.complete_payload()
        status = payload["source_game_status"]
        status["response_sha256"] = digest(status["games"])
        self.assert_incomplete_point_preserved(payload)

    def test_changed_response_or_map_or_rehashed_response_fails(self):
        for alteration in ("body", "map", "rehashed_body"):
            with self.subTest(alteration=alteration):
                payload = self.complete_payload()
                status = payload["source_game_status"]
                if alteration == "body":
                    status["response"]["fixture_only"] = "changed"
                elif alteration == "map":
                    next(iter(status["games"].values()))["detail"] = "Changed Final"
                else:
                    status["response"]["events"][0]["competitions"][0]["status"]["type"]["completed"] = False
                    status["response_sha256"] = digest(status["response"])
                self.assert_incomplete_point_preserved(payload)

    def test_legacy_missing_or_unsupported_transcript_is_not_upgraded(self):
        for field in ("response", "response_hash_format", "schema_version", "request", "mode"):
            with self.subTest(field=field):
                payload = self.complete_payload()
                payload["source_game_status"].pop(field)
                self.assert_incomplete_point_preserved(payload)
        payload = self.complete_payload()
        payload["source_game_status"]["response_hash_format"] = "sha256-raw-http-bytes"
        self.assert_incomplete_point_preserved(payload)

    def test_wrong_source_request_or_mode_rejected(self):
        changes = ({"source": "https://example.invalid/status"}, {"mode": "replay"},
                   {"request": {"dates": 2025, "week": 5, "seasontype": 2}},
                   {"request": {"dates": 2026, "week": 6, "seasontype": 2}},
                   {"request": {"dates": 2026, "week": 5, "seasontype": 3}})
        for change in changes:
            with self.subTest(change=change):
                payload = self.complete_payload()
                payload["source_game_status"].update(change)
                self.assert_incomplete_point_preserved(payload)

    def test_provider_period_not_just_request_must_match(self):
        for field, value in (("year", 2025), ("type", 3), ("week", 6), ("year", True)):
            with self.subTest(field=field, value=value):
                payload = self.complete_payload()
                status = payload["source_game_status"]
                if field == "week":
                    status["response"]["week"]["number"] = value
                else:
                    status["response"]["season"][field] = value
                status["response_sha256"] = digest(status["response"])
                self.assert_incomplete_point_preserved(payload)

    def test_missing_provider_period_and_duplicate_or_malformed_events_fail(self):
        for alteration in ("season", "week", "duplicate", "ambiguous", "missing_status", "bad_completed", "events"):
            with self.subTest(alteration=alteration):
                payload = self.complete_payload()
                status = payload["source_game_status"]
                response = status["response"]
                if alteration in ("season", "week", "events"):
                    response.pop(alteration)
                elif alteration == "duplicate":
                    response["events"].append(copy.deepcopy(response["events"][0]))
                elif alteration == "ambiguous":
                    response["events"][0]["competitions"] *= 2
                elif alteration == "missing_status":
                    response["events"][0]["competitions"][0].pop("status")
                else:
                    response["events"][0]["competitions"][0]["status"]["type"]["completed"] = 1
                status["response_sha256"] = digest(response)
                self.assert_incomplete_point_preserved(payload)

    def test_future_or_pre_final_source_clock_fails_without_erasing_actual(self):
        for observed in (NOW + timedelta(hours=6), NOW):
            payload = self.complete_payload()
            payload["source_game_status"]["collected_at"] = stamp(observed)
            self.assert_incomplete_point_preserved(payload)

    def test_cancelled_postponed_or_nonfinal_bound_response_is_not_complete(self):
        for state, detail in (("post", "Cancelled"), ("post", "Postponed"), ("pre", "Scheduled")):
            payload = self.complete_payload()
            payload["games"][0].update(state=state, detail=detail)
            payload["source_game_status"] = fictional_status(payload["games"])
            from scorecard import _verified_week_complete
            self.assertFalse(_verified_week_complete(payload))

    def test_recorder_copies_decoded_response_and_request(self):
        games = self.complete_payload()["games"]
        response = fictional_response(games)
        request = {"dates": 2026, "week": 5, "seasontype": 2}
        status = record_scoreboard(response, request, NOW + timedelta(hours=5))
        before = copy.deepcopy(status)
        response["events"].clear()
        request["week"] = 6
        self.assertEqual(status, before)
        self.assertEqual(verified_status(status, 2026, 5, "live", NOW + timedelta(hours=5)), status["games"])

    def test_recorder_refuses_unknown_source_mode_and_request_period(self):
        response = fictional_response(self.complete_payload()["games"])
        params = {"dates": 2026, "week": 5, "seasontype": 2}
        for options in ({"source": "https://example.invalid"}, {"mode": "recovery"}):
            with self.assertRaises(IntegrityError):
                record_scoreboard(response, params, NOW, **options)
        for change in ({"week": True}, {"dates": "2026"}, {"seasontype": 1}, {"week": 19}):
            with self.assertRaises(IntegrityError):
                record_scoreboard(response, params | change, NOW)


if __name__ == "__main__":
    unittest.main()
