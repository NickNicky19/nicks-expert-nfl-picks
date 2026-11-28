"""Adapt a genuinely verified C capture into the existing numerical wire.

This writes immutable SHADOW assets only. It never changes a live pointer,
source policy, probability, recommendation or ranking. The caller must supply
actual permitted bodies; receipt assertions alone cannot mint capabilities.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json

try:
    from . import m3_rec_mean_admission_v1 as admission
    from . import stat_point_mae_public_v2 as wire
except ImportError:
    import m3_rec_mean_admission_v1 as admission
    import stat_point_mae_public_v2 as wire


def numerical_shadow(root, manifest, inspection, registration, envelope, publication_comment_id,
                     out, *, native_body=None, fetch=admission.github_get, now=None):
    """Reopen and authenticate the real capture before creating any typed rows.

    ``fetch`` and ``now`` are injectable for in-process fictional tests, never
    exposed as CLI options. The existing wire's verifiers check actual observed
    bytes and canonical records, rather than accepting client PASS flags.
    """
    summary, context = admission.capture(root, manifest, inspection, registration, envelope,
        publication_comment_id, out + "/SHADOW_CAPTURE.json", native_body=native_body,
        fetch=fetch, now=now, return_context=True)
    m, q, env = context["manifest"], context["query"], context["envelope"]
    registry, catalog = context["registry"], context["catalog"]
    originals = context["originals"]
    event, source = m["event"], m["source_record_proposal"]
    report = context["shadow_receipt"]
    proof = context["proof"]
    readback_at = context["original_readback_at"]
    frozen = {
        manifest: context["inspection"]["manifest_sha256"],
        m["model"]["path"]: m["model"]["SHA256"],
        m["query"]["path"]: m["query"]["SHA256"],
        env["originals"]["path"]: env["originals"]["SHA256"],
        envelope: report["envelope_sha256"],
    }

    def recheck():
        for path, expected in frozen.items():
            admission.require(admission.sha(admission.read(root, path, admission.MAX_MODEL)) == expected,
                              "WIRE_INPUT_CHANGED_AFTER_CAPTURE")

    def registry_check(kind, body):
        recheck()
        admission.require(kind == "SOURCE_REGISTRY" and body == wire.canonical(registry)
            and registry["records"] == [m["source_record_proposal"]], "WIRE_REGISTRY_EVIDENCE")

    def catalog_check(kind, body):
        recheck()
        admission.require(kind == "CATALOG" and body == wire.canonical(catalog)
            and catalog["entries"] == [m["catalog_entry_proposal"]], "WIRE_CATALOG_EVIDENCE")

    source_cap = wire.admit_registry(registry, verify_owner_registry=registry_check)
    catalog_cap = wire.admit_catalog(catalog, source_cap, verify_owner_catalog=catalog_check)
    captures = []
    for original, query in zip(originals, q["rows"]):
        ident = dict(season=event["season"], week=event["week"], game_id=event["game_id"],
                     player_id=original["player_id"], target="rec")
        binding = dict(ident, website_game_id=event["native_event_id"], sleeper_id=query["sleeper_id"],
                       espn_player_id=query["espn_player_id"], team=query["team"], opponent=query["opponent_team"])
        selection_sha = wire.digest(dict(run=m["run"], forecast_id=original["forecast_id"],
            product=admission.PRODUCT, originals_sha256=env["originals"]["SHA256"]))
        value = dict(m["catalog_entry_proposal"], **{k:v for k,v in source.items()
                     if k not in m["catalog_entry_proposal"]})
        value.update(ident, schema_version=wire.EXPIRING_POINT,
            candidate_schema=wire.CANDIDATE_SCHEMA, selection_product=wire.PRODUCT,
            selection_metric=wire.METRIC, consumer_contract_version=wire.EXPIRING_POINT,
            horizon="player_game", position=original["position"], team=original["team"],
            opponent=original["opponent_team"], public_export_authorized=False,
            public_scope_eligible=True, operational_eligible=True, evidence_lane="original_pregame",
            participation_state="unknown", forecast_value=original["expected_mean"],
            separate_expected_mean=original["expected_mean"], mean_eligible=True,
            trained_prior_only=original["prior_mixture"] == 1, fallback=original["prior_mixture"] == 1,
            fallback_reason="role_prior_only" if original["prior_mixture"] == 1 else "",
            functional_proof=None, source_contract=m["source_contract"],
            source_receipt={"sha256": source["source_receipt_sha256"]},
            feature_capture_receipt={"sha256": source["feature_capture_receipt_sha256"]},
            feature_binding={"sha256": source["feature_binding_sha256"]},
            original_forecast={"source_capture_completed_at": source["feature_capture_completed_at"]},
            feature_max_source_available_utc=max((r["observed_UTC"] for r in
                m["source_evidence"]["observations"].values()), key=wire.clock),
            issued_at=original["issued_UTC"], issue_deadline_utc=env["issue_deadline_utc"],
            kickoff_utc=event["kickoff_UTC"], selection_sha256=selection_sha)
        value["candidate_sha256"] = wire.candidate_digest(value)
        receipt = dict(schema_version=wire.EXPIRING_CAPTURE, state="FROZEN_AND_READ_BACK",
            website_game_id=event["native_event_id"], sleeper_id=query["sleeper_id"],
            identity_bridge_sha256=source["identity_bridge_sha256"], identity_binding_sha256=wire.digest(binding),
            team=original["team"], opponent=original["opponent_team"], horizon="player_game",
            candidate_sha256=value["candidate_sha256"], capture_receipt_sha256=env["server_receipt"]["SHA256"],
            capture_body_sha256=env["originals"]["SHA256"], selection_sha256=selection_sha,
            identity=ident, source_registry_sha256=source_cap.sha256,
            persistence_completed_at=proof["completed_UTC"], readback_completed_at=readback_at,
            issued_at=original["issued_UTC"], issue_deadline_utc=env["issue_deadline_utc"],
            kickoff_utc=event["kickoff_UTC"], conditional_on=admission.CONDITION,
            conditioning_contract_sha256=admission.CONDITION_SHA, expires_at=env["expires_at"],
            **{k:value[k] for k in ("model_version", "procedure_version", "point_profile_sha256",
                                    "source_policy_sha256", "query_projection_sha256", "information_cutoff_utc")})
        expected = wire.canonical(receipt), value["candidate_sha256"], catalog_cap.sha256, source_cap.sha256

        def capture_check(body, candidate_sha, catalog_sha, registry_sha, expected=expected):
            recheck()
            admission.require((body, candidate_sha, catalog_sha, registry_sha) == expected,
                              "WIRE_CAPTURE_OR_IDENTITY_EVIDENCE")

        captures.append(wire.finalize_capture(value, receipt, catalog_cap, source_cap,
                                               verify_owner_capture=capture_check))
    expected_rows = [deepcopy(c.document) for c in captures]
    created_at = admission.stamp(admission.current(now))
    admission.require(wire.clock(readback_at) <= wire.clock(created_at), "WIRE_COMPLETION_CLOCK_REVERSED")
    for row in expected_rows:
        if wire.clock(created_at) >= wire.clock(row["kickoff_utc"]):
            row["retained_capture"] = True
    export_sha = wire.digest(dict(capture=report, row_commitment=wire.digest(expected_rows),
        lane="SHADOW_ONLY", primary_activation=False))

    def export_check(body, catalog_sha, registry_sha):
        recheck()
        feed = wire.strict_json(body)
        rows = deepcopy(expected_rows)
        for row in rows:
            if wire.clock(created_at) >= wire.clock(row["kickoff_utc"]):
                row["retained_capture"] = True
        admission.require(catalog_sha == catalog_cap.sha256 and registry_sha == source_cap.sha256
            and feed["rows"] == rows and feed["owner_export_receipt_sha256"] == export_sha,
            "WIRE_EXPORT_CHANGED_OR_UNVERIFIED")

    feed = wire.export_feed(captures, catalog_cap, source_cap, created_at=created_at,
        owner_export_receipt_sha256=export_sha, verify_owner_export=export_check)
    feed_bytes = wire.canonical(feed) + b"\n"
    physical_sha = admission.sha(feed_bytes)
    name = out + "/" + physical_sha + ".json"
    admission.write_new(root, name, feed)
    admission.require(admission.read(root, name) == feed_bytes, "SHADOW_WIRE_READBACK")
    completed_at = admission.stamp(admission.current(now))
    admission.require(wire.clock(created_at) <= wire.clock(completed_at), "WIRE_PUBLICATION_CLOCK_REVERSED")
    result = dict(summary, schema="website-m3-shadow-numerical-publication-v1",
        immutable_feed=name, feed_sha256=physical_sha, feed_bytes=len(feed_bytes),
        feed_canonical_sha256=wire.digest(feed), rows=len(feed["rows"]),
        prepared_at=completed_at, original_readback_at=readback_at,
        current_use_allowed=context["native_body_sha256"] is not None and wire.clock(completed_at) < wire.clock(env["expires_at"]),
        primary_activation=False, live_pointer_written=False,
        publication="LOCAL_IMMUTABLE_SHADOW_ASSET;NOT_DEPLOYED_OR_SERVED",
        ranking_policy_change=False, direction_policy_change=False, probability_product=False)
    admission.write_new(root, out + "/PUBLICATION_RECEIPT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "manifest", "inspection", "registration", "envelope", "out"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--publication-comment-id", type=int, required=True)
    parser.add_argument("--native-body")
    args = parser.parse_args()
    print(json.dumps(numerical_shadow(args.root, args.manifest, args.inspection, args.registration,
        args.envelope, args.publication_comment_id, args.out, native_body=args.native_body), sort_keys=True))


if __name__ == "__main__":
    main()
