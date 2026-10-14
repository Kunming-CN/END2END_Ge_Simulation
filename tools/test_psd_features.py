"""PSD1 known-signal and saved-only contracts using explicitly SYNTHETIC fixtures.

No physics/stage/calibration execution or production derivative is performed.
"""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch

import psd_features as P


def profile(end=20, width=4, polarity=1):
    value = copy.deepcopy(P.read_json(P.DEFAULT_PROFILE))
    value['analysis_window_ns'] = [0.0, float(end)]
    value['current_filter']['width_ns'] = float(width)
    value['polarity'] = polarity
    return value


def deposit(row, position, energy=1):
    return {'raw_row_index': row, 'energy_keV': energy, 'position_mm': position,
            'time_ns': 1000 + row, 'raw': {'evtid': 1, 'edep': energy, 'SYNTHETIC': True}}


def group_fixture(pid=1, gid=0, batch=0, accepted=True, failed=False):
    g = {'group_id': gid, 'origin_time_ns': 1001.0, 'row_indices': [1],
         'relative_times_ns': [0.0], 'horizon_ns': 100000,
         'boundary_split_within_horizon': False, 'recovery_not_established': False}
    identity = {'event_id': pid, 'global_decay_id': pid, 'global_initial_id': pid,
                'batch_index': batch, 'local_initial_id': pid}
    scalar = {**identity, 'record_kind': 'pulse', 'group_id': gid, 'group': g,
              'origin_time_ns': g['origin_time_ns'], 'raw_row_indices': [1], 'deposited_energy_keV': 10.0,
              'accepted': accepted, 'readout': {'accepted': accepted, 'reconstructed_energy_keV': 8.0,
                  'saturated': False, 'tail_truncated_possible': False},
              'transport_flags': {'step_limits': 0, 'stopped_without_contact': 0}, 'seed_family': 123,
              'native_min_charge_keV': 0.0, 'native_max_charge_keV': 20.0}
    if failed:
        scalar.update(status='native_transport_failed', readout=None, accepted=False, transport_flags=None,
                      final_induced_keV=None, native_error={'exception': 'ArgumentError', 'message': 'SYNTHETIC domain failure'})
    endpoints = [] if failed else [{**identity, 'group_id': gid, 'raw_row_index': 1,
                  'seed_uint64': '18446744073709551615', 'endpoint': {'contact_ids': [1],
                  'status': 'geometric_contact', 'step_limit_reached': False, 'inside_semiconductor': True}}]
    return scalar, endpoints


class KnownSignals(unittest.TestCase):
    def test_units_box_average_and_rise_have_independent_closed_form(self):
        # Q=2*t keV, eion=2 eV => I=(2*1000/2*e)*1e18 nA.
        t = list(range(21)); q = [2 * x for x in t]
        sig, obs = P.waveform_observables(t, q, 2, profile())
        expected = 160.2176634
        self.assertAlmostEqual(obs['signed_filtered_current_peak_nA'], expected, places=10)
        self.assertEqual(obs['t10_ns'], 2)
        self.assertEqual(obs['t90_ns'], 18)
        self.assertEqual(obs['charge_rise_10_90_ns'], 16)
        self.assertEqual(sig['filtered_midpoint_ns'][0], 2.5)
        self.assertEqual(sig['filtered_midpoint_ns'][-1], 17.5)
        self.assertTrue(all(math_value == expected for math_value in sig['signed_current_nA']))
        self.assertAlmostEqual(sig['signed_charge_fC'][-1], 3.204353268, places=11)

    def test_nonuniform_time_filter_uses_physical_duration_and_no_padding(self):
        # Independent integral: overlap original interval currents with 3 ns window.
        t = [0.0, 1.0, 3.0, 4.0, 8.0, 10.0]; q = [0.0, 0.0, 4.0, 7.0, 7.0, 8.0]
        sig, obs = P.waveform_observables(t, q, 2.95, profile(end=10, width=3))
        for center, result in zip(sig['filtered_midpoint_ns'], sig['filtered_signed_current_nA']):
            integral = 0.0
            for i in range(len(t) - 1):
                overlap = max(0, min(t[i+1], center+1.5) - max(t[i], center-1.5))
                integral += (q[i+1]-q[i]) / (t[i+1]-t[i]) * overlap
            expected = integral/3*1000/2.95*1.602176634e-19*1e18
            self.assertAlmostEqual(result, expected, places=12)
        self.assertEqual(sig['filtered_midpoint_ns'], [2.0, 3.5, 6.0])
        # Center 2 integrates 5.5 keV; center 3.5 integrates 5 keV.
        self.assertEqual(obs['peak_time_since_origin_ns'], 2.0)

    def test_declared_polarity_preserves_native_sign_and_no_event_gain(self):
        t = list(range(21)); q = [-x for x in t]
        native, obs = P.waveform_observables(t, q, 2.95, profile(polarity=-1))
        self.assertLess(obs['native_signed_current_at_peak_nA'], 0)
        self.assertGreater(obs['signed_filtered_current_peak_nA'], 0)
        self.assertTrue(all(x < 0 for x in native['signed_current_nA']))
        _, invalid = P.waveform_observables(t, q, 2.95, profile(polarity=1))
        self.assertIn('nonpositive_signed_observed_span', invalid['flags'])
        self.assertIsNone(invalid['charge_rise_10_90_ns'])
        scalar, endpoints = group_fixture()
        truth = {'steps': [deposit(1, [0, 0, 0], 10)]}
        record = P.group_record(scalar, truth, endpoints, (t, t), 2.95, profile())
        amplitude = 1000/2.95*1.602176634e-19*1e18
        self.assertAlmostEqual(record['features']['A_over_E_nA_per_keV'], amplitude/8)
        self.assertNotAlmostEqual(record['features']['A_over_E_nA_per_keV'], amplitude/10)
        scalar['deposited_energy_keV'] = 1000000
        repeated = P.group_record(scalar, truth, endpoints, (t, t), 2.95, profile())
        self.assertEqual(record['features'], repeated['features'])

    def test_first_crossing_and_nonmonotonic_observed_span(self):
        t = [0, 1, 2, 3, 4]; q = [0, 2, 0, 5, 10]
        _, obs = P.waveform_observables(t, q, 2.95, profile(end=4, width=1))
        self.assertEqual(obs['t10_ns'], 0.5)
        self.assertEqual(obs['t90_ns'], 3.8)
        self.assertAlmostEqual(obs['charge_rise_10_90_ns'], 3.3)
        self.assertIn('nonmonotonic_signed_observed_charge', obs['flags'])
        _, zero = P.waveform_observables(t, [0]*5, 2.95, profile(end=4, width=1))
        self.assertIsNone(zero['t10_ns'])
        self.assertIsNone(zero['charge_rise_10_90_ns'])

    def test_invalid_inputs_and_fixed_window_cannot_extrapolate(self):
        for t, q in [([0, 0], [0, 1]), ([1, 2], [0, 1]), ([0, 1], [0, float('nan')])]:
            with self.assertRaises(P.ControlError): P.waveform_observables(t, q, 2.95, profile())
        _, observed = P.waveform_observables([0, 1], [0, 1], 2.95, profile())
        self.assertIn('trace_does_not_cover_analysis_window', observed['flags'])
        self.assertIsNone(observed['charge_rise_10_90_ns'])

    def test_caps_rejection_saturation_and_native_failure_are_null_with_reasons(self):
        scalar, endpoints = group_fixture(); truth = {'steps': [deposit(1, [0, 0, 0], 10)]}
        for changes, reason in [({'transport_flags': {'step_limits': 1}}, 'native_step_limit'),
                                ({'readout': {'accepted': False, 'reconstructed_energy_keV': 8}}, 'readout_rejected'),
                                ({'readout': {'accepted': True, 'saturated': True, 'reconstructed_energy_keV': 8}}, 'readout_saturated'),
                                ({'readout': {'accepted': True, 'reconstructed_energy_keV': 0}}, 'invalid_reconstructed_energy')]:
            changed = copy.deepcopy(scalar); changed.update(changes)
            record = P.group_record(changed, truth, endpoints, (list(range(21)), list(range(21))), 2.95, profile())
            self.assertIn(reason, record['selection']['reasons'])
            self.assertTrue(all(x is None for x in record['features'].values()))
            self.assertIsNotNone(record['observed']['signed_filtered_current_peak_nA'])
        failed, no_endpoints = group_fixture(failed=True)
        record = P.group_record(failed, truth, no_endpoints, None, 2.95, profile())
        self.assertIsNone(record['signal']); self.assertIsNone(record['observed']); self.assertIsNone(record['Erec_keV'])
        self.assertEqual(record['saved_scalar']['native_error']['message'], 'SYNTHETIC domain failure')
        self.assertIn('native_transport_failed', record['selection']['reasons'])

    def test_topology_is_spatial_rule_and_threshold_sensitive_with_chaining(self):
        steps = [deposit(0, [0, 0, 0]), deposit(1, [0.75, 0, 0]), deposit(2, [1.5, 0, 0]),
                 deposit(3, [5, 0, 0]), deposit(4, [100, 0, 0], 0)]
        result = P.topology(steps, profile())
        self.assertEqual([x['cluster_count'] for x in result['sensitivity']], [4, 2, 2])
        self.assertEqual(result['clusters_raw_row_indices'], [[0, 1, 2], [3]])
        self.assertEqual(result['positive_energy_point_count'], 4)
        self.assertTrue(result['threshold_sensitive'])
        self.assertEqual(result['proxy_label'], 'multiple_spatial_clusters_proxy')
        self.assertEqual(P.topology([steps[-1]], profile())['cluster_count'], 0)


class SyntheticBundle(unittest.TestCase):
    def setUp(self):
        evidence = P.W.ROOT / '.local/nonzero-storage-p2/synthetic-tests'
        evidence.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='SYNTHETIC-', dir=evidence))
        self.addCleanup(self.cleanup_owned_fixture)
        for ref in P.SOURCE_REFS:
            dest = self.root/ref; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(P.W.ROOT/ref, dest)
        self.run = self.root/'.local/runs/SYNTHETIC'; self.response = self.run/'response'
        self.response.mkdir(parents=True)
        scalar, endpoints = group_fixture()
        self.nonzero = {**{k: scalar[k] for k in ('event_id', 'global_decay_id', 'global_initial_id', 'batch_index', 'local_initial_id')},
                        'steps': [deposit(0, [7, 0, 0], 0), deposit(1, [0, 0, 0], 10)], 'pulse_groups': [scalar['group']],
                        'SYNTHETIC': True}
        zero = {'event_id': 0, 'global_decay_id': 0, 'global_initial_id': 0, 'batch_index': 0, 'local_initial_id': 0,
                'steps': [deposit(9, [9, 0, 0], 0)], 'pulse_groups': [], 'SYNTHETIC': True}
        primaries = [{**{k: truth[k] for k in ('event_id', 'global_decay_id', 'global_initial_id', 'batch_index', 'local_initial_id')},
                      'record_kind': 'decay', 'group_id': None, 'zero_deposit': pid == 0,
                      'deposited_energy_keV': pid*10.0, 'pulse_count': pid,
                      'raw_row_indices': [x['raw_row_index'] for x in truth['steps']]}
                     for pid, truth in enumerate([zero, self.nonzero])]
        self.write_lines('truth.jsonl', [zero, self.nonzero]); self.write_lines('scalars.jsonl', [primaries[0], primaries[1], scalar])
        self.write_lines('endpoints.jsonl', endpoints)
        with (self.response/'signals.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=P.SIGNAL_COLUMNS); writer.writeheader()
            for time in range(21):
                writer.writerow({**{k: scalar[k] for k in P.SIGNAL_COLUMNS[:6]}, 'time_since_origin_ns': time,
                                 'induced_equivalent_energy_keV': time})
        self.config = {'selection': {'name': 'SYNTHETIC', 'primary_count': 2}, 'operating_model': {'wiring_factor': 1}, 'SYNTHETIC': True}
        self.receipt = {'kind': P.W.KIND, 'status': 'completed', 'configuration_sha256': P.W.digest(self.config), 'resolved': self.config}
        self.report = {'ionisation_energy_eV': 2.95, 'calibration': {'method': 'single delta-charge injection at t=0; SYNTHETIC',
                       'volts_per_keV': 0.1}, 'SYNTHETIC': True, 'batch': {'batch_index': 0}}
        self.write(self.response/'run.json', self.report)
        self.write(self.response/'readout-config.json', {'SYNTHETIC': True})
        self.write(self.response/'profile.json', {'SYNTHETIC': True})
        self.write(self.run/'run.json', self.receipt)
        self.write(self.run/'resolved-config.json', {'configuration_sha256': self.receipt['configuration_sha256'], 'resolved': self.config})
        self.write(self.run/'COMPLETE.json', {'SYNTHETIC': True, 'status': 'completed'})
        self.profile_path = self.root/'.local/SYNTHETIC-profile.json'; self.write(self.profile_path, profile())
        self.out = P.default_bundle_dir(self.root, self.receipt['configuration_sha256'])

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(P.encoded(value))

    def cleanup_owned_fixture(self):
        expected = (P.W.ROOT/'.local/nonzero-storage-p2/synthetic-tests').resolve()
        self.assertTrue(self.root.resolve().is_relative_to(expected))
        for path in [self.root, *self.root.rglob('*')]:
            self.assertFalse(path.is_symlink() or path.is_junction())
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
        shutil.rmtree(self.root)

    def write_lines(self, name, rows):
        (self.response/name).write_bytes(b''.join(P.encoded(x) for x in rows))

    def export(self):
        with patch.object(P, 'inspect_saved_run', return_value=self.receipt) as checker:
            result = P.export_bundle(self.run, self.out, self.profile_path, root=self.root)
            checker.assert_called_once_with(self.run.resolve(), self.root.resolve())
        return result

    def rehash(self, name):
        manifest = P.read_json(self.out/'manifest.json'); manifest['artifacts'][name] = P.stamp(self.out/name)
        self.write(self.out/'manifest.json', manifest)
        complete = P.read_json(self.out/'COMPLETE.json'); complete['manifest_sha256'] = P.sha(self.out/'manifest.json')
        self.write(self.out/'COMPLETE.json', complete)

    def test_complete_census_nonzero_storage_seeds_and_lossless_csv(self):
        manifest = self.export(); bundle = P.load_bundle(self.out, self.receipt['configuration_sha256'], root=self.root)
        self.assertEqual(manifest['event_storage'], P.N.descriptor(2, 1))
        self.assertEqual(manifest['counts']['primaries'], 2)
        self.assertEqual(manifest['counts']['efficiency_denominator'], 2)
        self.assertEqual(manifest['counts']['zero_deposit_primaries'], 1)
        self.assertEqual(manifest['counts']['stored_primaries'], 1)
        self.assertEqual([r['global_initial_id'] for r in bundle['records']], [1])
        with self.assertRaises(P.ControlError): P.get_record(bundle, 0)
        self.assertEqual(len(P.get_record(bundle, 1)['truth']['steps']), 2)
        pulse = P.get_record(bundle, 1, 0)
        self.assertEqual(pulse['raw_row_indices'], [1])
        self.assertEqual(pulse['endpoints'][0]['seed_uint64'], '18446744073709551615')
        with (self.out/'features.csv').open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['Erec_keV'], '8.0'); self.assertEqual(rows[0]['selection_valid'], 'true')
        self.assertEqual([json.loads(row['record_json']) for row in rows], bundle['records'])
        with self.assertRaises(P.ControlError): P.get_record(bundle, 0, 0)
        with self.assertRaises(P.ControlError): P.load_bundle(self.out, 'f'*64, root=self.root)
        with self.assertRaises(P.ControlError): self.export()

    def test_marked_sparse_native_source_retains_original_ids_and_denominator(self):
        original_pins = {name: P.stamp(self.response/name) for name in ('truth.jsonl', 'scalars.jsonl', 'signals.csv')}
        self.write_lines('truth.jsonl', [self.nonzero])
        self.write_lines('scalars.jsonl', [r for r in P.json_lines(self.response/'scalars.jsonl') if r['global_initial_id'] == 1])
        policy = P.N.descriptor(2, 1)
        self.write(self.response/'run.json', {**self.report, 'event_storage': policy, 'counts': {
            'initial_primaries': 2, 'zero_deposit_primaries': 1, 'nonzero_primaries': 1}})
        preserved = {name: P.stamp(self.response/name) for name in original_pins}
        self.export(); data = P.load_bundle(self.out, root=self.root)
        self.assertEqual(data['event_storage'], policy)
        self.assertEqual([r['global_initial_id'] for r in data['records']], [1])
        self.assertEqual(data['counts']['selected_groups']/data['counts']['efficiency_denominator'], .5)
        self.assertEqual(preserved, {name: P.stamp(self.response/name) for name in preserved})
        altered = P.read_json(self.out/'features.json'); altered['event_storage']['efficiency_denominator'] = 1
        self.write(self.out/'features.json', altered); self.rehash('features.json')
        with self.assertRaises(P.ControlError): P.load_bundle(self.out, root=self.root, verify_inputs=False)

    def test_nonzero_native_failure_and_readout_rejection_are_stored(self):
        rows = P.json_lines(self.response/'scalars.jsonl')
        failed, _ = group_fixture(failed=True); rows[-1] = failed
        self.write_lines('scalars.jsonl', rows); self.write_lines('endpoints.jsonl', [])
        (self.response/'signals.csv').write_text(','.join(P.SIGNAL_COLUMNS)+'\n', encoding='utf-8')
        self.export(); data = P.load_bundle(self.out, root=self.root)
        self.assertEqual(data['counts']['native_failed_groups'], 1)
        self.assertEqual(data['counts']['rejected_groups'], 1)
        self.assertEqual(data['counts']['readout_rejected_groups'], 0)
        group = P.get_record(data, 1, 0)
        self.assertIsNone(group['signal']); self.assertIsNone(group['Erec_keV'])
        self.assertEqual(group['saved_scalar']['native_error'], failed['native_error'])

    def test_historical_unmarked_bundle_keeps_strict_full_census(self):
        self.export()
        dense, summaries, _ = P.build_records(self.run, self.receipt, profile())
        data = P.read_json(self.out/'features.json'); manifest = P.read_json(self.out/'manifest.json')
        for value in (data, manifest):
            value['schema_version'] = 1; value.pop('event_storage'); value['counts'] = P.record_counts(dense)
        data['records'] = dense
        for value in (manifest, data['provenance']):
            value['extractor_sources'].pop('tools/nonzero_events.py')
        schema = P.encoded(P.LEGACY_DEFINITIONS); (self.out/'schema.json').write_bytes(schema)
        for value in (manifest, data['provenance']): value['schema_template_sha256'] = hashlib.sha256(schema).hexdigest()
        self.write(self.out/'features.json', data); (self.out/'features.csv').write_bytes(P.csv_bytes(dense))
        manifest['artifacts'] = {name: P.stamp(self.out/name) for name in manifest['artifacts']}
        self.write(self.out/'manifest.json', manifest)
        complete = P.read_json(self.out/'COMPLETE.json'); complete.update(schema_version=1, manifest_sha256=P.sha(self.out/'manifest.json'))
        self.write(self.out/'COMPLETE.json', complete)
        legacy = P.load_bundle(self.out, root=self.root)
        self.assertEqual(P.get_record(legacy, 0)['selection']['reasons'], ['zero_deposit'])
        data['records'] = data['records'][1:]; data['counts'] = P.record_counts(data['records'])
        self.write(self.out/'features.json', data); self.rehash('features.json')
        with self.assertRaises(P.ControlError): P.load_bundle(self.out, root=self.root, verify_inputs=False)

    def test_derivative_tamper_and_rehashed_schema_or_raw_changes_rejected(self):
        self.export(); before = (self.out/'features.json').read_bytes()
        (self.out/'features.json').write_bytes(before + b' ')
        with self.assertRaises(P.ControlError): P.load_bundle(self.out, root=self.root)
        (self.out/'features.json').write_bytes(before)
        data = P.read_json(self.out/'features.json')
        data['records'][0]['pulse_groups'][0]['signal']['induced_equivalent_energy_keV'][-1] = 100
        self.write(self.out/'features.json', data); self.rehash('features.json')
        with self.assertRaises(P.ControlError): P.load_bundle(self.out, root=self.root)

    def test_rehashed_schema_definition_is_rejected(self):
        self.export(); definitions = P.read_json(self.out/'schema.json'); definitions['E'] = 'truth energy'
        self.write(self.out/'schema.json', definitions); self.rehash('schema.json')
        with self.assertRaises(P.ControlError): P.load_bundle(self.out, root=self.root)

    def test_rehashed_null_feature_and_selection_changes_rejected(self):
        self.export(); data = P.read_json(self.out/'features.json')
        data['records'][0]['selection'] = {'valid': False, 'reasons': ['invented_reason']}
        self.write(self.out/'features.json', data); self.rehash('features.json')
        with self.assertRaises(P.ControlError): P.load_bundle(self.out, root=self.root, verify_inputs=False)

    def test_current_source_and_original_input_change_rejected(self):
        self.export()
        path = self.root/P.SOURCE_REFS[0]; before = path.read_bytes(); path.write_bytes(before+b'\n')
        with self.assertRaises(P.ControlError): P.load_bundle(self.out, root=self.root)
        path.write_bytes(before)
        original = self.response/'signals.csv'; original.write_bytes(original.read_bytes()+b'\n')
        with self.assertRaises(P.ControlError): P.load_bundle(self.out, root=self.root)

    def test_output_science_path_and_traversal_are_refused(self):
        with self.assertRaises(P.ControlError): P.export_bundle(self.run, self.response/'derived', self.profile_path, root=self.root)
        with self.assertRaises(P.ControlError): P.default_bundle_dir(self.root, '../escape')
        with self.assertRaises(P.ControlError): P.load_bundle(self.root/'.local/../outside', root=self.root)

    def test_cli_defaults_to_the_canonical_discoverable_bundle(self):
        with patch.object(P, 'export_bundle', return_value={'status': 'complete', 'counts': {},
                'configuration_sha256': self.receipt['configuration_sha256']}) as exporter, patch('sys.stdout', io.StringIO()):
            self.assertEqual(P.main(['--run', str(self.run)]), 0)
        exporter.assert_called_once_with(self.run.resolve(), self.out, None)

    def test_batch_local_identity_reuse_does_not_merge_originals(self):
        import batch_execution as E
        self.config['selection']['primary_count'] = 3
        self.config['batching'] = E.partition(3, 123, cap=2)
        self.receipt['configuration_sha256'] = P.W.digest(self.config)
        self.write(self.run/'run.json', self.receipt)
        self.write(self.run/'resolved-config.json', {'configuration_sha256': self.receipt['configuration_sha256'], 'resolved': self.config})
        first = E.batch_directory(self.run, 0)/'response'; second = E.batch_directory(self.run, 1)/'response'
        shutil.copytree(self.response, first); shutil.copytree(self.response, second)
        def second_identity(row):
            row.update(global_initial_id=2, event_id=0, global_decay_id=0, local_initial_id=0, batch_index=1)
            return row
        self.write(second/'run.json', {**self.report, 'batch': {'batch_index': 1}})
        truth = second_identity(copy.deepcopy(self.nonzero))
        (second/'truth.jsonl').write_bytes(P.encoded(truth))
        originals = P.json_lines(self.response/'scalars.jsonl')
        (second/'scalars.jsonl').write_bytes(b''.join(P.encoded(second_identity(copy.deepcopy(row))) for row in originals[1:]))
        (second/'endpoints.jsonl').write_bytes(b''.join(P.encoded(second_identity(copy.deepcopy(row)))
                for row in P.json_lines(self.response/'endpoints.jsonl')))
        with (second/'signals.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=P.SIGNAL_COLUMNS); writer.writeheader()
            for time in range(21):
                writer.writerow({'event_id': 0, 'global_decay_id': 0, 'local_initial_id': 0, 'global_initial_id': 2,
                                 'batch_index': 1, 'group_id': 0, 'time_since_origin_ns': time,
                                 'induced_equivalent_energy_keV': time})
        self.out = P.default_bundle_dir(self.root, self.receipt['configuration_sha256'])
        self.export(); data = P.load_bundle(self.out, root=self.root)
        self.assertEqual([r['global_initial_id'] for r in data['records']], [1, 2])
        later = P.get_record(data, 2, 0)
        self.assertEqual(later['event_id'], 0); self.assertEqual(later['global_decay_id'], 0)
        self.assertEqual(later['local_initial_id'], 0); self.assertEqual(later['batch_index'], 1)
        self.assertEqual(later['signal']['time_since_origin_ns'], list(range(21)))


if __name__ == '__main__':
    unittest.main()
