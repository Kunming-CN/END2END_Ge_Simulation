"""Independent checks of the ideal-model forward draws."""

import unittest

import numpy as np
from scipy.integrate import quad

import gegi_ideal_forward_sample as forward
from gegi_photon_continuation import PhotonRates, cosine_density


class IdealForwardSampleTests(unittest.TestCase):
    def test_kn_draws_agree_with_normalized_cosine_marginal(self):
        incident = 1173.228
        rng = np.random.default_rng(261101771)
        draws = [forward.draw_compton(rng, incident) for _ in range(6000)]
        self.assertTrue(all(0 < e <= incident and 0 <= x < 2 and 0 <= phi < 2*np.pi for e, x, phi in draws))
        expected = quad(lambda x: cosine_density(incident, x), 0., 1.)[0]
        observed = sum(x < 1. for _, x, _ in draws)/len(draws)
        descriptive_se = np.sqrt(expected*(1-expected)/len(draws))
        self.assertLess(abs(observed-expected), 5*descriptive_se)

    def test_untruncated_path_with_competing_rates(self):
        rng = np.random.default_rng(261101772)
        rates = PhotonRates(.21, .05, .14)
        n, length = 12000, 4.
        categories = [forward.flight(rng, rates, length)[0] for _ in range(n)]
        exit_prob = np.exp(-rates.total_per_mm*length)
        for label, expected in [('exit', exit_prob), ('photoelectric', (1-exit_prob)*.05/.21),
                                ('compton', (1-exit_prob)*.14/.21), ('other', (1-exit_prob)*.02/.21)]:
            se = np.sqrt(expected*(1-expected)/n)
            self.assertLess(abs(categories.count(label)/n-expected), 5*se)


if __name__ == '__main__':
    unittest.main()
