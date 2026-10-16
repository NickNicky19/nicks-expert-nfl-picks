# Prospective full-week population capture

This implements the manual adapter for **NICK-WEB-AUDIT-20261015/AUD-01**.
It does not change the registered evaluation/timing policies, original model,
forecast receipts, outcome scoring, production workflow or website. The gate
uses `NICK-WEB-AUDIT-20261015:AUD-01` for the same finding because its existing
identifier grammar excludes `/`; the gate is unchanged.

The version is `week-population-espn-nfl-v1`. Only the checked **2026 regular
season** club/source contract is supported. Another season or incompatible
source structure needs a reviewed adapter version, not an automatic fallback.

## Manual operation in an isolated root

After authorization, run from the exact reviewed checkout:

```sh
python tools/week_population.py --root /absolute/isolated-validation-root --season 2026 --week 7
```

The root is mandatory. The repository and its descendants are refused. This
checkpoint does not install a production collector, schedule, dispatcher, or
automatic capture. It does not publish the root's data into the repository.
Evidence adoption/publication and production wiring require their own approval.
Keep recurring ChatGPT audits paused. The existing production updater is separate.

The live CLI accepts **no supplied clock**, replay date or historical backfill.
Every request/response and the final local seal use the actual UTC clock. Both
source observations and validation must finish strictly before the first saved
kickoff. The client collection interval is capped at 120 seconds to reject stale
or transplanted client observations; this operational bound is not a provider
quote-freshness guarantee or a change to an experiment threshold.

A Week 7 demonstration must fetch fresh data after approval, while that entire
week remains future. If it is late or sources disagree, stop. Do not substitute
another week or attach newly fetched data to the old Week 6 forecast.

## Independently checked membership

1. Fetch the complete ESPN scoreboard response with explicit `dates=2026`,
   `seasontype=2`, `week=W`, `limit=1000`. Check the returned period, duplicate
   IDs, two unambiguous home/away clubs, pregame status, kickoffs and bye list.
2. Independently fetch `https://www.nfl.com/schedules/2026/by-week/week-W`.
   Decode only the known server-rendered Next Flight JSON; never execute page
   JavaScript. Require one successful `useFetchFootballWeeklyGameDetails` query
   explicitly bound to the requested season, REG and week, plus the matching
   official week-selector metadata, date boundaries and bye list.
3. Validate the official club IDs/full identities against the fixed 2026
   32-club map. All playing clubs plus bye clubs must partition that exact set
   once, independently in both documents. This rejects even matching jointly
   truncated game lists. The map's source URL, original observation time and
   HTTP-decoded body hash are recorded in the adapter source; the complete map
   and its canonical digest are pinned in every new document.
4. Match the complete sets by exact away/home identity **and parsed UTC kickoff**.
   Retain both provider game IDs. No fuzzy name matching, player-subset coverage,
   assumed game count, guessed IDs, date-window substitution or one-source
   completeness assertion can qualify a receipt.

Redirects are refused, including HTTP 200 documents with an unexpected final
URL. During investigation the old `/schedules/2026/reg7/` path redirected to a
generic Week 6 page; it is not Week 7 proof. The tested Sleeper
`/v1/schedule/nfl/2026/7` endpoint returned 404 and is not a supported source.
Empty documents, failed queries and unknown schemas fail closed.

The two public sources remain fallible. Exact matching and club/bye coverage do
not cryptographically authenticate a provider or independently verify that its
future schedule cannot change. No API key, private identity or paid feed is used.

## Create-only evidence and precise hashes

Success uses the existing `week-game-population-v1` envelope in:

```text
ROOT/data/week_populations/2026/wWW/PAYLOAD_SHA256.json.gz
```

It retains both **full source bodies**, exact requests/final URLs, HTTP results,
actual request/collection/seal clocks, the official week/club partition,
provider IDs and their crosswalk, canonical kickoffs, adapter version and exact
source-code digest. The source document and entire payload are content addressed.
The existing reader can embed the receipt without any scoring/policy changes.

`sha256-http-decoded-utf8-body-v1` hashes the UTF-8 bytes of `requests`' HTTP-decoded
body. These are **not raw wire/compressed transport bytes**. ESPN additionally
has `sha256-canonical-decoded-json-v1`. Duplicate JSON keys and nonfinite JSON
are rejected. A decode failure retains the body bytes as base64 in diagnostics.
HTTP Date is retained as an HTTP header, not interpreted as provider as-of time.
Provider `source_timestamp` remains null / `NOT_ESTABLISHED`; capture time does
not establish upstream freshness, prediction publication or provider authenticity.

`validate_receipt(payload)` re-derives the full document from its own saved
bodies, without consulting today's sources, and checks code version/hash, raw
body/document hashes, request/period/clock bindings and all membership rules.
Existing receipts are checked before another capture. A malformed, corrupted,
incompatible or conflicting prior receipt blocks new qualification and is
retained. This version does not silently adopt legacy or another adapter's
population proof.

Retries never overwrite source evidence. Identical payload bytes reuse the same
content address; genuinely new observations retain new clocks and receipts.
Repeated membership captures are not extra games, weeks or forecast outcomes.

Failures are content addressed separately in
`ROOT/data/week_population_diagnostics/2026/wWW/`. A diagnostic is explicitly
`BLOCKED_NOT_A_POPULATION_RECEIPT`, with the reason and all available original
source observations. HTTP failure, request failure, UTF-8/JSON/schema failure,
empty source, stale clocks and membership conflict remain inspectable.
`available` on a source observation means HTTP 200 transport, not valid or
complete membership; the diagnostic reason preserves parsing/empty-data failure.
An outage is never a model choosing NO_ACTION or evidence of an empty NFL week.

## Frozen schedules and original completion rules

Once saved, membership, both provider IDs, teams and kickoffs are frozen. A later
changed schedule or mapping creates a retained conflict diagnostic; no old
receipt is rewritten and no favorable version is selected. A postponed,
cancelled, started or unknown-status source cannot establish a fresh pregame
population. Such games remain in the original frozen universe.

The existing outcome reader still requires the entire nonempty frozen game
population and independently sourced, matching final/completed status for every
game. Nonfinal/cancelled games, changed kickoffs, missing coverage or contradictory
populations keep the week incomplete. No cancellation exception, dropped game or
retrospective rescheduling is introduced. A different inferential treatment
requires separate prospective policy review.

A qualified pregame population is **not a completed outcome week**. Valid resolved
point outcomes remain reportable while completed-week uncertainty is unavailable.
All original minimum-week/cluster/confirmation rules remain unchanged. There is
no eight-week freeze on descriptive reporting or separate candidate development.

The old committed Week 6 `tools/verify.py --offline` missing-proof failure remains
visible and unchanged. A successful separate A07 artifact or new population
receipt does not authenticate that old forecast. No original projection,
selection clock, line, decision or historical proof is reconstructed here.

## Verification and handoff

```sh
python -m unittest discover -s tests -p test_week_population.py -v
python -m unittest discover -s tests -v
python -m compileall -q pull tools
python tools/verify.py --offline
node --check output/app.js
node --check output/reliability-ui.js
node tests/test-ui.cjs
node tests/test-about.cjs
git diff --check
```

The original static verifier is an expected exit 1 until an independently
qualified exact new release artifact is prepared; do not suppress it. Tests
use explicitly fictional source documents, mocked HTTP/clocks and disposable
roots. They do not create live evidence or establish predictive performance.
The actual fresh Week 7 demonstration, exact source/coordination commits, CI,
checksums, limitations and scratch code-only rollback rehearsal belong in the
append-only `CODEX_RESULT` on PR #1. Retain failed diagnostics and all prior
evidence. Complete only the owned lease, then await independent actual-commit
review. No timing ledger, browser/kicker repair, new model, merge, deployment or
production promotion is included in this checkpoint.
