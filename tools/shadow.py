"""Experimental distributions. This module never writes production forecasts/picks."""
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pull"))
import grade
from reliability import IntegrityError, digest, finite, stamp, utc
from scorecard import identity


def distribution(center, category, rule, values=None):
    finite(center, "distribution center", optional=False)
    values = [] if values is None else values
    for value in values:
        finite(value, "training outcome", optional=False)
    n, prior_n = len(values), rule["dispersion_prior_games"]
    if category in ("rec", "rush_att"):
        if center < 0 or any(v < 0 or int(v) != v for v in values):
            raise IntegrityError("Count distribution requires nonnegative counts")
        alpha = rule["count_dispersion_prior_excess_variance"]
        if n >= 2:
            avg = statistics.mean(values)
            empirical = max(0, (statistics.variance(values) - avg) / (avg * avg)) if avg > 0 else alpha
            alpha = (prior_n * alpha + n * empirical) / (prior_n + n)
        # A tiny positive mean gives zero-projection players full count support.
        # It is an explicit engineering floor, not evidence of calibrated chances.
        mean = max(0.01, center)
        return {"family": "negative_binomial" if alpha > 1e-12 else "poisson", "mean": mean,
                "point_center": center, "alpha": alpha, "training_games": n}
    if category != "pass_yd":
        raise IntegrityError("Unsupported challenger target")
    variance = rule["yards_prior_sd"] ** 2
    if n >= 2:
        variance = (prior_n * variance + n * statistics.variance(values)) / (prior_n + n)
    return {"family": "integer_normal", "mean": center, "point_center": center,
            "sd": max(1, math.sqrt(variance)), "training_games": n}


def log_probability(model, actual):
    finite(actual, "probability outcome", optional=False)
    if int(actual) != actual:
        raise IntegrityError("Forecast distribution is defined on integer statistics")
    family, mean = model["family"], model["mean"]
    if family in ("poisson", "negative_binomial"):
        if actual < 0:
            raise IntegrityError("Negative count outcome")
        if family == "poisson":
            return actual * math.log(mean) - mean - math.lgamma(actual + 1)
        size = 1 / model["alpha"]
        return (math.lgamma(actual + size) - math.lgamma(size) - math.lgamma(actual + 1) +
                size * -math.log1p(mean / size) + actual * (math.log(mean) - math.log(size + mean)))
    sd = model["sd"]
    a, b = (actual - .5 - mean) / sd, (actual + .5 - mean) / sd
    if a >= 0:
        probability = .5 * (math.erfc(a / math.sqrt(2)) - math.erfc(b / math.sqrt(2)))
    elif b <= 0:
        probability = .5 * (math.erfc(-b / math.sqrt(2)) - math.erfc(-a / math.sqrt(2)))
    else:
        probability = .5 * (math.erf(b / math.sqrt(2)) - math.erf(a / math.sqrt(2)))
    if probability > 0:
        return math.log(probability)
    # Extreme normal tails can underflow erfc. Log-space Simpson integration of
    # the exact integer bin avoids clipping catastrophic errors to a fixed loss.
    logs = [-.5 * x * x - .5 * math.log(2 * math.pi) for x in (a, (a + b) / 2, b)]
    high = max(logs)
    return high + math.log(math.exp(logs[0] - high) + 4 * math.exp(logs[1] - high) + math.exp(logs[2] - high)) + math.log((b - a) / 6)


def cdf(model, integer):
    if model["family"] == "integer_normal":
        return .5 * math.erfc(-(integer + .5 - model["mean"]) / (model["sd"] * math.sqrt(2)))
    if integer < 0:
        return 0.0
    if integer > 10000:
        raise IntegrityError("Count threshold exceeds supported numerical range")
    return min(1, max(0, math.fsum(math.exp(log_probability(model, k)) for k in range(integer + 1))))


def event_probabilities(model, line):
    finite(line, "statistical event line", optional=False)
    under = cdf(model, math.ceil(line) - 1)
    through = cdf(model, math.floor(line))
    push = max(0, through - under) if int(line) == line else 0.0
    return {"under": under, "equal": push, "over": max(0, 1 - through)}


def interval80(model):
    if model["family"] == "integer_normal":
        return [math.ceil(model["mean"] + model["sd"] * statistics.NormalDist().inv_cdf(p) - .5) for p in (.1, .9)]
    total, bounds = 0.0, []
    for k in range(10001):
        total += math.exp(log_probability(model, k))
        if not bounds and total >= .1:
            bounds.append(k)
        if total >= .9:
            return bounds + [k]
    raise IntegrityError("Count interval failed to converge")


def make_shadow(baseline, inputs, policy, predicted_at, code_commit=None):
    predicted_at = utc(predicted_at)
    if utc(baseline["captured_at"]) != predicted_at:
        raise IntegrityError("Cannot backdate a newly created shadow forecast to an older receipt")
    if inputs["output_sha256"] != baseline["input_sha256"] or inputs["engine_files"] != baseline["engine_files"]:
        raise IntegrityError("Shadow inputs do not match the captured baseline")
    if utc(inputs["inputs_observed_at"]) > predicted_at:
        raise IntegrityError("Training inputs were observed after the forecast")
    if utc(policy["registered_at"]) > predicted_at:
        raise IntegrityError("Evaluation policy was not registered before forecast")
    if any(int(w) >= inputs["week"] or int(w) < 1 for w in inputs["weeks"]):
        raise IntegrityError("Shadow training contains current/future weeks")
    rule = policy["challenger"]
    rows = []
    for row in baseline["rows"]:
        if row["category"] not in policy["targets"] or row["raw_projection"] is None or row["adjusted_projection"] is None:
            continue
        if utc(row["kickoff"]) <= predicted_at:
            raise IntegrityError("Shadow forecast is not pregame")
        values = []
        for w, week in sorted(inputs["weeks"].items(), key=lambda x: int(x[0])):
            if int(w) >= row["week"]:
                raise IntegrityError("Shadow training contains current/future weeks")
            entry = week.get(row["player_id"])
            if grade.participation(entry) == "played" and entry["stats"].get(row["category"], 0) is not None:
                values.append(entry["stats"].get(row["category"], 0))
        models = {"raw_reference": distribution(row["raw_projection"], row["category"], rule),
                  "clone_reference": distribution(row["adjusted_projection"], row["category"], rule),
                  "challenger": distribution(row["adjusted_projection"], row["category"], rule, values)}
        saved = {k: row[k] for k in ("season", "week", "game_id", "player_id", "category", "team", "kickoff", "line", "line_from")}
        rows.append({**saved, "models": models, "training_last_week": row["week"] - 1,
                     "probabilities_at_saved_line": {k: event_probabilities(m, row["line"]) for k, m in models.items()} if row["line"] is not None else None,
                     "prediction_intervals_80": {k: interval80(m) for k, m in models.items()}})
    return {"schema_version": "shadow-probability-v1", "season": inputs["season"], "week": inputs["week"],
            "mode": baseline["mode"], "predicted_at": stamp(predicted_at), "baseline_payload_sha256": digest(baseline),
            "policy_sha256": digest(policy), "model_version": rule["version"], "code_commit": code_commit,
            "model_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "training_inputs_sha256": digest(inputs), "rows": rows, "production_enabled": False,
            "calibration": "NOT_ESTABLISHED", "profitability": "NOT_ESTABLISHED",
            "scope": "STATISTICAL_EVENTS_NOT_VENUE_SETTLEMENT"}


MODEL_ROLES = ("raw_reference", "clone_reference", "challenger")
PROBABILITY_TOLERANCE = 1e-10  # Absolute numerical agreement, not a scoring floor.


def _roles(value, label):
    if not isinstance(value, dict) or set(value) != set(MODEL_ROLES):
        raise IntegrityError(f"Invalid saved {label} roles")


def _validate_model(model, category, center, last_week, rule, reference):
    finite(center, "baseline center", optional=False)
    if not isinstance(model, dict):
        raise IntegrityError("Missing saved distribution")
    for field in ("point_center", "mean"):
        finite(model[field], f"saved {field}", optional=False)
    if model["point_center"] != center:
        raise IntegrityError("Shadow centers changed the retained baseline")
    n = model["training_games"]
    if type(n) is not int or not 0 <= n <= last_week:
        raise IntegrityError("Invalid saved training sample count")
    if category in ("rec", "rush_att"):
        finite(model["alpha"], "saved dispersion", optional=False)
        if center < 0 or model["mean"] != max(.01, center) or model["alpha"] < 0:
            raise IntegrityError("Invalid saved count distribution parameters")
        family = "negative_binomial" if model["alpha"] > 1e-12 else "poisson"
        fields = {"family", "mean", "point_center", "alpha", "training_games"}
    elif category == "pass_yd":
        finite(model["sd"], "saved standard deviation", optional=False)
        if model["mean"] != center or model["sd"] < 1:
            raise IntegrityError("Invalid saved yardage distribution parameters")
        family = "integer_normal"
        fields = {"family", "mean", "point_center", "sd", "training_games"}
    else:
        raise IntegrityError("Unsupported saved probability target")
    if model["family"] != family or set(model) != fields:
        raise IntegrityError("Saved distribution family/support/fields mismatch")
    if reference and model != distribution(center, category, rule):
        raise IntegrityError("Saved reference differs from its registered fixed prior")


def _validate_derived(row):
    models, intervals = row["models"], row["prediction_intervals_80"]
    _roles(intervals, "interval")
    probabilities = row["probabilities_at_saved_line"]
    line = row["line"]
    if line is None:
        if probabilities is not None:
            raise IntegrityError("Saved event probabilities lack a saved line")
    else:
        finite(line, "saved event line", optional=False)
        _roles(probabilities, "probability")
    for name in MODEL_ROLES:
        model, bounds = models[name], intervals[name]
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise IntegrityError("Invalid saved prediction interval")
        for bound in bounds:
            finite(bound, "saved interval endpoint", optional=False)
            if int(bound) != bound:
                raise IntegrityError("Saved interval endpoint is not an integer")
        if bounds[0] > bounds[1] or bounds != interval80(model):
            raise IntegrityError("Saved interval differs from its distribution quantiles")
        for bound, quantile in zip(bounds, (.1, .9)):
            below, through = cdf(model, bound - 1), cdf(model, bound)
            if (not 0 <= below <= through <= 1
                    or below > quantile + PROBABILITY_TOLERANCE
                    or through < quantile - PROBABILITY_TOLERANCE):
                raise IntegrityError("Distribution quantile mass is numerically unsupported")
        if line is None:
            continue
        saved, expected = probabilities[name], event_probabilities(model, line)
        if not isinstance(saved, dict) or set(saved) != {"under", "equal", "over"}:
            raise IntegrityError("Invalid saved event sides")
        for side in ("under", "equal", "over"):
            finite(saved[side], "saved event probability", optional=False)
            if (not 0 <= saved[side] <= 1 or not 0 <= expected[side] <= 1
                    or not math.isclose(saved[side], expected[side], rel_tol=0,
                                        abs_tol=PROBABILITY_TOLERANCE)):
                raise IntegrityError("Saved event probability differs from its distribution")
        if (not math.isclose(math.fsum(saved.values()), 1, rel_tol=0,
                             abs_tol=PROBABILITY_TOLERANCE)
                or (int(line) != line and saved["equal"] != 0)):
            raise IntegrityError("Invalid saved event mass/equality convention")


def _validated_rows(payload, baseline, policy):
    """Check saved evidence without replacing forecasts or consulting outcomes."""
    try:
        predicted = utc(payload["predicted_at"])
        completed = utc(payload.get("calculation_completed_at", payload["predicted_at"]))
        if (payload["schema_version"] != "shadow-probability-v1"
                or payload["production_enabled"] is not False
                or baseline["schema_version"] != "baseline-capture-v1"
                or baseline["model"] != policy["baseline"]
                or not utc(baseline["forecast_generated_at"]) <= predicted <= completed
                or utc(policy["registered_at"]) > predicted
                or type(payload["season"]) is not int or type(payload["week"]) is not int
                or not 2000 <= payload["season"] <= 2200 or not 1 <= payload["week"] <= 18):
            raise IntegrityError("Invalid saved shadow/baseline contract or clocks")
        available, expected = {}, set()
        if not isinstance(baseline["rows"], list) or not isinstance(payload["rows"], list):
            raise IntegrityError("Missing saved probability population")
        for original in baseline["rows"]:
            key = identity(original)
            if key in available:
                raise IntegrityError("Duplicate captured baseline opportunity")
            available[key] = original
            if (original["category"] in policy["targets"] and original["raw_projection"] is not None
                    and original["adjusted_projection"] is not None and utc(original["kickoff"]) > completed):
                expected.add(key)
        seen = set()
        for row in payload["rows"]:
            key = identity(row)
            if key in seen or key not in expected:
                raise IntegrityError("Duplicate or unmatched shadow opportunity")
            seen.add(key)
            original = available[key]
            if (any(row[k] != original[k] for k in ("season", "week", "team", "line", "line_from"))
                    or (row["season"], row["week"]) != (payload["season"], payload["week"])
                    or utc(row["kickoff"]) != utc(original["kickoff"])
                    or type(row["training_last_week"]) is not int or row["training_last_week"] != row["week"] - 1):
                raise IntegrityError("Shadow opportunity/line/source/kickoff/training mismatch")
            _roles(row["models"], "model")
            for name in MODEL_ROLES:
                center = original["raw_projection" if name == "raw_reference" else "adjusted_projection"]
                _validate_model(row["models"][name], row["category"], center, row["training_last_week"],
                                policy["challenger"], name != "challenger")
            _validate_derived(row)
        if seen != expected:
            raise IntegrityError("Shadow is missing captured probability opportunities")
        return payload["rows"]
    except (KeyError, TypeError, ArithmeticError) as err:
        raise IntegrityError(f"Malformed or numerically unsupported saved probability evidence: {err}") from err


def evaluate(shadows, baselines, outcomes, policy, allow_replay=False):
    """Earliest common saved triple per outcome; no retroactive forecast creation."""
    baseline_by_hash = {digest(p): p for p in baselines}
    selected = {}
    excluded = 0
    code_versions = set()
    for payload in sorted(shadows, key=lambda p: (utc(p["predicted_at"]), digest(p))):
        if payload.get("mode") != "live" and not (allow_replay and payload.get("mode") == "replay"):
            continue
        if payload.get("model_version") != policy["challenger"]["version"] or payload.get("policy_sha256") != digest(policy):
            excluded += len(payload["rows"])
            continue
        code_versions.add(payload["model_code_sha256"])
        if len(code_versions) > 1:
            raise IntegrityError("One candidate version cannot mix different model code; register a new version")
        baseline = baseline_by_hash.get(payload["baseline_payload_sha256"])
        if not baseline or baseline["captured_at"] != payload["predicted_at"] or baseline["mode"] != payload["mode"]:
            raise IntegrityError("Shadow has no contemporaneous captured baseline")
        for row in _validated_rows(payload, baseline, policy):
            key = identity(row)
            selected.setdefault(key, row)
    scores = {k: {name: {"n": 0, "negative_log_likelihood": None, "three_way_brier": None,
                       "interval_coverage_80": None} for name in ("raw_reference", "clone_reference", "challenger")} for k in policy["targets"]}
    buffers = {}
    pending = 0
    for key, row in selected.items():
        outcome = outcomes.get(key)
        if utc(row["kickoff"]) <= utc(policy["registered_at"]):
            continue
        if not outcome or outcome["status"] != "resolved" or (outcome.get("kickoff") and utc(outcome["kickoff"]) != utc(row["kickoff"])):
            pending += 1
            continue
        actual = outcome["actual"]
        for name, model in row["models"].items():
            nll = -log_probability(model, actual)
            finite(nll, "saved-model negative log likelihood", optional=False)
            if nll < 0:
                raise IntegrityError("Saved-model outcome mass exceeds one")
            low, high = row["prediction_intervals_80"][name]
            probabilities = row.get("probabilities_at_saved_line")
            brier = None
            if probabilities:
                event = "under" if actual < row["line"] else "over" if actual > row["line"] else "equal"
                brier = sum((p - (side == event)) ** 2 for side, p in probabilities[name].items())
            buffers.setdefault((row["category"], name), []).append((nll, brier, low <= actual <= high, model["point_center"] - actual))
    for (category, name), values in buffers.items():
        briers = [v[1] for v in values if v[1] is not None]
        scores[category][name] = {"n": len(values), "negative_log_likelihood": statistics.mean(v[0] for v in values),
                                   "three_way_brier": statistics.mean(briers) if briers else None,
                                   "brier_n": len(briers), "interval_coverage_80": statistics.mean(v[2] for v in values),
                                   "point_mae": statistics.mean(abs(v[3]) for v in values),
                                   "point_rmse": math.sqrt(statistics.mean(v[3] ** 2 for v in values))}
    return {"model_version": policy["challenger"]["version"], "unique_matched_opportunities": len(selected),
            "pending_or_unresolved": pending, "excluded_version_rows": excluded, "categories": scores,
            "production_enabled": False, "calibration": "NOT_ESTABLISHED", "profitability": "NOT_ESTABLISHED"}
