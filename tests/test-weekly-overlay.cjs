"use strict";
const assert=require("node:assert/strict"), fs=require("node:fs"), path=require("node:path"), vm=require("node:vm");
const root=path.resolve(__dirname,".."), helper=fs.existsSync(path.join(root,"website_packet/weekly-adaptive-overlay.js"))?path.join(root,"website_packet/weekly-adaptive-overlay.js"):path.join(root,"output/weekly-adaptive-overlay.js");
const overlay=require(helper), H="a".repeat(64), kickoff="2026-10-25T17:00:00Z";
const board={season:2026,week:8,games:[{id:"fictional-game",kickoff,state:"pre"}],players:[{id:"fictional-player",game_id:"fictional-game",props:[{key:"rush_att",line:3,adj:2.5},{key:"rush_yd"},{key:"anytime_td"},{key:"fpts"}]}]};
function row(category="rush_att") {return {player_id:"fictional-player",game_id:"fictional-game",category,method_id:"FICTIONAL",model_version:H,procedure_version:H,product:"point_mean",prediction_functional:"expected_mean",forecast_value:3.25,horizon:"player_game",source_cutoff_utc:"2026-10-25T16:00:00Z",issued_at:"2026-10-24T10:00:00Z",persistence_completed_at:"2026-10-24T10:01:00Z",kickoff_utc:kickoff,valid_until_utc:kickoff,selection_sha256:H,source_policy_sha256:H,query_source_sha256:H,first_prepared_at:"2026-10-24T10:02:00Z"};}
function doc(r=row()) {return {schema_version:"weekly-adaptive-public-overlay-v1",registration_id:"weekly-adaptive-release-v1",state:"PROVISIONAL",season:2026,week:8,canonical_board_sha256:H,display_board_sha256:H,board_contract_sha256:H,prepared_at:"2026-10-24T10:02:00Z",packaged_at:"2026-10-24T10:02:00Z",website_source_sha:"b".repeat(40),publication_review_sha256:H,rows:[r],frozen_rows:[],fallback_counts:{}};}
let checks=0;function check(fn){fn();checks++;}
check(()=>{const before=JSON.stringify(board),d=doc(),o=overlay.validate(d,board,H);assert.match(overlay.card(o,board.players[0],"rush_att",Date.parse("2026-10-24T12:00:00Z")),/Provisional selected forecast/);assert.equal(JSON.stringify(board),before);assert.equal(board.players[0].props[0].line,3);assert.equal(board.players[0].props[0].adj,2.5);});
check(()=>assert.throws(()=>overlay.validate(doc(),board,"0".repeat(64))));
check(()=>{const d=doc();d.rows.push({...d.rows[0],model_version:"c".repeat(64)});assert.throws(()=>overlay.validate(d,board,H));});
check(()=>assert.throws(()=>overlay.validate(doc({...row(),player_id:"not-on-board"}),board,H)));
check(()=>assert.throws(()=>overlay.validate(doc({...row(),category:"fpts"}),board,H)));
check(()=>assert.throws(()=>overlay.validate(doc({...row(),product:"point_blend"}),board,H)));
check(()=>assert.throws(()=>overlay.validate(doc({...row(),source_cutoff_utc:kickoff}),board,H)));
check(()=>{const d=doc({...row("rush_yd"),product:"point_median",prediction_functional:"intended_median",forecast_value:-2.5});assert.match(overlay.card(overlay.validate(d,board,H),board.players[0],"rush_yd",Date.parse("2026-10-24T12:00:00Z")),/-2.50/);});
check(()=>{const d=doc({...row("anytime_td"),product:"binary_probability",prediction_functional:"event_probability",forecast_value:.35});assert.match(overlay.card(overlay.validate(d,board,H),board.players[0],"anytime_td",Date.parse("2026-10-24T12:00:00Z")),/35.0%/);});
check(()=>{const d=doc({...row(),valid_until_utc:"2026-10-24T11:00:00Z"});assert.equal(overlay.card(overlay.validate(d,board,H),board.players[0],"rush_att",Date.parse("2026-10-24T12:00:00Z")),"");});
check(()=>{assert.equal(overlay.card(null,board.players[0],"rush_att"),"");const d=doc();assert.match(overlay.card(overlay.validate(d,board,H),board.players[0],"rush_att",Date.parse("2026-10-25T18:00:00Z")),/Frozen provisional forecast/);});
// Actual pinned website propStatus body: no imports, sources or real row values.
const appPath=process.env.WEEKLY_OVERLAY_PINNED_APP || (fs.existsSync(path.join(root,"output/app.js"))?path.join(root,"output/app.js"):"/tmp/weekly-website-source-78965e0/output/app.js");
if(fs.existsSync(appPath))check(()=>{const source=fs.readFileSync(appPath,"utf8"),start=source.indexOf("function propStatus("),end=source.indexOf("\nfunction twoPointScorers",start);assert(start>=0&&end>start);const fn=source.slice(start,end),modern=fn.includes("finalOutcomes"),context={S:{games:{g:{state:"post"}},finalOutcomes:new Map([["id",{status:"resolved",final_confirmed:true,actual:3}]])},finalIdentity:()=>"id",finalIdentityMatches:()=>true,current:()=>({stats:{rush_att:3}}),statValue:()=>3};vm.createContext(context);vm.runInContext(fn+"\nthis.status=propStatus({game_id:'g'},'rush_att',3,'over');",context);assert.equal(context.status.res,"push");});
(async()=>{const before=JSON.stringify(board);assert.equal(await overlay.load(board,H,async()=>new Response("bad",{status:404})),null);assert.equal(JSON.stringify(board),before);checks++;
const body=JSON.stringify(doc()),hash=require("node:crypto").createHash("sha256").update(body).digest("hex"),pointer={schema_version:"weekly-adaptive-overlay-pointer-v1",path:`data/weekly-adaptive/${hash}.json`,sha256:hash,bytes:Buffer.byteLength(body),display_board_sha256:H};
const mock=async url=>new Response(url.endsWith("weekly-adaptive-overlay.json")?JSON.stringify(pointer):body,{status:200});assert(await overlay.load(board,H,mock));checks++;
assert.equal(await overlay.load(board,H,async url=>new Response(url.endsWith("weekly-adaptive-overlay.json")?JSON.stringify(pointer):body+" ",{status:200})),null);checks++;
// Deadline covers the COMPLETE operation even when fetch/reader ignore abort.
let signal;
const stalledFetch=async(_url,options)=>{signal=options.signal;return new Promise(()=>{});};
assert.equal(await overlay.load(board,H,stalledFetch,20),null);assert(signal.aborted);checks++;
let cancelled=0,bodySignal;
const stalledBody=async(_url,options)=>{bodySignal=options.signal;return {ok:true,headers:new Headers(),body:{getReader:()=>({read:()=>new Promise(()=>{}),cancel:()=>{cancelled++;return new Promise(()=>{});},releaseLock:()=>{}})}};};
assert.equal(await overlay.load(board,H,stalledBody,20),null);assert(bodySignal.aborted);assert(cancelled>0);checks++;
// One shared deadline is NOT restarted for pointer, payload or legacy board.
const totalSignals=[];
assert.equal(await overlay.load(board,H,async(url,options)=>{totalSignals.push(options.signal);return totalSignals.length===1?mock(url):new Promise(()=>{});},20),null);
assert.equal(totalSignals.length,2);assert.equal(totalSignals[0],totalSignals[1]);assert(totalSignals[1].aborted);checks++;
// A fetch resolving after the deadline has its unread body cancelled.
let releaseFetch,lateCancelled=0;
assert.equal(await overlay.load(board,H,()=>new Promise(r=>{releaseFetch=r;}),20),null);
releaseFetch({body:{cancel:()=>{lateCancelled++;}}});await new Promise(r=>setImmediate(r));assert.equal(lateCancelled,1);checks++;
const appSource=fs.readFileSync(appPath,"utf8");
if(appSource.includes("function startWeeklyOverlay()")){
  const bridge=appSource.slice(appSource.indexOf("async function loadWeeklyOverlayBound("),appSource.indexOf("async function load() {"));
  const startup=appSource.slice(appSource.indexOf("(async function start() {"));
  const api={bound:overlay.bound,validate:overlay.validate};
  async function boot(loadedAPI,fetcher=mock,budget=200){
    const order=[],listeners={},state={sc:{mode:"sleeper"},tab:"props",games:{}};
    const context={S:state,WeeklyAdaptiveOverlay:loadedAPI,console,Promise,performance:require("node:perf_hooks").performance,setTimeout,clearTimeout,fetch:fetcher,
      location:{hash:""},WORKER_URL:"",META_MS:1000,
      addEventListener:(name,fn)=>{listeners[name]=fn;},store:()=>null,
      load:async()=>{state.data=board;state.weeklyOverlay=null;state.weeklyOverlayReady=false;state.weeklyOverlayBoardHash=H;},
      takeYahooTokens:()=>{},applyHash:()=>{},currentLeague:()=>true,$:()=>({textContent:""}),scoringName:()=>"fictional",setTopHeight:()=>{},
      startSelectedRankings:()=>{},render:()=>order.push("R0"),renderProps:()=>order.push("enhance"),renderGame:()=>order.push("game"),syncHash:()=>{},liveTick:()=>{},setInterval:()=>{}};
    vm.createContext(context);vm.runInContext(bridge,context);
    let enhancement;const actualBound=context.loadWeeklyOverlayBound;context.loadWeeklyOverlayBound=(b,h,a)=>(enhancement=actualBound(b,h,a,budget));
    await vm.runInContext(startup,context);
    assert.equal(order[0],"R0");return {context,state,order,listeners,settle:()=>enhancement};
  }
  const drain=async run=>{await Promise.resolve();await run.settle();await new Promise(r=>setImmediate(r));};
  const absent=await boot(undefined);assert.deepEqual(absent.order,["R0"]);checks++;
  const blocked=await boot(api,stalledFetch,20);assert.deepEqual(blocked.order,["R0"]);checks++;
  await new Promise(r=>setTimeout(r,30));assert.equal(blocked.state.weeklyOverlay,null);
  absent.context.WeeklyAdaptiveOverlay=api;absent.listeners["weekly-adaptive-overlay-ready"]();
  await drain(absent);assert.deepEqual(absent.order,["R0","enhance"]);checks++;
  const ready=await boot(api);await drain(ready);assert.deepEqual(ready.order,["R0","enhance"]);checks++;
  assert.equal(ready.state.weeklyOverlay.assetHash,hash);checks++;
  for(const fetcher of [stalledFetch,stalledBody]){
    const live=await boot(api,fetcher,20);assert.deepEqual(live.order,["R0"]);
    await new Promise(r=>setTimeout(r,30));assert.deepEqual(live.order,["R0"]);assert.equal(live.state.weeklyOverlay,null);checks++;
  }
  let resolveOld;const stale=await boot(api,url=>url.endsWith("weekly-adaptive-overlay.json")?new Promise(r=>{resolveOld=r;}):mock(url));
  stale.state.data={...board,week:9};resolveOld(new Response(JSON.stringify(pointer)));await drain(stale);
  assert.deepEqual(stale.order,["R0"]);assert.equal(stale.state.weeklyOverlay,null);checks++;
  let calls=0;const once=await boot(api,url=>{calls++;return mock(url);});
  once.listeners["weekly-adaptive-overlay-ready"]();once.listeners["weekly-adaptive-overlay-ready"]();
  await drain(once);assert.equal(calls,2);checks++;
}

console.log(JSON.stringify({checks,state:"PASS",scope:"fictional bounded-loader/overlay; explicit saved-final push semantics; no HTTP/provider/data"}));})().catch(e=>{console.error(e);process.exitCode=1;});
