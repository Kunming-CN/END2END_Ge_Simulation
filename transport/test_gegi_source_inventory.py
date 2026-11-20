"""Data parsing, lazy equilibrium inventory and native root record contracts."""
import copy
import json
import math
import unittest

import numpy as np
import gegi_source_inventory as I
import test_gegi_source as Legacy


def parameters():
    texts = {'cs137_decay': 'P 0 - 9.492526e8\nBetaMinus 0 1\nBetaMinus 0 - 5.3 1175.63\nBetaMinus 283.54 - 0.00058 892.09\nBetaMinus 661.659 - 94.699 513.971\n',
             'ba137_decay': 'P 661.659 - 153.12\nIT 0 1\n',
             'ba137_levels': '0 - 0 -1 1.5 0\n2 - 661.659 153.12 -5.5 1\n',
             'ensdf_states': '56 137 0 - -1 3 0\n56 137 661.659 - 2.209055e11 11 0\n'}
    return I.parameters_from_texts(texts, {'scope': 'synthetic parser fixture using the recorded values'})


class InventoryTests(unittest.TestCase):
    def test_native_normalization_lifetime_and_excited_ion_contract(self):
        value = parameters()
        self.assertEqual(value['feeding_probability'], 94.699/(5.3+.00058+94.699))
        self.assertEqual(value['mean_lifetime_ns'], 2.209055e11)
        self.assertEqual(value['lambda_per_ns'], 1./2.209055e11)
        self.assertEqual(value['expected_pdg'], 1000561371)
        self.assertEqual(I.gps_registration(value), ['/gps/particle ion', '/gps/ion 56 137 0 661.65899999999999'])
        self.assertNotIn('ionLvl', ' '.join(I.gps_registration(value)))

    def test_equilibrium_mean_and_finite_time_integral(self):
        value = I.contract(parameters())
        self.assertAlmostEqual(value['mean_initial_nuclei'], 185000*parameters()['feeding_probability']*220.9055)
        self.assertEqual(I.expected_initial_decays(value, 0), 0.)
        self.assertAlmostEqual(I.expected_initial_decays(value, 1.), value['initial_mean_decay_rate_per_s']*1e-9, places=12)
        self.assertAlmostEqual(I.expected_initial_decays(value, 1e14), value['mean_initial_nuclei'])

    def test_large_inventory_is_scalar_and_checkpoint_partition_invariant(self):
        contract = I.contract(parameters())
        first = I.initialize(contract, 20261120, 'inventory-test')
        self.assertGreater(first['initial_nuclei'], 30_000_000)
        self.assertLess(len(json.dumps(first)), 10000)
        whole, final = I.next_block(first, 2e6, 1000)
        split = []; state = json.loads(json.dumps(first))
        while True:
            rows, state = I.next_block(state, 2e6, 7)
            split.extend(rows)
            if not rows or state['pending_decay'] is not None: break
        self.assertEqual(whole, split)
        self.assertEqual(json.loads(json.dumps(final)), json.loads(json.dumps(state)))
        self.assertEqual(final['initial_nuclei'], final['remaining_nuclei']+final['generated_initial_daughter_decays'])
        self.assertEqual(first['generated_initial_daughter_decays'], 0)
        for row in whole:
            self.assertIsNone(row['parent_decay_id']); self.assertIsNone(row['new_parent_decay_id'])
            self.assertEqual(row['origin'], 'initial_daughter_inventory')

    def test_poisson_population_thinning_matches_nhpp_count_law(self):
        small = I.contract(parameters(), activity_bq=1.)
        small['mean_initial_nuclei'] = 12.
        stop = small['parameters']['mean_lifetime_ns']*.7
        expected = I.expected_initial_decays(small, stop)
        counts = []
        for seed in range(1200):
            rows, _ = I.next_block(I.initialize(small, seed, 'synthetic-statistical-check'), stop, 100)
            counts.append(len(rows))
        self.assertLess(abs(float(np.mean(counts))-expected), 5*math.sqrt(expected/len(counts)))
        self.assertLess(abs(float(np.var(counts, ddof=1))-expected), 5*expected*math.sqrt(2/(len(counts)-1)))

    def test_initial_ion_reader_checks_metastable_identity_and_reset_timing(self):
        fixture = Legacy.GeGILH5(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        def mutate(bundle):
            for particle in bundle['particles']: particle['particle'] = 1000561371
            for track in bundle['tracks']:
                if track['trackid'] == 1: track['particle'] = 1000561371
                if track['trackid'] == 2: track['particle'] = 1000561370
                if track['trackid'] == 4: track.update(parent_trackid=1, time=0.)
                if track['trackid'] == 5: track['time'] = .1
            for step in bundle['steps']:
                if step['trackid'] == 5: step['time'] = .5
        meta = fixture.fixture(mutate=mutate)
        params = parameters()
        meta['source_contract'] = I.daughter_contract(params, meta['source_position_global_mm'])
        meta['primary_vertex_time_ns'] = 0.
        def reader(rows, names, current): return I.validate_initial_tracks(rows, names, current, params)
        events = list(I_events(fixture.path, meta, reader))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]['truth_edep_keV'], 120.)


def I_events(path, meta, reader):
    import gegi_source as S
    return S.events(path, meta, primary_track_reader=reader)


if __name__ == '__main__': unittest.main()
