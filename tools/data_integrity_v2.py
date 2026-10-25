"""Closed presence-aware source dispatch; no collector or replacement engine.

V1 evidence is reproduced by retained V1 code in its own process/source root.
V2 never catches a V1 failure or changes an original registration. Live cutover
requires its own approved plan; the existing configuration cannot activate it.
"""
from contextlib import contextmanager
import hashlib
import json
import copy
import io
import os
from pathlib import Path
import subprocess
import shutil
import statistics
import tempfile
import types

from reliability import BASELINE_BLOBS, ENGINE_PATHS, IntegrityError, digest, load_json, utc

ROOT = Path(__file__).resolve().parents[1]
MODEL = "sleeper-matchup-data-integrity-v2"
CLASSIC_MODEL = "sleeper-matchup-classic-data-integrity-v2"
PRESENCE_MODELS = (MODEL, CLASSIC_MODEL)
PRESENCE = "nfl-data-presence-v2"
INPUTS = "matchup-inputs-v3"
PROOF = "matchup-proof-v2"
NATIVE = "baseline-capture-v2"
OUTCOMES = "forecast-outcomes-v2"
DESCRIPTIVE_OUTCOMES = "descriptive-statistic-outcomes-v2"
SCORECARD = "forecast-scorecard-v2"
VALIDATOR = "partial-week-data-integrity-v2"
PLAN = "partial-week-data-integrity-plan-v2"
MODEL_INPUT_HASH = "typed-model-input-json-v1"
LEGACY_SOURCE = "bf3ec09129e918b73641a65af5f05ecd5559139a"
LEGACY_TREE = "a7fa1863483d38fbda3eac4f6edbdbe26acfaccf"
RETAINED_CORRECTED_SOURCE = "b3de2fbd88ba3247b407a856972285ad10527b99"
RETAINED_CORRECTED_TREE = "c0d0d818f8e1266f55851c8c220d44cd94797c78"
RETAINED_CORRECTED_HELPERS = {
    "tools/data_integrity_v2.py": "7fb3ed03ff5b22dbe1aa9a0db4ae830fe540ace732e0a0199b0e82c93533cf49",
    "tools/build_recorded.py": "9c3106332cf522068c0d861e4288370b4bd0bb2acb69eaec440b5b1f37919c87",
    "tools/reliability.py": "a8bd3eced472598330ed3d4db0e9fb9c2715206c44254ce6af983b5afc0faf3b"}
V2_PATHS = ENGINE_PATHS + ("pull/grade.py",)
# Filled from the actual completed implementation, never from a caller/receipt.
V2_SOURCE_SHA256 = {'pull/build.py': 'd8a1094af872c84e0fe092662a1241afc0eceaca8c27f7bea687e6a1be2f576c', 'pull/matchup.py': 'eaf627730041060ad16dd9930accfe54a54cf5fb49bb42d18680b5c572ddd7a5', 'pull/scoring.py': '473e8fa2601d75eab8a223edda53555c51ce145c6426e570df9ae918c3f9eee0', 'pull/books.py': '0b89744960136a4f2e594b61e6df754d357706d8c66a8ae359d8eb02bbfa53f8', 'pull/gamemodel.py': '2a2519a12ad4993da02ae6bdcdb6c86f2b5a6554ce93a702b550ecde17fb7d1f', 'pull/sources.py': '36555cdbc55d73ba632d5adae1130288f4f532073857c642ac3ebc7e626b0061', 'pull/news.py': '17ce1b3b6b72694e6b543bd767e287c26a9d1f6dd5dba2de6c873543036842e9', 'pull/grade.py': 'cf4bccf4fd960d5cc896d5e8bbef216a7d84cd20ca938ce1c60ca7942c307d2f'}
CLASSIC_SOURCE_SHA256 = {
    "pull/books.py": "0b89744960136a4f2e594b61e6df754d357706d8c66a8ae359d8eb02bbfa53f8",
    "pull/build.py": "726378a2ae5f7a1cedb1bd1538d49e77a5a6bbf9805c07eb89fc9fd4bdd92cbf",
    "pull/gamemodel.py": "2a2519a12ad4993da02ae6bdcdb6c86f2b5a6554ce93a702b550ecde17fb7d1f",
    "pull/grade.py": "b260a2a7905eea7caf4b14115e94fd6898c0e0fc6cdd19e28de96ccc38da394a",
    "pull/matchup.py": "eaf627730041060ad16dd9930accfe54a54cf5fb49bb42d18680b5c572ddd7a5",
    "pull/news.py": "17ce1b3b6b72694e6b543bd767e287c26a9d1f6dd5dba2de6c873543036842e9",
    "pull/scoring.py": "712be92bb30d6486fd4d04d3cc43a2d1482b9ade42cb6c50194fe745c0ef5ae9",
    "pull/sources.py": "36555cdbc55d73ba632d5adae1130288f4f532073857c642ac3ebc7e626b0061",
}
RETAINED_ROOT_SOURCE = "67c1c4a202d22b316e719446010ba1b39e66f9e4"
RETAINED_ROOT_TREE = "994ed7a0de513b7fed9d513db411eda0016342a9"
RETAINED_ROOT_HELPERS = {
    "tools/data_integrity_v2.py": "f60798eca7071525727bd883e6bd230fdb5422297efb6a7748a3457a212ab3e7",
    "tools/build_recorded.py": "101e2a7cff6cc1cc5dba32de1930a241642eb0a0ec80dda7f9feb5e79076a03e",
    "tools/reliability.py": "6462ed6cd708c98b88f7e13fcd82330d6f32c6fc6fb39d7554f1ec8ad7fbe2cd",
}


def source_hashes(model):
    """Return only a copy of an installed closed presence-source contract."""
    if model == MODEL:
        return dict(V2_SOURCE_SHA256)
    if model == CLASSIC_MODEL:
        return dict(CLASSIC_SOURCE_SHA256)
    raise IntegrityError("Unsupported presence model")


def _source_bytes(root):
    root = Path(root).resolve()
    result = {}
    for name in V2_PATHS:
        path = root / name
        if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root)
                or path.stat().st_size > 2 * 1024 * 1024):
            raise IntegrityError("Corrected source path is not a bounded plain file")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def active_model(root=ROOT):
    """Recognize freshly hashed source; recognition has no activation effects."""
    actual = _source_bytes(root)
    for model in PRESENCE_MODELS:
        if actual == source_hashes(model):
            return model
    raise IntegrityError("Unrecognized installed presence source")


def _retained_families():
    return {
        "b3": (RETAINED_CORRECTED_SOURCE, RETAINED_CORRECTED_TREE, RETAINED_CORRECTED_HELPERS),
        "root67": (RETAINED_ROOT_SOURCE, RETAINED_ROOT_TREE, RETAINED_ROOT_HELPERS),
    }


def _source_file(repository, commit, name):
    """Bound and authenticate the actual Git blob, never a working-tree alias."""
    size = int(_git(repository, "cat-file", "-s", commit + ":" + name))
    if not 0 <= size <= 2 * 1024 * 1024:
        raise IntegrityError("Source blob exceeds bound")
    raw = _git(repository, "cat-file", "blob", commit + ":" + name)
    oid = _git(repository, "rev-parse", commit + ":" + name).decode().strip()
    if len(raw) != size or hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest() != oid:
        raise IntegrityError("Source blob identity mismatch")
    return raw


def _source_commit(repository, commit):
    size = int(_git(repository, "cat-file", "-s", commit))
    if not 0 <= size <= 1024 * 1024:
        raise IntegrityError("Source commit exceeds bound")
    raw = _git(repository, "cat-file", "commit", commit)
    if (len(raw) != size or hashlib.sha1(b"commit " + str(size).encode() + b"\0" + raw).hexdigest() != commit
            or raw.splitlines()[0] != b"tree " + _git(repository, "rev-parse", commit + "^{tree}").strip()):
        raise IntegrityError("Source commit/tree identity mismatch")


def _retained_profile(commit, *, repository=ROOT):
    if not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise IntegrityError("Invalid corrected source commit")
    _source_commit(repository, commit)
    for family, (_, _, helpers) in _retained_families().items():
        expected = {**V2_SOURCE_SHA256, **helpers}
        if all(hashlib.sha256(_source_file(repository, commit, name)).hexdigest() == value
               for name, value in expected.items()):
            return family
    return None


def model_input_hash(value):
    """Typed tree prevents nonfinite markers from colliding with actual objects."""
    import math
    def typed(item):
        if isinstance(item, dict):
            return ["object", [[key, typed(item[key])] for key in sorted(item)]]
        if isinstance(item, list):
            return ["array", [typed(child) for child in item]]
        if isinstance(item, float) and not math.isfinite(item):
            return ["nonfinite", "nan" if math.isnan(item) else "+infinity" if item > 0 else "-infinity"]
        return ["atom", item]
    return digest({"format": MODEL_INPUT_HASH, "value": typed(value)})


def _git(root, *args):
    return subprocess.check_output(["git", "--no-replace-objects", "-C", str(root),
        "-c", "core.hooksPath=/dev/null", *args], stderr=subprocess.PIPE)


def _legacy_blob(name, repository=ROOT):
    commit = _git(repository, "cat-file", "commit", LEGACY_SOURCE)
    if hashlib.sha1(b"commit " + str(len(commit)).encode() + b"\0" + commit).hexdigest() != LEGACY_SOURCE:
        raise IntegrityError("Retained original commit object is corrupt")
    if _git(repository, "rev-parse", LEGACY_SOURCE + "^{tree}").decode().strip() != LEGACY_TREE:
        raise IntegrityError("Retained approved V1 source tree unavailable")
    raw = _git(repository, "cat-file", "blob", LEGACY_SOURCE + ":" + name)
    if name in BASELINE_BLOBS:
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if blob != BASELINE_BLOBS[name]:
            raise IntegrityError("Retained original engine identity mismatch")
    return raw


def _legacy_graph(repository=ROOT, *, source=LEGACY_SOURCE, tree=LEGACY_TREE, objects_out=None):
    """Fresh bounded commit/tree/blob closure, including all retained helpers."""
    dispatcher_identity()
    commit = _git(repository, "cat-file", "commit", source)
    if tree is None:
        tree = commit.splitlines()[0].decode().removeprefix("tree ")
    if (hashlib.sha1(b"commit " + str(len(commit)).encode() + b"\0" + commit).hexdigest() != source
            or commit.splitlines()[0] != ("tree " + tree).encode()):
        raise IntegrityError("Retained original commit/tree identity mismatch")
    entries, objects = [], {tree: "tree"}
    for item in _git(repository, "ls-tree", "-r", "-t", "-z", source, "--", "pull", "tools", "config").split(b"\0"):
        if not item:
            continue
        metadata, name = item.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        path = name.decode()
        if (kind not in ("tree", "blob") or mode != ("040000" if kind == "tree" else "100644")
                or ".." in Path(path).parts or Path(path).is_absolute()):
            raise IntegrityError("Unsupported retained source object")
        objects[oid] = kind
        if kind == "blob":
            entries.append((path, oid))
    if len(objects) > 2048:
        raise IntegrityError("Retained source graph exceeds object bound")
    query = "".join(oid + "\n" for oid in objects).encode()
    command = ["git", "--no-replace-objects", "-C", str(repository), "cat-file", "--batch"]
    with tempfile.TemporaryFile() as requests:
        requests.write(query)
        requests.seek(0)
        with subprocess.Popen(command, stdin=requests, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
            raw = child.stdout.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                child.kill()
                raise IntegrityError("Retained source graph exceeds byte bound")
            child.stderr.read()
            if child.wait() != 0:
                raise IntegrityError("Retained source object graph unavailable")
    stream, content = io.BytesIO(raw), {}
    for oid, kind in objects.items():
        header = stream.readline().decode().strip().split()
        if len(header) != 3 or header[:2] != [oid, kind] or not header[2].isdigit():
            raise IntegrityError("Retained source object header mismatch")
        size = int(header[2])
        if size > 4 * 1024 * 1024:
            raise IntegrityError("Retained source object exceeds bound")
        value = stream.read(size)
        if len(value) != size or stream.read(1) != b"\n" or hashlib.sha1(
                kind.encode() + b" " + str(size).encode() + b"\0" + value).hexdigest() != oid:
            raise IntegrityError("Retained source object checksum mismatch")
        content[oid] = value
    if stream.read(1):
        raise IntegrityError("Unexpected retained source graph bytes")
    if objects_out is not None:
        objects_out[source] = ("commit", commit)
        objects_out.update({oid: (objects[oid], value) for oid, value in content.items()})
    return [(name, oid, content[oid]) for name, oid in entries], [
        (oid, objects[oid], hashlib.sha256(value).hexdigest()) for oid, value in content.items()]


def legacy_dependency_inventory(repository=ROOT, *, evidence_root=None, _objects=None):
    _, inventory = _legacy_graph(repository)
    import classic_model_v1 as classic
    classic_objects = classic.scoring_objects(repository)
    if _objects is not None:
        _objects.update(classic_objects)
    classic_inventory = [(oid, kind, hashlib.sha256(raw).hexdigest())
                         for oid, (kind, raw) in sorted(classic_objects.items())]
    families = {}
    for family, (source, tree, helpers) in _retained_families().items():
        entries, retained = _legacy_graph(repository, source=source, tree=tree, objects_out=_objects)
        values = {name: hashlib.sha256(raw).hexdigest() for name, _, raw in entries}
        if any(values.get(name) != expected for name, expected in {**V2_SOURCE_SHA256, **helpers}.items()):
            raise IntegrityError("Retained corrected source/helper identity mismatch")
        families[family] = {"commit": source, "tree": tree, "objects": retained}
    if _objects is not None:
        _legacy_graph(repository, objects_out=_objects)
    sources = {}
    if evidence_root is not None:
        from evidence import read
        verification = Path(evidence_root) / "data/verification"
        paths = list(verification.glob("*/w*/*.json.gz")) + list(
            (verification / "partial-registrations").glob("*/w*/*.json.gz"))
        if len(paths) > 16384:
            raise IntegrityError("Retained source observation inventory exceeds bound")
        for path in sorted(paths):
            if path.is_symlink():
                raise IntegrityError("Symlink source observation")
            payload = read(path)
            if payload.get("schema_version") not in (INPUTS, "partial-registration-data-integrity-v2"):
                continue
            commit = payload.get("code_commit") if payload.get("schema_version") == INPUTS else payload.get("source_sha")
            if not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
                raise IntegrityError("Invalid saved corrected source commit")
            if commit not in sources:
                _, source_inventory = _legacy_graph(repository, source=commit, tree=None, objects_out=_objects)
                sources[commit] = source_inventory
    return {"commit": LEGACY_SOURCE, "tree": LEGACY_TREE, "objects": inventory,
            "retained_corrected": families["b3"], "retained_root67": families["root67"],
            "retained_classic_scoring": {"commit": classic.SCORING_SOURCE, "tree": classic.SCORING_TREE,
                "pull_tree": classic.SCORING_PULL_TREE, "blob": classic.SCORING_BLOB,
                "objects": classic_inventory},
            "receipt_sources": sources}


def _retained_corrected_commit(commit):
    """Closed old helper family; new writes still use strict recording_source."""
    old = _retained_profile(commit)
    if old is None:
        recording_source(commit)
    return old is not None


def _retained_corrected_read(root, operation, request, *, family="b3"):
    """Read saved evidence with actual B3 code and a minimal verified Git store.

    No remote, alternates, old-source recording or durable trust. Source objects,
    original evidence, negative evidence and independent destination are checked
    at both boundaries. The old validator retains all identity/clock checks.
    """
    import sys
    root = Path(root).resolve()
    if family not in _retained_families():
        raise IntegrityError("Unsupported retained corrected family")
    retained_source, retained_tree, _ = _retained_families()[family]
    def evidence_inventory(base):
        result = {}
        for lane in ("data", "output/data"):
            directory = Path(base) / lane
            if directory.is_symlink():
                raise IntegrityError("Symlink retained evidence")
            for path in sorted(directory.rglob("*")):
                if path.is_symlink():
                    raise IntegrityError("Symlink retained evidence")
                if path.is_file():
                    h = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(65536), b""):
                            h.update(chunk)
                    result[path.relative_to(base).as_posix()] = h.hexdigest()
        return result
    objects = {}
    source_before = legacy_dependency_inventory(evidence_root=root, _objects=objects)
    before = evidence_inventory(root)
    entries, _ = _legacy_graph(source=retained_source, tree=retained_tree)
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_") and key != "GITHUB_SHA"}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_LAZY_FETCH="1", PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryDirectory(prefix="nfl-retained-corrected-") as directory:
        source = Path(directory)
        for name, _, raw in entries:
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        subprocess.run(["git", "init", "-q", str(source)], check=True, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for oid, (kind, raw) in objects.items():
            saved = subprocess.check_output(["git", "-C", str(source), "hash-object", "-t", kind, "-w", "--stdin"], input=raw, env=env).decode().strip()
            if saved != oid:
                raise IntegrityError("Copied retained Git object identity changed")
        (source / ".git/HEAD").write_text(retained_source + "\n")
        for lane in ("data", "output/data"):
            if (root / lane).exists():
                shutil.copytree(root / lane, source / lane)
        if (evidence_inventory(source) != before or evidence_inventory(root) != before
                or legacy_dependency_inventory(repository=source, evidence_root=source) != source_before):
            raise IntegrityError("Copied retained corrected evidence changed")
        program = """import json,sys
from pathlib import Path
sys.path[:0]=[str(Path.cwd()/'tools'),str(Path.cwd()/'pull')]
import data_integrity_v2 as d
r=json.load(sys.stdin)
if r['operation']=='inputs':
 result=d.recorded_inputs(Path.cwd(),**r['request'])
elif r['operation']=='bundle':
 result=d.read_bundle(Path.cwd(),**r['request'])
elif r['operation']=='reproduce':
 result=d._reproduce_game(Path.cwd(),**r['request'])
else: raise RuntimeError('Unsupported retained operation')
print(json.dumps(result,allow_nan=False))
"""
        # A temporary file bounds IPC memory even on a failing child.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.run([sys.executable, "-B", "-c", program], cwd=source, env=env,
                input=json.dumps({"operation": operation, "request": request}).encode(),
                stdout=output, stderr=errors, timeout=180)
            output.seek(0); raw = output.read(256 * 1024 * 1024 + 1)
            if process.returncode or len(raw) > 256 * 1024 * 1024:
                errors.seek(0); reason = errors.read(65536).decode(errors="replace").splitlines()
                raise IntegrityError("Retained corrected validation failed: " + (reason[-1] if reason else "invalid output"))
        if (evidence_inventory(source) != before or evidence_inventory(root) != before
                or legacy_dependency_inventory(evidence_root=root) != source_before
                or legacy_dependency_inventory(repository=source, evidence_root=source) != source_before
                or any((source / name).read_bytes() != value for name, _, value in entries)):
            raise IntegrityError("Retained corrected dependencies changed during validation")
    return json.loads(raw.splitlines()[-1])


def legacy_engine_hashes(repository=ROOT):
    return {name: hashlib.sha256(_legacy_blob(name, repository)).hexdigest() for name in ENGINE_PATHS}


def legacy_scoring(repository=ROOT):
    """Fresh exact approved bytes; no changed implementation under a V1 label."""
    raw = _legacy_blob("pull/scoring.py", repository)
    module = types.ModuleType("retained_v1_scoring")
    module.__file__ = str(Path(repository) / ".retained-v1-source/pull/scoring.py")
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    return module


@contextmanager
def legacy_source(repository=ROOT):
    """Resolve actual immutable Git objects, without network or path-only trust."""
    entries, _ = _legacy_graph(repository)
    with tempfile.TemporaryDirectory(prefix="nfl-retained-source-") as directory:
        root = Path(directory)
        for path, blob, raw in entries:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        yield root


def recording_source(commit=None, *, repository=ROOT, model=None):
    """Bind actual corrected source, never a dirty tree wearing an old SHA."""
    commit = commit or os.environ.get("GITHUB_SHA") or _git(repository, "rev-parse", "HEAD").decode().strip()
    if not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise IntegrityError("Corrected recording source commit is invalid")
    _source_commit(repository, commit)
    expected_files = engine_files(repository, model=model)
    for name, expected in expected_files.items():
        raw = _source_file(repository, commit, name)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise IntegrityError("Corrected recording source differs from closed engine")
    for name in ("tools/data_integrity_v2.py", "tools/build_recorded.py", "tools/reliability.py"):
        raw = _source_file(repository, commit, name)
        if raw != (Path(repository) / name).read_bytes():
            raise IntegrityError("Corrected recording helper is not the identified committed source")
    return commit


def engine_files(root, model=None):
    actual = _source_bytes(root)
    selected = model if model is not None else next((name for name in PRESENCE_MODELS if actual == source_hashes(name)), None)
    if selected is None:
        raise IntegrityError("Unrecognized installed presence source")
    expected = source_hashes(selected)
    if set(expected) != set(V2_PATHS):
        raise IntegrityError("Corrected source manifest is not finalized")
    if actual != expected:
        raise IntegrityError("Installed source differs from explicit presence model")
    return dict(actual)


def native_contract(payload, *, repository=ROOT):
    """No arbitrary manifests and no registered-experiment V2 admission."""
    version = payload.get("schema_version"), payload.get("model")
    if version == ("baseline-capture-v1", "original_sleeper_matchup_baseline"):
        expected = legacy_engine_hashes(repository)
    elif version[0] == NATIVE and version[1] in PRESENCE_MODELS:
        expected = source_hashes(version[1])
        if not expected or payload.get("presence_contract") != PRESENCE:
            raise IntegrityError("Unsupported corrected native presence contract")
    else:
        raise IntegrityError("Unsupported native schema/model combination")
    if payload.get("engine_files") != expected or payload.get("engine_sha256") != digest(expected):
        raise IntegrityError("Native source identity differs from the closed contract")
    return expected


def presence_scoring(model=None, *, repository=ROOT):
    """Fresh exact source for pure presence arithmetic, including old reports."""
    model = active_model(repository) if model is None else model
    expected = source_hashes(model)["pull/scoring.py"]
    base = Path(repository).resolve()
    path = base / "pull/scoring.py"
    if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base)
            or path.stat().st_size > 2 * 1024 * 1024):
        raise IntegrityError("Unsupported statistic source path")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        if model != MODEL:
            raise IntegrityError("Current statistic source unavailable")
        dispatcher_identity()
        # B3 and Root67 share this exact old scoring blob; their helper
        # qualification remains separately pinned in the retained readers.
        _source_commit(repository, RETAINED_CORRECTED_SOURCE)
        if _git(repository, "rev-parse", RETAINED_CORRECTED_SOURCE + "^{tree}").decode().strip() != RETAINED_CORRECTED_TREE:
            raise IntegrityError("Retained statistic source tree mismatch")
        raw = _source_file(repository, RETAINED_CORRECTED_SOURCE, "pull/scoring.py")
        if hashlib.sha256(raw).hexdigest() != expected:
            raise IntegrityError("Retained statistic source identity mismatch")
    module = types.ModuleType("closed_presence_scoring")
    exec(compile(raw, "closed-presence-scoring", "exec"), module.__dict__)
    return module


def statistic_contract(*, descriptive=False, model=None, repository=ROOT):
    model = active_model(repository) if model is None else model
    scoring = presence_scoring(model, repository=repository)
    hashes = source_hashes(model)
    if not hashes:
        raise IntegrityError("Corrected statistic source manifest unavailable")
    return {"version": "offensive-ppr-rush-rec-td-presence-v2" if descriptive else "ten-pickable-presence-v2",
            "presence_contract": PRESENCE, "source_files": hashes,
            "sparse_zero": "EXPLICIT_LEGACY_ADAPTER_ASSUMPTION_NOT_PROVIDER_AUTHENTICATION",
            **({"ppr_weights": dict(scoring.PPR), "ppr_defensive_fumble_exclusion": "idp_fum_rec",
                "td_event": "rush_td+rec_td>=1", "td_probability": "round(1-exp(-max(count,0)),3)"}
               if descriptive else {})}


def statistic_presence(category, stats, *, model=None, repository=ROOT):
    scoring = presence_scoring(model, repository=repository)
    keys = (set(scoring.PPR) | {"idp_fum_rec"} if category == "fpts" else
            {"rush_td", "rec_td"} if category == "anytime_td" else
            {"rush_yd", "rec_yd"} if category == "rush_rec_yd" else {category})
    return {key: scoring.component(stats, key) for key in sorted(keys)}


def statistic_model(contract, *, descriptive=False, repository=ROOT):
    """Select only an exact complete closed statistic contract, never a prefix."""
    if not isinstance(contract, dict):
        raise IntegrityError("Unsupported statistic contract")
    for model in PRESENCE_MODELS:
        if contract.get("source_files") == source_hashes(model):
            if digest(contract) != digest(statistic_contract(descriptive=descriptive, model=model, repository=repository)):
                break
            return model
    raise IntegrityError("Unsupported statistic source contract")


def recorded_inputs(root, name, season, week, *, mode=None, observed_at=None):
    """Qualify V3 model inputs without changing the old V2 validator."""
    from evidence import referenced
    from source_evidence import HASH_FORMAT, verified_status
    import verify
    inputs = referenced(root, name, "verification")
    expected = f"data/verification/{season}/w{week:02d}/{digest(inputs)}.json.gz"
    model = inputs.get("model")
    if name != expected or inputs.get("schema_version") != INPUTS or model not in PRESENCE_MODELS:
        raise IntegrityError("Unsupported corrected input identity/schema/model")
    family = _retained_profile(inputs.get("code_commit"))
    if family is not None:
        if model != MODEL:
            raise IntegrityError("Retained source cannot qualify a different model")
        result = _retained_corrected_read(root, "inputs", {"name": name, "season": season, "week": week,
            "mode": mode, "observed_at": utc(observed_at).isoformat() if observed_at is not None else None}, family=family)
        if result != inputs:
            raise IntegrityError("Retained corrected input return changed")
        return result
    hashes = engine_files(root, model=model)
    recording_source(inputs.get("code_commit"), model=model)
    if inputs.get("presence_contract") != PRESENCE or inputs.get("engine_files") != hashes:
        raise IntegrityError("Corrected input source/presence mismatch")
    if inputs.get("mode") not in ("live", "replay") or mode is not None and inputs["mode"] != mode:
        raise IntegrityError("Corrected input live/replay mismatch")
    saved = inputs["week_data"]
    if ((inputs.get("season"), inputs.get("week")) != (season, week)
            or (saved.get("season"), saved.get("week")) != (season, week)
            or inputs.get("output_sha256") != digest(saved)):
        raise IntegrityError("Corrected input board/period mismatch")
    started, observed, recorded = (utc(inputs[k]) for k in ("build_started_at", "inputs_observed_at", "recorded_at"))
    generated = utc(saved["generated_at"])
    if not started <= observed <= recorded or observed.replace(microsecond=0) > generated or generated > recorded:
        raise IntegrityError("Corrected input clocks are inconsistent")
    if observed_at is not None and recorded > utc(observed_at):
        raise IntegrityError("Corrected input evidence completed after verification")
    weeks = inputs["weeks"]
    if not isinstance(weeks, dict) or any(not str(w).isdigit() or str(int(w)) != w or not 1 <= int(w) < week for w in weeks):
        raise IntegrityError("Corrected inputs contain current/future or ambiguous weeks")
    positions = inputs["positions"]
    if not positions or any(not isinstance(pid, str) or pos not in ("QB", "RB", "WR", "TE") for pid, pos in positions.items()):
        raise IntegrityError("Invalid corrected full position population")
    games = verify._indexed(saved["games"], "id", "corrected original games")
    players = verify._indexed(saved["players"], "id", "corrected original players")
    for player in players.values():
        verify._indexed(player["props"], "key", "corrected original props")
    for request in inputs["source_requests"]:
        if (not isinstance(request.get("url"), str) or request.get("response_hash_format") != MODEL_INPUT_HASH
                or not isinstance(request.get("response_sha256"), str) or len(request["response_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in request["response_sha256"])
                or not started <= utc(request["collected_at"]) <= recorded):
            raise IntegrityError("Invalid corrected source observation")
    components = inputs.get("projection_input_components")
    if not isinstance(components, dict):
        raise IntegrityError("Missing corrected original projection components")
    for pid, record in components.items():
        if (not isinstance(pid, str) or not isinstance(record, dict) or not isinstance(record.get("stats"), dict)
                or any(key not in __import__("scoring").STAT_KEYS for key in record["stats"])
                or not started <= utc(record["collected_at"]) <= recorded
                or not any(request["url"] == record.get("source")
                    and request["response_sha256"] == record.get("source_response_sha256")
                    and utc(request["collected_at"]) == utc(record["collected_at"])
                    for request in inputs["source_requests"])):
            raise IntegrityError("Corrected component source/clock does not match original observation")
    status = inputs["game_status"][f"{season}_{week:02d}"]
    sourced = verified_status(status, season, week, inputs["mode"], recorded)
    if utc(status["collected_at"]) < started or set(sourced) != set(games) or any(
            utc(sourced[gid]["kickoff"]) != utc(game["kickoff"]) or sourced[gid]["state"] != game["state"]
            for gid, game in games.items()):
        raise IntegrityError("Corrected game population differs from original status")
    return inputs


def legacy_recorded_inputs(root, name, season, week, *, mode=None, observed_at=None, repository=ROOT):
    """Execute the unchanged recorded-input reader with its actual dependencies."""
    request = {"root": str(Path(root).resolve()), "name": name, "season": season, "week": week,
               "mode": mode, "observed_at": observed_at.isoformat() if hasattr(observed_at, "isoformat") else observed_at}
    program = """import json,sys
from pathlib import Path
sys.path[:0]=[str(Path.cwd()/'tools'),str(Path.cwd()/'pull')]
import verify,reliability
r=json.load(sys.stdin)
result=verify.recorded_inputs(Path(r['root']),r['name'],r['season'],r['week'],reliability.engine_hashes(Path.cwd()),mode=r['mode'],observed_at=r['observed_at'])
print(json.dumps(result,allow_nan=False))
"""
    with legacy_source(repository) as source:
        import sys
        try:
            raw = subprocess.check_output([sys.executable, "-B", "-c", program], input=json.dumps(request).encode(),
                                          cwd=source, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as error:
            raise IntegrityError("Retained V1 original-input validation failed") from error
    return json.loads(raw)


def legacy_bundle(root, name, spec, *, now, repository=ROOT):
    """Exact retained reader/dependencies in an independently copied root."""
    root = Path(root)
    request = {"name": name, "spec": spec, "now": utc(now).isoformat()}
    with legacy_source(repository) as source:
        for lane in ("data", "output/data"):
            original = root / lane
            if original.exists():
                if original.is_symlink() or any(path.is_symlink() for path in original.rglob("*")):
                    raise IntegrityError("Symlink retained evidence is unsupported")
                shutil.copytree(original, source / lane)
                for path in original.rglob("*"):
                    if path.is_file() and hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(
                            (source / lane / path.relative_to(original)).read_bytes()).digest():
                        raise IntegrityError("Copied retained evidence changed")
        program = """import json,sys
from pathlib import Path
sys.path[:0]=[str(Path.cwd()/'tools'),str(Path.cwd()/'pull')]
import partial_week,phase2_capture
r=json.load(sys.stdin)
result=partial_week.read_bundle(Path.cwd(),r['name'],r['spec'],phase2_capture.read_native_baseline,now=r['now'])
print(json.dumps(result,allow_nan=False))
"""
        import sys
        try:
            raw = subprocess.check_output([sys.executable, "-B", "-c", program], input=json.dumps(request).encode(),
                                          cwd=source, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as error:
            reason = error.stderr.decode("utf-8", errors="replace").splitlines()
            raise IntegrityError("Retained V1 completed-bundle validation failed: " + (reason[-1] if reason else "unknown")) from error
    return tuple(json.loads(raw.splitlines()[-1]))


def legacy_offline(root, data, proof, mode, observed_at, *, repository=ROOT):
    """Strict V1 arithmetic runs only with the complete retained dependency root."""
    request = {"data": data, "proof": proof,
               "mode": mode, "at": utc(observed_at).isoformat()}
    program = """import json,sys
from pathlib import Path
sys.path[:0]=[str(Path.cwd()/'tools'),str(Path.cwd()/'pull')]
import verify
r=json.load(sys.stdin)
print(json.dumps(verify.require_offline(Path.cwd(),r['data'],r['proof'],r['mode'],r['at']),allow_nan=False))
"""
    with legacy_source(repository) as source:
        for lane in ("data", "output/data"):
            original = Path(root) / lane
            if original.exists():
                if original.is_symlink() or any(path.is_symlink() for path in original.rglob("*")):
                    raise IntegrityError("Symlink retained evidence is unsupported")
                shutil.copytree(original, source / lane)
                for path in original.rglob("*"):
                    if path.is_file() and hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(
                            (source / lane / path.relative_to(original)).read_bytes()).digest():
                        raise IntegrityError("Copied retained evidence changed")
        import sys
        try:
            raw = subprocess.check_output([sys.executable, "-B", "-c", program], input=json.dumps(request).encode(),
                                          cwd=source, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as error:
            reason = error.stderr.decode("utf-8", errors="replace").splitlines()
            raise IntegrityError("Retained V1 strict validation failed: " + (reason[-1] if reason else "unknown")) from error
    return json.loads(raw.splitlines()[-1])


def legacy_candidate_evaluation(candidates, baselines, outcomes, registration, policy, now):
    request = {"candidates": candidates, "baselines": baselines, "outcomes": outcomes,
               "registration": registration, "policy": policy, "now": utc(now).isoformat()}
    program = """import json,sys
from pathlib import Path
sys.path[:0]=[str(Path.cwd()/'tools'),str(Path.cwd()/'pull')]
import point_challenger
r=json.load(sys.stdin)
print(json.dumps(point_challenger.evaluate(r['candidates'],r['baselines'],r['outcomes'],r['registration'],now=r['now'],policy=r['policy']),allow_nan=False))
"""
    with legacy_source() as source:
        import sys
        try:
            raw = subprocess.check_output([sys.executable, "-B", "-c", program], input=json.dumps(request).encode(),
                                          cwd=source, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as error:
            raise IntegrityError("Retained original candidate evaluation failed") from error
    return json.loads(raw)


def code_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def dispatcher_identity():
    import reliability
    if code_sha256() != reliability.V2_HELPER_SHA256:
        raise IntegrityError("Retained-source dispatcher implementation changed")
    return code_sha256()


def validate_plan(spec, data, at, *, root=ROOT):
    import partial_week as original
    import verify
    at = utc(at)
    plan = spec.get("plan", {})
    model = plan.get("model")
    hashes = source_hashes(model)
    if (digest(plan) != spec.get("plan_sha256") or spec.get("validator_sha256") != code_sha256()
            or plan.get("schema_version") != PLAN or plan.get("validator_contract") != VALIDATOR
            or plan.get("engine_files") != hashes or engine_files(root, model=model) != hashes
            or not hashes or plan.get("full_board_verified") is not False
            or plan.get("complete_week_qualified") is not False
            or plan.get("experimental_recording_enabled") is not False
            or plan.get("completion_status_max_age_seconds") != 60
            or not spec.get("owner_authorization")):
        raise IntegrityError("Unsupported corrected fixed plan/source/validator")
    if ((data["season"], data["week"]) != (plan.get("season"), plan.get("week"))
            or not utc(plan["plan_prepared_at"]) <= utc(plan["effective_not_before"]) <= at < utc(plan["expires_at"])):
        raise IntegrityError("Corrected plan period/effective/expiry mismatch")
    games = verify._indexed(plan["games"], "id", "corrected plan games")
    actual = verify._indexed(data["games"], "id", "corrected complete games")
    if set(games) != set(actual) or any(any(
            (utc(game[k]) != utc(actual[gid][k]) if k == "kickoff" else game[k] != actual[gid][k])
            for k in ("home", "away", "kickoff")) for gid, game in games.items()):
        raise IntegrityError("Corrected fixed game population/schedule changed")
    exemptions = verify._indexed(plan["legacy_exemptions"], "game_id", "corrected fixed exemptions")
    if not set(exemptions) <= set(games):
        raise IntegrityError("Corrected exemption outside fixed population")
    for gid, exemption in exemptions.items():
        if (not exemption.get("reason") or utc(games[gid]["kickoff"]) >= utc(plan["effective_not_before"])
                or digest(original.game_contract(data, gid)) != exemption.get("forecast_contract_sha256")):
            raise IntegrityError("Corrected fixed legacy contract/reason mismatch")
    return plan


def register_plan(root, spec, at, *, source_sha, initial_board):
    from evidence import write
    import partial_week as original
    plan = validate_plan(spec, initial_board, at, root=root)
    if engine_files(root, model=plan["model"]) != plan["engine_files"] or digest(initial_board) != plan["initial_complete_board_sha256"]:
        raise IntegrityError("Corrected initial board/source mismatch")
    if not isinstance(source_sha, str) or len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise IntegrityError("Corrected registration source commit unavailable")
    # The original saved source-status reader is pure and plan-version-neutral.
    candidates = []
    for path in (Path(root) / "data/verification/partial-schedule-baselines").rglob("*.json.gz"):
        name = path.relative_to(root).as_posix()
        saved = original._saved(root, name, "verification/partial-schedule-baselines")
        if digest(saved.get("status")) == plan["schedule_status_payload_sha256"]:
            original._plan_status(root, plan, name)
            candidates.append(name)
    if len(candidates) != 1:
        raise IntegrityError("Corrected original schedule source missing/ambiguous")
    payload = {"schema_version": "partial-registration-data-integrity-v2", "season": plan["season"],
               "week": plan["week"], "plan": copy.deepcopy(plan), "plan_sha256": digest(plan),
               "validator_sha256": code_sha256(), "source_sha": source_sha,
               "registered_at": utc(at).isoformat(), "owner_authorization": spec["owner_authorization"],
               "initial_board": copy.deepcopy(initial_board), "schedule_status_receipt": candidates[0]}
    for path in (Path(root) / "data/verification/partial-registrations").rglob("*.json.gz"):
        old = original._saved(root, path.relative_to(root).as_posix(), "verification/partial-registrations")
        if old.get("schema_version") == payload["schema_version"] and old.get("plan_sha256") == digest(plan):
            registration(root, path.relative_to(root).as_posix(), spec, at)
            return path, old
    path = write(root, "verification/partial-registrations", payload)
    registration(root, path.relative_to(root).as_posix(), spec, at)
    return path, payload


def registration(root, name, spec, at):
    import partial_week as original
    saved = original._saved(root, name, "verification/partial-registrations")
    plan = validate_plan(spec, saved["initial_board"], at, root=root)
    if (saved.get("schema_version") != "partial-registration-data-integrity-v2" or saved["plan"] != plan
            or saved["validator_sha256"] != code_sha256() or saved["plan_sha256"] != digest(plan)
            or saved["owner_authorization"] != spec["owner_authorization"]
            or digest(saved["initial_board"]) != plan["initial_complete_board_sha256"]
            or not utc(plan["effective_not_before"]) <= utc(saved["registered_at"]) <= utc(at)):
        raise IntegrityError("Corrected saved registration mismatch")
    original._plan_status(root, plan, saved["schedule_status_receipt"])
    recording_source(saved["source_sha"], model=plan["model"])
    return saved


def _saved_spec(root, scope):
    import partial_week as original
    saved = original._saved(root, scope["registration_receipt"], "verification/partial-registrations")
    plan = saved.get("plan")
    if plan is None:
        plan = original._saved(root, saved["plan_receipt"], "verification/partial-plans")
    return {"plan": plan, "plan_sha256": digest(plan), "validator_sha256": saved["validator_sha256"],
            "owner_authorization": saved["owner_authorization"]}


def _frozen(root, gid, origin, contract, now, seen, *, receipt=None):
    """Discover the earliest eligible witness, or validate one exact saved edge.

    Filename order is only a tie breaker. Saved reconstruction never discovers
    an alternative, including when the pinned witness is invalid or unavailable.
    """
    import partial_week as original
    def candidate(name):
        completion = original._saved(root, name, "verification/partial-completions")
        scope = original._saved(root, completion["scope_receipt"], "verification/partial-scopes")
        if scope.get("proof", {}).get("game_origins", {}).get(gid) != origin:
            return None
        population = [row for row in scope.get("game_population", []) if row.get("game_id") == gid]
        if len(population) != 1 or population[0].get("forecast_contract_sha256") != contract:
            return None
        if population[0].get("classification") not in ("new_pregame_original_inputs_verified", "frozen_original_inputs_verified"):
            return None
        if completion.get("schema_version") not in ("partial-completion-data-integrity-v2", original.COMPLETION_VERSION):
            raise IntegrityError("Unsupported frozen completion version")
        completed_at = utc(completion["evidence_completed_at"])
        if utc(scope["verified_at"]) > completed_at:
            raise IntegrityError("Invalid frozen evidence completion clock")
        if completed_at > utc(now):
            return None
        return completed_at, name, completion, scope

    if receipt is not None:
        selected = candidate(receipt)
    else:
        eligible = [item for path in (Path(root) / "data/verification/partial-completions").rglob("*.json.gz")
                    if (item := candidate(path.relative_to(root).as_posix())) is not None]
        selected = min(eligible, key=lambda item: item[:2]) if eligible else None
    if selected is None:
        raise IntegrityError("Frozen game lacks its exact eligible completed original bundle")
    _, name, completion, scope = selected
    if name in seen:
        raise IntegrityError("Cyclic corrected frozen evidence")
    saved_spec = _saved_spec(root, scope)
    if completion["schema_version"] == "partial-completion-data-integrity-v2":
        read_bundle(root, name, saved_spec, now=now, _seen=seen)
    else:
        legacy_bundle(root, name, saved_spec, now=now)
    return name


def _reproduce_game(root, data, game, inputs):
    family = _retained_profile(inputs.get("code_commit"))
    if family is not None:
        if inputs.get("model") != MODEL:
            raise IntegrityError("Retained reproduction model mismatch")
        return _retained_corrected_read(root, "reproduce", {"data": data, "game": game, "inputs": inputs}, family=family)
    import partial_week as original
    import verify
    import matchup
    import scoring
    import build
    verify._original_game(inputs, game)
    if original.game_contract(data, game["id"]) != original.game_contract(inputs["week_data"], game["id"]):
        raise IntegrityError("Corrected frozen forecast/offer/membership changed")
    model = matchup.Matchups({int(w): rows for w, rows in inputs["weeks"].items()}, inputs["positions"])
    history = build.build_history({(inputs["season"], int(w)): rows for w, rows in inputs["weeks"].items()})
    checked = 0
    for player in inputs["week_data"]["players"]:
        if player["game_id"] != game["id"]:
            continue
        if (player["team"] not in (game["home"], game["away"]) or player["opp"] not in (game["home"], game["away"])
                or player["opp"] == player["team"] or player["props"] and inputs["positions"].get(player["id"]) != player["pos"]):
            raise IntegrityError("Corrected original player identity mismatch")
        if not player["props"]:
            continue
        observation = inputs.get("projection_input_components", {}).get(player["id"])
        raw = observation["stats"] if observation is not None else {}
        projected = build.projection_components(raw) if observation is not None else None
        current_history = [entry for entry in history.get(player["id"], []) if entry["season"] == inputs["season"]]
        derived = {"proj_ppr": projected.get("pts_ppr") if projected else None,
                   "proj_half": projected.get("pts_half_ppr") if projected else None,
                   "proj": {key: value for key, value in (projected or {}).items() if key != "pts_ppr"},
                   "games_this_season": len(current_history), "snap_share": build.snap_share(current_history),
                   "avg_ppr": build.known_average(current_history, player["pos"]),
                   "avg_half": build.known_average(current_history, player["pos"], half=True),
                   "log": build.game_log(player["pos"], current_history)}
        if any(player.get(key) != value for key, value in derived.items()):
            raise IntegrityError("Corrected provider/component/history eligibility metadata does not reproduce")
        reconstructed = {prop["key"]: prop for prop in build.player_props(
            player, projected, history.get(player["id"], []), inputs["season"], player["opp"], model)}
        for prop in player["props"]:
            rebuilt = reconstructed.get(prop["key"])
            fields = ("proj", "adj", "mf", "mf_n", "values", "td_chance", "source")
            if rebuilt is None or any(rebuilt.get(key) != prop.get(key) for key in fields):
                raise IntegrityError("Corrected original history/components do not reproduce forecast")
            expected = scoring.stat_value(prop["key"], projected, projection=True)
            if prop.get("proj") != (round(expected, 2) if expected is not None else None):
                raise IntegrityError("Corrected original raw components do not reproduce forecast")
            if prop["key"] == "anytime_td":
                chance = round(scoring.td_probability(expected), 3) if expected is not None else None
                if prop.get("td_chance") != chance:
                    raise IntegrityError("Corrected TD missingness/probability mismatch")
                continue
            if "mf" not in prop:
                if prop.get("adj") is not None:
                    raise IntegrityError("Corrected adjusted forecast lacks factor")
                continue
            values = prop.get("values", [])
            average = statistics.mean(v["v"] for v in values) if values else None
            if model.factor(player["opp"], player["pos"], prop["key"], average) != (prop["mf"], prop["mf_n"]):
                raise IntegrityError("Corrected matchup reproduction failed")
            base = prop.get("proj") if prop.get("proj") is not None else average if len(values) >= 2 else None
            if base is None or round(base * prop["mf"], 2) != prop.get("adj"):
                raise IntegrityError("Corrected adjusted projection reproduction failed")
            checked += 1
    return checked


def verify_scope(root, data, proof, closing_status, spec, registration_name, at, *, _seen=None, _frozen_bindings=None):
    import partial_week as original
    import verify
    from source_evidence import verified_status
    at = utc(at)
    plan = validate_plan(spec, data, at, root=root)
    model = plan["model"]
    registration(root, registration_name, spec, at)
    hashes = engine_files(root, model=model)
    games = verify._indexed(data["games"], "id", "corrected complete board")
    if (proof.get("schema_version") != PROOF or proof.get("output_sha256") != digest(data)
            or set(proof.get("game_origins", {})) != set(games)):
        raise IntegrityError("Corrected proof/complete-board population mismatch")
    sourced = verified_status(closing_status, data["season"], data["week"], "live", at)
    if set(sourced) != set(games) or not 0 <= (at - utc(closing_status["collected_at"])).total_seconds() <= 60:
        raise IntegrityError("Corrected completion source population/age mismatch")
    latest = recorded_inputs(root, proof["latest_inputs"], data["season"], data["week"], mode="live", observed_at=at)
    if latest.get("model") != model:
        raise IntegrityError("Corrected latest input model differs from plan")
    if utc(closing_status["collected_at"]) < utc(latest["recorded_at"]):
        raise IntegrityError("Corrected closing status precedes original-input completion")
    if latest["output_sha256"] != digest(data):
        raise IntegrityError("Corrected latest input differs from complete current board")
    exemptions = {item["game_id"]: item for item in plan["legacy_exemptions"]}
    population, checked, original_players = [], 0, {}
    for gid, game in games.items():
        if (utc(sourced[gid]["kickoff"]) != utc(game["kickoff"])
                or original._teams(closing_status, gid) != {key: game[key] for key in ("home", "away")}):
            raise IntegrityError("Corrected closing schedule/team mismatch")
        status = sourced[gid]
        if (status["state"] == "pre" and status["completed"] is not False
                or game["state"] in ("in", "post") and status["state"] == "pre"
                or game["state"] == "pre" and utc(game["kickoff"]) > at and status["state"] != "pre"
                or any(word in status["detail"].lower() for word in ("cancel", "postpon", "suspend", "delay"))):
            raise IntegrityError("Corrected contradictory/nonstandard closing status")
        fingerprint = digest(original.game_contract(data, gid))
        origin = proof["game_origins"][gid]
        started = utc(game["kickoff"]) <= at or sourced[gid]["state"] != "pre"
        completion = None
        if gid in exemptions and origin is None:
            if not started or fingerprint != exemptions[gid]["forecast_contract_sha256"]:
                raise IntegrityError("Corrected legacy exemption status/contract changed")
            classification = "retained_legacy_original_proof_missing"
        else:
            if not origin:
                raise IntegrityError("Nonexempt corrected game lacks original inputs")
            from evidence import referenced
            saved = referenced(root, origin, "verification")
            if saved.get("schema_version") == INPUTS:
                inputs = recorded_inputs(root, origin, data["season"], data["week"], mode="live", observed_at=at)
                checked += _reproduce_game(root, data, game, inputs)
            elif saved.get("schema_version") == "matchup-inputs-v2":
                inputs = legacy_recorded_inputs(root, origin, data["season"], data["week"], mode="live", observed_at=at)
                verify._original_game(inputs, game)
                if original.game_contract(inputs["week_data"], gid) != original.game_contract(data, gid):
                    raise IntegrityError("Retained V1 frozen contract mismatch")
            else:
                raise IntegrityError("Unsupported original schema in corrected scope")
            if started or origin != proof["latest_inputs"]:
                pinned = None
                if _frozen_bindings is not None:
                    pinned = _frozen_bindings.get(gid)
                    if not isinstance(pinned, str) or not pinned:
                        raise IntegrityError("Saved frozen game lacks its exact recorded completion")
                completion = _frozen(root, gid, origin, fingerprint, at, set(_seen or ()), receipt=pinned)
                classification = "frozen_original_inputs_verified"
                original_players.update({(gid, p["id"]): p for p in inputs["week_data"]["players"] if p["game_id"] == gid})
            else:
                if game["state"] != "pre":
                    raise IntegrityError("New corrected pregame observation is not current original evidence")
                classification = "new_pregame_original_inputs_verified"
        population.append({"game_id": gid, "home": game["home"], "away": game["away"], "kickoff": game["kickoff"],
                           "classification": classification,
                           "forecast_contract_sha256": fingerprint, "origin": origin,
                           "completed_origin_receipt": completion})
    # Reuse only version-neutral structural and balance checks.
    errors = []
    shape = copy.deepcopy(data)
    legacy = {row["game_id"] for row in population if row["classification"] == "retained_legacy_original_proof_missing"}
    shape["picks"] = {side: [pick for pick in picks if pick["game_id"] not in legacy] for side, picks in shape["picks"].items()}
    for player in shape["players"]:
        saved_player = original_players.get((player["game_id"], player["id"]))
        if saved_player is not None:
            for field in ("injury", "snap_share", "proj_ppr"):
                if field in saved_player:
                    player[field] = saved_player[field]
                else:
                    player.pop(field, None)
    verify.check_shape(shape, report=errors.append)
    verify.check_lean_balance(data, report=errors.append)
    if errors:
        raise IntegrityError("Corrected board structure/selection check failed: " + "; ".join(errors))
    return {"schema_version": "partial-scope-data-integrity-v2", "season": data["season"], "week": data["week"],
            "validator_contract": VALIDATOR, "validator_sha256": code_sha256(), "model": model,
            "engine_files": hashes, "output_sha256": digest(data), "proof": copy.deepcopy(proof),
            "plan_sha256": digest(plan), "registration_receipt": registration_name,
            "latest_inputs_sha256": digest(latest), "completion_status": copy.deepcopy(closing_status),
            "verified_at": at.isoformat(), "checked_factors": checked, "game_population": population,
            "full_board_verified": False, "complete_week_qualified": False,
            "claim": "RETAINED_ORIGINAL_MODEL_INPUT_REPRODUCTION_NOT_PROVIDER_TIME_OR_ACCURACY"}


def read_bundle(root, name, spec, *, now, _seen=None):
    import partial_week as original
    import phase2_capture
    from reliability import make_payload
    seen = set(_seen or ())
    if name in seen:
        raise IntegrityError("Cyclic corrected frozen evidence")
    seen.add(name)
    completion = original._saved(root, name, "verification/partial-completions")
    family = next((name for name, (_, _, helpers) in _retained_families().items()
                   if completion.get("validator_sha256") == helpers["tools/data_integrity_v2.py"]), None)
    if family is not None:
        if completion.get("schema_version") != "partial-completion-data-integrity-v2":
            raise IntegrityError("Unsupported retained corrected completion version")
        return tuple(_retained_corrected_read(root, "bundle", {"name": name, "spec": spec,
            "now": utc(now).isoformat(), "_seen": list(_seen or ())}, family=family))
    for path in (Path(root) / "data/verification/partial-failures").rglob("*.json.gz"):
        failure = original._saved(root, path.relative_to(root).as_posix(), "verification/partial-failures")
        if failure.get("completion_sha256") == digest(completion):
            raise IntegrityError("Corrected completion rejected at final persistence boundary")
    if (completion.get("schema_version") != "partial-completion-data-integrity-v2"
            or completion.get("validator_sha256") != code_sha256()
            or completion.get("plan_sha256") != spec["plan_sha256"]):
        raise IntegrityError("Unsupported corrected completion/plan/validator")
    scope = original._saved(root, completion["scope_receipt"], "verification/partial-scopes")
    period = (spec["plan"]["season"], spec["plan"]["week"])
    if ((completion["season"], completion["week"]) != period
            or (scope["season"], scope["week"]) != period):
        raise IntegrityError("Corrected completion/scope/plan period mismatch")
    at = utc(completion["evidence_completed_at"])
    if not utc(scope["verified_at"]) <= at <= utc(now):
        raise IntegrityError("Invalid corrected evidence completion clock")
    inputs = recorded_inputs(root, scope["proof"]["latest_inputs"], scope["season"], scope["week"], mode="live", observed_at=at)
    model = spec["plan"].get("model")
    if inputs.get("model") != model:
        raise IntegrityError("Corrected saved input/plan model mismatch")
    data = inputs["week_data"]
    import verify
    population = verify._indexed(scope["game_population"], "game_id", "corrected saved scope")
    bindings = {gid: row.get("completed_origin_receipt") for gid, row in population.items()}
    expected = verify_scope(root, data, scope["proof"], scope["completion_status"], spec,
                            scope["registration_receipt"], scope["verified_at"], _seen=seen, _frozen_bindings=bindings)
    if scope != expected:
        raise IntegrityError("Corrected scope differs from reproduced evidence")
    native = phase2_capture.read_native_baseline(Path(root) / completion["baseline_receipt"], root, now=now)
    captured = utc(native["captured_at"])
    if (completion["scope_payload_sha256"] != digest(scope) or completion["baseline_payload_sha256"] != digest(native)
            or completion["output_sha256"] != digest(data) or native["input_sha256"] != digest(data)
            or native.get("code_commit") != inputs.get("code_commit")
            or not utc(inputs["recorded_at"]) <= captured <= utc(scope["verified_at"]) <= at
            or native.get("model") != model
            or native["rows"] != make_payload(data, captured, engine_files(root, model=model), "live", model=model)["rows"]):
        raise IntegrityError("Corrected native/input/scope/clock mismatch")
    _cutoff(data, scope, at)
    included = {row["game_id"] for row in scope["game_population"] if row["classification"] == "new_pregame_original_inputs_verified"}
    if any(row["game_id"] not in included for row in native["rows"]):
        raise IntegrityError("Corrected native includes a game outside its completed pregame population")
    return completion, scope, native


def _cutoff(data, scope, at):
    included = {game["game_id"] for game in scope["game_population"]
                if game["classification"] == "new_pregame_original_inputs_verified"}
    if (any(utc(game["kickoff"]) <= utc(at) for game in data["games"] if game["id"] in included)
            or not 0 <= (utc(at) - utc(scope["completion_status"]["collected_at"])).total_seconds() <= 60):
        raise IntegrityError("Corrected capture crossed kickoff or final status expiry")


def record_bundle(root, data, proof, closing_status, spec, registration_name, *, clock):
    from evidence import write
    from reliability import capture, load_json, digest
    import partial_week as original
    root = Path(root)
    model = spec.get("plan", {}).get("model")
    hashes = engine_files(root, model=model)
    identity = digest({"data": digest(data), "engine": digest(hashes), "mode": "live"})
    target = root / "data/forward" / str(data["season"]) / f"w{data['week']:02d}" / (identity + ".json.gz")
    if target.exists():
        candidates = []
        for path in (root / "data/verification/partial-completions").rglob("*.json.gz"):
            saved = original._saved(root, path.relative_to(root).as_posix(), "verification/partial-completions")
            if saved.get("baseline_receipt") == target.relative_to(root).as_posix():
                candidates.append(path)
        if len(candidates) != 1:
            raise IntegrityError("Orphan/ambiguous corrected native cannot be completed retrospectively")
        path = candidates[0]
        completed, scope, native = read_bundle(root, path.relative_to(root).as_posix(), spec, now=clock())
        if scope["proof"] != proof or scope["output_sha256"] != digest(data):
            raise IntegrityError("Corrected retry changed the original board/proof")
        current = utc(clock())
        validate_plan(spec, data, current, root=root)
        from source_evidence import verified_status
        statuses = verified_status(closing_status, data["season"], data["week"], "live", current)
        if (set(statuses) != {game["id"] for game in data["games"]}
                or not 0 <= (current - utc(closing_status["collected_at"])).total_seconds() <= 60
                or any(utc(statuses[g["id"]]["kickoff"]) != utc(g["kickoff"])
                    or original._teams(closing_status, g["id"]) != {k: g[k] for k in ("home", "away")}
                    for g in data["games"])):
            raise IntegrityError("Corrected retry closing status/schedule mismatch")
        from reliability import validate
        health = validate(data, load_json(root / "output/data/meta.json"), current)
        health.update(capture_created=False, capture_mode="live", receipt=target.relative_to(root).as_posix(),
                      first_captured_at=native["captured_at"], capture_rows=len(native["rows"]))
        return target, health, path, scope
    at = utc(clock())
    verify_scope(root, data, proof, closing_status, spec, registration_name, at)
    path, health = capture(data, load_json(root / "output/data/meta.json"), root, utc(clock()), hashes,
                           mode="live", model=model)
    import phase2_capture
    native = phase2_capture.read_native_baseline(path, root, now=clock())
    scope = verify_scope(root, data, proof, closing_status, spec, registration_name, utc(clock()))
    scope_path = write(root, "verification/partial-scopes", scope)
    if original._saved(root, scope_path.relative_to(root).as_posix(), "verification/partial-scopes") != scope:
        raise IntegrityError("Corrected scope persistence/readback failed")
    completed_at = utc(clock())
    _cutoff(data, scope, completed_at)
    payload = {"schema_version": "partial-completion-data-integrity-v2", "season": data["season"], "week": data["week"],
               "validator_sha256": code_sha256(), "plan_sha256": spec["plan_sha256"], "output_sha256": digest(data),
               "scope_receipt": scope_path.relative_to(root).as_posix(), "scope_payload_sha256": digest(scope),
               "baseline_receipt": path.relative_to(root).as_posix(), "baseline_payload_sha256": digest(native),
               "evidence_completed_at": completed_at.isoformat()}
    completion_path = write(root, "verification/partial-completions", payload)
    try:
        read_bundle(root, completion_path.relative_to(root).as_posix(), spec, now=clock())
        _cutoff(data, scope, clock())
    except BaseException:
        write(root, "verification/partial-failures", {"schema_version": "completion-failure-data-integrity-v2",
              "season": data["season"], "week": data["week"], "completion_sha256": digest(payload),
              "failed_at": utc(clock()).isoformat(), "reason": "FINAL_COMPLETION_BOUNDARY_FAILED"})
        raise
    return path, health, completion_path, scope


def public_scope(scope, completion):
    return {"schema_version": "partial-week-public-scope-v1", "season": scope["season"], "week": scope["week"],
            "output_sha256": scope["output_sha256"], "plan_sha256": scope["plan_sha256"], "scope_sha256": digest(scope),
            "completion_sha256": digest(completion), "evidence_completed_at": completion["evidence_completed_at"],
            "full_board_verified": False, "complete_week_qualified": False,
            "claim": scope["claim"], "games": [{key: row[key] for key in (
                "game_id", "home", "away", "kickoff", "classification")} for row in scope["game_population"]]}
