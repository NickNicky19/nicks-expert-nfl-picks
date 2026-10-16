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
from reliability import IntegrityError, digest, immutable_write, stamp, utc, engine_hashes
from evidence import read, write
from selection_report import (build_decisions, grade_decisions, summarize, run_report,
                              matched_checkpoints, archive_decisions, render_html, _inventory)

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
                     "outcome_observations", "outcome_collected_at", "week_confirmed_complete", "outcome_provenance")}
        self.assertEqual(digest(material), candidate["decision_sha256"])
        self.assertTrue(directory.exists())
        self.assertTrue(revised["coverage"]["frozen_decision_conflicts"])

    def test_actual_cli_uses_real_clock_and_emits_local_report_only(self):
        root, output = self.fixture()
        kickoff = datetime.now(timezone.utc) - timedelta(days=1)
        payload = receipt(kickoff - timedelta(hours=1), [row(kickoff=kickoff, top=True)])
        payload.update(engine_files=engine_hashes(ROOT), engine_sha256=digest(engine_hashes(ROOT)))
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


if __name__ == "__main__":
    unittest.main()
