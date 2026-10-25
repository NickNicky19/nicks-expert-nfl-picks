"""Retain failed build evidence without installing a board or deploying Pages."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zlib

VERSION = "classic-failed-attempt-v1"
STAGES = ("RUN", "CHECKS", "PAIR", "INSTALL", "CAPTURE", "OVERLAY", "PUBLISH", "DEPLOY", "RETRY")
MODELS = {"original_sleeper_matchup_baseline", "sleeper-matchup-classic-fg-identity-v1"}
MAX_FILE = 8 << 20
MAX_TOTAL = 32 << 20


def require(value, code):
    if not value:
        raise ValueError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def immutable(path, raw):
    require(not any(p.is_symlink() for p in (path, *path.parents)), "FAILURE_PATH_SYMLINK")
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


def record(root, run, fence, env):
    # The existing writer has already checked its trigger, checkout and workflow.
    # Reuse that immutable receipt; a failed begin cannot fabricate a reservation.
    import publication_guard_v1 as guard
    root, run = Path(root).resolve(), Path(run).resolve()
    require(not run.is_relative_to(root), "PRIVATE_STAGING_OUTSIDE_SOURCE")
    identity = guard.context(root, env)
    require(guard.read(Path(fence)) == dict(schema_version=guard.VERSION + "-begin", **identity),
            "ORIGINAL_PUBLICATION_FENCE_REQUIRED")
    outcomes = {name: env.get(name + "_OUTCOME") or "unknown" for name in STAGES}
    require(all(v in {"success", "failure", "cancelled", "skipped", "unknown"} for v in outcomes.values())
            and "failure" in outcomes.values(), "ACTUAL_FAILED_STEP_REQUIRED")
    target = root / "data/classic-failures" / (identity["run_id"] + "-" + identity["run_attempt"])
    manifest = target / "FAILED.json"
    if manifest.exists():
        previous = document(manifest.read_bytes())
        require(previous["identity"] == identity and previous["outcomes"] == outcomes,
                "IMMUTABLE_FAILURE_IDENTITY_CONFLICT")
        for row in previous["files"]:
            if row["status"] == "RETAINED_DERIVED_FORECAST":
                path = target / row["saved_path"]
                require(path.is_file() and not path.is_symlink() and sha(path.read_bytes()) == row["sha256"],
                        "RETAINED_FAILURE_BYTES_CHANGED")
        return previous
    rows, selected, total = [], [], 0
    # Closed forecast products only. Never copy HTTP bodies, request tape, cache,
    # stderr, arbitrary worker control paths, laboratory artifacts or weights.
    for stage in ("original", "current"):
        base = run / stage
        names = ["output/data/week.json", "output/data/meta.json"]
        worker = base / "WORKER.json"
        if worker.is_file() and not worker.is_symlink() and worker.stat().st_size <= MAX_FILE:
            try:
                control = document(worker.read_bytes())
                native = control.get("native_receipt", "")
                require(re.fullmatch(r"data/(?:forward|current-classic)/[0-9]{4}/w[0-9]{2}/[a-f0-9]{64}\.json\.gz", native),
                        "NATIVE_FAILURE_SCOPE")
                names.append(native)
            except (ValueError, TypeError):
                rows.append(dict(stage=stage, source="WORKER.json", status="INVALID_CONTROL_NOT_COPIED"))
        # These lanes are absent from stage seeds. A capture whose worker was
        # interrupted before its final marker must still survive the failure.
        for lane in ("data/forward", "data/current-classic"):
            for path in sorted((base / lane).rglob("*.json.gz")):
                require(len(names) < 16, "FAILURE_NATIVE_FILE_BOUND")
                name = path.relative_to(base).as_posix()
                require(re.fullmatch(r"data/(?:forward|current-classic)/[0-9]{4}/w[0-9]{2}/[a-f0-9]{64}\.json\.gz", name),
                        "NATIVE_FAILURE_SCOPE")
                if name not in names:
                    names.append(name)
        for name in names:
            path = base / name
            row = dict(stage=stage, source=name, status="ABSENT")
            if path.is_symlink() or any(p.is_symlink() for p in path.parents):
                row["status"] = "SYMLINK_NOT_COPIED"
            elif path.is_file():
                size = path.stat().st_size
                if size > MAX_FILE:
                    row.update(status="BOUND_EXCEEDED_NOT_COPIED", bytes=size)
                else:
                    raw = path.read_bytes(); row.update(bytes=len(raw), sha256=sha(raw))
                    try:
                        if name.endswith(".gz"):
                            with gzip.open(path, "rb") as stream:
                                decoded = stream.read(MAX_TOTAL + 1)
                            require(len(decoded) <= MAX_TOTAL, "NATIVE_FAILURE_INFLATION")
                            value = document(decoded)
                            require(set(value) == {"payload", "payload_sha256"}
                                    and sha(canonical(value["payload"])) == value["payload_sha256"]
                                    and value["payload"].get("model") in MODELS,
                                    "NATIVE_FAILURE_CONTENT")
                        else:
                            value = document(raw)
                            require(isinstance(value, dict) and type(value.get("season")) is int
                                    and type(value.get("week")) is int, "DERIVED_FAILURE_PERIOD")
                            if name.endswith("week.json"):
                                require(isinstance(value.get("players"), list) and isinstance(value.get("games"), list),
                                        "DERIVED_FAILURE_BOARD")
                        total += len(raw)
                        require(total <= MAX_TOTAL, "FAILURE_AGGREGATE_BOUND")
                        saved = stage + "/" + name
                        row.update(status="RETAINED_DERIVED_FORECAST", saved_path=saved)
                        selected.append((target / saved, raw))
                    except (ValueError, TypeError, OSError, EOFError, zlib.error):
                        row["status"] = "INVALID_DERIVED_BYTES_NOT_COPIED"
            rows.append(row)
    result = dict(schema_version=VERSION, state="FAILED_ATTEMPT_RETAINED", identity=identity,
                  recorded_at=datetime.now(timezone.utc).isoformat(), outcomes=outcomes,
                  files=rows, retained_bytes=sum(len(raw) for _, raw in selected),
                  successful_forecast=False, failure_record_publishes_forecasts=False,
                  raw_provider_corpus_copied=False, new_scheduler=False)
    # Complete admission before the first write. The original staged products
    # remain untouched even when a write is interrupted.
    for path, raw in selected:
        immutable(path, raw)
    immutable(manifest, canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--private-run-dir", type=Path, required=True)
    parser.add_argument("--fence", type=Path, required=True)
    args = parser.parse_args()
    value = record(args.root, args.private_run_dir, args.fence, os.environ)
    print(json.dumps({k: value[k] for k in ("schema_version", "state", "retained_bytes", "successful_forecast",
                                           "failure_record_publishes_forecasts", "raw_provider_corpus_copied")}))


if __name__ == "__main__":
    main()
