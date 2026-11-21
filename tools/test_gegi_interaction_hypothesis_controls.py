import json
import unittest

import gegi_interaction_hypothesis_controls as control
import gegi_incident_geometry as geometry
import gegi_joint_two_site as joint


class HypothesisControlsTests(unittest.TestCase):
    def test_center_interpolation_gives_a_distinct_same_cell_split(self):
        depths, energies = control.linear_depth_split(-.75, 400., joint.DEPTH_MM)
        self.assertEqual(depths, (-1., 0.))
        self.assertEqual(energies, (300., 100.))
        self.assertEqual(sum(z*energy for z, energy in zip(depths, energies))/sum(energies), -.75)
        self.assertIsNone(control.linear_depth_split(-1., 400., joint.DEPTH_MM))

    def test_both_hypotheses_share_vertices_and_keep_original_orders(self):
        positions = [[1., 2., 3.], [4., 2., 3.]]
        kinematics = json.loads(json.dumps(geometry.escape_geometry([200., 250.], [661.657], positions)))
        original = [dict(order=[0, 1], nominal_mass=.4), dict(order=[1, 0], nominal_mass=.6)]
        pair = dict(kinematics=kinematics, original_plane_pairing={'orders': original},
                    saved_waveform_positions_mm=positions)
        orders = control.paired_orders(pair)
        self.assertEqual([order['site_index_order'] for order in orders], [[0, 1], [1, 0]])
        self.assertEqual([order['original_projection'] for order in orders], original)
        forward = orders[0]
        absorption, escape = forward['absorption']['cone'], forward['resolved_escape'][0]['cone']
        for field in ('axis', 'vertex_mm', 'second_site_mm', 'site_separation_mm'):
            self.assertEqual(absorption[field], escape[field])
        self.assertNotEqual(absorption['half_angle_deg'], escape['half_angle_deg'])


if __name__ == '__main__':
    unittest.main()
