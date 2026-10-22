const assert = require('node:assert/strict');

// Actual private paper helpers: no provider, storage or ticket-network mock is
// mistaken for a production offer or an independently timestamped selection.
{
  let checks=0;const check=new Proxy(assert,{get:(target,key)=>typeof target[key]==='function'?(...args)=>{checks++;return target[key](...args);}:target[key]});
  const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
  const source=fs.readFileSync(path.join(__dirname,'../output/app.js'),'utf8');
  const names=['paperLegIdentity','validatePaperLeg','validatePaperTicket','savePaperTicket','readPaperTickets','paperLegStatus','paperTicketStatus','paperCandidates'];
  const functions=names.map(name=>{const value=source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`));check.ok(value,name);return value[0];}).join('\n');
  const prefix='nflprops.paper-ticket.v1.',data=new Map([['nflprops.mine','PRESERVED_OWNER_BYTES']]);
  const storage={get length(){return data.size;},key:i=>[...data.keys()][i],getItem:key=>data.has(key)?data.get(key):null,setItem:(key,value)=>data.set(key,value)};
  const category=['pass_yd','pass_td','pass_cmp','pass_att','pass_int','rush_yd','rush_att','rec_yd','rec','rush_rec_yd'];
  const state={paper:{source:'dk',sides:'mixed',categories:[],game:''},data:{season:2026,week:7,generated_at:'2026-10-24T10:00:00Z',games:[],players:[]},games:{}};
  const context={PAPER_PREFIX:prefix,PAPER_CATEGORIES:category,HASH64:/^[a-f0-9]{64}$/,S:state,UNAVAILABLE:new Set(['Out']),injOf:p=>({status:p.injury}),localStorage:storage};
  vm.createContext(context);vm.runInContext(functions+'\nthis.api={'+names.join(',')+'};',context);const a=context.api;
  const leg=i=>({season:2026,week:7,game_id:'fictional-game-'+i,player_id:'fictional-player-'+i,category:'rec',team:'AAA',name:'Fictional '+i,period:'full_game',kickoff:'2026-10-25T17:00:00Z',line:5.5,side:'over',line_source:'dk',raw_projection:5,adjusted_projection:7,board_generated_at:'2026-10-24T10:00:00Z',quote_observed_at:null});
  const ticket={schema_version:'paper-parlay-ticket-v1',ticket_id:'fictional-ticket-0001',revision_id:'fictional-revision-0001',parent_revision_id:null,saved_at:'2026-10-24T11:00:00Z',clock_basis:'OWNER_DEVICE_TIME_NOT_INDEPENDENTLY_TIMESTAMPED',product:'paper_all_legs',line_source:'dk',legs:[leg(1),leg(2)]};
  const key=a.savePaperTicket(ticket,storage),original=data.get(key);check.equal(a.readPaperTickets(storage).tickets.length,1);check.equal(data.get('nflprops.mine'),'PRESERVED_OWNER_BYTES');
  for(const change of [t=>t.legs.pop(),t=>t.legs.push(...Array.from({length:5},(_,i)=>leg(i+3))),t=>t.legs[1].line_source='sleeper',t=>t.legs[1].game_id=t.legs[0].game_id,t=>t.saved_at=123,t=>t.legs[0].kickoff=123,t=>t.legs[0].category='anytime_td',t=>t.saved_at='2026-10-25T17:00:00Z']){const t=structuredClone(ticket);change(t);check.throws(()=>a.validatePaperTicket(t));}
  const revision={...structuredClone(ticket),revision_id:'fictional-revision-0002',parent_revision_id:ticket.revision_id,saved_at:'2026-10-24T11:01:00Z'};a.savePaperTicket(revision,storage);check.equal(data.get(key),original);check.equal(a.readPaperTickets(storage).tickets.length,2);
  check.throws(()=>a.savePaperTicket({...revision,parent_revision_id:'fictional-missing-0001'},storage));
  check.throws(()=>a.savePaperTicket({...ticket,revision_id:'fictional-revision-0003'},storage));
  check.throws(()=>a.savePaperTicket({...ticket,legs:[{...leg(1),line:6.5},leg(2)]},storage));
  check.throws(()=>a.savePaperTicket(ticket,{...storage,setItem:()=>{throw new Error('QUOTA');},getItem:()=>null}));
  data.set(prefix+'bad','{');check.equal(a.readPaperTickets(storage).tickets.length,2);check.equal(a.readPaperTickets(storage).errors.length,1);
  data.delete(key);check.equal(a.readPaperTickets(storage).tickets.length,0);check.throws(()=>a.savePaperTicket({...revision,revision_id:'fictional-revision-0004',parent_revision_id:revision.revision_id},storage));data.set(key,original);
  const l=leg(1),outcome={...l,status:'resolved',actual:0,final_confirmed:true,outcome_conflict:false,game_state:'post',outcome_selection:'confirmed',collected_at:'2026-10-25T21:00:00Z',outcome_snapshot_sha256:'a'.repeat(64),selected_outcome_row_sha256:'b'.repeat(64),selected_outcome_provenance_sha256:'c'.repeat(64)};
  const outcomes=new Map([[a.paperLegIdentity(l),outcome]]);
  check.equal(a.paperLegStatus(l,outcomes).status,'loss');check.equal(a.paperLegStatus({...l,side:'under'},outcomes).status,'win');
  outcome.actual=5;check.equal(a.paperLegStatus({...l,line:5},outcomes).status,'push');outcome.actual=8;check.equal(a.paperLegStatus(l,outcomes).status,'win');
  outcome.week=8;check.equal(a.paperLegStatus(l,outcomes).status,'unresolved');outcome.week=7;outcome.outcome_conflict=true;check.equal(a.paperLegStatus(l,outcomes).status,'unresolved');outcome.outcome_conflict=false;outcome.status='dnp';outcome.actual=null;check.equal(a.paperLegStatus(l,outcomes).status,'dnp');
  check.match(a.paperTicketStatus([{status:'loss'},{status:'push'}]),/loss_present.*push/);check.equal(a.paperTicketStatus([{status:'win'},{status:'win'}]),'all_legs_won');
  state.data.players=[{id:l.player_id,name:l.name,game_id:l.game_id,team:l.team,injury:null,props:[{key:'rec',proj:5,adj:7,line:5.5,line_from:'dk',lean:'over'}]}];state.data.games=[{id:l.game_id,home:'AAA',away:'BBB',kickoff:l.kickoff,state:'pre'}];state.games[l.game_id]={...state.data.games[0]};
  check.equal(a.paperCandidates(Date.parse(ticket.saved_at)).length,1);state.games[l.game_id].kickoff='2026-10-26T17:00:00Z';check.equal(a.paperCandidates(Date.parse(ticket.saved_at)).length,0);state.games[l.game_id].kickoff=l.kickoff;state.data.players[0].injury='Out';check.equal(a.paperCandidates(Date.parse(ticket.saved_at)).length,0);
  state.data.players[0].injury=null;const prop=state.data.players[0].props[0];prop.line_from='sleeper';state.paper.source='sleeper';
  check.equal(a.paperCandidates(Date.parse(ticket.saved_at)).length,0,'unsupported missing Sleeper side is excluded');
  prop.sleeper={line:5.5,over:1.8,under:null};check.equal(a.paperCandidates(Date.parse(ticket.saved_at)).length,1,'saved matching available side remains eligible');
  prop.lean='under';check.equal(a.paperCandidates(Date.parse(ticket.saved_at)).length,0,'missing under side is not invented');
  prop.sleeper.under=1.7;check.equal(a.paperCandidates(Date.parse(ticket.saved_at)).length,1);
  prop.sleeper.line=6.5;check.equal(a.paperCandidates(Date.parse(ticket.saved_at)).length,0,'different offered threshold is not substituted');
  console.log(`Private paper contracts: ${checks} storage, identity, clock, correction and eligibility checks passed.`);
}

// Presence correction: actual helpers preserve known zero, signed PPR and
// unknown components. No forecast, saved-line or device-state mutation.
{
  const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
  const source = fs.readFileSync(path.join(__dirname, '../output/app.js'), 'utf8');
  const names = ['offensiveComponentsKnown', 'tdChanceText', 'ppr'];
  const functions = names.map(name => {
    const match = source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`));
    assert.ok(match, name + ' actual source'); return match[0];
  }).join('\n');
  const state = { data: { scoring: { rec: 1, rec_yd: .1, rush_yd: .1, fum_lost: -2, fum_rec_td: 6 } } };
  const context = { S: state }; vm.createContext(context);
  vm.runInContext(functions + '\nthis.api={tdChanceText,ppr,offensiveComponentsKnown};', context);
  const api = context.api;
  assert.equal(api.tdChanceText({ td_chance: null }), 'Unavailable');
  assert.equal(api.tdChanceText({}), 'Unavailable');
  assert.equal(api.tdChanceText({ td_chance: 0 }), '0%');
  assert.equal(api.tdChanceText({ td_chance: .543 }), '54%');
  assert.equal(api.ppr({ rec: null, rec_yd: 20, pts_ppr: 2 }), null);
  assert.equal(api.ppr({ rec: 0 }), 0);
  assert.equal(api.ppr({ rush_yd: -2, fum_lost: 1 }), -2.2);
  assert.equal(api.ppr({ rec: false }), null);
  assert.equal(api.ppr({ rec: 2, _presence: { version: 'nfl-data-presence-v2', kind: 'projection' } }), null);
  assert.equal(api.ppr({ _presence: null }), null);
  assert.equal((source.match(/tdChanceText\(/g) || []).length, 4, 'one helper and three render sites');
  assert.equal(api.offensiveComponentsKnown({rec:.5,_presence:{kind:'actual'}},['rec']),false);
  assert.equal(api.offensiveComponentsKnown({rush_yd:-2,_presence:{kind:'actual'}},['rush_yd']),true);
  console.log('13 presence/TD/PPR helper assertions passed.');
}

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
  networkStatus = 200; headers = {};
  const modern = { ...pointer, schema_version: 'selection-publication-pointer-v4' };
  const shared = { schema_version: 'selection-final-outcome-period-v2', season: 2026, week: 6, outcomes: [] };
  function install(body, filename = 'outcomes.json') {
    const decoded = Buffer.from(JSON.stringify(body)); delivered = zlib.gzipSync(decoded, { mtime: 0 });
    return { ...descriptor, path: hash(delivered) + '/' + filename, encoded_sha256: hash(delivered), encoded_bytes: delivered.length,
      sha256: hash(decoded), decoded_bytes: decoded.length };
  }
  const sharedDesc = install(shared);
  assert.equal((await ui.checkedGradingAsset(modern, sharedDesc, 'outcomes', true)).report_id, modern.report_id);
  assert.equal((await ui.checkedGradingAsset({ ...modern, report_id: 'd'.repeat(64) }, sharedDesc, 'outcomes', true)).report_id, 'd'.repeat(64), 'one body can belong to separate exact graphs');
  for (const invalid of [{ ...shared, report_id: modern.report_id }, { ...shared, schema_version: 'selection-final-outcome-period-v1' }, { ...shared, week: 5 }, { ...shared, private_extension: 'not-public' }]) {
    const invalidDesc = install(invalid);
    await assert.rejects(ui.checkedGradingAsset(modern, invalidDesc, 'outcomes', true), /type|context/);
  }
  const rowBody = { schema_version: 'selection-public-rows-v2', rows: [] }, rowDesc = install(rowBody, 'rows.json');
  delete rowDesc.season; delete rowDesc.week;
  assert.equal((await ui.checkedGradingAsset(modern, rowDesc, 'rows')).schema_version, 'selection-public-rows-v1');
  await assert.rejects(ui.checkedGradingAsset(pointer, rowDesc, 'rows'), /path|binding/);
  console.log('Shared payload typed readers: 8 version/envelope/context/reuse checks passed.');

})().catch(error => { console.error(error); process.exitCode = 1; });

// Typed prospective rows cannot acquire membership through a legacy reader.
{
  const fs=require('node:fs'),vm=require('node:vm');
  const source=fs.readFileSync(require('node:path').join(__dirname,'../output/app.js'),'utf8');
  const context={HASH64:/^[a-f0-9]{64}$/};vm.createContext(context);
  vm.runInContext(source.match(/function validateGradingRowContract\([^]*?\n\}/)[0]+';this.validate=validateGradingRowContract;',context);
  const row={schema_version:'selection-decision-v2',strategy_version:'ranked-selection-policy-v1',strategy_policy_sha256:'80d9ab617f8c6b331dc879ff3e83a8304a934944a01d40514567e6933d251250',strategy_receipt_sha256:'a'.repeat(64),strategy_rank:1,cohort:'ranked_biggest_lean_v1',model_version:'original_sleeper_matchup_baseline',engine_sha256:'e8e8823f460e074485ee91a0dc1c1cfc43877146c4498ef074d15d2b5a735d07',provenance_class:'completed_prospective_ranked_selection',action:'SELECT',side:'over',line_from:'dk',selection_clock_basis:'LOCAL_COMPLETED_RANKED_SELECTION',forecast_generated_at:'2026-11-01T10:00:00Z',collected_at:'2026-11-01T10:01:00Z',original_selection_created_at:'2026-11-01T10:02:00Z',recorded_selection_at:'2026-11-01T10:02:00Z',kickoff:'2026-11-01T17:00:00Z'};
  assert.doesNotThrow(()=>context.validate(row,'selection-public-report-v6'));
  for(const change of [{schema_version:'unknown'},{schema_version:'selection-decision-v1'},{strategy_rank:0},{strategy_policy_sha256:'b'.repeat(64)},{engine_sha256:'c'.repeat(64)},{cohort:'unsupported'},{collected_at:'2026-11-01T10:03:00Z'},{original_selection_created_at:row.kickoff,recorded_selection_at:row.kickoff},{line_from:'ours'},{strategy_receipt_sha256:null}]) assert.throws(()=>context.validate({...row,...change},'selection-public-report-v6'));
  assert.throws(()=>context.validate(row,'selection-public-report-v5'));
  console.log('Prospective row reader: 12 schema, source, registration, membership and clock controls passed.');
}
