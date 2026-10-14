# Reproducible forecast comparison — Phase 2

## Release status

Phase 1 is deployed in the existing repository and website. The first verified
production capture/deployment followed source commit
c5fd39cb2277b1b46c224fc2552b314377694bb2. The latest inspected production run,
38485592435, succeeded while its advisory verifier reported 805 discrepancies.
Those advisory failures are not described as passing checks.

Phase 2 is a review branch and pull request, not a deployed release. Stop before
merge or any production-model switch. Main and the existing Pages site remain
on Phase 1 until the owner reviews and merges the PR.

Before editing, the original remote backup was verified at
backup/pre-phase1-20261013-210e34329d6e. A second remote backup of working Phase 1
was created and verified at backup/pre-phase2-20261014-3149663447b2, commit
3149663447b29f95f06c7259b84da3bd4a21cab0. See ROLLBACK.md.

## Implemented in the review branch

- Exact matchup input recording around the byte-identical retained builder.
  Full roster positions include bye-week players; prior-week stats are immutable
  snapshots. Frozen games retain their original input reference. Required
  offline verification fails for missing proof, changed frozen forecasts,
  future inputs, corrupt checksums, wrong factors and wrong sample counts.
- A prospective scorecard from existing and new immutable baseline receipts for
  receptions, rushing attempts and passing yards. Raw Sleeper and the unchanged
  clone are paired within one capture. The earliest valid pair is selected once
  per player/game/statistic. Repeated captures are reported, never extra outcomes.
  Missing pairs, pending finals, DNP and unknown participation remain distinct.
- Final-status/participation provenance and append-only outcome snapshots.
  A bare post-game flag is insufficient to establish a completed game. Corrections
  create new snapshots and never rewrite forecasts or older outcome evidence.
- MAE, RMSE, signed errors, lead-time/injury coverage and paired week-cluster
  uncertainty. Eight fully completed NFL weeks are required for intervals.
  There are no completed outcomes in the initial Week 6 comparison; empty metrics
  are null, not zero or a claim of accuracy.
- Versioned evaluation/promotion policy committed before challenger development.
  Promotion remains manual and disabled. See docs/EVALUATION_PROTOCOL.md.
- Narrow Sleeper NFL normal-line selection capture for those three statistics,
  reusing the collector's existing public request. Contract/game mapping, source
  selection ID, line, side, leg multiplier, collection time, available updated_at
  field and official rule-page provenance are retained. No-offer, unavailable
  source and missing-information states are separate.
- An experimental shadow distribution model with current-season prior-week
  dispersion and fixed priors. Probability references centered on raw Sleeper and
  the clone are saved at the same time. Matched proper-score evaluation is
  implemented, including log score, three-way Brier and 80% interval coverage.
  Production picks, forecasting math and selection thresholds remain unchanged.
- About explains the implemented scorecard, shadow mode and capture limitations;
  unsupported historical performance and standalone-multiplier claims removed.
- Working-Phase-1 and original recovery routes retain all subsequent evidence,
  caches, browser settings and Git history. No reset or force-push is needed.

## Explicit limits and unresolved issues

A Sleeper leg multiplier is not a complete executable entry payout or a
straight-bet price. Complete entry format/payout context, acceptance and
entry-specific settlement remain unavailable in this feed. Those fields stay
missing; EV, ROI, venue injury/void grading and profitability are not computed.
No paid service, account signup, wager or optional AI service was added.

Source updated_at is recorded as a provider-reported field, not a guaranteed
quote time. Projection source-level as-of correctness, executable availability
and settlement-rule binding remain unverified. Rule-page hashes document the
retrieved versions; they do not guarantee that rules never change. The existing
public feed was reused; expanded/commercial licensing is not established.

Older Phase 1 builds lack original population snapshots. A contemporaneous
roster refetch explains the saved 805-error case but is not substituted for
original historical proof. Frozen forecasts without such proof fail verification.
Network diagnostic outages remain visible; local software tests do not establish
prediction performance. The first challenger retains the clone's center, so it
cannot earn point-MAE improvement merely by adding a distribution.

## Validation and operation

Run the offline suite and syntax/UI checks:

```sh
python -m unittest discover -s tests -v
python -m compileall -q pull tools
node --check output/app.js
node --check output/reliability-ui.js
node tests/test-ui.cjs
node tests/test-about.cjs
```

The fictional end-to-end replay covers recorded inputs → baseline receipt →
shadow/offer receipts → pending outcomes → confirmed final → corrected outcome.
It verifies retry immutability, untouched production selections and recovery-mode
refusal. Replay evidence is never prospective performance evidence.

For a live local integration check after dependencies are installed:

```sh
python tools/build_recorded.py
python tools/verify.py --offline --json output/data/matchup-diagnostics.json
python tools/phase2_capture.py --mode live
python tools/verify.py
```

The hourly runner uses the same sequence after merge, then records advisory
results and commits validated evidence before deploying output/. If main changes
mid-build, publication aborts. It never rebases or resolves generated forecasts
by choosing one side. Forecast/verification/offer/shadow/outcome receipts are
create-only. The PR workflow runs deterministic tests, including the end-to-end
replay; it does not deploy the review branch.
