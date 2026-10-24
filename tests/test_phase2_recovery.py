from pathlib import Path
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
