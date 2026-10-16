# Separate selection and timing extension, version 1

**Status: local offline ledger and descriptive report implemented; not
integrated or deployed.** tools/selection_report.py consumes saved observations
and retained statistics. It does not collect data, schedule work, change
forecasts, publish website files or implement timing inference/confirmation.
The registry's original REGISTERED_NOT_IMPLEMENTED field is retained unchanged
as registration metadata; implementation status is documented here.

Registry: `config/timing-policy.json`, phase2-timing-v1. This extends reporting;
it does not change the raw Sleeper versus clone experiment, its earliest paired
capture, categories, metrics, promotion criteria or immutable registry.
Production selection rules and the shadow model are unchanged.

The fixed checkpoints are 24 hours, 6 hours and 90 minutes before the **saved**
kickoff. At each boundary use the latest snapshot already recorded at or before
that boundary, at most 60 minutes old. This supports the existing hourly runner;
it does not promise an exact fresh quote at the boundary. Capture age and source
timestamp availability are reported. Never substitute a later forecast, price,
line, eligibility state or direction. A missing snapshot produces NO_ACTION;
an unknown opportunity universe is reported as unknown. A checkpoint preceding
registration is excluded, even if its game has not started. Changed schedules
are flagged; saved decisions are not moved or rewritten.

Preserve the recorded selection time and kickoff in UTC, derive their two
weekdays separately with America/Chicago (including daylight saving), and save
seconds remaining at the selection time. The scheduled checkpoint time is an
additional field, not a replacement selection timestamp. Grading collection
time never determines a performance weekday.

Compare recorded selected overs and unders separately for Top Picks and all
qualifying leans. A Top Pick is recorded membership, not a fresh ranking. A
qualifying lean is the recorded over/under against a real DraftKings or Sleeper
line; it need not pass the stricter Top Pick role filter. Top Picks are also
leans, so these two cohorts overlap and must not be pooled. Scope includes the
ten retained pickable statistic categories, including rush + receiving yards.
"Venue" means offer venue (DraftKings or Sleeper), not an invented stadium.
Model version includes the retained engine digest. Shadow forecasts have no
recorded selections and do not acquire inferred over/under decisions.

Older receipts provide a separate descriptive history: first recorded selected
decision per player/game/category **within each cohort**, or the first NO_ACTION
if never selected. This is not a retrospectively registered checkpoint policy.
Unknown historical eligibility and prices stay unknown. Earlier NO_ACTIONs,
later changes and every source receipt remain available; duplicates do not add
outcomes. Checkpoint policies freeze all decisions, including NO_ACTION, once.

Each policy reports its observed universe, available snapshots, qualifying and
selected coverage, exclusions and unique games/weeks. Checkpoint comparisons
first audit the common universe (including NO_ACTION), then compare selections
on the same player/game/category, venue and model. Each policy retains its own
line and side; line changes and direction flips are reported. Report each
policy's total coverage alongside its matched subset. The same underlying
outcome appearing at several checkpoints is not independent evidence.

Report selected n, unique games/weeks, wins, losses, pushes, confirmed DNP,
pending/unresolved and hit rate (W / (W + L)). These are **statistical** results,
not venue settlement. No standard odds are assumed. The supported feed has no
verified full entry payout or entry-specific settlement, and DraftKings prices
are absent, so paper profit and ROI are unavailable. Sleeper leg multipliers
remain captured observations; a multi-leg ticket's payout cannot be attributed
to an individual over/under subgroup.

All category, venue, model and day/timing subgroup tables are exploratory.
Selections from one game, nested cohorts and repeated checkpoint policies are
related. Use whole NFL weeks as bootstrap clusters; require eight completed
weeks, twenty games and thirty decided selections per side for the fourteen
registered overall/checkpoint contrasts. Their intervals use Bonferroni family
correction. Subgroup tables have no significance declarations. Rates compare
selected populations and do not identify a causal weekday effect.

Observed leaders need ten decided selections and five games but are explicitly
unconfirmed. Confirmation requires a separate immutable hypothesis registered
before later games, a fixed group/comparator/side/cohort/checkpoint, and its hash
already saved in those games' observation receipts. Use only decisions and
games after both registration and discovery cutoff, at least eight completed
weeks, twenty games and 100 decided selections in each group. Correct across
all ten permitted hypothesis slots. A positive simultaneous interval is a
later-game finding for that fixed contrast, not profitability or model
promotion. With no registered hypothesis or insufficient evidence, confirmed
findings stay empty. Reports never switch production models automatically.

This policy is preserved before the extension implementation and before any
eligible checkpoint outcomes. Future parameter changes require a new version;
never edit a registry already referenced by a decision receipt.

## Local offline report: selection-report-v1

One command produces the ledger, statistical grading rows, reconciled summaries,
JSON/CSV and standalone HTML. Repeat --input-root for additional explicitly
authorized immutable inputs:

~~~sh
python tools/selection_report.py \
  --input-root /read-only/project-input \
  --input-pin /read-only/project-input=EXACT_40_CHARACTER_GIT_SHA \
  --output-root /external/local-report
~~~

An input pin is optional. A root with its own Git metadata uses its HEAD by
default; an explicit frozen pin verifies consumed blobs against that commit.
Downloaded roots without local Git objects retain an EXTERNAL_PIN_REFERENCE_ONLY
label: the report itself does not authenticate that reference. Verify their
Git tree/blob mapping separately, as in the pinned-input demonstration.
Otherwise inputs are explicitly content-addressed and unpinned.

The output must be outside the source repository and every input root.
Original receipts, archives, caches, policies and production files are never
modified. The manifest retains every consumed byte/payload hash, optional
input pin, code hash and policy identity. Unknown forecast/model/engine
contracts remain explicit exclusions. Malformed envelopes, unrelated outcome
integrity errors and duplicate/unbound archive identities fail explicitly.
No permissive format upgrade or source repair is attempted.

Open reports/<report-sha256>/index.html locally. Its summaries link to auditable
complete drill-down pages under groups/; the index previews only fifty rows.
rows.json, rows.csv, summary.json and manifest.json accompany it. Outcome
provenance is indexed once and referenced from each row, retaining correction
history without repeating full observations for every overlapping cohort.
Weekly
and cumulative views cover category, side, category-by-side, model/engine,
venue, recorded-selection weekday, kickoff weekday, lead-time bucket and
checkpoint. Tables separate wins, losses, pushes, attributed DNP, pending,
unresolved, exclusions and NO_ACTION. W/(W+L) excludes all other statuses.
Never add overlapping cohorts/checkpoints/dimensions as independent samples.
Unique players, games and weeks are distinct counts; decided games/weeks and
selected players/games are explicitly separate from the observed population.
Archive count, weeks with
decided selections and qualified completed evaluation weeks are separate.

The original primary scorecard is reused on deduplicated receipts for raw
Sleeper versus unchanged-adjusted point accuracy in its three registered
targets. MAE/RMSE/bias remain category-specific under the unchanged paired
opportunity, cutoff and uncertainty rules. Valid arithmetic is not proof of
better forecasts. No fitted candidate or mixed-unit composite is added.

### Clocks, cohorts and coverage

For baseline-v1, recorded_selection_at=captured_at means membership was locally
observed then. The basis is LOCAL_PREGAME_MEMBERSHIP_OBSERVATION; an unrecorded
original_selection_created_at remains null. Generation, collection, saved
kickoff, checkpoint boundary, actual lead time and observation age are separate.
Chicago weekdays use the two original recorded clocks separately. Archive
saved_at, grading time and Git time never substitute for a decision clock.

First selections are chosen independently per cohort. A first lean and later
first Top can have different lines/directions. The explicitly disjoint views
top_at_all_lean_decision and non_top_at_all_lean_decision partition SELECT
rows in the all-lean view. They are not the separate first-Top cohort.

Checkpoint records are OFFLINE_DERIVED_FROM_ORIGINAL_PREGAME_OBSERVATIONS:
application of the registered rule, not proof the website executed that policy
historically. The latest whole snapshot is chosen before inspecting each
opportunity; missing rows cannot fall back. Future checkpoints are NOT_DUE,
with no frozen decision or invented NO_ACTION. Due checkpoint SELECT/NO_ACTION
records freeze once; contradictory later inputs are conflicts, preserving the
original record. Descriptive history is versioned separately so a first real
selection can follow earlier NO_ACTION. Equal-time conflicts and ambiguous
original kickoffs do not choose a digest-order winner. Schedule conflicts stay
visible without moving historical boundaries.

Inherited/unclocked archives stay in a separate provenance/model lane with
null decision clocks and unverified engine identity. Agreeing archive versions
are deduplicated; disagreeing versions are excluded, not extra samples.
Duplicate archive IDs/contracts and unbound Top/game relationships stop with
an explicit integrity error rather than silently selecting a version.

Observed No Lean on a real saved line differs from a missing/stale snapshot,
missing row, reference record or unknown source coverage. Standalone offer
observations retain available/unavailable/unknown status and coverage, but
no unrecorded observation/contract join is inferred. Existing offer receipts
cover only three categories. Legacy absence cannot establish successful-empty
response, complete opportunity coverage or intentional abstention. Entirely
unobserved universes remain unknown.

### Outcomes and reproducibility

Shared source extraction covers all ten pickable categories. Combined yards
is rush_yd + rec_yd, never aggregate plus components. Confirmed participation
permits omitted sparse zero; explicit null remains unresolved. All present
components are finite integers, counts nonnegative; yardage may be negative.
Missing, empty or fantasy-only statistics do not prove participation/DNP.
Equality is a statistical push on either side. Participation contradictions
and conflicting confirmed source versions remain unresolved.

Saved outcomes use latest_outcomes and retain IR-01 validation. A saved value
inconsistent with its components fails; no old value is silently rewritten.
External statistical regrades can use the exact saved board/cache with their
actual new derivation clock, in data/outcomes_derived. Their distinct origin
binds input pin/cache/board identity. A later derivation cannot make an older
cache supersede a saved correction; unsupported ordering stays unresolved.
Identical material reuses the first derived receipt; operational report
clocks are separate run receipts.

The offline report does not open separate population-capture files. New
derived outcomes explicitly have no full-week population qualification;
valid individual points remain reportable. Previously saved, authorized
embedded population evidence still undergoes the retained source validator.
Independent original-capture review remains pending, and the restricted ZIP
is neither needed nor accessed. The original Week 6 missing matchup-input/
proof failure stays visible; no replacement proof is refetched or fabricated.

### Limits and later integration

Timing inference/confirmation stays unavailable even if future sample counts
eventually meet minimums, until the registered evaluator is separately
implemented. The primary scorecard's eight-week behavior is unchanged.
No independent-prop intervals, subgroup significance, confirmed leaders,
odds, EV or ROI are invented. Void labels do not establish venue settlement.

This local HTML does not change existing cards/My Picks. Their DNP,
participation, push and live-progress corrections, report publication and
ongoing source/contract capture need a separately approved integration through
the existing updater. No scheduler is created. A missed original checkpoint
or offer observation cannot be recovered after its boundary.
