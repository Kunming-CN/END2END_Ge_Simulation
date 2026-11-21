"""Analytic normalization and free-limit checks for the empirical joint measure."""

import math
import unittest

import numpy as np

import gegi_compton_energy_kernel as energy
import gegi_empirical_compton_joint as model


class EmpiricalComptonJointTests(unittest.TestCase):
    def setUp(self):
        self.incident = 800.
        self.receipt = dict(
            incident_energies_keV=[self.incident], cosine_bin_centers=[-.5, .5],
            native_metadata={'native_electron_rest_keV': 510.99891},
            incident_groups=[{'livermore_bins': [
                dict(development_angular_mass=.25, development_residual_atoms=[-.3]),
                dict(development_angular_mass=.75, development_residual_atoms=[-.1, .0, .5])]}])

    def test_joint_cosine_solid_angle_and_discrete_energy_mass(self):
        angular = model.angular_model(self.receipt, self.incident)
        np.testing.assert_array_equal(angular['hat_areas'], [1., 1.])
        # Midpoint integration is exact on each linear segment. Integrate
        # angular density times the entire discrete energy measure over dΩ.
        a, b = angular['x'][:-1], angular['x'][1:]
        mass = []
        for c, width in zip((a+b)/2, b-a, strict=True):
            result = model.joint_nodes(self.receipt, self.incident, c, angular)
            mass.append(2*math.pi*width*result['angular_density_per_sr']*math.fsum(result['weights']))
        self.assertAlmostEqual(math.fsum(mass), 1., places=14)
        np.testing.assert_allclose(model.angular_cdf(angular, [-1., 0., 1.]), [0., .3125, 1.])

    def test_posterior_shares_change_while_atom_roster_is_exact(self):
        result = model.joint_nodes(self.receipt, self.incident, 0.)
        old = energy.conditional_nodes(self.receipt, self.incident, 0.)
        np.testing.assert_array_equal(result['outgoing_energies_keV'], old['outgoing_energies_keV'])
        np.testing.assert_array_equal(result['weights'], [.25]*4)
        self.assertEqual(result['baseline_angular_bin_weights'], [(0, .5), (1, .5)])
        self.assertEqual(result['angular_bin_weights'], [(0, .25), (1, .75)])
        self.assertIsNone(model.joint_nodes(self.receipt, 661.657, 0.)['weights'])

    def test_free_electron_delta_energy_limit_and_uniform_angular_limit(self):
        for b in self.receipt['incident_groups'][0]['livermore_bins']:
            b['development_residual_atoms'] = [0.]*len(b['development_residual_atoms'])
            b['development_angular_mass'] = .5
        for c in (-1., -.1, 0., .75, 1.):
            result = model.joint_nodes(self.receipt, self.incident, c)
            e = energy.free_outgoing(self.incident, c, self.receipt['native_metadata']['native_electron_rest_keV'])
            np.testing.assert_array_equal(result['outgoing_energies_keV'], np.full(len(result['weights']), e))
            self.assertEqual(result['angular_bin_weights'], result['baseline_angular_bin_weights'])
            self.assertAlmostEqual(result['angular_density_per_sr'], 1/(4*math.pi), places=14)


if __name__ == '__main__':
    unittest.main()
