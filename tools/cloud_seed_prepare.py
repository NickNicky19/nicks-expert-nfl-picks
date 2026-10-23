"""PROPOSED ONLY: bounded one-time seed preparation; never an operating PASS.

The existing fixture, validators, freezer and replay remain unchanged. Raw logs
stay in the run-specific work directory. Only finalize's exact allowlist may be
proposed for a separately approved Actions artifact upload.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import importlib.util
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
sys.dont_write_bytecode=True

BASE='b3de2fbd88ba3247b407a856972285ad10527b99'
TREE='c0d0d818f8e1266f55851c8c220d44cd94797c78'
LEGACY='bf3ec09129e918b73641a65af5f05ecd5559139a'
LEGACY_TREE='a7fa1863483d38fbda3eac4f6edbdbe26acfaccf'
HARNESS='441f0ccaa1b274708419643d993896b5ff6f2c4118e0016719c80a1746289328'
INPUTS='56c10c8c7e26a4ffd18c5838115c587f7bce7930a6bd078e49527dc2f0bc1cad'
GIB=1024**3
OUTPUT_CAP=2*GIB
CORE_SECONDS=15000
TOTAL_SECONDS=17700  # Leave 300 seconds inside the resource-supervisor bound for final accounting.
REQUIRED={'cloud_seed_prepare.py','cloud_seed_resource_bootstrap.py','diagnostic_resources.py',
    'operating_diagnostic.py','diagnostic_seed.py','diagnostic_network_guard.py',
    'coverage_gate.py','diagnostic-seed-inputs.json','cloud-seed-requirements.txt',
    'seed_checkpoint_frontier.py','source_ci.py','operating_seed_transport.py'}
CONTINUATION_ID='NFL-WEB-CONTINUE-VERIFIED-13-OF-24-12509203616-20261023'
PREFIX_HEAD='bea7faaed74c3975b9bd746882a5718cc614ff2f'
PREFIX_GENERATION='c9950828aefabea60c80ac691753988ba927718843e7042ba89c9e1e0f6df8c0'
PREFIX_SEMANTICS='02bbf427657c68669482c96b56e79e40cbc270b784286c4b825a84345e6b2c48'
SEED_FILES=('working.tar.gz','fictional.pack','public-source.pack','SEED_MANIFEST.json')
PUBLIC_FILES=set(SEED_FILES)|{'ADMISSION.json','COVERAGE.json','RESTORATION.json',
    'PREPARATION_RESULT.json','PREFLIGHT.json','RESOURCE.json','CAPABILITY.json',
    'ANCESTORS.before.json','ANCESTORS.after.json',
    'INCOMPLETE_CHECKPOINT.tar.gz','INCOMPLETE_SOURCE_CLOSURE.bundle','INCOMPLETE_MANIFEST.json','ARTIFACT_MANIFEST.json'}

def now():return datetime.now(timezone.utc).isoformat()
def rawhash(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for value in iter(lambda:stream.read(1024**2),b''):h.update(value)
    return h.hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.writing')
    tmp.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')
    tmp.replace(path)
def load(path,limit=16*1024**2):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:raise RuntimeError('Bounded regular JSON required: '+path.name)
    return json.loads(path.read_bytes())
def git(app,*args):
    return subprocess.check_output(['git','-C',str(app),*args],stderr=subprocess.PIPE,text=True).strip()
def actual(path):
    while not path.exists():path=path.parent
    return path
def filesystem(path):
    p=actual(path);s=os.statvfs(p)
    # findmnt resolves the effective mount; a different pathname is not capacity.
    fstype=subprocess.check_output(['findmnt','-n','-o','FSTYPE','--target',str(p)],text=True).strip()
    if fstype in ('tmpfs','ramfs','devtmpfs'):raise RuntimeError('Memory-backed critical filesystem: '+str(path))
    capacity=s.f_blocks*s.f_frsize;free=s.f_bavail*s.f_frsize
    return dict(path=str(path),device=p.stat().st_dev,fstype=fstype,capacity_bytes=capacity,
        free_bytes=free,reserve_bytes=max(2*GIB,capacity//5),additional_peak_estimate_bytes=0)
def integrity(path):
    m=load(path);here=Path(__file__).resolve().parent
    if m.get('schema_version')!='cloud-seed-code-integrity-v1' or not isinstance(m.get('files'),dict) or set(m['files'])!=REQUIRED:
        raise RuntimeError('Incomplete code dependency manifest')
    for name,expected in m['files'].items():
        p=here/name
        if Path(name).name!=name or p.is_symlink() or not p.is_file() or rawhash(p)!=expected:
            raise RuntimeError('Code dependency identity mismatch: '+name)
    if m['files']['operating_diagnostic.py']!=HARNESS or m['files']['diagnostic-seed-inputs.json']!=INPUTS:
        raise RuntimeError('Frozen diagnostic lineage changed')
    return rawhash(path)
def installed(args,expected=None):
    """Actual immutable installer objects, separate from application B3."""
    root=Path(__file__).resolve().parent.parent
    identity=dict(head=git(root,'rev-parse','HEAD'),tree=git(root,'rev-parse','HEAD^{tree}'))
    if expected is not None:
        if identity!={k:expected[k] for k in ('head','tree')}:raise RuntimeError('Installer checkout changed after preflight')
    elif os.environ.get('GITHUB_SHA')!=identity['head']:raise RuntimeError('Installer differs from actual workflow source')
    if args.integrity.resolve()!=root/'tools/cloud-seed-integrity.json':raise RuntimeError('Installed integrity path must be source-bound')
    for name in sorted(REQUIRED|{'cloud-seed-integrity.json'}):
        path=root/'tools'/name
        if git(root,'hash-object','--no-filters',str(path))!=git(root,'rev-parse',identity['head']+':tools/'+name):raise RuntimeError('Installer object differs: '+name)
    return identity
def runtime_versions():
    names=('requests','urllib3','certifi','charset-normalizer','idna')
    declared=dict(line.split('==',1) for line in Path(__file__).with_name('cloud-seed-requirements.txt').read_text().splitlines() if line)
    packages={name:importlib.metadata.version(name) for name in names}
    if packages!=declared:raise RuntimeError('Installed dependencies differ from declared pins')
    try:systemd=subprocess.check_output(['systemd','--version'],text=True,timeout=5).splitlines()[0]
    except (OSError,subprocess.SubprocessError):systemd=None
    return dict(python=sys.version,python_executable=str(Path(sys.executable).resolve()),
        node=subprocess.check_output(['node','--version'],text=True,timeout=5).strip(),
        packages=packages,declared_packages=declared,kernel=platform.release(),systemd=systemd,
        image={k:os.environ.get(k) for k in ('ImageOS','ImageVersion','RUNNER_OS','RUNNER_ARCH')})
def paths(args):
    a,w,o=(Path(getattr(args,k)).resolve() for k in ('app','work','output'))
    if any(x==y or x in y.parents or y in x.parents for i,x in enumerate((a,w,o)) for y in (a,w,o)[i+1:]):
        raise RuntimeError('Application, work and export roots must be independent')
    return a,w,o

def continuation_path(args):
    """A distinct, exact invocation; never a restart of the consumed first run."""
    if not getattr(args,'continue_checkpoint',False):return None
    expected={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted',
        'GITHUB_REPOSITORY_ID':'1411185749','GITHUB_ACTOR_ID':'208912933',
        'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1',
        'GITHUB_REF':'refs/heads/upgrade/phase2-reproducible-comparison',
        'CONTINUATION_ID':CONTINUATION_ID}
    if any(os.environ.get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Exact first-attempt continuation invocation required')
    run=os.environ.get('GITHUB_RUN_ID','')
    if not run.isascii() or not run.isdigit() or int(run)<=0 or str(int(run))!=run:
        raise RuntimeError('Actual continuation run identity required')
    path=Path(os.environ['RUNNER_TEMP']).resolve()/('nfl-seed-frontier-'+run)
    if path.is_symlink() or path.parent!=path.parent.resolve():
        raise RuntimeError('Independent run-specific checkpoint path required')
    return path

def retrieve_continuation(args):
    """Online read-only setup only; the resource-isolated worker has no token."""
    import seed_checkpoint_frontier as frontier
    import source_ci
    path=continuation_path(args)
    if path is None:raise RuntimeError('Explicit continuation flag required')
    integrity(args.integrity);identity=installed(args)
    api=source_ci.GitHub();run_id=int(os.environ['GITHUB_RUN_ID'])
    current=api.get('/actions/runs/'+str(run_id))
    if (type(current.get('run_attempt')) is not int or current.get('status')!='in_progress' or
        (current.get('id'),current.get('head_sha'),current.get('run_attempt'),
        current.get('event'),current.get('workflow_id'),(current.get('actor') or {}).get('id')) != (
            run_id,identity['head'],1,'workflow_dispatch',392359637,208912933)):
        raise RuntimeError('Unapproved continuation run/source')
    matches=[]
    for page in range(1,6):
        batch=api.get('/actions/workflows/392359637/runs?event=workflow_dispatch&per_page=100&page='+str(page))
        rows=batch.get('workflow_runs')
        if not isinstance(rows,list):raise RuntimeError('Complete invocation inventory required')
        matches.extend(r for r in rows if r.get('head_sha')==identity['head'])
        if len(rows)<100:break
    else:raise RuntimeError('Invocation inventory bound exceeded')
    if len(matches)!=1 or matches[0].get('id')!=run_id or matches[0].get('run_attempt')!=1:
        raise RuntimeError('Duplicate or ambiguous continuation invocation; no retrieval')
    frontier.hosted(path,'retrieve');frontier.retrieve(path)
    if installed(args)!=identity:raise RuntimeError('Continuation installer changed during retrieval')
    write(path/'CONTINUATION_INVOCATION.json',dict(continuation_id=CONTINUATION_ID,
        run_id=run_id,installer=identity,original_artifact=frontier.ARTIFACT,
        original_artifact_sha256=frontier.DIGEST,mode='RETRIEVED_NOT_CONSTRUCTED'))

def continuation_inventory(root):
    import seed_checkpoint_frontier as frontier
    result=frontier.tree_inventory(root)
    for name in ('FICTIONAL_ONLY.json','FICTIONAL_PHASES.json',
        'FICTIONAL_LEGACY_BASELINE.json','FICTIONAL_PARTICIPATION_ADAPTER.json'):
        result[name]=frontier.descriptor(root/name)
    return result

def continuation_frontier(args):
    """Freshly replay the actual prefix, then make a separately checked copy."""
    import operating_diagnostic as h
    import seed_checkpoint_frontier as frontier
    a,w,o=paths(args);path=continuation_path(args)
    if path is None:raise RuntimeError('Explicit continuation flag required')
    value=frontier.check_saved(path)
    required=dict(status='COMMITTED_HISTORY_REPLAYED_RAW_RESIDUAL_UNQUALIFIED',
        fixture_head=PREFIX_HEAD,recorded_generations=13,independently_replayed_committed_generations=13,
        target_generations=24,generation_sha256=PREFIX_GENERATION,semantic_sha256=PREFIX_SEMANTICS,
        residual_working_files=dict(new=0,changed=0,missing_from_checkpoint=0))
    if any(value.get(k)!=v for k,v in required.items()):
        raise RuntimeError('Only the exact freshly replayed zero-residual prefix is supported')
    source=path/'committed-frontier';root=w/'construction/root'
    if root.exists():raise RuntimeError('Fresh independent continuation root required')
    before=continuation_inventory(source)
    root.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['git','-c','core.hooksPath=/dev/null','clone','--quiet','--no-hardlinks',
        str(source),str(root)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    frontier.git(root,'fetch','--no-tags',str(source),'refs/fixture/source:refs/fixture/source')
    frontier.git(root,'remote','set-url','origin','https://github.com/NickNicky19/nicks-expert-nfl-picks.git')
    frontier.git(root,'fsck','--full','--no-reflogs')
    if ((root/'.git/objects/info/alternates').exists() or git(root,'rev-parse','HEAD')!=PREFIX_HEAD
        or continuation_inventory(root)!=before or continuation_inventory(source)!=before):
        raise RuntimeError('Independent prefix copy differs from actual verified source')
    frontier.verify_parents(path)
    # Preserve the original progress bytes; later completed commits have their
    # own actual continuation wall clocks. No original receipt is rewritten.
    shutil.copyfile(path/'raw-checkpoint/CONSTRUCTION_PROGRESS.json',root.parent/'progress.json')
    write(w/'CONTINUATION_PREFIX.json',before)
    write(w/'CONTINUATION.json',dict(continuation_id=CONTINUATION_ID,run_id=int(os.environ['GITHUB_RUN_ID']),
        original_artifact=frontier.ARTIFACT,original_artifact_sha256=frontier.DIGEST,
        original_fixture_head=PREFIX_HEAD,application_source=BASE,harness_sha256=HARNESS,
        input_contract_sha256=INPUTS,first_remaining_generation=14,target_generations=24,
        freshly_replayed_prefix_generations=13,prefix_inventory_sha256=rawhash(w/'CONTINUATION_PREFIX.json'),
        installer=load(w/'PREFLIGHT.json')['installer'],originals_unchanged=True))

def prefix_immutable(name):
    if name in ('FICTIONAL_ONLY.json','FICTIONAL_PHASES.json',
        'FICTIONAL_LEGACY_BASELINE.json','FICTIONAL_PARTICIPATION_ADAPTER.json'):return True
    if name.startswith(('pull/','tools/','config/','data/forward/','data/verification/',
        'data/offers/','data/outcomes/','data/shadow/','data/history/')):return True
    base='output/data/selection-grading/'
    return name.startswith(base) and name[len(base):] not in ('latest.json','hosting.json')

def continue_generations(root,h):
    """Use the original inner updater loop; do not rerun plan/legacy setup."""
    import seed_checkpoint_frontier as frontier
    dimensions=h.FULL;start=13
    if dimensions!=dict(games=14,per_team=20,snapshots=277,outcomes=49,generations=24):
        raise RuntimeError('Unchanged full continuation dimensions required')
    m=h.bind(root);before=continuation_inventory(root)
    provider=h.Provider(m,dimensions,h.START+h.timedelta(hours=h.SEED_HOUR,seconds=5*start))
    provider.revision=int(start-1>=dimensions['generations']//2);m['_provider']=provider
    board=m['rel'].load_json(root/'output/data/week.json')
    frozen={g['id']:m['rel'].digest(m['partial'].game_contract(board,g['id']))
        for g in board['games'] if g['state']!='pre'}
    with h.external(m,provider,root),h.patch.object(m['capture'],'_public_archive_commit',
            side_effect=lambda ref,tree:h.assert_local_tree(root,ref,tree)):
        # This is a fresh process/root and actual saved validation, not source-
        # root cache trust or the previous job's reported PASS.
        value=m['capture'].validate_generation(root)
        if dimensions==h.FULL and value['generation_sha256']!=PREFIX_GENERATION:
            raise RuntimeError('Copied prefix generation changed')
        for i in range(start,dimensions['generations']):
            provider.at=h.START+h.timedelta(hours=h.SEED_HOUR,seconds=(i+1)*5)
            provider.revision=int(i>=dimensions['generations']//2)
            m['capture'].run_capture(root,build_first=True)
            current=m['rel'].load_json(root/'output/data/week.json')
            if any(m['rel'].digest(m['partial'].game_contract(current,g))!=v for g,v in frozen.items()):
                raise RuntimeError('Continuation changed a frozen contract')
            for name,d in before.items():
                if prefix_immutable(name) and frontier.descriptor(root/name)!=d:
                    raise RuntimeError('Continuation changed prior immutable evidence')
            h.commit(root)
            h.put(root.parent/'progress.json',dict(generation=i+1,target=dimensions['generations'],wall_clock=now()))
    return dict(completed_generations=dimensions['generations'],previous_generations=start,
        added_generations=dimensions['generations']-start,prior_immutable_bytes_preserved=True)

def preflight(args,initialize=True):
    a,w,o=paths(args);digest=integrity(args.integrity);installer=installed(args);runtime=runtime_versions()
    if any(os.environ.get(k) for k in ('GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_OBJECT_DIRECTORY','GIT_DIR','GIT_WORK_TREE')):
        raise RuntimeError('External Git roots are not allowed')
    gd=Path(git(a,'rev-parse','--absolute-git-dir')).resolve()
    if a not in gd.parents or (gd/'objects/info/alternates').exists():raise RuntimeError('Independent checkout without alternates required')
    if git(a,'rev-parse','HEAD')!=BASE or git(a,'rev-parse','HEAD^{tree}')!=TREE or git(a,'status','--porcelain'):
        raise RuntimeError('Exact clean reviewed application checkout required')
    if git(a,'rev-parse',LEGACY+'^{tree}')!=LEGACY_TREE:raise RuntimeError('Retained legacy source closure unavailable')
    subprocess.run(['git','-C',str(a),'fsck','--full','--no-reflogs'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=120)
    source=Path(__file__).resolve().parent;node=shutil.which('node');request=importlib.util.find_spec('requests')
    if node is None or request is None or not request.origin:raise RuntimeError('Installed declared node/requests dependencies required')
    resume=continuation_path(args)
    if resume is not None:
        invocation=load(resume/'CONTINUATION_INVOCATION.json')
        if invocation!={'continuation_id':CONTINUATION_ID,'run_id':int(os.environ['GITHUB_RUN_ID']),
            'installer':installer,'original_artifact':12509203616,
            'original_artifact_sha256':'e9a1be3a3580d01a51b39375d7d908ba37300b02e83ab6ccf2e2732540b9876c',
            'mode':'RETRIEVED_NOT_CONSTRUCTED'}:raise RuntimeError('Actual retrieved invocation differs')
    fs=[filesystem(p) for p in (a,source,w,o,*([resume] if resume is not None else []),Path('/tmp'),Path.home(),Path(sys.executable).resolve(),Path(sys.prefix),Path(node).resolve(),Path(request.origin).resolve())]
    allocation={}
    for location,size in ((w,8*GIB),(o,2*GIB),*([(resume,4*GIB)] if resume is not None else [])):
        device=actual(location).stat().st_dev;allocation[device]=allocation.get(device,0)+size
    for f in fs:
        f['additional_peak_estimate_bytes']=allocation.get(f['device'],0)
        if f['free_bytes']<f['additional_peak_estimate_bytes']+f['reserve_bytes']:
            raise RuntimeError('Insufficient complete preparation disk headroom on device '+str(f['device']))
    mem=dict((x.split(':',1)[0],int(x.split()[1])*1024) for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith(('MemTotal:','MemAvailable:')))
    if mem['MemAvailable']<8*GIB+max(2*GIB,mem['MemTotal']//5):raise RuntimeError('Insufficient conservative preparation memory headroom')
    report=dict(status='EARLY_CAPACITY_CHECK_PASS_NOT_AGGREGATE_QUALIFICATION',at=now(),
        application_source=BASE,application_tree=TREE,legacy_source=LEGACY,installer=installer,runtime=runtime,integrity_sha256=digest,
        harness_sha256=HARNESS,input_contract_sha256=INPUTS,filesystems=fs,memory=mem,
        memory_peak_estimate_bytes=8*GIB,core_seconds=CORE_SECONDS,total_seconds=TOTAL_SECONDS,
        output_cap_bytes=OUTPUT_CAP,source_objects='git-fsck-complete-no-alternates')
    if initialize:
        if w.exists() or o.exists():raise RuntimeError('New run-specific work and export directories required')
        w.mkdir(parents=True);o.mkdir(parents=True);write(w/'PREFLIGHT.json',report)
    return report

def worker(args):
    import operating_diagnostic as h
    import diagnostic_seed as seed
    import coverage_gate
    h.require_offline();integrity(args.integrity)
    a,w,o=paths(args);root=w/'construction/root';restored=w/'restoration/root'
    installed(args,load(w/'PREFLIGHT.json')['installer'])
    if args.stage=='frontier':continuation_frontier(args)
    elif args.stage=='construct':
        if continuation_path(args) is None:h.fixture(a,root,small=False)
        else:
            record=load(w/'CONTINUATION.json');prefix=load(w/'CONTINUATION_PREFIX.json')
            import seed_checkpoint_frontier as frontier
            if (record['run_id']!=int(os.environ['GITHUB_RUN_ID']) or record['continuation_id']!=CONTINUATION_ID
                or record['installer']!=load(w/'PREFLIGHT.json')['installer']
                or record['original_fixture_head']!=PREFIX_HEAD or record['application_source']!=BASE
                or record['harness_sha256']!=HARNESS or record['input_contract_sha256']!=INPUTS
                or record['first_remaining_generation']!=14 or record['target_generations']!=24
                or record['freshly_replayed_prefix_generations']!=13
                or record['prefix_inventory_sha256']!=rawhash(w/'CONTINUATION_PREFIX.json')
                or continuation_inventory(root)!=prefix or git(root,'rev-parse','HEAD')!=PREFIX_HEAD):
                raise RuntimeError('Continuation prefix changed before construction')
            continue_generations(root,h)
    elif args.stage=='admit':h.admit(a,root,w/'ADMISSION.json',small=False)
    elif args.stage=='gate':
        admission=load(w/'ADMISSION.json');gate=coverage_gate.evaluate(h,admission);write(w/'COVERAGE.json',gate)
        if admission.get('status')!='ADMITTED' or gate.get('status')!='PRELIMINARY_COVERAGE_PASS':raise RuntimeError('Full admission or coverage failed')
    elif args.stage=='freeze':seed.freeze(root,w/'seed',w/'ADMISSION.json',h)
    elif args.stage=='restore':
        restored.parent.mkdir(parents=True,exist_ok=True)
        seed.restore(w/'seed',restored,rawhash(w/'seed/SEED_MANIFEST.json'))
    elif args.stage=='recheck':h.recheck(restored,w/'RESTORATION.json')
    else:raise RuntimeError('Unknown exact preparation stage')

def bounded_stage(args,name,deadline,log):
    remaining=deadline-time.monotonic()
    if remaining<=0:raise TimeoutError('Fixed preparation core deadline exhausted')
    env=os.environ.copy();env.pop('GITHUB_SHA',None)
    temp=Path(args.work)/'tmp';temp.mkdir(exist_ok=True)
    env.update(TMPDIR=str(temp),PYTHONDONTWRITEBYTECODE='1')
    cmd=[sys.executable,str(Path(__file__).resolve()),'_stage','--stage',name,'--app',args.app,'--work',args.work,'--output',args.output,'--integrity',str(args.integrity)]
    if getattr(args,'continue_checkpoint',False):cmd.append('--continue-checkpoint')
    with log.open('wb') as stream,selectors.DefaultSelector() as ready:
        p=subprocess.Popen(cmd,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        ready.register(p.stdout,selectors.EVENT_READ);written=0
        try:
            while ready.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Fixed preparation core deadline exhausted')
                for key,_ in ready.select(min(1,remaining)):
                    value=os.read(key.fd,65536)
                    if not value:ready.unregister(key.fileobj);continue
                    if written+len(value)>16*1024**2:raise RuntimeError('Bounded private stage log exceeded')
                    stream.write(value);written+=len(value)
            rc=p.wait(timeout=max(0.01,deadline-time.monotonic()))
        except BaseException:
            if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
            raise
        finally:p.stdout.close()
    if rc:raise RuntimeError(name+' failed with exit '+str(rc)+'; raw diagnostic log retained locally')

class CappedFile:
    def __init__(self,path,cap,deadline):self.f=path.open('xb');self.cap=cap;self.n=0;self.deadline=deadline
    def write(self,data):
        if time.monotonic()>self.deadline or self.n+len(data)>self.cap:raise RuntimeError('Bounded preservation allowance exhausted')
        self.n+=len(data);return self.f.write(data)
    def flush(self):self.f.flush()
    def close(self):self.f.close()

def checkpoint(w,o,deadline):
    """Retain explicit fixture files and source/fixture refs, never arbitrary .git."""
    root=w/'construction/root';files={};bundle=o/'INCOMPLETE_SOURCE_CLOSURE.bundle'
    if not root.is_dir():return dict(status='NO_FIXTURE_CREATED')
    if (root/'.git').is_dir():
        refs=[r for r in ('HEAD','refs/fixture/source') if subprocess.run(['git','-C',str(root),'rev-parse','--verify',r],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0]
        if refs:
            occupied=sum(p.stat().st_size for p in o.iterdir() if p.is_file())
            end=min(deadline,time.monotonic()+300);sink=CappedFile(bundle,OUTPUT_CAP-32*1024**2-occupied,end)
            process=subprocess.Popen(['git','-C',str(root),'bundle','create','-',*refs],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
            try:
                with selectors.DefaultSelector() as ready:
                    ready.register(process.stdout,selectors.EVENT_READ)
                    while ready.get_map():
                        if time.monotonic()>end:raise TimeoutError('Bounded source-closure preservation deadline')
                        for key,_ in ready.select(1):
                            value=os.read(key.fd,65536)
                            if not value:ready.unregister(key.fileobj)
                            else:sink.write(value)
                if process.wait(timeout=max(.01,end-time.monotonic())):raise RuntimeError('Incomplete Git bundle')
            except BaseException:
                if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.wait()
                bundle.replace(w/'failed-checkpoint.partial.bundle');raise
            finally:sink.close();process.stdout.close()
    for lane in ('pull','tools','config','data','output'):
        for p in sorted((root/lane).rglob('*')):
            if p.is_symlink():raise RuntimeError('Checkpoint refuses symlink')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':files[p.relative_to(root).as_posix()]=p
    for name in ('FICTIONAL_ONLY.json','FICTIONAL_PHASES.json','FICTIONAL_LEGACY_BASELINE.json','FICTIONAL_PARTICIPATION_ADAPTER.json'):
        marker=root/name
        if marker.is_symlink():raise RuntimeError('Checkpoint refuses symlink')
        if marker.is_file():files[marker.name]=marker
    progress=root.parent/'progress.json'
    if progress.is_file() and not progress.is_symlink():files['CONSTRUCTION_PROGRESS.json']=progress
    # No loss is disguised as a complete seed. The existing construction may be
    # interrupted; this preserves bytes for inspection, not an admitted resume.
    occupied=sum(p.stat().st_size for p in o.iterdir() if p.is_file())
    destination=o/'INCOMPLETE_CHECKPOINT.tar.gz';sink=CappedFile(destination,OUTPUT_CAP-32*1024**2-occupied,deadline)
    inventory={}
    try:
        with gzip.GzipFile(fileobj=sink,mode='wb',mtime=0,filename='') as gz,tarfile.open(fileobj=gz,mode='w|') as tar:
            for name,p in sorted(files.items()):
                if time.monotonic()>deadline:raise TimeoutError('Preservation deadline')
                d=dict(bytes=p.stat().st_size,sha256=rawhash(p));inventory[name]=d
                info=tarfile.TarInfo(name);info.size=d['bytes'];info.mode=0o600;info.mtime=0
                with p.open('rb') as stream:tar.addfile(info,stream)
    except BaseException:
        destination.replace(w/'failed-checkpoint.partial.tar.gz');raise
    finally:sink.close()
    value=dict(status='INCOMPLETE_NOT_ADMITTED_NOT_RESUME_AUTHORIZED',application_source=BASE,
        input_contract_sha256=INPUTS,files=inventory,archive_sha256=rawhash(destination),archive_bytes=destination.stat().st_size,
        git_bundle=None if not bundle.exists() else dict(name=bundle.name,bytes=bundle.stat().st_size,sha256=rawhash(bundle)),
        source_objects='PUBLIC_SOURCE_DISTINCT_FROM_FICTIONAL_DATA_IN_EXPLICIT_BUNDLE')
    write(o/'INCOMPLETE_MANIFEST.json',value);return value

def run(args):
    import operating_diagnostic as h
    # This cloud-only preparation boundary needs separate future invocation
    # approval. The old absolute deadline in the preserved input contract is
    # historical; this code neither revives it nor authorizes an operating run.
    start=time.monotonic();h.require_offline();a,w,o=paths(args)
    preflight_record=load(w/'PREFLIGHT.json')
    if preflight_record.get('integrity_sha256')!=integrity(args.integrity):raise RuntimeError('Code changed after early check')
    # Repeat capacity/source checks after setup; do not recreate directories.
    preflight(args,initialize=False)
    result=dict(status='PREPARATION_RUNNING',started_at=now(),stages=[],
        application_source=BASE,application_tree=TREE,harness_sha256=HARNESS,input_contract_sha256=INPUTS,
        core_limit_seconds=CORE_SECONDS,total_limit_seconds=TOTAL_SECONDS,operating_qualification='NOT_RUN')
    write(w/'PREPARATION_RESULT.json',result)
    try:
        stages=('construct','admit','gate','freeze','restore','recheck')
        if continuation_path(args) is not None:stages=('frontier',)+stages
        for name in stages:
            stage=dict(name=name,status='RUNNING',started_at=now());result['stages'].append(stage);write(w/'PREPARATION_RESULT.json',result)
            t=time.monotonic();bounded_stage(args,name,start+CORE_SECONDS,w/(name+'.private.log'))
            stage.update(status='PASS',exclusive_seconds=time.monotonic()-t,completed_at=now());write(w/'PREPARATION_RESULT.json',result)
        admission=load(w/'ADMISSION.json');replay=load(w/'RESTORATION.json');manifest=load(w/'seed/SEED_MANIFEST.json')
        if replay.get('status')!='PASS_SAVED_RECONSTRUCTION' or replay.get('semantic_sha256')!=admission['metrics']['public_semantics_sha256'] or manifest['semantic_sha256']!=replay['semantic_sha256']:
            raise RuntimeError('Fresh restored semantic identity mismatch')
        total=sum((w/'seed'/n).stat().st_size for n in SEED_FILES)
        if total>OUTPUT_CAP-32*1024**2:raise RuntimeError('Approved artifact output bound exceeded')
        for name in SEED_FILES:
            shutil.copyfile(w/'seed'/name,o/name)
            if rawhash(w/'seed'/name)!=rawhash(o/name):raise RuntimeError('Copied seed parent changed')
        result.update(status='PREPARATION_COMPLETE_NOT_OPERATING_QUALIFIED',seed_manifest_sha256=rawhash(o/'SEED_MANIFEST.json'),seed_parent_bytes=total)
    except (Exception,KeyboardInterrupt) as err:
        result.update(status='PREPARATION_FAILED',failure=type(err).__name__+': '+str(err))
        if result['stages'] and result['stages'][-1]['status']=='RUNNING':result['stages'][-1].update(status='FAIL',exclusive_seconds=time.monotonic()-t,completed_at=now())
        try:result['preservation']=checkpoint(w,o,start+TOTAL_SECONDS)
        except Exception as failure:result['preservation']=dict(status='RETENTION_FAILED',reason=type(failure).__name__+': '+str(failure),runner_local_progress_only=True)
    finally:
        if (w/'CONTINUATION.json').exists():result['continuation']=load(w/'CONTINUATION.json')
        result.update(finished_at=now(),driver_seconds=time.monotonic()-start)
        write(w/'PREPARATION_RESULT.json',result)
    return 0 if result['status']=='PREPARATION_COMPLETE_NOT_OPERATING_QUALIFIED' else 3

def finalize(args):
    a,w,o=paths(args);integrity(args.integrity)
    o.mkdir(parents=True,exist_ok=True)
    for name in ('PREFLIGHT.json','ADMISSION.json','COVERAGE.json','RESTORATION.json','PREPARATION_RESULT.json','RESOURCE.json','CAPABILITY.json','ANCESTORS.before.json','ANCESTORS.after.json'):
        source=w/name
        if source.exists():load(source);shutil.copyfile(source,o/name)
    inventory={}
    for p in o.iterdir():
        if p.name not in PUBLIC_FILES or p.is_symlink() or not p.is_file():raise RuntimeError('Unapproved export path: '+p.name)
        if p.name!='ARTIFACT_MANIFEST.json':inventory[p.name]=dict(bytes=p.stat().st_size,sha256=rawhash(p))
    if sum(v['bytes'] for v in inventory.values())>OUTPUT_CAP-1024**2:raise RuntimeError('Complete artifact exceeds approved 2GiB bound')
    result=load(o/'PREPARATION_RESULT.json') if (o/'PREPARATION_RESULT.json').exists() else {'status':'STOPPED_BEFORE_PREPARATION'}
    resource=load(o/'RESOURCE.json') if (o/'RESOURCE.json').exists() else {}
    if result['status']=='PREPARATION_COMPLETE_NOT_OPERATING_QUALIFIED':
        manifest=load(o/'SEED_MANIFEST.json')
        if rawhash(o/'SEED_MANIFEST.json')!=result['seed_manifest_sha256'] or manifest.get('full_admitted') is not True or manifest.get('application_source')!=BASE or manifest.get('harness_sha256')!=HARNESS:
            raise RuntimeError('Final output seed identity mismatch')
        descriptors=[manifest['working'],*manifest['packs']]
        if {x['name'] for x in descriptors}!=set(SEED_FILES)-{'SEED_MANIFEST.json'}:raise RuntimeError('Incomplete final seed parents')
        for descriptor in descriptors:
            actual=inventory.get(descriptor['name'])
            if actual!={k:descriptor[k] for k in ('bytes','sha256')}:raise RuntimeError('Final output seed parent changed')
    write(o/'ARTIFACT_MANIFEST.json',dict(schema_version='cloud-seed-artifact-envelope-v1',
        prepared_at=now(),application_source=BASE,installer=load(o/'PREFLIGHT.json')['installer'] if (o/'PREFLIGHT.json').exists() else None,
        runtime=load(o/'PREFLIGHT.json')['runtime'] if (o/'PREFLIGHT.json').exists() else None,integrity_sha256=rawhash(args.integrity),files=inventory,
        preparation_status=result['status'],resource_report_present=bool(resource),resource_verdict=resource.get('resource_verdict','UNKNOWN'),operating_qualification='NOT_RUN',
        transport='PROPOSED_ACTIONS_ARTIFACT_NOT_UPLOADED_BY_DRIVER',publication_authorized_by_code=False,
        absent_legacy_transport='Seed parents retain original bytes; old Git part transport is not this artifact route'))
    return 0

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('preflight','run','finalize','_stage','retrieve-continuation'))
    for name in ('app','work','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--integrity',type=Path,default=Path(__file__).with_name('cloud-seed-integrity.json'))
    p.add_argument('--stage',choices=('frontier','construct','admit','gate','freeze','restore','recheck'))
    p.add_argument('--continue-checkpoint',action='store_true')
    args=p.parse_args()
    if args.action=='retrieve-continuation':retrieve_continuation(args);return 0
    if args.action=='preflight':preflight(args);return 0
    if args.action=='run':return run(args)
    if args.action=='finalize':return finalize(args)
    worker(args);return 0
if __name__=='__main__':raise SystemExit(main())
