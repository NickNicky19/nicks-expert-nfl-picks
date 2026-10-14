"""Restore the verified working Phase 1 code without resetting history or evidence."""
import argparse
import json
from pathlib import Path

from restore_original import git, restore

BASELINE = "3149663447b29f95f06c7259b84da3bd4a21cab0"
BACKUP_REF = "backup/pre-phase2-20261014-3149663447b2"
PHASE1_FILES = {
    "output/app.js": "b060a9d0737d5505fecd3df65a5b40402cddf2e0",
    "output/index.html": "877dfd0011b036105852ed7b3b67986d62ef8230",
    "pull/grade.py": "67c7284ed84f69296158e9acfc05b5a0e0c9c300",
    "tools/verify.py": "9f510735c2401de1d19fb56718d147e8f1c5ff8d",
    "config/release-mode.json": "aff6c07f76b7eabcb2299a74a9c595138a878ccf",
}


def restore_phase1_mode(root, source=BASELINE, expected=None):
    root = Path(root)
    config = root / "config/phase2.json"
    if config.is_symlink() or config.parent.is_symlink():
        raise RuntimeError("Refusing symlink Phase 2 mode path")
    backup = restore(root, source, PHASE1_FILES if expected is None else expected)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"capture_enabled": False, "production_model": "original_sleeper_matchup_baseline",
                                  "challenger_production_enabled": False}) + "\n")
    git(root, "add", "--", "config/phase2.json")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", required=True, choices=["RESTORE_PHASE1"])
    parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if git(root, "branch", "--show-current").decode().strip() != "main":
        parser.error("Use a clean main checkout for production recovery")
    print("Pre-restore backup:", restore_phase1_mode(root))
    print("Phase 1 code staged; all evidence retained. Push the backup before committing/publishing recovery.")


if __name__ == "__main__":
    main()
