"""Preserve default R0; extend its observations only for current-history misses.

Reads an installed source checkout and retained public Git objects. All builds,
cache refreshes, receipts and response bodies stay in a fresh private run root.
This command never publishes/copies output back or edits a source checkout.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import gzip
import time

from classic_model_v1 import MODEL, ORIGINAL_MODEL, ORIGINAL_SOURCE, ENGINE, SHADOW_PROCEDURE, contract
from classic_source_replay_v1 import Inputs

PROCEDURE = SHADOW_PROCEDURE
MAX_COPY_BYTES = 512 << 20
MAX_COPY_FILES = 20000
PAIR_WALL_SECONDS = 900

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def sha(raw): return hashlib.sha256(raw).hexdigest()
def clock(): return datetime.now(timezone.utc).isoformat()

def copy_tree(source, target):
    """Bounded ordinary files only. No links to any mutable original."""
    source, target = Path(source), Path(target)
    if source.is_symlink():raise ValueError('STAGING_SYMLINK')
    files, total = [], 0
    if not source.exists(): return
    for path in sorted(source.rglob("*")):
        if path.is_symlink(): raise ValueError("STAGING_SYMLINK")
        if not path.is_file(): continue
        if "__pycache__" in path.parts or path.suffix == ".pyc": continue
        size = path.stat().st_size; total += size; files.append(path)
        if total > MAX_COPY_BYTES or len(files) > MAX_COPY_FILES: raise ValueError("STAGING_BOUND")
    for path in files:
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)

def original_blob(repository, name):
    args = ["git", "--no-replace-objects", "-C", str(repository)]
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1")
    oid = subprocess.check_output([*args, "rev-parse", ORIGINAL_SOURCE + ":" + name], env=env).decode().strip()
    raw = subprocess.check_output([*args, "cat-file", "blob", oid], env=env)
    if len(raw) > 2 << 20 or hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != oid:
        raise ValueError("ORIGINAL_GIT_BLOB_IDENTITY")
    return raw

def export_original_state(repository,target):
    """Exact bootstrap data objects, never an unmarked corrected filesystem."""
    args=['git','--no-replace-objects','-C',str(repository)]
    env=dict(os.environ,GIT_OPTIONAL_LOCKS='0',GIT_NO_LAZY_FETCH='1')
    entries=subprocess.check_output([*args,'ls-tree','-r','-z',ORIGINAL_SOURCE,'--','data/cache','output/data'],env=env).split(b'\0')
    count=total=0
    for entry in entries:
        if not entry:continue
        metadata,name=entry.split(b'\t',1);mode,kind,oid=metadata.decode().split();name=name.decode()
        if mode!='100644'or kind!='blob'or not name.startswith(('data/cache/','output/data/'))or '..'in Path(name).parts:raise ValueError('ORIGINAL_STATE_OBJECT_SCOPE')
        raw=subprocess.check_output([*args,'cat-file','blob',oid],env=env);count+=1;total+=len(raw)
        if total>MAX_COPY_BYTES or count>MAX_COPY_FILES:raise ValueError('ORIGINAL_STATE_BOUND')
        if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=oid:raise ValueError('ORIGINAL_STATE_OBJECT_IDENTITY')
        path=Path(target)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    if not count:raise ValueError('ORIGINAL_STATE_OBJECTS_REQUIRED')

def seed(source, run, repository, prior_r0=None):
    source, run = Path(source).resolve(), Path(run).resolve()
    current = contract(source)
    if run.exists() or run.is_relative_to(source): raise ValueError("FRESH_PRIVATE_RUN_ROOT_REQUIRED")
    if prior_r0 is None and (source/'data/classic-r0-shadow/latest.json').exists():
        pointer=json.loads((source/'data/classic-r0-shadow/latest.json').read_bytes())
        name=pointer.get('path','')
        import re
        if not re.fullmatch('[a-f0-9]{64}/state',name):raise ValueError('R0_POINTER_SCOPE')
        prior_r0=source/'data/classic-r0-shadow'/name
        if sha((prior_r0.parent/'PAIR.json').read_bytes())!=pointer.get('pair_sha256'):raise ValueError('R0_POINTER_BINDING')
    if prior_r0 is None:
        previous = source / "output/data/week.json"
        if previous.exists() and json.loads(previous.read_bytes()).get("execution_model") is not None:
            raise ValueError("PRIOR_ORIGINAL_R0_STATE_REQUIRED")
    else:
        prior_r0 = Path(prior_r0).resolve()
        qualification = json.loads((prior_r0.parent / "PAIR.json").read_bytes())
        if qualification.get("state") != "STAGED_PAIR_COMPLETE" or qualification.get("original_model") != ORIGINAL_MODEL:
            raise ValueError("PRIOR_R0_PAIR_REQUIRED")
        previous = prior_r0 / "output/data/week.json"
        if sha(previous.read_bytes()) != qualification["original_board_sha256"]:
            raise ValueError("PRIOR_R0_BOARD_CHANGED")
        if cache_digest(prior_r0)!=qualification['original_cache_sha256']:
            raise ValueError('PRIOR_R0_CACHE_CHANGED')
    # Resolve every original blob before creating a run or touching copied state.
    names = [*ENGINE, "tools/reliability.py"]
    originals = {name: original_blob(repository, name) for name in names}
    run.mkdir(mode=0o700, parents=True)
    before = run / "before"
    for lane in ["output/data", "data/cache"]:
        copy_tree(source / lane, before / lane)
    (run/'BEFORE.json').write_bytes(canonical(inventory(before)))
    for label in ["original", "current"]:
        stage = run / label
        for lane in ["pull", "tools", "config", "schemas"]:
            copy_tree(source / lane, stage / lane)
        copy_tree(before, stage)
    original = run / "original"
    if prior_r0 is None:
        bootstrap=run/'bootstrap-original-state';export_original_state(repository,bootstrap)
        for stage in [original,run/'current']:
            for lane in ['output/data','data/cache']:
                shutil.rmtree(stage/lane,ignore_errors=True);copy_tree(bootstrap/lane,stage/lane)
    # Corrected normalized caches are never original R0 inputs.
    shutil.rmtree(original/'data/cache/stat-keys-fgm-v1',ignore_errors=True)
    if prior_r0 is not None:
        # Preserve the original default procedure's own evolving cache/state.
        for lane in ["output/data","data/cache"]:
            shutil.rmtree(original / lane, ignore_errors=True)
            copy_tree(prior_r0 / lane, original / lane)
        for name in ['espn_athletes.json','injury_timeline.json']:
            prior=prior_r0/'data/cache'/name
            if prior.exists():shutil.copyfile(prior,run/'current/data/cache'/name)
    for name, raw in originals.items():
        path = original / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    (run/'ORIGINAL_SOURCE.json').write_bytes(canonical({name:sha(raw)for name,raw in originals.items()}))
    (run/'SEEDS.json').write_bytes(canonical({name:inventory(run/name)for name in ['original','current']}))
    # Raw public Git code is preserved exactly. Its old receipts remain in the
    # source checkout; the fresh original capture writes only inside this run.
    return current

def inventory(root):
    value={};total=0
    for lane in ['output/data','data/cache']:
        base=Path(root)/lane
        if base.is_symlink():raise ValueError('STATE_SYMLINK')
        for path in sorted(base.rglob('*'))if base.exists()else[]:
            if path.is_symlink():raise ValueError('STATE_SYMLINK')
            if not path.is_file():continue
            raw=path.read_bytes();total+=len(raw)
            if total>MAX_COPY_BYTES or len(value)>=MAX_COPY_FILES:raise ValueError('STATE_BOUND')
            value[path.relative_to(root).as_posix()]=sha(raw)
    return value

def cache_digest(root):
    return sha(canonical({name:value for name,value in inventory(root).items()if name.startswith('data/cache/')}))

def confined(path,root):
    path,root=Path(path),Path(root).resolve()
    if not path.resolve().is_relative_to(root):raise ValueError('OUTPUT_PATH_SCOPE')
    for parent in [path,*path.parents]:
        if parent==root.parent:break
        if parent.is_symlink():raise ValueError('OUTPUT_PATH_SYMLINK')

def worker(root, directory, phase, mode):
    root = Path(root).resolve()
    sys.path[:0] = [str(root / "pull"), str(root / "tools")]
    import build
    import books
    import news
    import sources
    import reliability
    previous_path=root/'output/data/week.json'
    previous=reliability.load_json(previous_path)if previous_path.exists()else{}
    if phase == "record":
        hashes = reliability.engine_hashes(root)  # strict original code profile
    else:
        contract(root)  # strict eight-file corrected profile
    allowed=[]
    if phase=='extend':
        parent=json.loads((root.parent/'original/WORKER.json').read_bytes())
        original_board=reliability.load_json(root.parent/'original/output/data/week.json')
        grouped={}
        for event in parent['cache_events']:
            grouped.setdefault((event['season'],event['week']),[]).append(event['cache_hit'])
        allowed=[key for key,hits in grouped.items()if all(hits)and 2000<=key[0]<=original_board['season']and 1<=key[1]<=18
                 and(key[0]<original_board['season']or key[1]<original_board['week'])]
    inputs = Inputs(directory, phase, fetch=sources.get_json if phase in {'record','extend'}else None,allowed_stats_periods=allowed)
    fgm_trace={'projections':{},'stats':{}}
    cache_events=[]
    original_stats,original_projection=build.week_stats,build.projections
    def summarize(rows):
        stats=[row.get('stats',row)for row in rows.values()]
        return dict(rows=len(stats),fgm_present=sum('fgm'in row and row['fgm']is not None for row in stats),
                    fgm_normalized_zero=sum(row.get('fgm')==0 for row in stats))
    def stats_trace(season,week,refresh):
        cache=build.CACHE if phase=='record'else build.CACHE/build.STATS_CACHE_VERSION
        cache_events.append(dict(season=season,week=week,refresh=refresh,
            cache_hit=(cache/f'stats_{season}_{week:02d}.json').exists()and not refresh))
        rows=original_stats(season,week,refresh)
        fgm_trace['stats'][str(season)+':'+str(week)]=summarize(rows);return rows
    def projection_trace(season,week):
        rows=original_projection(season,week)
        fgm_trace['projections'][str(season)+':'+str(week)]=summarize(rows);return rows
    build.week_stats,build.projections=stats_trace,projection_trace
    try:
        with inputs.install(sources, [build, books, news]):
            build.run()  # Exact deployed default: current/recent refresh only.
    finally:
        build.week_stats,build.projections=original_stats,original_projection
    inputs.qualified()
    provenance = inputs.finish()
    board_path, meta_path = root / "output/data/week.json", root / "output/data/meta.json"
    board, meta = reliability.load_json(board_path), reliability.load_json(meta_path)
    if phase == "record":
        if "execution_model" in board: raise ValueError("ORIGINAL_BOARD_CANNOT_INHERIT_CURRENT_MODEL")
        native, health = reliability.capture(board, meta, root, datetime.now(timezone.utc), hashes, mode=mode)
    else:
        execution = contract(root)
        bind_reference_origins(board,previous)
        board["execution_model"] = meta["execution_model"] = execution
        reliability.atomic_json(board_path, board); reliability.atomic_json(meta_path, meta)
        native, health = reliability.capture_profile(board, meta, root, datetime.now(timezone.utc), model=MODEL, mode=mode)
    result = dict(schema_version="classic-build-worker-v1", phase=phase, model=ORIGINAL_MODEL if phase == "record" else MODEL,
                  source_inputs=provenance, native_receipt=str(native.relative_to(root)),
                  native_sha256=sha(native.read_bytes()), board_sha256=sha(board_path.read_bytes()),
                  completed_at=clock(), procedure=PROCEDURE, health=health)
    result['normalized_fgm_presence']=fgm_trace
    result['cache_events']=cache_events
    result['additional_allowed_stats_periods']=[list(key)for key in sorted(allowed)]
    (root / "WORKER.json").write_bytes(canonical(result))
    return result

def bind_reference_origins(board,previous):
    """Annotate origins after the unmodified builder, without changing forecasts."""
    if (previous.get('season'),previous.get('week'))!=(board['season'],board['week']):previous={}
    generated=datetime.fromisoformat(board['generated_at'].replace('Z','+00:00'))
    games={g['id']:g for g in board['games']}
    old_players={p['id']:p for p in previous.get('players',[])}
    old_games={g['id']:g for g in previous.get('games',[])}
    old_default=previous.get('execution_model',{}).get('model',ORIGINAL_MODEL)
    if old_default not in {MODEL,ORIGINAL_MODEL}:raise ValueError('UNKNOWN_INHERITED_REFERENCE_MODEL')
    def started(game):
        return game['state']!='pre'or datetime.fromisoformat(game['kickoff'].replace('Z','+00:00'))<=generated
    for player in board['players']:
        old=old_players.get(player['id'])
        inherited=old and old.get('game_id')==player['game_id']and started(games[player['game_id']])
        origin=old.get('reference_model',old_default)if inherited else MODEL
        if origin not in {MODEL,ORIGINAL_MODEL}:raise ValueError('UNKNOWN_INHERITED_REFERENCE_MODEL')
        player['reference_model']=origin
    for game in board['games']:
        old=old_games.get(game['id'])
        inherited=old and old.get('ours')and started(game)
        origin=old.get('reference_model',old_default)if inherited else MODEL
        if origin not in {MODEL,ORIGINAL_MODEL}:raise ValueError('UNKNOWN_INHERITED_REFERENCE_MODEL')
        game['reference_model']=origin
    players={p['id']:p for p in board['players']}
    for side in board['picks'].values():
        for item in side:item['reference_model']=players[item['player_id']]['reference_model']

def run_pair(source, run, repository, *, mode="replay", prior_r0=None):
    if mode not in {"live", "replay"}: raise ValueError("CAPTURE_MODE")
    source, run = Path(source).resolve(), Path(run).resolve()
    deadline=time.monotonic()+PAIR_WALL_SECONDS
    current = seed(source, run, repository, prior_r0)
    script = Path(__file__).resolve()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_OPTIONAL_LOCKS="0")
    # Each interpreter imports its own exact source and own module globals.
    # Neither run overrides the original default refresh policy.
    (run/'inputs').mkdir()
    for stage, phase in [("original", "record"), ("current", "extend")]:
        child_env = dict(environment)
        if phase == "record": child_env["GITHUB_SHA"] = ORIGINAL_SOURCE
        if phase=='extend':copy_tree(run/'inputs/original',run/'inputs/current')
        command = [sys.executable, "-B", str(script), "--worker", str(run / stage), "--inputs", str(run / "inputs" / stage), "--phase", phase, "--mode", mode]
        with (run / (stage + ".log")).open("w") as log:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('PAIR_WALL_BUDGET')
            subprocess.run(command, env=child_env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=remaining)
    original, corrected = [json.loads((run / stage / "WORKER.json").read_bytes()) for stage in ["original", "current"]]
    if original["source_inputs"]["input_index_sha256"] != corrected["source_inputs"]["parent_index_sha256"]:
        raise ValueError("PAIR_INPUT_INDEX_CHANGED")
    original_raw=(run/'inputs/original/INDEX.json').read_bytes()
    index_raw = (run / "inputs/current/INDEX.json").read_bytes()
    if sha(original_raw)!=original['source_inputs']['input_index_sha256']or sha(index_raw)!=corrected['source_inputs']['input_index_sha256']:raise ValueError('PAIR_INPUT_INDEX_CHANGED')
    original_rows=json.loads(original_raw)['rows'];current_rows=json.loads(index_raw)['rows']
    if any(current_rows.get(key)!=value for key,value in original_rows.items()):raise ValueError('ORIGINAL_OBSERVATIONS_CHANGED')
    captures=[]
    for stage,info in [('original',original),('current',corrected)]:
        path=run/stage/info['native_receipt']
        if sha(path.read_bytes())!=info['native_sha256']:raise ValueError('PAIR_NATIVE_CHANGED')
        captures.append(json.loads(gzip.decompress(path.read_bytes()))['payload'])
    key=lambda row:(row['season'],row['week'],row['game_id'],row['player_id'],row['category'])
    old_scope={key(row)for row in captures[0]['rows']};current_scope={key(row)for row in captures[1]['rows']}
    # Preserve incomplete work on any failure; no success marker before both
    # real captures exist. No refresh clock or replay clock can be supplied.
    result = dict(schema_version="classic-build-pair-v1", state="STAGED_PAIR_COMPLETE", mode=mode,
                  model=MODEL, current_execution=current, original_model=ORIGINAL_MODEL,
                  original_engine_source=ORIGINAL_SOURCE, original_procedure=PROCEDURE,
                  original_source_inventory_sha256=sha((run/'ORIGINAL_SOURCE.json').read_bytes()),
                  original_cache_sha256=cache_digest(run/'original'),
                  wrapper_source_sha=os.environ.get('GITHUB_SHA'),
                  original_board_sha256=original["board_sha256"], current_board_sha256=corrected["board_sha256"],
                  original_native_sha256=original["native_sha256"], current_native_sha256=corrected["native_sha256"],
                  input_index_sha256=sha(index_raw), completed_at=clock(),
                  original_input_index_sha256=sha(original_raw),complete_input_sets_identical=False,
                  seed_inventory_sha256=sha((run/'SEEDS.json').read_bytes()),
                  additional_current_source_observations=corrected['source_inputs']['additional_observations'],
                  paired_pregame_rows=len(old_scope&current_scope),original_only_pregame_rows=len(old_scope-current_scope),
                  current_only_pregame_rows=len(current_scope-old_scope),
                  normalized_fgm_presence=dict(original=original['normalized_fgm_presence'],current=corrected['normalized_fgm_presence']),
                  source_checkout_written=False, public_output_applied=False, deployed=False,
                  raw_responses="PRIVATE_TRANSIENT_DO_NOT_COMMIT_OR_PUBLISH",
                  claim="STAGED_EXECUTION_AND_LOCAL_CAPTURE; NOT_HOSTED_OPERATING_OR_DEPLOYMENT_ACCEPTANCE")
    (run / "PAIR.json").write_bytes(canonical(result))
    return result

def install_pair_outputs(source,run):
    """Explicit data-only handoff after paired validation; never publishes Git.

    The outer workflow's current-source/output fences are still mandatory.
    Raw source responses and private logs are never copied into the checkout.
    """
    import reliability
    source,run=Path(source).resolve(),Path(run).resolve()
    result=json.loads((run/'PAIR.json').read_bytes())
    if result.get('state')!='STAGED_PAIR_COMPLETE' or result.get('current_execution')!=contract(source):raise ValueError('STAGED_PAIR_CONTRACT')
    if inventory(source)!=json.loads((run/'BEFORE.json').read_bytes()):raise ValueError('SOURCE_DATA_CHANGED_SINCE_SEED')
    if sha((run/'inputs/current/INDEX.json').read_bytes())!=result['input_index_sha256']:raise ValueError('PAIR_INPUT_INDEX_CHANGED')
    if sha((run/'inputs/original/INDEX.json').read_bytes())!=result['original_input_index_sha256']:raise ValueError('ORIGINAL_OBSERVATIONS_CHANGED')
    if sha((run/'ORIGINAL_SOURCE.json').read_bytes())!=result['original_source_inventory_sha256']:raise ValueError('ORIGINAL_SOURCE_BINDING')
    for stage in ['original','current']:
        board=run/stage/'output/data/week.json'
        if sha(board.read_bytes())!=result[stage+'_board_sha256']:raise ValueError('PAIR_BOARD_CHANGED')
        worker_info=json.loads((run/stage/'WORKER.json').read_bytes())
        path=(run/stage/worker_info['native_receipt'])
        if not path.resolve().is_relative_to(run/stage)or path.is_symlink()or sha(path.read_bytes())!=result[stage+'_native_sha256']:raise ValueError('PAIR_NATIVE_CHANGED')
    shadow=source/'data/classic-r0-shadow'/result['input_index_sha256']
    confined(shadow,source)
    # Create-only original shadow state. Retain only derived forecast state and
    # its native receipt; the full request-response corpus stays private.
    for lane in ['week.json','meta.json','track_record.json','archive','weeks']:
        path=run/'original/output/data'/lane
        if not path.exists():continue
        files=list(path.rglob('*'))if path.is_dir()else[path]
        for file in files:
            if not file.is_file():continue
            target=shadow/'state/output/data'/file.relative_to(run/'original/output/data')
            confined(target,source)
            immutable_copy(file,target)
    old_info=json.loads((run/'original/WORKER.json').read_bytes())
    immutable_copy(run/'original'/old_info['native_receipt'],shadow/'native.json.gz')
    immutable_copy(run/'PAIR.json',shadow/'PAIR.json')
    immutable_copy(run/'ORIGINAL_SOURCE.json',shadow/'ORIGINAL_SOURCE.json')
    # Original default-refresh cache continuity is independent of the current
    # normalization cache; old source checkout caches are never overwritten.
    for file in sorted((run/'original/data/cache').rglob('*')):
        if file.is_file():
            target=shadow/'state/data/cache'/file.relative_to(run/'original/data/cache')
            confined(target,source);immutable_copy(file,target)
    # Current captures have their distinct lane; every old receipt/cache stays.
    current_info=json.loads((run/'current/WORKER.json').read_bytes())
    confined(source/current_info['native_receipt'],source)
    immutable_copy(run/'current'/current_info['native_receipt'],source/current_info['native_receipt'])
    for lane in ['data/cache/stat-keys-fgm-v1','output/data']:
        root=run/'current'/lane
        for file in sorted(root.rglob('*'))if root.exists()else[]:
            if file.is_symlink():raise ValueError('STAGED_OUTPUT_SYMLINK')
            if not file.is_file():continue
            target=source/lane/file.relative_to(root)
            confined(target,source)
            if 'grading-history'in target.parts:immutable_copy(file,target)
            else:atomic_copy(file,target)
    reliability.atomic_json(source/'data/classic-r0-shadow/latest.json',dict(path=shadow.name+'/state',pair_sha256=sha((shadow/'PAIR.json').read_bytes())))
    return dict(state='STAGED_OUTPUT_INSTALLED_LOCALLY',model=MODEL,original_shadow=shadow.relative_to(source).as_posix(),
                source_code_written=False,git_published=False,deployed=False)

def immutable_copy(source,target):
    target=Path(target);raw=Path(source).read_bytes()
    if target.is_symlink():raise ValueError('IMMUTABLE_OUTPUT_SYMLINK')
    if target.exists():
        if target.read_bytes()!=raw:raise ValueError('IMMUTABLE_OUTPUT_COLLISION')
        return
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb')as stream:stream.write(raw)

def atomic_copy(source,target):
    import tempfile
    target=Path(target);raw=Path(source).read_bytes()
    if target.is_symlink():raise ValueError('OUTPUT_SYMLINK')
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.classic-',dir=target.parent)
    try:
        with os.fdopen(fd,'wb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,target)
    finally:
        Path(temporary).unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--phase", choices=["record", "extend"])
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--private-run-dir", type=Path)
    parser.add_argument("--original-repository", type=Path)
    parser.add_argument("--prior-r0-state", type=Path)
    parser.add_argument("--mode", required=True, choices=["live", "replay"])
    parser.add_argument('--install-staged-output',action='store_true')
    args = parser.parse_args()
    if args.worker:
        if not args.phase or not args.inputs: parser.error("Worker phase/inputs required")
        value = worker(args.worker, args.inputs, args.phase, args.mode)
    else:
        if not all([args.root, args.private_run_dir, args.original_repository]): parser.error("Source, original repository and fresh private run directory required")
        if args.install_staged_output:value=install_pair_outputs(args.root,args.private_run_dir)
        else:value = run_pair(args.root, args.private_run_dir, args.original_repository, mode=args.mode, prior_r0=args.prior_r0_state)
    print(json.dumps(value, sort_keys=True))

if __name__ == "__main__": main()
