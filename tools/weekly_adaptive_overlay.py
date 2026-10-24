"""Portable provisional display overlay. Never changes the reference board.

The same bytes are proposed as the website's tools/weekly_adaptive_overlay.py.
Only selected derived fields are public; source panels/models stay private.
Legacy R0 field/state names are retained as encoding identifiers. Policy V3
separates the corrected current reference from the immutable historical R0
freeze; an overlay producer identity is not current-source qualification.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

VERSION = "weekly-adaptive-public-overlay-v1"
POINTER = "weekly-adaptive-overlay-pointer-v1"
REVIEW = "weekly-adaptive-publication-review-v1"
MAX_BYTES = 4 * 1024 * 1024
COUNTS = {"pass_td", "pass_cmp", "pass_att", "pass_int", "rush_att", "rec"}
YARDS = {"pass_yd", "rush_yd", "rec_yd", "rush_rec_yd"}
PRODUCTS = {**{k: ("point_mean", "expected_mean") for k in COUNTS},
            **{k: ("point_median", "intended_median") for k in YARDS},
            "anytime_td": ("binary_probability", "event_probability")}
ROW_FIELDS = ("player_id", "game_id", "category", "method_id", "model_version", "procedure_version",
              "product", "prediction_functional", "forecast_value", "horizon", "source_cutoff_utc",
              "issued_at", "persistence_completed_at", "kickoff_utc", "valid_until_utc",
              "selection_sha256", "source_policy_sha256", "query_source_sha256")
PUBLIC_FIELDS = set(ROW_FIELDS) | {"first_prepared_at"}
FALLBACK_REASONS = {"malformed_candidate", "candidate_outside_board_R0", "invalid_previous_overlay_R0",
                   "started_R0_frozen_no_new_selection", "PPR_or_unsupported_R0", "publication_not_approved_R0",
                   "missing_or_duplicate_candidate_R0", "incompatible_stale_or_late_R0"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(body): return hashlib.sha256(body).hexdigest()
def digest(value): return sha(canonical(value))


def utc(value):
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None: raise ValueError("explicit UTC-aware clock required")
    return stamp.astimezone(timezone.utc)


def hash64(value):
    return isinstance(value, str) and len(value) == 64 and all(x in "0123456789abcdef" for x in value)


def key(row): return row["game_id"], row["player_id"], row["category"]


def board_offers(board):
    """Exact website IDs only. No fuzzy names, implicit aliases or new players."""
    games = {g["id"]: g for g in board["games"]}
    if len(games) != len(board["games"]): raise ValueError("duplicate board game")
    result = {}
    for player in board["players"]:
        game = games.get(player["game_id"])
        if game is None: raise ValueError("board player outside game population")
        for prop in player.get("props", []):
            k = player["game_id"], player["id"], prop["key"]
            if k in result: raise ValueError("duplicate board offer")
            result[k] = (player, game, prop)
    return result


def board_contract(board):
    offers = board_offers(board)
    # Only fields retained by both normal and public-stage reference boards. This is a
    # packaging equivalence check, not a substitute for either physical hash.
    return dict(season=board["season"], week=board["week"], offers=[dict(
        player_id=k[1], game_id=k[0], category=k[2], kickoff=v[1]["kickoff"],
        team=v[0]["team"], opponent=v[0]["opp"],
        r0={name: v[2].get(name) for name in ("proj", "adj", "td_chance", "line", "line_from")})
        for k, v in sorted(offers.items())])


def validate_row(row, offers):
    import math
    if set(row) != PUBLIC_FIELDS: raise ValueError("unapproved public row field")
    k = key(row)
    if k not in offers: raise ValueError("player/game/category absent from R0 board")
    _, game, _ = offers[k]
    if row["category"] not in PRODUCTS: raise ValueError("PPR or unsupported category")
    if (row["product"], row["prediction_functional"]) != PRODUCTS[row["category"]]:
        raise ValueError("typed forecast product mismatch; no point-to-probability or blend-median conversion")
    value = row["forecast_value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite selected forecast required")
    if row["category"] in COUNTS and value < 0: raise ValueError("negative count mean")
    if row["category"] == "anytime_td" and not 0 <= value <= 1: raise ValueError("invalid event probability")
    if row["horizon"] != "player_game" or utc(row["kickoff_utc"]) != utc(game["kickoff"]):
        raise ValueError("horizon or kickoff mismatch")
    for name in ("model_version", "procedure_version", "selection_sha256", "source_policy_sha256", "query_source_sha256"):
        if not hash64(row[name]): raise ValueError("exact version/source hash required")
    if not isinstance(row["method_id"], str) or not row["method_id"] or len(row["method_id"]) > 100:
        raise ValueError("declared method required")
    issued, persisted, cutoff, kickoff, prepared, expires = map(utc, (
        row["issued_at"], row["persistence_completed_at"], row["source_cutoff_utc"], row["kickoff_utc"],
        row["first_prepared_at"], row["valid_until_utc"]))
    if not issued <= persisted <= cutoff < kickoff or not persisted <= prepared < kickoff or not prepared < expires <= kickoff:
        raise ValueError("late/incoherent original issuance, persistence, source cutoff or expiry")
    return row


def validate_overlay(doc, board, board_sha256):
    required = {"schema_version", "registration_id", "state", "season", "week", "canonical_board_sha256",
                "display_board_sha256", "board_contract_sha256", "prepared_at", "packaged_at",
                "website_source_sha", "publication_review_sha256", "rows", "frozen_rows", "fallback_counts"}
    if set(doc) != required or doc["schema_version"] != VERSION or doc["registration_id"] != "weekly-adaptive-release-v1":
        raise ValueError("unknown overlay contract")
    if doc["state"] not in {"PROVISIONAL", "DISABLED_USE_R0"} or (doc["state"] == "DISABLED_USE_R0" and doc["rows"]):
        raise ValueError("invalid provisional state")
    if (doc["season"], doc["week"]) != (board["season"], board["week"]) or doc["display_board_sha256"] != board_sha256:
        raise ValueError("stale or different visible R0 board")
    if doc["board_contract_sha256"] != digest(board_contract(board)) or len(doc["rows"]) > 5000:
        raise ValueError("changed board offers or row bound")
    if not all(hash64(doc[k]) for k in ("canonical_board_sha256", "display_board_sha256", "board_contract_sha256", "publication_review_sha256")):
        raise ValueError("overlay provenance hash missing")
    if not isinstance(doc["website_source_sha"], str) or len(doc["website_source_sha"]) != 40 or any(c not in "0123456789abcdef" for c in doc["website_source_sha"]):
        raise ValueError("actual website source identity required")
    if utc(doc["packaged_at"]) < utc(doc["prepared_at"]): raise ValueError("packaging precedes preparation")
    if (not isinstance(doc["fallback_counts"], dict) or not set(doc["fallback_counts"]) <= FALLBACK_REASONS
            or any(type(v) is not int or v < 0 for v in doc["fallback_counts"].values())):
        raise ValueError("unapproved public fallback field")
    offers, seen = board_offers(board), set()
    for row in doc["rows"]:
        validate_row(row, offers)
        if key(row) in seen: raise ValueError("duplicate selected board offer/version")
        seen.add(key(row))
    if not isinstance(doc["frozen_rows"], list) or any(set(item) != {"key", "row_sha256"} or tuple(item["key"]) not in seen or item["row_sha256"] != digest(next(r for r in doc["rows"] if key(r) == tuple(item["key"]))) for item in doc["frozen_rows"]):
        raise ValueError("changed frozen selected row")
    return doc


def prepare_overlay(board, board_sha256, selected, review, *, website_source_sha, prepared_at, previous=None):
    """Pure projection; all offers stay R0 unless an admissible selected row exists."""
    now = utc(prepared_at); offers = board_offers(board); counters = {}; rows = []; frozen = []
    def count(reason): counters[reason] = counters.get(reason, 0) + 1
    if not isinstance(selected, dict): selected = {}
    if not isinstance(review, dict): review = {}
    try: selected_hash = digest(selected); digest(review)
    except (ValueError, TypeError): selected, review, selected_hash = {}, {}, digest({})
    approved = (review.get("schema_version") == REVIEW and review.get("approved") is True
        and review.get("selected_input_sha256") == selected_hash
        and review.get("website_source_sha") == website_source_sha)
    if not isinstance(selected.get("rows", []), list) or len(selected.get("rows", [])) > 5000: approved = False
    candidates = {}
    if approved:
        for row in selected.get("rows", []):
            try:
                if key(row) not in offers: count("candidate_outside_board_R0"); continue
                candidates.setdefault(key(row), []).append(row)
            except (KeyError, TypeError): count("malformed_candidate")
    prior = {}
    if isinstance(previous, dict):
        # Current R0 bytes may legitimately advance; prior selected row clocks
        # and exact identities must still validate against this same board scope.
        if previous.get("schema_version") == VERSION and (previous.get("season"), previous.get("week")) == (board["season"], board["week"]):
            for row in previous.get("rows", []):
                try: validate_row(row, offers)
                except (KeyError, TypeError, ValueError): count("invalid_previous_overlay_R0"); continue
                if key(row) in prior: raise ValueError("duplicate prior selected row")
                prior[key(row)] = row
    for k, (_, game, _) in sorted(offers.items()):
        started = game.get("state") != "pre" or utc(game["kickoff"]) <= now
        if started:
            old = prior.get(k)
            if old and utc(old["valid_until_utc"]) == utc(game["kickoff"]):
                rows.append(copy.deepcopy(old)); frozen.append(dict(key=list(k), row_sha256=digest(old)))
            else: count("started_R0_frozen_no_new_selection")
            continue
        if k[2] not in PRODUCTS: count("PPR_or_unsupported_R0"); continue
        candidates_here = candidates.get(k, [])
        if not approved: count("publication_not_approved_R0"); continue
        if len(candidates_here) != 1: count("missing_or_duplicate_candidate_R0"); continue
        try:
            source = candidates_here[0]
            if ((source.get("season"), source.get("week")) != (board["season"], board["week"])
                    or source.get("team") != offers[k][0]["team"] or source.get("opponent") != offers[k][0]["opp"]
                    or source.get("evidence_lane") != "original_pregame" or source.get("operational_eligible") is not True):
                raise ValueError("reconstruction or unqualified operational source")
            row = {name: source[name] for name in ROW_FIELDS}
            row["first_prepared_at"] = prepared_at
            validate_row(row, offers)
            if now >= utc(row["valid_until_utc"]): raise ValueError("stale selected forecast")
            rows.append(row)
        except (KeyError, TypeError, ValueError): count("incompatible_stale_or_late_R0")
    doc = dict(schema_version=VERSION, registration_id="weekly-adaptive-release-v1",
        state="PROVISIONAL" if rows else "DISABLED_USE_R0", season=board["season"], week=board["week"],
        canonical_board_sha256=board_sha256, display_board_sha256=board_sha256,
        board_contract_sha256=digest(board_contract(board)), prepared_at=prepared_at, packaged_at=prepared_at,
        website_source_sha=website_source_sha, publication_review_sha256=digest(review), rows=rows,
        frozen_rows=frozen, fallback_counts=counters)
    validate_overlay(doc, board, board_sha256)
    return doc


def repackage(doc, canonical_board, canonical_sha, display_board, display_sha, *, packaged_at):
    validate_overlay(doc, canonical_board, canonical_sha)
    if doc["canonical_board_sha256"] != canonical_sha or board_contract(canonical_board) != board_contract(display_board):
        raise ValueError("public stage changed original R0 forecast/line/identity contract")
    result = copy.deepcopy(doc)
    result.update(display_board_sha256=display_sha, packaged_at=packaged_at)
    return validate_overlay(result, display_board, display_sha)


def read_bound(path, expected=None, *, limit=MAX_BYTES):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit: raise ValueError("bounded plain file required")
    with path.open("rb") as stream:
        body = stream.read(limit + 1)
    if len(body) > limit: raise ValueError("bounded plain file required")
    if expected is not None and sha(body) != expected: raise ValueError("input hash changed")
    return json.loads(body), sha(body)


def read_public(root):
    root = Path(root)
    pointer, _ = read_bound(root / "data/weekly-adaptive-overlay.json")
    fields = {"schema_version", "path", "sha256", "bytes", "display_board_sha256"}
    if (set(pointer) != fields or pointer["schema_version"] != POINTER or not hash64(pointer["sha256"])
            or pointer["path"] != "data/weekly-adaptive/" + pointer["sha256"] + ".json"
            or type(pointer["bytes"]) is not int or not 0 < pointer["bytes"] <= MAX_BYTES):
        raise ValueError("invalid overlay pointer")
    path = root / pointer["path"]
    if path.stat().st_size != pointer["bytes"]: raise ValueError("overlay descriptor length changed")
    doc, _ = read_bound(path, pointer["sha256"])
    return pointer, doc


def validate_public_root(output):
    """Validate the new public graph freshly, including after the actual copy."""
    output = Path(output)
    allowed = {"weekly-adaptive-overlay.js"}
    if not (output / "data/weekly-adaptive-overlay.json").exists(): return allowed
    pointer, doc = read_public(output)
    board, board_sha = read_bound(output / "data/week.json", limit=16 * 1024 * 1024)
    validate_overlay(doc, board, board_sha)
    if pointer["display_board_sha256"] != board_sha: raise ValueError("overlay pointer has a different R0 board")
    return allowed | {"data/weekly-adaptive-overlay.json", pointer["path"]}


def stage_assets(root):
    """New isolated asset allowlist, after the existing full R0 checks."""
    return validate_public_root(Path(root) / "output")


def private_input_path(root, value):
    base = (Path(root) / "data/weekly-adaptive-input").resolve()
    result = (Path(root) / value).resolve()
    if not result.is_relative_to(base): raise ValueError("overlay input must stay in its private mounted namespace")
    return result


def write_public(doc, data_root, atomic_json):
    """Called only by the existing writer. No canonical R0 path is writable."""
    root = Path(data_root); body = canonical(doc)
    if len(body) > MAX_BYTES: raise ValueError("public overlay exceeds finite byte cap")
    name = sha(body); target = root / "weekly-adaptive" / (name + ".json")
    if root.is_symlink() or target.parent.is_symlink() or target.is_symlink(): raise ValueError("symlink public destination")
    if target.exists():
        if target.read_bytes() != body: raise ValueError("immutable overlay collision")
    else:
        # Existing website atomic_json is reused. Verify its actual serialization
        # and hash the physical bytes, rather than assuming canonical formatting.
        atomic_json(target, doc)
        actual = target.read_bytes()
        if actual != body:
            # Hash-addressed names require this exact serializer contract.
            raise ValueError("publisher serializer differs from reviewed canonical bytes")
    target.chmod(0o644)
    pointer = dict(schema_version=POINTER, path="data/weekly-adaptive/" + name + ".json",
                   sha256=name, bytes=len(body), display_board_sha256=doc["display_board_sha256"])
    atomic_json(root / "weekly-adaptive-overlay.json", pointer)
    (root / "weekly-adaptive-overlay.json").chmod(0o644)
    return pointer


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--website-source-sha", required=True)
    p.add_argument("--feed-policy", type=Path)
    p.add_argument("--feed-policy-sha256")
    args = p.parse_args(); root = args.root
    # This import is only used by the website's existing leased writer entrypoint.
    from reliability import atomic_json
    now = datetime.now(timezone.utc).isoformat()
    source = root / "output/data/weekly-adaptive-overlay.json"
    descriptor = root / "data/weekly-adaptive-input/approved-input.json"
    if not source.exists() and not descriptor.exists() and args.feed_policy is None:
        return  # Inert default: normal R0 build/publication needs no overlay input.
    board, board_sha = read_bound(root / "output/data/week.json", limit=16 * 1024 * 1024)
    selected, review, previous = {}, {}, None
    if source.exists():
        try: pointer, previous = read_public(root / "output")
        except (OSError, ValueError, TypeError, KeyError): previous = None
    if args.feed_policy is not None:
        from weekly_public_feed import prepare_writer
        selected, review = prepare_writer(root, args.feed_policy, args.feed_policy_sha256, board,
            website_source_sha=args.website_source_sha, now=now, atomic_json=atomic_json)
    elif descriptor.exists():
        try:
            spec, _ = read_bound(descriptor)
            selected, _ = read_bound(private_input_path(root, spec["selected_path"]), spec["selected_sha256"])
            review, _ = read_bound(private_input_path(root, spec["review_path"]), spec["review_sha256"])
        except (OSError, ValueError, TypeError, KeyError): selected, review = {}, {}
    doc = prepare_overlay(board, board_sha, selected, review, website_source_sha=args.website_source_sha,
                          prepared_at=now, previous=previous)
    write_public(doc, root / "output/data", atomic_json)


if __name__ == "__main__": main()
