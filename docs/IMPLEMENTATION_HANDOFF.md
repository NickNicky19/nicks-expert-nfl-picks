# Phase 2 reporting and implementation handoff

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
