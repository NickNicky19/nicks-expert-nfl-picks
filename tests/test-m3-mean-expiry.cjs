"use strict";
// Actual numerical helper/app functions with fictional records, a controlled
// clock and mocked transport. This is not a current NFL feed or admission.
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),{execFileSync}=require("node:child_process"),{createHash}=require("node:crypto");
const root=path.resolve(__dirname,".."), app=fs.readFileSync(path.join(root,"output/app.js"),"utf8");
const wire=require("../output/stat-point-mae-v2.js");
const feed=JSON.parse(execFileSync(process.env.PYTHON||"python3",["-B","-c","import runpy,json; x=runpy.run_path('tests/test_m3_mean_expiry.py'); print(json.dumps(x['fixture']()))"],{cwd:root,timeout:10000}));
const copy=x=>JSON.parse(JSON.stringify(x)),sha=x=>createHash("sha256").update(JSON.stringify(x)).digest("hex");
const row=feed.rows[0], expiry=row.expires_at, at=Date.parse("2099-10-31T01:20:00Z");let now=at,checks=0;
class Clock extends Date{static now(){return now;}}
const eq=(a,b,m)=>{assert.deepEqual(a,b,m);checks++;};
const p={id:row.sleeper_id,gsis_id:row.player_id,game_id:row.website_game_id,team:row.team,opp:row.opponent,pos:row.position};
const board={season:row.season,week:row.week,players:[p],games:[{id:p.game_id,home:p.team,away:p.opp,kickoff:row.kickoff_utc}],categories:{rec:{label:"Receptions"}}};
const admitted=wire.validate(feed), original=JSON.stringify(feed);
const legacyC=copy(feed);legacyC.schema_version="stat-point-mae-public-feed-v2-draft2";legacyC.catalog.schema_version="stat-point-mae-public-catalog-v2-draft2";legacyC.source_registry.schema_version="stat-point-mae-source-registry-v2-draft2";
for(const e of legacyC.catalog.entries){delete e.conditional_on;delete e.conditioning_contract_sha256;}
for(const s of legacyC.source_registry.records){delete s.conditional_on;delete s.conditioning_contract_sha256;delete s.expires_at;}
for(const r of legacyC.rows){delete r.conditioning_contract_sha256;delete r.expires_at;r.conditional_on="played";r.schema_version=r.consumer_contract_version="stat-point-mae-v2";}
assert.throws(()=>wire.validate(legacyC),/APPEARANCE_PRODUCT_REQUIRES_EXPIRING_WIRE/);checks++;
eq(wire.matchesPlayer(admitted,p,"rec",board),true,"actual identity bridge admitted");
eq(wire.forPlayer(admitted,p,"rec",board,at).value,3,"actual mean, no median substitution");
eq(wire.forPlayer(admitted,p,"rec",board,at).label,"Appearance-conditioned mean","truthful narrow target label");
eq(wire.forPlayer(admitted,p,"rec",board,"2099-10-31T01:30:00.000000Z").value,3,"microsecond before expiry remains valid");
eq(wire.nextExpiryDelay(admitted,"2099-10-31T01:30:00.000000Z"),1,"microsecond delay rounded safely");
for(const stamp of [expiry,"2099-10-31T02:00:00Z",row.kickoff_utc])eq(wire.forPlayer(admitted,p,"rec",board,stamp),null,"no current use at/after producer expiry");
eq(wire.matchesPlayer(admitted,p,"rec",board),true,"expiry is not an identity failure");
const retained=copy(feed);retained.rows[0].retained_capture=true;retained.created_at="2099-10-31T04:00:00Z";
eq(wire.forPlayer(wire.validate(retained),p,"rec",board,retained.created_at),null,"retention cannot revive expiry");
eq(wire.forPlayer(admitted,{...p,team:"WRONG"},"rec",board,at),null,"wrong team falls back");
eq(wire.forPlayer(admitted,{...p,pos:"RB"},"rec",board,at),null,"unsupported role falls back");
eq(wire.forPlayer(admitted,{...p,id:"missing"},"rec",board,at),null,"missing point falls back");
let fired=null,cleared=0,renders=0;
const S={data:board,byId:{[p.id]:p},games:{[p.game_id]:board.games[0]},maeDisplay:admitted,maeBodyHash:sha(feed),maeRequestBoard:null,maeTargets:new Set(["rec"]),maeExpiryTimer:null,weeklyOverlayReady:true,mine:[],tab:"props",gameView:null};
const ctx={S,Date:Clock,StatPointMaeV2:wire,setTimeout:(fn,delay)=>{fired={fn,delay};return 7;},clearTimeout:()=>{cleared++;},renderProps:()=>{renders++;},renderGame:()=>{renders++;},persistMine:()=>{},updateMineBadge:()=>{},propPickBound:()=>true,
  esc:String,fetch:()=>{throw Error("unexpected network");}};
vm.createContext(ctx);
const names=["scheduleMaeDisplayExpiry","refreshMaeDisplayExpiry","maeDisplayForecast","maeDisplayDetails","minePick","toggleMine","startMaeDisplay"];
for(const name of names){const m=app.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));assert(m,name);vm.runInContext(m[0],ctx);}
ctx.scheduleMaeDisplayExpiry();eq(fired.delay,600001,"UI timeout is bound to real producer expiry");
const cached=ctx.maeDisplayForecast(p,"rec");assert(ctx.maeDisplayDetails(cached).includes("Display expires"));checks++;
assert(ctx.maeDisplayDetails(cached).includes("not a participation probability"));checks++;
now=Date.parse("2099-10-31T01:30:00.001Z");fired.fn();eq(renders,1,"already painted point is refreshed at expiry");eq(S.maeExpiryTimer,null,"expired point cannot spin timer");
eq(ctx.maeDisplayForecast(p,"rec"),null,"post-expiry render uses identified incumbent fallback");
ctx.toggleMine(p.id,"rec","over",2,cached);eq(Object.hasOwn(S.mine[0],"display_forecast_snapshot"),false,"stale rendered object cannot be newly saved");
S.mine=[];now=at;ctx.toggleMine(p.id,"rec","over",2,ctx.maeDisplayForecast(p,"rec"));
const saved=JSON.stringify(S.mine[0]);now=Date.parse("2099-10-31T02:00:00Z");ctx.refreshMaeDisplayExpiry();eq(JSON.stringify(S.mine[0]),saved,"original saved snapshot preserved after expiry");
eq(S.mine[0].display_forecast_snapshot.row.expires_at,expiry,"original expiry travels with saved snapshot");
const pointer={schema_version:"weekly-mae-display-pointer-v2",path:`data/weekly-mae-display/${sha(feed)}.json`,sha256:sha(feed),bytes:Buffer.byteLength(JSON.stringify(feed)),display_board_sha256:sha(board),published_at:feed.created_at};
ctx.WeeklyAdaptiveOverlay={bound:async url=>url.endsWith("weekly-mae-display.json")?{value:pointer}:url.endsWith("week.json")?{value:board,hash:sha(board)}:{value:feed,hash:sha(feed),bytes:pointer.bytes}};
(async()=>{S.maeDisplay=null;S.maeRequestBoard=null;await ctx.startMaeDisplay();eq(S.maeDisplay.rows.length,1,"expired joined row remains retained instead of rejecting entire feed");eq(ctx.maeDisplayForecast(p,"rec"),null,"retained expired row stays unavailable to display");eq(JSON.stringify(feed),original,"all original numerical values/clocks remain unchanged");console.log(JSON.stringify({state:"PASS",checks,scope:"actual helper+app expiry/target/identity/timer/save/loader functions with fictional records; no NFL admission"}));})().catch(e=>{console.error(e);process.exitCode=1;});
