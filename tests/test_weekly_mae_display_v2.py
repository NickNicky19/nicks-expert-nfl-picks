"""Reconstructed seven wire controls plus the retained publisher controls.

Original seven-control source bytes were overwritten and are unavailable.
The seven logged test names/semantics are reconstructed honestly from the exact
retained fictional wire fixture. No model/native admission is asserted here.
The original fixture() runpy ABI remains standard-library only.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

_WIRE_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(_WIRE_ROOT/"tools"))
import stat_point_mae_public_v2 as wire

_WIRE_FIXTURE_BYTES=b'{"catalog":{"entries":[{"artifact_sha256":"605df8944e47d11b17c3d64420ee21d9cb0143d1f6f26b91845fc7a0e6474dc1","base_learner_id":"LAB_CDF","base_procedure_version":"3d7367e908e672efb9a21a6fdcb4cf96058f69169eeed55f46377286283d0735","forecast_product":"point_median","method_id":"LAB_CDF_FULL_LAW_MEDIAN_V2","model_bytes_sha256":"df84afcd36cfa099dbd9413a53623a9e0ea1c9ab7e32d00c2ee74c4db4e9a7d9","model_version":"605df8944e47d11b17c3d64420ee21d9cb0143d1f6f26b91845fc7a0e6474dc1","original_contract_version":"weekly-adaptive-release-v1-future-inference","point_profile_sha256":"d1f40e21cb87f83fa2fa482a9517d8c294c9c965eaee7060b9fd35e641de3c49","prediction_functional":"full_cdf_lower_median","procedure_version":"16618eb511448c799714f15a091f6b2a1e3117de162288e93ddfe28dbdf1a574","public_roles":["RB"],"scoring_target":"rush_att","source_contract_sha256":"322653f4e6535dee292b7c9241bebebcf18f9867187073c43c5cf9303d9a23a7","source_policy_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","target":"rush_att"}],"owner_admission_receipt_sha256":"55703089c1e79013a0cc3d83779b164fb30fcfec200130dfa984347aac8b8669","registered_at":"2099-10-30T00:00:00Z","schema_version":"stat-point-mae-public-catalog-v2-draft2","selection_metric":"MAE","selection_product":"stat_point_mae_v2"},"catalog_sha256":"305cee7c7c23d3f138ee904d931418ef4031004e5d12b41ad6b6a7f389c25f54","created_at":"2099-10-31T01:16:00Z","owner_export_receipt_sha256":"dc2b249321fe9bae222d0896a632999a63fc715431f58300e558ddfb9e96b7fe","rows":[{"artifact_sha256":"605df8944e47d11b17c3d64420ee21d9cb0143d1f6f26b91845fc7a0e6474dc1","base_learner_id":"LAB_CDF","base_procedure_version":"3d7367e908e672efb9a21a6fdcb4cf96058f69169eeed55f46377286283d0735","candidate_sha256":"bac8996dbb53016477bc7f8f5eef0e052a2800dfca16456a487951943683c154","capture_body_sha256":"419e8e08efe908ba0db9014714436c4b8eeb379873eca75ab8fdb79d2dc511e3","capture_receipt_sha256":"e1d5c5736a198398ebbeeebd76c5eba228014144eccb46877380c6b61c0b26fe","conditional_on":"played","consumer_contract_version":"stat-point-mae-v2","expected_mean":3.0,"expected_mean_kind":"full_law_expected_mean","fallback":true,"fallback_reason":"cold_start_role_prior","feature_binding_sha256":"cc99084343335466d468f0318b08846ce11cacbe7a7fac83e1ac7a2c5dcc6fe0","feature_capture_completed_at":"2099-10-31T00:07:00Z","feature_capture_receipt_sha256":"d826168e769d4c2a774b2324e10acf76e417357371e47c7e1ae42548b86d0f48","feature_max_source_available_utc":null,"forecast_product":"point_median","functional_proof":{"cdf_at":0.578125,"cdf_below":0.43749999999999994,"extractor_version":"full-law-lower-median-view-v2"},"game_id":"fictional-game","horizon":"player_game","identity_binding_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","identity_bridge_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","information_cutoff_utc":"2099-10-31T00:05:00+00:00","issue_deadline_utc":"2099-10-31T01:00:00+00:00","issued_at":"2099-10-31T00:08:00.000002+00:00","kickoff_utc":"2099-10-31T03:00:00+00:00","mean_eligible":true,"method_id":"LAB_CDF_FULL_LAW_MEDIAN_V2","model_bytes_sha256":"df84afcd36cfa099dbd9413a53623a9e0ea1c9ab7e32d00c2ee74c4db4e9a7d9","model_version":"605df8944e47d11b17c3d64420ee21d9cb0143d1f6f26b91845fc7a0e6474dc1","opponent":"QAB","original_contract_version":"weekly-adaptive-release-v1-future-inference","persistence_completed_at":"2099-10-31T00:09:00Z","player_id":"fictional-player-2","point_profile_sha256":"d1f40e21cb87f83fa2fa482a9517d8c294c9c965eaee7060b9fd35e641de3c49","position":"RB","prediction_functional":"full_cdf_lower_median","procedure_version":"16618eb511448c799714f15a091f6b2a1e3117de162288e93ddfe28dbdf1a574","projection_label":"Median fallback","public_roles":["RB"],"query_projection_sha256":"d76e900ef600e43f8c1cf0e584a3024743cff1c9ea3d6777c6a74e4279957846","query_source_sha256":"cc99084343335466d468f0318b08846ce11cacbe7a7fac83e1ac7a2c5dcc6fe0","readback_completed_at":"2099-10-31T01:15:00Z","retained_capture":false,"schema_version":"stat-point-mae-v2","scoring_target":"rush_att","season":2099,"selected_projection":2.0,"selection_metric":"MAE","selection_product":"stat_point_mae_v2","selection_sha256":"a6fa622f3d6924c3db3ecfa3ea006379a0d9b71112c7e9fa823d42a6d19de298","sleeper_id":"101","source_contract_sha256":"322653f4e6535dee292b7c9241bebebcf18f9867187073c43c5cf9303d9a23a7","source_policy_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","source_receipt_sha256":"0892bda1b6123acd9c0cc86ff5cb836fbd97ced7531a306646c0227a25e10a8b","source_registry_sha256":"5c2ca0e5ad4ccd8b3a911a3b878601df99c3844c59bb44c670097ad695e142c9","target":"rush_att","team":"QAA","trained_prior_only":true,"website_game_id":"990000001","week":8}],"schema_version":"stat-point-mae-public-feed-v2-draft2","season":2099,"selection_metric":"MAE","selection_product":"stat_point_mae_v2","source_registry":{"owner_admission_receipt_sha256":"a509859d9e36109a5e5a00490789a321784f815b462bc2a1061482237d387979","records":[{"feature_binding_sha256":"cc99084343335466d468f0318b08846ce11cacbe7a7fac83e1ac7a2c5dcc6fe0","feature_capture_completed_at":"2099-10-31T00:07:00Z","feature_capture_receipt_sha256":"d826168e769d4c2a774b2324e10acf76e417357371e47c7e1ae42548b86d0f48","identity_bridge_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","information_cutoff_utc":"2099-10-31T00:05:00+00:00","model_version":"605df8944e47d11b17c3d64420ee21d9cb0143d1f6f26b91845fc7a0e6474dc1","point_profile_sha256":"d1f40e21cb87f83fa2fa482a9517d8c294c9c965eaee7060b9fd35e641de3c49","procedure_version":"16618eb511448c799714f15a091f6b2a1e3117de162288e93ddfe28dbdf1a574","public_roles":["RB"],"query_projection_sha256":"d76e900ef600e43f8c1cf0e584a3024743cff1c9ea3d6777c6a74e4279957846","query_source_sha256":"cc99084343335466d468f0318b08846ce11cacbe7a7fac83e1ac7a2c5dcc6fe0","source_contract_sha256":"322653f4e6535dee292b7c9241bebebcf18f9867187073c43c5cf9303d9a23a7","source_policy_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","source_receipt_sha256":"0892bda1b6123acd9c0cc86ff5cb836fbd97ced7531a306646c0227a25e10a8b","target":"rush_att"}],"registered_at":"2099-10-31T00:07:30Z","schema_version":"stat-point-mae-source-registry-v2-draft2"},"source_registry_sha256":"5c2ca0e5ad4ccd8b3a911a3b878601df99c3844c59bb44c670097ad695e142c9","week":8}'
_WIRE_FIXTURE_SHA256="88e6dd8cbbafb5d09066df522793b1af09a7cbca9e7118d4ab9e5999a8918f7d"


def fixture():
    return wire.strict_json(_WIRE_FIXTURE_BYTES)


def _wire_reseal(feed):
    feed["catalog_sha256"]=wire.digest(feed["catalog"])
    feed["source_registry_sha256"]=wire.digest(feed["source_registry"])
    for row in feed["rows"]:row["source_registry_sha256"]=feed["source_registry_sha256"]
    return feed


class TypedPointWireChecks(unittest.TestCase):
    def rejects(self,feed):
        with self.assertRaises((ValueError,KeyError,TypeError)):
            wire.validate_feed(feed)

    def test_declared_point_and_expected_mean_remain_distinct(self):
        feed=fixture();wire.validate_feed(feed);row=feed["rows"][0]
        self.assertEqual(hashlib.sha256(wire.canonical(feed)).hexdigest(),_WIRE_FIXTURE_SHA256)
        self.assertEqual(wire.canonical(feed),_WIRE_FIXTURE_BYTES)
        self.assertEqual((row["selected_projection"],row["expected_mean"]),(2.,3.))
        self.assertNotEqual(row["selected_projection"],row["expected_mean"])
        self.assertEqual((row["forecast_product"],row["prediction_functional"]),("point_median","full_cdf_lower_median"))
        mean=fixture();mean["catalog"]["entries"][0].update(forecast_product="point_mean",prediction_functional="expected_mean")
        mean["rows"][0].update(forecast_product="point_mean",prediction_functional="expected_mean",selected_projection=3.,functional_proof=None,projection_label="Mean fallback")
        wire.validate_feed(_wire_reseal(mean))
        self.assertEqual(mean["rows"][0]["selected_projection"],mean["rows"][0]["expected_mean"])
        wrong=deepcopy(mean);wrong["rows"][0]["selected_projection"]=2.;self.rejects(wrong)

    def test_duplicate_canonical_or_website_identity_is_rejected(self):
        for changed in ({},{"sleeper_id":"999"},{"player_id":"fictional-other-canonical"}):
            with self.subTest(changed=changed):
                feed=fixture();duplicate=dict(feed["rows"][0],**changed);feed["rows"].append(duplicate);self.rejects(feed)

    def test_duplicate_json_key_and_nonfinite_input_are_rejected(self):
        for raw in (b'{"x":1,"x":2}',b'{"nested":{"x":1,"x":2}}',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":-Infinity}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):wire.strict_json(raw)
        for value in (float("nan"),float("inf"),float("-inf"),True):
            feed=fixture();feed["rows"][0]["expected_mean"]=value;self.rejects(feed)

    def test_missingness_mislabel_and_unknown_or_private_fields_fail(self):
        for field,value in (("selected_projection",None),("expected_mean",None),("selected_projection",True),
                ("selected_projection","2"),("prediction_functional","intended_median"),("forecast_product","binary_probability"),
                ("conditional_on","unconditional"),("horizon","player_week")):
            with self.subTest(field=field,value=value):
                feed=fixture();feed["rows"][0][field]=value;self.rejects(feed)
        for field in ("selected_projection","capture_receipt_sha256","issued_at"):
            feed=fixture();feed["rows"][0].pop(field);self.rejects(feed)
        for field,value in (("raw_source_path","/private/fictional"),("weights",[1,2]),("probability",.5),("actual",3)):
            feed=fixture();feed["rows"][0][field]=value;self.rejects(feed)
        feed=fixture();feed["private_root"]={"PASS":True};self.rejects(feed)
        feed=fixture();feed["schema_version"]="weekly-derived-selected-feed-v1";self.rejects(feed)

    def test_original_cutoff_and_source_clocks_are_not_repaired(self):
        original=fixture();before=wire.canonical(original)
        changes=(("persistence_completed_at","2099-10-31T01:00:00Z"),("issued_at","2099-10-31T01:00:00Z"),
            ("information_cutoff_utc","2099-10-31T00:08:01Z"),("feature_capture_completed_at","2099-10-31T00:08:01Z"),
            ("readback_completed_at","2099-10-31T00:08:59Z"),("kickoff_utc","2099-10-31T01:00:00Z"),
            ("feature_max_source_available_utc","2099-10-31T00:05:00.000001Z"),("issued_at","2099-10-31T00:08:00"),
            ("kickoff_utc","2099-02-30T03:00:00Z"))
        for field,value in changes:
            with self.subTest(field=field):
                feed=deepcopy(original);feed["rows"][0][field]=value;self.rejects(feed)
        feed=fixture();feed["source_registry"]["registered_at"]="2099-10-31T00:08:01Z";self.rejects(_wire_reseal(feed))
        valid=fixture();valid["rows"][0]["persistence_completed_at"]="2099-10-31T00:59:59.999999Z";wire.validate_feed(valid)
        self.assertEqual(wire.canonical(original),before)

    def test_retained_republication_preserves_the_original_forecast(self):
        feed=fixture();original=deepcopy(feed["rows"][0]);feed["created_at"]="2099-10-31T04:00:00Z"
        self.rejects(feed)
        feed["rows"][0]["retained_capture"]=True;wire.validate_feed(feed)
        retained=deepcopy(feed["rows"][0]);retained.pop("retained_capture");original.pop("retained_capture")
        self.assertEqual(retained,original)
        self.assertEqual((retained["selected_projection"],retained["expected_mean"]),(2.,3.))
        wrong=deepcopy(feed);wrong["rows"][0]["issued_at"]="2099-10-31T04:00:00Z";self.rejects(wrong)

    def test_true_zero_fractional_mean_and_signed_yards_are_retained(self):
        zero=fixture();zero["rows"][0].update(selected_projection=0.,expected_mean=.25,
            functional_proof=dict(extractor_version=wire.FUNCTIONAL_VERSION,cdf_below=0.,cdf_at=.75))
        wire.validate_feed(zero);self.assertEqual(zero["rows"][0]["selected_projection"],0.)
        fraction=fixture();fraction["rows"][0]["expected_mean"]=3.25;wire.validate_feed(fraction)
        self.assertEqual(fraction["rows"][0]["expected_mean"],3.25)
        signed=fixture()
        signed["catalog"]["entries"][0].update(target="rush_yd",scoring_target="rush_yd")
        signed["source_registry"]["records"][0]["target"]="rush_yd"
        signed["rows"][0].update(target="rush_yd",scoring_target="rush_yd",selected_projection=-2.,expected_mean=-1.25,
            functional_proof=dict(extractor_version=wire.FUNCTIONAL_VERSION,cdf_below=.4,cdf_at=.6))
        wire.validate_feed(_wire_reseal(signed));self.assertEqual((signed["rows"][0]["selected_projection"],signed["rows"][0]["expected_mean"]),(-2.,-1.25))


if __name__=="__main__":unittest.main()

# Publisher controls retain their original pytest harness and assertions.
if "pytest" in sys.modules:
    """Fictional native public data/API only; no model admission or live transport."""
    from copy import deepcopy
    import gzip
    import json
    from pathlib import Path
    import sys
    from types import SimpleNamespace

    import pytest

    ROOT=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(ROOT/"tools"))
    import weekly_mae_display_v2 as p
    from reliability import atomic_json

    NOW="2099-10-31T01:30:00Z"
    SOURCE="d"*40
    WEBSITE="e"*40
    RUN="123456789"
    API="https://api.github.com/repos/"+p.common.REPOSITORY+"/actions/runs/"+RUN


    def h(value):return p.digest(value)


    def publisher_fixture():
        policy=p.template();policy.update(state="ROOT_REGISTERED",registered_at_utc="2099-10-30T22:00:00Z")
        policy["producer"].update(source_sha=SOURCE,source_branch="research/fictional-mae",workflow_sha256=h("fictional-reviewed-workflow"),
            jobs=dict(produce="fictional-produce",restore="fictional-reader",consume="fictional-export"))
        policy["registered_recipe"].update(profile_registration_sha256=h("fictional-source-bound-config"),helper_inventory_sha256=h("fictional-final-helpers"))
        policy["registered_recipe_sha256"]=h(policy["registered_recipe"])
        stable=deepcopy(next(e for e in p.STABLE if e["target"]=="pass_int"))
        entry=dict(stable,model_version=h("fictional-current-path-manifest"),artifact_sha256=h("fictional-current-path-manifest"),
            procedure_version=h("fictional-native-prevalue-view-procedure"),point_profile_sha256=h("fictional-native-prevalue-profile"))
        root_sha=h("fictional-actual-native-root")
        catalog=dict(schema_version=p.wire.CATALOG,selection_product=p.wire.PRODUCT,selection_metric=p.wire.METRIC,
            registered_at="2099-10-31T00:00:00Z",owner_admission_receipt_sha256=root_sha,entries=[entry])
        row={k:h(["fictional",k]) for k in p.wire.ROW_KEYS}
        row.update(entry,schema_version="stat-point-mae-v2",consumer_contract_version="stat-point-mae-v2",selection_product=p.wire.PRODUCT,
            selection_metric=p.wire.METRIC,season=2099,week=8,game_id="fictional-canonical-game",player_id="fictional-canonical-player",
            website_game_id="123456789",sleeper_id="101",team="AAA",opponent="BBB",position="QB",horizon="player_game",conditional_on="played",
            information_cutoff_utc="2099-10-31T00:05:00Z",feature_capture_completed_at="2099-10-31T00:07:00Z",issued_at="2099-10-31T00:08:00Z",
            persistence_completed_at="2099-10-31T00:12:00Z",readback_completed_at="2099-10-31T01:15:00Z",
            issue_deadline_utc="2099-10-31T01:00:00Z",kickoff_utc="2099-10-31T03:00:00Z",feature_max_source_available_utc=None,
            selected_projection=2.,expected_mean=3.,expected_mean_kind="full_law_expected_mean",projection_label="Median fallback",
            mean_eligible=True,trained_prior_only=True,fallback=True,fallback_reason="FICTIONAL_TRAINED_PRIOR",retained_capture=False,
            functional_proof=dict(extractor_version=p.wire.FUNCTIONAL_VERSION,cdf_below=.4375,cdf_at=.578125),
            selection_sha256=h("fictional-original-point-catalog"),query_source_sha256=h("fictional-shared-features"),feature_binding_sha256=h("fictional-shared-features"))
        source={k:row[k] for k in p.wire.SOURCE_KEYS}
        registry=dict(schema_version=p.wire.REGISTRY,registered_at="2099-10-31T00:07:30Z",owner_admission_receipt_sha256=root_sha,records=[source])
        feed=dict(schema_version=p.wire.FEED,selection_product=p.wire.PRODUCT,selection_metric=p.wire.METRIC,season=2099,week=8,
            created_at="2099-10-31T01:20:00Z",catalog=catalog,catalog_sha256=h(catalog),source_registry=registry,source_registry_sha256=h(registry),
            rows=[row],owner_export_receipt_sha256=h("fixture-placeholder"))
        receipt={k:h(["fictional-receipt",k]) for k in p.RECEIPT_KEYS}
        jobs={role:dict(job_id=name,api_job_id=777+i) for i,(role,name) in enumerate(policy["producer"]["jobs"].items())}
        receipt.update(schema_version=p.RECEIPT,scope=p.SCOPE,state="POINT_SUBSET_VERIFIED",source_sha=SOURCE,source_branch=policy["producer"]["source_branch"],
            run_id=RUN,run_attempt=1,root_go_sha256=root_sha,profile_registration_sha256=policy["registered_recipe"]["profile_registration_sha256"],
            helper_inventory_sha256=policy["registered_recipe"]["helper_inventory_sha256"],point_policy_sha256=p.POINT_POLICY_SHA256,
            source_policy_sha256=policy["source_policy_sha256"],workflow_sha256=policy["producer"]["workflow_sha256"],jobs=jobs,
            prevalue_catalog_sha256=row["selection_sha256"],identity_bridge_sha256=row["identity_bridge_sha256"],categories=["pass_int"],
            unavailable=[dict(target=t,state="FAILED_RETAINED",original_state="FAILED_RETAINED",reason="FICTIONAL_TARGET_FAILURE",rows=0,eligible_rows=0)
                for t in ("pass_yd","rush_rec_yd")],created_at=feed["created_at"],verified_at=row["readback_completed_at"],
            persistence_completed_at_upper_bound=row["persistence_completed_at"],readback_completed_at=row["readback_completed_at"],
            fits=0,raw_or_models_public=False,probability_policy_change=False,ranking_policy_change=False)
        actor=dict(login="NickNicky19",id=208912933)
        run=dict(id=int(RUN),repository=dict(full_name=p.common.REPOSITORY),head_repository=dict(full_name=p.common.REPOSITORY),
            head_sha=SOURCE,head_branch=policy["producer"]["source_branch"],path=".github/workflows/lab.yml",event="workflow_dispatch",run_attempt=1,
            status="completed",conclusion="success",actor=actor,triggering_actor=dict(actor),created_at="2099-10-30T22:58:00Z",
            run_started_at="2099-10-30T22:59:00Z",updated_at="2099-10-31T01:22:00Z")
        times=[("2099-10-30T23:00:00Z","2099-10-31T00:12:00Z"),("2099-10-31T01:09:00Z","2099-10-31T01:11:00Z"),("2099-10-31T01:12:00Z","2099-10-31T01:21:00Z")]
        job_list=dict(total_count=3,jobs=[dict(id=777+i,name=policy["producer"]["jobs"][role],run_id=int(RUN),run_attempt=1,
            head_sha=SOURCE,status="completed",conclusion="success",started_at=times[i][0],completed_at=times[i][1]) for i,role in enumerate(("produce","restore","consume"))])
        board=dict(season=2099,week=8,generated_at="2099-10-31T01:25:00Z",picks=dict(over=[],under=[]),
            games=[dict(id="123456789",home="AAA",away="BBB",kickoff="2099-10-31T03:00Z",state="pre")],
            players=[dict(id="101",game_id="123456789",team="AAA",opp="BBB",pos="QB",props=[dict(key="pass_int",adj=8.5)])])
        q=SimpleNamespace(policy=policy,feed=feed,receipt=receipt,board=board,run=run,jobs=job_list,calls=[])
        return q


    def seal(q):
        f=q.feed;r=q.receipt
        f["catalog_sha256"]=h(f["catalog"]);f["source_registry_sha256"]=h(f["source_registry"])
        for row in f["rows"]:row["source_registry_sha256"]=f["source_registry_sha256"]
        r.update(catalog_sha256=f["catalog_sha256"],source_registry_sha256=f["source_registry_sha256"])
        r["owner_export_receipt_sha256"]=h({k:v for k,v in r.items() if k not in {"owner_export_receipt_sha256","feed_sha256","feed_bytes","rows"}})
        f["owner_export_receipt_sha256"]=r["owner_export_receipt_sha256"]
        body=p.canonical(f);r.update(feed_sha256=p.sha(body),feed_bytes=len(body),rows=len(f["rows"]))
        encoded=gzip.compress(p.canonical(r),mtime=0)
        stamp=p.clock(f["created_at"]).strftime("%Y%m%dT%H%M%S.%fZ")
        folder="state/"+p.PREFIX+"/2099-W08";name=stamp+"--"+p.sha(body)+".json"
        listing="https://api.github.com/repos/"+p.common.REPOSITORY+"/contents/"+folder+"?ref=lab-state"
        raw="https://raw.githubusercontent.com/"+p.common.REPOSITORY+"/lab-state/"
        routes={listing:p.canonical([dict(name=name,type="file",path=folder+"/"+name,download_url="https://provider.invalid/NEVER_USED")]),
            raw+folder+"/"+name:body,raw+"state/"+p.PREFIX+"/receipts/"+p.sha(body)+".json.gz":encoded,
            API:p.canonical(q.run),API+"/jobs?per_page=100&page=1":p.canonical(q.jobs)}
        q.body=body;q.encoded=encoded;q.routes=routes;q.listing=listing
        def fetch(url,cap):
            q.calls.append((url,cap));return q.routes[url]
        q.fetch=fetch
        return q


    def local(q,tmp_path):
        q.root=tmp_path
        q.policy_path=tmp_path/"config/point-policy.json";q.policy_path.parent.mkdir(parents=True)
        q.policy_path.write_bytes(p.canonical(q.policy));q.policy_sha=p.sha(q.policy_path.read_bytes())
        atomic_json(tmp_path/"output/data/week.json",q.board)
        q.originals={"output/data/weekly-mae-display.json":b'FICTIONAL_INCUMBENT_POINTER',
            "output/data/weekly-mae-display/"+"0"*64+".json":b'FICTIONAL_IMMUTABLE_INCUMBENT',
            "output/data/weekly-selected-rankings.json":b'FICTIONAL_INCUMBENT_RANKINGS',
            "output/data/original-public-receipt.json":b'FICTIONAL_ORIGINAL_RECEIPT'}
        for name,body in q.originals.items():
            target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
        q.board_bytes=(tmp_path/"output/data/week.json").read_bytes()
        return q


    def publish(q,**kwargs):
        return p.publish(q.root,q.policy_path,q.policy_sha,website_source_sha=WEBSITE,now=kwargs.pop("now",NOW),fetch=kwargs.pop("fetch",q.fetch),**kwargs)


    def preserved(q,*,pointer=True):
        for name,body in q.originals.items():
            if pointer or not name.endswith("weekly-mae-display.json"):assert (q.root/name).read_bytes()==body


    def test_real_publisher_unchanged_native_body_six_field_board_pointer_five_gets(tmp_path):
        q=local(seal(publisher_fixture()),tmp_path);result=publish(q)
        assert result["state"]=="POINT_DISPLAY_PERSISTED",result
        pointer=json.loads((tmp_path/"output/data/weekly-mae-display.json").read_bytes())
        assert set(pointer)==p.POINTER_KEYS and pointer["schema_version"]==p.POINTER
        assert pointer["display_board_sha256"]==p.sha(q.board_bytes) and pointer["bytes"]==len(q.body)
        assert (tmp_path/"output"/pointer["path"]).read_bytes()==q.body
        assert pointer["sha256"]==p.sha(q.body) and result["public_GETs"]==5 and result["GHA_metadata_GETs"]==2
        assert len(q.calls)==5 and sum('/actions/runs/' in url for url,_ in q.calls)==2
        assert all('provider.invalid' not in url for url,_ in q.calls)
        assert (tmp_path/"output/data/week.json").read_bytes()==q.board_bytes;preserved(q,pointer=False)
        audit=list((tmp_path/"data/weekly-mae-display-audit").glob("*.json"));assert len(audit)==1
        assert len(audit[0].read_bytes())<32<<10 and b'fictional-canonical-player' not in audit[0].read_bytes()


    @pytest.mark.parametrize("fault",["unregistered","source_unknown","recipe_rule","weights","base_procedure","roles","source_policy","profile_registration","helper_inventory","caller_PASS"])
    def test_unknown_or_unregistered_recipes_and_resealed_model_mutations_keep_incumbent(tmp_path,fault):
        q=publisher_fixture()
        if fault=="unregistered":q.policy=p.template()
        elif fault=="source_unknown":q.policy["producer"]["source_sha"]=None
        elif fault=="recipe_rule":q.policy["registered_recipe"]["rule"]="TRUST_CALLER_PASS";q.policy["registered_recipe_sha256"]=h(q.policy["registered_recipe"])
        elif fault in {"weights","base_procedure"}:
            field="model_bytes_sha256" if fault=="weights" else "base_procedure_version"
            q.feed["catalog"]["entries"][0][field]="f"*64;q.feed["rows"][0][field]="f"*64
        elif fault=="roles":
            q.feed["catalog"]["entries"][0]["public_roles"]=["RB"];q.feed["rows"][0].update(public_roles=["RB"],position="RB")
            q.feed["source_registry"]["records"][0]["public_roles"]=["RB"]
        elif fault=="source_policy":q.receipt["source_policy_sha256"]="f"*64
        elif fault=="profile_registration":q.receipt["profile_registration_sha256"]="f"*64
        elif fault=="helper_inventory":q.receipt["helper_inventory_sha256"]="f"*64
        else:q.receipt["state"]="PASS"
        local(seal(q),tmp_path);result=publish(q)
        assert result["state"]=="INCUMBENT_FALLBACK",result;preserved(q)
        assert not list((tmp_path/"output/data/weekly-mae-display").glob(p.sha(q.body)+".json"))


    @pytest.mark.parametrize("fault",["source","branch","workflow","actor","trigger","run_attempt","in_progress","job_attempt","job_id","job_name","job_failure","job_order","updated_future","persist_deadline","readback_before_export","created_after_export"])
    def test_actual_native_metadata_identity_status_clock_and_race_controls(tmp_path,fault):
        q=publisher_fixture()
        if fault=="source":q.run["head_sha"]="a"*40
        elif fault=="branch":q.run["head_branch"]="unregistered"
        elif fault=="workflow":q.run["path"]=".github/workflows/unrelated.yml"
        elif fault=="actor":q.run["actor"]["login"]="stranger"
        elif fault=="trigger":q.run["triggering_actor"]["id"]=1
        elif fault=="run_attempt":q.run["run_attempt"]=2
        elif fault=="in_progress":q.run["status"]="in_progress";q.run["conclusion"]=None
        elif fault=="job_attempt":q.jobs["jobs"][2]["run_attempt"]=2
        elif fault=="job_id":q.jobs["jobs"][2]["id"]=999
        elif fault=="job_name":q.jobs["jobs"][2]["name"]="generic-unrelated-lab"
        elif fault=="job_failure":q.jobs["jobs"][1]["conclusion"]="failure"
        elif fault=="job_order":q.jobs["jobs"][1]["started_at"]="2099-10-31T00:11:00Z"
        elif fault=="updated_future":q.run["updated_at"]="2099-10-31T01:31:00Z"
        elif fault=="persist_deadline":
            q.jobs["jobs"][0]["completed_at"]="2099-10-31T01:00:00Z"
            q.receipt["persistence_completed_at_upper_bound"]="2099-10-31T01:00:00Z";q.feed["rows"][0]["persistence_completed_at"]="2099-10-31T01:00:00Z"
        elif fault=="readback_before_export":q.receipt.update(readback_completed_at="2099-10-31T01:11:00Z",verified_at="2099-10-31T01:11:00Z");q.feed["rows"][0]["readback_completed_at"]="2099-10-31T01:11:00Z"
        else:q.jobs["jobs"][2]["completed_at"]="2099-10-31T01:19:59Z"
        local(seal(q),tmp_path);result=publish(q)
        assert result["state"]=="INCUMBENT_FALLBACK",result;preserved(q)
        assert len(q.calls)<=5


    @pytest.mark.parametrize("fault",["missing","directory_format","receipt_gzip","receipt_extra_member","receipt_hash","unknown_feed","unknown_receipt_field","extra_source","feed_hash","duplicate_json"])
    def test_missing_unknown_formats_and_strict_pair_hashes_preserve_all_originals(tmp_path,fault):
        q=local(seal(publisher_fixture()),tmp_path)
        receipt_url=next(u for u in q.routes if '/receipts/' in u)
        feed_url=next(u for u in q.routes if '/2099-W08/' in u and u.startswith('https://raw.'))
        if fault=="missing":q.routes.pop(q.listing)
        elif fault=="directory_format":q.routes[q.listing]=p.canonical([dict(name="latest.json",type="file",path="anything")])
        elif fault=="receipt_gzip":q.routes[receipt_url]=b'{"PASS":true}'
        elif fault=="receipt_extra_member":q.routes[receipt_url]+=gzip.compress(b'',mtime=0)
        elif fault=="receipt_hash":
            r=deepcopy(q.receipt);r["owner_export_receipt_sha256"]="f"*64;q.routes[receipt_url]=gzip.compress(p.canonical(r),mtime=0)
        elif fault=="unknown_feed":
            q.feed["schema_version"]="weekly-derived-selected-feed-v1";seal(q)
        elif fault=="unknown_receipt_field":q.receipt["private_raw"]="/private/provider/SECRET";seal(q)
        elif fault=="extra_source":q.feed["source_registry"]["records"].append(dict(q.feed["source_registry"]["records"][0],query_projection_sha256="f"*64));seal(q)
        elif fault=="feed_hash":q.routes[feed_url]+=b'\n'
        else:q.routes[q.listing]=b'[{"name":"x","name":"y"}]'
        result=publish(q)
        assert result["state"]=="INCUMBENT_FALLBACK",result;preserved(q)
        assert 'SECRET' not in json.dumps(result) and '/private/' not in json.dumps(result)


    @pytest.mark.parametrize("fault",["week","team","opponent","position","kickoff_microsecond","missing_player","duplicate_player","duplicate_game"])
    def test_exact_actual_board_membership_controls(tmp_path,fault):
        q=publisher_fixture()
        if fault=="week":q.board["week"]=9
        elif fault=="team":q.board["players"][0]["team"]="OTHER"
        elif fault=="opponent":q.board["players"][0]["opp"]="OTHER"
        elif fault=="position":q.board["players"][0]["pos"]="RB"
        elif fault=="kickoff_microsecond":q.board["games"][0]["kickoff"]="2099-10-31T03:00:00.000001Z"
        elif fault=="missing_player":q.board["players"][0]["id"]="999"
        elif fault=="duplicate_player":q.board["players"].append(deepcopy(q.board["players"][0]))
        else:q.board["games"].append(deepcopy(q.board["games"][0]))
        local(seal(q),tmp_path);result=publish(q)
        assert result["state"]=="INCUMBENT_FALLBACK",result;preserved(q)


    def test_bot_and_exact_numeric_board_ids_and_frozen_original_clocks(tmp_path):
        q=publisher_fixture();q.run["actor"]=q.run["triggering_actor"]=dict(login="github-actions[bot]",id=41898282)
        q.board["players"][0].update(id=101,game_id=123456789);q.board["games"][0].update(id=123456789,state="post")
        local(seal(q),tmp_path);result=publish(q,now="2099-10-31T04:00:00Z")
        assert result["state"]=="POINT_DISPLAY_PERSISTED",result
        assert (tmp_path/"output/data/weekly-mae-display"/(p.sha(q.body)+".json")).read_bytes()==q.body
        original=json.loads(q.body)["rows"][0]
        assert original["issued_at"]=="2099-10-31T00:08:00Z" and original["persistence_completed_at"]=="2099-10-31T00:12:00Z"


    @pytest.mark.parametrize("stage",["metadata","asset","audit","pointer"])
    def test_board_races_never_rebind_old_data_to_a_changed_board(tmp_path,stage):
        q=local(seal(publisher_fixture()),tmp_path);changed=deepcopy(q.board);changed["generated_at"]="2099-10-31T01:29:59Z"
        def atomic(path,value):
            atomic_json(path,value)
            if stage=="asset" and path.parent.name=="weekly-mae-display" or stage=="audit" and path.parent.name=="weekly-mae-display-audit" or stage=="pointer" and path.name=="weekly-mae-display.json":
                atomic_json(tmp_path/"output/data/week.json",changed)
        def fetch(url,cap):
            result=q.fetch(url,cap)
            if stage=="metadata" and '/jobs?' in url:atomic_json(tmp_path/"output/data/week.json",changed)
            return result
        result=publish(q,fetch=fetch,atomic_json=atomic)
        assert result["state"]=="INCUMBENT_FALLBACK",result
        if stage=="pointer":
            pointer=json.loads((tmp_path/"output/data/weekly-mae-display.json").read_bytes())
            assert pointer["display_board_sha256"]!=p.sha((tmp_path/"output/data/week.json").read_bytes())
            preserved(q,pointer=False)  # UI refuses this exact old-board hash; no rollback/deletion.
        else:preserved(q)


    def test_immutable_collision_does_not_replace_incumbent(tmp_path):
        q=local(seal(publisher_fixture()),tmp_path)
        asset=tmp_path/"output/data/weekly-mae-display"/(p.sha(q.body)+".json");asset.write_bytes(b'FICTIONAL_ALREADY_RETAINED_DIFFERENT_BYTES')
        result=publish(q);assert result["reason"]=="MAE_IMMUTABLE_NATIVE_ASSET_COLLISION";preserved(q)
        assert asset.read_bytes()==b'FICTIONAL_ALREADY_RETAINED_DIFFERENT_BYTES'


    def test_policy_changed_during_audit_does_not_replace_incumbent_pointer(tmp_path):
        q=local(seal(publisher_fixture()),tmp_path)
        def atomic(path,value):
            atomic_json(path,value)
            if path.parent.name=="weekly-mae-display-audit":
                changed=deepcopy(q.policy);changed["state"]="PREPARED_UNREGISTERED";q.policy_path.write_bytes(p.canonical(changed))
        result=publish(q,atomic_json=atomic)
        assert result["state"]=="INCUMBENT_FALLBACK";preserved(q)
        assert (tmp_path/"output/data/weekly-mae-display"/(p.sha(q.body)+".json")).read_bytes()==q.body
