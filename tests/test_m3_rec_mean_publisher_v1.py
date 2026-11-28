"""Fictional complete admission-to-wire tests; no NFL inference or release."""
from pathlib import Path
import sys
import tempfile
import unittest
import hashlib

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'tools')]
from test_m3_rec_mean_admission_v1 import AdmissionFixture, t
import m3_rec_mean_admission_v1 as admission
import m3_rec_mean_publisher_v1 as publisher
import stat_point_mae_public_v2 as wire


class ShadowPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = AdmissionFixture(self.root)
        self.f.deliver()

    def publish(self, at='19:45', *, fetch=None, native=True):
        f = self.f
        return publisher.numerical_shadow(self.root, f.manifest_path, f.inspection_path,
            f.registration, f.envelope_path, 124, 'shadow-typed',
            native_body=f.native_path if native else None,
            fetch=fetch or f.fetch, now=lambda: t(at))

    def feed(self, result):
        value = wire.strict_json((self.root / result['immutable_feed']).read_bytes())
        return wire.validate_feed(value)

    def test_real_inspection_and_authenticated_capture_reach_closed_numerical_wire(self):
        result = self.publish()
        feed = self.feed(result)
        self.assertEqual(result['rows'], 2)
        body=(self.root / result['immutable_feed']).read_bytes()
        self.assertEqual(hashlib.sha256(body).hexdigest(), result['feed_sha256'])
        self.assertEqual(Path(result['immutable_feed']).name, result['feed_sha256']+'.json')
        self.assertEqual(len(body), result['feed_bytes'])
        self.assertEqual(feed['schema_version'], wire.EXPIRING_FEED)
        self.assertEqual(feed['catalog']['entries'][0]['method_id'], admission.PRODUCT)
        original = self.f.get(self.f.envelope_path)['rows']
        for row, old in zip(feed['rows'], original):
            self.assertEqual(row['selected_projection'], old['expected_mean'])
            self.assertEqual(row['expected_mean'], old['expected_mean'])
            self.assertEqual(row['projection_label'], 'Appearance-conditioned mean')
            self.assertEqual(row['conditional_on'], 'observed_statistical_appearance_v1')
            self.assertEqual(row['issued_at'], old['issued_UTC'])
            self.assertEqual(row['expires_at'], old['expires_UTC'])
            self.assertFalse(row['fallback'])
            self.assertIsNone(row['functional_proof'])
            self.assertFalse({'probability', 'confidence', 'ev', 'actual', 'features', 'trees'} & set(row))
        self.assertAlmostEqual(feed['rows'][0]['expected_mean'], .95 * 1.5 + .05 * 1, places=12)
        self.assertAlmostEqual(feed['rows'][1]['expected_mean'], .95 * 1.5 + .05 / 3, places=12)

    def test_existing_live_pointer_and_rankings_are_untouched(self):
        sentinels = ['output/data/weekly-mae-display.json', 'output/data/weekly-selected-rankings.json',
                     'output/data/week.json']
        for name in sentinels:
            p = self.root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'old original bytes')
        result = self.publish()
        self.assertFalse(result['live_pointer_written'])
        self.assertFalse(result['primary_activation'])
        self.assertFalse(result['ranking_policy_change'])
        self.assertFalse(result['direction_policy_change'])
        for name in sentinels:
            self.assertEqual((self.root / name).read_bytes(), b'old original bytes')

    def test_later_shadow_export_retains_expired_pregame_original_and_later_readback(self):
        result = self.publish(at='21:00')
        feed = self.feed(result)
        self.assertEqual(result['retention_disposition'], 'EXPIRED_ORIGINAL_RETAINED')
        self.assertFalse(result['current_use_allowed'])
        self.assertEqual(result['new_forecasts_generated'], 0)
        self.assertEqual(result['outcomes'], 'NOT_SUPPLIED_UNGRADED')
        for row in feed['rows']:
            self.assertTrue(row['retained_capture'])
            self.assertEqual(row['issued_at'], '2026-12-01T19:35:00Z')
            self.assertEqual(row['readback_completed_at'], '2026-12-01T21:00:00Z')
            self.assertEqual(row['expires_at'], '2026-12-01T19:55:00Z')

    def test_slow_real_readback_crossing_expiry_uses_completion_clock(self):
        instant = [t('19:54')]
        def delayed_fetch(url, cap, raw=False):
            response = self.f.fetch(url, cap, raw)
            if '/RUN.json?' in url:
                instant[0] = t('20:01')
            return response
        f = self.f
        result = publisher.numerical_shadow(self.root, f.manifest_path, f.inspection_path,
            f.registration, f.envelope_path, 124, 'shadow-typed', native_body=f.native_path,
            fetch=delayed_fetch, now=lambda: instant[0])
        feed = self.feed(result)
        self.assertFalse(result['current_use_allowed'])
        self.assertEqual(result['prepared_at'], '2026-12-01T20:01:00Z')
        self.assertEqual(feed['created_at'], '2026-12-01T20:01:00Z')
        self.assertEqual(feed['rows'][0]['readback_completed_at'], '2026-12-01T20:01:00Z')
        self.assertEqual(feed['rows'][0]['issued_at'], '2026-12-01T19:35:00Z')

    def test_source_limited_shadow_is_never_primary_or_current_permission(self):
        result = self.publish(native=False)
        self.feed(result)
        self.assertEqual(result['state'], 'DELIVERED_SHADOW_SOURCE_LIMITED')
        self.assertFalse(result['current_use_allowed'])
        self.assertFalse(result['primary_activation'])
        self.assertIn('raw response remains owner-local', result['primary_blocker'])

    def test_actual_model_mutated_after_inspection_cannot_mint_wire_capabilities(self):
        f = self.f
        def changing_fetch(url, cap, raw=False):
            result = f.fetch(url, cap, raw)
            if '/RUN.json?' in url:
                path = self.root / f.m['model']['path']
                path.write_bytes(path.read_bytes() + b'tampered')
            return result
        with self.assertRaisesRegex(ValueError, 'WIRE_INPUT_CHANGED_AFTER_CAPTURE'):
            self.publish(fetch=changing_fetch)
        self.assertEqual({p.name for p in (self.root / 'shadow-typed').glob('*.json')}, {'SHADOW_CAPTURE.json'})
        self.assertFalse((self.root / 'output/data/weekly-mae-display.json').exists())

    def test_untrusted_owner_cannot_create_wire_despite_valid_numeric_body(self):
        url = f'https://api.github.com/repos/{admission.WEBSITE}/issues/comments/124'
        comment = admission.parse(self.f.responses[url]); comment['user']['id'] = 123
        self.f.responses[url] = admission.canonical(comment)
        with self.assertRaisesRegex(ValueError, 'AUTHENTIC_UNEDITED_WEBSITE_OWNER_REQUIRED'):
            self.publish()
        self.assertFalse((self.root / 'shadow-typed').exists())

    def test_immutable_original_and_publication_asset_are_not_overwritten(self):
        result = self.publish()
        before = (self.root / result['immutable_feed']).read_bytes()
        with self.assertRaises((FileExistsError, ValueError)):
            self.publish()
        self.assertEqual((self.root / result['immutable_feed']).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
