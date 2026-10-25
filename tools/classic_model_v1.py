"""Closed main-only corrected classic execution; historical R0 stays immutable."""
from pathlib import Path
import hashlib
import json

MODEL = "sleeper-matchup-classic-fg-identity-v1"
CAPTURE = "baseline-capture-classic-v1"
EXECUTION = "weekly-classic-current-execution-v1"
CACHE = "stat-keys-fgm-v1"
ORIGINAL_MODEL = "original_sleeper_matchup_baseline"
ORIGINAL_SOURCE = "89512ed952308dacc1f6a930915ddbcdccd460d9"
SHADOW_PROCEDURE = "original-builder-default-refresh-v1"
ENGINE = {
    "pull/build.py": "1d1646ef67469c3ec45227b9fcb053c4e229362a07bca092a5602a1a1442c1e1",
    "pull/scoring.py": "58c1f57fb0404f8bb6d1568d51791c97cdf0bb941c57117b703c6a24534980db",
    "pull/grade.py": "739df92bf9a04ef5f9974e4213bb7fda98b29be84c30654c2095003fbb974354",
    "pull/matchup.py": "15b1739b203e1757b0ebaefa3a6994034d56bb4a92a9e07572527ef1a90e914c",
    "pull/books.py": "0b89744960136a4f2e594b61e6df754d357706d8c66a8ae359d8eb02bbfa53f8",
    "pull/gamemodel.py": "2a2519a12ad4993da02ae6bdcdb6c86f2b5a6554ce93a702b550ecde17fb7d1f",
    "pull/sources.py": "36555cdbc55d73ba632d5adae1130288f4f532073857c642ac3ebc7e626b0061",
    "pull/news.py": "17ce1b3b6b72694e6b543bd767e287c26a9d1f6dd5dba2de6c873543036842e9",
}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def contract(root):
    root = Path(root).resolve()
    actual = {}
    for name, expected in ENGINE.items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > 2 << 20:
            raise ValueError("CURRENT_ENGINE_SCOPE")
        actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual[name] != expected:
            raise ValueError("UNRECOGNIZED_CLASSIC_CURRENT_SOURCE: " + name)
    return dict(schema_version=EXECUTION, model=MODEL, capture_schema=CAPTURE,
                normalized_stats_cache=CACHE, engine_sha256=actual,
                original_shadow_model=ORIGINAL_MODEL,original_shadow_source=ORIGINAL_SOURCE,
                original_shadow_procedure=SHADOW_PROCEDURE,
                grading_version="statistical-v3-identity-20261025")
