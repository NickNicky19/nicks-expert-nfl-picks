"""Portable website consumer checks; fictional inputs, no HTTP or NFL files."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import weekly_public_feed as f
from test_weekly_adaptive_overlay import fixture


class PublicFeedInputChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for name in f.LEGACY_CODE_FILES:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('FICTIONAL '+name).encode())
        self.git('init','-q');self.git('add','.');self.git('-c','user.name=F','-c','user.email=f@example.invalid','commit','-qm','fixture')
        self.head=self.git('rev-parse','HEAD');self.board,selected,_=fixture();self.now='2026-10-24T10:10:00Z'
        pins={k:f.sha((self.root/k).read_bytes()) for k in f.LEGACY_CODE_FILES};self.policy=dict(schema_version=f.POLICY,registration_id='weekly-adaptive-release-v1',producer_policy_sha256='a'*64,source_policy_sha256='d'*64,
            public_fields=list(f.overlay().ROW_FIELDS),procedures={},public_roles={},rights_authorities=['b'*64],r0_identities=['c'*64],engine_sha256={k:pins[k] for k in f.ENGINE_FILES},website_code_sha256=pins,public_ref='lab-state')
        rows=[]
        for row in selected['rows']:
            rows.append({k:row[k] for k in f.overlay().ROW_FIELDS});self.policy['procedures'][row['category']]=[{k:row[k] for k in ['method_id','model_version','procedure_version','product','source_policy_sha256']}];self.policy['public_roles'][row['category']]=['RB']
        self.feed=dict(schema_version=f.VERSION,state='DERIVED_SELECTED_ONLY',season=self.board['season'],week=self.board['week'],created_at='2026-10-24T10:02:00Z',expires_at=rows[0]['valid_until_utc'],producer_policy_sha256='a'*64,rights_authority_sha256='b'*64,rights_receipt_sha256='d'*64,durability_receipt_sha256='e'*64,r0_identity_sha256='c'*64,identity_scope_sha256=f.identity_scope(rows,self.board),rows=rows,coverage=dict(private_selected_rows=len(rows),public_rows=len(rows),fallback_counts={}))
    def tearDown(self):self.temp.cleanup()
    def git(self,*args):
        return subprocess.run(['git','--no-lazy-fetch','-c','core.hooksPath=/dev/null',*args],cwd=self.root,env=dict(os.environ,GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null'),capture_output=True,text=True,check=True).stdout.strip()
    def test_current_data_HEAD_review_is_automated_under_same_code(self):
        selected,review,receipt=f.writer_input(self.root,self.policy,self.board,website_source_sha=self.head,now=self.now,feed=self.feed)
        self.assertEqual(receipt['state'],'AUTOMATED_POLICY_ACCEPTED');self.assertFalse(review['human_approval']);self.assertEqual(len(selected['rows']),3)
        (self.root/'fresh-data.json').write_text('{}');self.git('add','.');self.git('-c','user.name=F','-c','user.email=f@example.invalid','commit','-qm','data')
        head=self.git('rev-parse','HEAD');self.assertNotEqual(head,self.head)
        self.assertEqual(f.writer_input(self.root,self.policy,self.board,website_source_sha=head,now=self.now,feed=self.feed)[1]['website_source_sha'],head)
    def test_corrupt_late_absent_or_new_code_uses_R0(self):
        for update in [dict(expires_at='2000-01-01T00:00:00Z'),dict(rows=[dict(self.feed['rows'][0],product='point_blend')]),dict(raw_inputs=['FICTIONAL'])]:
            self.assertEqual(f.writer_input(self.root,self.policy,self.board,website_source_sha=self.head,now=self.now,feed=dict(self.feed,**update))[0],{})
        self.assertEqual(f.writer_input(self.root,self.policy,self.board,website_source_sha=self.head,now=self.now,fetch=lambda *_:(_ for _ in ()).throw(TimeoutError()))[0],{})
        (self.root/'pull/build.py').write_text('CHANGED');self.assertEqual(f.writer_input(self.root,self.policy,self.board,website_source_sha=self.head,now=self.now,feed=self.feed)[0],{})
    def test_board_identity_and_extra_row_fields_are_strict(self):
        for update in [dict(player_id='not-on-board'),dict(model_weights=['FICTIONAL'])]:
            doc=deepcopy(self.feed);doc['rows'][0].update(update)
            self.assertEqual(f.writer_input(self.root,self.policy,self.board,website_source_sha=self.head,now=self.now,feed=doc)[0],{})


if __name__=='__main__':unittest.main()
