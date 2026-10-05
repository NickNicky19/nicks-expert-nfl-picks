"use strict";

// Live data comes straight from ESPN in the browser (the hourly build can't keep up with a game in progress).
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl";
// The site's small server (Cloudflare Worker, worker/ in the repo): Yahoo sign-in and the AI chat. Empty until it's
// deployed; those features stay hidden without it. localStorage "nflprops.worker" overrides it for testing.
const WORKER_URL = (() => { try { return JSON.parse(localStorage.getItem("nflprops.worker")) || ""; } catch { return ""; } })() || "https://expert-nfl-picks.joshuamoy.workers.dev";
const ESPN_TO_SLEEPER = { WSH: "WAS" };
const LIVE_MS = 30000;   // scores and box scores while a game is on
const IDLE_MS = 300000;  // scores when nothing is live
const GAME_MS = 8000;    // play-by-play for the game that's open
const META_MS = 60000;   // checks for a new build
const UNAVAILABLE = new Set(["Out", "IR", "PUP", "Suspended", "NA", "Doubtful", "COV", "DNR"]);
const SHORT = {
  pass_yd: "Pass Yds", pass_td: "Pass TD", pass_cmp: "Comp", pass_att: "Pass Att", pass_int: "INT",
  rush_yd: "Rush Yds", rush_att: "Rush Att", rec: "Rec", rec_yd: "Rec Yds", rush_rec_yd: "Rush+Rec",
  anytime_td: "Anytime TD", fpts: "Fantasy Pts",
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
  slp: {},             // player id -> Sleeper live stats
  liveOdds: {},        // game id -> DraftKings live spread, total and moneylines
  news: null, newsAt: 0, newsView: "headlines", newsMine: false,
  pnews: {},           // player id -> notes and headlines loaded from ESPN
  slpOk: false,
  injNews: {},         // player id -> injury news from ESPN newer than our build
  injAt: {},           // game id -> when its pregame injury news was last checked
  seenPlays: {},       // game id -> play ids already shown
  openDrives: new Set(),
  gs: {},              // game id -> that game page's tab and filters
  viewWeek: null,      // a finished week shown in the scores bar (null = this week)
  weeks: {},           // week -> that finished week's data (data/weeks/)
  pastGames: {},       // game id -> a game from a finished week
  favs: new Set(store("favs") || []),
  // Scoring for QB/RB/WR/TE: a preset (Sleeper or ESPN, PPR or half) or a saved Sleeper league's exact settings.
  // Kickers and defenses always use ESPN standard scoring.
  sc: store("scoring") || { mode: "sleeper", half: store("half") === true },
  leagues: store("leagues") || [],      // [{id, name, season, settings}]
  scFound: null, scMsg: "",
  mine: store("mine") || [],
  cmp: store("cmp") || [null, null],    // the two players on the Compare tab
  trade: store("trade") || { give: [], get: [] },
  yahoo: store("yahoo") || null,       // Yahoo tokens (from the Worker's sign-in)
  chat: [], chatBusy: false,
  sync: store("sync") || null,         // the synced Sleeper league: {league_id, user_id, roster_id, name}
  leagueData: null, ideas: null, syncMsg: "", syncFound: null, syncUser: null,   // My Picks: [{pid, key, dir, line, season, week, at}]
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
// Fantasy points to the hundredth, like Sleeper and ESPN
const fmtPts = (v) => fmt(v, 2);
const fmtStat = (key, v) => (v == null ? "-" : key.endsWith("_yd") || key === "fpts" ? fmt(v, key === "fpts" ? 2 : 0) : fmt(v, Number.isInteger(v) ? 0 : 1));
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
  if (key === "fpts") return fantasyPts(s, "WR");
  return s[key] || 0;
}

function kickoffText(iso) {
  const d = new Date(iso);
  const day = d.toLocaleDateString(undefined, { weekday: "short" });
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${day} ${time}`;
}

function gameStatus(g) {
  if (!g) return "Not playing this week";
  if (g.state === "pre") return kickoffText(g.kickoff);
  return g.detail || (g.state === "post" ? "Final" : "Live");
}

// ---------------------------------------------------------------- live data

// A player's stat line this week: ESPN's live box score first, then Sleeper's (from the last build).
// null before kickoff. {none: true} when the game is final and the player never showed up in the box score.
// Live stats: Sleeper's own feed first (what the Sleeper app shows), then ESPN's box score, then the last build.
function current(p) {
  const g = S.games[p.game_id];
  if (!g || g.state === "pre") return null;
  const slp = S.slp[p.id];
  const stats = (slp && slpPlayed(slp) ? slp : null) || S.live[p.id] || p.actual?.stats;
  if (stats) return { stats, none: false };
  if (g.state === "post" && (S.slpOk || S.boxLoaded.has(p.game_id))) return { stats: {}, none: true };
  return { stats: {}, none: false };
}

function slpPlayed(s) {
  return (s.gp || 0) > 0 || (s.off_snp || 0) > 0 || s.pts_ppr != null;
}

function livePPR(p) {
  const c = current(p);
  return c && !c.none ? fantasyPts(c.stats, p.pos) : null;
}

// Same as fantasy_points() in pull/scoring.py: Sleeper PPR or half PPR for skill players, ESPN standard for K and DEF
function fantasyPts(s, pos) {
  const table = (t, x = s) => Object.entries(t).reduce((a, [k, w]) => a + w * (x[k] || 0), 0);
  const tier = (v, tiers) => tiers.find(([most]) => v <= most)[1];
  if (pos === "K") {
    const k = { ...s };
    // Sleeper reports one of the 50-59 / 60+ splits; derive the other (projections have neither: 50-59)
    const fifty = k.fgm_50p || 0;
    if (k.fgm_60p == null) k.fgm_60p = k.fgm_50_59 != null ? fifty - k.fgm_50_59 : 0;
    if (k.fgm_50_59 == null) k.fgm_50_59 = Math.max(0, fifty - k.fgm_60p);
    return Math.round((ppr(s) + table(S.data.scoring_k, k)) * 100) / 100;
  }
  if (pos === "DEF") {
    return Math.round((table(S.data.scoring_def) + tier(s.pts_allow || 0, S.data.def_tiers.pts) + tier(s.yds_allow || 0, S.data.def_tiers.yds)) * 100) / 100;
  }
  return skillPts(s, pos);
}

function currentLeague() {
  return S.sc.mode === "league" ? S.leagues.find((l) => l.id === S.sc.league) : null;
}

// QB/RB/WR/TE points in the chosen scoring
function skillPts(s, pos) {
  const lg = currentLeague();
  if (lg) return scoreWith(lg.settings, s, pos);
  let t = ppr(s);
  if (S.sc.mode === "espn") t -= s.pass_int || 0;          // ESPN takes 2 per interception, Sleeper 1
  if (S.sc.half) t -= 0.5 * (s.rec || 0);
  return Math.round(t * 100) / 100;
}

// Score a stat line with Sleeper league settings: each setting's weight times the matching stat. Bonuses Sleeper
// keeps as their own stats (TE premium, 100-yard games and so on) are derived from the base stats when missing.
function scoreWith(w, s, pos) {
  let t = 0;
  for (const [k, v] of Object.entries(w || {})) {
    if (!v) continue;
    const x = s[k] != null ? s[k] : derivedStat(k, s, pos);
    if (x) t += v * x;
  }
  return Math.round(t * 100) / 100;
}

function derivedStat(k, s, pos) {
  let m = k.match(/^bonus_rec_(te|rb|wr|qb)$/);
  if (m) return (pos || "").toLowerCase() === m[1] ? s.rec || 0 : 0;
  m = k.match(/^bonus_(pass|rush|rec)_yd_(\d+)$/);
  if (m) return (s[`${m[1]}_yd`] || 0) >= +m[2] ? 1 : 0;
  m = k.match(/^bonus_rush_rec_yd_(\d+)$/);
  if (m) return (s.rush_yd || 0) + (s.rec_yd || 0) >= +m[1] ? 1 : 0;
  if (k === "bonus_pass_cmp_25") return (s.pass_cmp || 0) >= 25 ? 1 : 0;
  if (k === "bonus_rush_att_20") return (s.rush_att || 0) >= 20 ? 1 : 0;
  return 0;
}

const isDefault = () => S.sc.mode === "sleeper";

function projPts(p) {
  if (p.pos === "K" || p.pos === "DEF") return p.proj_ppr;
  if (isDefault()) return S.sc.half ? p.proj_half ?? p.proj_ppr : p.proj_ppr;
  return p.proj && Object.keys(p.proj).length ? skillPts(p.proj, p.pos) : null;
}

function logPts(p, x) {
  if (isDefault()) return S.sc.half ? x.h : x.pts;
  return x.st ? skillPts(x.st, p.pos) : null;
}

function avgPts(p) {
  if (p.pos === "K" || p.pos === "DEF") return p.avg_ppr;
  if (isDefault()) return S.sc.half ? p.avg_half ?? p.avg_ppr : p.avg_ppr;
  const pts = (p.log || []).map((x) => logPts(p, x)).filter((v) => v != null);
  return pts.length ? Math.round((pts.reduce((a, b) => a + b, 0) / pts.length) * 100) / 100 : null;
}

function scoringName() {
  const lg = currentLeague();
  if (lg) return lg.name;
  return `${S.sc.mode === "espn" ? "ESPN" : "Sleeper"} ${S.sc.half ? "Half PPR" : "PPR"}`;
}

// The fantasy points prop in the current scoring (half PPR swaps in its own numbers)
function pv(p, prop) {
  if (prop.key !== "fpts" || (isDefault() && !S.sc.half)) return prop;
  if (isDefault()) return prop.adj_h == null ? prop : { ...prop, line: prop.line_h, adj: prop.adj_h, proj: prop.proj_h, over: prop.over_h, values: prop.values.map((x) => ({ ...x, v: x.h ?? x.v })) };
  // Any other scoring: re-score his games and his projection, keep the matchup adjustment
  const byWeek = Object.fromEntries((p.log || []).map((x) => [x.w, x]));
  const values = prop.values.map((x) => { const g = byWeek[x.w]; const v = g ? logPts(p, g) : null; return { ...x, v: v ?? x.v }; });
  const proj = projPts(p);
  const adj = proj != null ? Math.round(proj * (prop.mf ?? 1) * 100) / 100 : prop.adj;
  const line = adj != null ? Math.floor(adj) + 0.5 : prop.line;
  return { ...prop, values, proj, adj, line, over: values.filter((x) => x.v > line).length };
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
      period: e.status.period, clockSec: e.status.clock,
      // timeouts (3 per half), the current drive and the ball spot, straight from ESPN's scoreboard
      homeTO: e.status.type.state === "in" ? sit.homeTimeouts ?? null : null,
      awayTO: e.status.type.state === "in" ? sit.awayTimeouts ?? null : null,
      drive: e.status.type.state === "in" ? sit.lastPlay?.drive?.description || "" : "",
      lastPlay: e.status.type.state === "in" && sit.lastPlay?.id ? {
        id: sit.lastPlay.id, text: sit.lastPlay.text, type: sit.lastPlay.type, scoreValue: sit.lastPlay.scoreValue,
        scoringPlay: (sit.lastPlay.scoreValue || 0) > 0, statYardage: sit.lastPlay.statYardage, start: sit.lastPlay.start, end: sit.lastPlay.end,
        period: { number: e.status.period }, clock: { displayValue: e.status.displayClock },
        homeScore: home.score === "" ? null : +home.score, awayScore: away.score === "" ? null : +away.score,
      } : null,
      spot: e.status.type.state === "in" && sit.yardLine != null ? { yardLine: sit.yardLine, down: sit.down, distance: sit.distance, text: sit.downDistanceText, team: sit.possession } : null,
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
      const d = await getJSON(`${CORE}/events/${id}/competitions/${id}/odds`);
      const it = (d.items || []).find((x) => x.provider?.id === "200");
      if (it && it.spread != null) S.liveOdds[id] = { spread: +it.spread, total: it.overUnder, ml_home: it.homeTeamOdds?.moneyLine, ml_away: it.awayTeamOdds?.moneyLine };
    } catch { /* live odds are optional */ }
  }));
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

// Every player's live stats in one small request (about 90 KB), keyed by Sleeper id
async function pollSleeper() {
  if (!Object.values(S.games).some((g) => g.state !== "pre")) return;
  const pos = ["QB", "RB", "WR", "TE", "K", "DEF"].map((x) => `position[]=${x}`).join("&");
  try {
    const rows = await getJSON(`https://api.sleeper.app/stats/nfl/${S.data.season}/${S.data.week}?season_type=regular&${pos}`);
    const next = {};
    for (const r of rows || []) if (S.byId[r.player_id] && r.stats) next[r.player_id] = r.stats;
    S.slp = next;
    S.slpOk = true;
  } catch (err) {
    S.slpOk = false;   // fall back to ESPN box scores for every live game
    console.warn("sleeper live", err);
  }
}

// ESPN game summaries: the open game is handled by gameTick. Here: pregame injury news for games kicking off
// soon, and box scores for live games only when Sleeper's feed is down.
async function pollBoxScores() {
  const now = Date.now();
  const soon = (g) => g.state === "pre" && new Date(g.kickoff) - now < 4 * 3600000 && now - (S.injAt[g.id] || 0) > 300000;
  const backup = (g) => !S.slpOk && (g.state === "in" || (g.state === "post" && !S.boxFinal.has(g.id)));
  const ids = Object.values(S.games)
    .filter((g) => g.id !== S.gameView && (backup(g) || soon(g)))
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
  if (!S.games[id]) return;   // a finished week's game: its box score is drawn straight from the summary
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
// Everything live refreshes together, then the page redraws once, so the score, stats, plays and odds always agree
let ticking = false;
async function liveTick() {
  clearTimeout(liveTimer);
  if (ticking) return;
  ticking = true;
  try {
    await pollScores().catch((err) => console.warn("scores", err));
    await pollSleeper();     // first, so the ESPN backup only runs if Sleeper's feed is actually down
    const live = Object.values(S.games).filter((g) => g.state === "in").map((g) => g.id);
    await Promise.all([pollBoxScores(), pollOpenGame(), pollLiveLines(live)]);
    S.liveAt = new Date();
  } catch (err) {
    console.warn("live", err);
  }
  ticking = false;
  S.rosKey = null; S.gradeKey = null;     // games may have kicked off: recount rest-of-season points
  updateSub();
  renderScores();
  renderLiveParts();
  const anyLive = Object.values(S.games).some((g) => g.state === "in");
  const soon = Object.values(S.games).some((g) => g.state === "pre" && new Date(g.kickoff) - Date.now() < 10 * 60000);
  const watching = S.gameView && S.games[S.gameView]?.state === "in";
  if (!document.hidden) liveTimer = setTimeout(liveTick, watching ? GAME_MS : anyLive || soon ? LIVE_MS : IDLE_MS);
}

async function pollOpenGame() {
  const id = S.gameView;
  const g = id && gameOf(id);
  if (!g || g.state === "pre" || (g.state === "post" && S.sum[id])) return;
  try {
    applySummary(id, await getJSON(`${ESPN}/summary?event=${id}`));
    syncGameFromSummary(id);
  } catch (err) {
    console.warn("game", id, err);
  }
}

// Opening a game starts a fresh update right away (which then repeats every 15 seconds while it's live)
function gameTick() {
  // a finished week's game only needs its summary once; don't wait for the next live update
  if (S.pastGames[S.gameView] && !S.games[S.gameView]) { pollOpenGame().then(() => { if (S.gameView && S.sum[S.gameView]) renderGame(); }); return; }
  liveTick();
}

// Score and clock from the summary, so the open game is never behind its own play-by-play
function syncGameFromSummary(id) {
  const comp = S.sum[id]?.header?.competitions?.[0];
  if (!comp) return;
  const g = gameOf(id);
  const st = comp.status?.type;
  for (const c of comp.competitors || []) {
    if (c.score != null && c.score !== "") g[c.homeAway === "home" ? "home_score" : "away_score"] = +c.score;
  }
  if (st) Object.assign(g, { state: st.state, detail: st.shortDetail || g.detail });
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.data) { liveTick(); checkMeta(); }
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
  S.rosKey = null; S.gradeKey = null;
  S.future = null; S.futureLoading = null; S.ideas = null; S.teamWeeksMap = null; S.teamOppsMap = null;
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
  updateSub();
}

// Two clocks: live data (every 15 to 30 seconds) and the last rebuild of lines and projections (hourly)
function updateSub() {
  const t = (d, sec) => d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", ...(sec ? { second: "2-digit" } : {}) });
  const built = new Date(S.data.generated_at);
  const day = built.toDateString() === new Date().toDateString() ? "" : `${built.toLocaleDateString(undefined, { weekday: "short" })} `;
  $("#sub").innerHTML = `${S.data.season} Week ${S.data.week}`
    + (S.liveAt ? ` \u00b7 <span class="sub-live">live ${t(S.liveAt, true)}</span>` : "")
    + ` \u00b7 <span title="Lines, projections and injuries rebuild about every hour">lines ${day}${t(built)}</span>`;
}

// ---------------------------------------------------------------- score strip

function renderScores() {
  const pastWk = S.viewWeek && S.weeks[S.viewWeek];
  const games = pastWk ? pastWk.games.map((g) => S.pastGames[g.id]).sort((a, b) => a.kickoff.localeCompare(b.kickoff) || a.id.localeCompare(b.id))
    : Object.values(S.games).sort((a, b) => {
      const order = { in: 0, pre: 1, post: 2 };
      return order[a.state] - order[b.state] || a.kickoff.localeCompare(b.kickoff);
    });
  const anyLive = !pastWk && games.some((g) => g.state === "in");
  $("#live-dot").hidden = !anyLive;
  $("#scores-status").textContent = pastWk ? `Week ${S.viewWeek} \u00b7 final scores`
    : anyLive ? `Live${innerWidth < 560 ? "" : ` · updates every 30s${S.liveAt ? ` · ${S.liveAt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" })}` : ""}`}`
    : `Week ${S.data.week} \u00b7 scores`;
  renderWeekPick();
  $("#scores-status").insertAdjacentHTML("beforeend", `<span class="hide-sm"> \u00b7 tap a game for play-by-play</span>`);
  $("#strip").innerHTML = games.map((g) => {
    const live = g.state === "in";
    const started = g.state !== "pre";
    const row = (team, score, other) => `
      <div class="row ${g.state === "post" && score < other ? "lose" : ""}">
        <img src="${logo(team)}" alt="" loading="lazy"><span class="abbr ${live && g.poss === team ? "poss" : ""}">${team}${live ? toDots(team === g.home ? g.homeTO : g.awayTO) : ""}</span>
        <span class="sc">${started && score != null ? score : ""}</span>
      </div>`;
    return `<button class="game ${live ? "live" : ""} ${g.rz ? "rz" : ""} ${S.gameView === g.id ? "on" : ""}" data-game="${g.id}">
      ${row(g.away, g.away_score, g.home_score)}${row(g.home, g.home_score, g.away_score)}
      ${(() => { const n = S.sync ? (g.pastWeek ? pastRows(g) : S.data.players.filter((p) => p.game_id === g.id)).filter((p) => isMine(p.id)).length : 0; return n ? `<div class="yours-n">${n} of yours</div>` : ""; })()}
      <div class="st"><span class="clock">${esc(gameStatus(g))}</span><span class="dd">${esc(live ? g.dd || "" : g.state === "pre" ? shortLine(g) || g.tv || "" : dayShort(g.kickoff))}</span></div>
    </button>`;
  }).join("");
}

// ---------------------------------------------------------------- shared bits

// Share of the game still to play (0 to 1): regulation is four 15-minute quarters, overtime one 10-minute period
function remaining(g) {
  if (g.state === "pre") return 1;
  if (g.state !== "in" || g.period == null) return 0;
  const clock = g.clockSec ?? 0;
  if (g.period > 4) return Math.max(0, clock) / 3600;
  return Math.max(0, (4 - g.period) * 900 + clock) / 3600;
}

// Ours, live: the score so far plus what's left of our pregame projection for the time remaining
function oursLive(g) {
  const u = g.ours;
  if (!u || g.state !== "in" || g.home_score == null) return null;
  const r = remaining(g);
  const home = g.home_score + u.home_pts * r, away = g.away_score + u.away_pts * r;
  const sd = 13.5 * Math.sqrt(Math.max(r, 0.004));
  const z = (home - away) / sd;
  const pHome = 0.5 * (1 + erf(z / Math.SQRT2));
  return { home_pts: home, away_pts: away, spread: away - home, total: home + away, home_win: pHome };
}

function erf(x) {
  // Abramowitz and Stegun 7.1.26
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
}

const fairML = (p) => {
  p = Math.min(Math.max(p, 0.01), 0.99);
  if (Math.abs(p - 0.5) < 0.005) return 100;   // a true coin flip is +100 (even money) for both sides
  return Math.round(p > 0.5 ? (-100 * p) / (1 - p) : (100 * (1 - p)) / p);
};

// Timeouts left, as three dots (filled = still has it)
function toDots(n) {
  if (n == null) return "";
  return `<span class="to" title="${n} timeout${n === 1 ? "" : "s"} left">${[0, 1, 2].map((i) => `<i class="${i < n ? "on" : ""}"></i>`).join("")}</span>`;
}

// "DET -3.5 · 51.5"
function shortLine(g) {
  const o = g.odds;
  if (!o) return "";
  const fav = o.spread < 0 ? g.home : g.away;
  return `${o.spread === 0 ? "PK" : `${fav} -${Math.abs(o.spread)}`} \u00b7 ${o.total}`;
}

const ml = (v) => (v == null ? "-" : v > 0 ? `+${v}` : `${v}`);

// A moneyline's implied chance, and a pair of moneylines with the sportsbook's margin taken out
const impliedProb = (v) => (v == null ? null : v > 0 ? 100 / (v + 100) : -v / (-v + 100));
function noVig(mlA, mlB) {
  const a = impliedProb(mlA), b = impliedProb(mlB);
  return a == null || b == null ? [null, null] : [a / (a + b), b / (a + b)];
}

function gameLines(g, teams) {
  const o = g.odds, u = g.ours;
  if (!o && !u) return "";
  const H = teams.home.abbr, A = teams.away.abbr;
  const spreadText = (sp) => (sp == null ? "-" : Math.abs(sp) < 0.05 ? "Pick'em" : `${sp < 0 ? H : A} -${fmt(Math.abs(sp), Math.abs(sp) % 1 ? 1 : 0)}`);
  const pct = (p) => `${Math.round(100 * p)}%`;
  // two teams' chances always add up to 100: round the home team's, the away team gets the rest
  const pair = (pHome) => { const h = Math.round(100 * pHome); return [`${100 - h}%`, `${h}%`]; };
  const lvDK = g.state === "in" ? S.liveOdds[g.id] : null;
  const lvUs = oursLive(g);
  const row = (label, cls, sp, tot, mlText, pts) => `<tr class="${cls}"><th>${label}</th><td>${sp}</td><td>${tot}</td><td>${mlText}</td><td>${pts}</td></tr>`;
  const rows = [];
  const dkML = (mA, mH) => { const [pa, ph] = noVig(mA, mH); const [ta, th] = ph != null ? pair(ph) : ["", ""]; return `${A} ${pa != null ? `${ta} ` : ""}(${ml(mA)}) \u00b7 ${H} ${ph != null ? `${th} ` : ""}(${ml(mH)})`; };
  if (o) rows.push(row("DraftKings", "dk", spreadText(o.spread) + (o.spread_open != null && o.spread_open !== o.spread ? `<span class="opened">opened ${spreadText(o.spread_open)}</span>` : ""),
    o.total, dkML(o.ml_away, o.ml_home), `${A} ${o.away_pts} \u00b7 ${H} ${o.home_pts}`));
  if (u) rows.push(row("Ours", "ours", spreadText(u.spread), fmt(u.total),
    `${A} ${pair(u.home_win)[0]} (${ml(u.ml_away)}) \u00b7 ${H} ${pair(u.home_win)[1]} (${ml(u.ml_home)})`, `${A} ${fmt(u.away_pts)} \u00b7 ${H} ${fmt(u.home_pts)}`));
  const live = [];
  if (lvDK) live.push(row("DraftKings", "dk live", spreadText(lvDK.spread), lvDK.total ?? "-", dkML(lvDK.ml_away, lvDK.ml_home), "-"));
  if (lvUs) live.push(row("Ours", "ours live", spreadText(lvUs.spread), fmt(lvUs.total),
    `${A} ${pair(lvUs.home_win)[0]} (${ml(fairML(1 - lvUs.home_win))}) \u00b7 ${H} ${pair(lvUs.home_win)[1]} (${ml(fairML(lvUs.home_win))})`,
    `${A} ${fmt(lvUs.away_pts)} \u00b7 ${H} ${fmt(lvUs.home_pts)}`));
  // + buttons: add DraftKings' pregame spread, total or moneyline to My Picks
  const gb = (market, side, line, odds, text) => {
    const on = !!mineGame(g.id, market, side);
    return `<button class="add gadd ${on ? "on" : ""}" data-gadd="${g.id}|${market}|${side}|${line ?? ""}|${odds ?? ""}" title="${on ? "Remove from" : "Add to"} My Picks">${on ? "✓" : "+"} ${text}</button>`;
  };
  const sgn = (x) => (x > 0 ? `+${x}` : `${x}`);
  const addRow = o && !g.pastWeek ? `<div class="gl-add">
      <span class="muted">Add to My Picks (change to an alternate line there):</span>
      ${gb("spread", A, -o.spread, null, `${A} ${sgn(-o.spread)}`)}${gb("spread", H, o.spread, null, `${H} ${sgn(o.spread)}`)}
      ${gb("total", "over", o.total, null, `Over ${o.total}`)}${gb("total", "under", o.total, null, `Under ${o.total}`)}
      ${gb("ml", A, null, o.ml_away, `${A} ${ml(o.ml_away)}`)}${gb("ml", H, null, o.ml_home, `${H} ${ml(o.ml_home)}`)}
    </div>` : "";
  const spreadLean = u?.lean_spread && o ? `${u.lean_spread} ${u.lean_spread === H ? (o.spread > 0 ? "+" : "") + o.spread : (o.spread < 0 ? "+" : "") + -o.spread}` : null;
  const leans = [spreadLean, u?.lean_total ? `${u.lean_total} ${o.total}` : null].filter(Boolean);
  return `<div class="glines2">
    <div class="tbl-wrap"><table class="gltab">
      <thead><tr><th></th><th>Spread</th><th>Total</th><th>Moneyline</th><th>Projected score</th></tr></thead>
      <tbody>
        <tr class="sec"><td colspan="5">Pregame${g.state === "pre" ? "" : ", locked at kickoff"}</td></tr>
        ${rows.join("")}
        ${live.length ? `<tr class="sec"><td colspan="5">Live${g.state === "in" ? ` \u00b7 ${esc(gameStatus(g))}` : ""}</td></tr>${live.join("")}` : ""}
      </tbody>
    </table></div>
    ${addRow}
    <div class="gl-foot">
      ${leans.length ? `<span>Our pregame ${leans.length === 1 ? "lean" : "leans"}: ${leans.map((l) => `<span class="glean">${esc(l)}</span>`).join(" ")}</span>` : u ? `<span class="muted">No pregame lean: we're within 2 points of DraftKings' spread and 3 of the total.</span>` : ""}
      ${u || lvUs ? `<span class="muted">Ours pregame: our player projections added up into team scores, locked at kickoff and graded${g.ours_late ? " (this one was first made after kickoff, so it isn't graded)" : ""}. Ours live: the score so far plus what's left of our pregame projection for the time remaining. Percentages are win chances: DraftKings' with their built-in margin taken out, so they compare directly with ours. Our moneylines are fair odds (no margin), which is why ours mirror each other (+163 / -163) and DraftKings' don't (+140 / -166).${lvDK ? " DraftKings' live odds come through ESPN without a timestamp and can lag a play or two, or freeze while betting is suspended." : ""}</span>` : ""}
    </div>
  </div>`;
}

// The player's team total implied by the DraftKings spread and total
function impliedFor(p) {
  const o = S.games[p.game_id]?.odds;
  return o ? (p.home ? o.home_pts : o.away_pts) : null;
}

function avatar(p) {
  if (p.pos === "DEF") return `<div class="av def"><img src="${logo(p.team)}" alt="" loading="lazy"></div>`;
  return `<div class="av"><img src="${photo(p.id)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">${p.freeAgent ? "" : `<img class="tm" src="${logo(p.team)}" alt="" loading="lazy">`}</div>`;
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

// How hard a defense is on a position this season: 1 = allows the fewest fantasy points (toughest), 32 = the most
function defRank(opp, pos) {
  const all = S.data.defense || {};
  const r = all[opp]?.[pos];
  if (!r) return null;
  const n = Object.values(all).filter((t) => t[pos]).length;
  return { rank: n + 1 - r.rank, n, allowed: r.allowed };
}

function rankChip(opp, pos, withOpp = false) {
  if (!opp || !["QB", "RB", "WR", "TE"].includes(pos)) return "";
  const d = defRank(opp, pos);
  if (!d) return withOpp ? `<span class="mrank">vs ${opp}</span>` : "";
  const cls = d.rank <= 8 ? "tough" : d.rank > d.n - 8 ? "easy" : "";
  return `<span class="mrank ${cls}" title="${opp} allows ${d.allowed} fantasy points a game to ${pos}s this season: #${d.rank} of ${d.n} (1 = toughest)">${withOpp ? `vs ${opp} ` : ""}#${d.rank} vs ${pos}</span>`;
}

function matchupText(p) {
  return rankChip(p.opp, p.pos);
}

// The rest of a player's schedule: average defensive rank of his remaining opponents against his position
function scheduleFor(p) {
  if (!S.future || !["QB", "RB", "WR", "TE"].includes(p.pos)) return null;
  const ranks = futureRows(p).map((x) => defRank(x.opp, p.pos)?.rank).filter((x) => x != null);
  if (!ranks.length) return null;
  const avg = ranks.reduce((a, b) => a + b, 0) / ranks.length;
  return { avg, label: avg >= 20 ? "Easy" : avg <= 13 ? "Hard" : "Average" };
}

function scheduleChip(p) {
  const sc = scheduleFor(p);
  if (!sc) return "";
  return `<span class="mrank ${sc.label === "Easy" ? "easy" : sc.label === "Hard" ? "tough" : ""}" title="Average defensive rank of his remaining opponents against ${p.pos}s (1 = toughest): ${fmt(sc.avg)}">${sc.label} schedule</span>`;
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
  if (st.res === "push") return `<span class="res dnp">PUSH</span>`;
  if (st.res === "live") return `<span class="res live">LIVE</span>`;
  return "";
}

function progress(st, line, dir, key) {
  if (!st || st.v == null) return "";
  const pct = Math.min(100, (100 * st.v) / Math.max(line, 0.5));
  // an under that's most of the way to its line is in danger
  const cls = st.res === "hit" ? "hit" : st.res === "miss" ? "miss" : dir === "under" && pct >= 75 ? "warn" : "";
  let note = "";
  if (st.res === "live" && key) {
    const gap = line - st.v;
    note = dir === "under" ? `${fmtStat(key, gap)} to spare` : `needs ${fmtStat(key, Math.max(0, Math.floor(gap) + 1))} more`;
  }
  return `<div class="prog ${cls}"><i style="width:${pct}%"></i></div>${note ? `<div class="prog-note">${note}</div>` : ""}`;
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
      <div class="small">${LINE_FROM[pick.line_from] || "Our"} line, locked at kickoff · ${adj != null ? `our pregame proj <b class="num">${fmt(adj)}</b> · ` : ""}over in ${pick.over} of ${pick.n} this season${liveLineText(p, pick.key, pick.line)}</div>
      ${progress(st, pick.line, pick.direction, pick.key)}
    </div>
    <div class="side">
      <button class="add mini ${pick.direction} ${minePick(p.id, pick.key, pick.direction) ? "on" : ""}" data-add="${p.id}|${pick.key}|${pick.direction}|${pick.line}" title="Add to My Picks">${minePick(p.id, pick.key, pick.direction) ? "\u2713" : "+"}</button>
      ${st ? `<div class="big" data-live-pick>${st.v == null ? "-" : fmtStat(pick.key, st.v)}</div>${resBadge(st)}` : `<div class="small">${esc(gameStatus(S.games[p.game_id]))}</div>`}
    </div>
  </div>`;
}

function propChip(p, raw) {
  const prop = pv(p, raw);
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

function catCard(p, raw) {
  const prop = pv(p, raw);
  const from = prop.line_from || "ours";
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
    : from === "ours"
      ? `<span class="lean none" title="Leans are only called against real sportsbook lines">No book line</span>`
      : `<span class="lean ${lean || "none"}">${lean ? `Lean ${lean}` : "No lean"}</span>`;

  const bars = vals.map((x) => `<div class="b ${x.v > line ? "o" : ""}" title="${x.s} week ${x.w} vs ${x.opp}: ${x.v}"><span>${fmtStat(prop.key, x.v)}</span><i style="height:${(100 * x.v) / top}%"></i></div>`).join("")
    + (nowV != null ? `<div class="b now" title="This week"><span>${fmtStat(prop.key, nowV)}</span><i style="height:${(100 * nowV) / top}%"></i></div>` : "");
  const xs = vals.map((x) => `<span>${x.s !== S.data.season ? "'" + String(x.s).slice(2) + " " : ""}W${x.w}</span>`).join("")
    + (nowV != null ? `<span style="color:var(--cyan)">Now</span>` : "");

  const liveLine = S.liveLines[p.id]?.[prop.key];
  const lineCell = prop.key === "anytime_td"
    ? `<div>Line<span class="n">0.5</span></div>`
    : `<div>${edited ? "Your line" : LINE_FROM[from]}<input type="number" step="1" inputmode="decimal" value="${line}" data-line="${k}" aria-label="${cat.label} line"></div>`
      + (prop.dk_open != null && prop.dk_open !== prop.line ? `<div>DK opened<span class="n">${prop.dk_open}</span></div>` : "")
      + (liveLine != null && S.games[p.game_id]?.state === "in" ? `<div title="DraftKings' in-game line right now">DK live<span class="n" style="color:var(--amber)">${liveLine}</span></div>` : "")
      + (prop.sleeper && from !== "sleeper" ? `<div>Sleeper Picks<span class="n">${prop.sleeper.line}</span></div>` : "")
      ;
  const gamesText = vals.length ? `${vals.length} game${vals.length === 1 ? "" : "s"} this season` : "";
  const mfText = prop.mf_n
    ? ` Matchup vs ${p.opp}: <b>${prop.mf >= 1 ? "+" : ""}${fmt(100 * (prop.mf - 1))}%</b> (similar ${p.pos}s against them this season, ${prop.mf_n} game${prop.mf_n === 1 ? "" : "s"}).`
    : prop.mf != null ? ` No similar ${p.pos}s have faced ${p.opp} yet, so no matchup adjustment.` : "";
  const note = prop.key === "anytime_td"
    ? `${vals.length ? `Scored in ${vals.filter((x) => x.v > 0).length} of ${gamesText}. ` : ""}Chance comes from Sleeper's projected TDs.`
    : (vals.length ? `Over in <b>${over}</b> of ${gamesText}${edited ? ` at your line (the ${LINE_FROM[from]} line is ${prop.line})` : ""}.` : "No games yet this season.")
        + mfText
        + (from === "ours" && prop.key !== "fpts" ? " No sportsbook line yet, so this line is our projection." : "")
        + (prop.sleeper?.over ? ` Sleeper Picks pays ${prop.sleeper.over}x over, ${prop.sleeper.under}x under.` : "");

  return `<div class="cat" data-cat="${k}">
    <div class="cat-h"><span>${prop.key === "fpts" ? `Fantasy Points (${scoringName()})` : cat.label}</span>${leanPill}</div>
    ${prop.key !== "anytime_td" ? `<div class="cat-add">${["over", "under"].map((d) => {
      const on = minePick(p.id, prop.key, d);
      return `<button class="add ${d} ${on ? "on" : ""}" data-add="${p.id}|${prop.key}|${d}|${line}" title="${on ? "Remove from" : "Add to"} My Picks">${on ? "\u2713" : "+"} ${d === "over" ? "Over" : "Under"} ${line}</button>`;
    }).join("")}</div>` : ""}
    <div class="cat-nums">
      ${lineCell}
      ${prop.adj != null && prop.key !== "anytime_td" ? `<div title="Sleeper's projection x the matchup adjustment, made before kickoff">Our proj (pregame)<span class="n">${prop.key === "fpts" ? fmtPts(prop.adj) : fmt(prop.adj)}</span></div>` : ""}
      ${st && !st.final && st.v != null && prop.adj != null && prop.key !== "anytime_td" ? `<div title="What he has so far plus our pregame projection for the time left">On pace<span class="n" style="color:var(--amber)">${fmt(st.v + prop.adj * remaining(S.games[p.game_id]), prop.key === "fpts" ? 2 : 1)}</span></div>` : ""}
      ${prop.proj != null ? `<div>Sleeper proj<span class="n">${fmtStat(prop.key, prop.proj)}</span></div>` : ""}
      ${avg != null ? `<div>Season avg<span class="n">${fmt(avg)}</span></div>` : ""}
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
  return `<div class="player ${out ? "out" : ""} ${isMine(p.id) ? "is-mine" : ""}" data-player="${p.id}">
    <div class="phead" data-toggle="${p.id}">
      ${avatar(p)}
      <div>
        <div class="pname">${esc(p.name)}${injBadge(p)}${mineTag(p)}</div>
        <div class="pmeta"><span class="pos ${p.pos}">${p.pos}</span> ${p.team} ${oppText(p)} ${matchupText(p)} <span>· ${esc(gameStatus(g))}</span>${impliedFor(p) != null ? `<span class="muted" title="${p.team}'s points implied by the DraftKings spread and total">· ${p.team} ${impliedFor(p)} pts</span>` : ""}</div>
      </div>
      <div class="pts"><div class="lbl">Proj</div><div class="v">${fmtPts(projPts(p))}</div></div>
      <div class="pts"><div class="lbl">${g?.state === "post" ? "Final" : g?.state === "in" ? "Live" : "Avg"}</div>
        <div class="v ${c ? "live" : ""}" data-live-ppr="${p.id}">${c ? (c.none ? "DNP" : fmtPts(live)) : fmtPts(avgPts(p))}</div></div>
    </div>
    <div class="props-row" data-chips="${p.id}">${props.map((x) => propChip(p, x)).join("")}</div>
    ${open ? `<div class="pbody">${latestBlock(p)}${gameLog(p)}${props.map((x) => catCard(p, x)).join("")}
      <div class="note" style="grid-column:1/-1">${favBtn(p)} <button class="tbtn" data-cmp-add="${p.id}">Compare</button> ${p.depth ? `Depth chart: ${p.pos}${p.depth}. ` : ""}${p.late ? "These lines were first built after kickoff, so they aren't graded." : ""}</div></div>` : ""}
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
    proj: (p) => -(projPts(p) ?? -1),
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

  const promo = !S.sync && !store("syncPromoHidden")
    ? `<div class="sync-promo"><div><b>Sync your league</b> <span class="muted">Sleeper username or ESPN league ID: see your best lineup, weak spots and trade ideas with every team. Your league's scoring applies everywhere.</span></div>
        <div class="sync-promo-btns"><button class="tbtn on" data-go-sync>Sync league</button><button class="rm" data-hide-promo title="Hide" aria-label="Hide">\u00d7</button></div></div>`
    : "";
  $("#main").innerHTML = promo + `
    <div class="picks-wrap">
      <div class="picks"><h3>Top Overs <span class="tag over">${picksFor("over").length}</span></h3>${pickList("over")}</div>
      <div class="picks"><h3>Top Unders <span class="tag under">${picksFor("under").length}</span></h3>${pickList("under")}</div>
    </div>
    <p class="note">Top picks are the biggest gaps between our projection (Sleeper's, adjusted for how similar players have done against this defense this season) and the real DraftKings line, for players with 2+ games this season who aren't ruled out. They lock at kickoff with the pregame line; during the game you'll also see DraftKings' live line. <a href="#" data-goto="about">How it works</a></p>

    <h2>Players <small>${list.length} shown</small></h2>
    <div class="filters">
      <div class="chips">${["ALL", "QB", "RB", "WR", "TE"].map((x) => `<button class="chip ${f.pos === x ? "on" : ""}" data-pos="${x}">${x === "ALL" ? "All" : x}</button>`).join("")}</div>
      <select id="f-game" aria-label="Game"><option value="">All games</option>${gameOpts}</select>
      <select id="f-cat" aria-label="Prop"><option value="">All props</option>${catOpts}</select>
      <select id="f-sort" aria-label="Sort">
        <option value="proj" ${f.sort === "proj" ? "selected" : ""}>Sort: Projected points</option>
        <option value="live" ${f.sort === "live" ? "selected" : ""}>Sort: Live points</option>
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
  if (ff.view === "ros") return renderRos();
  if (!posOk(ff.pos)) ff.pos = "FLEX";
  const pos = ff.pos === "FLEX" ? ["RB", "WR", "TE"] : ff.pos === "ALL" ? usePositions(["QB", "RB", "WR", "TE", "K", "DEF"]) : [ff.pos];
  const rows = S.data.players.filter((p) => pos.includes(p.pos) && projPts(p) != null && projPts(p) >= 0.5)
    .map((p) => {
      const live = livePPR(p);
      return { p, proj: projPts(p), live, diff: live != null ? live - projPts(p) : null, avg: avgPts(p), name: p.name, snap: p.snap_share ?? null };
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
    <h2>Fantasy rankings <small>${esc(scoringName())} \u00b7 K and DEF on ESPN standard scoring</small></h2>
    <div class="filters">${seg("data-fview", ff.view || "week", [["week", "This week"], ["ros", "Rest of season"]], "View")}<div class="chips">${usePositions(["QB", "RB", "WR", "TE", "FLEX", "K", "DEF", "ALL"]).map((x) => `<button class="chip ${ff.pos === x ? "on" : ""}" data-fpos="${x}">${x === "ALL" ? "All" : x}</button>`).join("")}</div></div>
    <div class="tbl-wrap"><table class="tbl">
      <thead><tr><th class="l">#</th>${th("name", "Player", "l")}<th class="l hide-sm">Game</th>${th("proj", "Proj")}${th("live", "Live")}${th("diff", "+/-", "hide-sm")}${th("avg", "Avg", "hide-sm")}${th("snap", "Snap %", "hide-sm")}</tr></thead>
      <tbody>${rows.slice(0, ff.shown).map((r) => {
        const p = r.p;
        const g = S.games[p.game_id];
        const c = current(p);
        return `<tr data-open="${p.id}" class="${isMine(p.id) ? "is-mine" : ""}">
          <td class="rk">${projRank.get(p.id)}</td>
          <td class="l"><div class="who">${avatar(p)}<div><div><b>${esc(p.name)}</b>${injBadge(p)}</div>
            <div class="pmeta"><span class="pos ${p.pos}">${p.pos}</span> ${p.team} ${oppText(p)} ${matchupText(p)}</div></div></div></td>
          <td class="l hide-sm muted">${esc(gameStatus(g))}</td>
          <td class="big">${fmtPts(r.proj)}</td>
          <td class="big" style="color:var(--cyan)">${c ? (c.none ? "DNP" : fmtPts(r.live)) : "-"}</td>
          <td class="hide-sm ${r.diff > 0 ? "up" : r.diff < 0 ? "down" : ""}">${r.diff == null ? "-" : (r.diff > 0 ? "+" : "") + fmtPts(r.diff)}</td>
          <td class="hide-sm muted">${fmtPts(r.avg)}</td>
          <td class="hide-sm muted">${r.snap != null ? `${Math.round(100 * r.snap)}%` : "-"}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>
    ${rows.length > ff.shown ? `<button class="more" data-fmore>Show more (${rows.length - ff.shown})</button>` : ""}
    <p class="note">Proj is Sleeper's projection for this week. Live comes from ESPN's box score every 30 seconds and matches Sleeper's final scoring, except rare plays the box score doesn't show (special teams fumble recoveries and blocked kicks), which catch up at the next hourly update. Kickers score 3 per field goal under 40 yards, 4 from 40 to 49, 5 from 50+, 1 per extra point and -1 per miss. Defenses score for sacks, takeaways, touchdowns, safeties and points allowed. Avg is this season's average.</p>`;
}

function renderRos() {
  const ff = S.ff;
  const head = `<h2>Rest of season <small>${esc(scoringName())} · Sleeper's weekly projections</small></h2>
    <div class="filters">${seg("data-fview", "ros", [["week", "This week"], ["ros", "Rest of season"]], "View")}<div class="chips">${usePositions(["QB", "RB", "WR", "TE", "FLEX", "K", "DEF", "ALL"]).map((x) => `<button class="chip ${ff.pos === x ? "on" : ""}" data-fpos="${x}">${x === "ALL" ? "All" : x}</button>`).join("")}</div></div>`;
  if (!S.future) {
    $("#main").innerHTML = head + `<div class="empty">Loading projections for the rest of the season...</div>`;
    loadFuture().then(() => { if (S.tab === "fantasy" && S.ff.view === "ros") renderRos(); });
    return;
  }
  if (!posOk(ff.pos)) ff.pos = "FLEX";
  const pos = ff.pos === "FLEX" ? ["RB", "WR", "TE"] : ff.pos === "ALL" ? usePositions(["QB", "RB", "WR", "TE", "K", "DEF"]) : [ff.pos];
  const nextWeeks = [];
  for (let w = S.data.week + 1; w <= S.data.week + 4 && w <= 18; w++) nextWeeks.push(w);
  const rows = rosPool().filter((p) => pos.includes(p.pos)).map((p) => {
    const fut = futureRows(p);
    const n = rosGames(p);
    const ros = rosPts(p);
    return { p, ros, per: n ? ros / n : 0, n, fut };
  }).filter((r) => r.ros >= 5).sort((a, b) => b.ros - a.ros).slice(0, ff.shown);
  $("#main").innerHTML = head + `<div class="tbl-wrap"><table class="tbl">
    <thead><tr><th class="l">#</th><th class="l">Player</th><th title="Position rank and projected points per game when he plays">Rank, per game</th><th>Season total</th>${nextWeeks.map((w) => `<th class="hide-sm">Wk ${w}</th>`).join("")}<th class="hide-sm">Bye</th></tr></thead>
    <tbody>${rows.map((r, i) => `<tr data-open="${r.p.id}">
      <td class="rk">${i + 1}</td>
      <td class="l"><div class="who">${avatar(r.p)}<div><div><b>${esc(r.p.name)}</b>${injBadge(r.p)}</div><div class="pmeta"><span class="pos ${r.p.pos}">${r.p.pos}</span> ${r.p.team}</div></div></div></td>
      <td class="big">${gradeChip(r.p)} ${fmtPts(rosPerGame(r.p))}</td>
      <td class="muted">${fmtPts(r.ros)}</td>
      ${nextWeeks.map((w) => { const x = r.fut.find((y) => y.w === w); return `<td class="hide-sm">${x ? `${fmtPts(x.pts)}<div class="muted small">${x.opp}</div>` : byesLeft(r.p).includes(w) ? `<span class="muted">BYE</span>` : "-"}</td>`; }).join("")}
      <td class="hide-sm muted">${byesLeft(r.p).join(", ") || "-"}</td>
    </tr>`).join("")}</tbody></table></div>
    <button class="more" data-fmore>Show more</button>
    <p class="note">Rest of season adds up this week (if his game hasn't started) and every remaining week of Sleeper's projections, scored in ${esc(scoringName())}. Kickers and defenses use ESPN standard scoring.</p>`;
}

// ---------------------------------------------------------------- trade

// How many starters a league uses at each position (default: 12 teams, QB, 2 RB, 2 WR, TE, FLEX, K, DEF).
// FLEX spots are split the way they're usually filled.
function leagueShape() {
  const lg = currentLeague();
  const teams = lg?.teams || 12;
  const slots = lg?.roster_positions || ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"];
  const n = { QB: 0, RB: 0, WR: 0, TE: 0, K: 0, DEF: 0 };
  for (const s2 of slots) {
    if (n[s2] != null) n[s2] += 1;
    else if (s2 === "FLEX") { n.RB += 0.45; n.WR += 0.45; n.TE += 0.1; }
    else if (s2 === "WRRB_FLEX") { n.RB += 0.5; n.WR += 0.5; }
    else if (s2 === "REC_FLEX") { n.WR += 0.8; n.TE += 0.2; }
    else if (s2 === "SUPER_FLEX") { n.QB += 0.8; n.RB += 0.1; n.WR += 0.1; }
  }
  // Bench spots get filled mostly with running backs and receivers
  const bench = lg?.roster_positions ? slots.filter((x) => x === "BN").length : 6;
  const share = { QB: 0.1, RB: 0.38, WR: 0.38, TE: 0.1, K: 0.02, DEF: 0.02 };
  const rostered = Object.fromEntries(Object.entries(n).map(([k, v]) => [k, Math.round((v + bench * share[k]) * teams)]));
  return { teams, bench, starters: Object.fromEntries(Object.entries(n).map(([k, v]) => [k, Math.round(v * teams)])), rostered, name: lg?.name };
}

// Replacement level: the best player at each position likely to be on waivers once every team has filled its
// starters and bench. A player's value is how many rest-of-season points he adds over that.
function replacementLevels() {
  const shape = leagueShape();
  const out = {};
  for (const pos of Object.keys(shape.rostered)) {
    const pts = rosPool().filter((p) => p.pos === pos).map(rosPts).sort((a, b) => b - a);
    out[pos] = pts[shape.rostered[pos]] ?? pts[pts.length - 1] ?? 0;
  }
  return out;
}

// ---- syncing a Sleeper league

const SLOT_ELIG = {
  QB: ["QB"], RB: ["RB"], WR: ["WR"], TE: ["TE"], K: ["K"], DEF: ["DEF"],
  FLEX: ["RB", "WR", "TE"], WRRB_FLEX: ["RB", "WR"], REC_FLEX: ["WR", "TE"], SUPER_FLEX: ["QB", "RB", "WR", "TE"],
};

async function syncFindUser(name) {
  S.syncMsg = "Looking...";
  S.syncFound = null;
  rerenderLeagueViews();
  try {
    const q = name.trim();
    if (/^\d{8,}$/.test(q)) {
      const l = await getJSON(`https://api.sleeper.app/v1/league/${q}`);
      S.syncFound = l?.league_id ? [l] : [];
      S.syncUser = null;
    } else {
      const u = await getJSON(`https://api.sleeper.app/v1/user/${encodeURIComponent(q)}`);
      if (!u?.user_id) throw new Error("no user");
      S.syncUser = { id: u.user_id, name: u.display_name };
      S.syncFound = ((await getJSON(`https://api.sleeper.app/v1/user/${u.user_id}/leagues/nfl/${S.data.season}`)) || []);
    }
    S.syncMsg = S.syncFound.length ? "" : "No leagues found for that.";
  } catch {
    S.syncMsg = "Couldn't find that Sleeper user or league.";
  }
  rerenderLeagueViews();
}

async function syncLeague(leagueId, userId, source = "sleeper") {
  S.syncMsg = "Loading rosters...";
  rerenderLeagueViews();
  try {
    let league, rosters, users;
    let yMine = null;
    if (source === "espn") ({ league, rosters, users } = await espnLeague(leagueId));
    else if (source === "yahoo") ({ league, rosters, users, mine: yMine } = await yahooLeague(leagueId));
    else [league, rosters, users] = await Promise.all([
      getJSON(`https://api.sleeper.app/v1/league/${leagueId}`),
      getJSON(`https://api.sleeper.app/v1/league/${leagueId}/rosters`),
      getJSON(`https://api.sleeper.app/v1/league/${leagueId}/users`),
    ]);
    const fresh = S.sync?.league_id !== leagueId;
    const mine = yMine != null ? rosters.find((r) => r.roster_id === yMine) : rosters.find((r) => r.owner_id === userId || (r.co_owners || []).includes(userId));
    const keep = S.sync?.league_id === leagueId ? S.sync.roster_id : null;
    S.sync = { league_id: leagueId, user_id: userId || null, roster_id: keep ?? mine?.roster_id ?? null, name: league.name, source, slots: league.roster_positions };
    S.leagueData = { league, rosters, users };
    store("sync", S.sync);
    // the league's scoring and lineup become the site's
    if (!S.leagues.some((l) => l.id === leagueId)) {
      S.leagues.push({ id: leagueId, name: league.name, season: league.season, settings: league.scoring_settings, teams: league.total_rosters, roster_positions: league.roster_positions });
      store("leagues", S.leagues);
    }
    if (fresh || !S.sc.mode || S.sc.mode === "league") {
      S.sc = { mode: "league", league: leagueId, half: false };
      store("scoring", S.sc);
      $("#sc-btn").textContent = `${scoringName()} ▾`;
    }
    S.syncFound = null;
    S.syncMsg = "";
    S.ideas = null;
  } catch (err) {
    S.syncMsg = source === "yahoo" ? `Couldn't load that Yahoo league (${err.message}).` : source === "espn"
      ? err.message === "private"
        ? "That ESPN league is private. In Chrome, sign in to espn.com in this browser and try again, or make the league viewable to the public in its ESPN settings."
        : "Couldn't find that ESPN league. Check the leagueId in your league's ESPN address."
      : "Couldn't load that league from Sleeper.";
  }
  rerenderLeagueViews();
  updateSyncBtn();
}

function rerenderLeagueViews() {
  if (S.gameView) return;
  if (S.tab === "league") renderLeagueTab();
  else if (S.tab === "trade") renderTrade();
}

// ---- ESPN leagues: read with the browser's own ESPN login (ESPN allows this site to ask), then reshaped to look
// like a Sleeper league so the lineup and trade finder work the same way

const ESPN_FF = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons";
const ESPN_POS = { 1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF" };
// ESPN lineup slot ids -> Sleeper slot names
const ESPN_SLOT = { 0: "QB", 2: "RB", 4: "WR", 6: "TE", 23: "FLEX", 7: "SUPER_FLEX", 3: "WRRB_FLEX", 5: "REC_FLEX", 16: "DEF", 17: "K", 20: "BN" };
// ESPN scoring stat ids -> Sleeper stat names (the offensive ones that matter for skill players)
const ESPN_STAT = { 3: "pass_yd", 4: "pass_td", 19: "pass_2pt", 20: "pass_int", 24: "rush_yd", 25: "rush_td", 26: "rush_2pt",
  42: "rec_yd", 43: "rec_td", 44: "rec_2pt", 53: "rec", 72: "fum_lost" };

// ESPN team ids (fixed; ESPN's team list doesn't allow browser requests)
const ESPN_TEAM_IDS = {"1":"ATL","2":"BUF","3":"CHI","4":"CIN","5":"CLE","6":"DAL","7":"DEN","8":"DET","9":"GB","10":"TEN","11":"IND","12":"KC","13":"LV","14":"LAR","15":"MIA","16":"MIN","17":"NE","18":"NO","19":"NYG","20":"NYJ","21":"PHI","22":"ARI","23":"PIT","24":"LAC","25":"SF","26":"SEA","27":"TB","28":"WAS","29":"CAR","30":"JAX","33":"BAL","34":"HOU"};

async function espnTeamCodes() {
  return ESPN_TEAM_IDS;
}

async function espnLeague(leagueId) {
  await loadFuture();
  const url = `${ESPN_FF}/${S.data.season}/segments/0/leagues/${leagueId}?view=mTeam&view=mRoster&view=mSettings`;
  const r = await fetch(url, { credentials: "include" });
  if (r.status === 401 || r.status === 403) throw new Error("private");
  if (!r.ok) throw new Error("missing");
  const d = await r.json();
  const teams = await espnTeamCodes();
  const byName = {};
  for (const p of rosPool()) byName[`${normName(p.name)}|${p.team}`] = p.id;
  const toSleeper = (pl) => {
    const pos = ESPN_POS[pl.defaultPositionId];
    const team = teams[pl.proTeamId];
    if (pos === "DEF") return team && S.byId[team] ? team : null;
    return S.byEspn[String(pl.id)] || byName[`${normName(pl.fullName || "")}|${team}`] || null;
  };
  const counts = d.settings?.rosterSettings?.lineupSlotCounts || {};
  const roster_positions = Object.entries(counts).flatMap(([slot, n]) => (ESPN_SLOT[slot] ? Array(n).fill(ESPN_SLOT[slot]) : []));
  const scoring_settings = {};
  for (const item of d.settings?.scoringSettings?.scoringItems || []) {
    const k = ESPN_STAT[item.statId];
    if (k) scoring_settings[k] = item.points;
  }
  const members = Object.fromEntries((d.members || []).map((m) => [m.id, m.displayName]));
  return {
    league: { league_id: String(leagueId), name: d.settings?.name || `ESPN league ${leagueId}`, season: String(S.data.season), total_rosters: d.teams.length, roster_positions, scoring_settings, source: "espn" },
    rosters: d.teams.map((t) => ({ roster_id: t.id, owner_id: t.primaryOwner || (t.owners || [])[0],
      settings: { wins: t.record?.overall?.wins, losses: t.record?.overall?.losses, ties: t.record?.overall?.ties, fpts: t.record?.overall?.pointsFor, fpts_against: t.record?.overall?.pointsAgainst },
      players: (t.roster?.entries || []).map((e) => toSleeper(e.playerPoolEntry?.player || {})).filter(Boolean) })),
    users: d.teams.map((t) => ({ user_id: t.primaryOwner || (t.owners || [])[0], display_name: members[t.primaryOwner] || "", metadata: { team_name: t.name || [t.location, t.nickname].filter(Boolean).join(" ") || t.abbrev } })),
  };
}

// ---- Yahoo leagues, through the site's Worker (Yahoo's API doesn't allow requests from web pages)

const YAHOO_SLOT = { QB: "QB", RB: "RB", WR: "WR", TE: "TE", K: "K", DEF: "DEF", "W/R/T": "FLEX", "W/R": "WRRB_FLEX", "W/T": "REC_FLEX", "Q/W/R/T": "SUPER_FLEX", BN: "BN", IR: "IR" };
// Yahoo scoring stat ids -> Sleeper stat names
const YAHOO_STAT = { 4: ["pass_yd"], 5: ["pass_td"], 6: ["pass_int"], 9: ["rush_yd"], 10: ["rush_td"], 11: ["rec"], 12: ["rec_yd"], 13: ["rec_td"], 16: ["pass_2pt", "rush_2pt", "rec_2pt"], 18: ["fum_lost"] };
const YAHOO_TEAM = { JAC: "JAX", WSH: "WAS", LA: "LAR" };

// Yahoo's JSON: lists come as {"0": {...}, "1": {...}, count} and records as arrays of small objects to merge
const yList = (x, key) => (x ? Object.keys(x).filter((k) => /^\d+$/.test(k)).map((k) => x[k][key]) : []);
const yObj = (x) => (Array.isArray(x) ? x.reduce((a, v) => Object.assign(a, Array.isArray(v) ? yObj(v) : v && typeof v === "object" ? v : {}), {}) : x || {});

async function yahooFetch(path) {
  let tok = S.yahoo;
  if (!tok) throw new Error("not signed in");
  if (tok.expires_at - Date.now() < 60000) {
    const r = await fetch(`${WORKER_URL}/yahoo/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: tok.refresh_token }) });
    if (!r.ok) { S.yahoo = null; store("yahoo", null); throw new Error("Yahoo sign-in expired"); }
    tok = { ...(await r.json()) };
    tok.refresh_token ||= S.yahoo.refresh_token;
    S.yahoo = tok;
    store("yahoo", tok);
  }
  const r = await fetch(`${WORKER_URL}/yahoo/api?path=${encodeURIComponent(path)}`, { headers: { Authorization: `Bearer ${tok.access_token}` } });
  if (!r.ok) throw new Error(`Yahoo ${r.status}`);
  return (await r.json()).fantasy_content;
}

async function yahooLeagues() {
  const fc = await yahooFetch("users;use_login=1/games;game_keys=nfl/leagues");
  const user = fc.users?.["0"]?.user || [];
  const games = yList(yObj(user).games, "game");
  return games.flatMap((g) => yList(yObj(g).leagues, "league").map(yObj)).filter((l) => String(l.season) === String(S.data.season));
}

async function yahooLeague(key) {
  await loadFuture();
  const [settingsFc, rostersFc, standingsFc] = await Promise.all([
    yahooFetch(`league/${key}/settings`), yahooFetch(`league/${key}/teams/roster`), yahooFetch(`league/${key}/standings`),
  ]);
  const meta = yObj(settingsFc.league);
  const settings = (meta.settings || [])[0] || meta.settings || {};
  const roster_positions = (settings.roster_positions || []).flatMap((x) => {
    const r = x.roster_position || {};
    return YAHOO_SLOT[r.position] ? Array(+r.count || 1).fill(YAHOO_SLOT[r.position]) : [];
  });
  const scoring_settings = {};
  for (const x of settings.stat_modifiers?.stats || []) for (const k of YAHOO_STAT[x.stat?.stat_id] || []) scoring_settings[k] = +x.stat.value;
  const byName = {};
  for (const p of rosPool()) byName[`${normName(p.name)}|${p.team}`] = p.id;
  const toSleeper = (pl) => {
    const team = YAHOO_TEAM[String(pl.editorial_team_abbr || "").toUpperCase()] || String(pl.editorial_team_abbr || "").toUpperCase();
    if ((pl.display_position || pl.primary_position) === "DEF") return S.byId[team] ? team : null;
    return byName[`${normName(pl.name?.full || "")}|${team}`] || null;
  };
  const teams = yList(yObj(rostersFc.league).teams, "team");
  const standing = {};
  const stl = yObj(standingsFc.league).standings;
  for (const t of yList((Array.isArray(stl) ? stl[0] : stl)?.teams, "team")) {
    const o = yObj(t);
    standing[o.team_id] = { wins: +o.team_standings?.outcome_totals?.wins || 0, losses: +o.team_standings?.outcome_totals?.losses || 0, ties: +o.team_standings?.outcome_totals?.ties || 0, fpts: +o.team_standings?.points_for || 0, fpts_against: +o.team_standings?.points_against || 0 };
  }
  let mine = null;
  const rosters = teams.map((t) => {
    const info = yObj(Array.isArray(t) ? t[0] : t);
    const roster = (Array.isArray(t) ? t[1] : t)?.roster || {};
    const players = yList(roster["0"]?.players || roster.players, "player").map((pl) => toSleeper(yObj(pl))).filter(Boolean);
    if (+info.is_owned_by_current_login === 1) mine = +info.team_id;
    return { roster_id: +info.team_id, owner_id: `y${info.team_id}`, players, settings: standing[info.team_id] || {}, _name: info.name };
  });
  return {
    league: { league_id: key, name: meta.name || "Yahoo league", season: String(meta.season || S.data.season), total_rosters: rosters.length, roster_positions, scoring_settings, source: "yahoo" },
    rosters,
    users: rosters.map((r) => ({ user_id: r.owner_id, display_name: r._name, metadata: { team_name: r._name } })),
    mine,
  };
}

// Back from Yahoo's sign-in page: the Worker put the tokens in the address fragment
function takeYahooTokens() {
  const m = location.hash.match(/[?&]yahoo=([\w-]+)/);
  const err = location.hash.match(/[?&]yahoo_error=([^&]+)/);
  if (m) {
    try {
      S.yahoo = JSON.parse(decodeURIComponent(escape(atob(m[1].replace(/-/g, "+").replace(/_/g, "/")))));
      store("yahoo", S.yahoo);
      S.syncApp = "yahoo";
    } catch { /* bad token string */ }
  }
  if (err) { S.syncApp = "yahoo"; S.syncMsg = decodeURIComponent(err[1]); }
  if (m || err) history.replaceState(null, "", "#/league");
}

async function yahooFind() {
  S.syncMsg = "Loading your Yahoo leagues...";
  rerenderLeagueViews();
  try {
    S.yahooLeagues = await yahooLeagues();
    S.syncMsg = S.yahooLeagues.length ? "" : `No Yahoo NFL leagues for ${S.data.season} on this account.`;
  } catch (err) {
    S.syncMsg = `Couldn't read your Yahoo leagues (${err.message}). Try signing in again.`;
  }
  rerenderLeagueViews();
}

function teamName(rosterId) {
  const ld = S.leagueData;
  const r = ld.rosters.find((x) => x.roster_id === rosterId);
  const u = ld.users.find((x) => x.user_id === r?.owner_id);
  return u?.metadata?.team_name || u?.display_name || `Team ${rosterId}`;
}

// Best lineup from a set of players by rest-of-season points, filling the strictest slots first
function bestLineup(ids, slots, value = rosPts) {
  const pool = ids.map((id) => S.byId[id]).filter(Boolean).map((p) => ({ p, v: value(p) || 0 })).sort((a, b) => b.v - a.v);
  const used = new Set();
  const order = slots.map((slot, i) => ({ slot, i })).sort((a, b) => (SLOT_ELIG[a.slot]?.length ?? 9) - (SLOT_ELIG[b.slot]?.length ?? 9));
  const starters = new Array(slots.length);
  let total = 0;
  for (const { slot, i } of order) {
    const pick = pool.find((x) => !used.has(x.p.id) && (SLOT_ELIG[slot] || []).includes(x.p.pos));
    if (pick) { used.add(pick.p.id); total += pick.v; }
    starters[i] = { slot, pick };
  }
  return { total, starters, bench: pool.filter((x) => !used.has(x.p.id)) };
}

// Trades that make your starting lineup better: 1-for-1, 2-for-1 and 1-for-2 with every other team.
// "They gain" says whether their lineup improves too (a deal they'd plausibly take).
// Each team's rank at each position (1 = best starters there), from its best rest-of-season lineup
function positionRanks() {
  const ld = S.leagueData, slots = leagueSlots();
  const totals = ld.rosters.map((r) => {
    const t = {};
    for (const s2 of bestLineup(r.players || [], slots).starters) if (s2.pick) t[s2.pick.p.pos] = (t[s2.pick.p.pos] || 0) + s2.pick.v;
    return { id: r.roster_id, t };
  });
  const out = {};
  for (const x of totals) {
    out[x.id] = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) out[x.id][pos] = 1 + totals.filter((y) => (y.t[pos] || 0) > (x.t[pos] || 0)).length;
  }
  return out;
}

const STAR_POWER = 1.3;

// Trades another manager could plausibly accept. A deal counts as fair when:
//  - the trade values (rest-of-season points over a waiver player) are within about 15% of each other, or up to
//    about 30% when the deal fills a position they're weak at and takes from one where they're deep (people pay
//    a little extra to fix a hole);
//  - their best lineup doesn't get meaningfully worse.
// Ideas are ranked by your lineup gain, their lineup gain and how well the deal fits both teams' needs.
function findTradeIdeas() {
  const ld = S.leagueData;
  const slots = leagueSlots();
  const me = myRoster();
  const n = ld.rosters.length;
  const usable = (ids) => (ids || []).filter((id) => S.byId[id] && rosPts(S.byId[id]) >= 15);
  const myIds = me.players || [];
  const baseMeLu = bestLineup(myIds, slots);
  const baseMe = baseMeLu.total, baseMeWeek = weeklyPts(baseMeLu);
  const mineC = usable(myIds);
  const pairs = (xs) => xs.flatMap((a, i) => xs.slice(i + 1).map((b) => [a, b]));
  const repl = replacementLevels();
  const tv = (id) => { const p = S.byId[id]; return p ? Math.max(0, rosPts(p) - (repl[p.pos] ?? 0)) : 0; };
  const sumTv = (ids) => ids.reduce((a, id) => a + tv(id), 0);
  const ranks = positionRanks();
  // For fairness, values are raised to a power above 1, so the best player in a deal counts extra: two good
  // players don't add up to one great one (the side taking two also has to cut someone)
  const starSum = (ids) => ids.reduce((a, id) => a + Math.pow(tv(id), STAR_POWER), 0);
  // + when a team receives players at positions it's weak (rank near n) and gives from positions it's deep
  const needFit = (rid, incoming, outgoing) => {
    const r = ranks[rid] || {};
    const w = (id) => { const pos = S.byId[id]?.pos; return r[pos] ? (r[pos] - 1) / Math.max(1, n - 1) : 0.5; };
    const inn = incoming.length ? incoming.reduce((a, id) => a + w(id), 0) / incoming.length : 0.5;
    const out = outgoing.length ? outgoing.reduce((a, id) => a + w(id), 0) / outgoing.length : 0.5;
    return inn - out;   // -1 .. 1
  };
  const wantPos = S.ideaGet || "ANY", givePos = S.ideaGive || "ANY";
  const okPos = (ids, want) => want === "ANY" || ids.some((id) => S.byId[id]?.pos === want);
  const ideas = [];
  for (const r of ld.rosters) {
    if (r.roster_id === me.roster_id) continue;
    const theirIds = r.players || [];
    const baseThemLu = bestLineup(theirIds, slots);
    const baseThem = baseThemLu.total, baseThemWeek = weeklyPts(baseThemLu);
    const theirC = usable(theirIds);
    const deals = [
      ...mineC.flatMap((g) => theirC.map((t) => [[g], [t]])),
      ...pairs(mineC).flatMap((g) => theirC.map((t) => [g, [t]])),
      ...mineC.flatMap((g) => pairs(theirC).map((t) => [[g], t])),
    ];
    for (const [give, get] of deals) {
      if (!okPos(get, wantPos) || !okPos(give, givePos)) continue;
      const vGive = sumTv(give), vGet = sumTv(get);
      const sGive = starSum(give), sGet = starSum(get);
      const edge = (sGet - sGive) / Math.max(sGive, sGet, Math.pow(25, STAR_POWER));   // how much more you'd get, as a share
      const theirFit = needFit(r.roster_id, give, get);   // they receive what you give
      const allowed = 0.15 + Math.max(0, theirFit) * 0.2; // up to about 30% when it fixes a hole for them
      if (edge > allowed || edge < -0.3) continue;        // too lopsided either way
      const newMine = myIds.filter((id) => !give.includes(id)).concat(get);
      const luMe = bestLineup(newMine, slots);
      const dMe = luMe.total - baseMe;
      if (dMe < 8) continue;
      const wMe = weeklyPts(luMe) - baseMeWeek;     // points a week, what actually matters each Sunday
      if (wMe < 1) continue;
      const newThem = theirIds.filter((id) => !get.includes(id)).concat(give);
      const luThem = bestLineup(newThem, slots);
      const dThem = luThem.total - baseThem;
      const wThem = weeklyPts(luThem) - baseThemWeek;
      if (wThem < -0.2) continue;
      if (dThem < -2) continue;                           // nobody accepts a deal that makes their starters worse
      if (dThem < 0 && edge > -0.1) continue;
      const myFit = needFit(me.roster_id, get, give);
      const score = wMe + 0.6 * Math.max(-1, wThem) + 1.2 * theirFit + 0.8 * myFit - 3 * Math.max(0, edge);
      ideas.push({ roster: r.roster_id, give, get, dMe, dThem, wMe, wThem, vGive, vGet, edge, theirFit, myFit, score });
    }
  }
  // Drop deals padded with a throw-in that doesn't help either side
  const key = (x) => `${x.roster}|${[...x.give].sort().join(",")}|${[...x.get].sort().join(",")}`;
  const byKey = new Map(ideas.map((x) => [key(x), x]));
  const subsets = (x) => [
    ...(x.give.length > 1 ? x.give.map((g) => ({ ...x, give: [g] })) : []),
    ...(x.get.length > 1 ? x.get.map((g) => ({ ...x, get: [g] })) : []),
  ];
  const lean = ideas.filter((x) => !subsets(x).some((sub) => {
    const y = byKey.get(key(sub));
    return y && x.dMe <= y.dMe + 2 && x.dThem <= y.dThem + 2;
  }));
  lean.sort((a, b) => b.score - a.score);
  const perTeam = {}, perTarget = {};
  return lean.filter((x) => {
    const tk = x.get.join("+");
    if ((perTeam[x.roster] || 0) >= 3 || (perTarget[tk] || 0) >= 1) return false;
    perTeam[x.roster] = (perTeam[x.roster] || 0) + 1;
    perTarget[tk] = (perTarget[tk] || 0) + 1;
    return true;
  }).slice(0, 15);
}

// Why the other manager might say yes, in words
// How a trade changes a lineup in a normal week (starters' points per game when they play)
function weeklyChange(rid, give, get) {
  const ld = S.leagueData, slots = leagueSlots();
  const r = ld.rosters.find((x) => x.roster_id === rid);
  const before = r.players || [];
  const after = before.filter((id) => !give.includes(id)).concat(get);
  return weeklyPts(bestLineup(after, slots)) - weeklyPts(bestLineup(before, slots));
}

function tradeSummary(x) {
  const me = x.wMe ?? weeklyChange(S.sync.roster_id, x.give, x.get);
  const them = x.wThem ?? weeklyChange(x.roster, x.get, x.give);
  const word = (v) => (v >= 0.05 ? `<b class="up">+${fmt(v)} points a week</b>` : v <= -0.05 ? `<b class="down">${fmt(v)} points a week</b>` : `<b>no change</b>`);
  const verdict = me >= 0.05 && them >= 0.05 ? "Fair for both" : me >= 0.05 && Math.abs(x.edge) < 0.1 ? "Good for you, fair for them" : me >= 0.05 ? "Good for you" : me <= -0.05 ? "Worse for you" : "Even";
  return `<div class="trade-sum"><span class="verdict-tag">${verdict}</span> Your starters: ${word(me)} · Their starters: ${word(them)}</div>`;
}

function fairText(x) {
  const ranks = positionRanks(), n = S.leagueData.rosters.length;
  const posList = (ids) => [...new Set(ids.map((id) => S.byId[id]?.pos).filter(Boolean))];
  const rk = (rid, pos) => ranks[rid]?.[pos];
  const ord = (k) => `${k}${["th", "st", "nd", "rd"][(k % 100 - 20) % 10] || ["th", "st", "nd", "rd"][k % 100] || "th"}`;
  const needs = posList(x.give).filter((pos) => rk(x.roster, pos) > n / 2).map((pos) => `a ${pos} (they're ${ord(rk(x.roster, pos))} of ${n})`);
  const depth = posList(x.get).filter((pos) => rk(x.roster, pos) <= n / 2).map((pos) => `${pos} depth (${ord(rk(x.roster, pos))} of ${n})`);
  const parts = [needs.length ? `They need ${needs.join(" and ")}` : "", depth.length ? `${needs.length ? "and have" : "They have"} ${depth.join(" and ")}` : ""].filter(Boolean);
  const balance = Math.abs(x.edge) < 0.05 ? "Even trade value." : x.edge > 0 ? "Slightly in your favor on value." : "Slightly in their favor on value.";
  return `${parts.length ? parts.join(" ") + ". " : ""}${balance}`;
}

// "Bhayshul Tuten: RB24 rest of season, 11.2 a game, bye week 9"
function whyLine(id) {
  const p = S.byId[id];
  if (!p) return "";
  const bye = byesLeft(p);
  const sc = scheduleFor(p);
  const bits = [gradeOf(p) ? `${ordinal(gradeOf(p).rank)}-best ${POS_WORD[p.pos] || p.pos}` : "", `${fmt(rosPerGame(p))} points a game`, sc ? `${sc.label.toLowerCase()} schedule` : "", bye.length ? `bye week ${bye.join(", ")}` : "", injOf(p).status || ""].filter(Boolean);
  return `<span class="why">${esc(p.name)}: ${bits.join(" · ")}</span>`;
}

// The sync box, or the league's loading / pick-your-team states. Returns null once the league is ready.
function leagueGate(intro) {
  const ld = S.leagueData;
  if (!S.sync) {
    const app = S.syncApp || "sleeper";
    const body = app === "sleeper"
      ? `<p class="note">Just your Sleeper username: we'll find your leagues and your team.</p>
        <div class="sc-find"><input id="sync-q" placeholder="Sleeper username (or a league ID)" autocomplete="off" autocapitalize="off" spellcheck="false"><button class="tbtn" data-sync-find>Find</button></div>`
      : app === "espn"
      ? `<p class="note">Paste your ESPN league ID: it's the number after <code>leagueId=</code> in your league's address on espn.com. Private leagues work in Chrome when you're signed in to espn.com in this browser; otherwise make the league viewable to the public in its settings.</p>
        <div class="sc-find"><input id="espn-q" placeholder="ESPN league ID" inputmode="numeric" autocomplete="off"><button class="tbtn" data-espn-find>Sync</button></div>`
      : !WORKER_URL
      ? `<p class="note">Yahoo sign-in is coming soon. You can still add your players to the trade calculator by name.</p>`
      : !S.yahoo
      ? `<p class="note">Sign in with your Yahoo account; the site only asks for read access to your fantasy leagues.</p><p><a class="tbtn on" href="${WORKER_URL}/yahoo/login">Sign in with Yahoo</a></p>`
      : `<p class="note">Signed in to Yahoo. <button class="tbtn" data-yahoo-find>Show my leagues</button> <button class="tbtn" data-yahoo-out>Sign out</button></p>
        ${(S.yahooLeagues || []).map((l) => `<div class="sc-lg"><span><b>${esc(l.name)}</b> <span class="muted">${l.num_teams} teams</span></span><button class="tbtn" data-yahoo-pick="${esc(l.league_key)}">Sync</button></div>`).join("")}`;
    return `<div class="card league-sync">
      <b>Sync your league</b>
      <p class="note">${intro}</p>
      ${seg("data-sync-app", app, [["sleeper", "Sleeper"], ["espn", "ESPN"], ["yahoo", "Yahoo"]], "App")}
      ${body}
      ${S.syncMsg ? `<p class="note">${esc(S.syncMsg)}</p>` : ""}
      ${app === "sleeper" ? (S.syncFound || []).map((l) => `<div class="sc-lg"><span><b>${esc(l.name)}</b> <span class="muted">${l.total_rosters} teams · ${leagueSummary(l.scoring_settings)}</span></span><button class="tbtn" data-sync-pick="${l.league_id}">Sync</button></div>`).join("") : ""}
    </div>`;
  }
  if (!ld) {
    if (!S.syncMsg) syncLeague(S.sync.league_id, S.sync.user_id, S.sync.source || "sleeper");
    return `<div class="card league-sync"><p class="note">${esc(S.syncMsg || "Loading your league...")}</p></div>`;
  }
  if (S.sync.roster_id == null) {
    return `<div class="card league-sync"><b>${esc(ld.league.name)}</b><p class="note">Which team is yours?</p>
      <div class="chips">${ld.rosters.map((r) => `<button class="chip" data-sync-team="${r.roster_id}">${esc(teamName(r.roster_id))}</button>`).join("")}</div>
      <p><button class="tbtn" data-sync-clear>Use a different league</button></p></div>`;
  }
  return null;
}

const leagueSlots = () => S.leagueData.league.roster_positions.filter((x) => SLOT_ELIG[x]);
const myRoster = () => S.leagueData.rosters.find((r) => r.roster_id === S.sync.roster_id);
const slotLabel = (x) => x.replace("SUPER_FLEX", "SF").replace("WRRB_FLEX", "W/R").replace("REC_FLEX", "W/T");

// "QB, 2 RB, 2 WR, TE, 2 FLEX, K, DEF, 6 bench"
function lineupSummary() {
  const rp = S.leagueData.league.roster_positions || [];
  const counts = {};
  for (const x of rp) counts[x] = (counts[x] || 0) + 1;
  const order = ["QB", "RB", "WR", "TE", "FLEX", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX", "K", "DEF", "BN", "IR", "TAXI"];
  const names = { WRRB_FLEX: "RB/WR flex", REC_FLEX: "WR/TE flex", SUPER_FLEX: "superflex", BN: "bench", IR: "IR", TAXI: "taxi" };
  return order.filter((k) => counts[k]).map((k) => `${counts[k] > 1 ? `${counts[k]} ` : ""}${names[k] || k}`).join(", ");
}

function leagueHead() {
  const ld = S.leagueData;
  return `<div class="league-h"><div><b>${esc(ld.league.name)}</b> <span class="muted">· ${esc(teamName(S.sync.roster_id))} · ${ld.rosters.length} teams · ${{ espn: "ESPN", yahoo: "Yahoo" }[S.sync.source] || "Sleeper"}</span>
      <div class="league-set">Lineup: ${esc(lineupSummary())} · scoring: ${esc(leagueSummary(ld.league.scoring_settings))}</div></div>
    <div><button class="tbtn" data-sync-refresh>Refresh</button> <button class="tbtn" data-sync-clear>Change</button></div></div>`;
}

// Each team's starters at each position, ranked against the league (rest-of-season points)
function needsBar() {
  const ld = S.leagueData, slots = leagueSlots(), n = ld.rosters.length;
  const posTotals = (ids) => {
    const t = {};
    for (const s2 of bestLineup(ids || [], slots).starters) if (s2.pick) t[s2.pick.p.pos] = (t[s2.pick.p.pos] || 0) + s2.pick.v;
    return t;
  };
  const all = ld.rosters.map((r) => ({ id: r.roster_id, t: posTotals(r.players) }));
  const mine = all.find((y) => y.id === S.sync.roster_id).t;
  const positions = ["QB", "RB", "WR", "TE"].filter((x) => slots.some((s2) => (SLOT_ELIG[s2] || []).includes(x)));
  const rankOf = (pos) => 1 + all.filter((x) => (x.t[pos] || 0) > (mine[pos] || 0)).length;
  return `<div class="needs">${positions.map((pos) => { const r = rankOf(pos); return `<span class="need ${r > n * 0.66 ? "weak" : r <= n * 0.33 ? "strong" : ""}">${pos} <b>${r}</b>/${n}</span>`; }).join("")}
    <span class="note">your starters' rank by rest-of-season points (1 = best)</span></div>`;
}

// A lineup's expected points in a normal week: each starter's points per game when he plays
const weeklyPts = (lu) => lu.starters.reduce((a, s2) => a + (s2.pick ? rosPerGame(s2.pick.p) : 0), 0);

function lineupHtml(ids, title, changed) {
  const lu = bestLineup(ids || [], leagueSlots());
  return `<h3>${title}</h3>${lu.starters.map((s2) => `<div class="lu ${changed && s2.pick && changed.has(s2.pick.p.id) ? "new" : ""}"><span class="slot">${slotLabel(s2.slot)}</span>${s2.pick ? `<span data-open="${s2.pick.p.id}" class="lu-p">${esc(s2.pick.p.name)} <span class="muted">${s2.pick.p.pos} ${s2.pick.p.team}</span>${injBadge(s2.pick.p)}</span><span class="lu-g">${gradeChip(s2.pick.p)} <span class="num">${fmtPts(rosPerGame(s2.pick.p))}</span></span>` : `<span class="muted">empty</span><span></span>`}</div>`).join("")}
    <div class="lu tot"><span></span><span>About this many points a week</span><span class="num">${fmtPts(weeklyPts(lu))}</span></div>
    ${lu.bench.length ? `<p class="note">Bench: ${lu.bench.map((x) => `${esc(x.p.name)} ${gradeOf(x.p)?.letter || ""}`).join(", ")}</p>` : ""}
    <p class="note">WR14 means the 14th-best receiver by projected points per game for the rest of the season (bye weeks and games he's expected to miss don't count against him). Green: a starter in a 12-team league. Blue: solid. Yellow: flex or backup. Gray: deep bench.</p>`;
}

// ---- League tab: my team, matchups, standings, every team, free agents

// ---- Everything else Sleeper has on the league: every week's results, transactions, the draft, playoffs, and
// how many Sleeper users added or dropped each player in the last day

const SLEEPER = "https://api.sleeper.app/v1";

async function loadTrending() {
  if (S.trend) return S.trend;
  const [adds, drops] = await Promise.all(["add", "drop"].map((k) => getJSON(`${SLEEPER}/players/nfl/trending/${k}?lookback_hours=24&limit=500`).catch(() => [])));
  S.trend = { add: Object.fromEntries(adds.map((r) => [r.player_id, r.count])), drop: Object.fromEntries(drops.map((r) => [r.player_id, r.count])) };
  return S.trend;
}

function loadLeagueExtras() {
  const ld = S.leagueData;
  if (!ld) return Promise.resolve();
  if (ld.extrasLoading) return ld.extrasLoading;
  const id = ld.league.league_id;
  const safe = (u, d = []) => getJSON(u).catch(() => d);
  const weeks = Array.from({ length: S.data.week }, (_, i) => i + 1);
  if (S.sync.source && S.sync.source !== "sleeper") {
    ld.extrasLoading = loadTrending().then(() => { ld.extras = true; });
    return ld.extrasLoading;
  }
  ld.extrasLoading = Promise.all([
    Promise.all(weeks.map((w) => safe(`${SLEEPER}/league/${id}/matchups/${w}`))),
    Promise.all(weeks.map((w) => safe(`${SLEEPER}/league/${id}/transactions/${w}`))),
    safe(`${SLEEPER}/league/${id}/drafts`),
    safe(`${SLEEPER}/league/${id}/traded_picks`),
    safe(`${SLEEPER}/league/${id}/winners_bracket`),
    loadTrending(),
  ]).then(async ([mw, tw, drafts, traded, bracket]) => {
    ld.weekly = Object.fromEntries(weeks.map((w, i) => [w, mw[i] || []]));
    ld.tx = tw.flat().filter((t) => t && t.status === "complete").sort((a, b) => (b.created || 0) - (a.created || 0));
    ld.traded = traded || [];
    ld.bracket = bracket || [];
    const d = (drafts || []).sort((a, b) => (b.start_time || 0) - (a.start_time || 0))[0];
    ld.draft = d ? { ...d, picks: await safe(`${SLEEPER}/draft/${d.draft_id}/picks`) } : null;
    ld.names = {};
    for (const pk of ld.draft?.picks || []) if (pk.metadata) ld.names[pk.player_id] = `${pk.metadata.first_name || ""} ${pk.metadata.last_name || ""}`.trim();
    ld.extras = true;
  });
  return ld.extrasLoading;
}

// Make sure the synced league is loaded (with projections and the extras), whichever tab you're on
async function ensureLeague() {
  if (!S.sync) return false;
  await loadFuture();
  if (!S.leagueData) await syncLeague(S.sync.league_id, S.sync.user_id, S.sync.source || "sleeper");
  if (!S.leagueData) return false;
  await loadLeagueExtras();
  return true;
}

const pname = (id) => S.byId[id]?.name || S.leagueData?.names?.[id] || (/^[A-Z]{2,3}$/.test(id) ? `${id} defense` : "a player");
const ppos = (id) => S.byId[id]?.pos || "";
const rosterPts = (st, k) => (st?.[k] || 0) + (st?.[`${k}_decimal`] || 0) / 100;
const isFaab = () => S.leagueData?.league.settings?.waiver_type === 2;
// weeks whose results are final
const doneWeeks = () => Object.keys(S.leagueData?.weekly || {}).map(Number).filter((w) => w < S.data.week).sort((a, b) => a - b);

// Standings rows with everything Sleeper keeps, plus each team's all-play record (its score against every other
// team every week) and best possible lineup points
function standingsRows() {
  const ld = S.leagueData;
  const allPlay = {};
  for (const w of doneWeeks()) {
    const pts = (ld.weekly[w] || []).map((m) => [m.roster_id, m.points || 0]);
    for (const [rid, v] of pts) {
      const a = (allPlay[rid] ??= { w: 0, l: 0, t: 0 });
      for (const [rid2, v2] of pts) if (rid2 !== rid) { if (v > v2) a.w++; else if (v < v2) a.l++; else a.t++; }
    }
  }
  const rows = ld.rosters.map((r) => {
    const st = r.settings || {};
    const games = (st.wins || 0) + (st.losses || 0) + (st.ties || 0);
    return {
      r, id: r.roster_id, w: st.wins || 0, l: st.losses || 0, t: st.ties || 0, games,
      pf: rosterPts(st, "fpts"), pa: rosterPts(st, "fpts_against"), max: st.ppts != null ? rosterPts(st, "ppts") : null,
      streak: r.metadata?.streak || "", last: (r.metadata?.record || "").slice(-5),
      allPlay: allPlay[r.roster_id] || null, waiver: st.waiver_position, faabLeft: isFaab() ? (ld.league.settings.waiver_budget || 0) - (st.waiver_budget_used || 0) : null,
      moves: st.total_moves, ros: bestLineup(r.players || [], leagueSlots()).total,
    };
  }).sort((a, b) => b.w - a.w || a.l - b.l || b.pf - a.pf);
  rows.forEach((x, i) => { x.place = i + 1; });
  const byPf = [...rows].sort((a, b) => b.pf - a.pf);
  rows.forEach((x) => { x.pfRank = byPf.indexOf(x) + 1; });
  return rows;
}

const recText = (x) => `${x.w}-${x.l}${x.t ? `-${x.t}` : ""}`;
const streakText = (s) => (!s ? "" : s.endsWith("W") ? `won ${s.slice(0, -1)} in a row` : s.endsWith("L") ? `lost ${s.slice(0, -1)} in a row` : s);

function leagueStandings() {
  const ld = S.leagueData;
  if (!ld.extras) { loadLeagueExtras().then(() => S.tab === "league" && renderLeagueTab()); }
  const rows = standingsRows();
  const cut = ld.league.settings?.playoff_teams;
  const rosRank = new Map([...rows].sort((a, b) => b.ros - a.ros).map((x, i) => [x.id, i + 1]));
  const hasMax = rows.some((x) => x.max != null);
  return `<div class="tbl-wrap"><table class="tbl stand">
    <thead><tr><th class="l">#</th><th class="l">Team</th><th>Record</th><th>Points for</th><th>Against</th>${hasMax ? `<th class="hide-sm" title="Points if the best possible lineup had started every week">Max</th>` : ""}<th class="hide-sm" title="Record if you played every team every week">All-play</th><th class="hide-sm">Streak</th>${isFaab() ? `<th class="hide-sm">Budget left</th>` : `<th class="hide-sm">Waiver</th>`}<th class="hide-sm" title="Rank of each team's best lineup for the rest of the season">Rest of season</th></tr></thead>
    <tbody>${rows.map((x) => `<tr class="${x.id === S.sync.roster_id ? "me" : ""} ${cut && x.place === cut ? "cutline" : ""}">
      <td class="rk">${x.place}</td>
      <td class="l"><b>${esc(teamName(x.id))}</b><div class="small muted">${esc(managerName(x.id))}</div></td>
      <td>${recText(x)}</td>
      <td>${fmtPts(x.pf)}<div class="small muted">${ordinal(x.pfRank)}</div></td>
      <td>${fmtPts(x.pa)}</td>
      ${hasMax ? `<td class="hide-sm">${x.max != null ? fmtPts(x.max) : "-"}</td>` : ""}
      <td class="hide-sm">${x.allPlay ? recText(x.allPlay) : "-"}</td>
      <td class="hide-sm">${esc(x.streak || "-")}</td>
      <td class="hide-sm">${isFaab() ? `$${x.faabLeft}` : x.waiver ?? "-"}</td>
      <td class="hide-sm">#${rosRank.get(x.id)}</td>
    </tr>`).join("")}</tbody>
  </table></div>
  <p class="note">From ${S.sync.source === "espn" ? "ESPN" : "Sleeper"}.${cut ? ` The top ${cut} make the playoffs${ld.league.settings?.playoff_week_start ? ` (starting week ${ld.league.settings.playoff_week_start})` : ""}: the line is under ${ordinal(cut)} place.` : ""} All-play is your record if you'd played every team every week, which takes schedule luck out. Rest of season ranks each team's best lineup by projected points the rest of the way. On a phone, turn sideways for every column.</p>`;
}

function managerName(rosterId) {
  const ld = S.leagueData;
  const r = ld.rosters.find((x) => x.roster_id === rosterId);
  return ld.users.find((x) => x.user_id === r?.owner_id)?.display_name || "";
}

// Past weeks' results (Sleeper's final scores) or this week's live matchups
function leagueMatchups() {
  const ld = S.leagueData;
  if (S.sync.source === "espn" || S.sync.source === "yahoo") return `<p class="note">Weekly matchups are available for Sleeper leagues for now.</p>`;
  const wk = S.muWeek || S.data.week;
  const pick = `<div class="gtool"><label class="wk-l">Week <select data-mu-week>${Array.from({ length: S.data.week }, (_, i) => i + 1).map((w) => `<option value="${w}" ${w === wk ? "selected" : ""}>${w}${w === S.data.week ? " (now)" : ""}</option>`).join("")}</select></label></div>`;
  if (wk !== S.data.week) {
    if (!ld.extras) { loadLeagueExtras().then(() => S.tab === "league" && renderLeagueTab()); return pick + `<div class="empty">Loading week ${wk}...</div>`; }
    const groups = {};
    for (const m of ld.weekly[wk] || []) if (m.matchup_id != null) (groups[m.matchup_id] ??= []).push(m);
    const cards = Object.values(groups).filter((g) => g.length === 2).sort((a, b) => (b.some((x) => x.roster_id === S.sync.roster_id)) - (a.some((x) => x.roster_id === S.sync.roster_id)));
    if (!cards.length) return pick + `<p class="note">No matchups in week ${wk}.</p>`;
    return pick + cards.map(([a, b]) => {
      const col = (x, o) => {
        const pts = x.starters_points || [];
        return `<div class="mu-side ${x.roster_id === S.sync.roster_id ? "me" : ""}">
          <div class="mu-name">${esc(teamName(x.roster_id))}</div>
          <div class="mu-pts num ${(x.points || 0) > (o.points || 0) ? "lead" : ""}">${fmtPts(x.points || 0)}</div>
          <div class="muted small">${(x.points || 0) > (o.points || 0) ? "Won" : (x.points || 0) < (o.points || 0) ? "Lost" : "Tied"}</div>
          ${(x.starters || []).map((id, i) => id && id !== "0" ? `<div class="mu-row" ${S.byId[id] ? `data-open="${id}"` : ""}><span>${ppos(id) ? `<span class="pos ${ppos(id)}">${ppos(id)}</span> ` : ""}${esc(pname(id))}</span><span class="num">${fmtPts(pts[i] || 0)}</span></div>` : "").join("")}
        </div>`;
      };
      return `<div class="mu-card">${col(a, b)}${col(b, a)}</div>`;
    }).join("") + `<p class="note">Week ${wk} final scores from Sleeper.</p>`;
  }
  if (!ld.matchups) {
    getJSON(`${SLEEPER}/league/${ld.league.league_id}/matchups/${S.data.week}`)
      .then((m) => { ld.matchups = m || []; if (S.tab === "league") renderLeagueTab(); })
      .catch(() => { ld.matchups = []; if (S.tab === "league") renderLeagueTab(); });
    return pick + `<div class="empty">Loading this week's matchups...</div>`;
  }
  return pick + liveMatchups();
}

// Free agents: who on waivers beats the players you have, by projected points per game for the rest of the
// season, and how many Sleeper users added each one in the last day
function leagueFreeAgents() {
  const ld = S.leagueData;
  if (!S.trend) loadTrending().then(() => S.tab === "league" && renderLeagueTab());
  const rostered = new Set(ld.rosters.flatMap((r) => [...(r.players || []), ...(r.reserve || []), ...(r.taxi || [])]));
  const okPos = usePositions(["QB", "RB", "WR", "TE", "K", "DEF"]).filter((x) => leagueSlots().some((s2) => (SLOT_ELIG[s2] || []).includes(x)));
  const pos = okPos.includes(S.faPos) ? S.faPos : "ALL";
  const sort = S.faSort || "fit";
  // your players expected to play (someone out for the year or without a team isn't a fair comparison)
  const mineAt = (ps) => (myRoster().players || []).map((id) => S.byId[id]).filter((q) => q && q.pos === ps && rosPerGame(q) >= 1).sort((a, b) => rosPerGame(a) - rosPerGame(b));
  const adds = (id) => S.trend?.add[id] || 0;
  const pool = rosPool().filter((p) => !rostered.has(p.id) && okPos.includes(p.pos) && (pos === "ALL" || p.pos === pos) && (rosPts(p) >= 5 || adds(p.id) > 0));
  // the weakest player of yours he beats
  const beats = (p) => mineAt(p.pos).find((q) => rosPerGame(p) > rosPerGame(q) + 0.5) || null;
  const rows = pool.map((p) => ({ p, beat: beats(p), add: adds(p.id), pg: rosPerGame(p) }))
    .sort(sort === "adds" ? (a, b) => b.add - a.add : sort === "proj" ? (a, b) => b.pg - a.pg
      : (a, b) => (!!b.beat - !!a.beat) || (b.beat ? (b.pg - rosPerGame(b.beat)) - (a.pg - rosPerGame(a.beat)) : 0) || b.pg - a.pg)
    .slice(0, 40);
  const ups = rows.filter((x) => x.beat);
  const nextWeeks = [];
  for (let w = S.data.week + 1; w <= Math.min(18, S.data.week + 3); w++) nextWeeks.push(w);
  const addsText = (n) => (n >= 1000 ? `${fmt(n / 1000, n >= 10000 ? 0 : 1)}K` : `${n}`);
  return `${ups.length ? `<div class="fa-ups"><b>${ups.length} free agent${ups.length === 1 ? " is" : "s are"} projected to score more than someone on your team</b>
      <ul>${ups.slice(0, 5).map((x) => `<li><span data-open="${x.p.id}" class="linkish">${esc(x.p.name)}</span> (${x.p.pos}, ${fmt(x.pg, 1)} a game) over your <span data-open="${x.beat.id}" class="linkish">${esc(x.beat.name)}</span> (${fmt(rosPerGame(x.beat), 1)} a game)${x.add ? `, added by ${addsText(x.add)} Sleeper users today` : ""}</li>`).join("")}</ul></div>`
      : `<div class="fa-ups none">No free agent is projected to score more than the players you have at ${pos === "ALL" ? "any position" : `${pos}`}.</div>`}
    <div class="gtool">${seg("data-fa-pos", pos, ["ALL", ...okPos].map((x) => [x, x === "ALL" ? "All" : x]), "Position")}
      ${seg("data-fa-sort", sort, [["fit", "Best for you"], ["proj", "Projection"], ["adds", "Most added"]], "Sort")}</div>
    <div class="fa-list">${rows.map(({ p, beat, add, pg }) => {
      const fut = futureRows(p);
      const g = S.games[p.game_id];
      const week = g && g.state === "pre" ? `wk ${S.data.week} proj ${fmtPts(projPts(p))}` : g ? `wk ${S.data.week} ${current(p) && !current(p).none ? fmtPts(livePPR(p)) : g.state === "post" ? "did not play" : "0.00"}${g.state === "in" ? " so far" : ""}` : `wk ${S.data.week} bye`;
      return `<div class="fa-row ${beat ? "up" : ""}" data-open="${p.id}">
        ${avatar(p)}
        <div class="fa-main"><div><b>${esc(p.name)}</b>${injBadge(p)} <span class="muted small">${p.pos} ${p.freeAgent ? "free agent" : p.team}${byesLeft(p).length ? ` · bye ${byesLeft(p).join(", ")}` : ""}</span></div>
          <div class="small muted">${week}${nextWeeks.map((wk) => { const x = fut.find((y) => y.w === wk); return ` · wk ${wk} ${x ? fmtPts(x.pts) : byesLeft(p).includes(wk) ? "bye" : "-"}`; }).join("")}</div>
          ${beat ? `<div class="fa-beat">Better than your ${esc(beat.name)} by ${fmt(pg - rosPerGame(beat), 1)} a game</div>` : ""}</div>
        <div class="fa-side">${gradeChip(p)}<b class="num">${fmt(pg, 1)}</b><span class="small muted">a game</span>${add ? `<span class="fa-add">${addsText(add)} adds</span>` : ""}</div>
      </div>`;
    }).join("") || `<div class="empty">No free agents with real projections here.</div>`}</div>
    <p class="note">Players on no roster in your league. "Better than" is the weakest player of yours at his position he's projected to outscore (points per game for the rest of the season, so byes and injuries don't skew it). Adds today: how many Sleeper users added him in the last 24 hours, across all Sleeper leagues.</p>`;
}

// Trades, waiver claims and free agent pickups, newest first
function leagueActivity() {
  const ld = S.leagueData;
  if (S.sync.source && S.sync.source !== "sleeper") return `<p class="note">League activity is available for Sleeper leagues for now.</p>`;
  if (!ld.extras) { loadLeagueExtras().then(() => S.tab === "league" && renderLeagueTab()); return `<div class="empty">Loading league activity...</div>`; }
  const kind = S.txKind || "all";
  const list = ld.tx.filter((t) => kind === "all" || t.type === kind || (kind === "waiver" && t.type === "free_agent"));
  const who = (rid) => `<b>${esc(teamName(rid))}</b>`;
  const plist = (ids) => ids.map((id) => `<span ${S.byId[id] ? `data-open="${id}" class="linkish"` : ""}>${esc(pname(id))}</span>${ppos(id) ? ` <span class="muted">${ppos(id)}</span>` : ""}`).join(", ");
  const when = (ms) => (ms ? new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "");
  const item = (t) => {
    const adds = Object.entries(t.adds || {}), drops = Object.entries(t.drops || {});
    if (t.type === "trade") {
      const sides = t.roster_ids.map((rid) => {
        const got = adds.filter(([, r]) => r === rid).map(([id]) => id);
        const picks = (t.draft_picks || []).filter((pk) => pk.owner_id === rid).map((pk) => `${pk.season} round ${pk.round} pick${pk.roster_id !== rid ? ` (${esc(teamName(pk.roster_id))}'s)` : ""}`);
        const faab = (t.waiver_budget || []).filter((x) => x.receiver === rid).map((x) => `$${x.amount} of budget`);
        return `<div>${who(rid)} gets ${[plist(got), ...picks, ...faab].filter(Boolean).join(", ") || "nothing"}</div>`;
      }).join("");
      return `<div class="tx trade"><span class="tx-k">Trade</span><div>${sides}</div><span class="muted small">Wk ${t.leg} · ${when(t.created)}</span></div>`;
    }
    const rid = t.roster_ids?.[0];
    const bid = t.settings?.waiver_bid;
    return `<div class="tx"><span class="tx-k ${t.type}">${t.type === "waiver" ? "Waiver" : "Free agent"}</span>
      <div>${who(rid)} ${adds.length ? `added ${plist(adds.map(([id]) => id))}${bid != null && isFaab() ? ` for $${bid}` : ""}` : ""}${adds.length && drops.length ? " and " : ""}${drops.length ? `dropped ${plist(drops.map(([id]) => id))}` : ""}</div>
      <span class="muted small">Wk ${t.leg} · ${when(t.created)}</span></div>`;
  };
  return `<div class="gtool">${seg("data-tx-kind", kind, [["all", "All"], ["trade", "Trades"], ["waiver", "Pickups"]], "Type")}</div>
    <div class="tx-list">${list.slice(0, 80).map(item).join("") || `<div class="empty">No ${kind === "trade" ? "trades" : kind === "waiver" ? "pickups" : "moves"} yet this season.</div>`}</div>`;
}

// The draft board, with how each pick is projected now
function leagueDraft() {
  const ld = S.leagueData;
  if (S.sync.source && S.sync.source !== "sleeper") return `<p class="note">The draft board is available for Sleeper leagues for now.</p>`;
  if (!ld.extras) { loadLeagueExtras().then(() => S.tab === "league" && renderLeagueTab()); return `<div class="empty">Loading the draft...</div>`; }
  const d = ld.draft;
  if (!d || !(d.picks || []).length) return `<p class="note">No draft results found for this league.</p>`;
  const teams = d.settings?.teams || ld.rosters.length;
  const mineOnly = !!S.draftMine;
  const picks = d.picks.filter((pk) => !mineOnly || pk.roster_id === S.sync.roster_id);
  const rounds = {};
  for (const pk of picks) (rounds[pk.round] ??= []).push(pk);
  return `<div class="gtool"><button class="tbtn ${mineOnly ? "on" : ""}" data-draft-mine aria-pressed="${mineOnly}">My picks</button>
      <span class="note">${esc({ snake: "Snake", linear: "Linear", auction: "Auction" }[d.type] || d.type || "")} draft · ${d.settings?.rounds || Object.keys(rounds).length} rounds${d.start_time ? ` · ${new Date(d.start_time).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}` : ""}</span></div>
    ${Object.entries(rounds).map(([rd, list]) => `<div class="draft-rd"><h3>Round ${rd}</h3>${list.sort((a, b) => a.pick_no - b.pick_no).map((pk) => {
      const p = S.byId[pk.player_id];
      const m = pk.metadata || {};
      const slot = ((pk.pick_no - 1) % teams) + 1;
      return `<div class="dp ${pk.roster_id === S.sync.roster_id ? "me" : ""}" ${p ? `data-open="${p.id}"` : ""}>
        <span class="num muted">${rd}.${String(slot).padStart(2, "0")}</span>
        <span><b>${esc(p?.name || `${m.first_name || ""} ${m.last_name || ""}`.trim())}</b> <span class="muted">${esc(m.position || p?.pos || "")} ${esc(m.team || p?.team || "")}</span>${m.amount ? ` <span class="muted">$${esc(m.amount)}</span>` : ""}${pk.is_keeper ? ` <span class="muted">keeper</span>` : ""}</span>
        <span class="small muted">${esc(teamName(pk.roster_id))}</span>
        <span>${p ? gradeChip(p) : ""}</span></div>`;
    }).join("")}</div>`).join("")}
    <p class="note">The colored rank is where each player is projected now (points per game for the rest of the season at his position), so you can see which picks are paying off.</p>`;
}

// Every setting worth knowing
const SCORE_NAMES = {
  pass_yd: "Passing yard", pass_td: "Passing TD", pass_int: "Interception thrown", pass_2pt: "2-pt pass", pass_cmp: "Completion", pass_inc: "Incompletion", pass_sack: "Sacked", pass_fd: "Passing first down",
  rush_yd: "Rushing yard", rush_td: "Rushing TD", rush_2pt: "2-pt run", rush_att: "Carry", rush_fd: "Rushing first down",
  rec: "Reception", rec_yd: "Receiving yard", rec_td: "Receiving TD", rec_2pt: "2-pt catch", rec_fd: "Receiving first down",
  bonus_rec_te: "Bonus per TE catch", bonus_rec_rb: "Bonus per RB catch", bonus_rec_wr: "Bonus per WR catch",
  fum_lost: "Fumble lost", fum: "Fumble", fum_rec_td: "Fumble recovery TD", st_td: "Special teams TD",
  bonus_pass_yd_300: "300+ passing yards", bonus_pass_yd_400: "400+ passing yards", bonus_rush_yd_100: "100+ rushing yards", bonus_rush_yd_200: "200+ rushing yards",
  bonus_rec_yd_100: "100+ receiving yards", bonus_rec_yd_200: "200+ receiving yards", bonus_pass_td_50p: "50+ yard TD pass", bonus_rush_td_40p: "40+ yard TD run", bonus_rec_td_40p: "40+ yard TD catch",
};
function leagueSettings() {
  const ld = S.leagueData, L = ld.league, st = L.settings || {};
  const wt = { 0: "Rolling waivers", 1: "Reverse standings waivers", 2: "FAAB (blind bidding)" }[st.waiver_type];
  const type = { 0: "Redraft", 1: "Keeper", 2: "Dynasty" }[st.type];
  const slots = (L.roster_positions || []);
  const count = (x) => slots.filter((y) => y === x).length;
  const facts = [
    ["Format", [type, `${L.total_rosters || ld.rosters.length} teams`, L.season ? `${L.season} season` : ""].filter(Boolean).join(" · ")],
    ["Lineup", lineupSummary()],
    count("IR") || st.reserve_slots ? ["IR spots", String(st.reserve_slots ?? count("IR"))] : null,
    st.taxi_slots ? ["Taxi squad", String(st.taxi_slots)] : null,
    ["Scoring", leagueSummary(L.scoring_settings)],
    wt ? ["Waivers", `${wt}${st.waiver_type === 2 ? `, $${st.waiver_budget} budget` : ""}${st.waiver_clear_days != null ? `, players clear after ${st.waiver_clear_days} day${st.waiver_clear_days === 1 ? "" : "s"}` : ""}${st.daily_waivers ? ", processed daily" : ""}`] : null,
    st.trade_deadline ? ["Trade deadline", st.trade_deadline >= 99 ? "None" : `Week ${st.trade_deadline}`] : null,
    st.playoff_teams ? ["Playoffs", `${st.playoff_teams} teams, starting week ${st.playoff_week_start || "?"}${st.playoff_round_type === 1 ? ", two-week championship" : ""}`] : null,
    ld.draft ? ["Draft", `${{ snake: "Snake", linear: "Linear", auction: "Auction" }[ld.draft.type] || ld.draft.type}, ${ld.draft.settings?.rounds || "?"} rounds`] : null,
    st.max_keepers ? ["Keepers", `Up to ${st.max_keepers}`] : null,
    st.disable_trades ? ["Trades", "Turned off"] : null,
  ].filter(Boolean);
  const scoring = Object.entries(L.scoring_settings || {}).filter(([, v]) => v);
  const named = scoring.filter(([k]) => SCORE_NAMES[k]), rest = scoring.filter(([k]) => !SCORE_NAMES[k]);
  const num = (v) => String(+(+v).toFixed(2));
  const val = (k, v) => (k.endsWith("_yd") ? `1 point per ${num(1 / v)} yards` : `${v > 0 ? "+" : ""}${num(v)}`);
  return `<div class="set-grid">${facts.map(([k, v]) => `<div class="set-f"><span class="muted">${k}</span><b>${esc(v)}</b></div>`).join("")}</div>
    <h3>Scoring</h3>
    <div class="set-sc">${named.map(([k, v]) => `<div><span>${SCORE_NAMES[k]}</span><b class="num">${esc(val(k, v))}</b></div>`).join("")}</div>
    ${rest.length ? `<details class="set-more"><summary>All ${rest.length} other scoring settings</summary><div class="set-sc">${rest.map(([k, v]) => `<div><span>${esc(k.replace(/_/g, " "))}</span><b class="num">${esc(String(v))}</b></div>`).join("")}</div></details>` : ""}`;
}

// The top of My team: your record, place, scoring rank and this week's opponent
function myTeamSummary() {
  const ld = S.leagueData;
  const rows = standingsRows();
  const me = rows.find((x) => x.id === S.sync.roster_id);
  if (!me) return "";
  const cur = (ld.matchups || ld.weekly?.[S.data.week] || []);
  const mine = cur.find((m) => m.roster_id === S.sync.roster_id);
  const opp = mine && cur.find((m) => m.matchup_id === mine.matchup_id && m.roster_id !== mine.roster_id);
  const cut = ld.league.settings?.playoff_teams;
  return `<div class="my-sum">
    <div><span class="muted">Record</span><b>${recText(me)}</b><span class="small muted">${ordinal(me.place)} of ${rows.length}${cut ? me.place <= cut ? ", in a playoff spot" : `, ${ordinal(cut)} makes the playoffs` : ""}</span></div>
    <div><span class="muted">Points for</span><b>${fmtPts(me.pf)}</b><span class="small muted">${ordinal(me.pfRank)} in the league${me.games ? ` · ${fmt(me.pf / me.games, 1)} a week` : ""}</span></div>
    <div><span class="muted">Points against</span><b>${fmtPts(me.pa)}</b>${me.allPlay ? `<span class="small muted">All-play ${recText(me.allPlay)}</span>` : ""}</div>
    ${me.streak ? `<div><span class="muted">Streak</span><b>${esc(me.streak)}</b><span class="small muted">${esc(streakText(me.streak))}</span></div>` : ""}
    ${opp ? `<div><span class="muted">This week</span><b>vs ${esc(teamName(opp.roster_id))}</b><span class="small muted">${esc(recText(rows.find((x) => x.id === opp.roster_id) || { w: 0, l: 0, t: 0 }))}</span></div>` : ""}
    ${isFaab() ? `<div><span class="muted">Budget left</span><b>$${me.faabLeft}</b><span class="small muted">of $${ld.league.settings.waiver_budget}</span></div>` : me.waiver != null ? `<div><span class="muted">Waiver order</span><b>${ordinal(me.waiver)}</b></div>` : ""}
  </div>`;
}

function renderLeagueTab() {
  const gate = leagueGate("Sync your Sleeper league with just your username, or an ESPN league by its ID, to see your team, this week's matchups, standings, every roster, the best free agents and trade ideas.");
  if (gate) { $("#main").innerHTML = `<h2>League</h2>${gate}`; return; }
  if (!S.future) { $("#main").innerHTML = `<h2>League</h2><div class="empty">Loading projections...</div>`; loadFuture().then(() => { if (S.tab === "league") renderLeagueTab(); }); return; }
  const view = S.leagueView || "team";
  const body = { team: leagueMyTeam, matchups: leagueMatchups, standings: leagueStandings, teams: leagueTeams, fa: leagueFreeAgents, activity: leagueActivity, draft: leagueDraft, settings: leagueSettings }[view]();
  $("#main").innerHTML = `<h2>League <small>${esc(scoringName())}</small></h2><div class="card league">${leagueHead()}
    <div class="lv-scroll">${seg("data-league-view", view, [["team", "My team"], ["matchups", "Matchups"], ["standings", "Standings"], ["teams", "Teams"], ["fa", "Free agents"], ["activity", "Activity"], ["draft", "Draft"], ["settings", "Settings"]], "View")}</div>
    <div class="league-body">${body}</div></div>`;
}

// This week's points for start/sit: our pregame projection (Sleeper's, adjusted for the matchup) for games not
// started, live points plus what's left for games in progress, final points after; 0 on a bye
function weekPts(p) {
  const g = S.games[p.game_id];
  if (!g) return 0;
  if (g.state === "pre") return ourProj(p) || 0;
  const live = current(p) && !current(p).none ? livePPR(p) || 0 : 0;
  return g.state === "in" ? live + (ourProj(p) || 0) * remaining(g) : live;
}

// This week's best lineup, respecting locks: a player whose game has started stays where your league has him
// (Sleeper lists starters in slot order). Only players who haven't played yet can move.
function weekLineup(r) {
  const slots = leagueSlots();
  const set = r.starters || [];
  const started = (id) => { const p = S.byId[id]; const g = p && S.games[p.game_id]; return !!g && g.state !== "pre"; };
  const fixed = new Array(slots.length).fill(null);
  const knowsSlots = set.length === slots.length;
  if (knowsSlots) set.forEach((id, i) => { if (id && id !== "0" && S.byId[id] && started(id)) fixed[i] = id; });
  const lockedBench = knowsSlots ? (r.players || []).filter((id) => started(id) && !set.includes(id)) : [];
  const taken = new Set([...fixed.filter(Boolean), ...lockedBench]);
  const pool = (r.players || []).filter((id) => !taken.has(id) && S.byId[id]).map((id) => ({ p: S.byId[id], v: weekPts(S.byId[id]) })).sort((a, b) => b.v - a.v);
  const used = new Set();
  const starters = slots.map((slot, i) => (fixed[i] ? { slot, pick: { p: S.byId[fixed[i]], v: weekPts(S.byId[fixed[i]]), locked: true } } : { slot, pick: null }));
  const order = starters.map((x, i) => ({ x, i })).filter(({ x }) => !x.pick).sort((a, b) => (SLOT_ELIG[a.x.slot]?.length ?? 9) - (SLOT_ELIG[b.x.slot]?.length ?? 9));
  for (const { x } of order) {
    const pick = pool.find((c) => !used.has(c.p.id) && (SLOT_ELIG[x.slot] || []).includes(c.p.pos));
    if (pick) { used.add(pick.p.id); x.pick = pick; }
  }
  const bench = [...pool.filter((c) => !used.has(c.p.id)), ...lockedBench.map((id) => ({ p: S.byId[id], v: weekPts(S.byId[id]), locked: true }))].sort((a, b) => b.v - a.v);
  return { starters, bench, total: starters.reduce((a, x) => a + (x.pick?.v || 0), 0), knowsSlots };
}

function startSit() {
  const r = myRoster(), slots = leagueSlots();
  const lu = weekLineup(r);
  const row = (x, slot) => {
    const p = x.p, g = S.games[p.game_id];
    return `<div class="lu"><span class="slot">${slot ? slotLabel(slot) : "BN"}</span>
      <span data-open="${p.id}" class="lu-p">${esc(p.name)} <span class="muted">${p.pos} ${p.team}</span>${injBadge(p)}
        <span class="lu-sub">${g ? `${p.home ? "vs" : "@"} ${p.opp} ${rankChip(p.opp, p.pos)} · ${esc(gameStatus(g))}` : `<span class="muted">bye or not playing</span>`}</span></span>
      <span class="num">${x.locked ? `<span class="lock" title="His game has started: locked">\u{1F512}\uFE0E</span> ` : ""}${fmtPts(x.v)}</span></div>`;
  };
  // close calls: the weakest starter each bench player could replace
  const calls = [];
  for (const b of lu.bench.filter((x) => !x.locked).slice(0, 6)) {
    const swaps = lu.starters.filter((s2) => s2.pick && !s2.pick.locked && (SLOT_ELIG[s2.slot] || []).includes(b.p.pos));
    if (!swaps.length) continue;
    const weakest = swaps.reduce((a, c) => (c.pick.v < a.pick.v ? c : a));
    const gap = weakest.pick.v - b.v;
    if (gap < 2.5) calls.push(`<li><b>${esc(weakest.pick.p.name)}</b> over <b>${esc(b.p.name)}</b> is close: ${fmtPts(weakest.pick.v)} vs ${fmtPts(b.v)} projected.</li>`);
  }
  // compare with the lineup set in Sleeper
  let diff = "";
  if (r.starters?.length) {
    const set = new Set(r.starters.filter((id) => id && id !== "0"));
    const ours = new Set(lu.starters.filter((s2) => s2.pick).map((s2) => s2.pick.p.id));
    const out = [...set].filter((id) => !ours.has(id) && S.byId[id]), inn = [...ours].filter((id) => !set.has(id));
    const setTotal = [...set].reduce((a, id) => a + (S.byId[id] ? weekPts(S.byId[id]) : 0), 0);
    diff = out.length || inn.length
      ? `<div class="verdict">Your Sleeper lineup differs: start ${inn.map((id) => `<b>${esc(S.byId[id].name)}</b>`).join(", ")} instead of ${out.map((id) => `<b>${esc(S.byId[id].name)}</b>`).join(", ")} for about <b>+${fmtPts(lu.total - setTotal)}</b> projected points.</div>`
      : `<div class="verdict even">Your Sleeper lineup matches ours.</div>`;
  }
  return `<h3>Start / sit, week ${S.data.week}</h3>${diff}
    ${lu.starters.map((s2) => (s2.pick ? row(s2.pick, s2.slot) : `<div class="lu"><span class="slot">${slotLabel(s2.slot)}</span><span class="muted">empty</span><span></span></div>`)).join("")}
    <div class="lu tot"><span></span><span>Projected this week</span><span class="num">${fmtPts(lu.total)}</span></div>
    ${lu.bench.length ? `<div class="bench-h">Bench</div>${lu.bench.map((x) => row(x, null)).join("")}` : ""}
    ${calls.length ? `<h3>Close calls</h3><ul class="calls">${calls.join("")}</ul>` : ""}
    <p class="note">${lu.knowsSlots ? "Players whose games have started are locked where your league has them; only the rest can move. " : ""}This week's numbers are our pregame projections (Sleeper's, adjusted for the matchup), live points plus what's left once a game starts, and final points after. Matchup ranks: #1 is the defense that allows the fewest fantasy points to that position this season.</p>`;
}

function leagueMyTeam() {
  if (!S.leagueData.extras) loadLeagueExtras().then(() => S.tab === "league" && (S.leagueView || "team") === "team" && renderLeagueTab());
  return myTeamSummary() + needsBar() + `<div class="league-grid"><div>${startSit()}</div>
    <div>${lineupHtml(myRoster().players, "Best lineup, rest of season")}
      <p class="note">See <a href="#" data-go-trade>trade ideas and top targets</a> for your weak spots, or the <a href="#" data-league-view="fa">best free agents</a>.</p></div></div>`;
}


function leagueTeams() {
  const ld = S.leagueData;
  return ld.rosters.map((r) => `<details class="team-d" ${r.roster_id === S.sync.roster_id ? "open" : ""}>
      <summary><b>${esc(teamName(r.roster_id))}</b> <span class="muted">${esc(managerName(r.roster_id))} · ${(r.settings?.wins ?? 0)}-${(r.settings?.losses ?? 0)}${r.settings?.ties ? `-${r.settings.ties}` : ""} · ${fmtPts(rosterPts(r.settings, "fpts"))} points for</span></summary>
      ${lineupHtml(r.players, "Best lineup")}
    </details>`).join("");
}


// This week's matchups (Sleeper leagues): each side's starters scored live in the league's scoring, plus what's
// left of their projections for the rest of their games
function liveMatchups() {
  const ld = S.leagueData;
  const side = (m) => {
    let live = 0, proj = 0;
    const rows = (m.starters || []).filter((id) => id && id !== "0").map((id) => {
      const p = S.byId[id];
      if (!p) return { id, name: id, live: 0, left: 0 };
      const g = S.games[p.game_id];
      const pts = current(p) ? livePPR(p) || 0 : 0;
      const left = !g ? 0 : g.state === "pre" ? projPts(p) || 0 : g.state === "in" ? (projPts(p) || 0) * remaining(g) : 0;
      live += pts; proj += pts + left;
      return { p, pts, left, g };
    });
    return { m, rows, live, proj };
  };
  const groups = {};
  for (const m of ld.matchups) if (m.matchup_id != null) (groups[m.matchup_id] ??= []).push(side(m));
  const cards = Object.values(groups).filter((g) => g.length === 2).sort((a, b) => (b.some((x) => x.m.roster_id === S.sync.roster_id)) - (a.some((x) => x.m.roster_id === S.sync.roster_id)));
  if (!cards.length) return `<p class="note">No matchups this week (bye week, playoffs or a league without head-to-head games).</p>`;
  return cards.map(([a, b]) => {
    const col = (x, other) => `<div class="mu-side ${x.m.roster_id === S.sync.roster_id ? "me" : ""}">
      <div class="mu-name">${esc(teamName(x.m.roster_id))}</div>
      <div class="mu-pts num ${x.live > other.live ? "lead" : ""}">${fmtPts(x.live)}</div>
      <div class="muted small">projected ${fmtPts(x.proj)}</div>
      ${x.rows.map((r) => r.p ? `<div class="mu-row" data-open="${r.p.id}"><span><span class="pos ${r.p.pos}">${r.p.pos}</span> ${esc(r.p.name)}</span><span class="num">${r.g && r.g.state !== "pre" ? fmtPts(r.pts) : `<span class="muted">${fmtPts(r.left)}</span>`}</span></div>` : "").join("")}
    </div>`;
    return `<div class="mu-card">${col(a, b)}${col(b, a)}</div>`;
  }).join("") + `<p class="note">Live points use this site's live stats in your league's scoring. Projected adds each starter's projection for the time left in his game (all of it if he hasn't played yet). Sleeper's own numbers can differ slightly until stats are final.</p>`;
}

// Players on other teams who'd add the most to your best lineup for the rest of the season, at the positions you
// need. "Fair price" is his trade value (rest-of-season points over a waiver player).
function topTargets() {
  const ld = S.leagueData, slots = leagueSlots(), me = myRoster();
  const base = bestLineup(me.players || [], slots).total;
  const repl = replacementLevels();
  const want = S.ideaGet && S.ideaGet !== "ANY" ? S.ideaGet : null;
  const out = [];
  for (const r of ld.rosters) {
    if (r.roster_id === me.roster_id) continue;
    for (const id of r.players || []) {
      const p = S.byId[id];
      if (!p || !["QB", "RB", "WR", "TE"].includes(p.pos) || (want && p.pos !== want)) continue;
      const gain = bestLineup([...(me.players || []), id], slots).total - base;
      if (gain >= 10) out.push({ p, r, gain, week: weeklyPts(bestLineup([...(me.players || []), id], slots)) - weeklyPts(bestLineup(me.players || [], slots)), price: Math.max(0, rosPts(p) - (repl[p.pos] ?? 0)) });
    }
  }
  return out.sort((a, b) => b.gain - a.gain).slice(0, 8);
}

// Your team (and theirs, when the players come from one roster) before and after the trade on the calculator
function afterTradeHtml() {
  const ld = S.leagueData;
  if (!ld || S.sync?.roster_id == null || !S.trade.give.length || !S.trade.get.length) return "";
  const slots = leagueSlots();
  const me = myRoster();
  const myAfter = (me.players || []).filter((id) => !S.trade.give.includes(id)).concat(S.trade.get);
  const other = ld.rosters.find((r) => r.roster_id !== me.roster_id && S.trade.get.every((id) => (r.players || []).includes(id)));
  const ranksWith = (rid, ids) => {
    const saved = ld.rosters.find((r) => r.roster_id === rid).players;
    ld.rosters.find((r) => r.roster_id === rid).players = ids;
    const r = positionRanks()[rid];
    ld.rosters.find((x) => x.roster_id === rid).players = saved;
    return r;
  };
  const side = (rid, beforeIds, afterIds, label) => {
    const b = bestLineup(beforeIds, slots), a = bestLineup(afterIds, slots);
    const wb = weeklyPts(b), wa = weeklyPts(a);
    const rb = positionRanks()[rid] || {}, ra = ranksWith(rid, afterIds) || {};
    const incoming = new Set(afterIds.filter((id) => !beforeIds.includes(id)));
    const n = ld.rosters.length;
    return `<div class="card after">
      <h3>${label}</h3>
      <div class="after-sum"><span>About <b class="num">${fmtPts(wb)}</b> a week now</span><span class="${wa >= wb ? "up" : "down"}">→ <b class="num">${fmtPts(wa)}</b> after (${wa >= wb ? "+" : ""}${fmtPts(wa - wb)})</span></div>
      <div class="needs">${["QB", "RB", "WR", "TE"].filter((x) => rb[x]).map((pos) => `<span class="need ${ra[pos] < rb[pos] ? "strong" : ra[pos] > rb[pos] ? "weak" : ""}">${pos} ${rb[pos]}→<b>${ra[pos]}</b>/${n}</span>`).join("")}</div>
      ${lineupHtml(afterIds, "Lineup after the trade", incoming)}
    </div>`;
  };
  return `<h2>After the trade</h2><div class="after-grid">
    ${side(me.roster_id, me.players || [], myAfter, `Your team (${esc(teamName(me.roster_id))})`)}
    ${other ? side(other.roster_id, other.players || [], (other.players || []).filter((id) => !S.trade.get.includes(id)).concat(S.trade.give), esc(teamName(other.roster_id))) : ""}
  </div><p class="note">New starters are highlighted. Position ranks show where each team would stand in your league (1 = best). Weekly points are each starter's projected points per game when he plays.</p>`;
}

// ---- AI trade builder: Gemini proposes, the site's own numbers check every proposal

async function buildAiTrades() {
  const ld = S.leagueData;
  const slots = leagueSlots(), me = myRoster(), n = ld.rosters.length;
  const ranks = positionRanks();
  const repl = replacementLevels();
  const tv = (p) => Math.max(0, rosPts(p) - (repl[p.pos] ?? 0));
  const line = (id) => { const p = S.byId[id]; return p && ["QB", "RB", "WR", "TE"].includes(p.pos) ? `${p.name} (${p.pos} ${p.team}, ${gradeOf(p)?.label || "unranked"}, ${fmtPts(rosPerGame(p))}/g, value ${fmtPts(tv(p))}${injOf(p).status ? `, ${injOf(p).status}` : ""})` : null; };
  const want = $("#ai-want")?.value?.trim() || "";
  const pos = S.ideaGet && S.ideaGet !== "ANY" ? S.ideaGet : "";
  const context = [
    `Fantasy league: ${n} teams, lineup ${lineupSummary()}, scoring ${scoringName()}. Week ${S.data.week} of ${S.data.season}.`,
    `Trade value = rest-of-season points over a waiver player (the higher, the more valuable). A rank like WR14 means the 14th-best receiver by projected points per game.`,
    `MY TEAM (${teamName(me.roster_id)}), my position ranks (1 = best of ${n}): ${Object.entries(ranks[me.roster_id] || {}).map(([k, v]) => `${k} ${v}`).join(", ")}.`,
    `My players: ${(me.players || []).map(line).filter(Boolean).join("; ")}`,
    ...ld.rosters.filter((r) => r.roster_id !== me.roster_id).map((r) => `TEAM "${teamName(r.roster_id)}" ranks: ${Object.entries(ranks[r.roster_id] || {}).map(([k, v]) => `${k} ${v}`).join(", ")}. Players: ${(r.players || []).map(line).filter(Boolean).join("; ")}`),
  ].join("\n");
  const ask = `Propose 4 realistic trades for MY TEAM${pos ? ` that bring back a ${pos}` : ""}${want ? `. What I want: ${want}` : ""}.
Rules: each trade is with one other team; 1-for-1 or 2-for-1 (either way); the trade values on both sides should be within about 15% (a bit more is fine if it fills a position where the other team ranks poorly); help my weakest positions without creating a new hole; only use players listed for those teams, spelled exactly.
Reply with JSON only: {"trades":[{"team":"<team name exactly>","give":["<my player>"],"get":["<their player>"],"why":"<one or two sentences>"}]}`;
  S.aiBusy = true; S.aiTrades = null; S.aiMsg = "";
  renderTrade();
  try {
    const r = await fetch(`${WORKER_URL}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ json: true, messages: [{ role: "user", text: ask }], context }) });
    const d = await r.json();
    if (!d.text) throw new Error(d.error || "no answer");
    const raw = d.text.slice(d.text.indexOf("{"), d.text.lastIndexOf("}") + 1);
    const proposals = JSON.parse(raw).trades || [];
    // match names to players on the right rosters, then grade each deal with the site's own numbers
    const findOn = (ids, name) => ids.find((id) => S.byId[id] && normName(S.byId[id].name) === normName(name));
    const baseMe = bestLineup(me.players || [], slots).total;
    S.aiTrades = proposals.map((t) => {
      const r = ld.rosters.find((x) => normName(teamName(x.roster_id)) === normName(t.team || ""));
      if (!r) return null;
      const give = (t.give || []).map((nm) => findOn(me.players || [], nm)), get = (t.get || []).map((nm) => findOn(r.players || [], nm));
      if (!give.length || !get.length || give.includes(undefined) || get.includes(undefined)) return null;
      const vGive = give.reduce((a, id) => a + tv(S.byId[id]), 0), vGet = get.reduce((a, id) => a + tv(S.byId[id]), 0);
      const sGive = give.reduce((a, id) => a + Math.pow(tv(S.byId[id]), STAR_POWER), 0), sGet = get.reduce((a, id) => a + Math.pow(tv(S.byId[id]), STAR_POWER), 0);
      const edge = (sGet - sGive) / Math.max(sGive, sGet, Math.pow(25, STAR_POWER));
      const dMe = bestLineup((me.players || []).filter((id) => !give.includes(id)).concat(get), slots).total - baseMe;
      const dThem = bestLineup((r.players || []).filter((id) => !get.includes(id)).concat(give), slots).total - bestLineup(r.players || [], slots).total;
      const fair = edge <= 0.25 && edge >= -0.3 && dThem >= -2 && (dThem >= 0 || edge < -0.1);
      return { roster: r.roster_id, give, get, why: t.why, vGive, vGet, edge, dMe, dThem, fair, theirFit: 0 };
    }).filter(Boolean).sort((a, b) => b.fair - a.fair || b.dMe - a.dMe);
    if (!S.aiTrades.length) S.aiMsg = "The AI's suggestions didn't match players in your league. Try again.";
  } catch (err) {
    S.aiMsg = `Couldn't build trades right now (${err.message}).`;
  }
  S.aiBusy = false;
  renderTrade();
}

function aiTradesHtml() {
  if (!WORKER_URL) return "";
  const nameList = (ids) => ids.map((id) => `<b>${esc(S.byId[id]?.name || id)}</b> <span class="pos ${S.byId[id]?.pos}">${S.byId[id]?.pos}</span>`).join(" + ");
  return `<h3>AI trade builder</h3>
    <div class="ai-build"><input id="ai-want" placeholder="Optional: what you want (e.g. upgrade my RB2 without giving up Puka Nacua)" autocomplete="off">
      <button class="tbtn on" data-ai-build ${S.aiBusy ? "disabled" : ""}>${S.aiBusy ? "Thinking..." : "Build trades with AI"}</button></div>
    ${S.aiMsg ? `<p class="note">${esc(S.aiMsg)}</p>` : ""}
    ${(S.aiTrades || []).map((x, i) => `<div class="idea">
      <div class="idea-team">${esc(teamName(x.roster))} ${x.fair ? `<span class="glean">checks out</span>` : `<span class="res miss">lopsided</span>`}</div>
      <div>You give ${nameList(x.give)}</div><div>You get ${nameList(x.get)}</div>
      ${tradeSummary(x)}
      ${x.why ? `<div class="idea-why"><b>AI:</b> ${esc(x.why)}</div>` : ""}
      <div class="idea-why">${fairText(x)}</div>
      <div class="idea-btns"><button class="tbtn" data-ai-idea="${i}">Open in calculator</button></div>
    </div>`).join("")}
    <p class="note">Gemini suggests trades from every roster and need in your league; the site then checks each one with its own numbers (both lineups and trade value) and flags any that are lopsided.</p>`;
}

// ---- trade ideas (Trade tab)

function tradeIdeasSection() {
  const gate = leagueGate("Sync your league to get trade ideas built for your roster: fair deals with every team that improve your starting lineup.");
  if (gate) return gate;
  if (!S.ideas) S.ideas = findTradeIdeas();
  setTimeout(() => { const w = $("#ai-want"); if (w && S.aiWant != null) w.value = S.aiWant; }, 0);
  const nameList = (ids) => ids.map((id) => `<b>${esc(S.byId[id]?.name || id)}</b> <span class="pos ${S.byId[id]?.pos}">${S.byId[id]?.pos}</span>`).join(" + ");
  return `<div class="card league">${leagueHead()}${needsBar()}
    <h3>Top targets</h3>
    <div class="targets">${topTargets().map((x) => `<div class="target">
      <div class="who">${avatar(x.p)}<div><div><b>${esc(x.p.name)}</b> <span class="pos ${x.p.pos}">${x.p.pos}</span>${injBadge(x.p)}</div>
        <div class="pmeta">${x.p.team} · on ${esc(teamName(x.r.roster_id))} · ${rosText(x.p)} ${scheduleChip(x.p)}</div></div></div>
      <div class="t-num"><span class="up">+${fmt(x.week)}</span><span class="small muted">a week for you</span></div>
      <div class="t-num"><span>${Math.round(x.price)}</span><span class="small muted">trade value</span></div>
      <button class="tbtn" data-target="${x.p.id}">Build a deal</button>
    </div>`).join("") || `<p class="note">No one on other rosters would add 10+ points to your lineup${S.ideaGet && S.ideaGet !== "ANY" ? ` at ${S.ideaGet}` : ""}.</p>`}</div>
    <p class="note">How many more points a week your starting lineup would score with him. Trade value is what he's worth in a deal; send back about that much.</p>
    ${aiTradesHtml()}
    <h3>Trade ideas</h3>
    <div class="gtool idea-filters"><span class="muted">I want</span>${seg("data-idea-get", S.ideaGet || "ANY", ["ANY", "QB", "RB", "WR", "TE"].map((x) => [x, x === "ANY" ? "Any" : x]), "Want")}
      <span class="muted">I'll give</span>${seg("data-idea-give", S.ideaGive || "ANY", ["ANY", "QB", "RB", "WR", "TE"].map((x) => [x, x === "ANY" ? "Any" : x]), "Give")}</div>
    <div class="ideas">${S.ideas.length ? S.ideas.map((x, i) => `<div class="idea">
      <div class="idea-team">${esc(teamName(x.roster))}</div>
      <div>You give ${nameList(x.give)}</div>
      <div>You get ${nameList(x.get)}</div>
      ${tradeSummary(x)}
      <div class="idea-why">${fairText(x)} ${x.get.map((id) => whyLine(id)).join(" ")}</div>
      <div class="idea-btns"><button class="tbtn" data-idea="${i}">Open in calculator</button> <button class="tbtn" data-ask-idea="${i}">Ask AI about it</button></div>
    </div>`).join("") : `<p class="note">No fair trades found that improve your starters${S.ideaGet && S.ideaGet !== "ANY" ? ` with a ${S.ideaGet} coming back` : ""}. Try another position, or the calculator below.</p>`}</div>
    <p class="note">"Points a week" is how much each team's starting lineup would score in a normal week after the trade, compared with now. Ideas are trades the other manager could plausibly accept: the values (rest-of-season points over a waiver player) are within about 15% of each other, or up to about 30% when the deal fills a position they're weak at and comes from one where they're deep. Their best lineup can't get meaningfully worse unless they get clearly more value. "Both teams gain" means their lineup improves too. Ranked by your lineup gain, theirs, and how well it fits both teams' needs. Built for your league's lineup (${esc(lineupSummary())}). Everything comes from Sleeper's projections for the remaining weeks, not last week's box score.</p>
  </div>`;
}

// ---- asking an AI: the whole trade, rosters and projections written out, opened in Claude or ChatGPT

function aiPrompt(give, get, rosterId) {
  const ld = S.leagueData;
  // full detail for the players in the trade; a short line for everyone else, so the link stays short enough
  const brief = (id) => { const p = S.byId[id]; return `${p.name} (${p.pos}) ${fmtPts(rosPts(p))}${injOf(p).status ? `, ${injOf(p).status}` : ""}`; };
  const keep = (ids) => (ids || []).filter((id) => S.byId[id] && rosPts(S.byId[id]) >= 20).sort((a, b) => rosPts(S.byId[b]) - rosPts(S.byId[a]));
  const fmtP = (id) => {
    const p = S.byId[id];
    if (!p) return id;
    const n = rosGames(p);
    const inj = injOf(p).status;
    const note = p.inj_report?.short;
    return `${p.name} (${p.pos}, ${p.team}): ${fmtPts(rosPts(p))} projected points over ${n} games left (${fmtPts(n ? rosPts(p) / n : 0)} a game)${byesLeft(p).length ? `, bye week ${byesLeft(p).join(", ")}` : ""}${inj ? `, ${inj}` : ""}${note ? `. Latest: ${note}` : ""}`;
  };
  const lines = [`I play in a ${ld ? `${ld.rosters.length}-team ` : ""}fantasy football league (${scoringName()} scoring${ld ? `, lineup: ${leagueSlots().join(", ")}` : ""}). It's ${S.data.season} week ${S.data.week}. Should I make this trade?`, "",
    "I give:", ...give.map((id) => `- ${fmtP(id)}`), "", "I get:", ...get.map((id) => `- ${fmtP(id)}`)];
  if (ld && S.sync?.roster_id != null) {
    lines.push("", "My roster (rest-of-season points):", keep(myRoster().players).map(brief).join("; "));
    if (rosterId != null) {
      const r = ld.rosters.find((x) => x.roster_id === rosterId);
      lines.push("", `Their roster, ${teamName(rosterId)} (rest-of-season points):`, keep(r.players).map(brief).join("; "));
    }
  }
  lines.push("", "Projections are Sleeper's for each remaining week. Please weigh my positional needs, injuries, bye weeks and the fantasy playoff weeks (usually 15 to 17), say whether the other manager would likely accept, and suggest a better counteroffer if there is one.");
  return lines.join("\n");
}

// What the chat knows: the scoring, your synced league and roster, the trade on the calculator, the week
// Everything about the synced league, written out for the chat
function leagueContext() {
  const ld = S.leagueData, L = ld.league, st = L.settings || {};
  const out = [];
  const one = (p) => {
    const g = gradeOf(p), inj = injOf(p).status, gm = S.games[p.game_id];
    const wk = gm ? gm.state === "pre" ? `proj ${fmt(projPts(p) || 0, 1)} this week vs ${p.opp}` : `${fmt(livePPR(p) || 0, 1)} so far this week` : "no game this week";
    return `${p.name} ${p.pos} ${p.team}${g ? ` (${g.label})` : ""}: ${fmt(rosPerGame(p), 1)} pts a game rest of season, ${wk}${byesLeft(p).length ? `, bye wk ${byesLeft(p).join("/")}` : ""}${inj ? `, ${inj}` : ""}`;
  };
  out.push(`MY LEAGUE: "${L.name}" on ${{ espn: "ESPN", yahoo: "Yahoo" }[S.sync.source] || "Sleeper"}, ${ld.rosters.length} teams, ${{ 0: "redraft", 1: "keeper", 2: "dynasty" }[st.type] || "redraft"}. Lineup: ${lineupSummary()}. Scoring: ${leagueSummary(L.scoring_settings)}.`
    + `${st.waiver_type != null ? ` Waivers: ${{ 0: "rolling", 1: "reverse standings", 2: `FAAB, $${st.waiver_budget} budget` }[st.waiver_type]}.` : ""}${st.trade_deadline && st.trade_deadline < 99 ? ` Trade deadline: week ${st.trade_deadline}.` : ""}${st.playoff_teams ? ` Playoffs: top ${st.playoff_teams}, starting week ${st.playoff_week_start}.` : ""}`);
  out.push(`I am "${teamName(S.sync.roster_id)}" (manager ${managerName(S.sync.roster_id)}).`);
  const rows = standingsRows();
  out.push("STANDINGS (place. team (manager): record, points for, points against, max points, all-play record, streak" + (isFaab() ? ", budget left" : ", waiver order") + "):");
  for (const x of rows) out.push(`${x.place}. ${teamName(x.id)} (${managerName(x.id)}): ${recText(x)}, PF ${fmt(x.pf, 1)}, PA ${fmt(x.pa, 1)}${x.max != null ? `, max ${fmt(x.max, 1)}` : ""}${x.allPlay ? `, all-play ${recText(x.allPlay)}` : ""}${x.streak ? `, streak ${x.streak}` : ""}${isFaab() ? `, $${x.faabLeft} left` : x.waiver != null ? `, waiver #${x.waiver}` : ""}`);
  try { out.push(`MY STARTERS' RANK IN THE LEAGUE BY POSITION (1 = best of ${ld.rosters.length}): ${Object.entries(positionRanks()[S.sync.roster_id] || {}).map(([k, v]) => `${k} ${v}`).join(", ")}.`); } catch { /* needs projections */ }
  // my roster in detail, with this week's best lineup
  const lu = weekLineup(myRoster());
  out.push(`MY ROSTER. Best lineup this week (${fmt(lu.total, 1)} projected):`);
  for (const x of lu.starters) if (x.pick) out.push(`- ${slotLabel(x.slot)}: ${one(x.pick.p)}`);
  out.push("My bench:");
  for (const x of lu.bench) out.push(`- ${one(x.p)}`);
  const unknown = (myRoster().players || []).filter((id) => !S.byId[id]);
  if (unknown.length) out.push(`Also on my roster: ${unknown.map(pname).join(", ")}.`);
  // everyone else's roster, shorter
  out.push("OTHER TEAMS' ROSTERS (rank at position, points a game rest of season):");
  for (const r of ld.rosters) {
    if (r.roster_id === S.sync.roster_id) continue;
    const ps = (r.players || []).map((id) => S.byId[id]).filter(Boolean).sort((a, b) => rosPerGame(b) - rosPerGame(a));
    out.push(`${teamName(r.roster_id)}: ${ps.map((p) => `${p.name} ${p.pos} ${p.team} ${gradeOf(p)?.label || ""} ${fmt(rosPerGame(p), 1)}${injOf(p).status ? ` ${injOf(p).status}` : ""}`).join("; ")}`);
  }
  // this week's matchups and last week's results
  const groups = (list) => { const g = {}; for (const m of list || []) if (m.matchup_id != null) (g[m.matchup_id] ??= []).push(m); return Object.values(g).filter((x) => x.length === 2); };
  const cur = groups(ld.matchups || ld.weekly?.[S.data.week]);
  if (cur.length) out.push(`WEEK ${S.data.week} MATCHUPS (Sleeper points so far): ${cur.map(([a, b]) => `${teamName(a.roster_id)} ${fmt(a.points || 0, 1)} vs ${teamName(b.roster_id)} ${fmt(b.points || 0, 1)}`).join("; ")}.`);
  for (const w of doneWeeks().slice(-3).reverse()) {
    const res = groups(ld.weekly[w]);
    if (res.length) out.push(`WEEK ${w} RESULTS: ${res.map(([a, b]) => `${teamName(a.roster_id)} ${fmt(a.points || 0, 1)} - ${teamName(b.roster_id)} ${fmt(b.points || 0, 1)}`).join("; ")}.`);
  }
  // recent moves
  if (ld.tx?.length) {
    out.push("RECENT LEAGUE MOVES (newest first):");
    for (const t of ld.tx.slice(0, 20)) {
      const adds = Object.entries(t.adds || {}), drops = Object.entries(t.drops || {});
      if (t.type === "trade") out.push(`- Week ${t.leg} trade: ${t.roster_ids.map((rid) => `${teamName(rid)} got ${adds.filter(([, r]) => r === rid).map(([id]) => pname(id)).join(", ") || "picks/nothing"}`).join("; ")}`);
      else out.push(`- Week ${t.leg} ${t.type === "waiver" ? "waiver" : "free agent"}: ${teamName(t.roster_ids?.[0])} added ${adds.map(([id]) => pname(id)).join(", ") || "nobody"}${drops.length ? `, dropped ${drops.map(([id]) => pname(id)).join(", ")}` : ""}${t.settings?.waiver_bid != null && isFaab() ? ` ($${t.settings.waiver_bid})` : ""}`);
    }
  }
  // the best free agents at each position the league uses
  const rostered = new Set(ld.rosters.flatMap((r) => [...(r.players || []), ...(r.reserve || []), ...(r.taxi || [])]));
  const fa = rosPool().filter((p) => !rostered.has(p.id) && posOk(p.pos) && leagueSlots().some((s2) => (SLOT_ELIG[s2] || []).includes(p.pos)));
  out.push("BEST FREE AGENTS (not on any roster; adds = Sleeper users who added him in the last 24 hours):");
  for (const pos of ["QB", "RB", "WR", "TE", "K", "DEF"]) {
    const list = fa.filter((p) => p.pos === pos).sort((a, b) => rosPerGame(b) - rosPerGame(a)).slice(0, 6);
    if (list.length) out.push(`${pos}: ${list.map((p) => `${one(p)}${S.trend?.add[p.id] ? `, ${S.trend.add[p.id]} adds` : ""}`).join("; ")}`);
  }
  if (ld.draft?.picks?.length) out.push(`MY DRAFT PICKS: ${ld.draft.picks.filter((pk) => pk.roster_id === S.sync.roster_id).map((pk) => `round ${pk.round} ${pname(pk.player_id)}`).join(", ")}.`);
  return out.join("\n");
}

function chatContext() {
  const bits = [`Season ${S.data.season}, week ${S.data.week}. Scoring: ${scoringName()} (kickers and defenses on ESPN standard).`];
  const ld = S.leagueData;
  if (ld && S.sync?.roster_id != null && S.future) bits.push(leagueContext());
  if (S.trade.give.length || S.trade.get.length) bits.push(`Trade on the calculator: give ${S.trade.give.map((id) => S.byId[id]?.name).join(", ") || "nothing"}; get ${S.trade.get.map((id) => S.byId[id]?.name).join(", ") || "nothing"}.`);
  // this week's top picks and game leans, so "best bet?" questions have something to go on
  const pickLine = (x) => {
    const p = S.byId[x.player_id], g = S.games[x.game_id];
    if (!p || !g || g.state !== "pre") return null;
    return `${p.name} (${p.pos} ${p.team}) ${x.direction} ${x.line} ${S.data.categories[x.key]?.label || x.key} (${x.line_from === "dk" ? "DraftKings" : x.line_from === "sleeper" ? "Sleeper Picks" : "our"} line; we project ${fmt(x.adj ?? x.proj, 1)})`;
  };
  const picks = [...(S.data.picks.over || []), ...(S.data.picks.under || [])].sort((a, b) => b.score - a.score).map(pickLine).filter(Boolean).slice(0, 8);
  if (picks.length) bits.push(`Our top prop picks for games not started yet, best first: ${picks.join("; ")}.`);
  const leans = Object.values(S.games).filter((g) => g.state === "pre" && g.ours && g.odds && (g.ours.lean_spread || g.ours.lean_total))
    .map((g) => `${g.away} @ ${g.home}: ${[g.ours.lean_spread ? `${g.ours.lean_spread} against the spread (DraftKings ${g.odds.details})` : "", g.ours.lean_total ? `${g.ours.lean_total} ${g.odds.total} (we project ${fmt(g.ours.total, 1)})` : ""].filter(Boolean).join(", ")}`);
  if (leans.length) bits.push(`Our game leans: ${leans.join("; ")}.`);
  if (S.chatExtra) bits.push(`Details for the trade being discussed:\n${S.chatExtra}`);
  if (S.gameView && gameOf(S.gameView)) { const g = gameOf(S.gameView); bits.push(`Looking at ${g.away} @ ${g.home}, ${gameStatus(g)}${g.home_score != null ? `, score ${g.away} ${g.away_score} - ${g.home} ${g.home_score}` : ""}.`); }
  return bits.join("\n");
}

function renderChat() {
  const box = $("#chat");
  if (!box) return;
  // light formatting: **bold** and "- " bullets, the rest as plain text
  const fmtMsg = (t) => {
    const out = [];
    let list = [];
    const flush = () => { if (list.length) out.push(`<ul>${list.map((x) => `<li>${x}</li>`).join("")}</ul>`); list = []; };
    for (const raw of esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split("\n")) {
      const m = raw.match(/^\s*(?:[-*\u2022]|\d+\.) +(.*)/);
      if (m) list.push(m[1]);
      else { flush(); if (raw.trim()) out.push(`<p>${raw}</p>`); }
    }
    flush();
    return out.join("");
  };
  const hello = S.sync ? "Hey! Ask me anything about your team." : "Hey! Ask me anything about fantasy or props. Sync your league and I can see your team too.";
  const ideas = S.sync ? ["Who should I start this week?", "Any good trades for me?", "Who should I pick up?", "How's my team looking?"]
    : ["Best prop bet this week?", "Who's a sleeper this week?", "Which injuries matter most?"];
  box.querySelector(".chat-msgs").innerHTML = (S.chat.length ? S.chat.map((m) => `<div class="msg ${m.role}">${fmtMsg(m.text)}</div>`).join("")
    : `<div class="msg model">${esc(hello)}</div><div class="chat-ideas">${ideas.map((q) => `<button class="tbtn" data-chat-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>`)
    + (S.chatBusy ? `<div class="msg model busy">Thinking...</div>` : "");
  const list = box.querySelector(".chat-msgs");
  list.scrollTop = list.scrollHeight;
}

function openChat(first) {
  if (!$("#chat")) {
    document.body.insertAdjacentHTML("beforeend", `<div id="chat" class="chat" role="dialog" aria-label="AI chat">
      <div class="chat-h"><b>Ask AI</b><button class="tbtn" data-chat-clear>New chat</button><button class="rm" data-chat-close aria-label="Close">×</button></div>
      <div class="chat-msgs"></div>
      <form class="chat-in"><textarea rows="1" placeholder="Ask anything..."></textarea><button class="tbtn on">Send</button></form>
      <div class="chat-note">Google Gemini, using this site's numbers. It can be wrong.</div>
    </div>`);
  }
  $("#chat").hidden = false;
  document.body.classList.add("chat-open");
  fitChat();
  renderChat();
  if (first) sendChat(first);
  else $("#chat textarea").focus();
}

// On phones the chat fills the screen above the keyboard (visualViewport shrinks when the keyboard opens)
function fitChat() {
  const vv = window.visualViewport;
  if (vv) document.documentElement.style.setProperty("--vvh", `${Math.round(vv.height)}px`);
}
window.visualViewport?.addEventListener("resize", fitChat);

async function sendChat(text) {
  text = text.trim();
  if (!text || S.chatBusy) return;
  S.chat.push({ role: "user", text });
  S.chatBusy = true;
  renderChat();
  try {
    if (S.sync) await ensureLeague().catch(() => false);
    const r = await fetch(`${WORKER_URL}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: S.chat, context: chatContext() }) });
    const d = await r.json();
    S.chat.push({ role: "model", text: d.text || `Sorry: ${d.error || "something went wrong"}${r.status === 429 ? " (the free daily limit may be used up; try again later)" : ""}.` });
  } catch {
    S.chat.push({ role: "model", text: "Sorry, I couldn't reach the chat right now." });
  }
  S.chatBusy = false;
  renderChat();
}

// "Ask AI" on a trade: the on-screen chat asks in plain words; the rosters and numbers go along as context
function askAboutTrade(give, get, rosterId) {
  const names = (ids) => ids.map((id) => S.byId[id]?.name).filter(Boolean).join(" and ");
  if (!WORKER_URL) { showAsk(aiPrompt(give, get, rosterId)); return; }
  S.chatExtra = aiPrompt(give, get, rosterId);
  openChat(`Should I trade ${names(give)} for ${names(get)}? Is it fair, and would they accept?`);
}

function showAsk(text) {
  const q = encodeURIComponent(text);
  $("#ask-box")?.remove();
  document.body.insertAdjacentHTML("beforeend", `<div id="ask-box" class="ask-box" role="dialog" aria-label="Ask AI">
    <div class="ask-card">
      <div class="ask-h"><b>Ask AI about this trade</b><button class="rm" data-ask-close aria-label="Close">×</button></div>
      <p class="note">This opens a chat with everything filled in: both rosters, projections, byes and injury notes. You can keep asking follow-ups there.</p>
      <textarea readonly>${esc(text)}</textarea>
      <div class="idea-btns">
        ${WORKER_URL ? `<button class="tbtn on" data-chat-here>Chat here</button>` : ""}
        <a class="tbtn ${WORKER_URL ? "" : "on"}" href="https://claude.ai/new?q=${q}" target="_blank" rel="noopener">Open in Claude</a>
        <a class="tbtn" href="https://chatgpt.com/?q=${q}" target="_blank" rel="noopener">Open in ChatGPT</a>
        <button class="tbtn" data-ask-copy>Copy</button>
      </div>
    </div></div>`);
}

function renderTrade() {
  const head = `<h2>Trade <small>${esc(scoringName())} · rest of season</small></h2>`;
  if (!S.future) {
    $("#main").innerHTML = head + `<div class="empty">Loading projections for the rest of the season...</div>`;
    loadFuture().then(() => { if (S.tab === "trade") renderTrade(); });
    return;
  }
  const repl = replacementLevels();
  const shape = leagueShape();
  // position ranks by rest-of-season points
  const ranks = {};
  for (const pos of Object.keys(repl)) {
    rosPool().filter((p) => p.pos === pos).map((p) => [p.id, rosPts(p)]).sort((a, b) => b[1] - a[1]).forEach(([id], i) => { ranks[id] = i + 1; });
  }
  const value = (p) => {
    const ros = rosPts(p);
    return { ros, vor: ros - (repl[p.pos] ?? 0), n: rosGames(p), rank: ranks[p.id] };
  };
  const options = rosPool().filter((p) => rosPts(p) >= 5 && posOk(p.pos)).sort((a, b) => rosPts(b) - rosPts(a))
    .map((p) => `<option value="${esc(playerLabel(p))}"></option>`).join("");
  const side = (k, title) => {
    const ids = S.trade[k].filter((id) => S.byId[id]);
    const rows = ids.map((id) => { const p = S.byId[id]; return { p, ...value(p) }; });
    const total = rows.reduce((a, r) => a + Math.max(0, r.vor), 0);
    const pts = rows.reduce((a, r) => a + r.ros, 0);
    return { total, pts, html: `<div class="trade-side card">
      <h3>${title}</h3>
      ${rows.map((r) => `<div class="trade-row">
        ${avatar(r.p)}
        <div><div><b>${esc(r.p.name)}</b> <span class="pos ${r.p.pos}">${r.p.pos}</span>${injBadge(r.p)}</div>
          <div class="pmeta">${r.p.team} · ${rosText(r.p)}${byesLeft(r.p).length ? ` · bye wk ${byesLeft(r.p).join(", ")}` : ""}</div></div>
        <div class="side"><div class="num ${r.vor > 0 ? "" : "muted"}">${Math.round(Math.max(0, r.vor))}</div><div class="small">trade value</div>
          <button class="rm" data-trade-rm="${k}|${r.p.id}" title="Remove" aria-label="Remove">×</button></div>
      </div>`).join("") || `<p class="note">Add players below.</p>`}
      <div class="trade-add"><input list="trade-list" data-trade-side="${k}" placeholder="Add a player" autocomplete="off"></div>
      <div class="trade-tot"><span>Trade value</span><b class="num">${Math.round(total)}</b></div>
    </div>` };
  };
  const give = side("give", "You give"), get = side("get", "You get");
  let verdict = "";
  if (S.trade.give.length && S.trade.get.length) {
    const d = get.total - give.total;
    const big = Math.max(give.total, get.total, 1);
    verdict = Math.abs(d) / big < 0.08
      ? `<div class="verdict even">Fair trade: about even value (${Math.round(give.total)} vs ${Math.round(get.total)}).</div>`
      : d > 0 ? `<div class="verdict">You win this trade on value: ${Math.round(get.total)} coming in vs ${Math.round(give.total)} going out.</div>`
      : `<div class="verdict lose">You lose this trade on value: ${Math.round(get.total)} coming in vs ${Math.round(give.total)} going out.</div>`;
  }
  const replText = Object.entries(repl).map(([pos, v]) => `${pos} ${fmtPts(v)}`).join(" · ");
  const after = afterTradeHtml();
  $("#main").innerHTML = head + tradeIdeasSection() + `<h2 id="calc">Trade calculator</h2><datalist id="trade-list">${options}</datalist>
    ${verdict}
    <div class="trade-grid">${give.html}${get.html}</div>
    ${after}
    <div class="gtool" style="margin-top:10px"><button class="tbtn" data-trade-clear>Clear trade</button>${S.trade.give.length && S.trade.get.length ? ` <button class="tbtn on" data-ask-trade>Ask AI about this trade</button>` : ""}</div>
    <p class="note"><b>Value</b> is how many rest-of-season points a player adds over the best player you could likely pick up at his position (<b>replacement level</b>: once every team in ${shape.name ? `<b>${esc(shape.name)}</b>` : "a 12-team league (QB, 2 RB, 2 WR, TE, FLEX, K, DEF, 6 bench spots)"} has filled its starters and bench). That's why a quarterback's big point total isn't automatically worth more: there are good quarterbacks on waivers. Rostered per position: ${Object.entries(shape.rostered).map(([k, v]) => `${k} ${v}`).join(", ")}. Replacement level now (rest-of-season points): ${replText}. A player below it counts as zero. Projections are Sleeper's for each remaining week, scored in ${esc(scoringName())}${shape.name ? "" : "; pick one of your Sleeper leagues in the scoring menu to use its size and lineup"}.</p>`;
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
    ${b ? `<h2>Our numbers vs DraftKings <small>${b.season} weeks ${b.weeks[0]}-${b.weeks[b.weeks.length - 1]}, ${b.props.toLocaleString()} props</small></h2>
    <div class="stats">
      ${b.our_side != null ? `<div class="card stat"><div class="k">When we disagreed with DraftKings</div><div class="v">${fmt(b.our_side)}%</div><div class="d">of the time the result landed on our side (${b.our_side_n.toLocaleString()} props; 50% is a coin flip)</div></div>` : ""}
      <div class="card stat"><div class="k">DraftKings closer to the result</div><div class="v">${fmt(b.dk_closer)}%</div><div class="d">vs the matchup-adjusted season average</div></div>
      <div class="card stat"><div class="k">Unders at DraftKings' line</div><div class="v">${fmt(b.dk_under)}%</div><div class="d">a fair line would be 50%</div></div>
      <div class="card stat"><div class="k">Ours well below DK: under hit</div><div class="v">${fmt(b.below_under)}%</div><div class="d">${b.below_n} props</div></div>
      <div class="card stat"><div class="k">Ours well above DK: over hit</div><div class="v">${fmt(b.above_over)}%</div><div class="d">${b.above_n} props</div></div>
    </div>
    <div class="tbl-wrap"><table class="tbl">
      <thead><tr><th class="l">Category</th><th>Props</th><th>Ours minus DK</th><th>Unders at DK</th><th>DK closer</th></tr></thead>
      <tbody>${b.categories.filter((x) => x.dk_under != null).map((x) => `<tr><td class="l">${S.data.categories[x.key].label}</td><td>${x.n}</td><td>${x.gap > 0 ? "+" : ""}${fmt(x.gap)}</td><td>${fmt(x.dk_under)}%</td><td>${x.dk_closer != null ? fmt(x.dk_closer) + "%" : "-"}</td></tr>`).join("")}</tbody>
    </table></div>
    <p class="note">DraftKings' closing lines, via ESPN, for every finished game this season, compared with each player's average so far this season adjusted for the matchup, using only earlier games (tools/compare_lines.py). Players need 2+ earlier games, so week 1 and 2 have few props. Sleeper's projections can't be tested on past weeks (Sleeper revises them after the games), so this tests the matchup adjustment on its own.</p>` : ""}`;
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
      ${w.ppr.n ? `<p class="note">PPR projection error: Sleeper ${w.ppr.proj_mae} pts per player, ours (matchup-adjusted) ${w.ppr.average_mae} (${w.ppr.n} players).</p>` : ""}
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
      <div class="card stat"><div class="k">PPR projection error</div><div class="v">${c.ppr.proj_mae ?? "-"}</div><div class="d">${c.ppr.n ? `pts per player for Sleeper, ${c.ppr.average_mae} for ours (${c.ppr.n} players)` : "graded once games go final"}</div></div>
    </div>
    ${cats.length ? `<h2>Leans by category</h2><div class="glist">${cats.map(([k, v]) => `<div class="g"><span>${S.data.categories[k].label}</span><span class="num">${v.hit}-${v.miss} · ${pctText(v)}</span></div>`).join("")}</div>` : ""}
    ${c.games ? `<h2>Game leans vs DraftKings</h2><div class="stats">
      <div class="card stat"><div class="k">Against the spread</div><div class="v">${pctText(c.games.spread)}</div><div class="d">${c.games.spread.hit}-${c.games.spread.miss}, when our spread is 2+ points off DraftKings'</div></div>
      <div class="card stat"><div class="k">Totals</div><div class="v">${pctText(c.games.total)}</div><div class="d">${c.games.total.hit}-${c.games.total.miss}, when our total is 3+ points off DraftKings'</div></div>
    </div>` : ""}
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
    <h2 id="features">What's here</h2>
    <div class="feat">
      <div class="card"><b>Props with real lines</b><p>DraftKings lines (then Sleeper Picks) for every prop, our pregame projection, leans, hit rates this season, and Top Overs / Unders for real starters only.</p></div>
      <div class="card"><b>Live everything</b><p>Scores, every player's stats and fantasy points from Sleeper's live feed, prop progress (cleared, lost, hit, miss), all refreshing together every 15 to 30 seconds.</p></div>
      <div class="card"><b>Game pages</b><p>Tap a game: field position, last play, quarter scores, win probability, play-by-play with filters (quarter, scoring, big plays, turnovers, flags), box score, props and fantasy for that game.</p></div>
      <div class="card"><b>Past weeks</b><p>Pick any earlier week above the scores: final scores, box scores, play-by-play, fantasy points and every player against DraftKings' closing lines.</p></div>
      <div class="card"><b>Injuries by game</b><p>Each game page has both teams' injury lists: every position from ESPN's report plus IR and fantasy statuses from Sleeper.</p></div>
      <div class="card"><b>Game lines</b><p>DraftKings spread, total, moneyline and implied points next to ours (player projections added up), pregame and live, with leans that get graded.</p></div>
      <div class="card"><b>Your scoring</b><p>Sleeper or ESPN, PPR or half, or your own Sleeper league's exact settings. Every number on the site follows it. Kickers and defenses use ESPN scoring.</p></div>
      <div class="card"><b>Fantasy rankings</b><p>This week or rest of season, by position or FLEX, with live points, snap share and byes.</p></div>
      <div class="card"><b>Game logs</b><p>Every player's games this season with snaps, then a projection for each remaining week, like Sleeper's. Games he missed show as Did not play (0 points).</p></div>
      <div class="card"><b>Compare</b><p>Two players side by side with a start recommendation, matchup, props and game logs.</p></div>
      <div class="card"><b>Your league</b><p>Sync Sleeper with just your username (or ESPN by league ID): start/sit for this week (locked players stay put), this week's matchups live, standings, every roster, and free agents ranked against your worst player at each spot.</p></div>
      <div class="card"><b>Trades</b><p>Top targets for your weak spots and fair trade ideas with every team (fair for both sides, and their lineup can't get worse), filtered by position, plus a calculator, position ranks (WR14), how both lineups look after the trade, and an AI trade builder.</p></div>
      <div class="card"><b>Matchup difficulty</b><p>Every player shows his opponent's rank against his position this season (#1 = toughest), and every remaining schedule is rated easy, average or hard.</p></div>
      <div class="card"><b>My Picks</b><p>Track any prop you like, live, with a running record for your slate. Saved on your device.</p></div>
      <div class="card"><b>News and injuries</b><p>ESPN headlines tagged with players, and an in-depth injury report: injury and side, expected return, games missed, recent snap shares, how his status has changed, and who plays more if he sits. Game-day inactives show up as they post.</p></div>
      <div class="card"><b>Honest track record</b><p>Every pick and lean graded only from what was posted before kickoff, and our numbers checked against DraftKings'.</p></div>
      <div class="card"><b>Ask AI</b><p>A built-in chat (Google Gemini) that knows your league, roster, our picks and the trade you're looking at. Short, plain answers. Tap Ask AI in the bottom right corner.</p></div>
    </div>
    <h2>Lines</h2>
    <p>Every prop uses the real <b>DraftKings</b> line when DraftKings has posted one (ESPN carries DraftKings' player props). If DraftKings hasn't, it uses <b>Sleeper Picks</b>' line, and only after that our own estimate, which is labeled "est". Each card shows all of them side by side, plus where DraftKings' line opened.</p>
    <h2>Our projection</h2>
    <p>Our projection starts from Sleeper's projection for the week and adjusts it for the matchup: we look at every player at the same position with a similar season average who has faced this defense <b>this season</b>, and compare what they did against it with what they usually do. With only a few games that adjustment is pulled toward zero, so early in the season it's small. Last season's games are never used, and every chart and hit rate shows this season only.</p>
    <h2>Leans and top picks</h2>
    <p>A lean means our projection is far enough above (over) or below (under) a real sportsbook line. There are no leans against our own estimate. Top Overs and Top Unders are the biggest gaps, measured in each category's typical spread, and only use real sportsbook lines. They include players with 2+ games this season who aren't out, doubtful or on IR, and lock at kickoff. During a game, cards also show DraftKings' live line.</p>
    <h2>How our lines compare with DraftKings</h2>
    <p>See the Track Record tab. In short: DraftKings' lines are sharper than a season average, and three or four weeks in, the matchup adjustment hasn't yet made a season average more accurate. That's why the real line is the one that counts, and why the adjustment is kept small until there's more data.</p>
    <h2>Our game lines</h2>
    <p>Our spread, total and moneyline come from the same player projections, added up: each team's projected touchdowns (passing TDs from the quarterback, rushing TDs from everyone, so no catch is counted twice), 2-point conversions, its kicker's field goals and extra points, and its defense's touchdowns and safeties. Those totals are scaled to this season's real average points per team, then turned into a spread, total and win chance (a fair moneyline with no sportsbook margin). We show a lean when we're 2+ points off DraftKings' spread or 3+ off the total, lock it at kickoff, and grade it on the Track Record tab.</p>
    <h2>Future weeks and trades</h2>
    <p>Every player's game log continues past this week with Sleeper's projection for each remaining game (and his bye), scored in whatever scoring you've picked. In Sleeper scoring the totals are Sleeper's own, so they match the app exactly. The Fantasy tab has a rest-of-season ranking.</p>
    <p>The Trade tab values each player by his rest-of-season points above <b>replacement level</b>: the best player at his position you could likely pick up once every team has filled its starters and bench (12 teams with QB, 2 RB, 2 WR, TE, FLEX, K, DEF and 6 bench spots, unless you've picked one of your Sleeper leagues, which uses its size and lineup). That's why a quarterback's big point total doesn't automatically beat a running back's.</p>
    <h2>Fantasy points</h2>
    <p>QB, RB, WR and TE use Sleeper's standard scoring, in PPR or half PPR (the switch at the top changes every number on the site). Our totals match Sleeper's own on about 6,000 player-weeks from 2025 and 2026, both settings, re-checked every update.</p>
    <table class="ptable">${scoreRows.map(([k, v]) => `<tr><td>${k}</td><td class="num">${v > 0 ? "+" : ""}${v}</td></tr>`).join("")}<tr><td>Reception (half PPR)</td><td class="num">+0.5</td></tr></table>
    <p>Kickers and team defenses use <b>ESPN's standard scoring</b>: field goals 3 (under 40 yards), 4 (40-49), 5 (50-59), 6 (60+), -1 per miss, 1 per extra point; defenses get 1 per sack, 2 per interception, fumble recovery, safety or blocked kick, 6 per touchdown, plus points-allowed and yards-allowed tiers. Every kicker and defense matches ESPN's own totals each week we've checked.</p>
    <h2>Live</h2>
    <p>Scores, box scores and play-by-play come straight from ESPN every 30 seconds while games are on (every 8 seconds for the game you have open, and the newest play shows "just in" the moment the scoreboard has it, before the full play-by-play catches up), paused when this tab is hidden. Live points use the same scoring, including 2-point conversions and field goal distances. An over is marked cleared the moment it passes the line, since stats only go up; an under is only a hit once the game is final.</p>
    <h2>News and injuries</h2>
    <p>Injury designations come from Sleeper with each update, along with ESPN's injury report (notes, body part and expected return). On game days the page also checks ESPN's latest news for games kicking off within 4 hours, so game-day inactives show up right away (outlined badges, with the time ESPN posted them). The News tab has ESPN's latest headlines, tagged with the players they mention, and an injury report by game. Opening a player and tapping More news loads his latest Rotowire note and headlines.</p>
    <h2>Updates and honest grading</h2>
    <p>Lines, projections and injuries rebuild every hour (every 30 minutes on game days). Once a game kicks off, its lines and picks freeze. The track record only grades what was posted before kickoff, and it isn't backfilled: Sleeper revises past weeks' projections after the games, so grading old weeks with them would use information nobody had beforehand.</p>
    <h2 id="maker">Made by Joshua Moy</h2>
    <div class="card bio">
      <p>Joshua Moy is a Northeastern University student who builds data tools: hourly data pipelines, sports models that grade themselves in public, and interactive maps and dashboards.</p>
      <ul>
        <li><b>Joshua Moy's Expert NFL Picks</b> (this site): NFL props against DraftKings and Sleeper lines, fantasy projections, live scoring and play-by-play, league sync and trade ideas.</li>
        <li><b><a href="https://joshuam0y.github.io/mlb-player-props/" target="_blank" rel="noopener">MLB Player Props</a></b>: the baseball version, rebuilt hourly from MLB's public data, with its own public track record.</li>
        <li><b><a href="https://joshuam0y.github.io/sustainability-network/" target="_blank" rel="noopener">Sustainability Faculty Network</a></b>: an interactive map of faculty research and courses in sustainability that replaced a Tableau dashboard.</li>
      </ul>
      <p class="note">Python, SQL, JavaScript and GitHub Actions. Code: <a href="https://github.com/joshuam0y" target="_blank" rel="noopener">github.com/joshuam0y</a></p>
    </div>
  </div>`;
}

// ---------------------------------------------------------------- game page

// ---- finished weeks (data/weeks/, built by pull/build.py): final scores, DraftKings' closing lines, every stat line

const gameOf = (id) => S.games[id] || S.pastGames[id];
const pastRows = (g) => S.weeks[g.pastWeek]?.byGame[g.id] || [];
const dayShort = (iso) => new Date(iso).toLocaleDateString(undefined, { weekday: "short", month: "numeric", day: "numeric" });

async function loadWeek(w) {
  if (S.weeks[w]) return S.weeks[w];
  const d = await getJSON(`data/weeks/${S.data.season}_w${String(w).padStart(2, "0")}.json?v=${encodeURIComponent(S.data.generated_at)}`);
  d.byGame = {};
  for (const r of d.players) (d.byGame[r.game_id] ??= []).push(r);
  for (const g of d.games) S.pastGames[g.id] = { ...g, pastWeek: w };
  S.weeks[w] = d;
  return d;
}

const loadPastWeeks = () => Promise.all(Array.from({ length: S.data.week - 1 }, (_, i) => loadWeek(i + 1).catch(() => null)));

function renderWeekPick() {
  const el = $("#wkpick");
  if (!el) return;
  const w = S.viewWeek || S.data.week;
  el.innerHTML = `<button class="wkb" data-wk="${w - 1}" ${w <= 1 ? "disabled" : ""} aria-label="Previous week">‹</button>
    <select class="wks" data-wksel aria-label="Week">${Array.from({ length: S.data.week }, (_, i) => i + 1).map((x) => `<option value="${x}" ${x === w ? "selected" : ""}>${x === S.data.week ? `Week ${x} (now)` : `Week ${x}`}</option>`).join("")}</select>
    <button class="wkb" data-wk="${w + 1}" ${w >= S.data.week ? "disabled" : ""} aria-label="Next week">›</button>`;
}

async function setWeek(w) {
  w = Math.max(1, Math.min(S.data.week, w));
  if (w === S.data.week) { S.viewWeek = null; renderScores(); return; }
  S.viewWeek = w;
  if (!S.weeks[w]) {
    $("#strip").innerHTML = `<div class="muted small" style="padding:8px 16px">Loading week ${w}...</div>`;
    try { await loadWeek(w); } catch { S.viewWeek = null; $("#scores-status").textContent = `Week ${w} isn't available`; return; }
  }
  renderScores();
}

// A finished game's players against DraftKings' closing lines
function renderPastProps(g, teams) {
  const st = gs(g.id);
  const rows = pastRows(g).filter((r) => r.lines && (!st.team || r.team === st.team) && (st.pos === "ALL" || r.pos === st.pos))
    .sort((a, b) => fantasyPts(b.st, b.pos) - fantasyPts(a.st, a.pos));
  let over = 0, under = 0;
  const body = rows.map((r) => {
    const cells = Object.entries(r.lines).filter(([k]) => S.data.categories[k]).map(([k, line]) => {
      const v = statValue(k, r.st);
      const res = v > line ? "over" : v < line ? "under" : "push";
      if (res === "over") over++; else if (res === "under") under++;
      return `<div class="pp-line ${res}"><span>${esc(S.data.categories[k].label)}</span><b class="num">${fmtStat(k, v)}</b><span class="muted">line ${line}</span><span class="pp-res">${res === "push" ? "Push" : res === "over" ? "Over" : "Under"}</span></div>`;
    }).join("");
    return `<div class="card pp-card ${isMine(r.id) ? "is-mine" : ""}" ${S.byId[r.id] ? `data-open="${r.id}"` : ""}>
      <div class="pp-who"><span class="pos ${r.pos}">${r.pos}</span> <b>${esc(r.name)}</b> <span class="muted">${r.team}</span>${S.byId[r.id] ? mineTag(r) : ""}<span class="num pp-pts">${fmtPts(fantasyPts(r.st, r.pos))} pts</span></div>
      <div class="pp-lines">${cells}</div></div>`;
  }).join("");
  return `<div class="gtool">${teamSeg(teams, st.team)}${seg("data-gpos", st.pos, ["ALL", "QB", "RB", "WR", "TE"].map((x) => [x, x === "ALL" ? "All" : x]), "Position")}</div>
    ${rows.length ? `<div class="gcount">${rows.length} players \u00b7 overs hit ${over}, unders hit ${under}</div>` : ""}
    <div class="pp-list">${body || `<div class="empty">No DraftKings player lines for this game.</div>`}</div>
    <p class="note">DraftKings' closing lines (via ESPN) against what each player actually did. Points in ${esc(scoringName())}.</p>`;
}

// A finished game's fantasy points, scored with the current settings
function renderPastFantasy(g, teams) {
  const st = gs(g.id);
  const rows = pastRows(g).filter((r) => posOk(r.pos) && (!st.team || r.team === st.team) && (st.pos === "ALL" || r.pos === st.pos))
    .map((r) => ({ r, pts: fantasyPts(r.st, r.pos) })).filter((x) => x.pts !== 0 || x.r.pos === "DEF").sort((a, b) => b.pts - a.pts);
  return `<div class="gtool">${teamSeg(teams, st.team)}${seg("data-gpos", st.pos, usePositions(["ALL", "QB", "RB", "WR", "TE", "K", "DEF"]).map((x) => [x, x === "ALL" ? "All" : x]), "Position")}</div>
    <div class="tbl-wrap"><table class="tbl">
      <thead><tr><th class="l">Player</th><th>Snaps</th><th>Final</th></tr></thead>
      <tbody>${rows.map(({ r, pts }) => {
        const p = S.byId[r.id];
        return `<tr ${p ? `data-open="${r.id}"` : ""} class="${p ? "click" : ""} ${isMine(r.id) ? "is-mine" : ""}">
          <td class="l"><div class="who">${p ? avatar(p) : ""}<div><div><b>${esc(r.name)}</b>${p ? mineTag(p) : ""}</div><div class="pmeta"><span class="pos ${r.pos}">${r.pos}</span> ${r.team}</div></div></div></td>
          <td>${r.st.off_snp != null ? `${r.st.off_snp}${r.st.tm_off_snp ? ` <span class="muted">${Math.round((100 * r.st.off_snp) / r.st.tm_off_snp)}%</span>` : ""}` : "-"}</td>
          <td class="big" style="color:var(--cyan)">${fmtPts(pts)}</td>
        </tr>`;
      }).join("") || `<tr><td class="l" colspan="3">No players match.</td></tr>`}</tbody>
    </table></div>
    <p class="note">Week ${g.pastWeek} points in ${esc(scoringName())}.</p>`;
}

function gameTeams(g) {
  const comp = S.sum[g.id]?.header?.competitions?.[0];
  const out = {};
  for (const side of ["away", "home"]) {
    const c = comp?.competitors?.find((x) => x.homeAway === side);
    out[side] = {
      abbr: g[side], id: c?.team?.id, name: c?.team?.displayName || g[side],
      short: c?.team?.name || c?.team?.shortDisplayName || g[side],
      color: c?.team?.color ? `#${c.team.color}` : "#344677",
      alt: c?.team?.alternateColor ? `#${c.team.alternateColor}` : null,
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
        ${who.map(({ p }) => `<button class="pl-who ${S.favs.has(p.id) ? "fav-on" : ""} ${isMine(p.id) ? "is-mine" : ""}" data-open="${p.id}" title="Open ${esc(p.name)}"><span class="pos ${p.pos}">${p.pos}</span> ${esc(p.name.split(" ").slice(1).join(" "))} <b class="num">${fmtPts(livePPR(p))}</b></button>`).join("")}</div>` : ""}
    </div>
  </div>`;
}

function fieldView(g, teams, sum) {
  if (g.state !== "in") return "";
  const drives = allDrives(sum);
  const last = drives.length ? drives[drives.length - 1].plays?.slice(-1)[0] : null;
  const sb = g.spot;
  const spot = sb ? { yardLine: sb.yardLine, down: sb.down, distance: sb.distance, downDistanceText: sb.text, team: { id: sb.team }, possessionText: sb.text } : last?.end;
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
  const hp = Math.round(100 * home), ap = 100 - hp;
  const hc = readable(teams.home), ac = readable(teams.away);
  const w = 600, h = 96, mid = h / 2;
  const x = (i) => (i / (wp.length - 1)) * w;
  const y = (v) => h * (1 - v);
  const line = wp.map((p, i) => `${x(i).toFixed(1)},${y(p.homeWinPercentage).toFixed(1)}`).join(" ");
  const area = `0,${mid} ${line} ${w},${mid}`;
  // Quarter markers, from the play each probability belongs to
  const period = {};
  for (const d of allDrives(sum)) for (const pl of d.plays || []) period[pl.id] = pl.period?.number;
  const marks = [];
  let last = null;
  wp.forEach((p, i) => {
    const q = period[p.playId];
    if (q && q !== last) { if (last != null) marks.push([x(i), q]); last = q; }
  });
  const qLabel = (q) => (q <= 4 ? `Q${q}` : "OT");
  return `<div class="wp">
    <div class="wp-top">
      <span class="wp-team"><img src="${logo(teams.away.abbr)}" alt=""> ${teams.away.abbr} <b class="num" style="color:${ac}">${ap}%</b></span>
      <span class="wp-title">Win probability</span>
      <span class="wp-team right"><b class="num" style="color:${hc}">${hp}%</b> ${teams.home.abbr} <img src="${logo(teams.home.abbr)}" alt=""></span>
    </div>
    <div class="wp-bar"><i style="width:${ap}%;background:${ac}"></i><i style="width:${hp}%;background:${hc}"></i></div>
    <div class="wp-chart">
      <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-label="${teams.home.abbr} win probability over the game">
        <defs>
          <clipPath id="wp-top"><rect x="0" y="0" width="${w}" height="${mid}"/></clipPath>
          <clipPath id="wp-bot"><rect x="0" y="${mid}" width="${w}" height="${mid}"/></clipPath>
        </defs>
        <polygon points="${area}" fill="${hc}" fill-opacity=".35" clip-path="url(#wp-top)"/>
        <polygon points="${area}" fill="${ac}" fill-opacity=".35" clip-path="url(#wp-bot)"/>
        <line x1="0" x2="${w}" y1="${mid}" y2="${mid}" class="mid"/>
        ${marks.map(([mx]) => `<line x1="${mx}" x2="${mx}" y1="0" y2="${h}" class="q"/>`).join("")}
        <polyline points="${line}" fill="none" stroke="#fff" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
      </svg>
      <span class="wp-lab top"><img src="${logo(teams.home.abbr)}" alt=""> ${teams.home.abbr}</span>
      <span class="wp-lab bot"><img src="${logo(teams.away.abbr)}" alt=""> ${teams.away.abbr}</span>
      <span class="wp-lab fifty">50%</span>
      ${marks.map(([mx, q]) => `<span class="wp-q" style="left:${(100 * mx) / w}%">${qLabel(q)}</span>`).join("")}
    </div>
  </div>`;
}

// A team color that shows up on the dark background (falls back to the team's alternate color, then a light gray)
function readable(t) {
  const lum = (hex) => {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return 0;
    const n = parseInt(m[1], 16);
    return (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
  };
  if (lum(t.color) >= 0.3) return t.color;
  if (lum(t.alt) >= 0.3) return t.alt;
  return "#c7d0dc";
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

const GAME_TABS = [["plays", "Plays"], ["box", "Box Score"], ["props", "Props"], ["fantasy", "Fantasy"], ["injuries", "Injuries"]];
const PLAY_FILTERS = [["all", "All"], ["scoring", "Scoring"], ["big", "Big plays"], ["to", "Turnovers"], ["flag", "Flags"]];
const BOX_SECTIONS = [["off", "Offense", ["passing", "rushing", "receiving", "fumbles"]], ["def", "Defense", ["defensive", "interceptions"]],
  ["st", "Special teams", ["kicking", "punting", "kickReturns", "puntReturns"]]];

// Each game remembers its own tab and filters for the session
function gs(id = S.gameView) {
  const g = gameOf(id);
  return (S.gs[id] ??= {
    tab: g.state === "pre" ? "props" : g.state === "in" ? "plays" : "box",
    pbp: "all", team: "", q: "", order: "new", drives: null, box: "off", bteam: g.away, pos: "ALL", sort: g.state === "pre" ? "proj" : "live", leans: false,
  });
}

function seg(attr, cur, options, label) {
  return `<div class="seg" role="group" aria-label="${label}">${options.map(([v, l]) =>
    `<button class="${cur === v ? "on" : ""}" ${attr}="${v}" aria-pressed="${cur === v}">${l}</button>`).join("")}</div>`;
}

function teamSeg(teams, cur) {
  return seg("data-gteam", cur, [["", "Both"], ...["away", "home"].map((s) => [teams[s].abbr, `<img src="${logo(teams[s].abbr)}" alt="">${teams[s].abbr}`])], "Team");
}

function gamesInOrder(g) {
  if (g?.pastWeek) return S.weeks[g.pastWeek].games.map((x) => S.pastGames[x.id]).sort((a, b) => a.kickoff.localeCompare(b.kickoff) || a.id.localeCompare(b.id));
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
  // Quarter filter: a drive that crosses quarters shows only that quarter's plays
  const inQ = (pl) => !st.q || (st.q === "5" ? (pl.period?.number || 0) >= 5 : String(pl.period?.number) === st.q);
  const drives = all
    .filter((d) => !st.team || teamCode(d.team?.abbreviation || "") === st.team)
    .map((d) => (st.q ? { ...d, plays: (d.plays || []).filter(inQ) } : d))
    .filter((d) => !st.q || d.plays.length);
  const quarters = [...new Set(all.flatMap((d) => (d.plays || []).map((pl) => Math.min(5, pl.period?.number || 0))))].filter(Boolean).sort();
  const ordered = (arr) => (st.order === "new" ? arr.slice().reverse() : arr);
  const isOpen = (d) => (st.drives === "all" ? true : st.drives === "none" ? false : d.id === newest) !== S.openDrives.has(d.id);
  const allOpen = drives.length > 0 && drives.every(isOpen);
  // the scoreboard often has the newest play a few seconds before the play-by-play feed does
  const known = new Set(all.flatMap((d) => (d.plays || []).map((pl) => pl.id)));
  const lp = g.lastPlay && !known.has(g.lastPlay.id) && (!st.team || teamCode(Object.values(teams).find((x) => x.id === g.lastPlay.start?.team?.id)?.abbr || "") === st.team || !g.lastPlay.start?.team?.id) ? g.lastPlay : null;
  const justIn = lp && (st.pbp === "all" || (st.pbp === "scoring" ? lp.scoringPlay : playTags(lp).some((x) => x[0] === st.pbp)))
    ? `<div class="justin"><span class="ptag big">JUST IN</span>${playRow(lp, teams, roster, true)}</div>` : "";

  const toolbar = `<div class="gtool">
    ${seg("data-pbp", st.pbp, PLAY_FILTERS, "Show")}
    ${teamSeg(teams, st.team)}
    ${quarters.length > 1 ? seg("data-gq", st.q, [["", "All Qs"], ...quarters.map((q) => [String(q), q === 5 ? "OT" : `Q${q}`])], "Quarter") : ""}
    ${seg("data-order", st.order, [["new", "Newest first"], ["old", "Oldest first"]], "Order")}
    ${st.pbp === "all" ? `<button class="tbtn" data-drives="${allOpen ? "none" : "all"}">${allOpen ? "Collapse all" : "Expand all"}</button>` : ""}
  </div>`;
  if (!drives.length) return toolbar + `<div class="empty">No plays yet.</div>`;

  if (st.pbp !== "all") {
    const keep = (pl) => st.pbp === "scoring" ? pl.scoringPlay : playTags(pl).some((t) => t[0] === st.pbp);
    const plays = ordered(drives.flatMap((d) => (d.plays || []).filter(keep)));
    return toolbar + justIn + `<div class="gcount">${plays.length} ${plays.length === 1 ? "play" : "plays"}</div>`
      + (plays.length ? `<div class="play-list">${plays.map((pl) => playRow(pl, teams, roster, isFresh(pl))).join("")}</div>` : `<div class="empty">None yet.</div>`);
  }

  return toolbar + justIn + ordered(drives).map((d) => {
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
        return `<tr ${pid && S.byId[pid].props.length ? `data-open="${pid}"` : ""} class="${pid && S.byId[pid].props.length ? "click" : ""} ${pid && isMine(pid) ? "is-mine" : ""}"><td class="l">${esc(at.athlete.displayName)}</td>${(at.stats || []).map((v) => `<td>${esc(v)}</td>`).join("")}${withPts ? `<td class="ppr">${fmtPts(pprOf(at.athlete.displayName, abbr))}</td>` : ""}</tr>`;
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
    const pts = p ? livePPR(p) : fantasyPts(st2, "WR");
    if (pts) leaders.push({ name: p?.name || boxName(sum, key), team: key.split("|")[1], pos: p?.pos, pid, proj: p ? projPts(p) : null, pts, props: p?.props.length });
  }
  for (const p of S.data.players) {
    if (p.game_id !== g.id || seenIds.has(p.id) || !["K", "DEF"].includes(p.pos) || !posOk(p.pos)) continue;
    const pts = livePPR(p);
    if (pts) leaders.push({ name: p.name, team: p.team, pos: p.pos, pid: p.id, proj: projPts(p), pts, props: 0 });
  }
  if (g.pastWeek) {   // a finished week: that week's stat lines, not this week's players
    leaders.length = 0;
    for (const r of pastRows(g)) {
      const pts = fantasyPts(r.st, r.pos);
      if (pts) leaders.push({ name: r.name, team: r.team, pos: r.pos, pid: S.byId[r.id] ? r.id : null, proj: null, pts, props: 0 });
    }
  }
  leaders.sort((x, y) => y.pts - x.pts);
  const leaderCard = `<div class="card"><div class="cat-h" style="margin-bottom:6px"><span>Fantasy leaders (${scoringName()})</span><span class="muted" style="font-weight:500;font-size:12px">both teams</span></div>
    ${leaders.filter((x) => posOk(x.pos)).slice(0, 12).map((x, i) => `<div class="fl ${x.pid && isMine(x.pid) ? "is-mine" : ""}" ${x.props ? `data-open="${x.pid}"` : ""}>
      <span><span class="muted num">${i + 1}</span> ${esc(x.name)} <span class="muted">${x.team}${x.pos ? ` ${x.pos}` : ""}</span></span>
      <span>${x.proj != null ? `<span class="muted">proj ${fmtPts(x.proj)}</span> ` : ""}<b class="num">${fmtPts(x.pts)}</b></span></div>`).join("") || `<div class="note">No points yet.</div>`}
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
  const key = { proj: (p) => -(projPts(p) ?? -1), live: (p) => -(livePPR(p) ?? -1), lean: (p) => -leanSize(p) }[st.sort];
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

// Both teams' injury lists: ESPN's game report (every position, defense too) plus Sleeper's statuses (IR included)
const INJ_ORDER = ["Out", "Doubtful", "Questionable", "IR", "PUP", "Suspended", "NA", "COV", "DNR"];
function gameInjuries(g, sum) {
  const out = [], seen = new Set();
  const norm = (st) => (st === "Injured Reserve" ? "IR" : st === "Physically Unable to Perform" ? "PUP" : st);
  for (const t of sum?.injuries || []) {
    const team = teamCode(t.team?.abbreviation);
    if (team !== g.home && team !== g.away) continue;
    for (const i of t.injuries || []) {
      const status = norm(i.status);
      if (!status || status === "Active") continue;
      const pid = S.byEspn[String(i.athlete?.id)];
      const d = i.details || {};
      seen.add(pid || `n:${i.athlete?.displayName}`);
      out.push({ team, pid, name: i.athlete?.displayName, pos: i.athlete?.position?.abbreviation || "", status,
        part: [d.side, d.type, d.detail].filter((x) => x && x !== "Not Specified").join(" "), ret: d.returnDate, date: i.date });
    }
  }
  for (const p of g.pastWeek ? [] : [...S.data.players, ...(S.extra || [])]) {
    if (p.team !== g.home && p.team !== g.away) continue;
    const inj = injOf(p), r = p.inj_report || {};
    const status = norm(inj.status || (r.status && r.status !== "Active" ? r.status : null));
    if (!status || seen.has(p.id) || seen.has(`n:${p.name}`)) continue;
    out.push({ team: p.team, pid: p.id, name: p.name, pos: p.pos, status, part: [r.side !== "Not Specified" && r.side, r.part || inj.part, r.detail !== "Not Specified" && r.detail].filter(Boolean).join(" "), ret: r.ret, date: r.date || inj.news?.date });
  }
  const rank = (st) => { const k = INJ_ORDER.indexOf(st); return k < 0 ? 99 : k; };
  return out.sort((a, b) => rank(a.status) - rank(b.status) || a.name.localeCompare(b.name));
}

function renderGameInjuries(g, sum, teams) {
  if (!S.future && !g.pastWeek) loadFuture().then(() => S.gameView && renderGame());
  const all = gameInjuries(g, sum);
  const block = (key) => {
    const t = teams[key], list = all.filter((x) => x.team === t.abbr);
    return `<section class="ginj">
      <h3><img src="${logo(t.abbr)}" alt=""> ${esc(t.short)} <span class="muted">${list.length ? `${list.length} on the report` : ""}</span></h3>
      ${list.length ? list.map((x) => {
        const p = x.pid && S.byId[x.pid];
        const short = INJ_SHORT[x.status] || x.status;
        return `<div class="ginj-row ${p ? "tap" : ""} ${p && isMine(p.id) ? "is-mine" : ""}" ${p ? `data-open="${p.id}"` : ""}>
          <span class="pos ${x.pos}">${esc(x.pos)}</span>
          <span class="ginj-n"><b>${esc(x.name)}</b>${p && isMine(p.id) ? mineTag(p) : ""}${x.part ? ` <span class="muted">${esc(x.part)}</span>` : ""}</span>
          <span class="ginj-s"><span class="inj ${short === "Q" ? "Q" : ""}">${esc(short)}</span>${x.ret ? `<span class="muted small">back ${esc(dayText(x.ret.slice(0, 10)))}</span>` : ""}</span>
        </div>`;
      }).join("") : `<div class="empty small">No one on the injury report.</div>`}
    </section>`;
  };
  return `<div class="ginj-wrap">${block("away")}${block("home")}</div>
    <p class="note">${g.pastWeek ? "Both teams' injuries as of today, from ESPN (it doesn't keep each week's old report)."
      : "ESPN's injury report for this game (every position) plus Sleeper's statuses for fantasy players, including IR. Tap a fantasy player for his full report."}</p>`;
}

function renderGameFantasy(g, teams) {
  const st = gs(g.id);
  const started = g.state !== "pre";
  const rows = S.data.players.filter((p) => p.game_id === g.id && posOk(p.pos) && (!st.team || p.team === st.team) && (st.pos === "ALL" || p.pos === st.pos))
    .map((p) => ({ p, proj: projPts(p), live: livePPR(p) }))
    .filter((r) => (r.proj ?? 0) >= 0.5 || (r.live ?? 0) !== 0)
    .sort((a, b) => (started ? (b.live ?? -99) - (a.live ?? -99) : 0) || (b.proj ?? -1) - (a.proj ?? -1));
  return `<div class="gtool">
      ${teamSeg(teams, st.team)}
      ${seg("data-gpos", st.pos, usePositions(["ALL", "QB", "RB", "WR", "TE", "K", "DEF"]).map((x) => [x, x === "ALL" ? "All" : x]), "Position")}
    </div>
    <div class="tbl-wrap"><table class="tbl">
      <thead><tr><th class="l">Player</th><th>Proj</th><th>${g.state === "post" ? "Final" : "Live"}</th><th>+/-</th></tr></thead>
      <tbody>${rows.map(({ p, proj, live }) => {
        const diff = live != null && proj != null ? live - proj : null;
        return `<tr ${p.props.length ? `data-open="${p.id}"` : ""} class="${p.props.length ? "click" : ""} ${isMine(p.id) ? "is-mine" : ""}">
          <td class="l"><div class="who">${avatar(p)}<div><div><b>${esc(p.name)}</b>${injBadge(p)}${mineTag(p)}</div><div class="pmeta"><span class="pos ${p.pos}">${p.pos}</span> ${p.team}</div></div></div></td>
          <td class="big">${fmtPts(proj)}</td>
          <td class="big" style="color:var(--cyan)">${started ? (current(p)?.none ? "DNP" : fmtPts(live)) : "-"}</td>
          <td class="${diff > 0 ? "up" : diff < 0 ? "down" : ""}">${diff == null ? "-" : (diff > 0 ? "+" : "") + fmtPts(diff)}</td>
        </tr>`;
      }).join("") || `<tr><td class="l" colspan="4">No players match.</td></tr>`}</tbody>
    </table></div>`;
}

// ---- the page

function renderGame() {
  const g = gameOf(S.gameView);
  const past = !!g.pastWeek;
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
      <div class="gt-n"><b class="long">${esc(t.short)}</b><b class="abbr">${t.abbr}</b><span class="muted">${esc(t.record)}</span>${g.state === "in" ? `<span class="gt-to">${toDots(key === "home" ? g.homeTO : g.awayTO)} <span class="muted">TO</span></span>` : ""}</div>
      <div class="gt-s num ${g.state === "post" && score < other ? "lose" : ""}">${started && score != null ? score : ""}${g.state === "in" && g.poss === t.abbr ? `<i class="poss-dot"></i>` : ""}</div>
    </div>`;
  };
  const lastDrive = allDrives(sum).slice(-1)[0];
  const fromFeed = lastDrive?.plays?.slice(-1)[0];
  const lastPlay = g.state === "in" ? (g.lastPlay && g.lastPlay.id !== fromFeed?.id && !allDrives(sum).some((d) => (d.plays || []).some((pl) => pl.id === g.lastPlay.id)) ? g.lastPlay : fromFeed || g.lastPlay) : null;
  const order = gamesInOrder(g);
  const i = order.findIndex((x) => x.id === g.id);
  const prev = order[i - 1], next = order[i + 1];
  const nPlays = allDrives(sum).reduce((a, d) => a + (d.plays?.length || 0), 0);
  const nProps = past ? pastRows(g).filter((r) => r.lines).length : S.data.players.filter((p) => p.game_id === g.id && p.props.length).length;
  const nInj = gameInjuries(g, sum).length;
  const badge = { plays: started && nPlays ? nPlays : "", props: nProps || "", box: "", fantasy: "", injuries: nInj || "" };
  const body = { plays: () => renderPlays(g, sum, teams), box: () => renderBox(g, sum, teams), props: () => (past ? renderPastProps(g, teams) : renderGameProps(g, teams)), fantasy: () => (past ? renderPastFantasy(g, teams) : renderGameFantasy(g, teams)), injuries: () => renderGameInjuries(g, sum, teams) }[st.tab]();

  $("#main").innerHTML = `
    <div class="gnav">
      <button class="back" data-back>← ${past ? `Week ${g.pastWeek}` : "All games"}</button>
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
          ${g.state === "in" && g.drive ? `<div class="gh-drive">Drive: ${esc(g.drive)}</div>` : ""}
        </div>
        ${side("home")}</div>
      ${(() => {
        if (past) {
          const mine = S.sync ? pastRows(g).filter((r) => isMine(r.id)) : [];
          return mine.length ? `<div class="yours-line"><b>Your players:</b> ${mine.map((r) => `<span ${S.byId[r.id] ? `data-open="${r.id}"` : ""}>${esc(r.name)} <b class="num">${fmtPts(fantasyPts(r.st, r.pos))}</b></span>`).join(" · ")}</div>` : "";
        }
        const mine = S.sync ? S.data.players.filter((p) => p.game_id === g.id && isMine(p.id)) : [];
        return mine.length ? `<div class="yours-line"><b>Your players:</b> ${mine.map((p) => `<span data-open="${p.id}">${esc(p.name)} <b class="num">${current(p) ? fmtPts(livePPR(p)) : `proj ${fmtPts(projPts(p))}`}</b></span>`).join(" · ")}</div>` : "";
      })()}
      ${fieldView(g, teams, sum)}
      ${lastPlay ? `<div class="last-play"><span class="muted">Last play</span> ${esc(lastPlay.text || "")}</div>` : ""}
      ${gameLines(g, teams)}
      ${linescore(sum, teams)}
      ${winProb(sum, teams)}
    </div>
    <nav class="gtabs" role="tablist" aria-label="Game sections">
      ${GAME_TABS.map(([k, l]) => `<button role="tab" aria-selected="${st.tab === k}" class="${st.tab === k ? "on" : ""}" data-gsub="${k}">
        ${l}${k === "plays" && g.state === "in" ? `<i class="ldot" title="Live"></i>` : ""}${badge[k] !== "" ? `<span class="gbadge">${badge[k]}</span>` : ""}</button>`).join("")}
      ${g.state === "in" ? `<span class="gtabs-note">updates every 8s</span>` : ""}
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
  const g = gameOf(id);
  if (!g) return;
  if (g.pastWeek) S.viewWeek = g.pastWeek;
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
  if (m && gameOf(m[1])) {
    S.gameView = m[1];
    if (S.pastGames[m[1]] && !S.games[m[1]]) S.viewWeek = S.pastGames[m[1]].pastWeek;
    if (m[2] && GAME_TABS.some(([k]) => k === m[2])) gs().tab = m[2];
    return true;
  }
  const t = location.hash.match(/^#\/(props|fantasy|compare|league|trade|mine|news|record|about)$/);
  if (t) { S.gameView = null; S.tab = t[1]; return true; }
  return false;
}

window.addEventListener("popstate", () => {
  if (!S.data) return;
  takeYahooTokens();
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
  // on phones the header scrolls away (it would cover half the screen), so sticky bars sit at the very top
  const top = $(".top");
  const pinned = top && getComputedStyle(top).position === "sticky";
  document.documentElement.style.setProperty("--top-h", `${pinned ? top.offsetHeight : 0}px`);
}
window.addEventListener("resize", setTopHeight);

// ---------------------------------------------------------------- news and injuries

function ago(iso) {
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
}

function dayText(iso) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

async function loadNews(force) {
  if (!force && S.newsAt && Date.now() - S.newsAt < 300000) return;
  try {
    const d = await getJSON(`${ESPN}/news?limit=100`);
    S.news = d.articles || [];
    S.newsAt = Date.now();
  } catch (err) {
    console.warn("news", err);
  }
}

// A player's latest notes from ESPN (Rotowire blurb and headlines), loaded when asked for
async function loadPlayerNews(pid) {
  const p = S.byId[pid];
  if (!p?.espn_id || S.pnews[pid]) return;
  S.pnews[pid] = { loading: true };
  try {
    const d = await getJSON(`https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/${p.espn_id}/overview`);
    S.pnews[pid] = {
      note: d.rotowire ? { headline: d.rotowire.headline, story: d.rotowire.story, date: d.rotowire.published || d.rotowire.lastModified } : null,
      news: (d.news || []).slice(0, 5).map((n) => ({ headline: n.headline, date: n.lastModified || n.published, href: n.links?.web?.href })),
    };
  } catch (err) {
    S.pnews[pid] = { error: true };
  }
}

const LOG_LABELS = {
  pass_cmp: "Cmp", pass_att: "Att", pass_yd: "Pass Yds", pass_td: "Pass TD", pass_int: "Int", rush_att: "Car",
  rush_yd: "Rush Yds", rush_td: "Rush TD", rec_tgt: "Tgt", rec: "Rec", rec_yd: "Rec Yds", rec_td: "Rec TD",
};

// This season's games, like Sleeper's game log: snaps (and share of the team's snaps), main stats, points
function gameLog(p) {
  const keys = S.data.log_stats?.[p.pos];
  if (!keys) return "";
  const rows = (p.log || []).map((x) => ({ ...x, pts: logPts(p, x) }));
  // weeks his team played without him show as "Did not play" (0 points), weeks the team was off as "Bye"
  const opps = teamOpps(p.team), playedW = new Set(rows.map((x) => x.w));
  for (let w = 1; w < S.data.week; w++) {
    if (playedW.has(w)) continue;
    rows.push(opps[w] ? { w, opp: opps[w], dnp: true, pts: 0 } : { w, bye: true });
  }
  rows.sort((a, b) => a.w - b.w);
  const g = S.games[p.game_id];
  const c = current(p);
  if (c && c.none && g) rows.push({ w: S.data.week, opp: p.opp, dnp: true, pts: 0, now: true });
  else if (c && !c.none) {
    const st = c.stats;
    rows.push({ w: S.data.week, opp: p.opp, snp: st.off_snp, tsnp: st.tm_off_snp, s: keys.map((k) => st[k] || 0), pts: livePPR(p), now: true });
  } else if (g && g.state === "pre" && p.proj) {
    rows.push({ w: S.data.week, opp: p.opp, s: keys.map((k) => p.proj[k] || 0), pts: projPts(p), proj: true });
  }
  if (!S.future) loadFuture().then(refreshOpenCards);
  if (S.future) {
    const fut = futureRows(p);
    const byes = new Set(byesLeft(p));
    const last = Math.max(S.data.week, ...fut.map((x) => x.w));
    for (let w = S.data.week + 1; w <= last; w++) {
      const x = fut.find((y) => y.w === w);
      if (x) rows.push({ w, opp: x.opp, s: keys.map((k) => x.st[k] || 0), pts: x.pts, proj: true });
      else if (byes.has(w)) rows.push({ w, bye: true });
    }
  }
  if (!rows.length) return "";
  const snaps = (r) => (r.snp == null ? "-" : `${r.snp}${r.tsnp ? ` <span class="muted">${Math.round((100 * r.snp) / r.tsnp)}%</span>` : ""}`);
  const cellv = (v, proj) => (proj ? fmt(v, v < 10 ? 1 : 0) : v);
  const fut = rows.filter((r) => r.proj);
  const ros = S.future ? rosPts(p) : null;
  return `<div class="glog" style="grid-column:1/-1"><div class="tbl-wrap"><table class="box">
    <thead><tr><th class="l">Game log</th><th>Opp</th><th>Snaps</th>${keys.map((k) => `<th>${LOG_LABELS[k]}</th>`).join("")}<th class="ppr">Pts</th></tr></thead>
    <tbody>${rows.map((r) => r.bye
      ? `<tr class="bye"><td class="l">Week ${r.w}</td><td colspan="${keys.length + 3}">Bye</td></tr>`
      : r.dnp
      ? `<tr class="dnp"><td class="l">${r.now ? "Final" : `Week ${r.w}`}</td><td>${r.opp || ""}</td><td colspan="${keys.length + 1}" class="dnp-t">Did not play</td><td class="ppr">${fmtPts(0)}</td></tr>`
      : `<tr class="${r.now ? "now" : r.proj ? "proj" : ""}"><td class="l">${r.now ? (g.state === "post" ? "Final" : "Now") : `Week ${r.w}`}${r.proj ? ` <span class="ptag big">proj</span>` : ""}</td><td>${r.opp || ""}</td><td>${r.proj ? "" : snaps(r)}</td>${r.s.map((v) => `<td>${cellv(v, r.proj)}</td>`).join("")}<td class="ppr">${fmtPts(r.pts)}</td></tr>`).join("")}</tbody>
  </table></div>
  <div class="note">${S.future ? `Future weeks are Sleeper's projections, scored in ${esc(scoringName())}. Rest of season: <b>${fmtPts(ros)}</b> over ${rosGames(p)} games${byesLeft(p).length ? `, bye in week ${byesLeft(p).join(", ")}` : ""}.` : "Loading future weeks..."}</div></div>`;
}

// Who each team played in each past week (from every player's game log), so missed games still show up
function teamOpps(team) {
  if (!S.teamOppsMap) {
    S.teamOppsMap = {};
    for (const q of S.data.players) for (const x of q.log || []) if (x.opp) (S.teamOppsMap[q.team] ??= {})[x.w] = x.opp;
  }
  return S.teamOppsMap[team] || {};
}

// Weeks each team has played this season (from every player's game log), for "missed N of M games"
function teamWeeks(team) {
  if (!S.teamWeeksMap) {
    S.teamWeeksMap = {};
    for (const q of S.data.players) for (const x of q.log || []) (S.teamWeeksMap[q.team] ??= new Set()).add(x.w);
  }
  return S.teamWeeksMap[team]?.size || 0;
}

// Who plays more if he sits: teammates at his position, next on the depth chart
function nextUp(p) {
  return S.data.players.filter((q) => q.team === p.team && q.pos === p.pos && q.id !== p.id && !UNAVAILABLE.has(injOf(q).status))
    .sort((a, b) => (a.depth ?? 99) - (b.depth ?? 99) || (projPts(b) ?? 0) - (projPts(a) ?? 0)).slice(0, 2);
}

// The full injury picture for one player
function injuryDetail(p) {
  const inj = injOf(p), r = p.inj_report || {};
  const status = inj.status || (r.status && r.status !== "Active" ? r.status : null);
  const played = (p.log || []).length, teamGames = teamWeeks(p.team);
  const snaps = (p.log || []).slice(-3).map((x) => (x.snp != null && x.tsnp ? `Wk ${x.w} ${Math.round((100 * x.snp) / x.tsnp)}%` : null)).filter(Boolean);
  const tl = (p.inj_timeline || []).slice().reverse();
  const backups = nextUp(p);
  const when = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `<div class="injd">
    <div class="injd-facts">
      ${status ? `<span><b>Status</b> ${esc(status)}${inj.news?.inactive ? " (game-day inactive)" : ""}</span>` : ""}
      ${r.part || inj.part ? `<span><b>Injury</b> ${esc([r.side, r.part || inj.part, r.detail].filter((x) => x && x !== "Not Specified").join(" "))}</span>` : ""}
      ${r.ret ? `<span><b>Expected back</b> ${esc(dayText(r.ret))}</span>` : ""}
      ${teamGames ? `<span><b>Played</b> ${played} of ${teamGames} games${played < teamGames ? ` (missed ${teamGames - played})` : ""}</span>` : ""}
      ${snaps.length ? `<span><b>Snap share</b> ${snaps.join(", ")}</span>` : ""}
    </div>
    ${r.short ? `<p>${esc(r.short)}</p>` : ""}
    ${r.long ? `<details><summary>Full report</summary><p>${esc(r.long)}</p></details>` : ""}
    ${tl.length > 1 ? `<div class="injd-h">Timeline</div><ul class="injd-tl">${tl.map((x) => `<li><span class="muted">${esc(when(x.t))}</span> <b>${esc(x.status)}</b>${x.part ? ` (${esc(x.part)})` : ""}${x.note ? ` · ${esc(x.note)}` : ""}</li>`).join("")}</ul>` : ""}
    ${status && backups.length ? `<div class="injd-h">If he sits</div>${backups.map((q) => `<div class="injd-next" data-open="${q.id}"><span><b>${esc(q.name)}</b> <span class="muted">${q.pos}${q.depth ? q.depth : ""} on the depth chart</span>${injBadge(q)}</span><span class="num">${fmtPts(projPts(q))} <span class="muted small">proj this week · avg ${fmtPts(avgPts(q))}</span></span></div>`).join("")}` : ""}
  </div>`;
}

function latestBlock(p) {
  const r = p.inj_report;
  const inj = injOf(p);
  const extra = S.pnews[p.id];
  const status = inj.status || (r?.status && r.status !== "Active" ? r.status : null);
  if (!r && !inj.news && !p.espn_id) return "";
  return `<div class="latest" style="grid-column:1/-1">
    <div class="latest-h"><b>Latest</b>${status ? ` ${injBadge(p)}` : ""}
      ${r?.date ? `<span class="muted when">${ago(r.date)}</span>` : ""}</div>
    ${inj.news ? `<p class="gd">Game day (ESPN, ${ago(inj.news.date)}): <b>${inj.news.inactive ? "Inactive" : esc(inj.news.status || "Active")}</b></p>` : ""}
    ${status ? injuryDetail(p) : `${r?.short ? `<p>${esc(r.short)}</p>` : ""}${r?.long ? `<details><summary>More</summary><p>${esc(r.long)}</p></details>` : ""}`}
    ${extra?.note && extra.note.headline !== r?.short ? `<p class="rw"><span class="muted">Rotowire${extra.note.date ? `, ${ago(extra.note.date)}` : ""}:</span> ${esc(extra.note.headline)}</p>` : ""}
    ${extra?.news?.length ? `<ul class="hl">${extra.news.map((n) => `<li><a href="${esc(n.href || "#")}" target="_blank" rel="noopener">${esc(n.headline)}</a> <span class="muted">${n.date ? ago(n.date) : ""}</span></li>`).join("")}</ul>` : ""}
    ${p.espn_id && !extra ? `<button class="tbtn" data-pnews="${p.id}">More news</button>` : extra?.loading ? `<span class="muted">Loading...</span>` : extra?.error ? `<span class="muted">Couldn't load more news.</span>` : ""}
  </div>`;
}

function renderNews() {
  const view = S.newsView || "headlines";
  const head = `<h2>News</h2><div class="gtool">${seg("data-newsview", view, [["headlines", "Headlines"], ["injuries", "Injury report"]], "View")}</div>`;
  if (view === "injuries") return renderInjuries(head);
  const mine = new Set([...S.favs, ...S.mine.map((m) => m.pid)]);
  const mineOnly = S.newsMine;
  if (!S.news) {
    $("#main").innerHTML = head + `<div class="empty">Loading news...</div>`;
    loadNews().then(() => { if (S.tab === "news" && !S.gameView) renderNews(); });
    return;
  }
  // Newest first, optionally only the last few hours or days
  const within = S.newsWithin || "all";
  const now = Date.now();
  const startOfToday = new Date().setHours(0, 0, 0, 0);
  const keepTime = (t) => within === "all" ? true : within === "today" ? t >= startOfToday : now - t <= { "3h": 3, "72h": 72 }[within] * 3600000;
  const items = S.news.map((a) => {
    const ids = (a.categories || []).filter((c) => c.type === "athlete").map((c) => S.byEspn[String(c.athleteId || c.athlete?.id)]).filter(Boolean);
    return { a, ids: [...new Set(ids)], t: new Date(a.published || a.lastModified || 0).getTime() };
  }).filter((x) => (!mineOnly || x.ids.some((id) => mine.has(id))) && keepTime(x.t))
    .sort((x, y) => y.t - x.t);
  const bucket = (t) => {
    if (now - t < 3600000) return "Last hour";
    if (t >= startOfToday) return "Today";
    if (t >= startOfToday - 86400000) return "Yesterday";
    return "Earlier";
  };
  let lastBucket = null;
  $("#main").innerHTML = head.replace("</div>", ` ${seg("data-newswithin", within, [["3h", "Last 3 hours"], ["today", "Today"], ["72h", "Last 3 days"], ["all", "All"]], "Recency")}
      <button class="tbtn ${mineOnly ? "on" : ""}" data-newsmine>My players</button> <span class="note">ESPN · newest first · checked ${S.newsAt ? ago(new Date(S.newsAt).toISOString()) : ""}</span></div>`)
    + `<div class="news">${items.map(({ a, ids, t }) => {
      const img = a.images?.[0]?.url;
      const b = bucket(t);
      const head2 = b !== lastBucket ? `<h3 class="nbucket">${b}</h3>` : "";
      lastBucket = b;
      return `${head2}<article class="card nitem">
        ${img ? `<img class="nimg" src="${esc(img)}" alt="" loading="lazy">` : ""}
        <div>
          <a class="nh" href="${esc(a.links?.web?.href || "#")}" target="_blank" rel="noopener">${esc(a.headline)}</a>
          <p class="nd">${esc(a.description || "")}</p>
          <div class="nmeta"><span class="muted">${a.published ? ago(a.published) : ""}${a.byline ? ` · ${esc(a.byline)}` : ""}</span>
            ${ids.map((id) => { const q = S.byId[id]; return `<button class="pl-who" data-open="${id}"><span class="pos ${q.pos}">${q.pos}</span> ${esc(q.name)}</button>`; }).join("")}</div>
        </div>
      </article>`;
    }).join("") || `<div class="empty">${mineOnly ? "No news about your favorites or picks in this window." : "No news in this window."}</div>`}</div>`;
}

function renderInjuries(head) {
  const st = S.injFilter || "ALL";
  const pos = S.injPos || "ALL";
  const statusOf = (p) => injOf(p).status || (p.inj_report?.status !== "Active" ? p.inj_report?.status : null);
  const want = (status) => st === "ALL" || (st === "Q" ? status === "Questionable" : st === "D" ? status === "Doubtful" : st === "O" ? ["Out", "Suspended", "PUP", "NA", "DNR", "COV"].includes(status) : st === "IR" ? status === "IR" || status === "Injured Reserve" : true);
  const rows = S.data.players.filter((p) => {
    const status = statusOf(p);
    return status && want(status) && (pos === "ALL" || p.pos === pos) && ((projPts(p) ?? 0) >= 2 || p.depth === 1);
  });
  const byGame = {};
  for (const p of rows) (byGame[p.game_id] ??= []).push(p);
  const games = gamesInOrder().filter((g) => byGame[g.id]);
  $("#main").innerHTML = head.replace("</div>", ` ${seg("data-injf", st, [["ALL", "All"], ["Q", "Questionable"], ["D", "Doubtful"], ["O", "Out"], ["IR", "IR"]], "Status")}
      ${seg("data-injpos", pos, usePositions(["ALL", "QB", "RB", "WR", "TE", "K"]).map((x) => [x, x === "ALL" ? "All" : x]), "Position")}</div>`)
    + `<p class="note">Fantasy-relevant players only (projected 2+ points or a starter). Tap a player for the full report: injury and side, expected return, games missed, recent snap shares, how his status has changed this season, and who plays more if he sits. Status from Sleeper and ESPN, plus game-day news from ESPN as it's posted.</p>`
    + (games.map((g) => `<section class="inj-game">
        <h3><button class="linkbtn" data-game="${g.id}">${g.away} @ ${g.home}</button> <span class="muted">${esc(gameStatus(g))}</span></h3>
        ${byGame[g.id].sort((a, b) => a.team.localeCompare(b.team) || (projPts(b) ?? 0) - (projPts(a) ?? 0)).map((p) => {
          const r = p.inj_report || {};
          return `<details class="inj-d"><summary class="inj-row">
            ${avatar(p)}
            <div><div><b>${esc(p.name)}</b> <span class="pos ${p.pos}">${p.pos}</span> <span class="muted">${p.team}</span> ${injBadge(p)}
              ${r.part ? `<span class="muted">${esc(r.part)}</span>` : ""}${r.ret ? ` <span class="ret">back ${esc(dayText(r.ret))}</span>` : ""}</div>
              ${r.short ? `<div class="inj-note">${esc(r.short)}</div>` : ""}</div>
            <div class="side"><div class="small">proj</div><div class="num">${fmtPts(projPts(p))}</div><div class="small">${r.date ? ago(r.date) : ""}</div></div>
          </summary>${injuryDetail(p)}<button class="tbtn" data-open="${p.id}">Open ${esc(p.name)}</button></details>`;
        }).join("")}
      </section>`).join("") || `<div class="empty">No injuries match.</div>`);
}

// ---------------------------------------------------------------- scoring menu

function updateSyncBtn() {
  const b = $("#sync-btn");
  if (!b) return;
  b.textContent = S.sync ? `${S.sync.name || "My league"}` : "Sync league";
  b.classList.toggle("on", !!S.sync);
  b.title = S.sync ? "Your lineup and trade ideas" : "Sync your Sleeper or ESPN league";
}

async function goToSync() {
  S.tab = "league";
  S.gameView = null;
  await loadFuture();     // the Trade tab needs rest-of-season projections; wait so the sync box is there to focus
  render();
  syncHash(true);
  const box = $(".league-sync, .league");
  if (box) box.scrollIntoView({ block: "start" });
  $("#sync-q")?.focus();
}

function applyScoring() {
  S.ideas = null;
  $("#sc-btn").textContent = `${scoringName()} \u25be`;
  setTopHeight();
  const y = window.scrollY;
  render();
  window.scrollTo(0, y);
}

function renderScoringPanel() {
  const on = (mode, x) => (S.sc.mode === mode && (mode === "league" ? S.sc.league === x : !!S.sc.half === (x === "half")) ? "on" : "");
  const preset = (mode, half, label, note) => `<button class="sc-opt ${on(mode, half ? "half" : "ppr")}" data-sc="${mode}|${half ? "half" : "ppr"}"><b>${label}</b><span>${note}</span></button>`;
  $("#sc-panel").innerHTML = `
    <div class="sc-h">Scoring for QB, RB, WR, TE</div>
    <div class="sc-grid">
      ${preset("sleeper", false, "Sleeper PPR", "default")}
      ${preset("sleeper", true, "Sleeper Half PPR", "0.5 per catch")}
      ${preset("espn", false, "ESPN PPR", "INT -2")}
      ${preset("espn", true, "ESPN Half PPR", "INT -2, 0.5 per catch")}
    </div>
    <div class="sc-h">My Sleeper leagues</div>
    ${S.leagues.map((l) => `<div class="sc-lg"><button class="sc-opt ${on("league", l.id)}" data-sc="league|${l.id}"><b>${esc(l.name)}</b><span>${esc(l.season || "")} \u00b7 ${leagueSummary(l.settings)}</span></button><button class="rm" data-sc-rm="${l.id}" title="Remove" aria-label="Remove">\u00d7</button></div>`).join("") || `<p class="note">Use your league's exact scoring: enter your Sleeper username (or a league ID).</p>`}
    <div class="sc-find"><input id="sc-q" placeholder="Sleeper username or league ID" autocomplete="off" autocapitalize="off" spellcheck="false"><button class="tbtn" data-sc-find>Find</button></div>
    ${S.scMsg ? `<p class="note">${esc(S.scMsg)}</p>` : ""}
    ${S.scFound?.length ? S.scFound.map((l) => `<div class="sc-lg"><span><b>${esc(l.name)}</b> <span class="muted">${esc(l.season || "")} \u00b7 ${leagueSummary(l.scoring_settings)}</span></span><button class="tbtn" data-sc-add="${l.league_id}">Use</button></div>`).join("") : ""}
    <p class="note">Kickers and defenses always use ESPN standard scoring. Your choices are saved on this device.</p>`;
}

function leagueSummary(w = {}) {
  const bits = [w.rec === 1 ? "PPR" : w.rec === 0.5 ? "Half PPR" : w.rec ? `${w.rec} per catch` : "Standard"];
  if (w.pass_td && w.pass_td !== 4) bits.push(`${w.pass_td}-pt pass TD`);
  if (w.bonus_rec_te) bits.push(`TE +${w.bonus_rec_te}`);
  if (w.pass_int != null && w.pass_int !== -1) bits.push(`INT ${w.pass_int}`);
  return bits.join(", ");
}

async function findLeagues(q) {
  if (!q) return;
  S.scMsg = "Looking...";
  S.scFound = null;
  renderScoringPanel();
  try {
    let found = [];
    if (/^\d{8,}$/.test(q)) {
      const l = await getJSON(`https://api.sleeper.app/v1/league/${q}`);
      if (l?.league_id) found = [l];
    } else {
      const u = await getJSON(`https://api.sleeper.app/v1/user/${encodeURIComponent(q)}`);
      if (u?.user_id) found = (await getJSON(`https://api.sleeper.app/v1/user/${u.user_id}/leagues/nfl/${S.data.season}`)) || [];
    }
    S.scFound = found.filter((l) => l.scoring_settings);
    S.scMsg = S.scFound.length ? "" : "No Sleeper leagues found for that.";
  } catch {
    S.scMsg = "Couldn't reach Sleeper. Try again.";
  }
  renderScoringPanel();
  $("#sc-q").value = q;
}

document.addEventListener("submit", (e) => {
  if (!e.target.closest(".chat-in")) return;
  e.preventDefault();
  const ta = e.target.querySelector("textarea");
  const v = ta.value;
  ta.value = "";
  sendChat(v);
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && e.target.closest?.(".chat-in")) { e.preventDefault(); e.target.closest("form").requestSubmit(); return; }
  if (e.key === "Enter" && e.target.id === "sc-q") findLeagues(e.target.value.trim());
  if (e.key === "Enter" && e.target.id === "sync-q") syncFindUser(e.target.value);
  if (e.key === "Enter" && e.target.id === "espn-q") $("[data-espn-find]")?.click();
});

// ---------------------------------------------------------------- future weeks and rest of season

async function loadFuture() {
  if (S.future || S.futureLoading) return S.futureLoading;
  S.futureLoading = getJSON(`data/future.json?v=${encodeURIComponent(S.data.generated_at)}`)
    .then((f) => {
      S.future = f;
      // players not in this week's data (on bye or hurt), so league rosters and rankings still include them
      S.extra = Object.entries(f.meta || {}).filter(([id]) => !S.byId[id]).map(([id, [name, pos, team, injury]]) => {
        const p = { id, name, pos, team: team || "FA", injury, props: [], log: [], extra: true, freeAgent: !team };
        S.byId[id] = p;
        return p;
      });
    })
    .catch((err) => { console.warn("future", err); S.future = { players: {}, byes: {} }; });
  return S.futureLoading;
}

// Sleeper's projection for each remaining week, scored the same way as everything else on the site
function futureRows(p) {
  const sleeperOwn = isDefault() && p.pos !== "K" && p.pos !== "DEF";
  return ((S.future?.players || {})[p.id] || []).map((x) => ({
    ...x, pts: sleeperOwn && x.pp != null ? (S.sc.half ? x.ph ?? x.pp : x.pp) : fantasyPts(x.st, p.pos),
  }));
}

function byesLeft(p) {
  return (S.future?.byes || {})[p.team] || [];
}

// Rest of season: this week (if his game hasn't started) plus every remaining week
function rosPts(p) {
  // memoized per scoring choice: the trade finder asks for these thousands of times
  const key = `${S.sc.mode}|${S.sc.half}|${S.sc.league || ""}|${S.future ? 1 : 0}`;
  if (S.rosKey !== key) { S.rosKey = key; S.rosMemo = new Map(); }
  if (S.rosMemo.has(p.id)) return S.rosMemo.get(p.id);
  const g = S.games[p.game_id];
  const now = g && g.state === "pre" ? projPts(p) || 0 : 0;
  const v = futureRows(p).reduce((a, x) => a + x.pts, now);
  S.rosMemo.set(p.id, v);
  return v;
}

// Points per game when he plays: byes and weeks he's projected out don't count against him
function rosPerGame(p) {
  const g = S.games[p.game_id];
  const rows = futureRows(p).filter((x) => x.pts > 0.5).map((x) => x.pts);
  if (g && g.state === "pre" && (projPts(p) || 0) > 0.5) rows.push(projPts(p));
  return rows.length ? rows.reduce((a, b) => a + b, 0) / rows.length : 0;
}

// His rank at his position by projected points per game for the rest of the season (WR14 = 14th-best receiver).
// Byes and games he's expected to miss don't count against him.
function gradeOf(p) {
  const key = `${S.sc.mode}|${S.sc.half}|${S.sc.league || ""}|${S.future ? 1 : 0}`;
  if (S.gradeKey !== key) {
    S.gradeKey = key;
    S.gradeRank = {};
    for (const pos of ["QB", "RB", "WR", "TE", "K", "DEF"]) {
      rosPool().filter((q) => q.pos === pos && futureRows(q).length >= 2).map((q) => [q.id, rosPerGame(q)]).sort((a, b) => b[1] - a[1])
        .forEach(([id], i) => { S.gradeRank[id] = i + 1; });
    }
  }
  const rank = S.gradeRank[p.id];
  if (!rank) return null;
  // tiers for a 12-team league: starter, solid, flex or backup, deep bench
  const per = ["RB", "WR"].includes(p.pos) ? 12 : 6;
  const tier = rank <= per ? 1 : rank <= 2 * per ? 2 : rank <= 3 * per ? 3 : 4;
  return { label: `${p.pos}${rank}`, rank, tier, letter: `${p.pos}${rank}` };
}

const ordinal = (n) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"}`;
const POS_WORD = { QB: "quarterback", RB: "running back", WR: "receiver", TE: "tight end", K: "kicker", DEF: "defense" };

function gradeChip(p) {
  const g = gradeOf(p);
  if (!g) return "";
  return `<span class="prank t${g.tier}" title="${ordinal(g.rank)}-best ${POS_WORD[p.pos] || p.pos} by projected points per game the rest of the season">${g.label}</span>`;
}

// "A- · 14.2 a game · 13 games left"
function rosText(p) {
  const n = futureRows(p).filter((x) => x.pts > 0.5).length + (S.games[p.game_id]?.state === "pre" && (projPts(p) || 0) > 0.5 ? 1 : 0);
  return `${gradeChip(p)} <b class="num">${fmtPts(rosPerGame(p))}</b> <span class="muted">a game · ${n} games left</span>`;
}

// Kickers and defenses only show for leagues that start them (all positions when no league is synced)
function posOk(pos) {
  const slots = S.leagueData?.league.roster_positions || S.sync?.slots;
  if (!slots || !["K", "DEF"].includes(pos)) return true;
  return slots.includes(pos);
}
const usePositions = (list) => list.filter((x) => posOk(x));

// My synced roster (kept from the last sync until the league reloads)
function mySet() {
  if (S.leagueData && S.sync?.roster_id != null) {
    const ids = myRoster()?.players || [];
    if (S.sync.myIds?.join() !== ids.join()) { S.sync.myIds = ids; store("sync", S.sync); }
    return new Set(ids);
  }
  return new Set(S.sync?.myIds || []);
}
const isMine = (id) => !!S.sync && mySet().has(id);
const mineTag = (p) => (isMine(p.id) ? `<span class="yours-tag" title="On your team">YOURS</span>` : "");

// Everyone with rest-of-season projections: this week's players plus those on bye or hurt this week
const rosPool = () => [...S.data.players, ...(S.extra || []).filter((p) => !p.freeAgent)];

function rosGames(p) {
  const g = S.games[p.game_id];
  return futureRows(p).length + (g && g.state === "pre" ? 1 : 0);
}

function refreshOpenCards() {
  for (const id of S.open) {
    const c = $(`[data-player="${id}"]`);
    if (c) c.outerHTML = playerCard(S.byId[id]);
  }
}

// ---------------------------------------------------------------- compare two players

function playerLabel(p) {
  return `${p.name} (${p.pos} ${p.team})`;
}

function seasonPts(p) {
  return (p.log || []).map((x) => ({ w: x.w, opp: x.opp, v: logPts(p, x) })).filter((x) => x.v != null);
}

// Our pregame projection in the current scoring: the fantasy points prop (Sleeper x matchup) when he has one
function ourProj(p) {
  const f = p.props.find((x) => x.key === "fpts");
  const v = f ? pv(p, f).adj : null;
  return v ?? projPts(p);
}

function renderCompare() {
  const [a, b] = (S.cmp || []).map((id) => S.byId[id]);
  const options = S.data.players.filter((p) => (projPts(p) != null || p.log?.length) && posOk(p.pos))
    .sort((x, y) => (projPts(y) ?? 0) - (projPts(x) ?? 0)).map((p) => `<option value="${esc(playerLabel(p))}"></option>`).join("");
  const picker = (slot, p) => `<div class="cmp-pick">
    <input list="cmp-list" data-cmp-slot="${slot}" placeholder="Search a player" value="${p ? esc(playerLabel(p)) : ""}" autocomplete="off">
    ${p ? `<button class="rm" data-cmp-clear="${slot}" title="Clear" aria-label="Clear">×</button>` : ""}</div>`;
  const head = `<h2>Compare players <small>${esc(scoringName())}</small></h2>
    <datalist id="cmp-list">${options}</datalist>
    <div class="cmp-pickers">${picker(0, a)}<span class="vs">vs</span>${picker(1, b)}</div>`;
  if (!a || !b) {
    $("#main").innerHTML = head + `<div class="card empty-card"><p>Pick two players to compare them side by side. You can also tap <b>Compare</b> on any player card.</p></div>`;
    return;
  }
  const pa = seasonPts(a), pb = seasonPts(b);
  const avg = (xs) => (xs.length ? xs.reduce((s2, x) => s2 + x.v, 0) / xs.length : null);
  const last3 = (xs) => avg(xs.slice(-3));
  const lo = (xs) => (xs.length ? Math.min(...xs.map((x) => x.v)) : null);
  const hi = (xs) => (xs.length ? Math.max(...xs.map((x) => x.v)) : null);
  const projA = ourProj(a), projB = ourProj(b);
  const noGame = { state: "pre", kickoff: "" };
  const ga = S.games[a.game_id] || noGame, gb = S.games[b.game_id] || noGame;
  const live = (p) => (current(p) ? livePPR(p) : null);
  const status = (p) => injOf(p).status || "Healthy";
  const mrank = (p) => defRank(p.opp, p.pos)?.rank;

  // one row: label, both values, which side is better ("high", "low" or none)
  const row = (label, va, vb, better, f = fmtPts, title = "") => {
    let wa = "", wb = "";
    if (better && va != null && vb != null && va !== vb) {
      const aWins = better === "high" ? va > vb : va < vb;
      wa = aWins ? "win" : ""; wb = aWins ? "" : "win";
    }
    return `<tr${title ? ` title="${esc(title)}"` : ""}><td class="${wa}">${va == null ? "-" : f(va)}</td><th>${label}</th><td class="${wb}">${vb == null ? "-" : f(vb)}</td></tr>`;
  };
  const pctF = (v) => `${Math.round(100 * v)}%`;
  const rankF = (v) => `#${v} of 32`;
  const txt = (v) => esc(v);
  const card = (p, g) => `<div class="cmp-card" data-open="${p.id}">
    ${avatar(p)}<div><div><b>${esc(p.name)}</b> <span class="pos ${p.pos}">${p.pos}</span>${injBadge(p)}</div>
    <div class="pmeta">${p.freeAgent ? "Free agent" : `${p.team} ${p.opp ? oppText(p) : ""} · ${esc(gameStatus(S.games[p.game_id]))}`}</div></div></div>`;

  // the call: our pregame projections, with a note when they're close
  let verdict = "";
  if (projA != null && projB != null) {
    const d = projA - projB;
    const fav = d >= 0 ? a : b;
    verdict = Math.abs(d) < 1
      ? `<div class="verdict even">Too close to call: our projections are within a point (${fmtPts(projA)} vs ${fmtPts(projB)}).</div>`
      : `<div class="verdict">We'd start <b>${esc(fav.name)}</b>: projected ${fmtPts(Math.max(projA, projB))} vs ${fmtPts(Math.min(projA, projB))} (+${fmtPts(Math.abs(d))}) in ${esc(scoringName())}.</div>`;
  }

  const keys = [...new Set([...a.props, ...b.props].map((x) => x.key))].filter((k) => k !== "fpts");
  const propRow = (k) => {
    const xa = a.props.find((x) => x.key === k), xb = b.props.find((x) => x.key === k);
    const cell = (x) => !x ? "-" : k === "anytime_td" ? `${Math.round(100 * (x.td_chance || 0))}% TD chance`
      : `${x.line} <span class="src ${x.line_from || "ours"}">${LINE_TAG[x.line_from] || "est"}</span> · proj ${fmtStat(k, x.adj)}${x.lean ? ` <span class="arrow ${x.lean}">${x.lean === "over" ? "▲" : "▼"}</span>` : ""}<div class="muted">over in ${x.over} of ${x.n}</div>`;
    return `<tr><td>${cell(xa)}</td><th>${S.data.categories[k].label}</th><td>${cell(xb)}</td></tr>`;
  };
  const weeks = [...new Set([...pa, ...pb].map((x) => x.w))].sort((x, y) => x - y);
  const wk = (xs, w) => xs.find((x) => x.w === w);

  $("#main").innerHTML = head + `
    <div class="cmp-heads">${card(a, ga)}${card(b, gb)}</div>
    ${verdict}
    <div class="tbl-wrap"><table class="cmp">
      <tbody>
        <tr class="sec"><td colspan="3">Fantasy (${esc(scoringName())})</td></tr>
        ${row("Our projection", projA, projB, "high", fmtPts, "Sleeper's projection adjusted for the matchup, made before kickoff")}
        ${row("Sleeper projection", projPts(a), projPts(b), "high")}
        ${ga.state !== "pre" || gb.state !== "pre" ? row(ga.state === "post" && gb.state === "post" ? "Final" : "Live", live(a), live(b), "high") : ""}
        ${row("Season average", avg(pa), avg(pb), "high")}
        ${row("Rest-of-season schedule", scheduleFor(a)?.avg ?? null, scheduleFor(b)?.avg ?? null, "high", (v) => `${fmt(v)} ${v >= 20 ? "(easy)" : v <= 13 ? "(hard)" : ""}`, "Average defensive rank of remaining opponents against the position (higher = easier)")}
        ${row("Last 3 games", last3(pa), last3(pb), "high")}
        ${row("Floor (worst game)", lo(pa), lo(pb), "high")}
        ${row("Ceiling (best game)", hi(pa), hi(pb), "high")}
        ${row("Snap share", a.snap_share, b.snap_share, "high", pctF)}
        <tr class="sec"><td colspan="3">Matchup</td></tr>
        ${row("Opponent", a.opp ? `${a.home ? "vs" : "@"} ${a.opp}` : "Not playing", b.opp ? `${b.home ? "vs" : "@"} ${b.opp}` : "Not playing", null, txt)}
        ${row(`Opponent's defense rank`, mrank(a), mrank(b), "high", rankF, "The opponent's rank against the position this season: #1 allows the fewest fantasy points (toughest), #32 the most (easiest)")}
        ${row("Team implied points", impliedFor(a), impliedFor(b), "high", (v) => fmt(v), "From the DraftKings spread and total")}
        ${row("Status", status(a), status(b), null, txt)}
        ${keys.length ? `<tr class="sec"><td colspan="3">Props (line · our pregame projection)</td></tr>${keys.map(propRow).join("")}` : ""}
        ${weeks.length ? `<tr class="sec"><td colspan="3">Game log (${esc(scoringName())})</td></tr>${weeks.map((w) => {
          const x = wk(pa, w), y = wk(pb, w);
          return row(`Week ${w}`, x ? x.v : null, y ? y.v : null, "high", (v) => fmtPts(v)).replace("<th>", `<th title="${x ? `${a.name}: vs ${x.opp}` : ""} ${y ? `${b.name}: vs ${y.opp}` : ""}">`);
        }).join("")}` : ""}
      </tbody>
    </table></div>
    <p class="note">Green marks the better number in each row. Our projection is pregame (Sleeper's projection adjusted for how similar players have done against that defense this season).</p>`;
}

function setCompare(slot, id) {
  S.cmp = [...(S.cmp || [null, null])];
  S.cmp[slot] = id;
  store("cmp", S.cmp);
}

// ---------------------------------------------------------------- my picks

function minePick(pid, key, dir) {
  return S.mine.find((m) => m.pid === pid && m.key === key && m.dir === dir && m.season === S.data.season && m.week === S.data.week);
}

function toggleMine(pid, key, dir, line) {
  const have = minePick(pid, key, dir);
  if (have) S.mine = S.mine.filter((m) => m !== have);
  else {
    // one side per prop: picking the over replaces an under on the same prop
    S.mine = S.mine.filter((m) => !(m.pid === pid && m.key === key && m.season === S.data.season && m.week === S.data.week));
    S.mine.push({ pid, key, dir, line: +line, season: S.data.season, week: S.data.week, at: Date.now() });
  }
  store("mine", S.mine);
  updateMineBadge();
}

// Game bets: {kind: "game", gid, market: "spread" | "total" | "ml", side: team code or "over"/"under", line, odds}
function mineGame(gid, market, side) {
  return S.mine.find((m) => m.kind === "game" && m.gid === gid && m.market === market && m.side === side && m.season === S.data.season && m.week === S.data.week);
}

function toggleGame(gid, market, side, line, odds) {
  const have = mineGame(gid, market, side);
  if (have) S.mine = S.mine.filter((m) => m !== have);
  else {
    // one side per market: taking one team's spread replaces the other's
    S.mine = S.mine.filter((m) => !(m.kind === "game" && m.gid === gid && m.market === market && m.season === S.data.season && m.week === S.data.week));
    S.mine.push({ kind: "game", gid, market, side, line: line === "" ? null : +line, odds: odds === "" ? null : +odds, season: S.data.season, week: S.data.week, at: Date.now() });
  }
  store("mine", S.mine);
  updateMineBadge();
}

function gameBetLabel(m, g) {
  const sign = (x) => (x > 0 ? `+${x}` : `${x}`);
  if (m.market === "total") return `${m.side === "over" ? "Over" : "Under"} ${m.line} total points`;
  if (m.market === "spread") return `${m.side} ${m.line === 0 ? "pick'em" : sign(m.line)}`;
  return `${m.side} to win${m.odds != null ? ` (${ml(m.odds)})` : ""}`;
}

// Where a game bet stands: live margins and totals, then hit, miss or push at the final
function gameBetStatus(m) {
  const g = S.games[m.gid];
  if (!g || g.state === "pre" || g.home_score == null) return null;
  const final = g.state === "post";
  const hs = g.home_score, as = g.away_score;
  if (m.market === "total") {
    const t = hs + as;
    const over = t > m.line;
    const res = final ? (t === m.line ? "push" : over === (m.side === "over") ? "hit" : "miss") : over ? (m.side === "over" ? "hit" : "miss") : "live";
    return { res, final, v: t, note: `${t} points${final ? "" : " so far"}${!final && !over ? `, ${fmt(m.line - t, 1)} under the line` : ""}`, pct: Math.min(100, (100 * t) / Math.max(m.line, 1)) };
  }
  const mine = m.side === g.home ? hs - as : as - hs;
  if (m.market === "spread") {
    const margin = mine + m.line;
    const res = final ? (margin === 0 ? "push" : margin > 0 ? "hit" : "miss") : "live";
    return { res, final, v: mine, note: margin > 0 ? `covering by ${fmt(margin, margin % 1 ? 1 : 0)}` : margin < 0 ? `short by ${fmt(-margin, margin % 1 ? 1 : 0)}` : "right on the number" };
  }
  const res = final ? (mine === 0 ? "push" : mine > 0 ? "hit" : "miss") : "live";
  const ahead = final ? ["won by", "lost by", "tied"] : ["leads by", "trails by", "tied"];
  return { res, final, v: mine, note: mine > 0 ? `${m.side} ${ahead[0]} ${mine}` : mine < 0 ? `${m.side} ${ahead[1]} ${-mine}` : ahead[2] };
}

function updateMineBadge() {
  const n = S.data ? S.mine.filter((m) => m.season === S.data.season && m.week === S.data.week).length : 0;
  const el = $("#mine-n");
  if (el) { el.textContent = n || ""; el.hidden = !n; }
}

function renderMine() {
  const thisWeek = (m) => m.season === S.data.season && m.week === S.data.week;
  const now = S.mine.filter((m) => thisWeek(m) && (m.kind === "game" ? S.games[m.gid] : S.byId[m.pid]));
  const old = S.mine.length - now.length;
  if (!now.length) {
    $("#main").innerHTML = `<h2>My Picks</h2><div class="card empty-card">
      <p><b>Track any prop or game bet live.</b> Open a player on the Props tab and tap <span class="add over on demo">+ Over</span> or <span class="add under on demo">+ Under</span> on any line, tap <b>+</b> on a top pick, or open a game and tap <b>+</b> on its spread, total or moneyline. Your picks are saved on this device and follow the games live.</p>
      ${old ? `<p class="note">${old} pick${old === 1 ? "" : "s"} from an earlier week. <button class="tbtn" data-mine-clear="old">Clear them</button></p>` : ""}
    </div>`;
    return;
  }
  const rows = now.map((m) => {
    if (m.kind === "game") {
      const g = S.games[m.gid];
      return { m, g, st: gameBetStatus(m) };
    }
    const p = S.byId[m.pid];
    const g = S.games[p.game_id];
    return { m, p, g, st: propStatus(p, m.key, m.line, m.dir), prop: p.props.find((x) => x.key === m.key) };
  });
  const rank = (r) => (r.g.state === "in" ? 0 : r.g.state === "pre" ? 1 : 2);
  rows.sort((a, b) => rank(a) - rank(b) || a.g.kickoff.localeCompare(b.g.kickoff) || a.m.at - b.m.at);
  const hit = rows.filter((r) => r.st?.res === "hit").length;
  const miss = rows.filter((r) => r.st?.res === "miss").length;
  const push = rows.filter((r) => r.st?.res === "push").length;
  const final = rows.filter((r) => r.st?.final).length;
  const live = rows.filter((r) => r.g.state === "in").length;
  const entry = miss ? "lost" : hit + push === rows.length && hit ? "won" : "open";
  const gameRow = ({ m, g, st }) => `<div class="pick mine ${st?.res || ""}" data-game="${g.id}">
      <div class="av def"><img src="${logo(m.market === "total" ? g.home : m.side)}" alt=""></div>
      <div>
        <div><b>${esc(gameBetLabel(m, g))}</b> <span class="ptag big">${m.market === "ml" ? "MONEYLINE" : m.market.toUpperCase()}</span>
          ${m.market !== "ml" ? `<label class="mline">line <input type="number" step="0.5" inputmode="decimal" value="${m.line}" data-mline="g|${g.id}|${m.market}|${m.side}" aria-label="Your line"></label>` : ""}</div>
        <div class="what">${g.away} @ ${g.home}${g.state !== "pre" ? ` · <b class="num">${g.away} ${g.away_score} - ${g.home} ${g.home_score}</b>` : ""}</div>
        <div class="small">${esc(gameStatus(g))}${st?.note ? ` · ${esc(st.note)}` : ""}</div>
        ${st?.pct != null ? `<div class="prog ${st.res === "hit" ? "hit" : st.res === "miss" ? "miss" : ""}"><i style="width:${st.pct}%"></i></div>` : ""}
      </div>
      <div class="side">
        ${st ? resBadge(st) : ""}
        <button class="rm" data-rm-game="${g.id}|${m.market}|${m.side}" title="Remove" aria-label="Remove">×</button>
      </div>
    </div>`;
  const propRow = ({ m, p, g, st, prop }) => {
    const label = S.data.categories[m.key].label;
    const lineNow = prop?.line;
    return `<div class="pick mine ${st?.res || ""}" data-open="${p.id}">
        ${avatar(p)}
        <div>
          <div><b>${esc(p.name)}</b> <span class="pos ${p.pos}">${p.pos}</span>${injBadge(p)} <span class="muted">${oppText(p)}</span></div>
          <div class="what">${m.dir === "over" ? "Over" : "Under"} <label class="mline"><input type="number" step="0.5" inputmode="decimal" value="${m.line}" data-mline="p|${p.id}|${m.key}|${m.dir}" aria-label="Your line"></label> ${label}${lineNow != null && lineNow !== m.line ? ` <span class="muted">(DK line ${lineNow})</span>` : ""}</div>
          <div class="small">${esc(gameStatus(g))}${liveLineText(p, m.key, m.line)}</div>
          ${progress(st, m.line, m.dir, m.key)}
        </div>
        <div class="side">
          ${st ? `<div class="big">${st.v == null ? "-" : fmtStat(m.key, st.v)}</div>${resBadge(st)}` : `<div class="small">${esc(kickoffText(g.kickoff))}</div>`}
          <button class="rm" data-rm="${p.id}|${m.key}|${m.dir}" title="Remove" aria-label="Remove">×</button>
        </div>
      </div>`;
  };
  $("#main").innerHTML = `
    <h2>My Picks <small>${S.data.season} week ${S.data.week}</small></h2>
    <div class="mine-sum card">
      <div><div class="k">Hit</div><div class="v num" style="color:var(--green)">${hit}</div></div>
      <div><div class="k">Missed</div><div class="v num" style="color:var(--red)">${miss}</div></div>
      <div><div class="k">Live</div><div class="v num" style="color:var(--cyan)">${live}</div></div>
      <div><div class="k">Not started</div><div class="v num">${rows.filter((r) => r.g.state === "pre").length}</div></div>
      <div class="entry ${entry}"><div class="k">All ${rows.length} together</div><div class="v">${entry === "won" ? "Won" : entry === "lost" ? "Lost" : `${hit} of ${rows.length}`}</div></div>
    </div>
    <div class="plist">${rows.map((r) => (r.m.kind === "game" ? gameRow(r) : propRow(r))).join("")}</div>
    <div class="gtool" style="margin-top:12px">
      ${final ? `<button class="tbtn" data-mine-clear="final">Clear finished</button>` : ""}
      <button class="tbtn" data-mine-clear="all">Clear all</button>
      ${old ? `<button class="tbtn" data-mine-clear="old">Clear ${old} from earlier weeks</button>` : ""}
    </div>
    <p class="note">Picks keep the line you added them at; change any line to the one you actually got (an alternate spread like -4.5, a different total). Overs show cleared as soon as they pass the line; unders, spreads and moneylines settle when the game is final (a push is a tie with the line).</p>`;
}

// ---------------------------------------------------------------- render and events

function render() {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", !S.gameView && b.dataset.tab === S.tab));
  if (S.gameView) { renderGame(); renderScores(); return; }
  ({ props: renderProps, fantasy: renderFantasy, compare: renderCompare, league: renderLeagueTab, trade: renderTrade, mine: renderMine, news: renderNews, record: renderRecord, about: renderAbout })[S.tab]();
  updateSyncBtn();
  updateMineBadge();
  renderScores();
}

// Live ticks update numbers in place, so open cards, focus and scroll position survive
function renderLiveParts() {
  if (!S.gameView && S.tab === "mine") { if (!document.activeElement?.matches("input")) { const y = window.scrollY; renderMine(); window.scrollTo(0, y); } return; }
  if (!S.gameView && S.tab === "league") { if ((S.leagueView || "team") === "matchups" && !document.activeElement?.matches("input")) { const y = window.scrollY; renderLeagueTab(); window.scrollTo(0, y); } return; }
  if (!S.gameView && S.tab === "compare") { if (!document.activeElement?.matches("input")) { const y = window.scrollY; renderCompare(); window.scrollTo(0, y); } return; }
  if (!S.gameView && S.tab === "news") {
    if (Date.now() - S.newsAt > 300000) loadNews().then(() => { if (S.tab === "news" && !S.gameView && (S.newsView || "headlines") === "headlines") { const y = window.scrollY; renderNews(); window.scrollTo(0, y); } });
    return;
  }
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
  for (const [attr, field] of [["data-pbp", "pbp"], ["data-gteam", "team"], ["data-gq", "q"], ["data-order", "order"], ["data-box", "box"], ["data-bteam", "bteam"], ["data-gpos", "pos"], ["data-gsort", "sort"]]) {
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
  const nv = t.closest("[data-newsview]");
  if (nv) { S.newsView = nv.dataset.newsview; renderNews(); return; }
  if (t.closest("[data-newsmine]")) { S.newsMine = !S.newsMine; renderNews(); return; }
  const nw = t.closest("[data-newswithin]");
  if (nw) { S.newsWithin = nw.dataset.newswithin; renderNews(); return; }
  const injf = t.closest("[data-injf]");
  if (injf) { S.injFilter = injf.dataset.injf; renderNews(); return; }
  const injpos = t.closest("[data-injpos]");
  if (injpos) { S.injPos = injpos.dataset.injpos; renderNews(); return; }
  const pn = t.closest("[data-pnews]");
  if (pn) {
    const id = pn.dataset.pnews;
    const redraw = () => { const c = $(`[data-player="${id}"]`); if (c) c.outerHTML = playerCard(S.byId[id]); };
    loadPlayerNews(id).then(redraw);
    redraw();
    return;
  }
  if (t.closest("#sc-btn")) { const panel = $("#sc-panel"); panel.hidden = !panel.hidden; if (!panel.hidden) renderScoringPanel(); return; }
  const pick = t.closest("[data-sc]");
  if (pick) {
    const [mode, x] = pick.dataset.sc.split("|");
    S.sc = mode === "league" ? { mode, league: x, half: false } : { mode, half: x === "half" };
    store("scoring", S.sc);
    $("#sc-panel").hidden = true;
    applyScoring();
    return;
  }
  const addLg = t.closest("[data-sc-add]");
  if (addLg) {
    const l = S.scFound.find((x) => x.league_id === addLg.dataset.scAdd);
    if (l && !S.leagues.some((x) => x.id === l.league_id)) {
      S.leagues.push({ id: l.league_id, name: l.name, season: l.season, settings: l.scoring_settings, teams: l.total_rosters, roster_positions: l.roster_positions });
      store("leagues", S.leagues);
    }
    S.sc = { mode: "league", league: l.league_id, half: false };
    store("scoring", S.sc);
    S.scFound = null;
    $("#sc-panel").hidden = true;
    applyScoring();
    return;
  }
  const rmLg = t.closest("[data-sc-rm]");
  if (rmLg) {
    S.leagues = S.leagues.filter((l) => l.id !== rmLg.dataset.scRm);
    store("leagues", S.leagues);
    if (S.sc.mode === "league" && S.sc.league === rmLg.dataset.scRm) { S.sc = { mode: "sleeper", half: false }; store("scoring", S.sc); applyScoring(); }
    renderScoringPanel();
    return;
  }
  if (t.closest("[data-sc-find]")) { findLeagues($("#sc-q").value.trim()); return; }
  if (!t.closest("#sc-panel") && $("#sc-panel") && !$("#sc-panel").hidden) $("#sc-panel").hidden = true;
  const ca = t.closest("[data-cmp-add]");
  if (ca) {
    const id = ca.dataset.cmpAdd;
    const cur = S.cmp || [null, null];
    // first empty slot; with both filled, he replaces the second player
    if (!cur.includes(id)) setCompare(cur[0] ? 1 : 0, id);
    S.tab = "compare"; S.gameView = null;
    render(); syncHash(true); window.scrollTo(0, 0);
    return;
  }
  if (t.closest("[data-sync-find]")) { syncFindUser($("#sync-q").value); return; }
  if (t.closest("[data-yahoo-find]")) { yahooFind(); return; }
  if (t.closest("[data-yahoo-out]")) { S.yahoo = null; S.yahooLeagues = null; store("yahoo", null); rerenderLeagueViews(); return; }
  const yp = t.closest("[data-yahoo-pick]");
  if (yp) { syncLeague(yp.dataset.yahooPick, null, "yahoo"); return; }
  if (t.closest("[data-go-sync]")) { goToSync(); return; }
  if (t.closest("[data-hide-promo]")) { store("syncPromoHidden", true); renderProps(); return; }
  const sa = t.closest("[data-sync-app]");
  if (sa) { S.syncApp = sa.dataset.syncApp; S.syncMsg = ""; rerenderLeagueViews(); return; }
  if (t.closest("[data-espn-find]")) {
    const id = $("#espn-q").value.trim();
    if (/^\d+$/.test(id)) syncLeague(id, null, "espn");
    else { S.syncMsg = "That doesn't look like an ESPN league ID (it's a number)."; rerenderLeagueViews(); }
    return;
  }
  const sp = t.closest("[data-sync-pick]");
  if (sp) { syncLeague(sp.dataset.syncPick, S.syncUser?.id); return; }
  const st2 = t.closest("[data-sync-team]");
  if (st2) { S.sync.roster_id = +st2.dataset.syncTeam; store("sync", S.sync); S.ideas = null; rerenderLeagueViews(); return; }
  if (t.closest("[data-sync-refresh]")) { S.leagueData = null; S.syncMsg = ""; rerenderLeagueViews(); return; }
  if (t.closest("[data-sync-clear]")) { S.sync = null; S.leagueData = null; S.ideas = null; store("sync", null); rerenderLeagueViews(); updateSyncBtn(); return; }
  const idea = t.closest("[data-idea]");
  if (idea) {
    const x = S.ideas[+idea.dataset.idea];
    S.trade = { give: [...x.give], get: [...x.get] };
    store("trade", S.trade);
    renderTrade();
    $("#calc")?.scrollIntoView({ block: "start" });
    return;
  }
  if (t.closest("[data-ai-build]")) { buildAiTrades(); return; }
  const aid = t.closest("[data-ai-idea]");
  if (aid) {
    const x = S.aiTrades[+aid.dataset.aiIdea];
    S.trade = { give: [...x.give], get: [...x.get] };
    store("trade", S.trade);
    renderTrade();
    $("#calc")?.scrollIntoView({ block: "start" });
    return;
  }
  const tg = t.closest("[data-target]");
  if (tg) {
    // put him on the "get" side and show the deals that bring him back (or let the calculator take it from there)
    S.trade = { give: [], get: [tg.dataset.target] };
    store("trade", S.trade);
    renderTrade();
    $("#calc")?.scrollIntoView({ block: "start" });
    return;
  }
  const fs = t.closest("[data-fa-sort]");
  if (fs) { S.faSort = fs.dataset.faSort; renderLeagueTab(); return; }
  const tk = t.closest("[data-tx-kind]");
  if (tk) { S.txKind = tk.dataset.txKind; renderLeagueTab(); return; }
  if (t.closest("[data-draft-mine]")) { S.draftMine = !S.draftMine; renderLeagueTab(); return; }
  const lv = t.closest("[data-league-view]");
  if (lv) { e.preventDefault(); S.leagueView = lv.dataset.leagueView; renderLeagueTab(); return; }
  if (t.closest("[data-go-trade]")) { e.preventDefault(); S.tab = "trade"; render(); syncHash(true); window.scrollTo(0, 0); return; }
  const fp = t.closest("[data-fa-pos]");
  if (fp) { S.faPos = fp.dataset.faPos; renderLeagueTab(); return; }
  const ai = t.closest("[data-ask-idea]");
  if (ai) { const x = S.ideas[+ai.dataset.askIdea]; askAboutTrade(x.give, x.get, x.roster); return; }
  if (t.closest("[data-ask-trade]")) {
    const owner = S.leagueData?.rosters.find((r) => S.trade.get.every((id) => (r.players || []).includes(id)));
    askAboutTrade(S.trade.give, S.trade.get, owner?.roster_id);
    return;
  }
  if (t.closest("[data-ask-close]") || t.id === "ask-box") { $("#ask-box")?.remove(); return; }
  if (t.closest("[data-chat-here]")) { const q = $("#ask-box textarea").value; $("#ask-box")?.remove(); openChat(q); return; }
  if (t.closest("#chat-btn")) { openChat(); return; }
  const cq = t.closest("[data-chat-q]");
  if (cq) { sendChat(cq.dataset.chatQ); return; }
  if (t.closest("[data-chat-close]")) { $("#chat").hidden = true; document.body.classList.remove("chat-open"); return; }
  if (t.closest("[data-chat-clear]")) { S.chat = []; S.chatExtra = null; renderChat(); return; }
  if (t.closest("[data-ask-copy]")) {
    const ta = $("#ask-box textarea");
    navigator.clipboard?.writeText(ta.value).then(() => { t.closest("[data-ask-copy]").textContent = "Copied"; }).catch(() => { ta.select(); });
    return;
  }
  const ig = t.closest("[data-idea-get]");
  if (ig) { S.ideaGet = ig.dataset.ideaGet; S.ideas = null; renderTrade(); return; }
  const iv = t.closest("[data-idea-give]");
  if (iv) { S.ideaGive = iv.dataset.ideaGive; S.ideas = null; renderTrade(); return; }
  const fv = t.closest("[data-fview]");
  if (fv) { S.ff.view = fv.dataset.fview; S.ff.shown = 60; renderFantasy(); return; }
  const trm = t.closest("[data-trade-rm]");
  if (trm) {
    const [k, id] = trm.dataset.tradeRm.split("|");
    S.trade[k] = S.trade[k].filter((x) => x !== id);
    store("trade", S.trade); renderTrade(); return;
  }
  if (t.closest("[data-trade-clear]")) { S.trade = { give: [], get: [] }; store("trade", S.trade); renderTrade(); return; }
  const cc = t.closest("[data-cmp-clear]");
  if (cc) { setCompare(+cc.dataset.cmpClear, null); renderCompare(); return; }
  const gadd = t.closest("[data-gadd]");
  if (gadd) {
    e.stopPropagation();
    const [gid, market, side, line, odds] = gadd.dataset.gadd.split("|");
    toggleGame(gid, market, side, line, odds);
    if (S.gameView) renderGame();
    return;
  }
  const rmg = t.closest("[data-rm-game]");
  if (rmg) {
    e.stopPropagation();
    const [gid, market, side] = rmg.dataset.rmGame.split("|");
    toggleGame(gid, market, side);
    renderMine();
    return;
  }
  const add = t.closest("[data-add]");
  if (add) {
    e.stopPropagation();
    const [pid, key, dir, line] = add.dataset.add.split("|");
    toggleMine(pid, key, dir, line);
    if (S.gameView) renderGame();
    else if (S.tab === "props") {
      const card = $(`[data-player="${pid}"]`);
      if (card) card.outerHTML = playerCard(S.byId[pid]);
      document.querySelectorAll(`.pick [data-add^="${pid}|${key}|"]`).forEach((b) => {
        const on = !!minePick(pid, key, b.dataset.add.split("|")[2]);
        b.classList.toggle("on", on);
        b.textContent = on ? "\u2713" : "+";
      });
    } else render();
    return;
  }
  const rm = t.closest("[data-rm]");
  if (rm) {
    const [pid, key, dir] = rm.dataset.rm.split("|");
    toggleMine(pid, key, dir);
    renderMine();
    return;
  }
  const clr = t.closest("[data-mine-clear]");
  if (clr) {
    const kind = clr.dataset.mineClear;
    const thisWeek = (m) => m.season === S.data.season && m.week === S.data.week;
    if (kind === "all" && !confirm("Remove all your picks for this week?")) return;
    S.mine = S.mine.filter((m) => kind === "old" ? thisWeek(m)
      : kind === "all" ? !thisWeek(m)
      : !(thisWeek(m) && (m.kind === "game" ? gameBetStatus(m)?.final : S.byId[m.pid] && propStatus(S.byId[m.pid], m.key, m.line, m.dir)?.final)));
    store("mine", S.mine);
    renderMine();
    updateMineBadge();
    return;
  }
  const fav = t.closest("[data-fav]");
  if (fav) {
    const id = fav.dataset.fav;
    S.favs.has(id) ? S.favs.delete(id) : S.favs.add(id);
    store("favs", [...S.favs]);
    render();
    return;
  }
  const wk = t.closest("[data-wk]");
  if (wk) { if (!wk.disabled) setWeek(+wk.dataset.wk); return; }
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
    syncHash(true);
    $(`[data-player="${p.id}"]`)?.scrollIntoView({ block: "center" });
    return;
  }
  const toggle = t.closest("[data-toggle]");
  if (toggle && !t.closest("input")) {
    const id = toggle.dataset.toggle;
    S.open.has(id) ? S.open.delete(id) : S.open.add(id);
    if (!S.future) loadFuture().then(() => { const c = $(`[data-player="${id}"]`); if (c && S.open.has(id)) c.outerHTML = playerCard(S.byId[id]); });
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
  if (t.id === "ai-want") { S.aiWant = t.value; return; }
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
  if (e.target.matches("[data-wksel]")) { setWeek(+e.target.value); return; }
  if (e.target.matches("[data-mu-week]")) { S.muWeek = +e.target.value; renderLeagueTab(); return; }
  const t = e.target;
  if (t.dataset.mline) {
    const v = parseFloat(t.value);
    if (Number.isNaN(v)) return;
    const [kind, a, b, c] = t.dataset.mline.split("|");
    const m = S.mine.find((x) => (kind === "g" ? x.kind === "game" && x.gid === a && x.market === b && x.side === c : x.kind !== "game" && x.pid === a && x.key === b && x.dir === c) && x.season === S.data.season && x.week === S.data.week);
    if (m) { m.line = v; store("mine", S.mine); renderMine(); }
    return;
  }
  if (t.dataset.tradeSide) {
    const p = rosPool().find((x) => playerLabel(x) === t.value);
    const k = t.dataset.tradeSide, other = k === "give" ? "get" : "give";
    if (p && !S.trade[k].includes(p.id)) {
      S.trade[k].push(p.id);
      S.trade[other] = S.trade[other].filter((x) => x !== p.id);
      store("trade", S.trade);
      renderTrade();
      $(`[data-trade-side="${k}"]`)?.focus();
    }
    return;
  }
  if (t.dataset.cmpSlot != null) {
    const p = S.data.players.find((x) => playerLabel(x) === t.value);
    if (p) { setCompare(+t.dataset.cmpSlot, p.id); t.blur(); renderCompare(); }
    return;
  }
  const set = { "f-game": "game", "f-cat": "cat", "f-sort": "sort" }[t.id];
  if (set) { S.f[set] = t.value; S.shown = 40; render(); return; }
  if (t.id === "f-out") { S.f.hideOut = t.checked; renderProps(); return; }
  if (t.id === "f-favs") { S.f.favs = t.checked; renderProps(); }
});

$("#sync-btn").addEventListener("click", goToSync);

$("#all-features").addEventListener("click", (e) => {
  e.preventDefault();
  S.tab = "about";
  S.gameView = null;
  render();
  syncHash(true);
  window.scrollTo(0, 0);
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
  if (["props", "fantasy", "compare", "league", "trade", "mine", "news", "record", "about"].includes(saved)) S.tab = saved;
  try {
    await load();
  } catch (err) {
    $("#main").innerHTML = `<div class="empty">Couldn't load this week's data. Try refreshing.</div>`;
    console.error(err);
    return;
  }
  takeYahooTokens();
  const deep = location.hash.match(/^#\/game\/(\d+)/);
  if (deep && !S.games[deep[1]]) await loadPastWeeks();
  applyHash();
  if (WORKER_URL) {
    document.body.insertAdjacentHTML("beforeend", `<button id="chat-btn" class="chat-btn" title="Ask AI about trades, start/sit, matchups"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H8l-4 4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>Ask AI</button>`);
  }
  if (S.sc.mode === "league" && !currentLeague()) S.sc = { mode: "sleeper", half: false };
  $("#sc-btn").textContent = `${scoringName()} \u25be`;
  setTopHeight();
  render();
  syncHash(false);
  liveTick();
  setInterval(() => { if (!document.hidden) checkMeta(); }, META_MS);
})();
