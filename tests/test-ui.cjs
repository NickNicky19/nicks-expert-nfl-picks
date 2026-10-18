const assert = require('node:assert/strict');

// Accepted Phase 2 grading checks are separate from the retained production additions.
{
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../output/app.js'), 'utf8');
const names = ['finalIdentity', 'finalIdentityMatches', 'publicAssetPath', 'current', 'slpPlayed', 'statValue', 'propStatus', 'gameBetStatus', 'resBadge'];
const functions = names.map(name => {
  const value = source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))?.[0];
  assert.ok(value, 'actual ' + name + ' implementation found');
  return value;
}).join('\n');
const p = { id: 'fictional-player', game_id: 'fictional-game', team: 'AAA', pos: 'WR' };
const kickoff = '2026-10-15T00:15:00Z';
const state = { data: { season: 2026, week: 6 }, games: { 'fictional-game': { kickoff, state: 'post', home: 'AAA', away: 'BBB', home_score: 10, away_score: 7 } }, finalOutcomes: new Map(), slp: {}, live: {} };
const context = { S: state, HASH64: /^[a-f0-9]{64}$/, GRADING_BASE: 'data/selection-grading/', esc: x => String(x ?? ''), fantasyPts: () => 0, fmt: x => String(x) };
vm.createContext(context);
vm.runInContext(functions + '\nthis.ui={finalIdentity,finalIdentityMatches,publicAssetPath,current,slpPlayed,propStatus,gameBetStatus,resBadge};', context);
const ui = context.ui;
assert.equal(ui.slpPlayed({ pts_ppr: 0 }), false);
assert.equal(ui.slpPlayed({ gp: 1, rec: 0 }), true);
assert.equal(ui.slpPlayed({ gp: -1, off_snp: 2 }), false);
assert.equal(ui.current(p).none, false);
assert.equal(ui.propStatus(p, 'rec', 0.5, 'over').res, 'unresolved');
const final = { season: 2026, week: 6, game_id: p.game_id, player_id: p.id, category: 'rec', team: 'AAA', kickoff, status: 'resolved', final_confirmed: true, actual: 0, outcome_conflict: false };
state.finalOutcomes.set(ui.finalIdentity(p, 'rec'), final);
assert.equal(ui.propStatus(p, 'rec', 0.5, 'over').res, 'miss');
assert.equal(ui.propStatus(p, 'rec', 0.5, 'under').res, 'hit');
assert.equal(ui.propStatus(p, 'rec', 0, 'over').res, 'push');
assert.equal(ui.propStatus(p, 'rec', 0, 'under').res, 'push');
final.actual = 5;
assert.equal(ui.propStatus(p, 'rec', 4.5, 'over').res, 'hit');
assert.equal(ui.propStatus(p, 'rec', 5.5, 'over').res, 'miss', 'uses the caller/user saved line');
assert.equal(ui.propStatus(p, 'rec', null, 'over').final, false);
final.team = 'BBB';
assert.equal(ui.propStatus(p, 'rec', 4.5, 'over').res, 'unresolved');
final.team = 'AAA'; final.outcome_conflict = true;
assert.equal(ui.propStatus(p, 'rec', 4.5, 'over').res, 'unresolved');
final.outcome_conflict = false; final.status = 'dnp'; final.actual = null;
assert.equal(ui.propStatus(p, 'rec', 4.5, 'over').res, 'dnp');
assert.equal(ui.current(p).none, true);
state.games[p.game_id].state = 'in'; state.slp[p.id] = { gp: 1, rec: 5 };
assert.equal(ui.propStatus(p, 'rec', 4, 'over').res, 'above');
state.slp[p.id].rec = 3;
assert.equal(ui.propStatus(p, 'rec', 4, 'over').res, 'below', 'downward correction remains reversible');
state.slp[p.id].rec = 4;
assert.equal(ui.propStatus(p, 'rec', 4, 'under').res, 'equal');
assert.equal(ui.propStatus(p, 'rec', 4, 'under').final, false);
assert.match(ui.resBadge(ui.propStatus(p, 'rec', 4, 'under')), /CURRENTLY EQUAL/);
state.slp[p.id] = { gp: 1, rec: null };
assert.equal(ui.propStatus(p, 'rec', 0.5, 'over').res, 'unresolved');
state.slp[p.id] = { gp: 1, rec: Infinity };
assert.equal(ui.propStatus(p, 'rec', 0.5, 'over').res, 'unresolved');
state.slp[p.id] = { gp: 1, rush_yd: 10, rec_yd: null };
assert.equal(ui.propStatus(p, 'rush_rec_yd', 10.5, 'over').res, 'unresolved');
state.slp[p.id] = { gp: 1 };
assert.equal(ui.propStatus(p, 'rec', 0.5, 'under').v, 0, 'confirmed played compact omitted-zero remains supported');
state.slp[p.id] = { pts_ppr: 12 };
assert.equal(ui.propStatus(p, 'rec', 4, 'over').res, 'unresolved');
assert.equal(ui.gameBetStatus({ gid: p.game_id, market: 'total', side: 'over', line: 10 }).res, 'above');
state.games[p.game_id].state = 'post'; state.games[p.game_id].detail = 'Cancelled';
assert.equal(ui.gameBetStatus({ gid: p.game_id, market: 'total', side: 'over', line: 10 }).res, 'unresolved');
state.games[p.game_id].detail = 'Final/OT';
assert.equal(ui.gameBetStatus({ gid: p.game_id, market: 'total', side: 'over', line: 17 }).res, 'push');
assert.equal(ui.gameBetStatus({ gid: p.game_id, market: 'total', side: 'over', line: null }).final, false);
assert.equal(ui.gameBetStatus({ gid: p.game_id, market: 'ml', side: 'UNRELATED', line: null }).res, 'unresolved');
state.games[p.game_id].away_score = null;
assert.equal(ui.gameBetStatus({ gid: p.game_id, market: 'total', side: 'over', line: 17 }).res, 'unresolved');
state.games[p.game_id].state = 'pre';
assert.equal(ui.propStatus(p, 'rec', 4, 'over'), null);
const pointer = { report_id: 'a'.repeat(64) }, sha256 = 'b'.repeat(64);
assert.match(ui.publicAssetPath(pointer, { path: pointer.report_id + '/rows-0000.json', sha256 }, 'rows'), /^data\/selection-grading\//);
assert.throws(() => ui.publicAssetPath(pointer, { path: '../secret.json', sha256 }, 'rows'));
assert.throws(() => ui.publicAssetPath(pointer, { path: 'https://example.com/rows-0000.json', sha256 }, 'rows'));
console.log('36 actual Phase 2 grading assertions passed.');
}

const { buildStatus, tallyDetails } = require('../output/reliability-ui.js');
const now = Date.parse('2026-10-10T19:00:00Z');
assert.equal(buildStatus('2026-10-10T18:00:00Z', now).state, 'recent');
assert.equal(buildStatus('2026-10-10T16:59:00Z', now).state, 'stale');
assert.equal(buildStatus('2026-10-10T17:00:00Z', now).state, 'recent');
assert.equal(buildStatus('2026-10-10T20:00:00Z', now).state, 'unknown');
assert.equal(buildStatus('not a timestamp', now).state, 'unknown');
assert.equal(tallyDetails({ push: 2, dnp: 1, unresolved: 3 }), '2 push · 1 confirmed DNP · 3 unresolved');
assert.equal(tallyDetails({}), '');
assert.equal(tallyDetails(undefined), '');
console.log('8 UI helper assertions passed.');

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../output/app.js'), 'utf8');

// Presentation uses saved-board values and the existing ranking eligibility.
// Frozen inputs catch accidental mutation; arbitrary units are fictional.
{
  const extract = name => {
    const value = source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))?.[0];
    assert.ok(value, 'actual ' + name + ' implementation found');
    return value;
  };
  const props = [
    { key: 'no_lean', lean: null, adj: 100, line: 1 },
    { key: 'tie_first', lean: 'over', adj: 15, line: 10 },
    { key: 'tie_under', lean: 'under', adj: 5, line: 10 },
    { key: 'tie_last', lean: 'over', adj: 3, line: 2 },
    { key: 'null_adj', lean: 'over', adj: null, line: .5 },
    { key: 'largest', lean: 'under', adj: 0, line: 1 },
    { key: 'negative_line', lean: 'over', adj: -1, line: -2 },
    { key: 'zero_line', lean: 'under', adj: -2, line: 0 },
    { key: 'reference', lean: null, adj: 0, line: 100, line_from: 'ours' },
  ].map(Object.freeze);
  const player = Object.freeze({ id: 'fixture', props: Object.freeze(props) });
  const S = { tab: 'props', gameView: null, f: { sort: 'edge', cat: '', q: '', pos: 'ALL',
    game: '', hideOut: false, favs: false }, data: { players: [] }, lines: {}, sc: {},
    games: { g: { state: 'pre' } }, favs: new Set() };
  const context = { S, UNAVAILABLE: new Set(), normName: x => x.toLowerCase(),
    posMatch: () => true, injOf: () => ({ status: '' }), projPts: p => p.proj_ppr, livePPR: p => p.live };
  vm.createContext(context);
  vm.runInContext(extract('displayedProps') + '\n' + extract('filteredPlayers'), context);
  const keys = rows => Array.from(rows, x => x.key);
  const normal = props.map(x => x.key);
  const expected = ['zero_line', 'largest', 'negative_line', 'tie_first', 'tie_under', 'tie_last', 'no_lean', 'null_adj', 'reference'];
  let checks = 0;
  const check = fn => { fn(); checks++; };
  check(() => assert.deepEqual(keys(context.displayedProps(player)), expected));
  check(() => {
    const result = context.displayedProps(player);
    assert.notEqual(result, player.props);
    assert.equal(new Set(result).size, props.length);
    assert.ok(result.every(prop => player.props.includes(prop)));
  });
  check(() => assert.deepEqual(keys(player.props), normal));
  for (const sort of ['proj', 'live', 'name']) check(() => {
    S.f.sort = sort; assert.deepEqual(keys(context.displayedProps(player)), normal);
  });
  S.f.sort = 'edge';
  for (const category of ['tie_last', 'missing']) check(() => {
    S.f.cat = category;
    assert.deepEqual(keys(context.displayedProps(player)), category === 'missing' ? [] : [category]);
  });
  S.f.cat = '';
  check(() => {
    S.lines = { 'fixture|zero_line': -2, 'fixture|tie_first': 15 }; S.sc = { mode: 'league', half: true };
    assert.deepEqual(keys(context.displayedProps(player)), expected);
  });
  for (const state of ['pre', 'in', 'post']) check(() => {
    S.games.g.state = state;
    assert.deepEqual(keys(context.displayedProps(player)), expected);
  });
  check(() => { S.gameView = 'g'; assert.deepEqual(keys(context.displayedProps(player)), normal); S.gameView = null; });
  check(() => { S.tab = 'mine'; assert.deepEqual(keys(context.displayedProps(player)), normal); S.tab = 'props'; });
  check(() => {
    S.gameView = 'g'; S.f.cat = 'tie_first';
    assert.deepEqual(keys(context.displayedProps(player)), ['tie_first']);
    S.gameView = null; S.f.cat = '';
  });
  S.data.players = [
    { id: 'a', name: 'A', pos: 'WR', game_id: 'g', proj_ppr: 20, live: 5, props: [{ key: 'rec', lean: 'over', adj: 11, line: 10 }] },
    { id: 'b', name: 'B', pos: 'WR', game_id: 'g', proj_ppr: 40, live: 1, props: [{ key: 'anytime_td', lean: 'over', adj: null, line: .5 }] },
    { id: 'c', name: 'C', pos: 'WR', game_id: 'g', proj_ppr: 10, live: 8, props: [{ key: 'rec', lean: 'under', adj: 0, line: 1 }] },
  ];
  const orders = { edge: ['c', 'a', 'b'], proj: ['b', 'a', 'c'], live: ['c', 'a', 'b'], name: ['a', 'b', 'c'] };
  for (const [sort, order] of Object.entries(orders)) check(() => {
    S.f.sort = sort;
    assert.deepEqual(Array.from(context.filteredPlayers(), p => p.id), order);
    for (const p of S.data.players) context.displayedProps(p);
    assert.deepEqual(Array.from(context.filteredPlayers(), p => p.id), order);
  });
  console.log('Biggest-lean presentation: ' + checks + ' focused preservation checks passed.');
}

// Versioned reporting uses one full context for headlines and category cells.
{
  const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
  const source = fs.readFileSync(path.join(__dirname, '../output/app.js'), 'utf8');
  const code = source.slice(source.indexOf('const GRADING_LABELS ='), source.indexOf('function gradingRowsHtml'));
  const base = { provenance_class: 'local_pregame_membership_observation', model_version: 'original', engine_sha256: 'a'.repeat(64),
    policy_version: 'policy-v1', policy_sha256: 'b'.repeat(64), view: 'all_qualifying_leans', checkpoint: 'history', period: 'cumulative',
    line_source_scope: 'all', win: 2, loss: 1, push: 1, dnp: 1, pending: 2, unresolved: 1, excluded: 0, no_action: 1, not_due: 0,
    decided: 3, rows: 9, unique_players: 3, unique_games: 2, unique_weeks: 1 };
  const tables = [];
  for (const policy of ['b', 'c']) for (const source of ['all', 'dk', 'sleeper']) for (const period of ['cumulative', '2026-w06']) {
    for (const [dimension, value] of [['overall', 'all'], ['category', 'rec'], ['category_side', 'rec:over'], ['category_side', 'rec:under']]) {
      tables.push({ ...base, policy_sha256: policy.repeat(64), period, line_source_scope: source, dimension, value,
        summary_id: [policy, source, period, dimension, value].join('|') });
    }
  }
  const S = { gradingFilters: {}, grading: { summary: { schema_version: 'selection-public-report-v2', summary: { tables } } },
    data: { categories: { rec: { label: 'Receptions', lean: true }, fpts: { label: 'PPR', lean: true } } } };
  const context = { S, SHORT: {}, esc: x => String(x ?? ''), fmt: n => n.toFixed(1) };
  vm.createContext(context); vm.runInContext(code + '\nthis.helpers={selectedGradingTables,selectionPerformanceHtml};', context);
  const ui = context.helpers;
  let selected = ui.selectedGradingTables();
  assert.equal(selected.baseTables.length, 4);
  assert.ok(selected.baseTables.every(t => t.policy_sha256 === 'b'.repeat(64) && t.line_source_scope === 'all' && t.period === 'cumulative'));
  let html = ui.selectionPerformanceHtml(selected.baseTables);
  assert.match(html, /Recorded selection performance/); assert.match(html, /2–1/); assert.match(html, /66\.7%/);
  assert.doesNotMatch(html, /data-category-performance="fpts"/);
  for (const [field, value] of [['policy_sha256', 'c'.repeat(64)], ['line_source_scope', 'dk'], ['period', '2026-w06']]) S.gradingFilters[field] = value;
  S.gradingFilters.dimension = 'selection_weekday';
  selected = ui.selectedGradingTables();
  assert.equal(S.gradingFilters.dimension, 'overall', 'unavailable source-specific day view resets truthfully');
  assert.ok(selected.baseTables.every(t => t.policy_sha256 === 'c'.repeat(64) && t.line_source_scope === 'dk' && t.period === '2026-w06'));
  html = ui.selectionPerformanceHtml(selected.baseTables.map(t => ({ ...t, win: 0, loss: 0, decided: 0 })));
  assert.match(html, /Unavailable/); assert.doesNotMatch(html, />0\.0%/);
  assert.match(html, /pending/); assert.match(html, /confirmed DNP/); assert.match(html, /no-side coverage/);
  assert.match(html, /Our selections by line source/);
  const legacy = tables.filter(t => t.policy_sha256 === 'b'.repeat(64) && t.line_source_scope === 'all').map(t => {
    const row = { ...t }; delete row.policy_version; delete row.policy_sha256; delete row.line_source_scope; return row;
  });
  S.grading.summary = { schema_version: 'selection-public-report-v1', summary: { tables: legacy } };
  selected = ui.selectedGradingTables();
  assert.match(selected.controls, /Legacy aggregate — policy not separated/);
  assert.equal(S.gradingFilters.line_source_scope, 'all');
  assert.match(ui.selectionPerformanceHtml(selected.baseTables), /Legacy aggregates/);
  console.log('Report context and category presentation: 17 focused assertions passed.');
}

// Real v3 asset/identity validators, without a provider or stored device data.
(async () => {
  const crypto = require('node:crypto');
  const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];
  let bytes, requests = 0;
  const context = { HASH64: /^[a-f0-9]{64}$/, GRADING_BASE: 'data/selection-grading/', GRADING_RESULTS: ['win','loss','push','dnp','pending','unresolved','no_action','not_due','excluded'],
    TextEncoder, TextDecoder, Blob, DecompressionStream, ReadableStream, crypto: crypto.webcrypto, Map, Set, gradingArchiveSources: new WeakMap(),
    fetch: async () => { requests++; return new Response(bytes); } };
  vm.createContext(context);
  vm.runInContext(['gradingHash','gradingStreamBytes','checkedHostingJson','resolveGradingArchive','fetchGradingAsset','publicAssetPath','checkedGradingAsset','validateFinalOutcomes','loadOutcomePeriod'].map(extract).join('\n') + '\nthis.ui={publicAssetPath,checkedGradingAsset,validateFinalOutcomes,loadOutcomePeriod};', context);
  const ui = context.ui, pointer = { schema_version: 'selection-publication-pointer-v2', report_id: 'a'.repeat(64), generated_at: '2026-10-18T18:00:00Z' };
  const payload = { schema_version: 'selection-final-outcome-period-v1', report_id: pointer.report_id, season: 2026, week: 6, outcomes: [] };
  bytes = Buffer.from(JSON.stringify(payload));
  const descriptor = { sha256: crypto.createHash('sha256').update(bytes).digest('hex'), decoded_bytes: bytes.length, season: 2026, week: 6, count: 0 };
  descriptor.path = descriptor.sha256 + '/outcomes.json';
  assert.equal(ui.publicAssetPath(pointer, descriptor, 'outcomes', true), 'data/selection-grading/' + descriptor.path);
  assert.throws(() => ui.publicAssetPath({ ...pointer, schema_version: 'selection-publication-pointer-v1' }, descriptor, 'outcomes', true));
  assert.equal((await ui.checkedGradingAsset(pointer, descriptor, 'outcomes', true)).week, 6);
  await assert.rejects(ui.checkedGradingAsset(pointer, { ...descriptor, decoded_bytes: 12 * 1024 * 1024 + 1 }, 'outcomes', true), /size/);
  const before = requests;
  const absent = await ui.loadOutcomePeriod({ pointer, outcomeIndex: { periods: [descriptor] } }, 2026, 5);
  assert.equal(absent.size, 0); assert.equal(requests, before, 'no unrelated outcome period request');
  bytes = Buffer.from(JSON.stringify({ ...payload, week: 5 }));
  const wrong = { ...descriptor, sha256: crypto.createHash('sha256').update(bytes).digest('hex'), decoded_bytes: bytes.length };
  wrong.path = wrong.sha256 + '/outcomes.json';
  await assert.rejects(ui.loadOutcomePeriod({ pointer, outcomeIndex: { periods: [wrong] } }, 2026, 6), /period/);
  bytes = Buffer.from(JSON.stringify({ ...payload, report_id: 'b'.repeat(64) }));
  const mixed = { ...descriptor, sha256: crypto.createHash('sha256').update(bytes).digest('hex'), decoded_bytes: bytes.length };
  mixed.path = mixed.sha256 + '/outcomes.json';
  await assert.rejects(ui.checkedGradingAsset(pointer, mixed, 'outcomes', true), /identity/);
  bytes = Buffer.from('wrong bytes');
  await assert.rejects(ui.checkedGradingAsset(pointer, descriptor, 'outcomes', true), /size|checksum/);
  console.log('Partitioned outcome/asset contracts: 10 focused checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });


// Actual encoded reader: independent wire fixtures and bounded stream controls.
(async () => {
  const crypto = require('node:crypto'), zlib = require('node:zlib');
  const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];
  const hash = value => crypto.createHash('sha256').update(value).digest('hex');
  const pointer = { schema_version: 'selection-publication-pointer-v3', report_id: 'c'.repeat(64) };
  const raw = Buffer.from(JSON.stringify({ schema_version: 'selection-final-outcome-period-v1', report_id: pointer.report_id, season: 2026, week: 6, outcomes: [] }));
  const encoded = zlib.gzipSync(raw, { mtime: 0 });
  const descriptor = { encoding: 'gzip', encoded_sha256: hash(encoded), encoded_bytes: encoded.length, sha256: hash(raw), decoded_bytes: raw.length, season: 2026, week: 6, count: 0, path: hash(encoded) + '/outcomes.json' };
  let delivered = encoded, headers = {}, fetches = 0, cancelled = 0, streamed = false, networkStatus = 200;
  const context = { HASH64: /^[a-f0-9]{64}$/, GRADING_BASE: 'data/selection-grading/', TextEncoder, TextDecoder, Blob, DecompressionStream, ReadableStream,
    crypto: crypto.webcrypto, Map, Set, gradingArchiveSources: new WeakMap(),
    gradingCanonical: value => JSON.stringify(value),
    fetch: async () => {
      fetches++;
      const body = streamed ? new ReadableStream({ pull(controller) { controller.enqueue(new Uint8Array(1024)); }, cancel() { cancelled++; } }) : delivered;
      return new Response(body, { status: networkStatus, headers });
    } };
  vm.createContext(context);
  vm.runInContext(['gradingHash','gradingStreamBytes','checkedHostingJson','resolveGradingArchive','fetchGradingAsset','publicAssetPath','checkedGradingAsset'].map(extract).join('\n') + '\nthis.ui={checkedGradingAsset,publicAssetPath};', context);
  const ui = context.ui;
  assert.equal((await ui.checkedGradingAsset(pointer, descriptor, 'outcomes', true)).week, 6);
  headers = { 'Content-Encoding': 'gzip' }; // Delivered body contract, independent of HTTP header.
  assert.equal((await ui.checkedGradingAsset(pointer, descriptor, 'outcomes', true)).week, 6);
  const before = fetches;
  for (const change of [{ encoding: 'br' }, { encoded_bytes: 12 * 1024 * 1024 + 1 }, { decoded_bytes: 12 * 1024 * 1024 + 1 }, { private_extension: true }]) {
    await assert.rejects(ui.checkedGradingAsset(pointer, { ...descriptor, ...change }, 'outcomes', true));
  }
  assert.equal(fetches, before, 'unsupported/oversized descriptors rejected before network');
  for (const change of [{ encoded_sha256: '0'.repeat(64), path: '0'.repeat(64) + '/outcomes.json' }, { sha256: '0'.repeat(64) }, { encoded_bytes: encoded.length - 1 }, { decoded_bytes: raw.length - 1 }]) {
    await assert.rejects(ui.checkedGradingAsset(pointer, { ...descriptor, ...change }, 'outcomes', true));
  }
  delivered = encoded.subarray(0, encoded.length - 4);
  let changed = { ...descriptor, encoded_sha256: hash(delivered), encoded_bytes: delivered.length, path: hash(delivered) + '/outcomes.json' };
  await assert.rejects(ui.checkedGradingAsset(pointer, changed, 'outcomes', true));
  delivered = Buffer.from(encoded); delivered[delivered.length - 5] ^= 255;
  changed = { ...descriptor, encoded_sha256: hash(delivered), path: hash(delivered) + '/outcomes.json' };
  await assert.rejects(ui.checkedGradingAsset(pointer, changed, 'outcomes', true));
  delivered = zlib.gzipSync(Buffer.alloc(13 * 1024 * 1024, 65));
  changed = { ...descriptor, encoded_sha256: hash(delivered), encoded_bytes: delivered.length, path: hash(delivered) + '/outcomes.json', decoded_bytes: 16 };
  await assert.rejects(ui.checkedGradingAsset(pointer, changed, 'outcomes', true), /limit/);
  streamed = true;
  await assert.rejects(ui.checkedGradingAsset(pointer, { ...descriptor, encoded_bytes: 32 }, 'outcomes', true), /limit/);
  assert.equal(cancelled, 1, 'reader cancelled before unbounded encoded buffering');
  streamed = false; delivered = encoded; context.DecompressionStream = undefined;
  await assert.rejects(ui.checkedGradingAsset(pointer, descriptor, 'outcomes', true), /decoder unavailable/);
  context.DecompressionStream = DecompressionStream;
  networkStatus = 503; const old = fetches;
  await assert.rejects(ui.checkedGradingAsset(pointer, descriptor, 'outcomes', true), /source unavailable/);
  assert.equal(fetches, old + 1, 'server failure does not select archive fallback');
  console.log('Encoded report streams: 19 focused integrity/limit/decoder checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
