"use strict";
// Real app/wire functions with wholly fictional records and explicit transport
// mocks. This file does not qualify a producer, model or hosted capture.
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const {execFileSync} = require("node:child_process"), {createHash} = require("node:crypto");
const root = path.resolve(__dirname, ".."), app = fs.readFileSync(path.join(root,"output/app.js"),"utf8");
const wire = require("../output/stat-point-mae-v2.js"), legacy = require("../output/weekly-adaptive-overlay.js");
const fixture = JSON.parse(execFileSync(process.env.PYTHON || "python3", ["-B","-c", "import runpy,json; x=runpy.run_path('tests/test_weekly_mae_display_v2.py'); print(json.dumps(x['fixture']()))"], {cwd:root,timeout:10000}));
const copy = x => JSON.parse(JSON.stringify(x)), sha = x => createHash("sha256").update(JSON.stringify(x)).digest("hex");
const extract = name => { const found=app.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`)); assert(found,name); return found[0]; };
let checks=0;
const eq=(a,b,why)=>{assert.deepEqual(a,b,why);checks++;};
const now=Date.parse("2099-10-31T01:20:00Z");
class Clock extends Date { static now(){return now;} }
const row=fixture.rows[0], row2={...row,player_id:"fictional-second-canonical",sleeper_id:"102",identity_binding_sha256:"c".repeat(64),selected_projection:6,expected_mean:7.2};
fixture.rows.push(row2);
const props = [{key:row.target,line:3,adj:5,proj:5,lean:"over",line_from:"dk",values:[],over:1,n:2}];
const players=[row,row2].map(r=>({id:r.sleeper_id,gsis_id:r.player_id,espn_id:r.sleeper_id,game_id:r.website_game_id,name:"Fictional "+r.sleeper_id,team:r.team,opp:r.opponent,pos:r.position,proj_ppr:12,props:copy(props)}));
const board={season:row.season,week:row.week,games:[{id:row.website_game_id,kickoff:row.kickoff_utc,home:row.team,away:row.opponent,state:"pre"}],players,categories:{[row.target]:{label:"Carries",lean:.8}},picks:{over:[{player_id:players[0].id,adj:4.25,line:3,game_id:row.website_game_id,key:row.target}],under:[]}};
const hash="a".repeat(64), selectedRows=players.map((p,i)=>({player_id:p.id,game_id:p.game_id,category:row.target,method_id:"FICTIONAL_INCUMBENT",model_version:hash,procedure_version:hash,product:"point_mean",prediction_functional:"expected_mean",forecast_value:i?3.75:4.25,horizon:"player_game",source_cutoff_utc:row.issue_deadline_utc,issued_at:row.issued_at,persistence_completed_at:row.persistence_completed_at,kickoff_utc:row.kickoff_utc,valid_until_utc:row.kickoff_utc,selection_sha256:hash,source_policy_sha256:hash,query_source_sha256:hash,first_prepared_at:row.readback_completed_at}));
const overlay=legacy.validate({schema_version:"weekly-adaptive-public-overlay-v1",registration_id:"weekly-adaptive-release-v1",state:"PROVISIONAL",season:board.season,week:board.week,canonical_board_sha256:hash,display_board_sha256:hash,board_contract_sha256:hash,prepared_at:row.readback_completed_at,packaged_at:row.readback_completed_at,website_source_sha:"b".repeat(40),publication_review_sha256:hash,rows:selectedRows,frozen_rows:[],fallback_counts:{}},board,hash);
const storage=new Map(), originalRecord=' { "pid":"preserved-unknown", "old_field" : "keep bytes" } ';
storage.set("nflprops.mine","["+originalRecord+"]");
const S={data:board,byId:Object.fromEntries(players.map(p=>[p.id,p])),weeklyOverlay:overlay,weeklyOverlayReady:true,selectedRankings:null,lines:{},games:Object.fromEntries(board.games.map(g=>[g.id,g])),liveLines:{},f:{sort:"selected_edge",cat:row.target,q:"",pos:"ALL",game:"",hideOut:false,favs:false},favs:new Set(),tab:"props",gameView:null,mine:JSON.parse(storage.get("nflprops.mine")),maeDisplay:null,maeTargets:new Set(),maeBodyHash:null,maeRequestBoard:null};
const ctx={S,Date:Clock,StatPointMaeV2:wire,WeeklyAdaptiveOverlay:legacy,TextEncoder,TextDecoder,
  UNAVAILABLE:new Set(),SHORT:{[row.target]:"Carries"},LINE_FROM:{dk:"DraftKings"},LINE_TAG:{dk:"DK"},
  esc:x=>String(x).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])),
  pv:(p,prop)=>prop,propStatus:()=>null,scoringName:()=>"PPR",remaining:()=>.5,
  fmt:(x,d=1)=>Number(x).toFixed(d),fmtPts:x=>Number(x).toFixed(1),fmtStat:(k,x)=>String(x),
  normName:x=>x.toLowerCase(),posMatch:()=>true,injOf:()=>({status:""}),projPts:p=>p.proj_ppr,livePPR:()=>null,
  localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},updateMineBadge:()=>{},
  fetch:()=>{throw Error("unexpected external request");},renderProps:()=>{},renderGame:()=>{}};
vm.createContext(ctx);
vm.runInContext(["selectedRankingPolicy","selectedPropForecast","effectivePropForecast","selectedPropGap","selectedPlayerGap","visibleTopPicks","filteredPlayers","maeDisplayForecast","maeDisplayDetails","propChip","catCard","propPickBound","minePick","persistMine","toggleMine","startMaeDisplay"].map(extract).join("\n"),ctx);
(async()=>{
  const before=JSON.stringify(board), picks=JSON.stringify(ctx.visibleTopPicks("over")), gap=JSON.stringify(ctx.selectedPropGap(players[0],props[0]));
  const legacyCard=ctx.catCard(players[0],props[0]), legacyChip=ctx.propChip(players[0],props[0]);
  S.maeDisplay=wire.validate(fixture);S.maeTargets=new Set([row.target]);S.maeBodyHash=sha(fixture);
  eq(ctx.maeDisplayForecast(players[0],row.target).value,2,"actual typed median");
  eq(ctx.maeDisplayForecast(players[0],row.target).expectedMean,3,"fractional/full-law mean remains separate");
  eq(JSON.stringify(ctx.selectedPropGap(players[0],props[0])),gap,"point adoption cannot change selection gap");
  eq(JSON.stringify(ctx.visibleTopPicks("over")),picks,"saved Top selections remain unchanged");
  eq(ctx.selectedPropForecast(players[0],row.target).value,4.25,"incumbent selection forecast remains separate");
  const card=ctx.catCard(players[0],props[0]),chip=ctx.propChip(players[0],props[0]);
  for(const text of ["2.00","Same-model expected mean","3.00","Ranking forecast:","Selection/ranking forecast","4.25","Information cutoff","Persisted","Registered deadline","not an independently selected lowest-MSE model"]){assert(card.includes(text),text);checks++;}
  assert(chip.includes("2.00")&&chip.includes("ranking lean"));checks++;
  S.f.sort="selected_value";eq(Array.from(ctx.filteredPlayers(),p=>p.id),["102","101"],"only display-value sorting uses new points");
  S.f.sort="selected_edge";eq(Array.from(ctx.filteredPlayers(),p=>p.id),["101","102"],"existing normalized-gap order unchanged");
  const changed={...players[0],team:"OTHER"};eq(ctx.maeDisplayForecast(changed,row.target),null,"wrong current team falls back");
  const game=board.games[0];board.games=[{...game,kickoff:"2099-10-31T04:00:00Z"}];eq(ctx.maeDisplayForecast(players[0],row.target),null,"rescheduled same ID does not inherit forecast");board.games=[game];
  const point=ctx.maeDisplayForecast(players[0],row.target);
  ctx.toggleMine(players[0].id,row.target,"over",3,point);
  eq(S.mine[1].display_forecast_snapshot.row.selected_projection,2,"new player-detail save retains displayed point");
  eq(S.mine[1].display_forecast_snapshot.meaning,"DISPLAY_ONLY_NOT_SELECTION_OR_PROBABILITY_POLICY","no silent selection attribution");
  assert(storage.get("nflprops.mine").includes(originalRecord));checks++;
  ctx.toggleMine(players[0].id,row.target,"over",3);ctx.toggleMine(players[0].id,row.target,"over",3);
  eq(Object.hasOwn(S.mine[1],"display_forecast_snapshot"),false,"Top/legacy save cannot invent an unshown point");
  ctx.toggleMine(players[0].id,row.target,"over",3);eq(storage.get("nflprops.mine"),"["+originalRecord+"]","removal retains original unknown-record bytes exactly");
  eq(JSON.stringify(board),before,"board and reference data unchanged");
  S.maeDisplay=null;S.maeTargets=new Set();eq(ctx.catCard(players[0],props[0]),legacyCard,"no optional feed preserves card byte-for-byte");eq(ctx.propChip(players[0],props[0]),legacyChip,"no optional feed preserves chip byte-for-byte");
  const pointer={schema_version:"weekly-mae-display-pointer-v2",path:`data/weekly-mae-display/${sha(fixture)}.json`,sha256:sha(fixture),bytes:Buffer.byteLength(JSON.stringify(fixture)),display_board_sha256:sha(board),published_at:"2099-10-31T01:19:00Z"};
  const transport={...legacy,bound:async url=>url.endsWith("weekly-mae-display.json")?{value:pointer}:url.endsWith("week.json")?{value:board,hash:sha(board)}:{value:fixture,hash:sha(fixture),bytes:pointer.bytes}};
  ctx.WeeklyAdaptiveOverlay=transport;S.maeRequestBoard=null;await ctx.startMaeDisplay();eq(S.maeDisplay.rows.length,2,"actual async loader installs coherent typed feed");
  S.maeDisplay=null;S.maeRequestBoard=null;const realBound=transport.bound;transport.bound=async url=>{const result=await realBound(url);if(url===pointer.path)S.data={...board};return result;};
  await ctx.startMaeDisplay();eq(S.maeDisplay,null,"board race cannot advance new point display");S.data=board;
  S.maeRequestBoard=null;transport.bound=async url=>{const result=await realBound(url);return url===pointer.path?{...result,hash:"f".repeat(64)}:result;};await ctx.startMaeDisplay();eq(S.maeDisplay,null,"corrupt body falls back without changing incumbent");
  eq(JSON.stringify(ctx.selectedPropGap(players[0],props[0])),gap,"failed new feed leaves selection intact");
  console.log(JSON.stringify({state:"PASS",checks,scope:"actual app+wire functions, fictional records, explicit transport/localStorage mocks; no native admission or actual provider requests"}));
})().catch(e=>{console.error(e);process.exitCode=1;});
