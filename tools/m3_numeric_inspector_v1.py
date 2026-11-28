"""Independent, numeric-only inspection of C M3 reception-mean model bodies.

This module reads bounded gzip JSON, traverses explicit tree arrays and computes
the unrounded reception mean. It never imports producer model code or pickle.
Its result is not source/timestamp authentication, fit reproduction, product
admission, or permission to publish. Those remain separate owner checks.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import zlib


SCHEMA = "C-NUMERIC-LEAF-v4"
FEATURE_COUNT = 32
TREE_COUNT = 32
MAX_NODES = 511
MAX_DEPTH = 8
MAX_LEAF_VALUES = 20_000
MAX_SAFE_INTEGER = 2**53 - 1
DEFAULT_MAX_COMPRESSED_BYTES = 1_048_576
DEFAULT_MAX_DECODED_BYTES = 16_777_216


class ModelValidationError(ValueError):
    """The actual numeric body or query violates the pinned safe format."""


def _require(condition, message):
    if not condition:
        raise ModelValidationError("M3_NUMERIC_" + message)


def _number(value, name):
    _require(type(value) in (int, float), name + "_NUMBER")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise ModelValidationError("M3_NUMERIC_" + name + "_FINITE") from None
    _require(math.isfinite(result), name + "_FINITE")
    return result


def _integer(value, name, minimum=0, maximum=MAX_SAFE_INTEGER):
    number = _number(value, name)
    _require(number.is_integer() and minimum <= number <= maximum, name + "_INTEGER")
    return int(number)


def _float32(value, name):
    value = _number(value, name)
    try:
        rounded = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error):
        raise ModelValidationError("M3_NUMERIC_" + name + "_FLOAT32_RANGE") from None
    _require(math.isfinite(rounded), name + "_FLOAT32_RANGE")
    return rounded


def _exact_keys(value, keys, name):
    _require(isinstance(value, dict) and set(value) == set(keys), name + "_FIELDS")


def _validate_prior(prior):
    _exact_keys(prior, ("kind", "empty", "mu", "center", "q", "event"), "PRIOR")
    _require(prior["kind"] == "count" and type(prior["empty"]) is bool, "PRIOR_KIND")
    _require(_number(prior["mu"], "PRIOR_MU") >= 0, "PRIOR_MU_SUPPORT")
    _integer(prior["center"], "PRIOR_CENTER")
    q = _number(prior["q"], "PRIOR_Q")
    _require(0 <= q < 1, "PRIOR_Q_SUPPORT")
    # For count priors, event is a legacy summary, not an event probability.
    # The producer's count format intentionally permits values greater than 1.
    _number(prior["event"], "PRIOR_LEGACY_EVENT")


def _validate_tree(tree):
    _exact_keys(tree, ("left", "right", "feature", "threshold", "leaves"), "TREE")
    for key in ("left", "right", "feature", "threshold"):
        _require(isinstance(tree[key], list), "TREE_ARRAY")
    n = len(tree["left"])
    _require(1 <= n <= MAX_NODES, "TREE_SIZE")
    _require(all(len(tree[key]) == n for key in ("right", "feature", "threshold")),
             "TREE_ARRAY_LENGTH")
    _require(isinstance(tree["leaves"], dict), "LEAF_MAP")

    leaf_nodes = set()
    for node in range(n):
        left, right, feature = (tree[key][node] for key in ("left", "right", "feature"))
        _require(all(type(value) is int for value in (left, right, feature)), "TREE_INDEX_TYPE")
        threshold = _number(tree["threshold"][node], "THRESHOLD")
        if left == -1:
            _require(right == -1 and feature == -2 and threshold == -2, "LEAF_SENTINEL")
            leaf_nodes.add(str(node))
        else:
            _require(0 <= left < n and 0 <= right < n and left != right, "TREE_CHILD_BOUNDS")
            _require(0 <= feature < FEATURE_COUNT * 2, "TREE_FEATURE_BOUNDS")
    _require(set(tree["leaves"]) == leaf_nodes, "LEAF_MEMBERSHIP")

    # Each node must be reached exactly once from root 0. This rejects cycles,
    # shared children, disconnected nodes and trees deeper than the recipe.
    seen = set()
    todo = [(0, 0)]
    while todo:
        node, depth = todo.pop()
        _require(node not in seen, "TREE_CYCLE_OR_SHARED_CHILD")
        _require(depth <= MAX_DEPTH, "TREE_DEPTH")
        seen.add(node)
        if tree["left"][node] != -1:
            todo.extend(((tree["left"][node], depth + 1),
                         (tree["right"][node], depth + 1)))
    _require(len(seen) == n, "TREE_UNREACHABLE_NODE")

    for leaf in tree["leaves"].values():
        _require(isinstance(leaf, list) and len(leaf) == 2, "LEAF_FIELDS")
        values, counts = leaf
        _require(isinstance(values, list) and isinstance(counts, list), "LEAF_ARRAY")
        _require(1 <= len(values) == len(counts) <= MAX_LEAF_VALUES, "EMPTY_OR_MISMATCHED_LEAF")
        integers = [_integer(value, "LEAF_VALUE") for value in values]
        _require(all(a < b for a, b in zip(integers, integers[1:])), "LEAF_VALUE_ORDER")
        for count in counts:
            _integer(count, "LEAF_COUNT", minimum=1)


def validate_model(model):
    """Validate the fixed count/32-feature/32-tree format; return the same dict.

    This does not verify source availability or independently reproduce fitting.
    Callers must retain and verify the original compressed-byte commitment.
    """
    _exact_keys(model, ("schema", "kind", "scale", "imputation", "prior",
                        "global_prior", "trees"), "MODEL")
    _require(model["schema"] == SCHEMA and model["kind"] == "count", "MODEL_SCHEMA")
    _require(type(model["scale"]) in (int, float) and model["scale"] == 1, "MODEL_SCALE")
    _require(isinstance(model["imputation"], list) and len(model["imputation"]) == FEATURE_COUNT,
             "IMPUTATION_LENGTH")
    for value in model["imputation"]:
        _float32(value, "IMPUTATION")
    _require(isinstance(model["prior"], dict) and
             all(role in ("RB", "WR", "TE") for role in model["prior"]), "ROLE_PRIOR_MAP")
    _validate_prior(model["global_prior"])
    for prior in model["prior"].values():
        _validate_prior(prior)
    _require(isinstance(model["trees"], list) and len(model["trees"]) == TREE_COUNT,
             "TREE_COUNT")
    for tree in model["trees"]:
        _validate_tree(tree)
    return model


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _nonfinite_constant(_value):
    raise ModelValidationError("M3_NUMERIC_JSON_NONFINITE")


def load_model(path, expected_sha256, *,
               max_compressed_bytes=DEFAULT_MAX_COMPRESSED_BYTES,
               max_decoded_bytes=DEFAULT_MAX_DECODED_BYTES):
    """Hash-check actual bytes, bounded-decode gzip JSON, and validate its model.

    No network, pickle, imported producer code, or automatic format substitution
    is used. A matching hash is integrity evidence, not disclosure authority.
    """
    _require(isinstance(expected_sha256, str) and
             re.fullmatch("[0-9a-f]{64}", expected_sha256) is not None, "EXPECTED_HASH")
    for limit in (max_compressed_bytes, max_decoded_bytes):
        _require(type(limit) is int and limit > 0, "BYTE_LIMIT")
    with Path(path).open("rb") as stream:
        raw = stream.read(max_compressed_bytes + 1)
    _require(len(raw) <= max_compressed_bytes, "COMPRESSED_BYTE_LIMIT")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "MODEL_HASH")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as stream:
            decoded = stream.read(max_decoded_bytes + 1)
        _require(len(decoded) <= max_decoded_bytes, "DECODED_BYTE_LIMIT")
        model = json.loads(decoded.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_nonfinite_constant)
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError, RecursionError, zlib.error) as exc:
        raise ModelValidationError("M3_NUMERIC_GZIP_OR_JSON") from exc
    return validate_model(model)


def calculate_predictions(model, rows):
    """Compute reception means and explicit prior-mixture attribution.

    Each row needs ``role`` and 32 ``features`` (finite numbers or explicit
    None). Additional identity fields are left to the caller's identity checks.
    This is numerical verification, not a forecast issue or admission receipt.
    """
    validate_model(model)
    _require(isinstance(rows, list), "QUERY_ROWS")
    result = []
    for row in rows:
        _require(isinstance(row, dict) and row.get("role") in ("WR", "TE"), "QUERY_ROLE")
        features = row.get("features")
        _require(isinstance(features, list) and len(features) == FEATURE_COUNT, "QUERY_FEATURE_LENGTH")
        design = [_float32(model["imputation"][index] if value is None else value,
                           "QUERY_FEATURE") for index, value in enumerate(features)]
        design += [1.0 if value is None else 0.0 for value in features]
        tree_means = []
        for tree in model["trees"]:
            node = 0
            while tree["left"][node] != -1:
                node = (tree["left"][node] if design[tree["feature"][node]] <= tree["threshold"][node]
                        else tree["right"][node])
            values, counts = tree["leaves"][str(node)]
            total = sum(counts)
            tree_means.append(math.fsum(float(value) * (count / total)
                                        for value, count in zip(values, counts)))
        prior = model["prior"].get(row["role"], model["global_prior"])
        prior_mean = 0.0 if prior["empty"] else prior["q"] / (1.0 - prior["q"])
        mean = 0.95 * (math.fsum(tree_means) / TREE_COUNT) + 0.05 * prior_mean
        _require(math.isfinite(mean) and mean >= 0, "MEAN_FINITE_SUPPORT")
        result.append(dict(mean=mean, prior_mixture=0.05,
                           prior_source="ROLE" if row["role"] in model["prior"] else "GLOBAL"))
    return result


def calculate_means(model, rows):
    """Return only the unrounded means from :func:`calculate_predictions`."""
    return [record["mean"] for record in calculate_predictions(model, rows)]
