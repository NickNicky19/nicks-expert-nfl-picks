"""Pregame selected-forecast gap rankings; canonical R0 records are read-only.

No model fitting, provider requests, probabilities inferred from points, or
historical selection backfills. Called by the existing serialized site writer.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import weekly_adaptive_overlay as overlay

VERSION = "weekly-selected-rankings-v1"
POINTER = "weekly-selected-rankings-pointer-v1"
LIMIT = 256 * 1024
POLICY = {
    "version": "selected-projection-gap-v1",
    "top_n": 12, "minimum_score": 0.35, "minimum_games": 2,
    "minimum_snap_share": 0.5,
    "minimum_projected_ppr": {"QB": 10, "RB": 6, "WR": 6, "TE": 6},
    "projection_line_ratio": [0.4, 2.5],
    "categories": {
        "pass_yd": {"lean": 8, "scale": 30, "minimum_line": 150.5},
        "pass_td": {"lean": 0.15, "scale": 0.6, "minimum_line": 0.5},
        "pass_cmp": {"lean": 0.8, "scale": 2.5, "minimum_line": 12.5},
        "pass_att": {"lean": 1, "scale": 3, "minimum_line": 20.5},
        "pass_int": {"lean": 0.12, "scale": 0.5, "minimum_line": 0.5},
        "rush_yd": {"lean": 4, "scale": 12, "minimum_line": 15.5},
        "rush_att": {"lean": 0.8, "scale": 3, "minimum_line": 6.5},
        "rec": {"lean": 0.3, "scale": 1.2, "minimum_line": 1.5},
        "rec_yd": {"lean": 4, "scale": 12, "minimum_line": 15.5},
        "rush_rec_yd": {"lean": 5, "scale": 15, "minimum_line": 25.5},
    },
    "unavailable": ["Out", "IR", "PUP", "Suspended", "NA", "Doubtful", "COV", "DNR"],
    "fallback": "same-opportunity R0 reference; unavailable is never zero",
    "meaning": "descriptive scaled forecast gap, not win probability or EV",
    "tie_order": ["absolute_score_desc", "game_id", "player_id", "category"],
}
POLICY_SHA = overlay.digest(POLICY)
CURRENT_MODEL = "sleeper-matchup-classic-fg-identity-v1"
CURRENT_POLICY = dict(POLICY, version="selected-projection-gap-classic-v1",
    fallback="same-opportunity reference identified by forecast_source and model_version; unavailable is never zero")
CURRENT_POLICY_SHA = overlay.digest(CURRENT_POLICY)
def policy_for(board):
    return CURRENT_POLICY if board.get('execution_model',{}).get('model')==CURRENT_MODEL else POLICY

ITEM_FIELDS = {"player_id", "game_id", "key", "direction", "line", "line_from", "adj", "score", "over", "n",
               "forecast_source", "product", "model_version", "selected_row_sha256", "selected_row_canonical", "selected_at", "kickoff_utc"}
POINTER_FIELDS = {"schema_version", "path", "sha256", "bytes", "display_board_sha256", "overlay_sha256", "published_at"}
FALLBACK_FIELDS = {"started_without_selected_record", "unavailable_forecast", "expired_before_kickoff"}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def identity(item):
    return item["game_id"], item["player_id"], item["key"], item["direction"]


def order(item):
    return (-abs(item["score"]), item["game_id"], item["player_id"], item["key"])


def effective(player, prop, doc, now):
    """Keep the forecast's actual functional; never treat a point as a CDF."""
    key = (player["game_id"], player["id"], prop["key"])
    row = next((r for r in doc["rows"] if overlay.key(r) == key), None)
    if row is not None and overlay.utc(row["valid_until_utc"]) > overlay.utc(now):
        return row["forecast_value"], "SELECTED", row["product"], row["model_version"], overlay.digest(row), overlay.canonical(row).decode()
    value = prop.get("adj")
    if number(value):
        return (value,"CURRENT_BASELINE","reference_point",CURRENT_MODEL,None,None) if player.get("reference_model")==CURRENT_MODEL else (value,"R0_FALLBACK","reference_point",None,None,None)
    return None


def eligible(player):
    minimum = POLICY["minimum_projected_ppr"].get(player.get("pos"))
    return (minimum is not None and player.get("injury") not in POLICY["unavailable"]
            and number(player.get("games_this_season")) and player["games_this_season"] >= POLICY["minimum_games"]
            and number(player.get("snap_share")) and player["snap_share"] >= POLICY["minimum_snap_share"]
            and number(player.get("proj_ppr")) and player["proj_ppr"] >= minimum)


def validate_item(item, offers, selected, *, frozen=False):
    if set(item) != ITEM_FIELDS: raise ValueError("ranking item fields")
    k = item["game_id"], item["player_id"], item["key"]
    if k not in offers or item["key"] not in POLICY["categories"]: raise ValueError("ranking opportunity")
    player, game, prop = offers[k]
    cat = POLICY["categories"][item["key"]]
    if (item["direction"] not in {"over", "under"} or item["line_from"] not in {"dk", "sleeper"}
            or not all(number(item[k]) for k in ("line", "adj", "score", "over", "n"))
            or item["line"] != prop.get("line") or item["line_from"] != prop.get("line_from")
            or type(item["over"]) is not int or type(item["n"]) is not int or not 0 <= item["over"] <= item["n"]
            or item["kickoff_utc"] != game["kickoff"] or overlay.utc(item["selected_at"]) >= overlay.utc(game["kickoff"])):
        raise ValueError("ranking source/line/clock")
    score = (item["adj"] - item["line"]) / cat["scale"]
    if (not math.isclose(item["score"], score, rel_tol=1e-12, abs_tol=1e-12)
            or abs(score) < POLICY["minimum_score"]
            or (item["direction"] == "over") != (score > 0)):
        raise ValueError("ranking score")
    if item["forecast_source"] == "SELECTED":
        row = selected.get(k)
        if (row is None or item["adj"] != row["forecast_value"] or item["product"] != row["product"]
                or item["model_version"] != row["model_version"] or item["selected_row_sha256"] != overlay.digest(row)
                or item["selected_row_canonical"] != overlay.canonical(row).decode()
                or overlay.utc(item["selected_at"]) >= overlay.utc(row["valid_until_utc"])):
            raise ValueError("ranking selected identity")
    elif item["forecast_source"] in {"R0_FALLBACK","CURRENT_BASELINE"}:
        current=player.get("reference_model")==CURRENT_MODEL
        if item["forecast_source"] != ("CURRENT_BASELINE" if current else "R0_FALLBACK"):raise ValueError("ranking reference model")
        if (item["adj"] != prop.get("adj") or item["product"] != "reference_point"
                or item["model_version"] != (CURRENT_MODEL if current else None) or item["selected_row_sha256"] is not None or item["selected_row_canonical"] is not None):
            raise ValueError("ranking R0 identity")
    else: raise ValueError("ranking forecast source")
    return item


def prepare(board, board_hash, doc, overlay_hash, *, now, website_source_sha, previous=None, previous_receipt=None):
    overlay.validate_overlay(doc, board, board_hash)
    if overlay.digest(doc) != overlay_hash: raise ValueError("ranking overlay hash")
    offers = overlay.board_offers(board)
    selected = {overlay.key(r): r for r in doc["rows"]}
    games = {g["id"]: g for g in board["games"]}
    started = {g["id"] for g in board["games"] if g.get("state") != "pre" or overlay.utc(g["kickoff"]) <= overlay.utc(now)}
    picks = {"over": [], "under": []}; proofs = []; fallback = {"started_without_selected_record": 0, "unavailable_forecast": 0, "expired_before_kickoff": 0}
    if previous is not None:
        if (previous["schema_version"] != VERSION or previous["policy"] not in ([POLICY,CURRENT_POLICY]if policy_for(board)==CURRENT_POLICY else [POLICY]) or previous["policy_sha256"] != overlay.digest(previous["policy"])
                or (previous["season"], previous["week"]) != (board["season"], board["week"])):
            previous = None
    if previous is not None:
        if previous_receipt is None or previous_receipt["sha256"] != overlay.digest(previous):
            raise ValueError("ranking previous receipt")
        old_proofs = {tuple(p["key"]): p for p in previous["frozen_proofs"]}
        for side in picks:
            for old in previous["picks"][side]:
                if old["game_id"] not in started: continue
                if old["forecast_source"] == "SELECTED":
                    old_row = json.loads(old["selected_row_canonical"])
                    overlay.validate_row(old_row, offers)
                    validate_item(old, offers, {overlay.key(old_row): old_row}, frozen=True)
                    if overlay.utc(old_row["valid_until_utc"]) < overlay.utc(old["kickoff_utc"]):
                        fallback["expired_before_kickoff"] += 1
                        continue  # The new overlay correctly omitted this expired row.
                validate_item(old, offers, selected, frozen=True)
                proof = old_proofs.get(identity(old))
                if proof is None:
                    proof = {"key": list(identity(old)), "receipt_sha256": overlay.digest(previous_receipt),
                             "persisted_at": previous_receipt["published_at"]}
                if overlay.utc(proof["persisted_at"]) >= overlay.utc(old["kickoff_utc"]):
                    raise ValueError("ranking late previous selection")
                picks[side].append(copy.deepcopy(old)); proofs.append(copy.deepcopy(proof))
    fallback["started_without_selected_record"] = len(started - {p["game_id"] for side in picks.values() for p in side})
    fresh = {"over": [], "under": []}
    for player in board["players"]:
        if player["game_id"] in started or not eligible(player): continue
        best = {}
        for prop in player.get("props", []):
            cat = POLICY["categories"].get(prop["key"])
            if cat is None or prop.get("line_from") not in {"dk", "sleeper"} or not number(prop.get("line")): continue
            line = prop["line"]
            forecast = effective(player, prop, doc, now)
            if forecast is None: fallback["unavailable_forecast"] += 1; continue
            value, source, product, model, row_sha, row_body = forecast
            if type(prop.get("over")) is not int or type(prop.get("n")) is not int or not 0 <= prop["over"] <= prop["n"]: continue
            if line < cat["minimum_line"] or not POLICY["projection_line_ratio"][0] <= value / line <= POLICY["projection_line_ratio"][1]: continue
            gap = value - line
            if abs(gap) <= cat["lean"]: continue
            score = gap / cat["scale"]
            if abs(score) < POLICY["minimum_score"]: continue
            side = "over" if gap > 0 else "under"
            item = dict(player_id=player["id"], game_id=player["game_id"], key=prop["key"], direction=side,
                        line=line, line_from=prop["line_from"], adj=value, score=score,
                        over=prop["over"], n=prop["n"], forecast_source=source, product=product,
                        model_version=model, selected_row_sha256=row_sha, selected_row_canonical=row_body, selected_at=now,
                        kickoff_utc=games[player["game_id"]]["kickoff"])
            validate_item(item, offers, selected)
            if side not in best or order(item) < order(best[side]): best[side] = item
        for side, item in best.items(): fresh[side].append(item)
    for side in picks:
        fresh[side].sort(key=order)
        picks[side] += fresh[side][:max(0, POLICY["top_n"] - len(picks[side]))]
        picks[side].sort(key=order)
    result = dict(schema_version=VERSION, policy=copy.deepcopy(policy_for(board)), policy_sha256=overlay.digest(policy_for(board)),
                  season=board["season"], week=board["week"], display_board_sha256=board_hash,
                  overlay_sha256=overlay_hash, prepared_at=now, website_source_sha=website_source_sha,
                  picks=picks, frozen_proofs=proofs, fallback_counts=fallback)
    if len(overlay.canonical(result)) > LIMIT: raise ValueError("ranking artifact byte bound")
    return result


def validate_pointer(pointer):
    """Use the same closed receipt contract for current and frozen origins."""
    if (set(pointer) != POINTER_FIELDS or pointer["schema_version"] != POINTER
            or not all(overlay.hash64(pointer[k]) for k in ("sha256", "display_board_sha256", "overlay_sha256"))
            or type(pointer["bytes"]) is not int or not 0 < pointer["bytes"] <= LIMIT
            or pointer["path"] != "weekly-selected-rankings/" + pointer["sha256"] + ".json"):
        raise ValueError("ranking pointer scope")
    overlay.utc(pointer["published_at"])


def read_public(root):
    root = Path(root)
    pointer, _ = overlay.read_bound(root / "weekly-selected-rankings.json", limit=4096)
    validate_pointer(pointer)
    name = pointer["path"]
    doc, body_sha = overlay.read_bound(root / name, pointer["sha256"], limit=LIMIT)
    if (pointer["bytes"] != len((root / name).read_bytes()) or body_sha != overlay.digest(doc)
            or (pointer["display_board_sha256"], pointer["overlay_sha256"]) != (doc["display_board_sha256"], doc["overlay_sha256"])):
        raise ValueError("ranking pointer binding")
    return pointer, doc


def validate_origin_policy(original, receipt, item, board):
    """Authenticate the policy used by this item's original receipt.

    The classic writer has its own reference identity. A frozen item keeps the
    exact earlier policy, source, model and content; a policy name alone cannot
    authorize a different reference stream or changed thresholds.
    """
    allowed = (POLICY, CURRENT_POLICY) if policy_for(board) == CURRENT_POLICY else (POLICY,)
    if (original.get("schema_version") != VERSION
            or (original.get("season"), original.get("week")) != (board["season"], board["week"])
            or not any(overlay.canonical(original.get("policy")) == overlay.canonical(policy)
                       and original.get("policy_sha256") == overlay.digest(policy) for policy in allowed)
            or original.get("display_board_sha256") != receipt.get("display_board_sha256")
            or original.get("overlay_sha256") != receipt.get("overlay_sha256")
            or not overlay.utc(original["prepared_at"]) <= overlay.utc(receipt["published_at"])):
        raise ValueError("ranking original policy binding")
    source = item["forecast_source"]
    if source == "CURRENT_BASELINE":
        if original["policy"] != CURRENT_POLICY or item["model_version"] != CURRENT_MODEL:
            raise ValueError("ranking original current reference policy")
    elif source == "R0_FALLBACK":
        if original["policy"] != POLICY or item["model_version"] is not None:
            raise ValueError("ranking original R0 reference policy")
    elif source != "SELECTED":
        raise ValueError("ranking original forecast source")


def validate_document(doc, pointer, board, board_hash, selected_doc, *, root=None):
    fields = {"schema_version", "policy", "policy_sha256", "season", "week", "display_board_sha256", "overlay_sha256",
              "prepared_at", "website_source_sha", "picks", "frozen_proofs", "fallback_counts"}
    if (set(doc) != fields or doc["schema_version"] != VERSION or overlay.canonical(doc["policy"]) != overlay.canonical(policy_for(board))
            or doc["policy_sha256"] != overlay.digest(policy_for(board)) or (doc["season"], doc["week"]) != (board["season"], board["week"])
            or doc["display_board_sha256"] != board_hash or doc["overlay_sha256"] != overlay.digest(selected_doc)
            or set(doc["picks"]) != {"over", "under"} or not isinstance(doc["frozen_proofs"], list)
            or len(doc["frozen_proofs"]) > 2 * POLICY["top_n"]
            or type(doc["website_source_sha"]) is not str or len(doc["website_source_sha"]) != 40
            or any(c not in "0123456789abcdef" for c in doc["website_source_sha"])
            or doc["website_source_sha"] != selected_doc.get("website_source_sha")
            or not isinstance(doc["fallback_counts"], dict) or set(doc["fallback_counts"]) != FALLBACK_FIELDS
            or any(type(v) is not int or v < 0 for v in doc["fallback_counts"].values())
            or not overlay.utc(doc["prepared_at"]) <= overlay.utc(pointer["published_at"])):
        raise ValueError("ranking document contract")
    offers = overlay.board_offers(board); selected = {overlay.key(r): r for r in selected_doc["rows"]}
    proofs = {}
    for proof in doc["frozen_proofs"]:
        if set(proof) != {"key", "receipt_sha256", "persisted_at"} or not overlay.hash64(proof["receipt_sha256"]) or len(proof["key"]) != 4:
            raise ValueError("ranking proof contract")
        k = tuple(proof["key"])
        if k in proofs: raise ValueError("ranking duplicate proof")
        proofs[k] = proof
    used = set()
    for side, items in doc["picks"].items():
        if not isinstance(items, list) or len(items) > POLICY["top_n"] or items != sorted(items, key=order):
            raise ValueError("ranking order/size")
        seen = set()
        for item in items:
            if item["direction"] != side: raise ValueError("ranking side mismatch")
            validate_item(item, offers, selected)
            k = identity(item); proof = proofs.get(k); used.add(k)
            player_game = item["game_id"], item["player_id"]
            if player_game in seen: raise ValueError("ranking duplicate player/side")
            seen.add(player_game)
            completed = proof["persisted_at"] if proof else pointer["published_at"]
            if not overlay.utc(item["selected_at"]) <= overlay.utc(completed) < overlay.utc(item["kickoff_utc"]):
                raise ValueError("ranking durable completion clock")
            if item["forecast_source"] == "SELECTED":
                expiry = overlay.utc(json.loads(item["selected_row_canonical"])["valid_until_utc"])
                if overlay.utc(completed) >= expiry or proof and expiry < overlay.utc(item["kickoff_utc"]):
                    raise ValueError("ranking expired before completion/freeze")
    if set(proofs) - used: raise ValueError("ranking unused proof")
    paths = {"weekly-selected-rankings.json", pointer["path"], "weekly-selected-rankings/" + overlay.digest(pointer) + ".receipt.json"}
    if root is not None:
        root = Path(root)
        current_receipt, _ = overlay.read_bound(root / ("weekly-selected-rankings/" + overlay.digest(pointer) + ".receipt.json"), overlay.digest(pointer), limit=4096)
        if current_receipt != pointer: raise ValueError("ranking current receipt")
        for k, proof in proofs.items():
            receipt_path = "weekly-selected-rankings/" + proof["receipt_sha256"] + ".receipt.json"
            receipt, _ = overlay.read_bound(root / receipt_path, proof["receipt_sha256"], limit=4096)
            validate_pointer(receipt)
            if receipt["schema_version"] != POINTER or receipt["published_at"] != proof["persisted_at"] or receipt["path"] != "weekly-selected-rankings/" + receipt["sha256"] + ".json":
                raise ValueError("ranking original receipt binding")
            original, original_sha = overlay.read_bound(root / receipt["path"], receipt["sha256"], limit=LIMIT)
            if (set(original) != fields or set(original["picks"]) != {"over", "under"}
                    or any(type(items) is not list for items in original["picks"].values())
                    or original_sha != overlay.digest(original)
                    or receipt["bytes"] != len(overlay.canonical(original))
                    or type(original["website_source_sha"]) is not str or len(original["website_source_sha"]) != 40
                    or any(c not in "0123456789abcdef" for c in original["website_source_sha"])):
                raise ValueError("ranking original body binding")
            old = [(side, i) for side, items in original["picks"].items() for i in items if identity(i) == k]
            current = next(i for side in doc["picks"].values() for i in side if identity(i) == k)
            if len(old) != 1 or old[0] != (current["direction"], current):
                raise ValueError("ranking original membership changed")
            validate_origin_policy(original, receipt, old[0][1], board)
            validate_item(old[0][1], offers, selected, frozen=True)
            paths.update({receipt_path, receipt["path"]})
    return paths


def write_public(doc, root, atomic_json, *, clock=lambda: datetime.now(timezone.utc).isoformat()):
    root = Path(root)
    body = overlay.canonical(doc); sha = overlay.sha(body)
    target = root / "weekly-selected-rankings" / (sha + ".json")
    if target.is_symlink() or any(p.is_symlink() for p in target.parents): raise ValueError("ranking path")
    if target.exists():
        if target.read_bytes() != body: raise ValueError("ranking immutable collision")
    else: atomic_json(target, doc)
    if target.read_bytes() != body: raise ValueError("ranking durable readback")
    persisted = clock(); proofs = {tuple(p["key"]): p for p in doc["frozen_proofs"]}
    for items in doc["picks"].values():
        for item in items:
            proof = proofs.get(identity(item))
            completion = proof["persisted_at"] if proof else persisted
            if not overlay.utc(item["selected_at"]) <= overlay.utc(completion) < overlay.utc(item["kickoff_utc"]):
                raise ValueError("ranking crossed kickoff before durable completion")
            if item["forecast_source"] == "SELECTED" and overlay.utc(completion) >= overlay.utc(json.loads(item["selected_row_canonical"])["valid_until_utc"]):
                raise ValueError("ranking expired before durable completion")
    pointer = dict(schema_version=POINTER, path="weekly-selected-rankings/" + sha + ".json", sha256=sha,
                   bytes=len(body), display_board_sha256=doc["display_board_sha256"], overlay_sha256=doc["overlay_sha256"], published_at=persisted)
    receipt = root / "weekly-selected-rankings" / (overlay.digest(pointer) + ".receipt.json")
    if receipt.exists():
        if receipt.read_bytes() != overlay.canonical(pointer): raise ValueError("ranking receipt collision")
    else: atomic_json(receipt, pointer)
    atomic_json(root / "weekly-selected-rankings.json", pointer)
    restored, value = read_public(root)
    if restored != pointer or value != doc: raise ValueError("ranking pointer readback")
    return pointer


def prepare_writer(root, board, board_hash, doc, *, website_source_sha, atomic_json):
    data = Path(root) / "output/data"
    previous = receipt = None
    if (data / "weekly-selected-rankings.json").exists():
        receipt, previous = read_public(data)  # Invalid prior evidence never silently disappears.
    now = datetime.now(timezone.utc).isoformat()
    result = prepare(board, board_hash, doc, overlay.digest(doc), now=now,
                     website_source_sha=website_source_sha, previous=previous, previous_receipt=receipt)
    pointer = write_public(result, data, atomic_json)
    validate_document(result, pointer, board, board_hash, doc, root=data)
    return pointer
