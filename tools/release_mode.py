"""Select the normal or recovery path without editing workflow definitions."""
import json
from pathlib import Path


def read_mode(root):
    value = json.loads((Path(root) / "config/release-mode.json").read_text())
    if not isinstance(value, dict) or value.get("mode") not in ("phase1", "original"):
        raise ValueError("Unknown release mode; refusing publication")
    return value["mode"]


if __name__ == "__main__":
    print("mode=" + read_mode(Path(__file__).resolve().parents[1]))
