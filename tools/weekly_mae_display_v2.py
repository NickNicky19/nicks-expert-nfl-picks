"""Optional owner-registered MAE point display in the existing website writer.

Five bounded public GETs, no credentials, provider calls, fitting or selection.
Native bytes remain unchanged; board/ranking/incumbent files are read-only.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
import zlib

import weekly_public_feed as common
from weekly_adaptive_overlay import read_bound
import stat_point_mae_public_v2 as wire

VERSION = "weekly-mae-display-publisher-v2"
POLICY = "weekly-mae-display-source-policy-v2"
POINTER = "weekly-mae-display-pointer-v2"
RECEIPT = "weekly-mae-display-public-receipt-v1"
SCOPE = "DISPLAY_ONLY_INCUMBENT_RANKING_UNCHANGED"
PREFIX = "public/stat-point-mae-v1"
POINT_POLICY_SHA256 = "efc3dfa27bd93b12a217417e64f07f1b78a777b0e0fda65f8fe619c34994149f"
WIRE_SHA256 = "72e23e7543902d23bd767929fda60296df82afbcfc82761462f23e940fe7ad10"
VIEW_SHA256 = "48cc101e8a2b4288bebc74bc2015d6140f4181e83ebfe3bbd0a3e87603a12ed5"
TARGETS = ("pass_yd", "pass_int", "rush_rec_yd")
STABLE = [{'target': 'pass_yd', 'scoring_target': 'pass_yd', 'method_id': 'MAE_DISPLAY_LEAF_pass_yd', 'base_learner_id': 'LAB_CDF', 'forecast_product': 'point_median', 'prediction_functional': 'full_cdf_lower_median', 'public_roles': ['QB'], 'source_contract_sha256': '96745d29c180c8f0e8813039544046aa8cad63d39393155bb714461ef6baad19', 'source_policy_sha256': 'e7f54213218031c978c766af7a1a3b22a57c2a424b51f62056742162154fe441', 'model_bytes_sha256': '7048e2231ab9651c2790b7e8ead7a77d6c3dd23ce8ce2decab9512d2d6746a09', 'base_procedure_version': '516b52338abc288032686ebb3387b004abc4ee8dda141eb6952c4ac5eaca6a12', 'original_contract_version': 'weekly-adaptive-release-v1-future-inference'}, {'target': 'pass_int', 'scoring_target': 'pass_int', 'method_id': 'MAE_DISPLAY_LEAF_pass_int', 'base_learner_id': 'LAB_CDF', 'forecast_product': 'point_median', 'prediction_functional': 'full_cdf_lower_median', 'public_roles': ['QB'], 'source_contract_sha256': '96745d29c180c8f0e8813039544046aa8cad63d39393155bb714461ef6baad19', 'source_policy_sha256': 'e7f54213218031c978c766af7a1a3b22a57c2a424b51f62056742162154fe441', 'model_bytes_sha256': '91d40a54ab22178dc7deef7818adf50ae590a33de9bdfc516af7a6c3c6c9ea53', 'base_procedure_version': '516b52338abc288032686ebb3387b004abc4ee8dda141eb6952c4ac5eaca6a12', 'original_contract_version': 'weekly-adaptive-release-v1-future-inference'}, {'target': 'rush_rec_yd', 'scoring_target': 'rush_rec_yd', 'method_id': 'MAE_DISPLAY_LEAF_rush_rec_yd', 'base_learner_id': 'LAB_CDF', 'forecast_product': 'point_median', 'prediction_functional': 'full_cdf_lower_median', 'public_roles': ['RB', 'WR', 'TE'], 'source_contract_sha256': '96745d29c180c8f0e8813039544046aa8cad63d39393155bb714461ef6baad19', 'source_policy_sha256': 'e7f54213218031c978c766af7a1a3b22a57c2a424b51f62056742162154fe441', 'model_bytes_sha256': 'bf5201078c19f1a6050f685634011be5a7ce2dd6d90cc3f4a9f6397f5cc716d6', 'base_procedure_version': '516b52338abc288032686ebb3387b004abc4ee8dda141eb6952c4ac5eaca6a12', 'original_contract_version': 'weekly-adaptive-release-v1-future-inference'}]
RECIPE_RULE = "NATIVE_PREVALUE_CATALOG_PATH_VERSIONS_FIXED_CORE3_WEIGHTS_AND_BASE_PROCEDURE"
POLICY_KEYS = frozenset("schema_version state scope repository public_ref public_prefix registered_at_utc source_policy_sha256 point_policy_sha256 producer registered_recipe registered_recipe_sha256".split())
PRODUCER_KEYS = frozenset("source_sha source_branch workflow_path workflow_sha256 event run_attempt jobs".split())
RECIPE_KEYS = frozenset("schema_version rule profile_registration_sha256 helper_inventory_sha256 entries".split())
RECEIPT_KEYS = frozenset("archive_files_sha256 archive_index_sha256 candidates_sha256 captures_sha256 catalog_completion_sha256 catalog_sha256 categories created_at exporter_proofs_sha256 feed_bytes feed_sha256 fits helper_inventory_sha256 identity_bridge_sha256 jobs legacy_feed_sha256 legacy_selected_sha256 owner_export_receipt_sha256 persistence_completed_at_upper_bound point_policy_sha256 prevalue_catalog_sha256 probability_policy_change producer_proof_sha256 profile_registration_sha256 ranking_policy_change raw_or_models_public readback_completed_at readback_sha256 reader_witness_sha256 restorer_proof_sha256 root_go_sha256 rows run_attempt run_id runtime_source_registry_sha256 runtime_terminal_sha256 schema_version scope source_branch source_policy_sha256 source_registry_sha256 source_sha state unavailable verified_at workflow_sha256".split())
POINTER_KEYS = frozenset("schema_version path sha256 bytes display_board_sha256 published_at".split())
STATUS_KEYS = frozenset("target state original_state reason rows eligible_rows".split())
ACTORS = (("NickNicky19", 208912933), ("github-actions[bot]", 41898282))
RECEIPT_CAP, POLICY_CAP, BOARD_CAP = 64 << 10, 128 << 10, 16 << 20


class DisplayError(ValueError): pass


def require(value, code):
    if not value: raise DisplayError(code)


def canonical(value): return wire.canonical(value)
def sha(body): return common.sha(body)
def digest(value): return wire.digest(value)
def clock(value): return wire.clock(value)


def template():
    """No producer commit/registration is guessed or automatically admitted."""
    recipe = dict(schema_version="weekly-mae-display-prevalue-recipe-v1",rule=RECIPE_RULE,
        profile_registration_sha256=None,helper_inventory_sha256=None,entries=deepcopy(STABLE))
    return dict(schema_version=POLICY,state="PREPARED_UNREGISTERED",scope=SCOPE,
        repository=common.REPOSITORY,public_ref="lab-state",public_prefix=PREFIX,registered_at_utc=None,
        source_policy_sha256=STABLE[0]["source_policy_sha256"],point_policy_sha256=POINT_POLICY_SHA256,
        producer=dict(source_sha=None,source_branch=None,workflow_path=".github/workflows/lab.yml",workflow_sha256=None,
            event="workflow_dispatch",run_attempt=1,jobs=dict(produce=None,restore=None,consume=None)),
        registered_recipe=recipe,registered_recipe_sha256=None)


def policy_check(p, now):
    require(type(p) is dict and set(p)==POLICY_KEYS and p["schema_version"]==POLICY and p["state"]=="ROOT_REGISTERED"
        and p["scope"]==SCOPE and p["repository"]==common.REPOSITORY and p["public_ref"]=="lab-state"
        and p["public_prefix"]==PREFIX and p["source_policy_sha256"]==STABLE[0]["source_policy_sha256"]
        and p["point_policy_sha256"]==POINT_POLICY_SHA256,"MAE_REGISTERED_SOURCE_POLICY_REQUIRED")
    require(clock(p["registered_at_utc"])<=clock(now),"MAE_POLICY_CLOCK")
    a=p["producer"]
    require(type(a) is dict and set(a)==PRODUCER_KEYS and type(a["source_sha"]) is str
        and re.fullmatch(r"[a-f0-9]{40}",a["source_sha"]) and wire.h(a["workflow_sha256"])
        and type(a["source_branch"]) is str and re.fullmatch(r"[A-Za-z0-9_./-]{1,160}",a["source_branch"])
        and not any(x in {"",".",".."} for x in a["source_branch"].split("/"))
        and a["workflow_path"]==".github/workflows/lab.yml" and a["event"]=="workflow_dispatch"
        and type(a["run_attempt"]) is int and a["run_attempt"]==1,"MAE_EXACT_REGISTERED_PRODUCER_REQUIRED")
    require(type(a["jobs"]) is dict and set(a["jobs"])=={"produce","restore","consume"}
        and all(type(v) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,100}",v) for v in a["jobs"].values())
        and len(set(a["jobs"].values()))==3,"MAE_REGISTERED_JOB_ROLES_REQUIRED")
    r=p["registered_recipe"]
    require(type(r) is dict and set(r)==RECIPE_KEYS and r["schema_version"]=="weekly-mae-display-prevalue-recipe-v1"
        and r["rule"]==RECIPE_RULE and r["entries"]==STABLE
        and wire.h(r["profile_registration_sha256"]) and wire.h(r["helper_inventory_sha256"])
        and p["registered_recipe_sha256"]==digest(r),"MAE_PREVALUE_REGISTERED_CORE3_RECIPE_REQUIRED")
    here=Path(__file__).resolve().parent
    require(sha((here/"stat_point_mae_public_v2.py").read_bytes())==WIRE_SHA256
        and sha((here/"next_checkpoint_median_policy_v2_view.py").read_bytes())==VIEW_SHA256,
        "MAE_FROZEN_WIRE_SOURCE_REQUIRED")
    return p


def receipt(encoded, feed, body, p):
    require(type(encoded) is bytes and 18<=len(encoded)<=RECEIPT_CAP
        and encoded[:4]==b"\x1f\x8b\x08\x00" and encoded[4:8]==b"\x00"*4,"MAE_ORIGINAL_RECEIPT_GZIP_REQUIRED")
    decoder=zlib.decompressobj(16+zlib.MAX_WBITS);raw=decoder.decompress(encoded,RECEIPT_CAP+1)
    require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail and len(raw)<=RECEIPT_CAP,
        "MAE_SINGLE_BOUNDED_RECEIPT_GZIP_REQUIRED")
    r=wire.strict_json(raw);a=p["producer"];recipe=p["registered_recipe"]
    require(type(r) is dict and set(r)==RECEIPT_KEYS and raw==canonical(r) and r["schema_version"]==RECEIPT
        and r["scope"]==SCOPE and r["state"]=="POINT_SUBSET_VERIFIED"
        and all(wire.h(v) for k,v in r.items() if k.endswith("sha256"))
        and r["source_sha"]==a["source_sha"] and r["source_branch"]==a["source_branch"]
        and r["workflow_sha256"]==a["workflow_sha256"] and r["point_policy_sha256"]==POINT_POLICY_SHA256
        and r["source_policy_sha256"]==p["source_policy_sha256"]
        and r["profile_registration_sha256"]==recipe["profile_registration_sha256"]
        and r["helper_inventory_sha256"]==recipe["helper_inventory_sha256"]
        and type(r["run_id"]) is str and re.fullmatch(r"[1-9][0-9]{0,19}",r["run_id"])
        and type(r["run_attempt"]) is int and r["run_attempt"]==1 and type(r["fits"]) is int and r["fits"]==0
        and r["raw_or_models_public"] is r["probability_policy_change"] is r["ranking_policy_change"] is False,
        "MAE_EXACT_NATIVE_RECEIPT_REQUIRED")
    require(r["feed_sha256"]==sha(body) and type(r["feed_bytes"]) is int and r["feed_bytes"]==len(body)
        and type(r["rows"]) is int and r["rows"]==len(feed["rows"])
        and r["created_at"]==feed["created_at"] and r["catalog_sha256"]==feed["catalog_sha256"]
        and r["source_registry_sha256"]==feed["source_registry_sha256"]
        and r["owner_export_receipt_sha256"]==feed["owner_export_receipt_sha256"]
        and r["owner_export_receipt_sha256"]==digest({k:v for k,v in r.items()
            if k not in {"owner_export_receipt_sha256","feed_sha256","feed_bytes","rows"}}),
        "MAE_FEED_RECEIPT_OWNER_EXPORT_HASH_REQUIRED")
    require(type(r["jobs"]) is dict and set(r["jobs"])==set(a["jobs"])
        and all(type(j) is dict and set(j)=={"job_id","api_job_id"} and j["job_id"]==a["jobs"][role]
            and type(j["api_job_id"]) is int and j["api_job_id"]>0 for role,j in r["jobs"].items())
        and len({j["api_job_id"] for j in r["jobs"].values()})==3,"MAE_RECEIPT_NATIVE_JOB_BINDINGS_REQUIRED")
    categories=sorted({row["target"] for row in feed["rows"]})
    require(r["categories"]==categories and set(categories)<=set(TARGETS)
        and type(r["unavailable"]) is list and len(r["unavailable"])<=3,"MAE_CLOSED_CATEGORY_SUBSET_REQUIRED")
    absent=[]
    for s in r["unavailable"]:
        require(type(s) is dict and set(s)==STATUS_KEYS and s["target"] in TARGETS
            and s["state"] in {"MAE_UNAVAILABLE","FAILED_RETAINED","INVALID_CAPTURE_RETAINED"}
            and s["original_state"] in {None,"CAPTURED","FAILED_RETAINED"}
            and (s["reason"] is None or type(s["reason"]) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}",s["reason"]))
            and type(s["rows"]) is type(s["eligible_rows"]) is int and s["eligible_rows"]==0 and 0<=s["rows"]<=1000,
            "MAE_CLOSED_UNAVAILABLE_CATEGORY_REQUIRED")
        absent.append(s["target"])
    require(len(absent)==len(set(absent)) and set(absent)==set(TARGETS)-set(categories),"MAE_COMPLETE_CATEGORY_STATUS_REQUIRED")
    return r


def registered_members(feed,r,p):
    catalog=feed["catalog"];registry=feed["source_registry"];entries=catalog["entries"]
    require(catalog["owner_admission_receipt_sha256"]==registry["owner_admission_receipt_sha256"]==r["root_go_sha256"]
        and len(entries)==len(r["categories"]) and {e["target"] for e in entries}==set(r["categories"]),
        "MAE_NATIVE_PREVALUE_CATALOG_ROOT_REQUIRED")
    require(clock(p["registered_at_utc"])<=clock(catalog["registered_at"])<=clock(registry["registered_at"]),
        "MAE_RECIPE_MUST_PRECEDE_NATIVE_VALUES")
    for e in entries:
        stable=next(s for s in STABLE if s["target"]==e["target"])
        require(all(e[k]==v for k,v in stable.items()),"MAE_UNREGISTERED_MODEL_PROCEDURE_OR_ROLE")
    seen=set()
    for s in registry["records"]:
        key=(s["target"],s["model_version"],s["procedure_version"],s["query_projection_sha256"])
        require(key not in seen,"MAE_AMBIGUOUS_SOURCE_REGISTRY");seen.add(key)
        entry=next((e for e in entries if e["target"]==s["target"]),None)
        require(entry is not None and all(s[k]==entry[k] for k in set(wire.SOURCE_KEYS)&set(wire.ENTRY_KEYS))
            and s["identity_bridge_sha256"]==r["identity_bridge_sha256"]
            and s["feature_binding_sha256"]==s["query_source_sha256"],"MAE_SOURCE_OUTSIDE_REGISTERED_RECIPE")
    used=set()
    for row in feed["rows"]:
        used.add((row["target"],row["model_version"],row["procedure_version"],row["query_projection_sha256"]))
        require(row["forecast_product"]=="point_median" and row["prediction_functional"]=="full_cdf_lower_median"
            and row["selection_sha256"]==r["prevalue_catalog_sha256"] and row["identity_bridge_sha256"]==r["identity_bridge_sha256"]
            and row["source_policy_sha256"]==p["source_policy_sha256"]
            and clock(row["feature_capture_completed_at"])<=clock(registry["registered_at"])<=clock(row["issued_at"])
            and clock(row["persistence_completed_at"])==clock(r["persistence_completed_at_upper_bound"])
            and clock(row["readback_completed_at"])==clock(r["readback_completed_at"]),"MAE_ROW_ORIGINAL_CAPTURE_BINDINGS_REQUIRED")
    require(seen==used and all(len({s[k] for s in registry["records"]})==1
        for k in ("source_receipt_sha256","feature_binding_sha256","query_source_sha256")),"MAE_ONE_NATIVE_SHARED_SOURCE_CAPTURE_REQUIRED")


def native_execution(feed,r,p,*,now,fetch):
    a=p["producer"];url="https://api.github.com/repos/"+common.REPOSITORY+"/actions/runs/"+r["run_id"]
    run_raw=fetch(url,1<<20);jobs_raw=fetch(url+"/jobs?per_page=100&page=1",1<<20)
    run=common.strict_public_json(run_raw);data=common.strict_public_json(jobs_raw)
    actor=run.get("actor",{});trigger=run.get("triggering_actor",{})
    require(type(run.get("id")) is int and run["id"]==int(r["run_id"])
        and run.get("repository",{}).get("full_name")==common.REPOSITORY
        and run.get("head_repository",{}).get("full_name")==common.REPOSITORY
        and run.get("head_sha")==a["source_sha"] and run.get("head_branch")==a["source_branch"]
        and run.get("path")==a["workflow_path"] and run.get("event")==a["event"]
        and type(run.get("run_attempt")) is int and run["run_attempt"]==1
        and run.get("status")=="completed" and run.get("conclusion")=="success"
        and type(actor.get("id")) is int and (actor.get("login"),actor["id"]) in ACTORS
        and type(trigger.get("id")) is int and (trigger.get("login"),trigger["id"])==(actor["login"],actor["id"]),
        "MAE_COMPLETED_NATIVE_SOURCE_RUN_REQUIRED")
    require(type(data) is dict and type(data.get("jobs")) is list and type(data.get("total_count")) is int
        and data["total_count"]==len(data["jobs"])<=100,"MAE_COMPLETE_NATIVE_JOB_LIST_REQUIRED")
    chain=[]
    for role in ("produce","restore","consume"):
        found=[j for j in data["jobs"] if j.get("name")==a["jobs"][role]]
        require(len(found)==1,"MAE_UNIQUE_NATIVE_JOB_ROLE_REQUIRED");j=found[0]
        require(type(j.get("id")) is int and j["id"]==r["jobs"][role]["api_job_id"]
            and type(j.get("run_id")) is int and j["run_id"]==int(r["run_id"])
            and j.get("head_sha")==a["source_sha"] and type(j.get("run_attempt")) is int and j["run_attempt"]==1
            and j.get("status")=="completed" and j.get("conclusion")=="success"
            and clock(j["started_at"])<=clock(j["completed_at"]),"MAE_EXACT_COMPLETED_NATIVE_JOB_REQUIRED")
        chain.append(j)
    producer,reader,exporter=chain
    require(clock(run["created_at"])<=clock(run["run_started_at"])<=clock(producer["started_at"])
        <=clock(producer["completed_at"])<=clock(reader["started_at"])<=clock(reader["completed_at"])
        <=clock(exporter["started_at"])<=clock(r["verified_at"])==clock(r["readback_completed_at"])
        <=clock(feed["created_at"])<=clock(exporter["completed_at"])<=clock(run["updated_at"])<=clock(now)
        and clock(r["persistence_completed_at_upper_bound"])==clock(producer["completed_at"])
        and clock(producer["started_at"])<=clock(feed["catalog"]["registered_at"]),"MAE_NATIVE_CAPTURE_JOB_CLOCKS_REQUIRED")
    for row in feed["rows"]:
        require(clock(producer["started_at"])<=clock(row["information_cutoff_utc"])<=clock(row["issued_at"])
            <=clock(producer["completed_at"])<clock(row["issue_deadline_utc"]),"MAE_ACTUAL_DURABLE_NATIVE_PERSISTENCE_BEFORE_DEADLINE")
    return dict(run_id=r["run_id"],source_sha=a["source_sha"],jobs=deepcopy(r["jobs"]),
        run_response_sha256=sha(run_raw),jobs_response_sha256=sha(jobs_raw),GHA_metadata_GETs=2)


def board_clock(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d{1,6})?)?(?:Z|\+00:00)",value),"MAE_EXACT_BOARD_UTC_REQUIRED")
    return datetime.fromisoformat(value.replace("Z","+00:00"))


def board_id(value):
    require(type(value) is str and wire.ident(value) or type(value) is int and value>0,"MAE_EXACT_BOARD_ID_REQUIRED")
    return str(value)


def board_membership(feed,board):
    require(type(board) is dict and type(board.get("season")) is type(board.get("week")) is int
        and (feed["season"],feed["week"])==(board["season"],board["week"])
        and type(board.get("games")) is list and 0<len(board["games"])<=32
        and type(board.get("players")) is list and 0<len(board["players"])<=10000,"MAE_CURRENT_BOARD_PERIOD_REQUIRED")
    games={};players={}
    for g in board["games"]:
        key=board_id(g["id"])
        require(key not in games and wire.ident(g["home"]) and wire.ident(g["away"]) and g["home"]!=g["away"],"MAE_UNIQUE_BOARD_GAME_REQUIRED")
        board_clock(g["kickoff"]);games[key]=g
    for player in board["players"]:
        key=(board_id(player["game_id"]),board_id(player["id"]))
        require(key not in players,"MAE_UNIQUE_BOARD_PLAYER_REQUIRED");players[key]=player
    for row in feed["rows"]:
        player=players.get((row["website_game_id"],row["sleeper_id"]));game=games.get(row["website_game_id"])
        require(player is not None and game is not None and player.get("team")==row["team"]
            and player.get("opp")==row["opponent"] and player.get("pos")==row["position"]
            and {row["team"],row["opponent"]}=={game["home"],game["away"]}
            and board_clock(game["kickoff"])==clock(row["kickoff_utc"]),"MAE_EXACT_CURRENT_BOARD_IDENTITY_REQUIRED")
    return len(feed["rows"])


def fetch_pair(p,board,*,now,fetch=common.download):
    policy_check(p,now);calls=[]
    def get(url,cap):
        require(len(calls)<5,"MAE_FIVE_PUBLIC_GET_LIMIT");calls.append(url)
        body=fetch(url,cap);require(type(body) is bytes and 0<len(body)<=cap,"MAE_PUBLIC_RESPONSE_BOUND")
        return body
    period=f"{board['season']}-W{board['week']:02d}";path=f"state/{PREFIX}/{period}"
    url="https://api.github.com/repos/"+common.REPOSITORY+"/contents/"+path+"?ref=lab-state"
    with common.publication_deadline(20):
        listing=common.strict_public_json(get(url,1<<20))
        require(type(listing) is list and 0<len(listing)<1000,"MAE_BOUNDED_IMMUTABLE_DIRECTORY_REQUIRED")
        found=[]
        for item in listing:
            require(type(item) is dict,"MAE_IMMUTABLE_DIRECTORY_FORMAT")
            name=item.get("name","");match=re.fullmatch(r"(\d{8}T\d{6}\.\d{6}Z)--([a-f0-9]{64})\.json",name)
            require(match and item.get("type")=="file" and item.get("path")==path+"/"+name,"MAE_IMMUTABLE_DIRECTORY_FORMAT")
            found.append((name,match[1],match[2]))
        require(len({n for n,_,_ in found})==len(found),"MAE_DUPLICATE_DIRECTORY_ENTRY")
        name,stamp,expected=max(found)
        raw="https://raw.githubusercontent.com/"+common.REPOSITORY+"/lab-state/"
        body=get(raw+path+"/"+name,wire.MAX_BYTES);require(sha(body)==expected,"MAE_NATIVE_FEED_HASH_REQUIRED")
        feed=wire.strict_json(body);wire.validate_feed(feed)
        require(body==canonical(feed) and clock(feed["created_at"])<=clock(now)
            and clock(feed["created_at"]).strftime("%Y%m%dT%H%M%S.%fZ")==stamp,"MAE_EXACT_ORIGINAL_NATIVE_FEED_FORMAT")
        encoded=get(raw+f"state/{PREFIX}/receipts/{expected}.json.gz",RECEIPT_CAP)
        r=receipt(encoded,feed,body,p);registered_members(feed,r,p)
        proof=native_execution(feed,r,p,now=now,fetch=get)
    joined=board_membership(feed,board)
    return feed,body,dict(native_receipt_sha256=sha(encoded),native_receipt_body_sha256=digest(r),
        native_feed_sha256=expected,matched_rows=joined,public_GETs=len(calls),native_execution=proof)


def safe_path(root,path):
    require(not any(p.is_symlink() for p in (path,*path.parents)) and path.resolve().is_relative_to(root.resolve()),"MAE_LOCAL_PATH_SCOPE")


def local_document(root,path,cap,expected=None):
    safe_path(root,path);_,physical=read_bound(path,expected,limit=cap)
    body=path.read_bytes();require(len(body)<=cap and sha(body)==physical,"MAE_LOCAL_READ_RACE")
    return common.strict_public_json(body),body,physical


def publish(root,policy_path,policy_sha256,*,website_source_sha,now,fetch=common.download,atomic_json=None):
    """Existing leased writer only. Failure never rebinds an old pointer."""
    root=Path(root).resolve();result=dict(schema_version=VERSION+"-receipt",state="INCUMBENT_FALLBACK",reason="OPTIONAL_MAE_DISPLAY_REJECTED",rows=0)
    if atomic_json is None:
        from reliability import atomic_json
    try:
        require(type(website_source_sha) is str and re.fullmatch(r"[a-f0-9]{40}",website_source_sha) and wire.h(policy_sha256),"MAE_PINNED_WRITER_INPUTS_REQUIRED")
        clock(now);path=Path(policy_path);path=path if path.is_absolute() else root/path
        p,_,_=local_document(root,path,POLICY_CAP,policy_sha256);policy_check(p,now)
        board_path=root/"output/data/week.json";board,_,board_sha=local_document(root,board_path,BOARD_CAP)
        require(type(board.get("season")) is type(board.get("week")) is int and 1<=board["week"]<=22,"MAE_BOARD_PERIOD_REQUIRED")
        feed,body,proof=fetch_pair(p,board,now=now,fetch=fetch)
        asset=root/"output/data/weekly-mae-display"/(sha(body)+".json");safe_path(root,asset)
        require(local_document(root,board_path,BOARD_CAP)[2]==board_sha,"MAE_BOARD_CHANGED_BEFORE_ASSET")
        if asset.exists():require(asset.read_bytes()==body,"MAE_IMMUTABLE_NATIVE_ASSET_COLLISION")
        else:atomic_json(asset,feed)
        require(asset.read_bytes()==body,"MAE_NATIVE_ASSET_SERIALIZER_CHANGED")
        pointer=dict(schema_version=POINTER,path="data/weekly-mae-display/"+sha(body)+".json",sha256=sha(body),bytes=len(body),
            display_board_sha256=board_sha,published_at=now)
        require(set(pointer)==POINTER_KEYS,"MAE_SIX_FIELD_POINTER_REQUIRED")
        # An exact board read is repeated after added immutable writes. A
        # source failure never stamps a previous point feed onto a new board.
        require(local_document(root,board_path,BOARD_CAP)[2]==board_sha,"MAE_BOARD_CHANGED_BEFORE_POINTER")
        require(local_document(root,path,POLICY_CAP,policy_sha256)[2]==policy_sha256,"MAE_POLICY_CHANGED_BEFORE_POINTER")
        audit=dict(schema_version=VERSION+"-audit",state="VALIDATED_FOR_ATOMIC_POINTER",website_source_sha=website_source_sha,
            at=now,policy_sha256=policy_sha256,display_board_sha256=board_sha,feed_sha256=sha(body),**proof)
        audit_path=root/"data/weekly-mae-display-audit"/(digest(audit)+".json");safe_path(root,audit_path)
        require(len(canonical(audit))<=32<<10,"MAE_BOUNDED_TECHNICAL_RECEIPT")
        if audit_path.exists():require(audit_path.read_bytes()==canonical(audit),"MAE_IMMUTABLE_AUDIT_COLLISION")
        else:atomic_json(audit_path,audit)
        pointer_path=root/"output/data/weekly-mae-display.json";safe_path(root,pointer_path)
        # The existing writer's lease serializes board/pointer writes. The
        # pointer also carries its exact board hash for independent UI checks.
        require(local_document(root,board_path,BOARD_CAP)[2]==board_sha,"MAE_BOARD_CHANGED_AT_POINTER_BOUNDARY")
        require(local_document(root,path,POLICY_CAP,policy_sha256)[2]==policy_sha256,"MAE_POLICY_CHANGED_AT_POINTER_BOUNDARY")
        atomic_json(pointer_path,pointer)
        require(local_document(root,pointer_path,16<<10)[0]==pointer,"MAE_POINTER_READBACK_REQUIRED")
        require(local_document(root,board_path,BOARD_CAP)[2]==board_sha,"MAE_BOARD_CHANGED_AFTER_POINTER")
        return dict(result,state="POINT_DISPLAY_PERSISTED",reason=None,rows=len(feed["rows"]),feed_sha256=sha(body),
            display_board_sha256=board_sha,policy_sha256=policy_sha256,audit_sha256=digest(audit),public_GETs=proof["public_GETs"],
            GHA_metadata_GETs=2,model_adoption=False)
    except Exception as error:
        if isinstance(error,DisplayError) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}",str(error)):result["reason"]=str(error)
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--policy",type=Path,required=True);parser.add_argument("--policy-sha256",required=True)
    parser.add_argument("--website-source-sha",required=True)
    args=parser.parse_args(argv)
    result=publish(args.root,args.policy,args.policy_sha256,website_source_sha=args.website_source_sha,now=datetime.now(timezone.utc).isoformat())
    print(json.dumps(result,sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())
