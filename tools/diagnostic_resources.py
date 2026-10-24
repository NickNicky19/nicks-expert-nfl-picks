"""Proposed dedicated-runner supervisor. No setup runs on import/preflight.

Only supervise creates an ephemeral root-owned cgroup, after owner approval.
An unavailable exact backend stops before any expensive workload. No sampled
RSS sum or shared historical memory peak can produce PASS.
"""
import argparse
import hashlib
import ctypes
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

GIB=1024**3

class CapabilityReady(Exception):pass

def events(path):
    result={}
    for line in (path/'memory.events').read_text().splitlines():
        fields=line.split()
        if len(fields)!=2 or fields[0] in result or not fields[1].isdigit():raise RuntimeError('Malformed OOM counters')
        result[fields[0]]=int(fields[1])
    if not {'oom','oom_kill','oom_group_kill'}<=set(result):raise RuntimeError('Required OOM counters unavailable')
    return result

def resolve():
    membership=[line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')]
    mounts=[line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines() if ' - cgroup2 ' in line]
    if len(membership)!=1 or len(mounts)!=1:raise RuntimeError('Ambiguous cgroup-v2 scope')
    if os.readlink('/proc/self/ns/cgroup')!=os.readlink('/proc/1/ns/cgroup'):raise RuntimeError('Different init/workload cgroup namespace')
    row=mounts[0];mount=Path(row[4]);relative=Path(membership[0])
    if row[3]!='/' or not relative.is_absolute() or '..' in relative.parts:
        raise RuntimeError('Hidden ancestor/namespace closure')
    current=mount/relative.relative_to('/')
    ancestors=[current,*[p for p in current.parents if p==mount or mount in p.parents]]
    if ancestors[-1]!=mount:raise RuntimeError('Incomplete ancestor closure')
    return mount,current,ancestors

def critical(paths):
    result={}
    for path in paths:
        p=Path(path).resolve()
        while not p.exists():p=p.parent
        st=p.stat();usage=shutil.disk_usage(p)
        key=str(st.st_dev)
        old=result.setdefault(key,dict(paths=[],total=usage.total,free=usage.free))
        old['paths'].append(str(Path(path).resolve()));old['free']=min(old['free'],usage.free)
    if not result:raise RuntimeError('No critical filesystems')
    return result

def disk_ok(record):
    return type(record.get('free')) is int and record['free']>=max(2*GIB,.2*record['total'])

def peak_ok(limit,peak):
    return type(limit) is int and type(peak) is int and limit>0 and 0<=peak<=limit and limit-peak>=max(2*GIB,.2*limit)

def capability(paths, privileged=False):
    try:
        mount,current,ancestors=resolve()
        if os.statvfs(mount).f_flag & os.ST_RDONLY:raise RuntimeError('Read-only cgroup mount')
        if privileged and os.geteuid()!=0:raise RuntimeError('Root supervisor permission absent')
        parent=current.parent if current!=mount else mount
        if 'memory' not in (parent/'cgroup.subtree_control').read_text().split():
            raise RuntimeError('Memory controller not already enabled; no controller mutation allowed')
        ancestors=[parent,*[p for p in parent.parents if p==mount or mount in p.parents]]
        for parent in ancestors:
            for control in (parent,parent/'cgroup.procs',parent/'cgroup.threads'):
                st=control.stat()
                if st.st_uid!=0 or st.st_mode&0o022:raise RuntimeError('Workload can escape delegated accounting')
            if parent==mount:continue
            for name in ('memory.current','memory.peak','memory.events','memory.max'):
                if not (parent/name).is_file():raise RuntimeError('Missing ancestor accounting')
        disks=critical(paths)
        if not all(map(disk_ok,disks.values())):raise RuntimeError('Critical filesystem headroom')
        return dict(status='CAPABLE_PENDING_FRESH_PEAK_RESET',mount=str(mount),current=str(current),
            ancestors=list(map(str,ancestors)),parent=str(ancestors[0]),filesystems=disks,
            ancestor_limits={str(p):(p/'memory.max').read_text().strip() for p in ancestors if p!=mount},
            controller=(ancestors[0]/'cgroup.subtree_control').read_text().strip(),
            cpu_limits={str(p):(p/'cpu.max').read_text().strip() for p in ancestors if (p/'cpu.max').is_file()},
            affinity_cpus=len(os.sched_getaffinity(0)),logical_cpus=os.cpu_count())
    except (OSError,ValueError,RuntimeError) as err:
        return dict(status='LOCAL_CAPABILITY_UNAVAILABLE',next='HOSTED_PREFLIGHT_REQUIRED',reason=str(err))

def populated(path):
    return dict(line.split() for line in (path/'cgroup.events').read_text().splitlines()).get('populated')!='0'

def wait_empty(path):
    end=time.monotonic()+10
    while populated(path):
        if time.monotonic()>=end:raise RuntimeError('Subprocess tree did not exit')
        time.sleep(.05)


def validate_supervision(args):
    # Seed construction is a separately authorized purpose, never an operating sample.
    purpose=getattr(args,'purpose','operating')
    if purpose=='operating':valid_sample=args.sample in (1,2,3);maximum=1200
    elif purpose=='seed-preparation':valid_sample=args.sample==0;maximum=18000
    else:raise RuntimeError('Unsupported resource supervision purpose')
    if type(args.uid) is not int or type(args.gid) is not int or args.uid<=0 or args.gid<=0 or not valid_sample or type(args.run_id) is not int or args.run_id<=0 or type(args.timeout) is not int or not 0<args.timeout<=maximum:
        raise RuntimeError('Invalid unprivileged worker/run/purpose/sample/timeout')
    return purpose


def supervise(args):
    # Explicit future privileged entry. No implicit sudo, no service/controller changes.
    purpose=validate_supervision(args)
    started=time.monotonic();caps=capability(args.critical_path,True)
    output=Path(args.output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    report=dict(schema_version='diagnostic-resources-v1',purpose=purpose,capability=caps,status='PREFLIGHT_FAILED',
        run_id=args.run_id,sample=args.sample,source=os.environ.get('GITHUB_SHA'),
        harness_sha256=os.environ.get('DIAGNOSTIC_HARNESS_SHA256'),seed_manifest_sha256=os.environ.get('SEED_MANIFEST_SHA256'),
        resource_verdict='UNKNOWN',complete_tree=False,minimum_free_bytes=2*GIB,minimum_free_fraction=.2)
    leaf=None;streams=[];child=None;fail=[];initial={};maxima={};minimum={};rc=1
    def save():output.write_text(json.dumps(report,sort_keys=True,separators=(',',':')))
    try:
        if caps['status']!='CAPABLE_PENDING_FRESH_PEAK_RESET':raise RuntimeError(caps.get('reason','Capability unavailable'))
        if not args.exclusive_runner or os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted' or os.environ.get('GITHUB_RUN_ATTEMPT')!='1' or os.environ.get('GITHUB_RUN_ID')!=str(args.run_id):raise RuntimeError('Approved first-attempt exclusive GitHub-hosted job binding required')
        checkout=Path(os.environ['GITHUB_WORKSPACE']).resolve()
        actual=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
        if actual!=os.environ.get('GITHUB_SHA'):raise RuntimeError('Supervisor checkout mismatch')
        report['source']=actual
        report['harness_sha256']=hashlib.sha256((checkout/'tools/operating_diagnostic.py').read_bytes()).hexdigest()
        mount=Path(caps['mount']);ancestors=list(map(Path,caps['ancestors']))
        # Fresh FD-local ancestor peaks, including current host use. Unsupported kernels abort here.
        for parent in ancestors:
            if parent==mount:continue  # Root has no memory controller accounting; VM-wide bound is below.
            fd=open(parent/'memory.peak','r+');fd.write('0');fd.flush();fd.seek(0)
            current=int((parent/'memory.current').read_text());fd.seek(0);peak=int(fd.read())
            if peak<current:raise RuntimeError('Fresh ancestor peak semantics unsupported')
            streams.append((parent,fd));initial[str(parent)]=events(parent)
        # VM-wide MemAvailable has no exact resettable peak. Therefore only a
        # finite memory-limited ancestor closure may qualify; no bare-VM guess.
        finite=[]
        for parent,_ in streams:
            value=(parent/'memory.max').read_text().strip()
            if value!='max':finite.append(int(value))
        if not finite:raise RuntimeError('No finite attributable ancestor memory limit')
        name='nfl-diagnostic-'+str(args.run_id)+'-'+str(args.sample)+'-'+str(os.getpid())
        candidate=Path(caps['parent'])/name
        candidate.mkdir(mode=0o755)
        leaf=candidate  # root-owned; workload cannot migrate itself or descendants.
        for control in (leaf,leaf/'cgroup.procs',leaf/'cgroup.threads'):
            st=control.stat()
            if st.st_uid!=0 or st.st_mode&0o022:raise RuntimeError('Fresh accounting leaf not root-controlled')
        if not (leaf/'cgroup.kill').exists() or not os.access(leaf/'cgroup.kill',os.W_OK):raise RuntimeError('Tree kill unavailable')
        if (leaf/'cgroup.procs').read_text().strip() or int((leaf/'memory.peak').read_text())!=0 or any(events(leaf).values()):
            raise RuntimeError('New group is not fresh/empty')
        limit=min(finite);(leaf/'memory.max').write_text(str(limit));(leaf/'memory.swap.max').write_text('0')
        initial[str(leaf)]=events(leaf)
        if args.preflight_only:raise CapabilityReady()
        command=args.command
        if command and command[0]=='--':command=command[1:]
        if not command:raise RuntimeError('No guarded workload command')
        def enter():
            (leaf/'cgroup.procs').write_text(str(os.getpid()))
            os.setgroups([]);os.setgid(args.gid);os.setuid(args.uid)
            if os.geteuid()!=args.uid or os.getegid()!=args.gid or any(line.split()[1]!='0000000000000000' for line in Path('/proc/self/status').read_text().splitlines() if line.startswith(('CapEff:','CapPrm:','CapAmb:'))):raise RuntimeError('Privilege drop incomplete')
            if ctypes.CDLL(None).prctl(38,1,0,0,0)!=0:raise RuntimeError('no_new_privs failed')
        env=dict(os.environ)
        for key in ('HOME','USER','LOGNAME'):env.pop(key,None)  # Child resolves its real dropped-UID account, not sudo's root home.
        env['DIAGNOSTIC_RESOURCE_BACKEND']='root-supervised-cgroup-v1'
        env['DIAGNOSTIC_RESOURCE_OUTPUT']=str(output)
        child=subprocess.Popen(command,preexec_fn=enter,env=env,start_new_session=True)
        while True:
            for key,value in critical(args.critical_path).items():
                if key not in minimum:minimum[key]=value
                minimum[key]['free']=min(minimum[key]['free'],value['free'])
                if not disk_ok(minimum[key]):fail.append('DISK_HEADROOM')
            if time.monotonic()-started>=args.timeout:fail.append('SUPERVISOR_TIMEOUT')
            if fail:
                (leaf/'cgroup.kill').write_text('1')
            rc=child.poll()
            if rc is not None:break
            time.sleep(.1)
        child.wait()
        if populated(leaf):
            (leaf/'cgroup.kill').write_text('1');fail.append('DESCENDANTS_REMAIN_AFTER_CLEANUP')
        wait_empty(leaf)
        for parent,fd in streams:
            fd.seek(0);peak=int(fd.read());raw=(parent/'memory.max').read_text().strip()
            if raw!=caps['ancestor_limits'][str(parent)]:fail.append('CHANGED_ANCESTOR_LIMIT')
            maxima[str(parent)]=dict(kernel_peak=peak,limit=None if raw=='max' else int(raw))
            if raw!='max' and not peak_ok(int(raw),peak):fail.append('ANCESTOR_MEMORY_HEADROOM')
        if resolve()!=(mount,Path(caps['current']),[Path(caps['current']),*[p for p in Path(caps['current']).parents if p==mount or mount in p.parents]]) or (Path(caps['parent'])/'cgroup.subtree_control').read_text().strip()!=caps['controller'] or (leaf/'memory.max').read_text().strip()!=str(limit) or (leaf/'memory.swap.max').read_text().strip()!='0':fail.append('CHANGED_RESOURCE_SCOPE')
        peak=int((leaf/'memory.peak').read_text());maxima[str(leaf)]=dict(kernel_peak=peak,limit=limit)
        if not peak_ok(limit,peak):fail.append('WORKLOAD_MEMORY_HEADROOM')
        deltas={}
        for parent in [*(p for p,_ in streams),leaf]:
            end=events(parent)
            deltas[str(parent)]={k:end[k]-initial[str(parent)].get(k,0) for k in end}
            if any(end.get(k,0)-initial[str(parent)].get(k,0)>0 for k in ('oom','oom_kill','oom_group_kill')):fail.append('OOM')
        if rc:fail.append('WORKLOAD_FAILURE')
        report.update(status='COMPLETE',resource_verdict='FAIL' if fail else 'PASS',complete_tree=not populated(leaf),
            attributable_scope='FRESH_WORKLOAD_LEAF_AND_VISIBLE_FINITE_ANCESTORS_ON_EXCLUSIVE_VM',
            initial_events=initial,event_deltas=deltas,peak_reset_verified=True,scope_closure_verified=True,privilege_drop_verified=True,kernel_peaks=maxima,filesystem_minima=minimum,failures=sorted(set(fail)),returncode=rc)
    except CapabilityReady:
        report.update(status='CAPABILITY_READY',resource_verdict='NOT_RUN_CAPABILITY_ONLY',complete_tree=True)
    except BaseException as err:
        report.update(status='CAPABILITY_OR_MONITOR_FAILURE',resource_verdict='UNKNOWN',reason=type(err).__name__+': '+str(err))
        if leaf is not None and populated(leaf):
            try:
                (leaf/'cgroup.kill').write_text('1')
                if child is not None:child.wait(timeout=10)
                wait_empty(leaf)
            except (OSError,RuntimeError,subprocess.TimeoutExpired) as cleanup:report['termination_error']=str(cleanup)
    finally:
        for _,fd in streams:fd.close()
        if leaf is not None:
            try:leaf.rmdir()
            except OSError as err:report.update(resource_verdict='UNKNOWN',cleanup_error=str(err))
        report['supervisor_seconds']=time.monotonic()-started
        if report.get('resource_verdict')=='PASS':report['resource_verdict']=report_verdict(report)
        save()
    return 0 if report['resource_verdict']=='PASS' or report.get('status')=='CAPABILITY_READY' and 'cleanup_error' not in report else 2

def report_verdict(value):
    if value.get('status')!='COMPLETE' or value.get('complete_tree') is not True:return 'UNKNOWN'
    if any(value.get(k) is not True for k in ('peak_reset_verified','scope_closure_verified','privilege_drop_verified')):return 'UNKNOWN'
    if value.get('failures') or value.get('returncode')!=0:return 'FAIL'
    peaks=value.get('kernel_peaks');disks=value.get('filesystem_minima');deltas=value.get('event_deltas')
    if not isinstance(peaks,dict) or not peaks or not isinstance(disks,dict) or not disks or not isinstance(deltas,dict) or not deltas:return 'UNKNOWN'
    finite=[p for p in peaks.values() if p.get('limit') is not None]
    if not finite:return 'UNKNOWN'
    required={'oom','oom_kill','oom_group_kill'}
    if any(not isinstance(v,dict) or not required<=set(v) or any(type(v[k]) is not int or v[k]<0 for k in required) for v in deltas.values()):return 'UNKNOWN'
    if any(not peak_ok(p.get('limit'),p.get('kernel_peak')) for p in finite):return 'FAIL'
    if any(not disk_ok(d) for d in disks.values()):return 'FAIL'
    if any(v.get(k,0)>0 for v in deltas.values() for k in ('oom','oom_kill','oom_group_kill')):return 'FAIL'
    return 'PASS'


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('preflight','supervise'))
    p.add_argument('--critical-path',action='append',required=True);p.add_argument('--output');p.add_argument('--run-id',type=int)
    p.add_argument('--sample',type=int);p.add_argument('--uid',type=int);p.add_argument('--gid',type=int)
    p.add_argument('--purpose',choices=('operating','seed-preparation'),default='operating')
    p.add_argument('--exclusive-runner',action='store_true');p.add_argument('--preflight-only',action='store_true');p.add_argument('--timeout',type=int,default=1200)
    argv=sys.argv[1:];cut=argv.index('--') if '--' in argv else len(argv)
    args=p.parse_args(argv[:cut]);args.command=argv[cut+1:] if cut<len(argv) else []
    if args.action=='preflight':
        value=capability(args.critical_path);print(json.dumps(value,sort_keys=True));sys.exit(0 if value['status']=='CAPABLE_PENDING_FRESH_PEAK_RESET' else 3)
    sys.exit(supervise(args))

if __name__=='__main__':main()
