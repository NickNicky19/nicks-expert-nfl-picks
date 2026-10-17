# Phase 2 reporting and implementation handoff

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
