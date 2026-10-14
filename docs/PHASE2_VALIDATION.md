# Phase 2 review validation

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
