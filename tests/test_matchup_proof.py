"""Recorded populations, corrected caches, frozen forecasts, and hard failures."""
import copy
from datetime import timedelta
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
from reliability import digest, stamp
from test_reliability import NOW
from test_source_evidence import fictional_status


def fixture(root):
    weeks = {"1": {"a": {"opp": "BBB", "stats": {"gp": 1, "rec": 2}},
                   "bye": {"opp": "BBB", "stats": {"gp": 1, "rec": 8}}},
             "2": {"a": {"opp": "CCC", "stats": {"gp": 1, "rec": 4}},
                   "bye": {"opp": "DDD", "stats": {"gp": 1, "rec": 4}}}}
    positions = {"a": "WR", "bye": "WR"}
    f, n = matchup.Matchups({int(w): x for w, x in weeks.items()}, positions).factor("BBB", "WR", "rec", 3)
    data = {"season": 2026, "week": 3, "generated_at": stamp(NOW),
            "games": [{"id": "g", "home": "AAA", "away": "BBB", "state": "pre",
                       "kickoff": stamp(NOW + timedelta(hours=1))}], "players": [
        {"id": "a", "name": "Fixture", "pos": "WR", "team": "AAA", "opp": "BBB", "game_id": "g", "props": [
            {"key": "rec", "proj": 4, "adj": round(4 * f, 2), "mf": f, "mf_n": n,
             "values": [{"s": 2026, "w": 1, "v": 2}, {"s": 2026, "w": 2, "v": 4}]}]}]}
    payload = {"schema_version": "matchup-inputs-v2", "mode": "replay", "build_started_at": stamp(NOW),
               "inputs_observed_at": stamp(NOW), "recorded_at": stamp(NOW),
               "season": 2026, "week": 3, "engine_files": {"test": "fixture"}, "positions": positions,
               "weeks": weeks, "week_data": copy.deepcopy(data), "output_sha256": digest(data),
               "source_requests": [], "game_status": {"2026_03": fictional_status(
                   data["games"], 3, mode="replay", collected_at=NOW)}}
    path = write(root, "verification", payload)
    proof = {"schema_version": "matchup-proof-v1", "output_sha256": digest(data),
             "latest_inputs": path.relative_to(root).as_posix(),
             "game_origins": {"g": path.relative_to(root).as_posix()}}
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

    def rebind(self, root, data, proof, payload):
        payload["output_sha256"] = digest(payload["week_data"])
        path = write(root, "verification", payload)
        name = path.relative_to(root).as_posix()
        proof.update(output_sha256=digest(data), latest_inputs=name, game_origins={"g": name})
        return path

    def test_postkickoff_original_inputs_or_recording_cannot_be_pregame_proof(self):
        for alteration in ("inputs", "completion", "generation", "at_kickoff"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as d:
                root = Path(d); data, proof, payload, _ = fixture(root)
                late = NOW + timedelta(hours=2)
                payload["recorded_at"] = stamp(late)
                if alteration == "inputs":
                    payload["inputs_observed_at"] = stamp(late)
                    payload["week_data"]["generated_at"] = stamp(late)
                elif alteration == "generation":
                    payload["week_data"]["generated_at"] = stamp(late)
                elif alteration == "at_kickoff":
                    payload["recorded_at"] = data["games"][0]["kickoff"]
                self.rebind(root, data, proof, payload)
                self.assertTrue(any("before kickoff" in x for x in self.check(root, data, proof)))

    def test_inconsistent_missing_or_timezone_free_clocks_fail(self):
        for change in ({"build_started_at": stamp(NOW + timedelta(seconds=1))},
                       {"recorded_at": stamp(NOW - timedelta(seconds=1))},
                       {"inputs_observed_at": "2026-10-10T19:00:00"},
                       {"inputs_observed_at": None}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as d:
                root = Path(d); data, proof, payload, _ = fixture(root)
                payload.update(change)
                self.rebind(root, data, proof, payload)
                self.assertTrue(self.check(root, data, proof))

    def test_retained_builder_second_precision_does_not_make_false_clock_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, payload, _ = fixture(root)
            payload["inputs_observed_at"] = stamp(NOW + timedelta(microseconds=800000))
            payload["recorded_at"] = stamp(NOW + timedelta(microseconds=900000))
            self.rebind(root, data, proof, payload)
            self.assertEqual(self.check(root, data, proof), [])

    def test_original_game_kickoff_team_and_player_mapping_cannot_drift(self):
        for alteration in ("kickoff", "teams", "position", "opponent", "player_team"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as d:
                root = Path(d); data, proof, _, _ = fixture(root)
                if alteration == "kickoff":
                    data["games"][0]["kickoff"] = stamp(NOW + timedelta(hours=2))
                elif alteration == "teams":
                    data["games"][0]["away"] = "CCC"
                else:
                    field = {"position": "pos", "opponent": "opp", "player_team": "team"}[alteration]
                    data["players"][0][field] = {"position": "RB", "opponent": "CCC", "player_team": "BBB"}[alteration]
                proof["output_sha256"] = digest(data)
                self.assertTrue(self.check(root, data, proof))

    def test_duplicate_original_players_props_and_games_are_ambiguous(self):
        for alteration in ("players", "props", "games"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as d:
                root = Path(d); data, proof, payload, _ = fixture(root)
                rows = (payload["week_data"]["players"][0]["props"] if alteration == "props"
                        else payload["week_data"][alteration])
                rows.append(copy.deepcopy(rows[0]))
                self.rebind(root, data, proof, payload)
                self.assertTrue(any("duplicate" in x for x in self.check(root, data, proof)))

    def test_recomputed_envelope_checksum_does_not_allow_rewrite_under_old_address(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, _, path = fixture(root)
            envelope = json.loads(gzip.decompress(path.read_bytes()))
            envelope["payload"]["note"] = "fictional changed observation"
            envelope["payload_sha256"] = digest(envelope["payload"])
            path.write_bytes(gzip.compress(json.dumps(envelope).encode()))
            self.assertTrue(any("content address" in x for x in self.check(root, data, proof)))

    def test_wrong_period_directory_is_not_an_original_reference(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, _, path = fixture(root)
            moved = root / "data/verification/2025/w03" / path.name
            moved.parent.mkdir(parents=True); moved.write_bytes(path.read_bytes())
            proof["game_origins"]["g"] = moved.relative_to(root).as_posix()
            self.assertTrue(any("content address/period" in x for x in self.check(root, data, proof)))

    def test_legacy_missing_qualification_remains_readable_but_not_verified(self):
        from evidence import read
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data, proof, payload, _ = fixture(root)
            payload["schema_version"] = "matchup-inputs-v1"
            path = self.rebind(root, data, proof, payload)
            before = path.read_bytes()
            self.assertEqual(read(path), payload)
            self.assertTrue(any("qualified" in x for x in self.check(root, data, proof)))
            self.assertEqual(path.read_bytes(), before)

    def test_original_source_response_hash_and_period_must_bind_to_games(self):
        for alteration in ("digest", "game_map", "provider_period"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as d:
                root = Path(d); data, proof, payload, _ = fixture(root)
                status = payload["game_status"]["2026_03"]
                if alteration == "digest":
                    status["response_sha256"] = "0" * 64
                elif alteration == "game_map":
                    status["games"]["g"]["kickoff"] = stamp(NOW + timedelta(hours=2))
                else:
                    status["response"]["week"]["number"] = 4
                    status["response_sha256"] = digest(status["response"])
                self.rebind(root, data, proof, payload)
                self.assertTrue(self.check(root, data, proof))


if __name__ == "__main__":
    unittest.main()
