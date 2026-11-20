"""Integrated queue/continuation contracts with synthetic transport and native inputs."""
import copy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import gegi_streaming_acquisition as A
import gegi_candidate_storage as S
from test_gegi_pulse_stream import pulse
from test_gegi_digital_readout import CHANNELS


GEOMETRY = [{**channel, 'family': 'X' if channel['id'] <= 17 else 'Y',
    'guard': channel['id'] in (17, 34), 'strip_center_mm': float(channel['id'] % 17)} for channel in CHANNELS]


def event(parent, clock, delay, source):
    return {'event_id': parent, 'parent_decay_id': parent, 'acquisition_id': 'test',
        'isotope': source, 'source_id': source, 'absolute_parent_time_ns': clock,
        'source_position_global_mm': [-40, 0, 40],
        'steps': [{'raw_row_index': 0, 'time_ns': delay, 'absolute_time_ns': clock+delay, 'energy_keV': 200.}],
        'pulse_groups': [{'group_id': 0, 'origin_time_ns': delay, 'row_indices': [0]}]}


class FakeNative:
    saved = {}
    def __init__(self, *args, **kwargs):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('CREATE TABLE events(x); CREATE TABLE arrays(x);')
    def read(self, parent, group, **kwargs):
        return {'status': 'completed'}, pulse((3, 24) if parent == 0 else (11, 26), 200., neighbor=True)
    def close(self): self.db.close()


class FakeWorker:
    calls = []
    def __init__(self, *args):
        self.process = type('Process', (), {'pid': os.getpid()})()
    def start(self): return {'channels': GEOMETRY, 'environment': {'kind': 'synthetic_native_runtime'}}
    def process_group(self, group, store):
        self.calls.append((group['event_id'], group['group_id']))
        return {'status': 'completed'}
    def close(self): pass


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / '.local').mkdir()
        self.patches = [patch.object(A, 'ROOT', self.root), patch.object(A, 'OWN_SOURCES', ()),
            patch.object(A.mixed, 'native_request', self.request),
            patch.object(A, 'transport_call', self.transport),
            patch.object(A.response, 'ResidentWorker', FakeWorker),
            patch.object(A.native_store, 'Store', FakeNative),
            patch.object(A.digital, 'terminal_contacts_complete', return_value=True)]
        for item in self.patches: item.start()
        FakeWorker.calls = []

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def request(self, output, count):
        path = output / 'native-request.json'
        A.candidates.write_new(path, {'synthetic': True})
        return path

    def transport(self, args, log):
        action = args[0]
        def path(key): return (self.root / 'transport' / args[args.index(key)+1]).resolve()
        if action == 'init':
            A.W.write(path('--output'), {'next_block_index': 0, 'last_parent_time_ns': 0.,
                'safe_frontier_ns': 0., 'finished': False})
        elif action == 'prepare-block':
            directory = path('--output'); directory.mkdir(parents=True)
            A.W.write(directory / 'prepared.json', A.W.read(path('--checkpoint')))
        elif action == 'run-block':
            A.W.write(path('--directory') / 'run.json', {'status': 'complete'})
        elif action == 'extract':
            directory = path('--directory'); before = A.W.read(directory / 'prepared.json')
            index = before['next_block_index']
            # Delayed parent 0 overlaps a later parent generated in block 1.
            rows = ([event(0, 1000., 5000., 'cs137'), event(1, 2000., 900000., 'cs137')]
                    if index == 0 else [event(2, 6000., 0., 'co60')])
            stream = directory / 'stream'; stream.mkdir()
            (stream / 'events.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
            after = {'next_block_index': index+1, 'last_parent_time_ns': 2000. if index == 0 else 8000.,
                'safe_frontier_ns': 2000. if index == 0 else 8000., 'finished': index == 1}
            A.W.write(directory / 'checkpoint-after.json', after)
            A.W.write(stream / 'manifest.json', {'primary_count': 2, 'counts': {'zero_deposit_primaries': index,
                'nonzero_primaries': 2-index}, 'events_file': 'events.jsonl', 'events_sha256': A.mixed.file_sha(stream/'events.jsonl')})

    def test_delayed_cross_block_signals_exact_after_stop_and_resume(self):
        complete = self.root / '.local/complete'
        resumed = self.root / '.local/resumed'
        expected = A.run(complete, 4, block_parents=2, retain_validation_inputs=True)
        self.assertEqual(expected['source']['initial_parents'], 4)
        self.assertEqual(expected['source']['delayed_groups_after_acquisition'], 1)
        self.assertGreater(expected['storage_counts']['saved_candidates'], 0)
        FakeWorker.calls = []
        stopped = A.run(resumed, 4, block_parents=2, stop_after_groups=1, retain_validation_inputs=True)
        self.assertEqual(stopped['status'], 'stopped')
        with closing(sqlite3.connect(resumed / S.ARCHIVE_NAME)) as db:
            checkpoint = json.loads(db.execute('SELECT state FROM checkpoint').fetchone()[0])
            self.assertTrue(checkpoint['readout']['pulses'])
        actual = A.run(resumed, 4, block_parents=2, resume=True, retain_validation_inputs=True)
        self.assertEqual(FakeWorker.calls, [(0, 0), (2, 0)])
        for field in ('source', 'counts', 'spectra', 'storage_counts', 'readout'):
            self.assertEqual(actual[field], expected[field])
        self.assertEqual(A.candidates.verify_candidates(resumed / S.ARCHIVE_NAME)['status'], 'verified_exact')
        for trigger in S.list_candidates(resumed / S.ARCHIVE_NAME):
            got = S.load_candidate(resumed / S.ARCHIVE_NAME, trigger['trigger_id'])
            want = S.load_candidate(complete / S.ARCHIVE_NAME, trigger['trigger_id'])
            self.assertEqual(got['readout'], want['readout'])
            self.assertEqual(got['context']['adc_codes'].tolist(), want['context']['adc_codes'].tolist())

    def test_changed_sources_refuse_resume_without_touching_committed_data(self):
        output = self.root / '.local/changed'
        A.run(output, 4, block_parents=2, stop_after_blocks=1)
        before = (output / S.ARCHIVE_NAME).read_bytes()
        with self.assertRaisesRegex(ValueError, 'original sources'):
            A.run(output, 4, resume=True, activities_bq=(1, 2))
        self.assertEqual((output / S.ARCHIVE_NAME).read_bytes(), before)

    def test_completed_database_recovers_export_without_repeating_science(self):
        output = self.root / '.local/export-interruption'
        with patch.object(A, '_write_report', side_effect=OSError('synthetic interrupted export')):
            with self.assertRaisesRegex(OSError, 'interrupted export'):
                A.run(output, 4, block_parents=2)
        calls = list(FakeWorker.calls)
        result = A.run(output, 4, block_parents=2, resume=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(FakeWorker.calls, calls)

    def test_low_memory_stops_before_native_and_resumes_same_queue(self):
        output = self.root / '.local/memory-stop'
        with patch.object(A, 'available_memory', return_value=300 * 1024**2):
            stopped = A.run(output, 4, block_parents=2)
        self.assertEqual(stopped['status'], 'stopped')
        self.assertEqual(FakeWorker.calls, [])
        result = A.run(output, 4, block_parents=2, resume=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['source']['initial_parents'], 4)

    def test_native_runtime_change_refuses_before_new_drift(self):
        output = self.root / '.local/changed-native-runtime'
        A.run(output, 4, block_parents=2, stop_after_groups=1)
        calls = list(FakeWorker.calls)
        with patch.object(FakeWorker, 'start', return_value={'channels': GEOMETRY, 'environment': {'kind': 'changed'}}):
            with self.assertRaisesRegex(ValueError, 'runtime versions changed'):
                A.run(output, 4, block_parents=2, resume=True)
        self.assertEqual(FakeWorker.calls, calls)


if __name__ == '__main__': unittest.main()
