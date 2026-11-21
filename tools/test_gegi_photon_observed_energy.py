import math
import unittest

import numpy as np
from scipy.integrate import quad

import gegi_photon_continuation as photon
import gegi_photon_observed_energy as measured


class ObservedPhotonEnergyTests(unittest.TestCase):
    def setUp(self):
        self.crystal = (np.vstack((np.eye(3), -np.eye(3))), np.full(6, 10.))
        self.ray = (self.crystal, [0., 0., 0.], [2., 0., 0.], 300.)

    def test_gaussian_measure_and_required_width(self):
        sigma, energy = 2., 300.
        mass = quad(lambda x: measured.gaussian_density_per_kev(x, energy, sigma), energy-12*sigma, energy+12*sigma)[0]
        self.assertAlmostEqual(mass, 1., places=12)
        with self.assertRaisesRegex(ValueError, 'explicit positive Gaussian width'):
            measured.gaussian_density_per_kev(energy, energy, 0.)

    def test_absorption_and_transparent_escape_preserve_their_path_masses(self):
        rates = photon.PhotonRates(.15,.025,.1)
        for sigma in (.03,2.,40.):
            with self.subTest(sigma=sigma):
                result = measured.observed_continuation(*self.ray, rates, lambda _:0., [300.],
                                                        sigma_keV=sigma, azimuth_samples=12)
                survival = math.exp(-.3)
                masses = result['observed_integrated_mass_per_mm']
                self.assertAlmostEqual(masses['absorption'], survival*.025, places=12)
                self.assertAlmostEqual(masses['escape'], survival*.1, places=11)
                self.assertAlmostEqual(result['observations'][0]['absorption_per_mm_observed_keV'],
                                       survival*.025/(math.sqrt(2*math.pi)*sigma), places=12)

    def test_narrow_measurement_returns_the_escape_continuum_density(self):
        rates = photon.PhotonRates(.15,.025,.1)
        expected = photon.continuation(*self.ray, rates, outgoing_keV=220., outgoing_total_per_mm=.05, azimuth_samples=64)
        result = measured.observed_continuation(*self.ray, rates, lambda _:.05, [80.], sigma_keV=.001, azimuth_samples=64)
        actual = result['observations'][0]['escape_per_mm_observed_keV']
        self.assertAlmostEqual(actual, expected['resolved_escape_density_per_mm_keV'], places=10)
        self.assertLess(result['observed_integrated_mass_per_mm']['escape'], result['pre_escape_Compton_path_mass_per_mm'])

    def test_initialized_total_interpolation_retains_anchors_and_bounds(self):
        lookup = measured.total_rate_interpolator({100.:photon.PhotonRates(.2,.05,.1), 400.:photon.PhotonRates(.05,.01,.03)})
        self.assertEqual(lookup(100.), .2)
        self.assertAlmostEqual(lookup(200.), .1)
        with self.assertRaisesRegex(ValueError, 'outside'):
            lookup(99.)


if __name__ == '__main__':
    unittest.main()
