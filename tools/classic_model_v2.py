"""Closed presence-safe successor; original and classic-v1 profiles stay exact."""
from pathlib import Path
import hashlib

import classic_model_v1 as previous

MODEL = "sleeper-matchup-classic-presence-strict-v2"
CAPTURE = "baseline-capture-classic-presence-v2"
EXECUTION = "weekly-classic-presence-execution-v2"
CACHE = "stat-keys-presence-strict-v3"
GRADING = "statistical-presence-strict-v5-20261106"
ORIGINAL_MODEL = previous.ORIGINAL_MODEL
ORIGINAL_SOURCE = previous.ORIGINAL_SOURCE
SHADOW_PROCEDURE = previous.SHADOW_PROCEDURE
PREVIOUS_MODEL = previous.MODEL
ENGINE = dict(previous.ENGINE, **{
    "pull/build.py": "b83126080149f2f0705682d1c0be0a8ee87610ebb0a88cd57b94b8a82b63ad73",
    "pull/scoring.py": "90a9d201581b20c4e757912ce7dbf4941a6a90784d721c80367341511c652a2d",
    "pull/grade.py": "afd1310d708def4f400e6bf84e981e2edc7635dc946a63571022203c1d3ae735",
    "pull/matchup.py": "eaf627730041060ad16dd9930accfe54a54cf5fb49bb42d18680b5c572ddd7a5",
})


def descriptor():
    return dict(schema_version=EXECUTION, model=MODEL, capture_schema=CAPTURE,
                normalized_stats_cache=CACHE, engine_sha256=dict(ENGINE),
                original_shadow_model=ORIGINAL_MODEL, original_shadow_source=ORIGINAL_SOURCE,
                original_shadow_procedure=SHADOW_PROCEDURE, grading_version=GRADING)


def contract(root):
    root = Path(root).resolve()
    for name, expected in ENGINE.items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > 2 << 20:
            raise ValueError("CURRENT_ENGINE_SCOPE")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("UNRECOGNIZED_CLASSIC_CURRENT_SOURCE: " + name)
    return descriptor()
