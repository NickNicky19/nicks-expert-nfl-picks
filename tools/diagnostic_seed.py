"""One immutable local diagnostic seed, explicit source/fictional Git closure.

No remote transport or publication. Future retrieval uses approved immutable
repository objects only; a path/hash with unavailable bytes is not admitted.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

LIMIT=8*1024**3
PART=16*1024**2

def sha(raw):return hashlib.sha256(raw).hexdigest()
def hashfile(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for value in iter(lambda:stream.read(1024**2),b''):h.update(value)
    return h.hexdigest()

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def run(root,*args,raw=False):
    v=subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE)
    return v if raw else v.decode().strip()
def files(root):
    names=run(root,'ls-files','-z',raw=True).decode().split('\0')
    result={}
    for name in names:
        if not name:continue
        p=root/name
        if p.is_symlink() or not p.is_file():raise RuntimeError('Seed requires regular immutable files')
        raw=p.read_bytes();result[name]=dict(sha256=sha(raw),bytes=len(raw),mode=p.stat().st_mode&0o777)
    return result

def freeze(root,destination,admission_path,harness):
    root=Path(root).resolve();destination=Path(destination).resolve()
    if destination.exists():raise RuntimeError('New immutable seed destination required')
    admission=json.loads(Path(admission_path).read_bytes())
    if admission['status']!='ADMITTED':raise RuntimeError('Unadmitted full seed cannot be transported')
    return _freeze(root,destination,admission,harness,False)

def _freeze(root,destination,admission,harness,smoke=False):
    if run(root,'status','--porcelain','--untracked-files=no'):raise RuntimeError('Uncommitted seed')
    destination.mkdir();inventory=files(root)
    head=run(root,'rev-parse','HEAD');public=run(root,'rev-parse','refs/fixture/source')
    # Explicit roots only. Source history is separately disclosed as PUBLIC
    # SOURCE OBJECTS, never claimed to be fictional or a scrubbed .git archive.
    fake_objects={line.split()[0] for line in run(root,'rev-list','--objects',head).splitlines()}
    source_objects={line.split()[0] for line in run(root,'rev-list','--objects',public).splitlines()}
    roots=dict(fictional_head=head,public_source=public)
    closure={name:dict(count=len(ids),object_ids_sha256=sha(('\n'.join(sorted(ids))+'\n').encode()))
        for name,ids in [('fictional',fake_objects),('public_source',source_objects)]}
    overlap=fake_objects & source_objects
    # Source files necessarily share immutable blobs. Pack those once in the
    # separately identified PUBLIC source closure, never relabel them fictional.
    fake_objects-=source_objects
    closure['shared_public_objects']=dict(count=len(overlap),object_ids_sha256=sha(('\n'.join(sorted(overlap))+'\n').encode()))
    packs=[]
    for name,ids in [('fictional',fake_objects),('public-source',source_objects)]:
        path=destination/(name+'.pack')
        with path.open('wb') as output:
            subprocess.run(['git','-C',str(root),'pack-objects','--stdout'],input=('\n'.join(sorted(ids))+'\n').encode(),stdout=output,check=True)
        packs.append(dict(name=path.name,sha256=hashfile(path),bytes=path.stat().st_size,objects=len(ids)))
    archive=destination/'working.tar.gz'
    with archive.open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0,filename='') as compressed,tarfile.open(fileobj=compressed,mode='w|') as tar:
        for name,d in sorted(inventory.items()):
            value=(root/name).read_bytes();info=tarfile.TarInfo(name);info.size=len(value);info.mode=d['mode'];info.mtime=0
            tar.addfile(info,io.BytesIO(value))
    manifest=dict(schema_version='fictional-operating-seed-v1',notice='WHOLLY_FICTIONAL_DATA_WITH_SEPARATELY_IDENTIFIED_PUBLIC_SOURCE_OBJECTS',
        roots=roots,object_closure=closure,files=inventory,working=dict(name=archive.name,sha256=hashfile(archive),bytes=archive.stat().st_size),
        packs=packs,application_source=harness.BASE,harness_sha256=sha(Path(harness.__file__).read_bytes()),
        admission_sha256=sha(canonical(admission)),semantic_sha256=admission['metrics']['public_semantics_sha256'],
        full_admitted=not smoke,construction_source=harness.git(root,'rev-parse','refs/fixture/source'),
        seed_revision=harness.SEED_REVISION,sample_revision=harness.NEXT_REVISION,sample_clock_seconds=harness.SAMPLE_SECONDS)
    (destination/'SEED_MANIFEST.json').write_bytes(canonical(manifest))
    # Proposed later transport is split, hash-bound files below Git file limits.
    transport=[]
    for path in [archive,*[destination/p['name'] for p in packs],destination/'SEED_MANIFEST.json']:
        with path.open('rb') as stream:
            n=0
            while True:
                value=stream.read(PART)
                if not value:break
                part=destination/(path.name+'.part-'+str(n).zfill(4));part.write_bytes(value)
                transport.append(dict(path=part.name,sha256=sha(value),bytes=len(value),parent=path.name,position=n));n+=1
    spec=dict(schema_version='fictional-seed-transport-v1',seed_manifest_sha256=sha(canonical(manifest)),parts=transport,
        destination='PROPOSED_EXISTING_PUBLIC_GITHUB_IMMUTABLE_FIXTURE_COMMIT_NOT_CREATED',publication_authorized=False)
    (destination/'TRANSPORT.json').write_bytes(canonical(spec))
    return manifest

def restore(seed,root,expected):
    seed=Path(seed).resolve();root=Path(root).resolve()
    manifest_path=seed/'SEED_MANIFEST.json'
    if manifest_path.is_symlink() or manifest_path.stat().st_size>16*1024**2:raise RuntimeError('Seed manifest bound/type')
    manifest_raw=manifest_path.read_bytes()
    if sha(manifest_raw)!=expected:raise RuntimeError('Seed manifest changed')
    m=json.loads(manifest_raw)
    if type(m.get('full_admitted')) is not bool:raise RuntimeError('Invalid seed qualification declaration')
    if m['schema_version']!='fictional-operating-seed-v1':raise RuntimeError('Unknown seed contract')
    if root.exists():raise RuntimeError('Cold restoration requires new root')
    total=sum(d['bytes'] for d in m['files'].values())
    if total>LIMIT:raise RuntimeError('Seed decoded restoration bound')
    for d in [m['working'],*m['packs']]:
        if d['name'] not in ('working.tar.gz','fictional.pack','public-source.pack'):raise RuntimeError('Unknown seed dependency role')
        p=seed/d['name']
        if p.is_symlink() or p.stat().st_size!=d['bytes']:raise RuntimeError('Seed size/type mismatch')
        h=hashlib.sha256()
        with p.open('rb') as stream:
            for value in iter(lambda:stream.read(1024**2),b''):h.update(value)
        if h.hexdigest()!=d['sha256']:raise RuntimeError('Seed original bytes changed')
    root.mkdir();seen=set();decoded=0
    with tarfile.open(seed/m['working']['name'],mode='r|gz') as tar:
        for info in tar:
            if info.name not in m['files'] or info.name in seen or not info.isfile() or Path(info.name).is_absolute() or '..' in Path(info.name).parts:
                raise RuntimeError('Unexpected/duplicate/unsafe seed member')
            d=m['files'][info.name]
            if info.size!=d['bytes'] or decoded+info.size>LIMIT:raise RuntimeError('Seed member expansion limit')
            target=root/info.name;target.parent.mkdir(parents=True,exist_ok=True)
            h=hashlib.sha256();remaining=info.size;source=tar.extractfile(info)
            with target.open('xb') as output:
                while remaining:
                    value=source.read(min(1024**2,remaining))
                    if not value:raise RuntimeError('Truncated seed')
                    output.write(value);h.update(value);remaining-=len(value)
            if h.hexdigest()!=d['sha256']:raise RuntimeError('Seed member hash')
            target.chmod(d['mode']);decoded+=info.size;seen.add(info.name)
    if seen!=set(m['files']):raise RuntimeError('Missing seed member')
    run(root,'init','-q')
    for d in m['packs']:
        with (seed/d['name']).open('rb') as source:subprocess.run(['git','-C',str(root),'index-pack','--stdin'],stdin=source,stdout=subprocess.DEVNULL,check=True)
    for ref,key in [('refs/heads/fixture','fictional_head'),('refs/fixture/source','public_source')]:run(root,'update-ref',ref,m['roots'][key])
    run(root,'symbolic-ref','HEAD','refs/heads/fixture');run(root,'read-tree','HEAD')
    run(root,'remote','add','origin','https://github.com/NickNicky19/nicks-expert-nfl-picks.git')
    run(root,'fsck','--full','--no-reflogs')
    if files(root)!=m['files'] or run(root,'status','--porcelain','--untracked-files=no'):raise RuntimeError('Restored tree differs')
    return m

def retrieve(code,destination,transport,ref):
    """Future local Git-object retrieval; no network, mutable URL or credentials."""
    if not isinstance(transport,dict) or transport.get('schema_version')!='fictional-seed-transport-v1':raise RuntimeError('Unknown transport contract')
    if not (len(ref)==40 and all(c in '0123456789abcdef' for c in ref)):raise RuntimeError('Exact approved seed commit required')
    if destination.exists():raise RuntimeError('New retrieval directory required')
    destination.mkdir();positions={};total=0
    allowed={'working.tar.gz','fictional.pack','public-source.pack','SEED_MANIFEST.json'}
    for d in transport['parts']:
        if '/' in d['path'] or '..' in d['path'] or type(d['bytes']) is not int or not 0<d['bytes']<=PART or d['parent'] not in allowed:
            raise RuntimeError('Invalid transport part/role')
        next_position=positions.get(d['parent'],0)
        if type(d['position']) is not int or d['position']!=next_position:raise RuntimeError('Transport order/coverage')
        total+=d['bytes']
        if total>LIMIT:raise RuntimeError('Encoded transport bound')
        oid=run(code,'rev-parse',ref+':seed/'+d['path'])
        if run(code,'cat-file','-t',oid)!='blob' or int(run(code,'cat-file','-s',oid))!=d['bytes']:raise RuntimeError('Transport blob type/size')
        raw=run(code,'cat-file','blob',oid,raw=True)
        if len(raw)!=d['bytes'] or sha(raw)!=d['sha256']:raise RuntimeError('Transport part mismatch')
        with (destination/d['parent']).open('xb' if next_position==0 else 'ab') as output:output.write(raw)
        positions[d['parent']]=next_position+1
    if set(positions)!=allowed:raise RuntimeError('Missing transport role')
    if sha((destination/'SEED_MANIFEST.json').read_bytes())!=transport['seed_manifest_sha256']:raise RuntimeError('Transport manifest mismatch')

LEGACY_GRADING_SOURCE='0f2768b77a004ac73ad2853b68b0c5ebf62d828b'

def legacy_backup_fixture(root,h,m,provider):
    """NEW wholly fictional legacy baseline, not relabelled versioned output.

    Execute the actual retained pre-Phase1 grader on complete fictional inputs.
    Its old grading limitations stay confined to the labelled history backup;
    the current board, forecasts, corrected grades and receipts are untouched.
    """
    import tempfile
    path=root/'data/history/pre_phase1_track_record.json.gz'
    if path.exists():raise RuntimeError('Create-only fictional legacy baseline')
    data={}
    for archive in (root/'output/data/archive').glob('*.json'):
        board=json.loads(archive.read_bytes());season,week=board['season'],board['week']
        data[f'{season}/{week}']={pid:dict(stats=provider.stats(pid,season,week,False)) for pid in provider.roster}
    # Source setup is already-public ancestor history, separate from fictional data.
    raw=run(root,'archive',LEGACY_GRADING_SOURCE,'pull',raw=True)
    with tempfile.TemporaryDirectory(prefix='fictional-legacy-grader-') as directory:
        directory=Path(directory)
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as tar:tar.extractall(directory,filter='data')
        command="""import json,sys;from pathlib import Path
sys.path.insert(0,sys.argv[1]);import grade
v=json.load(sys.stdin);root=Path(sys.argv[2]);lookup=lambda s,w:v[str(s)+'/'+str(w)]
print(json.dumps(grade.grade_all(root/'output/data/archive',lookup,(2026,6),set(sys.argv[3:])),sort_keys=True,allow_nan=False))
"""
        final=[e['id'] for e in provider.scoreboard(2026,6)['events'] if e['status']['type']['state']=='post']
        record=json.loads(subprocess.check_output([h.sys.executable,'-c',command,str(directory/'pull'),str(root),*final],input=canonical(data)))
    if record.get('grading_version') or not record.get('weeks'):raise RuntimeError('Not meaningful unversioned fictional baseline')
    payload=dict(label='LEGACY_GRADING_OUTPUT_NOT_NEW_PROSPECTIVE_EVIDENCE',captured_at=m['rel'].stamp(provider.at),record=record)
    m['rel'].immutable_write(path,payload)
    marker=dict(notice=h.NOTICE,source=LEGACY_GRADING_SOURCE,source_grade_blob=run(root,'rev-parse',LEGACY_GRADING_SOURCE+':pull/grade.py'),
        source_pull_tree=run(root,'rev-parse',LEGACY_GRADING_SOURCE+':pull'),
        inputs_sha256=sha(canonical(data)),record_sha256=m['rel'].digest(record),
        claim='NEW_FICTIONAL_PRE_PHASE1_RENDER_NOT_RELABELED_CURRENT_VERSIONED_REPORT',
        backup_path=path.relative_to(root).as_posix(),backup_sha256=hashfile(path))
    (root/'FICTIONAL_LEGACY_BASELINE.json').write_bytes(canonical(marker))
    return marker
