"""Closed nonprivileged preservation of one genuine case; never qualification."""
import argparse, gzip, hashlib, io, itertools, json, math, os, re, stat, subprocess, sys, tarfile, types, zlib
from datetime import datetime
from pathlib import Path
source_ci=None
weekly_overlay=None
weekly_static=None
weekly_rankings=None

CONF='NFL-WEB-GENUINE-PRODUCTION-CASE-20261024'
REPO='NickNicky19/nicks-expert-nfl-picks'
REF='refs/heads/upgrade/phase2-reproducible-comparison'
DRIVER='b0776717b8dc98eae6d959a098e7d0926cd164bbce7ebd086ff55520ba5e73c5'
LEGACY_DRIVER='2ee6d870c3bb6c8e667eae3a49cadf22220d6ab21d0c990c8035332d1deadfaf'
WEEKLY_DRIVER='2f4d7f7eac10c4c82a56762929e5d3d8f853493f5b01edbee2925adf158b501e'
PRESENCE_DRIVER='a045d47016a1e4646d6c430c4d73fb672da4f10592498ae9928a78f92a603693'
CURRENT_PRESENCE_DRIVER='0d80a96da370e9d59b1772c7d0a7b07700cd50395926a7d6477ae1da88e3d46d'
STAGED_POLICY_DRIVER='8fe9ca56e45cd64598f78ad859247563de21526c28858ce1ebee81b3758cd7a5'
PRESENCE_CONTRACT='genuine-current-production-controller-v4'
DRIVER_BYTES={LEGACY_DRIVER:30854,WEEKLY_DRIVER:35468,DRIVER:36877,PRESENCE_DRIVER:37167,CURRENT_PRESENCE_DRIVER:37868,STAGED_POLICY_DRIVER:37868}
WORKFLOW='.github/workflows/prepare-diagnostic-seed.yml'
MIB=1024**2
CAP=127*MIB
ENCODED=128*MIB
DECODED=32*MIB
META_CAP=8*MIB
FINAL_CAP=65536
COUNT=20000
SCHEMAS=set('baseline-capture-v2 matchup-inputs-v3 sleeper-selection-offers-v1 forecast-outcomes-v1 forecast-outcomes-v2 descriptive-statistic-outcomes-v1 descriptive-statistic-outcomes-v2 matchup-verification-v1 partial-schedule-baseline-v1 partial-registration-data-integrity-v2 partial-scope-data-integrity-v2 partial-completion-data-integrity-v2 completion-failure-data-integrity-v2 partial-completion-failure-v1 ranked-selection-observation-v1 ranked-selection-completion-v1 ranked-selection-decision-ledger-v1 derived-selection-ledger-v1 rich-scorecard-evidence-v1 selection-publication-run-v1 point-candidate-evaluation-v1 hosting-generation-proof-v1 generation-failure-v1 unqualified-native-preservation-v1 ranked-selection-failure-v1'.split())
LANE=re.compile(r'data/(?:forward|history|verification|offers|outcomes)/')
CACHE=re.compile(r'data/cache/(?:(?:espn_athletes|injury_timeline|stats_[0-9]{4}_[0-9]{2})\.json|(?:stat-keys-fgm-v1|stat-keys-presence-fgm-v2)/stats_[0-9]{4}_(?:0[1-9]|1[0-8])\.json)\Z')
BOARDS={'output/data/'+x+'.json' for x in 'week meta future teams track_record dk_backtest forecast-scorecard offer-capture health release-identity verification-scope game-status matchup-proof'.split()}
META=set('RELEASE_CASE_MANIFEST.json INPUT_DATA_MANIFEST.json OUTPUT_DATA_MANIFEST.json NEW_RECEIPTS_MANIFEST.json PAGES_MEMBERS_MANIFEST.json SOURCE_CI_BINDINGS.json'.split())
STATIC={'app.js','index.html','style.css','reliability-ui.js','recovery.html'}
WEEKLY_JS='weekly-adaptive-overlay.js'
WEEKLY_POINTER='data/weekly-adaptive-overlay.json'
WEEKLY_BODY=re.compile(r'data/weekly-adaptive/[0-9a-f]{64}\.json\Z')
WEEKLY_AUDIT=re.compile(r'data/weekly-adaptive-audit/[0-9a-f]{64}\.json\Z')
WEEKLY_CONTRACT='genuine-current-production-controller-v2'
RANKING_POINTER='data/weekly-selected-rankings.json'
RANKING_CONTRACT='genuine-current-production-controller-v3'
RANKING_CONTRACTS=frozenset((RANKING_CONTRACT,PRESENCE_CONTRACT))
DRIVER_CONTRACTS={LEGACY_DRIVER:None,WEEKLY_DRIVER:WEEKLY_CONTRACT,DRIVER:RANKING_CONTRACT,PRESENCE_DRIVER:PRESENCE_CONTRACT,CURRENT_PRESENCE_DRIVER:PRESENCE_CONTRACT,STAGED_POLICY_DRIVER:PRESENCE_CONTRACT}
REVIEWED_MAIN={WEEKLY_CONTRACT:('315be5e86a1a3a93022b68c453739076487e2077','dfdc11ac312a6a54c79e7379352106c315e13f5f'),
    RANKING_CONTRACT:('89512ed952308dacc1f6a930915ddbcdccd460d9','c88d5b3740c820b30387ec2eaca2b0bceafd9a51'),
    PRESENCE_CONTRACT:('e336bf7a68c32267c3c3eec48892aeadcd03a90e','26c1ca52eb1d9b3610a552ecf63ccd2fab5ad8f8')}
REPORT=re.compile(r'data/selection-grading/(?:latest\.json|hosting\.json|[0-9a-f]{64}/(?:summary|outcomes|rows|rows-[0-9]{4}|manifest|registry|archive)\.json|[0-9a-f]{64}/snapshot-(?:app\.js|index\.html|data_(?:week|meta|verification-scope|forecast-scorecard|health|release-identity)\.json|data_selection-grading_latest\.json))\Z')
SECRET=re.compile(r'\b(?:gh[pousr]_|github_pat_|sk-proj-|AKIA[A-Z0-9]{16}|xox[baprs]-)|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+\S+',re.I)
PRIVATE=re.compile(r'^(?:authorization|proxy[-_]?authorization|cookie|set[-_]?cookie|password|credentials?|tokens?|(?:access|refresh|id|auth|session|bearer)[-_]?tokens?|x[-_]?(?:auth[-_]?token|api[-_]?key)|secret|client[-_]?secret|api[_-]?key|localStorage|device_id|session_id|account_balance)$',re.I)

class Rejected(ValueError):pass
def need(value,code):
    if not value:raise Rejected(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def pairs(items):
    value={}
    for key,item in items:need(key not in value,'DUPLICATE_JSON_KEY');value[key]=item
    return value
def parsed(raw):
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(Rejected('NONFINITE_JSON')))
def safe_name(name):
    return len(name)<=512 and bool(re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',name)) and all(x not in ('.','..') for x in name.split('/'))
def ranking_role(name):
    logical=name[7:] if name.startswith('output/') else name
    return weekly_rankings.public_role(logical) if weekly_rankings is not None else None
def recording_limit(name,kind):
    ranked=ranking_role(name)
    return ranked[1] if ranked is not None else 4*MIB if kind and kind.startswith('weekly_') else ENCODED
def role(name):
    ranked=ranking_role(name)
    if ranked is not None and name.startswith('output/') and safe_name(name):return 'weekly_'+ranked[0]
    if safe_name(name) and WEEKLY_AUDIT.fullmatch(name):return 'weekly_audit'
    if name=='output/'+WEEKLY_POINTER:return 'weekly_pointer'
    if safe_name(name) and name.startswith('output/') and WEEKLY_BODY.fullmatch(name[7:]):return 'weekly_overlay'
    if safe_name(name) and LANE.match(name):
        if name.endswith('.json.gz'):return 'receipt'
        if re.fullmatch(r'\.capture-[a-z0-9_]{8}',name.rsplit('/',1)[-1]):return 'receipt_temporary'
    if safe_name(name) and (CACHE.fullmatch(name) or name in BOARDS):return 'cache_or_board'
    return None
def atomic_json_temp(name):
    return name.rsplit('/',1)[0] in ('data/cache','output/data') and bool(re.fullmatch(r'\.json-[a-z0-9_]{8}',name.rsplit('/',1)[-1]))
def reference(origin,name):
    result={'origin':origin,'logical_path_sha256':sha(name.encode())}
    if role(name) or atomic_json_temp(name):result.update(logical_path=name,physical_path=origin+'/'+name)
    return result
def privacy(value,text):
    need(not SECRET.search(text),'CREDENTIAL_INDICATOR')
    def walk(item):
        if isinstance(item,dict):
            for key,child in item.items():need(not PRIVATE.fullmatch(key),'PRIVATE_FIELD');walk(child)
        elif isinstance(item,list):
            for child in item:walk(child)
    walk(value)
def decoded(raw,receipt=False,object_required=True):
    stream=gzip.GzipFile(fileobj=io.BytesIO(raw)) if raw[:2]==b'\x1f\x8b' else io.BytesIO(raw)
    chunks=[];size=0
    with stream:
        while True:
            try:block=stream.read(min(65536,DECODED+1-size))
            except (EOFError,OSError,zlib.error):raise Rejected('INVALID_OR_INCOMPLETE_GZIP') from None
            if not block:break
            size+=len(block);need(size<=DECODED,'DECODED_BOUND');chunks.append(block)
    text=b''.join(chunks).decode('utf-8');value=parsed(text)
    need(isinstance(value,dict) or not object_required and isinstance(value,list),'JSON_OBJECT');privacy(value,text)
    if receipt:
        need(set(value)=={'payload','payload_sha256'} and isinstance(value['payload'],dict),'RECEIPT_ENVELOPE')
        need(sha(canonical(value['payload']))==value['payload_sha256'],'RECEIPT_DIGEST')
        need(value['payload'].get('schema_version') in SCHEMAS,'RECEIPT_SCHEMA')
        return value['payload']
    return value
def weekly_json(name,raw):
    """Strictly typed preservation; never an original-evidence qualification."""
    ranked=ranking_role(name)
    need(len(raw)<=(ranked[1] if ranked is not None else 4*MIB),'WEEKLY_JSON_BOUND')
    need(raw[:2]!=b'\x1f\x8b','WEEKLY_PLAIN_JSON_REQUIRED')
    if ranked is not None:
        logical=name[7:] if name.startswith('output/') else name
        return weekly_rankings.validate_public_asset(logical,raw)
    value=decoded(raw)
    logical=name[7:] if name.startswith('output/') else name
    if WEEKLY_AUDIT.fullmatch(logical):
        need(set(value)=={'schema_version','website_source_sha','at','policy_file_sha256','authority_kind','human_approval','validation','review'}
            and value['schema_version']=='weekly-public-feed-writer-audit-v1'
            and isinstance(value['website_source_sha'],str) and re.fullmatch('[0-9a-f]{40}',value['website_source_sha'])
            and isinstance(value['policy_file_sha256'],str) and re.fullmatch('[0-9a-f]{64}',value['policy_file_sha256'])
            and value['authority_kind']=='AUTOMATED_REGISTERED_POLICY' and value['human_approval'] is False
            and isinstance(value['validation'],dict) and isinstance(value['review'],dict),'WEEKLY_AUDIT_CONTRACT')
        need(isinstance(value['at'],str) and datetime.fromisoformat(value['at'].replace('Z','+00:00')).tzinfo is not None,'WEEKLY_AUDIT_CLOCK')
        need(logical=='data/weekly-adaptive-audit/'+sha(canonical(value))+'.json','WEEKLY_AUDIT_IDENTITY')
    elif logical==WEEKLY_POINTER:
        need(set(value)=={'schema_version','path','sha256','bytes','display_board_sha256'}
            and value['schema_version']=='weekly-adaptive-overlay-pointer-v1'
            and isinstance(value['sha256'],str) and re.fullmatch('[0-9a-f]{64}',value['sha256'])
            and value['path']=='data/weekly-adaptive/'+value['sha256']+'.json'
            and type(value['bytes']) is int and 0<value['bytes']<=4*MIB
            and isinstance(value['display_board_sha256'],str) and re.fullmatch('[0-9a-f]{64}',value['display_board_sha256']),'WEEKLY_POINTER_CONTRACT')
    else:
        need(WEEKLY_BODY.fullmatch(logical) and value.get('schema_version')=='weekly-adaptive-public-overlay-v1'
            and logical=='data/weekly-adaptive/'+sha(raw)+'.json','WEEKLY_OVERLAY_IDENTITY')
    return value
def weekly_pages(bodies,dispatch):
    """Recheck the exact modern public graph from actual tar bytes."""
    names={n for n in bodies if n==WEEKLY_JS or n==WEEKLY_POINTER or WEEKLY_BODY.fullmatch(n)}
    ranking_present={n for n in bodies if n==RANKING_POINTER or n.startswith('data/weekly-selected-rankings/')}
    if ranking_present:
        need(weekly_rankings is not None,'RANKING_VALIDATOR_NOT_BOUND')
        need(all(ranking_role(n) is not None for n in ranking_present),'RANKING_PUBLIC_ROLE')
        need(WEEKLY_POINTER in names,'RANKING_OVERLAY_REQUIRED')
    if not names:return
    need(WEEKLY_JS in names and weekly_static is not None and bodies[WEEKLY_JS]==weekly_static,'WEEKLY_STATIC_SOURCE')
    if WEEKLY_POINTER not in names:
        need(names=={WEEKLY_JS},'WEEKLY_ORPHAN_BODY')
        return
    need(weekly_overlay is not None,'WEEKLY_VALIDATOR_NOT_BOUND')
    pointer=weekly_json(WEEKLY_POINTER,bodies[WEEKLY_POINTER])
    need(names=={WEEKLY_JS,WEEKLY_POINTER,pointer['path']},'WEEKLY_COMPLETE_GRAPH')
    raw=bodies[pointer['path']]
    need(len(raw)==pointer['bytes'] and sha(raw)==pointer['sha256'],'WEEKLY_DESCRIPTOR_BYTES')
    value=weekly_json(pointer['path'],raw)
    need(value.get('website_source_sha')==dispatch,'WEEKLY_EXECUTED_SOURCE')
    need('data/week.json' in bodies and len(bodies['data/week.json'])<=16*MIB,'WEEKLY_BOARD_DEPENDENCY')
    board_raw=bodies['data/week.json'];board=decoded(board_raw)
    need(pointer['display_board_sha256']==sha(board_raw),'WEEKLY_POINTER_BOARD')
    weekly_overlay.validate_overlay(value,board,sha(board_raw))
    if ranking_present:
        required=weekly_rankings.validate_public_graph({n:bodies[n] for n in ranking_present},board,sha(board_raw),value,
            website_source_sha=dispatch)
        need(required==ranking_present,'RANKING_COMPLETE_GRAPH')
def encoded(path,retain=False,limit=ENCODED):
    initial=path.lstat();need(stat.S_ISREG(initial.st_mode) and not path.is_symlink(),'NONREGULAR_FILE')
    need(initial.st_size<=limit,'ENCODED_BOUND')
    stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK);body=[];digest=hashlib.sha256();size=0
    with os.fdopen(fd,'rb') as stream:
        need(stamp(os.fstat(stream.fileno()))==stamp(initial),'FILE_REPLACED')
        while True:
            block=stream.read(min(65536,limit+1-size))
            if not block:break
            size+=len(block);need(size<=limit,'ENCODED_BOUND');digest.update(block)
            if retain:body.append(block)
        need(size==initial.st_size and stamp(os.fstat(stream.fileno()))==stamp(initial) and stamp(path.lstat())==stamp(initial),'INCOMPLETE_OR_CHANGED_WRITE')
    return {'bytes':size,'sha256':digest.hexdigest(),'mode':stat.S_IMODE(initial.st_mode)},b''.join(body) if retain else None
def candidates(root):
    count=total=0
    for folder in ('data','output/data'):
        base=root/folder
        if not base.exists() and not base.is_symlink():continue
        need(base.is_dir() and not base.is_symlink(),'DATA_ROOT_UNSAFE')
        for directory,dirs,files in os.walk(base,followlinks=False):
            dirs.sort();files.sort();count+=len(dirs);need(count<=COUNT,'INVENTORY_COUNT_BOUND')
            for name in list(dirs):
                path=Path(directory)/name
                if path.is_symlink():
                    dirs.remove(name);yield path.relative_to(root).as_posix(),path,'DIRECTORY_SYMLINK'
            for name in files:
                count+=1;need(count<=COUNT,'INVENTORY_COUNT_BOUND')
                path=Path(directory)/name;logical=path.relative_to(root).as_posix()
                try:
                    size=path.lstat().st_size;total+=size;need(total<=768*MIB,'INVENTORY_BYTES_BOUND')
                    yield logical,path,None
                except OSError:yield logical,path,'UNAVAILABLE_FILE'
def snapshot(roots):
    result={}
    for origin,root in roots:
        for name,path,issue in candidates(root):
            need(issue is None,'BASELINE_NONREGULAR')
            info,_=encoded(path);key=sha(name.encode())
            item=result.setdefault(key,{'logical_path':name if role(name) else None,'versions':{}})
            item['versions'][origin]=info
    return result
def validate_invocation(env,event,head):
    need(not any(key in env for key in ('DBUS_SYSTEM_BUS_ADDRESS','SYSTEMD_BUS_ADDRESS')),'SYSTEM_MANAGER_BUS_OVERRIDE')
    fixed={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_REPOSITORY':REPO,'GITHUB_REPOSITORY_ID':'1411185749','GITHUB_ACTOR_ID':'208912933','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1','GITHUB_REF':REF,'GITHUB_JOB':'genuine-production-case','GITHUB_WORKFLOW_REF':REPO+'/.github/workflows/prepare-diagnostic-seed.yml@'+REF}
    need(all(env.get(k)==v for k,v in fixed.items()),'INVOCATION_CONTEXT')
    dispatch=env.get('GITHUB_SHA','');run=env.get('GITHUB_RUN_ID','')
    need(re.fullmatch('[0-9a-f]{40}',dispatch) and env.get('GITHUB_WORKFLOW_SHA')==dispatch and re.fullmatch('[1-9][0-9]*',run),'SOURCE_RUN_CONTEXT')
    need(event.get('inputs')=={'confirmation':CONF,'storage_approved':CONF,'installed_source':dispatch},'EXACT_THREE_INPUTS')
    need(event.get('repository',{}).get('id')==1411185749 and event['repository'].get('full_name')==REPO and event.get('sender',{}).get('id')==208912933,'EVENT_IDENTITY')
    need(re.fullmatch('[0-9a-f]{40}',head),'ACTUAL_GIT_SOURCE')
    return dispatch,run
def fixed_git(app,*args):
    env={key:value for key,value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_TERMINAL_PROMPT='0')
    result=subprocess.run(['/usr/bin/git','--no-replace-objects','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-C',str(app),*args],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=30)
    need(result.returncode==0 and len(result.stdout)<=DECODED,'FIXED_GIT_REJECTED')
    return result.stdout
def authenticated_bytes(app,dispatch,relative):
    need(relative in ('tools/source_ci.py','tools/genuine_case_recovery.py','tools/weekly_adaptive_overlay.py',
        'tools/weekly_selected_rankings.py','output/weekly-adaptive-overlay.js',WORKFLOW),'FIXED_DEPENDENCY')
    row=fixed_git(app,'ls-tree','-z',dispatch,'--',relative)
    need(row.endswith(b'\0') and row.count(b'\0')==1,'DEPENDENCY_GIT_ENTRY')
    header,name=row[:-1].split(b'\t');mode,kind,oid=header.decode().split()
    need(name.decode()==relative and mode in ('100644','100755') and kind=='blob' and re.fullmatch('[0-9a-f]{40}',oid),'DEPENDENCY_GIT_ROLE')
    length=fixed_git(app,'cat-file','-s',oid).decode().strip()
    need(length.isascii() and length.isdigit() and 0<int(length)<=DECODED,'DEPENDENCY_GIT_BOUND')
    raw=fixed_git(app,'cat-file','blob',oid)
    need(len(raw)==int(length) and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==oid,'DEPENDENCY_GIT_HASH')
    path=app/relative;need(path.resolve()==path,'DEPENDENCY_PATH')
    info,actual=encoded(path,True,DECODED)
    need(actual==raw and ('100755' if info['mode']&stat.S_IXUSR else '100644')==mode,'DEPENDENCY_DIFFERS_FROM_DISPATCH')
    return raw
def checked_source_ci(app,dispatch):
    raw=authenticated_bytes(app,dispatch,'tools/source_ci.py')
    module=types.ModuleType('genuine_verified_source_ci');module.__file__=str(app/'tools/source_ci.py')
    exec(compile(raw,module.__file__,'exec'),module.__dict__)
    return module
def checked_driver(app,dispatch):
    raw=authenticated_bytes(app,dispatch,WORKFLOW)
    start=b'          import datetime as dt, gzip, hashlib, json, math, os, re, resource, signal, stat, subprocess, sys, tarfile, time\n'
    end=b"          if __name__=='__main__':main()\n"
    need(raw.count(start)==1 and raw.count(end)==1,'CLOSED_DRIVER_MARKERS')
    block=raw[raw.index(start):raw.index(end)+len(end)]
    need(all(not row.strip() or row.startswith(b'          ') for row in block.splitlines()),'CLOSED_DRIVER_INDENTATION')
    value=b''.join((row[10:] if row.startswith(b'          ') else b'')+b'\n' for row in block.splitlines())
    digest=sha(value);need(DRIVER_BYTES.get(digest)==len(value),'CLOSED_DRIVER_IDENTITY')
    return digest
def checked_rankings(app,dispatch,overlay_module):
    raw=authenticated_bytes(app,dispatch,'tools/weekly_selected_rankings.py')
    module=types.ModuleType('genuine_verified_weekly_rankings');module.__file__=str(app/'tools/weekly_selected_rankings.py')
    absent=object();prior=sys.modules.get('weekly_adaptive_overlay',absent)
    sys.modules['weekly_adaptive_overlay']=overlay_module
    try:exec(compile(raw,module.__file__,'exec'),module.__dict__)
    finally:
        if prior is absent:del sys.modules['weekly_adaptive_overlay']
        else:sys.modules['weekly_adaptive_overlay']=prior
    need(getattr(module,'overlay',None) is overlay_module,'RANKING_AUTHENTICATED_OVERLAY')
    return module
def allowed_leftover(name,tracked):
    if not safe_name(name):return False
    if source_ci.mutable(name):return True
    base=name.rsplit('/',1)[-1]
    if role(name)=='receipt_temporary':return True
    if any(name.startswith(prefix) for prefix in source_ci.MUTABLE) and re.fullmatch(r'\.json-[a-z0-9_]{8}',base):return True
    if name.startswith(('data/cache/','output/data/')) and re.fullmatch(r'tmp[a-z0-9_]{8}',base):return True
    parts=name.split('/')
    match=re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\.cpython-312\.pyc',base)
    return bool(match and len(parts)>1 and parts[-2]=='__pycache__' and '/'.join([*parts[:-2],match[1]+'.py']) in tracked and name not in tracked)
def source_identity(app):
    # Preservation may observe incomplete data writes; it never turns them into a CI seal.
    current=source_ci.source(app,actual=False)
    for entry in current['files']:
        path=app/entry['path'];source_ci._regular(path,app);info,_=encoded(path,limit=source_ci.FILE_LIMIT)
        mode='100755' if info['mode']&stat.S_IXUSR else '100644'
        need((mode,info['bytes'],info['sha256'])==(entry['mode'],entry['bytes'],entry['sha256']),'ACTUAL_SOURCE_BYTES_CHANGED')
    tracked={entry['path'] for entry in current['files']}
    for raw in source_ci.git(app,'ls-files','--others','-z').split(b'\0'):
        if raw:
            name=raw.decode()
            need(allowed_leftover(name,tracked),'UNTRACKED_EXECUTABLE_SOURCE')
    return current
def context():
    global source_ci,weekly_overlay,weekly_static,weekly_rankings
    need(sys.flags.safe_path,'SAFE_PATH_STARTUP_REQUIRED')
    workspace=Path(os.environ['GITHUB_WORKSPACE']).resolve();app=workspace/'source';prod=workspace/'production'
    need(Path(__file__).resolve()==app/'tools/genuine_case_recovery.py','ACTUAL_HELPER_PATH')
    _,event_raw=encoded(Path(os.environ['GITHUB_EVENT_PATH']),True,131072)
    head=fixed_git(app,'rev-parse','HEAD').decode().strip();dispatch,run=validate_invocation(os.environ,parsed(event_raw),head)
    authenticated_bytes(app,dispatch,'tools/genuine_case_recovery.py')
    source_ci=checked_source_ci(app,dispatch);current=source_identity(app)
    need(current['commit']==head,'ACTUAL_GIT_SOURCE_CHANGED')
    need(source_ci._descendant(app,dispatch,current['commit']),'SOURCE_ANCESTRY')
    original=source_ci.source(app,dispatch,actual=False)
    need(original['source_manifest_sha256']==current['source_manifest_sha256'],'SOURCE_CLOSURE_CHANGED')
    driver=checked_driver(app,dispatch)
    contract=DRIVER_CONTRACTS[driver]
    weekly_rankings=None
    if contract in (WEEKLY_CONTRACT,*RANKING_CONTRACTS):
        weekly_raw=authenticated_bytes(app,dispatch,'tools/weekly_adaptive_overlay.py')
        weekly_overlay=types.ModuleType('genuine_verified_weekly_overlay');weekly_overlay.__file__=str(app/'tools/weekly_adaptive_overlay.py')
        exec(compile(weekly_raw,weekly_overlay.__file__,'exec'),weekly_overlay.__dict__)
        weekly_static=authenticated_bytes(app,dispatch,'output/weekly-adaptive-overlay.js')
        if contract in RANKING_CONTRACTS:
            weekly_rankings=checked_rankings(app,dispatch,weekly_overlay)
    else:weekly_overlay=weekly_static=None
    temp=Path(os.environ['RUNNER_TEMP']);need(temp.is_absolute() and temp.resolve()==temp,'TEMP_ROOT')
    transaction=temp/('nfl-capture-transactions-'+run);state=temp/('nfl-genuine-recovery-'+run)
    need(os.environ.get('TMPDIR')==str(transaction) and transaction.is_dir() and not transaction.is_symlink() and transaction.resolve()==transaction,'PRESTART_TMPDIR')
    need(stat.S_IMODE(transaction.stat().st_mode)==0o700 and transaction.stat().st_uid==os.getuid(),'TRANSACTION_OWNERSHIP')
    return app,prod,transaction,state,{'dispatch_source':dispatch,'executed_commit':current['commit'],'executed_tree':current['tree'],'source_manifest_sha256':current['source_manifest_sha256'],'run_id':run,'driver_sha256':driver}
def inactive_units(run):
    need(not any(key in os.environ for key in ('DBUS_SYSTEM_BUS_ADDRESS','SYSTEMD_BUS_ADDRESS')),'SYSTEM_MANAGER_BUS_OVERRIDE')
    result=[]
    for sample in (1,2):
        unit='nfl-operating-'+run+'-'+str(sample)+'.service'
        fields=('LoadState','ActiveState','SubState','MainPID','ControlPID')
        process=subprocess.run(['/usr/bin/systemctl','--system','--no-pager','show',unit,*['--property='+x for x in fields]],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10)
        need(len(process.stdout)<=8192 and process.returncode in (0,1),'UNIT_STATE_UNAVAILABLE')
        values=dict(line.split('=',1) for line in process.stdout.decode().splitlines())
        need(set(values)==set(fields) and values['LoadState'] in ('loaded','not-found') and values['ActiveState'] in ('inactive','failed') and values['SubState'] in ('dead','failed') and values['MainPID']=='0' and values['ControlPID']=='0','UNIT_NOT_QUIESCENT')
        result.append({'unit':unit,**values})
    return result
def write_new(path,raw):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw)
def baseline(app,prod,transaction,state,identity):
    need(identity['executed_commit']==identity['dispatch_source'] and not any(transaction.iterdir()),'FRESH_BASELINE_REQUIRED')
    state.mkdir(mode=0o700)
    record={'schema_version':'genuine-recovery-baseline-v1','identity':identity,'production_commit':source_ci.git(prod,'rev-parse','HEAD').decode().strip(),'production_tree':source_ci.git(prod,'rev-parse','HEAD^{tree}').decode().strip(),'files':snapshot((('source',app),('production',prod)))}
    raw=canonical(record);need(len(raw)<=META_CAP,'BASELINE_METADATA_BOUND');write_new(state/'BASELINE.json',raw)
    return {'baseline_sha256':sha(raw),'status':'BASELINE_ONLY_NO_CAPTURE','transaction_tmpdir':str(transaction)}
def unchanged(name,info,before):
    versions=before.get(sha(name.encode()),{}).get('versions',{})
    return any(info['sha256']==value['sha256'] and info['bytes']==value['bytes'] for value in versions.values())
def recover(roots,before):
    records=[];queue=[];payload=[];kept=0;by_hash={}
    for origin,root in roots:
        try:
            for name,path,issue in candidates(root):
                item=reference(origin,name)
                try:
                    need(issue is None,issue or 'NONREGULAR_FILE')
                    kind=role(name)
                    info,_=encoded(path,limit=recording_limit(name,kind));item.update(info)
                    if unchanged(name,info,before):continue
                    need(kind is not None,'ATOMIC_JSON_TARGET_UNAVAILABLE' if atomic_json_temp(name) else 'UNCLASSIFIED_ROLE')
                    queue.append((kind,origin,name,path,info,item))
                except (OSError,ValueError,TypeError,KeyError,RecursionError,EOFError) as error:
                    item.update(state='UNAVAILABLE_INVALID_INCOMPLETE_OR_UNCLASSIFIED',reason=str(error) if isinstance(error,Rejected) else type(error).__name__)
                    records.append(item)
                need(len(records)+len(queue)<=COUNT,'RECOVERY_RECORD_COUNT')
        except (OSError,ValueError) as error:records.append({'origin':origin,'state':'UNAVAILABLE_SCAN','reason':str(error) if isinstance(error,Rejected) else type(error).__name__})
    for kind,origin,name,path,info,item in sorted(queue,key=lambda value:(not value[0].startswith('receipt'),value[1],value[2])):
        try:
            info2,raw=encoded(path,True,recording_limit(name,kind));need(info2==info,'INCOMPLETE_OR_CHANGED_WRITE')
            if kind=='receipt_temporary':need(raw[:2]==b'\x1f\x8b','ATOMIC_RECEIPT_GZIP_REQUIRED')
            value=weekly_json(name,raw) if kind.startswith('weekly_') else decoded(raw,kind.startswith('receipt'));item.update(role=kind,schema_version=value.get('schema_version'),state='UNQUALIFIED_PRESERVED')
            if kind.startswith('receipt'):item['payload_sha256']=sha(canonical(value))
            if kind=='receipt_temporary':item['logical_reference_status']='ATOMIC_TEMP_NO_CANONICAL_NATIVE_CREATED'
            match=next((prior for prior in by_hash.get(info['sha256'],[]) if prior[1]==raw),None)
            if match:item['archive_member']=match[0];item['same_physical_bytes_as']=match[0]
            else:
                member='quarantine/recording-'+str(len(payload)).zfill(5)
                cost=512+((len(raw)+511)//512)*512
                need(kept+cost+10240<=CAP-META_CAP-FINAL_CAP,'RECOVERY_CAP')
                payload.append((member,raw));by_hash.setdefault(info['sha256'],[]).append((member,raw));kept+=cost;item['archive_member']=member
        except (OSError,ValueError,TypeError,KeyError,RecursionError,EOFError) as error:
            item.update(state='UNAVAILABLE_INVALID_INCOMPLETE_OR_UNCLASSIFIED',reason=str(error) if isinstance(error,Rejected) else type(error).__name__)
        records.append(item)
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w',format=tarfile.USTAR_FORMAT) as tar:
        for name,raw in payload:
            entry=tarfile.TarInfo(name);entry.size=len(raw);entry.mode=0o600;entry.mtime=0;tar.addfile(entry,io.BytesIO(raw))
    need(stream.tell()<=CAP-META_CAP-FINAL_CAP,'RECOVERY_TAR_BOUND')
    return stream.getvalue(),records
def public_path(name):
    return ranking_role(name) is not None or name in STATIC or name in (WEEKLY_JS,WEEKLY_POINTER) or bool(WEEKLY_BODY.fullmatch(name)) or 'output/'+name in BOARDS-{'output/data/game-status.json','output/data/matchup-proof.json'} or bool(re.fullmatch(r'data/(?:archive|weeks)/[0-9]{4}_w[0-9]{2}\.json',name)) or bool(REPORT.fullmatch(name))
def tar_entries(raw,public=False,expected=None):
    need(len(raw)<=CAP and len(raw)%512==0,'TAR_BOUND')
    items={};seen=set();position=0;pending=None;count=0
    while position+512<=len(raw):
        header=raw[position:position+512]
        if not any(header):
            need(position+1024<=len(raw) and not any(raw[position:]) and pending is None,'TAR_TRAILER')
            return items
        count+=1;need(count<=COUNT*3,'TAR_ENTRY_COUNT')
        try:entry=tarfile.TarInfo.frombuf(header,'utf-8','strict')
        except tarfile.HeaderError:raise Rejected('INVALID_TAR_HEADER') from None
        need(0<=entry.size<=CAP,'TAR_MEMBER_BOUND')
        start=position+512;end=start+entry.size;next_position=start+((entry.size+511)//512)*512
        need(next_position<=len(raw) and not any(raw[end:next_position]),'TAR_MEMBER_BYTES')
        body=raw[start:end];position=next_position
        if entry.type==tarfile.GNUTYPE_LONGNAME:
            need(public and pending is None and entry.name in ('././@LongLink','@LongLink') and 1<=len(body)<=513 and body.endswith(b'\0') and body.count(b'\0')==1,'TAR_LONGNAME_ROLE')
            pending=body[:-1].decode('utf-8');continue
        name=pending if pending is not None else entry.name;pending=None
        name=name.removeprefix('./')
        if entry.isdir():
            name=name.rstrip('/')
            need(public and (name in ('','.') or safe_name(name) and any(path.startswith(name+'/') for path in (expected or {}))),'TAR_DIRECTORY_ROLE')
            continue
        need(entry.type in (tarfile.REGTYPE,tarfile.AREGTYPE) and safe_name(name) and name not in seen,'TAR_REGULAR_ROLE')
        seen.add(name);items[name]=body;need(len(items)<=COUNT,'TAR_FILE_COUNT')
    raise Rejected('TAR_TERMINATOR_MISSING')
def controller_archive(raw,dispatch,status,*,driver=None):
    entries=tar_entries(raw)
    need(META<=set(entries),'CONTROLLER_METADATA_ROLES')
    meta={name:decoded(entries[name],object_required=False) for name in META}
    need(all(isinstance(meta[name],dict) for name in META-{'NEW_RECEIPTS_MANIFEST.json'}) and isinstance(meta['NEW_RECEIPTS_MANIFEST.json'],list),'CONTROLLER_METADATA_TYPES')
    case=meta['RELEASE_CASE_MANIFEST.json']
    need(case.get('schema_version')=='genuine-current-production-case-v1' and case.get('source')==dispatch and case.get('status')==status and meta['INPUT_DATA_MANIFEST.json'].get('source')==dispatch,'CONTROLLER_METADATA_SOURCE')
    contract=case.get('controller_contract')
    modern=contract in (WEEKLY_CONTRACT,*RANKING_CONTRACTS)
    need('controller_contract' not in case or modern,'CONTROLLER_CONTRACT')
    if driver is not None:
        need(driver in DRIVER_CONTRACTS and contract==DRIVER_CONTRACTS[driver],'CONTROLLER_SOURCE_CONTRACT')
    if modern:
        need((case.get('reviewed_main_base'),case.get('reviewed_main_source_tree'))==REVIEWED_MAIN[contract],'CONTROLLER_REVIEWED_MAIN_SOURCE')
    outputs=meta['OUTPUT_DATA_MANIFEST.json'];after=outputs['after'];representations=outputs['representations']
    receipts={}
    for item in meta['NEW_RECEIPTS_MANIFEST.json']:
        name=item['path'];need(name not in receipts and role(name)=='receipt','CONTROLLER_RECEIPT_INDEX');receipts[name]=item
    actual=set()
    same=lambda body,info:isinstance(info,dict) and info.get('bytes')==len(body) and info.get('sha256')==sha(body)
    for name,body in entries.items():
        if name in META or name=='public-pages.tar':continue
        if name.startswith('receipts/'):
            logical=name[len('receipts/'):];need(logical in receipts,'CONTROLLER_UNINDEXED_RECEIPT')
            payload=decoded(body,True);need(same(body,receipts[logical]) and same(body,after[logical]) and payload['schema_version']==receipts[logical]['schema_version'],'CONTROLLER_RECEIPT_BYTES');actual.add(logical)
        elif name.startswith('mutable/'):
            logical=name[len('mutable/'):]
            ranked=ranking_role(logical)
            need(ranked is None or contract in RANKING_CONTRACTS,'RANKING_CONTROLLER_REQUIRED')
            weekly=ranked is not None or bool(WEEKLY_AUDIT.fullmatch(logical)) or logical=='output/'+WEEKLY_POINTER or logical.startswith('output/') and bool(WEEKLY_BODY.fullmatch(logical[7:]))
            allowed=bool(CACHE.fullmatch(logical)) or logical in ('output/data/game-status.json','output/data/matchup-proof.json','output/data/selection-grading/hosting.json') or logical.startswith('output/') and public_path(logical[7:]) or bool(WEEKLY_AUDIT.fullmatch(logical))
            nested_cache=logical.startswith(('data/cache/stat-keys-fgm-v1/','data/cache/stat-keys-presence-fgm-v2/'))
            need(not nested_cache or contract==PRESENCE_CONTRACT,'PRESENCE_CONTROLLER_REQUIRED')
            need(allowed and (not weekly or modern),'CONTROLLER_MUTABLE_ROLE')
            weekly_json(logical,body) if weekly else decoded(body)
            need(same(body,after[logical]) and same(body,representations[logical]) and representations[logical]['storage']==name,'CONTROLLER_MUTABLE_BYTES')
        else:raise Rejected('CONTROLLER_UNCLASSIFIED_MEMBER')
    need(actual==set(receipts),'CONTROLLER_RECEIPT_MEMBERSHIP')
    pages=meta['PAGES_MEMBERS_MANIFEST.json']
    need(len(pages)<=COUNT and all(public_path(name) for name in pages),'CONTROLLER_PAGES_ROLES')
    if 'public-pages.tar' in entries:
        bodies=tar_entries(entries['public-pages.tar'],True,pages)
        need(set(bodies)==set(pages) and all(same(body,pages[name]) for name,body in bodies.items()),'CONTROLLER_PAGES_MEMBERSHIP')
        if any(ranking_role(n) is not None for n in bodies):need(contract in RANKING_CONTRACTS,'RANKING_CONTROLLER_REQUIRED')
        if any(n==WEEKLY_JS or n==WEEKLY_POINTER or WEEKLY_BODY.fullmatch(n) or ranking_role(n) is not None for n in bodies):
            need(modern,'WEEKLY_CONTROLLER_REQUIRED');weekly_pages(bodies,dispatch)
    else:need(status!='COMPLETE_GENUINE_NONDEPLOY_CASE','CONTROLLER_COMPLETE_PAGES_MISSING')
    if status=='COMPLETE_GENUINE_NONDEPLOY_CASE':
        for logical,item in representations.items():
            storage=item['storage']
            if storage.startswith('public-pages.tar::'):
                name=storage.split('::',1)[1]
                need(logical=='output/'+name and name in pages and item['sha256']==pages[name]['sha256'] and item['bytes']==pages[name]['bytes'],'CONTROLLER_PAGE_REFERENCE')
            else:need(storage in entries and storage=='mutable/'+logical,'CONTROLLER_MUTABLE_REFERENCE')
    return meta
def controller(out,dispatch,*,driver=None):
    report={'status':'UNAVAILABLE','reason':'MISSING_FINAL'};final_raw=None
    try:
        _,raw=encoded(out/'FINAL.json',True,FINAL_CAP);value=decoded(raw)
        allowed={'status','source','artifact_tar_bytes','artifact_tar_sha256','new_receipts','operating_qualification','resource_verdict','failure_type','controller_seconds_including_retention'}
        need(set(value)<=allowed and value.get('operating_qualification')=='NOT_ESTABLISHED' and value.get('resource_verdict')=='UNKNOWN','CONTROLLER_FINAL_CONTRACT')
        need(bool(re.fullmatch('[A-Z0-9_]{1,80}',value.get('status',''))),'CONTROLLER_STATUS')
        need(value.get('source',dispatch)==dispatch,'CONTROLLER_SOURCE')
        if 'failure_type' in value:need(bool(re.fullmatch('[A-Za-z0-9_]{1,80}',value['failure_type'])),'CONTROLLER_FAILURE_TYPE')
        for key in ('new_receipts','artifact_tar_bytes'):
            if key in value:need(type(value[key]) is int and 0<=value[key]<=CAP,'CONTROLLER_INTEGER')
        seconds=value.get('controller_seconds_including_retention')
        need(type(seconds) in (int,float) and math.isfinite(seconds) and 0<=seconds<=3600,'CONTROLLER_SECONDS')
        final_raw=raw;report={'status':value['status'],'final_sha256':sha(raw)}
        info,archive=encoded(out/'release-review.tar',True,CAP)
        need(value.get('source')==dispatch and info['bytes']==value.get('artifact_tar_bytes') and info['sha256']==value.get('artifact_tar_sha256'),'CONTROLLER_TAR_BINDING')
        controller_archive(archive,dispatch,value['status'],driver=driver)
        report['tar']=info
        return report,out/'release-review.tar',final_raw
    except (OSError,ValueError,TypeError,KeyError,RecursionError,EOFError) as error:
        report['tar_or_final_unavailable']=str(error) if isinstance(error,Rejected) else type(error).__name__
        return report,None,final_raw
def transaction_roots(transaction):
    roots=[];issues=[];children=list(itertools.islice(transaction.iterdir(),33))
    if len(children)>32:return [],[{'state':'UNAVAILABLE_TRANSACTION_COUNT_BOUND'}]
    children.sort()
    for child in children:
        if re.fullmatch(r'phase2-coherent-generation-[A-Za-z0-9_-]{1,80}',child.name) and child.is_dir() and not child.is_symlink():
            generation=child/'generation'
            if generation.is_dir() and not generation.is_symlink():roots.append(('transactions/'+child.name+'/generation',generation));continue
        issues.append({'transaction_entry_sha256':sha(child.name.encode()),'state':'UNAVAILABLE_UNCLASSIFIED_TRANSACTION_ENTRY'})
    return roots,issues
def collect(app,prod,transaction,state,identity):
    units=inactive_units(identity['run_id'])
    need(state.is_dir() and not state.is_symlink() and state.resolve()==state,'RECOVERY_STATE')
    _,baseline_raw=encoded(state/'BASELINE.json',True,META_CAP);before=parsed(baseline_raw)
    need(before.get('schema_version')=='genuine-recovery-baseline-v1' and before['identity']['dispatch_source']==identity['dispatch_source'] and before['identity']['run_id']==identity['run_id'] and before['identity']['source_manifest_sha256']==identity['source_manifest_sha256'],'BASELINE_BINDING')
    need(source_ci.git(prod,'rev-parse','HEAD').decode().strip()==before['production_commit'],'PRODUCTION_BASELINE_CHANGED')
    out=Path(os.environ['RUNNER_TEMP'])/'nfl-real-production-case'
    parent,original,final_raw=controller(out,identity['dispatch_source'],driver=identity['driver_sha256'])
    if parent['status']=='COMPLETE_GENUINE_NONDEPLOY_CASE' and original:
        return {'status':'CONTROLLER_SUCCESS_UNCHANGED','artifact_path':str(original),'artifact_sha256':parent['tar']['sha256'],'artifact_bytes':parent['tar']['bytes'],'operating_qualification':'NOT_ESTABLISHED'}
    try:roots,issues=transaction_roots(transaction)
    except OSError:roots,issues=[],[{'state':'UNAVAILABLE_TRANSACTION_DIRECTORY'}]
    recordings,records=recover([('source',app),*roots],before['files'])
    metadata={'schema_version':'genuine-failure-recovery-v1','claim':'UNQUALIFIED_PRESERVATION_ONLY_NEVER_COMPLETION','operating_qualification':'NOT_ESTABLISHED','resource_verdict':'UNKNOWN','identity':identity,'baseline':before,'baseline_sha256':sha(baseline_raw),'units':units,'controller':parent,'records':records,'transaction_issues':issues,'durability_limit':'ONLY_FILES_STILL_PRESENT_AFTER_QUIESCENCE; DELETED_OR_IN_MEMORY_BYTES_UNAVAILABLE','recordings_sha256':sha(recordings)}
    original_raw=None;metadata['controller_export']='OMITTED_NO_MATCHED_CONTROLLER'
    if original:
        try:
            info,raw=encoded(original,True,CAP);need(info==parent['tar'],'CONTROLLER_EXPORT_CHANGED')
            original_raw=raw
        except (OSError,ValueError):metadata['controller_export']='UNAVAILABLE_CONTROLLER_CHANGED'
    files=export_files(metadata,recordings,original_raw,final_raw)
    export=state/'EXPORT';export.mkdir(mode=0o700)
    for name,raw in files.items():write_new(export/name,raw)
    need({path.name for path in export.iterdir()}==set(files),'CLOSED_EXPORT_MEMBERS')
    for name,raw in files.items():
        info,_=encoded(export/name,limit=CAP);need(info['bytes']==len(raw) and info['sha256']==sha(raw),'EXPORT_WRITE_CHANGED')
    return {'status':'FAILURE_EVIDENCE_ONLY','artifact_path':str(export),'artifact_bytes':sum(map(len,files.values())),'recordings_sha256':sha(recordings),'controller_final_available':final_raw is not None,'operating_qualification':'NOT_ESTABLISHED'}
def export_files(metadata,recordings,original_raw=None,final_raw=None):
    metadata=dict(metadata);meta=canonical(metadata)
    if original_raw is not None:
        if len(recordings)+len(meta)+len(final_raw or b'')+len(original_raw)+1024<=CAP:
            metadata['controller_export']='EXACT_MATCHED_CONTROLLER_TAR'
        else:original_raw=None;metadata['controller_export']='OMITTED_TOTAL_CAP_PRESERVING_NEW_RECORDINGS'
    meta=canonical(metadata)
    if len(meta)>META_CAP:
        meta=canonical({'schema_version':'genuine-failure-recovery-v1','claim':'UNQUALIFIED_PRESERVATION_ONLY_NEVER_COMPLETION','status':'METADATA_BOUND_INCOMPLETE','full_metadata_sha256':sha(meta),'baseline_sha256':metadata['baseline_sha256'],'recordings_sha256':sha(recordings),'identity':metadata['identity'],'controller_export':metadata['controller_export']})
    files={'failure-first-recordings.tar':recordings,'RECOVERY.json':meta}
    if original_raw is not None:files['controller-release-review.tar']=original_raw
    if final_raw is not None:files['controller-FINAL.json']=final_raw
    need(sum(map(len,files.values()))<=CAP,'TOTAL_EXPORT_CAP')
    return files
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('baseline','collect'));args=parser.parse_args()
    result=(baseline if args.action=='baseline' else collect)(*context())
    print('GENUINE_RECOVERY_JSON='+canonical(result).decode())
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
            for key in ('artifact_path','artifact_bytes','status','transaction_tmpdir'):
                if key in result:stream.write(key+'='+str(result[key])+'\n')
if __name__=='__main__':
    try:main()
    except (OSError,ValueError,TypeError,KeyError,EOFError) as error:
        print('GENUINE_RECOVERY_REJECTED='+ (str(error) if isinstance(error,Rejected) else type(error).__name__),file=sys.stderr);raise SystemExit(3)
