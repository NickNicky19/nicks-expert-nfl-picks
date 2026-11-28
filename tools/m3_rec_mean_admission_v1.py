"""Bounded, local M3 reception-mean inspection and delivered-shadow admission.

No fitting, scheduling, publishing, model activation or implicit source approval.
The CLI performs only fixed GitHub reads. Human source review and publication
are authenticated separately; a locally written catalog is not public admission.
Private outputs include player identifiers/means and must stay in approved
private storage. Public registry/catalog/verification contain commitments only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.request import Request, build_opener, HTTPRedirectHandler

try:
    from . import stat_point_mae_public_v2 as wire
    from .m3_numeric_inspector_v1 import load_model, calculate_predictions
except ImportError:
    import stat_point_mae_public_v2 as wire
    from m3_numeric_inspector_v1 import load_model, calculate_predictions

PRODUCT = "C-M3-v1.1::rec::M3-0::base::MEAN_POINT"
FAMILY = PRODUCT.rsplit("::", 1)[0]
CONDITION = "observed_statistical_appearance_v1"
CONDITION_SHA = "f8a4e007e7d1ffbbf636ba02f0194a995b14cffccc750d71fad98973da0d313b"
WEBSITE = "NickNicky19/nicks-expert-nfl-picks"
PRODUCER = "NickNicky19/NFL-forecasting-NGS-C"
BRANCH = "research/shared-game-sim-01-follow-through-v1"
OWNER = 208912933
FEATURES = ["rec_mean_last3","rec_known_last3","rec_mean_last8","rec_known_last8","rec_lag1_value","rec_lag1_age_days","rec_lag1_missing","rec_lag2_value","rec_lag2_age_days","rec_lag2_missing","rec_lag3_value","rec_lag3_age_days","rec_lag3_missing","rec_lag4_value","rec_lag4_age_days","rec_lag4_missing","role_QB","role_RB","role_WR","role_TE","player_attempts_mean_last3","player_attempts_rows_last3","player_attempts_last","player_carries_mean_last3","player_carries_rows_last3","player_carries_last","player_targets_mean_last3","player_targets_rows_last3","player_targets_last","team_attempts_mean3","team_carries_mean3","team_sacks_mean3"]
RECIPE = {"targeted_data_m3.py":{"path":"src/targeted_data_m3.py","SHA256":"29ddb7299dcabeb03b446a81d06f726dd4e6db8d3db14f9ec90765f520e8d4b4","bytes":18927},"data_v2.py":{"path":"src/data_v2.py","SHA256":"e217c62617ea394a514fbde274e0074274f04a24890522db2af70f3b35ec2b9a","bytes":4106},"contracts_v2.py":{"path":"src/contracts_v2.py","SHA256":"9321d35ba5c7d7af59684784cbf92322849e968097ab7c01a2990493d061a77a","bytes":3784},"targeted_accuracy_m3.py":{"path":"src/targeted_accuracy_m3.py","SHA256":"28746603f1433093ba49844dfe3156aab85a3085624aeaf909394801d03854a1","bytes":14208},"laws_v2.py":{"path":"src/laws_v2.py","SHA256":"70251578ac1f431c7da63cd14760386eef5c38ce1915a40a4520340189ffce7c","bytes":6656},"safe_models_v4.py":{"path":"src/safe_models_v4.py","SHA256":"c6ae2868ab6530803cd5a9c56dae2922aeaf1f0b4c5cae54341d25dda8dea0e0","bytes":5048},"current_query_delivery_c06.py":{"path":"src/current_query_delivery_c06.py","SHA256":"5ccc7346bc205de8b125e8ee2902841192662e84eae495d6220987ce5d76f8c6","bytes":41155}}
SOURCE_POLICY = "Record actual response/observation, publisher and available revision clocks, ETag, hashes, bytes and identity. Apply the existing Date/Age, roster (36 h) and native event (30 min) checks. Compare schedule, native ID, kickoff, GB and LA. Use the qualified identity/status/team/role facts as observed; timestamp and label any uncertainty about a transaction or participation. Withhold ambiguous player/team bindings. No future individual result is required."
HASH = re.compile(r"[0-9a-f]{64}\Z")
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)\Z")
MAX_JSON = 4 << 20
MAX_MODEL = 8 << 20
MAX_COMMENT = 128 << 10
SCOPES = ["identity_and_event_effective_membership", "source_rights_and_versions",
          "actual_source_observation_and_revision_clocks", "weekly_and_query_eligibility",
          "owner_admitted_training_and_target_exclusion_evidence", "registered_C_producer_and_model_query_provenance"]


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def fingerprint(value):
    return sha(canonical(value))


def parse(body):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "DUPLICATE_JSON_KEY")
            out[key] = value
        return out
    def invalid(value):
        raise ValueError("NONFINITE_JSON")
    require(len(body) <= MAX_JSON, "JSON_BYTE_CAP")
    return json.loads(body, object_pairs_hook=pairs, parse_constant=invalid)


def clock(value):
    require(type(value) is str and UTC.fullmatch(value), "UTC_CLOCK_REQUIRED")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def current(now=None):
    # Only in-process synthetic tests inject a clock. CLI has no --now switch.
    value = now() if now is not None else datetime.now(timezone.utc)
    require(value.tzinfo is not None and value.utcoffset().total_seconds() == 0, "UTC_NOW_REQUIRED")
    return value


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def identifier(value):
    return type(value) is str and bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value))


def safe_path(root, relative):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "PRIVATE_ROOT_REQUIRED")
    require(type(relative) is str, "UNSAFE_PATH")
    p = PurePosixPath(relative)
    require(p.as_posix() == relative and not p.is_absolute() and p.parts and
            all(part not in ("", ".", "..") for part in p.parts), "UNSAFE_PATH")
    path = root
    for part in p.parts:
        path = path / part
        require(not path.is_symlink(), "SYMLINK_REJECTED")
    require(path.resolve().is_relative_to(root.resolve()), "PATH_ESCAPES_ROOT")
    return path


def read(root, relative, cap=MAX_JSON):
    path = safe_path(root, relative)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= cap, "FILE_SIZE_OR_TYPE")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            body = stream.read(cap + 1)
        require(len(body) == info.st_size and len(body) <= cap, "FILE_CHANGED_OR_OVERSIZE")
        return body
    finally:
        os.close(fd)


def write_new(root, relative, value):
    path = safe_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    safe_path(root, relative)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def bound_body(root, desc, cap):
    require(type(desc) is dict and set(desc) == {"path", "bytes", "SHA256"} and
            type(desc["bytes"]) is int and 0 < desc["bytes"] <= cap and
            type(desc["SHA256"]) is str and HASH.fullmatch(desc["SHA256"]), "INVALID_BODY_BINDING")
    body = read(root, desc["path"], cap)
    require(len(body) == desc["bytes"] and sha(body) == desc["SHA256"], "BOUND_BODY_MISMATCH")
    return body


def inspect_bundle(root, manifest_path, *, now=None):
    at = current(now)
    raw = read(root, manifest_path)
    m = parse(raw)
    required = set("state run product event model query model_artifact procedure point_profile source_contract source_evidence feature_capture identity_bridge source_record_proposal catalog_entry_proposal issued_at prior_fit_reused".split())
    require(type(m) is dict and set(m) == required, "ACTUAL_C_MANIFEST_REQUIRED")
    require(m["state"] == "ACTUAL_MODEL_AND_QUERY_PENDING_OWNER_ADMISSION" and
            m["product"] == PRODUCT and m["issued_at"] is None and
            m["prior_fit_reused"] is False and identifier(m["run"]) and
            m["run"].startswith("C-M3-REC-MEAN-"), "UNISSUED_ACTUAL_CURRENT_FIT_REQUIRED")
    # Reuse is deliberately not accepted without a separately implemented exact
    # equality proof. This tool does not silently bless historical W9 models.
    event = m["event"]
    require(type(event) is dict and set(event) == set("season week game_id native_event_id away_team home_team kickoff_UTC".split()), "EVENT_CONTRACT")
    require(type(event["season"]) is int and type(event["week"]) is int and
            1 <= event["week"] <= 18 and all(identifier(event[k]) for k in
            ("game_id", "native_event_id", "away_team", "home_team")) and
            event["away_team"] != event["home_team"], "EVENT_IDENTITY")
    require(event["game_id"] == f"{event['season']}_{event['week']:02d}_{event['away_team']}_{event['home_team']}" and
            re.fullmatch(r"[1-9]\d{0,11}", event["native_event_id"]), "CANONICAL_EVENT_IDENTITY")
    require(at < clock(event["kickoff_UTC"]), "PREGAME_INSPECTION_REQUIRED")
    model_bytes = bound_body(root, m["model"], MAX_MODEL)
    query_bytes = bound_body(root, m["query"], MAX_JSON)
    q = parse(query_bytes)
    require(type(q) is dict and set(q) == {"event", "product", "feature_order", "rows"} and
            q["event"] == event and q["product"] == PRODUCT and q["feature_order"] == FEATURES,
            "EXACT_QUERY_CONTRACT")
    rows = q["rows"]
    require(type(rows) is list and 0 < len(rows) <= 128, "BOUNDED_NONEMPTY_QUERY")
    seen = set()
    bridge = []
    for row in rows:
        require(type(row) is dict and set(row) == set("player_id sleeper_id espn_player_id position team opponent_team features last_prior_game last_team_game".split()), "CLOSED_QUERY_ROW")
        require(row["position"] in ("WR", "TE") and all(identifier(row[k]) for k in
                ("player_id", "sleeper_id", "espn_player_id", "team", "opponent_team")), "QUERY_IDENTITY_ROLE")
        require(re.fullmatch(r"00-\d{7}", row["player_id"]) and
                re.fullmatch(r"[1-9]\d{0,10}", row["sleeper_id"]) and
                re.fullmatch(r"[1-9]\d{0,10}", row["espn_player_id"]), "CANONICAL_PLAYER_IDENTIFIERS")
        require({row["team"], row["opponent_team"]} == {event["away_team"], event["home_team"]}, "QUERY_WRONG_EVENT")
        require(row["player_id"] not in seen, "DUPLICATE_QUERY")
        seen.add(row["player_id"])
        require(type(row["features"]) is list and len(row["features"]) == 32 and
                all(x is None or number(x) for x in row["features"]), "ORDERED_32_FEATURES")
        require(row["features"][16:20] == ([0, 0, 1, 0] if row["position"] == "WR" else [0, 0, 0, 1]),
                "QUERY_ROLE_ONEHOT_MISMATCH")
        bridge.append({k: row[k] for k in ("player_id", "sleeper_id", "espn_player_id", "team", "opponent_team", "position")})
    require(bridge == m["identity_bridge"] and len({r["sleeper_id"] for r in rows}) == len(rows) and
            len({r["espn_player_id"] for r in rows}) == len(rows), "IDENTITY_BRIDGE_OR_DUPLICATE")
    p = m["procedure"]
    require(p == dict(recipe=RECIPE, family=FAMILY, order=FEATURES,
            update="H-MULTI/E0_OP32/weekly_first_kickoff/strict_7d", conditional_on=CONDITION), "FROZEN_PROCEDURE_CHANGED")
    require(m["point_profile"] == dict(family=FAMILY, product=PRODUCT, functional="unrounded Law.mean()",
            corrector="NO_EXTRA_CORRECTOR", conditioning_contract_sha256=CONDITION_SHA), "POINT_OR_CORRECTOR_CHANGED")
    art, source, entry = m["model_artifact"], m["source_record_proposal"], m["catalog_entry_proposal"]
    require(type(art) is dict and set(art) == {"model", "procedure_sha256", "training", "fit_started_UTC", "fit_completed_UTC"} and
            art["model"] == m["model"] and art["procedure_sha256"] == fingerprint(p), "MODEL_ARTIFACT_BINDING")
    training = art["training"]
    require(type(training) is dict and type(training.get("actual_rows")) is int and
            training["actual_rows"] > 0 and all(HASH.fullmatch(training.get(k, "")) for k in
            ("feature_order_sha256", "training_member_sha256", "role_sequence_sha256",
             "retained_recipe_X_y_sha256", "training_NaN_mask_sha256")), "TRAINING_COMMITMENTS_REQUIRED")
    require(training["feature_order_sha256"] == fingerprint(FEATURES), "TRAINING_FEATURE_ORDER")
    require(clock(training["latest_training_available_UTC"]) < clock(training["fit_cutoff_UTC"]) <=
            clock(art["fit_started_UTC"]) <= clock(art["fit_completed_UTC"]) <= at < clock(event["kickoff_UTC"]), "FIT_CHRONOLOGY")
    require(clock(training["roster_publication_UTC"]) <= clock(training["information_cutoff_UTC"]) <=
            clock(m["feature_capture"]["completed_UTC"]) <= clock(art["fit_started_UTC"]), "SOURCE_FEATURE_FIT_CHRONOLOGY")
    se = m["source_evidence"]
    require(se["event"] == event and se["cutoff_UTC"] == training["information_cutoff_UTC"] and
            set(se["observations"]) == {"schedule", "roster", "weekly"}, "SOURCE_EVIDENCE")
    urls = []
    for name in ("schedule", "roster", "weekly"):
        rec = se["observations"][name]
        require(set(rec) == {"url", "bytes", "sha256", "observed_UTC", "headers"} and
                type(rec["url"]) is str and rec["url"].startswith("https://") and
                type(rec["bytes"]) is int and 0 < rec["bytes"] <= 4194304 and HASH.fullmatch(rec["sha256"]) and
                clock(rec["observed_UTC"]) <= clock(se["cutoff_UTC"]), "SOURCE_OBSERVATION_BINDING")
        require(type(rec["headers"]) is dict, "SOURCE_HEADER_EVIDENCE")
        urls.append(rec["url"])
    expected_contract = dict(target="rec", history=p["update"], event_role=["WR", "TE"],
                             sources=urls, conditioning_contract_sha256=CONDITION_SHA)
    require(m["source_contract"] == expected_contract, "SOURCE_CONTRACT_CHANGED")
    fc = m["feature_capture"]
    require(set(fc) == {"completed_UTC", "order_SHA256", "query_SHA256", "identity_SHA256", "source_SHA256"} and
            fc["order_SHA256"] == fingerprint(FEATURES) and fc["query_SHA256"] == fingerprint(q) and
            fc["identity_SHA256"] == fingerprint(bridge) and fc["source_SHA256"] == fingerprint(se), "FEATURE_CAPTURE_CROSSHASH")
    common = dict(target="rec", model_version=fingerprint(art), procedure_version=fingerprint(p),
                  point_profile_sha256=fingerprint(m["point_profile"]), source_policy_sha256=fingerprint(SOURCE_POLICY),
                  source_contract_sha256=fingerprint(expected_contract), public_roles=["WR", "TE"])
    expected_entry = dict(common, scoring_target="rec", method_id=PRODUCT, base_learner_id="P2_LEAF",
                         artifact_sha256=fingerprint(art), model_bytes_sha256=sha(model_bytes),
                         base_procedure_version=fingerprint(p), forecast_product="point_mean",
                         prediction_functional="expected_mean", original_contract_version="C-M3-v1.1",
                         conditional_on=CONDITION, conditioning_contract_sha256=CONDITION_SHA)
    require(entry == expected_entry, "CATALOG_PROPOSAL_CROSSHASH")
    expected_source = dict(common, identity_bridge_sha256=fingerprint(bridge), source_receipt_sha256=fingerprint(se),
                           feature_capture_receipt_sha256=fingerprint(fc), feature_binding_sha256=fingerprint({"order": FEATURES, "rows": rows}),
                           query_projection_sha256=fingerprint(q), query_source_sha256=fingerprint({"event": event, "ids": bridge}),
                           information_cutoff_utc=training["information_cutoff_UTC"], feature_capture_completed_at=fc["completed_UTC"],
                           conditional_on=CONDITION, conditioning_contract_sha256=CONDITION_SHA, expires_at=source["expires_at"])
    require(source == expected_source and at < clock(source["expires_at"]) <= clock(event["kickoff_UTC"]), "SOURCE_PROPOSAL_OR_EXPIRY")
    require(clock(source["expires_at"]) <= clock(training["roster_publication_UTC"]) +
            timedelta(hours=36), "ROSTER_EXPIRY")
    model = load_model(safe_path(root, m["model"]["path"]), m["model"]["SHA256"])
    predictions = calculate_predictions(model, [{"role": r["position"], "features": r["features"]} for r in rows])
    require(len(predictions) == len(rows), "INCOMPLETE_NUMERIC_INSPECTION")
    report = dict(schema="website-m3-private-inspection-v1", inspected_at=stamp(at), run=m["run"], event=event, product=PRODUCT,
                  manifest_sha256=sha(raw), model_sha256=sha(model_bytes), query_sha256=sha(query_bytes),
                  source_evidence_sha256=fingerprint(se), feature_capture_sha256=fingerprint(fc),
                  identity_bridge_sha256=fingerprint(bridge), source_policy_sha256=common["source_policy_sha256"],
                  exact_body_lengths={"manifest":len(raw), "model":len(model_bytes), "query":len(query_bytes)},
                  predictions=[dict(player_id=r["player_id"], sleeper_id=r["sleeper_id"], **v) for r, v in zip(rows, predictions)],
                  scope="Independent safe numeric reopening and structural/crosshash checks; source rights, vintage, complete training membership and role/event truth require authenticated owner review.")
    return m, q, report


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def github_get(url, cap, raw=False):
    # URLs are constructed below from fixed repositories/routes, never a payload locator.
    require(url.startswith("https://api.github.com/repos/"), "FIXED_GITHUB_ROUTE")
    request = Request(url, headers={"Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
                                   "User-Agent": "nicks-expert-nfl-picks-m3-admission-v1"})
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        require(response.status == 200 and response.geturl() == url, "GITHUB_READ_FAILED")
        body = response.read(cap + 1)
    require(len(body) <= cap, "GITHUB_RESPONSE_CAP")
    return body


def github_json(fetch, url, cap=MAX_COMMENT):
    body = fetch(url, cap, False)
    return parse(body), sha(body)


def owner_comment(comment_id, marker, fetch, at):
    require(type(comment_id) is int and comment_id > 0, "EXACT_COMMENT_ID_REQUIRED")
    url = f"https://api.github.com/repos/{WEBSITE}/issues/comments/{comment_id}"
    comment, body_hash = github_json(fetch, url)
    require(comment.get("id") == comment_id and comment.get("user", {}).get("id") == OWNER and
            comment.get("issue_url") == f"https://api.github.com/repos/{WEBSITE}/issues/1" and
            comment.get("html_url") == f"https://github.com/{WEBSITE}/pull/1#issuecomment-{comment_id}" and
            comment.get("author_association") in ("OWNER", "MEMBER", "COLLABORATOR") and
            comment.get("created_at") == comment.get("updated_at") and clock(comment["created_at"]) <= at,
            "AUTHENTIC_UNEDITED_WEBSITE_OWNER_REQUIRED")
    body = comment.get("body", "")
    prefix = marker + "\n```json\n"
    require(type(body) is str and body.startswith(prefix) and body.endswith("\n```") and
            body.count("\n```") == 2, "EXACT_TYPED_OWNER_STATEMENT_REQUIRED")
    return parse(body[len(prefix):-4].encode()), comment, body_hash


def same_inspection(root, manifest, inspection_path, at, *, retain_expired=False):
    body = read(root, inspection_path)
    old = parse(body)
    require(clock(old["inspected_at"]) <= at, "FUTURE_INSPECTION")
    # Later readback may preserve genuine expired originals. Reopening the same
    # hash-bound body is distinct from issuing a forecast or reviving current use.
    check_at = clock(old["inspected_at"]) if retain_expired else at
    m, q, fresh = inspect_bundle(root, manifest, now=lambda: check_at)
    old_core = {k:v for k,v in old.items() if k != "inspected_at"}
    fresh_core = {k:v for k,v in fresh.items() if k != "inspected_at"}
    require(old_core == fresh_core, "INSPECTION_OR_INPUT_CHANGED")
    return m, q, old, sha(body)


def source_review_statement(m, report, report_hash):
    return dict(schema="website-m3-source-review-v1", run=m["run"], event_id=m["event"]["native_event_id"],
                    product=PRODUCT, inspection_sha256=report_hash,
                    **{k:report[k] for k in ("manifest_sha256", "model_sha256", "query_sha256", "source_evidence_sha256",
                                             "feature_capture_sha256", "identity_bridge_sha256", "source_policy_sha256")},
                    disposition="SOURCE_AND_RIGHTS_VERIFIED", source_rights="PERMITTED_EXISTING_ROUTE", verification_scope=SCOPES)


def register(root, manifest, inspection, out, owner_review_id, *, fetch=github_get, now=None):
    at = current(now)
    started_at = at
    m, q, report, report_hash = same_inspection(root, manifest, inspection, at)
    statement, comment, wire_hash = owner_comment(owner_review_id, "M3_SOURCE_REVIEW_V1", fetch, at)
    require(statement == source_review_statement(m, report, report_hash) and
            clock(report["inspected_at"]) <= clock(comment["created_at"]), "OWNER_REVIEW_BINDINGS_OR_SCOPE")
    at = current(now)
    require(started_at <= at < clock(m["source_record_proposal"]["expires_at"]) < clock(m["event"]["kickoff_UTC"]),
            "REGISTRATION_COMPLETION_EXPIRED_OR_CLOCK_REVERSED")
    verified = dict(schema="website-m3-preissue-verification-v1", run=m["run"], product=PRODUCT,
                    event_id=m["event"]["native_event_id"], verified_at=stamp(at),
                    inspection_sha256=report_hash, owner_review_comment_id=owner_review_id,
                    owner_review_wire_sha256=wire_hash, owner_review_created_at=comment["created_at"],
                    commitments={k:report[k] for k in ("manifest_sha256", "model_sha256", "query_sha256", "source_evidence_sha256",
                                                      "feature_capture_sha256", "identity_bridge_sha256", "source_policy_sha256")},
                    source_verification="Authenticated owner scope in the bound PR1 source review; structural checks alone do not establish source truth.",
                    publication="LOCAL_ONLY_PENDING_AUTHENTICATED_PREISSUE_PUBLICATION")
    proof_hash = fingerprint(verified)
    registry = dict(schema_version=wire.EXPIRING_REGISTRY, registered_at=stamp(at), owner_admission_receipt_sha256=proof_hash,
                    records=[m["source_record_proposal"]])
    catalog = dict(schema_version=wire.EXPIRING_CATALOG, selection_product=wire.PRODUCT, selection_metric=wire.METRIC,
                   registered_at=stamp(at), owner_admission_receipt_sha256=proof_hash, entries=[m["catalog_entry_proposal"]])
    wire.validate_registry(registry)
    wire.validate_catalog(catalog)
    for name, document in (("VERIFICATION_REPORT.json", verified), ("SOURCE_REGISTRY.json", registry), ("MODEL_CATALOG.json", catalog)):
        write_new(root, f"{out}/{name}", document)
    return {"state":"LOCAL_VERIFIED_REGISTRATION_AWAITING_PUBLICATION", "run":m["run"],
            "registry_sha256":fingerprint(registry), "catalog_sha256":fingerprint(catalog),
            "verification_sha256":proof_hash, "primary_activation":False}


def decompress_originals(body):
    dec = lzma.LZMADecompressor(memlimit=64 << 20)
    raw = dec.decompress(body, max_length=MAX_JSON + 1)
    require(len(raw) <= MAX_JSON and dec.eof and not dec.unused_data, "ORIGINALS_DECOMPRESSION_CAP")
    return parse(raw)


def capture(root, manifest, inspection, registration, envelope_path, publication_comment_id,
            out, *, native_body=None, fetch=github_get, now=None, return_context=False):
    at = current(now)
    m, q, report, report_hash = same_inspection(root, manifest, inspection, at, retain_expired=True)
    verification = parse(read(root, f"{registration}/VERIFICATION_REPORT.json"))
    registry = parse(read(root, f"{registration}/SOURCE_REGISTRY.json"))
    catalog = parse(read(root, f"{registration}/MODEL_CATALOG.json"))
    wire.validate_registry(registry)
    wire.validate_catalog(catalog)
    commitments = {k:report[k] for k in ("manifest_sha256", "model_sha256", "query_sha256", "source_evidence_sha256",
                                       "feature_capture_sha256", "identity_bridge_sha256", "source_policy_sha256")}
    require(verification["schema"] == "website-m3-preissue-verification-v1" and
            verification["run"] == m["run"] and verification["event_id"] == m["event"]["native_event_id"] and
            verification["product"] == PRODUCT and verification["inspection_sha256"] == report_hash and
            verification["commitments"] == commitments and
            registry["records"] == [m["source_record_proposal"]] and catalog["entries"] == [m["catalog_entry_proposal"]] and
            registry["owner_admission_receipt_sha256"] == catalog["owner_admission_receipt_sha256"] == fingerprint(verification),
            "REGISTRATION_BINDING")
    # Re-fetch the genuine source review: a local verification file is not authority.
    reviewed, comment, review_hash = owner_comment(verification["owner_review_comment_id"], "M3_SOURCE_REVIEW_V1", fetch, at)
    require(review_hash == verification["owner_review_wire_sha256"] and
            reviewed == source_review_statement(m, report, report_hash) and
            clock(report["inspected_at"]) <= clock(comment["created_at"]) <= clock(verification["verified_at"]) and
            comment["created_at"] == verification["owner_review_created_at"], "SOURCE_REVIEW_CHANGED")
    publication, published, publication_wire_hash = owner_comment(publication_comment_id, "M3_PREISSUE_REGISTRATION_V1", fetch, at)
    require(publication == dict(schema="website-m3-preissue-publication-v1", run=m["run"], product=PRODUCT,
            event_id=m["event"]["native_event_id"], source_registry=registry, model_catalog=catalog,
            verification_report=verification), "PUBLIC_REGISTRATION_BINDINGS")
    envelope_bytes = read(root, envelope_path)
    env = parse(envelope_bytes)
    require(env.get("schema") == "C-M3-0-MANUAL-RECEPTION-MEAN-ENVELOPE-v1" and
            env["run"] == m["run"] and env["event"] == m["event"] and env["product"] == PRODUCT and
            env["model"] == m["model"] and env["query"] == m["query"] and
            env["source"] == m["source_record_proposal"] and env["catalog_entry"] == m["catalog_entry_proposal"], "DELIVERED_PRODUCT_BINDING")
    require(env["expires_at"] == registry["records"][0]["expires_at"], "DELIVERED_EXPIRY_CHANGED")
    issue = clock(env["issued_at"])
    deadline = clock(env["issue_deadline_utc"])
    require(clock(verification["verified_at"]) == clock(registry["registered_at"]) == clock(catalog["registered_at"]) <=
            clock(published["created_at"]) <= issue < deadline <= clock(env["expires_at"]) < clock(m["event"]["kickoff_UTC"]),
            "REGISTRATION_BEFORE_ISSUE_AND_EXPIRY_REQUIRED")
    proof = env["server"]
    require(SHA1.fullmatch(proof["capture_commit"]) and type(proof["workflow_run_id"]) is int and proof["workflow_run_id"] > 0,
            "REAL_C_SERVER_PROOF_REQUIRED")
    workflow, workflow_wire_hash = github_json(fetch, f"https://api.github.com/repos/{PRODUCER}/actions/runs/{proof['workflow_run_id']}")
    correct_pr = any(x.get("number") == 65 and x.get("head", {}).get("sha") == proof["capture_commit"]
                     for x in workflow.get("pull_requests", []))
    require(workflow.get("repository", {}).get("full_name") == PRODUCER and workflow.get("head_branch") == BRANCH and
            workflow.get("path", "").split("@")[0] == ".github/workflows/c-checks-pages.yml" and
            workflow.get("event") == "pull_request" and workflow.get("status") == "completed" and
            workflow.get("conclusion") == "success" and
            (correct_pr or workflow.get("head_sha") == proof["capture_commit"] and not workflow.get("pull_requests")),
            "AUTHENTIC_C_WORKFLOW_REQUIRED")
    require(workflow["id"] == proof["workflow_run_id"] and workflow["html_url"] == proof["workflow_run_url"] and
            workflow["created_at"] == proof["created_UTC"] and workflow["run_started_at"] == proof["started_UTC"] and
            workflow["updated_at"] == proof["completed_UTC"], "SERVER_PROOF_FIELDS")
    created, started, persisted = (clock(workflow[k]) for k in ("created_at", "run_started_at", "updated_at"))
    require(created <= started <= persisted and issue <= persisted < deadline and
            persisted <= clock(proof["actual_original_readback_UTC"]) <= clock(env["prepared_UTC"]) <= at, "GENUINE_PERSISTENCE_CLOCKS")
    desc = env["originals"]
    expected_path = f"prospective/runs/{m['run']}/FORECASTS.json.xz"
    require(desc["path"] == expected_path and desc["SHA256"] == proof["original_SHA256"] and
            desc["bytes"] == proof["original_bytes"], "ORIGINAL_IDENTITY")
    local = bound_body(root, desc, MAX_JSON)
    original_url = f"https://api.github.com/repos/{PRODUCER}/contents/{expected_path}?ref={proof['capture_commit']}"
    remote = fetch(original_url, MAX_JSON, True)
    require(remote == local, "IMMUTABLE_ORIGINAL_READBACK_MISMATCH")
    run_path = f"prospective/runs/{m['run']}/RUN.json"
    run_body = read(root, run_path)
    run_url = f"https://api.github.com/repos/{PRODUCER}/contents/{run_path}?ref={proof['capture_commit']}"
    require(fetch(run_url, MAX_JSON, True) == run_body, "IMMUTABLE_RUN_READBACK_MISMATCH")
    run = parse(run_body)
    manifest_desc = dict(path=manifest, bytes=report["exact_body_lengths"]["manifest"], SHA256=report["manifest_sha256"])
    require(run["run"] == m["run"] and run["event"] == m["event"] and run["product"] == PRODUCT and
            run["state"] == "ISSUED_AWAITING_GITHUB_PROOF" and run["issued_UTC"] == env["issued_at"] and
            run["originals"] == desc and run["inputs"] == manifest_desc and
            run["actual_expiry_UTC"] == env["expires_at"] and
            run["registry"]["registry_sha256"] == fingerprint(registry) and
            run["registry"]["catalog_sha256"] == fingerprint(catalog) and
            env["actual_website_admission"] == run["registry"], "IMMUTABLE_RUN_BINDINGS")
    source = run["native_source"]
    require(source["id"] == m["run"] and HASH.fullmatch(source["SHA256"]), "NATIVE_SOURCE_BINDING")
    require(run["native_status"]["game_id"] == m["event"]["game_id"] and
            run["native_status"]["observed_UTC"] == source["observed_UTC"] and
            run["native_status"]["source_id"] == m["run"], "NATIVE_PROJECTED_BINDINGS")
    validate_native(projection_payload(run["native_status"]), source, m["event"], issue,
                    clock(published["created_at"]), clock(env["expires_at"]), m)
    raw_native = read(root, native_body) if native_body else None
    if raw_native is not None:
        require(sha(raw_native) == source["SHA256"], "NATIVE_BODY_BINDING")
        native_payload = parse(raw_native)
    else:
        # Preserve owner-local raw-source verification limits. The authenticated
        # run projection is useful shadow evidence, not raw-response reproduction.
        native_payload = projection_payload(run["native_status"])
    validate_native(native_payload, source, m["event"], issue,
                    clock(published["created_at"]), clock(env["expires_at"]), m)
    receipt_body = bound_body(root, env["server_receipt"], MAX_JSON)
    require(parse(receipt_body) == proof, "SERVER_RECEIPT_BODY_MISMATCH")
    originals = decompress_originals(local)
    require(type(originals) is list and len(originals) == len(q["rows"]) == len(env["rows"]), "COMPLETE_ORIGINAL_POPULATION")
    native_count = sum(x["prior_mixture"] < 1 for x in report["predictions"])
    prior_count = len(originals)-native_count
    require(type(env["native"]) is int and type(env["prior_only"]) is int and
            env["native"] == run["native"] == native_count and env["prior_only"] == run["prior_only"] == prior_count and
            env["coverage"] == run["coverage"], "DECLARED_ATTRIBUTION_COVERAGE")
    original_keys = set("forecast_id product game_id player_id position team opponent_team sleeper_id expected_mean selected_projection prior_mixture attribution inference_UTC issued_UTC expires_UTC".split())
    typed_keys = original_keys | set("query_fingerprint conditional_on conditioning_contract_sha256 forecast_product prediction_functional expected_mean_kind label mean_eligible functional_proof fallback".split())
    for original, typed, query, prediction in zip(originals, env["rows"], q["rows"], report["predictions"]):
        require(type(original) is dict and set(original) == original_keys and
                type(typed) is dict and set(typed) == typed_keys, "CLOSED_ORIGINAL_AND_TYPED_ROW")
        for key in ("player_id", "sleeper_id", "position", "team", "opponent_team"):
            require(original[key] == typed[key] == query[key], "DELIVERED_IDENTITY")
        require(original["product"] == typed["product"] == PRODUCT and original["game_id"] == typed["game_id"] == m["event"]["game_id"], "ORIGINAL_EVENT_PRODUCT")
        require(original["forecast_id"] == typed["forecast_id"] == fingerprint([m["run"], m["event"]["game_id"], query["player_id"], PRODUCT])[:24], "ORIGINAL_FORECAST_ID")
        require(all(number(original[k]) and original[k] >= 0 for k in ("expected_mean", "selected_projection")) and
                original["expected_mean"] == original["selected_projection"] == typed["expected_mean"] == typed["selected_projection"] and
                math.isclose(original["expected_mean"], prediction["mean"], rel_tol=1e-12, abs_tol=1e-12), "DELIVERED_MEAN_CHANGED")
        require(number(original["prior_mixture"]) and original["prior_mixture"] == typed["prior_mixture"] == prediction["prior_mixture"] and
                original["attribution"] == typed["attribution"] ==
                ("PRIOR_ONLY" if prediction["prior_mixture"] == 1 else "LEARNED_LEAF_WITH_EXPLICIT_PRIOR_TAIL"), "ATTRIBUTION_CHANGED")
        require(original["issued_UTC"] == typed["issued_UTC"] == env["issued_at"] and
                original["expires_UTC"] == typed["expires_UTC"] == env["expires_at"] and
                clock(art_fit(m)) <= clock(original["inference_UTC"]) <= issue, "ORIGINAL_CLOCK_BINDING")
        require(typed["conditional_on"] == CONDITION and typed["conditioning_contract_sha256"] == CONDITION_SHA and
                typed["forecast_product"] == "point_mean" and typed["prediction_functional"] == "expected_mean" and
                typed["expected_mean_kind"] == "full_law_expected_mean" and typed["mean_eligible"] is True and
                typed["functional_proof"] is None and typed["label"] == "Appearance-conditioned mean" and
                typed["fallback"] is (prediction["prior_mixture"] == 1), "TYPED_PRODUCT_CHANGED")
        require(typed["query_fingerprint"] == query_fingerprint(original, query, m, registry, proof), "EXACT_QUERY_ROW_FINGERPRINT")
        require(not any(k in original or k in typed for k in ("outcome", "grade", "probability", "confidence", "actual_rec")), "UNDECLARED_OUTCOME_OR_PROBABILITY")
    completed_at = current(now)
    require(at <= completed_at, "CAPTURE_COMPLETION_CLOCK_REVERSED")
    at = completed_at
    receipt = dict(schema="website-m3-delivered-shadow-v1", state="DELIVERED_SHADOW" if raw_native is not None else "DELIVERED_SHADOW_SOURCE_LIMITED", run=m["run"], product=PRODUCT,
                   event=m["event"], captured_at=stamp(at), issued_at=env["issued_at"], expires_at=env["expires_at"],
                   inspection_sha256=report_hash, envelope_sha256=sha(envelope_bytes), originals_sha256=sha(local),
                   registration_comment_id=publication_comment_id, registration_wire_sha256=publication_wire_hash,
                   C_workflow_wire_sha256=workflow_wire_hash, C_capture_commit=proof["capture_commit"],
                   rows=originals, forecast_count=len(originals), outcomes="NOT_SUPPLIED_UNGRADED",
                   retention_disposition="EXPIRED_ORIGINAL_RETAINED" if at >= clock(env["expires_at"]) else "VALID_ORIGINAL_RETAINED",
                   current_use_allowed=at < clock(env["expires_at"]) and raw_native is not None, new_forecasts_generated=0,
                   native_raw_body_reproduced=raw_native is not None,
                   primary_activation=False, primary_blocker="Product-specific scientific and consumer admission remain separate; this receipt never updates a live pointer." +
                   (" Late native evidence is limited to C's authenticated projection and clocks; raw response remains owner-local." if raw_native is None else ""),
                   verification_scope="Safe numeric reconstruction, bound actual model/query, authenticated owner source review and preissue publication, genuine C persistence and immutable originals; no private training-fit reproduction or newly authenticated historical vintages.")
    write_new(root, out, receipt)
    summary = {k:receipt[k] for k in ("state", "run", "product", "forecast_count", "outcomes", "retention_disposition", "current_use_allowed", "new_forecasts_generated", "primary_activation", "primary_blocker")}
    if return_context:
        return summary, dict(manifest=m, query=q, inspection=report, envelope=env, originals=originals,
            proof=proof, run=run, registry=registry, catalog=catalog, verification=verification,
            publication=published, owner_review=comment, workflow=workflow,
            original_readback_at=stamp(at), native_body_sha256=sha(raw_native) if raw_native is not None else None, shadow_receipt=receipt)
    return summary


def query_fingerprint(original, query, manifest, registry, proof):
    row = {k:original[k] for k in ("player_id", "game_id", "position", "team", "opponent_team", "inference_UTC", "issued_UTC", "expires_UTC")}
    row.update(procedure_id=FAMILY, category="rec", native_event_id=manifest["event"]["native_event_id"],
        feature_order=FEATURES, features=query["features"], source_contract_SHA256=manifest["source_record_proposal"]["source_contract_sha256"],
        query_admission_SHA256=fingerprint(registry), source_observed_UTC=manifest["source_record_proposal"]["information_cutoff_utc"],
        information_cutoff_UTC=manifest["source_record_proposal"]["information_cutoff_utc"], persisted_UTC=proof["completed_UTC"],
        kickoff_UTC=manifest["event"]["kickoff_UTC"])
    # C's row-fingerprint domain uses the default ASCII JSON escaping.
    return sha(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def validate_native(payload, source, event, issue, registered, expiry, manifest):
    """Check the retained actual status body; never fetch current/postgame NFL data."""
    observed = clock(source["observed_UTC"])
    require(registered <= observed <= issue and (issue-observed).total_seconds() <= 1800, "NATIVE_OBSERVATION_CHRONOLOGY")
    limits = [clock(event["kickoff_UTC"])-timedelta(minutes=5), observed+timedelta(minutes=30),
              clock(manifest["model_artifact"]["training"]["roster_publication_UTC"])+timedelta(hours=36)]
    require(expiry == min(limits), "EXACT_PRODUCER_EXPIRY_REQUIRED")
    has_clock = False
    age = source.get("HTTP_Age")
    if age not in (None, ""):
        require(type(age) in (str, int, float), "NATIVE_HTTP_AGE")
        age = float(age)
        require(math.isfinite(age) and 0 <= age <= 1800 and age+(issue-observed).total_seconds() <= 1800, "NATIVE_HTTP_AGE")
        limits.append(observed+timedelta(seconds=1800-age)); has_clock = True
    date = source.get("HTTP_Date")
    if date not in (None, ""):
        date = parsedate_to_datetime(date)
        require(date.tzinfo is not None and -5 <= (observed-date).total_seconds() <= 1800 and
                -5 <= (issue-date).total_seconds() <= 1800, "NATIVE_HTTP_DATE")
        limits.append(date+timedelta(minutes=30)); has_clock = True
    require(has_clock and expiry <= min(limits), "NATIVE_EXPIRY_NOT_SUPPORTED")
    matches = [r for r in payload.get("events", []) if str(r.get("id")) == event["native_event_id"]]
    require(len(matches) == 1, "NATIVE_EVENT_MISSING_OR_DUPLICATED")
    row = matches[0]; competitions = row.get("competitions", [])
    require(len(competitions) == 1 and str(competitions[0]["id"]) == event["native_event_id"], "NATIVE_COMPETITION_ID")
    comp = competitions[0]; teams = {x["homeAway"]:x["team"]["abbreviation"] for x in comp["competitors"]}
    norm = lambda x: {"LAR":"LA", "WSH":"WAS", "JAC":"JAX"}.get(x, x)
    require(set(teams) == {"home", "away"} and norm(teams["home"]) == norm(event["home_team"]) and
            norm(teams["away"]) == norm(event["away_team"]) and clock(row["date"]) == clock(event["kickoff_UTC"]) and
            row["season"]["year"] == event["season"] and row["season"]["type"] == 2 and
            row.get("week", payload.get("week", {})).get("number") == event["week"], "NATIVE_EVENT_IDENTITY")
    state = row["status"]["type"]
    require(state["state"] == "pre" and state["name"] == "STATUS_SCHEDULED" and state["completed"] is False and
            issue < clock(event["kickoff_UTC"])-timedelta(minutes=5), "NATIVE_EVENT_NOT_PREGAME")
    other = comp.get("status", {}).get("type")
    require(not other or all(other[k] == state[k] for k in ("state", "name", "completed")), "NATIVE_STATUS_CONFLICT")


def projection_payload(row):
    require(row["espn_event_id"] == row["competition_id"] and row["competition_state_agreement"] in (True, "NOT_SEPARATELY_PROVIDED"), "NATIVE_PROJECTED_IDENTITY")
    state = {k:row[k] for k in ("state", "completed")}; state["name"] = row["status_name"]
    return {"events":[dict(id=row["espn_event_id"], date=row["kickoff_UTC"], week={"number":row["week"]},
        season={"year":row["season"], "type":row["season_type"]}, status={"type":state},
        competitions=[dict(id=row["competition_id"], status={"type":state}, competitors=[
            {"homeAway":"home", "team":{"abbreviation":row["home_team"]}},
            {"homeAway":"away", "team":{"abbreviation":row["away_team"]}}])])]}


def art_fit(manifest):
    return manifest["model_artifact"]["fit_completed_UTC"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Approved private input/output root; no automatic publication")
    parser.add_argument("--manifest", required=True, help="Relative actual C INPUT_MANIFEST.json")
    sub = parser.add_subparsers(dest="phase", required=True)
    p = sub.add_parser("inspect"); p.add_argument("--out", required=True)
    p = sub.add_parser("register"); p.add_argument("--inspection", required=True); p.add_argument("--out", required=True)
    p.add_argument("--owner-review-id", required=True, type=int)
    p = sub.add_parser("capture"); p.add_argument("--inspection", required=True); p.add_argument("--registration", required=True)
    p.add_argument("--envelope", required=True); p.add_argument("--publication-comment-id", required=True, type=int)
    p.add_argument("--native-body", help="Retained actual late native response through the approved private route; otherwise preserve SOURCE_LIMITED shadow")
    p.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.phase == "inspect":
        _, _, report = inspect_bundle(args.root, args.manifest)
        write_new(args.root, args.out, report)
        result = dict(state="PRIVATE_NUMERIC_INSPECTION_COMPLETE", forecast_count=len(report["predictions"]), primary_activation=False)
    elif args.phase == "register":
        result = register(args.root, args.manifest, args.inspection, args.out, args.owner_review_id)
    else:
        result = capture(args.root, args.manifest, args.inspection, args.registration, args.envelope,
                         args.publication_comment_id, args.out, native_body=args.native_body)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
