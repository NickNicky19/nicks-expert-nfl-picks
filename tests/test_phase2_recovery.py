from pathlib import Path
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from release_mode import read_phase2
from restore_phase1 import restore_phase1_mode
from restore_original import blob_hash, git
from test_recovery import repository
from reliability import IntegrityError
import phase2_capture


class Phase2RecoveryTests(unittest.TestCase):
    def test_phase1_recovery_keeps_evidence_history_and_runner(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = repository(root)
            (root / ".github/workflows").mkdir(parents=True)
            runner = root / ".github/workflows/hourly.yml"; runner.write_text("recovery-aware runner\n")
            (root / "data/shadow").mkdir(parents=True)
            receipt = root / "data/shadow/keep.json.gz"; receipt.write_bytes(b"fixture evidence")
            git(root, "add", ".github", "data"); git(root, "commit", "-m", "Fixture runner and receipt")
            head = git(root, "rev-parse", "HEAD")
            backup = restore_phase1_mode(root, source, {"code.txt": blob_hash(b"original\n")})
            self.assertFalse(read_phase2(root))
            self.assertEqual(receipt.read_bytes(), b"fixture evidence")
            self.assertEqual(runner.read_text(), "recovery-aware runner\n")
            self.assertEqual(git(root, "rev-parse", "HEAD"), head)
            self.assertEqual(git(root, "rev-parse", backup), head)
            self.assertNotIn("data/", git(root, "diff", "--cached", "--name-only").decode())

    def test_phase1_wrong_hash_and_dirty_worktree_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = repository(root)
            with self.assertRaises(RuntimeError): restore_phase1_mode(root, source, {"code.txt": "wrong"})
            self.assertFalse((root / "config/phase2.json").exists())
            (root / "unsaved.txt").write_text("keep")
            with self.assertRaises(RuntimeError): restore_phase1_mode(root, source, {"code.txt": blob_hash(b"original\n")})

    def test_mode_rejects_attempted_production_switch(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "config").mkdir()
            self.assertFalse(read_phase2(root))
            config = root / "config/phase2.json"
            config.write_text(json.dumps({"capture_enabled": True, "production_model": "original_sleeper_matchup_baseline",
                                          "challenger_production_enabled": False}))
            self.assertTrue(read_phase2(root))
            config.write_text(json.dumps({"capture_enabled": True, "production_model": "challenger", "challenger_production_enabled": True}))
            with self.assertRaises(ValueError): read_phase2(root)

    def test_failed_generation_promotion_restores_old_files_and_mutable_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            root, stage = Path(directory) / "current", Path(directory) / "stage"
            (root / "output/data").mkdir(parents=True)
            old = root / "output/data/week.json"
            old.write_bytes(b'old coherent board')
            for name in ("week.json", "health.json", "release-identity.json", "verification-scope.json",
                         "selection-grading/latest.json", "selection-grading/immutable/summary.json"):
                target = stage / "output/data" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'new derived bytes')
            evidence = stage / "data/verification/fictional/keep.json.gz"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_bytes(b'new immutable evidence')
            with patch.object(phase2_capture, "validate_generation", side_effect=IntegrityError("injected final binding failure")):
                with self.assertRaises(IntegrityError):
                    phase2_capture._promote(stage, root)
            self.assertEqual(old.read_bytes(), b'old coherent board')
            for name in ("health.json", "release-identity.json", "verification-scope.json", "selection-grading/latest.json"):
                self.assertFalse((root / "output/data" / name).exists(), name)
            self.assertEqual((root / evidence.relative_to(stage)).read_bytes(), b'new immutable evidence')
            self.assertTrue((root / "output/data/selection-grading/immutable/summary.json").exists())

    def test_generation_copy_never_overwrites_retained_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root, stage = Path(directory) / "current", Path(directory) / "stage"
            name = "data/verification/fictional/keep.json.gz"
            for base, content in ((root, b'first original'), (stage, b'conflicting original')):
                path = base / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
            with self.assertRaises(IntegrityError): phase2_capture._copy_evidence(stage, root)
            self.assertEqual((root / name).read_bytes(), b'first original')

    def test_partial_configuration_cannot_enable_experiments_or_replace_strict_fallback(self):
        import json
        import partial_week
        from test_partial_week import fixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, _, spec, _ = fixture(root)
            config = {"verification_mode": partial_week.VERSION, "partial_week": spec, "experimental_recording_enabled": False}
            from test_reliability import NOW
            self.assertEqual(partial_week.dispatch(config, dict(data, week=7), NOW), "strict")
            config["experimental_recording_enabled"] = True
            with self.assertRaises(IntegrityError): partial_week.dispatch(config, dict(data, week=7), NOW)


class IssuedRecordLeafTests(unittest.TestCase):
    """Actual graders on fictional inputs; this boundary never regrades history."""

    def record(self, producer=None):
        from test_reliability import fixture
        import grade
        import scoring
        producer = grade if producer is None else producer
        board, _ = fixture()
        who = board["players"][0]
        who["props"].extend([
            {"key":"fpts", "adj":8, "source":"model"},
            {"key":"rush_yd", "line":-.5, "proj":-1, "adj":-1,
             "lean":"under", "line_from":"sleeper"},
        ])
        board["picks"]["under"] = [dict(board["picks"]["over"][0], key="rush_yd",
            direction="under", line=-.5, proj=-1, adj=-1, line_from="sleeper")]
        stats = {key:0 for key in scoring.PPR}
        stats.update(gp=1, rec=5, rec_yd=10, rush_yd=-2, idp_fum_rec=0)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)
            (archive / "2026_w05.json").write_text(json.dumps(board))
            return producer.grade_all(archive, lambda *_:{"fictional-1":{"stats":stats}},
                                      (2026,5), {"fictional-game"}, scores_for=lambda *_:{})

    def old_grader(self, source):
        """Read actual three-file pure producer closure, never current code relabelled."""
        def module(name):
            command = ["git", "--no-replace-objects", "--no-lazy-fetch", "-C", str(ROOT)]
            oid = subprocess.check_output([*command,"rev-parse",source+":pull/"+name+".py"]).decode().strip()
            size = int(subprocess.check_output([*command,"cat-file","-s",oid]))
            self.assertLessEqual(size, 65536)
            raw = subprocess.check_output([*command,"cat-file","blob",oid])
            self.assertEqual(len(raw), size)
            self.assertEqual(hashlib.sha1(b"blob "+str(size).encode()+b"\0"+raw).hexdigest(),oid)
            result = types.ModuleType("issued_test_"+name)
            exec(compile(raw,"actual-retained-"+source+"-"+name,"exec"),result.__dict__)
            return result
        old_scoring = module("scoring")
        with patch.dict(sys.modules, {"scoring":old_scoring}):
            old_game = module("gamemodel")
            with patch.dict(sys.modules, {"gamemodel":old_game}):
                return module("grade")

    def set_path(self, value, path, replacement):
        target = value
        for component in path[:-1]:
            target = target[component]
        target[path[-1]] = replacement

    def leaves(self, value, path=()):
        if isinstance(value, dict):
            for key, child in value.items():
                yield from self.leaves(child, path+(key,))
        elif isinstance(value, list):
            for key, child in enumerate(value):
                yield from self.leaves(child, path+(key,))
        else:
            yield path, value

    def test_actual_old_and_current_grade_outputs_are_unchanged(self):
        producers = [None, *[self.old_grader(source) for source in
            ("89512ed952308dacc1f6a930915ddbcdccd460d9",
             "b3de2fbd88ba3247b407a856972285ad10527b99",
             "0f03af20226c17c54f27f930eccea162ab331c4c")]]
        versions = set()
        for producer in producers:
            record = self.record(producer)
            before = copy.deepcopy(record)
            phase2_capture._issued_record_shape(record)
            self.assertEqual(record, before)
            versions.add(record["grading_version"])
            self.assertEqual(record["weeks"][0]["top_under"]["picks"][0]["actual"], -2)
        self.assertEqual(versions, {"statistical-v2", "statistical-presence-v3",
                         "statistical-v3-identity-20261025", "statistical-presence-fgm-identity-v4"})

    def test_nested_values_are_rejected_at_every_actual_scalar_role(self):
        record = self.record()
        for path, _ in self.leaves(record):
            for nested in ({"raw_provider_records":["FICTIONAL_BOUNDARY_CANARY"]}, [0]):
                changed = copy.deepcopy(record)
                self.set_path(changed,path,nested)
                with self.subTest(path=path, nested=type(nested).__name__), self.assertRaises(IntegrityError):
                    phase2_capture._issued_record_shape(changed)

    def test_boolean_nonfinite_and_invalid_label_controls(self):
        record = self.record()
        for path, original in self.leaves(record):
            if type(original) in (int,float) or original is None and path[-1] in {
                    "line","proj","adj","decision_projection","actual","pct","proj_mae",
                    "average_mae","adjusted_mae","proj_bias","vs_line"}:
                for invalid in (True,float("nan"),float("inf"),float("-inf"),"0"):
                    changed = copy.deepcopy(record); self.set_path(changed,path,invalid)
                    with self.subTest(path=path, invalid=repr(invalid)), self.assertRaises(IntegrityError):
                        phase2_capture._issued_record_shape(changed)
            elif type(original) is bool:
                changed = copy.deepcopy(record); self.set_path(changed,path,0)
                with self.subTest(path=path), self.assertRaises(IntegrityError):
                    phase2_capture._issued_record_shape(changed)
        for path in [("grading_version",),("settlement_status",),("provenance_note",),
                     ("weeks",0,"dk_leans_scope"),("weeks",0,"top_over","picks",0,"key"),
                     ("weeks",0,"top_over","picks",0,"line_from"),
                     ("weeks",0,"top_over","picks",0,"direction"),
                     ("weeks",0,"top_over","picks",0,"result")]:
            changed = copy.deepcopy(record); self.set_path(changed,path,"UNKNOWN")
            with self.subTest(path=path), self.assertRaises(IntegrityError):
                phase2_capture._issued_record_shape(changed)

    def test_null_zero_signed_and_optional_legacy_fields_remain_exact(self):
        record = self.record()
        week = record["weeks"][0]
        pick = week["top_over"]["picks"][0]
        for name in ("line","proj","adj","decision_projection","actual","name","line_from"):
            pick[name] = None
        week["ppr"].update(n=0,proj_mae=None,average_mae=0,adjusted_mae=0,proj_bias=-2)
        week["ppr"]["sums"] = {"raw_abs":0,"adjusted_abs":0,"bias":-2}
        week["matchup"]["soft"].update(n=0,vs_line=-3)
        week["matchup"]["neutral"].update(n=0,vs_line=None)
        before = copy.deepcopy(record)
        phase2_capture._issued_record_shape(record)
        self.assertEqual(record,before)
        # New fictional legacy-shape control; no historical receipt is relabelled.
        legacy = {"cumulative":{"weeks":0,"top_over":{"n":0,"pct":None}},"weeks":[]}
        phase2_capture._issued_record_shape(legacy)
        pick = {key:value for key,value in pick.items() if key in
                {"player_id","game_id","key","line","actual","result"}}
        legacy["cumulative"]["top_over"]["picks"] = [pick]
        phase2_capture._issued_record_shape(legacy)

    def test_unknown_fields_structures_and_negative_error_metrics_rejected(self):
        record = self.record()
        for path in [(),("cumulative",),("weeks",0),("weeks",0,"top_over"),
                     ("weeks",0,"top_over","picks",0),("weeks",0,"leans","by_category"),
                     ("weeks",0,"by_venue"),("weeks",0,"dk_leans"),("weeks",0,"games"),
                     ("weeks",0,"ppr"),("weeks",0,"ppr","sums"),
                     ("weeks",0,"matchup"),("weeks",0,"matchup","soft")]:
            changed = copy.deepcopy(record); target = changed
            for component in path:
                target = target[component]
            target["unregistered_private_note"] = "FICTIONAL_BOUNDARY_CANARY"
            with self.subTest(path=path), self.assertRaises(IntegrityError):
                phase2_capture._issued_record_shape(changed)
        for path in [("weeks",),("weeks",0,"top_over","picks")]:
            changed = copy.deepcopy(record); self.set_path(changed,path,{})
            with self.subTest(path=path), self.assertRaises(IntegrityError):
                phase2_capture._issued_record_shape(changed)
        for path in [("weeks",0,"ppr","proj_mae"),("weeks",0,"ppr","sums","raw_abs"),
                     ("weeks",0,"matchup","soft","n"),("weeks",0,"top_over","hit")]:
            changed = copy.deepcopy(record); self.set_path(changed,path,-1)
            with self.subTest(path=path), self.assertRaises(IntegrityError):
                phase2_capture._issued_record_shape(changed)

    def test_actual_staging_rejects_self_hashed_nested_scalar_canaries(self):
        for bad_path in (None,("weeks",0,"top_over","picks",0,"line"),
                         ("weeks",0,"ppr","sums","raw_abs")):
            record = self.record()
            if bad_path:
                self.set_path(record,bad_path,{"raw_provider_records":["FICTIONAL_BOUNDARY_CANARY"]})
            raw = json.dumps(record,separators=(",",":"),allow_nan=False).encode()
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory); output = root / "output"
                path = output / "data/grading-history" / (hashlib.sha256(raw).hexdigest()+".json")
                path.parent.mkdir(parents=True); path.write_bytes(raw)
                destination = root / "pages"
                if bad_path:
                    with self.subTest(path=bad_path), self.assertRaises(IntegrityError):
                        phase2_capture.stage_pages(root,destination)
                else:
                    phase2_capture.stage_pages(root,destination)
                    self.assertEqual((destination / path.relative_to(output)).read_bytes(),raw)
                self.assertEqual(path.read_bytes(),raw)


if __name__ == "__main__":
    unittest.main()
