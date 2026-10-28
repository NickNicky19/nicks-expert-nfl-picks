"""Strict, content-addressed, create-only evidence shared by Phase 2 lanes."""
import gzip
import json
from pathlib import Path

from reliability import IntegrityError, canonical, digest, immutable_write, load_json


def read(path):
    path = Path(path)
    raw = gzip.decompress(path.read_bytes()).decode("utf-8")
    # Reuse the strict JSON decoder (duplicate keys and non-finite values fail).
    from reliability import _pairs
    def invalid(value):
        raise IntegrityError(f"Non-finite evidence value: {value}")
    envelope = json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)
    if envelope.get("payload_sha256") != digest(envelope.get("payload")):
        raise IntegrityError(f"Evidence checksum mismatch: {path}")
    return envelope["payload"]


def write(root, lane, payload):
    path = Path(root) / "data" / lane / str(payload["season"]) / f"w{payload['week']:02d}" / (digest(payload) + ".json.gz")
    if path.exists():
        if read(path) != payload:
            raise IntegrityError(f"Evidence conflict: {path}")
        return path
    immutable_write(path, payload)
    return path


def referenced(root, name, lane):
    path = Path(root) / name
    if Path(name).is_absolute() or not path.resolve().is_relative_to((Path(root) / "data" / lane).resolve()):
        raise IntegrityError(f"Invalid {lane} evidence path")
    return read(path)
