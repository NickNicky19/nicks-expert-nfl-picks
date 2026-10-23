"""Focused controls: fictional tiny archives/Git, never an admitted full seed."""
import copy
import contextlib
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / 'tools'))
import seed_checkpoint_frontier as f


class Checkpoint(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.base = Path(self.temp.name)
        self.name = 'data/verification/example.json'
        self.raw = b'{"software_test":"fictional"}'
        self.manifest = dict(status='INCOMPLETE_NOT_ADMITTED_NOT_RESUME_AUTHORIZED',
            application_source=f.BASE, input_contract_sha256=f.INPUTS,
            files={self.name: dict(bytes=len(self.raw), sha256=hashlib.sha256(self.raw).hexdigest())})

    def tearDown(self): self.temp.cleanup()

    def archive(self, entries=None):
        path = self.base / 'checkpoint.tar.gz'
        with tarfile.open(path, 'w:gz') as tar:
            for name, raw, kind in entries or [(self.name, self.raw, tarfile.REGTYPE)]:
                info = tarfile.TarInfo(name); info.size = len(raw); info.mode = 0o600; info.mtime = 0; info.type = kind
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE): info.linkname = 'outside'
                tar.addfile(info, io.BytesIO(raw) if kind == tarfile.REGTYPE else None)
        return path

    def unpack(self, entries=None):
        return f.unpack_checkpoint(self.archive(entries), self.base / 'raw', self.manifest)

    def test_real_streamed_bytes_and_normalized_modes(self):
        self.assertEqual(self.unpack(), self.manifest['files'])
        path = self.base / 'raw' / self.name
        self.assertEqual(path.read_bytes(), self.raw); self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_actual_writer_long_path_pax_extension(self):
        self.name = 'output/data/selection-grading/' + 'a' * 64 + '/parts/' + 'b' * 64 + '.json.gz'
        self.manifest['files'] = {self.name: dict(bytes=len(self.raw), sha256=hashlib.sha256(self.raw).hexdigest())}
        self.assertEqual(self.unpack(), self.manifest['files'])

    def test_gzip_crc_truncation_and_nonzero_trailer_rejected(self):
        archive = self.archive(); original = archive.read_bytes()
        for label, raw in [('crc', original[:-8] + b'\xff' * 8), ('truncated', original[:-4]),
                           ('trailing', gzip.compress(gzip.decompress(original) + b'extra'))]:
            archive.write_bytes(raw)
            with self.subTest(label=label), self.assertRaises((OSError, EOFError, ValueError)):
                f.unpack_checkpoint(archive, self.base / label, self.manifest)

    def test_unsupported_pax_overrides_fail(self):
        for payload in (b'12 size=123\n', b'9 path=x\n', b'0 path=x\n'):
            with self.subTest(payload=payload), self.assertRaises(ValueError): f.pax_path(payload)

    def test_archive_byte_change_rejected(self):
        with self.assertRaisesRegex(ValueError, 'hash'): self.unpack([(self.name, b'x' * len(self.raw), tarfile.REGTYPE)])

    def test_duplicate_tar_member(self):
        entry = (self.name, self.raw, tarfile.REGTYPE)
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.unpack([entry, entry])

    def test_unknown_member(self):
        with self.assertRaises(ValueError): self.unpack([('data/other.json', self.raw, tarfile.REGTYPE)])

    def test_symlink_and_hardlink_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                f.unpack_checkpoint(self.archive([(self.name, b'', kind)]), self.base / ('raw-' + kind.decode()), self.manifest)

    def test_size_mismatch(self):
        with self.assertRaisesRegex(ValueError, 'bound'): self.unpack([(self.name, self.raw + b'x', tarfile.REGTYPE)])

    def test_missing_member(self):
        self.manifest['files']['output/data/required.json'] = self.manifest['files'][self.name]
        with self.assertRaisesRegex(ValueError, 'membership'): self.unpack()

    def test_noncanonical_and_unrelated_paths(self):
        for name in ('../outside', '/tmp/outside', 'data/../outside', 'data//x', './data/x', '.git/config',
                     'data\\x', 'data', 'tools', '', None):
            with self.subTest(name=name): self.assertFalse(f.safe_name(name))

    def test_declared_overlapping_paths(self):
        self.manifest['files']['data/verification'] = self.manifest['files'][self.name]
        with self.assertRaisesRegex(ValueError, 'Overlapping'): f.manifest_files(self.manifest)

    def test_bool_or_oversized_lengths(self):
        for value in (True, -1, f.FILE_LIMIT + 1):
            self.manifest['files'][self.name]['bytes'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): f.manifest_files(self.manifest)

    def test_complete_inventory_limit(self):
        with patch.object(f, 'DECODED_LIMIT', len(self.raw) - 1), self.assertRaises(ValueError): f.manifest_files(self.manifest)

    def test_wrong_lineage_and_fake_admission(self):
        for key, value in (('application_source', 'a' * 40), ('input_contract_sha256', 'b' * 64), ('status', 'ADMITTED')):
            bad = copy.deepcopy(self.manifest); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): f.manifest_files(bad)

    def test_immutable_new_restoration_root(self):
        root = self.base / 'raw'; root.mkdir(); (root / 'keep').write_text('unchanged')
        with self.assertRaisesRegex(ValueError, 'Fresh'): self.unpack()
        self.assertEqual((root / 'keep').read_text(), 'unchanged')

    def test_duplicate_json_keys(self):
        p = self.base / 'x.json'; p.write_bytes(b'{"x":1,"x":2}')
        with self.assertRaises(ValueError): f.decoded(p)

    def test_symlink_json(self):
        p = self.base / 'x.json'; p.write_text('{}'); q = self.base / 'link.json'; q.symlink_to(p)
        with self.assertRaises(ValueError): f.decoded(q)

    def test_recorded_progress_has_no_admission_upgrade(self):
        value = dict(generation=13, target=24, wall_clock=datetime.now(timezone.utc).isoformat())
        self.assertEqual(f.progress(value), 13)
        for key, bad in (('generation', True), ('generation', 24), ('target', 13), ('wall_clock', '2026-10-23T01:00:00')):
            changed = dict(value); changed[key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError): f.progress(changed)

    def test_same_size_dependency_mutation_is_rehashed(self):
        p = self.base / 'same'; p.write_bytes(b'aaa'); old = p.stat(); before = f.descriptor(p)
        p.write_bytes(b'bbb'); os.utime(p, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.assertNotEqual(f.descriptor(p), before)

    def test_parent_race_after_saved_validator_cannot_return_success(self):
        import operating_diagnostic as h
        work = self.base / 'operation'; work.mkdir()
        (work / f.MANIFEST).write_text('{"fictional_control":true}')
        (work / f.CHECKPOINT).write_bytes(b'not-read-by-this-mocked-replay-control')
        bundle = work / f.BUNDLE; bundle.write_bytes(b'aa')
        parents = {name: f.descriptor(work / name) for name in (f.MANIFEST, f.CHECKPOINT, f.BUNDLE)}
        raw = work / 'raw-checkpoint'; raw.mkdir()
        (raw / 'CONSTRUCTION_PROGRESS.json').write_text(json.dumps(dict(generation=13, target=24, wall_clock='2026-10-23T14:32:21+00:00')))
        root = work / 'mock-committed'; root.mkdir()
        (root / 'FICTIONAL_ONLY.json').write_text(json.dumps(dict(reviewed_source=f.BASE, dimensions=h.FULL)))
        (root / 'FICTIONAL_PHASES.json').write_text(json.dumps(dict(contract=h.phase_contract(),
            contract_sha256=hashlib.sha256(h.encoded(h.phase_contract())).hexdigest())))
        capture = SimpleNamespace(_public_archive_commit=lambda *args: None, validate_generation=lambda _: {'generation_sha256': 'a' * 64})
        def mutate(*_):
            old = bundle.stat(); bundle.write_bytes(b'bb'); os.utime(bundle, ns=(old.st_atime_ns, old.st_mtime_ns))
            return dict(complete_generations=13, public_semantics_sha256='b' * 64, rows=1, groups=1, outcomes=1, native=1)
        with patch.object(f, 'PARENTS', parents), patch.object(f, 'unpack_checkpoint', return_value={}), \
                patch.object(f, 'restore_committed', return_value=(root, {'HEAD': 'c' * 40}, {})), \
                patch.object(f, 'tree_inventory', return_value={}), patch.object(f, 'git', return_value=b''), \
                patch.object(h, 'require_offline'), patch.object(h, 'bind', return_value={'capture': capture}), \
                patch.object(h, 'Provider'), patch.object(h, 'external', return_value=contextlib.nullcontext()), \
                patch.object(h, 'workload', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'parent bytes'): f.check_saved(work)


class GitFrontier(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.base = Path(self.temp.name)
        self.repo = self.base / 'producer'; self.repo.mkdir()
        self.g('init', '-q'); self.g('config', 'user.name', 'Fictional software test')
        self.g('config', 'user.email', 'fictional@example.invalid')
        helper = subprocess.check_output(['git', '-C', str(CODE), 'show', f.BASE + ':tools/data_integrity_v2.py'])
        for name, raw in {'tools/data_integrity_v2.py': helper, 'pull/example.py': b'# Fictional unit source\n',
                          'config/phase2.json': b'{"fictional":true}', 'output/data/latest.json': b'{"generation":12}'}.items():
            p = self.repo / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
        self.g('add', '.'); self.g('commit', '-qm', 'Tiny fictional source; not production evidence')
        self.source = self.g('rev-parse', 'HEAD').decode().strip(); self.tree = self.g('rev-parse', 'HEAD^{tree}').decode().strip()
        self.g('update-ref', 'refs/fixture/source', self.source)
        (self.repo / 'output/data/latest.json').write_bytes(b'{"generation":13}')
        self.g('add', '.'); self.g('commit', '-qm', 'Tiny fictional committed frontier')
        self.head = self.g('rev-parse', 'HEAD').decode().strip()
        self.work = self.base / 'work'; self.work.mkdir()
        self.g('bundle', 'create', str(self.work / f.BUNDLE), 'HEAD', 'refs/fixture/source')
        self.raw = self.work / 'raw'; self.raw.mkdir()
        for p in self.repo.rglob('*'):
            if p.is_file() and '.git' not in p.parts:
                q = self.raw / p.relative_to(self.repo); q.parent.mkdir(parents=True, exist_ok=True); q.write_bytes(p.read_bytes())
        self.scope = {p.relative_to(self.raw).as_posix(): f.descriptor(p) for p in self.raw.rglob('*') if p.is_file()}

    def tearDown(self): self.temp.cleanup()

    def g(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL)

    def restore(self):
        with patch.object(f, 'BASE', self.source), patch.object(f, 'TREE', self.tree):
            return f.restore_committed(self.work, self.raw, self.scope)

    def test_real_independent_git_restore_preserves_partial_next_files(self):
        p = self.raw / 'output/data/latest.json'; p.write_bytes(b'{"generation":14}'); self.scope['output/data/latest.json'] = f.descriptor(p)
        extra = self.raw / 'data/verification/future.json'; extra.parent.mkdir(parents=True); extra.write_text('{"fictional":true}')
        self.scope['data/verification/future.json'] = f.descriptor(extra)
        root, heads, residual = self.restore()
        self.assertEqual(heads['HEAD'], self.head)
        self.assertEqual(residual, dict(new=1, changed=1, missing_from_checkpoint=0))
        self.assertEqual((root / 'output/data/latest.json').read_bytes(), b'{"generation":13}')
        self.assertEqual(p.read_bytes(), b'{"generation":14}'); self.assertTrue(extra.exists())
        self.assertNotEqual(root, self.raw); self.assertFalse((root / '.git/objects/info/alternates').exists())

    def test_corrupt_bundle_is_not_substituted(self):
        p = self.work / f.BUNDLE; p.write_bytes(b'corrupt')
        with self.assertRaises(subprocess.SubprocessError): self.restore()

    def test_actual_changed_source_bytes_rejected(self):
        p = self.raw / 'pull/example.py'; p.write_text('# same path, unsupported implementation\n')
        self.scope['pull/example.py'] = f.descriptor(p)
        with self.assertRaisesRegex(ValueError, 'B3 code'): self.restore()

    def test_untracked_extra_executable_rejected(self):
        p = self.raw / 'tools/extra.py'; p.write_text('# unknown source\n'); self.scope['tools/extra.py'] = f.descriptor(p)
        with self.assertRaisesRegex(ValueError, 'executable inventory'): self.restore()

    def test_missing_committed_dependency_rejected(self):
        del self.scope['output/data/latest.json']
        with self.assertRaisesRegex(ValueError, 'missing'): self.restore()


class SafeDiagnostics(unittest.TestCase):
    def test_nested_git_failure_identifies_role_without_raw_payload(self):
        private = 'https://example.invalid/?token=DO_NOT_PRINT'
        error = subprocess.CalledProcessError(128,
            ['/usr/bin/git', '-C', '/private/owner-path', 'cat-file', 'blob', private],
            output=b'PRIVATE_OUTPUT', stderr=b'fatal: Not a valid object name '+private.encode())
        with patch.object(f, 'DIAGNOSTIC_PHASE', 'latest_saved_validation'):
            report = f.failure_report(error)
        self.assertEqual((report['phase'], report['command_role'], report['command_verb'], report['returncode']),
                         ('latest_saved_validation', 'git', 'cat-file', 128))
        self.assertEqual(report['stderr_class'], 'GIT_OBJECT_UNAVAILABLE')
        raw = json.dumps(report)
        for value in (private, 'DO_NOT_PRINT', '/private', 'PRIVATE_OUTPUT', 'fatal:'):
            self.assertNotIn(value, raw)

    def test_string_command_and_unknown_exception_cannot_be_logged(self):
        secret = 'https://example.invalid/private-owner-data'
        error = subprocess.CalledProcessError(2, secret, stderr=secret.encode())
        report = f.failure_report(error)
        self.assertEqual(report['command_role'], 'subprocess')
        self.assertIsNone(report['command_verb'])
        self.assertNotIn(secret, json.dumps(report))
        invented = type('PrivateOwnerSecret', (Exception,), {})(secret)
        self.assertEqual(f.failure_report(invented)['error_class'], 'OTHER_ERROR')
        self.assertNotIn('PrivateOwnerSecret', json.dumps(f.failure_report(invented)))

    def test_phase_is_closed_and_does_not_change_failure_semantics(self):
        with patch.object(f, 'DIAGNOSTIC_PHASE', 'entry'), contextlib.redirect_stdout(io.StringIO()):
            f.phase('retained_history_validation')
            self.assertEqual(f.DIAGNOSTIC_PHASE, 'retained_history_validation')
            with self.assertRaises(ValueError): f.phase('https://invalid/private')
            self.assertEqual(f.DIAGNOSTIC_PHASE, 'retained_history_validation')
        error = subprocess.TimeoutExpired(['/usr/bin/python3.12', '-c', 'private code'], 3)
        report = f.failure_report(error)
        self.assertEqual(report['command_role'], 'python')
        self.assertIsNone(report['returncode'])
        self.assertNotIn('private code', json.dumps(report))

    def test_unknown_traceback_paths_and_error_messages_are_excluded(self):
        try:
            raise ValueError('/private/path?credential=DO_NOT_PRINT')
        except ValueError as error:
            report = f.failure_report(error)
        self.assertEqual(report['public_call_frames'], [])
        self.assertNotIn('DO_NOT_PRINT', json.dumps(report))


class RetainedSourceNamespace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)/'actual-retained-source'
        cls.root.mkdir()
        rows = subprocess.check_output(['git','-C',str(CODE),'ls-tree','-r','-z',f.BASE,'--','pull','tools','config'])
        total = 0
        for row in rows.split(b'\0'):
            if not row: continue
            left, name = row.split(b'\t',1); mode, kind, blob = left.decode().split()
            if kind != 'blob' or mode != '100644': raise AssertionError('Unexpected retained public source role')
            raw = subprocess.check_output(['git','-C',str(CODE),'cat-file','blob',blob]); total += len(raw)
            if total > 2*1024**2: raise AssertionError('Bounded public source probe exceeded')
            target = cls.root/name.decode(); target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw)
        f.git(cls.root,'init','-q')
        f.git(cls.root,'-c','user.name=FictionalNamespaceControl','-c','user.email=fictional@example.invalid','add','.')
        f.git(cls.root,'-c','user.name=FictionalNamespaceControl','-c','user.email=fictional@example.invalid',
              '-c','commit.gpgsign=false','commit','-qm','Actual retained source bytes; isolated software-test commit')
        cls.head=f.git(cls.root,'rev-parse','HEAD').decode().strip()
        cls.installer=subprocess.check_output(['git','-C',str(CODE),'rev-parse','HEAD'],text=True).strip()
        cls.program=("import json,subprocess,sys;sys.path[:0]=['tools','pull'];import data_integrity_v2 as d\n"
            "try: result={'actual_source':d.recording_source()}\n"
            "except subprocess.CalledProcessError as e: result={'subprocess_rejected':True,'returncode':e.returncode}\n"
            "print(json.dumps(result,sort_keys=True))\n")

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def actual_reader(self):
        # Real retained helper/engine/Git reads in a fresh process, not a mock.
        return json.loads(subprocess.check_output([sys.executable,'-B','-c',self.program],cwd=self.root,stderr=subprocess.PIPE))

    def test_actual_old_source_rejects_installer_then_resolves_its_own_git(self):
        with patch.dict(os.environ,{'GITHUB_SHA':self.installer}):
            self.assertEqual(self.actual_reader(),{'subprocess_rejected':True,'returncode':128})
            with f.retained_source_environment():
                self.assertNotIn('GITHUB_SHA',os.environ)
                self.assertEqual(self.actual_reader(),{'actual_source':self.head})
            self.assertEqual(os.environ['GITHUB_SHA'],self.installer)
        self.assertFalse((self.root/'.git/objects/info/alternates').exists())

    def test_installer_environment_is_restored_on_validation_failure(self):
        with patch.dict(os.environ,{'GITHUB_SHA':self.installer}):
            with self.assertRaisesRegex(RuntimeError,'control'):
                with f.retained_source_environment():
                    self.assertNotIn('GITHUB_SHA',os.environ)
                    raise RuntimeError('control failure remains failure')
            self.assertEqual(os.environ['GITHUB_SHA'],self.installer)


if __name__ == '__main__': unittest.main()
