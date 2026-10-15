# Phase 2 review validation

The results below describe their named historical source checkpoints and
separately recorded local builds. The committed static Week 6 output still has
no matching original-input proof and fails the required offline verifier.
The prospective v2 contract and current limits are documented at the end.

The source checkpoint ae28843e5ccaf7b81f520ee4c719c67830f84a17 passed
[GitHub CI run 38494530356](https://github.com/NickNicky19/nicks-expert-nfl-picks/actions/runs/38494530356).
It includes 103 Python regression/end-to-end tests, 8 UI helper assertions,
9 About rendering assertions, and Python/JavaScript syntax checks.

Fresh live collection, exact-input verification, immutable baseline/shadow/offer
capture, outcome snapshotting and comparison generation were completed locally.
The full verifier found zero mismatches in 1,860 factors, checked PPR/half-PPR on
6,452 player-weeks and matched all 55 compared kicker/defense scores. Shape and
selection checks covered 502 players, 14 games and 24 picks. No final games were
available this week; live final-game scoring and real prediction performance
were not demonstrated. Fictional final/correction cases are software tests.

After incorporating the newer Phase 1 captures from main, the snapshot has 415
unique matched opportunities, 2,900 repeated capture rows and 800 missing-pair
capture rows. All 415 outcomes are pending. Point/probability performance metrics
remain null. Raw Sleeper and the clone are paired within one forecast receipt;
missing values are not completed from a different capture time.

The latest source observation captured 166 complete selection records and 862
no-offer cases. Its collection time is 2026-10-14T01:13:43.805087Z. Full executable
entry capture remains incomplete: no entry-format/payout table, acceptance or
entry-specific settlement is established, so complete_executable_entries is 0.
The available multipliers are source observations, not invented straight-bet
odds or complete payouts. Quote freshness and source-level as-of correctness
remain unverified. Source outages and incomplete contracts are tested separately.

Shadow v1.1 has 414 unique matched opportunities; original v1 also retains 414,
evaluated separately rather than pooled into extra outcomes. The revision fixes
mixed timestamp precision ordering; distribution parameters and promotion rules
are unchanged. The first registry and every prior forecast remain intact.
Neither version has resolved real outcomes, calibration evidence or profitability.

Both recovery targets were rehearsed in a disposable local Git repository using
exact original/Phase 1 source blobs. All 58 data/evidence files present in that
rehearsal remained byte-identical, history and pre-restore branches were retained,
and the restored Phase 1's original offline checks passed. Subsequent evidence
is also retained by the same allowlisted recovery commands. Production recovery
was not run. Main's source matched the verified Phase 1 backup while its scheduled
collector continued appending new captures.

The machine-readable report in data/verification/reports includes file/payload
checksums, code checkpoints, backup references, live counts, runtime and limits.
The new verification envelopes include the complete build output and exact
inputs, allowing reproduction without replacing main's current generated data.
The saved original diagnostic reproduces 805 subset failures and zero full-roster
failures; its newer roster observation is explicitly not original as-of proof.

Legacy frozen forecasts without original input proof intentionally fail the
new verifier. If rollout occurs after such games start, investigate that evidence
gap and retain the last valid release; do not waive the check. Source errors and
unavailable network coverage remain visible. No account, paid service, website
replacement, production model switch, reset, force-push or evidence deletion was
introduced. Pages deployment remains pending owner review and merge.

## A07 original-input verification: prospective v2

The A07/A02-PROV-01 correction qualifies new `matchup-inputs-v2` receipts. The
unchanged builder still supplies its exact full skill-player position mapping,
including bye-week players, and current-season prior-week statistics at its
original `Matchups` initialization. Engine files and all forecast math remain
unchanged. The receipt preserves the complete output, source-request identities
and decoded-response fingerprints, actual build/input/completion observations,
and an explicit live/replay mode. `code_commit` is the caller's recorded
`GITHUB_SHA`, not independently authenticated publication evidence.

The shared verifier checks payload checksums AND the exact content-addressed
path/period, source/output/engine identity, unique original games/players/props,
original kickoff/team/player/opponent mapping, prior-only inputs, factors,
sample counts and unchanged frozen forecast fields. It never rebuilds old inputs
from today's roster or statistics cache. A new current-week receipt must also
match the current output and its saved decoded ESPN game-status response.

Original input observation, forecast generation and recorded build completion
must all precede the game's kickoff. UTC instants are parsed. The retained
builder truncates generation timestamps to seconds; the observation must be in
or before that generation second. Exact observation/completion instants still
have a strict before-kickoff bound. `recorded_at` observes completion of the
builder before receipt serialization; it does not claim independently verified
filesystem/publication time. A post-kickoff completion cannot create a new
original game origin. Frozen games retain their genuine earlier reference;
missing or unqualified origins remain blocked.

`phase2_capture.run_capture` now executes the same required offline PPR,
original-input, shape and selection-balance checks before the first capture
write. Invalid original proof or a mismatched latest receipt creates no new
baseline, shadow, offer, outcome, verification or report files. Live capture
refreshes its actual clock after preflight; it accepts neither replay inputs nor
a supplied historical clock. A create-only `matchup-verification-v1` receipt in
`data/matchup_checks` (or `matchup_checks_replay`) links the exact inputs/output,
game origins, engine, check time and baseline payload. Health records its path.

All legacy inputs/forecasts/evidence remain byte-identical. Reading legacy
evidence does not certify missing v2 qualifications. In particular the retained
Week 6 output digest is
`6e2721c8ffa524621ba22384d070295ed6c3d2ccd9a5f5cc2ba5eb1fe3ef851d`,
generated `2026-10-14T01:10:09Z`; none of the four saved original input receipts
matches it. The later diagnostic roster refetch is not a substitute. No pointer
is backfilled and no historical forecast is reconstructed.

For genuine new prospective validation, use a separate clean disposable checkout
of the exact corrected commit. Preserve its initial manifest and source SHA;
run the unchanged engine through `tools/build_recorded.py`, then the required
`tools/verify.py --offline`, then `tools/phase2_capture.py --mode live`. Save the
new matching output/meta/inputs/origins, raw verifier log, immutable capture links
and actual clock/source manifests in an audit packet. Do not run this collector
in the shared review or production checkout, push generated data, or overwrite
the older failing snapshot. A source outage, started game, invalid origin or
failed verifier remains a visible limitation. A replay is only a software test.

These checks establish saved local consistency and reproduction. They do not
authenticate provider as-of truth, pregame public publication or real full-week
NFL population completeness. A separate verified full-week capture adapter and
real future evidence are still needed; there is no invented complete-week CI,
accuracy result, calibration or sportsbook profitability. No model/policy
promotion, merge or deployment is authorized by passing the software checks.
