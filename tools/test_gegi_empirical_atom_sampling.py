"""Check inverse-CDF selection and the resulting angular-energy measure."""

import math
import unittest

import numpy as np

from gegi_empirical_atom_sampling import sample_conditional_atom
from gegi_empirical_compton_joint import angular_model, joint_nodes


class EmpiricalAtomSamplingTests(unittest.TestCase):
    def setUp(self):
        self.line = 1173.228
        self.kernel = dict(incident_energies_keV=[self.line], cosine_bin_centers=[-.5, .5],
                           native_metadata=dict(native_electron_rest_keV=510.99891),
                           incident_groups=[dict(livermore_bins=[
                               dict(development_angular_mass=.25, development_residual_atoms=[-.3]),
                               dict(development_angular_mass=.75, development_residual_atoms=[-.1, 0., .5])])])
        self.model = angular_model(self.kernel, self.line)

    def test_draws_share_attenuation_atom_and_joint_angular_density(self):
        angular_energy_mass = []
        edges = self.model['x']
        for a, b in zip(edges[:-1], edges[1:], strict=True):
            cosine = (a+b)/2
            atoms = joint_nodes(self.kernel, self.line, cosine, self.model)
            cumulative = np.r_[0., np.cumsum(atoms['weights'])]
            drew = [sample_conditional_atom(self.kernel, self.line, cosine, u, self.model)
                    for u in (cumulative[:-1]+cumulative[1:])/2]
            np.testing.assert_array_equal([r['outgoing_keV'] for r in drew], atoms['outgoing_energies_keV'])
            self.assertEqual([r['atom_index'] for r in drew], list(range(len(drew))))
            mass_per_sr = math.fsum(r['conditional_atom_mass']*r['angular_density_per_sr'] for r in drew)
            angular_energy_mass.append(2*math.pi*(b-a)*mass_per_sr)
        self.assertAlmostEqual(math.fsum(angular_energy_mass), 1., places=14)

    def test_uniform_endpoint_and_unrepresented_incident_energy(self):
        last = sample_conditional_atom(self.kernel, self.line, 0., np.nextafter(1., 0.), self.model)
        self.assertEqual(last['atom_index'], 3)
        with self.assertRaisesRegex(ValueError, 'atom coordinate'):
            sample_conditional_atom(self.kernel, self.line, 0., 1., self.model)
        with self.assertRaisesRegex(ValueError, 'physical scattering cosine'):
            sample_conditional_atom(self.kernel, self.line, 1.1, 0., self.model)
        absent = sample_conditional_atom(self.kernel, 661.657, 0., 0.)
        self.assertEqual(absent['status'], 'incident_energy_unrepresented')
        self.assertIsNone(absent['outgoing_keV'])


if __name__ == '__main__':
    unittest.main()
