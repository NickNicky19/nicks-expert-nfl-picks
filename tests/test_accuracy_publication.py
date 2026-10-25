"""Aggregate extension controls; wholly fictional observations, no collector."""
import copy
from collections import Counter
import json
import subprocess
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
import data_integrity_v2 as corrected
import classic_model_v1 as classic
from reliability import IntegrityError, digest
from accuracy_publication import project_accuracy, validate_accuracy
from scorecard import descriptive_contract


def observation(player, category="rec", *, actual=0, raw=2, adjusted=1,
                status="resolved", provenance="recorded_outcome_receipt", model="original_sleeper_matchup_baseline"):
    return dict(season=2026, week=7, game_id="fictional-game", player_id=player,
                category=category, raw_projection=raw, adjusted_projection=adjusted,
                actual=actual if status == "resolved" else None, evaluation_status=status,
                outcome_provenance=provenance, model_version=model,
                engine_sha256=digest(corrected.source_hashes(model) if model in corrected.PRESENCE_MODELS else classic.ENGINE if model == classic.MODEL else corrected.legacy_engine_hashes()))


def evaluation(rows=(), *, td=(), model="original_sleeper_matchup_baseline"):
    return dict(model_version=model, statistic_contract=descriptive_contract(presence_aware=model in corrected.PRESENCE_MODELS, model=model if model in (*corrected.PRESENCE_MODELS, classic.MODEL) else None),
                rows=list(rows), paired_rows=[r for r in rows if r["category"] != "anytime_td" and r["raw_projection"] is not None and r["adjusted_projection"] is not None],
                td_rows=list(td), capture_coverage=dict(unique_receipts=int(bool(rows)), duplicate_receipts=0,
                    eligible_capture_rows=dict(Counter(r["category"] for r in rows)),
                    paired_capture_rows=dict(Counter(r["category"] for r in rows if r["category"] != "anytime_td" and r["raw_projection"] is not None and r["adjusted_projection"] is not None)), excluded={}),
                secret="PRIVATE_CANARY", private_path="/unapproved/private/capture")


class PublicAccuracyTests(unittest.TestCase):
    def test_zero_signed_yardage_and_nonfinal_denominators(self):
        report = evaluation([observation("zero"), observation("negative", "rush_yd", actual=-2, raw=0, adjusted=-1),
                             observation("unknown", status="unresolved"), observation("dnp", status="dnp"),
                             observation("pending", status="pending")])
        value = project_accuracy([report]); validate_accuracy(value)
        cats = value["cohorts"][0]["categories"]
        self.assertEqual((cats["rec"]["coverage"]["opportunities"], cats["rec"]["paired"]["raw"]["n"]), (4, 1))
        self.assertEqual(cats["rec"]["paired"]["raw"]["mae"], 2)
        self.assertEqual(cats["rush_yd"]["paired"]["adjusted"]["bias"], 1)
        self.assertIsNone(cats["pass_yd"]["paired"]["raw"]["mae"])
        encoded = json.dumps(value)
        self.assertNotIn("PRIVATE_CANARY", encoded); self.assertNotIn("/unapproved", encoded)
        self.assertNotIn('"player_id"', encoded)

    def test_original_corrected_and_saved_cache_are_separate(self):
        original = evaluation([observation("A"), observation("B", provenance="saved_cache_descriptive_regrade")])
        modern = evaluation([observation("C", model=corrected.MODEL)], model=corrected.MODEL)
        cohorts = project_accuracy([original, modern])["cohorts"]
        self.assertEqual(len(cohorts), 3)
        self.assertEqual({c["model_version"] for c in cohorts}, {"original_sleeper_matchup_baseline", corrected.MODEL})
        with self.assertRaises(IntegrityError): project_accuracy([original, original])
        broken = copy.deepcopy(original); broken["paired_rows"][0]["model_version"] = corrected.MODEL
        with self.assertRaises(IntegrityError): project_accuracy([broken])

    def test_provider_ppr_is_not_invented_from_components(self):
        row = observation("PPR", "fpts", raw=8, adjusted=9, actual=10)
        categories = project_accuracy([evaluation([row])])["cohorts"][0]["categories"]
        self.assertEqual(categories["fpts"]["paired"]["raw"]["n"], 1)
        self.assertEqual(categories["fpts"]["direct_provider_ppr"]["raw"]["n"], 0)
        row["provider_ppr"] = 12
        categories = project_accuracy([evaluation([row])])["cohorts"][0]["categories"]
        self.assertEqual(categories["fpts"]["direct_provider_ppr"]["raw"]["bias"], 2)

    def test_td_probability_facets_and_infinite_loss(self):
        a = observation("TD-A", "anytime_td", actual=1, raw=.5, adjusted=None)
        b = observation("TD-B", "anytime_td", actual=0, raw=.2, adjusted=None)
        a.update(probability=0, probability_provenance="originally_recorded_probability")
        b.update(probability=.25, probability_provenance="rederived_from_original_count_retained_formula")
        # Producer recomputes proper scores rather than trusting a supplied PASS/value.
        a.update(actual_event=0, brier=0, log_loss=0, log_loss_state="finite")
        report = evaluation([a, b], td=[a, b])
        probability = project_accuracy([report])["cohorts"][0]["categories"]["anytime_td"]["probability"]
        original = probability["originally_recorded_probability"]
        self.assertEqual((original["n"], original["events"], original["brier"]), (1, 1, 1))
        self.assertEqual(original["log_loss_state"], "positive_infinity"); self.assertIsNone(original["log_loss"])
        self.assertEqual(probability["rederived_from_original_count_retained_formula"]["n"], 1)

    def test_mutated_aggregates_unknown_fields_and_bad_sources_fail(self):
        original = project_accuracy([evaluation([observation("A")])])
        mutations = [lambda v: v.update(rows=[]),
                     lambda v: v["cohorts"][0].update(engine_sha256="0" * 64),
                     lambda v: v["cohorts"][0].update(period="2026-w07"),
                     lambda v: v["cohorts"][0]["categories"]["rec"]["paired"]["raw"].update(mae=0),
                     lambda v: v["cohorts"][0]["categories"]["rec"]["outcome_status"].update(password=1),
                     lambda v: v["uncertainty"].update(interval=[0, 1])]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = copy.deepcopy(original); mutate(changed)
                with self.assertRaises(IntegrityError): validate_accuracy(changed)
        broken = evaluation([observation("A", raw=True)])
        with self.assertRaises(IntegrityError): project_accuracy([broken])

    def test_empty_population_has_all_categories_and_unavailable_metrics(self):
        value = project_accuracy([evaluation()])
        self.assertEqual(len(value["cohorts"][0]["categories"]), 12)
        self.assertIsNone(value["cohorts"][0]["categories"]["rec"]["paired"]["raw"]["mae"])

    def test_counterexample_aggregates_and_coverage_are_rejected(self):
        a = observation("TD", "anytime_td", raw=.5, adjusted=None)
        a.update(probability=.2, probability_provenance="originally_recorded_probability")
        original = project_accuracy([evaluation([a, observation("R")], td=[a])])
        changes = [
            lambda v: v["cohorts"][0].update(statistic_contract_sha256="0" * 64),
            lambda v: v["cohorts"][0]["categories"]["anytime_td"]["outcome_status"].update(resolved=0, pending=1),
            lambda v: v["cohorts"][0]["categories"]["anytime_td"]["probability"]["rederived_from_original_count_retained_formula"].update(finite_log_loss_sum=100),
            lambda v: v["cohorts"][0]["categories"]["anytime_td"]["probability"]["originally_recorded_probability"]["calibration"][0].update(upper_inclusive=0),
            lambda v: v["capture_coverage"][0]["capture_coverage"]["excluded"].update(private_path=1),
        ]
        for mutate in changes:
            changed = copy.deepcopy(original); mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises(IntegrityError): validate_accuracy(changed)
        point = original["cohorts"][0]["categories"]["rec"]["paired"]["raw"]
        point.update(n=1, absolute_error_sum=1, squared_error_sum=0, signed_error_sum=2,
                     mae=1, rmse=0, mean_error=2, bias=2)
        with self.assertRaises(IntegrityError): validate_accuracy(original)

    def test_adjusted_only_missing_probability_and_exclusions_remain_visible(self):
        row = observation("adjusted", raw=None)
        td = observation("TD", "anytime_td", raw=.5, adjusted=None)
        td.update(probability=None, probability_provenance="invalid_exact_original_board")
        report = evaluation([row, td], td=[td])
        report["capture_coverage"] = dict(unique_receipts=3, duplicate_receipts=0,
            eligible_capture_rows={"rec": 1, "anytime_td": 1}, paired_capture_rows={}, excluded={"missing_forecast": 1})
        report["unsupported_outcome_receipts"] = [{"reason": "unsupported_legacy_extra_statistic", "payload_sha256": "0" * 64}]
        value = project_accuracy([report]); cats = value["cohorts"][0]["categories"]
        self.assertEqual(cats["rec"]["adjusted_only"]["n"], 1)
        self.assertEqual(cats["rec"]["unpaired_missingness"], {"raw_missing": 1})
        self.assertEqual(cats["anytime_td"]["probability_unavailable"], {"invalid_exact_original_board": 1})
        self.assertEqual(value["capture_coverage"][0]["capture_coverage"]["excluded"], {"missing_forecast": 1})

    def test_actual_browser_reader_accepts_producer_and_rejects_mutations(self):
        row = observation("TD", "anytime_td", raw=.5, adjusted=None, actual=1)
        row.update(probability=0, probability_provenance="originally_recorded_probability")
        value = project_accuracy([evaluation([observation("R"), row], td=[row])])
        script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('output/app.js','utf8'), f=source.match(/function validateForecastAccuracy\([^]*?\n\}/)[0];
const context={HASH64:/^[a-f0-9]{64}$/,PAPER_CATEGORIES:['pass_yd','pass_td','pass_cmp','pass_att','pass_int','rush_yd','rush_att','rec_yd','rec','rush_rec_yd']};vm.createContext(context);vm.runInContext(f+'\nthis.validate=validateForecastAccuracy',context);
const original=JSON.parse(fs.readFileSync(0,'utf8'));context.validate(original);
const changes=[v=>v.extra=[],v=>v.cohorts[0].engine_sha256=null,v=>v.cohorts[0].categories.rec.paired.raw.mae=999,v=>v.cohorts[0].categories.anytime_td.probability.rederived_from_original_count_retained_formula.finite_log_loss_sum=1,v=>v.capture_coverage[0].capture_coverage.excluded.private_path=1];
for(const change of changes){const v=structuredClone(original);change(v);assert.throws(()=>context.validate(v));}
'''
        result = subprocess.run(["node", "-e", script], input=json.dumps(value), text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)


class ThreeSourceAccuracyTests(unittest.TestCase):
    def test_all_three_closed_models_remain_distinct_and_crossed_engine_rejects(self):
        models = ("original_sleeper_matchup_baseline", *corrected.PRESENCE_MODELS)
        reports = [evaluation([observation("fictional-"+str(i), model=model)], model=model)
                   for i, model in enumerate(models)]
        before = copy.deepcopy(reports)
        value = project_accuracy(reports)
        validate_accuracy(value)
        self.assertEqual(reports, before)
        self.assertEqual({c["model_version"] for c in value["cohorts"]}, set(models))
        self.assertEqual(len({c["engine_sha256"] for c in value["cohorts"]}), 3)
        self.assertEqual(len({c["statistic_contract_sha256"] for c in value["cohorts"]}), 3)
        bad = copy.deepcopy(value)
        cohort = next(c for c in bad["cohorts"] if c["model_version"] == corrected.CLASSIC_MODEL)
        cohort["engine_sha256"] = digest(corrected.source_hashes(corrected.MODEL))
        with self.assertRaises(IntegrityError):
            validate_accuracy(bad)
        bad = copy.deepcopy(reports[-1]); bad["model_version"] = "unknown"
        with self.assertRaises(IntegrityError):
            project_accuracy([bad])


class FourSourceAccuracyTests(unittest.TestCase):
    def test_saved_classic_fourth_context_and_wrong_statistic_contract_reject(self):
        models=("original_sleeper_matchup_baseline",corrected.MODEL,classic.MODEL,corrected.CLASSIC_MODEL)
        reports=[evaluation([observation("fictional-"+str(i),model=model)],model=model)for i,model in enumerate(models)]
        before=copy.deepcopy(reports);value=project_accuracy(reports);validate_accuracy(value)
        self.assertEqual(reports,before);self.assertEqual({c["model_version"]for c in value["cohorts"]},set(models))
        self.assertEqual(len({c["engine_sha256"]for c in value["cohorts"]}),4)
        legacy=next(c for c in value["cohorts"]if c["model_version"]==classic.MODEL)
        self.assertEqual(legacy["engine_sha256"],digest(classic.ENGINE))
        self.assertEqual(legacy["statistic_contract_sha256"],digest(descriptive_contract(model=classic.MODEL)))
        for wrong in [descriptive_contract(),descriptive_contract(presence_aware=True,model=corrected.MODEL),
                      descriptive_contract(presence_aware=True,model=corrected.CLASSIC_MODEL)]:
            invalid=copy.deepcopy(value)
            next(c for c in invalid["cohorts"]if c["model_version"]==classic.MODEL)["statistic_contract_sha256"]=digest(wrong)
            with self.assertRaises(IntegrityError):validate_accuracy(invalid)


if __name__ == "__main__":
    unittest.main()
