"""Dedicated manual operating diagnostic with no provider or import-time actions.

P5 remains the immutable B3 seed builder. This wrapper never alters its bytes,
input contract or original observations. A trusted Actions-only coordinator
performs all three real source-CI checks. Every application/check subprocess
tree uses the unchanged network guard with credentials removed. Actual source,
retrieval, checks and packaging costs remain inside the measured job.
"""
import argparse
import copy
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
import importlib.util
from pathlib import Path
import resource
import re
import selectors
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
from unittest.mock import patch
import operating_diagnostic as seed_v1
from seed_checkpoint_frontier import operation_lifetime
from operating_diagnostic import (BASE, CAMPAIGN, NOTICE, SEED_HOUR, START, Provider,
    Resources, assert_local_tree, bind, bounded, commit, encoded, external, git, put,
    require_offline, sha)

SEED_HARNESS_SHA256='441f0ccaa1b274708419643d993896b5ff6f2c4118e0016719c80a1746289328'
CAMPAIGN_WORKFLOW='.github/workflows/operating-diagnostic.yml'
DEPENDENCIES=('tools/operating_diagnostic.py','tools/source_ci.py',
    'tools/diagnostic_network_guard.py','tools/diagnostic_seed.py','tools/diagnostic_resources.py',
    'tools/cloud-seed-integrity.json','tools/diagnostic-seed-inputs.json','tools/cloud-seed-requirements.txt',
    'tools/operating_seed_transport.py','tools/operating_resource_bootstrap.py',
    'tools/seed_checkpoint_frontier.py')
JSON_LIMIT=16*1024**2
SOURCE_FILE_LIMIT=32*1024**2
SEED_BYTES_LIMIT=8*1024**3
ENTRY_LIMIT=20000
EVIDENCE_ENTRIES=200000
HEX40=re.compile(r'[0-9a-f]{40}')
HEX64=re.compile(r'[0-9a-f]{64}')
# Closed website-only additions to a separate B3-derived execution copy. These
# do not repin the original seed, engine, historical policy or registration.
WEEKLY_POLICY='config/weekly-derived-selected-policy-v3.json'
WEEKLY_POLICY_SHA256='5ddd3af107f1a547fca3100be792a5c2c1b35d26415e1bb8eaf03164f9df4193'
WEEKLY_EXECUTION_ADDITIONS={
    'config/weekly-derived-selected-policy-v1.json':'0bcdf8505d2f0d268ea97e5c17c26f2a8d7cb91ef2e089cd9e410f27eb36f1ae',
    'config/weekly-derived-selected-policy-v2.json':'e8e037a00a22d3e0e07e41ed5816f2374e8f162a7fa78ea8cc45888ed2e2f094',
    WEEKLY_POLICY:WEEKLY_POLICY_SHA256,
    'output/weekly-adaptive-overlay.js':'d6657e82639aa001f64701672e25cc72bd6e55142127669a59396f9efe485a68',
}


def _stage_clock(start,tick):
    end=time.monotonic()
    return dict(start=tick-start,end=end-start,seconds=end-tick)


GIB=1024**3
MIB=1024**2
METRICS=('working_tree_bytes','clean_checkout_bytes','staged_bytes','uploader_tar_bytes','packed_bytes')


def _bytes(value,name):
    if type(value) is not int or value<0:raise RuntimeError('Missing supported allocation metric: '+name)
    return value


def pretransport_plan(approved):
    # Transport permits <=2GiB decoded ZIP members, distinct from later tar expansion.
    archive=_bytes(approved.get('archive_bytes'),'approved.archive_bytes')
    if not 0<archive<=2*GIB:raise RuntimeError('Unsupported approved archive bound')
    return {'artifact_zip':archive,'maximum_decoded_zip_members':2*GIB}


def seed_plan(manifest,metrics,source):
    """Additional allocation after retained compressed parents already exist.

    W includes Git; sum(files) does not. Never count W+all files as disjoint.
    source.executable_bytes/source.git_object_bytes are actual bounded inventories
    of the candidate checkout/complete nonalternate Git store, never a guess.
    """
    if type(manifest.get('files')) is not dict or type(manifest.get('packs')) is not list or not manifest['packs']:
        raise RuntimeError('Complete verified seed inventory is required')
    working=sum(_bytes(d.get('bytes'),'seed.files.bytes') for d in manifest['files'].values())
    packs=sum(_bytes(d.get('bytes'),'seed.packs.bytes') for d in manifest['packs'])
    objects=sum(_bytes(d.get('objects'),'seed.packs.objects') for d in manifest['packs'])
    values={k:_bytes(metrics.get(k),k) for k in METRICS}
    executable=_bytes(source.get('executable_bytes'),'candidate.executable_bytes')
    git_objects=_bytes(source.get('git_object_bytes'),'candidate.git_object_bytes')
    if source.get('complete_nonalternate_git_store') is not True:
        raise RuntimeError('Candidate Git closure allocation is unestablished')
    # Two index tables/offsets plus fixed Git/filesystem metadata. This term is
    # explicitly estimated, including source tree indexes and journal overhead.
    indexes=objects*64+64*MIB
    primary=max(working+packs,values['working_tree_bytes'])+indexes
    restart=max(primary,values['clean_checkout_bytes'])
    gc=2*max(packs,values['packed_bytes'])
    # One fixed material correction can rewrite every report/body. Reserve one
    # complete measured working tree plus a second report working-set copy; this
    # is conservative for the frozen input lineage, not arbitrary future updates.
    update=primary+2*values['staged_bytes']
    source_copy=2*executable+2*git_objects
    pages=3*values['staged_bytes']  # admission, independent restart, sample pages coexist
    tars=2*values['uploader_tar_bytes']
    # 25% of copying/report representation work and a 64MiB fixed logs/metadata
    # allowance are prospectively frozen uncertainty allowances, not evidence padding.
    subtotal=primary+restart+gc+update+source_copy+pages+tars
    return {'restored_primary_tree_and_git':primary,'independent_restart_checkout':restart,
        'git_gc_temporary_pack_bound':gc,'new_update_capture_report_bound':update,
        'candidate_source_copy_and_git_import':source_copy,'three_pages_roots':pages,
        'two_uploader_tars':tars,'metadata_logs_allocation_uncertainty':math.ceil(subtotal/4)+64*MIB}


def admission_allocation(items,critical_paths=()):
    """items are (label, actual_destination_path, additional_byte_estimate)."""
    groups={}
    for label,path,count in [*items,*[('critical_no_new_allocation',p,0) for p in critical_paths]]:
        count=_bytes(count,label);p=Path(path).resolve()
        while not p.exists():p=p.parent
        info=p.stat();disk=shutil.disk_usage(p);key=str(info.st_dev)
        entry=groups.setdefault(key,{'filesystem_probe':str(p),'total':disk.total,'free':disk.free,'additional':0,'terms':[]})
        if entry['total']!=disk.total:raise RuntimeError('Filesystem changed during allocation admission')
        entry['free']=min(entry['free'],disk.free);entry['additional']+=count
        entry['terms'].append({'label':label,'path':str(Path(path).resolve()),'estimated_additional_bytes':count})
    if not groups:raise RuntimeError('No allocation filesystems established')
    for entry in groups.values():
        entry['required_reserve']=max(2*GIB,(entry['total']+4)//5)
        entry['required_free_before_allocation']=entry['additional']+entry['required_reserve']
        entry['pass']=entry['free']>=entry['required_free_before_allocation']
    if not all(entry['pass'] for entry in groups.values()):
        raise RuntimeError('Planned peak allocation would consume required disk headroom')
    return {'status':'ESTIMATED_PEAK_ALLOCATION_ADMITTED_NOT_RESOURCE_PASS','filesystems':groups,
        'uncertainty':'Frozen-lineage estimates; supervisor monitors actual reserve and stops on violation'}


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise RuntimeError('Duplicate marker key')
        result[key]=value
    return result


def _decoded(raw,limit=JSON_LIMIT):
    if len(raw)>limit:raise RuntimeError('Bounded JSON exceeded')
    try:return json.loads(raw,object_pairs_hook=_pairs,parse_constant=lambda _:(_ for _ in ()).throw(RuntimeError('Nonfinite marker value')))
    except (UnicodeError,json.JSONDecodeError) as error:raise RuntimeError('Malformed marker') from error


def _bounded_file(path,limit=SOURCE_FILE_LIMIT):
    fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size>limit:raise RuntimeError('Nonregular or oversized dependency')
        value=bytearray()
        while True:
            chunk=os.read(fd,min(65536,limit+1-len(value)))
            if not chunk:break
            value.extend(chunk)
            if len(value)>limit:raise RuntimeError('Dependency grew beyond its bound')
        return bytes(value)
    finally:os.close(fd)


def _load(path):
    value=_decoded(_bounded_file(path,JSON_LIMIT))
    if type(value) is not dict:raise RuntimeError('Object marker required')
    return value


def _hash_file(path,limit=SOURCE_FILE_LIMIT):
    fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW);h=hashlib.sha256();size=0
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise RuntimeError('Nonregular dependency')
        while True:
            chunk=os.read(fd,65536)
            if not chunk:break
            size+=len(chunk)
            if size>limit:raise RuntimeError('Dependency exceeds bounded size')
            h.update(chunk)
        return h.hexdigest()
    finally:os.close(fd)


def _fresh_cli(code,action,environment,run_id=None):
    """Bounded memory transport only; the helper CLI supplies all authority."""
    command=[sys.executable,str(code/'tools/source_ci.py'),action,'--root',str(code)]
    if run_id is not None:
        if action!='verify' or type(run_id) is not int or run_id<1:raise RuntimeError('Invalid fixed CI run')
        command.extend(('--run-id',str(run_id)))
    process=subprocess.Popen(command,cwd=code,env=environment,stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
    result=bytearray();deadline=time.monotonic()+60
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout,selectors.EVENT_READ)
            while ready.get_map():
                if time.monotonic()>=deadline:raise RuntimeError('Source-CI CLI exceeded bounded command time')
                for key,_ in ready.select(min(1,max(.01,deadline-time.monotonic()))):
                    raw=os.read(key.fd,65536)
                    if not raw:ready.unregister(key.fileobj);continue
                    if len(result)+len(raw)>2*1024**2:raise RuntimeError('Source-CI CLI output exceeds bound')
                    result.extend(raw)
        if process.wait(timeout=max(.01,deadline-time.monotonic())):raise RuntimeError('Required source-CI CLI rejected')
        value=_decoded(result,2*1024**2)
        if type(value) is not dict:raise RuntimeError('Source-CI object required')
        return value
    except BaseException:
        if process.poll() is None:os.killpg(process.pid,9);process.wait()
        raise
    finally:process.stdout.close()

def _bounded_stage(command,cwd,log,timeout,*,log_limit=16*1024**2,environment=None):
    """Keep draining output after the private log cap; do not limit asset files."""
    process=subprocess.Popen(command,cwd=cwd,stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True,env=environment)
    deadline=time.monotonic()+timeout;kept=0
    try:
        with log.open('xb') as output,selectors.DefaultSelector() as ready:
            ready.register(process.stdout,selectors.EVENT_READ)
            while ready.get_map():
                if time.monotonic()>=deadline:raise TimeoutError('Diagnostic stage deadline')
                for key,_ in ready.select(min(1,max(.01,deadline-time.monotonic()))):
                    raw=os.read(key.fd,65536)
                    if not raw:ready.unregister(key.fileobj);continue
                    if kept<log_limit:
                        piece=raw[:log_limit-kept];output.write(piece);kept+=len(piece)
        rc=process.wait(timeout=max(.01,deadline-time.monotonic()))
        if rc:raise subprocess.CalledProcessError(rc,command)
    except BaseException:
        if process.poll() is None:os.killpg(process.pid,9);process.wait()
        raise
    finally:process.stdout.close()


def _source_ci_cli(code,action,run_id=None):
    """Use the exact helper CLI import boundary; never reconstruct its verdict."""
    if action not in ('verify','fingerprint') or Path.cwd().resolve()!=code:
        raise RuntimeError('Exact source-CI CLI/cwd required')
    # Every helper child gets an independently empty 0700 prefix BEFORE startup.
    # Reusing the parent's empty-looking prefix is not this contract.
    parent=Path(os.environ['RUNNER_TEMP']).resolve()
    cache=Path(tempfile.mkdtemp(prefix='nfl-source-ci-pyc-',dir=parent));cache.chmod(0o700)
    environment=dict(os.environ,PYTHONPYCACHEPREFIX=str(cache),PYTHONDONTWRITEBYTECODE='1')
    failed=False
    try:return _fresh_cli(code,action,environment) if run_id is None else _fresh_cli(code,action,environment,run_id)
    except BaseException:failed=True;raise
    finally:
        try:
            with os.scandir(cache) as items:empty=next(items,None) is None
            if empty:cache.rmdir()
            elif not failed:raise RuntimeError('Source-CI child populated its inactive prefix')
        except OSError:
            if not failed:raise


def _matched_source_ci(verification,fingerprint):
    expected={'executed_commit':fingerprint['commit'],'executed_tree':fingerprint['tree'],
        'source_manifest_sha256':fingerprint['source_manifest_sha256'],
        'environment_sha256':sha(encoded(fingerprint['environment']))}
    if (verification.get('schema_version')!='source-ci-verification-v1'
            or verification.get('claim')!='COMPLETE_SOURCE_CHECKS_ONLY_NOT_GENERATION_OR_OPERATING_QUALIFICATION'
            or any(verification.get(k)!=v for k,v in expected.items())):
        raise RuntimeError('Fresh source/runtime differs from authenticated CI verification')


def _runtime_identity(environment):
    values=environment.get('distributions')
    if (type(values) is not list or len(values)>ENTRY_LIMIT
            or any(type(v) is not dict or set(v)!={'name','version'} or any(type(x) is not str or not x for x in v.values()) for v in values)
            or type(environment.get('python')) is not dict or type(environment['python'].get('version')) is not str
            or type(environment.get('node')) is not dict or type(environment['node'].get('version')) is not str):
        raise RuntimeError('Incomplete authenticated runtime identity')
    return {'python':environment['python']['version'],'node':environment['node']['version'],'distributions':copy.deepcopy(values)}


def _guarded_stage(code,command,log,timeout):
    cache=Path(tempfile.mkdtemp(prefix='nfl-dataflow-pyc-',dir=Path(os.environ['RUNNER_TEMP'])));cache.chmod(0o700)
    environment={k:v for k,v in os.environ.items() if k not in ('GH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY','OPENAI_API_KEY')}
    environment.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPYCACHEPREFIX=str(cache))
    guarded=[sys.executable,str(code/'tools/diagnostic_network_guard.py'),'--',*command]
    failed=False
    try:return _bounded_stage(guarded,code,log,timeout,environment=environment)
    except BaseException:failed=True;raise
    finally:
        # No app evidence is removed; inactive empty interpreter prefixes only.
        try:
            if not any(cache.iterdir()):cache.rmdir()
        except OSError:
            if not failed:raise


def _worker_argv(code,root,result,sample_number):
    values=['/usr/bin/env']
    for name in ('GIT_CONFIG_COUNT','GIT_CONFIG_KEY_0','GIT_CONFIG_VALUE_0','GIT_CONFIG_GLOBAL','GIT_CONFIG_NOSYSTEM'):
        values.extend(('-u',name))
    return values+[sys.executable,str(code/'tools/operating_campaign.py'),'job','--code',str(code),
        '--root',str(root),'--result',str(result),'--sample-number',str(sample_number)]


def _job_context(code,root,result,sample_number):
    if any(os.environ.get(name) for name in ('AWS_SECRET_ACCESS_KEY','OPENAI_API_KEY')):
        raise RuntimeError('Unrelated credentials are forbidden')
    clean={k:v for k,v in os.environ.items() if k not in ('GH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY','OPENAI_API_KEY')}
    head=subprocess.check_output(['git','-C',str(code),'rev-parse','HEAD'],env=clean,text=True).strip()
    if Path(seed_v1.__file__).resolve()!=code/'tools/operating_diagnostic.py' or _hash_file(Path(seed_v1.__file__))!=SEED_HARNESS_SHA256:
        raise RuntimeError('Frozen P5 seed-builder identity changed')
    if (os.environ.get('GITHUB_RUN_ATTEMPT')!='1' or sample_number not in (1,2,3)
            or os.environ.get('GITHUB_SHA')!=head
            or os.environ.get('GITHUB_EVENT_NAME')!='workflow_dispatch'
            or os.environ.get('DIAGNOSTIC_RESOURCE_BACKEND')!='root-supervised-cgroup-v1'
            or Path(__file__).resolve()!=code/'tools/operating_campaign.py'
            or os.environ.get('CAMPAIGN_ID')!=CAMPAIGN
            or os.environ.get('GITHUB_ACTOR_ID')!='208912933'):
        raise RuntimeError('Wrong authenticated installed campaign/source/resource context')
    prefix=Path(sys.pycache_prefix or '/')
    if (not sys.dont_write_bytecode or not sys.pycache_prefix or prefix.is_symlink()
            or not prefix.is_dir() or stat.S_IMODE(prefix.stat().st_mode)!=0o700 or any(prefix.iterdir())):
        raise RuntimeError('Fresh inactive parent bytecode prefix required before startup')
    report=Path('/var/tmp')/('nfl-operating-'+os.environ['GITHUB_RUN_ID']+'-'+str(sample_number))/'RESOURCE.json'
    if os.environ.get('DIAGNOSTIC_RESOURCE_OUTPUT')!=str(report):
        raise RuntimeError('Exact root-protected operating resource path required')
    expected=Path(os.environ['RUNNER_TEMP']).resolve()/('nfl-operating-'+str(sample_number))
    if root!=expected/'fixture' or result!=expected/'RESULT.json' or root.exists():
        raise RuntimeError('Only a new exact runner-local fixture destination is allowed')


def _critical_paths(code,root,result):
    values=[code,Path(seed_v1.__file__),root,root.parent,result,root.parent/'retrieved-seed',
        root.parent/'sample-pages',root.parent/'sample-artifact.tar',Path(os.environ['RUNNER_TEMP']),
        Path('/tmp'),Path.home(),Path(sys.executable).resolve(),Path(sys.prefix),Path(sys.base_prefix),
        Path(os.environ['DIAGNOSTIC_RESOURCE_OUTPUT']),Path(os.environ['DIAGNOSTIC_RESOURCE_OUTPUT']).parent,
        Path(os.environ['RUNNER_TEMP'])/'operating-artifact-approval.json']
    values.extend(Path(p) for p in sysconfig.get_paths().values() if p)
    for name in ('node','git'):
        path=shutil.which(name)
        if not path:raise RuntimeError('Required runtime tool unavailable')
        values.append(Path(path).resolve())
    return list(dict.fromkeys(map(str,values)))


def _resource_preflight(code,root,result,sample_number):
    import diagnostic_resources as resources
    if Path(resources.__file__).resolve()!=code/'tools/diagnostic_resources.py':raise RuntimeError('Wrong actual resource backend')
    caps=resources.capability(_critical_paths(code,root,result))
    if caps.get('status')!='CAPABLE_PENDING_FRESH_PEAK_RESET':raise RuntimeError('HOSTED_PREFLIGHT_REQUIRED: attributable resource capability unavailable')
    current=Path(caps['current']);run=os.environ['GITHUB_RUN_ID']
    if (not re.fullmatch(r'nfl-diagnostic-'+re.escape(run)+'-'+str(sample_number)+r'-[0-9]+',current.name)
            or current.parent.name!='nfl-operating-'+run+'-'+str(sample_number)+'.service'
            or not any(value!='max' for value in caps['ancestor_limits'].values())):
        raise RuntimeError('Actual cgroup is not the reviewed operating job leaf')
    return caps  # Capability only. Final root-supervisor accounting is mandatory.


def _candidate_allocation(code):
    # Actual complete object-directory inventory, not a caller-supplied size.
    if git(code,'rev-parse','--is-shallow-repository')!='false' or os.environ.get('GIT_ALTERNATE_OBJECT_DIRECTORIES'):
        raise RuntimeError('Complete nonalternate candidate Git store required')
    objects=Path(git(code,'rev-parse','--git-path','objects'))
    if not objects.is_absolute():objects=code/objects
    objects=objects.resolve()
    if (objects/'info/alternates').exists() or (objects/'info/alternates').is_symlink():
        raise RuntimeError('Candidate Git alternates are unsupported')
    partial=subprocess.run(['git','-C',str(code),'config','--local','--get','extensions.partialClone'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    if partial.returncode not in (0,1) or partial.returncode==0:raise RuntimeError('Partial candidate Git store is unsupported')
    pending=[objects];total=0;entries=0
    while pending:
        directory=pending.pop()
        with os.scandir(directory) as values:
            for entry in values:
                entries+=1
                if entries>EVIDENCE_ENTRIES or entry.is_symlink():raise RuntimeError('Unsupported bounded Git object inventory')
                if entry.is_dir(follow_symlinks=False):pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):total+=entry.stat(follow_symlinks=False).st_size
                else:raise RuntimeError('Nonregular Git object store')
                if total>SEED_BYTES_LIMIT:raise RuntimeError('Candidate Git inventory exceeds supported preparation bound')
    names=_installed_names(code,('pull','tools','output'))
    executable=sum((code/name).stat().st_size for name in names)
    return dict(executable_bytes=executable,git_object_bytes=total,complete_nonalternate_git_store=True)


def _transport_allocation(code,root,result,approved):
    terms=pretransport_plan(approved)
    return admission_allocation([(k,root.parent/'retrieved-seed',v) for k,v in terms.items()],_critical_paths(code,root,result))


def _restoration_allocation(code,root,result,retrieved):
    manifest,_=_frozen_seed_manifest(root)
    if type(retrieved) is not dict or type(retrieved.get('admission_metrics')) is not dict:
        raise RuntimeError('Verified original admission allocation metrics are unavailable')
    terms=seed_plan(manifest,retrieved['admission_metrics'],_candidate_allocation(code))
    destinations={'restored_primary_tree_and_git':root,'independent_restart_checkout':root.parent/'restart-checkout',
        'git_gc_temporary_pack_bound':root/'data','new_update_capture_report_bound':Path(os.environ['TMPDIR']),
        'candidate_source_copy_and_git_import':root,'three_pages_roots':root.parent/'sample-pages',
        'two_uploader_tars':root.parent/'sample-artifact.tar','metadata_logs_allocation_uncertainty':root.parent}
    return admission_allocation([(k,destinations[k],v) for k,v in terms.items()],_critical_paths(code,root,result))


def launch_job(code,root,result,sample_number):
    """Private same-operation handoff; no persisted proof or caller PASS flag."""
    start=time.monotonic();stages={}
    def timed(name,action):
        tick=time.monotonic()
        try:return action()
        finally:stages[name]=_stage_clock(start,tick)
    try:
        _job_context(code,root,result,sample_number)
        capability=timed('resource_capability',lambda:_resource_preflight(code,root,result,sample_number))
        if root.parent.exists():
            if root.parent.is_symlink() or not root.parent.is_dir() or any(root.parent.iterdir()):
                raise RuntimeError('Fresh empty job workspace required')
        else:root.parent.mkdir(parents=True)
        # Retrieve only the separately approved wholly fictional Actions seed,
        # BEFORE the final online CI check and BEFORE inherited isolation.
        import operating_seed_transport as transport
        if Path(transport.__file__).resolve()!=code/'tools/operating_seed_transport.py':
            raise RuntimeError('Wrong installed fictional transport')
        approved=transport.read_approval(Path(os.environ['RUNNER_TEMP'])/'operating-artifact-approval.json',
            os.environ['OPERATING_ARTIFACT_APPROVAL_SHA256'])
        if approved['seed_manifest_sha256']!=os.environ['SEED_MANIFEST_SHA256']:
            raise RuntimeError('Approved seed and invocation differ')
        timed('transport_allocation_admission',lambda:_transport_allocation(code,root,result,approved))
        retrieved=timed('seed_retrieval',lambda:transport.retrieve(code,root.parent/'retrieved-seed',approved,deadline=start+1200))
        timed('restoration_allocation_admission',lambda:_restoration_allocation(code,root,result,retrieved))
        # This trusted coordinator retains the read-only GitHub token for the
        # three actual hourly source-CI boundaries. App/test children never do.
        verification=timed('source_ci_online',lambda:_source_ci_cli(code,'verify'))
        fingerprint=timed('source_ci_private_binding',lambda:_source_ci_cli(code,'fingerprint'))
        _matched_source_ci(verification,fingerprint)
        _runtime_identity(fingerprint['environment'])
        operation=(copy.deepcopy(verification),copy.deepcopy(fingerprint),start,stages,capability)
        timed('network_isolation',lambda:_guarded_stage(code,[sys.executable,'-c',
            "import os;assert not os.environ.get('GH_TOKEN');assert not os.environ.get('GITHUB_TOKEN')"],
            result.parent/'network-controls.log',max(.01,1200-(time.monotonic()-start))))
        return job(code,root,result,sample_number,_operation=operation)
    except BaseException as error:
        for name in ('GH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY','OPENAI_API_KEY'):os.environ.pop(name,None)
        if not result.exists():put(result,dict(status='SOURCE_CI_OR_ISOLATION_SETUP_FAILED',sample=sample_number,
            source=os.environ.get('GITHUB_SHA'),failure_class=type(error).__name__,stages=stages,
            harness_wall_seconds=time.monotonic()-start,operating='NOT_QUALIFIED'))
        raise

    finally:
        for name in ('GH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY','OPENAI_API_KEY'):os.environ.pop(name,None)


def _execution_files(fingerprint):
    return {f['path']:f for f in fingerprint['files']
        if f['path'].startswith(('pull/','tools/')) or f['path'].startswith('output/') and not f['path'].startswith('output/data/')}


def _weekly_execution_additions(fingerprint):
    additions={f['path']:f for f in fingerprint['files'] if f['path'] in WEEKLY_EXECUTION_ADDITIONS}
    if additions and set(additions)!=set(WEEKLY_EXECUTION_ADDITIONS):
        raise RuntimeError('Incomplete registered weekly execution additions')
    if any(f.get('mode')!='100644' or f.get('sha256')!=WEEKLY_EXECUTION_ADDITIONS[name]
            or type(f.get('bytes')) is not int or not 0<f['bytes']<=1<<20 for name,f in additions.items()):
        raise RuntimeError('Unsupported registered weekly execution addition')
    return additions


def _walk(root,lanes,*,source=False):
    """Bound directories and files while enumerating; prune data before walking."""
    pending=[root/name for name in lanes];files=[];directories=0;entries=0
    while pending:
        directory=pending.pop();directories+=1
        if directories>(ENTRY_LIMIT if source else 50000):raise RuntimeError('Directory inventory exceeds bound')
        if directory.is_symlink() or not directory.is_dir():raise RuntimeError('Nonregular dependency directory')
        with os.scandir(directory) as items:
            for entry in items:
                entries+=1
                if entries>(ENTRY_LIMIT if source else EVIDENCE_ENTRIES):raise RuntimeError('Dependency inventory exceeds bound')
                p=Path(entry.path)
                if source and p==root/'output/data':continue
                if entry.is_symlink():raise RuntimeError('Symlink dependency')
                if entry.is_dir(follow_symlinks=False):
                    if source and entry.name=='__pycache__':
                        if not sys.dont_write_bytecode or not sys.pycache_prefix:raise RuntimeError('Inactive bytecode contract unavailable')
                        continue
                    pending.append(p)
                elif entry.is_file(follow_symlinks=False):files.append(p)
                else:raise RuntimeError('Nonregular derived source dependency')
    return sorted(files)


def _installed_names(root,lanes):
    # Flat .pyc and native extensions remain in this set and must be declared;
    # an untracked active import asset cannot disappear as "generated".
    return {p.relative_to(root).as_posix() for p in _walk(root,lanes,source=True)}


def _evidence_inventory(root):
    paths=_walk(root,('data','output/data'));total=0;result={}
    for p in paths:
        total+=p.stat().st_size
        if total>SEED_BYTES_LIMIT:raise RuntimeError('Evidence inventory exceeds retained seed bound')
        result[p.relative_to(root).as_posix()]=_hash_file(p,SEED_BYTES_LIMIT)
    return result


def _hex(value,pattern):return type(value) is str and pattern.fullmatch(value) is not None


def _frozen_seed_manifest(root):
    path=root.parent/'retrieved-seed/SEED_MANIFEST.json'
    raw=_bounded_file(path,JSON_LIMIT)
    if sha(raw)!=os.environ['SEED_MANIFEST_SHA256']:raise RuntimeError('Frozen seed manifest changed')
    value=_decoded(raw)
    if (type(value) is not dict or value.get('schema_version')!='fictional-operating-seed-v1'
            or value.get('full_admitted') is not True or value.get('application_source')!=BASE
            or value.get('harness_sha256')!=SEED_HARNESS_SHA256 or type(value.get('files')) is not dict):
        raise RuntimeError('Wrong original seed association')
    config=value['files'].get('config/phase2.json')
    if (type(config) is not dict or set(config)!={'sha256','bytes','mode'}
            or not _hex(config['sha256'],HEX64) or type(config['bytes']) is not int
            or not 0<=config['bytes']<=SOURCE_FILE_LIMIT or type(config['mode']) is not int
            or config['mode'] not in (0o644,0o755)):
        raise RuntimeError('Missing closed fictional configuration descriptor')
    return value,config


def _source_marker(root):
    marker=_load(root/'DIAGNOSTIC_EXECUTION_SOURCE.json')
    keys={'schema_version','fixture_construction_source','prior_fixture_commit','candidate_commit','candidate_tree',
        'files','config_files','fictional_phase2_sha256','candidate_phase2_sha256','retained_evidence_inventory_sha256','saved_seed_manifest_sha256','packaging_pending'}
    version=marker.get('schema_version')
    if version=='diagnostic-execution-source-v3':keys=keys|{'phase2_transition'}
    if (set(marker)!=keys or version not in ('diagnostic-execution-source-v2','diagnostic-execution-source-v3')
            or marker['fixture_construction_source']!=BASE or marker['packaging_pending'] is not True
            or any(not _hex(marker[k],HEX40) for k in ('prior_fixture_commit','candidate_commit','candidate_tree'))
            or any(not _hex(marker[k],HEX64) for k in ('fictional_phase2_sha256','candidate_phase2_sha256','retained_evidence_inventory_sha256','saved_seed_manifest_sha256'))
            or type(marker['files']) is not dict or not 0<len(marker['files'])<=ENTRY_LIMIT
            or type(marker['config_files']) is not dict or len(marker['config_files'])>ENTRY_LIMIT):
        raise RuntimeError('Invalid versioned execution marker')
    for name,d in marker['files'].items():
        if (type(name) is not str or name.startswith('/') or '..' in Path(name).parts
                or type(d) is not dict or set(d)!={'path','mode','blob','bytes','sha256'} or d['path']!=name
                or d['mode'] not in ('100644','100755') or type(d['bytes']) is not int or not 0<=d['bytes']<=SOURCE_FILE_LIMIT
                or not _hex(d['blob'],HEX40) or not _hex(d['sha256'],HEX64)):
            raise RuntimeError('Invalid execution file descriptor')
    for name,digest in marker['config_files'].items():
        if type(name) is not str or not name.startswith('config/') or '..' in Path(name).parts or not _hex(digest,HEX64):raise RuntimeError('Invalid configuration descriptor')
    if version=='diagnostic-execution-source-v3' and marker['phase2_transition'] is not None:
        descriptor=marker['phase2_transition']
        if (type(descriptor) is not dict or set(descriptor)!={'path','sha256','bytes'}
                or descriptor['path']!=TRANSITION_PATH or not _hex(descriptor['sha256'],HEX64)
                or type(descriptor['bytes']) is not int or not 0<descriptor['bytes']<=JSON_LIMIT):
            raise RuntimeError('Unsupported fictional transition descriptor')
    return marker


def _execution_base_identity(code,root,*,packaged=True):
    """Final candidate bytes and separately preserved fictional inputs."""
    marker=_source_marker(root)
    _,seed_config=_frozen_seed_manifest(root)
    if (marker['saved_seed_manifest_sha256']!=os.environ['SEED_MANIFEST_SHA256']
            or marker['fictional_phase2_sha256']!=seed_config['sha256']):
        raise RuntimeError('Execution configuration is not the exact frozen seed configuration')
    current=_source_ci_cli(code,'fingerprint')
    if (marker['candidate_commit']!=current['commit'] or marker['candidate_tree']!=current['tree']
            or marker['files']!=_execution_files(current)):
        raise RuntimeError('Wrong final candidate/fixture execution association')
    candidate_config=next((f['sha256'] for f in current['files'] if f['path']=='config/phase2.json'),None)
    if candidate_config!=marker['candidate_phase2_sha256']:raise RuntimeError('Actual source-CI configuration changed')
    if _installed_names(root,('pull','tools','output'))!=set(marker['files']):raise RuntimeError('Derived executable inventory changed')
    configs={f['path']:f['sha256'] for f in current['files'] if f['path'].startswith('config/') and f['path']!='config/phase2.json'}
    if marker['config_files']!=configs or _installed_names(root,('config',))!=set(configs)|{'config/phase2.json'}:
        raise RuntimeError('Derived configuration inventory changed')
    if any(_hash_file(root/name)!=digest for name,digest in configs.items()):raise RuntimeError('Derived configuration bytes changed')
    for name,d in marker['files'].items():
        if not packaged and name in ('output/app.js','output/index.html'):continue
        p=root/name
        if (p.is_symlink() or not p.is_file() or p.stat().st_size!=d['bytes'] or _hash_file(p)!=d['sha256']
                or ('100755' if p.stat().st_mode&0o100 else '100644')!=d['mode']):
            raise RuntimeError('Derived execution source bytes differ from candidate: '+name)
    return marker


def execution_identity(code,root,*,packaged=True):
    marker=_execution_base_identity(code,root,packaged=packaged)
    descriptor=marker.get('phase2_transition')
    if descriptor is None:
        if _hash_file(root/'config/phase2.json')!=marker['fictional_phase2_sha256']:
            raise RuntimeError('Fictional activation configuration changed')
    else:
        raw=_bounded_file(root/TRANSITION_PATH,JSON_LIMIT)
        if len(raw)!=descriptor['bytes'] or sha(raw)!=descriptor['sha256']:
            raise RuntimeError('Fictional transition bytes changed')
        target,_,_=_transition_binding(root,marker)
        if _bounded_file(root/'config/phase2.json')!=encoded(target):
            raise RuntimeError('Derived fictional activation configuration changed')
    return marker


TRANSITION_SECONDS=130
TRANSITION_PATH='DIAGNOSTIC_PLAN_TRANSITION.json'


def _transition_clock():
    if (SEED_HOUR!=77 or seed_v1.FULL.get('generations')!=24
            or seed_v1.SAMPLE_SECONDS!=135 or not 5*24<TRANSITION_SECONDS<seed_v1.SAMPLE_SECONDS):
        raise RuntimeError('Changed fixed fictional transition/sample clock')
    return START+timedelta(hours=SEED_HOUR,seconds=TRANSITION_SECONDS)


def _atomic_private_bytes(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as handle:
        handle.write(raw);handle.flush();os.fsync(handle.fileno());temporary=Path(handle.name)
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def _seed_json(root,marker,name):
    """Read an approved original role through freshly hashed Git objects."""
    import source_ci
    if name not in ('config/phase2.json','output/data/week.json'):
        raise RuntimeError('Unsupported original seed role')
    manifest,_=_frozen_seed_manifest(root)
    prior=marker['prior_fixture_commit']
    if manifest.get('roots',{}).get('fictional_head')!=prior:
        raise RuntimeError('Original fixture commit differs from approved seed')
    expected=manifest['files'].get(name)
    if (type(expected) is not dict or set(expected)!={'sha256','bytes','mode'}
            or not _hex(expected['sha256'],HEX64) or type(expected['bytes']) is not int
            or not 0<expected['bytes']<=SOURCE_FILE_LIMIT or expected['mode'] not in (0o644,0o755)):
        raise RuntimeError('Missing bounded original seed role')
    def obj(kind,oid):
        if not _hex(oid,HEX40):raise RuntimeError('Invalid original Git object identity')
        raw,_=source_ci.command(['git','--no-replace-objects','-c','core.hooksPath=/dev/null','-C',str(root),
            'cat-file',kind,oid],limit=SOURCE_FILE_LIMIT,env=source_ci._git_environment())
        if hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=oid:
            raise RuntimeError('Corrupt original Git object')
        return raw
    commit=obj('commit',prior);first=commit.splitlines()[0]
    if not re.fullmatch(b'tree [0-9a-f]{40}',first):raise RuntimeError('Invalid original commit tree')
    oid=first[5:].decode();parts=name.split('/')
    for number,part in enumerate(parts):
        raw=obj('tree',oid);offset=0;entries={}
        while offset<len(raw):
            end=raw.find(b'\0',offset)
            if end<0 or end+21>len(raw):raise RuntimeError('Malformed original tree')
            header=raw[offset:end].split(b' ',1)
            if len(header)!=2:raise RuntimeError('Malformed original tree entry')
            mode,entry=header;entry=entry.decode();child=raw[end+1:end+21].hex();offset=end+21
            if entry in entries or not entry or entry in ('.','..') or '/' in entry or '\\' in entry:
                raise RuntimeError('Unsupported original tree entry')
            entries[entry]=(mode,child)
        if part not in entries:raise RuntimeError('Original seed role is absent from Git')
        mode,oid=entries[part]
        if number<len(parts)-1:
            if mode!=b'40000':raise RuntimeError('Non-directory original seed path')
        elif mode not in (b'100644',b'100755') or (0o755 if mode==b'100755' else 0o644)!=expected['mode']:
            raise RuntimeError('Unsupported original seed mode')
    raw=obj('blob',oid)
    if len(raw)!=expected['bytes'] or sha(raw)!=expected['sha256']:
        raise RuntimeError('Original seed bytes differ from approved manifest')
    return _decoded(raw),raw


def _transition_spec(original,board,status,source_sha):
    """Closed fictional transformation; this pure value builder grants no trust."""
    import data_integrity_v2 as api
    import partial_week
    import reliability
    from source_evidence import verified_status
    at=_transition_clock()
    if (not _hex(source_sha,HEX40) or original.get('capture_enabled') is not True
            or original.get('production_model')!=api.MODEL
            or original.get('verification_mode')!=api.VALIDATOR
            or original.get('challenger_production_enabled') is not False
            or original.get('experimental_recording_enabled') is not False):
        raise RuntimeError('Unsupported original fictional configuration')
    old=original['partial_week'];plan=old['plan']
    if (old.get('validator_sha256')!=api.RETAINED_CORRECTED_HELPERS['tools/data_integrity_v2.py']
            or reliability.digest(plan)!=old.get('plan_sha256') or plan.get('engine_files')!=api.V2_SOURCE_SHA256
            or (plan.get('season'),plan.get('week'))!=(2026,6)
            or (board.get('season'),board.get('week'))!=(2026,6)
            or len(board.get('games',[]))!=14
            or not reliability.utc(plan['effective_not_before'])<at<reliability.utc(plan['expires_at'])
            or reliability.utc(board['generated_at'])>=at
            or not at<START+timedelta(hours=SEED_HOUR,seconds=seed_v1.SAMPLE_SECONDS)<reliability.utc(plan['expires_at'])):
        raise RuntimeError('Unsupported fixed fictional predecessor or clock')
    games={g['id']:g for g in board['games']}
    old_games={g['id']:g for g in plan['games']}
    exemptions=plan['legacy_exemptions'];legacy={g['game_id']:g for g in exemptions}
    if (len(games)!=14 or len(old_games)!=14 or len(exemptions)!=9 or len(legacy)!=9
            or set(games)!=set(old_games) or not set(legacy)<=set(games)):
        raise RuntimeError('Changed fixed fictional game/exemption population')
    for gid,game in games.items():
        if any((reliability.utc(game[k])!=reliability.utc(old_games[gid][k]) if k=='kickoff'
                else game[k]!=old_games[gid][k]) for k in ('home','away','kickoff')):
            raise RuntimeError('Changed fictional schedule')
        if gid in legacy:
            if (reliability.utc(game['kickoff'])>=at or not legacy[gid].get('reason')
                    or reliability.digest(partial_week.game_contract(board,gid))!=legacy[gid]['forecast_contract_sha256']):
                raise RuntimeError('Changed original fictional legacy contract')
        elif reliability.utc(game['kickoff'])<=at:
            raise RuntimeError('Additional started fictional game needs a separate decision')
    observed=verified_status(status,2026,6,'live',at)
    if (status.get('collected_at')!=reliability.stamp(at) or set(observed)!=set(games)
            or {state:sum(g['state']==state for g in observed.values()) for state in ('post','in','pre')}
                !={'post':2,'in':7,'pre':5}):
        raise RuntimeError('Changed fixed fictional status population/clock')
    for gid,value in observed.items():
        kickoff=reliability.utc(games[gid]['kickoff'])
        expected='post' if at>=kickoff+timedelta(hours=4) else 'in' if at>=kickoff else 'pre'
        if (reliability.utc(value['kickoff'])!=kickoff or value['state']!=expected
                or value['completed']!=(expected=='post')):
            raise RuntimeError('Changed fictional status schedule/finality')
    updated=copy.deepcopy(plan)
    updated.update(plan_id='FICTIONAL_DERIVED_EXECUTION_'+source_sha+'_'+old['plan_sha256'],
        plan_prepared_at=reliability.stamp(at),effective_not_before=reliability.stamp(at),
        initial_complete_board_sha256=reliability.digest(board),source_start=source_sha,
        previous_plan_sha256=old['plan_sha256'],
        fixture_transition='DERIVED_FICTIONAL_ONLY_ORIGINAL_B3_EVIDENCE_RETAINED',
        schedule_status_payload_sha256=reliability.digest(status),schedule_status_observed_at=status['collected_at'])
    board_payload=dict(schema_version='partial-plan-board-v1',season=2026,week=6,board=board)
    board_name='data/verification/partial-plan-boards/2026/w06/'+reliability.digest(board_payload)+'.json.gz'
    spec=dict(plan=updated,plan_sha256=reliability.digest(updated),validator_sha256=api.code_sha256(),
        owner_authorization='FICTIONAL_ONLY_DERIVED_SOURCE_TRANSITION_NOT_REAL_ACTIVATION',initial_board_receipt=board_name)
    result=copy.deepcopy(original);result['partial_week']=spec
    api.validate_plan(spec,board,at)
    return result,board_payload


def _transition_material(root,marker):
    """Actual copied helper/source and original seed, never production config."""
    m=bind(root)
    import data_integrity_v2 as api
    if (Path(api.__file__).resolve()!=root/'tools/data_integrity_v2.py'
            or Path(m['rel'].__file__).resolve()!=root/'tools/reliability.py'
            or Path(m['source'].__file__).resolve()!=root/'tools/source_evidence.py'):
        raise RuntimeError('Derived transition must execute actual copied helpers')
    helper=_hash_file(root/'tools/data_integrity_v2.py')
    if helper!=m['rel'].V2_HELPER_SHA256 or helper!=marker['files']['tools/data_integrity_v2.py']['sha256']:
        raise RuntimeError('Derived transition helper binding changed')
    api.recording_source(marker['candidate_commit'],repository=root)
    original,original_raw=_seed_json(root,marker,'config/phase2.json')
    board,_=_seed_json(root,marker,'output/data/week.json')
    notice=_load(root/'FICTIONAL_ONLY.json')
    if (notice.get('notice')!=NOTICE or notice.get('campaign')!=CAMPAIGN
            or notice.get('reviewed_source')!=BASE or notice.get('construction_code')!=BASE
            or notice.get('dimensions') not in (seed_v1.FULL,seed_v1.SMALL)):
        raise RuntimeError('Unsupported fictional transition lineage')
    provider=Provider(m,notice['dimensions'],_transition_clock())
    status=m['source'].record_scoreboard(provider.scoreboard(2026,6),dict(dates=2026,week=6,seasontype=2),_transition_clock())
    target,board_payload=_transition_spec(original,board,status,marker['candidate_commit'])
    return m,api,original_raw,board,target,board_payload,status


def _transition_binding(root,marker,*,issue=False):
    """Recompute complete expected values and freshly validate every saved edge."""
    m,api,original_raw,board,target,board_payload,status=_transition_material(root,marker)
    spec=target['partial_week'];at=_transition_clock();ev=m['ev'];rel=m['rel'];partial=m['partial']
    if _bounded_file(root/'config/phase2.json') not in (original_raw,encoded(target)):
        raise RuntimeError('Changed fictional configuration is not a supported transition state')
    status_payload=dict(schema_version='partial-schedule-baseline-v1',season=2026,week=6,status=status)
    status_name='data/verification/partial-schedule-baselines/2026/w06/'+rel.digest(status_payload)+'.json.gz'
    if issue:
        if ev.write(root,'verification/partial-schedule-baselines',status_payload).relative_to(root).as_posix()!=status_name:
            raise RuntimeError('Derived status identity differs')
        if ev.write(root,'verification/partial-plan-boards',board_payload).relative_to(root).as_posix()!=spec['initial_board_receipt']:
            raise RuntimeError('Derived initial board identity differs')
        reg_path,_=api.register_plan(root,spec,at,source_sha=marker['candidate_commit'],initial_board=board)
        reg_name=reg_path.relative_to(root).as_posix()
    else:
        stored=_load(root/TRANSITION_PATH)
        reg_name=stored.get('registration_receipt')
    if (partial._saved(root,status_name,'verification/partial-schedule-baselines')!=status_payload
            or partial._saved(root,spec['initial_board_receipt'],'verification/partial-plan-boards')!=board_payload):
        raise RuntimeError('Derived plan original dependencies changed')
    saved=api.registration(root,reg_name,spec,at)
    if (saved['source_sha']!=marker['candidate_commit'] or saved['registered_at']!=at.isoformat()
            or saved['schedule_status_receipt']!=status_name or saved['initial_board']!=board):
        raise RuntimeError('Derived registration source/clock/dependencies changed')
    binding=dict(schema_version='diagnostic-fictional-plan-transition-v1',fixture_construction_source=BASE,
        saved_seed_manifest_sha256=marker['saved_seed_manifest_sha256'],prior_fixture_commit=marker['prior_fixture_commit'],
        candidate_commit=marker['candidate_commit'],candidate_tree=marker['candidate_tree'],
        original_phase2_sha256=sha(original_raw),candidate_phase2_sha256=marker['candidate_phase2_sha256'],
        derived_phase2_sha256=sha(encoded(target)),helper_sha256=api.code_sha256(),
        original_plan_sha256=_decoded(original_raw)['partial_week']['plan_sha256'],plan_sha256=spec['plan_sha256'],
        transition_at=at.isoformat(),sample_at=(START+timedelta(hours=SEED_HOUR,seconds=seed_v1.SAMPLE_SECONDS)).isoformat(),
        initial_board_receipt=spec['initial_board_receipt'],schedule_status_receipt=status_name,
        registration_receipt=reg_name,registration_payload_sha256=rel.digest(saved))
    if not issue and stored!=binding:raise RuntimeError('Derived transition record differs from actual dependencies')
    return target,original_raw,binding


def _saved_packaging_identity(root,m,packaging):
    """Fresh old-generation validation, including interrupted-transition retries.

    Only the saved snapshot's own registration qualifies that old observation.
    This does not qualify it as a new current-plan capture.
    """
    capture=m['capture'];base=root/'output/data/selection-grading'
    working=_decoded(_bounded_file(base/'hosting.json',MIB),MIB);checked={}
    capture._registry(base,working,_checked=checked)
    manifest,snapshots=capture._manifest(base,working['latest'],root=root,_checked=checked)
    if manifest['generation_sha256']!=packaging['generation']:
        raise RuntimeError('Changed saved packaging before fictional transition')
    if any(not capture._same_generation_snapshot(name,_bounded_file(root/'output'/name),snapshots[name])
            for name in capture.HOST_SNAPSHOTS):
        raise RuntimeError('Saved packaging aliases changed before fictional transition')


def transition_execution_plan(code,root):
    """Idempotent diagnostic-only plan migration after saved packaging."""
    require_offline();marker=_execution_base_identity(code,root)
    if marker['schema_version']!='diagnostic-execution-source-v3':
        raise RuntimeError('Legacy execution marker cannot acquire a new plan')
    packaging=_load(root/'DIAGNOSTIC_EXECUTION_PACKAGING.json')
    if (set(packaging)!={'schema_version','fixture_construction_source','candidate_commit','generation','original_capture_preserved'}
            or packaging['schema_version']!='diagnostic-execution-packaging-v2'
            or packaging['fixture_construction_source']!=BASE or packaging['candidate_commit']!=marker['candidate_commit']
            or packaging['original_capture_preserved'] is not True or not _hex(packaging['generation'],HEX64)):
        raise RuntimeError('Saved packaging must precede the fictional plan transition')
    before=_evidence_inventory(root);old_marker=_bounded_file(root/'DIAGNOSTIC_EXECUTION_SOURCE.json')
    config_path=root/'config/phase2.json';old_config=_bounded_file(config_path)
    if git(root,'diff','--cached','--name-only'):
        raise RuntimeError('Unrelated staged work before fictional transition')
    try:
        m=bind(root);notice=_load(root/'FICTIONAL_ONLY.json')
        provider=Provider(m,notice['dimensions'],_transition_clock())
        with operation_lifetime(seed_v1, modules=(m,)),external(m,provider,root),patch.object(m['capture'],'_public_archive_commit',side_effect=lambda ref,tree:assert_local_tree(root,ref,tree)):
            _saved_packaging_identity(root,m,packaging)
        # Failed/interrupted invocations retain deterministic new receipts. A retry
        # recomputes them, never inherits a PASS record or changes their identity.
        target,original_raw,binding=_transition_binding(root,marker,issue=not (root/TRANSITION_PATH).exists())
        if old_config not in (original_raw,encoded(target)):
            raise RuntimeError('Changed fictional configuration is not a supported transition state')
        if (root/TRANSITION_PATH).exists() and _load(root/TRANSITION_PATH)!=binding:
            raise RuntimeError('Existing transition is not this exact source/plan')
        _atomic_private_bytes(root/TRANSITION_PATH,encoded(binding))
        raw=_bounded_file(root/TRANSITION_PATH)
        descriptor=dict(path=TRANSITION_PATH,sha256=sha(raw),bytes=len(raw))
        if marker['phase2_transition'] not in (None,descriptor):raise RuntimeError('Conflicting fictional transition marker')
        after=_evidence_inventory(root)
        if any(after.get(name)!=digest for name,digest in before.items()):
            raise RuntimeError('Transition changed retained data/report/evidence')
        _atomic_private_bytes(config_path,encoded(target))
        updated=copy.deepcopy(marker);updated['phase2_transition']=descriptor
        _atomic_private_bytes(root/'DIAGNOSTIC_EXECUTION_SOURCE.json',encoded(updated))
        execution_identity(code,root)
        git(root,'add','--','config/phase2.json',TRANSITION_PATH,'DIAGNOSTIC_EXECUTION_SOURCE.json')
        changed=subprocess.run(['git','-C',str(root),'diff','--cached','--quiet']).returncode
        if changed not in (0,1):raise RuntimeError('Cannot inspect fictional transition commit')
        if changed:
            git(root,'commit','-qm','Fictional derived source/plan; B3 originals retained')
        return binding
    except BaseException as original_error:
        # Mutable diagnostic state rolls back; all create-only receipts/failure
        # evidence remain. Original seed bytes live in their independent root.
        cleanup_error=None
        try:
            staged=git(root,'diff','--cached','--name-only').splitlines()
            owned={'config/phase2.json',TRANSITION_PATH,'DIAGNOSTIC_EXECUTION_SOURCE.json'}
            if not set(staged)<=owned:raise RuntimeError('Unrelated staged work during transition failure')
            if staged:git(root,'restore','--staged','--',*staged)
        except BaseException as error:cleanup_error=error
        _atomic_private_bytes(config_path,old_config)
        _atomic_private_bytes(root/'DIAGNOSTIC_EXECUTION_SOURCE.json',old_marker)
        if cleanup_error is not None:
            raise RuntimeError('Fictional transition failed; owned index cleanup also failed: '+type(cleanup_error).__name__) from original_error
        raise


def install_execution_source(code,root):
    """Source-only derived copy; immutable B3 seed and all evidence stay intact."""
    require_offline()
    if (root/'DIAGNOSTIC_EXECUTION_SOURCE.json').exists():raise RuntimeError('New derived execution copy required')
    notice=_load(root/'FICTIONAL_ONLY.json')
    if (set(notice)!={'campaign','construction_code','dimensions','notice','reviewed_source'}
            or notice['reviewed_source']!=BASE or notice['construction_code']!=BASE or notice['notice']!=NOTICE
            or notice['campaign']!=CAMPAIGN or type(notice['dimensions']) is not dict
            or notice['dimensions'] not in (seed_v1.FULL,seed_v1.SMALL,seed_v1.VALID_FROZEN_SMALL)
            or any(type(value) is not int for value in notice['dimensions'].values())):
        raise RuntimeError('Not the preserved B3 fictional lineage')
    _,seed_config=_frozen_seed_manifest(root)
    if (_hash_file(root/'config/phase2.json')!=seed_config['sha256']
            or (root/'config/phase2.json').stat().st_size!=seed_config['bytes']):
        raise RuntimeError('Fictional configuration differs from the approved frozen seed')
    current=_source_ci_cli(code,'fingerprint');files=_execution_files(current)
    additions=_weekly_execution_additions(current)
    if additions:_install_weekly_registrations(code,root,current)
    before=_evidence_inventory(root)
    actual=_installed_names(root,('pull','tools','output'))
    if not actual<=set(files):raise RuntimeError('Unsupported extra executable/static source in fixture')
    for f in current['files']:
        name=f['path']
        if name.startswith('config/') and name!='config/phase2.json' and (not (root/name).is_file() or _hash_file(root/name)!=_hash_file(code/name)):
            if name not in additions or (root/name).exists() or (root/name).is_symlink():
                raise RuntimeError('Undeclared fictional/candidate configuration difference: '+name)
            raw=_bounded_file(code/name,1<<20)
            if len(raw)!=f['bytes'] or sha(raw)!=f['sha256']:
                raise RuntimeError('Registered weekly configuration changed before copying')
            (root/name).parent.mkdir(parents=True,exist_ok=True)
            (root/name).write_bytes(raw);(root/name).chmod(0o644)
    for name,d in files.items():
        p=code/name
        if p.is_symlink() or _hash_file(p)!=d['sha256']:raise RuntimeError('Candidate changed before copying')
        if name.startswith('pull/') or name.startswith('output/'):
            if not (root/name).is_file() or _hash_file(root/name)!=_hash_file(p):
                if name not in ('output/app.js','output/index.html') and not (
                        name in additions and not (root/name).exists() and not (root/name).is_symlink()):
                    raise RuntimeError('Unsupported model/static transition: '+name)
        if name in ('output/app.js','output/index.html'):continue  # Existing saved-packaging route owns this transition.
        (root/name).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,root/name)
        (root/name).chmod(0o755 if d['mode']=='100755' else 0o644)
    if before!=_evidence_inventory(root):raise RuntimeError('Source installation changed retained evidence')
    git(root,'fetch','--quiet',str(code),current['commit']);git(root,'update-ref','refs/diagnostic/execution-source',current['commit'])
    put(root/'DIAGNOSTIC_EXECUTION_SOURCE.json',dict(schema_version='diagnostic-execution-source-v3',phase2_transition=None,
        fixture_construction_source=BASE,prior_fixture_commit=git(root,'rev-parse','HEAD'),
        candidate_commit=current['commit'],candidate_tree=current['tree'],files=files,
        config_files={f['path']:f['sha256'] for f in current['files'] if f['path'].startswith('config/') and f['path']!='config/phase2.json'},
        fictional_phase2_sha256=_hash_file(root/'config/phase2.json'),
        candidate_phase2_sha256=next(f['sha256'] for f in current['files'] if f['path']=='config/phase2.json'),
        retained_evidence_inventory_sha256=sha(encoded(before)),saved_seed_manifest_sha256=os.environ['SEED_MANIFEST_SHA256'],packaging_pending=True))
    names=[name for name in files if name not in ('output/app.js','output/index.html')]+[
        name for name in additions if name.startswith('config/')]
    git(root,'add','--',*names,'DIAGNOSTIC_EXECUTION_SOURCE.json')
    git(root,'commit','-qm','Wholly fictional derived execution source; B3 origins retained')
    execution_identity(code,root,packaged=False)


def _packaging_clock():
    # The full seed ends at +120s; packaging is a new operation, before the
    # separately registered +130s transition and unchanged +135s sample.
    return _transition_clock()-timedelta(seconds=5)


def package_execution_source(code,root):
    require_offline();execution_identity(code,root,packaged=False)
    m=bind(root);marker=_load(root/'FICTIONAL_ONLY.json')
    at=_packaging_clock()
    pointer=_load(root/'output/data/selection-grading/latest.json')
    if m['rel'].utc(pointer['generated_at'])>=at:
        raise RuntimeError('Saved publication does not precede the fixed packaging clock')
    provider=Provider(m,marker['dimensions'],at)
    with operation_lifetime(seed_v1, modules=(m,)),external(m,provider,root),patch.object(m['capture'],'_public_archive_commit',side_effect=lambda ref,tree:assert_local_tree(root,ref,tree)):
        generation=m['capture'].repackage_generation(root,source_root=code)
    execution_identity(code,root)
    put(root/'DIAGNOSTIC_EXECUTION_PACKAGING.json',dict(schema_version='diagnostic-execution-packaging-v2',
        fixture_construction_source=BASE,candidate_commit=git(code,'rev-parse','HEAD'),
        generation=generation['generation_sha256'],original_capture_preserved=True))
    git(root,'add','--','output/app.js','output/index.html','DIAGNOSTIC_EXECUTION_PACKAGING.json')
    commit(root)


def job(code,root,result,sample_number,*,_operation=None):
    """Future hosted-only job entry; not invoked during local preparation."""
    _job_context(code,root,result,sample_number)
    if _operation is None:raise RuntimeError('Direct trusted source-CI launcher required')
    verification,identity,start,stages,capability=_operation
    if os.environ.get('DIAGNOSTIC_RESOURCE_BACKEND')!='root-supervised-cgroup-v1':raise RuntimeError('Hosted resource preflight required')
    if Path(__file__).resolve()!=code/'tools/operating_campaign.py':raise RuntimeError('Job must use actual installed harness')
    for name in ('GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY','OPENAI_API_KEY'):
        if os.environ.get(name):raise RuntimeError('Forbidden injected credential name')
    expected=Path(os.environ['RUNNER_TEMP']).resolve()/('nfl-operating-'+str(sample_number))
    if root!=expected/'fixture' or result!=expected/'RESULT.json' or root.exists():
        raise RuntimeError('Only a new exact runner-local fixture destination is allowed')
    if os.environ.get('CAMPAIGN_ID')!=CAMPAIGN or os.environ.get('GITHUB_ACTOR_ID')!='208912933':
        raise RuntimeError('Wrong authenticated campaign actor/identity')
    result.parent.mkdir(parents=True,exist_ok=True)
    root.parent.mkdir(parents=True,exist_ok=True)
    result.parent.mkdir(parents=True,exist_ok=True)
    runtime=_runtime_identity(identity['environment'])
    wrapper=next((f for f in identity['files'] if f['path']=='tools/operating_campaign.py'),None)
    if wrapper is None:raise RuntimeError('Actual wrapper is missing from authenticated source')
    dependencies={name:_hash_file(code/name) for name in DEPENDENCIES}
    run_id=int(os.environ['GITHUB_RUN_ID']);run_attempt=int(os.environ['GITHUB_RUN_ATTEMPT'])
    monitor=Resources(root.parent,critical_paths=_critical_paths(code,root,result));monitor.start()
    status='FAIL';failure=None;failure_error=None;failure_trace=None;finalization_errors=[]
    online_boundaries={'initial':verification}
    def stage(name,command):
        tick=time.monotonic()
        try:_guarded_stage(code,command,result.parent/(name+'.log'),max(.01,1200-(time.monotonic()-start)))
        finally:stages[name]=_stage_clock(start,tick)
    try:
        tick=time.monotonic()
        try:
            if _source_ci_cli(code,'fingerprint')!=identity:raise RuntimeError('Source/runtime changed at fresh entry')
            _matched_source_ci(verification,identity)
        finally:stages['source_ci_isolated_entry']=_stage_clock(start,tick)
        stage('seed_restoration',[sys.executable,__file__,'restore','--code',str(code),'--root',str(root)])
        stage('workload_admission',[sys.executable,__file__,'admit','--code',str(code),'--root',str(root),'--result',str(result.parent/'admission.json')])
        if _load(result.parent/'admission.json')['status']!='ADMITTED':
            raise RuntimeError('Fixture not admitted; no timed sample substitution')
        stage('execution_source_install',[sys.executable,__file__,'install-source','--code',str(code),'--root',str(root)])
        stage('execution_saved_packaging',[sys.executable,__file__,'package-source','--code',str(code),'--root',str(root)])
        stage('execution_fictional_plan_transition',[sys.executable,__file__,'transition-plan','--code',str(code),'--root',str(root)])
        stage('retained_cheap_checks',[sys.executable,__file__,'checks','--code',str(code),'--root',str(root)])
        stage('capture_and_advisories',[sys.executable,__file__,'capture-stage','--code',str(code),'--root',str(root),'--result',str(result.parent/'dataflow.json')])
        for boundary,action,stage_name in (('before_data_commit','commit-stage','local_commit_and_pages_stage'),('after_pages_stage','tar-stage','uploader_tar')):
            tick=time.monotonic()
            try:
                checked=_source_ci_cli(code,'verify',run_id=verification['run_id'])
                if checked!=verification:raise RuntimeError('Source-CI boundary differs from initial fixed run')
                online_boundaries[boundary]=checked
            finally:stages['source_ci_'+boundary]=_stage_clock(start,tick)
            stage(stage_name,[sys.executable,__file__,action,'--code',str(code),'--root',str(root),'--result',str(result.parent/'dataflow.json')])
        tick=time.monotonic()
        try:
            if _source_ci_cli(code,'fingerprint')!=identity:raise RuntimeError('Source/runtime changed at final boundary')
        finally:stages['source_ci_isolated_final']=_stage_clock(start,tick)
        status='LOCAL_BOUNDARY_COMPLETE_EXTERNAL_JOB_TIMESTAMPS_PENDING'
    except BaseException as error:
        failure=type(error).__name__;failure_error=error;failure_trace=error.__traceback__
    finally:
        tick=time.monotonic()
        retention={'status':'FAILED_WORKSPACE_RETAINED_NO_EXPORT','root':str(root),'automatic_resume':False}
        if failure_error is None:
            try:
                # Success-only disposal; failed work remains until an approved
                # bounded checkpoint/retention action is performed.
                if root.exists():shutil.rmtree(root)
                for name in ('retrieved-seed','admission-pages','sample-pages','restart-checkout','restart-pages'):
                    q=root.parent/name
                    if q.exists():shutil.rmtree(q)
                for name in ('admission-artifact.tar','sample-artifact.tar'):(root.parent/name).unlink(missing_ok=True)
                retention={'status':'SUCCESS_JOB_COPY_CLEANED_ORIGINAL_SEED_UNCHANGED'}
            except BaseException as error:finalization_errors.append('cleanup:'+type(error).__name__)
        try:resources=monitor.finish()
        except BaseException as error:
            resources={'resource_verdict':'UNKNOWN','reason':'monitor finalization unavailable'}
            finalization_errors.append('monitor:'+type(error).__name__)
        stages['cleanup']=_stage_clock(start,tick)
        if finalization_errors:status='FINALIZATION_FAILED'
        payload=dict(schema_version='operating-campaign-result-v2',status=status,failure_class=failure,sample=sample_number,campaign=CAMPAIGN,
            run_id=run_id,run_attempt=run_attempt,
            source=identity['commit'],source_tree=identity['tree'],source_manifest_sha256=identity['source_manifest_sha256'],
            source_ci=verification,source_ci_boundaries=online_boundaries,fixture_construction_source=BASE,
            harness_sha256=wrapper['sha256'],
            fixture_harness_sha256=SEED_HARNESS_SHA256,seed_manifest_sha256=os.environ.get('SEED_MANIFEST_SHA256'),
            dependency_hashes=dependencies,runtime=runtime,environment_sha256=verification['environment_sha256'],stages=stages,
            capability_before_online=capability,worker_argv=_worker_argv(code,root,result,sample_number),
            transport_approval_sha256=os.environ['OPERATING_ARTIFACT_APPROVAL_SHA256'],retention=retention,finalization_errors=finalization_errors,
            configuration_scope='FICTIONAL_CLOSED_PHASE2_ADAPTATION_NOT_PRODUCTION_CONFIG',
            harness_wall_seconds=time.monotonic()-start,planning_seconds=960,timeout_seconds=1200,resources=resources,
            excludes=['queue','earlier_setup','later_checkout_post_actions','live_provider_network','remote_push','artifact_upload','Pages_deployment'],
            whole_job_verdict='PENDING_ACTIONS_COMPLETED_AT_AND_RESOURCE_REVIEW')
        try:put(result,payload)
        except BaseException as error:finalization_errors.append('result_write:'+type(error).__name__)
    if failure_error is not None:raise failure_error.with_traceback(failure_trace)
    if finalization_errors:raise RuntimeError('Job finalization failed: '+','.join(finalization_errors))
    return payload


def _resource_binding(measured,outer,report,run_id,sample,source):
    outer_source=outer.get('source',{});source_files=outer_source.get('files',{})
    wrapper_descriptor=source_files.get('tools/operating_campaign.py',{})
    worker=outer.get('worker_argv');supervisor=outer.get('supervisor_argv')
    cgroup=outer.get('cgroup',{});scopes=cgroup.get('scopes',[])
    before_path=report.get('capability_before_online',{}).get('current')
    resource_raw=encoded(measured)
    bound=(measured.get('run_id')==run_id and measured.get('sample')==sample
        and measured.get('source')==source and measured.get('harness_sha256')==SEED_HARNESS_SHA256
        and measured.get('seed_manifest_sha256')==report.get('seed_manifest_sha256')
        and report.get('fixture_harness_sha256')==SEED_HARNESS_SHA256
        and outer.get('schema_version')=='operating-root-execution-v1'
        and outer.get('mode')=='campaign' and outer.get('purpose')=='operating' and outer.get('root_uid')==0
        and type(outer.get('worker_uid')) is int and outer['worker_uid']>0
        and outer.get('run_id')==run_id and outer.get('sample')==sample
        and outer.get('run_attempt')==1 and outer.get('repository')=='NickNicky19/nicks-expert-nfl-picks'
        and outer.get('repository_id')==1411185749 and outer.get('actor_id')==208912933
        and outer.get('event')=='workflow_dispatch' and outer.get('branch')=='upgrade/phase2-reproducible-comparison'
        and outer.get('workflow_path')==CAMPAIGN_WORKFLOW
        and outer_source.get('commit')==source and outer_source.get('tree')==report.get('source_tree')
        and outer_source.get('source_closure_sha256')==sha(encoded(source_files))
        and wrapper_descriptor.get('sha256')==report.get('harness_sha256')
        and outer.get('resource_p5_harness_sha256')==SEED_HARNESS_SHA256
        and outer.get('resource_report')=={'sha256':sha(resource_raw),'bytes':len(resource_raw)}
        and worker==report.get('worker_argv') and outer.get('worker_argv_sha256')==sha(encoded(worker))
        and type(supervisor) is list and supervisor[-len(worker):]==worker
        and outer.get('supervisor_argv_sha256')==sha(encoded(supervisor))
        and outer.get('resource_supervisor_returncode')==0 and type(outer.get('resource_supervisor_pid')) is int
        and cgroup.get('unit')=='nfl-operating-'+str(run_id)+'-'+str(sample)+'.service'
        and type(scopes) is list and len(scopes)==3 and type(before_path) is str
        and Path(before_path).parent==Path(scopes[1]['path'])
        and Path(before_path).name=='nfl-diagnostic-'+str(run_id)+'-'+str(sample)+'-'+str(outer.get('resource_supervisor_pid'))
        and outer.get('monitored_leaf_path')==before_path and before_path in measured.get('kernel_peaks',{})
        and outer.get('complete_tree') is True and outer.get('privilege_drop_verified') is True
        and outer.get('status')=='COMPLETE_RESOURCE_REVIEW_STILL_REQUIRES_JOB_TIMESTAMPS'
        and outer.get('resource_verdict')=='PASS'
        and outer.get('transport_approval',{}).get('sha256')==report.get('transport_approval_sha256')
        and set(report.get('capability_before_online',{}).get('filesystems',{}))<=set(measured.get('filesystem_minima',{})))
    return bound


def _protected_report(path):
    parent=path.parent
    if parent.parent!=Path('/var/tmp') or parent.is_symlink():raise RuntimeError('Wrong protected report location')
    for ancestor in (Path('/'),Path('/var'),Path('/var/tmp'),parent):
        info=ancestor.lstat();mode=stat.S_IMODE(info.st_mode)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or ancestor.is_symlink()
                or (mode!=0o1777 if ancestor==Path('/var/tmp') else bool(mode&0o022))):
            raise RuntimeError('Unprotected report ancestry')
    fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>2*1024**2:
            raise RuntimeError('Unprotected or oversized resource report')
        raw=bytearray()
        while True:
            chunk=os.read(fd,min(65536,2*1024**2+1-len(raw)))
            if not chunk:break
            raw.extend(chunk)
            if len(raw)>2*1024**2:raise RuntimeError('Resource report grew beyond bound')
        value=_decoded(raw,2*1024**2)
        if type(value) is not dict:raise RuntimeError('Object resource report required')
        return value,{'sha256':sha(raw),'bytes':len(raw)}
    finally:os.close(fd)


def _measurements(measured):
    failures=measured.get('failures',[])
    if (type(failures) is not list or len(failures)>128
            or any(type(v) is not str or not re.fullmatch(r'[A-Z_0-9]{1,80}',v) for v in failures)):
        raise RuntimeError('Unsupported diagnostic failure code')
    if measured.get('status') not in ('COMPLETE','PREFLIGHT_FAILED','CAPABILITY_OR_MONITOR_FAILURE','CAPABILITY_READY'):
        raise RuntimeError('Unsupported resource measurement state')
    for values in (measured.get('kernel_peaks',{}),measured.get('event_deltas',{}),measured.get('filesystem_minima',{})):
        if type(values) is not dict or len(values)>64:raise RuntimeError('Resource dimension bound')
    for flag in ('complete_tree','peak_reset_verified','scope_closure_verified','privilege_drop_verified'):
        if measured.get(flag) is not None and type(measured[flag]) is not bool:raise RuntimeError('Invalid resource flag')
    for dimension in ('kernel_peaks','event_deltas','filesystem_minima'):
        for values in measured.get(dimension,{}).values():
            if type(values) is not dict:raise RuntimeError('Invalid numeric resource dimension')
            allowed={'kernel_peak','limit'} if dimension=='kernel_peaks' else {'low','high','max','oom','oom_kill','oom_group_kill'} if dimension=='event_deltas' else {'free','total','paths'}
            if not set(values)<=allowed:raise RuntimeError('Unsupported numeric resource field')
            if any(type(v) is not int or v<0 for k,v in values.items() if k!='paths' and not (dimension=='kernel_peaks' and k=='limit' and v is None)):
                raise RuntimeError('Invalid numeric resource fact')
    fields=('status','complete_tree','peak_reset_verified','scope_closure_verified','privilege_drop_verified',
        'failures','returncode','minimum_free_bytes','minimum_free_fraction','resource_verdict','supervisor_seconds')
    if measured.get('resource_verdict') not in ('PASS','FAIL','UNKNOWN','NOT_RUN_CAPABILITY_ONLY'):raise RuntimeError('Unsupported resource verdict')
    if measured.get('returncode') is not None and type(measured['returncode']) is not int:raise RuntimeError('Invalid return code')
    if measured.get('minimum_free_bytes')!=2*1024**3 or measured.get('minimum_free_fraction')!=.2:raise RuntimeError('Changed resource headroom rule')
    if type(measured.get('supervisor_seconds')) not in (int,float) or not 0<=measured['supervisor_seconds']<86400:raise RuntimeError('Invalid supervisor duration')
    value={k:copy.deepcopy(measured.get(k)) for k in fields}
    scopes=sorted(set(measured.get('kernel_peaks',{}))|set(measured.get('event_deltas',{})))
    tags={path:'scope-'+str(i).zfill(2) for i,path in enumerate(scopes)}
    value['kernel_peaks']={tags[p]:copy.deepcopy(v) for p,v in measured.get('kernel_peaks',{}).items()}
    value['event_deltas']={tags[p]:copy.deepcopy(v) for p,v in measured.get('event_deltas',{}).items()}
    value['filesystem_minima']={'filesystem-'+str(i).zfill(2):{'free':v.get('free'),'total':v.get('total')}
        for i,(_,v) in enumerate(sorted(measured.get('filesystem_minima',{}).items()))}
    # No raw paths, argv, environment, reasons, approval fields or fictional rows.
    if len(encoded(value))>32*1024:raise RuntimeError('Measurement projection exceeds its bound')
    return value


# The retained real release is a measured load reference, not fictional history.
FINAL_REFERENCE = {'source': '04519b54dfb76dcca7916fe6bf75d7e1711793b6', 'report_id': '46560e64a80282e7a602390b681c99e9cf60b104424b2a8a88d87097aaf49010', 'pointer_sha256': '1a311201666b258c7b0081eea485ba5660ee0e6682cebb95b5a109b19bf13083', 'summary_index_sha256': 'f0a19f5dc8c5c4265efb5caddc63feeb0dbf50f9faf6f485b0425837a5d3e6c3', 'context_descriptors_sha256': '5e3a67a867a9c2b49e6aae85f4661b06983ff4f895ebbf9f2479dfe504889449', 'required_load_floors': {'rows': 56918, 'groups': 24295, 'outcomes': 4830}, 'informational_descriptor_metrics': {'contexts': 122, 'summary_partitions': 328, 'row_chunks': 228, 'row_encoded_bytes': 22139104, 'row_decoded_bytes': 167554381, 'summary_encoded_bytes': 4685375, 'summary_decoded_bytes': 41545386, 'outcome_encoded_bytes': 450259, 'outcome_decoded_bytes': 4100696}, 'accuracy_capture_work': {'original_sleeper_matchup_baseline': {'unique_receipts': 431, 'eligible_capture_rows': {'anytime_td': 104861, 'fpts': 141796, 'pass_att': 13148, 'pass_cmp': 13148, 'pass_int': 13148, 'pass_td': 13148, 'pass_yd': 13148, 'rec': 128648, 'rec_yd': 128648, 'rush_att': 35501, 'rush_rec_yd': 92691, 'rush_yd': 48649}, 'paired_capture_rows': {'anytime_td': 0, 'fpts': 114451, 'pass_att': 9590, 'pass_cmp': 9590, 'pass_int': 9590, 'pass_td': 9590, 'pass_yd': 9590, 'rec': 104861, 'rec_yd': 104861, 'rush_att': 28120, 'rush_rec_yd': 74476, 'rush_yd': 37710}}, 'sleeper-matchup-data-integrity-v2': {'unique_receipts': 431, 'eligible_capture_rows': {'anytime_td': 366, 'fpts': 772, 'pass_att': 72, 'pass_cmp': 72, 'pass_int': 72, 'pass_td': 72, 'pass_yd': 72, 'rec': 734, 'rec_yd': 734, 'rush_att': 204, 'rush_rec_yd': 524, 'rush_yd': 276}, 'paired_capture_rows': {'anytime_td': 0, 'fpts': 0, 'pass_att': 52, 'pass_cmp': 52, 'pass_int': 52, 'pass_td': 52, 'pass_yd': 52, 'rec': 600, 'rec_yd': 600, 'rush_att': 168, 'rush_rec_yd': 346, 'rush_yd': 220}}}}
FINAL_LOAD_FLOORS = {'rows':56918,'groups':24295,'outcomes':4830}
FINAL_REFERENCE_CONTEXT_IDS = frozenset(['01515ae50d8129e07627a7597170e03d1ad7ddaeaabc56270e5bb05824e2bccf', '0183e948ab4360a97e8eb02b9fddbad17c6cc11fbf2fdd7d98d0cce191b1994d', '01c1324797562cd61f434b2217d77c1ea6e9f81a67497754c08b5a7f7bb6f7eb', '02515da245258676e12ce48f384a33a09b2c572a5a7e5071b5fa584a55e7fb77', '038a965fa85d8eef70c86dfe84c82ad71da117138ba89bdd10dd3c703f48857a', '03c2a3ed953c54b8d52d9cb998af69e0b3ddb26f7bc87b6638c615e0ecf7d5ae', '03d4267f2f291b91f48a208b4fda6f984440de51cbe37a96d0c9812aa36f942f', '05e5c8f4a81b9c0b0cd23eb3443a3de6f65e4e304c95d9e513e4a55422719fd4', '08f5075e23fb90d09636c2f6d466502d036cb5c8d7c27e83b9688aecd5a1837b', '0ab48ecc68cfdbc387817e48beb10f238505faf94f0994bacb3077f470265083', '0b205690db797f398230ec3554765fde8bcdc8817cec76bb067808f5313c2cf7', '0c63e02505d61b76d27a9fb34765637824d30aa8de05d6f80942203d684f650d', '1349c367652c4dce16c6b256667d3385b9a6cb1d01d7a06337af21c7f129d672', '13fcb3db60e4f2af514ddbe7521b103fe01055328ceeb4b0ef1d14b48b92a724', '1513caeb6807c44f8542061481df67d90115529e7accfc700f0fa35ea412a0b8', '1676bf6fda75ab5716befbe5b88683dd22c23015220b1c915710adeb2e5e300b', '19eb29f350c5aaf522c412521dbe095e282e15fe25c25d027042ef447e5361af', '1a7255ca0058c854cf020eb02cf8d78990f864f53f179a8087d14955594f0d12', '1e9b377713a212170751b9d29e7391f16388bfe24a09f48aea0842d83ff75dd6', '1ff2858e75d9b4f82203e89fe17ed4b8078f65ec28b7f028f19930bf8d8d69c3', '21d550c7be10ea98102262ee89fa60462c51c02399a6e37591f814fbc66c6456', '221092c9e6a68e65e6247af9df0cc488915e9c67c9a53028b86e21fb2db5cf2e', '2219db5a6602f2495a9640f29153c42953c8ee45db4dd00baa94e8f135be8755', '222276f4eaaed8397ab6131551e03fafffaedf77093de3ec87eefc2ce47ee035', '22cdce400b2bf684380ec11052f617325e549e7fda08d3eef0200b9012203e6d', '29bf6d7e9385cb47f114ed9cfd8f3b6d3e197244cdeb55a5334f31bcb3851921', '2cb1620c2f51651c962f146b0384591f04dc8edcd49cc663b4b9566ea91dfa68', '2f494b34574ea74fc479f8505578e8612acc5979e4c6d7f93d8d0f070db6edf3', '3044a32a344d888607afddeee4580a22f588e751f6175f3111a64a63f595eb3d', '3101c09f6e7a0eb35906ae27aef1c817fe1c2265590a830eee9774d20423603f', '31487f1a43d52f77525e3c3687423669a50c06ca551dbab0aebe53bc1e711057', '31edbe9d739e106429c404f7d8f3dc9b11366d096aa59c77b5a4136c9d8c2e11', '34221f9d031a671faa299eb8f76ea802b930344c820a9fc06e0673ca139b0b8f', '37e6b8abffd03d23881dd8428fcfc2668475fa13c25b7dbf68e4bc09229ee0b6', '3864b4185932a5cdef2c2888075555ede1c3c1e9029abc4eb5685fdb41e31c6c', '38abb10ec32c83855e74e2e8ecf723ab14975cba121227c8ccd2fcad0189e894', '38b6f786ea8b5ef2d42d7094281ab023bf76cd1b7838f6e95184a221ede6afd5', '395f4013843e898f3a01a22170a281fce8d28acd6d8206e353277d9fc1b65d34', '39bffb1552c0c983f38d5e11f54289da3f745bf92951108343d0d102b2ba93a6', '3a257b28d922250c0b0774513524a996837a4f76a2926aed24f2dddce9070abe', '3cb571fb423837c909dc35a4bb567c495997988d310eafa42daf4cd65c5ef889', '3f9a738bfe36d59402e24f4a25e63f70bcb6a553499d6c180cf2b3f4628590a6', '43c792be68164e97b2e834b7fe061027e74e1a8c705efa93a2673d5a56658bf9', '44e2346e72a427edc4e5f97b8798657759dbd40536d79b2df27d1c25de42bb31', '48d6bcdd6e29ce6adfe2472a2cb70fba204720f16fd1912a77265a93e5145459', '4e4015571ceb5ba47f8b49dbbf461659311823f1c585107cdf76329a3985555f', '4f8590014c47ddafcf52bdae4e96cb293a87999aa3078fb8e4715d8e06961ca1', '515abf81825732f1ec186552eca4faed21302fa5df44891918d0e38107e882c3', '526987f761ee3e969f8103487ad5b1632fa8195251ac93e84c0a3b75d0c8d1e9', '570e837b894327c7152d80ca8fba6e4c2754ca77d579c6809c372a3ac72c2318', '5d7ae0fd976bedf9044ec5d85f7267e22b1f9439b6b0d3b6f19916dec8ed6ab3', '5eb9b8b124977bbb67946a6871e7f110aab672233bb08828629271a78e334de1', '5fc34a173365f142d02661166bb34830f303bef86bdf089372f1e4b7cffa49f8', '63a28e68aa08a60bd4722a177f7d484de57bda6a4b76a4104ccb9201c388b2fa', '65c01211b7a70a5be77b43a162f05bdfea1c1fa7437871838e171323ec9bee63', '693ed4e191d593e6dcc33b3d43e602f1664ec6ee7d0e921782c2bac835e3009f', '6eb049bb88974849e084d03bc4f3ec10780fe778cf9f9b53dfbb801ab888a999', '7232f81ade6a0df8b4162d886a94d6b16e06b3ad68c776f372b05319909bb086', '733450c78e233562e1402a3b061fe47f019dc21be9235701b3d334ffd2bd8de8', '7553197ae8da08da2df904361932638501f258d0ce9ad36a1878650600a4426b', '75940d5b299ba49ae8beaa684ea8b54a623d4c4310eefc1e2e931ae21bd7ce40', '78a980057ad617dd38eb658229a66da41f45b75440b64d635a1536bd560a90da', '79f39e49a85aecfa0773fa4112d5c2dd926f83a6495c80e70b3de60b4c7b9eb5', '7ac252a246dcdb0fd4963c0e0af5c34a0053214aa399cdd987534f29590f7bab', '7de5a7445f332ce7e354c357a82ea7150122053bcdd53f71da957cd852a84b9d', '7eb6d7503cd05a3b59abbd89be6ee73b69852f09e4bff395bc76fedf4aecee2b', '7f27f476b692186e8550505b8062f530a0a8c0d0cfe161fa52eafc795c8a1cd6', '7fb8ed849a44e3a207a54ddcac3cad492687eaff7494dad37e44bb2a424ab7c1', '8147a4a550c258f46257c2d4be89940ef89e8fa7e0079ad3315bb510757b52d3', '851d54d6fde7390308a492db1a329ad5393623f5768bcb6164fd7566a605f6b5', '8551cfbe2a566293fce8faca58b0bf1d5f5bbcbae41004adacbf8d424887fa53', '875605da910d5b03efbf9835605d75797e63d3efe26946487f15cebbba794197', '88f703e4092cb5e1022eb5cc199b333ba8a9aceebe8efbfdcfccaab30107b3ca', '8a0fe565e4d0d8a8cf5b92c5b91fb79b7559eaf94535e2017708b1f3f86a802f', '8fa40967d7d42c74159a58eeaa385e9efcf4b8b439a6f49ec63516604f4cb5d9', '91202aec9c025cac998f0b33f819c6bbc899b37c371ac9869da07c75b10f200c', '921313a93b863924bc6c3ab3e0d609b14abb118b85b6cef3c7f8a63ca80a8853', '92e83e8c29eb45c16124675695d6e07cf41f1e648a3d05dd9b76a28cf23d6994', '9302004f06fddd32c69dc5e7226361cdd9986c07ce85dc6f5a9e24f1c13ba25e', '98183ce290bae25ddaca15ceab54c758020faa9e3bc0ff15eff0a9542548b45c', '9a203dfa424fe6ca2d6593d5cb3cb9d8a6ca8bf06bd9b551bf8d50d42dff7f58', '9a3d2da487ac88f53cf7164a4b62617956cc9f1f0900d38f0648849ab95195fe', '9b02fd012c002004f2a718917eac49c24073e7cb77872930e28f5af88c5b663f', 'a2745c3a6f6f24dfc150169597a21dadde045a6b888a948443d2616c79b98b02', 'a32744044352a6961ea9ddf3dad20768e0b74ba89af4e19db1d06d56aecdc4e7', 'a35894d27c59d2646d98e56dcf33bbfd4aed15efb910dc418f2c818f955bb882', 'a61e652c1e8fd6f13a5cd9852bf1b70b35c6ab50a35c4cec5d34226638a719ec', 'a8ba1015c089699ed0cc694e39c61e9d3045569ca90535ba2a1573006e8a3497', 'a9848fdad562636e207d9c75e5cfc57fdebbee209627ff09865d26aac6a6cc52', 'ac87693372c8c699b35d0c1dea8f09d6121d7d78f912e39c76ca9324725ed77b', 'ade7e4e5264caf7ee90bcca8cbd7f9d085081d395e987ca200724bef6af82b6c', 'b120d8ee968cf88289f7fafbe613e8b2b2a98d426f56efb126ae5fb04f3e4566', 'b189c3ea08e853a28dd7402ee42819899c4b47beb184b7c8b6f5773a065d35df', 'b6a789236d8051f36939aa2dc09a5606523caf82998b32963b5c7a08319bc6d8', 'b7d1f76afa4bde50b46ab410990d2368c640c6dc8d12d455a9181991ac83bff1', 'ba3511e4a1350ebfb2eaf7772ebe3a5084a4df4f0c6e33c128141d650ef156d9', 'c352c839917ecef44a4fad811c216d76ecd2606ae97c364f6b4eb2d2c639ed20', 'c8b0248a4e39849b4f0443efffd3645382ed8dcc828cf57e17abee4e29f9aec6', 'ca691f8040aa871702c8cb25ede2b557d9241c29d2cf312e07890cafc7246e2f', 'cb6dcdb1be845ec7491851e38203008b37135e3d2d85b2aa94e6477ab7f1b650', 'cb86d3674e289e2ec775f54be531325662ee7a250ed88b639013c18e2a33d7d0', 'cf8bac85d035fe37e887a822b98e0665e470c4c863ce21141c2c4e42d7da46a5', 'd180c49a22916e9c64989450b9f814cd1a3d28215f18557084bd50ba9baa2166', 'd4159d5e1ef971ee6329792d185a5c91ad9d52409184340c282980472b3ef246', 'd5258be20700cb0d9e0d18ccef0d298a9c1cad3252b52478089f62fd97b99c47', 'dab73e07b8dafb40c5220dcaeea23f9b0f7b47fc4a1958a968213fa1a3507d58', 'e000c30abb7b5cf400ae7b1393fc51f82ca26286e516adc3c2eb907642276e13', 'e0a03d6c0e4d3161c1501dff79b27a951d43164d34e010ed091eb4012ee26220', 'e7d20a37a96837d453fea331a8710d376d62e2b988a7d2eb31122119a9861993', 'eb479076bfbe88b7857293387cc59d6039ed9efb7f207f65d267c1059932cbc0', 'ebac7df9fd88b01579391ccbdf53e7387de45257e336aca08b9ecc4fe4efe728', 'ec54e83ab7431a22213634b259fc810db0e9aed47666797aaae3b260b56c87b8', 'ed7fa607e1c7aed32eeeecd69cb6daeb836147f75d9957c4299a63007c333abe', 'eeac2da5d457d8f618f0b1d0d3ef69cdea7e8670fbf7e9a22a370f8b41b87a00', 'ef38df88304c817f6549947470544bcc66e47e5dfbdd6da823658dbbfe55b09b', 'efcc24bb959710c520279870aa944bbc8fb33832f32a4db1e880e81bdab6a354', 'f15f459cc224806265482f431d26844ec769851d7dc1f188d6d4a3538f8f9d0d', 'f342e76bf5fd10b4424faffbd0587c399bdd984892c46bec920625d77a98e64d', 'f67f83ebec1418a4dcfc6ea709e706959c82ab123f43bc3d0c6d79048ae1df61', 'fd3eeee600cf74b2f0b95490ece12d5b9f88ad81216f2a6a39077825068a3639', 'fe04fb5d1dd7cea894d4fb1ad8dae208e3f12d892b7782ebeb9071dd1c368092', 'ff71ce2e79563477653da0406e4015d5e396530e29c9b7511024349ceb517782'])
FINAL_COHORTS = frozenset(seed_v1.REQUIRED_SETS['cohorts'] | {'ranked_biggest_lean_v1','ranked_projected_points_v1'})
FINAL_DIMENSIONS = frozenset({'category_side','selection_weekday','kickoff_weekday','lead_time_bucket','category_side_selection_kickoff_lead'})
FINAL_ACCURACY_CATEGORIES = frozenset(seed_v1.REQUIRED_SETS['categories'] | {'fpts','anytime_td'})
FINAL_ACCURACY_MODELS = frozenset({'original_sleeper_matchup_baseline','sleeper-matchup-data-integrity-v2'})
FINAL_ACCURACY_ENGINES = {'original_sleeper_matchup_baseline':'e8e8823f460e074485ee91a0dc1c1cfc43877146c4498ef074d15d2b5a735d07','sleeper-matchup-data-integrity-v2':'3909c7ac5470970182065576f057e8036f31ad30da13f1ef9999eb1108a183b4'}


def _metric_counts(values):
    return dict(sorted(Counter('unavailable' if v is None else str(v) for v in values).items()))


def _final_statistic_contracts():
    # Exact existing model/schema dispatch, using the actual reviewed source.
    # A caller-supplied digest or self-consistent metric hash has no authority.
    from scorecard import descriptive_contract
    return {model:sha(encoded(descriptive_contract(presence_aware=model=='sleeper-matchup-data-integrity-v2')))
        for model in FINAL_ACCURACY_MODELS}


def _accuracy_workload(value):
    # publication_contents already invokes the unchanged typed accuracy reader.
    # Preserve supported zero/pending populations; category keys alone prove no work.
    cohorts=[]
    for cohort in value['cohorts']:
        categories={}
        for category,v in cohort['categories'].items():
            item={k:copy.deepcopy(v[k]) for k in ('coverage','paired_coverage','unpaired_coverage','outcome_status')}
            item.update(paired_resolved=v['paired']['raw']['n'],adjusted_only_resolved=v['adjusted_only']['n'])
            if category=='fpts':item['direct_provider_ppr_resolved']=v['direct_provider_ppr']['raw']['n']
            if category=='anytime_td':item['probability']={basis:metrics['n'] for basis,metrics in v['probability'].items()}
            categories[category]=item
        cohorts.append({**{k:copy.deepcopy(cohort[k]) for k in ('model_version','engine_sha256','period','forecast_provenance','outcome_provenance','statistic_contract_sha256','source_report_sha256','coverage')},'categories':categories})
    return dict(schema_version=value['schema_version'],content_sha256=sha(encoded(value)),
        capture_coverage=copy.deepcopy(value['capture_coverage']),cohorts=cohorts)


def _final_workload_decisions(value):
    metrics=value['metrics'];coverage=value['coverage'];accuracy=value['accuracy']
    numeric={name:type(metrics.get(name)) is int and metrics[name]>=floor for name,floor in FINAL_LOAD_FLOORS.items()}
    captures={v['model_version']:v for v in accuracy['capture_coverage']}
    cohorts=accuracy['cohorts']
    def present(name,required):return all(coverage[name].get(key,0)>0 for key in required)
    original=[v for v in cohorts if v['model_version']=='original_sleeper_matchup_baseline']
    categorical={
        'current_v4_publication':value['report_schema_version']=='selection-report-v4',
        'source_bound_current_capture':value['publication_source']==value['candidate']['commit'] and value['generation_source']==value['candidate']['commit'],
        'categories':present('categories',seed_v1.REQUIRED_SETS['categories']),
        'sides':present('sides',{'over','under'}),
        'sources':present('sources',seed_v1.REQUIRED_SETS['sources']),
        'cohorts':present('cohorts',FINAL_COHORTS),
        'checkpoints':present('checkpoints',seed_v1.REQUIRED_SETS['checkpoints']),
        'joint_and_timing_dimensions':present('dimensions',FINAL_DIMENSIONS),
        'preserved_result_states':present('results',seed_v1.REQUIRED_SETS['status_counts']),
        'genuine_ranked_membership':all(type(coverage['strategy_selected'].get(name)) is int and coverage['strategy_selected'][name]>0 for name in ('ranked_biggest_lean_v1','ranked_projected_points_v1')),
        'accuracy_schema':accuracy['schema_version']=='forecast-accuracy-public-v1',
        'accuracy_models':FINAL_ACCURACY_MODELS<=set(captures) and FINAL_ACCURACY_MODELS<={v['model_version'] for v in cohorts} and all(any(v['model_version']==model and v['coverage']['opportunities']>0 for v in cohorts) for model in FINAL_ACCURACY_MODELS),
        'accuracy_actual_category_populations':all(model in captures and FINAL_ACCURACY_CATEGORIES<=set(captures[model]['capture_coverage']['eligible_capture_rows']) and all(captures[model]['capture_coverage']['eligible_capture_rows'][cat]>0 for cat in FINAL_ACCURACY_CATEGORIES) for model in FINAL_ACCURACY_MODELS),
        'original_numerical_resolved_controls':all(any(v['categories'][cat]['paired_resolved']>0 for v in original) for cat in seed_v1.REQUIRED_SETS['categories']),
        'original_ppr_resolved_control':any(v['categories']['fpts']['paired_resolved']>0 for v in original),
        'original_supported_td_probability_control':any(v['categories']['anytime_td']['probability'].get('rederived_from_original_count_retained_formula',0)>0 for v in original),
        'retained_full_history':metrics['complete_generations']>=24,
    }
    return dict(numeric=numeric,categorical=categorical,admitted=all(numeric.values()) and all(categorical.values()))


def _final_applicability(value):
    """Conservative applicability, distinct from frozen admission and timing.

    An unmatched real observation/byte workload requires a later matched case;
    it never changes the frozen fictional population or invents history.
    """
    comparisons={};deficiencies=[]
    def compare(name,actual,reference,*,present=True):
        if present and (type(actual) is not int or actual<0):raise RuntimeError('Malformed final applicability dimension: '+name)
        covers=present and actual>=reference
        record={'actual':actual if present else None,'reference':reference,'covers':covers,'presence':'MEASURED' if present else 'ABSENT_UNESTABLISHED'}
        comparisons[name]=record
        if not covers:deficiencies.append(name)
    reference={**FINAL_LOAD_FLOORS,**FINAL_REFERENCE['informational_descriptor_metrics']}
    for name,minimum in reference.items():compare('report.'+name,value['metrics'].get(name),minimum)
    captures={v['model_version']:v['capture_coverage'] for v in value['accuracy']['capture_coverage']}
    for model,expected in FINAL_REFERENCE['accuracy_capture_work'].items():
        actual=captures.get(model,{})
        compare('accuracy.'+model+'.unique_receipts',actual.get('unique_receipts'),expected['unique_receipts'],present='unique_receipts' in actual)
        for lane in ('eligible_capture_rows','paired_capture_rows'):
            for category,minimum in expected[lane].items():
                compare('accuracy.'+model+'.'+lane+'.'+category,actual.get(lane,{}).get(category),minimum,present=category in actual.get(lane,{}))
    return dict(status='CONSERVATIVE_REFERENCE_ENVELOPE_COVERED' if not deficiencies else 'UNKNOWN_ADDITIONAL_MATCHED_REAL_CASE_REQUIRED',
        comparisons=comparisons,deficiencies=deficiencies,
        limitation='Measured fictional compute is not a matched production/configuration/provider/publication qualification')


def _check_final_workload(value,source=None,tree=None,*,require_admitted=True,projection=False):
    expected={'schema_version','candidate','publication_source','generation_source','generation_sha256','report_id','report_schema_version','summary_index_sha256','semantics_sha256','reference','metrics','coverage','contexts','accuracy','decisions','applicability'}
    original=value
    if projection:expected=expected|{'private_metrics_sha256'}
    version='final-candidate-workload-projection-v1' if projection else 'final-candidate-workload-v1'
    if type(value) is not dict or set(value)!=expected or value.get('schema_version')!=version or value.get('reference')!=FINAL_REFERENCE:
        raise RuntimeError('Missing exact final-candidate workload metrics')
    if projection:
        if not _hex(value['private_metrics_sha256'],HEX64):raise RuntimeError('Missing full private metrics binding')
        value=copy.deepcopy(value)
        contexts=value['contexts'];indices=contexts.pop('missing_reference_indices',None)
        reference_ids=sorted(FINAL_REFERENCE_CONTEXT_IDS)
        if type(indices) is not list or indices!=sorted(set(indices)) or any(type(i) is not int or not 0<=i<len(reference_ids) for i in indices) or 'missing_reference_ids' in contexts:raise RuntimeError('Malformed compact exact reference context IDs')
        contexts['missing_reference_ids']=[reference_ids[i] for i in indices]
        fields=('opportunities','unique_players','unique_games','unique_weeks')
        for cohort in value['accuracy']['cohorts']:
            for item,keys in [(cohort,('coverage',)),*((v,('coverage','paired_coverage','unpaired_coverage')) for v in cohort['categories'].values())]:
                for key in keys:
                    counts=item[key]
                    if type(counts) is not list or len(counts)!=4 or any(type(n) is not int or n<0 for n in counts):raise RuntimeError('Malformed compact accuracy sample')
                    item[key]=dict(zip(fields,counts))
    candidate=value['candidate']
    if (type(candidate) is not dict or set(candidate)!={'commit','tree'} or any(not _hex(candidate[k],HEX40) for k in candidate)
            or candidate['commit']==BASE or source is not None and candidate['commit']!=source or tree is not None and candidate['tree']!=tree
            or value['publication_source']!=candidate['commit'] or value['generation_source']!=candidate['commit']):
        raise RuntimeError('Final workload source/version mixing')
    for key in ('generation_sha256','report_id','summary_index_sha256','semantics_sha256'):
        if not _hex(value[key],HEX64):raise RuntimeError('Invalid final workload identity')
    metrics=value['metrics']
    if type(metrics) is not dict or set(metrics)!=set(FINAL_METRICS) or any(type(n) is not int or not 0<=n<=9007199254740991 for n in metrics.values()):
        raise RuntimeError('Missing bounded final workload counts/bytes')
    coverage=value['coverage']
    allowed={'categories','sides','sources','cohorts','checkpoints','dimensions','results','periods','strategy_selected'}
    if type(coverage) is not dict or set(coverage)!=allowed or any(type(v) is not dict or len(v)>256 or any(type(k) is not str or len(k)>160 or type(n) is not int or n<0 for k,n in v.items()) for v in coverage.values()):
        raise RuntimeError('Invalid final semantic coverage')
    contexts=value['contexts']
    context_fields={'descriptors_sha256','missing_reference_ids','correspondence'}|({'ids_sha256','extra_reference_count','extra_reference_ids_sha256'} if projection else {'ids','extra_reference_ids'})
    if type(contexts) is not dict or set(contexts)!=context_fields or not _hex(contexts['descriptors_sha256'],HEX64):raise RuntimeError('Missing final context descriptor binding')
    for name in (('missing_reference_ids',) if projection else ('ids','missing_reference_ids','extra_reference_ids')):
        values=contexts[name]
        if type(values) is not list or len(values)>512 or values!=sorted(set(values)) or any(not _hex(v,HEX64) for v in values):raise RuntimeError('Invalid exact final context IDs')
    if projection:
        coherent=(set(contexts['missing_reference_ids'])<=FINAL_REFERENCE_CONTEXT_IDS and type(contexts['extra_reference_count']) is int and 0<=contexts['extra_reference_count']<=512
            and metrics['contexts']==len(FINAL_REFERENCE_CONTEXT_IDS)-len(contexts['missing_reference_ids'])+contexts['extra_reference_count']
            and all(_hex(contexts[k],HEX64) for k in ('ids_sha256','extra_reference_ids_sha256')))
    else:
        coherent=(metrics['contexts']==len(contexts['ids']) and contexts['missing_reference_ids']==sorted(FINAL_REFERENCE_CONTEXT_IDS-set(contexts['ids'])) and contexts['extra_reference_ids']==sorted(set(contexts['ids'])-FINAL_REFERENCE_CONTEXT_IDS))
    if not coherent or contexts['correspondence']!='EXACT_DESCRIPTOR_IDS_MISSING_EXTRA_REPORTED_NOT_SYNTHETIC_HISTORY':raise RuntimeError('Final context correspondence differs')
    accuracy=value['accuracy']
    if type(accuracy) is not dict or set(accuracy)!={'schema_version','content_sha256','capture_coverage','cohorts'} or not _hex(accuracy['content_sha256'],HEX64):raise RuntimeError('Missing final accuracy work')
    if type(accuracy['capture_coverage']) is not list or len(accuracy['capture_coverage'])>2 or type(accuracy['cohorts']) is not list or len(accuracy['cohorts'])>12:raise RuntimeError('Invalid final accuracy population bound')
    seen=set()
    for capture in accuracy['capture_coverage']:
        if type(capture) is not dict or set(capture)!={'model_version','capture_coverage','unsupported_outcome_counts'} or capture['model_version'] not in FINAL_ACCURACY_MODELS or capture['model_version'] in seen:raise RuntimeError('Mixed final accuracy capture models')
        seen.add(capture['model_version']);v=capture['capture_coverage']
        if type(v) is not dict or set(v)!={'unique_receipts','duplicate_receipts','eligible_capture_rows','paired_capture_rows','excluded'} or any(type(v[k]) is not int or v[k]<0 for k in ('unique_receipts','duplicate_receipts')):raise RuntimeError('Invalid actual accuracy capture counts')
        for key in ('eligible_capture_rows','paired_capture_rows','excluded'):
            if type(v[key]) is not dict or any(type(n) is not int or n<0 for n in v[key].values()):raise RuntimeError('Invalid actual accuracy capture rows')
        if any(n>v['eligible_capture_rows'].get(category,0) for category,n in v['paired_capture_rows'].items()):raise RuntimeError('Final paired capture count exceeds eligible captures')
    cohort_keys=set();statistic_contracts=_final_statistic_contracts()
    for cohort in accuracy['cohorts']:
        keys={'model_version','engine_sha256','period','forecast_provenance','outcome_provenance','statistic_contract_sha256','source_report_sha256','coverage','categories'}
        if type(cohort) is not dict or set(cohort)!=keys or cohort['model_version'] not in FINAL_ACCURACY_MODELS or cohort['period']!='cumulative' or cohort['forecast_provenance']!='original_recorded_pregame_observation' or cohort['outcome_provenance'] not in {'missing','unknown_unverified','identity_quarantined','conflicting_outcome_evidence','saved_cache_descriptive_regrade','recorded_outcome_receipt'}:raise RuntimeError('Mixed final accuracy cohort identity')
        if any(not _hex(cohort[k],HEX64) for k in ('engine_sha256','statistic_contract_sha256','source_report_sha256')) or set(cohort['categories'])!=FINAL_ACCURACY_CATEGORIES:raise RuntimeError('Incomplete final accuracy categories')
        key=(cohort['model_version'],cohort['outcome_provenance'])
        if key in cohort_keys or cohort['engine_sha256']!=FINAL_ACCURACY_ENGINES[cohort['model_version']]:raise RuntimeError('Mixed final accuracy engine/cohort')
        cohort_keys.add(key)
        if cohort['statistic_contract_sha256']!=statistic_contracts[cohort['model_version']]:raise RuntimeError('Unsupported final accuracy statistic contract')
        if type(cohort['coverage']) is not dict or set(cohort['coverage'])!={'opportunities','unique_players','unique_games','unique_weeks'} or any(type(n) is not int or n<0 for n in cohort['coverage'].values()):raise RuntimeError('Invalid final accuracy cohort sample')
        for category,item in cohort['categories'].items():
            fields={'coverage','paired_coverage','unpaired_coverage','outcome_status','paired_resolved','adjusted_only_resolved'}|({'direct_provider_ppr_resolved'} if category=='fpts' else {'probability'} if category=='anytime_td' else set())
            if type(item) is not dict or set(item)!=fields:raise RuntimeError('Incomplete final accuracy category work')
            for name in ('coverage','paired_coverage','unpaired_coverage'):
                if type(item[name]) is not dict or set(item[name])!={'opportunities','unique_players','unique_games','unique_weeks'} or any(type(n) is not int or n<0 for n in item[name].values()):raise RuntimeError('Invalid final accuracy sample')
            if type(item['outcome_status']) is not dict or any(type(n) is not int or n<0 for n in item['outcome_status'].values()):raise RuntimeError('Invalid final accuracy outcome states')
            if any(type(item[k]) is not int or item[k]<0 for k in ('paired_resolved','adjusted_only_resolved')):raise RuntimeError('Invalid final resolved accuracy work')
            if category=='fpts' and (type(item['direct_provider_ppr_resolved']) is not int or item['direct_provider_ppr_resolved']<0):raise RuntimeError('Invalid final direct-provider PPR work')
            if category=='anytime_td' and (set(item['probability'])!={'originally_recorded_probability','rederived_from_original_count_retained_formula'} or any(type(n) is not int or n<0 for n in item['probability'].values())):raise RuntimeError('Invalid final TD probability work')
            for name in ('coverage','paired_coverage','unpaired_coverage'):
                sample=item[name]
                if any(sample[k]>sample['opportunities'] for k in ('unique_players','unique_games','unique_weeks')) or sample['opportunities'] and any(sample[k]==0 for k in ('unique_players','unique_games','unique_weeks')):raise RuntimeError('Final accuracy sample identities exceed population')
            resolved=item['outcome_status'].get('resolved',0)
            if (item['paired_resolved']>item['paired_coverage']['opportunities'] or item['adjusted_only_resolved']>item['unpaired_coverage']['opportunities'] or sum(item['outcome_status'].values())!=item['coverage']['opportunities']
                or item['paired_coverage']['opportunities']+item['unpaired_coverage']['opportunities']>item['coverage']['opportunities'] or item['paired_resolved']+item['adjusted_only_resolved']>resolved
                or any(item[name][k]>cohort['coverage'][k] for name in ('coverage','paired_coverage','unpaired_coverage') for k in ('opportunities','unique_players','unique_games','unique_weeks'))):raise RuntimeError('Final accuracy populations do not reconcile')
            if category=='fpts' and item['direct_provider_ppr_resolved']>item['paired_resolved']:raise RuntimeError('Direct-provider PPR exceeds supported pairs')
            if category=='anytime_td' and sum(item['probability'].values())>resolved:raise RuntimeError('TD probability bases exceed resolved population')
        if sum(item['coverage']['opportunities'] for item in cohort['categories'].values())!=cohort['coverage']['opportunities']:raise RuntimeError('Final category populations do not reconcile with cohort')
    decisions=_final_workload_decisions(value)
    if value['decisions']!=decisions:raise RuntimeError('Final workload decisions were not recomputed')
    if value['applicability']!=_final_applicability(value):raise RuntimeError('Final workload applicability was not recomputed')
    if require_admitted and not decisions['admitted']:raise RuntimeError('Final candidate does not cover the real release load/semantic envelope')
    return original


def _public_final_workload(value):
    _check_final_workload(value,require_admitted=False)
    result=copy.deepcopy(value);result['schema_version']='final-candidate-workload-projection-v1'
    result['private_metrics_sha256']=sha(encoded(value))
    contexts=result['contexts'];ids=contexts.pop('ids');extra=contexts.pop('extra_reference_ids')
    contexts.update(ids_sha256=sha(encoded(ids)),extra_reference_count=len(extra),extra_reference_ids_sha256=sha(encoded(extra)))
    reference_ids=sorted(FINAL_REFERENCE_CONTEXT_IDS)
    contexts['missing_reference_indices']=[reference_ids.index(key) for key in contexts.pop('missing_reference_ids')]
    fields=('opportunities','unique_players','unique_games','unique_weeks')
    for cohort in result['accuracy']['cohorts']:
        for item,keys in [(cohort,('coverage',)),*((v,('coverage','paired_coverage','unpaired_coverage')) for v in cohort['categories'].values())]:
            for key in keys:item[key]=[item[key][name] for name in fields]
    _check_final_workload(result,require_admitted=False,projection=True)
    return result


FINAL_METRICS=('rows','groups','outcomes','contexts','summary_partitions','row_chunks','complete_generations',
    'row_encoded_bytes','row_decoded_bytes','summary_encoded_bytes','summary_decoded_bytes','outcome_encoded_bytes','outcome_decoded_bytes',
    'staged_files','staged_bytes','staged_report_bytes','stored_report_bytes')


def _bound_final_graph(root,pages,publication):
    base=root/'output/data/selection-grading';delivery=pages/'data/selection-grading'
    raw_pointer=_bounded_file(base/'latest.json',JSON_LIMIT);pointer=_decoded(raw_pointer)
    if pointer.get('schema_version')!='selection-publication-pointer-v4' or not _hex(pointer.get('report_id'),HEX64):raise RuntimeError('Final metrics require the actual current shared publication')
    raw_generation=_bounded_file(root/'output/data/release-identity.json',JSON_LIMIT)
    generation=_decoded(raw_generation);bindings={'data/selection-grading/latest.json':raw_pointer,'data/release-identity.json':raw_generation}
    indices={}
    for name in ('summary','outcomes'):
        descriptor=pointer[name]
        # Reuse the actual strict bounded descriptor/path/hash reader on both
        # trust namespaces; this is metadata binding, not history replay.
        indices[name]=publication._partition_asset(base,descriptor,name+'.json',index=True,report_id=pointer['report_id'])
        delivered=publication._partition_asset(delivery,descriptor,name+'.json',index=True,report_id=pointer['report_id'])
        raw=_bounded_file(base/descriptor['path'],JSON_LIMIT)
        if len(raw)!=descriptor['decoded_bytes'] or sha(raw)!=descriptor['sha256'] or delivered!=indices[name]:raise RuntimeError('Final index descriptor changed during metric collection')
        bindings['data/selection-grading/'+descriptor['path']]=raw
    for name,raw in bindings.items():
        if _bounded_file(root/'output'/name,JSON_LIMIT)!=raw or _bounded_file(pages/name,JSON_LIMIT)!=raw:raise RuntimeError('Final metric graph differs from actual staged generation')
    if (indices['summary'].get('report_id')!=pointer['report_id'] or indices['outcomes'].get('report_id')!=pointer['report_id']
        or generation.get('selection_report_id')!=pointer['report_id'] or indices['summary'].get('row_count')!=pointer['row_count']):raise RuntimeError('Final report/generation metadata identities differ')
    return pointer,indices['summary'],indices['outcomes'],generation,{name:sha(raw) for name,raw in bindings.items()}


def final_candidate_workload(code,root,m,pages):
    # Existing stage_pages has already performed mandatory current/previous,
    # archive, source and independent-destination checks. Do not replay those
    # histories merely to count them. Read the current complete semantic graph.
    identity=execution_identity(code,root)
    for key,name in (('capture','phase2_capture.py'),('publication','selection_publication.py')):
        if Path(m[key].__file__).resolve()!=root/'tools'/name:raise RuntimeError('Final metrics must use actual installed candidate consumers')
    base=root/'output/data/selection-grading'
    pointer,index,outcome_index,generation,bindings=_bound_final_graph(root,pages,m['publication'])
    summary,rows,outcomes=m['publication'].publication_contents(base,pointer)
    if summary.get('report_id')!=pointer['report_id'] or len(rows)!=pointer['row_count'] or len(outcomes)!=outcome_index['outcome_count']:raise RuntimeError('Final semantic reader differs from bound metadata')
    if generation.get('schema_version')!='website-generation-v1':raise RuntimeError('Final metrics require the actual connected capture, not saved B3 packaging')
    contexts=index['contexts']
    if len(contexts)>512 or any(sha(encoded(v))!=k for k,v in contexts.items()):raise RuntimeError('Final context descriptor identity')
    tables=summary['summary']['tables'];working=_load(base/'hosting.json')
    registry=m['capture']._registry(base,working)
    staged=[p for p in pages.rglob('*') if p.is_file()]
    if any(p.is_symlink() for p in staged):raise RuntimeError('Unsupported final staged asset')
    parts=index['summary_partitions'];outparts=outcome_index['periods']
    metrics=dict(rows=len(rows),groups=len(tables),outcomes=len(outcomes),contexts=len(contexts),summary_partitions=len(parts),row_chunks=len(pointer['rows']),complete_generations=len(registry),
        row_encoded_bytes=sum(d['encoded_bytes'] for d in pointer['rows']),row_decoded_bytes=sum(d['decoded_bytes'] for d in pointer['rows']),summary_encoded_bytes=sum(d['encoded_bytes'] for d in parts),summary_decoded_bytes=sum(d['decoded_bytes'] for d in parts),outcome_encoded_bytes=sum(d['encoded_bytes'] for d in outparts),outcome_decoded_bytes=sum(d['decoded_bytes'] for d in outparts),
        staged_files=len(staged),staged_bytes=sum(p.stat().st_size for p in staged),staged_report_bytes=sum(p.stat().st_size for p in staged if p.is_relative_to(pages/'data/selection-grading')),stored_report_bytes=sum(p.stat().st_size for p in base.rglob('*') if p.is_file()))
    coverage=dict(categories=_metric_counts(r['category'] for r in rows),sides=_metric_counts(r['side'] for r in rows),sources=_metric_counts(t['line_source_scope'] for t in tables),cohorts=_metric_counts(t['view'] for t in tables),checkpoints=_metric_counts(r['checkpoint'] for r in rows),dimensions=_metric_counts(t['dimension'] for t in tables),results=_metric_counts(r['result'] for r in rows),periods=_metric_counts(t['period'] for t in tables),
        strategy_selected={name:sum(r['cohort']==name and r['action']=='SELECT' and r.get('strategy_receipt_sha256') is not None and r.get('strategy_rank') is not None for r in rows) for name in ('ranked_biggest_lean_v1','ranked_projected_points_v1')})
    result=dict(schema_version='final-candidate-workload-v1',candidate={'commit':identity['candidate_commit'],'tree':identity['candidate_tree']},publication_source=index['source_sha'],generation_source=generation['source_sha'],generation_sha256=generation['generation_sha256'],report_id=pointer['report_id'],report_schema_version=index['report_schema_version'],summary_index_sha256=_hash_file(base/pointer['summary']['path']),semantics_sha256=sha(encoded(dict(summary=summary,rows=rows,outcomes=outcomes))),reference=copy.deepcopy(FINAL_REFERENCE),metrics=metrics,coverage=coverage,
        contexts=dict(ids=sorted(contexts),descriptors_sha256=sha(encoded(contexts)),missing_reference_ids=sorted(FINAL_REFERENCE_CONTEXT_IDS-set(contexts)),extra_reference_ids=sorted(set(contexts)-FINAL_REFERENCE_CONTEXT_IDS),correspondence='EXACT_DESCRIPTOR_IDS_MISSING_EXTRA_REPORTED_NOT_SYNTHETIC_HISTORY'),accuracy=_accuracy_workload(summary['forecast_accuracy']))
    result['decisions']=_final_workload_decisions(result)
    result['applicability']=_final_applicability(result)
    if _bound_final_graph(root,pages,m['publication'])[4]!=bindings:raise RuntimeError('Final staged graph changed while collecting metrics')
    _check_final_workload(result,identity['candidate_commit'],identity['candidate_tree'],require_admitted=False)
    # Full actual descriptors stay private and bound to the public compact hash.
    put(root.parent/'FINAL_CONTEXT_DESCRIPTORS.private.json',contexts)
    return result


def _evidence_aggregates(work):
    admission_raw=_bounded_file(work/'admission.json',JSON_LIMIT);admission=_decoded(admission_raw)
    metrics=admission['metrics'];decisions=seed_v1.admission_decisions(metrics)
    if (admission.get('status')!='ADMITTED' or admission.get('required_decisions')!=decisions
            or not all(decisions[k] is True for k in ('all_numeric_pass','categorical_pass','population_pass'))):
        raise RuntimeError('Fresh workload admission does not satisfy its unchanged contract')
    numeric={k:{'actual':metrics[k],'required':minimum,'meets':decisions['numeric'][k]} for k,minimum in seed_v1.ENVELOPE.items()}
    semantics=metrics.get('public_semantics_sha256')
    if not _hex(semantics,HEX64):raise RuntimeError('Missing admitted semantics identity')
    dataflow_raw=_bounded_file(work/'dataflow.json',JSON_LIMIT);dataflow=_decoded(dataflow_raw);correction=dataflow['material_correction']
    final=_check_final_workload(dataflow.get('final_candidate_workload'))
    expected=correction['expected']['expected'];count=correction['changed_decisions']
    if (dataflow.get('status')!='PASS_DATAFLOW_ONLY_NOT_WHOLE_JOB' or correction.get('status')!='PASS_ACTUAL_SAVED_CONSUMERS'
            or type(expected) is not list or type(count) is not int or count!=len(expected) or count<1
            or (correction['expected']['before'],correction['expected']['after'])!=(3,8)):
        raise RuntimeError('Material correction did not satisfy its predeclared affected set')
    outcome_counts={k:correction[k] for k in ('original_outcome_count','new_outcome_count')}
    if any(type(v) is not int or v<0 for v in outcome_counts.values()):raise RuntimeError('Invalid outcome count')
    advisory=dataflow['advisories']
    if (set(advisory.get('outcomes',{}))!={'legacy_verifier','historical_comparison'}
            or advisory.get('remote_continuation') not in ('UNMEASURED','NOT_REQUESTED')
            or type(advisory.get('unsupported_raw_http_calls')) is not int or advisory['unsupported_raw_http_calls']<0):
        raise RuntimeError('Missing actual advisory execution measurement')
    public_advisory={}
    for name,value in advisory['outcomes'].items():
        if value.get('outcome') not in ('success','failure') or type(value.get('returncode')) is not int:raise RuntimeError('Invalid advisory result')
        public_advisory[name]={'outcome':value['outcome'],'returncode':value['returncode']}
    return dict(final_candidate_workload=_public_final_workload(final),admission=dict(numeric_floors=numeric,categorical=decisions['categorical'],population_pass=decisions['population_pass'],
        game_states=metrics['game_states'],qualification_counts=metrics['latest_scope_classifications'],public_semantics_sha256=semantics,
        original_file_sha256=sha(admission_raw)),
        advisories=dict(outcomes=public_advisory,remote_continuation=advisory['remote_continuation'],unsupported_raw_http_calls=advisory['unsupported_raw_http_calls']),
        correction=dict(before=3,after=8,expected_affected_count=len(expected),actual_changed_count=count,
            expected_set_sha256=sha(encoded(expected)),declaration_sha256=sha(encoded(correction['expected'])),
            **outcome_counts,original_file_sha256=sha(dataflow_raw)))


def _check_evidence_projection(evidence,source=None,tree=None):
    if type(evidence) is not dict or set(evidence)!={'admission','correction','advisories','final_candidate_workload'}:raise RuntimeError('Fresh workload/correction measurements missing')
    _check_final_workload(evidence['final_candidate_workload'],source,tree,projection=True)
    advisory=evidence['advisories']
    if (set(advisory.get('outcomes',{}))!={'legacy_verifier','historical_comparison'}
            or advisory.get('remote_continuation') not in ('UNMEASURED','NOT_REQUESTED')
            or type(advisory.get('unsupported_raw_http_calls')) is not int or advisory['unsupported_raw_http_calls']<0
            or any(v.get('outcome') not in ('success','failure') or type(v.get('returncode')) is not int for v in advisory['outcomes'].values())):
        raise RuntimeError('Actual advisory outcome measurements missing')
    admission=evidence['admission'];correction=evidence['correction'];numeric=admission.get('numeric_floors',{})
    categorical=set(seed_v1.REQUIRED_SETS)|{'outcome_revisions','original_contexts','recorders_inactive','original_schema',
        'corrected_schema','archives','scope_schema','original_comparator'}
    if (set(numeric)!=set(seed_v1.ENVELOPE) or set(admission.get('categorical',{}))!=categorical
            or any(v is not True for v in admission['categorical'].values()) or admission.get('population_pass') is not True
            or admission.get('game_states')!={'post':2,'in':7,'pre':5}
            or admission.get('qualification_counts')!={'retained_legacy_original_proof_missing':9,'new_pregame_original_inputs_verified':5}):
        raise RuntimeError('Derived admission coverage is incomplete')
    for key,floor in seed_v1.ENVELOPE.items():
        value=numeric[key]
        if (type(value) is not dict or set(value)!={'actual','required','meets'} or type(value['actual']) is not int
                or value['actual']<floor or value['required']!=floor or value['meets'] is not True):raise RuntimeError('Derived numeric admission floor failed')
    if (correction.get('before'),correction.get('after'))!=(3,8) or type(correction.get('expected_affected_count')) is not int or correction['expected_affected_count']<1 or correction.get('actual_changed_count')!=correction['expected_affected_count']:
        raise RuntimeError('Derived material correction set differs')
    for key in ('original_outcome_count','new_outcome_count'):
        if type(correction.get(key)) is not int or correction[key]<0:raise RuntimeError('Derived outcome count invalid')
    for obj,keys in ((admission,('public_semantics_sha256','original_file_sha256')),(correction,('expected_set_sha256','declaration_sha256','original_file_sha256'))):
        if any(not _hex(obj.get(k),HEX64) for k in keys):raise RuntimeError('Missing derived evidence identity')


def _capability_projection(measured,outer,actual,run,sample):
    files={f['path']:{'sha256':f['sha256'],'bytes':f['bytes']} for f in actual['files']}
    source=outer.get('source',{});raw=encoded(measured)
    if (outer.get('schema_version')!='operating-root-execution-v1' or outer.get('mode')!='capability'
            or outer.get('status')!='CAPABILITY_READY' or outer.get('resource_verdict')!='NOT_RUN_CAPABILITY_ONLY'
            or outer.get('root_uid')!=0 or outer.get('run_id')!=run or outer.get('sample')!=sample
            or outer.get('run_attempt')!=1 or source.get('commit')!=actual['commit'] or source.get('tree')!=actual['tree']
            or not source.get('files') or any(files.get(k)!=v for k,v in source['files'].items())
            or outer.get('worker_argv') is not None or outer.get('seed_manifest_sha256') is not None
            or outer.get('transport_approval')!='NOT_REQUIRED_CAPABILITY_ONLY' or outer.get('resource_supervisor_returncode')!=0
            or outer.get('resource_report')!={'sha256':sha(raw),'bytes':len(raw)}
            or measured.get('status')!='CAPABILITY_READY' or measured.get('complete_tree') is not True
            or measured.get('resource_verdict')!='NOT_RUN_CAPABILITY_ONLY' or measured.get('cleanup_error')):
        raise RuntimeError('Actual no-seed capability binding is incomplete')
    caps=measured['capability'];disks={};limits={}
    for i,(_,value) in enumerate(sorted(caps['filesystems'].items())):
        if type(value.get('free')) is not int or type(value.get('total')) is not int:raise RuntimeError('Invalid filesystem capability fact')
        disks['filesystem-'+str(i).zfill(2)]={'free':value['free'],'total':value['total']}
    for i,(_,value) in enumerate(sorted(caps['ancestor_limits'].items())):
        if value!='max' and (type(value) is not str or not value.isdigit()):raise RuntimeError('Invalid ancestor limit')
        limits['scope-'+str(i).zfill(2)]=None if value=='max' else int(value)
    return dict(status='CAPABILITY_READY',resources='NOT_RUN_CAPABILITY_ONLY',source_tree=actual['tree'],
        source_manifest_sha256=actual['source_manifest_sha256'],capability=dict(filesystems=disks,ancestor_limits=limits,
            fresh_peak_reset_and_leaf_creation_tested=True,privilege_drop_tested=False,workload_memory_measurement='NOT_RUN',
            source_ci_qualification='NOT_RUN',planning_qualification='NOT_RUN'))


def project(code,root,result,sample_number):
    """Validate protected originals in-run; emit a derived numeric record only."""
    run=int(os.environ['GITHUB_RUN_ID']);source=os.environ['GITHUB_SHA']
    expected=Path(os.environ['RUNNER_TEMP']).resolve()/('nfl-operating-'+str(sample_number))
    if (root!=expected/'fixture' or result!=expected/'RESULT.json' or sample_number not in (1,2,3)
            or os.environ.get('GITHUB_RUN_ATTEMPT')!='1' or os.environ.get('GITHUB_EVENT_NAME')!='workflow_dispatch'):
        raise RuntimeError('Wrong exact projection invocation')
    record=dict(schema_version='operating-measurement-projection-v1',claim='DERIVED_MEASUREMENTS_NOT_ORIGINAL_RECORD_BYTES',
        run_id=run,run_attempt=1,sample=sample_number,source=source,status='INCOMPLETE',resources='UNKNOWN',checks={},original_records={})
    try:
        base=Path('/var/tmp')/('nfl-operating-'+str(run)+'-'+str(sample_number))
        measured,resource_identity=_protected_report(base/'RESOURCE.json')
        outer,outer_identity=_protected_report(base/'OUTER_EXECUTION_BINDING.json')
        record['original_records']={'resource':resource_identity,'outer_execution':outer_identity}
        actual=_source_ci_cli(code,'fingerprint')
        if os.environ.get('OPERATING_MODE')=='capability':
            record.update(_capability_projection(measured,outer,actual,run,sample_number));return record
        report_raw=_bounded_file(result,JSON_LIMIT);report=_decoded(report_raw)
        record['original_records']['sample']={'sha256':sha(report_raw),'bytes':len(report_raw)}
        _matched_source_ci(report['source_ci'],actual)
        proof_keys={'schema_version','executed_commit','executed_tree','source_manifest_sha256','source_ci_commit',
            'run_id','run_attempt','job_id','seal_sha256','environment_sha256','claim'}
        if (set(report['source_ci'])!=proof_keys
                or any(type(report['source_ci'][k]) is not int or report['source_ci'][k]<1 for k in ('run_id','run_attempt','job_id'))
                or not _hex(report['source_ci']['source_ci_commit'],HEX40)
                or not _hex(report['source_ci']['seal_sha256'],HEX64)):
            raise RuntimeError('Unsupported source-CI projection fields')
        if report.get('status') not in ('FAIL','FINALIZATION_FAILED','LOCAL_BOUNDARY_COMPLETE_EXTERNAL_JOB_TIMESTAMPS_PENDING'):
            raise RuntimeError('Unsupported sample state')
        if report.get('retention',{}).get('status') not in ('FAILED_WORKSPACE_RETAINED_NO_EXPORT','SUCCESS_JOB_COPY_CLEANED_ORIGINAL_SEED_UNCHANGED'):
            raise RuntimeError('Unsupported retention state')
        boundaries=report.get('source_ci_boundaries',{})
        if report['status']=='LOCAL_BOUNDARY_COMPLETE_EXTERNAL_JOB_TIMESTAMPS_PENDING' and (set(boundaries)!={'initial','before_data_commit','after_pages_stage'} or any(v!=report['source_ci'] for v in boundaries.values())):
            raise RuntimeError('Incomplete actual online source-CI boundaries')
        dependencies={name:_hash_file(code/name) for name in DEPENDENCIES}
        if (report.get('source_tree')!=actual['tree'] or report.get('source_manifest_sha256')!=actual['source_manifest_sha256']
                or report.get('environment_sha256')!=sha(encoded(actual['environment'])) or report.get('runtime')!=_runtime_identity(actual['environment'])
                or report.get('dependency_hashes')!=dependencies or report.get('fixture_harness_sha256')!=SEED_HARNESS_SHA256
                or report.get('fixture_construction_source')!=BASE or report.get('seed_manifest_sha256')!=os.environ.get('SEED_MANIFEST_SHA256')):
            raise RuntimeError('Actual runtime/source/seed differs from recorded sample')
        allowed_stages={'resource_capability','transport_allocation_admission','restoration_allocation_admission','seed_retrieval','source_ci_online','source_ci_private_binding','network_isolation',
            'source_ci_isolated_entry','seed_restoration','workload_admission','execution_source_install','execution_saved_packaging','execution_fictional_plan_transition',
            'retained_cheap_checks','capture_and_advisories','source_ci_before_data_commit','local_commit_and_pages_stage',
            'source_ci_after_pages_stage','uploader_tar','source_ci_isolated_final','cleanup'}
        if type(report.get('stages')) is not dict or not set(report['stages'])<=allowed_stages:raise RuntimeError('Unsupported stage projection')
        for stage in report['stages'].values():
            if type(stage) is not dict or set(stage)!={'start','end','seconds'} or any(type(v) not in (int,float) or not 0<=v<86400 for v in stage.values()):raise RuntimeError('Invalid exclusive stage fact')
        if report.get('failure_class') is not None and (type(report['failure_class']) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,80}',report['failure_class'])):
            raise RuntimeError('Unsupported failure class')
        if report.get('source')!=source or report.get('run_id')!=run or report.get('sample')!=sample_number:
            raise RuntimeError('Wrong sample identity')
        source_files={f['path']:{'sha256':f['sha256'],'bytes':f['bytes']} for f in actual['files']}
        if any(source_files.get(k)!=v for k,v in outer.get('source',{}).get('files',{}).items()):
            raise RuntimeError('Root source closure differs from actual installed source')
        bound=_resource_binding(measured,outer,report,run,sample_number,source)
        from diagnostic_resources import report_verdict
        facts=_measurements(measured);verdict=report_verdict(facts) if bound else 'UNKNOWN'
        final_workload=None
        dataflow_path=root.parent/'dataflow.json'
        if dataflow_path.exists():
            dataflow=_load(dataflow_path)
            if dataflow.get('final_candidate_workload') is not None:
                final_workload=_check_final_workload(dataflow['final_candidate_workload'],source,actual['tree'],require_admitted=False)
        aggregate=_evidence_aggregates(root.parent) if report['status']=='LOCAL_BOUNDARY_COMPLETE_EXTERNAL_JOB_TIMESTAMPS_PENDING' else None
        if aggregate is not None:_check_evidence_projection(aggregate,source,actual['tree'])
        record.update(status=report['status'],resources=verdict,resource_measurements=facts,
            workload_evidence=aggregate,final_candidate_workload=_public_final_workload(final_workload) if aggregate is None and final_workload is not None else None,source_tree=report['source_tree'],source_manifest_sha256=report['source_manifest_sha256'],source_ci=report['source_ci'],
            source_ci_boundary_count=len(boundaries),wrapper_sha256=report['harness_sha256'],fixture_harness_sha256=report['fixture_harness_sha256'],
            fixture_construction_source=report['fixture_construction_source'],seed_manifest_sha256=report['seed_manifest_sha256'],
            dependency_hashes=report['dependency_hashes'],runtime=report['runtime'],environment_sha256=report['environment_sha256'],
            stages=report['stages'],harness_wall_seconds=report['harness_wall_seconds'],failure_class=report['failure_class'],
            retention_status=report.get('retention',{}).get('status'),
            checks=dict(fresh_source_ci_binding=True,root_record_source_bytes=True,root_execution_and_resource_binding=bound,
                protected_original_records=True,resource_measurements_recomputed=True))
        if len(encoded(record))>64*1024:raise RuntimeError('Closed projection exceeds its bound')
    except BaseException as error:
        record={k:v for k,v in record.items() if k in ('schema_version','claim','run_id','run_attempt','sample','source','original_records')}
        record.update(status='PROJECTION_INCOMPLETE',resources='UNKNOWN',failure_class=type(error).__name__,checks={})
    return record


def assess(metadata,result,*,api=None):
    """Fresh authenticated run/jobs/log retrieval; no caller-provided PASS file."""
    import math
    import source_ci
    approval=_load(metadata)
    required={'schema_version','campaign','repository','repository_id','run_id','head_sha','workflow_id','workflow_path',
        'actor_id','attempt','seed_manifest_sha256','wrapper_sha256','dependency_hashes','source_manifest_sha256',
        'source_ci_identity','runtime_environment_sha256'}
    sealed=approval.get('source_ci_identity')
    if (type(sealed) is not dict or set(sealed)!={'run_id','run_attempt','job_id','seal_sha256','environment_sha256'}
            or any(type(sealed[k]) is not int or sealed[k]<1 for k in ('run_id','run_attempt','job_id'))
            or any(not _hex(sealed[k],HEX64) for k in ('seal_sha256','environment_sha256'))):
        raise RuntimeError('Complete approved source-CI seal identity required')
    if (set(approval)!=required or approval['schema_version']!='operating-campaign-approval-v1'
            or approval['campaign']!=CAMPAIGN or approval['repository']!=source_ci.REPOSITORY
            or approval['repository_id']!=source_ci.REPOSITORY_ID or approval['workflow_path']!=CAMPAIGN_WORKFLOW
            or approval['actor_id']!=208912933 or type(approval['run_id']) is not int or approval['run_id']<1
            or type(approval['workflow_id']) is not int or approval['workflow_id']<1 or approval['attempt']!=1
            or not _hex(approval['head_sha'],HEX40)):
        raise RuntimeError('Exact populated invocation approval required')
    api=api or source_ci.GitHub();route='/actions/runs/'+str(approval['run_id'])
    run=api.get(route);attempt=api.get(route+'/attempts/1')
    fixed={'id':approval['run_id'],'head_sha':approval['head_sha'],'workflow_id':approval['workflow_id'],
        'path':CAMPAIGN_WORKFLOW,'event':'workflow_dispatch','run_attempt':1,'status':'completed',
        'head_branch':'upgrade/phase2-reproducible-comparison'}
    if (any(run.get(k)!=v for k,v in fixed.items()) or any(attempt.get(k)!=v for k,v in fixed.items())
            or run.get('actor',{}).get('id')!=approval['actor_id']
            or run.get('repository',{}).get('id')!=approval['repository_id']):
        raise RuntimeError('Actual completed campaign identity differs from approval')
    inventory=api.get(route+'/attempts/1/jobs?per_page=100')
    if type(inventory.get('jobs')) is not list or inventory.get('total_count')!=3 or len(inventory['jobs'])!=3:
        raise RuntimeError('Exactly three complete job records required')
    def instant(value):
        at=datetime.fromisoformat(value.replace('Z','+00:00'))
        if at.tzinfo is None:raise RuntimeError('Timezone required')
        return at
    def number(value):
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise RuntimeError('Invalid numeric measurement')
        return value
    samples=[];intervals=[];seen=set()
    stages={'resource_capability','transport_allocation_admission','restoration_allocation_admission','seed_retrieval','source_ci_online','source_ci_private_binding','network_isolation',
        'source_ci_isolated_entry','seed_restoration','workload_admission','execution_source_install',
        'execution_saved_packaging','execution_fictional_plan_transition','retained_cheap_checks','capture_and_advisories','source_ci_before_data_commit','local_commit_and_pages_stage',
            'source_ci_after_pages_stage','uploader_tar','source_ci_isolated_final','cleanup'}
    for job in inventory['jobs']:
        match=re.fullmatch(r'Operating sample ([123])',job.get('name',''))
        if not match or job.get('status')!='completed' or job.get('run_id')!=run['id'] or job.get('head_sha')!=run['head_sha']:
            raise RuntimeError('Actual job identity mismatch')
        n=int(match[1])
        if n in seen:raise RuntimeError('Duplicate actual sample')
        seen.add(n)
        try:
            a=instant(job['started_at']);b=instant(job['completed_at'])
            if b<a:raise RuntimeError('Negative whole-job interval')
            intervals.append((a,b,n))
        except Exception as error:
            samples.append(dict(sample=n,job_id=job['id'],conclusion=job['conclusion'],complete_harness=False,
                planning='FAIL',resources='UNKNOWN',failure_class=type(error).__name__,failure='JOB_TIMESTAMPS_UNAVAILABLE'))
            continue
        raw=None
        try:
            raw=api.get('/actions/jobs/'+str(job['id'])+'/logs',logs=True);records=[]
            for line in raw.decode('utf-8-sig').splitlines():
                line=re.sub(r'^\d{4}-\d\d-\d\dT[0-9:.]+Z\s+','',line)
                if line.startswith('NFL_OPERATING_MEASUREMENT '):
                    records.append(_decoded(line[len('NFL_OPERATING_MEASUREMENT '):].encode(),64*1024))
            if len(records)>1:raise RuntimeError('Duplicate authenticated measurement records')
            if not records:
                samples.append(dict(sample=n,job_id=job['id'],conclusion=job['conclusion'],
                    complete_harness=False,planning='FAIL',resources='UNKNOWN',failure='MEASUREMENT_RECORD_MISSING',
                    whole_job_seconds=(b-a).total_seconds(),authenticated_log_sha256=sha(raw)))
                continue
            projection=records[0]
            if (type(projection) is not dict or projection.get('schema_version')!='operating-measurement-projection-v1'
                    or projection.get('claim')!='DERIVED_MEASUREMENTS_NOT_ORIGINAL_RECORD_BYTES'
                    or projection.get('run_id')!=run['id'] or projection.get('run_attempt')!=1
                    or projection.get('source')!=run['head_sha'] or projection.get('sample')!=n):
                raise RuntimeError('Authenticated projection identity mismatch')
            wall=(b-a).total_seconds()
            complete=projection.get('status')=='LOCAL_BOUNDARY_COMPLETE_EXTERNAL_JOB_TIMESTAMPS_PENDING'
            bound=False;elapsed=0.;summed=0.;resources='UNKNOWN';applicability='UNKNOWN_ADDITIONAL_MATCHED_REAL_CASE_REQUIRED';applicability_deficiencies=[]
            if complete:
                proof=projection['source_ci'];sealed=approval['source_ci_identity']
                if (type(sealed) is not dict or any(proof.get(k)!=v for k,v in sealed.items())
                        or projection.get('environment_sha256')!=approval['runtime_environment_sha256']
                        or projection.get('seed_manifest_sha256')!=approval['seed_manifest_sha256']
                        or projection.get('wrapper_sha256')!=approval['wrapper_sha256']
                        or projection.get('dependency_hashes')!=approval['dependency_hashes']
                        or projection.get('source_manifest_sha256')!=approval['source_manifest_sha256']
                        or proof.get('schema_version')!='source-ci-verification-v1'
                        or proof.get('executed_tree')!=projection.get('source_tree')
                        or proof.get('source_manifest_sha256')!=projection.get('source_manifest_sha256')
                        or projection.get('source_ci_boundary_count')!=3
                        or projection.get('fixture_harness_sha256')!=SEED_HARNESS_SHA256
                        or projection.get('fixture_construction_source')!=BASE
                        or proof.get('executed_commit')!=run['head_sha']
                        or proof.get('claim')!='COMPLETE_SOURCE_CHECKS_ONLY_NOT_GENERATION_OR_OPERATING_QUALIFICATION'):
                    raise RuntimeError('Measured source/runtime differs from approved campaign')
                evidence=projection.get('workload_evidence')
                _check_evidence_projection(evidence,run['head_sha'],projection['source_tree'])
                final=evidence['final_candidate_workload'];matched=_final_applicability(final)
                applicability=matched['status'];applicability_deficiencies=[{'dimension':name,**matched['comparisons'][name]} for name in matched['deficiencies']]
                checks=projection['checks'];bound=set(checks)=={'fresh_source_ci_binding','root_record_source_bytes',
                    'root_execution_and_resource_binding','protected_original_records','resource_measurements_recomputed'} and all(v is True for v in checks.values())
                elapsed=number(projection['harness_wall_seconds']);last=0.
                if set(projection['stages'])!=stages:raise RuntimeError('Missing complete measured stage')
                for value in sorted(projection['stages'].values(),key=lambda x:x['start']):
                    start,end,seconds=(number(value[k]) for k in ('start','end','seconds'))
                    if start<last or end<start or end>elapsed or abs(end-start-seconds)>.001:raise RuntimeError('Nonexclusive measured stage')
                    last=end;summed+=seconds
                if elapsed>wall+2:raise RuntimeError('Harness exceeds actual whole-job interval')
                from diagnostic_resources import report_verdict
                resources=report_verdict(projection['resource_measurements']) if bound else 'UNKNOWN'
            samples.append(dict(sample=n,job_id=job['id'],conclusion=job['conclusion'],complete_harness=complete,
                whole_job_seconds=wall,conservative_upper_seconds=wall+2,
                planning='PASS' if complete and bound and job['conclusion']=='success' and wall+2<=960 else 'FAIL',
                resources=resources,applicability=applicability,applicability_deficiencies=applicability_deficiencies,accounted_harness_seconds=elapsed,exclusive_stage_seconds=summed,
                unassigned_inside_harness_seconds=elapsed-summed,outside_harness_residual_seconds=wall-elapsed,
                projection_sha256=sha(encoded(projection)),authenticated_log_sha256=sha(raw)))
        except Exception as error:
            samples.append(dict(sample=n,job_id=job['id'],conclusion=job['conclusion'],complete_harness=False,
                whole_job_seconds=(b-a).total_seconds(),planning='FAIL',resources='UNKNOWN',
                failure_class=type(error).__name__,failure='MEASUREMENT_UNAVAILABLE_OR_INVALID',
                authenticated_log_sha256=sha(raw) if type(raw) is bytes else None))
    intervals.sort()
    serial=[n for _,_,n in intervals]==[1,2,3] and all(intervals[i][0]>=intervals[i-1][1] for i in (1,2))
    final_identity=True;final_identity_failure=None
    try:
        if api.get(route)!=run or api.get(route+'/attempts/1/jobs?per_page=100')!=inventory:
            raise RuntimeError('Campaign identity changed during assessment')
    except Exception as error:final_identity=False;final_identity_failure=type(error).__name__
    value=dict(schema_version='operating-campaign-assessment-v2',source=run['head_sha'],run_id=run['id'],
        samples=sorted(samples,key=lambda x:x['sample']),queue_seconds=(instant(run['run_started_at'])-instant(run['created_at'])).total_seconds(),
        final_api_identity_rechecked=final_identity,final_identity_failure_class=final_identity_failure,
        fixed_cold_serial_order=serial,operating='PASS_FICTIONAL_COMPUTE_ONLY' if final_identity and serial and run['conclusion']=='success' and all(x['planning']=='PASS' and x['resources']=='PASS' and x.get('applicability')=='CONSERVATIVE_REFERENCE_ENVELOPE_COVERED' for x in samples) else 'NOT_QUALIFIED',
        evidence='AUTHENTICATED_GITHUB_JOB_LOG_DERIVED_MEASUREMENTS_AND_POST_COMPLETION_JOB_TIMESTAMPS',
        excludes=['production_configuration','live_providers','remote_write','artifact_upload','Pages','public_cache','season_long_operation'])
    put(result,value);return value


def cheap_checks(code):
    """Exact Phase 2 cheap checks retained by hourly.yml; full suite stays in CI."""
    require_offline()
    for command in ([sys.executable,'-m','compileall','-q','pull','tools'],
            ['node','--check','output/app.js'],['node','--check','output/reliability-ui.js'],
            ['node','tests/test-ui.cjs'],['node','tests/test-about.cjs']):
        subprocess.run(command,cwd=code,check=True)


def _sample_context(root):
    m=bind(root);marker=_load(root/'FICTIONAL_ONLY.json')
    if marker['notice']!=NOTICE:raise RuntimeError('Not the reviewed fictional fixture')
    provider=Provider(m,marker['dimensions'],START+timedelta(hours=SEED_HOUR,seconds=seed_v1.SAMPLE_SECONDS))
    provider.revision=seed_v1.NEXT_REVISION
    return m,provider


def _advisory_script(path,args,clock):
    spec=importlib.util.spec_from_file_location('diagnostic_advisory_'+path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with patch.object(sys,'argv',[str(path),*args]):
        if hasattr(module,'datetime'):
            with patch.object(module,'datetime',clock):module.main()
        else:module.main()
    return module


def _advisories(root,m,provider):
    """Execute actual advisory scripts; unavailable remote continuations stay so."""
    import requests
    outcomes={};unavailable=0
    def denied(*a,**kw):
        nonlocal unavailable
        unavailable+=1
        raise RuntimeError('No supported fictional raw-HTTP advisory observation')
    for name,args in (('legacy_verifier',[]),('historical_comparison',['--json','output/data/dk_backtest.json'])):
        script='verify.py' if name=='legacy_verifier' else 'compare_lines.py'
        tick=time.monotonic();exit_code=0;failure=None
        with patch.object(requests.sessions.Session,'request',denied):
            try:_advisory_script(root/'tools'/script,args,m['capture'].datetime)
            except SystemExit as error:exit_code=error.code if type(error.code) is int else 1
            except Exception as error:exit_code=1;failure=type(error).__name__
        outcomes[name]=dict(outcome='success' if exit_code==0 else 'failure',returncode=exit_code,
            failure_class=failure,seconds=time.monotonic()-tick)
    health=_load(root/'output/data/health.json')
    health.update({name:value['outcome'] for name,value in outcomes.items()});put(root/'output/data/health.json',health)
    return dict(outcomes=outcomes,unsupported_raw_http_calls=unavailable,
        remote_continuation='UNMEASURED' if unavailable else 'NOT_REQUESTED',live_provider_requests=0)


def _weekly_display(root,m):
    """Actual writer and graph validation; no matching lab feed is fabricated.

    The fixture's missing remote feed is an explicit HTTP-404 source mock. The
    real policy/source checks must reach that lookup before the result counts
    as coverage. This only exercises current-reference fallback, not accepted
    selected-feed qualification. No original or corrected forecast is changed.
    """
    from urllib.error import HTTPError
    from urllib.request import OpenerDirector
    path=root/WEEKLY_POLICY
    raw=_bounded_file(path,1<<20)
    if sha(raw)!=WEEKLY_POLICY_SHA256:raise RuntimeError('Registered weekly policy changed')
    source=git(root,'rev-parse','HEAD')
    if not _hex(source,HEX40):raise RuntimeError('Actual derived execution HEAD required')
    board_before=_bounded_file(root/'output/data/week.json',SOURCE_FILE_LIMIT)
    ranker=_weekly_ranker(root)
    fixture_clock=m['capture'].datetime
    missing=0
    def absent(_opener,request,*args,**kwargs):
        nonlocal missing
        missing+=1
        # No response from another population may be borrowed for this fixture.
        raise HTTPError(request.full_url,404,'No fictional lab publication',{},None)
    with patch.object(OpenerDirector,'open',new=absent),patch.dict(sys.modules,{'weekly_selected_rankings':ranker}),patch.object(ranker,'datetime',fixture_clock):
        module=_advisory_script(root/'tools/weekly_adaptive_overlay.py',
            ['--root',str(root),'--website-source-sha',source,'--feed-policy',WEEKLY_POLICY,
             '--feed-policy-sha256',WEEKLY_POLICY_SHA256],m['capture'].datetime)
    module.validate_public_root(root/'output')
    pointer,doc=module.read_public(root/'output')
    ranking_pointer,ranking=ranker.read_public(root/'output/data')
    expected_clock=fixture_clock.now(timezone.utc).isoformat()
    if (_bounded_file(root/'output/data/week.json',SOURCE_FILE_LIMIT)!=board_before
            or doc['website_source_sha']!=source or pointer['display_board_sha256']!=sha(board_before)):
        raise RuntimeError('Weekly display changed its reference board/source binding')
    if missing!=1 or doc['rows'] or doc['state']!='DISABLED_USE_R0':
        raise RuntimeError('Fictional weekly missing-feed branch was not exercised')
    if (ranking['website_source_sha']!=source or ranking['display_board_sha256']!=sha(board_before)
            or ranking['overlay_sha256']!=pointer['sha256']
            or ranking['prepared_at']!=expected_clock or ranking_pointer['published_at']!=expected_clock):
        raise RuntimeError('Fictional ranking source/board or preparation/completion clock changed')
    ranking_rows=[item for side in ranking['picks'].values() for item in side]
    if any(item['forecast_source']!='R0_FALLBACK' for item in ranking_rows):
        raise RuntimeError('Missing fictional selected feed acquired selected ranking evidence')
    return dict(state=doc['state'],selected_rows=len(doc['rows']),website_source_sha=source,
        policy_file_sha256=WEEKLY_POLICY_SHA256,overlay_sha256=pointer['sha256'],
        mocked_missing_feed_requests=missing,provider_requests=0,
        coverage='ACTUAL_REGISTERED_WRITER_AND_GRAPH_CURRENT_REFERENCE_FALLBACK_ONLY',
        accepted_selected_feed='NOT_EXERCISED_NO_MATCHING_FICTIONAL_LAB_PUBLICATION',
        rankings=dict(body_sha256=ranking_pointer['sha256'],schema_version=ranking['schema_version'],
            prepared_at=ranking['prepared_at'],published_at=ranking_pointer['published_at'],
            picks={side:len(items) for side,items in ranking['picks'].items()},frozen_proofs=len(ranking['frozen_proofs']),
            source_counts={'R0_FALLBACK':len(ranking_rows),'SELECTED':0},
            accuracy_or_registered_reference_strategy_claim=False))


def _weekly_ranker(root):
    """Load only actual copied source bytes, preserving the execution association."""
    name='tools/weekly_selected_rankings.py'
    return _weekly_source_module(root,name,_source_marker(root)['files'].get(name,{}))


def _weekly_source_module(root,name,descriptor):
    import types
    if name not in ('tools/weekly_selected_rankings.py','tools/weekly_public_feed.py'):
        raise RuntimeError('Unsupported weekly execution module')
    path=root/name
    body=_bounded_file(path,SOURCE_FILE_LIMIT)
    if (descriptor.get('path')!=name or descriptor.get('mode')!='100644'
            or descriptor.get('bytes')!=len(body) or descriptor.get('sha256')!=sha(body)):
        raise RuntimeError('Derived ranking source changed before execution')
    module=types.ModuleType(Path(name).stem);module.__file__=str(path)
    exec(compile(body,str(path),'exec'),module.__dict__)
    return module


def _install_weekly_registrations(code,root,fingerprint):
    """Transport only the closed eight actual public policy Git objects.

    The normal candidate-source fetch still retains its full parent/source
    closure. This typed transport also makes the two immutable registrations
    available before any source-qualified optional writer can run.
    """
    name='tools/weekly_public_feed.py'
    descriptor=next((item for item in fingerprint['files'] if item['path']==name),{})
    module=_weekly_source_module(code,name,descriptor)
    original=module.registration_objects(code)
    if not isinstance(original,dict) or not 0<len(original)<=8:
        raise RuntimeError('Closed public registration object set required')
    for oid,item in original.items():
        if (not _hex(oid,HEX40) or set(item)!={'type','body'} or item['type'] not in ('commit','tree','blob')
                or type(item['body']) is not bytes or len(item['body'])>1<<20
                or hashlib.sha1(item['type'].encode()+b' '+str(len(item['body'])).encode()+b'\0'+item['body']).hexdigest()!=oid):
            raise RuntimeError('Public registration Git object changed')
        result=subprocess.run(['git','--no-replace-objects','-c','core.hooksPath=/dev/null','-C',str(root),
            'hash-object','-t',item['type'],'-w','--stdin'],input=item['body'],capture_output=True,check=True,timeout=15)
        if result.stdout.decode().strip()!=oid:raise RuntimeError('Public registration Git write identity changed')
    if module.registration_objects(root)!=original:
        raise RuntimeError('Destination public registration closure differs')


def sample_capture(code,root,result):
    """P5 capture/preservation sequence, stopped at the real pre-commit gate."""
    require_offline();identity=execution_identity(code,root)
    if identity.get('schema_version')!='diagnostic-execution-source-v3' or identity.get('phase2_transition') is None:
        raise RuntimeError('Completed fictional source/plan transition required before connected update')
    m,provider=_sample_context(root)
    r=dict(notice=NOTICE,stages={},status='CAPTURE_RUNNING')
    def step(name,action):
        tick=time.monotonic()
        try:return action()
        finally:r['stages'][name]=time.monotonic()-tick;put(result,r)
    with external(m,provider,root),patch.object(m['capture'],'_public_archive_commit',side_effect=lambda ref,tree:assert_local_tree(root,ref,tree)):
        declaration,old_rows,old_outcomes=seed_v1.correction_declaration(root,m)
        before_board=m['rel'].load_json(root/'output/data/week.json')
        contracts={g['id']:m['partial'].game_contract(before_board,g['id']) for g in before_board['games']}
        put(result.parent/'MATERIAL_CORRECTION.predeclared.json',declaration)
        before={p.relative_to(root).as_posix():_hash_file(p,SEED_BYTES_LIMIT)
            for lane in ('forward','offers','outcomes','verification') for p in (root/'data'/lane).rglob('*') if p.is_file()}
        step('preserve_existing_grading',lambda:subprocess.run([sys.executable,str(root/'tools/preserve_legacy.py')],cwd=root,check=True))
        step('recorded_build_capture_report',lambda:m['capture'].run_capture(root,build_first=True))
        step('explicit_generation_validation',lambda:m['capture'].validate_generation(root))
        r['material_correction']=seed_v1.check_correction(root,m,declaration,old_rows,old_outcomes)
        board=m['rel'].load_json(root/'output/data/week.json')
        if contracts!={g['id']:m['partial'].game_contract(board,g['id']) for g in board['games']}:raise RuntimeError('Outcome correction altered frozen contracts')
        if any(not (root/name).is_file() or _hash_file(root/name,SEED_BYTES_LIMIT)!=digest for name,digest in before.items()):raise RuntimeError('Prior original evidence changed')
        r['advisories']=step('actual_advisory_scripts_and_health',lambda:_advisories(root,m,provider))
        r['weekly_display']=step('actual_weekly_display_writer_and_graph',lambda:_weekly_display(root,m))
    execution_identity(code,root)
    r.update(status='CAPTURE_COMPLETE_PRECOMMIT_CI_PENDING',fake_http_responses=provider.calls,provider_requests=0)
    put(result,r)


def sample_commit(code,root,result):
    require_offline();execution_identity(code,root);m,provider=_sample_context(root);r=_load(result)
    if r.get('status')!='CAPTURE_COMPLETE_PRECOMMIT_CI_PENDING':raise RuntimeError('Wrong split-update frontier')
    with external(m,provider,root),patch.object(m['capture'],'_public_archive_commit',side_effect=lambda ref,tree:assert_local_tree(root,ref,tree)):
        tick=time.monotonic();commit(root);r['stages']['local_git_commit']=time.monotonic()-tick
        tick=time.monotonic();m['capture'].stage_pages(root,root.parent/'sample-pages');r['stages']['pages_staging_archive_checks']=time.monotonic()-tick
        # This inventory is diagnostic-only; actual capture/validation/staging
        # above retain the production functions and their native cache lifetimes.
        tick=time.monotonic()
        with operation_lifetime(seed_v1, modules=(m,)):
            r['final_candidate_workload']=final_candidate_workload(code,root,m,root.parent/'sample-pages')
        r['stages']['final_candidate_metrics']=time.monotonic()-tick
        if not r['final_candidate_workload']['decisions']['admitted']:r['status']='FINAL_CANDIDATE_WORKLOAD_NOT_ADMITTED'
        put(result,r)
        _check_final_workload(r['final_candidate_workload'],require_admitted=True)
    execution_identity(code,root);r['status']='PAGES_STAGED_FINAL_CI_PENDING';put(result,r)


def sample_tar(code,root,result):
    require_offline();execution_identity(code,root);r=_load(result)
    if r.get('status')!='PAGES_STAGED_FINAL_CI_PENDING':raise RuntimeError('Wrong split-update frontier')
    tick=time.monotonic()
    subprocess.run(['tar','--dereference','--hard-dereference','--directory',str(root.parent/'sample-pages'),'-cf',
        str(root.parent/'sample-artifact.tar'),'--exclude=.git','--exclude=.github','.'],check=True)
    r['stages']['uploader_tar']=time.monotonic()-tick;r['status']='PASS_DATAFLOW_ONLY_NOT_WHOLE_JOB'
    put(result,r);execution_identity(code,root)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('job','critical','project','restore','admit','install-source','package-source','transition-plan','checks','capture-stage','commit-stage','tar-stage','assess'))
    p.add_argument('--code',type=Path,required=True);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--result',type=Path);p.add_argument('--sample-number',type=int);p.add_argument('--metadata',type=Path)
    a=p.parse_args();code=a.code.resolve();root=a.root.resolve()
    if a.action=='project':print(encoded(project(code,root,a.result,a.sample_number)).decode())
    elif a.action=='critical':print(json.dumps(_critical_paths(code,root,a.result)))
    elif a.action=='job':launch_job(code,root,a.result,a.sample_number)
    elif a.action=='restore':seed_v1.restore_seed(code,root)
    elif a.action=='admit':
        # Source construction remains the actual frozen fixture, not candidate.
        with operation_lifetime(seed_v1):
            if seed_v1.admit(root,root,a.result,small=False)['status']!='ADMITTED':raise SystemExit(3)
    elif a.action=='install-source':install_execution_source(code,root)
    elif a.action=='package-source':package_execution_source(code,root)
    elif a.action=='transition-plan':transition_execution_plan(code,root)
    elif a.action=='checks':cheap_checks(code)
    elif a.action=='capture-stage':sample_capture(code,root,a.result)
    elif a.action=='commit-stage':sample_commit(code,root,a.result)
    elif a.action=='tar-stage':sample_tar(code,root,a.result)
    else:assess(a.metadata,a.result)

if __name__=='__main__':main()
