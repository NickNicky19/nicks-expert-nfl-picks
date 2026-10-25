#!/usr/bin/env node
'use strict';
// BEGIN BOUNDED BROWSER FAILURE TELEMETRY
const BROWSER_FAILURE_PHASES=Object.freeze(['B001','B002','B003','B004','B005','B006','B007','B008','B009','B010','B011','B012','B013','B014','B015','B016','B017','B018','B019','B020','B021','B022','B023','B024','B025','B026','B027','B028','B029']);
const BROWSER_FAILURE_KINDS=Object.freeze(['ASSERTION','TIMEOUT','TYPE','REFERENCE','SYNTAX','RANGE','ERROR','OTHER','MODULE_NOT_FOUND','ENOENT','EACCES','ENOSPC','ENOMEM','FILESYSTEM_GUARD','BROWSER_DEADLINE']);
let browserPhase='B001',browserViewport=0,browserDiagnosticIssued=false;
const browserReviewStartedAt=Date.now();
function browserFailureDiagnostic(error,forced='') {
  const names={AssertionError:'ASSERTION',TimeoutError:'TIMEOUT',TypeError:'TYPE',ReferenceError:'REFERENCE',SyntaxError:'SYNTAX',RangeError:'RANGE',Error:'ERROR'};
  const name=error&&typeof error.name==='string'?error.name:'';
  let kind=Object.hasOwn(names,name)?names[name]:'OTHER';
  if(error&&['MODULE_NOT_FOUND','ENOENT','EACCES','ENOSPC','ENOMEM'].includes(error.code))kind=error.code;
  if(BROWSER_FAILURE_KINDS.includes(forced))kind=forced;
  return {schema_version:'release-browser-failure-diagnostic-v1',stage:BROWSER_FAILURE_PHASES.includes(browserPhase)?browserPhase:'B001',kind,viewport:[1280,390,320].includes(browserViewport)?browserViewport:0};
}
function reportBrowserFailure(error,forced='') {
  if(browserDiagnosticIssued)return;
  browserDiagnosticIssued=true;
  try{process.stderr.write('NFL_BROWSER_FAILURE_DIAGNOSTIC_V1='+JSON.stringify(browserFailureDiagnostic(error,forced))+'\n');}catch{}
}
process.on('uncaughtExceptionMonitor',error=>reportBrowserFailure(error));
// END BOUNDED BROWSER FAILURE TELEMETRY
// Local acceptance of the ACTUAL staged package. Never modifies staged/evidence files.
// Saved tickets/picks exist only in new disposable browser contexts at actual time.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const vm = require('node:vm');
const cp = require('node:child_process');
browserPhase='B002';
const { chromium } = require('playwright');
const argv = process.argv.slice(2);
const arg = (key, fallback) => argv.includes(key) ? argv[argv.indexOf(key) + 1] : fallback;
const markerPath = path.resolve(arg('--manifest') || arg('--marker') || '');
assert.ok(arg('--manifest') || arg('--marker'), 'Actual RELEASE_CASE_MANIFEST is required');
assert.ok(arg('--root'), 'Actual artifact Pages root is required, including for public comparison');
const root = fs.realpathSync(arg('--root'));
const publicURL = arg('--url');
if(publicURL){const u=new URL(publicURL);assert.equal(u.protocol,'https:');assert.ok(!u.search&&!u.hash&&!u.username&&!u.password);}
const canonical = v => JSON.stringify(v&&typeof v==='object'?(Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))]))):v);
const reserve=2147483648;
function existingAncestor(value){let p=path.resolve(value);for(;;){try{fs.lstatSync(p);return p;}catch(e){if(e.code!=='ENOENT')throw e;const parent=path.dirname(p);assert.notEqual(parent,p);p=parent;}}}
function resolvedDestination(value){const p=path.resolve(value),ancestor=existingAncestor(p);return path.resolve(fs.realpathSync(ancestor),path.relative(ancestor,p));}
function overlaps(a,b){const prefix=p=>p===path.sep?p:p+path.sep;return a===b||a.startsWith(prefix(b))||b.startsWith(prefix(a));}
function destinationsSafe(protectedRoots,outputs){const roots=protectedRoots.map(resolvedDestination),dest=outputs.map(resolvedDestination);assert.ok(dest.every(p=>roots.every(r=>!overlaps(p,r))),'OUTPUT_OVERLAPS_ARTIFACT');return dest;}
function filesystemGuard(paths,extra=0,reader=p=>fs.statfsSync(existingAncestor(p))){return paths.map(p=>{const s=reader(p),total=s.blocks*s.bsize,available=s.bavail*s.bsize,floor=Math.max(reserve,Math.ceil(total*.2));assert.ok(available>=floor+extra,'CRITICAL_FILESYSTEM_RESERVE');return {path:p,total_bytes:total,free_bytes:available,reserve_bytes:floor};});}
function latchFailure(state,error){if(!state.failure)state.failure=error;}
function settleStatus(record,state,success){if(state.failure){record.status='FAIL';record.error='CRITICAL_FILESYSTEM_RESERVE';return false;}if(success)record.status=success;return true;}
browserPhase='B003';
assert.equal(require('playwright/package.json').version,'1.62.1','Pinned Playwright required');
browserPhase='B004';
const chrome=process.env.NFL_CHROMIUM_PATH||['/usr/bin/google-chrome','/usr/bin/google-chrome-stable','/usr/bin/chromium'].find(p=>fs.existsSync(p));
assert.ok(chrome&&fs.statSync(chrome).isFile(),'UNSUPPORTED_PREINSTALLED_CHROME_UNAVAILABLE');
assert.ok(arg('--result'),'Bounded result path required');
const evidence=path.resolve(arg('--evidence',path.dirname(arg('--result'))));
assert.ok(arg('--artifact-root'),'Exact extracted artifact root required');
const artifactRoot=fs.realpathSync(arg('--artifact-root')),resultPath=path.resolve(arg('--result')),profileRoot=path.resolve(arg('--profile-root',resultPath+'.profiles'));
browserPhase='B005';
destinationsSafe([root,artifactRoot,path.dirname(markerPath)],[resultPath,evidence,profileRoot]);
assert.ok(!fs.existsSync(resultPath)&&!fs.existsSync(profileRoot),'Fresh result/profile paths required');
const criticalPaths=[root,artifactRoot,markerPath,resultPath,evidence,profileRoot,'/tmp',process.env.TMPDIR||'/tmp',process.env.RUNNER_TEMP||'/tmp',process.cwd(),chrome,require.resolve('playwright')];
browserPhase='B006';
const initialFilesystems=filesystemGuard(criticalPaths,12*1024*1024);
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const readJSON = filename => JSON.parse(fs.readFileSync(filename));
// BEGIN WEEKLY DISPLAY GRAPH CONTRACT
const WEEKLY_HELPER_SHA256='d6657e82639aa001f64701672e25cc72bd6e55142127669a59396f9efe485a68';
function readWeeklyAsset(filename,cap,io=fs) {
  assert.ok(Number.isSafeInteger(cap)&&cap>0&&cap<=16*1024*1024,'WEEKLY_READ_LIMIT');
  const flags=io.constants;assert.ok(Number.isInteger(flags.O_NOFOLLOW)&&Number.isInteger(flags.O_NONBLOCK),'WEEKLY_READER_PLATFORM');
  const fd=io.openSync(filename,flags.O_RDONLY|flags.O_NOFOLLOW|flags.O_NONBLOCK);
  try{
    const first=io.fstatSync(fd);
    assert.ok(first.isFile()&&Number.isSafeInteger(first.size)&&first.size>=0&&first.size<=cap,'WEEKLY_BOUNDED_REGULAR_FILE');
    const chunks=[],buffer=Buffer.alloc(Math.min(65536,cap+1));let bytes=0;
    for(;;){const count=io.readSync(fd,buffer,0,Math.min(buffer.length,cap+1-bytes),null);if(!count)break;
      bytes+=count;assert.ok(bytes<=cap,'WEEKLY_STREAMED_BOUND');chunks.push(Buffer.from(buffer.subarray(0,count)));}
    const after=io.fstatSync(fd),current=io.lstatSync(filename);
    assert.ok(after.isFile()&&current.isFile()&&!current.isSymbolicLink()&&first.dev===after.dev&&first.ino===after.ino
      &&after.dev===current.dev&&after.ino===current.ino&&first.size===bytes&&after.size===bytes&&current.size===bytes,'WEEKLY_READ_RACE');
    return Buffer.concat(chunks,bytes);
  }finally{io.closeSync(fd);}
}
function weeklyDisplayGraph(pointer,body,actualBoard,boardHash,source,helper) {
  assert.deepEqual(Object.keys(pointer).sort(),['schema_version','path','sha256','bytes','display_board_sha256'].sort(),'WEEKLY_POINTER_CLOSED');
  assert.equal(pointer.schema_version,'weekly-adaptive-overlay-pointer-v1');
  assert.match(pointer.sha256,/^[a-f0-9]{64}$/);
  assert.equal(pointer.path,'data/weekly-adaptive/'+pointer.sha256+'.json');
  assert.ok(Number.isSafeInteger(pointer.bytes)&&pointer.bytes>0&&pointer.bytes<=4*1024*1024);
  assert.equal(pointer.display_board_sha256,boardHash,'WEEKLY_ACTUAL_BOARD_BINDING');
  assert.equal(body.length,pointer.bytes);assert.equal(sha(body),pointer.sha256,'WEEKLY_ACTUAL_BODY_HASH');
  const doc=JSON.parse(body),value=helper.validate(doc,actualBoard,boardHash);
  assert.equal(doc.website_source_sha,source,'WEEKLY_ACTUAL_SOURCE_BINDING');
  assert.equal(value.rows.size,doc.rows.length);
  return {pointer,doc};
}
// END WEEKLY DISPLAY GRAPH CONTRACT
// BEGIN SELECTED RANKING GRAPH CONTRACT
function rankingPublicLimit(name) {
  if(name==='data/weekly-selected-rankings.json')return 4096;
  if(/^data\/weekly-selected-rankings\/[a-f0-9]{64}\.receipt\.json$/.test(name))return 4096;
  if(/^data\/weekly-selected-rankings\/[a-f0-9]{64}\.json$/.test(name))return 262144;
  throw Error('RANKING_PUBLIC_PATH');
}
function rankingArtifactMembers(directory,io=fs) {
  const result={},pointer='data/weekly-selected-rankings.json';
  result[pointer]=readWeeklyAsset(path.join(directory,pointer),rankingPublicLimit(pointer),io);
  const folder=path.join(directory,'data/weekly-selected-rankings'),info=io.lstatSync(folder);
  assert.ok(info.isDirectory()&&!info.isSymbolicLink(),'RANKING_REGULAR_DIRECTORY');
  const stream=io.opendirSync(folder);let count=0;
  try{for(;;){const item=stream.readSync();if(!item)break;assert.ok(++count<=50,'RANKING_COMPLETE_GRAPH_BOUND');
    const name='data/weekly-selected-rankings/'+item.name;
    assert.ok(item.isFile()&&!item.isSymbolicLink(),'RANKING_REGULAR_MEMBER');
    result[name]=readWeeklyAsset(path.join(directory,name),rankingPublicLimit(name),io);}}
  finally{stream.closeSync();}
  assert.ok(count>=2,'RANKING_CURRENT_BODY_AND_RECEIPT_REQUIRED');return result;
}
function checkedRankingSources(codeRoot,source,run=cp.execFileSync) {
  assert.match(source,/^[a-f0-9]{40}$/);const sources={};
  for(const name of ['weekly_adaptive_overlay.py','weekly_selected_rankings.py']){
    const bytes=readWeeklyAsset(path.join(codeRoot,'tools',name),1<<20);
    const original=run('git',['--no-lazy-fetch','--no-replace-objects','-c','core.hooksPath=/dev/null','-C',codeRoot,
      'cat-file','blob',source+':tools/'+name],{timeout:10000,maxBuffer:1<<20,stdio:['ignore','pipe','pipe']});
    assert.ok(bytes.equals(original),'RANKING_ACTUAL_IMMUTABLE_HELPER_SOURCE');
    sources[name]={sha256:sha(bytes)};
  }
  return sources;
}
function validateRankingArtifact(directory,members,source,sources,expectedBoard,expectedOverlay,run=cp.execFileSync) {
  // The actual versioned Python validator owns all original membership/proof
  // semantics. Raw bytes preserve canonical float spelling and body identities.
  const program=String.raw`import hashlib,json,os,stat,sys,types
from pathlib import Path
code=Path(sys.argv[1]);pages=Path(sys.argv[2]);request=json.loads(sys.argv[3])
def read(path,cap):
    assert not any(p.is_symlink() for p in (path,*path.parents))
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        first=os.fstat(stream.fileno());assert stat.S_ISREG(first.st_mode) and first.st_size<=cap
        raw=stream.read(cap+1);last=os.fstat(stream.fileno());current=path.lstat()
        identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        assert len(raw)<=cap and len(raw)==first.st_size and identity(first)==identity(last)==identity(current)
    return raw
for name in ('weekly_adaptive_overlay.py','weekly_selected_rankings.py'):
    item=request['sources'][name];raw=read(code/'tools'/name,1<<20)
    assert hashlib.sha256(raw).hexdigest()==item['sha256']
    module=types.ModuleType(name[:-3]);module.__file__=str(code/'tools'/name)
    sys.modules[name[:-3]]=module;exec(compile(raw,module.__file__,'exec'),module.__dict__)
rank=sys.modules['weekly_selected_rankings'];overlay=sys.modules['weekly_adaptive_overlay']
files={'data/weekly-selected-rankings.json':read(pages/'data/weekly-selected-rankings.json',4096)}
folder=pages/'data/weekly-selected-rankings';assert folder.is_dir() and not folder.is_symlink()
with os.scandir(folder) as entries:
    for entry in entries:
        assert len(files)<51 and entry.is_file(follow_symlinks=False)
        name='data/weekly-selected-rankings/'+entry.name;role=rank.public_role(name);assert role is not None
        files[name]=read(pages/name,role[1])
board_body=read(pages/'data/week.json',16*1024**2)
assert hashlib.sha256(board_body).hexdigest()==request['board_sha256']
pointer=json.loads(read(pages/'data/weekly-adaptive-overlay.json',4096))
assert pointer['sha256']==request['overlay_sha256'] and pointer['path']=='data/weekly-adaptive/'+pointer['sha256']+'.json'
selected_body=read(pages/pointer['path'],4*1024**2)
assert len(selected_body)==pointer['bytes'] and hashlib.sha256(selected_body).hexdigest()==pointer['sha256']
board=json.loads(board_body);selected=json.loads(selected_body)
required=rank.validate_public_graph(files,board,hashlib.sha256(board_body).hexdigest(),selected,website_source_sha=request['source'])
assert set(files)==set(required)
pointer=json.loads(files['data/weekly-selected-rankings.json']);doc=json.loads(files['data/'+pointer['path']])
print(json.dumps(dict(required=sorted(required),source=doc['website_source_sha'],body_sha256=pointer['sha256'],
    picks={side:len(items) for side,items in doc['picks'].items()},frozen_proofs=len(doc['frozen_proofs']),
    bytes=sum(map(len,files.values())),members={name:dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for name,raw in files.items()},
    qualified_accuracy_claim=False),sort_keys=True))`;
  const request=JSON.stringify({source,sources,board_sha256:expectedBoard,overlay_sha256:expectedOverlay});
  assert.ok(Buffer.byteLength(request)<=4096,'RANKING_VALIDATION_BINDING_BOUND');
  const bytes=run('python',['-I','-B','-c',program,path.resolve(__dirname,'..'),directory,request],
    {timeout:30000,maxBuffer:65536,stdio:['ignore','pipe','pipe']});
  const value=JSON.parse(bytes);assert.ok(Array.isArray(value.required)&&value.required.length<=51);
  assert.equal(value.source,source);assert.deepEqual(value.required,Object.keys(members).sort());
  for(const [name,raw]of Object.entries(members))assert.deepEqual(value.members[name],{bytes:raw.length,sha256:sha(raw)},'RANKING_DESTINATION_FRESH_BYTE_IDENTITY');
  delete value.members;return value;
}
// END SELECTED RANKING GRAPH CONTRACT
// BEGIN PUBLIC DEPLOYMENT REVIEW CONTRACT
const PUBLIC_SITE='https://nicknicky19.github.io/nicks-expert-nfl-picks/';
function publicDeploymentContract(value,url,actualGeneration,identityBytes,membersDigest) {
  const keys=(v,expected)=>assert.deepEqual(Object.keys(v).sort(),expected.split(' ').sort(),'PUBLIC_REVIEW_CLOSED_KEYS');
  const integer=v=>assert.ok(Number.isSafeInteger(v)&&v>0,'PUBLIC_REVIEW_INTEGER');
  const digest=v=>assert.match(v,/^[0-9a-f]{64}$/,'PUBLIC_REVIEW_DIGEST');
  const commit=v=>assert.match(v,/^[0-9a-f]{40}$/,'PUBLIC_REVIEW_COMMIT');
  assert.equal(url,PUBLIC_SITE,'PUBLIC_REVIEW_CANONICAL_SITE');
  keys(value,'schema_version status source installed_source installed_source_manifest_sha256 runtime_data_commit runtime_data_tree hourly source_ci artifact pages generation expected_site_url');
  assert.equal(value.schema_version,'public-deployment-review-v1');
  assert.equal(value.status,'AUTHENTICATED_HOURLY_PAGES_DEPLOYMENT');
  assert.equal(value.expected_site_url,PUBLIC_SITE);
  for(const key of ['source','installed_source','runtime_data_commit','runtime_data_tree'])commit(value[key]);
  digest(value.installed_source_manifest_sha256);
  keys(value.hourly,'run_id run_attempt head_sha event job_id workflow_path');
  for(const key of ['run_id','run_attempt','job_id'])integer(value.hourly[key]);
  commit(value.hourly.head_sha);assert.ok(['push','schedule','workflow_dispatch'].includes(value.hourly.event));
  assert.equal(value.hourly.workflow_path,'.github/workflows/hourly.yml');
  keys(value.source_ci,'schema_version executed_commit executed_tree source_manifest_sha256 source_ci_commit run_id run_attempt job_id seal_sha256 environment_sha256 claim');
  assert.equal(value.source_ci.schema_version,'source-ci-verification-v1');
  assert.equal(value.source_ci.claim,'COMPLETE_SOURCE_CHECKS_ONLY_NOT_GENERATION_OR_OPERATING_QUALIFICATION');
  assert.equal(value.source_ci.executed_commit,value.runtime_data_commit);
  assert.equal(value.source_ci.executed_tree,value.runtime_data_tree);
  assert.equal(value.source_ci.source_manifest_sha256,value.installed_source_manifest_sha256);
  commit(value.source_ci.source_ci_commit);
  for(const key of ['run_id','run_attempt','job_id'])integer(value.source_ci[key]);
  for(const key of ['source_manifest_sha256','seal_sha256','environment_sha256'])digest(value.source_ci[key]);
  keys(value.artifact,'id name zip_bytes zip_sha256 tar_bytes tar_sha256');
  assert.equal(value.artifact.name,'github-pages');
  for(const key of ['id','zip_bytes','tar_bytes'])integer(value.artifact[key]);
  assert.ok(value.artifact.zip_bytes<=128*1024**2&&value.artifact.tar_bytes<=127*1024**2);
  for(const key of ['zip_sha256','tar_sha256'])digest(value.artifact[key]);
  keys(value.pages,'members_sha256 release_identity_sha256 generation_sha256');
  for(const key of ['members_sha256','release_identity_sha256','generation_sha256'])digest(value.pages[key]);
  assert.equal(value.pages.members_sha256,membersDigest,'PUBLIC_REVIEW_ACTUAL_PAGES_MEMBERS');
  assert.equal(value.pages.release_identity_sha256,sha(identityBytes));
  assert.equal(value.pages.generation_sha256,actualGeneration.generation_sha256);
  assert.equal(value.source,actualGeneration.source_sha);
  assert.deepEqual(value.generation,actualGeneration,'PUBLIC_REVIEW_ACTUAL_GENERATION');
}
function publicMembersDigest(directory) {
  const members={},pending=[directory];let total=0;
  while(pending.length){const parent=pending.pop();for(const name of fs.readdirSync(parent)){const file=path.join(parent,name),info=fs.lstatSync(file);assert.ok(!info.isSymbolicLink(),'PUBLIC_REVIEW_SYMLINK');if(info.isDirectory()){pending.push(file);continue;}assert.ok(info.isFile(),'PUBLIC_REVIEW_FILE');const key=path.relative(directory,file).split(path.sep).join('/');total+=info.size;assert.ok(Object.keys(members).length<20000&&total<=900000000,'PUBLIC_REVIEW_MEMBERS_BOUND');members[key]={bytes:info.size,sha256:sha(fs.readFileSync(file))};}}
  assert.ok(Object.keys(members).length);return sha(Buffer.from(canonical(members)));
}
// END PUBLIC DEPLOYMENT REVIEW CONTRACT
browserPhase='B007';
const marker = readJSON(markerPath);
const deploymentReview=marker.schema_version==='public-deployment-review-v1';
if(!deploymentReview){
assert.equal(marker.schema_version,'genuine-current-production-case-v1');
assert.equal(marker.status,'COMPLETE_GENUINE_NONDEPLOY_CASE','Actual complete case required');
assert.equal(marker.provider_case_attempts,1);assert.equal(marker.deployed,false);assert.equal(marker.main_written,false);
}
assert.ok(fs.statSync(root).isDirectory(), 'Actual fresh staged root is required');
fs.mkdirSync(evidence,{recursive:true});
fs.mkdirSync(profileRoot,{mode:0o700});process.env.TMPDIR=profileRoot;process.env.TMP=profileRoot;process.env.TEMP=profileRoot;
filesystemGuard(criticalPaths,12*1024*1024);
browserPhase='B008';
const generationBytes = fs.readFileSync(path.join(root, 'data/release-identity.json'));
const generation = JSON.parse(generationBytes);
if(deploymentReview)publicDeploymentContract(marker,publicURL,generation,generationBytes,publicMembersDigest(root));
const pointer = readJSON(path.join(root, 'data/selection-grading/latest.json'));
const board = readJSON(path.join(root, 'data/week.json'));
const appHash = sha(fs.readFileSync(path.join(root, 'app.js')));
assert.equal(generation.bindings['app.js'], appHash, 'Actual staged app is generation-bound');
assert.equal(generation.selection_report_id, pointer.report_id, 'Actual pointer is generation-bound');
assert.equal(generation.source_sha, marker.source, 'Capture source is actual successful attempt source');
assert.deepEqual(generation,marker.generation,'Identity is the actual case generation');
assert.equal(sha(fs.readFileSync(path.join(root,'data/selection-grading/latest.json'))),generation.bindings['data/selection-grading/latest.json']);
assert.equal(sha(fs.readFileSync(path.join(root,'data/week.json'))),generation.bindings['data/week.json']);
const weeklyScript=readWeeklyAsset(path.join(root,'weekly-adaptive-overlay.js'),1<<20);
assert.equal(sha(weeklyScript),WEEKLY_HELPER_SHA256,'Actual reviewed weekly helper');
assert.match(fs.readFileSync(path.join(root,'index.html'),'utf8'),/src=["']weekly-adaptive-overlay\.js(?:\?[^"']*)?["']/,'Weekly helper is included in actual shell');
const weeklyPointerBytes=readWeeklyAsset(path.join(root,'data/weekly-adaptive-overlay.json'),4096);
assert.ok(weeklyPointerBytes.length<=4096,'Bounded actual weekly pointer');
const weeklyPointer=JSON.parse(weeklyPointerBytes);
assert.match(weeklyPointer.sha256||'',/^[a-f0-9]{64}$/);assert.equal(weeklyPointer.path,'data/weekly-adaptive/'+weeklyPointer.sha256+'.json');
const weeklyBodyPath=path.join(root,weeklyPointer.path),weeklyModule={exports:{}};
// Execute exactly the reviewed bytes already read and hashed, never a second
// mutable pathname read. The validation realm has no filesystem/network APIs.
vm.runInNewContext(weeklyScript.toString('utf8'),{module:weeklyModule},{timeout:2000});
const weeklySaved=weeklyDisplayGraph(weeklyPointer,readWeeklyAsset(weeklyBodyPath,4*1024*1024),board,
  generation.bindings['data/week.json'],generation.source_sha,weeklyModule.exports);
const rankingMembers=rankingArtifactMembers(root),rankingPointerBytes=rankingMembers['data/weekly-selected-rankings.json'];
const rankingPointer=JSON.parse(rankingPointerBytes),rankingBodyBytes=rankingMembers['data/'+rankingPointer.path];
const rankingSaved=JSON.parse(rankingBodyBytes);
const rankingGraph=validateRankingArtifact(root,rankingMembers,generation.source_sha,
  checkedRankingSources(path.resolve(__dirname,'..'),generation.source_sha),generation.bindings['data/week.json'],weeklyPointer.sha256);
const result = {
  schema_version: 'actual-staged-release-browser-acceptance-v1', status: 'RUNNING',
  started_at: new Date(browserReviewStartedAt).toISOString(), source: marker.source,
  pre_browser_validation_seconds:(Date.now()-browserReviewStartedAt)/1000,
  app_sha256: appHash, generation_sha256: generation.generation_sha256,
  release_identity_file_sha256: sha(generationBytes), report_id: pointer.report_id,
  board_period: [board.season, board.week], original_board_generated_at: board.generated_at,
  weekly_display: {pointer_sha256:sha(weeklyPointerBytes),body_sha256:weeklyPointer.sha256,
    helper_sha256:sha(weeklyScript),website_source_sha:weeklySaved.doc.website_source_sha,
    state:weeklySaved.doc.state,rows:weeklySaved.doc.rows.length,qualified_accuracy_claim:false},
  selected_rankings:{...rankingGraph,pointer_sha256:sha(rankingPointerBytes),qualified_reference_strategy_claim:false},
  contexts: [], checks: [], limitations: [
    'Local Chromium, not physical iPhone/Safari or deployed public acceptance.',
    'External requests are intercepted; zero provider requests are permitted.',
    'Route interception disables HTTP cache; reload coherence/persistence is exercised, not HTTP-cache timing.',
    'Actual future outcomes/corrections are not fabricated. Future result/correction controls remain separately identified software evidence.',
    'Private test selections are created now in isolated profiles, not owner records or authenticated historical decisions.'
  ]
};
result.target=publicURL?{kind:'ACTUAL_PUBLIC_URL',url:publicURL}:{kind:'ACTUAL_STAGED_BYTES',root};
result.diagnostic_source=process.env.GITHUB_SHA||null;result.instrumentation_sha256=sha(fs.readFileSync(__filename));
result.manifest_sha256=sha(fs.readFileSync(markerPath));result.unavailable=[];
if(deploymentReview){result.review_contract='public-deployment-review-v1';result.runtime_data_commit=marker.runtime_data_commit;result.hourly_run_id=marker.hourly.run_id;}
result.filesystems=initialFilesystems;result.resource_verdict='UNKNOWN';result.job_aggregate_peak_bytes=null;
result.limitations=['Actual artifact/public data only; no clocks, responses or outcomes fabricated.','Private choices created now in isolated contexts; no historical pregame ticket claim.','CDP/host resolver block external requests; no Playwright routing. Controlled missing-asset denial is explicitly identified.','Real-data rule calls do not establish a natural future correction transition or physical Safari.','Recorded strategy/cohort differs from display sort; unsupported historical populations stay unavailable.'];
const save = () => {const bytes=JSON.stringify(result,null,2)+'\n';assert.ok(Buffer.byteLength(bytes)<=128*1024,'Bounded result');fs.writeFileSync(arg('--result')||path.join(evidence,'RESULT.json'),bytes);};
const checks = result.checks;
function check(value, label) { assert.ok(value, label); checks.push(label); save(); }
const served = new Map(), requests = [];
let faultPath = null;
const server = http.createServer((req, res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405); res.end(); return; }
    if (pathname === faultPath) { res.writeHead(404, { 'Cache-Control': 'no-store' }); res.end('Controlled missing saved outcome asset'); return; }
    const filename = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
    const resolved = fs.realpathSync(filename);
    if (!resolved.startsWith(root + path.sep) || fs.lstatSync(filename).isSymbolicLink() || !fs.statSync(filename).isFile()) throw Error('Unsafe static path');
    const bytes = fs.readFileSync(filename);
    const old = served.get(filename);
    if (old && old !== sha(bytes)) throw Error('Actual package changed during browser review');
    served.set(filename, sha(bytes));
    const mime = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon' }[path.extname(filename)] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': mime, 'Cache-Control': pathname.endsWith('latest.json') || pathname.endsWith('meta.json') ? 'no-store' : 'public, max-age=600' });
    requests.push({ path: pathname, bytes: bytes.length });
    res.end(req.method === 'HEAD' ? undefined : bytes);
  } catch { res.writeHead(404); res.end('Unavailable static asset'); }
});
let browser;
const hardStop = setTimeout(() => { reportBrowserFailure(null,'BROWSER_DEADLINE');result.status = 'FAIL'; result.error = 'Bounded 420-second browser review exhausted'; save(); if (browser) browser.close().finally(() => process.exit(2)); else process.exit(2); }, Math.max(1,420000-(Date.now()-browserReviewStartedAt)));
const pageState = page => page.evaluate(() => ({ report_id: S.grading?.pointer.report_id, source: S.grading?.summary.source_sha,
  schema: S.grading?.summary.schema_version, report_schema: S.grading?.summary.report_schema_version,
  error: S.gradingError, part_error: S.grading?.partError, filters: { ...S.gradingFilters } }));
const records = page => page.evaluate(() => Object.fromEntries(Object.keys(localStorage).sort().map(key => [key, localStorage.getItem(key)])));
async function loaded(page) {
  await page.waitForFunction(() => S.data && (S.grading || S.gradingError) && !S.grading?.partLoading, null, { timeout: 45000 });
  const state = await pageState(page);
  assert.equal(state.error, null, 'Actual saved publication must load: ' + JSON.stringify(state));
  assert.equal(state.part_error, null, 'Actual selected summary must load');
  assert.equal(state.report_id, pointer.report_id, 'Browser must retain actual generation report');
  return state;
}
async function weeklyDisplay(page,network) {
  await page.waitForFunction(() => S.weeklyOverlayReady&&S.weeklyOverlayRequestBoard===S.data&&S.weeklyOverlay!==null,null,{timeout:10000});
  const before=await records(page);
  const value=await page.evaluate(expected=>{
    const overlay=S.weeklyOverlay;
    if(overlay.boardHash!==expected.board_hash||overlay.state!==expected.state)throw Error('Weekly displayed board/state mismatch');
    const rows=[...overlay.rows.values()];
    const examples=[];const seen=new Set();
    for(const row of rows){
      const player=S.byId[row.player_id],prop=player?.props.find(p=>p.key===row.category);
      if(!player||!prop)throw Error('Weekly selected identity absent from actual reference');
      const selected=selectedPropForecast(player,row.category);
      if(!selected||seen.has(row.product))continue;
      if(selected.value!==row.forecast_value)throw Error('Weekly typed selected value changed');
      const template=document.createElement('template');template.innerHTML=catCard(player,prop);
      const primary=template.content.querySelector('[data-weekly-primary]');
      if(!primary||!primary.textContent.includes(selected.text))throw Error('Weekly primary caption/value mismatch');
      const text=template.content.textContent;
      const knownReference=row.product==='binary_probability'||pv(player,prop).adj!=null;
      if(!/provisional/i.test(primary.textContent)||(knownReference&&!/Current reference (forecast|probability)/.test(text))||!text.includes('accuracy is still being evaluated')
          ||(row.product!=='binary_probability'&&!text.includes('Top Picks use saved sportsbook lines')))throw Error('Weekly/reference captions conflated');
      examples.push({product:row.product,category:row.category,value:selected.value,frozen:selected.frozen,
        reference_status:knownReference?'KNOWN_SHOWN':'UNAVAILABLE_REFERENCE_FORECAST'});seen.add(row.product);
    }
    return {rows,examples,board:JSON.stringify(S.data),report_id:S.grading.pointer.report_id,
      visible_primary_cells:document.querySelectorAll('[data-weekly-primary]').length};
  },{board_hash:generation.bindings['data/week.json'],state:weeklySaved.doc.state});
  assert.deepEqual(value.rows,weeklySaved.doc.rows,'Browser consumes exact saved selected rows');
  assert.equal(value.report_id,pointer.report_id);assert.deepEqual(await records(page),before);
  assert.ok(network.some(r=>r.path==='data/weekly-adaptive-overlay.json'&&r.status===200),'Actual optional pointer request');
  assert.ok(network.some(r=>r.path===weeklySaved.pointer.path&&r.status===200),'Actual required overlay body request');
  assert.ok(network.some(r=>r.path.split('?')[0]==='weekly-adaptive-overlay.js'&&r.status===200),'Actual helper script request');
  return {state:weeklySaved.doc.state,rows:value.rows.length,typed_caption_examples:value.examples,
    visible_primary_cells:value.visible_primary_cells,
    selected_feed_coverage:weeklySaved.doc.rows.length?'ACTUAL_SAVED_PROVISIONAL_ROWS':'UNAVAILABLE_NO_ACCEPTED_SELECTED_ROWS',
    reference_board_and_storage_unchanged:true,provisional_rows_used_as_qualified_accuracy:false};
}
async function selectedRankingDisplay(page,network) {
  await page.waitForFunction(()=>S.selectedRankings!==null,null,{timeout:12000});
  const value=await page.evaluate(()=>({doc:S.selectedRankings,
    board:JSON.stringify(S.data),reference_picks:JSON.stringify(S.data.picks),
    record_caption:document.querySelector('#main')?.textContent||'',
    rows:[...visibleTopPicks('over'),...visibleTopPicks('under')].length}));
  assert.deepEqual(value.doc,rankingSaved,'Actual complete saved selected ranking document');
  assert.match(value.record_caption,/not a track record for the separate provisional selected-forecast Top Picks/i);
  const before=await records(page);await tab(page,'props');
  const visible=await page.evaluate(()=>{
    const over=visibleTopPicks('over'),under=visibleTopPicks('under');
    for(const item of [...over,...under]){
      const html=pickCard(item),template=document.createElement('template');template.innerHTML=html;
      const label=item.forecast_source==='SELECTED'?'Selected':item.forecast_source==='R0_FALLBACK'?'Reference fallback':'Current reference';
      if(!template.content.textContent.includes(label))throw Error('Selected Top source caption mismatch');
      const add=template.content.querySelector('[data-add]');
      if(!add||add.dataset.add!==[item.player_id,item.key,item.direction,item.line].join('|'))throw Error('Selected Top exact saved line');
    }
    return {over,under,board:JSON.stringify(S.data),reference_picks:JSON.stringify(S.data.picks),sort:S.f.sort};
  });
  assert.equal(visible.board,value.board);assert.equal(visible.reference_picks,value.reference_picks);
  assert.deepEqual(await records(page),before);
  assert.ok(network.some(r=>r.path==='data/weekly-selected-rankings.json'&&r.status===200));
  assert.ok(network.some(r=>r.path==='data/'+rankingPointer.path&&r.status===200));
  for(const name of rankingGraph.required.filter(n=>n.endsWith('.receipt.json')))assert.ok(!network.some(r=>r.path===name),'Proof dependencies are verified offline without eager browser downloads');
  await tab(page,'record');await loaded(page);
  return {visible_picks:{over:visible.over.length,under:visible.under.length},complete_proofs_verified:rankingGraph.frozen_proofs,
    saved_stream_picks:rankingGraph.picks,reference_board_and_picks_unchanged:true,qualified_reference_history_or_accuracy:false};
}
async function missingSelectedRankings(page,cdp,blockedURLs,base) {
  const before=await records(page),hash=await page.evaluate(()=>gradingHash(new TextEncoder().encode(JSON.stringify(S.data))));
  try{
    await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});faultPath='/data/weekly-selected-rankings.json';
    await cdp.send('Network.setBlockedURLs',{urls:[...blockedURLs,new URL('data/weekly-selected-rankings.json',base).href]});
    await page.reload();await loaded(page);await page.waitForFunction(()=>S.weeklyOverlay!==null,null,{timeout:10000});await tab(page,'props');
    await page.evaluate(()=>startSelectedRankings(S.data,S.weeklyOverlay,WeeklyAdaptiveOverlay));
    const value=await page.evaluate(()=>({missing:S.selectedRankings===null,
      over:visibleTopPicks('over'),under:visibleTopPicks('under'),original:S.data.picks,report:S.grading.pointer.report_id}));
    assert.equal(value.missing,true);assert.deepEqual(value.over,value.original.over);assert.deepEqual(value.under,value.original.under);
    assert.equal(value.report,pointer.report_id);assert.equal(await page.evaluate(()=>gradingHash(new TextEncoder().encode(JSON.stringify(S.data)))),hash);
    assert.deepEqual(await records(page),before);
  }finally{faultPath=null;await cdp.send('Network.setBlockedURLs',{urls:blockedURLs});await cdp.send('Network.setCacheDisabled',{cacheDisabled:false});}
  await page.reload();await loaded(page);await page.waitForFunction(()=>S.selectedRankings!==null,null,{timeout:12000});
  assert.deepEqual(await records(page),before);
  return {status:'PASS_CONTROLLED_RANKING_DENIAL_EXPLICIT_REFERENCE_TOP_FALLBACK_AND_RECOVERY',qualified_accuracy_claim:false};
}
async function missingWeeklyDisplay(page,cdp,blockedURLs,base) {
  const before=await records(page),boardHash=await page.evaluate(()=>gradingHash(new TextEncoder().encode(JSON.stringify(S.data))));
  try{
    await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});faultPath='/data/weekly-adaptive-overlay.json';
    await cdp.send('Network.setBlockedURLs',{urls:[...blockedURLs,new URL('data/weekly-adaptive-overlay.json',base).href]});
    await page.reload();await loaded(page);await tab(page,'props');
    const result=await page.evaluate(async()=>{
      const missing=await WeeklyAdaptiveOverlay.load(S.data,S.weeklyOverlayBoardHash);
      const bad={schema_version:'weekly-adaptive-overlay-pointer-v1',path:'data/weekly-adaptive/'+'0'.repeat(64)+'.json',sha256:'0'.repeat(64),bytes:1,display_board_sha256:'0'.repeat(64)};
      const rejected=await WeeklyAdaptiveOverlay.load(S.data,S.weeklyOverlayBoardHash,async()=>new Response(JSON.stringify(bad)));
      return {missing:missing===null,rejected:rejected===null,active:S.weeklyOverlay===null,
        primary_cells:document.querySelectorAll('[data-weekly-primary]').length,report:S.grading.pointer.report_id};
    });
    assert.deepEqual(result,{missing:true,rejected:true,active:true,primary_cells:0,report:pointer.report_id});
    assert.equal(await page.evaluate(()=>gradingHash(new TextEncoder().encode(JSON.stringify(S.data)))),boardHash);
    assert.deepEqual(await records(page),before);
  }finally{faultPath=null;await cdp.send('Network.setBlockedURLs',{urls:blockedURLs});await cdp.send('Network.setCacheDisabled',{cacheDisabled:false});}
  await page.reload();await loaded(page);await page.waitForFunction(()=>S.weeklyOverlay!==null,null,{timeout:10000});
  assert.deepEqual(await records(page),before);
  return {status:'PASS_CONTROLLED_MISSING_AND_REJECTED_OPTIONAL_GRAPH_REFERENCE_FALLBACK_AND_RECOVERY',
    scope:'Actual missing-asset/CDP denial and separately identified wrong-board response control; not an observed public outage'};
}
async function tab(page, name) {
  await page.locator('[data-tab="' + name + '"]').first().click();
  await page.waitForFunction(value => S.tab === value, name);
}
async function assertNoOverflow(page, width) {
  const actual = await page.evaluate(() => document.documentElement.scrollWidth);
  assert.ok(actual <= width + 1, 'Viewport overflow: ' + actual + ' at ' + width);
}
async function semanticRows(page) {
  return page.evaluate(async expected => {
    const grading = S.grading, rows = [];
    if(grading.pointer.row_count!==expected.count||grading.pointer.rows.length!==expected.chunks||grading.pointer.row_count>1000000||grading.pointer.rows.length>4000)throw Error('Actual manifest-bound pointer population/bound changed');
    for (const descriptor of grading.pointer.rows) {
      const chunk = await checkedGradingAsset(grading.pointer, descriptor, 'rows');
      if (!Array.isArray(chunk.rows) || chunk.rows.length !== descriptor.count) throw Error('Actual row chunk count mismatch');
      chunk.rows.forEach(row => validateGradingRowContract(row, grading.index?.schema_version || grading.summary.schema_version));
      rows.push(...chunk.rows);
    }
    if (rows.length !== grading.pointer.row_count || new Set(rows.map(r => r.decision_sha256)).size !== rows.length) throw Error('Complete saved row identity/count mismatch');
    const fields=['provenance_class','model_version','engine_sha256','policy_version','policy_sha256','view','checkpoint','line_source_scope'];
    const dimensions=['category','side','venue','selection_weekday','kickoff_weekday','lead_time_bucket','checkpoint','selection_clock_basis','category_side','category_side_selection_kickoff_lead'];
    const expectedGroups=new Map(),key=(context,period,dimension,value)=>JSON.stringify([fields.map(k=>context[k]??null),period,dimension,value]);
    rows.forEach((r,i)=>{
      const views=[r.cohort];if(r.cohort==='all_qualifying_leans'&&r.action==='SELECT')views.push(r.top_at_decision?'top_at_all_lean_decision':'non_top_at_all_lean_decision');
      for(const view of views)for(const period of ['cumulative',r.season+'-w'+String(r.week).padStart(2,'0')])for(const source of ['all',r.line_from||'unknown']){
        const context={...r,view,line_source_scope:source},add=(d,v)=>{const k=key(context,period,d,v);if(!expectedGroups.has(k))expectedGroups.set(k,[]);expectedGroups.get(k).push(i);};
        add('overall','all');for(const d of dimensions)add(d,d==='venue'?r.line_from:d==='category_side'?r.category+':'+r.side:d==='category_side_selection_kickoff_lead'?JSON.stringify(['category','side','selection_weekday','kickoff_weekday','lead_time_bucket'].map(k=>r[k]??null)):r[d]??null);
      }
    });
    let groups=0;const groupIds=new Set();
    for(const descriptor of grading.index.summary_partitions){
      const part=await checkedGradingAsset(grading.pointer,descriptor,'summary',true);
      if(part.tables.length!==descriptor.table_count)throw Error('Exact full summary part count');
      validateGradingTables(grading.pointer,part.tables,grading.index.schema_version);
      for(const table of part.tables){
        if(groupIds.has(table.summary_id))throw Error('Duplicate complete summary group');groupIds.add(table.summary_id);
        if(table.period!==descriptor.period||fields.some(k=>table[k]!==grading.index.contexts[descriptor.context_id][k]))throw Error('Complete context binding');
        const k=key(table,table.period,table.dimension,table.value),positions=expectedGroups.get(k);
        if(!positions||JSON.stringify(positions)!==JSON.stringify(table.row_positions))throw Error('Exact independently derived context/joint membership');
        expectedGroups.delete(k);const actual=positions.map(i=>rows[i]);
        const counts=Object.fromEntries(GRADING_RESULTS.map(status=>[status,actual.filter(r=>r.result===status).length]));
        if(actual.length!==table.rows||GRADING_RESULTS.some(status=>counts[status]!==table[status])||table.decided!==counts.win+counts.loss)throw Error('Complete independent saved-row tally');
        if(await gradingHash(new TextEncoder().encode(JSON.stringify(actual.map(r=>r.decision_sha256))))!==table.row_ids_sha256)throw Error('Complete membership digest');groups++;
      }
    }
    if(expectedGroups.size)throw Error('Missing complete summary groups');
    let outcomes=0;const statuses={};for(const period of grading.outcomeIndex.periods){const values=await loadOutcomePeriod(grading,period.season,period.week);if(values.size!==period.count)throw Error('Complete outcome period count');for(const row of values.values())statuses[row.status]=(statuses[row.status]||0)+1;outcomes+=values.size;}
    if(outcomes!==grading.outcomeIndex.outcome_count)throw Error('Complete outcome population');
    return {complete_saved_rows:rows.length,complete_saved_row_identity_digest:await gradingHash(new TextEncoder().encode(JSON.stringify(rows.map(r=>r.decision_sha256)))),complete_context_groups_reconciled:groups,outcomes,outcome_statuses:statuses,partial_page_used_as_population:false};
  },{count:pointer.row_count,chunks:pointer.rows.length});
}
async function checkDisplayedCells(page) {
  const values = await page.locator('[data-performance-cell]').evaluateAll(nodes => nodes.map(node => {
    const t = S.grading.summary.summary.tables.find(row => row.summary_id === node.dataset.summaryId);
    return { id: node.dataset.summaryId, text: node.textContent, exists: !!t, win: t?.win, loss: t?.loss, decided: t?.decided };
  }));
  check(values.length > 0, 'Actual performance cells are rendered');
  for (const value of values) {
    assert.ok(value.exists && value.text.includes(value.win + '–' + value.loss) && value.text.includes(value.decided + ' decided'), 'Actual displayed W/L/denominator mismatch');
  }
  return values.length;
}
async function drillDown(page) {
  const visible = await page.locator('[data-grading-group]:visible').evaluateAll(nodes => nodes.map(node => node.dataset.gradingGroup));
  const choice = await page.evaluate(ids => selectedGradingTables().baseTables.filter(t => ids.includes(t.summary_id) && t.rows > 0 && t.rows <= 500 &&
    (S.gradingFilters.dimension === 'category_side_selection_kickoff_lead' ? t.dimension === S.gradingFilters.dimension : ['category', 'category_side', 'overall'].includes(t.dimension)))
    .sort((a,b) => a.rows-b.rows)[0]?.summary_id || null, visible);
  assert.ok(choice, 'Actual nonempty bounded supporting group must exist');
  await page.locator('[data-grading-group="' + choice + '"]:visible').first().click();
  for (let n = 0; n < 25; n++) {
    await page.waitForFunction(() => S.gradingGroup && !S.gradingGroup.loading);
    const group = await page.evaluate(() => ({ complete: S.gradingGroup.complete, error: S.gradingGroup.error }));
    assert.equal(group.error, undefined, 'Actual drill-down must reconcile');
    if (group.complete) break;
    await page.locator('[data-grading-more]').click();
  }
  const reconciled = await page.evaluate(() => {
    const group = S.gradingGroup, table = S.grading.summary.summary.tables.find(t => t.summary_id === group.id);
    const joint = table.dimension === 'category_side_selection_kickoff_lead' ? JSON.parse(table.value) : null;
    return { complete: group.complete, rows: group.rows.length, expected: table.rows, dimension:table.dimension,
      joint_membership_matches:joint === null ? null : group.rows.every(row => JSON.stringify(['category','side','selection_weekday','kickoff_weekday','lead_time_bucket'].map(k=>row[k] ?? null)) === JSON.stringify(joint)),
      unique: new Set(group.rows.map(r => r.decision_sha256)).size,
      counts: Object.fromEntries(GRADING_RESULTS.map(s => [s, group.rows.filter(r => r.result === s).length])), expected_counts: Object.fromEntries(GRADING_RESULTS.map(s => [s, table[s]])) };
  });
  assert.ok(reconciled.complete); assert.equal(reconciled.rows, reconciled.expected); assert.equal(reconciled.unique, reconciled.rows); assert.deepEqual(reconciled.counts, reconciled.expected_counts);
  if (reconciled.joint_membership_matches !== null) assert.equal(reconciled.joint_membership_matches,true,'Exact joint group must use its actual saved row fields');
  return reconciled;
}
async function actualFilterCoverage(page) {
  const output=[];
  const current=String(board.season)+'-w'+String(board.week).padStart(2,'0');
  for(const [field,value] of [['model_version','sleeper-matchup-data-integrity-v2'],['period',current],['line_source_scope','dk'],['view','top_picks'],['dimension','category_side_selection_kickoff_lead']]) {
    const selector=page.locator('[data-grading-filter="'+field+'"]');
    const available=await selector.locator('option').evaluateAll(nodes=>nodes.map(node=>node.value));
    if(!available.includes(value)){output.push({field,value,status:'UNAVAILABLE_IN_ACTUAL_SAVED_POPULATION',available});continue;}
    await selector.selectOption(value);await loaded(page);
    const state=await pageState(page);assert.equal(state.filters[field],value,'Actual requested context cannot be overwritten by stale selection');
    const item={field,value,status:'ACTUAL_CONTEXT_LOADED',state,displayed_cells:await checkDisplayedCells(page)};
    if(field==='dimension')item.exact_joint_drilldown=await drillDown(page);
    output.push(item);
  }
  await page.reload();await loaded(page);
  return output;
}

async function strategyUI(page){
  const output=[];
  for(const view of ['ranked_biggest_lean_v1','ranked_projected_points_v1']){
    const chosen=await page.evaluate(view=>{
      const g=S.grading;const parts=g.index.summary_partitions.filter(p=>g.index.contexts[p.context_id].view===view);
      parts.sort((a,b)=>Number(b.period==='cumulative')-Number(a.period==='cumulative')||Number(g.index.contexts[b.context_id].line_source_scope==='all')-Number(g.index.contexts[a.context_id].line_source_scope==='all'));
      const p=parts[0];return p?{context_id:p.context_id,period:p.period,values:Object.fromEntries(gradingContextFields.map(f=>[f,gradingContextValue({...g.index.contexts[p.context_id],period:p.period},f)]))}:null;
    },view);
    if(!chosen){output.push({view,status:'UNAVAILABLE_ACTUAL_RECORDED_STRATEGY'});continue;}
    for(const [field,value]of Object.entries(chosen.values)){await page.locator('[data-grading-filter="'+field+'"]').selectOption(value);await loaded(page);}
    const dimension=page.locator('[data-grading-filter=dimension]'),options=await dimension.locator('option').evaluateAll(v=>v.map(n=>n.value));
    await dimension.selectOption(options.includes('category_side_selection_kickoff_lead')?'category_side_selection_kickoff_lead':'category');await loaded(page);
    assert.equal((await pageState(page)).filters.view,view);
    const displayed=await checkDisplayedCells(page),supporting=await drillDown(page);
    assert.ok(await page.evaluate(view=>S.gradingGroup.rows.every(r=>r.cohort===view),view),'Exact recorded strategy membership');
    assert.ok(await page.evaluate(values=>S.grading.summary.summary.tables.every(t=>Object.entries(values).every(([k,v])=>gradingContextValue(t,k)===v)),chosen.values),'Exact recorded context');
    output.push({view,...chosen,displayed,supporting,status:'PASS_ACTUAL_STRATEGY_UI'});
  }return output;
}

function compatible(legs,size,mixed=false){
  const extend=seed=>{const chosen=[...seed];if(chosen.length===size)return chosen;for(const leg of legs)if(!chosen.some(v=>v.player_id===leg.player_id||v.game_id===leg.game_id)){chosen.push(leg);if(chosen.length===size)break;}return chosen.length===size?chosen:[];};
  if(!mixed)return extend([]);
  for(const a of legs)for(const b of legs)if(a.side!==b.side&&a.player_id!==b.player_id&&a.game_id!==b.game_id){const choice=extend([a,b]);if(choice.length===size)return choice;}
  return [];
}
async function categoryControls(page){
  await tab(page,'parlay');const storage=records,boardHash=page=>page.evaluate(()=>gradingHash(new TextEncoder().encode(JSON.stringify(S.data))));
  const initialStorage=await storage(page),initialBoard=await boardHash(page);let phase='';result.paper=[];
    phase='paper-controls';const categories=await page.locator('[data-paper-category]').evaluateAll(nodes=>nodes.map(n=>n.dataset.paperCategory));
    assert.deepEqual([...categories].sort(),['pass_yd','pass_td','pass_cmp','pass_att','pass_int','rush_yd','rush_att','rec_yd','rec','rush_rec_yd'].sort());
    await page.locator('[data-paper-filter=size]').selectOption('2');
    for(const source of ['dk','sleeper']){
      await page.locator('[data-paper-filter=source]').selectOption(source);await page.locator('[data-paper-filter=sides]').selectOption('mixed');
      const baseline=await page.evaluate(()=>paperCandidates().map(v=>v.leg));
      for(const category of categories){await page.locator('[data-paper-category="'+category+'"]').check();
        for(const side of ['over','under','mixed']){
          await page.locator('[data-paper-filter=sides]').selectOption(side);
          const actual=await page.evaluate(()=>paperCandidates().map(v=>v.leg));
          const want=baseline.filter(l=>l.category===category&&(side==='mixed'||l.side===side));assert.deepEqual(actual,want,'Exact actual baseline subset '+source+'/'+category+'/'+side);
          await page.locator('[data-paper-suggest]').click();const draft=await page.evaluate(()=>({legs:S.paper.legs,error:S.paper.error}));
          const compatible=[];for(const leg of want){if(!compatible.some(l=>l.player_id===leg.player_id||l.game_id===leg.game_id))compatible.push(leg);if(compatible.length===2)break;}
          assert.deepEqual(draft.legs,compatible,'Suggestion retains exact filtered actual contracts');
          if(draft.legs.length<2)assert.match(draft.error,/NO_ACTION: fewer than two compatible legs/);
          result.paper.push({source,category,side,candidates:actual.length,suggested:draft.legs.length,suggested_sides:[...new Set(draft.legs.map(l=>l.side))],status:actual.length===0?'UNAVAILABLE_ACTUAL_POPULATION':draft.legs.length<2?'UNAVAILABLE_COMPATIBLE_PAIR':'PASS_ACTUAL_CONTROLS'});
        }
        await page.locator('[data-paper-category="'+category+'"]').uncheck();
      }
    }
    assert.deepEqual(await storage(page),initialStorage);assert.equal(await boardHash(page),initialBoard);check(true,'Sixty actual category/source/side controls and suggestions preserve board and storage bytes');
  const cases=result.paper;delete result.paper;return cases;
}
async function paper(page,width){
  await tab(page,'parlay');await page.waitForSelector('[data-paper-suggest]');
  const saved=[],coverage=[];let revision=null;
  for(const side of ['over','under','mixed'])for(const size of [2,3,4,5,6]){
    await page.locator('[data-paper-new]').click();await page.locator('[data-paper-filter=sides]').selectOption(side);await page.locator('[data-paper-filter=size]').selectOption(String(size));
    let chosen=[],source=null;
    for(const candidate of ['dk','sleeper']){
      await page.locator('[data-paper-filter=source]').selectOption(candidate);
      const legs=await page.evaluate(()=>paperCandidates().map(v=>v.leg));
      const pick=compatible(legs,size,side==='mixed');if(pick.length){chosen=pick;source=candidate;break;}
    }
    if(!chosen.length){coverage.push({side,size,status:'UNAVAILABLE_ACTUAL_COMPATIBLE_POPULATION'});continue;}
    for(const leg of chosen){
      const visible=await page.locator('[data-paper-add]').evaluateAll((v,l)=>v.some(b=>b.dataset.paperAdd===JSON.stringify(l)),leg);
      if(!visible){await page.locator('[data-paper-filter=game]').selectOption(leg.game_id);await page.locator('[data-paper-category="'+leg.category+'"]').check();}
      await page.locator('[data-paper-add]').evaluateAll((v,l)=>{const b=v.find(b=>b.dataset.paperAdd===JSON.stringify(l));if(!b)throw Error('Exact actual leg unavailable');b.click();},leg);
      if(!visible){await page.locator('[data-paper-category="'+leg.category+'"]').uncheck();await page.locator('[data-paper-filter=game]').selectOption('');}
    }
    assert.deepEqual(await page.evaluate(()=>S.paper.legs),chosen);if(side==='mixed')assert.equal(new Set(chosen.map(l=>l.side)).size,2);
    await page.locator('[data-paper-save]').click();await page.waitForFunction(()=>S.paper.opened&&S.paper.error==='Saved and read back on this device.'&&S.paper.results);
    const item=await page.evaluate(()=>({key:PAPER_PREFIX+S.paper.opened.ticket_id+'.'+S.paper.opened.revision_id,bytes:localStorage.getItem(PAPER_PREFIX+S.paper.opened.ticket_id+'.'+S.paper.opened.revision_id),ticket:S.paper.opened,results:S.paper.results,state:paperTicketStatus(S.paper.results)}));
    assert.equal(item.ticket.legs.length,size);assert.equal(new Set(item.ticket.legs.map(l=>l.game_id)).size,size);assert.ok(item.ticket.legs.every(l=>Date.parse(l.kickoff)>Date.now()&&l.line_source===source));assert.ok(item.results.every(r=>['pending','unresolved'].includes(r.status)));
    saved.push(item);coverage.push({side,size,source,sides:[...new Set(chosen.map(l=>l.side))],status:'PASS_ACTUAL_SAVED_TICKET'});
  }
  await page.reload();await loaded(page);await page.waitForSelector('[data-paper-suggest]');
  const exact=await records(page);for(const item of saved)assert.equal(exact[item.key],item.bytes);
  const original=saved.find(v=>v.ticket.legs.length===2);
  if(original){
    await page.locator('[data-paper-open]').evaluateAll((buttons,key)=>buttons.find(b=>b.dataset.paperOpen===key).click(),original.key);
    await page.waitForFunction(()=>S.paper.results);
    await page.locator('[data-paper-filter=source]').selectOption(original.ticket.line_source);
    await page.locator('[data-paper-filter=sides]').selectOption(original.ticket.legs.every(l=>l.side===original.ticket.legs[0].side)?original.ticket.legs[0].side:'mixed');
    await page.locator('[data-paper-filter=size]').selectOption('3');await page.locator('[data-paper-suggest]').click();
    if(await page.evaluate(()=>S.paper.legs.length)===3){
      await page.locator('[data-paper-save]').click();await page.waitForFunction(id=>S.paper.opened?.parent_revision_id===id&&S.paper.results,original.ticket.revision_id);
      revision=await page.evaluate(()=>({ticket_id:S.paper.opened.ticket_id,revision_id:S.paper.opened.revision_id,parent:S.paper.opened.parent_revision_id}));assert.equal(revision.ticket_id,original.ticket.ticket_id);assert.equal((await records(page))[original.key],original.bytes);
    }else coverage.push({kind:'revision3',status:'UNAVAILABLE_ACTUAL_COMPATIBLE_TRIPLE'});
  }
  let history=null;
  if(saved.length){
    await page.locator('[data-paper-evaluate]').click();await page.waitForFunction(()=>S.paper.history);
    history=await page.evaluate(()=>({report:S.paper.history.report_id,rows:S.paper.history.rows.map(r=>({size:r.ticket.legs.length,original:r.ticket.parent_revision_id===null,status:r.status,legs:r.legs.map(l=>l.status)})),excluded:S.paper.history.excluded}));
    assert.equal(history.report,pointer.report_id);assert.equal(history.excluded,0);assert.equal(history.rows.length,saved.length+Number(!!revision));
    for(const size of [2,3,4,5,6])assert.equal(history.rows.filter(r=>r.original&&r.size===size).length,saved.filter(v=>v.ticket.legs.length===size).length);
    assert.match(await page.locator('[data-paper-performance]').innerText(),/Financial ROI and venue settlement unavailable/);
  }
  await assertNoOverflow(page,width);
  return {coverage,saved_ticket_count:saved.length,original_ticket_hashes:saved.map(v=>sha(v.bytes)),revision,grouped_history:history,natural_future_correction:'UNAVAILABLE_NOT_FABRICATED'};
}
async function scoringAndRules(page){
  const before=await records(page),mine=before['nflprops.mine'],settings=[];
  for(const value of ['sleeper|half','sleeper|ppr','espn|half','espn|ppr']){
    await page.locator('#sc-btn').click();await page.locator('[data-sc="'+value+'"]').click();
    const state=await page.evaluate(()=>({...S.sc}));assert.equal(state.mode,value.split('|')[0]);assert.equal(state.half,value.endsWith('half'));
    await page.reload();await loaded(page);assert.deepEqual(await page.evaluate(()=>({...S.sc})),state);
    const current=await records(page);for(const [key,bytes]of Object.entries(before))if(key!=='nflprops.scoring')assert.equal(current[key],bytes);
    settings.push(state);
  }
  const rules=await page.evaluate(()=>{
    const cases={};for(const row of S.finalOutcomes.values()){
      const p=S.byId[row.player_id];if(!p||!finalIdentityMatches(row,p,row.category)||S.games[p.game_id]?.state!=='post')continue;
      const kind=row.outcome_conflict?'conflict':row.status==='resolved'&&Number.isInteger(row.actual)?'integer_push':row.status;
      if(!['conflict','integer_push','dnp','pending'].includes(kind)||cases[kind])continue;
      const line=kind==='integer_push'?row.actual:p.props.find(q=>q.key===row.category)?.line;
      if(!Number.isFinite(line))continue;const value=propStatus(p,row.category,line,'over');
      cases[kind]={identity:finalIdentity(p,row.category),row_sha256:row.selected_outcome_row_sha256||null,value,personal_line:line,scope:'RETROSPECTIVE_REAL_OUTCOME_RULE_CALL_NOT_PREGAME_TICKET'};
    }return cases;
  });
  for(const [kind,value]of Object.entries(rules))assert.equal(value.value.res,{integer_push:'push',dnp:'dnp',pending:'pending',conflict:'unresolved'}[kind]);
  assert.equal((await records(page))['nflprops.mine'],mine);
  return {settings,rules,unavailable:['integer_push','dnp','pending','conflict'].filter(k=>!rules[k]),natural_correction_transition:'UNAVAILABLE_REQUIRES_TWO_ACTUAL_GENERATIONS_AND_SAVED_CHOICE'};
}
async function fetched(page, relative, cache='default') {
  return page.evaluate(async ({relative,cache}) => {
    const r=await fetch(relative,{cache}), bytes=new Uint8Array(await r.arrayBuffer());
    if(bytes.length>8*1024*1024)throw Error('Bounded supplemental response exceeded 8 MiB');
    return {status:r.status,bytes:bytes.length,sha256:await gradingHash(bytes),cache_control:r.headers.get('cache-control'),content_encoding:r.headers.get('content-encoding')};
  },{relative,cache});
}
async function ordinaryCache(page,cdp,network){
  const storage=records,boardHash=page=>page.evaluate(()=>gradingHash(new TextEncoder().encode(JSON.stringify(S.data))));
  const initialStorage=await storage(page),initialBoard=await boardHash(page),expected=generation,root=!publicURL;
  const populated=!!JSON.parse(initialStorage['nflprops.mine']||'[]').length&&Object.keys(initialStorage).some(k=>k.startsWith('nflprops.paper-ticket.v1.'));
  const serverCounts={get:relative=>requests.filter(v=>v.path==='/'+relative).length};
  const phaseSummary=(name,start)=>({phase:name,responses:network.slice(start).map(n=>({path:n.path,status:n.status,cache_control:n.cache_control,from_disk:n.cached,from_memory:false}))});
  let phase='';result.cache=[];
    const pointer=await page.evaluate(()=>S.grading.pointer),immutable='data/selection-grading/'+pointer.summary.path;
    const immutableHash=pointer.summary.encoded_sha256||pointer.summary.sha256;
    for(const [relative,expectedHash] of [['app.js',expected.bindings['app.js']],[immutable,immutableHash],['data/'+rankingPointer.path,rankingPointer.sha256]]){
      phase='cache-warm';const first=await fetched(page,relative);assert.equal(first.sha256,expectedHash);
      const serverBefore=serverCounts.get(relative)||0,start=network.length;phase='cache-repeat';const second=await fetched(page,relative);assert.equal(second.sha256,expectedHash);
      await page.waitForTimeout(30);const details=phaseSummary('cache-repeat',start),response=details.responses.find(r=>r.path===relative);
      check(!!response,'Ordinary cache repeat has observed Chromium response');
      const hit=!!(response.from_disk||response.from_memory);if(root){assert.equal(serverCounts.get(relative)||0,serverBefore);check(hit,'Controlled immutable response reused ordinary HTTP cache');}
      result.cache.push({asset:relative,cache_control:second.cache_control,ordinary_cache_hit:hit,server_repeat_reads:root?(serverCounts.get(relative)||0)-serverBefore:null,...details});
    }
    phase='mutable-no-store';let start=network.length;const before=serverCounts.get('data/selection-grading/latest.json')||0;
    for(let n=0;n<2;n++)assert.equal((await fetched(page,'data/selection-grading/latest.json','no-store')).sha256,expected.bindings['data/selection-grading/latest.json']);
    await page.waitForTimeout(30);const mutable=phaseSummary('mutable-no-store',start);check(mutable.responses.length===2&&mutable.responses.every(r=>!r.from_disk&&!r.from_memory),'Mutable pointer no-store reads do not reuse cached responses');
    if(root)assert.equal((serverCounts.get('data/selection-grading/latest.json')||0)-before,2);result.cache.push(mutable);
    phase='ordinary-app-refresh';start=network.length;
    const previousRevision=await page.evaluate(()=>gradingLoadRevision);
    await page.locator('#reload').dispatchEvent('click');
    await page.waitForFunction(previous=>gradingLoadRevision>previous&&S.grading&&!S.grading.partLoading,previousRevision,{timeout:45000});
    await loaded(page);assert.equal(await boardHash(page),initialBoard);assert.deepEqual(await storage(page),initialStorage);result.cache.push(phaseSummary(phase,start));
    phase='ordinary-document-reload';start=network.length;await page.reload({waitUntil:'domcontentloaded'});await loaded(page);assert.equal(await boardHash(page),initialBoard);assert.deepEqual(await storage(page),initialStorage);result.cache.push(phaseSummary(phase,start));
    assert.equal((await fetched(page,'data/release-identity.json','no-store')).sha256,sha(generationBytes),'Generation unchanged after ordinary refresh/reload');
    check(true,'Ordinary refresh and document reload preserve genuine report, board and private storage');
  const cache=result.cache;delete result.cache;
  return {cache,populated_storage:populated,status:populated?'PASS_POPULATED_RELOAD':'UNAVAILABLE_POPULATED_STORAGE'};
}
async function missingPartition(page,cdp,blockedURLs,base){
  const before=await records(page),asset=await page.evaluate(()=>S.grading.outcomeIndex.periods.find(p=>p.season===S.data.season&&p.week===S.data.week)?.path||null);
  if(!asset)return {status:'UNAVAILABLE_ACTUAL_CURRENT_PARTITION'};
  try{
    await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});faultPath='/data/selection-grading/'+asset;
    await cdp.send('Network.setBlockedURLs',{urls:[...blockedURLs,new URL('data/selection-grading/'+asset,base).href]});
    await page.reload();await page.waitForFunction(()=>S.data&&S.gradingError);assert.equal(await page.evaluate(()=>S.grading),null);assert.deepEqual(await records(page),before);
  }finally{faultPath=null;await cdp.send('Network.setBlockedURLs',{urls:blockedURLs});await cdp.send('Network.setCacheDisabled',{cacheDisabled:false});}
  await page.reload();await loaded(page);assert.deepEqual(await records(page),before);
  return {status:'PASS_CONTROLLED_REAL_ASSET_DENIAL_AND_RECOVERY',scope:'Controlled local/CDP denial; not an observed public outage'};
}

(async () => {
  save();let diskTimer;const diskState={failure:null};
  try {
browserPhase='B009';
    if(!publicURL)await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
    const origin=publicURL?(publicURL.endsWith('/')?publicURL:publicURL+'/'):'http://127.0.0.1:'+server.address().port+'/';
    const allowedOrigin=new URL(origin).origin,hostname=new URL(origin).hostname;
    const staticText=fs.readFileSync(path.join(root,'app.js'),'utf8')+fs.readFileSync(path.join(root,'index.html'),'utf8');
    const blockedURLs=[...new Set([...staticText.matchAll(/https?:\/\/([a-zA-Z0-9.-]+)/g)].map(m=>m[1]).filter(h=>h!==hostname))].flatMap(h=>['*://'+h+'/*','*://*.'+h+'/*']);
browserPhase='B010';
    browser=await chromium.launch({executablePath:chrome,headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--disk-cache-size=1048576','--media-cache-size=1048576','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE '+hostname]});
    result.browser={playwright:require('playwright/package.json').version,chrome_version:browser.version(),node:process.version,physical_device:false};
    diskTimer=setInterval(()=>{try{filesystemGuard(criticalPaths,1024*1024);}catch(error){reportBrowserFailure(error,'FILESYSTEM_GUARD');latchFailure(diskState,error);settleStatus(result,diskState);browser.close().catch(()=>{});}},200);
    for (const width of [1280,390,320]) {
      browserViewport=width;
browserPhase='B011';
      const context=await browser.newContext({viewport:{width,height:width===390?844:900},serviceWorkers:'block'});
      const errors=[],external=[],nonGet=[];
      const page=await context.newPage(),cdp=await context.newCDPSession(page),network=[],cacheIds=new Set(),externalResponses=[];
      page.on('pageerror',error=>errors.push(error.message));await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:false});await cdp.send('Network.setBlockedURLs',{urls:blockedURLs});
      cdp.on('Network.requestWillBeSent',e=>{if(!['GET','HEAD'].includes(e.request.method))nonGet.push(e.request.method);if(new URL(e.request.url).origin!==allowedOrigin)external.push(new URL(e.request.url).hostname);});
      cdp.on('Network.requestServedFromCache',e=>{cacheIds.add(e.requestId);const item=network.find(v=>v.id===e.requestId);if(item)item.cached=true;});
      cdp.on('Network.responseReceived',e=>{const u=new URL(e.response.url);if(u.origin!==allowedOrigin)externalResponses.push(u.origin);else network.push({id:e.requestId,path:u.pathname.replace(new URL(origin).pathname,''),status:e.response.status,cached:!!e.response.fromDiskCache||cacheIds.has(e.requestId),cache_control:Object.entries(e.response.headers).find(([k])=>k.toLowerCase()==='cache-control')?.[1]||null});});
      const review={width,checks:[]};result.contexts.push(review);save();
      try {
browserPhase='B012';
        await page.goto(origin+'#/record');review.state=await loaded(page);
        review.weekly_display=await weeklyDisplay(page,network);
        review.selected_rankings=await selectedRankingDisplay(page,network);
browserPhase='B013';
        const bindings=await page.evaluate(async names=>{const out={};for(const name of names){const r=await fetch(name,{cache:'no-store'});if(!r.ok)throw Error('Required actual binding unavailable');out[name]=await gradingHash(new Uint8Array(await r.arrayBuffer()));}return out;},['data/release-identity.json',...Object.keys(generation.bindings)]);
        assert.equal(bindings['data/release-identity.json'],sha(generationBytes));for(const [name,hash]of Object.entries(generation.bindings))assert.equal(bindings[name],hash);
browserPhase='B014';
        const schema=await page.evaluate(()=>[S.grading.summary.schema_version,S.grading.summary.report_schema_version,!!S.grading.summary.forecast_accuracy]);
        assert.deepEqual(schema,['selection-public-report-v6','selection-report-v4',true],'Actual complete release must expose the approved accuracy contract');
browserPhase='B015';
        review.displayed_cells=await checkDisplayedCells(page);
browserPhase='B016';
        if(width===1280)review.independent_saved_rows=await semanticRows(page);
browserPhase='B017';
        review.drilldown=await drillDown(page);await assertNoOverflow(page,width);
browserPhase='B018';
        if(width===1280)review.actual_filter_coverage=await actualFilterCoverage(page);
browserPhase='B019';
        review.strategy_ui=await strategyUI(page);for(const item of review.strategy_ui)if(item.status.startsWith('UNAVAILABLE'))result.unavailable.push({width,...item});
browserPhase='B020';
        review.accuracy=await page.evaluate(()=>({cohorts:S.grading.summary.forecast_accuracy.cohorts.map(c=>({model:c.model_version,categories:Object.keys(c.categories).sort(),opportunities:c.coverage.opportunities,paired_counts:Object.fromEntries(Object.entries(c.categories).map(([k,v])=>[k,v.paired.raw.n]))})),rendered:!!document.querySelector('[data-forecast-accuracy]')}));
        assert.ok(review.accuracy.rendered);assert.ok(review.accuracy.cohorts.length>0);assert.ok(review.accuracy.cohorts.every(c=>c.categories.length===12));
        if(argv.includes('--screenshots'))await page.screenshot({path:path.join(evidence,'actual-record-'+width+'.png'),fullPage:false});
browserPhase='B021';
        await tab(page,'props');
        const pick=await page.locator('[data-add]').evaluateAll(buttons=>buttons.map(b=>b.dataset.add).find(v=>{const[pid]=v.split('|');const p=S.byId[pid],g=p&&S.games[p.game_id];return g?.state==='pre'&&Date.parse(g.kickoff)>Date.now();}) || null);
        let mine=null;if(pick){
        await page.locator('[data-add]').evaluateAll((buttons,p)=>buttons.find(b=>b.dataset.add===p).click(),pick);
        await tab(page,'mine');await page.waitForSelector('[data-mline]');
        const input=page.locator('[data-mline]').first(),line=Number(await input.inputValue());await input.fill(String(line+.5));await input.dispatchEvent('change');
        mine=await page.evaluate(()=>({bytes:localStorage.getItem('nflprops.mine'),picks:S.mine,status:S.mine.map(m=>propStatus(S.byId[m.pid],m.key,m.line,m.dir))}));
        assert.equal(mine.picks.length,1);assert.equal(mine.picks[0].line,line+.5);assert.ok(mine.status.every(s=>!s?.final));
        assert.match(await page.locator('.mine-sum').innerText(),/Final wins\s+0/);assert.match(await page.locator('.mine-sum').innerText(),/Final losses\s+0/);
        await page.reload();await loaded(page);assert.equal(await page.evaluate(()=>localStorage.getItem('nflprops.mine')),mine.bytes);review.my_picks={saved_count:1,personal_line_persisted:true,final_wins:0,final_losses:0,storage_sha256:sha(mine.bytes)};
        }else review.my_picks={status:'UNAVAILABLE_ACTUAL_UPCOMING_DISPLAYED_PICK'};
browserPhase='B022';
        if(width===1280)review.category_source_side_controls=await categoryControls(page);
browserPhase='B023';
        review.paper=await paper(page,width);if(mine)assert.equal(await page.evaluate(()=>localStorage.getItem('nflprops.mine')),mine.bytes,'Paper operations never mutate actual My Picks bytes');
        browserPhase='B024';review.scoring_and_real_rules=await scoringAndRules(page);
        browserPhase='B025';review.ordinary_cache=await ordinaryCache(page,cdp,network);
        browserPhase='B026';review.missing_partition_and_recovery=await missingPartition(page,cdp,blockedURLs,origin);
        review.missing_weekly_display_and_recovery=await missingWeeklyDisplay(page,cdp,blockedURLs,origin);
        review.missing_selected_rankings_and_recovery=await missingSelectedRankings(page,cdp,blockedURLs,origin);
        for(const item of review.paper.coverage)if(item.status.startsWith('UNAVAILABLE'))result.unavailable.push({width,...item});
        for(const kind of review.scoring_and_real_rules.unavailable)result.unavailable.push({width,kind,status:'UNAVAILABLE_ACTUAL_OUTCOME_POPULATION'});
        result.unavailable.push({width,kind:'natural_future_correction_transition',status:'UNAVAILABLE_NOT_FABRICATED'});
        if(!mine||!review.ordinary_cache.populated_storage)result.unavailable.push({width,kind:'populated_picks_and_tickets',status:'UNAVAILABLE_ACTUAL_POPULATION'});
browserPhase='B027';
        assert.deepEqual(externalResponses,[]);assert.deepEqual(errors,[],'Actual package has no browser page errors');assert.deepEqual(nonGet,[],'Private picks/tickets never issue network writes');
        review.intercepted_external_requests=external.length;review.external_network_requests=0;review.status='PASS';save();
      } catch(error) {
        reportBrowserFailure(error);
        review.status='FAIL';review.error=error.message;save();
        try{if(argv.includes('--screenshots'))await page.screenshot({path:path.join(evidence,'actual-failure-'+width+'.png'),fullPage:false});}catch{}
        throw error;
      } finally { await context.close(); }
    }
browserPhase='B028';
    for(const [filename,hash] of served)assert.equal(sha(fs.readFileSync(filename)),hash,'Actual consumed package bytes must remain unchanged');
    filesystemGuard(criticalPaths,1024*1024);
browserPhase='B029';
    assert.ok(settleStatus(result,diskState,result.unavailable.length?'PASS_EXECUTED_CHECKS_WITH_EXPLICIT_UNAVAILABLE_CASES':'PASS_EXECUTED_ACTUAL_CHECKS'),'DISK_FAILURE_LATCHED');result.playwright_routing_installed=false;result.served_asset_count=served.size;result.local_response_body_bytes=requests.reduce((n,r)=>n+r.bytes,0);result.provider_requests=0;result.source_package_mutated=false;
  } catch(error) { reportBrowserFailure(error);result.status='FAIL';result.error=error.message;result.stack=error.stack;throw error; }
  finally {clearInterval(diskTimer);if(!settleStatus(result,diskState))process.exitCode=1;result.finished_at=new Date().toISOString();save();clearTimeout(hardStop);if(browser)await browser.close();if(server.listening)await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{reportBrowserFailure(error);console.error(error.message);process.exitCode=1;});
