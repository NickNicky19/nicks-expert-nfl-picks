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


class Continued22RetrievalBudget(unittest.TestCase):
    def setUp(self):
        self.source = subprocess.check_output(['git', '-C', str(CODE), 'rev-parse', 'HEAD']).decode().strip()
        self.work = Path('/tmp') / 'nfl-seed-frontier-123456789'
        self.confirmation = 'NFL-WEB-CONTINUE-CHECKPOINT-22-OF-24-12540324398-20261024'
        self.env = dict(PREPARATION_ID=self.confirmation, CONTINUATION_ID=self.confirmation,
            GITHUB_ACTIONS='true', GITHUB_JOB='prepare-continuation',
            GITHUB_REPOSITORY='NickNicky19/nicks-expert-nfl-picks', GITHUB_REPOSITORY_ID='1411185749',
            GITHUB_ACTOR_ID='208912933', GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_RUN_ATTEMPT='1',
            RUNNER_ENVIRONMENT='github-hosted', GITHUB_REF='refs/heads/upgrade/phase2-reproducible-comparison',
            GITHUB_WORKFLOW_REF='NickNicky19/nicks-expert-nfl-picks/.github/workflows/prepare-diagnostic-seed.yml@refs/heads/upgrade/phase2-reproducible-comparison',
            GITHUB_SHA=self.source, GITHUB_WORKFLOW_SHA=self.source, GITHUB_RUN_ID='123456789', RUNNER_TEMP='/tmp')

    def test_normal_240_unchanged(self):
        for profile in (None, f.PROFILE22):
            with self.subTest(profile=profile), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(f.retrieval_budget(self.work, profile), 240)
        with patch.dict(os.environ, dict(self.env, PREPARATION_ID='unapproved'), clear=True):
            self.assertEqual(f.retrieval_budget(self.work, f.PROFILE22), 240)

    def test_exact_preparation22_is_900(self):
        # Synthetic invocation context; actual read-only checkout/source guard, no API or retrieval.
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(f.retrieval_budget(self.work, f.PROFILE22), 900)
            with self.assertRaises(ValueError):f.retrieval_budget(self.work)

    def test_other_context_cannot_receive_preparation_budget(self):
        for key in ('CONTINUATION_ID', 'GITHUB_ACTIONS', 'GITHUB_JOB', 'GITHUB_REPOSITORY',
                    'GITHUB_REPOSITORY_ID', 'GITHUB_ACTOR_ID', 'GITHUB_EVENT_NAME',
                    'GITHUB_RUN_ATTEMPT', 'RUNNER_ENVIRONMENT', 'GITHUB_REF', 'GITHUB_WORKFLOW_REF',
                    'GITHUB_SHA', 'GITHUB_WORKFLOW_SHA'):
            with self.subTest(key=key), patch.dict(os.environ, dict(self.env, **{key:'wrong'}), clear=True):
                with self.assertRaises(ValueError):f.retrieval_budget(self.work, f.PROFILE22)

    def test_canonical_run_and_actual_run_path_required(self):
        for run in ('', '0', '01', '-1', '1/../2'):
            with self.subTest(run=run), patch.dict(os.environ, dict(self.env, GITHUB_RUN_ID=run), clear=True):
                with self.assertRaises(ValueError):f.retrieval_budget(self.work, f.PROFILE22)
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(ValueError):f.retrieval_budget(self.work.with_name('another-run'), f.PROFILE22)


class Continued22Profiles(unittest.TestCase):
    def test_closed_profiles_and_original_constants_unchanged(self):
        old=f.profile_identity();new=f.profile_identity(f.PROFILE22)
        self.assertEqual((old['count'],old['artifact'],old['run']),(13,12509203616,39940028362))
        self.assertEqual((new['count'],new['artifact'],new['run']),(22,12540324398,40017092249))
        new['count']=1;self.assertEqual(f.profile_identity(f.PROFILE22)['count'],22)
        for bad in ('unknown',{},False,22):
            with self.subTest(bad=bad),self.assertRaises(ValueError):f.profile_identity(bad)

    def test_typed22_progress_does_not_relabel13(self):
        value=dict(generation=22,target=24,wall_clock='2026-10-24T00:00:00+00:00')
        self.assertEqual(f.progress(value,f.PROFILE22),22)
        with self.assertRaises(ValueError):f.progress(value)
        for name,bad in [('generation',True),('generation',13),('target',True)]:
            changed=dict(value);changed[name]=bad
            with self.subTest(name=name,bad=bad),self.assertRaises(ValueError):f.progress(changed,f.PROFILE22)

    def test_actual_outer_and_parents_rehashed_with_restored_mtime(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory);inventory={}
            for name in f.ALLOW-{'ARTIFACT_MANIFEST.json'}:
                body=b'{}' if name.endswith('.json') else b'tiny-fictional-parent'
                (work/name).write_bytes(body);inventory[name]=f.descriptor(work/name)
            selected=f.profile_identity(f.PROFILE22)
            envelope=dict(schema_version='cloud-seed-artifact-envelope-v1',application_source=f.BASE,
                installer=dict(head=selected['producer'],tree=selected['tree']),integrity_sha256=selected['integrity'],
                preparation_status='PREPARATION_FAILED',operating_qualification='NOT_RUN',files=inventory)
            archive=work/'artifact.zip'
            with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as zipped:
                for name in f.ALLOW:
                    zipped.writestr(name,json.dumps(envelope).encode() if name=='ARTIFACT_MANIFEST.json' else (work/name).read_bytes())
            selected.update(size=archive.stat().st_size,digest=f.descriptor(archive)['sha256'])
            with patch.object(f,'_CONTINUED22',selected):
                expected=f.verify_parents(work,f.PROFILE22)
                self.assertEqual(expected,{name:inventory[name] for name in f.PARENTS})
                parent=work/f.BUNDLE;before=parent.stat();parent.write_bytes(b'x'*before.st_size);os.utime(parent,ns=(before.st_atime_ns,before.st_mtime_ns))
                with self.assertRaisesRegex(ValueError,'parent bytes'):f.verify_parents(work,f.PROFILE22)
                parent.write_bytes(b'tiny-fictional-parent')
                before=archive.stat();raw=archive.read_bytes();archive.write_bytes(raw[:-1]+bytes([raw[-1]^1]));os.utime(archive,ns=(before.st_atime_ns,before.st_mtime_ns))
                with self.assertRaisesRegex(ValueError,'outer artifact bytes'):f.verify_parents(work,f.PROFILE22)


class Continued22Residuals(unittest.TestCase):
    setUp = GitFrontier.setUp
    tearDown = GitFrontier.tearDown
    g = GitFrontier.g

    def restore(self):
        with patch.object(f,'BASE',self.source),patch.object(f,'TREE',self.tree):
            return f.restore_committed(self.work,self.raw,self.scope,f.PROFILE22)

    def evidence(self,lane='verification/partial-failures',payload=None):
        value=payload or dict(schema_version='completion-failure-data-integrity-v2',season=2026,week=6,
            completion_sha256='a'*64,failed_at='2026-11-09T05:01:55+00:00',reason='FINAL_COMPLETION_BOUNDARY_FAILED')
        digest=hashlib.sha256(f.ci.canonical(value)).hexdigest()
        name='data/'+lane+'/2026/w06/'+digest+'.json.gz';p=self.raw/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(gzip.compress(f.ci.canonical(dict(payload=value,payload_sha256=digest)),mtime=0));self.scope[name]=f.descriptor(p)
        return name

    def test_failure_marker_carried_verbatim_before_replay(self):
        name=self.evidence();root,_,residual=self.restore()
        self.assertEqual((root/name).read_bytes(),(self.raw/name).read_bytes())
        self.assertEqual(residual['new'],1)
        self.assertTrue(f.git(root,'status','--porcelain')) # Carried evidence is not a false clean commit.

    def test_changed_mutable_cache_keeps_committed_alias(self):
        cache=self.raw/'data/cache/provider.json';cache.parent.mkdir(parents=True,exist_ok=True);cache.write_text('{}');self.scope[cache.relative_to(self.raw).as_posix()]=f.descriptor(cache)
        root,_,_=self.restore();self.assertFalse((root/'data/cache/provider.json').exists())

    def test_changed_immutable_or_unknown_new_role_rejected(self):
        name=self.evidence();(self.raw/name).write_bytes(b'not-canonical');self.scope[name]=f.descriptor(self.raw/name)
        with self.assertRaises((ValueError,OSError,EOFError)):self.restore()

    def test_orphan_new_native_rejected_by_completed_consumer(self):
        name=self.evidence('forward',dict(schema_version='baseline-capture-v2',season=2026,week=6))
        root,_,_=self.restore()
        partial=SimpleNamespace(COMPLETION_LANE='verification/partial-completions')
        m={'capture':SimpleNamespace(corrected=SimpleNamespace(NATIVE='baseline-capture-v2')),'partial':partial,'ev':SimpleNamespace()}
        with self.assertRaisesRegex(ValueError,'Orphan residual native'):
            f._qualify_residual(self.work,root,m,self.scope,datetime(2026,11,9,tzinfo=timezone.utc))

    def test_negative_marker_is_visible_to_completed_consumer_before_acceptance(self):
        native_name=self.evidence('forward',dict(schema_version='baseline-capture-v2',season=2026,week=6))
        marker=self.evidence()
        completion=self.evidence('verification/partial-completions',dict(schema_version='partial-completion-data-integrity-v2',
            season=2026,week=6,baseline_receipt=native_name,scope_receipt='scope'))
        root,_,_=self.restore();calls=[]
        def saved(_root,name,_lane):
            if name=='scope':return {'fictional_scope':True}
            return f._residual_evidence(root/name,name)
        def rejected(*args,**kwargs):
            calls.append((root/marker).read_bytes());raise ValueError('actual completed consumer rejected negative marker')
        partial=SimpleNamespace(COMPLETION_LANE='verification/partial-completions',_saved=saved)
        corrected=SimpleNamespace(NATIVE='baseline-capture-v2',_saved_spec=lambda *_:{},read_bundle=rejected)
        m={'capture':SimpleNamespace(corrected=corrected),'partial':partial,'ev':SimpleNamespace()}
        with self.assertRaisesRegex(ValueError,'completed consumer rejected'):
            f._qualify_residual(self.work,root,m,self.scope,datetime(2026,11,9,tzinfo=timezone.utc))
        self.assertEqual(calls,[(self.raw/marker).read_bytes()])

    def test_copied_root_rechecks_actual_inventory_and_mode(self):
        name=self.evidence();root,_,_=self.restore()
        self.raw.rename(self.work/'raw-checkpoint');self.raw=self.work/'raw-checkpoint'
        (self.work/f.MANIFEST).write_text(json.dumps(dict(status='INCOMPLETE_NOT_ADMITTED_NOT_RESUME_AUTHORIZED',
            application_source=self.source,input_contract_sha256=f.INPUTS,files=self.scope)))
        with patch.object(f,'BASE',self.source),patch.object(f,'TREE',self.tree),patch.object(f,'verify_parents') as parents:
            checked=f.verify_copied_frontier(self.work,root,f.PROFILE22)
            self.assertIn(name,checked['inventory']);self.assertEqual(parents.call_count,2)
            target=root/'config/phase2.json';old=target.stat();raw=target.read_bytes();target.write_bytes(b'x'*len(raw));os.utime(target,ns=(old.st_atime_ns,old.st_mtime_ns))
            with self.assertRaisesRegex(ValueError,'inventory changed'):f.verify_copied_frontier(self.work,root,f.PROFILE22)
            target.write_bytes(raw);target.chmod(0o755)
            with self.assertRaisesRegex(ValueError,'mode changed'):f.verify_copied_frontier(self.work,root,f.PROFILE22)

    def test_actual_b3_data_aliases_keep_committed22_and_raw23_separate(self):
        names=['output/data/'+name for name in ('matchup-proof.json','game-status.json','offer-capture.json',
            'future.json','teams.json','track_record.json')]
        names+=['output/data/archive/2026_w06.json','output/data/weeks/2026_w05.json']
        for name in names:
            p=self.repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'{"generation":22}')
        self.g('add','.');self.g('commit','-qm','Fictional committed22 data aliases')
        (self.work/f.BUNDLE).unlink();self.g('bundle','create',str(self.work/f.BUNDLE),'HEAD','refs/fixture/source')
        for name in names:
            p=self.raw/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'{"generation":23}');self.scope[name]=f.descriptor(p)
        root,_,_=self.restore()
        for name in names:
            self.assertEqual((root/name).read_bytes(),b'{"generation":22}')
            self.assertEqual((self.raw/name).read_bytes(),b'{"generation":23}')
        for name in ('output/app.js','output/index.html','output/data/archive/2027_w06.json',
                     'output/data/weeks/2026_w07.json','output/data/archive/arbitrary.json'):
            self.assertFalse(f._mutable_role(name))

    def test_partial23_report_assets_are_raw_unqualified_not22_members(self):
        name='output/data/selection-grading/'+'a'*64+'/rows-0000.json'
        p=self.raw/name;p.parent.mkdir(parents=True);p.write_bytes(b'{"partial23":true}');self.scope[name]=f.descriptor(p)
        root,_,_=self.restore()
        self.assertFalse((root/name).exists());self.assertEqual(p.read_bytes(),b'{"partial23":true}')

    def test_no_new_source_config_markers_or_unknown_raw_roles(self):
        for name in ('config/new.json','FICTIONAL_ONLY.json','output/data/unknown.json'):
            with self.subTest(name=name):
                p=self.raw/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'{}');self.scope[name]=f.descriptor(p)
                with self.assertRaises(ValueError):self.restore()
                # Restore failure retains its independent partial directory.
                root=self.work/'committed-frontier'
                if root.exists():
                    import shutil;shutil.rmtree(root)
                del self.scope[name];p.unlink()


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

    def test_actual_b3_corrected_outcome_producer_envelope_is_supported(self):
        # Execute the exact retained B3 emitter, not a new schema-name stub.
        target=self.root.parent/'outcome-inputs';(target/'output/data').mkdir(parents=True)
        game=dict(id='fictional-game',home='AAA',away='BBB',state='pre',detail='Scheduled',kickoff='2026-11-10T18:00:00Z')
        (target/'output/data/week.json').write_text(json.dumps(dict(season=2026,week=6,games=[game])))
        program="""import json,sys;from pathlib import Path
sys.path[:0]=['tools','pull']
import scorecard,data_integrity_v2 as d
from reliability import utc
from evidence import read
root=Path(sys.argv[1]);row=dict(season=2026,week=6,game_id='fictional-game',player_id='fictional-player',
category='rec',team='AAA',kickoff='2026-11-10T18:00:00Z',model_version=d.MODEL)
paths=scorecard.snapshot_outcomes(root,{(2026,6,'fictional-game','fictional-player','rec'):row},utc('2026-11-09T05:01:55Z'),include_populations=False)
assert len(paths)==1 and read(paths[0])['schema_version']==d.OUTCOMES=='forecast-outcomes-v2'
print(paths[0].relative_to(root).as_posix())
"""
        completed=subprocess.run([sys.executable,'-B','-c',program,str(target)],cwd=self.root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
        name=completed.stdout.strip().splitlines()[-1]
        value=f._residual_evidence(target/name,name)
        self.assertEqual(value['schema_version'],'forecast-outcomes-v2')
        self.assertEqual(value['rows'][0]['actual'],None)
        self.assertIn('statistic_contract',value)
        # Descriptive outcomes have a distinct B3 emitter lane and cannot
        # acquire canonical forecast-outcome trust by changing a schema label.
        for schema in ('descriptive-statistic-outcomes-v1','descriptive-statistic-outcomes-v2'):
            self.assertNotIn(schema,f._RESIDUAL_SCHEMAS['outcomes'])
            wrong=dict(value,schema_version=schema)
            digest=hashlib.sha256(f.ci.canonical(wrong)).hexdigest()
            wrong_name='data/outcomes/2026/w06/'+digest+'.json.gz'
            path=target/wrong_name
            path.write_bytes(gzip.compress(f.ci.canonical(dict(payload=wrong,payload_sha256=digest)),mtime=0))
            with self.assertRaisesRegex(ValueError,'Unsupported residual schema/role'):
                f._residual_evidence(path,wrong_name)

    def test_installer_environment_is_restored_on_validation_failure(self):
        with patch.dict(os.environ,{'GITHUB_SHA':self.installer}):
            with self.assertRaisesRegex(RuntimeError,'control'):
                with f.retained_source_environment():
                    self.assertNotIn('GITHUB_SHA',os.environ)
                    raise RuntimeError('control failure remains failure')
            self.assertEqual(os.environ['GITHUB_SHA'],self.installer)


if __name__ == '__main__': unittest.main()
