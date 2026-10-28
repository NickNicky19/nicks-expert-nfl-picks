"""Bounded main-only transition. Fictional fixtures; all provider access denied."""
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'pull'),str(ROOT/'tests')]
import classic_model_v1 as model
import classic_source_replay_v1 as sources
import classic_build_pair_v1 as pair
import reliability as r
import weekly_public_feed as f
from test_reliability import fixture as board_fixture
from test_weekly_publication_authority_v2 import fixture,transport,NOW,SOURCE
from test_classic_build_pair_v1 import retained_classic_source

def policy():
    old=f.active_policy_v2(ROOT)
    value=deepcopy(old)
    value.update(schema_version=f.POLICY_V3,historical_policy_sha256=f.ACTIVE_POLICY_SHA256,
        current_execution=f.current_execution_contract(ROOT),
        website_code_sha256={name:f.sha((ROOT/name).read_bytes())for name in f.PIPELINE_CODE_FILES})
    return value

class ClassicProfileTests(unittest.TestCase):
    def test_frozen_original_values_keep_original_model_and_other_periods_do_not(self):
        board,_=board_fixture();board['generated_at']='2031-10-25T18:00:00Z'
        board['games'][0]['state']='in';board['games'][0]['kickoff']='2031-10-25T17:00:00Z'
        old=deepcopy(board);old['players'][0]['reference_model']=model.ORIGINAL_MODEL
        pair.bind_reference_origins(board,old)
        self.assertEqual(board['players'][0]['reference_model'],model.ORIGINAL_MODEL)
        old['week']-=1
        pair.bind_reference_origins(board,old)
        self.assertEqual(board['players'][0]['reference_model'],model.MODEL)

    def test_original_hash_check_rejects_actual_corrected_source(self):
        with self.assertRaisesRegex(r.IntegrityError,'Original engine changed'):
            r.engine_hashes(ROOT)

    def test_current_model_closes_all_eight_actual_files(self):
        with tempfile.TemporaryDirectory()as d:
            legacy=retained_classic_source(Path(d))
            contract=model.contract(legacy)
            self.assertEqual(set(contract['engine_sha256']),set(model.ENGINE))
            self.assertEqual(contract['model'],'sleeper-matchup-classic-fg-identity-v1')
            self.assertIn('pull/grade.py',contract['engine_sha256'])
        current=f.current_execution_contract(ROOT)
        self.assertEqual(current['model'],'sleeper-matchup-classic-data-integrity-v2')
        self.assertEqual(set(current['engine_sha256']),set(model.ENGINE))
        self.assertNotEqual(current['engine_sha256'],contract['engine_sha256'])
        with self.assertRaisesRegex(ValueError,'UNRECOGNIZED_CLASSIC_CURRENT_SOURCE'):
            model.contract(ROOT)

    def test_same_size_engine_or_grader_corruption_is_rejected(self):
        for changed in ['pull/scoring.py','pull/grade.py']:
            with self.subTest(changed=changed),tempfile.TemporaryDirectory()as d:
                root=retained_classic_source(Path(d))
                self.assertEqual(model.contract(root),model.execution_contract())
                p=root/changed;raw=p.read_bytes();old=p.stat();p.write_bytes(b'!'+raw[1:]);os.utime(p,ns=(old.st_atime_ns,old.st_mtime_ns))
                with self.assertRaisesRegex(ValueError,'UNRECOGNIZED_CLASSIC_CURRENT_SOURCE: '+changed):model.contract(root)

    def test_current_native_has_its_own_model_schema_and_clock(self):
        board,meta=board_fixture();now=datetime.now(timezone.utc);board['generated_at']=r.stamp(now);meta['generated_at']=board['generated_at']
        board['games'][0]['kickoff']='2099-10-25T17:00:00Z'
        with tempfile.TemporaryDirectory()as d:
            root=retained_classic_source(Path(d))
            board['execution_model']=meta['execution_model']=model.contract(root)
            for player in board['players']:player['reference_model']=model.MODEL
            with patch.dict(os.environ):
                os.environ.pop('GITHUB_SHA',None)
                path,health=r.capture_profile(board,meta,root,datetime.now(timezone.utc),model=model.MODEL,mode='replay')
            payload=json.loads(gzip.decompress(path.read_bytes()))['payload']
            self.assertEqual(payload['model'],model.MODEL);self.assertEqual(payload['schema_version'],model.CAPTURE)
            self.assertEqual(payload['engine_files'],model.ENGINE)
            self.assertNotEqual(payload['model'],model.ORIGINAL_MODEL)
            self.assertGreaterEqual(r.utc(payload['captured_at']),r.utc(board['generated_at']))
            # A forged row cannot hide behind the correct immutable file name
            # and a recomputed envelope checksum on a subsequent capture.
            payload['rows'][0]['adjusted_projection']+=1
            path.write_bytes(gzip.compress(r.canonical(dict(payload=payload,payload_sha256=r.digest(payload))),mtime=0))
            with self.assertRaisesRegex(r.IntegrityError,'CURRENT_NATIVE_CONTENT'):
                r.capture_profile(board,meta,root,datetime.now(timezone.utc),model=model.MODEL,mode='replay')

    def test_unknown_and_crossed_profiles_fail_without_fallback(self):
        for value in ['unknown','sleeper-matchup-unregistered-v99']:
            with self.subTest(value=value),self.assertRaisesRegex(r.IntegrityError,'UNKNOWN_CAPTURE_PROFILE'):
                r.capture_profile({}, {}, ROOT, datetime.now(timezone.utc), model=value)
        # The earlier corrected model is supported only with its actual source;
        # recognizing that name never permits today's different engine bytes.
        with self.assertRaisesRegex(r.IntegrityError,'Installed source differs from explicit presence model'):
            r.capture_profile({}, {}, ROOT, datetime.now(timezone.utc), model='sleeper-matchup-data-integrity-v2')
        with self.assertRaisesRegex(ValueError,'UNRECOGNIZED_CLASSIC_CURRENT_SOURCE'):
            r.capture_profile({}, {}, ROOT, datetime.now(timezone.utc), model=model.MODEL)
        with tempfile.TemporaryDirectory()as d:
            legacy=retained_classic_source(Path(d))
            with self.assertRaisesRegex(r.IntegrityError,'CURRENT_BOARD_EXECUTION_BINDING'):
                r.capture_profile({}, {}, legacy, datetime.now(timezone.utc), model=model.MODEL)
        with self.assertRaisesRegex(r.IntegrityError,'Original engine changed'):
            r.capture_profile({}, {}, ROOT, datetime.now(timezone.utc), model=model.ORIGINAL_MODEL)

    def test_live_cli_rejects_supplied_replay_clock(self):
        result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/reliability.py'),'--mode','live','--model',model.MODEL,'--replay-at','2000-01-01T00:00:00Z'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('Live capture cannot use a supplied clock',result.stderr)

    def test_legacy_cli_reaches_actual_closed_capture_and_rejects_unknown_model(self):
        board,meta=board_fixture();now=datetime.now(timezone.utc)
        board['generated_at']=meta['generated_at']=r.stamp(now)
        board['games'][0]['kickoff']='2099-10-25T17:00:00Z'
        with tempfile.TemporaryDirectory()as d:
            root=retained_classic_source(Path(d))
            board['execution_model']=meta['execution_model']=model.contract(root)
            for player in board['players']:player['reference_model']=model.MODEL
            (root/'output/data').mkdir(parents=True)
            for name,value in [('week',board),('meta',meta)]:
                (root/'output/data'/ (name+'.json')).write_text(json.dumps(value))
            environment=dict(os.environ);environment.pop('GITHUB_SHA',None)
            command=[sys.executable,'-B',str(ROOT/'tools/reliability.py'),'--root',str(root),'--mode','replay']
            result=subprocess.run([*command,'--model',model.MODEL],env=environment,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            health=json.loads(result.stdout)
            self.assertEqual(health['capture_model'],model.MODEL)
            payload=json.loads(gzip.decompress((root/health['receipt']).read_bytes()))['payload']
            self.assertEqual(payload['engine_files'],model.ENGINE)
            self.assertIsNone(payload['code_commit'])
            before={p.relative_to(root).as_posix():p.read_bytes()for p in (root/'data').rglob('*')if p.is_file()}
            rejected=subprocess.run([*command,'--model','unknown'],env=environment,capture_output=True,text=True)
            self.assertNotEqual(rejected.returncode,0)
            self.assertIn('invalid choice',rejected.stderr)
            self.assertEqual({p.relative_to(root).as_posix():p.read_bytes()for p in (root/'data').rglob('*')if p.is_file()},before)

    def test_default_cli_preserves_original_capture_route(self):
        expected=({'original':'board'},{'original':'meta'})
        with patch.object(sys,'argv',['reliability.py','--mode','replay']),\
             patch.object(r,'load_json',side_effect=expected),\
             patch.object(r,'engine_hashes',return_value={'actual':'original'})as hashes,\
             patch.object(r,'capture',return_value=(Path('fictional.json.gz'),{'capture_model':model.ORIGINAL_MODEL}))as capture,\
             patch.object(r,'capture_profile',side_effect=AssertionError('legacy default switched dispatcher')),\
             patch('builtins.print'):
            r.main()
        hashes.assert_called_once_with(r.ROOT.resolve())
        self.assertEqual(capture.call_args.args[:2],expected)
        self.assertEqual(capture.call_args.kwargs,{'mode':'replay'})

class ClassicPolicyTests(unittest.TestCase):
    def test_current_reference_rankings_carry_current_model_not_original_R0(self):
        import weekly_selected_rankings as ranking,weekly_adaptive_overlay as overlay
        from test_weekly_selected_rankings import fixture as ranking_fixture,make
        board,doc=ranking_fixture();execution=f.current_execution_contract(ROOT);board['execution_model']=execution
        for player in board['players']:player['reference_model']=execution['model']
        doc['rows']=[];doc['display_board_sha256']=doc['canonical_board_sha256']=overlay.digest(board)
        result=make(board,doc)
        self.assertEqual(result['policy'],ranking.CURRENT_POLICY)
        items=[item for rows in result['picks'].values()for item in rows]
        self.assertTrue(items)
        self.assertTrue(all(item['forecast_source']=='CURRENT_BASELINE'and item['model_version']==execution['model'] for item in items))
        offers=overlay.board_offers(board)
        bad=deepcopy(items[0]);bad.update(forecast_source='R0_FALLBACK',model_version=None)
        with self.assertRaisesRegex(ValueError,'ranking reference model'):ranking.validate_item(bad,offers,{})

    def test_actual_historical_caption_policy_preserved_and_current_is_distinct(self):
        body=(ROOT/f.HISTORICAL_POLICY_PATH).read_bytes();value=policy()
        self.assertEqual(f.sha(body),'e8e037a00a22d3e0e07e41ed5816f2374e8f162a7fa78ea8cc45888ed2e2f094')
        self.assertEqual(f.policy_check_v3(value,root=ROOT),json.loads(body))
        self.assertEqual(value['engine_sha256'],json.loads(body)['engine_sha256'])
        self.assertNotEqual(value['engine_sha256']['pull/build.py'],value['current_execution']['engine_sha256']['pull/build.py'])
        self.assertEqual((ROOT/f.HISTORICAL_POLICY_PATH).read_bytes(),body)
        # The earlier315 registration is separately retained under its own
        # original14/13-path contract; it is never repinned to current source.
        historical=f.historical_policy_v2(ROOT)
        historical_bytes=f._registration_object(ROOT,f.HISTORICAL_POLICY_BLOB,'blob',1<<20)
        self.assertEqual(f.sha(historical_bytes),f.HISTORICAL_POLICY_SHA256)
        self.assertEqual(json.loads(historical_bytes),historical)
        self.assertNotEqual(historical['website_code_sha256'],value['website_code_sha256'])

    def test_historical_fields_and_current_model_cannot_be_repinned(self):
        for change in [lambda p:p['engine_sha256'].update(p['current_execution']['engine_sha256']),
                       lambda p:p['r0_identities'].append('0'*64),
                       lambda p:p['current_execution'].update(model='sleeper-matchup-data-integrity-v2'),
                       lambda p:p['website_code_sha256'].pop('tools/classic_build_pair_v1.py')]:
            value=policy();change(value)
            with self.assertRaises(f.FeedError):f.policy_check_v3(value,root=ROOT)

    def test_V2_selected_feed_still_consumed_under_separate_current_execution(self):
        historical,feed,board,run,jobs=fixture();before=deepcopy(feed)
        actual=policy();execution=actual['current_execution']
        value=deepcopy(historical)
        value.update(schema_version=f.POLICY_V3,historical_policy_sha256=f.ACTIVE_POLICY_SHA256,
            current_execution=execution,website_code_sha256=actual['website_code_sha256'])
        board['execution_model']=execution
        calls=[]
        with patch.object(f,'active_policy_v2',return_value=deepcopy(historical)),\
             patch.object(f,'current_execution_contract',return_value=execution),\
             patch.object(f,'code_review',return_value='a'*64):
            selected,review,receipt=f.writer_input(ROOT,value,board,website_source_sha=SOURCE,now=NOW,feed=feed,fetch=transport(run,jobs,calls))
        self.assertEqual(receipt['state'],'AUTOMATED_POLICY_ACCEPTED');self.assertEqual(len(selected['rows']),1)
        self.assertEqual(receipt['current_reference_model'],execution['model']);self.assertEqual(feed,before);self.assertEqual(len(calls),2)

    def test_bad_V3_never_retries_V2_or_fetches(self):
        value=policy();value['current_execution']['model']='unknown'
        with patch.object(f,'writer_input_v2',side_effect=AssertionError('V2 retry forbidden')):
            selected,review,receipt=f.writer_input(ROOT,value,{},website_source_sha=SOURCE,now=NOW,fetch=lambda*a:(_ for _ in ()).throw(AssertionError('network')))
        self.assertEqual((selected,review),({},{}));self.assertEqual(receipt['state'],'CURRENT_REFERENCE_FALLBACK')

    def test_current_execution_policy_is_not_a_lab_export_registration(self):
        with self.assertRaisesRegex(f.FeedError,'WEBSITE_EXECUTION_POLICY_NOT_LAB_EXPORT'):
            f.private_gates({},policy(),now=NOW)

class InputCoverageTests(unittest.TestCase):
    def test_current_extension_cannot_read_other_urls_params_or_unqualified_callsites(self):
        for url,params in [('https://api.sleeper.app/projections/nfl/2098/1',None),
                           ('https://api.sleeper.app/stats/nfl/2098/1',{'wrong':'params'}),
                           ('https://api.sleeper.app/stats/nfl/2098/1',[('season_type','regular'),*[('position[]',p)for p in sources.POSITIONS]])]:
            with self.subTest(url=url,params=params),tempfile.TemporaryDirectory()as d:
                original=Path(d)/'original';record=sources.Inputs(original,'record',fetch=lambda*a,**k:{})
                record.finish();current=Path(d)/'current';shutil.copytree(original,current)
                extension=sources.Inputs(current,'extend',fetch=lambda*a,**k:(_ for _ in ()).throw(AssertionError('network forbidden')),allowed_stats_periods=[(2098,1)])
                with self.assertRaisesRegex(sources.CoverageError,'UNQUALIFIED_CURRENT_SOURCE_EXTENSION'):extension.request(url,params)
                with self.assertRaises(sources.CoverageError):extension.finish()

    def test_record_replay_and_source_book_aliases_share_exact_responses(self):
        with tempfile.TemporaryDirectory()as d:
            calls=[]
            def fetch(url,params=None):calls.append((url,params));return {'fgm':3,'nested':[1],'observation':len(calls)}
            module=SimpleNamespace(get_json=fetch);book=SimpleNamespace(sources=module,captured_alias=fetch)
            record=sources.Inputs(Path(d)/'inputs','record',fetch=fetch)
            with record.install(module,[book]):
                one=module.get_json('https://api.sleeper.app/test',{'a':1})
                one['nested'].append(99)
                two=book.captured_alias('https://api.sleeper.app/test',{'a':1})
            self.assertEqual(two,{'fgm':3,'nested':[1],'observation':2});self.assertEqual(len(calls),2)
            original=record.finish()
            replay=sources.Inputs(Path(d)/'inputs','replay')
            with replay.install(module,[book]):
                self.assertEqual(book.captured_alias('https://api.sleeper.app/test',{'a':1})['observation'],1)
                self.assertEqual(book.captured_alias('https://api.sleeper.app/test',{'a':1}),two)
            self.assertEqual(replay.finish()['input_index_sha256'],original['input_index_sha256'])

    def test_missing_request_stays_fatal_when_book_catches_exception(self):
        with tempfile.TemporaryDirectory()as d:
            record=sources.Inputs(Path(d)/'inputs','record',fetch=lambda*a,**k:{});record.finish()
            replay=sources.Inputs(Path(d)/'inputs','replay')
            try:replay.request('https://api.sleeper.app/missing')
            except Exception:pass
            with self.assertRaisesRegex(sources.CoverageError,'SOURCE_COVERAGE_FAILED'):replay.finish()

    def test_corrupt_raw_body_rejected_and_qualified_failure_persisted(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d)/'inputs';record=sources.Inputs(root,'record',fetch=lambda*a,**k:{'fgm':3})
            record.request('https://api.sleeper.app/test');record.finish()
            body=next(p for p in root.glob('*.json')if p.name!='INDEX.json');body.write_bytes(b'{}')
            replay=sources.Inputs(root,'replay')
            with self.assertRaisesRegex(sources.CoverageError,'SOURCE_BODY_MISMATCH'):replay.request('https://api.sleeper.app/test')
            with self.assertRaises(sources.CoverageError):replay.finish()

    def test_uninstrumented_request_is_blocked_even_if_caught(self):
        import requests
        with tempfile.TemporaryDirectory()as d:
            module=SimpleNamespace(get_json=lambda*a,**k:{})
            record=sources.Inputs(Path(d)/'inputs','record',fetch=module.get_json)
            with record.install(module,[]):
                try:requests.get('https://api.sleeper.app/uncovered')
                except Exception:pass
            with self.assertRaisesRegex(sources.CoverageError,'UNINSTRUMENTED_NETWORK_REQUEST'):record.finish()

    def test_other_endpoint_and_resource_overflow_fail_closed(self):
        with tempfile.TemporaryDirectory()as d:
            record=sources.Inputs(Path(d)/'inputs','record',fetch=lambda*a,**k:{})
            with self.assertRaisesRegex(sources.CoverageError,'SOURCE_ENDPOINT_SCOPE'):record.request('https://example.invalid/no')
        with tempfile.TemporaryDirectory()as d,patch.object(sources,'MAX_RESPONSE',2):
            record=sources.Inputs(Path(d)/'inputs','record',fetch=lambda*a,**k:{'fgm':3})
            with self.assertRaisesRegex(sources.CoverageError,'SOURCE_RESPONSE_BOUND'):record.request('https://api.sleeper.app/test')

if __name__=='__main__':unittest.main()
