"""Closed main-only corrected classic execution; historical R0 stays immutable."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import math
import subprocess
import types

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
SCORING_SOURCE = "0f03af20226c17c54f27f930eccea162ab331c4c"
SCORING_TREE = "2a846d109df8daa385bad212b1a68af2831212a3"
SCORING_PULL_TREE = "6470d9ae3e3bee27651792979150f040c95deb17"
SCORING_BLOB = "5a6386ee77b142b7a3404cad5712f88403a39416"
NATIVE_FIELDS = {"schema_version", "mode", "evidence_label", "captured_at", "forecast_generated_at",
    "input_sha256", "engine_sha256", "engine_files", "code_commit", "model", "rows",
    "excluded_started_or_late_games", "execution_contract", "execution_contract_sha256"}
ROW_FIELDS = {"season", "week", "game_id", "kickoff", "player_id", "name", "team", "position", "category",
    "raw_projection", "adjusted_projection", "line", "line_from", "lean", "matchup_factor", "injury_at_capture",
    "top_over", "top_under", "probability", "expected_value", "price", "settlement_status", "source_timestamps_verified"}
CATEGORIES = {"pass_yd", "pass_td", "pass_cmp", "pass_att", "pass_int", "rush_yd", "rush_att",
              "rec", "rec_yd", "rush_rec_yd", "fpts", "anytime_td"}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def execution_contract():
    """Saved execution identity only; this does not qualify inputs or a week."""
    return dict(schema_version=EXECUTION, model=MODEL, capture_schema=CAPTURE,
                normalized_stats_cache=CACHE, engine_sha256=dict(ENGINE),
                original_shadow_model=ORIGINAL_MODEL, original_shadow_source=ORIGINAL_SOURCE,
                original_shadow_procedure=SHADOW_PROCEDURE,
                grading_version="statistical-v3-identity-20261025")

def _clock(value):
    if type(value) is not str:
        raise ValueError("CLASSIC_NATIVE_CLOCK")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("CLASSIC_NATIVE_CLOCK")
    return result.astimezone(timezone.utc)

def _hash(value, length=64):
    return type(value) is str and len(value) == length and all(c in "0123456789abcdef" for c in value)

def native_contract(payload):
    """Strict saved Classic1 observations, never original-input qualification.

    Source claims are compared with the closed old execution descriptor. Actual
    retained file/Git identities are the outer reader's responsibility. This
    reader neither records a forecast nor authenticates provider publication.
    """
    expected = execution_contract()
    if (type(payload) is not dict or set(payload) != NATIVE_FIELDS
            or payload.get("schema_version") != CAPTURE or payload.get("model") != MODEL
            or payload.get("mode") not in ("live", "replay")
            or payload.get("engine_files") != ENGINE or payload.get("engine_sha256") != digest(ENGINE)
            or canonical(payload.get("execution_contract")) != canonical(expected)
            or payload.get("execution_contract_sha256") != digest(expected)
            or not _hash(payload.get("input_sha256"))
            or (payload.get("code_commit") is not None or payload.get("mode") == "live")
                and not _hash(payload.get("code_commit"), 40)
            or payload.get("evidence_label") != ("LOCAL_PRE_GAME_CAPTURE_PUBLICATION_NOT_VERIFIED"
                if payload.get("mode") == "live" else "REPLAY_TEST_NOT_PROSPECTIVE")):
        raise ValueError("UNSUPPORTED_CLASSIC_SAVED_NATIVE")
    captured = _clock(payload["captured_at"])
    if _clock(payload["forecast_generated_at"]) > captured:
        raise ValueError("CLASSIC_NATIVE_REVERSED_CLOCK")
    rows, excluded = payload["rows"], payload["excluded_started_or_late_games"]
    if (type(rows) is not list or len(rows) > 50000 or type(excluded) is not list or len(excluded) > 64
            or any(type(value) is not str or not value.strip() or len(value) > 400 for value in excluded)
            or excluded != sorted(set(excluded))):
        raise ValueError("CLASSIC_NATIVE_POPULATION")
    identities, periods = [], set()
    for row in rows:
        if (type(row) is not dict or not ROW_FIELDS <= set(row)
                or set(row) - ROW_FIELDS - {"sleeper_observation"}
                or type(row["season"]) is not int or type(row["week"]) is not int or not 1 <= row["week"] <= 18
                or type(row["category"]) is not str or row["category"] not in CATEGORIES
                or row["position"] not in ("QB", "RB", "WR", "TE")
                or any(type(row[key]) is not str or not row[key].strip() or len(row[key]) > 400
                       for key in ("game_id", "player_id", "team", "name", "line_from"))
                or row["lean"] not in (None, "over", "under")
                or row["injury_at_capture"] is not None and (type(row["injury_at_capture"]) is not str or len(row["injury_at_capture"]) > 400)
                or any(type(row[key]) is not bool for key in ("top_over", "top_under"))
                or row["source_timestamps_verified"] is not False or row["settlement_status"] != "NOT_VERIFIED"
                or any(row[key] is not None for key in ("probability", "expected_value", "price"))
                or row["raw_projection"] is None and row["adjusted_projection"] is None
                or any(row[key] is not None and (type(row[key]) not in (int, float) or not math.isfinite(row[key]))
                       for key in ("raw_projection", "adjusted_projection", "line", "matchup_factor"))
                or _clock(row["kickoff"]) <= captured):
            raise ValueError("CLASSIC_NATIVE_ROW_CONTRACT")
        if "sleeper_observation" in row and (type(row["sleeper_observation"]) is not dict
                or len(canonical(row["sleeper_observation"])) > 16384):
            raise ValueError("CLASSIC_NATIVE_OPTIONAL_OBSERVATION")
        identities.append((row["game_id"], row["player_id"], row["category"]))
        periods.add((row["season"], row["week"]))
    if len(set(identities)) != len(identities) or identities != sorted(identities) or len(periods) > 1:
        raise ValueError("CLASSIC_NATIVE_DUPLICATE_OR_MIXED_POPULATION")
    return dict(ENGINE)

def scoring_objects(repository=None):
    """Fresh fixed commit/tree/blob closure, shared by reads and local transport."""
    root = Path(repository) if repository is not None else Path(__file__).resolve().parents[1]
    objects = {}
    def object(oid, kind, bound):
        command = ["git", "--no-replace-objects", "--no-lazy-fetch", "-C", str(root), "cat-file"]
        header = subprocess.check_output([*command, "--batch-check"], input=(oid+"\n").encode(),
                                         stderr=subprocess.PIPE, timeout=30).decode().split()
        if len(header) != 3 or header[:2] != [oid, kind] or not header[2].isdigit():
            raise ValueError("CLASSIC_SCORING_OBJECT_TYPE")
        size = int(header[2])
        if not 0 <= size <= bound:
            raise ValueError("CLASSIC_SCORING_OBJECT_BOUND")
        body = subprocess.check_output([*command, kind, oid], stderr=subprocess.PIPE, timeout=30)
        if len(body) != size or hashlib.sha1(kind.encode()+b" "+str(size).encode()+b"\0"+body).hexdigest() != oid:
            raise ValueError("CLASSIC_SCORING_OBJECT_IDENTITY")
        objects[oid] = (kind, body)
        return body
    def child(raw, name, mode, expected):
        at, found = 0, []
        while at < len(raw):
            try:
                sep, end = raw.index(b" ", at), raw.index(b"\0", at)
            except ValueError:
                raise ValueError("CLASSIC_SCORING_TREE_ENCODING") from None
            if sep >= end or end+21 > len(raw):
                raise ValueError("CLASSIC_SCORING_TREE_ENCODING")
            if raw[sep+1:end] == name:
                found.append((raw[at:sep], raw[end+1:end+21].hex()))
            at = end+21
        if found != [(mode, expected)]:
            raise ValueError("CLASSIC_SCORING_TREE_LINK")
    commit = object(SCORING_SOURCE, "commit", 65536)
    if commit.splitlines()[0] != b"tree "+SCORING_TREE.encode():
        raise ValueError("CLASSIC_SCORING_SOURCE_TREE")
    tree = object(SCORING_TREE, "tree", 1 << 20)
    child(tree, b"pull", b"40000", SCORING_PULL_TREE)
    pull = object(SCORING_PULL_TREE, "tree", 1 << 20)
    child(pull, b"scoring.py", b"100644", SCORING_BLOB)
    raw = object(SCORING_BLOB, "blob", 65536)
    if hashlib.sha256(raw).hexdigest() != ENGINE["pull/scoring.py"]:
        raise ValueError("CLASSIC_SCORING_CLOSED_BYTES")
    return objects

def scoring(repository=None):
    """Actual immutable old pure scoring bytes; no current-source substitution."""
    raw = scoring_objects(repository)[SCORING_BLOB][1]
    result = types.ModuleType("retained_classic_scoring")
    exec(compile(raw, "retained-classic-scoring", "exec"), result.__dict__)
    return result

def contract(root, *, model=MODEL):
    if model != MODEL:
        raise ValueError("UNRECOGNIZED_CLASSIC_MODEL")
    root = Path(root).resolve()
    actual = {}
    for name, expected in ENGINE.items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > 2 << 20:
            raise ValueError("CURRENT_ENGINE_SCOPE")
        actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual[name] != expected:
            raise ValueError("UNRECOGNIZED_CLASSIC_CURRENT_SOURCE: " + name)
    return execution_contract()
