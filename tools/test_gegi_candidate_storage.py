import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zlib

import numpy as np

import gegi_candidate_storage as storage
import gegi_event_energy as energy
import gegi_exposure_stream as stream
from test_gegi_pulse_stream import prepare, pulse


def card(event):
    measured = energy.estimate_event_energy(event)
    return {'trigger_time_ns': event['trigger_time_ns'],
            'single_pixel_energy_keV': event['slow_energy_keV'],
            'energy_keV': measured['energy_keV'],
            'x_collecting_strips': measured['x_contact_ids'],
            'y_collecting_strips': measured['y_contact_ids'],
            'guard_contact_ids': measured['guard_contact_ids'],
            'flags': event['flags'], 'event_energy_flags': measured['flags']}


class CandidateStorageTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.local' / 'candidate-storage-v1'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='unit-', dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / storage.ARCHIVE_NAME

    def test_exact_fast_slow_timing_neighbors_pileup_and_truncation_replay(self):
        first = prepare(pulse((3, 24), energy=190., neighbor=True))
        second = prepare(pulse((11, 26), energy=470.))
        third = prepare(pulse((12, 29), energy=160.))
        clock = stream.ADCExposure([(third, 1577., 1.), (first, 2017., 1.), (second, 2017., 1.),
                                    (third, 2417., 1.), (third, 6007., 1.),
                                    (first, 9727., 1.), (second, 9727., 1.)],
                                   live_time_ns=10000., phase_ns=7., noise_seed=23)
        originals = {}
        with storage.CandidateStore(self.path, {'seed': 23, 'initial_parents': 7}) as saved:
            def observe(event, context):
                identifier = context['readout_trigger_id']
                originals[identifier] = copy.deepcopy(event)
                saved.observe(card(event), context, event=event,
                              identities=[{'source': 'synthetic_unit_input', 'unassigned': True}])

            with patch.object(clock, 'blocks', wraps=clock.blocks) as blocks:
                result = stream.reconstruct_exposure(clock, block_samples=11,
                                                      on_readout_context=observe, retain_events=False)
            self.assertEqual(blocks.call_count, 2)
            self.assertEqual(result['events'], [])
            completion = saved.finalize(acquisition_statistics={
                'initial_parents': 7, 'zero_deposit_parents': 0, 'nonzero_deposit_parents': 7,
                'activity_count': result['activity_count'], 'adc_sha256': result['adc_sha256']})
        summary = storage.store_summary(self.path)
        self.assertEqual(summary['status'], 'completed')
        self.assertEqual(completion['observed_coincident_rises'], len(originals))
        self.assertGreater(completion['saved_candidates'], 1)
        self.assertGreater(completion['rejected_rises'], 0)
        self.assertEqual(completion['observed_coincident_rises'],
                         result['accepted_trigger_count'] + result['rejected_rise_count'])
        candidates = storage.list_candidates(self.path)
        self.assertEqual(len(candidates), completion['saved_candidates'])
        self.assertEqual(storage.list_candidates(self.path, limit=1, offset=1), candidates[1:2])
        truncated, pileup, full_slow = False, False, False
        for item in candidates:
            identifier = item['trigger_id']
            actual = storage.replay_candidate(self.path, identifier)
            self.assertEqual(actual, originals[identifier])
            record = storage.load_candidate(self.path, identifier)
            context = record['context']
            self.assertEqual(context['adc_codes'].dtype, np.int16)
            self.assertEqual(context['adc_codes'].shape[0], 34)
            self.assertNotIn('adc_codes', item)
            self.assertEqual(len(record['readout']['channels']), 34)
            truncated |= 'slow_window_truncated' in actual['flags']
            pileup |= 'slow_pileup' in actual['flags'] or 'fast_pileup' in actual['flags']
            full_slow |= (context['stop_sample_index'] * stream.SAMPLE_PERIOD_NS + context['adc_phase_ns']
                          > actual['trigger_time_ns'] + 980.)
        self.assertTrue(truncated)
        self.assertTrue(pileup)
        self.assertTrue(full_slow)
        self.assertEqual(summary['completion']['acquisition_statistics']['initial_parents'], 7)
        with closing(sqlite3.connect(self.path)) as db:
            rejection = db.execute('SELECT trigger_id,record,adc_codes FROM triggers WHERE decision=? LIMIT 1',
                                   ('rejected',)).fetchone()
        self.assertIsNone(rejection[2])
        self.assertEqual(json.loads(zlib.decompress(rejection[1]))['trigger_id'], rejection[0])
        with self.assertRaisesRegex(ValueError, 'no saved ADC'):
            storage.replay_candidate(self.path, rejection[0])

    def test_selection_keeps_multistrip_charge_sharing_pairing_and_quality_ambiguity(self):
        base = {'x_collecting_strips': [3], 'y_collecting_strips': [24],
                'guard_contact_ids': [], 'flags': [], 'event_energy_flags': [],
                'single_pixel_energy_keV': 100.}
        self.assertEqual(storage.candidate_decision(base), (False, 'qualified_single_strip_pair'))
        for changes in ({'x_collecting_strips': [3, 4]}, {'y_collecting_strips': [24, 25, 26]},
                        {'x_collecting_strips': [3, 4, 5], 'energy_keV': None},
                        {'flags': ['slow_pileup']}, {'flags': ['step_adc_saturation']},
                        {'single_pixel_energy_keV': None}, {'x_collecting_strips': None},
                        {'x_collecting_strips': [3, 4], 'y_collecting_strips': [24, 25],
                         'two_strip_pairings': {'compatible_pairing_count': 0}}):
            with self.subTest(changes=changes):
                self.assertTrue(storage.candidate_decision(base | changes)[0])
        guard = base | {'x_collecting_strips': [], 'y_collecting_strips': [],
                        'guard_contact_ids': [17, 34], 'flags': ['guard_collection']}
        self.assertEqual(storage.candidate_decision(guard), (False, 'guard_only_collection'))
        self.assertTrue(storage.candidate_decision(guard | {'flags': ['step_window_truncated']})[0])

    def test_original_ids_reject_ledger_incomplete_store_and_changed_bytes(self):
        clock = stream.ADCExposure([(prepare(pulse()), 1017., 1.)], live_time_ns=4000.)
        captured = []
        stream.reconstruct_exposure(clock, on_readout_context=lambda event, context:
                                    captured.append((copy.deepcopy(event), copy.deepcopy(context))))
        event, context = captured[0]
        with storage.CandidateStore(self.path, {'original_seed': None}) as saved:
            candidate = card(event) | {'flags': ['unqualified_slow_energy']}
            saved.observe(candidate, context, event=event, trigger_id=9,
                          identities=[{'original_parent_id': 698, 'source': 'test'}])
            with self.assertRaisesRegex(ValueError, 'once in acquisition order'):
                saved.observe(candidate, context, event=event, trigger_id=9)
            saved.observe(card(event), context, event=event, trigger_id=12,
                          rejection_reason='excluded_history')
        self.assertEqual(storage.store_summary(self.path)['status'], 'interrupted_or_running')
        record = storage.load_candidate(self.path, 9)
        self.assertEqual(record['identities'], [{'original_parent_id': 698, 'source': 'test'}])
        self.assertEqual(storage.load_candidate(self.path, 12)['reason'], 'excluded_history')
        wrong = copy.deepcopy(record['context'])
        wrong['digital_profile_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'different channel, filter'):
            stream.replay_readout_context(wrong)
        with closing(sqlite3.connect(self.path)) as db:
            blob = db.execute('SELECT adc_codes FROM triggers WHERE trigger_id=9').fetchone()[0]
            raw = bytearray(zlib.decompress(blob))
            raw[-1] ^= 1
            db.execute('UPDATE triggers SET adc_codes=? WHERE trigger_id=9', (zlib.compress(raw),))
            db.commit()
        with self.assertRaisesRegex(ValueError, 'ADC samples changed'):
            storage.load_candidate(self.path, 9)
        with self.assertRaises(FileExistsError):
            storage.CandidateStore(self.path, {})


if __name__ == '__main__':
    unittest.main()
