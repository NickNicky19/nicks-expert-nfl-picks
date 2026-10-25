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

// Game-market finality is independent of the Phase 2 outcome publication.
// These are actual application functions with fictional scoreboards/selections.
// DOM/localStorage and kickoff formatting are presentation-only test doubles;
// no modern outcome row, native proof or validator success is manufactured.
{
  const extract = name => {
    const value = source.match(new RegExp(`^function ${name}\\([^]*?^\\}`, 'm'))?.[0];
    assert.ok(value, 'actual ' + name + ' implementation found');
    return value;
  };
  const constant = name => {
    const key = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const value = source.match(new RegExp('^const ' + key + ' = .+;$', 'm'))?.[0];
    assert.ok(value, 'actual ' + name + ' declaration found');
    return value;
  };
  const main = { innerHTML: '' }, saved = new Map();
  const S = { data: { season: 2026, week: 7 }, games: {}, byId: {}, mine: [] };
  const context = { S,
    document: { querySelector: selector => { assert.equal(selector, '#main'); return main; } },
    localStorage: { getItem: key => saved.has(key) ? saved.get(key) : null,
      setItem: (key, value) => saved.set(key, String(value)) },
    kickoffText: () => 'Fictional scheduled kickoff' };
  vm.createContext(context);
  vm.runInContext(['$', 'esc', 'fmt', 'logo', 'ml'].map(constant).join('\n') + '\n'
    + ['gameStatus', 'gameBetLabel', 'gameBetStatus', 'resBadge', 'renderMine', 'store'].map(extract).join('\n'), context);
  let checks = 0;
  const check = (name, run) => { run(); checks++; };
  const game = (state = 'in', home = 30, away = 30, detail = 'Live') => ({
    id: 'fixture-game', state, home: 'QAA', away: 'QAB', home_score: home, away_score: away,
    detail, kickoff: '2026-10-24T12:00:00Z', offered_total: 99.5 });
  const pick = (market = 'total', side = 'over', line = 50) => ({
    kind: 'game', gid: 'fixture-game', market, side, line, odds: null,
    season: 2026, week: 7, at: 1 });
  const state = (g, m) => { S.games = { 'fixture-game': g }; S.mine = [m]; return context.gameBetStatus(m); };
  for (const [score, result] of [[20, 'below'], [25, 'equal'], [30, 'above']]) check('provisional total ' + result, () => {
    const status = state(game('in', score, score), pick());
    assert.equal(status.res, result); assert.equal(status.final, false);
    const badge = context.resBadge(status);
    assert.ok(badge.includes('CURRENTLY ' + result.toUpperCase())); assert.doesNotMatch(badge, /HIT|MISS|WIN|LOSS|CLEARED|LOST/);
    context.renderMine(); assert.doesNotMatch(main.innerHTML, /class="entry |All \d+ together/);
    assert.match(main.innerHTML, /Final wins/);
  });
  const finals = [
    ['total', 'over', 43.5, 24, 20, 'hit'], ['total', 'under', 43.5, 24, 20, 'miss'],
    ['total', 'over', 44, 24, 20, 'push'], ['total', 'under', 44, 24, 20, 'push'],
    ['spread', 'QAA', -3.5, 24, 20, 'hit'], ['spread', 'QAB', 3.5, 24, 20, 'miss'],
    ['spread', 'QAA', -4, 24, 20, 'push'], ['spread', 'QAB', 4, 24, 20, 'push'],
    ['ml', 'QAA', null, 24, 20, 'hit'], ['ml', 'QAB', null, 24, 20, 'miss'],
    ['ml', 'QAA', null, 0, 0, 'push'], ['total', 'under', .5, 0, 0, 'hit'],
    ['spread', 'QAA', 0, 0, 0, 'push'], ['total', 'over', 0, 0, 0, 'push'],
  ];
  for (const [market, side, line, home, away, result] of finals) check('final ' + market + ' ' + side + ' ' + line, () => {
    const status = state(game('post', home, away, 'Final'), pick(market, side, line));
    assert.equal(status.res, result); assert.equal(status.final, true);
  });
  for (const detail of ['Final/OT', 'Final/2OT', ' final ']) check('supported final marker ' + detail, () => {
    const status = state(game('post', 24, 20, detail), pick('ml', 'QAA', null));
    assert.equal(status.res, 'hit'); assert.equal(status.final, true);
  });
  for (const detail of ['', null, {}, 'Postponed', 'Canceled', 'Suspended']) check('unconfirmed final marker', () => {
    const status = state(game('post', 24, 20, detail), pick());
    assert.equal(status.res, 'unresolved'); assert.equal(status.final, false);
    assert.doesNotThrow(() => context.renderMine());
  });
  for (const value of [undefined, null, NaN, Infinity, -Infinity, '0', -1, .5, Number.MAX_SAFE_INTEGER + 1]) {
    for (const side of ['home', 'away']) check('invalid ' + side + ' score ' + String(value), () => {
      const g = game('post', 0, 0, 'Final'); g[side + '_score'] = value;
      const status = state(g, pick()); assert.equal(status.res, 'unresolved'); assert.equal(status.final, false);
      assert.doesNotThrow(() => context.renderMine()); assert.match(main.innerHTML, /Score unavailable/);
    });
  }
  for (const m of [pick('total', 'QAA'), pick('spread', 'OTHER', 3.5), pick('ml', 'over', null),
    pick('unknown'), pick(null), pick({}), pick('total', null), pick('ml', {}, null),
    pick('total', 'over', null), pick('spread', 'QAA', Infinity), pick('total', 'over', '50'),
    pick('total', 'over', {}), pick('total', '\"><img src=x onerror=fixtureAttack>', 50),
    pick('total', 'over', '\"><img src=x onerror=fixtureAttack>')]) check('malformed stored game field', () => {
    const status = state(game('post', 24, 20, 'Final'), m);
    const original = '  ' + JSON.stringify([m]) + '  '; saved.set('nflprops.mine', original);
    assert.equal(status.res, 'unresolved'); assert.equal(status.final, false);
    assert.doesNotThrow(() => context.renderMine());
    assert.match(main.innerHTML, /UNRESOLVED/); assert.doesNotMatch(main.innerHTML, /onerror=fixtureAttack/);
    assert.equal(saved.get('nflprops.mine'), original);
  });
  check('malformed displayed moneyline odds cannot throw or change a stored selection', () => {
    const m = pick('ml', 'QAA', null); m.odds = { unsupported: true };
    state(game('post', 24, 20, 'Final'), m);
    const original = JSON.stringify([m]); saved.set('nflprops.mine', original);
    assert.doesNotThrow(() => context.renderMine()); assert.equal(saved.get('nflprops.mine'), original);
    assert.match(main.innerHTML, /QAA to win/); assert.doesNotMatch(main.innerHTML, /\[object Object\]/);
  });
  for (const m of [pick('spread', 'QAA', -3.5), pick('ml', 'QAB', null)]) check('other live markets stay provisional', () => {
    const status = state(game('in', 24, 20), m); assert.equal(status.final, false); assert.equal(status.res, 'live');
    assert.doesNotMatch(context.resBadge(status), /HIT|MISS|WIN|LOSS|CLEARED|LOST/);
  });
  check('pregame and missing games are not settled', () => {
    assert.equal(state(game('pre', 24, 20, 'Final'), pick()), null);
    S.games = {}; assert.equal(context.gameBetStatus(pick()), null);
  });
  for (const phase of [undefined, null, 'unknown', {}]) check('unsupported game phase is unresolved', () => {
    const status = state(game(phase, 24, 20, 'Final'), pick());
    // Explicit assignment also covers undefined rather than the fixture default.
    S.games['fixture-game'].state = phase;
    const actual = context.gameBetStatus(S.mine[0]);
    assert.equal(actual.res, 'unresolved'); assert.equal(actual.final, false);
    assert.doesNotThrow(() => context.renderMine()); assert.match(main.innerHTML, /UNRESOLVED/);
  });
  check('saved game identity matches explicit string/number IDs only', () => {
    for (const [stored, actual] of [['123', 123], [123, '123'], [0, '0']]) {
      const m = pick('ml', 'QAA', null); m.gid = stored;
      const g = game('post', 24, 20, 'Final'); g.id = actual;
      S.games = { [String(stored)]: g }; S.mine = [m];
      const status = context.gameBetStatus(m); assert.equal(status.res, 'hit'); assert.equal(status.final, true);
    }
    const m = pick(); const g = game('post', 24, 20, 'Final'); g.id = 'wrong-game';
    const status = state(g, m); assert.equal(status.res, 'unresolved'); assert.equal(status.final, false);
    context.renderMine(); assert.match(main.innerHTML, /Saved game identity unavailable/);
    assert.doesNotMatch(main.innerHTML, /data-rm-game=/);
  });
  for (const id of [null, {}, [], '', '   ', Infinity, .5, -1]) check('unusable saved game id is unresolved and retained', () => {
    const m = pick(); m.gid = id; S.games = {}; S.mine = [m];
    const original = JSON.stringify([m]); saved.set('nflprops.mine', original);
    const status = context.gameBetStatus(m); assert.equal(status.res, 'unresolved'); assert.equal(status.final, false);
    assert.doesNotThrow(() => context.renderMine()); assert.equal(saved.get('nflprops.mine'), original);
  });
  check('object identity fields are not coerced into another saved selection', () => {
    const id = { toString: 'unsupported' };
    S.games = {}; S.byId = {}; S.mine = [{ ...pick(), gid: id }, { pid: id, season: 2026, week: 7 }];
    const original = JSON.stringify(S.mine); saved.set('nflprops.mine', original);
    assert.doesNotThrow(() => context.renderMine()); assert.equal(saved.get('nflprops.mine'), original);
  });
  for (const value of [null, 1, 'unsupported', []]) check('unsupported direct saved selection', () => {
    const status = context.gameBetStatus(value); assert.equal(status.res, 'unresolved'); assert.equal(status.final, false);
  });
  for (const mine of [{}, [null], [1], ['unsupported'], [[]]]) check('malformed stored collection is retained', () => {
    S.mine = mine; const original = JSON.stringify(mine); saved.set('nflprops.mine', original);
    assert.doesNotThrow(() => context.renderMine()); assert.match(main.innerHTML, /unsupported record/);
    assert.equal(saved.get('nflprops.mine'), original);
  });
  for (const [result, text, final] of [['unresolved', 'UNRESOLVED', false], ['pending', 'PENDING', false],
    ['dnp', 'DNP', true], ['push', 'PUSH', true]]) check('presentation-only ' + result + ' badge', () => {
    assert.ok(context.resBadge({ res: result, final, reason: 'Fictional view-model status' }).includes(text));
  });
  check('only final individual result flags enter summary counters', () => {
    const text = extract('renderMine');
    const names = ['hit', 'miss', 'push', 'dnp', 'unresolved', 'final', 'live'];
    const declarations = names.map(name => {
      const value = text.match(new RegExp('^  const ' + name + ' = .+;$', 'm'))?.[0]; assert.ok(value); return value;
    });
    const projection = vm.runInContext('(rows)=>{' + declarations.join('\n') + ';return {hit,miss,push,dnp,unresolved,final,live};}', context);
    // Minimal renderer-status doubles, not source-qualified outcome records.
    const rows = [['hit', true, 'post'], ['miss', true, 'post'], ['push', true, 'post'], ['dnp', true, 'post'],
      ['unresolved', false, 'post'], ['hit', false, 'in'], ['miss', false, 'in'], ['push', false, 'in']]
      .map(([res, final, state]) => ({ st: { res, final }, g: { state } }));
    assert.equal(JSON.stringify(projection(rows)), JSON.stringify({ hit: 1, miss: 1, push: 1, dnp: 1, unresolved: 1, final: 4, live: 3 }));
  });
  check('personal line and legacy bytes survive rendering and score corrections', () => {
    const m = pick('total', 'over', 50), old = { pid: 'old-fixture-player', key: 'rec', dir: 'under',
      line: 5.5, season: 2025, week: 1, at: 0 };
    state(game('post', 20, 20, 'Final'), m); S.mine.push(old);
    const original = '  ' + JSON.stringify(S.mine) + '  '; saved.set('nflprops.mine', original);
    assert.equal(context.gameBetStatus(m).res, 'miss'); context.renderMine(); assert.match(main.innerHTML, /value="50"/);
    S.games['fixture-game'].home_score = 40;
    assert.equal(context.gameBetStatus(m).res, 'hit'); context.renderMine();
    assert.equal(m.line, 50); assert.equal(saved.get('nflprops.mine'), original);
    assert.equal(context.store('mine')[0].line, 50); assert.equal(context.store('mine')[1].line, 5.5);
    assert.match(main.innerHTML, /Player-prop results still use/);
  });
  check('saved zero and half lines remain distinct from current offers', () => {
    for (const line of [0, 37.5]) {
      const m = pick('total', 'under', line); state(game('post', 24, 20, 'Final'), m);
      const original = JSON.stringify([m]); saved.set('nflprops.mine', original); context.renderMine();
      assert.ok(main.innerHTML.includes('value="' + line + '"'));
      assert.equal(saved.get('nflprops.mine'), original); assert.notEqual(m.line, S.games['fixture-game'].offered_total);
    }
  });
  check('game finality needs no prop settlement loader or evidence Map', () => {
    assert.equal(Object.hasOwn(S, 'finalOutcomes'), false);
    assert.equal('propStatus' in context, false); assert.equal('loadGrading' in context, false);
  });
  console.log('Game-market finality: ' + checks + ' scoped source/render/storage checks passed; prop-evidence settlement remains separate.');
}
