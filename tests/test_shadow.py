import copy
from datetime import timedelta
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
from reliability import digest, stamp
from scorecard import identity
from shadow import cdf, distribution, evaluate, event_probabilities, interval80, log_probability, make_shadow
from test_scorecard import setup
from test_reliability import NOW


def inputs_for(data, baseline):
    return {"season": data["season"], "week": data["week"], "output_sha256": digest(data),
            "engine_files": baseline["engine_files"], "inputs_observed_at": stamp(NOW - timedelta(minutes=1)),
            "weeks": {"4": {"fictional-1": {"stats": {"gp": 1, "rec": 3}}}}}


class ShadowTests(unittest.TestCase):
    def test_count_mass_mean_and_all_event_sides(self):
        _, _, policy = setup()
        model = distribution(4, "rec", policy["challenger"])
        probs = [math.exp(log_probability(model, k)) for k in range(200)]
        self.assertAlmostEqual(sum(probs), 1, places=12)
        self.assertAlmostEqual(sum(k * p for k, p in enumerate(probs)), 4, places=11)
        at_integer = event_probabilities(model, 4)
        self.assertAlmostEqual(at_integer["equal"], probs[4])
        self.assertAlmostEqual(sum(at_integer.values()), 1)
        self.assertEqual(event_probabilities(model, 4.5)["equal"], 0)

    def test_poisson_limit_and_zero_projection_full_support(self):
        _, _, policy = setup(); rule = copy.deepcopy(policy["challenger"])
        rule["count_dispersion_prior_excess_variance"] = 0
        model = distribution(3, "rush_att", rule)
        self.assertEqual(model["family"], "poisson")
        self.assertAlmostEqual(math.exp(log_probability(model, 0)), math.exp(-3))
        self.assertTrue(math.isfinite(log_probability(distribution(0, "rec", rule), 4)))

    def test_yards_allow_negative_and_extreme_tail_loss(self):
        _, _, policy = setup()
        model = distribution(0, "pass_yd", policy["challenger"])
        self.assertGreater(math.exp(log_probability(model, -1)), 0)
        self.assertAlmostEqual(sum(event_probabilities(model, 0).values()), 1)
        self.assertTrue(math.isfinite(log_probability(model, 10000)))
        self.assertGreater(-log_probability(model, 10000), 1000)
        self.assertLess(interval80(model)[0], 0)

    def test_dispersion_shrinkage_and_probability_reference_is_separate(self):
        _, _, policy = setup(); rule = policy["challenger"]
        reference = distribution(4, "rec", rule)
        challenge = distribution(4, "rec", rule, [4, 4, 4, 4])
        self.assertLess(challenge["alpha"], reference["alpha"])
        self.assertEqual(challenge["point_center"], reference["point_center"])

    def test_no_future_training_no_backdating_and_no_baseline_mutation(self):
        data, baseline, policy = setup(); before = copy.deepcopy(baseline)
        inputs = inputs_for(data, baseline)
        shadow = make_shadow(baseline, inputs, policy, NOW)
        self.assertEqual(baseline, before)
        self.assertFalse(shadow["production_enabled"])
        self.assertEqual(shadow["rows"][0]["models"]["challenger"]["training_games"], 1)
        with self.assertRaises(ValueError): make_shadow(baseline, inputs, policy, NOW + timedelta(minutes=1))
        inputs["weeks"]["5"] = {}
        with self.assertRaises(ValueError): make_shadow(baseline, inputs, policy, NOW)

    def test_unresolved_training_not_treated_as_zero(self):
        data, baseline, policy = setup(); inputs = inputs_for(data, baseline)
        inputs["weeks"]["4"]["fictional-1"] = {"stats": {}}
        model = make_shadow(baseline, inputs, policy, NOW)["rows"][0]["models"]["challenger"]
        self.assertEqual(model["training_games"], 0)

    def test_probability_scores_use_one_earliest_common_triple(self):
        data, baseline, policy = setup()
        first = make_shadow(baseline, inputs_for(data, baseline), policy, NOW)
        later_baseline = copy.deepcopy(baseline); later_baseline["captured_at"] = stamp(NOW + timedelta(minutes=1))
        later = make_shadow(later_baseline, inputs_for(data, later_baseline), policy, NOW + timedelta(minutes=1))
        row = baseline["rows"][0]
        outcomes = {identity(row): {"status": "resolved", "actual": 5, "kickoff": row["kickoff"]}}
        result = evaluate([later, first, first], [baseline, later_baseline], outcomes, policy)
        self.assertEqual(result["unique_matched_opportunities"], 1)
        for name in ("raw_reference", "clone_reference", "challenger"):
            self.assertEqual(result["categories"]["rec"][name]["n"], 1)
            self.assertTrue(math.isfinite(result["categories"]["rec"][name]["negative_log_likelihood"]))
        self.assertFalse(result["production_enabled"])

    def test_missing_matching_baseline_or_mixed_model_code_fails(self):
        data, baseline, policy = setup(); shadow = make_shadow(baseline, inputs_for(data, baseline), policy, NOW)
        with self.assertRaises(ValueError): evaluate([shadow], [], {}, policy)
        other = copy.deepcopy(shadow); other["model_code_sha256"] = "different"
        with self.assertRaises(ValueError): evaluate([shadow, other], [baseline], {}, policy)

    def test_unresolved_actual_does_not_enter_probability_metrics(self):
        data, baseline, policy = setup(); shadow = make_shadow(baseline, inputs_for(data, baseline), policy, NOW)
        report = evaluate([shadow], [baseline], {}, policy)
        self.assertEqual(report["pending_or_unresolved"], 1)
        self.assertIsNone(report["categories"]["rec"]["challenger"]["negative_log_likelihood"])

    def test_shadow_common_triple_orders_mixed_precision_by_instant(self):
        data, baseline, policy = setup()
        first = make_shadow(baseline, inputs_for(data, baseline), policy, NOW)
        first["predicted_at"] = baseline["captured_at"] = "2026-10-10T19:00:00Z"
        first["baseline_payload_sha256"] = digest(baseline)
        later_baseline = copy.deepcopy(baseline); later_baseline["captured_at"] = "2026-10-10T19:00:00.900000Z"
        later = make_shadow(later_baseline, inputs_for(data, later_baseline), policy, NOW + timedelta(microseconds=900000))
        later["rows"][0]["models"]["challenger"]["alpha"] = 2
        outcome = {identity(baseline["rows"][0]): {"status": "resolved", "actual": 5}}
        expected = evaluate([first], [baseline], outcome, policy)
        actual = evaluate([later, first], [baseline, later_baseline], outcome, policy)
        self.assertEqual(actual["categories"], expected["categories"])


if __name__ == "__main__":
    unittest.main()
