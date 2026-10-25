"""Real local Git races, fictional website bytes/context; no provider or GitHub I/O."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

SPEC=importlib.util.spec_from_file_location('publication_guard',Path(__file__).resolve().parents[1]/'tools/publication_guard_v1.py')
f=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(f)


class PublicationFenceTests(unittest.TestCase):
    def git(self,*args,root=None):
        return subprocess.check_output(['git',*args],cwd=root or self.root,stderr=subprocess.DEVNULL,text=True).strip()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'work';self.root.mkdir()
        self.origin=self.base/'origin.git'
        self.git('init','--bare',str(self.origin))
        self.git('init','--initial-branch=main')
        self.git('config','user.name','Fictional Audit');self.git('config','user.email','fictional@example.invalid')
        (self.root/'output/data').mkdir(parents=True)
        (self.root/'output/data/week.json').write_text('{"fictional":1}')
        (self.root/'output/app.js').write_text('/* fictional */')
        self.git('add','.');self.git('commit','-m','fictional initial')
        self.git('remote','add','origin',str(self.origin));self.git('push','-u','origin','main')
        source=self.git('rev-parse','HEAD')
        self.env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY=f.REPOSITORY,GITHUB_REF='refs/heads/main',
            GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_RUN_ID='12345',GITHUB_RUN_ATTEMPT='1',
            GITHUB_SHA=source,GITHUB_WORKFLOW_SHA=source)
        self.receipt=self.base/'fence.json'

    def advance_elsewhere(self):
        other=self.base/'other';self.git('clone','-b','main',str(self.origin),str(other))
        self.git('config','user.name','Other Fictional Writer',root=other)
        self.git('config','user.email','fictional@example.invalid',root=other)
        (other/'output/app.js').write_text('/* newer source */')
        self.git('add','.',root=other);self.git('commit','-m','newer legitimate source',root=other)
        self.git('push','origin','main',root=other)

    def publish_generated(self):
        (self.root/'output/data/week.json').write_text('{"fictional":2}')
        self.git('add','output/data');self.git('commit','-m','generated data');self.git('push','origin','main')

    def test_real_commit_push_and_all_publication_stages(self):
        f.begin(self.root,self.receipt,self.env);self.publish_generated()
        result=f.sealed(self.root,self.receipt,self.env)
        self.assertEqual(result['published_head_sha'],self.git('rev-parse','HEAD'))
        for stage in ['upload','deploy','retry','postdeploy']:
            self.assertEqual(f.check(self.root,self.receipt,self.env,stage)['files'],2)
        before=self.receipt.with_suffix('.published.json').read_bytes()
        f.sealed(self.root,self.receipt,self.env)
        self.assertEqual(self.receipt.with_suffix('.published.json').read_bytes(),before)

    def test_old_trigger_is_rejected_without_fast_forwarding_its_source(self):
        before=self.git('rev-parse','HEAD');self.advance_elsewhere()
        with self.assertRaisesRegex(f.FenceError,'STALE_TRIGGER_OR_CHECKOUT'):f.begin(self.root,self.receipt,self.env)
        self.assertEqual(self.git('rev-parse','HEAD'),before)
        self.assertFalse(self.receipt.exists())

    def test_different_workflow_source_rejected(self):
        with self.assertRaisesRegex(f.FenceError,'GENUINE_MATCHED_WORKFLOW_CONTEXT'):
            f.begin(self.root,self.receipt,dict(self.env,GITHUB_WORKFLOW_SHA='0'*40))

    def test_new_main_after_push_is_rejected_at_every_later_stage(self):
        f.begin(self.root,self.receipt,self.env);self.publish_generated();f.sealed(self.root,self.receipt,self.env)
        self.advance_elsewhere()
        for stage in ['upload','deploy','retry','postdeploy']:
            with self.subTest(stage=stage),self.assertRaisesRegex(f.FenceError,'SUPERSEDED_BEFORE_'+stage.upper()):
                f.check(self.root,self.receipt,self.env,stage)

    def test_source_changes_cannot_pose_as_generated_data(self):
        f.begin(self.root,self.receipt,self.env)
        (self.root/'output/app.js').write_text('/* changed source */')
        self.git('add','.');self.git('commit','-m','unexpected source');self.git('push','origin','main')
        with self.assertRaisesRegex(f.FenceError,'GENERATED_COMMIT_CHANGED_SOURCE'):f.sealed(self.root,self.receipt,self.env)

    def test_uncommitted_or_extra_upload_bytes_are_rejected(self):
        f.begin(self.root,self.receipt,self.env);f.sealed(self.root,self.receipt,self.env)
        (self.root/'output/app.js').write_text('/* tampered */')
        with self.assertRaisesRegex(f.FenceError,'CLEAN_COMMITTED_OUTPUT_REQUIRED'):
            f.check(self.root,self.receipt,self.env,'upload')
        self.git('restore','output/app.js')
        (self.root/'output/partial.tmp').write_text('unfinished')
        with self.assertRaisesRegex(f.FenceError,'UNTRACKED_OR_SPECIAL_OUTPUT'):
            f.check(self.root,self.receipt,self.env,'upload')

    def test_symlink_and_conflicting_receipt_never_overwrite(self):
        f.begin(self.root,self.receipt,self.env);first=self.receipt.read_bytes()
        with self.assertRaisesRegex(f.FenceError,'IMMUTABLE_FENCE_CONFLICT'):f.create(self.receipt,{'different':True})
        self.assertEqual(self.receipt.read_bytes(),first)
        (self.root/'output/alias').symlink_to('app.js')
        with self.assertRaisesRegex(f.FenceError,'OUTPUT_SYMLINK'):f.inventory(self.root)

    def test_classic_derived_capture_and_shadow_pass_all_fences(self):
        f.begin(self.root,self.receipt,self.env)
        names=['data/current-classic/2099/w02/'+('a'*64)+'.json.gz',
               'data/classic-r0-shadow/latest.json',
               *['data/classic-r0-shadow/'+('b'*64)+'/'+suffix for suffix in
                 ['PAIR.json','ORIGINAL_SOURCE.json','native.json.gz','state/output/data/week.json',
                  'state/output/data/archive/2098_w01.json','state/data/cache/stats_2098_01.json']]]
        for name in names:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('FICTIONAL DERIVED')
        self.git('add','data');self.git('commit','-m','fictional derived captures');self.git('push','origin','main')
        f.sealed(self.root,self.receipt,self.env)
        for stage in ['upload','deploy','retry','postdeploy']:f.check(self.root,self.receipt,self.env,stage)

    def test_shadow_response_corpus_and_mutation_are_rejected(self):
        prefix='data/classic-r0-shadow/'+('b'*64)+'/'
        for suffix in ['inputs/INDEX.json',('a'*64)+'.json','original.log','state/data/cache/response.json']:
            with self.subTest(suffix=suffix):
                from unittest.mock import patch
                with patch.object(f,'git',return_value=('A\0'+prefix+suffix+'\0').encode()),self.assertRaises(f.FenceError):
                    f.classic_generated(self.root,'source','head')
        from unittest.mock import patch
        for name in [prefix+'PAIR.json','data/current-classic/2099/w02/'+('a'*64)+'.json.gz']:
            for status in ['M','D']:
                with self.subTest(name=name,status=status),patch.object(f,'git',return_value=(status+'\0'+name+'\0').encode()),self.assertRaises(f.FenceError):
                    f.classic_generated(self.root,'source','head')

    def pages_copy(self):
        runner=self.base/'runner';runner.mkdir()
        pages=runner/'nfl-pages';shutil.copytree(self.root/'output',pages)
        env=dict(self.env,RUNNER_TEMP=str(runner))
        f.begin(self.root,self.receipt,env);f.sealed(self.root,self.receipt,env)
        return pages,env

    def test_fresh_pages_copy_is_bound_and_checked_at_every_boundary(self):
        pages,env=self.pages_copy()
        result=f.bind_pages(self.root,self.receipt,env,pages)
        self.assertEqual(result['files'],2)
        before=self.receipt.with_suffix('.pages.json').read_bytes()
        for stage in ('upload','deploy','retry','postdeploy'):
            self.assertEqual(f.check(self.root,self.receipt,env,stage,pages_root=pages)['files'],2)
        f.bind_pages(self.root,self.receipt,env,pages)
        self.assertEqual(self.receipt.with_suffix('.pages.json').read_bytes(),before)
        with self.assertRaisesRegex(f.FenceError,'BOUND_PAGES_ROOT_REQUIRED'):
            f.check(self.root,self.receipt,env,'retry')

    def test_same_size_staged_change_with_restored_mtime_is_not_trusted(self):
        pages,env=self.pages_copy();f.bind_pages(self.root,self.receipt,env,pages)
        asset=pages/'app.js';before=asset.stat();raw=asset.read_bytes()
        asset.write_bytes(raw.replace(b'fictional',b'fictionAl'));os.utime(asset,ns=(before.st_atime_ns,before.st_mtime_ns))
        for stage in ('upload','deploy','retry','postdeploy'):
            with self.subTest(stage=stage),self.assertRaisesRegex(f.FenceError,'STAGED_PAGES_CHANGED_AFTER_BINDING'):
                f.check(self.root,self.receipt,env,stage,pages_root=pages)
        self.assertEqual((self.root/'output/app.js').read_bytes(),raw)

    def test_new_missing_and_symlink_staged_assets_are_rejected(self):
        pages,env=self.pages_copy();f.bind_pages(self.root,self.receipt,env,pages)
        added=pages/'extra.json';added.write_text('{}')
        with self.assertRaisesRegex(f.FenceError,'STAGED_PAGES_CHANGED_AFTER_BINDING'):
            f.check(self.root,self.receipt,env,'upload',pages_root=pages)
        added.unlink();raw=(pages/'app.js').read_bytes();(pages/'app.js').unlink()
        with self.assertRaisesRegex(f.FenceError,'STAGED_PAGES_CHANGED_AFTER_BINDING'):
            f.check(self.root,self.receipt,env,'upload',pages_root=pages)
        (pages/'app.js').write_bytes(raw);(pages/'alias').symlink_to('app.js')
        with self.assertRaisesRegex(f.FenceError,'PAGES_ASSET_SYMLINK'):
            f.check(self.root,self.receipt,env,'upload',pages_root=pages)

    def test_staged_namespace_and_genuine_main_advance_remain_checked(self):
        pages,env=self.pages_copy()
        with self.assertRaisesRegex(f.FenceError,'EXACT_RUNNER_PAGES_NAMESPACE_REQUIRED'):
            f.bind_pages(self.root,self.receipt,env,self.root/'output')
        f.bind_pages(self.root,self.receipt,env,pages);self.advance_elsewhere()
        with self.assertRaisesRegex(f.FenceError,'SUPERSEDED_BEFORE_RETRY'):
            f.check(self.root,self.receipt,env,'retry',pages_root=pages)


class FailurePublicationTests(unittest.TestCase):
    """Exercise the real failure-step shell against a local bare Git remote."""
    git=PublicationFenceTests.git
    advance_elsewhere=PublicationFenceTests.advance_elsewhere

    def setUp(self):
        PublicationFenceTests.setUp(self)
        self.source_root=Path(__file__).resolve().parents[1]
        (self.root/'tools').mkdir()
        for name in ['classic_failure_v1.py','classic_model_v1.py','publication_guard_v1.py']:
            shutil.copyfile(self.source_root/'tools'/name,self.root/'tools'/name)
        self.git('add','tools');self.git('commit','-m','fictional failure helper source');self.git('push','origin','main')
        self.source=self.git('rev-parse','HEAD')
        self.env.update(GITHUB_SHA=self.source,GITHUB_WORKFLOW_SHA=self.source)
        self.runner=self.base/'runner';self.runner.mkdir()
        self.receipt=self.runner/'publication-fence-12345-1.json'
        f.begin(self.root,self.receipt,self.env)
        self.environment=dict(os.environ,**self.env,RUNNER_TEMP=str(self.runner),RUN_OUTCOME='failure',
                              PAIR_OUTCOME='failure',PYTHONDONTWRITEBYTECODE='1')
        for name in ['GH_TOKEN','GITHUB_TOKEN','GIT_INDEX_FILE']:
            self.environment.pop(name,None)
        workflow=(self.source_root/'.github/workflows/hourly.yml').read_text()
        step=workflow.split('      - name: Preserve terminal failures without publishing a partial forecast\n',1)[1]
        self.command=textwrap.dedent(step.split('        run: |\n',1)[1])

    def execute_failure(self):
        return subprocess.run(['bash','-e','-o','pipefail','-c',self.command],cwd=self.root,
                              env=self.environment,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)

    def verify_only_failure_was_published(self,main_before):
        self.assertEqual(self.git('rev-parse','refs/heads/main',root=self.origin),main_before)
        ref='refs/heads/audit-failures/classic-12345-1'
        commit=self.git('rev-parse',ref,root=self.origin)
        self.assertEqual(self.git('rev-parse',commit+'^',root=self.origin),self.source)
        names=self.git('diff','--name-only',self.source,commit,root=self.origin).splitlines()
        self.assertTrue(names)
        self.assertTrue(all(name.startswith('data/classic-failures/12345-1/')for name in names))
        self.assertEqual(self.git('show',commit+':output/data/week.json',root=self.origin),'{"fictional":1}')
        restored=self.runner/'classic-failure-restored-12345-1/data/classic-failures/12345-1/FAILED.json'
        self.assertTrue(restored.is_file())
        import json
        document=json.loads(restored.read_bytes())
        self.assertEqual(document['state'],'FAILED_ATTEMPT_RETAINED')
        self.assertIs(document['successful_forecast'],False)
        self.assertIs(document['failure_record_publishes_forecasts'],False)
        return commit

    def test_failure_never_commits_previously_staged_partial_output(self):
        (self.root/'output/data/week.json').write_text('{"fictional_partial":true}')
        self.git('add','output/data/week.json')
        result=self.execute_failure()
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.verify_only_failure_was_published(self.source)
        self.assertIn('output/data/week.json',self.git('diff','--cached','--name-only'))
        self.assertEqual((self.root/'output/data/week.json').read_text(),'{"fictional_partial":true}')

    def test_failure_remains_durable_when_main_legitimately_advances(self):
        self.advance_elsewhere()
        main=self.git('rev-parse','refs/heads/main',root=self.origin)
        result=self.execute_failure()
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.verify_only_failure_was_published(main)


if __name__=='__main__':unittest.main()
