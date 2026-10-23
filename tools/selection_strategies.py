"""Prospective, immutable ranked selections, separate from production Top Picks.

The existing updater supplies qualified original inputs. Saved consumption pins
the same completed evidence and never ranks an old observation retrospectively.
"""
from datetime import datetime, timezone
from datetime import timedelta
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from contextlib import contextmanager

from evidence import read, write
from reliability import IntegrityError, canonical, digest, load_json, stamp, utc
import data_integrity_v2 as corrected

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = "tools/selection-strategies-v1.json"
VERSION = "ranked-selection-observation-v1"
COMPLETION = "ranked-selection-completion-v1"
LANE = "verification/ranked-selections"
COMPLETE_LANE = "verification/ranked-selection-completions"
FAILURE_LANE = "verification/ranked-selection-failures"
STRATEGIES = ("ranked_biggest_lean_v1", "ranked_projected_points_v1")
SOURCE_PATHS = ("tools/selection_strategies.py", POLICY_PATH, "tools/phase2_capture.py",
                "tools/reliability.py", "tools/partial_week.py", "tools/data_integrity_v2.py",
                "tools/verify.py", "tools/scorecard.py", "tools/selection_report.py", "tools/evidence.py",
                "pull/build.py", "pull/scoring.py")
RETAINED_SOURCE = "e2dd96a31690baad04c8660302933f45f77d72e7"
RETAINED_TREE = "d02544420316557ddf1451a0753c2321e3d2a245"
RETAINED_SOURCES = {
    RETAINED_SOURCE: RETAINED_TREE,
    "04519b54dfb76dcca7916fe6bf75d7e1711793b6": "10a5cc1539c51c8089fb7ff077447b6d17c4e13e",
}


@contextmanager
def _retained_source(source_sha=RETAINED_SOURCE):
    """Actual closed prior source, never current code wearing an old label."""
    if source_sha not in RETAINED_SOURCES:
        raise IntegrityError("Unsupported retained ranked source identity")
    source_tree = RETAINED_SOURCES[source_sha]
    git = lambda *args: corrected._git(ROOT, *args)
    commit = git("cat-file", "commit", source_sha)
    if (hashlib.sha1(b"commit " + str(len(commit)).encode() + b"\0" + commit).hexdigest() != source_sha
            or commit.splitlines()[0] != b"tree " + source_tree.encode()):
        raise IntegrityError("Retained ranked commit/tree identity mismatch")
    entries, trees = [], {}
    def tree(oid, prefix=""):
        if len(trees) + len(entries) >= 512 or int(git("cat-file", "-s", oid)) > 4 * 1024**2:
            raise IntegrityError("Retained ranked tree exceeds supported closure")
        raw = git("cat-file", "tree", oid)
        if hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != oid:
            raise IntegrityError("Retained ranked tree is corrupt")
        trees[oid] = raw
        offset, names = 0, set()
        while offset < len(raw):
            end = raw.index(b"\0", offset)
            mode, encoded_name = raw[offset:end].split(b" ", 1)
            name = encoded_name.decode(); child = raw[end + 1:end + 21]
            if (len(child) != 20 or name in names or not name or name in (".", "..") or "/" in name or "\\" in name):
                raise IntegrityError("Unsupported retained ranked tree entry")
            names.add(name); offset = end + 21
            if not prefix and name not in ("tools", "pull", "config"): continue
            path = prefix + name; child = child.hex()
            if mode == b"40000":
                tree(child, path + "/"); continue
            if mode not in (b"100644", b"100755") or not prefix:
                raise IntegrityError("Unsupported retained ranked source entry")
            size = int(git("cat-file", "-s", child))
            if (size > 4 * 1024**2 or len(trees) + len(entries) >= 512
                    or sum(len(v) for _, _, v in entries) + size > 16 * 1024**2):
                raise IntegrityError("Retained ranked source exceeds supported closure")
            body = git("cat-file", "blob", child)
            if len(body) != size or hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest() != child:
                raise IntegrityError("Retained ranked source blob is corrupt")
            entries.append((path, child, body))
    tree(source_tree)
    if not entries or len(entries) > 512 or sum(len(raw) for _, _, raw in entries) > 16 * 1024**2:
        raise IntegrityError("Retained ranked source exceeds supported closure")
    # Replay the actual previous dispatcher/report/wrapper together. The saved
    # snapshot plan selector changed; native, scope, engine, clocks and policy
    # still require the exact shared qualification dependencies below.
    changed = {"tools/selection_strategies.py", "tools/selection_report.py", "tools/selection_publication.py",
               "tools/phase2_capture.py"}
    from reliability import ENGINE_PATHS
    shared = (set(SOURCE_PATHS) | set(ENGINE_PATHS)) - changed
    for name, _, raw in entries:
        if name in shared and (ROOT / name).read_bytes() != raw:
            raise IntegrityError("Retained ranked qualification dependency changed")
    with tempfile.TemporaryDirectory(prefix="nfl-retained-ranked-") as directory:
        source = Path(directory)
        for name, _, raw in entries:
            target = source / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        # Read-only access to the already retained actual Git objects. No
        # alternates, ref mutation, network retrieval or copied private history.
        git_dir = git("rev-parse", "--absolute-git-dir").decode().strip()
        (source / ".git").write_text("gitdir: " + git_dir + "\n")
        yield source
        if git("cat-file", "commit", source_sha) != commit:
            raise IntegrityError("Retained ranked commit changed during validation")
        if any(git("cat-file", "tree", oid) != raw for oid, raw in trees.items()):
            raise IntegrityError("Retained ranked tree changed during validation")
        for name, oid, raw in entries:
            if (git("cat-file", "blob", oid) != raw or (source / name).read_bytes() != raw
                    or name in shared and (ROOT / name).read_bytes() != raw):
                raise IntegrityError("Retained ranked source changed during validation")


def _retained_call(root, operation, payload, at, *, source_sha=RETAINED_SOURCE):
    """Fresh actual-source replay. No durable or cross-root PASS cache."""
    import phase2_capture
    from phase2_capture import _dependency_closure
    from writer_gate import strict_json
    root = Path(root).resolve()
    before = _dependency_closure(root)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "GITHUB_SHA"}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_LAZY_FETCH="1",
               GIT_OPTIONAL_LOCKS="0", PYTHONDONTWRITEBYTECODE="1")
    program = """import json,sys,resource
resource.setrlimit(resource.RLIMIT_FSIZE,(128*1024**2,128*1024**2))
from pathlib import Path
sys.path[:0]=[str(Path.cwd()/'tools'),str(Path.cwd()/'pull')]
import selection_strategies as s
from reliability import utc
from scorecard import identity
p=json.load(sys.stdin)
import phase2_capture
from datetime import datetime
class ValidationClock(datetime):
 @classmethod
 def now(cls,tz=None):return utc(p['validation_now'])
phase2_capture.datetime=ValidationClock
try:
 if p['operation']=='completed':
  value=s.read_completed(Path(p['root']),p['payload']['name'],now=utc(p['at']))
 elif p['operation']=='records':
  snapshots=p['payload']['snapshots']
  for snapshot in snapshots:
   rows=snapshot['rows']; snapshot['rows']={identity(row):row for row in rows}
   if len(rows)!=len(snapshot['rows']):raise ValueError('Duplicate pinned ranked rows')
  value=s._records(snapshots,p['payload']['timing'],utc(p['at']))
 else:raise ValueError('Unsupported retained operation')
 Path(sys.argv[1]).write_text(json.dumps({'value':value},allow_nan=False,separators=(',',':')))
except Exception as error:
 Path(sys.argv[1]).write_text(json.dumps({'error':type(error).__name__,'detail':str(error)[:400]}));sys.exit(2)
"""
    request = canonical({"root": str(root), "operation": operation, "payload": payload, "at": stamp(at),
                         "validation_now": stamp(phase2_capture.datetime.now(timezone.utc))})
    if len(request) > 128 * 1024**2:
        raise IntegrityError("Retained ranked replay request exceeds supported bound")
    with _retained_source(source_sha) as source:
        output = source / "retained-result.json"
        result = subprocess.run([sys.executable, "-c", program, str(output)], cwd=source, env=env,
                                input=request, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        if not output.is_file():
            raise IntegrityError("Retained ranked child did not produce a supported result")
        with output.open("rb") as handle: raw = handle.read(128 * 1024**2 + 1)
        if len(raw) > 128 * 1024**2 or _dependency_closure(root) != before:
            raise IntegrityError("Retained ranked replay exceeded bound or dependencies changed")
        value = strict_json(raw.decode())
        if result.returncode:
            error = UnqualifiedStrategy if value.get("error") == "UnqualifiedStrategy" else IntegrityError
            raise error("Retained ranked validation rejected: " + value.get("detail", "unsupported result"))
        if set(value) != {"value"}:
            raise IntegrityError("Unsupported retained ranked replay result")
        return value["value"]

class UnqualifiedStrategy(IntegrityError):
    """A preserved, explicitly failed completion never supplies decisions."""


def policy(root=ROOT):
    value = load_json(Path(root) / POLICY_PATH)
    installed = load_json(ROOT / POLICY_PATH)
    if value != installed or value.get("schema_version") != "ranked-selection-policy-v1" or value.get("strategies") != list(STRATEGIES):
        raise IntegrityError("Unsupported ranked selection registration")
    utc(value["registered_at"])
    return value


def _source(root, source_sha):
    """Actual installed helper bytes must exist at the asserted source commit."""
    import re
    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise IntegrityError("Ranked selection needs an exact source")
    installed = {name: (ROOT / name).read_bytes() for name in SOURCE_PATHS}
    for repository in dict.fromkeys((Path(root).resolve(), ROOT)):
        try:
            actual = {name: subprocess.check_output(["git", "-C", str(repository), "show", source_sha + ":" + name], stderr=subprocess.PIPE) for name in SOURCE_PATHS}
        except subprocess.CalledProcessError:
            continue
        if actual != installed:
            raise IntegrityError("Ranked selection source/helper bytes differ")
        return {name: hashlib.sha256(raw).hexdigest() for name, raw in actual.items()}
    raise IntegrityError("Ranked selection source objects unavailable")


def rank(board, native, rules, at):
    """Deterministic supported candidates; no new forecast or outcome input."""
    import build
    from scorecard import identity
    at = utc(at)
    games = {g["id"]: g for g in board["games"]}
    originals = {identity(row): row for row in native["rows"]}
    if len(originals) != len(native["rows"]) or digest(board) != native["input_sha256"]:
        raise IntegrityError("Ranked candidate board/native mismatch")
    candidates, excluded = [], []
    for player in sorted(board["players"], key=lambda p: (p["game_id"], p["id"])):
        game = games[player["game_id"]]
        for prop in sorted(player.get("props", []), key=lambda p: p["key"]):
            key = (board["season"], board["week"], game["id"], player["id"], prop["key"])
            row = originals.get(key)
            reason = None
            if not row: reason = "no_qualified_original_native_row"
            elif game["state"] != "pre" or utc(game["kickoff"]) <= at or player.get("late"): reason = "not_new_pregame_eligible"
            elif prop["key"] not in rules["categories"]: reason = "unsupported_category"
            elif prop.get("line_from") not in ("dk", "sleeper"): reason = "missing_real_reference_source"
            elif prop.get("lean") not in ("over", "under"): reason = "observed_no_side"
            elif type(player.get("proj_ppr")) not in (int, float) or not __import__("math").isfinite(player["proj_ppr"]): reason = "missing_direct_player_ppr"
            else:
                for name in ("proj", "adj", "line"):
                    value = prop.get(name)
                    if type(value) not in (int, float) or not __import__("math").isfinite(value): reason = "unknown_projection_or_line"
                if reason is None and not build.pick_candidates(dict(player, props=[prop])): reason = "production_eligibility_not_met"
            if reason:
                excluded.append({"opportunity": list(key), "reason": reason}); continue
            if any(row.get(target) != prop.get(source) for source, target in
                   (("proj", "raw_projection"), ("adj", "adjusted_projection"), ("line", "line"), ("lean", "lean"), ("line_from", "line_from"))):
                raise IntegrityError("Ranked candidate differs from saved native contract")
            candidates.append({"row": row, "direct_player_ppr": player["proj_ppr"],
                               "relative_gap": abs(prop["adj"] - prop["line"]) / max(1, prop["line"])})
    def tie(c):
        r = c["row"]
        return r["game_id"], r["player_id"], r["category"], r["line_from"], r["line"]
    candidates.sort(key=lambda c: (-c["relative_gap"], tie(c)))
    best, seen = [], set()
    for c in candidates:
        key = c["row"]["player_id"], c["row"]["lean"]
        if key not in seen: best.append(c); seen.add(key)
    selected = {}
    for strategy in STRATEGIES:
        order = sorted(best, key=lambda c: ((-c["direct_player_ppr"],) if strategy == STRATEGIES[1] else ()) + (-c["relative_gap"], tie(c)))
        selected[strategy] = []
        for side in ("over", "under"):
            selected[strategy].extend({"row_sha256": digest(c["row"]), "side": side, "rank": i + 1}
                for i, c in enumerate([c for c in order if c["row"]["lean"] == side][:rules["maximum_per_side"]]))
    return {"candidates": candidates, "exclusions": excluded, "memberships": selected}


def read_completed(root, name, *, now=None, _checked=None):
    """Revalidate the exact pinned original dependencies at their saved clocks."""
    import partial_week
    root = Path(root).resolve()
    completed = partial_week._saved(root, name, COMPLETE_LANE)
    saved = partial_week._saved(root, completed["observation_receipt"], LANE)
    if saved.get("source_sha") in RETAINED_SOURCES:
        result = _retained_call(root, "completed", {"name": name}, utc(now or datetime.now(timezone.utc)),
                                source_sha=saved["source_sha"])
        if not isinstance(result, list) or len(result) != 2:
            raise IntegrityError("Unsupported retained ranked completion result")
        return tuple(result)
    return _validate_completed(root, completed, now=now, _checked=_checked)


def _validate_completed(root, completed, *, now=None, _checked=None):
    """Full shared checks, including provisional producer payloads not issued yet."""
    import partial_week
    from phase2_capture import _strategy_qualification
    root = Path(root).resolve(); now = utc(now or datetime.now(timezone.utc))
    fields = {"schema_version", "season", "week", "observation_receipt", "observation_sha256", "completed_at"}
    if set(completed) != fields or completed["schema_version"] != COMPLETION:
        raise IntegrityError("Unsupported ranked completion")
    for path in (root / "data" / FAILURE_LANE).rglob("*.json.gz"):
        failure = read(path)
        if failure.get("completion_sha256") == digest(completed):
            if (set(failure) != {"schema_version", "season", "week", "completion_sha256", "failed_at"}
                    or failure["schema_version"] != "ranked-selection-failure-v1"
                    or (failure["season"], failure["week"]) != (completed["season"], completed["week"])
                    or utc(failure["failed_at"]) > now):
                raise IntegrityError("Invalid ranked failure marker")
            raise UnqualifiedStrategy("Ranked completion crossed final persistence boundary")
    saved = partial_week._saved(root, completed["observation_receipt"], LANE)
    fields = {"schema_version", "season", "week", "policy_sha256", "source_sha", "source_files", "created_at", "qualification", "ranked"}
    if set(saved) != fields or saved["schema_version"] != VERSION or digest(saved) != completed["observation_sha256"] or (saved["season"], saved["week"]) != (completed["season"], completed["week"]):
        raise IntegrityError("Unsupported ranked observation")
    rules = policy(root)
    if saved["policy_sha256"] != digest(rules) or saved["source_files"] != _source(root, saved["source_sha"]):
        raise IntegrityError("Ranked policy/source identity mismatch")
    created, done = utc(saved["created_at"]), utc(completed["completed_at"])
    if not utc(rules["registered_at"]) <= created <= done <= now:
        raise IntegrityError("Ranked recording clocks invalid")
    board, native = _strategy_qualification(root, saved["qualification"], created, _checked=_checked)
    if (board["season"], board["week"]) != (saved["season"], saved["week"]) or utc(native["forecast_generated_at"]) < utc(rules["registered_at"]) or not 0 <= (created - utc(native["captured_at"])).total_seconds() <= rules["maximum_observation_age_seconds"]:
        raise IntegrityError("Ranked observation is stale, pre-registration or wrong period")
    expected = rank(board, native, rules, created)
    if saved["ranked"] != expected:
        raise IntegrityError("Ranked membership does not reproduce exact saved board")
    selected = {m["row_sha256"] for rows in expected["memberships"].values() for m in rows}
    if any(done >= utc(c["row"]["kickoff"]) for c in expected["candidates"] if digest(c["row"]) in selected):
        raise IntegrityError("Ranked evidence completed after selected kickoff")
    return saved, completed


def record(root, qualification, source_sha, *, clock=None, _checked=None):
    """Create once per native+policy. Orphans never supply saved decisions."""
    from phase2_capture import _strategy_qualification
    clock = clock or (lambda: datetime.now(timezone.utc)); root = Path(root).resolve()
    # The installed registration is mandatory. A data-only legacy root may
    # omit its copy only for a fully requalified pre-registration forecast;
    # that observation is ineligible, never a strategy-enabled fallback.
    rules = policy()
    runtime_policy = root / POLICY_PATH
    if runtime_policy.exists() or not qualification.get("native_receipt"):
        rules = policy(root)
    created = utc(clock())
    board, native = _strategy_qualification(root, qualification, created, _checked=_checked)
    if utc(native["forecast_generated_at"]) < utc(rules["registered_at"]):
        return None  # Existing history is never assigned a retrospective strategy.
    rules = policy(root)  # Active observations must retain the exact registry.
    existing = []
    for path in sorted((root / "data" / COMPLETE_LANE).rglob("*.json.gz")):
        try:
            saved, done = read_completed(root, path.relative_to(root).as_posix(), now=created, _checked=_checked)
        except UnqualifiedStrategy:
            continue
        if saved["qualification"]["native_payload_sha256"] == digest(native) and saved["policy_sha256"] == digest(rules): existing.append((saved, done, path))
    if len(existing) > 1: raise IntegrityError("Conflicting completed ranked recordings")
    if existing: return existing[0][2]
    ranked = rank(board, native, rules, created)
    saved = {"schema_version": VERSION, "season": board["season"], "week": board["week"], "policy_sha256": digest(rules),
             "source_sha": source_sha, "source_files": _source(root, source_sha), "created_at": stamp(created),
             "qualification": qualification, "ranked": ranked}
    path = write(root, LANE, saved)
    # No canonical completion exists while expensive validation runs. A hard
    # interruption here preserves only an ineligible orphan observation.
    prepared_at = utc(clock())
    provisional = {"schema_version": COMPLETION, "season": board["season"], "week": board["week"],
                   "observation_receipt": path.relative_to(root).as_posix(), "observation_sha256": digest(saved),
                   "completed_at": stamp(prepared_at)}
    _validate_completed(root, provisional, now=prepared_at, _checked=_checked)
    done = utc(clock())
    selected = {m["row_sha256"] for rows in ranked["memberships"].values() for m in rows}
    if done < prepared_at or done < created or any(done >= utc(c["row"]["kickoff"]) for c in ranked["candidates"] if digest(c["row"]) in selected):
        raise IntegrityError("Ranked validation completion crossed kickoff or reversed clocks")
    completion = dict(provisional, completed_at=stamp(done))
    try:
        completed_path = write(root, COMPLETE_LANE, completion)
        # Exact deterministic encoded bytes bound the read and need no second
        # expensive qualification. Saved consumers still perform all checks.
        import gzip
        encoded = gzip.compress(canonical({"payload_sha256": digest(completion), "payload": completion}), mtime=0)
        expected_path = root / "data" / COMPLETE_LANE / str(board["season"]) / f"w{board['week']:02d}" / (digest(completion) + ".json.gz")
        if completed_path != expected_path or completed_path.is_symlink():
            raise IntegrityError("Ranked completion readback path mismatch")
        with completed_path.open("rb") as handle:
            if handle.read(len(encoded) + 1) != encoded:
                raise IntegrityError("Ranked completion bounded readback mismatch")
        final = utc(clock())
        if final < done or any(final >= utc(c["row"]["kickoff"]) for c in ranked["candidates"] if digest(c["row"]) in selected):
            raise IntegrityError("Ranked final persistence crossed kickoff")
    except BaseException:
        write(root, FAILURE_LANE, {"schema_version": "ranked-selection-failure-v1", "season": board["season"], "week": board["week"],
            "completion_sha256": digest(completion), "failed_at": stamp(utc(clock()))})
        raise
    return completed_path


def decisions(roots, timing, at, *, ledger_root=None):
    """First recorded selections and unchanged timely-checkpoint rules.

    Only completed strategy receipts participate. Display sorting and older
    native observations without this registration never acquire membership.
    """
    from scorecard import identity
    from selection_report import _decision
    at = utc(at); snapshots = []; seen_payloads = {}
    for root in roots:
        for path in sorted((Path(root) / "data" / COMPLETE_LANE).rglob("*.json.gz")):
            try:
                saved, done = read_completed(root, path.relative_to(root).as_posix(), now=at)
            except UnqualifiedStrategy:
                continue
            sha = digest(saved)
            if sha in seen_payloads:
                if seen_payloads[sha] != digest(done): raise IntegrityError("Conflicting completions for one ranked observation")
                continue
            seen_payloads[sha] = digest(done)
            native = read(Path(root) / saved["qualification"]["native_receipt"])
            if digest(native) != saved["qualification"]["native_payload_sha256"]:
                raise IntegrityError("Ranked native changed during consumption")
            rows = {identity(row): dict(row, observation_row_sha256=digest(row)) for row in native["rows"]
                    if row["category"] in timing["categories"]}
            snapshots.append({"payload_sha256": digest(native), "captured_at": saved["created_at"], "native_captured_at": native["captured_at"],
                "forecast_generated_at": native["forecast_generated_at"], "season": saved["season"], "week": saved["week"],
                "model": native["model"], "engine_sha256": native["engine_sha256"], "engine_files": native["engine_files"],
                "rows": rows, "saved": saved, "completed": done})
    result = _records(snapshots, timing, at)
    return _freeze(ledger_root, result, snapshots, timing, at) if ledger_root is not None else result


def _records(snapshots, timing, at):
    from scorecard import identity
    from selection_report import _decision
    rules = policy(); policy_sha = digest(rules)
    snapshots = sorted(snapshots, key=lambda s: (utc(s["captured_at"]), digest(s["saved"])))
    # Equal-clock contradictory observations remain explicit failures.
    instants = {}
    for s in snapshots:
        key = s["season"], s["week"], s["model"], s["engine_sha256"], s["captured_at"]
        signature = digest({"rows": [row for _, row in sorted(s["rows"].items())], "saved": s["saved"]})
        if key in instants and instants[key] != signature: raise IntegrityError("Conflicting same-time ranked observations")
        instants[key] = signature
    observations, groups = defaultdict(list), defaultdict(list)
    for s in snapshots:
        groups[(s["season"], s["week"], s["model"], s["engine_sha256"])].append(s)
        for key, row in s["rows"].items(): observations[key + (s["model"], s["engine_sha256"])].append((s, row))
    result = []
    def member(s, row, strategy):
        return next((m for m in s["saved"]["ranked"]["memberships"][strategy]
                     if m["row_sha256"] == row["observation_row_sha256"]), None)
    for key, history in sorted(observations.items()):
        first, original = history[0]
        template = dict(original, _model=first["model"], _engine=first["engine_sha256"], _engine_files=first["engine_files"])
        for strategy in STRATEGIES:
            chosen, row = next(((s, r) for s, r in history if member(s, r, strategy)), history[0])
            candidates = [("history", None, chosen, row, None)]
            for rule in timing["checkpoints"]:
                boundary = utc(original["kickoff"]) - timedelta(seconds=rule["seconds_before_kickoff"])
                if boundary > at:
                    candidates.append((rule["id"], boundary, None, None, "checkpoint_not_yet_reached")); continue
                if not any(utc(s["completed"]["completed_at"]) <= boundary for s, _ in history): continue
                eligible = [s for s in groups[key[:2] + key[5:]] if utc(rules["registered_at"]) < utc(s["captured_at"]) <= boundary and utc(s["completed"]["completed_at"]) <= boundary]
                witness = eligible[-1] if eligible else None
                observed = witness["rows"].get(key[:5]) if witness else None
                reason = None
                if not witness: reason = "missing_registered_snapshot"
                elif (boundary - utc(witness["captured_at"])).total_seconds() > timing["maximum_snapshot_age_seconds"]:
                    observed = None; reason = "stale_snapshot"
                candidates.append((rule["id"], boundary, witness, observed, reason))
            for checkpoint, boundary, s, r, reason in candidates:
                m = member(s, r, strategy) if s and r else None
                excluded = next((e["reason"] for e in s["saved"]["ranked"]["exclusions"] if e["opportunity"] == list(identity(r))), None) if s and r else None
                conflict = bool(r and utc(r["kickoff"]) != utc(original["kickoff"]))
                unsupported = bool(reason) or excluded not in (None, "observed_no_side", "production_eligibility_not_met")
                action = "NOT_DUE" if reason == "checkpoint_not_yet_reached" else "EXCLUDED" if conflict or unsupported else "SELECT" if m else "NO_ACTION"
                record = _decision(template, s, r, strategy, checkpoint, timing, boundary=boundary, action=action,
                    reason="saved_schedule_conflict" if conflict else reason or excluded or ("prospectively_recorded_ranked_membership" if m else "not_selected_by_registered_strategy"), schedule_conflict=conflict)
                saved = s["saved"] if s else None
                record.update(schema_version="selection-decision-v2", provenance_class="completed_prospective_ranked_selection",
                    strategy_version="ranked-selection-policy-v1", strategy_policy_sha256=policy_sha,
                    strategy_receipt_sha256=digest(saved) if saved else None, strategy_rank=m["rank"] if m else None,
                    original_selection_created_at=s["captured_at"] if s and r else None,
                    collected_at=s["native_captured_at"] if s else None,
                    selection_clock_basis="LOCAL_COMPLETED_RANKED_SELECTION" if s and r else "UNKNOWN",
                    policy_application_mode="PROSPECTIVE_FIRST_RECORDED_STRATEGY" if checkpoint == "history" else "OFFLINE_CHECKPOINT_OF_PROSPECTIVE_STRATEGY")
                record["decision_key"] = digest({k: record[k] for k in ("season", "week", "game_id", "player_id", "category", "model_version", "engine_sha256", "policy_sha256", "strategy_policy_sha256", "cohort", "checkpoint", "kickoff", "provenance_class")})
                record.pop("decision_sha256"); record["decision_sha256"] = digest(record); result.append(record)
    return result


def _freeze(root, records, snapshots, timing, at):
    """A separate typed ledger pins the exact originally derived witness set.

    Replaying a saved checkpoint never discovers a replacement from a later
    directory inventory. All pinned witnesses were freshly qualified above.
    """
    root = Path(root); witnesses = {digest(s["completed"]): s for s in snapshots}
    helper = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in ("tools/selection_strategies.py", "tools/selection_report.py", POLICY_PATH)}
    previous = {}
    for path in sorted((root / "data/ranked_selection_decisions").rglob("*.json.gz")):
        import partial_week
        payload = partial_week._saved(root, path.relative_to(root).as_posix(), "ranked_selection_decisions")
        fields = {"schema_version", "season", "week", "derived_at", "policy_sha256", "timing_policy_sha256", "helper_files", "witnesses", "rows"}
        if (set(payload) != fields or payload["schema_version"] != "ranked-selection-decision-ledger-v1"
                or payload["policy_sha256"] != digest(policy()) or payload["timing_policy_sha256"] != digest(timing)
                or utc(payload["derived_at"]) > at
                or not isinstance(payload["rows"], list) or not isinstance(payload["witnesses"], list)
                or payload["witnesses"] != sorted(set(payload["witnesses"]))):
            raise IntegrityError("Unsupported ranked decision ledger")
        if any(ref not in witnesses for ref in payload["witnesses"]):
            raise IntegrityError("Pinned ranked decision witness unavailable")
        pinned = [witnesses[ref] for ref in payload["witnesses"]]
        if any(utc(s["completed"]["completed_at"]) > utc(payload["derived_at"]) for s in pinned):
            raise IntegrityError("Ranked ledger borrows a later completion")
        if payload["helper_files"] == helper:
            reproduced = _records(pinned, timing, utc(payload["derived_at"]))
        else:
            selected_source = None
            for source_sha in RETAINED_SOURCES:
                with _retained_source(source_sha) as retained:
                    old_helper = {name: hashlib.sha256((retained / name).read_bytes()).hexdigest() for name in helper}
                if payload["helper_files"] == old_helper:
                    selected_source = source_sha
                    break
            if selected_source is None:
                raise IntegrityError("Unsupported ranked ledger helper identity")
            # Pinned witnesses were freshly qualified above. Reproduce their
            # old decision algorithm and its actual _decision dependency.
            encoded = [{**s, "rows": list(s["rows"].values())} for s in pinned]
            reproduced = _retained_call(root, "records", {"snapshots": encoded, "timing": timing}, utc(payload["derived_at"]),
                                        source_sha=selected_source)
        expected = {r["decision_key"]: r for r in reproduced}
        for row in payload["rows"]:
            if ((row["season"], row["week"]) != (payload["season"], payload["week"])
                    or row["checkpoint"] == "history" and row["action"] != "SELECT" or row["action"] == "NOT_DUE"
                    or expected.get(row["decision_key"]) != row):
                raise IntegrityError("Frozen ranked checkpoint does not reproduce pinned witnesses")
            old = previous.setdefault(row["decision_key"], row)
            if old != row: raise IntegrityError("Conflicting frozen ranked checkpoints")
    stable = []
    keys = set()
    for row in records:
        key = row["decision_key"]; keys.add(key)
        # Keep the actual saved decision, including its specific witness and
        # clocks. Later matching alternatives cannot replace it.
        stable.append(previous.get(key, row))
    stable.extend(row for key, row in sorted(previous.items()) if key not in keys)
    weeks = defaultdict(list)
    for row in stable:
        if (row["checkpoint"] != "history" or row["action"] == "SELECT") and row["action"] != "NOT_DUE" and row["decision_key"] not in previous:
            weeks[(row["season"], row["week"])].append(row)
    for (season, week), rows in weeks.items():
        write(root, "ranked_selection_decisions", {"schema_version": "ranked-selection-decision-ledger-v1", "season": season, "week": week,
            "derived_at": stamp(at), "policy_sha256": digest(policy()), "timing_policy_sha256": digest(timing), "helper_files": helper,
            "witnesses": sorted(witnesses), "rows": rows})
    return stable
