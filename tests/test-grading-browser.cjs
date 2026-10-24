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
function fictionalWeeklyAssets(current) {
  const hash=sha(encode(current)),identity=sha('FICTIONAL_WEEKLY_BROWSER_ONLY');
  const player=current.players[0],game=current.games.find(g=>g.id===player.game_id);
  const row={player_id:player.id,game_id:game.id,category:'rec',method_id:'FICTIONAL_BROWSER_CONTROL',
    model_version:identity,procedure_version:identity,product:'point_mean',prediction_functional:'expected_mean',forecast_value:5.25,
    horizon:'player_game',source_cutoff_utc:'2026-10-14T09:00:00Z',issued_at:'2026-10-14T08:00:00Z',
    persistence_completed_at:'2026-10-14T08:01:00Z',kickoff_utc:game.kickoff,valid_until_utc:game.kickoff,
    selection_sha256:identity,source_policy_sha256:identity,query_source_sha256:identity,first_prepared_at:'2026-10-14T10:00:00Z'};
  const doc={schema_version:'weekly-adaptive-public-overlay-v1',registration_id:'weekly-adaptive-release-v1',
    state:variant==='weekly-disabled'?'DISABLED_USE_R0':'PROVISIONAL',season:current.season,week:current.week,
    canonical_board_sha256:hash,display_board_sha256:hash,board_contract_sha256:identity,
    prepared_at:'2026-10-14T10:00:00Z',packaged_at:'2026-10-14T10:00:00Z',website_source_sha:'7'.repeat(40),
    publication_review_sha256:identity,rows:variant==='weekly-disabled'?[]:[row],frozen_rows:[],fallback_counts:{}};
  const body=encode(doc),pointer={schema_version:'weekly-adaptive-overlay-pointer-v1',path:'data/weekly-adaptive/'+sha(body)+'.json',
    sha256:sha(body),bytes:body.length,display_board_sha256:variant==='weekly-wrong-board'?'0'.repeat(64):hash};
  return {body,pointer};
}
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  requests.push(pathname);
  let bytes;
  if (!arg('--root')) {
    if(pathname==='/data/weekly-adaptive-overlay.json'||pathname.startsWith('/data/weekly-adaptive/')){
      if(!variant.startsWith('weekly-')||variant==='weekly-missing'){res.writeHead(404);res.end();return;}
      const saved=fictionalWeeklyAssets(week);
      if(pathname==='/data/weekly-adaptive-overlay.json')bytes=encode(saved.pointer);
      else if(pathname==='/'+saved.pointer.path){bytes=Buffer.from(saved.body);if(variant==='weekly-corrupt')bytes[0]^=1;}
      if(!bytes){res.writeHead(404);res.end();return;}
    }
    else if (pathname === '/data/week.json') bytes = encode(variant === 'scope-mixed-board' ? { ...week, generated_at: '2026-10-15T11:00:00Z' } : week);
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

async function weeklyDisplayChecks(browser,origin) {
  if(arg('--root'))return {status:'NOT_RUN_USE_ACTUAL_RELEASE_BROWSER_FOR_GENERATED_ROOT'};
  const savedVariant=variant,savedWeek=week,savedFixture=fixture,results=[];
  try{
    week=fictionalWeek();fixture=gzipPublication(partitionedPublication(fictionalPublication('weekly-display')));
    for(const width of [1280,390,320]){
      const context=await browser.newContext({viewport:{width,height:width===390?844:900},serviceWorkers:'block'});
      await context.route('**/*',route=>route.request().url().startsWith(origin+'/')?route.continue():route.fulfill({status:200,contentType:'application/json',body:route.request().url().includes('/stats')?'[]':'{"events":[]}'}));
      const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
      try{
        let originalBoard=null,originalPicks=null,originalGrade=null;
        const mine='[{"pid":"fixture-0","key":"rec","dir":"over","line":4.5,"season":2026,"week":6,"at":1}]';
        for(const state of ['weekly-valid','weekly-missing','weekly-corrupt','weekly-wrong-board','weekly-disabled']){
          variant=state;if(state==='weekly-valid')await page.goto(origin+'/#/props');else await page.reload();
          await page.waitForFunction(()=>S.data&&S.weeklyOverlayReady&&typeof WeeklyAdaptiveOverlay?.load==='function');
          if(state==='weekly-valid'||state==='weekly-disabled')await page.waitForFunction(()=>S.weeklyOverlay!==null);
          else assert.equal(await page.evaluate(async()=>await WeeklyAdaptiveOverlay.load(S.data,S.weeklyOverlayBoardHash)),null);
          if(state==='weekly-valid')await page.evaluate(bytes=>localStorage.setItem('nflprops.mine',bytes),mine);
          const actual=await page.evaluate(()=>{
            const p=S.byId['fixture-0'],prop=p.props.find(v=>v.key==='rec'),selected=selectedPropForecast(p,'rec');
            const template=document.createElement('template');template.innerHTML=catCard(p,prop);
            return {selected,primary:template.content.querySelector('[data-weekly-primary]')?.textContent||null,
              component_text:template.content.textContent,visible:document.querySelectorAll('[data-weekly-primary]').length,
              board:JSON.stringify(S.data),picks:JSON.stringify(S.data.picks),grade:JSON.stringify(propStatus(p,'rec',prop.line,'over')),
              mine:localStorage.getItem('nflprops.mine'),state:S.weeklyOverlay?.state||null};
          });
          if(state==='weekly-valid'){
            assert.equal(actual.selected.value,5.25);assert.match(actual.primary,/Frozen provisional mean forecast\s*5\.25/);
            assert.match(actual.component_text,/Current reference forecast/);assert.match(actual.component_text,/Lines, leans, ranking and saved selections use the reference model/);
            assert.ok(actual.visible>0,'Actual Props includes selected primary chip');
            originalBoard=actual.board;originalPicks=actual.picks;originalGrade=actual.grade;
          }else{
            assert.equal(actual.selected,null);assert.equal(actual.primary,null);assert.equal(actual.visible,0);
            assert.equal(actual.state,state==='weekly-disabled'?'DISABLED_USE_R0':null);
          }
          assert.equal(actual.board,originalBoard);assert.equal(actual.picks,originalPicks);assert.equal(actual.grade,originalGrade);
          assert.equal(actual.mine,mine);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth)<=width+1);
          results.push({width,state,selected_rows:state==='weekly-valid'?1:0,reference_and_saved_results_unchanged:true});
        }
        assert.deepEqual(errors,[]);
      }finally{await context.close();}
    }
    return {status:'PASS_FICTIONAL_OPTIONAL_DISPLAY_CONTROLS',cases:results,provider_requests:0,
      qualified_selected_feed:false,disclosure:'Fictional consumer controls, not production forecast or predictive evidence.'};
  }finally{variant=savedVariant;week=savedWeek;fixture=savedFixture;}
}

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
    const presence = await page.evaluate(() => {
      const unknown = {rec: null, rec_yd: 20}, negative = {rush_yd: -2, fum_lost: 1};
      const partial = {rec: 2.5, _presence: {version:'nfl-data-presence-v2',kind:'projection'}};
      const player = {...S.byId['fixture-3'], proj: partial};
      const before = JSON.stringify(S.mine), settings = S.sc;
      S.sc = {mode:'espn',half:false};
      const adjusted = pv(player, player.props.find(p => p.key === 'fpts')).adj;
      S.sc = settings;
      return {tdMissing:tdChanceText({td_chance:null}),tdZero:tdChanceText({td_chance:0}),
        pprMissing:ppr(unknown),pprNegative:ppr(negative),pprZero:ppr({rec:0}),
        partialKnown:offensiveComponentsKnown(partial,['rec']),partialUnknown:offensiveComponentsKnown(partial,['rush_yd']),
        adjusted,picksIntact:JSON.stringify(S.mine)===before};
    });
    equal(presence, {tdMissing:'Unavailable',tdZero:'0%',pprMissing:null,pprNegative:-2.2,pprZero:0,
      partialKnown:true,partialUnknown:false,adjusted:null,picksIntact:true}, 'presence-aware PPR/TD and custom scoring preserve unknowns and saved picks');
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

// Proposed insertion into tests/test-grading-browser.cjs, before its final IIFE.
// Uses that file's existing server, fictionalPublication, partitionedPublication,
// gzipPublication, sha/encode, fixture/week/variant variables and Chromium.
// This is fictional browser transport. It does not certify capture qualification,
// independently timestamped selections, offered entries or predictive performance.
const PAPER_TEST_START = '2026-11-01T10:00:00Z';
const PAPER_TEST_KICKOFF = '2026-11-02T18:00:00Z';
const PAPER_TEST_FINAL = '2026-11-04T10:00:00Z';
const PAPER_TEST_CORRECTION = '2026-11-04T11:00:00Z';

function paperBrowserWeek() {
  const value = fictionalWeek(), template = structuredClone(value.players[0]);
  const prop = structuredClone(template.props[0]);
  value.generated_at = PAPER_TEST_START;
  value.games = Array.from({ length: 10 }, (_, i) => ({
    id: 'paper-game-' + i, home: 'AAA', away: 'BBB', kickoff: PAPER_TEST_KICKOFF,
    state: 'pre', detail: 'Scheduled', home_score: null, away_score: null,
  }));
  value.players = Array.from({ length: 11 }, (_, i) => {
    const source = i >= 8 && i < 10 ? 'sleeper' : 'dk';
    const side = [1, 3, 5, 6, 9].includes(i) ? 'under' : 'over';
    const line = [2, 3].includes(i) ? 4 : 5.5;
    return { ...structuredClone(template), id: 'paper-player-' + i,
      name: 'FICTIONAL paper player ' + i, game_id: 'paper-game-' + (i === 10 ? 0 : i),
      team: 'AAA', opp: 'BBB', injury: null, inj: null, late: false, actual: null,
      props: [
        { ...structuredClone(prop), key: 'rec', line, line_from: source, sleeper: source==='sleeper'?{line,over:1.8,under:1.8}:undefined, proj: side === 'over' ? 7 : 4,
          adj: side === 'over' ? line + 2.5 : line - 2.5, lean: side },
        { ...structuredClone(prop), key: 'rec_yd', line: 40.5, line_from: source, sleeper:source==='sleeper'?{line:40.5,over:1.8,under:1.8}:undefined, proj: side === 'over' ? 55 : 30,
          adj: side === 'over' ? 60 : 20, lean: side },
      ],
    };
  });
  value.picks = { over: [], under: [] };
  return value;
}

function paperBrowserPublication(stage) {
  const value = fictionalPublication('PAPER_BROWSER_COMMON_INPUT_NOT_CAPTURE_PROOF');
  const observed = stage === 'pre' ? PAPER_TEST_START : stage === 'correction' ? PAPER_TEST_CORRECTION : PAPER_TEST_FINAL;
  const finalRows = paperBrowserWeek().players.map((player, i) => {
    const status = stage === 'pre' ? 'pending' : i === 3 ? 'dnp' : i === 4 || i === 7 ? 'unresolved' : i === 5 ? 'pending' : 'resolved';
    const confirmed = ['resolved', 'dnp'].includes(status), corrected = stage === 'correction' && i === 0;
    const tag = corrected ? 'paper-corrected-final-0' : 'paper-original-final-' + i;
    const actual = status !== 'resolved' ? null : i === 0 ? (corrected ? 3 : 8) : i === 2 ? 4 : i === 6 ? 0 : [1, 9].includes(i) ? 3 : 8;
    return { season: 2026, week: 6, player_id: player.id, game_id: player.game_id, category: 'rec', team: player.team,
      kickoff: PAPER_TEST_KICKOFF, status, actual, final_confirmed: confirmed,
      outcome_conflict: stage !== 'pre' && i === 7, game_state: stage === 'pre' ? 'pre' : 'post',
      outcome_selection: confirmed ? 'confirmed' : i === 7 && stage !== 'pre' ? 'conflict' : 'incomplete_observation',
      outcome_snapshot_sha256: confirmed ? sha(tag + '-snapshot') : null,
      selected_outcome_provenance_sha256: confirmed ? sha(tag + '-provenance') : null,
      selected_outcome_row_sha256: confirmed ? sha(tag + '-row') : null,
      reason: i === 7 && stage !== 'pre' ? 'conflicting_sources' : confirmed ? null : 'awaiting_saved_final',
      outcome_provenance: 'recorded_outcome_receipt', outcome_source_mix: i === 7 && stage !== 'pre' ? 'conflicting_sources' : 'single_source',
      outcome_identity_status: 'bound_to_recorded_game', collected_at: corrected ? PAPER_TEST_CORRECTION : stage === 'pre' ? PAPER_TEST_START : PAPER_TEST_FINAL };
  });
  value.finals = finalRows;
  value.pointer.generated_at = observed;
  const originalOutcomeBytes = encode({ schema_version: 'selection-final-outcomes-v1', report_id: value.pointer.report_id, outcomes: finalRows });
  value.pointer.outcomes = { ...value.pointer.outcomes, sha256: sha(originalOutcomeBytes) };
  value.assets.set('/data/selection-grading/' + value.pointer.outcomes.path, originalOutcomeBytes);
  const plain = partitionedPublication(value);
  const put = payload => {
    const bytes = encode({ ...payload, report_id: plain.pointer.report_id }), digest = sha(bytes);
    const descriptor = { path: digest + '/outcomes.json', sha256: digest, decoded_bytes: bytes.length };
    plain.assets.set('/data/selection-grading/' + descriptor.path, bytes);
    return descriptor;
  };
  // An intentionally different current-period value is a negative cross-period
  // join control. It must never settle this saved Week6 ticket.
  const currentRows = finalRows.map((row, i) => ({ ...row, week: 7,
    actual: row.status === 'resolved' ? 99 : null,
    outcome_snapshot_sha256: row.final_confirmed ? sha('paper-week7-snapshot-' + i) : null,
    selected_outcome_provenance_sha256: row.final_confirmed ? sha('paper-week7-provenance-' + i) : null,
    selected_outcome_row_sha256: row.final_confirmed ? sha('paper-week7-row-' + i) : null,
    collected_at: stage === 'pre' ? PAPER_TEST_START : PAPER_TEST_FINAL }));
  const periods = [6, 7].map(weekNumber => {
    const outcomes = weekNumber === 6 ? finalRows : currentRows;
    return { ...put({ schema_version: 'selection-final-outcome-period-v1', season: 2026, week: weekNumber, outcomes }),
      season: 2026, week: weekNumber, count: outcomes.length };
  });
  plain.pointer.outcomes = put({ schema_version: 'selection-final-outcome-index-v1', outcome_count: finalRows.length + currentRows.length, periods });
  plain.pointer.generated_at = observed;
  return gzipPublication(plain, 'paper-browser-' + stage);
}

async function paperBuilderChecks(browser, origin) {
  if (arg('--root')) return { skipped: 'Saved release roots are not replaced by fictional browser inputs.' };
  const savedFixture = fixture, savedWeek = week, savedVariant = variant;
  const publications = Object.fromEntries(['pre', 'final', 'correction'].map(stage => [stage, paperBrowserPublication(stage)]));
  const output = [];
  try {
    for (const width of [1280, 390, 320]) {
      fixture = publications.pre; week = paperBrowserWeek(); variant = 'valid';
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const requestsMade = [], pageErrors = [], checks = [];
      await context.route('**/*', route => {
        const request = route.request(), url = request.url();
        requestsMade.push({ method: request.method(), own: url.startsWith(origin + '/'), url });
        if (url.startsWith(origin + '/')) return route.continue();
        return route.fulfill({ status: 200, contentType: 'application/json', body: url.includes('api.sleeper.app/stats') ? '[]' : '{"events":[]}' });
      });
      const page = await context.newPage();
      page.on('pageerror', error => pageErrors.push(error.message));
      await page.clock.install({ time: new Date(PAPER_TEST_START) });
      const check = (condition, description) => { assert.ok(condition, description); checks.push(description); };
      const equal = (actual, expected, description) => { assert.deepEqual(actual, expected, description); checks.push(description); };
      const records = () => page.evaluate(() => Object.fromEntries(Object.keys(localStorage).filter(k => k.startsWith(PAPER_PREFIX)).sort().map(k => [k, localStorage.getItem(k)])));
      const add = async (id, category = 'rec') => {
        const payload = await page.locator('[data-paper-add]').evaluateAll((buttons, value) => {
          const element = buttons.find(button => { const leg = JSON.parse(button.dataset.paperAdd); return leg.player_id === value.id && leg.category === value.category; });
          return element?.dataset.paperAdd || null;
        }, { id, category });
        assert.ok(payload, 'fictional candidate exists: ' + id + '/' + category);
        await page.locator('[data-paper-add]').filter({ hasText: 'Add leg' }).evaluateAll((buttons, value) => {
          const element = buttons.find(button => button.dataset.paperAdd === value);
          if (!element) throw new Error('Rendered exact leg disappeared');
          element.click();
        }, payload);
      };
      const newDraft = () => page.locator('[data-paper-new]').click();
      const open = key => page.locator('[data-paper-open]').evaluateAll((buttons, value) => {
        const button = buttons.find(button => button.dataset.paperOpen === value);
        if (!button) throw new Error('Saved revision missing'); button.click();
      }, key);
      const save = async ids => {
        await newDraft();
        await page.locator('[data-paper-filter=source]').selectOption('dk');
        await page.locator('[data-paper-filter=sides]').selectOption('mixed');
        await page.locator('[data-paper-filter=game]').selectOption('');
        await page.locator('[data-paper-category=rec]').check();
        for (const id of ids) await add('paper-player-' + id);
        await page.locator('[data-paper-save]').click();
        await page.waitForFunction(() => S.paper.opened && S.paper.error.includes('Saved and read back'));
        return page.evaluate(() => ({ key: PAPER_PREFIX + S.paper.opened.ticket_id + '.' + S.paper.opened.revision_id, ticket: S.paper.opened }));
      };
      try {
        await page.goto(origin + '/#/parlay');
        await page.waitForSelector('[data-paper-suggest]');
        await page.waitForFunction(() => S.grading && !S.grading.partLoading && !ticking);
        await page.evaluate(() => localStorage.setItem('nflprops.mine', '[{"private":"preserve this exact value"}]'));
        const mine = await page.evaluate(() => localStorage.getItem('nflprops.mine'));
        equal(await page.evaluate(() => S.tab), 'parlay', 'deep link opens actual builder');
        equal(await page.evaluate(() => readPaperTickets().tickets.length), 0, 'new profile has no invented tickets');
        await page.locator('[data-paper-category=rec]').check();
        await page.locator('[data-paper-filter=sides]').selectOption('over');
        check(await page.evaluate(() => paperCandidates().length && paperCandidates().every(v => v.leg.category === 'rec' && v.leg.side === 'over' && v.leg.line_source === 'dk')), 'single category/Over/source controls reach actual candidates');
        await page.locator('[data-paper-filter=sides]').selectOption('under');
        check(await page.evaluate(() => paperCandidates().length && paperCandidates().every(v => v.leg.side === 'under')), 'Under-only has genuine under candidates');
        await page.locator('[data-paper-filter=sides]').selectOption('mixed');
        await page.locator('[data-paper-category=rec_yd]').check();
        equal(await page.evaluate(() => [...new Set(paperCandidates().map(v => v.leg.category))].sort()), ['rec', 'rec_yd'], 'multiple categories supported');
        await add('paper-player-0');
        check(await page.locator('[data-paper-save]').isDisabled(), 'one leg cannot be saved');
        await add('paper-player-0', 'rec_yd');
        equal(await page.evaluate(() => S.paper.legs.length), 1, 'repeat player rejected');
        await add('paper-player-10');
        equal(await page.evaluate(() => S.paper.legs.length), 1, 'different player in same game rejected');
        await page.locator('[data-paper-filter=source]').selectOption('sleeper');
        await add('paper-player-8');
        equal(await page.evaluate(() => S.paper.legs.length), 1, 'DK and Sleeper legs cannot mix');
        await newDraft(); await page.locator('[data-paper-filter=source]').selectOption('dk');
        await page.locator('[data-paper-filter=game]').selectOption('paper-game-0');
        await page.locator('[data-paper-suggest]').click();
        equal(await page.evaluate(() => S.paper.legs.length), 1, 'restricted single game does not force two legs');
        check((await page.locator('#main').innerText()).includes('NO_ACTION'), 'insufficient compatible population is NO_ACTION');
        await newDraft(); await page.locator('[data-paper-filter=game]').selectOption('');
        await page.locator('[data-paper-category=rec_yd]').uncheck();
        const exactTarget = await page.locator('[data-paper-add]').evaluateAll(buttons => buttons.map(b => b.dataset.paperAdd).find(v => JSON.parse(v).player_id === 'paper-player-4'));
        await page.evaluate(() => { S.games['paper-game-0'].state = 'post'; });
        await page.locator('[data-paper-add]').evaluateAll((buttons, value) => buttons.find(b => b.dataset.paperAdd === value).click(), exactTarget);
        equal(await page.evaluate(() => S.paper.legs[0].player_id), 'paper-player-4', 'a stale displayed position never substitutes another leg');
        await page.evaluate(() => { S.games['paper-game-0'].state = 'pre'; S.games['paper-game-4'].kickoff = '2026-11-03T18:00:00Z'; });
        check(await page.evaluate(() => !paperCandidates().some(v => v.leg.player_id === 'paper-player-4')), 'changed live schedule cannot relabel original board');
        await page.evaluate(() => { S.games['paper-game-4'].kickoff = S.data.games.find(g => g.id === 'paper-game-4').kickoff; S.injNews['paper-player-4'] = { status: 'Out' }; });
        check(await page.evaluate(() => !paperCandidates().some(v => v.leg.player_id === 'paper-player-4')), 'new existing inactive evidence blocks a new leg');
        await page.evaluate(() => { delete S.injNews['paper-player-4']; });

        const original = await save([0, 1]);
        const originalBytes = (await records())[original.key];
        equal(original.ticket.legs.map(v => [v.player_id, v.line, v.side]), [['paper-player-0', 5.5, 'over'], ['paper-player-1', 5.5, 'under']], 'actual UI freezes requested exact contracts');
        await page.reload(); await page.waitForSelector('[data-paper-open]');
        equal((await records())[original.key], originalBytes, 'reload preserves original exact bytes');
        await open(original.key); await page.waitForFunction(() => S.paper.results);
        equal(await page.evaluate(() => S.paper.results.map(r => r.status)), ['pending', 'pending'], 'pregame pending evidence stays pending');
        await page.locator('[data-paper-remove="1"]').click(); await add('paper-player-2');
        await page.locator('[data-paper-save]').click();
        await page.waitForFunction(id => S.paper.opened && S.paper.opened.parent_revision_id === id, original.ticket.revision_id);
        const revision = await page.evaluate(() => structuredClone(S.paper.opened));
        equal(revision.ticket_id, original.ticket.ticket_id, 'revision retains logical ticket');
        check(revision.revision_id !== original.ticket.revision_id, 'revision receives a new identity');
        equal((await records())[original.key], originalBytes, 'revision never overwrites original membership');
        const pushed = await save([2, 3]), incomplete = await save([4, 5]), zero = await save([6, 7]);
        await save([0, 1, 2, 3, 4, 5]);
        await add('paper-player-6');
        equal(await page.evaluate(() => S.paper.legs.length), 6, 'seventh leg cannot enter saved draft');
        await newDraft(); await page.locator('[data-paper-filter=source]').selectOption('sleeper');
        await add('paper-player-8'); await add('paper-player-9'); await page.locator('[data-paper-save]').click();
        check(await page.evaluate(() => S.paper.opened.line_source === 'sleeper' && S.paper.opened.legs.every(l => l.line_source === 'sleeper')), 'same-source Sleeper paper ticket saves');
        const beforeQuota = await records();
        await newDraft(); await page.locator('[data-paper-filter=source]').selectOption('dk');
        await add('paper-player-0'); await add('paper-player-1');
        await page.evaluate(() => { window.paperOriginalSetItem = Storage.prototype.setItem; Storage.prototype.setItem = function(key, value) { if (key.startsWith(PAPER_PREFIX)) throw new DOMException('FICTIONAL quota control', 'QuotaExceededError'); return window.paperOriginalSetItem.call(this, key, value); }; });
        await page.locator('[data-paper-save]').click();
        check((await page.locator('#main').innerText()).includes('Not saved:'), 'storage quota failure is explicit');
        await page.evaluate(() => { Storage.prototype.setItem = window.paperOriginalSetItem; delete window.paperOriginalSetItem; });
        equal(await records(), beforeQuota, 'quota failure retains all saved records');

        // Future final/correction publication transport is separately identified.
        // Week7 carries deliberately different numbers as the negative join control.
        fixture = publications.final; week = paperBrowserWeek(); week.week = 7; week.generated_at = PAPER_TEST_FINAL;
        week.games = week.games.map(g => ({ ...g, state: 'post', detail: 'Final' }));
        await page.clock.setFixedTime(new Date(PAPER_TEST_FINAL));
        await page.reload(); await page.waitForSelector('[data-paper-open]');
        await page.waitForFunction(() => S.grading && [...S.finalOutcomes.values()].every(row => row.week === 7));
        await open(original.key); await page.waitForFunction(() => S.paper.results);
        equal(await page.evaluate(() => S.paper.results.map(r => [r.status, r.actual])), [['win', 8], ['win', 3]], 'saved Week6 ticket cannot borrow Week7 actual99');
        await open(pushed.key); await page.waitForFunction(() => S.paper.results);
        equal(await page.evaluate(() => S.paper.results.map(r => r.status)), ['push', 'dnp'], 'integer push and confirmed DNP remain distinct');
        await open(incomplete.key); await page.waitForFunction(() => S.paper.results);
        equal(await page.evaluate(() => S.paper.results.map(r => r.status)), ['unresolved', 'pending'], 'missing and pending are distinct');
        await open(zero.key); await page.waitForFunction(() => S.paper.results);
        equal(await page.evaluate(() => S.paper.results.map(r => [r.status, r.actual])), [['win', 0], ['unresolved', null]], 'played zero is scored; conflicting evidence is not');
        await page.locator('[data-paper-evaluate]').click(); await page.waitForFunction(() => S.paper.history);
        equal(await page.evaluate(() => S.paper.history.rows.filter(r => r.ticket.parent_revision_id === null && r.ticket.legs.length === 2).length), 5, 'five actual first-saved2-leg tickets, not reconstructed combinations');
        equal(await page.evaluate(() => S.paper.history.rows.filter(r => r.ticket.parent_revision_id === null && r.ticket.legs.length === 6).length), 1, 'six-leg ticket is separately counted');
        check((await page.locator('[data-paper-performance]').innerText()).includes('Financial ROI and venue settlement unavailable'), 'performance does not invent financial return');

        fixture = publications.correction;
        await page.clock.setFixedTime(new Date(PAPER_TEST_CORRECTION));
        await page.evaluate(async () => { await loadGrading(); });
        await open(original.key); await page.waitForFunction(() => S.paper.results);
        equal(await page.evaluate(() => S.paper.results.map(r => [r.status, r.actual])), [['loss', 3], ['win', 3]], 'later correction changes grade without changing membership');
        equal((await records())[original.key], originalBytes, 'correction preserves original saved selection bytes');
        await page.evaluate(() => { localStorage.setItem(PAPER_PREFIX + 'defective-record', '{broken'); renderParlay(); });
        check((await page.locator('#main').innerText()).includes('original bytes were preserved'), 'corrupt private record is individually quarantined');
        equal((await records())[original.key], originalBytes, 'corrupt record does not overwrite valid ticket');
        equal(await page.evaluate(() => localStorage.getItem(PAPER_PREFIX + 'defective-record')), '{broken', 'defective original bytes retained');
        equal(await page.evaluate(() => localStorage.getItem('nflprops.mine')), mine, 'My Picks bytes never change');
        equal(requestsMade.filter(r => r.method !== 'GET').length, 0, 'ticket saves/evaluation create no network write');
        equal(await page.evaluate(() => document.documentElement.scrollWidth), width, 'entire builder stays within viewport');
        equal(pageErrors, [], 'no browser page errors');
        if (evidence) await page.screenshot({ path: path.join(evidence, 'paper-builder-' + width + '.png'), fullPage: true });
        output.push({ width, checks: checks.length, descriptions: checks, original_ticket: sha(originalBytes),
          source: 'FICTIONAL_BROWSER_TRANSPORT', capture_qualification_exercised: false,
          provider_requests: 0, owner_device_accessed: false, physical_device: false });
      } finally { await context.close(); }
    }
  } finally { fixture = savedFixture; week = savedWeek; variant = savedVariant; }
  return output;
}


// Modern report transport controls. The aggregate is produced by the real
// projector once from wholly fictional evaluator observations; this exercises
// the actual browser reader/UI, not capture qualification or provider proof.
function modernBrowserAccuracy() {
  const script = String.raw`
import json, sys
from pathlib import Path
sys.path[:0] = [str(Path.cwd() / 'tests'), str(Path.cwd() / 'tools'), str(Path.cwd() / 'pull')]
from test_accuracy_publication import observation, evaluation
from accuracy_publication import project_accuracy, validate_accuracy
import data_integrity_v2 as corrected
categories = ['pass_yd','pass_td','pass_cmp','pass_att','pass_int','rush_yd','rush_att','rec','rec_yd','rush_rec_yd','fpts']
rows = [observation('fictional-browser-' + key, key, actual=0 if key != 'rush_yd' else -2, raw=2, adjusted=1) for key in categories]
next(r for r in rows if r['category'] == 'fpts')['provider_ppr'] = 3
rows.append(observation('fictional-browser-pending', status='pending'))
rows.append(observation('fictional-browser-saved-cache', provenance='saved_cache_descriptive_regrade'))
td0 = observation('fictional-browser-td-zero', 'anytime_td', actual=1, raw=.5, adjusted=None)
td0.update(probability=0, probability_provenance='originally_recorded_probability')
td1 = observation('fictional-browser-td-rederived', 'anytime_td', actual=0, raw=.2, adjusted=None)
td1.update(probability=.25, probability_provenance='rederived_from_original_count_retained_formula')
rows += [td0, td1]
modern = observation('fictional-browser-corrected', model=corrected.MODEL)
value = project_accuracy([evaluation(rows, td=[td0, td1]), evaluation([modern], model=corrected.MODEL)])
validate_accuracy(value)
print(json.dumps(value, sort_keys=True, separators=(',', ':')))
`;
  const aggregate = JSON.parse(cp.execFileSync(process.env.NFL_PYTHON_PATH || 'python3', ['-c', script], { cwd: repo, encoding: 'utf8', maxBuffer: 1024 * 1024 }));
  const bytes = JSON.stringify(aggregate);
  assert.doesNotMatch(bytes, /PRIVATE_CANARY|unapproved\/private|player_id|fictional-browser-/, 'public projection contains no rich player records or private evaluator canaries');
  return aggregate;
}

function modernPublication(aggregate, mutation = null) {
  const old = fictionalPublication('modern-browser');
  // Exact membership is retained from this mock's saved rows. No marginal
  // arithmetic supplies a joint result. Producer semantics are tested in Python.
  for (const table of [...old.tables]) {
    if (table.dimension !== 'category_side') continue;
    const members = table.row_positions.map(position => old.rows[position]);
    const value = JSON.stringify(['category', 'side', 'selection_weekday', 'kickoff_weekday', 'lead_time_bucket'].map(key => members[0][key]));
    assert.equal(members.every(row => JSON.stringify(['category', 'side', 'selection_weekday', 'kickoff_weekday', 'lead_time_bucket'].map(key => row[key])) === value), true);
    const joint = { ...table, dimension: 'category_side_selection_kickoff_lead', value };
    delete joint.summary_id; joint.summary_id = sha(testCanonical(joint)); old.tables.push(joint);
  }
  const current = gzipPublication(partitionedPublication(old), 'modern-accuracy-' + (mutation || 'valid'));
  const summary = JSON.parse(current.assets.get('/data/selection-grading/' + current.pointer.summary.path));
  Object.assign(summary, { schema_version: 'selection-public-report-v6', report_schema_version: 'selection-report-v4',
    input_content_sha256: sha('fictional-modern-input-binding'), forecast_accuracy: structuredClone(aggregate) });
  if (mutation === 'unknown-index') summary.private_unrecognized_field = 'MUST_NOT_BE_ACCEPTED';
  if (mutation === 'unknown-accuracy') summary.forecast_accuracy.extra = [];
  if (mutation === 'bad-engine') summary.forecast_accuracy.cohorts[0].engine_sha256 = '0'.repeat(64);
  if (mutation === 'bad-metric') summary.forecast_accuracy.cohorts.find(c => c.outcome_provenance === 'recorded_outcome_receipt' && c.model_version === 'original_sleeper_matchup_baseline').categories.rec.paired.raw.mae = 999;
  if (mutation === 'wrong-source-version') summary.report_schema_version = 'selection-report-v3';
  if (mutation === 'missing-input-binding') delete summary.input_content_sha256;
  if (mutation === 'legacy-unvalidated-accuracy') { summary.schema_version = 'selection-public-report-v4'; summary.report_schema_version = 'selection-report-v3'; }
  const bytes = encode(summary);
  current.pointer.summary = { ...current.pointer.summary, sha256: sha(bytes), decoded_bytes: bytes.length };
  current.assets.set('/data/selection-grading/' + current.pointer.summary.path, bytes);
  current.assets.set('/data/selection-grading/latest.json', encode(current.pointer));
  return current;
}

async function modernAccuracyChecks(browser, origin) {
  if (arg('--root')) return { skipped: 'Saved-root checks use their existing immutable assets.' };
  const savedFixture = fixture, savedWeek = week, savedVariant = variant;
  const aggregate = modernBrowserAccuracy(), current = modernPublication(aggregate), output = [];
  const failures = ['unknown-index', 'unknown-accuracy', 'bad-engine', 'bad-metric', 'wrong-source-version', 'missing-input-binding', 'legacy-unvalidated-accuracy'];
  try {
    for (const width of [1280, 390, 320]) {
      fixture = current; week = fictionalWeek(); variant = 'valid';
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const external = [], errors = [];
      await context.route('**/*', async route => {
        const url = route.request().url();
        if (url.startsWith(origin + '/')) return route.continue();
        external.push(url);
        return route.fulfill({ status: 200, contentType: 'application/json', body: url.includes('api.sleeper.app/stats') ? '[]' : '{"events":[]}' });
      });
      const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
      try {
        await page.goto(origin + '/#/record');
        await page.waitForSelector('[data-forecast-accuracy]');
        await page.waitForFunction(() => S.grading && !S.grading.partLoading);
        assert.equal(await page.evaluate(() => S.grading.index.schema_version), 'selection-public-report-v6');
        assert.equal(await page.evaluate(() => S.grading.index.report_schema_version), 'selection-report-v4');
        const accuracy = page.locator('[data-forecast-accuracy]');
        const actual = await page.evaluate(() => S.grading.index.forecast_accuracy);
        assert.deepEqual(actual, aggregate, 'browser uses the exact producer aggregate');
        const identities = actual.cohorts.map(c => [c.model_version, c.outcome_provenance]);
        assert.equal(new Set(identities.map(JSON.stringify)).size, 3, 'model and outcome provenance retain separate cohorts');
        assert.ok(identities.some(([model]) => model === 'sleeper-matchup-data-integrity-v2'));
        assert.ok(identities.some(([, provenance]) => provenance === 'saved_cache_descriptive_regrade'));
        assert.ok(identities.some(([, provenance]) => provenance === 'recorded_outcome_receipt'));
        const directCohorts = accuracy.locator(':scope > details').filter({ has: page.locator('table') });
        assert.equal(await directCohorts.count(), 3);
        for (let i = 0; i < 3; i++) {
          await directCohorts.nth(i).locator(':scope > summary').click();
          assert.equal(await directCohorts.nth(i).locator('tbody > tr').count(), 12, 'all ten numerical categories plus offensive PPR and anytime TD remain visible');
        }
        const allText = await accuracy.innerText();
        assert.match(allText, /Positive infinity/); assert.match(allText, /Unavailable/);
        assert.match(allText, /component-derived/); assert.match(allText, /Direct saved provider PPR comparator/);
        assert.match(allText, /independent of selection filters/i);
        assert.match(allText, /first-observation coverage and earliest-valid-pair coverage can differ/i);
        assert.match(allText, /recorded probability|originally recorded probability/);
        assert.match(allText, /rederived from original count retained formula/);
        assert.doesNotMatch(allText, /PRIVATE_CANARY|unapproved\/private/);
        const before = await accuracy.textContent();
        await page.getByLabel('Line source', { exact: true }).selectOption('sleeper');
        await page.waitForFunction(() => S.grading && !S.grading.partLoading && S.grading.summary.summary.tables.every(t => t.line_source_scope === 'sleeper'));
        await page.getByLabel('Reporting period', { exact: true }).selectOption('2026-w06');
        await page.waitForFunction(() => S.grading && !S.grading.partLoading && S.grading.summary.summary.tables.every(t => t.period === '2026-w06'));
        await page.getByLabel('Supporting breakdown', { exact: true }).selectOption('category_side_selection_kickoff_lead');
        assert.equal(await accuracy.textContent(), before, 'cumulative forecast accuracy is independent of selection-period/source filters');
        const targetValue = JSON.stringify(['rec', 'under', 'Wednesday', 'Wednesday', '6-24h']);
        const selected = await page.evaluate(value => S.grading.summary.summary.tables.find(t => t.dimension === 'category_side_selection_kickoff_lead' && t.value === value), targetValue);
        assert.ok(selected, 'exact source/category/side/selection-day/kickoff-day/lead group exists');
        assert.equal(selected.line_source_scope, 'sleeper'); assert.equal(selected.period, '2026-w06');
        await page.locator('[data-grading-group="' + selected.summary_id + '"]').click();
        await page.waitForFunction(() => S.gradingGroup && !S.gradingGroup.loading);
        while (await page.locator('[data-grading-more]').count()) { await page.locator('[data-grading-more]').click(); await page.waitForFunction(() => !S.gradingGroup.loading); }
        const expectedRows = current.rows.filter(row => row.line_from === 'sleeper' && row.category === 'rec' && row.side === 'under' && row.selection_weekday === 'Wednesday' && row.kickoff_weekday === 'Wednesday' && row.lead_time_bucket === '6-24h');
        const ids = await page.locator('[data-grading-row]').evaluateAll(nodes => nodes.map(node => node.dataset.gradingRow));
        assert.deepEqual(ids, expectedRows.map(row => row.decision_sha256), 'complete exact joint membership comes from saved rows');
        assert.deepEqual(selected.row_positions, expectedRows.map(row => current.rows.indexOf(row)));
        assert.equal(selected.decided, expectedRows.filter(row => ['win', 'loss'].includes(row.result)).length);
        assert.equal(selected.win, expectedRows.filter(row => row.result === 'win').length);
        assert.equal(selected.loss, expectedRows.filter(row => row.result === 'loss').length);
        // Expand the full report, caveats, coverage and row evidence before the
        // narrow-width overflow assertion; horizontal table wrappers may scroll.
        await page.evaluate(() => document.querySelectorAll('#selection-grading details').forEach(node => { node.open = true; }));
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'entire expanded modern report has no page overflow at ' + width);
        assert.ok(await page.evaluate(() => [...document.querySelectorAll('#selection-grading select, #selection-grading button')].every(node => { const r = node.getBoundingClientRect(); return r.left >= -1 && r.right <= innerWidth + 1 || !!node.closest('.tbl-wrap'); })), 'controls remain inside phone/desktop bounds at ' + width);
        assert.deepEqual(errors, []);
        if (evidence) await page.screenshot({ path: path.join(evidence, 'modern-accuracy-joint-' + width + '.png'), fullPage: true });
        output.push({ width, cohorts: 3, categories_per_cohort: 12, exact_joint_rows: ids.length, no_page_overflow: true,
          aggregate_sha256: sha(encode(aggregate)), source: 'FICTIONAL_BROWSER_TRANSPORT', capture_qualification_exercised: false,
          intercepted_external_requests: external.length, provider_requests: 0, physical_device: false });
        if (width === 1280) {
          for (const failure of failures) {
            fixture = modernPublication(aggregate, failure);
            await page.reload(); await page.waitForFunction(() => !ticking);
            assert.equal(await page.evaluate(() => S.grading), null, failure + ' rejects a self-consistently hashed malformed modern index');
            assert.equal(await page.locator('[data-forecast-accuracy]').count(), 0, failure + ' does not retain fabricated or stale accuracy');
            assert.equal(await page.locator('[data-performance-headline]').count(), 0, failure + ' cannot fall back to older accepted totals');
            assert.match(await page.locator('#selection-grading').innerText(), /unavailable/i);
          }
          fixture = current;
        }
      } finally { await context.close(); }
    }
  } finally { fixture = savedFixture; week = savedWeek; variant = savedVariant; }
  return { cases: output, strict_failure_controls: failures, transport: 'loopback plus intercepted provider responses', performance_claim: false };
}


// Focused Chromium rendering regression. Uses fictional transport and the actual
// HTML/CSS/app. Computed contrast is not a physical Safari/device measurement.
async function paperSelectReadabilityChecks(browser, origin) {
  if (arg('--root')) return { skipped: 'Saved release roots are not replaced.' };
  const savedFixture=fixture, savedWeek=week, savedVariant=variant, output=[];
  try {
    for (const width of [1280,390,320]) {
      fixture=paperBrowserPublication('pre'); week=paperBrowserWeek(); variant='valid';
      const context=await browser.newContext({viewport:{width,height:900}});
      await context.route('**/*', route => route.request().url().startsWith(origin+'/') ? route.continue() : route.fulfill({status:200,contentType:'application/json',body:'{"events":[]}'}));
      const page=await context.newPage(), measurements=[];
      await page.clock.install({time:new Date(PAPER_TEST_START)});
      try {
        await page.goto(origin+'/#/parlay'); await page.waitForSelector('[data-paper-suggest]');
        await page.waitForFunction(()=>S.grading&&!S.grading.partLoading&&!ticking);
        async function inspect(expected, phase) {
          const actual=await page.locator('select[data-paper-filter]').evaluateAll(elements=>{
            const rgb=value=>{const v=value.match(/[\d.]+/g)?.map(Number);if(!v||v.length<3)throw Error('Unsupported computed color '+value);return [...v.slice(0,3),v.length>3?v[3]:1];};
            const lum=rgb=>rgb.slice(0,3).map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4;}).reduce((v,x,i)=>v+x*[.2126,.7152,.0722][i],0);
            return elements.map(element=>{
              const style=getComputedStyle(element),rect=element.getBoundingClientRect(),fg=rgb(style.color),bg=rgb(style.backgroundColor);
              const light=lum(fg),dark=lum(bg),contrast=(Math.max(light,dark)+.05)/(Math.min(light,dark)+.05);
              const option=element.selectedOptions[0],canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');ctx.font=style.font;
              return {field:element.dataset.paperFilter,value:element.value,text:option?.textContent,foreground:style.color,background:style.backgroundColor,
                contrast,opaque:fg[3]===1&&bg[3]===1,visible:style.display!=='none'&&style.visibility==='visible'&&+style.opacity===1,
                left:rect.left,right:rect.right,width:rect.width,height:rect.height,clientWidth:element.clientWidth,
                requiredTextWidth:ctx.measureText(option?.textContent||'').width+parseFloat(style.paddingLeft)+parseFloat(style.paddingRight)+18};
            });
          });
          assert.deepEqual(actual.map(v=>v.field).sort(),['game','sides','size','source'],phase+' has all four select controls');
          for(const control of actual){
            assert.deepEqual([control.value,control.text],expected[control.field],phase+' exact selected '+control.field+' text/value');
            assert.ok(control.visible&&control.width>0&&control.height>0,phase+' visible '+control.field);
            assert.ok(control.opaque&&control.contrast>=4.5,phase+' '+control.field+' selected text contrast '+control.contrast.toFixed(3)+' '+control.foreground+'/'+control.background);
            assert.ok(control.left>=0&&control.right<=width&&control.clientWidth+.5>=control.requiredTextWidth,phase+' readable selected '+control.field+' text fits the viewport/control');
          }
          measurements.push({phase,controls:actual});
        }
        await inspect({source:['dk','DraftKings reference'],sides:['mixed','mixed'],game:['','All'],size:['2','2']},'initial');
        await page.locator('[data-paper-filter=source]').selectOption('sleeper');
        await page.locator('[data-paper-filter=sides]').selectOption('under');
        await page.locator('[data-paper-filter=game]').selectOption('paper-game-0');
        await page.locator('[data-paper-filter=size]').selectOption('6');
        await inspect({source:['sleeper','Sleeper Picks reference'],sides:['under','under'],game:['paper-game-0','BBB–AAA'],size:['6','6']},'changed-and-rerendered');
        output.push({width,assertions:34,measurements,source:'FICTIONAL_BROWSER_TRANSPORT',physical_device:false});
      } finally {await context.close();}
    }
  } finally {fixture=savedFixture;week=savedWeek;variant=savedVariant;}
  return output;
}

// Separate from the existing 120 paper UI checks. Real saved-ticket handlers and
// bounded asset reader run against fictional encoded HTTP outcome partitions.
async function paperHistoricalAsyncChecks(browser, origin) {
  if (arg('--root')) return {skipped:'Saved release roots are not replaced.'};
  const previous={fixture,week,variant}, checks=[], requestsMade=[];
  const publications=Object.fromEntries(['pre','final','correction'].map(stage=>[stage,paperBrowserPublication(stage)]));
  const context=await browser.newContext({viewport:{width:390,height:900}});
  let transport=null;
  await context.route('**/*', async route=>{
    const request=route.request(),url=request.url(); requestsMade.push({url,method:request.method()});
    if(!url.startsWith(origin+'/'))return route.fulfill({status:200,contentType:'application/json',body:'{"events":[]}'});
    const control=transport;
    if(control&&new URL(url).pathname===control.pathname){
      if(control.mode==='missing')return route.fulfill({status:404,contentType:'application/json',body:'{"fictional_missing_historical_partition":true}'});
      if(control.mode==='delay'&&!control.caught){
        control.caught=true;control.startedResolve();await control.gate;
        // Freeze the exact old response bytes when the request starts, so a
        // later publication cannot accidentally alter this delayed response.
        return route.fulfill({status:200,contentType:'application/json',headers:{'Cache-Control':'no-store'},body:control.bytes});
      }
    }
    return route.continue();
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const equal=(a,b,label)=>{assert.deepEqual(a,b,label);checks.push(label);};
  const check=(value,label)=>{assert.ok(value,label);checks.push(label);};
  const timeout=async promise=>{let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Historical transport control did not start')),5000);})]);}finally{clearTimeout(timer);}};
  const hold=publication=>{
    const descriptor=publication.periods.find(v=>v.season===2026&&v.week===6);
    assert.ok(descriptor,'fictional historical Week6 partition exists');
    const control={mode:'delay',caught:false,pathname:'/data/selection-grading/'+descriptor.path,bytes:Buffer.from(publication.assets.get('/data/selection-grading/'+descriptor.path))};
    control.started=new Promise(resolve=>{control.startedResolve=resolve;});control.gate=new Promise(resolve=>{control.release=resolve;});transport=control;return control;
  };
  const open=async key=>page.locator('[data-paper-open]').evaluateAll((buttons,key)=>{const b=buttons.find(v=>v.dataset.paperOpen===key);if(!b)throw Error('Saved ticket missing');b.click();},key);
  const records=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith(PAPER_PREFIX)).sort().map(k=>[k,localStorage.getItem(k)])));
  try{
    fixture=publications.pre;week=paperBrowserWeek();variant='valid';
    await page.clock.install({time:new Date(PAPER_TEST_START)});
    await page.goto(origin+'/#/parlay');await page.waitForSelector('[data-paper-suggest]');await page.waitForFunction(()=>S.grading&&!ticking);
    await page.locator('[data-paper-category=rec]').check();
    const save=async ids=>{
      await page.locator('[data-paper-new]').click();
      for(const id of ids)await page.locator('[data-paper-add]').evaluateAll((buttons,id)=>{const b=buttons.find(v=>JSON.parse(v.dataset.paperAdd).player_id==='paper-player-'+id);if(!b)throw Error('Fictional candidate absent');b.click();},id);
      await page.locator('[data-paper-save]').click();await page.waitForFunction(()=>S.paper.opened&&S.paper.error.includes('Saved and read back'));
      return page.evaluate(()=>({key:PAPER_PREFIX+S.paper.opened.ticket_id+'.'+S.paper.opened.revision_id,ticket:S.paper.opened}));
    };
    const first=await save([0,1]),second=await save([2,3]),saved=await records();
    fixture=publications.final;week=paperBrowserWeek();week.week=7;week.generated_at=PAPER_TEST_FINAL;week.games=week.games.map(g=>({...g,state:'post',detail:'Final'}));
    await page.clock.setFixedTime(new Date(PAPER_TEST_FINAL));await page.reload();await page.waitForSelector('[data-paper-open]');
    await page.waitForFunction(()=>S.grading&&S.finalOutcomes.size&&[...S.finalOutcomes.values()].every(row=>row.week===7));
    await page.evaluate(()=>{const original=gradeOpenedPaper;window.paperAsyncJobs=[];gradeOpenedPaper=function(...args){const pending=original(...args);window.paperAsyncJobs.push(pending);return pending;};});
    const oldSelection=hold(publications.final);await open(first.key);await timeout(oldSelection.started);
    equal(await page.evaluate(()=>S.paper.results),null,'delayed historical partition has no invented interim grade');
    await open(second.key);await page.waitForFunction(()=>S.paper.results?.[0]?.status==='push'&&S.paper.results?.[1]?.status==='dnp');
    equal(await page.evaluate(()=>S.paper.opened.revision_id),second.ticket.revision_id,'newly opened ticket owns displayed results');
    oldSelection.release();await page.evaluate(()=>Promise.all(window.paperAsyncJobs));
    equal(await page.evaluate(()=>[S.paper.opened.revision_id,S.paper.results.map(r=>r.status)]),[second.ticket.revision_id,['push','dnp']],'old delayed ticket cannot overwrite newer open ticket');
    equal(await page.evaluate(()=>[...S.finalOutcomes.values()].map(r=>r.actual).filter(v=>v!==null).every(v=>v===99)),true,'different current-week outcomes remain a negative join control');

    const oldGeneration=hold(publications.final);await open(first.key);await timeout(oldGeneration.started);
    fixture=publications.correction;await page.clock.setFixedTime(new Date(PAPER_TEST_CORRECTION));
    await page.evaluate(()=>loadGrading());await page.waitForFunction(()=>S.paper.results?.[0]?.actual===3&&S.paper.results?.[1]?.actual===3);
    equal(await page.evaluate(()=>[S.grading.pointer.report_id,S.paper.results.map(r=>[r.status,r.actual])]),[publications.correction.pointer.report_id,[['loss',3],['win',3]]],'new publication correction owns exact saved historical results');
    oldGeneration.release();await page.evaluate(()=>Promise.all(window.paperAsyncJobs));
    equal(await page.evaluate(()=>[S.grading.pointer.report_id,S.paper.results.map(r=>[r.status,r.actual])]),[publications.correction.pointer.report_id,[['loss',3],['win',3]]],'delayed older generation cannot undo current correction');

    const historical=publications.correction.periods.find(v=>v.week===6);
    transport={mode:'missing',pathname:'/data/selection-grading/'+historical.path};await open(first.key);await page.evaluate(()=>Promise.all(window.paperAsyncJobs));
    equal(await page.evaluate(()=>S.paper.results),null,'missing historical bytes do not substitute zero DNP or prior results');
    check((await page.locator('#main').innerText()).includes('Required saved outcome evidence is unavailable; no result was substituted.'),'required historical failure is visibly unavailable');
    await page.locator('[data-paper-evaluate]').click();await page.waitForFunction(()=>S.paper.error.startsWith('Saved results unavailable:'));
    equal(await page.evaluate(()=>S.paper.history),null,'required historical failure cannot produce partial saved-ticket totals');
    equal(await records(),saved,'missing/delayed/corrected outcomes never mutate saved private selections');
    equal(await page.evaluate(()=>S.data.week),7,'historical outcomes do not change current board period');
    transport=null;await open(first.key);await page.evaluate(()=>Promise.all(window.paperAsyncJobs));
    equal(await page.evaluate(()=>S.paper.results.map(r=>[r.status,r.actual])),[['loss',3],['win',3]],'explicit user reopen recovers from missing historical transport');
    equal(requestsMade.filter(r=>r.method!=='GET').length,0,'all historical checks remain read-only network operations');
    equal(errors,[],'no browser page errors during historical races/failures');
    return {width:390,checks:checks.length,descriptions:checks,source:'FICTIONAL_ENCODED_HTTP_OUTCOME_TRANSPORT',provider_requests:0,capture_qualification_exercised:false,performance_claim:false};
  }finally{if(transport?.release)transport.release();await context.close();fixture=previous.fixture;week=previous.week;variant=previous.variant;}
}

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ executablePath: process.env.NFL_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const measurements = [];
  const presentation = [];
  try {
    const weekly=['--modern-only','--paper-only','--paper-readability-only','--paper-async-only'].some(flag=>args.includes(flag))?null:await weeklyDisplayChecks(browser,origin);
    if(args.includes('--weekly-only')){console.log(JSON.stringify({weekly,scope:'FOCUSED_FICTIONAL_WEEKLY_DISPLAY_UI_ONLY',app_sha256:sha(fs.readFileSync(path.join(staticRoot,'app.js'))),performance_claim:false},null,2));return;}
    const modern = ['--paper-only','--paper-readability-only','--paper-async-only'].some(flag=>args.includes(flag)) ? null : await modernAccuracyChecks(browser, origin);
    if (args.includes('--modern-only')) { console.log(JSON.stringify({ modern, app_sha256: sha(fs.readFileSync(path.join(staticRoot, 'app.js'))), scope: 'FOCUSED_MODERN_ACCURACY_JOINT_UI_ONLY', performance_claim: false }, null, 2)); return; }
    const paperReadability = args.includes('--paper-async-only') ? null : await paperSelectReadabilityChecks(browser, origin);
    if (args.includes('--paper-readability-only')) { console.log(JSON.stringify({paperReadability,app_sha256:sha(fs.readFileSync(path.join(staticRoot,'app.js'))),scope:'FOCUSED_PAPER_SELECT_READABILITY_ONLY',performance_claim:false},null,2)); return; }
    const paperAsync = await paperHistoricalAsyncChecks(browser, origin);
    if (args.includes('--paper-async-only')) { console.log(JSON.stringify({paperAsync,app_sha256:sha(fs.readFileSync(path.join(staticRoot,'app.js'))),scope:'FOCUSED_PAPER_HISTORICAL_ASYNC_ONLY',performance_claim:false},null,2)); return; }
    const paper = await paperBuilderChecks(browser, origin);
    if (args.includes('--paper-only')) { console.log(JSON.stringify({ paper, app_sha256: sha(fs.readFileSync(path.join(staticRoot, 'app.js'))), scope: 'FOCUSED_PAPER_UI_ONLY', performance_claim: false }, null, 2)); return; }
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
    const result = { hosting, weekly, modern, paperReadability, paperAsync, paper, fixture: arg('--root') ? 'AUTHORIZED_SAVED_DATA_ISOLATED_ROOT' : 'FICTIONAL_ONLY', public_deployment_test: false,
      external_network_requests: 0, app_sha256: sha(fs.readFileSync(path.join(staticRoot, 'app.js'))),
      html_sha256: sha(fs.readFileSync(path.join(staticRoot, 'index.html'))), measurements, presentation, requests: [...new Set(requests)], assertions: 'passed' };
    if (evidence) fs.writeFileSync(path.join(evidence, 'grading-browser-results.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => server.close());
