"""Typed consumer bridge for future admitted MAE-selected numeric forecasts.

No model load/query, source acquisition, production mutation or hidden conversion
of a mean into a median. Call only inside the existing trusted producer seam.
"""
from datetime import datetime
import math

VERSION = "stat-point-mae-v2"
FUNCTIONAL_VERSION = "full-law-lower-median-view-v2"
COUNT = frozenset({"pass_td", "pass_cmp", "pass_att", "pass_int", "rush_att", "rec"})
SIGNED = frozenset({"pass_yd", "rush_yd", "rec_yd", "rush_rec_yd", "nick-chart-ppr-v1"})


def _numbers(values):
    result = [float(value) for value in values]
    if not result or any(not math.isfinite(value) for value in result):
        raise ValueError("finite complete point vector required")
    return result


def full_law_functionals(law, *, target):
    """Extract actual full-law medians and separately retained means.

    The law must already come from the existing owned, source/cutoff-qualified
    future producer. This helper does not authenticate a model or replace any
    strict historical-query / future-source validation. It verifies every lower
    median bracket on the original integer law and never clips the prior/tails.
    """
    if target not in COUNT | SIGNED:
        raise ValueError("numeric target required; probabilities stay separate")
    expected = "count" if target in COUNT else "signed_integer"
    if law.prior.support != expected:
        raise ValueError("law support differs from exact target contract")
    scale = 50 if target == "nick-chart-ppr-v1" else 1
    median = _numbers(law.quantile(.5))
    means = _numbers(law.mean)
    left = _numbers(law.cdf([value - 1 for value in median]))
    at = _numbers(law.cdf(median))
    if len({len(median), len(means), len(left), len(at)}) != 1:
        raise ValueError("all full-law functional rows required")
    for m, mu, below, here in zip(median, means, left, at):
        if m != math.floor(m) or not 0 <= below < .5 <= here <= 1:
            raise ValueError("not a verified full-law lower median")
        if target in COUNT and (m < 0 or mu < 0):
            raise ValueError("count target has negative median/mean")
    return {"version": FUNCTIONAL_VERSION, "target": target, "lattice_scale": scale,
        "median": [value / scale for value in median],
        "expected_mean": [value / scale for value in means],
        "cdf_below_median": left, "cdf_at_median": at,
        "functional_distinct_from_mean": True, "distribution_changed": False,
        "new_fits": 0, "new_football_observations": 0}


def _clock(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed


def _hash(value):
    return isinstance(value,str) and len(value)==64 and all(c in "0123456789abcdef" for c in value)


def consumer_view(row):
    """Format a typed MAE-selected point without relabeling its functional.

    `issue_deadline_utc` is the registered issue/persistence deadline. It is not
    an assertion that information published after issuance was already known.
    The owner still validates owned source, restoration, capture and public scope.
    """
    if (row["schema_version"] != VERSION or row["target"] not in COUNT | SIGNED
            or row["selection_product"] != "stat_point_mae_v2" or row["selection_metric"] != "MAE"):
        raise ValueError("exact new MAE point projection schema required")
    if row["scoring_target"] != row["target"]:
        raise ValueError("exact original statistic/chart scoring target required")
    for field in ("game_id", "player_id", "horizon"):
        if not isinstance(row[field], str) or not row[field]:
            raise ValueError("complete opportunity identity required")
    for field in ("model_version", "procedure_version", "source_policy_sha256", "capture_receipt_sha256"):
        if not _hash(row[field]):
            raise ValueError("actual 64-hex model/procedure/source/capture identity required")
    if row["consumer_contract_version"] != VERSION:
        raise ValueError("registered new consumer contract required")
    issued = _clock(row["issued_at"])
    if not (_clock(row["information_cutoff_utc"]) <= issued < _clock(row["issue_deadline_utc"])
            < _clock(row["kickoff_utc"])):
        raise ValueError("information and actual issue must precede registered deadline/kickoff")
    source = row.get("feature_max_source_available_utc")
    if source is not None and _clock(source) > _clock(row["information_cutoff_utc"]):
        raise ValueError("source availability after the declared information cutoff")
    if source is None and row.get("trained_prior_only") is not True:
        raise ValueError("unknown non-prior feature availability remains unqualified")
    value = row["forecast_value"]
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("finite numeric forecast required")
    if row["target"] in COUNT and value < 0:
        raise ValueError("count support violated")
    product, functional = row["forecast_product"], row["prediction_functional"]
    fallback = row.get("fallback") is True
    if product == "point_median" and functional in ("full_cdf_lower_median", "median_objective_point"):
        if functional == "full_cdf_lower_median":
            proof = row["functional_proof"]
            scale = 50 if row["target"] == "nick-chart-ppr-v1" else 1
            lattice = float(value) * scale
            if (abs(lattice-round(lattice)) > 1e-8 or proof["extractor_version"] != FUNCTIONAL_VERSION
                    or not 0 <= proof["cdf_below"] < .5 <= proof["cdf_at"] <= 1):
                raise ValueError("actual full-law median bracket and lattice proof required")
        elif row.get("training_objective") != "absolute_error":
            raise ValueError("median-objective point needs its actual training contract")
        kind = "median" if functional == "full_cdf_lower_median" else "median-objective projection"
    elif product == "point_mean" and functional in ("expected_mean", "valid_mean_objective_point"):
        if row.get("mean_eligible") is not True:
            raise ValueError("a legacy mixed point cannot be labeled a valid mean")
        kind = "mean projection"
    elif product == "point_empirical" and functional in ("empirical_point", "legacy_mixed_point", "arithmetic_point_blend", "market_line_heuristic"):
        kind = "empirical point" if functional != "arithmetic_point_blend" else "point blend"
    else:
        raise ValueError("untyped or mislabeled point/probability product")
    if fallback and (not row.get("fallback_reason") or not row.get("original_contract_version")):
        raise ValueError("fallback must retain its actual reason and original contract version")
    expected = row.get("separate_expected_mean")
    if expected is None and product == "point_mean":
        expected = value
    if expected is not None and (type(expected) not in (int,float) or not math.isfinite(expected)
            or (row["target"] in COUNT and expected < 0)):
        raise ValueError("separate expected value is invalid")
    label = ("Mean fallback" if product == "point_mean" else kind.capitalize()+" fallback") if fallback else "Selected "+kind
    return {"selected_projection": value, "projection_label": label,
        "selection_product": "stat_point_mae_v2", "selection_metric": "MAE",
        "forecast_product": product, "prediction_functional": functional,
        "expected_mean": expected, "fallback": fallback,
        "fallback_reason": row.get("fallback_reason", ""),
        "model_version": row["model_version"], "procedure_version": row["procedure_version"],
        "scoring_target": row["scoring_target"], "new_probability_or_EV_claim": False,
        "authority": "Existing owner validates source, clock, persistence, public scope and activation separately"}
