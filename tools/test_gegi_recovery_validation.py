"""Targeted contracts for the frozen event split and posthoc error accounting."""
import copy
import unittest
import numpy as np
import gegi_recovery_validation as V


def view(eid, reason='candidate', stratum='2:2', group=0):
    return {'campaign_initial_id': eid, 'reason': reason, 'stratum': stratum,
            'group_key': [0, eid, group], 'metadata_sha256': str(eid)}


class ValidationTests(unittest.TestCase):
    def test_sample_is_order_independent_and_closes_original_events(self):
        rows = [view(e, stratum='1:2' if e % 2 else '2:2') for e in range(100)]
        rows += [view(e, 'other', group=1) for e in range(10)]
        first = V.select(rows, 5)
        self.assertEqual(first, V.select(list(reversed(rows)), 5))
        V.check_disjoint(first['groups'])
        ids = {a['campaign_initial_id'] for a in first['assignments']}
        self.assertEqual(len(first['groups']), sum(r['campaign_initial_id'] in ids for r in rows))
        for counts in first['targets'].values():
            self.assertLessEqual(max(counts['selected'].values()), 5)

    def test_small_class_halves_and_multiple_groups_cannot_leak(self):
        rows = [view(e) for e in range(5)] + [view(0, 'rare', group=1)]
        selected = V.select(rows)
        self.assertEqual(selected['targets']['candidate']['selected'], {'development': 3, 'holdout': 2})
        event_zero = [g for g in selected['groups'] if g['campaign_initial_id'] == 0]
        self.assertEqual(len(event_zero), 2)
        self.assertEqual(len({g['split'] for g in event_zero}), 1)
        bad = copy.deepcopy(event_zero); bad[1]['split'] = 'holdout' if bad[0]['split'] == 'development' else 'development'
        with self.assertRaisesRegex(ValueError, 'crosses'):
            V.check_disjoint(bad)

    def test_selection_allowlist_ignores_truth_pose_and_energy(self):
        record = {'original_identity': {'campaign_initial_id': 7, 'chunk_index': 0,
                  'raw_primary_id': 7, 'pulse_group_id': 0, 'metadata_sha256': 'abc'},
                  'native_status': 'completed', 'reconstruction': {'reason': 'ambiguous',
                  'candidates': [1], 'strip_counts': [2, 3], 'energy_keV': 99}}
        expected = V.selection_view(record)
        record.update(truth_edep_keV=1000, source_position=[1, 2, 3])
        record['reconstruction']['energy_keV'] = 10000
        record['original_identity']['source_group'] = 'changed'
        self.assertEqual(expected, V.selection_view(record))

    def test_pairing_splitting_residual_and_unknown_are_separate(self):
        h = {'sites': [{'x_contact': 1, 'y_contact': 18, 'position_mm': [0, 0, 1], 'energy_keV': 11},
                       {'x_contact': 2, 'y_contact': 18, 'position_mm': [1, 0, 0], 'energy_keV': 5}]}
        sites = [{'energy': 20, 'processes': {'compt'}}]
        cells = {(1, 18): [10, np.array([0, 0, 0])], (3, 18): [10, np.array([0, 0, 0])]}
        r = V.evaluate_hypothesis(h, sites, 0, cells)
        self.assertFalse(r['endpoint_pairing_matches'])
        self.assertTrue(r['false_gamma_anchor_splitting'])
        self.assertEqual(r['unsupported_predicted_cells'], 1)
        self.assertEqual(r['missing_endpoint_cells'], 1)
        self.assertEqual(r['matched_cell_residuals'][0]['abs_depth_mm'], 1)
        self.assertEqual(r['matched_cell_residuals'][0]['energy_error_keV'], 1)
        unknown = V.evaluate_hypothesis(h, sites, 6, {})
        self.assertIsNone(unknown['endpoint_pairing_matches'])
        self.assertIsNone(unknown['false_gamma_anchor_splitting'])

    def test_sequence_without_timing_is_unknown(self):
        sites = [{'photon_id': 1, 'position': [0, 0, 0], 'processes': {'compt'}, 'x': {1: 5}, 'y': {18: 5}},
                 {'photon_id': 1, 'position': [1, 0, 0], 'processes': {'phot'}, 'x': {2: 5}, 'y': {18: 5}}]
        event = {'input_group': {'parent_event_metadata': {'tracks': [
            {'particle': 11, 'parent_trackid': 1, 'xloc': 0, 'yloc': 0, 'zloc': 0}]}}}
        order, reason = V.sequence_truth(event, sites, 0)
        self.assertIsNone(order)
        self.assertEqual(reason, 'anchor_birth_time_unavailable')

    def test_failed_raw_steps_preserve_truth_anchors_but_endpoints_unknown(self):
        tracks = [{'trackid': 1, 'parent_trackid': 0, 'particle': 22},
                  {'trackid': 2, 'parent_trackid': 1, 'particle': 11,
                   'xloc': 0, 'yloc': 0, 'zloc': 0, 'procid': 4}]
        raw_step = {'track_id': 2, 'particle_pdg': 11, 'energy_keV': 20,
                    'position_mm': [0, 0, 0], 'raw_row_index': 9}
        event = {'status': 'native_failed', 'input_steps': [raw_step],
                 'steps': [raw_step], 'input_group': {'parent_event_metadata': {'tracks': tracks}}}
        original = copy.deepcopy(event)
        result, known = V.posthoc_topology(event, {4: 'compt'})
        self.assertFalse(known)
        self.assertEqual(len(result[0]), 1)
        self.assertEqual(result[0][0]['energy'], 20)
        self.assertEqual(dict(result[6]), {})
        self.assertEqual(event, original)
        # Invalid completed native rows must remain visible, rather than silently
        # being treated like the documented failed/null schema.
        event['status'] = 'completed'
        with self.assertRaises(KeyError):
            V.posthoc_topology(event, {4: 'compt'})


if __name__ == '__main__':
    unittest.main()
