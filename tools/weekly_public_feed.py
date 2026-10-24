"""Derived-only selected feed and policy-driven website input adapter.

Portable as tools/weekly_public_feed.py in the website. No model/outcome API.
Private validation imports are used only by the lab exporter.
"""
from __future__ import annotations
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import re
import signal
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

VERSION="weekly-derived-selected-feed-v1"
POLICY="weekly-derived-selected-policy-v1"
VERSION_V2="weekly-derived-selected-feed-v2"
POLICY_V2="weekly-derived-selected-policy-v2"
AUTHORITY_V2="weekly-derived-publication-authority-v2"
PUBLICATION_V2="weekly-derived-publication-v2"
CATALOG_V2="weekly-generic-future-producer-v1-selected-version-catalog"
REPOSITORY="NickNicky19/NFL-forecasting"
PUBLICATION_FIELDS={"schema_version","authority_sha256","repository","source_sha","run_id","run_attempt","workflow_path","export_job","api_job_id",
    "selected_body_sha256","source_version_catalog_sha256","version_catalog_sha256","version_catalog"}
MAX_BYTES=4<<20
META_FIELDS={"schema_version","state","season","week","created_at","expires_at","producer_policy_sha256","rights_authority_sha256","rights_receipt_sha256","durability_receipt_sha256","r0_identity_sha256","identity_scope_sha256","rows","coverage"}
ENGINE_FILES={"pull/build.py","pull/matchup.py","pull/scoring.py","pull/books.py","pull/gamemodel.py","pull/sources.py","pull/news.py"}
CODE_FILES=ENGINE_FILES|{"config/release-mode.json","tools/reliability.py","tools/weekly_adaptive_overlay.py","tools/weekly_public_feed.py","output/app.js","output/weekly-adaptive-overlay.js"}


class FeedError(ValueError):pass
def require(value,reason):
    if not value:raise FeedError(reason)
def canonical(doc):return json.dumps(doc,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def digest(doc):return hashlib.sha256(canonical(doc)).hexdigest()
def sha(body):return hashlib.sha256(body).hexdigest()
def utc(value):
    require(type(value) is str,"CLOCK_REQUIRED")
    result=datetime.fromisoformat(value.replace("Z","+00:00"));require(result.tzinfo is not None,"CLOCK_REQUIRED")
    return result.astimezone(timezone.utc)
def h(value):return type(value) is str and bool(re.fullmatch(r"[a-f0-9]{64}",value))
def overlay():return importlib.import_module("nfl_lab.weekly_website_overlay" if __package__=="nfl_lab" else "weekly_adaptive_overlay")


def policy_check(policy):
    if policy.get("schema_version")==POLICY_V2:return policy_check_v2(policy)
    require(policy.get("schema_version")==POLICY and policy.get("registration_id")=="weekly-adaptive-release-v1","POLICY_CONTRACT")
    require(policy.get("public_fields")==list(overlay().ROW_FIELDS) and "fantasy_ppr" not in policy.get("procedures",{}),"PUBLIC_SCOPE")
    require(policy.get("rights_authorities") and all(h(v) for v in policy["rights_authorities"]),"RIGHTS_REGISTRATION_PENDING")
    require(policy.get("r0_identities") and all(h(v) for v in policy["r0_identities"]),"R0_FREEZE_PENDING")
    require(h(policy.get("producer_policy_sha256")) and h(policy.get("source_policy_sha256")),"POLICY_SOURCE_HASH")
    require(set(policy.get("engine_sha256",{}))==ENGINE_FILES and set(policy.get("website_code_sha256",{}))==CODE_FILES
        and all(h(v) for v in policy["website_code_sha256"].values())
        and all(policy["engine_sha256"][k]==policy["website_code_sha256"][k] for k in ENGINE_FILES),"REGISTERED_ENGINE_INVENTORY")
    keys={"method_id","model_version","procedure_version","product","source_policy_sha256"}
    require(set(policy.get("public_roles",{}))==set(policy["procedures"]),"REGISTERED_ROLE_SCOPE")
    for target,entries in policy["procedures"].items():
        require(target in overlay().PRODUCTS and isinstance(entries,list) and entries,"REGISTERED_PROCEDURE_SCOPE")
        for entry in entries:
            require(set(entry)==keys and all(h(entry[k]) for k in ["model_version","procedure_version","source_policy_sha256"])
                and entry["product"]==overlay().PRODUCTS[target][0] and entry["source_policy_sha256"]==policy["source_policy_sha256"]
                and type(entry["method_id"]) is str and bool(re.fullmatch(r"[A-Z0-9_]{1,100}",entry["method_id"])),"REGISTERED_PROCEDURE_SCOPE")


def member(policy,row):
    require(policy.get("schema_version")!=POLICY_V2,"VERIFIED_ISSUED_CATALOG_REQUIRED")
    candidates=policy["procedures"].get(row["category"],[])
    require(any(all(row.get(k)==value for k,value in allowed.items()) for allowed in candidates),"PROCEDURE_NOT_REGISTERED")


def identity_scope(rows,board):
    offers=overlay().board_offers(board)
    return digest([dict(player_id=r["player_id"],game_id=r["game_id"],category=r["category"],kickoff=offers[overlay().key(r)][1]["kickoff"],
        team=offers[overlay().key(r)][0]["team"],opponent=offers[overlay().key(r)][0]["opp"]) for r in sorted(rows,key=overlay().key)])


def private_gates(bundle,policy,*,now,durable_acceptance=None):
    """Validate metadata BEFORE any selected JSONL is decoded by the CLI."""
    policy_check(policy)
    if policy.get("schema_version")==POLICY_V2:require(durable_acceptance is not None,"LIVE_DURABILITY_VERIFIER_REQUIRED_FOR_V2")
    now=utc(now);terminal=bundle["terminal"];completion=bundle["completion"];decision=bundle["decision"]
    source_contract=policy["private_source_schemas"].get(terminal["schema_version"])
    require(source_contract is not None and terminal["state"]==source_contract["selected_state"]
        and terminal.get("fatal") is None and terminal["selected"]==completion and completion["state"]=="PERSISTED","SELECTED_COMPLETION_REQUIRED")
    require(terminal["startup_policy"]["sha256"]==policy["producer_policy_sha256"] and terminal["decision"]["sha256"]==bundle["decision_body_sha256"],"REGISTERED_DECISION_REQUIRED")
    parent=bundle["parent_capture"]
    require(terminal["parent_capture"]["sha256"]==bundle["parent_capture_body_sha256"]
        and parent["state"]==source_contract["parent_state"] and parent["schema_version"]==source_contract["parent_schema"] and parent.get("fatal") is None
        and utc(parent["actual_completed_at"])<=utc(completion["persist_started_at"]),"REGISTERED_CAPTURE_SOURCE_REQUIRED")
    if source_contract["choice_order"]=="AFTER_PARENT_CAPTURE":
        require(utc(parent["actual_completed_at"])<=utc(terminal["decision_persist_completed_at"]),"INITIAL_STARTUP_CHOICE_ORDER")
    else:
        require(source_contract["choice_order"]=="BEFORE_PARENT_CAPTURE"
            and utc(terminal["decision_persist_completed_at"])<=utc(parent["actual_completed_at"]),"GENERIC_WEEKLY_CHOICE_ORDER")
    rights=bundle["rights"];r0=bundle["r0"]
    require(rights.get("schema_version")=="weekly-derived-selected-rights-v1" and rights.get("state")=="SOURCE_REVIEW_ACCEPTED"
        and rights.get("authority_kind")=="REGISTERED_SOURCE_RIGHTS_POLICY" and rights.get("authority_policy_sha256") in policy["rights_authorities"]
        and rights.get("selected_sha256")==completion["binding"]["sha256"] and rights.get("source_policy_sha256")==policy["source_policy_sha256"]
        and rights.get("scope")=="SELECTED_DERIVED_ONLY" and rights.get("public_fields")==policy["public_fields"] and utc(rights["reviewed_at"])<=now,"SOURCE_RIGHTS_REQUIRED")
    require(r0.get("schema_version")=="weekly-actual-r0-freeze-v1" and r0.get("state")=="ACTUAL_FIRST_RELEASE_R0_FROZEN"
        and digest(r0) in policy["r0_identities"] and type(r0.get("deployment_id")) is int and r0["deployment_id"]>0
        and re.fullmatch(r"[a-f0-9]{40}",r0.get("deployed_source_sha","")) and h(r0.get("visible_board_sha256"))
        and r0.get("engine_sha256")==policy["engine_sha256"] and utc(r0["frozen_at"])<=now,"ACTUAL_R0_FREEZE_REQUIRED")
    from . import weekly_durable_acceptance as acceptance
    durable=bundle["durability"]
    accepted=acceptance.check(bundle,policy,now=now.isoformat(),live=durable_acceptance)
    restored=durable["restore_proof"]
    require(restored["payload_sha256"]==completion["binding"]["sha256"] and restored["bytes"]==completion["binding"]["bytes"],"EXACT_DURABLE_BODY_REQUIRED")
    completed=max(map(utc,[completion["completed_at"],terminal["selected_body_and_receipt_persist_completed_at"],terminal["actual_completed_at"],restored["created_at_utc"]]))
    require(utc(terminal["decision_persist_completed_at"])<=utc(completion["persist_started_at"])<=utc(completion["completed_at"])<=completed<=now,"ACTUAL_COMPLETION_CLOCK")
    return completed,accepted


def export_rows(rows,bundle,policy,board,*,now,durable_acceptance=None,version_catalog_body=None):
    """Never rewrites original rows or repairs their pending publication flags."""
    if policy.get("schema_version")==POLICY_V2:
        return export_rows_v2(rows,bundle,policy,board,now=now,durable_acceptance=durable_acceptance,version_catalog_body=version_catalog_body)
    persisted,accepted=private_gates(bundle,policy,now=now,durable_acceptance=durable_acceptance);api=overlay();offers=api.board_offers(board);result=[];counts={};seen=set()
    from .weekly_private_selected import identity_map
    bridge=identity_map(bundle["bridge"])
    require(len(rows)==bundle["completion"]["rows"]<=5000,"EXACT_SELECTED_ROW_COUNT")
    def count(reason):counts[reason]=counts.get(reason,0)+1
    for source in rows:
        require(not {"actual","loss","label","brier","crps","log_score"}&set(source),"OUTCOME_FIELD_FORBIDDEN")
        require(source["evidence_lane"]=="original_pregame" and source["source_policy_sha256"]==policy["source_policy_sha256"],"ORIGINAL_SOURCE_REQUIRED")
        require(utc(source["source_capture_completed_at"])<=utc(source["issued_at"])<=persisted<=utc(source["source_cutoff_utc"])<utc(source["kickoff_utc"]),"ORIGINAL_CUTOFF_NOT_REPAIRABLE")
        original=bridge.get((source["game_id"],source["player_id"]))
        require(original is not None and all(source.get(k)==v for k,v in original.items()),"EXACT_ORIGINAL_IDENTITY_BRIDGE")
        decision_completed=bundle["terminal"]["decision_persist_completed_at"]
        require(utc(source.get("decision_persist_completed_at",decision_completed))==utc(decision_completed)
            and utc(decision_completed)<=utc(source["issued_at"]),"DECISION_MUST_PRECEDE_ISSUANCE")
        if not(source["operational_eligible"] is True and source["primary_role"] is True and source["public_initial_scope_eligible"] is True):count("private_ineligible_R0");continue
        require(source["category"] in api.PRODUCTS,"PPR_OR_UNSUPPORTED_PUBLIC_TARGET")
        require(source.get("position") in policy["public_roles"].get(source["category"],[]),"REGISTERED_ROLE_SCOPE")
        row={name:source[name] for name in api.ROW_FIELDS if name in source}
        if bundle["terminal"]["schema_version"]!="weekly-private-selected-policy-v1":require(h(source.get("selection_sha256")),"EXPLICIT_GENERIC_SELECTION_REQUIRED")
        row.update(player_id=source["website_player_id"],game_id=source["website_game_id"],selection_sha256=source.get("selection_sha256",source.get("decision_sha256")),
            persistence_completed_at=persisted.isoformat(),valid_until_utc=source.get("valid_until_utc",source["kickoff_utc"]))
        require(h(row["selection_sha256"]) and (source.get("selection_sha256") is not None or row["selection_sha256"]==digest(bundle["decision"])),"SELECTION_IDENTITY_REQUIRED")
        require(set(row)==set(api.ROW_FIELDS),"PUBLIC_FIELD_PROJECTION")
        key=api.key(row);require(key not in seen,"DUPLICATE_SELECTED_IDENTITY");seen.add(key)
        if key not in offers:count("outside_board_R0");continue
        player,game,_=offers[key]
        require(source["season"]==board["season"] and source["week"]==board["week"] and source["team"]==player["team"] and source["opponent"]==player["opp"],"EXACT_BOARD_MEMBERSHIP")
        member(policy,row)
        if game.get("state")!="pre" or utc(row["kickoff_utc"])<=utc(now):count("started_R0");continue
        api.validate_row(dict(row,first_prepared_at=now),offers)
        result.append(row)
    require(result,"NO_ELIGIBLE_PUBLIC_ROWS")
    feed=dict(schema_version=VERSION,state="DERIVED_SELECTED_ONLY",season=board["season"],week=board["week"],created_at=now,
        expires_at=max((r["valid_until_utc"] for r in result),key=utc),producer_policy_sha256=policy["producer_policy_sha256"],
        rights_authority_sha256=bundle["rights"]["authority_policy_sha256"],rights_receipt_sha256=digest(bundle["rights"]),
        durability_receipt_sha256=digest(accepted),r0_identity_sha256=digest(bundle["r0"]),
        identity_scope_sha256=identity_scope(result,board),rows=result,coverage=dict(private_selected_rows=len(rows),public_rows=len(result),fallback_counts=counts))
    require(len(canonical(feed))<=MAX_BYTES,"PUBLIC_FEED_BYTE_CAP")
    return feed


def validate_feed(feed,policy,board,*,now,fetch=None):
    if policy.get("schema_version")==POLICY_V2:return validate_feed_v2(feed,policy,board,now=now,fetch=fetch or download)[0]
    policy_check(policy);api=overlay();require(set(feed)==META_FIELDS and feed["schema_version"]==VERSION and feed["state"]=="DERIVED_SELECTED_ONLY","FEED_CONTRACT")
    require((feed["season"],feed["week"])==(board["season"],board["week"]) and feed["producer_policy_sha256"]==policy["producer_policy_sha256"]
        and feed["rights_authority_sha256"] in policy["rights_authorities"] and feed["r0_identity_sha256"] in policy["r0_identities"],"FEED_POLICY_BINDING")
    require(all(h(feed[k]) for k in ["rights_receipt_sha256","durability_receipt_sha256","identity_scope_sha256"])
        and utc(feed["created_at"])<=utc(now)<utc(feed["expires_at"]) and 0<len(feed["rows"])<=5000,"FEED_CLOCK_OR_BOUND")
    coverage=feed["coverage"];reasons={"private_ineligible_R0","outside_board_R0","started_R0"}
    require(type(coverage) is dict and set(coverage)=={"private_selected_rows","public_rows","fallback_counts"}
        and type(coverage["private_selected_rows"]) is int and type(coverage["public_rows"]) is int and 0<coverage["private_selected_rows"]<=5000
        and coverage["public_rows"]==len(feed["rows"]) and type(coverage["fallback_counts"]) is dict and set(coverage["fallback_counts"])<=reasons
        and all(type(v) is int and v>=0 for v in coverage["fallback_counts"].values())
        and coverage["private_selected_rows"]==coverage["public_rows"]+sum(coverage["fallback_counts"].values()),"CLOSED_PUBLIC_COVERAGE")
    require(feed["identity_scope_sha256"]==identity_scope(feed["rows"],board),"CURRENT_BOARD_SCOPE_CHANGED")
    offers=api.board_offers(board);seen=set();selected=[]
    for row in feed["rows"]:
        require(set(row)==set(api.ROW_FIELDS) and api.key(row) not in seen,"CLOSED_UNIQUE_PUBLIC_ROWS");seen.add(api.key(row))
        member(policy,row);api.validate_row(dict(row,first_prepared_at=feed["created_at"]),offers)
        player,game,_=offers[api.key(row)]
        if game.get("state")!="pre" or utc(row["valid_until_utc"])<=utc(now):continue
        selected.append(dict(row,season=board["season"],week=board["week"],team=player["team"],opponent=player["opp"],evidence_lane="original_pregame",operational_eligible=True))
    return dict(rows=selected)


def code_review(root,policy,source_sha):
    root=Path(root);require(re.fullmatch(r"[a-f0-9]{40}",source_sha),"ACTUAL_HEAD_REQUIRED")
    head=subprocess.run(["git","--no-lazy-fetch","rev-parse","HEAD"],cwd=root,capture_output=True,text=True,timeout=2,check=True).stdout.strip()
    require(head==source_sha,"CURRENT_HEAD_MISMATCH")
    actual={}
    for name,expected in policy["website_code_sha256"].items():
        path=root/name;require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),"CODE_SCOPE")
        require(path.stat().st_size<=2<<20,"WEBSITE_CODE_BOUND");body=path.read_bytes();require(sha(body)==expected,"WEBSITE_CODE_NOT_REGISTERED");actual[name]=expected
    require(actual,"CODE_REGISTRATION_REQUIRED")
    return digest(actual)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):return None


def download(url,cap):
    try:response=build_opener(NoRedirect()).open(Request(url,headers={"Accept":"application/json","User-Agent":"weekly-derived-feed-v1"}),timeout=10)
    except HTTPError as response:raise FeedError("PUBLIC_FEED_UNAVAILABLE") from None
    with response:
        require(response.status==200,"PUBLIC_FEED_UNAVAILABLE");body=response.read(cap+1);require(len(body)<=cap,"PUBLIC_FEED_BOUND");return body


def fetch_feed(policy,board,*,fetch=download):
    """Two public GETs, append-only directory; never overwrite a latest pointer."""
    if policy.get("schema_version")==POLICY_V2:
        def checked(url,cap):
            body=fetch(url,cap);strict_public_json(body);return body
        return fetch_feed(dict(policy,schema_version=POLICY),board,fetch=checked)
    ref=policy.get("public_ref");require(type(ref) is str and bool(re.fullmatch(r"[A-Za-z0-9_./-]+",ref)),"REGISTERED_PUBLIC_FEED_REQUIRED")
    season,week=board["season"],board["week"]
    require(type(season) is int and type(week) is int and 1<=week<=22,"BOARD_WEEK_REQUIRED")
    path=f"state/public/weekly-adaptive-v1/{season}-W{week:02d}"
    url="https://api.github.com/repos/NickNicky19/NFL-forecasting/contents/"+path+"?ref="+ref
    listing=json.loads(fetch(url,1<<20));require(isinstance(listing,list) and 0<len(listing)<1000,"PUBLIC_DIRECTORY_BOUND")
    found=[]
    for item in listing:
        name=item.get("name","");match=re.fullmatch(r"(\d{8}T\d{6}\.\d{6}Z)--([a-f0-9]{64})\.json",name)
        require(match and item.get("type")=="file" and item.get("path")==path+"/"+name,"PUBLIC_DIRECTORY_SCOPE")
        found.append((name,match[1],match[2]))
    name,stamp,expected=max(found)
    body=fetch("https://raw.githubusercontent.com/NickNicky19/NFL-forecasting/"+ref+"/"+path+"/"+name,MAX_BYTES)
    require(sha(body)==expected,"PUBLIC_FEED_HASH");feed=json.loads(body)
    require(utc(feed["created_at"]).strftime("%Y%m%dT%H%M%S.%fZ")==stamp,"PUBLIC_FILENAME_CLOCK")
    return feed


def writer_input(root,policy,board,*,website_source_sha,now,feed=None,fetch=download):
    """Optional feed failure returns in-memory empty input; never reuses a stale descriptor."""
    if policy.get("schema_version")==POLICY_V2:
        return writer_input_v2(root,policy,board,website_source_sha=website_source_sha,now=now,feed=feed,fetch=fetch)
    try:
        policy_check(policy);inventory=code_review(root,policy,website_source_sha)
        if feed is None:
            old=signal.getsignal(signal.SIGALRM);timer=signal.getitimer(signal.ITIMER_REAL)
            require(timer==(0.,0.),"OPTIONAL_TIMER_ALREADY_IN_USE")
            def expired(*_):raise FeedError("OPTIONAL_FEED_DEADLINE")
            signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,20)
            try:feed=fetch_feed(policy,board,fetch=fetch)
            finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)
        selected=validate_feed(feed,policy,board,now=now)
        review=dict(schema_version=overlay().REVIEW,approved=True,selected_input_sha256=digest(selected),website_source_sha=website_source_sha,
            authority_kind="AUTOMATED_REGISTERED_POLICY",human_approval=False,authority_policy_sha256=digest(policy),code_inventory_sha256=inventory,
            feed_sha256=digest(feed),reviewed_at=now,board_membership_sha256=feed["identity_scope_sha256"])
        return selected,review,dict(state="AUTOMATED_POLICY_ACCEPTED",rows=len(selected["rows"]),website_source_sha=website_source_sha,policy_sha256=digest(policy),review_sha256=digest(review))
    except Exception as error:
        reason=str(error) if isinstance(error,FeedError) and re.fullmatch(r"[A-Z0-9_]+",str(error)) else "OPTIONAL_FEED_REJECTED"
        return {},{},dict(state="R0_FALLBACK",reason=reason,rows=0,human_approval=False)


def prepare_writer(root,policy_path,policy_sha256,board,*,website_source_sha,now,atomic_json,fetch=download):
    """Normal writer seam. Approval is an automated policy result, never a human claim."""
    try:
        path=Path(policy_path);path=path if path.is_absolute() else Path(root)/path
        require(not path.is_symlink() and not any(p.is_symlink() for p in path.parents) and path.resolve().is_relative_to(Path(root).resolve()) and path.stat().st_size<=1<<20,"POLICY_FILE_BOUND")
        body=path.read_bytes();require(sha(body)==policy_sha256,"REGISTERED_POLICY_FILE_HASH")
        selected,review,receipt=writer_input(root,json.loads(body),board,website_source_sha=website_source_sha,now=now,fetch=fetch)
    except Exception:
        selected,review,receipt={},{},dict(state="R0_FALLBACK",reason="POLICY_INPUT_UNAVAILABLE",rows=0,human_approval=False)
    if not isinstance(website_source_sha,str) or not re.fullmatch(r"[a-f0-9]{40}",website_source_sha):return {},{}
    try:utc(now)
    except Exception:return {},{}
    audit=dict(schema_version="weekly-public-feed-writer-audit-v1",website_source_sha=website_source_sha,at=now,policy_file_sha256=policy_sha256,
        authority_kind="AUTOMATED_REGISTERED_POLICY",human_approval=False,validation=receipt,review=review)
    try:
        target=Path(root)/"data/weekly-adaptive-audit"/(digest(audit)+".json")
        require(not target.is_symlink() and not any(p.is_symlink() for p in target.parents),"WRITER_AUDIT_PATH")
        if target.exists():require(target.read_bytes()==canonical(audit),"IMMUTABLE_WRITER_AUDIT")
        else:atomic_json(target,audit)
    except Exception:return {},{}
    return selected,review


def strict_public_json(body):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,"DUPLICATE_PUBLIC_JSON_FIELD");result[key]=value
        return result
    def bad(_):raise FeedError("NONFINITE_PUBLIC_JSON")
    return json.loads(body,object_pairs_hook=pairs,parse_constant=bad)


def policy_check_v2(policy):
    authority=policy.get("publication_authority",{})
    keys={"schema_version","state","repository","source_sha","source_branch","workflow_path","event","export_job","run_attempt","public_ref",
        "catalog_schema","catalog_freezer_sha256","catalog_registration_rule"}
    require(set(authority)==keys and authority["schema_version"]==AUTHORITY_V2 and authority["state"]=="ROOT_REGISTERED"
        and authority["repository"]==REPOSITORY and type(authority["source_sha"]) is str and re.fullmatch(r"[a-f0-9]{40}",authority["source_sha"])
        and type(authority["source_branch"]) is str and re.fullmatch(r"[A-Za-z0-9_./-]+",authority["source_branch"])
        and not any(p in {".","..",""} for p in authority["source_branch"].split("/"))
        and authority["workflow_path"]==".github/workflows/lab.yml" and authority["event"]=="workflow_dispatch"
        and type(authority["export_job"]) is str and re.fullmatch(r"[A-Za-z0-9_-]+",authority["export_job"])
        and type(authority["run_attempt"]) is int and authority["run_attempt"]==1 and authority["public_ref"]==policy.get("public_ref")=="lab-state"
        and authority["catalog_schema"]==CATALOG_V2 and h(authority["catalog_freezer_sha256"])
        and authority["catalog_registration_rule"]=="OWNED_SELECTED_VERSION_CATALOG_BEFORE_FEATURES_OR_VALUES","PUBLICATION_AUTHORITY_NOT_REGISTERED")
    require(policy.get("state")=="ROOT_REGISTERED" and policy.get("authority_kind")=="AUTOMATED_REGISTERED_POLICY"
        and policy.get("human_approval") is False and policy.get("public_raw_or_model_weights") is False,"REGISTERED_DERIVED_V2_POLICY_REQUIRED")
    probe=copy.deepcopy(policy);probe["schema_version"]=POLICY
    for target,entries in probe.get("procedures",{}).items():
        require(isinstance(entries,list) and entries,"FIXED_PUBLICATION_RECIPES_REQUIRED")
        for entry in entries:
            require(set(entry)=={"method_id","procedure_version","product","source_policy_sha256"},"FIXED_PUBLICATION_RECIPE_FIELDS")
            entry["model_version"]="0"*64
    policy_check(probe)  # Original rights/R0/code/role/support gates stay required.


def catalog_policy_v2(policy,catalog):
    policy_check_v2(policy)
    require(type(catalog) is dict and set(catalog)=={"schema_version","rows","current_values_used","public_policy_registration"}
        and catalog["schema_version"]==CATALOG_V2 and catalog["current_values_used"] is False
        and catalog["public_policy_registration"]=="REQUIRED_SEPARATELY; not automatic approval"
        and type(catalog["rows"]) is list and 0<len(catalog["rows"])<=256,"BEFORE_VALUES_VERSION_CATALOG_REQUIRED")
    effective=copy.deepcopy(policy);effective["schema_version"]=POLICY;effective["procedures"]={};seen=set()
    for row in catalog["rows"]:
        require(type(row) is dict and set(row)=={"category","method_id","procedure_version","model_version"}
            and h(row["procedure_version"]) and h(row["model_version"]) and digest(row) not in seen,"CLOSED_UNIQUE_ISSUED_VERSION_CATALOG")
        seen.add(digest(row));recipes=policy["procedures"].get(row["category"],[])
        matches=[r for r in recipes if r["method_id"]==row["method_id"] and r["procedure_version"]==row["procedure_version"]]
        require(len(matches)==1,"ISSUED_PROCEDURE_NOT_REGISTERED")
        effective["procedures"].setdefault(row["category"],[]).append(dict(matches[0],model_version=row["model_version"]))
    require(set(effective["procedures"])==set(policy["procedures"]),"COMPLETE_REGISTERED_VERSION_CATALOG_REQUIRED")
    policy_check(effective)
    return effective


def publication_metadata_v2(policy,accepted,bundle,catalog,catalog_body):
    exporter=accepted.get("exporter");authority=policy["publication_authority"]
    require(accepted.get("authority_kind")=="ROOT_APPROVED_PROCEDURE_VERIFIED" and type(exporter) is dict
        and exporter.get("execution_lane")=="github_actions" and exporter.get("repository")==REPOSITORY
        and exporter.get("source_sha")==authority["source_sha"] and exporter.get("job_id")==authority["export_job"]
        and exporter.get("run_attempt")==1 and exporter.get("permission")=="write" and type(exporter.get("api_job_id")) is int and exporter["api_job_id"]>0
        and type(exporter.get("run_id")) is str and re.fullmatch(r"[1-9][0-9]{0,19}",exporter["run_id"])
        and exporter.get("workflow_ref")==REPOSITORY+"/"+authority["workflow_path"]+"@refs/heads/"+authority["source_branch"],"ACTUAL_VERIFIED_PUBLICATION_JOB_REQUIRED")
    return dict(schema_version=PUBLICATION_V2,authority_sha256=digest(authority),repository=REPOSITORY,source_sha=exporter["source_sha"],
        run_id=exporter["run_id"],run_attempt=1,workflow_path=authority["workflow_path"],export_job=authority["export_job"],api_job_id=exporter["api_job_id"],
        selected_body_sha256=bundle["completion"]["binding"]["sha256"],source_version_catalog_sha256=sha(catalog_body),version_catalog_sha256=digest(catalog),version_catalog=catalog)


def export_rows_v2(rows,bundle,policy,board,*,now,durable_acceptance,version_catalog_body):
    policy_check_v2(policy)
    require(durable_acceptance is not None,"LIVE_DURABILITY_VERIFIER_REQUIRED_FOR_V2")
    # Actual live verifier remains mandatory before selected data can be used.
    _,accepted=private_gates(bundle,policy,now=now,durable_acceptance=durable_acceptance)
    ref=bundle["terminal"].get("selected_version_catalog")
    require(bundle["terminal"]["schema_version"]=="weekly-generic-future-producer-v1" and type(ref) is dict
        and type(version_catalog_body) is bytes and 0<len(version_catalog_body)<=256<<10
        and len(version_catalog_body)==ref.get("bytes") and sha(version_catalog_body)==ref.get("sha256"),"EXACT_OWNED_PRE_VALUE_VERSION_CATALOG_BODY_REQUIRED")
    catalog=strict_public_json(version_catalog_body)
    require(version_catalog_body==canonical(catalog)+b"\n","REGISTERED_CATALOG_SERIALIZATION_REQUIRED")
    effective=catalog_policy_v2(policy,catalog)
    document=export_rows(rows,bundle,effective,board,now=now,durable_acceptance=durable_acceptance)
    publication=publication_metadata_v2(policy,accepted,bundle,catalog,version_catalog_body)
    document.update(schema_version=VERSION_V2,publication=publication,publication_sha256=digest(publication))
    require(len(canonical(document))<=MAX_BYTES,"PUBLIC_FEED_BYTE_CAP")
    return document


@contextmanager
def publication_deadline(seconds):
    """Nested checks can only shorten the caller's existing optional timeout."""
    previous=signal.getsignal(signal.SIGALRM);timer=signal.getitimer(signal.ITIMER_REAL);started=time.monotonic()
    require(timer[1]==0.,"OPTIONAL_INTERVAL_TIMER_FORBIDDEN")
    def expired(*_):raise FeedError("PUBLICATION_METADATA_DEADLINE")
    signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,min(seconds,timer[0]) if timer[0]>0 else seconds)
    try:yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
        if timer[0]>0:
            left=timer[0]-(time.monotonic()-started)
            require(left>0,"PUBLICATION_METADATA_DEADLINE");signal.setitimer(signal.ITIMER_REAL,left)


def verify_publication_execution(feed,policy,*,now,fetch):
    publication=feed["publication"];authority=policy["publication_authority"]
    require(type(publication) is dict and set(publication)==PUBLICATION_FIELDS and publication["schema_version"]==PUBLICATION_V2
        and publication["authority_sha256"]==digest(authority) and publication["repository"]==REPOSITORY
        and publication["source_sha"]==authority["source_sha"] and publication["workflow_path"]==authority["workflow_path"]
        and publication["export_job"]==authority["export_job"] and type(publication["run_id"]) is str
        and re.fullmatch(r"[1-9][0-9]{0,19}",publication["run_id"]) and type(publication["run_attempt"]) is int and publication["run_attempt"]==1
        and type(publication["api_job_id"]) is int and publication["api_job_id"]>0
        and all(h(publication[k]) for k in ["selected_body_sha256","source_version_catalog_sha256","version_catalog_sha256"])
        and digest(publication["version_catalog"])==publication["version_catalog_sha256"]
        and sha(canonical(publication["version_catalog"])+b"\n")==publication["source_version_catalog_sha256"]
        and feed.get("publication_sha256")==digest(publication),"CLOSED_REGISTERED_PUBLICATION_REQUIRED")
    base="https://api.github.com/repos/"+REPOSITORY+"/actions/runs/"+publication["run_id"]
    with publication_deadline(20):
        run_body=fetch(base,1<<20);require(type(run_body) is bytes and len(run_body)<=1<<20,"PUBLICATION_METADATA_BOUND")
        run=strict_public_json(run_body)
        require(type(run) is dict and type(run.get("id")) is int and run["id"]==int(publication["run_id"])
            and run.get("repository",{}).get("full_name")==REPOSITORY and run.get("head_repository",{}).get("full_name")==REPOSITORY
            and run.get("head_sha")==authority["source_sha"] and run.get("head_branch")==authority["source_branch"]
            and run.get("path")==authority["workflow_path"] and run.get("event")==authority["event"]
            and type(run.get("run_attempt")) is int and run["run_attempt"]==1 and run.get("status")=="completed" and run.get("conclusion")=="success",
            "SUCCESSFUL_REGISTERED_PUBLICATION_RUN_REQUIRED")
        jobs_body=fetch(base+"/jobs?per_page=100&page=1",1<<20);require(type(jobs_body) is bytes and len(jobs_body)<=1<<20,"PUBLICATION_METADATA_BOUND")
        jobs=strict_public_json(jobs_body)
    require(type(jobs) is dict and type(jobs.get("jobs")) is list and type(jobs.get("total_count")) is int
        and jobs["total_count"]==len(jobs["jobs"])<=100,"COMPLETE_PUBLICATION_JOB_LIST_REQUIRED")
    matches=[j for j in jobs["jobs"] if j.get("name")==authority["export_job"]]
    require(len(matches)==1,"UNIQUE_REGISTERED_EXPORT_JOB_REQUIRED");job=matches[0]
    require(type(job.get("id")) is int and job["id"]==publication["api_job_id"] and job.get("run_id")==int(publication["run_id"])
        and job.get("head_sha")==authority["source_sha"] and job.get("status")=="completed" and job.get("conclusion")=="success"
        and utc(job["started_at"])<=utc(feed["created_at"])<=utc(job["completed_at"])<=utc(run["updated_at"])<=utc(now),"SUCCESSFUL_REGISTERED_EXPORT_JOB_REQUIRED")
    return dict(schema_version=PUBLICATION_V2+"-execution",repository=REPOSITORY,run_id=publication["run_id"],source_sha=authority["source_sha"],
        api_job_id=job["id"],export_job=authority["export_job"],run_response_sha256=sha(run_body),jobs_response_sha256=sha(jobs_body),API_GETs=2,
        verification="COMPLETED_RUN_AND_JOB; public bytes trusted through owner-controlled immutable lab-state publisher")


def validate_feed_v2(feed,policy,board,*,now,fetch):
    policy_check_v2(policy)
    require(set(feed)==META_FIELDS|{"publication","publication_sha256"} and feed["schema_version"]==VERSION_V2,"V2_FEED_CONTRACT")
    effective=catalog_policy_v2(policy,feed["publication"]["version_catalog"])
    proof=verify_publication_execution(feed,policy,now=now,fetch=fetch)
    original={k:v for k,v in feed.items() if k in META_FIELDS};original["schema_version"]=VERSION
    selected=validate_feed(original,effective,board,now=now)
    return selected,proof


def writer_input_v2(root,policy,board,*,website_source_sha,now,feed,fetch):
    try:
        with publication_deadline(4):
            policy_check_v2(policy);inventory=code_review(root,policy,website_source_sha)
            if feed is None:feed=fetch_feed(policy,board,fetch=fetch)
            selected,proof=validate_feed_v2(feed,policy,board,now=now,fetch=fetch)
        review=dict(schema_version=overlay().REVIEW,approved=True,selected_input_sha256=digest(selected),website_source_sha=website_source_sha,
            authority_kind="AUTOMATED_REGISTERED_POLICY",human_approval=False,authority_policy_sha256=digest(policy),code_inventory_sha256=inventory,
            feed_sha256=digest(feed),reviewed_at=now,board_membership_sha256=feed["identity_scope_sha256"],publication_execution=proof)
        return selected,review,dict(state="AUTOMATED_POLICY_ACCEPTED",rows=len(selected["rows"]),website_source_sha=website_source_sha,
            policy_sha256=digest(policy),review_sha256=digest(review),publication_execution=proof)
    except Exception as error:
        reason=str(error) if isinstance(error,FeedError) and re.fullmatch(r"[A-Z0-9_]+",str(error)) else "OPTIONAL_FEED_REJECTED"
        return {},{},dict(state="R0_FALLBACK",reason=reason,rows=0,human_approval=False)
