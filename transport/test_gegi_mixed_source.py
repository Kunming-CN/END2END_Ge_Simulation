"""Fresh-source clock/input/identity checks; synthetic fixtures do not run physics."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gegi_mixed_source as M
import test_gegi_source as L


class MixedSourceContracts(unittest.TestCase):
    def test_schedule_has_one_fixed_chronological_clock_and_correct_mark_position(self):
        config = M.default_config()
        first = list(M.parent_schedule(config)); second = list(M.parent_schedule(config))
        self.assertEqual(first, second)
        self.assertEqual([p['parent_decay_id'] for p in first], list(range(100)))
        self.assertTrue(all(a['absolute_parent_time_ns'] < b['absolute_parent_time_ns']
                            for a, b in zip(first, first[1:])))
        self.assertGreater(first[0]['absolute_parent_time_ns'], 0)
        sources = {s['id']: s for s in config['sources']}
        self.assertEqual({p['source_id'] for p in first}, set(sources))
        for parent in first:
            self.assertEqual(parent['source_position_global_mm'], sources[parent['source_id']]['position_global_mm'])
        self.assertEqual(config['initial_state']['initial_daughter_populations'], {})

    def test_combined_generator_consumes_the_predefined_both_source_schedule_once(self):
        config = M.default_config(); plan = {'config': config, 'cryostat_contract': M.S.G.load_cryostat()}
        text = M.macro(plan)
        for line in ('/RMG/Generator/Select FromFile', '/RMG/Generator/FromFile/IncludePosition true',
                     '/RMG/Generator/FromFile/FileName primaries.lh5', '/run/beamOn 100',
                     '/RMG/Processes/Stepping/DaughterNucleusMaxLifetime -1 ns'):
            self.assertIn(line, text)
        self.assertEqual(text.count('/run/beamOn'), 1)
        self.assertIn('/gps/ion 55 137', text); self.assertIn('/gps/ion 27 60', text)
        self.assertLess(text.index('/RMG/Generator/FromFile/IncludePosition true'),
                        text.index('/RMG/Generator/FromFile/FileName primaries.lh5'))
        self.assertNotIn('/run/beamOn', M.macro(plan, True))

    def test_invalid_or_undeclared_initial_states_and_large_runs_fail(self):
        for change in ({'primary_count': 501}, {'primary_count': True}, {'initial_state': {}},
                       {'sources': M.default_config()['sources'][:1]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                list(M.parent_schedule(dict(M.default_config(), **change)))

    def test_lh5_input_binds_pdg_time_position_and_one_at_rest_parent(self):
        try: import h5py
        except ImportError: self.skipTest('Use locked transport Python for native LH5 checks')
        parents = list(M.parent_schedule(M.default_config()))
        with tempfile.TemporaryDirectory(dir=M.h.ROOT/'.local') as temp:
            path = Path(temp)/'primaries.lh5'; M.write_primaries(path, parents)
            with h5py.File(path) as raw:
                table = raw['vtx/kin']
                self.assertEqual(table['g4_pid'].dtype.itemsize, 4)
                self.assertEqual(table['time'].dtype.itemsize, 8)
                self.assertEqual(list(table['g4_pid']), [p['source_pdg'] for p in parents])
                self.assertEqual(list(table['time']), [p['absolute_parent_time_ns'] for p in parents])
                self.assertEqual(table['time'].attrs['units'], 'ns')
                self.assertTrue(all(table['ekin'][:] == 0)); self.assertTrue(all(table['n_part'][:] == 1))
                for j, axis in enumerate(('x', 'y', 'z')):
                    self.assertEqual(list(table[axis+'loc']), [p['source_position_global_mm'][j]/1000 for p in parents])


class MixedLH5(L.GeGILH5):
    # Reuse only fixture helpers; the inherited tests also guard the unchanged reader.
    def test_mixed_reader_preserves_native_delays_and_source_identity(self):
        config = M.default_config(primary_count=2)
        parents = list(M.parent_schedule(config))
        # The first two fixed marks happen to be Cs137. Force the second mark in
        # this synthetic fixture to exercise both readers without new physics.
        parents[1].update(source_id=M.S.CO60, isotope='Co60', source_pdg=1000270600,
                          source_position_global_mm=[40., 0., 40.])
        def mutate(bundle):
            for eid, parent in enumerate(parents):
                position = parent['source_position_global_mm']
                vertex = bundle['vertices'][eid]
                vertex.update(time=parent['absolute_parent_time_ns'],
                              **dict(zip(('xloc', 'yloc', 'zloc'), [p/1000 for p in position])))
                bundle['particles'][eid]['particle'] = parent['source_pdg']
                for track in bundle['tracks']:
                    if track['evtid'] != eid: continue
                    if track['parent_trackid'] == 0:
                        track.update(particle=parent['source_pdg'], time=parent['absolute_parent_time_ns'],
                                     **dict(zip(('xloc', 'yloc', 'zloc'), [p/1000 for p in position])))
                    if eid == 1:
                        if track['trackid'] == 2: track['particle'] = 1000280600
                        if track['trackid'] == 4: track['time'] = 0.
                        if track['trackid'] == 5: track['time'] = .1
                if eid == 1: bundle['steps'][-1]['time'] = .5
        meta = self.fixture(M.S.CS137, mutate)
        meta['source_id'] = M.SOURCE
        cryostat = meta['cryostat_contract']
        contracts = [M.S.source_contract({'source': source['id'], 'source_position_mm': source['position_global_mm']}, cryostat)
                     for source in config['sources']]
        meta['checked'] = {'config': config, 'sources': [{'contract': c} for c in contracts]}
        with patch.object(M, 'parent_schedule', return_value=iter(parents)):
            events = list(M.events(self.path, meta))
        self.assertEqual([e['source_id'] for e in events], [M.S.CS137, M.S.CO60])
        self.assertEqual(events[0]['steps'], [])
        self.assertEqual(events[1]['truth_edep_keV'], 120.)
        for event in events:
            parent_time = event['absolute_parent_time_ns']
            self.assertEqual(event['primary_time_ns'], parent_time)
            for row in event['steps']:
                self.assertEqual(row['absolute_time_ns'], parent_time+row['time_ns'])
                self.assertEqual(row['deposit_id'], ['fresh100', event['event_id'], row['raw_row_index']])


if __name__ == '__main__': unittest.main()
