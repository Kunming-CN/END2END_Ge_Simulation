"""PSD2 bounded known-signal and original-binding tests, SYNTHETIC fixtures only.

One Julia child exports one fixture; all reader/tamper tests are saved-only.
Synthetic files and failures remain under the PSD2 implementation evidence root.
"""
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import waveform_acquisition as A
import psd_features as P


class KnownSignal(unittest.TestCase):
    def setUp(self):
        self.p = copy.deepcopy(A.read_json(A.DEFAULT_PROFILE))
        self.c = A.read_json(P.W.ROOT/'simulation/readout_demo.json')

    def test_profile_units_grid_and_unknown_fields(self):
        self.assertEqual(A.validate_profile(self.p), self.p)
        for change in ({'measurement_polarity': 1}, {'extra': True}, {'sampling_rate_Hz': float('nan')},
                       {'noise': {'kind': 'postfilter_sampled_iid_gaussian_voltage', 'rms_V': 0, 'root_seed_uint64': str(2**64)}}):
            bad = copy.deepcopy(self.p); bad.update(change)
            with self.assertRaises(A.ControlError): A.validate_profile(bad)
        bad = copy.deepcopy(self.p); bad['bandwidth']['cutoff_Hz'] = bad['sampling_rate_Hz']/2
        with self.assertRaises(A.ControlError): A.validate_profile(bad)
        bad = copy.deepcopy(self.p); bad['record_window_ns'][0] = -1001
        with self.assertRaises(A.ControlError): A.validate_profile(bad)

    def test_floor_code_centres_and_bipolar_clipping(self):
        adc = {'bits': 3, 'minimum_V': -1.0, 'maximum_V': 1.0}
        for voltage, expected in [(0.0, (4, .125, False, False)), (-.5, (2, -.375, False, False)),
                                  (-1.0, (0, -.875, False, False)), (-1.01, (0, -.875, True, False)),
                                  (1.0, (7, .875, False, True))]:
            self.assertEqual(A.digitize(voltage, adc), expected)
        self.assertGreater(A.digitize(0.0, self.p['adc'])[1], 0.0)
        below_upper = A.digitize(math.nextafter(self.p['adc']['maximum_V'], -math.inf), self.p['adc'])
        self.assertEqual(below_upper[0], 2**self.p['adc']['bits']-1); self.assertFalse(below_upper[3])

    def test_uniform_sampling_negative_prehistory_and_no_unknown_tail(self):
        times = [float(i) for i in range(0, 102, 2)]; q = [0.0]+[10.0]*(len(times)-1)
        pre, filt = A.reference_frontend(times, q, self.c, 2.95, 1e7)
        self.p['record_window_ns'] = [-100.0, 200.0]
        trace, flags = A.reference_sample(times, pre, filt, self.p, '1')
        self.assertEqual(trace['time_since_origin_ns'], list(range(-100, 101, 10)))
        self.assertEqual(trace['signed_preamp_V'][:10], [0.0]*10)
        self.assertTrue(flags['record_exceeds_native_support']); self.assertEqual(trace['time_since_origin_ns'][-1], times[-1])
        self.assertLess(min(trace['signed_preamp_V']), 0)
        self.assertLess(min(trace['adc_center_V']), 0)
        self.p['sampling_rate_Hz'] = 1e9/3
        with self.assertRaises(A.ControlError): A.reference_sample(times, pre, filt, self.p, '1')

    def test_independent_injection_gain_charge_and_polarity(self):
        cal = A.reference_calibration(self.c, 2.95, 2.0, self.p)
        expected_charge = 500*1000/2.95*1.602176634e-19
        self.assertAlmostEqual(cal['charge_C'], expected_charge, delta=1e-28)
        self.assertLess(cal['peak_V'], .1); self.assertGreater(cal['peak_time_ns'], 0)
        for energy in (100.0, 1000.0):
            p = copy.deepcopy(self.p); p['calibration']['energy_keV'] = energy
            self.assertAlmostEqual(A.reference_calibration(self.c, 2.95, 2.0, p)['volts_per_keV'], cal['volts_per_keV'], delta=1e-15)
        narrow = copy.deepcopy(self.p); narrow['adc']['minimum_V'] = -.001
        with self.assertRaises(A.ControlError): A.reference_calibration(self.c, 2.95, 2.0, narrow)

    def test_noise_counter_repeatability_independence_and_conditional_bound(self):
        seed = A.noise_seed(self.p, 188, 0)
        self.assertEqual(seed, A.noise_seed(self.p, 188, 0))
        self.assertNotEqual(seed, A.noise_seed(self.p, 203, 0))
        self.assertNotEqual(seed, A.noise_seed(self.p, 188, 1))
        values = [A.normal(seed, i) for i in range(4096)]
        self.assertEqual([A.normal(seed, i) for i in (10, 0, 9)], [values[i] for i in (10, 0, 9)])
        self.assertLess(abs(sum(values)/len(values)), .05)
        self.assertTrue(.9 < sum(x*x for x in values)/len(values) < 1.1)
        cal = A.reference_calibration(self.c, 2.95, 2.0, self.p)
        self.p['noise']['rms_V'] = 1e-5
        bound = A.uncertainty(self.p, cal, len(values))
        self.assertTrue(bound['peak_noise_winner_bias_possible']); self.assertFalse(bound['physical_energy_resolution'])
        # A probabilistic model bound is checked on this declared deterministic sample;
        # this is not a measured confidence interval or a physical-resolution claim.
        self.assertLess(max(abs(x) for x in values)*1e-5/cal['volts_per_keV'], bound['simultaneous_noise_bound_keV'])


class SavedSynthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence = P.W.ROOT/'.local/psd-acquisition-v1/implementation/synthetic-tests'
        evidence.mkdir(parents=True, exist_ok=True)
        cls.root = Path(tempfile.mkdtemp(prefix='SYNTHETIC-', dir=evidence))
        for ref in A.SOURCE_REFS:
            destination = cls.root/ref; destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(P.W.ROOT/ref, destination)
        cls.run_dir = cls.root/'.local/runs/SYNTHETIC'; response = cls.run_dir/'response'; response.mkdir(parents=True)
        profile = A.read_json(P.W.ROOT/'simulation/native_readout_profile.json')
        frontend = A.read_json(P.W.ROOT/'simulation/readout_demo.json'); frontend.update(profile['settings'])
        frontend.update(schema_version=2, expected_primary_count=4); frontend.pop('max_total_samples')
        write = lambda path, value: path.write_bytes(A.encoded(value))
        write(response/'readout-config.json', frontend); write(response/'profile.json', profile)
        report = {'ionisation_energy_eV': 2.95, 'calibration': {'method': 'single delta-charge injection at t=0; SYNTHETIC',
            'volts_per_keV': .00049, 'time_step_ns': 2.0}, 'batch': {'batch_index': 0}, 'SYNTHETIC': True}
        write(response/'run.json', report)
        truths = []; scalars = []; endpoints = []; signals = []
        for pid, energies in enumerate(([], [10.0], [20.0], [10.0, -5.0])):
            identity = {'event_id': pid, 'global_decay_id': pid, 'global_initial_id': pid, 'batch_index': 0, 'local_initial_id': pid}
            groups = []; steps = []
            for gid, signal_energy in enumerate(energies):
                row = pid*10+gid; origin = 1000.0+pid*1000+gid*100
                group = {'group_id': gid, 'origin_time_ns': origin, 'row_indices': [row], 'relative_times_ns': [0.0],
                    'horizon_ns': 100000.0, 'boundary_split_within_horizon': False, 'recovery_not_established': False}
                groups.append(group); steps.append({'raw_row_index': row, 'energy_keV': abs(signal_energy), 'position_mm': [pid*1.0, gid*1.0, 0.0],
                    'time_ns': origin, 'raw': {'SYNTHETIC': True, 'row': row}})
                scalar = {**identity, 'record_kind': 'pulse', 'group_id': gid, 'group': group, 'origin_time_ns': origin, 'raw_row_indices': [row],
                    'deposited_energy_keV': abs(signal_energy), 'accepted': True, 'readout': {'accepted': True, 'reconstructed_energy_keV': abs(signal_energy)*.8,
                    'saturated': False, 'tail_truncated_possible': False}, 'transport_flags': {'step_limits': 0, 'stopped_without_contact': 0},
                    'seed_family': 123, 'native_min_charge_keV': min(0, signal_energy), 'native_max_charge_keV': max(0, signal_energy)}
                if pid == 2:
                    scalar.update(status='native_transport_failed', readout=None, accepted=False, transport_flags=None,
                        final_induced_keV=None, native_error={'exception': 'ArgumentError', 'message': 'SYNTHETIC domain failure'})
                else:
                    endpoints.append({**identity, 'group_id': gid, 'raw_row_index': row, 'seed_uint64': '18446744073709551615',
                        'endpoint': {'contact_ids': [1], 'status': 'geometric_contact', 'step_limit_reached': False, 'inside_semiconductor': True}})
                    for time_ns in range(0, 1002, 2):
                        # Bounded 10 ns ramp, then exact recorded constant charge.
                        charge = signal_energy*min(time_ns/10, 1)
                        signals.append({**identity, 'group_id': gid, 'time_since_origin_ns': time_ns, 'induced_equivalent_energy_keV': charge})
                scalars.append(scalar)
            truth = {**identity, 'steps': steps, 'pulse_groups': groups, 'SYNTHETIC': True}; truths.append(truth)
            scalars.append({**identity, 'record_kind': 'decay', 'group_id': None, 'zero_deposit': not energies,
                'deposited_energy_keV': sum(abs(e) for e in energies), 'pulse_count': len(groups), 'raw_row_indices': [s['raw_row_index'] for s in steps]})
        for name, rows in [('truth.jsonl', truths), ('scalars.jsonl', scalars), ('endpoints.jsonl', endpoints)]:
            (response/name).write_bytes(b''.join(A.encoded(row) for row in rows))
        with (response/'signals.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=P.SIGNAL_COLUMNS); writer.writeheader(); writer.writerows(signals)
        config = {'selection': {'name': 'SYNTHETIC', 'primary_count': 4}, 'operating_model': {'wiring_factor': 1}, 'SYNTHETIC': True}
        cls.config_sha = P.W.digest(config)
        receipt = {'kind': P.W.KIND, 'status': 'completed', 'configuration_sha256': cls.config_sha, 'resolved': config}
        write(cls.run_dir/'run.json', receipt); write(cls.run_dir/'resolved-config.json', {'configuration_sha256': cls.config_sha, 'resolved': config})
        write(cls.run_dir/'COMPLETE.json', {'SYNTHETIC': True, 'status': 'completed'})
        source_profile = A.read_json(P.DEFAULT_PROFILE); source_profile['analysis_window_ns'] = [0.0, 1000.0]
        profile_path = cls.root/'.local/source-profile.json'; write(profile_path, source_profile)
        source_out = P.default_bundle_dir(cls.root, cls.config_sha)
        with patch.object(P, 'inspect_saved_run', return_value=receipt): P.export_bundle(cls.run_dir, source_out, profile_path, root=cls.root)
        cls.source_pins = {ref: A.stamp(cls.root/ref) for ref in P.read_json(source_out/'manifest.json')['input_artifacts']}
        cls.profile = A.read_json(A.DEFAULT_PROFILE); cls.profile['record_window_ns'] = [-100.0, 1000.0]
        cls.profile['noise']['rms_V'] = 1e-5
        acquisition_profile = cls.root/'.local/acquisition-profile.json'; write(acquisition_profile, cls.profile)
        cls.output = A.default_bundle_dir(cls.root, cls.config_sha)
        cls.manifest = A.export_bundle(cls.run_dir, cls.output, acquisition_profile, root=cls.root)
        cls.bundle = A.load_bundle(cls.output, cls.config_sha, root=cls.root)
        cls.source = P.load_bundle(source_out, cls.config_sha, root=cls.root)

    def tamper_copy(self, suffix):
        target = self.root/'.local'/('TAMPER-'+suffix)
        shutil.copytree(self.output, target); return target

    def rehash(self, directory, names):
        manifest = A.read_json(directory/'manifest.json')
        for name in names:
            key = 'numerical_artifacts' if name in manifest['numerical_artifacts'] else 'artifacts'
            manifest[key][name] = A.stamp(directory/name)
        (directory/'manifest.json').write_bytes(A.encoded(manifest))
        complete = A.read_json(directory/'COMPLETE.json'); complete['manifest_sha256'] = A.sha(directory/'manifest.json')
        (directory/'COMPLETE.json').write_bytes(A.encoded(complete))

    def test_census_original_join_energy_and_native_failure_null(self):
        self.assertEqual(self.bundle['counts']['primaries'], 4); self.assertEqual(self.bundle['counts']['zero_deposit_primaries'], 1)
        self.assertEqual(self.bundle['counts']['pulse_groups'], 4); self.assertEqual(self.bundle['counts']['acquired_groups'], 3)
        for original, joined in zip(self.source['records'], self.bundle['records']):
            self.assertEqual(original['truth'], joined['truth']); self.assertEqual(original['primary'], joined['primary'])
            self.assertEqual(original['Erec_keV'], joined['Erec_keV'])
            for og, jg in zip(original['pulse_groups'], joined['pulse_groups']):
                self.assertEqual({k: v for k, v in jg.items() if k != 'acquisition'}, og)
        self.assertEqual(A.get_record(self.bundle, 0)['pulse_groups'], [])
        failed = A.get_record(self.bundle, 2, 0)['acquisition']
        self.assertEqual(failed['status'], 'native_transport_failed'); self.assertIsNone(failed['trace']); self.assertIsNone(failed['observed'])
        self.assertIsNone(failed['acquisition_energy_keV'])
        multi = A.get_record(self.bundle, 3); self.assertIsNone(multi['acquisition_energy_keV']); self.assertIsNone(multi['Erec_keV'])
        good = A.get_record(self.bundle, 1, 0)
        self.assertTrue(good['acquisition']['selection']['valid']); self.assertNotEqual(good['acquisition']['acquisition_energy_keV'], good['Erec_keV'])
        self.assertEqual(self.source_pins, {ref: A.stamp(self.root/ref) for ref in self.source_pins})

    def test_no_reader_execution_noise_repeat_and_cross_language_reference(self):
        with patch.object(A, 'run_numerical', side_effect=AssertionError('reader executed Julia')):
            repeated = A.load_bundle(self.output, self.config_sha, root=self.root)
        self.assertEqual(repeated, self.bundle)
        group = A.get_record(self.bundle, 1, 0); acq = group['acquisition']; trace = acq['trace']
        self.assertTrue(any(v != 0 for v in trace['noise_V']))
        self.assertEqual(trace['noise_V'], [self.profile['noise']['rms_V']*A.normal(acq['metadata']['derived_noise_seed_uint64'], i) for i in range(len(trace['noise_V']))])
        self.assertEqual(trace['time_since_origin_ns'], list(range(-100, 1001, 10)))
        # Fixed known charge predicts roughly 10 keV (finite ramp + quantization/noise).
        self.assertLess(abs(acq['acquisition_energy_keV']-10), .5)

    def test_lossless_csv_and_immutable_output(self):
        compact = A.read_json(self.output/'acquisition.json')['records']
        with (self.output/'acquisition.csv').open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([json.loads(row['record_json']) for row in rows], compact)
        with self.assertRaises(A.ControlError): A.export_bundle(self.run_dir, self.output, root=self.root)
        with self.assertRaises(A.ControlError): A.load_bundle(self.output, '0'*64, root=self.root)

    def test_deliberately_rehashed_adc_sample_fails_original_reference(self):
        directory = self.tamper_copy('ADC')
        numerical = A.read_json(directory/'numerical.json'); numerical['groups'][0]['acquisition']['trace']['adc_code'][20] += 1
        (directory/'numerical.json').write_bytes(A.encoded(numerical))
        execution = A.read_json(directory/'execution.json'); execution['numerical_sha256'] = A.sha(directory/'numerical.json')
        (directory/'execution.json').write_bytes(A.encoded(execution))
        data = A.read_json(directory/'acquisition.json'); data['provenance']['execution'] = execution
        data['records'] = A.compact_records(self.source, numerical, self.profile)
        (directory/'acquisition.json').write_bytes(A.encoded(data)); (directory/'acquisition.csv').write_bytes(A.csv_bytes(data['records']))
        self.rehash(directory, ('numerical.json', 'execution.json', 'acquisition.json', 'acquisition.csv'))
        with self.assertRaisesRegex(A.ControlError, 'value/identity changed'): A.load_bundle(directory, self.config_sha, root=self.root)

    def test_deliberately_rehashed_source_join_or_census_fails(self):
        directory = self.tamper_copy('JOIN')
        data = A.read_json(directory/'acquisition.json'); data['records'][1]['source_record_sha256'] = '0'*64
        data['records'][1]['acquisition_energy_keV'] = data['records'][1]['pulse_groups'][0]['acquisition']['observed']['acquisition_energy_keV']*10
        (directory/'acquisition.json').write_bytes(A.encoded(data)); (directory/'acquisition.csv').write_bytes(A.csv_bytes(data['records']))
        self.rehash(directory, ('acquisition.json', 'acquisition.csv'))
        with self.assertRaisesRegex(A.ControlError, 'raw identities/census'): A.load_bundle(directory, self.config_sha, root=self.root)

    def test_deliberately_rehashed_old_frontend_request_fails(self):
        directory = self.tamper_copy('FRONTEND')
        request = A.read_json(directory/'request.json'); request['batches'][0]['frontend_config']['gain'] += 1
        (directory/'request.json').write_bytes(A.encoded(request)); self.rehash(directory, ('request.json',))
        with self.assertRaisesRegex(A.ControlError, 'original full native inputs/settings'): A.load_bundle(directory, self.config_sha, root=self.root)

    def test_source_schema_and_profile_hashes_cannot_self_certify(self):
        for name, suffix, message in [('schema.json', 'SCHEMA', 'schema/template'), ('profile.json', 'PROFILE', 'profile binding')]:
            directory = self.tamper_copy(suffix); data = A.read_json(directory/name)
            if name == 'schema.json': data['scope'] = 'invented measured-hardware claim'
            else: data['noise']['root_seed_uint64'] = '7'
            (directory/name).write_bytes(A.encoded(data)); self.rehash(directory, (name,))
            with self.assertRaisesRegex(A.ControlError, message): A.load_bundle(directory, self.config_sha, root=self.root)

    def test_required_schema_and_serialization_rehash_rejected(self):
        for suffix, extra in [('EXTRA-FIELD', True), ('SERIALIZATION', False)]:
            directory = self.tamper_copy(suffix); data = A.read_json(directory/'acquisition.json')
            if extra:
                data['hardware_validated'] = True
                blob = A.encoded(data)
            else:
                blob = json.dumps(data, indent=2, allow_nan=False).encode()+b'\n'
            (directory/'acquisition.json').write_bytes(blob); self.rehash(directory, ('acquisition.json',))
            with self.assertRaisesRegex(A.ControlError, 'schema/serialization'): A.load_bundle(directory, self.config_sha, root=self.root)

    def test_signed_negative_ineligible_and_unknown_window_or_clip_null(self):
        negative = A.get_record(self.bundle, 3, 1)['acquisition']
        self.assertGreater(max(negative['trace']['signed_preamp_V']), 0)
        self.assertIsNone(negative['acquisition_energy_keV']); self.assertIn('nonpositive_signed_observed_span', negative['selection']['reasons'])
        noiseless = copy.deepcopy(self.profile); noiseless['noise']['rms_V'] = 0.0
        calibration = self.bundle['calibrations'][0]
        negative_reference = A.reference_acquire(A.get_record(self.source, 3, 1), calibration['frontend_config'],
            calibration['ionisation_energy_eV'], noiseless, calibration['calibration'])
        self.assertIn('nonpositive_acquisition_peak', negative_reference['selection']['reasons'])
        good = A.get_record(self.source, 1, 0); cal = self.bundle['calibrations'][0]; p = copy.deepcopy(self.profile)
        for change, reason in [({'record_window_ns': [-100.0, 1100.0]}, 'record_exceeds_native_support'),
                               ({'record_window_ns': [-100.0, 900.0]}, 'record_truncates_native_window'),
                               ({'adc': {'bits': 14, 'minimum_V': -.0001, 'maximum_V': .1}}, 'adc_lower_clipped')]:
            changed = copy.deepcopy(p); changed.update(change)
            result = A.reference_acquire(good, cal['frontend_config'], cal['ionisation_energy_eV'], changed, cal['calibration'])
            self.assertIn(reason, result['selection']['reasons']); self.assertIsNone(result['acquisition_energy_keV'])


if __name__ == '__main__':
    unittest.main()
