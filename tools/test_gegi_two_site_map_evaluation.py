"""Focused identity and photon-vertex assignment checks; no science inputs."""
import unittest
from collections import Counter
import numpy as np
import gegi_two_site_map_evaluation as M


class MapEvaluationTests(unittest.TestCase):
    def test_ancestry_retains_tiny_anchor_and_direct_row(self):
        tracks = [{'trackid': 1, 'parent_trackid': 0, 'particle': 22},
            {'trackid': 2, 'parent_trackid': 1, 'particle': 11, 'xloc': .001, 'yloc': 0., 'zloc': 0.},
            {'trackid': 3, 'parent_trackid': 0, 'particle': 11}]
        event = {'input_group': {'parent_event_metadata': {'tracks': tracks}}, 'input_steps': [
            {'track_id': 2, 'particle_pdg': 11, 'position_mm': [2., 0., 0.], 'energy_keV': .1, 'raw_row_index': 8},
            {'track_id': 3, 'particle_pdg': 11, 'position_mm': [3., 0., 0.], 'energy_keV': 2., 'raw_row_index': 9}]}
        result = M.anchor_identity_map(event)
        self.assertEqual(result['unmapped_positive_rows'], 1)
        self.assertEqual(result['contributing_recorded_photon_ids_all_positive_energy'], [1])
        self.assertEqual(result['anchors_all_positive_energy'][0]['deposited_energy_keV'], .1)
        self.assertEqual(result['anchors_all_positive_energy'][0]['birth_position_mm'], [1., 0., 0.])
        self.assertEqual(result['anchors_all_positive_energy'][0]['deposition_centroid_mm'], [2., 0., 0.])

    def test_vertex_assignment_requires_exact_existing_cell_mapping(self):
        result = {'candidates': [{'hypothesis_index': 0}], 'hypotheses': [{'hypothesis_index': 0, 'sites': [
            {'x_contact': 1, 'y_contact': 18, 'position_mm': [1., 1., 1.], 'energy_keV': 100.},
            {'x_contact': 2, 'y_contact': 19, 'position_mm': [4., 4., 4.], 'energy_keV': 200.}]}]}
        sites = [{'position': [0., 0., 0.], 'x': Counter({1: 100}), 'y': Counter({18: 100})},
            {'position': [3., 3., 3.], 'x': Counter({2: 200}), 'y': Counter({19: 200})}]
        cells = {(1, 18): [100., np.array([50., 50., 50.])], (2, 19): [200., np.array([700., 700., 700.])]}
        rows = M.spatial_diagnostics(result, sites, cells, [(1, 18), (2, 19)], None, True)
        self.assertEqual(rows[0]['photon_interaction_vertex'][0]['position_error_xyz_mm'], [1., 1., 1.])
        self.assertEqual(rows[0]['charge_deposition_centroid'][0]['position_error_xyz_mm'], [.5, .5, .5])
        rows = M.spatial_diagnostics(result, sites, cells, None, 'multiple_anchors_share_cell', True)
        self.assertIsNone(rows[0]['photon_interaction_vertex'])
        self.assertEqual(rows[0]['photon_vertex_unknown_reason'], 'multiple_anchors_share_cell')
        result['hypotheses'][0]['sites'][1]['x_contact'] = 3
        rows = M.spatial_diagnostics(result, sites, cells, [(1, 18), (2, 19)], None, True)
        self.assertIsNone(rows[0]['photon_interaction_vertex'])
        self.assertEqual(rows[0]['photon_vertex_unknown_reason'], 'predicted_cells_not_exact_reference_pair')


if __name__ == '__main__':
    unittest.main()
