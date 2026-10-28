"""Explicit partial-week model-input reproduction. Never a strict fallback.

No provider I/O occurs here. Complete original boards and immutable inputs stay
in the existing verification/forward lanes. A completion marker qualifies only
an intact, source-revalidated bundle; an orphan native receipt does not qualify.
"""
import copy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import statistics

import verify
import matchup
from evidence import read, referenced, write
from reliability import (IntegrityError, capture, digest, engine_hashes, load_json,
                         make_payload, stamp, utc, validate)
from source_evidence import verified_status

VERSION = "partial-week-input-reproduction-v1"
PLAN_VERSION = "partial-week-cutover-plan-v1"
REGISTRATION_VERSION = "partial-week-registration-v1"
COMPLETION_VERSION = "partial-week-completion-v1"
SCOPE_LANE = "verification/partial-scopes"
COMPLETION_LANE = "verification/partial-completions"
FORECAST_FIELDS = ("proj", "adj", "mf", "mf_n", "values", "line", "line_from", "lean",
                   "our_line", "td_chance", "source", "sleeper", "adj_h", "line_h", "proj_h")
HEX = re.compile(r"[0-9a-f]{64}\Z")


def code_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def game_contract(data, gid):
    """Forecasts, offered contracts and original Top membership; never outcomes."""
    players = []
    for player in data["players"]:
        if player["game_id"] == gid:
            players.append({"id": player["id"], "game_id": gid, "team": player["team"],
                            "opp": player["opp"], "pos": player["pos"], "late": player.get("late", False),
                            "props": sorted([{key: prop.get(key) for key in ("key", *FORECAST_FIELDS)}
                                             for prop in player["props"]], key=lambda prop: prop["key"])})
    picks = {side: sorted([pick for pick in rows if pick["game_id"] == gid],
                          key=lambda pick: (pick["player_id"], pick["key"]))
             for side, rows in data["picks"].items()}
    return {"players": sorted(players, key=lambda player: player["id"]), "picks": picks}


def _saved(root, name, lane):
    root, relative = Path(root).resolve(), Path(name)
    if relative.is_absolute() or ".." in relative.parts or str(relative) != name:
        raise IntegrityError("Invalid partial-evidence path")
    path = root / relative
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root):
        raise IntegrityError("Symlink partial evidence is unsupported")
    payload = referenced(root, name, lane)
    expected = (Path("data") / lane / str(payload["season"]) / f"w{payload['week']:02d}"
                / (digest(payload) + ".json.gz"))
    if relative != expected:
        raise IntegrityError("Partial evidence filename/period mismatch")
    return payload


def dispatch(config, data, at):
    """Unknown configuration fails. Other weeks select strict before any check."""
    route = config.get("verification_mode", "strict-full-board-v1")
    if route == "strict-full-board-v1":
        return "strict"
    if route != VERSION:
        raise IntegrityError("Unknown explicit verification route")
    spec = config.get("partial_week", {})
    plan = spec.get("plan", {})
    validate_plan(plan, spec.get("plan_sha256"))
    if spec.get("validator_sha256") != code_sha256():
        raise IntegrityError("Partial validator code identity differs from configuration")
    if config.get("experimental_recording_enabled") is not False:
        raise IntegrityError("Partial cutover requires experimental recording inactive")
    if (data["season"], data["week"]) != (plan["season"], plan["week"]):
        return "strict"
    if not utc(plan["effective_not_before"]) <= utc(at) < utc(plan["expires_at"]):
        raise IntegrityError("Partial cutover plan is not effective or has expired")
    return "partial"


def validate_plan(plan, expected_digest):
    try:
        if (not HEX.fullmatch(expected_digest or "") or digest(plan) != expected_digest
                or plan["schema_version"] != PLAN_VERSION or plan["validator_contract"] != VERSION
                or plan["full_board_verified"] is not False or plan["complete_week_qualified"] is not False
                or plan["experimental_recording_enabled"] is not False
                or plan["completion_status_max_age_seconds"] != 60
                or not utc(plan["plan_prepared_at"]) <= utc(plan["effective_not_before"]) < utc(plan["expires_at"])):
            raise IntegrityError("Wrong partial cutover plan/identity/clock")
        games = verify._indexed(plan["games"], "id", "plan games")
        exemptions = verify._indexed(plan["legacy_exemptions"], "game_id", "legacy exemptions")
        if not set(exemptions) <= set(games):
            raise IntegrityError("Legacy exemption outside the fixed game population")
        for gid, exemption in exemptions.items():
            if (not HEX.fullmatch(exemption["forecast_contract_sha256"])
                    or utc(games[gid]["kickoff"]) >= utc(plan["effective_not_before"])):
                raise IntegrityError("Invalid fixed legacy exemption")
    except (KeyError, TypeError, AttributeError) as err:
        raise IntegrityError("Malformed partial plan") from err
    return plan


def _plan_status(root, plan, name):
    original = _saved(root, name, "verification/partial-schedule-baselines")
    if (original["season"], original["week"]) != (plan["season"], plan["week"]):
        raise IntegrityError("Schedule baseline/plan period mismatch")
    status = original["status"]
    if (original.get("schema_version") != "partial-schedule-baseline-v1"
            or digest(status) != plan["schedule_status_payload_sha256"]
            or status["collected_at"] != plan["schedule_status_observed_at"]):
        raise IntegrityError("Fixed schedule source identity/clock mismatch")
    games = verified_status(status, plan["season"], plan["week"], "live", plan["plan_prepared_at"])
    planned = verify._indexed(plan["games"], "id", "plan games")
    if set(games) != set(planned):
        raise IntegrityError("Fixed schedule source population mismatch")
    for gid, game in planned.items():
        if (utc(games[gid]["kickoff"]) != utc(game["kickoff"])
                or _teams(status, gid) != {key: game[key] for key in ("home", "away")}):
            raise IntegrityError("Fixed schedule source differs from the approved plan")
    return status


def register_plan(root, spec, at, *, source_sha, initial_board):
    """Actual registration has its own immutable clock; the approved plan is intact."""
    plan = validate_plan(spec["plan"], spec["plan_sha256"])
    at = utc(at)
    if (spec["validator_sha256"] != code_sha256() or plan["engine_files"] != engine_hashes(Path(root))
            or not re.fullmatch(r"[0-9a-f]{40}", source_sha or "")
            or not utc(plan["effective_not_before"]) <= at < utc(plan["expires_at"])):
        raise IntegrityError("Invalid registration source, engine or clock")
    if digest(initial_board) != plan["initial_complete_board_sha256"]:
        raise IntegrityError("Original cutover board binding mismatch")
    baselines = []
    for path in sorted((Path(root) / "data/verification/partial-schedule-baselines").rglob("*.json.gz")):
        saved = _saved(root, path.relative_to(root).as_posix(), "verification/partial-schedule-baselines")
        if digest(saved.get("status")) == plan["schedule_status_payload_sha256"]:
            baselines.append(path.relative_to(root).as_posix())
    if len(baselines) != 1:
        raise IntegrityError("The required original fixed schedule source is missing or ambiguous")
    _plan_status(root, plan, baselines[0])
    for exemption in plan["legacy_exemptions"]:
        if digest(game_contract(initial_board, exemption["game_id"])) != exemption["forecast_contract_sha256"]:
            raise IntegrityError("Original legacy contract differs from the fixed plan")
    lane = "verification/partial-registrations"
    existing = []
    for path in sorted((Path(root) / "data" / lane).rglob("*.json.gz")):
        saved = _saved(root, path.relative_to(root).as_posix(), lane)
        if saved.get("plan_sha256") == digest(plan):
            existing.append((path, saved))
    if len(existing) > 1:
        raise IntegrityError("Conflicting partial plan registrations")
    if existing:
        path, payload = existing[0]
        _registration(root, path.relative_to(root).as_posix(), spec, at)
        return path, payload
    original = write(root, "verification/partial-plan-boards", {
        "schema_version": "partial-initial-board-v1", "season": plan["season"], "week": plan["week"],
        "board": initial_board, "board_sha256": digest(initial_board), "plan_sha256": digest(plan)})
    plan_path = write(root, "verification/partial-plans", plan)
    payload = {"schema_version": REGISTRATION_VERSION, "season": plan["season"], "week": plan["week"],
               "plan_sha256": digest(plan), "plan_receipt": plan_path.relative_to(root).as_posix(),
               "initial_board_receipt": original.relative_to(root).as_posix(), "registered_at": stamp(at),
               "schedule_status_receipt": baselines[0],
               "source_sha": source_sha, "validator_sha256": code_sha256(),
               "owner_authorization": spec["owner_authorization"]}
    path = write(root, lane, payload)
    _registration(root, path.relative_to(root).as_posix(), spec, at)
    return path, payload


def _registration(root, name, spec, at):
    plan = validate_plan(spec["plan"], spec["plan_sha256"])
    payload = _saved(root, name, "verification/partial-registrations")
    if (payload["season"], payload["week"]) != (plan["season"], plan["week"]):
        raise IntegrityError("Registration/plan period mismatch")
    saved_plan = _saved(root, payload["plan_receipt"], "verification/partial-plans")
    board = _saved(root, payload["initial_board_receipt"], "verification/partial-plan-boards")
    _plan_status(root, plan, payload["schedule_status_receipt"])
    if (payload.get("schema_version") != REGISTRATION_VERSION or saved_plan != plan
            or payload["plan_sha256"] != digest(plan) or payload["validator_sha256"] != code_sha256()
            or payload["owner_authorization"] != spec["owner_authorization"]
            or not re.fullmatch(r"[0-9a-f]{40}", payload.get("source_sha", ""))
            or not utc(plan["effective_not_before"]) <= utc(payload["registered_at"]) <= utc(at)
            or utc(payload["registered_at"]) >= utc(plan["expires_at"])
            or board.get("schema_version") != "partial-initial-board-v1"
            or board["plan_sha256"] != digest(plan)
            or board["board_sha256"] != digest(board["board"])):
        raise IntegrityError("Invalid saved partial registration/original board")
    if digest(board["board"]) != plan["initial_complete_board_sha256"]:
        raise IntegrityError("Initial board original checksum mismatch")
    for exemption in plan["legacy_exemptions"]:
        if digest(game_contract(board["board"], exemption["game_id"])) != exemption["forecast_contract_sha256"]:
            raise IntegrityError("Saved exemption contract mismatch")
    return payload


def _teams(status, gid):
    events = verify._indexed(status["response"]["events"], "id", "status events")
    competitors = events[gid]["competitions"][0]["competitors"]
    if len(competitors) != 2 or {item["homeAway"] for item in competitors} != {"home", "away"}:
        raise IntegrityError("Ambiguous completion-status teams")
    return {item["homeAway"]: verify.sources.team_code(item["team"]["abbreviation"]) for item in competitors}


def _game(root, data, game, original):
    verify._original_game(original, game)
    if game_contract(data, game["id"]) != game_contract(original["week_data"], game["id"]):
        raise IntegrityError("Original forecast, saved contract or Top membership changed")
    players = verify._indexed(data["players"], "id", "players")
    model = matchup.Matchups({int(week): rows for week, rows in original["weeks"].items()}, original["positions"])
    checked = 0
    for player in players.values():
        if player["game_id"] != game["id"]:
            continue
        if (player["team"] not in (game["home"], game["away"])
                or player["opp"] not in (game["home"], game["away"]) or player["opp"] == player["team"]
                or player["props"] and original["positions"].get(player["id"]) != player["pos"]):
            raise IntegrityError("Original player/game/team/opponent/position mismatch")
        for prop in player["props"]:
            if "mf" not in prop:
                if prop.get("adj") is not None:
                    raise IntegrityError("Adjusted forecast without a saved matchup factor")
                continue
            average = statistics.mean(value["v"] for value in prop.get("values", [])) if prop.get("values") else None
            if model.factor(player["opp"], player["pos"], prop["key"], average) != (prop["mf"], prop["mf_n"]):
                raise IntegrityError("Original matchup-factor reproduction failed")
            checked += 1
    return checked


def _shape_input(root, data, proof, exemptions, hashes, at):
    """Frozen Top eligibility uses original metadata, not later injury updates.

    Legacy picks remain structurally checked and fingerprinted, but their lost
    original eligibility is explicitly unverified. No new pick is exempted.
    """
    checked = copy.deepcopy(data)
    games = {game["id"]: game for game in data["games"]}
    legacy = {gid for gid in exemptions if proof["game_origins"][gid] is None}
    originals = {}
    for player in checked["players"]:
        game = games[player["game_id"]]
        frozen = game["state"] != "pre" or utc(game["kickoff"]) <= utc(data["generated_at"])
        if not frozen or game["id"] in legacy:
            continue
        origin = proof["game_origins"][game["id"]]
        if not origin:
            raise IntegrityError("Nonexempt frozen selection lacks original inputs")
        if origin not in originals:
            original = verify.recorded_inputs(root, origin, data["season"], data["week"], hashes,
                                              mode="live", observed_at=at)
            originals[origin] = verify._indexed(original["week_data"]["players"], "id", "original players")
        saved = originals[origin][player["id"]]
        for key in ("injury", "snap_share", "proj_ppr"):
            if key in saved:
                player[key] = saved[key]
            else:
                player.pop(key, None)
    checked["picks"] = {side: [pick for pick in picks if pick["game_id"] not in legacy]
                        for side, picks in checked["picks"].items()}
    return checked


def verify_scope(root, data, proof, closing_status, spec, registration, at, *, frozen_reader=None):
    """Validate complete saved sources, never a trimmed board or a saved PASS."""
    root, at = Path(root), utc(at)
    plan = validate_plan(spec["plan"], spec["plan_sha256"])
    registered = _registration(root, registration, spec, at)
    if not utc(registered["registered_at"]) <= at < utc(plan["expires_at"]):
        raise IntegrityError("Scope verification outside the registered plan window")
    if (data["season"], data["week"]) != (plan["season"], plan["week"]):
        raise IntegrityError("Partial plan period mismatch")
    hashes = engine_hashes(root)
    if hashes != plan["engine_files"] or spec["validator_sha256"] != code_sha256():
        raise IntegrityError("Partial engine/validator identity mismatch")
    games = verify._indexed(data["games"], "id", "board games")
    planned = verify._indexed(plan["games"], "id", "plan games")
    if (proof.get("schema_version") != "matchup-proof-v1" or proof.get("output_sha256") != digest(data)
            or set(games) != set(planned) or set(proof["game_origins"]) != set(games)):
        raise IntegrityError("Full board/proof/plan population mismatch")
    latest = verify.recorded_inputs(root, proof["latest_inputs"], data["season"], data["week"], hashes,
                                    mode="live", observed_at=at)
    if latest["week_data"] != data:
        raise IntegrityError("Latest complete original board differs")
    errors = []
    verify.check_ppr(root=root, report=errors.append)
    exemptions = {item["game_id"]: item for item in plan["legacy_exemptions"]}
    verify.check_shape(_shape_input(root, data, proof, exemptions, hashes, at), report=errors.append)
    verify.check_lean_balance(data, report=errors.append)
    validate(data, {key: data[key] for key in ("season", "week", "generated_at")}, at)
    if errors:
        raise IntegrityError("Global board integrity failure: " + "; ".join(errors))
    statuses = verified_status(closing_status, data["season"], data["week"], "live", at)
    closed = utc(closing_status["collected_at"])
    if not utc(latest["recorded_at"]) <= closed <= at or (at - closed).total_seconds() > 60:
        raise IntegrityError("Missing, reversed or stale final status observation")
    if set(statuses) != set(games):
        raise IntegrityError("Final status population mismatch")
    cache, population, checked = {proof["latest_inputs"]: latest}, [], 0
    for gid, game in sorted(games.items()):
        scheduled, status = planned[gid], statuses[gid]
        if (any(game[key] != scheduled[key] for key in ("home", "away"))
                or utc(game["kickoff"]) != utc(scheduled["kickoff"])
                or utc(status["kickoff"]) != utc(scheduled["kickoff"])
                or _teams(closing_status, gid) != {key: game[key] for key in ("home", "away")}):
            raise IntegrityError("Changed schedule or game/team identity requires a plan decision")
        if (game["state"] not in ("pre", "in", "post") or status["state"] not in ("pre", "in", "post")
                or status["state"] == "pre" and status["completed"] is not False
                or game["state"] in ("in", "post") and status["state"] == "pre"
                or any(word in status["detail"].lower() for word in ("cancel", "postpon", "suspend", "delay"))):
            raise IntegrityError("Unknown, contradictory or nonstandard game status")
        origin = proof["game_origins"][gid]
        if gid in exemptions and origin is None:
            if (status["state"] not in ("in", "post") or utc(game["kickoff"]) > at
                    or digest(game_contract(data, gid)) != exemptions[gid]["forecast_contract_sha256"]):
                raise IntegrityError("Fixed legacy exemption status/contract mismatch")
            kind = "retained_legacy_original_proof_missing"
        else:
            if not origin:
                raise IntegrityError("Nonexempt game lacks original inputs")
            if origin not in cache:
                cache[origin] = verify.recorded_inputs(root, origin, data["season"], data["week"], hashes,
                                                      mode="live", observed_at=at)
            checked += _game(root, data, game, cache[origin])
            new = game["state"] == "pre" and utc(game["kickoff"]) > utc(data["generated_at"])
            if new:
                if (origin != proof["latest_inputs"] or status["state"] != "pre"
                        or utc(game["kickoff"]) <= at):
                    raise IntegrityError("New forecast did not complete before the unchanged kickoff/status")
                kind = "new_pregame_original_inputs_verified"
            else:
                if frozen_reader is None:
                    raise IntegrityError("Frozen game lacks independently completed evidence")
                frozen_reader(gid, origin, digest(game_contract(data, gid)))
                kind = "frozen_original_inputs_verified"
        population.append({"game_id": gid, "home": game["home"], "away": game["away"],
                           "kickoff": game["kickoff"], "board_state": game["state"],
                           "completion_source_state": status["state"], "classification": kind,
                           "original_inputs": origin, "forecast_contract_sha256": digest(game_contract(data, gid))})
    return {"schema_version": VERSION, "season": data["season"], "week": data["week"],
            "full_board_verified": False, "complete_week_qualified": False,
            "claim": "RETAINED_ORIGINAL_MODEL_INPUT_REPRODUCTION_ONLY",
            "provider_projection_authentication": "NOT_ESTABLISHED", "quote_freshness": "NOT_ESTABLISHED",
            "predictive_accuracy": "NOT_ESTABLISHED", "venue_settlement": "NOT_ESTABLISHED",
            "output_sha256": digest(data), "proof": copy.deepcopy(proof), "plan_sha256": digest(plan),
            "registration_receipt": registration, "validator_sha256": code_sha256(), "engine_files": hashes,
            "latest_inputs_sha256": digest(latest), "completion_status": copy.deepcopy(closing_status),
            "verified_at": stamp(at), "checked_factors": checked, "game_population": population}


def read_bundle(root, name, spec, native_reader, *, now=None, _seen=None):
    """Saved consumption reproduces the source contract; no saved flags suffice."""
    root, now = Path(root), utc(now or datetime.now(timezone.utc))
    seen = set() if _seen is None else set(_seen)
    if name in seen:
        raise IntegrityError("Cyclic frozen evidence")
    seen.add(name)
    completion = _saved(root, name, COMPLETION_LANE)
    for failure in (root / "data/verification/partial-failures").rglob("*.json.gz"):
        if read(failure).get("completion_sha256") == digest(completion):
            raise IntegrityError("Completion was rejected at its final persistence barrier")
    if (completion.get("schema_version") != COMPLETION_VERSION
            or completion["validator_sha256"] != code_sha256()
            or completion["plan_sha256"] != spec["plan_sha256"]):
        raise IntegrityError("Unsupported completion/validator/plan")
    scope = _saved(root, completion["scope_receipt"], SCOPE_LANE)
    period = (spec["plan"]["season"], spec["plan"]["week"])
    if ((completion["season"], completion["week"]) != period
            or (scope["season"], scope["week"]) != period):
        raise IntegrityError("Completion/scope/plan period mismatch")
    at = utc(completion["evidence_completed_at"])
    if not utc(scope["verified_at"]) <= at <= now:
        raise IntegrityError("Invalid evidence-completion clock")
    original = verify.recorded_inputs(root, scope["proof"]["latest_inputs"], scope["season"], scope["week"],
                                      engine_hashes(root), mode="live", observed_at=at)
    data = original["week_data"]
    def frozen(gid, origin, contract):
        return _frozen(root, spec, native_reader, gid, origin, contract, now, seen)
    expected = verify_scope(root, data, scope["proof"], scope["completion_status"], spec,
                            scope["registration_receipt"], utc(scope["verified_at"]), frozen_reader=frozen)
    if scope != expected:
        raise IntegrityError("Scope differs from revalidated original evidence")
    baseline = native_reader(root / completion["baseline_receipt"], root, now=now)
    generated, captured = utc(baseline["forecast_generated_at"]), utc(baseline["captured_at"])
    if (completion["scope_payload_sha256"] != digest(scope)
            or completion["baseline_payload_sha256"] != digest(baseline)
            or completion["output_sha256"] != digest(data)
            or baseline["input_sha256"] != digest(data)
            or generated != utc(data["generated_at"])
            or not utc(original["recorded_at"]) <= captured <= utc(scope["verified_at"]) <= at
            or baseline["rows"] != make_payload(data, captured, engine_hashes(root), "live")["rows"]):
        raise IntegrityError("Native receipt/source/row/clock binding mismatch")
    included = {game["game_id"] for game in scope["game_population"]
                if game["classification"] == "new_pregame_original_inputs_verified"}
    if any(row["game_id"] not in included or utc(row["kickoff"]) <= at for row in baseline["rows"]):
        raise IntegrityError("Native pregame population or evidence cutoff mismatch")
    if (at - utc(scope["completion_status"]["collected_at"])).total_seconds() > 60:
        raise IntegrityError("Evidence completed after final status expired")
    return completion, scope, baseline


def _frozen(root, spec, native_reader, gid, origin, contract, now, seen=None):
    matches = []
    for path in sorted((Path(root) / "data" / COMPLETION_LANE).rglob("*.json.gz")):
        name = path.relative_to(root).as_posix()
        candidate = _saved(root, name, COMPLETION_LANE)
        if candidate.get("plan_sha256") != spec["plan_sha256"]:
            continue
        scope = _saved(root, candidate["scope_receipt"], SCOPE_LANE)
        if any(game["game_id"] == gid and game["original_inputs"] == origin
               and game["forecast_contract_sha256"] == contract
               and game["classification"] == "new_pregame_original_inputs_verified"
               for game in scope["game_population"]):
            matches.append(name)
    if not matches:
        raise IntegrityError("Frozen forecast has no completed original pregame bundle")
    for name in matches:
        read_bundle(root, name, spec, native_reader, now=now, _seen=seen)


def record_bundle(root, data, proof, closing_status, spec, registration, native_reader, *, clock=None):
    root = Path(root)
    clock = clock or (lambda: datetime.now(timezone.utc))
    before = utc(clock())
    native_id = digest({"data": digest(data), "engine": digest(engine_hashes(root)), "mode": "live"})
    native = root / "data/forward" / str(data["season"]) / f"w{data['week']:02d}" / (native_id + ".json.gz")
    if native.exists():
        matches = []
        for path in sorted((root / "data" / COMPLETION_LANE).rglob("*.json.gz")):
            saved = _saved(root, path.relative_to(root).as_posix(), COMPLETION_LANE)
            if saved.get("baseline_receipt") == native.relative_to(root).as_posix():
                matches.append(path)
        if len(matches) != 1:
            raise IntegrityError("Existing native identity lacks one intact completed bundle; no backfill")
        completion, scope, baseline = read_bundle(root, matches[0].relative_to(root).as_posix(), spec, native_reader, now=before)
        if scope["proof"] != proof or scope["output_sha256"] != digest(data):
            raise IntegrityError("Retry current proof differs from the first durable source bundle")
        # A retry revalidates current identity/status separately without altering
        # the first observation. It does not make a new pregame claim.
        statuses = verified_status(closing_status, data["season"], data["week"], "live", before)
        if ((before - utc(closing_status["collected_at"])).total_seconds() > 60
                or set(statuses) != {game["id"] for game in data["games"]}):
            raise IntegrityError("Retry requires a fresh complete status observation")
        for game in data["games"]:
            status = statuses[game["id"]]
            if (utc(status["kickoff"]) != utc(game["kickoff"])
                    or _teams(closing_status, game["id"]) != {key: game[key] for key in ("home", "away")}
                    or status["state"] == "pre" and status["completed"] is not False
                    or game["state"] in ("in", "post") and status["state"] == "pre"
                    or any(word in status["detail"].lower() for word in ("cancel", "postpon", "suspend", "delay"))):
                raise IntegrityError("Retry schedule/team changed")
        health = validate(data, {key: data[key] for key in ("season", "week", "generated_at")}, before)
        health.update(capture_mode="live", capture_created=False, receipt=native.relative_to(root).as_posix(),
                      first_captured_at=baseline["captured_at"], capture_rows=len(baseline["rows"]))
        return native, health, matches[0], scope
    def frozen(gid, origin, contract):
        return _frozen(root, spec, native_reader, gid, origin, contract, before)
    scope = verify_scope(root, data, proof, closing_status, spec, registration, before, frozen_reader=frozen)
    native, health = capture(data, load_json(root / "output/data/meta.json"), root, before, engine_hashes(root), mode="live")
    baseline = native_reader(native, root, now=utc(clock()))
    # Validate again after native persistence and expensive source/row checks.
    validated = utc(clock())
    scope = verify_scope(root, data, proof, closing_status, spec, registration, validated, frozen_reader=frozen)
    if baseline["rows"] != make_payload(data, before, engine_hashes(root), "live")["rows"]:
        raise IntegrityError("Native rows differ from original board")
    scope_path = write(root, SCOPE_LANE, scope)
    if _saved(root, scope_path.relative_to(root).as_posix(), SCOPE_LANE) != scope:
        raise IntegrityError("Scope readback failed")
    # This clock is AFTER required native and scope fsync/readback. The final
    # marker records that barrier; no orphan file is independently qualified.
    completed = utc(clock())
    included = {game["game_id"] for game in scope["game_population"]
                if game["classification"] == "new_pregame_original_inputs_verified"}
    if (completed < validated or (completed - utc(closing_status["collected_at"])).total_seconds() > 60
            or any(utc(game["kickoff"]) <= completed for game in scope["game_population"] if game["game_id"] in included)):
        raise IntegrityError("Evidence completion crossed kickoff, reversed clocks or expired status")
    completion = {"schema_version": COMPLETION_VERSION, "season": data["season"], "week": data["week"],
                  "plan_sha256": spec["plan_sha256"], "validator_sha256": code_sha256(),
                  "output_sha256": digest(data), "scope_receipt": scope_path.relative_to(root).as_posix(),
                  "scope_payload_sha256": digest(scope), "baseline_receipt": native.relative_to(root).as_posix(),
                  "baseline_payload_sha256": digest(baseline), "evidence_completed_at": stamp(completed)}
    path = write(root, COMPLETION_LANE, completion)
    if _saved(root, path.relative_to(root).as_posix(), COMPLETION_LANE) != completion:
        raise IntegrityError("Completion readback mismatch")
    persisted = utc(clock())
    if (persisted < completed or (persisted - utc(closing_status["collected_at"])).total_seconds() > 60
            or any(utc(game["kickoff"]) <= persisted for game in scope["game_population"] if game["game_id"] in included)):
        write(root, "verification/partial-failures", {"schema_version": "partial-completion-failure-v1",
              "season": data["season"], "week": data["week"], "completion_sha256": digest(completion),
              "failed_at": stamp(persisted), "reason": "completion_persistence_crossed_cutoff"})
        raise IntegrityError("Completion persistence crossed the final pregame cutoff")
    return native, health, path, scope


def public_scope(scope, completion):
    return {"schema_version": "partial-week-public-scope-v1", "season": scope["season"], "week": scope["week"],
            "output_sha256": scope["output_sha256"], "plan_sha256": scope["plan_sha256"],
            "scope_sha256": digest(scope), "completion_sha256": digest(completion),
            "evidence_completed_at": completion["evidence_completed_at"], "full_board_verified": False,
            "complete_week_qualified": False, "claim": scope["claim"],
            "games": [{key: game[key] for key in ("game_id", "home", "away", "kickoff", "classification")}
                      for game in scope["game_population"]]}
