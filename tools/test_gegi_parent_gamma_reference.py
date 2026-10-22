"""Focused parent-interaction attribution boundaries; no scientific inputs."""
import unittest
import gegi_parent_gamma_reference as P


def track(tid, parent, particle, x=0., time=1., proc=1):
    return {'trackid': tid, 'parent_trackid': parent, 'particle': particle, 'xloc': x/1000,
        'yloc': 0., 'zloc': 0., 'time': time, 'procid': proc, 'ekin': 1.}


def event(tracks, tids):
    by_id = {t['trackid']: t for t in tracks}
    return {'input_group': {'parent_event_metadata': {'tracks': tracks}}, 'input_steps': [
        {'track_id': tid, 'particle_pdg': by_id[tid]['particle'], 'raw_row_index': i,
            'energy_keV': 2., 'position_mm': [i, 0., 0.], 'time_ns': .5} for i, tid in enumerate(tids)], 'steps': []}


class ParentReferenceTests(unittest.TestCase):
    def test_fluorescence_and_electron_brems_use_first_child(self):
        tracks = [track(1, 0, 22), track(2, 1, 11, x=2, proc=5),
            track(3, 1, 22, x=2, proc=5), track(4, 3, 11, x=8),
            track(5, 2, 22, x=9), track(6, 5, 11, x=12)]
        result = P.evaluate(event(tracks, [2, 4, 6]), {}, {'spatial_diagnostics': [], 'candidates': []})
        self.assertEqual(len(result['parent_interactions']), 1)
        self.assertEqual(result['parent_interactions'][0]['first_child_trackids'], [2, 3])
        self.assertEqual(result['parent_interactions'][0]['deposited_energy_keV'], 6.)

    def test_two_decay_roots_never_merge_and_direct_gamma_stays_unassigned(self):
        tracks = [track(1, 0, 1000280609), track(2, 1, 22), track(3, 1, 22),
            track(4, 2, 11), track(5, 3, 11)]
        result = P.evaluate(event(tracks, [4, 5, 2]), {}, {'spatial_diagnostics': [], 'candidates': []})
        self.assertEqual(len(result['root_gammas']), 2)
        self.assertEqual(len(result['parent_interactions']), 2)
        self.assertEqual(result['unassigned_interaction_energy_keV'], 2.)
        self.assertEqual(result['row_assignment_ledger'][-1]['unassigned_reason'], 'direct_root_gamma_deposit_no_child_birth')
        self.assertEqual(result['references']['ge5keV']['unknown_reason'], 'root_gamma_count_not_one')
        interactions = [{'deposited_energy_keV': 100., 'birth_time_ns': float(i), 'interaction_key': [i],
            'endpoint_x_input_keV': {i: 100.}, 'endpoint_y_input_keV': {i+18: 100.},
            'collector_cells': [{'cell': [i, i+18], 'energy_keV': 100.}]} for i in (1, 2)]
        small = P.reference(interactions, {2: 200.}, .2, [], 5.)
        self.assertEqual(small['status'], 'major_interaction_reference_with_small_unassigned')
        self.assertEqual(P.reference(interactions, {2: 200.}, 5., [], 5.)['unknown_reason'],
            'unassigned_energy_reaches_threshold')

    def test_missing_cycle_and_birth_fields_do_not_guess(self):
        self.assertEqual(P.ancestry(2, {2: track(2, 99, 11)})[2], 'missing_ancestor')
        self.assertEqual(P.ancestry(2, {2: track(2, 3, 11), 3: track(3, 2, 22)})[2], 'ancestry_cycle')
        tracks = [track(1, 0, 22), track(2, 1, 11)]; tracks[1].pop('time')
        result = P.evaluate(event(tracks, [2]), {}, {'spatial_diagnostics': [], 'candidates': []})
        self.assertEqual(result['parent_interactions'], [])
        self.assertEqual(result['row_assignment_ledger'][0]['unassigned_reason'], 'missing_child_birth_fields')


if __name__ == '__main__':
    unittest.main()
