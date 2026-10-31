"""Actual report identity, source closure and production UI integration checks."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
ROOT = Path(__file__).resolve().parents[1]
REPORT_SHA = "b3707ebca913bbe467be73bd3f532bf7700345a09d0c47e4cd7e41649a9b6819"
class OriginalSideRecord(unittest.TestCase):
    def test_renderer_controls(self):
        subprocess.run(["node", str(ROOT / "tests/test-original-side-record.cjs")], check=True, timeout=30, cwd=ROOT)
    def test_report_identity_and_retained_source_blobs(self):
        raw = (ROOT / "output/data/original_recorded_leans_report.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), REPORT_SHA)
        report = json.loads(raw)
        for binding in report["source"]["source_manifest"]:
            actual = subprocess.check_output(["git", "cat-file", "blob", report["source"]["snapshot_commit"] + ":" + binding["path"]], cwd=ROOT)
            self.assertEqual(len(actual), binding["bytes"])
            self.assertEqual(hashlib.sha1(b"blob " + str(len(actual)).encode() + b"\0" + actual).hexdigest(), binding["git_blob_sha"])
        self.assertEqual(report["scored_opportunities"]["original_lean_decided"], 1376)
        for view, rows in report["tables"].items():
            for row in rows:
                for side in ["over", "under"]:
                    value = row[side]
                    self.assertEqual(value["decided"], value["hit"] + value["miss"])
                    self.assertEqual(value["hit_rate"], value["hit"] / value["decided"] if value["decided"] else None)
    def test_consumer_checks_are_executed_without_legacy_record(self):
        source = (ROOT / "output/app.js").read_text()
        self.assertIn('Nothing graded yet.</div>`;\n    mountOriginalSideRecord();\n    return;', source)
        self.assertIn('  mountOriginalSideRecord();\n}\n\n// ---------------------------------------------------------------- how it works tab', source)
        self.assertIn('Earlier recorded forecasts', source)
        self.assertNotIn('"Classic track record" : "R0 track record"', source)
