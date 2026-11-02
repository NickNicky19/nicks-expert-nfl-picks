"""Actual original/current builders in independent subprocesses; no providers."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import classic_build_pair_v1 as pair
import classic_model_v1 as model

class ActualBuildPairTests(unittest.TestCase):
    def assert_workflow_feed_policy(self,workflow,*,candidate_policy=None):
        import shlex
        commands=[shlex.split(line.strip()[5:])for line in workflow.splitlines()
                  if line.strip().startswith('run: python tools/weekly_adaptive_overlay.py ')]
        self.assertEqual(len(commands),1)
        command=commands[0]
        path=command[command.index('--feed-policy')+1]
        schemas={'config/weekly-derived-selected-policy-v3.json':'weekly-derived-selected-policy-v3',
                 'config/weekly-derived-selected-policy-v4.json':'weekly-derived-selected-policy-v4',
                 'config/weekly-derived-selected-policy-v5.json':'weekly-derived-selected-policy-v4',
                 'config/weekly-derived-selected-policy-v6.json':'weekly-derived-selected-policy-v4'}
        self.assertIn(path,schemas)
        body=(ROOT/path).read_bytes()if candidate_policy is None else candidate_policy
        self.assertEqual(command[command.index('--feed-policy-sha256')+1],hashlib.sha256(body).hexdigest())
        value=json.loads(body)
        self.assertEqual(value['schema_version'],schemas[path])
        if path.endswith('-v3.json'):
            import weekly_public_feed as feed
            feed.policy_check_v3(value,root=ROOT)
            self.assertEqual(value['historical_policy_sha256'],feed.HISTORICAL_POLICY_SHA256)
        else:
            import weekly_public_feed_v4 as feed
            feed.policy_check(value,root=ROOT)
            self.assertIn('tools/weekly_public_feed_v4.py',value['website_code_sha256'])
        self.assertEqual(value['current_execution'],model.contract(ROOT))

    def test_workflow_installs_pair_before_current_policy_and_publishes_both_lanes(self):
        import re
        workflow=(ROOT/'.github/workflows/hourly.yml').read_text()
        commands=[line.strip()for line in workflow.splitlines()if 'run:'in line]
        stage=next(i for i,line in enumerate(commands)if 'classic_build_pair_v1.py'in line and '--install-staged-output'not in line)
        install=next(i for i,line in enumerate(commands)if '--install-staged-output'in line)
        capture=next(i for i,line in enumerate(commands)if 'tools/reliability.py'in line)
        feed=next(i for i,line in enumerate(commands)if 'tools/weekly_adaptive_overlay.py'in line)
        self.assertLess(stage,install);self.assertLess(install,capture);self.assertLess(capture,feed)
        self.assertEqual(commands[capture].count('--model '),1)
        self.assertIn('--model '+model.MODEL,commands[capture])
        self.assertIn('--mode live',commands[stage]);self.assertNotIn('--refresh',commands[stage])
        self.assert_workflow_feed_policy(workflow)
        self.assertIn('data/current-classic data/classic-r0-shadow',workflow)
        for operation in ['begin','sealed','check --stage upload','check --stage deploy','check --stage retry','check --stage postdeploy']:
            self.assertIn('tools/publication_guard_v1.py '+operation,workflow)

    def test_explicit_v4_workflow_branch_requires_new_schema_scope_and_physical_policy(self):
        from test_weekly_public_feed_v4 import fixture
        p,*_=fixture();body=json.dumps(p,sort_keys=True,separators=(',',':')).encode()
        import re
        actual=(ROOT/'.github/workflows/hourly.yml').read_text()
        candidate,count=re.subn(r'--feed-policy \S+ --feed-policy-sha256 [a-f0-9]{64}',
            '--feed-policy config/weekly-derived-selected-policy-v4.json --feed-policy-sha256 '+hashlib.sha256(body).hexdigest(),actual)
        self.assertEqual(count,1)
        self.assert_workflow_feed_policy(candidate,candidate_policy=body)
        with self.assertRaises(AssertionError):
            self.assert_workflow_feed_policy(candidate.replace(hashlib.sha256(body).hexdigest(),'0'*64),candidate_policy=body)
        with self.assertRaises(AssertionError):
            self.assert_workflow_feed_policy(candidate.replace('-policy-v4.json','-policy-v3.json'),candidate_policy=body)
        p['website_code_sha256'].pop('tools/weekly_public_feed_v4.py')
        invalid=json.dumps(p,sort_keys=True,separators=(',',':')).encode()
        candidate=candidate.replace(hashlib.sha256(body).hexdigest(),hashlib.sha256(invalid).hexdigest())
        with self.assertRaises(ValueError):self.assert_workflow_feed_policy(candidate,candidate_policy=invalid)

    def test_v4_unregistered_template_cannot_activate_actual_workflow_branch(self):
        import re
        import weekly_public_feed_v4 as feed
        template=feed.template(ROOT)
        self.assertEqual(template['state'],'PREPARED_UNREGISTERED')
        body=json.dumps(template,sort_keys=True,separators=(',',':')).encode()
        workflow,count=re.subn(r'--feed-policy \S+ --feed-policy-sha256 [a-f0-9]{64}',
            '--feed-policy config/weekly-derived-selected-policy-v4.json --feed-policy-sha256 '+hashlib.sha256(body).hexdigest(),
            (ROOT/'.github/workflows/hourly.yml').read_text())
        self.assertEqual(count,1)
        with self.assertRaisesRegex(ValueError,'V4_ROOT_REGISTRATION_REQUIRED'):
            self.assert_workflow_feed_policy(workflow,candidate_policy=body)

    def test_original_deployed_default_and_no_refresh_override(self):
        import ast
        repository=Path(os.environ.get('NFL_ORIGINAL_REPOSITORY',ROOT))
        workflow=pair.original_blob(repository,'.github/workflows/hourly.yml').decode()
        self.assertIn('run: python pull/build.py\n',workflow)
        self.assertNotIn('pull/build.py --refresh',workflow)
        calls=[node for node in ast.walk(ast.parse((ROOT/'tools/classic_build_pair_v1.py').read_text()))
               if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)and isinstance(node.func.value,ast.Name)
               and node.func.value.id=='build'and node.func.attr=='run']
        self.assertTrue(calls)
        self.assertTrue(all(not call.args and not call.keywords for call in calls))

    def source(self,root):
        source=root/'source';source.mkdir()
        for name in ['pull','tools','config','schemas']:
            shutil.copytree(ROOT/name,source/name,ignore=shutil.ignore_patterns('__pycache__'))
        (source/'output/data').mkdir(parents=True)
        (source/'data/cache').mkdir(parents=True)
        from classic_fixture_transport import ROWS
        legacy={row['player_id']:dict(team=row['team'],opp=row['opponent'],stats={key:value for key,value in row['stats'].items()if key!='fgm'})for row in ROWS}
        (source/'data/cache/stats_2098_01.json').write_text(json.dumps(legacy,sort_keys=True)+'\n')
        (source/'data/forward/2098/w01').mkdir(parents=True)
        (source/'data/forward/2098/w01/fictional-original.json.gz').write_bytes(gzip.compress(b'{"fictional_original_receipt":true}',mtime=0))
        (source/'output/data/track_record.json').write_bytes(b'{"grading_version":"statistical-v2","weeks":[]}\n')
        return source

    def run_fixture(self,root,source,run):
        bootstrap=root/'bootstrap';bootstrap.mkdir(exist_ok=True)
        (bootstrap/'sitecustomize.py').write_text('from classic_fixture_transport import install\ninstall()\n')
        repository=Path(os.environ.get('NFL_ORIGINAL_REPOSITORY',ROOT))
        environment=dict(PYTHONPATH=str(bootstrap)+os.pathsep+str(ROOT/'tests'),CLASSIC_FIXTURE_COUNTER=str(root/'transport-count.txt'))
        # Data is wholly fictional; the original code objects are independently
        # read from real 89512ed. The exporter has its own real Git test below.
        def fixture_state(repository,target):
            for lane in ['output/data','data/cache']:pair.copy_tree(source/lane,target/lane)
        with patch.dict(os.environ,environment),patch.object(pair,'export_original_state',side_effect=fixture_state):
            return pair.run_pair(source,run,repository,mode='replay')

    def test_bootstrap_state_uses_exact_git_objects(self):
        import subprocess
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);repo=root/'git';repo.mkdir()
            def git(*a):return subprocess.check_output(['git','-C',str(repo),*a],stderr=subprocess.DEVNULL).decode().strip()
            git('init','-b','main');git('config','user.name','Fictional');git('config','user.email','fictional@example.invalid')
            (repo/'data/cache').mkdir(parents=True);(repo/'output/data').mkdir(parents=True)
            (repo/'data/cache/stats_2098_01.json').write_text('{"fictional":1}')
            (repo/'output/data/week.json').write_text('{"fictional_original_board":1}')
            git('add','.');git('commit','-m','Fictional original state');sha=git('rev-parse','HEAD')
            with patch.object(pair,'ORIGINAL_SOURCE',sha):pair.export_original_state(repo,root/'export')
            self.assertEqual((root/'export/data/cache/stats_2098_01.json').read_bytes(),(repo/'data/cache/stats_2098_01.json').read_bytes())
            self.assertEqual((root/'export/output/data/week.json').read_bytes(),(repo/'output/data/week.json').read_bytes())

    def test_actual_default_original_then_current_with_qualified_history_extension(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);source=self.source(root);run=root/'private'
            before={p.relative_to(source).as_posix():p.read_bytes()for p in source.rglob('*')if p.is_file()}
            result=self.run_fixture(root,source,run)
            old=json.loads((run/'original/output/data/week.json').read_bytes())
            new=json.loads((run/'current/output/data/week.json').read_bytes())
            self.assertNotIn('execution_model',old);self.assertEqual(new['execution_model']['model'],model.MODEL)
            self.assertEqual(old['games'][0]['ours']['spread'],8.8)
            self.assertEqual(new['games'][0]['ours']['spread'],1.0)
            workers=[json.loads((run/lane/'WORKER.json').read_bytes())for lane in ['original','current']]
            self.assertEqual(workers[0]['source_inputs']['input_index_sha256'],workers[1]['source_inputs']['parent_index_sha256'])
            self.assertFalse(result['complete_input_sets_identical'])
            self.assertEqual(workers[1]['source_inputs']['additional_requests'],1)
            self.assertEqual(workers[0]['procedure'],'original-builder-default-refresh-v1')
            self.assertTrue(all(not event['refresh']for event in workers[0]['cache_events']if event['season']==2098))
            self.assertEqual(workers[0]['normalized_fgm_presence']['projections']['2099:2']['fgm_present'],0)
            self.assertEqual(workers[1]['normalized_fgm_presence']['projections']['2099:2']['fgm_present'],2)
            self.assertEqual(workers[0]['normalized_fgm_presence']['stats']['2098:1']['fgm_present'],0)
            self.assertEqual(workers[1]['normalized_fgm_presence']['stats']['2098:1']['fgm_present'],2)
            calls=(root/'transport-count.txt').read_text().splitlines()
            self.assertEqual(len(calls),workers[0]['source_inputs']['recorded_requests']+workers[1]['source_inputs']['additional_requests'])
            for lane,expected in [('original',model.ORIGINAL_MODEL),('current',model.MODEL)]:
                info=json.loads((run/lane/'WORKER.json').read_bytes())
                payload=json.loads(gzip.decompress((run/lane/info['native_receipt']).read_bytes()))['payload']
                self.assertEqual(payload['model'],expected)
            self.assertEqual((source/'data/cache/stats_2098_01.json').read_bytes(),before['data/cache/stats_2098_01.json'])
            self.assertEqual((source/'output/data/track_record.json').read_bytes(),before['output/data/track_record.json'])
            for name,raw in before.items():self.assertEqual((source/name).read_bytes(),raw,name)
            self.assertFalse((source/'.git').exists())
            self.assertFalse(result['source_checkout_written']);self.assertFalse(result['deployed'])
            # Simulate data-only workflow installation on this fictional copy.
            installed=pair.install_pair_outputs(source,run)
            self.assertFalse(installed['git_published']);self.assertFalse(installed['deployed'])
            self.assertEqual((source/'data/cache/stats_2098_01.json').read_bytes(),before['data/cache/stats_2098_01.json'])
            preserved=source/'output/data/grading-history'/(hashlib.sha256(before['output/data/track_record.json']).hexdigest()+'.json')
            self.assertEqual(preserved.read_bytes(),before['output/data/track_record.json'])
            self.assertTrue((source/'data/classic-r0-shadow/latest.json').exists())
            self.assertFalse((source/'inputs').exists())
            # A later run discovers the preserved original previous board;
            # copied current-model output cannot become original shadow state.
            next_root=root/'private-second'
            repository=Path(os.environ.get('NFL_ORIGINAL_REPOSITORY',ROOT))
            pair.seed(source,next_root,repository)
            previous=json.loads((next_root/'original/output/data/week.json').read_bytes())
            self.assertNotIn('execution_model',previous)
            self.assertEqual(previous['games'][0]['ours']['spread'],8.8)
            self.assertEqual((next_root/'original/data/cache/stats_2098_01.json').read_bytes(),before['data/cache/stats_2098_01.json'])
            print(json.dumps(dict(actual_pair='PASS',original_spread=8.8,current_spread=1.0,
                original_recorded_requests=workers[0]['source_inputs']['recorded_requests'],
                corrected_history_extension_requests=workers[1]['source_inputs']['additional_requests'],
                actual_HTTP_requests=0,original_procedure='default_refresh',model=model.MODEL)))

    def test_missing_original_objects_stops_before_any_staging(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);source=self.source(root);run=root/'private'
            with self.assertRaises(Exception):pair.seed(source,run,root/'absent-repository')
            self.assertFalse(run.exists())

    def test_current_board_cannot_bootstrap_an_original_shadow(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);source=self.source(root)
            (source/'output/data/week.json').write_text(json.dumps(dict(execution_model=model.contract(source))))
            with self.assertRaisesRegex(ValueError,'PRIOR_ORIGINAL_R0_STATE_REQUIRED'):
                pair.seed(source,root/'private',root/'unused-repository')

if __name__=='__main__':unittest.main()
