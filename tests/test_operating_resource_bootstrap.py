"""Pure/mocked root-control regressions, NOT privileged/backend qualification."""
import copy
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

    def test_latest_twelve_file_contract_binds_finished_helpers(self):
        value=self.check()
        self.assertEqual(value['files']['tools/cloud-seed-integrity.json']['sha256'],b.FINISHED22_SEED_INTEGRITY)
        self.assertEqual(len(b.SEED_CONTRACTS[b.FINISHED22_SEED_INTEGRITY]),12)

    def test_only_three_exact_contracts_are_recognized(self):
        self.assertEqual(set(b.SEED_CONTRACTS),{
            'bfb48f36d1db5b2980235238e1b869efb183f23095ff72cee33c1d88e84a3b26',
            'ed5b6773c3d4e642bf4346aa2b9de89a2b580a1f34e97bddc6172b068a388611',
            '636b3cd2a966346df02ad30c516dc805e40ae082e1b4f5e7b757162c29e6459f'})
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


if __name__=='__main__':unittest.main(verbosity=2)
