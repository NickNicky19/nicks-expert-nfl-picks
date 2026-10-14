// Render the actual About function with pending, resolved, and unavailable data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../output/app.js'), 'utf8');
const about = source.match(/function renderAbout\(\) \{[\s\S]*?\n\}/)?.[0];
assert.ok(about, 'actual About renderer found');
const data = JSON.parse(fs.readFileSync(path.join(__dirname, '../output/data/week.json'), 'utf8'));
function render(report) {
  const main = { innerHTML: '' };
  vm.runInNewContext(about + '\nrenderAbout();', {
    S: { data, forecastScorecard: report },
    $: () => main,
    fmt: (value, digits) => Number(value).toFixed(digits),
  });
  return main.innerHTML;
}
const pending = { coverage: { unique_opportunities: 42, repeated_capture_rows: 84 },
  outcome_status: { pending: 42 }, categories: Object.fromEntries(['rec', 'rush_att', 'pass_yd'].map(key => [key,
    { raw_sleeper: { n: 0, mae: null }, unchanged_clone: { n: 0, mae: null } }])) };
const pendingHtml = render(pending);
assert.match(pendingHtml, /42 unique matched opportunities; 84 repeated captures excluded/);
assert.match(pendingHtml, /42 pending, 0 unresolved, 0 confirmed DNP/);
assert.equal((pendingHtml.match(/<td>Pending<\/td>/g) || []).length, 6);
assert.match(pendingHtml, /Production picks use the retained baseline/);
assert.match(pendingHtml, /does not select production picks/);
assert.match(pendingHtml, /Full entry payout and entry-specific settlement remain unverified/);
const resolved = structuredClone(pending);
resolved.categories.rec = { raw_sleeper: { n: 2, mae: 1.25 }, unchanged_clone: { n: 2, mae: 1.5 } };
assert.match(render(resolved), /<td>Receptions<\/td><td>2<\/td><td>1.25<\/td><td>1.50<\/td>/);
assert.match(render(null), /No comparison report is available/);
console.log('9 About rendering assertions passed.');
