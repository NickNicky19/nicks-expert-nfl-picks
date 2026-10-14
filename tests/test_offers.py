import copy
from datetime import timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
from offers import capture_offers
from reliability import stamp
from test_reliability import fixture, NOW


def offer_fixture():
    data, _ = fixture(); data["players"][0]["opp"] = "BBB"
    option = {"sport": "nfl", "subject_type": "player", "subject_id": "fictional-1", "status": "active",
              "wager_type": "receptions", "game_status": "pre_game", "game_id": "source-game",
              "outcome": "over", "outcome_type": "over_under", "outcome_value": 4.5,
              "line_type": "normal", "line_id": "line-1", "market_type": "receptions_over_under_player_fictional-1",
              "season": "2026", "season_type": "regular", "subject_team": "AAA", "payout_multiplier": "1.75"}
    market = {"sport": "nfl", "wager_type": "receptions", "status": "active", "options": [option],
              "updated_at": int((NOW - timedelta(minutes=2)).timestamp() * 1000)}
    observation = {"collected_at": stamp(NOW), "status": "available", "markets": [market]}
    metadata = {"fictional-1": {"season": "2026", "week": 5, "game_id": "source-game", "team": "AAA", "opponent": "BBB"}}
    rules = {"documents": [{"url": "https://support.sleeper.com/fictional-test-only", "content_sha256": "fixture"}]}
    return data, observation, metadata, rules


class OfferTests(unittest.TestCase):
    def test_exact_line_side_multiplier_times_and_rule_provenance(self):
        args = offer_fixture(); report = capture_offers(*args)
        over = next(r for r in report["rows"] if r["side"] == "over")
        self.assertEqual(over["collection_status"], "complete_selection_capture")
        self.assertEqual(over["line"], 4.5)
        self.assertEqual(over["price_or_payout"]["raw"], "1.75")
        self.assertEqual(over["source_timestamp"]["utc"], stamp(NOW - timedelta(minutes=2)))
        self.assertEqual(over["settlement_rule_provenance"], args[3])
        self.assertIsNone(over["expected_value"])
        self.assertFalse(over["entry_economics_complete"])
        self.assertIn("complete_entry_payout_table", over["missing_information"])
        self.assertEqual(report["complete_executable_entries"], 0)

    def test_no_offer_unavailable_and_missing_information_are_distinct(self):
        data, observed, meta, rules = offer_fixture()
        observed["markets"] = []
        self.assertEqual(set(r["collection_status"] for r in capture_offers(data, observed, meta, rules)["rows"]), {"no_offer"})
        observed.update(status="unavailable", markets=None)
        self.assertEqual(set(r["collection_status"] for r in capture_offers(data, observed, meta, rules)["rows"]), {"source_unavailable"})
        observed.update(status="available", markets={"unexpected": "shape"})
        self.assertEqual(set(r["collection_status"] for r in capture_offers(data, observed, meta, rules)["rows"]), {"missing_information"})

    def test_incomplete_multiplier_and_rule_source_are_not_fabricated(self):
        data, observed, meta, rules = offer_fixture()
        observed["markets"][0]["options"][0]["payout_multiplier"] = None
        rules["documents"] = []
        over = next(r for r in capture_offers(data, observed, meta, rules)["rows"] if r["side"] == "over")
        self.assertEqual(over["collection_status"], "missing_information")
        self.assertIsNone(over["price_or_payout"])
        self.assertIn("rule_provenance", over["missing_information"])

    def test_missing_timestamp_stays_unknown_and_future_timestamp_is_invalid(self):
        data, observed, meta, rules = offer_fixture()
        observed["markets"][0].pop("updated_at")
        over = next(r for r in capture_offers(data, observed, meta, rules)["rows"] if r["side"] == "over")
        self.assertIsNone(over["source_timestamp"]["utc"])
        self.assertEqual(over["source_timestamp"]["status"], "not_supplied")
        observed["markets"][0]["updated_at"] = int((NOW + timedelta(hours=1)).timestamp() * 1000)
        over = next(r for r in capture_offers(data, observed, meta, rules)["rows"] if r["side"] == "over")
        self.assertEqual(over["collection_status"], "missing_information")

    def test_wrong_event_mapping_and_duplicate_selections_fail_closed(self):
        data, observed, meta, rules = offer_fixture()
        meta["fictional-1"]["game_id"] = "different-game"
        over = next(r for r in capture_offers(data, observed, meta, rules)["rows"] if r["side"] == "over")
        self.assertIn("verified_game_mapping", over["missing_information"])
        observed["markets"].append(copy.deepcopy(observed["markets"][0]))
        over = next(r for r in capture_offers(data, observed, meta, rules)["rows"] if r["side"] == "over")
        self.assertIn("ambiguous_multiple_normal_selections", over["missing_information"])

    def test_started_late_non_normal_and_inactive_offers_not_captured(self):
        data, observed, meta, rules = offer_fixture()
        observed["markets"][0]["options"][0]["line_type"] = "alternate"
        self.assertEqual(capture_offers(data, observed, meta, rules)["coverage"], {"no_offer": 2})
        data["players"][0]["late"] = True
        self.assertEqual(capture_offers(data, observed, meta, rules)["rows"], [])


if __name__ == "__main__":
    unittest.main()
