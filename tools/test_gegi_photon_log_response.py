"""Check finite log densities and unchanged raw photon-response output."""

import math
import unittest

import numpy as np

import gegi_photon_continuation as photon
import gegi_photon_observed_energy as measured
import gegi_point_source_response as point
from gegi_photon_log_response import gaussian_log_density_per_kev


def raw_view(value):
    if isinstance(value, dict):
        return {k: raw_view(v) for k, v in value.items()
                if not k.startswith('log_') and not k.endswith('_density_status')}
    if isinstance(value, list):
        return [raw_view(v) for v in value]
    return value


class PhotonLogResponseTests(unittest.TestCase):
    def setUp(self):
        self.crystal = (np.vstack((np.eye(3), -np.eye(3))), np.full(6, 12.))
        self.ray = self.crystal, [0., 0., 0.], [2., 0., 0.]

    def test_same_positive_quadrature_and_raw_gaussian_agree_where_representable(self):
        rate = photon.PhotonRates(.15, .025, .1)
        args = (*self.ray, 300., rate, lambda _:.15, [120., 370.])
        options = dict(sigma_keV=20., azimuth_samples=12, energy_order=32)
        raw = measured.observed_continuation(*args, **options)
        stable = measured.observed_continuation(*args, include_log=True, **options)
        self.assertEqual(raw, raw_view(stable))
        for row in stable['observations']:
            for branch in ('absorption', 'escape'):
                field = branch + '_per_mm_observed_keV'
                self.assertGreater(row[field], 0.)
                self.assertAlmostEqual(math.exp(row['log_'+field])/row[field], 1., places=12)
                self.assertEqual(row[branch+'_density_status'], 'positive_raw_density')

    def test_raw_zero_tails_keep_finite_logs_and_zero_rate_is_separate(self):
        arguments = (*self.ray, 300.)
        options = dict(sigma_keV=2., azimuth_samples=12, energy_order=64, include_log=True)
        rate = photon.PhotonRates(.15, .025, .1)
        positive = measured.observed_continuation(*arguments, rate, lambda _:.15, [900.], **options)
        row = positive['observations'][0]
        for branch in ('absorption', 'escape'):
            field = branch+'_per_mm_observed_keV'
            self.assertEqual(row[field], 0.)
            self.assertTrue(math.isfinite(row['log_'+field]))
            self.assertEqual(row[branch+'_density_status'], 'raw_density_underflow')
        log_expected = math.log(rate.photoelectric_per_mm)-.3+gaussian_log_density_per_kev(900., 300., 2.)
        self.assertEqual(row['log_absorption_per_mm_observed_keV'], log_expected)
        self.assertEqual(len(row['log_escape_endpoint_knots_keV']), 4)
        self.assertLess(row['log_escape_quadrature_difference'], 1e-3)
        zero = measured.observed_continuation(*arguments, photon.PhotonRates(.15, 0., 0.), lambda _:.15, [900.], **options)
        for branch in ('absorption', 'escape'):
            row = zero['observations'][0]
            self.assertIsNone(row['log_'+branch+'_per_mm_observed_keV'])
            self.assertEqual(row[branch+'_density_status'], 'zero_physical_channel_rate')

    def test_ge_survival_and_escape_factors_do_not_underflow_before_taking_log(self):
        rate = photon.PhotonRates(500., .02, .1)
        report = measured.observed_continuation(*self.ray, 300., rate, lambda _:500., [110.], sigma_keV=10.,
                                                azimuth_samples=8, energy_order=32, include_log=True)
        row = report['observations'][0]
        self.assertEqual(report['no_interaction_survival'], 0.)
        self.assertEqual(row['escape_per_mm_observed_keV'], 0.)
        self.assertTrue(math.isfinite(row['log_escape_per_mm_observed_keV']))
        self.assertEqual(row['escape_density_status'], 'raw_density_underflow')

    def test_first_site_underflow_does_not_zero_the_point_source_log_response(self):
        rate = photon.PhotonRates(.15, .025, .1)
        args = (self.crystal, [-4., 0., 0.], [0., 0., 0.], [2., 0., 0.], 800., 180., 120., lambda _:rate, lambda _:.15)
        options = dict(sigma_first_keV=2., sigma_second_keV=20., azimuth_samples=12, energy_order=48)
        raw = point.point_source_response(*args, **options)
        stable = point.point_source_response(*args, include_log=True, **options)
        self.assertEqual(raw, raw_view(stable))
        self.assertEqual(stable['first_measurement_density_per_keV'], 0.)
        self.assertEqual(stable['first_measurement_density_status'], 'raw_density_underflow')
        for branch in ('absorption', 'escape'):
            self.assertEqual(stable[f'{branch}_per_mm3_observed_keV2'], 0.)
            self.assertTrue(math.isfinite(stable[f'log_{branch}_per_mm3_observed_keV2']))
            self.assertEqual(stable[branch+'_density_status'], 'raw_density_underflow')


if __name__ == '__main__':
    unittest.main()
