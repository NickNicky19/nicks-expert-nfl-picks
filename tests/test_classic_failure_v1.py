"""Actual capture bytes, filesystem/process regressions, no provider calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import errno
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / name) for name in ("tools", "pull", "tests")]
import classic_failure_v1 as failure
import classic_model_v1 as model
import publication_guard_v1 as guard
import reliability
from test_reliability import fixture


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
        self.target = self.root / "data/classic-failures/123-1"

    def board(self):
        path = self.run / "original/output/data/week.json"; path.parent.mkdir(parents=True, exist_ok=True)
        raw = b'{"season":2026,"week":7,"players":[],"games":[]}'
        path.write_bytes(raw); return path, raw

    def native(self, stage="original", rows=1, tag="fixture", sleeper=False):
        data, meta = fixture(); now = datetime.now(timezone.utc)
        data.update(season=2026, week=7, generated_at=reliability.stamp(now - timedelta(minutes=1)))
        data["games"][0]["kickoff"] = reliability.stamp(now + timedelta(days=1))
        template = data["players"][0]
        data["players"] = []
        for i in range(rows):
            player = deepcopy(template)
            player.update(id=f"fictional-{tag}-{i:05d}", name=f"André Fictional {tag} {i}", injury="Questionable")
            if sleeper:
                player["props"][0]["sleeper"] = dict(line=4.5, over=1.5, under=None)
            data["players"].append(player)
        data["picks"] = dict(over=[], under=[])
        meta = {k: data[k] for k in ("season", "week", "generated_at")}
        base = self.run / stage
        if stage == "original":
            with patch.dict(os.environ, GITHUB_SHA=model.ORIGINAL_SOURCE):
                path, _ = reliability.capture(data, meta, base, now, failure.ORIGINAL_ENGINE, mode="live")
        else:
            for name in model.ENGINE:
                path = base / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes((ROOT / name).read_bytes())
            data["execution_model"] = meta["execution_model"] = model.contract(base)
            for player in data["players"]:
                player["reference_model"] = model.MODEL
            with patch.dict(os.environ, GITHUB_SHA=self.env["GITHUB_SHA"]):
                path, _ = reliability.capture_profile(data, meta, base, now, model=model.MODEL, mode="live")
        return path, path.read_bytes()

    def record(self):
        return failure.record(self.root, self.run, self.fence, self.env)

    def row(self, result, source=None, stage="original", kind=None):
        return next(r for r in result["files"] if r["stage"] == stage and (source is None or r["source"] == source)
                    and (kind is None or r["kind"] == kind))

    def rewrite_native(self, path, value):
        path.write_bytes(gzip.compress(failure.canonical(dict(payload=value, payload_sha256=failure.sha(failure.canonical(value)))), mtime=0))

    def reset(self):
        shutil.rmtree(self.target, ignore_errors=True)
        for stage in failure.STAGE_NAMES:
            shutil.rmtree(self.run / stage, ignore_errors=True)

    def test_partial_capture_without_worker_survives_exactly_and_never_installs(self):
        board, raw = self.board(); native, compressed = self.native(rows=240, sleeper=True)
        corpus = self.run / "inputs/raw-provider-response.json"; corpus.parent.mkdir(); corpus.write_bytes(b"PRIVATE RAW")
        result = self.record(); row = self.row(result, kind="NATIVE")
        self.assertEqual((self.target / native.relative_to(self.run)).read_bytes(), compressed)
        self.assertEqual(row["native_rows"], 240)
        self.assertEqual(result["retained_forecast_rows"], 240)
        self.assertEqual(self.row(result, "output/data/week.json")["sha256"], failure.sha(raw))
        self.assertFalse((self.target / "original/output/data/week.json").exists())
        self.assertFalse(result["successful_forecast"]); self.assertFalse(result["failure_record_publishes_forecasts"])
        self.assertFalse(result["raw_provider_corpus_copied"])
        self.assertEqual((self.root / "output/data/week.json").read_bytes(), b"previous published board")
        self.assertEqual(board.read_bytes(), raw)
        self.assertFalse(any(b"PRIVATE RAW" in p.read_bytes() for p in self.target.rglob("*") if p.is_file()))
        self.assertTrue(failure.verify_retained(self.target)["native_retention_complete"])

    def test_both_actual_native_profiles_and_all_rows_retained(self):
        originals = [self.native(rows=3), self.native("current", rows=5, sleeper=True)]
        result = self.record()
        self.assertEqual(result["retained_forecast_rows"], 8)
        for path, raw in originals:
            self.assertEqual((self.target / path.relative_to(self.run)).read_bytes(), raw)
        summary = failure.verify_retained(self.target)
        self.assertEqual(summary["files"], 3)
        self.assertEqual(summary["retained_forecast_rows"], 8)
        self.assertFalse(summary["source_context_verified_externally"])

    def test_unicode_wrong_hash_rejected_with_original_byte_hash(self):
        path, _ = self.native(); envelope = json.loads(gzip.decompress(path.read_bytes()))
        envelope["payload_sha256"] = hashlib.sha256(json.dumps(envelope["payload"], sort_keys=True,
                                                               separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        path.write_bytes(gzip.compress(failure.canonical(envelope), mtime=0))
        row = self.row(self.record(), kind="NATIVE")
        self.assertEqual(row["status"], "INVALID_DERIVED_BYTES_NOT_COPIED")
        self.assertEqual(row["sha256"], failure.sha(path.read_bytes()))
        self.assertIsNone(row["saved_path"])

    def test_list_null_and_malformed_native_payloads_never_suppress_manifest(self):
        for value in ([], None, "bad", {}, {"model": model.ORIGINAL_MODEL}):
            with self.subTest(value=value):
                self.reset(); self.board(); path, _ = self.native(); self.rewrite_native(path, value)
                result = self.record(); row = self.row(result, kind="NATIVE")
                self.assertEqual(row["status"], "INVALID_DERIVED_BYTES_NOT_COPIED")
                self.assertEqual(row["sha256"], failure.sha(path.read_bytes()))
                self.assertTrue((self.target / "FAILED.json").is_file())

    def test_deflate_truncated_and_trailing_native_rejected_without_losing_attempt(self):
        for kind in ("deflate", "truncated", "trailing", "header"):
            with self.subTest(kind=kind):
                self.reset(); path, raw = self.native()
                if kind == "deflate": raw = bytes.fromhex("1f8b0800000000000003") + b"\xff" * 16
                elif kind == "truncated": raw = raw[:-5]
                elif kind == "trailing": raw += gzip.compress(b"", mtime=0)
                else: raw = raw[:3] + b"\x08" + raw[4:10] + b"PRIVATE HEADER\0" + raw[10:]
                path.write_bytes(raw)
                row = self.row(self.record(), kind="NATIVE")
                self.assertEqual(row["status"], "INVALID_DERIVED_BYTES_NOT_COPIED")
                self.assertEqual(row["sha256"], failure.sha(raw))
                self.assertTrue((self.target / "FAILED.json").exists())

    def test_bad_worker_never_suppresses_independent_native_scan(self):
        for value in ([], None, {"native_receipt": "../../private.json"}, {"native_receipt": []}):
            with self.subTest(value=value):
                self.reset(); path, raw = self.native()
                worker = self.run / "original/WORKER.json"; worker.write_text(json.dumps(value))
                result = self.record()
                self.assertEqual(self.row(result, "WORKER.json")["status"], "INVALID_CONTROL_NOT_COPIED")
                self.assertEqual((self.target / path.relative_to(self.run)).read_bytes(), raw)
                self.assertEqual(result["retained_forecast_rows"], 1)

    def test_raw_board_and_unknown_native_fields_are_metadata_only(self):
        for where in ("payload", "row", "book"):
            with self.subTest(where=where):
                self.reset(); board, _ = self.board(); b = json.loads(board.read_bytes())
                b["raw_provider_corpus"] = "PRIVATE_CANARY"; board.write_bytes(failure.canonical(b))
                path, _ = self.native(sleeper=True); p = json.loads(gzip.decompress(path.read_bytes()))["payload"]
                obj = p if where == "payload" else p["rows"][0] if where == "row" else p["rows"][0]["sleeper_observation"]
                obj["raw_provider_corpus"] = "PRIVATE_CANARY"; self.rewrite_native(path, p)
                result = self.record()
                self.assertEqual(self.row(result, "output/data/week.json")["status"], "UNISSUED_METADATA_ONLY")
                self.assertEqual(self.row(result, kind="NATIVE")["status"], "INVALID_DERIVED_BYTES_NOT_COPIED")
                self.assertEqual(result["retained_bytes"], 0)
                self.assertFalse(any(b"PRIVATE_CANARY" in f.read_bytes() for f in self.target.rglob("*") if f.is_file()))

    def test_typed_last_row_rejection_does_not_publish_a_truncated_prefix(self):
        path, raw = self.native(rows=240); p = json.loads(gzip.decompress(raw))["payload"]
        p["rows"][-1]["adjusted_projection"] = {"raw": "PRIVATE_CANARY"}; self.rewrite_native(path, p)
        result = self.record(); row = self.row(result, kind="NATIVE")
        self.assertEqual(row["status"], "INVALID_DERIVED_BYTES_NOT_COPIED")
        self.assertEqual(result["retained_forecast_rows"], 0)
        self.assertEqual(row["sha256"], failure.sha(path.read_bytes()))
        self.assertFalse((self.target / path.relative_to(self.run)).exists())

    def test_native_profile_clock_period_and_numeric_types_are_closed(self):
        changes = [lambda p: p.update(model="unknown"), lambda p: p.update(code_commit="f" * 40),
                   lambda p: p.update(mode="replay"), lambda p: p["engine_files"].update({"pull/build.py": "f" * 64}),
                   lambda p: p["rows"][0].update(week=8), lambda p: p["rows"][0].update(raw_projection=True),
                   lambda p: p["rows"][0].update(price=1.5), lambda p: p["rows"][0].update(source_timestamps_verified=True),
                   lambda p: p.update(captured_at=reliability.stamp(datetime.now(timezone.utc) + timedelta(days=1)))]
        for change in changes:
            with self.subTest(change=change):
                self.reset(); path, raw = self.native(); payload = json.loads(gzip.decompress(raw))["payload"]
                change(payload); self.rewrite_native(path, payload)
                row = self.row(self.record(), kind="NATIVE")
                self.assertEqual(row["status"], "INVALID_DERIVED_BYTES_NOT_COPIED")
                self.assertEqual(row["sha256"], failure.sha(path.read_bytes()))
                self.assertFalse((self.target / path.relative_to(self.run)).exists())
        self.reset(); path, raw = self.native(); value = json.loads(gzip.decompress(raw))
        value["payload"]["rows"][0]["name"] = "\ud800"
        path.write_bytes(gzip.compress(json.dumps(value, ensure_ascii=True).encode(), mtime=0))
        self.assertEqual(self.row(self.record(), kind="NATIVE")["status"], "INVALID_DERIVED_BYTES_NOT_COPIED")

    def test_seed_board_and_changed_board_origins_are_explicit(self):
        path, raw = self.board()
        (self.run / "SEEDS.json").write_bytes(failure.canonical(dict(original={"output/data/week.json": failure.sha(raw)}, current={})))
        first = self.record(); row = self.row(first, "output/data/week.json")
        self.assertEqual((row["status"], row["origin"]), ("SEED_CONTEXT_METADATA_ONLY", "SEEDED_UNCHANGED"))
        self.assertEqual(first["retained_forecast_rows"], 0)
        shutil.rmtree(self.target)
        changed = json.loads(raw); changed["generated_at"] = "2026-01-01T00:00:00Z"; path.write_bytes(failure.canonical(changed))
        row = self.row(self.record(), "output/data/week.json")
        self.assertEqual((row["status"], row["origin"]), ("UNISSUED_METADATA_ONLY", "CHANGED_SINCE_SEED"))
        self.assertIsNone(row["saved_path"])

    def test_aggregate_budget_exclusion_does_not_poison_later_small_capture(self):
        small, a = self.native(tag="small")
        large, b = self.native(rows=1000, tag="large")
        later, c = self.native("current", tag="later")
        self.assertGreater(len(b), len(a) + len(c))
        with patch.object(failure, "MAX_TOTAL", len(a) + len(c)):
            result = self.record()
        by_source = {r["source"]: r for r in result["files"]}
        row = by_source[large.relative_to(self.run / "original").as_posix()]
        self.assertEqual(row["status"], "CAPACITY_NOT_RETAINED")
        self.assertEqual(row["native_rows"], 1000)
        self.assertEqual(row["sha256"], failure.sha(b))
        self.assertEqual(result["retained_forecast_rows"], 2)
        self.assertEqual(result["retained_bytes"], len(a) + len(c))
        for path, raw in [(small, a), (later, c)]: self.assertEqual((self.target / path.relative_to(self.run)).read_bytes(), raw)
        self.assertFalse(failure.verify_retained(self.target)["native_retention_complete"])

    def test_native_cardinality_bound_retains_attempt_and_explicit_incompleteness(self):
        for i in range(failure.MAX_NATIVE_FILES + 1): self.native(tag=f"capture{i}")
        result = self.record(); summary = result["collection"]["original"]
        self.assertEqual(summary["status"], "FILE_LIMIT_NOT_COMPLETE")
        self.assertEqual(summary["queued_native_files"], failure.MAX_NATIVE_FILES)
        self.assertEqual(summary["observed_native_files"], failure.MAX_NATIVE_FILES + 1)
        self.assertEqual(result["retained_forecast_rows"], failure.MAX_NATIVE_FILES)
        self.assertFalse(failure.verify_retained(self.target)["collection_complete"])

    def test_unqualified_native_filename_is_hashed_not_published(self):
        path = self.run / "original/data/forward/PRIVATE_FILENAME.json.gz"; path.parent.mkdir(parents=True)
        path.write_bytes(b"PRIVATE_CONTENT")
        row = self.row(self.record(), kind="NATIVE")
        self.assertTrue(row["source"].startswith("unqualified:"))
        self.assertEqual(row["status"], "UNQUALIFIED_PATH_METADATA_ONLY")
        self.assertEqual(row["sha256"], failure.sha(path.read_bytes()))
        raw = (self.target / "FAILED.json").read_bytes()
        self.assertNotIn(b"PRIVATE_FILENAME", raw); self.assertNotIn(b"PRIVATE_CONTENT", raw)

    def test_per_file_and_enumeration_limits_are_explicit_without_suppressing_manifest(self):
        path, _ = self.board(); path.write_bytes(b" " * (failure.MAX_FILE + 1))
        lane = self.run / "original/data/forward"; lane.mkdir(parents=True)
        for i in range(failure.MAX_SCAN_ENTRIES + 1): (lane / str(i)).mkdir()
        result = self.record(); row = self.row(result, "output/data/week.json")
        self.assertEqual(row["status"], "FILE_SIZE_LIMIT_NOT_COPIED")
        self.assertEqual(row["bytes"], failure.MAX_FILE + 1)
        self.assertIsNone(row["sha256"])
        self.assertEqual(result["collection"]["original"]["status"], "ENTRY_LIMIT_NOT_COMPLETE")
        self.assertFalse(failure.verify_retained(self.target)["collection_complete"])

    def test_duplicate_in_fresh_process_preserves_first_receipt_and_all_bytes(self):
        self.board(); self.native(); first = self.record()
        manifest = self.target / "FAILED.json"; raw = manifest.read_bytes()
        script = "import json,sys;sys.path.insert(0,sys.argv[1]);import classic_failure_v1 as f;f.record(*sys.argv[2:5],json.loads(sys.argv[5]))"
        subprocess.run([sys.executable, "-B", "-c", script, str(Path(failure.__file__).parent), str(self.root), str(self.run),
                        str(self.fence), json.dumps(self.env)], check=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(manifest.read_bytes(), raw); self.assertEqual(self.record(), first)

    def test_verify_cli_in_fresh_process_is_readonly_and_returns_complete_graph(self):
        self.native("current", rows=12); self.record()
        before = {p.relative_to(self.target).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.target.rglob("*") if p.is_file()}
        isolated = self.base / "verifier"; isolated.mkdir()
        for name in ["classic_failure_v1.py", "classic_model_v1.py", "publication_guard_v1.py"]:
            shutil.copyfile(ROOT / "tools" / name, isolated / name)
        environment = dict(os.environ); environment.pop("PYTHONDONTWRITEBYTECODE", None)
        process = subprocess.run([sys.executable, str(isolated / "classic_failure_v1.py"), "--verify-retained-root", str(self.target)],
                                 check=True, capture_output=True, text=True, env=environment)
        self.assertFalse(any(isolated.rglob("__pycache__")))
        value = json.loads(process.stdout)
        self.assertEqual(value["state"], "CLOSED_RETAINED_GRAPH_VERIFIED")
        self.assertEqual(value["retained_forecast_rows"], 12)
        self.assertEqual(value["identity"]["trigger_source_sha"], self.env["GITHUB_SHA"])
        self.assertFalse(value["successful_forecast"]); self.assertFalse(value["raw_provider_corpus_copied"])
        self.assertEqual(before, {p.relative_to(self.target).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in self.target.rglob("*") if p.is_file()})
        self.assertEqual(value, failure.verify_retained(self.target))

    def test_existing_receipt_semantics_graph_and_accounting_are_closed(self):
        self.native(); self.record(); path = self.target / "FAILED.json"; original = json.loads(path.read_bytes())
        def drop_native(value): value["files"] = [r for r in value["files"] if r["kind"] != "NATIVE"]
        mutations = [lambda v: v.update(state="SUCCESS"), lambda v: v.update(successful_forecast=True),
                     lambda v: v.update(files=[]), lambda v: v.update(retained_bytes=0),
                     lambda v: v.update(retained_forecast_rows=0), lambda v: v.update(extra="PRIVATE"), drop_native,
                     lambda v: v["files"][0].update(status="RETAINED_DERIVED_FORECAST"),
                     lambda v: v["collection"]["original"].update(queued_native_files=0)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                value = deepcopy(original); mutate(value); raw = failure.canonical(value); path.write_bytes(raw)
                with self.assertRaises((ValueError, TypeError)): failure.verify_retained(self.target)
                with self.assertRaises((ValueError, TypeError)): self.record()
                self.assertEqual(path.read_bytes(), raw)
        path.write_bytes(failure.canonical(original))
        self.assertEqual(failure.verify_retained(self.target)["retained_forecast_rows"], 1)

    def test_existing_receipt_confines_paths_and_rejects_saved_symlinks(self):
        self.native(); result = self.record(); manifest = self.target / "FAILED.json"
        original = manifest.read_bytes(); outside = self.base / "outside"; outside.write_bytes(b"outside")
        for name in [str(outside), "../../outside", "original/../../outside"]:
            with self.subTest(path=name):
                value = json.loads(original); row = self.row(value, kind="NATIVE")
                row.update(saved_path=name, sha256=failure.sha(outside.read_bytes()), bytes=outside.stat().st_size)
                manifest.write_bytes(failure.canonical(value))
                with self.assertRaises(ValueError): self.record()
                with self.assertRaises(ValueError): failure.verify_retained(self.target)
        manifest.write_bytes(original); row = self.row(result, kind="NATIVE"); saved = self.target / row["saved_path"]
        saved.unlink(); saved.symlink_to(outside)
        with self.assertRaises(ValueError): failure.verify_retained(self.target)
        with self.assertRaises(ValueError): self.record()

    def test_extra_stored_file_or_removed_saved_bytes_cannot_hide_in_graph(self):
        self.native(); self.record()
        extra = self.target / "unexpected.json"; extra.write_bytes(b"PRIVATE")
        with self.assertRaisesRegex(ValueError, "STORED_GRAPH"): failure.verify_retained(self.target)
        extra.unlink()
        saved = next(p for p in self.target.rglob("*.json.gz")); saved.unlink()
        with self.assertRaisesRegex(ValueError, "RETAINED_FAILURE_BYTES"): failure.verify_retained(self.target)

    def test_manifest_symlinks_and_missing_verify_root_never_create_or_read_evidence(self):
        outside = self.base / "private.json"; outside.write_bytes(b"PRIVATE")
        self.target.mkdir(parents=True); (self.target / "FAILED.json").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "SYMLINK_OR_ESCAPE"): self.record()
        with self.assertRaisesRegex(ValueError, "SYMLINK_OR_ESCAPE"): failure.verify_retained(self.target)
        missing = self.base / "missing"
        with self.assertRaises(ValueError): failure.verify_retained(missing)
        self.assertFalse(missing.exists())
        self.assertEqual(outside.read_bytes(), b"PRIVATE")

    def test_changed_original_identity_or_saved_evidence_is_rejected(self):
        self.native(); self.record(); saved = next(self.target.rglob("*.json.gz")); saved.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "RETAINED_FAILURE_BYTES"): self.record()

    def test_interrupt_before_manifest_keeps_originals_and_exact_recovery(self):
        source, raw = self.native(); actual = failure.immutable
        def interrupted(destination, body):
            if destination.name == "FAILED.json": raise OSError("controlled interruption")
            return actual(destination, body)
        with patch.object(failure, "immutable", side_effect=interrupted):
            with self.assertRaises(OSError): self.record()
        self.assertEqual(source.read_bytes(), raw)
        self.assertFalse((self.target / "FAILED.json").exists())
        self.assertEqual(self.record()["retained_forecast_rows"], 1)

    def test_insufficient_native_store_records_explicit_error_not_invalid_forecast(self):
        self.native(); actual = failure.immutable
        def no_native_space(destination, body):
            if destination.name.endswith(".gz"): raise OSError(errno.ENOSPC, "fictional no space")
            return actual(destination, body)
        with patch.object(failure, "immutable", side_effect=no_native_space): result = self.record()
        row = self.row(result, kind="NATIVE")
        self.assertEqual(row["status"], "STORE_ERROR_NOT_RETAINED")
        self.assertEqual(row["native_rows"], 1); self.assertIsNone(row["saved_path"])
        self.assertEqual(result["retained_forecast_rows"], 0)
        self.assertFalse(failure.verify_retained(self.target)["native_retention_complete"])
        self.assertFalse(result["successful_forecast"])

    def test_unavailable_manifest_store_never_returns_retention_success(self):
        self.board()
        with patch.object(failure, "immutable", side_effect=OSError(errno.ENOSPC, "fictional no space")):
            with self.assertRaises(OSError): self.record()
        self.assertFalse((self.target / "FAILED.json").exists())

    def test_invalid_forecast_keeps_full_original_hash_and_size_without_copy(self):
        path, _ = self.board(); path.write_bytes(b'{"season":')
        result = self.record(); row = self.row(result, "output/data/week.json")
        self.assertEqual(row["status"], "INVALID_DERIVED_BYTES_NOT_COPIED")
        self.assertEqual(row["sha256"], failure.sha(path.read_bytes()))
        self.assertEqual(row["bytes"], path.stat().st_size)
        self.assertIsNone(row["saved_path"]); self.assertEqual(result["retained_bytes"], 0)

    def test_missing_fence_nonfailure_and_empty_outcome_boundaries(self):
        self.fence.unlink()
        with self.assertRaises((ValueError, FileNotFoundError)): self.record()
        self.assertFalse((self.root / "data").exists())
        guard.create(self.fence, dict(schema_version=guard.VERSION + "-begin", **guard.context(self.root, self.env)))
        self.env["PAIR_OUTCOME"] = "success"
        with self.assertRaisesRegex(ValueError, "ACTUAL_FAILED_STEP"): self.record()
        self.assertFalse((self.root / "data").exists())
        self.env.update(PAIR_OUTCOME="", RUN_OUTCOME="failure")
        self.assertEqual(self.record()["outcomes"]["PAIR"], "unknown")


if __name__ == "__main__":
    unittest.main()
