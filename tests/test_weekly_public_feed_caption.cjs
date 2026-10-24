"use strict";
// Standalone fictional runtime check; requires a separately bounded Node runner.
// Do not run under a 512 MiB virtual-address ceiling: this Node reserves more
// address space before executing JavaScript. Keep physical RSS bounded separately.
const assert = require("node:assert/strict"), path = require("node:path");
const api = require(path.resolve(process.argv[2] || "output/weekly-adaptive-overlay.js"));
const now = Date.parse("2026-10-24T10:00:00Z"), player = {id:"p",game_id:"g"};
for (const [product,label,value] of [["point_mean","Mean forecast",0],
  ["point_median","Median forecast",-2.5],
  ["binary_probability","Rushing or receiving TD probability",.35]]) {
  const row = {player_id:"p",game_id:"g",category:"rush_att",method_id:"DO_NOT_SHOW_INTERNAL_ID",
    product,forecast_value:value,kickoff_utc:"2026-10-25T17:00:00Z",valid_until_utc:"2026-10-25T17:00:00Z"};
  const html = api.card({rows:new Map([[JSON.stringify(["g","p","rush_att"]),row]])},player,"rush_att",now);
  assert(html.includes(label)); assert(html.includes("Provisional selected forecast"));
  assert(html.includes("Assumes the player participates. Accuracy is still being evaluated."));
  assert(html.includes("Reference forecast")); assert(!html.includes("DO_NOT_SHOW_INTERNAL_ID"));
  assert(!html.includes("R0"));
  if(product==="binary_probability") assert(html.includes("35.0%"));
}
console.log(JSON.stringify({state:"PASS",cases:3,scope:"fictional caption only; no HTTP/data"}));
