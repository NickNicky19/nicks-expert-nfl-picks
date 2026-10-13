"""Create-only preservation of the pre-v2 grading output before the first new build."""
from pathlib import Path
from datetime import datetime, timezone
import gzip
import json
import sys

from reliability import digest, immutable_write, load_json, stamp

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "data/history/pre_phase1_track_record.json.gz"
if path.exists():
    envelope = json.loads(gzip.decompress(path.read_bytes()))
    if envelope.get("payload_sha256") != digest(envelope.get("payload")):
        raise SystemExit("Legacy backup checksum mismatch")
    print("Existing pre-upgrade grading record retained unchanged.")
else:
    record = load_json(ROOT / "output/data/track_record.json")
    if record.get("grading_version"):
        raise SystemExit("No legacy backup exists, but grading is already versioned; investigate rather than relabel it")
    payload = {"label": "LEGACY_GRADING_OUTPUT_NOT_NEW_PROSPECTIVE_EVIDENCE",
               "captured_at": stamp(datetime.now(timezone.utc)), "record": record}
    immutable_write(path, payload)
    print("Pre-upgrade grading output preserved; source forecasts were not modified.")
