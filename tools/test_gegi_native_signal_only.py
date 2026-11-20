"""Opt-in native-only resident/store contracts; no transport, fields or drift."""

import copy
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import gegi_campaign_response as C
import gegi_event_store as S


def native_payload():
    signals, channels = {}, []
    for cid in range(1, 35):
        q = [0., .25, 0.] if cid == 2 else [0., 4., 4.] if cid == 3 else [0., -4., -4.] if cid == 24 else [0., 0., 0.]
        wiring = 1 if cid <= 17 else -1
        signals[cid] = {'time_ns': [0., 1., 2.], 'signed_induced_keV': q}
        channels.append({'contact_id': cid, 'wiring_factor': wiring,
                         'final_induced_keV': q[-1], 'final_wired_induced_keV': wiring*q[-1]})
    event = {'event_id': 27, 'group_id': 0, 'status': 'completed', 'truth_edep_keV': 4.,
             'steps': [{'energy_keV': 4., 'endpoints': [{'status': 'contact', 'step_limit_reached': False}]}],
             'channels': channels, 'response_mode': S.NATIVE_SIGNAL_ONLY,
             'readout_summary': None, 'readout_status': 'shared_readout_pending'}
    return event, signals


class NativeOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-only-', dir=C.ROOT/'.local')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.event, self.signals = native_payload()

    def store(self, name='events.sqlite'):
        store = S.Store(self.root/name, {'response_mode': S.NATIVE_SIGNAL_ONLY}, create=True)
        self.addCleanup(store.close)
        return store

    def test_all_electrode_bits_and_zero_final_neighbor_survive_without_trace_hashing(self):
        store = self.store()
        original = copy.deepcopy(self.event)
        with patch.object(S, 'trace_hash', side_effect=AssertionError('No isolated trace exists')):
            store.append(27, 0, self.event, self.signals, 'a'*64)
            C.verify_store_roundtrip(store, 27, 0, self.event, self.signals, 'a'*64)
        event, native = store.read(27, 0, with_signals=True)
        self.assertEqual(self.event, original)
        self.assertEqual(event['channels'], original['channels'])
        self.assertEqual(len(native), 34)
        self.assertIsNone(event['readout_summary'])
        self.assertEqual(native[2]['signed_induced_keV'], [0., .25, 0.])
        for cid in self.signals:
            for field, values in self.signals[cid].items():
                self.assertEqual(struct.pack('<3d', *native[cid][field]), struct.pack('<3d', *values))
        self.assertTrue(all('trace' not in row and 'derived_trace_sha256' not in row for row in event['channels']))
        store.seal({'native_only_groups': 1})

    def test_native_schema_rejects_missing_electrodes_and_fabricated_readout(self):
        for index, changes in enumerate(('missing', 'fake_trace', 'fake_readout')):
            store = self.store(f'bad-{index}.sqlite')
            event, signals = copy.deepcopy(self.event), copy.deepcopy(self.signals)
            if changes == 'missing':
                event['channels'].pop();signals.pop(34)
            elif changes == 'fake_trace':
                event['channels'][0]['trace'] = {'preamp_V': [0., 0.]}
            else:
                event['readout_summary'] = {'accepted': False, 'energy_keV': 0.}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                store.append(27, 0, event, signals, 'b'*64)
            self.assertEqual(list(store.keys()), [])
        legacy = copy.deepcopy(self.event);legacy.pop('response_mode')
        with self.assertRaises(KeyError):
            self.store('legacy-strict.sqlite').append(27, 0, legacy, self.signals, 'c'*64)

    def worker_and_spool(self, *, failed=False):
        worker = object.__new__(C.ResidentWorker)
        worker.ready = {'response_mode': S.NATIVE_SIGNAL_ONLY}
        worker.spool = self.root/'spool';worker.spool.mkdir()
        group = {'event_id': 27, 'group_id': 0, 'steps': [{'raw_row_index': 4, 'energy_keV': 4.}]}
        digest = S.sha(S.encoded(group)); stem = 'g-'+digest
        event = {**copy.deepcopy(self.event), 'input_group': group, 'input_event_sha256': digest,
                 'input_steps': group['steps']}
        if failed:
            event.update(status='native_failed', channels=None, error='original native domain failure', readout_status='native_unavailable')
        paths = {name: worker.spool/(stem+suffix) for name, suffix in (
            ('event_path', '.json'), ('input_path', '-input.json'), ('receipt_path', '-receipt.json'), ('signals_path', '-signals.csv'))}
        C.write(paths['event_path'], event); C.write(paths['input_path'], group)
        if not failed:
            with paths['signals_path'].open('w', encoding='utf-8', newline='') as out:
                out.write('contact_id,time_ns,signed_induced_keV,wired_induced_keV\n')
                for row in event['channels']:
                    cid = row['contact_id']
                    for t, q in zip(self.signals[cid]['time_ns'], self.signals[cid]['signed_induced_keV']):
                        out.write(f'{cid},{t},{q},{row["wiring_factor"]*q}\n')
        receipt = {name: str(path) for name, path in paths.items()}
        receipt.update(input_sha256=digest, event_id=27, group_id=0, event_sha256=C.file_sha(paths['event_path']),
                       signals_sha256=C.file_sha(paths['signals_path']) if not failed else None)
        if failed:
            receipt['signals_path'] = None
        C.write(paths['receipt_path'], receipt)
        worker.command = lambda *args, **kwargs: receipt
        worker.recipe = lambda: self.fail('Native-only processing must not claim an isolated recipe')
        return worker, group, paths

    def test_adapter_skips_isolated_summary_and_recipe_then_reuses_committed_native(self):
        worker, group, paths = self.worker_and_spool()
        store = self.store()
        with patch.object(C, 'readout_summary', side_effect=AssertionError('No isolated readout')):
            result = worker.process_group(group, store)
        self.assertIsNone(result['readout_summary'])
        self.assertIsNone(result['readout_recipe_sha256'])
        self.assertEqual(result['readout_status'], 'shared_readout_pending')
        self.assertTrue(all(not path.exists() for path in paths.values()))
        worker.command = lambda *args, **kwargs: self.fail('Completed native group was repeated')
        self.assertEqual(worker.process_group(group, store), result)
        worker.ready = {}
        with self.assertRaisesRegex(ValueError, 'response mode differs'):
            worker.process_group(group, store)
        with self.assertRaisesRegex(ValueError, 'no isolated electronics reference'):
            C.verify_replayed_channels(result, {'drift_executed': False})

    def test_native_failure_remains_null_without_an_electronics_rejection(self):
        worker, group, paths = self.worker_and_spool(failed=True)
        result = worker.process_group(group, self.store())
        self.assertIsNone(result['native_signals'])
        self.assertIsNone(result['channels'])
        self.assertIsNone(result['readout_summary'])
        self.assertEqual(result['error'], 'original native domain failure')
        self.assertEqual(result['readout_status'], 'native_unavailable')
        self.assertTrue(paths['event_path'].is_file())


if __name__ == '__main__':
    unittest.main()
