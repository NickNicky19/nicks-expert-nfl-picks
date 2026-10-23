# Phase 2 reporting and implementation handoff

## Shared payload compatibility and local runtime limit

The shared contracts are `selection-publication-pointer-v4`,
`selection-public-report-v5`, `selection-final-outcome-index-v2`,
`selection-public-rows-v2`, `selection-public-summary-partition-v2` and
`selection-final-outcome-period-v2`. Reusable row, summary and outcome bodies
omit only the per-generation report-ID envelope. Generation metadata remains
in the indexes and manifests. Forecasts, original clocks, outcomes, memberships,
semantic summary IDs, global positions and 250-row slicing stay unchanged.

Bodies use deterministic application gzip and separate encoded/decoded hashes
and bounds. Application gzip is distinct from HTTP Content-Encoding. Explicit
plain/gzip legacy readers remain supported; invalid modern assets never trigger
a permissive fallback. Complete graph validation precedes pointer advancement.

Reuse is limited to one operation. Actual bounded bytes, descriptors and relevant
dependencies are freshly checked before cached decoding or reconciliation can be
used. Defensive copies prevent mutable aliases, source/destination roots remain
separate, and a later operation does not trust a previous success flag.

Saved packaging uses `website-packaging-generation-v2` and a flat transition
receipt. Original capture evidence and clocks remain distinct from later
packaging. Recovery must support pointer-v4, gzip and packaging-v2, preserve
retained evidence and the deployed presentation, and be checked through later
updater runs. Reverting to an incompatible reader is not functioning recovery.
A limited fallback is not implemented or activated by this documentation.

The saved real-size local control measured 1,117.148 seconds of recurring
dataflow. Adding the separately measured 473.088 seconds of retained checks gives
1,590.236 seconds, exceeding both the unchanged 1,200-second job timeout and
960-second safety budget. This combined local runtime control fails; the dataflow
alone also exceeds the safety budget. Mocked sources, local contention and
separately measured checks limit the comparison, and hosted setup, provider/API
and Pages latency remain unmeasured. Smaller synthetic successes and passing
correctness checks do not establish hosted or routine season-long operation.

No production cutover, deployment or experimental recording is activated by
these source changes. All-category numerical evaluation remains local/opt-in;
artifact, disclosure and combined release/recovery decisions remain separate.

### Prepared publication correction (2026-10-19)

The publisher now retains an operation-local prepared result only after complete
publication validation. Every lookup freshly hashes the bounded complete graph,
including non-default partitions and legacy plain row chunks. Source/helper or
contract changes invalidate lower decode and semantic reuse too. Public readers
receive isolated decoded values from private immutable serialized results.
The optional LRU retains at most eight results and 384 MiB of serialized values;
that bound is additional memo accounting, not a total process-memory cap.
Outer source, original-input, native, scope, completion, generation, health,
clock, archive/Git, destination and atomic-advancement checks remain unchanged.

The fixed serial unprofiled B1/C1/C2/B2 comparison used frozen input 643f99be,
fresh control/candidate checkouts and identical saved responses, clocks, retained
data history and timing boundaries. Control 551d605 dataflow took 1,159.937 and 1,192.730
seconds; candidate 18fd286 took 400.632 and 416.573 seconds. The candidate passed
544 Python tests and retained syntax/UI/About checks; the hourly-required subset
separately cost 253.536537 seconds, giving measured local sums of 654.168 and
670.110 seconds. Compile and whitespace checks separately added 0.036364 seconds;
they are not steps in the unchanged hourly workflow.
Adding the separately measured C2 utilities and blocked advisory prefixes to
both samples gives lower-envelope estimates of 655.158 and 671.100 seconds;
these are sums of separate measurements, not complete job timings. The matched
control suite was not remeasured, so no check-suite speed comparison is claimed.
These fixed initial retained-history local components fit the 960-second
planning target; they do not bound the cost of a growing retained archive. The complete
connected/hosted budget remains UNKNOWN, and the 1,200-second timeout is unchanged.
Full online-advisory continuation, hosted setup/dependencies, live providers,
remote Git, artifact transfer and deployment remain unmeasured. Local Git,
Pages staging and uploader tar creation are already included in dataflow.
The historical failed 1,590.236-second control above remains preserved.

Matched Python-process peak RSS rose from approximately 1.91 to 2.43 GiB.
Maximum observed retained serialized bytes in any one memo were 398,233,666,
below its 384 MiB per-memo bound; that bound does not cap aggregate process
memory. Existing 3/6/18-week synthetic storage fixtures returned literally
identical complete values under both sources when each read the same actual
assets in each format. Cold 3/6-week single-reader whole-process checks were
1.1–4.5 seconds slower with the candidate; their serial order and OS caches were
not controlled paired performance evidence. The 18-week full-reader process
reached approximately 7.97 GiB peak RSS, including returned copies and full-value
hashing, while its oversized prepared result remained unretained. This observed
peak is not a minimum RAM requirement or full-season hosted-capacity proof.

The paired reports preserved forecast contracts, outcomes, exact logical
memberships and registered comparisons. Three receipt-bound decision identities
differ truthfully with the actual source fixture commits. Separate full-preimage
reconstruction by the implementation analysis proved that precise delta without
rewriting receipts or clocks; this is not independent actual-source acceptance.

Local Chromium checks completed 117 presentation checks, 24 loads and 54 complete
groups with no recorded missing assets or page errors. Retained-v3/shared-v4
initial loads respectively used 626,395/626,481 response-body bytes cold with
17 local-site requests, and 320,104/320,312 bytes returning with 10 requests.
These are server response bodies excluding headers, not complete wire totals;
mocked external requests are separate. This frontend format comparison used
identical final app bytes and does not measure the backend correction. Loopback
phone emulation does not establish physical iPhone/Safari, public cellular or
deployment acceptance.

One separate saved-genuine-capture packaging probe using candidate code and real
packaging time took 135.096 seconds, followed by 50.745 seconds of generation
validation. It preserved original capture lineage and complete public semantics
without provider collection. The independent review of the original 29166
archive remains complete and was not reopened. The derived local packaging copy
is not an approved production artifact or a new independent actual-source review.

All twenty real-sized mocked updater steps passed complete saved-data replay,
including exact memberships and the four intended fictional outcome corrections.
Six-component dataflow averaged 515.969201 seconds and reached 677.596708 seconds;
adding the once-measured hourly checks gives a maximum local subtotal of
931.133245 seconds. The remaining 28.866755 seconds to the 960-second planning
target do not certify unmeasured hosted work. The final isolated fixture runtime
was a41756bd, tree 2527f16c; it is not a public development or deployment identity.
The twenty five-second mock steps span 100 fictional source seconds, not six
hours, cadence or hosted operation. Sequence peak RSS and a real-sized exact
whole-updater retry remain unmeasured.

The twenty steps added 13,093,318 evidence-lane bytes, including derived evidence,
and 324,528,918 report/generation asset bytes. Adjusted packed-history increments
totaled 300,416,000 bytes, excluding 984,064 packed setup bytes (distinct from
985,907 bytes of Git-directory setup). Working-file bytes grew from 119,510,354
to 457,135,059; Git-directory bytes from 73,490,872 to 375,564,221. Final complete
Pages staging was 48,711,382 bytes and uploader-command tar 49,571,840 bytes.
These are local stored sizes, not network transfers or season-long capacity.
Sixteen new-clock updates retained unchanged outcome values but added observation
and provenance evidence; they were not metadata-only rotations. This CPU
correction preserves the earlier shared format and claims no new storage saving.

A scratch-only broken publisher was rejected, intervening fictional evidence
retained, and a normal forward restore to compatible candidate code completed.
Actual restored source 8f7e2de4 then passed two mocked updates and complete saved
replays, preserving 3,819 prior immutable files and the intervening evidence.
Their dataflows were 704.258455 and 707.089166 seconds; adding the separately
measured hourly checks gives 957.794992 and 960.625703 seconds. The second exceeds
the 960-second planning target by 0.625703 seconds before hosted overhead; this
FAIL is retained without another timing sample or changed limits. Functional
format-compatible recovery passed; routine operating-budget recovery did not
qualify. Returning to source 551d605 remains format-compatible but restores its
known slow path, and the older 269a817 reader explicitly rejects shared-v4.

The recovery wrapper's kernel-reported largest descendant-process RSS was
6,724,208 KiB (approximately 6.41 GiB), across its helper/workers/Git descendants.
It is not their sum, concurrent total, cgroup peak or an attributed worker peak;
separate root retention work is excluded. The wrapper's 2,443.050-second wall
time includes acceptance work and a root review pause, not one updater job.
Different retained histories make this a separate observation from the initial
matched RSS comparison. No hosted or season-long memory/operating PASS is claimed.

These measurements identify publisher/test code 18fd286. The actual published-
source commit, PR test-merge checkout identities and their actual check results
are recorded separately in this checkpoint's CODEX_RESULT. A later documentation
commit has its own source identity even when publisher/test bytes are equivalent;
the older local check result is not a final published-source or CI verdict.
These local measurements certify no production cutover, artifact/content
disclosure, hosted acceptance or release/deployment.

## Approved partial-week operational cutover (source implementation)

This checkpoint implements NFL-WEB-PARTIAL-OPS-PROPOSAL-20261018-131818Z,
PR #1 comment 6250738186 (canonical proposal SHA-256
7fee0d61faca32ce9f361e543fb27140c40500595ae51cd714c738c945a9cfb2).
It changes no forecasting engine, ranking policy or registered experiment.
Source implementation, independent source acceptance, an inspected actual-data
package, disclosure approval and production release remain separate states.
No genuine operational package or deployment is established by fictional tests.

The explicit `verification_mode` is either `strict-full-board-v1` or
`partial-week-input-reproduction-v1`. A strict error NEVER selects partial mode.
`tools/verify.py` is unchanged; its old Week 6 missing-original-proof failure
remains visible. Partial verification never establishes full-board verification
or complete-week research qualification. It establishes only reproduction from
retained original model inputs/factors, not independent raw-provider projection
authentication, quote freshness, executable prices, predictive accuracy, ROI
or platform settlement.

The approved immutable plan is embedded intact in config/phase2.json with its
canonical digest d1d2b076a9be544b16d29d333f895ab2336892a6d9c16539c6671eb5cfd19024.
It binds 2026 Week 6, the complete original board at
885e165e41b9cc0c34b68c1cf57888443505cd7e, all fourteen game/team/kickoff
identities and the original saved schedule/status observation. Its preparation
and effective-not-before clock is 2026-10-18T13:50:07.746131Z; its expiry remains
2026-10-21T00:00:00Z. These are plan clocks, not actual registration or execution.
Only SEA–DEN/401872995 and HOU–JAX/401872996 have approved legacy exemptions,
with the exact contract fingerprints in that plan. Current fresh status must
confirm those games have started without schedule/team changes. Missing or
invalid nonexempt proof cannot enlarge this list. An expired same-week plan
fails closed; another season/week selects the strict route without exemptions.

Actual registration is a separate create-only receipt containing its real
clock, source commit, validator-file digest, exact plan, owner authorization,
complete initial board and original schedule/status references. The approved
plan's original PROPOSED metadata is never rewritten. On first preparation the
initial board is retrieved from its exact Git commit (or its intact retained
receipt); the saved schedule source must already be retained in
data/verification/partial-schedule-baselines as a `partial-schedule-baseline-v1`
envelope with season, week and the intact original `status` object. Its digest,
clock, response/request, full population and teams/kickoffs must match the plan.
A current status or source digest alone cannot replace this required original.
These seed bytes belong to the separately reviewed local artifact and later
actual-content approval; source approval does not upload them.

### Source, clocks, retry and recovery

`partial_week` is a network-free validator. The existing capture entrypoint
obtains one closing response through the existing ESPN scoreboard path and
retains its actual clock/request/full decoded response. It must be no more
than sixty seconds old at completion. All original v2 envelopes, engine,
positions/history, complete boards, origin mappings, game/player/team/opponent,
saved lines/sides and Top memberships are checked. Active-game failures fail
the generation, never a trimmed-and-rehashed board.

Native filename identity remains input/engine/mode, unchanged. New observations
require generation, input sealing, validation and persisted native/scope evidence
before kickoff. The final cutoff is sampled after expensive revalidation and
native/scope fsync/readback, and checked again after completion persistence.
Crossing a kickoff or status expiry rejects the generation; a persisted failed
completion is explicitly rejected on saved consumption. An orphan native file
cannot be completed later to manufacture a missed pregame observation.

Completed bundles retain first clocks and bytes on retry and revalidate their
sources, rows and current pointer; they are not new forecasts. Frozen games
require matching original contracts plus a source-revalidated completed original
bundle. Later injury/snap/projection metadata may evolve, but historical Top
eligibility is checked against its original selection-time metadata, not the
new injury status. Legacy selections retain their exact approved fingerprint
and structural checks, while their original selection eligibility stays
explicitly unverified. Outcomes and supported corrections continue to evolve.
Unproven new late players or changed frozen contracts fail explicitly rather
than silently acquiring a game-level verification claim.

The updater stages the existing recorded builder and capture/report work in one
isolated generation root. ROOT/OUT/CACHE/ARCHIVE/WEEKS and the ESPN athlete-cache
path are rebound together; the unchanged engine files are not edited. Required
evidence transfers create-only. Output promotion validates the complete binding
and restores old mutable files or prior absence on failure. Unreachable new
immutable assets and every retained original remain preserved. An abrupt crash
before durable evidence transfer is a recording gap, not permission to backdate
or reconstruct it. Restart verifies retained originals; saved PASS flags do not
qualify an incomplete bundle.

### Durable GitHub versus Pages contract

The selected durable destination is this EXISTING PUBLIC GitHub repository,
subject to separate approval of the actual generated contents. Its existing
staging lanes remain output/data, data/cache, data/forward, data/history,
data/verification, data/shadow, data/offers and data/outcomes. Required original
model inputs, exact plans/registrations, initial board/status, native/scope/
completion receipts, frozen origins, failed probes and rich reports are immutable
under the existing verification/evidence lanes. Clean exact-commit checkout and
source revalidation is the readback procedure. No private hosted store or ACL is
claimed; if required originals cannot be approved for this public store, a named
existing private destination and runner read/write access become a specific
owner dependency.

The optional 177-response transcript, mixed-sport full response and unrelated
diagnostic/news bodies remain local. They are not new mandatory inputs for this
narrow claim, and are not copied into a new encoding/destination. The retained
NFL offer observation is a scoped derivative bound to its original source
digest, not independent full-response authentication.

Pages receives a bounded staging copy of the existing output tree. It excludes
data/game-status.json, data/matchup-proof.json and data/matchup-diagnostics.json;
the GitHub originals are neither redacted nor made private by this exclusion.
The full rich scorecard is retained under verification/report-originals.
data/forecast-scorecard.json is `forecast-scorecard-public-summary-v1`: only the
registered rec/rush_att/pass_yd metrics, count coverage, identities and explicit
limitations. Rich rows/provenance, shadow and candidate records are not passed
through. Public-v2 selection assets keep the safe row field whitelist and lazy
250-row chunks. All retained old asset directories remain intact.

The explicit Pages inventory is the existing app/index/style/reliability/recovery
assets; week/meta/future/teams/track_record, archive/weeks, dk_backtest, public
scorecard/offer summary/health, selection-grading assets/latest, and the new
whitelisted verification-scope/release-identity sidecars. Unknown paths,
symlinks or scratch files fail staging. Health, source/app/shell, board/meta,
native receipt, scope and report bind one `website-generation-v1` identity.
The public scope exposes game identities/classifications and the narrow claim,
not internal manifests or raw bodies. Device My Picks never become model evidence.

### Versioned selection presentation

Local `selection-report-v3` maps only to `selection-public-report-v2`. The explicit
legacy local-v2/public-v1 path remains supported; pointer, row and outcome schemas
remain v1. No historical assets/receipts are migrated. New bytes receive new
content identities. Legacy summaries are labeled policy-unseparated, not given
newly inferred joint counts.

Headlines and desktop category table/mobile category cards use exactly the same
period/provenance/model/engine/policy-version-and-hash/cohort/checkpoint/source
context. Over, Under and Combined remain separate, with exact W-L and W/(W+L),
decided N, pending, push, confirmed DNP, unresolved and coverage. Zero decided is
Unavailable. No-side and NO_ACTION rows are coverage, not losses. Combined is its
actual saved aggregate. All-source groups retain all existing day/timing views;
exact-source groups contain only overall/category/category-side. Unsupported
source/day joints are unavailable, never reconstructed from marginals.

Actual first-recorded Top is distinct from Top at the all-lean decision; only
the latter and its recorded non-Top complement partition all-lean selections.
Chicago selection weekday, kickoff weekday and actual age/lead-time views remain
separate. Category order is stable. “Our selections by line source” does not
claim sportsbook accuracy. The separate historical season-average benchmark vs
DraftKings exposes only its saved rounded above/below rates and exact sample N,
never inferred exact W-L or financial claims. The registered three-target
numerical comparison retains its own eligibility independently of these filters.
All-twelve numeric/PPR/TD evaluation remains local and opt-in.

The unchanged reader bounds remain 12 MiB decoded summary/outcomes and 2 MiB per
row chunk, with at most four chunk fetches per interaction. Producers enforce
those bounds before advancing latest. Oversize or invalid later generations
preserve the working pointer. Measurements must distinguish gzip transfer,
decoded bytes, parse/validation, useful rendering, first rows and complete
optional drill-down; loopback Chromium/phone emulation is not public cellular
or physical iPhone/Safari evidence.

### Execution, review and release boundary

Stage 1 uses the ordinary authenticated manual lease for exactly thirteen
approved tools/tests/docs/app paths, with operational and display commits kept
separate. Only after normal result/release/full readback may the same actor use
the owner-approved NEW protected-source exception for config/phase2.json and
.github/workflows/hourly.yml, bound to the actual Stage 1 source/released state.
The unchanged controller does NOT validate that protected operation. No gate,
policy or readiness field is edited and no prior lease/exception is reused.

New experimental recording stays inactive through this cutover and rollover;
existing candidate evidence, formula/registration and Weeks 7–14 remain intact.
CLI-01 remains a limitation of frozen standalone candidate commands; the
supported native baseline reader remains the updater interface.

After final source review, one separately preauthorized local real-data attempt
may use the exact accepted code, still-valid plan and actual clocks/status. A
plan/contract/expiry issue stops that attempt; no exemption growth, polling or
backdating. All actual generated bytes remain local for artifact and GitHub/Pages
content review. Only then may one combined release approval cover current main
integration, approved persistence/updater activation, Pages, actual public Props/
Record/cache/My Picks/desktop/phone/loading checks and rollback. A source suite
or local certificate is not that release artifact.

Rollback restores only this checkpoint's fifteen source paths with forward
history, retaining all historical/new evidence and production data. Eventual
production rollback uses a current backup containing the successful PR #2 lean
presentation, restores the proper configuration through the same serialized
updater and verifies restored public identities and subsequent updates. Do not
reset history or merely redeploy old Pages over still-faulty source.

Parlay Builder remains later, unstarted work after this release: paper-first
2–6 legs (fewer/NO_ACTION allowed), exact saved contracts/membership/revisions,
one supported venue/product, privacy by default, separate leg/ticket states and
verified settlement/economics only. No gap-score probabilities, invented odds,
correlation-as-independence, forced tickets or wagering. PrizePicks, venue
expansion, injury/workload modeling and other optional features remain deferred.
The canonical roadmap remains in docs/EVALUATION_PROTOCOL.md.

PR #1 is the shared technical record. The existing hourly ChatGPT audit remains
the sole scheduler. The repository installs **no** second scheduler, webhook,
Codex API client or automatic dispatcher. Automatic implementation stays false
in config/handoff-policy.json. This is a cooperative writer gate and handoff,
not a claim that every possible GitHub writer is technically prevented.

## Verified connection and remaining owner step

The read-only handshake reached chatgpt-codex-connector[bot], which replied at
[comment 6159426861](https://github.com/NickNicky19/nicks-expert-nfl-picks/pull/1#issuecomment-6159426861)
that this repository needs an environment. It did not provide a cloud task/run
acknowledgement. The environment settings page redirected this session's browser
to sign-in; installed environments and their account/repo binding remain unknown.
No credentials, environment settings or permissions were changed.

Open [Codex environment settings](https://chatgpt.com/codex/cloud/settings/environments)
in your signed-in Codex account. Inspect/reuse an appropriate existing **legacy
integration-compatible** environment for NickNicky19/nicks-expert-nfl-picks where
the UI supports it. Verify the GitHub connection uses the intended account and
has access to this exact repository. A ChatGPT Work workspace/GitHub connector
is not by itself proof of that legacy environment binding. If none is compatible,
environment setup for the existing repo remains an owner step; do not create a
replacement repository, request an API key, or buy a service. Select Python 3.12
and Node 22 and install the existing requirements.txt for the offline checks.
Read-only handshakes need no new live collector access. Do not turn on another
automatic reviewer or implementation scheduler to work around the blocker.

Official [GitHub integration documentation](https://learn.chatgpt.com/docs/third-party/github)
states that ordinary non-review mentions start a legacy cloud chat; code review
is a different capability. [Legacy environments](https://learn.chatgpt.com/docs/environments/cloud-environment)
and [current Cloud](https://learn.chatgpt.com/docs/cloud) are separately documented.
Existing environments may be reused where compatible, but compatibility was not
verified here. Do not repeat the failed identical mention while this is unchanged.

## Durable single-writer transaction

The same GitHub repository has an append-only metadata branch,
coordination/phase2-writer, holding coordination/writer-state.json. Source
changes remain on the existing development branch. Initialization recorded the
known active manual owner; it did not declare other sessions idle. The metadata
branch retains its parent and all source/evidence files. Backups are untouched.

For a request, read fresh PR head, trusted GitHub comment, live state and exact
policy. Prepare a state commit with **one parent: that observed state commit**.
Move only the coordination branch using a non-force fast-forward. Two competing
sibling commits cannot both advance the ref. Verify remote commit and full state
readback before editing. A failed claim stops; never retry by reparenting it onto
the winner. No automatic timeout, takeover, reset, force-push or ref deletion.

tools/writer_gate.py implements this with existing Git authentication and public
GitHub comment reads; it does not ask for an OpenAI API key. For supported cloud
environments with normal Git push access:

```sh
python tools/writer_gate.py show
python tools/writer_gate.py claim --comment-id ACTUAL_REQUEST_COMMENT_ID
python tools/writer_gate.py check --run-id EXACT_RUN_ID
# Make only allowed bounded edits; test and publish normal development commits.
# Post/read back the final structured CODEX_RESULT, then:
python tools/writer_gate.py finish --comment-id ACTUAL_RESULT_COMMENT_ID
```

The connected GitHub API equivalent is: fresh state/PR read → pure transition →
create_tree with only the state-path change → create_commit with the observed
state as sole parent → update_ref with expected_sha and force:false → full
readback. Ordinary non-force server enforcement, not a check-then-write boolean
alone, rejects a losing sibling claim. Check the lease and exact source parent
again before each development publication; publish source with expected head
and force:false. Scope/ancestry is verified again before release.

Local process/staged files are not the lock. Tests exercise two isolated Git
writers racing on a real bare remote, input immutability, preserved staging and
history, author/origin checks, duplicate request and audit IDs, busy ownership
without expiry, stale head/policies, protected paths, default-disabled readiness,
attempt limits and exact result release. Remote probe readbacks are recorded in
the checkpoint evidence. GitHub-triggered native use of this gate remains
**unverified** until an actual connected task follows it; AGENTS.md instructs
all implementation entrypoints, but is not server branch protection. Leave
automatic implementation disabled while that condition is unverified.

## Explicit manual ownership and one-time bootstrap

The separately reviewed manual mechanism is `phase2-manual-writer-v1` in
tools/writer_gate.py. It is distinct from automatic implementation. The existing
automatic claim path retains its policy, readiness and structured audit checks;
automatic_implementation_enabled remains false. No native environment/task
readiness is asserted by a manual claim. All current protected paths, duplicate
request/review IDs, finding attempt limits, busy ownership without expiry, and
source-history/scope checks remain in effect.

An owner-requested manual entrypoint uses a new, unedited PR #1 comment, freshly
fetched from GitHub, with the exact numeric owner identity. A comment body or
display name supplied locally is not authentication. Verify the repository ID
and fresh PR head/repository/branch/status using GitHub metadata too. The
`audit_id` below identifies this explicit owner review cycle for deduplication;
it does not fabricate an independent AUDIT_REPORT or replace automatic audit
reference validation. Cite actual prior audit/handoff evidence in the prose.

```json
{
  "schema_version": "manual-writer-authorization-v1",
  "request_id": "UNIQUE_MANUAL_REQUEST_ID",
  "run_id": "EXACT_OWNER_REQUESTED_RUN_ID",
  "audit_id": "UNIQUE_OWNER_REVIEW_CYCLE_ID",
  "repository": "NickNicky19/nicks-expert-nfl-picks",
  "repository_id": 1411185749,
  "pull_request": 1,
  "branch": "upgrade/phase2-reproducible-comparison",
  "reviewed_sha": "EXACT_CURRENT_DEVELOPMENT_SHA",
  "coordination_sha": "EXACT_CURRENT_COORDINATION_SHA",
  "policy_version": "phase2-handoff-v1",
  "policy_sha256": "EXACT_POLICY_DIGEST",
  "evaluation_policy_version": "phase2-evaluation-v1.1",
  "timing_policy_version": "phase2-timing-v1",
  "gate_version": "phase2-manual-writer-v1",
  "gate_sha256": "SHA256_OF_EXACT_INSTALLED_WRITER_GATE_BYTES",
  "kind": "manual_owner",
  "approval": "OWNER_APPROVED_MANUAL_EXECUTION",
  "native_dispatch": false,
  "boundaries": {"main_writes": false, "merge": false, "deployment": false,
                 "model_promotion": false, "force_push": false},
  "scope": ["tools/scorecard.py", "tests/test_scorecard.py"],
  "finding_ids": ["A01", "A02"]
}
```

This is an example, not authorization. The actual comment must start with
`### MANUAL_OWNER_AUTHORIZATION`. The code verifies its GitHub origin, author,
body hash and unedited timestamps. Bind the exact invocation run, current
coordination parent, gate version/bytes and evaluation/timing versions. Require
owner_handoff_complete and rejection_tests_verified; preserve every readiness
value. Re-fetch authorization and PR target immediately before publication.
Use the existing one-parent, non-force transaction and full state readback, with
source-head checks before and after the coordination push. A drift after push
leaves the claim unusable and requires attention; never silently release/retry.
Each manual check, checkpoint and ordinary finish re-fetches the original
authorization and current PR target. Edited/deleted authorization or a
closed/stale target blocks checkpoint and ordinary finish publication. Checkpoint
and finish also re-read the result comment and bind coordination publication to
the observed source head before and after the non-force push.

After revocation, explicit `finish --safe-release` permits only owner-authored
BLOCKED cleanup at the last acknowledged source SHA, with no source advance or
changed paths and a clean worktree. It retains owner/run/result, gate digest, repository/branch/head
and state/readback checks. An unmerged closed PR is permitted for this cleanup;
it does not check the revoked authorization or authorize source changes.
Unknown source/state drift, a merged PR or another owner requires attention.

```sh
python tools/writer_gate.py claim-manual --comment-id ACTUAL_OWNER_AUTHORIZATION_ID --run-id EXACT_RUN_ID
python tools/writer_gate.py check --run-id EXACT_RUN_ID
# Bounded edits, tests, non-force development publication; check before publishing.
# Post/read back structured CODEX_RESULT for each checkpoint and at completion.
python tools/writer_gate.py checkpoint --comment-id ACTUAL_CHECKPOINT_RESULT_ID
python tools/writer_gate.py finish --comment-id ACTUAL_FINAL_RESULT_ID
# Explicit cleanup only, unchanged acknowledged source and BLOCKED result:
python tools/writer_gate.py finish --safe-release --comment-id ACTUAL_BLOCKED_RESULT_ID
```

The authenticated API equivalent must call the same claim_manual validation on
fresh server comment/repository/PR metadata; do not construct trusted metadata
from an arbitrary local body. The gate digest remains bound throughout the
lease. An independent exact-source check plus actual manual claim/readback
demonstration is required before resuming Phase 2 repairs. A marker alone is
never permission, and AGENTS.md is still not server branch protection.

Bootstrap cannot be performed under a lease that does not exist. The owner
must first approve the proposed patch, manifest and one-time controller by
digest, pin source and coordination SHAs, name the sole bootstrap actor and
authorize exactly four infrastructure paths: tools/writer_gate.py,
tests/test_manual_writer_gate.py, docs/IMPLEMENTATION_HANDOFF.md and AGENTS.md.
The protected AGENTS.md edit is an explicit one-time exception, not a new
permission for ordinary manual claims. No policy/config/evidence/workflow or
production edit belongs to this exception.

Only after that approval, record/read back a trusted structured
BOOTSTRAP_WRITER_GATE_AUTHORIZATION with the exact artifact hashes and bases.
The separately reviewed external pure controller may reserve the existing
coordination ref with kind bootstrap_reservation, exact patch/manifest/body
digests and reserved_source_sha. It deliberately omits source_head: old gate
checks cannot mistake it for a lease, and all ordinary claims see BUSY. Publish
as one non-force sibling with the observed parent and verify full readback
before installing the exact approved patch. No competing source writer, expiry
or takeover is authorized. The controller is not installed as a recurring
repository entrypoint or scheduler.

Publish only the approved source tree with one parent, the pinned source SHA;
preserve all other bytes/refs. Record the installation on the reservation while
running exact-head checks and independent verification. A freshly read-back
CODEX_RESULT and proven exact tree/parent alone do not permit reservation closure.
Closure also needs an actual independent exact-source AUDIT_REPORT and separate
explicit owner acceptance, each authenticated and bound by comment ID, origin,
body digest, unedited timestamps and reviewed SHA. Do not
convert the reservation into a manual owner: close it, then acquire/read back a
fresh explicit manual authorization against the actual installed source and
current coordination SHA. No Phase 2 repair edit is allowed before that step.

On failure before source publication, report BLOCKED and explicitly close only
this reservation against the unchanged source. After publication but before
reservation release, the approved rollback is one ordinary code-only revert of
those four paths to their pre-bootstrap bytes, parented to the recorded install;
retain the failed commit, all evidence, backups and coordination history. The
external controller verifies the original tree and exact rollback parent before
closing as BLOCKED. Unknown source/state drift or another owner means retain the
reservation and stop; no reset, forced ref update, expiry or deletion. A rollback
after reservation closure needs a fresh exact-head authorization/reservation
and cannot interrupt an active manual owner. Automatic implementation stays
disabled throughout bootstrap, manual use, abort and rollback.

An existing exact-patch reservation cannot authorize an amended patch. For the
G01/G02 remedy at 43099c1, obtain a new owner-approved, digest-pinned correction
authorization before any source or coordination change. The proposed external
controller retains the same bootstrap owner/run/reservation and records its
previous metadata; it replaces the permitted artifact pins without release or
an implementation lease. The original controller then rejects the superseded
artifact pins. Read back the exact one-parent, non-force state transaction before
installing only the new approved three-file tree with parent 43099c1.

Record the corrected install while holding the reservation. A new structured
`manual-gate-audit-v1` report must identify the exact source/tree, repository ID,
branch, policy/evaluation/timing versions, correction manifest/controller/gate
digests and G01/G02 PASS findings. Closure additionally requires a separately
owner-approved `manual-gate-review-acceptance-v1` comment referencing that audit's
full metadata, with `independent_review_confirmed:true`. Bind both actual comments
in the final CODEX_RESULT. Re-fetch all evidence and exact repository/PR/source/
state immediately before publication, use source-bound non-force coordination,
and verify full readback. Missing, edited, rejected, stale or unaccepted audit
evidence leaves the reservation held. Correction-plan approval authorizes the
patch only; it does not preapprove the later audit acceptance or release.

The corrective code-only rollback restores those three paths to their 43099c1
bytes in a new commit parented to the recorded corrective install. It retains
the reservation as BLOCKED, the failed correction, bootstrap and all evidence.
43099c1 remains unpassed after rollback. Restoring pre-bootstrap 9c02617 or
releasing a failed reservation requires a separately pinned owner procedure;
there is no reset, force update, history deletion or automatic takeover.

This is a cooperative gate. Delegated owner credentials can author owner
comments, and direct repository writes can bypass local checks. Comment
authentication proves GitHub identity/origin, not a separate human decision.
The owner must confirm independent review in a separate decision after reading
the actual report. No server permissions or branch protection is changed here.

## Automatic structured request and audit contract

The trusted owner is GitHub login NickNicky19, numeric ID 208912933, type User.
The marker alone is not trusted. Fetch actual metadata/body from GitHub; require
the expected PR URL, unedited timestamps and exact source/policy versions.
Read-only probes use empty source scope; they never authorize edits. There is
no automatically posted implementation request in this checkpoint.

A future HANDOFF_REQUEST starts with `### HANDOFF_REQUEST`, with one JSON block:

```json
{
  "schema_version": "implementation-request-v1",
  "request_id": "UNIQUE_REQUEST_ID",
  "run_id": "UNIQUE_RUN_ID",
  "audit_id": "EXACT_AUDIT_ID",
  "repository": "NickNicky19/nicks-expert-nfl-picks",
  "pull_request": 1,
  "branch": "upgrade/phase2-reproducible-comparison",
  "policy_version": "phase2-handoff-v1",
  "policy_sha256": "EXACT_POLICY_DIGEST",
  "evaluation_policy_version": "phase2-evaluation-v1.1",
  "timing_policy_version": "phase2-timing-v1",
  "reviewed_sha": "EXACT_CURRENT_DEVELOPMENT_SHA",
  "kind": "implementation",
  "scope": ["tools/timing.py", "tests/test_timing.py"],
  "finding_ids": ["EXACT_FINDING_ID"],
  "audit_comment_id": 0,
  "audit_body_sha256": "EXACT_REFERENCED_AUDIT_BODY_DIGEST"
}
```

This is a format example, not an authorized request. The referenced AUDIT_REPORT
must itself contain one structured JSON block with schema_version
implementation-audit-v1, audit_id, repository, pull_request, reviewed_sha and
finding_ids, plus human-readable reproduction evidence. The consumer fetches
both comments, binds body hashes and verifies the requested findings are present.
Legacy free-form reports remain useful manual feedback but do not satisfy an
automatic claim. No raw comment commands are executed by the gate. Two attempts
on a finding consume its budget; another needs owner attention or a newly
evidenced, owner-approved plan, not a loop resetting IDs to evade the limit.

## Round trip and automatic-readiness boundary

CODEX_RESULT is posted and read back. The **existing** audit then posts its
SHA-specific AUDIT_REPORT, and the manual owner reads it, reproduces actionable
findings before fixes, posts an acknowledgement with each finding's status and
reads that acknowledgement back. Record all comment IDs, body digests, SHAs and
actual scope. An audit requested asynchronously is not proof it completed.
This report transport demonstration is distinct from the still-blocked connector
bot acknowledgement and native implementation serialization.

Before enabling a later version: all owner work safely committed/handed off;
compatible environment and genuine native task reference verified; native task
and every manual implementation entrypoint shown to claim/read back the gate;
duplicate/busy/stale requests rejected; one existing dispatcher retained; and
report → audit → acknowledgement readback demonstrated. All current readiness
fields and blockers are visible in the live state. Never enable by flipping a
flag merely because tests passed or a bot reacted. No merge/deploy/promotion is
authorized even after transport and ownership are verified.

## Safely preserved next implementation stage

config/timing-policy.json and docs/TIMING_PROTOCOL.md preserve the proposed
separate phase2-timing-v1 study, explicitly REGISTERED_NOT_IMPLEMENTED. There
are no timing decision receipts, timing metrics or timing UI claims yet. The
primary experiment/registries, output/data/forecast-scorecard.json and all older
evidence remain unchanged. The next approved bounded stage is the timing
recorder, NO_ACTION/coverage/matched report, Chicago/DST attribution tests and
accurate About display. It must use genuine new checkpoint observations; never
backfill old captures as prospective policy decisions. Economics stay
unavailable without complete verified venue/ticket records. Confirmatory
evaluation requires genuinely later games. The existing Phase 2 implementation
and its original validation remain reviewable; this handoff is not an audit pass.

## Checkpoint evidence and a reproduced build blocker

At source 2887d6e13a3f14d2efb0d65a48d6d733d08a7cd6, 123 Python tests, 8 UI
helper assertions and 11 About assertions passed locally and in exact-head CI
38503503889 / 38503500421. Metadata-only requests read back from actual PR
comments were rejected against live state: duplicate (6159953021), busy
(6159953174), stale source (6159953361), stale policy (6159953503). No native task
was invoked. Actual GitHub sibling candidates shared parent f539f4fe3605b1e72dd8749712b68a484edb4d69;
winner c17cb097bd5b1655cb385277c1e99db230044efa advanced the ref, while sibling
1b164320ee1d760c20816ed5859d4f078125fad2 was rejected with force:false as
"rejecting non-fast forward update." Remote winner/owner/source readback matched.
Both rollback routes were rehearsed in an isolated clone and retained 69
tracked data files, all three current policies, coordination ref and Git history.

**The committed static Week 6 build does not pass the offline verifier.**
`python tools/verify.py --offline` exits 1 because output/data/matchup-proof.json
is absent, including at pre-extension 8fc1fb2. Its output hash is
6e2721c8ffa524621ba22384d070295ed6c3d2ccd9a5f5cc2ba5eb1fe3ef851d, generated
2026-10-14T01:10:09Z. None of the four exact input snapshots matches it. The
diagnostic refetch is not original proof. Previous live integration results
refer to the separately recorded local builds; they do not verify this committed
snapshot. Unit/CI success does not override the failed build gate.

Leave this failing case visible. Before a release, an authorized recorded build
must establish its own matching output/proof; do not fabricate a historical
pointer, refetch proof retroactively, weaken checks or overwrite older decisions.
Frozen games lacking original proof remain blocked. No collector or deployment
was run for this handoff. The timing recorder/report is still the next bounded
stage, and native environment/gate adoption and audit round-trip delivery remain
separate readiness requirements. See the append-only CODEX_RESULT checkpoints
and data/verification/reports/handoff_validation_20261014.json.

### Bounded summary and outcome partitions (capacity checkpoint)

`selection-publication-pointer-v2` selects the explicit public-v3 storage layout;
legacy pointer-v1/public-v1 and public-v2 readers remain supported. The local
selection-report-v3 contract, decision IDs and semantic summary IDs do not change.
The publisher reconstructs **all** partitions and rows, then applies the retained
complete semantic validator before the caller can atomically advance `latest.json`.
A missing, corrupt, oversized or inconsistent non-default partition also fails
producer validation. Failure preserves the previous coherent pointer with its real
clock; it does not make that saved generation current.

Summary contexts bind provenance, model, engine, timing-policy version and hash,
cohort, checkpoint and line-source scope. Each summary partition binds one exact
context and reporting period (weekly or cumulative). Outcome partitions bind one
season/week and retain complete game/player/category/team/kickoff identities.
Indexes carry report ID, context/period, exact byte hashes, decoded sizes and group
or outcome counts. The new logical report ID includes the versioned layout
 discriminator; original row positions, 250-row chunks, membership hashes and all
counts/rates/sample context remain exact. Changed representations never reuse an
older publication identity.

The fixed limits are 1 MiB for the pointer and each index, 12 MiB per summary or
outcome partition, 2 MiB per row chunk, 250 rows per chunk and 4,000 chunks. These
are failure bounds, not targets to increase as data grows. Indexes retain safe
`<logical-report-id>/summary.json` and `outcomes.json` paths. Partitions use
`<sha256(actual-part-bytes)>/summary.json` or `outcomes.json`; their payload still
binds the logical report. This fits the unchanged strict Pages staging allowlist;
GitHub evidence and excluded original input files retain their existing paths and
bytes. No new raw responses, device selections or private manifest fields are
published.

The browser initially loads both indexes, the selected exact-context summary and
only the current board's required outcome period. It does not prefetch every
context. Other contexts load on demand; each table still contains its complete
membership and counts, independent of drill-down pagination. Publication and view
revision checks prevent delayed responses from replacing newer filters or clearing
a newer generation. Immutable v3 assets may use the normal browser cache; the
latest pointer is revalidated. The shell cache identity advances from v53 to v54.

Current My Picks remains current-week-only, with unchanged device storage and
saved-line grading. Full outcome keys prevent another week's result from settling
a current contract. Historical game views retain their existing saved-board-stat
path; this checkpoint adds no historical My Picks interface. Unavailable outcomes
remain unknown, never an inferred zero or DNP. All-twelve numerical/PPR/TD analysis
remains local and opt-in. Forecasting, selection policies, strict verification,
partial plans and candidate registration are unchanged.

A code-only forward rollback preserves every immutable old/new asset. At the
current under-cap dataset the old publisher can regenerate a legacy pointer, and
the unchanged Pages allowlist can retain the v3 assets. Above the old monolithic
cap, restoring the old publisher cannot promise continued complete reporting.
Before production release, larger-data rollback must explicitly retain compatible
partition publication support, or receive approval for the limited Phase 1 fallback
with truthful unavailable/previous/stale grading status. This source scope does
not alter protected configuration or implement that fallback. The production
backup must include PR #2 and preserve all intervening evidence and My Picks.

Capacity stress fixtures duplicate report shapes into fictional weeks; they are
storage tests, not new football samples or evidence of predictive improvement.
Browser loading measurements are local Chromium emulation under documented cache,
compression and network conditions, not public cellular or physical iPhone/Safari
acceptance. Visiting every context can increase total requests and compressed
bytes. Exact measurements and rollback evidence belong to this run's CODEX_RESULT.
The old Week 6 full-board missing-original-input failure remains a failure; partial
original-model-input reproduction is not full-week qualification or accuracy proof.
## Owner-approved bounded hosting contract — 2026-10-18

This contract is frozen before implementation under
NFL-WEB-HOSTING-SOURCE-20261018-202256Z, starting at
4efbca6559203e23af5e34a91132a71c74195e95. The eight-file scope is packaging only.
The genuine five-game capture, original release identity, health and every
input/native/scope/completion/report byte remain unchanged in the original local
package. There is no new collection, forecast, candidate or exemption.

### Encoded report contract

The explicit new pointer is selection-publication-pointer-v3, the summary index
selection-public-report-v4, and the content discriminator gzip-context-period-v1.
Legacy pointer v1/v2 and public v1/v2/v3 readers remain explicit and unchanged.
Summary/outcome root indexes stay plain JSON. Individual summary partitions,
outcome periods and 250-row chunks use deterministic application gzip with empty
filename, mtime zero, level 6. Payload filenames remain narrowly allowlisted JSON
names; encoding is declared, never inferred from HTTP headers or a suffix.

Each compressed descriptor retains path, decoded sha256 and decoded_bytes and
adds encoding:gzip, encoded_sha256 and encoded_bytes, alongside its exact
context/period/count. Physical part namespaces use the encoded hash; row chunks
remain under the separately identified new report. Both encoded and decoded
sizes/hashes are mandatory. Stream reads stop before exceeding declared sizes
or existing caps: pointer/index/manifest/archive shard 1 MiB; summary/outcome
partition 12 MiB; row chunk 2 MiB; 250 rows and 4,000 row chunks. Complete producer
reconstruction validates every part and exact rows/members/counts before latest
can advance. No corrupt modern object may fall back to a legacy reader.

Fetch removes HTTP content coding. The delivered body must still equal the
declared encoded application bytes before one application decompression. Thus
outer HTTP gzip(application-gzip) is supported; incorrectly labeling stored
application gzip as HTTP Content-Encoding is an explicit integrity failure.
Feature-detect streaming/decompression support and show unavailable without
touching My Picks if absent. Enforce delivered and expanded limits while
streaming, before unbounded buffering or JSON parsing.

### Complete generations and archive retrieval

Immutable selection-hosting-generation-v1 manifests retain the exact report
pointer, source/capture identities, actual packaging clock and immutable public
board/meta/scope/scorecard/health/release-identity snapshots. The bounded
selection-hosting-working-set-v1 pointer hosting.json selects latest and one
previous SUCCESSFUL COMPLETE generation, not two weeks. A same finalized retry
does not rotate. Every cumulative week remains in each complete report.

Archive metadata is split by the first hex digit of the exact pointer digest into at most
sixteen independently hash-validated, 1 MiB plain shards. Entries bind the exact pointer digest and report ID,
immutable manifest path/hash/size and the exact Git commit that actually contains
that manifest and its complete assets. New generations cannot invent their
future generated-data commit. A prior generation is archived only after reading
every required blob at an already-existing commit and matching actual bytes.
Stage fully validates latest and previous graphs and proven archived backing
before omitting an older generation. GitHub retains all originals/assets; Pages
copies only the two reachable graphs, archive metadata and existing public static
allowlist into a fresh directory. No evidence or older asset is deleted.

An old open browser may resolve its exact report ID through current bounded
archive metadata, then fetch only required assets from the hardcoded existing
public repository at the verified immutable Git commit. Validate original
descriptor hashes/context/generation again. Never substitute current totals or
outcomes, clear storage, or retry indefinitely. Controlled two-origin tests must
exercise CORS/content types and A-to-B-to-C-to-D fictional committed archives.
Do not claim an unseen real remote archive URL exists.

The conservative complete staged-file budget is 900,000,000 bytes, below the
documented 1 GB Pages maximum. Check all files and actual uploader tar separately
before staging succeeds. Failed/missing/oversized updates preserve the last
coherent pointer and truthful clocks/status. Whole-tar gzip is diagnostic only.

### Packaging-only descendant and recovery

Ordinary new captures retain website-generation-v1. A repackage of saved evidence
uses website-packaging-generation-v1 with distinct actual packaging source/time,
original capture generation/source/clock, unchanged board/native/scope/completion,
and exact new app/shell/report bindings. Required original generation/health/
pointer evidence is create-only in the existing verification lane. Validate
original capture independently, including original source app/shell bytes from
retained Git history; then validate the derived generation. Never spoof
GITHUB_SHA, rewrite original receipts, or imply newer code captured old inputs.
Only derived copies receive new health/release identities.

Recovery retains this versioned reader/writer/staging compatibility and may
forward-pin/recover a fully validated retained generation before subsequent
ordinary updater runs. It must preserve all latest/previous/archived evidence
and the deployed PR #2 presentation. A blanket source rollback to the old
monolithic publisher is not oversized-data recovery. Any limited Phase 1 fallback
would lose current expanded reporting and still needs explicit protected release
permission; it is not implemented here.

Measure complete current/3/6/18-week and changed-generation staging plus
repository working-tree, immutable file, Git pack and full-depth clean-checkout
growth. Synthetic fixtures are storage tests, not football evidence. Neither
compression nor a bounded Pages working set establishes unlimited GitHub archive
capacity. No season-long operational claim without measured repository/hosting
support. Source, original-evidence, artifact, both GitHub/Pages disclosure and
combined release approvals remain separate.

Contract clarification during implementation: registry/archive keys are the exact
canonical pointer digest, rather than semantic report ID, because a later complete
generation can retain report content while having its own clock. Each immutable
manifest also references a create-only hosting-generation-proof receipt in the
existing verification lane. This retains that generation's exact proof without
publishing it to Pages or borrowing a newer mutable proof. The staged working-set
pointer has a separately hashed delivery form; its archive pins are generated
only AFTER the actual data commit exists and its public commit/tree is read back.
The stored source form has no archive pins and no claimed public delivery hash.

Implementation validation details: each staging operation fully validates each
exact pointer graph at its source and again in the fresh destination. An
operation-local cache avoids repeatedly decoding that same immutable graph;
it is discarded after the call, and a later call rechecks changed/corrupt bytes.
The first migration seals the existing coherent plain generation before alias
replacement, so the first working set includes that previous complete report.
Its plain assets remain supported until they rotate to the verified Git archive.
An already encoded identical saved app/report is a validated no-op, not a new
capture or manufactured packaging source identity. Original JSON pointer bytes
retain their original canonical serialization without adding a newline.

The conservative complete-stage budget is also checked before copying each
allowed file; a 900,000,001-byte sparse negative control is rejected without
materializing that oversized payload. Metadata is included in the final total.
This negative storage fixture is not a forecast or a valid historical board.
Recovery requires a reviewed partition/gzip-capable source floor. Reverting
these eight paths to 4efbca65 alone is not a functioning modern-report recovery.
A limited Phase 1 fallback would require separate explicit permission for its
configuration/dispatch and honest unavailable/stale grading capability; it is
not implemented by this source checkpoint. Primary evidence and all report
copies remain retained in Git, whose measured growth is a separate operational
budget and cannot be certified by the two-generation Pages size alone.

The fresh public stage explicitly sets 0755 directories and 0644 files,
including its atomically written delivery pointer, independent of local umask.
Original capture/repository permissions and bytes are untouched. The first
fictional tar probe's 0600 metadata failure remains in the local evidence.

The unchanged hourly workflow records its two advisory-step outcomes after
capture. The retained health snapshot is the health at qualification time;
`legacy_verifier` and `historical_comparison` alone may later acquire a normal
GitHub step outcome (success/failure/cancelled/skipped). All other health fields
must match exactly, including capture/source/board/report/generation identities.
This append neither rotates report generations nor upgrades a failed advisory
or original proof. Tests execute the actual existing health-recording block.

Browser scope labels match a packaging generation's explicit capture source,
while checking the new packaging source/time against health separately. They
do not relabel the retained selection report as newly captured by packaging.
A wrong capture-source binding suppresses the verification claim.


## 2026-10-20 presence/identity correction — source checkpoint

The approved previous documentation delta is preserved verbatim above. Its
standalone resulting document has SHA-256
`3b560f3e5308c18836b5410151a7145de33bf41ab9f72062717b6a6df9edc790`.
This appendix creates a new document identity; it does not relabel that file.
The original proposal is preserved unchanged; owner-reviewed amendments add
`tools/release_mode.py` and reserve `matchup-inputs-v3` for new semantics.
The amended implementation scope is 27 paths: 22 ordinary and five protected.

### Closed version dispatch

| Role | Original retained contract | Presence-aware correction |
| --- | --- | --- |
| Model | original_sleeper_matchup_baseline | sleeper-matchup-data-integrity-v2 |
| Inputs | matchup-inputs-v2 | matchup-inputs-v3 |
| Proof | matchup-proof-v1 | matchup-proof-v2 |
| Native | baseline-capture-v1 | baseline-capture-v2 |
| Numeric outcomes | forecast-outcomes-v1 | forecast-outcomes-v2 |
| Local extended outcomes | descriptive-statistic-outcomes-v1 | descriptive-statistic-outcomes-v2 |
| Derived comparator | earlier immutable scorecards | forecast-scorecard-v2 |
| Private scoped validator | original partial-week contract | partial-week-data-integrity-v2 |
| Private fixed plan | original approved plan | partial-week-data-integrity-plan-v2; separate approval required |

The new helper closes its source manifest over actual implementation bytes.
Unknown source/schema combinations fail; the original seven-blob map, scoring
identity, strict/partial validators, candidate module, registration and policies
are unchanged. Full Git history supplies the actual original implementation
and dependencies in a separate source/process namespace. Current code is not
allowed to impersonate an original engine by using an old label. Existing public
selection/pointer/gzip formats remain unchanged, including the bounded prepared
publisher and fresh complete dependency checks. Public scoped labels use the
existing narrow public projection; private receipts retain new version identities.

Reported zero, supported inferred sparse zero, explicit unknown, invalid value
and unsupported absence remain distinct. Actual source rows retain modeled
null/zero/value fields and their attributed presence context. The sparse-zero
convention remains a labeled legacy adapter assumption, not independent provider
completeness authentication. A label, HTTP success or participation alone is not
proof of omission semantics. A modern attributed played row must match its saved
original modeled fields and valid participation. Original lossy caches stay
unchanged and cannot reveal whether an old omitted value was originally null.

Projection components remain separately retained before rounding. Unknown direct
provider PPR does not remove known sibling forecasts. Component-derived offensive
PPR, combined yards and rushing-or-receiving TD expectations require complete
components; a known direct provider total does not fill missing components.
Fractional projections, signed yardage and valid negative/fractional PPR are
preserved. Invalid actual count components cannot cancel into a plausible total.
Invalid optional components and contradictory joins quarantine the affected
comparison rather than erase valid siblings, manufacture DNP or count a loss.
Nonfinite invalid components use a JSON-safe typed representation and a distinct
model-input hash contract; they do not masquerade as null or valid zero.

Primary, all-category and recorded-selection consumers independently check
season/week/game/player/category/team and supported kickoff bindings. A true
schedule change is distinct from an identity error. Existing supported corrections
and conflicting frontiers retain their original receipts. Any new interpretation
gets its own derived identity and explanation. Conditional reproductions are not
proof that a lossy historical cache actually underwent a null-to-zero incident.

Existing original-version observations can be read/evaluated using their retained
source. A genuinely new original-version observation must execute the original
implementation. Corrected observations use the new source and cannot enter the
original registered primary or rec-half experiment. Operating that candidate is
a fourth separate decision. Its formula, registration and Weeks 7–14 do not move.
Both experimental recorders remain inactive; no new builder/collector is activated.
The direct shadow join remains `KNOWN_UNGUARDED_JOIN / NOT_CERTIFIED`, with only
supported original inputs and no qualified public accuracy, complete-week or
promotion claim. Offer parsing, provisional-live display and broader coherence
research remain deferred beyond connected PPR/TD completeness presentation.

The release selector recognizes only the explicit corrected model/validator pair
with inactive experiments; this is not artifact qualification. Legacy enabled/
disabled behavior, recovery modes and CLI outputs remain supported. Unknown
models, invalid booleans, incompatible validators and challenger enablement fail.
Configuration, activation plans and all current operating settings stay unchanged.

The original review archive and its scoped independent review remain completed
for their exact bytes. Production frozen selections and separate genuine local
observations remain distinct. No proof is attached to a different contract.
The old strict Week 6 missing-proof failure remains expected. Source correctness
is separate from operating, artifact, disclosure and deployment approval.

The earlier 960.625703-second local planning result remains a FAIL against the
unchanged 960-second target; the job timeout remains 1,200 seconds. Changed source
does not inherit that runtime or memory result. No hosted campaign, new provider
request, real-data package, production merge, deployment or experimental activation
is performed by this source checkpoint. The future final-source operating campaign,
production-rooted artifact/content review and combined release/public/cache/My Picks/
compatible-recovery decision remain separate. PR #2 and its owner-reported limited
phone/My Picks confirmation remain preserved. Physical Safari was not retested.



## Connected reporting and paper-builder checkpoint — 2026-10-22

Status: implemented and locally checked; exact final push/PR test-merge status is
recorded in the checkpoint result; operating-qualified: no; Phase 2 deployed: no.
This is the sole owned nineteen-ordinary-path development operation. Public
Phase 1 and the separate daily-cadence checkpoint are not the new report release.


The new source/report contracts are `selection-report-v4` and
`selection-public-report-v6`; pointer-v4 shared application-gzip storage and its
existing caps remain unchanged. Legacy public readers remain explicit; unknown,
mixed or corrupt modern evidence cannot fall back to a legacy reader. Exact
category/side/source/strategy/selection-day/kickoff-day/lead-time comparisons use
their saved joint memberships, never products of marginal percentages. The two
new ranked cohorts are prospective under their separate registry; existing
Biggest-lean/Projected-points display sorts do not become historical selections.

The aggregate accuracy contract covers the ten numerical categories, offensive
PPR and anytime TD, split by actual model/engine/outcome provenance. Paired
numerical MAE/RMSE/bias and TD Brier/log-loss/descriptive bins remain separate
from selection hit rates. Coverage, unavailable values and rederived probability
provenance are explicit. Rich evaluation rows remain outside the public aggregate;
software-test outcomes do not establish predictive improvement or a best day.

Local Chromium checks completed at 320, 390 and 1280 CSS pixels: 120 paper-ticket
checks, 102 control-readability checks, 14 historical asynchronous-state controls,
seven invalid modern/legacy accuracy cases, and 368 presentation-preservation
checks. My Picks bytes, personal lines/scoring, rankings and saved historical
identities were retained. Fictional HTTP/clocks and controlled transport are
explicit test boundaries; no physical iPhone/Safari or new public release was
tested. An unsupported gzip decoder gives an unavailable report state. Paper
tickets remain private by default and statistical only, with distinct leg/ticket
states and immutable revisions; no accepted venue payout, probability, EV or ROI
is inferred.

A fixed 36-load Chromium comparison used 4 Mbps down, 1 Mbps up and 150 ms
latency, no CPU throttling, consistent HTTP gzip and the same legacy fixture.
The new app increased cold HTTP body transfer from 141,683 to 154,025 bytes
(+12,342, 8.71%); the modern fictional aggregate/joint fixture used 157,010 bytes.
Those totals include required static/board/health assets, pointer, both indexes,
selected summary and initial outcome partitions, not just index size. Returning
network bodies were about 6.5 KB while logical cached content remained counted.
Useful first-render ranges were 2.415–2.434 seconds for the baseline,
2.437–2.445 for the matched new app and 2.436–2.464 for the modern fixture.
Fifty-four filter changes and eighteen complete 305-row drill-downs reconciled;
complete drill-downs took 0.856–0.971 seconds. These small controlled results do
not qualify real-sized provider/updater, hosted, physical-device or season-long
performance, and the increased bytes are not described as an improvement.

The retained full local run at `115c89fd` executed 624 Python tests in
1,950.694 seconds, with one failure and three errors. Tracebacks identified
legacy fixture clocks crossing the new registry, data-only fixture Git heads
being mistaken for executed application source, and one missing fixture parent
directory. The fixture corrections preserve old assertions and use explicit
pre-registration clocks plus the actual executed checkout identity. The four corrected cases then passed in a focused run with the original
assertions retained. Active strategy proof/registry checks remain independently
strict. All five active
strategy integrations in that run, including current-format forward recovery
and two later mocked updater/staging runs, passed. Earlier failed/interrupted
runs remain evidence; exact final-source suite/CI outcomes are recorded in the
checkpoint result, not attributed to an earlier or different checkout.

The local suite is retained check cost, not an updater or hosted operating
measurement. Its per-child high-water maximum was 979,184 KiB; this is not an
attributable aggregate process-tree peak. Existing 960-second planning and
1,200-second job limits and prior misses stay unchanged. No full admitted
representative seed or final-source hosted operating qualification exists.
Compatible recovery requires a source that reads/generates public-v6 and current
ranked evidence; restoring an older reader is not a functioning rollback. The
local forward rehearsal preserves evidence but does not establish a twenty-minute
operational recovery or remote transport.

Remaining release gates are current-main integration, the supported finite
operating envelope, production-rooted artifact and exact public-content review,
and the combined approved deployment/public Props/Record/cache/phone/My Picks/
compatible-recovery verification. The independently reviewed original archive
remains complete for its exact bytes; later artifact deltas have their own review.
No provider capture, historical strategy backfill, production contract overwrite,
new real-data publication, model promotion or experiment activation is performed.

An interrupted-process negative control exposed canonical ranked-completion
issuance before expensive validation in local intermediate `257e93ad`. The
finished helper validates the complete provisional payload before issuance,
samples actual completion time afterward, and retains bounded exact readback
plus the final persistence cutoff/failure marker. All 17 ranked unit checks
passed, including hard interruption and kickoff crossing during validation.
Saved consumption still validates fresh original/source/policy/clock evidence.
Interrupted provisional work leaves an ineligible orphan; genuinely completed
work remains usable if only later report publication fails. The initial probe
mocked original/source qualification while exercising actual immutable writes,
hard exit and fresh decisions; it is not original-capture authentication.
No accepted frozen-origin helper, engine, original receipt or public physical
format is changed by this completion-order correction.


## Source-CI and integration completion boundary — 2026-10-22

The accepted application/reporting source at `7f403b1` remains the baseline.
Its exact-source CI passed 624 Python tests plus syntax, 187 UI and 15 About
checks. The retained suite step took 1,132 seconds and the whole CI job 1,146
seconds; these overlap and are not added. This is below 1,200 seconds but the
suite alone exceeds the 960-second planning target, before updater dataflow.
The earlier 960.625703-second and 1015.945480-second observations remain separate
historical misses. No operating qualification follows from correctness CI.

The execution-boundary correction keeps the complete regression suite in
Reliability tests. A completed successful source-check run must bind the actual
code, tests, workflows, configuration, static assets and dependency inputs, plus
the retained data fixture directly consumed by the tests. The updater freshly
reads the actual tracked path/mode/blob/content inventory and installed runtime
bytes; changed, missing, untracked or corrupt source, helpers, fixtures or
dependencies cannot inherit a previous result. A requirements-file checksum,
commit name, mtime, pathname or stored PASS is insufficient.

A final CI seal is emitted only after the complete mandatory checks. Reuse
requires authenticated repository/workflow/run/job/attempt identity, actual
source ancestry and byte-equivalent inputs, successful ordered steps, an intact
bounded log seal and matching installed toolchain/dependencies. Normal merges
with identical verified source inputs are supported; unrelated source is not.
The helper hashes installed package files, Python standard/dynamic modules,
the shared interpreter and executable toolchains. Fresh, empty per-invocation
bytecode namespaces and closed import/loader overrides prevent unchecked
bytecode from inheriting source trust. Sourceless bytecode and executable files
inside data directories cannot hide as mutable data. The complete workflow-run
inventory is bounded at 1,000; overflow or unavailable logs fail closed. Latest
attempt execution, including a later failed rerun of an older run, takes
precedence over an earlier success. Changes require renewed full source CI.

The source-check evidence qualifies static source checks only. It does not
qualify a generation, authenticate an original capture, establish freshness, or
provide an operating-budget result. Missing, expired, failed or incompatible
CI evidence makes the source gate unavailable; it never enables a legacy
qualification fallback. Runtime changes require renewed full source checks.

Every Phase 2 update still performs the actual recorded build and explicit
verification route, source/input/native/clock/scope/completion checks, exact
report reconciliation, coherent-generation verification and independently
checked Pages staging. Source is freshly checked again at publication
boundaries. Phase 1 and explicit recovery retain their existing routes. No
forecasting formula, original validator, policy, experiment, daily cadence,
concurrency protection or 20-minute updater timeout is weakened.

Source-change CI, source-evidence retrieval/verification, ordinary updater
dataflow and final publication each retain their real clocks and costs. The
full suite has moved to a source-change acceptance boundary; its work is not
described as eliminated or hidden outside total source-change release cost.
Later operating samples must include their actual setup, evidence retrieval,
restoration, fresh validation, one update, packaging and cleanup. The former
full-suite measurement is not reused as a changed-source runtime qualification.

Current-main integration must retain every already-public main data file and
all development evidence. The seed-workflow add/add conflict is resolved by
retaining the full guarded manual-only installed workflow, not by dispatching
it. The exact inherited data and protected workflow scope are recorded outside
the ordinary writer lease; the ordinary controller does not validate that
protected operation. Ticker remains retired and the daily Chicago schedule
remains unchanged. Actual current-base integration CI is required.

Completion status is kept in the single existing handoff: IMPLEMENTED,
INTEGRATION-TESTED, OPERATING-VERIFIED and PUBLICLY VERIFIED are separate.
Source integration and deployment proceed under the owner's completion
authority through current gates, accepted artifacts and normal protections;
no historical authorization is rewritten. Artifact storage/cost facts remain
a distinct operation-specific prerequisite. No additional spending or new
private-data publication is inferred.

The first integrated `38ef48b` push CI rejected an installed dependency outside
the helper's initially supported interpreter namespace before the suite ran.
That failure remains recorded; it is not a model, data or operating-budget
result. A bounded package-relative diagnostic identifies the actual layout
without publishing resolved workspace paths or accepting unknown dependencies.
Current-base PR regression execution and source-seal qualification remain
distinct until the final combined source passes both.

The exact hosted rejection was pip's generated certifi bytecode recorded in
a transient per-install cache directory. The bounded correction disables pip's
explicit compilation (`--no-compile`) in source CI and updater dependency setup;
Python imports retain fresh isolated caches and disabled bytecode writes. The
reader continues to reject unknown external dependencies. A tiny fictional
local wheel exercises actual default-pip compilation and the no-compilation
control without an index or network. This is runtime packaging compatibility,
not a forecast, data-validation or operating-performance improvement.

Independent review separately reproduced `SOURCE-CI-STDLIB-NATIVE-01`: a native
extension directly in an allowed standard-library directory could execute while
being omitted from its inventory. The correction includes the interpreter's
actual supported extension suffixes there, retaining the same size/inventory
limits. A copied public native module and isolated child processes exercise
addition plus same-size/restored-mtime observable mutation. Flat bytecode was
already included and its separate suspected omission was disproved. The earlier
package/RECORD finding and its attempt history are preserved independently.


### Operating diagnostic source boundary (2026-10-22)

The fictional seed builder and its original B3 source, observations, input
contract and source-object closure remain unchanged. The separate operating
coordinator restores that same seed, validates its original dependencies, and
uses a derived execution copy. Its executable files come from the actual
candidate source; the seed's exact fictional activation configuration remains
separately hash-bound. This is a fictional operating test, not production
configuration, historical publication proof or experiment activation.

The coordinator includes the existing updater's three complete online source-CI
checks: initially, before the local data commit, and after Pages staging. Later
checks retain the initial CI run identity. Complete source tests remain in their
normal CI job; the updater's compile, JavaScript, UI and About checks still run
inside the measured operation. Actual advisory scripts and health outcomes also
run; unsupported advisory provider continuations remain explicitly unmeasured.
All application, fixture and check subprocess trees use the existing inherited
network guard with credentials removed. The narrowly bounded GitHub control
transports remain online. The diagnostic does not claim that the whole job is
offline or that mocked providers establish live-provider latency.

Only an approved completed preparation artifact can supply the four immutable
seed parents. Retrieval validates actual bounded file descriptors, the complete
allowlisted ZIP inventory, preparation identities and freshly rehashed bytes.
A source checkout, marker or saved admission result alone is insufficient.
Before allocating transport or restored copies, the coordinator applies the
unchanged filesystem reserve to the declared concurrent allocation estimate.
Unknown required measurements stop preparation. Root-supervised accounting must
independently establish attributable memory, subprocess-tree cleanup, OOM events
and filesystem headroom; local capability remains unknown where unavailable.

The protected original resource records are checked in the job. A separately
identified bounded measurement projection exposes numerical facts and aggregate
admission/correction results under logical scope tags. It omits raw evidence,
fixture rows, credentials, environment dumps and workspace paths. Subsequent
assessment retrieves the actual run, jobs and logs, recomputes all three results
using completed job timestamps, and retains missing or invalid samples as
failures. A projection is derived evidence, not the original bytes under an
original record's checksum. Failed raw job copies and private logs are retained
only on that ephemeral runner; they are not exported or durably preserved after
runner teardown. The remote immutable seed remains unchanged.

The 960-second planning target, 1,200-second job timeout and historical planning
misses remain unchanged. This source checkpoint establishes no new runtime,
resource, hosting or season-long operating PASS. A full admitted cloud seed,
approved artifact storage/transport, fresh hosted capability checks and the
separately authorized three cold serial samples remain necessary. The manual
workflow drafts and default-branch registration are separate protected changes;
no diagnostic dispatch, production configuration change or deployment is
implied by installing ordinary diagnostic source.

Local installed-source verification passed 148 focused controls (115 diagnostic
and 33 retained source-CI controls), Python/JavaScript syntax, 187 UI and 15 About
assertions. API and root-control responses in unit tests are mocked; harmless
child/grandchild network-denial controls execute real subprocesses. The full
split-path positive integration remains pending a genuinely admitted full seed;
an unadmitted small seed is rejected. None of these local checks establishes
hosted resource capability or an operating budget.

## Separate one-time paper odds study — 2026-10-22

This owner-authorized study is independent of the grading/builder release and
of diagnostic seed preparation. The accepted application, original forecasts,
saved selections, outcomes, source-CI boundary, completed reviews, daily cadence,
retired Ticker and inactive registrations are unchanged. A separate research
session does not become another website writer or receive the API credential.

`tools/odds_study.py` implements the bounded offline collection/normalization/
comparison and saved-bundle path. The ten existing numerical prop categories
map to their documented standard NFL markets; the eleventh study market is
`player_anytime_td`. That adapter is study-only, not new production parser
support. PPR is outside the requested bookmaker market set. Anytime TD remains
unvalued when its offered event differs from the saved rush-plus-receiving-TD
definition, its player identity is unresolved or a complementary side is absent.

The fixed one-time identity is `NFL-WEB-ODDS-ONCE-20261022`. At most sixteen
earliest future games within eight days are selected before prices, with one
region (`us`) and the exact eleven markets. Documented uncharged event discovery
provides quota evidence; no separately charged market-discovery request is used.
Before each event request, the collector refreshes that uncharged evidence and
authenticates a durable PR #1 reservation for eleven worst-case credits. Total
reservations cannot exceed176 or the initial verified remaining allowance;
later quota increases do not expand the ceiling. Counter disagreement, ambiguous
request completion, missing quota, HTTP failure or unsupported response encoding
stops the batch without a chargeable retry or replacement game. Reservations
are never refunded automatically. Duplicate claims and prior invocations fail.

The manual workflow is prepared locally and is **not installed or dispatched**
by this ordinary source operation. Its future collection step alone receives
`ODDS_API_KEY`; no browser, ordinary build, research repository or other step
receives it. Official API authentication uses a private HTTPS query parameter;
the collector never logs or serializes that URL, an arbitrary exception,
unrestricted headers or a request object. Nonidentity response encodings are
withheld before retention. Credential-bearing originals block the bundle seal;
original bodies are not edited and misrepresented as unchanged. There is no
key access or provider request in offline tests.

Before collection, freeze actual public website board/meta bytes only when they
match one pinned main commit. Retain those original files, source/tree identity,
original generation cutoff and separate retrieval/freeze clocks. A new odds
observation does not refresh an older forecast. Snapshot Top membership binds
line, side, source and both forecasts; differing saved Top contracts remain
preserved and explicitly unmatched rather than being silently attached to a
different displayed prop. Game/team/kickoff and unique within-game player joins
are required. Quote identities retain threshold, side, book, market, period,
source-body hash and retrieval/provider clocks. No historical selection is
invented and no model forecast is changed.

Supported reference arithmetic proportionally removes the two-sided margin
within each other book at the exact same player/game/statistic/period/threshold,
then excludes the offering book from its reference. Missing pairs, integer-push
uncertainty, unsupported clocks, unresolved identities or incompatible action/
void/statistic rules remain unvalued. The live v1 collector authenticates no
venue-rule registry, so its EV fields remain unavailable. Explicit fictional
rule controls exercise the supported arithmetic without certifying real rules.
Any later supported estimate is market-derived paper analysis, not a calibrated
model win probability, proven edge, executable offer, financial ROI or parlay
valuation. Projection gaps and display rankings are not probabilities.

The proposed output is one artifact for seven days, at most128MiB for both the
pre-upload bundle and decoded allowlisted members; each original event entity
is bounded to4MiB. Reserve136MiB of verified no-cost account headroom for that
artifact and overhead, after existing/pending shared allocations. This project
budget is not a provider hard cap or a public-artifact exemption. Actual account
storage and the applicable paid-usage hard-stop evidence remain unresolved;
**acquisition is held**. The larger diagnostic seed is not required for this
study, and its separate storage prerequisite is not waived. Public-repository
artifacts must not be described as private. No new destination or spending is
authorized. The existing cloud recipient must actually download, rehash, extract
and freshly verify the bundle before its seven-day expiration; a path or digest
alone is not completed delivery.

Saved verification rehashes the full allowlist and reconstructs the frozen
snapshot, selected population, quota/reservation accounting, normalized quotes
and comparisons from original retained bodies and receipts. A secret-cleared
failed batch may be integrity-valid while remaining `FAILED_SAFE`; it is never
a successful complete study. Manifest identity must also match the externally
retained completion record during retrieval. Unknown files, changed bytes,
symlinks, missing originals and unsupported bounds reject export. The summary
is a closed numerical projection rather than raw player/provider data.

Focused acceptance:59 wholly fictional tests passed, including a real
collector-wrapper/ledger/saved-reader integration with external HTTP/GitHub,
source-CI proof and execution context explicitly mocked. This is offline code
evidence, not a provider, subscription, quota, storage, hosted or predictive PASS.
An independent bounded source review reran the same59 tests successfully; its
API, context and source-CI boundaries remained mocked. Key rotation is not
performed: after the batch the owner can replace the same
repository Actions secret through Settings > Secrets and variables > Actions;
no browser or research credential migration is required. A replacement key's
validity is not claimed without a separately permitted check.

An additional bounded offline control then exposed a saved-reader defect in
that initial implementation: one188,846-byte fictional response containing
2,400 distinct quotes produced a9,667,338-byte report, marked COMPLETE, that the
generic entity parser rejected. The original failure and bytes remain retained;
the earlier59 tests did not cover this case. The correction keeps provider
entities at150,000 value nodes and depth24, and gives the larger derived report
its own finite500,000-node reader contract. Producer and saved failure replay
share a480,000-node quote/comparison bound, reserving20,000 nodes for the fixed
sixteen-event envelope. The4MiB original-body,32MiB derived-content and128MiB
archive/decoded caps are unchanged. A byte or complexity overflow stops before
another acquisition, retains the full original entity and reservation, and
records FAILED_SAFE; a partial comparison is never called a complete study.
Fresh saved verification recomputes that exact failure condition rather than
trusting its reason label. The2,400-quote case now round-trips without lost
contracts, and a separate6,000-quote case exercises the real complexity-failure
bound below32MiB. All63 focused tests passed locally; these are finite correctness
controls, not a live coverage, resource or operating-performance qualification.

A separate saved-input check then found that the retained public website board
exceeded the generic provider-entity complexity limit:157,103 nodes despite
remaining below the existing8MiB website-input byte cap. That failure is retained
separately from the report-reader defect. The adapter now gives the complete
website input an explicit finite500,000-node role while preserving the150,000-node
provider-entity limit. Before writing a frozen snapshot, the producer validates
all normalized rows against the unchanged150,000-node and16MiB saved-snapshot
reader bounds; unsupported expansion fails before acquisition rather than
dropping rows. The actual immutable saved Git board produces1,963 study rows,
fourteen game identities and twelve matching Top selections per side, retaining
its original forecast clock. This is an offline Git-input regression with the
Pages-match precondition explicitly mocked, not a new website observation,
capture or authenticated publication claim. All66 focused tests passed locally,
including finite website and outgoing-snapshot failure controls. The initial
test invocation missing the required tools import path is retained separately;
the corrected invocation ran the complete focused suite. No live data, credit,
storage, hosted operating or release qualification follows from these checks.

## 2026-10-22 release continuation: daily-refresh explanation

The actual About renderer still described hourly and additional game-day builds
after the daily-cadence checkpoint. That stale description was reproduced and
corrected: one scheduled refresh targets 8:06 a.m. America/Chicago; deliberate
manual and code-change runs may also occur. Daily operation can miss registered
timing checkpoints. Later observations cannot fill those gaps. This change does
not alter the updater, concurrency, timing policy, forecasts or selections.
The app cache identity advances from v58 to v59; previously qualified release
identities are not reused for changed application bytes.

The actual-renderer regressions now include the daily schedule, the separate
manual/code-change route and the missing-checkpoint caveat. Local JavaScript
syntax, 18 About assertions, 187 UI checks and Python compilation passed.
Required exact-source CI and browser results are recorded separately on PR #1;
earlier passing CI does not certify this changed source or a later main tree.

Independent read-only release review also confirmed a production configuration
dependency: the checked-in original-model selector cannot qualify the accepted
corrected engine. Its unchanged source guard rejects that mismatch before
provider requests. A fresh production-rooted corrected plan/configuration and
verified generated artifact are still required. The old Week 6 plan is not a
corrected Week 7 authorization. No such plan is applied by this documentation
or UI correction. Existing production records and separately reviewed local
observations remain distinct, with proof attached only to matching contracts.

The repository cleanup assessment is closed without deletion. Its dated
9.21 MiB artifact inventory establishes neither account exhaustion nor a need
to purchase storage. Existing retention and source/evidence/CI/recovery records
remain unchanged. Assess the 136 MiB odds reservation separately from the seed;
the seed's 2 GiB upload ceiling is not its measured retained size. Use observable
account usage and spending controls; no owner attestation of hidden allocations
is required. No-cost storage remains unverified, not proven insufficient.
Odds acquisition and research are not website-release prerequisites.

Expanded grading, exact saved-row comparisons, accuracy and private paper
tickets remain development features pending their connected acceptance and
actual public-site verification. Missing-report controls establish safe
unavailable states, not an accepted split release. Full operating qualification,
the production-rooted artifact, public contents and compatible recovery remain
release requirements; this small correction does not complete the Goal.

## 2026-10-23 production configuration transition

The owner-authorized release continues through the existing corrected-model
dispatch. Operational configuration may select only the explicitly supported
`sleeper-matchup-data-integrity-v2` model with its own
`partial-week-data-integrity-v2` plan, closed source hashes and actual clocks.
This does not repin the original experiment or qualify old receipts under a new
identity. Both research recorders remain inactive. Original source, registrations,
frozen selections and all retained evidence remain preserved.

The configuration regression now distinguishes exact retained original settings
from a separately identified corrected operational plan. It retains the original
recovery-mode bytes and CLI controls, and checks the complete corrected plan,
initial-board identity, engine closure and inactive flags. A self-consistently
rehashed wrong-engine plan must still reject. No validator or engine guard is
weakened. The protected configuration operation is recorded separately after the
ordinary test/documentation lease closes; the ordinary gate does not authorize it.

This source preparation is not deployment or operating qualification. Actual
production-rooted build, report reconstruction, Pages staging, paper-ticket
verification and compatible recovery must pass before release. The former
seven-day uploaded diagnostic seed is an execution arrangement, not a product
feature; any revised arrangement must retain the intended workload, reproducible
evidence, resource limits and honest measurement boundaries without spending.
# Recorded projection-response hashing and saved-source compatibility — 2026-10-23

The first genuine corrected-engine build at the production-rooted configuration
transition exceeded its unchanged 1,200-second local artifact boundary before
completed capture, report publication or Pages staging. This is a coding-path
failure, not evidence of account-storage exhaustion or a successful update.
The failed attempt and original evidence remain preserved.

The recorder now computes the same typed model-input response hash once per
request and reuses that request-local value in its retained player components.
It preserves observation clocks, all actual component values, independent request
identities and the first current-week projection mapping. No forecasting formula,
selection threshold, closed engine identity or experimental registration changes.

Saved corrected receipts with the accepted B3 helper association are read using
the actual retained B3 validator and its verified source/Git dependencies in an
independent temporary root. Existing original-version validation remains separate.
The new recorder cannot write evidence under the old helper identity. Complete
source/evidence inventories are freshly checked before and after delegation,
including copied Git objects, failure markers and saved frozen dependencies.
No durable PASS shortcut or permissive unknown-helper fallback is introduced.

The new helper requires its actual configuration/registration binding before a
new live attempt. Source correctness, completed real-package acceptance, operating
qualification and public deployment remain separate requirements; the historical
960-second planning misses and 1,200-second updater timeout remain unchanged.
# Frozen forecast population at recorded build — 2026-10-23

The next genuine build completed its recorded-builder work, then correctly failed
the fixed contract guard: 17 newly discovered explicitly late players enlarged an
already-started game's 38-player population. Every original player contract and
saved pick was unchanged. No completed capture/report/Pages generation advanced.
The failed original-input and failure evidence are retained without qualification.

The corrected-route integration now keeps new post-kickoff discoveries outside an
existing frozen forecast population before recording the new board. Their actual
source positions/components remain retained. It does not edit an old board,
receipt, fingerprint or clock, change forecasting/selection rules, or loosen the
validator. Changed/missing original contracts still fail. Original-version builds
retain their existing route, and temporary assembly wrappers restore on failure.
This integration correction requires its own actual-source tests/CI and genuine
build/report/staging acceptance; the failed 20.448-second attempt is not a passing
updater or operating measurement.
# 2026-10-23 report-finalization correction (release still pending)

The production-rooted corrected build completed its original-input/native/scope
bundle for thirteen pregame games, retaining one started game's original-proof
limitation. Its later report path exceeded the unchanged 1,200-second local
boundary (1,200.068540 seconds); neither latest nor Pages advanced. The genuine
capture and all failed attempts remain preserved separately. This is not a
successful updater, hosted operating qualification or deployment.

The actual report contained 56,918 rows and 24,291 groups. Reproducible private
group HTML occupied 1,047,441,052 bytes. Its first/last file timestamps span
156.723 seconds; that interval is not exclusive CPU attribution or a promised
runtime saving. The updater now requests `run_report(diagnostic_exports=False)`.
Only diagnostic JSON/CSV/HTML exports are optional. Complete semantic report
construction, exact memberships, derived outcomes, persistent ledgers, report-run
receipts, final original-byte checks and complete public validation remain.
The default offline API retains its original complete exports and return values.
No public format, asset cap, freshness rule or forecasting policy changes.

A connected due-checkpoint control also exposed the persistent ledger's original
seven-file-engine-only guard. Corrected checkpoints now dispatch explicitly to
the already closed corrected model/eight-file engine. Original-model dispatch
stays unchanged; unknown models, crossed labels and changed engine maps fail.
This does not repin or admit corrected observations to the original registered
comparison. Saved checkpoint decisions retain their exact identities on retry;
genuinely later outcome derivations retain their own clocks and report identities.

Saved ranked observations and pinned decision ledgers from source
`e2dd96a31690baad04c8660302933f45f77d72e7` use actual retained source and dependencies,
with typed commit/tree/blob verification before execution and fresh checks after
replay. A separate bounded child performs original qualification or pinned-ledger
reproduction. Its validation clock is genuinely sampled by the invoking reader;
it does not create observations or change original clocks. Unknown sources,
changed shared qualification dependencies, corruption and failed completions
remain rejected. New recording still requires exact current source bytes. This
is closed compatibility for that retained source, not arbitrary old-source trust.
The public publisher's existing helper inventory covers the changed report and
strategy reader. No durable PASS shortcut or cross-root validation trust is added.

Source acceptance, complete generated-artifact/browser review and a supported
finite operating budget remain separate release requirements. Existing 960-second
planning misses, the 960-second target and 1,200-second updater timeout remain
visible. No source-only test or report-finalization retry establishes full hosted
operation. Research recording remains inactive; odds/research are separate from
the website release.

The real saved-capture report retry at source `2a5432b` exited with signal 11
before Pages staging, after 600.204891 seconds. Its root crash cause is not
established. Preserved stack samples and a three-saved-row control exposed a
connected publication cost: each ranked row reread the same retained engine Git
objects and strategy policy. Typed row batches now use private immutable engine
and policy digests freshly established before the batch and rechecked afterward.
Every row keeps its identity, privacy, policy, schema and clock checks. Standalone
row checks still read fresh dependencies. Prepared reuse binds these actual
retained-Git/policy dependencies and rechecks them before returning a cache hit;
changed or unavailable modern dependencies cannot inherit an earlier success.
Legacy formats can still run complete uncached validation when optional reuse
has no complete dependency closure. This does not alter public formats, report
memberships, source qualification, caps, engine or scoring rules. A later actual
report/updater result is required; removing redundant reads alone is not an
operating or deployment PASS.

### Saved-plan and diagnostic source transition — 2026-10-23

The genuine current-production-rooted corrected-engine build/report/validation/
Pages/tar path at 04519b54 completed locally in 920.071674 seconds. The actual
56,918 rows, 24,295 exact-membership groups and 4,830 outcomes reconciled; the
601-file Pages working set is 38,020,230 bytes and its uploader tar is 39,147,520
bytes. Controlled Chromium checks at 320/390/1280 and independent compatible
Git/data restoration passed. This is accepted local artifact evidence, not a
whole-hosted-job, aggregate-memory, physical-device or public-deployment result.
Both exact-source push and current-main test-merge CI passed 862 tests for that
source. All earlier unfavorable timing results and failed attempts remain.

Saved hosting snapshots now resolve their exact completion, scope and original
registration before full bundle verification. A later root configuration cannot
replace that pinned plan. The current non-snapshot generation still must match
current configuration. Missing, corrupted, late, failed or incompatible pinned
evidence fails without discovery of a convenient alternative. The wrapper does
not change any clock, source, native, model, scope or completion algorithm.

Saved ranked observations and decision ledgers have two closed retained readers:
e2dd96a31690baad04c8660302933f45f77d72e7/tree
d02544420316557ddf1451a0753c2321e3d2a245, and
04519b54dfb76dcca7916fe6bf75d7e1711793b6/tree
10a5cc1539c51c8089fb7ff077447b6d17c4e13e. Each executes its actual bounded,
freshly checked old source rather than current helpers under an old label.
Shared engine, policy and qualification dependencies stay exact. New recording
remains strict to current installed source. Unknown source/helper combinations
have no fallback. Existing original records, selections and timestamps remain.

The existing diagnostic coordinator keeps the immutable B3 seed and frozen input
contract. On a separately derived copy it installs the actual candidate source,
repackages the saved generation, then creates a new fictional plan/registration
at the fixed +77h+130s clock before the unchanged +135s material-correction
sample. Its internal source-marker-v3 binds the original seed/configuration and
Git roles, current candidate configuration/source/helper, new fictional plan and
actual registration. Marker-v2 stays readable but grants no transition privilege.
The original fourteen games, nine legacy fingerprints, five verified games,
expiry, engine, offers, clocks and inactive experiments stay unchanged. This
fictional adaptation never edits the production plan or requalifies an old
receipt. Every retry freshly checks the saved graph and aliases; changed
registration/configuration/source dependencies invalidate reuse. Failed mutable
state rolls back separately from retained create-only evidence.

No full 24-generation/277-observation seed, three cold hosted samples or aggregate
resource qualification is claimed here. A SMALL correctness fixture is not full
admission. The 960-second planning target and 1,200-second updater timeout are
unchanged. Storage remains an account-evidence prerequisite, not presumed
exhaustion: shorter artifact retention can reduce cost exposure but cannot prove
no additional cost. An old source that merely reads the format is not certified
routine operational recovery. Existing daily cadence, retired Ticker, PR #2,
My Picks and original-archive review remain preserved. The expanded grading,
accuracy and private paper builder remain unreleased pending the remaining
operating and public-release acceptance.

Targeted local acceptance for this change: three actual closed-reader catalog
controls PASS0.397s; four actual corrected builder/native/report/hosting saved-plan
controls PASS17.018s; six actual e2d/045 source/ledger/cold-process/corruption
controls PASS392.473s; 59 coordinator controls PASS1.426s plus four additional
fresh-retry/alias/index controls PASS0.319s. Source-CI transport/resource records
in the coordinator unit controls are mocks, not hosted qualification. Separately,
the unchanged F607 dispatcher reproduced a pinned B3 origin and prospective
nine-legacy/five-verified scope in71.880s; no completed new bundle or full seed
was inferred. The initial negative test incorrectly expected a second bundle to
remain globally usable after corrupting an inventoried registration; the full
inventory correctly rejected it. Its corrected test retains the rejection and
checks the untouched alternative bytes. Another synthetic assessor fixture had
20s for21 declared stages; its accounting was corrected without altering any
real timing limit. Both initial logs remain. Combined wrapper replay and final
exact-source CI are pending at this implementation commit.
