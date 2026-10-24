"""Portable fictional consumer/publisher contract tests; no provider or NFL rows."""
import ast
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "nfl_lab/weekly_website_overlay.py"
if not SOURCE.exists(): SOURCE = ROOT / "tools/weekly_adaptive_overlay.py"
spec = importlib.util.spec_from_file_location("weekly_overlay_under_test", SOURCE)
w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)


def fixture():
    board = dict(season=2026, week=8, generated_at="2026-10-24T09:00:00Z",
        games=[dict(id="fictional-game", kickoff="2026-10-25T17:00:00Z", state="pre", home="AAA", away="BBB")],
        players=[dict(id="fictional-player", game_id="fictional-game", team="AAA", opp="BBB",
            props=[dict(key=k, proj=2., adj=2.5, line=3, line_from="dk", lean="under", td_chance=.2,
                        values=[dict(v=3)]) for k in ("rush_att", "rush_yd", "anytime_td", "fpts")])],
        picks={"over":[dict(player_id="fictional-player", key="rush_att", line=3)]}, scoring={"pass_yd":.04})
    rows=[]
    for category, product, functional, value in (("rush_att","point_mean","expected_mean",3.25),
            ("rush_yd","point_median","intended_median",-2.5),
            ("anytime_td","binary_probability","event_probability",.35)):
        row=dict(player_id="fictional-player", game_id="fictional-game", category=category,
            method_id="FICTIONAL_METHOD",model_version="a"*64,procedure_version="b"*64,
            product=product,prediction_functional=functional,forecast_value=value,horizon="player_game",
            source_cutoff_utc="2026-10-25T16:00:00Z", issued_at="2026-10-24T10:00:00Z",
            persistence_completed_at="2026-10-24T10:01:00Z",kickoff_utc="2026-10-25T17:00:00Z",
            valid_until_utc="2026-10-25T17:00:00Z",selection_sha256="c"*64,
            source_policy_sha256="d"*64,query_source_sha256="e"*64,
            season=2026,week=8,evidence_lane="original_pregame",operational_eligible=True,
            team="AAA",opponent="BBB",
            private_training_panel=["FICTIONAL_NEVER_PUBLIC"],raw_provider_value=999)
        rows.append(row)
    selected=dict(rows=rows)
    review=dict(schema_version=w.REVIEW,approved=True,selected_input_sha256=w.digest(selected),website_source_sha="f"*40)
    return board, selected, review


def compile_fixture(board=None, selected=None, review=None, **kwargs):
    a,b,c=fixture();board=board or a;selected=b if selected is None else selected;review=c if review is None else review
    return w.prepare_overlay(board,w.digest(board),selected,review,website_source_sha="f"*40,
        prepared_at=kwargs.pop("prepared_at","2026-10-24T10:02:00Z"),**kwargs)


def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(w.canonical(value))


class OverlayTests(unittest.TestCase):
    def test_typed_projection_preserves_r0_and_excludes_private_fields(self):
        board,selected,review=fixture();original=w.canonical(board)
        doc=compile_fixture(board,selected,review)
        self.assertEqual(len(doc["rows"]),3);self.assertEqual(w.canonical(board),original)
        self.assertNotIn(b"FICTIONAL_NEVER_PUBLIC",w.canonical(doc));self.assertNotIn(b"raw_provider_value",w.canonical(doc))
        self.assertEqual(doc["fallback_counts"]["PPR_or_unsupported_R0"],1)

    def test_no_review_or_different_source_is_default_r0(self):
        for review in ({},dict(fixture()[2],website_source_sha="0"*40)):
            doc=compile_fixture(review=review)
            self.assertEqual(doc["state"],"DISABLED_USE_R0");self.assertEqual(doc["rows"],[])

    def test_duplicate_unknown_and_different_scope_never_select(self):
        board,selected,review=fixture();selected["rows"].append(copy.deepcopy(selected["rows"][0]));selected["rows"][1]["player_id"]="other"
        selected["rows"][2]["week"]=9;review["selected_input_sha256"]=w.digest(selected)
        self.assertEqual(compile_fixture(board,selected,review)["rows"],[])

    def test_late_issue_persistence_cutoff_and_stale_are_r0(self):
        for field,value in (("issued_at","2026-10-26T00:00:00Z"),("persistence_completed_at","2026-10-25T17:00:00Z"),
                            ("source_cutoff_utc","2026-10-25T17:00:00Z"),("valid_until_utc","2026-10-24T10:01:30Z")):
            board,selected,review=fixture()
            for row in selected["rows"]:row[field]=value
            review["selected_input_sha256"]=w.digest(selected)
            self.assertEqual(compile_fixture(board,selected,review)["rows"],[])

    def test_replay_point_blend_and_count_to_probability_are_unsupported(self):
        for update in (dict(evidence_lane="current_vintage_availability_uncertain"),dict(product="point_blend"),
                       dict(product="binary_probability",prediction_functional="event_probability")):
            board,selected,review=fixture();selected["rows"]=selected["rows"][:1];selected["rows"][0].update(update)
            review["selected_input_sha256"]=w.digest(selected)
            self.assertEqual(compile_fixture(board,selected,review)["rows"],[])

    def test_negative_signed_and_zero_counts_legal(self):
        board,selected,review=fixture();selected["rows"][0]["forecast_value"]=0.;review["selected_input_sha256"]=w.digest(selected)
        doc=compile_fixture(board,selected,review)
        self.assertEqual(doc["rows"][0]["forecast_value"],.35) # stable category order
        self.assertIn(-2.5,[r["forecast_value"] for r in doc["rows"]]);self.assertIn(0.,[r["forecast_value"] for r in doc["rows"]])

    def test_started_rows_byte_exact_even_after_new_candidate_or_rollback(self):
        board,selected,review=fixture();old=compile_fixture(board,selected,review);before=[w.canonical(r) for r in old["rows"]]
        board["games"][0]["state"]="in";selected["rows"][0]["forecast_value"]=100.
        doc=compile_fixture(board,selected,{},prepared_at="2026-10-25T17:30:00Z",previous=old)
        self.assertEqual([w.canonical(r) for r in doc["rows"]],before)
        self.assertEqual(len(doc["frozen_rows"]),3)

    def test_new_postkickoff_rows_never_appear(self):
        board,selected,review=fixture();board["games"][0]["state"]="in"
        self.assertEqual(compile_fixture(board,selected,review,prepared_at="2026-10-25T17:30:00Z")["rows"],[])

    def test_repackage_changes_no_row_or_original_and_binds_visible_bytes(self):
        board,selected,review=fixture();doc=compile_fixture(board,selected,review);visible=copy.deepcopy(board);visible["public_only"]=True
        staged=w.repackage(doc,board,w.digest(board),visible,w.digest(visible),packaged_at="2026-10-24T10:03:00Z")
        self.assertEqual(staged["rows"],doc["rows"]);self.assertEqual(doc["display_board_sha256"],w.digest(board))
        visible["players"][0]["props"][0]["line"]=4
        with self.assertRaises(ValueError):w.repackage(doc,board,w.digest(board),visible,w.digest(visible),packaged_at="2026-10-24T10:03:00Z")

    def test_publication_hash_readback_stage_allowlist_and_corruption(self):
        board,selected,review=fixture();doc=compile_fixture(board,selected,review)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);atomic(root/"output/data/week.json",board)
            ptr=w.write_public(doc,root/"output/data",atomic)
            self.assertEqual(w.read_public(root/"output")[1],doc)
            self.assertEqual(w.stage_assets(root),{"weekly-adaptive-overlay.js","data/weekly-adaptive-overlay.json",ptr["path"]})
            p=root/"output"/ptr["path"];p.write_bytes(p.read_bytes()+b" ")
            with self.assertRaises(ValueError):w.read_public(root/"output")

    def test_private_descriptor_cannot_read_arbitrary_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ("/etc/passwd","../../secret.json","data/cache/rows.json"):
                with self.assertRaises(ValueError):w.private_input_path(directory,value)

    def test_current_board_team_and_opponent_binding_is_required(self):
        board,selected,review=fixture()
        for row in selected['rows']:row['opponent']='OTHER'
        review['selected_input_sha256']=w.digest(selected)
        self.assertEqual(compile_fixture(board,selected,review)['rows'],[])

    def test_optional_schema_and_real_publisher_serializer(self):
        # The exact website helper body is exercised if the pinned readonly
        # source snapshot exists. No website package/import/build is executed.
        source=ROOT/'tools/reliability.py'
        if not source.exists():source=Path('/tmp/weekly-website-source-78965e0/tools/reliability.py')
        if not source.exists():self.skipTest('readonly source snapshot unavailable')
        tree=ast.parse(source.read_text());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'canonical','atomic_json'}]
        ns=dict(json=json,os=os,tempfile=tempfile,Path=Path);exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),ns)
        board,selected,review=fixture();doc=compile_fixture(board,selected,review)
        with tempfile.TemporaryDirectory() as directory:
            w.write_public(doc,Path(directory),ns['atomic_json'])


if __name__=='__main__':unittest.main()
