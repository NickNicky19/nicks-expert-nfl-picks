"use strict";
// Actual render functions, fictional inputs, browser DOM; no external requests.
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { chromium } = require("playwright");
const root = path.resolve(__dirname, ".."), source = fs.readFileSync(path.join(root, "output/app.js"), "utf8");
new vm.Script(source); // Parse the complete changed application without booting it.
const extract = name => { const match = source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`)); assert(match, name); return match[0]; };
const functions = ["selectedRankingPolicy", "effectivePropForecast", "selectedPropGap", "selectedPlayerGap", "visibleTopPicks", "selectedPropForecast", "propChip", "catCard", "displayedProps", "filteredPlayers", "renderProps", "tdChanceText"].map(extract).join("\n");
const helper = fs.readFileSync(path.join(root, "output/weekly-adaptive-overlay.js"), "utf8");
const css = fs.readFileSync(path.join(root, "output/style.css"), "utf8");
const widths = process.env.WEEKLY_PRIMARY_CUSTOM_LINE_ONLY === "1" ? [390] : [320, 390, 1280];
let checks = 0, networkRequests = 0;
const check = (a, b, message) => { assert.deepEqual(a, b, message); checks++; };
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.NFL_CHROMIUM_PATH || "/usr/bin/chromium", headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage"] });
  try {
    for (const width of widths) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      await context.route("**/*", route => { networkRequests++; return route.abort(); });
      const page = await context.newPage(), errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.setContent('<main id="main"></main>');
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: helper });
      await page.addScriptTag({ content: `
const TEST_NOW = Date.parse("2031-10-24T12:00:00Z"), TEST_KICKOFF = "2031-10-25T17:00:00Z", TEST_HASH = "a".repeat(64);
Date.now = () => TEST_NOW;
const esc = value => String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (v, digits=1) => Number(v).toFixed(digits), fmtPts = v => Number(v).toFixed(1), fmtStat = (k,v) => fmt(v);
const pv = (p, raw) => raw, propStatus = () => null, minePick = () => false, scoringName = () => "PPR", remaining = () => .5;
const LINE_FROM = { dk:"DraftKings", sleeper:"Sleeper Picks", ours:"Our estimate" }, LINE_TAG = { dk:"DK", sleeper:"SLP", ours:"est" };
const SHORT = { rush_att:"Carries", rush_yd:"Rush yds", anytime_td:"TD", fpts:"PPR" }, UNAVAILABLE = new Set();
const normName = v => v.toLowerCase(), posMatch = () => true, injOf = () => ({status:""}), projPts = p => p.proj_ppr, livePPR = () => null;
const store = () => true, withFlex = v => v, $ = selector => document.querySelector(selector), pickCard = pick => '<div data-r0-pick>'+pick.line+'</div>';
const props = [
 {key:"rush_att",line:4,adj:2.5,proj:2,lean:"under",line_from:"dk",values:[]},
 {key:"rush_yd",line:10,adj:8,proj:7,lean:null,line_from:"ours",values:[]},
 {key:"anytime_td",line:.5,adj:null,proj:.4,td_chance:.55,lean:"over",line_from:"dk",values:[]},
 {key:"fpts",line:9,adj:8,proj:7,lean:null,line_from:"ours",values:[]}];
function deepFreeze(value) { if (value && typeof value === "object") { Object.freeze(value); Object.values(value).forEach(deepFreeze); } return value; }
const board = deepFreeze({season:2031,week:7,games:[{id:"fictional-game",kickoff:TEST_KICKOFF,state:"pre",home:"AAA",away:"BBB"}],
 players:[{id:"fictional-player",game_id:"fictional-game",name:"Fictional",team:"AAA",opp:"BBB",pos:"RB",proj_ppr:8,props}],
 categories:Object.fromEntries(props.map(p => [p.key,{label:SHORT[p.key],lean:1}])),picks:{over:[{line:4,game_id:"fictional-game"}],under:[]}});
const S = {data:board,weeklyOverlay:null,lines:{},liveLines:{},games:{"fictional-game":board.games[0]},tab:"props",gameView:null,
 f:{sort:"edge",cat:"",q:"",pos:"ALL",game:"",hideOut:false,favs:false},favs:new Set(),shown:40};
const playerCard = p => '<div class="props-row">'+displayedProps(p).map(x=>propChip(p,x)).join("")+'</div>'+displayedProps(p).map(x=>catCard(p,x)).join("");
function candidate(category,value,product,functional,expiry=TEST_KICKOFF) {
 return {player_id:"fictional-player",game_id:"fictional-game",category,method_id:"FICTIONAL",model_version:TEST_HASH,procedure_version:TEST_HASH,
 product,prediction_functional:functional,forecast_value:value,horizon:"player_game",source_cutoff_utc:"2031-10-24T11:00:00Z",
 issued_at:"2031-10-24T10:00:00Z",persistence_completed_at:"2031-10-24T10:01:00Z",kickoff_utc:TEST_KICKOFF,valid_until_utc:expiry,
 selection_sha256:TEST_HASH,source_policy_sha256:TEST_HASH,query_source_sha256:TEST_HASH,first_prepared_at:"2031-10-24T10:02:00Z"};
}
function overlayRows(rows) {
 return WeeklyAdaptiveOverlay.validate({schema_version:"weekly-adaptive-public-overlay-v1",registration_id:"weekly-adaptive-release-v1",state:"PROVISIONAL",
 season:2031,week:7,canonical_board_sha256:TEST_HASH,display_board_sha256:TEST_HASH,board_contract_sha256:TEST_HASH,
 prepared_at:"2031-10-24T10:02:00Z",packaged_at:"2031-10-24T10:02:00Z",website_source_sha:"b".repeat(40),publication_review_sha256:TEST_HASH,
 rows,frozen_rows:[],fallback_counts:{}},board,TEST_HASH);
}
window.fixture={S,board,candidate,overlayRows};
${functions}
` });
      const result = await page.evaluate(() => {
        const { S, board, candidate, overlayRows } = fixture, p = board.players[0], before = JSON.stringify(board);
        const baselineOrder = displayedProps(p).map(x => x.key), baselineRank = filteredPlayers().map(x => x.id);
        const baseCards = p.props.map(x => catCard(p, x)), baseChips = p.props.map(x => propChip(p, x));
        S.weeklyOverlay = overlayRows([candidate("rush_att",3.25,"point_mean","expected_mean"), candidate("rush_yd",-2.5,"point_median","intended_median"), candidate("anytime_td",.35,"binary_probability","event_probability")]);
        renderProps();
        const card = key => document.querySelector('[data-cat="fictional-player|'+key+'"]');
        const selected = Object.fromEntries(p.props.map(x => [x.key, card(x.key).querySelector('[data-weekly-primary]')?.textContent || null]));
        const meansFirst = card("rush_att").querySelector('.cat-nums').firstElementChild.hasAttribute('data-weekly-primary');
        const text = document.querySelector('#main').textContent;
        const snapshots = { selected, meansFirst, selectedGapNoLean:selectedPropGap(p,p.props[0]).lean===null, reference:card("rush_att").textContent.includes("Current reference forecast2.5"),
          negative:card("rush_yd").textContent.includes("-2.50"), referenceTD:card("anytime_td").textContent.includes("Current reference probability55%"),
          primaryTD:card("anytime_td").querySelector('.cat-h').textContent.includes("35.0% provisional TD probability"),
          tdHasNoDirectionalLean:card("anytime_td").querySelector('.lean').className === 'lean none',
          chips:[...document.querySelectorAll('.pchip[data-weekly-primary]')].map(x=>x.textContent),
          pointWarning:card("rush_att").textContent.includes("does not give a bet-win probability"),
          referenceControls:text.includes("historical Record retain their exact recorded reference identities"),
          referenceSort:[...document.querySelector('#f-sort').options].filter(x=>['proj','edge'].includes(x.value)).every(x=>x.textContent.includes('Reference')),
          line:card("rush_att").querySelector('input').value,
          orderUnchanged:JSON.stringify(displayedProps(p).map(x=>x.key))===JSON.stringify(baselineOrder),
          rankUnchanged:JSON.stringify(filteredPlayers().map(x=>x.id))===JSON.stringify(baselineRank),
          noPageOverflow:document.documentElement.scrollWidth<=innerWidth };
        S.lines['fictional-player|rush_att']=6; renderProps();
        snapshots.customLine=document.querySelector('[data-line="fictional-player|rush_att"]').value;
        snapshots.customStillSelected=card('rush_att').querySelector('[data-weekly-primary]').textContent.includes('3.25');
        snapshots.customSelectedUnder=selectedPropGap(p,p.props[0],true).lean==='under';
        const customBookChip=[...document.querySelectorAll('.pchip')].find(x=>x.textContent.startsWith('Carries')).textContent;
        snapshots.customBookLabel=customBookChip.includes('Your line6custom')&&!customBookChip.includes('book line');
        S.lines['fictional-player|rush_yd']=12;renderProps();
        const customR0Chip=[...document.querySelectorAll('.pchip')].find(x=>x.textContent.startsWith('Rush yds')).textContent;
        snapshots.customReferenceLabel=customR0Chip.includes('Your line12custom')&&!customR0Chip.includes('Reference line');
        S.lines={};
        snapshots.frozen=selectedPropForecast(p,'rush_att',Date.parse('2031-10-25T18:00:00Z')).frozen;
        S.weeklyOverlay=overlayRows([candidate('rush_att',3.25,'point_mean','expected_mean','2031-10-24T11:00:00Z')]);
        snapshots.expired=selectedPropForecast(p,'rush_att')===null && catCard(p,p.props[0])===baseCards[0];
        snapshots.expiredCannotBecomeFrozen=selectedPropForecast(p,'rush_att',Date.parse('2031-10-25T18:00:00Z'))===null;
        S.weeklyOverlay=null;
        snapshots.absentSameCards=p.props.every((x,i)=>catCard(p,x)===baseCards[i]);
        snapshots.absentSameChips=p.props.every((x,i)=>propChip(p,x)===baseChips[i]);
        snapshots.fantasyNoSelection=selectedPropForecast(p,'fpts')===null;
        S.weeklyOverlay={rows:new Map([[JSON.stringify([p.game_id,p.id,'rush_att']),{}]])};
        snapshots.malformedFallback=selectedPropForecast(p,'rush_att')===null;
        snapshots.boardUnchanged=JSON.stringify(board)===before;
        return snapshots;
      });
      check(result.selected.rush_att,"Provisional mean forecast3.25","selected count is primary");
      check(result.selected.rush_yd,"Provisional median forecast-2.50","signed median is primary");
      check(result.selected.anytime_td,"Provisional TD probability35.0%","selected TD probability is primary");
      check(result.selected.fpts,null,"exact PPR is unchanged");
      for (const key of ["meansFirst","selectedGapNoLean","customSelectedUnder","reference","negative","referenceTD","primaryTD","tdHasNoDirectionalLean","pointWarning","referenceControls","referenceSort","orderUnchanged","rankUnchanged","noPageOverflow","customStillSelected","customBookLabel","customReferenceLabel","frozen","expired","expiredCannotBecomeFrozen","absentSameCards","absentSameChips","fantasyNoSelection","malformedFallback","boardUnchanged"]) check(result[key],true,key+" at width "+width);
      check(result.line,"4","market line unchanged"); check(result.customLine,"6","personal line unchanged");
      check(result.chips.length,3,"all supported selected chips are primary");
      check(result.chips.every(x=>!x.includes('Reference lean')),true,"selected chips do not inherit reference direction");
      check(result.chips.some(x=>x.includes('35.0%')&&x.includes('provisional TD probability')),true,"chip uses selected TD probability");
      check(errors,[],"browser has no errors");
      await context.close();
    }
    check(networkRequests,0,"no actual network requests");
    console.log(JSON.stringify({state:"PASS",checks,widths,actual_network_requests:networkRequests,scope:"fictional actual render functions/DOM; no NFL/model/provider/publication"}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
