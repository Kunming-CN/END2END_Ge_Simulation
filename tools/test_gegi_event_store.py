"""Bounded storage/recovery and exact native signal round-trip checks; no physics."""
import copy
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
import gegi_event_store as S


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gegi-store-', dir=Path(__file__).resolve().parents[1]/'.local')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'batch.sqlite3'
        self.identity = {'model_sha256': 'a'*64, 'configuration_sha256': 'b'*64, 'batch_index': 0}
        self.event = {'event_id': 27, 'status': 'completed', 'truth_edep_keV': 3.,
            'steps': [{'energy_keV': 3., 'deposition_delay_ns': 451234.5}],
            'channels': [{'contact_id': 1, 'wiring_factor': 1, 'accepted': False,
                'reconstructed_energy_keV': None, 'trace': {'charge_fC': [-0., -1.2345678901234567, 2.],
                    'time_ns': [0., 1., 2.], 'preamp_V': [0., -.1, .25]}}]}
        self.signals = {1: {'time_ns': [0., 1., 2.], 'signed_induced_keV': [-0., -1.2345678901234567, 2.]}}

    def test_resume_exact_bits_scalars_unknowns_and_seal(self):
        store = S.Store(self.path, self.identity, create=True)
        store.append(27, 2, self.event, self.signals, 'c'*64)
        store.close()
        store = S.Store(self.path, self.identity)
        self.addCleanup(store.close)
        self.assertTrue(store.has(27, 2, 'c'*64))
        event, native = store.read(27, 2, with_signals=True)
        self.assertEqual(struct.pack('<3d', *native[1]['signed_induced_keV']), struct.pack('<3d', *self.signals[1]['signed_induced_keV']))
        self.assertEqual(event['steps'], self.event['steps'])
        self.assertIsNone(event['channels'][0]['reconstructed_energy_keV'])
        self.assertEqual(event['channels'][0]['derived_trace_sha256'], S.trace_hash(self.event['channels'][0]['trace']))
        self.assertNotIn('trace', event['channels'][0])
        with self.assertRaisesRegex(ValueError, 'must not be reprocessed'):
            store.append(27, 2, self.event, self.signals, 'c'*64)
        with self.assertRaisesRegex(ValueError, 'input changed'):
            store.has(27, 2, 'd'*64)
        store.seal({'nonzero_primaries': 1, 'nonzero_groups': 1, 'initial_primaries': 100})
        with self.assertRaisesRegex(ValueError, 'immutable'):
            store.append(27, 3, self.event, self.signals, 'c'*64)

    def test_failed_groups_are_null_and_distinct_from_zero_primaries(self):
        store = S.Store(self.path, self.identity, create=True)
        self.addCleanup(store.close)
        failure = {'event_id': 27, 'status': 'native_failed', 'channels': None, 'truth_edep_keV': 3., 'error': 'preserved'}
        store.append(27, 0, failure, None, 'c'*64)
        event, signal = store.read(27, 0, with_signals=True)
        self.assertIsNone(event['native_signals'])
        self.assertIsNone(signal)
        self.assertEqual(list(store.keys()), [(27, 0)])

    def test_identity_and_corrupt_native_data_refused(self):
        store = S.Store(self.path, self.identity, create=True)
        store.append(27, 0, self.event, self.signals, 'c'*64)
        store.close()
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            S.Store(self.path, dict(self.identity, batch_index=1))
        store = S.Store(self.path, self.identity)
        self.addCleanup(store.close)
        with store.db:
            store.db.execute('UPDATE arrays SET count=count+1')
        with self.assertRaisesRegex(ValueError, 'count changed'):
            store.seal({})

    def test_transaction_does_not_publish_failed_group(self):
        store = S.Store(self.path, self.identity, create=True)
        self.addCleanup(store.close)
        invalid = copy.deepcopy(self.signals)
        invalid[1]['signed_induced_keV'][1] = float('nan')
        with self.assertRaisesRegex(ValueError, 'Nonfinite'):
            store.append(27, 0, self.event, invalid, 'c'*64)
        self.assertEqual(list(store.keys()), [])
        self.assertEqual(store.db.execute('SELECT count(*) FROM arrays').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
