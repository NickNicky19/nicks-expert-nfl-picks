from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from release_mode import read_phase2
from restore_phase1 import restore_phase1_mode
from restore_original import blob_hash, git
from test_recovery import repository


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


if __name__ == "__main__":
    unittest.main()
