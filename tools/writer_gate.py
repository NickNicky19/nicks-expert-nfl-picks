"""Cooperative, fail-closed Phase 2 writer gate. No scheduler or model changes.

The durable state lives on a separate append-only branch in the SAME repository.
Claims use sibling commits and an ordinary non-force Git push: only one sibling
can fast-forward the remote ref. There is no timeout takeover. A marker alone
does not authorize a request. Native cloud entrypoint adoption remains unverified.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

from reliability import IntegrityError, _pairs, canonical, digest, load_json, stamp, utc

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}\Z")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z")
MANUAL_GATE_VERSION = "phase2-manual-writer-v1"
HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class GateRejected(IntegrityError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def reject(reason):
    raise GateRejected(reason)


def strict_json(text):
    def invalid(_):
        reject("NONFINITE_JSON")
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=invalid)


def message(comment, marker, policy):
    """Verify a freshly fetched GitHub identity and exactly one structured body."""
    user = comment.get("user", {})
    trusted = policy["trusted_requester"]
    if user.get("id") != trusted["id"] or user.get("login") != trusted["login"] or user.get("type") != "User":
        reject("UNTRUSTED_AUTHOR")
    expected_url = f"https://github.com/{policy['repository']}/pull/{policy['pull_request']}#issuecomment-{comment.get('id')}"
    if type(comment.get("id")) is not int or comment.get("html_url") != expected_url:
        reject("WRONG_COMMENT_ORIGIN")
    body = comment.get("body", "")
    if not re.match(rf"\A### {re.escape(marker)}(?:\s|$)", body):
        reject("WRONG_MESSAGE_MARKER")
    blocks = re.findall(r"```json\s*\n(.*?)\n```", body, flags=re.S)
    if len(blocks) != 1:
        reject("STRUCTURED_MESSAGE_REQUIRED")
    payload = strict_json(blocks[0])
    if not isinstance(payload, dict):
        reject("INVALID_MESSAGE")
    payload = copy.deepcopy(payload)
    payload["_comment"] = {"id": comment["id"], "url": comment["html_url"], "author": trusted, "marker": marker,
                           "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "created_at": comment["created_at"],
                           "updated_at": comment["updated_at"]}
    return payload


def validate_state(state, policy):
    if state.get("schema_version") != "implementation-writer-state-v1":
        reject("UNKNOWN_STATE_SCHEMA")
    if state.get("policy_version") != policy["version"] or state.get("policy_sha256") != digest(policy):
        reject("STATE_POLICY_DRIFT")
    if type(state.get("revision")) is not int or state["revision"] < 0:
        reject("INVALID_STATE_REVISION")
    if not isinstance(state.get("requests"), dict) or not isinstance(state.get("audit_ids"), list):
        reject("INVALID_REQUEST_LEDGER")
    if set(state.get("readiness", {})) != set(policy["readiness_requirements"]):
        reject("INVALID_READINESS")
    if any(type(v) is not bool for v in state["readiness"].values()):
        reject("INVALID_READINESS")


def allowed_path(name, policy):
    if not isinstance(name, str) or not name or "\\" in name:
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or str(path) != name:
        return False
    def matches(pattern):
        return name.startswith(pattern) if pattern.endswith("/") else name == pattern
    return any(matches(p) for p in policy["allowed_scope"]) and not any(matches(p) for p in policy["protected_scope"])


def changed(state, now):
    result = copy.deepcopy(state)
    result["revision"] += 1
    result["updated_at"] = stamp(utc(now))
    return result


def claim(state, request, policy, source_head, now, audit=None):
    """Pure transition. Callers must publish with compare/readback + non-force."""
    return _claim(state, request, policy, source_head, now, audit)


def verify_manual_target(policy, source_head, repository, pull_request):
    """Require fresh server metadata, not just the configured Git remote URL."""
    head = pull_request.get("head", {})
    head_repo = head.get("repo") or {}
    if (type(repository.get("id")) is not int or repository["id"] != policy["repository_id"]
            or repository.get("full_name") != policy["repository"]
            or head_repo.get("id") != policy["repository_id"] or head_repo.get("full_name") != policy["repository"]
            or type(pull_request.get("number")) is not int or pull_request["number"] != policy["pull_request"]
            or pull_request.get("html_url") != f"https://github.com/{policy['repository']}/pull/{policy['pull_request']}"
            or pull_request.get("state") != "open" or pull_request.get("merged") is not False
            or head.get("ref") != policy["development_branch"] or head.get("sha") != source_head):
        reject("WRONG_OR_STALE_MANUAL_TARGET")


def entrypoint_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def verify_active_manual_authorization(active, raw_comment, policy):
    reread = message(raw_comment, "MANUAL_OWNER_AUTHORIZATION", policy)
    if reread["_comment"] != active["request_comment"]:
        reject("MANUAL_AUTHORIZATION_CHANGED")


def claim_manual(state, raw_comment, policy, source_head, state_head, now, *,
                 run_id, repository, pull_request, gate_sha256):
    """Explicit owner authorization; never accepted by the automatic claim path."""
    request = message(raw_comment, "MANUAL_OWNER_AUTHORIZATION", policy)
    if (request.get("schema_version") != "manual-writer-authorization-v1"
            or request.get("kind") != "manual_owner"
            or request.get("approval") != "OWNER_APPROVED_MANUAL_EXECUTION"
            or request.get("native_dispatch") is not False
            or request.get("boundaries") != policy["boundaries"]):
        reject("EXPLICIT_MANUAL_AUTHORIZATION_REQUIRED")
    if not run_id or request.get("run_id") != run_id:
        reject("WRONG_MANUAL_RUN")
    if (type(request.get("repository_id")) is not int
            or request["repository_id"] != policy["repository_id"]):
        reject("WRONG_TARGET")
    verify_manual_target(policy, source_head, repository, pull_request)
    if (not isinstance(state_head, str) or not SHA.fullmatch(state_head)
            or request.get("coordination_sha") != state_head):
        reject("STALE_COORDINATION_HEAD")
    if (request.get("gate_version") != MANUAL_GATE_VERSION
            or not isinstance(gate_sha256, str) or not HEX_DIGEST.fullmatch(gate_sha256)
            or request.get("gate_sha256") != gate_sha256):
        reject("STALE_MANUAL_GATE")
    result = _claim(state, request, policy, source_head, now, manual=True)
    result["active"].update(manual_gate_version=MANUAL_GATE_VERSION, manual_gate_sha256=gate_sha256,
                            authorized_coordination_sha=state_head)
    return result


def _claim(state, request, policy, source_head, now, audit=None, *, manual=False):
    validate_state(state, policy)
    schema = "manual-writer-authorization-v1" if manual else "implementation-request-v1"
    if request.get("schema_version") != schema:
        reject("UNKNOWN_REQUEST_SCHEMA")
    for key in ("request_id", "run_id", "audit_id"):
        if not isinstance(request.get(key), str) or not IDENTIFIER.fullmatch(request[key]):
            reject("INVALID_REQUEST_ID")
    comment = request.get("_comment", {})
    if comment.get("author") != policy["trusted_requester"]:
        reject("UNTRUSTED_AUTHOR")
    if request.get("repository") != policy["repository"] or request.get("pull_request") != policy["pull_request"] or request.get("branch") != policy["development_branch"]:
        reject("WRONG_TARGET")
    if request.get("policy_version") != policy["version"] or request.get("policy_sha256") != digest(policy):
        reject("STALE_POLICY")
    for field in ("evaluation_policy_version", "timing_policy_version"):
        if request.get(field) != policy[field]:
            reject("STALE_EXPERIMENT_VERSION")
    if not isinstance(source_head, str) or not SHA.fullmatch(source_head) or request.get("reviewed_sha") != source_head:
        reject("STALE_HEAD")
    if utc(comment["created_at"]) > utc(now) or utc(comment["updated_at"]) != utc(comment["created_at"]):
        reject("FUTURE_OR_EDITED_REQUEST")
    if request["request_id"] in state["requests"] or request["audit_id"] in state["audit_ids"]:
        reject("DUPLICATE_REQUEST_OR_AUDIT")
    if state.get("active") is not None:
        reject("BUSY")
    kind = request.get("kind")
    if kind not in (("manual_owner",) if manual else ("read_only_probe", "implementation")):
        reject("UNKNOWN_REQUEST_KIND")
    scope = request.get("scope")
    if not isinstance(scope, list) or any(not isinstance(p, str) for p in scope) or len(scope) != len(set(scope)):
        reject("INVALID_SCOPE")
    if kind == "read_only_probe" and scope:
        reject("PROBE_CANNOT_EDIT_SOURCE")
    if kind in ("implementation", "manual_owner"):
        if not scope or not all(allowed_path(p, policy) for p in scope):
            reject("PROTECTED_OR_UNBOUNDED_SCOPE")
    if kind == "manual_owner":
        if policy.get("automatic_implementation_enabled") is not False:
            reject("MANUAL_REQUIRES_AUTOMATIC_DISABLED")
        if not state["readiness"].get("owner_handoff_complete") or not state["readiness"].get("rejection_tests_verified"):
            reject("MANUAL_PREREQUISITES_NOT_VERIFIED")
    if kind == "implementation":
        if policy.get("automatic_implementation_enabled") is not True:
            reject("AUTOMATIC_IMPLEMENTATION_DISABLED")
        if not all(state["readiness"].values()):
            reject("READINESS_NOT_VERIFIED")
    findings = request.get("finding_ids", [])
    if not isinstance(findings, list) or any(not isinstance(f, str) or not IDENTIFIER.fullmatch(f) for f in findings) or len(findings) != len(set(findings)):
        reject("INVALID_FINDINGS")
    if any(state["finding_attempts"].get(f, 0) >= policy["maximum_attempts_per_finding"] for f in findings):
        reject("ATTEMPT_LIMIT_OWNER_ATTENTION")
    if kind in ("implementation", "manual_owner") and not findings:
        reject("AUDIT_FINDING_REQUIRED")
    if kind == "implementation":
        if not isinstance(audit, dict) or audit.get("_comment", {}).get("author") != policy["trusted_requester"]:
            reject("VERIFIED_AUDIT_REFERENCE_REQUIRED")
        if (audit.get("schema_version") != "implementation-audit-v1" or audit.get("audit_id") != request["audit_id"]
                or audit.get("repository") != policy["repository"] or audit.get("pull_request") != policy["pull_request"]
                or audit.get("reviewed_sha") != source_head or audit["_comment"].get("id") != request.get("audit_comment_id")
                or audit["_comment"].get("body_sha256") != request.get("audit_body_sha256")):
            reject("STALE_OR_WRONG_AUDIT_REFERENCE")
        if utc(audit["_comment"]["updated_at"]) != utc(audit["_comment"]["created_at"]) or utc(audit["_comment"]["created_at"]) > utc(comment["created_at"]):
            reject("EDITED_OR_FUTURE_AUDIT")
        if not set(findings).issubset(audit.get("finding_ids", [])):
            reject("FINDING_NOT_IN_REFERENCED_AUDIT")
    result = changed(state, now)
    result["active"] = {"request_id": request["request_id"], "run_id": request["run_id"], "kind": kind,
                        "owner": policy["trusted_requester"], "source_head": source_head,
                        "acquired_at": stamp(utc(now)), "request_comment": comment, "scope": scope}
    result["requests"][request["request_id"]] = {"status": "ACTIVE", "run_id": request["run_id"],
                                                "kind": kind, "audit_id": request["audit_id"],
                                                "request_comment": comment}
    result["audit_ids"].append(request["audit_id"])
    for finding in findings:
        result["finding_attempts"][finding] = result["finding_attempts"].get(finding, 0) + 1
    return result


def check_owner(state, policy, run_id, source_head, *, gate_sha256=None):
    validate_state(state, policy)
    active = state.get("active")
    if active is None or active.get("run_id") != run_id or active.get("owner") != policy["trusted_requester"]:
        reject("NOT_LEASE_OWNER")
    if active.get("kind") == "bootstrap_reservation":
        reject("BOOTSTRAP_NOT_IMPLEMENTATION_LEASE")
    if active.get("manual_gate_sha256") is not None and active["manual_gate_sha256"] != gate_sha256:
        reject("STALE_MANUAL_GATE")
    if active.get("source_head") != source_head:
        reject("SOURCE_HEAD_DRIFT")
    return active


def finish(state, report, policy, source_head, now, *, descendant=False, changed_paths=(), release=True,
           gate_sha256=None):
    """Release only this owner after an exact, freshly read-back result comment."""
    validate_state(state, policy)
    active = state.get("active")
    if active is None or active.get("run_id") != report.get("run_id") or report.get("request_id") != active["request_id"]:
        reject("NOT_LEASE_OWNER")
    if active.get("kind") == "bootstrap_reservation":
        reject("BOOTSTRAP_NOT_IMPLEMENTATION_LEASE")
    if active.get("manual_gate_sha256") is not None and active["manual_gate_sha256"] != gate_sha256:
        reject("STALE_MANUAL_GATE")
    if report.get("_comment", {}).get("author") != policy["trusted_requester"]:
        reject("UNTRUSTED_RESULT_AUTHOR")
    if report.get("start_sha") != active["source_head"] or report.get("end_sha") != source_head or not SHA.fullmatch(source_head):
        reject("STALE_RESULT")
    if report.get("status") not in ("COMPLETED", "BLOCKED") or report.get("deployed") is not False or report.get("production_model_changed") is not False:
        reject("UNSAFE_OR_INCOMPLETE_RESULT")
    if utc(report["_comment"]["created_at"]) > utc(now) or utc(report["_comment"]["updated_at"]) != utc(report["_comment"]["created_at"]):
        reject("FUTURE_OR_EDITED_RESULT")
    if source_head != active["source_head"] and not descendant:
        reject("SOURCE_HISTORY_NOT_DESCENDANT")
    if active["kind"] == "read_only_probe" and source_head != active["source_head"]:
        reject("PROBE_CHANGED_SOURCE")
    if any(p not in active["scope"] for p in changed_paths):
        reject("SOURCE_CHANGED_OUTSIDE_LEASE_SCOPE")
    result = changed(state, now)
    result["requests"][active["request_id"]].update(status=report["status"] if release else "ACTIVE", result_comment=report["_comment"],
                                                   start_sha=report["start_sha"], end_sha=source_head)
    result["checkpoints"].append({"run_id": report["run_id"], "result_comment": report["_comment"], "end_sha": source_head})
    if release:
        result["active"] = None
    else:
        result["active"]["source_head"] = source_head
    if release and active["kind"] == "manual_owner":
        result["readiness"]["owner_handoff_complete"] = True
    return result


def git(root, *args, input=None, env=None):
    return subprocess.check_output(["git", "-C", str(root), *args], input=input, env=env, stderr=subprocess.PIPE)


def state_commit(root, parent, state, state_path):
    """Build one-parent state commit without touching worktree or staged changes."""
    with tempfile.TemporaryDirectory(prefix="nfl-writer-index-") as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        git(root, "read-tree", parent, env=env)
        blob = git(root, "hash-object", "-w", "--stdin", input=canonical(state) + b"\n").decode().strip()
        git(root, "update-index", "--add", "--cacheinfo", f"100644,{blob},{state_path}", env=env)
        tree = git(root, "write-tree", env=env).decode().strip()
        return git(root, "commit-tree", tree, "-p", parent, input=f"Writer gate revision {state['revision']}\n".encode()).decode().strip()


class RemoteGate:
    def __init__(self, root, policy, remote="origin", *, verify_target=True):
        self.root, self.policy, self.remote = Path(root), policy, remote
        if verify_target:
            url = git(root, "remote", "get-url", remote).decode().strip()
            repo = re.escape(policy["repository"])
            if not re.fullmatch(rf"(?:https://github\.com/|git@github\.com:){repo}(?:\.git)?", url):
                reject("WRONG_REMOTE")

    def fetch_ref(self, branch):
        target = f"refs/remotes/{self.remote}/{branch}"
        git(self.root, "fetch", "--no-tags", self.remote, f"refs/heads/{branch}:{target}")
        return git(self.root, "rev-parse", target).decode().strip()

    def read(self):
        commit = self.fetch_ref(self.policy["coordination_branch"])
        payload = strict_json(git(self.root, "show", f"{commit}:{self.policy['state_path']}").decode())
        validate_state(payload, self.policy)
        return commit, payload

    def head(self):
        return self.fetch_ref(self.policy["development_branch"])

    def publish(self, expected_commit, state, *, expected_source=None):
        current, _ = self.read()
        if current != expected_commit:
            reject("CONCURRENT_STATE_CHANGE")
        if expected_source is not None and self.head() != expected_source:
            reject("SOURCE_HEAD_DRIFT")
        candidate = state_commit(self.root, expected_commit, state, self.policy["state_path"])
        try:
            # Sibling claims cannot both fast-forward this ref. No force flag.
            git(self.root, "push", self.remote, f"{candidate}:refs/heads/{self.policy['coordination_branch']}")
        except subprocess.CalledProcessError:
            reject("CONCURRENT_STATE_CHANGE_OR_PUSH_BLOCKED")
        actual, payload = self.read()
        if actual != candidate or payload != state:
            reject("STATE_READBACK_FAILED")
        if expected_source is not None and self.head() != expected_source:
            # The reservation remains; do not edit, retry, or silently release it.
            reject("SOURCE_HEAD_DRIFT")
        return candidate


def fetched_comment(policy, comment_id):
    import requests
    response = requests.get(f"https://api.github.com/repos/{policy['repository']}/issues/comments/{comment_id}", timeout=30)
    response.raise_for_status()
    return response.json()


def fetched_manual_target(policy):
    import requests
    prefix = f"https://api.github.com/repos/{policy['repository']}"
    result = []
    for url in (prefix, f"{prefix}/pulls/{policy['pull_request']}"):
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        result.append(response.json())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("show", "claim", "claim-manual", "check", "checkpoint", "finish"))
    parser.add_argument("--run-id")
    parser.add_argument("--comment-id", type=int)
    args = parser.parse_args()
    policy = load_json(ROOT / "config/handoff-policy.json")
    remote = RemoteGate(ROOT, policy)
    try:
        state_commit_sha, state = remote.read()
        source_head = remote.head()
        now = datetime.now(timezone.utc)
        if args.operation == "show":
            print(json.dumps({"state_commit": state_commit_sha, "source_head": source_head, "active": state["active"],
                              "automatic_implementation_enabled": policy["automatic_implementation_enabled"], "readiness": state["readiness"]}))
        elif args.operation == "check":
            active = check_owner(state, policy, args.run_id, source_head, gate_sha256=entrypoint_sha256())
            if active.get("manual_gate_sha256") is not None:
                verify_active_manual_authorization(active, fetched_comment(policy, active["request_comment"]["id"]), policy)
                verify_manual_target(policy, source_head, *fetched_manual_target(policy))
            print(json.dumps({"status": "LEASE_OWNER_VERIFIED", "state_commit": state_commit_sha, "source_head": source_head}))
        else:
            if not args.comment_id:
                parser.error("claim/claim-manual/checkpoint/finish require an actual GitHub --comment-id")
            raw = fetched_comment(policy, args.comment_id)
            if args.operation == "claim-manual":
                if not args.run_id:
                    parser.error("claim-manual requires the exact authorized --run-id")
                repository, pull_request = fetched_manual_target(policy)
                updated = claim_manual(state, raw, policy, source_head, state_commit_sha, now,
                                       run_id=args.run_id, repository=repository, pull_request=pull_request,
                                       gate_sha256=entrypoint_sha256())
                # Bind the actual comment again immediately before publication.
                reread = message(fetched_comment(policy, args.comment_id), "MANUAL_OWNER_AUTHORIZATION", policy)
                if reread["_comment"] != updated["active"]["request_comment"]:
                    reject("MANUAL_AUTHORIZATION_CHANGED")
                verify_manual_target(policy, source_head, *fetched_manual_target(policy))
            elif args.operation == "claim":
                request = message(raw, "HANDOFF_REQUEST", policy)
                audit = None
                if request.get("kind") == "implementation" and type(request.get("audit_comment_id")) is int:
                    audit = message(fetched_comment(policy, request["audit_comment_id"]), "AUDIT_REPORT", policy)
                updated = claim(state, request, policy, source_head, now, audit)
            else:
                report = message(raw, "CODEX_RESULT", policy)
                if state.get("active") is None:
                    reject("NOT_LEASE_OWNER")
                if state["active"].get("kind") == "bootstrap_reservation":
                    reject("BOOTSTRAP_NOT_IMPLEMENTATION_LEASE")
                original = state["active"]["source_head"]
                descendant = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", original, source_head], capture_output=True).returncode == 0
                paths = git(ROOT, "diff", "--name-only", original, source_head).decode().splitlines()
                updated = finish(state, report, policy, source_head, now, descendant=descendant, changed_paths=paths,
                                 release=args.operation == "finish", gate_sha256=entrypoint_sha256())
            published = remote.publish(state_commit_sha, updated,
                                       expected_source=source_head if args.operation == "claim-manual" else None)
            print(json.dumps({"status": "READBACK_VERIFIED", "state_commit": published, "source_head": source_head}))
    except (GateRejected, subprocess.CalledProcessError, OSError) as error:
        print(json.dumps({"status": "REJECTED_OR_BLOCKED", "reason": getattr(error, "reason", type(error).__name__),
                          "automatic_loop_active": False}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
