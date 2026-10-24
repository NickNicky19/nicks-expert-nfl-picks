"use strict";
// Actual display/load helpers with fictional inputs. No browser or provider.
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../output/app.js"), "utf8");
const names = ["startWeeklyOverlay", "selectedPropForecast", "propChip", "catCard", "tdChanceText", "forecastAccuracyHtml"];
const functions = names.map(name => {
  const match = source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`));
  assert.ok(match, "actual " + name); return match[0];
}).join("\n");
let checks = 0;
const check = (value, message) => { assert.ok(value, message); checks++; };
const equal = (actual, expected, message) => { assert.deepEqual(actual, expected, message); checks++; };
const now = Date.parse("2031-10-24T12:00:00Z"), kickoff = "2031-10-25T17:00:00Z";
const props = [
  { key: "rec", line: 4, adj: 2.5, proj: 2, lean: "under", line_from: "dk", values: [] },
  { key: "rush_yd", line: 10, adj: 8, proj: 7, lean: null, line_from: "ours", values: [] },
  { key: "anytime_td", line: .5, adj: null, proj: .4, td_chance: null, lean: null, line_from: "dk", values: [] },
  { key: "fpts", line: 9, adj: 8, proj: 7, lean: null, line_from: "ours", values: [] }
];
const player = { id: "fictional-player", game_id: "fictional-game", team: "AAA", opp: "BBB", pos: "RB", props };
const board = { season: 2031, week: 7, games: [{ id: player.game_id, kickoff, state: "post" }], players: [player],
  picks: { over: [], under: [] }, categories: Object.fromEntries(props.map(p => [p.key, { label: p.key, lean: 1 }])) };
const original = JSON.stringify(board), storage = new Map([["nflprops.mine", "UNCHANGED_MY_PICKS"], ["nflprops.paper-ticket.v1.fixture", "UNCHANGED_PAPER"]]);
const state = { data: board, lines: {}, liveLines: {}, games: { [player.game_id]: board.games[0] }, weeklyOverlay: null,
  weeklyOverlayReady: true, weeklyOverlayBoardHash: "a".repeat(64), weeklyOverlayRequestBoard: null, tab: "props", gameView: null };
let renders = 0;
const context = { S: state, pv: (_p, p) => p, propStatus: () => ({ v: null, res: "unresolved", final: false }), minePick: () => false,
  esc: value => String(value),
  SHORT: { rec: "Rec", rush_yd: "Rush yds", anytime_td: "TD", fpts: "PPR" }, LINE_FROM: { dk: "DraftKings", ours: "Our estimate" }, LINE_TAG: { dk: "DK", ours: "est" },
  fmt: (v, n = 1) => Number(v).toFixed(n), fmtPts: v => Number(v).toFixed(1), fmtStat: (_k, v) => Number(v).toFixed(1),
  scoringName: () => "PPR", remaining: () => .5, resBadge: st => `<b>${st.res}</b>`, renderProps: () => { renders++; }, renderGame: () => { renders++; },
  localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) } };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../output/weekly-adaptive-overlay.js"), "utf8") + "\nDate.now=()=>" + now + ";\n" + functions + "\nthis.api={" + names.join(",") + "};", context);
const a = context.api;
const candidate = (category, value, product, functional, expiry = kickoff) => ({ player_id: player.id, game_id: player.game_id, category,
  method_id: "FICTIONAL", model_version: "a".repeat(64), procedure_version: "b".repeat(64), product, prediction_functional: functional,
  forecast_value: value, horizon: "player_game", source_cutoff_utc: "2031-10-24T11:00:00Z", issued_at: "2031-10-24T10:00:00Z",
  persistence_completed_at: "2031-10-24T10:01:00Z", kickoff_utc: kickoff, valid_until_utc: expiry, selection_sha256: "c".repeat(64),
  source_policy_sha256: "d".repeat(64), query_source_sha256: "e".repeat(64), first_prepared_at: "2031-10-24T10:02:00Z" });
const overlay = rows => context.WeeklyAdaptiveOverlay.validate({ schema_version: "weekly-adaptive-public-overlay-v1", registration_id: "weekly-adaptive-release-v1",
  state: "PROVISIONAL", season: board.season, week: board.week, canonical_board_sha256: "a".repeat(64), display_board_sha256: "a".repeat(64),
  board_contract_sha256: "a".repeat(64), prepared_at: "2031-10-24T10:02:00Z", packaged_at: "2031-10-24T10:02:00Z", website_source_sha: "b".repeat(40),
  publication_review_sha256: "c".repeat(64), rows, frozen_rows: [], fallback_counts: {} }, board, "a".repeat(64));
const selected = [candidate("rec", 3.25, "point_mean", "expected_mean"), candidate("rush_yd", -2.5, "point_median", "intended_median"), candidate("anytime_td", .35, "binary_probability", "event_probability")];
const baseCards = props.map(p => a.catCard(player, p)), baseChips = props.map(p => a.propChip(player, p));
check(baseCards[2].includes("Unavailable TD chance"), "unknown reference TD does not become zero");
check(baseCards[0].includes("Final evidence") && baseCards[0].includes("Unresolved") && !baseCards[0].includes(">DNP<"), "unresolved final evidence stays unresolved");
state.weeklyOverlay = overlay(selected);
equal(a.selectedPropForecast(player, "rec", now).text, "3.25", "typed mean");
equal(a.selectedPropForecast(player, "rush_yd", now).text, "-2.50", "signed typed median");
equal(a.selectedPropForecast(player, "anytime_td", now).text, "35.0%", "typed event probability");
equal(a.selectedPropForecast(player, "fpts", now), null, "exact PPR is not replaced");
check(a.catCard(player, props[2]).includes("Current reference probability") && a.catCard(player, props[2]).includes("Unavailable"), "selected TD preserves unknown reference probability");
check(a.catCard(player, props[0]).includes("does not give a bet-win probability"), "point forecast is not a win probability");
state.lines[player.id + "|rec"] = 6;
check(a.propChip(player, props[0]).includes("Your line") && a.propChip(player, props[0]).includes("custom"), "personal line keeps its label");
check(a.catCard(player, props[0]).includes('value="6"'), "personal line stays exact");
equal(JSON.stringify(board), original, "canonical board forecasts and selections unchanged");
equal([...storage], [["nflprops.mine", "UNCHANGED_MY_PICKS"], ["nflprops.paper-ticket.v1.fixture", "UNCHANGED_PAPER"]], "private saved bytes unchanged");
state.lines = {};
state.weeklyOverlay = overlay([candidate("rec", 3.25, "point_mean", "expected_mean", "2031-10-24T11:00:00Z")]);
equal(a.selectedPropForecast(player, "rec", now), null, "expired before kickoff falls back");
equal(a.selectedPropForecast(player, "rec", Date.parse("2031-10-25T18:00:00Z")), null, "expired forecast does not acquire frozen status later");
state.weeklyOverlay = overlay(selected);
equal(a.selectedPropForecast(player, "rec", Date.parse("2031-10-25T18:00:00Z")).frozen, true, "valid started forecast remains frozen");
state.weeklyOverlay = null;
for (let i = 0; i < props.length; i++) { equal(a.catCard(player, props[i]), baseCards[i], "missing overlay preserves reference card"); equal(a.propChip(player, props[i]), baseChips[i], "missing overlay preserves reference chip"); }
state.weeklyOverlay = { rows: new Map([[JSON.stringify([player.game_id, player.id, "rec"]), {}]]) };
equal(a.selectedPropForecast(player, "rec", now), null, "malformed modern row does not produce a selected display");
check(source.includes("Historical R0 records retain their original source identity"), "historical identity remains distinct from current reference");
const accuracy = a.forecastAccuracyHtml({ cohorts: [], capture_coverage: [], uncertainty: {}, limitations: [] });
check(accuracy.includes("Evaluates saved reference forecasts in the listed model/engine cohorts.") && accuracy.includes("Provisional display forecasts are not scored here."), "visible Record accuracy excludes provisional display forecasts");
check(source.includes("Sort: Reference biggest lean") && source.includes("Sort: Reference projected points"), "display sorts remain reference sorts");
const load = source.match(/async function load\([^]*?\n\}/)[0];
check(load.includes("weeklyOverlayBoardHash = board.hash") && load.includes("await loadGrading()") && load.includes("S.verificationScope"), "bounded board binding preserves scope and grading path");
(async () => {
  const originalHelper = context.WeeklyAdaptiveOverlay, pending = new Map(), calls = [];
  context.WeeklyAdaptiveOverlay = { load: (b, hash) => { calls.push({ b, hash }); return new Promise((resolve, reject) => pending.set(b, { resolve, reject })); } };
  state.weeklyOverlay = null; state.weeklyOverlayRequestBoard = null;
  a.startWeeklyOverlay(); await Promise.resolve(); await Promise.resolve();
  equal(calls.length, 1, "one optional request for a board"); equal(calls[0].hash, state.weeklyOverlayBoardHash, "loader receives actual bounded board hash");
  a.startWeeklyOverlay(); await Promise.resolve(); equal(calls.length, 1, "no immediate duplicate fetch");
  const nextBoard = { ...board, week: 8 }; state.data = nextBoard; state.weeklyOverlayBoardHash = "f".repeat(64);
  a.startWeeklyOverlay(); await Promise.resolve(); await Promise.resolve();
  pending.get(nextBoard).resolve({ id: "NEW" }); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  equal(state.weeklyOverlay.id, "NEW", "new board owns selected result");
  pending.get(board).resolve({ id: "OLD" }); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  equal(state.weeklyOverlay.id, "NEW", "delayed older board cannot overwrite newer selection");
  equal(renders, 1, "obsolete result causes no render");
  state.data = board; state.weeklyOverlay = null; state.weeklyOverlayRequestBoard = null;
  a.startWeeklyOverlay(); await Promise.resolve(); await Promise.resolve(); pending.get(board).reject(Error("OPTIONAL_UNAVAILABLE"));
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  equal(state.weeklyOverlay, null, "missing optional feed retains reference");
  context.WeeklyAdaptiveOverlay = originalHelper;
  equal(JSON.stringify(board), original, "late responses never mutate reference board");
  console.log(`Weekly display integration: ${checks} actual-helper typed/unknown/caption/isolation/race checks passed (fictional Node VM; no browser/provider).`);
})().catch(error => { console.error(error); process.exitCode = 1; });
