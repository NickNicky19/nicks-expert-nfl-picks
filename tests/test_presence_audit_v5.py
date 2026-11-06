"""Audit A2/A3 controls through real intake, serialization, grading and capture.

Fictional software controls. They do not recover missing historical source data,
fit a model, call a provider, or establish a forecasting accuracy improvement.
"""
import copy
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / name) for name in ('pull', 'tools', 'tests')]
import build
import grade
import scoring
import classic_build_pair_v1 as pair
import classic_model_v1 as old_model
import classic_model_v2 as model
import reliability
import weekly_adaptive_overlay as overlay
import weekly_selected_rankings as ranking
from test_grading_identity_v3 import fixture as grade_fixture
from test_weekly_selected_rankings import fixture as ranking_fixture, make, NOW, PERSIST


def source_rows(stats):
    return [dict(player_id='fictional-player', team='AAA', opponent='BBB', stats=stats)]


def intake(stats):
    return build.trim_stats(source_rows(stats), source_context=dict(
        adapter='sleeper-week-stats-v1', season=2099, week=1))['fictional-player']


class PresenceAuditTests(unittest.TestCase):
    def test_explicit_null_zero_and_absence_survive_real_serialization_and_grade(self):
        archive, _ = grade_fixture()
        archive['players'][0]['props'][0].update(line=.5, lean='under')
        archive['picks'] = {'over': [], 'under': [dict(archive['players'][0]['props'][0],
            player_id='fictional-player', game_id='fictional-game')]}
        for name, component, expected in [('null', {'rec': None}, 'unresolved'),
                                          ('zero', {'rec': 0}, 'hit'),
                                          ('absent', {}, 'unresolved')]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                stats = {'gp': 1, 'off_snp': 20, **component}
                entry = intake(stats)
                path = Path(directory) / 'actual.json'
                build.dump(path, {'fictional-player': entry})
                saved = json.loads(path.read_bytes())
                preserved = saved['fictional-player']['stats']
                self.assertEqual('rec' in preserved, 'rec' in component)
                self.assertEqual(preserved['_presence']['original_row']['stats'], stats)
                outcome = grade.grade_week(archive, saved, {'fictional-game'})['top_under']
                self.assertEqual(outcome[expected], 1)
                self.assertEqual(outcome['n_decided'], int(expected == 'hit'))
                self.assertEqual(outcome['picks'][0]['actual'], 0 if name == 'zero' else None)

    def test_partial_composites_never_borrow_zero(self):
        for key, parts in [('rush_rec_yd', {'rush_yd': 55, 'rec_yd': None}),
                           ('rush_rec_yd', {'rush_yd': None, 'rec_yd': 55}),
                           ('anytime_td', {'rush_td': 0, 'rec_td': None}),
                           ('anytime_td', {'rush_td': None, 'rec_td': 0})]:
            with self.subTest(key=key, parts=parts):
                entry = intake({'gp': 1, **parts})
                self.assertEqual(grade._prop_result({'key': key, 'line': 60.5}, 'under', entry),
                                 (None, 'unresolved'))
        self.assertEqual(scoring.stat_value('rush_rec_yd', {'rush_yd': -3, 'rec_yd': 0}), -3)

    def test_invalid_components_remain_invalid_after_json_roundtrip(self):
        for value in [True, False, '0', '', float('nan'), float('inf'), -float('inf'), -1, .5]:
            with self.subTest(value=value):
                entry = intake({'gp': 1, 'rec': value})
                saved = json.loads(json.dumps(entry, allow_nan=False))
                self.assertEqual(scoring.component(saved['stats'], 'rec')['state'], 'invalid_value')
                self.assertEqual(grade._prop_result({'key': 'rec', 'line': .5}, 'under', saved),
                                 (None, 'unresolved'))
        self.assertEqual(scoring.component(intake({'gp': 1, 'rec': 0})['stats'], 'rec')['state'], 'reported_zero')

    def test_participation_or_claimed_sparse_contract_is_not_completeness(self):
        entry = intake({'gp': 1, 'off_snp': 20})
        entry['stats']['_presence']['sparse_contract'] = scoring.LEGACY_SPARSE_ASSUMPTION
        self.assertIsNone(scoring.stat_value('rec', entry['stats']))
        self.assertIsNone(scoring.stat_value('rec', {'gp': 1}))
        self.assertEqual(grade.participation(entry), 'played')
        self.assertEqual(grade._prop_result({'key': 'rec', 'line': .5}, 'under', entry), (None, 'unresolved'))

    def test_composite_ppr_requires_every_required_component(self):
        complete = {key: 0 for key in scoring.PPR}
        complete.update(idp_fum_rec=0, rec=2, rec_yd=15)
        self.assertEqual(scoring.ppr_points(complete), 3.5)
        self.assertEqual(scoring.fantasy_points(complete, 'WR', half=True), 2.5)
        for key in scoring.PPR:
            missing = dict(complete)
            missing.pop(key)
            self.assertIsNone(scoring.ppr_points(missing), key)
            missing[key] = None
            self.assertIsNone(scoring.ppr_points(missing), key)

    def test_td_projection_unknown_zero_fractional_and_full_path(self):
        class Neutral:
            def factor(self, *_): return 1, 0
        for raw, expected in [(None, None), ({}, None), ({'rush_td': 0}, None),
                              ({'rush_td': None, 'rec_td': 0}, None),
                              ({'rush_td': 0, 'rec_td': 0}, 0),
                              ({'rush_td': .2, 'rec_td': .3}, round(scoring.td_probability(.5), 3))]:
            projection = build.projection_components(raw) if raw is not None else None
            props = build.player_props({'pos': 'RB'}, projection, [], 2099, 'BBB', Neutral())
            td = next(p for p in props if p['key'] == 'anytime_td')
            self.assertEqual(td['td_chance'], expected)
            self.assertEqual(td['proj'], .5 if expected not in (None, 0) else expected)
            if expected is None: self.assertIsNone(td['lean'])

    def test_projection_invalid_values_keep_original_presence_and_fractional_counts(self):
        p = build.projection_components({'rec': 4.25, 'rush_td': float('nan'), 'rec_td': None})
        self.assertEqual(scoring.stat_value('rec', p, projection=True), 4.25)
        self.assertEqual(p['_presence']['invalid_fields'], ['rush_td'])
        self.assertEqual(p['_presence']['original_components']['rush_td']['value'], 'nan')
        self.assertIsNone(scoring.stat_value('anytime_td', p, projection=True))
        json.dumps(p, allow_nan=False)

    def test_matchups_exclude_unknown_components_instead_of_zero(self):
        from matchup import Matchups
        weeks = {i: {'p': dict(opp=opp, stats=intake({'gp': 1, 'rec': value})['stats'])}
                 for i, (opp, value) in enumerate([('BBB', 4), ('CCC', None), ('DDD', 8)], 1)}
        actual = Matchups(weeks, {'p': 'WR'})
        self.assertEqual(actual.factor('CCC', 'WR', 'rec', 6), (1.0, 0))
        self.assertEqual(actual.factor('BBB', 'WR', 'rec', 6), (.944, 1))

    def test_old_and_new_profiles_reject_crossed_sources_without_changing_old_identity(self):
        self.assertEqual(old_model.MODEL, 'sleeper-matchup-classic-fg-identity-v1')
        self.assertEqual(old_model.CACHE, 'stat-keys-fgm-v1')
        self.assertEqual(model.contract(ROOT)['model'], model.MODEL)
        with self.assertRaisesRegex(ValueError, 'UNRECOGNIZED_CLASSIC_CURRENT_SOURCE'):
            old_model.contract(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            historical = Path(directory)
            for name, checksum in old_model.ENGINE.items():
                raw = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                    'fe369c7462e4e4f290727b2d03b696d28ef5454b:' + name])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), checksum)
                p = historical / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(raw)
            self.assertEqual(old_model.contract(historical)['model'], old_model.MODEL)
            with self.assertRaisesRegex(ValueError, 'UNRECOGNIZED_CLASSIC_CURRENT_SOURCE'):
                model.contract(historical)

    def test_started_old_reference_origin_stays_old_while_future_is_new(self):
        board, _ = ranking_fixture()
        old = copy.deepcopy(board)
        old['execution_model'] = dict(model=old_model.MODEL)
        old['generated_at'] = board['generated_at'] = '2031-10-25T18:00:00Z'
        old['games'][0]['state'] = board['games'][0]['state'] = 'in'
        for p in old['players']: p['reference_model'] = old_model.MODEL
        pair.bind_reference_origins(board, old)
        self.assertTrue(all(p['reference_model'] == old_model.MODEL for p in board['players']))
        board['games'][0]['state'] = 'pre'
        board['generated_at'] = '2031-10-24T12:00:00Z'
        pair.bind_reference_origins(board, old)
        self.assertTrue(all(p['reference_model'] == model.MODEL for p in board['players']))

    def test_frozen_v1_rankings_keep_original_policy_and_values_under_v2(self):
        board, doc = ranking_fixture()
        board['execution_model'] = dict(model=old_model.MODEL)
        for p in board['players']: p['reference_model'] = old_model.MODEL
        doc['rows'] = []
        doc['display_board_sha256'] = doc['canonical_board_sha256'] = overlay.digest(board)
        previous = make(board, doc)
        self.assertEqual(previous['policy'], ranking.CURRENT_POLICY)
        with tempfile.TemporaryDirectory() as directory:
            receipt = ranking.write_public(previous, directory, reliability.atomic_json, clock=lambda: PERSIST)
            frozen_before = overlay.canonical(previous['picks'])
            board['execution_model'] = model.contract(ROOT)
            doc['display_board_sha256'] = doc['canonical_board_sha256'] = overlay.digest(board)
            successor = make(board, doc, now='2031-10-25T18:00:00Z', previous=previous, previous_receipt=receipt)
            self.assertEqual(successor['policy'], ranking.PRESENCE_POLICY)
            self.assertEqual(overlay.canonical(successor['picks']), frozen_before)
            pointer = ranking.write_public(successor, directory, reliability.atomic_json,
                                           clock=lambda: '2031-10-25T18:00:01Z')
            ranking.validate_document(successor, pointer, board, overlay.digest(board), doc, root=directory)
            bad = copy.deepcopy(previous)
            bad['policy'] = ranking.PRESENCE_POLICY
            bad['policy_sha256'] = ranking.PRESENCE_POLICY_SHA
            with self.assertRaisesRegex(ValueError, 'ranking original current reference policy'):
                ranking.validate_origin_policy(bad, receipt, bad['picks']['over'][0], board)

    def test_issued_grades_are_append_preserved_and_missing_presence_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'track_record.json'
            original = b'{ "grading_version":"statistical-v3-identity-20261025", "hit":1 }\n'
            target.write_bytes(original)
            build.dump(target, dict(grading_version=grade.GRADING_VERSION, unresolved=1))
            saved = target.parent / 'grading-history' / (hashlib.sha256(original).hexdigest() + '.json')
            self.assertEqual(saved.read_bytes(), original)
        value, outcome = grade._prop_result({'key': 'rec', 'line': .5}, 'under', {'stats': {'gp': 1}})
        self.assertIsNone(value)
        self.assertEqual(outcome, 'unresolved')


if __name__ == '__main__':
    unittest.main()
