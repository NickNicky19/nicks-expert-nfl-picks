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
    raw = manifest.read_bytes(); value = document(raw)
    require(type(value) is dict and "identity" in value and "outcomes" in value, "CLOSED_FAILURE_RECEIPT")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--private-run-dir", type=Path)
    parser.add_argument("--fence", type=Path)
    parser.add_argument("--verify-retained-root", type=Path)
    args = parser.parse_args()
    if args.verify_retained_root:
        if args.private_run_dir or args.fence:
            parser.error("Verification cannot be combined with recording")
        print(json.dumps(verify_retained(args.verify_retained_root), sort_keys=True))
    else:
        if not args.private_run_dir or not args.fence:
            parser.error("Recording requires private-run-dir and fence")
        value = record(args.root, args.private_run_dir, args.fence, os.environ)
        print(json.dumps({k: value[k] for k in ("schema_version", "state", "retained_bytes", "retained_forecast_rows", "retention_scope",
                                               "successful_forecast", "failure_record_publishes_forecasts", "raw_provider_corpus_copied")}))


if __name__ == "__main__":
    main()
