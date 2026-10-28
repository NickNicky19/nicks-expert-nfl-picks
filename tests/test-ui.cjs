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

// Player-prop evidence correction: fictional event bodies and device records.
// Execute actual app functions/events; no network, provider outcomes or models.
(async () => {
  const legacyPins = {"current": "3657b210f1dbcc49a1a2339c8331a732e9eabe7a750b3df875578738747848b3", "slpPlayed": "938a0262a1f0e57b3412bf934c0749083bc3dc372d5a27477694cd123f1c7ad4"};
  for (const [name, expected] of Object.entries(legacyPins)) {
    const fn = source.match(new RegExp('^function '+name+'\\([\\s\\S]*?^\\}', 'm'))?.[0];
    assert.equal(require('node:crypto').createHash('sha256').update(fn).digest('hex'), expected);
  }
  const failures = []; let checks = 0;
  const test = async (name, run) => {
    checks++;
    try { await run(); } catch (error) { failures.push({ name, error: error.message }); }
  };
  const harness = () => {
    const nodes = new Map(), saved = new Map(), events = {};
    const node = name => {
      if (!nodes.has(name)) nodes.set(name, { innerHTML: '', hidden: false, style: {},
        addEventListener() {}, classList: { add() {}, remove() {}, toggle() {} }, querySelectorAll: () => [] });
      return nodes.get(name);
    };
    const box = { console, Date, URL, URLSearchParams, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1,
      localStorage: { getItem: k => saved.get(k) ?? null, setItem: (k, v) => saved.set(k, String(v)) },
      document: { hidden: true, querySelector: node, querySelectorAll: () => [], body: node('body'),
        documentElement: node('html'), addEventListener: (kind, fn) => (events[kind] ||= []).push(fn) },
      location: { hash: '' }, history: {}, navigator: {}, CSS: { escape: x => x },
      addEventListener() {}, innerWidth: 390, scrollY: 0, scrollTo() {}, confirm: () => true,
      fetch: async () => { throw new Error('ACTUAL_NETWORK_FORBIDDEN'); } };
    box.window = box;
    vm.createContext(box);
    vm.runInContext(source.slice(0, source.indexOf('(async function start()')), box);
    const S = vm.runInContext('S', box);
    S.data = { season: 2099, week: 2, players: [], games: [], scoring: {}, categories: { rush_yd: { label: 'Rush Yds' } } };
    const p = { id: 'fictional-player', espn_id: '900000001', name: 'Fictional Player', team: 'QAA', pos: 'RB',
      game_id: '900000101', props: [{ key: 'rush_yd', line: 5.5 }], log: [], actual: null };
    const g = { id: p.game_id, home: 'QAA', away: 'QAB', state: 'post', detail: 'Final',
      kickoff: '2099-10-25T17:00:00Z', home_score: 0, away_score: 0 };
    S.data.players = [p]; S.data.games = [g]; S.byId = { [p.id]: p }; S.games = { [g.id]: g };
    S.byKey = { 'fictional player|QAA': p.id }; S.byEspn = { [p.espn_id]: p.id };
    S.slpOk = false; S.slp = {}; S.live = {};
    vm.runInContext('applyInjuries=()=>{}; defenseFromSummary=()=>({});', box);
    const pick = () => ({ pid: p.id, key: 'rush_yd', dir: 'under', line: 5.5, season: 2099, week: 2, at: 1,
      schema_version: 'mypicks-player-game-v1', gid: g.id, team: p.team, espn_id: p.espn_id,
      kickoff: g.kickoff, period: 'full_game_including_overtime', stat_source: 'ESPN_EVENT_BOXSCORE' });
    const summary = (yards = '0', attempts = '1', opts = {}) => ({
      header: { id: g.id, season: { year: 2099, type: 2 }, week: { number: 2 }, competitions: [{ id: g.id, date: g.kickoff,
        status: { type: { state: opts.state || 'post', shortDetail: opts.detail || 'Final', completed: opts.completed ?? true } } }] },
      boxscore: { players: [{ team: { abbreviation: 'QAA' }, statistics: [{ name: 'rushing', labels: ['CAR', 'YDS', 'TD'],
        athletes: [{ athlete: { id: opts.athlete || p.espn_id, displayName: 'Fictional Player' },
          ...(opts.dnp == null ? {} : { didNotPlay: opts.dnp }), stats: [attempts, yards, '0'] }] }] }] } });
    const apply = value => box.applySummary(g.id, value, S.data);
    const status = (m = pick()) => box.propStatus(p, m.key, m.line, m.dir, m);
    return { box, S, p, g, pick, summary, apply, status, saved, events, main: node('#main') };
  };
  for (const flag of ['missing', 'sleeper_ok', 'box_loaded', 'INA', 'gp_zero']) await test('unknown is not zero/DNP: ' + flag, () => {
    const h = harness();
    if (flag === 'sleeper_ok') h.S.slpOk = true;
    if (flag === 'box_loaded') h.S.boxLoaded.add(h.g.id);
    if (flag === 'INA') h.p.injury = 'Out';
    if (flag === 'gp_zero') h.S.slp[h.p.id] = { gp: 0, pts_ppr: 0, rush_yd: 0 };
    const st = h.status(); assert.equal(st.final, false); assert.equal(st.res, 'unresolved'); assert.equal(st.v, null);
    // V2 deliberately restores the shared fantasy helpers; prop status above remains independently strict.
  });
  await test('played zero is a real final zero; integer equality is a push', () => {
    const h = harness(); h.apply(h.summary('0', '1'));
    assert.equal(h.status().v, 0); assert.equal(h.status().res, 'hit');
    const m = h.pick(); m.line = 0; assert.equal(h.status(m).res, 'push'); assert.equal(h.status(m).final, true);
  });
  await test('positive explicit DNP is distinct from missing data', () => {
    const h = harness(); h.apply(h.summary('--', '--', { dnp: true }));
    assert.equal(h.status().res, 'dnp'); assert.equal(h.status().final, true); assert.equal(h.status().v, null);
  });
  await test('contradictory DNP and nonzero observed statistics stay unresolved', () => {
    const h = harness(); h.apply(h.summary('4', '1', { dnp: true }));
    assert.equal(h.status().res, 'unresolved'); assert.equal(h.status().final, false);
  });
  for (const value of [undefined, null, '--', '', 'NaN', 'Infinity']) await test('missing/malformed field: ' + String(value), () => {
    const h = harness(); h.apply(h.summary(value, '1')); // Explicitly overwrite the defaulted parameter.
    const body = h.summary('0', '1'); body.boxscore.players[0].statistics[0].athletes[0].stats[1] = value; h.apply(body);
    assert.equal(h.status().res, 'unresolved'); assert.equal(h.status().final, false); assert.equal(h.status().v, null);
  });
  for (const detail of ['Postponed', 'Canceled', 'Suspended', '', null]) await test('post is not confirmed Final: ' + detail, () => {
    const h = harness(); h.g.detail = detail; h.apply(h.summary('9', '1'));
    assert.equal(h.status().final, false); assert.notEqual(h.status().res, 'hit'); assert.notEqual(h.status().res, 'miss');
  });
  await test('summary still live cannot finalize after scoreboard transitions to Final', () => {
    const h = harness(); h.apply(h.summary('9', '1', { state: 'in', detail: 'Q4', completed: false }));
    assert.equal(h.status().final, false);
  });
  for (const detail of ['Final', 'Final/OT', 'Final/2OT']) await test('confirmed final marker: ' + detail, () => {
    const h = harness(); h.g.detail = detail; h.apply(h.summary('9', '1', { detail }));
    assert.equal(h.status().final, true); assert.equal(h.status().res, 'miss');
  });
  await test('live over is provisional and signed-yardage corrections can reverse it', () => {
    const h = harness(); h.g.state = 'in'; h.g.detail = 'Q3'; const m = h.pick(); m.dir = 'over'; m.line = 0;
    h.apply(h.summary('7', '1', { state: 'in', detail: 'Q3', completed: false }));
    assert.equal(h.status(m).final, false); assert.equal(h.status(m).res, 'live');
    h.apply(h.summary('-1', '1', { state: 'in', detail: 'Q4', completed: false }));
    assert.equal(h.status(m).v, -1); assert.equal(h.status(m).final, false);
    h.g.state = 'post'; h.g.detail = 'Final'; h.apply(h.summary('-1', '1'));
    assert.equal(h.status(m).res, 'miss'); assert.equal(h.status(m).final, true);
    h.apply(h.summary('1', '1')); assert.equal(h.status(m).res, 'hit');
  });
  for (const field of ['gid', 'pid', 'team', 'espn_id', 'kickoff', 'week', 'season', 'period', 'stat_source', 'schema_version']) {
    await test('saved binding cannot be repointed: ' + field, () => {
      const h = harness(); h.apply(h.summary('0', '1')); const m = h.pick(); m[field] = typeof m[field] === 'number' ? -1 : 'wrong-binding';
      assert.equal(h.status(m).res, 'unresolved'); assert.equal(h.status(m).final, false);
    });
  }
  for (const type of ['wrong-event', 'wrong-athlete', 'wrong-team', 'same-name', 'wrong-season']) await test('source identity: ' + type, () => {
    const h = harness(); const body = h.summary('0', '1');
    if (type === 'wrong-event') body.header.id = '900000999';
    if (type === 'wrong-athlete' || type === 'same-name') body.boxscore.players[0].statistics[0].athletes[0].athlete.id = '900000999';
    if (type === 'wrong-team') body.boxscore.players[0].team.abbreviation = 'QAB';
    if (type === 'wrong-season') body.header.season.year = 2098;
    h.apply(body); assert.equal(h.status().res, 'unresolved'); assert.equal(h.status().final, false);
  });
  await test('partial combined categories never pad missing fields with zero', () => {
    const h = harness(); h.apply(h.summary('0', '1')); const m = h.pick(); m.key = 'rush_rec_yd';
    assert.equal(h.status(m).res, 'unresolved'); assert.equal(h.status(m).v, null);
  });
  for (const value of [{}, { toString: 'unsupported' }, [], true]) await test('malformed saved provider identity stays unresolved', () => {
    const h = harness(); h.apply(h.summary('0', '1')); const m = h.pick(); m.espn_id = value;
    assert.equal(h.status(m).res, 'unresolved'); assert.equal(h.status(m).final, false);
    h.S.mine = [m]; const raw = JSON.stringify([m]); h.saved.set('nflprops.mine', raw);
    assert.doesNotThrow(() => h.box.renderMine()); assert.equal(h.saved.get('nflprops.mine'), raw);
  });
  await test('duplicate provider identity cannot resolve a player by name', () => {
    const h = harness(); h.S.data.players.push({ ...h.p, id: 'other-fictional-player' }); h.apply(h.summary('0', '1'));
    assert.equal(h.status().res, 'unresolved'); assert.equal(h.status().final, false);
  });
  await test('provided wrong source week and wrong source kickoff cannot finalize', () => {
    const h = harness(); let body = h.summary('0', '1'); body.header.week = 3; h.apply(body);
    assert.equal(h.status().res, 'unresolved');
    body = h.summary('0', '1'); body.header.competitions[0].date = '2099-10-26T17:00:00Z'; h.apply(body);
    assert.equal(h.status().res, 'unresolved');
  });
  await test('source success followed by a missing field clears the prior final value', () => {
    const h = harness(); h.apply(h.summary('0', '1')); assert.equal(h.status().res, 'hit');
    h.apply(h.summary('--', '1')); assert.equal(h.status().res, 'unresolved'); assert.equal(h.status().v, null);
  });
  await test('legacy picks render unresolved and keep original storage bytes', () => {
    const h = harness(); h.apply(h.summary('0', '1')); const m = { ...h.pick() }; delete m.gid; delete m.schema_version;
    h.S.mine = [m]; const raw = ' \n[ ' + JSON.stringify(m) + ' ]\n'; h.saved.set('nflprops.mine', raw);
    h.box.renderMine(); assert.match(h.main.innerHTML, /UNRESOLVED/); assert.equal(h.saved.get('nflprops.mine'), raw);
    assert.equal(m.gid, undefined); assert.equal(m.line, 5.5);
  });
  await test('adding a bound new pick preserves an unbound record and its exact JSON bytes', () => {
    const h = harness(); const old = '{ "pid":"fictional-player", "key":"rush_yd", "dir":"under", "line":5.50, "season":2099, "week":2, "at":0, "note":"comma, quote\\\" and slash\\\\" }';
    h.saved.set('nflprops.mine', '[\n' + old + '\n]'); h.S.mine = JSON.parse(h.saved.get('nflprops.mine'));
    assert.equal(h.box.minePick(h.p.id, 'rush_yd', 'under'), undefined);
    h.box.toggleMine(h.p.id, 'rush_yd', 'over', 9.5);
    const raw = h.saved.get('nflprops.mine'); assert.ok(raw.includes(old));
    const records = JSON.parse(raw); assert.equal(records.length, 2); assert.equal(records[0].line, 5.5); assert.equal(records[0].gid, undefined);
    assert.equal(records[1].gid, h.g.id); assert.equal(records[1].period, 'full_game_including_overtime');
  });
  await test('personal line edits target the exact record; unchanged legacy bytes survive reload', () => {
    const h = harness(); const old = '{ "pid":"fictional-player", "key":"rush_yd", "dir":"under", "line":5.50, "season":2099, "week":2, "at":0 }';
    const m = h.pick(); h.saved.set('nflprops.mine', '[\n' + old + ',\n' + JSON.stringify(m) + ']'); h.S.mine = JSON.parse(h.saved.get('nflprops.mine'));
    const target = { dataset: { mline: 'p', mineIndex: '1' }, value: '0', matches: () => false };
    for (const fn of h.events.change) fn({ target });
    const raw = h.saved.get('nflprops.mine'); assert.ok(raw.includes(old));
    const records = JSON.parse(raw); assert.equal(records[0].line, 5.5); assert.equal(records[1].line, 0);
    assert.equal(records[0].gid, undefined); assert.equal(records[1].gid, h.g.id);
    assert.equal(h.box.store('mine')[1].line, 0);
  });
  await test('late previous-period Sleeper response never contaminates a new board', async () => {
    const h = harness(); h.g.state = 'in'; let finish;
    h.box.fixtureGetJSON = () => new Promise(resolve => { finish = resolve; });
    vm.runInContext('getJSON=(...args)=>fixtureGetJSON(...args)', h.box);
    const pending = h.box.pollSleeper(); const old = h.S.data; h.S.data = { ...old, week: 3 };
    finish([{ player_id: h.p.id, stats: { gp: 1, rush_yd: 99 } }]); await pending;
    assert.equal(h.S.propSleeper, null); assert.equal(h.S.slp[h.p.id], undefined);
  });
  await test('completed events are refreshed despite healthy Sleeper/final cache, allowing corrections', async () => {
    const h = harness(); h.S.slpOk = true; h.S.boxFinal.add(h.g.id); let gets = 0;
    h.box.fixtureGetJSON = async () => { gets++; return h.summary(gets === 1 ? '9' : '0', '1'); };
    vm.runInContext('getJSON=(...args)=>fixtureGetJSON(...args)', h.box);
    await h.box.pollBoxScores(); assert.equal(h.status().res, 'miss');
    await h.box.pollBoxScores(); assert.equal(h.status().res, 'hit'); assert.equal(gets, 2);
  });
  for (const [name, completed] of [['missing', undefined], ['null', null], ['zero', 0],
    ['string-false', 'false'], ['false', false], ['true', true]]) {
    await test('polled summary requires explicit boolean completion: ' + name, async () => {
      const h = harness(), body = h.summary('0', '1');
      const status = body.header.competitions[0].status.type;
      if (name === 'missing') delete status.completed;
      else status.completed = completed;
      const original = JSON.stringify(body); let gets = 0;
      h.box.fixtureGetJSON = async url => {
        assert.equal(url, 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=' + h.g.id);
        gets++; return body;
      };
      vm.runInContext('getJSON=(...args)=>fixtureGetJSON(...args)', h.box);
      await h.box.pollBoxScores();
      const result = h.status();
      assert.equal(gets, 1); assert.equal(JSON.stringify(body), original);
      assert.equal(result.v, 0);
      assert.equal(result.final, completed === true);
      assert.equal(result.res, completed === true ? 'hit' : 'pending');
    });
  }
  console.log(JSON.stringify({ suite: 'player-prop-evidence-v1', fictional_cases: checks, failures }));
  assert.equal(failures.length, 0, 'player-prop evidence regressions: ' + JSON.stringify(failures));
})().catch(error => { console.error(error); process.exitCode = 1; });

// V2: mandatory provider identity/scope; local observation time is not availability proof.
{
  const extract=(text,name)=>{const m=text.match(new RegExp('^function '+name+'\\([\\s\\S]*?^\\}', 'm'));assert.ok(m,name);return m[0];};
function identityProbe(mutate){
  const S={data:{season:2099,week:2,players:[]},games:{},propEvents:{},propSleeper:null};
  const p={id:'fictional-p',espn_id:'900000001',game_id:'900000101',team:'QAA'};
  const g={id:p.game_id,home:'QAA',away:'QAB',kickoff:'2099-10-25T17:00:00Z',state:'post',detail:'Final'};
  S.data.players=[p];S.games[g.id]=g;
  const body={header:{id:g.id,season:{year:2099,type:2},week:{number:2},competitions:[{id:g.id,date:g.kickoff,
    status:{type:{state:'post',shortDetail:'Final',completed:true}}}]},boxscore:{players:[{team:{abbreviation:'QAA'},statistics:[{
      name:'rushing',labels:['CAR','YDS','TD'],athletes:[{athlete:{id:p.espn_id},stats:['1','0','0']}]}]}]}};
  mutate(body,S,g);
  const c={S,teamCode:x=>x};vm.createContext(c);
  vm.runInContext(['propFinal','propValue','propPickBound','recordPropEvidence','propStatus'].map(n=>extract(source,n)).join('\n'),c);
  const m={pid:p.id,gid:g.id,team:p.team,espn_id:p.espn_id,kickoff:g.kickoff,season:S.data.season,week:S.data.week,
    schema_version:'mypicks-player-game-v1',period:'full_game_including_overtime',stat_source:'ESPN_EVENT_BOXSCORE'};
  c.recordPropEvidence(g.id,body,S.data);
  const entry=S.propEvents[g.id];
  return {status:c.propStatus(p,'rush_yd',5.5,'under',m),stored_scope:entry?{
    season:entry.season,week:entry.week,kickoff:entry.kickoff,observed_at:entry.observed_at,final:entry.final}:null};
}
const invalid=[
["missing-season",b=>{delete b.header.season;}],
["missing-season-year",b=>{delete b.header.season.year;}],
["missing-season-type",b=>{delete b.header.season.type;}],
["null-season",b=>{b.header.season=null;}],
["null-year",b=>{b.header.season.year=null;}],
["string-year",b=>{b.header.season.year='2099';}],
["wrong-season",b=>{b.header.season.year=2098;}],
["wrong-season-type",b=>{b.header.season.type=3;}],
["missing-week",b=>{delete b.header.week;}],
["missing-week-number",b=>{delete b.header.week.number;}],
["null-week",b=>{b.header.week=null;}],
["string-week",b=>{b.header.week='2';}],
["wrong-week",b=>{b.header.week.number=3;}],
["missing-kickoff",b=>{delete b.header.competitions[0].date;}],
["null-kickoff",b=>{b.header.competitions[0].date=null;}],
["invalid-kickoff",b=>{b.header.competitions[0].date='not-a-date';}],
["kickoff-without-timezone",b=>{b.header.competitions[0].date='2099-10-25T17:00:00';}],
["wrong-kickoff",b=>{b.header.competitions[0].date='2099-10-26T17:00:00Z';}],
["wrong-event-id",b=>{b.header.id='900000999';}],
["wrong-competition-id",b=>{b.header.competitions[0].id='900000999';}],
["wrong-team",b=>{b.boxscore.players[0].team.abbreviation='QAB';}],
["wrong-athlete",b=>{b.boxscore.players[0].statistics[0].athletes[0].athlete.id='900000999';}],
["all-required-scope-absent",b=>{delete b.header.season;delete b.header.week;delete b.header.competitions[0].date;}]
];
for(const [name,mutate]of invalid){
  const result=identityProbe(mutate);
  assert.equal(result.status.res,'unresolved',name);
  assert.equal(result.status.final,false,name);
  assert.equal(result.status.v,null,name);
}
const complete=identityProbe(()=>{});
assert.equal(complete.status.res,'hit');assert.equal(complete.status.v,0);assert.equal(complete.status.final,true);
const offset=identityProbe(b=>{b.header.competitions[0].date='2099-10-25T12:00:00-05:00';b.header.week=2;});
assert.equal(offset.status.final,true);assert.equal(offset.status.v,0);
console.log(JSON.stringify({suite:'v2-strict-provider-scope',invalid_cases:invalid.length,valid_cases:2,failures:0}));
}

// V2 preserves the legacy fantasy path, including separately recorded missing-data debt.
{
const policy={"scoring":{"pass_yd":0.04,"pass_td":4,"pass_int":-1,"pass_2pt":2,"rush_yd":0.1,"rush_td":6,"rush_2pt":2,"rec":1,"rec_yd":0.1,"rec_td":6,"rec_2pt":2,"fum_lost":-2,"st_td":6,"st_fum_rec":1,"st_ff":1,"fum_rec_td":6,"idp_blk_kick":2},"scoring_k":{"fgm_0_19":3,"fgm_20_29":3,"fgm_30_39":3,"fgm_40_49":4,"fgm_50_59":5,"fgm_60p":6,"xpm":1,"fgmiss":-1},"scoring_def":{"sack":1,"int":2,"fum_rec":2,"def_st_fum_rec":2,"blk_kick":2,"safe":2,"def_td":6,"def_st_td":6},"def_tiers":{"pts":[[0,5],[6,4],[13,3],[17,1],[27,0],[34,-1],[45,-3],[1000000,-5]],"yds":[[99,5],[199,3],[299,2],[349,0],[399,-1],[449,-3],[499,-5],[549,-6],[1000000,-7]]}};
const cases=[{"name":"missing-player-row","pos":"WR","stats":null,"expected":{"participation":null,"current":{"stats":{},"none":true},"live_points":null,"week_points":0},"fallback":null},{"name":"gp-zero-points-zero-is-not-participation","pos":"WR","stats":{"gp":0,"pts_ppr":0},"expected":{"participation":true,"current":{"stats":{"gp":0,"pts_ppr":0},"none":false},"live_points":0,"week_points":0},"fallback":null},{"name":"points-zero-alone-is-not-participation","pos":"WR","stats":{"pts_ppr":0},"expected":{"participation":true,"current":{"stats":{"pts_ppr":0},"none":false},"live_points":0,"week_points":0},"fallback":null},{"name":"played-skill-zero","pos":"RB","stats":{"rush_att":1,"rush_yd":0,"pts_ppr":0},"expected":{"participation":true,"current":{"stats":{"rush_att":1,"rush_yd":0,"pts_ppr":0},"none":false},"live_points":0,"week_points":0},"fallback":null},{"name":"kicker-positive-field-goal-no-gp","pos":"K","stats":{"fgm":1,"fgm_20_29":1,"pts_ppr":3},"expected":{"participation":true,"current":{"stats":{"fgm":1,"fgm_20_29":1,"pts_ppr":3},"none":false},"live_points":3,"week_points":3},"fallback":null},{"name":"kicker-positive-extra-point-no-gp","pos":"K","stats":{"xpm":1,"pts_ppr":1},"expected":{"participation":true,"current":{"stats":{"xpm":1,"pts_ppr":1},"none":false},"live_points":1,"week_points":1},"fallback":null},{"name":"kicker-played-zero-missed-XP","pos":"K","stats":{"xpmiss":1,"pts_ppr":0},"expected":{"participation":true,"current":{"stats":{"xpmiss":1,"pts_ppr":0},"none":false},"live_points":0,"week_points":0},"fallback":null},{"name":"defense-positive-sack-no-gp","pos":"DEF","stats":{"sack":1,"pts_allow":7,"yds_allow":100,"pts_ppr":7},"expected":{"participation":true,"current":{"stats":{"sack":1,"pts_allow":7,"yds_allow":100,"pts_ppr":7},"none":false},"live_points":7,"week_points":7},"fallback":null},{"name":"defense-played-zero-known-allowances","pos":"DEF","stats":{"pts_allow":20,"yds_allow":320,"pts_ppr":0},"expected":{"participation":true,"current":{"stats":{"pts_allow":20,"yds_allow":320,"pts_ppr":0},"none":false},"live_points":0,"week_points":0},"fallback":null},{"name":"receiving-two-point-only","pos":"TE","stats":{"rec_2pt":1,"pts_ppr":2},"expected":{"participation":true,"current":{"stats":{"rec_2pt":1,"pts_ppr":2},"none":false},"live_points":2,"week_points":2},"fallback":null},{"name":"passing-two-point-only","pos":"QB","stats":{"pass_2pt":1,"pts_ppr":2},"expected":{"participation":true,"current":{"stats":{"pass_2pt":1,"pts_ppr":2},"none":false},"live_points":2,"week_points":2},"fallback":null},{"name":"rushing-two-point-only","pos":"RB","stats":{"rush_2pt":1,"pts_ppr":2},"expected":{"participation":true,"current":{"stats":{"rush_2pt":1,"pts_ppr":2},"none":false},"live_points":2,"week_points":2},"fallback":null},{"name":"special-teams-touchdown-only","pos":"WR","stats":{"st_td":1,"pts_ppr":6},"expected":{"participation":true,"current":{"stats":{"st_td":1,"pts_ppr":6},"none":false},"live_points":6,"week_points":6},"fallback":null},{"name":"offensive-blocked-kick-only","pos":"TE","stats":{"idp_blk_kick":1,"pts_ppr":2},"expected":{"participation":true,"current":{"stats":{"idp_blk_kick":1,"pts_ppr":2},"none":false},"live_points":2,"week_points":2},"fallback":null},{"name":"fumble-negative-only","pos":"WR","stats":{"fum_lost":1,"pts_ppr":-2},"expected":{"participation":true,"current":{"stats":{"fum_lost":1,"pts_ppr":-2},"none":false},"live_points":-2,"week_points":-2},"fallback":null},{"name":"fresh-kicker-row-versus-older-build","pos":"K","stats":{"fgm":1,"fgm_20_29":1,"pts_ppr":3},"expected":{"participation":true,"current":{"stats":{"fgm":1,"fgm_20_29":1,"pts_ppr":3},"none":false},"live_points":3,"week_points":3},"fallback":{"xpm":1,"pts_ppr":1}},{"name":"skill-participation-without-scoring-fields","pos":"WR","stats":{"gp":1},"expected":{"current":{"stats":{"gp":1},"none":false},"live_points":0,"week_points":0},"fallback":null},{"name":"defense-participation-without-allowances","pos":"DEF","stats":{"gp":1},"expected":{"current":{"stats":{"gp":1},"none":false},"live_points":10,"week_points":10},"fallback":null}];
const extract=(name)=>{const m=source.match(new RegExp('^function '+name+'\\([\\s\\S]*?^\\}', 'm'));assert.ok(m,name);return m[0];};
const names=['current','slpPlayed','livePPR','ppr','fantasyPts','skillPts','currentLeague','scoreWith','derivedStat','weekPts'];
for(const row of cases){
  const S={data:{...policy,season:2099,week:2},sc:{mode:'sleeper',half:false},leagues:[],games:{g:{id:'g',state:'post',detail:'Final'}},
    slp:row.stats==null?{}:{p:row.stats},live:{},slpOk:true,boxLoaded:new Set(),boxFinal:new Set()};
  const p={id:'p',game_id:'g',pos:row.pos,actual:row.fallback?{stats:row.fallback}:null};
  const c={S};vm.createContext(c);vm.runInContext(names.map(extract).join('\n'),c);
  const actual={current:c.current(p),live_points:c.livePPR(p),week_points:c.weekPts(p)};
  if(Object.hasOwn(row.expected,'participation'))actual.participation=row.stats?c.slpPlayed(row.stats):null;
  assert.deepEqual(JSON.parse(JSON.stringify(actual)),row.expected,row.name);
}
console.log(JSON.stringify({suite:'v2-downstream-legacy-preservation',cases:cases.length,failures:0,
  legacy_missing_data_debt_fixed:false,new_values_introduced:false}));
}


// FPts is a preserved current-scoring display, never a certified saved outcome.
// Actual application functions run in a DOM/storage VM with fictional rows;
// HTTP/timers are disabled. Existing strict eleven-stat controls above remain.
{
  const scoring = {pass_yd:.04,pass_td:4,pass_int:-1,pass_2pt:2,rush_yd:.1,rush_td:6,rush_2pt:2,
    rec:1,rec_yd:.1,rec_td:6,rec_2pt:2,fum_lost:-2,st_td:6,st_fum_rec:1,st_ff:1,fum_rec_td:6,idp_blk_kick:2};
  const complete = () => ({...Object.fromEntries(Object.keys(scoring).map(k=>[k,0])),gp:1,rush_att:1,
    rush_yd:10,rec:4,rec_yd:40,rec_td:1,pts_ppr:15});
  function setupFantasy() {
    const nodes = new Map(), stored = new Map();
    const node = key => {
      if (!nodes.has(key)) nodes.set(key,{innerHTML:'',hidden:false,style:{},addEventListener(){},
        classList:{add(){},remove(){},toggle(){}},querySelectorAll:()=>[]});
      return nodes.get(key);
    };
    const box = {console,Date,URL,URLSearchParams,setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,
      localStorage:{getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,String(v))},
      document:{hidden:true,querySelector:node,querySelectorAll:()=>[],body:node('body'),
        documentElement:node('html'),addEventListener(){}},location:{hash:''},history:{},navigator:{},
      CSS:{escape:x=>x},addEventListener(){},innerWidth:390,scrollY:0,scrollTo(){},confirm:()=>true,
      fetch:async()=>{throw Error('NETWORK_FORBIDDEN');}};
    box.window=box;vm.createContext(box);
    const start=source.indexOf('(async function start()');assert.ok(start>0);
    vm.runInContext(source.slice(0,start),box);
    const state=vm.runInContext('S',box);
    state.data={season:2099,week:2,scoring,scoring_def:{},def_tiers:{pts:[[1000000,5]],yds:[[1000000,5]]},
      categories:{fpts:{label:'Fantasy Points',lean:1},rush_yd:{label:'Rush Yards',lean:4}},
      execution_model:{model:'sleeper-matchup-classic-fg-identity-v1'}};
    const p={id:'fictional-fpts',espn_id:'900000001',name:'Fictional FPts',team:'QAA',opp:'QAB',pos:'WR',
      game_id:'900000101',log:[],actual:null,proj:complete(),props:[{key:'fpts',line:14.5,adj:18,proj:18,
        line_h:12.5,adj_h:16,proj_h:16,line_from:'ours',lean:'over',values:[],over:0,n:0}]};
    const g={id:p.game_id,home:'QAA',away:'QAB',state:'post',detail:'Final',kickoff:'2099-10-25T17:00:00Z',home_score:0,away_score:0};
    Object.assign(state,{byId:{[p.id]:p},games:{[g.id]:g},byKey:{'fictional fpts|QAA':p.id},byEspn:{[p.espn_id]:p.id},
      slpOk:true,slp:{[p.id]:complete()},live:{},sc:{mode:'sleeper',half:false},
      leagues:[{id:'fictional-league',name:'Fictional double reception',settings:{...scoring,rec:2}}]});
    state.data.players=[p];state.data.games=[g];
    const saved=()=>({schema_version:'mypicks-player-game-v1',pid:p.id,key:'fpts',dir:'over',line:14.5,
      season:2099,week:2,at:1,gid:g.id,team:p.team,espn_id:p.espn_id,kickoff:g.kickoff,
      period:'full_game_including_overtime',stat_source:'ESPN_EVENT_BOXSCORE'});
    return {box,state,p,g,saved,node};
  }
  let checks=0;
  const check=fn=>{fn();checks++;};
  for (const [mode,expected] of [['ppr',15],['half',13],['league',19],['zero',0]]) {
    const h=setupFantasy();
    h.state.sc={mode:mode==='league'?'league':'sleeper',half:mode==='half',league:'fictional-league'};
    if(mode==='zero')h.state.slp[h.p.id]={...Object.fromEntries(Object.keys(scoring).map(k=>[k,0])),gp:1,rush_att:1,pts_ppr:0};
    const value=h.box.propStatus(h.p,'fpts',14.5,'over');
    check(()=>assert.equal(value.v,expected,mode));
    check(()=>assert.equal(value.final,false,mode));
    check(()=>assert.equal(value.res,'pending',mode));
    check(()=>assert.match(value.reason,/Provisional/));
    const card=h.box.catCard(h.p,h.p.props[0]),chip=h.box.propChip(h.p,h.p.props[0]);
    check(()=>assert.match(card,/<div>Provisional<span/));
    check(()=>assert.match(card,/Saved FPts settlement is unavailable/));
    check(()=>assert.match(chip,/class="cur"/));
    check(()=>assert.match(chip,/>provisional</));
    h.g.state='in';h.g.detail='Live';
    check(()=>{const live=h.box.propStatus(h.p,'fpts',14.5,'over');assert.equal(live.v,expected);assert.equal(live.res,'live');assert.equal(live.final,false);});
    const saved=Object.freeze(h.saved());h.state.mine=Object.freeze([saved]);const before=JSON.stringify(h.state.mine);
    check(()=>{const st=h.box.propStatus(h.p,'fpts',14.5,'over',saved);assert.equal(st.v,null);assert.equal(st.final,false);assert.equal(st.res,'unresolved');assert.match(st.reason,/scoring\/source completeness/);});
    h.g.state='post';h.g.detail='Final';h.box.renderMine();
    check(()=>{assert.equal(JSON.stringify(h.state.mine),before);assert.match(h.node('#main').innerHTML,/scoring\/source completeness/);assert.doesNotMatch(h.node('#main').innerHTML,/data-mine-clear="final"/);});
  }
  for (const phase of ['in','post']) {
    const h=setupFantasy();h.g.state=phase;delete h.state.slp[h.p.id];
    check(()=>{const st=h.box.propStatus(h.p,'fpts',14.5,'over');assert.equal(st.v,null);assert.equal(st.res,'unresolved');assert.equal(st.final,false);assert.match(st.reason,/no current player statistic row/);});
  }
  for (const [pos,expected] of [['WR',0],['DEF',10]]) {
    const h=setupFantasy();h.p.pos=pos;h.state.slp[h.p.id]={gp:1};
    check(()=>{const st=h.box.propStatus(h.p,'fpts',14.5,'over');assert.equal(st.v,expected);assert.equal(st.final,false);assert.equal(st.res,'pending');});
  }
  const h=setupFantasy(),saved=h.saved();
  for(const change of [{gid:'wrong'},{team:'QAB'},{week:3},{kickoff:'2099-10-26T17:00:00Z'},{stat_source:'SLEEPER'}]) {
    check(()=>{const st=h.box.propStatus(h.p,'fpts',14.5,'over',{...saved,...change});assert.equal(st.v,null);assert.equal(st.res,'unresolved');assert.equal(st.final,false);assert.match(st.reason,/binding unavailable/);});
  }
  check(()=>assert.equal(h.box.propValue(complete(),'fpts'),null,'strict stat-value guard still excludes fantasy scoring'));
  h.box.recordPropEvidence(h.g.id,{header:{id:h.g.id,season:{year:2099,type:2},week:{number:2},competitions:[
    {id:h.g.id,date:h.g.kickoff,status:{type:{state:'post',shortDetail:'Final',completed:true}}}]},boxscore:{players:[
    {team:{abbreviation:'QAA'},statistics:[
      {name:'passing',labels:['C/ATT','YDS','TD','INT'],athletes:[{athlete:{id:h.p.espn_id},didNotPlay:false,stats:['0/0','0','0','0']}]},
      {name:'rushing',labels:['CAR','YDS','TD'],athletes:[{athlete:{id:h.p.espn_id},didNotPlay:false,stats:['1','10','0']}]},
      {name:'receiving',labels:['REC','YDS','TD','TGTS'],athletes:[{athlete:{id:h.p.espn_id},didNotPlay:false,stats:['4','40','1','5']}]}]}]}},h.state.data);
  const strict={pass_yd:0,pass_td:0,pass_cmp:0,pass_att:0,pass_int:0,rush_yd:10,rush_att:1,rec:4,rec_yd:40,rush_rec_yd:50,anytime_td:1};
  for(const [key,value]of Object.entries(strict))check(()=>{const st=h.box.propStatus(h.p,key,value,'over',{...saved,key,line:value});assert.equal(st.v,value,key);assert.equal(st.res,'push',key);assert.equal(st.final,true,key);});
  check(()=>{const st=h.box.propStatus(h.p,'fpts',14.5,'over',saved);assert.equal(st.res,'unresolved');assert.equal(st.final,false);});
  console.log(JSON.stringify({suite:'fpts-provisional-display-preservation',cases:checks,failures:0,
    strict_categories:Object.keys(strict).length,saved_fpts_settlement:'UNAVAILABLE',
    legacy_gp_only_zero_and_missing_defense_allowance_debt:'PRESERVED_UNCERTIFIED',network:'forbidden',browser:'Node VM only'}));
}
