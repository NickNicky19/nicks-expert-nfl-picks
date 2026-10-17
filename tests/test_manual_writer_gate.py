"""Explicit manual authority, unchanged automatic gates, and real Git races."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_writer_gate import NOW, HEAD, comment, fixture, result
from writer_gate import (GateRejected, MANUAL_GATE_VERSION, RemoteGate, check_owner,
                         claim, claim_manual, entrypoint_sha256, finish, git, main, message, state_commit,
                         verify_active_manual_authorization)

STATE_HEAD = "c" * 40


def authorization(policy, source=HEAD, state_head=STATE_HEAD, suffix="1"):
    return {"schema_version": "manual-writer-authorization-v1", "request_id": "manual-" + suffix,
            "run_id": "manual-run-" + suffix, "audit_id": "manual-review-" + suffix,
            "repository": policy["repository"], "repository_id": policy["repository_id"],
            "pull_request": policy["pull_request"], "branch": policy["development_branch"],
            "reviewed_sha": source, "coordination_sha": state_head,
            "policy_version": policy["version"], "policy_sha256": fixture()[2]["policy_sha256"],
            "evaluation_policy_version": policy["evaluation_policy_version"],
            "timing_policy_version": policy["timing_policy_version"],
            "gate_version": MANUAL_GATE_VERSION, "gate_sha256": entrypoint_sha256(),
            "kind": "manual_owner", "approval": "OWNER_APPROVED_MANUAL_EXECUTION", "native_dispatch": False,
            "boundaries": copy.deepcopy(policy["boundaries"]),
            "scope": ["tools/scorecard.py", "tests/test_scorecard.py"], "finding_ids": ["A01", "A02"]}


def target(policy, source=HEAD):
    repository = {"id": policy["repository_id"], "full_name": policy["repository"]}
    pull_request = {"number": policy["pull_request"], "html_url": f"https://github.com/{policy['repository']}/pull/1",
                    "state": "open", "merged": False,
                    "head": {"repo": copy.deepcopy(repository), "ref": policy["development_branch"], "sha": source}}
    return repository, pull_request


def manual_fixture():
    policy, state, _ = fixture()
    state["readiness"].update(owner_handoff_complete=True, rejection_tests_verified=True)
    payload = authorization(policy)
    raw = comment("MANUAL_OWNER_AUTHORIZATION", payload, policy)
    return policy, state, payload, raw


def acquire(policy, state, raw, source=HEAD, state_head=STATE_HEAD, run_id="manual-run-1", context=None):
    repository, pull_request = context or target(policy, source)
    return claim_manual(state, raw, policy, source, state_head, NOW, run_id=run_id,
                        repository=repository, pull_request=pull_request, gate_sha256=entrypoint_sha256())


class ManualGateTests(unittest.TestCase):
    def rejected(self, reason, function, *args, **kwargs):
        with self.assertRaises(GateRejected) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.reason, reason)

    def test_owner_manual_acquires_with_native_gates_false_and_inputs_unchanged(self):
        policy, state, payload, raw = manual_fixture()
        original = copy.deepcopy((policy, state, raw))
        active = acquire(policy, state, raw)
        self.assertEqual(active["active"]["kind"], "manual_owner")
        self.assertEqual(active["active"]["scope"], payload["scope"])
        self.assertEqual(active["readiness"], state["readiness"])
        self.assertFalse(policy["automatic_implementation_enabled"])
        self.assertFalse(active["readiness"]["native_entrypoint_uses_gate_verified"])
        self.assertEqual(active["finding_attempts"], {"A01": 1, "A02": 1})
        self.assertEqual((policy, state, raw), original)
        check_owner(active, policy, payload["run_id"], HEAD, gate_sha256=entrypoint_sha256())

    def test_wrong_github_id_login_bot_and_comment_origin_rejected(self):
        policy, state, _, raw = manual_fixture()
        for field, value in (("id", 0), ("login", "not-the-owner"), ("type", "Bot")):
            with self.subTest(field=field):
                altered = copy.deepcopy(raw); altered["user"][field] = value
                self.rejected("UNTRUSTED_AUTHOR", acquire, policy, state, altered)
        raw["html_url"] = raw["html_url"].replace("/pull/1", "/pull/2")
        self.rejected("WRONG_COMMENT_ORIGIN", acquire, policy, state, raw)

    def test_manual_marker_cannot_be_replaced_with_handoff(self):
        policy, state, payload, _ = manual_fixture()
        raw = comment("HANDOFF_REQUEST", payload, policy)
        self.rejected("WRONG_MESSAGE_MARKER", acquire, policy, state, raw)
        self.rejected("UNKNOWN_REQUEST_SCHEMA", claim, state, message(raw, "HANDOFF_REQUEST", policy), policy, HEAD, NOW)

    def test_legacy_handoff_cannot_select_manual_kind(self):
        policy, state, request = fixture(); request["kind"] = "manual_owner"
        self.rejected("UNKNOWN_REQUEST_KIND", claim, state, request, policy, HEAD, NOW)

    def test_manual_explicit_approval_boundaries_and_no_native_dispatch_required(self):
        policy, state, payload, _ = manual_fixture()
        for key, value in (("approval", "implicit"), ("native_dispatch", True),
                           ("boundaries", {"merge": True}), ("schema_version", "old"), ("kind", "implementation")):
            with self.subTest(key=key):
                altered = {**payload, key: value}
                self.rejected("EXPLICIT_MANUAL_AUTHORIZATION_REQUIRED", acquire, policy, state,
                              comment("MANUAL_OWNER_AUTHORIZATION", altered, policy))

    def test_authorized_run_must_match_invocation(self):
        policy, state, _, raw = manual_fixture()
        self.rejected("WRONG_MANUAL_RUN", acquire, policy, state, raw, run_id="other-run")
        self.rejected("WRONG_MANUAL_RUN", acquire, policy, state, raw, run_id=None)

    def test_stale_source_coordination_policy_experiment_and_gate_versions(self):
        policy, state, payload, raw = manual_fixture()
        self.rejected("STALE_HEAD", acquire, policy, state, raw, source="b" * 40)
        self.rejected("STALE_COORDINATION_HEAD", acquire, policy, state, raw, state_head="d" * 40)
        for key, value, reason in (("policy_version", "old", "STALE_POLICY"),
                                   ("policy_sha256", "0" * 64, "STALE_POLICY"),
                                   ("evaluation_policy_version", "old", "STALE_EXPERIMENT_VERSION"),
                                   ("timing_policy_version", "old", "STALE_EXPERIMENT_VERSION"),
                                   ("gate_version", "old", "STALE_MANUAL_GATE"),
                                   ("gate_sha256", "0" * 64, "STALE_MANUAL_GATE")):
            with self.subTest(key=key):
                self.rejected(reason, acquire, policy, state,
                              comment("MANUAL_OWNER_AUTHORIZATION", {**payload, key: value}, policy))

    def test_wrong_repo_branch_pr_closed_merged_or_fork_rejected(self):
        policy, state, payload, raw = manual_fixture()
        altered = {**payload, "repository_id": 1}
        self.rejected("WRONG_TARGET", acquire, policy, state, comment("MANUAL_OWNER_AUTHORIZATION", altered, policy))
        for area, key, value in (("repository", "id", 1), ("repository", "full_name", "other/repo"),
                                 ("pr", "number", 2), ("pr", "state", "closed"), ("pr", "merged", True),
                                 ("head", "ref", "main"), ("head", "sha", "b" * 40),
                                 ("head", "repo", {"id": 1, "full_name": "fork/repo"})):
            with self.subTest(area=area, key=key):
                repository, pr = target(policy)
                where = repository if area == "repository" else pr if area == "pr" else pr["head"]
                where[key] = value
                self.rejected("WRONG_OR_STALE_MANUAL_TARGET", acquire, policy, state, raw, context=(repository, pr))

    def test_edited_and_future_authorization_rejected(self):
        policy, state, _, raw = manual_fixture()
        raw["updated_at"] = (NOW + timedelta(seconds=1)).isoformat()
        self.rejected("FUTURE_OR_EDITED_REQUEST", acquire, policy, state, raw)
        raw["created_at"] = raw["updated_at"]
        self.rejected("FUTURE_OR_EDITED_REQUEST", acquire, policy, state, raw)

    def test_protected_empty_duplicate_and_unbounded_scopes_rejected(self):
        policy, state, payload, _ = manual_fixture()
        for scope in ([], ["AGENTS.md"], ["config/handoff-policy.json"], ["pull/build.py"],
                      ["data/forward/receipt.json.gz"], [".github/workflows/hourly.yml"], ["../tools/x.py"]):
            with self.subTest(scope=scope):
                self.rejected("PROTECTED_OR_UNBOUNDED_SCOPE", acquire, policy, state,
                              comment("MANUAL_OWNER_AUTHORIZATION", {**payload, "scope": scope}, policy))
        self.rejected("INVALID_SCOPE", acquire, policy, state,
                      comment("MANUAL_OWNER_AUTHORIZATION", {**payload, "scope": ["tools/x.py", "tools/x.py"]}, policy))

    def test_manual_requires_prior_handoff_and_verified_rejections(self):
        policy, state, _, raw = manual_fixture()
        for key in ("owner_handoff_complete", "rejection_tests_verified"):
            altered = copy.deepcopy(state); altered["readiness"][key] = False
            self.rejected("MANUAL_PREREQUISITES_NOT_VERIFIED", acquire, policy, altered, raw)

    def test_automatic_requests_still_disabled_after_manual_release(self):
        policy, state, payload, raw = manual_fixture()
        active = acquire(policy, state, raw)
        done = finish(active, result(policy, payload), policy, HEAD, NOW, gate_sha256=entrypoint_sha256())
        _, _, request = fixture()
        request.update(kind="implementation", scope=["tools/scorecard.py"], finding_ids=["A01"])
        self.rejected("AUTOMATIC_IMPLEMENTATION_DISABLED", claim, done, request, policy, HEAD, NOW)

    def test_manual_does_not_run_under_automatically_enabled_policy(self):
        from reliability import digest
        policy, state, payload, _ = manual_fixture(); policy["automatic_implementation_enabled"] = True
        state["policy_sha256"] = payload["policy_sha256"] = digest(policy)
        self.rejected("MANUAL_REQUIRES_AUTOMATIC_DISABLED", acquire, policy, state,
                      comment("MANUAL_OWNER_AUTHORIZATION", payload, policy))

    def test_duplicate_request_and_review_ids_remain_consumed_after_blocked_release(self):
        policy, state, payload, raw = manual_fixture(); active = acquire(policy, state, raw)
        done = finish(active, result(policy, payload, status="BLOCKED"), policy, HEAD, NOW, gate_sha256=entrypoint_sha256())
        self.rejected("DUPLICATE_REQUEST_OR_AUDIT", acquire, policy, done, raw)
        changed = {**payload, "request_id": "another-id"}
        self.rejected("DUPLICATE_REQUEST_OR_AUDIT", acquire, policy, done, comment("MANUAL_OWNER_AUTHORIZATION", changed, policy))

    def test_busy_bootstrap_and_manual_owners_have_no_takeover(self):
        policy, state, _, raw = manual_fixture(); active = acquire(policy, state, raw)
        other = authorization(policy, suffix="2")
        self.rejected("BUSY", acquire, policy, active, comment("MANUAL_OWNER_AUTHORIZATION", other, policy), run_id=other["run_id"])
        state["active"] = {"kind": "bootstrap_reservation"}
        self.rejected("BUSY", acquire, policy, state, raw)

    def test_finding_budget_and_empty_findings_not_bypassed(self):
        policy, state, payload, raw = manual_fixture(); state["finding_attempts"]["A01"] = 2
        self.rejected("ATTEMPT_LIMIT_OWNER_ATTENTION", acquire, policy, state, raw)
        state["finding_attempts"].clear()
        self.rejected("AUDIT_FINDING_REQUIRED", acquire, policy, state,
                      comment("MANUAL_OWNER_AUTHORIZATION", {**payload, "finding_ids": []}, policy))

    def test_checkpoint_advance_and_exact_release_preserve_ledger_readiness(self):
        policy, state, payload, raw = manual_fixture(); active = acquire(policy, state, raw)
        checkpoint = finish(active, result(policy, payload, end="b" * 40), policy, "b" * 40, NOW,
                            descendant=True, changed_paths=["tools/scorecard.py"], release=False,
                            gate_sha256=entrypoint_sha256())
        check_owner(checkpoint, policy, payload["run_id"], "b" * 40, gate_sha256=entrypoint_sha256())
        final = {"run_id": payload["run_id"], "request_id": payload["request_id"], "start_sha": "b" * 40,
                 "end_sha": "b" * 40, "status": "COMPLETED", "deployed": False, "production_model_changed": False}
        done = finish(checkpoint, message(comment("CODEX_RESULT", final, policy), "CODEX_RESULT", policy),
                      policy, "b" * 40, NOW, gate_sha256=entrypoint_sha256())
        self.assertIsNone(done["active"])
        self.assertEqual(len(done["checkpoints"]), 2)
        self.assertEqual(done["readiness"], state["readiness"])
        self.assertEqual(done["requests"][payload["request_id"]]["status"], "COMPLETED")

    def test_checkpoint_scope_stale_gate_and_other_owner_rejected(self):
        policy, state, payload, raw = manual_fixture(); active = acquire(policy, state, raw)
        self.rejected("SOURCE_CHANGED_OUTSIDE_LEASE_SCOPE", finish, active, result(policy, payload, end="b" * 40),
                      policy, "b" * 40, NOW, descendant=True, changed_paths=["pull/build.py"], gate_sha256=entrypoint_sha256())
        self.rejected("STALE_MANUAL_GATE", check_owner, active, policy, payload["run_id"], HEAD, gate_sha256="0" * 64)
        self.rejected("STALE_MANUAL_GATE", finish, active, result(policy, payload), policy, HEAD, NOW)
        other = {**payload, "run_id": "other-run"}
        self.rejected("NOT_LEASE_OWNER", finish, active, result(policy, other), policy, HEAD, NOW, gate_sha256=entrypoint_sha256())

    def test_bootstrap_reservation_cannot_check_or_finish_as_implementation_lease(self):
        policy, state, payload, _ = manual_fixture()
        state["active"] = {"kind": "bootstrap_reservation", "run_id": payload["run_id"],
                           "request_id": payload["request_id"], "owner": policy["trusted_requester"]}
        self.rejected("BOOTSTRAP_NOT_IMPLEMENTATION_LEASE", check_owner, state, policy, payload["run_id"], HEAD)
        self.rejected("BOOTSTRAP_NOT_IMPLEMENTATION_LEASE", finish, state, result(policy, payload), policy, HEAD, NOW)

    def test_remote_source_drift_and_wrong_readback_block_publication(self):
        policy, state, _, _ = manual_fixture()
        remote = RemoteGate(Path('.'), policy, verify_target=False)
        with patch.object(remote, "read", return_value=(STATE_HEAD, state)), patch.object(remote, "head", return_value="b" * 40):
            self.rejected("SOURCE_HEAD_DRIFT", remote.publish, STATE_HEAD, state, expected_source=HEAD)
        with patch.object(remote, "read", side_effect=[(STATE_HEAD, state), ("e" * 40, state)]), \
             patch.object(remote, "head", return_value=HEAD), \
             patch("writer_gate.state_commit", return_value="d" * 40), patch("writer_gate.git"):
            self.rejected("STATE_READBACK_FAILED", remote.publish, STATE_HEAD, state, expected_source=HEAD)

    def test_source_drift_after_state_push_leaves_claim_unusable(self):
        policy, state, _, _ = manual_fixture()
        remote = RemoteGate(Path('.'), policy, verify_target=False)
        with patch.object(remote, "read", side_effect=[(STATE_HEAD, state), ("d" * 40, state)]), \
             patch.object(remote, "head", side_effect=[HEAD, "b" * 40]), \
             patch("writer_gate.state_commit", return_value="d" * 40), patch("writer_gate.git"):
            self.rejected("SOURCE_HEAD_DRIFT", remote.publish, STATE_HEAD, state, expected_source=HEAD)

    def test_owner_edits_after_acquisition_stop_renewed_authorization_check(self):
        policy, state, _, raw = manual_fixture(); active = acquire(policy, state, raw)
        verify_active_manual_authorization(active["active"], raw, policy)
        changed = copy.deepcopy(raw); changed["body"] += "\nOwner withdrew this request."
        self.rejected("MANUAL_AUTHORIZATION_CHANGED", verify_active_manual_authorization, active["active"], changed, policy)

    def test_cli_manual_path_fetches_owner_and_target_twice_and_publishes_source_bound(self):
        policy, state, payload, raw = manual_fixture(); remote = MagicMock()
        remote.read.return_value = (STATE_HEAD, state); remote.head.return_value = HEAD
        remote.publish.return_value = "e" * 40
        with patch("writer_gate.RemoteGate", return_value=remote), \
             patch("writer_gate.fetched_comment", side_effect=[raw,raw]) as comments, \
             patch("writer_gate.fetched_manual_target", return_value=target(policy)) as targets, \
             patch.object(sys,"argv",["writer_gate.py","claim-manual","--comment-id","123","--run-id",payload["run_id"]]), \
             redirect_stdout(io.StringIO()) as output:
            main()
        self.assertEqual(comments.call_count,2); self.assertEqual(targets.call_count,2)
        self.assertEqual(remote.publish.call_args.kwargs,{"expected_source":HEAD})
        self.assertEqual(remote.publish.call_args.args[1]["active"]["kind"],"manual_owner")
        self.assertIn('READBACK_VERIFIED',output.getvalue())

    def test_cli_changed_authorization_before_publication_never_pushes(self):
        policy, state, payload, raw = manual_fixture(); remote = MagicMock()
        remote.read.return_value = (STATE_HEAD, state); remote.head.return_value = HEAD
        changed = copy.deepcopy(raw); changed["body"] += "\nChanged by owner."
        with patch("writer_gate.RemoteGate", return_value=remote), \
             patch("writer_gate.fetched_comment", side_effect=[raw,changed]), \
             patch("writer_gate.fetched_manual_target", return_value=target(policy)), \
             patch.object(sys,"argv",["writer_gate.py","claim-manual","--comment-id","123","--run-id",payload["run_id"]]), \
             redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught: main()
        self.assertEqual(caught.exception.code,2); remote.publish.assert_not_called()


class ManualGitRaceTests(unittest.TestCase):
    def test_two_authorized_manual_siblings_only_one_wins_then_readback_checkpoint_release(self):
        policy, state, _, _ = manual_fixture()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); server = base / "remote.git"; a = base / "a"; b = base / "b"
            git(base, "init", "--bare", str(server)); git(base, "init", str(a))
            for key, value in (("user.name", "Fixture"), ("user.email", "fixture@example.invalid")):
                git(a, "config", key, value)
            (a / "forecast-evidence.txt").write_text("immutable\n")
            path = a / policy["state_path"]; path.parent.mkdir(); path.write_text(json.dumps(state))
            git(a, "add", "."); git(a, "commit", "-m", "Fictional manual-gate baseline")
            first = git(a, "rev-parse", "HEAD").decode().strip()
            git(a, "remote", "add", "origin", str(server))
            for branch in (policy["coordination_branch"], policy["development_branch"]):
                git(a, "push", "origin", f"{first}:refs/heads/{branch}")
            git(base, "clone", str(server), str(b))
            git(b, "config", "user.name", "Fixture"); git(b, "config", "user.email", "fixture@example.invalid")
            payloads = [authorization(policy, first, first, str(i)) for i in range(2)]
            states = [acquire(policy, state, comment("MANUAL_OWNER_AUTHORIZATION", p, policy),
                              source=first, state_head=first, run_id=p["run_id"]) for p in payloads]
            candidates = [state_commit(root, first, s, policy["state_path"]) for root, s in zip((a,b), states)]
            barrier = threading.Barrier(2)
            def push(pair):
                root, candidate = pair; barrier.wait()
                try:
                    git(root, "push", "origin", f"{candidate}:refs/heads/{policy['coordination_branch']}")
                    return True
                except subprocess.CalledProcessError:
                    return False
            with ThreadPoolExecutor(max_workers=2) as executor:
                won = list(executor.map(push, zip((a,b), candidates)))
            self.assertEqual(sum(won), 1)
            winner = won.index(True); remote = RemoteGate(a, policy, verify_target=False)
            actual, active = remote.read(); self.assertEqual(actual, candidates[winner]); self.assertEqual(active, states[winner])
            check_owner(active, policy, payloads[winner]["run_id"], remote.head(), gate_sha256=entrypoint_sha256())
            report = {"run_id": payloads[winner]["run_id"], "request_id": payloads[winner]["request_id"],
                      "start_sha": first, "end_sha": first, "status": "COMPLETED", "deployed": False,
                      "production_model_changed": False}
            parsed = message(comment("CODEX_RESULT", report, policy), "CODEX_RESULT", policy)
            saved = finish(active, parsed, policy, first, NOW, release=False, gate_sha256=entrypoint_sha256())
            second = remote.publish(actual, saved, expected_source=first)
            done = finish(saved, parsed, policy, first, NOW, gate_sha256=entrypoint_sha256())
            final = remote.publish(second, done, expected_source=first)
            self.assertEqual(remote.read(), (final, done)); self.assertIsNone(done["active"])
            self.assertEqual(git(a, "show", f"{final}:forecast-evidence.txt"), b"immutable\n")
            self.assertEqual(remote.head(), first)
            git(a, "merge-base", "--is-ancestor", first, final)


if __name__ == "__main__":
    unittest.main()
