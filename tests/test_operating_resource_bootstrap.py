"""Pure/mocked root-control regressions, NOT privileged/backend qualification."""
import copy
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT
spec = importlib.util.spec_from_file_location('bootstrap_under_test', ROOT/'tools/operating_resource_bootstrap.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)


def changed_actual_controller_contract(raw):
    start=b'          import datetime as dt, gzip, hashlib, json, math, os, re, resource, signal, stat, subprocess, sys, tarfile, time\n'
    end=b"          if __name__=='__main__':main()\n"
    first,last=raw.index(start),raw.index(end)+len(end)
    block=raw[first:last];changed=block.replace(b.PRESENCE_CONTRACT.encode(),b'genuine-current-production-controller-v9',1)
    if changed==block:raise AssertionError('Actual current controller contract unavailable')
    return raw[:first]+changed+raw[last:]


def args(code=Path('/fictional/code'), **changes):
    value = dict(unit='nfl-operating-123-1.service', memory_max=8*1024**3, uid=1001, gid=1001,
                 run_id=123, sample=1, code=code, critical_path=['/fictional/dependencies'], capability_only=False)
    value.update(changes)
    return SimpleNamespace(**value)


class Arguments(unittest.TestCase):
    def raw(self,sample=1):
        return ['--unit',f'nfl-operating-123-{sample}.service','--memory-max','8589934592',
                '--uid','1001','--gid','1001','--run-id','123','--sample',str(sample),
                '--code','/fictional/code','--critical-path','/fictional/dependencies']
    def test_exact_supported_three_sample_parser(self):
        for sample in (1,2,3):self.assertEqual(b.arguments(self.raw(sample)).sample,sample)
    def test_seed_sample_zero_rejected(self):
        with self.assertRaises(SystemExit):b.arguments(self.raw(0))
    def test_fourth_sample_rejected(self):
        with self.assertRaises(SystemExit):b.arguments(self.raw(4))
    def test_seed_unit_rejected(self):
        raw=self.raw();raw[1]='nfl-seedprep-123.service'
        with self.assertRaisesRegex(RuntimeError,'exact operating'):b.arguments(raw)
    def test_root_worker_rejected(self):
        raw=self.raw();raw[raw.index('--uid')+1]='0'
        with self.assertRaises(RuntimeError):b.arguments(raw)
    def test_timeout_override_not_supported(self):
        with self.assertRaises(SystemExit):b.arguments(self.raw()+['--timeout','18000'])


class Environment(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);self.code=self.root/'code';self.code.mkdir()
        self.prefix=self.root/'fresh-prefix';self.prefix.mkdir()
        self.env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',GITHUB_RUN_ATTEMPT='1',
            GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_REPOSITORY=b.REPOSITORY,GITHUB_REPOSITORY_ID='1411185749',
            GITHUB_ACTOR_ID='208912933',GITHUB_REF_NAME=b.BRANCH,GITHUB_RUN_ID='123',CAMPAIGN_ID=b.CAMPAIGN,
            GITHUB_WORKFLOW_REF=b.REPOSITORY+'/'+b.WORKFLOW+'@refs/heads/'+b.BRANCH,
            GITHUB_SHA='1'*40,GITHUB_WORKSPACE=str(self.code),SEED_MANIFEST_SHA256='a'*64,
            OPERATING_ARTIFACT_APPROVAL_SHA256='b'*64,
            ImageOS='ubuntu24',ImageVersion='FICTIONAL_IMAGE',RUNNER_TEMP=str(self.root),
            PYTHONDONTWRITEBYTECODE='1',PYTHONPYCACHEPREFIX=str(self.prefix),GH_TOKEN='FICTIONAL_READ_TOKEN')
    def check(self,*,startup_safe=True,**changes):
        self.env.update(changes)
        original_stat=Path.stat
        def actual_except_checkout(path,*argv,**kwargs):
            value=original_stat(path,*argv,**kwargs)
            if path==self.code:
                fields=list(value);fields[4]=1001;fields[5]=1001
                return os.stat_result(fields)
            return value
        with patch.dict(os.environ,self.env,clear=True),patch.object(os,'geteuid',return_value=0), \
             patch.object(sys,'dont_write_bytecode',True),patch.object(sys,'pycache_prefix',str(self.prefix)), \
             patch.object(sys,'flags',SimpleNamespace(safe_path=startup_safe)), \
             patch.object(b.pwd,'getpwuid',return_value=SimpleNamespace(pw_gid=1001)), \
             patch.object(Path,'stat',actual_except_checkout):
            b.environment(args(self.code))
            return dict(os.environ)
    def test_valid_environment_and_root_only_git_exception(self):
        env=self.check(GIT_DIR='/untrusted/old',GIT_CONFIG_COUNT='99')
        self.assertNotIn('GIT_DIR',env);self.assertEqual(env['GIT_CONFIG_COUNT'],'1')
        self.assertEqual(env['GIT_CONFIG_VALUE_0'],str(self.code));self.assertEqual(env['ImageVersion'],'FICTIONAL_IMAGE')
    def test_unsafe_root_import_path_stops(self):
        with self.assertRaisesRegex(RuntimeError,'requires -P'):self.check(startup_safe=False)
    def test_capability_needs_no_seed_approval_or_token_and_clears_them(self):
        self.env.pop('SEED_MANIFEST_SHA256');self.env.pop('OPERATING_ARTIFACT_APPROVAL_SHA256');self.env.pop('GH_TOKEN')
        original_args=args
        with patch.dict(globals(),args=lambda code:original_args(code,capability_only=True)):
            result=self.check()
        self.assertNotIn('SEED_MANIFEST_SHA256',result);self.assertNotIn('GH_TOKEN',result)
    def test_campaign_missing_seed_still_rejected(self):
        self.env.pop('SEED_MANIFEST_SHA256')
        with self.assertRaisesRegex(RuntimeError,'Campaign requires'):self.check()
    def test_missing_runner_image_stops(self):
        with self.assertRaisesRegex(RuntimeError,'runtime image'):self.check(ImageVersion='')
    def test_second_attempt_stops(self):
        with self.assertRaises(RuntimeError):self.check(GITHUB_RUN_ATTEMPT='2')
    def test_wrong_workflow_stops(self):
        with self.assertRaises(RuntimeError):self.check(GITHUB_WORKFLOW_REF='wrong')
    def test_unknown_loader_override_stops(self):
        for key in ('PYTHONPATH','LD_PRELOAD','NODE_OPTIONS'):
            with self.subTest(key=key),self.assertRaises(RuntimeError):self.check(**{key:'forbidden'})
            self.env.pop(key,None)
    def test_unrelated_credentials_stop(self):
        with self.assertRaises(RuntimeError):self.check(AWS_SECRET_ACCESS_KEY='FICTIONAL_NEVER_EXPORT')
    def test_nonempty_bytecode_prefix_stops(self):
        (self.prefix/'unexpected.pyc').write_bytes(b'not trusted')
        with self.assertRaisesRegex(RuntimeError,'existing empty'):self.check()


class SourceClosure(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.code=Path(self.directory.name)
        manifest=json.loads((SOURCE/'tools/cloud-seed-integrity.json').read_bytes())
        names=set(b.FILES)|{'tools/'+n for n in manifest['files']}
        for name in names:
            path=self.code/name;path.parent.mkdir(parents=True,exist_ok=True)
            actual=SOURCE/name
            path.write_bytes(actual.read_bytes() if actual.exists() else b'# fictional wrapper/workflow source\n')
        self.objects={name:(self.code/name).read_bytes() for name in names}
    def git(self,code,*argv):
        if argv==('rev-parse','HEAD'):return b'1'*40
        if argv[0]=='rev-parse':return b'2'*40
        name=argv[-1].split(':',1)[1]
        if argv[0]=='cat-file':return str(len(self.objects[name])).encode()
        if argv[0]=='show':return self.objects[name]
        raise AssertionError(argv)
    def check(self):
        with patch.object(b,'__file__',str(self.code/'tools/operating_resource_bootstrap.py')), \
             patch.object(b,'git',side_effect=self.git),patch.dict(os.environ,GITHUB_SHA='1'*40):
            return b.closure(self.code)
    def test_exact_continued_closure_and_all_twelve_helpers(self):
        closure=self.check();self.assertEqual(closure['commit'],'1'*40)
        self.assertEqual(closure['files']['tools/operating_diagnostic.py']['sha256'],b.P5)
        self.assertEqual(closure['files']['tools/diagnostic_resources.py']['sha256'],b.RESOURCE)
        self.assertIn('tools/operating_campaign.py',closure['files'])
        for name in b.SEED_CONTRACTS[b.CONTINUED_SEED_INTEGRITY]:
            self.assertIn('tools/'+name,closure['files'])
        self.assertEqual(len(b.SEED_CONTRACTS[b.CONTINUED_SEED_INTEGRITY]),12)
    def test_exact_retained_original_nine_file_contract(self):
        # Read actual public historical bytes, not today's driver wearing its
        # original schema name. Git access here is local and unmocked.
        old='1b592af659cec56fe87440cf679d69d7fc41590e'
        for name in b.SEED_NAMES|{'cloud-seed-integrity.json'}:
            raw=subprocess.check_output(['git','-C',str(SOURCE),'show',old+':tools/'+name])
            (self.code/'tools'/name).write_bytes(raw);self.objects['tools/'+name]=raw
        value=self.check()
        self.assertEqual(value['files']['tools/cloud-seed-integrity.json']['sha256'],b.SEED_INTEGRITY)
        self.assertEqual(len(b.SEED_CONTRACTS[b.SEED_INTEGRITY]),9)
    def test_exact_retained_twelve_file_contract_uses_actual485_bytes(self):
        old='4855732886ce0da65ccf3af13928049149f33ea8'
        for name in b.SEED_CONTRACTS[b.CONTINUED_SEED_INTEGRITY]|{'cloud-seed-integrity.json'}:
            raw=subprocess.check_output(['git','-C',str(SOURCE),'show',old+':tools/'+name])
            (self.code/'tools'/name).write_bytes(raw);self.objects['tools/'+name]=raw
        value=self.check()
        self.assertEqual(value['files']['tools/cloud-seed-integrity.json']['sha256'],b.CONTINUED_SEED_INTEGRITY)

    def test_latest_twelve_file_contract_binds_lifetime_helpers(self):
        value=self.check()
        self.assertEqual(value['files']['tools/cloud-seed-integrity.json']['sha256'],b.CARRIED_PREFIX_SEED_INTEGRITY)
        self.assertEqual(len(b.SEED_CONTRACTS[b.FINISHED22_SEED_INTEGRITY]),12)

    def test_retained_current_main_contract_uses_actual_3d_source_bytes(self):
        old='3d95100af8d0671a1dcd29ce27605599ae0dc736'
        for name in b.SEED_CONTRACTS[b.CURRENT_MAIN_WEEKLY_INTEGRITY]|{'cloud-seed-integrity.json'}:
            raw=subprocess.check_output(['git','-C',str(SOURCE),'show',old+':tools/'+name])
            (self.code/'tools'/name).write_bytes(raw);self.objects['tools/'+name]=raw
        value=self.check()
        self.assertEqual(value['files']['tools/cloud-seed-integrity.json']['sha256'],b.CURRENT_MAIN_WEEKLY_INTEGRITY)

    def test_ranked_genuine_closure_requires_actual_ranker_source_and_fresh_bytes(self):
        commit=subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()
        driver=b.genuine_driver(SOURCE,commit)
        self.assertEqual(b.GENUINE_DRIVER_CONTRACTS[b.sha(driver)],b.PRESENCE_CONTRACT)
        names=set(b.RANKING_FILES)|{b.GENUINE_WORKFLOW,'tools/genuine_case_recovery.py'}
        for name in names:
            body=(SOURCE/name).read_bytes();path=self.code/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(body);self.objects[name]=body
        def checked():
            with patch.object(b,'__file__',str(self.code/'tools/operating_resource_bootstrap.py')), \
                    patch.object(b,'git',side_effect=self.git),patch.object(b,'genuine_driver',return_value=driver), \
                    patch.dict(os.environ,GITHUB_SHA='1'*40):return b.closure(self.code,genuine=True)
        value=checked()
        self.assertTrue(set(b.RANKING_FILES)<=set(value['files']))
        path=self.code/'tools/weekly_selected_rankings.py';original=path.read_bytes();info=path.stat()
        path.write_bytes(original[:-1]+bytes([original[-1]^1]));os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
        with self.assertRaisesRegex(RuntimeError,'differs from committed source'):checked()

    def test_retained_finished22_contract_uses_actual_5eb_source_bytes(self):
        old='5eb4a2f07750951df8a6e348eb46d08f8fe7fd3d'
        for name in b.SEED_CONTRACTS[b.FINISHED22_SEED_INTEGRITY]|{'cloud-seed-integrity.json'}:
            raw=subprocess.check_output(['git','-C',str(SOURCE),'show',old+':tools/'+name])
            (self.code/'tools'/name).write_bytes(raw);self.objects['tools/'+name]=raw
        value=self.check()
        self.assertEqual(value['files']['tools/cloud-seed-integrity.json']['sha256'],b.FINISHED22_SEED_INTEGRITY)

    def test_retained_retrieval_contract_uses_actual_f130_source_bytes(self):
        old='f1303ee9dfac61fb47fb6820eabd1d04b36f173c'
        for name in b.SEED_CONTRACTS[b.PREPARATION22_RETRIEVAL_INTEGRITY]|{'cloud-seed-integrity.json'}:
            raw=subprocess.check_output(['git','-C',str(SOURCE),'show',old+':tools/'+name])
            (self.code/'tools'/name).write_bytes(raw);self.objects['tools/'+name]=raw
        value=self.check()
        self.assertEqual(value['files']['tools/cloud-seed-integrity.json']['sha256'],b.PREPARATION22_RETRIEVAL_INTEGRITY)

    def test_only_seven_exact_contracts_are_recognized(self):
        self.assertEqual(set(b.SEED_CONTRACTS),{
            b.CARRIED_PREFIX_SEED_INTEGRITY,
            b.CURRENT_MAIN_WEEKLY_INTEGRITY,
            b.PREPARATION24_LIFETIME_INTEGRITY,
            'bfb48f36d1db5b2980235238e1b869efb183f23095ff72cee33c1d88e84a3b26',
            'ed5b6773c3d4e642bf4346aa2b9de89a2b580a1f34e97bddc6172b068a388611',
            '636b3cd2a966346df02ad30c516dc805e40ae082e1b4f5e7b757162c29e6459f',
            b.PREPARATION22_RETRIEVAL_INTEGRITY})
        self.assertTrue(all(isinstance(v,frozenset) for v in b.SEED_CONTRACTS.values()))
    def test_newly_required_frontier_same_size_mutation_rejected(self):
        path=self.code/'tools/seed_checkpoint_frontier.py';raw=path.read_bytes();old=path.stat()
        path.write_bytes(bytes([raw[0]^1])+raw[1:]);os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
        with self.assertRaisesRegex(RuntimeError,'differs from committed'):self.check()
    def test_newly_required_frontier_missing_rejected(self):
        (self.code/'tools/seed_checkpoint_frontier.py').unlink()
        with self.assertRaises(FileNotFoundError):self.check()
    def test_self_consistent_new_helper_revision_not_accepted_under_old_manifest(self):
        name='tools/seed_checkpoint_frontier.py';raw=self.objects[name];changed=bytes([raw[0]^1])+raw[1:]
        (self.code/name).write_bytes(changed);self.objects[name]=changed
        with self.assertRaisesRegex(RuntimeError,'Immutable seed dependency changed'):self.check()
    def test_self_consistent_carried_wrapper_mutation_cannot_borrow_new_manifest(self):
        name='tools/cloud_seed_prepare.py';raw=self.objects[name];changed=bytes([raw[0]^1])+raw[1:]
        (self.code/name).write_bytes(changed);self.objects[name]=changed
        with self.assertRaisesRegex(RuntimeError,'Immutable seed dependency changed'):self.check()
    def test_self_consistent_unknown_manifest_not_accepted(self):
        path=self.code/'tools/cloud-seed-integrity.json';value=json.loads(path.read_bytes())
        value['files']['extra.py']='a'*64;raw=json.dumps(value,sort_keys=True).encode()
        path.write_bytes(raw);self.objects['tools/cloud-seed-integrity.json']=raw
        with self.assertRaisesRegex(RuntimeError,'integrity manifest changed'):self.check()
    def test_same_size_wrapper_mutation_rejected(self):
        path=self.code/'tools/operating_campaign.py';raw=path.read_bytes()
        path.write_bytes(bytes([raw[0]^1])+raw[1:])
        with self.assertRaisesRegex(RuntimeError,'differs from committed'):self.check()
    def test_missing_dependency_rejected(self):
        (self.code/'tools/source_ci.py').unlink()
        with self.assertRaises(FileNotFoundError):self.check()
    def test_source_symlink_rejected(self):
        path=self.code/'tools/source_ci.py';path.unlink();path.symlink_to(self.code/'tools/operating_diagnostic.py')
        with self.assertRaisesRegex(RuntimeError,'Symlink'):self.check()
    def test_rewritten_seed_manifest_not_admitted(self):
        path=self.code/'tools/cloud-seed-integrity.json';path.write_bytes(path.read_bytes()+b' ')
        self.objects['tools/cloud-seed-integrity.json']=path.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'integrity manifest changed'):self.check()
    def test_wrong_actual_source_sha_rejected(self):
        with patch.object(b,'git',return_value=b'2'*40),patch.dict(os.environ,GITHUB_SHA='1'*40):
            with self.assertRaisesRegex(RuntimeError,'checkout differs'):b.closure(self.code)


class ProtectedReports(unittest.TestCase):
    def info(self,mode,uid=0):return SimpleNamespace(st_mode=stat.S_IFDIR|mode,st_uid=uid)
    def create(self,parent_mode=0o1777,parent_uid=0,child_uid=0):
        def status(path):
            if path==Path('/var/tmp'):return self.info(parent_mode,parent_uid)
            if path in (Path('/'),Path('/var')):return self.info(0o755)
            return self.info(0o755,child_uid)
        with patch.object(Path,'lstat',status),patch.object(Path,'resolve',lambda p:p),patch.object(Path,'mkdir') as mkdir:
            result=b.root_directory(args());self.assertEqual(mkdir.call_count,1);return result
    def test_root_sticky_parent_protects_exact_new_child(self):
        self.assertEqual(self.create(),Path('/var/tmp/nfl-operating-123-1'))
    def test_runner_owned_parent_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'ancestry'):self.create(parent_uid=1001)
    def test_nonsticky_writable_parent_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'ancestry'):self.create(parent_mode=0o777)
    def test_runner_owned_child_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'root ownership'):self.create(child_uid=1001)
    def test_outer_write_exclusive_and_bounded_no_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);b.write_report(root,'report.json',{'status':'UNKNOWN'})
            self.assertEqual(json.loads((root/'report.json').read_bytes()),{'status':'UNKNOWN'})
            self.assertEqual(stat.S_IMODE((root/'report.json').stat().st_mode),0o644)
            with self.assertRaises(FileExistsError):b.write_report(root,'report.json',{'status':'PASS'})
            with self.assertRaises(RuntimeError):b.write_report(root,'oversized.json',{'large':'x'*b.LIMIT})


class ArtifactApproval(unittest.TestCase):
    def test_actual_bounded_approval_bytes_are_rehashed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'operating-artifact-approval.json';path.write_bytes(b'{"fictional":true}\n')
            expected=b.sha(path.read_bytes())
            with patch.dict(os.environ,RUNNER_TEMP=directory,OPERATING_ARTIFACT_APPROVAL_SHA256=expected):
                value=b.transport_approval();self.assertEqual(value['sha256'],expected)
                path.write_bytes(b'{"fictional":false}')
                with self.assertRaisesRegex(RuntimeError,'reviewed identity'):b.transport_approval()
    def test_symlink_approval_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'outside').write_bytes(b'fictional')
            (root/'operating-artifact-approval.json').symlink_to(root/'outside')
            with patch.dict(os.environ,RUNNER_TEMP=directory,OPERATING_ARTIFACT_APPROVAL_SHA256=b.sha(b'fictional')):
                with self.assertRaisesRegex(RuntimeError,'approval path'):b.transport_approval()


class UnitSetup(unittest.TestCase):
    """Plain scratch files + mocked systemctl/xattr, never actual kernel writes."""
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.mount=Path(self.directory.name)/'mock-cgroup';self.unit=self.mount/'system.slice'/'nfl-operating-123-1.service'
        self.current=self.unit/'supervisor';self.current.mkdir(parents=True)
        self.ancestors=[self.current,self.unit,self.unit.parent,self.mount]
        for parent in self.ancestors:
            parent.chmod(0o755)
            for name,value in {'cgroup.procs':'','cgroup.threads':'','cgroup.subtree_control':'memory',
                'memory.max':str(8*1024**3),'memory.swap.max':'0','cgroup.controllers':'memory'}.items():
                (parent/name).write_text(value);(parent/name).chmod(0o644)
        self.properties={'ControlGroup':'/system.slice/nfl-operating-123-1.service','Delegate':'yes',
            'DelegateSubgroup':'supervisor','User':'root','MemoryMax':str(8*1024**3),
            'MemorySwapMax':'0','RuntimeMaxUSec':'20min 30s'}
        self.module=SimpleNamespace(resolve=lambda:(self.mount,self.current,self.ancestors))
    def check(self,readonly=False):
        original_read=Path.read_text;original_write=Path.write_text;original_stat=Path.lstat
        self.writes=[]
        def read(path,*argv,**kwargs):
            if path==Path('/proc/meminfo'):return 'MemTotal:       8388608 kB\n'
            return original_read(path,*argv,**kwargs)
        def write(path,value,*argv,**kwargs):
            self.writes.append((path,value))
            return original_write(path,'memory' if value=='+memory' else value,*argv,**kwargs)
        def status(path):
            value=original_stat(path)
            fields=list(value);fields[4]=0
            return os.stat_result(fields)
        raw='\n'.join(k+'='+v for k,v in self.properties.items())+'\n'
        with patch.object(Path,'read_text',read),patch.object(Path,'write_text',write), \
             patch.object(Path,'lstat',status),patch.object(b.os,'getxattr',return_value=b'1'), \
             patch.object(b.os,'statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY if readonly else 0)), \
             patch.object(b.subprocess,'check_output',return_value=raw):
            return b.unit_setup(args(),self.module)
    def test_exact_existing_unit_records_real_scratch_inode_without_kernel_claim(self):
        value=self.check();self.assertEqual(value['unit'],'nfl-operating-123-1.service')
        self.assertEqual(value['scopes'][1]['inode'],self.unit.stat().st_ino);self.assertEqual(self.writes,[])
    def test_only_unit_local_missing_memory_controller_is_written(self):
        (self.unit/'cgroup.subtree_control').write_text('')
        self.check();self.assertEqual(self.writes,[(self.unit/'cgroup.subtree_control','+memory')])
    def test_missing_ancestor_memory_controller_stops_without_mutation(self):
        (self.unit.parent/'cgroup.subtree_control').write_text('')
        with self.assertRaisesRegex(RuntimeError,'Ancestor controller'):self.check()
        self.assertEqual(self.writes,[])
    def test_wrong_service_property_stops(self):
        self.properties['MemorySwapMax']='max'
        with self.assertRaisesRegex(RuntimeError,'service differs'):self.check()
    def test_readonly_cgroup_mount_stops_before_controller_write(self):
        with self.assertRaisesRegex(RuntimeError,'Read-only'):self.check(readonly=True)
        self.assertEqual(self.writes,[])
    def test_populated_inner_unit_stops(self):
        (self.unit/'cgroup.procs').write_text('FICTIONAL_PID')
        with self.assertRaisesRegex(RuntimeError,'delegated finite'):self.check()
    def test_wrong_current_cgroup_stops(self):
        self.module.resolve=lambda:(self.mount,self.mount,self.ancestors)
        with self.assertRaisesRegex(RuntimeError,'cgroup membership'):self.check()


class CommandAndRun(unittest.TestCase):
    def test_real_supervisor_cli_and_pre_python_git_scrub(self):
        with patch.dict(os.environ,RUNNER_TEMP='/fictional/temp'),patch.object(Path,'exists',return_value=False), \
             patch.object(b.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir='/fictional/home')):
            argv,worker,critical=b.commands(args(),Path('/var/tmp/nfl-operating-123-1'))
        self.assertEqual(argv[1],'-P');self.assertEqual(argv[3],'supervise');self.assertEqual(argv[argv.index('--purpose')+1],'operating')
        self.assertEqual(argv[argv.index('--timeout')+1],'1200');self.assertEqual(worker[0],'/usr/bin/env')
        for name in b.ROOT_GIT:self.assertIn(name,worker)
        self.assertLess(worker.index('GIT_CONFIG_COUNT'),worker.index(sys.executable))
        self.assertNotIn('diagnostic_network_guard.py',' '.join(worker))
        self.assertIn('/var/tmp/nfl-operating-123-1',critical)
        self.assertEqual(worker[-1],'1');self.assertNotIn('FICTIONAL_READ_TOKEN',' '.join(argv))
    def test_capability_supervisor_has_no_worker_or_transport_path(self):
        with patch.dict(os.environ,RUNNER_TEMP='/fictional/temp'),patch.object(Path,'exists',return_value=False), \
             patch.object(b.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir='/fictional/home')):
            argv,worker,critical=b.commands(args(capability_only=True),Path('/var/tmp/nfl-operating-123-1'))
        self.assertEqual(worker,[]);self.assertIn('--preflight-only',argv);self.assertNotIn('--',argv)
        self.assertFalse(any('artifact-approval' in p for p in critical))
    def perform(self,mutate=None,changed=False,capability=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source={'commit':'1'*40,'tree':'2'*40,'files':{'wrapper':'FICTIONAL_HASH'}}
            resource=dict(source='1'*40,purpose='operating',run_id=123,sample=1,harness_sha256=b.P5,
                seed_manifest_sha256='a'*64,status='COMPLETE',resource_verdict='PASS',complete_tree=True,
                privilege_drop_verified=True,kernel_peaks={'/fictional/unit/nfl-diagnostic-123-1-456':{}})
            if capability:resource.update(status='CAPABILITY_READY',resource_verdict='NOT_RUN_CAPABILITY_ONLY',seed_manifest_sha256=None)
            if mutate:mutate(resource)
            child=Mock(pid=456);child.wait.return_value=0;child.poll.return_value=0
            module=SimpleNamespace(report_verdict=lambda value:value['resource_verdict'])
            snapshots=[source,dict(source,tree='3'*40)] if changed else [source,source]
            with patch.object(b,'environment'),patch.object(b,'root_directory',return_value=root), \
                 patch.object(b,'closure',side_effect=snapshots), \
                 patch.object(b,'transport_approval',return_value={'path':'FICTIONAL_APPROVAL','sha256':'b'*64,'bytes':123}) as approval_reader, \
                 patch.object(b,'checked_resource_module',return_value=module), \
                 patch.object(b,'unit_setup',return_value={'scopes':[{}, {'path':'/fictional/unit'}]}), \
                 patch.object(b,'commands',return_value=(['FICTIONAL_SUPERVISOR_CLI'],[] if capability else ['FICTIONAL_WORKER'],[])), \
                 patch.object(b.subprocess,'Popen',return_value=child), \
                 patch.object(b,'protected_resource',return_value=(resource,{'sha256':'b'*64,'bytes':123})), \
                 patch.dict(os.environ,SEED_MANIFEST_SHA256='a'*64,ImageOS='ubuntu24',ImageVersion='FICTIONAL',
                    GITHUB_RUN_ATTEMPT='1',GITHUB_REPOSITORY=b.REPOSITORY,GITHUB_REPOSITORY_ID='1411185749',
                    GITHUB_ACTOR_ID='208912933',GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_REF_NAME=b.BRANCH,
                    GITHUB_WORKFLOW_REF=b.REPOSITORY+'/'+b.WORKFLOW+'@refs/heads/'+b.BRANCH):
                code=b.run(args(capability_only=capability))
                if capability:self.assertEqual(approval_reader.call_count,0)
            value=json.loads((root/'OUTER_EXECUTION_BINDING.json').read_bytes())
            return code,value
    def test_mocked_root_control_binds_actual_wrapper_separately_from_p5(self):
        code,value=self.perform();self.assertEqual(code,0)
        self.assertEqual(value['resource_p5_harness_sha256'],b.P5)
        self.assertEqual(value['resource_report']['sha256'],'b'*64)
        self.assertEqual(value['run_attempt'],1);self.assertEqual(value['actor_id'],208912933)
        self.assertEqual(value['workflow_path'],b.WORKFLOW)
        self.assertEqual(value['worker_uid'],1001);self.assertTrue(value['privilege_drop_verified'])
        self.assertNotIn('GH_TOKEN',json.dumps(value))
        self.assertIn('STILL_REQUIRES_JOB_TIMESTAMPS',value['status'])
    def test_wrong_p5_label_cannot_be_replaced_by_wrapper_hash(self):
        code,value=self.perform(lambda r:r.update(harness_sha256='WRAPPER_NOT_P5'))
        self.assertEqual(code,3);self.assertEqual(value['resource_verdict'],'UNKNOWN')
    def test_other_run_resource_report_rejected(self):
        code,value=self.perform(lambda r:r.update(run_id=124));self.assertEqual(code,3)
    def test_wrong_sample_resource_report_rejected(self):
        code,value=self.perform(lambda r:r.update(sample=2));self.assertEqual(code,3)
    def test_wrong_seed_binding_rejected(self):
        code,value=self.perform(lambda r:r.update(seed_manifest_sha256='c'*64));self.assertEqual(code,3)
    def test_wrong_leaf_process_binding_rejected(self):
        code,value=self.perform(lambda r:r.update(kernel_peaks={'/wrong/leaf':{}}));self.assertEqual(code,3)
    def test_changed_final_source_closure_rejected(self):
        code,value=self.perform(changed=True);self.assertEqual(code,3)
    def test_backend_unknown_never_becomes_pass(self):
        code,value=self.perform(lambda r:r.update(resource_verdict='UNKNOWN'))
        self.assertEqual(code,2);self.assertEqual(value['resource_verdict'],'UNKNOWN')
    def test_capability_only_is_explicitly_not_operating_pass(self):
        code,value=self.perform(capability=True);self.assertEqual(code,0)
        self.assertEqual(value['status'],'CAPABILITY_READY')
        self.assertEqual(value['resource_verdict'],'NOT_RUN_CAPABILITY_ONLY')
        self.assertEqual(value['transport_approval'],'NOT_REQUIRED_CAPABILITY_ONLY')
        self.assertIsNone(value['seed_manifest_sha256']);self.assertIsNone(value['worker_argv'])
        self.assertFalse(value['workload_started'])



class GenuineRoute(unittest.TestCase):
    """Closed control tests; actual privileged/cgroup/provider execution is NOT run."""
    def test_argument_route_is_explicit_and_reader_cannot_select_legacy(self):
        raw=Arguments().raw();self.assertTrue(b.arguments(raw+['--genuine-case']).genuine_case)
        with self.assertRaisesRegex(RuntimeError,'exclusive'):b.arguments(raw+['--read-unit-lifetime'])
        self.assertFalse(b.arguments(raw).genuine_case)
    def test_actual_reviewed_inline_source_bytes_and_changed_source_rejected(self):
        commit=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
        raw=b.genuine_driver(ROOT,commit);self.assertEqual(len(raw),37868);self.assertEqual(b.sha(raw),b.STAGED_POLICY_GENUINE_DRIVER)
        with patch.object(b,'git',return_value=b'not the actual source'):
            with self.assertRaisesRegex(RuntimeError,'actual source'):b.genuine_driver(ROOT,commit)
        original=(ROOT/b.GENUINE_WORKFLOW).read_bytes()
        changed=changed_actual_controller_contract(original)
        self.assertNotEqual(changed,original);self.assertEqual(len(changed),len(original))
        with patch.object(b,'regular_bytes',return_value=changed),patch.object(b,'git',return_value=changed):
            with self.assertRaisesRegex(RuntimeError,'Unknown genuine controller'):b.genuine_driver(ROOT,commit)
    def test_legacy_controller_reader_keeps_actual_retained_source_association(self):
        for legacy,digest,length in [('f1303ee9dfac61fb47fb6820eabd1d04b36f173c',b.LEGACY_GENUINE_DRIVER,30854),
                ('25826e015e70cad74a375e9a5028e7cada5d5c88',b.LEGACY_GENUINE_DRIVER,30854),
                ('e415912b9c3d3ff52e8f435517af02e794d97fa4',b.LEGACY_GENUINE_DRIVER,30854),
                ('a247b378bd05bbb4cd93cb20c88c1498fecef523',b.GENUINE_DRIVER,36877),
                ('d48493e559d6f9540af2a5f45ab75830fe52ee84',b.PRESENCE_GENUINE_DRIVER,37167),
                ('a4815f7ce47720922c30f98c441ca561605bba48',b.CURRENT_PRESENCE_GENUINE_DRIVER,37868)]:
            # Read the real retained Git object; mock only its physical replay root.
            original=subprocess.check_output(['git','-C',str(ROOT),'show',legacy+':'+b.GENUINE_WORKFLOW])
            with patch.object(b,'regular_bytes',return_value=original),patch.object(b,'git',return_value=original):
                raw=b.genuine_driver(ROOT,legacy)
            self.assertEqual(len(raw),length);self.assertEqual(b.sha(raw),digest)
        self.assertEqual(b.GENUINE_DRIVER_BYTES,{b.LEGACY_GENUINE_DRIVER:30854,b.WEEKLY_GENUINE_DRIVER:35468,b.GENUINE_DRIVER:36877,b.PRESENCE_GENUINE_DRIVER:37167,b.CURRENT_PRESENCE_GENUINE_DRIVER:37868,b.STAGED_POLICY_GENUINE_DRIVER:37868})
    def test_actual315_registration_stub_cannot_become_a_genuine_controller(self):
        source='315be5e86a1a3a93022b68c453739076487e2077'
        original=subprocess.check_output(['git','-C',str(ROOT),'show',source+':'+b.GENUINE_WORKFLOW])
        self.assertEqual(b.sha(original),'b1147e8107de5ac44122864cbdb51ade4be3224e956a94ddfb3b83ac9eafc3a9')
        with patch.object(b,'regular_bytes',return_value=original),patch.object(b,'git',return_value=original):
            with self.assertRaisesRegex(RuntimeError,'markers unavailable'):b.genuine_driver(ROOT,source)
    def test_direct_data_only_descendant_and_unchanged_source(self):
        def git(code,*argv):
            if argv==('rev-parse','HEAD'):return b'2'*40
            if argv[0]=='show':return b'1'*40
            if argv[0]=='diff':return b'data/outcomes/fictional.json.gz\0'
            return b''
        with patch.object(b,'git',side_effect=git):self.assertEqual(b.genuine_data_head(Path('/unit'),'1'*40),'2'*40)
        def invalid(code,*argv):return b'tools/scorecard.py\0' if argv[0]=='diff' else git(code,*argv)
        with patch.object(b,'git',side_effect=invalid):
            with self.assertRaisesRegex(RuntimeError,'changes source'):b.genuine_data_head(Path('/unit'),'1'*40)
        def wrong_parent(code,*argv):return b'3'*40 if argv[0]=='show' else git(code,*argv)
        with patch.object(b,'git',side_effect=wrong_parent):
            with self.assertRaisesRegex(RuntimeError,'direct data'):b.genuine_data_head(Path('/unit'),'1'*40)
    def test_closed_genuine_argv_and_legacy_no_new_seed_semantics(self):
        stream=io.BytesIO()
        class Sink(io.BytesIO):
            def close(self):pass
            def fileno(self):return 12
        stream=Sink()
        with patch.dict(os.environ,RUNNER_TEMP='/fictional/temp',GITHUB_SHA='1'*40),patch.object(b.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir='/fictional/home')),patch.object(b,'genuine_driver',return_value=b'reviewed'),patch.object(b.os,'open',return_value=12),patch.object(b.os,'fdopen',return_value=stream),patch.object(b.os,'fsync'):
            supervisor,worker,paths=b.commands(args(Path('/fictional/parent/source'),genuine_case=True),Path('/protected/report'))
        self.assertIn('GITHUB_WORKSPACE=/fictional/parent',worker);self.assertIn('/protected/report/GENUINE_CONTROLLER.py',worker)
        self.assertNotIn('job',worker);self.assertIn('--timeout',supervisor);self.assertEqual(supervisor[supervisor.index('--timeout')+1],'1200')
        self.assertNotIn('/fictional/temp/operating-artifact-approval.json',paths);self.assertIn('/fictional/parent/production',paths)
    def read(self,*,bad_state=False,bad_namespace=False,oom=0,capability=False,changed_final=False,bad_peak=False,read_race=False,low_peak=False,control_group=None):
        unit=Path('/sys/fs/cgroup/system.slice/nfl-operating-123-1.service');limit=8*1024**3
        cg={'scopes':[{},dict(path=str(unit),device=7,inode=8)],'cgroup_namespace':'cg','mount_namespace':'mnt','properties':{'InvocationID':'a'*32,'ExecMainPID':'42'},'kernel_lifetime_backend':{'version':b.LIFETIME_BACKEND,'invocation_id':'a'*32,'exec_main_pid':42,'initial_memory_peak_bytes':100}}
        outer=dict(source={'commit':'1'*40},run_id=123,sample=1,run_attempt=1,root_uid=0,worker_uid=1001,workflow_path=b.GENUINE_WORKFLOW,resource_report={'hash':'unit'},seed_manifest_sha256=None,status='CAPABILITY_READY' if capability else 'GENUINE_COMPLETE_LIFETIME_READ_REQUIRED',cgroup=cg,mode='genuine-capability' if capability else 'genuine',repository=b.REPOSITORY,repository_id=1411185749,actor_id=208912933,supervised_subprocess_verdict='PASS',genuine_result={'sha256':'a'*64},resource_supervisor_pid=42,monitored_leaf_path=str(unit/'nfl-diagnostic-123-1-42'))
        resource={'status':'CAPABILITY_READY','resource_verdict':'NOT_RUN_CAPABILITY_ONLY'} if capability else {'kernel_peaks':{str(unit):{'kernel_peak':256},str(unit/'nfl-diagnostic-123-1-42'):{'kernel_peak':512}}}
        state={'ControlGroup':'/system.slice/nfl-operating-123-1.service' if control_group is None else control_group,'ActiveState':'active','SubState':'running' if bad_state else 'exited','MainPID':'0','RemainAfterExit':'yes','MemoryAccounting':'yes','InvocationID':'a'*32,'MemoryPeak':str(2**64-1) if bad_peak else '1' if low_peak else str(1024**3),'MemorySwapPeak':'0','MemoryMax':str(limit),'MemorySwapMax':'0','Result':'success','ExecMainStatus':'0'}
        values={'memory.peak':str(1024**3),'memory.current':'0','memory.swap.peak':'0','memory.swap.current':'0','memory.max':str(limit),'memory.swap.max':'0','cgroup.events':'populated 0\n','cgroup.procs':'','cgroup.threads':''}
        module=SimpleNamespace(events=lambda p:dict(oom=oom,oom_kill=0,oom_group_kill=0),peak_ok=lambda limit,peak:limit-peak>=max(2*1024**3,.2*limit),report_verdict=lambda value:'FAIL' if oom else 'PASS')
        def info(path,*a,**k):return SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|(0o1777 if path==b.ROOT_BASE else 0o755),st_dev=7,st_ino=8)
        output=io.StringIO()
        with patch.object(b,'genuine_result',return_value={'sha256':('b' if changed_final else 'a')*64}),patch.object(b,'environment'),patch.object(b,'closure',return_value={'commit':'1'*40}),patch.object(b,'regular_bytes',return_value=json.dumps(outer).encode()),patch.object(b,'protected_resource',return_value=(resource,{'hash':'unit'})),patch.object(b,'checked_resource_module',return_value=module),patch.object(Path,'lstat',info),patch.object(Path,'stat',info),patch.object(Path,'resolve',lambda p:p),patch.object(Path,'is_symlink',return_value=False),patch.object(Path,'read_text',lambda p:values[p.name]),patch.object(b.os,'access',return_value=False),patch.object(b.os,'readlink',side_effect=lambda p:'bad' if bad_namespace else 'mnt' if str(p).endswith('/mnt') else 'cg'),patch.object(b.subprocess,'check_output',side_effect=['\n'.join(k+'='+v for k,v in state.items()),'\n'.join(k+'='+('b'*32 if read_race and k=='InvocationID' else v) for k,v in state.items())]),contextlib.redirect_stdout(output):
            code=b.read_unit_lifetime(args(genuine_case=True,read_unit_lifetime=True))
        return code,json.loads(output.getvalue().splitlines()[0].split('=',1)[1])
    def test_lifetime_unit_only_never_whole_job_or_vm_pass(self):
        code,value=self.read();self.assertEqual(code,0);self.assertEqual(value['unit_headroom'],'PASS');self.assertEqual(value['resource_verdict'],'UNKNOWN');self.assertEqual(value['whole_gha_job_memory'],'NOT_MEASURED')
    def test_retained_empty_unit_capability_is_not_workload_evidence(self):
        code,value=self.read(capability=True);self.assertEqual(code,0);self.assertEqual(value['status'],'CAPABILITY_READY_NO_WORKLOAD')
    def test_running_or_untrusted_namespace_cannot_qualify(self):
        with self.assertRaisesRegex(RuntimeError,'exited manager'):self.read(bad_state=True)
        with self.assertRaisesRegex(RuntimeError,'namespaces'):self.read(bad_namespace=True)
    def test_changed_postroot_result_cannot_borrow_prior_success(self):
        with self.assertRaisesRegex(RuntimeError,'changed after'):self.read(changed_final=True)
    def test_actual_small_final_and_tar_fresh_hashes_fail_closed(self):
        # Real unprivileged regular files, only tiny wholly fictional bytes.
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'nfl-real-production-case';out.mkdir();tar=out/'release-review.tar';tar.write_bytes(b'fictional bytes')
            value=dict(status='COMPLETE_GENUINE_NONDEPLOY_CASE',source='1'*40,artifact_tar_bytes=tar.stat().st_size,artifact_tar_sha256=hashlib.sha256(tar.read_bytes()).hexdigest(),operating_qualification='NOT_ESTABLISHED',resource_verdict='UNKNOWN')
            final=out/'FINAL.json';final.write_text(json.dumps(value))
            with patch.dict(os.environ,RUNNER_TEMP=temp,GITHUB_SHA='1'*40),patch.object(b,'genuine_driver',return_value=b'fictional reviewed controller'):
                first=b.genuine_result(args());self.assertEqual(first['root_run_id'],123)
                self.assertEqual(first['driver_sha256'],b.sha(b'fictional reviewed controller'))
                # A caught application failure may exit0; typed status must reject.
                value['status']='FAILED';final.write_text(json.dumps(value))
                with self.assertRaisesRegex(RuntimeError,'did not complete'):b.genuine_result(args())
                value['status']='COMPLETE_GENUINE_NONDEPLOY_CASE';final.write_text(json.dumps(value));tar.write_bytes(b'fictional BYTES')
                with self.assertRaisesRegex(RuntimeError,'changed'):b.genuine_result(args())
    def test_pycache_does_not_exempt_tracked_or_untracked_python_source(self):
        def check(name,tracked):
            def git(code,*a):
                if a==('rev-parse','HEAD'):return b'1'*40
                if (a[0]=='diff')==tracked:return name.encode()+b'\0'
                return b''
            with patch.object(b,'git',side_effect=git):return b.genuine_data_head(Path('/unit'),'1'*40)
        for tracked in (False,True):
            with self.assertRaisesRegex(RuntimeError,'source'):check('pull/__pycache__/untrusted.py',tracked)
        self.assertEqual(check('pull/__pycache__/grade.cpython-312.pyc',False),'1'*40)

    def test_canonical_weekly_audit_data_lane_never_exempts_source(self):
        def check(name,tracked=False):
            def git(code,*argv):
                if argv==('rev-parse','HEAD'):return b'1'*40
                if (argv[0]=='diff')==tracked:return name.encode()+b'\0'
                return b''
            with patch.object(b,'git',side_effect=git):return b.genuine_data_head(Path('/unit'),'1'*40)
        for tracked in (False,True):
            self.assertEqual(check('data/weekly-adaptive-audit/'+'a'*64+'.json',tracked),'1'*40)
            for name in ('data/weekly-adaptive-audit/'+ 'A'*64+'.json',
                    'data/weekly-adaptive-audit/'+ 'a'*63+'.json',
                    'data/weekly-adaptive-audit/'+ 'a'*64+'.json.gz',
                    'data/weekly-adaptive-audit/nested/'+ 'a'*64+'.json',
                    'data/weekly-adaptive-audit/helper.py'):
                with self.subTest(name=name,tracked=tracked),self.assertRaisesRegex(RuntimeError,'source'):
                    check(name,tracked)

    def test_cached_kernel_unknown_identity_race_and_lower_bound_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError,'unavailable'):self.read(bad_peak=True)
        with self.assertRaisesRegex(RuntimeError,'below recorded'):self.read(low_peak=True)
        with self.assertRaisesRegex(RuntimeError,'changed during read'):self.read(read_race=True)
    def test_system_bus_override_and_metadata_bounds_rejected(self):
        with patch.dict(os.environ,DBUS_SYSTEM_BUS_ADDRESS='unix:path=/fictional/untrusted'):
            with self.assertRaisesRegex(RuntimeError,'overrides'):b.manager_properties(args(),('MemoryPeak',))
        with patch.object(b.subprocess,'check_output',return_value='MemoryPeak=1\nMemoryPeak=2\n'):
            with self.assertRaisesRegex(RuntimeError,'properties'):b.manager_properties(args(),('MemoryPeak',))
    def test_root_setup_records_actual_manager_invocation_and_pid(self):
        mount=Path('/mock/cgroup');unit=mount/'system.slice'/'nfl-operating-123-1.service';current=unit/'supervisor';limit=8*1024**3
        values={'cgroup.procs':'','cgroup.threads':'','cgroup.subtree_control':'memory','memory.max':str(limit),'memory.swap.max':'0','cgroup.controllers':'memory'}
        state={'ControlGroup':'/system.slice/nfl-operating-123-1.service','Delegate':'yes','DelegateSubgroup':'supervisor','User':'root','MemoryMax':str(limit),'MemorySwapMax':'0','RuntimeMaxUSec':'20min 30s','RemainAfterExit':'yes','MemoryAccounting':'yes','InvocationID':'a'*32,'ExecMainPID':str(os.getpid()),'MemoryPeak':'100','MemorySwapPeak':'0'}
        module=SimpleNamespace(resolve=lambda:(mount,current,[current,unit,mount]));info=SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|0o755,st_dev=7,st_ino=8)
        def read(p,*a,**kw):return 'MemTotal: 8388608 kB\n' if p==Path('/proc/meminfo') else values[p.name]
        with patch.object(Path,'read_text',read),patch.object(Path,'lstat',return_value=info),patch.object(Path,'stat',return_value=info),patch.object(Path,'is_symlink',return_value=False),patch.object(b.os,'getxattr',return_value=b'1'),patch.object(b.os,'statvfs',return_value=SimpleNamespace(f_flag=0)),patch.object(b.os,'readlink',return_value='unitnamespace'),patch.object(b.subprocess,'check_output',side_effect=lambda *a,**kw:'\n'.join(k+'='+v for k,v in state.items())):
            value=b.unit_setup(args(genuine_case=True),module)
            self.assertEqual(value['kernel_lifetime_backend']['exec_main_pid'],os.getpid());self.assertEqual(value['kernel_lifetime_backend']['initial_memory_peak_bytes'],100)
            state['InvocationID']='g'*32
            with self.assertRaisesRegex(RuntimeError,'invocation'):b.unit_setup(args(genuine_case=True),module)

    def test_pruned_empty_cgroup_retains_exact_cached_invocation(self):
        code,value=self.read(control_group='')
        self.assertEqual(code,0);self.assertEqual(value['backend'],b.LIFETIME_BACKEND)
        self.assertEqual(value['resource_verdict'],'UNKNOWN');self.assertEqual(value['unit_headroom'],'PASS')
    def test_cached_invocation_cannot_select_another_cgroup(self):
        with self.assertRaisesRegex(RuntimeError,'exited manager'):self.read(control_group='/system.slice/unrelated.service')

    def test_lifetime_oom_is_not_hidden_by_leaf_pass(self):
        with self.assertRaisesRegex(RuntimeError,'did not pass'):self.read(oom=1)


class PublicDeploymentBrowserContract(unittest.TestCase):
    """Synthetic contract controls only; no browser, deployed bytes or outcome qualification."""
    def invoke(self,change=None,url=None):
        script=(ROOT/'tools/release_browser.cjs').read_text()
        fragment=script.split('// BEGIN PUBLIC DEPLOYMENT REVIEW CONTRACT\n',1)[1].split('// END PUBLIC DEPLOYMENT REVIEW CONTRACT',1)[0]
        generation={'source_sha':'1'*40,'generation_sha256':'a'*64}
        raw=json.dumps(generation,separators=(',',':')).encode()
        import hashlib
        proof=dict(schema_version='source-ci-verification-v1',executed_commit='2'*40,executed_tree='3'*40,
            source_manifest_sha256='b'*64,source_ci_commit='4'*40,run_id=55,run_attempt=1,job_id=66,
            seal_sha256='c'*64,environment_sha256='d'*64,
            claim='COMPLETE_SOURCE_CHECKS_ONLY_NOT_GENERATION_OR_OPERATING_QUALIFICATION')
        value=dict(schema_version='public-deployment-review-v1',status='AUTHENTICATED_HOURLY_PAGES_DEPLOYMENT',
            source='1'*40,installed_source='5'*40,installed_source_manifest_sha256='b'*64,
            runtime_data_commit='2'*40,runtime_data_tree='3'*40,
            hourly=dict(run_id=77,run_attempt=1,head_sha='6'*40,event='schedule',job_id=88,workflow_path='.github/workflows/hourly.yml'),
            source_ci=proof,artifact=dict(id=99,name='github-pages',zip_bytes=1024,zip_sha256='e'*64,tar_bytes=1024,tar_sha256='f'*64),
            pages=dict(members_sha256='e'*64,release_identity_sha256=hashlib.sha256(raw).hexdigest(),generation_sha256='a'*64),
            generation=generation,expected_site_url='https://nicknicky19.github.io/nicks-expert-nfl-picks/')
        if change:change(value)
        test="const assert=require('node:assert/strict'),crypto=require('node:crypto');const sha=b=>crypto.createHash('sha256').update(b).digest('hex');\n"+fragment
        test+="\nconst input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));publicDeploymentContract(input.value,input.url,input.generation,Buffer.from(input.raw),'e'.repeat(64));"
        result=subprocess.run(['node','-e',test],input=json.dumps(dict(value=value,url=url or value['expected_site_url'],generation=generation,raw=raw.decode())),text=True,capture_output=True,timeout=10)
        return result.returncode
    def test_explicit_deployment_contract_accepts_typed_synthetic_binding(self):
        self.assertEqual(self.invoke(),0)
    def test_public_target_must_be_exact_canonical_site(self):
        for url in ('https://example.test/','https://nicknicky19.github.io/nicks-expert-nfl-picks/?x=1','https://nicknicky19.github.io/nicks-expert-nfl-picks'):
            self.assertNotEqual(self.invoke(url=url),0)
    def test_case_status_cannot_stand_in_for_hourly_review(self):
        self.assertNotEqual(self.invoke(lambda v:v.update(status='COMPLETE_GENUINE_NONDEPLOY_CASE')),0)
    def test_extra_provider_or_qualification_fields_rejected(self):
        self.assertNotEqual(self.invoke(lambda v:v.update(provider_case_attempts=1)),0)
    def test_source_ci_must_bind_actual_runtime_commit_and_tree(self):
        for key in ('executed_commit','executed_tree','source_manifest_sha256'):
            self.assertNotEqual(self.invoke(lambda v,k=key:v['source_ci'].update({k:'9'*(40 if k!='source_manifest_sha256' else 64)})),0)
    def test_public_generation_and_actual_identity_bytes_bound(self):
        self.assertNotEqual(self.invoke(lambda v:v['pages'].update(release_identity_sha256='0'*64)),0)
        self.assertNotEqual(self.invoke(lambda v:v.update(source='0'*40)),0)
        self.assertNotEqual(self.invoke(lambda v:v['pages'].update(generation_sha256='0'*64)),0)
    def test_actual_pages_member_digest_must_match(self):
        self.assertNotEqual(self.invoke(lambda v:v['pages'].update(members_sha256='0'*64)),0)
    def test_zip_tar_caps_and_actual_artifact_role(self):
        self.assertNotEqual(self.invoke(lambda v:v['artifact'].update(zip_bytes=128*1024**2+1)),0)
        self.assertNotEqual(self.invoke(lambda v:v['artifact'].update(tar_bytes=127*1024**2+1)),0)
        self.assertNotEqual(self.invoke(lambda v:v['artifact'].update(name='genuine-production-review-77')),0)
    def test_normal_hourly_identity_not_caller_command_or_url(self):
        self.assertNotEqual(self.invoke(lambda v:v['hourly'].update(workflow_path='arbitrary.yml')),0)
        self.assertNotEqual(self.invoke(lambda v:v['hourly'].update(run_attempt=True)),0)



class GenuineRecovery(unittest.TestCase):
    """Small synthetic data/streams only; no provider or backend qualification."""
    def setUp(self):
        import genuine_case_recovery as recovery
        import source_ci
        self.r=recovery;self.r.source_ci=source_ci
    def receipt(self,schema='baseline-capture-v2',mtime=0,**fields):
        import gzip
        payload=dict(schema_version=schema,source_sha='a'*40,**fields)
        return gzip.compress(self.r.canonical(dict(payload=payload,payload_sha256=self.r.sha(self.r.canonical(payload)))),mtime=mtime)
    def members(self,raw):
        import io,tarfile
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            return {item.name:archive.extractfile(item).read() for item in archive}
    def test_stream_bounds_crc_schema_and_private_inputs(self):
        r=self.r;good=self.receipt('completion-failure-data-integrity-v2')
        self.assertEqual(r.decoded(good,True)['schema_version'],'completion-failure-data-integrity-v2')
        for raw in (good[:-4],self.receipt('http-transcript-v1'),b'{"x":1,"x":2}',b'{"x":Infinity}'):
            with self.subTest(raw=raw[:16]),self.assertRaises((ValueError,EOFError,OSError)):r.decoded(raw,raw[:2]==b'\x1f\x8b')
        for fields in (dict(password='CONTROL'),dict(localStorage={}),dict(account_balance=0),dict(message='Bearer CONTROL')):
            with self.subTest(fields=fields),self.assertRaises(ValueError):r.decoded(self.receipt(**fields),True)
        with patch.object(r,'DECODED',32),self.assertRaisesRegex(ValueError,'DECODED_BOUND'):
            r.decoded(self.receipt(large='x'*100))
    def test_actual_small_encoded_file_is_unchanged_and_symlink_rejected(self):
        r=self.r
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'receipt';body=self.receipt();path.write_bytes(body)
            before=path.stat();info,read=r.encoded(path,True)
            self.assertEqual(read,body);self.assertEqual(info['sha256'],r.sha(body))
            self.assertEqual((path.stat().st_mtime_ns,path.read_bytes()),(before.st_mtime_ns,body))
            with patch.object(r,'ENCODED',1):
                with self.assertRaises(ValueError):r.encoded(path,limit=1)
            link=path.with_name('link');link.symlink_to(path)
            with self.assertRaisesRegex(ValueError,'NONREGULAR'):r.encoded(link)

    def test_encoded_reader_does_not_block_when_regular_file_is_replaced_by_fifo(self):
        r=self.r
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'record';path.write_bytes(b'fictional')
            opening=r.os.open
            def replace(name,flags):
                self.assertTrue(flags&os.O_NONBLOCK)
                path.unlink();os.mkfifo(path)
                return opening(name,flags)
            with patch.object(r.os,'open',side_effect=replace),self.assertRaisesRegex(ValueError,'FILE_REPLACED'):
                r.encoded(path,True)
    def test_union_baseline_skips_both_saved_versions_and_hides_unknown_names(self):
        r=self.r
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);a=root/'a';b=root/'b'
            for folder,body in ((a,b'{"version":1}'),(b,b'{"version":2}')):
                path=folder/'output/data/week.json';path.parent.mkdir(parents=True);path.write_bytes(body)
            unknown=a/'data/private-owner.json';unknown.parent.mkdir();unknown.write_bytes(b'{}')
            before=r.snapshot((('source',a),('production',b)))
            self.assertEqual(len(before[r.sha(b'output/data/week.json')]['versions']),2)
            self.assertNotIn(b'private-owner',r.canonical(before))
            recordings,records=r.recover([('source',a)],before)
            self.assertEqual(self.members(recordings),{});self.assertEqual(records,[])
    def test_new_receipts_from_source_and_transaction_preserve_exact_bytes(self):
        r=self.r
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);source=root/'source';stage=root/'stage'
            path=source/'data/verification/new.json.gz';path.parent.mkdir(parents=True);body=self.receipt();path.write_bytes(body)
            twin=stage/'data/verification/new.json.gz';twin.parent.mkdir(parents=True);os.link(path,twin)
            different=stage/'data/verification/different.json.gz';different.write_bytes(self.receipt(mtime=1))
            bad=source/'data/verification/incomplete.json.gz';bad.write_bytes(body[:-4])
            recordings,records=r.recover([('source',source),('transactions/phase2-coherent-generation-test/generation',stage)],{})
            members=self.members(recordings);self.assertEqual(len(members),2)
            self.assertIn(body,members.values());self.assertIn(different.read_bytes(),members.values())
            kept=[x for x in records if x['state']=='UNQUALIFIED_PRESERVED']
            self.assertEqual(len(kept),3);self.assertEqual(len({x['archive_member'] for x in kept}),2)
            self.assertTrue(all(x['physical_path']!=x['logical_path'] for x in kept))
            self.assertTrue(any(x.get('logical_path','').endswith('incomplete.json.gz') and x['state'].startswith('UNAVAILABLE') for x in records))
    def test_invalid_modern_output_does_not_hide_primary_receipt(self):
        r=self.r
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);path=root/'data/forward/new.json.gz';path.parent.mkdir(parents=True);body=self.receipt();path.write_bytes(body)
            extra=root/'output/data/optional-http-transcript.json';extra.parent.mkdir(parents=True);extra.write_bytes(b'{"password":"CONTROL"}')
            recordings,records=r.recover([('source',root)],{})
            self.assertEqual(list(self.members(recordings).values()),[body])
            unknown=next(x for x in records if x.get('reason')=='UNCLASSIFIED_ROLE')
            self.assertNotIn('logical_path',unknown);self.assertNotIn(b'CONTROL',recordings)
    def test_only_two_exact_quiescent_units_are_read(self):
        r=self.r
        state=b'LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\nControlPID=0\n'
        with patch.object(r.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=state)) as show:
            units=r.inactive_units('123')
            self.assertEqual([x['unit'] for x in units],['nfl-operating-123-1.service','nfl-operating-123-2.service'])
            self.assertEqual(show.call_count,2)
        with patch.object(r.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=state.replace(b'inactive',b'active'))):
            with self.assertRaisesRegex(ValueError,'UNIT_NOT_QUIESCENT'):r.inactive_units('123')
    def test_exact_three_inputs_and_source_job_context(self):
        r=self.r;source='a'*40
        env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',GITHUB_REPOSITORY=r.REPO,GITHUB_REPOSITORY_ID='1411185749',GITHUB_ACTOR_ID='208912933',GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_RUN_ATTEMPT='1',GITHUB_REF=r.REF,GITHUB_JOB='genuine-production-case',GITHUB_WORKFLOW_REF=r.REPO+'/.github/workflows/prepare-diagnostic-seed.yml@'+r.REF,GITHUB_SHA=source,GITHUB_WORKFLOW_SHA=source,GITHUB_RUN_ID='123')
        event=dict(inputs=dict(confirmation=r.CONF,storage_approved=r.CONF,installed_source=source),repository=dict(id=1411185749,full_name=r.REPO),sender=dict(id=208912933))
        self.assertEqual(r.validate_invocation(env,event,source),(source,'123'))
        for key in ('GITHUB_JOB','GITHUB_SHA','GITHUB_WORKFLOW_SHA','GITHUB_ACTOR_ID','GITHUB_RUN_ATTEMPT','GITHUB_RUN_ID'):
            with self.subTest(key=key),self.assertRaises(ValueError):r.validate_invocation(dict(env,**{key:'wrong'}),event,source)
        changed=copy.deepcopy(event);changed['inputs']['extra']='bad'
        with self.assertRaises(ValueError):r.validate_invocation(env,changed,source)
    def test_missing_final_still_exports_first_recordings_and_total_cap(self):
        r=self.r;recordings=b'bounded synthetic recordings'
        meta=dict(schema_version='genuine-failure-recovery-v1',claim='UNQUALIFIED_PRESERVATION_ONLY_NEVER_COMPLETION',baseline_sha256='a'*64,identity={},controller_export='OMITTED_NO_MATCHED_CONTROLLER')
        with tempfile.TemporaryDirectory() as raw:
            report,original,final=r.controller(Path(raw),'a'*40)
            self.assertIsNone(original);self.assertIsNone(final)
        files=r.export_files(meta,recordings)
        self.assertEqual(set(files),{'failure-first-recordings.tar','RECOVERY.json'})
        self.assertEqual(files['failure-first-recordings.tar'],recordings)
        with patch.object(r,'CAP',2048):
            files=r.export_files(meta,recordings,b'x'*1900)
            self.assertNotIn('controller-release-review.tar',files)
            self.assertLessEqual(sum(map(len,files.values())),2048)
            self.assertEqual(files['failure-first-recordings.tar'],recordings)
    def test_existing_final_and_controller_tar_remain_byte_identical(self):
        r=self.r;archive,final=self.controller_fixture()
        def read(path,retain=False,limit=None):
            body=final if path.name=='FINAL.json' else archive
            return dict(bytes=len(body),sha256=r.sha(body),mode=0o644),body if retain else None
        with patch.object(r,'encoded',side_effect=read):
            report,path,original_final=r.controller(Path('/synthetic/out'),'a'*40)
        self.assertEqual(report['status'],'COMPLETE_GENUINE_NONDEPLOY_CASE')
        self.assertEqual(path,Path('/synthetic/out/release-review.tar'));self.assertEqual(original_final,final)
        self.assertEqual(r.sha(archive),r.parsed(final)['artifact_tar_sha256'])

    def test_incomplete_data_write_does_not_bypass_actual_source_guard(self):
        r=self.r
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);path=root/'helper.py';path.write_bytes(b'# synthetic source\n')
            current=dict(commit='a'*40,files=[dict(path='helper.py',mode='100644',bytes=path.stat().st_size,sha256=r.sha(path.read_bytes()))])
            allowed=('data/forward/new.json.gz','output/data/week.json','data/verification/.capture-abcdefgh','output/data/.json-abcdefgh','data/cache/tmpabcdefgh','output/data/selection-grading/tmpabcdefgh','__pycache__/helper.cpython-312.pyc')
            for name in allowed:
                with self.subTest(name=name),patch.object(r.source_ci,'source',return_value=current),patch.object(r.source_ci,'git',return_value=name.encode()+b'\0'):
                    self.assertEqual(r.source_identity(root),current)
            path.write_bytes(b'# changed source\n')
            with patch.object(r.source_ci,'source',return_value=current),patch.object(r.source_ci,'git',return_value=b''):
                with self.assertRaisesRegex(ValueError,'ACTUAL_SOURCE_BYTES_CHANGED'):r.source_identity(root)
            path.write_bytes(b'# synthetic source\n')
            denied=('data/forward/evil.py','tools/__pycache__/evil.py','data/cache/evil.py','__pycache__/helper.cpython-311.pyc','__pycache__/evil.cpython-312.pyc','data/verification/receipt.tmp','tools/import-shadow.py','data/forward/.capture-abcdefgh.py')
            for name in denied:
                with self.subTest(name=name),patch.object(r.source_ci,'source',return_value=current),patch.object(r.source_ci,'git',return_value=name.encode()+b'\0'):
                    with self.assertRaisesRegex(ValueError,'UNTRACKED_EXECUTABLE_SOURCE'):r.source_identity(root)

    def test_complete_first_atomic_receipt_survives_without_canonical_link(self):
        r=self.r
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);path=root/'data/forward/2026/w07/.capture-abcdefgh';path.parent.mkdir(parents=True)
            body=self.receipt();path.write_bytes(body)
            recordings,records=r.recover([('transactions/phase2-coherent-generation-test/generation',root)],{})
            self.assertEqual(list(self.members(recordings).values()),[body])
            self.assertEqual(records[0]['role'],'receipt_temporary')
            self.assertTrue(records[0]['physical_path'].endswith('/.capture-abcdefgh'))
            self.assertEqual(records[0]['logical_reference_status'],'ATOMIC_TEMP_NO_CANONICAL_NATIVE_CREATED')
            self.assertEqual(sorted(path.parent.iterdir()),[path])
            for bad in (body[:-4],self.receipt('unsupported-source-control-v1')):
                path.write_bytes(bad);recordings,records=r.recover([('source',root)],{})
                self.assertEqual(self.members(recordings),{})
                self.assertTrue(records[0]['state'].startswith('UNAVAILABLE'))
    def tar(self,members,gnu=False):
        import io,tarfile
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w',format=tarfile.GNU_FORMAT if gnu else tarfile.USTAR_FORMAT) as archive:
            for name,body in members.items():
                item=tarfile.TarInfo(name);item.size=len(body);item.mode=0o644;archive.addfile(item,io.BytesIO(body))
        return stream.getvalue()
    def controller_fixture(self,**private):
        r=self.r;logical='data/forward/2026/w07/'+'e'*64+'.json.gz';receipt=self.receipt(**private)
        info=dict(bytes=len(receipt),sha256=r.sha(receipt),mode=0o600)
        pages={'app.js':b'// synthetic public source\n','data/selection-grading/'+'b'*64+'/summary.json':b'{"public":true}'}
        page_info={name:dict(bytes=len(body),sha256=r.sha(body)) for name,body in pages.items()}
        metadata={'RELEASE_CASE_MANIFEST.json':dict(schema_version='genuine-current-production-case-v1',source='a'*40,status='COMPLETE_GENUINE_NONDEPLOY_CASE'),'INPUT_DATA_MANIFEST.json':dict(source='a'*40),'OUTPUT_DATA_MANIFEST.json':dict(after={logical:info},representations={}),'NEW_RECEIPTS_MANIFEST.json':[dict(path=logical,schema_version='baseline-capture-v2',**info)],'PAGES_MEMBERS_MANIFEST.json':page_info,'SOURCE_CI_BINDINGS.json':{}}
        entries={'receipts/'+logical:receipt,'public-pages.tar':self.tar(pages,True),**{name:r.canonical(value) for name,value in metadata.items()}}
        archive=self.tar(entries)
        final=r.canonical(dict(status='COMPLETE_GENUINE_NONDEPLOY_CASE',source='a'*40,artifact_tar_bytes=len(archive),artifact_tar_sha256=r.sha(archive),new_receipts=1,operating_qualification='NOT_ESTABLISHED',resource_verdict='UNKNOWN',controller_seconds_including_retention=1.25))
        return archive,final
    def test_standard_credentials_rejected_but_owner_marker_preserved(self):
        r=self.r
        for key in ('access_token','refresh_token','id_token','Set-Cookie','set_cookie','Proxy-Authorization','X-Api-Key'):
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'PRIVATE_FIELD'):r.decoded(self.receipt(**{key:'CONTROL'}),True)
        value=r.decoded(self.receipt(owner_authorization='FICTIONAL_ONLY_DERIVED_SOURCE_TRANSITION_NOT_REAL_ACTIVATION'),True)
        self.assertEqual(value['owner_authorization'],'FICTIONAL_ONLY_DERIVED_SOURCE_TRANSITION_NOT_REAL_ACTIVATION')
    def test_success_tar_with_self_consistent_secret_is_never_exportable(self):
        r=self.r
        for fields in (dict(access_token='CONTROL'),{'Set-Cookie':'session=CONTROL'}):
            archive,final=self.controller_fixture(**fields)
            def read(path,retain=False,limit=None):
                body=final if path.name=='FINAL.json' else archive
                return dict(bytes=len(body),sha256=r.sha(body),mode=0o644),body if retain else None
            with self.subTest(fields=fields),patch.object(r,'encoded',side_effect=read):
                report,original,kept_final=r.controller(Path('/synthetic/out'),'a'*40)
            self.assertIsNone(original);self.assertEqual(kept_final,final)
            self.assertEqual(report['tar_or_final_unavailable'],'PRIVATE_FIELD')
            meta=dict(schema_version='genuine-failure-recovery-v1',claim='UNQUALIFIED_PRESERVATION_ONLY_NEVER_COMPLETION',baseline_sha256='a'*64,identity={},controller_export='OMITTED_UNSAFE_CONTROLLER')
            files=r.export_files(meta,b'bounded safe recordings',final_raw=kept_final)
            self.assertNotIn('controller-release-review.tar',files);self.assertTrue(all(body!=archive for body in files.values()));self.assertTrue(all(b'\"access_token\"' not in body and b'\"Set-Cookie\"' not in body for body in files.values()))
            self.assertEqual(r.sha(archive),r.parsed(final)['artifact_tar_sha256'])
    def test_system_manager_cannot_be_redirected(self):
        r=self.r
        for key in ('DBUS_SYSTEM_BUS_ADDRESS','SYSTEMD_BUS_ADDRESS'):
            with self.subTest(key=key),patch.dict(os.environ,{key:'CONTROL'}),patch.object(r.subprocess,'run') as call:
                with self.assertRaisesRegex(ValueError,'SYSTEM_MANAGER_BUS_OVERRIDE'):r.inactive_units('123')
                call.assert_not_called()
        state=b'LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\nControlPID=0\n'
        with patch.dict(os.environ,{},clear=True),patch.object(r.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=state)) as call:
            r.inactive_units('123')
        self.assertTrue(all(item.args[0][:4]==['/usr/bin/systemctl','--system','--no-pager','show'] for item in call.call_args_list))
    def test_bad_deflate_excludes_only_that_file_and_preserves_neighbor(self):
        r=self.r;good=self.receipt();bad=b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03'+b'\xff'*10
        files={'bad.json.gz':bad,'good.json.gz':good}
        def encoded(path,retain=False,limit=None):
            raw=files[path.name];return dict(bytes=len(raw),sha256=r.sha(raw),mode=0o600),raw if retain else None
        candidates=[('data/forward/'+name,Path('/synthetic')/name,None) for name in files]
        with patch.object(r,'candidates',return_value=iter(candidates)),patch.object(r,'encoded',side_effect=encoded):
            recordings,records=r.recover([('source',Path('/synthetic'))],{})
        self.assertEqual(list(self.members(recordings).values()),[good])
        self.assertTrue(any(item.get('reason')=='INVALID_OR_INCOMPLETE_GZIP' for item in records))

    def test_authenticated_dependency_rejects_same_size_restored_time_before_execution(self):
        import hashlib
        r=self.r
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);path=root/'tools/source_ci.py';path.parent.mkdir();expected=b'FLAG=1\n';path.write_bytes(expected)
            oid=hashlib.sha1(b'blob '+str(len(expected)).encode()+b'\0'+expected).hexdigest()
            def git(_root,*args):
                if args[0]=='ls-tree':return ('100644 blob '+oid+'\ttools/source_ci.py\0').encode()
                if args[0]=='cat-file' and args[1]=='-s':return str(len(expected)).encode()
                if args[0]=='cat-file':return expected
                raise AssertionError(args)
            with patch.object(r,'fixed_git',side_effect=git):
                self.assertEqual(r.checked_source_ci(root,'a'*40).FLAG,1)
                stamp=path.stat();path.write_bytes(b'FLAG=2\n');os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                with patch.object(r.types,'ModuleType') as execution:
                    with self.assertRaisesRegex(ValueError,'DEPENDENCY_DIFFERS_FROM_DISPATCH'):r.checked_source_ci(root,'a'*40)
                    execution.assert_not_called()

    def test_new_ranker_dependency_is_git_bound_before_loading(self):
        import hashlib
        r=self.r;name='tools/weekly_selected_rankings.py';expected=(ROOT/name).read_bytes()
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);path=root/name;path.parent.mkdir();path.write_bytes(expected)
            oid=hashlib.sha1(b'blob '+str(len(expected)).encode()+b'\0'+expected).hexdigest()
            def git(_root,*args):
                if args[0]=='ls-tree':return ('100644 blob '+oid+'\t'+name+'\0').encode()
                if args[:2]==('cat-file','-s'):return str(len(expected)).encode()
                if args[0]=='cat-file':return expected
                raise AssertionError(args)
            with patch.object(r,'fixed_git',side_effect=git):
                self.assertEqual(r.authenticated_bytes(root,'a'*40,name),expected)
                info=path.stat();path.write_bytes(expected[:-1]+bytes([expected[-1]^1]));os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
                with self.assertRaisesRegex(ValueError,'DEPENDENCY_DIFFERS_FROM_DISPATCH'):
                    r.authenticated_bytes(root,'a'*40,name)

    def test_ranker_exec_uses_authenticated_overlay_and_restores_import_namespace(self):
        import types
        import weekly_adaptive_overlay as w
        r=self.r;raw=(ROOT/'tools/weekly_selected_rankings.py').read_bytes()
        untrusted=types.ModuleType('weekly_adaptive_overlay')
        untrusted.digest=lambda _:self.fail('Unchecked imported overlay was used')
        with patch.dict(sys.modules,weekly_adaptive_overlay=untrusted),patch.object(r,'authenticated_bytes',return_value=raw) as source:
            checked=r.checked_rankings(Path('/fictional/source'),'a'*40,w)
            source.assert_called_once_with(Path('/fictional/source'),'a'*40,'tools/weekly_selected_rankings.py')
            self.assertIs(checked.overlay,w);self.assertIs(sys.modules['weekly_adaptive_overlay'],untrusted)
            self.assertEqual(checked.POLICY_SHA,w.digest(checked.POLICY))
        with patch.dict(sys.modules,weekly_adaptive_overlay=untrusted),patch.object(r,'authenticated_bytes',side_effect=r.Rejected('DEPENDENCY_DIFFERS_FROM_DISPATCH')),patch.object(r.types,'ModuleType') as execution:
            with self.assertRaisesRegex(ValueError,'DEPENDENCY_DIFFERS_FROM_DISPATCH'):
                r.checked_rankings(Path('/fictional/source'),'a'*40,w)
            execution.assert_not_called();self.assertIs(sys.modules['weekly_adaptive_overlay'],untrusted)
    def test_real_local_source_ci_dependency_is_verified_before_use(self):
        r=self.r;head=subprocess.check_output(['/usr/bin/git','-C',str(SOURCE),'rev-parse','HEAD']).decode().strip()
        checked=r.checked_source_ci(SOURCE,head)
        self.assertTrue(checked.mutable('data/forward/control.json.gz'))
    def test_pages_member_hash_and_unknown_tar_roles_are_rejected(self):
        r=self.r;archive,_=self.controller_fixture()
        entries=r.tar_entries(archive);entries['owner-worker.log']=b'CONTROL'
        with self.assertRaisesRegex(ValueError,'CONTROLLER_UNCLASSIFIED_MEMBER'):r.controller_archive(self.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE')
        entries.pop('owner-worker.log');pages=r.parsed(entries['PAGES_MEMBERS_MANIFEST.json']);next(iter(pages.values()))['sha256']='0'*64
        entries['PAGES_MEMBERS_MANIFEST.json']=r.canonical(pages)
        with self.assertRaisesRegex(ValueError,'CONTROLLER_PAGES_MEMBERSHIP'):r.controller_archive(self.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE')

    def audit_fixture(self,**changes):
        r=self.r
        value=dict(schema_version='weekly-public-feed-writer-audit-v1',website_source_sha='a'*40,
            at='2026-10-24T10:02:00Z',policy_file_sha256='b'*64,
            authority_kind='AUTOMATED_REGISTERED_POLICY',human_approval=False,
            validation=dict(state='CURRENT_REFERENCE_FALLBACK',reason='FICTIONAL_NO_FEED',rows=0,human_approval=False),review={})
        value.update(changes)
        return 'data/weekly-adaptive-audit/'+r.sha(r.canonical(value))+'.json',r.canonical(value)

    def test_weekly_audit_typed_identity_and_private_fields_fail_closed(self):
        r=self.r;name,body=self.audit_fixture()
        self.assertEqual(r.role(name),'weekly_audit')
        self.assertEqual(r.weekly_json(name,body)['schema_version'],'weekly-public-feed-writer-audit-v1')
        for change in (dict(website_source_sha='a'*39),dict(at='2026-10-24T10:02:00'),
                dict(human_approval=True),dict(policy_file_sha256=None),dict(review=[]),dict(extra='UNAPPROVED'),
                dict(review={'access_token':'CONTROL'})):
            bad_name,bad=self.audit_fixture(**change)
            with self.subTest(change=change),self.assertRaises(ValueError):r.weekly_json(bad_name,bad)
        with self.assertRaisesRegex(ValueError,'IDENTITY'):r.weekly_json(name,body.replace(b'FICTIONAL_NO_FEED',b'FICTIONAL_NO_DATA'))
        with patch.object(r,'MIB',1),self.assertRaisesRegex(ValueError,'BOUND'):r.weekly_json(name,body)
        for wrong in ('data/weekly-adaptive-audit/x.json','data/weekly-adaptive-audit/'+ 'a'*64+'.json.gz'):
            self.assertIsNone(r.role(wrong))

    def test_weekly_plain_json_roles_reject_gzip_before_decoding(self):
        import gzip
        r=self.r;name,body=self.audit_fixture();w,pages=self.weekly_fixture()
        pointer=pages[r.WEEKLY_POINTER];path=r.parsed(pointer)['path'];overlay=gzip.compress(pages[path],mtime=0)
        cases=[(name,gzip.compress(body,mtime=0)),(r.WEEKLY_POINTER,gzip.compress(pointer,mtime=0)),
            ('data/weekly-adaptive/'+r.sha(overlay)+'.json',overlay)]
        for logical,encoded in cases:
            with self.subTest(role=logical),self.assertRaisesRegex(ValueError,'WEEKLY_PLAIN_JSON_REQUIRED'):
                r.weekly_json(logical,encoded)
            with patch.object(r,'decoded') as decoding:
                with self.assertRaisesRegex(ValueError,'WEEKLY_PLAIN_JSON_REQUIRED'):r.weekly_json(logical,encoded)
                decoding.assert_not_called()
        self.assertEqual(r.decoded(self.receipt(),True)['schema_version'],'baseline-capture-v2')

    def test_weekly_audit_quarantine_preserves_exact_valid_bytes_and_neighbors(self):
        r=self.r;name,body=self.audit_fixture()
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);good=root/name;good.parent.mkdir(parents=True);good.write_bytes(body)
            bad_name,bad=self.audit_fixture(human_approval=True);(root/bad_name).write_bytes(bad)
            receipt=root/'data/forward/new.json.gz';receipt.parent.mkdir();receipt.write_bytes(self.receipt())
            recordings,records=r.recover([('source',root)],{})
            self.assertIn(body,self.members(recordings).values());self.assertIn(receipt.read_bytes(),self.members(recordings).values())
            kept=next(v for v in records if v.get('logical_path')==name)
            self.assertEqual(kept['state'],'UNQUALIFIED_PRESERVED');self.assertEqual(kept['role'],'weekly_audit')
            self.assertTrue(any(v.get('reason')=='WEEKLY_AUDIT_CONTRACT' for v in records))
            self.assertEqual(good.read_bytes(),body)

    def test_weekly_reader_bound_precedes_open_and_applies_to_both_reads(self):
        r=self.r;name,body=self.audit_fixture()
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);path=root/name;path.parent.mkdir(parents=True);path.write_bytes(body)
            real=r.encoded;calls=[]
            def read(p,retain=False,limit=None):
                calls.append((retain,limit))
                return real(p,retain,limit)
            with patch.object(r,'encoded',side_effect=read):recordings,records=r.recover([('source',root)],{})
            self.assertEqual(calls,[(False,4*r.MIB),(True,4*r.MIB)])
            self.assertIn(body,self.members(recordings).values())
            # A sparse invalid file exercises the actual pre-read size check
            # without allocating a multi-megabyte test payload.
            with path.open('wb') as output:output.truncate(4*r.MIB+1)
            with patch.object(r.os,'open') as opening:
                recordings,records=r.recover([('source',root)],{})
                opening.assert_not_called()
            self.assertEqual(self.members(recordings),{})
            self.assertEqual(records[0]['reason'],'ENCODED_BOUND')

    def test_weekly_retained_read_rejects_growth_and_legacy_keeps_its_limit(self):
        r=self.r;name,body=self.audit_fixture()
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);path=root/name;path.parent.mkdir(parents=True);path.write_bytes(body)
            real=r.encoded
            def read(p,retain=False,limit=None):
                if retain:
                    self.assertEqual(limit,4*r.MIB)
                    with p.open('wb') as output:output.truncate(4*r.MIB+1)
                return real(p,retain,limit)
            with patch.object(r,'encoded',side_effect=read):recordings,records=r.recover([('source',root)],{})
            self.assertEqual(self.members(recordings),{});self.assertEqual(records[0]['reason'],'ENCODED_BOUND')
            path.unlink();legacy=root/'data/forward/control.json.gz';legacy.parent.mkdir();legacy.write_bytes(self.receipt())
            calls=[]
            def legacy_read(p,retain=False,limit=None):
                calls.append(limit);return real(p,retain,limit)
            with patch.object(r,'encoded',side_effect=legacy_read):recordings,records=r.recover([('source',root)],{})
            self.assertEqual(calls,[r.ENCODED,r.ENCODED]);self.assertIn(legacy.read_bytes(),self.members(recordings).values())

    def weekly_fixture(self):
        spec=importlib.util.spec_from_file_location('weekly_recovery_test',ROOT/'tools/weekly_adaptive_overlay.py')
        w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w);r=self.r
        board=dict(season=2026,week=8,generated_at='2026-10-24T10:00:00Z',
            games=[dict(id='fictional-game',kickoff='2026-10-25T17:00:00Z',state='pre')],
            players=[dict(id='fictional-player',game_id='fictional-game',team='AAA',opp='BBB',
                props=[dict(key='rec',proj=2.,adj=2.5,line=3.,line_from='dk')])])
        selected=dict(rows=[dict(game_id='fictional-game',player_id='fictional-player',category='rec',
            method_id='FICTIONAL_METHOD',model_version='b'*64,procedure_version='c'*64,product='point_mean',
            prediction_functional='expected_mean',forecast_value=3.25,horizon='player_game',
            source_cutoff_utc='2026-10-24T10:01:00Z',issued_at='2026-10-24T10:00:00Z',
            persistence_completed_at='2026-10-24T10:01:00Z',kickoff_utc='2026-10-25T17:00:00Z',
            valid_until_utc='2026-10-25T17:00:00Z',selection_sha256='d'*64,source_policy_sha256='e'*64,
            query_source_sha256='f'*64,season=2026,week=8,team='AAA',opponent='BBB',
            evidence_lane='original_pregame',operational_eligible=True)])
        review=dict(schema_version=w.REVIEW,approved=True,selected_input_sha256=w.digest(selected),website_source_sha='a'*40)
        board_raw=w.canonical(board)
        doc=w.prepare_overlay(board,w.sha(board_raw),selected,review,website_source_sha='a'*40,prepared_at='2026-10-24T10:02:00Z')
        self.assertEqual(len(doc['rows']),1)
        body=w.canonical(doc);path='data/weekly-adaptive/'+w.sha(body)+'.json'
        pointer=dict(schema_version=w.POINTER,path=path,sha256=w.sha(body),bytes=len(body),display_board_sha256=w.sha(board_raw))
        pages={r.WEEKLY_JS:b'// FICTIONAL reviewed public helper\n','data/week.json':board_raw,
            r.WEEKLY_POINTER:w.canonical(pointer),path:body}
        return w,pages

    def test_complete_weekly_graph_uses_actual_semantic_validator_and_closed_source(self):
        r=self.r;w,pages=self.weekly_fixture()
        with patch.object(r,'weekly_overlay',w),patch.object(r,'weekly_static',pages[r.WEEKLY_JS]):
            r.weekly_pages(pages,'a'*40)
            for key in (r.WEEKLY_JS,r.WEEKLY_POINTER,w.sha(b'absent')):
                if key not in pages:continue
                changed=dict(pages);changed.pop(key)
                with self.subTest(missing=key),self.assertRaises(ValueError):r.weekly_pages(changed,'a'*40)
            path=r.parsed(pages[r.WEEKLY_POINTER])['path']
            changed=dict(pages);changed.pop(path)
            with self.assertRaisesRegex(ValueError,'COMPLETE_GRAPH'):r.weekly_pages(changed,'a'*40)
            with self.assertRaisesRegex(ValueError,'EXECUTED_SOURCE'):r.weekly_pages(pages,'b'*40)
            changed=dict(pages);changed[path]=changed[path].replace(b'3.25',b'9.25')
            with self.assertRaisesRegex(ValueError,'DESCRIPTOR_BYTES'):r.weekly_pages(changed,'a'*40)
            changed=dict(pages);changed[r.WEEKLY_JS]=b'// changed same role\n'
            with self.assertRaisesRegex(ValueError,'STATIC_SOURCE'):r.weekly_pages(changed,'a'*40)
            changed=dict(pages);changed['data/weekly-adaptive/'+'0'*64+'.json']=b'{}'
            with self.assertRaisesRegex(ValueError,'COMPLETE_GRAPH'):r.weekly_pages(changed,'a'*40)
            for mutate in (lambda d:d.update(week=9),lambda d:d['rows'][0].update(game_id='other-game'),
                    lambda d:d['rows'][0].update(access_token='CONTROL')):
                changed=dict(pages);doc=r.parsed(changed.pop(path));mutate(doc);body=r.canonical(doc)
                new='data/weekly-adaptive/'+r.sha(body)+'.json';changed[new]=body
                pointer=r.parsed(changed[r.WEEKLY_POINTER]);pointer.update(path=new,sha256=r.sha(body),bytes=len(body))
                changed[r.WEEKLY_POINTER]=r.canonical(pointer)
                with self.subTest(mutation=mutate),self.assertRaises(ValueError):r.weekly_pages(changed,'a'*40)

    def test_weekly_controller_extension_is_explicit_and_legacy_stays_readable(self):
        r=self.r;archive,_=self.controller_fixture();r.controller_archive(archive,'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE')
        entries=r.tar_entries(archive);w,pages=self.weekly_fixture()
        entries['public-pages.tar']=self.tar(pages,True)
        entries['PAGES_MEMBERS_MANIFEST.json']=r.canonical({n:dict(bytes=len(v),sha256=r.sha(v)) for n,v in pages.items()})
        case=r.parsed(entries['RELEASE_CASE_MANIFEST.json'])
        with patch.object(r,'weekly_overlay',w),patch.object(r,'weekly_static',pages[r.WEEKLY_JS]):
            with self.assertRaisesRegex(ValueError,'WEEKLY_CONTROLLER_REQUIRED'):r.controller_archive(self.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE')
            case.update(controller_contract=r.WEEKLY_CONTRACT,reviewed_main_base='315be5e86a1a3a93022b68c453739076487e2077',
                reviewed_main_source_tree='dfdc11ac312a6a54c79e7379352106c315e13f5f')
            entries['RELEASE_CASE_MANIFEST.json']=r.canonical(case)
            r.controller_archive(self.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE')
            name,body=self.audit_fixture();storage='mutable/'+name;info=dict(bytes=len(body),sha256=r.sha(body),storage=storage)
            outputs=r.parsed(entries['OUTPUT_DATA_MANIFEST.json']);outputs['after'][name]=dict(bytes=len(body),sha256=r.sha(body))
            outputs['representations'][name]=info;entries[storage]=body;entries['OUTPUT_DATA_MANIFEST.json']=r.canonical(outputs)
            r.controller_archive(self.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE')
            case['reviewed_main_base']='0'*40;entries['RELEASE_CASE_MANIFEST.json']=r.canonical(case)
            with self.assertRaisesRegex(ValueError,'REVIEWED_MAIN_SOURCE'):r.controller_archive(self.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE')

    def test_recovery_driver_dispatch_uses_only_exact_actual_controller_bytes(self):
        r=self.r;original=(ROOT/r.WORKFLOW).read_bytes()
        with patch.object(r,'authenticated_bytes',return_value=original):
            self.assertEqual(r.checked_driver(ROOT,'a'*40),r.STAGED_POLICY_DRIVER)
        changed=changed_actual_controller_contract(original)
        self.assertNotEqual(changed,original);self.assertEqual(len(changed),len(original))
        with patch.object(r,'authenticated_bytes',return_value=changed):
            with self.assertRaisesRegex(ValueError,'CLOSED_DRIVER_IDENTITY'):r.checked_driver(ROOT,'a'*40)
        for source,digest in [('f1303ee9dfac61fb47fb6820eabd1d04b36f173c',r.LEGACY_DRIVER),
                ('25826e015e70cad74a375e9a5028e7cada5d5c88',r.LEGACY_DRIVER),
                ('e415912b9c3d3ff52e8f435517af02e794d97fa4',r.LEGACY_DRIVER),
                ('a247b378bd05bbb4cd93cb20c88c1498fecef523',r.DRIVER),
                ('d48493e559d6f9540af2a5f45ab75830fe52ee84',r.PRESENCE_DRIVER),
                ('a4815f7ce47720922c30f98c441ca561605bba48',r.CURRENT_PRESENCE_DRIVER)]:
            legacy=subprocess.check_output(['git','-C',str(ROOT),'show',source+':'+r.WORKFLOW])
            with patch.object(r,'authenticated_bytes',return_value=legacy):
                self.assertEqual(r.checked_driver(ROOT,source),digest)
        self.assertEqual(r.DRIVER_BYTES,{r.LEGACY_DRIVER:30854,r.WEEKLY_DRIVER:35468,r.DRIVER:36877,r.PRESENCE_DRIVER:37167,r.CURRENT_PRESENCE_DRIVER:37868,r.STAGED_POLICY_DRIVER:37868})

    def test_actual315_registration_stub_is_rejected_by_saved_recovery(self):
        r=self.r;source='315be5e86a1a3a93022b68c453739076487e2077'
        original=subprocess.check_output(['git','-C',str(ROOT),'show',source+':'+r.WORKFLOW])
        self.assertEqual(r.sha(original),'b1147e8107de5ac44122864cbdb51ade4be3224e956a94ddfb3b83ac9eafc3a9')
        with patch.object(r,'authenticated_bytes',return_value=original):
            with self.assertRaisesRegex(ValueError,'CLOSED_DRIVER_MARKERS'):r.checked_driver(ROOT,source)

    def ranked_fixture(self, directory):
        import weekly_adaptive_overlay as w
        import weekly_selected_rankings as rankings
        from test_weekly_selected_rankings import fixture, NOW, PERSIST
        root=Path(directory)/'root';output=root/'output';data=output/'data';data.mkdir(parents=True)
        board,doc=fixture()
        def save(path,value):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(w.canonical(value))
        save(data/'week.json',board);w.write_public(doc,data,save)
        (output/self.r.WEEKLY_JS).write_bytes(b'// Fictional authenticated static\n')
        original=rankings.prepare(board,w.digest(board),doc,w.digest(doc),now=NOW,website_source_sha='b'*40)
        original_pointer=rankings.write_public(original,data,save,clock=lambda:PERSIST)
        board['games'][0]['state']='in';board['generated_at']='2031-10-25T18:00:00+00:00'
        doc=w.prepare_overlay(board,w.digest(board),{},{},website_source_sha='c'*40,
            prepared_at='2031-10-25T18:00:00+00:00',previous=doc)
        save(data/'week.json',board);w.write_public(doc,data,save)
        current=rankings.prepare(board,w.digest(board),doc,w.digest(doc),now='2031-10-25T18:00:00+00:00',
            website_source_sha='c'*40,previous=original,previous_receipt=original_pointer)
        pointer=rankings.write_public(current,data,save,clock=lambda:'2031-10-25T18:00:01+00:00')
        names=w.stage_assets(root)
        files={name:(output/name).read_bytes() for name in names};files['data/week.json']=(data/'week.json').read_bytes()
        return root,w,rankings,current,pointer,files

    def test_ranked_graph_keeps_frozen_original_source_and_rejects_missing_corrupt_extra(self):
        r=self.r
        with tempfile.TemporaryDirectory() as directory:
            _,w,rankings,current,pointer,files=self.ranked_fixture(directory)
            self.assertEqual(len(current['frozen_proofs']),2);self.assertGreaterEqual(len(files),9)
            origin='data/weekly-selected-rankings/'+current['frozen_proofs'][0]['receipt_sha256']+'.receipt.json'
            original_body='data/'+r.parsed(files[origin])['path']
            self.assertEqual(r.parsed(files[original_body])['website_source_sha'],'b'*40)
            self.assertEqual(current['website_source_sha'],'c'*40)
            with patch.object(r,'weekly_overlay',w),patch.object(r,'weekly_rankings',rankings),patch.object(r,'weekly_static',files[r.WEEKLY_JS]):
                r.weekly_pages(files,'c'*40)
                for name in (origin,original_body,r.RANKING_POINTER):
                    changed=dict(files);changed.pop(name)
                    with self.subTest(missing=name),self.assertRaises(ValueError):r.weekly_pages(changed,'c'*40)
                changed=dict(files);changed[origin]=b'X'+changed[origin][1:]
                with self.assertRaises(ValueError):r.weekly_pages(changed,'c'*40)
                changed=dict(files);changed['data/weekly-selected-rankings/'+'0'*64+'.json']=b'{}'
                with self.assertRaises(ValueError):r.weekly_pages(changed,'c'*40)
                with self.assertRaises(ValueError):r.weekly_pages(files,'d'*40)

    def test_ranked_roles_enforce_plain_per_role_caps_before_open_and_preserve_valid_neighbor(self):
        import gzip
        r=self.r
        with tempfile.TemporaryDirectory() as directory:
            root,w,rankings,current,pointer,files=self.ranked_fixture(directory)
            with patch.object(r,'weekly_rankings',rankings):
                for name,body in files.items():
                    description=rankings.public_role(name)
                    if description is None:continue
                    logical='output/'+name;kind=r.role(logical)
                    self.assertEqual(r.recording_limit(logical,kind),description[1])
                    self.assertEqual(r.weekly_json(logical,body),r.parsed(body))
                    with self.subTest(gzip=name),self.assertRaisesRegex(ValueError,'PLAIN_JSON'):
                        r.weekly_json(logical,gzip.compress(body,mtime=0))
                audit_name,audit_body=self.audit_fixture();neighbor=root/audit_name;neighbor.parent.mkdir(parents=True);neighbor.write_bytes(audit_body)
                target=root/'output'/r.RANKING_POINTER
                with target.open('wb') as stream:stream.truncate(4097)
                recordings,records=r.recover([('source',root)],{})
                self.assertIn(audit_body,self.members(recordings).values())
                failed=next(v for v in records if v.get('logical_path')=='output/'+r.RANKING_POINTER)
                self.assertEqual(failed['reason'],'ENCODED_BOUND')
                encoded=r.encoded;calls=[]
                def bounded(path,retain=False,limit=None):
                    if path==target:calls.append((retain,limit))
                    return encoded(path,retain,limit)
                with patch.object(r,'encoded',side_effect=bounded):r.recover([('source',root)],{})
                self.assertEqual(calls,[(False,4096)])

    def test_ranked_complete_controller_requires_v3_and_failed_outputs_remain_unqualified(self):
        r=self.r
        with tempfile.TemporaryDirectory() as directory:
            _,w,rankings,current,pointer,files=self.ranked_fixture(directory)
            archive,_=self.controller_fixture();entries=r.tar_entries(archive)
            case=r.parsed(entries['RELEASE_CASE_MANIFEST.json']);case.update(source='c'*40,
                controller_contract=r.WEEKLY_CONTRACT,reviewed_main_base=r.REVIEWED_MAIN[r.WEEKLY_CONTRACT][0],
                reviewed_main_source_tree=r.REVIEWED_MAIN[r.WEEKLY_CONTRACT][1])
            entries['INPUT_DATA_MANIFEST.json']=r.canonical(dict(source='c'*40))
            entries['RELEASE_CASE_MANIFEST.json']=r.canonical(case)
            entries['PAGES_MEMBERS_MANIFEST.json']=r.canonical({n:dict(bytes=len(v),sha256=r.sha(v)) for n,v in files.items()})
            entries['public-pages.tar']=self.tar(files,True)
            with patch.object(r,'weekly_overlay',w),patch.object(r,'weekly_rankings',rankings),patch.object(r,'weekly_static',files[r.WEEKLY_JS]):
                with self.assertRaisesRegex(ValueError,'RANKING_CONTROLLER_REQUIRED'):
                    r.controller_archive(self.tar(entries),'c'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE')
                case.update(controller_contract=r.RANKING_CONTRACT,reviewed_main_base=r.REVIEWED_MAIN[r.RANKING_CONTRACT][0],
                    reviewed_main_source_tree=r.REVIEWED_MAIN[r.RANKING_CONTRACT][1])
                entries['RELEASE_CASE_MANIFEST.json']=r.canonical(case)
                r.controller_archive(self.tar(entries),'c'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE')
                self.assertEqual(r.DRIVER_CONTRACTS[r.DRIVER],r.RANKING_CONTRACT)
                r.controller_archive(self.tar(entries),'c'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=r.DRIVER)
                case.update(controller_contract=r.PRESENCE_CONTRACT,reviewed_main_base=r.REVIEWED_MAIN[r.PRESENCE_CONTRACT][0],
                    reviewed_main_source_tree=r.REVIEWED_MAIN[r.PRESENCE_CONTRACT][1])
                entries['RELEASE_CASE_MANIFEST.json']=r.canonical(case)
                r.controller_archive(self.tar(entries),'c'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=r.PRESENCE_DRIVER)
                with self.assertRaisesRegex(ValueError,'CONTROLLER_SOURCE_CONTRACT'):
                    r.controller_archive(self.tar(entries),'c'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=r.DRIVER)
                case.update(controller_contract=r.RANKING_CONTRACT,reviewed_main_base=r.REVIEWED_MAIN[r.RANKING_CONTRACT][0],
                    reviewed_main_source_tree=r.REVIEWED_MAIN[r.RANKING_CONTRACT][1])
                entries['RELEASE_CASE_MANIFEST.json']=r.canonical(case)
                with self.assertRaisesRegex(ValueError,'CONTROLLER_SOURCE_CONTRACT'):
                    r.controller_archive(self.tar(entries),'c'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=r.WEEKLY_DRIVER)
                with self.assertRaisesRegex(ValueError,'CONTROLLER_SOURCE_CONTRACT'):
                    r.controller_archive(self.tar(entries),'c'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver='0'*64)
                case['status']='FAILED';entries['RELEASE_CASE_MANIFEST.json']=r.canonical(case)
                entries.pop('public-pages.tar');entries['PAGES_MEMBERS_MANIFEST.json']=b'{}'
                outputs=r.parsed(entries['OUTPUT_DATA_MANIFEST.json'])
                for name,body in files.items():
                    if rankings.public_role(name) is None:continue
                    logical='output/'+name;storage='mutable/'+logical;info=dict(bytes=len(body),sha256=r.sha(body))
                    outputs['after'][logical]=info;outputs['representations'][logical]=dict(info,storage=storage);entries[storage]=body
                entries['OUTPUT_DATA_MANIFEST.json']=r.canonical(outputs)
                preserved=r.controller_archive(self.tar(entries),'c'*40,'FAILED')
                self.assertEqual(preserved['RELEASE_CASE_MANIFEST.json']['status'],'FAILED')
                case['controller_contract']=r.WEEKLY_CONTRACT;case['reviewed_main_base'],case['reviewed_main_source_tree']=r.REVIEWED_MAIN[r.WEEKLY_CONTRACT]
                entries['RELEASE_CASE_MANIFEST.json']=r.canonical(case)
                with self.assertRaisesRegex(ValueError,'RANKING_CONTROLLER_REQUIRED'):
                    r.controller_archive(self.tar(entries),'c'*40,'FAILED')


class GenuineRawRankedRetention(unittest.TestCase):
    """Execute actual installed inline controller helpers; never main/providers."""

    def controller(self):
        import types
        commit=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
        raw=b.genuine_driver(ROOT,commit)
        self.assertEqual(b.sha(raw),b.STAGED_POLICY_GENUINE_DRIVER)
        module=types.ModuleType('genuine_installed_controller_under_test')
        exec(compile(raw,str(ROOT/b.GENUINE_WORKFLOW)+'::genuine-controller','exec'),module.__dict__)
        self.assertEqual(module.CONTROLLER_CONTRACT,b.PRESENCE_CONTRACT)
        return module

    def fixture(self,directory):
        helper=GenuineRecovery();helper.setUp()
        return helper.ranked_fixture(directory)

    def test_later_failure_preserves_all_five_typed_ranked_assets_as_unqualified_mutable(self):
        raw=self.controller()
        with tempfile.TemporaryDirectory() as directory:
            root,w,rankings,current,pointer,files=self.fixture(directory)
            expected={'mutable/output/'+name for name in files if rankings.public_role(name) is not None}
            self.assertEqual(len(expected),5)
            original={name:(root/name[len('mutable/'):]).read_bytes() for name in expected}
            after=raw.inventory(root)
            payload,native,errors=raw.collect_receipts(root,{},after)
            self.assertEqual({name for name,_ in payload},expected)
            self.assertEqual(native,[]);self.assertEqual(errors,[])
            payload,native,representations,failure,errors=raw.retention_delta(root,{},after,{},None)
            self.assertEqual(failure,'NO_COMPLETE_PAGES_TAR');self.assertEqual(native,[]);self.assertEqual(errors,[])
            self.assertEqual({name for name,_ in payload},expected)
            self.assertEqual(set(representations),{name[len('mutable/'):] for name in expected})
            for name,path in payload:
                self.assertEqual(path.read_bytes(),original[name]);logical=name[len('mutable/'):]
                self.assertEqual(representations[logical],dict(after[logical],storage=name))

    def test_invalid_ranked_neighbor_is_not_exported_and_valid_typed_bytes_are_preserved(self):
        import gzip
        raw=self.controller()
        for mutation in ('gzip_pointer','oversized_body','corrupt_origin_receipt','unclassified'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as directory:
                root,w,rankings,current,pointer,files=self.fixture(directory)
                expected={'mutable/output/'+name for name in files if rankings.public_role(name) is not None}
                if mutation=='gzip_pointer':
                    path=root/'output/data/weekly-selected-rankings.json';path.write_bytes(gzip.compress(path.read_bytes(),mtime=0))
                elif mutation=='oversized_body':
                    path=root/'output/data'/pointer['path']
                    with path.open('r+b') as stream:stream.truncate(rankings.LIMIT+1)
                elif mutation=='corrupt_origin_receipt':
                    path=root/'output/data/weekly-selected-rankings'/(current['frozen_proofs'][0]['receipt_sha256']+'.receipt.json')
                    path.write_bytes(b'X'+path.read_bytes()[1:])
                else:
                    path=root/'output/data/weekly-selected-rankings/unclassified.json';path.write_bytes(b'{}')
                bad=path.relative_to(root).as_posix();after=raw.inventory(root)
                payload,native,errors=raw.collect_receipts(root,{},after)
                self.assertEqual(native,[]);self.assertTrue(any(v['path']==bad for v in errors))
                self.assertEqual({name for name,_ in payload},expected-{'mutable/'+bad})
                self.assertTrue(all(name!='mutable/'+bad for name,_ in payload))
                for name,member in payload:self.assertEqual(w.sha(member.read_bytes()),after[name[len('mutable/'):]]['sha256'])
                retained,native,representations,failure,again=raw.retention_delta(root,{},after,{},None)
                self.assertEqual(failure,'RECEIPT_VALIDATION_ERRORS');self.assertEqual(native,[])
                self.assertEqual({name for name,_ in retained},{name for name,_ in payload})
                self.assertTrue(any(v['path']==bad for v in again))

    def test_immutable_guard_detects_unused_original_ranking_and_overlay_changes(self):
        from test_phase2_e2e import WeeklyRankedPagesGraphTests
        raw=self.controller()
        for kind in ('overlay_body','ranking_body','ranking_receipt'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root,w,rankings,current,pointer,unused,_=WeeklyRankedPagesGraphTests().fixture(directory)
                needed={'output/'+name for name in w.stage_assets(root)}
                before=raw.inventory(root)
                if kind=='overlay_body':names=[n for n in before if n.startswith('output/data/weekly-adaptive/') and n not in needed]
                elif kind=='ranking_body':names=['output/data/'+n for n in unused if n.endswith('.json') and not n.endswith('.receipt.json')]
                else:names=['output/data/'+n for n in unused if n.endswith('.receipt.json')]
                self.assertTrue(names);name=names[0];self.assertNotIn(name,needed)
                path=root/name;body=path.read_bytes();path.write_bytes(b'X'+body[1:])
                after=raw.inventory(root);violations=raw.immutable_violations(before,after)
                self.assertEqual([v['path'] for v in violations],[name])
                self.assertEqual(violations[0]['before_sha256'],before[name]['sha256'])
                self.assertEqual(violations[0]['after_sha256'],after[name]['sha256'])


class GenuinePresenceController(unittest.TestCase):
    """Actual typed v4 readers and local Git; no provider or resource qualification."""

    def setUp(self):
        self.helper=GenuineRecovery();self.helper.setUp();self.r=self.helper.r

    def controller(self):
        return GenuineRawRankedRetention().controller()

    def archive(self,contract=None,cache=None):
        r=self.r;raw,_=self.helper.controller_fixture();entries=r.tar_entries(raw)
        case=r.parsed(entries['RELEASE_CASE_MANIFEST.json'])
        if contract is None:contract=r.PRESENCE_CONTRACT
        case.update(controller_contract=contract,reviewed_main_base=r.REVIEWED_MAIN[contract][0],
            reviewed_main_source_tree=r.REVIEWED_MAIN[contract][1])
        entries['RELEASE_CASE_MANIFEST.json']=r.canonical(case)
        if cache is not None:
            name,body=cache;storage='mutable/'+name;info=dict(bytes=len(body),sha256=r.sha(body))
            output=r.parsed(entries['OUTPUT_DATA_MANIFEST.json'])
            output['after'][name]=info;output['representations'][name]=dict(info,storage=storage)
            entries['OUTPUT_DATA_MANIFEST.json']=r.canonical(output);entries[storage]=body
        return entries

    def test_closed_v4_addition_preserves_exact_v1_v2_v3_contracts(self):
        r=self.r
        expected={b.LEGACY_GENUINE_DRIVER:None,b.WEEKLY_GENUINE_DRIVER:r.WEEKLY_CONTRACT,
            b.GENUINE_DRIVER:r.RANKING_CONTRACT,b.PRESENCE_GENUINE_DRIVER:r.PRESENCE_CONTRACT,
            b.CURRENT_PRESENCE_GENUINE_DRIVER:r.PRESENCE_CONTRACT,b.STAGED_POLICY_GENUINE_DRIVER:r.PRESENCE_CONTRACT}
        self.assertEqual(b.GENUINE_DRIVER_CONTRACTS,expected)
        self.assertEqual(r.DRIVER_CONTRACTS,expected)
        self.assertEqual(r.DRIVER,'b0776717b8dc98eae6d959a098e7d0926cd164bbce7ebd086ff55520ba5e73c5')
        self.assertEqual(r.REVIEWED_MAIN[r.RANKING_CONTRACT],
            ('89512ed952308dacc1f6a930915ddbcdccd460d9','c88d5b3740c820b30387ec2eaca2b0bceafd9a51'))
        self.assertEqual(r.REVIEWED_MAIN[r.PRESENCE_CONTRACT],
            ('e336bf7a68c32267c3c3eec48892aeadcd03a90e','26c1ca52eb1d9b3610a552ecf63ccd2fab5ad8f8'))

    def test_actual_local_git_closure_rejects_disk_and_committed_unknown_driver(self):
        r=self.r;original=(ROOT/b.GENUINE_WORKFLOW).read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/b.GENUINE_WORKFLOW;path.parent.mkdir(parents=True);path.write_bytes(original)
            def git(*argv):return subprocess.check_output(['git','-c','core.hooksPath=/dev/null','-C',str(root),*argv],stderr=subprocess.PIPE).strip()
            git('init','-q');git('add','--',b.GENUINE_WORKFLOW)
            git('-c','user.name=Fictional regression','-c','user.email=fixture@example.invalid','commit','-qm','fictional local controller closure')
            commit=git('rev-parse','HEAD').decode()
            self.assertEqual(b.sha(b.genuine_driver(root,commit)),b.STAGED_POLICY_GENUINE_DRIVER)
            self.assertEqual(r.checked_driver(root,commit),r.STAGED_POLICY_DRIVER)
            before=path.stat();path.write_bytes(changed_actual_controller_contract(original))
            os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
            with self.assertRaisesRegex(RuntimeError,'differs from actual source'):b.genuine_driver(root,commit)
            with self.assertRaisesRegex(ValueError,'DEPENDENCY_DIFFERS_FROM_DISPATCH'):r.checked_driver(root,commit)
            git('add','--',b.GENUINE_WORKFLOW)
            git('-c','user.name=Fictional regression','-c','user.email=fixture@example.invalid','commit','-qm','unsupported local contract control')
            changed=git('rev-parse','HEAD').decode()
            with self.assertRaisesRegex(RuntimeError,'Unknown genuine controller bytes'):b.genuine_driver(root,changed)
            with self.assertRaisesRegex(ValueError,'CLOSED_DRIVER_IDENTITY'):r.checked_driver(root,changed)

    def test_controller_binds_actual_week8_config_and_keeps_week7_originals(self):
        raw=self.controller()
        self.assertEqual(raw.BASE,'e336bf7a68c32267c3c3eec48892aeadcd03a90e')
        self.assertEqual(raw.REVIEWED_MAIN_TREE,'26c1ca52eb1d9b3610a552ecf63ccd2fab5ad8f8')
        self.assertEqual(raw.WEEKLY_POLICY_SHA256,'cc075055cec92d3eadd16d4a927cea7c787616f63dcacb89277dca409b24b90b')
        self.assertEqual(len(raw.FIXED),3)
        self.assertEqual(sum('/2026/w07/' in name for name in raw.FIXED),2)
        self.assertEqual(raw.FIXED['data/verification/partial-schedule-baselines/2026/w08/5abfdeef1e84f866463a470f2d05292e4f3af286cca622ef33f564d1da58624f.json.gz'],
            'cf9d319eaf9226dc6288fd75b9af6d1f438882f7f6e857b9b736b96eb76464fa')
        self.assertFalse(any('/partial-registrations/2026/w08/' in name for name in raw.FIXED))

    def test_current_controller_accounts_for_actual_phase2_hourly_required_work(self):
        import ast
        import re
        commit=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
        tree=ast.parse(b.genuine_driver(ROOT,commit))
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        hourly=(ROOT/'.github/workflows/hourly.yml').read_text()
        offline=hourly.split('      - name: Required offline regression tests\n',1)[1].split('      - name: Preserve original grading output\n',1)[0]
        required={tuple((('--check',) if check else ())+ (path,)) for check,path in
            re.findall(r'\bnode\s+(--check\s+)?([A-Za-z0-9_./-]+\.(?:cjs|js))',offline)}
        actual=[]
        for node in ast.walk(main):
            if isinstance(node,ast.List) and node.elts and isinstance(node.elts[0],ast.Constant) and node.elts[0].value=='node':
                actual.append(tuple(ast.literal_eval(node)[1:]))
        self.assertEqual(len(actual),len(required));self.assertEqual(set(actual),required)
        for missing in ('tests/test-weekly-overlay.cjs','tests/test-selected-rankings.cjs','tests/test-classic-ranking-model.cjs'):
            with self.subTest(missing=missing),self.assertRaises(AssertionError):
                self.assertEqual(set(actual)-{(missing,)},required)
        calls=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='run']
        validate=[n for n in calls if len(n.args)>1 and isinstance(n.args[1],ast.List) and
            any(isinstance(item,ast.Constant) and item.value=='--validate-generation' for item in n.args[1].elts)]
        proofs=[n for n in calls if len(n.args)>2 and isinstance(n.args[2],ast.Constant) and n.args[2].value is True]
        self.assertEqual(len(validate),hourly.count('python tools/phase2_capture.py --mode live --validate-generation'))
        self.assertEqual(len(validate),2)
        normal=hourly.split('      - name: Deploy validated output\n',1)[0]
        self.assertEqual(len(proofs),normal.count('python tools/source_ci.py verify'))
        self.assertEqual(hourly.count('python tools/source_ci.py verify'),len(proofs)+1)  # Deployment-retry-only proof is outside this nondeploy case.
        self.assertEqual([n.args[0].value for n in sorted(proofs,key=lambda n:n.lineno)],
            ['source-ci-before','source-ci-before-data-commit','source-ci-after-stage','source-ci-before-case-completion'])
        advisory=next(n for n in calls if n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='legacy-advisory')
        self.assertTrue(all(n.lineno<advisory.lineno for n in validate))
        tar=next(n for n in calls if n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='pages-tar')
        complete=next(n for n in ast.walk(main) if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and n.value.value=='COMPLETE_GENUINE_NONDEPLOY_CASE')
        final=next(n for n in proofs if n.args[0].value=='source-ci-before-case-completion')
        frozen=next(n for n in ast.walk(main) if isinstance(n,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='FROZEN_CONTRACT_CHANGED' for a in n.args))
        self.assertLess(tar.lineno,final.lineno);self.assertLess(frozen.lineno,final.lineno);self.assertLess(final.lineno,complete.lineno)
        guard=next(n for n in ast.walk(main) if isinstance(n,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='FINAL_DATA_COMMIT_SOURCE_CI_BINDING' for a in n.args))
        self.assertGreater(guard.lineno,final.lineno);self.assertLess(guard.lineno,complete.lineno)
        self.assertEqual(b.GENUINE_DRIVER_BYTES[b.PRESENCE_GENUINE_DRIVER],37167)
        self.assertEqual(b.GENUINE_DRIVER_CONTRACTS[b.PRESENCE_GENUINE_DRIVER],b.PRESENCE_CONTRACT)
        self.assertEqual(b.GENUINE_DRIVER_CONTRACTS[b.CURRENT_PRESENCE_GENUINE_DRIVER],b.PRESENCE_CONTRACT)
        self.assertNotEqual(b.PRESENCE_GENUINE_DRIVER,b.CURRENT_PRESENCE_GENUINE_DRIVER)

    def test_actual_controller_retains_both_nested_cache_lanes_and_signed_zero_values(self):
        raw=self.controller();r=self.r
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);expected={}
            for lane in ('stat-keys-fgm-v1','stat-keys-presence-fgm-v2'):
                name='data/cache/'+lane+'/stats_2026_08.json';path=root/name;path.parent.mkdir(parents=True)
                body=r.canonical({'FICTIONAL':{'rec':0,'rush_yd':-3,'pass_yd':None}});path.write_bytes(body);expected[name]=body
            after=raw.inventory(root);payload,receipts,representations=raw.new_payloads(root,{},after,{})
            self.assertEqual(receipts,[]);self.assertEqual(set(representations),set(expected))
            self.assertEqual({name:path.read_bytes() for name,path in payload},{'mutable/'+n:v for n,v in expected.items()})
            self.assertTrue(all(r.role(name)=='cache_or_board' for name in expected))
            self.assertEqual(raw.new_payloads(root,after,after,{}),([],[],{}))

    def test_unknown_nested_cache_lanes_or_weeks_are_not_exportable(self):
        raw=self.controller();r=self.r
        for name in ('data/cache/unreviewed/stats_2026_08.json',
                'data/cache/stat-keys-presence-fgm-v2/stats_2026_00.json',
                'data/cache/stat-keys-fgm-v1/stats_2026_99.json'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);path=root/name;path.parent.mkdir(parents=True);path.write_bytes(b'{}')
                self.assertIsNone(r.role(name))
                with self.assertRaisesRegex(RuntimeError,'UNCLASSIFIED_OUTPUT_DELTA'):
                    raw.new_payloads(root,{},raw.inventory(root),{})

    def test_v4_complete_archive_preserves_nested_caches_and_rejects_changed_bytes(self):
        r=self.r
        for lane in ('stat-keys-fgm-v1','stat-keys-presence-fgm-v2'):
            name='data/cache/'+lane+'/stats_2026_08.json'
            entries=self.archive(cache=(name,b'{"FICTIONAL":{"rec":0,"rush_yd":-3}}'))
            r.controller_archive(self.helper.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=r.PRESENCE_DRIVER)
            entries['mutable/'+name]=b'{"FICTIONAL":{"rec":1,"rush_yd":-3}}'
            with self.assertRaisesRegex(ValueError,'CONTROLLER_MUTABLE_BYTES'):
                r.controller_archive(self.helper.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=r.PRESENCE_DRIVER)

    def test_nested_caches_do_not_expand_legacy_v2_v3_archive_contracts(self):
        r=self.r;name='data/cache/stat-keys-fgm-v1/stats_2026_08.json'
        for contract,digest in ((r.WEEKLY_CONTRACT,r.WEEKLY_DRIVER),(r.RANKING_CONTRACT,r.DRIVER)):
            entries=self.archive(contract=contract)
            r.controller_archive(self.helper.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=digest)
            entries=self.archive(contract=contract,cache=(name,b'{}'))
            with self.assertRaisesRegex(ValueError,'PRESENCE_CONTROLLER_REQUIRED'):
                r.controller_archive(self.helper.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=digest)

    def test_v4_wrong_main_or_crossed_driver_and_private_cache_fail(self):
        r=self.r;entries=self.archive()
        with self.assertRaisesRegex(ValueError,'CONTROLLER_SOURCE_CONTRACT'):
            r.controller_archive(self.helper.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=r.DRIVER)
        case=r.parsed(entries['RELEASE_CASE_MANIFEST.json']);case['reviewed_main_base']='0'*40
        entries['RELEASE_CASE_MANIFEST.json']=r.canonical(case)
        with self.assertRaisesRegex(ValueError,'CONTROLLER_REVIEWED_MAIN_SOURCE'):
            r.controller_archive(self.helper.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=r.PRESENCE_DRIVER)
        name='data/cache/stat-keys-presence-fgm-v2/stats_2026_08.json'
        entries=self.archive(cache=(name,b'{"access_token":"FICTIONAL_CONTROL"}'))
        with self.assertRaisesRegex(ValueError,'PRIVATE_FIELD'):
            r.controller_archive(self.helper.tar(entries),'a'*40,'COMPLETE_GENUINE_NONDEPLOY_CASE',driver=r.PRESENCE_DRIVER)


class DiagnosticLifetimeDependencyContract(unittest.TestCase):
    def test_frozen_and_new_seed_contracts_and_direct_child_dependency(self):
        self.assertIn('tools/seed_checkpoint_frontier.py', b.FILES)
        self.assertEqual(b.PREPARATION24_LIFETIME_INTEGRITY,
            '3c68e0b8e88b458dc5ecb0dce1376160e668e1941e3e2302bce3e35a38a08f77')
        expected=frozenset(b.SEED_NAMES | {
            'seed_checkpoint_frontier.py','source_ci.py','operating_seed_transport.py'})
        self.assertEqual(b.SEED_CONTRACTS[b.PREPARATION24_LIFETIME_INTEGRITY],expected)
        for version in (b.CONTINUED_SEED_INTEGRITY,b.FINISHED22_SEED_INTEGRITY,
                b.PREPARATION22_RETRIEVAL_INTEGRITY):
            self.assertEqual(b.SEED_CONTRACTS[version],expected)
        self.assertEqual(b.SEED_CONTRACTS[b.SEED_INTEGRITY],frozenset(b.SEED_NAMES))
        self.assertEqual(b.SEED_CONTRACTS[b.CURRENT_MAIN_WEEKLY_INTEGRITY],expected)
        self.assertEqual(b.SEED_CONTRACTS[b.CARRIED_PREFIX_SEED_INTEGRITY],expected)
    def test_carried_manifest_changes_only_wrapper_and_preserves_older_manifests(self):
        manifest=json.loads((ROOT/'tools/cloud-seed-integrity.json').read_bytes())
        self.assertEqual(b.sha((ROOT/'tools/cloud-seed-integrity.json').read_bytes()),b.CARRIED_PREFIX_SEED_INTEGRITY)
        self.assertEqual(manifest['files']['cloud_seed_prepare.py'],
            b.sha((ROOT/'tools/cloud_seed_prepare.py').read_bytes()))
        self.assertEqual(manifest['files']['source_ci.py'],
            'f3728b363e3556771b48e9e9ed761928ca9078fa842beae5551a982d7820b619')
        self.assertEqual(len(manifest['files']),12)
        self.assertNotIn('operating_resource_bootstrap.py',manifest['files'])
        retained=copy.deepcopy(manifest)
        retained['files']['cloud_seed_prepare.py']='1deb47bc1424024db9e5743cb2c85191bc9416c8de28bba47b8bf8fbb5aa3586'
        self.assertEqual(b.sha((json.dumps(retained,sort_keys=True,indent=2)+'\n').encode()),b.CURRENT_MAIN_WEEKLY_INTEGRITY)
        retained['files']['source_ci.py']='f7bb054c9299a226ae9f30aa71b8f5afeca07b2ee37c853aad7abc40360e59cd'
        self.assertEqual(b.sha((json.dumps(retained,sort_keys=True,indent=2)+'\n').encode()),b.PREPARATION24_LIFETIME_INTEGRITY)


class BrowserFailureTelemetryAndCaptureBinding(unittest.TestCase):
    """Pure source-bound controls; no browser, source-CI run, provider, or backend claim."""
    def helpers(self):
        import ast
        text=(ROOT/'.github/workflows/prepare-diagnostic-seed.yml').read_text()
        block=text.split('  generated-browser-acceptance:\n',1)[1].split('  public-browser-acceptance:\n',1)[0]
        block=block.split("python -P - <<'PY'\n",1)[1].split('          PY\n',1)[0]
        reader='\n'.join(line[10:] if line.startswith('          ') else line for line in block.splitlines())
        names={'BROWSER_DIAGNOSTIC_PHASES','BROWSER_DIAGNOSTIC_KINDS','BROWSER_READER_CODES','CAPTURE_F130','CAPTURE_F130_MANIFEST','DIAGNOSTIC_SOURCE_PATHS','F130_ARTIFACT_APPROVAL'}
        functions={'parse_browser_failure','private_browser_failure','browser_reader_code','capture_source_for_approval','require_f130_source_ci','compare_diagnostic_sources'}
        nodes=[n for n in ast.parse(reader).body if isinstance(n,ast.FunctionDef) and n.name in functions or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets)]
        def need(value,reason):
            if not value:raise ValueError(reason)
        def pairs(items):
            value={}
            for key,item in items:need(key not in value,'DUPLICATE');value[key]=item
            return value
        import hashlib
        namespace=dict(json=json,subprocess=subprocess,need=need,pairs=pairs,
            canonical=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode(),
            sha=lambda raw:hashlib.sha256(raw).hexdigest())
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-browser-reader-controls','exec'),namespace)
        return namespace
    def old_source(self):
        spec=importlib.util.spec_from_file_location('source_ci_for_diagnostic_contract',ROOT/'tools/source_ci.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.source(ROOT,'f1303ee9dfac61fb47fb6820eabd1d04b36f173c',actual=False)
    def changed_source(self,change=None):
        h=self.helpers();old=self.old_source();new=copy.deepcopy(old);new['commit']='9'*40
        if change:change(new)
        new['source_manifest_sha256']=h['sha'](h['canonical'](new['files']))
        return h,old,new
    def test_actual_f130_manifest_allows_only_named_diagnostic_delta(self):
        def change(value):
            entry=next(f for f in value['files'] if f['path']=='tools/release_browser.cjs')
            entry.update(blob='9'*40,sha256='8'*64,bytes=entry['bytes']+1)
        h,old,new=self.changed_source(change)
        self.assertEqual(len(old['files']),123)
        self.assertEqual(h['compare_diagnostic_sources'](old,new)['difference_count'],1)
    def test_product_blob_or_mode_difference_rejected(self):
        for field,value in (('sha256','8'*64),('mode','100755')):
            def change(current):
                next(f for f in current['files'] if f['path']=='output/app.js')[field]=value
            h,old,new=self.changed_source(change)
            with self.assertRaisesRegex(ValueError,'APPLICATION_OR_VALIDATOR'):h['compare_diagnostic_sources'](old,new)
    def test_unexpected_or_missing_source_path_rejected(self):
        for change in (lambda v:v['files'].append(dict(path='tools/unapproved_diagnostic.py',mode='100644',blob='1'*40,sha256='2'*64,bytes=1)),lambda v:v['files'].pop()):
            h,old,new=self.changed_source(change)
            with self.assertRaisesRegex(ValueError,'NAMESPACES'):h['compare_diagnostic_sources'](old,new)
    def test_old_source_hash_or_caller_declared_manifest_cannot_substitute(self):
        h,old,new=self.changed_source();bad=copy.deepcopy(old);bad['source_manifest_sha256']='0'*64
        with self.assertRaises(ValueError):h['compare_diagnostic_sources'](bad,new)
        new['files'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'DIGESTS'):h['compare_diagnostic_sources'](old,new)
    def test_only_exact_immutable_old_artifact_approval_crosses_source(self):
        h=self.helpers();approval=copy.deepcopy(h['F130_ARTIFACT_APPROVAL'])
        self.assertEqual(h['capture_source_for_approval'](approval,'9'*40),h['CAPTURE_F130'])
        for key,value in (('case_run_id',40099428553),('artifact_id',12563140142),('source','8'*40),('artifact_sha256','0'*64)):
            bad=copy.deepcopy(approval);bad[key]=value
            with self.assertRaises(ValueError):h['capture_source_for_approval'](bad,'9'*40)
    def test_legacy_same_source_selection_remains_generic(self):
        h=self.helpers();value=copy.deepcopy(h['F130_ARTIFACT_APPROVAL']);value.update(source='9'*40,case_run_id=101,artifact_id=202)
        self.assertEqual(h['capture_source_for_approval'](value,'9'*40),'9'*40)
    def test_old_qualified_ci_identity_must_be_original_not_new_source(self):
        h=self.helpers();value=dict(schema_version='source-ci-verification-v1',executed_commit=h['CAPTURE_F130'],executed_tree='13cd5461b81bf775c4fd415640de70d28a5edf69',source_ci_commit=h['CAPTURE_F130'],source_manifest_sha256=h['CAPTURE_F130_MANIFEST'],run_id=40091905641,run_attempt=1,job_id=120866138326,seal_sha256='d15f4084d2e7aad9e7c2282c2864684469106873bd6e8a40c4e53b14d0f88fee')
        h['require_f130_source_ci'](value)
        for key,wrong in (('source_ci_commit','9'*40),('seal_sha256','0'*64),('run_id',40091905642),('run_attempt',True)):
            bad=copy.deepcopy(value);bad[key]=wrong
            with self.assertRaises(ValueError):h['require_f130_source_ci'](bad)
    def diagnostic_line(self,**changes):
        value=dict(schema_version='release-browser-failure-diagnostic-v1',stage='B016',kind='ASSERTION',viewport=1280);value.update(changes)
        return b'NFL_BROWSER_FAILURE_DIAGNOSTIC_V1='+json.dumps(value,separators=(',',':')).encode()+b'\n'
    def test_private_log_parser_exports_only_fixed_enum_record(self):
        h=self.helpers();raw=b'private raw message and player text omitted\n'+self.diagnostic_line()
        self.assertEqual(h['parse_browser_failure'](raw),dict(browser_failure_stage='B016',browser_failure_kind='ASSERTION',browser_failure_viewport=1280))
    def test_private_log_parser_rejects_unknown_fields_values_and_duplicates(self):
        h=self.helpers()
        for raw in (self.diagnostic_line(secret='PRIVATE_VALUE'),self.diagnostic_line(stage='PRIVATE_VALUE'),self.diagnostic_line(kind='PRIVATE_VALUE'),self.diagnostic_line(viewport=True),self.diagnostic_line()+self.diagnostic_line()):
            result=h['parse_browser_failure'](raw);self.assertEqual(result['browser_failure_stage'],'INVALID');self.assertNotIn('PRIVATE_VALUE',json.dumps(result))
    def test_missing_diagnostic_and_raw_exception_never_export_message(self):
        h=self.helpers();self.assertEqual(h['parse_browser_failure'](b'raw private error')['browser_failure_stage'],'UNAVAILABLE')
        self.assertEqual(h['browser_reader_code'](ValueError('PRIVATE_URL_OR_PLAYER')),'UNCLASSIFIED')
        self.assertEqual(h['browser_reader_code'](ValueError('PREINSTALLED_CHROME_UNAVAILABLE')),'PREINSTALLED_CHROME_UNAVAILABLE')
    def node_diagnostic(self,expression):
        script=(ROOT/'tools/release_browser.cjs').read_text().split('// BEGIN BOUNDED BROWSER FAILURE TELEMETRY\n',1)[1].split('// END BOUNDED BROWSER FAILURE TELEMETRY',1)[0]
        code="const output=[];const process={stderr:{write:v=>output.push(v)},on:()=>{}};\n"+script+"\n"+expression+"\nconsole.log(JSON.stringify(output));"
        result=subprocess.run(['node','-e',code],text=True,capture_output=True,timeout=10,check=True)
        return json.loads(result.stdout)
    def test_actual_cjs_fixed_phase_class_and_single_emission(self):
        lines=self.node_diagnostic("browserPhase='B010';browserViewport=390;reportBrowserFailure(Object.assign(new Error('PRIVATE_URL_OR_PLAYER'),{code:'ENOENT'}));reportBrowserFailure(new Error('SECOND_PRIVATE'));")
        self.assertEqual(len(lines),1);self.assertNotIn('PRIVATE',lines[0])
        value=json.loads(lines[0].split('=',1)[1]);self.assertEqual((value['stage'],value['kind'],value['viewport']),('B010','ENOENT',390))
    def test_actual_cjs_unknown_error_properties_and_forced_values_cannot_leak(self):
        lines=self.node_diagnostic("browserPhase='PRIVATE_STAGE';browserViewport=42;reportBrowserFailure({name:'__proto__',message:'PRIVATE_MESSAGE',code:'PRIVATE_CODE'},'PRIVATE_FORCED');")
        self.assertNotIn('PRIVATE',lines[0]);value=json.loads(lines[0].split('=',1)[1]);self.assertEqual((value['stage'],value['kind'],value['viewport']),('B001','OTHER',0))


if __name__=='__main__':unittest.main(verbosity=2)
