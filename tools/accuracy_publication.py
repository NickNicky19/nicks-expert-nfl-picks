"""Typed aggregate projection of the existing descriptive evaluator.

No provider access, forecasting, inference policy or promotion lives here. Rich
evaluation rows are inputs, never public output. Selection filters do not change
this cumulative paired-forecast population.
"""
from collections import Counter
import copy
import math

from reliability import IntegrityError, canonical, digest
from scorecard import (PICKABLE_STATS, _paired_metrics, _point_metrics, _sample_context, _td_metrics,
                       probability_scores, descriptive_contract, identity)
import data_integrity_v2 as corrected

VERSION = "forecast-accuracy-public-v1"
MODELS = frozenset(("original_sleeper_matchup_baseline", "sleeper-matchup-data-integrity-v2"))
CATEGORIES = PICKABLE_STATS | {"fpts", "anytime_td"}
PROVENANCE = frozenset(("missing", "unknown_unverified", "identity_quarantined",
                        "conflicting_outcome_evidence", "saved_cache_descriptive_regrade",
                        "recorded_outcome_receipt"))
PROBABILITY_PROVENANCE = ("originally_recorded_probability",
                          "rederived_from_original_count_retained_formula")
OUTCOME_STATUSES = frozenset(("resolved", "dnp", "pending", "unresolved", "void", "excluded_schedule_changed"))
CAPTURE_EXCLUSIONS = frozenset(("unsupported_forecast_contract_or_engine", "non_live_receipt", "future_receipt",
    "unsupported_category", "unsupported_category_position", "not_pregame", "missing_forecast"))
UNSUPPORTED_OUTCOMES = frozenset(("unsupported_legacy_extra_statistic", "unsupported_descriptive_outcome_contract"))
PROBABILITY_MISSING = frozenset(("invalid_exact_original_board",))
SAMPLE_FIELDS = frozenset(("opportunities", "unique_players", "unique_games", "unique_weeks"))
POINT_FIELDS = frozenset(("n", "mae", "rmse", "mean_error", "bias", "absolute_error_sum",
                         "squared_error_sum", "signed_error_sum"))
PAIR_FIELDS = frozenset(("raw", "adjusted", "helps", "hurts", "ties", "absolute_error_change_sum", "sample"))
TD_FIELDS = frozenset(("n", "events", "sample", "brier_sum", "brier", "finite_log_loss_sum",
                      "infinite_log_loss_count", "log_loss", "log_loss_state", "calibration"))
UNCERTAINTY = {"status": "UNAVAILABLE_DESCRIPTIVE_EXTENSION_NO_REGISTERED_INTERVAL",
               "interval": None, "calibration": "DESCRIPTIVE_NOT_CONFIRMED"}
LIMITATIONS = ["Cumulative saved original pregame forecasts; independent of selection filters.",
               "Model versions and selected outcome provenance are separate populations.",
               "Component-derived PPR and saved direct-provider PPR are different comparators.",
               "Recorded and formula-rederived TD probabilities are separate.",
               "No mixed-unit accuracy, calibrated pick probability, promotion, profit or ROI claim."]


def _finite(value, *, nonnegative=False):
    if type(value) not in (int, float) or not math.isfinite(value) or nonnegative and value < 0:
        raise IntegrityError("Invalid public accuracy number")


def _count(value):
    if type(value) is not int or not 0 <= value <= 9007199254740991:
        raise IntegrityError("Invalid public accuracy count")


def _same(actual, expected):
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10):
        raise IntegrityError("Public accuracy arithmetic does not reconcile")


def _sample(value):
    if not isinstance(value, dict) or set(value) != SAMPLE_FIELDS:
        raise IntegrityError("Unknown public accuracy sample fields")
    for n in value.values():
        _count(n)
    if any(value[key] > value["opportunities"] for key in SAMPLE_FIELDS - {"opportunities"}):
        raise IntegrityError("Public accuracy sample exceeds its population")
    if value["opportunities"] and any(value[key] == 0 for key in SAMPLE_FIELDS - {"opportunities"}):
        raise IntegrityError("Nonempty public accuracy sample lacks its identities")


def _counts(value):
    if not isinstance(value, dict) or set(value) - OUTCOME_STATUSES:
        raise IntegrityError("Invalid public accuracy status map")
    for n in value.values():
        _count(n)


def _point(value):
    if not isinstance(value, dict) or set(value) != POINT_FIELDS:
        raise IntegrityError("Unknown public accuracy metric fields")
    _count(value["n"])
    for key in ("absolute_error_sum", "squared_error_sum", "signed_error_sum"):
        _finite(value[key], nonnegative=key != "signed_error_sum")
    if not value["n"]:
        if any(value[k] is not None for k in ("mae", "rmse", "mean_error", "bias")) or any(
                value[k] != 0 for k in ("absolute_error_sum", "squared_error_sum", "signed_error_sum")):
            raise IntegrityError("Empty public accuracy sample is not unavailable")
        return
    for key in ("mae", "rmse", "mean_error", "bias"):
        _finite(value[key], nonnegative=key in ("mae", "rmse"))
    _same(value["mae"], value["absolute_error_sum"] / value["n"])
    _same(value["rmse"] ** 2, value["squared_error_sum"] / value["n"])
    _same(value["mean_error"], value["signed_error_sum"] / value["n"])
    _same(value["bias"], value["mean_error"])
    tolerance = 1e-10 * max(1, value["absolute_error_sum"], abs(value["signed_error_sum"]))
    if abs(value["signed_error_sum"]) > value["absolute_error_sum"] + tolerance or value["mae"] > value["rmse"] + 1e-10 * max(1, value["rmse"]):
        raise IntegrityError("Impossible public accuracy error sums")


def _pair(value):
    if not isinstance(value, dict) or set(value) != PAIR_FIELDS:
        raise IntegrityError("Unknown public paired-accuracy fields")
    _point(value["raw"]); _point(value["adjusted"]); _sample(value["sample"])
    for key in ("helps", "hurts", "ties"):
        _count(value[key])
    if value["raw"]["n"] != value["adjusted"]["n"] or value["raw"]["n"] != value["sample"]["opportunities"]:
        raise IntegrityError("Public paired-accuracy populations differ")
    if sum(value[k] for k in ("helps", "hurts", "ties")) != value["raw"]["n"]:
        raise IntegrityError("Public adjustment effects do not reconcile")
    _finite(value["absolute_error_change_sum"])
    _same(value["absolute_error_change_sum"], value["adjusted"]["absolute_error_sum"] - value["raw"]["absolute_error_sum"])


def _probability(value):
    if not isinstance(value, dict) or set(value) != TD_FIELDS:
        raise IntegrityError("Unknown public TD probability fields")
    for key in ("n", "events", "infinite_log_loss_count"):
        _count(value[key])
    _sample(value["sample"])
    if value["sample"]["opportunities"] != value["n"] or value["events"] > value["n"] or value["infinite_log_loss_count"] > value["n"]:
        raise IntegrityError("Public TD probability sample differs")
    for key in ("brier_sum", "finite_log_loss_sum"):
        _finite(value[key], nonnegative=True)
    if value["n"] == value["infinite_log_loss_count"] and value["finite_log_loss_sum"] != 0:
        raise IntegrityError("TD finite loss has no finite observations")
    expected = "positive_infinity" if value["infinite_log_loss_count"] else "finite" if value["n"] else "unavailable"
    if value["log_loss_state"] != expected:
        raise IntegrityError("Public TD loss state differs")
    if value["n"]:
        _finite(value["brier"], nonnegative=True)
        if value["brier"] > 1:
            raise IntegrityError("Public Brier score outside support")
        _same(value["brier"], value["brier_sum"] / value["n"])
    elif value["brier"] is not None or value["brier_sum"] != 0:
        raise IntegrityError("Empty public TD score must be unavailable")
    if expected == "finite":
        _finite(value["log_loss"], nonnegative=True)
        _same(value["log_loss"], value["finite_log_loss_sum"] / value["n"])
    elif value["log_loss"] is not None:
        raise IntegrityError("Infinite/unavailable TD loss needs an explicit nonnumeric state")
    bins = value["calibration"]
    if not isinstance(bins, list) or len(bins) != 10:
        raise IntegrityError("Unsupported calibration bins")
    for i, group in enumerate(bins):
        if set(group) != {"lower", "upper", "upper_inclusive", "n", "events", "predicted_mean", "event_rate", "sample"}:
            raise IntegrityError("Unknown calibration fields")
        _finite(group["lower"]); _finite(group["upper"])
        if type(group["upper_inclusive"]) is not bool or (group["lower"], group["upper"], group["upper_inclusive"]) != (i / 10, (i + 1) / 10, i == 9):
            raise IntegrityError("Calibration boundaries changed")
        _count(group["n"]); _count(group["events"]); _sample(group["sample"])
        if group["events"] > group["n"] or group["sample"]["opportunities"] != group["n"]:
            raise IntegrityError("Calibration sample differs")
        if group["n"]:
            for key in ("predicted_mean", "event_rate"):
                _finite(group[key], nonnegative=True)
            if not group["lower"] <= group["predicted_mean"] <= group["upper"] or i < 9 and group["predicted_mean"] == group["upper"] or group["event_rate"] > 1:
                raise IntegrityError("Calibration value outside support")
            _same(group["event_rate"], group["events"] / group["n"])
        elif group["predicted_mean"] is not None or group["event_rate"] is not None:
            raise IntegrityError("Empty calibration bin must be unavailable")
    if sum(b["n"] for b in bins) != value["n"] or sum(b["events"] for b in bins) != value["events"]:
        raise IntegrityError("Calibration population does not reconcile")


def project_accuracy(reports):
    """Project already-validated evaluator results; never pool model/provenance."""
    cohorts, seen, captures = [], set(), []
    for report in reports:
        model = report["model_version"]
        if model not in MODELS or model in seen:
            raise IntegrityError("Mixed, duplicate or unsupported accuracy model")
        seen.add(model)
        capture = copy.deepcopy(report["capture_coverage"])
        captures.append({"model_version": model, "capture_coverage": capture,
                         "unsupported_outcome_counts": dict(Counter(r["reason"] for r in report.get("unsupported_outcome_receipts", [])))})
        population, pairs, td = report["rows"], report["paired_rows"], report["td_rows"]
        rows = population + pairs + td
        engines = {r["engine_sha256"] for r in rows}
        if len(engines) > 1 or any(r.get("model_version") != model for r in rows):
            raise IntegrityError("Mixed accuracy engine/model cohort")
        for row in rows:
            if row.get("category") not in CATEGORIES or row.get("evaluation_status") not in OUTCOME_STATUSES:
                raise IntegrityError("Unsupported accuracy row category/status")
            for key in ("raw_projection", "adjusted_projection"):
                if row.get(key) is not None:
                    _finite(row[key])
            if row["evaluation_status"] == "resolved":
                _finite(row.get("actual"))
        provenances = sorted({r["outcome_provenance"] for r in rows}) or ["missing"]
        paired_keys = {identity(r) for r in pairs}
        for provenance in provenances:
            if provenance not in PROVENANCE:
                raise IntegrityError("Unsupported accuracy outcome provenance")
            members = [r for r in population if r["outcome_provenance"] == provenance]
            matched = [r for r in pairs if r["outcome_provenance"] == provenance]
            categories = {}
            for category in sorted(CATEGORIES):
                group = [r for r in members if r["category"] == category]
                paired = [r for r in matched if r["category"] == category]
                resolved = [r for r in paired if r["evaluation_status"] == "resolved"]
                unpaired = [r for r in group if identity(r) not in paired_keys and category != "anytime_td"]
                value = {"coverage": _sample_context(group), "paired_coverage": _sample_context(paired),
                         "outcome_status": dict(Counter(r["evaluation_status"] for r in group)),
                         "paired_status": dict(Counter(r["evaluation_status"] for r in paired)),
                         "paired": _paired_metrics(resolved), "unpaired_coverage": _sample_context(unpaired),
                         "unpaired_status": dict(Counter(r["evaluation_status"] for r in unpaired)),
                         "unpaired_missingness": dict(Counter("raw_missing" if r.get("raw_projection") is None else "adjusted_missing" for r in unpaired)),
                         "adjusted_only": _point_metrics([r for r in unpaired if r["evaluation_status"] == "resolved" and r.get("adjusted_projection") is not None], "adjusted_projection")}
                if category == "fpts":
                    value["direct_provider_ppr"] = _paired_metrics([r for r in resolved if r.get("provider_ppr") is not None], "provider_ppr")
                if category == "anytime_td":
                    value["probability"] = {}
                    value["probability_unavailable"] = dict(Counter(r["probability_provenance"] for r in td
                        if r["outcome_provenance"] == provenance and r.get("probability") is None))
                    for basis in PROBABILITY_PROVENANCE:
                        group_td = [dict(r) for r in td if r["outcome_provenance"] == provenance and r["probability_provenance"] == basis]
                        for r in group_td:
                            if r["evaluation_status"] == "resolved" and r.get("probability") is not None:
                                r["actual_event"] = int(r["actual"] >= 1)
                                r.update(probability_scores(r["probability"], r["actual_event"]))
                        metrics = _td_metrics(group_td)
                        value["probability"][basis] = {k: metrics[k] for k in TD_FIELDS}
                categories[category] = value
            cohorts.append({"model_version": model, "engine_sha256": next(iter(engines), digest(corrected.V2_SOURCE_SHA256 if model == corrected.MODEL else corrected.legacy_engine_hashes())),
                            "period": "cumulative", "forecast_provenance": "original_recorded_pregame_observation",
                            "outcome_provenance": provenance, "statistic_contract_sha256": digest(report["statistic_contract"]),
                            "source_report_sha256": digest(report), "coverage": _sample_context(members),
                            "categories": categories})
    result = {"schema_version": VERSION, "cohorts": cohorts, "capture_coverage": captures, "uncertainty": dict(UNCERTAINTY),
              "limitations": list(LIMITATIONS)}
    validate_accuracy(result)
    return result


def validate_accuracy(value):
    if not isinstance(value, dict) or set(value) != {"schema_version", "cohorts", "capture_coverage", "uncertainty", "limitations"} or value["schema_version"] != VERSION:
        raise IntegrityError("Unsupported public accuracy contract")
    if value["uncertainty"] != UNCERTAINTY or value["limitations"] != LIMITATIONS:
        raise IntegrityError("Public accuracy scope/uncertainty changed")
    cohorts = value["cohorts"]
    if not isinstance(cohorts, list) or len(cohorts) > len(MODELS) * len(PROVENANCE):
        raise IntegrityError("Unsupported public accuracy cohort population")
    seen = set()
    import re
    engines = {"original_sleeper_matchup_baseline": digest(corrected.legacy_engine_hashes()),
               corrected.MODEL: digest(corrected.V2_SOURCE_SHA256)}
    captures = value["capture_coverage"]
    if not isinstance(captures, list) or len(captures) > len(MODELS):
        raise IntegrityError("Invalid capture coverage models")
    capture_models = set()
    for item in captures:
        if not isinstance(item, dict) or set(item) != {"model_version", "capture_coverage", "unsupported_outcome_counts"} or item["model_version"] not in MODELS or item["model_version"] in capture_models:
            raise IntegrityError("Mixed capture coverage models")
        capture_models.add(item["model_version"])
        coverage = item["capture_coverage"]
        if not isinstance(coverage, dict) or set(coverage) != {"unique_receipts", "duplicate_receipts", "eligible_capture_rows", "paired_capture_rows", "excluded"}:
            raise IntegrityError("Unknown capture coverage fields")
        for field in ("unique_receipts", "duplicate_receipts"): _count(coverage[field])
        for field, allowed in (("eligible_capture_rows", CATEGORIES), ("paired_capture_rows", CATEGORIES), ("excluded", CAPTURE_EXCLUSIONS)):
            if not isinstance(coverage[field], dict) or set(coverage[field]) - allowed:
                raise IntegrityError("Unsupported capture coverage category/reason")
            for n in coverage[field].values(): _count(n)
        if any(n > coverage["eligible_capture_rows"].get(category, 0) for category, n in coverage["paired_capture_rows"].items()):
            raise IntegrityError("Paired capture count exceeds eligible captures")
        if not isinstance(item["unsupported_outcome_counts"], dict) or set(item["unsupported_outcome_counts"]) - UNSUPPORTED_OUTCOMES:
            raise IntegrityError("Unsupported outcome exclusion reason")
        for n in item["unsupported_outcome_counts"].values(): _count(n)
    for cohort in cohorts:
        fields = {"model_version", "engine_sha256", "period", "forecast_provenance", "outcome_provenance",
                  "statistic_contract_sha256", "source_report_sha256", "coverage", "categories"}
        if not isinstance(cohort, dict) or set(cohort) != fields:
            raise IntegrityError("Unknown public accuracy cohort fields")
        key = cohort["model_version"], cohort["outcome_provenance"]
        if key in seen or key[0] not in MODELS or key[1] not in PROVENANCE or cohort["period"] != "cumulative" or cohort["forecast_provenance"] != "original_recorded_pregame_observation":
            raise IntegrityError("Mixed public accuracy cohort")
        seen.add(key)
        for name in ("engine_sha256", "statistic_contract_sha256", "source_report_sha256"):
            if not isinstance(cohort[name], str) or not re.fullmatch(r"[0-9a-f]{64}", cohort[name]):
                raise IntegrityError("Invalid public accuracy identity")
        _sample(cohort["coverage"])
        if cohort["engine_sha256"] != engines[cohort["model_version"]]:
            raise IntegrityError("Public accuracy engine is not a supported closed source")
        if cohort["model_version"] not in capture_models or cohort["statistic_contract_sha256"] != digest(descriptive_contract(presence_aware=cohort["model_version"] == corrected.MODEL)):
            raise IntegrityError("Public accuracy statistic/source contract differs")
        if not isinstance(cohort["categories"], dict) or set(cohort["categories"]) != CATEGORIES:
            raise IntegrityError("Public accuracy categories differ")
        for category, item in cohort["categories"].items():
            fields = {"coverage", "paired_coverage", "outcome_status", "paired_status", "paired", "unpaired_coverage", "unpaired_status", "unpaired_missingness", "adjusted_only"}
            if category == "fpts": fields.add("direct_provider_ppr")
            if category == "anytime_td": fields.update(("probability", "probability_unavailable"))
            if not isinstance(item, dict) or set(item) != fields:
                raise IntegrityError("Unknown public category accuracy fields")
            _sample(item["coverage"]); _sample(item["paired_coverage"])
            _counts(item["outcome_status"]); _counts(item["paired_status"]); _pair(item["paired"])
            _sample(item["unpaired_coverage"]); _counts(item["unpaired_status"]); _point(item["adjusted_only"])
            if not isinstance(item["unpaired_missingness"], dict) or set(item["unpaired_missingness"]) - {"raw_missing", "adjusted_missing"}:
                raise IntegrityError("Unsupported forecast missingness")
            for n in item["unpaired_missingness"].values(): _count(n)
            if sum(item["unpaired_missingness"].values()) != item["unpaired_coverage"]["opportunities"] or sum(item["unpaired_status"].values()) != item["unpaired_coverage"]["opportunities"] or item["adjusted_only"]["n"] > item["unpaired_status"].get("resolved", 0):
                raise IntegrityError("Unpaired coverage differs")
            if item["unpaired_coverage"]["opportunities"] > item["coverage"]["opportunities"]:
                raise IntegrityError("Unpaired coverage exceeds original population")
            if sum(item["outcome_status"].values()) != item["coverage"]["opportunities"] or sum(item["paired_status"].values()) != item["paired_coverage"]["opportunities"]:
                raise IntegrityError("Accuracy coverage does not reconcile")
            if item["paired"]["raw"]["n"] != item["paired_status"].get("resolved", 0):
                raise IntegrityError("Accuracy denominator includes nonfinal outcomes")
            if category == "fpts":
                _pair(item["direct_provider_ppr"])
                if item["direct_provider_ppr"]["raw"]["n"] > item["paired"]["raw"]["n"]:
                    raise IntegrityError("Provider PPR sample exceeds the component pair population")
            if category == "anytime_td":
                if not isinstance(item["probability"], dict) or set(item["probability"]) != set(PROBABILITY_PROVENANCE):
                    raise IntegrityError("Mixed TD probability provenance")
                for probability in item["probability"].values(): _probability(probability)
                if sum(p["n"] for p in item["probability"].values()) > item["outcome_status"].get("resolved", 0):
                    raise IntegrityError("TD probability sample exceeds resolved forecasts")
                missing = item["probability_unavailable"]
                if not isinstance(missing, dict) or set(missing) - PROBABILITY_MISSING:
                    raise IntegrityError("Unsupported missing probability reason")
                for n in missing.values(): _count(n)
                if sum(missing.values()) + sum(p["n"] for p in item["probability"].values()) > item["coverage"]["opportunities"]:
                    raise IntegrityError("TD missing probability count exceeds population")
        if sum(item["coverage"]["opportunities"] for item in cohort["categories"].values()) != cohort["coverage"]["opportunities"]:
            raise IntegrityError("Accuracy category population differs")
    if capture_models != {c["model_version"] for c in cohorts}:
        raise IntegrityError("Accuracy capture/model populations differ")
    canonical(value)
    return value
