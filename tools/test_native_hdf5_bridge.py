"""Focused bridge contract/mutation tests against read-only saved inputs."""
import copy
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

import h5py
import native_hdf5_bridge as B


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index = 1
        while (B.BASE/f'tests-{index:03d}').exists():
            index += 1
        cls.root = B.BASE/f'tests-{index:03d}'
        cls.root.mkdir()
        cls.fixture = B.BASE/f'test-contracts-{index:03d}'
        if cls.fixture.exists():
            raise ValueError('Test fixture name already exists')
        cls.receipt = B.build(cls.fixture)
        cls.docs = {m: B.read(cls.fixture/(m+'.json')) for m in B.A.MODELS}
        print('TEST_FIXTURE '+B.relative(cls.fixture), flush=True)

    def doc(self, model='AK02'):
        return copy.deepcopy(self.docs[model])

    def positive(self, d):
        return next(e for e in d['events'] if e['namespace'] == B.MILLION and not e['zero_ge'])

    def test_census_and_exact_roundtrip(self):
        B.verify(self.fixture)
        self.assertEqual([self.docs[m]['selected_census']['initial_primaries'] for m in B.A.MODELS], [10, 13])
        self.assertEqual([self.docs[m]['selected_census']['groups'] for m in B.A.MODELS], [9, 13])
        self.assertEqual(sum(d['selected_census']['initial_primaries'] for d in self.docs.values()), 23)
        for d in self.docs.values():
            self.assertEqual(d['selected_census']['zero_ge_primaries'], 1)
            self.assertEqual(d['input_population_reference']['initial_primaries'], 1000000)
            self.assertIsNone(d['nonselected_response'])
            self.assertEqual(d['diagnostic_census']['primaries'], 1)

    def test_wrong_model_range_units(self):
        for key, value in [('model_id', 'GeGI'), ('model_sha256', '0'*64), ('units', {})]:
            d = self.doc(); d[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): B.validate_contract(d)
        d = self.doc(); self.positive(d)['identity']['local_primary_id'] = 10000
        with self.assertRaises(ValueError): B.validate_contract(d)

    def test_coordinate_alias_and_transform(self):
        for key in ('position_mm', 'pre_position_mm', 'post_position_mm', 'global_position_m'):
            d = self.doc(); self.positive(d)['steps'][0][key][0] += 0.01
            with self.subTest(key=key), self.assertRaises(ValueError): B.validate_contract(d)
        d = self.doc(); d['prepared']['coordinate_transform']['translation_global_mm'][0] += 1
        with self.assertRaises(ValueError): B.validate_contract(d)

    def test_delays_energy_zeros_ids(self):
        mutations = [lambda e: e['pulse_groups'][0]['relative_times_ns'].__setitem__(0, 2),
                     lambda e: e['steps'][0].__setitem__('energy_keV', 1.23),
                     lambda e: e.__setitem__('zero_ge', True),
                     lambda e: e.__setitem__('seed_event_id', 999),
                     lambda e: e['steps'][0]['raw'].__setitem__('evtid', 999),
                     lambda e: e['steps'][0].__setitem__('raw_row_index', 999),
                     lambda e: e.__setitem__('ge_energy_keV', 0)]
        for number, mutate in enumerate(mutations):
            d = self.doc(); mutate(self.positive(d))
            with self.subTest(mutation=number), self.assertRaises(ValueError): B.validate_contract(d)

    def test_multi_group_preserved(self):
        d = self.doc('SAP22')
        e = next(e for e in d['events'] if len(e['pulse_groups']) == 2)
        self.assertEqual([g['group_id'] for g in e['pulse_groups']], [0, 1])
        self.assertTrue(set(e['pulse_groups'][0]['row_indices']).isdisjoint(e['pulse_groups'][1]['row_indices']))
        e['pulse_groups'].pop()
        with self.assertRaises(ValueError): B.validate_contract(d)

    def test_namespace_and_original_failures(self):
        for m, eid in [('AK02', 8432), ('SAP22', 8413)]:
            d = self.doc(m); e = next(e for e in d['events'] if e['namespace'] == B.OLD)
            original = B.read(B.ROOT/e['historical_record'])
            self.assertEqual(e['event_id'], eid)
            self.assertEqual(e['steps'], original['original_event']['steps'])
            self.assertIsNone(original['pulse']['final_induced_keV'])
            self.assertIsNone(original['pulse']['readout'])
            e['namespace'] = 'mixed'
            with self.assertRaises(ValueError): B.validate_contract(d)

    def test_seed_reordering_and_chunk_collision(self):
        events = [e for d in self.docs.values() for e in d['events']]
        get = lambda seq: {(e['namespace'], e['identity']['model_id'], e['event_id'], s['raw_row_index']):
                          B.parcel_seed(e['seed_event_id'], s['raw_row_index'], 1)
                          for e in seq for s in e['steps']}
        self.assertEqual(get(events), get(list(reversed(events))))
        self.assertNotEqual(B.parcel_seed(7, 55, 1), B.parcel_seed(10007, 55, 1))
        self.assertEqual(B.parcel_seed(8432, 150, 1), 13733843045326248232)

    def test_explicit_selection_bounds(self):
        reps = B.read(B.ANALYSIS/'representative-events.json')
        self.assertEqual(B.choose(reps, {'AK02': [10001, 0], 'SAP22': [9]}), {'AK02': [0, 10001], 'SAP22': [9]})
        for bad in ({'AK02': [1]}, {'AK02': [1, 1], 'SAP22': [0]},
                    {'AK02': list(range(65)), 'SAP22': [0]}, {'AK02': [-1], 'SAP22': [0]},
                    {'AK02': [1000000], 'SAP22': [0]}):
            with self.assertRaises(ValueError): B.choose(reps, bad)

    def test_compact_model_range_hash_and_units(self):
        d = self.docs['AK02']; c = d['chunks'][0]
        ids = d['selected_global_primary_ids']
        original = B.ROOT/c['compact_path']
        for label, attr, value in [('model', 'model_id', 'SAP22'), ('range', 'global_offset', 10000),
                                   ('hash', 'raw_sha256', '0'*64)]:
            path = self.root/(label+'.h5'); shutil.copyfile(original, path)
            with h5py.File(path, 'r+') as f: f.attrs[attr] = value
            with self.subTest(label=label), self.assertRaises(ValueError):
                B.extract_selected(path, c['plan'], d['prepared'], c['raw_sha256'], ids)
        path = self.root/'units.h5'; shutil.copyfile(original, path)
        with h5py.File(path, 'r+') as f: f['details/stp/germanium/xloc'].attrs['units'] = 'mm'
        with self.assertRaises(ValueError): B.extract_selected(path, c['plan'], d['prepared'], c['raw_sha256'], ids)

    def rehashed(self, label, mutate):
        dest = self.root/label; shutil.copytree(self.fixture, dest)
        d = B.read(dest/'AK02.json'); mutate(d)
        (dest/'AK02.json').write_text(json.dumps(d), encoding='utf-8')
        receipt = B.read(dest/'EXPORT.json'); receipt['contracts']['AK02']['sha256'] = B.sha(dest/'AK02.json')
        (dest/'EXPORT.json').write_text(json.dumps(receipt), encoding='utf-8')
        with self.assertRaises(ValueError): B.verify(dest)

    def test_rehashed_alias_mutations(self):
        mutations = {
            'coordinate': lambda d: self.positive(d)['steps'][0]['position_mm'].__setitem__(0, 8),
            'delay': lambda d: self.positive(d)['pulse_groups'][0]['relative_times_ns'].__setitem__(0, 1),
            'energy': lambda d: self.positive(d)['steps'][0].__setitem__('energy_keV', 8),
            'zero': lambda d: self.positive(d).__setitem__('zero_ge', True),
            'id': lambda d: self.positive(d).__setitem__('event_id', 8)}
        for label, mutate in mutations.items():
            with self.subTest(label=label): self.rehashed(label, mutate)

    def test_rehashed_coordinated_time_edit_hits_source_roundtrip(self):
        def mutate(d):
            e = self.positive(d)
            for s in e['steps']:
                s['raw']['time'] += 100
                s['time_ns'] = s['raw']['time']
            e['pulse_groups'] = B.C.group_deposits(e['steps'])
            B.validate_contract(d)  # internally consistent, but not the original HDF5 rows
        self.rehashed('coordinated-time', mutate)

    def test_plain_hash_mismatch(self):
        dest = self.root/'hash'; shutil.copytree(self.fixture, dest)
        with (dest/'AK02.json').open('a', encoding='utf-8') as stream: stream.write(' ')
        with self.assertRaises(ValueError): B.verify(dest)

    def test_launcher_failure_and_stall_receipts(self):
        class Child:
            def __init__(self, stalled): self.stalled, self.killed = stalled, False
            def poll(self): return None if self.stalled else 2
            def kill(self): self.killed = True
            def wait(self): return -9 if self.killed else 2
        for stalled in (False, True):
            child = Child(stalled)
            dest = B.BASE/(self.root.name+('-stall' if stalled else '-failed'))
            with patch.object(B, 'verify'), patch.object(B.subprocess, 'Popen', return_value=child), \
                 patch.object(B.time, 'time', side_effect=[0, 181, 182] if stalled else [0, 1]), \
                 self.assertRaises(ValueError):
                B.run_pilot(self.fixture, dest, Path(sys.executable))
            receipt = B.read(B.BASE/(dest.name+'-launcher')/'launcher.json')
            self.assertEqual(receipt['status'], 'failed_or_incomplete')
            self.assertEqual(child.killed, stalled)
            self.assertEqual(receipt['returncode'], -9 if stalled else 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
