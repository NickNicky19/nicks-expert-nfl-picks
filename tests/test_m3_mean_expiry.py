"""Fictional numerical-wire fixtures. No NFL fit, source, or admission claim."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import stat_point_mae_public_v2 as wire
_spec = importlib.util.spec_from_file_location('legacy_numeric_fixture', ROOT / 'tests/test_weekly_mae_display_v2.py')
_old = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_old)


def fixture():
    value = _old.fixture()
    value['schema_version'] = 'stat-point-mae-public-feed-v2-expiring-v1'
    value['catalog']['schema_version'] = 'stat-point-mae-public-catalog-v2-expiring-v1'
    value['source_registry']['schema_version'] = 'stat-point-mae-source-registry-v2-expiring-v1'
    condition = 'observed_statistical_appearance_v1'
    commitment = 'e' * 64  # Explicit fictional contract, never a production allowlist.
    expiry = '2099-10-31T01:30:00.000001Z'
    entry = value['catalog']['entries'][0]
    entry.update(target='rec', scoring_target='rec',
        method_id='C-M3-v1.1::rec::M3-0::base::MEAN_POINT',
        forecast_product='point_mean', prediction_functional='expected_mean',
        public_roles=['WR', 'TE'], conditional_on=condition,
        conditioning_contract_sha256=commitment)
    source = value['source_registry']['records'][0]
    source.update(target='rec', public_roles=['WR', 'TE'], conditional_on=condition,
        conditioning_contract_sha256=commitment, expires_at=expiry)
    row = value['rows'][0]
    row.update({k: entry[k] for k in entry})
    row.update(schema_version='stat-point-mae-v2-expiring-v1',
        consumer_contract_version='stat-point-mae-v2-expiring-v1',
        position='WR', expires_at=expiry, selected_projection=3., functional_proof=None,
        fallback=False, trained_prior_only=False, fallback_reason='',
        feature_max_source_available_utc=row['information_cutoff_utc'],
        projection_label='Appearance-conditioned mean')
    return _old._wire_reseal(value)


class ExpiringMeanTests(unittest.TestCase):
    def reject(self, value):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            wire.validate_feed(value)

    def test_exact_mean_and_truthful_target_survive_round_trip(self):
        value = fixture()
        before = wire.canonical(value)
        wire.validate_feed(wire.strict_json(before))
        self.assertEqual(wire.canonical(value), before)
        self.assertEqual(value['rows'][0]['conditional_on'], 'observed_statistical_appearance_v1')
        self.assertEqual(value['rows'][0]['selected_projection'], value['rows'][0]['expected_mean'])

    def test_expiry_is_bound_to_the_admitted_source(self):
        for field, changed in [('expires_at', '2099-10-31T01:31:00Z'),
                ('conditioning_contract_sha256', 'f' * 64), ('conditional_on', 'played')]:
            value = fixture(); value['rows'][0][field] = changed
            with self.subTest(field=field): self.reject(value)
        for expiry in ['2099-10-31T00:08:00Z', '2099-10-31T03:00:01Z', '2099-10-31T01:30:00']:
            value = fixture(); value['rows'][0]['expires_at'] = expiry
            value['source_registry']['records'][0]['expires_at'] = expiry
            with self.subTest(expiry=expiry): self.reject(_old._wire_reseal(value))

    def test_explicit_conditioning_is_not_a_new_general_permission(self):
        for field, changed in [('target', 'pass_att'), ('forecast_product', 'point_median'),
                ('method_id', 'UNREGISTERED_OTHER_METHOD'), ('position', 'RB')]:
            value = fixture(); value['rows'][0][field] = changed
            with self.subTest(field=field): self.reject(value)
        value = fixture(); value['catalog']['entries'][0]['conditional_on'] = 'played'
        self.reject(_old._wire_reseal(value))

    def test_history_is_retained_without_extending_validity(self):
        value = fixture(); original = deepcopy(value['rows'][0])
        value['created_at'] = '2099-10-31T04:00:00Z'
        value['rows'][0]['retained_capture'] = True
        wire.validate_feed(value)
        kept = deepcopy(value['rows'][0]); kept.pop('retained_capture'); original.pop('retained_capture')
        self.assertEqual(kept, original)
        self.assertLess(wire.clock(kept['expires_at']), wire.clock(value['created_at']))

    def test_legacy_wire_and_true_zero_prior_remain_honest(self):
        legacy = _old.fixture(); original = wire.canonical(legacy)
        wire.validate_feed(legacy); self.assertEqual(wire.canonical(legacy), original)
        value = fixture(); row = value['rows'][0]
        row.update(selected_projection=0., expected_mean=0., fallback=True, trained_prior_only=True,
            fallback_reason='fictional_prior_only', projection_label='Appearance-conditioned mean fallback',
            feature_max_source_available_utc=None)
        wire.validate_feed(value)
        row['selected_projection'] = None; self.reject(value)

    def test_exact_C_product_cannot_bypass_expiry_through_legacy_wire(self):
        value = _old.fixture()
        value['catalog']['entries'][0]['method_id'] = wire.APPEARANCE_METHOD
        value['rows'][0]['method_id'] = wire.APPEARANCE_METHOD
        self.reject(_old._wire_reseal(value))


if __name__ == '__main__':
    unittest.main()
