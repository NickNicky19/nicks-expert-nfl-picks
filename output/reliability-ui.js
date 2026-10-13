"use strict";
// Pure helpers, also exercised under Node. No network calls or storage changes.
(function (root) {
  const MAX_AGE_MINUTES = 120;
  function buildStatus(generatedAt, nowMs = Date.now()) {
    const built = Date.parse(generatedAt);
    if (!Number.isFinite(built) || !Number.isFinite(nowMs) || built > nowMs) {
      return { state: "unknown", text: "Build freshness unknown. Do not treat these rows as current offers." };
    }
    const age = (nowMs - built) / 60000;
    const prefix = age > MAX_AGE_MINUTES ? "STALE BUILD" : "Build age";
    return { state: age > MAX_AGE_MINUTES ? "stale" : "recent", ageMinutes: age,
      text: `${prefix}: ${Math.floor(age)} minutes. Individual quote timestamps are not verified. Projection gaps are not win probabilities or expected value.` };
  }
  function tallyDetails(tally) {
    return ["push", "dnp", "unresolved"].filter((key) => Number(tally?.[key]) > 0)
      .map((key) => `${Number(tally[key])} ${key === "dnp" ? "confirmed DNP" : key}`).join(" · ");
  }
  const api = { buildStatus, tallyDetails, MAX_AGE_MINUTES };
  root.NflReliability = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
