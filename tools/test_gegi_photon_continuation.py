import math
import unittest

import numpy as np
from scipy.integrate import quad

from gegi_photon_continuation import (PhotonRates, azimuth_survival, continuation, exit_distance_mm,
    outgoing_density_per_keV, solid_angle_density_per_sr, ELECTRON_REST_KEV)


class PhotonContinuationTests(unittest.TestCase):
    def test_normalized_klein_nishina_in_both_measures(self):
        for energy in (154.8, 283.2, 661.657, 1332.492):
            with self.subTest(energy=energy):
                minimum = energy/(1+2*energy/ELECTRON_REST_KEV)
                polar = quad(lambda c: 2*math.pi*solid_angle_density_per_sr(energy, c), -1, 1)[0]
                transformed = quad(lambda e: outgoing_density_per_keV(energy, e), minimum, energy)[0]
                self.assertAlmostEqual(polar, 1., places=10)
                self.assertAlmostEqual(transformed, 1., places=10)
                self.assertEqual(outgoing_density_per_keV(energy, .99*minimum), 0.)
                self.assertEqual(outgoing_density_per_keV(energy, 1.01*energy), 0.)

    def test_box_exits_and_single_direction_escape(self):
        crystal = (np.vstack((np.eye(3), -np.eye(3))), np.array([45.,45.,5.5]*2))
        np.testing.assert_allclose(exit_distance_mm(crystal, [1., 2., -3.], np.eye(3)), [44., 43., 8.5])
        self.assertAlmostEqual(azimuth_survival(crystal, [1., 2., -3.], [0., 0., 1.], 1., .1, samples=16),
                               math.exp(-.85))
        self.assertEqual(azimuth_survival(crystal, [0.,0.,0.], [0.,0.,1.], .3, 0., samples=16), 1.)

    def test_conditional_path_and_energy_factors_have_explicit_units(self):
        crystal = (np.vstack((np.eye(3), -np.eye(3))), np.array([10.]*6))
        branch = continuation(crystal, [0., 0., 0.], [2., 0., 0.], 300., PhotonRates(.15,.025,.1),
                              outgoing_keV=180., outgoing_total_per_mm=0.)
        self.assertAlmostEqual(branch['photoelectric_path_density_per_mm'], math.exp(-.3)*.025)
        self.assertAlmostEqual(branch['resolved_escape_density_per_mm_keV'],
                               math.exp(-.3)*.1*outgoing_density_per_keV(300.,180.))


if __name__ == '__main__':
    unittest.main()
