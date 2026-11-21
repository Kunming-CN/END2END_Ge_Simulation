"""Support bounds for the continuous cosine and discrete residual mixture."""

import unittest

from gegi_compton_energy_kernel import free_outgoing
from gegi_empirical_energy_support import ELECTRON_REST_KEV, missing_ranges, support


class EmpiricalEnergySupportTests(unittest.TestCase):
    def test_analytic_hat_endpoints_preserve_disjoint_energy_support(self):
        e0, m = 800., 510.99891
        receipt = dict(incident_energies_keV=[e0], cosine_bin_centers=[-.5, .5],
                       native_metadata=dict(native_electron_rest_keV=m),
                       incident_groups=[dict(livermore_bins=[
                           dict(development_angular_mass=.25, development_residual_atoms=[-.9],
                                development_sample_indices=[12]),
                           dict(development_angular_mass=.75, development_residual_atoms=[.5],
                                development_sample_indices=[17])])])
        got = support(receipt, e0)
        expected = [[free_outgoing(e0, -1., m)*(1-.9), free_outgoing(e0, .5, m)*(1-.9)],
                    [e0-.5*(e0-free_outgoing(e0, -.5, m)), e0]]
        self.assertEqual(got['outgoing_support_closure_keV'], expected)
        escaped = [[a/(1+2*a/ELECTRON_REST_KEV), b] for a, b in expected]
        self.assertEqual(got['second_outgoing_support_closure_keV'], escaped)
        self.assertEqual(got['minimum']['development_sample_index'], 12)
        self.assertEqual(got['second_backscatter_minimum_keV'], escaped[0][0])
        self.assertEqual(missing_ranges(escaped, 100., e0),
                         dict(below_table_keV=[escaped[0]], above_table_keV=[]))
        self.assertEqual(support(receipt, 661.657)['status'], 'incident_energy_unrepresented')


if __name__ == '__main__':
    unittest.main()
