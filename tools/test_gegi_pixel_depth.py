"""Check the portable center-depth table and its field-bound estimator."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import unittest

import gegi_pixel_depth as depth


ROOT = Path(__file__).resolve().parents[1]


class PixelDepthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = depth.load_calibration()
        cls.stamps = dict(source_identity={key: cls.table[key] for key in depth.FIELD_KEYS},
                          digital_profile_sha256=cls.table['digital_profile_sha256'],
                          digital_timing_sha256=cls.table['digital_timing_sha256'])

    def estimate(self, pixel, delay, **overrides):
        return depth.estimate_depth(self.table, *pixel, delay, 0, **(self.stamps | overrides))

    def test_bundled_table_census_provenance_and_historical_holdout_scope(self):
        raw = depth.CALIBRATION_PATH.read_bytes()
        self.assertEqual(self.table['calibration_sha256'], sha256(raw).hexdigest())
        canonical = json.dumps(json.loads(raw), sort_keys=True, allow_nan=False, separators=(',', ':')) + '\n'
        self.assertEqual(raw, canonical.encode('utf-8'))
        statuses = Counter(row['status'] for row in self.table['pixels'].values())
        self.assertEqual(sum(statuses.values()), 256)
        self.assertEqual(self.table['curve_status_counts'], dict(statuses))
        validation = self.table['off_center_validation']
        self.assertEqual((validation['pixels_checked'], validation['intended'], validation['estimated']), (16, 188, 150))
        source = self.table['provenance']['source_sha256']['tools/gegi_pixel_depth.py']
        self.assertEqual(source, sha256(Path(depth.__file__).read_bytes()).hexdigest())
        self.assertNotIn(b'.local', raw)
        self.assertNotIn(b'channel_signals', raw)

    def test_exact_endpoints_interpolation_and_unavailable_outside_support(self):
        pixel = (9, 26)
        row = self.table['pixels']['9:26']
        cfd, z = row['cfd_x_minus_y_ns'], row['z_mm']
        for index in (0, -1):
            estimate = self.estimate(pixel, cfd[index])
            self.assertEqual((estimate['status'], estimate['apparent_depth_mm']), ('estimated', z[index]))
            self.assertEqual(estimate['evidence_level'], 'local_independent_off_center_check')
        middle = self.estimate(pixel, (cfd[4] + cfd[5])/2)
        self.assertAlmostEqual(middle['apparent_depth_mm'], (z[4] + z[5])/2)
        outside = self.estimate(pixel, cfd[-1] + row['direction'])
        self.assertEqual(outside['status'], 'outside_calibrated_cfd_range')
        self.assertIsNone(outside['apparent_depth_mm'])

    def test_field_readout_and_missing_timing_admission(self):
        pixel = (9, 26)
        delay = self.table['pixels']['9:26']['cfd_x_minus_y_ns'][5]
        wrong = {'field_cache_sha256': 'f'*64}
        for expected, overrides in (('unconfirmed_field', {'source_identity': self.stamps['source_identity'] | wrong}),
                                    ('unconfirmed_field', {'source_identity': None}),
                                    ('readout_profile_mismatch', {'digital_timing_sha256': 'b'*64}),
                                    ('readout_profile_mismatch', {'digital_profile_sha256': 'b'*64})):
            with self.subTest(expected=expected, overrides=overrides):
                result = self.estimate(pixel, delay, **overrides)
                self.assertEqual(result['status'], expected)
                self.assertIsNone(result['apparent_depth_mm'])
                self.assertIsNone(result['evidence_level'])
        for bad in (None, True, float('inf')):
            self.assertEqual(self.estimate(pixel, bad)['status'], 'collector_cfd_unavailable')
        self.assertEqual(self.estimate((9, 17), delay)['status'], 'invalid_pixel')

    def test_center_only_and_unavailable_pixel_evidence_remain_distinct(self):
        center = next((key, row) for key, row in self.table['pixels'].items()
                      if row['status'] == 'available' and 'off_center_check' not in row)
        key, row = center
        estimate = self.estimate(tuple(map(int, key.split(':'))), row['cfd_x_minus_y_ns'][3])
        self.assertEqual(estimate['evidence_level'], 'center_calibration_only')
        for key, row in self.table['pixels'].items():
            if row['status'] != 'available':
                result = self.estimate(tuple(map(int, key.split(':'))), 0)
                self.assertEqual(result['status'], row['status'])
                self.assertIsNone(result['apparent_depth_mm'])
                self.assertIsNone(result['evidence_level'])

    @unittest.skipUnless((ROOT/'.local/gegi-pixel-cfd-depth/all-pixels.json').is_file(),
                         'sealed local replay evidence unavailable')
    def test_regeneration_from_sealed_measurements_and_reused_curves(self):
        import gegi_build_pixel_depth_calibration as build
        import gegi_pixel_cfd_depth_study as study
        prior = study.scan.Inputs().read(build.PRIOR, build.PRIOR_SHA)
        report = json.loads((ROOT/'.local/gegi-pixel-cfd-depth/all-pixels.json').read_bytes())
        rebuilt = build.frozen_curves(prior)
        for pixel in report['extended_pixels']:
            rebuilt[tuple(pixel['contact_ids'])] = study.fit_curve(pixel['center_measurements'])
        self.assertEqual(report['calibration_sha256'], self.table['calibration_sha256'])
        self.assertEqual(self.table['pixels'], {f'{x}:{y}': curve for (x, y), curve in rebuilt.items()})
        for row in prior['validation']:
            estimate = depth.estimate_depth(self.table, *row['measured_contact_ids'],
                                            *row['collector_cfd50_ns'], **self.stamps)
            self.assertEqual((estimate['status'], estimate['apparent_depth_mm']),
                             (row['estimate_status'], row['estimated_z_mm']))


if __name__ == '__main__':
    unittest.main()
