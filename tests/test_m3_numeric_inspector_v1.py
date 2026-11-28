"""Synthetic, hand-calculated fixtures; these are not NFL forecast results."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import m3_numeric_inspector_v1 as inspect


def prior(q=0.5, empty=False):
    return dict(kind="count", empty=empty, mu=0 if empty else 1, center=0,
                q=q, event=2.5)  # A count prior's legacy event is not a probability.


def stump(values=None, counts=None):
    return dict(left=[-1], right=[-1], feature=[-2], threshold=[-2.0],
                leaves={"0": [values if values is not None else [0, 2],
                               counts if counts is not None else [1, 3]]})


def model(tree=None):
    return dict(schema="C-NUMERIC-LEAF-v4", kind="count", scale=1,
                imputation=[1.0] * 32, prior={"WR": prior()},
                global_prior=prior(q=0.25),
                trees=[copy.deepcopy(tree or stump()) for _ in range(32)])


def split_tree(feature=0, threshold=0.5):
    return dict(left=[1, -1, -1], right=[2, -1, -1], feature=[feature, -2, -2],
                threshold=[threshold, -2.0, -2.0], leaves={"1": [[2], [1]], "2": [[4], [1]]})


class NumericModelInspectionTests(unittest.TestCase):
    def test_hand_calculated_empirical_and_role_prior_means(self):
        # (0*1 + 2*3)/4 = 1.5 in each of the 32 trees.
        got = inspect.calculate_means(model(), [dict(role="WR", features=[0] * 32),
                                                dict(role="TE", features=[0] * 32)])
        self.assertAlmostEqual(got[0], 0.95 * 1.5 + 0.05 * 1.0)
        self.assertAlmostEqual(got[1], 0.95 * 1.5 + 0.05 * (0.25 / 0.75))

    def test_empty_prior_and_explicit_zero_prediction(self):
        data = model(stump([0], [7]))
        data["prior"]["WR"] = prior(empty=True)
        self.assertEqual(inspect.calculate_means(data, [dict(role="WR", features=[0] * 32)]), [0.0])
        self.assertEqual(inspect.calculate_predictions(data, [dict(role="WR", features=[0] * 32)]),
                         [dict(mean=0.0, prior_mixture=0.05, prior_source="ROLE")])

    def test_role_and_global_attribution_remains_learned_mixture(self):
        predictions = inspect.calculate_predictions(model(), [dict(role="WR", features=[0] * 32),
                                                               dict(role="TE", features=[0] * 32)])
        self.assertEqual([item["prior_source"] for item in predictions], ["ROLE", "GLOBAL"])
        self.assertEqual([item["prior_mixture"] for item in predictions], [0.05, 0.05])

    def test_tree_mixture_is_equal_weight_not_pooled_leaf_counts(self):
        data = model(stump([0], [1000]))
        data["trees"][-1] = stump([32], [1])
        self.assertAlmostEqual(inspect.calculate_means(data, [dict(role="WR", features=[0] * 32)])[0], 1.0)

    def test_float32_routing_boundary(self):
        data = model(split_tree(threshold=1 + 2**-26))
        rows = []
        for value in (1 + 2**-25, 1 + 2**-22):
            features = [0] * 32
            features[0] = value
            rows.append(dict(role="WR", features=features))
        # First raw float is above threshold, but rounds to 1 in float32.
        means = inspect.calculate_means(data, rows)
        self.assertAlmostEqual(means[0], 1.95)
        self.assertAlmostEqual(means[1], 3.85)

    def test_missing_indicator_branch_and_training_imputation(self):
        data = model(split_tree(feature=32))
        self.assertAlmostEqual(inspect.calculate_means(data, [dict(role="WR", features=[0] * 32)])[0], 1.95)
        features = [0] * 32
        features[0] = None
        self.assertAlmostEqual(inspect.calculate_means(data, [dict(role="WR", features=features)])[0], 3.85)
        data = model(split_tree(feature=0, threshold=0.5))
        self.assertAlmostEqual(inspect.calculate_means(data, [dict(role="WR", features=features)])[0], 3.85)

    def test_rejects_unknown_role_and_bad_query(self):
        for row in (dict(role="RB", features=[0] * 32), dict(role="WR", features=[0] * 31),
                    dict(role="WR", features=[True] * 32), dict(role="WR", features=[float("nan")] * 32),
                    dict(role="WR", features=[float("inf")] * 32), dict(role="WR", features=[1e100] * 32)):
            with self.subTest(row=row), self.assertRaises(inspect.ModelValidationError):
                inspect.calculate_means(model(), [row])

    def test_rejects_wrong_product_schema_and_arrays(self):
        changes = (lambda x: x.update(kind="signed"), lambda x: x.update(scale=50),
                   lambda x: x.update(scale=True), lambda x: x.update(schema="OTHER"),
                   lambda x: x["trees"].pop(), lambda x: x["imputation"].pop(),
                   lambda x: x["imputation"].__setitem__(0, float("inf")),
                   lambda x: x["trees"][0]["threshold"].append(1))
        for change in changes:
            data = model()
            change(data)
            with self.subTest(change=change), self.assertRaises(inspect.ModelValidationError):
                inspect.validate_model(data)

    def test_rejects_cycles_shared_children_unreachable_nodes_and_bounds(self):
        trees = []
        tree = split_tree(); tree["left"][0] = 0; trees.append(tree)
        tree = split_tree(); tree["right"][0] = 1; trees.append(tree)
        tree = split_tree(); tree["right"][0] = 3; trees.append(tree)
        tree = split_tree(); tree["feature"][0] = 64; trees.append(tree)
        tree = split_tree(); tree["left"][0] = True; trees.append(tree)
        tree = split_tree(); tree["threshold"][0] = float("nan"); trees.append(tree)
        tree = stump(); tree["left"].append(-1); tree["right"].append(-1)
        tree["feature"].append(-2); tree["threshold"].append(-2.0); tree["leaves"]["1"] = [[0], [1]]; trees.append(tree)
        for tree in trees:
            with self.subTest(tree=tree), self.assertRaises(inspect.ModelValidationError):
                inspect.validate_model(model(tree))

    def test_rejects_empty_invalid_or_noncount_leaf_support(self):
        for values, counts in (([], []), ([0, 1], [1]), ([-1], [1]), ([0, 0], [1, 1]),
                               ([2, 1], [1, 1]), ([0.5], [1]), ([0], [0]), ([0], [-1]),
                               ([0], [True]), ([0], [0.5]), ([float("inf")], [1])):
            with self.subTest(values=values, counts=counts), self.assertRaises(inspect.ModelValidationError):
                inspect.validate_model(model(stump(values, counts)))

    def test_depth_eight_is_supported_and_depth_nine_rejected(self):
        def chain(depth):
            tree = dict(left=[], right=[], feature=[], threshold=[], leaves={})
            def add(level):
                node = len(tree["left"])
                tree["left"].append(-1); tree["right"].append(-1)
                tree["feature"].append(-2); tree["threshold"].append(-2.0)
                if level == depth:
                    tree["leaves"][str(node)] = [[0], [1]]
                else:
                    tree["left"][node] = add(level + 1)
                    leaf = len(tree["left"])
                    tree["left"].append(-1); tree["right"].append(-1)
                    tree["feature"].append(-2); tree["threshold"].append(-2.0)
                    tree["leaves"][str(leaf)] = [[1], [1]]
                    tree["right"][node] = leaf
                    tree["feature"][node] = 0; tree["threshold"][node] = 0.5
                return node
            add(0)
            return tree
        inspect.validate_model(model(chain(8)))
        with self.assertRaisesRegex(inspect.ModelValidationError, "TREE_DEPTH"):
            inspect.validate_model(model(chain(9)))

    def test_prior_probability_and_boolean_type_contracts(self):
        # A legacy count event summary >1 is intentionally valid.
        inspect.validate_model(model())
        for key, value in (("q", 1.0), ("q", -0.1), ("mu", -1), ("mu", float("inf")),
                           ("center", 1.5), ("empty", 1), ("event", float("nan"))):
            data = model(); data["global_prior"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(inspect.ModelValidationError):
                inspect.validate_model(data)

    def load_bytes(self, raw, **limits):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic-model.json.gz"
            path.write_bytes(raw)
            return inspect.load_model(path, hashlib.sha256(raw).hexdigest(), **limits)

    def test_actual_gzip_reopening_and_hash_tampering(self):
        raw = gzip.compress(json.dumps(model(), allow_nan=False).encode(), mtime=0)
        self.assertEqual(self.load_bytes(raw), model())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.gz"
            path.write_bytes(raw + b"changed")
            with self.assertRaisesRegex(inspect.ModelValidationError, "MODEL_HASH"):
                inspect.load_model(path, hashlib.sha256(raw).hexdigest())

    def test_json_duplicates_nonfinite_and_bad_compression(self):
        for text in ('{"schema":1,"schema":2}', '{"imputation":[NaN]}', '{"x":Infinity}', '{"x":1e999}'):
            with self.subTest(text=text), self.assertRaises(inspect.ModelValidationError):
                self.load_bytes(gzip.compress(text.encode(), mtime=0))
        with self.assertRaises(inspect.ModelValidationError):
            self.load_bytes(b"not gzip or a permitted model format")
        with self.assertRaises(inspect.ModelValidationError):
            self.load_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03invalid-deflate")

    def test_compressed_and_decoded_byte_guards(self):
        raw = gzip.compress(json.dumps(model()).encode(), mtime=0)
        with self.assertRaisesRegex(inspect.ModelValidationError, "COMPRESSED_BYTE_LIMIT"):
            self.load_bytes(raw, max_compressed_bytes=len(raw) - 1)
        with self.assertRaisesRegex(inspect.ModelValidationError, "DECODED_BYTE_LIMIT"):
            self.load_bytes(raw, max_decoded_bytes=100)


if __name__ == "__main__":
    unittest.main()
