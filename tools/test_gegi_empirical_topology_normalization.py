"""Checks for matched Sobol proposals and transport through one shared atom."""

import unittest

import numpy as np
from scipy.stats import qmc

import gegi_empirical_topology_normalization as normalizer
from gegi_empirical_atom_sampling import sample_conditional_atom
from gegi_photon_continuation import PhotonRates, ELECTRON_REST_KEV


class EmpiricalTopologyNormalizationTests(unittest.TestCase):
    def test_retained_scrambles_and_nested_ninth_coordinate(self):
        old = qmc.Sobol(8, scramble=True, seed=3100).random_base2(5)
        draws = normalizer.sobol_draws(3100, 5)
        np.testing.assert_array_equal(draws[:, :8], old)
        np.testing.assert_array_equal(draws[:8], normalizer.sobol_draws(3100, 3))
        self.assertEqual(len(np.unique(draws[:, 8])), len(draws))
        self.assertTrue((draws[:, 8] >= 0.).all() and (draws[:, 8] < 1.).all())

    def test_shared_atom_sets_intermediate_and_second_scatter_rates(self):
        incident = 800.
        kernel = dict(incident_energies_keV=[incident], cosine_bin_centers=[-.5, .5],
                      native_metadata=dict(native_electron_rest_keV=510.99891),
                      incident_groups=[dict(livermore_bins=[
                          dict(development_angular_mass=.25, development_residual_atoms=[-.3]),
                          dict(development_angular_mass=.75, development_residual_atoms=[-.1, 0., .5])])])
        u = np.full((4, 9), .5)
        u[:, 8] = [.125, .375, .625, .875]
        intermediate, exiting = [], []

        def rate_at(e):
            intermediate.append(e)
            return PhotonRates(.2, .03, .1)

        def total(e):
            exiting.append(e)
            return .2

        physics, traces = normalizer.empirical_factors(u, kernel, incident, rate_at, total, (30., 900.))
        oracle = [sample_conditional_atom(kernel, incident, 0., v) for v in u[:, 8]]
        expected = np.array([r['outgoing_keV'] for r in oracle])
        np.testing.assert_array_equal(traces['intermediate_keV'], expected)
        np.testing.assert_array_equal(intermediate[:-1], expected)
        np.testing.assert_array_equal(exiting, expected/(1+expected/ELECTRON_REST_KEV))
        np.testing.assert_allclose(physics['first_angle'], [4*np.pi*r['angular_density_per_sr'] for r in oracle])
        np.testing.assert_allclose(traces['atom_conditional_mass'], 1.)
        self.assertEqual(physics['missing_bound_per_fraction'], 0.)


if __name__ == '__main__':
    unittest.main()
