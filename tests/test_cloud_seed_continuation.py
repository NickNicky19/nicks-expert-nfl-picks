"""Closed continuation controls; tiny Git is real, application calls are mocked.

These are driver regressions, not full admission or a hosted operating result.
The retained full prefix must still be replayed in the actual isolated job.
"""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE/'tools'))
import cloud_seed_prepare as p
import seed_checkpoint_frontier as f
import source_ci as ci


class Invocation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.args=SimpleNamespace(continue_checkpoint=True,integrity=CODE/'tools/cloud-seed-integrity.json')
        self.env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',
            GITHUB_REPOSITORY_ID='1411185749',GITHUB_ACTOR_ID='208912933',
            GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_RUN_ATTEMPT='1',
            GITHUB_REF='refs/heads/upgrade/phase2-reproducible-comparison',
            CONTINUATION_ID=p.CONTINUATION_ID,GITHUB_RUN_ID='123',RUNNER_TEMP=str(self.root))
        self.identity=dict(head='a'*40,tree='b'*40)
        self.current=dict(id=123,head_sha=self.identity['head'],run_attempt=1,event='workflow_dispatch',
            workflow_id=392359637,actor=dict(id=208912933),status='in_progress')

    def tearDown(self):self.tmp.cleanup()

    def test_original_invocation_needs_no_continuation_environment(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertIsNone(p.continuation_path(SimpleNamespace()))
            self.assertIsNone(p.continuation_path(SimpleNamespace(continue_checkpoint=False)))

    def test_exact_run_path(self):
        with patch.dict(os.environ,self.env,clear=True):
            self.assertEqual(p.continuation_path(self.args),self.root/'nfl-seed-frontier-123')

    def test_unknown_actor_ref_mode_or_attempt_rejected(self):
        for k,v in dict(GITHUB_ACTOR_ID='1',GITHUB_REF='refs/heads/main',GITHUB_RUN_ATTEMPT='2',
            CONTINUATION_ID='old-preparation',GITHUB_EVENT_NAME='push',GITHUB_REPOSITORY_ID='1').items():
            with self.subTest(k=k),patch.dict(os.environ,{**self.env,k:v},clear=True),self.assertRaises(RuntimeError):
                p.continuation_path(self.args)

    def test_noncanonical_run_identity_rejected(self):
        for v in ('0','00123','-1','１２３','not-an-id'):
            with self.subTest(v=v),patch.dict(os.environ,{**self.env,'GITHUB_RUN_ID':v},clear=True),self.assertRaises(RuntimeError):
                p.continuation_path(self.args)

    def test_checkpoint_symlink_rejected(self):
        (self.root/'nfl-seed-frontier-123').symlink_to(self.root,target_is_directory=True)
        with patch.dict(os.environ,self.env,clear=True),self.assertRaises(RuntimeError):p.continuation_path(self.args)

    def retrieve(self,rows,current=None):
        calls=[]
        def get(path):
            calls.append(path)
            if path=='/actions/runs/123':return current or self.current
            return dict(workflow_runs=rows)
        def receive(path):path.mkdir()
        with patch.dict(os.environ,self.env,clear=True),patch.object(p,'integrity'),\
            patch.object(p,'installed',return_value=self.identity),patch.object(ci,'GitHub',return_value=SimpleNamespace(get=get)),\
            patch.object(f,'hosted'),patch.object(f,'retrieve',side_effect=receive) as download:
            p.retrieve_continuation(self.args)
        return calls,download.call_count

    def test_one_exact_invocation_retrieves_once(self):
        calls,count=self.retrieve([self.current]);self.assertEqual(count,1)
        value=p.load(self.root/'nfl-seed-frontier-123/CONTINUATION_INVOCATION.json')
        self.assertEqual(value['installer'],self.identity);self.assertEqual(value['run_id'],123)
        self.assertEqual(value['mode'],'RETRIEVED_NOT_CONSTRUCTED');self.assertEqual(len(calls),2)

    def test_duplicate_fresh_dispatch_is_rejected_before_download(self):
        with self.assertRaisesRegex(RuntimeError,'Duplicate'):
            self.retrieve([self.current,{**self.current,'id':124}])
        self.assertFalse((self.root/'nfl-seed-frontier-123').exists())

    def test_missing_current_run_is_not_assumed_single_use(self):
        with self.assertRaisesRegex(RuntimeError,'Duplicate'):self.retrieve([])
        self.assertFalse((self.root/'nfl-seed-frontier-123').exists())

    def test_wrong_source_or_actor_and_completed_run_fail(self):
        for bad in ({**self.current,'head_sha':'c'*40},{**self.current,'actor':dict(id=1)},
            {**self.current,'run_attempt':True},{**self.current,'status':'completed'}):
            with self.subTest(bad=bad),self.assertRaisesRegex(RuntimeError,'Unapproved'):
                self.retrieve([bad],bad)

    def test_installed_integrity_closes_new_dependencies(self):
        value=json.loads((CODE/'tools/cloud-seed-integrity.json').read_bytes())
        self.assertEqual(set(value['files']),p.REQUIRED)
        self.assertEqual(value['files']['operating_diagnostic.py'],p.HARNESS)
        self.assertEqual(value['files']['diagnostic-seed-inputs.json'],p.INPUTS)
        for name,digest in value['files'].items():
            self.assertEqual(hashlib.sha256((CODE/'tools'/name).read_bytes()).hexdigest(),digest)


class CopyPrefix(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.checkpoint=self.base/'checkpoint';self.checkpoint.mkdir()
        self.source=self.checkpoint/'committed-frontier';self.source.mkdir()
        self.git('init','-q');self.git('config','user.name','FictionalUnitTest')
        self.git('config','user.email','fictional@example.invalid')
        for name,raw in {'tools/example.py':b'# Fictional unit source\n','config/phase2.json':b'{}',
            'data/verification/original.json.gz':b'actual bytes; no qualification claim'}.items():
            q=self.source/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw)
        for name in ('FICTIONAL_ONLY.json','FICTIONAL_PHASES.json','FICTIONAL_LEGACY_BASELINE.json','FICTIONAL_PARTICIPATION_ADAPTER.json'):
            (self.source/name).write_bytes(b'{"fictional_unit_control":true}')
        self.git('add','.');self.git('commit','-qm','Tiny fictional Git-copy control')
        self.head=self.git('rev-parse','HEAD');self.git('update-ref','refs/fixture/source',self.head)
        (self.checkpoint/'raw-checkpoint').mkdir()
        self.progress=b'{"generation":13,"target":24,"wall_clock":"2026-10-23T14:32:21+00:00"}'
        (self.checkpoint/'raw-checkpoint/CONSTRUCTION_PROGRESS.json').write_bytes(self.progress)
        self.work=self.base/'work';self.work.mkdir()
        p.write(self.work/'PREFLIGHT.json',dict(installer=dict(head='a'*40,tree='b'*40)))
        self.args=SimpleNamespace(app=str(self.base/'app'),work=str(self.work),output=str(self.base/'export'),continue_checkpoint=True)
        self.value=dict(status='COMMITTED_HISTORY_REPLAYED_RAW_RESIDUAL_UNQUALIFIED',fixture_head=self.head,
            recorded_generations=13,independently_replayed_committed_generations=13,target_generations=24,
            generation_sha256=p.PREFIX_GENERATION,semantic_sha256=p.PREFIX_SEMANTICS,
            residual_working_files=dict(new=0,changed=0,missing_from_checkpoint=0))

    def tearDown(self):self.tmp.cleanup()
    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.source),*args],stderr=subprocess.PIPE,text=True).strip()

    def prepare(self,value=None):
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'123'}),patch.object(p,'continuation_path',return_value=self.checkpoint),\
            patch.object(p,'PREFIX_HEAD',self.head),patch.object(f,'check_saved',return_value=value or self.value),\
            patch.object(f,'verify_parents'):
            p.continuation_frontier(self.args)

    def test_actual_independent_git_copy_and_original_progress_preserved(self):
        before=f.tree_inventory(self.source);self.prepare();root=self.work/'construction/root'
        self.assertEqual(f.tree_inventory(root),before);self.assertEqual(f.tree_inventory(self.source),before)
        self.assertFalse((root/'.git/objects/info/alternates').exists())
        self.assertEqual((root.parent/'progress.json').read_bytes(),self.progress)
        self.assertEqual((self.checkpoint/'raw-checkpoint/CONSTRUCTION_PROGRESS.json').read_bytes(),self.progress)
        self.assertEqual(p.load(self.work/'CONTINUATION.json')['first_remaining_generation'],14)

    def test_nonzero_or_missing_residual_fails_without_copy(self):
        for residual in (dict(new=1,changed=0,missing_from_checkpoint=0),dict(new=0,changed=1,missing_from_checkpoint=0),{},None):
            with self.subTest(residual=residual),self.assertRaisesRegex(RuntimeError,'zero-residual'):
                self.prepare({**self.value,'residual_working_files':residual})
        self.assertFalse((self.work/'construction/root').exists())

    def test_wrong_generation_head_or_semantics_fails(self):
        for k,v in dict(fixture_head='c'*40,independently_replayed_committed_generations=12,
            target_generations=23,generation_sha256='c'*64,semantic_sha256='d'*64).items():
            with self.subTest(k=k),self.assertRaisesRegex(RuntimeError,'zero-residual'):self.prepare({**self.value,k:v})

    def test_new_copy_mutation_is_detected_even_with_restored_mtime(self):
        actual=subprocess.run
        def mutate(command,*a,**kw):
            result=actual(command,*a,**kw)
            if 'clone' in command:
                q=self.work/'construction/root/tools/example.py';old=q.stat();q.write_bytes(b'X'*old.st_size)
                os.utime(q,ns=(old.st_atime_ns,old.st_mtime_ns))
            return result
        with patch.object(p.subprocess,'run',side_effect=mutate),self.assertRaisesRegex(RuntimeError,'copy differs'):
            self.prepare()


class UpdateSequence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'fixture';self.root.mkdir()
        self.evidence=self.root/'data/verification/origin.json.gz';self.evidence.parent.mkdir(parents=True)
        self.evidence.write_bytes(b'original immutable control')
        for name in ('FICTIONAL_ONLY.json','FICTIONAL_PHASES.json','FICTIONAL_LEGACY_BASELINE.json','FICTIONAL_PARTICIPATION_ADAPTER.json'):
            (self.root/name).write_bytes(b'{"fictional_unit_control":true}')
        self.board=dict(games=[dict(id='fictional-game',state='in')],contract='frozen')
        self.observations=[];self.commits=[]
        self.h=SimpleNamespace(FULL=dict(games=14,per_team=20,snapshots=277,outcomes=49,generations=24),
            START=datetime(2026,11,6,tzinfo=timezone.utc),SEED_HOUR=77,timedelta=timedelta,patch=__import__('unittest.mock',fromlist=['patch']).patch,
            assert_local_tree=lambda *a:None,external=lambda *a:contextlib.nullcontext(),commit=lambda r:self.commits.append(r),put=p.write)
        class Provider:
            def __init__(inner,m,d,at):inner.at=at;inner.revision=None;self.provider=inner
        self.h.Provider=Provider
        def capture(root,build_first):
            self.assertTrue(build_first);self.observations.append((self.provider.at,self.provider.revision))
        self.capture=SimpleNamespace(validate_generation=lambda r:dict(generation_sha256=p.PREFIX_GENERATION),
            run_capture=capture,_public_archive_commit=lambda *a:None)
        self.modules=dict(rel=SimpleNamespace(load_json=lambda path:copy.deepcopy(self.board),digest=lambda x:x),
            partial=SimpleNamespace(game_contract=lambda board,g:board['contract']),capture=self.capture)
        self.h.bind=lambda root:self.modules

    def tearDown(self):self.tmp.cleanup()

    def test_only_next_eleven_clocks_and_predeclared_revision_are_executed(self):
        value=p.continue_generations(self.root,self.h)
        expected=[(self.h.START+timedelta(hours=77,seconds=5*(i+1)),1) for i in range(13,24)]
        self.assertEqual(self.observations,expected);self.assertEqual(len(self.commits),11)
        self.assertEqual(value['completed_generations'],24);self.assertEqual(value['added_generations'],11)
        self.assertEqual(p.load(self.root.parent/'progress.json')['generation'],24)
        self.assertEqual(self.evidence.read_bytes(),b'original immutable control')

    def test_wrong_copied_saved_generation_fails_before_update(self):
        self.capture.validate_generation=lambda r:dict(generation_sha256='0'*64)
        with self.assertRaisesRegex(RuntimeError,'prefix generation'):p.continue_generations(self.root,self.h)
        self.assertEqual(self.observations,[]);self.assertEqual(self.commits,[])

    def test_changed_dimensions_cannot_lower_the_test(self):
        self.h.FULL={**self.h.FULL,'generations':23}
        with self.assertRaisesRegex(RuntimeError,'dimensions'):p.continue_generations(self.root,self.h)

    def test_new_capture_cannot_replace_original_evidence(self):
        self.capture.run_capture=lambda *a,**kw:self.evidence.write_bytes(b'X'*len(self.evidence.read_bytes()))
        with self.assertRaisesRegex(RuntimeError,'immutable'):p.continue_generations(self.root,self.h)
        self.assertEqual(self.commits,[])

    def test_new_capture_cannot_change_started_contract(self):
        self.capture.run_capture=lambda *a,**kw:self.board.update(contract='changed')
        with self.assertRaisesRegex(RuntimeError,'frozen contract'):p.continue_generations(self.root,self.h)
        self.assertEqual(self.commits,[])

    def test_fictional_phase_and_qualification_markers_remain_immutable(self):
        self.capture.run_capture=lambda *a,**kw:(self.root/'FICTIONAL_PHASES.json').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'immutable'):p.continue_generations(self.root,self.h)
        self.assertEqual(self.commits,[])

    def test_only_known_report_pointers_are_mutable(self):
        for name in ('output/data/selection-grading/latest.json','output/data/selection-grading/hosting.json','data/cache/stats.json'):
            self.assertFalse(p.prefix_immutable(name))
        for name in ('output/data/selection-grading/old/summary.json.gz','data/verification/failed.json',
            'data/forward/native.json.gz','config/phase2.json','tools/engine.py'):
            self.assertTrue(p.prefix_immutable(name))


if __name__=='__main__':unittest.main()
