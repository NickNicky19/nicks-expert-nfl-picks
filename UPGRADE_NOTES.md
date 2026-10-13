# Reliability foundation — Phase 1

## Preparation status

**In the preparation session: built and locally tested, but not installed or deployed.** The GitHub connection rejected the requested backup-branch write.
Apply this patch to the existing `NickNicky19/nicks-expert-nfl-picks` repository, not a replacement repository.
The installed release's actual workflow results must be checked before marking deployment complete.

## Implemented

- Statistical grader v2: strict finite numeric inputs; explicit equality/push outcome; missing participation is unresolved;
  confirmed DNP requires explicit sourced evidence. Existing sparse stat rows still represent omitted zeros only when
  participation is known. No venue-specific injury, void, or payout rules are invented.
- Both raw and matchup-adjusted projections retained in top-pick grade records. Source-separated lean tallies added.
  Compatibility fields remain; `dk_leans` historically combined both real-line sources, so use `by_venue` for attribution.
- Original pre-v2 grading output preserved once before the first upgraded build. Forecast archives are not rewritten by
  the grader. Older weeks require explicit final-game evidence rather than assuming a week in the past is entirely final.
- Required offline tests, structural validation, timestamp/history checks, selection consistency, and exact original-model
  hash checks before publication. The older network-dependent verification/comparison steps remain advisory and their
  outcomes are saved in `output/data/health.json`; not every old diagnostic is a release gate.
- No rebase conflict preference for generated evidence. If main changes during a build, publishing aborts rather than
  merging conflicting forecasts. A failed critical step leaves the previously published site in place.
- Create-only compressed baseline receipts under `data/forward`, after the collector builds; not in the public static site
  directory. Each stores raw/adjusted projections, available lines, source/code fingerprints, and first local capture time.
  Only games still pregame at capture time enter the receipt; forecasts for all eligible players are recorded, not only picks.
- Separate replay lane under `data/replay`. Live CLI forbids a user-supplied clock. Retries preserve existing receipt bytes.
- The score-refresh clock now advances only after a successful matched scoreboard response, not after failed poll attempts.
- About/Record explanations and a build-age status message. The operational warning threshold is 120 minutes; that is not
  a guarantee of sportsbook quote freshness. Per-source timestamps remain unverified.
- Manual recovery restores the original app/grader through a JSON mode switch without editing workflow definitions. A local full-restoration command can also restore the original workflow with appropriate write access. See `ROLLBACK.md`.

## Unchanged

Projection formulas, matchup adjustments, selection thresholds, scoring constants, collector endpoints and schedules,
existing stylesheet, league integrations, browser-local settings, and the disabled-by-default optional Worker connection.
The preserved engine is an original benchmark, not a newly trained independent football model.

## Not implemented or established in Phase 1

Calibrated prop probabilities; positive-EV selection; verified DraftKings prop-side prices; venue settlement adapters;
parlay joint probability/payout engines; new workload models; prospective comparison of challenger models; profitability.
No paid service, signup, sportsbook action, or automated wagering was added.

Receipt existence proves a local observation, not public publication, executable prices, or source-level as-of correctness.
Git commit/deployment receipts and authenticated source timestamps would be additional evidence. Known source timestamps
are marked unknown, not guessed. The small archived sample is for regression tests, not performance proof.

## Tests

```sh
python -m unittest discover -s tests -v
node --check output/app.js
node --check output/reliability-ui.js
node tests/test-ui.cjs
```

The package contains test logs, a historical-fixture replay report, and browser smoke-test results.
A full source rebuild against live Sleeper/ESPN, hosted CI, OAuth integrations, and a real Pages deployment were not
performed in this environment. Those integration checks remain necessary before claiming end-to-end deployment.

## Next milestone after deployment

Validate one fresh build → immutable pregame receipt → committed evidence → public release cycle, verify the source
coverage/diagnostic status, and then begin a preregistered original-versus-challenger comparison. Preserve the original
baseline and test on future games; do not promote a new model because of software-test counts alone.
