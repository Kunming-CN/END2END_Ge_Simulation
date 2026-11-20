"""Atomic candidate/checkpoint recovery with synthetic signed ADC contexts only."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import gegi_candidate_storage as storage
from gegi_event_store import encoded


ROOT = Path(__file__).resolve().parents[1]


def observation(trigger_id):
    codes = (np.arange(34 * 7, dtype=np.int16).reshape(34, 7) - 119)
    codes[0, :2] = [-32768, 32767]
    card = {'trigger_time_ns': trigger_id * 20., 'x_collecting_strips': [3, 4],
            'y_collecting_strips': [24], 'guard_contact_ids': [], 'flags': ['slow_pileup'],
            'event_energy_flags': [], 'single_pixel_energy_keV': None, 'energy_keV': None}
    context = {'readout_trigger_id': trigger_id, 'first_sample_index': 11,
               'stop_sample_index': 18, 'adc_codes': codes,
               'adc_phase_ns': 3., 'readout_rejection_reason': None,
               'unit_fixture': {'signed': True, 'baseline_v': [-0.125] * 34}}
    event = {'trigger_time_ns': card['trigger_time_ns'], 'flags': ['slow_pileup'],
             'channels': [{'contact_id': i, 'fast_energy_keV': -i / 8.,
                           'slow_energy_keV': i / 4., 'timing_ns': None} for i in range(1, 35)]}
    return card, context, event


class CandidateStorageResumeTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / '.local' / 'candidate-storage-v1'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='unit-resume-', dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / storage.ARCHIVE_NAME
        self.identity = {'scope': 'synthetic_unit_only', 'seed': 20261120,
                         'source': {'sha256': 'a' * 64, 'isotopes': ['Cs137', 'Co60']}}

    def initial_checkpoint(self):
        with storage.CandidateStore(self.path, self.identity) as store:
            store.db.execute('CREATE TABLE source_blocks (ordinal INTEGER PRIMARY KEY, body TEXT)')
            with store.transaction():
                store.save_checkpoint({'source_cursor': 0, 'readout': {'next_sample': 0}, 'counts': {}})

    def test_block_rollback_resume_and_exact_contexts(self):
        self.initial_checkpoint()
        with storage.CandidateStore(self.path, self.identity, resume=True) as store:
            metadata_before = store.db.execute('SELECT body FROM metadata').fetchone()[0]
            initial = store.load_checkpoint()
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                with store.transaction():
                    store.db.execute('INSERT INTO source_blocks VALUES (1,?)', ('uncommitted',))
                    card, context, event = observation(7)
                    store.observe(card, context, event=event)
                    store.save_checkpoint({'source_cursor': 1})
                    raise RuntimeError('interrupted block')
            self.assertEqual(store.last_trigger_id, 0)
            self.assertEqual(store.load_checkpoint(), initial)
            self.assertEqual(store.db.execute('SELECT count(*) FROM source_blocks').fetchone()[0], 0)
            state = {'source_cursor': 1, 'readout': {'next_sample': 18, 'pending': [-32768, 32767]},
                     'counts': {'candidates': 1, 'rejections': 1}}
            with store.transaction():
                store.db.execute('INSERT INTO source_blocks VALUES (1,?)', ('committed',))
                card, context, event = observation(7)
                store.observe(card, context, event=event, identities=[{'original_parent_id': 698}])
                store.observe(card, context, trigger_id=9, rejection_reason='excluded_unit_fixture')
                store.save_checkpoint(state)
            detached = store.load_checkpoint()
            detached['source_cursor'] = 999
            self.assertEqual(store.load_checkpoint(), state)
            checkpoint_ids = store.db.execute(
                'SELECT last_trigger_id,last_candidate_trigger_id FROM checkpoint').fetchone()
            self.assertEqual(checkpoint_ids, (9, 7))
        with storage.CandidateStore(self.path, self.identity, resume=True) as store:
            self.assertEqual(store.load_checkpoint(), state)
            self.assertEqual(store.db.execute('SELECT body FROM metadata').fetchone()[0], metadata_before)
            with self.assertRaisesRegex(ValueError, 'once in acquisition order'):
                store.observe(*observation(7)[:2], event=observation(7)[2])
            with store.transaction():
                card, context, event = observation(11)
                store.observe(card, context, event=event)
                store.save_checkpoint(state | {'source_cursor': 2})
            completion = store.finalize(acquisition_statistics={'scope': 'synthetic_unit_only'})
        self.assertEqual(completion['observed_coincident_rises'], 3)
        self.assertEqual(completion['saved_candidates'], 2)
        saved = storage.load_candidate(self.path, 7)
        card, context, event = observation(7)
        self.assertEqual(saved['card'], card)
        self.assertEqual(saved['readout'], event)
        self.assertEqual(saved['identities'], [{'original_parent_id': 698}])
        np.testing.assert_array_equal(saved['context'].pop('adc_codes'), context.pop('adc_codes'))
        self.assertEqual(saved['context'], context)
        rejection = storage.load_candidate(self.path, 9)
        self.assertNotIn('context', rejection)
        self.assertEqual(rejection['reason'], 'excluded_unit_fixture')
        self.assertEqual(storage.store_summary(self.path)['status'], 'completed')
        before = sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'already complete'):
            storage.CandidateStore(self.path, self.identity, resume=True)
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), before)

    def test_checkpoint_is_required_after_the_last_observation(self):
        self.initial_checkpoint()
        with storage.CandidateStore(self.path, self.identity, resume=True) as store:
            initial = store.load_checkpoint()
            for early_checkpoint in (False, True):
                with self.subTest(early_checkpoint=early_checkpoint):
                    with self.assertRaisesRegex(ValueError, 'needs a checkpoint'):
                        with store.transaction():
                            if early_checkpoint:
                                store.save_checkpoint({'source_cursor': 1})
                            card, context, event = observation(1)
                            store.observe(card, context, event=event)
                    self.assertEqual(store.last_trigger_id, 0)
                    self.assertEqual(store.load_checkpoint(), initial)
            with store.transaction():
                with self.assertRaisesRegex(ValueError, 'existing transaction'):
                    with store.transaction():
                        pass
                with self.assertRaisesRegex(ValueError, 'Finalize after'):
                    store.finalize(acquisition_statistics={})
                store.save_checkpoint(initial)

    def test_resume_mismatch_and_changed_checkpoint_fail_without_rebasing(self):
        self.initial_checkpoint()
        before = sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            storage.CandidateStore(self.path, self.identity | {'seed': 0}, resume=True)
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), before)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE checkpoint SET state=?', (encoded({'source_cursor': 999}),))
            db.commit()
        with self.assertRaisesRegex(ValueError, 'checkpoint.*changed'):
            storage.CandidateStore(self.path, self.identity, resume=True)

    def test_finite_bounded_checkpoint_and_identity_snapshot(self):
        original = json.loads(encoded(self.identity))
        with storage.CandidateStore(self.path, self.identity) as store:
            self.identity['source']['isotopes'].append('mutated_caller')
            self.assertEqual(store.metadata['identity'], original)
            with store.transaction():
                store.save_checkpoint({'source_cursor': 0})
            for bad in ({'value': float('nan')}, {1: 'non_string_key'}, {'tuple': (1, 2)}):
                with self.subTest(bad=repr(bad)):
                    with self.assertRaisesRegex(ValueError, 'finite standard JSON'):
                        with store.transaction():
                            card, context, event = observation(1)
                            store.observe(card, context, event=event)
                            store.save_checkpoint(bad)
                    self.assertEqual(store.last_trigger_id, 0)
            with patch.object(storage, 'MAX_CHECKPOINT_BYTES', 128):
                with self.assertRaisesRegex(ValueError, 'serialized limit'):
                    with store.transaction():
                        store.save_checkpoint({'pending': 'x' * 129})
            self.assertEqual(store.load_checkpoint(), {'source_cursor': 0})
        with storage.CandidateStore(self.path, original, resume=True) as store:
            self.assertEqual(store.load_checkpoint(), {'source_cursor': 0})

    def test_abrupt_process_exit_rolls_back_candidate_source_and_checkpoint(self):
        self.initial_checkpoint()
        code = '''
import json, os, sys
sys.path.insert(0, sys.argv[1])
import gegi_candidate_storage as storage
from test_gegi_candidate_storage_resume import observation
with storage.CandidateStore(sys.argv[2], json.loads(sys.argv[3]), resume=True) as store:
    with store.transaction():
        store.db.execute('INSERT INTO source_blocks VALUES (1,?)', ('uncommitted',))
        card, context, event = observation(3)
        store.observe(card, context, event=event)
        store.save_checkpoint({'source_cursor': 1})
        os._exit(17)
'''
        child = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT / 'tools'),
                                str(self.path), json.dumps(self.identity)],
                               cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 17, child.stdout + child.stderr)
        with storage.CandidateStore(self.path, self.identity, resume=True) as store:
            self.assertEqual(store.last_trigger_id, 0)
            self.assertEqual(store.load_checkpoint()['source_cursor'], 0)
            self.assertEqual(store.db.execute('SELECT count(*) FROM source_blocks').fetchone()[0], 0)
            with store.transaction():
                card, context, event = observation(3)
                store.observe(card, context, event=event)
                store.save_checkpoint({'source_cursor': 1})
        np.testing.assert_array_equal(storage.load_candidate(self.path, 3)['context']['adc_codes'],
                                      observation(3)[1]['adc_codes'])

    def test_legacy_rows_remain_readable_but_cannot_resume_without_a_checkpoint(self):
        with storage.CandidateStore(self.path, self.identity) as store:
            card, context, event = observation(5)
            store.observe(card, context, event=event)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TABLE checkpoint')
            db.execute('DROP INDEX trigger_decision_id')
            db.commit()
        self.assertEqual(storage.store_summary(self.path)['saved_candidates'], 1)
        self.assertEqual(storage.load_candidate(self.path, 5)['readout'], observation(5)[2])
        before = sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'no resumable checkpoint'):
            storage.CandidateStore(self.path, self.identity, resume=True)
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
