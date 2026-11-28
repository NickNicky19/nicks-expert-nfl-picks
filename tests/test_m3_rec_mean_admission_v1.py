"""Synthetic actual-body and transport tests, never NFL performance evidence."""
import copy
import gzip
import json
import lzma
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import m3_rec_mean_admission_v1 as a


def t(clock):
    return a.clock("2026-12-01T" + clock + ":00Z")


class AdmissionFixture:
    """Reusable synthetic private bundle for owned publisher integration tests."""
    def __init__(self, root, *, zero_mean=False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.run = "C-M3-REC-MEAN-SYNTHETIC-01"
        self.base = "prospective/runs/" + self.run
        self.manifest_path = self.base + "/INPUT_MANIFEST.json"
        self.inspection_path = "inspection.json"
        self.registration = "registration"
        self.envelope_path = self.base + "/REC_MEAN_ENVELOPE.json"
        self.native_path = "private/native.source"
        self.responses = {}
        self.calls = []
        self.event = dict(season=2026, week=13, game_id="2026_13_DEN_PIT", native_event_id="401899999",
                          away_team="DEN", home_team="PIT", kickoff_UTC="2026-12-01T20:00:00Z")
        prior = dict(kind="count", empty=False, mu=1, center=0, q=0.5, event=2.5)
        tree = dict(left=[-1], right=[-1], feature=[-2], threshold=[-2.0], leaves={"0":[[0,2],[1,3]]})
        model = dict(schema="C-NUMERIC-LEAF-v4", kind="count", scale=1, imputation=[1.0]*32,
                     prior={"WR":prior}, global_prior=dict(prior, q=0.25), trees=[copy.deepcopy(tree) for _ in range(32)])
        if zero_mean:
            for value in [*model["prior"].values(),model["global_prior"]]:
                value.update(empty=True,mu=0)
            for value in model["trees"]:
                value["leaves"]={"0":[[0],[7]]}
        self.put_bytes(self.base + "/CURRENT_MODEL.json.gz", gzip.compress(a.canonical(model), mtime=0))
        rows = []
        for n, role in enumerate(("WR", "TE"), 1):
            features = [0.0]*32
            features[18 if role == "WR" else 19] = 1.0
            rows.append(dict(player_id=f"00-{n:07d}", sleeper_id=str(100+n), espn_player_id=str(200+n),
                             position=role, team="DEN", opponent_team="PIT", features=features,
                             last_prior_game=None, last_team_game=None))
        self.query = dict(event=self.event, product=a.PRODUCT, feature_order=a.FEATURES, rows=rows)
        self.put(self.base + "/QUERY_PROJECTION.json", self.query)
        bridge = [{k:r[k] for k in ("player_id", "sleeper_id", "espn_player_id", "team", "opponent_team", "position")} for r in rows]
        procedure = dict(recipe=a.RECIPE, family=a.FAMILY, order=a.FEATURES,
                         update="H-MULTI/E0_OP32/weekly_first_kickoff/strict_7d", conditional_on=a.CONDITION)
        profile = dict(family=a.FAMILY, product=a.PRODUCT, functional="unrounded Law.mean()",
                       corrector="NO_EXTRA_CORRECTOR", conditioning_contract_sha256=a.CONDITION_SHA)
        observations = {name:dict(url="https://example.invalid/"+name, bytes=2, sha256="1"*64,
                        observed_UTC="2026-12-01T18:59:00Z", headers={"Date":"Tue, 01 Dec 2026 18:59:00 GMT"})
                        for name in ("schedule", "roster", "weekly")}
        source_contract = dict(target="rec", history=procedure["update"], event_role=["WR", "TE"],
                               sources=[x["url"] for x in observations.values()], conditioning_contract_sha256=a.CONDITION_SHA)
        source_evidence = dict(event=self.event, observations=observations, cutoff_UTC="2026-12-01T19:00:00Z")
        features = dict(completed_UTC="2026-12-01T19:01:00Z", order_SHA256=a.fingerprint(a.FEATURES),
                        query_SHA256=a.fingerprint(self.query), identity_SHA256=a.fingerprint(bridge), source_SHA256=a.fingerprint(source_evidence))
        training = dict(actual_rows=100, feature_order_sha256=a.fingerprint(a.FEATURES), training_member_sha256="2"*64,
                        role_sequence_sha256="3"*64, retained_recipe_X_y_sha256="4"*64, training_NaN_mask_sha256="5"*64,
                        latest_training_available_UTC="2026-11-30T00:00:00Z", fit_cutoff_UTC="2026-12-01T01:00:00Z",
                        roster_publication_UTC="2026-12-01T18:00:00Z", information_cutoff_UTC="2026-12-01T19:00:00Z")
        model_desc = self.binding(self.base + "/CURRENT_MODEL.json.gz")
        artifact = dict(model=model_desc, procedure_sha256=a.fingerprint(procedure), training=training,
                        fit_started_UTC="2026-12-01T19:02:00Z", fit_completed_UTC="2026-12-01T19:03:00Z")
        common = dict(target="rec", model_version=a.fingerprint(artifact), procedure_version=a.fingerprint(procedure),
                      point_profile_sha256=a.fingerprint(profile), source_policy_sha256=a.fingerprint(a.SOURCE_POLICY),
                      source_contract_sha256=a.fingerprint(source_contract), public_roles=["WR", "TE"])
        entry = dict(common, scoring_target="rec", method_id=a.PRODUCT, base_learner_id="P2_LEAF",
                     artifact_sha256=a.fingerprint(artifact), model_bytes_sha256=model_desc["SHA256"],
                     base_procedure_version=a.fingerprint(procedure), forecast_product="point_mean", prediction_functional="expected_mean",
                     original_contract_version="C-M3-v1.1", conditional_on=a.CONDITION, conditioning_contract_sha256=a.CONDITION_SHA)
        source = dict(common, identity_bridge_sha256=a.fingerprint(bridge), source_receipt_sha256=a.fingerprint(source_evidence),
                      feature_capture_receipt_sha256=a.fingerprint(features), feature_binding_sha256=a.fingerprint({"order":a.FEATURES,"rows":rows}),
                      query_projection_sha256=a.fingerprint(self.query), query_source_sha256=a.fingerprint({"event":self.event,"ids":bridge}),
                      information_cutoff_utc="2026-12-01T19:00:00Z", feature_capture_completed_at="2026-12-01T19:01:00Z",
                      conditional_on=a.CONDITION, conditioning_contract_sha256=a.CONDITION_SHA, expires_at="2026-12-01T19:55:00Z")
        self.m = dict(state="ACTUAL_MODEL_AND_QUERY_PENDING_OWNER_ADMISSION", run=self.run, product=a.PRODUCT,
                      event=self.event, model=model_desc, query=self.binding(self.base + "/QUERY_PROJECTION.json"),
                      model_artifact=artifact, procedure=procedure, point_profile=profile, source_contract=source_contract,
                      source_evidence=source_evidence, feature_capture=features, identity_bridge=bridge,
                      source_record_proposal=source, catalog_entry_proposal=entry, issued_at=None, prior_fit_reused=False)
        self.put(self.manifest_path, self.m)

    def put_bytes(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def put(self, name, data):
        self.put_bytes(name, a.canonical(data) + b"\n")

    def get(self, name):
        return json.loads((self.root/name).read_bytes())

    def binding(self, name):
        body = (self.root/name).read_bytes()
        return dict(path=name, bytes=len(body), SHA256=a.sha(body))

    def comment(self, identifier, marker, value, when):
        comment = dict(id=identifier, user={"id":a.OWNER}, issue_url=f"https://api.github.com/repos/{a.WEBSITE}/issues/1",
                       author_association="OWNER", created_at=when, updated_at=when,
                       html_url=f"https://github.com/{a.WEBSITE}/pull/1#issuecomment-{identifier}",
                       body=marker+"\n```json\n"+a.canonical(value).decode()+"\n```")
        url=f"https://api.github.com/repos/{a.WEBSITE}/issues/comments/{identifier}"
        self.responses[url] = a.canonical(comment)
        return comment

    def fetch(self, url, cap, raw=False):
        self.calls.append((url, cap, raw))
        if url not in self.responses:
            raise AssertionError("Unregistered test network route: " + url)
        body = self.responses[url]
        if len(body)>cap:
            raise ValueError("TEST_RESPONSE_CAP")
        return body

    def inspect(self):
        _, _, report = a.inspect_bundle(self.root, self.manifest_path, now=lambda:t("19:04"))
        a.write_new(self.root, self.inspection_path, report)
        self.report=report
        self.report_hash=self.binding(self.inspection_path)["SHA256"]
        return report

    def register(self):
        self.inspect()
        statement = a.source_review_statement(self.m, self.report, self.report_hash)
        self.review = self.comment(123, "M3_SOURCE_REVIEW_V1", statement, "2026-12-01T19:05:00Z")
        return a.register(self.root, self.manifest_path, self.inspection_path, self.registration, 123,
                          fetch=self.fetch, now=lambda:t("19:06"))

    def deliver(self, change=None):
        self.register()
        registry = self.get("registration/SOURCE_REGISTRY.json")
        catalog = self.get("registration/MODEL_CATALOG.json")
        verification = self.get("registration/VERIFICATION_REPORT.json")
        self.publication = self.comment(124,"M3_PREISSUE_REGISTRATION_V1",dict(schema="website-m3-preissue-publication-v1",
            run=self.run,product=a.PRODUCT,event_id=self.event["native_event_id"],source_registry=registry,
            model_catalog=catalog,verification_report=verification), "2026-12-01T19:07:00Z")
        originals=[]
        for row,p in zip(self.query["rows"],self.report["predictions"]):
            original=dict(forecast_id=a.fingerprint([self.run,self.event["game_id"],row["player_id"],a.PRODUCT])[:24],
                product=a.PRODUCT,game_id=self.event["game_id"],expected_mean=p["mean"],selected_projection=p["mean"],
                prior_mixture=p["prior_mixture"],attribution="LEARNED_LEAF_WITH_EXPLICIT_PRIOR_TAIL",
                inference_UTC="2026-12-01T19:34:00Z",issued_UTC="2026-12-01T19:35:00Z",expires_UTC="2026-12-01T19:55:00Z",
                **{k:row[k] for k in ("player_id","position","team","opponent_team","sleeper_id")})
            originals.append(original)
        if change:
            change(originals)
        self.put_bytes(self.base+"/FORECASTS.json.xz",lzma.compress(a.canonical(originals),preset=3))
        desc=self.binding(self.base+"/FORECASTS.json.xz")
        commit="a"*40
        workflow=dict(id=999,repository={"full_name":a.PRODUCER},head_branch=a.BRANCH,path=".github/workflows/c-checks-pages.yml",
            event="pull_request",status="completed",conclusion="success",head_sha=commit,pull_requests=[],
            html_url=f"https://github.com/{a.PRODUCER}/actions/runs/999",created_at="2026-12-01T19:36:00Z",
            run_started_at="2026-12-01T19:37:00Z",updated_at="2026-12-01T19:38:00Z")
        self.workflow=workflow
        self.responses[f"https://api.github.com/repos/{a.PRODUCER}/actions/runs/999"]=a.canonical(workflow)
        proof=dict(run=self.run,capture_commit=commit,original_SHA256=desc["SHA256"],original_bytes=desc["bytes"],
            workflow_run_id=999,workflow_run_url=workflow["html_url"],created_UTC=workflow["created_at"],started_UTC=workflow["run_started_at"],
            completed_UTC=workflow["updated_at"],actual_original_readback_UTC="2026-12-01T19:39:00Z")
        serverpath="prospective/receipts/"+self.run+"-server.json"
        self.put(serverpath,proof)
        state=dict(state="pre",name="STATUS_SCHEDULED",completed=False)
        native=dict(events=[dict(id=self.event["native_event_id"],date=self.event["kickoff_UTC"],week={"number":13},
            season={"year":2026,"type":2},status={"type":state},competitions=[dict(id=self.event["native_event_id"],status={"type":state},
                competitors=[{"homeAway":"home","team":{"abbreviation":"PIT"}},{"homeAway":"away","team":{"abbreviation":"DEN"}}])])])
        self.put(self.native_path,native)
        native_status=dict(game_id=self.event["game_id"],espn_event_id=self.event["native_event_id"],competition_id=self.event["native_event_id"],
            competition_state_agreement=True,week=13,kickoff_UTC=self.event["kickoff_UTC"],home_team="PIT",away_team="DEN",season=2026,
            season_type=2,state="pre",status_name="STATUS_SCHEDULED",completed=False,observed_UTC="2026-12-01T19:30:00Z",source_id=self.run)
        admission=dict(registry_sha256=a.fingerprint(registry),catalog_sha256=a.fingerprint(catalog),
            registry_registered_at=registry["registered_at"],catalog_registered_at=catalog["registered_at"],
            review={"locator":self.publication["html_url"]},verified_UTC="2026-12-01T19:08:00Z")
        run=dict(run=self.run,event=self.event,product=a.PRODUCT,state="ISSUED_AWAITING_GITHUB_PROOF",issued_UTC="2026-12-01T19:35:00Z",
            originals=desc,inputs=self.binding(self.manifest_path),registry=admission,native_status=native_status,
            native_source=dict(id=self.run,SHA256=self.binding(self.native_path)["SHA256"],observed_UTC="2026-12-01T19:30:00Z",
                HTTP_Date="Tue, 01 Dec 2026 19:30:00 GMT",HTTP_Age="0"),actual_expiry_UTC="2026-12-01T19:55:00Z",coverage={},native=2,prior_only=0)
        self.put(self.base+"/RUN.json",run)
        self.responses[f"https://api.github.com/repos/{a.PRODUCER}/contents/{self.base}/RUN.json?ref={commit}"]=(self.root/(self.base+"/RUN.json")).read_bytes()
        self.responses[f"https://api.github.com/repos/{a.PRODUCER}/contents/{self.base}/FORECASTS.json.xz?ref={commit}"]=(self.root/(self.base+"/FORECASTS.json.xz")).read_bytes()
        typed=[]
        for row,query in zip(originals,self.query["rows"]):
            typed.append(dict(row,query_fingerprint=a.query_fingerprint(row,query,self.m,registry,proof),conditional_on=a.CONDITION,
                conditioning_contract_sha256=a.CONDITION_SHA,forecast_product="point_mean",prediction_functional="expected_mean",
                expected_mean_kind="full_law_expected_mean",label="Appearance-conditioned mean",mean_eligible=True,functional_proof=None,fallback=False))
        self.envelope=dict(schema="C-M3-0-MANUAL-RECEPTION-MEAN-ENVELOPE-v1",run=self.run,event=self.event,product=a.PRODUCT,
            model=self.m["model"],query=self.m["query"],source=self.m["source_record_proposal"],catalog_entry=self.m["catalog_entry_proposal"],
            actual_website_admission=admission,originals=desc,server=proof,server_receipt=self.binding(serverpath),coverage={},native=2,prior_only=0,
            expires_at="2026-12-01T19:55:00Z",issued_at="2026-12-01T19:35:00Z",issue_deadline_utc="2026-12-01T19:40:00Z",
            prepared_UTC="2026-12-01T19:42:00Z",rows=typed)
        self.put(self.envelope_path,self.envelope)
        return self.envelope

    def capture(self, at="19:45", *, native=True, return_context=False):
        return a.capture(self.root,self.manifest_path,self.inspection_path,self.registration,self.envelope_path,124,"shadow.json",
            native_body=self.native_path if native else None,fetch=self.fetch,now=lambda:t(at),return_context=return_context)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.f=AdmissionFixture(self.temp.name)

    def test_actual_model_and_query_reopen_and_hand_calculated_means(self):
        report=self.f.inspect()
        self.assertAlmostEqual(report["predictions"][0]["mean"],1.475)
        self.assertAlmostEqual(report["predictions"][1]["mean"],0.95*1.5+0.05/3)
        self.assertNotIn("features",json.dumps(report))

    def test_missing_model_and_tampered_actual_body_stop(self):
        path=self.f.root/self.f.m["model"]["path"]
        path.write_bytes(path.read_bytes()+b"tamper")
        with self.assertRaisesRegex(ValueError,"BOUND_BODY_MISMATCH"):
            self.f.inspect()
        path.unlink()
        with self.assertRaises(FileNotFoundError): self.f.inspect()

    def test_query_feature_body_change_is_not_admitted_by_old_hash(self):
        self.f.query["rows"][0]["features"][0]=99
        self.f.put(self.f.m["query"]["path"],self.f.query)
        with self.assertRaisesRegex(ValueError,"BOUND_BODY_MISMATCH"):
            self.f.inspect()

    def test_wrong_or_missing_role_onehot_is_not_a_qualified_query(self):
        for values in ([0,0,0,1], [0,0,None,0]):
            self.f.query["rows"][0]["features"][16:20]=values
            self.f.put(self.f.m["query"]["path"],self.f.query)
            self.f.m["query"]=self.f.binding(self.f.m["query"]["path"])
            self.f.put(self.f.manifest_path,self.f.m)
            with self.subTest(values=values),self.assertRaisesRegex(ValueError,"QUERY_ROLE_ONEHOT_MISMATCH"):
                self.f.inspect()

    def test_placeholder_and_old_condition_cannot_register(self):
        self.f.m["state"]="PLACEHOLDER";self.f.put(self.f.manifest_path,self.f.m)
        with self.assertRaisesRegex(ValueError,"ACTUAL_CURRENT_FIT"):
            self.f.inspect()

    def test_old_played_condition_is_not_a_compatible_relabel(self):
        self.f.m["procedure"]["conditional_on"]="played";self.f.put(self.f.manifest_path,self.f.m)
        with self.assertRaisesRegex(ValueError,"FROZEN_PROCEDURE_CHANGED"):
            self.f.inspect()

    def test_source_or_feature_crosshash_change_is_rejected(self):
        self.f.m["feature_capture"]["source_SHA256"]="0"*64;self.f.put(self.f.manifest_path,self.f.m)
        with self.assertRaisesRegex(ValueError,"FEATURE_CAPTURE_CROSSHASH"):
            self.f.inspect()

    def test_untrusted_or_edited_source_review_fails_no_catalog(self):
        self.f.inspect();statement=a.source_review_statement(self.f.m,self.f.report,self.f.report_hash)
        comment=self.f.comment(123,"M3_SOURCE_REVIEW_V1",statement,"2026-12-01T19:05:00Z")
        for key,value in (("user",{"id":1}),("updated_at","2026-12-01T19:05:01Z")):
            bad=dict(comment);bad[key]=value
            self.f.responses[f"https://api.github.com/repos/{a.WEBSITE}/issues/comments/123"]=a.canonical(bad)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,"AUTHENTIC_UNEDITED"):
                a.register(self.f.root,self.f.manifest_path,self.f.inspection_path,"registration",123,fetch=self.f.fetch,now=lambda:t("19:06"))
        self.assertFalse((self.f.root/"registration").exists())

    def test_genuine_owner_review_creates_closed_local_docs_only(self):
        result=self.f.register()
        self.assertEqual(result["state"],"LOCAL_VERIFIED_REGISTRATION_AWAITING_PUBLICATION")
        self.assertFalse(result["primary_activation"])
        a.wire.validate_registry(self.f.get("registration/SOURCE_REGISTRY.json"))
        a.wire.validate_catalog(self.f.get("registration/MODEL_CATALOG.json"))
        public=json.dumps(self.f.get("registration/VERIFICATION_REPORT.json"))
        self.assertNotIn("predictions",public);self.assertNotIn("features",public)

    def test_registration_uses_completion_clock_and_rejects_crossed_expiry(self):
        self.f.inspect();statement=a.source_review_statement(self.f.m,self.f.report,self.f.report_hash)
        self.f.comment(123,"M3_SOURCE_REVIEW_V1",statement,"2026-12-01T19:05:00Z")
        readings=iter([t("19:06"),t("19:08")])
        a.register(self.f.root,self.f.manifest_path,self.f.inspection_path,"completion-registration",123,
                   fetch=self.f.fetch,now=lambda:next(readings))
        self.assertEqual(self.f.get("completion-registration/SOURCE_REGISTRY.json")["registered_at"],"2026-12-01T19:08:00Z")
        readings=iter([t("19:54"),t("19:56")])
        with self.assertRaisesRegex(ValueError,"REGISTRATION_COMPLETION_EXPIRED"):
            a.register(self.f.root,self.f.manifest_path,self.f.inspection_path,"expired-registration",123,
                       fetch=self.f.fetch,now=lambda:next(readings))
        self.assertFalse((self.f.root/"expired-registration").exists())

    def test_valid_originals_capture_in_shadow_with_actual_server_checks(self):
        self.f.deliver();result,context=self.f.capture(return_context=True)
        self.assertEqual(result["state"],"DELIVERED_SHADOW");self.assertEqual(result["forecast_count"],2)
        self.assertFalse(result["primary_activation"]);self.assertEqual(result["new_forecasts_generated"],0)
        self.assertTrue(context["shadow_receipt"]["native_raw_body_reproduced"])
        self.assertEqual(context["originals"][0]["issued_UTC"],"2026-12-01T19:35:00Z")
        self.assertEqual(len(self.f.calls),6)  # Register source review + 5 capture reads.
        self.assertFalse(any("espn.com" in x[0] for x in self.f.calls))

    def test_async_after_expiry_and_kickoff_preserves_original_no_reissue(self):
        self.f.deliver();result,context=self.f.capture(at="21:00",return_context=True)
        self.assertEqual(result["retention_disposition"],"EXPIRED_ORIGINAL_RETAINED")
        self.assertFalse(result["current_use_allowed"]);self.assertFalse(result["primary_activation"])
        self.assertEqual(result["new_forecasts_generated"],0)
        self.assertEqual(context["originals"],self.f.get("shadow.json")["rows"])
        self.assertEqual(context["original_readback_at"],"2026-12-01T21:00:00Z")

    def test_readback_crossing_expiry_uses_actual_completion_clock(self):
        self.f.deliver()
        readings=iter([a.clock("2026-12-01T19:54:59Z"),a.clock("2026-12-01T19:55:01Z")])
        result,context=a.capture(self.f.root,self.f.manifest_path,self.f.inspection_path,self.f.registration,
            self.f.envelope_path,124,"crossing-shadow.json",native_body=self.f.native_path,
            fetch=self.f.fetch,now=lambda:next(readings),return_context=True)
        self.assertFalse(result["current_use_allowed"])
        self.assertEqual(result["retention_disposition"],"EXPIRED_ORIGINAL_RETAINED")
        self.assertEqual(context["original_readback_at"],"2026-12-01T19:55:01Z")
        self.assertEqual(context["shadow_receipt"]["captured_at"],"2026-12-01T19:55:01Z")

    def test_fractional_issue_can_follow_same_second_server_created_clock(self):
        issued="2026-12-01T19:35:00.500000Z"
        self.f.deliver(lambda rows:[r.update(issued_UTC=issued) for r in rows])
        self.f.workflow["created_at"]="2026-12-01T19:35:00Z"
        self.f.responses[f"https://api.github.com/repos/{a.PRODUCER}/actions/runs/999"]=a.canonical(self.f.workflow)
        env=self.f.envelope;env["issued_at"]=issued;env["server"]["created_UTC"]=self.f.workflow["created_at"]
        serverpath=env["server_receipt"]["path"]
        self.f.put(serverpath,env["server"]);env["server_receipt"]=self.f.binding(serverpath)
        self.f.put(self.f.envelope_path,env)
        runpath=self.f.base+"/RUN.json";run=self.f.get(runpath);run["issued_UTC"]=issued
        self.f.put(runpath,run)
        key=next(k for k in self.f.responses if "/RUN.json?ref=" in k)
        self.f.responses[key]=(self.f.root/runpath).read_bytes()
        result=self.f.capture()
        self.assertEqual(result["state"],"DELIVERED_SHADOW")

    def test_originals_with_all_outcomes_unknown_stay_frozen_and_ungraded(self):
        self.f.deliver();self.f.capture()
        receipt=self.f.get("shadow.json")
        self.assertEqual(receipt["outcomes"],"NOT_SUPPLIED_UNGRADED")
        self.assertEqual(len(receipt["rows"]),2)
        self.assertTrue(all("outcome" not in x and "grade" not in x for x in receipt["rows"]))

    def test_missing_native_body_retains_honest_source_limited_shadow(self):
        self.f.deliver();result,context=self.f.capture(native=False,return_context=True)
        self.assertEqual(result["state"],"DELIVERED_SHADOW_SOURCE_LIMITED")
        self.assertFalse(result["current_use_allowed"])
        self.assertFalse(context["shadow_receipt"]["native_raw_body_reproduced"])

    def test_forged_workflow_success_or_revision_is_rejected(self):
        self.f.deliver();self.f.workflow["head_sha"]="b"*40
        self.f.responses[f"https://api.github.com/repos/{a.PRODUCER}/actions/runs/999"]=a.canonical(self.f.workflow)
        with self.assertRaisesRegex(ValueError,"AUTHENTIC_C_WORKFLOW"):
            self.f.capture()

    def test_changed_mean_even_with_consistent_original_hashes_fails(self):
        self.f.deliver(lambda rows:rows[0].update(expected_mean=8,selected_projection=8))
        with self.assertRaisesRegex(ValueError,"DELIVERED_MEAN_CHANGED"):
            self.f.capture()

    def test_changed_identity_even_with_consistent_original_hashes_fails(self):
        self.f.deliver(lambda rows:rows[0].update(player_id="00-9999999"))
        with self.assertRaisesRegex(ValueError,"DELIVERED_IDENTITY"):
            self.f.capture()

    def test_fabricated_prior_only_attribution_is_not_a_valid_fallback(self):
        self.f.deliver(lambda rows:rows[0].update(prior_mixture=1,attribution="PRIOR_ONLY"))
        with self.assertRaisesRegex(ValueError,"ATTRIBUTION_CHANGED"):
            self.f.capture()

    def test_real_zero_mean_remains_known_numeric_zero(self):
        other=AdmissionFixture(self.f.root/"zero",zero_mean=True)
        other.deliver();result,context=other.capture(return_context=True)
        self.assertEqual(result["forecast_count"],2)
        self.assertEqual([r["expected_mean"] for r in context["originals"]],[0.0,0.0])
        self.assertEqual(result["outcomes"],"NOT_SUPPLIED_UNGRADED")

    def test_changed_query_fingerprint_is_not_a_display_binding(self):
        self.f.deliver();self.f.envelope["rows"][0]["query_fingerprint"]="0"*64
        self.f.put(self.f.envelope_path,self.f.envelope)
        with self.assertRaisesRegex(ValueError,"EXACT_QUERY_ROW_FINGERPRINT"):
            self.f.capture()

    def test_changed_expiry_cannot_override_registered_source(self):
        self.f.deliver();self.f.envelope["expires_at"]="2026-12-01T19:56:00Z"
        self.f.put(self.f.envelope_path,self.f.envelope)
        with self.assertRaisesRegex(ValueError,"DELIVERED_EXPIRY_CHANGED"):
            self.f.capture()

    def test_late_authenticated_registration_does_not_become_pregame(self):
        self.f.deliver();comment=copy.deepcopy(self.f.publication)
        comment["created_at"]=comment["updated_at"]="2026-12-01T19:36:00Z"
        self.f.responses[f"https://api.github.com/repos/{a.WEBSITE}/issues/comments/124"]=a.canonical(comment)
        with self.assertRaisesRegex(ValueError,"REGISTRATION_BEFORE_ISSUE"):
            self.f.capture()

    def test_remote_original_readback_must_be_exact(self):
        self.f.deliver()
        key=next(k for k in self.f.responses if "/FORECASTS.json.xz?ref=" in k)
        self.f.responses[key]=b"different body"
        with self.assertRaisesRegex(ValueError,"IMMUTABLE_ORIGINAL_READBACK"):
            self.f.capture()

    def test_native_stale_http_clock_does_not_pass_from_local_observation(self):
        self.f.deliver()
        run=self.f.get(self.f.base+"/RUN.json");run["native_source"]["HTTP_Date"]="Tue, 01 Dec 2026 18:00:00 GMT"
        self.f.put(self.f.base+"/RUN.json",run)
        key=next(k for k in self.f.responses if "/RUN.json?ref=" in k)
        self.f.responses[key]=(self.f.root/(self.f.base+"/RUN.json")).read_bytes()
        with self.assertRaisesRegex(ValueError,"NATIVE_HTTP_DATE"):
            self.f.capture()

    def test_native_earlier_expiry_is_not_the_frozen_producer_policy(self):
        self.f.deliver();run=self.f.get(self.f.base+"/RUN.json")
        with self.assertRaisesRegex(ValueError,"EXACT_PRODUCER_EXPIRY_REQUIRED"):
            a.validate_native(self.f.get(self.f.native_path),run["native_source"],self.f.event,t("19:35"),
                              t("19:07"),t("19:54"),self.f.m)

    def test_native_http_clock_must_remain_valid_through_declared_expiry(self):
        self.f.deliver();run=self.f.get(self.f.base+"/RUN.json")
        # At issuance this Date is25minutes old, but cannot support19:55 expiry.
        run["native_source"]["HTTP_Date"]="Tue, 01 Dec 2026 19:10:00 GMT"
        with self.assertRaisesRegex(ValueError,"NATIVE_EXPIRY_NOT_SUPPORTED"):
            a.validate_native(self.f.get(self.f.native_path),run["native_source"],self.f.event,t("19:35"),
                              t("19:07"),t("19:55"),self.f.m)

    def test_symlink_traversal_and_immutable_output_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"UNSAFE_PATH"):
            a.read(self.f.root,"../outside")
        link=self.f.root/"link";link.symlink_to(self.f.root/self.f.manifest_path)
        with self.assertRaisesRegex(ValueError,"SYMLINK"):
            a.read(self.f.root,"link")
        self.f.inspect()
        with self.assertRaises(FileExistsError):
            a.write_new(self.f.root,self.f.inspection_path,{"overwrite":True})

    def test_duplicate_json_keys_and_nonfinite_values_rejected(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE_JSON"):
            a.parse(b'{"x":1,"x":2}')
        with self.assertRaisesRegex(ValueError,"NONFINITE_JSON"):
            a.parse(b'{"x":NaN}')


if __name__=="__main__":
    unittest.main()
