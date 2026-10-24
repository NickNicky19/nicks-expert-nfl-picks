"""Fictional metadata and tiny ZIPs only: no real Actions artifact or seed PASS."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import operating_seed_transport as t


def raw(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
def desc(value): return {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}


class Response(io.BytesIO):
    def __init__(self, value, length=None):
        super().__init__(value); self.headers = {} if length is None else {'Content-Length': str(length)}
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class Opener:
    def __init__(self, body, redirect=True): self.body = body; self.requests = []; self.redirect = redirect; self.length = len(body)
    def open(self, request, timeout):
        self.requests.append(request)
        if len(self.requests) == 1 and self.redirect:
            raise urllib.error.HTTPError(request.full_url, 302, 'fictional artifact redirect', {'Location': 'https://fictional.blob.core.windows.net/artifact?sig=fictional'}, None)
        return Response(self.body, self.length)


class API:
    def __init__(self, approval):
        now = datetime.now(timezone.utc)
        self.approval = approval; self.reads = 0; self.on_final = None
        self.repo = {'id': t.REPOSITORY_ID, 'full_name': t.REPOSITORY, 'private': False}
        self.workflow = {'id': approval['workflow_id'], 'path': t.WORKFLOW_PATH, 'state': 'active'}
        self.run = dict(id=approval['run_id'], run_attempt=1, head_sha=approval['installer_commit'], workflow_id=approval['workflow_id'],
                        path=t.WORKFLOW_PATH, event='workflow_dispatch', head_branch='upgrade/phase2-reproducible-comparison',
                        status='completed', conclusion='success', repository={'id': t.REPOSITORY_ID}, head_repository={'id': t.REPOSITORY_ID},
                        run_started_at=(now - timedelta(hours=2)).isoformat(), updated_at=(now - timedelta(minutes=30)).isoformat())
        self.artifact = dict(id=approval['artifact_id'], name=approval['artifact_name'], size_in_bytes=approval['artifact_size_bytes'], expired=False,
                             digest='sha256:' + approval['archive_sha256'], created_at=(now - timedelta(hours=1)).isoformat(), expires_at=approval['artifact_expires_at'],
                             workflow_run={'id': approval['run_id'], 'repository_id': t.REPOSITORY_ID, 'head_repository_id': t.REPOSITORY_ID,
                                           'head_sha': approval['installer_commit'], 'head_branch': 'upgrade/phase2-reproducible-comparison'})
        self.attempt = copy.deepcopy(self.run)
    def get(self, path):
        if path == '':
            self.reads += 1
            if self.reads == 2 and self.on_final: self.on_final()
            return copy.deepcopy(self.repo)
        if path.startswith('/actions/workflows/'): return copy.deepcopy(self.workflow)
        if path.startswith('/actions/artifacts/'): return copy.deepcopy(self.artifact)
        if '/attempts/' in path: return copy.deepcopy(self.attempt)
        if path.startswith('/actions/runs/'): return copy.deepcopy(self.run)
        raise AssertionError('Unexpected fictional metadata route')


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.code = self.root / 'code'; (self.code / 'tools').mkdir(parents=True)
        self.inputs = self.code / 'tools/diagnostic-seed-inputs.json'; self.inputs.write_bytes(b'{"fictional":1}')
        self.approved = dict(schema_version=t.SCHEMA, repository=t.REPOSITORY, repository_id=t.REPOSITORY_ID,
            workflow_id=1, workflow_path=t.WORKFLOW_PATH, artifact_id=2, artifact_name='fictional-seed-preparation-3',
            artifact_size_bytes=1, archive_bytes=1, archive_sha256='0'*64, run_id=3, run_attempt=1,
            installer_commit='1'*40, installer_tree='2'*40, seed_manifest_sha256='0'*64,
            seed_application_source='3'*40, seed_harness_sha256='4'*64, frozen_input_sha256=desc(self.inputs.read_bytes())['sha256'],
            integrity_sha256='5'*64, artifact_expires_at=(datetime.now(timezone.utc) + timedelta(days=6)).isoformat())
        self.files = {name: ('WHOLLY_FICTIONAL_' + name).encode() for name in t.SEED_FILES - {'SEED_MANIFEST.json'}}
        # Explicit fake aggregates for wholly fictional transport fixtures.
        self.synthetic_admission_metrics={'working_tree_bytes':101,'clean_checkout_bytes':202,
            'staged_bytes':303,'uploader_tar_bytes':404,'packed_bytes':505}
        admission={'status':'ADMITTED','metrics':{'public_semantics_sha256':'9'*64,**self.synthetic_admission_metrics}}
        seed = dict(admission_sha256=desc(raw(admission))['sha256'], semantic_sha256='9'*64, construction_source=self.approved['seed_application_source'],
                    roots={'public_source':self.approved['seed_application_source'],'fictional_head':'6'*40}, schema_version='fictional-operating-seed-v1', full_admitted=True, application_source=self.approved['seed_application_source'],
                    harness_sha256=self.approved['seed_harness_sha256'], working={'name':'working.tar.gz', **desc(self.files['working.tar.gz'])},
                    packs=[{'name':name, **desc(self.files[name]), 'objects':0} for name in ('fictional.pack', 'public-source.pack')])
        self.files['SEED_MANIFEST.json'] = raw(seed); self.approved['seed_manifest_sha256'] = desc(raw(seed))['sha256']
        results = {'ADMISSION.json': admission, 'RESTORATION.json': {'status':'PASS_SAVED_RECONSTRUCTION','semantic_sha256':'9'*64},
                   'RESOURCE.json': {'resource_verdict':'PASS'}, 'PREPARATION_RESULT.json': {'status':'PREPARATION_COMPLETE_NOT_OPERATING_QUALIFIED',
                   'seed_manifest_sha256':self.approved['seed_manifest_sha256'], 'input_contract_sha256':self.approved['frozen_input_sha256'],
                   'application_source':self.approved['seed_application_source'],'harness_sha256':self.approved['seed_harness_sha256']}}
        self.files.update({name:raw(value) for name,value in results.items()})
        self.refresh_envelope()
        self.token = patch.dict(os.environ, GH_TOKEN='fictional-token', GITHUB_TOKEN='fictional-token'); self.token.start(); self.addCleanup(self.token.stop)

    def refresh_envelope(self):
        envelope = dict(schema_version='cloud-seed-artifact-envelope-v1', files={name:desc(value) for name,value in self.files.items() if name!='ARTIFACT_MANIFEST.json'},
            application_source=self.approved['seed_application_source'], installer={'head':self.approved['installer_commit'],'tree':self.approved['installer_tree']},
            integrity_sha256=self.approved['integrity_sha256'], preparation_status='PREPARATION_COMPLETE_NOT_OPERATING_QUALIFIED', resource_verdict='PASS', operating_qualification='NOT_RUN')
        self.files['ARTIFACT_MANIFEST.json'] = raw(envelope)

    def archive(self, *, method=zipfile.ZIP_DEFLATED, extra=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=method) as output:
            for name,value in self.files.items(): output.writestr(name,value)
            if extra is not None: output.writestr(*extra)
        value = stream.getvalue(); self.approved.update(archive_bytes=len(value), artifact_size_bytes=len(value), archive_sha256=desc(value)['sha256'])
        return value

    def retrieve(self, body=None, *, api=None, opener=None, destination=None):
        body = self.archive() if body is None else body
        return t.retrieve(self.code, destination or self.root/'retrieved', self.approved, deadline=time.monotonic()+600, api=api or API(self.approved), opener=opener or Opener(body))

    def test_complete_transport_keeps_exact_four_parents_and_strips_redirect_credential(self):
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            body = self.archive(method=method); opener = Opener(body)
            destination = self.root / ('retrieved-'+str(method)); result = self.retrieve(body, opener=opener, destination=destination)
            self.assertEqual({item.name for item in destination.iterdir()}, t.SEED_FILES)
            self.assertEqual(result['seed_manifest_sha256'], self.approved['seed_manifest_sha256'])
            self.assertEqual(result['admission_metrics'],self.synthetic_admission_metrics)
            self.assertIn('TRANSPORT_ONLY', result['claim'])
            self.assertEqual(opener.requests[0].get_header('Authorization'), 'Bearer fictional-token')
            self.assertIsNone(opener.requests[1].get_header('Authorization'))
            self.assertEqual(opener.requests[0].get_header('Cache-control'), 'no-cache')

    def test_single_disk_zip64_directory_with_small_members_is_supported(self):
        body=self.archive();position=body.rfind(b'PK\x05\x06')
        _,_,_,count,total,length,offset,comment=struct.unpack('<4s4H2LH',body[position:position+22])
        directory=struct.pack('<4sQ2H2L4Q',b'PK\x06\x06',44,45,45,0,0,count,total,length,offset)
        locator=struct.pack('<4sLQL',b'PK\x06\x07',0,position,1)
        body=body[:position]+directory+locator+body[position:]
        self.approved.update(archive_bytes=len(body),artifact_size_bytes=len(body),archive_sha256=desc(body)['sha256'])
        self.assertIn('TRANSPORT_ONLY',self.retrieve(body)['claim'])

    def test_unpopulated_or_unknown_approval_is_rejected_without_transport(self):
        original = copy.deepcopy(self.approved)
        for update in ({'artifact_id':None},{'run_attempt':2},{'artifact_name':'other'},{'repository':'other/repo'},{'unexpected':1}):
            self.approved = {**original, **update}
            with self.subTest(update=update), self.assertRaises(t.Rejected): self.retrieve()

    def test_wrong_artifact_run_source_fork_attempt_expiry_and_status_are_rejected(self):
        body = self.archive()
        variants = [('artifact', 'digest', 'sha256:'+'f'*64), ('artifact','size_in_bytes',1), ('artifact','expired',True),
                    ('artifact','name','wrong'), ('run','run_attempt',2), ('run','status','in_progress'), ('run','head_sha','f'*40),
                    ('attempt','conclusion','failure'), ('run','head_repository',{'id':999})]
        for obj,key,value in variants:
            api = API(self.approved); getattr(api,obj)[key]=value
            with self.subTest(obj=obj,key=key), self.assertRaises(t.Rejected): self.retrieve(body,api=api)

    def test_missing_duplicate_unknown_traversal_and_symlink_zip_members_reject(self):
        original = dict(self.files)
        for name in ('working.tar.gz','../raw.log','raw.log','working.tar.gz.part-0000'):
            self.files = dict(original)
            body = self.archive(extra=(name,b'fictional extra'))
            with self.subTest(name=name), self.assertRaises(t.Rejected): self.retrieve(body)
        self.files = dict(original); del self.files['fictional.pack']; body=self.archive()
        with self.assertRaises(t.Rejected): self.retrieve(body)
        self.files=dict(original); stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as zipped:
            for name,value in self.files.items():
                entry=zipfile.ZipInfo(name);entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16 if name=='fictional.pack' else 0
                zipped.writestr(entry,value)
        body=stream.getvalue();self.approved.update(archive_bytes=len(body),artifact_size_bytes=len(body),archive_sha256=desc(body)['sha256'])
        with self.assertRaises(t.Rejected): self.retrieve(body)

    def test_nul_disguised_name_and_boolean_seed_size_are_not_supported(self):
        # Equal-length local+central names; ZipInfo exposes the truncated prefix
        # as filename but retains the original NUL suffix in orig_filename.
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as output:
            for name,value in self.files.items():
                if name=='fictional.pack':name='fictional.packX'
                output.writestr(name,value)
        disguised=stream.getvalue().replace(b'fictional.packX',b'fictional.pack\x00')
        self.approved.update(archive_bytes=len(disguised),artifact_size_bytes=len(disguised),archive_sha256=desc(disguised)['sha256'])
        with self.assertRaises(t.Rejected):self.retrieve(disguised)
        seed=json.loads(self.files['SEED_MANIFEST.json']);self.files['working.tar.gz']=b'x'
        seed['working']={'name':'working.tar.gz','bytes':True,'sha256':desc(b'x')['sha256']}
        self.files['SEED_MANIFEST.json']=raw(seed);self.approved['seed_manifest_sha256']=desc(raw(seed))['sha256']
        result=json.loads(self.files['PREPARATION_RESULT.json']);result['seed_manifest_sha256']=self.approved['seed_manifest_sha256']
        self.files['PREPARATION_RESULT.json']=raw(result);self.refresh_envelope()
        with self.assertRaisesRegex(t.Rejected,'Invalid typed seed parent descriptor'):self.retrieve()

    def test_self_consistent_zip_corrupt_parent_and_unknown_seed_schema_reject(self):
        original = dict(self.files)
        for mutate in ('parent','schema','boolean','envelope'):
            self.files = dict(original)
            if mutate=='parent': self.files['working.tar.gz']+=b'changed'
            elif mutate in ('schema','boolean'):
                seed=json.loads(self.files['SEED_MANIFEST.json']);seed['schema_version']='unknown' if mutate=='schema' else seed['schema_version']
                if mutate=='boolean':seed['full_admitted']=1
                self.files['SEED_MANIFEST.json']=raw(seed);self.approved['seed_manifest_sha256']=desc(raw(seed))['sha256']
            else:self.files['ARTIFACT_MANIFEST.json']=raw({})
            if mutate!='envelope':self.refresh_envelope()
            body=self.archive()
            with self.subTest(mutate=mutate),self.assertRaises(t.Rejected):self.retrieve(body)

    def test_rehashed_envelope_cannot_change_original_admission_or_reconstruction(self):
        original = dict(self.files)
        for member, key, value in (('ADMISSION.json','metrics',{'public_semantics_sha256':'f'*64}),
                                   ('RESTORATION.json','semantic_sha256','f'*64),
                                   ('PREPARATION_RESULT.json','harness_sha256','f'*64)):
            self.files=dict(original);changed=json.loads(self.files[member]);changed[key]=value;self.files[member]=raw(changed)
            self.refresh_envelope();body=self.archive()
            with self.subTest(member=member),self.assertRaises(t.Rejected):self.retrieve(body)

    def test_self_consistent_original_admission_missing_or_invalid_byte_metrics_reject(self):
        original=dict(self.files)
        # Rebind every enclosing checksum so these cases reach the numeric
        # aggregate guard rather than an earlier transport/seed identity guard.
        for key in self.synthetic_admission_metrics:
            for invalid in ('missing',None,True,-1,'unknown',1.5):
                self.files=dict(original);admission=json.loads(self.files['ADMISSION.json'])
                if invalid=='missing':del admission['metrics'][key]
                else:admission['metrics'][key]=invalid
                self.files['ADMISSION.json']=raw(admission)
                seed=json.loads(self.files['SEED_MANIFEST.json']);seed['admission_sha256']=desc(raw(admission))['sha256']
                self.files['SEED_MANIFEST.json']=raw(seed);self.approved['seed_manifest_sha256']=desc(raw(seed))['sha256']
                preparation=json.loads(self.files['PREPARATION_RESULT.json']);preparation['seed_manifest_sha256']=self.approved['seed_manifest_sha256']
                self.files['PREPARATION_RESULT.json']=raw(preparation);self.refresh_envelope();body=self.archive()
                with self.subTest(metric=key,invalid=invalid),self.assertRaisesRegex(t.Rejected,'Original admission requires all five nonnegative integer byte metrics'):
                    self.retrieve(body)
                self.assertFalse((self.root/'retrieved').exists())

    def test_bound_original_admission_zero_byte_metrics_are_returned_without_other_records(self):
        admission=json.loads(self.files['ADMISSION.json'])
        admission['metrics'].update({key:0 for key in self.synthetic_admission_metrics})
        admission['metrics']['fixture_only_record']={'fictional':'not a returned aggregate'}
        self.files['ADMISSION.json']=raw(admission)
        seed=json.loads(self.files['SEED_MANIFEST.json']);seed['admission_sha256']=desc(raw(admission))['sha256']
        self.files['SEED_MANIFEST.json']=raw(seed);self.approved['seed_manifest_sha256']=desc(raw(seed))['sha256']
        preparation=json.loads(self.files['PREPARATION_RESULT.json']);preparation['seed_manifest_sha256']=self.approved['seed_manifest_sha256']
        self.files['PREPARATION_RESULT.json']=raw(preparation);self.refresh_envelope()
        result=self.retrieve()
        self.assertEqual(result['admission_metrics'],{key:0 for key in self.synthetic_admission_metrics})
        self.assertTrue(all(type(value) is int for value in result['admission_metrics'].values()))
        self.assertEqual({item.name for item in (self.root/'retrieved').iterdir()},t.SEED_FILES)

    def test_transient_self_consistent_metadata_changes_cannot_change_returned_metrics(self):
        real_content=t._content
        def transient_changes(stage,inventory,approved,deadline=None):
            originals={name:(stage/name).read_bytes() for name in ('ADMISSION.json','SEED_MANIFEST.json')}
            admission=json.loads(originals['ADMISSION.json']);admission['metrics']['working_tree_bytes']=999999
            seed=json.loads(originals['SEED_MANIFEST.json']);seed['admission_sha256']=desc(raw(admission))['sha256']
            (stage/'ADMISSION.json').write_bytes(raw(admission));(stage/'SEED_MANIFEST.json').write_bytes(raw(seed))
            try:return real_content(stage,inventory,approved,deadline)
            finally:
                # Final file rehashes alone would accept these restored originals
                # while retaining altered in-memory parsed admission metrics.
                for name,value in originals.items():(stage/name).write_bytes(value)
        with patch.object(t,'_content',side_effect=transient_changes),self.assertRaisesRegex(t.Rejected,'Transport JSON bytes changed before parsing'):
            self.retrieve()
        self.assertFalse((self.root/'retrieved').exists())

    def test_streamed_compressed_decoded_json_and_central_directory_bounds(self):
        body=self.archive();opener=Opener(body);opener.length=len(body)+1
        with self.assertRaises(t.Rejected):self.retrieve(body,opener=opener)
        with patch.object(t,'LIMIT',len(body)-1),self.assertRaises(t.Rejected):self.retrieve(body)
        self.files['fictional.pack']=b'a'*100000;self.refresh_envelope();body=self.archive()
        with patch.object(t,'LIMIT',max(len(body)+100,5000)),self.assertRaises(t.Rejected):self.retrieve(body)
        body=self.archive()
        with patch.object(t,'JSON_LIMIT',4),self.assertRaises(t.Rejected):self.retrieve(body)
        altered=bytearray(body);position=altered.rfind(b'PK\x05\x06');struct.pack_into('<L',altered,position+12,t.CENTRAL_LIMIT+1)
        path=self.root/'bad-central.zip';path.write_bytes(altered)
        with patch.object(t.zipfile,'ZipFile',side_effect=AssertionError('Must bound directory first')),self.assertRaises(t.Rejected):t._zip_inventory(path)

    def test_truncated_transfer_wrong_digest_and_unapproved_redirect_reject(self):
        body=self.archive()
        for changed in (body[:-1], body+b'extra', b'x'*len(body)):
            with self.subTest(size=len(changed)),self.assertRaises(t.Rejected):self.retrieve(body,opener=Opener(changed))
        class Evil:
            def open(self,request,timeout):raise urllib.error.HTTPError(request.full_url,302,'fictional',{'Location':'https://unapproved.example/archive'},None)
        with self.assertRaises(t.Rejected):self.retrieve(body,opener=Evil())

    def test_final_metadata_mutation_and_same_size_restored_mtime_input_change_reject(self):
        body=self.archive();api=API(self.approved)
        api.on_final=lambda:api.artifact.update(expired=True)
        with self.assertRaises(t.Rejected):self.retrieve(body,api=api)
        api=API(self.approved);info=self.inputs.stat()
        def mutate():
            self.inputs.write_bytes(b'{"fictional":2}');os.utime(self.inputs,ns=(info.st_atime_ns,info.st_mtime_ns))
        api.on_final=mutate
        with self.assertRaises(t.Rejected):self.retrieve(body,api=api)
        self.assertFalse((self.root/'retrieved').exists())

    def test_one_deadline_covers_metadata_and_transport_and_approval_bytes_are_bound(self):
        body=self.archive();api=API(self.approved)
        with self.assertRaises(t.Rejected): t.retrieve(self.code,self.root/'late',self.approved,deadline=time.monotonic()-1,api=api,opener=Opener(body))
        self.assertEqual(api.reads,0)
        with self.assertRaises(t.Rejected): t.retrieve(self.code,self.root/'too-long',self.approved,deadline=time.monotonic()+1300,api=api,opener=Opener(body))
        approval_path=self.root/'approval.json';approval_path.write_bytes(raw(self.approved));expected=desc(approval_path.read_bytes())['sha256']
        self.assertEqual(t.read_approval(approval_path,expected),self.approved)
        approval_path.write_bytes(raw({**self.approved,'artifact_id':999}))
        with self.assertRaises(t.Rejected):t.read_approval(approval_path,expected)
        with patch.object(t.time,'monotonic',side_effect=[1,1,2,999]),self.assertRaises(t.Rejected):
            t.retrieve(self.code,self.root/'expired-transport',self.approved,deadline=100,api=api,opener=Opener(body))

    def test_actual_oversized_regular_files_reject_before_read_allocation(self):
        for kind, limit in (('json',t.JSON_LIMIT),('approval',t.JSON_LIMIT),('hash',t.LIMIT)):
            path=self.root/('oversized-'+kind)
            # Sparse real files exercise the production limits without allocating
            # either their decoded memory or their nominal disk size.
            with path.open('wb') as stream:stream.truncate(limit+1)
            operation={'json':lambda:t._json(path),
                       'approval':lambda:t.read_approval(path,'0'*64),
                       'hash':lambda:t._hash(path,time.monotonic()+60)}[kind]
            with self.subTest(kind=kind),patch.object(t.os,'read',side_effect=AssertionError('Oversized file must fail before read')),self.assertRaises(t.Rejected):
                operation()

    def test_json_approval_and_hash_bound_actual_growth_after_open(self):
        for kind in ('json','approval','hash'):
            path=self.root/('growing-'+kind);initial=raw(self.approved);path.write_bytes(initial)
            limit=len(initial)+16;reads=[];real_read=os.read
            def grow_after_first_read(descriptor,count):
                value=real_read(descriptor,count);reads.append((count,len(value)))
                if len(reads)==1:
                    # A real append after fstat must still hit the read budget.
                    with path.open('ab') as stream:stream.write(b' '*(limit+1))
                return value
            operation={'json':lambda:t._json(path),
                       'approval':lambda:t.read_approval(path,desc(initial)['sha256']),
                       'hash':lambda:t._hash(path,time.monotonic()+60)}[kind]
            with self.subTest(kind=kind),patch.object(t,'JSON_LIMIT',limit),patch.object(t,'LIMIT',limit),patch.object(t,'CHUNK',8),patch.object(t.os,'read',side_effect=grow_after_first_read),self.assertRaisesRegex(t.Rejected,'exceeds its bound'):
                operation()
            self.assertGreater(path.stat().st_size,limit)
            self.assertEqual(sum(size for _,size in reads),limit+1)
            self.assertTrue(all(0<count<=8 for count,_ in reads))

    def test_actual_symlink_substitution_and_nonregular_descriptors_reject(self):
        target=self.root/'target.json';target.write_bytes(raw(self.approved))
        for kind in ('json','approval','hash'):
            path=self.root/('replaced-'+kind);path.write_bytes(b'{}');real_open=os.open
            def replace_before_open(name,flags,*args,**kwargs):
                self.assertTrue(flags & os.O_NOFOLLOW)
                path.unlink();path.symlink_to(target)
                return real_open(name,flags,*args,**kwargs)
            operation={'json':lambda:t._json(path),
                       'approval':lambda:t.read_approval(path,desc(target.read_bytes())['sha256']),
                       'hash':lambda:t._hash(path,time.monotonic()+60)}[kind]
            with self.subTest(kind=kind),patch.object(t.os,'open',side_effect=replace_before_open),patch.object(t.os,'read',side_effect=AssertionError('Symlink target must not be read')),self.assertRaises(t.Rejected):
                operation()
        fifo=self.root/'fifo';os.mkfifo(fifo)
        for kind in ('json','approval','hash'):
            operation={'json':lambda:t._json(fifo),
                       'approval':lambda:t.read_approval(fifo,'0'*64),
                       'hash':lambda:t._hash(fifo,time.monotonic()+60)}[kind]
            with self.subTest(kind=kind),self.assertRaises(t.Rejected):operation()

    def test_readers_remain_bound_to_open_descriptor_when_path_is_replaced(self):
        initial=raw(self.approved)
        for kind in ('json','approval','hash'):
            path=self.root/('opened-'+kind);path.write_bytes(initial);real_open=os.open
            def replace_after_open(name,flags,*args,**kwargs):
                descriptor=real_open(name,flags,*args,**kwargs)
                path.unlink();path.write_bytes(b'{}')
                return descriptor
            operation={'json':lambda:t._json(path),
                       'approval':lambda:t.read_approval(path,desc(initial)['sha256']),
                       'hash':lambda:t._hash(path,time.monotonic()+60)}[kind]
            expected=desc(initial) if kind=='hash' else self.approved
            with self.subTest(kind=kind),patch.object(t.os,'open',side_effect=replace_after_open):
                self.assertEqual(operation(),expected)
            self.assertEqual(path.read_bytes(),b'{}')

    def test_open_descriptor_readers_preserve_exact_caps_and_deadline(self):
        approval_path=self.root/'approval-at-limit.json';value=raw(self.approved);approval_path.write_bytes(value)
        with patch.object(t,'JSON_LIMIT',len(value)),patch.object(t,'LIMIT',len(value)):
            self.assertEqual(t._json(approval_path),self.approved)
            self.assertEqual(t.read_approval(approval_path,desc(value)['sha256']),self.approved)
            self.assertEqual(t._hash(approval_path,time.monotonic()+60),desc(value))
        for operation in (lambda:t._json(approval_path,time.monotonic()-1),
                          lambda:t.read_approval(approval_path,desc(value)['sha256'],deadline=time.monotonic()-1),
                          lambda:t._hash(approval_path,time.monotonic()-1)):
            with patch.object(t.os,'open',side_effect=AssertionError('Expired reads must not open')),self.assertRaises(t.Rejected):operation()

    def test_existing_destination_is_not_overwritten_and_corrupt_zip_crc_rejects(self):
        destination=self.root/'exists';destination.mkdir();(destination/'preserved').write_bytes(b'keep')
        with self.assertRaises(t.Rejected):self.retrieve(destination=destination)
        self.assertEqual((destination/'preserved').read_bytes(),b'keep')
        body=bytearray(self.archive(method=zipfile.ZIP_STORED));index=body.find(b'WHOLLY_FICTIONAL_');body[index]^=1;body=bytes(body)
        self.approved.update(archive_bytes=len(body),artifact_size_bytes=len(body),archive_sha256=desc(body)['sha256'])
        with self.assertRaises(t.Rejected):self.retrieve(body)


if __name__=='__main__':unittest.main()
