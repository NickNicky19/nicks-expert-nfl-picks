"""Fresh source checks plus authenticated complete-CI evidence; never data proof.

No artifact storage, saved PASS shortcut, provider request or repository write.
Generation/input/native/scope/report/health checks remain separate and mandatory.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import sysconfig
import threading
import urllib.error
import urllib.parse
import urllib.request

VERSION = "source-ci-seal-v1"
FINGERPRINT = "source-ci-fingerprint-v1"
PREFIX = "SOURCE_CI_SEAL_V1 "
REPOSITORY = "NickNicky19/nicks-expert-nfl-picks"
REPOSITORY_ID = 1411185749
WORKFLOW_ID = 383746306
WORKFLOW_PATH = ".github/workflows/reliability-tests.yml"
JOB_NAME = "test"
SEAL_STEP = "Seal complete Phase 2 source checks"
REQUIRED_STEPS = ("Install existing dependencies", "Fingerprint Phase 2 source checks",
                  "Retained baseline and Phase 2 regression suites", "Python syntax",
                  "JavaScript and UI checks", "About comparison states", SEAL_STEP)
CHECKS = ("python -m unittest discover -s tests -v", "python -m compileall -q pull tools",
          "node --check output/app.js", "node --check output/reliability-ui.js",
          "node tests/test-ui.cjs", "node tests/test-about.cjs")
MUTABLE = ("output/data/", "data/cache/", "data/forward/", "data/history/",
           "data/verification/", "data/shadow/", "data/offers/", "data/outcomes/")
FIXTURE = "data/verification/2026/w06/dcf4bce0b2d3a162bdea39217eb6ae0ee2545e3895cce129338afc715a5e8e2a.json.gz"
API_LIMIT = 2 * 1024 * 1024
LOG_LIMIT = 16 * 1024 * 1024
FILE_LIMIT = 32 * 1024 * 1024
SOURCE_LIMIT = 64 * 1024 * 1024
ENV_LIMIT = 512 * 1024 * 1024
ENTRY_LIMIT = 20000
RUN_LIMIT = 1000
ANCESTRY_LIMIT = 1000
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")


class Rejected(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Rejected("Duplicate evidence key")
        result[key] = value
    return result


def decoded(raw, limit=API_LIMIT):
    if len(raw) > limit:
        raise Rejected("Evidence exceeds its bound")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Rejected("Nonfinite evidence")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Rejected("Malformed evidence") from error


def command(arguments, *, data=None, limit=SOURCE_LIMIT + ENTRY_LIMIT * 100, env=None, accepted=(0,)):
    """Bound reads while the child runs; never allocate unbounded captured output."""
    process = subprocess.Popen(arguments, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, start_new_session=True)
    result = bytearray(); exceeded = []
    def stop():
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    def read():
        while True:
            chunk = process.stdout.read(min(65536, limit + 1 - len(result)))
            if not chunk: break
            result.extend(chunk)
            if len(result) > limit:
                exceeded.append(True); stop(); break
    def feed():
        try: process.stdin.write(data); process.stdin.close()
        except (BrokenPipeError, OSError): pass
    reader = threading.Thread(target=read, daemon=True); reader.start()
    writer = threading.Thread(target=feed, daemon=True) if data is not None else None
    if writer: writer.start()
    try:
        code = process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        stop(); process.wait(); raise Rejected("Required command exceeded its bounded time") from None
    finally:
        reader.join(timeout=5)
        if writer: writer.join(timeout=5)
        process.stdout.close()
    if exceeded or reader.is_alive() or writer and writer.is_alive():
        raise Rejected("Required command output exceeds its bound")
    if code not in accepted:
        raise Rejected("Required local command evidence is unavailable")
    return bytes(result), code


def _git_environment():
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                 "GIT_REPLACE_REF_BASE", "GIT_NAMESPACE", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE", "GIT_CONFIG",
                 "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"):
        if os.environ.get(name):
            raise Rejected("Unsupported Git execution override")
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0")
    return env


def git(root, *args, data=None):
    return command(["git", "--no-replace-objects", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                    "-c", "core.hooksPath=/dev/null", "-C", str(root), *args], data=data, env=_git_environment())[0]


def _history_guard(root):
    path = Path(git(root, "rev-parse", "--git-path", "info/grafts").decode().strip())
    if not path.is_absolute(): path = root / path
    if path.exists() or git(root, "for-each-ref", "--format=%(refname)", "refs/replace"):
        raise Rejected("Grafted or replacement Git history is unsupported")


def mutable(name):
    return name != FIXTURE and name.startswith(MUTABLE) and name.endswith((".json", ".json.gz"))


def generated(name):
    return "__pycache__" in Path(name).parts


def _regular(path, root):
    try:
        path.relative_to(root)
    except ValueError as error:
        raise Rejected("Source path escaped its namespace") from error
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise Rejected("Symlink source dependency")
    if not path.is_file():
        raise Rejected("Missing or nonregular source dependency")


def _actual(path, limit=FILE_LIMIT):
    if path.stat().st_size > limit:
        raise Rejected("File exceeds its bound")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise Rejected("File grew beyond its bound")
    return raw


def _tree(root, commit):
    if not isinstance(commit, str) or not HEX40.fullmatch(commit):
        raise Rejected("An exact source commit is required")
    entries = []
    for record in git(root, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
        if not record:
            continue
        header, raw_name = record.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        name = raw_name.decode("utf-8")
        if mutable(name):
            continue
        if (kind != "blob" or mode not in ("100644", "100755") or name.startswith("/")
                or ".." in Path(name).parts or not HEX40.fullmatch(oid)):
            raise Rejected("Unsupported source tree entry")
        entries.append((name, mode, oid))
    if len(entries) > ENTRY_LIMIT or FIXTURE not in {x[0] for x in entries}:
        raise Rejected("Source closure or required retained fixture unavailable")
    return sorted(entries)


def _blobs(root, entries):
    ids = list(dict.fromkeys(oid for _, _, oid in entries))
    request = "".join(oid + "\n" for oid in ids).encode()
    sizes = git(root, "cat-file", "--batch-check", data=request).decode("ascii").splitlines()
    if len(sizes) != len(ids):
        raise Rejected("Incomplete source object size inventory")
    lengths = []
    for oid, header in zip(ids, sizes):
        fields = header.split()
        if len(fields) != 3 or fields[:2] != [oid, "blob"] or not fields[2].isdigit():
            raise Rejected("Unexpected source object type")
        length = int(fields[2])
        if length > FILE_LIMIT:
            raise Rejected("Source object exceeds its bound")
        lengths.append(length)
    if sum(lengths) > SOURCE_LIMIT:
        raise Rejected("Source object closure exceeds its bound")
    stream = git(root, "cat-file", "--batch", data=request)
    if len(stream) > SOURCE_LIMIT + len(ids) * 100:
        raise Rejected("Source object closure exceeds its bound")
    position, total, result = 0, 0, {}
    for oid in ids:
        end = stream.find(b"\n", position)
        if end < 0:
            raise Rejected("Truncated Git object closure")
        fields = stream[position:end].decode("ascii").split()
        if len(fields) != 3 or fields[0] != oid or fields[1] != "blob" or not fields[2].isdigit():
            raise Rejected("Unexpected Git object type")
        length = int(fields[2]); total += length
        if length > FILE_LIMIT or total > SOURCE_LIMIT:
            raise Rejected("Source object closure exceeds its bound")
        start = end + 1; raw = stream[start:start + length]
        if len(raw) != length or stream[start + length:start + length + 1] != b"\n":
            raise Rejected("Truncated Git object")
        if hashlib.sha1(b"blob " + str(length).encode() + b"\0" + raw).hexdigest() != oid:
            raise Rejected("Git blob content identity mismatch")
        result[oid] = raw; position = start + length + 1
    if position != len(stream):
        raise Rejected("Extra Git object bytes")
    return result


def source(root, commit=None, *, actual=True):
    root = Path(root).resolve()
    _history_guard(root)
    head = git(root, "rev-parse", "HEAD").decode().strip()
    commit = commit or head
    if actual and commit != head:
        raise Rejected("Executed checkout differs from claimed source")
    entries = _tree(root, commit); blobs = _blobs(root, entries); files = []
    if actual:
        for raw_name in git(root, "ls-files", "--others", "-z").split(b"\0"):
            if raw_name:
                name = raw_name.decode("utf-8")
                if not mutable(name) and not generated(name):
                    raise Rejected("Untracked executable/source input")
    for name, mode, oid in entries:
        raw = blobs[oid]
        if actual:
            path = root / name; _regular(path, root)
            if ("100755" if path.stat().st_mode & stat.S_IXUSR else "100644") != mode:
                raise Rejected("Source mode differs from committed code")
            if _actual(path) != raw:
                raise Rejected("Actual source bytes differ from committed code")
        files.append(dict(path=name, mode=mode, blob=oid, bytes=len(raw), sha256=sha(raw)))
    return dict(schema_version=FINGERPRINT, commit=commit,
                tree=git(root, "rev-parse", commit + "^{tree}").decode().strip(),
                source_manifest_sha256=sha(canonical(files)), files=files)


def _file_hash(path, limit=ENV_LIMIT):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise Rejected("Runtime dependency unavailable or oversized")
    h = hashlib.sha256(); length = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            length += len(chunk)
            if length > limit:
                raise Rejected("Runtime dependency grew beyond its bound")
            h.update(chunk)
    return length, h.hexdigest()


def _runtime_guard(root, standard, sites):
    """Only the reviewed interpreter/import arrangement can receive a seal.

    The workflow must create this empty prefix BEFORE Python startup, for each
    command separately, with bytecode writes disabled. A post-startup check
    cannot undo a malicious startup; it refuses to certify one.
    """
    allowed = {"PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "LD_LIBRARY_PATH"}
    for name, value in os.environ.items():
        if value and ((name.startswith(("PYTHON", "NODE_", "LD_", "DYLD_")) and name not in allowed)
                      or name in ("NODE_PATH", "BASH_ENV", "ENV")):
            raise Rejected("Unsupported interpreter or dynamic-loader override")
    if os.environ.get("PYTHONUNBUFFERED", "1") not in ("", "1"):
        raise Rejected("Unsupported Python runtime option")
    library = Path(sys.base_prefix).resolve() / "lib"
    if os.environ.get("LD_LIBRARY_PATH") and os.environ["LD_LIBRARY_PATH"] != str(library):
        raise Rejected("Unexpected Python dynamic-library search path")
    prefix = os.environ.get("PYTHONPYCACHEPREFIX")
    if (not prefix or not sys.pycache_prefix or Path(prefix).resolve() != Path(sys.pycache_prefix).resolve()
            or os.environ.get("PYTHONDONTWRITEBYTECODE") != "1" or not sys.dont_write_bytecode):
        raise Rejected("A fresh pre-startup bytecode prefix with writes disabled is required")
    cache = Path(prefix)
    if cache.is_symlink() or not cache.is_dir():
        raise Rejected("Bytecode prefix is missing or unsafe")
    with os.scandir(cache) as items:
        if next(items, None) is not None:
            raise Rejected("Bytecode prefix is not fresh and empty")
    root = Path(root).resolve()
    allowed_roots = {root, *standard, *sites}
    if any(cache.resolve().is_relative_to(item) for item in allowed_roots):
        raise Rejected("Bytecode prefix overlaps imported source")
    # CPython commonly names a nonexistent stdlib ZIP. An existing ZIP is not
    # enumerable by this bounded contract and therefore cannot be certified.
    optional_zip = {item.parent / ("python" + str(sys.version_info.major) + str(sys.version_info.minor) + ".zip") for item in standard}
    paths = []
    for value in sys.path:
        path = Path(value or os.getcwd()).resolve()
        if path in optional_zip and not path.exists():
            paths.append("absent-standard-zip"); continue
        if not path.is_dir() or not any(path.is_relative_to(item) for item in allowed_roots):
            raise Rejected("Unexpected Python import path")
        # Store logical namespaces rather than differing checkout/toolcache paths.
        matches = sorted((len(str(item)), item) for item in allowed_roots if path.is_relative_to(item))
        base = matches[-1][1]
        kind = "repository" if base == root else "site" if base in sites else "standard"
        paths.append(kind + ":" + path.relative_to(base).as_posix())
    return dict(import_paths=paths, bytecode="fresh-prefix-no-write-v1")


def environment(root=None):
    """Hash installed bytes, not RECORD claims, mtime, or version strings alone."""
    packages, roots, outside = [], set(), []
    declared_entries, metadata_bytes = 0, 0
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    for dist in importlib.metadata.distributions():
        if len(packages) >= ENTRY_LIMIT:
            raise Rejected("Installed distribution inventory exceeds its bound")
        metadata = Path(getattr(dist, "_path", ""))
        if not metadata.is_dir() or not (metadata / "METADATA").is_file() or not (metadata / "RECORD").is_file():
            raise Rejected("Only enumerable installed wheel metadata is supported")
        metadata_bytes += len(_actual(metadata / "METADATA"))
        record = _actual(metadata / "RECORD"); metadata_bytes += len(record)
        if metadata_bytes > ENV_LIMIT:
            raise Rejected("Distribution metadata exceeds its aggregate bound")
        if len(record.splitlines()) > ENTRY_LIMIT:
            raise Rejected("Installed distribution file inventory exceeds its bound")
        name, version = dist.metadata.get("Name"), dist.version
        if not name or not version:
            raise Rejected("Unenumerable Python distribution")
        location = Path(dist.locate_file("")).resolve(); roots.add(location)
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        packages.append(dict(name=normalized, version=version))
        for row in csv.reader(record.decode("utf-8").splitlines()):
            declared_entries += 1
            if declared_entries > ENTRY_LIMIT:
                raise Rejected("Declared distribution inventory exceeds its aggregate bound")
            if len(row) != 3: raise Rejected("Malformed installed distribution inventory")
            filename = row[0]
            if generated(filename) or Path(filename).name == "RECORD": continue
            path = Path(dist.locate_file(filename))
            if path.is_symlink() or not path.is_file():
                raise Rejected("Missing or symlink installed distribution file")
            if not path.resolve().is_relative_to(location):
                if not any(path.resolve().is_relative_to(Path(prefix).resolve()) for prefix in (sys.prefix, sys.base_prefix)):
                    raise Rejected("Installed script escaped the interpreter namespace")
                length, checksum = _file_hash(path)
                outside.append(dict(distribution=normalized, path=filename, bytes=length, sha256=checksum))
                if len(outside) > ENTRY_LIMIT or sum(item["bytes"] for item in outside) > ENV_LIMIT:
                    raise Rejected("Installed entry points exceed their aggregate bound")
    packages.sort(key=lambda item: (item["name"], item["version"]))
    if len({p["name"] for p in packages}) != len(packages):
        raise Rejected("Ambiguous installed Python distributions")
    standard = {Path(sysconfig.get_path(name)).resolve() for name in ("stdlib", "platstdlib")}
    dynamic = Path(sysconfig.get_config_var("DESTSHARED") or next(iter(standard)) / "lib-dynload").resolve()
    if not any(dynamic.is_relative_to(item) for item in standard):
        raise Rejected("Dynamic-module path escaped the standard runtime")
    guard = _runtime_guard(root, standard, roots)
    # setup-python's sole supported loader override points here. Hash the actual
    # shared libpython target as well as the executable; do not trust its SONAME.
    library = Path(sys.base_prefix).resolve() / "lib"
    shared_name = sysconfig.get_config_var("LDLIBRARY")
    shared = None
    if sysconfig.get_config_var("Py_ENABLE_SHARED"):
        if not isinstance(shared_name, str) or Path(shared_name).name != shared_name:
            raise Rejected("Unknown shared Python runtime")
        shared_path = (library / shared_name).resolve()
        if not shared_path.is_relative_to(library):
            raise Rejected("Shared Python runtime escaped its namespace")
        length, checksum = _file_hash(shared_path)
        shared = dict(name=shared_name, bytes=length, sha256=checksum)
    elif os.environ.get("LD_LIBRARY_PATH"):
        raise Rejected("Loader override is unsupported for this Python build")
    inventory, total, enumerated = [], shared["bytes"] if shared else 0, 0
    # External wheel entry points are part of the same aggregate bound.
    if len(outside) > ENTRY_LIMIT:
        raise Rejected("Installed script closure exceeds its bound")
    total += sum(item["bytes"] for item in outside)
    if total > ENV_LIMIT:
        raise Rejected("Installed script closure exceeds its bound")
    for index, root in enumerate(sorted(roots)):
        if not root.is_dir():
            raise Rejected("Missing installed distribution root")
        pending, files = [root], []
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    enumerated += 1
                    if enumerated > ENTRY_LIMIT:
                        raise Rejected("Installed runtime enumeration exceeds its bound")
                    if entry.name == "__pycache__": continue
                    if entry.is_symlink(): raise Rejected("Symlink installed distribution")
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False): pending.append(path)
                    elif entry.is_file(follow_symlinks=False): files.append(path)
                    else: raise Rejected("Nonregular installed distribution")
        for path in sorted(files):
            name = path.relative_to(root).as_posix()
            if generated(name) or path.name == "RECORD" and path.parent.name.endswith(".dist-info"):
                continue
            if path.is_symlink():
                raise Rejected("Symlink installed distribution")
            if not path.is_file():
                continue
            length, checksum = _file_hash(path); total += length
            if total > ENV_LIMIT or len(inventory) + len(outside) >= ENTRY_LIMIT:
                raise Rejected("Installed runtime closure exceeds its bound")
            inventory.append(dict(root=index, path=name, bytes=length, sha256=checksum))
    standard_files = []
    for index, base in enumerate(sorted(standard)):
        if not base.is_dir(): raise Rejected("Standard library is unavailable")
        pending = [base]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    enumerated += 1
                    if enumerated > ENTRY_LIMIT:
                        raise Rejected("Runtime enumeration exceeds its bound")
                    path = Path(entry.path)
                    if entry.name == "__pycache__" or path in roots: continue
                    if entry.is_symlink(): raise Rejected("Symlink standard runtime dependency")
                    if entry.is_dir(follow_symlinks=False): pending.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        if path.suffix not in (".py", ".pyc") and not path.is_relative_to(dynamic): continue
                        length, checksum = _file_hash(path); total += length
                        if total > ENV_LIMIT or len(inventory) + len(standard_files) + len(outside) >= ENTRY_LIMIT:
                            raise Rejected("Complete runtime closure exceeds its bound")
                        standard_files.append(dict(root=index, path=path.relative_to(base).as_posix(), bytes=length, sha256=checksum))
                    else: raise Rejected("Nonregular standard runtime dependency")
    standard_files.sort(key=lambda item: (item["root"], item["path"]))
    def tool(name, command):
        path = shutil.which(name)
        if not path:
            raise Rejected("Required runtime tool unavailable")
        version = globals()["command"](command, limit=4096)[0].decode().strip()
        return dict(version=version, binary_sha256=_file_hash(Path(path).resolve())[1])
    return dict(python=dict(version=sys.version, implementation=sys.implementation.cache_tag,
                           soabi=sysconfig.get_config_var("SOABI"), shared_library=shared, binary_sha256=_file_hash(Path(sys.executable).resolve())[1]),
                node=tool("node", ["node", "--version"]), git=tool("git", ["git", "--version"]),
                image=dict(os=os.environ.get("ImageOS"), version=os.environ.get("ImageVersion"), architecture=platform.machine()),
                import_contract=guard, standard_files_sha256=sha(canonical(standard_files)), standard_files=len(standard_files),
                distributions=packages, installed_files_sha256=sha(canonical(inventory)), installed_files=len(inventory),
                installed_scripts=sorted(outside, key=lambda item: (item["distribution"], item["path"])))


def fingerprint(root):
    result = source(root); result["environment"] = environment(root)
    return result


def _context():
    def number(name):
        value = os.environ.get(name, "")
        if not value.isdigit() or int(value) < 1:
            raise Rejected("Missing authenticated Actions execution identity")
        return int(value)
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or number("GITHUB_REPOSITORY_ID") != REPOSITORY_ID
            or os.environ.get("GITHUB_EVENT_NAME") not in ("push", "workflow_dispatch")
            or os.environ.get("GITHUB_JOB") != JOB_NAME):
        raise Rejected("Unsupported CI provenance")
    return dict(repository=REPOSITORY, repository_id=REPOSITORY_ID, run_id=number("GITHUB_RUN_ID"),
                run_attempt=number("GITHUB_RUN_ATTEMPT"), event=os.environ["GITHUB_EVENT_NAME"],
                branch=os.environ.get("GITHUB_REF_NAME"), workflow_path=WORKFLOW_PATH, job_name=JOB_NAME)


def seal(root, initial):
    context = _context(); current = fingerprint(root)
    if current != initial or current["commit"] != os.environ.get("GITHUB_SHA"):
        raise Rejected("Source or runtime changed during retained CI checks")
    if not current["environment"]["image"]["os"] or not current["environment"]["image"]["version"]:
        raise Rejected("Hosted runtime image identity unavailable")
    # Recovery-only CI does not qualify the complete active Phase 2 suite.
    sys.path.insert(0, str(Path(root).resolve() / "tools"))
    from release_mode import read_mode, read_phase2
    if read_mode(root) != "phase1" or not read_phase2(root):
        raise Rejected("Complete Phase 2 checks were not selected")
    result = dict(schema_version=VERSION, **context, **{k: current[k] for k in ("commit", "tree", "source_manifest_sha256", "files", "environment")}, checks=list(CHECKS))
    if len(canonical(result)) > API_LIMIT:
        raise Rejected("CI seal exceeds its bound")
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


class GitHub:
    """Read-only bounded transport. Credentials never follow log redirects."""
    def __init__(self):
        self.token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    def get(self, path, *, logs=False):
        if (path and not path.startswith("/")) or ".." in path:
            raise Rejected("Unsupported GitHub evidence route")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nfl-source-ci-v1", "Cache-Control": "no-cache"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        url = "https://api.github.com/repos/" + REPOSITORY + path
        limit = LOG_LIMIT if logs else API_LIMIT
        try:
            opener = urllib.request.build_opener(_NoRedirect)
            try:
                response = opener.open(urllib.request.Request(url, headers=headers), timeout=30)
            except urllib.error.HTTPError as error:
                target = urllib.parse.urlsplit(error.headers.get("Location", ""))
                if (not logs or error.code not in (301, 302, 303, 307, 308) or target.scheme != "https"
                        or target.username or target.password or not target.hostname
                        or not (target.hostname.endswith(".blob.core.windows.net") or target.hostname.endswith(".actions.githubusercontent.com"))):
                    raise Rejected("GitHub evidence unavailable") from None
                response = opener.open(urllib.request.Request(target.geturl(), headers={"User-Agent": "nfl-source-ci-v1"}), timeout=30)
            with response:
                if response.headers.get("Content-Length", "").isdigit() and int(response.headers["Content-Length"]) > limit:
                    raise Rejected("GitHub evidence exceeds its bound")
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise Rejected("GitHub evidence exceeds its bound")
            return raw if logs else decoded(raw)
        except (urllib.error.URLError, OSError):
            # Do not expose signed redirects, credentials or raw response bodies.
            raise Rejected("GitHub evidence transport failed") from None


def _descendant(root, ancestor, head):
    # Normal protected merges are supported. Exact current input bytes and
    # runtime equivalence are checked separately; no historical data is qualified.
    result = command(["git", "--no-replace-objects", "-C", str(root), "merge-base", "--is-ancestor", ancestor, head],
                     env=_git_environment(), limit=4096, accepted=(0, 1))
    return result[1] == 0


def _log_seal(raw):
    if len(raw) > LOG_LIMIT:
        raise Rejected("CI job log exceeds its bound")
    matches = []
    for line in raw.decode("utf-8-sig").splitlines():
        line = re.sub(r"^\d{4}-\d\d-\d\dT[0-9:.]+Z\s+", "", line)
        if line.startswith(PREFIX):
            matches.append(decoded(line[len(PREFIX):].encode()))
    if len(matches) != 1:
        raise Rejected("Exactly one complete CI seal is required")
    return matches[0]


def _attempt_identity(run):
    attempt, started, created = run.get("run_attempt"), run.get("run_started_at"), run.get("created_at")
    if type(attempt) is not int or attempt < 1 or not isinstance(started, str) or not isinstance(created, str):
        raise Rejected("CI attempt execution timestamp is unavailable")
    try:
        stamp = datetime.fromisoformat(started.replace("Z", "+00:00"))
        original = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        raise Rejected("Malformed CI attempt execution timestamp") from None
    if stamp.tzinfo is None or original.tzinfo is None or stamp < original:
        raise Rejected("Inconsistent CI attempt execution timestamp")
    return (stamp, run["id"], attempt)


def _runs(api, route):
    """A finite complete inventory; never ignore an old run's newer attempt."""
    all_runs, seen, expected, page = [], set(), None, 1
    while True:
        response = api.get(route if page == 1 else route + "&page=" + str(page))
        count, runs = response.get("total_count"), response.get("workflow_runs")
        if type(count) is not int or count < 0 or count > RUN_LIMIT or not isinstance(runs, list):
            raise Rejected("Complete workflow-run inventory is unavailable or exceeds its bound")
        if expected is None: expected = count
        if count != expected or len(runs) != min(100, expected - len(all_runs)):
            raise Rejected("Workflow-run inventory changed or was truncated during retrieval")
        for run in runs:
            identity = run.get("id")
            if type(identity) is not int or identity < 1 or identity in seen:
                raise Rejected("Duplicate or malformed workflow-run inventory")
            seen.add(identity); all_runs.append(run)
        if len(all_runs) == expected:
            return dict(total_count=expected, workflow_runs=all_runs)
        page += 1


def _newest(root, current, listed):
    candidates = []
    actual_tree = [(f["path"], f["mode"], f["blob"]) for f in current["files"]]
    for run in listed.get("workflow_runs", []):
        commit = run.get("head_sha")
        if (run.get("event") not in ("push", "workflow_dispatch") or run.get("workflow_id") != WORKFLOW_ID
                or (run.get("repository") or {}).get("id") != REPOSITORY_ID
                or (run.get("head_repository") or {}).get("id") != REPOSITORY_ID
                or run.get("head_branch") not in ("main", "upgrade/phase2-reproducible-comparison")
                or not isinstance(commit, str) or not HEX40.fullmatch(commit)):
            continue
        try:
            # Matching blob IDs refer to the actual objects freshly read and
            # verified in current. No repeated decode/hash of the same bytes.
            compatible = _tree(root, commit) == actual_tree and _descendant(root, commit, current["commit"])
        except Rejected:
            compatible = False
        if compatible:
            candidates.append(run)
    if not candidates:
        raise Rejected("No source-compatible complete CI run is available")
    return max(candidates, key=_attempt_identity)


def verify(root, *, api=None, run_id=None):
    """Use newest source-compatible run, never select an older passing sample."""
    root = Path(root).resolve(); current = fingerprint(root); api = api or GitHub()
    repository = api.get("")
    if repository.get("id") != REPOSITORY_ID or repository.get("full_name") != REPOSITORY or repository.get("private") is not False:
        raise Rejected("Unexpected public repository identity")
    workflow = api.get("/actions/workflows/" + str(WORKFLOW_ID))
    if workflow.get("id") != WORKFLOW_ID or workflow.get("path") != WORKFLOW_PATH or workflow.get("state") != "active":
        raise Rejected("Unexpected source-check workflow")
    route = "/actions/workflows/" + str(WORKFLOW_ID) + "/runs?per_page=100"
    candidate = _newest(root, current, _runs(api, route))
    if run_id is not None and candidate["id"] != run_id:
        raise Rejected("Requested CI run is stale or unrelated")
    run = api.get("/actions/runs/" + str(candidate["id"]))
    for field in ("id", "head_sha", "event", "workflow_id", "head_branch", "run_attempt", "run_started_at", "created_at"):
        if run.get(field) != candidate.get(field):
            raise Rejected("CI run changed during evidence retrieval")
    if ((run.get("repository") or {}).get("id") != REPOSITORY_ID
            or (run.get("head_repository") or {}).get("id") != REPOSITORY_ID):
        raise Rejected("CI run repository identity changed")
    if run.get("status") != "completed" or run.get("conclusion") != "success" or type(run.get("run_attempt")) is not int:
        raise Rejected("Newest compatible CI run is not completed success")
    attempt = api.get(f"/actions/runs/{run['id']}/attempts/{run['run_attempt']}")
    if any(attempt.get(key) != run.get(key) for key in ("id", "run_attempt", "run_started_at", "created_at", "head_sha", "event", "workflow_id", "head_branch", "status", "conclusion")):
        raise Rejected("Authenticated attempt execution identity mismatch")
    _attempt_identity(attempt)
    job_page = api.get(f"/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
    jobs = job_page.get("jobs", [])
    if job_page.get("total_count") != len(jobs) or len(jobs) != 1:
        raise Rejected("Unexpected source-check job inventory")
    job = jobs[0]; steps = job.get("steps", [])
    if (job.get("name") != JOB_NAME or job.get("head_sha") != run["head_sha"]
            or job.get("run_id") != run["id"] or job.get("run_attempt") != run["run_attempt"]
            or job.get("status") != "completed" or job.get("conclusion") != "success"
            or len({s.get("name") for s in steps}) != len(steps)
            or any(s.get("conclusion") != "success" for s in steps)):
        raise Rejected("Complete retained source checks did not pass")
    names = [step.get("name") for step in steps]
    if any(name not in names for name in REQUIRED_STEPS) or [names.index(name) for name in REQUIRED_STEPS] != sorted(names.index(name) for name in REQUIRED_STEPS):
        raise Rejected("Required source-check steps missing, skipped or reordered")
    if any(not name.startswith("Post ") and name != "Complete job" for name in names[names.index(SEAL_STEP) + 1:]):
        raise Rejected("CI seal is not the final regular step")
    value = _log_seal(api.get("/actions/jobs/" + str(job["id"]) + "/logs", logs=True))
    expected_keys = {"schema_version", "repository", "repository_id", "run_id", "run_attempt", "event", "branch", "workflow_path", "job_name", "commit", "tree", "source_manifest_sha256", "files", "environment", "checks"}
    if (set(value) != expected_keys or value.get("schema_version") != VERSION or value["repository"] != REPOSITORY
            or value["repository_id"] != REPOSITORY_ID or value["run_id"] != run["id"]
            or value["run_attempt"] != run["run_attempt"] or value["event"] != run["event"]
            or value["branch"] != run["head_branch"] or value["workflow_path"] != WORKFLOW_PATH
            or value["job_name"] != JOB_NAME or value["commit"] != run["head_sha"] or value["checks"] != list(CHECKS)):
        raise Rejected("CI seal provenance or complete check contract mismatch")
    previous = source(root, run["head_sha"], actual=False)
    if (any(value[key] != previous[key] for key in ("commit", "tree", "source_manifest_sha256", "files"))
            or value["environment"] != current["environment"]):
        raise Rejected("Executed source or actual installed runtime differs from complete CI")
    final = api.get("/actions/runs/" + str(run["id"]))
    if (final.get("status"), final.get("conclusion"), final.get("run_attempt"), final.get("head_sha")) != ("completed", "success", run["run_attempt"], run["head_sha"]):
        raise Rejected("CI result or latest attempt changed during verification")
    if (final.get("run_started_at"), final.get("created_at")) != (run["run_started_at"], run["created_at"]):
        raise Rejected("CI attempt execution timestamp changed during verification")
    newest = _newest(root, current, _runs(api, route))
    final_keys = ("id", "run_attempt", "run_started_at", "created_at", "head_sha", "status", "conclusion", "event", "workflow_id", "head_branch")
    if any(newest.get(key) != run.get(key) for key in final_keys):
        raise Rejected("A newer or changed compatible CI execution appeared during verification")
    # This complete byte/runtime check must be AFTER all transport reads; a
    # mutation during a final API call cannot inherit the earlier fingerprint.
    if fingerprint(root) != current:
        raise Rejected("Executed source or runtime changed during gate verification")
    return dict(schema_version="source-ci-verification-v1", executed_commit=current["commit"],
                executed_tree=current["tree"], source_manifest_sha256=current["source_manifest_sha256"],
                source_ci_commit=run["head_sha"], run_id=run["id"], run_attempt=run["run_attempt"],
                job_id=job["id"], seal_sha256=sha(canonical(value)), environment_sha256=sha(canonical(current["environment"])),
                claim="COMPLETE_SOURCE_CHECKS_ONLY_NOT_GENERATION_OR_OPERATING_QUALIFICATION")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fingerprint", "seal", "verify"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--initial", type=Path)
    parser.add_argument("--run-id", type=int)
    args = parser.parse_args()
    try:
        if args.command == "fingerprint":
            result = fingerprint(args.root)
        elif args.command == "seal":
            if not args.initial:
                raise Rejected("Initial pre-check fingerprint is required")
            result = seal(args.root, decoded(_actual(args.initial, API_LIMIT)))
        else:
            result = verify(args.root, run_id=args.run_id)
        print((PREFIX if args.command == "seal" else "") + canonical(result).decode())
    except (Rejected, OSError, KeyError, TypeError, UnicodeError) as error:
        print("Source CI gate rejected: " + (str(error) if isinstance(error, Rejected) else "unavailable or malformed required evidence"), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
