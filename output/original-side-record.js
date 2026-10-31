/* Additive original-recorded-history renderer. No forecasting or selection. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.NflOriginalSideRecord = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const VERSION = "original-side-record-renderer-v1.1";
  const SCHEMA = "original-recorded-leans-report-v1";
  const VIEWS = ["cumulative", "weekly", "by_version"];
  const COUNTS = ["hit", "miss", "decided", "push", "void", "dnp", "pending", "unresolved", "excluded"];
  const UNKNOWN_MODEL = "__UNKNOWN_MODEL__";
  const COHORT_LABELS = { ALL_RECORDED_LEANS: "All original recorded leans", ORIGINAL_TOP_PICKS: "Original highlighted Top Picks" };
  function escape(value) {
    return String(value == null ? "Unknown" : value).replace(/[&<>"']/g, function (x) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[x];
    });
  }
  function count(x) { return Number.isSafeInteger(x) && x >= 0; }
  function text(x) { return x == null ? "Unknown / not retained" : String(x); }
  function require(condition, reason) { if (!condition) throw new Error("Original record: " + reason); }
  function validateSide(side) {
    require(side && typeof side === "object", "missing side");
    COUNTS.forEach(function (k) { require(count(side[k]), "invalid " + k + " count"); });
    require(side.decided === side.hit + side.miss, "decided denominator");
    require(side.decided === 0 ? side.hit_rate === null : typeof side.hit_rate === "number" && Number.isFinite(side.hit_rate) && Math.abs(side.hit_rate - side.hit / side.decided) <= 1e-12, "hit rate must equal hits / (hits + misses)");
  }
  function validate(report) {
    require(report && (report.schema_version || report.version) === SCHEMA, "unsupported report version");
    require(report.source && typeof report.source === "object", "missing source metadata");
    require(report.tables && typeof report.tables === "object", "missing tables");
    require(Array.isArray(report.limitations) && report.limitations.every(function (x) { return typeof x === "string"; }), "missing limitations");
    VIEWS.forEach(function (view) {
      require(Array.isArray(report.tables[view]), "missing " + view + " table");
      report.tables[view].forEach(function (row) {
        require(typeof row.category === "string" && row.category.length > 0, "missing category");
        require(Object.prototype.hasOwnProperty.call(COHORT_LABELS, row.cohort), "unsupported cohort");
        require(count(row.season) && row.season >= 2000, "invalid season");
        require(row.week === null || count(row.week) && row.week > 0, "invalid week");
        require(count(row.unique_games), "invalid unique-game count");
        ["weeks", "partial_weeks"].forEach(function (k) { require(Array.isArray(row[k]) && row[k].every(function (x) { return count(x) && x > 0; }), "invalid " + k); });
        require(row.partial_weeks.every(function (x) { return row.weeks.includes(x); }), "partial week outside coverage");
        ["model_version", "selection_policy_version"].forEach(function (k) { require(row[k] === null || typeof row[k] === "string", "invalid " + k); });
        ["provenance", "evidence_tier"].forEach(function (k) { require(typeof row[k] === "string" && row[k].length > 0, "missing " + k); });
        validateSide(row.over); validateSide(row.under);
      });
    });
    return report;
  }
  function allRows(report) { return VIEWS.flatMap(function (view) { return report.tables[view]; }); }
  function options(report) {
    validate(report);
    const rows = allRows(report);
    return {
      categories: Array.from(new Set(rows.map(function (r) { return r.category; }))).sort(),
      models: Array.from(new Set(rows.map(function (r) { return r.model_version == null ? UNKNOWN_MODEL : r.model_version; }))).sort(),
      weeks: Array.from(new Set(rows.flatMap(function (r) { return r.weeks; }))).sort(function (a, b) { return a - b; }),
    };
  }
  function filteredRows(report, settings) {
    validate(report);
    const state = Object.assign({ view: "cumulative", category: "all", cohort: "all", side: "both", model: "all", week: "all" }, settings || {});
    require(VIEWS.includes(state.view), "unsupported view");
    require(["both", "over", "under", "combined"].includes(state.side), "unsupported side");
    return report.tables[state.view].filter(function (r) {
      return (state.category === "all" || r.category === state.category)
        && (state.cohort === "all" || r.cohort === state.cohort)
        && (state.model === "all" || (r.model_version == null ? UNKNOWN_MODEL : r.model_version) === state.model)
        && (state.week === "all" || r.week === Number(state.week));
    });
  }
  function combined(row) {
    const value = Object.fromEntries(COUNTS.map(k => [k, row.over[k] + row.under[k]]));
    COUNTS.forEach(k => require(count(value[k]), "combined count overflow"));
    value.hit_rate = value.decided ? value.hit / value.decided : null;
    return value;
  }
  async function load() {
    const reader = globalThis.WeeklyAdaptiveOverlay;
    require(typeof reader?.bound === "function", "bounded reader unavailable");
    const saved = await reader.bound("data/original_recorded_leans_report.json", 524288);
    require(saved.hash === "b3707ebca913bbe467be73bd3f532bf7700345a09d0c47e4cd7e41649a9b6819" && saved.bytes === 175460, "report identity mismatch");
    return validate(saved.value);
  }
  function rate(side) { return side.decided ? (100 * side.hit / side.decided).toFixed(1) + "%" : "—"; }
  function emptyReason(report) {
    return "No supported original records match these filters. Missing records are not zero-error or zero-loss results.";
  }
  function render(report, settings) {
    const rows = filteredRows(report, settings);
    const state = Object.assign({ side: "both", view: "cumulative" }, settings || {});
    const sides = state.side === "both" ? ["over", "under", "combined"] : [state.side];
    const body = rows.flatMap(function (row) {
      return sides.map(function (side) {
        const v = side === "combined" ? combined(row) : row[side];
        return '<tr><td class="l">' + escape(row.category) + (row.unsupported_reason ? '<br><b>Unavailable: ' + escape(row.unsupported_reason) + '</b>' : '') + '</td><td class="l">' + escape(COHORT_LABELS[row.cohort]) + '</td><td>' + escape(side === "combined" ? "Combined" : side === "over" ? "Over" : "Under") + '</td><td>' + v.hit + '</td><td>' + v.miss + '</td><td>' + rate(v) + '</td><td>' + v.decided + '</td><td>' + v.push + '</td><td>' + v.void + '</td><td>' + v.dnp + '</td><td>' + v.pending + '</td><td>' + v.unresolved + '</td><td>' + v.excluded + '</td><td class="l">' + escape(row.season + " · " + (row.week == null ? "weeks " + row.weeks.join(", ") : "Week " + row.week)) + (row.partial_weeks.length ? '<br><b>Partial: ' + escape(row.partial_weeks.join(", ")) + '</b>' : "") + '</td><td>' + row.unique_games + '</td><td class="l">' + escape(text(row.model_version)) + '<br>' + escape(text(row.selection_policy_version)) + '<br>' + escape(row.provenance) + '<br>' + escape(row.evidence_tier) + '</td></tr>';
      });
    }).join("");
    return '<section aria-label="Original recorded lean history"><h2>Original recorded leans by category and side</h2><p class="note">Decided hit rate = hits / (hits + misses). This is historical statistical direction, not an individual player’s estimated win probability or a sportsbook-settled profit record. Pushes, voids, DNPs, pending, unresolved and excluded-late records stay separate. Game coverage includes both sides and all statuses; it is not a side-specific decided sample. This is the fixed October 30 archive snapshot; newer outcomes are not silently added. All leans and highlighted Top Picks are separate populations.</p>'
      + (body ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th class="l">Category</th><th class="l">Original population</th><th>Side</th><th>Hits</th><th>Misses</th><th>Decided rate</th><th>Decided sample</th><th>Push</th><th>Void</th><th>DNP</th><th>Pending</th><th>Unresolved</th><th>Excluded late</th><th class="l">Coverage</th><th>All-status games (both sides)</th><th class="l">Original model / policy / provenance</th></tr></thead><tbody>' + body + '</tbody></table></div>' : '<p class="note">' + escape(emptyReason(report)) + '</p>')
      + '<p class="note">Source commit: ' + escape(text(report.source.snapshot_commit)) + ' · Grading: ' + escape(text(report.source.grading_version)) + '</p>'
      + '<details><summary>Evidence and coverage limitations</summary><ul>' + report.limitations.map(function (x) { return '<li>' + escape(x) + '</li>'; }).join("") + '</ul></details></section>';
  }
  function selector(name, label, values, selected) {
    return '<label>' + escape(label) + ' <select data-original-record="' + escape(name) + '">' + values.map(function (v) { return '<option value="' + escape(v[0]) + '"' + (String(v[0]) === String(selected) ? ' selected' : '') + '>' + escape(v[1]) + '</option>'; }).join("") + '</select></label> ';
  }
  function controls(report, state) {
    const o = options(report);
    return '<div class="gtool" aria-label="Original history filters">'
      + selector("view", "View", [["cumulative", "Cumulative"], ["weekly", "Weekly"], ["by_version", "By model / policy"]], state.view)
      + selector("category", "Category", [["all", "All categories"]].concat(o.categories.map(function (x) { return [x, x]; })), state.category)
      + selector("cohort", "Population", [["all", "Both populations"], ["ALL_RECORDED_LEANS", COHORT_LABELS.ALL_RECORDED_LEANS], ["ORIGINAL_TOP_PICKS", COHORT_LABELS.ORIGINAL_TOP_PICKS]], state.cohort)
      + selector("side", "Side", [["both", "Over / Under / combined"], ["over", "Over"], ["under", "Under"], ["combined", "Combined"]], state.side)
      + selector("model", "Model", [["all", "All recorded models"]].concat(o.models.map(function (x) { return [x, x === UNKNOWN_MODEL ? "Unknown / not retained" : x]; })), state.model)
      + (state.view === "weekly" ? selector("week", "Week", [["all", "All weeks"]].concat(o.weeks.map(function (x) { return [x, "Week " + x]; })), state.week) : "") + '</div>';
  }
  function mount(element, report) {
    require(element && typeof element.addEventListener === "function", "mount element required");
    validate(report);
    let state = { view: "cumulative", category: "all", cohort: "all", side: "both", model: "all", week: "all" };
    function paint() { element.innerHTML = controls(report, state) + render(report, state); }
    function changed(event) {
      const field = event.target && event.target.getAttribute && event.target.getAttribute("data-original-record");
      if (!Object.prototype.hasOwnProperty.call(state, field)) return;
      state[field] = event.target.value;
      if (field === "view") state.week = "all";
      paint();
    }
    element.addEventListener("change", changed); paint();
    return function () { element.removeEventListener("change", changed); };
  }
  return Object.freeze({ VERSION, SCHEMA, validate, filteredRows, options, render, mount, combined, load });
});
