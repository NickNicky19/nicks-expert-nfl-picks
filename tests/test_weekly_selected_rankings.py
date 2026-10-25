"""Fictional software fixtures only; no NFL evidence or provider calls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import weekly_adaptive_overlay as o
import weekly_selected_rankings as r
from reliability import atomic_json

NOW = "2031-10-24T12:00:00+00:00"
PERSIST = "2031-10-24T12:00:01+00:00"
KICKOFF = "2031-10-25T17:00:00+00:00"
H = "a" * 64


def fixture():
    def player(pid, raw):
        return dict(id=pid, name="Fictional " + pid, game_id="fictional-game", pos="RB", team="AAA", opp="BBB",
                    injury=None, games_this_season=6, snap_share=.75, proj_ppr=12,
                    props=[dict(key="rush_yd", adj=raw, proj=raw, line=30.5, line_from="dk", lean="under" if raw < 30.5 else "over", over=2, n=6, values=[])])
    board = dict(season=2031, week=7, generated_at=NOW,
                 games=[dict(id="fictional-game", kickoff=KICKOFF, state="pre", home="AAA", away="BBB")],
                 players=[player("fictional-a", 20), player("fictional-b", 45)],
                 picks={"over": [], "under": []}, categories={"rush_yd": {"label": "Rushing Yards", "lean": 4}})
    selected = dict(rows=[dict(player_id=p["id"], game_id=p["game_id"], category="rush_yd", method_id="FICTIONAL",
        model_version=H, procedure_version=H, product="point_median", prediction_functional="intended_median", forecast_value=value,
        horizon="player_game", source_cutoff_utc="2031-10-24T11:00:00+00:00", issued_at="2031-10-24T10:00:00+00:00",
        persistence_completed_at="2031-10-24T10:01:00+00:00", kickoff_utc=KICKOFF, valid_until_utc=KICKOFF,
        selection_sha256=H, source_policy_sha256=H, query_source_sha256=H, season=2031, week=7,
        team="AAA", opponent="BBB", evidence_lane="original_pregame", operational_eligible=True)
        for p, value in zip(board["players"], [50.0, 18.0])])
    review = dict(schema_version=o.REVIEW, approved=True, selected_input_sha256=o.digest(selected), website_source_sha="b" * 40)
    board_sha = o.digest(board)
    doc = o.prepare_overlay(board, board_sha, selected, review, website_source_sha="b" * 40, prepared_at=NOW)
    return board, doc


def make(board, doc, **kwargs):
    return r.prepare(board, o.digest(board), doc, o.digest(doc), now=kwargs.pop("now", NOW), website_source_sha="b" * 40, **kwargs)


class SelectedRankingsTests(unittest.TestCase):
    def test_selected_reverses_reference_and_original_stays_intact(self):
        board, doc = fixture(); original = copy.deepcopy((board, doc))
        out = make(board, doc)
        self.assertEqual(out["picks"]["over"][0]["player_id"], "fictional-a")
        self.assertEqual(out["picks"]["over"][0]["adj"], 50)
        self.assertEqual(out["picks"]["under"][0]["player_id"], "fictional-b")
        self.assertEqual(out["picks"]["under"][0]["adj"], 18)
        self.assertEqual((board, doc), original)
        self.assertEqual(out["picks"]["over"][0]["forecast_source"], "SELECTED")

    def test_missing_row_falls_back_explicitly_not_zero(self):
        board, doc = fixture(); doc["rows"] = []
        out = make(board, doc)
        self.assertEqual(out["picks"]["over"][0]["adj"], 45)
        self.assertEqual(out["picks"]["under"][0]["adj"], 20)
        self.assertTrue(all(x["forecast_source"] == "R0_FALLBACK" for side in out["picks"].values() for x in side))
        board["players"][0]["props"][0]["adj"] = None
        doc["display_board_sha256"] = doc["canonical_board_sha256"] = o.digest(board)
        doc["board_contract_sha256"] = o.digest(o.board_contract(board))
        out = make(board, doc)
        self.assertEqual(out["picks"]["under"], [])
        self.assertEqual(out["fallback_counts"]["unavailable_forecast"], 1)

    def test_zero_and_signed_yards_are_retained(self):
        board, doc = fixture(); row = doc["rows"][0]; p = board["players"][0]; prop = p["props"][0]
        for value in [0, -5.25]:
            row["forecast_value"] = value
            self.assertEqual(r.effective(p, prop, doc, NOW)[0], value)

    def test_unsupported_population_and_fake_lines_not_top(self):
        board, doc = fixture()
        for field, value in [("injury", "Out"), ("snap_share", None), ("games_this_season", 0), ("proj_ppr", None)]:
            b = copy.deepcopy(board); b["players"][0][field] = value
            d = copy.deepcopy(doc); d["display_board_sha256"] = d["canonical_board_sha256"] = o.digest(b)
            out = make(b, d)
            self.assertFalse(out["picks"]["over"])
        board["players"][0]["props"][0]["line_from"] = "ours"
        doc["display_board_sha256"] = doc["canonical_board_sha256"] = o.digest(board)
        doc["board_contract_sha256"] = o.digest(o.board_contract(board))
        self.assertFalse(make(board, doc)["picks"]["over"])

    def test_ties_stable_and_one_candidate_per_player_side(self):
        board, doc = fixture()
        board["players"][1]["props"][0]["adj"] = 20
        doc["rows"][1]["forecast_value"] = 50
        for player, row, pid in zip(board["players"], doc["rows"], ["1", "10"]):
            player["id"] = row["player_id"] = pid
        doc["display_board_sha256"] = doc["canonical_board_sha256"] = o.digest(board)
        doc["board_contract_sha256"] = o.digest(o.board_contract(board))
        out = make(board, doc)
        self.assertEqual([x["player_id"] for x in out["picks"]["over"]], ["1", "10"])

    def test_started_games_are_never_backfilled(self):
        board, doc = fixture()
        out = make(board, doc, now="2031-10-25T18:00:00+00:00")
        self.assertEqual(out["picks"], {"over": [], "under": []})
        self.assertEqual(out["fallback_counts"]["started_without_selected_record"], 1)

    def test_durable_readback_idempotency_and_new_process(self):
        board, doc = fixture(); out = make(board, doc)
        with tempfile.TemporaryDirectory() as td:
            pointer = r.write_public(out, td, atomic_json, clock=lambda: PERSIST)
            self.assertEqual(r.read_public(td), (pointer, out))
            files = {p.name: p.read_bytes() for p in Path(td).rglob("*.json")}
            self.assertEqual(r.write_public(out, td, atomic_json, clock=lambda: PERSIST), pointer)
            self.assertEqual({p.name: p.read_bytes() for p in Path(td).rglob("*.json")}, files)
            code = "import sys,json;sys.path.insert(0,sys.argv[1]);import weekly_selected_rankings as r;print(json.dumps(r.read_public(sys.argv[2])[0]))"
            restored = subprocess.check_output([sys.executable, "-c", code, str(Path(r.__file__).parent), td], timeout=10)
            self.assertEqual(json.loads(restored), pointer)

    def test_frozen_membership_line_model_and_clock_persist(self):
        board, doc = fixture(); old = make(board, doc)
        with tempfile.TemporaryDirectory() as td:
            pointer = r.write_public(old, td, atomic_json, clock=lambda: PERSIST)
            out = make(board, doc, now="2031-10-25T18:00:00+00:00", previous=old, previous_receipt=pointer)
            self.assertEqual(out["picks"], old["picks"])
            self.assertEqual(len(out["frozen_proofs"]), 2)
            for proof in out["frozen_proofs"]: self.assertEqual(proof["persisted_at"], PERSIST)
            r.write_public(out, td, atomic_json, clock=lambda: "2031-10-25T18:00:01+00:00")
            board["players"][0]["props"][0]["line"] = 35.5
            doc["display_board_sha256"] = doc["canonical_board_sha256"] = o.digest(board)
            doc["board_contract_sha256"] = o.digest(o.board_contract(board))
            with self.assertRaises(ValueError): make(board, doc, now="2031-10-25T18:00:00+00:00", previous=old, previous_receipt=pointer)

    def test_crossing_kickoff_never_advances_pointer(self):
        board, doc = fixture(); out = make(board, doc)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError): r.write_public(out, td, atomic_json, clock=lambda: "2031-10-25T17:00:00+00:00")
            self.assertFalse((Path(td) / "weekly-selected-rankings.json").exists())

    def test_bad_row_hash_and_previous_receipt_rejected(self):
        board, doc = fixture(); out = make(board, doc)
        bad = copy.deepcopy(out["picks"]["over"][0]); bad["selected_row_sha256"] = "f" * 64
        with self.assertRaises(ValueError): r.validate_item(bad, o.board_offers(board), {o.key(x): x for x in doc["rows"]})
        with self.assertRaises(ValueError): make(board, doc, previous=out, previous_receipt={"sha256": "f" * 64})

    def test_unknown_history_is_not_invented_zero(self):
        board, doc = fixture(); board["players"][0]["props"][0].pop("n")
        doc["display_board_sha256"] = doc["canonical_board_sha256"] = o.digest(board)
        self.assertEqual(make(board, doc)["picks"]["over"], [])

    def test_expiry_between_selection_and_persistence_rejected(self):
        board, doc = fixture(); doc["rows"][0]["valid_until_utc"] = "2031-10-24T12:00:00.500000+00:00"
        out = make(board, doc)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "expired"):
                r.write_public(out, td, atomic_json, clock=lambda: PERSIST)
            self.assertFalse((Path(td) / "weekly-selected-rankings.json").exists())

    def test_early_expiry_never_freezes_or_promotes_replacement(self):
        board, doc = fixture(); doc["rows"][0]["valid_until_utc"] = "2031-10-24T13:00:00+00:00"
        old = make(board, doc)
        with tempfile.TemporaryDirectory() as td:
            pointer = r.write_public(old, td, atomic_json, clock=lambda: PERSIST)
            renewed = o.prepare_overlay(board, o.digest(board), {}, {}, website_source_sha="b" * 40,
                                        prepared_at="2031-10-25T18:00:00+00:00", previous=doc)
            self.assertNotIn("fictional-a", [row["player_id"] for row in renewed["rows"]])
            out = make(board, renewed, now="2031-10-25T18:00:00+00:00", previous=old, previous_receipt=pointer)
            self.assertEqual(out["picks"]["over"], [])
            self.assertEqual(out["fallback_counts"]["expired_before_kickoff"], 1)

    def test_complete_public_graph_and_original_receipts_are_required(self):
        board, doc = fixture(); old = make(board, doc)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); data = root / "data"
            atomic_json(data / "week.json", board)
            o.write_public(doc, data, atomic_json)
            pointer = r.write_public(old, data, atomic_json, clock=lambda: PERSIST)
            paths = o.validate_public_root(root)
            self.assertIn("data/weekly-selected-rankings.json", paths)
            self.assertIn("data/" + pointer["path"], paths)
            frozen = make(board, doc, now="2031-10-25T18:00:00+00:00", previous=old, previous_receipt=pointer)
            r.write_public(frozen, data, atomic_json, clock=lambda: "2031-10-25T18:00:01+00:00")
            paths = o.validate_public_root(root)
            original_receipt = "weekly-selected-rankings/" + o.digest(pointer) + ".receipt.json"
            self.assertIn("data/" + original_receipt, paths)
            (data / original_receipt).unlink()
            with self.assertRaises(OSError): o.validate_public_root(root)

    def test_closed_pointer_rejects_extra_fields_bad_clocks_and_byte_types(self):
        board, doc = fixture(); out = make(board, doc)
        with tempfile.TemporaryDirectory() as td:
            pointer = r.write_public(out, td, atomic_json, clock=lambda: PERSIST)
            for change in [lambda x: x.update(extra=True), lambda x: x.update(bytes=True), lambda x: x.update(published_at="2031-10-24T12:00:01")]:
                bad = dict(pointer); change(bad); atomic_json(Path(td) / "weekly-selected-rankings.json", bad)
                with self.assertRaises(ValueError): r.read_public(td)

    def test_closed_document_rejects_bad_source_and_coverage(self):
        board, doc = fixture(); out = make(board, doc)
        with tempfile.TemporaryDirectory() as td:
            pointer = r.write_public(out, td, atomic_json, clock=lambda: PERSIST)
            for change in [lambda x: x.update(extra=True), lambda x: x.update(website_source_sha="invalid"),
                           lambda x: x["fallback_counts"].update(unavailable_forecast=-1)]:
                bad = copy.deepcopy(out); change(bad)
                with self.assertRaises(ValueError): r.validate_document(bad, pointer, board, o.digest(board), doc)


    def test_valid_over_cannot_be_rehomed_into_under_container(self):
        board, doc = fixture(); good = make(board, doc)
        with tempfile.TemporaryDirectory() as td:
            pointer = r.write_public(good, td, atomic_json, clock=lambda: PERSIST)
            r.validate_document(good, pointer, board, o.digest(board), doc, root=td)
            bad = copy.deepcopy(good)
            bad["picks"]["under"].append(bad["picks"]["over"].pop(0))
            bad["picks"]["under"].sort(key=r.order)
            pointer = r.write_public(bad, td, atomic_json, clock=lambda: PERSIST)
            with self.assertRaisesRegex(ValueError, "ranking side mismatch"):
                r.validate_document(bad, pointer, board, o.digest(board), doc, root=td)



if __name__ == "__main__":
    unittest.main()
