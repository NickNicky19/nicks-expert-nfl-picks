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
        capture = SimpleNamespace(_manifest=lambda *a, **kw: ({}, {}), _git_archive=lambda *a, **kw: {},
            _public_archive_commit=lambda *args: None, validate_generation=lambda _: {'generation_sha256': 'a' * 64})
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
        if lane=='forward':value.update(input_sha256='1'*64,engine_sha256='2'*64,mode='live')
        digest=hashlib.sha256(f.ci.canonical(value)).hexdigest()
        locator=hashlib.sha256(f.ci.canonical(dict(data=value['input_sha256'],engine=value['engine_sha256'],mode=value['mode']))).hexdigest() if lane=='forward' else digest
        name='data/'+lane+'/2026/w06/'+locator+'.json.gz';p=self.raw/name;p.parent.mkdir(parents=True,exist_ok=True)
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
        name=self.evidence();root,heads,_=self.restore()
        f._preserve_carried(root,heads['HEAD'],self.raw,self.scope,f.PROFILE22)
        self.raw.rename(self.work/'raw-checkpoint');self.raw=self.work/'raw-checkpoint'
        (self.work/f.MANIFEST).write_text(json.dumps(dict(status='INCOMPLETE_NOT_ADMITTED_NOT_RESUME_AUTHORIZED',
            application_source=self.source,input_contract_sha256=f.INPUTS,files=self.scope)))
        with patch.object(f,'BASE',self.source),patch.object(f,'TREE',self.tree),patch.object(f,'verify_parents') as parents:
            checked=f.verify_copied_frontier(self.work,root,f.PROFILE22)
            self.assertIn(name,checked['inventory']);self.assertEqual(parents.call_count,2)
            target=root/'config/phase2.json';old=target.stat();raw=target.read_bytes();target.write_bytes(b'x'*len(raw));os.utime(target,ns=(old.st_atime_ns,old.st_mtime_ns))
            with self.assertRaisesRegex(ValueError,'tracked bytes|inventory changed'):f.verify_copied_frontier(self.work,root,f.PROFILE22)
            target.write_bytes(raw);target.chmod(0o755)
            with self.assertRaisesRegex(ValueError,'mode'):f.verify_copied_frontier(self.work,root,f.PROFILE22)

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


class DiagnosticOperationLifetime(unittest.TestCase):
    """Tiny delegate/lifetime controls; no seed, provider, kernel or fit claim."""
    def setUp(self):
        import operating_diagnostic as h
        self.h = h;self.head = 'a' * 40;self.calls = [];self.run_calls = [];self.refs = []
        self.root = Path('/workspace/diagnostic-lifetime-unit/root')
        self.real_run = subprocess.run
        import weakref
        class Value:pass
        def manifest(base, descriptor, *, root=None, _checked=None):
            self.assertEqual(_checked, {});value = Value()
            _checked['payload'] = value;self.refs.append(weakref.ref(value))
            self.calls.append(('manifest', descriptor, root));return descriptor, {}
        def archive(root, records, excluded, *, verify_public=True, _checked=None):
            self.assertEqual(_checked, {});value = Value()
            _checked['payload'] = value;self.refs.append(weakref.ref(value))
            self.calls.append(('archive', frozenset(excluded), verify_public))
            return {rid: {'git_ref': self.head, 'manifest': records[rid]} for rid in excluded}
        self.capture = SimpleNamespace(_manifest=manifest, _git_archive=archive)
        self.modules = {'capture': self.capture};self.originals = (manifest, archive)
        def run(command, *args, **kwargs):
            self.run_calls.append((command, args, kwargs));return SimpleNamespace(returncode=0)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(h, 'bind', new=lambda root: self.modules))
        self.stack.enter_context(patch.object(h.subprocess, 'run', new=run))
        self.stack.enter_context(patch.object(f, 'git', new=lambda root,*args: (self.head+'\n').encode()))
    def tearDown(self):self.stack.close()
    def context(self, **kw):return f.operation_lifetime(self.h, **kw)
    def assert_restored(self):
        self.assertIs(self.capture._manifest, self.originals[0])
        self.assertIs(self.capture._git_archive, self.originals[1])
        self.assertFalse(hasattr(self.h, '_installer_generation_lifetime'))
    def test_fresh_context_delegation_and_no_retained_payload(self):
        import gc,types
        shared = {'caller_state': 'untouched'}
        with self.context(modules=(self.modules,)):
            self.assertIsInstance(self.capture._manifest, types.FunctionType)
            for i in range(4):
                descriptor = {'report': str(i)}
                self.assertEqual(self.capture._manifest(self.root, descriptor,
                    root=self.root, _checked=shared), (descriptor, {}))
                gc.collect();self.assertTrue(all(ref() is None for ref in self.refs))
            self.assertEqual(shared, {'caller_state': 'untouched'})
        self.assert_restored();self.assertEqual(len(self.calls), 4)
    def test_archive_exact_single_report_full_union_and_fresh_contexts(self):
        records = {str(i): {'path': str(i)} for i in range(3)}
        with self.context(modules=(self.modules,)):
            result = self.capture._git_archive(self.root, records, set(records), verify_public=False)
            self.assertEqual(result, {rid:{'git_ref':self.head,'manifest':v} for rid,v in records.items()})
            self.assertEqual(self.calls, [('archive',frozenset({str(i)}),False) for i in range(3)])
            self.assertTrue(all(ref() is None for ref in self.refs))
        self.assert_restored()
    def test_empty_archive_still_delegates_exact_original(self):
        with self.context(modules=(self.modules,)):
            self.assertEqual(self.capture._git_archive(self.root, {}, set()), {})
        self.assertEqual(self.calls,[('archive',frozenset(),True)]);self.assert_restored()
    def test_bind_hook_and_nested_context_use_one_plain_adapter(self):
        with self.context():
            self.assertIs(self.h.bind(self.root), self.modules);outer = self.capture._manifest
            with self.context(modules=(self.modules,)):
                self.assertIs(self.capture._manifest, outer)
                self.capture._manifest(self.root, {'report':'x'})
            self.assertIs(self.capture._manifest, outer)
        self.assert_restored()
    def test_original_validation_error_propagates_and_restores(self):
        def fail(*args,**kwargs):raise RuntimeError('COLD_VALIDATION_FAILED')
        self.capture._manifest = fail
        with self.assertRaisesRegex(RuntimeError,'COLD_VALIDATION_FAILED'):
            with self.context(modules=(self.modules,)):
                self.capture._manifest(self.root,{})
        self.assertIs(self.capture._manifest,fail);self.assertIs(self.capture._git_archive,self.originals[1])
        self.assertFalse(hasattr(self.h,'_installer_generation_lifetime'))
    def test_archive_omission_extra_wrong_ref_and_changed_descriptor_fail(self):
        records={'x':{'path':'original'}}
        for label in ('missing','extra','wrong_ref','changed'):
            def bad(root, records, excluded, **kwargs):
                if label=='missing':return {}
                if label=='extra':return {'x':{'git_ref':self.head,'manifest':records['x']},'extra':{}}
                if label=='changed':records['x']['path']='changed'
                return {'x':{'git_ref':'b'*40 if label=='wrong_ref' else self.head,'manifest':records['x']}}
            with self.subTest(label=label),patch.object(self.capture,'_git_archive',new=bad):
                with self.assertRaisesRegex(ValueError,'Exact cold archive'):
                    with self.context(modules=(self.modules,)):
                        self.capture._git_archive(self.root,records,{'x'})
            records['x']['path']='original'
        self.assert_restored()
    def test_archive_head_drift_fails_before_next_batch(self):
        reads=iter([self.head,self.head,self.head,'b'*40])
        with patch.object(f,'git',new=lambda *args:(next(reads)+'\n').encode()):
            with self.assertRaisesRegex(ValueError,'HEAD changed'):
                with self.context(modules=(self.modules,)):
                    self.capture._git_archive(self.root,{'x':{},'y':{}},{'x','y'})
        self.assertEqual(len(self.calls),1);self.assert_restored()
    def test_archive_original_failure_is_not_a_partial_success(self):
        def fail(*args,**kw):raise RuntimeError('ORIGINAL_GIT_BOUNDARY_FAILED')
        with patch.object(self.capture,'_git_archive',new=fail):
            with self.assertRaisesRegex(RuntimeError,'ORIGINAL_GIT_BOUNDARY_FAILED'):
                with self.context(modules=(self.modules,)):
                    self.capture._git_archive(self.root,{'x':{}},{'x'})
        self.assert_restored()
    def test_missing_excluded_record_rejected_before_original(self):
        with self.context(modules=(self.modules,)):
            with self.assertRaisesRegex(ValueError,'coverage inputs'):
                self.capture._git_archive(self.root,{}, {'missing'})
        self.assertEqual(self.calls,[]);self.assert_restored()
    def test_actual_harness_hash_guard_rejects_other_source(self):
        wrong=SimpleNamespace(__file__=f.__file__)
        with self.assertRaisesRegex(ValueError,'Actual frozen'):
            with f.operation_lifetime(wrong):self.fail('wrong harness entered')
    def test_exact_cold_modern_and_recheck_are_new_interpreter_commands(self):
        roots=[['modern','--code',str(self.root),'--root',str(self.root)],
            ['modern','--code',str(self.root),'--root',str(self.root),'--small'],
            ['recheck','--code','/workspace/diagnostic-lifetime-unit/restart-checkout',
             '--root','/workspace/diagnostic-lifetime-unit/restart-checkout',
             '--result','/workspace/diagnostic-lifetime-unit/RESTART.json']]
        for tail in roots:
            command=[sys.executable,str(Path(self.h.__file__).resolve()),*tail]
            with self.context():self.h.subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
            actual,_,kw=self.run_calls[-1]
            self.assertEqual(actual[:2],[sys.executable,'-c']);self.assertEqual(actual[3:],tail)
            self.assertIn('f.frozen_harness_child()',actual[2]);self.assertEqual(kw,{'check':True,'stdout':subprocess.DEVNULL})
        self.assert_restored()
    def test_other_commands_are_delegated_unchanged(self):
        for command in (['git','rev-parse','HEAD'],
                [sys.executable,str(Path(self.h.__file__).resolve()),'legacy','--code','/a','--root','/b'],
                [sys.executable,'tools/source_ci.py','verify']):
            with self.context():self.h.subprocess.run(command,check=True)
            self.assertIs(self.run_calls[-1][0],command)
    def test_malformed_closed_child_cannot_add_routes_or_destinations(self):
        good=['modern','--code',str(self.root),'--root',str(self.root)]
        variants=[good+['--unknown'],good[:3]+['--root','/workspace/different'],
            ['recheck','--code','/workspace/r','--root','/workspace/r','--result','/workspace/R.json']]
        for tail in variants:
            with self.subTest(tail=tail),self.assertRaises(ValueError):
                with self.context():self.h.subprocess.run([sys.executable,str(Path(self.h.__file__).resolve()),*tail],check=True)
        self.assertEqual(self.run_calls,[]);self.assert_restored()
    def test_cold_child_checks_offline_then_calls_unchanged_main(self):
        calls=[]
        tail=['modern','--code',str(self.root),'--root',str(self.root)]
        def main():
            self.assertTrue(hasattr(self.h,'_installer_generation_lifetime'))
            self.assertEqual(sys.argv[1:],tail);calls.append('main')
        with patch.object(self.h,'require_offline',new=lambda:calls.append('offline')),\
                patch.object(self.h,'main',new=main),patch.object(sys,'argv',['-c',*tail]):
            f.frozen_harness_child()
        self.assertEqual(calls,['offline','main']);self.assert_restored()
    def test_cold_child_offline_failure_stops_before_main(self):
        calls=[]
        def denied():raise RuntimeError('KERNEL_ISOLATION_REQUIRED')
        with patch.object(self.h,'require_offline',new=denied),patch.object(self.h,'main',new=lambda:calls.append('main')),\
                patch.object(sys,'argv',['-c','modern','--code',str(self.root),'--root',str(self.root)]):
            with self.assertRaisesRegex(RuntimeError,'KERNEL_ISOLATION_REQUIRED'):f.frozen_harness_child()
        self.assertEqual(calls,[]);self.assert_restored()
    def test_all_seed_prepare_stages_share_adapter_entry(self):
        import cloud_seed_prepare as p
        stages=[]
        def worker(args):
            m=self.h.bind(self.root)
            self.assertIsNot(m['capture']._manifest,self.originals[0])
            stages.append(args.stage);return args.stage
        with patch.object(p,'_worker',new=worker):
            for name in ('frontier','construct','admit','gate','freeze','restore','recheck'):
                self.assertEqual(p.worker(SimpleNamespace(stage=name)),name)
        self.assertEqual(len(stages),7);self.assert_restored()
    def test_connected_caller_scopes_and_dependency_are_present(self):
        import ast
        tools=Path(f.__file__).parent
        source=ast.parse((tools/'seed_checkpoint_frontier.py').read_text())
        saved=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='check_saved')
        self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='operation_lifetime' for n in ast.walk(saved)))
        campaign=ast.parse((tools/'operating_campaign.py').read_text())
        def function(name):
            return next(n for n in campaign.body if isinstance(n,ast.FunctionDef) and n.name==name)
        def call_name(node):
            if not isinstance(node,ast.Call):return None
            return node.func.id if isinstance(node.func,ast.Name) else node.func.attr if isinstance(node.func,ast.Attribute) else None
        for name in ('transition_execution_plan','package_execution_source','main'):
            self.assertTrue(any(call_name(n)=='operation_lifetime' for n in ast.walk(function(name))),name)
        # Production capture/validation/staging must keep their own cache
        # lifetimes. Only the subsequent diagnostic inventory gets the adapter.
        capture=function('sample_capture')
        self.assertFalse(any(call_name(n)=='operation_lifetime' for n in ast.walk(capture)))
        self.assertTrue({'run_capture','validate_generation'} <= {call_name(n) for n in ast.walk(capture)})
        commit=function('sample_commit')
        self.assertTrue({'commit','stage_pages','final_candidate_workload'} <= {call_name(n) for n in ast.walk(commit)})
        scopes=[n for n in ast.walk(commit) if isinstance(n,ast.With)
            and any(call_name(item.context_expr)=='operation_lifetime' for item in n.items)]
        self.assertEqual(len(scopes),1)
        bounded={call_name(n) for n in ast.walk(scopes[0])}
        self.assertIn('final_candidate_workload',bounded)
        self.assertFalse({'run_capture','validate_generation','commit','stage_pages'} & bounded)
        import operating_campaign as c
        self.assertIn('tools/seed_checkpoint_frontier.py',c.DEPENDENCIES)
    def test_actual_installer_identity_never_claims_measured_capacity(self):
        value=f.operation_identity()
        self.assertEqual(value['installer_helper_sha256'],hashlib.sha256(Path(f.__file__).read_bytes()).hexdigest())
        self.assertEqual(value['frozen_harness_sha256'],f.HARNESS)
        self.assertIn('NOT_MEASURED',value['claim'])

    def test_actual_new_interpreter_retains_root_helper_import_order(self):
        # Real new Python interpreters and original441f bind; tiny synthetic
        # app modules only. Offline guard is substituted IN THIS CONTROL ONLY;
        # no kernel/sourceCI/model/fixture/operating qualification is claimed.
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);installer=base/'installer';root=base/'root'
            installer.mkdir();(root/'tools').mkdir(parents=True)
            (installer/'operating_diagnostic.py').write_bytes(Path(self.h.__file__).read_bytes())
            (installer/'reliability.py').write_text("ORIGIN='INSTALLER'\n")
            (installer/'seed_checkpoint_frontier.py').write_text(
                "import reliability\n"
                "def frozen_harness_child():print(reliability.ORIGIN)\n")
            names=('build','build_recorded','reliability','evidence','partial_week',
                'phase2_capture','selection_publication','scorecard','source_evidence')
            for name in names:(root/'tools'/(name+'.py')).write_text("ORIGIN='RETAINED_ROOT'\n")
            tail=['modern','--code',str(root),'--root',str(root)]
            with patch.object(f,'__file__',str(installer/'seed_checkpoint_frontier.py')):
                with self.context():
                    self.h.subprocess.run([sys.executable,str(Path(self.h.__file__).resolve()),*tail],check=True)
            command=self.run_calls[-1][0]
            self.assertEqual(command[:2],[sys.executable,'-c'])
            program=command[2].replace('h.require_offline();','')
            self.assertIn('h.bind(Path(sys.argv[3]).resolve());',program)
            environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
            positive=self.real_run([sys.executable,'-B','-c',program,*tail],
                check=True,capture_output=True,text=True,env=environment)
            self.assertEqual(positive.stdout.strip(),'RETAINED_ROOT')
            control=program.replace('h.bind(Path(sys.argv[3]).resolve());','')
            negative=self.real_run([sys.executable,'-B','-c',control,*tail],
                check=True,capture_output=True,text=True,env=environment)
            self.assertEqual(negative.stdout.strip(),'INSTALLER')

    def test_final_union_rejects_later_batch_mutating_earlier_record(self):
        records={'a':{'path':'original-a'},'b':{'path':'original-b'}}
        def archive(root, records, excluded, **kwargs):
            rid=next(iter(excluded))
            if rid=='b':records['a']['path']='changed-later'
            return {rid:{'git_ref':self.head,'manifest':records[rid]}}
        with patch.object(self.capture,'_git_archive',new=archive):
            with self.assertRaisesRegex(ValueError,'Final cold archive descriptors'):
                with self.context(modules=(self.modules,)):
                    self.capture._git_archive(self.root,records,set(records))
        self.assert_restored()
    def test_final_union_rejects_later_batch_mutating_detached_return(self):
        records={'a':{'path':'original-a'},'b':{'path':'original-b'}};returned=[]
        def archive(root, records, excluded, **kwargs):
            rid=next(iter(excluded))
            if rid=='b':returned[0]['manifest']['path']='changed-detached-return'
            value={'git_ref':self.head,'manifest':dict(records[rid])};returned.append(value)
            return {rid:value}
        with patch.object(self.capture,'_git_archive',new=archive):
            with self.assertRaisesRegex(ValueError,'Final cold archive descriptors'):
                with self.context(modules=(self.modules,)):
                    self.capture._git_archive(self.root,records,set(records))
        self.assertEqual(records['a']['path'],'original-a');self.assert_restored()
    def test_final_union_rejects_later_batch_mutating_earlier_locator(self):
        records={'a':{},'b':{}};returned=[]
        def archive(root, records, excluded, **kwargs):
            rid=next(iter(excluded))
            if rid=='b':returned[0]['git_ref']='b'*40
            value={'git_ref':self.head,'manifest':records[rid]};returned.append(value)
            return {rid:value}
        with patch.object(self.capture,'_git_archive',new=archive):
            with self.assertRaisesRegex(ValueError,'Final cold archive descriptors'):
                with self.context(modules=(self.modules,)):
                    self.capture._git_archive(self.root,records,set(records))
        self.assert_restored()
    def test_final_union_rechecks_head_after_all_batches(self):
        reads=iter([self.head]*5+['b'*40])
        with patch.object(f,'git',new=lambda *args:(next(reads)+'\n').encode()):
            with self.assertRaisesRegex(ValueError,'HEAD changed before complete union'):
                with self.context(modules=(self.modules,)):
                    self.capture._git_archive(self.root,{'a':{},'b':{}},{'a','b'})
        self.assertEqual(len(self.calls),2);self.assert_restored()


class CarriedEvidenceRecovery(unittest.TestCase):
    """Real tiny local Git and synthetic envelopes; never a fixture qualification."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=self.base/'root';self.root.mkdir();self.work=self.base/'work';self.work.mkdir()
        self.raw=self.work/'raw-checkpoint';self.raw.mkdir()
        f.git(self.root,'init','--template=','-q')
        for k,v in [('user.name','FictionalUnit'),('user.email','fictional@example.invalid'),
                    ('core.logAllRefUpdates','false')]:f.git(self.root,'config',k,v)
        import operating_diagnostic as h
        values={'tools/helper.py':b'# fixed source\n','config/phase2.json':b'{"fixed":true}\n',
            'output/data/week.json':b'{"generation":22}\n',
            'FICTIONAL_ONLY.json':h.encoded(dict(reviewed_source=f.BASE,dimensions=h.FULL)),
            'FICTIONAL_PHASES.json':h.encoded(dict(contract=h.phase_contract(),
                contract_sha256=hashlib.sha256(h.encoded(h.phase_contract())).hexdigest()))}
        for n,b in values.items():
            q=self.root/n;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b);q.chmod(0o644)
        f.git(self.root,'add','.');f.git(self.root,'-c','commit.gpgsign=false','commit','-qm','Tiny original22')
        self.origin=f.git(self.root,'rev-parse','HEAD').decode().strip()
        self.tree=f.git(self.root,'rev-parse','HEAD^{tree}').decode().strip()
        f.git(self.root,'update-ref','refs/fixture/source',self.origin)
        f.git(self.root,'bundle','create',str(self.work/f.BUNDLE),'HEAD','refs/fixture/source')
        self.files={}
        for n in values:
            q=self.raw/n;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(values[n])
            self.files[n]=f.descriptor(q)
        progress={'generation':22,'target':24,'wall_clock':'2026-10-24T00:00:00+00:00'}
        (self.raw/'CONSTRUCTION_PROGRESS.json').write_text(json.dumps(progress))
        self.files['CONSTRUCTION_PROGRESS.json']=f.descriptor(self.raw/'CONSTRUCTION_PROGRESS.json')
        self.name=self.receipt()
    def tearDown(self):self.temp.cleanup()
    def receipt(self,native=False):
        payload={'schema_version':'baseline-capture-v2' if native else 'generation-failure-v1',
            'season':2026,'week':6,'source_sha':self.origin}
        if native:payload.update(input_sha256='1'*64,engine_sha256='2'*64,mode='live')
        digest=hashlib.sha256(f.ci.canonical(payload)).hexdigest()
        locator=hashlib.sha256(f.ci.canonical(dict(data=payload['input_sha256'],
            engine=payload['engine_sha256'],mode='live'))).hexdigest() if native else digest
        n='data/'+('forward' if native else 'verification/partial-failures')+'/2026/w06/'+locator+'.json.gz'
        b=gzip.compress(f.ci.canonical(dict(payload=payload,payload_sha256=digest)),mtime=0)
        for root in (self.raw,self.root):
            q=root/n;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b);q.chmod(0o644)
        self.files[n]=f.descriptor(self.raw/n);return n
    def preserve(self):return f._preserve_carried(self.root,self.origin,self.raw,self.files,f.PROFILE22)
    def head(self):return f.git(self.root,'rev-parse','HEAD').decode().strip()
    def test_normal_forward_evidence_commit_and_no_op_retry(self):
        before=f.tree_inventory(self.root);value=self.preserve();head=self.head()
        self.assertNotEqual(head,self.origin);self.assertEqual(value['parent'],self.origin)
        self.assertEqual(value['origin_bundle_head'],self.origin);self.assertEqual(value['recovery_head'],head)
        self.assertEqual(value['addition_count'],1);self.assertFalse(value['forecast_generation_created'])
        self.assertEqual(f.git(self.root,'diff','--name-only',self.origin,head).decode().splitlines(),[self.name])
        self.assertEqual(f.tree_inventory(self.root),before)
        self.assertEqual((self.root/'output/data/week.json').read_bytes(),b'{"generation":22}\n')
        self.assertEqual(self.preserve(),value);self.assertEqual(self.head(),head)
        self.assertEqual(f.git(self.root,'rev-list','--count',self.origin+'..HEAD').strip(),b'1')
        self.assertIsNotNone(datetime.fromisoformat(value['git_committer_at']).tzinfo)
    def test_no_carried_additions_has_no_commit(self):
        (self.root/self.name).unlink();(self.raw/self.name).unlink();self.files.pop(self.name)
        value=self.preserve();self.assertEqual(value['operation'],'NO_ADDITIONS_NO_COMMIT')
        self.assertEqual(value['addition_count'],0);self.assertEqual(self.head(),self.origin)
    def test_mutated_original_same_size_restored_time_is_rejected(self):
        q=self.root/'tools/helper.py';old=q.stat();q.write_bytes(b'X'*old.st_size)
        os.utime(q,ns=(old.st_atime_ns,old.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'tracked bytes'):self.preserve()
        self.assertEqual(self.head(),self.origin)
    def test_tracked_deletion_and_mode_change_are_rejected(self):
        q=self.root/'tools/helper.py';body=q.read_bytes();q.unlink()
        with self.assertRaises(ValueError):self.preserve()
        q.write_bytes(body);q.chmod(0o755)
        with self.assertRaisesRegex(ValueError,'modes'):self.preserve()
        self.assertEqual(self.head(),self.origin)
    def test_unexpected_index_and_unexpected_source_are_rejected(self):
        q=self.root/'tools/helper.py';old=q.read_bytes();q.write_bytes(b'# staged source\n')
        f.git(self.root,'add','tools/helper.py');q.write_bytes(old)
        with self.assertRaisesRegex(ValueError,'index'):self.preserve()
        f.git(self.root,'reset','-q',self.origin,'--','tools/helper.py')
        (self.root/'tools/extra.py').write_bytes(b'# unexpected\n')
        with self.assertRaisesRegex(ValueError,'namespace'):self.preserve()
        self.assertEqual(self.head(),self.origin)
    def test_second_or_wrong_parent_commit_is_not_accepted(self):
        self.preserve();f.git(self.root,'-c','commit.gpgsign=false','commit','--allow-empty','-qm','Wrong extra parent')
        with self.assertRaisesRegex(ValueError,'one evidence-only descendant'):self.preserve()
    def test_source_field_mutation_cannot_change_original_native_bytes(self):
        name=self.receipt(native=True);q=self.root/name
        value=json.loads(gzip.decompress(q.read_bytes()));value['payload']['source_sha']='b'*40
        value['payload_sha256']=hashlib.sha256(f.ci.canonical(value['payload'])).hexdigest()
        q.write_bytes(gzip.compress(f.ci.canonical(value),mtime=0))
        with self.assertRaisesRegex(ValueError,'carried bytes'):self.preserve()
        self.assertEqual(self.head(),self.origin)
    def test_original_native_locator_and_payload_envelope_are_distinct(self):
        name=self.receipt(native=True);payload=f._residual_evidence(self.root/name,name)
        digest=hashlib.sha256(f.ci.canonical(payload)).hexdigest()
        self.assertNotEqual(Path(name).name,digest+'.json.gz')
        renamed=name.rsplit('/',1)[0]+'/'+digest+'.json.gz'
        q=self.root/renamed;q.write_bytes((self.root/name).read_bytes())
        with self.assertRaisesRegex(ValueError,'Original residual native locator'):
            f._residual_evidence(q,renamed)
        self.assertEqual((self.root/name).read_bytes(),(self.raw/name).read_bytes())
    def test_native_locator_does_not_expand_unsupported_history_shadow_roles(self):
        name=self.receipt(native=True)
        for lane in ('history','shadow'):
            other=name.replace('data/forward/','data/'+lane+'/');q=self.root/other
            q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes((self.root/name).read_bytes())
            with self.assertRaisesRegex(ValueError,'Unsupported residual schema/role'):
                f._residual_evidence(q,other)
    def test_fresh_copy_derives_actual_origin_and_recovery_head(self):
        self.preserve();head=self.head()
        manifest={'status':'INCOMPLETE_NOT_ADMITTED_NOT_RESUME_AUTHORIZED',
            'application_source':self.origin,'input_contract_sha256':f.INPUTS,'files':self.files}
        (self.work/f.MANIFEST).write_text(json.dumps(manifest))
        copy=self.base/'copy'
        f.git(self.base,'clone','--quiet','--no-hardlinks',str(self.root),str(copy))
        f.git(copy,'fetch','--no-tags',str(self.root),'refs/fixture/source:refs/fixture/source')
        with patch.object(f,'BASE',self.origin),patch.object(f,'TREE',self.tree),patch.object(f,'verify_parents'):
            result=f.verify_copied_frontier(self.work,copy,f.PROFILE22)
        self.assertEqual(result['origin_fixture_head'],self.origin);self.assertEqual(result['fixture_head'],head)
        self.assertEqual(result['evidence_recovery']['addition_count'],1)
        self.assertFalse((copy/'.git/objects/info/alternates').exists())
        self.assertEqual((copy/self.name).read_bytes(),(self.raw/self.name).read_bytes())
    def saved_context(self,*,residual_failure=False,history_failure=False):
        import operating_diagnostic as h
        capture=SimpleNamespace(_manifest=lambda *a,**kw:({},{}),_git_archive=lambda *a,**kw:{},
            _public_archive_commit=lambda *a:None,validate_generation=lambda root:dict(generation_sha256='c'*64))
        modules={'capture':capture};stack=contextlib.ExitStack()
        stack.enter_context(patch.object(f,'verify_parents'));stack.enter_context(patch.object(f,'unpack_checkpoint',return_value=self.files))
        stack.enter_context(patch.object(f,'decoded',side_effect=lambda path:json.loads(path.read_bytes())))
        (self.work/f.MANIFEST).write_bytes(b'{}')
        stack.enter_context(patch.object(f,'restore_committed',return_value=(self.root,{'HEAD':self.origin},{})))
        stack.enter_context(patch.object(h,'require_offline'));stack.enter_context(patch.object(h,'bind',new=lambda root:modules))
        stack.enter_context(patch.object(h,'Provider',new=lambda *a:SimpleNamespace(at=None)))
        stack.enter_context(patch.object(h,'external',new=lambda *a:contextlib.nullcontext()))
        if residual_failure:
            stack.enter_context(patch.object(f,'_qualify_residual',side_effect=ValueError('LATE_RESIDUAL_VALIDATION_FAILED')))
        else:stack.enter_context(patch.object(f,'_qualify_residual',return_value={}))
        if history_failure:stack.enter_context(patch.object(h,'workload',side_effect=ValueError('HISTORY_VALIDATION_FAILED')))
        return stack
    def test_late_residual_validation_failure_does_not_commit(self):
        with self.saved_context(residual_failure=True):
            with self.assertRaisesRegex(ValueError,'LATE_RESIDUAL_VALIDATION_FAILED'):
                f.check_saved(self.work,f.PROFILE22)
        self.assertEqual(self.head(),self.origin);self.assertFalse((self.work/'EVIDENCE_RECOVERY.json').exists())
        self.assertEqual((self.root/self.name).read_bytes(),(self.raw/self.name).read_bytes())
    def test_late_history_failure_retains_separate_recovery_identity_without_qualification(self):
        with self.saved_context(history_failure=True):
            with self.assertRaisesRegex(ValueError,'HISTORY_VALIDATION_FAILED'):
                f.check_saved(self.work,f.PROFILE22)
        value=json.loads((self.work/'EVIDENCE_RECOVERY.json').read_bytes())
        self.assertEqual(value['origin_bundle_head'],self.origin);self.assertEqual(value['recovery_head'],self.head())
        self.assertNotEqual(self.head(),self.origin);self.assertFalse(value['forecast_generation_created'])
        self.assertFalse((self.work/'FRONTIER.json').exists())

    def test_commit_operation_rejects_physical_mode_change(self):
        original=f.git
        def changed(root,*args,**kwargs):
            result=original(root,*args,**kwargs)
            if args and args[0]=='add':(self.root/'tools/helper.py').chmod(0o600)
            return result
        with patch.object(f,'git',new=changed):
            with self.assertRaisesRegex(ValueError,'before commit'):self.preserve()
        self.assertEqual(self.head(),self.origin)
    def test_commit_uses_real_git_clock_despite_caller_date_overrides(self):
        import time
        before=int(time.time())
        with patch.dict(os.environ,{'GIT_AUTHOR_DATE':'2001-01-01T00:00:00Z',
                'GIT_COMMITTER_DATE':'2001-01-01T00:00:00Z'}):
            value=self.preserve()
        self.assertGreaterEqual(datetime.fromisoformat(value['git_committer_at']).timestamp(),before)
        self.assertEqual(value['git_committer_at'],value['git_author_at'])
