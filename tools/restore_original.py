"""Restore allowlisted original files. Preserve data and Git history.

Run on a clean main checkout after fetching the repository. Never force-push.
This command does not commit, push, deploy, or remove newly collected evidence.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

BASELINE = "6c33224b90d32ac2e005fff140662f114f97eb14"
ORIGINAL_FILES = {
    "pull/grade.py": "c8417c224fb1f395db911c69102c37a2bcad94aa",
    ".github/workflows/hourly.yml": "99ba2148941b9560599dd273a0a7e40b3bb6bd28",
    "output/app.js": "34d2769db20f2ff5c86d232ddfc046c092033234",
    "output/index.html": "08fc1cea83a942bef91ed86e472306c25111f624",
    "tools/verify.py": "9f510735c2401de1d19fb56718d147e8f1c5ff8d",
}


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.STDOUT)


def blob_hash(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def restore(root: Path, source: str = BASELINE, expected: dict | None = None) -> str:
    expected = ORIGINAL_FILES if expected is None else expected
    if git(root, "status", "--porcelain").strip():
        raise RuntimeError("Uncommitted or untracked changes exist; refusing to overwrite them")
    source_commit = git(root, "rev-parse", "--verify", source + "^{commit}").decode().strip()
    # Read and verify all content before any mutation.
    for path, sha in expected.items():
        content = git(root, "show", source_commit + ":" + path)
        if blob_hash(content) != sha:
            raise RuntimeError(f"Baseline content mismatch: {path}")
        local = root / path
        if local.is_symlink():
            raise RuntimeError(f"Refusing symlink: {path}")
    saved_head = git(root, "rev-parse", "HEAD").decode().strip()
    backup = "backup/pre-restore-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    git(root, "branch", backup, saved_head)
    git(root, "restore", "--source", source_commit, "--staged", "--worktree", "--", *expected)
    return backup


def restore_original_mode(root: Path, source: str = BASELINE, expected: dict | None = None) -> str:
    """Actions-safe recovery: restore app/grader, retain workflow files, select original mode."""
    originals = ORIGINAL_FILES if expected is None else expected
    code = {k: v for k, v in originals.items() if not k.startswith(".github/workflows/")}
    config = root / "config/release-mode.json"
    if config.is_symlink() or config.parent.is_symlink():
        raise RuntimeError("Refusing symlink release-mode path")
    backup = restore(root, source, code)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"mode": "original", "restored_from": source}) + "\n")
    git(root, "add", "--", "config/release-mode.json")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", required=True, choices=["RESTORE_ORIGINAL"])
    parser.add_argument("--application-only", action="store_true", help="Retain the workflow runner and select its original-code mode (for GitHub Actions)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if git(root, "branch", "--show-current").decode().strip() != "main":
        parser.error("Use a clean main checkout for the production recovery command")
    backup = restore_original_mode(root) if args.application_only else restore(root)
    print(f"Original code restored to working tree/index. Previous HEAD saved at {backup}.")
    print("All data, captures, archives, and other files are retained. Commit/review before publishing.")


if __name__ == "__main__":
    main()
