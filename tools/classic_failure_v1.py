"""Closed native failure evidence; other staged products remain metadata-only.

Local retention and graph verification are not remote-storage or Pages acceptance.
Malformed products never become issued forecasts. No response tape is copied.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import zlib

sys.dont_write_bytecode = True
import classic_model_v1 as model

VERSION = "classic-failed-attempt-v2"
STAGES = ("RUN", "CHECKS", "PAIR", "INSTALL", "CAPTURE", "OVERLAY", "PUBLISH", "DEPLOY", "RETRY")
MAX_FILE = 8 << 20
MAX_TOTAL = 32 << 20
MAX_DECODE = 32 << 20
MAX_MANIFEST = 256 << 10
MAX_NATIVE_FILES = 16  # Per stage. Overflow is explicitly incomplete.
MAX_SCAN_ENTRIES = 256
MAX_TARGET_ENTRIES = 512
OUTCOMES = {"success", "failure", "cancelled", "skipped", "unknown"}
STAGE_NAMES = ("original", "current")
FIXED = {"output/data/week.json": "BOARD", "output/data/meta.json": "BOARD", "WORKER.json": "CONTROL"}
ROW_FIELDS = {"stage", "source", "kind", "status", "origin", "bytes", "sha256", "saved_path", "native_rows"}
STATUSES = {"ABSENT", "SYMLINK_NOT_COPIED", "READ_ERROR_NOT_COPIED", "FILE_SIZE_LIMIT_NOT_COPIED",
            "INVALID_DERIVED_BYTES_NOT_COPIED", "INVALID_CONTROL_NOT_COPIED", "CONTROL_METADATA_ONLY",
            "UNISSUED_METADATA_ONLY", "SEED_CONTEXT_METADATA_ONLY", "UNQUALIFIED_PATH_METADATA_ONLY",
            "RETAINED_DERIVED_FORECAST", "CAPACITY_NOT_RETAINED", "STORE_ERROR_NOT_RETAINED"}
ORIGINS = {"UNKNOWN", "SEEDED_UNCHANGED", "CHANGED_SINCE_SEED", "NOT_IN_SEED", "UNQUALIFIED", "UNSEEDED_CAPTURE"}
SCAN_STATES = {"COMPLETE", "FILE_LIMIT_NOT_COMPLETE", "ENTRY_LIMIT_NOT_COMPLETE", "READ_ERROR_NOT_COMPLETE", "SYMLINK_NOT_COMPLETE"}
PAYLOAD_FIELDS = {"schema_version", "mode", "evidence_label", "captured_at", "forecast_generated_at", "input_sha256",
                  "engine_sha256", "engine_files", "code_commit", "model", "rows", "excluded_started_or_late_games"}
NATIVE_ROW_FIELDS = {"season", "week", "game_id", "kickoff", "player_id", "name", "team", "position", "category",
                     "raw_projection", "adjusted_projection", "line", "line_from", "lean", "matchup_factor",
                     "injury_at_capture", "top_over", "top_under", "probability", "expected_value", "price",
                     "settlement_status", "source_timestamps_verified"}
CATEGORIES = {"pass_yd", "pass_td", "pass_cmp", "pass_att", "pass_int", "rush_yd", "rush_att", "rec", "rec_yd",
              "rush_rec_yd", "anytime_td", "fpts"}
ORIGINAL_ENGINE = {k: v for k, v in model.ENGINE.items() if k != "pull/grade.py"}
ORIGINAL_ENGINE.update({"pull/build.py": "75bf99c55b5f2561a60a120c82db368ad3b996a8a64e9ab08828b586a9314419",
                        "pull/scoring.py": "31672c10d526d591db8951157b0ecd669b4d02b412a75deec337618bff18dab2"})
BAD_PRODUCT = (ValueError, TypeError, OSError, EOFError, zlib.error, RecursionError, OverflowError)


def require(value, code):
    if not value:
        raise ValueError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def utc(value):
    require(isinstance(value, str) and len(value) <= 40, "FAILURE_CLOCK")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "FAILURE_CLOCK")
    return parsed.astimezone(timezone.utc)


def text(value, limit=128):
    return isinstance(value, str) and 0 < len(value) <= limit and all(ord(c) >= 32 for c in value)


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is not None


def number(value):
    return value is None or type(value) in (int, float) and math.isfinite(value)


def confined(path, root):
    require(path.resolve().is_relative_to(root.resolve()) and not any(p.is_symlink() for p in (path, *path.parents)),
            "FAILURE_PATH_SYMLINK_OR_ESCAPE")


def immutable(path, raw):
    confined(path, path.parent)
    if path.exists():
        require(path.is_file() and path.read_bytes() == raw, "IMMUTABLE_FAILURE_CONFLICT")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".failure-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            require(path.read_bytes() == raw, "IMMUTABLE_FAILURE_CONFLICT")
    finally:
        Path(name).unlink(missing_ok=True)


def document(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "DUPLICATE_FAILURE_JSON_KEY")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_FAILURE_JSON")))


def execution():
    return dict(schema_version=model.EXECUTION, model=model.MODEL, capture_schema=model.CAPTURE,
                normalized_stats_cache=model.CACHE, engine_sha256=model.ENGINE,
                original_shadow_model=model.ORIGINAL_MODEL, original_shadow_source=model.ORIGINAL_SOURCE,
                original_shadow_procedure=model.SHADOW_PROCEDURE, grading_version="statistical-v3-identity-20261025")


def native_name(stage, name):
    lane = "forward" if stage == "original" else "current-classic"
    return re.fullmatch(r"data/" + lane + r"/([0-9]{4})/w([0-9]{2})/([a-f0-9]{64})\.json\.gz", name)


def validate_native(raw, stage, name, identity, recorded_at):
    """Validate every row; never project or truncate a native receipt."""
    match = native_name(stage, name)
    require(match is not None, "NATIVE_FAILURE_SCOPE")
    season, week = map(int, match.group(1, 2))
    require(2000 <= season <= 2200 and 1 <= week <= 18, "NATIVE_FAILURE_PERIOD")
    require(raw[:8] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00", "NATIVE_FAILURE_GZIP_HEADER")
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    decoded = inflater.decompress(raw, MAX_DECODE + 1)
    require(len(decoded) <= MAX_DECODE and inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail,
            "NATIVE_FAILURE_INFLATION_OR_TRAILING_DATA")
    envelope = document(decoded)
    require(type(envelope) is dict and set(envelope) == {"payload", "payload_sha256"}
            and type(envelope["payload"]) is dict and digest(envelope["payload_sha256"])
            and sha(canonical(envelope["payload"])) == envelope["payload_sha256"]
            and canonical(envelope) == decoded, "NATIVE_FAILURE_CONTENT")
    p = envelope["payload"]
    current = stage == "current"
    require(set(p) == PAYLOAD_FIELDS | ({"execution_contract", "execution_contract_sha256"} if current else set()),
            "NATIVE_FAILURE_FIELDS")
    engine = model.ENGINE if current else ORIGINAL_ENGINE
    require(p["schema_version"] == (model.CAPTURE if current else "baseline-capture-v1")
            and p["model"] == (model.MODEL if current else model.ORIGINAL_MODEL)
            and p["engine_files"] == engine and p["engine_sha256"] == sha(canonical(engine))
            and p["code_commit"] == (identity["trigger_source_sha"] if current else model.ORIGINAL_SOURCE)
            and p["mode"] == "live" and p["evidence_label"] == "LOCAL_PRE_GAME_CAPTURE_PUBLICATION_NOT_VERIFIED"
            and digest(p["input_sha256"]), "NATIVE_FAILURE_PROFILE")
    observed = utc(p["captured_at"])
    require(utc(p["forecast_generated_at"]) <= observed <= utc(recorded_at), "NATIVE_FAILURE_CLOCK")
    key = dict(data=p["input_sha256"], mode="live")
    if current:
        require(p["execution_contract"] == execution() and p["execution_contract_sha256"] == sha(canonical(execution())),
                "NATIVE_FAILURE_EXECUTION")
        key["execution"] = p["execution_contract_sha256"]
    else:
        key["engine"] = p["engine_sha256"]
    require(match.group(3) == sha(canonical(key)), "NATIVE_FAILURE_FILENAME_BINDING")
    excluded = p["excluded_started_or_late_games"]
    require(type(excluded) is list and all(identifier(x) for x in excluded)
            and excluded == sorted(set(excluded)), "NATIVE_FAILURE_EXCLUDED")
    require(type(p["rows"]) is list, "NATIVE_FAILURE_ROWS")
    keys = []
    for row in p["rows"]:
        require(type(row) is dict and set(row) in (NATIVE_ROW_FIELDS, NATIVE_ROW_FIELDS | {"sleeper_observation"}),
                "NATIVE_FAILURE_ROW_FIELDS")
        require(type(row["season"]) is int and row["season"] == season and type(row["week"]) is int and row["week"] == week
                and identifier(row["game_id"]) and identifier(row["player_id"]) and text(row["name"], 160)
                and isinstance(row["team"], str) and re.fullmatch(r"[A-Z]{2,4}", row["team"])
                and row["position"] in {"QB", "RB", "WR", "TE", "K", "DEF"} and row["category"] in CATEGORIES,
                "NATIVE_FAILURE_ROW_IDENTITY")
        require(utc(row["kickoff"]) > observed and row["game_id"] not in excluded, "NATIVE_FAILURE_KICKOFF")
        require(all(number(row[k]) for k in ("raw_projection", "adjusted_projection", "line", "matchup_factor"))
                and (row["raw_projection"] is not None or row["adjusted_projection"] is not None)
                and row["line_from"] in {"ours", "dk", "sleeper"} and row["lean"] in {None, "over", "under"}
                and (row["injury_at_capture"] is None or text(row["injury_at_capture"], 80)), "NATIVE_FAILURE_ROW_TYPES")
        require(type(row["top_over"]) is bool and type(row["top_under"]) is bool
                and not (row["top_over"] and row["top_under"])
                and all(row[k] is None for k in ("probability", "expected_value", "price"))
                and row["settlement_status"] == "NOT_VERIFIED" and row["source_timestamps_verified"] is False,
                "NATIVE_FAILURE_ROW_SEMANTICS")
        if "sleeper_observation" in row:
            observation = row["sleeper_observation"]
            require(type(observation) is dict and set(observation) == {"line", "over", "under"}
                    and all(number(observation[k]) for k in observation), "NATIVE_FAILURE_BOOK_FIELDS")
        keys.append((row["game_id"], row["player_id"], row["category"]))
    require(keys == sorted(set(keys)), "NATIVE_FAILURE_DUPLICATE_OR_UNSORTED_ROWS")
    return len(p["rows"])


def inspect(path, base):
    """Take one bounded byte snapshot; parse and copy that same snapshot."""
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(base.resolve()):
        return "SYMLINK_NOT_COPIED", None, None, None
    if not path.exists():
        return "ABSENT", None, None, None
    try:
        require(path.is_file(), "NOT_ORDINARY_FAILURE_FILE")
        size = path.stat().st_size
        if size > MAX_FILE:
            return "FILE_SIZE_LIMIT_NOT_COPIED", size, None, None
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE:
            return "FILE_SIZE_LIMIT_NOT_COPIED", len(raw), None, None
        return "INSPECTED", len(raw), sha(raw), raw
    except (ValueError, OSError):
        return "READ_ERROR_NOT_COPIED", None, None, None


def candidates(base, stage):
    """Bound enumeration and queue before loading candidate contents."""
    summary = dict(status="COMPLETE", entries=0, observed_native_files=0, queued_native_files=0)
    lane = base / ("data/forward" if stage == "original" else "data/current-classic")
    queue, stack = [], [lane]
    while stack:
        directory = stack.pop()
        if directory.is_symlink() or any(p.is_symlink() for p in directory.parents):
            summary["status"] = "SYMLINK_NOT_COMPLETE"; break
        if not directory.exists():
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    summary["entries"] += 1
                    if summary["entries"] > MAX_SCAN_ENTRIES:
                        summary["status"] = "ENTRY_LIMIT_NOT_COMPLETE"; break
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path)); continue
                    summary["observed_native_files"] += 1
                    if len(queue) >= MAX_NATIVE_FILES:
                        summary["status"] = "FILE_LIMIT_NOT_COMPLETE"; break
                    queue.append(Path(entry.path))
        except OSError:
            summary["status"] = "READ_ERROR_NOT_COMPLETE"
        if summary["status"] != "COMPLETE":
            break
    summary["queued_native_files"] = len(queue)
    return sorted(queue), summary


def seed_inventory(run):
    status, size, checksum, raw = inspect(run / "SEEDS.json", run)
    seeds = None
    if raw is not None:
        try:
            value = document(raw)
            require(type(value) is dict and set(value) == set(STAGE_NAMES)
                    and all(type(value[k]) is dict and all(isinstance(n, str) and digest(v) for n, v in value[k].items())
                            for k in STAGE_NAMES), "INVALID_SEED_INVENTORY")
            seeds = value
        except BAD_PRODUCT:
            status = "INVALID_DERIVED_BYTES_NOT_COPIED"
    return seeds, dict(status=status, bytes=size, sha256=checksum)


def validate_identity(identity, outcomes):
    import publication_guard_v1 as guard
    require(type(identity) is dict and set(identity) == {"repository", "run_id", "run_attempt", "trigger_source_sha"}
            and identity["repository"] == guard.REPOSITORY
            and isinstance(identity["run_id"], str) and re.fullmatch(r"[1-9][0-9]{0,19}", identity["run_id"])
            and isinstance(identity["run_attempt"], str) and re.fullmatch(r"[1-9][0-9]{0,3}", identity["run_attempt"])
            and isinstance(identity["trigger_source_sha"], str) and re.fullmatch(r"[a-f0-9]{40}", identity["trigger_source_sha"]),
            "CLOSED_FAILURE_IDENTITY")
    require(type(outcomes) is dict and set(outcomes) == set(STAGES)
            and all(isinstance(v, str) and v in OUTCOMES for v in outcomes.values())
            and "failure" in outcomes.values(), "ACTUAL_FAILED_STEP_REQUIRED")


def validate_manifest(value, raw, target, identity, outcomes, include_manifest=True):
    validate_identity(identity, outcomes)
    fields = {"schema_version", "state", "identity", "recorded_at", "outcomes", "files", "retained_bytes", "retained_forecast_rows",
              "successful_forecast", "failure_record_publishes_forecasts", "raw_provider_corpus_copied", "new_scheduler",
              "retention_scope", "collection", "seed_inventory"}
    require(type(value) is dict and set(value) == fields and canonical(value) == raw and len(raw) <= MAX_MANIFEST
            and value["schema_version"] == VERSION and value["state"] == "FAILED_ATTEMPT_RETAINED"
            and value["identity"] == identity and value["outcomes"] == outcomes
            and all(value[k] is False for k in ("successful_forecast", "failure_record_publishes_forecasts", "raw_provider_corpus_copied", "new_scheduler"))
            and value["retention_scope"] == "LOCAL_CHECKOUT_ONLY", "CLOSED_FAILURE_RECEIPT")
    require(utc(value["recorded_at"]) <= datetime.now(timezone.utc), "FAILURE_RECEIPT_CLOCK")
    seed = value["seed_inventory"]
    require(type(seed) is dict and set(seed) == {"status", "bytes", "sha256"}
            and seed["status"] in {"INSPECTED", "ABSENT", "SYMLINK_NOT_COPIED", "READ_ERROR_NOT_COPIED", "FILE_SIZE_LIMIT_NOT_COPIED", "INVALID_DERIVED_BYTES_NOT_COPIED"}
            and (seed["bytes"] is None or type(seed["bytes"]) is int and seed["bytes"] >= 0)
            and (seed["sha256"] is None or digest(seed["sha256"])), "CLOSED_FAILURE_SEED")
    collection = value["collection"]
    require(type(collection) is dict and set(collection) == set(STAGE_NAMES), "CLOSED_FAILURE_COLLECTION")
    rows = value["files"]
    require(type(rows) is list and 6 <= len(rows) <= 6 + 2 * MAX_NATIVE_FILES, "CLOSED_FAILURE_ROW_BOUND")
    expected = {"FAILED.json"} if include_manifest else set()
    seen = set(); retained = native_rows = 0
    counts = {stage: 0 for stage in STAGE_NAMES}
    for row in rows:
        require(type(row) is dict and set(row) == ROW_FIELDS and isinstance(row["stage"], str) and row["stage"] in STAGE_NAMES
                and isinstance(row["status"], str) and row["status"] in STATUSES
                and isinstance(row["origin"], str) and row["origin"] in ORIGINS and isinstance(row["source"], str), "CLOSED_FAILURE_ROW")
        stage, source = row["stage"], row["source"]
        require((stage, source) not in seen, "DUPLICATE_FAILURE_ROW"); seen.add((stage, source))
        kind = FIXED.get(source)
        if kind is None:
            require(native_name(stage, source) is not None or re.fullmatch(r"unqualified:[a-f0-9]{64}", source), "FAILURE_SAVED_PATH_SCOPE")
            kind = "NATIVE"; counts[stage] += 1
        require(row["kind"] == kind and (row["bytes"] is None or type(row["bytes"]) is int and row["bytes"] >= 0)
                and (row["sha256"] is None or digest(row["sha256"]))
                and (row["native_rows"] is None or type(row["native_rows"]) is int and row["native_rows"] >= 0), "CLOSED_FAILURE_ROW_TYPES")
        status = row["status"]
        if status in {"ABSENT", "SYMLINK_NOT_COPIED", "READ_ERROR_NOT_COPIED", "FILE_SIZE_LIMIT_NOT_COPIED"}:
            require(row["sha256"] is None and row["native_rows"] is None and row["origin"] == "UNKNOWN"
                    and (type(row["bytes"]) is int and row["bytes"] > MAX_FILE if status == "FILE_SIZE_LIMIT_NOT_COPIED"
                         else row["bytes"] is None), "CLOSED_FAILURE_UNREAD_PRODUCT")
        else:
            require(type(row["bytes"]) is int and row["bytes"] <= MAX_FILE and digest(row["sha256"]), "CLOSED_FAILURE_HASHED_PRODUCT")
            if kind == "CONTROL":
                require(status in {"CONTROL_METADATA_ONLY", "INVALID_CONTROL_NOT_COPIED"}
                        and row["origin"] == "UNKNOWN" and row["native_rows"] is None, "CLOSED_FAILURE_CONTROL")
            elif kind == "BOARD":
                require(row["native_rows"] is None and (
                    status == "SEED_CONTEXT_METADATA_ONLY" and row["origin"] == "SEEDED_UNCHANGED"
                    or status == "UNISSUED_METADATA_ONLY" and row["origin"] in {"UNKNOWN", "NOT_IN_SEED", "CHANGED_SINCE_SEED"}
                    or status == "INVALID_DERIVED_BYTES_NOT_COPIED" and row["origin"] == "UNKNOWN"), "CLOSED_FAILURE_BOARD")
            else:
                require(status in {"RETAINED_DERIVED_FORECAST", "CAPACITY_NOT_RETAINED", "STORE_ERROR_NOT_RETAINED"}
                        and row["origin"] == "UNSEEDED_CAPTURE" and type(row["native_rows"]) is int
                        or status == "INVALID_DERIVED_BYTES_NOT_COPIED" and row["origin"] == "UNKNOWN" and row["native_rows"] is None
                        or status == "UNQUALIFIED_PATH_METADATA_ONLY" and source.startswith("unqualified:")
                        and row["origin"] == "UNQUALIFIED" and row["native_rows"] is None, "CLOSED_FAILURE_NATIVE")
        if row["status"] == "RETAINED_DERIVED_FORECAST":
            require(kind == "NATIVE" and native_name(stage, source) is not None and row["origin"] == "UNSEEDED_CAPTURE"
                    and row["saved_path"] == stage + "/" + source and type(row["bytes"]) is int and row["bytes"] <= MAX_FILE
                    and digest(row["sha256"]), "FAILURE_SAVED_PATH_SCOPE")
            path = target / row["saved_path"]; confined(path, target)
            require(path.is_file() and path.stat().st_size == row["bytes"], "RETAINED_FAILURE_BYTES_CHANGED")
            saved = path.read_bytes()
            require(sha(saved) == row["sha256"], "RETAINED_FAILURE_BYTES_CHANGED")
            require(validate_native(saved, stage, source, identity, value["recorded_at"]) == row["native_rows"], "RETAINED_FAILURE_ROWS_CHANGED")
            expected.add(row["saved_path"]); retained += len(saved); native_rows += row["native_rows"]
        else:
            require(row["saved_path"] is None, "UNQUALIFIED_FAILURE_PATH")
            require(row["status"] not in {"CAPACITY_NOT_RETAINED", "STORE_ERROR_NOT_RETAINED"}
                    or kind == "NATIVE" and type(row["native_rows"]) is int and digest(row["sha256"]), "CLOSED_FAILURE_CAPACITY")
    require(all((stage, source) in seen for stage in STAGE_NAMES for source in FIXED), "INCOMPLETE_FAILURE_FILE_GRAPH")
    for stage, summary in collection.items():
        require(type(summary) is dict and set(summary) == {"status", "entries", "observed_native_files", "queued_native_files"}
                and isinstance(summary["status"], str) and summary["status"] in SCAN_STATES
                and all(type(summary[k]) is int and summary[k] >= 0 for k in ("entries", "observed_native_files", "queued_native_files"))
                and summary["entries"] <= MAX_SCAN_ENTRIES + 1
                and summary["queued_native_files"] == counts[stage] <= MAX_NATIVE_FILES
                and summary["queued_native_files"] <= summary["observed_native_files"] <= MAX_NATIVE_FILES + 1
                and (summary["status"] != "COMPLETE" or summary["observed_native_files"] == counts[stage]), "INCOMPLETE_FAILURE_COLLECTION_GRAPH")
    require(type(value["retained_bytes"]) is int and value["retained_bytes"] == retained <= MAX_TOTAL
            and type(value["retained_forecast_rows"]) is int and value["retained_forecast_rows"] == native_rows,
            "FAILURE_RECEIPT_ACCOUNTING")
    actual = set(); stack = [target]; entries_seen = 0
    while stack:
        directory = stack.pop(); confined(directory, target)
        if not directory.exists():
            continue
        with os.scandir(directory) as entries:
            for entry in entries:
                entries_seen += 1; require(entries_seen <= MAX_TARGET_ENTRIES, "FAILURE_STORED_GRAPH_BOUND")
                path = Path(entry.path); confined(path, target)
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                else:
                    require(entry.is_file(follow_symlinks=False), "FAILURE_SPECIAL_STORED_FILE")
                    actual.add(path.relative_to(target).as_posix())
    require(actual == expected, "INCOMPLETE_FAILURE_STORED_GRAPH")


def verify_retained(target):
    """Read-only closed graph verification, including every complete native row.

    The returned identity is a declaration to bind to external Git/job proof; this
    local verifier does not authenticate a remote run or prove remote durability.
    """
    target = Path(target).absolute(); confined(target, target)
    manifest = target / "FAILED.json"
    confined(manifest, target)
    require(manifest.is_file() and not manifest.is_symlink() and manifest.stat().st_size <= MAX_MANIFEST,
            "BOUNDED_FAILURE_RECEIPT")
    with manifest.open("rb") as stream:
        raw = stream.read(MAX_MANIFEST + 1)
    require(len(raw) <= MAX_MANIFEST, "BOUNDED_FAILURE_RECEIPT")
    value = document(raw)
    require(type(value) is dict and "identity" in value and "outcomes" in value, "CLOSED_FAILURE_RECEIPT")
    if value.get("schema_version") == PHASE2_VERSION:
        return phase2_retained(target, value, raw)
    validate_manifest(value, raw, target, value["identity"], value["outcomes"])
    files = [dict(path="FAILED.json", bytes=len(raw), sha256=sha(raw))]
    files += [dict(path=r["saved_path"], bytes=r["bytes"], sha256=r["sha256"]) for r in value["files"]
              if r["status"] == "RETAINED_DERIVED_FORECAST"]
    return dict(schema_version=VERSION, state="CLOSED_RETAINED_GRAPH_VERIFIED", identity=value["identity"],
                manifest_sha256=sha(raw), file_graph_sha256=sha(canonical(sorted(files, key=lambda x: x["path"]))),
                files=len(files), retained_bytes=value["retained_bytes"], retained_forecast_rows=value["retained_forecast_rows"],
                collection_complete=all(s["status"] == "COMPLETE" for s in value["collection"].values()),
                native_retention_complete=all(r["status"] == "RETAINED_DERIVED_FORECAST" for r in value["files"] if r["kind"] == "NATIVE"),
                product_status_counts={s: sum(r["status"] == s for r in value["files"]) for s in sorted({r["status"] for r in value["files"]})},
                retention_scope="LOCAL_CHECKOUT_ONLY", successful_forecast=False, failure_record_publishes_forecasts=False,
                raw_provider_corpus_copied=False, new_scheduler=False, source_context_verified_externally=False)


def record(root, run, fence, env):
    import publication_guard_v1 as guard
    root, run = Path(root).resolve(), Path(run).resolve()
    require(not run.is_relative_to(root), "PRIVATE_STAGING_OUTSIDE_SOURCE")
    identity = guard.context(root, env)
    require(guard.read(Path(fence)) == dict(schema_version=guard.VERSION + "-begin", **identity), "ORIGINAL_PUBLICATION_FENCE_REQUIRED")
    outcomes = {name: env.get(name + "_OUTCOME") or "unknown" for name in STAGES}
    validate_identity(identity, outcomes)
    target = root / "data/classic-failures" / (identity["run_id"] + "-" + identity["run_attempt"])
    confined(target, root)
    manifest = target / "FAILED.json"
    confined(manifest, target)
    if manifest.exists():
        require(manifest.is_file() and manifest.stat().st_size <= MAX_MANIFEST, "BOUNDED_FAILURE_RECEIPT")
        raw = manifest.read_bytes(); previous = document(raw)
        validate_manifest(previous, raw, target, identity, outcomes)
        return previous
    recorded_at = datetime.now(timezone.utc).isoformat()
    seeds, seed_status = seed_inventory(run)
    rows, selected, collection, total = [], [], {}, 0
    for stage in STAGE_NAMES:
        base = run / stage
        queue, collection[stage] = candidates(base, stage)
        products = [(base / name, name, kind) for name, kind in FIXED.items()]
        for path in queue:
            name = path.relative_to(base).as_posix()
            source = name if native_name(stage, name) is not None else "unqualified:" + sha(os.fsencode(name))
            products.append((path, source, "NATIVE"))
        for path, source, kind in products:
            status, size, checksum, raw = inspect(path, base)
            row = dict(stage=stage, source=source, kind=kind, status=status, origin="UNKNOWN", bytes=size,
                       sha256=checksum, saved_path=None, native_rows=None)
            if raw is not None:
                if kind == "NATIVE" and source.startswith("unqualified:"):
                    row.update(status="UNQUALIFIED_PATH_METADATA_ONLY", origin="UNQUALIFIED")
                else:
                    try:
                        if kind == "NATIVE":
                            count = validate_native(raw, stage, source, identity, recorded_at)
                            row.update(origin="UNSEEDED_CAPTURE", native_rows=count)
                            if total + len(raw) > MAX_TOTAL:
                                row["status"] = "CAPACITY_NOT_RETAINED"
                            else:
                                row.update(status="RETAINED_DERIVED_FORECAST", saved_path=stage + "/" + source)
                                total += len(raw); selected.append((row, raw))
                        else:
                            value = document(raw)
                            require(type(value) is dict, "FAILURE_PRODUCT_MAPPING")
                            if kind == "CONTROL":
                                require(isinstance(value.get("native_receipt"), str)
                                        and native_name(stage, value["native_receipt"]) is not None, "FAILURE_CONTROL_PATH")
                                row["status"] = "CONTROL_METADATA_ONLY"
                            else:
                                require(type(value.get("season")) is int and 2000 <= value["season"] <= 2200
                                        and type(value.get("week")) is int and 1 <= value["week"] <= 18, "FAILURE_BOARD_PERIOD")
                                if source.endswith("week.json"):
                                    require(type(value.get("players")) is list and type(value.get("games")) is list, "FAILURE_BOARD_CONTAINERS")
                                row["status"] = "UNISSUED_METADATA_ONLY"
                                if seeds is not None:
                                    seed = seeds[stage].get(source)
                                    row["origin"] = "SEEDED_UNCHANGED" if seed == checksum else "NOT_IN_SEED" if seed is None else "CHANGED_SINCE_SEED"
                                    if seed == checksum:
                                        row["status"] = "SEED_CONTEXT_METADATA_ONLY"
                    except BAD_PRODUCT:
                        row["status"] = "INVALID_CONTROL_NOT_COPIED" if kind == "CONTROL" else "INVALID_DERIVED_BYTES_NOT_COPIED"
            rows.append(row)
    for row, raw in selected:
        path = target / row["saved_path"]; confined(path, target)
        try:
            immutable(path, raw)
        except OSError:
            row.update(status="STORE_ERROR_NOT_RETAINED", saved_path=None)
    result = dict(schema_version=VERSION, state="FAILED_ATTEMPT_RETAINED", identity=identity, recorded_at=recorded_at,
                  outcomes=outcomes, files=rows, collection=collection, seed_inventory=seed_status,
                  retained_bytes=sum(row["bytes"] for row in rows if row["status"] == "RETAINED_DERIVED_FORECAST"),
                  retained_forecast_rows=sum(row["native_rows"] for row in rows if row["status"] == "RETAINED_DERIVED_FORECAST"),
                  successful_forecast=False, failure_record_publishes_forecasts=False, raw_provider_corpus_copied=False,
                  new_scheduler=False, retention_scope="LOCAL_CHECKOUT_ONLY")
    raw = canonical(result)
    validate_manifest(result, raw, target, identity, outcomes, include_manifest=False)
    immutable(manifest, raw)  # An unavailable manifest store propagates; never claim retention.
    return result


PHASE2_VERSION = "phase2-failed-attempt-v1"
PHASE2_NAMESPACES = ("data/forward", "data/verification")
PHASE2_SCHEMAS = {
    "INPUTS": ("matchup-inputs-v3", set("schema_version mode code_commit build_started_at recorded_at season week output_sha256 engine_files positions weeks inputs_observed_at week_data offer_observation projection_metadata game_status source_requests model presence_contract projection_input_components".split())),
    "SCOPE": ("partial-scope-data-integrity-v2", set("schema_version season week validator_contract validator_sha256 model engine_files output_sha256 proof plan_sha256 registration_receipt latest_inputs_sha256 completion_status verified_at checked_factors game_population full_board_verified complete_week_qualified claim".split())),
    "COMPLETION": ("partial-completion-data-integrity-v2", set("schema_version season week validator_sha256 plan_sha256 output_sha256 scope_receipt scope_payload_sha256 baseline_receipt baseline_payload_sha256 evidence_completed_at".split())),
    "REGISTRATION": ("partial-registration-data-integrity-v2", set("schema_version season week plan plan_sha256 validator_sha256 source_sha registered_at owner_authorization initial_board schedule_status_receipt".split())),
}
PHASE2_FAILURE_FIELDS = {
    "generation-failure-v1": set("schema_version season week failed_at output_sha256 error_type".split()),
    "completion-failure-data-integrity-v2": set("schema_version season week completion_sha256 failed_at reason".split()),
    "unqualified-native-preservation-v1": set("schema_version season week original_forward_name retained_name native_file_sha256 failed_at qualification".split()),
}


def phase2_role(name):
    if re.fullmatch(r"data/forward/[0-9]{4}/w[0-9]{2}/[a-f0-9]{64}\.json\.gz", name):
        return "NATIVE"
    if re.fullmatch(r"data/verification/partial-unqualified-native/[0-9]{4}/w[0-9]{2}/[a-f0-9]{64}/[a-f0-9]{64}\.json\.gz", name):
        return "NATIVE"
    if re.fullmatch(r"data/verification/[0-9]{4}/w[0-9]{2}/[a-f0-9]{64}\.json\.gz", name):
        return "INPUTS"
    for lane, kind in (("partial-scopes", "SCOPE"), ("partial-completions", "COMPLETION"),
                       ("partial-registrations", "REGISTRATION"), ("partial-failures", "FAILURE")):
        if re.fullmatch(r"data/verification/" + lane + r"/[0-9]{4}/w[0-9]{2}/[a-f0-9]{64}\.json\.gz", name):
            return kind
    return None


def phase2_decode(raw):
    require(raw[:8] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00", "PHASE2_FAILURE_GZIP_HEADER")
    stream = zlib.decompressobj(16 + zlib.MAX_WBITS)
    body = stream.decompress(raw, MAX_DECODE + 1)
    require(len(body) <= MAX_DECODE and stream.eof and not stream.unused_data and not stream.unconsumed_tail,
            "PHASE2_FAILURE_DECODE_BOUND")
    envelope = document(body)
    require(type(envelope) is dict and set(envelope) == {"payload", "payload_sha256"}
            and type(envelope["payload"]) is dict and digest(envelope["payload_sha256"])
            and sha(canonical(envelope["payload"])) == envelope["payload_sha256"]
            and canonical(envelope) == body, "PHASE2_FAILURE_ENVELOPE")
    import genuine_case_recovery as safe
    safe.privacy(envelope, body.decode("utf-8"))
    require(not re.search(r"(?:/workspace/|/Users/|file://|[A-Za-z]:\\\\Users\\\\)", body.decode("utf-8")),
            "PHASE2_FAILURE_PRIVATE_PATH")
    def private(item):
        if isinstance(item, dict):
            require(not set(item) & {"raw_provider_corpus", "raw_response_transcript", "optional_raw_response_tape",
                                     "worker_logs", "private_metadata", "private_path"}, "PHASE2_FAILURE_PRIVATE_FIELD")
            for value in item.values(): private(value)
        elif isinstance(item, list):
            for value in item: private(value)
    private(envelope)
    return envelope["payload"]


def phase2_validate(raw, kind, name, identity, profile, recorded_at):
    """Complete typed bytes for preservation only, never bundle qualification."""
    p = phase2_decode(raw)
    import data_integrity_v2 as corrected
    engine = corrected.source_hashes(corrected.CLASSIC_MODEL)
    require(profile["model"] == corrected.CLASSIC_MODEL and profile["engine_files"] == engine
            and profile["engine_sha256"] == sha(canonical(engine)) and digest(profile["validator_sha256"]),
            "PHASE2_FAILURE_CLOSED_PROFILE")
    require(type(p.get("season")) is int and 2000 <= p["season"] <= 2200
            and type(p.get("week")) is int and 1 <= p["week"] <= 18, "PHASE2_FAILURE_PERIOD") if kind != "NATIVE" else None
    if kind == "NATIVE":
        require(set(p) == PAYLOAD_FIELDS | {"presence_contract"} and p.get("schema_version") == corrected.NATIVE
                and p.get("model") == corrected.CLASSIC_MODEL and p.get("presence_contract") == corrected.PRESENCE
                and p.get("engine_files") == engine and p.get("engine_sha256") == profile["engine_sha256"]
                and p.get("code_commit") == identity["trigger_source_sha"] and p.get("mode") == "live"
                and p.get("evidence_label") == "LOCAL_PRE_GAME_CAPTURE_PUBLICATION_NOT_VERIFIED"
                and digest(p.get("input_sha256")), "PHASE2_FAILURE_NATIVE_PROFILE")
        at = utc(p["captured_at"])
        require(utc(p["forecast_generated_at"]) <= at <= utc(recorded_at), "PHASE2_FAILURE_NATIVE_CLOCK")
        native_id = sha(canonical(dict(data=p["input_sha256"], engine=p["engine_sha256"], mode="live")))
        period = re.search(r"/([0-9]{4})/w([0-9]{2})/", name)
        require(period is not None and 2000 <= int(period[1]) <= 2200 and 1 <= int(period[2]) <= 18
                and name.endswith("/" + native_id + ".json.gz"), "PHASE2_FAILURE_NATIVE_NAME")
        if "/partial-unqualified-native/" in name:
            require(name.split("/")[-2] == sha(raw), "PHASE2_FAILURE_QUARANTINE_HASH")
        excluded, rows = p["excluded_started_or_late_games"], p["rows"]
        require(type(excluded) is list and all(identifier(x) for x in excluded) and excluded == sorted(set(excluded))
                and type(rows) is list, "PHASE2_FAILURE_NATIVE_POPULATION")
        keys = []
        for row in rows:
            require(type(row) is dict and set(row) in (NATIVE_ROW_FIELDS, NATIVE_ROW_FIELDS | {"sleeper_observation"}), "PHASE2_FAILURE_NATIVE_FIELDS")
            require(type(row["season"]) is int and row["season"] == int(period[1]) and type(row["week"]) is int
                    and row["week"] == int(period[2]) and 1 <= row["week"] <= 18
                    and identifier(row["game_id"]) and identifier(row["player_id"]) and text(row["name"], 160)
                    and re.fullmatch(r"[A-Z]{2,4}", row["team"]) and row["position"] in {"QB", "RB", "WR", "TE", "K", "DEF"}
                    and row["category"] in CATEGORIES and utc(row["kickoff"]) > at and row["game_id"] not in excluded,
                    "PHASE2_FAILURE_NATIVE_IDENTITY")
            require(all(number(row[k]) for k in ("raw_projection", "adjusted_projection", "line", "matchup_factor"))
                    and (row["raw_projection"] is not None or row["adjusted_projection"] is not None)
                    and row["line_from"] in {"ours", "dk", "sleeper"} and row["lean"] in {None, "over", "under"}
                    and (row["injury_at_capture"] is None or text(row["injury_at_capture"], 80))
                    and type(row["top_over"]) is bool and type(row["top_under"]) is bool
                    and not (row["top_over"] and row["top_under"]) and all(row[k] is None for k in ("probability", "expected_value", "price"))
                    and row["settlement_status"] == "NOT_VERIFIED" and row["source_timestamps_verified"] is False,
                    "PHASE2_FAILURE_NATIVE_VALUES")
            if "sleeper_observation" in row:
                value = row["sleeper_observation"]
                require(type(value) is dict and set(value) == {"line", "over", "under"}
                        and all(number(value[k]) for k in value), "PHASE2_FAILURE_NATIVE_BOOK")
            keys.append((row["game_id"], row["player_id"], row["category"]))
        require(keys == sorted(set(keys)), "PHASE2_FAILURE_NATIVE_DUPLICATES")
        return len(rows)
    require(name.endswith("/" + sha(canonical(p)) + ".json.gz")
            and f"/{p['season']}/w{p['week']:02d}/" in name, "PHASE2_FAILURE_RECEIPT_NAME")
    if kind == "FAILURE":
        require(p.get("schema_version") in PHASE2_FAILURE_FIELDS
                and set(p) == PHASE2_FAILURE_FIELDS[p["schema_version"]]
                and utc(p["failed_at"]) <= utc(recorded_at), "PHASE2_FAILURE_MARKER")
        require(all(digest(value) for key, value in p.items() if key.endswith("sha256")), "PHASE2_FAILURE_MARKER_DIGEST")
        if "error_type" in p: require(identifier(p["error_type"]), "PHASE2_FAILURE_ERROR_TYPE")
        if "reason" in p: require(p["reason"] == "FINAL_COMPLETION_BOUNDARY_FAILED", "PHASE2_FAILURE_REASON")
        if "qualification" in p:
            require(p["qualification"] == "NO_COMPLETED_PARTIAL_BUNDLE_NOT_A_PREGAME_OBSERVATION"
                    and phase2_role(p["original_forward_name"]) == "NATIVE"
                    and phase2_role(p["retained_name"]) == "NATIVE", "PHASE2_FAILURE_QUARANTINE_REFERENCE")
        return 0
    schema, fields = PHASE2_SCHEMAS[kind]
    require(set(p) == fields and p["schema_version"] == schema, "PHASE2_FAILURE_TYPED_FIELDS")
    require(all(digest(value) for key, value in p.items() if key.endswith("sha256")), "PHASE2_FAILURE_TYPED_DIGEST")
    if kind == "INPUTS":
        require(p["model"] == corrected.CLASSIC_MODEL and p["presence_contract"] == corrected.PRESENCE
                and p["code_commit"] == identity["trigger_source_sha"] and p["engine_files"] == engine and p["mode"] == "live"
                and type(p["week_data"]) is dict and sha(canonical(p["week_data"])) == p["output_sha256"]
                and (p["week_data"].get("season"), p["week_data"].get("week")) == (p["season"], p["week"])
                and utc(p["build_started_at"]) <= utc(p["inputs_observed_at"]) <= utc(p["recorded_at"]) <= utc(recorded_at)
                and utc(p["week_data"]["generated_at"]) <= utc(p["recorded_at"])
                and type(p["positions"]) is dict and p["positions"] and all(identifier(k) and v in {"QB", "RB", "WR", "TE"} for k, v in p["positions"].items())
                and all(type(p[k]) is dict for k in ("weeks", "offer_observation", "projection_metadata", "game_status", "projection_input_components"))
                and type(p["source_requests"]) is list, "PHASE2_FAILURE_INPUT_PROFILE")
        require(type(p["week_data"].get("players")) is list and type(p["week_data"].get("games")) is list,
                "PHASE2_FAILURE_INPUT_BOARD")
        for request in p["source_requests"]:
            require(type(request) is dict and set(request) == {"url", "params", "collected_at", "response_sha256", "response_hash_format"}
                    and request["response_hash_format"] == corrected.MODEL_INPUT_HASH and digest(request["response_sha256"])
                    and isinstance(request["url"], str) and re.fullmatch(r"https://api\.sleeper\.app/(?:v1/players/nfl|(?:stats|projections)/nfl/[0-9]{4}/[0-9]{1,2})", request["url"])
                    and utc(p["build_started_at"]) <= utc(request["collected_at"]) <= utc(p["recorded_at"]), "PHASE2_FAILURE_INPUT_REQUEST")
            params = request["params"]
            require(params is None or type(params) is list and all(type(pair) is list and len(pair) == 2 and
                    (pair[0] == "season_type" and pair[1] == "regular" or pair[0] == "position[]" and pair[1] in {"QB", "RB", "WR", "TE", "K", "DEF"}
                     or pair[0] == "order_by" and pair[1] == "pts_ppr") for pair in params), "PHASE2_FAILURE_INPUT_PARAMS")
        import source_evidence
        status = p["game_status"].get(f"{p['season']}_{p['week']:02d}")
        games = source_evidence.verified_status(status, p["season"], p["week"], "live", utc(p["recorded_at"]))
        require(set(games) == {g["id"] for g in p["week_data"]["games"]}, "PHASE2_FAILURE_INPUT_STATUS")
        for component in p["projection_input_components"].values():
            require(type(component) is dict and set(component) == {"stats", "collected_at", "source", "source_response_sha256", "claim"}
                    and type(component["stats"]) is dict
                    and component["claim"] == "RETAINED_MODEL_INPUT_COMPONENTS_NOT_INDEPENDENT_PROVIDER_AUTHENTICATION"
                    and any(r["url"] == component["source"] and r["response_sha256"] == component["source_response_sha256"]
                            and r["collected_at"] == component["collected_at"] for r in p["source_requests"]), "PHASE2_FAILURE_COMPONENT_SOURCE")
        return 0
    require(p["validator_sha256"] == profile["validator_sha256"], "PHASE2_FAILURE_HELPER_VERSION")
    if kind == "SCOPE":
        require(p["model"] == corrected.CLASSIC_MODEL and p["engine_files"] == engine and p["validator_contract"] == corrected.VALIDATOR
                and p["full_board_verified"] is False and p["complete_week_qualified"] is False
                and p["claim"] == "RETAINED_ORIGINAL_MODEL_INPUT_REPRODUCTION_NOT_PROVIDER_TIME_OR_ACCURACY"
                and utc(p["verified_at"]) <= utc(recorded_at) and type(p["proof"]) is dict
                and type(p["game_population"]) is list and type(p["checked_factors"]) is int,
                "PHASE2_FAILURE_SCOPE")
    elif kind == "COMPLETION":
        require(utc(p["evidence_completed_at"]) <= utc(recorded_at) and phase2_role(p["scope_receipt"]) == "SCOPE"
                and phase2_role(p["baseline_receipt"]) == "NATIVE", "PHASE2_FAILURE_COMPLETION")
    else:
        require(type(p["plan"]) is dict and p["plan"].get("model") == corrected.CLASSIC_MODEL
                and sha(canonical(p["plan"])) == p["plan_sha256"] and p["source_sha"] == identity["trigger_source_sha"]
                and utc(p["registered_at"]) <= utc(recorded_at) and text(p["owner_authorization"], 4096)
                and type(p["initial_board"]) is dict and p["plan"].get("schema_version") == corrected.PLAN
                and p["plan"].get("validator_contract") == corrected.VALIDATOR and p["plan"].get("engine_files") == engine
                and p["plan"].get("experimental_recording_enabled") is False and p["plan"].get("full_board_verified") is False
                and p["plan"].get("complete_week_qualified") is False and type(p["plan"].get("games")) is list
                and type(p["plan"].get("legacy_exemptions")) is list, "PHASE2_FAILURE_REGISTRATION")
    return 0


def phase2_git(root, *args, worktree=None, bound=MAX_MANIFEST, partial=False):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    command = ["git", "--no-replace-objects", "--no-lazy-fetch", "-C", str(root), "-c", "core.hooksPath=/dev/null"]
    if worktree is not None: command += ["--work-tree=" + str(worktree)]
    process = subprocess.Popen(command + list(args), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    try:
        body = process.stdout.read(bound + 1)
        if len(body) > bound:
            process.kill(); process.wait(timeout=5)
            if partial:
                prefix = body[:bound]
                return prefix[:prefix.rfind(b"\0") + 1], True
            raise ValueError("PHASE2_FAILURE_GIT_BOUND")
        require(process.wait(timeout=60) == 0, "PHASE2_FAILURE_GIT_READ")
        return (body, False) if partial else body
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)


def phase2_source(root, identity):
    import data_integrity_v2 as corrected
    source = identity["trigger_source_sha"]
    commit = phase2_git(root, "cat-file", "commit", source, bound=65536)
    require(hashlib.sha1(b"commit " + str(len(commit)).encode() + b"\0" + commit).hexdigest() == source,
            "PHASE2_FAILURE_TRIGGER_OBJECT")
    engine = corrected.source_hashes(corrected.CLASSIC_MODEL)
    for name, expected in engine.items():
        entry = phase2_git(root, "ls-tree", source, "--", name).decode().strip().split()
        require(len(entry) == 4 and entry[0] == "100644" and entry[1] == "blob" and entry[3] == name,
                "PHASE2_FAILURE_SOURCE_ROLE")
        raw = phase2_git(root, "cat-file", "blob", source + ":" + name, bound=MAX_FILE)
        require(sha(raw) == expected and hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == entry[2],
                "PHASE2_FAILURE_SOURCE_BYTES")
        status, _, checksum, _ = inspect(root / name, root)
        require(status == "INSPECTED" and checksum == expected, "PHASE2_FAILURE_CHANGED_SOURCE")
    return dict(model=corrected.CLASSIC_MODEL, engine_files=engine, engine_sha256=sha(canonical(engine)),
                validator_sha256=corrected.code_sha256(), trigger_tree=commit.splitlines()[0].decode().removeprefix("tree "))


def phase2_paths(root, base, source):
    changed, overflow = phase2_git(root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "--no-renames", source, "--", *PHASE2_NAMESPACES, worktree=base, partial=True)
    untracked, more = phase2_git(root, "ls-files", "--others", "-z", "--", *PHASE2_NAMESPACES, worktree=base, partial=True)
    names = sorted(set(os.fsdecode(name) for name in (changed + untracked).split(b"\0") if name))
    incomplete = overflow or more or len(names) > MAX_SCAN_ENTRIES
    return names[:MAX_SCAN_ENTRIES], "ENTRY_LIMIT_NOT_COMPLETE" if incomplete else "COMPLETE"


def phase2_retained(target, value, raw, *, include_manifest=True):
    fields = set("schema_version state identity recorded_at outcomes profile files collection retained_bytes retained_forecast_rows successful_forecast failure_record_publishes_forecasts raw_provider_corpus_copied new_scheduler retention_scope".split())
    require(type(value) is dict and set(value) == fields and value["schema_version"] == PHASE2_VERSION
            and canonical(value) == raw and len(raw) <= MAX_MANIFEST and value["state"] == "FAILED_ATTEMPT_RETAINED"
            and all(value[k] is False for k in ("successful_forecast", "failure_record_publishes_forecasts", "raw_provider_corpus_copied", "new_scheduler"))
            and value["retention_scope"] == "LOCAL_CHECKOUT_ONLY", "PHASE2_FAILURE_MANIFEST")
    validate_identity(value["identity"], value["outcomes"])
    import data_integrity_v2 as corrected
    profile = value["profile"]; engine = corrected.source_hashes(corrected.CLASSIC_MODEL)
    require(type(profile) is dict and set(profile) == {"model", "engine_files", "engine_sha256", "validator_sha256", "trigger_tree"}
            and profile["model"] == corrected.CLASSIC_MODEL and profile["engine_files"] == engine
            and profile["engine_sha256"] == sha(canonical(engine)) and digest(profile["validator_sha256"])
            and isinstance(profile["trigger_tree"], str) and re.fullmatch(r"[a-f0-9]{40}", profile["trigger_tree"]), "PHASE2_FAILURE_CLOSED_PROFILE")
    require(utc(value["recorded_at"]) <= datetime.now(timezone.utc) and type(value["files"]) is list
            and len(value["files"]) <= MAX_SCAN_ENTRIES and type(value["collection"]) is dict, "PHASE2_FAILURE_MANIFEST_BOUND")
    expected = {"FAILED.json"} if include_manifest else set(); total = rows = 0; seen = set()
    files = [dict(path="FAILED.json", bytes=len(raw), sha256=sha(raw))]
    for row in value["files"]:
        require(type(row) is dict and set(row) == ROW_FIELDS and identifier(row["stage"])
                and (row["stage"] == "checkout" or re.fullmatch(r"transaction-[0-9]{3}", row["stage"]))
                and type(row["source"]) is str and row["kind"] in {"NATIVE", "INPUTS", "SCOPE", "COMPLETION", "REGISTRATION", "FAILURE", "UNCLASSIFIED"}
                and (row["stage"], row["source"]) not in seen, "PHASE2_FAILURE_ROW")
        seen.add((row["stage"], row["source"]))
        require(phase2_role(row["source"]) == row["kind"] if row["kind"] != "UNCLASSIFIED"
                else re.fullmatch(r"unqualified:[a-f0-9]{64}", row["source"]), "PHASE2_FAILURE_LOGICAL_ROLE")
        require(row["origin"] in {"NOT_IN_BASELINE", "TRACKED_BASELINE"} and (row["bytes"] is None or type(row["bytes"]) is int and row["bytes"] >= 0)
                and (row["sha256"] is None or digest(row["sha256"])) and (row["native_rows"] is None or type(row["native_rows"]) is int and row["native_rows"] >= 0), "PHASE2_FAILURE_ROW_TYPES")
        if row["status"] == "RETAINED_UNQUALIFIED_EVIDENCE":
            require(row["origin"] == "NOT_IN_BASELINE" and phase2_role(row["source"]) == row["kind"]
                    and re.fullmatch(r"evidence/[0-9]{3}-[a-f0-9]{64}\.json\.gz", row["saved_path"])
                    and row["saved_path"].endswith("-" + row["sha256"] + ".json.gz")
                    and row["bytes"] <= MAX_FILE and digest(row["sha256"]), "PHASE2_FAILURE_SAVED_PATH")
            path = target / row["saved_path"]; confined(path, target)
            require(path.is_file() and path.stat().st_size == row["bytes"], "PHASE2_FAILURE_SAVED_BYTES")
            with path.open("rb") as stream:
                saved = stream.read(MAX_FILE + 1)
            require(len(saved) == row["bytes"] <= MAX_FILE and sha(saved) == row["sha256"], "PHASE2_FAILURE_SAVED_BYTES")
            count = phase2_validate(saved, row["kind"], row["source"], value["identity"], value["profile"], value["recorded_at"])
            require(count == row["native_rows"], "PHASE2_FAILURE_SAVED_ROWS")
            expected.add(row["saved_path"]); total += len(saved); rows += count
            files.append(dict(path=row["saved_path"], bytes=len(saved), sha256=sha(saved)))
        else:
            require(row["status"] in {"ABSENT", "SYMLINK_NOT_COPIED", "READ_ERROR_NOT_COPIED", "FILE_SIZE_LIMIT_NOT_COPIED", "INVALID_DERIVED_BYTES_NOT_COPIED", "UNQUALIFIED_PATH_METADATA_ONLY", "TRACKED_BASELINE_METADATA_ONLY", "CAPACITY_NOT_RETAINED", "STORE_ERROR_NOT_RETAINED", "NATIVE_LIMIT_METADATA_ONLY"}
                    and row["saved_path"] is None, "PHASE2_FAILURE_METADATA_ROW")
    require(type(value["retained_bytes"]) is int and type(value["retained_forecast_rows"]) is int
            and total == value["retained_bytes"] <= MAX_TOTAL and rows == value["retained_forecast_rows"], "PHASE2_FAILURE_ACCOUNTING")
    for stage, summary in value["collection"].items():
        require((stage in {"checkout", "transactions"} or re.fullmatch(r"transaction-[0-9]{3}", stage))
                and type(summary) is dict and set(summary) == {"status", "entries"}
                and summary["status"] in SCAN_STATES and type(summary["entries"]) is int
                and 0 <= summary["entries"] <= MAX_SCAN_ENTRIES, "PHASE2_FAILURE_COLLECTION")
        if stage != "transactions":
            require(summary["entries"] == sum(r["stage"] == stage for r in value["files"]), "PHASE2_FAILURE_COLLECTION_ROWS")
    require("checkout" in value["collection"] and all(r["stage"] in value["collection"] for r in value["files"])
            and sum(r["kind"] == "NATIVE" and r["status"] != "NATIVE_LIMIT_METADATA_ONLY" for r in value["files"]) <= MAX_NATIVE_FILES,
            "PHASE2_FAILURE_NATIVE_BOUND")
    actual = set(); entries = 0
    for directory, folders, names in os.walk(target, followlinks=False):
        for name in folders + names:
            entries += 1; require(entries <= MAX_TARGET_ENTRIES, "FAILURE_STORED_GRAPH_BOUND")
            path = Path(directory) / name; confined(path, target)
            if path.is_file(): actual.add(path.relative_to(target).as_posix())
    require(actual == expected, "PHASE2_FAILURE_STORED_GRAPH")
    return dict(schema_version=PHASE2_VERSION, state="CLOSED_RETAINED_GRAPH_VERIFIED", identity=value["identity"],
                manifest_sha256=sha(raw), file_graph_sha256=sha(canonical(sorted(files, key=lambda x: x["path"]))),
                files=len(files), retained_bytes=total, retained_forecast_rows=rows,
                collection_complete=all(v["status"] == "COMPLETE" for v in value["collection"].values()),
                native_retention_complete=all(r["status"] == "RETAINED_UNQUALIFIED_EVIDENCE" for r in value["files"] if r["kind"] == "NATIVE"),
                retention_scope="LOCAL_CHECKOUT_ONLY", successful_forecast=False, failure_record_publishes_forecasts=False,
                raw_provider_corpus_copied=False, new_scheduler=False, source_context_verified_externally=False)


def record_phase2(root, transaction, fence, env):
    import publication_guard_v1 as guard
    import genuine_case_recovery as safe
    from reliability import IntegrityError
    root = Path(root).resolve(); transaction = Path(transaction).absolute()
    identity = guard.context(root, env)
    require(guard.read(Path(fence)) == dict(schema_version=guard.VERSION + "-begin", **identity), "ORIGINAL_PUBLICATION_FENCE_REQUIRED")
    expected = Path(env.get("RUNNER_TEMP", "")) / ("nfl-current-updater-" + identity["run_id"] + "-" + identity["run_attempt"])
    require(env.get("RUNNER_TEMP") and env.get("TMPDIR") and transaction == expected.absolute()
            and transaction == Path(env["TMPDIR"]).absolute() and not transaction.is_relative_to(root), "PHASE2_FAILURE_TRANSACTION_BINDING")
    confined(transaction, transaction.parent)
    outcomes = {name: env.get(name + "_OUTCOME") or "unknown" for name in STAGES}; validate_identity(identity, outcomes)
    profile = phase2_source(root, identity)
    target = root / "data/classic-failures" / (identity["run_id"] + "-" + identity["run_attempt"]); confined(target, root)
    manifest = target / "FAILED.json"
    confined(manifest, target)
    if manifest.exists():
        require(manifest.is_file() and manifest.stat().st_size <= MAX_MANIFEST, "BOUNDED_FAILURE_RECEIPT")
        with manifest.open("rb") as stream:
            raw = stream.read(MAX_MANIFEST + 1)
        require(len(raw) <= MAX_MANIFEST, "BOUNDED_FAILURE_RECEIPT")
        previous = document(raw)
        require(previous.get("identity") == identity and previous.get("outcomes") == outcomes, "PHASE2_FAILURE_RETRY_IDENTITY")
        phase2_retained(target, previous, raw); return previous
    origins = [("checkout", root)]; collection = {}
    if transaction.exists():
        extra, issues = safe.transaction_roots(transaction)
        require(len(extra) + len(issues) <= MAX_SCAN_ENTRIES, "PHASE2_FAILURE_TRANSACTION_COUNT")
        origins += [("transaction-" + str(i).zfill(3), path) for i, (_, path) in enumerate(extra)]
        collection["transactions"] = dict(status="COMPLETE" if not issues else "ENTRY_LIMIT_NOT_COMPLETE", entries=len(extra) + len(issues))
    recorded_at = datetime.now(timezone.utc).isoformat(); rows = []; selected = []; total = native_count = 0
    for stage, base in origins:
        try:
            names, scan_status = phase2_paths(root, base, identity["trigger_source_sha"])
        except (ValueError, OSError, subprocess.SubprocessError):
            collection[stage] = dict(status="READ_ERROR_NOT_COMPLETE", entries=0)
            continue
        collection[stage] = dict(status=scan_status, entries=0)
        source_ok = all(inspect(base / name, base)[:3:2] == ("INSPECTED", expected)
                        for name, expected in profile["engine_files"].items())
        if not source_ok: collection[stage]["status"] = "READ_ERROR_NOT_COMPLETE"
        for name in names:
            if len(rows) >= MAX_SCAN_ENTRIES:
                collection[stage]["status"] = "ENTRY_LIMIT_NOT_COMPLETE"; break
            collection[stage]["entries"] += 1
            kind = phase2_role(name); source = name if kind else "unqualified:" + sha(os.fsencode(name))
            tracked = bool(phase2_git(root, "ls-tree", identity["trigger_source_sha"], "--", name))
            status, size, checksum, raw = inspect(base / name, base)
            row = dict(stage=stage, source=source, kind=kind or "UNCLASSIFIED", status=status,
                       origin="TRACKED_BASELINE" if tracked else "NOT_IN_BASELINE", bytes=size, sha256=checksum, saved_path=None, native_rows=None)
            native_overflow = kind == "NATIVE" and native_count >= MAX_NATIVE_FILES
            if kind == "NATIVE" and not native_overflow: native_count += 1
            if native_overflow:
                row["status"] = "NATIVE_LIMIT_METADATA_ONLY"; collection[stage]["status"] = "FILE_LIMIT_NOT_COMPLETE"
            elif raw is not None:
                if tracked: row["status"] = "TRACKED_BASELINE_METADATA_ONLY"
                elif kind is None: row["status"] = "UNQUALIFIED_PATH_METADATA_ONLY"
                elif not source_ok: row["status"] = "INVALID_DERIVED_BYTES_NOT_COPIED"
                else:
                    try:
                        row["native_rows"] = phase2_validate(raw, kind, name, identity, profile, recorded_at)
                        if total + len(raw) > MAX_TOTAL: row["status"] = "CAPACITY_NOT_RETAINED"
                        else:
                            row.update(status="RETAINED_UNQUALIFIED_EVIDENCE", saved_path="evidence/" + str(len(rows)).zfill(3) + "-" + checksum + ".json.gz")
                            total += len(raw); selected.append((row, raw))
                    except BAD_PRODUCT + (KeyError, IndexError, IntegrityError):
                        row["status"] = "INVALID_DERIVED_BYTES_NOT_COPIED"; row["native_rows"] = None
            rows.append(row)
    for row, raw in selected:
        path = target / row["saved_path"]; confined(path, target)
        try: immutable(path, raw)
        except OSError: row.update(status="STORE_ERROR_NOT_RETAINED", saved_path=None)
    result = dict(schema_version=PHASE2_VERSION, state="FAILED_ATTEMPT_RETAINED", identity=identity, recorded_at=recorded_at,
                  outcomes=outcomes, profile=profile, files=rows, collection=collection,
                  retained_bytes=sum(r["bytes"] for r in rows if r["status"] == "RETAINED_UNQUALIFIED_EVIDENCE"),
                  retained_forecast_rows=sum(r["native_rows"] for r in rows if r["status"] == "RETAINED_UNQUALIFIED_EVIDENCE"),
                  successful_forecast=False, failure_record_publishes_forecasts=False, raw_provider_corpus_copied=False,
                  new_scheduler=False, retention_scope="LOCAL_CHECKOUT_ONLY")
    raw = canonical(result); phase2_retained(target, result, raw, include_manifest=False)
    require(phase2_source(root, identity) == profile, "PHASE2_FAILURE_SOURCE_CHANGED")
    immutable(manifest, raw)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--private-run-dir", type=Path)
    parser.add_argument("--phase2-transaction-dir", type=Path)
    parser.add_argument("--fence", type=Path)
    parser.add_argument("--verify-retained-root", type=Path)
    args = parser.parse_args()
    if args.verify_retained_root:
        if args.private_run_dir or args.phase2_transaction_dir or args.fence:
            parser.error("Verification cannot be combined with recording")
        print(json.dumps(verify_retained(args.verify_retained_root), sort_keys=True))
    else:
        if not args.fence or bool(args.private_run_dir) == bool(args.phase2_transaction_dir):
            parser.error("Recording requires fence and exactly one recording route")
        value = (record_phase2(args.root, args.phase2_transaction_dir, args.fence, os.environ)
                 if args.phase2_transaction_dir else record(args.root, args.private_run_dir, args.fence, os.environ))
        print(json.dumps({k: value[k] for k in ("schema_version", "state", "retained_bytes", "retained_forecast_rows", "retention_scope",
                                               "successful_forecast", "failure_record_publishes_forecasts", "raw_provider_corpus_copied")}))


if __name__ == "__main__":
    main()
