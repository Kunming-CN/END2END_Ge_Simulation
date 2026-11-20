from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zlib

import gegi_storage_estimate as E


class StorageEstimateTests(unittest.TestCase):
    def fixture(self, root):
        database = root/'compton-candidates.sqlite'
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript('CREATE TABLE metadata(singleton INTEGER PRIMARY KEY,body BLOB);'
                             'CREATE TABLE completion(singleton INTEGER PRIMARY KEY,body BLOB);'
                             'CREATE TABLE triggers(trigger_id INTEGER PRIMARY KEY,decision TEXT,record BLOB,adc_codes BLOB);')
            db.execute('INSERT INTO metadata VALUES(1,?)', (E.encoded({'kind': 'fixture'}),))
            db.execute('INSERT INTO completion VALUES(1,?)', (E.encoded({'saved_candidates': 1}),))
            context = {'digital_profile_sha256': 'profile', 'digital_timing_sha256': 'timing',
                       'readout_source_sha256': {'reader': 'sha'}, 'sample_period_ns': 20, 'contact_ids': [1]}
            db.execute('INSERT INTO triggers VALUES(1,?,?,?)', ('candidate',
                       zlib.compress(E.encoded({'context': context})), zlib.compress(b'\0\0\1\0')))
            db.execute('INSERT INTO triggers VALUES(2,?,?,NULL)', ('rejected', zlib.compress(b'{"reason":"single"}')))
        groups = root/'input-groups.jsonl.gz'
        groups.write_bytes(gzip.compress(b'{"input_group_ordinal":1}\n', mtime=0))
        report = {'kind': 'gegi_candidate_acquisition_v1', 'status': 'completed',
                  'artifacts': {p.name: {'bytes': p.stat().st_size, 'sha256': E.sha(p)} for p in (database, groups)},
                  'storage_counts': {'observed_coincident_rises': 2, 'saved_candidates': 1,
                                     'rejected_rises': 1, 'selection_reason_counts': {'candidate': 1, 'single': 1}},
                  'live_time_ns': 100., 'excluded_intervals_ns': [[0, 20], [10, 25]],
                  'source': {'initial_parents': 10}, 'elapsed_seconds': .5,
                  'identity': {'activities_bq': [185000, 37000], 'sources': [
                      {'chunk_index': 45, 'chunk_sha256': 'sha', 'private_path': 'C:/private/path'}]},
                  'selection_policy': {'ambiguity': 'keep'}}
        target = root/'candidate-acquisition.json'; target.write_bytes(E.encoded(report)+b'\n')
        return target, report

    def test_exact_byte_measurement_and_public_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, report = self.fixture(root)
            reference = E.reference_from_run(path)
            self.assertEqual(reference['observation']['qualified_fraction'], .75)
            self.assertEqual(reference['bytes']['uncompressed_candidate_adc'], 4)
            self.assertEqual(reference['bytes']['input_group_ledger'], report['artifacts']['input-groups.jsonl.gz']['bytes'])
            self.assertEqual(reference['observation']['input_group_ledger_rows'], 1)
            self.assertNotIn('private_path', json.dumps(reference))
            blobs = reference['bytes']['all_compressed_trigger_blobs']
            self.assertGreater(reference['bytes']['trigger_pages'], blobs)
            self.assertEqual(reference['bytes']['fixed_archive_pages']+reference['bytes']['trigger_pages'],
                             report['artifacts']['compton-candidates.sqlite']['bytes'])

    def test_scenarios_scale_variable_cost_but_keep_configuration_once(self):
        with tempfile.TemporaryDirectory() as temp:
            reference = E.reference_from_run(self.fixture(Path(temp))[0])
            value = E.estimate(10, reference=reference)
            observed = value['scenarios']['as_observed']
            self.assertEqual(observed['candidate_archive_bytes'], reference['bytes']['archive'])
            self.assertEqual(observed['run_summary_config_bytes'], reference['bytes']['report'])
            self.assertEqual(observed['shared_input_group_ledger_bytes'], reference['bytes']['input_group_ledger'])
            self.assertGreater(value['planning_range_bytes'][1], value['planning_range_bytes'][0])
            self.assertIsNone(value['runtime_prediction'])
            self.assertFalse(value['runtime_scratch']['production_ready'])

    def test_budget_does_not_pretend_to_bound_unmeasured_scratch(self):
        value = E.estimate(disk_budget_bytes=100*1024**3)
        self.assertEqual(value['disk_budget']['status'], 'final_and_shared_fit_scratch_unbudgeted')
        self.assertEqual(E.estimate(disk_budget_bytes=1)['disk_budget']['status'], 'insufficient_for_final_and_shared')
        self.assertAlmostEqual(value['expected_duration_s'], 20_000_000/222000)

    def test_no_silent_activity_transfer_or_changed_artifact(self):
        with self.assertRaises(ValueError): E.estimate(activities_bq=(37000, 37000))
        with tempfile.TemporaryDirectory() as temp:
            path, _ = self.fixture(Path(temp))
            with path.with_name('compton-candidates.sqlite').open('ab') as out: out.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'differs'): E.reference_from_run(path)

    def test_zero_candidate_pilot_cannot_supply_a_zero_storage_forecast(self):
        reference = E.load_reference()
        reference['observation']['saved_candidates'] = 0
        with self.assertRaisesRegex(ValueError, 'zero-candidate'): E.estimate(reference=reference)


if __name__ == '__main__': unittest.main()
