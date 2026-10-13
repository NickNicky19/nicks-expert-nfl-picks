"""Offline Git recovery tests; no remote writes or network calls."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from restore_original import blob_hash, git, restore, restore_original_mode
from release_mode import read_mode


def repository(path):
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "user.name", "Recovery test")
    (path / "code.txt").write_bytes(b"original\n")
    (path / "evidence.txt").write_bytes(b"old evidence\n")
    git(path, "add", "code.txt", "evidence.txt")
    git(path, "commit", "-m", "Fictional baseline")
    source = git(path, "rev-parse", "HEAD").decode().strip()
    (path / "code.txt").write_bytes(b"upgraded\n")
    (path / "evidence.txt").write_bytes(b"new evidence retained\n")
    git(path, "add", "code.txt", "evidence.txt")
    git(path, "commit", "-m", "Fictional upgrade")
    return source


class RecoveryTests(unittest.TestCase):
    def test_restore_preserves_data_and_history(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = repository(root)
            before = git(root, "rev-parse", "HEAD").decode().strip()
            backup = restore(root, source, {"code.txt": blob_hash(b"original\n")})
            self.assertEqual((root / "code.txt").read_bytes(), b"original\n")
            self.assertEqual((root / "evidence.txt").read_bytes(), b"new evidence retained\n")
            self.assertEqual(git(root, "rev-parse", "HEAD").decode().strip(), before)
            self.assertEqual(git(root, "rev-parse", backup).decode().strip(), before)
            self.assertEqual(git(root, "diff", "--cached", "--name-only").decode().strip(), "code.txt")
            refs = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/backup/pre-restore-*").decode()
            self.assertIn(backup, refs)

    def test_actions_recovery_does_not_modify_workflows(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = repository(root)
            (root / ".github/workflows").mkdir(parents=True)
            workflow = root / ".github/workflows/hourly.yml"
            workflow.write_text("retained recovery-aware runner\n")
            git(root, "add", ".github"); git(root, "commit", "-m", "Fixture workflow")
            restore_original_mode(root, source, {"code.txt": blob_hash(b"original\n"), ".github/workflows/hourly.yml": "unused"})
            self.assertEqual(workflow.read_text(), "retained recovery-aware runner\n")
            self.assertEqual(read_mode(root), "original")
            self.assertEqual((root / "evidence.txt").read_text(), "new evidence retained\n")
            self.assertNotIn(".github", git(root, "diff", "--cached", "--name-only").decode())

    def test_original_mode_refuses_dirty_tree(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = repository(root)
            (root / "unsaved.txt").write_text("keep")
            with self.assertRaises(RuntimeError): restore_original_mode(root, source, {"code.txt": blob_hash(b"original\n")})
            self.assertFalse((root / "config/release-mode.json").exists())

    def test_release_mode_whitelist(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "config").mkdir()
            (root / "config/release-mode.json").write_text('{"mode":"phase1"}')
            self.assertEqual(read_mode(root), "phase1")
            (root / "config/release-mode.json").write_text('{"mode":"original"}')
            self.assertEqual(read_mode(root), "original")

    def test_unknown_release_mode_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "config").mkdir()
            (root / "config/release-mode.json").write_text('{"mode":"unsafe"}')
            with self.assertRaises(ValueError): read_mode(root)

    def test_dirty_tree_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = repository(root)
            (root / "code.txt").write_bytes(b"uncommitted work\n")
            with self.assertRaises(RuntimeError): restore(root, source, {"code.txt": blob_hash(b"original\n")})
            self.assertEqual((root / "code.txt").read_bytes(), b"uncommitted work\n")

    def test_untracked_file_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = repository(root)
            (root / "unsaved.txt").write_text("preserve me")
            with self.assertRaises(RuntimeError): restore(root, source, {"code.txt": blob_hash(b"original\n")})

    def test_wrong_baseline_hash_refused_before_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = repository(root)
            with self.assertRaises(RuntimeError): restore(root, source, {"code.txt": "0" * 40})
            self.assertEqual((root / "code.txt").read_bytes(), b"upgraded\n")
            self.assertEqual(git(root, "status", "--porcelain").strip(), b"")


if __name__ == "__main__": unittest.main()
