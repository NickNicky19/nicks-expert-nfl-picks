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
            value.get("challenger_production_enabled") is not False):
        raise ValueError("Invalid Phase 2 mode or attempted production-model switch")
    model = value.get("production_model")
    if model == "original_sleeper_matchup_baseline":
        if value.get("verification_mode") == "partial-week-data-integrity-v2":
            raise ValueError("Original model cannot use the corrected verification contract")
        # Preserve the existing original-model interface without loading new code.
        return value["capture_enabled"]
    if model == "sleeper-matchup-classic-fg-identity-v1":
        if (value["capture_enabled"] is not False or value.get("experimental_recording_enabled") is not False
                or value.get("verification_mode") is not None):
            raise ValueError("Legacy Classic has no qualified Phase 2 verification route")
        return False
    if (model not in ("sleeper-matchup-data-integrity-v2", "sleeper-matchup-classic-data-integrity-v2")
            or value.get("verification_mode") != "partial-week-data-integrity-v2"
            or value.get("experimental_recording_enabled") is not False):
        raise ValueError("Invalid Phase 2 mode or attempted production-model switch")
    # Recognition is not qualification. The capture entrypoint still validates
    # actual closed source, fixed plan, original inputs and final completion.
    return value["capture_enabled"]


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    mode = read_mode(root)
    print("mode=" + mode)
    print("phase2_enabled=" + str(mode == "phase1" and read_phase2(root)).lower())
