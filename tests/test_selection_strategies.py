"""Prospective strategy controls; wholly fictional boards, no providers."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
from reliability import IntegrityError, digest, make_payload, stamp
import data_integrity_v2 as corrected
import selection_strategies as strategies
from evidence import read

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def fixture():
    games = [dict(id="fictional-game-" + str(i), home="AAA", away="BBB", state="pre", kickoff=stamp(NOW + timedelta(hours=25))) for i in range(3)]
    players = [dict(id="fictional-player-" + str(i), name="Fictional Player " + str(i), game_id=games[i]["id"], team="AAA", opp="BBB", pos="WR", injury=None,
                    games_this_season=3, snap_share=.8, proj_ppr=10 + 10 * i, late=False,
                    props=[dict(key="rec", proj=5, adj=8-i, line=4.5, line_from="dk", lean="over", mf=1, over=60, n=3)]) for i in range(3)]
    board = dict(season=2026, week=9, generated_at=stamp(NOW), games=games, players=players, picks={"over": [], "under": []})
    native = make_payload(board, NOW, corrected.legacy_engine_hashes(), "live")
    return board, native


class StrategyTests(unittest.TestCase):
    def test_ranked_strategies_are_different_and_input_order_invariant(self):
        board, native = fixture(); rules = strategies.policy()
        result = strategies.rank(board, native, rules, NOW)
        biggest = result["memberships"][strategies.STRATEGIES[0]]
        points = result["memberships"][strategies.STRATEGIES[1]]
        self.assertEqual(biggest[0]["row_sha256"], digest(native["rows"][0]))
        self.assertEqual(points[0]["row_sha256"], digest(native["rows"][2]))
        self.assertEqual(len(biggest), 3)  # Never force twelve.
        board["players"].reverse(); board["games"].reverse()
        native["input_sha256"] = digest(board)
        self.assertEqual(result, strategies.rank(board, native, rules, NOW))

    def test_missing_direct_ppr_is_not_replaced_by_component_ppr(self):
        board, _ = fixture(); player = board["players"][0]
        player["proj_ppr"] = None
        player["props"].append(dict(key="fpts", proj=50, adj=50, line=40, line_from="ours", lean="over", mf=1))
        native = make_payload(board, NOW, corrected.legacy_engine_hashes(), "live")
        result = strategies.rank(board, native, strategies.policy(), NOW)
        self.assertTrue(any(e["reason"] == "missing_direct_player_ppr" for e in result["exclusions"]))
        self.assertFalse(any(c["row"]["player_id"] == player["id"] for c in result["candidates"]))

    def test_sources_unknowns_and_kickoff_remain_exclusions(self):
        board, _ = fixture(); board["players"][0]["props"][0]["line_from"] = "ours"
        board["players"][1]["props"][0]["adj"] = None
        native = make_payload(board, NOW, corrected.legacy_engine_hashes(), "live")
        result = strategies.rank(board, native, strategies.policy(), NOW)
        self.assertEqual({e["reason"] for e in result["exclusions"]}, {"missing_real_reference_source", "unknown_projection_or_line"})
        self.assertEqual(len(result["memberships"][strategies.STRATEGIES[0]]), 1)
        late = strategies.rank(board, native, strategies.policy(), NOW + timedelta(hours=25))
        self.assertTrue(all(not rows for rows in late["memberships"].values()))
        native["rows"][0]["line"] = 9
        board["players"][0]["props"][0]["line_from"] = "dk"; native["input_sha256"] = digest(board)
        with self.assertRaises(IntegrityError): strategies.rank(board, native, strategies.policy(), NOW)

    def test_completion_boundary_retry_and_failure_markers(self):
        # The qualifier and source transport are mocked here; actual wrapper
        # replay is an independent integration check, not established by this test.
        board, native = fixture(); q = {"native_payload_sha256": digest(native)}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / "tools").mkdir()
            (root / strategies.POLICY_PATH).write_bytes((ROOT / strategies.POLICY_PATH).read_bytes())
            at = iter([NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2), NOW + timedelta(seconds=3)])
            with patch("phase2_capture._strategy_qualification", return_value=(board, native)), patch.object(strategies, "_source", return_value={"fictional": "bound"}):
                completed = strategies.record(root, q, "a" * 40, clock=lambda: next(at))
                before = completed.read_bytes()
                again = strategies.record(root, q, "a" * 40, clock=lambda: NOW + timedelta(seconds=5))
                self.assertEqual(again, completed); self.assertEqual(before, completed.read_bytes())
                strategies.read_completed(root, completed.relative_to(root).as_posix(), now=NOW + timedelta(days=2))
                second = copy.deepcopy(native); second["captured_at"] = stamp(NOW + timedelta(seconds=5))
                other = {"native_payload_sha256": digest(second)}
                def qualify(_root, qualification, _cutoff, **_kwargs):
                    return board, native if qualification["native_payload_sha256"] == digest(native) else second
                values = iter([NOW + timedelta(seconds=10), NOW + timedelta(hours=26), NOW + timedelta(hours=26), NOW + timedelta(hours=26)])
                with patch("phase2_capture._strategy_qualification", side_effect=qualify):
                    with self.assertRaises(IntegrityError):
                        strategies.record(root, other, "a" * 40, clock=lambda: next(values))
                    failures = list((root / "data" / strategies.FAILURE_LANE).rglob("*.json.gz"))
                    self.assertEqual(len(failures), 1)
                    failed = next(p for p in (root / "data" / strategies.COMPLETE_LANE).rglob("*.json.gz") if p != completed)
                    with self.assertRaises(strategies.UnqualifiedStrategy):
                        strategies.read_completed(root, failed.relative_to(root).as_posix(), now=NOW + timedelta(days=2))
                    strategies.read_completed(root, completed.relative_to(root).as_posix(), now=NOW + timedelta(days=2))
                self.assertEqual(before, completed.read_bytes())



class StrategySavedDecisionTests(unittest.TestCase):
    """Real ranking/decision/ledger algorithms with explicit fictional snapshots.

    These compact controls do not claim original-input qualification. The
    connected updater test separately exercises the actual evidence validator.
    """
    def timing(self):
        from reliability import load_json
        return load_json(ROOT / "config/timing-policy.json")

    def snapshot(self, *, created, completed=None, native_at=None, line=4.5):
        from scorecard import identity
        board, _ = fixture()
        board["players"][0]["props"][0]["line"] = line
        native = make_payload(board, native_at or created, corrected.legacy_engine_hashes(), "live")
        ranked = strategies.rank(board, native, strategies.policy(), created)
        saved = {"schema_version": strategies.VERSION, "season": board["season"], "week": board["week"],
                 "policy_sha256": digest(strategies.policy()), "source_sha": "a" * 40,
                 "source_files": {"explicit_unit_fixture": "not_a_qualification_claim"},
                 "created_at": stamp(created), "qualification": {"native_payload_sha256": digest(native)},
                 "ranked": ranked}
        done = {"schema_version": strategies.COMPLETION, "season": board["season"], "week": board["week"],
                "observation_receipt": "explicit-unit-fixture-only", "observation_sha256": digest(saved),
                "completed_at": stamp(completed or created)}
        return {"payload_sha256": digest(native), "captured_at": saved["created_at"],
                "native_captured_at": native["captured_at"], "forecast_generated_at": native["forecast_generated_at"],
                "season": saved["season"], "week": saved["week"], "model": native["model"],
                "engine_sha256": native["engine_sha256"], "engine_files": native["engine_files"],
                "rows": {identity(r): dict(r, observation_row_sha256=digest(r)) for r in native["rows"]},
                "saved": saved, "completed": done}

    def test_checkpoint_requires_completed_evidence_and_keeps_original_collection_clock(self):
        boundary = NOW + timedelta(hours=1)  # fixture kickoff is NOW + 25h.
        early = self.snapshot(created=boundary - timedelta(minutes=20),
                              completed=boundary - timedelta(minutes=19),
                              native_at=boundary - timedelta(minutes=21))
        late = self.snapshot(created=boundary - timedelta(seconds=10),
                             completed=boundary + timedelta(seconds=10), line=5.5)
        rows = strategies._records([late, early], self.timing(), boundary + timedelta(minutes=2))
        due = [r for r in rows if r["checkpoint"] == "24h"]
        self.assertTrue(due)
        for row in due:
            self.assertEqual(row["strategy_receipt_sha256"], digest(early["saved"]))
            self.assertEqual(row["collected_at"], early["native_captured_at"])
            self.assertEqual(row["recorded_selection_at"], early["captured_at"])
            self.assertNotEqual(row["collected_at"], row["recorded_selection_at"])
        only_late = strategies._records([late], self.timing(), boundary + timedelta(minutes=2))
        self.assertFalse(any(r["checkpoint"] == "24h" for r in only_late))

    def test_first_membership_and_missing_source_reason_are_preserved(self):
        early = self.snapshot(created=NOW + timedelta(seconds=10), native_at=NOW)
        later = self.snapshot(created=NOW + timedelta(minutes=5), line=5.5)
        rows = strategies._records([later, early], self.timing(), NOW + timedelta(minutes=6))
        for row in (r for r in rows if r["checkpoint"] == "history" and r["action"] == "SELECT"):
            self.assertEqual(row["strategy_receipt_sha256"], digest(early["saved"]))
            self.assertEqual(row["collected_at"], stamp(NOW))
        # Exercise actual rank exclusions, rather than assigning an output state.
        board, _ = fixture()
        board["players"][0]["props"][0]["line_from"] = "ours"
        native = make_payload(board, NOW, corrected.legacy_engine_hashes(), "live")
        unknown = self.snapshot(created=NOW)
        from scorecard import identity
        unknown["rows"] = {identity(r): dict(r, observation_row_sha256=digest(r)) for r in native["rows"]}
        unknown["saved"]["ranked"] = strategies.rank(board, native, strategies.policy(), NOW)
        unknown["completed"]["observation_sha256"] = digest(unknown["saved"])
        rows = strategies._records([unknown], self.timing(), NOW + timedelta(seconds=1))
        absent = [r for r in rows if r["player_id"] == "fictional-player-0" and r["checkpoint"] == "history"]
        self.assertEqual(len(absent), len(strategies.STRATEGIES))
        self.assertTrue(all(r["action"] == "NO_ACTION" and r["reason"] == "missing_real_reference_source" for r in absent))

    def test_frozen_checkpoint_uses_pinned_witness_when_later_inventory_would_choose_another(self):
        boundary = NOW + timedelta(hours=1)
        early = self.snapshot(created=boundary - timedelta(minutes=30))
        alternate = self.snapshot(created=boundary - timedelta(minutes=10), line=5.5)
        at = boundary + timedelta(minutes=1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial = strategies._records([early], self.timing(), at)
            frozen = strategies._freeze(root, initial, [early], self.timing(), at)
            due = {r["decision_key"]: r for r in frozen if r["checkpoint"] == "24h"}
            self.assertTrue(due)
            originals = {p.relative_to(root): p.read_bytes() for p in (root / "data").rglob("*.json.gz")}
            recomputed = strategies._records([early, alternate], self.timing(), at + timedelta(seconds=1))
            changed = {r["decision_key"]: r for r in recomputed if r["checkpoint"] == "24h"}
            self.assertTrue(any(changed[key] != row for key, row in due.items()))
            retained = strategies._freeze(root, recomputed, [early, alternate], self.timing(), at + timedelta(seconds=1))
            self.assertEqual({r["decision_key"]: r for r in retained if r["checkpoint"] == "24h"}, due)
            for name, raw in originals.items():
                self.assertEqual((root / name).read_bytes(), raw)
            # Another matching completed witness cannot replace a missing pin.
            with self.assertRaisesRegex(IntegrityError, "witness unavailable"):
                strategies._freeze(root, recomputed, [alternate], self.timing(), at + timedelta(seconds=2))

    def test_self_consistently_rehashed_ledger_row_and_helper_identity_are_rejected(self):
        from evidence import write
        boundary = NOW + timedelta(hours=1)
        snapshot = self.snapshot(created=boundary - timedelta(minutes=20))
        rows = strategies._records([snapshot], self.timing(), boundary)
        for change in ("row", "helper"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                strategies._freeze(root, rows, [snapshot], self.timing(), boundary)
                ledger = next((root / "data/ranked_selection_decisions").rglob("*.json.gz"))
                payload = copy.deepcopy(read(ledger))
                if change == "row":
                    payload["rows"][0]["line"] += 1
                    row = payload["rows"][0]
                    row.pop("decision_sha256"); row["decision_sha256"] = digest(row)
                else:
                    payload["helper_files"]["tools/selection_strategies.py"] = "0" * 64
                write(root, "ranked_selection_decisions", payload)
                with self.assertRaises(IntegrityError):
                    strategies._freeze(root, rows, [snapshot], self.timing(), boundary + timedelta(seconds=1))


class StrategyPersistenceBoundaryTests(unittest.TestCase):
    def setup_root(self, directory):
        from reliability import immutable_write
        root = Path(directory); (root / "tools").mkdir()
        (root / strategies.POLICY_PATH).write_bytes((ROOT / strategies.POLICY_PATH).read_bytes())
        board, native = fixture()
        native_id=digest({"data":native["input_sha256"],"engine":native["engine_sha256"],"mode":native["mode"]})
        path=root/"data/forward"/str(board["season"])/f"w{board['week']:02d}"/(native_id+".json.gz")
        immutable_write(path,native)
        qualification = {"native_receipt": path.relative_to(root).as_posix(), "native_payload_sha256": digest(native)}
        return root, board, native, qualification

    def test_completed_bytes_followed_by_write_failure_are_marked_and_ineligible(self):
        # Only original-input qualification and source transport are mocked.
        # Completion write, marker, strict saved reader and consumer are real.
        from evidence import write
        with tempfile.TemporaryDirectory() as directory:
            root, board, native, qualification = self.setup_root(directory)
            def fail_after_persistence(destination, lane, payload):
                path = write(destination, lane, payload)
                if lane == strategies.COMPLETE_LANE:
                    raise OSError("Fictional completion readback failure after immutable bytes landed")
                return path
            with patch("phase2_capture._strategy_qualification", return_value=(board, native)), \
                    patch.object(strategies, "_source", return_value={"fixture": "mocked_source_transport"}), \
                    patch.object(strategies, "write", side_effect=fail_after_persistence):
                with self.assertRaises(OSError):
                    strategies.record(root, qualification, "a" * 40, clock=lambda: NOW)
            complete = list((root / "data" / strategies.COMPLETE_LANE).rglob("*.json.gz"))
            self.assertEqual(len(complete), 1)
            with self.assertRaises(strategies.UnqualifiedStrategy):
                strategies.read_completed(root, complete[0].relative_to(root).as_posix(), now=NOW + timedelta(seconds=1))
            from reliability import load_json
            self.assertEqual(strategies.decisions([root], load_json(ROOT / "config/timing-policy.json"), NOW + timedelta(seconds=1)), [])
            self.assertEqual(len(list((root / "data" / strategies.FAILURE_LANE).rglob("*.json.gz"))), 1)

    def test_kickoff_crossing_during_final_expensive_validation_cannot_supply_a_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root, board, native, qualification = self.setup_root(directory)
            kickoff = NOW + timedelta(hours=25)
            values = iter([NOW, kickoff - timedelta(seconds=2), kickoff - timedelta(seconds=1), kickoff])
            with patch("phase2_capture._strategy_qualification", return_value=(board, native)), \
                    patch.object(strategies, "_source", return_value={"fixture": "mocked_source_transport"}):
                with self.assertRaises(IntegrityError):
                    strategies.record(root, qualification, "a" * 40, clock=lambda: next(values, kickoff))
            complete = next((root / "data" / strategies.COMPLETE_LANE).rglob("*.json.gz"))
            self.assertLess(read(complete)["completed_at"], stamp(kickoff))
            with self.assertRaises(strategies.UnqualifiedStrategy):
                strategies.read_completed(root, complete.relative_to(root).as_posix(), now=kickoff + timedelta(seconds=1))

    def test_actual_committed_source_binding_and_unknown_source_rejection(self):
        # This intentionally requires a committed final source; it must not be
        # attributed to an earlier HEAD while helper bytes remain unpublished.
        import hashlib
        import subprocess
        source = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        expected = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in strategies.SOURCE_PATHS}
        self.assertEqual(strategies._source(ROOT, source), expected)
        with self.assertRaises(IntegrityError):
            strategies._source(ROOT, "0" * 40)



if __name__ == "__main__": unittest.main()
