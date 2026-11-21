"""Focused conditional energy-kernel and mass accounting checks."""

import unittest

import numpy as np

import gegi_compton_energy_kernel as kernel


class ComptonEnergyKernelTests(unittest.TestCase):
    def setUp(self):
        self.receipt = dict(incident_energies_keV=[662.], native_metadata={'native_electron_rest_keV': 510.99891},
                            cosine_bin_centers=[-.5, .5], incident_groups=[{'livermore_bins': [
                                {'development_residual_atoms': [-.5, .4]}, {'development_residual_atoms': [-.3, .2]}]}])

    def test_neighbors_mix_full_mass_with_bound_preserving_residuals(self):
        result = kernel.conditional_nodes(self.receipt, 662., 0.)
        self.assertEqual(result['angular_bin_weights'], [(0, .5), (1, .5)])
        self.assertEqual(result['weights'].tolist(), [.25]*4)
        f = result['free_outgoing_keV']
        np.testing.assert_allclose(result['outgoing_energies_keV'], [.5*f, f+.4*(662.-f), .7*f, f+.2*(662.-f)])
        for theta in (-1., 1.):
            endpoint = kernel.conditional_nodes(self.receipt, 662., theta)
            self.assertTrue(all(0. < e <= 662. for e in endpoint['outgoing_energies_keV']))
            self.assertEqual(float(endpoint['weights'].sum()), 1.)
        backwards = kernel.conditional_nodes(self.receipt, 662., -1.)
        self.assertLess(backwards['outgoing_energies_keV'][0], backwards['free_outgoing_keV'])

    def test_numerical_curve_interval_marks_unsupported_weight_without_renormalization(self):
        nominal = kernel.conditional_nodes(self.receipt, 662., 0.)
        scoped = kernel.conditional_nodes(self.receipt, 662., 0., curve_support_keV=(nominal['free_outgoing_keV'], 662.))
        self.assertEqual(scoped['covered_mask'].tolist(), [False, True, False, True])
        self.assertEqual((scoped['covered_mass'], scoped['uncovered_mass']), (.5, .5))
        np.testing.assert_array_equal(scoped['weights'], nominal['weights'])
        np.testing.assert_array_equal(scoped['outgoing_energies_keV'], nominal['outgoing_energies_keV'])

    def test_exact_incident_energy_and_missing_angle_bin_are_explicit(self):
        rejected = kernel.conditional_nodes(self.receipt, 661.657, 0.)
        self.assertEqual(rejected['status'], 'incident_energy_unrepresented')
        self.assertIsNone(rejected['outgoing_energies_keV'])
        self.receipt['incident_groups'][0]['livermore_bins'][1]['development_residual_atoms'] = []
        unsupported = kernel.conditional_nodes(self.receipt, 662., 0.)
        self.assertEqual(unsupported['status'], 'missing_angular_bin')
        self.assertIsNone(unsupported['weights'])
        self.assertEqual(unsupported['angular_bin_weights'], [(0, .5), (1, .5)])

    def test_split_and_reference_crps_of_discrete_distribution(self):
        samples = [(i, -.25, 300., False) for i in range(10)]
        ((training, holdout),) = kernel.separated_samples(samples, [-1., 1.])
        self.assertEqual([i for i, *_ in holdout], [0, 5])
        self.assertEqual(set(training)|set(holdout), set(samples))
        self.assertFalse(set(training)&set(holdout))
        # The analytic CRPS definition uses two independent draws from the nodes.
        trial = kernel.conditional_nodes(self.receipt, 662., -.25)
        x, w = trial['outgoing_energies_keV'], trial['weights']
        want = w @ np.abs(x-300.) - .5*(w @ np.abs(x[:, None]-x) @ w)
        cases = kernel.heldout_predictions(self.receipt, 662., holdout)
        self.assertAlmostEqual(cases[0][0], want, places=12)


if __name__ == '__main__':
    unittest.main()
