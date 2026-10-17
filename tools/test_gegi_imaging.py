"""Small analytic checks for cone direction, ambiguity, depth and event weights."""
import copy
import math
import unittest
import gegi_imaging as G


class ImagingTests(unittest.TestCase):
    def test_known_ninety_degree_scatter(self):
        outgoing = 662/(1+662/G.ELECTRON_REST_KEV)
        first = {'position_mm': [0, 0, 0], 'energy_keV': 662-outgoing}
        second = {'position_mm': [10, 0, 0], 'energy_keV': outgoing}
        c = G.cone(first, second)
        self.assertAlmostEqual(c['half_angle_deg'], 90)
        self.assertEqual(c['axis'], [-1, 0, 0])
        self.assertAlmostEqual(sum(a*b for a, b in zip(c['axis'], [0, 0, 1])), c['cos_theta'])

    def test_invalid_cosine_is_rejected_not_clamped(self):
        self.assertIsNone(G.cone({'position_mm': [0, 0, 0], 'energy_keV': 600},
                                 {'position_mm': [10, 0, 0], 'energy_keV': 1}))

    def test_depth_interpolation_and_out_of_range(self):
        t = {'depth_mm': [-5, 0, 5], 'ctd_ns': [50, 0, -50]}
        self.assertEqual(G.depth_from_timing(25, t), -2.5)
        self.assertIsNone(G.depth_from_timing(60, t))
        self.assertIsNone(G.depth_from_timing(10, {'depth_mm': [-5, 0, 5], 'ctd_ns': [50, 0, 25]}))

    def test_backprojection_preserves_event_weight(self):
        c = {'axis': [0, 0, 1], 'half_angle_deg': 60, 'weight': .5}
        result = G.backproject([c, c], step_deg=10)
        integral = sum(sum(row)*area for row, area in zip(result['values'], result['solid_angle_per_cell_sr_by_row']))
        self.assertAlmostEqual(integral, 1., places=10)

    @staticmethod
    def sample():
        meta = [{'id': i, 'wiring_factor': 1 if i <= 17 else -1} for i in range(1, 35)]
        chans = []
        for i, e, t in ((7, 200., 70.), (11, 462., 80.), (24, 200., 60.), (29, 462., 60.)):
            chans.append({'contact_id': i, 'accepted': True, 'collection_candidate': True, 'reconstructed_energy_keV': e,
                          'final_induced_keV': e*(1 if i <= 17 else -1), 't50_ns': t})
        return {'event_id': 44, 'status': 'completed', 'truth_edep_keV': 662, 'channels': chans}, meta

    def test_truth_and_source_pose_not_used(self):
        event, meta = self.sample()
        table = {'depth_mm': [-5, 0, 5], 'ctd_ns': [-50, 0, 50]}
        original = G.reconstruct_event(event, meta, table, 662)
        changed = copy.deepcopy(event)
        changed.update(truth_edep_keV=1, truth_positions_mm=[[900, 900, 900]], truth_first_site=999)
        self.assertEqual(G.reconstruct_event(changed, meta, table, 662), original)
        self.assertEqual(original['status'], 'accepted')
        self.assertEqual(sum(c['weight'] for c in original['cones']), 1.)
        self.assertAlmostEqual(sum(s['energy_keV'] for s in original['sites']), 662.)

    def test_pairing_ambiguity_is_explicit(self):
        event, meta = self.sample()
        for c in event['channels']:
            c['reconstructed_energy_keV'] = 331.
            c['final_induced_keV'] = 331.*(1 if c['contact_id'] <= 17 else -1)
        result = G.reconstruct_event(event, meta, {'depth_mm': [-5, 0, 5], 'ctd_ns': [-50, 0, 50]}, 662)
        self.assertEqual(result['reason'], 'ambiguous_strip_pairing')
        self.assertEqual(result['cones'], [])


if __name__ == '__main__':
    unittest.main()
