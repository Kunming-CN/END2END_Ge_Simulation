"""Check the batched positive reference and unknown-atom accounting."""

import unittest

import numpy as np

import gegi_batched_escape_quadrature as batch
import gegi_empirical_measured_grid as measured
import gegi_photon_observed_energy as frozen
from gegi_photon_continuation import PhotonRates


class EmpiricalMeasuredGridTests(unittest.TestCase):
    def test_batched_rule_matches_frozen_positive_underflow(self):
        crystal = (np.vstack((np.eye(3), -np.eye(3))), np.full(6, 12.))
        m = dict(first_fitted_mm=[0., 0., 0.], second_fitted_mm=[2., 1., .2],
                 measured_second_site_keV=1000., sigma_second_keV=2.)
        rate = PhotonRates(.18, .03, .1)
        new = batch.checked_evaluator(m, crystal, lambda _: rate, lambda _: .18, 16)(320., 64)
        old = frozen.observed_continuation(crystal, m['first_fitted_mm'], m['second_fitted_mm'],
                 320., rate, lambda _: .18, [m['measured_second_site_keV']], sigma_keV=2.,
                 azimuth_samples=16, energy_order=64, include_log=True)['observations'][0]
        self.assertEqual(new['density_status'], 'raw_density_underflow')
        self.assertAlmostEqual(new['log_escape_density'], old['log_escape_per_mm_observed_keV'], places=9)

    def test_missing_escape_retains_conditional_mass(self):
        incident = 800.
        kernel = dict(incident_energies_keV=[incident], cosine_bin_centers=[0.],
                      native_metadata=dict(native_electron_rest_keV=510.99891),
                      incident_groups=[dict(livermore_bins=[
                          dict(development_angular_mass=1., development_residual_atoms=[-.1, .1])])])
        rates = np.log([50., 800.]), np.log([.03, .03]), np.log([.15, .15])
        values, unknown = measured.branch_factors(kernel, incident, np.array([-.2, .8]), 2., 300., 2.,
                             dict(measured_second_site_keV=400., sigma_second_keV=2.), [], rates)
        np.testing.assert_array_equal(unknown, [1., 1.])
        self.assertTrue(np.isfinite(values[0]).all())
        self.assertTrue(np.isnan(values[1]).all())


if __name__ == '__main__':
    unittest.main()
