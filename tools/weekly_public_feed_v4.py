"""Source-bound correction-epoch consumer; existing feed wire remains V2.

Only an owner-registered publisher/recipe may declare dynamic metadata versions.
This module never fits, selects, reads outcomes or promotes an unregistered
template. Historical website policies and their fixed recipes stay unchanged.
"""
from __future__ import annotations
import copy
from pathlib import Path
import re
import zlib

import weekly_public_feed as old
from classic_model_v1 import contract

POLICY = "weekly-derived-selected-policy-v4"
AUTHORITY = "audit-weekly-publication-authority-v3"
RULE = "DECLARED_EPOCH_METADATA_PROJECTION_ONLY_NO_VALUES_OR_RESELECTION"
ROOT = Path(__file__).resolve().parents[1]
CURRENT_CODE_FILES = old.CURRENT_CODE_FILES | {"tools/weekly_public_feed_v4.py"}
STATIC = {"registration_id", "source_policy_sha256", "public_fields", "public_roles",
          "rights_authorities", "r0_identities", "engine_sha256", "public_ref"}
KEYS = STATIC | {"schema_version", "state", "authority_kind", "human_approval",
    "public_raw_or_model_weights", "static_registration_sha256", "registered_at_utc",
    "lab_public_policy_sha256", "lab_recipe_registered_at_utc", "recipe_registration_sha256", "producer_policy_sha256",
    "workflow_sha256", "jobs", "publication_authority", "expected_categories",
    "current_execution", "website_code_sha256"}
AUTHORITY_KEYS = {"schema_version", "state", "repository", "source_sha", "source_branch",
    "workflow_path", "event", "export_job", "run_attempt", "public_ref", "catalog_schema",
    "catalog_freezer_sha256", "catalog_registration_rule", "recipe_registration_sha256"}
CATALOG_KEYS = {"schema_version", "rows", "current_values_used", "public_policy_registration"}
CATALOG_ROW_KEYS = {"category", "method_id", "procedure_version", "model_version"}
RECEIPT_SCHEMA = "audit-weekly-delivery-v1-public-receipt"
RECEIPT_CAP = 64 << 10
DISCOVERY_HASH_KEYS = {"archive_index_sha256", "archive_files_sha256", "reader_witness_sha256", "epoch_sha256", "choice_sha256"}
RECEIPT_KEYS = {"schema_version", "source_sha", "run_id", "root_go_sha256", "policy_sha256", "policy_registered_at_utc",
    "workflow_sha256", "recipe_registration_sha256", "rights_authority_sha256", "r0_identity_sha256", "origin_choice_sha256",
    "feed_sha256", "feed_bytes", "rows", "categories", "jobs", "created_at", "verified_at", "fits", "raw_or_models_public"} | DISCOVERY_HASH_KEYS


def current(root):
    try:
        return contract(root)
    except (OSError, ValueError):
        raise old.FeedError("V4_CURRENT_ENGINE_SOURCE") from None


def inventory(root):
    root = Path(root).resolve()
    actual = {}
    for name in sorted(CURRENT_CODE_FILES):
        path = root / name
        old.require(not path.is_symlink() and path.resolve().is_relative_to(root)
                    and path.is_file() and path.stat().st_size <= 2 << 20, "V4_CODE_SCOPE")
        actual[name] = old.sha(path.read_bytes())
    return actual


def template(root=ROOT):
    """Public static scope only; required new authority inputs remain null."""
    base = old.historical_policy_v2(root)
    p = {k:copy.deepcopy(base[k]) for k in STATIC}
    p.update(schema_version=POLICY, state="PREPARED_UNREGISTERED",
        authority_kind="AUTOMATED_REGISTERED_POLICY", human_approval=False,
        public_raw_or_model_weights=False, static_registration_sha256=old.digest(base),
        registered_at_utc=None, lab_public_policy_sha256=None, lab_recipe_registered_at_utc=None, recipe_registration_sha256=None,
        producer_policy_sha256=None, workflow_sha256=None,
        jobs=dict(produce=None, restore=None, consume=None),
        expected_categories=sorted(old.overlay().PRODUCTS), current_execution=current(root),
        website_code_sha256=inventory(root),
        publication_authority=dict(schema_version=AUTHORITY, state="PREPARED_UNREGISTERED",
            repository=old.REPOSITORY, source_sha=None, source_branch=None,
            workflow_path=".github/workflows/lab.yml", event="workflow_dispatch", export_job=None,
            run_attempt=1, public_ref="lab-state", catalog_schema=old.CATALOG_V2,
            catalog_freezer_sha256=None, catalog_registration_rule=RULE,
            recipe_registration_sha256=None))
    return p


def policy_check(p, *, root=ROOT, now=None):
    old.require(type(p) is dict and set(p) in (KEYS, KEYS | {WITNESS_FIELD}) and p["schema_version"] == POLICY
        and p["state"] == "ROOT_REGISTERED" and p["authority_kind"] == "AUTOMATED_REGISTERED_POLICY"
        and p["human_approval"] is p["public_raw_or_model_weights"] is False,
        "V4_ROOT_REGISTRATION_REQUIRED")
    old.require(len(old.canonical(p)) <= 1 << 20, "V4_POLICY_BOUND")
    if WITNESS_FIELD in p:witness_descriptors(p)
    base = old.historical_policy_v2(root)
    old.require(p["static_registration_sha256"] == old.digest(base)
        and all(p[k] == base[k] for k in STATIC), "V4_ORIGINAL_STATIC_SCOPE_CHANGED")
    old.require(p["expected_categories"] == sorted(old.overlay().PRODUCTS)
        and len(p["expected_categories"]) == 11 and "fantasy_ppr" not in p["expected_categories"],
        "V4_COMPLETE_SUPPORTED_SCOPE")
    old.require(all(old.h(p[k]) for k in ("lab_public_policy_sha256", "recipe_registration_sha256",
        "producer_policy_sha256", "workflow_sha256"))
        and p["recipe_registration_sha256"] == p["producer_policy_sha256"], "V4_NEW_RECIPE_BINDING")
    registered = old.utc(p["registered_at_utc"])
    old.require(old.utc(p["lab_recipe_registered_at_utc"]) <= registered, "V4_DISTINCT_CAUSAL_REGISTRATION_CLOCKS")
    if now is not None:
        old.require(registered <= old.utc(now), "V4_POLICY_REGISTRATION_CLOCK")
    jobs = p["jobs"]
    old.require(type(jobs) is dict and set(jobs) == {"produce", "restore", "consume"}
        and all(type(v) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v) for v in jobs.values())
        and len(set(jobs.values())) == 3, "V4_CLOSED_REGISTERED_JOBS")
    a = p["publication_authority"]
    old.require(type(a) is dict and set(a) == AUTHORITY_KEYS and a["schema_version"] == AUTHORITY
        and a["state"] == "ROOT_REGISTERED" and a["repository"] == old.REPOSITORY
        and type(a["source_sha"]) is str and re.fullmatch(r"[a-f0-9]{40}", a["source_sha"])
        and type(a["source_branch"]) is str and re.fullmatch(r"[A-Za-z0-9_./-]+", a["source_branch"])
        and all(x not in {"", ".", ".."} for x in a["source_branch"].split("/"))
        and a["workflow_path"] == ".github/workflows/lab.yml" and a["event"] == "workflow_dispatch"
        and a["export_job"] == jobs["consume"] and type(a["run_attempt"]) is int and a["run_attempt"] == 1
        and a["public_ref"] == p["public_ref"] == "lab-state" and a["catalog_schema"] == old.CATALOG_V2
        and old.h(a["catalog_freezer_sha256"]) and a["catalog_registration_rule"] == RULE
        and a["recipe_registration_sha256"] == p["recipe_registration_sha256"], "V4_CLOSED_NEW_AUTHORITY")
    execution = current(root)
    old.require(p["current_execution"] == execution and type(p["website_code_sha256"]) is dict
        and set(p["website_code_sha256"]) == CURRENT_CODE_FILES
        and all(old.h(x) for x in p["website_code_sha256"].values())
        and p["website_code_sha256"] == inventory(root)
        and all(p["website_code_sha256"][k] == v for k,v in execution["engine_sha256"].items()),
        "V4_CURRENT_EXECUTION_OR_INVENTORY")
    return base


def declared_catalog(catalog, p):
    """Called after live job verification; no selection or version inference."""
    old.require(type(catalog) is dict and set(catalog) == CATALOG_KEYS
        and catalog["schema_version"] == old.CATALOG_V2 and catalog["current_values_used"] is False
        and catalog["public_policy_registration"] == "REQUIRED_SEPARATELY; not automatic approval"
        and type(catalog["rows"]) is list and 11 <= len(catalog["rows"]) <= 256,
        "V4_DECLARED_METADATA_CATALOG")
    allowed = set()
    for r in catalog["rows"]:
        old.require(type(r) is dict and set(r) == CATALOG_ROW_KEYS
            and r["category"] in p["expected_categories"] and r["method_id"] == "P2_SELECTED"
            and old.h(r["procedure_version"]) and old.h(r["model_version"]), "V4_CLOSED_CATALOG_ROW")
        key = (r["category"], r["method_id"], r["procedure_version"], r["model_version"])
        old.require(key not in allowed, "V4_DUPLICATE_CATALOG_ROW")
        allowed.add(key)
    old.require({r[0] for r in allowed} == set(p["expected_categories"]), "V4_ALL_ELEVEN_CATALOG_CATEGORIES")
    return allowed


def verify_public_receipt(feed, p, chain, *, fetch):
    """Exactly one bounded new receipt; never an old receipt impersonation."""
    body = old.canonical(feed)
    feed_sha = old.sha(body)
    url = "https://raw.githubusercontent.com/" + old.REPOSITORY + "/lab-state/state/public/weekly-adaptive-v1/receipts/" + feed_sha + ".json.gz"
    raw = fetch(url, RECEIPT_CAP)
    old.require(type(raw) is bytes and 0 < len(raw) <= RECEIPT_CAP, "V4_PUBLIC_RECEIPT_BOUND")
    try:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        plain = decoder.decompress(raw, RECEIPT_CAP + 1)
        old.require(len(plain) <= RECEIPT_CAP and decoder.eof and not decoder.unused_data
                    and not decoder.unconsumed_tail, "V4_PUBLIC_RECEIPT_INFLATION_OR_TRAILING_BYTES")
    except zlib.error:
        raise old.FeedError("V4_PUBLIC_RECEIPT_COMPRESSION") from None
    r = old.strict_public_json(plain)
    old.require(type(r) is dict and set(r) == RECEIPT_KEYS and r["schema_version"] == RECEIPT_SCHEMA
        and plain == old.canonical(r) and type(r["fits"]) is int and r["fits"] == 0
        and r["raw_or_models_public"] is False, "V4_CLOSED_NEW_PUBLIC_RECEIPT")
    old.require(all(old.h(r[k]) for k in DISCOVERY_HASH_KEYS | {"root_go_sha256", "policy_sha256", "workflow_sha256",
        "recipe_registration_sha256", "rights_authority_sha256", "r0_identity_sha256", "origin_choice_sha256", "feed_sha256"}),
        "V4_PUBLIC_RECEIPT_HASH_FIELDS")
    old.require(r["policy_sha256"] == p["lab_public_policy_sha256"] and r["workflow_sha256"] == p["workflow_sha256"]
        and r["recipe_registration_sha256"] == p["recipe_registration_sha256"]
        and r["source_sha"] == p["publication_authority"]["source_sha"] and r["run_id"] == feed["publication"]["run_id"]
        and r["rights_authority_sha256"] == feed["rights_authority_sha256"] and r["r0_identity_sha256"] == feed["r0_identity_sha256"],
        "V4_EXACT_PUBLIC_POLICY_RECIPE_SOURCE_RECEIPT")
    old.require(r["feed_sha256"] == feed_sha and type(r["feed_bytes"]) is int and r["feed_bytes"] == len(body)
        and type(r["rows"]) is int and r["rows"] == len(feed["rows"])
        and r["categories"] == sorted({row["category"] for row in feed["rows"]}) and r["created_at"] == feed["created_at"],
        "V4_PUBLIC_RECEIPT_EXACT_FEED")
    expected = {role:dict(job_id=p["jobs"][role], api_job_id=j["id"])
                for role,j in zip(("produce", "restore", "consume"), chain)}
    old.require(type(r["jobs"]) is dict and r["jobs"] == expected and all(type(j["api_job_id"]) is int
        and set(j) == {"job_id", "api_job_id"} for j in r["jobs"].values()), "V4_PUBLIC_RECEIPT_ACTUAL_JOB_IDS")
    old.require(old.utc(p["lab_recipe_registered_at_utc"]) <= old.utc(r["policy_registered_at_utc"])
        <= min(old.utc(row["issued_at"]) for row in feed["rows"])
        and old.utc(r["policy_registered_at_utc"]) <= old.utc(r["verified_at"])
        and old.utc(chain[2]["started_at"]) <= old.utc(r["verified_at"]) <= old.utc(r["created_at"]),
        "V4_PUBLIC_RECEIPT_HONEST_POLICY_CLOCKS")
    return dict(public_receipt_sha256=old.sha(raw), public_receipt_body_sha256=old.sha(plain),
        lab_public_policy_sha256=r["policy_sha256"], lab_policy_registered_at_utc=r["policy_registered_at_utc"],
        workflow_sha256=r["workflow_sha256"], public_receipt_schema=r["schema_version"],
        public_receipt_GETs=1, receipt_policy_and_workflow_checked=True)


def verify_execution(feed, p, *, now, fetch):
    responses = {}
    pub = feed["publication"]
    old.require(type(pub) is dict and type(pub.get("run_id")) is str
        and re.fullmatch(r"[1-9][0-9]{0,19}", pub["run_id"]), "V4_PUBLICATION_RUN")
    base = "https://api.github.com/repos/" + old.REPOSITORY + "/actions/runs/" + pub["run_id"]
    jobs_url = base + "/jobs?per_page=100&page=1"
    def tracked(url, cap):
        old.require(url in {base, jobs_url} and cap == 1 << 20, "V4_FIXED_METADATA_ROUTES")
        body = fetch(url, cap)
        old.require(type(body) is bytes and 0 < len(body) <= cap, "PUBLICATION_METADATA_BOUND")
        responses[url] = old.strict_public_json(body)
        return body
    proof = old.verify_publication_execution(feed, p, now=now, fetch=tracked)
    run = responses[base]
    data = responses[jobs_url]
    chain = []
    for role in ("produce", "restore", "consume"):
        found = [j for j in data["jobs"] if j.get("name") == p["jobs"][role]]
        old.require(len(found) == 1, "V4_UNIQUE_REGISTERED_WORKFLOW_ROLE")
        j = found[0]
        old.require(type(j.get("id")) is int and j["id"] > 0
            and type(j.get("run_id")) is int and j["run_id"] == int(pub["run_id"])
            and j.get("head_sha") == p["publication_authority"]["source_sha"]
            and j.get("status") == "completed" and j.get("conclusion") == "success"
            and old.utc(j["started_at"]) <= old.utc(j["completed_at"]), "V4_SUCCESSFUL_REGISTERED_WORKFLOW_ROLE")
        chain.append(j)
    old.require(len({j["id"] for j in chain}) == 3
        and old.utc(chain[0]["completed_at"]) <= old.utc(chain[1]["started_at"])
        and old.utc(chain[1]["completed_at"]) <= old.utc(chain[2]["started_at"]), "V4_PRODUCER_READER_EXPORTER_ORDER")
    receipt = verify_public_receipt(feed, p, chain, fetch=fetch)
    # Completed runs can be restarted. Reject a changed run before approval.
    before = copy.deepcopy(run)
    tracked(base, 1 << 20)
    after = responses[base]
    fields = ("id", "repository", "head_repository", "head_sha", "head_branch", "path",
              "event", "run_attempt", "status", "conclusion", "updated_at")
    old.require(all(after.get(k) == before.get(k) for k in fields), "V4_RUN_CHANGED_DURING_VERIFICATION")
    proof.update(schema_version="weekly-derived-v4-publication-execution", API_GETs=3,
        registered_jobs={r:j["id"] for r,j in zip(("produce", "restore", "consume"), chain)},
        recipe_registration_sha256=p["recipe_registration_sha256"], final_run_response_sha256=old.digest(after),
        verification_HTTP_GETs=4, **receipt)
    return proof


WITNESS_FIELD = "identity_scope_witnesses"
WITNESS_SCHEMA = "weekly-identity-scope-git-witness-v1"
WITNESS_KEYS = {"schema_version", "commit", "path", "git_blob_sha1", "bytes", "sha256"}
WITNESS_CAP = 4 << 20


def witness_descriptors(p):
    witnesses = p.get(WITNESS_FIELD)
    old.require(type(witnesses) is list and 1 <= len(witnesses) <= 4, "V4_WITNESS_LIST_BOUND")
    seen = set()
    for d in witnesses:
        old.require(type(d) is dict and set(d) == WITNESS_KEYS
            and d["schema_version"] == WITNESS_SCHEMA and d["path"] == "output/data/week.json"
            and all(type(d[k]) is str and re.fullmatch(r"[a-f0-9]{40}", d[k]) for k in ("commit", "git_blob_sha1"))
            and type(d["bytes"]) is int and 0 < d["bytes"] <= WITNESS_CAP and old.h(d["sha256"]),
            "V4_WITNESS_DESCRIPTOR")
        key = (d["commit"], d["path"])
        old.require(key not in seen, "V4_DUPLICATE_WITNESS"); seen.add(key)
    return sorted(witnesses, key=lambda d:(d["commit"], d["path"], d["sha256"]))


def read_scope_witness(root, descriptor):
    """An identity preimage witness, never a forecast/capture-time substitute."""
    import hashlib
    import subprocess
    command = ["git", "--no-replace-objects", "--no-lazy-fetch", "-C", str(Path(root).resolve())]
    def metadata(*args):
        result = subprocess.run(command + list(args), capture_output=True, timeout=1)
        old.require(result.returncode == 0 and len(result.stdout) <= 4096, "V4_WITNESS_GIT_METADATA")
        return result.stdout
    source = descriptor["commit"]
    old.require(metadata("rev-parse", "--verify", source + "^{commit}").decode().strip() == source,
                "V4_WITNESS_ACTUAL_COMMIT")
    metadata("merge-base", "--is-ancestor", source, "HEAD")
    tree = metadata("ls-tree", source, "--", descriptor["path"])
    expected = "100644 blob " + descriptor["git_blob_sha1"] + "\t" + descriptor["path"] + "\n"
    old.require(tree == expected.encode(), "V4_WITNESS_REGULAR_TRACKED_BLOB")
    oid = descriptor["git_blob_sha1"]
    old.require(metadata("cat-file", "-s", oid).decode().strip() == str(descriptor["bytes"]),
                "V4_WITNESS_ENCODED_BOUND")
    process = subprocess.Popen(command + ["cat-file", "blob", oid], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        body = process.stdout.read(descriptor["bytes"] + 1)
        old.require(len(body) == descriptor["bytes"], "V4_WITNESS_BYTES")
        old.require(process.wait(timeout=1) == 0, "V4_WITNESS_READ")
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=1)
        process.stdout.close()
    old.require(old.sha(body) == descriptor["sha256"]
        and hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest() == oid,
        "V4_WITNESS_CONTENT_IDENTITIES")
    board = old.strict_public_json(body)
    old.require(type(board) is dict, "V4_WITNESS_BOARD_TYPE")
    return board


def board_members(board):
    old.require(type(board.get("games")) is list and type(board.get("players")) is list,
                "V4_BOARD_MEMBERSHIP_TYPE")
    games = {g["id"]:g for g in board["games"]}
    players = {(p["game_id"],p["id"]):p for p in board["players"]}
    old.require(len(games) == len(board["games"]) and len(players) == len(board["players"])
        and all(type(g["id"]) is str for g in board["games"])
        and all(type(p["id"]) is str and type(p["game_id"]) is str and p["game_id"] in games for p in board["players"]),
        "V4_UNIQUE_BOARD_MEMBERSHIP")
    return games, players, old.overlay().board_offers(board)


def complete_scope(rows, games, players):
    if any(r["game_id"] not in games or (r["game_id"],r["player_id"]) not in players for r in rows):
        return None
    return old.digest([dict(player_id=r["player_id"],game_id=r["game_id"],category=r["category"],
        kickoff=games[r["game_id"]]["kickoff"],team=players[(r["game_id"],r["player_id"])]["team"],
        opponent=players[(r["game_id"],r["player_id"])]["opp"])
        for r in sorted(rows,key=old.overlay().key)])


def validate_witness_scoped_rows(feed, p, board, *, now, root, proof, allowed):
    games, players, offers = board_members(board)
    candidates = []
    # Every registered dependency is freshly checked; malformed witnesses never
    # become permission to keep looking for a convenient alternative.
    for descriptor in witness_descriptors(p):
        witness = read_scope_witness(root, descriptor)
        old.require(type(witness.get("season")) is int and type(witness.get("week")) is int
            and witness.get("execution_model") == p["current_execution"], "V4_WITNESS_PERIOD_OR_ENGINE")
        wg, wp, wo = board_members(witness)
        if (witness["season"],witness["week"]) != (board["season"],board["week"]):
            continue
        if complete_scope(feed["rows"], wg, wp) == feed["identity_scope_sha256"]:
            candidates.append((descriptor,wg,wp,wo))
    if not candidates and complete_scope(feed["rows"], games, players) == feed["identity_scope_sha256"]:
        candidates.append((None,games,players,offers))
    old.require(candidates, "CURRENT_BOARD_SCOPE_CHANGED")
    contexts = []
    for descriptor, wg, wp, wo in candidates:
        seen = set()
        for r in feed["rows"]:
            key = old.overlay().key(r)
            old.require(key not in seen, "CLOSED_UNIQUE_PUBLIC_ROWS"); seen.add(key)
            old.require((r["category"],r["method_id"],r["procedure_version"],r["model_version"]) in allowed,
                        "V4_ROW_NOT_IN_DECLARED_CATALOG")
            old.require(r["source_policy_sha256"] == p["source_policy_sha256"]
                and old.utc(p["lab_recipe_registered_at_utc"]) <= old.utc(r["issued_at"]), "V4_ROW_POLICY_AND_REGISTRATION")
            player, game = wp[(r["game_id"],r["player_id"])], wg[r["game_id"]]
            active = game.get("state") == "pre" and old.utc(r["valid_until_utc"]) > old.utc(now)
            old.require(not active or key in wo, "V4_ACTIVE_OFFER_MISSING")
            old.overlay().validate_row(dict(r, first_prepared_at=feed["created_at"]),
                                      wo if key in wo else {key:(player,game,{})})
            old.require(player.get("pos",player.get("position")) in p["public_roles"][r["category"]],
                        "V4_REGISTERED_PLAYER_ROLE")
        contexts.append(old.digest([dict(key=old.overlay().key(r),role=wp[(r["game_id"],r["player_id"])].get("pos",
            wp[(r["game_id"],r["player_id"])].get("position"))) for r in sorted(feed["rows"],key=old.overlay().key)]))
    old.require(len(set(contexts)) == 1, "V4_AMBIGUOUS_WITNESS_ROLES")
    descriptor, wg, wp, wo = candidates[0]
    rows, unavailable = [], {}
    def skip(reason):unavailable[reason] = unavailable.get(reason,0) + 1
    for r in feed["rows"]:
        key = old.overlay().key(r)
        game = games.get(r["game_id"]); player = players.get((r["game_id"],r["player_id"]))
        original = wp[(r["game_id"],r["player_id"])]
        if game is None:skip("current_game_missing"); continue
        if player is None:skip("current_player_missing"); continue
        if (player.get("team"),player.get("opp")) != (original["team"],original["opp"]):
            skip("current_team_or_opponent_changed"); continue
        if old.utc(game["kickoff"]) != old.utc(wg[r["game_id"]]["kickoff"]):
            skip("current_kickoff_changed"); continue
        role = player.get("pos",player.get("position"))
        if role not in p["public_roles"][r["category"]] or role != original.get("pos",original.get("position")):
            skip("current_role_changed"); continue
        if game.get("state") != "pre" or old.utc(r["valid_until_utc"]) <= old.utc(now):
            skip("current_started_or_expired"); continue
        if key not in offers:skip("current_offer_missing"); continue
        old.overlay().validate_row(dict(r,first_prepared_at=feed["created_at"]),offers)
        rows.append(dict(r,season=board["season"],week=board["week"],team=player["team"],opponent=player["opp"],
                         evidence_lane="original_pregame",operational_eligible=True))
    proof = dict(proof,identity_scope_resolution=dict(schema_version=WITNESS_SCHEMA,
        purpose="IDENTITY_PREIMAGE_ONLY_NOT_CAPTURE_TIME_OR_FORECAST_PROOF",witness=descriptor,
        complete_original_scope_sha256=feed["identity_scope_sha256"],original_validated_rows=len(feed["rows"]),
        current_eligible_rows=len(rows),current_unavailable_counts=unavailable))
    return dict(rows=rows), proof


def validate_feed(feed, p, board, *, now, fetch, root=ROOT):
    policy_check(p, root=root, now=now)
    old.require(type(feed) is dict and set(feed) == old.META_FIELDS | {"publication", "publication_sha256"}
        and feed["schema_version"] == old.VERSION_V2 and feed["state"] == "DERIVED_SELECTED_ONLY"
        and len(old.canonical(feed)) <= old.MAX_BYTES, "V4_V2_WIRE_CONTRACT")
    old.require(board.get("execution_model") == p["current_execution"], "V4_BOARD_CURRENT_EXECUTION")
    old.require(type(feed["season"]) is int and type(feed["week"]) is int
        and (feed["season"],feed["week"]) == (board["season"],board["week"])
        and feed["producer_policy_sha256"] == p["recipe_registration_sha256"]
        and feed["rights_authority_sha256"] in p["rights_authorities"] and feed["r0_identity_sha256"] in p["r0_identities"],
        "V4_STATIC_SCOPE_OR_RECIPE")
    old.require(all(old.h(feed[k]) for k in ("rights_receipt_sha256", "durability_receipt_sha256", "identity_scope_sha256"))
        and old.utc(p["lab_recipe_registered_at_utc"]) <= old.utc(feed["created_at"]) <= old.utc(now) < old.utc(feed["expires_at"])
        and type(feed["rows"]) is list and 0 < len(feed["rows"]) <= 5000, "V4_FEED_CLOCK_OR_BOUND")
    old.require(all(type(r) is dict and set(r) == set(old.overlay().ROW_FIELDS) for r in feed["rows"]),
                "CLOSED_UNIQUE_PUBLIC_ROWS")
    c = feed["coverage"]
    old.require(type(c) is dict and set(c) == {"private_selected_rows", "public_rows", "fallback_counts"}
        and type(c["private_selected_rows"]) is int and 0 < c["private_selected_rows"] <= 5000
        and type(c["public_rows"]) is int and c["public_rows"] == len(feed["rows"])
        and type(c["fallback_counts"]) is dict and set(c["fallback_counts"]) <= {"private_ineligible_R0", "outside_board_R0", "started_R0"}
        and all(type(v) is int and v >= 0 for v in c["fallback_counts"].values())
        and c["private_selected_rows"] == c["public_rows"] + sum(c["fallback_counts"].values()), "CLOSED_PUBLIC_COVERAGE")
    proof = verify_execution(feed, p, now=now, fetch=fetch)
    allowed = declared_catalog(feed["publication"]["version_catalog"], p)
    if WITNESS_FIELD in p:
        return validate_witness_scoped_rows(feed,p,board,now=now,root=root,proof=proof,allowed=allowed)
    offers = old.overlay().board_offers(board)
    games = {game["id"]:game for game in board["games"]}
    players = {(player["game_id"],player["id"]):player for player in board["players"]}
    old.require(len(games) == len(board["games"]) and len(players) == len(board["players"])
        and all(row["game_id"] in games and (row["game_id"],row["player_id"]) in players for row in feed["rows"]),
        "CURRENT_BOARD_SCOPE_CHANGED")
    # The original scope commits identity, teams and kickoff, not market-offer
    # availability. Keep that exact preimage even after an expired offer leaves.
    scope = old.digest([dict(player_id=row["player_id"],game_id=row["game_id"],category=row["category"],
        kickoff=games[row["game_id"]]["kickoff"],team=players[(row["game_id"],row["player_id"])]["team"],
        opponent=players[(row["game_id"],row["player_id"])]["opp"])
        for row in sorted(feed["rows"],key=old.overlay().key)])
    old.require(feed["identity_scope_sha256"] == scope, "CURRENT_BOARD_SCOPE_CHANGED")
    seen = set(); rows = []
    for r in feed["rows"]:
        old.require(type(r) is dict and set(r) == set(old.overlay().ROW_FIELDS), "CLOSED_UNIQUE_PUBLIC_ROWS")
        key = old.overlay().key(r)
        old.require(key not in seen, "CLOSED_UNIQUE_PUBLIC_ROWS"); seen.add(key)
        old.require((r["category"],r["method_id"],r["procedure_version"],r["model_version"]) in allowed,
                    "V4_ROW_NOT_IN_DECLARED_CATALOG")
        old.require(r["source_policy_sha256"] == p["source_policy_sha256"]
            and old.utc(p["lab_recipe_registered_at_utc"]) <= old.utc(r["issued_at"]), "V4_ROW_POLICY_AND_REGISTRATION")
        player, game = players[(r["game_id"],r["player_id"])], games[r["game_id"]]
        active = game.get("state") == "pre" and old.utc(r["valid_until_utc"]) > old.utc(now)
        old.require(not active or key in offers, "V4_ACTIVE_OFFER_MISSING")
        # Validate every original row's type, product, bounds, version and clock.
        # Only expired rows may use their authenticated identity without an offer;
        # they are never returned as eligible selections or given a fabricated prop.
        row_context = offers if key in offers else {key:(player,game,{})}
        old.overlay().validate_row(dict(r, first_prepared_at=feed["created_at"]), row_context)
        old.require(player.get("pos", player.get("position")) in p["public_roles"][r["category"]], "V4_REGISTERED_PLAYER_ROLE")
        if not active:
            continue
        rows.append(dict(r, season=board["season"],week=board["week"],team=player["team"],opponent=player["opp"],
                         evidence_lane="original_pregame",operational_eligible=True))
    return dict(rows=rows), proof


def writer_input(root, p, board, *, website_source_sha, now, feed=None, fetch=old.download):
    try:
        with old.publication_deadline(4):
            policy_check(p, root=root, now=now)
            checked = old.code_review(root, p, website_source_sha)
            if feed is None:
                def strict_fetch(url, cap):
                    raw = fetch(url, cap); old.strict_public_json(raw); return raw
                feed = old.fetch_feed(p, board, fetch=strict_fetch)
            selected, proof = validate_feed(feed, p, board, now=now, fetch=fetch, root=root)
            old.require(old.code_review(root, p, website_source_sha) == checked, "V4_INVENTORY_CHANGED_DURING_VERIFICATION")
        review = dict(schema_version=old.overlay().REVIEW, approved=True, selected_input_sha256=old.digest(selected),
            website_source_sha=website_source_sha, authority_kind="AUTOMATED_REGISTERED_POLICY",human_approval=False,
            authority_policy_sha256=old.digest(p),code_inventory_sha256=checked,feed_sha256=old.digest(feed),reviewed_at=now,
            board_membership_sha256=feed["identity_scope_sha256"],publication_execution=proof,
            current_reference_model=p["current_execution"]["model"],recipe_registration_sha256=p["recipe_registration_sha256"],
            lab_public_policy_sha256=p["lab_public_policy_sha256"],static_registration_sha256=p["static_registration_sha256"])
        return selected, review, dict(state="AUTOMATED_POLICY_ACCEPTED",rows=len(selected["rows"]),
            website_source_sha=website_source_sha,policy_sha256=old.digest(p),review_sha256=old.digest(review),publication_execution=proof)
    except Exception as error:
        reason = str(error) if isinstance(error, old.FeedError) and re.fullmatch(r"[A-Z0-9_]+", str(error)) else "OPTIONAL_FEED_REJECTED"
        return {}, {}, dict(state="CURRENT_REFERENCE_FALLBACK",reason=reason,rows=0,human_approval=False)
