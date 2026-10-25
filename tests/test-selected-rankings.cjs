"use strict";
// Cross-language fictional contracts and actual application functions. No NFL data.
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { execFileSync } = require("node:child_process"), { webcrypto } = require("node:crypto");
const root = path.resolve(__dirname, ".."), source = fs.readFileSync(path.join(root, "output/app.js"), "utf8");
new vm.Script(source);
const extract = name => {
  const found = source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));
  assert(found, "actual function " + name); return found[0];
};
const python = `import sys,json,tempfile,runpy
sys.path.insert(0,'tools')
import weekly_selected_rankings as r
from reliability import atomic_json
t=runpy.run_path('tests/test_weekly_selected_rankings.py')
board,overlay=t['fixture'](); ranking=t['make'](board,overlay)
with tempfile.TemporaryDirectory() as d:
 pointer=r.write_public(ranking,d,atomic_json,clock=lambda:t['PERSIST'])
 frozen=t['make'](board,overlay,now='2031-10-25T18:00:00+00:00',previous=ranking,previous_receipt=pointer)
 frozen_pointer=r.write_public(frozen,d,atomic_json,clock=lambda:'2031-10-25T18:00:01+00:00')
 print(json.dumps(dict(board=board,overlay=overlay,ranking=ranking,pointer=pointer,frozen=frozen,frozen_pointer=frozen_pointer)))`;
const fixture = JSON.parse(execFileSync(process.env.PYTHON || "python3", ["-c", python], { cwd: root, timeout: 10000 }));
const helper = require("../output/weekly-adaptive-overlay.js");
const names = ["selectedRankingPolicy", "rankingCanonical", "selectedPropForecast", "effectivePropForecast", "selectedPropGap", "selectedPlayerGap", "visibleTopPicks", "compareSelectedRankingItems", "validateSelectedRankings", "startSelectedRankings", "displayedProps", "filteredPlayers", "propStatus"];
const functions = names.map(extract).join("\n");
let checks = 0;
const eq = (a, b, why) => { assert.deepEqual(a, b, why); checks++; };
const clock = Date.parse("2031-10-24T12:00:00Z");
class TestDate extends Date { static now() { return clock; } }
const S = { data: fixture.board, weeklyOverlay: helper.validate(fixture.overlay, fixture.board, fixture.overlay.display_board_sha256),
  selectedRankings: null, lines: {}, games: {"fictional-game": fixture.board.games[0]}, f: { sort: "selected_edge", cat: "rush_yd", q: "", pos: "ALL", game: "", hideOut: false, favs: false },
  favs: new Set(), tab: "props", gameView: null };
const context = { S, WeeklyAdaptiveOverlay: helper, Date: TestDate, crypto: webcrypto, TextEncoder,
  UNAVAILABLE: new Set(), normName: x => x.toLowerCase(), posMatch: () => true, injOf: () => ({status:""}),
  projPts: p => p.proj_ppr, livePPR: () => null, current: () => ({stats:{rush_yd:30.5}}), statValue: (k,s) => s[k],
  fetch: () => { throw Error("unexpected network request"); }, renderProps: () => {}, renderGame: () => {} };
vm.createContext(context); vm.runInContext(functions, context);
const clone = value => JSON.parse(JSON.stringify(value));
(async () => {
  eq(context.compareSelectedRankingItems({score:1,game_id:'g',player_id:'1',key:'rec'},{score:1,game_id:'g',player_id:'10',key:'rec'}),-1,'prefix IDs follow Python tuple order');
  eq((await context.validateSelectedRankings(fixture.ranking, fixture.pointer, S.data, S.weeklyOverlay)).policy.version, "selected-projection-gap-v1", "Python-produced contract accepted by actual JS");
  await context.validateSelectedRankings(fixture.frozen, fixture.frozen_pointer, S.data, S.weeklyOverlay); checks++;
  S.selectedRankings = fixture.ranking;
  eq(context.visibleTopPicks("over")[0].player_id, "fictional-a", "selected Top differs from reference");
  eq(Array.from(context.filteredPlayers(), p => p.id), ["fictional-a", "fictional-b"], "new normalized gap sorting");
  S.f.sort = "edge";
  eq(Array.from(context.filteredPlayers(), p => p.id), ["fictional-b", "fictional-a"], "explicit legacy sort retained");
  S.f.sort = "selected_value";
  eq(Array.from(context.filteredPlayers(), p => p.id), ["fictional-a", "fictional-b"], "new value sort uses selected forecasts");
  const p = S.data.players[0], prop = p.props[0];
  eq(context.selectedPropGap(p, prop).lean, "over", "selected forecast reverses old under");
  S.lines[p.id + "|rush_yd"] = 80;
  eq(context.selectedPropGap(p, prop, true).lean, "under", "personal-line lean");
  eq(context.visibleTopPicks("over")[0].line, 30.5, "personal line does not rewrite saved Top");
  eq(context.selectedPropGap(p, prop).lean, "over", "official gap ignores custom line");
  S.games["fictional-game"].state = "post";
  eq(context.propStatus(p, "rush_yd", 30.5, "over").res, "push", "integer-line over push");
  eq(context.propStatus(p, "rush_yd", 30.5, "under").res, "push", "integer-line under push");
  S.games["fictional-game"].state = "in";
  eq(context.propStatus(p, "rush_yd", 20, "over").res, "live", "signed yardage not irreversibly cleared live");
  S.games["fictional-game"].state = "pre";
  for (const change of [d => d.picks.over[0].score += 1, d => d.picks.over[0].line += 1,
    d => d.picks.over[0].model_version = "f".repeat(64), d => d.picks.over[0].selected_row_sha256 = "f".repeat(64),
    d => d.picks.over[0].selected_row_canonical = '{}', d => d.extra_public_field='not allowed',
    d => d.prepared_at='invalid', d => d.picks.over[0].extra_public_field='not allowed',
    d => d.fallback_counts.unavailable_forecast=-1,
    d => d.frozen_proofs.push({key:['other','other','rush_yd','over'],receipt_sha256:'a'.repeat(64),persisted_at:'2031-10-24T12:00:00Z'})]) {
    const bad = clone(fixture.ranking); change(bad);
    await assert.rejects(() => context.validateSelectedRankings(bad, fixture.pointer, S.data, S.weeklyOverlay)); checks++;
  }
  const late = {...fixture.pointer,published_at:"2031-10-25T18:00:00Z"};
  await assert.rejects(() => context.validateSelectedRankings(fixture.ranking, late, S.data, S.weeklyOverlay)); checks++;
  const before = JSON.stringify(fixture.board), key = JSON.stringify([p.game_id,p.id,"rush_yd"]), original = S.weeklyOverlay.rows.get(key);
  S.weeklyOverlay.rows.set(key, {...original,valid_until_utc:"2031-10-24T11:59:59Z"});
  eq(context.visibleTopPicks("over").length, 0, "expired selection omitted without unrecorded replacement");
  S.weeklyOverlay.rows.set(key, original);
  S.weeklyOverlay.rows.set(key, {...original,forecast_value:0});
  eq(context.selectedPropForecast(p,'rush_yd').value,0,'valid zero preserved');
  S.weeklyOverlay.rows.set(key, {...original,forecast_value:-5.25});
  eq(context.selectedPropForecast(p,'rush_yd').value,-5.25,'signed yards preserved');
  S.weeklyOverlay.rows.delete(key);
  eq(Array.from(context.filteredPlayers(), x=>x.id),['fictional-b','fictional-a'],'missing selected values sort last');
  S.weeklyOverlay.rows.set(key, original);
  const originalData=S.data,originalOverlay=S.weeklyOverlay;
  const tdBoard=clone(S.data),tdDoc=clone(fixture.overlay);
  tdBoard.players.forEach((p,i)=>{p.props.push({key:'anytime_td',td_chance:.4,line:.5,values:[]});tdDoc.rows.push({...tdDoc.rows[i],category:'anytime_td',product:'binary_probability',prediction_functional:'event_probability',forecast_value:i===0?.1:.9});});
  S.data=tdBoard;S.weeklyOverlay=helper.validate(tdDoc,tdBoard,tdDoc.display_board_sha256);S.f.cat='anytime_td';
  eq(Array.from(context.filteredPlayers(), x=>x.id),['fictional-b','fictional-a'],'TD sort uses true event probabilities');
  S.data=originalData;S.weeklyOverlay=originalOverlay;S.f.cat='rush_yd';
  const fakeAPI = {bound: async url => url.endsWith('weekly-selected-rankings.json') ? {value:fixture.pointer} : {value:fixture.ranking,hash:fixture.pointer.sha256,bytes:fixture.pointer.bytes}};
  const savedValidator = context.validateSelectedRankings;
  context.validateSelectedRankings = async () => { S.data = {...fixture.board}; return fixture.ranking; };
  S.selectedRankings = null;
  await context.startSelectedRankings(fixture.board, S.weeklyOverlay, fakeAPI);
  eq(S.selectedRankings, null, "async board change cannot install stale ranks");
  context.validateSelectedRankings = savedValidator; S.data = fixture.board;
  await context.startSelectedRankings(S.data, S.weeklyOverlay, fakeAPI);
  eq(S.selectedRankings.policy.version, "selected-projection-gap-v1", "real bounded-reader seam installs matched snapshot");
  eq(JSON.stringify(fixture.board), before, "canonical board unchanged");
  eq(source.includes('value="selected_edge"'), true, "new gap sort option");
  eq(source.includes('value="selected_value"'), true, "new category value/probability option");
  eq(source.includes('Live prop values remain provisional, including overs already above the line'), true, 'My Picks caption matches provisional grading');
  eq(source.includes('Overs show cleared as soon as they pass the line'), false, 'obsolete early-finality caption removed');
  if (process.env.SELECTED_RANKINGS_BROWSER === '1') {
    const {chromium}=require('playwright');
    const browser=await chromium.launch({executablePath:process.env.NFL_CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
    let requests=0;
    try {
      for(const width of [320,390,1280]) {
        const ctx=await browser.newContext({viewport:{width,height:900}});
        await ctx.route('**/*',route=>{requests++;return route.abort();});
        const page=await ctx.newPage();await page.setContent('<main id="main"></main>');
        await page.addStyleTag({content:fs.readFileSync(path.join(root,'output/style.css'),'utf8')});
        await page.addScriptTag({content:fs.readFileSync(path.join(root,'output/weekly-adaptive-overlay.js'),'utf8')});
        const renderNames=[...names.filter(n=>n!=='propStatus'),'pickCard','propChip','catCard','renderProps'];
        await page.addScriptTag({content:`
const fixture=${JSON.stringify(fixture)};Date.now=()=>${clock};
const S={data:fixture.board,weeklyOverlay:WeeklyAdaptiveOverlay.validate(fixture.overlay,fixture.board,fixture.overlay.display_board_sha256),selectedRankings:fixture.ranking,
lines:{},liveLines:{},games:Object.fromEntries(fixture.board.games.map(g=>[g.id,g])),byId:Object.fromEntries(fixture.board.players.map(p=>[p.id,p])),tab:'props',gameView:null,
f:{sort:'selected_edge',cat:'rush_yd',q:'',pos:'ALL',game:'',hideOut:false,favs:false},favs:new Set(),shown:40};
const $=s=>document.querySelector(s),esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(v,n=1)=>Number(v).toFixed(n),fmtPts=v=>fmt(v),fmtStat=(k,v)=>fmt(v),pv=(p,x)=>x,propStatus=()=>null,minePick=()=>false,scoringName=()=>'PPR',remaining=()=>1;
const LINE_FROM={dk:'DraftKings',sleeper:'Sleeper Picks',ours:'Our estimate'},LINE_TAG={dk:'DK',sleeper:'SLP',ours:'est'},SHORT={rush_yd:'Rush Yds'},UNAVAILABLE=new Set();
const normName=x=>x.toLowerCase(),posMatch=()=>true,injOf=()=>({status:''}),projPts=p=>p.proj_ppr,livePPR=()=>null,store=()=>true,withFlex=x=>x;
const avatar=()=>'',injBadge=()=>'',oppText=()=>'vs BBB',liveLineText=()=>'',progress=()=>'',resBadge=()=>'',gameStatus=()=>'Upcoming';
const playerCard=p=>'<div class="props-row">'+displayedProps(p).map(x=>propChip(p,x)).join('')+'</div>'+displayedProps(p).map(x=>catCard(p,x)).join('');
${renderNames.map(extract).join('\n')}
renderProps();`});
        const result=await page.evaluate(()=>({text:document.querySelector('#main').textContent,options:[...document.querySelector('#f-sort').options].map(x=>x.value),
          lean:document.querySelector('[data-cat="fictional-a|rush_yd"] .lean').textContent,
          overflow:document.documentElement.scrollWidth>innerWidth}));
        eq(result.text.includes('Selected forecasts · provisional'),true,'new Top source at '+width);
        eq(result.text.includes('Selected median 50.0'),true,'Top card uses actual selected forecast at '+width);
        eq(result.lean,'Selected: Lean over','expanded lean uses new direction at '+width);
        eq(result.options.includes('selected_value'),true,'new sort visible at '+width);
        eq(result.overflow,false,'no horizontal overflow at '+width);
        await ctx.close();
      }
      eq(requests,0,'fictional browser performs no HTTP');
    } finally {await browser.close();}
  }
  console.log(JSON.stringify({state:"PASS",checks,scope:"fictional Python/JS contracts and actual app functions",HTTP:0}));
})().catch(error => { console.error(error); process.exitCode=1; });
