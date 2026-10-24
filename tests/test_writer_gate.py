"""Durable ownership, trusted comments, fail-closed requests and real Git races."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from reliability import digest, load_json, stamp
from writer_gate import GateRejected, RemoteGate, allowed_path, check_owner, claim, finish, git, message, state_commit

NOW = datetime(2026, 10, 14, 3, tzinfo=timezone.utc)
HEAD = "a" * 40


def fixture():
    policy = load_json(ROOT / "config/handoff-policy.json")
    state = {"schema_version": "implementation-writer-state-v1", "policy_version": policy["version"],
             "policy_sha256": digest(policy), "revision": 0, "updated_at": stamp(NOW), "active": None,
             "requests": {}, "audit_ids": [], "finding_attempts": {}, "checkpoints": [],
             "readiness": {k: False for k in policy["readiness_requirements"]}}
    request = {"schema_version": "implementation-request-v1", "request_id": "probe-1", "run_id": "run-1",
               "audit_id": "transport-probe-1", "repository": policy["repository"], "pull_request": 1,
               "branch": policy["development_branch"], "policy_version": policy["version"],
               "policy_sha256": digest(policy), "evaluation_policy_version": policy["evaluation_policy_version"],
               "timing_policy_version": policy["timing_policy_version"], "reviewed_sha": HEAD,
               "kind": "read_only_probe", "scope": [], "finding_ids": []}
    request = message(comment("HANDOFF_REQUEST", request, policy), "HANDOFF_REQUEST", policy)
    return policy, state, request


def comment(marker, payload, policy, number=123):
    return {"id": number, "user": {**policy["trusted_requester"], "type": "User"},
            "html_url": f"https://github.com/{policy['repository']}/pull/1#issuecomment-{number}",
            "created_at": stamp(NOW), "updated_at": stamp(NOW),
            "body": f"### {marker}\n\n```json\n{json.dumps(payload)}\n```"}


def result(policy, request, end=HEAD, status="COMPLETED"):
    payload = {"run_id": request["run_id"], "request_id": request["request_id"], "start_sha": HEAD,
               "end_sha": end, "status": status, "deployed": False, "production_model_changed": False}
    return message(comment("CODEX_RESULT", payload, policy, 124), "CODEX_RESULT", policy)


class GateTests(unittest.TestCase):
    def assert_rejected(self, reason, function, *args, **kwargs):
        with self.assertRaises(GateRejected) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.reason, reason)

    def test_claim_then_readback_result_release_preserves_input(self):
        policy, state, request = fixture(); before = copy.deepcopy(state)
        active = claim(state, request, policy, HEAD, NOW)
        self.assertEqual(state, before)
        check_owner(active, policy, request["run_id"], HEAD)
        done = finish(active, result(policy, request), policy, HEAD, NOW)
        self.assertIsNone(done["active"])
        self.assertEqual(done["requests"][request["request_id"]]["status"], "COMPLETED")
        self.assertEqual(active["active"]["run_id"], "run-1")

    def test_duplicate_request_and_duplicate_audit_after_blocked_completion(self):
        policy, state, request = fixture()
        active = claim(state, request, policy, HEAD, NOW)
        done = finish(active, result(policy, request, status="BLOCKED"), policy, HEAD, NOW)
        self.assert_rejected("DUPLICATE_REQUEST_OR_AUDIT", claim, done, request, policy, HEAD, NOW)
        request["request_id"] = "new-id-same-audit"
        self.assert_rejected("DUPLICATE_REQUEST_OR_AUDIT", claim, done, request, policy, HEAD, NOW)

    def test_busy_never_expires_or_assumes_idle_from_age(self):
        policy, state, request = fixture(); active = claim(state, request, policy, HEAD, NOW)
        request.update(request_id="probe-2", run_id="run-2", audit_id="transport-2")
        self.assert_rejected("BUSY", claim, active, request, policy, HEAD, NOW + timedelta(days=365))

    def test_stale_head_policy_and_experiment_versions(self):
        policy, state, request = fixture()
        self.assert_rejected("STALE_HEAD", claim, state, request, policy, "b" * 40, NOW)
        request["policy_version"] = "old"
        self.assert_rejected("STALE_POLICY", claim, state, request, policy, HEAD, NOW)
        request["policy_version"] = policy["version"]; request["evaluation_policy_version"] = "old"
        self.assert_rejected("STALE_EXPERIMENT_VERSION", claim, state, request, policy, HEAD, NOW)
        request["evaluation_policy_version"] = policy["evaluation_policy_version"]; request["timing_policy_version"] = "old"
        self.assert_rejected("STALE_EXPERIMENT_VERSION", claim, state, request, policy, HEAD, NOW)

    def test_markers_and_display_names_are_not_authentication(self):
        policy, _, _ = fixture(); raw = comment("HANDOFF_REQUEST", {}, policy)
        raw["user"]["id"] = 0
        self.assert_rejected("UNTRUSTED_AUTHOR", message, raw, "HANDOFF_REQUEST", policy)
        raw["user"] = {**policy["trusted_requester"], "type": "Bot"}
        self.assert_rejected("UNTRUSTED_AUTHOR", message, raw, "HANDOFF_REQUEST", policy)
        raw["user"]["type"] = "User"; raw["body"] = "### HANDOFF_REQUEST\nplease start"
        self.assert_rejected("STRUCTURED_MESSAGE_REQUIRED", message, raw, "HANDOFF_REQUEST", policy)

    def test_comment_origin_duplicate_json_and_extra_blocks_rejected(self):
        policy, _, _ = fixture(); raw = comment("HANDOFF_REQUEST", {}, policy)
        raw["html_url"] = raw["html_url"].replace("/pull/1", "/pull/2")
        self.assert_rejected("WRONG_COMMENT_ORIGIN", message, raw, "HANDOFF_REQUEST", policy)
        raw = comment("HANDOFF_REQUEST", {}, policy); raw["body"] = '### HANDOFF_REQUEST\n```json\n{"id":1,"id":2}\n```'
        with self.assertRaises(ValueError): message(raw, "HANDOFF_REQUEST", policy)
        raw = comment("HANDOFF_REQUEST", {}, policy); raw["body"] += "\n```json\n{}\n```"
        self.assert_rejected("STRUCTURED_MESSAGE_REQUIRED", message, raw, "HANDOFF_REQUEST", policy)

    def test_edited_future_and_wrong_target_requests_rejected(self):
        policy, state, request = fixture(); request["_comment"]["updated_at"] = stamp(NOW + timedelta(seconds=1))
        self.assert_rejected("FUTURE_OR_EDITED_REQUEST", claim, state, request, policy, HEAD, NOW)
        request["_comment"]["updated_at"] = request["_comment"]["created_at"] = stamp(NOW + timedelta(seconds=1))
        self.assert_rejected("FUTURE_OR_EDITED_REQUEST", claim, state, request, policy, HEAD, NOW)
        request["_comment"]["updated_at"] = request["_comment"]["created_at"] = stamp(NOW)
        request["branch"] = "main"
        self.assert_rejected("WRONG_TARGET", claim, state, request, policy, HEAD, NOW)

    def test_default_disabled_cannot_be_bypassed_by_readiness_flags(self):
        policy, state, request = fixture(); state["readiness"] = {k: True for k in state["readiness"]}
        request.update(kind="implementation", scope=["tools/timing.py"], finding_ids=["finding-1"])
        self.assert_rejected("AUTOMATIC_IMPLEMENTATION_DISABLED", claim, state, request, policy, HEAD, NOW)

    def test_even_enabled_policy_needs_all_readiness_and_fixed_scope(self):
        policy, state, request = fixture(); policy["automatic_implementation_enabled"] = True
        request["policy_sha256"] = state["policy_sha256"] = digest(policy)
        request.update(kind="implementation", scope=["tools/timing.py"], finding_ids=["finding-1"])
        self.assert_rejected("READINESS_NOT_VERIFIED", claim, state, request, policy, HEAD, NOW)
        state["readiness"] = {k: True for k in state["readiness"]}
        request["scope"] = ["config/evaluation-policy.json"]
        self.assert_rejected("PROTECTED_OR_UNBOUNDED_SCOPE", claim, state, request, policy, HEAD, NOW)
        request["scope"] = ["tools/timing.py"]
        self.assert_rejected("VERIFIED_AUDIT_REFERENCE_REQUIRED", claim, state, request, policy, HEAD, NOW)
        audit = message(comment("AUDIT_REPORT", {"schema_version": "implementation-audit-v1", "audit_id": request["audit_id"],
                        "repository": policy["repository"], "pull_request": 1, "reviewed_sha": HEAD, "finding_ids": ["finding-1"]}, policy, 125), "AUDIT_REPORT", policy)
        request.update(audit_comment_id=125, audit_body_sha256=audit["_comment"]["body_sha256"])
        self.assertEqual(claim(state, request, policy, HEAD, NOW, audit)["active"]["scope"], ["tools/timing.py"])
        audit["reviewed_sha"] = "b" * 40
        self.assert_rejected("STALE_OR_WRONG_AUDIT_REFERENCE", claim, state, request, policy, HEAD, NOW, audit)

    def test_evidence_policies_permissions_and_traversal_protected(self):
        policy, _, _ = fixture()
        for name in ("data/forward/keep.json.gz", "pull/build.py", "config/handoff-policy.json", "AGENTS.md",
                     ".github/workflows/hourly.yml", "../tools/x.py", "/tools/x.py", "tools\\x.py", "tools//x.py"):
            self.assertFalse(allowed_path(name, policy), name)
        self.assertTrue(allowed_path("tests/test_timing.py", policy))

    def test_probe_cannot_claim_source_scope(self):
        policy, state, request = fixture(); request["scope"] = ["tools/timing.py"]
        self.assert_rejected("PROBE_CANNOT_EDIT_SOURCE", claim, state, request, policy, HEAD, NOW)

    def test_attempt_limit_requires_owner_attention(self):
        policy, state, request = fixture(); state["finding_attempts"]["repeated-failure"] = 2
        request["finding_ids"] = ["repeated-failure"]
        self.assert_rejected("ATTEMPT_LIMIT_OWNER_ATTENTION", claim, state, request, policy, HEAD, NOW)

    def test_other_owner_and_source_drift_fail_before_push(self):
        policy, state, request = fixture(); active = claim(state, request, policy, HEAD, NOW)
        self.assert_rejected("NOT_LEASE_OWNER", check_owner, active, policy, "another-run", HEAD)
        self.assert_rejected("SOURCE_HEAD_DRIFT", check_owner, active, policy, "run-1", "b" * 40)

    def test_release_needs_owner_exact_result_and_no_deployment(self):
        policy, state, request = fixture(); active = claim(state, request, policy, HEAD, NOW)
        report = result(policy, request); report["run_id"] = "another-run"
        self.assert_rejected("NOT_LEASE_OWNER", finish, active, report, policy, HEAD, NOW)
        report = result(policy, request); report["end_sha"] = "b" * 40
        self.assert_rejected("STALE_RESULT", finish, active, report, policy, HEAD, NOW)
        report = result(policy, request); report["deployed"] = True
        self.assert_rejected("UNSAFE_OR_INCOMPLETE_RESULT", finish, active, report, policy, HEAD, NOW)

    def test_probe_and_non_descendant_source_changes_never_release(self):
        policy, state, request = fixture(); active = claim(state, request, policy, HEAD, NOW)
        report = result(policy, request, end="b" * 40)
        self.assert_rejected("SOURCE_HISTORY_NOT_DESCENDANT", finish, active, report, policy, "b" * 40, NOW)
        self.assert_rejected("PROBE_CHANGED_SOURCE", finish, active, report, policy, "b" * 40, NOW, descendant=True)

    def test_state_hash_drift_and_unbounded_shapes_rejected(self):
        policy, state, request = fixture(); state["policy_sha256"] = "wrong"
        self.assert_rejected("STATE_POLICY_DRIFT", claim, state, request, policy, HEAD, NOW)
        state["policy_sha256"] = digest(policy); request["scope"] = [["nested"]]
        self.assert_rejected("INVALID_SCOPE", claim, state, request, policy, HEAD, NOW)

    def test_checkpoint_advances_expected_head_and_retains_manual_owner(self):
        policy, state, request = fixture(); active = claim(state, request, policy, HEAD, NOW)
        active["active"].update(kind="manual_owner", scope=["docs/notes.md"])
        report = result(policy, request, end="b" * 40)
        saved = finish(active, report, policy, "b" * 40, NOW, descendant=True, changed_paths=["docs/notes.md"], release=False)
        check_owner(saved, policy, "run-1", "b" * 40)
        self.assertEqual(saved["requests"]["probe-1"]["status"], "ACTIVE")
        self.assertFalse(saved["readiness"]["owner_handoff_complete"])
        self.assert_rejected("SOURCE_CHANGED_OUTSIDE_LEASE_SCOPE", finish, active, report, policy, "b" * 40, NOW,
                             descendant=True, changed_paths=["pull/build.py"])

    def test_timing_is_explicitly_unimplemented_and_primary_registry_preserved(self):
        timing = load_json(ROOT / "config/timing-policy.json")
        self.assertEqual(timing["implementation_status"], "REGISTERED_NOT_IMPLEMENTED")
        self.assertEqual(timing["timezone"], "America/Chicago")
        self.assertFalse(timing["production_changes"])
        self.assertEqual([p["seconds_before_kickoff"] for p in timing["checkpoints"]], [86400, 21600, 5400])
        primary = load_json(ROOT / "config/evaluation-policy.json")
        self.assertEqual(primary["version"], "phase2-evaluation-v1.1")
        self.assertEqual(primary["targets"], ["rec", "rush_att", "pass_yd"])


class GitRaceTests(unittest.TestCase):
    def test_two_isolated_writers_only_one_nonforce_claim_wins_and_source_is_untouched(self):
        policy, state, request = fixture()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); server = base / "remote.git"; a = base / "a"; b = base / "b"
            git(base, "init", "--bare", str(server)); git(base, "init", str(a))
            git(a, "config", "user.name", "Fixture"); git(a, "config", "user.email", "fixture@example.invalid")
            (a / "forecast-evidence.txt").write_text("must stay unchanged\n")
            target = a / policy["state_path"]; target.parent.mkdir(); target.write_text(json.dumps(state))
            git(a, "add", "."); git(a, "commit", "-m", "Fixture evidence and idle gate")
            first = git(a, "rev-parse", "HEAD").decode().strip()
            git(a, "remote", "add", "origin", str(server))
            git(a, "push", "origin", f"{first}:refs/heads/{policy['coordination_branch']}")
            git(a, "push", "origin", f"{first}:refs/heads/{policy['development_branch']}")
            git(base, "clone", str(server), str(b)); git(b, "config", "user.name", "Fixture")
            git(b, "config", "user.email", "fixture@example.invalid")
            requests = [copy.deepcopy(request), copy.deepcopy(request)]
            for i, req in enumerate(requests):
                req.update(reviewed_sha=first, request_id=f"probe-{i}", run_id=f"run-{i}", audit_id=f"audit-{i}")
            states = [claim(state, req, policy, first, NOW) for req in requests]
            candidates = [state_commit(root, first, new_state, policy["state_path"]) for root, new_state in zip((a,b), states)]
            barrier = threading.Barrier(2)
            def push(pair):
                root, candidate = pair; barrier.wait()
                try:
                    git(root, "push", "origin", f"{candidate}:refs/heads/{policy['coordination_branch']}")
                    return True
                except subprocess.CalledProcessError:
                    return False
            with ThreadPoolExecutor(max_workers=2) as executor:
                winners = list(executor.map(push, zip((a,b), candidates)))
            self.assertEqual(sum(winners), 1)
            remote = RemoteGate(a, policy, verify_target=False)
            actual, saved = remote.read()
            self.assertEqual(actual, candidates[winners.index(True)])
            self.assertEqual(saved, states[winners.index(True)])
            self.assertEqual(remote.head(), first)
            self.assertEqual(git(a, "show", f"{actual}:forecast-evidence.txt"), b"must stay unchanged\n")
            with self.assertRaises(GateRejected) as caught: remote.publish(first, states[0])
            self.assertEqual(caught.exception.reason, "CONCURRENT_STATE_CHANGE")
            self.assertEqual(git(a, "rev-list", "--count", actual).decode().strip(), "2")
            git(a, "merge-base", "--is-ancestor", first, actual)

    def test_state_commit_does_not_touch_existing_staging_or_worktree(self):
        policy, state, _ = fixture()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); git(root, "init"); git(root, "config", "user.name", "Fixture")
            git(root, "config", "user.email", "fixture@example.invalid")
            (root / "keep.txt").write_text("original\n"); git(root, "add", "."); git(root, "commit", "-m", "Fixture")
            head = git(root, "rev-parse", "HEAD").decode().strip()
            (root / "keep.txt").write_text("staged\n"); git(root, "add", "keep.txt")
            (root / "keep.txt").write_text("unsaved\n")
            before = git(root, "diff", "--cached"), git(root, "diff"), git(root, "status", "--porcelain")
            state_commit(root, head, state, policy["state_path"])
            self.assertEqual(before, (git(root, "diff", "--cached"), git(root, "diff"), git(root, "status", "--porcelain")))


if __name__ == "__main__":
    unittest.main()
