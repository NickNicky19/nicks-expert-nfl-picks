"""Portable fictional V2 consumer and public API checks; no actual HTTP."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import weekly_public_feed as f

NOW='2026-10-24T12:01:00Z';SOURCE='d'*40;RUN='123456789'


def fixture():
    recipe=dict(method_id='P2_SELECTED',procedure_version='a'*64,product='point_median',source_policy_sha256='e'*64)
    authority=dict(schema_version=f.AUTHORITY_V2,state='ROOT_REGISTERED',repository=f.REPOSITORY,source_sha=SOURCE,source_branch='fictional',
        workflow_path='.github/workflows/lab.yml',event='workflow_dispatch',export_job='genuine-hosted-selected-export-v1',run_attempt=1,public_ref='lab-state',
        catalog_schema=f.CATALOG_V2,catalog_freezer_sha256='f'*64,catalog_registration_rule='OWNED_SELECTED_VERSION_CATALOG_BEFORE_FEATURES_OR_VALUES')
    policy=dict(schema_version=f.POLICY_V2,state='ROOT_REGISTERED',registration_id='weekly-adaptive-release-v1',authority_kind='AUTOMATED_REGISTERED_POLICY',human_approval=False,
        public_raw_or_model_weights=False,public_ref='lab-state',publication_authority=authority,producer_policy_sha256='1'*64,source_policy_sha256='e'*64,
        rights_authorities=['2'*64],r0_identities=['3'*64],engine_sha256={n:'4'*64 for n in f.ENGINE_FILES},website_code_sha256={n:'4'*64 for n in f.CODE_FILES},
        public_fields=list(f.overlay().ROW_FIELDS),public_roles={'pass_yd':['QB']},procedures={'pass_yd':[recipe]})
    catalog=dict(schema_version=f.CATALOG_V2,rows=[dict(category='pass_yd',method_id='P2_SELECTED',procedure_version='a'*64,model_version='b'*64)],
        current_values_used=False,public_policy_registration='REQUIRED_SEPARATELY; not automatic approval')
    row=dict(player_id='fictional-player',game_id='fictional-game',category='pass_yd',method_id='P2_SELECTED',model_version='b'*64,procedure_version='a'*64,
        product='point_median',prediction_functional='intended_median',forecast_value=-2.5,horizon='player_game',source_cutoff_utc='2026-10-24T14:00:00Z',
        issued_at='2026-10-24T11:50:00Z',persistence_completed_at='2026-10-24T11:55:00Z',kickoff_utc='2026-10-25T17:00:00Z',valid_until_utc='2026-10-25T17:00:00Z',
        selection_sha256='5'*64,source_policy_sha256='e'*64,query_source_sha256='6'*64)
    board=dict(season=2026,week=7,games=[dict(id='fictional-game',kickoff=row['kickoff_utc'],state='pre')],
        players=[dict(id='fictional-player',game_id='fictional-game',team='A',opp='B',props=[dict(key='pass_yd',proj=10)])])
    publication=dict(schema_version=f.PUBLICATION_V2,authority_sha256=f.digest(authority),repository=f.REPOSITORY,source_sha=SOURCE,run_id=RUN,run_attempt=1,
        workflow_path=authority['workflow_path'],export_job=authority['export_job'],api_job_id=789,selected_body_sha256='7'*64,source_version_catalog_sha256=f.sha(f.canonical(catalog)+b'\n'),
        version_catalog_sha256=f.digest(catalog),version_catalog=catalog)
    feed=dict(schema_version=f.VERSION_V2,state='DERIVED_SELECTED_ONLY',season=2026,week=7,created_at='2026-10-24T12:00:00Z',expires_at=row['valid_until_utc'],
        producer_policy_sha256='1'*64,rights_authority_sha256='2'*64,rights_receipt_sha256='9'*64,durability_receipt_sha256='0'*64,r0_identity_sha256='3'*64,
        identity_scope_sha256=f.identity_scope([row],board),rows=[row],coverage=dict(private_selected_rows=1,public_rows=1,fallback_counts={}),
        publication=publication,publication_sha256=f.digest(publication))
    run=dict(id=int(RUN),repository={'full_name':f.REPOSITORY},head_repository={'full_name':f.REPOSITORY},head_sha=SOURCE,head_branch='fictional',path=authority['workflow_path'],
        event='workflow_dispatch',run_attempt=1,status='completed',conclusion='success',updated_at='2026-10-24T12:00:30Z')
    job=dict(id=789,name=authority['export_job'],run_id=int(RUN),head_sha=SOURCE,status='completed',conclusion='success',
        started_at='2026-10-24T11:58:00Z',completed_at='2026-10-24T12:00:20Z')
    return policy,feed,board,run,dict(total_count=1,jobs=[job])


def transport(run,jobs,calls):
    base='https://api.github.com/repos/'+f.REPOSITORY+'/actions/runs/'+RUN
    def fetch(url,cap):
        calls.append((url,cap));assert cap==1<<20
        if url==base:return f.canonical(run)
        if url==base+'/jobs?per_page=100&page=1':return f.canonical(jobs)
        raise AssertionError('unexpected URL')
    return fetch


def rehash(feed):
    feed['publication']['version_catalog_sha256']=f.digest(feed['publication']['version_catalog'])
    feed['publication']['source_version_catalog_sha256']=f.sha(f.canonical(feed['publication']['version_catalog'])+b'\n')
    feed['publication_sha256']=f.digest(feed['publication'])


class PublicationAuthorityChecks(unittest.TestCase):
    def test_closed_schema_keeps_ROW_FIELDS_and_denies_raw_or_code_approval_fields(self):
        root=Path(__file__).resolve().parents[1];schema=json.loads((root/'schemas/weekly-derived-selected-feed-v2.json').read_text())
        policy,feed,board,run,jobs=fixture()
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['properties']),set(feed))
        self.assertEqual(set(schema['required']),set(feed))
        self.assertFalse(schema['properties']['publication']['additionalProperties'])
        self.assertEqual(set(schema['properties']['publication']['properties']),set(feed['publication']))
        self.assertFalse(schema['properties']['rows']['items']['additionalProperties'])
        self.assertEqual(set(schema['properties']['rows']['items']['properties']),set(f.overlay().ROW_FIELDS))
        self.assertEqual(schema['properties']['rows'],json.loads((root/'schemas/weekly-derived-selected-feed-v1.json').read_text())['properties']['rows'])
        for section in ('publication','row'):
            changed=deepcopy(feed)
            if section=='publication':changed['publication']['code_approved']=True
            else:changed['rows'][0]['raw_inputs']=['forbidden']
            with self.subTest(section=section),self.assertRaises(f.FeedError):f.validate_feed(changed,policy,board,now=NOW,fetch=transport(run,jobs,[]))

    def test_exact_reviewed_execution_accepts_new_hash_and_signed_derived_row(self):
        policy,feed,board,run,jobs=fixture();calls=[]
        selected=f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,calls))
        self.assertEqual(selected['rows'][0]['forecast_value'],-2.5);self.assertEqual(len(calls),2)
        self.assertEqual(set(feed['rows'][0]),set(f.overlay().ROW_FIELDS))

    def test_routine_parameter_hash_update_needs_same_recipe_and_catalog_not_new_code(self):
        policy,feed,board,run,jobs=fixture();before=deepcopy(policy)
        feed['rows'][0]['model_version']='c'*64;feed['publication']['version_catalog']['rows'][0]['model_version']='c'*64;rehash(feed)
        self.assertEqual(len(f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,[]))['rows']),1)
        self.assertEqual(policy,before)

    def test_V1_literal_gate_still_rejects_unknown_model_without_API(self):
        policy,feed,board,_,_=fixture();policy['schema_version']=f.POLICY;policy['procedures']['pass_yd'][0]['model_version']='b'*64
        feed={k:v for k,v in feed.items() if k in f.META_FIELDS};feed['schema_version']=f.VERSION
        self.assertEqual(len(f.validate_feed(feed,policy,board,now=NOW)['rows']),1)
        feed['rows'][0]['model_version']='c'*64
        with self.assertRaisesRegex(f.FeedError,'PROCEDURE_NOT_REGISTERED'):f.validate_feed(feed,policy,board,now=NOW)

    def test_pending_authority_wrong_source_and_arbitrary_URL_do_not_query_API(self):
        for field,value in [('source_sha','0'*40),('run_id','123/../../evil'),('extra_url','https://evil.invalid/')]:
            policy,feed,board,run,jobs=fixture();feed['publication'][field]=value;rehash(feed);calls=[]
            with self.subTest(field=field),self.assertRaises(Exception):f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,calls))
            self.assertEqual(calls,[])
        policy,feed,board,run,jobs=fixture();policy['publication_authority']['state']='PREPARED'
        with self.assertRaises(f.FeedError):f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,[]))

    def test_wrong_run_repository_head_workflow_event_attempt_status_and_conclusion_fail(self):
        for field,value in [('repository',{'full_name':'foreign/repo'}),('head_repository',{'full_name':'foreign/repo'}),('head_sha','0'*40),
                ('head_branch','foreign'),('path','.github/workflows/evil.yml'),('event','pull_request'),('run_attempt',2),('status','in_progress'),('conclusion','failure')]:
            policy,feed,board,run,jobs=fixture();run[field]=value;calls=[]
            with self.subTest(field=field),self.assertRaises(f.FeedError):f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,calls))
            self.assertEqual(len(calls),1)

    def test_job_must_be_unique_complete_exact_source_and_export_identity(self):
        for field,value in [('id',999),('head_sha','0'*40),('run_id',999),('status','in_progress'),('conclusion','failure'),('completed_at','2026-10-24T11:59:59Z')]:
            policy,feed,board,run,jobs=fixture();jobs['jobs'][0][field]=value
            with self.subTest(field=field),self.assertRaises(f.FeedError):f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,[]))
        for kind in ('duplicate','incomplete'):
            policy,feed,board,run,jobs=fixture()
            if kind=='duplicate':jobs['jobs'].append(deepcopy(jobs['jobs'][0]));jobs['total_count']=2
            else:jobs['total_count']=101
            with self.subTest(kind=kind),self.assertRaises(f.FeedError):f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,[]))

    def test_unregistered_procedure_product_source_or_unfrozen_catalog_fails(self):
        for kind in ('procedure','product','source','current'):
            policy,feed,board,run,jobs=fixture()
            if kind=='procedure':feed['publication']['version_catalog']['rows'][0]['procedure_version']='0'*64
            elif kind=='product':policy['procedures']['pass_yd'][0]['product']='point_mean'
            elif kind=='source':policy['procedures']['pass_yd'][0]['source_policy_sha256']='0'*64
            else:feed['publication']['version_catalog']['current_values_used']=True
            rehash(feed)
            with self.subTest(kind=kind),self.assertRaises(f.FeedError):f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,[]))

    def test_catalog_hashes_duplicates_unknown_fields_and_unlisted_version_fail(self):
        for kind in ('digest','physical','duplicate','extra','version'):
            policy,feed,board,run,jobs=fixture()
            if kind=='digest':feed['publication']['version_catalog_sha256']='0'*64;feed['publication_sha256']=f.digest(feed['publication'])
            elif kind=='physical':feed['publication']['source_version_catalog_sha256']='0'*64;feed['publication_sha256']=f.digest(feed['publication'])
            elif kind=='duplicate':feed['publication']['version_catalog']['rows']*=2;rehash(feed)
            elif kind=='extra':feed['publication']['version_catalog']['raw_source']='forbidden';rehash(feed)
            else:feed['rows'][0]['model_version']='c'*64
            with self.subTest(kind=kind),self.assertRaises(f.FeedError):f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,[]))

    def test_metadata_overflow_duplicate_JSON_and_unavailable_HTTP_have_no_retry(self):
        policy,feed,board,run,jobs=fixture()
        for body in (b'x'*((1<<20)+1),b'{"id":1,"id":2}'):
            calls=[]
            def fetch(url,cap):calls.append(url);return body
            with self.assertRaises(Exception):f.validate_feed(feed,policy,board,now=NOW,fetch=fetch)
            self.assertEqual(len(calls),1)
        calls=[]
        def unavailable(url,cap):calls.append(url);raise f.FeedError('PUBLIC_FEED_UNAVAILABLE')
        with patch.object(f,'code_review',return_value='a'*64):
            selected,review,receipt=f.writer_input('.',policy,board,website_source_sha=SOURCE,now=NOW,feed=feed,fetch=unavailable)
        self.assertEqual((selected,review),({},{}));self.assertEqual(receipt['state'],'R0_FALLBACK');self.assertEqual(len(calls),1)

    def test_existing_directory_and_raw_plus_only_two_fixed_API_GETs(self):
        policy,feed,board,run,jobs=fixture();body=f.canonical(feed);stamp=f.utc(feed['created_at']).strftime('%Y%m%dT%H%M%S.%fZ')
        name=stamp+'--'+f.sha(body)+'.json';path='state/public/weekly-adaptive-v1/2026-W07/'+name;calls=[];api=transport(run,jobs,[])
        def fetch(url,cap):
            calls.append(url)
            if '/contents/' in url:return f.canonical([dict(name=name,path=path,type='file',download_url='https://evil.invalid/ignored')])
            if url=='https://raw.githubusercontent.com/'+f.REPOSITORY+'/lab-state/'+path:return body
            return api(url,cap)
        with patch.object(f,'code_review',return_value='a'*64):
            selected,review,receipt=f.writer_input('.',policy,board,website_source_sha=SOURCE,now=NOW,fetch=fetch)
        self.assertEqual(len(calls),4);self.assertEqual(len(selected['rows']),1);self.assertFalse(review['human_approval'])
        self.assertEqual(receipt['publication_execution']['API_GETs'],2);self.assertNotIn('https://evil.invalid/',calls)

    def test_deadline_never_extends_existing_optional_timeout(self):
        with patch.object(f.signal,'getitimer',return_value=(2.,0.)),patch.object(f.signal,'getsignal'),patch.object(f.signal,'signal'),\
                patch.object(f.signal,'setitimer') as timer,patch.object(f.time,'monotonic',side_effect=[10.,10.25]):
            with f.publication_deadline(20):pass
        self.assertEqual(timer.call_args_list[0].args,(f.signal.ITIMER_REAL,2.))
        self.assertEqual(timer.call_args_list[-1].args,(f.signal.ITIMER_REAL,1.75))

    def test_V2_direct_member_and_manual_ROOT_acceptance_cannot_bypass_live_gate(self):
        policy,feed,board,_,_=fixture()
        with self.assertRaisesRegex(f.FeedError,'VERIFIED_ISSUED_CATALOG'):f.member(policy,feed['rows'][0])
        with self.assertRaisesRegex(f.FeedError,'LIVE_DURABILITY'):f.private_gates({},policy,now=NOW)

    def test_exporter_identity_comes_from_actual_accepted_job_and_exact_catalog_bytes(self):
        policy,feed,board,_,_=fixture();catalog_body=f.canonical(feed['publication']['version_catalog'])+b'\n'
        bundle=dict(terminal=dict(schema_version='weekly-generic-future-producer-v1',selected_version_catalog={'sha256':f.sha(catalog_body),'bytes':len(catalog_body)}),
            completion={'binding':{'sha256':'7'*64}})
        exporter=dict(execution_lane='github_actions',repository=f.REPOSITORY,source_sha=SOURCE,job_id=policy['publication_authority']['export_job'],run_id=RUN,run_attempt=1,permission='write',api_job_id=789,
            workflow_ref=f.REPOSITORY+'/.github/workflows/lab.yml@refs/heads/fictional')
        accepted=dict(authority_kind='ROOT_APPROVED_PROCEDURE_VERIFIED',exporter=exporter)
        original={k:v for k,v in feed.items() if k in f.META_FIELDS};original['schema_version']=f.VERSION
        with patch.object(f,'private_gates',return_value=(f.utc(NOW),accepted)),patch.object(f,'export_rows',return_value=original):
            result=f.export_rows_v2([],bundle,policy,board,now=NOW,durable_acceptance=object(),version_catalog_body=catalog_body)
            self.assertEqual(result['publication']['source_version_catalog_sha256'],f.sha(catalog_body))
            with self.assertRaisesRegex(f.FeedError,'EXACT_OWNED'):f.export_rows_v2([],bundle,policy,board,now=NOW,durable_acceptance=object(),version_catalog_body=catalog_body+b' ')
            accepted['exporter']=None
            with self.assertRaisesRegex(f.FeedError,'ACTUAL_VERIFIED'):f.export_rows_v2([],bundle,policy,board,now=NOW,durable_acceptance=object(),version_catalog_body=catalog_body)


class CurrentStaticPortChecks(unittest.TestCase):
    """Invented policy metadata against closed actual source-code bytes only."""
    def metadata(self):
        import check_weekly_consumer_v3_static as checker
        policy, _, _, _, _ = fixture()
        actual = {name: f.sha((ROOT/name).read_bytes()) for name in f.CODE_FILES}
        policy['website_code_sha256'] = actual
        policy['engine_sha256'] = {name: actual[name] for name in f.ENGINE_FILES}
        body = f.canonical(policy)
        original = (ROOT/'.github/workflows/hourly.yml').read_text()
        import re
        hourly, count = re.subn(r'(--feed-policy-sha256 )[a-f0-9]{64}', lambda match: match[1]+f.sha(body), original)
        self.assertEqual(count, 1)
        hourly = hourly.encode()
        pins = dict(policy_path='config/weekly-derived-selected-policy-v2.json',
            physical_sha256=dict(policy=f.sha(body), helper=f.sha((ROOT/'tools/weekly_public_feed.py').read_bytes()),
                schema=f.sha((ROOT/'schemas/weekly-derived-selected-feed-v2.json').read_bytes()), hourly=f.sha(hourly)),
            code_paths=sorted(f.CODE_FILES), new_lab_source_sha=SOURCE,
            new_producer_policy_sha256=policy['producer_policy_sha256'], new_source_policy_sha256=policy['source_policy_sha256'],
            new_catalog_freezer_sha256=policy['publication_authority']['catalog_freezer_sha256'],
            new_procedures=deepcopy(policy['procedures']), new_app_sha256=actual['output/app.js'])
        return checker, pins, dict(policy=body, hourly=hourly)

    def test_new_exact_metadata_is_proposed_only_without_installed_policy(self):
        checker, pins, bodies = self.metadata()
        result = checker.check_current_port(ROOT, pins, bodies)
        self.assertEqual(result['state'], 'PROPOSED_STATIC_CONTRACT_PASS')
        self.assertFalse(result['installed_port_acceptance'])
        self.assertFalse(result['historical_reports_used'])
        self.assertFalse(result['hosted_publication_or_deployment_acceptance'])
        self.assertEqual(result['website_code_inventory_checks'], 14)
        self.assertIn('tools/weekly_selected_rankings.py', f.CODE_FILES)
        self.assertEqual(result['HTTP'], 0)
        self.assertEqual(result['model_or_data_reads'], 0)

    def test_physical_policy_mismatch_rejects_before_semantics(self):
        checker, pins, bodies = self.metadata(); pins['physical_sha256']['policy'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'NEW_EXACT_PHYSICAL_BYTES_REQUIRED'):
            checker.check_current_port(ROOT, pins, bodies)

    def test_root_new_source_binding_cannot_inherit_old_success(self):
        checker, pins, bodies = self.metadata(); pins['new_lab_source_sha'] = '0'*40
        with self.assertRaisesRegex(ValueError, 'NEW_SOURCE'):
            checker.check_current_port(ROOT, pins, bodies)

    def test_workflow_needs_exact_physical_policy_pin(self):
        checker, pins, bodies = self.metadata()
        bodies['hourly'] = bodies['hourly'].replace(pins['physical_sha256']['policy'].encode(), b'0'*64)
        pins['physical_sha256']['hourly'] = f.sha(bodies['hourly'])
        with self.assertRaisesRegex(ValueError, 'WORKFLOW_PHYSICAL_POLICY_SHA'):
            checker.check_current_port(ROOT, pins, bodies)

    def test_duplicate_policy_JSON_rejects_without_old_report_lookup(self):
        checker, pins, bodies = self.metadata(); bodies['policy'] = b'{"x":1,"x":2}'
        pins['physical_sha256']['policy'] = f.sha(bodies['policy'])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_JSON_KEY'):
            checker.check_current_port(ROOT, pins, bodies)

    def test_new_UI_and_procedure_pins_are_independent_requirements(self):
        checker, pins, bodies = self.metadata(); pins['new_app_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'NEW_UI'):
            checker.check_current_port(ROOT, pins, bodies)
        checker, pins, bodies = self.metadata(); pins['new_procedures'] = {}
        with self.assertRaisesRegex(ValueError, 'NEW_RECIPES'):
            checker.check_current_port(ROOT, pins, bodies)

    def test_schema_physical_mismatch_does_not_reuse_an_earlier_receipt(self):
        checker, pins, bodies = self.metadata(); pins['physical_sha256']['schema'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'NEW_EXACT_PHYSICAL_BYTES_REQUIRED'):
            checker.check_current_port(ROOT, pins, bodies)


if __name__=='__main__':unittest.main()
