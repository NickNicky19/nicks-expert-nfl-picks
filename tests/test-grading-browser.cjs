#!/usr/bin/env node
'use strict';
// Actual integrated app, served only on loopback. Provider requests are mocked.
// Optional --root is an isolated website root containing approved saved assets.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const os = require('node:os');
const cp = require('node:child_process');
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

function fictionalPublication(label = '') {
  const reportId = sha('FICTIONAL_BROWSER_PUBLICATION_NOT_REAL_EVIDENCE' + label);
  const generatedAt = '2026-10-15T10:00:00Z';
  const rows = Array.from({ length: 305 }, (_, i) => ({
    schema_version: 'selection-decision-v1', decision_sha256: sha('fictional-decision-' + i),
    season: 2026, week: 6, player_id: 'fictional-' + i, name: i ? 'Fictional Player ' + i : '<script>unsafe()</script>',
    game_id: 'fictional-game', team: 'AAA', category: cats[i % cats.length], side: i % 2 ? 'under' : 'over',
    line: 4, line_from: i % 2 ? 'sleeper' : 'dk', top_at_decision: i < 32,
    model_version: 'original_sleeper_matchup_baseline', engine_sha256: sha('fictional-engine' + label),
    policy_version: 'phase2-timing-v1', policy_sha256: sha('fictional-policy'), checkpoint: 'history',
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
  function table(members, view, dimension, value, source = 'all') {
    const counts = Object.fromEntries(statuses.map(status => [status, members.filter(row => row.result === status).length]));
    const decided = counts.win + counts.loss;
    const base = { provenance_class: 'local_pregame_membership_observation', model_version: 'original_sleeper_matchup_baseline', engine_sha256: sha('fictional-engine' + label),
      policy_version: 'phase2-timing-v1', policy_sha256: sha('fictional-policy'), line_source_scope: source,
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
    for (const source of ['dk', 'sleeper']) {
      const scoped = members.filter(row => row.line_from === source);
      tables.push(table(scoped, view, 'overall', 'all', source));
      for (const dimension of ['category', 'category_side']) {
        const value = row => dimension === 'category_side' ? row.category + ':' + row.side : row.category;
        for (const key of [...new Set(scoped.map(value))]) tables.push(table(scoped.filter(row => value(row) === key), view, dimension, key, source));
      }
    }
  }
  const summary = put('summary.json', { schema_version: 'selection-public-report-v2', report_schema_version: 'selection-report-v3', report_id: reportId,
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

// Same fictional rows and summary identities in a separately identified v3 layout.
function partitionedPublication(legacy) {
  const reportId = sha('FICTIONAL_PARTITIONED_PUBLICATION_NOT_REAL_EVIDENCE');
  const assets = new Map(), canonical = value => JSON.stringify(value && typeof value === 'object' ? (Array.isArray(value) ? value.map(v => JSON.parse(canonical(v))) : Object.fromEntries(Object.keys(value).sort().map(k => [k, JSON.parse(canonical(value[k]))]))) : value);
  const fields = ['provenance_class', 'model_version', 'engine_sha256', 'policy_version', 'policy_sha256', 'view', 'checkpoint', 'line_source_scope'];
  const put = (filename, payload, part = false) => {
    const bytes = encode({ ...payload, report_id: reportId }), hash = sha(bytes);
    const descriptor = { path: (part ? hash : reportId) + '/' + filename, sha256: hash, decoded_bytes: bytes.length };
    assets.set('/data/selection-grading/' + descriptor.path, bytes); return descriptor;
  };
  const contexts = {}, groups = new Map();
  const tables = legacy.tables.flatMap(table => [table, { ...table, period: '2026-w06', summary_id: sha('weekly-' + table.summary_id) }]);
  for (const table of tables) {
    const context = Object.fromEntries(fields.map(k => [k, table[k]])), id = sha(canonical(context));
    contexts[id] = context; const key = id + ':' + table.period;
    if (!groups.has(key)) groups.set(key, { context_id: id, period: table.period, tables: [] });
    groups.get(key).tables.push(table);
  }
  const parts = [...groups.values()].map(part => ({ ...put('summary.json', { schema_version: 'selection-public-summary-partition-v1', ...part }, true),
    context_id: part.context_id, period: part.period, table_count: part.tables.length }));
  const oldSummary = JSON.parse(legacy.assets.get('/data/selection-grading/' + legacy.pointer.summary.path));
  const summary = put('summary.json', { ...oldSummary, schema_version: 'selection-public-report-v3', row_count: legacy.rows.length,
    summary: {}, contexts, summary_partitions: parts });
  const historical = legacy.finals.map(row => ({ ...row, week: 5, actual: row.status === 'resolved' ? 99 : null }));
  const periods = [5, 6].map(week => {
    const outcomes = week === 5 ? historical : legacy.finals;
    return { ...put('outcomes.json', { schema_version: 'selection-final-outcome-period-v1', season: 2026, week, outcomes }, true), season: 2026, week, count: outcomes.length };
  });
  const outcomes = put('outcomes.json', { schema_version: 'selection-final-outcome-index-v1', outcome_count: legacy.finals.length + historical.length, periods });
  const rows = legacy.pointer.rows.map(descriptor => {
    const chunk = JSON.parse(legacy.assets.get('/data/selection-grading/' + descriptor.path));
    const value = put(descriptor.path.split('/')[1], chunk); delete value.decoded_bytes; return { ...value, count: descriptor.count };
  });
  const pointer = { ...legacy.pointer, schema_version: 'selection-publication-pointer-v2', report_id: reportId, summary, outcomes, rows };
  assets.set('/data/selection-grading/latest.json', encode(pointer));
  return { ...legacy, pointer, assets, tables, parts, periods };
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


function gzipPublication(plain, label = 'current', shared = true) {
  const reportId = sha('FICTIONAL_GZIP_PUBLICATION_' + label), assets = new Map();
  const read = descriptor => JSON.parse(plain.assets.get('/data/selection-grading/' + descriptor.path));
  const put = (filename, payload, compressed, part) => {
    const body = { ...payload, report_id: reportId };
    if (shared && compressed) {
      delete body.report_id;
      body.schema_version = filename.startsWith('rows') ? 'selection-public-rows-v2' : filename === 'summary.json' ? 'selection-public-summary-partition-v2' : 'selection-final-outcome-period-v2';
    }
    const bytes = encode(body), stored = compressed ? zlib.gzipSync(bytes, { mtime: 0 }) : bytes;
    const descriptor = { path: (part ? sha(stored) : reportId) + '/' + filename, sha256: sha(bytes), decoded_bytes: bytes.length };
    if (compressed) Object.assign(descriptor, { encoding: 'gzip', encoded_sha256: sha(stored), encoded_bytes: stored.length });
    assets.set('/data/selection-grading/' + descriptor.path, stored); return descriptor;
  };
  const oldSummary = read(plain.pointer.summary), oldOutcomes = read(plain.pointer.outcomes);
  const parts = oldSummary.summary_partitions.map(old => ({ ...put('summary.json', read(old), true, true), context_id: old.context_id, period: old.period, table_count: old.table_count }));
  const periods = oldOutcomes.periods.map(old => ({ ...put('outcomes.json', read(old), true, true), season: old.season, week: old.week, count: old.count }));
  const summary = put('summary.json', { ...oldSummary, schema_version: shared ? 'selection-public-report-v5' : 'selection-public-report-v4', summary_partitions: parts }, false, false);
  const outcomes = put('outcomes.json', { ...oldOutcomes, schema_version: shared ? 'selection-final-outcome-index-v2' : 'selection-final-outcome-index-v1', periods }, false, false);
  const rows = plain.pointer.rows.map(old => ({ ...put(shared ? 'rows.json' : old.path.split('/')[1], read(old), true, shared), count: old.count }));
  const pointer = { ...plain.pointer, schema_version: shared ? 'selection-publication-pointer-v4' : 'selection-publication-pointer-v3', report_id: reportId, summary, outcomes, rows };
  assets.set('/data/selection-grading/latest.json', encode(pointer));
  return { ...plain, pointer, assets, parts, periods };
}
const testCanonical = value => JSON.stringify(value && typeof value === 'object' ? (Array.isArray(value) ? value.map(v => JSON.parse(testCanonical(v))) : Object.fromEntries(Object.keys(value).sort().map(k => [k, JSON.parse(testCanonical(value[k]))]))) : value);
const legacyFixture = fictionalPublication();
const plainFixture = partitionedPublication(legacyFixture);
let fixture = gzipPublication(plainFixture);
const legacyGzipFixture = gzipPublication(plainFixture, 'legacy-gzip', false);
const metadataOnlyFixture = gzipPublication(plainFixture, 'metadata-only');
assert.deepEqual(metadataOnlyFixture.pointer.rows, fixture.pointer.rows, 'metadata-only graphs share exact row bodies');
assert.deepEqual(metadataOnlyFixture.parts, fixture.parts, 'metadata-only graphs share exact summary bodies');
assert.deepEqual(metadataOnlyFixture.periods, fixture.periods, 'metadata-only graphs share exact outcome bodies');
let week = fictionalWeek();
function scopeAssets(kind) {
  const scope = { schema_version: 'partial-week-public-scope-v1', full_board_verified: false, complete_week_qualified: false,
    output_sha256: sha('fictional-board-canonical'), games: week.games.map(game => ({ game_id: game.id, home: game.home, away: game.away,
      kickoff: game.kickoff, classification: game.state === 'pre' ? 'new_pregame_original_inputs_verified' : 'retained_legacy_original_proof_missing' })) };
  if (kind === 'scope-malformed') scope.games = null;
  const rawScope = encode(scope), generationId = sha('fictional coherent generation');
  const packaged = kind.startsWith('scope-packaged');
  const generation = { schema_version: kind === 'scope-packaged-v2' ? 'website-packaging-generation-v2' : packaged ? 'website-packaging-generation-v1' : 'website-generation-v1', generation_sha256: generationId,
    board_sha256: scope.output_sha256, source_sha: packaged ? '8'.repeat(40) : '7e5b499851a938f7b605ff2d43890d307da83e03',
    selection_report_id: kind === 'scope-mixed-report' ? sha('different report') : fixture.pointer.report_id,
    bindings: { 'data/week.json': sha(encode(week)), 'data/verification-scope.json': sha(rawScope) } };
  const health = { generation_sha256: generationId, board_sha256: scope.output_sha256, source_sha: generation.source_sha };
  if (packaged) {
    Object.assign(generation, { capture_source_sha: '7e5b499851a938f7b605ff2d43890d307da83e03', capture_generation_sha256: sha('original capture'), packaged_at: '2026-10-18T20:00:00Z' });
    Object.assign(health, { capture_source_sha: kind === 'scope-packaged-mixed-capture' ? '9'.repeat(40) : generation.capture_source_sha,
      capture_generation_sha256: generation.capture_generation_sha256, packaged_at: generation.packaged_at });
  }
  return { 'verification-scope': rawScope, 'release-identity': encode(generation), health: encode(health) };
}
let variant = 'valid', transferred = 0;
const requests = [];
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  requests.push(pathname);
  let bytes;
  if (!arg('--root')) {
    if (pathname === '/data/week.json') bytes = encode(variant === 'scope-mixed-board' ? { ...week, generated_at: '2026-10-15T11:00:00Z' } : week);
    else if (variant.startsWith('scope-') && /^\/data\/(verification-scope|release-identity|health)\.json$/.test(pathname)) {
      bytes = scopeAssets(variant)[pathname.split('/').pop().replace('.json', '')];
    }
    else if (pathname === '/data/track_record.json' || pathname === '/data/dk_backtest.json' || pathname === '/data/forecast-scorecard.json') { res.writeHead(404); res.end(); return; }
    else if (pathname.startsWith('/data/selection-grading/')) {
      bytes = (variant === 'legacy' ? legacyFixture : variant === 'legacy-gzip' ? legacyGzipFixture : variant === 'plain-partitioned' ? plainFixture : fixture).assets.get(pathname);
      if (variant === 'oversized-pointer' && pathname.endsWith('/latest.json') && bytes) bytes = Buffer.concat([bytes, Buffer.alloc(1024 * 1024, 32)]);
      const contentPart = !pathname.includes('/' + fixture.pointer.report_id + '/') && !pathname.endsWith('/latest.json');
      if (variant === 'missing-summary-part' && contentPart && /summary.json$/.test(pathname)) bytes = null;
      if (variant === 'missing-outcome-part' && contentPart && /outcomes.json$/.test(pathname)) bytes = null;
      if (variant === 'missing' || variant === 'missing-chunk' && /\/rows(?:-[0-9]{4})?\.json$/.test(pathname)) bytes = null;
      if (variant === 'corrupt' && /outcomes.json$/.test(pathname) && bytes) { bytes = Buffer.from(bytes); bytes[0] ^= 1; }
    }
  }
  if (!bytes && (!pathname.startsWith('/data/selection-grading/') || arg('--root'))) {
    const relative = pathname === '/' ? 'index.html' : pathname.slice(1);
    const file = path.resolve(staticRoot, relative);
    if (file.startsWith(staticRoot + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) bytes = fs.readFileSync(file);
  }
  if (!bytes) { res.writeHead(404); res.end(); return; }
  const applicationGzip = bytes[0] === 0x1f && bytes[1] === 0x8b;
  const coding = applicationGzip && ['outer-http-gzip', 'wrong-http-coding'].includes(variant);
  if (coding && variant === 'outer-http-gzip') bytes = zlib.gzipSync(bytes, { mtime: 0 });
  transferred += bytes.length;
  res.writeHead(200, { ...(coding ? { 'Content-Encoding': 'gzip' } : {}), 'Content-Type': pathname.endsWith('.js') ? 'application/javascript' : pathname.endsWith('.css') ? 'text/css' : pathname.endsWith('.json') ? 'application/json' : 'text/html', 'Cache-Control': 'no-store' });
  res.end(bytes);
});

async function presentationChecks(browser, origin, width) {
  // Reuse the real application and normal HTTP reload path with fictional,
  // frozen-in-time boards. Never consult outcomes to choose display order.
  const previous = week;
  week = structuredClone(previous);
  const base = week.players[3].props[0];
  week.players[3].props = [
    { ...base, key: 'rec', proj: 5, adj: 5.5, line: 5, lean: 'over' },
    { ...base, key: 'rec_yd', proj: 30, adj: 35, line: 25, lean: 'over' },
    { ...base, key: 'rush_rec_yd', proj: 40, adj: 30, line: 50, lean: 'under' },
    { ...base, key: 'anytime_td', proj: .8, adj: null, line: .5, lean: 'over', td_chance: .55 },
    { ...base, key: 'fpts', proj: 20, adj: 24, line: 20, lean: 'over', adj_h: 1, line_h: .5, proj_h: 1 },
  ];
  week.players[0].props = week.players[3].props.map(prop => ({ ...prop, lean: null, line_from: 'ours' }));
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 } });
  const errors = [];
  let checks = 0;
  const equal = (a, b, reason) => { assert.deepEqual(a, b, reason); checks++; };
  const normal = ['rec', 'rec_yd', 'rush_rec_yd', 'anytime_td', 'fpts'];
  const ordered = ['rec_yd', 'rush_rec_yd', 'fpts', 'rec', 'anytime_td'];
  try {
    await context.route('**/*', route => {
      const url = route.request().url();
      if (url.startsWith(origin + '/')) return route.continue();
      return route.fulfill({ status: 200, contentType: 'application/json', body: url.includes('api.sleeper.app/stats') ? '[]' : '{"events":[]}' });
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + '/#/props');
    await page.waitForFunction(() => S.data && !ticking && document.querySelector('#f-sort'));
    equal(await page.evaluate(() => S.f.sort), 'proj', 'default sort is unchanged');
    equal(await page.evaluate(() => S.open.size), 0, 'cards remain collapsed initially');
    const original = await page.evaluate(() => JSON.stringify(S.data.players));
    const top = await page.evaluate(() => JSON.stringify(S.data.picks));
    await page.evaluate(() => { S.f.q = 'Pending Player'; S.f.hideOut = false; S.f.sort = 'edge'; render(); });
    const order = async (id = 'fixture-3', panels = false) => page.evaluate(({ id, panels }) => {
      const card = document.querySelector(`[data-player="${id}"]`);
      if (panels) return [...card.querySelectorAll('.pbody > .cat')].map(el => el.dataset.cat.split('|')[1]);
      const labels = Object.entries(SHORT).sort((a, b) => b[1].length - a[1].length);
      return [...card.querySelectorAll('.pchip')].map(el => labels.find(([, label]) => el.textContent.trim().startsWith(label))?.[0]);
    }, { id, panels });
    equal(await order(), ordered, 'collapsed chips lead with rec_yd, score .4; equal-score rush_rec_yd follows');
    equal(await page.locator('[data-player="fixture-3"] .pbody').count(), 0, 'sorting does not auto-expand');
    await page.locator('[data-toggle="fixture-3"]').click();
    equal(await order('fixture-3', true), ordered, 'expanded panels match chips');
    const topText = await page.locator('.picks-wrap').innerText();
    for (const sort of ['name', 'live', 'proj', 'edge']) {
      await page.locator('#f-sort').selectOption(sort);
      equal(await order(), sort === 'edge' ? ordered : normal, 'sort switching chip order');
      equal(await order('fixture-3', true), sort === 'edge' ? ordered : normal, 'sort switching panel order');
      equal(await page.evaluate(() => S.open.has('fixture-3')), true, 'sort switch retains expanded player');
      equal(await page.locator('.picks-wrap').innerText(), topText, 'Top Picks content unchanged on identical inputs');
    }
    await page.locator('#f-cat').selectOption('rec');
    equal(await order(), ['rec'], 'category filter applies before sorting');
    equal(await order('fixture-3', true), ['rec'], 'panels respect category filter');
    await page.locator('#f-cat').selectOption('');
    await page.locator('#f-q').focus();
    await page.evaluate(() => renderLiveParts());
    equal(await page.locator('#f-q').inputValue(), 'Pending Player', 'focused query survives live refresh');
    equal(await page.evaluate(() => document.activeElement.id), 'f-q', 'live refresh retains input focus');
    equal(await order(), ordered, 'focused-input live refresh keeps chips');
    equal(await order('fixture-3', true), ordered, 'focused-input live refresh keeps panels');
    const saved = [{ pid: 'fixture-3', key: 'rec_yd', dir: 'over', line: 45, season: 2026, week: 6, at: 1 }];
    await page.evaluate(picks => { S.mine = picks; store('mine', picks); }, saved);
    await page.locator('[data-line="fixture-3|rec_yd"]').fill('35');
    equal(await page.evaluate(() => S.lines['fixture-3|rec_yd']), 35, 'personal line editor still works');
    equal(await page.evaluate(() => S.byId['fixture-3'].props[1].line), 25, 'saved board line unchanged');
    equal(await order(), ordered, 'personal line does not supply display score');
    equal(await order('fixture-3', true), ordered, 'personal-line edit retains panel positions');
    equal(await page.evaluate(() => document.activeElement.dataset.line), 'fixture-3|rec_yd', 'line editor focus retained');
    for (const settings of [{ mode: 'sleeper', half: true }, { mode: 'espn', half: false }]) {
      await page.evaluate(settings => { S.sc = settings; applyScoring(); }, settings);
      equal(await order(), ordered, 'scoring changes do not replace saved-board ranking inputs');
      equal(await order('fixture-3', true), ordered, 'custom-scoring panels keep saved-board order');
    }
    equal(await page.evaluate(() => pv(S.byId['fixture-3'], S.byId['fixture-3'].props[4]).adj !== 24), true, 'custom scoring actually changes displayed fantasy value');
    await page.evaluate(() => { S.sc = { mode: 'sleeper', half: false }; applyScoring(); });
    for (const state of ['pre', 'in', 'post']) {
      await page.evaluate(state => { S.games[S.byId['fixture-3'].game_id].state = state; renderProps(); }, state);
      equal(await order(), ordered, 'game state does not change presentation eligibility');
    }
    const grades = await page.evaluate(() => {
      const p = S.byId['fixture-3'], g = S.games[p.game_id];
      S.finalOutcomes.set(finalIdentity(p, 'rec_yd'), { season: 2026, week: 6, player_id: p.id, game_id: p.game_id,
        category: 'rec_yd', team: p.team, kickoff: g.kickoff, status: 'resolved', actual: 30,
        final_confirmed: true, outcome_conflict: false });
      return [propStatus(p, 'rec_yd', 25, 'over').res, propStatus(p, 'rec_yd', S.mine[0].line, 'over').res];
    });
    equal(grades, ['hit', 'miss'], 'board and own saved contract remain independently graded');
    // Exercise the shared player-card renderer with the real game-page guard.
    const reused = await page.evaluate(() => {
      S.gameView = S.byId['fixture-3'].game_id;
      const container = document.createElement('div');
      gs(S.gameView).sort = 'lean';
      container.innerHTML = renderGameProps(S.games[S.gameView], { away: { abbr: 'BBB' }, home: { abbr: 'AAA' } });
      const result = [...container.querySelectorAll('.pbody > .cat')].map(el => el.dataset.cat.split('|')[1]);
      S.gameView = null;
      S.games[S.byId['fixture-3'].game_id].state = 'pre';
      S.finalOutcomes.delete(finalIdentity(S.byId['fixture-3'], 'rec_yd'));
      return result;
    });
    equal(reused, normal, 'game-page card reuse retains normal category order');
    await page.evaluate(() => { S.f.q = 'Zero Played'; S.open.add('fixture-0'); render(); });
    equal(await order('fixture-0'), normal, 'all No Lean/reference chips retain normal order');
    equal(await order('fixture-0', true), normal, 'all No Lean/reference panels retain normal order');
    await page.evaluate(() => { S.f.q = 'Pending Player'; render(); document.activeElement?.blur(); renderLiveParts(); });
    equal(await order(), ordered, 'unfocused live refresh retains ordering');
    await page.evaluate(() => { document.querySelector('#banner').hidden = false; });
    await Promise.all([page.waitForResponse(r => new URL(r.url()).pathname === '/data/week.json'), page.locator('#reload').click()]);
    await page.waitForFunction(() => !ticking && document.querySelector('[data-player="fixture-3"] .pbody'));
    equal(await order(), ordered, 'ordinary update reload retains edge chips');
    equal(await order('fixture-3', true), ordered, 'ordinary update reload retains expanded panels');
    equal(await page.evaluate(() => [S.f.sort, S.f.q, S.open.has('fixture-3')]), ['edge', 'Pending Player', true], 'ordinary refresh retains sort/filter/open');
    equal(await page.evaluate(() => JSON.stringify(S.data.players)), original, 'original forecasts and prop arrays immutable');
    equal(await page.evaluate(() => JSON.stringify(S.data.picks)), top, 'recorded Top memberships unchanged');
    equal(await page.evaluate(() => S.mine), saved, 'all interactions retain own saved contract');
    equal(await page.evaluate(() => S.lines['fixture-3|rec_yd']), 35, 'ordinary refresh retains temporary personal line');
    await page.reload();
    await page.waitForFunction(() => S.data && !ticking && document.querySelector('#f-sort'));
    equal(await page.evaluate(() => [S.f.sort, S.f.q, S.f.cat, S.open.size]), ['proj', '', '', 0], 'full browser reload preserves existing reset behavior');
    equal(await page.evaluate(() => S.mine), saved, 'full browser reload preserves device selections');
    equal(await page.evaluate(() => S.lines['fixture-3|rec_yd']), undefined, 'full browser reload retains existing temporary-line reset');
    equal(errors, [], 'no browser errors');
    return { width, checks, assertions: 'passed', leading_prop: 'rec_yd', score: .4, phone: width === 390 ? 'Chromium width emulation, not physical iPhone/Safari' : null };
  } finally { await context.close(); week = previous; }
}

async function archiveAndDecoderChecks(browser, origin) {
  const savedFixture = fixture, savedVariant = variant;
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'nfl-fictional-report-archives-'));
  const git = (...args) => cp.execFileSync('git', ['-C', directory, ...args], { encoding: 'utf8', stdio: ['ignore','pipe','pipe'] }).trim();
  git('init','-q'); git('config','user.name','Fictional browser test'); git('config','user.email','fixture@example.invalid');
  const generations = [];
  for (const label of ['A','B','C','D']) {
    const value = gzipPublication(partitionedPublication(fictionalPublication(label)), label);
    const manifestBytes = encode({ schema_version: 'selection-hosting-generation-v1', report_id: value.pointer.report_id, pointer: value.pointer,
      transport_fixture: 'FICTIONAL_COMMITTED_ARCHIVE_NOT_ORIGINAL_FOOTBALL_EVIDENCE' });
    const manifest = { path: sha(manifestBytes) + '/manifest.json', sha256: sha(manifestBytes), decoded_bytes: manifestBytes.length };
    value.assets.set('/data/selection-grading/' + manifest.path, manifestBytes);
    for (const [name, bytes] of value.assets) {
      const file = path.join(directory, 'output', name.slice(1)); fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, bytes);
    }
    git('add','output'); git('commit','-qm','Fictional committed generation ' + label);
    generations.push({ ...value, manifest, git_ref: git('rev-parse','HEAD') });
  }
  const delivered = { ...generations[3], assets: new Map([...generations[2].assets, ...generations[3].assets]) };
  const working = { schema_version: 'selection-hosting-working-set-v1', latest: generations[3].manifest, previous: generations[2].manifest, registry: [], archive_index: [] };
  const grouped = new Map();
  for (const old of generations.slice(0,2)) {
    const key = sha(testCanonical(old.pointer)), prefix = key[0];
    if (!grouped.has(prefix)) grouped.set(prefix, {});
    grouped.get(prefix)[key] = { git_ref: old.git_ref, manifest: old.manifest };
  }
  for (const [prefix,reports] of grouped) {
    const bytes = encode({ schema_version: 'selection-hosting-archive-v1', repository: 'NickNicky19/nicks-expert-nfl-picks', prefix, reports });
    const descriptor = { path: sha(bytes) + '/archive.json', sha256: sha(bytes), decoded_bytes: bytes.length };
    delivered.assets.set('/data/selection-grading/' + descriptor.path, bytes); working.archive_index.push({ prefix, asset: descriptor });
  }
  working.delivery_sha256 = sha(testCanonical(working));
  delivered.assets.set('/data/selection-grading/hosting.json', encode(working));
  let cors = 'allowed', corrupt = false; const archiveRequests = [];
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await context.route('**/*', route => {
    const url = route.request().url();
    if (url.startsWith(origin + '/')) return route.continue();
    const match = url.match(/^https:\/\/raw\.githubusercontent\.com\/NickNicky19\/nicks-expert-nfl-picks\/([0-9a-f]{40})\/output\/(data\/selection-grading\/[0-9a-f]{64}\/(?:manifest|summary|outcomes|rows|rows-[0-9]{4})\.json)$/);
    if (match) {
      archiveRequests.push({ ref: match[1], path: match[2], cors, corrupt });
      let bytes;
      try { bytes = cp.execFileSync('git', ['-C', directory, 'show', match[1] + ':output/' + match[2]], { stdio: ['ignore','pipe','pipe'] }); }
      catch (_) { return route.fulfill({ status: 404, headers: { 'Access-Control-Allow-Origin': origin }, body: '' }); }
      if (corrupt && /\/rows(?:-[0-9]{4})?\.json$/.test(match[2])) { bytes = Buffer.from(bytes); bytes[0] ^= 1; }
      return route.fulfill({ status: 200, headers: { 'Content-Type': 'application/octet-stream', 'Access-Control-Allow-Origin': cors === 'allowed' ? origin : 'https://invalid.example' }, body: bytes });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: url.includes('api.sleeper.app/stats') ? '[]' : '{"events":[]}' });
  });
  try {
    fixture = generations[0]; variant = 'valid'; const page = await context.newPage();
    await page.goto(origin + '/#/record'); await page.waitForSelector('[data-performance-primary]'); await page.waitForFunction(() => !S.grading.partLoading);
    const saved = [{ pid: 'fixture-5', key: 'rec', dir: 'over', line: 5.5, season: 2026, week: 6, at: 1 }];
    await page.evaluate(picks => { S.mine=picks; store('mine',picks); }, saved);
    const storage = await page.evaluate(() => localStorage.getItem('nflprops.mine'));
    for (const next of generations.slice(1)) fixture = next; // Operating site advances B/C/D while page stays on A.
    fixture = delivered;
    // An uncached old-generation exact-context summary must use the same pinned archive, too.
    await page.selectOption('[data-grading-filter=line_source_scope]', 'dk');
    await page.waitForFunction(() => !S.grading.partLoading);
    assert.ok(archiveRequests.some(item => /summary.json$/.test(item.path)));
    await page.selectOption('[data-grading-filter=line_source_scope]', 'all');
    await page.waitForFunction(() => !S.grading.partLoading);
    await page.locator('[data-grading-group]').first().click(); await page.waitForSelector('[data-grading-row]');
    while (await page.locator('[data-grading-more]').count()) { await page.locator('[data-grading-more]').click(); await page.waitForFunction(() => !S.gradingGroup.loading); }
    assert.equal(await page.evaluate(() => S.grading.pointer.report_id), generations[0].pointer.report_id);
    assert.deepEqual(await page.locator('[data-grading-row]').evaluateAll(nodes => nodes.map(node => node.dataset.gradingRow)), generations[0].rows.map(row => row.decision_sha256));
    assert.ok(archiveRequests.some(item => /\/rows(?:-[0-9]{4})?\.json$/.test(item.path)));
    assert.ok(archiveRequests.every(item => item.ref === generations[0].git_ref));
    assert.equal(await page.evaluate(() => localStorage.getItem('nflprops.mine')), storage);
    for (const failure of ['cors','corrupt']) {
      cors = failure === 'cors' ? 'wrong' : 'allowed'; corrupt = failure === 'corrupt';
      await page.evaluate(() => { S.grading.chunks.clear(); S.gradingGroup=null; });
      await page.locator('[data-grading-group]').first().click(); await page.waitForSelector('[data-grading-details] [role="alert"]');
      assert.equal(await page.locator('[data-grading-row]').count(), 0);
      assert.equal(await page.evaluate(() => S.grading.pointer.report_id), generations[0].pointer.report_id);
      assert.equal(await page.evaluate(() => localStorage.getItem('nflprops.mine')), storage);
    }
    cors='allowed';corrupt=false; await page.reload();await page.waitForSelector('[data-performance-primary]');
    assert.equal(await page.evaluate(() => S.grading.pointer.report_id), generations[3].pointer.report_id);
    assert.equal(await page.evaluate(() => localStorage.getItem('nflprops.mine')), storage);
    await page.evaluate(async () => { window.originalReportDecoder=DecompressionStream; window.DecompressionStream=undefined; await loadGrading(); S.tab='record';render(); });
    assert.equal(await page.evaluate(() => S.grading),null);
    assert.match(await page.locator('#selection-grading').innerText(), /decoder unavailable/);
    assert.equal(await page.evaluate(() => localStorage.getItem('nflprops.mine')), storage);
    await page.evaluate(async () => { window.DecompressionStream=window.originalReportDecoder;await loadGrading();render(); });
    await page.waitForSelector('[data-performance-primary]');
    assert.ok(archiveRequests.length < 20, 'archive lookup has bounded attempts');
    return { fictional_git_refs: generations.map(v=>v.git_ref), older_report_ref: generations[0].git_ref,
      archive_requests: archiveRequests, decoder_unavailable_preserves_mypicks: true, all_checks:'passed', public_archive_uploaded:false };
  } finally { fixture=savedFixture;variant=savedVariant;await context.close(); /* Preserve committed fictional archive for evidence. */ }
}

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ executablePath: process.env.NFL_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const measurements = [];
  const presentation = [];
  try {
    for (const width of [1280, 390, 320]) {
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
      await page.waitForFunction(() => S.grading && !S.grading.partLoading);
      const loadMs = Date.now() - start;
      if (!arg('--root')) {
        assert.equal(await page.evaluate(() => S.grading.parts.size), 1, 'only selected exact-context summary initially loaded');
        assert.equal(await page.evaluate(() => [...S.finalOutcomes.values()].every(row => row.week === 6)), true, 'historical outcomes cannot settle current picks');
        assert.equal(requests.includes('/data/selection-grading/' + fixture.periods[0].path), false, 'unneeded historical outcomes are not prefetched');
      }
      assert.equal(await page.locator('[data-grading-row]').count(), 0, 'rows load only after drill-down');
      const chunkRequestsBefore = requests.filter(request => /\/rows(?:-[0-9]{4})?\.json$/.test(request)).length;
      await page.locator('[data-grading-group]').first().click();
      await page.waitForSelector('[data-grading-row]');
      assert.ok(requests.filter(request => /\/rows(?:-[0-9]{4})?\.json$/.test(request)).length - chunkRequestsBefore <= 4, 'one interaction reads at most four bounded chunks');
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
        await page.getByLabel('Supporting breakdown', { exact: true }).selectOption('category_side');
        assert.equal(await page.locator('[data-grading-summary]').count(), 10);
        await page.getByLabel('Cohort', { exact: true }).selectOption('non_top_at_all_lean_decision');
        await page.waitForFunction(() => !S.grading.partLoading);
        assert.ok((await page.locator('[data-grading-summary]').count()) > 0);
        await page.getByLabel('Supporting breakdown', { exact: true }).selectOption('overall');
        await page.locator('[data-grading-group]').first().click();
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
        for (const failure of ['oversized-pointer', 'missing-summary-part', 'missing-outcome-part']) {
          variant = failure; await page.reload(); await page.waitForFunction(() => !ticking);
          assert.match(await page.locator('#selection-grading').innerText(), /unavailable|size limit/i, failure);
          assert.equal(await page.locator('[data-performance-headline]').count(), 0, 'no substitute totals on failed selected assets');
          if (failure !== 'missing-summary-part') assert.equal(await page.evaluate(() => S.finalOutcomes.size), 0, 'required outcome failure remains unknown');
        }
        variant = 'outer-http-gzip'; await page.reload(); await page.waitForSelector('[data-performance-primary]');
        assert.equal(await page.evaluate(() => S.grading.pointer.schema_version), 'selection-publication-pointer-v4', 'HTTP outer coding removes only transport layer');
        variant = 'wrong-http-coding'; await page.reload(); await page.waitForFunction(() => !ticking);
        assert.equal(await page.evaluate(() => S.grading), null, 'HTTP-decoded application representation cannot satisfy encoded identity');
        assert.match(await page.locator('#selection-grading').innerText(), /unavailable|size|checksum/i);
        variant = 'legacy-gzip'; await page.reload(); await page.waitForSelector('[data-performance-primary]');
        assert.equal(await page.evaluate(() => S.grading.pointer.schema_version), 'selection-publication-pointer-v3', 'retained gzip reader');
        variant = 'plain-partitioned'; await page.reload(); await page.waitForSelector('[data-performance-primary]');
        assert.equal(await page.evaluate(() => S.grading.pointer.schema_version), 'selection-publication-pointer-v2', 'retained plain partition reader');
        variant = 'legacy'; await page.reload(); await page.waitForSelector('[data-performance-primary]');
        assert.equal(await page.evaluate(() => S.grading.partitioned), false, 'explicit retained legacy reader');
        variant = 'valid'; await page.reload(); await page.waitForSelector('[data-performance-primary]');
        await page.waitForFunction(() => !S.grading.partLoading);
        const initialRequestCount = requests.length;
        await page.getByLabel('Reporting period', { exact: true }).selectOption('2026-w06');
        await page.waitForFunction(() => !S.grading.partLoading);
        assert.equal(await page.evaluate(() => S.grading.summary.summary.tables.every(t => t.period === '2026-w06')), true);
        assert.equal(requests.slice(initialRequestCount).filter(p => /summary.json$/.test(p)).length, 1);
        // Delay source A, select source B, and complete A last. Old totals must not win.
        await page.evaluate(async () => {
          const original = checkedGradingAsset, grading = S.grading;
          let release, started;
          const waiting = new Promise(resolve => { started = resolve; });
          checkedGradingAsset = async function(...args) {
            if (args[1].context_id && grading.index.contexts[args[1].context_id].line_source_scope === 'dk') {
              started(); await new Promise(resolve => { release = resolve; });
            }
            return original(...args);
          };
          S.gradingFilters.line_source_scope = 'dk'; const old = loadSelectedGradingSummary(); await waiting;
          S.gradingFilters.line_source_scope = 'sleeper'; await loadSelectedGradingSummary();
          release(); await old; checkedGradingAsset = original; renderRecord();
        });
        assert.equal(await page.evaluate(() => S.grading.summary.summary.tables.every(t => t.line_source_scope === 'sleeper')), true, 'delayed context cannot overwrite selected totals');
        // A delayed failed old publication cannot clear a subsequently loaded good one.
        await page.evaluate(async () => {
          const original = fetch; let release, started;
          const waiting = new Promise(resolve => { started = resolve; }); let intercept = true;
          window.fetch = async function(url, ...args) {
            if (intercept && String(url).endsWith('selection-grading/latest.json')) {
              intercept = false; started(); await new Promise(resolve => { release = resolve; }); throw Error('old-generation failure');
            }
            return original(url, ...args);
          };
          const old = loadGrading(); await waiting; await loadGrading(); release(); await old; window.fetch = original; renderRecord();
        });
        assert.equal(await page.evaluate(() => S.grading?.partitioned), true, 'old generation failure cannot clear new publication');
        assert.equal(await page.evaluate(() => S.gradingError), null);
        for (const kind of ['scope-valid', 'scope-packaged', 'scope-packaged-v2', 'scope-packaged-mixed-capture', 'scope-mixed-board', 'scope-mixed-report', 'scope-malformed']) {
          variant = kind; await page.reload(); await page.waitForSelector('[data-performance-primary]');
          assert.equal(await page.evaluate(() => S.verificationScope !== null), ['scope-valid','scope-packaged','scope-packaged-v2'].includes(kind), kind + ' generation binding');
          const label = await page.locator('[data-verification-scope]').innerText();
          assert.match(label, ['scope-valid','scope-packaged','scope-packaged-v2'].includes(kind) ? /Partial-week original-model-input reproduction only/ : /unavailable or legacy/);
        }
      }
      await context.close();
      if (!arg('--root')) {
        variant = 'valid';
        presentation.push(await presentationChecks(browser, origin, width));
      }
    }
    const hosting = !arg('--root') ? await archiveAndDecoderChecks(browser, origin) : null;
    const result = { hosting, fixture: arg('--root') ? 'AUTHORIZED_SAVED_DATA_ISOLATED_ROOT' : 'FICTIONAL_ONLY', public_deployment_test: false,
      external_network_requests: 0, app_sha256: sha(fs.readFileSync(path.join(staticRoot, 'app.js'))),
      html_sha256: sha(fs.readFileSync(path.join(staticRoot, 'index.html'))), measurements, presentation, requests: [...new Set(requests)], assertions: 'passed' };
    if (evidence) fs.writeFileSync(path.join(evidence, 'grading-browser-results.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => server.close());
