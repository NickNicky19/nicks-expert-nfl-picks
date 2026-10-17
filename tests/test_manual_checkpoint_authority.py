"""CLI authorization boundaries: remote inputs are mocks, never live claims."""
import copy
from contextlib import ExitStack, redirect_stdout
import io
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from test_manual_writer_gate import STATE_HEAD, acquire, manual_fixture, target
from test_writer_gate import HEAD, comment
import writer_gate


class ManualCheckpointAuthorityTests(unittest.TestCase):
    def run_cli(self, operation="checkpoint", *, authority="valid", pr_change=None,
                advance=False, safe=False, status="COMPLETED", result_change=False,
                publish_error=None, wrong_gate=False, wrong_report=False, dirty_worktree=False):
        policy, state, payload, raw_auth = manual_fixture()
        state = acquire(policy, state, raw_auth)
        if wrong_gate:
            state["active"]["manual_gate_sha256"] = "0" * 64
        head = "b" * 40 if advance else HEAD
        report = {"run_id": payload["run_id"], "request_id": payload["request_id"],
                  "start_sha": HEAD, "end_sha": head, "status": status,
                  "deployed": False, "production_model_changed": False}
        if wrong_report:
            report["run_id"] = "competing-run"
        raw_result = comment("CODEX_RESULT", report, policy, 124)
        repo, pr = target(policy, head)
        if pr_change:
            area, key, value = pr_change
            (repo if area == "repo" else pr["head"] if area == "head" else pr)[key] = value
        remote = MagicMock()
        remote.read.return_value = STATE_HEAD, state
        remote.head.return_value = head
        remote.publish.return_value = "e" * 40
        remote.publish.side_effect = publish_error
        changed_auth = copy.deepcopy(raw_auth)
        if authority == "edited":
            changed_auth["body"] += "\nWithdrawn by owner."
        elif authority == "unauthorized":
            changed_auth["user"]["id"] = 0
        result_reads = 0
        def fetch(_policy, number):
            nonlocal result_reads
            if number == 124:
                result_reads += 1
                fetched = copy.deepcopy(raw_result)
                if result_change and result_reads > 1:
                    fetched["body"] += "\nChanged after first read."
                return fetched
            if number != raw_auth["id"]:
                raise AssertionError("Unexpected comment ID")
            if authority == "deleted":
                raise OSError("HTTP 404: deleted owner authorization")
            return changed_auth
        argv = ["writer_gate.py", operation, "--comment-id", "124"]
        if safe:
            argv.append("--safe-release")
        output = io.StringIO()
        exit_code = 0
        def local_git(_root, operation, *_args):
            if operation == "status":
                return b" M tools/scorecard.py\n" if dirty_worktree else b""
            return b"tools/scorecard.py\n" if advance else b""
        with ExitStack() as stack:
            stack.enter_context(patch("writer_gate.RemoteGate", return_value=remote))
            comments = stack.enter_context(patch("writer_gate.fetched_comment", side_effect=fetch))
            targets = stack.enter_context(patch("writer_gate.fetched_manual_target", return_value=(repo, pr)))
            stack.enter_context(patch("writer_gate.git", side_effect=local_git))
            stack.enter_context(patch("writer_gate.subprocess.run", return_value=subprocess.CompletedProcess([], 0)))
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(redirect_stdout(output))
            try:
                writer_gate.main()
            except SystemExit as error:
                exit_code = error.code
        return exit_code, output.getvalue(), remote, comments, targets, state

    def blocked(self, **kwargs):
        code, output, remote, *_ = self.run_cli(**kwargs)
        self.assertEqual(code, 2, output)
        remote.publish.assert_not_called()
        return output

    def test_checkpoint_rejects_edited_authorization(self):
        self.assertIn("MANUAL_AUTHORIZATION_CHANGED", self.blocked(authority="edited"))

    def test_checkpoint_rejects_deleted_authorization(self):
        self.assertIn("OSError", self.blocked(authority="deleted"))

    def test_checkpoint_rejects_unauthorized_original_comment(self):
        self.assertIn("UNTRUSTED_AUTHOR", self.blocked(authority="unauthorized"))

    def test_checkpoint_rejects_closed_pr(self):
        self.assertIn("WRONG_OR_STALE_MANUAL_TARGET",
                      self.blocked(pr_change=("pr", "state", "closed")))

    def test_checkpoint_rejects_stale_pr_head(self):
        self.assertIn("WRONG_OR_STALE_MANUAL_TARGET",
                      self.blocked(pr_change=("head", "sha", "c" * 40)))

    def test_checkpoint_rejects_wrong_repository_and_branch(self):
        for change in (("repo", "id", 0), ("head", "ref", "main")):
            with self.subTest(change=change):
                self.blocked(pr_change=change)

    def test_checkpoint_rejects_result_changed_before_publish(self):
        self.assertIn("RESULT_CHANGED", self.blocked(result_change=True))

    def test_checkpoint_success_advances_only_with_fresh_authority_and_source_binding(self):
        code, output, remote, comments, targets, before = self.run_cli(advance=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(comments.call_count, 3)
        self.assertEqual(targets.call_count, 1)
        self.assertEqual(remote.publish.call_args.kwargs, {"expected_source": "b" * 40})
        updated = remote.publish.call_args.args[1]
        self.assertEqual(updated["active"]["source_head"], "b" * 40)
        self.assertEqual(updated["readiness"], before["readiness"])

    def test_checkpoint_source_race_is_passed_to_nonforce_publisher(self):
        code, output, remote, *_ = self.run_cli(publish_error=writer_gate.GateRejected("SOURCE_HEAD_DRIFT"))
        self.assertEqual(code, 2)
        self.assertIn("SOURCE_HEAD_DRIFT", output)
        self.assertEqual(remote.publish.call_args.kwargs, {"expected_source": HEAD})

    def test_finish_rejects_new_source_after_revocation(self):
        self.blocked(operation="finish", authority="edited", advance=True)

    def test_normal_finish_rejects_deleted_authorization_and_closed_pr(self):
        self.blocked(operation="finish", authority="deleted")
        self.blocked(operation="finish", pr_change=("pr", "state", "closed"))

    def test_normal_finish_with_new_source_requires_fresh_authority(self):
        code, output, remote, comments, targets, _ = self.run_cli(operation="finish", advance=True)
        self.assertEqual(code, 0, output)
        self.assertIsNone(remote.publish.call_args.args[1]["active"])
        self.assertEqual(comments.call_count, 3)
        self.assertEqual(targets.call_count, 1)
        self.assertEqual(remote.publish.call_args.kwargs, {"expected_source": "b" * 40})

    def test_explicit_safe_release_works_after_deletion_and_closed_pr_without_source_edits(self):
        code, output, remote, comments, targets, before = self.run_cli(
            operation="finish", safe=True, authority="deleted", status="BLOCKED",
            pr_change=("pr", "state", "closed"))
        self.assertEqual(code, 0, output)
        self.assertEqual(comments.call_count, 2)
        self.assertEqual(targets.call_count, 1)
        updated = remote.publish.call_args.args[1]
        self.assertIsNone(updated["active"])
        self.assertEqual(updated["requests"]["manual-1"]["status"], "BLOCKED")
        self.assertEqual(updated["readiness"], before["readiness"])
        self.assertEqual(remote.publish.call_args.kwargs, {"expected_source": HEAD})

    def test_safe_release_cannot_acknowledge_new_source_or_completed_work(self):
        self.blocked(operation="finish", safe=True, advance=True, status="BLOCKED")
        self.blocked(operation="finish", safe=True, status="COMPLETED")

    def test_safe_release_cannot_checkpoint_or_cross_target(self):
        self.blocked(safe=True, status="BLOCKED")
        self.blocked(operation="finish", safe=True, status="BLOCKED",
                     pr_change=("head", "ref", "main"))

    def test_safe_release_does_not_bypass_gate_digest_or_owner(self):
        self.blocked(operation="finish", safe=True, status="BLOCKED", wrong_gate=True)
        self.blocked(operation="finish", safe=True, status="BLOCKED", wrong_report=True)

    def test_safe_release_cannot_leave_unpublished_worktree_edits(self):
        self.assertIn("SAFE_RELEASE_REQUIRES_CLEAN_WORKTREE",
                      self.blocked(operation="finish", safe=True, status="BLOCKED", dirty_worktree=True))


if __name__ == "__main__":
    unittest.main()
