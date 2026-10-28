"""Fictional V2-wire/new-authority cases against actual V4 and old consumers."""
from copy import deepcopy
from contextlib import contextmanager
import ast
import gzip
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import weekly_public_feed as f
import weekly_public_feed_v4 as v4

NOW='2026-10-25T12:00:30Z'
LAB='d'*40
RUN='123456789'
HEAD=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
API='https://api.github.com/repos/'+f.REPOSITORY+'/actions/runs/'+RUN
FIXTURES={}


def fixture(tag='one'):
    p=v4.template(ROOT)
    recipe=f.digest('fictional ROOT registered recipe')
    p.update(state='ROOT_REGISTERED',registered_at_utc='2026-10-25T12:00:25Z',lab_recipe_registered_at_utc='2026-10-25T09:00:00Z',
        lab_public_policy_sha256=f.digest('fictional exact before-values lab policy'),
        recipe_registration_sha256=recipe,producer_policy_sha256=recipe,workflow_sha256=f.digest('fictional fixed workflow'),
        jobs=dict(produce='fictional-weekly-produce',restore='fictional-weekly-restore',consume='fictional-weekly-export'))
    p['publication_authority'].update(state='ROOT_REGISTERED',source_sha=LAB,source_branch='research/fictional-weekly',
        export_job=p['jobs']['consume'],catalog_freezer_sha256=f.digest('fictional reviewed epoch projection source'),
        recipe_registration_sha256=recipe)
    rows=[];players=[]
    for category in p['expected_categories']:
        pos=p['public_roles'][category][0]
        pid='fictional-'+category
        product,functional=f.overlay().PRODUCTS[category]
        rows.append(dict(player_id=pid,game_id='fictional-game',category=category,method_id='P2_SELECTED',
            model_version=f.digest([tag,category,'model']),procedure_version=f.digest([tag,category,'procedure']),
            product=product,prediction_functional=functional,forecast_value=0,
            horizon='player_game',source_cutoff_utc='2026-10-25T14:00:00Z',issued_at='2026-10-25T10:00:00Z',
            persistence_completed_at='2026-10-25T11:55:00Z',kickoff_utc='2026-10-26T17:00:00Z',valid_until_utc='2026-10-26T17:00:00Z',
            selection_sha256=f.digest(['fictional-selection',category]),source_policy_sha256=p['source_policy_sha256'],
            query_source_sha256=f.digest(['fictional-query',category])))
        players.append(dict(id=pid,game_id='fictional-game',team='AAA',opp='BBB',pos=pos,props=[dict(key=category,proj=10)]))
    board=dict(season=2026,week=7,execution_model=p['current_execution'],
        games=[dict(id='fictional-game',kickoff='2026-10-26T17:00:00Z',state='pre')],players=players)
    catalog=dict(schema_version=f.CATALOG_V2,current_values_used=False,
        public_policy_registration='REQUIRED_SEPARATELY; not automatic approval',
        rows=[{k:r[k]for k in v4.CATALOG_ROW_KEYS}for r in rows])
    # This is the publisher's existing unchanged metadata API, also called by
    # audit_weekly_public_v1.export. No private JSONL/native body is constructed.
    exporter=dict(execution_lane='github_actions',repository=f.REPOSITORY,source_sha=LAB,job_id=p['jobs']['consume'],
        run_attempt=1,permission='write',api_job_id=789,run_id=RUN,
        workflow_ref=f.REPOSITORY+'/.github/workflows/lab.yml@refs/heads/research/fictional-weekly')
    publication=f.publication_metadata_v2(p,dict(authority_kind='ROOT_APPROVED_PROCEDURE_VERIFIED',exporter=exporter),
        dict(completion=dict(binding=dict(sha256=f.digest('fictional selected source')))),catalog,f.canonical(catalog)+b'\n')
    feed=dict(schema_version=f.VERSION_V2,state='DERIVED_SELECTED_ONLY',season=2026,week=7,created_at='2026-10-25T12:00:00Z',
        expires_at=rows[0]['valid_until_utc'],producer_policy_sha256=recipe,rights_authority_sha256=p['rights_authorities'][0],
        rights_receipt_sha256=f.digest('fictional rights receipt'),durability_receipt_sha256=f.digest('fictional full live acceptance'),
        r0_identity_sha256=p['r0_identities'][0],identity_scope_sha256=f.identity_scope(rows,board),rows=rows,
        coverage=dict(private_selected_rows=11,public_rows=11,fallback_counts={}),
        publication=publication,publication_sha256=f.digest(publication))
    run=dict(id=int(RUN),repository=dict(full_name=f.REPOSITORY),head_repository=dict(full_name=f.REPOSITORY),
        head_sha=LAB,head_branch=p['publication_authority']['source_branch'],path='.github/workflows/lab.yml',
        event='workflow_dispatch',run_attempt=1,status='completed',conclusion='success',updated_at='2026-10-25T12:00:25Z')
    times=[('09:00:00','11:56:00'),('11:56:01','11:58:00'),('11:58:01','12:00:20')]
    jobs=dict(total_count=3,jobs=[dict(id=787+i,name=p['jobs'][role],run_id=int(RUN),head_sha=LAB,status='completed',conclusion='success',
        started_at='2026-10-25T'+times[i][0]+'Z',completed_at='2026-10-25T'+times[i][1]+'Z')
        for i,role in enumerate(('produce','restore','consume'))])
    FIXTURES[id(run)]=(p,feed)
    return p,feed,board,run,jobs


def rehash(feed):
    pub=feed['publication'];pub['version_catalog_sha256']=f.digest(pub['version_catalog'])
    pub['source_version_catalog_sha256']=f.sha(f.canonical(pub['version_catalog'])+b'\n')
    feed['publication_sha256']=f.digest(pub)


def receipt_fixture(p,feed,jobs):
    r=dict(schema_version=v4.RECEIPT_SCHEMA,source_sha=LAB,run_id=RUN,root_go_sha256=f.digest('fictional root'),
        policy_sha256=p['lab_public_policy_sha256'],policy_registered_at_utc='2026-10-25T09:00:01Z',
        workflow_sha256=p['workflow_sha256'],recipe_registration_sha256=p['recipe_registration_sha256'],
        rights_authority_sha256=feed['rights_authority_sha256'],r0_identity_sha256=feed['r0_identity_sha256'],
        origin_choice_sha256=f.digest('fictional original choice'),feed_sha256=f.sha(f.canonical(feed)),feed_bytes=len(f.canonical(feed)),
        rows=len(feed['rows']),categories=sorted({r['category']for r in feed['rows']}),
        jobs={role:dict(job_id=p['jobs'][role],api_job_id=j['id']) for role,j in zip(('produce','restore','consume'),jobs['jobs'])},
        created_at=feed['created_at'],verified_at='2026-10-25T11:59:59Z',fits=0,raw_or_models_public=False)
    r.update({k:f.digest('fictional '+k)for k in v4.DISCOVERY_HASH_KEYS})
    return r


def transport(run,jobs,calls,final=None,receipt_change=None,raw_receipt=None):
    reads=0
    def fetch(url,cap):
        nonlocal reads
        calls.append((url,cap))
        p,feed=FIXTURES[id(run)]
        expected='https://raw.githubusercontent.com/'+f.REPOSITORY+'/lab-state/state/public/weekly-adaptive-v1/receipts/'+f.sha(f.canonical(feed))+'.json.gz'
        if url==expected:
            assert cap==64<<10
            if raw_receipt is not None:return raw_receipt
            receipt=receipt_fixture(p,feed,jobs)
            if receipt_change:receipt_change(receipt)
            return gzip.compress(f.canonical(receipt),mtime=0)
        assert cap==1<<20
        if url==API:
            reads+=1
            return f.canonical(final if final is not None and reads>1 else run)
        if url==API+'/jobs?per_page=100&page=1':return f.canonical(jobs)
        raise AssertionError('UNREGISTERED_METADATA_URL')
    return fetch


class V4ConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network=patch.object(socket.socket,'connect',side_effect=AssertionError('REAL_NETWORK_FORBIDDEN'))
        cls.network.start()
    @classmethod
    def tearDownClass(cls):cls.network.stop()

    def validate(self,p,feed,board,run,jobs,**kwargs):
        calls=[];result=v4.validate_feed(feed,p,board,root=ROOT,now=NOW,fetch=transport(run,jobs,calls,**kwargs))
        return result,calls

    def test_actual_v2_wire_all_eleven_known_zero_values_and_three_roles(self):
        p,feed,board,run,jobs=fixture();(selected,proof),calls=self.validate(p,feed,board,run,jobs)
        self.assertEqual(len(selected['rows']),11);self.assertTrue(all(r['forecast_value']==0 for r in selected['rows']))
        self.assertEqual(proof['API_GETs'],3);self.assertEqual(proof['public_receipt_GETs'],1);self.assertEqual(len(calls),4)
        self.assertTrue(proof['receipt_policy_and_workflow_checked'])
        self.assertEqual(set(proof['registered_jobs']),{'produce','restore','consume'})
        self.assertEqual(set(feed),f.META_FIELDS|{'publication','publication_sha256'})

    def expired_offer_case(self):
        p,feed,board,run,jobs=fixture()
        future='fictional-future-game'
        board['games'].append(dict(id=future,kickoff='2026-10-27T17:00:00Z',state='pre'))
        for row in feed['rows']:
            if row['category']=='rush_att':
                row.update(game_id=future,kickoff_utc='2026-10-27T17:00:00Z',valid_until_utc='2026-10-27T17:00:00Z')
                next(player for player in board['players'] if player['id']==row['player_id'])['game_id']=future
        feed['expires_at']='2026-10-27T17:00:00Z'
        feed['identity_scope_sha256']=f.identity_scope(feed['rows'],board)
        next(player for player in board['players'] if player['id']=='fictional-rec')['props']=[]
        return p,feed,board,run,jobs

    def test_expired_missing_offer_does_not_discard_authentic_future_rows(self):
        p,feed,board,run,jobs=self.expired_offer_case()
        selected,_=v4.validate_feed(feed,p,board,root=ROOT,now='2026-10-26T18:00:00Z',
                                  fetch=transport(run,jobs,[]))
        self.assertEqual([row['category'] for row in selected['rows']],['rush_att'])
        self.assertEqual(len(feed['rows']),11)

    def test_expired_rows_still_require_valid_original_values_and_identity(self):
        for kind in ('negative_count','missing_player','changed_team','active_missing_offer'):
            with self.subTest(kind=kind):
                p,feed,board,run,jobs=self.expired_offer_case()
                rec=next(row for row in feed['rows'] if row['category']=='rec')
                if kind=='negative_count':rec['forecast_value']=-1
                elif kind=='missing_player':board['players']=[player for player in board['players'] if player['id']!=rec['player_id']]
                elif kind=='changed_team':next(player for player in board['players'] if player['id']==rec['player_id'])['team']='OTHER'
                else:next(player for player in board['players'] if player['id']=='fictional-rush_att')['props']=[]
                with self.assertRaises((ValueError,KeyError)):
                    v4.validate_feed(feed,p,board,root=ROOT,now='2026-10-26T18:00:00Z',
                                     fetch=transport(run,jobs,[]))

    def test_weekly_model_and_procedure_versions_change_under_same_registered_recipe(self):
        results=[]
        for tag in ('first','next'):
            p,feed,board,run,jobs=fixture(tag);(selected,_),_=self.validate(p,feed,board,run,jobs)
            results.append((p['recipe_registration_sha256'],selected['rows'][0]['model_version'],selected['rows'][0]['procedure_version']))
        self.assertEqual(results[0][0],results[1][0]);self.assertNotEqual(results[0][1:],results[1][1:])

    def test_first_website_install_after_genuine_feed_keeps_both_actual_clocks(self):
        p,feed,board,run,jobs=fixture()
        self.assertGreater(f.utc(p['registered_at_utc']),f.utc(feed['created_at']))
        self.assertGreater(f.utc(p['registered_at_utc']),f.utc(feed['rows'][0]['issued_at']))
        self.assertLess(f.utc(p['lab_recipe_registered_at_utc']),f.utc(feed['rows'][0]['issued_at']))
        (selected,_),_=self.validate(p,feed,board,run,jobs)
        self.assertEqual(len(selected['rows']),11)

    def test_exact_static_public_policy_receipt_and_workflow_hash_are_required(self):
        for key,value in [('policy_sha256','0'*64),('workflow_sha256','0'*64),('recipe_registration_sha256','0'*64),
            ('source_sha','0'*40),('run_id','9'),('feed_sha256','0'*64),('feed_bytes',1),('rows',1),
            ('categories',[]),('fits',False),('raw_or_models_public',True),('policy_registered_at_utc','2026-10-25T10:01:00Z'),
            ('verified_at','2026-10-25T08:00:00Z'),('archive_index_sha256','not-a-hash')]:
            p,feed,board,run,jobs=fixture()
            with self.subTest(key=key),self.assertRaises(f.FeedError):
                self.validate(p,feed,board,run,jobs,receipt_change=lambda r:r.update({key:value}))
        p,feed,board,run,jobs=fixture();q=deepcopy(p);q['lab_public_policy_sha256']='0'*64
        with self.assertRaisesRegex(f.FeedError,'V4_EXACT_PUBLIC_POLICY'):
            self.validate(q,feed,board,run,jobs)

    def test_public_receipt_closed_job_graph_and_bounded_gzip(self):
        def wrong_job(r):r['jobs']['produce']['api_job_id']=1
        def extra(r):r['unexpected']='extra'
        def missing(r):r.pop('choice_sha256')
        for change in (wrong_job,extra,missing):
            p,feed,board,run,jobs=fixture()
            with self.assertRaises(f.FeedError):self.validate(p,feed,board,run,jobs,receipt_change=change)
        for raw in (b'not-gzip',gzip.compress(b'x'*((64<<10)+1)),gzip.compress(b'{}')+b'trailing',b'x'*((64<<10)+1)):
            p,feed,board,run,jobs=fixture()
            with self.assertRaises(f.FeedError):self.validate(p,feed,board,run,jobs,raw_receipt=raw)

    def test_missing_public_opportunity_remains_missing_not_zero_and_unknown_value_rejects(self):
        p,feed,board,run,jobs=fixture();missing=feed['rows'].pop(0)['player_id']
        feed['coverage']=dict(private_selected_rows=11,public_rows=10,fallback_counts=dict(private_ineligible_R0=1))
        feed['identity_scope_sha256']=f.identity_scope(feed['rows'],board)
        (selected,_),_=self.validate(p,feed,board,run,jobs)
        self.assertNotIn(missing,{r['player_id']for r in selected['rows']})
        feed['rows'][0]['forecast_value']=None
        with self.assertRaises(ValueError):self.validate(p,feed,board,run,jobs)

    def test_no_role_product_ppr_or_source_policy_conversion(self):
        for kind in ('role','product','ppr','source','functional','bool','nan'):
            p,feed,board,run,jobs=fixture();row=feed['rows'][0]
            if kind=='role':board['players'][0]['pos']='K'
            if kind=='product':row['product']='point_legacy'
            if kind=='ppr':row['category']='fantasy_ppr'
            if kind=='source':row['source_policy_sha256']='0'*64
            if kind=='functional':row['prediction_functional']='legacy_unknown'
            if kind=='bool':row['forecast_value']=True
            if kind=='nan':row['forecast_value']=float('nan')
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):
                self.validate(p,feed,board,run,jobs)

    def test_closed_catalog_all_categories_unique_four_fields_no_values(self):
        for kind in ('missing_category','duplicate','extra_field','method','ppr','hash','current_values','extra_top','oversize','bad_type'):
            p,feed,board,run,jobs=fixture();cat=feed['publication']['version_catalog']
            if kind=='missing_category':cat['rows'].pop()
            if kind=='duplicate':cat['rows'].append(deepcopy(cat['rows'][0]))
            if kind=='extra_field':cat['rows'][0]['forecast_value']=0
            if kind=='method':cat['rows'][0]['method_id']='RAW'
            if kind=='ppr':cat['rows'][0]['category']='fantasy_ppr'
            if kind=='hash':cat['rows'][0]['model_version']='not-a-hash'
            if kind=='current_values':cat['current_values_used']=True
            if kind=='extra_top':cat['selection_rule']='new reselection'
            if kind=='oversize':cat['rows']*=24
            if kind=='bad_type':cat['rows'][0]=[]
            rehash(feed)
            with self.subTest(kind=kind),self.assertRaises(f.FeedError):self.validate(p,feed,board,run,jobs)

    def test_catalog_and_publication_physical_bindings_cannot_be_rehashed_away(self):
        for kind in ('source_catalog','catalog_digest','publication_digest','unlisted_row','recipe'):
            p,feed,board,run,jobs=fixture()
            if kind=='source_catalog':feed['publication']['source_version_catalog_sha256']='0'*64
            if kind=='catalog_digest':feed['publication']['version_catalog_sha256']='0'*64
            if kind=='publication_digest':feed['publication_sha256']='0'*64
            if kind=='unlisted_row':feed['rows'][0]['model_version']='0'*64
            if kind=='recipe':feed['producer_policy_sha256']='0'*64
            if kind in ('source_catalog','catalog_digest'):feed['publication_sha256']=f.digest(feed['publication'])
            with self.subTest(kind=kind),self.assertRaises(f.FeedError):self.validate(p,feed,board,run,jobs)

    def test_unregistered_template_and_wrong_static_scope_make_no_api_calls(self):
        template=v4.template(ROOT)
        self.assertEqual(template['state'],'PREPARED_UNREGISTERED')
        p,feed,board,run,jobs=fixture();bad=[template]
        for field in ('lab_public_policy_sha256','recipe_registration_sha256','workflow_sha256'):
            q=deepcopy(p);q[field]=None;bad.append(q)
        for field in ('public_roles','rights_authorities','r0_identities','engine_sha256','public_fields'):
            q=deepcopy(p);q[field]={} if isinstance(q[field],dict)else[];bad.append(q)
        for q in bad:
            calls=[]
            with self.assertRaises(f.FeedError):v4.validate_feed(feed,q,board,root=ROOT,now=NOW,fetch=transport(run,jobs,calls))
            self.assertEqual(calls,[])

    def test_wrong_source_authority_recipe_and_old_catalog_rule_reject(self):
        for key,value in [('schema_version',f.AUTHORITY_V2),('recipe_registration_sha256','0'*64),
            ('catalog_registration_rule','OWNED_SELECTED_VERSION_CATALOG_BEFORE_FEATURES_OR_VALUES'),
            ('source_sha','0'*40),('export_job','unregistered-job'),('run_attempt',True)]:
            p,feed,board,run,jobs=fixture();p['publication_authority'][key]=value
            with self.subTest(key=key),self.assertRaises(f.FeedError):self.validate(p,feed,board,run,jobs)

    def test_failed_stale_restarted_or_wrong_source_run_rejects(self):
        for key,value in [('head_sha','0'*40),('head_branch','other'),('event','push'),('run_attempt',2),
            ('status','in_progress'),('conclusion','failure'),('path','.github/workflows/other.yml'),('updated_at','2026-10-25T12:01:00Z')]:
            p,feed,board,run,jobs=fixture();run[key]=value
            with self.subTest(key=key),self.assertRaises(f.FeedError):self.validate(p,feed,board,run,jobs)

    def test_all_three_actual_jobs_must_be_unique_successful_same_source_and_ordered(self):
        for role in range(3):
            for kind in ('missing','duplicate','failed','wrong_source','wrong_run','bool_id','out_of_order'):
                p,feed,board,run,jobs=fixture();j=jobs['jobs'][role]
                if kind=='missing':jobs['jobs'].pop(role);jobs['total_count']-=1
                if kind=='duplicate':jobs['jobs'].append(deepcopy(j));jobs['total_count']+=1
                if kind=='failed':j['conclusion']='failure'
                if kind=='wrong_source':j['head_sha']='0'*40
                if kind=='wrong_run':j['run_id']=1
                if kind=='bool_id':j['id']=True
                if kind=='out_of_order':j['completed_at']='2026-10-25T12:00:29Z'
                with self.subTest(role=role,kind=kind),self.assertRaises(f.FeedError):self.validate(p,feed,board,run,jobs)

    def test_run_failure_or_restart_between_metadata_reads_rejects(self):
        for key,value in [('conclusion','failure'),('run_attempt',2),('status','queued'),('head_sha','0'*40)]:
            p,feed,board,run,jobs=fixture();final=deepcopy(run);final[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(f.FeedError,'V4_RUN_CHANGED'):
                self.validate(p,feed,board,run,jobs,final=final)

    def test_board_epoch_registration_and_expiry_clocks_reject(self):
        for kind in ('period','stale','registered_after_values','crossed_model'):
            p,feed,board,run,jobs=fixture()
            if kind=='period':feed['week']-=1
            if kind=='stale':feed['expires_at']='2026-10-25T12:00:00Z'
            if kind=='registered_after_values':p['lab_recipe_registered_at_utc']='2026-10-25T11:00:00Z'
            if kind=='crossed_model':board['execution_model']['model']='original_sleeper_matchup_baseline'
            with self.subTest(kind=kind),self.assertRaises(f.FeedError):self.validate(p,feed,board,run,jobs)

    def test_actual_dispatch_writer_approves_and_fallback_never_reuses_rows(self):
        p,feed,board,run,jobs=fixture();calls=[]
        selected,review,receipt=f.writer_input(ROOT,p,board,website_source_sha=HEAD,now=NOW,feed=feed,fetch=transport(run,jobs,calls))
        self.assertTrue(review['approved']);self.assertEqual(receipt['rows'],11);self.assertEqual(len(selected['rows']),11)
        self.assertEqual(review['recipe_registration_sha256'],p['recipe_registration_sha256'])
        bad=deepcopy(feed);bad['publication_sha256']='0'*64
        selected,review,receipt=f.writer_input(ROOT,p,board,website_source_sha=HEAD,now=NOW,feed=bad,fetch=transport(run,jobs,[]))
        self.assertEqual((selected,review),({},{}));self.assertEqual(receipt['state'],'CURRENT_REFERENCE_FALLBACK')

    def test_current_code_inventory_and_model_source_are_required_before_api(self):
        p,feed,board,run,jobs=fixture()
        for kind in ('inventory','scope','engine'):
            q=deepcopy(p)
            if kind=='inventory':q['website_code_sha256']['output/app.js']='0'*64
            if kind=='scope':q['website_code_sha256'].pop('tools/weekly_public_feed_v4.py')
            if kind=='engine':q['current_execution']['engine_sha256']['pull/build.py']='0'*64
            calls=[]
            with self.subTest(kind=kind),self.assertRaises(f.FeedError):v4.validate_feed(feed,q,board,root=ROOT,now=NOW,fetch=transport(run,jobs,calls))
            self.assertEqual(calls,[])
        with tempfile.TemporaryDirectory()as d:
            root=Path(d)
            for name in v4.CURRENT_CODE_FILES|{f.HISTORICAL_POLICY_PATH}:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
            path=root/'pull/scoring.py';raw=path.read_bytes();path.write_bytes(b'!'+raw[1:])
            with self.assertRaisesRegex(f.FeedError,'V4_CURRENT_ENGINE_SOURCE'):v4.policy_check(p,root=root,now=NOW)

    def test_source_head_and_mid_verification_code_changes_prevent_approval(self):
        p,feed,board,run,jobs=fixture();calls=[]
        selected,review,_=f.writer_input(ROOT,p,board,website_source_sha='0'*40,now=NOW,feed=feed,fetch=transport(run,jobs,calls))
        self.assertEqual((selected,review),({},{}));self.assertEqual(calls,[])
        with patch.object(f,'code_review',side_effect=['first-inventory','changed-inventory']):
            selected,review,receipt=f.writer_input(ROOT,p,board,website_source_sha=HEAD,now=NOW,feed=feed,fetch=transport(run,jobs,[]))
        self.assertEqual((selected,review),({},{}));self.assertEqual(receipt['reason'],'V4_INVENTORY_CHANGED_DURING_VERIFICATION')

    def test_old_authority_validator_does_not_accept_new_v4_policy(self):
        p,*_=fixture()
        with self.assertRaises(f.FeedError):f.policy_check_v2(p)
        self.assertEqual(f.CURRENT_CODE_FILES|{'tools/weekly_public_feed_v4.py'},v4.CURRENT_CODE_FILES)
        self.assertEqual(len(v4.CURRENT_CODE_FILES),len(f.CURRENT_CODE_FILES)+1)

class V4ScopeWitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network=patch.object(socket.socket,'connect',side_effect=AssertionError('REAL_NETWORK_FORBIDDEN'))
        cls.network.start()

    @classmethod
    def tearDownClass(cls):cls.network.stop()

    @contextmanager
    def case(self, *, witness_change=None):
        p,feed,board,run,jobs=fixture()
        witness=deepcopy(board)
        if witness_change:witness_change(witness)
        with tempfile.TemporaryDirectory()as d:
            root=Path(d)
            for name in v4.CURRENT_CODE_FILES|{f.HISTORICAL_POLICY_PATH}:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
            path=root/'output/data/week.json';path.parent.mkdir(parents=True);path.write_bytes(f.canonical(witness))
            def git(*args):return subprocess.check_output(['git','-C',d,*args],stderr=subprocess.DEVNULL)
            git('init','-q');git('add','--all')
            git('-c','user.name=Fictional test','-c','user.email=fictional@example.invalid','commit','-qm','Fictional immutable identity witness')
            commit=git('rev-parse','HEAD').decode().strip();blob=git('rev-parse','HEAD:output/data/week.json').decode().strip()
            raw=path.read_bytes()
            descriptor=dict(schema_version=v4.WITNESS_SCHEMA,commit=commit,path='output/data/week.json',git_blob_sha1=blob,bytes=len(raw),sha256=f.sha(raw))
            p[v4.WITNESS_FIELD]=[descriptor]
            yield root,p,feed,board,run,jobs,git

    def validate(self,root,p,feed,board,run,jobs,**kwargs):
        return v4.validate_feed(feed,p,board,root=root,now=kwargs.pop('now',NOW),fetch=transport(run,jobs,[],**kwargs))

    def test_actual_git_witness_validates_full_feed_before_current_missing_player(self):
        with self.case()as(root,p,feed,board,run,jobs,git):
            original=f.canonical(feed);missing=board['players'].pop(0)['id']
            selected,proof=self.validate(root,p,feed,board,run,jobs)
            self.assertEqual(len(selected['rows']),10);self.assertNotIn(missing,{r['player_id']for r in selected['rows']})
            self.assertEqual(f.canonical(feed),original)
            resolution=proof['identity_scope_resolution']
            self.assertEqual(resolution['original_validated_rows'],11);self.assertEqual(resolution['current_eligible_rows'],10)
            self.assertEqual(resolution['current_unavailable_counts'],{'current_player_missing':1})
            self.assertEqual(resolution['complete_original_scope_sha256'],feed['identity_scope_sha256'])
            self.assertEqual(resolution['witness'],p[v4.WITNESS_FIELD][0])
            self.assertIn('NOT_CAPTURE_TIME',resolution['purpose'])
            for row in selected['rows']:
                self.assertEqual({k:row[k]for k in f.overlay().ROW_FIELDS},next(r for r in feed['rows']if f.overlay().key(r)==f.overlay().key(row)))

    def test_each_current_drift_only_excludes_affected_opportunities(self):
        for kind in ('player','game','offer','team','opponent','kickoff','role','allowed_role','started','expired'):
            with self.subTest(kind=kind),self.case()as(root,p,feed,board,run,jobs,git):
                player=board['players'][0];pid=player['id'];game=board['games'][0]
                now=NOW
                if kind=='player':board['players'].pop(0)
                elif kind=='game':board['games']=[];board['players']=[]
                elif kind=='offer':player['props']=[]
                elif kind=='team':player['team']='OTHER'
                elif kind=='opponent':player['opp']='OTHER'
                elif kind=='kickoff':game['kickoff']='2026-10-26T18:00:00Z'
                elif kind=='role':player['pos']='K'
                elif kind=='allowed_role':player['pos']='WR'
                elif kind=='started':game['state']='in'
                elif kind=='expired':feed['rows'][0]['valid_until_utc']='2026-10-25T12:00:20Z'
                selected,proof=self.validate(root,p,feed,board,run,jobs,now=now)
                self.assertEqual(len(selected['rows']),0 if kind in ('game','kickoff','started')else 10)
                self.assertNotIn(pid,{r['player_id']for r in selected['rows']})
                self.assertEqual(len(feed['rows']),11)
                self.assertEqual(sum(proof['identity_scope_resolution']['current_unavailable_counts'].values())+len(selected['rows']),11)

    def test_invalid_original_values_role_identity_and_clocks_cannot_be_hidden_by_absence(self):
        for kind in ('negative','null','bool','late','catalog','source','scope'):
            with self.subTest(kind=kind),self.case()as(root,p,feed,board,run,jobs,git):
                board['players'].pop(0);row=feed['rows'][0]
                if kind=='negative':row['forecast_value']=-1
                elif kind=='null':row['forecast_value']=None
                elif kind=='bool':row['forecast_value']=True
                elif kind=='late':row['persistence_completed_at']='2026-10-26T18:00:00Z'
                elif kind=='catalog':row['model_version']='0'*64
                elif kind=='source':row['source_policy_sha256']='0'*64
                else:feed['identity_scope_sha256']='0'*64
                with self.assertRaises((ValueError,KeyError)):self.validate(root,p,feed,board,run,jobs)
        for kind in ('role','team','period','duplicate'):
            def change(w):
                if kind=='role':w['players'][0]['pos']='K'
                elif kind=='team':w['players'][0]['team']='OTHER'
                elif kind=='period':w['week']=6
                else:w['players'].append(deepcopy(w['players'][0]))
            with self.subTest(witness=kind),self.case(witness_change=change)as(root,p,feed,board,run,jobs,git):
                board['players'].pop(0)
                with self.assertRaises((ValueError,KeyError)):self.validate(root,p,feed,board,run,jobs)

    def test_descriptor_closed_types_and_duplicate_or_oversize_list_reject(self):
        mutations=[lambda d:d.update(path='../week.json'),lambda d:d.update(bytes=True),lambda d:d.update(bytes=(4<<20)+1),
            lambda d:d.update(schema_version='unknown'),lambda d:d.update(commit='main'),lambda d:d.update(sha256='0'*64),
            lambda d:d.update(git_blob_sha1='0'*40),lambda d:d.update(extra='unapproved')]
        for mutation in mutations:
            with self.case()as(root,p,feed,board,run,jobs,git):
                mutation(p[v4.WITNESS_FIELD][0])
                with self.assertRaises(ValueError):self.validate(root,p,feed,board,run,jobs)
        for count in (0,2,5):
            with self.case()as(root,p,feed,board,run,jobs,git):
                p[v4.WITNESS_FIELD]*=count
                with self.assertRaises(ValueError):self.validate(root,p,feed,board,run,jobs)

    def test_missing_wrong_size_nonancestor_or_symlink_git_witness_rejects(self):
        for kind in ('missing','size','nonancestor','symlink'):
            with self.subTest(kind=kind),self.case()as(root,p,feed,board,run,jobs,git):
                d=p[v4.WITNESS_FIELD][0]
                if kind=='missing':d['commit']='0'*40
                elif kind=='size':d['bytes']+=1
                elif kind=='nonancestor':
                    tree=git('rev-parse','HEAD^{tree}').decode().strip()
                    d['commit']=git('-c','user.name=Fictional test','-c','user.email=fictional@example.invalid','commit-tree',tree,'-m','Unrelated witness').decode().strip()
                else:
                    git('update-index','--cacheinfo','120000',d['git_blob_sha1'],d['path'])
                    git('-c','user.name=Fictional test','-c','user.email=fictional@example.invalid','commit','-qm','Symlink control')
                    d['commit']=git('rev-parse','HEAD').decode().strip()
                with self.assertRaises(ValueError):self.validate(root,p,feed,board,run,jobs)

    def test_bad_second_witness_cannot_be_skipped_for_convenient_valid_one(self):
        with self.case()as(root,p,feed,board,run,jobs,git):
            bad=deepcopy(p[v4.WITNESS_FIELD][0]);bad['commit']='0'*40;p[v4.WITNESS_FIELD].append(bad)
            board['players'].pop(0)
            with self.assertRaises(ValueError):self.validate(root,p,feed,board,run,jobs)

    def test_distinct_roots_and_new_process_freshly_reject_missing_or_corrupt_dependencies(self):
        with self.case()as(root,p,feed,board,run,jobs,git):
            d=p[v4.WITNESS_FIELD][0];self.assertEqual(v4.read_scope_witness(root,d)['season'],2026)
            with tempfile.TemporaryDirectory()as other:
                with self.assertRaises(ValueError):v4.read_scope_witness(Path(other),d)
            blob=root/'.git/objects'/d['git_blob_sha1'][:2]/d['git_blob_sha1'][2:]
            raw=blob.read_bytes();blob.chmod(0o600);blob.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
            with self.assertRaises(ValueError):v4.read_scope_witness(root,d)
            script='import sys,json;sys.path.insert(0,sys.argv[1]);import weekly_public_feed_v4 as v;v.read_scope_witness(sys.argv[2],json.loads(sys.argv[3]))'
            child=subprocess.run([sys.executable,'-c',script,str(ROOT/'tools'),str(root),json.dumps(d)],capture_output=True)
            self.assertNotEqual(child.returncode,0)

    def test_two_valid_witnesses_are_deterministic_and_role_ambiguity_rejects(self):
        for changed_role in (False,True):
            with self.subTest(changed_role=changed_role),self.case()as(root,p,feed,board,run,jobs,git):
                path=root/'output/data/week.json';witness=json.loads(path.read_bytes())
                witness['generated_at']='fictional-later-witness-not-forecast-proof'
                if changed_role:witness['players'][0]['pos']='WR'
                raw=f.canonical(witness);path.write_bytes(raw);git('add','--','output/data/week.json')
                git('-c','user.name=Fictional test','-c','user.email=fictional@example.invalid','commit','-qm','Second fictional identity witness')
                d=dict(schema_version=v4.WITNESS_SCHEMA,commit=git('rev-parse','HEAD').decode().strip(),
                    path='output/data/week.json',git_blob_sha1=git('rev-parse','HEAD:output/data/week.json').decode().strip(),bytes=len(raw),sha256=f.sha(raw))
                p[v4.WITNESS_FIELD].append(d);board['players'].pop(0)
                if changed_role:
                    with self.assertRaisesRegex(ValueError,'V4_AMBIGUOUS_WITNESS_ROLES'):self.validate(root,p,feed,board,run,jobs)
                else:
                    selected,proof=self.validate(root,p,feed,board,run,jobs)
                    self.assertEqual(len(selected['rows']),10)
                    self.assertEqual(proof['identity_scope_resolution']['witness'],v4.witness_descriptors(p)[0])

    def test_valid_other_week_witness_does_not_block_complete_current_scope(self):
        with self.case(witness_change=lambda w:w.update(week=6))as(root,p,feed,board,run,jobs,git):
            selected,proof=self.validate(root,p,feed,board,run,jobs)
            self.assertEqual(len(selected['rows']),11)
            self.assertIsNone(proof['identity_scope_resolution']['witness'])
            self.assertEqual(proof['identity_scope_resolution']['current_unavailable_counts'],{})

    def test_duplicates_fatal_and_legacy_no_witness_keeps_strict_full_scope(self):
        for kind in ('game','player','offer'):
            with self.subTest(kind=kind),self.case()as(root,p,feed,board,run,jobs,git):
                if kind=='game':board['games'].append(deepcopy(board['games'][0]))
                elif kind=='player':board['players'].append(deepcopy(board['players'][0]))
                else:board['players'][0]['props'].append(deepcopy(board['players'][0]['props'][0]))
                with self.assertRaises(ValueError):self.validate(root,p,feed,board,run,jobs)
        p,feed,board,run,jobs=fixture();board['players'].pop(0)
        with self.assertRaisesRegex(ValueError,'CURRENT_BOARD_SCOPE_CHANGED'):
            v4.validate_feed(feed,p,board,root=ROOT,now=NOW,fetch=transport(run,jobs,[]))

if __name__=='__main__':unittest.main(verbosity=2)
