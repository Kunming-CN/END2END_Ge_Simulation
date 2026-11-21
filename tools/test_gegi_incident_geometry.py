"""Analytic and saved-fit checks for conditional finite-vertex escape cones."""

import math
import unittest

import gegi_incident_geometry as geometry
from gegi_incident_hypotheses import ELECTRON_REST_KEV


def orders(ledger, line=0):
    return ledger['incident_line_hypotheses'][line]['two_resolved_scatter_escape_orders']


class IncidentGeometryTests(unittest.TestCase):
    def test_right_angle_uses_incident_energy_and_each_order_uses_its_own_vertex(self):
        incident = 1000.
        energy_after = 1/(1/incident + 1/ELECTRON_REST_KEV)
        positions = [[10., -3., 5.], [10., -3., 9.]]
        ledger = geometry.escape_geometry([incident-energy_after, 90.], [incident, 1100.], positions)
        forward, reverse = (row['cone'] for row in orders(ledger))
        self.assertEqual(forward['vertex_mm'], positions[0])
        self.assertEqual(reverse['vertex_mm'], positions[1])
        self.assertEqual(forward['axis'], [0., 0., -1.])
        self.assertEqual(reverse['axis'], [0., 0., 1.])
        self.assertEqual(forward['site_separation_mm'], 4.)
        self.assertAlmostEqual(forward['half_angle_deg'], 90.)
        self.assertAlmostEqual(geometry.angular_residual_deg(forward, [20., -3., 5.]), 0.)
        self.assertAlmostEqual(geometry.angular_residual_deg(forward, [20., -3., -5.]), -45.)
        self.assertLess(orders(ledger, 1)[0]['cone']['half_angle_deg'], forward['half_angle_deg'])
        self.assertIsNone(ledger['unresolved_or_mixed']['direction'])
        with self.assertRaisesRegex(ValueError, 'undefined at the cone vertex'):
            geometry.angular_residual_deg(forward, positions[0])

    def test_inadmissible_energy_and_unavailable_axes_carry_no_cones(self):
        energies = [730., 90.]
        coincident = geometry.escape_geometry(energies, [1000.], [[1., 2., 3.], [1., 2., 3.]])
        missing = geometry.escape_geometry(energies, [1000.], None)
        self.assertEqual(orders(coincident)[0]['geometry_status'], 'coincident_fitted_positions')
        self.assertEqual(orders(missing)[0]['geometry_status'], 'no_saved_waveform_positions')
        for ledger in (coincident, missing):
            self.assertTrue(orders(ledger)[0]['nominally_admissible'])
            self.assertEqual(orders(ledger)[1]['geometry_status'], 'nominal_escape_inadmissible')
            self.assertTrue(all(row['cone'] is None for row in orders(ledger)))
        original = geometry.escape_geometry(None, [1000.], None, unavailable='energy_incompatible')
        self.assertEqual(original['status'], 'energy_incompatible')
        self.assertIsNone(original['unresolved_or_mixed']['direction'])

    def test_escape_can_use_saved_positions_even_if_original_absorption_order_was_invalid(self):
        positions = [[1., 2., 3.], [4., 6., 3.]]
        fitted = {'index': 1, 'cells': [[8, 23], [9, 25]], 'fit': {
            'fits': {'waveform': {'center': {'optimizer_success': True, 'positions_mm': positions}}}}}
        original = {'site_energies_keV': [730., 90.],
                    'orders': [{'order': [1, 0], 'status': 'projected', 'nominal_mass': 1.}]}
        pair = geometry.pairing_geometry(fitted, original, 'center', [1000.])
        self.assertEqual(pair['original_plane_pairing'], original)
        forward, reverse = orders(pair['kinematics'])
        self.assertTrue(forward['nominally_admissible'])
        self.assertFalse(reverse['nominally_admissible'])
        self.assertEqual(forward['cone']['axis'], [-.6, -.8, 0.])
        self.assertAlmostEqual(math.hypot(*forward['cone']['axis']), 1.)
        self.assertNotIn('nominal_mass', forward['cone'])


if __name__ == '__main__':
    unittest.main()
