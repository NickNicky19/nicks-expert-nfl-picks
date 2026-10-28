"""PROPOSED ONLY: one approved transient-service resource setup, then supervise.

No setup occurs on import or --help. This file is not permission to execute sudo.
The only controller write is +memory inside the exact delegated service cgroup.
The separate supervisor retains all workload/accounting/cleanup checks and drops
the workload to the declared runner UID/GID before executing its command.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--unit',required=True)
    p.add_argument('--memory-max',type=int,required=True)
    p.add_argument('--uid',type=int,required=True)
    p.add_argument('--gid',type=int,required=True)
    p.add_argument('--run-id',type=int,required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--critical-path',action='append',required=True)
    p.add_argument('--timeout',type=int,default=18000)
    p.add_argument('--preflight-only',action='store_true')
    return p


def checked_args(argv):
    cut=argv.index('--') if '--' in argv else len(argv)
    args=parser().parse_args(argv[:cut])
    args.command=argv[cut+1:] if cut<len(argv) else []
    if args.run_id<=0 or args.unit!='nfl-seedprep-'+str(args.run_id)+'.service':
        raise RuntimeError('Expected exact run-bound transient unit')
    if args.uid<=0 or args.gid<=0 or args.memory_max<=0 or not 0<args.timeout<=18000:
        raise RuntimeError('Invalid worker, memory or preparation timeout')
    if not args.preflight_only and not args.command:
        raise RuntimeError('No preparation workload command')
    return args


def root_owned(path):
    if path.is_symlink() or path.resolve()!=path:
        raise RuntimeError('Unexpected resource-control symlink')
    value=path.stat()
    if value.st_uid!=0 or value.st_mode & (stat.S_IWGRP|stat.S_IWOTH):
        raise RuntimeError('Resource control not protected by root ownership')


def checked_module():
    if os.geteuid()!=0:
        raise RuntimeError('Explicit approved root bootstrap required')
    if any(os.environ.get(key)!=value for key,value in (
        ('GITHUB_ACTIONS','true'),('RUNNER_ENVIRONMENT','github-hosted'),
        ('GITHUB_RUN_ATTEMPT','1'))):
        raise RuntimeError('First-attempt GitHub-hosted job required')
    checkout=Path(os.environ['GITHUB_WORKSPACE']).resolve()
    # The root service must read only this runner-owned checkout. Do not write
    # global Git configuration or inherit caller-selected alternate Git roots.
    for key in tuple(os.environ):
        if key.startswith('GIT_'):
            del os.environ[key]
    os.environ.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',
        GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='safe.directory',
        GIT_CONFIG_VALUE_0=str(checkout))
    actual=subprocess.check_output(['/usr/bin/git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
    if actual!=os.environ.get('GITHUB_SHA'):
        raise RuntimeError('Actual installer checkout identity mismatch')
    here=Path(__file__).resolve()
    if here!=checkout/'tools/cloud_seed_resource_bootstrap.py':
        raise RuntimeError('Bootstrap must run from the actual installer checkout')
    for name in ('cloud_seed_resource_bootstrap.py','diagnostic_resources.py','operating_diagnostic.py'):
        path=checkout/'tools'/name
        expected=subprocess.check_output(['/usr/bin/git','-C',str(checkout),'show',actual+':tools/'+name])
        if path.is_symlink() or path.read_bytes()!=expected:
            raise RuntimeError('Installer dependency differs from its actual Git source: '+name)
    path=checkout/'tools/diagnostic_resources.py'
    spec=importlib.util.spec_from_file_location('seed_resource_supervisor',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bootstrap(args):
    if os.environ.get('GITHUB_RUN_ID')!=str(args.run_id):
        raise RuntimeError('Run identity mismatch')
    module=checked_module()
    memory=[line.split() for line in Path('/proc/meminfo').read_text().splitlines()
        if line.startswith('MemTotal:')]
    if len(memory)!=1 or len(memory[0])!=3 or memory[0][2]!='kB' or int(memory[0][1])*1024!=args.memory_max:
        raise RuntimeError('Finite service limit must equal observed physical MemTotal')
    mount,current,ancestors=module.resolve()
    expected=mount/'system.slice'/args.unit
    if current!=expected/'supervisor':
        raise RuntimeError('Expected exact delegated unit/supervisor cgroup')
    unit=expected
    properties=subprocess.check_output([
        '/usr/bin/systemctl','show',args.unit,'--property=ControlGroup',
        '--property=Delegate','--property=DelegateSubgroup','--property=User',
        '--property=MemoryMax','--property=MemorySwapMax'],text=True)
    values=dict(line.split('=',1) for line in properties.splitlines())
    if values!={'ControlGroup':'/system.slice/'+args.unit,'Delegate':'yes',
        'DelegateSubgroup':'supervisor','User':'root','MemoryMax':str(args.memory_max),
        'MemorySwapMax':'0'}:
        raise RuntimeError('Transient service settings differ from the proposed contract')
    if os.statvfs(mount).f_flag & os.ST_RDONLY:
        raise RuntimeError('Cgroup mount is read-only')
    for parent in ancestors:
        for path in (parent,parent/'cgroup.procs',parent/'cgroup.threads'):
            root_owned(path)
    if (unit/'cgroup.procs').read_text().strip():
        raise RuntimeError('Delegated service inner cgroup is populated')
    if os.getxattr(unit,'user.delegate')!=b'1':
        raise RuntimeError('Systemd delegation marker unavailable')
    if (unit/'memory.max').read_text().strip()!=str(args.memory_max) or (unit/'memory.swap.max').read_text().strip()!='0':
        raise RuntimeError('Actual finite service memory/swap limits mismatch')
    if 'memory' not in (unit/'cgroup.controllers').read_text().split():
        raise RuntimeError('Memory controller not available in delegated service')
    control=unit/'cgroup.subtree_control'
    root_owned(control)
    # The sole controller mutation, confined to the exact fresh delegated unit.
    if 'memory' not in control.read_text().split():
        control.write_text('+memory')
    if 'memory' not in control.read_text().split():
        raise RuntimeError('Delegated memory controller did not enable')
    args.purpose='seed-preparation'
    args.sample=0
    args.exclusive_runner=True
    return module.supervise(args)


def main(argv=None):
    args=checked_args(sys.argv[1:] if argv is None else argv)
    try:
        return bootstrap(args)
    except (KeyError,OSError,ValueError,RuntimeError,subprocess.SubprocessError) as err:
        record={'status':'HOSTED_PREFLIGHT_STOP','purpose':'seed-preparation',
            'resource_verdict':'UNKNOWN','reason':type(err).__name__+': '+str(err)}
        print(json.dumps(record,sort_keys=True),file=sys.stderr)
        try:
            output=Path(args.output).resolve()
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(record,sort_keys=True)+'\n')
            output.chmod(0o644)
        except OSError as failure:
            print('Resource failure record unavailable: '+str(failure),file=sys.stderr)
        return 3


if __name__=='__main__':
    raise SystemExit(main())
