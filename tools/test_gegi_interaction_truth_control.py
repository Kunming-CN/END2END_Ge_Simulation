"""Check signed source residuals and deposit-control support on fixed geometry."""

import math
import unittest

from gegi_imaging import ELECTRON_REST_KEV
from gegi_interaction_truth_control import FULL_ENERGY, arm, site_control


class InteractionTruthControlTests(unittest.TestCase):
    def test_arm_uses_axis_toward_source_and_preserves_residual_sign(self):
        remaining = 1 / (1 / 1000 + (1 - .5) / ELECTRON_REST_KEV)
        points = [[0., 0., 0.], [2., 0., 0.]]
        energies = [1000 - remaining, remaining]
        source = [-.5, math.sqrt(.75), 0.]
        self.assertAlmostEqual(arm(points, energies, source)['signed_arm_deg'], 0.)
        self.assertAlmostEqual(arm(points, energies, [-1., 0., 0.])['signed_arm_deg'], -60.)
        self.assertAlmostEqual(arm(points, energies, [0., 1., 0.])['signed_arm_deg'], 30.)
        self.assertEqual(arm(points, [1000., .001], source)['status'], 'no_supported_cone')

    def test_deposit_energy_control_requires_full_absorption_and_keeps_photon_vertices(self):
        first, second = [0., 0., 0.], [2., 0., 0.]
        sites = [{'cell': cell,
                  'photon_step': {'pre_position_mm': start, 'post_position_mm': end, 'raw_row_index': row},
                  'cell_deposit_centroid_mm': [end[0], .2, 0.], 'interaction_deposit_centroid_mm': end,
                  'interaction_deposited_energy_keV': 330., 'cell_deposited_energy_keV': 331.}
                 for cell, start, end, row in (([3, 19], [-1., 0., 0.], first, 16),
                                               ([8, 25], first, second, 17))]
        pairing = {'sites': [{'x_contact_id': s['cell'][0], 'y_contact_id': s['cell'][1], 'energy_keV': 331.}
                             for s in sites[::-1]]}
        prior = {'fit': {'fits': {'waveform': {'center': {'positions_mm': [second, first],
                                                        'optimizer_success': True, 'modeled_cfd_available': True}}}}}
        full = site_control(sites, prior, pairing, [1, 0], [-1., 0., 0.], FULL_ENERGY, 662.)
        partial = site_control(sites, prior, pairing, [1, 0], [-1., 0., 0.], 'incomplete', 1332.)
        self.assertEqual(full['scored_photon_step_rows'], [16, 17])
        self.assertEqual(full['positions_mm_in_photon_order']['photon_vertex'], [first, second])
        self.assertEqual(full['positions_mm_in_photon_order']['waveform_center'], [first, second])
        self.assertEqual(full['ge_photon_turn_deg'], 0.)
        self.assertIsNone(full['photon_kinetic_energy_at_vertices_keV'])
        self.assertEqual(full['energies_keV_in_photon_order']['interaction_deposit'], [330., 330.])
        self.assertEqual(list(partial['energies_keV_in_photon_order']), ['measured_slow'])


if __name__ == '__main__':
    unittest.main()
