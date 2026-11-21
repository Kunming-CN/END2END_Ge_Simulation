import unittest

import numpy as np
from scipy.stats import qmc

import gegi_ideal_two_interaction_mass as ideal
import gegi_shared_topology_normalization as shared
from gegi_photon_continuation import PhotonRates


class SharedTopologyNormalizationTests(unittest.TestCase):
    def test_cached_proposal_replays_original_sample_array_for_each_source(self):
        cube = np.vstack((np.eye(3),-np.eye(3))),np.full(6,10.)
        u = qmc.Sobol(8,scramble=True,seed=3100).random_base2(6)
        energy,support = 661.657,(150.,700.)
        rate_at = lambda _:PhotonRates(.1,.02,.06)
        total = lambda _: .1
        factors = shared.energy_factors(u,[energy],rate_at,total,support)
        covered_missing_mass = False
        for source in np.array([[0.,0.,0.],[0.,0.,10000.]]):
            expected,hits,fraction,bound = ideal.ray_weights(cube,source,energy,rate_at,total,support,u)
            ray = shared.first_rays(cube,source,u)
            actual, new_bound = shared.cached_exact_weights(cube,ray,factors[energy])
            self.assertTrue(hits.any())
            self.assertEqual(fraction,ray['fraction'])
            np.testing.assert_array_equal(ray['hit'],hits)
            np.testing.assert_array_equal(actual,expected)
            covered_missing_mass |= bool(actual[:,3].sum())
            self.assertAlmostEqual(new_bound,bound,places=14)
        self.assertTrue(covered_missing_mass)


if __name__=='__main__':
    unittest.main()
