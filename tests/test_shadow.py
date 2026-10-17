import copy
from datetime import timedelta
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
from reliability import IntegrityError, digest, make_payload, stamp
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
        model = later["rows"][0]["models"]["challenger"]
        later["rows"][0]["probabilities_at_saved_line"]["challenger"] = event_probabilities(model, later["rows"][0]["line"])
        later["rows"][0]["prediction_intervals_80"]["challenger"] = interval80(model)
        outcome = {identity(baseline["rows"][0]): {"status": "resolved", "actual": 5}}
        expected = evaluate([first], [baseline], outcome, policy)
        actual = evaluate([later, first], [baseline, later_baseline], outcome, policy)
        self.assertEqual(actual["categories"], expected["categories"])


class SavedProbabilityIntegrityTests(unittest.TestCase):
    """Fictional corrupt receipts must never become better forecast scores."""

    def saved(self, category="rec", line=4.5, raw=4.8, adjusted=5.2, actual=5, poisson=False):
        data, _, policy = setup()
        data["players"][0]["props"][0].update(key=category, line=line, proj=raw, adj=adjusted)
        baseline = make_payload(data, NOW, {"test": "fixture"}, "live")
        if poisson:
            policy["challenger"]["count_dispersion_prior_excess_variance"] = 0
        payload = make_shadow(baseline, inputs_for(data, baseline), policy, NOW)
        outcomes = {identity(baseline["rows"][0]): {"status": "resolved", "actual": actual}}
        return payload, baseline, outcomes, policy

    def evaluate_saved(self, case, shadows=None, outcomes=None):
        payload, baseline, saved_outcomes, policy = case
        return evaluate(shadows if shadows is not None else [payload], [baseline],
                        saved_outcomes if outcomes is None else outcomes, policy)

    def reject(self, change, **options):
        case = self.saved(**options)
        change(case[0]["rows"][0])
        before = copy.deepcopy(case)
        with self.assertRaises(IntegrityError):
            self.evaluate_saved(case)
        self.assertEqual(case, before)

    def coherent_model_change(self, row, role, **values):
        model = row["models"][role]
        model.update(values)
        row["prediction_intervals_80"][role] = interval80(model)
        if row["line"] is not None:
            row["probabilities_at_saved_line"][role] = event_probabilities(model, row["line"])

    def test_valid_saved_scores_and_evidence_unchanged(self):
        case = self.saved(); before = copy.deepcopy(case)
        report = self.evaluate_saved(case)
        score = report["categories"]["rec"]["challenger"]
        self.assertAlmostEqual(score["three_way_brier"], 0.4283292396908636, places=13)
        self.assertAlmostEqual(score["negative_log_likelihood"], 2.0276611392042, places=13)
        self.assertEqual(score["n"], 1)
        self.assertEqual(case, before)

    def test_forged_normalized_vector_cannot_create_perfect_score(self):
        self.reject(lambda row: row["probabilities_at_saved_line"].update(
            challenger={"under": 0., "equal": 0., "over": 1.}))

    def test_exact_event_sides_ranges_and_mass_required(self):
        for vector in ({"under": .5, "over": .5}, {"under": .4, "equal": 0., "over": .4},
                       {"under": -.1, "equal": 0., "over": 1.1},
                       {"under": .5, "equal": 0., "over": .5, "extra": 0.},
                       {"under": True, "equal": 0., "over": 0.}):
            with self.subTest(vector=vector):
                self.reject(lambda row: row["probabilities_at_saved_line"].update(challenger=vector))

    def test_integer_push_mass_and_fractional_line_zero_equality(self):
        case = self.saved(line=4)
        self.assertGreater(case[0]["rows"][0]["probabilities_at_saved_line"]["challenger"]["equal"], 0)
        self.assertEqual(self.evaluate_saved(case)["categories"]["rec"]["challenger"]["n"], 1)
        self.reject(lambda row: row["probabilities_at_saved_line"].update(
            challenger={"under": .5, "equal": 0., "over": .5}), line=4)
        self.reject(lambda row: row["probabilities_at_saved_line"]["challenger"].update(equal=1e-12))

    def test_interval_must_be_the_saved_models_integer_quantiles(self):
        for interval in ([-1000000, 1000000], [100, 0], [0.25, 100.75], [True, 10], [0], None):
            with self.subTest(interval=interval):
                self.reject(lambda row: row["prediction_intervals_80"].update(challenger=interval))

    def test_all_model_probability_and_interval_roles_are_required(self):
        for field in ("models", "probabilities_at_saved_line", "prediction_intervals_80"):
            with self.subTest(field=field):
                self.reject(lambda row: row[field].pop("raw_reference"))
                self.reject(lambda row: row[field].update(extra=copy.deepcopy(row[field]["challenger"])))
        def coherent_extra(row):
            for field in ("models", "probabilities_at_saved_line", "prediction_intervals_80"):
                row[field]["extra"] = copy.deepcopy(row[field]["challenger"])
        self.reject(coherent_extra)

    def test_distribution_family_support_mean_and_parameters(self):
        changes = ({"family": "unregistered_family", "sd": 65.},
                   {"family": "integer_normal", "sd": 65.}, {"mean": 999.},
                   {"alpha": -.1}, {"point_center": 99.}, {"training_games": True},
                   {"training_games": -1}, {"training_games": 5})
        for values in changes:
            with self.subTest(values=values):
                self.reject(lambda row: row["models"]["challenger"].update(values))
        self.reject(lambda row: row["models"]["challenger"].update(sd=0), category="pass_yd")
        self.reject(lambda row: row["models"]["challenger"].pop("alpha"))

    def test_fixed_prior_references_cannot_be_changed_even_coherently(self):
        for role in ("raw_reference", "clone_reference"):
            with self.subTest(role=role):
                self.reject(lambda row: self.coherent_model_change(row, role, alpha=.5))

    def test_missing_line_is_unscored_not_a_fabricated_event(self):
        case = self.saved(line=None)
        score = self.evaluate_saved(case)["categories"]["rec"]["challenger"]
        self.assertEqual(score["n"], 1)
        self.assertEqual(score["brier_n"], 0)
        self.assertIsNone(score["three_way_brier"])
        self.reject(lambda row: row.update(probabilities_at_saved_line={}), line=None)
        self.reject(lambda row: row.update(probabilities_at_saved_line=None))
        self.reject(lambda row: row.pop("probabilities_at_saved_line"))

    def test_zero_count_floor_poisson_and_negative_yardage_remain_valid(self):
        case = self.saved(category="rush_att", line=0, raw=0, adjusted=0, actual=0, poisson=True)
        model = case[0]["rows"][0]["models"]["challenger"]
        self.assertEqual(model["family"], "poisson")
        self.assertEqual((model["point_center"], model["mean"]), (0, .01))
        self.assertTrue(math.isfinite(self.evaluate_saved(case)["categories"]["rush_att"]["challenger"]["negative_log_likelihood"]))
        negative = self.saved(category="pass_yd", line=-.5, raw=-1.2, adjusted=-.7, actual=-2)
        self.assertEqual(self.evaluate_saved(negative)["categories"]["pass_yd"]["challenger"]["n"], 1)

    def test_extreme_yardage_loss_is_not_clipped(self):
        case = self.saved(category="pass_yd", raw=0, adjusted=0, actual=10000)
        self.assertGreater(self.evaluate_saved(case)["categories"]["pass_yd"]["challenger"]["negative_log_likelihood"], 1000)

    def test_saved_baseline_identity_line_source_and_training_must_match(self):
        changes = ({"kickoff": stamp(NOW + timedelta(hours=2))}, {"team": "BBB"},
                   {"line_from": "invented_source"}, {"line": 99}, {"week": 6},
                   {"season": 2025}, {"category": "unknown"}, {"player_id": "unknown"},
                   {"game_id": "unknown"}, {"training_last_week": 5})
        for values in changes:
            with self.subTest(values=values):
                self.reject(lambda row: row.update(values))

    def test_missing_duplicate_or_ambiguous_opportunities_fail(self):
        for target in ("shadow_missing", "shadow_duplicate", "baseline_duplicate"):
            case = self.saved(); payload, baseline, _, _ = case
            if target == "shadow_missing":
                payload["rows"].clear()
            elif target == "shadow_duplicate":
                payload["rows"].append(copy.deepcopy(payload["rows"][0]))
            else:
                baseline["rows"].append(copy.deepcopy(baseline["rows"][0]))
                payload["baseline_payload_sha256"] = digest(baseline)
            with self.subTest(target=target), self.assertRaises(IntegrityError):
                self.evaluate_saved(case)

    def test_pending_and_later_unselected_corrupt_receipts_still_fail(self):
        case = self.saved(); bad = copy.deepcopy(case[0])
        bad["rows"][0]["prediction_intervals_80"]["challenger"] = [-1000, 1000]
        for outcomes in ({}, case[2]):
            with self.subTest(outcomes=bool(outcomes)), self.assertRaises(IntegrityError):
                self.evaluate_saved(case, shadows=[case[0], bad], outcomes=outcomes)

    def test_contract_and_completion_clocks_fail_closed(self):
        for change in ({"schema_version": "unknown"}, {"production_enabled": True},
                       {"calculation_completed_at": stamp(NOW - timedelta(seconds=1))},
                       {"calculation_completed_at": stamp(NOW + timedelta(hours=2))}):
            case = self.saved(); case[0].update(change)
            with self.subTest(change=change), self.assertRaises(IntegrityError):
                self.evaluate_saved(case)

    def test_game_starting_during_calculation_is_excluded_not_backdated(self):
        case = self.saved(); case[0]["calculation_completed_at"] = stamp(NOW + timedelta(hours=1))
        case[0]["rows"].clear()
        self.assertEqual(self.evaluate_saved(case)["unique_matched_opportunities"], 0)

    def test_nonfinite_serialized_evidence_remains_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            for field in ("probability", "interval", "parameter"):
                case = self.saved(); row = case[0]["rows"][0]
                if field == "probability":
                    row["probabilities_at_saved_line"]["challenger"]["under"] = bad
                elif field == "interval":
                    row["prediction_intervals_80"]["challenger"][0] = bad
                else:
                    row["models"]["challenger"]["alpha"] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    self.evaluate_saved(case)

    def test_invalid_actual_support_never_enters_metrics(self):
        for actual in (True, -1, 5.5, float("nan")):
            case = self.saved(actual=actual)
            with self.subTest(actual=actual), self.assertRaises(IntegrityError):
                self.evaluate_saved(case)


if __name__ == "__main__":
    unittest.main()
