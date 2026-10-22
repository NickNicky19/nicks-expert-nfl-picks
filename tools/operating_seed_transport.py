"""One approved, bounded Actions-artifact retrieval before network isolation.

No upload, Git/ref mutation, fixture construction, or source qualification.
The four immutable seed parents still require diagnostic_seed.restore and fresh
application/source/evidence/admission checks after this transport completes.
An owner-reviewed populated approval is required; a template is not approval.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import struct
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import source_ci

REPOSITORY = source_ci.REPOSITORY
REPOSITORY_ID = source_ci.REPOSITORY_ID
WORKFLOW_PATH = '.github/workflows/prepare-diagnostic-seed.yml'
SCHEMA = 'operating-seed-actions-approval-v1'
SEED_FILES = {'working.tar.gz', 'fictional.pack', 'public-source.pack', 'SEED_MANIFEST.json'}
JSON_FILES = {'ADMISSION.json', 'COVERAGE.json', 'RESTORATION.json', 'PREPARATION_RESULT.json',
              'PREFLIGHT.json', 'RESOURCE.json', 'CAPABILITY.json', 'ANCESTORS.before.json',
              'ANCESTORS.after.json', 'ARTIFACT_MANIFEST.json'}
REQUIRED_JSON = {'ADMISSION.json', 'RESTORATION.json', 'PREPARATION_RESULT.json', 'RESOURCE.json', 'ARTIFACT_MANIFEST.json'}
ADMISSION_METRICS = ('working_tree_bytes', 'clean_checkout_bytes', 'staged_bytes', 'uploader_tar_bytes', 'packed_bytes')
LIMIT = 2 * 1024 ** 3
JSON_LIMIT = 16 * 1024 ** 2
CENTRAL_LIMIT = 64 * 1024
CHUNK = 1024 ** 2
HEX40 = re.compile(r'[0-9a-f]{40}')
HEX64 = re.compile(r'[0-9a-f]{64}')
APPROVAL_KEYS = {'schema_version', 'repository', 'repository_id', 'workflow_id', 'workflow_path',
                 'artifact_id', 'artifact_name', 'artifact_size_bytes', 'archive_bytes', 'archive_sha256',
                 'run_id', 'run_attempt', 'installer_commit', 'installer_tree', 'seed_manifest_sha256',
                 'seed_application_source', 'seed_harness_sha256', 'frozen_input_sha256', 'integrity_sha256', 'artifact_expires_at'}


class Rejected(ValueError):
    pass


def _check(deadline):
    if not isinstance(deadline, (int, float)) or not math.isfinite(deadline) or time.monotonic() >= deadline:
        raise Rejected('Whole-job retrieval deadline exhausted')


def _open_regular(path, limit):
    # Validate the opened object, never a pathname that can change before open.
    # NONBLOCK also prevents a substituted FIFO from blocking before fstat.
    try: descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error: raise Rejected('Transport dependency is not a readable regular file') from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode): raise Rejected('Transport dependency is not a regular file')
        if not 0 <= info.st_size <= limit: raise Rejected('Transport file exceeds its bound')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _chunks(path, limit, deadline=None):
    if deadline is not None: _check(deadline)
    descriptor = _open_regular(path, limit)
    size = 0
    try:
        while True:
            if deadline is not None: _check(deadline)
            # Read at most limit+1 bytes in total, including real file growth.
            chunk = os.read(descriptor, min(CHUNK, limit + 1 - size))
            if deadline is not None: _check(deadline)
            if not chunk: break
            size += len(chunk)
            if size > limit: raise Rejected('Transport file exceeds its bound')
            yield chunk
    finally:
        os.close(descriptor)


def _hash(path, deadline=None):
    h = hashlib.sha256(); size = 0
    for chunk in _chunks(path, LIMIT, deadline):
        size += len(chunk); h.update(chunk)
    return {'bytes': size, 'sha256': h.hexdigest()}


def _json(path, deadline=None, *, descriptor=None):
    try:
        raw = b''.join(_chunks(path, JSON_LIMIT, deadline))
        if descriptor is not None and {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} != descriptor:
            raise Rejected('Transport JSON bytes changed before parsing')
        value = source_ci.decoded(raw, JSON_LIMIT)
        if not isinstance(value, dict): raise Rejected('Transport JSON object required')
        return value
    except source_ci.Rejected as error: raise Rejected('Malformed transport JSON') from error


def _approval(value):
    if not isinstance(value, dict) or set(value) != APPROVAL_KEYS or value.get('schema_version') != SCHEMA:
        raise Rejected('Complete exact owner-approved artifact manifest is required')
    if (value['repository'], value['repository_id'], value['workflow_path']) != (REPOSITORY, REPOSITORY_ID, WORKFLOW_PATH):
        raise Rejected('Unapproved repository or preparation workflow')
    for key in ('workflow_id', 'artifact_id', 'run_id'):
        if type(value[key]) is not int or value[key] < 1: raise Rejected('Unpopulated artifact identity')
    if value['run_attempt'] != 1 or type(value['run_attempt']) is not int:
        raise Rejected('Only the approved first preparation attempt is supported')
    if value['artifact_name'] != 'fictional-seed-preparation-' + str(value['run_id']):
        raise Rejected('Unapproved artifact name')
    for key in ('artifact_size_bytes', 'archive_bytes'):
        if type(value[key]) is not int or not 0 < value[key] <= LIMIT: raise Rejected('Artifact size exceeds its bound')
    for key in ('installer_commit', 'installer_tree', 'seed_application_source'):
        if not isinstance(value[key], str) or not HEX40.fullmatch(value[key]): raise Rejected('Exact source identity is required')
    for key in ('archive_sha256', 'seed_manifest_sha256', 'seed_harness_sha256', 'frozen_input_sha256', 'integrity_sha256'):
        if not isinstance(value[key], str) or not HEX64.fullmatch(value[key]): raise Rejected('Exact approved digest is required')
    _stamp(value['artifact_expires_at'])
    return dict(value)


def _stamp(value):
    if not isinstance(value, str): raise Rejected('Missing authenticated timestamp')
    try: result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError: raise Rejected('Malformed authenticated timestamp') from None
    if result.tzinfo is None: raise Rejected('Unqualified authenticated timestamp')
    return result


def _identity(api, approved, deadline):
    def get(path):
        _check(deadline); value = api.get(path); _check(deadline)
        if not isinstance(value, dict): raise Rejected('Malformed authenticated metadata object')
        return value
    repo = get('')
    if (repo.get('id'), repo.get('full_name')) != (REPOSITORY_ID, REPOSITORY) or repo.get('private') is not False:
        raise Rejected('Public repository identity changed')
    workflow = get('/actions/workflows/' + str(approved['workflow_id']))
    if (workflow.get('id'), workflow.get('path')) != (approved['workflow_id'], WORKFLOW_PATH):
        raise Rejected('Preparation workflow identity changed')
    run = get('/actions/runs/' + str(approved['run_id']))
    attempt = get(f"/actions/runs/{approved['run_id']}/attempts/1")
    for record in (run, attempt):
        expected = {'id': approved['run_id'], 'run_attempt': 1, 'head_sha': approved['installer_commit'],
                    'workflow_id': approved['workflow_id'], 'path': WORKFLOW_PATH, 'event': 'workflow_dispatch',
                    'head_branch': 'upgrade/phase2-reproducible-comparison', 'status': 'completed', 'conclusion': 'success'}
        if type(record.get('run_attempt')) is not int or any(record.get(key) != value for key, value in expected.items()):
            raise Rejected('Approved first preparation attempt did not complete successfully')
        if ((record.get('repository') or {}).get('id'), (record.get('head_repository') or {}).get('id')) != (REPOSITORY_ID, REPOSITORY_ID):
            raise Rejected('Preparation run repository changed')
    if any(run.get(key) != attempt.get(key) for key in ('run_started_at', 'updated_at')):
        raise Rejected('Preparation attempt identity changed')
    artifact = get('/actions/artifacts/' + str(approved['artifact_id']))
    expected = {'id': approved['artifact_id'], 'name': approved['artifact_name'], 'size_in_bytes': approved['artifact_size_bytes'],
                'digest': 'sha256:' + approved['archive_sha256'], 'expires_at': approved['artifact_expires_at']}
    if artifact.get('expired') is not False or any(artifact.get(key) != value for key, value in expected.items()): raise Rejected('Approved artifact identity, digest, size or availability changed')
    link = artifact.get('workflow_run') or {}
    if any(link.get(key) != value for key, value in {'id': approved['run_id'], 'repository_id': REPOSITORY_ID,
           'head_repository_id': REPOSITORY_ID, 'head_sha': approved['installer_commit'],
           'head_branch': 'upgrade/phase2-reproducible-comparison'}.items()):
        raise Rejected('Artifact is not from the exact approved preparation source')
    created, expires = _stamp(artifact.get('created_at')), _stamp(artifact.get('expires_at'))
    if not _stamp(run.get('run_started_at')) <= created <= _stamp(run.get('updated_at')):
        raise Rejected('Artifact creation is outside its authenticated preparation attempt')
    if expires <= datetime.now(timezone.utc) or expires <= created or created > datetime.now(timezone.utc):
        raise Rejected('Approved artifact is expired')
    return {'artifact': artifact, 'run': run}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl): return None


def _download(approved, target, *, deadline, opener=None):
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token: raise Rejected('Read-only Actions credential is unavailable')
    url = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{approved['artifact_id']}/zip"
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28', 'Cache-Control': 'no-cache', 'User-Agent': 'nfl-seed-transport-v1'}
    opener = opener or urllib.request.build_opener(_NoRedirect)
    _check(deadline)
    try:
        try: response = opener.open(urllib.request.Request(url, headers=headers), timeout=min(30, max(0.001, deadline - time.monotonic())))
        except urllib.error.HTTPError as error:
            target_url = urllib.parse.urlsplit(error.headers.get('Location', ''))
            if (error.code not in (301, 302, 303, 307, 308) or target_url.scheme != 'https' or target_url.username
                    or target_url.password or not target_url.hostname or target_url.port not in (None, 443)
                    or not (target_url.hostname.endswith('.blob.core.windows.net') or target_url.hostname.endswith('.actions.githubusercontent.com'))):
                raise Rejected('Unapproved artifact redirect') from None
            _check(deadline)
            response = opener.open(urllib.request.Request(target_url.geturl(), headers={'User-Agent': 'nfl-seed-transport-v1', 'Cache-Control': 'no-cache'}), timeout=min(30, max(0.001, deadline - time.monotonic())))
        _check(deadline)
        with response, target.open('xb') as stream:
            length = response.headers.get('Content-Length')
            if length is not None and (not length.isdigit() or int(length) != approved['archive_bytes']):
                raise Rejected('Artifact transfer size does not match approval')
            digest = hashlib.sha256(); count = 0
            while True:
                _check(deadline)
                chunk = response.read(min(CHUNK, approved['archive_bytes'] + 1 - count)); _check(deadline)
                if not chunk: break
                count += len(chunk)
                if count > approved['archive_bytes'] or count > LIMIT: raise Rejected('Artifact transfer exceeds its bound')
                stream.write(chunk); digest.update(chunk)
            if count != approved['archive_bytes'] or digest.hexdigest() != approved['archive_sha256']:
                raise Rejected('Artifact transfer bytes do not match approval')
    except Rejected: raise
    except (OSError, urllib.error.URLError, ValueError):
        raise Rejected('Artifact transfer unavailable') from None


def _zip_inventory(path):
    # Bound the central directory BEFORE ZipFile allocates its member list.
    with path.open('rb') as stream:
        size = path.stat().st_size
        stream.seek(max(0, size - 65557)); tail = stream.read(65557)
        position = tail.rfind(b'PK\x05\x06')
        if position < 0 or len(tail) - position < 22: raise Rejected('Missing bounded ZIP directory')
        signature, disk, central_disk, disk_count, count, length, offset, comment = struct.unpack('<4s4H2LH', tail[position:position + 22])
        end = size - len(tail) + position
        if position + 22 + comment != len(tail) or disk or central_disk or disk_count != count:
            raise Rejected('Unsupported multipart or trailing ZIP data')
        locator_present = end >= 20 and tail[max(0, position - 20):position - 16] == b'PK\x06\x07'
        if locator_present or count == 65535 or length == 0xffffffff or offset == 0xffffffff:
            # The supported single-disk ZIP64 directory has no extension data.
            if end < 76: raise Rejected('Truncated ZIP64 directory')
            stream.seek(end - 20); locator = stream.read(20)
            sig, directory_disk, zip64_offset, disks = struct.unpack('<4sLQL', locator)
            if sig != b'PK\x06\x07' or directory_disk or disks != 1: raise Rejected('Unsupported ZIP64 locator')
            stream.seek(zip64_offset); raw = stream.read(56)
            if len(raw) != 56: raise Rejected('Truncated ZIP64 directory')
            sig, extra, _, _, disk, central_disk, disk_count, count, length, offset = struct.unpack('<4sQ2H2L4Q', raw)
            if sig != b'PK\x06\x06' or extra != 44 or disk or central_disk or disk_count != count or zip64_offset + 56 != end - 20:
                raise Rejected('Unsupported ZIP64 directory')
            end = zip64_offset
        if not 4 <= count <= len(SEED_FILES | JSON_FILES) or length > CENTRAL_LIMIT or offset + length != end:
            raise Rejected('ZIP inventory exceeds its supported bound')
    return count


def _extract(archive, stage, deadline):
    _check(deadline)
    count = _zip_inventory(archive); inventory = {}; total = 0
    try:
        with zipfile.ZipFile(archive) as zipped:
            members = zipped.infolist()
            if len(members) != count: raise Rejected('ZIP directory inventory mismatch')
            for member in members:
                _check(deadline)
                name = member.filename; kind = member.external_attr >> 16 & 0o170000
                if (member.orig_filename != name or name not in SEED_FILES | JSON_FILES or name in inventory or member.is_dir()
                        or kind not in (0, stat.S_IFREG) or member.flag_bits & 1
                        or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise Rejected('Unexpected, duplicate, unsafe or unsupported artifact member')
                if member.file_size < 0 or member.file_size > LIMIT or total + member.file_size > LIMIT:
                    raise Rejected('Artifact decoded content exceeds its bound')
                if name.endswith('.json') and member.file_size > JSON_LIMIT: raise Rejected('Artifact JSON exceeds its bound')
                h = hashlib.sha256(); size = 0
                with zipped.open(member) as source, (stage / name).open('xb') as output:
                    while True:
                        _check(deadline)
                        raw = source.read(min(CHUNK, member.file_size + 1 - size)); _check(deadline)
                        if not raw: break
                        size += len(raw)
                        if size > member.file_size or total + size > LIMIT: raise Rejected('Artifact member grew beyond its bound')
                        output.write(raw); h.update(raw)
                if size != member.file_size: raise Rejected('Truncated artifact member')
                total += size; inventory[name] = {'bytes': size, 'sha256': h.hexdigest()}
    except Rejected: raise
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        raise Rejected('Artifact ZIP integrity validation failed') from None
    if not SEED_FILES | REQUIRED_JSON <= set(inventory): raise Rejected('Missing approved seed parents or preparation results')
    return inventory


def _content(stage, inventory, approved, deadline=None):
    metadata = {name: _json(stage / name, deadline, descriptor=inventory[name]) for name in inventory if name in JSON_FILES or name == 'SEED_MANIFEST.json'}
    artifact, seed = metadata['ARTIFACT_MANIFEST.json'], metadata['SEED_MANIFEST.json']
    if inventory['SEED_MANIFEST.json']['sha256'] != approved['seed_manifest_sha256']:
        raise Rejected('Seed manifest differs from its approved original bytes')
    if seed.get('full_admitted') is not True or (seed.get('schema_version'), seed.get('application_source'), seed.get('harness_sha256')) != (
            'fictional-operating-seed-v1', approved['seed_application_source'], approved['seed_harness_sha256']):
        raise Rejected('Unsupported original seed/source/harness identity')
    if artifact.get('schema_version') != 'cloud-seed-artifact-envelope-v1' or artifact.get('files') != {k: v for k, v in inventory.items() if k != 'ARTIFACT_MANIFEST.json'}:
        raise Rejected('Artifact envelope does not bind its complete actual inventory')
    if (artifact.get('application_source'), artifact.get('installer'), artifact.get('integrity_sha256')) != (
            approved['seed_application_source'], {'head': approved['installer_commit'], 'tree': approved['installer_tree']}, approved['integrity_sha256']):
        raise Rejected('Artifact original preparation/source binding changed')
    if (artifact.get('preparation_status'), artifact.get('resource_verdict'), artifact.get('operating_qualification')) != (
            'PREPARATION_COMPLETE_NOT_OPERATING_QUALIFIED', 'PASS', 'NOT_RUN'):
        raise Rejected('Incomplete or unqualified preparation output')
    result = metadata['PREPARATION_RESULT.json']
    if (result.get('status'), result.get('seed_manifest_sha256'), result.get('input_contract_sha256'), result.get('application_source'), result.get('harness_sha256')) != (
            'PREPARATION_COMPLETE_NOT_OPERATING_QUALIFIED', approved['seed_manifest_sha256'], approved['frozen_input_sha256'], approved['seed_application_source'], approved['seed_harness_sha256']):
        raise Rejected('Preparation result does not bind the approved seed/input')
    if metadata['ADMISSION.json'].get('status') != 'ADMITTED' or metadata['RESTORATION.json'].get('status') != 'PASS_SAVED_RECONSTRUCTION':
        raise Rejected('Preparation did not retain complete admission/restoration')
    if (seed.get('admission_sha256') != hashlib.sha256(source_ci.canonical(metadata['ADMISSION.json'])).hexdigest()
            or seed.get('semantic_sha256') != (metadata['ADMISSION.json'].get('metrics') or {}).get('public_semantics_sha256')
            or seed.get('semantic_sha256') != metadata['RESTORATION.json'].get('semantic_sha256')):
        raise Rejected('Seed admission/restoration semantic bindings differ')
    if (seed.get('construction_source') != approved['seed_application_source']
            or (seed.get('roots') or {}).get('public_source') != approved['seed_application_source']
            or not isinstance((seed.get('roots') or {}).get('fictional_head'), str)
            or not HEX40.fullmatch(seed['roots']['fictional_head'])):
        raise Rejected('Seed original source/Git-root binding differs')
    if metadata['RESOURCE.json'].get('resource_verdict') != 'PASS': raise Rejected('Preparation resource verdict is not qualified')
    descriptors = [seed.get('working'), *(seed.get('packs') or [])]
    if len(descriptors) != 3 or any(not isinstance(item, dict) for item in descriptors): raise Rejected('Incomplete seed parent descriptors')
    if {item.get('name') for item in descriptors} != SEED_FILES - {'SEED_MANIFEST.json'}: raise Rejected('Incorrect seed dependency roles')
    for descriptor in descriptors:
        if (type(descriptor.get('bytes')) is not int or not 0 < descriptor['bytes'] <= LIMIT
                or not isinstance(descriptor.get('sha256'), str) or not HEX64.fullmatch(descriptor['sha256'])):
            raise Rejected('Invalid typed seed parent descriptor')
        if {key: descriptor.get(key) for key in ('bytes', 'sha256')} != inventory[descriptor['name']]:
            raise Rejected('Seed parent content does not match its original manifest')
    return metadata


def retrieve(code, destination, approval, *, deadline, api=None, opener=None):
    """Retrieve once into a NEW directory, then let existing restore validate it.

    At peak, download ZIP and decoded transport parents coexist (up to 4 GiB),
    separately from the existing seed's up-to-8-GiB expanded working tree/Git
    restoration. The caller must admit the complete concurrent disk allocation.
    api/opener are test-only dependency injection; no caller-supplied PASS path.
    """
    _check(deadline)
    if deadline - time.monotonic() > 1200: raise Rejected('Retrieval deadline exceeds the unchanged whole-job bound')
    approved = _approval(approval); code = Path(code).resolve(); destination = Path(destination)
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir() or destination.parent.is_symlink():
        raise Rejected('A fresh existing-parent retrieval location is required')
    if _hash(code / 'tools/diagnostic-seed-inputs.json', deadline)['sha256'] != approved['frozen_input_sha256']:
        raise Rejected('Consumer frozen fictional input contract changed')
    api = api or source_ci.GitHub(); before = _identity(api, approved, deadline)
    stage = Path(tempfile.mkdtemp(prefix=destination.name + '.retrieving-', dir=destination.parent))
    try:
        archive = stage / 'artifact.zip'; _download(approved, archive, deadline=deadline, opener=opener)
        inventory = _extract(archive, stage, deadline); _check(deadline)
        metadata = _content(stage, inventory, approved, deadline); _check(deadline)
        after = _identity(api, approved, deadline)
        if after != before: raise Rejected('Artifact or preparation provenance changed during retrieval')
        if stage.is_symlink() or not stage.is_dir(): raise Rejected('Retrieval namespace changed before promotion')
        # Fresh bytes after all final transport calls, before local promotion.
        for name, descriptor in inventory.items():
            if _hash(stage / name, deadline) != descriptor: raise Rejected('Retrieved dependency changed before promotion')
        if _hash(code / 'tools/diagnostic-seed-inputs.json', deadline)['sha256'] != approved['frozen_input_sha256']:
            raise Rejected('Consumer input contract changed during retrieval')
        original_metrics = metadata['ADMISSION.json'].get('metrics')
        if not isinstance(original_metrics, dict) or any(
                type(original_metrics.get(key)) is not int or original_metrics[key] < 0 for key in ADMISSION_METRICS):
            raise Rejected('Original admission requires all five nonnegative integer byte metrics')
        admission_metrics = {key: original_metrics[key] for key in ADMISSION_METRICS}
        for name in (set(inventory) - SEED_FILES) | {'artifact.zip'}: (stage / name).unlink()
        if destination.exists() or destination.is_symlink(): raise Rejected('Retrieval destination appeared during transfer')
        _check(deadline)
        stage.rename(destination)
        return {'schema_version': 'operating-seed-artifact-retrieval-v1', 'artifact_id': approved['artifact_id'],
                'run_id': approved['run_id'], 'run_attempt': 1, 'archive_sha256': approved['archive_sha256'],
                'seed_manifest_sha256': approved['seed_manifest_sha256'], 'parents': {name: inventory[name] for name in sorted(SEED_FILES)},
                'admission_metrics': admission_metrics,
                'validated_preparation_members': sorted(set(inventory) - SEED_FILES), 'expires_at': before['artifact']['expires_at'],
                'claim': 'TRANSPORT_ONLY_FRESH_RESTORATION_AND_ADMISSION_STILL_REQUIRED'}
    finally:
        if stage.exists(): shutil.rmtree(stage)  # Only new reproducible transport scratch; never original evidence.


def read_approval(path, expected_file_sha256, *, deadline=None):
    """Bind the complete private owner manifest by its ordinary file checksum."""
    path = Path(path)
    if not isinstance(expected_file_sha256, str) or not HEX64.fullmatch(expected_file_sha256):
        raise Rejected('Exact owner approval file checksum required')
    raw = b''.join(_chunks(path, JSON_LIMIT, deadline))
    if hashlib.sha256(raw).hexdigest() != expected_file_sha256:
        raise Rejected('Owner approval file bytes changed')
    try: value = source_ci.decoded(raw, JSON_LIMIT)
    except source_ci.Rejected as error: raise Rejected('Malformed owner approval file') from error
    return _approval(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--approval-sha256', required=True)
    parser.add_argument('--deadline-monotonic', type=float, required=True)
    args = parser.parse_args()
    try:
        approved = read_approval(args.approval, args.approval_sha256, deadline=args.deadline_monotonic)
        result = retrieve(args.code, args.destination, approved, deadline=args.deadline_monotonic)
        result['approval_file_sha256'] = args.approval_sha256
        print(source_ci.canonical(result).decode())
    except (Rejected, source_ci.Rejected, OSError, KeyError, TypeError, ValueError, RecursionError, UnicodeError, zipfile.BadZipFile):
        # Never print signed download URLs, token headers, private approval
        # contents, raw response bodies or fixture bytes.
        print('Approved seed transport failed; no qualified restored seed is claimed', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__': main()
