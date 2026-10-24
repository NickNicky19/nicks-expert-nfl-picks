"""Inspect ONE retained failed fictional checkpoint; never construct or admit.

The raw checkpoint is separate from a fresh checkout of its committed frontier.
Progress, independent saved reconstruction, and permission to continue are
different facts. No original input, plan, receipt, clock or helper is rewritten.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import traceback
import zipfile

import source_ci as ci
import operating_seed_transport as transport

sys.dont_write_bytecode = True
BASE = 'b3de2fbd88ba3247b407a856972285ad10527b99'
TREE = 'c0d0d818f8e1266f55851c8c220d44cd94797c78'
PRODUCER = '1b592af659cec56fe87440cf679d69d7fc41590e'
RUN = 39940028362
ARTIFACT = 12509203616
SIZE = 998031473
DIGEST = 'e9a1be3a3580d01a51b39375d7d908ba37300b02e83ab6ccf2e2732540b9876c'
EXPIRES = '2026-10-30T14:45:09Z'
HARNESS = '441f0ccaa1b274708419643d993896b5ff6f2c4118e0016719c80a1746289328'
INPUTS = '56c10c8c7e26a4ffd18c5838115c587f7bce7930a6bd078e49527dc2f0bc1cad'
CHECKPOINT = 'INCOMPLETE_CHECKPOINT.tar.gz'
BUNDLE = 'INCOMPLETE_SOURCE_CLOSURE.bundle'
MANIFEST = 'INCOMPLETE_MANIFEST.json'
PARENTS = {
    CHECKPOINT: dict(bytes=481423181, sha256='e6fcb2247ef46e10dc5da0c26443c2451a21d907385f777f5c89a9a4445042b2'),
    BUNDLE: dict(bytes=514507259, sha256='1a00f598255d1a42322330adcf65c3b317778aa6a2c48642b844f48a63fefdbf'),
    MANIFEST: dict(bytes=1025096, sha256='2b650a9a89951d0657398caf2f3012244938242e41529c07cbc1df33f351a6ee'),
}
ALLOW = set(PARENTS) | {'ANCESTORS.after.json', 'ANCESTORS.before.json',
    'ARTIFACT_MANIFEST.json', 'PREFLIGHT.json', 'PREPARATION_RESULT.json', 'RESOURCE.json'}
GIB = 1024 ** 3
DECODED_LIMIT = 8 * GIB
FILE_LIMIT = 64 * 1024 ** 2
FILE_COUNT = 20000
PHASES = ('entry', 'source_binding', 'retrieval', 'parent_integrity', 'raw_restore',
    'committed_git_restore', 'lineage_binding', 'latest_saved_validation',
    'retained_history_validation', 'final_integrity', 'final_source_binding')
DIAGNOSTIC_PHASE = 'entry'
PROFILE22 = 'continued22'
_CONTINUED22 = dict(run=40017092249, artifact=12540324398,
    producer='4855732886ce0da65ccf3af13928049149f33ea8', tree='2dfb1d661a073f2cb997d03157beb79b970f818c',
    size=2092241565, digest='d5060fb316f4626144b71ebbf6d774f7c644f2568f92b2e5b89efd10c04ac18d',
    expiry='2026-10-27T00:21:55Z', integrity='ed5b6773c3d4e642bf4346aa2b9de89a2b580a1f34e97bddc6172b068a388611', count=22)


def profile_identity(profile=None):
    """Closed producer identities; callers cannot supply a replacement profile."""
    if profile is None:
        return dict(run=RUN, artifact=ARTIFACT, producer=PRODUCER,
            tree='49ddc936c1ba3f47bb038c7250eb82c6e0a91393', size=SIZE, digest=DIGEST,
            expiry=EXPIRES, integrity='bfb48f36d1db5b2980235238e1b869efb183f23095ff72cee33c1d88e84a3b26', count=13)
    if type(profile) is str and profile == PROFILE22:
        return dict(_CONTINUED22)
    raise ValueError('Unsupported closed checkpoint profile')


def phase(name):
    """Constant diagnostic labels, never fixture fields or validation authority."""
    global DIAGNOSTIC_PHASE
    if name not in PHASES:
        raise ValueError('Unknown inspection diagnostic phase')
    DIAGNOSTIC_PHASE = name
    print('CHECKPOINT_FRONTIER_PHASE=' + name, flush=True)


@contextmanager
def retained_source_environment():
    """Let retained readers resolve their actual Git root, never the installer.

    This matches the existing frozen preparation stage boundary: no old SHA is
    invented or injected. The caller retains its real source identity and gets
    the original environment back on success and failure.
    """
    installer = os.environ.pop('GITHUB_SHA', None)
    try:
        yield
    finally:
        os.environ.pop('GITHUB_SHA', None)
        if installer is not None:
            os.environ['GITHUB_SHA'] = installer


def failure_report(error):
    """Identify a failing operation without printing raw command/error payloads."""
    classes = {'CalledProcessError', 'TimeoutExpired', 'IntegrityError', 'Rejected',
        'ValueError', 'OSError', 'EOFError', 'BadGzipFile', 'AssertionError',
        'FileNotFoundError', 'PermissionError', 'RuntimeError', 'KeyboardInterrupt'}
    result = dict(schema_version='checkpoint-inspection-failure-v1',
        phase=DIAGNOSTIC_PHASE if DIAGNOSTIC_PHASE in PHASES else 'entry',
        error_class=type(error).__name__ if type(error).__name__ in classes else 'OTHER_ERROR',
        raw_exception_and_arguments_omitted=True)
    if isinstance(error, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
        command = error.cmd
        role = 'subprocess'; verb = None
        if isinstance(command, (tuple, list)) and command and isinstance(command[0], str):
            executable = Path(command[0]).name
            if executable == 'git':
                role = 'git'
                verbs = {'bundle', 'fetch', 'fsck', 'ls-tree', 'cat-file', 'rev-parse',
                    'status', 'show', 'init', 'symbolic-ref', 'checkout', 'remote',
                    'count-objects', 'config', 'hash-object', 'clone', 'gc'}
                verb = next((x for x in command[1:] if isinstance(x, str) and x in verbs), None)
            elif re.fullmatch(r'python(?:[0-9]+(?:\.[0-9]+)*)?', executable):
                role = 'python'
        returncode = error.returncode if isinstance(error, subprocess.CalledProcessError) else None
        result.update(command_role=role, command_verb=verb,
            returncode=returncode if type(returncode) is int and abs(returncode) <= 2147483647 else None)
        stderr = getattr(error, 'stderr', None)
        prefix = (stderr[:8192].encode(errors='replace') if isinstance(stderr, str)
            else stderr[:8192] if isinstance(stderr, bytes) else b'').lower()
        classifiers = (
            ('GIT_OBJECT_UNAVAILABLE', (b'bad object', b'not a valid object', b'unknown revision',
                b'bad revision', b'invalid object name', b'could not get object info')),
            ('GIT_OWNERSHIP_REJECTED', (b'dubious ownership', b'safe.directory')),
            ('GIT_LOCK_REJECTED', (b'index.lock', b'cannot lock ref')),
            ('NETWORK_PERMISSION_DENIED', (b'operation not permitted', b'could not resolve host')),
            ('RESOURCE_UNAVAILABLE', (b'cannot allocate memory', b'resource temporarily unavailable', b'no space left')),
        )
        result['stderr_class'] = next((label for label, patterns in classifiers
            if any(p in prefix for p in patterns)), 'UNCLASSIFIED_OR_NOT_CAPTURED')
    public_files = {'seed_checkpoint_frontier.py', 'operating_diagnostic.py',
        'phase2_capture.py', 'data_integrity_v2.py', 'partial_week.py', 'reliability.py',
        'verify.py', 'selection_publication.py', 'scorecard.py', 'source_evidence.py'}
    result['public_call_frames'] = [dict(file=Path(f.filename).name, function=f.name, line=f.lineno)
        for f in traceback.extract_tb(error.__traceback__, limit=12)
        if Path(f.filename).name in public_files and re.fullmatch(r'[A-Za-z0-9_<>]{1,80}', f.name)]
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def descriptor(path, limit=None):
    require(path.is_file() and not path.is_symlink(), 'Regular dependency required')
    if limit is not None:
        require(type(limit) is int and limit >= 0 and path.stat().st_size <= limit, 'Dependency byte bound')
    h = hashlib.sha256(); count = 0
    with path.open('rb') as source:
        for raw in iter(lambda: source.read(1024 ** 2), b''):
            h.update(raw); count += len(raw)
            if limit is not None:require(count <= limit, 'Dependency grew beyond byte bound')
    return dict(bytes=count, sha256=h.hexdigest())


def verify_parents(work, profile=None):
    expected_parents = PARENTS if profile is None else _outer_parents(work, profile)
    for name, expected in expected_parents.items():
        require(descriptor(work / name, expected['bytes'] if profile is not None else None) == expected, 'Actual checkpoint parent bytes')
    return dict(expected_parents)


def _outer_parents(work, profile):
    """Derive new parents only from the fixed, freshly hashed actual ZIP."""
    selected = profile_identity(profile); archive = work / 'artifact.zip'
    require(descriptor(archive, selected['size']) == dict(bytes=selected['size'], sha256=selected['digest']), 'Actual outer artifact bytes')
    transport._zip_inventory(archive)
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist(); names = [item.filename for item in members]
        require(set(names) == ALLOW and len(names) == len(ALLOW), 'Exact retained outer inventory')
        total = 0
        for item in members:
            require(item.orig_filename == item.filename and not item.is_dir()
                and item.external_attr >> 16 & 0o170000 in (0, stat.S_IFREG)
                and not item.flag_bits & 1 and item.compress_type in (0, 8)
                and 0 <= item.file_size <= transport.LIMIT, 'Actual bounded outer role')
            total += item.file_size
        require(total <= transport.LIMIT, 'Actual complete outer decoded bound')
        member = zipped.getinfo('ARTIFACT_MANIFEST.json')
        require(member.file_size <= transport.JSON_LIMIT, 'Actual bounded outer envelope')
        with zipped.open(member) as stream:
            raw = stream.read(transport.JSON_LIMIT + 1)
        envelope = ci.decoded(raw, transport.JSON_LIMIT)
        require(type(envelope) is dict and envelope.get('schema_version') == 'cloud-seed-artifact-envelope-v1'
            and envelope.get('application_source') == BASE
            and envelope.get('installer') == dict(head=selected['producer'], tree=selected['tree'])
            and envelope.get('integrity_sha256') == selected['integrity']
            and envelope.get('preparation_status') == 'PREPARATION_FAILED'
            and envelope.get('operating_qualification') == 'NOT_RUN', 'Actual new producer envelope')
        inventory = envelope.get('files')
        require(type(inventory) is dict and set(inventory) == ALLOW - {'ARTIFACT_MANIFEST.json'}, 'Actual complete envelope inventory')
        for name, d in inventory.items():
            require(type(d) is dict and set(d) == {'bytes', 'sha256'}
                and type(d['bytes']) is int and d['bytes'] == zipped.getinfo(name).file_size
                and type(d['sha256']) is str and re.fullmatch('[0-9a-f]{64}', d['sha256']), 'Actual envelope descriptor')
        return {name: dict(inventory[name]) for name in PARENTS}


def decoded(path, limit=transport.JSON_LIMIT):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit, 'JSON dependency bound/type')
    return ci.decoded(path.read_bytes(), limit)


def safe_name(name):
    if not isinstance(name, str): return False
    p = PurePosixPath(name)
    return (isinstance(name, str) and bool(name) and not p.is_absolute()
        and str(p) == name and '..' not in p.parts and '\\' not in name and '\x00' not in name
        and (len(p.parts) > 1 and p.parts[0] in ('pull', 'tools', 'config', 'data', 'output') or name in {
            'FICTIONAL_ONLY.json', 'FICTIONAL_PHASES.json', 'FICTIONAL_LEGACY_BASELINE.json',
            'FICTIONAL_PARTICIPATION_ADAPTER.json', 'CONSTRUCTION_PROGRESS.json'}))


def manifest_files(value):
    require(value.get('status') == 'INCOMPLETE_NOT_ADMITTED_NOT_RESUME_AUTHORIZED'
        and value.get('application_source') == BASE and value.get('input_contract_sha256') == INPUTS,
        'Original incomplete identity required')
    files = value.get('files')
    require(isinstance(files, dict) and 0 < len(files) <= FILE_COUNT, 'Inventory count')
    total = 0
    for name, d in files.items():
        require(safe_name(name) and isinstance(d, dict) and set(d) == {'bytes', 'sha256'}, 'Inventory role')
        require(type(d['bytes']) is int and 0 <= d['bytes'] <= FILE_LIMIT
            and isinstance(d['sha256'], str) and re.fullmatch('[0-9a-f]{64}', d['sha256']), 'Inventory descriptor')
        total += d['bytes']
    require(total <= DECODED_LIMIT, 'Complete checkpoint decoded bound')
    for name in files:
        require(not any('/'.join(PurePosixPath(name).parts[:i]) in files
            for i in range(1, len(PurePosixPath(name).parts))), 'Overlapping inventory roles')
    return files, total


def pax_path(raw):
    """Only the writer's bounded long-path extension, never a size override."""
    fields = {}; offset = 0
    while offset < len(raw):
        space = raw.find(b' ', offset)
        require(space > offset and raw[offset:space].isdigit(), 'Malformed PAX length')
        length = int(raw[offset:space])
        require(space + 2 < offset + length <= len(raw), 'PAX record bound')
        record = raw[space + 1:offset + length]
        require(record.endswith(b'\n') and b'=' in record, 'Malformed PAX record')
        key, value = record[:-1].split(b'=', 1)
        require(key == b'path' and key not in fields and len(value) <= 4096, 'Unsupported PAX override')
        fields[key] = value.decode('utf-8'); offset += length
    require(set(fields) == {b'path'} and safe_name(fields[b'path']), 'PAX path role')
    return fields[b'path']


def unpack_checkpoint(archive, destination, value):
    files, total = manifest_files(value)
    require(not destination.exists(), 'Fresh raw restoration required')
    destination.mkdir(mode=0o700); seen = set(); consumed = 0; tar_bytes = 0; pending = None
    # Parse fixed headers ourselves so an untrusted PAX size cannot cause an
    # unbounded tarfile allocation. Drain gzip through its actual CRC/footer.
    with gzip.open(archive, 'rb') as source:
        def take(size):
            nonlocal tar_bytes
            require(0 <= size <= 1024 ** 2, 'Bounded decompression read')
            raw = source.read(size); tar_bytes += len(raw)
            require(tar_bytes <= total + len(files) * (16384 + 2048) + 10240, 'Complete TAR decoding bound')
            require(len(raw) == size, 'Truncated checkpoint member')
            return raw
        while True:
            header = take(512)
            if header == b'\0' * 512:
                require(pending is None and take(512) == b'\0' * 512, 'TAR end markers')
                tail = source.read(10241)
                require(len(tail) <= 10240 and not any(tail) and source.read(1) == b'', 'TAR trailing bytes bound')
                break
            info = tarfile.TarInfo.frombuf(header, 'utf-8', 'strict')
            require(info.size >= 0, 'Negative TAR size')
            if info.type == tarfile.XHDTYPE:
                require(pending is None and info.name == '././@PaxHeader' and info.size <= 16384, 'Bounded PAX header')
                pending = pax_path(take(info.size))
                require(not any(take((-info.size) % 512)), 'PAX padding')
                continue
            name = pending if pending is not None else info.name; pending = None
            require(name in files and name not in seen and safe_name(name)
                and info.isfile() and info.mode == 0o600 and info.mtime == 0, 'Unsafe or duplicate checkpoint member')
            d = files[name]
            require(info.size == d['bytes'] and consumed + info.size <= DECODED_LIMIT, 'Checkpoint expansion bound')
            target = destination / name; target.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256(); remaining = info.size
            with target.open('xb') as output:
                while remaining:
                    raw = take(min(1024 ** 2, remaining)); output.write(raw); h.update(raw); remaining -= len(raw)
            target.chmod(0o600); require(not any(take((-info.size) % 512)), 'TAR file padding')
            require(h.hexdigest() == d['sha256'], 'Checkpoint member hash')
            seen.add(name); consumed += info.size
    require(seen == set(files) and consumed == total, 'Complete checkpoint membership')
    return files


def progress(value, profile=None):
    selected = profile_identity(profile)
    require(isinstance(value, dict) and set(value) == {'generation', 'target', 'wall_clock'}
        and type(value['generation']) is int and type(value['target']) is int
        and value['generation'] == selected['count'] and value['target'] == 24, 'Exact recorded frontier')
    require(isinstance(value['wall_clock'], str)
        and datetime.fromisoformat(value['wall_clock']).tzinfo is not None, 'Progress clock')
    return value['generation']


def git(root, *arguments, data=None, timeout=120):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')
        and k not in ('GH_TOKEN', 'GITHUB_TOKEN', 'ODDS_API_KEY')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0', GIT_NO_REPLACE_OBJECTS='1')
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'gc.auto=0',
        '-C', str(root), *arguments], input=data, stderr=subprocess.PIPE, env=env, timeout=timeout)


def tracked(root, ref='HEAD'):
    result = {}
    for row in git(root, 'ls-tree', '-r', '-z', ref).split(b'\0'):
        if not row: continue
        left, name = row.split(b'\t', 1); mode, kind, blob = left.decode().split()
        require(kind == 'blob' and mode in ('100644', '100755'), 'Tracked type/mode')
        result[name.decode()] = (mode, blob)
    return result


def tree_inventory(root):
    return {p.relative_to(root).as_posix(): descriptor(p) for lane in ('pull', 'tools', 'config', 'data', 'output')
        for p in (root / lane).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def restore_committed(work, raw, files, profile=None):
    """Keep raw partial14 unchanged; independently restore actual committed HEAD."""
    bundle = work / BUNDLE
    heads = {}
    for line in git(work, 'bundle', 'list-heads', str(bundle)).decode().splitlines():
        sha, name = line.split(); require(re.fullmatch('[0-9a-f]{40}', sha) and name not in heads, 'Bundle heads')
        heads[name] = sha
    require(set(heads) == {'HEAD', 'refs/fixture/source'} and heads['refs/fixture/source'] == BASE, 'Exact bundle roots')
    root = work / 'committed-frontier'; require(not root.exists(), 'Independent fresh frontier required')
    root.mkdir(mode=0o700); git(root, 'init', '-q')
    git(root, 'bundle', 'verify', str(bundle))
    git(root, 'fetch', '--no-tags', str(bundle), 'HEAD:refs/heads/frontier', 'refs/fixture/source:refs/fixture/source')
    require(all(safe_name(name) for name in tracked(root, 'refs/heads/frontier')), 'Tracked checkpoint roles')
    git(root, 'symbolic-ref', 'HEAD', 'refs/heads/frontier'); git(root, 'checkout', '--quiet', 'frontier')
    git(root, 'remote', 'add', 'origin', 'https://github.com/' + ci.REPOSITORY + '.git')
    require(git(root, 'rev-parse', 'HEAD').decode().strip() == heads['HEAD']
        and git(root, 'rev-parse', BASE + '^{tree}').decode().strip() == TREE, 'Actual fixture/source identity')
    require(not (root / '.git/objects/info/alternates').exists(), 'No source alternates')
    git(root, 'fsck', '--full', '--no-reflogs')
    require(not git(root, 'status', '--porcelain'), 'Clean committed frontier')
    source = {k: v for k, v in tracked(root, BASE).items() if k.startswith(('pull/', 'tools/'))}
    require(set(source) == {name for name in files if name.startswith(('pull/', 'tools/'))}, 'Exact B3 executable inventory')
    for name, (_, blob) in source.items():
        expected = git(root, 'cat-file', 'blob', blob)
        require((raw / name).read_bytes() == expected and (root / name).read_bytes() == expected, 'Actual retained B3 code')
    require(hashlib.sha256((root / 'tools/data_integrity_v2.py').read_bytes()).hexdigest()
        == '7fb3ed03ff5b22dbe1aa9a0db4ae830fe540ace732e0a0199b0e82c93533cf49', 'Original repaired helper')
    before = {name: descriptor(root / name) for name in tracked(root) if safe_name(name)}
    residual = {'new': 0, 'changed': 0, 'missing_from_checkpoint': 0}
    for name, d in files.items():
        if name == 'CONSTRUCTION_PROGRESS.json': continue
        if name not in before: residual['new'] += 1
        elif before[name] != d: residual['changed'] += 1
    residual['missing_from_checkpoint'] = len(set(before) - set(files))
    require(not residual['missing_from_checkpoint'], 'Committed dependency missing from preserved checkpoint')
    if profile is not None:
        _carry_residual(root, raw, files, before)
    return root, heads, residual


_MARKERS = {'FICTIONAL_ONLY.json', 'FICTIONAL_PHASES.json',
    'FICTIONAL_LEGACY_BASELINE.json', 'FICTIONAL_PARTICIPATION_ADAPTER.json'}
_SNAPSHOTS = {'output/' + name for name in ('app.js', 'index.html', 'data/week.json',
    'data/meta.json', 'data/verification-scope.json', 'data/forecast-scorecard.json',
    'data/selection-grading/latest.json', 'data/health.json', 'data/release-identity.json')}
# Exact mutable data aliases emitted by the retained B3 builder/capture. Static
# app/shell snapshots are source, not mutable build products.
_BUILD_ALIASES = {'output/data/' + name for name in ('week.json', 'future.json',
    'meta.json', 'teams.json', 'track_record.json', 'matchup-proof.json',
    'game-status.json', 'verification-scope.json', 'forecast-scorecard.json',
    'offer-capture.json', 'release-identity.json', 'health.json')}
_RESIDUAL_SCHEMAS = {
    'forward': {'baseline-capture-v2'},
    'verification': {'matchup-inputs-v2', 'matchup-inputs-v3'},
    'verification/partial-scopes': {'partial-week-input-reproduction-v1', 'partial-scope-data-integrity-v2'},
    'verification/partial-completions': {'partial-week-completion-v1', 'partial-completion-data-integrity-v2'},
    'verification/partial-plan-boards': {'partial-initial-board-v1'},
    'verification/partial-registrations': {'partial-week-registration-v1', 'partial-registration-data-integrity-v2'},
    'verification/partial-failures': {'generation-failure-v1', 'partial-completion-failure-v1',
        'completion-failure-data-integrity-v2', 'unqualified-native-preservation-v1'},
    'verification/matchup-checks': {'matchup-verification-v1'},
    'verification/report-originals': {'rich-scorecard-evidence-v1'},
    'verification/hosting-generation-proof': {'hosting-generation-proof-v1'},
    'verification/hosting-capture-originals': {'hosting-capture-original-v1', 'hosting-packaging-transition-v1'},
    'offers': {'sleeper-selection-offers-v1'},
    'outcomes': {'forecast-outcomes-v1', 'forecast-outcomes-v2'},
}


def _mutable_role(name):
    return (name.startswith('data/cache/') or name in _BUILD_ALIASES
        or name in {'output/data/selection-grading/latest.json', 'output/data/selection-grading/hosting.json'}
        or re.fullmatch(r'output/data/(?:archive|weeks)/2026_w0[1-6]\.json', name) is not None)


def _residual_evidence(path, name):
    """Bounded canonical original envelope, never a new evidence interpretation."""
    match = re.fullmatch(r'data/(forward|history|verification|shadow|offers|outcomes)/(?:[A-Za-z0-9_-]+/)*([0-9]{4})/w([0-9]{2})/([0-9a-f]{64})\.json\.gz', name)
    require(match is not None, 'Unsupported residual evidence role')
    require(descriptor(path)['bytes'] <= FILE_LIMIT, 'Residual evidence encoded bound')
    with gzip.open(path, 'rb') as source:
        raw = source.read(FILE_LIMIT + 1)
        require(len(raw) <= FILE_LIMIT and source.read(1) == b'', 'Residual evidence decoded bound')
    envelope = ci.decoded(raw, FILE_LIMIT)
    require(type(envelope) is dict and set(envelope) == {'payload', 'payload_sha256'}, 'Residual evidence envelope')
    value = envelope['payload']
    require(type(value) is dict and type(value.get('schema_version')) is str and bool(value['schema_version'])
        and type(value.get('season')) is int and type(value.get('week')) is int
        and value['season'] == int(match[2]) and value['week'] == int(match[3])
        and hashlib.sha256(ci.canonical(value)).hexdigest() == match[4] == envelope['payload_sha256'], 'Canonical residual evidence identity')
    lane = name[5:].rsplit('/', 3)[0]
    require(value['schema_version'] in _RESIDUAL_SCHEMAS.get(lane, set()), 'Unsupported residual schema/role')
    return value


def _report_asset(name):
    return re.fullmatch(r'output/data/selection-grading/[0-9a-f]{64}/(?:[A-Za-z0-9_.-]+|parts/[0-9a-f]{64}\.json\.gz)', name) is not None


def _carry_residual(root, raw, files, committed):
    """Make new original/failure evidence visible before any saved replay.

    Mutable aliases/cache remain the exact committed frontier. No old record,
    source/configuration or original marker may change or disappear.
    """
    for name, expected in committed.items():
        require(name in files, 'Committed dependency missing from raw checkpoint')
        if files[name] != expected:
            require(_mutable_role(name) and name not in _MARKERS
                and not name.startswith(('pull/', 'tools/', 'config/')), 'Changed immutable checkpoint dependency')
    carried = {}
    for name, d in files.items():
        if name in committed or name == 'CONSTRUCTION_PROGRESS.json': continue
        if _mutable_role(name): continue
        source = raw / name
        if name.startswith('data/'):
            _residual_evidence(source, name)
        else:
            require(_report_asset(name), 'Unknown residual checkpoint role')
            # A partially produced23 asset is not a member of committed22.
            # Preserve it in the hash-verified raw checkpoint only; the normal
            # producer must validate any later complete generation before use.
            continue
        target = root / name; require(not target.exists() and not target.is_symlink(), 'Residual first recording collision')
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target); target.chmod(0o644)
        require(descriptor(target) == d, 'Copied residual bytes differ')
        carried[name] = d
    return carried


def verify_copied_frontier(work, root, profile=None):
    """Fresh actual parents, bundle roots and full copied-byte closure."""
    verify_parents(work, profile)
    value = decoded(work / MANIFEST); files, _ = manifest_files(value)
    raw = work / 'raw-checkpoint'
    require(all(descriptor(raw / name) == d for name, d in files.items()), 'Raw checkpoint changed')
    heads = {}
    for line in git(work, 'bundle', 'list-heads', str(work / BUNDLE)).decode().splitlines():
        oid, name = line.split(); require(re.fullmatch('[0-9a-f]{40}', oid) and name not in heads, 'Bundle roots')
        heads[name] = oid
    require(set(heads) == {'HEAD', 'refs/fixture/source'} and heads['refs/fixture/source'] == BASE
        and git(root, 'rev-parse', 'HEAD').decode().strip() == heads['HEAD']
        and git(root, 'rev-parse', BASE + '^{tree}').decode().strip() == TREE
        and not (root / '.git/objects/info/alternates').exists(), 'Copied actual source/Git roots')
    expected = {}
    for name, (mode, blob) in tracked(root).items():
        require(safe_name(name) and name in files, 'Copied tracked role')
        body = git(root, 'cat-file', 'blob', blob)
        d = dict(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        require((bool((root / name).stat().st_mode & 0o111)) == (mode == '100755'), 'Copied tracked executable mode changed')
        require(files[name] == d or profile is not None and _mutable_role(name), 'Changed immutable raw dependency')
        expected[name] = d
    if profile is not None:
        for name, d in files.items():
            if name in expected or name == 'CONSTRUCTION_PROGRESS.json' or _mutable_role(name): continue
            if name.startswith('data/'):_residual_evidence(raw / name, name)
            else:
                require(_report_asset(name), 'Unknown copied residual role')
                continue  # Unqualified next-generation assets remain raw only.
            expected[name] = d
    for lane in ('pull', 'tools', 'config', 'data', 'output'):
        for path in (root / lane).rglob('*'):
            require(not path.is_symlink() and (path.is_file() or path.is_dir()), 'Copied namespace type changed')
            require(path.suffix != '.pyc', 'Unexpected active bytecode in copied frontier')
    actual = tree_inventory(root)
    actual.update({name: descriptor(root / name) for name in _MARKERS if (root / name).exists()})
    require(actual == expected, 'Copied committed/residual inventory changed')
    git(root, 'fsck', '--full', '--no-reflogs')
    verify_parents(work, profile)
    return dict(fixture_head=heads['HEAD'], files=len(expected), carried_files=len(set(expected) - set(tracked(root))),
        inventory=expected, expected_inventory_sha256=hashlib.sha256(ci.canonical(expected)).hexdigest(),
        profile=profile_identity(profile))


def _qualify_residual(work, root, m, files, at):
    """No residual native receives trust without its real completed consumer."""
    committed = tracked(root); carried = set(files) - set(committed) - {'CONSTRUCTION_PROGRESS.json'}
    corrected = m['capture'].corrected; partial = m['partial']; evidence = m['ev']
    completions = []
    for path in sorted((root / 'data' / partial.COMPLETION_LANE).rglob('*.json.gz')):
        name = path.relative_to(root).as_posix()
        value = partial._saved(root, name, partial.COMPLETION_LANE)
        completions.append((name, value))
    checked = 0; checked_completions = set()
    def qualify(ref, value):
        scope = partial._saved(root, value['scope_receipt'], 'verification/partial-scopes')
        spec = corrected._saved_spec(root, scope)
        result = corrected.read_bundle(root, ref, spec, now=at)
        checked_completions.add(ref)
        return result
    for ref, value in completions:
        if ref in carried:qualify(ref, value)
    scope_refs = {value.get('scope_receipt') for _, value in completions}
    for name in carried:
        if name.startswith('data/verification/partial-scopes/'):
            require(name in scope_refs, 'Orphan residual scope has no completion')
    for name in sorted(carried):
        if not name.startswith('data/forward/'): continue
        native = _residual_evidence(root / name, name)
        require(native.get('schema_version') == corrected.NATIVE, 'Unsupported residual native model')
        matches = [(ref, value) for ref, value in completions if value.get('baseline_receipt') == name]
        require(bool(matches), 'Orphan residual native has no completed origin')
        for ref, value in matches:
            complete, _, actual_native = qualify(ref, value)
            require(actual_native == native and complete['baseline_receipt'] == name, 'Residual native/completion mismatch')
        checked += 1
    assets = {name for name in carried if _report_asset(name)}
    require(all(not (root / name).exists() for name in assets), 'Unqualified report asset entered committed frontier')
    return dict(qualified_new_natives=checked, qualified_residual_completions=len(checked_completions),
        carried_evidence_files=sum(name.startswith('data/') and not _mutable_role(name) for name in carried),
        carried_report_files=0, raw_unqualified_report_files=len(assets),
        residual_observation_cutoff=at.isoformat())


def check_saved(work, profile=None):
    import operating_diagnostic as h
    h.require_offline()
    here = Path(__file__).resolve().parent
    require(hashlib.sha256((here / 'operating_diagnostic.py').read_bytes()).hexdigest() == HARNESS
        and hashlib.sha256((here / 'diagnostic-seed-inputs.json').read_bytes()).hexdigest() == INPUTS, 'Frozen lineage changed')
    phase('parent_integrity'); verify_parents(work, profile)
    value = decoded(work / MANIFEST); raw = work / 'raw-checkpoint'
    phase('raw_restore')
    files = unpack_checkpoint(work / CHECKPOINT, raw, value)
    n = progress(decoded(raw / 'CONSTRUCTION_PROGRESS.json'), profile)
    phase('committed_git_restore')
    root, heads, residual = restore_committed(work, raw, files, profile)
    phase('lineage_binding')
    marker = decoded(root / 'FICTIONAL_ONLY.json')
    require(marker.get('reviewed_source') == BASE and marker.get('dimensions') == h.FULL, 'Full original fictional lineage')
    phases = decoded(root / 'FICTIONAL_PHASES.json')
    require(h.encoded(phases.get('contract')) == h.encoded(h.phase_contract())
        and phases.get('contract_sha256') == hashlib.sha256(h.encoded(h.phase_contract())).hexdigest(), 'Exact phase/input contract')
    before = tree_inventory(root); m = h.bind(root)
    at = h.START + timedelta(hours=h.SEED_HOUR, seconds=5 * n)
    provider = h.Provider(m, h.FULL, at)
    with retained_source_environment(), h.external(m, provider, root), h.patch.object(m['capture'], '_public_archive_commit',
            side_effect=lambda ref, tree: h.assert_local_tree(root, ref, tree)):
        phase('latest_saved_validation')
        generation = m['capture'].validate_generation(root)
        adjudication = None
        if profile is not None:
            # The saved22 generation is first checked at its own +110 cutoff.
            # The failed next update's real +115 originals stay separately dated.
            provider.at = at + timedelta(seconds=5)
            adjudication = _qualify_residual(work, root, m, files, provider.at)
        phase('retained_history_validation')
        metrics = h.workload(root, m)
    phase('final_integrity')
    require(metrics['complete_generations'] == n, 'Registry/committed frontier disagreement')
    require(tree_inventory(root) == before, 'Saved reconstruction changed evidence')
    if profile is None:require(not git(root, 'status', '--porcelain'), 'Saved reconstruction changed evidence')
    else:verified = verify_copied_frontier(work, root, profile)
    require(all(descriptor(raw / name) == d for name, d in files.items()), 'Raw partial checkpoint changed')
    git(root, 'fsck', '--full', '--no-reflogs')
    verify_parents(work, profile)
    return dict(schema_version='failed-seed-frontier-inspection-v1', status='COMMITTED_HISTORY_REPLAYED_RAW_RESIDUAL_UNQUALIFIED',
        application_source=BASE, application_tree=TREE, fixture_head=heads['HEAD'],
        recorded_generations=n, independently_replayed_committed_generations=metrics['complete_generations'],
        target_generations=24, raw_checkpoint_files=len(files), residual_working_files=residual,
        generation_sha256=generation['generation_sha256'], semantic_sha256=metrics['public_semantics_sha256'],
        rows=metrics['rows'], groups=metrics['groups'], outcomes=metrics['outcomes'], native=metrics['native'],
        source_and_original_clocks_preserved=True, raw_checkpoint_preserved=True,
        normalized_tar_mode='0600; committed checkout modes independently recovered from verified Git objects',
        retained_execution_source='Actual retained Git root; installer GITHUB_SHA absent only during saved-reader calls and restored afterward',
        archive_transport='actual local Git objects, public-commit transport replaced by exact local tree comparison',
        full_seed_admitted=False, continuation_authorized=False, current_checkpoint_qualified=False,
        residual_completion_or_revocation_not_adjudicated=profile is None,
        residual_evidence_preserved=profile is not None,
        residual_evidence_adjudication=adjudication,
        expected_inventory_sha256=verified['expected_inventory_sha256'] if profile is not None else None,
        origin_profile=profile_identity(profile),
        construction_performed=False, operating_qualification='NOT_RUN', resource_qualification='NOT_MEASURED_BY_THIS_INSPECTION')


def actual_identity(profile=None):
    selected = profile_identity(profile)
    api = ci.GitHub()
    run = api.get('/actions/runs/' + str(selected['run']))
    require((run.get('id'), run.get('head_sha'), run.get('run_attempt'), run.get('status'), run.get('conclusion'),
        run.get('workflow_id'), (run.get('actor') or {}).get('id'))
        == (selected['run'], selected['producer'], 1, 'completed', 'failure', 392359637, 208912933), 'Original failed invocation')
    artifact = api.get('/actions/artifacts/' + str(selected['artifact']))
    require((artifact.get('id'), artifact.get('size_in_bytes'), artifact.get('digest'), artifact.get('expired'),
        artifact.get('expires_at'), artifact.get('name')) == (selected['artifact'], selected['size'], 'sha256:' + selected['digest'], False,
        selected['expiry'], 'fictional-seed-preparation-' + str(selected['run'])), 'Original artifact identity')
    origin = artifact.get('workflow_run') or {}
    require(origin.get('id') == selected['run'] and origin.get('head_sha') == selected['producer']
        and origin.get('repository_id') == 1411185749 and origin.get('head_repository_id') == 1411185749,
        'Artifact repository/source binding')
    require(datetime.fromisoformat(selected['expiry'].replace('Z', '+00:00')) > datetime.now(timezone.utc), 'Expired original artifact')
    return artifact


def retrieve(work, profile=None):
    selected = profile_identity(profile)
    require(not work.exists(), 'New run-specific retrieval required')
    fs = os.statvfs(work.parent)
    require(fs.f_bavail * fs.f_frsize - (2 * DECODED_LIMIT + 6 * GIB)
        >= max(2 * GIB, fs.f_blocks * fs.f_frsize // 5), 'Complete concurrent disk allocation and reserve')
    mem = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
        if line.startswith(('MemTotal:', 'MemAvailable:'))}
    require(mem['MemAvailable'] >= 8 * GIB + max(2 * GIB, mem['MemTotal'] // 5), 'Conservative read-only memory preflight')
    before = actual_identity(profile); work.mkdir(mode=0o700); archive = work / 'artifact.zip'
    deadline = time.monotonic() + 240
    transport._download(dict(artifact_id=selected['artifact'], archive_bytes=selected['size'], archive_sha256=selected['digest']), archive, deadline=deadline)
    expected_parents = PARENTS if profile is None else _outer_parents(work, profile)
    transport._zip_inventory(archive); inventory = {}; total = 0; metadata = {}
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            name = item.filename
            require(name in ALLOW and name == item.orig_filename and name not in inventory and not item.is_dir()
                and item.external_attr >> 16 & 0o170000 in (0, stat.S_IFREG) and not item.flag_bits & 1
                and item.compress_type in (0, 8), 'Bounded outer member role')
            require(0 <= item.file_size <= transport.LIMIT and total + item.file_size <= transport.LIMIT, 'Outer decoded bound')
            data = bytearray(); h = hashlib.sha256(); count = 0
            target = (work / name).open('xb') if name in PARENTS else None
            try:
                with zipped.open(item) as source:
                    while True:
                        transport._check(deadline); raw = source.read(min(1024 ** 2, item.file_size + 1 - count))
                        if not raw: break
                        count += len(raw); require(count <= item.file_size, 'Outer member grew'); h.update(raw)
                        if target: target.write(raw)
                        if name.endswith('.json'):
                            require(len(data) + len(raw) <= transport.JSON_LIMIT, 'Outer JSON bound'); data.extend(raw)
                require(count == item.file_size, 'Truncated outer member')
            finally:
                if target: target.close()
            inventory[name] = dict(bytes=count, sha256=h.hexdigest()); total += count
            if name.endswith('.json'): metadata[name] = ci.decoded(bytes(data), transport.JSON_LIMIT)
    require(set(inventory) == ALLOW and all(inventory[name] == d for name, d in expected_parents.items()), 'Exact retained inventory')
    envelope = metadata['ARTIFACT_MANIFEST.json']
    require(envelope.get('schema_version') == 'cloud-seed-artifact-envelope-v1'
        and envelope.get('files') == {k: v for k, v in inventory.items() if k != 'ARTIFACT_MANIFEST.json'}
        and envelope.get('application_source') == BASE and envelope.get('preparation_status') == 'PREPARATION_FAILED'
        and envelope.get('operating_qualification') == 'NOT_RUN', 'Actual complete failure envelope')
    require(actual_identity(profile) == before and descriptor(archive) == dict(bytes=selected['size'], sha256=selected['digest']), 'Final retrieval identity/bytes')
    (work / 'RETRIEVAL.json').write_bytes(ci.canonical(dict(status='EXACT_FAILED_CHECKPOINT_BYTES_RECEIVED_NOT_RESTORED',
        artifact_id=selected['artifact'], artifact_sha256=selected['digest'], parents=expected_parents)))
    if profile is None: archive.unlink()  # Only this disposable download; retained original artifact/parents remain unchanged.


def hosted(work, action):
    expected = dict(GITHUB_REPOSITORY_ID='1411185749', GITHUB_ACTOR_ID='208912933', GITHUB_EVENT_NAME='workflow_dispatch',
        GITHUB_RUN_ATTEMPT='1', RUNNER_ENVIRONMENT='github-hosted', GITHUB_REF='refs/heads/upgrade/phase2-reproducible-comparison')
    require(all(os.environ.get(k) == v for k, v in expected.items()), 'Trusted fixed inspection invocation')
    root = Path(__file__).resolve().parents[1]
    require(git(root, 'rev-parse', 'HEAD').decode().strip() == os.environ.get('GITHUB_SHA'), 'Actual inspection source')
    require(work == Path(os.environ['RUNNER_TEMP']).resolve() / ('nfl-seed-frontier-' + os.environ['GITHUB_RUN_ID'])
        and work.parent.is_dir() and not work.is_symlink(), 'Exact run-specific inspection path')
    if action == 'verify':
        require(not any(os.environ.get(k) for k in ('GH_TOKEN', 'GITHUB_TOKEN', 'ODDS_API_KEY')), 'No application credential')
    return root


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('retrieve', 'verify')); p.add_argument('--work', type=Path, required=True)
    p.add_argument('--profile', choices=(PROFILE22,))
    args = p.parse_args(); start = time.monotonic(); work = args.work.absolute()
    phase('source_binding')
    code = hosted(work, args.action); identity = ci.source(code)
    if args.action == 'retrieve':
        phase('retrieval')
        retrieve(work, args.profile)
        phase('final_source_binding')
        require(ci.source(code) == identity, 'Inspection source changed during retrieval')
        return
    result = check_saved(work, args.profile)
    phase('final_source_binding')
    require(ci.source(code) == identity, 'Inspection source changed during saved reconstruction')
    selected = profile_identity(args.profile)
    result.update(inspection_source=os.environ['GITHUB_SHA'], artifact_id=selected['artifact'], artifact_sha256=selected['digest'],
        inspection_tree=identity['tree'], inspection_source_manifest_sha256=identity['source_manifest_sha256'],
        expires_at=selected['expiry'], verification_seconds=time.monotonic() - start)
    raw = ci.canonical(result); require(len(raw) <= 128 * 1024, 'Technical result bound')
    (work / 'FRONTIER.json').write_bytes(raw)
    print('CHECKPOINT_FRONTIER_JSON=' + raw.decode())
    print('CHECKPOINT_FRONTIER_SHA256=' + hashlib.sha256(raw).hexdigest())


if __name__ == '__main__':
    try: main()
    except BaseException as error:
        # No signed URLs, provider responses, environment or raw fixture records.
        report = failure_report(error)
        print('CHECKPOINT_FRONTIER_REJECTED=' + report['error_class'], file=sys.stderr)
        print('CHECKPOINT_FRONTIER_FAILURE_JSON=' + ci.canonical(report).decode(), file=sys.stderr)
        raise SystemExit(1) from None
