"""Select the normal or recovery path without editing workflow definitions."""
import json
from pathlib import Path


def read_mode(root):
    value = json.loads((Path(root) / "config/release-mode.json").read_text())
    if not isinstance(value, dict) or value.get("mode") not in ("phase1", "original"):
        raise ValueError("Unknown release mode; refusing publication")
    return value["mode"]


def read_phase2(root):
    path = Path(root) / "config/phase2.json"
    if not path.exists():
        return False
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or type(value.get("capture_enabled")) is not bool or
            value.get("production_model") != "original_sleeper_matchup_baseline" or
            value.get("challenger_production_enabled") is not False):
        raise ValueError("Invalid Phase 2 mode or attempted production-model switch")
    return value["capture_enabled"]


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    mode = read_mode(root)
    print("mode=" + mode)
    print("phase2_enabled=" + str(mode == "phase1" and read_phase2(root)).lower())
