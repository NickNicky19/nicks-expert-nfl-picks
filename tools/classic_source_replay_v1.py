"""Bounded original observations plus a separately timed current-history extension.

Recording never coalesces original requests: their order, repeated observations,
failures and actual clocks are retained. Reuse is by logical callsite/request and
ordinal. Only original-cache-hit historical stats may be additionally acquired.
Bodies remain private; no input tape is a public artifact or upstream-age proof.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import copy,hashlib,inspect,json,re,threading
from pathlib import Path
from urllib.parse import urlsplit

HOSTS={'api.sleeper.app','site.api.espn.com','sports.core.api.espn.com'}
MAX_REQUESTS=4096
MAX_RESPONSE=32<<20
MAX_TOTAL=256<<20
POSITIONS=['QB','RB','WR','TE','K','DEF']
SCHEMA='classic-source-observations-v2'

def now():return datetime.now(timezone.utc).isoformat()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(value):return hashlib.sha256(value).hexdigest()
class CoverageError(ValueError):pass

def callsite():
    names=[];frame=inspect.currentframe().f_back
    try:
        while frame:
            module=frame.f_globals.get('__name__')
            if module in {'sources','build','books','news','matchup'}:names.append(module+':'+frame.f_code.co_name)
            frame=frame.f_back
    finally:del frame
    return names

class Inputs:
    def __init__(self,directory,phase,fetch=None,allowed_stats_periods=()):
        if phase not in {'record','replay','extend'}:raise ValueError('INPUT_PHASE')
        self.directory=Path(directory);self.phase=phase;self.fetch=fetch
        self.lock=threading.RLock();self.local=threading.local()
        self.rows={};self.cursors={};self.used=0;self.fatal=[];self.total=0
        self.started_at=now();self.parent_index_sha256=None;self.extensions=[];self.common=0
        self.allowed={tuple(x)for x in allowed_stats_periods}
        if phase=='record':self.directory.mkdir(mode=0o700)
        else:
            if self.directory.is_symlink():raise CoverageError('INPUT_SYMLINK')
            raw=(self.directory/'INDEX.json').read_bytes()
            if len(raw)>4<<20:raise CoverageError('INPUT_INDEX_BOUND')
            index=json.loads(raw)
            if index.get('schema_version')!=SCHEMA or index.get('state')!='SEALED' or type(index.get('rows'))is not dict:raise CoverageError('INPUT_NOT_SEALED')
            self.rows=index['rows'];self.original_index_sha256=sha(raw)
            if phase=='extend':self.parent_index_sha256=sha(raw)
            else:self.parent_index_sha256=index.get('parent_index_sha256')
            self.started_at=index['started_at']
            count=0
            for key,observations in self.rows.items():
                if not re.fullmatch('[a-f0-9]{64}',key)or type(observations)is not list or not observations:raise CoverageError('INPUT_ROW_SCOPE')
                for row in observations:
                    count+=1
                    fields={'status','started_at','completed_at','origin'}|({'body_sha256','bytes'}if row.get('status')=='ok'else set())
                    if set(row)!=fields or row['status']not in {'ok','error'}or row['origin']not in {'ORIGINAL_OBSERVATION','CURRENT_HISTORY_EXTENSION'}:raise CoverageError('INPUT_ROW_FIELDS')
                    clocks=[datetime.fromisoformat(row[k])for k in ['started_at','completed_at']]
                    if any(c.tzinfo is None for c in clocks)or clocks[0]>clocks[1]:raise CoverageError('INPUT_CLOCK')
                    if row['status']=='ok':
                        if not isinstance(row['body_sha256'],str)or not re.fullmatch('[a-f0-9]{64}',row['body_sha256'])or type(row['bytes'])is not int or not 0<=row['bytes']<=MAX_RESPONSE:raise CoverageError('INPUT_BODY_SCOPE')
                        self.total+=row['bytes']
            if count>MAX_REQUESTS or self.total>MAX_TOTAL:raise CoverageError('INPUT_TOTAL_BOUND')
        self.base_keys=set(self.rows)

    def reject(self,reason):self.fatal.append(reason);raise CoverageError(reason)

    def extra_allowed(self,url,params,site):
        p=urlsplit(url);match=re.fullmatch('/stats/nfl/([0-9]{4})/([0-9]{1,2})',p.path)
        expected=[('season_type','regular'),*[('position[]',pos)for pos in POSITIONS]]
        return (p.hostname=='api.sleeper.app'and match is not None and tuple(map(int,match.groups()))in self.allowed
                and canonical(params)==canonical(expected)and 'build:week_stats'in site)

    def request(self,url,params=None,*args,**kwargs):
        with self.lock:
            parts=urlsplit(url)
            if parts.scheme!='https'or parts.hostname not in HOSTS or parts.username or parts.password or parts.port:return self.reject('SOURCE_ENDPOINT_SCOPE')
            if args or set(kwargs)-{'tries'}:return self.reject('SOURCE_ARGUMENT_SCOPE')
            site=callsite();key=sha(canonical(dict(url=url,params=params,callsite=site)));self.used+=1
            if self.phase!='record':
                cursor=self.cursors.get(key,0);observations=self.rows.get(key,[])
                if key in self.base_keys:
                    if cursor>=len(observations):return self.reject('UNRECORDED_SOURCE_OBSERVATION')
                    row=observations[cursor];self.cursors[key]=cursor+1;self.common+=1
                    if row['status']=='error':raise RuntimeError('RECORDED_SOURCE_UNAVAILABLE')
                    path=self.directory/(row['body_sha256']+'.json')
                    if path.is_symlink()or path.stat().st_size>MAX_RESPONSE:return self.reject('SOURCE_BODY_SCOPE')
                    raw=path.read_bytes()
                    if len(raw)!=row['bytes']or sha(raw)!=row['body_sha256']:return self.reject('SOURCE_BODY_MISMATCH')
                    return json.loads(raw)
                if self.phase!='extend':return self.reject('UNRECORDED_SOURCE_REQUEST')
                if not self.extra_allowed(url,params,site):return self.reject('UNQUALIFIED_CURRENT_SOURCE_EXTENSION')
            if sum(map(len,self.rows.values()))>=MAX_REQUESTS:return self.reject('SOURCE_REQUEST_BOUND')
            began=now();origin='ORIGINAL_OBSERVATION'if self.phase=='record'else'CURRENT_HISTORY_EXTENSION'
            try:
                self.local.active=True;response=self.fetch(url,params,**kwargs)
            except Exception:
                self.rows.setdefault(key,[]).append(dict(status='error',started_at=began,completed_at=now(),origin=origin));raise
            finally:self.local.active=False
            try:raw=canonical(response)
            except(ValueError,TypeError):return self.reject('SOURCE_JSON_DOMAIN')
            if len(raw)>MAX_RESPONSE or self.total+len(raw)>MAX_TOTAL:return self.reject('SOURCE_RESPONSE_BOUND')
            self.total+=len(raw);body=sha(raw);path=self.directory/(body+'.json')
            if not path.exists():path.write_bytes(raw);path.chmod(0o600)
            elif path.read_bytes()!=raw:return self.reject('SOURCE_BODY_COLLISION')
            row=dict(status='ok',started_at=began,completed_at=now(),origin=origin,body_sha256=body,bytes=len(raw))
            self.rows.setdefault(key,[]).append(row)
            if origin=='CURRENT_HISTORY_EXTENSION':self.extensions.append(dict(request_sha256=key,**row))
            return copy.deepcopy(response)

    def qualified(self):
        if self.fatal:raise CoverageError('SOURCE_COVERAGE_FAILED: '+','.join(self.fatal))

    def finish(self):
        self.qualified()
        if self.phase in {'record','extend'}:
            index=dict(schema_version=SCHEMA,state='SEALED',rows=self.rows,started_at=self.started_at,completed_at=now(),parent_index_sha256=self.parent_index_sha256)
            raw=canonical(index);(self.directory/'INDEX.json').write_bytes(raw);(self.directory/'INDEX.json').chmod(0o600)
            self.original_index_sha256=sha(raw)
        return dict(input_index_sha256=self.original_index_sha256,parent_index_sha256=self.parent_index_sha256,
                    used_requests=self.used,recorded_requests=sum(map(len,self.rows.values())),recorded_keys=len(self.rows),
                    common_observations_replayed=self.common,additional_requests=len(self.extensions),additional_observations=self.extensions,
                    phase=self.phase,completed_at=now(),claim='ACTUAL_REQUEST_OBSERVATIONS; NOT_IDENTICAL_COMPLETE_INPUTS_OR_UPSTREAM_AGE_PROOF')

    @contextmanager
    def install(self,sources,modules):
        import requests
        original=sources.get_json;saved=[]
        for module in [sources,*modules]:
            if hasattr(module,'sources')and module.sources is not sources:self.reject('SOURCE_MODULE_ALIAS_MISMATCH')
            for name,value in list(vars(module).items()):
                if value is original:saved.append((module,name,value));setattr(module,name,self.request)
        session_request=requests.sessions.Session.request;session_send=requests.sessions.Session.send
        def guarded(session,*args,**kwargs):
            if self.phase not in {'record','extend'}or not getattr(self.local,'active',False):return self.reject('UNINSTRUMENTED_NETWORK_REQUEST')
            return session_request(session,*args,**kwargs)
        def guarded_send(session,request,**kwargs):
            p=urlsplit(request.url)
            if self.phase not in {'record','extend'}or not getattr(self.local,'active',False):return self.reject('UNINSTRUMENTED_NETWORK_SEND')
            if p.scheme!='https'or p.hostname not in HOSTS or p.username or p.password or p.port:return self.reject('SOURCE_REDIRECT_SCOPE')
            return session_send(session,request,**kwargs)
        requests.sessions.Session.request=guarded;requests.sessions.Session.send=guarded_send
        try:yield self
        finally:
            requests.sessions.Session.request=session_request;requests.sessions.Session.send=session_send
            for module,name,value in saved:setattr(module,name,value)
