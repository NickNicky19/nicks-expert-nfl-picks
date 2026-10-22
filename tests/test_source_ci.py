"""Small real-Git controls; GitHub/runtime records are explicitly fictional.

These are source-CI gate unit tests, not a hosted run, model proof or job budget.
"""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import source_ci as ci


ENV = {"python": {"version": "fictional-3.12", "binary_sha256": "1" * 64},
       "node": {"version": "fictional-22", "binary_sha256": "2" * 64},
       "git": {"version": "fictional-git", "binary_sha256": "3" * 64},
       "image": {"os": "fictional-linux", "version": "fictional-fixed-image", "architecture": "x86_64"},
       "distributions": [{"name": "fictional-requests", "version": "1"}],
       "installed_files_sha256": "4" * 64, "installed_files": 2}


class API:
    def __init__(self, source, runtime):
        self.source = source
        self.runs = [self.run(101)]
        self.details = {101: copy.deepcopy(self.runs[0])}
        self.job = dict(id=202, run_id=101, run_attempt=1, name=ci.JOB_NAME,
                        head_sha=source["commit"], status="completed", conclusion="success",
                        steps=[dict(name=name, conclusion="success") for name in ci.REQUIRED_STEPS])
        self.seal = dict(schema_version=ci.VERSION, repository=ci.REPOSITORY, repository_id=ci.REPOSITORY_ID,
                         run_id=101, run_attempt=1, event="push", branch="upgrade/phase2-reproducible-comparison",
                         workflow_path=ci.WORKFLOW_PATH, job_name=ci.JOB_NAME, checks=list(ci.CHECKS),
                         **{k: source[k] for k in ("commit", "tree", "source_manifest_sha256", "files")}, environment=runtime)
        self.workflow = dict(id=ci.WORKFLOW_ID, path=ci.WORKFLOW_PATH, state="active")
        self.repository = dict(id=ci.REPOSITORY_ID, full_name=ci.REPOSITORY, private=False)
        self.log_override = None; self.on_log = None; self.run_reads = 0; self.on_run = None
        self.list_reads = 0; self.on_list = None

    def run(self, number):
        return dict(id=number, head_sha=self.source["commit"], workflow_id=ci.WORKFLOW_ID,
                    head_branch="upgrade/phase2-reproducible-comparison", event="push", run_attempt=1,
                    status="completed", conclusion="success", created_at=f"2026-10-22T01:{number % 60:02d}:00Z",
                    run_started_at=f"2026-10-22T01:{number % 60:02d}:01Z",
                    repository={"id": ci.REPOSITORY_ID}, head_repository={"id": ci.REPOSITORY_ID})

    def get(self, path, *, logs=False):
        if path == "": return copy.deepcopy(self.repository)
        if path == f"/actions/workflows/{ci.WORKFLOW_ID}": return copy.deepcopy(self.workflow)
        if path == f"/actions/workflows/{ci.WORKFLOW_ID}/runs?per_page=100":
            self.list_reads += 1
            if self.on_list: self.on_list(self)
            return dict(total_count=len(self.runs), workflow_runs=copy.deepcopy(self.runs))
        if path.startswith("/actions/runs/") and path.count("/") == 3:
            self.run_reads += 1
            if self.on_run: self.on_run(self)
            return copy.deepcopy(self.details[int(path.split("/")[-1])])
        if "/attempts/" in path:
            if "/jobs?" not in path:
                return copy.deepcopy(self.details[int(path.split("/")[3])])
            return dict(total_count=1, jobs=[copy.deepcopy(self.job)])
        if path == "/actions/jobs/202/logs" and logs:
            if self.on_log: self.on_log()
            return self.log_override if self.log_override is not None else b"2026-10-22T01:42:00.123Z " + ci.PREFIX.encode() + ci.canonical(self.seal) + b"\n"
        raise AssertionError("Undeclared fictional API route: " + path)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fictional source gate")
        self.git("config", "user.email", "fictional@example.invalid")
        self.files = {"tools/engine.py": b"one\n", "tools/source_ci.py": b"# Fictional helper source\n",
                      "tests/test_example.py": b"# Fictional test source\n", "config/phase2.json": b'{"capture_enabled":true}\n',
                      ci.WORKFLOW_PATH: b"# Fictional tested workflow\n", "output/app.js": b"// Fictional static app\n",
                      "requirements.txt": b"fictional-requests\n", ".gitignore": b"__pycache__/\n*.pyc\n",
                      ci.FIXTURE: b"WHOLLY FICTIONAL fixed regression fixture, no original-evidence claim\n",
                      "data/cache/current.json": b'{"fictional":1}\n'}
        for name, raw in self.files.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        self.commit()
        self.environment = patch.object(ci, "environment", return_value=copy.deepcopy(ENV))
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.source = ci.source(self.root); self.api = API(self.source, copy.deepcopy(ENV))

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def commit(self):
        self.git("add", "."); self.git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "Wholly fictional source gate fixture")

    def verify(self, **kwargs):
        return ci.verify(self.root, api=self.api, **kwargs)

    def test_complete_current_source_pass_and_unchanged_data_descendant_keep_distinct_commit_ids(self):
        first = self.verify()
        (self.root / "data/cache/current.json").write_bytes(b'{"fictional":2}\n'); self.commit()
        second = self.verify()
        self.assertNotEqual(first["executed_commit"], second["executed_commit"])
        self.assertEqual(second["source_ci_commit"], first["source_ci_commit"])
        self.assertEqual(second["source_manifest_sha256"], first["source_manifest_sha256"])
        self.assertIn("NOT_GENERATION_OR_OPERATING", second["claim"])

    def test_actual_two_parent_merge_with_tested_source_ancestor_is_supported(self):
        tested = self.source["commit"]
        (self.root / "data/cache/current.json").write_bytes(b'{"fictional":3}\n'); self.commit()
        parent = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        merge = self.git("commit-tree", tree, "-p", parent, "-p", tested, "-m", "Fictional normal protected integration")
        self.git("reset", "--hard", merge)  # Isolated test repository only.
        result = self.verify()
        self.assertEqual(result["executed_commit"], merge)
        self.assertEqual(result["source_ci_commit"], tested)
        self.assertEqual(len(self.git("rev-list", "--parents", "-n", "1", "HEAD").split()), 3)

    def test_unrelated_equal_tree_is_rejected_and_forward_restore_of_tested_source_is_supported(self):
        tested_tree = self.source["tree"]
        unrelated = self.git("commit-tree", tested_tree, "-m", "Fictional unrelated equal-content root")
        self.git("reset", "--hard", unrelated)
        with self.assertRaises(ci.Rejected): self.verify()
        self.git("reset", "--hard", self.source["commit"])
        path = self.root / "tools/engine.py"; path.write_bytes(b"two\n"); self.commit()
        with self.assertRaises(ci.Rejected): self.verify()
        path.write_bytes(self.files["tools/engine.py"]); self.commit()
        self.assertEqual(self.verify()["source_ci_commit"], self.source["commit"])

    def test_same_size_restored_mtime_source_test_workflow_config_and_fixture_mutations_reject(self):
        for name in ("tools/engine.py", "tests/test_example.py", "config/phase2.json", ci.WORKFLOW_PATH, "output/app.js", ci.FIXTURE):
            path = self.root / name; original = path.read_bytes(); info = path.stat()
            with self.subTest(path=name):
                path.write_bytes(bytes([original[0] ^ 1]) + original[1:]); os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                with self.assertRaises(ci.Rejected): self.verify()
            path.write_bytes(original); os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))

    def test_untracked_ignored_source_mode_missing_and_new_unrecognized_data_lane_fail(self):
        path = self.root / "tools/hidden.py"
        (self.root / ".git/info/exclude").write_text("tools/hidden.py\n")
        path.write_text("# Fictional ignored executable input\n")
        with self.assertRaises(ci.Rejected): self.verify()
        path.unlink()
        engine = self.root / "tools/engine.py"; engine.chmod(0o755)
        with self.assertRaises(ci.Rejected): self.verify()
        engine.chmod(0o644); engine.unlink()
        with self.assertRaises(ci.Rejected): self.verify()
        engine.write_bytes(self.files["tools/engine.py"])
        extra = self.root / "data/unrecognized/new.json"; extra.parent.mkdir(); extra.write_text("{}")
        self.commit()
        with self.assertRaises(ci.Rejected): self.verify()

    def test_accepted_new_generated_evidence_does_not_claim_it_was_tested_or_qualified(self):
        path = self.root / "data/verification/fictional-failure.json"; path.write_text('{"fictional_failure_marker":true}')
        self.commit()
        self.assertIn("NOT_GENERATION_OR_OPERATING", self.verify()["claim"])
        self.assertNotIn(str(path), str(self.verify()))

    def test_newest_compatible_failed_pending_or_cancelled_run_blocks_old_success(self):
        for status, conclusion in (("completed", "failure"), ("in_progress", None), ("completed", "cancelled")):
            with self.subTest(status=status, conclusion=conclusion):
                newer = self.api.run(102); newer.update(status=status, conclusion=conclusion)
                self.api.runs = [self.api.runs[0], newer]; self.api.details[102] = newer
                with self.assertRaises(ci.Rejected): self.verify()
        with self.assertRaises(ci.Rejected): self.verify(run_id=101)

    def test_fork_pr_wrong_repository_or_wrong_workflow_do_not_supply_a_pass(self):
        variants = ({"head_repository": {"id": 123}}, {"event": "pull_request"}, {"repository": {"id": 123}}, {"workflow_id": 123})
        original = copy.deepcopy(self.api.runs[0])
        for change in variants:
            with self.subTest(change=change):
                self.api.runs = [{**original, **change}]
                with self.assertRaises(ci.Rejected): self.verify()
        self.api.runs = [original]; self.api.workflow["path"] = ".github/workflows/unrelated.yml"
        with self.assertRaises(ci.Rejected): self.verify()

    def test_every_required_step_must_pass_and_seal_is_last_regular_step(self):
        original = copy.deepcopy(self.api.job)
        for name in ci.REQUIRED_STEPS:
            with self.subTest(skipped=name):
                self.api.job = copy.deepcopy(original)
                next(s for s in self.api.job["steps"] if s["name"] == name)["conclusion"] = "skipped"
                with self.assertRaises(ci.Rejected): self.verify()
        self.api.job = copy.deepcopy(original); self.api.job["steps"].append(dict(name="Unexpected later check", conclusion="success"))
        with self.assertRaises(ci.Rejected): self.verify()

    def test_missing_duplicate_wrong_generation_and_unknown_contract_seals_reject(self):
        original = copy.deepcopy(self.api.seal)
        for change in ({"schema_version": "unknown"}, {"commit": "0" * 40}, {"tree": "0" * 40},
                       {"source_manifest_sha256": "0" * 64}, {"files": []}, {"checks": []}, {"run_attempt": 2}):
            with self.subTest(change=change):
                self.api.seal = {**original, **change}
                with self.assertRaises(ci.Rejected): self.verify()
        self.api.seal = original
        for raw in (b"", ci.PREFIX.encode() + ci.canonical(original) + b"\n" + ci.PREFIX.encode() + ci.canonical(original)):
            self.api.log_override = raw
            with self.assertRaises(ci.Rejected): self.verify()

    def test_runtime_distribution_byte_or_version_change_rejects_matching_source(self):
        for key in ("installed_files_sha256", "distributions", "python", "image"):
            changed = copy.deepcopy(ENV); changed[key] = "fictional changed dependency"
            with self.subTest(key=key), patch.object(ci, "environment", return_value=changed):
                with self.assertRaises(ci.Rejected): self.verify()

    def test_source_runtime_rerun_and_new_run_races_fail_at_final_boundary(self):
        path = self.root / "tools/engine.py"
        self.api.on_log = lambda: path.write_bytes(b"two\n")
        with self.assertRaises(ci.Rejected): self.verify()
        path.write_bytes(self.files["tools/engine.py"]); self.api.on_log = None
        changed = copy.deepcopy(ENV); changed["installed_files_sha256"] = "f" * 64
        with patch.object(ci, "environment", side_effect=[copy.deepcopy(ENV), changed]):
            with self.assertRaises(ci.Rejected): self.verify()
        self.api.run_reads = 0
        self.api.on_run = lambda api: api.details[101].update(run_attempt=2) if api.run_reads == 2 else None
        with self.assertRaises(ci.Rejected): self.verify()
        self.api.details[101]["run_attempt"] = 1; self.api.on_run = None; self.api.list_reads = 0
        self.api.on_list = lambda api: api.runs.append(api.run(102)) if api.list_reads == 2 else None
        with self.assertRaises(ci.Rejected): self.verify()

    def test_final_run_and_list_transport_mutations_are_detected_after_all_reads(self):
        path = self.root / "tools/engine.py"
        with tempfile.TemporaryDirectory() as dependency_root:
            dependency_path = Path(dependency_root) / "fictional_installed.py"
            for hook in ("on_run", "on_list"):
                for dependency in (False, True):
                    with self.subTest(hook=hook, dependency=dependency):
                        self.api.run_reads = 0; self.api.list_reads = 0
                        dependency_path.write_bytes(b"dep1\n"); dep_info = dependency_path.stat()
                        def runtime(*args):
                            result = copy.deepcopy(ENV)
                            result["installed_files_sha256"] = ci._file_hash(dependency_path)[1]
                            return result
                        self.api.seal["environment"] = runtime()
                        original = path.read_bytes(); info = path.stat()
                        def mutate(api):
                            count = api.run_reads if hook == "on_run" else api.list_reads
                            if count != 2: return
                            if dependency:
                                dependency_path.write_bytes(b"dep2\n")
                                os.utime(dependency_path, ns=(dep_info.st_atime_ns, dep_info.st_mtime_ns))
                            else:
                                path.write_bytes(b"two\n")
                                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                        setattr(self.api, hook, mutate)
                        with patch.object(ci, "environment", side_effect=runtime):
                            with self.assertRaises(ci.Rejected): self.verify()
                        path.write_bytes(original); os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                        setattr(self.api, hook, None)

    def test_older_run_latest_attempt_execution_blocks_newer_original_run_success(self):
        newer = self.api.run(102)
        self.api.runs.append(newer); self.api.details[102] = copy.deepcopy(newer)
        old = self.api.runs[0]
        old.update(run_attempt=2, run_started_at="2026-10-22T02:00:00Z")
        for status, conclusion in (("in_progress", None), ("completed", "failure")):
            with self.subTest(status=status):
                old.update(status=status, conclusion=conclusion)
                self.api.details[101] = copy.deepcopy(old)
                with self.assertRaises(ci.Rejected): self.verify()
        old.update(status="completed", conclusion="success")
        self.api.details[101] = copy.deepcopy(old)
        self.api.job["run_attempt"] = 2; self.api.seal["run_attempt"] = 2
        self.assertEqual(self.verify()["run_attempt"], 2)
        self.api.details[101]["run_started_at"] = "2026-10-22T02:01:00Z"
        with self.assertRaises(ci.Rejected): self.verify()
        old.pop("run_started_at")
        with self.assertRaises(ci.Rejected): self.verify()

    def test_complete_bounded_pagination_rejects_missing_duplicates_overflow_and_count_race(self):
        route = "/fictional/runs?per_page=100"
        records = [dict(id=number) for number in range(1, 102)]
        pages = [{"total_count": 101, "workflow_runs": records[:100]}, {"total_count": 101, "workflow_runs": records[100:]}]
        api = types.SimpleNamespace(get=lambda path: copy.deepcopy(pages[0 if "page=2" not in path else 1]))
        self.assertEqual(len(ci._runs(api, route)["workflow_runs"]), 101)
        for change in ({"total_count": 1001}, {"workflow_runs": []}, {"total_count": 102}, {"workflow_runs": [records[0]]}):
            original = copy.deepcopy(pages[1]); pages[1].update(change)
            with self.subTest(change=change), self.assertRaises(ci.Rejected): ci._runs(api, route)
            pages[1] = original

    def test_sourceless_bytecode_is_not_hidden_by_generated_cache_exclusion(self):
        import py_compile
        path = self.root / "tools/fictional_shadow.py"; path.write_text("value = 'fictional sourceless code'\n")
        py_compile.compile(str(path), cfile=str(path.with_suffix(".pyc")), doraise=True)
        path.unlink()
        with tempfile.TemporaryDirectory() as cache:
            env = dict(os.environ, PYTHONPYCACHEPREFIX=cache, PYTHONDONTWRITEBYTECODE="1")
            env.pop("PYTHONPATH", None)
            raw = subprocess.check_output([sys.executable, "-B", "-c", "import sys;sys.path.insert(0,sys.argv[1]);import fictional_shadow;print(fictional_shadow.value)", str(path.parent)], env=env)
            self.assertEqual(raw.strip(), b"fictional sourceless code")
        # Real CPython imported it even with a fresh prefix; our actual source
        # inventory must reject the untracked executable, including ignored pyc.
        with self.assertRaises(ci.Rejected): self.verify()

    def test_executable_under_mutable_data_lane_is_a_source_dependency(self):
        path = self.root / "data/cache/inject.py"; path.write_text("x=1\n")
        with self.assertRaises(ci.Rejected): self.verify()
        self.commit()
        with self.assertRaises(ci.Rejected): self.verify()
        self.assertIn("data/cache/inject.py", {item["path"] for item in ci.source(self.root)["files"]})

    def test_json_log_and_source_size_bounds_are_enforced(self):
        with self.assertRaises(ci.Rejected): ci.decoded(b'{"a":1,"a":2}')
        with self.assertRaises(ci.Rejected): ci.decoded(b"{}", limit=1)
        with patch.object(ci, "LOG_LIMIT", 5), self.assertRaises(ci.Rejected): ci._log_seal(b"too many bytes")
        with patch.object(ci, "FILE_LIMIT", 2), self.assertRaises(ci.Rejected): ci.source(self.root)
        with patch.object(ci, "SOURCE_LIMIT", 2), self.assertRaises(ci.Rejected): ci.source(self.root)

    def test_git_replace_grafts_and_execution_overrides_are_rejected(self):
        replacement = self.git("commit-tree", self.source["tree"], "-m", "Fictional replacement graph")
        self.git("replace", self.source["commit"], replacement)
        with self.assertRaises(ci.Rejected): self.verify()
        self.git("replace", "-d", self.source["commit"])
        path = self.root / ".git/info/grafts"; path.write_text(self.source["commit"] + "\n")
        with self.assertRaises(ci.Rejected): self.verify()
        path.unlink()
        for key in ("GIT_DIR", "GIT_OBJECT_DIRECTORY", "GIT_GRAFT_FILE", "GIT_CONFIG_PARAMETERS"):
            with self.subTest(key=key), patch.dict(os.environ, {key: "fictional override"}), self.assertRaises(ci.Rejected):
                self.verify()

    def test_complete_seal_matches_post_install_initial_fingerprint_and_rejects_runtime_change(self):
        context = dict(repository=ci.REPOSITORY, repository_id=ci.REPOSITORY_ID, run_id=101, run_attempt=1,
                       event="push", branch="upgrade/phase2-reproducible-comparison", workflow_path=ci.WORKFLOW_PATH, job_name=ci.JOB_NAME)
        mode = types.SimpleNamespace(read_mode=lambda _: "phase1", read_phase2=lambda _: True)
        initial = ci.fingerprint(self.root)
        with patch.object(ci, "_context", return_value=context), patch.dict(os.environ, GITHUB_SHA=self.source["commit"]), patch.dict(sys.modules, release_mode=mode):
            value = ci.seal(self.root, initial)
            self.assertEqual(value["checks"], list(ci.CHECKS))
            changed = copy.deepcopy(ENV); changed["installed_files_sha256"] = "0" * 64
            with patch.object(ci, "environment", return_value=changed), self.assertRaises(ci.Rejected): ci.seal(self.root, initial)
            mode.read_phase2 = lambda _: False
            with self.assertRaises(ci.Rejected): ci.seal(self.root, initial)


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "fictional_package"; self.package.mkdir()
        (self.package / "module.py").write_text("value = 1\n")
        self.metadata = self.root / "fictional_package-1.dist-info"; self.metadata.mkdir()
        (self.metadata / "METADATA").write_text("Name: fictional-package\nVersion: 1\n")
        (self.metadata / "RECORD").write_text("fictional_package/module.py,,\nfictional_package-1.dist-info/METADATA,,\nfictional_package-1.dist-info/RECORD,,\n")
        distribution = types.SimpleNamespace(_path=self.metadata, metadata={"Name": "fictional-package"}, version="1", locate_file=lambda name: self.root / name)
        self.binary = self.root / "runtime"; self.binary.write_bytes(b"fictional runtime binary")
        self.stack = __import__("contextlib").ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(ci.importlib.metadata, "distributions", return_value=[distribution]))
        self.stack.enter_context(patch.object(ci.shutil, "which", return_value=str(self.binary)))
        self.stack.enter_context(patch.object(ci, "command", return_value=(b"fictional-runtime-version", 0)))
        self.stack.enter_context(patch.object(ci.sys, "executable", str(self.binary)))
        self.standard_temp = tempfile.TemporaryDirectory(); self.addCleanup(self.standard_temp.cleanup)
        self.standard = Path(self.standard_temp.name); self.dynamic = self.standard / "lib-dynload"; self.dynamic.mkdir()
        (self.standard / "fictional_stdlib.py").write_text("stdlib = 1\n")
        (self.dynamic / "fictional.so").write_bytes(b"fictional extension 1")
        self.cache_temp = tempfile.TemporaryDirectory(); self.addCleanup(self.cache_temp.cleanup)
        self.cache = Path(self.cache_temp.name)
        self.stack.enter_context(patch.object(ci.sysconfig, "get_path", return_value=str(self.standard)))
        original_config = {"SOABI": ci.sysconfig.get_config_var("SOABI"), "Py_ENABLE_SHARED": 0}
        self.stack.enter_context(patch.object(ci.sysconfig, "get_config_var", side_effect=lambda name: str(self.dynamic) if name == "DESTSHARED" else original_config.get(name)))
        self.stack.enter_context(patch.object(ci.sys, "path", [str(self.root), str(self.standard), str(self.dynamic)]))
        self.stack.enter_context(patch.object(ci.sys, "pycache_prefix", str(self.cache)))
        self.stack.enter_context(patch.object(ci.sys, "dont_write_bytecode", True))
        loader = {name: value for name, value in os.environ.items() if not name.startswith(("PYTHON", "NODE_", "LD_", "DYLD_")) and name not in ("BASH_ENV", "ENV")}
        loader.update(PYTHONPYCACHEPREFIX=str(self.cache), PYTHONDONTWRITEBYTECODE="1")
        self.stack.enter_context(patch.dict(os.environ, loader, clear=True))

    def test_actual_installed_file_mutation_with_restored_size_and_mtime_changes_identity(self):
        original = ci.environment(); path = self.package / "module.py"; info = path.stat()
        path.write_text("value = 2\n"); os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        changed = ci.environment()
        self.assertEqual(original["distributions"], changed["distributions"])
        self.assertNotEqual(original["installed_files_sha256"], changed["installed_files_sha256"])

    def test_new_unmanaged_file_missing_declared_file_and_symlink_are_not_accepted(self):
        original = ci.environment(); path = self.root / "unmanaged.py"; path.write_text("fictional=1\n")
        self.assertNotEqual(original["installed_files_sha256"], ci.environment()["installed_files_sha256"])
        path.unlink(); target = self.package / "module.py"; raw = target.read_bytes(); target.unlink()
        with self.assertRaises(ci.Rejected): ci.environment()
        target.write_bytes(raw); link = self.root / "linked.py"; link.symlink_to(target)
        with self.assertRaises(ci.Rejected): ci.environment()

    def test_generated_bytecode_and_record_values_are_excluded_but_enumeration_is_bounded(self):
        original = ci.environment()
        (self.package / "__pycache__").mkdir(); (self.package / "__pycache__/module.pyc").write_bytes(b"fictional generated bytecode")
        (self.metadata / "RECORD").write_text("fictional_package/module.py,ignored-untrusted-old-hash,1\nfictional_package-1.dist-info/METADATA,,\n")
        self.assertEqual(original["installed_files_sha256"], ci.environment()["installed_files_sha256"])
        with patch.object(ci, "ENTRY_LIMIT", 1), self.assertRaises(ci.Rejected): ci.environment()

    def test_standard_source_and_dynamic_extension_same_size_mutations_change_runtime(self):
        for path in (self.standard / "fictional_stdlib.py", self.dynamic / "fictional.so"):
            with self.subTest(path=path.name):
                before = ci.environment(); raw = path.read_bytes(); info = path.stat()
                path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:]); os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                self.assertNotEqual(before["standard_files_sha256"], ci.environment()["standard_files_sha256"])
                path.write_bytes(raw)

    def test_runtime_loader_overrides_unknown_import_roots_and_stale_pycache_reject(self):
        for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE", "PYTHONINSPECT", "NODE_OPTIONS", "NODE_PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "BASH_ENV"):
            with self.subTest(key=key), patch.dict(os.environ, {key: "fictional-override"}), self.assertRaises(ci.Rejected): ci.environment()
        with tempfile.TemporaryDirectory() as unexpected, patch.object(ci.sys, "path", [unexpected]), self.assertRaises(ci.Rejected): ci.environment()
        (self.cache / "poison.pyc").write_bytes(b"fictional invalid cached code")
        with self.assertRaises(ci.Rejected): ci.environment()
        (self.cache / "poison.pyc").unlink()
        with patch.object(ci.sys, "dont_write_bytecode", False), self.assertRaises(ci.Rejected): ci.environment()
        with patch.dict(os.environ, PYTHONPYCACHEPREFIX=""), self.assertRaises(ci.Rejected): ci.environment()


    def test_setup_python_exact_loader_path_hashes_actual_shared_library(self):
        prefix_temp = tempfile.TemporaryDirectory(); self.addCleanup(prefix_temp.cleanup)
        prefix = Path(prefix_temp.name); library = prefix / "lib"; library.mkdir()
        actual = library / "libpython-fictional.so.1"; actual.write_bytes(b"fictional shared Python 1")
        (library / "libpython-fictional.so").symlink_to(actual.name)
        def config(name):
            return {"DESTSHARED": str(self.dynamic), "SOABI": "fictional", "Py_ENABLE_SHARED": 1, "LDLIBRARY": "libpython-fictional.so"}.get(name)
        with patch.object(ci.sys, "base_prefix", str(prefix)), patch.object(ci.sysconfig, "get_config_var", side_effect=config), patch.dict(os.environ, LD_LIBRARY_PATH=str(library)):
            before = ci.environment(); raw = actual.read_bytes(); info = actual.stat()
            actual.write_bytes(raw[:-1] + b"2"); os.utime(actual, ns=(info.st_atime_ns, info.st_mtime_ns))
            self.assertNotEqual(before["python"]["shared_library"], ci.environment()["python"]["shared_library"])
            with patch.dict(os.environ, LD_LIBRARY_PATH=str(library) + ":/fictional/extra"), self.assertRaises(ci.Rejected): ci.environment()



class TransportTests(unittest.TestCase):
    def test_command_output_is_bounded_during_reading(self):
        with self.assertRaises(ci.Rejected):
            ci.command([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*2000000)"], limit=1024)

    def test_log_redirect_strips_authorization_and_uses_no_cache(self):
        calls = []
        class Response(io.BytesIO):
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        class Opener:
            def open(self, request, timeout):
                calls.append(request)
                if len(calls) == 1:
                    raise ci.urllib.error.HTTPError(request.full_url, 302, "fictional redirect", {"Location": "https://fictional.blob.core.windows.net/log?sig=fictional"}, None)
                return Response(b"fictional log")
        with patch.dict(os.environ, GH_TOKEN="fictional-token", GITHUB_TOKEN="fictional-token"), patch.object(ci.urllib.request, "build_opener", return_value=Opener()):
            self.assertEqual(ci.GitHub().get("/actions/jobs/202/logs", logs=True), b"fictional log")
        self.assertTrue(calls[0].get_header("Authorization") == "Bearer fictional-token", "Only the fictional authorization may be used")
        self.assertEqual(calls[0].get_header("Cache-control"), "no-cache")
        self.assertIsNone(calls[1].get_header("Authorization"))

    def test_unapproved_redirect_and_oversized_api_body_are_rejected(self):
        class Opener:
            def open(self, request, timeout):
                raise ci.urllib.error.HTTPError(request.full_url, 302, "fictional redirect", {"Location": "https://unapproved.example/credential-test"}, None)
        with patch.object(ci.urllib.request, "build_opener", return_value=Opener()), self.assertRaises(ci.Rejected):
            ci.GitHub().get("/actions/jobs/202/logs", logs=True)
        class Response(io.BytesIO):
            headers = {"Content-Length": "999999999"}
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        opener = types.SimpleNamespace(open=lambda *args, **kwargs: Response(b"{}"))
        with patch.object(ci.urllib.request, "build_opener", return_value=opener), self.assertRaises(ci.Rejected):
            ci.GitHub().get("/actions/runs/101")


if __name__ == "__main__": unittest.main()
