"""Independent probability-mass and physical-kernel checks for the new rule."""

import math
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr

import gegi_gaussian_escape_quadrature as fast
import gegi_photon_continuation as photon
import gegi_photon_observed_energy as frozen


class GaussianEscapeQuadratureTests(unittest.TestCase):
    def test_constant_integrates_full_gaussian_interval(self):
        log_value, log_mass, count = fast.integrate_log_spectrum(lambda _: math.log(13.), -1., 3., 1., 2., 8)
        self.assertAlmostEqual(math.exp(log_mass), ndtr(1.)-ndtr(-1.), places=15)
        self.assertAlmostEqual(log_value-log_mass, math.log(13.), places=15)
        self.assertEqual(count, 16)

    def test_exponential_rescaling_independently_checks_extreme_tail_mass(self):
        for obs in (-1000., 1000.):
            nodes, weights, log_mass = next(fast.gaussian_segments(-1., 1., obs, 1., 16))
            self.assertTrue(np.all((-1. <= nodes) & (nodes <= 1.)))
            self.assertTrue(np.all(weights > 0))
            scaled = quad(lambda d: math.exp(-999*d-d*d/2), 0., 2., epsabs=1e-15)[0]
            expected = math.log(scaled)-999**2/2-math.log(2*math.pi)/2
            self.assertAlmostEqual(log_mass, expected, places=8)
            self.assertEqual(math.exp(log_mass), 0.)

    def test_frozen_physical_kernel_at_both_endpoints(self):
        crystal = (np.vstack((np.eye(3), -np.eye(3))), np.full(6, 12.))
        rate = photon.PhotonRates(.15, .025, .1)
        e0, sigma = 320., 2.
        e_min, _ = photon.outgoing_energy_model(e0)
        args = (crystal, [0., 0., 0.], [2., 0., 0.], e0, rate, lambda _: .15)
        for y in (0., e0-e_min):
            original = frozen.observed_continuation(*args, [y], sigma_keV=sigma, azimuth_samples=32,
                                                    energy_order=128, include_log=True)['observations'][0]
            result = fast.observed_escape(*args, y, sigma_keV=sigma, azimuth_samples=32, energy_order=32)
            self.assertAlmostEqual(result['log_escape_per_mm_observed_keV'],
                                   original['log_escape_per_mm_observed_keV'], delta=.001)


if __name__ == '__main__':
    unittest.main()
