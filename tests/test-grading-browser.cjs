#!/usr/bin/env node
'use strict';
// Actual integrated app, served only on loopback. Provider requests are mocked.
// Optional --root is an isolated website root containing approved saved assets.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const repo = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const arg = name => args.includes(name) ? args[args.indexOf(name) + 1] : null;
const staticRoot = arg('--root') ? path.resolve(arg('--root')) : path.join(repo, 'output');
const evidence = arg('--evidence-dir') ? path.resolve(arg('--evidence-dir')) : null;
if (evidence) fs.mkdirSync(evidence, { recursive: true });
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const encode = value => Buffer.from(JSON.stringify(value));
const statuses = ['win', 'loss', 'push', 'dnp', 'pending', 'unresolved', 'no_action', 'not_due', 'excluded'];
const cats = ['pass_yd', 'pass_td', 'pass_cmp', 'pass_att', 'pass_int', 'rush_yd', 'rush_att', 'rec', 'rec_yd', 'rush_rec_yd'];

function fictionalPublication() {
  const reportId = sha('FICTIONAL_BROWSER_PUBLICATION_NOT_REAL_EVIDENCE');
  const generatedAt = '2026-10-15T10:00:00Z';
  const rows = Array.from({ length: 305 }, (_, i) => ({
    schema_version: 'selection-decision-v1', decision_sha256: sha('fictional-decision-' + i),
    season: 2026, week: 6, player_id: 'fictional-' + i, name: i ? 'Fictional Player ' + i : '<script>unsafe()</script>',
    game_id: 'fictional-game', team: 'AAA', category: cats[i % cats.length], side: i % 2 ? 'under' : 'over',
    line: 4, line_from: i % 2 ? 'sleeper' : 'dk', top_at_decision: i < 32,
    model_version: 'original_sleeper_matchup_baseline', engine_sha256: sha('fictional-engine'),
    policy_version: 'phase2-timing-v1', checkpoint: 'history',
    provenance_class: 'local_pregame_membership_observation', recorded_selection_at: '2026-10-14T12:00:00Z',
    forecast_generated_at: '2026-10-14T11:59:00Z', collected_at: '2026-10-14T12:00:00Z',
    kickoff: '2026-10-15T00:15:00Z', selection_weekday: 'Wednesday', kickoff_weekday: 'Wednesday',
    observation_age_seconds: 900, seconds_to_kickoff: 44100, lead_time_bucket: '6-24h',
    action: i % 9 === 6 ? 'NO_ACTION' : i % 9 === 7 ? 'NOT_DUE' : i % 9 === 8 ? 'EXCLUDED' : 'SELECT',
    reason: i % 9 === 6 ? 'missing_row_in_latest_snapshot' : 'recorded_membership',
    result: statuses[i % 9], actual: i % 9 < 3 ? 4 : null,
    outcome_provenance: 'saved_cache_descriptive_regrade', outcome_source_mix: 'single_source',
    outcome_snapshot_sha256: sha('fictional-outcome'), observation_receipt_sha256: sha('fictional-observation'),
    source_coverage: 'UNKNOWN_LEGACY_RESPONSE_STATUS',
  })).sort((a, b) => a.decision_sha256.localeCompare(b.decision_sha256));
  const chunks = [], assets = new Map();
  const put = (name, value) => {
    const bytes = encode(value), descriptor = { path: reportId + '/' + name, sha256: sha(bytes) };
    assets.set('/data/selection-grading/' + descriptor.path, bytes);
    return descriptor;
  };
  for (let i = 0; i < rows.length; i += 250) {
    const members = rows.slice(i, i + 250);
    chunks.push({ ...put(`rows-${String(chunks.length).padStart(4, '0')}.json`, { schema_version: 'selection-public-rows-v1', report_id: reportId, rows: members }), count: members.length });
  }
  const location = new Map(rows.map((row, i) => [row.decision_sha256, Math.floor(i / 250)]));
  function table(members, view, dimension, value) {
    const counts = Object.fromEntries(statuses.map(status => [status, members.filter(row => row.result === status).length]));
    const decided = counts.win + counts.loss;
    const base = { provenance_class: 'local_pregame_membership_observation', model_version: 'original_sleeper_matchup_baseline', engine_sha256: sha('fictional-engine'),
      view, checkpoint: 'history', period: 'cumulative', dimension, value, ...counts,
      rows: members.length, selected: members.filter(row => row.action === 'SELECT').length, decided,
      hit_rate: decided ? counts.win / decided : null, unique_players: members.length, unique_games: 1, unique_weeks: 1,
      decided_unique_players: decided, decided_unique_games: decided ? 1 : 0, decided_unique_weeks: decided ? 1 : 0,
      row_positions: members.map(row => rows.indexOf(row)), row_ids_sha256: sha(JSON.stringify(members.map(row => row.decision_sha256))), row_chunks: [...new Set(members.map(row => location.get(row.decision_sha256)))],
    };
    return { ...base, summary_id: sha(JSON.stringify(base)) };
  }
  const tables = [];
  for (const view of ['all_qualifying_leans', 'top_picks', 'top_at_all_lean_decision', 'non_top_at_all_lean_decision']) {
    const members = view === 'all_qualifying_leans' ? rows : rows.filter(row => view === 'non_top_at_all_lean_decision' ? !row.top_at_decision : row.top_at_decision);
    tables.push(table(members, view, 'overall', 'all'));
    for (const dimension of ['category', 'side', 'category_side', 'selection_weekday', 'kickoff_weekday', 'lead_time_bucket', 'venue']) {
      const value = row => dimension === 'category_side' ? row.category + ':' + row.side : dimension === 'venue' ? row.line_from : row[dimension];
      for (const key of [...new Set(members.map(value))]) tables.push(table(members.filter(row => value(row) === key), view, dimension, key));
    }
  }
  const summary = put('summary.json', { schema_version: 'selection-public-report-v1', report_schema_version: 'selection-report-v2', report_id: reportId,
    summary: { tables }, source_sha: '7e5b499851a938f7b605ff2d43890d307da83e03', input_binding: 'NOT_YET_GIT_COMMITTED',
    coverage: { universe_scope: 'FICTIONAL_OBSERVED_UNION_ONLY' }, limitations: ['FICTIONAL ONLY. Not predictive evidence.'], uncertainty: null,
    primary_raw_vs_adjusted: { categories: { rec: { raw_sleeper: { n: 1, mae: 1, rmse: 1, mean_error: -1 }, unchanged_clone: { n: 1, mae: 0.5, rmse: 0.5, mean_error: -0.5 } } } } });
  const finals = Array.from({ length: 8 }, (_, i) => ({ season: 2026, week: 6, player_id: 'fixture-' + i, game_id: i === 3 ? 'fictional-pending' : 'fictional-game', category: 'rec', team: 'AAA',
    kickoff: i === 3 ? '2026-10-20T17:00:00Z' : '2026-10-15T00:15:00Z',
    status: i === 2 ? 'dnp' : i === 3 ? 'pending' : [1, 6, 7].includes(i) ? 'unresolved' : 'resolved',
    actual: i === 0 ? 0 : i === 4 ? 4 : i === 5 ? 5 : null,
    final_confirmed: [0, 2, 4, 5].includes(i), outcome_conflict: i === 6,
    game_state: i === 3 ? 'pre' : 'post', outcome_selection: i === 6 ? 'conflict' : [0, 2, 4, 5].includes(i) ? 'confirmed' : 'incomplete_observation',
    outcome_snapshot_sha256: [0, 2, 4, 5].includes(i) ? sha('fictional-source-' + i) : null,
    selected_outcome_provenance_sha256: [0, 2, 4, 5].includes(i) ? sha('fictional-provenance-' + i) : null,
    selected_outcome_row_sha256: [0, 2, 4, 5].includes(i) ? sha('fictional-row-' + i) : null,
    reason: i === 6 ? 'conflicting_sources' : i === 7 ? 'participation_not_confirmed' : null,
    outcome_provenance: 'recorded_outcome_receipt', outcome_source_mix: i === 6 ? 'conflicting_sources' : 'single_source',
    outcome_identity_status: 'bound_to_recorded_game', collected_at: generatedAt,
  }));
  const outcomes = put('outcomes.json', { schema_version: 'selection-final-outcomes-v1', report_id: reportId, outcomes: finals });
  const pointer = { schema_version: 'selection-publication-pointer-v1', report_id: reportId, generated_at: generatedAt, summary, rows: chunks, outcomes, row_count: rows.length };
  assets.set('/data/selection-grading/latest.json', encode(pointer));
  return { pointer, assets, rows, tables, finals };
}

function fictionalWeek() {
  const original = JSON.parse(fs.readFileSync(path.join(repo, 'output/data/week.json'), 'utf8'));
  const template = original.players.find(player => player.pos === 'WR' && player.props.some(prop => prop.key === 'rec'));
  const prop = template.props.find(item => item.key === 'rec');
  original.generated_at = '2026-10-15T10:00:00Z'; original.season = 2026; original.week = 6;
  original.games = [{ id: 'fictional-game', home: 'AAA', away: 'BBB', kickoff: '2026-10-15T00:15:00Z', state: 'post', detail: 'Final', home_score: 17, away_score: 10 },
    { id: 'fictional-pending', home: 'AAA', away: 'BBB', kickoff: '2026-10-20T17:00:00Z', state: 'pre', detail: 'Scheduled', home_score: null, away_score: null }];
  original.players = Array.from({ length: 8 }, (_, i) => ({ ...structuredClone(template), id: 'fixture-' + i, espn_id: null,
    name: ['Zero Played', 'Absent Statistics', 'Confirmed DNP', 'Pending Player', 'Integer Push', 'Line Difference', 'Conflicting Player', 'Fantasy Only'][i],
    team: 'AAA', opp: 'BBB', game_id: i === 3 ? 'fictional-pending' : 'fictional-game', inj: null, injury: null,
    props: [{ ...structuredClone(prop), key: 'rec', line: i === 4 ? 4 : 4.5, line_from: 'dk', lean: 'over', adj: 5, proj: 4.8 }],
    actual: i === 0 ? { stats: { gp: 1, rec: 0 } } : i === 7 ? { stats: { pts_ppr: 12 } } : null,
  }));
  original.picks = { over: original.players.map(player => ({ player_id: player.id, game_id: player.game_id, direction: 'over', key: 'rec', line: player.props[0].line, line_from: 'dk', adj: 5, proj: 4.8, over: 2, n: 5 })), under: [] };
  return original;
}

const fixture = fictionalPublication(), week = fictionalWeek();
let variant = 'valid', transferred = 0;
const requests = [];
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  requests.push(pathname);
  let bytes;
  if (!arg('--root')) {
    if (pathname === '/data/week.json') bytes = encode(week);
    else if (pathname === '/data/track_record.json' || pathname === '/data/dk_backtest.json' || pathname === '/data/forecast-scorecard.json') { res.writeHead(404); res.end(); return; }
    else if (pathname.startsWith('/data/selection-grading/')) {
      bytes = fixture.assets.get(pathname);
      if (variant === 'missing' || variant === 'missing-chunk' && /rows-/.test(pathname)) bytes = null;
      if (variant === 'corrupt' && /outcomes.json$/.test(pathname) && bytes) bytes = Buffer.concat([bytes, Buffer.from(' ')]);
    }
  }
  if (!bytes && (!pathname.startsWith('/data/selection-grading/') || arg('--root'))) {
    const relative = pathname === '/' ? 'index.html' : pathname.slice(1);
    const file = path.resolve(staticRoot, relative);
    if (file.startsWith(staticRoot + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) bytes = fs.readFileSync(file);
  }
  if (!bytes) { res.writeHead(404); res.end(); return; }
  transferred += bytes.length;
  res.writeHead(200, { 'Content-Type': pathname.endsWith('.js') ? 'application/javascript' : pathname.endsWith('.css') ? 'text/css' : pathname.endsWith('.json') ? 'application/json' : 'text/html', 'Cache-Control': 'no-store' });
  res.end(bytes);
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ executablePath: process.env.NFL_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const measurements = [];
  try {
    for (const width of [1280, 390]) {
      variant = 'valid';
      const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 } });
      await context.route('**/*', async route => {
        const url = route.request().url();
        if (url.startsWith(origin + '/')) return route.continue();
        // No real provider, font, image or quote requests are made.
        return route.fulfill({ status: 200, contentType: 'application/json', body: url.includes('api.sleeper.app/stats') ? '[]' : '{"events":[]}' });
      });
      const page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const startBytes = transferred, start = Date.now();
      await page.goto(origin + '/#/record');
      await page.waitForSelector('#selection-grading [data-grading-summaries]');
      const loadMs = Date.now() - start;
      assert.equal(await page.locator('[data-grading-row]').count(), 0, 'rows load only after drill-down');
      const chunkRequestsBefore = requests.filter(request => /\/rows-\d+\.json$/.test(request)).length;
      await page.locator('[data-grading-group]').first().click();
      await page.waitForSelector('[data-grading-row]');
      assert.ok(requests.filter(request => /\/rows-\d+\.json$/.test(request)).length - chunkRequestsBefore <= 4, 'one interaction reads at most four bounded chunks');
      let reconciledRowCount = 0;
      if (!arg('--root')) {
        assert.equal(await page.locator('[data-grading-row]').count(), 100);
        assert.match(await page.locator('[data-grading-freshness]').innerText(), /Stale report/);
        while (await page.locator('[data-grading-more]').count()) { await page.locator('[data-grading-more]').click(); await page.waitForFunction(() => !S.gradingGroup.loading); }
        const ids = await page.locator('[data-grading-row]').evaluateAll(nodes => nodes.map(node => node.dataset.gradingRow));
        assert.deepEqual(ids, fixture.rows.map(row => row.decision_sha256));
        reconciledRowCount = ids.length;
        const [download] = await Promise.all([page.waitForEvent('download'), page.locator('[data-grading-download]').click()]);
        const downloaded = JSON.parse(fs.readFileSync(await download.path(), 'utf8'));
        assert.equal(downloaded.schema_version, 'selection-public-group-download-v1');
        assert.equal(downloaded.report_id, fixture.pointer.report_id);
        assert.deepEqual(downloaded.rows.map(row => row.decision_sha256), ids);
        assert.equal(await page.locator('#selection-grading script').count(), 0, 'provider text is escaped');
        await page.getByLabel('Breakdown', { exact: true }).selectOption('category_side');
        assert.equal(await page.locator('[data-grading-summary]').count(), 10);
        await page.getByLabel('Cohort', { exact: true }).selectOption('non_top_at_all_lean_decision');
        assert.ok((await page.locator('[data-grading-summary]').count()) > 0);
        await page.getByLabel('Breakdown', { exact: true }).selectOption('overall');
        await page.locator('[data-grading-group]').click();
        await page.waitForFunction(() => !S.gradingGroup.loading);
        const nonTop = await page.evaluate(() => S.gradingGroup.rows.every(row => !row.top_at_decision));
        assert.equal(nonTop, true);
        const saved = week.players.map((player, i) => ({ pid: player.id, key: 'rec', dir: 'over', line: i === 5 ? 5.5 : player.props[0].line, season: 2026, week: 6, at: 1 }));
        await page.evaluate(picks => { S.mine = picks; store('mine', picks); S.tab = 'props'; render(); }, saved);
        const statusesAtCards = await page.evaluate(() => S.data.players.map(p => propStatus(p, 'rec', p.props[0].line, 'over')?.res || 'pending'));
        assert.deepEqual(statusesAtCards, ['miss', 'unresolved', 'dnp', 'pending', 'push', 'hit', 'unresolved', 'unresolved']);
        assert.match(await page.locator('.picks-wrap').innerText(), /PUSH/);
        assert.match(await page.locator('.picks-wrap').innerText(), /UNRESOLVED/);
        await page.evaluate(() => { S.tab = 'mine'; render(); });
        const mine = await page.locator('#main').innerText();
        assert.match(mine, /Final wins\s+0/); assert.match(mine, /Final losses\s+2/);
        assert.match(mine, /Push \/ DNP\s+1 \/ 1/); assert.match(mine, /Unresolved\s+3/);
        assert.doesNotMatch(mine, /All 8 together|CLEARED|LOST/);
        assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('nflprops.mine'))), saved);
        await page.evaluate(() => { const p = S.byId['fixture-5']; S.games[p.game_id].state = 'in'; S.slp[p.id] = { gp: 1, rec: 7 }; S.tab = 'mine'; render(); });
        assert.match(await page.locator('#main').innerText(), /CURRENTLY ABOVE/);
        assert.doesNotMatch(await page.locator('.mine-sum').innerText(), /Final wins\s+[1-9]/);
        await page.evaluate(() => { S.slp['fixture-5'].rec = 2; render(); });
        assert.match(await page.locator('#main').innerText(), /CURRENTLY BELOW/);
        await page.evaluate(() => { S.slp['fixture-5'].rec = 5.5; render(); });
        assert.match(await page.locator('#main').innerText(), /CURRENTLY EQUAL/);
        await page.evaluate(() => { S.slp['fixture-5'].rec = null; render(); });
        assert.equal(await page.evaluate(() => propStatus(S.byId['fixture-5'], 'rec', 5.5, 'over').v), null);
        assert.match(await page.locator('#main').innerText(), /UNRESOLVED/);
        assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('nflprops.mine'))), saved);
        await page.evaluate(() => { const p = S.byId['fixture-5']; S.games[p.game_id].state = 'post'; S.finalOutcomes.get(finalIdentity(p, 'rec')).actual = 7; render(); });
        assert.match(await page.locator('.mine-sum').innerText(), /Final wins\s+1/);
        await page.evaluate(() => { const p = S.byId['fixture-5']; S.finalOutcomes.get(finalIdentity(p, 'rec')).actual = 3; render(); });
        assert.match(await page.locator('.mine-sum').innerText(), /Final wins\s+0/);
        await page.evaluate(() => { S.tab = 'record'; render(); });
      } else {
        const table = await page.evaluate(() => S.grading.summary.summary.tables.find(t => t.summary_id === S.gradingGroup.id));
        while (await page.locator('[data-grading-more]').count()) { await page.locator('[data-grading-more]').click(); await page.waitForFunction(() => !S.gradingGroup.loading); }
        const ids = await page.locator('[data-grading-row]').evaluateAll(nodes => nodes.map(node => node.dataset.gradingRow));
        assert.equal(ids.length, table.row_positions.length);
        const originalIds = await page.evaluate(() => {
          const table = S.grading.summary.summary.tables.find(t => t.summary_id === S.gradingGroup.id);
          return table.row_positions.map(position => S.gradingGroup.idsByPosition.get(position));
        });
        assert.equal(sha(JSON.stringify(originalIds)), table.row_ids_sha256);
        assert.equal(new Set(ids).size, ids.length);
        reconciledRowCount = ids.length;
      }
      const firstEvidence = page.locator('[data-grading-row] details').first();
      if (await firstEvidence.count()) {
        await firstEvidence.locator('summary').click();
        assert.match(await firstEvidence.innerText(), /Recorded:|Generated:/);
      }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'no body overflow at ' + width);
      if (evidence) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({ path: path.join(evidence, 'integrated-record-' + width + '.png') });
        if (await page.locator('[data-grading-details]').count()) {
          await page.locator('[data-grading-details]').scrollIntoViewIfNeeded();
          await page.screenshot({ path: path.join(evidence, 'integrated-rows-' + width + '.png') });
        }
      }
      assert.deepEqual(errors, [], 'actual integrated app has no browser errors');
      measurements.push({ width, height: width === 390 ? 844 : 900, load_ms: loadMs, transferred_local_bytes: transferred - startBytes,
        publication_id: await page.evaluate(() => S.grading.pointer.report_id), complete_group_reconciled_rows: reconciledRowCount,
        rendered_group_rows: await page.locator('[data-grading-row]').count(), browser_errors: errors });
      if (!arg('--root')) {
        variant = 'missing-chunk'; await page.reload(); await page.waitForSelector('[data-grading-group]');
        await page.locator('[data-grading-group]').first().click(); await page.waitForSelector('[data-grading-details] [role="alert"]');
        assert.equal(await page.locator('[data-grading-row]').count(), 0);
        variant = 'corrupt'; await page.reload(); await page.waitForSelector('#selection-grading [role="status"]');
        assert.match(await page.locator('#selection-grading').innerText(), /checksum mismatch/);
        assert.equal(await page.evaluate(() => S.finalOutcomes.size), 0);
        variant = 'missing'; await page.reload(); await page.waitForSelector('#selection-grading [role="status"]');
        assert.match(await page.locator('#selection-grading').innerText(), /unavailable/);
        assert.equal(await page.evaluate(() => S.finalOutcomes.size), 0);
      }
      await context.close();
    }
    const result = { fixture: arg('--root') ? 'AUTHORIZED_SAVED_DATA_ISOLATED_ROOT' : 'FICTIONAL_ONLY', public_deployment_test: false,
      external_network_requests: 0, app_sha256: sha(fs.readFileSync(path.join(staticRoot, 'app.js'))),
      html_sha256: sha(fs.readFileSync(path.join(staticRoot, 'index.html'))), measurements, requests: [...new Set(requests)], assertions: 'passed' };
    if (evidence) fs.writeFileSync(path.join(evidence, 'grading-browser-results.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => server.close());
