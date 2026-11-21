"""Integrated queue/continuation contracts with synthetic transport and native inputs."""
import copy
from contextlib import closing
import gzip
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
OBSERVATION = dict(kind='gegi_photon_step_sidecar_v1', file='photon-steps.csv', bytes=1720, sha256='d'*64,
                   executable_sha256='e'*64, observer_source_sha256='f'*64, observer_reader_sha256='a'*64)


def event(parent, clock, delay, source):
    point = [2., 3., 4.]
    return {'event_id': parent, 'parent_decay_id': parent, 'acquisition_id': 'test',
        'isotope': source, 'source_id': source, 'absolute_parent_time_ns': clock,
        'source_position_global_mm': [-40, 0, 40],
        'steps': [{'raw_row_index': 1, 'time_ns': delay, 'absolute_time_ns': clock+delay, 'energy_keV': 200.,
                   'deposit_id': ['test', parent, 0], 'position_mm': point, 'pre_position_mm': point,
                   'post_position_mm': point, 'track_id': 3, 'parent_track_id': 2, 'pdg': 11}],
        'decay_photons': [{'track_id': 2, 'parent_track_id': 1, 'time_ns': delay}],
        'candidate_photon_truth': {'ge_gamma_steps': [{'raw_row_index': 0, 'track_id': 2, 'parent_track_id': 1,
            'time_ns': delay, 'edep_keV': 0., 'pre_position_mm': [1., 2., 3.], 'post_position_mm': point}],
            'track_births': [{'track_id': 2, 'parent_track_id': 1, 'birth_time_ns': delay, 'birth_process': 'RadioactiveDecay'}]},
        'pulse_groups': [{'group_id': 0, 'origin_time_ns': delay, 'row_indices': [1]}]}


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
    groups = []
    def __init__(self, *args):
        self.process = type('Process', (), {'pid': os.getpid()})()
    def start(self): return {'channels': GEOMETRY, 'environment': {'kind': 'synthetic_native_runtime'}}
    def process_group(self, group, store):
        self.calls.append((group['event_id'], group['group_id']))
        self.groups.append(copy.deepcopy(group))
        return {'status': 'completed', 'event_id': group['event_id'], 'group_id': group['group_id'],
                'input_event_sha256': '3'*64, 'signals_sha256': '4'*64,
                'steps': [{'raw_row_index': row['raw_row_index'], 'endpoints': [{'species': 'electron',
                           'contact_ids': [3], 'status': 'contact'}]} for row in group['steps']]}
    def close(self): pass


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / '.local').mkdir()
        self.patches = [patch.object(A, 'ROOT', self.root), patch.object(A, 'OWN_SOURCES', ()),
            patch.object(A, 'OBSERVER_SOURCES', ()),
            patch.object(A.mixed, 'native_request', self.request),
            patch.object(A, 'transport_call', self.transport),
            patch.object(A.response, 'ResidentWorker', FakeWorker),
            patch.object(A.native_store, 'Store', FakeNative),
            patch.object(A.digital, 'terminal_contacts_complete', return_value=True)]
        for item in self.patches: item.start()
        FakeWorker.calls = []
        FakeWorker.groups = []
        self.failure_fixture = False

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def request(self, output, count, **options):
        path = output / 'native-request.json'
        A.candidates.write_new(path, {'synthetic': True, 'selection': {'primary_count': count},
            'numerics': {'drift_dt_ns': 1., 'drift_cap_ns': 1000.}, **options})
        return path

    def transport(self, args, log):
        action = args[0]
        def path(key): return (self.root / 'transport' / args[args.index(key)+1]).resolve()
        if action == 'init':
            config = A.W.read(path('--config'))
            state = {'next_block_index': 0, 'last_parent_time_ns': 0., 'safe_frontier_ns': 0., 'finished': False}
            if config['initial_state']['policy'] == A.STEADY_POLICY:
                state['initial_inventory'] = {'kind': 'synthetic_initial_inventory', 'policy': A.STEADY_POLICY,
                    'initial_nuclei': 10, 'remaining_nuclei': 10, 'generated_initial_daughter_decays': 0}
            A.W.write(path('--output'), state)
        elif action == 'process-block':
            self.assertIn('--candidate-truth', args)
            self.transport(['prepare-block', *args[1:]], log)
            directory = args[args.index('--output')+1]
            for stage in ('run-block', 'extract', 'verify'):
                self.transport([stage, '--directory', directory], log)
        elif action == 'prepare-block':
            directory = path('--output'); directory.mkdir(parents=True)
            A.W.write(directory / 'prepared.json', A.W.read(path('--checkpoint')))
            A.W.write(directory / 'source-config.json', A.W.read(path('--config')))
        elif action == 'run-block':
            A.W.write(path('--directory') / 'run.json', {'status': 'complete'})
        elif action == 'extract':
            directory = path('--directory'); before = A.W.read(directory / 'prepared.json')
            index = before['next_block_index']
            # Delayed parent 0 overlaps a later parent generated in block 1.
            rows = ([event(0, 1000., 5000., 'cs137'), event(1, 2000., 900000., 'cs137')]
                    if index == 0 else [event(2, 6000., 0., 'co60')])
            config = A.W.read(directory / 'source-config.json')
            duration = config['stop'].get('duration_ns')
            if duration is not None:
                daughter = event(1, 3000., 3000., 'cs137')
                daughter.update(parent_decay_id=None, new_parent_decay_id=None, initial_daughter_id=0,
                    origin='initial_daughter_inventory', isotope='Ba137m', source_pdg=1000561371,
                    absolute_decay_time_ns=3000.)
                rows = ([event(0, 1000., 5000., 'cs137'), daughter] if index == 0 else
                    [event(2, 7000., 0., 'co60'), event(3, 8000., duration-8000., 'cs137'),
                     event(4, 9000., duration-9000.+20., 'cs137')])
                if self.failure_fixture and index == 1:
                    rows = [event(2, 7000., 0., 'co60'), event(3, 9000., 0., 'cs137'),
                            event(4, 9500., duration-9500.+20., 'cs137')]
            stream = directory / 'stream'; stream.mkdir()
            for local, event_row in enumerate(rows):
                event_row.update(block_index=index, transport_event_id=local)
                if config.get(A.PHOTON_KINEMATICS):
                    photon = event_row['candidate_photon_truth']
                    chord = photon['ge_gamma_steps'][0]
                    photon['photon_step_observation_status'] = 'observed_exact'
                    chord['observed_transport_step'] = dict(
                        run_id=0, event_id=local, track_id=chord['track_id'], parent_track_id=chord['parent_track_id'],
                        step_number=3, process='compt',
                        pre={'kinetic_keV': 662., 'direction': [0., 0., -1.]},
                        post={'kinetic_keV': 462., 'direction': [1., 0., 0.]})
            (stream / 'events.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
            after = {'next_block_index': index+1, 'last_parent_time_ns': 2000. if index == 0 else 8000.,
                'safe_frontier_ns': 2000. if index == 0 else 8000., 'finished': index == 1}
            counts = {'zero_deposit_primaries': index, 'nonzero_primaries': 2-index}
            primary_count = 2
            if duration is not None:
                after.update(last_parent_time_ns=1000. if index == 0 else 9000.,
                    safe_frontier_ns=3000. if index == 0 else duration)
                if self.failure_fixture and index == 1:
                    after['last_parent_time_ns'] = 9500.
                if 'initial_inventory' in before:
                    after['initial_inventory'] = {**before['initial_inventory'], 'remaining_nuclei': 9,
                                                  'generated_initial_daughter_decays': 1}
                primary_count = 2 if index == 0 else 3
                counts = {'new_parent_primaries': 1 if index == 0 else 3,
                    'initial_daughter_primaries': 1 if index == 0 else 0,
                    'zero_deposit_parents': 0, 'nonzero_parents': 1 if index == 0 else 3,
                    'zero_deposit_initial_daughters': 0, 'nonzero_initial_daughters': 1 if index == 0 else 0,
                    'zero_deposit_primaries': 0, 'nonzero_primaries': primary_count}
            A.W.write(directory / 'checkpoint-after.json', after)
            A.W.write(stream / 'manifest.json', {'primary_count': primary_count, 'counts': counts,
                'block_index': index, 'candidate_photon_truth_kind': A.truth.PHOTON_KIND, 'source_lh5_sha256': '2'*64,
                'events_file': 'events.jsonl', 'events_sha256': A.mixed.file_sha(stream/'events.jsonl'),
                **({'source_contract': config, 'photon_step_observation': OBSERVATION}
                   if config.get(A.PHOTON_KINEMATICS) else {})})

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
        self.assertEqual(actual['retention']['candidate_truth']['status'], 'verified_exact')
        with gzip.open(complete/A.truth.ARTIFACT, 'rb') as expected_truth, gzip.open(resumed/A.truth.ARTIFACT, 'rb') as resumed_truth:
            self.assertNotEqual(expected_truth.readline(), resumed_truth.readline())
            self.assertEqual(expected_truth.read(), resumed_truth.read())
        with gzip.open(resumed/A.truth.ARTIFACT, 'rt', encoding='utf-8') as handle:
            truth_rows = [json.loads(line) for line in handle]
        retained_triggers = {row['original_trigger_id']: row for row in truth_rows if row['record'] == 'trigger_context'}
        driver_rows = {row['driver_id']: row for row in truth_rows if row['record'] == 'transport_event'}
        delivered_groups = {row['input_group_ordinal']: row for row in truth_rows if row['record'] == 'input_group_response'}
        self.assertEqual(set(delivered_groups), {i for row in retained_triggers.values() for i in row['input_group_ordinals']})
        self.assertEqual(set(driver_rows), {row['driver_id'] for row in delivered_groups.values()})
        self.assertEqual(driver_rows[0]['ge_gamma_steps'][0]['edep_keV'], 0.)
        self.assertEqual(driver_rows[0]['ge_gamma_steps'][0]['absolute_time_ns'], 6000.)
        self.assertEqual(driver_rows[0]['photon_step_observation'], {'status': 'unavailable_not_recorded'})
        self.assertEqual(driver_rows[0]['positive_ge_deposits'][0]['raw_row_index'], 1)
        self.assertEqual(next(row for row in delivered_groups.values() if row['driver_id'] == 0)
                         ['native_steps'][0]['endpoints'][0]['contact_ids'], [3])
        self.assertEqual(A.candidates.verify_candidates(resumed / S.ARCHIVE_NAME)['status'], 'verified_exact')
        for trigger in S.list_candidates(resumed / S.ARCHIVE_NAME):
            got = S.load_candidate(resumed / S.ARCHIVE_NAME, trigger['trigger_id'])
            want = S.load_candidate(complete / S.ARCHIVE_NAME, trigger['trigger_id'])
            self.assertEqual(got['readout'], want['readout'])
            self.assertEqual(got['context']['adc_codes'].tolist(), want['context']['adc_codes'].tolist())
            self.assertEqual(retained_triggers[trigger['trigger_id']]['input_group_ordinals'], got['identities'])
            self.assertNotIn('candidate_photon_truth', got['card'])

    def test_opt_in_photon_kinematics_survive_resume_outside_reconstruction(self):
        ordinary = self.root / '.local/ordinary'
        observed = self.root / '.local/observed'
        untouched = A.run(ordinary, 4, block_parents=2)
        plain_groups = FakeWorker.groups[:]
        FakeWorker.groups = []
        A.run(observed, 4, block_parents=2, stop_after_blocks=1, retain_photon_kinematics=True)
        with self.assertRaisesRegex(ValueError, 'original sources'):
            A.run(observed, 4, resume=True, block_parents=2, retain_photon_kinematics=False)
        result = A.run(observed, 4, resume=True, block_parents=2)
        self.assertTrue(result['identity']['source_config'][A.PHOTON_KINEMATICS])
        self.assertEqual(FakeWorker.groups, plain_groups)
        for field in ('source', 'counts', 'spectra', 'storage_counts', 'readout'):
            self.assertEqual(result[field], untouched[field])
        with gzip.open(observed/A.truth.ARTIFACT, 'rt', encoding='utf-8') as stream:
            rows = [json.loads(line) for line in stream]
        driver_rows = [r for r in rows if r['record'] == 'transport_event']
        self.assertGreater(len(driver_rows), 0)
        self.assertEqual(result['retention']['candidate_truth']['photon_step_observation'],
                         {'observed_exact': len(driver_rows), 'unavailable_not_recorded': 0})
        for row in driver_rows:
            self.assertEqual(row['photon_step_observation'], {'status': 'observed_exact', **OBSERVATION})
            step = row['ge_gamma_steps'][0]['observed_transport_step']
            self.assertEqual((step['process'], step['pre']['kinetic_keV'], step['post']['direction']), ('compt', 662., [1., 0., 0.]))
            self.assertEqual(step['event_id'], row['transport_event_id'])
        self.assertFalse((observed/A.truth.SCRATCH).exists())
        for trigger in S.list_candidates(observed / S.ARCHIVE_NAME):
            actual = S.load_candidate(observed / S.ARCHIVE_NAME, trigger['trigger_id'])
            baseline = S.load_candidate(ordinary / S.ARCHIVE_NAME, trigger['trigger_id'])
            self.assertEqual(actual['card'], baseline['card'])
            self.assertEqual(actual['context']['adc_codes'].tolist(), baseline['context']['adc_codes'].tolist())

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
        self.assertEqual(result['retention']['candidate_truth']['status'], 'verified_exact')
        self.assertFalse((output/A.truth.SCRATCH).exists())
        self.assertIn(A.truth.SCRATCH, [row['path'] for row in A.W.read(output/'scratch-retirement.json')['files']])

    def test_completed_resume_requires_intact_candidate_truth_after_scratch_retirement(self):
        output = self.root / '.local/completed-truth'
        settings = {'primary_count': 4, 'block_parents': 2}
        A.run(output, **settings)
        self.assertFalse((output/A.truth.SCRATCH).exists())
        calls = list(FakeWorker.calls)
        artifact = output/A.truth.ARTIFACT
        original = artifact.read_bytes()
        self.assertEqual(A.run(output, resume=True, **settings)['status'], 'completed')
        for corrupted in (None, bytes([original[0]^1])+original[1:]):
            if corrupted is None:
                artifact.unlink()
            else:
                artifact.write_bytes(corrupted)
            with self.assertRaisesRegex(ValueError, 'candidate truth is missing or differs'):
                A.run(output, resume=True, **settings)
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

    def test_explicit_native_continuation_keeps_candidate_identity_and_group_phases(self):
        self.assert_continuation(1, 'native-only', 'native-only-continuation.json', A.continuation)

    def test_stream_id_repair_keeps_checkpoint_and_never_repeats_completed_groups(self):
        self.assert_continuation(2, 'stream-id-repair', 'stream-id-continuation.json', A.stream_ids)

    def assert_continuation(self, phase, namespace, receipt_path, module):
        output = self.root / '.local/native-continuation'
        A.run(output, 4, block_parents=2, stop_after_groups=1, retain_validation_inputs=True)
        original_request = (output / 'native-request.json').read_bytes()
        with closing(sqlite3.connect(output / S.ARCHIVE_NAME)) as db:
            original_metadata = db.execute('SELECT body FROM metadata').fetchone()[0]
        original_identity = json.loads(original_metadata)['identity']
        (output / namespace).mkdir()
        request = output / namespace / 'native-request.json'
        A.W.write(request, {'synthetic': True, 'response_mode': 'native_signals_only_v1',
                            'numerics': {'drift_dt_ns': 1., 'drift_cap_ns': 1000.}})
        A.W.write(output / receipt_path, {'synthetic_admission_fixture': True})
        active = {'original_identity': original_identity, 'active_request': request,
            'active_spool': output / namespace / 'native-spool',
            'active_store': output / namespace / 'native-scratch.sqlite',
            'native_phase': phase, 'receipt_path': receipt_path}
        with patch.object(module, 'admit', return_value=active):
            result = A.run(output, 4, block_parents=2, resume=True, retain_validation_inputs=True)
        self.assertEqual(result['identity'], original_identity)
        self.assertEqual(result['execution_provenance']['native_processing_phase'], phase)
        self.assertEqual(result['execution_provenance']['continuation_receipt']['path'], receipt_path)
        self.assertNotEqual(result['execution_provenance']['active_producer_identity']['native_request_sha256'],
                            original_identity['native_request_sha256'])
        self.assertEqual((output / 'native-request.json').read_bytes(), original_request)
        with closing(sqlite3.connect(output / S.ARCHIVE_NAME)) as db:
            self.assertEqual(db.execute('SELECT body FROM metadata').fetchone()[0], original_metadata)
            self.assertEqual(dict(db.execute('SELECT phase,count(*) FROM native_processing_phases GROUP BY phase')), {0: 1, phase: 1})
        self.assertEqual(FakeWorker.calls, [(0, 0), (2, 0)])

    def test_native_runtime_change_refuses_before_new_drift(self):
        output = self.root / '.local/changed-native-runtime'
        A.run(output, 4, block_parents=2, stop_after_groups=1)
        calls = list(FakeWorker.calls)
        with patch.object(FakeWorker, 'start', return_value={'channels': GEOMETRY, 'environment': {'kind': 'changed'}}):
            with self.assertRaisesRegex(ValueError, 'runtime versions changed'):
                A.run(output, 4, block_parents=2, resume=True)
        self.assertEqual(FakeWorker.calls, calls)

    def test_five_second_request_is_minimal_and_initial_inventory_resolves_in_checkpoint(self):
        output = self.root / '.local/five-second-prefix'
        stopped = A.run(output, duration_s=5, initial_state_policy=A.STEADY_POLICY,
                        block_parents=2, stop_after_groups=1, retain_validation_inputs=True)
        self.assertEqual(stopped['status'], 'stopped')
        config = A.W.read(output / 'source-config.json')
        self.assertEqual(config['stop'], {'mode': 'duration', 'duration_ns': 5e9})
        self.assertEqual(config['initial_state'], {'policy': 'secular_equilibrium_poisson_daughters_v1',
                                                   'acquisition_start_ns': 0})
        with closing(sqlite3.connect(output / S.ARCHIVE_NAME)) as db:
            state = json.loads(db.execute('SELECT state FROM checkpoint').fetchone()[0])
        self.assertEqual(state['source_checkpoint']['initial_inventory']['initial_nuclei'], 10)
        self.assertTrue(state['readout']['pulses'])
        self.assertLess(state['readout']['next_sample_index'], 1000)
        self.assertEqual(state['stage_timings']['stages']['native_group']['count'], 1)
        request = A.W.read(output / 'native-request.json')
        self.assertEqual(request['event_id_policy'], 'streaming_transport_driver_v1')
        self.assertEqual(request['selection']['primary_count'], 1110000)
        for invalid in (0, -1, True, float('inf'), float('nan')):
            with self.subTest(duration=invalid), self.assertRaisesRegex(ValueError, 'positive finite'):
                A.run(self.root / '.local/rejected-duration', duration_s=invalid,
                      initial_state_policy=A.STEADY_POLICY)
        self.assertFalse((self.root / '.local/rejected-duration').exists())

    def test_user_duration_count_and_block_size_have_no_artificial_ceiling(self):
        # Synthetic transport stops after its first tiny block: no long simulation.
        for label, settings in (
            ('duration', {'duration_s': 90.09, 'initial_state_policy': A.STEADY_POLICY}),
            ('count', {'primary_count': 20000000}),
        ):
            with self.subTest(label=label):
                output = self.root / '.local' / label
                result = A.run(output, **settings, block_parents=20000, stop_after_blocks=1)
                self.assertEqual(result['status'], 'stopped')
                config = A.W.read(output / 'source-config.json')
                expected = ({'mode': 'duration', 'duration_ns': 90.09e9} if label == 'duration'
                            else {'mode': 'count', 'parent_count': 20000000})
                self.assertEqual(config['stop'], expected)
                self.assertEqual(FakeWorker.calls, [])

    def test_duration_exact_cutoff_separate_daughter_census_and_nullable_parent_identity(self):
        output = self.root / '.local/duration-completed'
        duration_s = .00002
        result = A.run(output, duration_s=duration_s, initial_state_policy=A.STEADY_POLICY,
                       block_parents=2, retain_validation_inputs=True)
        self.assertEqual(result['live_time_ns'], 20000.)
        self.assertNotEqual(result['live_time_ns'], 9000.+A.mixed.READOUT_TAIL_NS)
        self.assertEqual(result['readout']['sample_frames_processed'], 1000)
        census = result['source']
        self.assertEqual(census['initial_parents'], 4)
        self.assertEqual(census['initial_daughter_decays'], 1)
        self.assertEqual(census['transport_primaries'], 5)
        self.assertEqual(census['zero_deposit_parents']+census['nonzero_parents'], 4)
        self.assertEqual(census['zero_deposit_initial_daughters']+census['nonzero_initial_daughters'], 1)
        self.assertEqual(census['delayed_groups_after_acquisition'], 2)
        self.assertEqual(FakeWorker.calls, [(0, 0), (1, 0), (2, 0)])
        initial = next(group for group in FakeWorker.groups if group['event_id'] == 1)
        self.assertIsNone(initial['parent_event_metadata']['parent_decay_id'])
        self.assertIsNone(initial['parent_event_metadata']['new_parent_decay_id'])
        self.assertEqual(initial['parent_event_metadata']['initial_daughter_id'], 0)
        self.assertEqual(result['source_initial_state']['initial_nuclei'], 10)
        with gzip.open(output/'input-groups.jsonl.gz', 'rt', encoding='utf-8') as handle:
            ledger = [json.loads(line) for line in handle]
        daughter = next(row for row in ledger if row['initial_daughter_id'] == 0)
        self.assertIsNone(daughter['parent_decay_id'])
        self.assertIsNone(daughter['new_parent_decay_id'])
        self.assertEqual(daughter['global_decay_id'], 1)
        self.assertEqual(daughter['origin'], 'initial_daughter_inventory')
        self.assertEqual(sorted(row['first_ge_deposit_ns'] for row in ledger
                                if row['status'] == 'daughter_deposits_after_acquisition'), [20000., 20020.])

    def test_duration_stop_resume_restores_stage_counts_without_repeating_native_groups(self):
        output = self.root / '.local/duration-resumed'
        settings = {'duration_s': .00002, 'initial_state_policy': A.STEADY_POLICY,
                    'block_parents': 2, 'retain_validation_inputs': True}
        stopped = A.run(output, **settings, stop_after_groups=1)
        self.assertEqual(stopped['status'], 'stopped')
        with closing(sqlite3.connect(output/S.ARCHIVE_NAME)) as db:
            before = json.loads(db.execute('SELECT state FROM checkpoint').fetchone()[0])
        native_before = before['stage_timings']['stages']['native_group']
        load_before = before['stage_timings']['stages']['native_worker_load']
        self.assertEqual(native_before['count'], 1)
        result = A.run(output, **settings, resume=True)
        native_after = result['stage_timings']['stages']['native_group']
        self.assertEqual(native_after['count'], 3)
        self.assertGreaterEqual(native_after['total_seconds'], native_before['total_seconds'])
        self.assertEqual(result['stage_timings']['stages']['native_worker_load']['count'], load_before['count']+1)
        self.assertEqual(result['stage_timings']['native_outcomes'], {'completed': 3, 'failed': 0, 'unavailable': 0})
        self.assertEqual(FakeWorker.calls, [(0, 0), (1, 0), (2, 0)])
        self.assertEqual(result['live_time_ns'], 20000.)

    def test_future_native_failure_excludes_prior_trigger_before_it_can_commit(self):
        self.failure_fixture = True
        process, read = FakeWorker.process_group, FakeNative.read

        def process_with_failure(worker, group, store):
            result = process(worker, group, store)
            if group['event_id'] == 3:
                return dict(result, status='native_failed', error='preserved synthetic domain failure')
            return result

        def read_with_failure(store, parent, group, **kwargs):
            return ({'status': 'native_failed'}, None) if parent == 3 else read(store, parent, group, **kwargs)

        output = self.root / '.local/future-failure'
        with patch.object(FakeWorker, 'process_group', process_with_failure), \
                patch.object(FakeNative, 'read', read_with_failure), \
                patch.object(A.digital, 'terminal_contacts_complete', side_effect=lambda event: event['status'] == 'completed'):
            result = A.run(output, duration_s=.00002, initial_state_policy=A.STEADY_POLICY,
                           block_parents=2, retain_validation_inputs=True)
        self.assertEqual(FakeWorker.calls, [(0, 0), (1, 0), (2, 0), (3, 0)])
        self.assertEqual(result['source']['unavailable_native_groups'], 1)
        self.assertEqual(result['stage_timings']['native_outcomes'], {'completed': 3, 'failed': 1, 'unavailable': 0})
        self.assertEqual(result['counts']['qualified_triggers'], 0)
        self.assertEqual(result['storage_counts']['saved_candidates'], 0)
        self.assertEqual(result['retention']['candidate_truth']['counts'],
                         {'trigger_context': 0, 'transport_event': 0, 'input_group_response': 0})
        self.assertGreater(result['storage_counts']['selection_reason_counts'].get('unknown_native_history', 0), 0)
        expected = A.dual._history_mask([{'first_ge_deposit_ns': 9000., 'last_ge_deposit_ns': 9000.,
                                         'positive_ge_energy_keV': 200.}], 20000.)
        self.assertEqual(result['excluded_intervals_ns'], expected)
        with closing(sqlite3.connect(output/S.ARCHIVE_NAME)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM native_failures').fetchone()[0], 1)


if __name__ == '__main__': unittest.main()
