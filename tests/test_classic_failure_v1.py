import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import classic_failure_v1 as failure
import publication_guard_v1 as guard


class FailedAttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / "repo"; self.root.mkdir()
        self.run = self.base / "private-pair"; self.run.mkdir()
        self.env = dict(GITHUB_ACTIONS="true", GITHUB_REPOSITORY=guard.REPOSITORY,
                        GITHUB_REF="refs/heads/main", GITHUB_EVENT_NAME="workflow_dispatch",
                        GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1", GITHUB_SHA="a" * 40,
                        GITHUB_WORKFLOW_SHA="a" * 40, PAIR_OUTCOME="failure")
        self.fence = self.base / "fence.json"
        guard.create(self.fence, dict(schema_version=guard.VERSION + "-begin", **guard.context(self.root, self.env)))
        (self.root / "output/data").mkdir(parents=True)
        (self.root / "output/data/week.json").write_bytes(b"previous published board")

    def board(self):
        path = self.run / "original/output/data/week.json"; path.parent.mkdir(parents=True)
        raw = b'{"season":2026,"week":7,"players":[],"games":[]}'
        path.write_bytes(raw); return path, raw

    def native(self):
        path = self.run / ("original/data/forward/2026/w07/" + "b" * 64 + ".json.gz")
        path.parent.mkdir(parents=True)
        payload = dict(model="original_sleeper_matchup_baseline", captured_at="2026-10-25T03:00:00Z",
                       rows=[dict(name="Andr\u00e9", adjusted_projection=1.25)])
        expected = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        raw = gzip.compress(json.dumps(dict(payload=payload, payload_sha256=hashlib.sha256(expected).hexdigest()),
                                       ensure_ascii=False).encode(), mtime=0)
        path.write_bytes(raw); return path, raw

    def record(self):
        return failure.record(self.root, self.run, self.fence, self.env)

    def test_partial_capture_without_worker_survives_exactly_and_never_installs(self):
        board, raw = self.board(); native, compressed = self.native()
        corpus = self.run / "inputs/raw-provider-response.json"; corpus.parent.mkdir(); corpus.write_bytes(b"PRIVATE RAW")
        result = self.record(); target = self.root / "data/classic-failures/123-1"
        self.assertEqual((target / "original/output/data/week.json").read_bytes(), raw)
        self.assertEqual((target / native.relative_to(self.run)).read_bytes(), compressed)
        self.assertFalse(result["successful_forecast"]); self.assertFalse(result["failure_record_publishes_forecasts"])
        self.assertFalse(result["raw_provider_corpus_copied"])
        self.assertEqual((self.root / "output/data/week.json").read_bytes(), b"previous published board")
        self.assertFalse(any(b"PRIVATE RAW" in p.read_bytes() for p in target.rglob("*") if p.is_file()))

    def test_duplicate_in_fresh_process_preserves_first_receipt_and_all_bytes(self):
        self.board(); self.native(); first = self.record()
        target = self.root / "data/classic-failures/123-1/FAILED.json"; raw = target.read_bytes()
        script = "import json,sys;sys.path.insert(0,sys.argv[1]);import classic_failure_v1 as f;f.record(*sys.argv[2:5],json.loads(sys.argv[5]))"
        subprocess.run([sys.executable, "-c", script, str(Path(failure.__file__).parent), str(self.root), str(self.run),
                        str(self.fence), json.dumps(self.env)], check=True)
        self.assertEqual(target.read_bytes(), raw); self.assertEqual(self.record(), first)

    def test_interrupt_before_manifest_keeps_originals_and_exact_recovery(self):
        path, raw = self.board(); actual = failure.immutable
        def interrupted(destination, body):
            if destination.name == "FAILED.json": raise OSError("controlled interruption")
            return actual(destination, body)
        with patch.object(failure, "immutable", side_effect=interrupted):
            with self.assertRaises(OSError): self.record()
        self.assertEqual(path.read_bytes(), raw)
        self.assertFalse((self.root / "data/classic-failures/123-1/FAILED.json").exists())
        self.assertEqual(self.record()["state"], "FAILED_ATTEMPT_RETAINED")

    def test_invalid_forecast_is_reported_with_original_hash_and_not_copied(self):
        path, _ = self.board(); path.write_bytes(b'{"season":')
        result = self.record(); row = result["files"][0]
        self.assertEqual(row["status"], "INVALID_DERIVED_BYTES_NOT_COPIED")
        self.assertEqual(row["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertNotIn("saved_path", row); self.assertEqual(result["retained_bytes"], 0)

    def test_missing_fence_and_nonfailure_never_create_failure_success(self):
        self.fence.unlink()
        with self.assertRaises((ValueError, FileNotFoundError)): self.record()
        self.assertFalse((self.root / "data").exists())
        guard.create(self.fence, dict(schema_version=guard.VERSION + "-begin", **guard.context(self.root, self.env)))
        self.env["PAIR_OUTCOME"] = "success"
        with self.assertRaisesRegex(ValueError, "ACTUAL_FAILED_STEP"): self.record()
        self.assertFalse((self.root / "data").exists())

    def test_changed_original_identity_or_saved_evidence_is_rejected(self):
        self.board(); self.record()
        saved = self.root / "data/classic-failures/123-1/original/output/data/week.json"; saved.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "RETAINED_FAILURE_BYTES"): self.record()


if __name__ == "__main__":
    unittest.main()
