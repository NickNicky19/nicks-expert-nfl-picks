"""Closed website-source transition; fictional feeds and no HTTP/model fitting.

Historical-policy and closed-engine adapters are mocked only in the small
dispatcher controls. Separate tests read/hash their actual retained bytes.
These checks do not qualify a native receipt, saved generation or deployment.
"""
from contextlib import ExitStack
from copy import deepcopy
import os
import subprocess
import zlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import weekly_public_feed as f
from test_weekly_publication_authority_v2 import fixture,transport,NOW,SOURCE


def transition_fixture():
    historical,feed,board,run,jobs=fixture()
    execution=dict(schema_version=f.CURRENT_EXECUTION,model=f.CURRENT_MODEL,
        inputs_schema='matchup-inputs-v3',native_schema='baseline-capture-v2',
        verification_contract='partial-week-data-integrity-v2',
        engine_sha256={name:'8'*64 for name in f.ENGINE_FILES|{'pull/grade.py'}})
    current={name:execution['engine_sha256'].get(name,'6'*64) for name in f.CODE_FILES}
    policy=deepcopy(historical)
    policy.update(schema_version=f.POLICY_V3,historical_policy_sha256=f.HISTORICAL_POLICY_SHA256,
        current_execution=deepcopy(execution),website_code_sha256=current,active_policy_sha256=f.ACTIVE_POLICY_SHA256)
    return policy,historical,execution,feed,board,run,jobs


class WeeklyPhase2BindingChecks(unittest.TestCase):
    def adapters(self,historical,execution):
        stack=ExitStack()
        stack.enter_context(patch.object(f,'historical_policy_v2',return_value=deepcopy(historical)))
        stack.enter_context(patch.object(f,'current_execution_contract',return_value=deepcopy(execution)))
        active=deepcopy(historical);active['website_code_sha256']['tools/weekly_selected_rankings.py']='6'*64
        stack.enter_context(patch.object(f,'active_policy_v2',return_value=active))
        return stack

    def test_historical_R0_and_current_corrected_execution_remain_distinct(self):
        policy,historical,execution,*_=transition_fixture();before=f.canonical(historical)
        with self.adapters(historical,execution):
            self.assertEqual(f.policy_check_v3(policy),historical)
            self.assertEqual(f.policy_check(policy),historical)
        self.assertEqual(f.canonical(historical),before)
        self.assertEqual(policy['engine_sha256'],historical['engine_sha256'])
        self.assertEqual(policy['r0_identities'],historical['r0_identities'])
        self.assertNotEqual(policy['engine_sha256']['pull/build.py'],policy['current_execution']['engine_sha256']['pull/build.py'])
        with self.assertRaisesRegex(f.FeedError,'V2_POLICY_CONTRACT'):f.policy_check_v2(policy)

    def test_every_historical_authority_and_engine_field_is_preserved(self):
        updates={'engine_sha256':{name:'9'*64 for name in f.ENGINE_FILES},'r0_identities':['9'*64],
            'rights_authorities':['9'*64],'producer_policy_sha256':'9'*64,'source_policy_sha256':'9'*64,
            'public_roles':{},'procedures':{},'human_approval':True,
            'publication_authority':dict(transition_fixture()[1]['publication_authority'],source_sha='9'*40)}
        for field,value in updates.items():
            policy,historical,execution,*_=transition_fixture();policy[field]=value
            with self.subTest(field=field),self.adapters(historical,execution),self.assertRaises(f.FeedError):
                f.policy_check_v3(policy)

    def test_unknown_models_versions_hashes_and_fields_are_not_fallbacks(self):
        updates=[('model','sleeper-matchup-data-integrity-v999'),('model','original_sleeper_matchup_baseline'),
            ('inputs_schema','matchup-inputs-v2'),('native_schema','baseline-capture-v1'),
            ('verification_contract','strict-full-board-v1'),('engine_sha256',{'pull/build.py':'9'*64})]
        for field,value in updates:
            policy,historical,execution,*_=transition_fixture();policy['current_execution'][field]=value
            with self.subTest(field=field,value=value),self.adapters(historical,execution),self.assertRaises(f.FeedError):
                f.policy_check_v3(policy)
        for field,value in [('historical_policy_sha256','9'*64),('extra','unsupported'),('human_approval',0)]:
            policy,historical,execution,*_=transition_fixture();policy[field]=value
            with self.subTest(field=field),self.adapters(historical,execution),self.assertRaises(f.FeedError):f.policy_check_v3(policy)
        policy,historical,execution,*_=transition_fixture();policy['website_code_sha256']['pull/build.py']='9'*64
        with self.adapters(historical,execution),self.assertRaisesRegex(f.FeedError,'CURRENT_ENGINE_CODE_MISMATCH'):f.policy_check_v3(policy)

    def test_actual_historical_registration_is_freshly_hashed_and_not_relabelled(self):
        # Real retained public Git objects; no source/clock/model mocks here.
        objects=f.registration_objects(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True)
            for oid,item in objects.items():
                actual=subprocess.run(['git','-C',str(root),'hash-object','-w','-t',item['type'],'--stdin'],input=item['body'],capture_output=True,check=True).stdout.decode().strip()
                self.assertEqual(actual,oid)
            original=f.historical_policy_v2(root);active=f.active_policy_v2(root)
            self.assertEqual(len(original['website_code_sha256']),13);self.assertEqual(len(active['website_code_sha256']),14)
            self.assertEqual(original['engine_sha256'],active['engine_sha256']);self.assertEqual(original['r0_identities'],active['r0_identities'])
            path=root/f.HISTORICAL_POLICY_PATH;path.parent.mkdir();path.write_text('NOT THE REGISTERED GIT POLICY')
            self.assertEqual(f.historical_policy_v2(root),original)
            self.assertEqual(f.active_policy_v2(root),active)
            target=root/'.git/objects'/f.HISTORICAL_POLICY_BLOB[:2]/f.HISTORICAL_POLICY_BLOB[2:]
            initial=target.read_bytes();decoded=zlib.decompress(initial);old=target.stat()
            target.chmod(0o644)  # Only the new temporary Git object copy is corrupted.
            target.write_bytes(zlib.compress(decoded.replace(b'ROOT_REGISTERED',b'ROOT_REGISTEREE',1)));os.utime(target,ns=(old.st_atime_ns,old.st_mtime_ns))
            with self.assertRaises(ValueError):f.historical_policy_v2(root)
            target.write_bytes(initial)
            self.assertEqual(f.historical_policy_v2(root),original)
            target.unlink()
            with self.assertRaises(ValueError):f.historical_policy_v2(root)

    def test_actual_corrected_contract_is_closed_and_same_size_corruption_rejects(self):
        contract=f.current_execution_contract(ROOT)
        self.assertEqual(contract['model'],'sleeper-matchup-data-integrity-v2')
        self.assertEqual(contract['inputs_schema'],'matchup-inputs-v3')
        self.assertEqual(set(contract['engine_sha256']),f.ENGINE_FILES|{'pull/grade.py'})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,expected in contract['engine_sha256'].items():
                body=(ROOT/name).read_bytes();self.assertEqual(f.sha(body),expected)
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
            self.assertEqual(f.current_execution_contract(root),contract)
            path=root/'pull/build.py';body=path.read_bytes();old=path.stat();path.write_bytes(b'!'+body[1:]);os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
            with self.assertRaisesRegex(ValueError,'Unrecognized corrected source bytes'):f.current_execution_contract(root)

    def test_current_source_review_checks_actual_head_and_every_code_byte(self):
        policy,historical,execution,*_=transition_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in f.CODE_FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('FICTIONAL '+name).encode())
            code={name:f.sha((root/name).read_bytes())for name in f.CODE_FILES}
            execution['engine_sha256'].update({name:code[name]for name in f.ENGINE_FILES})
            policy.update(website_code_sha256=code,current_execution=deepcopy(execution))
            with self.adapters(historical,execution),patch.object(f.subprocess,'run',return_value=SimpleNamespace(stdout=SOURCE)):
                self.assertEqual(f.code_review(root,policy,SOURCE),f.digest(code))
                with self.assertRaisesRegex(f.FeedError,'CURRENT_HEAD_MISMATCH'):f.code_review(root,policy,'0'*40)
                path=root/'output/app.js';body=path.read_bytes();old=path.stat();path.write_bytes(b'!'+body[1:]);os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
                with self.assertRaisesRegex(f.FeedError,'WEBSITE_CODE_NOT_REGISTERED'):f.code_review(root,policy,SOURCE)

    def test_v3_uses_unchanged_V2_feed_and_its_exact_original_R0_identity(self):
        policy,historical,execution,feed,board,run,jobs=transition_fixture();before=deepcopy(feed);calls=[]
        with self.adapters(historical,execution),patch.object(f,'code_review',return_value='a'*64):
            selected,review,receipt=f.writer_input('.',policy,board,website_source_sha=SOURCE,now=NOW,feed=feed,fetch=transport(run,jobs,calls))
        self.assertEqual(len(selected['rows']),1);self.assertEqual(len(calls),2);self.assertEqual(feed,before)
        self.assertEqual(receipt['state'],'AUTOMATED_POLICY_ACCEPTED')
        self.assertEqual(review['current_reference_model'],f.CURRENT_MODEL)
        self.assertEqual(review['historical_policy_sha256'],f.HISTORICAL_POLICY_SHA256)
        self.assertEqual(feed['r0_identity_sha256'],historical['r0_identities'][0])

    def test_invalid_v3_never_calls_the_legacy_writer_or_fetches(self):
        policy,historical,execution,feed,board,run,jobs=transition_fixture();policy['current_execution']['model']='unknown';calls=[]
        with self.adapters(historical,execution),patch.object(f,'writer_input_v2',side_effect=AssertionError('no V2 retry')):
            selected,review,receipt=f.writer_input('.',policy,board,website_source_sha=SOURCE,now=NOW,fetch=transport(run,jobs,calls))
        self.assertEqual((selected,review),({},{}));self.assertEqual(receipt['state'],'CURRENT_REFERENCE_FALLBACK');self.assertEqual(calls,[])

    def test_website_execution_policy_cannot_export_or_directly_admit_lab_rows(self):
        policy,_,_,feed,board,_,_=transition_fixture()
        with self.assertRaisesRegex(f.FeedError,'WEBSITE_EXECUTION_POLICY_NOT_LAB_EXPORT'):f.private_gates({},policy,now=NOW)
        with self.assertRaisesRegex(f.FeedError,'WEBSITE_EXECUTION_POLICY_NOT_LAB_EXPORT'):f.export_rows([],{},policy,board,now=NOW)
        with self.assertRaisesRegex(f.FeedError,'VERIFIED_ISSUED_CATALOG_REQUIRED'):f.member(policy,feed['rows'][0])

    def test_retained_v2_validation_still_requires_its_own_qualification(self):
        policy,feed,board,run,jobs=fixture();calls=[]
        self.assertEqual(len(f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,calls))['rows']),1)
        self.assertEqual(len(calls),2)
        feed['r0_identity_sha256']='0'*64
        with self.assertRaisesRegex(f.FeedError,'FEED_POLICY_BINDING'):f.validate_feed(feed,policy,board,now=NOW,fetch=transport(run,jobs,[]))


    def test_original13_V3_layout_remains_separate_from_current14(self):
        policy,historical,execution,*_=transition_fixture()
        policy['website_code_sha256'].pop('tools/weekly_selected_rankings.py')
        policy.pop('active_policy_sha256')
        with self.adapters(historical,execution):self.assertEqual(f.policy_check_v3(policy),historical)
        policy['active_policy_sha256']=f.ACTIVE_POLICY_SHA256
        with self.adapters(historical,execution),self.assertRaisesRegex(f.FeedError,'CLOSED_V3_POLICY_FIELDS'):f.policy_check_v3(policy)

    def test_current14_requires_actual_active_registration_identity(self):
        policy,historical,execution,*_=transition_fixture()
        for value in ('0'*64,None):
            changed=deepcopy(policy)
            if value is None:changed.pop('active_policy_sha256')
            else:changed['active_policy_sha256']=value
            with self.adapters(historical,execution),self.assertRaises(f.FeedError):f.policy_check_v3(changed)
        active=deepcopy(historical);active['website_code_sha256']['tools/weekly_selected_rankings.py']='6'*64;active['producer_policy_sha256']='0'*64
        with self.adapters(historical,execution),patch.object(f,'active_policy_v2',return_value=active),self.assertRaisesRegex(f.FeedError,'ACTIVE_SCIENTIFIC_REGISTRATION_CHANGED'):f.policy_check_v3(policy)

    def test_V2_current14_semantics_preserve_legacy13_without_v1_expansion(self):
        historical,feed,board,run,jobs=fixture();current=deepcopy(historical)
        current['website_code_sha256']['tools/weekly_selected_rankings.py']='6'*64
        self.assertIsNone(f.policy_check_v2(current))
        self.assertEqual(f.validate_feed(feed,current,board,now=NOW,fetch=transport(run,jobs,[])),f.validate_feed(feed,historical,board,now=NOW,fetch=transport(run,jobs,[])))
        v1=f.catalog_policy_v2(current,feed['publication']['version_catalog'])
        self.assertEqual(set(v1['website_code_sha256']),f.LEGACY_CODE_FILES)
        v1['website_code_sha256']['tools/weekly_selected_rankings.py']='6'*64
        with self.assertRaisesRegex(f.FeedError,'REGISTERED_ENGINE_INVENTORY'):f.policy_check(v1)
        current['website_code_sha256']['tools/unknown_ranker.py']=current['website_code_sha256'].pop('tools/weekly_selected_rankings.py')
        with self.assertRaisesRegex(f.FeedError,'REGISTERED_V2_CODE_INVENTORY'):f.policy_check_v2(current)


class WeeklyPhase2StaticChecks(unittest.TestCase):
    def metadata(self):
        import check_weekly_consumer_v3_static as checker
        historical=f.historical_policy_v2(ROOT);execution=f.current_execution_contract(ROOT)
        code={name:f.sha((ROOT/name).read_bytes())for name in f.CODE_FILES}
        policy=deepcopy(historical);policy.update(schema_version=f.POLICY_V3,
            historical_policy_sha256=f.HISTORICAL_POLICY_SHA256,current_execution=execution,website_code_sha256=code,active_policy_sha256=f.ACTIVE_POLICY_SHA256)
        body=f.canonical(policy);policy_path='config/weekly-derived-selected-policy-v3.json'
        # Fictional static proposal, not the installed production workflow.
        hourly=('run: python tools/weekly_adaptive_overlay.py --root . --website-source-sha "$(git rev-parse HEAD)" '
            '--feed-policy '+policy_path+' --feed-policy-sha256 '+f.sha(body)+'\n').encode()
        pins=dict(policy_path=policy_path,physical_sha256=dict(policy=f.sha(body),
            helper=f.sha((ROOT/'tools/weekly_public_feed.py').read_bytes()),
            schema=f.sha((ROOT/'schemas/weekly-derived-selected-feed-v2.json').read_bytes()),hourly=f.sha(hourly)),
            code_paths=sorted(f.CODE_FILES),new_lab_source_sha=historical['publication_authority']['source_sha'],
            new_producer_policy_sha256=historical['producer_policy_sha256'],new_source_policy_sha256=historical['source_policy_sha256'],
            new_catalog_freezer_sha256=historical['publication_authority']['catalog_freezer_sha256'],
            new_procedures=deepcopy(historical['procedures']),new_app_sha256=code['output/app.js'])
        return checker,policy,pins,dict(policy=body,hourly=hourly)

    def test_static_V3_keeps_public_feed_V2_and_separates_historical_R0(self):
        checker,policy,pins,bodies=self.metadata();result=checker.check_current_port(ROOT,pins,bodies)
        self.assertEqual(result['state'],'PROPOSED_STATIC_CONTRACT_PASS')
        self.assertEqual(result['current_reference_model'],f.CURRENT_MODEL)
        self.assertEqual(result['historical_policy_sha256'],f.HISTORICAL_POLICY_SHA256)
        self.assertEqual(result['website_code_inventory_checks'],14)
        self.assertFalse(result['installed_port_acceptance']);self.assertFalse(result['hosted_publication_or_deployment_acceptance'])
        self.assertEqual(result['HTTP'],0);self.assertEqual(result['model_or_data_reads'],0)

    def test_static_V3_cannot_repin_old_engine_or_change_lab_authority(self):
        for field,value in [('engine_sha256',f.current_execution_contract(ROOT)['engine_sha256']),
                ('publication_authority',dict(f.historical_policy_v2(ROOT)['publication_authority'],source_sha='0'*40))]:
            checker,policy,pins,bodies=self.metadata();policy[field]=value;bodies['policy']=f.canonical(policy)
            pins['physical_sha256']['policy']=f.sha(bodies['policy'])
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'HISTORICAL_OR_CURRENT_EXECUTION_CHANGED'):
                checker.check_current_port(ROOT,pins,bodies)


if __name__=='__main__':unittest.main()
