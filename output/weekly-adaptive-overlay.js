"use strict";
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.WeeklyAdaptiveOverlay = api;
  if (typeof root.dispatchEvent === "function" && typeof root.Event === "function") root.dispatchEvent(new root.Event("weekly-adaptive-overlay-ready"));
})(globalThis, function () {
  const VERSION = "weekly-adaptive-public-overlay-v1", POINTER = "weekly-adaptive-overlay-pointer-v1";
  const HASH = /^[a-f0-9]{64}$/, LIMIT = 4 * 1024 * 1024, DEADLINE_MS = 4000;
  const counts = new Set(["pass_td", "pass_cmp", "pass_att", "pass_int", "rush_att", "rec"]);
  const yards = new Set(["pass_yd", "rush_yd", "rec_yd", "rush_rec_yd"]);
  const rowFields = ["player_id","game_id","category","method_id","model_version","procedure_version","product","prediction_functional","forecast_value","horizon","source_cutoff_utc","issued_at","persistence_completed_at","kickoff_utc","valid_until_utc","selection_sha256","source_policy_sha256","query_source_sha256","first_prepared_at"].sort();
  const fields = ["schema_version","registration_id","state","season","week","canonical_board_sha256","display_board_sha256","board_contract_sha256","prepared_at","packaged_at","website_source_sha","publication_review_sha256","rows","frozen_rows","fallback_counts"].sort();
  const identity = r => JSON.stringify([r.game_id, r.player_id, r.category]);
  const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  function clock(v) {
    if (typeof v !== "string" || !/^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(v) || !Number.isFinite(Date.parse(v))) throw Error("Invalid overlay clock");
    return Date.parse(v);
  }
  function validate(doc, board, boardHash) {
    if (!doc || JSON.stringify(Object.keys(doc).sort()) !== JSON.stringify(fields) || doc.schema_version !== VERSION
        || doc.registration_id !== "weekly-adaptive-release-v1" || !["PROVISIONAL","DISABLED_USE_R0"].includes(doc.state)
        || doc.season !== board.season || doc.week !== board.week || doc.display_board_sha256 !== boardHash
        || ![doc.canonical_board_sha256,doc.display_board_sha256,doc.board_contract_sha256,doc.publication_review_sha256].every(v => HASH.test(v))
        || !/^[a-f0-9]{40}$/.test(doc.website_source_sha) || !Array.isArray(doc.rows) || doc.rows.length > 5000
        || doc.state === "DISABLED_USE_R0" && doc.rows.length || clock(doc.packaged_at) < clock(doc.prepared_at)) throw Error("Overlay unavailable");
    const games = new Map(board.games.map(g => [g.id,g])), offers = new Map(), rows = new Map();
    if(games.size!==board.games.length)throw Error("Duplicate R0 game");
    for (const p of board.players) for (const prop of p.props || []) {const k=identity({game_id:p.game_id,player_id:p.id,category:prop.key});if(offers.has(k))throw Error("Duplicate R0 offer");offers.set(k,{p,g:games.get(p.game_id)});}
    for (const row of doc.rows) {
      const k = identity(row), match = offers.get(k);
      const product = counts.has(row.category) ? ["point_mean","expected_mean"] : yards.has(row.category) ? ["point_median","intended_median"] : row.category === "anytime_td" ? ["binary_probability","event_probability"] : null;
      if (JSON.stringify(Object.keys(row).sort()) !== JSON.stringify(rowFields) || !match?.g || !product || rows.has(k)
          || row.product !== product[0] || row.prediction_functional !== product[1] || row.horizon !== "player_game"
          || typeof row.forecast_value !== "number" || !Number.isFinite(row.forecast_value)
          || counts.has(row.category) && row.forecast_value < 0 || row.category === "anytime_td" && (row.forecast_value < 0 || row.forecast_value > 1)
          || ![row.model_version,row.procedure_version,row.selection_sha256,row.source_policy_sha256,row.query_source_sha256].every(v => HASH.test(v))
          || typeof row.method_id !== "string" || !row.method_id || row.method_id.length > 100
          || clock(row.kickoff_utc) !== clock(match.g.kickoff)) throw Error("Incompatible overlay row");
      const issued=clock(row.issued_at), persisted=clock(row.persistence_completed_at), cutoff=clock(row.source_cutoff_utc), kickoff=clock(row.kickoff_utc), prepared=clock(row.first_prepared_at), expires=clock(row.valid_until_utc);
      if (!(issued <= persisted && persisted <= cutoff && cutoff < kickoff && persisted <= prepared && prepared < kickoff && prepared < expires && expires <= kickoff)) throw Error("Late overlay row");
      rows.set(k, Object.freeze({...row}));
    }
    const reasons=new Set(["malformed_candidate","candidate_outside_board_R0","invalid_previous_overlay_R0","started_R0_frozen_no_new_selection","PPR_or_unsupported_R0","publication_not_approved_R0","missing_or_duplicate_candidate_R0","incompatible_stale_or_late_R0"]);
    if(!Array.isArray(doc.frozen_rows)||doc.frozen_rows.some(v=>!v||JSON.stringify(Object.keys(v).sort())!==JSON.stringify(["key","row_sha256"])||!Array.isArray(v.key)||v.key.length!==3||!rows.has(JSON.stringify(v.key))||!HASH.test(v.row_sha256))
        ||!doc.fallback_counts||typeof doc.fallback_counts!=="object"||Array.isArray(doc.fallback_counts)||Object.entries(doc.fallback_counts).some(([k,v])=>!reasons.has(k)||!Number.isInteger(v)||v<0))throw Error("Unapproved public overlay metadata");
    return Object.freeze({rows,season:doc.season,week:doc.week,boardHash,state:doc.state});
  }
  function cancel(reader) { try { Promise.resolve(reader.cancel()).catch(() => {}); } catch (_) { /* Cancellation must never delay R0. */ } }
  async function deadline(work, milliseconds) {
    if (!Number.isInteger(milliseconds) || milliseconds < 1 || milliseconds > DEADLINE_MS) throw Error("Invalid overlay deadline");
    const controller = new AbortController(), readers = new Set(); let timer;
    const context = {signal:controller.signal, readers};
    try {
      return await Promise.race([Promise.resolve().then(() => work(context)), new Promise((_, reject) => {
        timer=setTimeout(() => { controller.abort(); for (const reader of readers) cancel(reader); reject(Error("Overlay deadline exceeded")); }, milliseconds);
      })]);
    } finally {
      clearTimeout(timer); controller.abort(); for (const reader of readers) cancel(reader);
    }
  }
  async function readAsset(url, cap, fetcher, context) {
    const response = await fetcher(url, {cache:"no-store", signal:context.signal});
    if (context.signal.aborted) { if(response.body)cancel(response.body); throw Error("Overlay deadline exceeded"); }
    if (!response.ok || !response.body?.getReader || Number(response.headers?.get("content-length")) > cap) { if(response.body)cancel(response.body); throw Error("Missing bounded overlay asset"); }
    const reader=response.body.getReader(), chunks=[]; let bytes=0;
    context.readers.add(reader);
    try {
      for (;;) { const part=await reader.read(); if(context.signal.aborted)throw Error("Overlay deadline exceeded"); if(part.done)break; bytes+=part.value.byteLength; if(bytes>cap)throw Error("Overlay bound exceeded"); chunks.push(part.value); }
    } finally { context.readers.delete(reader); cancel(reader); try { reader.releaseLock(); } catch (_) { /* Pending abandoned read. */ } }
    const body=new Uint8Array(bytes);let offset=0;for(const c of chunks){body.set(c,offset);offset+=c.byteLength;}
    const hash=[...new Uint8Array(await crypto.subtle.digest("SHA-256",body))].map(v=>v.toString(16).padStart(2,"0")).join("");
    if(context.signal.aborted)throw Error("Overlay deadline exceeded");
    return {value:JSON.parse(new TextDecoder().decode(body)),hash,bytes};
  }
  async function bound(url, cap, fetcher=fetch, milliseconds=DEADLINE_MS) {
    return deadline(context => readAsset(url, cap, fetcher, context), milliseconds);
  }
  async function load(board, boardHash, fetcher=fetch, milliseconds=DEADLINE_MS) {
    try {
      return await deadline(async context => {
      const pointer=(await readAsset("data/weekly-adaptive-overlay.json",4096,fetcher,context)).value;
      const keys=["schema_version","path","sha256","bytes","display_board_sha256"].sort();
      if(JSON.stringify(Object.keys(pointer).sort())!==JSON.stringify(keys)||pointer.schema_version!==POINTER||!HASH.test(pointer.sha256)
          ||pointer.path!==`data/weekly-adaptive/${pointer.sha256}.json`||!Number.isInteger(pointer.bytes)||pointer.bytes<1||pointer.bytes>LIMIT)return null;
      if (!boardHash) { // Legacy reader only: never change its original board.
        const same=await readAsset("data/week.json",16*1024*1024,fetcher,context);
        if(JSON.stringify(same.value)!==JSON.stringify(board))return null;
        boardHash=same.hash;
      }
      if(pointer.display_board_sha256!==boardHash)return null;
      const saved=await readAsset(pointer.path,LIMIT,fetcher,context);
      if(saved.hash!==pointer.sha256||saved.bytes!==pointer.bytes)return null;
      return validate(saved.value,board,boardHash);
      }, milliseconds);
    } catch (_) { return null; } // R0 board and normal consumer remain untouched.
  }
  function card(overlay, player, category, now=Date.now()) {
    const row=overlay?.rows.get(identity({game_id:player.game_id,player_id:player.id,category}));
    if(!row)return "";
    const kickoff=clock(row.kickoff_utc), expiry=clock(row.valid_until_utc);
    if(now<kickoff&&now>=expiry || now>=kickoff&&expiry<kickoff)return "";
    const binary=row.product==="binary_probability", value=binary?`${(100*row.forecast_value).toFixed(1)}%`:row.forecast_value.toFixed(2);
    const label=binary?"Rushing or receiving TD probability":row.product==="point_mean"?"Mean forecast":"Median forecast";
    return `<div class="card note" data-weekly-provisional><b>${now>=kickoff?"Frozen provisional forecast":"Provisional selected forecast"}: ${esc(value)}</b> · ${esc(label)}<div>Assumes the player participates. Accuracy is still being evaluated. Reference forecast and recorded lines are shown separately.${binary?"":" Point forecasts do not give a bet-win probability."}</div></div>`;
  }
  return Object.freeze({validate,load,card,bound,DEADLINE_MS});
});
