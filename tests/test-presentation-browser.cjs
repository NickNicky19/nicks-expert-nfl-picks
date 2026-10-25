#!/usr/bin/env node
'use strict';
// Actual existing site on loopback; every external request is mocked. No provider collection.
// --baseline-root compares versioned production; --evidence-dir retains local screenshots.
// Phase 1 and Phase 2 intentionally have different final-evidence/status contracts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const args = process.argv.slice(2);
const arg = key => args.includes(key) ? args[args.indexOf(key) + 1] : null;
const repo = path.resolve(__dirname, '..');
const roots = { after: path.resolve(arg('--root') || path.join(repo, 'output')) };
if (arg('--baseline-root')) roots.before = path.resolve(arg('--baseline-root'));
const contracts = Object.fromEntries(Object.entries(roots).map(([lane, root]) => {
  const app = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
  return [lane, { authoritativeFinals: app.includes('function finalIdentity('), leanFirst: app.includes('function displayedProps(') }];
}));
const evidence = arg('--evidence-dir') && path.resolve(arg('--evidence-dir'));
if (evidence) fs.mkdirSync(path.join(evidence, 'screenshots'), { recursive: true });
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const original = JSON.parse(fs.readFileSync(path.join(roots.after, 'data/week.json')));
let fixture = null;
const requests = [];
let checks = 0;
const equal = (actual, expected, reason) => { assert.deepEqual(actual, expected, reason); checks++; };
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const match = pathname.match(/^\/(before|after)\/(.*)$/);
  if (!match || !roots[match[1]]) { res.writeHead(404); res.end(); return; }
  const [, lane, relative] = match;
  requests.push({ lane, path: '/' + relative });
  const root = roots[lane];
  const file = path.resolve(root, relative || 'index.html');
  let bytes;
  if (relative === 'data/week.json' && fixture) bytes = Buffer.from(JSON.stringify(fixture));
  else if (file.startsWith(root + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) bytes = fs.readFileSync(file);
  if (!bytes) { res.writeHead(404); res.end(); return; }
  const type = file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.json') ? 'application/json' : 'text/html';
  res.writeHead(200, { 'Content-Type': type, 'Cache-Control': 'no-store' }); res.end(bytes);
});

function fictionalWeek() {
  const week = structuredClone(original);
  const template = week.players.find(p => p.pos === 'WR' && p.props.some(x => x.key === 'rec'));
  const base = template.props.find(x => x.key === 'rec');
  week.games = [{ id: 'fictional-game', home: 'AAA', away: 'BBB', kickoff: '2026-10-20T17:00:00Z', state: 'pre', detail: 'Scheduled' }];
  const props = [
    { ...base, key: 'rec', proj: 5, adj: 5.5, line: 5, lean: 'over' },
    { ...base, key: 'rec_yd', proj: 30, adj: 35, line: 25, lean: 'over' },
    { ...base, key: 'rush_rec_yd', proj: 40, adj: 30, line: 50, lean: 'under' },
    { ...base, key: 'anytime_td', proj: .8, adj: null, line: .5, lean: 'over', td_chance: .55 },
    { ...base, key: 'fpts', proj: 20, adj: 24, line: 20, lean: 'over', adj_h: 1, line_h: .5, proj_h: 1 },
  ];
  week.players = ['FICTIONAL lead and tie control', 'FICTIONAL No Lean control'].map((name, i) => ({
    ...structuredClone(template), id: 'fictional-' + i, espn_id: null, name, team: 'AAA', opp: 'BBB',
    game_id: 'fictional-game', actual: null, inj: null, injury: null,
    props: props.map(prop => ({ ...structuredClone(prop), ...(i ? { lean: null, line_from: 'ours' } : {}) })),
  }));
  week.picks = { over: [], under: [] };
  return week;
}

async function open(browser, origin, lane, width, hash = 'props') {
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 } });
  const errors = [], mocked = [], unexpected = [];
  await context.route('**/*', route => {
    const req = route.request(), url = req.url();
    if (url.startsWith(origin + '/')) return route.continue();
    mocked.push({ host: new URL(url).hostname, type: req.resourceType() });
    if (req.resourceType() === 'image') return route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="48" height="48" fill="#223045"/></svg>' });
    if (req.resourceType() === 'stylesheet') return route.fulfill({ status: 200, contentType: 'text/css', body: '' });
    if (req.resourceType() === 'font') return route.fulfill({ status: 200, body: '' });
    return route.fulfill({ status: 200, contentType: 'application/json', body: url.includes('api.sleeper.app/stats') ? '[]' : '{"events":[]}' });
  });
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', req => { if (!req.url().startsWith(origin + '/') && !mocked.some(x => x.host === new URL(req.url()).hostname)) unexpected.push(req.url()); });
  await page.goto(`${origin}/${lane}/#/${hash}`);
  await page.waitForFunction(tab => S.data && !ticking && (tab === 'record'
    ? [...document.querySelectorAll('#main h2')].some(el => el.textContent.trim().startsWith('Track record'))
    : document.querySelector('#f-sort')), hash);
  return { page, context, errors, mocked, unexpected };
}
async function order(page, id, panels = false) {
  return page.evaluate(({ id, panels }) => {
    const card = document.querySelector(`[data-player="${id}"]`);
    if (panels) return [...card.querySelectorAll('.pbody > .cat')].map(el => el.dataset.cat.split('|')[1]);
    const labels = Object.entries(SHORT).sort((a, b) => b[1].length - a[1].length);
    return [...card.querySelectorAll('.pchip')].map(el => labels.find(([, label]) => el.textContent.trim().startsWith(label))?.[0]);
  }, { id, panels });
}
async function screenshot(page, stem, selector) {
  if (!evidence) return;
  await page.locator(selector).first().evaluate(el => {
    const header = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--top-h')) || 0;
    window.scrollTo(0, scrollY + el.getBoundingClientRect().top - header - 12);
  });
  await page.screenshot({ path: path.join(evidence, 'screenshots', stem + '.png') });
}

async function realDataChecks(browser, origin, lane, width) {
  const { page, context, errors, mocked } = await open(browser, origin, lane, width);
  try {
    await page.waitForSelector('#f-sort');
    const baseline = await page.evaluate(() => {
      const data = JSON.stringify(S.data), top = JSON.stringify(S.data.picks), ranks = {}, grades = [];
      S.f.hideOut = false;
      for (const sort of ['proj', 'live', 'name', 'edge']) for (const cat of ['', 'pass_td', 'rec_yd', 'fpts']) {
        S.f.sort = sort; S.f.cat = cat; ranks[sort + ':' + cat] = filteredPlayers().map(p => p.id);
      }
      for (const p of S.data.players) for (const x of p.props) grades.push([p.id, x.key, propStatus(p, x.key, x.line, x.lean)]);
      S.f.sort = 'edge'; S.f.cat = ''; S.f.q = ''; render();
      return { data, top, ranks, grades };
    });
    const scenes = await page.evaluate(() => {
      const candidates = S.data.players.map(p => {
        const eligible = p.props.map((x, i) => ({ key: x.key, index: i, eligible: !!(x.lean && x.adj != null), score: Math.abs(x.adj - x.line) / Math.max(1, x.line) }))
          .filter(x => x.eligible).sort((a, b) => b.score - a.score || a.index - b.index);
        return { id: p.id, name: p.name, pos: p.pos, props: p.props.map(x => x.key), ordered: p.props.map((x, i) => ({ x, i })).sort((a, b) => Number(!!(b.x.lean && b.x.adj != null)) - Number(!!(a.x.lean && a.x.adj != null)) || (a.x.lean && a.x.adj != null ? Math.abs(b.x.adj - b.x.line) / Math.max(1, b.x.line) - Math.abs(a.x.adj - a.x.line) / Math.max(1, a.x.line) : 0) || a.i - b.i).map(v => v.x.key), leading: eligible[0] };
      }).filter(p => p.leading && p.leading.index > 0);
      return ['4984', '9509'].map(id => candidates.find(p => p.id === id)).filter(Boolean).concat(candidates).filter((p, i, all) => all.findIndex(x => x.id === p.id) === i).slice(0, 2);
    });
    equal(scenes.length, 2, 'two real leading props outside customary first category');
    for (const scene of scenes) {
      await page.evaluate(id => { S.f.q = S.byId[id].name; S.open.clear(); render(); }, scene.id);
      equal(await order(page, scene.id), contracts[lane].leanFirst ? scene.ordered : scene.props, 'saved real collapsed chip order');
      equal(await page.locator(`[data-player="${scene.id}"] .pbody`).count(), 0, 'real card stays collapsed');
      await screenshot(page, `${scene.id}-${lane}-${width}-collapsed`, `[data-player="${scene.id}"]`);
      await page.locator(`[data-toggle="${scene.id}"]`).click();
      equal(await order(page, scene.id, true), contracts[lane].leanFirst ? scene.ordered : scene.props, 'real expanded panel order matches chips');
      await screenshot(page, `${scene.id}-${lane}-${width}-expanded`, `[data-player="${scene.id}"] .pbody > .cat`);
    }
    equal(await page.evaluate(() => JSON.stringify(S.data)), baseline.data, 'saved frozen data and source arrays unchanged');
    equal(await page.evaluate(() => JSON.stringify(S.data.picks)), baseline.top, 'saved Top picks unchanged');
    equal(errors, [], 'real-data browser has no page errors');
    return { lane, width, scenes, invariant_sha256: sha(JSON.stringify({ data: baseline.data, top: baseline.top, ranks: baseline.ranks })), grades_sha256: sha(JSON.stringify(baseline.grades)), mocked_requests: mocked.length };
  } finally { await context.close(); }
}

async function controlChecks(browser, origin, lane, width) {
  const { page, context, errors } = await open(browser, origin, lane, width);
  const normal = ['rec', 'rec_yd', 'rush_rec_yd', 'anytime_td', 'fpts'];
  const sorted = ['rec_yd', 'rush_rec_yd', 'fpts', 'rec', 'anytime_td'];
  const expected = contracts[lane].leanFirst ? sorted : normal;
  try {
    await page.waitForSelector('#f-sort');
    equal(await page.evaluate(() => [S.f.sort, S.open.size]), ['proj', 0], 'default sort and collapsed state unchanged');
    const source = await page.evaluate(() => JSON.stringify(S.data));
    await page.evaluate(() => { S.f.q = 'FICTIONAL lead'; S.f.sort = 'edge'; S.f.hideOut = false; render(); });
    equal(await order(page, 'fictional-0'), expected, 'fictional tie order in collapsed chips');
    await screenshot(page, `tie-${lane}-${width}-collapsed`, '[data-player="fictional-0"]');
    await page.locator('[data-toggle="fictional-0"]').click();
    equal(await order(page, 'fictional-0', true), expected, 'fictional tie panel ordering');
    await screenshot(page, `tie-${lane}-${width}-expanded`, '[data-player="fictional-0"] .pbody > .cat');
    for (const sort of ['name', 'live', 'proj', 'edge']) {
      await page.locator('#f-sort').selectOption(sort);
      equal(await order(page, 'fictional-0'), sort === 'edge' ? expected : normal, 'sort-switch chips');
      equal(await order(page, 'fictional-0', true), sort === 'edge' ? expected : normal, 'sort-switch panels');
      equal(await page.evaluate(() => S.open.has('fictional-0')), true, 'sort switching preserves expanded player');
    }
    await page.locator('#f-cat').selectOption('rec');
    equal(await order(page, 'fictional-0'), ['rec'], 'category filter chips');
    equal(await order(page, 'fictional-0', true), ['rec'], 'category filter panels');
    await page.locator('#f-cat').selectOption('');
    await page.locator('#f-q').focus(); await page.evaluate(() => renderLiveParts());
    equal(await page.evaluate(() => document.activeElement.id), 'f-q', 'live refresh retains query focus');
    equal(await order(page, 'fictional-0'), expected, 'focused refresh chip order');
    equal(await order(page, 'fictional-0', true), expected, 'focused refresh panel order');
    const mine = [{ pid: 'fictional-0', key: 'rec_yd', dir: 'over', line: 45, season: original.season, week: original.week, at: 1 }];
    await page.evaluate(picks => { S.mine = picks; store('mine', picks); }, mine);
    await page.locator('[data-line="fictional-0|rec_yd"]').fill('35');
    equal(await page.evaluate(() => [S.lines['fictional-0|rec_yd'], S.byId['fictional-0'].props[1].line]), [35, 25], 'personal-line editing preserves original board');
    equal(await order(page, 'fictional-0'), expected, 'saved-board score ignores personal line');
    for (const settings of [{ mode: 'sleeper', half: true }, { mode: 'espn', half: false }]) {
      await page.evaluate(settings => { S.sc = settings; applyScoring(); }, settings);
      equal(await order(page, 'fictional-0'), expected, 'scoring settings keep saved-board chip order');
      equal(await order(page, 'fictional-0', true), expected, 'scoring settings keep saved-board panel order');
    }
    equal(await page.evaluate(() => pv(S.byId['fictional-0'], S.byId['fictional-0'].props[4]).adj !== 24), true, 'scoring fixture changes actual displayed fantasy value');
    await page.evaluate(() => { S.sc = { mode: 'sleeper', half: false }; applyScoring(); });
    for (const state of ['pre', 'in', 'post']) {
      await page.evaluate(state => { S.games['fictional-game'].state = state; renderProps(); }, state);
      equal(await order(page, 'fictional-0'), expected, 'started-game behavior leaves display ordering unchanged');
    }
    if (contracts[lane].authoritativeFinals) {
      equal(await page.evaluate(() => propStatus(S.byId['fictional-0'], 'rec_yd', 25, 'over').res), 'unresolved', 'missing final receipt cannot be replaced by live statistics');
    }
    const grades = await page.evaluate(authoritative => {
      const p = S.byId['fictional-0']; S.live[p.id] = { gp: 1, rec: 3, rec_yd: 30 };
      if (authoritative) for (const [category, actual] of [['rec_yd', 30], ['rec', 3]]) {
        S.finalOutcomes.set(finalIdentity(p, category), { season: S.data.season, week: S.data.week,
          player_id: p.id, game_id: p.game_id, category, team: p.team, kickoff: S.games[p.game_id].kickoff,
          status: 'resolved', actual, final_confirmed: true, outcome_conflict: false });
      }
      return [propStatus(p, 'rec_yd', 25, 'over'), propStatus(p, 'rec_yd', S.mine[0].line, 'over'), propStatus(p, 'rec', 3, 'over')];
    }, contracts[lane].authoritativeFinals);
    equal(grades[2].res, contracts[lane].authoritativeFinals ? 'push' : 'miss', 'integer equality follows the explicit versioned grading contract');
    if (contracts[lane].authoritativeFinals) {
      const negatives = await page.evaluate(() => {
        const p = S.byId['fictional-0'], row = S.finalOutcomes.get(finalIdentity(p, 'rec_yd'));
        row.team = 'UNRELATED'; const identity = propStatus(p, 'rec_yd', 25, 'over').res;
        row.team = p.team; row.outcome_conflict = true; const conflict = propStatus(p, 'rec_yd', 25, 'over').res;
        row.outcome_conflict = false; row.status = 'dnp'; row.actual = null; const dnp = propStatus(p, 'rec_yd', 25, 'over').res;
        row.status = 'resolved'; row.actual = 30; return [identity, conflict, dnp];
      });
      equal(negatives, ['unresolved', 'unresolved', 'dnp'], 'matching identity and nonconflicting final evidence remain required; confirmed DNP is explicit');
    }
    equal(grades.slice(0, 2).map(x => x.res), ['hit', 'miss'], 'own saved contract remains distinct from board line');
    const gameOrder = await page.evaluate(() => {
      S.gameView = 'fictional-game'; gs(S.gameView).sort = 'lean';
      const box = document.createElement('div'); box.innerHTML = renderGameProps(S.games[S.gameView], { away: { abbr: 'BBB' }, home: { abbr: 'AAA' } });
      const keys = [...box.querySelectorAll('.pbody > .cat')].map(x => x.dataset.cat.split('|')[1]);
      S.gameView = null; S.games['fictional-game'].state = 'pre'; delete S.live['fictional-0'];
      if (typeof finalIdentity === 'function') for (const key of ['rec', 'rec_yd']) S.finalOutcomes.delete(finalIdentity(S.byId['fictional-0'], key));
      return keys;
    });
    equal(gameOrder, normal, 'game-page reused cards retain normal order');
    await page.evaluate(() => { S.f.q = 'FICTIONAL No Lean'; S.open.add('fictional-1'); render(); });
    equal(await order(page, 'fictional-1'), normal, 'all No Lean/reference chip ordering unchanged');
    equal(await order(page, 'fictional-1', true), normal, 'all No Lean/reference panels unchanged');
    await screenshot(page, `nolean-${lane}-${width}-expanded`, '[data-player="fictional-1"] .pbody > .cat');
    await page.evaluate(() => { S.f.q = 'FICTIONAL lead'; render(); document.activeElement?.blur(); renderLiveParts(); document.querySelector('#banner').hidden = false; });
    await Promise.all([page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/data/week.json')), page.locator('#reload').click()]);
    await page.waitForFunction(() => !ticking && document.querySelector('[data-player="fictional-0"] .pbody'));
    equal(await order(page, 'fictional-0'), expected, 'ordinary refresh retains chip order');
    equal(await order(page, 'fictional-0', true), expected, 'ordinary refresh retains expanded panels');
    equal(await page.evaluate(() => [S.f.sort, S.f.q, S.open.has('fictional-0')]), ['edge', 'FICTIONAL lead', true], 'ordinary refresh preserves open/filter/sort');
    equal(await page.evaluate(() => JSON.stringify(S.data)), source, 'controls do not mutate original source arrays or forecasts');
    equal(await page.evaluate(() => S.mine), mine, 'controls preserve saved fictional My Picks');
    await page.reload(); await page.waitForFunction(() => S.data && !ticking && document.querySelector('#f-sort'));
    equal(await page.evaluate(() => [S.f.sort, S.f.q, S.f.cat, S.open.size]), ['proj', '', '', 0], 'full reload preserves existing filter/open reset');
    equal(await page.evaluate(() => S.mine), mine, 'full reload retains device saved selections');
    equal(await page.evaluate(() => S.lines['fictional-0|rec_yd']), undefined, 'full reload preserves existing temporary-line reset');
    const finality = await page.evaluate(() => {
      const id = 'presentation-finality', previous = S.games[id], mine = S.mine, bytes = localStorage.getItem('nflprops.mine');
      const pick = {kind:'game',gid:id,market:'total',side:'under',line:0,season:S.data.season,week:S.data.week,at:1};
      const game = {id,home:'AAA',away:'BBB',kickoff:'2026-10-20T17:00:00Z',state:'post',detail:'Final',home_score:0,away_score:0};
      try {
        S.games[id] = game; S.mine = [pick]; const push = gameBetStatus(pick); renderMine(); const ownLine = document.querySelector('[data-mline]')?.value;
        game.away_score = null; const missing = gameBetStatus(pick).res;
        game.away_score = 0; game.state = 'in'; const live = gameBetStatus(pick); renderMine(); const text = document.querySelector('#main').innerText;
        game.id = 'other-game'; const wrongGame = gameBetStatus(pick).res;
        return {push:[push.res,push.final],missing,live:[live.res,live.final],wrongGame,ownLine,
          noFinalWin:/Final wins\s+0/.test(text),noCombined:!(/All \d+ together|CLEARED|LOST/.test(text)),bytes:localStorage.getItem('nflprops.mine')===bytes};
      } finally { S.mine = mine; if (previous) S.games[id] = previous; else delete S.games[id]; render(); }
    });
    equal(finality, {push:['push',true],missing:'unresolved',live:['equal',false],wrongGame:'unresolved',ownLine:'0',noFinalWin:true,noCombined:true,bytes:true}, 'Main game finality composes with qualified props without changing saved selections');
    equal(errors, [], 'control browser has no page errors');
    return { lane, width, leading_prop: 'rec_yd', score: .4, tie_follows: 'rush_rec_yd', grades };
  } finally { await context.close(); }
}

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ executablePath: process.env.NFL_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const real = [], controls = [], records = [];
  try {
    for (const width of [1280, 390, 320]) for (const lane of Object.keys(roots)) real.push(await realDataChecks(browser, origin, lane, width));
    fixture = fictionalWeek();
    for (const width of [1280, 390, 320]) for (const lane of Object.keys(roots)) controls.push(await controlChecks(browser, origin, lane, width));
    fixture = null;
    for (const width of [1280, 390, 320]) for (const lane of Object.keys(roots)) {
      const start = requests.length, item = await open(browser, origin, lane, width, 'record');
      try { equal(item.errors, [], 'record browser has no page errors'); records.push({ lane, width, text: await item.page.locator('#main').innerText(), legacy_cards: await item.page.locator('#main .stats .stat').allTextContents(), legacy_weeks: await item.page.locator('#main details.week > summary').allTextContents(), integrated_state: contracts[lane].authoritativeFinals ? await item.page.locator('#selection-grading').innerText() : null, paths: [...new Set(requests.slice(start).filter(x => x.lane === lane).map(x => x.path))].sort() }); }
      finally { await item.context.close(); }
    }
    if (roots.before) for (const width of [1280, 390, 320]) {
      equal(real.find(x => x.width === width && x.lane === 'after').invariant_sha256, real.find(x => x.width === width && x.lane === 'before').invariant_sha256, 'all rankings, Top selections and forecast records identical across versioned grading contracts');
      if (contracts.after.authoritativeFinals === contracts.before.authoritativeFinals) {
        equal(controls.find(x => x.width === width && x.lane === 'after').grades, controls.find(x => x.width === width && x.lane === 'before').grades, 'same-version grading contract retained');
        equal(real.find(x => x.width === width && x.lane === 'after').grades_sha256, real.find(x => x.width === width && x.lane === 'before').grades_sha256, 'same-version original board grades retained');
      } else equal(controls.find(x => x.width === width && x.lane === 'after').grades[2].res, 'push', 'corrected Phase 2 push must not equal the legacy integer-tie bug');
      const before = records.find(x => x.width === width && x.lane === 'before'), after = records.find(x => x.width === width && x.lane === 'after');
      equal(after.legacy_cards, before.legacy_cards, 'legacy archive summary values retained');
      equal(after.legacy_weeks, before.legacy_weeks, 'legacy archive weekly membership retained');
      if (contracts.after.authoritativeFinals === contracts.before.authoritativeFinals) {
        equal(after.text, before.text, 'same-version Track Record text unchanged');
        equal(after.paths, before.paths, 'same-version Track Record request contract unchanged');
      } else {
        equal(after.paths.filter(p => !p.startsWith('/data/selection-grading/') && p !== '/data/forecast-scorecard.json'), before.paths, 'only the documented grading pointer and public forecast scorecard extend legacy asset requests');
        equal(after.integrated_state.includes('report is unavailable'), true, 'missing public report is explicit rather than zero outcomes');
      }
    }
    equal(requests.filter(x => /offer-capture|matchup-proof|point-challenger/.test(x.path)), [], 'browser requests no private evidence or unsupported Phase2 assets');
    for (const lane of Object.keys(roots)) {
      const gradingPaths = [...new Set(requests.filter(x => x.lane === lane && x.path.startsWith('/data/selection-grading/')).map(x => x.path))];
      equal(gradingPaths, contracts[lane].authoritativeFinals ? ['/data/selection-grading/latest.json'] : [], 'versioned optional public pointer request contract');
      const scorecardPaths = [...new Set(requests.filter(x => x.lane === lane && x.path.includes('forecast-scorecard')).map(x => x.path))];
      equal(scorecardPaths, contracts[lane].authoritativeFinals ? ['/data/forecast-scorecard.json'] : [], 'only the exact supported public forecast scorecard may be requested');
    }
    const result = { status: 'PASS', contracts, checks, provider_requests_sent: 0, external_requests: 'ALL MOCKED', phone: '320/390px Chromium emulation, not physical iPhone/Safari or public-site acceptance', data_sha256: sha(fs.readFileSync(path.join(roots.after, 'data/week.json'))), app_sha256: Object.fromEntries(Object.entries(roots).map(([lane, root]) => [lane, sha(fs.readFileSync(path.join(root, 'app.js')))])), real, controls, record: records.map(({ text, ...x }) => ({ ...x, text_sha256: sha(text) })) };
    if (evidence) fs.writeFileSync(path.join(evidence, 'browser-results.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => server.close());
