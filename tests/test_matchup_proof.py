"""Recorded populations, corrected caches, frozen forecasts, and hard failures."""
import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
import matchup
import verify
from evidence import write
from reliability import digest


def fixture(root):
    weeks = {"1": {"a": {"opp": "BBB", "stats": {"gp": 1, "rec": 2}},
                   "bye": {"opp": "BBB", "stats": {"gp": 1, "rec": 8}}},
             "2": {"a": {"opp": "CCC", "stats": {"gp": 1, "rec": 4}},
                   "bye": {"opp": "DDD", "stats": {"gp": 1, "rec": 4}}}}
    positions = {"a": "WR", "bye": "WR"}
    f, n = matchup.Matchups({int(w): x for w, x in weeks.items()}, positions).factor("BBB", "WR", "rec", 3)
    data = {"season": 2026, "week": 3, "games": [{"id": "g"}], "players": [
        {"id": "a", "name": "Fixture", "pos": "WR", "opp": "BBB", "game_id": "g", "props": [
            {"key": "rec", "proj": 4, "adj": round(4 * f, 2), "mf": f, "mf_n": n,
             "values": [{"s": 2026, "w": 1, "v": 2}, {"s": 2026, "w": 2, "v": 4}]}]}]}
    payload = {"season": 2026, "week": 3, "engine_files": {"test": "fixture"}, "positions": positions,
               "weeks": weeks, "week_data": copy.deepcopy(data), "output_sha256": digest(data)}
    path = write(root, "verification", payload)
    proof = {"output_sha256": digest(data), "game_origins": {"g": path.relative_to(root).as_posix()}}
    return data, proof, payload, path


class ProofTests(unittest.TestCase):
    def check(self, root, data, proof):
        verify.problems.clear()
        with patch.object(verify, "ROOT", root), patch.object(verify, "engine_hashes", return_value={"test": "fixture"}):
            verify.check_point_in_time(data, proof)
        return list(verify.problems)

    def test_full_builder_population_includes_bye_players(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, payload, _ = fixture(root)
            full = data["players"][0]["props"][0]
            subset = matchup.Matchups({int(w): x for w, x in payload["weeks"].items()}, {"a": "WR"})
            self.assertNotEqual(subset.factor("BBB", "WR", "rec", 3), (full["mf"], full["mf_n"]))
            self.assertEqual(self.check(root, data, proof), [])

    def test_corrected_latest_cache_does_not_rewrite_frozen_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, _, path = fixture(root)
            before = path.read_bytes()
            (root / "data/cache").mkdir()
            (root / "data/cache/stats_2026_01.json").write_text('{"a":{"opp":"BBB","stats":{"gp":1,"rec":99}}}')
            self.assertEqual(self.check(root, data, proof), [])
            self.assertEqual(path.read_bytes(), before)

    def test_bad_factor_still_fails_even_with_matching_checksums(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, payload, _ = fixture(root)
            data["players"][0]["props"][0]["mf"] = 0.75
            payload["week_data"] = copy.deepcopy(data); payload["output_sha256"] = digest(data)
            path = write(root, "verification", payload)
            proof.update(output_sha256=digest(data), game_origins={"g": path.relative_to(root).as_posix()})
            self.assertTrue(any("matchup factor" in x for x in self.check(root, data, proof)))

    def test_wrong_sample_count_still_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, _, _ = fixture(root)
            data["players"][0]["props"][0]["mf_n"] = 999
            proof["output_sha256"] = digest(data)
            self.assertTrue(self.check(root, data, proof))

    def test_future_input_week_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, payload, _ = fixture(root)
            payload["weeks"]["3"] = {}
            path = write(root, "verification", payload)
            proof["game_origins"]["g"] = path.relative_to(root).as_posix()
            self.assertTrue(any("future week" in x for x in self.check(root, data, proof)))

    def test_future_chart_and_missing_origin_both_reported(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, _, _ = fixture(root)
            data["players"][0]["props"][0]["values"][0]["w"] = 3
            proof.update(output_sha256=digest(data), game_origins={"g": None})
            errors = self.check(root, data, proof)
            self.assertEqual(len(errors), 2)

    def test_tampered_receipt_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, _, path = fixture(root)
            envelope = json.loads(gzip.decompress(path.read_bytes()))
            envelope["payload"]["positions"].pop("bye")
            path.write_bytes(gzip.compress(json.dumps(envelope).encode()))
            self.assertTrue(any("checksum" in x for x in self.check(root, data, proof)))

    def test_missing_or_mismatched_proof_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, _, _ = fixture(root)
            self.assertTrue(self.check(root, data, {"output_sha256": "wrong"}))
            proof["game_origins"]["g"] = "../escape.json.gz"
            self.assertTrue(self.check(root, data, proof))


if __name__ == "__main__":
    unittest.main()
