const assert = require('node:assert/strict');
require('./test_weekly_public_feed_caption.cjs');
require('./test-weekly-overlay.cjs');
require('./test-selected-rankings.cjs');

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

// Saved-leg and draft persistence run the actual bounded readers/writers across
// fresh VM instances. Storage and async outcome transport are controlled doubles;
// these tests establish no provider quote freshness or pregame authentication.
(async()=>{
  let checks=0;const check=new Proxy(assert,{get:(target,key)=>typeof target[key]==='function'?(...args)=>{checks++;return target[key](...args);}:target[key]});
  const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
  const source=fs.readFileSync(path.join(__dirname,'../output/app.js'),'utf8');
  const names=['paperLegIdentity','validatePaperLeg','validatePaperTicket','savePaperTicket','readPaperTickets','paperStorageBytes','validateSavedPaperLeg','readPaperLegs','savePaperLeg','validatePaperDraft','paperDraftParent','readPaperDraft','savePaperDraft','persistPaperDraft','restorePaperDraft','paperCurrentLeg','addSavedPaperLeg','paperLegStatus','paperTicketStatus','paperCandidates','gradeOpenedPaperLeg','paperPerformanceHtml','renderParlay'];
  const functions=names.map(name=>{const value=source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));check.ok(value,name);return value[0];}).join('\n');
  const constants=['PAPER_PREFIX','PAPER_LEG_PREFIX','PAPER_DRAFT_KEY','PAPER_STORAGE_LIMITS','PAPER_CATEGORIES','gradingCanonical','esc'].map(name=>{const value=source.match(new RegExp(`^const ${name} = .+;$`,'m'));check.ok(value,name);return value[0];}).join('\n');
  const at=Date.parse('2026-10-24T11:00:00Z'),prefix='nflprops.paper-leg.v1.',draftKey='nflprops.paper-draft.v1';
  class FixtureDate extends Date { static now(){return at;} }
  const leg=i=>({season:2026,week:7,game_id:'fictional-saved-game-'+i,player_id:'fictional-saved-player-'+i,category:'rec',team:'AAA',name:'Fictional '+i,period:'full_game',kickoff:'2026-10-25T17:00:00Z',line:5.5,side:'over',line_source:'dk',raw_projection:5,adjusted_projection:7,board_generated_at:'2026-10-24T10:00:00Z',quote_observed_at:null});
  const record=i=>({schema_version:'paper-parlay-leg-v1',saved_id:'fictional-saved-leg-'+String(i).padStart(3,'0'),saved_at:'2026-10-24T11:00:00Z',clock_basis:'OWNER_DEVICE_TIME_NOT_INDEPENDENTLY_TIMESTAMPED',leg:leg(i)});
  const data=new Map([['nflprops.mine','PRESERVED_MY_PICKS_BYTES']]);
  const storageFor=values=>({get length(){return values.size;},key:i=>[...values.keys()][i],getItem:key=>values.has(key)?values.get(key):null,setItem:(key,value)=>values.set(key,value)});
  const storage=storageFor(data);
  function fresh(store=storage){
    const state={tab:'props',paper:{legs:[],source:'dk',sides:'mixed',categories:[],game:'',size:2,opened:null,results:null,history:null,historyEpoch:0,epoch:0,error:'',draftLoaded:false,openedLeg:null,legResult:null,legEpoch:0},data:{season:2026,week:7,generated_at:'2026-10-24T10:00:00Z',games:[],players:[]},games:{},finalOutcomes:new Map(),grading:null};
    const main={innerHTML:''};
    const context={S:state,localStorage:store,TextEncoder,structuredClone,Date:FixtureDate,HASH64:/^[a-f0-9]{64}$/,UNAVAILABLE:new Set(['Out']),injOf:p=>({status:p.injury}),gradeOpenedPaper:()=>{},$:()=>main,SHORT:{rec:'Rec'},LINE_FROM:{dk:'DraftKings',sleeper:'Sleeper'},fmt:(n,d=1)=>Number(n).toFixed(d)};
    vm.createContext(context);vm.runInContext(constants+'\n'+functions+'\nthis.api={'+names.join(',')+'};',context);
    const l=leg(1),game={id:l.game_id,home:'AAA',away:'BBB',kickoff:l.kickoff,state:'pre'};
    state.data.games=[game];state.games[l.game_id]={...game};state.data.players=[{id:l.player_id,name:l.name,team:l.team,game_id:l.game_id,injury:null,props:[{key:l.category,proj:l.raw_projection,adj:l.adjusted_projection,line:l.line,line_from:l.line_source,lean:l.side}]}];
    return {a:context.api,state,context,main};
  }
  let {a,state,context,main}=fresh();
  const first=record(1),key=a.savePaperLeg(first),original=data.get(key);
  check.equal(a.readPaperLegs().legs.length,1);check.equal(a.readPaperLegs().storedCount,1);check.equal(a.readPaperLegs().storedBytes,Buffer.byteLength(original));
  check.equal(a.savePaperLeg(first),key);check.equal(data.get(key),original,'unchanged retry preserves first stored bytes');
  for(const change of [r=>r.saved_at=123,r=>r.saved_at=r.leg.kickoff,r=>r.saved_at='2026-10-24T09:00:00Z',r=>r.leg.quote_observed_at=r.saved_at,r=>r.leg.extra='PRIVATE',r=>r.leg.week=0,r=>r.saved_id='bad']){const r=structuredClone(first);change(r);check.throws(()=>a.savePaperLeg(r));}
  check.throws(()=>a.savePaperLeg({...structuredClone(first),leg:{...leg(1),line:6.5}}),/immutable/);
  const detached=a.readPaperLegs().legs[0].record;detached.leg.line=99;check.equal(data.get(key),original,'returned objects cannot mutate stored contracts');
  a.addSavedPaperLeg(key,storage,at);check.equal(state.paper.legs[0].line,5.5);check.throws(()=>a.addSavedPaperLeg(key,storage,at),/incompatible/);
  a.savePaperDraft(state.paper,storage,at);const draftBytes=data.get(draftKey);
  check.equal(JSON.parse(draftBytes).legs[0].board_generated_at,first.leg.board_generated_at);
  ({a,state,context,main}=fresh());a.restorePaperDraft();
  check.equal(state.paper.legs.length,1);check.equal(state.paper.legs[0].board_generated_at,first.leg.board_generated_at);check.equal(state.paper.opened,null);check.equal(data.get(draftKey),draftBytes);
  check.match(state.paper.error,/not a saved ticket or verified pregame evidence/);
  check.equal(a.readPaperTickets().tickets.length,0,'draft restoration does not manufacture a saved selection');
  check.equal(data.get('nflprops.mine'),'PRESERVED_MY_PICKS_BYTES');
  for(const [field,value]of[['season',2027],['week',8],['game_id','other-game'],['player_id','other-player'],['category','rec_yd'],['team','BBB'],['kickoff','2026-10-26T17:00:00Z'],['line',6.5],['side','under'],['line_source','sleeper'],['raw_projection',6],['adjusted_projection',8],['board_generated_at','2026-10-24T10:01:00Z']])check.equal(a.paperCurrentLeg({...leg(1),[field]:value},at),null,field+' change cannot borrow saved contract');
  check.equal(a.paperCurrentLeg(leg(1),Date.parse(leg(1).kickoff)),null,'kickoff does not refresh an old leg');
  state.paper.legs=[];state.data.generated_at='2026-10-24T10:01:00Z';check.throws(()=>a.addSavedPaperLeg(key,storage,at));check.equal(data.get(key),original);
  state.data.generated_at=leg(1).board_generated_at;
  const parent={schema_version:'paper-parlay-ticket-v1',ticket_id:'fictional-ticket-saved-legs',revision_id:'fictional-revision-saved-legs',parent_revision_id:null,saved_at:'2026-10-24T11:00:00Z',clock_basis:'OWNER_DEVICE_TIME_NOT_INDEPENDENTLY_TIMESTAMPED',product:'paper_all_legs',line_source:'dk',legs:[leg(1),leg(2)]};
  const parentKey=a.savePaperTicket(parent),parentBytes=data.get(parentKey);state.paper.opened=parent;state.paper.legs=structuredClone(parent.legs);
  a.savePaperDraft(state.paper,storage,at);const parentDraft=data.get(draftKey);
  ({a,state,context,main}=fresh());a.restorePaperDraft();check.equal(state.paper.opened.revision_id,parent.revision_id);check.equal(data.get(parentKey),parentBytes);
  data.delete(parentKey);check.throws(()=>a.readPaperDraft(),/lineage/);check.equal(data.get(draftKey),parentDraft);data.set(parentKey,parentBytes);
  for(const legs of [[leg(1),leg(1)],[leg(1),{...leg(2),game_id:leg(1).game_id}],[leg(1),{...leg(2),line_source:'sleeper'}],Array.from({length:7},(_,i)=>leg(i+1))])check.throws(()=>a.savePaperDraft({...state.paper,legs},storage,at));
  data.set(prefix+'broken','{');check.equal(a.readPaperLegs().legs.length,1);check.equal(a.readPaperLegs().errors.length,1);check.equal(data.get(prefix+'broken'),'{');data.delete(prefix+'broken');
  data.set(prefix+'wrong-id',original);check.equal(a.readPaperLegs().errors.length,1);data.delete(prefix+'wrong-id');
  data.set(prefix+'oversized',original+' '.repeat(9000));check.equal(a.readPaperLegs().errors.length,1);check.ok(data.get(prefix+'oversized').length>8192);data.delete(prefix+'oversized');
  for(const raw of ['{',JSON.stringify({...JSON.parse(parentDraft),schema_version:'unknown-draft'}),parentDraft+' '.repeat(65536)]){data.set(draftKey,raw);check.throws(()=>a.readPaperDraft());check.equal(data.get(draftKey),raw);}data.set(draftKey,parentDraft);
  const quota={...storage,setItem:()=>{throw Error('QUOTA');}};check.throws(()=>a.savePaperLeg(record(2),quota),/QUOTA/);check.throws(()=>a.savePaperDraft(state.paper,quota,at),/QUOTA/);check.equal(data.get(key),original);check.equal(data.get(parentKey),parentBytes);
  const failed=new Map(data),partial={...storageFor(failed),setItem:(k,v)=>failed.set(k,v.slice(0,-1))};
  check.throws(()=>a.savePaperLeg(record(2),partial),/verified/);check.equal(failed.get(key),original);check.equal(failed.get(parentKey),parentBytes);check.equal(failed.get('nflprops.mine'),'PRESERVED_MY_PICKS_BYTES');
  check.throws(()=>a.savePaperDraft(state.paper,partial,at),/verified/);
  const full=new Map();for(let i=0;i<64;i++)full.set(prefix+record(i).saved_id,JSON.stringify(record(i)));check.equal(a.readPaperLegs(storageFor(full)).legs.length,64);check.throws(()=>a.savePaperLeg(record(64),storageFor(full)),/capacity/);full.set(prefix+record(64).saved_id,JSON.stringify(record(64)));check.throws(()=>a.readPaperLegs(storageFor(full)),/64 records/);
  const large=new Map();for(let i=0;i<33;i++){const raw=JSON.stringify(record(i));large.set(prefix+record(i).saved_id,raw+' '.repeat(8100-Buffer.byteLength(raw)));}check.throws(()=>a.readPaperLegs(storageFor(large)),/256 KiB/);
  a.renderParlay();check.match(main.innerHTML,/<h3>Saved legs<\/h3>/);check.match(main.innerHTML,/board 2026-10-24T10:00:00Z/);check.match(main.innerHTML,/data-paper-leg-result/);check.equal(data.get(key),original);check.equal(data.get(parentKey),parentBytes);
  const outcome={...leg(1),status:'resolved',actual:3,final_confirmed:true,game_state:'post',outcome_selection:'confirmed',outcome_conflict:false,collected_at:'2026-10-25T21:00:00Z',outcome_snapshot_sha256:'a'.repeat(64),selected_outcome_row_sha256:'b'.repeat(64),selected_outcome_provenance_sha256:'c'.repeat(64)};
  const outcomes=new Map([[a.paperLegIdentity(leg(1)),outcome]]),requests=[];
  state.data.week=8;state.paper.openedLeg=JSON.parse(original);state.grading={outcomeIndex:{},pointer:{report_id:'first'}};
  context.loadOutcomePeriod=async(g,season,week)=>{requests.push([season,week]);return outcomes;};
  await a.gradeOpenedPaperLeg();check.equal(JSON.stringify(requests),JSON.stringify([[2026,7]]));check.equal(state.paper.legResult.status,'loss');
  outcome.actual=8;await a.gradeOpenedPaperLeg();check.equal(state.paper.legResult.status,'win');check.equal(data.get(key),original,'outcome corrections leave saved references unchanged');
  outcome.week=8;await a.gradeOpenedPaperLeg();check.equal(state.paper.legResult.status,'unresolved');outcome.week=7;
  let complete;context.loadOutcomePeriod=()=>new Promise(done=>{complete=done;});const changedDependency=a.gradeOpenedPaperLeg();data.set(key,'{');complete(outcomes);await changedDependency;check.equal(state.paper.legResult,null,'changed stored dependency cannot inherit an in-flight result');check.equal(data.get(key),'{');data.set(key,original);
  let resolve;context.loadOutcomePeriod=()=>new Promise(done=>{resolve=done;});const old=a.gradeOpenedPaperLeg();state.grading={outcomeIndex:{},pointer:{report_id:'new'}};resolve(outcomes);await old;check.equal(state.paper.legResult,null,'old publication response cannot grade a new selection');
  const oldSelection=a.gradeOpenedPaperLeg();state.paper.openedLeg=record(2);resolve(outcomes);await oldSelection;check.equal(state.paper.legResult,null,'old selected-leg response cannot overwrite a later selection');
  context.loadOutcomePeriod=async()=>{throw Error('missing partition');};await a.gradeOpenedPaperLeg();check.equal(state.paper.legResult,null);check.match(state.paper.error,/unavailable; no result was substituted/);
  check.equal(data.get('nflprops.mine'),'PRESERVED_MY_PICKS_BYTES');check.equal(data.get(parentKey),parentBytes);
  console.log(`Saved paper legs/draft: ${checks} reload, storage-boundary, exact-contract, correction and stale-response checks passed.`);
})().catch(error=>{console.error(error);process.exitCode=1;});

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
const state = { data: { season: 2026, week: 6 }, games: { 'fictional-game': { id: 'fictional-game', kickoff, state: 'post', home: 'AAA', away: 'BBB', home_score: 10, away_score: 7 } }, finalOutcomes: new Map(), slp: {}, live: {} };
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
  for (const [model,engine] of [['sleeper-matchup-data-integrity-v2','3909c7ac5470970182065576f057e8036f31ad30da13f1ef9999eb1108a183b4'],['sleeper-matchup-classic-data-integrity-v2','16d0ea1eb1ed7378427f3279bb4e1b7907d2370928b3ad30a2ca7dbe0bf6265b']]) {
    assert.doesNotThrow(()=>context.validate({...row,model_version:model,engine_sha256:engine},'selection-public-report-v6'));
    assert.throws(()=>context.validate({...row,model_version:model+'-unknown',engine_sha256:engine},'selection-public-report-v6'));
    assert.throws(()=>context.validate({...row,model_version:model,engine_sha256:'0'.repeat(64)},'selection-public-report-v6'));
  }
  assert.throws(()=>context.validate({...row,model_version:'sleeper-matchup-classic-fg-identity-v1',engine_sha256:'9f605590fdd4a23bee01c977e606d964e280c8b567ee4de6e1b5bc9eadd46538'},'selection-public-report-v6'),'legacy Classic native records are not qualified ranked-strategy evidence');
  console.log('Prospective row reader: 19 schema, source, registration, membership and clock controls passed.');
}

// Game-market finality is independent of the Phase 2 outcome publication.
// These are actual application functions with fictional scoreboards/selections.
// DOM/localStorage and kickoff formatting are presentation-only test doubles;
// no modern outcome row, native proof or validator success is manufactured.
{
  const extract = name => {
    const value = source.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^\\}`, 'm'))?.[0];
    assert.ok(value, 'actual ' + name + ' implementation found');
    return value;
  };
  const constant = name => {
    const key = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const value = source.match(new RegExp('^const ' + key + ' = (?:.+;|\\{[^]*?^\\};)$', 'm'))?.[0];
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
  vm.runInContext(['$', 'esc', 'fmt', 'logo', 'ml', 'SHORT', 'mineOutcomeLoads'].map(constant).join('\n') + '\n'
    + ['gameStatus', 'gameBetLabel', 'gameBetStatus', 'resBadge', 'savedPropContract', 'mineHistorical', 'mineOutcomeState', 'loadHistoricalMineOutcomes', 'historicalPropStatus', 'minePlayerStatus', 'renderMine', 'store'].map(extract).join('\n'), context);
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
    assert.match(main.innerHTML, /Only confirmed final statistical outcomes/);
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

// Actual producer projection and actual strict browser reader agree on the
// four distinct saved-model families. All observations below are fictional;
// no historical receipt is relabeled or promoted into a different experiment.
{
  const python = `import sys,json,runpy
sys.path.insert(0,'tools')
import data_integrity_v2 as corrected
import classic_model_v1 as legacy_classic
from accuracy_publication import project_accuracy
t=runpy.run_path('tests/test_accuracy_publication.py')
reports=[]
for index,model in enumerate(['original_sleeper_matchup_baseline',corrected.MODEL,legacy_classic.MODEL,corrected.CLASSIC_MODEL]):
 row=t['observation']('fictional-ui-accuracy-'+str(index),model=model)
 report=t['evaluation']([row],model=model)
 reports.append(report)
print(json.dumps(project_accuracy(reports)))`;
  const value = JSON.parse(require('node:child_process').execFileSync(process.env.PYTHON || 'python3', ['-B', '-c', python], {cwd:path.resolve(__dirname,'..'),timeout:10000}));
  const context = {HASH64:/^[a-f0-9]{64}$/}; vm.createContext(context);
  const categories = source.match(/^const PAPER_CATEGORIES = .+;$/m)?.[0]; assert.ok(categories);
  const reader = source.match(/function validateForecastAccuracy\([^]*?\n\}/)?.[0]; assert.ok(reader);
  vm.runInContext(categories+'\n'+reader+'\nthis.validate=validateForecastAccuracy;',context);
  assert.equal(context.validate(value),value);
  assert.equal(value.capture_coverage.length,4);
  const model='sleeper-matchup-classic-data-integrity-v2';
  const cohort=value.cohorts.find(item=>item.model_version===model); assert.ok(cohort);
  assert.equal(cohort.engine_sha256,'16d0ea1eb1ed7378427f3279bb4e1b7907d2370928b3ad30a2ca7dbe0bf6265b');
  assert.equal(cohort.statistic_contract_sha256,'9a08bd9a3f7d2affbe8bee1ba4638fa53a9148d2f04f951f5bfa5fa296081f4e');
  for (const change of [item=>item.engine_sha256='0'.repeat(64),item=>item.statistic_contract_sha256='0'.repeat(64),item=>item.model_version=model+'-unknown',item=>item.statistic_contract_sha256='53f6016d59fe93f9ce09bc23c472f7e77471e7a80a8b1f75e78b2ab3ed4a258d',item=>item.statistic_contract_sha256='f35596bd8cae04f1ff1a6ee85b8e3e7963e05450c8c040a2bbb6e484db6b068f']) {
    const broken=structuredClone(value);change(broken.cohorts.find(item=>item.model_version===model));
    assert.throws(()=>context.validate(broken));
  }
  const legacy=value.cohorts.find(item=>item.model_version==='sleeper-matchup-classic-fg-identity-v1'); assert.ok(legacy);
  assert.equal(legacy.engine_sha256,'9f605590fdd4a23bee01c977e606d964e280c8b567ee4de6e1b5bc9eadd46538');
  assert.equal(legacy.statistic_contract_sha256,'f35596bd8cae04f1ff1a6ee85b8e3e7963e05450c8c040a2bbb6e484db6b068f');
  for (const category of ['fpts','anytime_td']) {
    assert.equal(legacy.categories[category].coverage.opportunities,0);
    assert.equal(legacy.categories[category].paired.raw.n,0);
    assert.equal(legacy.categories[category].paired.raw.mae,null);
  }
  for (const hash of ['53f6016d59fe93f9ce09bc23c472f7e77471e7a80a8b1f75e78b2ab3ed4a258d','fd024229abd98a661f0ffa53866bf55bf13142e891b2e64ecee94012dcbe1948','9a08bd9a3f7d2affbe8bee1ba4638fa53a9148d2f04f951f5bfa5fa296081f4e']) {
    const broken=structuredClone(value);broken.cohorts.find(item=>item.model_version===legacy.model_version).statistic_contract_sha256=hash;
    assert.throws(()=>context.validate(broken),'legacy native evidence cannot borrow a presence-aware statistic contract');
  }
  assert.doesNotMatch(JSON.stringify(value),/PRIVATE_CANARY|unapproved\/private/);
  console.log('Four-model accuracy: producer/reader, exact legacy/presence identities, absent PPR/TD and crossed-contract rejection passed.');
}

// Actual About interpolation and current-only lineage text. Only the output
// element and formatting are presentation doubles; no evidence/storage mock
// establishes qualification or a new original-model observation.
{
  const names=['renderAbout','effectivePropForecast'];
  const functions=names.map(name=>{const match=source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`));assert.ok(match);return match[0];}).join('\n');
  const main={innerHTML:''},bytes=new Map([['nflprops.mine','UNCHANGED_SAVED_LINE_BYTES'],['nflprops.paper-ticket.v1.fixture','UNCHANGED_TICKET_BYTES']]);
  const S={data:{scoring:{},categories:{},execution_model:{}},forecastScorecard:null};
  const context={S,$:()=>main,esc:value=>String(value),fmt:value=>String(value),selectedPropForecast:()=>null,
    localStorage:{getItem:key=>bytes.get(key),setItem:()=>{throw Error('About/fallback must not write device state');}}};
  vm.createContext(context);vm.runInContext(functions,context);
  const modern='sleeper-matchup-classic-data-integrity-v2',legacy='sleeper-matchup-classic-fg-identity-v1';
  for(const model of [modern,legacy]){
    S.data.execution_model.model=model;context.renderAbout();
    assert.ok(main.innerHTML.includes('Current baseline model: '+model+'.'));
    assert.doesNotMatch(main.innerHTML,/\$\{esc\(S\.data\.execution_model/,'template source must not leak into displayed copy');
    if(model===modern){
      assert.match(main.innerHTML,/current-only update produces no new original-model observation and does not activate the registered experiment/);
      assert.doesNotMatch(main.innerHTML,/The original R0 shadow is captured separately under original code/);
    }else assert.match(main.innerHTML,/The original R0 shadow is captured separately under original code/);
  }
  for(const [model,expected] of [[undefined,'R0_FALLBACK'],[null,'R0_FALLBACK'],['original_sleeper_matchup_baseline','R0_FALLBACK'],[legacy,'CURRENT_BASELINE'],[modern,'CURRENT_BASELINE']])
    assert.equal(context.effectivePropForecast({reference_model:model},{key:'rec',adj:2}).source,expected);
  for(const model of ['sleeper-matchup-data-integrity-v2',modern+'-unknown','unsupported'])
    assert.equal(context.effectivePropForecast({reference_model:model},{key:'rec',adj:2}),null,'unsupported weekly fallback cannot become R0');
  assert.equal(bytes.get('nflprops.mine'),'UNCHANGED_SAVED_LINE_BYTES');assert.equal(bytes.get('nflprops.paper-ticket.v1.fixture'),'UNCHANGED_TICKET_BYTES');
  console.log('About/current-reference: actual interpolation, route lineage and closed model fallback checks passed.');
}

// Actual ranking semantic reader, with a wholly fictional document. Descriptor
// hashes are test inputs; transport/hash-graph validation is not claimed here.
(async()=>{
  const names=['selectedRankingPolicy','rankingCanonical','compareSelectedRankingItems','validateSelectedRankings'];
  const functions=names.map(name=>{const match=source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));assert.ok(match);return match[0];}).join('\n');
  const hash='a'.repeat(64),kickoff='2026-11-01T17:00:00Z';
  const player={id:'fictional-ranking-player',game_id:'fictional-ranking-game',props:[{key:'rec',line:5.5,adj:8,line_from:'dk'}]};
  const board={season:2026,week:8,players:[player],games:[{id:player.game_id,kickoff}],execution_model:{}};
  const context={S:{data:board}};vm.createContext(context);vm.runInContext(functions,context);
  const item={player_id:player.id,game_id:player.game_id,key:'rec',direction:'over',line:5.5,line_from:'dk',adj:8,score:(8-5.5)/1.2,over:1,n:1,
    forecast_source:'R0_FALLBACK',product:'reference_point',model_version:null,selected_row_sha256:null,selected_row_canonical:null,
    selected_at:'2026-11-01T10:00:00Z',kickoff_utc:kickoff};
  const doc={schema_version:'weekly-selected-rankings-v1',policy:null,policy_sha256:null,season:2026,week:8,display_board_sha256:hash,overlay_sha256:hash,
    prepared_at:'2026-11-01T10:00:00Z',website_source_sha:'b'.repeat(40),picks:{over:[item],under:[]},frozen_proofs:[],
    fallback_counts:{started_without_selected_record:0,unavailable_forecast:0,expired_before_kickoff:0}};
  const pointer={schema_version:'weekly-selected-rankings-pointer-v1',path:'weekly-selected-rankings/'+hash+'.json',sha256:hash,bytes:1,
    display_board_sha256:hash,overlay_sha256:hash,published_at:'2026-11-01T10:01:00Z'};
  const overlay={boardHash:hash,assetHash:hash,rows:new Map()};
  const prepare=model=>{
    player.reference_model=model;board.execution_model.model=model;doc.policy=context.selectedRankingPolicy(board);
    const classic=['sleeper-matchup-classic-fg-identity-v1','sleeper-matchup-classic-data-integrity-v2'].includes(model);
    doc.policy_sha256=classic?'d56088350b8adf123816e4162e868aaecfd9e5181cd2f0780bb1053bd135e72f':'e8cebeadaa5debd04c06cad9c19e72485618c0f43f29a9b4553122cfeeed0696';
    item.forecast_source=classic?'CURRENT_BASELINE':'R0_FALLBACK';item.model_version=classic?model:null;
  };
  for(const model of [undefined,'original_sleeper_matchup_baseline','sleeper-matchup-classic-fg-identity-v1','sleeper-matchup-classic-data-integrity-v2']){
    prepare(model);assert.equal(await context.validateSelectedRankings(doc,pointer,board,overlay),doc);
  }
  for(const model of ['sleeper-matchup-data-integrity-v2','sleeper-matchup-classic-data-integrity-v2-unknown']){
    prepare(undefined);player.reference_model=model;
    await assert.rejects(context.validateSelectedRankings(doc,pointer,board,overlay),/Ranking source\/clock/,'unsupported weekly reference cannot inherit legacy R0 trust');
  }
  console.log('Closed weekly reference: actual reader accepts legacy/Classic identities and rejects Root-presence/unknown aliases.');
})().catch(error=>{console.error(error);process.exitCode=1;});
// The standalone About consumer needs no global escape helper for closed model
// names. Unknown values must never become HTML through the model caption.
{
  const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
  const source = fs.readFileSync(path.join(__dirname, '../output/app.js'), 'utf8');
  const about = source.match(/function renderAbout\(\) \{[\s\S]*?\n\}/)?.[0];
  const assert = require('node:assert/strict');
  for (const model of ['sleeper-matchup-classic-fg-identity-v1', 'sleeper-matchup-classic-data-integrity-v2', '<img src=x onerror=alert(1)>']) {
    const main = {innerHTML: ''};
    vm.runInNewContext(about+'\nrenderAbout();', {
      S: {data:{execution_model:{model},scoring:{},categories:{}},forecastScorecard:null},
      $:()=>main,fmt:(value,digits)=>Number(value).toFixed(digits),
    });
    if (model.startsWith('sleeper-')) assert.ok(main.innerHTML.includes('Current baseline model: '+model));
    else assert.ok(!main.innerHTML.includes(model));
  }
  console.log('3 closed-model standalone About controls passed.');
}


// Player-prop evidence correction: fictional event bodies and device records.
// Execute actual app functions/events; no network, provider outcomes or models.
(async () => {
  const legacyPins = {"current": "30eb111166adf0ef9516e3363b81fc471eb45d0c82651255c2be53790bb81a64", "slpPlayed": "80d07c27863d2c513dc90656ff7e6c8712a3f4277ae1a7c89b0c0f4e75b4c084"};
  for (const [name, expected] of Object.entries(legacyPins)) {
    const fn = source.match(new RegExp('^function '+name+'\\([\\s\\S]*?^\\}', 'm'))?.[0];
    assert.equal(require('node:crypto').createHash('sha256').update(fn).digest('hex'), expected);
  }
  const failures = []; let checks = 0;
  const test = async (name, run) => {
    checks++;
    try { await run(); } catch (error) { failures.push({ name, error: error.message }); }
  };
  class FixtureClock extends Date {
    constructor(...args) { super(...(args.length ? args : ['2099-10-25T18:00:00Z'])); }
    static now() { return Date.parse('2099-10-25T18:00:00Z'); }
  }
  const harness = () => {
    const nodes = new Map(), saved = new Map(), events = {};
    const node = name => {
      if (!nodes.has(name)) nodes.set(name, { innerHTML: '', hidden: false, style: {},
        addEventListener() {}, classList: { add() {}, remove() {}, toggle() {} }, querySelectorAll: () => [] });
      return nodes.get(name);
    };
    const box = { console, Date: FixtureClock, URL, URLSearchParams, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1,
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
    // Loader-state double isolates raw provider checks; it does not qualify a publication.
    S.grading = { pointer: { report_id: 'fictional-unit-authority' } };
    S.propOutcomeAuthority = { board: S.data, state: 'validated_current_period', season: S.data.season,
      week: S.data.week, report_id: S.grading.pointer.report_id, grading: S.grading, outcomes: S.finalOutcomes, outcomeCount: S.finalOutcomes.size };
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
  // Mutate the raw event after construction: the helper's ?? default must
  // never turn missing/null completion evidence into literal true.
  for (const [label, completed] of [['true', true], ['false', false], ['absent', undefined],
      ['null', null], ['zero', 0], ['string-false', 'false']]) await test('explicit boolean event completion: ' + label, () => {
    const h = harness(), pick = h.pick(), before = JSON.stringify(pick);
    class CompletionClock extends Date {
      constructor(...args) { super(...(args.length ? args : ['2099-10-25T18:00:00Z'])); }
      static now() { return Date.parse('2099-10-25T18:00:00Z'); }
    }
    h.box.Date = CompletionClock;
    assert.ok(Date.parse(h.g.kickoff) < h.box.Date.now(), 'fictional kickoff is in the past');
    const body = h.summary('0', '1'), type = body.header.competitions[0].status.type;
    if (label === 'absent') delete type.completed; else type.completed = completed;
    assert.equal(Object.hasOwn(type, 'completed'), label !== 'absent');
    if (label !== 'absent') assert.equal(type.completed, completed);
    h.apply(body);
    const status = h.status(pick), final = completed === true;
    assert.equal(h.S.propEvents[h.g.id].final, final);
    assert.equal(status.final, final);
    assert.equal(status.res, final ? 'hit' : 'pending');
    assert.equal(status.v, 0, 'observed played zero remains exact');
    assert.equal(JSON.stringify(pick), before, 'original saved selection remains exact');
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
    assert.equal(h.status(m).final, false); assert.equal(h.status(m).res, 'above');
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
  console.log(JSON.stringify({ suite: 'player-prop-evidence-v1', fictional_cases: checks, failures }));
  assert.equal(failures.length, 0, 'player-prop evidence regressions: ' + JSON.stringify(failures));
})().catch(error => { console.error(error); process.exitCode = 1; });


// V2: mandatory provider identity/scope; local observation time is not availability proof.
{
  const extract=(text,name)=>{const m=text.match(new RegExp('^function '+name+'\\([\\s\\S]*?^\\}', 'm'));assert.ok(m,name);return m[0];};
function identityProbe(mutate){
  const S={data:{season:2099,week:2,players:[]},games:{},propEvents:{},propSleeper:null,finalOutcomes:new Map()};
  const p={id:'fictional-p',espn_id:'900000001',game_id:'900000101',team:'QAA'};
  const g={id:p.game_id,home:'QAA',away:'QAB',kickoff:'2099-10-25T17:00:00Z',state:'post',detail:'Final'};
  S.data.players=[p];S.games[g.id]=g;
  const body={header:{id:g.id,season:{year:2099,type:2},week:{number:2},competitions:[{id:g.id,date:g.kickoff,
    status:{type:{state:'post',shortDetail:'Final',completed:true}}}]},boxscore:{players:[{team:{abbreviation:'QAA'},statistics:[{
      name:'rushing',labels:['CAR','YDS','TD'],athletes:[{athlete:{id:p.espn_id},stats:['1','0','0']}]}]}]}};
  mutate(body,S,g);
  class ScopeClock extends Date { constructor(...args){super(...(args.length?args:['2099-10-25T18:00:00Z']));} static now(){return Date.parse('2099-10-25T18:00:00Z');} }
  S.grading={pointer:{report_id:'fictional-scope-authority'}};
  S.propOutcomeAuthority={board:S.data,state:'validated_current_period',season:S.data.season,week:S.data.week,report_id:S.grading.pointer.report_id,grading:S.grading,outcomes:S.finalOutcomes,outcomeCount:S.finalOutcomes.size};
  const c={S,teamCode:x=>x,Date:ScopeClock};vm.createContext(c);
  vm.runInContext(['propFinal','propValue','propPickBound','recordPropEvidence','propEventStatus','propRawFallbackAllowed','propStatus'].map(n=>extract(source,n)).join('\n'),c);
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


// 484d composition: independently saved Phase 2 outcomes retain their contract;
// raw ESPN evidence and device picks cannot silently replace that authority.
{
  const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
  const app = fs.readFileSync(path.join(__dirname, '../output/app.js'), 'utf8');
  const failures = []; let checks = 0;
  function harness() {
    const nodes = new Map(), storage = new Map(), events = {};
    const node = key => {
      if (!nodes.has(key)) nodes.set(key, {innerHTML:'',hidden:false,style:{},addEventListener(){},
        classList:{add(){},remove(){},toggle(){}},querySelectorAll:()=>[]});
      return nodes.get(key);
    };
    class CompositionClock extends Date { constructor(...args){super(...(args.length?args:['2099-10-25T18:00:00Z']));} static now(){return Date.parse('2099-10-25T18:00:00Z');} }
    const box = {console,Date:CompositionClock,URL,URLSearchParams,setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,
      localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v))},
      document:{hidden:true,querySelector:node,querySelectorAll:()=>[],body:node('body'),documentElement:node('html'),
        addEventListener:(kind,fn)=>(events[kind]||=[]).push(fn)},
      location:{hash:''},history:{},navigator:{},CSS:{escape:x=>x},addEventListener(){},innerWidth:390,scrollY:0,scrollTo(){},confirm:()=>true,
      fetch:async()=>{throw new Error('ACTUAL_NETWORK_FORBIDDEN');}};
    box.window=box;vm.createContext(box);vm.runInContext(app.slice(0,app.indexOf('(async function start()')),box);
    const S=vm.runInContext('S',box);
    const p={id:'fictional-player',espn_id:'900000001',game_id:'900000101',team:'QAA',name:'Fictional Player',pos:'RB',props:[{key:'rush_yd',line:5.5}],log:[]};
    const g={id:p.game_id,home:'QAA',away:'QAB',kickoff:'2099-10-25T17:00:00Z',state:'post',detail:'Final'};
    S.data={season:2099,week:2,players:[p],games:[g],categories:{rush_yd:{label:'Rush Yds'}},scoring:{}};
    S.games={[g.id]:g};S.byId={[p.id]:p};S.byKey={'fictional player|QAA':p.id};S.byEspn={[p.espn_id]:p.id};
    S.grading={pointer:{report_id:'fictional-composition-authority'}};
    S.propOutcomeAuthority={board:S.data,state:'validated_current_period',season:S.data.season,week:S.data.week,report_id:S.grading.pointer.report_id,grading:S.grading,outcomes:S.finalOutcomes,outcomeCount:S.finalOutcomes.size};
    const pick={pid:p.id,gid:g.id,team:p.team,espn_id:p.espn_id,kickoff:g.kickoff,season:2099,week:2,
      key:'rush_yd',line:5.5,dir:'under',schema_version:'mypicks-player-game-v1',period:'full_game_including_overtime',stat_source:'ESPN_EVENT_BOXSCORE'};
    const final={season:2099,week:2,game_id:g.id,player_id:p.id,category:'rush_yd',team:p.team,kickoff:g.kickoff,
      status:'resolved',final_confirmed:true,actual:0,outcome_conflict:false};
    const summary={header:{id:g.id,season:{year:2099,type:2},week:{number:2},competitions:[{id:g.id,date:g.kickoff,
      status:{type:{state:'post',shortDetail:'Final',completed:true}}}]},boxscore:{players:[{team:{abbreviation:'QAA'},
      statistics:[{name:'rushing',labels:['CAR','YDS','TD'],athletes:[{athlete:{id:p.espn_id,displayName:p.name},stats:['1','9','0']}]}]}]}};
    vm.runInContext('applyInjuries=()=>{};defenseFromSummary=()=>({});',box);
    return {S,p,g,pick,final,summary,box,storage,events,node,
      publish:row=>S.finalOutcomes.set(box.finalIdentity(p,'rush_yd'),row),
      status:()=>box.propStatus(p,'rush_yd',pick.line,pick.dir,pick)};
  }
  function test(name,run){checks++;try{run(harness());}catch(error){failures.push({name,error:error.message});}}
  test('authoritative Phase 2 zero survives contradictory raw event fallback',h=>{
    h.publish(h.final);h.box.applySummary(h.g.id,h.summary,h.S.data);
    assert.equal(h.status().res,'hit');assert.equal(h.status().v,0);assert.equal(h.status().final,true);
  });
  for(const status of ['pending','unresolved'])test('saved '+status+' cannot be replaced by a raw final',h=>{
    h.publish({...h.final,status,final_confirmed:false,actual:null});h.box.applySummary(h.g.id,h.summary,h.S.data);
    assert.equal(h.status().res,status);assert.equal(h.status().final,false);
  });
  test('saved conflict cannot be replaced by raw final',h=>{
    h.publish({...h.final,outcome_conflict:true});h.box.applySummary(h.g.id,h.summary,h.S.data);
    assert.equal(h.status().res,'unresolved');assert.equal(h.status().v,null);
  });
  test('mismatched saved outcome scope cannot fall through to raw final',h=>{
    h.publish({...h.final,team:'QAB'});h.box.applySummary(h.g.id,h.summary,h.S.data);
    assert.equal(h.status().res,'unresolved');assert.equal(h.status().final,false);
  });
  test('saved final corrections remain original line-relative Phase 2 evidence',h=>{
    h.publish(h.final);assert.equal(h.status().res,'hit');h.final.actual=9;
    assert.equal(h.status().res,'miss');assert.equal(h.pick.line,5.5);
  });
  test('authoritative final cannot repoint an old saved athlete',h=>{
    h.publish(h.final);h.pick.espn_id='900000999';assert.equal(h.status().res,'unresolved');
  });
  test('legacy pick stays unresolved even with a qualified current-player final',h=>{
    h.publish(h.final);const old={...h.pick};delete old.schema_version;delete old.gid;
    const raw=' \n[ '+JSON.stringify(old)+' ]\n';h.S.mine=[old];h.storage.set('nflprops.mine',raw);h.box.renderMine();
    assert.match(h.node('#main').innerHTML,/UNRESOLVED/);assert.equal(h.storage.get('nflprops.mine'),raw);
  });
  test('invalid event headers cannot borrow name-matched fantasy live values',h=>{
    h.g.state='in';h.g.detail='Q3';h.S.live[h.p.id]={gp:1,rush_yd:99};delete h.summary.header.week;
    h.box.applySummary(h.g.id,h.summary,h.S.data);assert.equal(h.status().res,'unresolved');assert.equal(h.status().v,null);
  });
  test('previous-board summary cannot mutate caches or new event state',h=>{
    const board=h.S.data;h.S.data={...board,week:3};const before=JSON.stringify({sum:h.S.sum,live:h.S.live,events:h.S.propEvents});
    h.box.applySummary(h.g.id,h.summary,board);assert.equal(JSON.stringify({sum:h.S.sum,live:h.S.live,events:h.S.propEvents}),before);
  });
  test('live fantasy prop keeps Phase 2 presence/scoring with scoped Sleeper values',h=>{
    h.g.state='in';h.S.data.scoring={rush_yd:.1,rec:1};h.S.slp[h.p.id]={gp:1,rush_yd:10,rec:1};
    h.S.propSleeper={board:h.S.data,players:h.S.slp};
    const st=h.box.propStatus(h.p,'fpts',2,'over');assert.equal(st.v,2);assert.equal(st.res,'equal');assert.equal(st.final,false);
  });
  test('fantasy prop keeps explicit unknown scoring components unresolved',h=>{
    h.g.state='in';h.S.data.scoring={rush_yd:.1,rec:1};h.S.slp[h.p.id]={gp:1,rush_yd:null,rec:1};
    h.S.propSleeper={board:h.S.data,players:h.S.slp};
    const st=h.box.propStatus(h.p,'fpts',2,'over');
    assert.deepEqual(JSON.parse(JSON.stringify(st)),{v:null,res:'unresolved',final:false,reason:'Live scoring components are unavailable or incomplete'});
  });
  test('exact saved removal preserves unrelated legacy object bytes',h=>{
    const old='{ "pid":"fictional-old", "key":"rush_yd", "line":7.50, "season":2098, "week":1 }';
    h.storage.set('nflprops.mine','[ '+old+', '+JSON.stringify(h.pick)+' ]');h.S.mine=JSON.parse(h.storage.get('nflprops.mine'));
    const button={dataset:{rm:'p',mineIndex:'1'}};
    for(const fn of h.events.click)fn({target:{closest:selector=>selector==='[data-rm]'?button:null},preventDefault(){}});
    assert.equal(h.S.mine.length,1);assert.ok(h.storage.get('nflprops.mine').includes(old));
  });
  test('non-numeric personal edit cannot partially parse into a stored line',h=>{
    h.S.mine=[h.pick];const raw=JSON.stringify(h.S.mine);h.storage.set('nflprops.mine',raw);
    const target={dataset:{mline:'p',mineIndex:'0'},value:'0garbage',matches:()=>false};
    for(const fn of h.events.change)fn({target});assert.equal(h.pick.line,5.5);assert.equal(h.storage.get('nflprops.mine'),raw);
  });
  console.log(JSON.stringify({suite:'actual-484d-prop-phase2-composition',fictional_cases:checks,failures}));
  assert.equal(failures.length,0,'Phase 2 prop composition: '+JSON.stringify(failures));
}


// Correctness controls for required outcome availability, board epochs, raw clocks
// and fantasy missingness. In-memory transport serves actual hash-checked assets.
{
// Fictional, actual bounded pointer/index/period readers and Node VM app functions.
// All fetches are in-memory Responses; no provider or production qualification.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const file=path.join(__dirname,'../output/app.js'),app=fs.readFileSync(file,'utf8');
const at='2099-10-25T18:00:00Z',kickoff='2099-10-25T17:00:00Z',hash=v=>crypto.createHash('sha256').update(v).digest('hex');
function fixture(){
 const nodes=new Map(),storage=new Map([['nflprops.mine','PRIVATE_BYTES'],['nflprops.paper-ticket.v1.existing','TICKET_BYTES'],['nflprops.paper-leg.v1.existing','LEG_BYTES'],['nflprops.paper-draft.v1','DRAFT_BYTES']]),requests=[];
 const node=k=>{if(!nodes.has(k))nodes.set(k,{innerHTML:'',hidden:false,style:{},addEventListener(){},classList:{add(){},remove(){},toggle(){}},querySelectorAll:()=>[]});return nodes.get(k);};
 let now=at;class Clock extends Date{constructor(...a){super(...(a.length?a:[now]));}static now(){return Date.parse(now);}}
 const box={console,Date:Clock,URL,URLSearchParams,TextEncoder,TextDecoder,Response,ReadableStream,Blob,DecompressionStream,structuredClone,crypto:crypto.webcrypto,
  setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v))},
  document:{hidden:true,querySelector:node,querySelectorAll:()=>[],body:node('body'),documentElement:node('html'),addEventListener(){}},
  location:{hash:''},history:{},navigator:{},CSS:{escape:x=>x},addEventListener(){},innerWidth:390,scrollY:0,scrollTo(){},confirm:()=>true,
  fetch:async(url)=>{requests.push(String(url));throw Error('NO_REAL_NETWORK');}};
 box.window=box;vm.createContext(box);vm.runInContext(app.slice(0,app.indexOf('(async function start()')),box);
 const S=vm.runInContext('S',box),p={id:'fictional-player',espn_id:'900000001',game_id:'900000101',team:'QAA',name:'Fictional Player',pos:'RB',props:[{key:'rush_yd',line:5.5}],log:[]};
 const g={id:p.game_id,home:'QAA',away:'QAB',kickoff,state:'post',detail:'Final'};
 S.data={season:2099,week:2,players:[p],games:[g],categories:{rush_yd:{label:'Rush Yds'},fpts:{label:'Fantasy'}},scoring:{rush_yd:.1,rec:1}};
 S.games={[g.id]:g};S.byId={[p.id]:p};S.byKey={'fictional player|QAA':p.id};S.byEspn={[p.espn_id]:p.id};
 const pick={pid:p.id,gid:g.id,team:p.team,espn_id:p.espn_id,kickoff,season:2099,week:2,key:'rush_yd',line:5.5,dir:'under',schema_version:'mypicks-player-game-v1',period:'full_game_including_overtime',stat_source:'ESPN_EVENT_BOXSCORE'};
 const summary=()=>({header:{id:g.id,season:{year:2099,type:2},week:{number:2},competitions:[{id:g.id,date:kickoff,status:{type:{state:'post',shortDetail:'Final',completed:true}}}]},boxscore:{players:[{team:{abbreviation:'QAA'},statistics:[{name:'rushing',labels:['CAR','YDS','TD'],athletes:[{athlete:{id:p.espn_id,displayName:p.name},stats:['1','9','0']}]}]}]}});
 vm.runInContext('applyInjuries=()=>{};defenseFromSummary=()=>({});',box);
 function publication({id='a'.repeat(64),week=2,plain=false,wrongPeriod=false,wrongGeneration=false}={}){
  const assets=new Map(),put=(payload,filename,partition=false)=>{const raw=Buffer.from(JSON.stringify({...payload,report_id:id}));const digest=hash(raw),name=(partition?digest:id)+'/'+filename;assets.set('data/selection-grading/'+name,raw);return {path:name,sha256:digest,...(!plain?{decoded_bytes:raw.length}:{})};};
  const row={season:2099,week:wrongPeriod?3:week,game_id:'fictional-other-game',player_id:'fictional-other-player',category:'rec',team:'QAA',kickoff,status:'pending',actual:null,final_confirmed:false,outcome_conflict:false};
  let summary,outcomes;
  if(plain){summary=put({schema_version:'selection-public-report-v1',report_schema_version:'selection-report-v2',summary:{tables:[]}},'summary.json');outcomes=put({schema_version:'selection-final-outcomes-v1',outcomes:[row]},'outcomes.json');}
  else{
   const raw=Buffer.from(JSON.stringify({schema_version:'selection-final-outcome-period-v1',report_id:wrongGeneration?'b'.repeat(64):id,season:2099,week:wrongPeriod?3:week,outcomes:[row]}));
   const digest=hash(raw),period={path:digest+'/outcomes.json',sha256:digest,decoded_bytes:raw.length,season:2099,week,count:1};assets.set('data/selection-grading/'+period.path,raw);
   summary=put({schema_version:'selection-public-report-v3',report_schema_version:'selection-report-v3',row_count:0,contexts:{},summary_partitions:[],summary:{}},'summary.json');
   outcomes=put({schema_version:'selection-final-outcome-index-v1',outcome_count:1,periods:[period]},'outcomes.json');
  }
  const pointer={schema_version:plain?'selection-publication-pointer-v1':'selection-publication-pointer-v2',report_id:id,generated_at:now,row_count:0,rows:[],summary,outcomes};
  assets.set('data/selection-grading/latest.json',Buffer.from(JSON.stringify(pointer)));return {assets,pointer};
 }
 function serve(pub,override=null){box.fetch=async url=>{url=String(url);requests.push(url);if(override){const response=await override(url,pub);if(response)return response;}return pub.assets.has(url)?new Response(pub.assets.get(url),{status:200,headers:{'Content-Type':'application/json'}}):new Response('missing',{status:500});};}
 const status=()=>box.propStatus(p,'rush_yd',pick.line,pick.dir,pick),apply=body=>box.applySummary(g.id,body||summary(),S.data);
 return {box,S,p,g,pick,summary,status,apply,storage,requests,publication,serve,setClock:value=>now=value};
}
const failures=[],passed=[];
async function test(name,fn){try{await fn(fixture());passed.push(name);}catch(e){failures.push({name,error:e.message});}}
(async()=>{
 for(const plain of [false,true])await test('actual hashed '+(plain?'plain':'partitioned')+' complete period permits absent-key raw fallback',async h=>{const pub=h.publication({plain});h.serve(pub);await h.box.loadGrading();assert.ok(h.S.grading,h.S.gradingError);h.apply();assert.equal(h.status().v,9);assert.equal(h.status().final,true);});
 for(const status of [404,500])await test('pointer HTTP'+status+' stays unavailable',async h=>{h.serve(h.publication(),url=>url.endsWith('latest.json')?new Response('missing',{status}):null);h.apply();await h.box.loadGrading();assert.equal(h.status().res,'unresolved');assert.equal(h.status().v,null);});
 await test('malformed pointer stays unavailable',async h=>{h.serve(h.publication(),url=>url.endsWith('latest.json')?new Response('{',{status:200}):null);h.apply();await h.box.loadGrading();assert.equal(h.status().res,'unresolved');});
 for(const mode of ['missing','corrupt'])await test('required partition '+mode+' stays unavailable',async h=>{const pub=h.publication();h.serve(pub,(url,p)=>{if(url.endsWith('/outcomes.json')&&!url.startsWith('data/selection-grading/'+p.pointer.report_id+'/'))return mode==='missing'?new Response('missing',{status:500}):new Response(Buffer.concat([p.assets.get(url),Buffer.from(' ')]),{status:200});});h.apply();await h.box.loadGrading();assert.equal(h.status().res,'unresolved');assert.equal(h.status().v,null);});
 for(const option of [{week:3},{wrongPeriod:true},{wrongGeneration:true}])await test('wrong/absent required period or generation '+JSON.stringify(option),async h=>{h.serve(h.publication(option));h.apply();await h.box.loadGrading();assert.equal(h.status().res,'unresolved');assert.equal(h.status().final,false);});
 await test('loading is not successful absence',async h=>{let finish;const pub=h.publication();h.serve(pub,url=>url.endsWith('latest.json')?new Promise(done=>finish=done):null);h.apply();const pending=h.box.loadGrading();assert.equal(h.status().res,'unresolved');finish(new Response(pub.assets.get('data/selection-grading/latest.json')));await pending;assert.equal(h.status().final,true);});
 await test('old board response cannot assign grading to a new board',async h=>{let finish;const pub=h.publication();h.serve(pub,url=>url.endsWith('latest.json')?new Promise(done=>finish=done):null);const pending=h.box.loadGrading();const old=h.S.data;h.S.data={...old,week:3};finish(new Response(pub.assets.get('data/selection-grading/latest.json')));await pending;assert.equal(h.S.grading,null);assert.equal(h.S.finalOutcomes.size,0);assert.equal(h.box.propRawFallbackAllowed(),false);});
 await test('same-period replacement board cannot borrow old authority',async h=>{h.serve(h.publication());await h.box.loadGrading();h.apply();h.S.data={...h.S.data};assert.equal(h.status().res,'unresolved');});
 await test('same-id replacement grading object cannot inherit old raw absence authority',async h=>{h.serve(h.publication());await h.box.loadGrading();h.apply();assert.equal(h.status().final,true);h.S.grading={...h.S.grading};assert.equal(h.box.propRawFallbackAllowed(),false);assert.equal(h.status().res,'unresolved');});
 await test('clearing the witnessed outcome map cannot inherit successful complete-period absence',async h=>{h.serve(h.publication());await h.box.loadGrading();h.apply();assert.equal(h.status().final,true);h.S.finalOutcomes.clear();assert.equal(h.box.propRawFallbackAllowed(),false);assert.equal(h.status().res,'unresolved');});
 await test('replacement outcome map cannot inherit old raw absence authority',async h=>{h.serve(h.publication());await h.box.loadGrading();h.apply();assert.equal(h.status().final,true);h.S.finalOutcomes=new Map(h.S.finalOutcomes);assert.equal(h.box.propRawFallbackAllowed(),false);assert.equal(h.status().res,'unresolved');});
 await test('old publication response cannot overwrite newer complete report',async h=>{const a=h.publication(),b=h.publication({id:'b'.repeat(64)});let finish,count=0;h.serve({assets:new Map([...a.assets,...b.assets]),pointer:b.pointer},url=>url.endsWith('latest.json')?(++count===1?new Promise(done=>finish=done):new Response(b.assets.get(url))):null);const first=h.box.loadGrading();await h.box.loadGrading();finish(new Response(a.assets.get('data/selection-grading/latest.json')));await first;assert.equal(h.S.grading.pointer.report_id,b.pointer.report_id);h.apply();assert.equal(h.status().final,true);});
 for(const fields of [{gp:1,rush_yd:null,rec:1},{gp:1,rush_yd:10,rec:null}])for(const line of [2,-1])await test('unknown fantasy component is unresolved '+JSON.stringify(fields)+' line'+line,h=>{h.g.state='in';h.S.slp[h.p.id]=fields;h.S.propSleeper={board:h.S.data,players:h.S.slp};const s=h.box.propStatus(h.p,'fpts',line,'over');assert.equal(s.v,null);assert.equal(s.res,'unresolved');});
 for(const [stats,expected]of [[{gp:1,rush_yd:0,rec:0},0],[{gp:1,rush_yd:-2,rec:0},-.2],[{gp:1,rush_yd:10,rec:1},2]])await test('known fantasy zero/signed/complete preserved '+expected,h=>{h.g.state='in';h.S.slp[h.p.id]=stats;const s=h.box.propStatus(h.p,'fpts',2,'over');assert.equal(s.v,expected);assert.equal(s.res,expected===2?'equal':'below');});
 for(const clock of ['2099-10-25T16:00:00Z'])await test('raw final cannot precede kickoff',async h=>{h.setClock(clock);h.serve(h.publication());await h.box.loadGrading();h.apply();assert.equal(h.status().res,'unresolved');assert.equal(h.status().final,false);});
 for(const value of [undefined,'bad','2099-10-25T16:00:00Z','2099-10-25T17:00:00Z','2099-10-25T19:00:00Z'])await test('raw observation clock rejects '+String(value),async h=>{h.serve(h.publication());await h.box.loadGrading();h.apply();h.S.propEvents[h.g.id].observed_at=value;assert.equal(h.status().res,'unresolved');});
 for(const yards of ['9.5','9007199254740992'])await test('raw yardage actual must be a safe integer '+yards,async h=>{h.serve(h.publication());await h.box.loadGrading();const body=h.summary();body.boxscore.players[0].statistics[0].athletes[0].stats[1]=yards;h.apply(body);assert.equal(h.status().res,'unresolved');});
 for(const yards of ['0','-1','9'])await test('raw valid zero/signed/integer yardage '+yards,async h=>{h.serve(h.publication());await h.box.loadGrading();const body=h.summary();body.boxscore.players[0].statistics[0].athletes[0].stats[1]=yards;h.apply(body);assert.equal(h.status().v,Number(yards));assert.equal(h.status().final,true);});
 await test('raw final cannot become paper or public outcome authority',async h=>{h.serve(h.publication());await h.box.loadGrading();const before=JSON.stringify([...h.S.finalOutcomes]);h.apply();assert.equal(h.status().final,true);assert.equal(JSON.stringify([...h.S.finalOutcomes]),before);const leg={season:2099,week:2,game_id:h.g.id,player_id:h.p.id,category:'rush_yd',team:h.p.team,name:h.p.name,period:'full_game',kickoff,line:5.5,side:'under',line_source:'dk',raw_projection:5,adjusted_projection:4,board_generated_at:'2099-10-25T15:00:00Z',quote_observed_at:null};assert.equal(h.box.paperLegStatus(leg,h.S.finalOutcomes).status,'unresolved');});
 await test('all private namespaces remain unchanged',async h=>{const before=JSON.stringify([...h.storage]);h.serve(h.publication());await h.box.loadGrading();h.apply();h.status();assert.equal(JSON.stringify([...h.storage]),before);assert.ok(h.requests.every(url=>url.startsWith('data/selection-grading/')));});
 console.log(JSON.stringify({suite:'prop-outcome-authority-actual-readers',checks:passed.length+failures.length,failures,actual_reader_used:true,HTTP_provider_requests:0,production_qualification:false}));if(failures.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
}

// Fully bound saved personal selections keep their own historical period. These
// tests use the actual bounded, hash-checked publication readers; all transport
// is fictional in-memory Responses, without provider requests or qualification.
{
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const app=fs.readFileSync(path.join(__dirname,'../output/app.js'),'utf8'),digest=v=>crypto.createHash('sha256').update(v).digest('hex');
function savedHistoryFixture(){
 const nodes=new Map(),storage=new Map(),events={},requests=[];
 const node=k=>{if(!nodes.has(k))nodes.set(k,{innerHTML:'',hidden:false,style:{},addEventListener(){},classList:{add(){},remove(){},toggle(){}},querySelectorAll:()=>[]});return nodes.get(k);};
 class Clock extends Date{constructor(...a){super(...(a.length?a:['2099-10-25T22:00:00Z']));}static now(){return Date.parse('2099-10-25T22:00:00Z');}}
 const box={console,Date:Clock,URL,URLSearchParams,TextEncoder,TextDecoder,Response,ReadableStream,Blob,DecompressionStream,structuredClone,crypto:crypto.webcrypto,
  setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v))},
  document:{hidden:true,querySelector:node,querySelectorAll:()=>[],body:node('body'),documentElement:node('html'),addEventListener:(kind,fn)=>(events[kind]||=[]).push(fn)},
  location:{hash:''},history:{},navigator:{},CSS:{escape:x=>x},addEventListener(){},innerWidth:390,scrollY:0,scrollTo(){},confirm:()=>true,
  fetch:async()=>{throw Error('NO_REAL_NETWORK');}};box.window=box;vm.createContext(box);vm.runInContext(app.slice(0,app.indexOf('(async function start()')),box);
 const S=vm.runInContext('S',box),p={id:'fictional-saved-player',espn_id:'900000001',game_id:'900000202',team:'QZZ',name:'Fictional Saved Player',pos:'RB',props:[{key:'rush_yd',line:99.5}],log:[]};
 const g={id:p.game_id,home:'QZZ',away:'QZY',kickoff:'2099-10-25T17:00:00Z',state:'post',detail:'Final'};
 S.data={season:2099,week:2,players:[p],games:[g],categories:{rush_yd:{label:'Rush Yds'}},scoring:{}};S.games={[g.id]:g};S.byId={[p.id]:p};
 const pick={pid:p.id,gid:'900000101',team:'QAA',espn_id:p.espn_id,kickoff:'2099-10-18T17:00:00Z',season:2099,week:1,key:'rush_yd',line:5.5,dir:'under',schema_version:'mypicks-player-game-v1',period:'full_game_including_overtime',stat_source:'ESPN_EVENT_BOXSCORE'};
 const outcome={season:2099,week:1,game_id:pick.gid,player_id:pick.pid,team:pick.team,category:pick.key,kickoff:pick.kickoff,status:'resolved',actual:0,final_confirmed:true,outcome_conflict:false,game_state:'post',outcome_selection:'confirmed',collected_at:'2099-10-18T21:00:00Z',outcome_snapshot_sha256:'1'.repeat(64),selected_outcome_row_sha256:'2'.repeat(64),selected_outcome_provenance_sha256:'3'.repeat(64)};
 const current={...outcome,week:2,game_id:g.id,team:p.team,kickoff:g.kickoff,collected_at:'2099-10-25T21:00:00Z',actual:100};
 function publication({id='a'.repeat(64),row=outcome,omit=false,wrongGeneration=false,plain=false}={}){
  const assets=new Map(),put=(value,name,partition=false)=>{const raw=Buffer.from(JSON.stringify({...value,report_id:value.report_id||id})),sha=digest(raw),descriptor={path:(partition?sha:id)+'/'+name,sha256:sha,decoded_bytes:raw.length};assets.set('data/selection-grading/'+descriptor.path,raw);return descriptor;};
  const part=(week,rows)=>({...put({schema_version:'selection-final-outcome-period-v1',report_id:wrongGeneration&&week===1?'b'.repeat(64):id,season:2099,week,outcomes:rows},'outcomes.json',true),season:2099,week,count:rows.length});
  const periods=[part(2,[current]),...(!omit?[part(1,[row])]:[]),part(3,[{...current,week:3,status:'pending',actual:null,final_confirmed:false}])];
  const summary=put({schema_version:'selection-public-report-v3',report_schema_version:'selection-report-v3',row_count:0,contexts:{},summary_partitions:[],summary:{}},'summary.json');
  const outcomes=put({schema_version:'selection-final-outcome-index-v1',outcome_count:periods.length,periods},'outcomes.json');
  let pointer={schema_version:'selection-publication-pointer-v2',report_id:id,generated_at:'2099-10-25T22:00:00Z',row_count:0,rows:[],summary,outcomes};
  if(plain){const descriptor=(value,name)=>{const d=put(value,name);delete d.decoded_bytes;return d;};pointer={...pointer,schema_version:'selection-publication-pointer-v1',summary:descriptor({schema_version:'selection-public-report-v1',report_schema_version:'selection-report-v2',summary:{tables:[]}},'summary.json'),outcomes:descriptor({schema_version:'selection-final-outcomes-v1',outcomes:[current,...(!omit?[row]:[])]},'outcomes.json')};}
  assets.set('data/selection-grading/latest.json',Buffer.from(JSON.stringify(pointer)));return {assets,pointer,periods};
 }
 function serve(pub,override){box.fetch=async url=>{url=String(url);requests.push(url);if(override){const response=await override(url,pub);if(response)return response;}return pub.assets.has(url)?new Response(pub.assets.get(url),{status:200}):new Response('missing',{status:500});};}
 async function load(pub=publication(),override){serve(pub,override);await box.loadGrading();assert.ok(S.grading,S.gradingError);}
 // Await the actual async loader jobs, including real WebCrypto work. A count
 // of event-loop turns is not a completion signal when other retained suites
 // run concurrently in this process.
 const jobs=new Set(),actualHistoricalLoader=box.loadHistoricalMineOutcomes;
 box.loadHistoricalMineOutcomes=(...args)=>{
  const task={job:actualHistoricalLoader(...args),grading:S.grading,board:S.data};jobs.add(task);
  task.job.then(()=>jobs.delete(task),()=>jobs.delete(task));return task.job;
 };
 async function drain({currentOnly=false}={}){
  let watchdog;
  const pending=()=>[...jobs].filter(task=>!currentOnly||task.grading===S.grading&&task.board===S.data);
  try{await Promise.race([(async()=>{while(pending().length)await Promise.all(pending().map(task=>task.job));})(),
   new Promise((_,reject)=>{watchdog=setTimeout(()=>reject(Error('Historical loader did not settle')),2000);})]);}
  finally{clearTimeout(watchdog);}
 }
 function choose(records=[pick]){S.mine=records;storage.set('nflprops.mine',JSON.stringify(records));S.tab='mine';box.renderMine();}
 return {box,S,p,g,pick,outcome,current,node,storage,events,requests,publication,serve,load,drain,choose,status:()=>box.historicalPropStatus(pick)};
}
const failures=[],passed=[];
async function historyTest(name,run){try{await run(savedHistoryFixture());passed.push(name);}catch(error){failures.push({name,error:error.message});}}
(async()=>{
 await historyTest('exact old contract grades on its own team/game despite new current contract',async h=>{await h.load();h.choose();await h.drain();assert.equal(h.status().v,0);assert.equal(h.status().res,'hit');assert.equal(h.status().final,true);const html=h.node('#main').innerHTML;assert.match(html,/Saved 2099 week 1/);assert.match(html,/QAA/);assert.doesNotMatch(html,/DK line 99.5/);assert.match(html,/Final wins/);assert.equal(h.pick.line,5.5);});
 await historyTest('supported complete plain legacy publication retains exact historical result',async h=>{await h.load(h.publication({plain:true}));const before=h.requests.length;h.choose();await h.drain();assert.equal(h.status().res,'hit');assert.equal(h.status().v,0);assert.equal(h.requests.length,before);});
 for(const option of [{row:{season:2099,week:2}},{wrongGeneration:true}])await historyTest('self-consistently hashed historical wrong period/generation rejects '+JSON.stringify(option),async h=>{const pub=h.publication(option.row?{row:{...h.outcome,...option.row}}:option);await h.load(pub);h.choose();await h.drain();assert.equal(h.status().res,'unresolved');assert.equal(h.status().v,null);});
 await historyTest('only current and actually required historical period are fetched once',async h=>{const pub=h.publication();await h.load(pub);const before=h.requests.length;h.choose([h.pick,{...h.pick,key:'rec'}]);await h.drain();h.box.renderMine();await h.drain();const old='data/selection-grading/'+pub.periods.find(p=>p.week===1).path,future='data/selection-grading/'+pub.periods.find(p=>p.week===3).path;assert.equal(h.requests.filter(x=>x===old).length,1);assert.equal(h.requests.filter(x=>x===future).length,0);assert.equal(h.requests.length,before+1);});
 for(const actual of [5.5,8])await historyTest('saved line remains independently relative to correction '+actual,async h=>{const value=actual===5.5?5:actual;h.pick.line=actual===5.5?5:5.5;await h.load(h.publication({row:{...h.outcome,actual:value}}));h.choose();await h.drain();assert.equal(h.status().res,value===5?'push':'miss');assert.equal(h.pick.line,value===5?5:5.5);});
 for(const status of ['dnp','pending','unresolved'])await historyTest('historical '+status+' retains exact supported state',async h=>{await h.load(h.publication({row:{...h.outcome,status,actual:null,final_confirmed:status==='dnp'}}));h.choose();await h.drain();assert.equal(h.status().res,status);assert.equal(h.status().final,status==='dnp');});
 await historyTest('missing indexed history stays unresolved despite current matching player final',async h=>{await h.load(h.publication({omit:true}));h.choose();await h.drain();assert.equal(h.status().res,'unresolved');assert.equal(h.status().v,null);});
 for(const failure of ['missing','corrupt'])await historyTest('required historical '+failure+' is unavailable without retry loop',async h=>{const pub=h.publication(),old='data/selection-grading/'+pub.periods.find(p=>p.week===1).path;await h.load(pub,url=>url===old?new Response(failure==='missing'?'missing':Buffer.concat([pub.assets.get(url),Buffer.from(' ')]),{status:failure==='missing'?500:200}):null);h.choose();await h.drain();h.box.renderMine();await h.drain();assert.equal(h.status().res,'unresolved');assert.equal(h.status().v,null);assert.equal(h.requests.filter(x=>x===old).length,1);});
 for(const change of [{team:'QAB'},{game_id:'900000999'},{player_id:'fictional-other'},{kickoff:'2099-10-18T18:00:00Z'},{outcome_conflict:true,status:'unresolved',actual:null,final_confirmed:false}])await historyTest('historical identity/conflict cannot borrow '+JSON.stringify(change),async h=>{await h.load(h.publication({row:{...h.outcome,...change}}));h.choose();await h.drain();assert.equal(h.status().res,'unresolved');});
 for(const mapping of [null,'900000999'])await historyTest('changed current ESPN mapping cannot alter exact saved primary identity '+mapping,async h=>{h.p.espn_id=mapping;await h.load();h.choose();await h.drain();assert.equal(h.status().res,'hit');assert.equal(h.status().v,0);});
 await historyTest('absent current player cannot erase a fully bound saved public result',async h=>{delete h.S.byId[h.p.id];await h.load();h.choose();await h.drain();assert.equal(h.status().res,'hit');assert.equal(h.status().v,0);assert.match(h.node('#main').innerHTML,/Saved player selection unavailable/);});
 await historyTest('supported nullable saved ESPN id retains exact primary historical grading',async h=>{h.pick.espn_id=null;await h.load();h.choose();await h.drain();assert.equal(h.status().res,'hit');assert.equal(h.status().v,0);});
 await historyTest('old unbound record bytes remain excluded and untouched',async h=>{const old={pid:h.pick.pid,key:h.pick.key,line:1,season:2098,week:1};const raw='[  '+JSON.stringify(old)+' , '+JSON.stringify(h.pick)+' ]';await h.load();h.S.mine=JSON.parse(raw);h.storage.set('nflprops.mine',raw);h.S.tab='mine';h.box.renderMine();await h.drain();assert.equal(h.storage.get('nflprops.mine'),raw);assert.match(h.node('#main').innerHTML,/Saved 2099 week 1/);});
 await historyTest('historical exact-index personal edit preserves unrelated original bytes',async h=>{const old='{ "pid":"unbound", "key":"rec", "line":7.50, "season":2098, "week":1 }';await h.load();h.S.mine=JSON.parse('[ '+old+', '+JSON.stringify(h.pick)+' ]');h.storage.set('nflprops.mine','[ '+old+', '+JSON.stringify(h.pick)+' ]');h.S.tab='mine';h.box.renderMine();await h.drain();const target={dataset:{mline:'p',mineIndex:'1'},value:'0',matches:()=>false};for(const fn of h.events.change)fn({target});assert.equal(h.S.mine[1].line,0);assert.ok(h.storage.get('nflprops.mine').includes(old));});
 await historyTest('a delayed old board cannot assign historical results or redraw new selection',async h=>{const pub=h.publication(),old='data/selection-grading/'+pub.periods.find(p=>p.week===1).path;let finish;await h.load(pub,url=>url===old?new Promise(done=>finish=done):null);h.choose();await new Promise(done=>setImmediate(done));const html=h.node('#main').innerHTML;h.S.data={...h.S.data};finish(new Response(pub.assets.get(old)));await h.drain();assert.equal(h.status().res,'unresolved');assert.equal(h.node('#main').innerHTML,html);});
 await historyTest('a delayed old publication cannot supply new publication totals',async h=>{const a=h.publication(),old='data/selection-grading/'+a.periods.find(p=>p.week===1).path;let finish;await h.load(a,url=>url===old?new Promise(done=>finish=done):null);h.choose();await new Promise(done=>setImmediate(done));const b=h.publication({id:'b'.repeat(64),row:{...h.outcome,actual:8}});await h.load(b);h.box.renderMine();await h.drain({currentOnly:true});assert.equal(h.status().res,'miss');finish(new Response(a.assets.get(old)));await h.drain();assert.equal(h.status().res,'miss');assert.equal(h.S.grading.pointer.report_id,b.pointer.report_id);});
 await historyTest('selection changed during response never renders old saved-line totals',async h=>{const pub=h.publication(),old='data/selection-grading/'+pub.periods.find(p=>p.week===1).path;let finish;await h.load(pub,url=>url===old?new Promise(done=>finish=done):null);h.choose();await new Promise(done=>setImmediate(done));h.S.mine=[{...h.pick,line:-1}];h.box.renderMine();const html=h.node('#main').innerHTML;finish(new Response(pub.assets.get(old)));await h.drain();assert.equal(h.node('#main').innerHTML,html);h.box.renderMine();assert.match(h.node('#main').innerHTML,/value="-1"/);assert.equal(h.box.minePlayerStatus(h.S.mine[0]).res,'miss');});
 for(const field of ['key','season','week','team','gid','pid','kickoff'])await historyTest('malformed historical saved '+field+' stays inspectable/unresolved',async h=>{h.pick[field]=JSON.parse('{"toString":null,"valueOf":null}');await h.load();const bytes=JSON.stringify([h.pick]);h.choose();await h.drain();assert.equal(h.box.minePlayerStatus(h.pick).res,'unresolved');assert.equal(h.storage.get('nflprops.mine'),bytes);assert.match(h.node('#main').innerHTML,/UNRESOLVED/);});
 await historyTest('raw event current outcome and caches cannot settle unavailable history',async h=>{await h.load(h.publication({omit:true}));h.S.propEvents[h.pick.gid]={final:true,players:{[h.pick.pid]:{stats:{rush_yd:99},played:true}}};h.choose();await h.drain();assert.equal(h.status().res,'unresolved');assert.equal(h.status().final,false);});
 console.log(JSON.stringify({suite:'saved-mypicks-own-period-actual-readers',checks:passed.length+failures.length,failures,actual_reader_used:true,HTTP_provider_requests:0,production_qualification:false}));if(failures.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
}
