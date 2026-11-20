"""Clock, checkpoint, bounded allocation and exact RNG macro tests; no physics."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import gegi_streaming_source as G
import test_gegi_source as Legacy


def json_roundtrip(value): return json.loads(json.dumps(value))


class StreamingSourceTests(unittest.TestCase):
    def collect(self, config, sizes):
        checkpoint = G.initialize(config); rows = []; index = 0
        while not checkpoint['finished']:
            new, checkpoint = G.next_block(config, json_roundtrip(checkpoint), sizes[index % len(sizes)])
            self.assertLessEqual(len(new), sizes[index % len(sizes)])
            rows.extend(new); index += 1
        return rows, checkpoint

    def test_fixed_count_split_resume_matches_original_single_clock(self):
        config = G.default_config(parent_count=100)
        whole, final = self.collect(config, [500])
        split, resumed = self.collect(config, [7, 19, 50, 1])
        self.assertEqual(whole, split)
        self.assertEqual(final['rng_state'], resumed['rng_state'])
        legacy = G.M.default_config(100, config['seed'], config['acquisition_id'])
        original = list(G.M.parent_schedule(legacy))
        self.assertEqual([{key: row[key] for key in original[0]} for row in whole], original)
        self.assertEqual([p['parent_decay_id'] for p in whole], list(range(100)))
        self.assertTrue(final['finished']); self.assertIsNone(final['pending_parent'])

    def test_fixed_duration_keeps_next_arrival_and_frontier_at_exact_end(self):
        config = G.default_config(duration_ns=415527.2846520245)
        whole, final = self.collect(config, [500])
        split, resumed = self.collect(config, [11, 3])
        self.assertEqual(whole, split)
        self.assertEqual(final['pending_parent'], resumed['pending_parent'])
        self.assertTrue(all(row['absolute_parent_time_ns'] < config['stop']['duration_ns'] for row in whole))
        self.assertGreaterEqual(final['pending_parent']['absolute_parent_time_ns'], config['stop']['duration_ns'])
        self.assertEqual(final['safe_frontier_ns'], config['stop']['duration_ns'])
        self.assertEqual(final['rng_state'], resumed['rng_state'])

    def test_short_empty_interval_does_not_create_a_fake_parent(self):
        config = G.default_config(duration_ns=1.e-9)
        rows, final = G.next_block(config, G.initialize(config), 50)
        self.assertEqual(rows, []); self.assertTrue(final['finished'])
        self.assertEqual(final['next_parent_id'], 0); self.assertIsNotNone(final['pending_parent'])

    def test_bounded_blocks_and_mutation_refusal(self):
        config = G.default_config(parent_count=20_000_000)
        start = G.initialize(config)
        rows, after = G.next_block(config, start, 500)
        self.assertEqual(len(rows), 500); self.assertEqual(after['next_parent_id'], 500)
        self.assertEqual(start['next_parent_id'], 0)
        changed = copy.deepcopy(config); changed['sources'][0]['activity_Bq'] += 1
        with self.assertRaisesRegex(ValueError, 'mismatch'): G.next_block(changed, after)
        for size in (0, 10001, True):
            with self.assertRaises(ValueError): G.next_block(config, start, size)

    def test_equilibrium_driver_merge_keeps_original_new_parent_clock(self):
        from test_gegi_source_inventory import parameters
        config = G.default_config(parent_count=100)
        config['initial_state'] = {'policy': G.inventory.POLICY, 'acquisition_start_ns': 0}
        def collect(size):
            state = G.initialize(config, inventory_parameters=parameters()); rows = []
            while not state['finished']:
                block, state = G.next_block(config, json_roundtrip(state), size); rows.extend(block)
            return rows, state
        whole, final = collect(10000); split, resumed = collect(11)
        self.assertEqual(whole, split)
        parents = [row for row in whole if row['origin'] == 'new_parent']
        original = list(G.M.parent_schedule(G.M.default_config(100, config['seed'], config['acquisition_id'])))
        self.assertEqual([row['absolute_parent_time_ns'] for row in parents], [row['absolute_parent_time_ns'] for row in original])
        self.assertEqual([row['new_parent_decay_id'] for row in parents], list(range(100)))
        self.assertEqual([row['event_id'] for row in whole], list(range(len(whole))))
        daughters = [row for row in whole if row['origin'] == 'initial_daughter_inventory']
        self.assertGreater(len(daughters), 0)
        self.assertTrue(all(row['parent_decay_id'] is None for row in daughters))
        self.assertEqual(final['next_parent_id'], 100)
        self.assertEqual(final['next_transport_id'], len(whole))
        self.assertEqual(final['rng_state'], resumed['rng_state'])

    def test_rng_restore_and_native_state_save_wrap_the_same_joint_beam(self):
        plan = {'config': G.M.default_config(), 'cryostat_contract': G.S.G.load_cryostat()}
        macro = G.block_macro(plan, 50, True)
        restore = macro.index('/random/resetEngineFrom rng-input.rndm')
        before = macro.index('/GeSignal/RNG/Save rng-before.rndm')
        beam = macro.index('/run/beamOn 50')
        after = macro.index('/GeSignal/RNG/Save rng-after.rndm')
        self.assertLess(restore, before); self.assertLess(before, beam); self.assertLess(beam, after)
        self.assertLess(macro.index('/gps/ion 55 137'), beam)
        self.assertLess(macro.index('/gps/ion 27 60'), beam)
        self.assertEqual(macro.count('/run/beamOn'), 1)
        self.assertIn('CLHEP::HepRandom::saveEngineStatus', G.RNG_SOURCE)
        self.assertIn('return app.RunSimulation(argc, argv)', G.RNG_SOURCE)

    def test_deposit_identity_is_parent_local_not_lh5_block_row_number(self):
        parent = next(G.M.parent_schedule(G.M.default_config()))
        a = {'steps': [{'raw_row_index': 110, 'time_ns': 3.}],
             'decay_photons': [{'track_id': 4, 'time_ns': 2.}], 'tracks': [{'trackid': 4}]}
        b = copy.deepcopy(a); b['steps'][0]['raw_row_index'] = 7
        first = G._decorate(a, parent, 88, 0); second = G._decorate(b, parent, 38, 1)
        self.assertEqual(first['steps'][0]['deposit_id'], second['steps'][0]['deposit_id'])
        self.assertEqual(first['decay_photons'][0]['emission_id'], second['decay_photons'][0]['emission_id'])
        self.assertEqual(first['tracks'][0]['global_track_id'], second['tracks'][0]['global_track_id'])
        self.assertNotEqual(first['steps'][0]['raw_row_index'], second['steps'][0]['raw_row_index'])

    def retirement_fixture(self, root, groups=1):
        directory = root/'block'; (directory/'stream').mkdir(parents=True)
        for ref in ('truth.lh5', 'primaries.lh5', 'parents.jsonl', 'stream/events.jsonl'):
            (directory/ref).write_bytes(b'synthetic owned scratch')
        (directory/'rng-after.rndm').write_bytes(b'preserved RNG state')
        manifest = {'first_parent_id': 50, 'last_parent_id': 99}
        G.h.publish_json(directory/'stream/manifest.json', manifest)
        G.h.publish_json(directory/'checkpoint-after.json', {'state': 'after'})
        seal = {'artifacts': {p.relative_to(directory).as_posix(): G.h.sha256(p)
                             for p in directory.rglob('*') if p.is_file()}}
        G.h.publish_json(directory/'seal.json', seal)
        database = root/'candidate.sqlite'
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript('CREATE TABLE source_blocks(block_index INTEGER,manifest_sha256 TEXT,after_state BLOB);'
                             'CREATE TABLE input_groups(parent INTEGER);')
            db.execute('INSERT INTO source_blocks VALUES(1,?,?)',
                       (G.h.sha256(directory/'stream/manifest.json'), b'{"state":"after"}'))
            for _ in range(groups): db.execute('INSERT INTO input_groups VALUES(88)')
        consumer = root/'consumer.json'
        G.h.publish_json(consumer, {'kind': 'gegi_streaming_source_consumer_receipt_v1', 'status': 'committed',
            'block_index': 1, 'source_manifest_sha256': G.h.sha256(directory/'stream/manifest.json'),
            'checkpoint_after_sha256': G.h.sha256(directory/'checkpoint-after.json'),
            'database_ref': database.relative_to(G.h.ROOT).as_posix()})
        verified = {'block_index': 1, 'counts': {'pulse_groups': 1}, 'seal_sha256': G.h.sha256(directory/'seal.json')}
        return directory, consumer, verified

    def test_retirement_requires_real_consumer_commit_and_keeps_state(self):
        with tempfile.TemporaryDirectory(dir=G.h.ROOT/'.local') as temp:
            directory, consumer, verified = self.retirement_fixture(Path(temp))
            with patch.object(G, 'verify', return_value=verified):
                result = G.retire(directory, consumer)
            self.assertGreater(result['retired_now_bytes'], 0)
            self.assertFalse((directory/'truth.lh5').exists())
            self.assertEqual((directory/'rng-after.rndm').read_bytes(), b'preserved RNG state')
            self.assertEqual(len(G._retired(directory)), 4)

    def test_incomplete_consumer_census_prevents_retirement(self):
        with tempfile.TemporaryDirectory(dir=G.h.ROOT/'.local') as temp:
            directory, consumer, verified = self.retirement_fixture(Path(temp), groups=0)
            with patch.object(G, 'verify', return_value=verified), self.assertRaisesRegex(ValueError, 'census'):
                G.retire(directory, consumer)
            self.assertTrue((directory/'truth.lh5').exists())

    def test_explicit_native_empty_alias_adapter_keeps_legacy_strict(self):
        fixture = Legacy.GeGILH5(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        meta = fixture.fixture()
        with fixture.h5py.File(fixture.path, 'r+') as raw: raw['stp'].create_group('__by_uid__')
        with self.assertRaisesRegex(ValueError, 'UID alias census'):
            list(G.S.events(fixture.path, meta))
        rows = list(G.S.events(fixture.path, meta, native_empty_uid_aliases=True))
        self.assertEqual([row['truth_edep_keV'] for row in rows], [0., 120.])
        with fixture.h5py.File(fixture.path, 'r+') as raw: del raw['stp/germanium']
        with self.assertRaisesRegex(ValueError, 'Missing/foreign raw step table'):
            list(G.S.events(fixture.path, meta, native_empty_uid_aliases=True))

    def test_extraction_repair_cannot_change_source_clock_or_transport_functions(self):
        original = 'def next_block():\n return 1\ndef events():\n return 2\n'
        reader_fix = 'def next_block():\n return 1\ndef events():\n return 3\n'
        physics_change = 'def next_block():\n return 3\ndef events():\n return 2\n'
        self.assertTrue(G._same_except(original, reader_fix, {'events'}))
        self.assertFalse(G._same_except(original, physics_change, {'events'}))

    def test_process_block_continues_prepared_completed_and_sealed_stages(self):
        config = G.default_config(); checkpoint = G.initialize(config)
        saved = {'config': config, 'checkpoint_before_sha256': G.digest(checkpoint)}
        for stage in ('prepared', 'transport_complete', 'sealed'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory(dir=G.h.ROOT/'.local') as temp:
                directory = Path(temp); (directory/'prepared.json').write_text('{}')
                if stage != 'prepared': (directory/'run.json').write_text('{"status":"complete"}')
                if stage == 'sealed': (directory/'seal.json').write_text('{}')
                def complete_run(path): (path/'run.json').write_text('{"status":"complete"}')
                with patch.object(G, '_prepared', return_value=(directory, saved, {}, [])), \
                     patch.object(G, 'prepare_block') as prepare, \
                     patch.object(G, 'run_block', side_effect=complete_run) as run, \
                     patch.object(G, 'extract') as extract, patch.object(G, 'verify', return_value={'status': 'sealed'}):
                    self.assertEqual(G.process_block(config, checkpoint, directory), {'status': 'sealed'})
                    prepare.assert_not_called()
                    self.assertEqual(run.call_count, int(stage == 'prepared'))
                    self.assertEqual(extract.call_count, int(stage != 'sealed'))

    def test_process_block_refuses_a_failed_or_mismatched_existing_stage(self):
        config = G.default_config(); checkpoint = G.initialize(config)
        saved = {'config': config, 'checkpoint_before_sha256': G.digest(checkpoint)}
        with tempfile.TemporaryDirectory(dir=G.h.ROOT/'.local') as temp:
            directory = Path(temp); (directory/'prepared.json').write_text('{}')
            (directory/'run.json').write_text('{"status":"failed"}')
            with patch.object(G, '_prepared', return_value=(directory, saved, {}, [])), \
                 patch.object(G, 'run_block') as run, patch.object(G, 'extract') as extract:
                with self.assertRaisesRegex(ValueError, 'cannot be rerun'): G.process_block(config, checkpoint, directory)
                run.assert_not_called(); extract.assert_not_called()
                saved['checkpoint_before_sha256'] = 'other'
                with self.assertRaisesRegex(ValueError, 'another requested'): G.process_block(config, checkpoint, directory)


if __name__ == '__main__': unittest.main()
