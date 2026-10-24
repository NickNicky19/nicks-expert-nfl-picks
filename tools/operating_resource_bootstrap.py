"""Manual operating-only resource launcher. No setup occurs on import or --help.

Execute only under separately approved transient-service privileges. Existing
seed helpers remain immutable. Their P5 resource-report field keeps its meaning;
the independent root-owned outer record binds this operating wrapper and argv.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import time

REPOSITORY = 'NickNicky19/nicks-expert-nfl-picks'
BRANCH = 'upgrade/phase2-reproducible-comparison'
WORKFLOW = '.github/workflows/operating-diagnostic.yml'
CAMPAIGN = 'NFL-WEB-OPERATING-SEED-THREE-20261020-B3'
GENUINE_WORKFLOW = '.github/workflows/prepare-diagnostic-seed.yml'
GENUINE_CONFIRMATION = 'NFL-WEB-GENUINE-PRODUCTION-CASE-20261024'
GENUINE_DRIVER = '2ee6d870c3bb6c8e667eae3a49cadf22220d6ab21d0c990c8035332d1deadfaf'
LIFETIME_BACKEND = 'SYSTEMD_INVOCATION_CACHED_KERNEL_MEMORY_PEAK_V1'
P5 = '441f0ccaa1b274708419643d993896b5ff6f2c4118e0016719c80a1746289328'
RESOURCE = 'e02bc3926f709029f038bd2bd275247e8738ace9fb1645dfb67eff63d804d292'
SEED_INTEGRITY = 'bfb48f36d1db5b2980235238e1b869efb183f23095ff72cee33c1d88e84a3b26'
ROOT_BASE = Path('/var/tmp')
LIMIT = 2 * 1024 * 1024
ROOT_GIT = ('GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_0', 'GIT_CONFIG_VALUE_0',
            'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM')
FILES = ('tools/operating_resource_bootstrap.py', 'tools/operating_campaign.py',
         'tools/source_ci.py', 'tools/diagnostic_resources.py',
         'tools/operating_diagnostic.py', 'tools/operating_seed_transport.py',
         'tools/cloud-seed-integrity.json', 'tools/seed_checkpoint_frontier.py', WORKFLOW)
SEED_NAMES = {'cloud-seed-requirements.txt', 'cloud_seed_prepare.py',
              'cloud_seed_resource_bootstrap.py', 'coverage_gate.py',
              'diagnostic-seed-inputs.json', 'diagnostic_network_guard.py',
              'diagnostic_resources.py', 'diagnostic_seed.py', 'operating_diagnostic.py'}
CONTINUED_SEED_INTEGRITY = 'ed5b6773c3d4e642bf4346aa2b9de89a2b580a1f34e97bddc6172b068a388611'
FINISHED22_SEED_INTEGRITY = '636b3cd2a966346df02ad30c516dc805e40ae082e1b4f5e7b757162c29e6459f'
PREPARATION22_RETRIEVAL_INTEGRITY = '08a9fc62c6707d7385ac8388df8325bd9588f95caad3fdfc48762fdfa4b200a4'
PREPARATION24_LIFETIME_INTEGRITY = '3c68e0b8e88b458dc5ecb0dce1376160e668e1941e3e2302bce3e35a38a08f77'
SEED_CONTRACTS = {
    PREPARATION24_LIFETIME_INTEGRITY: frozenset(SEED_NAMES | {
        'seed_checkpoint_frontier.py', 'source_ci.py', 'operating_seed_transport.py'}),
    PREPARATION22_RETRIEVAL_INTEGRITY: frozenset(SEED_NAMES | {
        'seed_checkpoint_frontier.py', 'source_ci.py', 'operating_seed_transport.py'}),
    SEED_INTEGRITY: frozenset(SEED_NAMES),
    FINISHED22_SEED_INTEGRITY: frozenset(SEED_NAMES | {
        'seed_checkpoint_frontier.py', 'source_ci.py', 'operating_seed_transport.py'}),
    CONTINUED_SEED_INTEGRITY: frozenset(SEED_NAMES | {
        'seed_checkpoint_frontier.py', 'source_ci.py', 'operating_seed_transport.py'}),
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit', required=True)
    parser.add_argument('--memory-max', type=int, required=True)
    parser.add_argument('--uid', type=int, required=True)
    parser.add_argument('--gid', type=int, required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--sample', type=int, choices=(1, 2, 3), required=True)
    parser.add_argument('--code', type=Path, required=True)
    parser.add_argument('--critical-path', action='append', required=True)
    parser.add_argument('--capability-only', action='store_true')
    parser.add_argument('--genuine-case', action='store_true')
    parser.add_argument('--read-unit-lifetime', action='store_true')
    args = parser.parse_args(argv)
    if (args.unit != f'nfl-operating-{args.run_id}-{args.sample}.service'
            or min(args.run_id, args.uid, args.gid, args.memory_max) <= 0):
        raise RuntimeError('Invalid exact operating unit, sample, or worker identity')
    if args.read_unit_lifetime and not args.genuine_case:
        raise RuntimeError('Lifetime read is exclusive to the closed genuine route')
    args.code = args.code.resolve()
    return args


def environment(args):
    if not sys.flags.safe_path:
        raise RuntimeError('Root interpreter requires -P before startup to exclude checkout import shadows')
    genuine = getattr(args, 'genuine_case', False)
    reader = getattr(args, 'read_unit_lifetime', False)
    if (os.geteuid() != args.uid if reader else os.geteuid() != 0):
        raise RuntimeError('Exact dropped-UID reader required' if reader else 'Explicit approved root service required')
    if genuine and any(k in os.environ for k in ('DBUS_SYSTEM_BUS_ADDRESS','SYSTEMD_BUS_ADDRESS')):
        raise RuntimeError('System-manager bus overrides are unsupported')
    workflow = GENUINE_WORKFLOW if genuine else WORKFLOW
    campaign = GENUINE_CONFIRMATION if genuine else CAMPAIGN
    expected = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_REPOSITORY': REPOSITORY, 'GITHUB_REPOSITORY_ID': '1411185749',
                'GITHUB_ACTOR_ID': '208912933', 'GITHUB_REF_NAME': BRANCH,
                'GITHUB_RUN_ID': str(args.run_id), 'CAMPAIGN_ID': campaign,
                'GITHUB_WORKFLOW_REF': REPOSITORY + '/' + workflow + '@refs/heads/' + BRANCH,
                'PYTHONDONTWRITEBYTECODE': '1'}
    if any(os.environ.get(k) != v for k, v in expected.items()):
        raise RuntimeError('Unexpected operating workflow/run/actor/source context')
    if (not re.fullmatch('[0-9a-f]{40}', os.environ.get('GITHUB_SHA', ''))
            or Path(os.environ.get('GITHUB_WORKSPACE', '/')).resolve() != args.code
            or not os.environ.get('ImageOS') or not os.environ.get('ImageVersion')):
        raise RuntimeError('Missing exact source, seed, runtime image, or checkout identity')
    if genuine and (os.environ.get('GITHUB_WORKFLOW_SHA') != os.environ.get('GITHUB_SHA')
            or any(os.environ.get(k) for k in ('SEED_MANIFEST_SHA256', 'OPERATING_ARTIFACT_APPROVAL_SHA256'))):
        raise RuntimeError('Genuine execution needs actual workflow source and no fictional seed label')
    if not args.capability_only and not genuine and (
            not re.fullmatch('[0-9a-f]{64}', os.environ.get('SEED_MANIFEST_SHA256', ''))
            or not re.fullmatch('[0-9a-f]{64}', os.environ.get('OPERATING_ARTIFACT_APPROVAL_SHA256', ''))):
        raise RuntimeError('Campaign requires exact seed and artifact approval identities')
    if args.capability_only:
        # Capability proves only resource support: it needs no seed, artifact
        # approval, transport token, or workload. Do not invent placeholder hashes.
        for name in ('SEED_MANIFEST_SHA256', 'OPERATING_ARTIFACT_APPROVAL_SHA256', 'GH_TOKEN'):
            os.environ.pop(name, None)
    blocked = {'LD_PRELOAD', 'LD_AUDIT', 'NODE_OPTIONS', 'NODE_PATH',
               'AWS_SECRET_ACCESS_KEY', 'OPENAI_API_KEY', 'GITHUB_TOKEN'}
    if (any(os.environ.get(k) for k in blocked)
            or any(k.startswith('PYTHON') and k not in
                   {'PYTHONDONTWRITEBYTECODE', 'PYTHONPYCACHEPREFIX', 'PYTHONUNBUFFERED'}
                   for k in os.environ)):
        raise RuntimeError('Unsupported loader, interpreter, or credential override')
    if (not sys.dont_write_bytecode or sys.pycache_prefix != os.environ.get('PYTHONPYCACHEPREFIX')
            or not sys.pycache_prefix):
        raise RuntimeError('Fresh bytecode-disabled prefix required before interpreter startup')
    prefix = Path(sys.pycache_prefix)
    temp = Path(os.environ['RUNNER_TEMP']).resolve()
    if (not prefix.is_absolute() or prefix.is_symlink() or prefix.resolve() == temp
            or temp not in prefix.resolve().parents or not prefix.is_dir()
            or any(prefix.iterdir())):
        raise RuntimeError('Prefix must be an existing empty job-local directory')
    library = os.environ.get('LD_LIBRARY_PATH')
    if library and library != str(Path(sys.base_prefix) / 'lib'):
        raise RuntimeError('Unsupported runtime library path')
    if not args.capability_only and not reader and not os.environ.get('GH_TOKEN'):
        raise RuntimeError('Read-only Actions token required before isolated campaign entry')
    account = pwd.getpwuid(args.uid)
    if args.code.stat().st_uid != args.uid or account.pw_gid != args.gid:
        raise RuntimeError('Worker must be the actual checkout owner and account group')
    # These overrides exist only for root-owned read-only Git access below.
    # No caller-selected Git namespace, object store, hooks or config survives.
    for key in tuple(os.environ):
        if key.startswith('GIT_'):
            del os.environ[key]
    os.environ.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                      GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='safe.directory',
                      GIT_CONFIG_VALUE_0=str(args.code))


def git(code, *argv):
    return subprocess.check_output(['/usr/bin/git', '--no-replace-objects',
        '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
        '-C', str(code), *argv], stderr=subprocess.PIPE)


def regular_bytes(path, limit=LIMIT):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
        raise RuntimeError('Unsupported bounded regular source/report file')
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise RuntimeError('Source/report exceeds its bound')
    return raw


def genuine_driver(code, commit):
    raw = regular_bytes(code / GENUINE_WORKFLOW)
    if raw != git(code, 'show', commit + ':' + GENUINE_WORKFLOW):
        raise RuntimeError('Genuine workflow differs from actual source')
    start = b'          import datetime as dt, gzip, hashlib, json, math, os, re, resource, signal, stat, subprocess, sys, tarfile, time\n'
    end = b"          if __name__=='__main__':main()\n"
    if raw.count(start) != 1 or raw.count(end) != 1:
        raise RuntimeError('Closed genuine driver markers unavailable')
    block = raw[raw.index(start):raw.index(end) + len(end)]
    if any(row.strip() and not row.startswith(b'          ') for row in block.splitlines()):
        raise RuntimeError('Genuine source indentation changed')
    value = b''.join((row[10:] if row.startswith(b'          ') else b'') + b'\n' for row in block.splitlines())
    if len(value) != 30854 or sha(value) != GENUINE_DRIVER:
        raise RuntimeError('Unknown genuine controller bytes')
    return value


def genuine_data_head(code, source):
    head = git(code, 'rev-parse', 'HEAD').decode().strip()
    mutable = lambda n: n != 'data/verification/2026/w06/dcf4bce0b2d3a162bdea39217eb6ae0ee2545e3895cce129338afc715a5e8e2a.json.gz' and n.startswith(('output/data/', 'data/cache/', 'data/forward/', 'data/history/', 'data/verification/', 'data/shadow/', 'data/offers/', 'data/outcomes/')) and n.endswith(('.json', '.json.gz'))
    if head != source:
        if git(code, 'show', '-s', '--format=%P', head).decode().strip() != source:
            raise RuntimeError('Genuine local result is not one direct data descendant')
        names = git(code, 'diff', '--name-only', '-z', source, head).split(b'\0')
        if not any(names) or any(not mutable(n.decode()) for n in names if n):
            raise RuntimeError('Local result changes source or fixed evidence')
    names = git(code, 'diff', '--name-only', '-z', 'HEAD').split(b'\0')
    if any(not mutable(n.decode()) for n in names if n):
        raise RuntimeError('Unvalidated tracked source change after genuine execution')
    names = git(code, 'ls-files', '--others', '-z').split(b'\0')
    pyc = re.compile(r'(?:[^/]+/)*__pycache__/[A-Za-z_][A-Za-z0-9_]*\.cpython-312(?:\.opt-[012])?\.pyc')
    if any(not mutable(n.decode()) and pyc.fullmatch(n.decode()) is None for n in names if n):
        raise RuntimeError('Unvalidated untracked source after genuine execution')
    return head


def closure(code, *, genuine=False, allow_data=False):
    actual = git(code, 'rev-parse', 'HEAD').decode().strip()
    if actual != os.environ['GITHUB_SHA']:
        if not genuine or not allow_data:
            raise RuntimeError('Actual candidate checkout differs from authenticated source')
        genuine_data_head(code, os.environ['GITHUB_SHA'])
        actual = os.environ['GITHUB_SHA']
    if Path(__file__).resolve() != code / 'tools/operating_resource_bootstrap.py':
        raise RuntimeError('Bootstrap must execute the actual installed source path')
    manifest_raw = regular_bytes(code / 'tools/cloud-seed-integrity.json')
    seed_names = SEED_CONTRACTS.get(sha(manifest_raw))
    if seed_names is None:
        raise RuntimeError('Immutable seed integrity manifest changed')
    manifest = json.loads(manifest_raw)
    if (manifest.get('schema_version') != 'cloud-seed-code-integrity-v1'
            or set(manifest.get('files', {})) != seed_names):
        raise RuntimeError('Unsupported immutable seed dependency inventory')
    names = sorted(set(FILES) | {'tools/' + name for name in seed_names} | ({GENUINE_WORKFLOW, 'tools/genuine_case_recovery.py'} if genuine else set()))
    values = {}
    for name in names:
        path = code / name
        if path.resolve() != path or any(p.is_symlink() for p in path.parents if p != code):
            raise RuntimeError('Symlink source dependency rejected')
        raw = regular_bytes(path)
        # Check the immutable Git blob's declared size before reading its body.
        length = git(code, 'cat-file', '-s', actual + ':' + name).decode().strip()
        if not length.isdigit() or int(length) > LIMIT:
            raise RuntimeError('Source Git blob exceeds its bound')
        committed = git(code, 'show', actual + ':' + name)
        if raw != committed:
            raise RuntimeError('Actual executable dependency differs from committed source')
        values[name] = {'sha256': sha(raw), 'bytes': len(raw)}
    if (values['tools/operating_diagnostic.py']['sha256'] != P5
            or values['tools/diagnostic_resources.py']['sha256'] != RESOURCE
            or any(values['tools/' + k]['sha256'] != v for k, v in manifest['files'].items())):
        raise RuntimeError('Immutable seed dependency changed')
    result = {'commit': actual, 'tree': git(code, 'rev-parse', actual + '^{tree}').decode().strip(),
            'files': values, 'source_closure_sha256': sha(canonical(values))}
    if genuine:
        driver = genuine_driver(code, actual)
        result['genuine_driver'] = {'workflow': GENUINE_WORKFLOW, 'sha256': sha(driver), 'bytes': len(driver)}
    return result


def root_directory(args):
    base = ROOT_BASE
    if base != Path('/var/tmp'):
        raise RuntimeError('Only the approved fixed report base is supported')
    for path in (Path('/'), Path('/var'), base):
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or path.resolve() != path
                or (mode != 0o1777 if path == base else bool(mode & 0o022))):
            raise RuntimeError('Unprotected fixed report ancestry')
    report = base / f'nfl-operating-{args.run_id}-{args.sample}'
    report.mkdir(mode=0o755)  # Exclusive: retries never inherit an old report.
    info = report.lstat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o755:
        raise RuntimeError('New report directory is not protected by root ownership')
    return report


def write_report(directory, name, value):
    raw = canonical(value) + b'\n'
    if len(raw) > LIMIT:
        raise RuntimeError('Outer execution report exceeds its bound')
    descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    os.fchmod(descriptor, 0o644)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return sha(raw)


def transport_approval():
    path = Path(os.environ['RUNNER_TEMP']).resolve() / 'operating-artifact-approval.json'
    if path.is_symlink() or path.resolve() != path:
        raise RuntimeError('Unsupported artifact approval path')
    raw = regular_bytes(path)
    expected = os.environ.get('OPERATING_ARTIFACT_APPROVAL_SHA256', '')
    if not re.fullmatch('[0-9a-f]{64}', expected) or sha(raw) != expected:
        raise RuntimeError('Actual artifact approval differs from the fixed reviewed identity')
    # Strict schema/content/transport checks remain in the exact worker helper.
    # This independent boundary binds actual input bytes, never an ADMITTED flag.
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


def checked_resource_module(code):
    path = code / 'tools/diagnostic_resources.py'
    if sha(regular_bytes(path)) != RESOURCE:
        raise RuntimeError('Unexpected resource supervisor bytes')
    spec = importlib.util.spec_from_file_location('operating_exact_resource_supervisor', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manager_properties(args, fields):
    if any(k in os.environ for k in ('DBUS_SYSTEM_BUS_ADDRESS','SYSTEMD_BUS_ADDRESS')):
        raise RuntimeError('System-manager bus overrides are unsupported')
    raw=subprocess.check_output(['/usr/bin/systemctl','--system','--no-pager','show',args.unit,
        *['--property='+key for key in fields]],text=True,stderr=subprocess.PIPE,timeout=10)
    rows=[line.split('=',1) for line in raw.splitlines()]
    if (len(raw.encode())>8192 or any(len(row)!=2 for row in rows)
            or len(rows)!=len(fields) or len({row[0] for row in rows})!=len(rows)
            or {row[0] for row in rows}!=set(fields)):
        raise RuntimeError('Bounded system-manager properties unavailable')
    return dict(rows)


def manager_peak(raw):
    if not isinstance(raw,str) or re.fullmatch(r'0|[1-9][0-9]{0,19}',raw) is None or int(raw)>=2**64-1:
        raise RuntimeError('Cached kernel memory peak unavailable')
    return int(raw)


def unit_setup(args, module):
    values = [line.split() for line in Path('/proc/meminfo').read_text().splitlines()
              if line.startswith('MemTotal:')]
    if (len(values) != 1 or len(values[0]) != 3 or values[0][2] != 'kB'
            or int(values[0][1]) * 1024 != args.memory_max):
        raise RuntimeError('Finite service bound must equal actual physical MemTotal')
    mount, current, ancestors = module.resolve()
    if os.statvfs(mount).f_flag & os.ST_RDONLY:
        raise RuntimeError('Read-only cgroup mount; no setup attempted')
    unit = mount / 'system.slice' / args.unit
    if current != unit / 'supervisor':
        raise RuntimeError('Unexpected unit/supervisor cgroup membership')
    command = ['/usr/bin/systemctl', 'show', args.unit, '--property=ControlGroup',
               '--property=Delegate', '--property=DelegateSubgroup', '--property=User',
               '--property=MemoryMax', '--property=MemorySwapMax', '--property=RuntimeMaxUSec']
    genuine=getattr(args,'genuine_case',False)
    expected={'ControlGroup':'/system.slice/'+args.unit,'Delegate':'yes','DelegateSubgroup':'supervisor',
              'User':'root','MemoryMax':str(args.memory_max),'MemorySwapMax':'0','RuntimeMaxUSec':'20min 30s'}
    if genuine:
        fixed={**expected,'RemainAfterExit':'yes','MemoryAccounting':'yes'}
        observed=manager_properties(args,tuple(fixed)+('InvocationID','ExecMainPID','MemoryPeak','MemorySwapPeak'))
        if ({key:observed[key] for key in fixed}!=fixed
                or re.fullmatch('[0-9a-f]{32}',observed['InvocationID']) is None
                or int(observed['InvocationID'],16)==0 or observed['ExecMainPID']!=str(os.getpid())):
            raise RuntimeError('Genuine unit manager invocation or root process differs')
        initial_peak=manager_peak(observed['MemoryPeak']);manager_peak(observed['MemorySwapPeak'])
    else:
        properties=subprocess.check_output(command,text=True)
        observed=dict(line.split('=',1) for line in properties.splitlines())
        if observed!=expected:
            raise RuntimeError('Transient service differs from exact operating contract')
    scopes = []
    for parent in ancestors:
        for path in (parent, parent / 'cgroup.procs', parent / 'cgroup.threads'):
            info = path.lstat()
            if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
                raise RuntimeError('Unprotected cgroup accounting ancestry')
        if parent != current and parent != unit and 'memory' not in (parent / 'cgroup.subtree_control').read_text().split():
            raise RuntimeError('Ancestor controller unavailable; no global setup allowed')
    if ((unit / 'cgroup.procs').read_text().strip()
            or os.getxattr(unit, 'user.delegate') != b'1'
            or (unit / 'memory.max').read_text().strip() != str(args.memory_max)
            or (unit / 'memory.swap.max').read_text().strip() != '0'
            or 'memory' not in (unit / 'cgroup.controllers').read_text().split()):
        raise RuntimeError('Unsupported delegated finite resource unit')
    control = unit / 'cgroup.subtree_control'
    if 'memory' not in control.read_text().split():
        control.write_text('+memory')  # Sole controller write, inside this exact fresh unit.
    if 'memory' not in control.read_text().split():
        raise RuntimeError('Unit-local memory delegation failed')
    for path in (mount, unit, current):
        info = path.stat()
        scopes.append({'path': str(path), 'device': info.st_dev, 'inode': info.st_ino})
    result={'unit':args.unit,'scopes':scopes,'cgroup_namespace':os.readlink('/proc/self/ns/cgroup'),
            'mount_namespace':os.readlink('/proc/self/ns/mnt'),'properties':observed}
    if genuine:
        result['kernel_lifetime_backend']={'version':LIFETIME_BACKEND,'invocation_id':observed['InvocationID'],
            'exec_main_pid':os.getpid(),'initial_memory_peak_bytes':initial_peak}
    return result


def commands(args, directory):
    code = args.code
    temp = Path(os.environ['RUNNER_TEMP']).resolve()
    work = temp / ('nfl-operating-' + str(args.sample))
    root, result = work / 'fixture', work / 'RESULT.json'
    if root.exists() or result.exists():
        raise RuntimeError('New exact fixture and result required; no implicit retry')
    worker = ['/usr/bin/env']
    for name in ROOT_GIT:
        worker.extend(('-u', name))
    worker.extend((sys.executable, str(code / 'tools/operating_campaign.py'), 'job',
                   '--code', str(code), '--root', str(root), '--result', str(result),
                   '--sample-number', str(args.sample)))
    critical = list(dict.fromkeys([str(Path(p).resolve()) for p in args.critical_path] +
        [str(code), str(temp), str(work), str(directory), '/tmp', pwd.getpwuid(args.uid).pw_dir,
         str(Path(sys.executable).resolve()), str(Path(sys.base_prefix).resolve())] +
        ([] if args.capability_only else [str(temp / 'operating-artifact-approval.json')])))
    if getattr(args, 'genuine_case', False):
        critical = list(dict.fromkeys(critical + [str(code.parent), str(code.parent / 'production')]))
        if not args.capability_only:
            driver = genuine_driver(code, os.environ['GITHUB_SHA'])
            target = directory / 'GENUINE_CONTROLLER.py'
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(driver); stream.flush(); os.fsync(stream.fileno())
            worker = ['/usr/bin/env']
            for name in ROOT_GIT: worker.extend(('-u', name))
            worker.extend(('GITHUB_WORKSPACE=' + str(code.parent), sys.executable, '-P', str(target)))
        critical = [p for p in critical if p != str(temp / 'operating-artifact-approval.json')]
    supervisor = [sys.executable, '-P', str(code / 'tools/diagnostic_resources.py'), 'supervise',
                  '--purpose', 'operating', '--sample', str(args.sample), '--timeout', '1200',
                  '--run-id', str(args.run_id), '--uid', str(args.uid), '--gid', str(args.gid),
                  '--exclusive-runner', '--output', str(directory / 'RESOURCE.json')]
    for path in critical:
        supervisor.extend(('--critical-path', path))
    if args.capability_only:
        return supervisor + ['--preflight-only'], [], critical
    return supervisor + ['--'] + worker, worker, critical


def protected_resource(directory):
    path = directory / 'RESOURCE.json'
    info = path.lstat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('Resource report is not root-protected')
    raw = regular_bytes(path)
    return json.loads(raw), {'sha256': sha(raw), 'bytes': len(raw)}


def run(args):
    started = time.monotonic()
    directory = None
    child = None
    record = {'schema_version': 'operating-root-execution-v1', 'status': 'PREFLIGHT_STOP',
              'resource_verdict': 'UNKNOWN', 'run_id': args.run_id, 'sample': args.sample,
              'mode': 'capability' if args.capability_only else 'campaign',
              'root_uid': os.geteuid(), 'worker_uid': args.uid, 'worker_gid': args.gid,
              'purpose': 'operating', 'planning_seconds': 960, 'timeout_seconds': 1200}
    try:
        environment(args)
        genuine = getattr(args, 'genuine_case', False)
        if genuine:
            record.update(mode='genuine-capability' if args.capability_only else 'genuine',
                          boundary='FINITE_COMPLETE_UPDATER_UNIT_NOT_GHA_JOB_OR_WHOLE_VM')
        record.update(run_attempt=int(os.environ['GITHUB_RUN_ATTEMPT']),
                      repository=os.environ['GITHUB_REPOSITORY'],
                      repository_id=int(os.environ['GITHUB_REPOSITORY_ID']),
                      actor_id=int(os.environ['GITHUB_ACTOR_ID']),
                      event=os.environ['GITHUB_EVENT_NAME'], branch=os.environ['GITHUB_REF_NAME'],
                      workflow_path=GENUINE_WORKFLOW if genuine else WORKFLOW, workflow_ref=os.environ['GITHUB_WORKFLOW_REF'])
        directory = root_directory(args)
        approval = None if args.capability_only or genuine else transport_approval()
        record['transport_approval'] = ('NOT_REQUIRED_GENUINE_CASE' if genuine else 'NOT_REQUIRED_CAPABILITY_ONLY' if args.capability_only else approval)
        initial = closure(args.code, genuine=True) if genuine else closure(args.code)
        record['source'] = initial
        record['seed_manifest_sha256'] = None if args.capability_only or genuine else os.environ['SEED_MANIFEST_SHA256']
        record['runtime_image'] = {'os': os.environ['ImageOS'], 'version': os.environ['ImageVersion']}
        module = checked_resource_module(args.code)
        argv, worker, critical = commands(args, directory)
        record['cgroup'] = unit_setup(args, module)
        record.update(supervisor_argv=argv, supervisor_argv_sha256=sha(canonical(argv)),
                      worker_argv=worker or None, worker_argv_sha256=sha(canonical(worker)) if worker else None,
                      critical_paths=critical)
        # The immutable supervisor drops uid/gid/caps and sets no_new_privs.
        # Root's Git exception is removed by /usr/bin/env before worker Python.
        # Worker performs approved online Actions proofs/retrieval, destroys its
        # read token, THEN installs the inherited network guard before fixture work.
        child = subprocess.Popen(argv, close_fds=True)
        record['resource_supervisor_pid'] = child.pid
        record['resource_supervisor_returncode'] = child.wait(timeout=1220)
        resource, binding = protected_resource(directory)
        record['resource_report'] = binding
        if not args.capability_only and not genuine and transport_approval() != approval:
            raise RuntimeError('Artifact approval changed during supervision')
        final_source = closure(args.code, genuine=True, allow_data=True) if genuine else closure(args.code)
        if final_source != initial:
            raise RuntimeError('Execution source closure changed during supervision')
        if genuine:
            record['execution_data_head'] = genuine_data_head(args.code, initial['commit'])
        record['resource_report'] = binding
        if (resource.get('source') != initial['commit']
                or resource.get('purpose') != 'operating'
                or resource.get('run_id') != args.run_id or resource.get('sample') != args.sample
                or resource.get('harness_sha256') != P5
                or resource.get('seed_manifest_sha256') != record['seed_manifest_sha256']):
            raise RuntimeError('Actual resource report differs from execution binding')
        record['resource_p5_harness_sha256'] = resource['harness_sha256']
        if args.capability_only:
            ready = (resource.get('status') == 'CAPABILITY_READY'
                     and resource.get('resource_verdict') == 'NOT_RUN_CAPABILITY_ONLY'
                     and resource.get('complete_tree') is True
                     and not resource.get('cleanup_error')
                     and record['resource_supervisor_returncode'] == 0)
            record.update(status='CAPABILITY_READY' if ready else 'CAPABILITY_STOP',
                          workload_started=False,
                          resource_verdict='NOT_RUN_CAPABILITY_ONLY' if ready else 'UNKNOWN')
            return 0 if ready else 3
        verdict = module.report_verdict(resource)
        if record['resource_supervisor_returncode'] != 0 or verdict != 'PASS':
            record.update(status='RESOURCE_OR_WORKLOAD_FAILED', resource_verdict=verdict)
            return 2
        expected = str(Path(record['cgroup']['scopes'][1]['path']) /
                       f'nfl-diagnostic-{args.run_id}-{args.sample}-{child.pid}')
        if expected not in resource.get('kernel_peaks', {}):
            raise RuntimeError('Actual monitored leaf does not match supervisor process')
        if genuine:
            record['genuine_result'] = genuine_result(args)
            record.update(status='GENUINE_COMPLETE_LIFETIME_READ_REQUIRED',
                          resource_verdict='UNKNOWN', supervised_subprocess_verdict='PASS',
                          complete_tree=resource['complete_tree'], privilege_drop_verified=resource['privilege_drop_verified'],
                          monitored_leaf_path=expected)
            return 0
        record.update(status='COMPLETE_RESOURCE_REVIEW_STILL_REQUIRES_JOB_TIMESTAMPS',
                      resource_verdict='PASS', complete_tree=resource['complete_tree'],
                      privilege_drop_verified=resource['privilege_drop_verified'],
                      monitored_leaf_path=expected)
        return 0
    except BaseException as error:
        # No environment/token dump, subprocess output, or arbitrary argv echo.
        record.update(status='BOOTSTRAP_STOP', resource_verdict='UNKNOWN',
                      failure_class=type(error).__name__)
        return 3
    finally:
        if child is not None and child.poll() is None:
            record['unfinished_supervisor'] = True
            record['resource_verdict'] = 'UNKNOWN'
            record['status'] = 'EXACT_UNIT_CLEANUP_REQUIRED'
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            # Worker descendants are killed by this exact systemd unit's
            # KillMode=control-group on main-process exit. External workflow
            # readback must confirm inactivity; no complete-tree claim here.
        record['bootstrap_seconds'] = time.monotonic() - started
        if directory is not None:
            # This directory has root-owned protected ancestry, not a runner-writable parent.
            write_report(directory, 'OUTER_EXECUTION_BINDING.json', record)
            os.chmod(directory / 'OUTER_EXECUTION_BINDING.json', 0o644)


def genuine_result(args):
    # FINAL has no inner run/generation fields. Its exact bytes and tar are
    # bound to the root's actual run/source/driver, never a new artifact PASS.
    out = Path(os.environ['RUNNER_TEMP']) / 'nfl-real-production-case'
    raw = regular_bytes(out / 'FINAL.json', 65536);value = json.loads(raw)
    if (not isinstance(value, dict) or value.get('status') != 'COMPLETE_GENUINE_NONDEPLOY_CASE'
            or value.get('source') != os.environ['GITHUB_SHA']
            or value.get('operating_qualification') != 'NOT_ESTABLISHED' or value.get('resource_verdict') != 'UNKNOWN'
            or type(value.get('artifact_tar_bytes')) is not int or not 0 < value['artifact_tar_bytes'] <= 127 * 1024**2
            or not re.fullmatch('[0-9a-f]{64}', str(value.get('artifact_tar_sha256', '')))):
        raise RuntimeError('Genuine controller did not complete or used another source')
    path=out/'release-review.tar';before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != value['artifact_tar_bytes']:
        raise RuntimeError('Actual genuine tar size/type differs')
    digest=hashlib.sha256();size=0
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(65536),b''):
            size+=len(block)
            if size>value['artifact_tar_bytes']:raise RuntimeError('Genuine tar grew beyond its bound')
            digest.update(block)
    after=path.lstat();keys=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
    if (any(getattr(before,k)!=getattr(after,k) for k in keys)
            or size!=value['artifact_tar_bytes'] or digest.hexdigest()!=value['artifact_tar_sha256']
            or regular_bytes(out/'FINAL.json',65536)!=raw):
        raise RuntimeError('Genuine FINAL/tar changed during verification')
    return {'sha256':sha(raw),'bytes':len(raw),'tar_sha256':digest.hexdigest(),'tar_bytes':size,
            'source':value['source'],'root_run_id':args.run_id,'driver_sha256':GENUINE_DRIVER}


def read_unit_lifetime(args):
    environment(args)
    directory = ROOT_BASE / f'nfl-operating-{args.run_id}-{args.sample}'
    for p in (Path('/'), Path('/var'), ROOT_BASE, directory):
        info = p.lstat()
        if p.resolve() != p or info.st_uid != 0 or not stat.S_ISDIR(info.st_mode) or (stat.S_IMODE(info.st_mode) != 0o1777 if p == ROOT_BASE else bool(info.st_mode & 0o022)):
            raise RuntimeError('Unprotected lifetime witness ancestry')
    path = directory / 'OUTER_EXECUTION_BINDING.json';info = path.lstat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('Unprotected root witness')
    outer = json.loads(regular_bytes(path));resource, binding = protected_resource(directory)
    current = closure(args.code, genuine=True, allow_data=True)
    if (outer.get('source') != current or outer.get('run_id') != args.run_id or outer.get('sample') != args.sample
            or outer.get('run_attempt') != 1 or outer.get('root_uid') != 0 or outer.get('worker_uid') != args.uid
            or outer.get('workflow_path') != GENUINE_WORKFLOW or outer.get('resource_report') != binding
            or outer.get('mode') not in ('genuine','genuine-capability')
            or outer.get('repository') != REPOSITORY or outer.get('repository_id') != 1411185749
            or outer.get('actor_id') != 208912933
            or outer.get('seed_manifest_sha256') is not None
            or outer.get('status') not in ('GENUINE_COMPLETE_LIFETIME_READ_REQUIRED', 'CAPABILITY_READY')):
        raise RuntimeError('Wrong source/run or incomplete genuine root witness')
    cg = outer['cgroup'];unit = Path(cg['scopes'][1]['path'])
    if (os.readlink('/proc/self/ns/cgroup') != cg['cgroup_namespace']
            or os.readlink('/proc/self/ns/mnt') != cg['mount_namespace']):
        raise RuntimeError('Reader differs from witnessed host namespaces')
    backend=cg.get('kernel_lifetime_backend',{})
    if (set(backend)!={'version','invocation_id','exec_main_pid','initial_memory_peak_bytes'}
            or backend['version']!=LIFETIME_BACKEND
            or re.fullmatch('[0-9a-f]{32}',str(backend.get('invocation_id',''))) is None
            or backend['invocation_id']!=cg['properties'].get('InvocationID')
            or str(backend['exec_main_pid'])!=cg['properties'].get('ExecMainPID')
            or type(backend['initial_memory_peak_bytes']) is not int or backend['initial_memory_peak_bytes']<0):
        raise RuntimeError('Source-bound cached-kernel invocation witness unavailable')
    fields=('ControlGroup','ActiveState','SubState','MainPID','RemainAfterExit','MemoryAccounting','MemoryMax','MemorySwapMax','Result','ExecMainStatus','InvocationID','MemoryPeak','MemorySwapPeak')
    state=manager_properties(args,fields)
    expected=dict(zip(fields[:11],('/system.slice/'+args.unit,'active','exited','0','yes','yes',str(args.memory_max),'0','success','0',backend['invocation_id'])))
    if state['ControlGroup']=='':
        expected['ControlGroup']=''  # Same manager invocation may have pruned its empty cgroup.
    if {key:state[key] for key in expected}!=expected:
        raise RuntimeError('Exact exited manager invocation differs')
    peak=manager_peak(state['MemoryPeak']);swap=manager_peak(state['MemorySwapPeak'])
    lower=[backend['initial_memory_peak_bytes']]
    if outer.get('mode')!='genuine-capability':
        leaf=str(unit/f"nfl-diagnostic-{args.run_id}-{args.sample}-{outer.get('resource_supervisor_pid')}")
        if outer.get('monitored_leaf_path')!=leaf:
            raise RuntimeError('Recorded supervised leaf identity differs')
        for key in (str(unit),leaf):
            bound=resource.get('kernel_peaks',{}).get(key,{}).get('kernel_peak')
            if type(bound) is not int or bound<0:
                raise RuntimeError('Recorded unit/leaf peak missing')
            lower.append(bound)
    if peak<max(lower):raise RuntimeError('Cached kernel peak below recorded accounting')
    module=checked_resource_module(args.code)
    capable=outer.get('mode') == 'genuine-capability'
    if not capable and (module.report_verdict(resource) != 'PASS' or outer.get('supervised_subprocess_verdict') != 'PASS'):
        raise RuntimeError('Full supervised update did not pass')
    if capable and (resource.get('status') != 'CAPABILITY_READY' or resource.get('resource_verdict') != 'NOT_RUN_CAPABILITY_ONLY'):
        raise RuntimeError('Genuine capability preflight did not pass')
    if not capable and genuine_result(args) != outer.get('genuine_result'):
        raise RuntimeError('Genuine FINAL/tar changed after root execution')
    if manager_properties(args,fields)!=state:
        raise RuntimeError('Cached manager identity or peak changed during read')
    if os.readlink('/proc/self/ns/cgroup')!=cg['cgroup_namespace'] or os.readlink('/proc/self/ns/mnt')!=cg['mount_namespace']:
        raise RuntimeError('Reader namespace changed during manager read')
    safe=module.peak_ok(args.memory_max,peak) and swap==0
    value={'schema_version':'genuine-systemd-kernel-lifetime-v1','backend':LIFETIME_BACKEND,'source':current['commit'],'run_id':args.run_id,'sample':args.sample,
           'status':'CAPABILITY_READY_NO_WORKLOAD' if capable else 'COMPLETE_UPDATER_UNIT_LIFETIME_OBSERVED',
           'unit_lifetime_peak_bytes':peak,'unit_swap_peak_bytes':swap,'unit_limit_bytes':args.memory_max,
           'unit_invocation_sha256':sha(backend['invocation_id'].encode()),'oom_scope':'SUPERVISED_CORE_EVENT_DELTAS_AND_SUCCESSFUL_UNIT_EXIT',
           'unit_headroom':'PASS' if safe else 'FAIL','resource_verdict':'UNKNOWN','whole_gha_job_memory':'NOT_MEASURED',
           'whole_vm_memory':'NOT_MEASURED','excludes':['GHA_setup','Worker_and_other_GHA_processes','GHA_post_actions'],
           'root_witness_sha256':sha(regular_bytes(path))}
    raw=canonical(value);print('GENUINE_UNIT_LIFETIME_JSON='+raw.decode());print('GENUINE_UNIT_LIFETIME_SHA256='+sha(raw))
    return 0 if safe else 2


if __name__ == '__main__':
    args = arguments()
    raise SystemExit(read_unit_lifetime(args) if args.read_unit_lifetime else run(args))
