"""Fictional identity/version migration checks; only temporary fixture writes."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "pull"), str(ROOT / "tools")]
import build
import grade

EXPECTED_VERSION = "statistical-presence-verified-int-v7-20261112"
OLD_VERSION = "statistical-v2"


def fixture():
    prop = dict(key="rec", line=4.5, adj=6, proj=6, source="model", line_from="dk", lean="over")
    player = dict(id="fictional-player", name="Fictional Receiver", team="AAA", opp="BBB", pos="WR",
                  game_id="fictional-game", props=[prop], proj_ppr=12)
    pick = dict(prop, player_id=player["id"], game_id=player["game_id"])
    archive = dict(season=2099, week=1, players=[player], picks={"over": [pick], "under": []},
        games=[dict(id=player["game_id"], home="AAA", away="BBB", kickoff="2099-01-01T00:00:00Z")])
    stats = {player["id"]: dict(team="AAA", opp="BBB", stats={"gp": 1, "rec": 6})}
    return archive, stats


class IdentityV3Tests(unittest.TestCase):
    def test_verified_interception_zero_changes_grade_without_mutating_sparse_stats(self):
        archive = json.loads((ROOT/'output/data/archive/2026_w05.json').read_bytes())
        stats = json.loads((ROOT/'data/cache/stat-keys-presence-strict-v3/stats_2026_05.json').read_bytes())
        before = json.dumps((archive,stats),sort_keys=True)
        raw = (ROOT/'output/data/archive/2026_w05.json').read_bytes()
        verified = grade.verified_int_outcomes()[hashlib.sha256(raw).hexdigest()]
        old = grade.grade_week(archive,stats,None)
        new = grade.grade_week(archive,stats,None,verified)
        self.assertEqual(old['leans']['by_category']['pass_int']['unresolved'],14)
        self.assertEqual((new['leans']['by_category']['pass_int']['hit'],new['leans']['by_category']['pass_int']['miss']), (9,11))
        self.assertEqual(new['leans']['by_category']['pass_int']['unresolved'],0)
        self.assertEqual(old['ppr'],new['ppr'])
        self.assertEqual(old['matchup'],new['matchup'])
        self.assertEqual({k:v for k,v in old['leans']['by_category'].items()if k!='pass_int'},
                         {k:v for k,v in new['leans']['by_category'].items()if k!='pass_int'})
        self.assertEqual(json.dumps((archive,stats),sort_keys=True),before)
        self.assertNotIn('pass_int',stats['6770']['stats'])

    def test_new_week4_evidence_preserves_source_absence_and_previous_scope(self):
        archive=json.loads((ROOT/'output/data/archive/2026_w04.json').read_bytes())
        stats=json.loads((ROOT/'data/cache/stat-keys-presence-strict-v3/stats_2026_04.json').read_bytes())
        before=json.dumps((archive,stats),sort_keys=True)
        digest=hashlib.sha256((ROOT/'output/data/archive/2026_w04.json').read_bytes()).hexdigest()
        verified=grade.verified_int_outcomes()[digest]
        self.assertEqual(verified,{('401872978','3163'):0,('401872979','12545'):0})
        old=grade.grade_week(archive,stats,None)
        new=grade.grade_week(archive,stats,None,verified)
        self.assertEqual(old['leans']['by_category']['pass_int']['unresolved'],2)
        self.assertEqual((new['leans']['by_category']['pass_int']['hit'],new['leans']['by_category']['pass_int']['miss'],new['leans']['by_category']['pass_int']['unresolved']),(0,2,0))
        self.assertEqual(old['ppr'],new['ppr'])
        self.assertEqual(old['matchup'],new['matchup'])
        self.assertEqual({k:v for k,v in old['leans']['by_category'].items()if k!='pass_int'},
                         {k:v for k,v in new['leans']['by_category'].items()if k!='pass_int'})
        self.assertEqual(json.dumps((archive,stats),sort_keys=True),before)
        for pid in ['3163','12545']:self.assertNotIn('pass_int',stats[pid]['stats'])

    def test_all_verified_player_games_are_explicit_passing_values(self):
        registry=grade.verified_int_outcomes()
        values=[v for rows in registry.values()for v in rows.values()]
        self.assertEqual(len(values),88)
        self.assertEqual(sum(v==0 for v in values),48)
        self.assertTrue(all(type(v)is int and v>=0 for v in values))

    def test_verified_index_tampering_fails_before_source_use(self):
        raw=(ROOT/'output/data/verified-int-v1/index-v2.json').read_bytes()
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);target=root/'output/data/verified-int-v1/index-v2.json';target.parent.mkdir(parents=True)
            target.write_bytes(raw+b' ')
            with patch.object(grade,'__file__',str(root/'pull/grade.py')):
                with self.assertRaisesRegex(ValueError,'VERIFIED_INT_INDEX_IDENTITY'):
                    grade.verified_int_outcomes.__wrapped__()

    def test_verified_outcome_never_substitutes_for_missing_participation(self):
        prop=dict(key='pass_int',line=.5)
        self.assertEqual(grade._prop_result(prop,'under',{'stats':{}},0),(None,'unresolved'))
        self.assertEqual(grade._prop_result(prop,'under',{'stats':{'gp':1,'pass_int':None}}),(None,'unresolved'))
        self.assertEqual(grade._prop_result(prop,'under',{'stats':{'gp':1,'pass_int':None}},0),(0,'hit'))

    def test_canonical_audited_archive_change_fails_closed(self):
        archive,stats=fixture();archive.update(season=2026,week=5)
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);folder=root/'output/data/archive';folder.mkdir(parents=True)
            (folder/'2026_w05.json').write_text(json.dumps(archive))
            with patch.object(grade,'__file__',str(root/'pull/grade.py')),patch.object(grade,'verified_int_outcomes',return_value={'known-original-hash':{}}):
                with self.assertRaisesRegex(ValueError,'VERIFIED_INT_ARCHIVE_CHANGED'):
                    grade.grade_all(folder,lambda *args:stats,(2026,5),{'fictional-game'})

    def test_new_version_is_explicit_on_week_and_issued_report(self):
        self.assertEqual(grade.GRADING_VERSION, EXPECTED_VERSION)
        archive, stats = fixture()
        week = grade.grade_week(archive, stats, {"fictional-game"})
        self.assertEqual(week["grading_version"], EXPECTED_VERSION)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "archive.json").write_text(json.dumps(archive))
            issued = grade.grade_all(path, lambda *args: stats, (2099, 1), {"fictional-game"})
            self.assertEqual(issued["grading_version"], EXPECTED_VERSION)
            self.assertEqual(issued["weeks"][0]["grading_version"], EXPECTED_VERSION)

    def test_valid_same_game_and_wrong_team_opponent_are_distinct(self):
        archive, stats = fixture()
        self.assertEqual(grade.grade_week(archive, stats, {"fictional-game"})["top_over"]["hit"], 1)
        for field in ("team", "opp"):
            wrong = copy.deepcopy(stats)
            wrong["fictional-player"][field] = "OTHER"
            report = grade.grade_week(archive, wrong, {"fictional-game"})
            self.assertEqual(report["top_over"]["unresolved"], 1)
            self.assertEqual(report["leans"]["unresolved"], 1)

    def test_top_pick_game_cannot_borrow_another_player_game_statistic(self):
        archive, stats = fixture()
        archive["picks"]["over"][0]["game_id"] = "other-game"
        report = grade.grade_week(archive, stats, {"fictional-game", "other-game"})
        self.assertEqual(report["top_over"]["unresolved"], 1)

    def test_builder_preserves_previously_issued_bytes_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "track_record.json"
            old = ('{ "grading_version": "' + OLD_VERSION + '", "issued": "fictional" }\n').encode()
            path.write_bytes(old)
            build.dump(path, {"grading_version": EXPECTED_VERSION, "issued": "new-fictional"})
            target = path.parent / "grading-history" / (hashlib.sha256(old).hexdigest() + ".json")
            self.assertEqual(target.read_bytes(), old)
            self.assertEqual(json.loads(target.read_bytes())["grading_version"], OLD_VERSION)
            self.assertEqual(json.loads(path.read_bytes())["grading_version"], EXPECTED_VERSION)

    def test_each_issued_revision_is_retained_without_relabeling(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "track_record.json"
            build.dump(path, {"grading_version": EXPECTED_VERSION, "actual": 4})
            first = path.read_bytes()
            build.dump(path, {"grading_version": EXPECTED_VERSION, "actual": 5})
            second = path.read_bytes()
            build.dump(path, {"grading_version": EXPECTED_VERSION, "actual": 6})
            for issued in (first, second):
                self.assertEqual((path.parent / "grading-history" / (hashlib.sha256(issued).hexdigest() + ".json")).read_bytes(), issued)
            grade.preserve_issued_record(path)
            count = len(list((path.parent / "grading-history").glob("*.json")))
            grade.preserve_issued_record(path)
            self.assertEqual(len(list((path.parent / "grading-history").glob("*.json"))), count)

    def test_corrupt_history_fails_before_replacing_issued_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "track_record.json"
            issued = b'{"grading_version":"statistical-v2","issued":"fictional"}'
            path.write_bytes(issued)
            target = path.parent / "grading-history" / (hashlib.sha256(issued).hexdigest() + ".json")
            target.parent.mkdir()
            target.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                build.dump(path, {"grading_version": EXPECTED_VERSION})
            self.assertEqual(path.read_bytes(), issued)

    def test_partial_write_never_occupies_final_path_and_retry_succeeds(self):
        real_fdopen = grade.os.fdopen
        class InterruptedWriter:
            def __init__(self, fd, mode):
                self.stream = real_fdopen(fd, mode)
            def __enter__(self):
                self.stream.__enter__()
                return self
            def write(self, value):
                self.stream.write(value[:7])
                self.stream.flush()
                raise OSError("FICTIONAL_INTERRUPTED_PARTIAL_WRITE")
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "track_record.json"
            issued = json.dumps(dict(grading_version=OLD_VERSION, issued="fictional-original")).encode()
            path.write_bytes(issued)
            target = path.parent / "grading-history" / (hashlib.sha256(issued).hexdigest() + ".json")
            with patch.object(grade.os, "fdopen", side_effect=InterruptedWriter):
                with self.assertRaisesRegex(OSError, "FICTIONAL_INTERRUPTED_PARTIAL_WRITE"):
                    build.dump(path, {"grading_version": EXPECTED_VERSION})
            self.assertEqual(path.read_bytes(), issued)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.iterdir()), [])
            build.dump(path, {"grading_version": EXPECTED_VERSION})
            self.assertEqual(target.read_bytes(), issued)
            self.assertEqual(json.loads(path.read_bytes())["grading_version"], EXPECTED_VERSION)

    def test_fsync_interruption_publishes_nothing_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "track_record.json"
            issued = json.dumps(dict(grading_version=OLD_VERSION, issued="fictional-original")).encode()
            path.write_bytes(issued)
            target = path.parent / "grading-history" / (hashlib.sha256(issued).hexdigest() + ".json")
            with patch.object(grade.os, "fsync", side_effect=OSError("FICTIONAL_FSYNC_INTERRUPTION")):
                with self.assertRaisesRegex(OSError, "FICTIONAL_FSYNC_INTERRUPTION"):
                    build.dump(path, {"grading_version": EXPECTED_VERSION})
            self.assertEqual(path.read_bytes(), issued)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.iterdir()), [])
            build.dump(path, {"grading_version": EXPECTED_VERSION})
            self.assertEqual(target.read_bytes(), issued)

    def test_symlink_history_collision_does_not_rewrite_any_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "track_record.json"
            issued = json.dumps(dict(grading_version=OLD_VERSION, issued="fictional-original")).encode()
            path.write_bytes(issued)
            original = path.parent / "fictional-other-original.json"
            original.write_bytes(b"FICTIONAL_ORIGINAL_MUST_REMAIN_UNCHANGED")
            target = path.parent / "grading-history" / (hashlib.sha256(issued).hexdigest() + ".json")
            target.parent.mkdir()
            target.symlink_to(original)
            with self.assertRaisesRegex(ValueError, "history checksum mismatch"):
                build.dump(path, {"grading_version": EXPECTED_VERSION})
            self.assertTrue(target.is_symlink())
            self.assertEqual(path.read_bytes(), issued)
            self.assertEqual(original.read_bytes(), b"FICTIONAL_ORIGINAL_MUST_REMAIN_UNCHANGED")
            self.assertEqual(list(target.parent.iterdir()), [target])


if __name__ == "__main__":
    unittest.main()
