# Prospective evaluation, version 1

The machine-readable registry is config/evaluation-policy.json. Commit its
version before developing or tuning a challenger. Future changes need a new
candidate version and a fresh forward holdout; do not rewrite an old registry,
receipt or outcome snapshot. The source timestamp of Sleeper projections is
unknown: collection time does not establish source-level as-of correctness.

The v1 registry is retained unchanged in config/policies/. Before any game
outcome, v1.1 corrects ordering of mixed second/microsecond timestamp formats
using parsed UTC instants. Distribution parameters and promotion rules are
unchanged. V1 forecasts remain saved and separately evaluable; versions are
never pooled into additional independent outcomes.

Compare raw Sleeper and the unchanged clone for receptions, rushing attempts,
and passing yards. A pair must come from the same live receipt and the same
player, game and category, with finite projections and collection and generation
times before kickoff. Use the earliest valid paired capture for each opportunity.
Repeated hourly observations are alternatives for the same outcome, not extra
independent samples. Report missing pairs, pending finals, unresolved
participation, DNP and exclusions; never silently turn missing outcomes into zero.
Only games kicking off after registration enter the prospective primary report.
Older games stay available as descriptive evidence.

Outcome selection reads immutable receipts only; it never consults a later
cache or rewrites a forecast/outcome snapshot. A resolved value needs a confirmed
past final and a finite integer statistic (passing yards may be negative; counts
may not). When a saved statistics entry is provided, participation, team and the
actual must agree with it. DNP needs explicit attributed participation; a recorded
void stays a distinct unscored exclusion, without inferring venue settlement.
Incomplete later observations cannot erase a previously confirmed result.

Each player/game/category retains distinct receipt and row digests, declared
source/cache identity and version, collection/source timestamps and observed
status/value in outcome_observations. Repeated identical inputs do not create
additional observations or scored outcomes. Compare versions only within the
same mode, declared source and cache path. A saved cache digest (or saved entry
digest when no cache digest exists) identifies a version. If every candidate in
that origin supplies a valid source timestamp, order by that clock; otherwise
order versions by their first recorded collection time. Seeing an already-known
older cache again does not prove either a stale response or a legitimate value
reversion. Without a source clock, retain that version in the active comparison
and quarantine any resulting disagreement; an actual newer sourced timestamp
can confirm a legitimate reversion. This fallback is local observation ordering,
not proof of source freshness; unknown source timestamps stay unknown.

A later consistent, attributed source version can correct a statistic, with all
old receipts retained. Different unattributed/unversioned finals, conflicting
values within the same latest version, tied latest versions, or disagreeing
current sources are quarantined as unresolved with actual:null and an explicit
outcome_conflict flag. Content-digest ordering does not choose a numeric winner.
Agreement or a later valid source correction may reconcile a conflict; its
original observations remain visible. Quarantined values enter neither point
nor probability score denominators. Single legacy finals remain readable, but
missing provenance cannot justify replacing them with a different final value.

Confirmed resolved-versus-DNP participation is checked across all retained
terminal observations, including superseded versions from the same source. A
later cache or source timestamp cannot establish that an earlier confirmed
played record was invalid. Quarantine either chronological direction as
unresolved, retain both receipts, and exclude the opportunity from scoring.
Ordinary numeric corrections among played records still use the version rules
above. This repair provides no automatic invalidation or adjudication mechanism;
repeated assertions of either participation state do not clear the contradiction.

Week completion is separate from the selected statistic receipt. A board and
its status subset cannot certify their own full-week coverage. Require a
separately sourced, independently checked full regular-season-week population,
frozen locally before its first kickoff. Read create-only, content-addressed
receipts from data/week_populations/SEASON/wWW/*.json.gz with the existing
evidence envelope/checksum format. The payload contract is:

```json
{
  "schema_version": "week-game-population-v1",
  "mode": "live",
  "season": 2026,
  "week": 5,
  "collected_at": "EXACT_RECORDED_PREGAME_COLLECTION_TIME",
  "source_timestamp": null,
  "source": "ATTRIBUTED_FULL_WEEK_SCHEDULE_DOCUMENT_REFERENCE",
  "population_scope": "FULL_NFL_REGULAR_SEASON_WEEK",
  "source_document": {
    "season": 2026,
    "week": 5,
    "games": [{"id": "EVERY_EXPECTED_GAME_ID", "kickoff": "ITS_RECORDED_KICKOFF"}]
  },
  "source_document_sha256": "CANONICAL_SHA256_OF_SOURCE_DOCUMENT"
}
```

This is a receipt contract, not a real schedule or authorization to collect or
backfill one. Supply it only from a verified complete source population; a
truncated scoreboard, forecast-player subset, inferred count or self-declared
completion flag is insufficient. Retain the source document/reference for
independent membership review. Hashes check recorded integrity, not upstream
authenticity or completeness; source_timestamp:null stays unknown. This repair
adds no live collector or source-completeness verification adapter and creates
no real population receipts. Existing evidence without that original proof
remains incomplete/unknown for this interval; never insert a retrospective
pregame timestamp or reconstruct old forecasts from later schedule data.

Embed all read population payloads and their digests in each new outcome receipt.
They must agree on every expected game ID and parsed kickoff, have matching
mode/season/week, valid source/document provenance and pregame collection times.
The saved board must contain exactly that nonempty population, without duplicate,
missing or extra IDs. Reconcile the whole board with the saved source-status
population: exact IDs/kickoffs, post state, completed literally true and Final
detail on both records. Every kickoff must precede the recorded status collection,
which must not follow the outcome collection. Postponed, cancelled, nonfinal,
future, unmapped or conflicting games leave the week incomplete/unknown; this
repair does not invent an exception for cancelled games or choose among
conflicting population versions.

Revalidate this embedded proof when reading immutable outcomes. A legacy
week_confirmed_complete:true flag alone cannot qualify a week, and a receipt for
another season/week/game/kickoff cannot complete the row. Keep completion receipt
references separately, matching the selected team/kickoff. A qualified later
receipt can complete an earlier resolved statistic even if its stat is missing;
an outage does not revoke already qualified completion. Preserve original flags
in outcome_observations and expose their separate week_completion_verified result.
Valid resolved values still enter point metrics when full-week proof is absent;
missing stats never become zero. No evaluation policy, bootstrap threshold,
seed, replicate count or confidence level is changed.

Point metrics are MAE, RMSE and signed mean error, separately by category. Paired
error differences use the same outcomes. Report lead time and injury coverage.
Use a week-cluster bootstrap to keep correlated players and games together;
before eight completed weeks, uncertainty is unavailable. The prespecified
98.33% intervals address the three primary comparisons. Do not combine yards
and counts into a single unscaled accuracy number.

For each category's primary interval, every scored row in a season/week cluster
must have week_confirmed_complete literally true; otherwise exclude that entire
cluster from resampling. The gate still requires eight eligible completed weeks.
Sort eligible week keys before seeded resampling, draw the same number of whole
week blocks with replacement, and retain every paired row in each drawn block.
Each replicate divides summed paired absolute-error differences by the sampled
number of paired outcomes, not by an unweighted average of week means. The
registered seed, replicate count, confidence, thresholds and policy files stay
unchanged.

Report observed, resampled and excluded week/outcome counts, plus the completed-
week paired MAE delta corresponding to the interval. Overall point MAE/RMSE/bias
and paired delta still describe all resolved matched observations, including
partial weeks; their denominator can differ from the completed-week interval.
Use completed_week_mae_delta_clone_minus_raw for its matching point estimate.
Before eight eligible completed weeks, the interval remains unavailable even
when many partial weeks or observations exist. No interval supplies independent
evidence for repeated captures, and completed-week clustering does not establish
calibration, profitability or production readiness.

The first shadow challenger centers on the retained clone and adds a historical
dispersion estimate. Count targets use negative-binomial/Poisson distributions;
yards use an integer-discretized normal that permits negative yards. Dispersion
is shrunk toward fixed priors with eight prior games. Only played observations
from earlier weeks of the same season in the saved build-input snapshot enter
training. Priors are engineering assumptions, not fitted calibration claims.
Save fixed-prior distribution references centered on raw Sleeper and the clone
at the same time as the challenger. These new probability references are not
probabilities produced by the original application.

Probability evaluation reports negative log likelihood, three-way Brier score
(under/equal/over), and central 80% interval coverage, on matched saved forecasts.
Both sides of a line and repeated lines share one outcome; score one recorded
line per opportunity. This tests statistical events, not venue-specific voids,
injury insurance, contest settlement, payouts or profitability.

Promotion is manual and remains disabled. Require at least 200 resolved
player-game outcomes per target and eight completed weeks, at least 2% MAE
improvement, no more than 2% RMSE regression, simultaneous cluster intervals
below zero, better proper probability scores than the saved clone reference,
and holdout calibration, tail, coverage and integrity review. The first
challenger retains the clone's center, so it cannot demonstrate point-MAE
improvement merely by adding a distribution. Passing software tests never
promotes a model. EV/ROI claims additionally require complete entry economics
and verified venue settlement. Explicit owner approval is required before a
production-model change.
## A02-PROV-01: bound decoded-provider status evidence

The installed completion predicate and saved-outcome reader require an
`espn-status-response-v1` transcript. Its `response_sha256` has the recorder's
original meaning: SHA-256 of the **full decoded provider JSON**, serialized with
sorted keys, compact separators, UTF-8/`ensure_ascii=False`, and no non-finite
numbers. `response_hash_format` explicitly names
`sha256-canonical-decoded-json-v1`. It is not a digest of raw HTTP wire bytes or
only the normalized game map.

The saved transcript includes that full response, exact ESPN NFL scoreboard
endpoint and regular-season request period, actual collection time, live/replay
mode and normalized statuses. Verification recomputes the full-response hash,
derives the game map again, checks the provider's own season/week metadata and
rejects mismatched maps, duplicate/ambiguous events, wrong period/source/mode,
unsupported contracts and impossible collection times. The existing full-week
membership and all-final reconciliation requirements still apply. A valid
formatting-only hash, including 64 zeroes, cannot establish completion.

Legacy evidence without the saved response is retained and remains unverified
for whole-week eligibility; it is not reconstructed from a later request or
silently upgraded. A valid numerical point outcome remains readable even when
its week cannot qualify for uncertainty. Source observations and conflicting
outcomes remain append-only; the A01-R1 participation logic is unchanged.

This binding demonstrates saved integrity, not upstream authenticity or that a
self-declared full-week population covers the real NFL schedule. No real
population capture adapter or retrospective pregame proof is supplied here.
The original policy registry, eight-completed-week threshold, completed-only
resampling pool, confidence level, replicates, seed and promotion restrictions
are unchanged. Missing original evidence stays unknown/ineligible.

## A03: validate saved probability evidence before scoring

Every applicable saved shadow receipt is validated before selecting the earliest
common triple or looking at outcomes. Pending or later unselected receipts do
not bypass this check. Require the captured target population (excluding games
that started by a recorded calculation-completion time), unique opportunities,
the same team, period, kickoff, line and line source, and exactly the raw-reference,
clone-reference and challenger roles. Preserve the existing policy/version/mode,
contemporaneous-baseline and no-mixed-model-code guards.

Validate finite distribution parameters and their count/yardage support, original
point centers, the retained 0.01 count-mean floor, legal training counts and the
registered fixed-prior references. Learned challenger dispersion is checked as
a saved distribution, not retrained from evaluation outcomes. This check does
not independently authenticate its upstream training data or rederive learned
dispersion from an unavailable historical training snapshot.

Saved under/equal/over vectors must have exactly those sides, finite values in
[0,1], unit mass and agreement with the saved model at its recorded threshold.
Agreement uses absolute tolerance 1e-10 and no relative tolerance; this is a
numerical consistency tolerance, never a probability floor or loss clip. A
fractional line has exactly zero equality mass. With no line, the probability
field must explicitly be null and Brier scoring is unavailable; point-mass log
score and interval coverage may still be evaluated on valid actuals.

The saved 80% interval must have finite ordered integer endpoints equal to the
distribution's retained quantiles, with the corresponding CDF mass brackets.
Unsupported numerical cases and non-finite losses fail closed. Negative yardage,
zero-count full support, integer pushes and extreme-tail losses retain their
original definitions. The distribution, quantile and forecast-generation
functions and all registered policy parameters remain unchanged.

Validation derives expected values only for comparison. It never replaces,
relabels or rewrites saved probabilities, intervals, parameters, forecasts or
outcomes. Invalid receipts remain preserved and cannot enter scoring; a caller
must report the failure rather than silently skip it or repair historical proof.
The absence of an old calculation-completion timestamp remains a provenance
limitation; no completion time is fabricated. A03 changes the evaluator module's
file hash, so future captures must still honor the existing model-code/version
guard. No new live shadow capture, candidate re-registration, A05 research gate,
policy relaxation or model promotion is part of this correction.

## Fixed receptions point research: rec-half-adjustment-v1

This separately registered, nonproduction experiment follows
NFL-REC-HALF-RESEARCH-PROPOSAL-20261016-162556Z (canonical proposal SHA-256
ebb70e8b3ada4b64647bc476315eb6f3926d51c76b77261eb8d42de4bf6eabbb),
accepted design review NICK-REC-HALF-PROTOCOL-REVIEW-20261016-v1 and the owner's
refreshed three-file implementation authorization. It does not amend any
registered primary raw-Sleeper/clone or probability experiment above.

For finite, nonnegative reception point forecasts from the same original
baseline observation, the candidate is:

    candidate = raw + 0.5 * (unchanged_adjusted - raw)

Keep fractional forecasts. Training: none. Tuning budget: zero. The fixed half
weight is a testable engineering hypothesis, not an estimated or optimal weight;
it adds no football information. The unchanged website engine remains the
comparator and production model. No Lean and reference-only observations are
eligible for point scoring; no offered line or price is required.

Actual code/protocol freeze and local registration: **2026-10-16T19:36:46.224755Z**.
Candidate code SHA-256: `52620fb9fcf6a3fe8ac82057c5caf1a0947ae726ef4bdb64c46f8ad91179d635`.
Canonical executable protocol SHA-256: `9877a43b85f0ff35e98c2866a7b82195a1387f5757e4df370d218a40f06bf7dd`.
Official registration payload SHA-256: `0ffd81a0d2708418d1d1b072cf9ce7750f42c554f04c2456f2a5206be199e0c6`.
The complete registration below is safe research metadata, not raw source data.
Its `source_commit` is the approved preparation base, not a claim that candidate
code existed in that commit. The implementation commit and read-back CODEX_RESULT
independently bind this registration to the final source. This avoids a circular
Git-commit/self-hash reference. Reuse this official registration for a later
approved recording hook; do not regenerate its clock to shift eligibility.

```json
{
  "candidate_id": "rec-half-adjustment-v1",
  "code_frozen_at": "2026-10-16T19:36:46.224755Z",
  "engine_sha256": "e8e8823f460e074485ee91a0dc1c1cfc43877146c4498ef074d15d2b5a735d07",
  "expected_engine_files": {
    "pull/books.py": "0b89744960136a4f2e594b61e6df754d357706d8c66a8ae359d8eb02bbfa53f8",
    "pull/build.py": "75bf99c55b5f2561a60a120c82db368ad3b996a8a64e9ab08828b586a9314419",
    "pull/gamemodel.py": "2a2519a12ad4993da02ae6bdcdb6c86f2b5a6554ce93a702b550ecde17fb7d1f",
    "pull/matchup.py": "15b1739b203e1757b0ebaefa3a6994034d56bb4a92a9e07572527ef1a90e914c",
    "pull/news.py": "17ce1b3b6b72694e6b543bd767e287c26a9d1f6dd5dba2de6c873543036842e9",
    "pull/scoring.py": "31672c10d526d591db8951157b0ecd669b4d02b412a75deec337618bff18dab2",
    "pull/sources.py": "36555cdbc55d73ba632d5adae1130288f4f532073857c642ac3ebc7e626b0061"
  },
  "model_code_sha256": "52620fb9fcf6a3fe8ac82057c5caf1a0947ae726ef4bdb64c46f8ad91179d635",
  "production_enabled": false,
  "protocol": {
    "baseline_model": "original_sleeper_matchup_baseline",
    "candidate_id": "rec-half-adjustment-v1",
    "fitting": false,
    "formula": "raw + 0.5 * (unchanged_adjusted - raw)",
    "production_promotion": false,
    "publication": "LOCAL_OBSERVATION_NOT_VERIFIED_PUBLICATION",
    "recording": "OFFLINE_ONLY_NO_UPDATER_HOOK",
    "same_original_receipt": true,
    "selection": "earliest_eligible_common_triple_by_capture_then_completion_then_digest",
    "target": "rec",
    "tuning_budget": 0,
    "version": "rec-half-protocol-v1",
    "weight": 0.5,
    "window": {
      "first_kickoff": "2026-10-23T00:15:00Z",
      "first_kickoffs_by_week": {
        "10": "2026-11-13T01:15:00Z",
        "11": "2026-11-20T01:15:00Z",
        "12": "2026-11-26T01:00:00Z",
        "13": "2026-12-04T01:15:00Z",
        "14": "2026-12-11T01:15:00Z",
        "7": "2026-10-23T00:15:00Z",
        "8": "2026-10-30T00:15:00Z",
        "9": "2026-11-06T01:15:00Z"
      },
      "schedule_changes": "retain_original_membership_and_kickoffs; flag_changes; never_shift_window",
      "schedule_reference": {
        "file_sha256": "84a85e361cb0d2f01a1e5f0be8e2072d854b386d4753e29e4b1fff496a23ea7e",
        "generated_at": "2026-10-14T01:10:09Z",
        "path": "output/data/teams.json",
        "purpose": "EXISTING_PLANNING_SCHEDULE_NOT_INDEPENDENT_FULL_WEEK_PROOF",
        "source_commit": "52d068326045c010c9e3bb89f23188f9153ab151"
      },
      "season": 2026,
      "shift_or_extension_allowed": false,
      "weeks": [
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14
      ]
    }
  },
  "protocol_sha256": "9877a43b85f0ff35e98c2866a7b82195a1387f5757e4df370d218a40f06bf7dd",
  "protocol_version": "rec-half-protocol-v1",
  "recording_status": "OFFLINE_NOT_ACTIVATED",
  "registered_at": "2026-10-16T19:36:46.224755Z",
  "schema_version": "point-candidate-registration-v1",
  "source_commit": "52d068326045c010c9e3bb89f23188f9153ab151"
}
```

The offline CLI exposes `register`, `capture`, and `evaluate`; output must be
outside this source checkout. For this completed registration, point `evaluate`
at its saved create-only receipt with no candidate/outcome arguments to report
`NOT_RECORDED`, zero samples and null errors. A new registration command creates
a distinct actual-clock record; it does not supersede the official registration.
Saved candidate receipts reference the exact registration and original baseline
payload/row digests. Their consumers validate both original records again,
including the retained engine, rather than trust saved validation flags.
Candidate receipts use `data/verification/point-candidates`; registrations use
its `registrations` subdirectory. The existing updater already preserves the
verification lane, but no hook is activated by this implementation.

Unknown/altered candidate or registration contracts fail closed. Original
baseline v1 rows retain their recorded season/week shape; no header is invented.
Legacy resolved outcomes without selected-source attribution or saved statistics
remain readable through the original consumer, but this new prospective
candidate labels them unresolved (`legacy_missing_source_or_stats`) and does not
score them. Unknown provider source clocks remain explicitly unknown and do not
by themselves erase valid locally recorded evidence. Original primary scoring
and historical receipt bytes are unchanged.

Keep this v1 module/validator unchanged for its legitimate saved registration
and candidate receipts. A future code/formula/schema change needs its own
versioned implementation and explicit validator dispatch, retaining v1; do not
update an old receipt hash or accept a changed file merely to keep it eligible.


Use the first eligible common triple per player/game/category, ordered by parsed
original collection time and deterministic receipt tie breaks. Repeated captures
are alternatives for one outcome. Never combine raw and adjusted forecasts from
different receipts, replace the primary experiment's own earliest-pair rule, or
use a later observation to fill an earlier missing forecast. Retain generation,
original collection, candidate start/completion and saved kickoff independently.
Prospective eligibility requires a new original live observation strictly after
registration and actual candidate completion strictly before saved kickoff.
Exact-kickoff, future/reversed clocks and retrospective calculations cannot
qualify. Explicit development/descriptive calculations remain separate.

The fixed evaluation window is 2026 regular-season Weeks 7 through 14, the first
eight full chronological weeks after this freeze. Week 6 is already underway and
can contribute development/descriptive examples only. Do not shift or extend
Weeks 7–14 for unavailable captures, missing outcomes, delayed activation or
unfavorable results. Preserve the saved schedule and changes; postponements or
cancellations do not silently replace week membership or rewrite original
kickoffs. Confirmed cancellations/voids remain supported unscored statuses.
A changed schedule requires separate retained evidence and the existing
complete-week reconciliation; a contradictory clock or identity cannot qualify
merely because the NFL week number matches.

Existing saved planning schedule: `output/data/teams.json` at approved base
`52d068326045c010c9e3bb89f23188f9153ab151`, generated
`2026-10-14T01:10:09Z`, file SHA-256
`84a85e361cb0d2f01a1e5f0be8e2072d854b386d4753e29e4b1fff496a23ea7e`.
Its recorded first kickoffs are:

| Week | First kickoff, UTC |
| --- | --- |
| 7 | 2026-10-23T00:15:00Z |
| 8 | 2026-10-30T00:15:00Z |
| 9 | 2026-11-06T01:15:00Z |
| 10 | 2026-11-13T01:15:00Z |
| 11 | 2026-11-20T01:15:00Z |
| 12 | 2026-11-26T01:00:00Z |
| 13 | 2026-12-04T01:15:00Z |
| 14 | 2026-12-11T01:15:00Z |

These are saved scheduling observations for prespecification, not independently
verified full-week population receipts. No new provider request was made or
restricted capture reviewed for this registration. A later schedule change must
be recorded separately; these original planning bytes and fixed week labels
remain retained.


Outcome scoring consumes saved outcome receipts through the retained
authoritative consumer, including source-version corrections, conflicts and
participation checks. Bind exact player/game/category, saved kickoff and team;
retain opponent evidence and mark missing original opponent identity unknown.
Missing statistics do not become zero or DNP. Confirmed played zero is a valid
count. Pending, unresolved, confirmed DNP and supported voids are distinct
unscored observations. Keep selected source receipt/row/provenance references.
Full-week evidence eligibility is separate from valid individual point outcomes.
The accepted IR-01 source validation remains unchanged.

Report common-row receptions MAE, RMSE and signed bias for raw Sleeper, unchanged
adjusted and the candidate; report paired candidate-minus-each-baseline error
differences, weekly and cumulative rows, unique players/games/weeks, missing pairs,
repeated captures, missing outcomes, exclusions and evidence coverage. Do not
mix counts and yards or label player rows independent games. Whole-week
uncertainty must use the unchanged completed-week requirement, season/week
cluster resampling, seed 1906, 2,000 replicates and 98.33% confidence where
applicable. An absent qualified week does not block descriptive scores.
This receptions-only point experiment cannot satisfy the original three-target
and probability production-promotion gate. It supplies no probability accuracy,
selection profitability, EV/ROI or automatic promotion claim.

The prior inventory is a development-data limitation, not a new recount:
140 unique receipts produced 42,607 same-receipt paired reception capture rows,
but only 316 unique opportunities across 14 games in Week 6; 42,291 were repeated
paired rows. Six immutable outcome receipts had zero resolved matches.
The Git-pinned saved-cache descriptive regrade had 19 resolved pairs from one
game/week. Inherited Week 4/5 records lack original forecast clocks. None becomes
an untouched future test or suitable chronological learned-model training set
merely by recomputing this formula.

The implementation is offline only. No updater hook or ongoing recording is
activated. A later approved hook must calculate on genuinely new eligible
baseline receipts inside the existing serial updater, preserve create-only
registration/candidate evidence before kickoff, and report missed Weeks 7–14
observations without moving the window. Existing code and an empty report are
not evidence that this operating capture path exists. No new scheduler is needed.

Preserve the original Week 6 missing-matchup-proof failure. A new receipt cannot
authenticate that old artifact. Original AUD01 capture review remains separately
pending, and neither original nor derivative archive export is authorized here.
No forecast/source/outcome receipt is rewritten, no model is fitted, and no
production integration, public forecast publication, merge or deployment is
included.

## Canonical all-category forecasting and testing roadmap

This is the single retained research ladder for this website project. Subsequent
bounded protocols should reference it rather than create competing roadmaps.
The half-adjustment receptions candidate is the first comparator, not a finished
forecasting upgrade.

1. Operate the paired raw-Sleeper versus unchanged adjusted comparison on common
   original observations. Separately version no-adjustment, restrained learned
   upstream-error correction when timestamped training data permits, and
   category-specific shrinkage. Split chronologically with untouched future
   confirmation and a fixed tuning budget; do not assume matchup adjustment helps
   every target or that upstream information is double-counted.
2. Test supported workload and participation information in bounded additions:
   team plays, passing/rushing allocation, attempts/targets, genuine snaps/routes,
   availability, injuries and role changes. Preserve missingness and actual
   information clocks.
3. Evaluate matchup estimation chronologically, including shrinkage and clipping.
   Player-game counts include correlated teammates; handle game/team dependence.
   Eight prior games and 0.75–1.25 multipliers are engineering choices to test.
4. Specify forecast semantics (means, medians, quantiles or samples) and enforce
   appropriate coherence: completions/attempts, receptions/targets and combined
   yardage/components. Do not hide contradictions through arbitrary normalization.
5. Compare appropriate count/yardage distributions, participation scenarios,
   dispersion, calibration and tail behavior on saved future forecasts. Retain
   legal support, integer push mass and extreme losses; use proper scores and
   intervals. A projection-gap score is not automatically a win probability.
6. Add market-only/hybrid comparisons only with saved event/full-contract evidence.
   A line is a point benchmark; fair probabilities need supported prices and
   documented margin removal. Avoid circular references and invented -110,
   complete-entry payouts, EV or ROI.
7. Evaluate selection policies separately. Retain the original up-to-twelve-per-side
   benchmark; allow fewer selections and genuine NO_ACTION. Compare matched
   opportunities plus total coverage. Do not multiply marginal probabilities into
   ticket probabilities without a justified dependence model. Freeze confirmation
   before future outcomes and retain failed candidates.

Extend descriptive point accuracy to every eligible category, including No Lean,
categories without sportsbook lines and fantasy points. Retain separate scopes
for the three registered primary targets and all ten pickable selection
categories. Evaluate game spreads/totals and saved moneyline probabilities with
their own units and proper scoring when forecasts exist. The reproduced kicker
field-goal omission belongs to a separately versioned game-score correction; it
does not by itself block an independent receptions experiment. Statistical
forecast accuracy, recorded selection success, probability calibration and
supported financial performance remain separate questions.

Each candidate requires reproducible code/tests, immutable row-level forecasts
and outcomes, original clocks/model versions, category-specific MAE/RMSE/bias,
coverage and sample context. Historical reconstruction can support development
but is never original pregame proof. Results may show improvement, no established
improvement or insufficient valid evidence. Minimum-week requirements constrain
the defined inference/promotion claims, not useful descriptive reporting,
synthetic development or separately authorized shadow research.
