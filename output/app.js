"use strict";

// Live data comes straight from ESPN in the browser (the hourly build can't keep up with a game in progress).
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl";
const ESPN_TO_SLEEPER = { WSH: "WAS" };
const LIVE_MS = 30000;   // scores and box scores while a game is on
const IDLE_MS = 300000;  // scores when nothing is live
const META_MS = 60000;   // checks for a new build
const UNAVAILABLE = new Set(["Out", "IR", "PUP", "Suspended", "NA", "Doubtful", "COV", "DNR"]);
const SHORT = {
  pass_yd: "Pass Yds", pass_td: "Pass TD", pass_cmp: "Comp", pass_att: "Pass Att", pass_int: "INT",
  rush_yd: "Rush Yds", rush_att: "Rush Att", rec: "Rec", rec_yd: "Rec Yds", rush_rec_yd: "Rush+Rec",
  anytime_td: "Anytime TD", fpts: "PPR Pts",
};
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
  return c && !c.none ? ppr(c.stats) : null;
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
        }
      }
    }
  }
  for (const play of summary.scoringPlays || []) {
    const abbr = teamCode(play.team?.abbreviation || "");
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

async function pollBoxScores() {
  const ids = Object.values(S.games)
    .filter((g) => g.state === "in" || (g.state === "post" && !S.boxFinal.has(g.id)))
    .map((g) => g.id);
  await Promise.all(ids.map(async (id) => {
    try {
      const summary = await getJSON(`${ESPN}/summary?event=${id}`);
      for (const [key, stats] of Object.entries(liveStatsFromSummary(summary))) {
        const pid = S.byKey[key];
        if (pid) S.live[pid] = stats;
      }
      S.boxLoaded.add(id);
      if (S.games[id].state === "post") S.boxFinal.add(id);
    } catch (err) {
      console.warn("box score", id, err);
    }
  }));
}

let liveTimer = null;
async function liveTick() {
  clearTimeout(liveTimer);
  try {
    await pollScores();
    await pollBoxScores();
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
  S.generatedAt = S.data.generated_at;
  try { S.track = await getJSON(`data/track_record.json?t=${Date.now()}`); } catch { S.track = null; }
  S.byId = {};
  S.byKey = {};
  for (const p of S.data.players) {
    S.byId[p.id] = p;
    S.byKey[`${normName(p.name)}|${p.team}`] = p.id;
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
  $("#strip").innerHTML = games.map((g) => {
    const live = g.state === "in";
    const started = g.state !== "pre";
    const row = (team, score, other) => `
      <div class="row ${g.state === "post" && score < other ? "lose" : ""}">
        <img src="${logo(team)}" alt="" loading="lazy"><span class="abbr ${live && g.poss === team ? "poss" : ""}">${team}</span>
        <span class="sc">${started && score != null ? score : ""}</span>
      </div>`;
    return `<button class="game ${live ? "live" : ""} ${g.rz ? "rz" : ""} ${S.f.game === g.id && S.tab === "props" ? "on" : ""}" data-game="${g.id}">
      ${row(g.away, g.away_score, g.home_score)}${row(g.home, g.home_score, g.away_score)}
      <div class="st"><span class="clock">${esc(gameStatus(g))}</span><span class="dd">${esc(live ? g.dd || "" : g.state === "pre" ? g.tv || "" : "")}</span></div>
    </button>`;
  }).join("");
}

// ---------------------------------------------------------------- shared bits

function avatar(p) {
  return `<div class="av"><img src="${photo(p.id)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'"><img class="tm" src="${logo(p.team)}" alt="" loading="lazy"></div>`;
}

function injBadge(p) {
  if (!p.injury) return "";
  const short = INJ_SHORT[p.injury] || p.injury;
  const title = p.injury + (p.injury_part ? ` (${p.injury_part})` : "");
  return `<span class="inj ${short === "Q" ? "Q" : ""}" title="${esc(title)}">${esc(short)}</span>`;
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
      <div class="small">${adj != null ? `Our number <b class="num">${fmt(adj)}</b> · ` : ""}over in ${pick.over} of last ${pick.n}</div>
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
  const lineText = prop.key === "anytime_td" ? "" : `<b>${line}</b>`;
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
    : prop.source !== "history"
      ? `<span class="lean none">No lean</span>`
      : `<span class="lean ${lean || "none"}">${lean ? `Lean ${lean}` : "No lean"}</span>`;

  const bars = vals.map((x) => `<div class="b ${x.v > line ? "o" : ""}" title="${x.s} week ${x.w} vs ${x.opp}: ${x.v}"><span>${fmtStat(prop.key, x.v)}</span><i style="height:${(100 * x.v) / top}%"></i></div>`).join("")
    + (nowV != null ? `<div class="b now" title="This week"><span>${fmtStat(prop.key, nowV)}</span><i style="height:${(100 * nowV) / top}%"></i></div>` : "");
  const xs = vals.map((x) => `<span>${x.s !== S.data.season ? "'" + String(x.s).slice(2) + " " : ""}W${x.w}</span>`).join("")
    + (nowV != null ? `<span style="color:var(--cyan)">Now</span>` : "");

  const lineCell = prop.key === "anytime_td"
    ? `<div>Line<span class="n">0.5</span></div>`
    : `<div>Line<input type="number" step="1" inputmode="decimal" value="${line}" data-line="${k}" aria-label="${cat.label} line"></div>`;
  const note = prop.key === "anytime_td"
    ? `Scored in ${vals.filter((x) => x.v > 0).length} of last ${vals.length}. Chance comes from Sleeper's projected TDs.`
    : prop.source === "projection"
      ? "Fewer than 4 games played, so this line is Sleeper's projection and has no lean."
      : `Over in <b>${over}</b> of last ${vals.length}${edited ? ` at your line (ours is ${prop.line})` : ""}.`;

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
  const out = UNAVAILABLE.has(p.injury);
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
    && (!f.hideOut || !UNAVAILABLE.has(p.injury))
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
    <p class="note">Top picks are the biggest gaps between Sleeper's projection and our line (players with 2+ games this season, not ruled out). Picks lock at kickoff. <a href="#" data-goto="about">How lines work</a></p>

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
  const pos = ff.pos === "FLEX" ? ["RB", "WR", "TE"] : ff.pos === "ALL" ? ["QB", "RB", "WR", "TE"] : [ff.pos];
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
    <div class="filters"><div class="chips">${["QB", "RB", "WR", "TE", "FLEX", "ALL"].map((x) => `<button class="chip ${ff.pos === x ? "on" : ""}" data-fpos="${x}">${x === "ALL" ? "All" : x}</button>`).join("")}</div></div>
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
    <p class="note">Proj is Sleeper's projection for this week. Live comes from ESPN's box score every 30 seconds and matches Sleeper's final scoring, except rare special teams plays (a fumble recovery or blocked kick by an offensive player), which show up after the next hourly update. Avg is this season's average.</p>`;
}

// ---------------------------------------------------------------- track record tab

function pctText(t) {
  return t && t.pct != null ? `${fmt(t.pct)}%` : "-";
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
    <h2>By week</h2>${weeks}
    <p class="note">A hit needs the result strictly over or under the line (lines end in .5, so there are no pushes). Players who didn't play are DNP, not misses. Lines first built after a game kicked off are never graded.</p>`;
}

// ---------------------------------------------------------------- how it works tab

function renderAbout() {
  const cats = Object.entries(S.data.categories).filter(([k]) => k !== "anytime_td");
  const sc = S.data.scoring;
  const scoreRows = [
    ["Passing yard", sc.pass_yd], ["Passing TD", sc.pass_td], ["Interception", sc.pass_int], ["Rushing yard", sc.rush_yd],
    ["Rushing or receiving TD", sc.rush_td], ["Reception", sc.rec], ["Receiving yard", sc.rec_yd], ["2-point conversion", sc.pass_2pt],
    ["Fumble lost", sc.fum_lost], ["Special teams TD", sc.st_td],
  ];
  $("#main").innerHTML = `<div class="about">
    <h2>Lines</h2>
    <p>No sportsbook lines are used. Each line is built from the player's last 8 games (this season and last), and only games before this week count.</p>
    <p>A plain average sits too high: big games pull it up, and injury exits and lost roles pull real games down. With the plain average, the result landed under the line about 63% of the time. So each category's average is scaled down by a factor fit on 2025 games to make it a 50/50 line, then checked on 2026 games the fit never saw. The line is that number rounded to a .5, so there are no pushes. Players with fewer than 4 games get Sleeper's projection as the line and no lean.</p>
    <table class="ptable">${cats.map(([k, v]) => `<tr><td>${v.label}</td><td class="num">x ${v.shrink}</td></tr>`).join("")}</table>
    <h2>Leans and top picks</h2>
    <p>A lean means Sleeper's projection for this week disagrees with the line. The projection is scaled the same way as the line (that's "our number"), and if it's far enough above the line it leans over, below it leans under. Top picks are the biggest of those gaps, measured in each category's typical spread, for players who have played 2+ games this season and aren't out, doubtful or on IR. Each player gets at most one top over and one top under.</p>
    <p>Matchup tags (soft/tough) show how many PPR points the opponent allows to the position. They're shown for context only, not used in leans, until they prove useful in the track record.</p>
    <h2>Fantasy points</h2>
    <p>PPR with Sleeper's standard settings. Our formula reproduces Sleeper's own PPR totals on every player-week from 2025 and 2026 (about 6,000), and that's re-checked on every update.</p>
    <table class="ptable">${scoreRows.map(([k, v]) => `<tr><td>${k}</td><td class="num">${v > 0 ? "+" : ""}${v}</td></tr>`).join("")}</table>
    <h2>Live scoring</h2>
    <p>Scores and box scores come straight from ESPN every 30 seconds while games are on (every 5 minutes otherwise, and paused when this tab is hidden). Live PPR uses the same formula, including 2-point conversions from the scoring plays. An over is marked cleared the moment it passes the line, since stats only go up; an under is only a hit once the game is final.</p>
    <h2>Updates</h2>
    <p>Lines, projections and injuries rebuild every hour. Once a game kicks off, its lines and picks are frozen. When a new update is out, a banner appears at the top of the page.</p>
    <h2>Honest grading</h2>
    <p>The track record only grades what was posted before kickoff. It wasn't backfilled: Sleeper revises its projections for past weeks after the games, so grading old weeks with them would use information nobody had beforehand.</p>
  </div>`;
}

// ---------------------------------------------------------------- render and events

function render() {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === S.tab));
  ({ props: renderProps, fantasy: renderFantasy, record: renderRecord, about: renderAbout })[S.tab]();
  renderScores();
}

// Live ticks update numbers in place, so open cards, focus and scroll position survive
function renderLiveParts() {
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
  if (tab) { S.tab = tab.dataset.tab; store("tab", S.tab); render(); window.scrollTo(0, 0); return; }
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
    S.tab = "props";
    S.f.game = S.f.game === game.dataset.game ? "" : game.dataset.game;
    S.shown = 40;
    render();
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
    S.tab = "props";
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
  render();
  liveTick();
  setInterval(() => { if (!document.hidden) checkMeta(); }, META_MS);
})();
