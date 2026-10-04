"use strict";

// Live data comes straight from ESPN in the browser (the hourly build can't keep up with a game in progress).
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl";
const ESPN_TO_SLEEPER = { WSH: "WAS" };
const LIVE_MS = 30000;   // scores and box scores while a game is on
const IDLE_MS = 300000;  // scores when nothing is live
const GAME_MS = 15000;   // play-by-play for the game that's open
const META_MS = 60000;   // checks for a new build
const UNAVAILABLE = new Set(["Out", "IR", "PUP", "Suspended", "NA", "Doubtful", "COV", "DNR"]);
const SHORT = {
  pass_yd: "Pass Yds", pass_td: "Pass TD", pass_cmp: "Comp", pass_att: "Pass Att", pass_int: "INT",
  rush_yd: "Rush Yds", rush_att: "Rush Att", rec: "Rec", rec_yd: "Rec Yds", rush_rec_yd: "Rush+Rec",
  anytime_td: "Anytime TD", fpts: "PPR Pts",
};
const LINE_FROM = { dk: "DraftKings", sleeper: "Sleeper Picks", ours: "Our estimate" };
const LINE_TAG = { dk: "DK", sleeper: "SLP", ours: "est" };
const INJ_SHORT = { Questionable: "Q", Doubtful: "D", Out: "OUT", IR: "IR", PUP: "PUP", Suspended: "SUS", NA: "NA", COV: "COV", DNR: "DNR" };

const S = {
  data: null, track: null, generatedAt: null,
  byId: {}, byKey: {},
  games: {},           // game id -> schedule merged with the latest ESPN scoreboard
  live: {},            // player id -> stat line from ESPN's box score (Sleeper field names)
  boxLoaded: new Set(),
  boxFinal: new Set(),
  liveAt: null,
  tab: "props",
  f: { pos: "ALL", game: "", cat: "", q: "", hideOut: true, favs: false, sort: "proj" },
  ff: { pos: "FLEX", sort: "proj", desc: true, shown: 60 },
  open: new Set(), lines: {}, shown: 40,
  gameView: null,      // game id when a game's page is open
  gsub: "plays",       // that page's section: plays, box or props
  sum: {},             // game id -> latest ESPN summary
  liveLines: {},       // player id -> {key: DraftKings in-game line}
  injNews: {},         // player id -> injury news from ESPN newer than our build
  injAt: {},           // game id -> when its pregame injury news was last checked
  seenPlays: {},       // game id -> play ids already shown
  openDrives: new Set(),
  gs: {},              // game id -> that game page's tab and filters
  favs: new Set(store("favs") || []),
};

// ---------------------------------------------------------------- helpers

function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem("nflprops." + key));
    localStorage.setItem("nflprops." + key, JSON.stringify(value));
  } catch { return null; }
}
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? "-" : (Math.round(v * 10 ** d) / 10 ** d).toFixed(d));
const fmtStat = (key, v) => (v == null ? "-" : key.endsWith("_yd") || key === "fpts" ? fmt(v, key === "fpts" ? 1 : 0) : fmt(v, Number.isInteger(v) ? 0 : 1));
const teamCode = (abbr) => ESPN_TO_SLEEPER[abbr] || abbr;
const photo = (id) => `https://sleepercdn.com/content/nfl/players/thumb/${id}.jpg`;
const logo = (team) => `https://sleepercdn.com/images/team_logos/nfl/${team.toLowerCase()}.png`;

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

function normName(name) {
  return name.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[.'’,]/g, "").replace(/\b(jr|sr|ii|iii|iv|v)\b/g, "").replace(/\s+/g, " ").trim();
}

// Same as ppr_points() in pull/scoring.py (Sleeper's standard PPR)
function ppr(s) {
  let total = 0;
  for (const [k, w] of Object.entries(S.data.scoring)) total += w * (s[k] || 0);
  if (s.idp_fum_rec) total -= S.data.scoring.fum_rec_td * (s.fum_rec_td || 0);
  return Math.round(total * 100) / 100;
}

function statValue(key, s) {
  if (key === "rush_rec_yd") return (s.rush_yd || 0) + (s.rec_yd || 0);
  if (key === "anytime_td") return (s.rush_td || 0) + (s.rec_td || 0);
  if (key === "fpts") return ppr(s);
  return s[key] || 0;
}

function kickoffText(iso) {
  const d = new Date(iso);
  const day = d.toLocaleDateString(undefined, { weekday: "short" });
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${day} ${time}`;
}

function gameStatus(g) {
  if (!g) return "";
  if (g.state === "pre") return kickoffText(g.kickoff);
  return g.detail || (g.state === "post" ? "Final" : "Live");
}

// ---------------------------------------------------------------- live data

// A player's stat line this week: ESPN's live box score first, then Sleeper's (from the last build).
// null before kickoff. {none: true} when the game is final and the player never showed up in the box score.
function current(p) {
  const g = S.games[p.game_id];
  if (!g || g.state === "pre") return null;
  const stats = S.live[p.id] || p.actual?.stats;
  if (stats) return { stats, none: false };
  if (g.state === "post" && S.boxLoaded.has(p.game_id)) return { stats: {}, none: true };
  return { stats: {}, none: false };
}

function livePPR(p) {
  const c = current(p);
  return c && !c.none ? fantasyPts(c.stats, p.pos) : null;
}

// Same as fantasy_points() in pull/scoring.py
function fantasyPts(s, pos) {
  const table = (t) => Object.entries(t).reduce((a, [k, w]) => a + w * (s[k] || 0), 0);
  if (pos === "K") return Math.round((ppr(s) + table(S.data.scoring_k)) * 100) / 100;
  if (pos === "DEF") return Math.round(table(S.data.scoring_def) * 100) / 100;
  return ppr(s);
}

// Where a prop stands. dir is the side being tracked (a pick or lean), or null.
function propStatus(p, key, line, dir) {
  const c = current(p);
  if (!c) return null;
  const g = S.games[p.game_id];
  if (c.none) return { v: null, res: "dnp", final: true };
  const v = statValue(key, c.stats);
  const over = v > line;
  if (g.state === "post") return { v, res: dir ? ((dir === "over") === over ? "hit" : "miss") : over ? "over" : "under", final: true };
  if (over) return { v, res: dir === "under" ? "miss" : "hit", final: false };   // stats only go up, so an over is locked in
  return { v, res: "live", final: false };
}

function twoPointScorers(text) {
  let m = text.match(/\(([^()]+?) pass to ([^()]+?) for two-point conversion\)/i);
  if (m) return [["pass_2pt", m[1]], ["rec_2pt", m[2]]];
  m = text.match(/\(([^()]+?) run for two-point conversion\)/i);
  if (m) return [["rush_2pt", m[1]]];
  return [];
}

// Per-player stat lines from an ESPN game summary, in Sleeper's field names (tools/verify.py checks this against
// Sleeper's final numbers)
function liveStatsFromSummary(summary) {
  const out = {};
  const line = (name, team) => (out[`${normName(name)}|${team}`] ??= {});
  for (const team of summary.boxscore?.players || []) {
    const abbr = teamCode(team.team.abbreviation);
    for (const group of team.statistics || []) {
      const labels = group.labels || [];
      for (const a of group.athletes || []) {
        const s = line(a.athlete.displayName, abbr);
        const vals = Object.fromEntries(labels.map((l, i) => [l, a.stats?.[i]]));
        const num = (k) => parseFloat(String(vals[k] ?? "0").replace("--", "0")) || 0;
        if (group.name === "passing") {
          const [cmp, att] = String(vals["C/ATT"] || "0/0").split("/");
          Object.assign(s, { pass_cmp: +cmp || 0, pass_att: +att || 0, pass_yd: num("YDS"), pass_td: num("TD"), pass_int: num("INT") });
        } else if (group.name === "rushing") {
          Object.assign(s, { rush_att: num("CAR"), rush_yd: num("YDS"), rush_td: num("TD") });
        } else if (group.name === "receiving") {
          Object.assign(s, { rec: num("REC"), rec_yd: num("YDS"), rec_td: num("TD"), rec_tgt: num("TGTS") });
        } else if (group.name === "fumbles") {
          Object.assign(s, { fum_lost: num("LOST") });
        } else if (group.name === "kicking") {
          const [fgm, fga] = String(vals.FG || "0/0").split("/").map((x) => +x || 0);
          const [xpm, xpa] = String(vals.XP || "0/0").split("/").map((x) => +x || 0);
          Object.assign(s, { fgm, fga, fgmiss: Math.max(0, fga - fgm), xpm, xpmiss: Math.max(0, xpa - xpm) });
        }
      }
    }
  }
  for (const play of summary.scoringPlays || []) {
    const abbr = teamCode(play.team?.abbreviation || "");
    // Field goal distances decide kicker points: "Chris Boswell 31 Yd Field Goal"
    const fg = (play.text || "").match(/^(.+?) (\d+) Yd Field Goal/i);
    if (fg) {
      const d = +fg[2];
      const bucket = d < 20 ? "fgm_0_19" : d < 30 ? "fgm_20_29" : d < 40 ? "fgm_30_39" : d < 50 ? "fgm_40_49" : "fgm_50p";
      const s = line(fg[1], abbr);
      s[bucket] = (s[bucket] || 0) + 1;
    }
    for (const [field, name] of twoPointScorers(play.text || "")) {
      const s = line(name, abbr);
      s[field] = (s[field] || 0) + 1;
    }
  }
  return out;
}

async function pollScores() {
  const d = await getJSON(`${ESPN}/scoreboard?seasontype=2&week=${S.data.week}&dates=${S.data.season}`);
  for (const e of d.events || []) {
    const g = S.games[e.id];
    if (!g) continue;
    const c = e.competitions[0];
    const home = c.competitors.find((x) => x.homeAway === "home");
    const away = c.competitors.find((x) => x.homeAway === "away");
    const sit = c.situation || {};
    const possTeam = [home, away].find((x) => x.team.id === sit.possession);
    Object.assign(g, {
      state: e.status.type.state,
      detail: e.status.type.shortDetail,
      home_score: home.score === "" ? null : +home.score,
      away_score: away.score === "" ? null : +away.score,
      poss: possTeam ? teamCode(possTeam.team.abbreviation) : null,
      dd: e.status.type.state === "in" ? sit.shortDownDistanceText || sit.downDistanceText || "" : "",
      rz: e.status.type.state === "in" && !!sit.isRedZone,
    });
  }
}

// DraftKings' in-game lines, via ESPN (same markets as pull/books.py)
const CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl";
const DK_MARKETS = {
  "Total Passing Yards (incl. overtime)": "pass_yd", "Total Pass Completions (incl. overtime)": "pass_cmp",
  "Total Passing Attempts (incl. overtime)": "pass_att", "Total Passing Touchdowns (incl. overtime)": "pass_td",
  "Total Passing Interceptions (incl. overtime)": "pass_int", "Total Rushing Yards (incl. overtime)": "rush_yd",
  "Total Carries (incl. overtime)": "rush_att", "Total Receptions (incl. overtime)": "rec",
  "Total Receiving Yards (incl. overtime)": "rec_yd", "Total Rushing Plus Receiving Yards (incl. overtime)": "rush_rec_yd",
};

async function pollLiveLines(ids) {
  await Promise.all(ids.map(async (id) => {
    try {
      const d = await getJSON(`${CORE}/events/${id}/competitions/${id}/odds/200/propBets?limit=1000`);
      for (const item of d.items || []) {
        const key = DK_MARKETS[item.type?.name];
        const espn = (item.athlete?.$ref || "").match(/athletes\/(\d+)/)?.[1];
        const pid = espn && S.byEspn[espn];
        const v = item.current?.target?.value;
        if (key && pid && v != null) (S.liveLines[pid] ??= {})[key] = v;
      }
    } catch (err) {
      console.warn("live lines", id, err);
    }
  }));
}

function liveLineText(p, key, line) {
  const v = S.liveLines[p.id]?.[key];
  if (v == null || S.games[p.game_id]?.state !== "in") return "";
  return ` · <span style="color:var(--amber)">DK live ${v}</span>`;
}

async function pollBoxScores() {
  const now = Date.now();
  const soon = (g) => g.state === "pre" && new Date(g.kickoff) - now < 4 * 3600000 && now - (S.injAt[g.id] || 0) > 300000;
  const ids = Object.values(S.games)
    .filter((g) => g.state === "in" || (g.state === "post" && !S.boxFinal.has(g.id)) || soon(g))
    .map((g) => { if (g.state === "pre") S.injAt[g.id] = now; return g.id; });
  await Promise.all(ids.map(async (id) => {
    try {
      const summary = await getJSON(`${ESPN}/summary?event=${id}`);
      applySummary(id, summary);
    } catch (err) {
      console.warn("box score", id, err);
    }
  }));
}

function applySummary(id, summary) {
  S.sum[id] = summary;
  applyInjuries(summary);
  if (!summary.boxscore?.players?.length) return;   // not started yet
  for (const [key, stats] of Object.entries(liveStatsFromSummary(summary))) {
    const pid = S.byKey[key];
    if (pid) S.live[pid] = stats;
  }
  for (const [team, stats] of Object.entries(defenseFromSummary(summary))) {
    if (S.byId[team]) S.live[team] = stats;   // a team defense's Sleeper id is its team code
  }
  S.boxLoaded.add(id);
  if (S.games[id].state === "post") S.boxFinal.add(id);
}

// ESPN lists each team's most recent injury news (game-day inactives included). Anything newer than our last
// build replaces the status shown.
const ESPN_INJ = { "Injured Reserve": "IR", Suspension: "Suspended", "Physically Unable to Perform": "PUP" };
function applyInjuries(summary) {
  for (const team of summary.injuries || []) {
    const abbr = teamCode(team.team?.abbreviation || "");
    for (const i of team.injuries || []) {
      const a = i.athlete || {};
      const pid = S.byEspn[String(a.id)] || S.byKey[`${normName(a.displayName || "")}|${abbr}`];
      if (!pid || !i.date || new Date(i.date) <= new Date(S.generatedAt)) continue;
      const inactive = i.details?.fantasyStatus?.description === "INACTIVE";
      const status = inactive ? "Out" : ESPN_INJ[i.status] || i.status;
      S.injNews[pid] = { status: status === "Active" ? null : status, part: i.details?.type, date: i.date, inactive };
    }
  }
}

function injOf(p) {
  const n = S.injNews[p.id];
  return n ? { status: n.status, part: n.part, news: n } : { status: p.injury, part: p.injury_part, news: null };
}

// Team defense stats from an ESPN summary, in Sleeper's field names (blocked kicks aren't in the feed)
function defenseFromSummary(summary) {
  const comp = summary.header?.competitions?.[0];
  if (!comp) return {};
  const teams = comp.competitors.map((c) => ({ abbr: teamCode(c.team.abbreviation), id: c.team.id, score: +c.score || 0 }));
  const out = {};
  for (const t of teams) out[t.abbr] = { sack: 0, int: 0, fum_rec: 0, ff: 0, def_td: 0, def_st_td: 0, safe: 0 };
  const other = (abbr) => teams.find((t) => t.abbr !== abbr)?.abbr;
  for (const team of summary.boxscore?.players || []) {
    const abbr = teamCode(team.team.abbreviation);
    for (const grp of team.statistics || []) {
      const col = (label) => (grp.labels || []).indexOf(label);
      const sum = (label) => (grp.athletes || []).reduce((a, x) => a + (parseFloat(x.stats?.[col(label)]) || 0), 0);
      if (grp.name === "defensive" && col("SACKS") >= 0) out[abbr].sack += sum("SACKS");
      if (grp.name === "interceptions" && col("INT") >= 0) out[abbr].int += sum("INT");
      if (grp.name === "fumbles") {
        // the other defense recovered what this offense lost
        if (col("LOST") >= 0) out[other(abbr)].fum_rec += sum("LOST");
      }
    }
  }
  for (const play of summary.scoringPlays || []) {
    const abbr = teamCode(play.team?.abbreviation || "");
    const type = play.type?.text || "";
    if (!out[abbr]) continue;
    if (/safety/i.test(type)) out[abbr].safe += 1;
    else if (/(kickoff|punt) return touchdown|blocked (punt|field goal).*touchdown/i.test(type)) out[abbr].def_st_td += 1;
    else if (/(interception|fumble) return touchdown|fumble recovery touchdown/i.test(type)) out[abbr].def_td += 1;
  }
  // Forced fumbles ("FUMBLES (T.Watt)"; unforced ones have no name) and blocked kicks, credited to the team without the ball
  for (const drive of allDrives(summary)) {
    const offense = teamCode(drive.team?.abbreviation || "");
    const defense = other(offense);
    if (!out[defense]) continue;
    for (const play of drive.plays || []) {
      const text = play.text || "";
      if (/no play|reversed/i.test(text)) continue;   // wiped out by a penalty or overturned on review
      out[defense].ff += (text.match(/FUMBLES \([^)]+\)/g) || []).length;
      if (/\bBLOCKED\b/.test(text) && /punt|field goal|extra point|kick/i.test(`${play.type?.text} ${text}`)) out[defense].blk_kick = (out[defense].blk_kick || 0) + 1;
    }
  }
  for (const t of teams) {
    // Points the other team's defense or special teams scored don't count against this defense
    const opp = out[other(t.abbr)];
    const pa = Math.max(0, teams.find((x) => x.abbr !== t.abbr).score - 6 * (opp.def_td + opp.def_st_td));
    const tier = pa === 0 ? "pts_allow_0" : pa <= 6 ? "pts_allow_1_6" : pa <= 13 ? "pts_allow_7_13" : pa <= 20 ? "pts_allow_14_20"
      : pa <= 27 ? "pts_allow_21_27" : pa <= 34 ? "pts_allow_28_34" : "pts_allow_35p";
    Object.assign(out[t.abbr], { pts_allow: pa, [tier]: 1 });
  }
  return out;
}

let liveTimer = null;
async function liveTick() {
  clearTimeout(liveTimer);
  try {
    await pollScores();
    await pollBoxScores();
    await pollLiveLines(Object.values(S.games).filter((g) => g.state === "in").map((g) => g.id));
    S.liveAt = new Date();
  } catch (err) {
    console.warn("live", err);
  }
  renderScores();
  renderLiveParts();
  const anyLive = Object.values(S.games).some((g) => g.state === "in");
  const soon = Object.values(S.games).some((g) => g.state === "pre" && new Date(g.kickoff) - Date.now() < 10 * 60000);
  if (!document.hidden) liveTimer = setTimeout(liveTick, anyLive || soon ? LIVE_MS : IDLE_MS);
}

// The open game's play-by-play refreshes faster than everything else
let gameTimer = null;
async function gameTick() {
  clearTimeout(gameTimer);
  const id = S.gameView;
  if (!id) return;
  const g = S.games[id];
  if (g.state !== "pre" && (g.state === "in" || !S.sum[id])) {
    try {
      applySummary(id, await getJSON(`${ESPN}/summary?event=${id}`));
      syncGameFromSummary(id);
    } catch (err) {
      console.warn("game", id, err);
    }
    if (S.gameView === id) renderLiveParts();
  }
  if (!document.hidden && S.gameView === id && g.state === "in") gameTimer = setTimeout(gameTick, GAME_MS);
}

// Score and clock from the summary, so the open game is never behind its own play-by-play
function syncGameFromSummary(id) {
  const comp = S.sum[id]?.header?.competitions?.[0];
  if (!comp) return;
  const g = S.games[id];
  const st = comp.status?.type;
  for (const c of comp.competitors || []) {
    if (c.score != null && c.score !== "") g[c.homeAway === "home" ? "home_score" : "away_score"] = +c.score;
  }
  if (st) Object.assign(g, { state: st.state, detail: st.shortDetail || g.detail });
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.data) { liveTick(); gameTick(); checkMeta(); }
});

async function checkMeta() {
  try {
    const m = await getJSON(`data/meta.json?t=${Date.now()}`);
    if (S.generatedAt && m.generated_at !== S.generatedAt) $("#banner").hidden = false;
  } catch { /* offline or mid-deploy: try again next time */ }
}

// ---------------------------------------------------------------- load

async function load() {
  S.data = await getJSON(`data/week.json?t=${Date.now()}`);
  S.generatedAt = S.data.generated_at;
  try { S.track = await getJSON(`data/track_record.json?t=${Date.now()}`); } catch { S.track = null; }
  try { S.dk = await getJSON(`data/dk_backtest.json?t=${Date.now()}`); } catch { S.dk = null; }
  S.byId = {};
  S.byKey = {};
  S.byEspn = {};
  for (const p of S.data.players) {
    S.byId[p.id] = p;
    S.byKey[`${normName(p.name)}|${p.team}`] = p.id;
    if (p.espn_id) S.byEspn[String(p.espn_id)] = p.id;
  }
  for (const g of S.data.games) S.games[g.id] = { ...g, ...(S.games[g.id] || {}) };
  const built = new Date(S.data.generated_at);
  $("#sub").textContent = `${S.data.season} Week ${S.data.week} · PPR · updated ${built.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}`;
}

// ---------------------------------------------------------------- score strip

function renderScores() {
  const games = Object.values(S.games).sort((a, b) => {
    const order = { in: 0, pre: 1, post: 2 };
    return order[a.state] - order[b.state] || a.kickoff.localeCompare(b.kickoff);
  });
  const anyLive = games.some((g) => g.state === "in");
  $("#live-dot").hidden = !anyLive;
  $("#scores-status").textContent = anyLive
    ? `Live · updates every 30s${S.liveAt ? ` · ${S.liveAt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" })}` : ""}`
    : "Scores";
  $("#scores-status").textContent += " \u00b7 tap a game for play-by-play";
  $("#strip").innerHTML = games.map((g) => {
    const live = g.state === "in";
    const started = g.state !== "pre";
    const row = (team, score, other) => `
      <div class="row ${g.state === "post" && score < other ? "lose" : ""}">
        <img src="${logo(team)}" alt="" loading="lazy"><span class="abbr ${live && g.poss === team ? "poss" : ""}">${team}</span>
        <span class="sc">${started && score != null ? score : ""}</span>
      </div>`;
    return `<button class="game ${live ? "live" : ""} ${g.rz ? "rz" : ""} ${S.gameView === g.id ? "on" : ""}" data-game="${g.id}">
      ${row(g.away, g.away_score, g.home_score)}${row(g.home, g.home_score, g.away_score)}
      <div class="st"><span class="clock">${esc(gameStatus(g))}</span><span class="dd">${esc(live ? g.dd || "" : g.state === "pre" ? g.tv || "" : "")}</span></div>
    </button>`;
  }).join("");
}

// ---------------------------------------------------------------- shared bits

function avatar(p) {
  if (p.pos === "DEF") return `<div class="av def"><img src="${logo(p.team)}" alt="" loading="lazy"></div>`;
  return `<div class="av"><img src="${photo(p.id)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'"><img class="tm" src="${logo(p.team)}" alt="" loading="lazy"></div>`;
}

function injBadge(p) {
  const inj = injOf(p);
  if (!inj.status) return inj.news ? `<span class="inj ok" title="Cleared (ESPN, ${esc(new Date(inj.news.date).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }))})">ACTIVE</span>` : "";
  const short = inj.news?.inactive ? "INACTIVE" : INJ_SHORT[inj.status] || inj.status;
  const when = inj.news ? `, ESPN ${new Date(inj.news.date).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}` : "";
  const title = (inj.news?.inactive ? "Inactive" : inj.status) + (inj.part ? ` (${inj.part})` : "") + when;
  return `<span class="inj ${short === "Q" ? "Q" : ""} ${inj.news ? "new" : ""}" title="${esc(title)}">${esc(short)}</span>`;
}

function oppText(p) {
  return `${p.home ? "vs" : "@"} ${p.opp}`;
}

function matchupText(p) {
  const m = p.matchup;
  if (!m || !m.label || m.label === "neutral") return "";
  return `<span class="mu ${m.label}" title="${p.opp} allows ${m.allowed} PPR per game to ${p.pos}s (rank ${m.rank} of 32, 1 = most)">${m.label === "soft" ? "Soft" : "Tough"} matchup</span>`;
}

function favBtn(p) {
  const on = S.favs.has(p.id);
  return `<button class="fav ${on ? "on" : ""}" data-fav="${p.id}" title="${on ? "Remove from" : "Add to"} favorites" aria-label="Favorite">${on ? "★" : "☆"}</button>`;
}

function resBadge(st) {
  if (!st) return "";
  if (st.res === "hit") return `<span class="res hit">${st.final ? "HIT" : "CLEARED"}</span>`;
  if (st.res === "miss") return `<span class="res miss">${st.final ? "MISS" : "LOST"}</span>`;
  if (st.res === "dnp") return `<span class="res dnp">DNP</span>`;
  if (st.res === "live") return `<span class="res live">LIVE</span>`;
  return "";
}

function progress(st, line, dir) {
  if (!st || st.v == null) return "";
  const pct = Math.min(100, (100 * st.v) / Math.max(line, 0.5));
  const cls = st.res === "hit" ? "hit" : st.res === "miss" ? "miss" : "";
  return `<div class="prog ${cls}"><i style="width:${pct}%"></i></div>`;
}

// ---------------------------------------------------------------- props tab

function pickCard(pick) {
  const p = S.byId[pick.player_id];
  if (!p) return "";
  const label = S.data.categories[pick.key].label;
  const st = propStatus(p, pick.key, pick.line, pick.direction);
  const adj = pick.adj ?? null;
  return `<div class="pick" data-open="${p.id}">
    ${avatar(p)}
    <div>
      <div><b>${esc(p.name)}</b> <span class="pos ${p.pos}">${p.pos}</span>${injBadge(p)}</div>
      <div class="what">${pick.direction === "over" ? "Over" : "Under"} <b class="num">${pick.line}</b> ${label} <span class="muted">${oppText(p)}</span></div>
      <div class="small">${LINE_FROM[pick.line_from] || "Our"} line, locked at kickoff · ${adj != null ? `our number <b class="num">${fmt(adj)}</b> · ` : ""}over in ${pick.over} of last ${pick.n}${liveLineText(p, pick.key, pick.line)}</div>
      ${progress(st, pick.line, pick.direction)}
    </div>
    <div class="side">
      ${st ? `<div class="big" data-live-pick>${st.v == null ? "-" : fmtStat(pick.key, st.v)}</div>${resBadge(st)}` : `<div class="small">${esc(gameStatus(S.games[p.game_id]))}</div>`}
    </div>
  </div>`;
}

function propChip(p, prop) {
  const line = S.lines[`${p.id}|${prop.key}`] ?? prop.line;
  const st = propStatus(p, prop.key, line, prop.lean);
  const arrow = prop.key === "anytime_td"
    ? `<span class="muted"> ${Math.round(100 * (prop.td_chance || 0))}%</span>`
    : prop.lean ? `<span class="arrow">${prop.lean === "over" ? "▲" : "▼"}</span>` : "";
  const cls = [prop.lean ? `lean-${prop.lean}` : "", st && prop.lean && (st.res === "hit" || st.res === "miss") ? st.res : ""].join(" ");
  const lineText = prop.key === "anytime_td" ? "" : `<b>${line}</b><span class="src ${prop.line_from || "ours"}">${LINE_TAG[prop.line_from] || "est"}</span>`;
  const cur = st && st.v != null ? `<span class="cur">${fmtStat(prop.key, st.v)}</span>` : "";
  return `<span class="pchip ${cls}">${SHORT[prop.key]}${lineText}${arrow}${cur}</span>`;
}

function catCard(p, prop) {
  const cat = S.data.categories[prop.key];
  const k = `${p.id}|${prop.key}`;
  const line = S.lines[k] ?? prop.line;
  const edited = S.lines[k] != null && S.lines[k] !== prop.line;
  const vals = prop.values;
  const st = propStatus(p, prop.key, line, null);
  const nowV = st && st.v != null ? st.v : null;
  const all = vals.map((x) => x.v).concat(nowV != null ? [nowV] : [], [line]);
  const top = Math.max(...all, 0.5) * 1.25;   // headroom for the value labels
  const over = vals.filter((x) => x.v > line).length;
  const avg = vals.length ? vals.reduce((a, x) => a + x.v, 0) / vals.length : null;

  let lean = prop.lean;
  if (edited && prop.adj != null && prop.key !== "anytime_td") {
    const d = prop.adj - line;
    lean = d > cat.lean ? "over" : d < -cat.lean ? "under" : null;
  }
  const leanPill = prop.key === "anytime_td"
    ? `<span class="lean ${prop.lean ? "over" : "none"}">${Math.round(100 * (prop.td_chance || 0))}% TD chance</span>`
    : prop.source !== "history" && from === "ours"
      ? `<span class="lean none">No lean</span>`
      : `<span class="lean ${lean || "none"}">${lean ? `Lean ${lean}` : "No lean"}</span>`;

  const bars = vals.map((x) => `<div class="b ${x.v > line ? "o" : ""}" title="${x.s} week ${x.w} vs ${x.opp}: ${x.v}"><span>${fmtStat(prop.key, x.v)}</span><i style="height:${(100 * x.v) / top}%"></i></div>`).join("")
    + (nowV != null ? `<div class="b now" title="This week"><span>${fmtStat(prop.key, nowV)}</span><i style="height:${(100 * nowV) / top}%"></i></div>` : "");
  const xs = vals.map((x) => `<span>${x.s !== S.data.season ? "'" + String(x.s).slice(2) + " " : ""}W${x.w}</span>`).join("")
    + (nowV != null ? `<span style="color:var(--cyan)">Now</span>` : "");

  const from = prop.line_from || "ours";
  const liveLine = S.liveLines[p.id]?.[prop.key];
  const lineCell = prop.key === "anytime_td"
    ? `<div>Line<span class="n">0.5</span></div>`
    : `<div>${edited ? "Your line" : LINE_FROM[from]}<input type="number" step="1" inputmode="decimal" value="${line}" data-line="${k}" aria-label="${cat.label} line"></div>`
      + (prop.dk_open != null && prop.dk_open !== prop.line ? `<div>DK opened<span class="n">${prop.dk_open}</span></div>` : "")
      + (liveLine != null && S.games[p.game_id]?.state === "in" ? `<div title="DraftKings' in-game line right now">DK live<span class="n" style="color:var(--amber)">${liveLine}</span></div>` : "")
      + (prop.sleeper && from !== "sleeper" ? `<div>Sleeper Picks<span class="n">${prop.sleeper.line}</span></div>` : "")
      + (from !== "ours" && prop.our_line != null ? `<div title="${prop.source === "history" ? "From his last 8 games" : "From Sleeper's projection"}">Our line<span class="n">${prop.our_line}</span></div>` : "");
  const note = prop.key === "anytime_td"
    ? `Scored in ${vals.filter((x) => x.v > 0).length} of last ${vals.length}. Chance comes from Sleeper's projected TDs.`
    : prop.source === "projection"
      ? (from === "ours" ? "Fewer than 4 games played and no sportsbook line, so this is Sleeper's projection and has no lean." : `Over in <b>${over}</b> of last ${vals.length}.`)
      : `Over in <b>${over}</b> of last ${vals.length}${edited ? ` at your line (the ${LINE_FROM[from]} line is ${prop.line})` : ""}.`
        + (from === "ours" && prop.key !== "fpts" ? " No sportsbook line yet, so this is our estimate." : "")
        + (prop.sleeper?.over ? ` Sleeper Picks pays ${prop.sleeper.over}x over, ${prop.sleeper.under}x under.` : "");

  return `<div class="cat" data-cat="${k}">
    <div class="cat-h"><span>${cat.label}</span>${leanPill}</div>
    <div class="cat-nums">
      ${lineCell}
      ${prop.adj != null && prop.key !== "anytime_td" ? `<div title="Sleeper's projection on the same scale as the line">Our number<span class="n">${fmt(prop.adj)}</span></div>` : ""}
      ${prop.proj != null ? `<div>Sleeper proj<span class="n">${fmtStat(prop.key, prop.proj)}</span></div>` : ""}
      ${avg != null ? `<div>Last ${vals.length} avg<span class="n">${fmt(avg)}</span></div>` : ""}
      ${st ? `<div>${st.final ? "Final" : "Now"}<span class="n" style="color:var(--cyan)">${st.v == null ? "DNP" : fmtStat(prop.key, st.v)}</span></div>` : ""}
    </div>
    ${vals.length ? `<div class="bars">${bars}<div class="lineat" style="bottom:${(100 * line) / top}%"></div></div><div class="bars-x">${xs}</div>` : ""}
    <div class="foot-n">${note}</div>
  </div>`;
}

function playerCard(p) {
  const open = S.open.has(p.id);
  const g = S.games[p.game_id];
  const live = livePPR(p);
  const c = current(p);
  const props = p.props.filter((x) => !S.f.cat || x.key === S.f.cat);
  const out = UNAVAILABLE.has(injOf(p).status);
  return `<div class="player ${out ? "out" : ""}" data-player="${p.id}">
    <div class="phead" data-toggle="${p.id}">
      ${avatar(p)}
      <div>
        <div class="pname">${esc(p.name)}${injBadge(p)}</div>
        <div class="pmeta"><span class="pos ${p.pos}">${p.pos}</span> ${p.team} ${oppText(p)} ${matchupText(p)} <span>· ${esc(gameStatus(g))}</span></div>
      </div>
      <div class="pts"><div class="lbl">Proj</div><div class="v">${fmt(p.proj_ppr)}</div></div>
      <div class="pts"><div class="lbl">${g?.state === "post" ? "Final" : g?.state === "in" ? "Live" : "Avg"}</div>
        <div class="v ${c ? "live" : ""}" data-live-ppr="${p.id}">${c ? (c.none ? "DNP" : fmt(live)) : fmt(p.avg_ppr)}</div></div>
    </div>
    <div class="props-row" data-chips="${p.id}">${props.map((x) => propChip(p, x)).join("")}</div>
    ${open ? `<div class="pbody">${props.map((x) => catCard(p, x)).join("")}
      <div class="note" style="grid-column:1/-1">${favBtn(p)} ${p.depth ? `Depth chart: ${p.pos}${p.depth}. ` : ""}${p.late ? "These lines were first built after kickoff, so they aren't graded." : ""}</div></div>` : ""}
  </div>`;
}

function filteredPlayers() {
  const f = S.f;
  const q = normName(f.q);
  let list = S.data.players.filter((p) =>
    (f.pos === "ALL" || p.pos === f.pos)
    && (!f.game || p.game_id === f.game)
    && (!f.cat || p.props.some((x) => x.key === f.cat))
    && (!q || normName(p.name).includes(q) || p.team.toLowerCase() === q)
    && (!f.hideOut || !UNAVAILABLE.has(injOf(p).status))
    && p.props.length
    && (!f.favs || S.favs.has(p.id)));
  const key = {
    proj: (p) => -(p.proj_ppr ?? -1),
    live: (p) => -(livePPR(p) ?? -1),
    name: (p) => p.name,
    edge: (p) => -Math.max(0, ...p.props.filter((x) => x.lean && x.adj != null && (!f.cat || x.key === f.cat))
      .map((x) => Math.abs(x.adj - x.line) / Math.max(1, x.line))),
  }[f.sort];
  list.sort((a, b) => { const ka = key(a), kb = key(b); return ka < kb ? -1 : ka > kb ? 1 : 0; });
  return list;
}

function renderProps() {
  const d = S.data;
  const f = S.f;
  const gameOpts = Object.values(S.games).sort((a, b) => a.kickoff.localeCompare(b.kickoff))
    .map((g) => `<option value="${g.id}" ${f.game === g.id ? "selected" : ""}>${g.away} @ ${g.home}</option>`).join("");
  const catOpts = Object.entries(d.categories).map(([k, v]) => `<option value="${k}" ${f.cat === k ? "selected" : ""}>${v.label}</option>`).join("");
  const list = filteredPlayers();
  const picksFor = (side) => d.picks[side].filter((x) => !f.game || x.game_id === f.game);
  const pickList = (side) => picksFor(side).map(pickCard).join("") || `<div class="empty">No ${side} picks${f.game ? " in this game" : ""}.</div>`;

  $("#main").innerHTML = `
    <div class="picks-wrap">
      <div class="picks"><h3>Top Overs <span class="tag over">${picksFor("over").length}</span></h3>${pickList("over")}</div>
      <div class="picks"><h3>Top Unders <span class="tag under">${picksFor("under").length}</span></h3>${pickList("under")}</div>
    </div>
    <p class="note">Top picks are the biggest gaps between our number (Sleeper's projection, adjusted) and the real DraftKings line, for players with 2+ games this season who aren't ruled out. They lock at kickoff with the pregame line; during the game you'll also see DraftKings' live line. <a href="#" data-goto="about">How it works</a></p>

    <h2>Players <small>${list.length} shown</small></h2>
    <div class="filters">
      <div class="chips">${["ALL", "QB", "RB", "WR", "TE"].map((x) => `<button class="chip ${f.pos === x ? "on" : ""}" data-pos="${x}">${x === "ALL" ? "All" : x}</button>`).join("")}</div>
      <select id="f-game" aria-label="Game"><option value="">All games</option>${gameOpts}</select>
      <select id="f-cat" aria-label="Prop"><option value="">All props</option>${catOpts}</select>
      <select id="f-sort" aria-label="Sort">
        <option value="proj" ${f.sort === "proj" ? "selected" : ""}>Sort: Projected PPR</option>
        <option value="live" ${f.sort === "live" ? "selected" : ""}>Sort: Live PPR</option>
        <option value="edge" ${f.sort === "edge" ? "selected" : ""}>Sort: Biggest lean</option>
        <option value="name" ${f.sort === "name" ? "selected" : ""}>Sort: Name</option>
      </select>
      <input type="search" id="f-q" placeholder="Search player or team" value="${esc(f.q)}">
      <label><input type="checkbox" id="f-out" ${f.hideOut ? "checked" : ""}> Hide out/IR</label>
      <label><input type="checkbox" id="f-favs" ${f.favs ? "checked" : ""}> ★ Favorites</label>
    </div>
    <div class="plist">${list.slice(0, S.shown).map(playerCard).join("") || `<div class="empty">No players match.</div>`}</div>
    ${list.length > S.shown ? `<button class="more" data-more>Show more (${list.length - S.shown})</button>` : ""}`;
}

// ---------------------------------------------------------------- fantasy tab

function renderFantasy() {
  const ff = S.ff;
  const pos = ff.pos === "FLEX" ? ["RB", "WR", "TE"] : ff.pos === "ALL" ? ["QB", "RB", "WR", "TE", "K", "DEF"] : [ff.pos];
  const rows = S.data.players.filter((p) => pos.includes(p.pos) && p.proj_ppr != null && p.proj_ppr >= 0.5)
    .map((p) => {
      const live = livePPR(p);
      return { p, proj: p.proj_ppr, live, diff: live != null ? live - p.proj_ppr : null, avg: p.avg_ppr, name: p.name };
    });
  const projRank = new Map([...rows].sort((a, b) => b.proj - a.proj).map((r, i) => [r.p.id, i + 1]));
  const dir = ff.desc ? -1 : 1;
  rows.sort((a, b) => {
    const x = a[ff.sort], y = b[ff.sort];
    if (x == null && y == null) return b.proj - a.proj;
    if (x == null) return 1;
    if (y == null) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * dir;
  });
  const th = (key, label, cls = "") => `<th class="${cls} ${ff.sort === key ? "sorted" : ""}" data-sort="${key}">${label}${ff.sort === key ? (ff.desc ? " ↓" : " ↑") : ""}</th>`;
  $("#main").innerHTML = `
    <h2>Fantasy rankings <small>PPR, Sleeper's standard scoring</small></h2>
    <div class="filters"><div class="chips">${["QB", "RB", "WR", "TE", "FLEX", "K", "DEF", "ALL"].map((x) => `<button class="chip ${ff.pos === x ? "on" : ""}" data-fpos="${x}">${x === "ALL" ? "All" : x}</button>`).join("")}</div></div>
    <div class="tbl-wrap"><table class="tbl">
      <thead><tr><th class="l">#</th>${th("name", "Player", "l")}<th class="l hide-sm">Game</th>${th("proj", "Proj")}${th("live", "Live")}${th("diff", "+/-", "hide-sm")}${th("avg", "Avg", "hide-sm")}</tr></thead>
      <tbody>${rows.slice(0, ff.shown).map((r) => {
        const p = r.p;
        const g = S.games[p.game_id];
        const c = current(p);
        return `<tr data-open="${p.id}">
          <td class="rk">${projRank.get(p.id)}</td>
          <td class="l"><div class="who">${avatar(p)}<div><div><b>${esc(p.name)}</b>${injBadge(p)}</div>
            <div class="pmeta"><span class="pos ${p.pos}">${p.pos}</span> ${p.team} ${oppText(p)} ${matchupText(p)}</div></div></div></td>
          <td class="l hide-sm muted">${esc(gameStatus(g))}</td>
          <td class="big">${fmt(r.proj)}</td>
          <td class="big" style="color:var(--cyan)">${c ? (c.none ? "DNP" : fmt(r.live)) : "-"}</td>
          <td class="hide-sm ${r.diff > 0 ? "up" : r.diff < 0 ? "down" : ""}">${r.diff == null ? "-" : (r.diff > 0 ? "+" : "") + fmt(r.diff)}</td>
          <td class="hide-sm muted">${fmt(r.avg)}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>
    ${rows.length > ff.shown ? `<button class="more" data-fmore>Show more (${rows.length - ff.shown})</button>` : ""}
    <p class="note">Proj is Sleeper's projection for this week. Live comes from ESPN's box score every 30 seconds and matches Sleeper's final scoring, except rare plays the box score doesn't show (special teams fumble recoveries and blocked kicks), which catch up at the next hourly update. Kickers score 3 per field goal under 40 yards, 4 from 40 to 49, 5 from 50+, 1 per extra point and -1 per miss. Defenses score for sacks, takeaways, touchdowns, safeties and points allowed. Avg is this season's average.</p>`;
}

// ---------------------------------------------------------------- track record tab

function pctText(t) {
  return t && t.pct != null ? `${fmt(t.pct)}%` : "-";
}

function dkSection(c) {
  const b = S.dk;
  const dl = c.dk_leans || {};
  const leanStat = (side) => `<div class="card stat"><div class="k">Leans ${side} the real line</div><div class="v">${pctText(dl[side])}</div><div class="d">${dl[side] ? `${dl[side].hit}-${dl[side].miss}` : "0-0"}, DraftKings or Sleeper Picks lines</div></div>`;
  return `<h2>Against real lines</h2>
    <div class="stats">${leanStat("over")}${leanStat("under")}</div>
    ${b ? `<h2>Our lines vs DraftKings <small>${b.season} weeks ${b.weeks[0]}-${b.weeks[b.weeks.length - 1]}, ${b.props.toLocaleString()} props</small></h2>
    <div class="stats">
      <div class="card stat"><div class="k">DraftKings closer to the result</div><div class="v">${fmt(b.dk_closer)}%</div><div class="d">vs our line built from recent games</div></div>
      <div class="card stat"><div class="k">Unders at DraftKings' line</div><div class="v">${fmt(b.dk_under)}%</div><div class="d">a fair line would be 50%</div></div>
      <div class="card stat"><div class="k">Our line well below DK: under hit</div><div class="v">${fmt(b.below_under)}%</div><div class="d">${b.below_n} props</div></div>
      <div class="card stat"><div class="k">Our line well above DK: over hit</div><div class="v">${fmt(b.above_over)}%</div><div class="d">${b.above_n} props</div></div>
    </div>
    <div class="tbl-wrap"><table class="tbl">
      <thead><tr><th class="l">Category</th><th>Props</th><th>Ours minus DK</th><th>Unders at DK</th><th>DK closer</th></tr></thead>
      <tbody>${b.categories.filter((x) => x.dk_under != null).map((x) => `<tr><td class="l">${S.data.categories[x.key].label}</td><td>${x.n}</td><td>${x.gap > 0 ? "+" : ""}${fmt(x.gap)}</td><td>${fmt(x.dk_under)}%</td><td>${x.dk_closer != null ? fmt(x.dk_closer) + "%" : "-"}</td></tr>`).join("")}</tbody>
    </table></div>
    <p class="note">DraftKings' closing lines, via ESPN, for every finished game this season, compared with the line we would have set from earlier games only (tools/compare_lines.py). DraftKings is sharper, which is why its line is the one used on this site.</p>` : ""}`;
}

function renderRecord() {
  const t = S.track;
  if (!t || !t.weeks.length) {
    $("#main").innerHTML = `<h2>Track record</h2><div class="card note">Nothing graded yet.</div>`;
    return;
  }
  const c = t.cumulative;
  const graded = (x) => x.hit + x.miss;
  const stat = (k, tally, d) => `<div class="card stat"><div class="k">${k}</div><div class="v">${pctText(tally)}</div><div class="d">${d}</div></div>`;
  const cats = Object.entries(c.leans.by_category);
  const weeks = t.weeks.map((w) => {
    const picks = [...w.top_over.picks, ...w.top_under.picks];
    return `<details class="card week" ${w === t.weeks[0] ? "open" : ""}>
      <summary>${w.season} Week ${w.week} ${w.complete ? "" : `<span class="res live">IN PROGRESS</span>`}
        <span class="muted" style="font-weight:500"> · Overs ${w.top_over.hit}-${w.top_over.miss} · Unders ${w.top_under.hit}-${w.top_under.miss} · Leans ${w.leans.hit}-${w.leans.miss}</span></summary>
      ${picks.length ? `<div class="glist">${picks.map((x) => `<div class="g"><span>${esc(x.name)} ${x.direction === "over" ? "o" : "u"}${x.line} ${SHORT[x.key]}</span><span><span class="num">${x.actual ?? "-"}</span> <span class="res ${x.result}">${x.result.toUpperCase()}</span></span></div>`).join("")}</div>` : `<p class="note">No picks graded yet this week (they're graded when each game goes final).</p>`}
      ${w.ppr.n ? `<p class="note">PPR projection error: Sleeper ${w.ppr.proj_mae} pts per player vs ${w.ppr.average_mae} for our fantasy points line (${w.ppr.n} players).</p>` : ""}
    </details>`;
  }).join("");
  const nothing = graded(c.top_over) + graded(c.top_under) + graded(c.leans) === 0;
  $("#main").innerHTML = `
    <h2>Track record <small>${c.weeks} week${c.weeks === 1 ? "" : "s"}</small></h2>
    ${nothing ? `<div class="card note" style="margin-bottom:10px">Grading started with week ${t.weeks[t.weeks.length - 1].week} of ${t.weeks[t.weeks.length - 1].season}. Only picks and leans saved before kickoff count, so this fills in as games go final. There's no backfill: Sleeper updates past weeks' projections after the games, so grading old weeks would look far better than it really is.</div>` : ""}
    <div class="stats">
      ${stat("Top Overs", c.top_over, `${c.top_over.hit}-${c.top_over.miss}${c.top_over.dnp ? `, ${c.top_over.dnp} DNP` : ""}`)}
      ${stat("Top Unders", c.top_under, `${c.top_under.hit}-${c.top_under.miss}${c.top_under.dnp ? `, ${c.top_under.dnp} DNP` : ""}`)}
      ${stat("Every lean", c.leans, `${c.leans.hit}-${c.leans.miss}, all categories`)}
      <div class="card stat"><div class="k">PPR projection error</div><div class="v">${c.ppr.proj_mae ?? "-"}</div><div class="d">${c.ppr.n ? `pts per player, vs ${c.ppr.average_mae} for our line (${c.ppr.n} players)` : "graded once games go final"}</div></div>
    </div>
    ${cats.length ? `<h2>Leans by category</h2><div class="glist">${cats.map(([k, v]) => `<div class="g"><span>${S.data.categories[k].label}</span><span class="num">${v.hit}-${v.miss} · ${pctText(v)}</span></div>`).join("")}</div>` : ""}
    ${dkSection(c)}
    <h2>By week</h2>${weeks}
    <p class="note">A hit needs the result strictly over or under the line (lines end in .5, so there are no pushes). Players who didn't play are DNP, not misses. Lines first built after a game kicked off are never graded.</p>`;
}

// ---------------------------------------------------------------- how it works tab

function renderAbout() {
  const sc = S.data.scoring;
  const scoreRows = [
    ["Passing yard", sc.pass_yd], ["Passing TD", sc.pass_td], ["Interception", sc.pass_int], ["Rushing yard", sc.rush_yd],
    ["Rushing or receiving TD", sc.rush_td], ["Reception", sc.rec], ["Receiving yard", sc.rec_yd], ["2-point conversion", sc.pass_2pt],
    ["Fumble lost", sc.fum_lost], ["Special teams TD", sc.st_td],
  ];
  const cats = Object.entries(S.data.categories).filter(([k]) => k !== "anytime_td");
  $("#main").innerHTML = `<div class="about">
    <h2>Lines</h2>
    <p>Every prop uses the real <b>DraftKings</b> line when DraftKings has posted one (ESPN carries DraftKings' player props). If DraftKings hasn't, it uses <b>Sleeper Picks</b>' line, and only after that our own estimate, which is labeled "est". Each card shows all of them side by side, plus where DraftKings' line opened.</p>
    <p>Our own line is built from the player's last 8 games (only games before this week count), scaled down per category so it lands 50/50 on past games, and rounded to a .5. It's shown for comparison and as a fallback.</p>
    <h2>Leans and top picks</h2>
    <p>"Our number" is Sleeper's projection for this week on the same scale as our line. A lean means our number is far enough above (over) or below (under) the real line. Top Overs and Top Unders are the biggest gaps, measured in each category's typical spread, and only use real sportsbook lines. They include players with 2+ games this season who aren't out, doubtful or on IR, and lock at kickoff. During a game, cards also show DraftKings' live line.</p>
    <h2>How our lines compare with DraftKings</h2>
    <p>See the Track Record tab. In short: DraftKings' lines are sharper than ours, and unders have hit more often than overs at DraftKings' lines this season. That's why the real line is the one that counts.</p>
    <h2>Fantasy points</h2>
    <p>PPR with Sleeper's standard settings, for every position including kickers and team defenses. The formula reproduces Sleeper's own totals on about 7,400 player-weeks from 2025 and 2026, re-checked on every update.</p>
    <table class="ptable">${scoreRows.map(([k, v]) => `<tr><td>${k}</td><td class="num">${v > 0 ? "+" : ""}${v}</td></tr>`).join("")}</table>
    <h2>Live</h2>
    <p>Scores, box scores and play-by-play come straight from ESPN every 30 seconds while games are on (every 15 seconds for the game you have open), paused when this tab is hidden. Live points use the same scoring, including 2-point conversions and field goal distances. An over is marked cleared the moment it passes the line, since stats only go up; an under is only a hit once the game is final.</p>
    <h2>Injuries</h2>
    <p>Injury designations come from Sleeper with each update. On game days the page also checks ESPN's latest injury news for games kicking off within 4 hours, so game-day inactives show up right away (outlined badges, with the time ESPN posted them).</p>
    <h2>Updates and honest grading</h2>
    <p>Lines, projections and injuries rebuild every hour (every 30 minutes on game days). Once a game kicks off, its lines and picks freeze. The track record only grades what was posted before kickoff, and it isn't backfilled: Sleeper revises past weeks' projections after the games, so grading old weeks with them would use information nobody had beforehand.</p>
    <h2 id="maker">Made by Joshua Moy</h2>
    <div class="card bio">
      <p>Joshua Moy is a Northeastern University student who builds data tools: hourly data pipelines, sports models that grade themselves in public, and interactive maps and dashboards.</p>
      <ul>
        <li><b>NFL Player Props</b> (this site): DraftKings and Sleeper lines, PPR projections, live scoring and play-by-play for every game.</li>
        <li><b><a href="https://joshuam0y.github.io/mlb-player-props/" target="_blank" rel="noopener">MLB Player Props</a></b>: the baseball version, rebuilt hourly from MLB's public data, with its own public track record.</li>
        <li><b><a href="https://joshuam0y.github.io/sustainability-network/" target="_blank" rel="noopener">Sustainability Faculty Network</a></b>: an interactive map of faculty research and courses in sustainability that replaced a Tableau dashboard.</li>
      </ul>
      <p class="note">Python, SQL, JavaScript and GitHub Actions. Code: <a href="https://github.com/joshuam0y" target="_blank" rel="noopener">github.com/joshuam0y</a></p>
    </div>
  </div>`;
}

// ---------------------------------------------------------------- game page

function gameTeams(g) {
  const comp = S.sum[g.id]?.header?.competitions?.[0];
  const out = {};
  for (const side of ["away", "home"]) {
    const c = comp?.competitors?.find((x) => x.homeAway === side);
    out[side] = {
      abbr: g[side], id: c?.team?.id, name: c?.team?.displayName || g[side],
      short: c?.team?.name || c?.team?.shortDisplayName || g[side],
      color: c?.team?.color ? `#${c.team.color}` : "#344677",
      record: c?.record?.find((r) => r.type === "total")?.summary || c?.record?.[0]?.summary || "",
    };
  }
  return out;
}

function allDrives(sum) {
  const d = sum?.drives || {};
  const list = [...(d.previous || [])];
  if (d.current && !list.some((x) => x.id === d.current.id)) list.push(d.current);
  return list;
}

function playTags(play) {
  const type = play.type?.text || "";
  const text = play.text || "";
  const tags = [];
  if (play.scoringPlay) tags.push(["score", play.type?.abbreviation === "FG" || /field goal/i.test(type) ? "FG" : /safety/i.test(type) ? "SAFETY" : /extra point|two-point/i.test(type) ? "PAT" : "TD"]);
  if (/interception/i.test(type) || /intercepted/i.test(text)) tags.push(["to", "INT"]);
  else if (/fumble recovery \(opponent\)|opp fumble recovery/i.test(type) || (/fumbles/i.test(text) && /recovered by/i.test(text) && play.end?.team?.id && play.start?.team?.id && play.end.team.id !== play.start.team.id)) tags.push(["to", "FUMBLE"]);
  if (/sack/i.test(type)) tags.push(["flag", "SACK"]);
  if (/penalty/i.test(text)) tags.push(["flag", /declined/i.test(text) ? "FLAG, DECLINED" : "FLAG"]);
  if ((play.statYardage || 0) >= 20 && !play.scoringPlay && !/punt|kickoff/i.test(type)) tags.push(["big", `+${play.statYardage}`]);
  return tags;
}

// ESPN writes players as "D.Watson" / "M.Harrison Jr." in play text
function playersInPlay(text, roster) {
  return roster.filter((r) => r.abbrs.some((a) => text.includes(a)));
}

function gameRoster(g) {
  return S.data.players.filter((p) => p.game_id === g.id && p.pos !== "DEF").map((p) => {
    const parts = p.name.split(" ");
    const rest = parts.slice(1).join(" ");
    const bare = rest.replace(/ (Jr\.|Sr\.|II|III|IV|V)$/, "");
    return { p, abbrs: [...new Set([`${parts[0][0]}.${rest}`, `${parts[0][0]}.${bare}`])] };
  });
}

function playRow(play, teams, roster = [], fresh = false) {
  const tags = playTags(play);
  const who = playersInPlay(play.text || "", roster);
  const dd = play.start?.down > 0 ? `${play.start.shortDownDistanceText || ""} at ${play.start.possessionText || ""}` : "";
  const score = play.scoringPlay ? `<span class="pl-score">${teams.away.abbr} ${play.awayScore} - ${teams.home.abbr} ${play.homeScore}</span>` : "";
  const cls = play.scoringPlay ? "scoring" : tags.some((t) => t[0] === "to") ? "turnover" : "";
  return `<div class="play ${cls} ${fresh ? "fresh" : ""}">
    <div class="pl-time">Q${play.period?.number ?? ""}<br>${esc(play.clock?.displayValue || "")}</div>
    <div class="pl-body">
      ${dd ? `<div class="pl-dd">${esc(dd)}</div>` : ""}
      <div class="pl-text">${esc(play.text || play.type?.text || "")}</div>
      ${tags.length || score || who.length ? `<div class="pl-tags">${tags.map(([k, v]) => `<span class="ptag ${k}">${v}</span>`).join("")}${score}
        ${who.map(({ p }) => `<button class="pl-who ${S.favs.has(p.id) ? "fav-on" : ""}" data-open="${p.id}" title="Open ${esc(p.name)}"><span class="pos ${p.pos}">${p.pos}</span> ${esc(p.name.split(" ").slice(1).join(" "))} <b class="num">${fmt(livePPR(p))}</b></button>`).join("")}</div>` : ""}
    </div>
  </div>`;
}

function fieldView(g, teams, sum) {
  if (g.state !== "in") return "";
  const drives = allDrives(sum);
  const last = drives.length ? drives[drives.length - 1].plays?.slice(-1)[0] : null;
  const spot = last?.end;
  if (!spot || spot.yardLine == null) return "";
  // ESPN's yardLine is yards from the home team's goal line: home end zone on the left, away on the right
  const x = Math.max(0, Math.min(100, spot.yardLine));
  const homeBall = spot.team?.id === teams.home.id;
  const toGo = spot.distance || 0;
  const firstDown = spot.down > 0 && toGo ? Math.max(0, Math.min(100, homeBall ? x + toGo : x - toGo)) : null;
  const pos = (v) => `calc(8% + ${v * 0.84}%)`;
  const ticks = [10, 20, 30, 40, 50, 60, 70, 80, 90].map((v) => `<i class="yl" style="left:${pos(v)}"><b>${v <= 50 ? v : 100 - v}</b></i>`).join("");
  return `<div class="field">
    <div class="ez" style="left:0;background:${teams.home.color}">${teams.home.abbr}</div>
    <div class="ez" style="right:0;background:${teams.away.color}">${teams.away.abbr}</div>
    ${ticks}
    ${firstDown != null ? `<i class="fd" style="left:${pos(firstDown)}"></i>` : ""}
    <i class="los" style="left:${pos(x)}"></i>
    <span class="ball ${homeBall ? "right" : "left"}" style="left:${pos(x)}" title="${esc(spot.possessionText || "")}"></span>
  </div>
  <div class="field-cap">${esc(spot.downDistanceText || spot.possessionText || "")}${g.rz ? ` <span class="ptag to">RED ZONE</span>` : ""}</div>`;
}

function winProb(sum, teams) {
  const wp = sum?.winprobability || [];
  if (wp.length < 2) return "";
  const home = wp[wp.length - 1].homeWinPercentage;
  const leader = home >= 0.5 ? teams.home : teams.away;
  const pct = Math.round(100 * Math.max(home, 1 - home));
  const w = 300, h = 54;
  const pts = wp.map((x, i) => `${(i / (wp.length - 1)) * w},${(h * (1 - x.homeWinPercentage)).toFixed(1)}`).join(" ");
  return `<div class="wp">
    <div class="wp-h"><span>Win probability</span><span><b class="num">${pct}%</b> ${leader.abbr}</span></div>
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-label="Win probability over the game">
      <line x1="0" x2="${w}" y1="${h / 2}" y2="${h / 2}" class="mid"/>
      <polyline points="${pts}" fill="none" stroke="var(--cyan)" stroke-width="2" vector-effect="non-scaling-stroke"/>
    </svg>
    <div class="wp-x"><span>${teams.home.abbr}</span><span>${teams.away.abbr}</span></div>
  </div>`;
}


const TEAM_STATS = [
  ["firstDowns", "1st downs"], ["totalYards", "Total yards"], ["netPassingYards", "Passing"], ["rushingYards", "Rushing"],
  ["thirdDownEff", "3rd down"], ["fourthDownEff", "4th down"], ["redZoneAttempts", "Red zone"], ["turnovers", "Turnovers"],
  ["sacksYardsLost", "Sacks-yards"], ["totalPenaltiesYards", "Penalties"], ["possessionTime", "Possession"],
];


function linescore(sum, teams) {
  const comp = sum?.header?.competitions?.[0];
  const rows = ["away", "home"].map((side) => comp?.competitors?.find((c) => c.homeAway === side));
  if (!rows[0]?.linescores?.length) return "";
  const n = Math.max(4, ...rows.map((r) => r.linescores.length));
  const head = Array.from({ length: n }, (_, i) => `<th>${i < 4 ? i + 1 : i === 4 ? "OT" : `OT${i - 3}`}</th>`).join("");
  const row = (r, side) => `<tr><td class="l"><img src="${logo(teams[side].abbr)}" alt=""> ${teams[side].abbr}</td>${Array.from({ length: n }, (_, i) => `<td>${r.linescores[i]?.displayValue ?? r.linescores[i]?.value ?? ""}</td>`).join("")}<td class="t">${r.score ?? ""}</td></tr>`;
  return `<table class="linescore"><thead><tr><th></th>${head}<th>T</th></tr></thead><tbody>${row(rows[0], "away")}${row(rows[1], "home")}</tbody></table>`;
}


// ---- game page: tabs, toolbars and their state

const GAME_TABS = [["plays", "Plays"], ["box", "Box Score"], ["props", "Props"], ["fantasy", "Fantasy"]];
const PLAY_FILTERS = [["all", "All"], ["scoring", "Scoring"], ["big", "Big plays"], ["to", "Turnovers"], ["flag", "Flags"]];
const BOX_SECTIONS = [["off", "Offense", ["passing", "rushing", "receiving", "fumbles"]], ["def", "Defense", ["defensive", "interceptions"]],
  ["st", "Special teams", ["kicking", "punting", "kickReturns", "puntReturns"]]];

// Each game remembers its own tab and filters for the session
function gs(id = S.gameView) {
  const g = S.games[id];
  return (S.gs[id] ??= {
    tab: g.state === "pre" ? "props" : g.state === "in" ? "plays" : "box",
    pbp: "all", team: "", order: "new", drives: null, box: "off", bteam: g.away, pos: "ALL", sort: g.state === "pre" ? "proj" : "live", leans: false,
  });
}

function seg(attr, cur, options, label) {
  return `<div class="seg" role="group" aria-label="${label}">${options.map(([v, l]) =>
    `<button class="${cur === v ? "on" : ""}" ${attr}="${v}" aria-pressed="${cur === v}">${l}</button>`).join("")}</div>`;
}

function teamSeg(teams, cur) {
  return seg("data-gteam", cur, [["", "Both"], ...["away", "home"].map((s) => [teams[s].abbr, `<img src="${logo(teams[s].abbr)}" alt="">${teams[s].abbr}`])], "Team");
}

function gamesInOrder() {
  return Object.values(S.games).sort((a, b) => a.kickoff.localeCompare(b.kickoff) || a.id.localeCompare(b.id));
}

// ---- plays

function renderPlays(g, sum, teams) {
  const st = gs(g.id);
  if (g.state === "pre") return `<div class="empty">Play-by-play starts at kickoff (${esc(kickoffText(g.kickoff))}).</div>`;
  if (!sum) return `<div class="empty">Loading plays...</div>`;
  const roster = gameRoster(g);
  const seen = S.seenPlays[g.id];
  const isFresh = (pl) => seen && !seen.has(pl.id);
  const all = allDrives(sum);
  const newest = all.length ? all[all.length - 1].id : null;
  const drives = st.team ? all.filter((d) => teamCode(d.team?.abbreviation || "") === st.team) : all;
  const ordered = (arr) => (st.order === "new" ? arr.slice().reverse() : arr);
  const isOpen = (d) => (st.drives === "all" ? true : st.drives === "none" ? false : d.id === newest) !== S.openDrives.has(d.id);
  const allOpen = drives.length > 0 && drives.every(isOpen);

  const toolbar = `<div class="gtool">
    ${seg("data-pbp", st.pbp, PLAY_FILTERS, "Show")}
    ${teamSeg(teams, st.team)}
    ${seg("data-order", st.order, [["new", "Newest first"], ["old", "Oldest first"]], "Order")}
    ${st.pbp === "all" ? `<button class="tbtn" data-drives="${allOpen ? "none" : "all"}">${allOpen ? "Collapse all" : "Expand all"}</button>` : ""}
  </div>`;
  if (!drives.length) return toolbar + `<div class="empty">No plays yet.</div>`;

  if (st.pbp !== "all") {
    const keep = (pl) => st.pbp === "scoring" ? pl.scoringPlay : playTags(pl).some((t) => t[0] === st.pbp);
    const plays = ordered(drives.flatMap((d) => (d.plays || []).filter(keep)));
    return toolbar + `<div class="gcount">${plays.length} ${plays.length === 1 ? "play" : "plays"}</div>`
      + (plays.length ? `<div class="play-list">${plays.map((pl) => playRow(pl, teams, roster, isFresh(pl))).join("")}</div>` : `<div class="empty">None yet.</div>`);
  }

  return toolbar + ordered(drives).map((d) => {
    const open = isOpen(d);
    const abbr = teamCode(d.team?.abbreviation || "");
    const live = g.state === "in" && d.id === newest && !d.displayResult;
    const result = live ? "In progress" : d.displayResult || d.result || "";
    const lost = /fumble|interception|downs|safety/i.test(d.displayResult || d.result || "");
    return `<div class="drive ${d.isScore ? "scored" : ""} ${lost ? "lost" : ""} ${live ? "live" : ""}">
      <button class="drive-h" data-drive="${d.id}" aria-expanded="${open}">
        <img src="${logo(abbr)}" alt="">
        <span class="drive-r"><b>${esc(result)}</b> <span class="muted">${esc(d.description || "")}</span></span>
        <span class="muted drive-s">${d.start?.text ? `from ${esc(d.start.text)}` : ""}</span>
        <span class="chev">${open ? "▴" : "▾"}</span>
      </button>
      ${open ? `<div class="drive-b">${ordered(d.plays || []).map((pl) => playRow(pl, teams, roster, isFresh(pl))).join("")}</div>` : ""}
    </div>`;
  }).join("");
}

// ---- box score

function boxName(sum, key) {
  for (const team of sum.boxscore?.players || []) for (const grp of team.statistics || []) for (const at of grp.athletes || [])
    if (`${normName(at.athlete.displayName)}|${teamCode(team.team.abbreviation)}` === key) return at.athlete.displayName;
  return key.split("|")[0];
}

function statNumber(v) {
  if (v == null) return null;
  const s = String(v);
  let m = s.match(/^(\d+):(\d+)$/);
  if (m) return +m[1] * 60 + +m[2];                       // possession time
  m = s.match(/^(\d+)-(\d+)$/);
  if (m) return +m[2] ? +m[1] / +m[2] : 0;                // 3rd down 4-11, as a rate
  const n = parseFloat(s);
  return Number.isNaN(n) ? null : n;
}

function renderBox(g, sum, teams) {
  const st = gs(g.id);
  if (g.state === "pre") return `<div class="empty">The box score fills in once the game starts.</div>`;
  if (!sum?.boxscore) return `<div class="empty">Loading box score...</div>`;
  const stat = (side) => {
    const t = sum.boxscore.teams?.find((x) => teamCode(x.team.abbreviation) === teams[side].abbr);
    return Object.fromEntries((t?.statistics || []).map((x) => [x.name, x.displayValue]));
  };
  const a = stat("away"), h = stat("home");
  const teamRows = TEAM_STATS.filter(([k]) => a[k] != null || h[k] != null).map(([k, label]) => {
    const x = statNumber(a[k]), y = statNumber(h[k]);
    const share = x != null && y != null && x + y > 0 ? (100 * x) / (x + y) : 50;
    return `<div class="tsr">
      <span class="num">${esc(a[k] ?? "-")}</span><span class="lbl">${label}</span><span class="num">${esc(h[k] ?? "-")}</span>
      <div class="tsb"><i style="width:${share}%;background:${teams.away.color}"></i><i style="width:${100 - share}%;background:${teams.home.color}"></i></div>
    </div>`;
  }).join("");

  const lines = liveStatsFromSummary(sum);
  const pprOf = (name, abbr) => { const s = lines[`${normName(name)}|${abbr}`]; return s ? ppr(s) : null; };
  const groupsWanted = BOX_SECTIONS.find((x) => x[0] === st.box)[2];
  // One team's tables, then the other's (away first)
  const teamOrder = [teams.away.abbr, teams.home.abbr].filter((abbr) => !st.bteam || st.bteam === abbr);
  const byTeam = Object.fromEntries((sum.boxscore.players || []).map((team) => [teamCode(team.team.abbreviation), team]));
  const tables = teamOrder.map((abbr) => groupsWanted.map((name) => {
    const team = byTeam[abbr];
    if (!team) return "";
    const grp = (team.statistics || []).find((x) => x.name === name);
    if (!grp || !grp.athletes?.length) return "";
    const labels = grp.labels || [];
    const withPts = st.box === "off" && name !== "fumbles";
    const title = grp.text || name.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase());
    return `<div class="tbl-wrap"><table class="box">
      <thead><tr><th class="l"><img src="${logo(abbr)}" alt=""> ${abbr} ${esc(title)}</th>${labels.map((l) => `<th>${esc(l)}</th>`).join("")}${withPts ? `<th class="ppr">PPR</th>` : ""}</tr></thead>
      <tbody>${grp.athletes.map((at) => {
        const pid = S.byKey[`${normName(at.athlete.displayName)}|${abbr}`];
        return `<tr ${pid && S.byId[pid].props.length ? `data-open="${pid}" class="click"` : ""}><td class="l">${esc(at.athlete.displayName)}</td>${(at.stats || []).map((v) => `<td>${esc(v)}</td>`).join("")}${withPts ? `<td class="ppr">${fmt(pprOf(at.athlete.displayName, abbr))}</td>` : ""}</tr>`;
      }).join("")}</tbody>
    </table></div>`;
  }).join("")).join("");

  // Fantasy leaders across both teams, kickers and defenses included
  const leaders = [];
  const seenIds = new Set();
  for (const [key, st2] of Object.entries(lines)) {
    const pid = S.byKey[key];
    const p = pid ? S.byId[pid] : null;
    if (p) seenIds.add(pid);
    const pts = p ? livePPR(p) : ppr(st2);
    if (pts) leaders.push({ name: p?.name || boxName(sum, key), team: key.split("|")[1], pos: p?.pos, pid, proj: p?.proj_ppr, pts, props: p?.props.length });
  }
  for (const p of S.data.players) {
    if (p.game_id !== g.id || seenIds.has(p.id) || !["K", "DEF"].includes(p.pos)) continue;
    const pts = livePPR(p);
    if (pts) leaders.push({ name: p.name, team: p.team, pos: p.pos, pid: p.id, proj: p.proj_ppr, pts, props: 0 });
  }
  leaders.sort((x, y) => y.pts - x.pts);
  const leaderCard = `<div class="card"><div class="cat-h" style="margin-bottom:6px"><span>Fantasy leaders (PPR)</span><span class="muted" style="font-weight:500;font-size:12px">both teams</span></div>
    ${leaders.slice(0, 12).map((x, i) => `<div class="fl" ${x.props ? `data-open="${x.pid}"` : ""}>
      <span><span class="muted num">${i + 1}</span> ${esc(x.name)} <span class="muted">${x.team}${x.pos ? ` ${x.pos}` : ""}</span></span>
      <span>${x.proj != null ? `<span class="muted">proj ${fmt(x.proj)}</span> ` : ""}<b class="num">${fmt(x.pts)}</b></span></div>`).join("") || `<div class="note">No points yet.</div>`}
  </div>`;

  const teamToggle = seg("data-bteam", st.bteam, [...["away", "home"].map((sd) => [teams[sd].abbr, `<img src="${logo(teams[sd].abbr)}" alt="">${teams[sd].abbr}`]), ["", "Both"]], "Team");
  return `<div class="box-grid"><div class="card team-stats">
      <div class="tsr head"><span><img src="${logo(teams.away.abbr)}" alt=""> ${teams.away.abbr}</span><span class="lbl">Team stats</span><span>${teams.home.abbr} <img src="${logo(teams.home.abbr)}" alt=""></span></div>
      ${teamRows || `<div class="note">No team stats yet.</div>`}
    </div>${leaderCard}</div>
    <div class="gtool">${teamToggle}${seg("data-box", st.box, BOX_SECTIONS.map(([k, l]) => [k, l]), "Section")}</div>
    ${tables || `<div class="empty">Nothing here yet.</div>`}`;
}

// ---- props in this game

function renderGameProps(g, teams) {
  const st = gs(g.id);
  let list = S.data.players.filter((p) => p.game_id === g.id && p.props.length
    && (!st.team || p.team === st.team) && (st.pos === "ALL" || p.pos === st.pos)
    && (!st.leans || p.props.some((x) => x.lean && x.line_from !== "ours")));
  const leanSize = (p) => Math.max(0, ...p.props.filter((x) => x.lean && x.adj != null).map((x) => Math.abs(x.adj - x.line) / Math.max(1, x.line)));
  const key = { proj: (p) => -(p.proj_ppr ?? -1), live: (p) => -(livePPR(p) ?? -1), lean: (p) => -leanSize(p) }[st.sort];
  list = list.sort((a, b) => key(a) - key(b));
  const picks = [...S.data.picks.over, ...S.data.picks.under].filter((x) => x.game_id === g.id);
  return `<div class="gtool">
      ${teamSeg(teams, st.team)}
      ${seg("data-gpos", st.pos, ["ALL", "QB", "RB", "WR", "TE"].map((x) => [x, x === "ALL" ? "All" : x]), "Position")}
      ${seg("data-gsort", st.sort, [["proj", "Projected"], ["live", "Live pts"], ["lean", "Biggest lean"]], "Sort")}
      <button class="tbtn ${st.leans ? "on" : ""}" data-gleans aria-pressed="${st.leans}">Leans only</button>
    </div>
    ${picks.length ? `<div class="picks game-picks"><h3>Top picks in this game</h3>${picks.map(pickCard).join("")}</div>` : ""}
    <div class="gcount">${list.length} players</div>
    <div class="plist">${list.map(playerCard).join("") || `<div class="empty">No players match.</div>`}</div>`;
}

// ---- fantasy in this game

function renderGameFantasy(g, teams) {
  const st = gs(g.id);
  const started = g.state !== "pre";
  const rows = S.data.players.filter((p) => p.game_id === g.id && (!st.team || p.team === st.team) && (st.pos === "ALL" || p.pos === st.pos))
    .map((p) => ({ p, proj: p.proj_ppr, live: livePPR(p) }))
    .filter((r) => (r.proj ?? 0) >= 0.5 || (r.live ?? 0) !== 0)
    .sort((a, b) => (started ? (b.live ?? -99) - (a.live ?? -99) : 0) || (b.proj ?? -1) - (a.proj ?? -1));
  return `<div class="gtool">
      ${teamSeg(teams, st.team)}
      ${seg("data-gpos", st.pos, ["ALL", "QB", "RB", "WR", "TE", "K", "DEF"].map((x) => [x, x === "ALL" ? "All" : x]), "Position")}
    </div>
    <div class="tbl-wrap"><table class="tbl">
      <thead><tr><th class="l">Player</th><th>Proj</th><th>${g.state === "post" ? "Final" : "Live"}</th><th>+/-</th></tr></thead>
      <tbody>${rows.map(({ p, proj, live }) => {
        const diff = live != null && proj != null ? live - proj : null;
        return `<tr ${p.props.length ? `data-open="${p.id}" class="click"` : ""}>
          <td class="l"><div class="who">${avatar(p)}<div><div><b>${esc(p.name)}</b>${injBadge(p)}</div><div class="pmeta"><span class="pos ${p.pos}">${p.pos}</span> ${p.team}</div></div></div></td>
          <td class="big">${fmt(proj)}</td>
          <td class="big" style="color:var(--cyan)">${started ? (current(p)?.none ? "DNP" : fmt(live)) : "-"}</td>
          <td class="${diff > 0 ? "up" : diff < 0 ? "down" : ""}">${diff == null ? "-" : (diff > 0 ? "+" : "") + fmt(diff)}</td>
        </tr>`;
      }).join("") || `<tr><td class="l" colspan="4">No players match.</td></tr>`}</tbody>
    </table></div>`;
}

// ---- the page

function renderGame() {
  const g = S.games[S.gameView];
  const sum = S.sum[g.id];
  const teams = gameTeams(g);
  const st = gs(g.id);
  const started = g.state !== "pre";
  const side = (key) => {
    const t = teams[key];
    const score = g[`${key}_score`];
    const other = g[`${key === "home" ? "away" : "home"}_score`];
    return `<div class="gt ${key}">
      <img src="${logo(t.abbr)}" alt="">
      <div class="gt-n"><b class="long">${esc(t.short)}</b><b class="abbr">${t.abbr}</b><span class="muted">${esc(t.record)}</span></div>
      <div class="gt-s num ${g.state === "post" && score < other ? "lose" : ""}">${started && score != null ? score : ""}${g.state === "in" && g.poss === t.abbr ? `<i class="poss-dot"></i>` : ""}</div>
    </div>`;
  };
  const lastDrive = allDrives(sum).slice(-1)[0];
  const lastPlay = g.state === "in" ? lastDrive?.plays?.slice(-1)[0] : null;
  const order = gamesInOrder();
  const i = order.findIndex((x) => x.id === g.id);
  const prev = order[i - 1], next = order[i + 1];
  const nPlays = allDrives(sum).reduce((a, d) => a + (d.plays?.length || 0), 0);
  const nProps = S.data.players.filter((p) => p.game_id === g.id && p.props.length).length;
  const badge = { plays: started && nPlays ? nPlays : "", props: nProps || "", box: "", fantasy: "" };
  const body = { plays: () => renderPlays(g, sum, teams), box: () => renderBox(g, sum, teams), props: () => renderGameProps(g, teams), fantasy: () => renderGameFantasy(g, teams) }[st.tab]();

  $("#main").innerHTML = `
    <div class="gnav">
      <button class="back" data-back>← All games</button>
      <div class="gnav-r">
        <button class="tbtn" data-game="${prev?.id || ""}" ${prev ? "" : "disabled"} title="Previous game ([)">‹ ${prev ? `${prev.away} @ ${prev.home}` : ""}</button>
        <button class="tbtn" data-game="${next?.id || ""}" ${next ? "" : "disabled"} title="Next game (])">${next ? `${next.away} @ ${next.home}` : ""} ›</button>
      </div>
    </div>
    <div class="card game-head">
      <div class="gh">${side("away")}
        <div class="gh-mid">
          <div class="gh-st ${g.state === "in" ? "live" : ""}">${esc(gameStatus(g))}</div>
          <div class="muted">${esc(g.state === "in" ? g.dd || "" : g.state === "pre" ? [g.tv, g.venue].filter(Boolean).join(" · ") : g.venue || "")}</div>
        </div>
        ${side("home")}</div>
      ${fieldView(g, teams, sum)}
      ${lastPlay ? `<div class="last-play"><span class="muted">Last play</span> ${esc(lastPlay.text || "")}</div>` : ""}
      ${linescore(sum, teams)}
      ${winProb(sum, teams)}
    </div>
    <nav class="gtabs" role="tablist" aria-label="Game sections">
      ${GAME_TABS.map(([k, l]) => `<button role="tab" aria-selected="${st.tab === k}" class="${st.tab === k ? "on" : ""}" data-gsub="${k}">
        ${l}${k === "plays" && g.state === "in" ? `<i class="ldot" title="Live"></i>` : ""}${badge[k] !== "" ? `<span class="gbadge">${badge[k]}</span>` : ""}</button>`).join("")}
      ${g.state === "in" ? `<span class="gtabs-note">updates every 15s</span>` : ""}
    </nav>
    <div class="gbody" role="tabpanel">${body}</div>`;
  // Plays drawn now count as seen; anything that shows up on a later refresh gets highlighted once
  const ids = allDrives(sum).flatMap((d) => (d.plays || []).map((pl) => pl.id));
  if (ids.length) S.seenPlays[g.id] = new Set(ids);
}

// Switch a game's tab, keeping the tab bar in view if the page was scrolled past it
function setGameTab(tab) {
  if (!S.gameView || !GAME_TABS.some(([k]) => k === tab)) return;
  gs().tab = tab;
  renderGame();
  syncHash(false);
  const bar = $(".gtabs");
  if (bar) {
    const top = bar.getBoundingClientRect().top + window.scrollY - (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--top-h")) || 0);
    if (window.scrollY > top) window.scrollTo(0, top);
  }
}

function stepGameTab(dir) {
  const k = GAME_TABS.findIndex(([t]) => t === gs().tab);
  setGameTab(GAME_TABS[(k + dir + GAME_TABS.length) % GAME_TABS.length][0]);
  $(".gtabs button.on")?.focus({ preventScroll: true });
}

function openGame(id, push = true) {
  if (!S.games[id]) return;
  S.gameView = id;
  delete S.seenPlays[id];
  S.openDrives.clear();
  gs(id);
  render();
  syncHash(push);
  window.scrollTo(0, 0);
  gameTick();
}

// ---- links: #/props, #/fantasy, #/record, #/about, #/game/<id>/<tab>

function hashNow() {
  return S.gameView ? `#/game/${S.gameView}/${gs().tab}` : `#/${S.tab}`;
}

function syncHash(push) {
  const h = hashNow();
  if (location.hash === h) return;
  try { push ? history.pushState(null, "", h) : history.replaceState(null, "", h); } catch { /* file:// or sandboxed */ }
}

function applyHash() {
  const m = location.hash.match(/^#\/game\/(\d+)(?:\/(\w+))?/);
  if (m && S.games[m[1]]) {
    S.gameView = m[1];
    if (m[2] && GAME_TABS.some(([k]) => k === m[2])) gs().tab = m[2];
    return true;
  }
  const t = location.hash.match(/^#\/(props|fantasy|record|about)$/);
  if (t) { S.gameView = null; S.tab = t[1]; return true; }
  return false;
}

window.addEventListener("popstate", () => {
  if (!S.data) return;
  if (!applyHash()) S.gameView = null;
  render();
  if (S.gameView) gameTick();
});

document.addEventListener("keydown", (e) => {
  if (!S.gameView || e.metaKey || e.ctrlKey || e.altKey || e.target.closest?.("input,select,textarea")) return;
  if (e.key === "Escape") { S.gameView = null; render(); syncHash(true); window.scrollTo(0, 0); }
  else if (e.key === "ArrowRight") { e.preventDefault(); stepGameTab(1); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); stepGameTab(-1); }
  else if (e.key === "]" || e.key === "[") {
    const order = gamesInOrder();
    const next = order[order.findIndex((x) => x.id === S.gameView) + (e.key === "]" ? 1 : -1)];
    if (next) openGame(next.id);
  }
});

// Swipe left or right on a game page to change tabs (not inside things that scroll sideways)
let swipe = null;
document.addEventListener("touchstart", (e) => {
  if (!S.gameView || e.touches.length !== 1 || e.target.closest(".tbl-wrap,.strip,.props-row,.gtool,.field,.gtabs")) { swipe = null; return; }
  swipe = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() };
}, { passive: true });
document.addEventListener("touchend", (e) => {
  if (!swipe || !S.gameView) return;
  const dx = e.changedTouches[0].clientX - swipe.x, dy = e.changedTouches[0].clientY - swipe.y;
  if (Math.abs(dx) > 70 && Math.abs(dy) < 45 && Date.now() - swipe.t < 600) stepGameTab(dx < 0 ? 1 : -1);
  swipe = null;
}, { passive: true });

function setTopHeight() {
  document.documentElement.style.setProperty("--top-h", `${$(".top")?.offsetHeight || 0}px`);
}
window.addEventListener("resize", setTopHeight);

// ---------------------------------------------------------------- render and events

function render() {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", !S.gameView && b.dataset.tab === S.tab));
  if (S.gameView) { renderGame(); renderScores(); return; }
  ({ props: renderProps, fantasy: renderFantasy, record: renderRecord, about: renderAbout })[S.tab]();
  renderScores();
}

// Live ticks update numbers in place, so open cards, focus and scroll position survive
function renderLiveParts() {
  if (S.gameView) {
    if (document.activeElement?.matches("input,select")) return;
    const y = window.scrollY;
    renderGame();
    window.scrollTo(0, y);
    return;
  }
  if (S.tab === "fantasy") return renderFantasy();
  if (S.tab !== "props") return;
  const active = document.activeElement;
  if (active && active.matches("input,select")) {
    // Don't redraw while someone is typing; just refresh the numbers that don't hold focus
    document.querySelectorAll("[data-chips]").forEach((el) => {
      const p = S.byId[el.dataset.chips];
      el.innerHTML = p.props.filter((x) => !S.f.cat || x.key === S.f.cat).map((x) => propChip(p, x)).join("");
    });
    return;
  }
  const y = window.scrollY;
  renderProps();
  window.scrollTo(0, y);
}

document.addEventListener("click", (e) => {
  const t = e.target;
  const tab = t.closest(".tabs button");
  if (tab) { S.tab = tab.dataset.tab; S.gameView = null; store("tab", S.tab); render(); syncHash(true); window.scrollTo(0, 0); return; }
  if (t.closest("[data-back]")) { S.gameView = null; render(); syncHash(true); window.scrollTo(0, 0); return; }
  const gsub = t.closest("[data-gsub]");
  if (gsub) { setGameTab(gsub.dataset.gsub); return; }
  // game page toolbars
  for (const [attr, field] of [["data-pbp", "pbp"], ["data-gteam", "team"], ["data-order", "order"], ["data-box", "box"], ["data-bteam", "bteam"], ["data-gpos", "pos"], ["data-gsort", "sort"]]) {
    const el = t.closest(`[${attr}]`);
    if (el && S.gameView) { gs()[field] = el.getAttribute(attr); renderGame(); return; }
  }
  if (t.closest("[data-gleans]") && S.gameView) { gs().leans = !gs().leans; renderGame(); return; }
  const drivesAll = t.closest("[data-drives]");
  if (drivesAll && S.gameView) { gs().drives = drivesAll.dataset.drives; S.openDrives.clear(); renderGame(); return; }
  const drive = t.closest("[data-drive]");
  if (drive) {
    const id = drive.dataset.drive;
    S.openDrives.has(id) ? S.openDrives.delete(id) : S.openDrives.add(id);
    renderGame();
    return;
  }
  const go = t.closest("[data-goto]");
  if (go) { e.preventDefault(); S.tab = go.dataset.goto; render(); window.scrollTo(0, 0); return; }
  const fav = t.closest("[data-fav]");
  if (fav) {
    const id = fav.dataset.fav;
    S.favs.has(id) ? S.favs.delete(id) : S.favs.add(id);
    store("favs", [...S.favs]);
    render();
    return;
  }
  const game = t.closest("[data-game]");
  if (game) {
    const id = game.dataset.game;
    if (!id) return;
    if (S.gameView === id && game.closest(".strip")) { S.gameView = null; render(); syncHash(true); return; }
    openGame(id);
    return;
  }
  const pos = t.closest("[data-pos]");
  if (pos) { S.f.pos = pos.dataset.pos; S.shown = 40; renderProps(); return; }
  const fpos = t.closest("[data-fpos]");
  if (fpos) { S.ff.pos = fpos.dataset.fpos; S.ff.shown = 60; renderFantasy(); return; }
  const sort = t.closest("[data-sort]");
  if (sort) {
    const k = sort.dataset.sort;
    if (S.ff.sort === k) S.ff.desc = !S.ff.desc; else { S.ff.sort = k; S.ff.desc = k !== "name"; }
    renderFantasy();
    return;
  }
  if (t.closest("[data-more]")) { S.shown += 40; renderLiveParts(); return; }
  if (t.closest("[data-fmore]")) { S.ff.shown += 60; renderFantasy(); return; }
  const openEl = t.closest("[data-open]");
  if (openEl) {
    // From a pick card or the fantasy table: show that player's full card on the Props tab
    const p = S.byId[openEl.dataset.open];
    if (S.gameView && p.game_id === S.gameView && p.props.length) {
      const st = gs();
      Object.assign(st, { tab: "props", leans: false, pos: "ALL", team: "" });
      S.open.add(p.id);
      renderGame();
      syncHash(false);
      $(`[data-player="${p.id}"]`)?.scrollIntoView({ block: "center" });
      return;
    }
    S.tab = "props";
    S.gameView = null;
    S.f = { ...S.f, pos: "ALL", game: "", cat: "", q: p.name, favs: false, hideOut: false };
    S.open.add(p.id);
    render();
    $(`[data-player="${p.id}"]`)?.scrollIntoView({ block: "center" });
    return;
  }
  const toggle = t.closest("[data-toggle]");
  if (toggle && !t.closest("input")) {
    const id = toggle.dataset.toggle;
    S.open.has(id) ? S.open.delete(id) : S.open.add(id);
    const card = $(`[data-player="${id}"]`);
    card.outerHTML = playerCard(S.byId[id]);
    return;
  }
  if (t.closest("[data-chips]")) {
    const id = t.closest("[data-chips]").dataset.chips;
    S.open.add(id);
    $(`[data-player="${id}"]`).outerHTML = playerCard(S.byId[id]);
  }
});

document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.id === "f-q") {
    S.f.q = t.value;
    S.shown = 40;
    const pos = t.selectionStart;
    renderProps();
    const box = $("#f-q");
    box.focus();
    box.setSelectionRange(pos, pos);
    return;
  }
  if (t.dataset.line) {
    const v = parseFloat(t.value);
    if (Number.isNaN(v)) return;
    S.lines[t.dataset.line] = v;
    const [pid, key] = t.dataset.line.split("|");
    const p = S.byId[pid];
    const pos = t.selectionStart;
    $(`[data-cat="${CSS.escape(t.dataset.line)}"]`).outerHTML = catCard(p, p.props.find((x) => x.key === key));
    $(`[data-chips="${pid}"]`).innerHTML = p.props.filter((x) => !S.f.cat || x.key === S.f.cat).map((x) => propChip(p, x)).join("");
    const box = $(`[data-line="${CSS.escape(t.dataset.line)}"]`);
    box.focus();
    try { box.setSelectionRange(pos, pos); } catch { /* number inputs don't support selection */ }
  }
});

document.addEventListener("change", (e) => {
  const t = e.target;
  const set = { "f-game": "game", "f-cat": "cat", "f-sort": "sort" }[t.id];
  if (set) { S.f[set] = t.value; S.shown = 40; render(); return; }
  if (t.id === "f-out") { S.f.hideOut = t.checked; renderProps(); return; }
  if (t.id === "f-favs") { S.f.favs = t.checked; renderProps(); }
});

$("#made-by").addEventListener("click", (e) => {
  e.preventDefault();
  S.tab = "about";
  S.gameView = null;
  render();
  $("#maker")?.scrollIntoView({ block: "start" });
});

$("#reload").addEventListener("click", async () => {
  $("#banner").hidden = true;
  await load();
  render();
  liveTick();
});

(async function start() {
  const saved = store("tab");
  if (["props", "fantasy", "record", "about"].includes(saved)) S.tab = saved;
  try {
    await load();
  } catch (err) {
    $("#main").innerHTML = `<div class="empty">Couldn't load this week's data. Try refreshing.</div>`;
    console.error(err);
    return;
  }
  applyHash();
  setTopHeight();
  render();
  syncHash(false);
  liveTick();
  if (S.gameView) gameTick();
  setInterval(() => { if (!document.hidden) checkMeta(); }, META_MS);
})();
