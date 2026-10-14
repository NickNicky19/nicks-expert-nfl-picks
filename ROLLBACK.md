# Recover working Phase 1 or the original code

## Verified backups

Before Phase 2 edits, both remote references and trees were read back:

| Backup | Commit | Tree |
| --- | --- | --- |
| Original before Phase 1: backup/pre-phase1-20261013-210e34329d6e | 210e34329d6e5b42b4e8f1af768b63db75ec10c5 | 4c2349e3a37905ad8043437b9f661227be488a2c |
| Working Phase 1: backup/pre-phase2-20261014-3149663447b2 | 3149663447b29f95f06c7259b84da3bd4a21cab0 | 880aa7e3b980be3bf55cb27cb735bf9a3d9a74f3 |

The original backup's app, grader and seven baseline engine files match the
original pinned source at 6c33224b90d32ac2e005fff140662f114f97eb14. Both backups
retain repository history and all tracked data at their respective checkpoints.
They do not contain browser-local settings or external Worker secrets.

Phase 2 is unmerged. To stop at review, leave main and Pages alone; no recovery
mutation is required. Keep the review branch and its new evidence.

## Recover working Phase 1 after Phase 2 is merged

From a phone: Actions → **Restore working Phase 1** → Run workflow → main →
**RESTORE_PHASE1**. The workflow verifies the pinned Phase 1 backup, creates and
pushes a fresh pre-restore backup, restores allowlisted Phase 1 app/grader/verifier
files, disables Phase 2 capture, commits normally and requests an Hourly update.
It retains the recovery-aware runner and all new evidence. Confirm that the
following build and Pages deployment both succeed.

From an existing local checkout, fetch/pull a clean main branch, then:

```sh
git fetch origin backup/pre-phase2-20261014-3149663447b2
# Verify FETCH_HEAD is 3149663447b29f95f06c7259b84da3bd4a21cab0.
python tools/restore_phase1.py --confirm RESTORE_PHASE1
git diff --cached
```

The command prints its new backup branch. Push that branch first, inspect the
staged code/mode changes, commit normally and push main. Request Hourly update
and check the deployment. It never commits or pushes by itself. The old Phase 1
population diagnostic may report its known discrepancies again; that does not
silently enable a different forecast model or rewrite evidence.

## Recover the original edition before Phase 1

Pinned target: 6c33224b90d32ac2e005fff140662f114f97eb14, Nick's edition, not Joshua's
older published data. The original deployed snapshot was 2026-10-10T19:01:53Z.

From a phone: Actions → **Restore original code** → Run workflow → main →
**RESTORE_ORIGINAL**. It saves a remote pre-restore backup, restores the original
app, page shell, grader and verifier, selects original mode, and requests a
rebuild. The retained runner skips Phase 1/2 capture and upgraded grading checks.
Check the following build and Pages deployment; a recovery commit alone is not
proof that the website was restored.

From a clean, fetched main checkout:

```sh
python tools/restore_original.py --confirm RESTORE_ORIGINAL --application-only
git diff --cached
```

Push the reported pre-restore backup before committing/publishing recovery.
Without --application-only the local command also restores the original hourly
workflow; publishing workflow changes requires normal workflow-write permission.

## What every recovery retains

All data/forward, data/verification, data/shadow, data/offers, data/outcomes,
data/history, replay lanes, caches, prediction archives and Git history remain.
Current data can be rebuilt; recovery does not deliberately deploy stale lines.
New helper files may remain but recovered modes do not execute Phase 2 capture.
The recovery routes share the hourly concurrency group, refuse dirty worktrees,
verify allowlisted source hashes before staging, and never reset or force-push.
Repository/environment protections remain in effect.

An ordinary code-only revert is also possible. Review it carefully; retain new
immutable evidence and do not revert intervening hourly data commits. The
original backup's untouched Pages artifact SHA-256 remains
80ecb82ff130d501eed874fcb9a762379c24d8b398918437afc0eba3ecf9e322. Redeploying
that old artifact is visual-snapshot recovery, not current offers.

Offline tests cover both recovery modes, backup/history retention, wrong hashes,
uncommitted files and refusal of a production-model switch. A disposable
repository rollback rehearsal is part of the Phase 2 integration validation;
production recovery is not run while preparing this unmerged PR.
