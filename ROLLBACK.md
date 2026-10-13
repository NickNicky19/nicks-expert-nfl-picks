# Restore the original without losing your evidence

## What "original" means

Nick's working edition **before Phase 1**, not Joshua's older published data.
Pinned source commit: `6c33224b90d32ac2e005fff140662f114f97eb14`.
Original deployed snapshot: `2026-10-10T19:01:53Z` (October 10, 2:01:53 p.m. America/Chicago).

GitHub refused the attempted backup-branch creation during preparation (`403: Resource not accessible by integration`).
**No remote backup branch, code update, workflow change, or deployment was created by this session.**
The delivered backup is a local/downloadable deployed-site snapshot plus exact copies of the original modified source files.
It is not a full repository-history export, and does not contain external Worker secrets or browser-local settings.

## Before installing

Use the package's `apply_upgrade.py` against the existing repository. It checks the origin, clean worktree,
original file hashes, original model-file hashes, and patch applicability. With `--apply`, it creates a
local backup branch and full tracked-tree ZIP before creating an upgrade branch. It does not push or deploy.
Push the reported backup branch to GitHub before merging the upgrade. Do not force-push or reset main.
Keep the original downloaded snapshot and the repository-tree backup outside the repository.

## Recovery from your phone — available only after installation

1. Open the repository's **Actions** page and select **Restore original code**.
2. Choose **Run workflow**, branch **main**, and confirmation **RESTORE_ORIGINAL**.
3. Run it. It saves the pre-restore head to a backup branch, restores the original app and grader, switches a release-mode JSON file, commits normally,
   then requests an **Hourly update** rebuild using the restored original code.
4. Check that the rebuild and Pages deployment succeeded. A completed recovery commit alone is not proof of deployment.

The Actions route restores `pull/grade.py`, `output/app.js`, and `output/index.html`, then sets `config/release-mode.json` to `original`.
It deliberately retains the recovery-aware workflow runner, which skips Phase 1 tests/capture in original mode; the token does not need to edit workflow definitions.
The local full-restoration command additionally restores `.github/workflows/hourly.yml` exactly, but publishing that workflow change requires the appropriate workflow-write permission.
No `data/forward`, `data/history`, caches, original prediction archives, browser storage, or Git history is deleted.
New helper files and recovery documentation may remain in the repository, but the original application no longer uses them and the recovery-mode runner does not execute new capture/grading checks.
This restores original behavior while retaining current data; it does not deliberately make data four days old.

Recovery needs repository-content and workflow permissions. It does not bypass branch protection.
The recovery and hourly jobs share a concurrency group. A genuinely stuck earlier run may need to be cancelled
in Actions before recovery can proceed; do not circumvent an environment approval requirement.

## Recovery from an existing local checkout

Start with a clean `main` branch, fetch/pull the latest main, then run:

```sh
python tools/restore_original.py --confirm RESTORE_ORIGINAL
git diff --cached
```

The default local script creates a pre-restore backup and stages the four original files, including the workflow. Add `--application-only` for the same workflow-preserving route used by Actions. After reviewing the result,
push the backup branch, commit normally, and push the recovery commit. Run the restored Hourly update workflow.
No hard reset, forced push, blanket checkout, or deletion of evidence is necessary.
An ordinary revert of a code-only upgrade commit is also possible; do not revert intervening data-capture commits.

## Exact visual snapshot recovery

The supplied `nicks-nfl-original-pages-20261010.zip` is the untouched GitHub Pages artifact, containing `artifact.tar`.
Its SHA-256 is `80ecb82ff130d501eed874fcb9a762379c24d8b398918437afc0eba3ecf9e322`.
It contains the original static website and published data, not the Python collector or complete Git history.
Redeploying it would restore an old visual/data snapshot only. The snapshots' lines are not current offers.
