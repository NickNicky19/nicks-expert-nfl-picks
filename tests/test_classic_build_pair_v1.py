"""Actual original/current builders in independent subprocesses; no providers."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import classic_build_pair_v1 as pair
import classic_model_v1 as model


def retained_classic_source(target):
    """Real closed Classic1 source, not today's code wearing its old label."""
    target = Path(target)
    repository = Path(os.environ.get('NFL_ORIGINAL_REPOSITORY', ROOT))
    source = model.SCORING_SOURCE
    command = ['git', '--no-replace-objects', '--no-lazy-fetch', '-C', str(repository)]
    entries = subprocess.check_output([*command, 'ls-tree', '-r', '-z', source,
                                       '--', 'pull', 'tools', 'config', 'schemas']).split(b'\0')
    count = 0
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        name = name.decode()
        if mode != '100644' or kind != 'blob' or '..' in Path(name).parts:
            raise AssertionError('Unexpected retained source entry')
        raw = subprocess.check_output([*command, 'cat-file', 'blob', oid])
        if len(raw) > 2 << 20 or hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != oid:
            raise AssertionError('Retained source blob identity')
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        count += 1
    if not count:
        raise AssertionError('Retained Classic1 source required')
    if model.contract(target) != model.execution_contract():
        raise AssertionError('Retained Classic1 contract changed')
    return target


class ActualBuildPairTests(unittest.TestCase):
    def test_workflow_separates_current_capture_from_retained_legacy_pair(self):
        import re
        workflow=(ROOT/'.github/workflows/hourly.yml').read_text()
        starts=list(re.finditer(r'(?m)^      - (?:name:|uses:)',workflow))
        blocks=[workflow[start.start():starts[i+1].start()if i+1<len(starts)else len(workflow)]for i,start in enumerate(starts)]
        def block(name):
            return next((i,value)for i,value in enumerate(blocks)if value.startswith('      - name: '+name+'\n'))
        stage,build=block('Build accepted versioned production engine')
        install,installed=block('Install validated data without changing source or old R0 caches')
        capture,captured=block('Required integrity checks and pregame capture')
        feed,overlay=block('Prepare isolated provisional overlay (default R0)')
        self.assertLess(stage,install);self.assertLess(install,capture);self.assertLess(capture,feed)
        self.assertIn("if [ '${{ steps.mode.outputs.phase2_enabled }}' = 'true' ]; then",build)
        self.assertLess(build.index('python tools/phase2_capture.py --mode live --build-and-capture'),build.index('elif '))
        self.assertGreater(build.index('python tools/classic_build_pair_v1.py'),build.index('elif '))
        self.assertIn('--mode live',build);self.assertNotIn('--refresh',build)
        self.assertIn('python tools/phase2_capture.py --mode live --validate-generation',installed)
        self.assertIn('--install-staged-output',installed)
        self.assertIn('python tools/phase2_capture.py --mode live --validate-generation',captured)
        self.assertEqual(captured.count('--model '),1)
        self.assertIn('--model '+model.MODEL,captured)
        self.assertIn("steps.mode.outputs.phase2_enabled != 'true'",overlay)
        # This separate recovery branch retains its old policy/source binding;
        # current Phase2 publication is validated inside the coherent stage.
        policy=subprocess.check_output(['git','--no-replace-objects','--no-lazy-fetch','-C',str(ROOT),'show',
            model.SCORING_SOURCE+':config/weekly-derived-selected-policy-v3.json'])
        self.assertIn('--feed-policy config/weekly-derived-selected-policy-v3.json --feed-policy-sha256 '+hashlib.sha256(policy).hexdigest(),overlay)
        self.assertIn('data/current-classic data/classic-r0-shadow',workflow)
        for operation in ['begin','sealed','check --stage upload','check --stage deploy','check --stage retry','check --stage postdeploy']:
            self.assertIn('tools/publication_guard_v1.py '+operation,workflow)

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
        source=retained_classic_source(root/'source')
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
            # Replay uses retained engine/helper bytes. Do not carry the CI
            # runner's current-source SHA into this historical test capture.
            os.environ.pop('GITHUB_SHA',None)
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
