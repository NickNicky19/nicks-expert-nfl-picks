"""Fictional end-to-end acceptance tests for the offline selection ledger."""
from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import subprocess
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
import data_integrity_v2 as corrected
from reliability import IntegrityError, digest, immutable_write, stamp, utc, engine_hashes
from evidence import read, write
from selection_report import (build_decisions, grade_decisions, summarize, run_report,
                              matched_checkpoints, archive_decisions, render_html, _inventory,
                              final_outcome_records)
from scorecard import identity, latest_outcomes, snapshot_outcomes

ENGINE = {"fictional_original_engine": "fixture-source-hash"}
KICKOFF = datetime(2026, 10, 25, 17, tzinfo=timezone.utc)
BOUNDARY = KICKOFF - timedelta(hours=24)


def timing_policy():
    policy = json.loads((ROOT / "config/timing-policy.json").read_text())
    policy["registered_at"] = "2026-10-14T02:22:31.717455Z"
    return policy


def row(player="fixture-A", category="rec", *, line=4.5, side="over", top=False,
        kickoff=KICKOFF, week=7):
    adjusted = 5.2 if category == "rec" else 32.0
    return {
        "season": 2026, "week": week, "game_id": "fictional-game-" + str(week),
        "kickoff": stamp(kickoff), "player_id": player, "name": player,
        "team": "AAA", "position": "WR", "category": category,
        "raw_projection": 4.8 if category == "rec" else 28.0,
        "adjusted_projection": adjusted, "line": line, "line_from": "sleeper",
        "lean": side, "top_over": top and side == "over",
        "top_under": top and side == "under", "matchup_factor": None,
        "injury_at_capture": None, "settlement_status": "NOT_VERIFIED",
        "source_timestamps_verified": False,
    }


def receipt(at, rows):
    return {
        "schema_version": "baseline-capture-v1", "mode": "live",
        "season": rows[0]["season"], "week": rows[0]["week"],
        "evidence_label": "LOCAL_PRE_GAME_CAPTURE_PUBLICATION_NOT_VERIFIED",
        "captured_at": stamp(at),
        "forecast_generated_at": stamp(at - timedelta(minutes=1)),
        "input_sha256": digest({"fictional_rows": rows, "at": stamp(at)}),
        "engine_sha256": digest(ENGINE), "engine_files": copy.deepcopy(ENGINE),
        "code_commit": None, "model": "original_sleeper_matchup_baseline",
        "rows": copy.deepcopy(rows), "excluded_started_or_late_games": [],
    }


def find(records, *, player="fixture-A", category="rec", checkpoint="24h",
         cohort="all_qualifying_leans"):
    matches = [r for r in records if r["player_id"] == player
               and r["category"] == category and r["checkpoint"] == checkpoint
               and r["cohort"] == cohort]
    if len(matches) != 1:
        raise AssertionError(f"Expected one {player}/{category}/{checkpoint}/{cohort}; got {len(matches)}")
    return matches[0]


def core_snapshots(*, include_after=True):
    early = receipt(BOUNDARY - timedelta(days=1), [
        row(),
        row("fixture-B", "rush_rec_yd", line=29.5, top=True),
    ])
    latest_before = receipt(BOUNDARY - timedelta(minutes=15), [
        row(line=5.5, side="under", top=True),
    ])
    snapshots = [early, latest_before]
    if include_after:
        # The later row must not fill B's absence at the 24h boundary.
        snapshots.append(receipt(BOUNDARY + timedelta(microseconds=1), [
            row(line=5.5, side="under", top=True),
            row("fixture-B", "rush_rec_yd", line=29.5, top=True),
        ]))
    return snapshots


class ClosedRankedReaderCatalogTests(unittest.TestCase):
    def test_unknown_reader_rejects_before_git_or_source_execution(self):
        import selection_strategies as strategies
        with patch.object(corrected, "_git") as git:
            with self.assertRaisesRegex(IntegrityError, "Unsupported retained ranked source"):
                with strategies._retained_source("0" * 40):
                    self.fail("Unknown source yielded executable code")
            git.assert_not_called()

    def test_accepted_previous_reader_uses_its_actual_complete_source(self):
        import selection_strategies as strategies
        previous = "04519b54dfb76dcca7916fe6bf75d7e1711793b6"
        self.assertEqual(strategies.RETAINED_SOURCES[previous], "10a5cc1539c51c8089fb7ff077447b6d17c4e13e")
        with strategies._retained_source(previous) as source:
            for name in strategies.SOURCE_PATHS:
                self.assertEqual((source / name).read_bytes(), corrected._git(ROOT, "show", previous + ":" + name))
            self.assertNotEqual((source / "tools/phase2_capture.py").read_bytes(),
                                (ROOT / "tools/phase2_capture.py").read_bytes())

    def test_retained_reader_never_qualifies_a_new_old_labelled_recording(self):
        import selection_strategies as strategies
        for source in strategies.RETAINED_SOURCES:
            with self.subTest(source=source), self.assertRaisesRegex(IntegrityError, "source/helper bytes differ"):
                strategies._source(ROOT, source)


class SelectionTimingAcceptance(unittest.TestCase):
    def build(self, snapshots, *, at=None, policy=None):
        return build_decisions(snapshots, policy or timing_policy(),
                               at or BOUNDARY + timedelta(hours=1), ENGINE)

    def test_checkpoint_uses_latest_snapshot_not_latest_row(self):
        records, _ = self.build(core_snapshots())
        a = find(records)
        b = find(records, player="fixture-B", category="rush_rec_yd")
        self.assertEqual((a["action"], a["line"], a["side"], a["top_at_decision"]),
                         ("SELECT", 5.5, "under", True))
        self.assertEqual(a["observation_age_seconds"], 900)
        self.assertEqual(utc(a["recorded_selection_at"]), BOUNDARY - timedelta(minutes=15))
        self.assertEqual((a["selection_weekday"], a["kickoff_weekday"]), ("Saturday", "Sunday"))
        self.assertEqual(b["action"], "NO_ACTION")
        self.assertIn("missing", b["reason"].lower())
        self.assertIsNone(b.get("line"))
        self.assertIsNone(b.get("side"))

    def test_future_checkpoint_is_not_due_even_with_recent_observation(self):
        records, _ = self.build(core_snapshots(include_after=False),
                                at=BOUNDARY - timedelta(minutes=10))
        for checkpoint in ("24h", "6h", "90m"):
            for cohort in ("top_picks", "all_qualifying_leans"):
                candidate = find(records, checkpoint=checkpoint, cohort=cohort)
                self.assertEqual(candidate["action"], "NOT_DUE")
                self.assertIsNone(candidate.get("line"))
                self.assertIsNone(candidate.get("side"))

    def test_first_selected_is_per_cohort_and_partition_remains_disjoint(self):
        records, _ = self.build(core_snapshots())
        first_lean = find(records, checkpoint="history")
        first_top = find(records, checkpoint="history", cohort="top_picks")
        self.assertEqual((first_lean["line"], first_lean["side"], first_lean["top_at_decision"]),
                         (4.5, "over", False))
        self.assertEqual((first_top["line"], first_top["side"], first_top["top_at_decision"]),
                         (5.5, "under", True))
        self.assertLess(utc(first_lean["recorded_selection_at"]),
                        utc(first_top["recorded_selection_at"]))
        leans = [r for r in records if r["checkpoint"] == "history"
                 and r["cohort"] == "all_qualifying_leans" and r["action"] == "SELECT"]
        tops = [r for r in records if r["checkpoint"] == "history"
                and r["cohort"] == "top_picks" and r["action"] == "SELECT"]
        self.assertEqual(len(leans), 2)
        self.assertEqual(len(tops), 2)
        self.assertEqual(sum(bool(r["top_at_decision"]) for r in leans), 1)
        self.assertEqual(sum(not r["top_at_decision"] for r in leans), 1)
        # First-Top is not interchangeable with the all-lean Top partition.
        self.assertNotEqual(len(tops), sum(bool(r["top_at_decision"]) for r in leans))

    def test_repeated_identical_receipt_does_not_duplicate_decisions(self):
        snapshots = core_snapshots()
        once, _ = self.build(snapshots)
        repeated, _ = self.build([*snapshots, copy.deepcopy(snapshots[0])])
        def decisions(records):
            return sorted((r["player_id"], r["category"], r["checkpoint"], r["cohort"],
                           r["action"], r.get("line"), r.get("side"),
                           r.get("recorded_selection_at")) for r in records)
        self.assertEqual(decisions(once), decisions(repeated))

    def test_exact_age_boundary_and_postboundary_observation(self):
        snapshots = [receipt(BOUNDARY - timedelta(hours=1), [row()]),
                     receipt(BOUNDARY + timedelta(microseconds=1),
                             [row(line=5.5, side="under", top=True)])]
        records, _ = self.build(snapshots)
        selected = find(records)
        self.assertEqual((selected["action"], selected["line"], selected["side"]),
                         ("SELECT", 4.5, "over"))
        self.assertEqual(selected["observation_age_seconds"], 3600)
        stale, _ = self.build([receipt(BOUNDARY - timedelta(hours=1, microseconds=1), [row()])])
        candidate = find(stale)
        self.assertEqual(candidate["action"], "NO_ACTION")
        self.assertIn("stale", candidate["reason"].lower())

    def test_dst_offsets_are_applied_separately_to_both_original_clocks(self):
        # Selection: Sunday 00:15 CDT. Kickoff: Sunday 23:30 CST.
        # Fixed -06 would put selection on Saturday; fixed -05 would put
        # kickoff on Monday. UTC dates alone also put kickoff on Monday.
        kickoff = datetime(2026, 11, 2, 5, 30, tzinfo=timezone.utc)
        boundary = kickoff - timedelta(hours=24)
        observed = boundary - timedelta(minutes=15)
        records, _ = self.build([receipt(observed, [row(kickoff=kickoff, week=8)])], at=boundary)
        candidate = find(records)
        self.assertEqual(candidate["action"], "SELECT")
        self.assertEqual((candidate["selection_weekday"], candidate["kickoff_weekday"]),
                         ("Sunday", "Sunday"))
        self.assertEqual(candidate["observation_age_seconds"], 900)
        self.assertEqual(utc(candidate["recorded_selection_at"]), observed)


def saved_forecast(root, payload):
    capture_id = digest({"data": payload["input_sha256"], "engine": payload["engine_sha256"], "mode": payload["mode"]})
    path = root / "data/forward/2026/w07" / (capture_id + ".json.gz")
    immutable_write(path, payload)
    return path


def saved_sources(root, entries, *, kickoff=KICKOFF, final=True, week=7):
    directory = root / "output/data"
    directory.mkdir(parents=True, exist_ok=True)
    (root / "data/cache").mkdir(parents=True, exist_ok=True)
    board = {"season": 2026, "week": week, "generated_at": stamp(kickoff + timedelta(hours=5)),
             "games": [{"id": "fictional-game-" + str(week), "kickoff": stamp(kickoff),
                        "home": "AAA", "away": "BBB", "state": "post" if final else "pre",
                        "detail": "Final" if final else "Scheduled"}]}
    (directory / "week.json").write_text(json.dumps(board))
    (root / f"data/cache/stats_2026_{week:02d}.json").write_text(json.dumps(entries))
    return board


class SelectionReportIntegration(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root, output = Path(directory.name) / "input", Path(directory.name) / "report"
        root.mkdir()
        return root, output

    def report(self, root, output, at=None):
        return run_report([root], output, now=at or KICKOFF + timedelta(days=1),
                          expected_hashes=ENGINE, policy=timing_policy())

    def test_machine_only_report_preserves_all_semantics_and_persistent_evidence(self):
        root, output = self.fixture()
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), [row(top=True), row("fixture-B", side="under")]))
        saved_sources(root, {"fixture-A": {"team": "AAA", "stats": {"gp": 1, "rec": 0}},
                             "fixture-B": {"team": "AAA", "stats": {"gp": 1, "rec": 8}}})
        full, directory = self.report(root, output)
        lean = output.parent / "machine-only"
        with patch("selection_report._export_report", side_effect=AssertionError("Unexpected private exports")):
            actual, returned = run_report([root], lean, now=KICKOFF + timedelta(days=1),
                expected_hashes=ENGINE, policy=timing_policy(), diagnostic_exports=False)
        self.assertEqual(actual, full)
        self.assertEqual(returned.name, directory.name)
        self.assertFalse((lean / "reports").exists())
        for lane in ("selection_decisions", "outcomes_derived", "selection_report_runs"):
            expected = {p.relative_to(output / "data" / lane): read(p) for p in (output / "data" / lane).rglob("*.json.gz")}
            retained = {p.relative_to(lean / "data" / lane): read(p) for p in (lean / "data" / lane).rglob("*.json.gz")}
            self.assertEqual(retained, expected)
        self.assertTrue((directory / "manifest.json").is_file())
        self.assertTrue((directory / "rows.csv").is_file())
        self.assertEqual(len(list((directory / "groups").glob("*.html"))), len(full["summary"]["tables"]))

    def test_machine_only_report_still_rejects_final_boundary_input_mutation(self):
        import selection_report as module
        root, output = self.fixture()
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), [row(top=True)]))
        native = next((root / "data/forward").rglob("*.json.gz"))
        actual_write = module.write
        def race(destination, lane, payload):
            result = actual_write(destination, lane, payload)
            if lane == "selection_report_runs":
                raw = native.read_bytes(); native.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            return result
        with patch.object(module, "write", side_effect=race):
            with self.assertRaisesRegex(IntegrityError, "Original input changed during report"):
                run_report([root], output, now=KICKOFF + timedelta(days=1),
                    expected_hashes=ENGINE, policy=timing_policy(), diagnostic_exports=False)

    def test_diagnostic_export_selection_requires_an_actual_boolean(self):
        root, output = self.fixture()
        for value in (None, 0, 1, "false"):
            with self.subTest(value=value), self.assertRaisesRegex(IntegrityError, "explicit boolean"):
                run_report([root], output, diagnostic_exports=value)

    def test_actual_pipeline_all_ten_categories_and_immutable_rows_reconcile(self):
        root, output = self.fixture()
        policy = timing_policy()
        rows, stats = [], {}
        for category in policy["categories"]:
            pid = "fictional-" + category
            rows.append(row(pid, category, line=29.5 if category == "rush_rec_yd" else .5,
                            top=category in ("rec", "rush_rec_yd")))
            stats[pid] = {"team": "AAA", "stats": {"gp": 1, category: 1}}
            if category == "rush_rec_yd":
                stats[pid]["stats"].update(rush_yd=10, rec_yd=20, rush_rec_yd=999)
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), rows))
        saved_sources(root, stats)
        original, _ = _inventory([root])
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")):
            report, directory = self.report(root, output)
        leans = [r for r in report["rows"] if r["checkpoint"] == "history" and r["cohort"] == "all_qualifying_leans"]
        self.assertEqual({r["category"] for r in leans}, set(policy["categories"]))
        self.assertEqual(len(leans), 10)
        self.assertEqual(Counter(r["result"] for r in leans), {"win": 10})
        self.assertEqual(next(r["actual"] for r in leans if r["category"] == "rush_rec_yd"), 30)
        self.assertTrue(report["summary"]["disjoint_selected_partitions_reconciled"])
        lookup = {r["decision_sha256"]: r for r in report["rows"]}
        for group in report["summary"]["tables"]:
            members = [lookup[key] for key in group["row_ids"]]
            self.assertEqual(group["rows"], len(members))
            self.assertEqual(group["win"], sum(r["result"] == "win" for r in members))
            self.assertEqual(group["decided"], group["win"] + group["loss"])
            detail = directory / "groups" / (group["summary_id"] + ".html")
            self.assertEqual(detail.read_text().count("<tr id="), len(members))
        for member in report["rows"]:
            self.assertTrue(set(member["outcome_observations"]) <= set(report["outcome_observation_index"]))
        self.assertTrue(all((directory / name).exists() for name in ("index.html", "rows.json", "rows.csv",
                                                                    "summary.json", "manifest.json")))
        self.assertEqual(_inventory([root])[0], original)
        self.assertFalse((root / "data/outcomes").exists())
        self.assertEqual(report["coverage"]["independently_qualified_completed_weeks"], [])
        # Retry at a genuinely later operational clock adds no new substantive
        # decision/outcome or report, although its run receipt is retained.
        derived_before = set((output / "data/outcomes_derived").rglob("*.json.gz"))
        ledger_before = set((output / "data/selection_decisions").rglob("*.json.gz"))
        repeated, repeated_directory = self.report(root, output, KICKOFF + timedelta(days=1, minutes=1))
        self.assertEqual(repeated_directory, directory)
        self.assertEqual(repeated["rows"], report["rows"])
        self.assertEqual(set((output / "data/outcomes_derived").rglob("*.json.gz")), derived_before)
        self.assertEqual(set((output / "data/selection_decisions").rglob("*.json.gz")), ledger_before)

    def test_actual_pipeline_participation_pushes_pending_and_status_denominators(self):
        root, output = self.fixture()
        names = ("win", "loss", "push", "dnp", "missing", "fantasy_only", "played_zero", "contradiction")
        rows = [row(name, line=4 if name == "push" else .5 if name == "played_zero" else 4.5,
                    side="under" if name == "played_zero" else "over", top=True) for name in names]
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), rows))
        entries = {"win": {"team": "AAA", "stats": {"gp": 1, "rec": 6}},
                   "loss": {"team": "AAA", "stats": {"gp": 1, "rec": 2}},
                   "push": {"team": "AAA", "stats": {"gp": 1, "rec": 4}},
                   "dnp": {"participation_status": "dnp", "participation_source": "fictional_attributed_source"},
                   "fantasy_only": {"team": "AAA", "stats": {"pts_ppr": 0}},
                   "played_zero": {"team": "AAA", "stats": {"gp": 1}},
                   "contradiction": {"team": "AAA", "stats": {"gp": 1, "rec": 6},
                                     "participation_status": "dnp", "participation_source": "fictional"}}
        saved_sources(root, entries)
        report, _ = self.report(root, output)
        members = [r for r in report["rows"] if r["checkpoint"] == "history" and r["cohort"] == "all_qualifying_leans"]
        self.assertEqual(Counter(r["result"] for r in members), {"win": 2, "loss": 1, "push": 1, "dnp": 1, "unresolved": 3})
        group = next(g for g in report["summary"]["tables"] if g["period"] == "cumulative"
                     and g["dimension"] == "overall" and g["view"] == "all_qualifying_leans"
                     and g["checkpoint"] == "history")
        self.assertEqual(group["hit_rate"], 2 / 3)
        self.assertEqual((group["decided_unique_games"], group["decided_unique_weeks"]), (1, 1))
        pending_root, pending_output = self.fixture()
        saved_forecast(pending_root, receipt(BOUNDARY - timedelta(minutes=15), [row()]))
        saved_sources(pending_root, entries, final=False)
        pending, _ = self.report(pending_root, pending_output)
        self.assertEqual(find(pending["rows"], checkpoint="history")["result"], "pending")

    def test_no_lean_and_unknown_offer_are_not_source_outage_or_zero(self):
        root, output = self.fixture()
        no_lean, reference = row(side=None), row("reference", side=None)
        reference.update(line_from="ours", line=None)
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), [no_lean, reference]))
        saved_sources(root, {})
        for number, status in enumerate(("available", "unavailable", "unknown")):
            write(root, "offers", {"schema_version": "sleeper-offer-capture-v1", "season": 2026, "week": 7,
                                    "collected_at": stamp(BOUNDARY - timedelta(minutes=number)),
                                    "source_status": status, "coverage": {"no_offer": 0}, "rows": []})
        report, _ = self.report(root, output)
        known = find(report["rows"], checkpoint="history")
        self.assertEqual((known["action"], known["result"], known["reason"]),
                         ("NO_ACTION", "no_action", "observed_no_lean"))
        reference_row = find(report["rows"], player="reference", checkpoint="history")
        self.assertIn("unknown", reference_row["reason"])
        self.assertEqual({s["source_status"] for s in report["coverage"]["source_observations"]},
                         {"available", "unavailable", "unknown"})
        self.assertTrue(all(not s["bound_to_decisions"] for s in report["coverage"]["source_observations"]))

    def test_unrelated_saved_outcome_integrity_failure_is_not_suppressed(self):
        root, output = self.fixture()
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), [row()]))
        saved_sources(root, {})
        directory = root / "data/outcomes/2026/w07"
        directory.mkdir(parents=True)
        (directory / ("0" * 64 + ".json.gz")).write_bytes(b"not gzip")
        with self.assertRaises((ValueError, OSError)):
            self.report(root, output)

    def test_observable_cache_opponent_conflict_remains_unresolved(self):
        root, output = self.fixture()
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), [row(top=True)]))
        saved_sources(root, {"fixture-A": {"team": "AAA", "opp": "WRONG", "stats": {"gp": 1, "rec": 6}}})
        report, _ = self.report(root, output)
        candidate = find(report["rows"], checkpoint="history")
        self.assertEqual(candidate["result"], "unresolved")
        self.assertIn("identity_mismatch", candidate["outcome_reason"])

    def test_output_cannot_touch_source_or_any_input(self):
        root, _ = self.fixture()
        with self.assertRaisesRegex(ValueError, "outside"):
            self.report(root, root / "report")

    def test_history_no_action_can_gain_first_real_selection_without_checkpoint_rewrite(self):
        root, output = self.fixture()
        first = receipt(BOUNDARY - timedelta(minutes=15), [row(side=None)])
        saved_forecast(root, first)
        saved_sources(root, {}, final=False)
        early, _ = self.report(root, output, BOUNDARY)
        self.assertEqual(find(early["rows"], checkpoint="history")["action"], "NO_ACTION")
        saved_forecast(root, receipt(BOUNDARY + timedelta(hours=1), [row(top=True)]))
        later, _ = self.report(root, output, BOUNDARY + timedelta(hours=2))
        self.assertEqual(find(later["rows"], checkpoint="history")["action"], "SELECT")
        self.assertEqual(find(later["rows"])["action"], "NO_ACTION")
        self.assertEqual(later["coverage"]["frozen_decision_conflicts"], [])

    def test_newly_discovered_earlier_observation_cannot_rewrite_frozen_checkpoint(self):
        root, output = self.fixture()
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), [row()]))
        saved_sources(root, {}, final=False)
        first, directory = self.report(root, output, BOUNDARY + timedelta(minutes=1))
        frozen = find(first["rows"])["decision_sha256"]
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=10), [row(side="under", line=5.5)]))
        revised, _ = self.report(root, output, BOUNDARY + timedelta(minutes=2))
        candidate = find(revised["rows"])
        self.assertEqual((candidate["action"], candidate["frozen_decision_sha256"]), ("EXCLUDED", frozen))
        material = {k: v for k, v in candidate.items() if k not in
                    ("decision_sha256", "result", "outcome_reason", "actual", "outcome_snapshot_sha256",
                     "outcome_observations", "outcome_collected_at", "week_confirmed_complete", "outcome_provenance",
                     "selected_outcome_provenance_sha256", "selected_outcome_row_sha256", "outcome_selection",
                     "outcome_conflict", "outcome_source_mix", "outcome_revision", "outcome_identity_status",
                     "outcome_identity_reasons")}
        self.assertEqual(digest(material), candidate["decision_sha256"])
        self.assertTrue(directory.exists())
        self.assertTrue(revised["coverage"]["frozen_decision_conflicts"])

    def test_actual_cli_uses_real_clock_and_emits_local_report_only(self):
        root, output = self.fixture()
        kickoff = datetime.now(timezone.utc) - timedelta(days=1)
        payload = receipt(kickoff - timedelta(hours=1), [row(kickoff=kickoff, top=True)])
        payload.update(engine_files=corrected.legacy_engine_hashes(ROOT), engine_sha256=digest(corrected.legacy_engine_hashes(ROOT)))
        saved_forecast(root, payload)
        saved_sources(root, {"fixture-A": {"team": "AAA", "stats": {"gp": 1, "rec": 6}}}, kickoff=kickoff)
        completed = subprocess.run([sys.executable, str(ROOT / "tools/selection_report.py"),
                                    "--input-root", str(root), "--output-root", str(output)],
                                   capture_output=True, text=True, check=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "LOCAL_DESCRIPTIVE_ONLY_NOT_DEPLOYED")
        self.assertTrue(Path(result["report"]).is_file())
        rows = json.loads((Path(result["report"]).parent / "rows.json").read_text())
        self.assertEqual(find(rows, checkpoint="history")["result"], "win")
        self.assertFalse((root / "data/outcomes").exists())

    def test_declared_external_input_pin_is_preserved_without_claiming_authentication(self):
        root, output = self.fixture()
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), [row()]))
        saved_sources(root, {})
        _, directory = run_report([root], output, now=KICKOFF + timedelta(days=1), expected_hashes=ENGINE,
                                  policy=timing_policy(), input_pins={str(root.resolve()): "a" * 40})
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual({r["input_git_pin"] for r in manifest["inputs"]}, {"a" * 40})
        self.assertEqual({r["pin_binding"] for r in manifest["inputs"]}, {"EXTERNAL_PIN_REFERENCE_ONLY"})


class SelectionIntegrityAcceptance(unittest.TestCase):
    def build(self, receipts, *, at=None, policy=None):
        return build_decisions(receipts, policy or timing_policy(), at or BOUNDARY + timedelta(hours=1), ENGINE)

    def test_conflicting_same_time_receipts_and_duplicate_rows_quarantined(self):
        first = receipt(BOUNDARY - timedelta(minutes=15), [row()])
        conflict = receipt(BOUNDARY - timedelta(minutes=15), [row(side="under", line=5.5)])
        decisions, _ = self.build([first, conflict])
        self.assertEqual(find(decisions)["action"], "EXCLUDED")
        duplicate = receipt(BOUNDARY - timedelta(minutes=15), [row(), row()])
        decisions, _ = self.build([duplicate])
        self.assertEqual(find(decisions)["action"], "EXCLUDED")

    def test_ambiguous_first_kickoff_never_chooses_digest_order_boundary(self):
        a = receipt(BOUNDARY - timedelta(minutes=15), [row()])
        b = receipt(BOUNDARY - timedelta(minutes=15), [row(kickoff=KICKOFF + timedelta(hours=2))])
        records, _ = self.build([a, b])
        self.assertTrue(all(r["action"] == "EXCLUDED" for r in records))
        self.assertTrue(all(r["checkpoint_at"] is None for r in records))
        self.assertTrue(all(r["kickoff"] is None for r in records))

    def test_registration_future_and_exact_kickoff_controls(self):
        policy = timing_policy()
        policy["registered_at"] = stamp(BOUNDARY)
        records, _ = self.build([receipt(BOUNDARY - timedelta(minutes=1), [row()])], policy=policy)
        self.assertEqual(find(records)["action"], "EXCLUDED")
        exact = receipt(KICKOFF, [row()])
        records, coverage = self.build([exact], at=KICKOFF + timedelta(hours=1))
        self.assertEqual(records, [])
        self.assertEqual(coverage["receipt_exclusions"]["not_pregame_row"], 1)
        future = receipt(BOUNDARY + timedelta(hours=2), [row()])
        records, coverage = self.build([future], at=BOUNDARY)
        self.assertEqual(records, [])
        self.assertEqual(coverage["receipt_exclusions"]["future_or_reversed_clock"], 1)

    def test_original_v1_period_is_read_from_recorded_rows(self):
        original = receipt(BOUNDARY - timedelta(minutes=15), [row()])
        original.pop("season")
        original.pop("week")
        records, _ = self.build([original])
        self.assertEqual((find(records)["season"], find(records)["week"], find(records)["action"]),
                         (2026, 7, "SELECT"))
        original["rows"].append(row("other-period", week=8))
        with self.assertRaisesRegex(ValueError, "Mixed periods"):
            self.build([original])

    def test_saved_schedule_change_does_not_move_original_checkpoint(self):
        initial = receipt(BOUNDARY - timedelta(hours=2), [row()])
        moved = receipt(BOUNDARY - timedelta(minutes=15), [row(kickoff=KICKOFF + timedelta(hours=2))])
        records, coverage = self.build([initial, moved])
        candidate = find(records)
        self.assertEqual(utc(candidate["checkpoint_at"]), BOUNDARY)
        self.assertEqual(candidate["action"], "EXCLUDED")
        self.assertTrue(coverage["schedule_conflicts"])

    def test_line_changes_and_direction_flips_on_common_opportunities(self):
        snapshots = [receipt(BOUNDARY - timedelta(minutes=15), [row()]),
                     receipt(KICKOFF - timedelta(hours=6, minutes=15), [row(line=5.5, side="under", top=True)])]
        records, _ = self.build(snapshots, at=KICKOFF - timedelta(hours=5))
        matches = matched_checkpoints(records)
        contrast = next(m for m in matches if m["left_checkpoint"] == "24h" and m["right_checkpoint"] == "6h"
                        and m["both_selected"])
        self.assertTrue(contrast["line_changed"])
        self.assertTrue(contrast["direction_flipped"])
        self.assertEqual((contrast["left_line"], contrast["right_line"]), (4.5, 5.5))

    def test_outcome_kickoff_mismatch_and_unsupported_void_not_graded(self):
        records, _ = self.build([receipt(BOUNDARY - timedelta(minutes=15), [row()])])
        decision = find(records)
        outcome = {**row(), "status": "resolved", "actual": 5, "kickoff": stamp(KICKOFF + timedelta(hours=1))}
        result = grade_decisions([decision], {(2026, 7, "fictional-game-7", "fixture-A", "rec"): outcome})
        self.assertEqual(result[0]["result"], "unresolved")
        outcome.update(kickoff=stamp(KICKOFF), status="void")
        result = grade_decisions([decision], {(2026, 7, "fictional-game-7", "fixture-A", "rec"): outcome})
        self.assertEqual(result[0]["result"], "unresolved")

    def test_html_escapes_player_content_and_retains_required_links(self):
        root = row(player="<script>fictional</script>")
        records, _ = self.build([receipt(BOUNDARY - timedelta(minutes=15), [root])])
        graded = grade_decisions(records, {})
        rendered = render_html({"rows": graded, "summary": summarize(graded)})
        self.assertNotIn("<script>fictional</script>", rendered)
        self.assertIn("&lt;script&gt;fictional", rendered)
        self.assertIn('href="rows.csv"', rendered)
        self.assertIn('href="#row-', rendered)

    def archive(self):
        original = row(top=True)
        return {"season": 2026, "week": 7, "saved_at": "2026-10-26T12:00:00Z",
                "games": [{"id": original["game_id"], "kickoff": original["kickoff"]}],
                "players": [{"id": original["player_id"], "name": "fictional",
                             "team": original["team"], "game_id": original["game_id"],
                             "props": [{"key": "rec", "proj": 4.8, "adj": 5.2, "line": 4.5,
                                        "lean": "over", "line_from": "sleeper"}]}],
                "picks": {"over": [{"player_id": original["player_id"], "game_id": original["game_id"],
                                    "key": "rec", "line": 4.5, "line_from": "sleeper", "proj": 4.8, "adj": 5.2}],
                          "under": []}}

    def test_archive_clocks_and_engine_identity_remain_unknown(self):
        archive = self.archive()
        later = copy.deepcopy(archive)
        later["saved_at"] = "2026-10-27T12:00:00Z"
        records = archive_decisions([archive, later], timing_policy())
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r["recorded_selection_at"] is None and r["selection_weekday"] is None
                            and r["engine_sha256"] is None for r in records))
        self.assertTrue(all(r["kickoff_weekday"] == "Sunday" for r in records))
        self.assertTrue(all(len(r["archive_receipt_refs"]) == 2 for r in records))

    def test_archive_conflicting_versions_are_excluded_not_extra_outcomes(self):
        archive = self.archive()
        changed = copy.deepcopy(archive)
        changed["players"][0]["props"][0]["line"] = 5.5
        records = archive_decisions([archive, changed], timing_policy())
        lean = next(r for r in records if r["cohort"] == "all_qualifying_leans")
        self.assertEqual(lean["action"], "EXCLUDED")
        self.assertEqual(len([r for r in records if r["cohort"] == "all_qualifying_leans"]), 1)

    def test_archive_duplicate_or_wrong_game_bindings_fail_explicitly(self):
        for alteration in ("player", "prop", "pick", "game"):
            archive = self.archive()
            if alteration == "player":
                archive["players"].append(copy.deepcopy(archive["players"][0]))
            elif alteration == "prop":
                archive["players"][0]["props"].append(copy.deepcopy(archive["players"][0]["props"][0]))
            elif alteration == "pick":
                archive["picks"]["over"].append(copy.deepcopy(archive["picks"]["over"][0]))
            else:
                archive["picks"]["over"][0]["game_id"] = "wrong-game"
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                archive_decisions([archive], timing_policy())


class SelectedOutcomeLabelIntegrationTests(unittest.TestCase):
    def fixture(self):
        return SelectionReportIntegration.fixture(self)

    def snapshot(self, *, actual=6, hours=5, derived=False):
        root, output = self.fixture()
        record = row(top=True)
        saved_sources(root, {record["player_id"]: {"team": "AAA", "opp": "BBB", "stats": {"gp": 1, "rec": actual}}})
        options = {"include_populations": False}
        if derived:
            options.update(output_root=output, derived_context={"input_git_pin": "a" * 40,
                           "scope": "fictional_saved_fixture_only"})
        with patch("requests.sessions.Session.request", side_effect=AssertionError("HTTP forbidden")):
            path, = snapshot_outcomes(root, {identity(record): record}, KICKOFF + timedelta(hours=hours), **options)
        return read(path)

    def grade(self, payloads):
        decisions, _ = build_decisions([receipt(BOUNDARY - timedelta(minutes=15), [row(top=True)])],
                                        timing_policy(), KICKOFF + timedelta(days=1), ENGINE)
        outcomes = latest_outcomes(payloads)
        return find(grade_decisions(decisions, outcomes), checkpoint="history"), next(iter(outcomes.values()))

    def test_fresh_saved_and_mixed_sources_bind_label_to_exact_selected_evidence(self):
        normal = self.snapshot(hours=4)
        cache = self.snapshot(hours=5, derived=True)
        normal_later = self.snapshot(hours=6)
        for payloads, expected, mix in (
            ([normal], "recorded_outcome_receipt", "single_source"),
            ([cache], "saved_cache_descriptive_regrade", "single_source"),
            ([cache, normal], "recorded_outcome_receipt", "mixed_agreeing_sources"),
            ([normal_later, cache], "saved_cache_descriptive_regrade", "mixed_agreeing_sources"),
            ([cache, normal_later], "saved_cache_descriptive_regrade", "mixed_agreeing_sources"),
        ):
            with self.subTest(expected=expected, clocks=[p["collected_at"] for p in payloads]):
                graded, outcome = self.grade(payloads)
                self.assertEqual((graded["result"], graded["actual"]), ("win", 6))
                self.assertEqual(graded["outcome_provenance"], expected)
                self.assertEqual(graded["outcome_source_mix"], mix)
                selected = outcome["selected_outcome_provenance"]
                self.assertEqual(graded["selected_outcome_provenance_sha256"], digest(selected))
                self.assertEqual(graded["selected_outcome_row_sha256"], selected["outcome_row_sha256"])
                self.assertEqual(graded["outcome_snapshot_sha256"], selected["outcome_snapshot_sha256"])

    def test_conflicts_have_no_selected_source_and_remain_unresolved_in_either_order(self):
        cache = self.snapshot(derived=True)
        conflict = self.snapshot(actual=2, hours=6)
        for snapshots in ([cache, conflict], [conflict, cache]):
            graded, outcome = self.grade(snapshots)
            self.assertEqual((graded["result"], graded["actual"]), ("unresolved", None))
            self.assertEqual(graded["outcome_provenance"], "conflicting_outcome_evidence")
            self.assertEqual(graded["outcome_source_mix"], "conflicting_sources")
            self.assertIsNone(graded["selected_outcome_provenance_sha256"])
            self.assertIsNone(graded["selected_outcome_row_sha256"])
            self.assertIsNone(outcome["selected_outcome_provenance"])

    def test_superseded_and_incomplete_observations_cannot_supply_selected_label(self):
        old, correction = self.snapshot(actual=3, hours=4), self.snapshot(actual=6, hours=6)
        graded, outcome = self.grade([correction, old])
        self.assertEqual((graded["result"], graded["actual"]), ("win", 6))
        self.assertEqual(graded["outcome_provenance"], "recorded_outcome_receipt")
        self.assertTrue(graded["outcome_revision"])
        self.assertNotEqual(outcome["selected_outcome_provenance"], outcome["outcome_observations"][0])
        self.assertEqual(len(outcome["outcome_active_observations"]), 1)

    def test_unbound_selected_reference_or_unknown_source_does_not_invent_provenance(self):
        cache = self.snapshot(derived=True)
        _, base = self.grade([cache])
        decisions, _ = build_decisions([receipt(BOUNDARY - timedelta(minutes=15), [row(top=True)])],
                                        timing_policy(), KICKOFF + timedelta(days=1), ENGINE)
        for alteration in ("missing", "digest", "snapshot", "row", "observation"):
            outcome = copy.deepcopy(base)
            if alteration == "missing": outcome.pop("selected_outcome_provenance")
            elif alteration == "digest": outcome["selected_outcome_provenance_sha256"] = "0" * 64
            elif alteration == "snapshot": outcome["outcome_snapshot_sha256"] = "0" * 64
            elif alteration == "row": outcome["selected_outcome_row_sha256"] = "0" * 64
            else: outcome["outcome_observations"] = []
            with self.subTest(alteration=alteration):
                graded = find(grade_decisions(decisions, {identity(row()): outcome}), checkpoint="history")
                self.assertEqual(graded["outcome_provenance"], "unknown_unverified")
                self.assertEqual((graded["result"], graded["actual"]), ("win", 6))
        unknown = self.snapshot()
        unknown["source"] = "unsupported_fictional_source"
        graded, _ = self.grade([unknown])
        self.assertEqual(graded["outcome_provenance"], "unknown_unverified")

    def test_full_persisted_report_v2_labels_and_minimal_outcome_index_preserve_old_artifact(self):
        root, output = self.fixture()
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), [row(top=True)]))
        saved_sources(root, {"fixture-A": {"team": "AAA", "opp": "BBB", "stats": {"gp": 1, "rec": 6}}})
        old = output / "reports" / ("a" * 64) / "index.html"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"fictional original v1 report bytes preserved")
        before = old.read_bytes()
        with patch("requests.sessions.Session.request", side_effect=AssertionError("HTTP forbidden")):
            report, directory = run_report([root], output, now=KICKOFF + timedelta(days=1),
                                          expected_hashes=ENGINE, policy=timing_policy())
        persisted = json.loads((directory / "rows.json").read_text())
        self.assertEqual(report["schema_version"], "selection-report-v3")
        self.assertEqual(find(persisted, checkpoint="history")["outcome_provenance"], "saved_cache_descriptive_regrade")
        self.assertEqual(old.read_bytes(), before)
        self.assertNotEqual(directory, old.parent)
        final, = report["final_outcomes"]
        self.assertEqual((final["status"], final["actual"], final["outcome_provenance"]),
                         ("resolved", 6, "saved_cache_descriptive_regrade"))
        self.assertTrue(final["final_confirmed"])
        self.assertFalse(final["outcome_conflict"])
        self.assertFalse({"stats_entry", "derived_context", "cache_path", "outcome_observations"} & set(final))
        self.assertTrue(report["summary"]["disjoint_selected_partitions_reconciled"])

    def test_seeded_frozen_checkpoint_absent_from_new_inputs_remains_in_report(self):
        root, output = self.fixture()
        saved_forecast(root, receipt(BOUNDARY - timedelta(minutes=15), [row(top=True)]))
        saved_sources(root, {"fixture-A": {"team": "AAA", "stats": {"gp": 1, "rec": 6}}})
        first, _ = run_report([root], output, now=KICKOFF + timedelta(days=1),
                              expected_hashes=ENGINE, policy=timing_policy())
        frozen = find(first["rows"])
        partial, _ = self.fixture()
        saved_sources(partial, {})
        later, _ = run_report([partial], output, now=KICKOFF + timedelta(days=1, minutes=1),
                              expected_hashes=ENGINE, policy=timing_policy())
        retained = find(later["rows"])
        self.assertEqual(retained["decision_sha256"], frozen["decision_sha256"])
        self.assertEqual((retained["line"], retained["side"], retained["recorded_selection_at"]),
                         (frozen["line"], frozen["side"], frozen["recorded_selection_at"]))


class AllCategoryReportIntegration(unittest.TestCase):
    def fixture(self, *, final=True, stats=None):
        from test_scorecard import descriptive_fixture
        from reliability import capture
        import scoring
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        root, output = base / "input", base / "derived"
        root.mkdir()
        board, _, hashes = descriptive_fixture()
        board.update(week=7, generated_at=stamp(BOUNDARY - timedelta(minutes=16)),
                     categories=copy.deepcopy(scoring.CATEGORIES))
        board["games"][0].update(id="fictional-game-7", kickoff=stamp(KICKOFF))
        for player in board["players"]: player["game_id"] = "fictional-game-7"
        for picks in board["picks"].values():
            for pick in picks: pick["game_id"] = "fictional-game-7"
        for position, categories in (("QB", ["pass_yd", "pass_td", "pass_cmp", "pass_att", "pass_int"]),
                                     ("RB", ["rush_yd", "rush_att"]), ("WR", ["rec_yd", "rush_rec_yd"])):
            props = [{"key": category, "proj": 2.5, "adj": 3.5, "line": 3.5,
                      "line_from": "ours", "lean": None} for category in categories]
            board["players"].append({"id": "fictional-" + position, "name": "Fictional " + position,
                "game_id": "fictional-game-7", "team": "AAA", "opp": "BBB", "pos": position,
                "proj_ppr": None, "late": False, "props": props})
        meta = {k: board[k] for k in ("season", "week", "generated_at")}
        path, health = capture(board, meta, root, BOUNDARY - timedelta(minutes=15), hashes, mode="live")
        self.assertEqual(health["capture_rows"], 12)
        self.assertNotEqual(path.name, digest(read(path)) + ".json.gz", "native baseline contract must be exercised")
        original = base / "original-board.json"
        original.write_text(json.dumps(board))
        final_board = copy.deepcopy(board)
        final_board["games"][0].update(state="post" if final else "pre", detail="Final" if final else "Scheduled")
        (root / "output/data").mkdir(parents=True)
        (root / "output/data/week.json").write_text(json.dumps(final_board))
        entries = {p["id"]: {"team": "AAA", "opp": "BBB", "pos": p["pos"], "stats": {"gp": 1}}
                   for p in board["players"]}
        entries["fictional-1"]["stats"].update(stats or {"pass_yd": 1, "rec": 1, "rec_yd": -2, "fum_lost": 1})
        (root / "data/cache").mkdir(parents=True)
        (root / "data/cache/stats_2026_07.json").write_text(json.dumps(entries))
        return root, output, original, hashes

    def report(self, root, output, hashes, original=None, *, at=None, enabled=True):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("No provider collection")):
            return run_report([root], output, now=at or KICKOFF + timedelta(days=1), expected_hashes=hashes,
                              policy=timing_policy(), include_descriptive=enabled,
                              original_board_paths=[original] if original else [])

    def test_native_saved_file_to_report_primary_public_and_input_bytes_unchanged(self):
        from selection_publication import _projection
        root, output, original, hashes = self.fixture()
        before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        legacy, legacy_dir = self.report(root, output.parent / "legacy", hashes, enabled=False)
        report, directory = self.report(root, output, hashes, original)
        for field in ("rows", "summary", "primary_raw_vs_adjusted", "final_outcomes", "outcome_observation_index",
                      "matched_checkpoints", "coverage", "timing_policy_sha256", "evaluation_policy_sha256"):
            self.assertEqual(report[field], legacy[field], field)
        self.assertEqual(sum(v["raw_sleeper"]["n"] for v in report["primary_raw_vs_adjusted"]["categories"].values()), 3)
        self.assertNotIn("descriptive_all_categories", legacy)
        self.assertFalse((legacy_dir / "descriptive-evaluation.json").exists())
        report["descriptive_all_categories"]["private_canary"] = "PRIVATE_LOCAL_ONLY_CANARY"
        projected = _projection(report, source_sha="a" * 40, input_digest="b" * 64)
        self.assertEqual(projected, _projection(legacy, source_sha="a" * 40, input_digest="b" * 64))
        self.assertNotIn("PRIVATE_LOCAL_ONLY_CANARY", json.dumps(projected))
        report["descriptive_all_categories"].pop("private_canary")
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertFalse((root / "data/outcomes").exists())
        value = report["descriptive_all_categories"]
        self.assertEqual((len(value["rows"]), len(value["paired_rows"]), len(value["td_rows"])), (12, 11, 1))
        self.assertEqual(value["coverage"]["unique_games"], 1)
        self.assertEqual(value["categories"]["fpts"]["paired"]["raw"]["n"], 1)
        ppr = next(r for r in value["paired_rows"] if r["category"] == "fpts")
        self.assertEqual(ppr["actual"], -1.16)
        self.assertEqual(ppr["provider_ppr"], 10.1)
        self.assertEqual(ppr["outcome_provenance"], "saved_cache_descriptive_regrade")
        self.assertEqual(value["td_rows"][0]["probability_provenance"], "originally_recorded_probability")
        self.assertEqual(json.loads((directory / "descriptive-evaluation.json").read_text()), value)

    def test_rows_metrics_csv_and_retry_content_identity_reconcile(self):
        import csv
        root, output, original, hashes = self.fixture()
        report, directory = self.report(root, output, hashes, original)
        value = report["descriptive_all_categories"]
        for category, result in value["categories"].items():
            rows = [r for r in value["paired_rows"] if r["category"] == category and r["evaluation_status"] == "resolved"]
            self.assertEqual(result["paired"]["raw"]["n"], len(rows))
            for prefix, field in (("raw", "raw_projection"), ("adjusted", "adjusted_projection")):
                metric = result["paired"][prefix]
                self.assertAlmostEqual(metric["absolute_error_sum"], sum(r[field + "_absolute_error"] for r in rows))
                self.assertAlmostEqual(metric["signed_error_sum"], sum(r[field + "_error"] for r in rows))
            self.assertEqual(sum(result["paired"][k] for k in ("helps", "hurts", "ties")), len(rows))
        for label, rows in (("forecasts", value["rows"]), ("pairs", value["paired_rows"]), ("td", value["td_rows"])):
            with (directory / f"descriptive-{label}.csv").open() as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), len(rows))
        saved = {p: p.read_bytes() for p in output.rglob("*") if p.is_file()}
        repeated, same = self.report(root, output, hashes, original, at=KICKOFF + timedelta(days=1, minutes=1))
        self.assertEqual((repeated, same), (report, directory))
        self.assertEqual({p: p.read_bytes() for p in saved}, saved)
        typed = [read(p) for p in (output / "descriptive-evaluation/data/outcomes_derived").rglob("*.json.gz")]
        self.assertEqual(len(typed), 1)
        saved_results = latest_outcomes(typed)
        self.assertEqual(next(r for k, r in saved_results.items() if k[-1] == "fpts")["actual"], -1.16)
        self.assertTrue(all(not r["week_confirmed_complete"] for r in saved_results.values()))

    def test_missing_board_reference_only_and_missing_pair_remain_explicit(self):
        root, output, original, hashes = self.fixture()
        report, _ = self.report(root, output, hashes)
        value = report["descriptive_all_categories"]
        self.assertGreater(sum(v["paired_no_lean"] for v in value["categories"].values()), 0)
        self.assertGreater(sum(v["paired_reference_only"] for v in value["categories"].values()), 0)
        self.assertEqual(value["categories"]["fpts"]["direct_provider_forecast_coverage"], 0)
        self.assertTrue(value["td_rows"][0]["probability_provenance"].startswith("rederived"))
        with self.assertRaisesRegex(ValueError, "explicit"):
            self.report(root, output, hashes, original, enabled=False)

    def test_pending_missing_unknown_and_conflicting_saved_evidence(self):
        from scorecard import DERIVED_STAT_SCHEMA
        root, output, original, hashes = self.fixture(final=False)
        pending, _ = self.report(root, output, hashes, original)
        self.assertEqual(pending["descriptive_all_categories"]["outcome_status"], {"pending": 12})
        board_path = root / "output/data/week.json"
        board = json.loads(board_path.read_text()); board["games"][0].update(state="post", detail="Final")
        board_path.write_text(json.dumps(board))
        cache = root / "data/cache/stats_2026_07.json"
        entries = json.loads(cache.read_text()); entries.pop("fictional-1")
        cache.write_text(json.dumps(entries))
        missing, _ = self.report(root, output, hashes, original, at=KICKOFF + timedelta(days=1, minutes=1))
        self.assertEqual(missing["descriptive_all_categories"]["categories"]["fpts"]["outcome_status"], {"unresolved": 1})
        entries["fictional-1"] = {"team": "AAA", "opp": "BBB", "pos": "WR", "participation_status": "dnp", "participation_source": "fictional"}
        cache.write_text(json.dumps(entries))
        dnp, _ = self.report(root, output, hashes, original, at=KICKOFF + timedelta(days=1, minutes=2))
        self.assertEqual(dnp["descriptive_all_categories"]["categories"]["fpts"]["outcome_status"], {"dnp": 1})
        write(root, "outcomes", {"schema_version": "future-unsupported-v9", "season": 2026, "week": 7})
        unsupported, _ = self.report(root, output, hashes, original, at=KICKOFF + timedelta(days=1, minutes=3))
        self.assertEqual(unsupported["descriptive_all_categories"]["unsupported_outcome_receipts"][0]["reason"], "unsupported_descriptive_outcome_contract")
        # New typed saved files are read from the input lane too. Opposing
        # independently pinned derivations have no winner based on a new clock.
        other_root, other_output, other_original, other_hashes = self.fixture(stats={"gp": 1, "rec": 2})
        self.report(other_root, other_output, other_hashes, other_original)
        typed = next(read(p) for p in (other_output / "descriptive-evaluation/data/outcomes_derived").rglob("*.json.gz"))
        self.assertEqual(typed["schema_version"], DERIVED_STAT_SCHEMA)
        write(root, "outcomes", typed)
        conflict, _ = self.report(root, output, hashes, original, at=KICKOFF + timedelta(days=1, minutes=4))
        self.assertEqual(conflict["descriptive_all_categories"]["categories"]["fpts"]["outcome_status"], {"unresolved": 1})


class VersionedSummaryTests(unittest.TestCase):
    def rows(self):
        decisions, _ = build_decisions(core_snapshots(), timing_policy(), KICKOFF, ENGINE)
        rows = grade_decisions(decisions, {})
        selected = next(row for row in rows if row["action"] == "SELECT")
        alternatives = []
        for index, (source, policy_hash, provenance, week) in enumerate((
                ("dk", "a" * 64, selected["provenance_class"], 7),
                ("sleeper", "a" * 64, selected["provenance_class"], 7),
                ("dk", "b" * 64, selected["provenance_class"], 7),
                ("dk", "a" * 64, "inherited_or_unclocked_archive", 6))):
            row = dict(selected, line_from=source, policy_sha256=policy_hash,
                       provenance_class=provenance, week=week, result="win" if index % 2 else "loss")
            row["decision_sha256"] = digest({"fictional_original": selected["decision_sha256"], "variant": index})
            alternatives.append(row)
        return alternatives

    def test_joint_policy_source_period_and_provenance_are_real_member_sets(self):
        rows = self.rows()
        summary = summarize(rows)
        by_id = {row["decision_sha256"]: row for row in rows}
        for table in summary["tables"]:
            members = [by_id[key] for key in table["row_ids"]]
            for key in ("provenance_class", "model_version", "engine_sha256", "policy_version", "policy_sha256", "checkpoint"):
                self.assertEqual({row[key] for row in members}, {table[key]})
            if table["line_source_scope"] != "all":
                self.assertEqual({row["line_from"] for row in members}, {table["line_source_scope"]})
                self.assertIn(table["dimension"], ("overall", "category", "category_side"))
            self.assertEqual(table["rows"], len(members))
            self.assertEqual(table["win"] + table["loss"], table["decided"])
            self.assertEqual(table["hit_rate"], table["win"] / table["decided"] if table["decided"] else None)
        # Equal policy names with distinct identities cannot mix in a headline.
        whole = [table for table in summary["tables"] if table["period"] == "cumulative"
                 and table["dimension"] == "overall" and table["line_source_scope"] == "all"
                 and table["view"] == rows[0]["cohort"]]
        self.assertEqual(sum(table["rows"] for table in whole), len(rows))
        self.assertEqual(len(whole), 3)

    def test_legacy_summary_has_original_fields_ids_and_no_inferred_joint_context(self):
        rows = self.rows()
        legacy = summarize(rows, contract="selection-report-v2")
        for table in legacy["tables"]:
            self.assertFalse({"policy_version", "policy_sha256", "line_source_scope"} & table.keys())
            self.assertEqual(table["summary_id"], digest({key: value for key, value in table.items()
                                                       if key not in ("row_ids", "summary_id")}))
        with self.assertRaises(IntegrityError):
            summarize(rows, contract="selection-report-unknown")

    def test_no_side_coverage_is_not_an_under_loss_and_partition_stays_disjoint(self):
        rows = self.rows()[:2]
        no_action = dict(rows[0], action="NO_ACTION", side=None, result="no_action",
                         reason="missing_real_offer", decision_sha256=digest("fictional-no-action"))
        rows.append(no_action)
        tables = summarize(rows)["tables"]
        aggregate = next(table for table in tables if table["dimension"] == "overall" and table["period"] == "cumulative"
                         and table["line_source_scope"] == "all" and table["view"] == rows[0]["cohort"])
        self.assertEqual((aggregate["win"], aggregate["loss"], aggregate["no_action"], aggregate["decided"]), (1, 1, 1, 2))
        self.assertEqual(aggregate["hit_rate"], .5)
        sides = [table for table in tables if table["dimension"] == "category_side" and table["period"] == "cumulative"
                 and table["line_source_scope"] == "all" and table["view"] == rows[0]["cohort"]]
        self.assertEqual(sum(table["no_action"] for table in sides), 1)
        self.assertTrue(summarize(rows)["disjoint_selected_partitions_reconciled"])


class ExtendedJointTests(unittest.TestCase):
    def test_full_joint_populations_use_exact_rows_and_preserve_legacy_tables(self):
        policy=timing_policy()
        observations=[receipt(BOUNDARY-timedelta(minutes=15),[row("A",top=True),row("B",side="under"),row("C","rush_rec_yd")])]
        decisions,_=build_decisions(observations,policy,BOUNDARY+timedelta(hours=1),ENGINE)
        rows=grade_decisions(decisions,{})
        # Separate exact source/day contexts deliberately disagree. No marginal
        # percentage is a substitute for the actual full joint membership.
        rows[0]=dict(rows[0],selection_weekday="Tuesday",line_from="dk")
        old=summarize(rows,contract="selection-report-v3")
        extended=summarize(rows,contract="selection-report-v4")
        self.assertFalse(any(t["dimension"]=="category_side_selection_kickoff_lead" for t in old["tables"]))
        joint=[t for t in extended["tables"] if t["dimension"]=="category_side_selection_kickoff_lead"]
        self.assertTrue(joint)
        by_id={r["decision_sha256"]:r for r in rows}
        for table in joint:
            value=json.loads(table["value"])
            for row_id in table["row_ids"]:
                r=by_id[row_id]
                self.assertEqual(value,[r.get(k) for k in ("category","side","selection_weekday","kickoff_weekday","lead_time_bucket")])
                if table["line_source_scope"]!="all":self.assertEqual(r["line_from"] or "unknown",table["line_source_scope"])
            self.assertEqual(table["rows"],len(table["row_ids"]))
        old_all={t["summary_id"]:t for t in old["tables"] if t["line_source_scope"]=="all"}
        new_all={t["summary_id"]:t for t in extended["tables"] if t["line_source_scope"]=="all" and t["dimension"]!="category_side_selection_kickoff_lead"}
        self.assertEqual(old_all,new_all)


class PresenceModelReportDispatchTests(unittest.TestCase):
    def test_both_presence_observations_preserve_separate_saved_memberships(self):
        captures = []
        for i, model in enumerate(corrected.PRESENCE_MODELS):
            payload = receipt(BOUNDARY-timedelta(minutes=10), [row(player="fictional-source-"+str(i), top=True)])
            hashes = corrected.source_hashes(model)
            payload.update(schema_version=corrected.NATIVE, model=model, presence_contract=corrected.PRESENCE,
                           engine_files=hashes, engine_sha256=digest(hashes))
            captures.append(payload)
        before = copy.deepcopy(captures)
        decisions, _ = build_decisions(captures, timing_policy(), KICKOFF, ENGINE)
        selected = [d for d in decisions if d["action"] == "SELECT"]
        self.assertEqual(captures, before)
        self.assertEqual({d["model_version"] for d in selected}, set(corrected.PRESENCE_MODELS))
        for decision in selected:
            self.assertEqual(decision["engine_files"], corrected.source_hashes(decision["model_version"]))
            self.assertIs(decision["top_at_decision"], True)
        bad = copy.deepcopy(captures[-1]); bad["model"] = "unsupported"
        with self.assertRaises(IntegrityError):
            build_decisions([bad], timing_policy(), KICKOFF, ENGINE)

    def test_input_inventory_pins_all_three_actual_cache_namespaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ["data/cache/stats_2026_07.json", "data/cache/stat-keys-fgm-v1/stats_2026_07.json",
                     "data/cache/stat-keys-presence-fgm-v2/stats_2026_07.json"]
            for name in names:
                path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('{}')
            manifest, _ = _inventory([root])
            self.assertEqual({item["path"] for item in manifest}, set(names))
            self.assertTrue(all(item["bytes"] == 2 and item["pin_binding"] == "CONTENT_ADDRESSED_UNPINNED"
                                for item in manifest))


class SavedClassicReportTests(unittest.TestCase):
    def test_actual_classic_lane_filename_and_saved_rows_are_preserved(self):
        import classic_model_v1 as classic
        from test_scorecard import classic_saved_fixture
        _,native,_,at=classic_saved_fixture();before=copy.deepcopy(native)
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory)
            identity=digest({"data":native["input_sha256"],"execution":native["execution_contract_sha256"],"mode":native["mode"]})
            path=root/"data/current-classic/2026/w05"/(identity+".json.gz");path.parent.mkdir(parents=True)
            immutable_write(path,native); original=path.read_bytes()
            manifest,inputs=_inventory([root]);self.assertEqual(inputs["forward"],[native])
            self.assertEqual(manifest[0]["path"],path.relative_to(root).as_posix())
            policy=timing_policy();policy["registered_at"]=stamp(at-timedelta(days=1))
            decisions,_=build_decisions(inputs["forward"],policy,at+timedelta(hours=3),ENGINE)
            self.assertEqual({r["model_version"]for r in decisions},{classic.MODEL})
            self.assertEqual(native,before);self.assertEqual(path.read_bytes(),original)
            bad=path.with_name("0"*64+".json.gz");bad.write_bytes(original)
            with self.assertRaises(IntegrityError):_inventory([root])


if __name__ == "__main__":
    unittest.main()
