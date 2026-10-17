const assert = require('node:assert/strict');
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
// Exercise the actual browser grading functions, including saved-line equality
// and final evidence binding. Fictional fields never call a provider.
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
console.log('8 retained UI helper assertions and 36 actual grading assertions passed.');

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
