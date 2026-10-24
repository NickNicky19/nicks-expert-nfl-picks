#!/usr/bin/env node
'use strict';
// Local acceptance of the ACTUAL staged package. Never modifies staged/evidence files.
// Saved tickets/picks exist only in new disposable browser contexts at actual time.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
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
assert.equal(require('playwright/package.json').version,'1.62.1','Pinned Playwright required');
const chrome=process.env.NFL_CHROMIUM_PATH||['/usr/bin/google-chrome','/usr/bin/google-chrome-stable','/usr/bin/chromium'].find(p=>fs.existsSync(p));
assert.ok(chrome&&fs.statSync(chrome).isFile(),'UNSUPPORTED_PREINSTALLED_CHROME_UNAVAILABLE');
assert.ok(arg('--result'),'Bounded result path required');
const evidence=path.resolve(arg('--evidence',path.dirname(arg('--result'))));
assert.ok(arg('--artifact-root'),'Exact extracted artifact root required');
const artifactRoot=fs.realpathSync(arg('--artifact-root')),resultPath=path.resolve(arg('--result')),profileRoot=path.resolve(arg('--profile-root',resultPath+'.profiles'));
destinationsSafe([root,artifactRoot,path.dirname(markerPath)],[resultPath,evidence,profileRoot]);
assert.ok(!fs.existsSync(resultPath)&&!fs.existsSync(profileRoot),'Fresh result/profile paths required');
const criticalPaths=[root,artifactRoot,markerPath,resultPath,evidence,profileRoot,'/tmp',process.env.TMPDIR||'/tmp',process.env.RUNNER_TEMP||'/tmp',process.cwd(),chrome,require.resolve('playwright')];
const initialFilesystems=filesystemGuard(criticalPaths,12*1024*1024);
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const readJSON = filename => JSON.parse(fs.readFileSync(filename));
const marker = readJSON(markerPath);
assert.equal(marker.schema_version,'genuine-current-production-case-v1');
assert.equal(marker.status,'COMPLETE_GENUINE_NONDEPLOY_CASE','Actual complete case required');
assert.equal(marker.provider_case_attempts,1);assert.equal(marker.deployed,false);assert.equal(marker.main_written,false);
assert.ok(fs.statSync(root).isDirectory(), 'Actual fresh staged root is required');
fs.mkdirSync(evidence,{recursive:true});
fs.mkdirSync(profileRoot,{mode:0o700});process.env.TMPDIR=profileRoot;process.env.TMP=profileRoot;process.env.TEMP=profileRoot;
filesystemGuard(criticalPaths,12*1024*1024);
const generationBytes = fs.readFileSync(path.join(root, 'data/release-identity.json'));
const generation = JSON.parse(generationBytes);
const pointer = readJSON(path.join(root, 'data/selection-grading/latest.json'));
const board = readJSON(path.join(root, 'data/week.json'));
const appHash = sha(fs.readFileSync(path.join(root, 'app.js')));
assert.equal(generation.bindings['app.js'], appHash, 'Actual staged app is generation-bound');
assert.equal(generation.selection_report_id, pointer.report_id, 'Actual pointer is generation-bound');
assert.equal(generation.source_sha, marker.source, 'Capture source is actual successful attempt source');
assert.deepEqual(generation,marker.generation,'Identity is the actual case generation');
assert.equal(sha(fs.readFileSync(path.join(root,'data/selection-grading/latest.json'))),generation.bindings['data/selection-grading/latest.json']);
assert.equal(sha(fs.readFileSync(path.join(root,'data/week.json'))),generation.bindings['data/week.json']);
const result = {
  schema_version: 'actual-staged-release-browser-acceptance-v1', status: 'RUNNING',
  started_at: new Date().toISOString(), source: marker.source,
  app_sha256: appHash, generation_sha256: generation.generation_sha256,
  release_identity_file_sha256: sha(generationBytes), report_id: pointer.report_id,
  board_period: [board.season, board.week], original_board_generated_at: board.generated_at,
  contexts: [], checks: [], limitations: [
    'Local Chromium, not physical iPhone/Safari or deployed public acceptance.',
    'External requests are intercepted; zero provider requests are permitted.',
    'Route interception disables HTTP cache; reload coherence/persistence is exercised, not HTTP-cache timing.',
    'Actual future outcomes/corrections are not fabricated. Future result/correction controls remain separately identified software evidence.',
    'Private test selections are created now in isolated profiles, not owner records or authenticated historical decisions.'
  ]
};
result.target=publicURL?{kind:'ACTUAL_PUBLIC_URL',url:publicURL}:{kind:'ACTUAL_STAGED_BYTES',root};
result.manifest_sha256=sha(fs.readFileSync(markerPath));result.unavailable=[];
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
const hardStop = setTimeout(() => { result.status = 'FAIL'; result.error = 'Bounded 420-second browser review exhausted'; save(); if (browser) browser.close().finally(() => process.exit(2)); else process.exit(2); }, 420000);
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
    for(const [relative,expectedHash] of [['app.js',expected.bindings['app.js']],[immutable,immutableHash]]){
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
    if(!publicURL)await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
    const origin=publicURL?(publicURL.endsWith('/')?publicURL:publicURL+'/'):'http://127.0.0.1:'+server.address().port+'/';
    const allowedOrigin=new URL(origin).origin,hostname=new URL(origin).hostname;
    const staticText=fs.readFileSync(path.join(root,'app.js'),'utf8')+fs.readFileSync(path.join(root,'index.html'),'utf8');
    const blockedURLs=[...new Set([...staticText.matchAll(/https?:\/\/([a-zA-Z0-9.-]+)/g)].map(m=>m[1]).filter(h=>h!==hostname))].flatMap(h=>['*://'+h+'/*','*://*.'+h+'/*']);
    browser=await chromium.launch({executablePath:chrome,headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--disk-cache-size=1048576','--media-cache-size=1048576','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE '+hostname]});
    result.browser={playwright:require('playwright/package.json').version,chrome_version:browser.version(),node:process.version,physical_device:false};
    diskTimer=setInterval(()=>{try{filesystemGuard(criticalPaths,1024*1024);}catch(error){latchFailure(diskState,error);settleStatus(result,diskState);browser.close().catch(()=>{});}},200);
    for (const width of [1280,390,320]) {
      const context=await browser.newContext({viewport:{width,height:width===390?844:900},serviceWorkers:'block'});
      const errors=[],external=[],nonGet=[];
      const page=await context.newPage(),cdp=await context.newCDPSession(page),network=[],cacheIds=new Set(),externalResponses=[];
      page.on('pageerror',error=>errors.push(error.message));await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:false});await cdp.send('Network.setBlockedURLs',{urls:blockedURLs});
      cdp.on('Network.requestWillBeSent',e=>{if(!['GET','HEAD'].includes(e.request.method))nonGet.push(e.request.method);if(new URL(e.request.url).origin!==allowedOrigin)external.push(new URL(e.request.url).hostname);});
      cdp.on('Network.requestServedFromCache',e=>{cacheIds.add(e.requestId);const item=network.find(v=>v.id===e.requestId);if(item)item.cached=true;});
      cdp.on('Network.responseReceived',e=>{const u=new URL(e.response.url);if(u.origin!==allowedOrigin)externalResponses.push(u.origin);else network.push({id:e.requestId,path:u.pathname.replace(new URL(origin).pathname,''),status:e.response.status,cached:!!e.response.fromDiskCache||cacheIds.has(e.requestId),cache_control:Object.entries(e.response.headers).find(([k])=>k.toLowerCase()==='cache-control')?.[1]||null});});
      const review={width,checks:[]};result.contexts.push(review);save();
      try {
        await page.goto(origin+'#/record');review.state=await loaded(page);
        const bindings=await page.evaluate(async names=>{const out={};for(const name of names){const r=await fetch(name,{cache:'no-store'});if(!r.ok)throw Error('Required actual binding unavailable');out[name]=await gradingHash(new Uint8Array(await r.arrayBuffer()));}return out;},['data/release-identity.json',...Object.keys(generation.bindings)]);
        assert.equal(bindings['data/release-identity.json'],sha(generationBytes));for(const [name,hash]of Object.entries(generation.bindings))assert.equal(bindings[name],hash);
        const schema=await page.evaluate(()=>[S.grading.summary.schema_version,S.grading.summary.report_schema_version,!!S.grading.summary.forecast_accuracy]);
        assert.deepEqual(schema,['selection-public-report-v6','selection-report-v4',true],'Actual complete release must expose the approved accuracy contract');
        review.displayed_cells=await checkDisplayedCells(page);
        if(width===1280)review.independent_saved_rows=await semanticRows(page);
        review.drilldown=await drillDown(page);await assertNoOverflow(page,width);
        if(width===1280)review.actual_filter_coverage=await actualFilterCoverage(page);
        review.strategy_ui=await strategyUI(page);for(const item of review.strategy_ui)if(item.status.startsWith('UNAVAILABLE'))result.unavailable.push({width,...item});
        review.accuracy=await page.evaluate(()=>({cohorts:S.grading.summary.forecast_accuracy.cohorts.map(c=>({model:c.model_version,categories:Object.keys(c.categories).sort(),opportunities:c.coverage.opportunities,paired_counts:Object.fromEntries(Object.entries(c.categories).map(([k,v])=>[k,v.paired.raw.n]))})),rendered:!!document.querySelector('[data-forecast-accuracy]')}));
        assert.ok(review.accuracy.rendered);assert.ok(review.accuracy.cohorts.length>0);assert.ok(review.accuracy.cohorts.every(c=>c.categories.length===12));
        if(argv.includes('--screenshots'))await page.screenshot({path:path.join(evidence,'actual-record-'+width+'.png'),fullPage:false});
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
        if(width===1280)review.category_source_side_controls=await categoryControls(page);
        review.paper=await paper(page,width);if(mine)assert.equal(await page.evaluate(()=>localStorage.getItem('nflprops.mine')),mine.bytes,'Paper operations never mutate actual My Picks bytes');
        review.scoring_and_real_rules=await scoringAndRules(page);review.ordinary_cache=await ordinaryCache(page,cdp,network);review.missing_partition_and_recovery=await missingPartition(page,cdp,blockedURLs,origin);
        for(const item of review.paper.coverage)if(item.status.startsWith('UNAVAILABLE'))result.unavailable.push({width,...item});
        for(const kind of review.scoring_and_real_rules.unavailable)result.unavailable.push({width,kind,status:'UNAVAILABLE_ACTUAL_OUTCOME_POPULATION'});
        result.unavailable.push({width,kind:'natural_future_correction_transition',status:'UNAVAILABLE_NOT_FABRICATED'});
        if(!mine||!review.ordinary_cache.populated_storage)result.unavailable.push({width,kind:'populated_picks_and_tickets',status:'UNAVAILABLE_ACTUAL_POPULATION'});
        assert.deepEqual(externalResponses,[]);assert.deepEqual(errors,[],'Actual package has no browser page errors');assert.deepEqual(nonGet,[],'Private picks/tickets never issue network writes');
        review.intercepted_external_requests=external.length;review.external_network_requests=0;review.status='PASS';save();
      } catch(error) {
        review.status='FAIL';review.error=error.message;save();
        try{if(argv.includes('--screenshots'))await page.screenshot({path:path.join(evidence,'actual-failure-'+width+'.png'),fullPage:false});}catch{}
        throw error;
      } finally { await context.close(); }
    }
    for(const [filename,hash] of served)assert.equal(sha(fs.readFileSync(filename)),hash,'Actual consumed package bytes must remain unchanged');
    filesystemGuard(criticalPaths,1024*1024);
    assert.ok(settleStatus(result,diskState,result.unavailable.length?'PASS_EXECUTED_CHECKS_WITH_EXPLICIT_UNAVAILABLE_CASES':'PASS_EXECUTED_ACTUAL_CHECKS'),'DISK_FAILURE_LATCHED');result.playwright_routing_installed=false;result.served_asset_count=served.size;result.local_response_body_bytes=requests.reduce((n,r)=>n+r.bytes,0);result.provider_requests=0;result.source_package_mutated=false;
  } catch(error) { result.status='FAIL';result.error=error.message;result.stack=error.stack;throw error; }
  finally {clearInterval(diskTimer);if(!settleStatus(result,diskState))process.exitCode=1;result.finished_at=new Date().toISOString();save();clearTimeout(hardStop);if(browser)await browser.close();if(server.listening)await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
