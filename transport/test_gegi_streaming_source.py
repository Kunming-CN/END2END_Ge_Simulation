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
        for size in (0, -1, True, 1.5):
            with self.assertRaises(ValueError): G.next_block(config, start, size)
        small = G.default_config(parent_count=3)
        rows, after = G.next_block(small, G.initialize(small), 20000)
        self.assertEqual(len(rows), 3)
        self.assertTrue(after['finished'])

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

    def test_photon_truth_retains_zero_steps_and_positive_deposit_ancestry(self):
        def track(tid, parent, pdg, procid, energy):
            return dict(trackid=tid, parent_trackid=parent, particle=pdg, raw_row_index=100+tid,
                        procid=procid, ekin=energy, time=3.*tid, xloc=.001*tid, yloc=.002, zloc=.003)
        tracks = {1: track(1, 0, 1000270600, -1, 0.), 2: track(2, 1, 22, 3, 1.173),
                  3: track(3, 2, 11, 4, .19), 4: track(4, 1, 11, 3, .25)}
        def step(index, tid, energy):
            track = tracks[tid]
            return dict(raw_row_index=index, particle=track['particle'], trackid=tid,
                        parent_trackid=track['parent_trackid'], edep=energy, time=12.,
                        xloc_pre=.002, yloc_pre=.003, zloc_pre=.004, xloc_post=.005, yloc_post=.006, zloc_post=.007)
        ge = [step(5, 2, 0.), step(6, 2, .03), step(7, 3, 190.)]
        saved = G.S.candidate_photon_truth(ge, tracks, {3: 'RadioactiveDecay', 4: 'compt'},
                                         [{'track_id': 2}], [{'track_id': 3}])
        self.assertEqual([row['raw_row_index'] for row in saved['ge_gamma_steps']], [5, 6])
        self.assertEqual(saved['ge_gamma_steps'][0]['edep_keV'], 0.)
        self.assertEqual(saved['ge_gamma_steps'][0]['post_position_mm'], [5., 6., 7.])
        self.assertNotIn('process', saved['ge_gamma_steps'][0])
        self.assertEqual([t['track_id'] for t in saved['track_births']], [1, 2, 3])
        self.assertEqual(saved['track_births'][1]['birth_kinetic_energy_keV'], 1173.)
        self.assertEqual(saved['track_births'][2]['birth_process'], 'compt')

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

    def test_transport_retirement_requires_new_photon_truth_staging_commit(self):
        with tempfile.TemporaryDirectory(dir=G.h.ROOT/'.local') as temp:
            root = Path(temp)
            directory, consumer, verified = self.retirement_fixture(root)
            manifest_path = directory/'stream/manifest.json'
            manifest = G.S.load(manifest_path)
            manifest['candidate_photon_truth_kind'] = G.S.CANDIDATE_PHOTON_TRUTH_KIND
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            receipt = G.S.load(consumer)
            scratch = root/'candidate-truth-scratch.sqlite'
            receipt.update(source_manifest_sha256=G.h.sha256(manifest_path),
                           candidate_truth_scratch_ref=scratch.relative_to(G.h.ROOT).as_posix())
            consumer.write_text(json.dumps(receipt), encoding='utf-8')
            with closing(sqlite3.connect(root/'candidate.sqlite')) as db, db:
                db.execute('UPDATE source_blocks SET manifest_sha256=?', (receipt['source_manifest_sha256'],))
            verified['counts']['nonzero_primaries'] = 1
            with closing(sqlite3.connect(scratch)) as db, db:
                db.execute('CREATE TABLE events (block_index INTEGER)')
            with patch.object(G, 'verify', return_value=verified):
                with self.assertRaisesRegex(ValueError, 'committed positive-deposit'):
                    G.retire(directory, consumer)
                self.assertTrue((directory/'truth.lh5').exists())
                with closing(sqlite3.connect(scratch)) as db, db:
                    db.execute('INSERT INTO events VALUES (1)')
                self.assertGreater(G.retire(directory, consumer)['retired_now_bytes'], 0)
            self.assertFalse((directory/'truth.lh5').exists())

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

    def test_opt_in_flat_lh5_truth_preserves_native_positive_deposit_inputs(self):
        fixture = Legacy.GeGILH5(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        def include_zero_energy_photon(bundle):
            bundle['steps'].append(dict(bundle['steps'][-1], trackid=4, parent_trackid=2, particle=22, edep=0.))
        meta = fixture.fixture(mutate=include_zero_energy_photon)
        before = list(G.S.events(fixture.path, meta))
        with_truth = list(G.S.events(fixture.path, meta, include_candidate_truth=True))
        saved = with_truth[1].pop('candidate_photon_truth')
        self.assertEqual(with_truth, before)
        step, = saved['ge_gamma_steps']
        self.assertEqual((step['raw_row_index'], step['track_id'], step['parent_track_id'], step['edep_keV']), (2, 4, 2, 0.))
        self.assertIn('compt', [t['birth_process'] for t in saved['track_births']])

    def test_extraction_repair_cannot_change_source_clock_or_transport_functions(self):
        original = 'def next_block():\n return 1\ndef events():\n return 2\n'
        reader_fix = 'def next_block():\n return 1\ndef events():\n return 3\n'
        physics_change = 'def next_block():\n return 3\ndef events():\n return 2\n'
        self.assertTrue(G._same_except(original, reader_fix, {'events'}))
        self.assertFalse(G._same_except(original, physics_change, {'events'}))

    def test_block_limit_continuation_proves_same_clock_and_sealed_transport(self):
        import hashlib
        import zipfile
        current = Path(G.__file__).read_text(encoding='utf-8')
        original = current.replace(
            "    h.require(type(max_parents) is int and max_parents > 0, 'Transport drivers per block must be a positive integer')\n",
            "    h.require(type(max_parents) is int and 1 <= max_parents <= 10000, 'Use 1–10000 transport drivers per block')\n", 1).replace(
            '    compatibility = {**_extraction_compatibility(directory, meta), **_block_limit_compatibility(directory, meta)}\n',
            '    compatibility = _extraction_compatibility(directory, meta)\n', 1)
        self.assertTrue(G._block_limit_only(original, current))
        changed = current.replace("state['next_transport_id'] += 1", "state['next_transport_id'] += 2", 1)
        self.assertFalse(G._block_limit_only(original, changed))
        changed = current.replace('/GeSignal/RNG/Save rng-after.rndm', '/GeSignal/RNG/Save changed.rndm', 1)
        self.assertFalse(G._block_limit_only(original, changed))
        namespace = {'__name__': 'source_before_block_limit', '__file__': G.__file__}
        exec(compile(original, '<preserved source>', 'exec'), namespace)
        config = G.default_config(parent_count=100)
        checkpoint = G.initialize(config)
        old_rows, old_after = namespace['next_block'](config, checkpoint, 50)
        self.assertEqual((old_rows, old_after), G.next_block(config, checkpoint, 50))
        self.assertEqual(namespace['block_macro']({'config': G.M.default_config(), 'cryostat_contract': G.S.G.load_cryostat()},50,True),
                         G.block_macro({'config': G.M.default_config(), 'cryostat_contract': G.S.G.load_cryostat()},50,True))
        with tempfile.TemporaryDirectory(dir=G.h.ROOT/'.local') as temp:
            root = Path(temp); directory = root/'block'; directory.mkdir()
            for name in ('truth.lh5', 'rng-before.rndm', 'rng-after.rndm', 'run.mac'):
                (directory/name).write_bytes(('synthetic sealed '+name).encode())
            hashes = {p.name: G.h.sha256(p) for p in directory.iterdir()}
            meta = {'source_sha256': {'transport/gegi_streaming_source.py': hashlib.sha256(original.encode()).hexdigest()},
                    'files_sha256': {'run.mac': hashes['run.mac']}}
            G.h.publish_json(directory/'prepared.json', meta)
            G.h.publish_json(directory/'run.json', {'status': 'complete', 'source_lh5_sha256': hashes['truth.lh5'],
                'rng_before_sha256': hashes['rng-before.rndm'], 'rng_after_sha256': hashes['rng-after.rndm']})
            G.h.publish_json(directory/'seal.json', {'status': 'sealed', 'artifacts': hashes})
            before = {p.name: p.read_bytes() for p in directory.iterdir()}
            package = root/'producer.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.writestr('END2END-Ge-Student/transport/gegi_streaming_source.py', original)
            with patch.object(G, 'verify', return_value={'status': 'sealed'}):
                record = G.admit_block_limit_continuation(directory, package)
            self.assertEqual(record['kind'], 'gegi_streaming_block_limit_continuation_v1')
            self.assertFalse((directory/'extraction-compatibility.json').exists())
            self.assertEqual(before, {name: (directory/name).read_bytes() for name in before})
            self.assertEqual(set(G._block_limit_compatibility(directory, meta)), {'transport/gegi_streaming_source.py'})
            with self.assertRaisesRegex(ValueError, 'Preserve existing'):
                G.admit_block_limit_continuation(directory, package)
            (directory/'run.json').write_bytes((directory/'run.json').read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'another sealed block'):
                G._block_limit_compatibility(directory, meta)

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
