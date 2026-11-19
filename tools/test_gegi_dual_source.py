"""Measured fast feature receipts for GeGI acquisition triggers."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gegi_dual_source as dual
from gegi_dual_source import _strip_neighbors, _trigger_card


def channel(cid, *, slow=None, fast=None, flags=()):
    return {'contact_id': cid, 'slow_energy_keV': slow, 'fast_signal_keV_equiv': fast, 'flags': list(flags)}


def pulse(collectors, neighbors, *, single=None, flags=()):
    ids = [row['contact_id'] for row in collectors]
    return {'trigger_time_ns': 10000, 'rise_end_ns': 10080, 'channels': collectors + neighbors,
            'contact_ids': ids if single is not None else None, 'step_contact_ids': ids,
            'slow_energy_keV': single, 'flags': list(flags)}


class TriggerFeaturesTests(unittest.TestCase):
    def test_position_requires_matching_fields_and_a_calibrated_pair(self):
        calibration = dual.substrip.load_calibration()
        record = {'slow_energy_keV': 500., 'contact_ids': [15, 29]}
        self.assertEqual(dual._continuous_position(record, calibration, [], None)['status'], 'unconfirmed_field')
        identity = {k: calibration[k] for k in ('model_sha256', 'field_cache_sha256', 'field_precision_bits')}
        self.assertEqual(dual._continuous_position(record, calibration, [], identity)['status'], 'uncalibrated_pixel')
        record.update(slow_energy_keV=900., contact_ids=[11, 24], channels=[])
        partial = {'x': {'status': 'estimated', 'slot': 4, 'position_mm': 12.5},
                   'y': {'status': 'ratio_outside_calibration', 'slot': None, 'position_mm': None},
                   'depth': {'status': 'estimated', 'position_mm': 7.}}
        with patch.object(dual.substrip, 'infer_position', return_value=partial) as fit:
            result = dual._continuous_position(record, calibration, [], identity)
        fit.assert_called_once_with(calibration, 11, 24, record, [], source_identity=identity, mode='cfd_conditioned')
        self.assertEqual((result['status'], result['position_mm'], result['energy_scope']),
                         ('partial', None, 'outside_tested_range'))
        self.assertEqual(result['axes']['z']['position_mm'], 7.)

    def setUp(self):
        geometry = [dict(id=start + index, family=axis, guard=index == 16,
                         strip_center_mm=(index - 7.5) * 5 if index < 16 else None)
                    for axis, start in (('X', 1), ('Y', 18)) for index in range(17)]
        self.neighbors = _strip_neighbors(geometry[::-1])
        self.geometry = geometry

    def test_two_strip_energy_permutations_and_orders(self):
        for energies, compatible in [((200., 462., 462., 200.), 1), ((300., 300., 300., 300.), 2),
                                     ((200., 462., 300., 362.), 0)]:
            with self.subTest(energies=energies):
                rows = [channel(cid, slow=e) for cid, e in zip((3, 5, 21, 25), energies)]
                record = _trigger_card(pulse(rows, []), self.neighbors, geometry=self.geometry)
                result = record['two_strip_pairings']
                self.assertEqual(result['compatible_pairing_count'], compatible)
                self.assertEqual(len(result['pairings']), 2)
                for pairing in result['pairings']:
                    orders = pairing['compton_orders']
                    self.assertEqual(len(orders), 2 if pairing['energy_compatible'] else 0)
                    for order in orders:
                        self.assertEqual(order['kinematically_allowed'], order['half_angle_deg'] is not None)
                self.assertIsNone(record['single_pixel_features'])

    def test_collecting_energies_and_opposite_signed_ratios(self):
        readout = pulse([channel(3, slow=99.), channel(24, slow=101.)],
                        [channel(2, fast=11.), channel(4, fast=-4.),
                         channel(23, fast=-13.), channel(25, fast=2.)], single=100.)
        readout['channels'][0]['preamp_cfd50_ns'] = 32.5
        card = _trigger_card(readout, self.neighbors)
        self.assertEqual(card['single_pixel_energy_keV'], 100.)
        self.assertEqual(card['single_pixel_features'], {
            'x': {'contact_id': 3, 'slow_energy_keV': 99., 'fast_ratio': .15, 'preamp_cfd50_ns': 32.5,
                  'low': {'contact_id': 2, 'fast_keV_equiv': 11., 'flags': []},
                  'high': {'contact_id': 4, 'fast_keV_equiv': -4., 'flags': []}},
            'y': {'contact_id': 24, 'slow_energy_keV': 101., 'fast_ratio': -.15, 'preamp_cfd50_ns': None,
                  'low': {'contact_id': 23, 'fast_keV_equiv': -13., 'flags': []},
                  'high': {'contact_id': 25, 'fast_keV_equiv': 2., 'flags': []}},
        })

    def test_edge_preserves_one_neighbor_on_each_face(self):
        edge_cases = [(16, 18, (15, None), (None, 19)), (1, 33, (None, 2), (32, None))]
        for x, y, x_neighbors, y_neighbors in edge_cases:
            with self.subTest(x=x, y=y):
                nearby = [channel(cid, fast=1.) for cid in (*x_neighbors, *y_neighbors, 17, 34) if cid is not None]
                readout = pulse([channel(x, slow=100.), channel(y, slow=100.)], nearby, single=100.)
                features = _trigger_card(readout, self.neighbors)['single_pixel_features']
                for axis, expected in (('x', x_neighbors), ('y', y_neighbors)):
                    face = features[axis]
                    adjacent = [face['low'], face['high']]
                    self.assertEqual([item['contact_id'] if item else None for item in adjacent], list(expected))
                    self.assertIsNone(face['fast_ratio'])

    def test_zero_and_missing_are_distinct(self):
        readout = pulse([channel(3, slow=100.), channel(24, slow=100.)],
                        [channel(2, fast=0., flags=('slow_below_threshold',)), channel(4, fast=0.),
                         channel(25, fast=5.)], single=100.)
        features = _trigger_card(readout, self.neighbors)['single_pixel_features']
        self.assertEqual(features['x']['low'], {'contact_id': 2, 'fast_keV_equiv': 0., 'flags': []})
        self.assertEqual(features['x']['fast_ratio'], 0.)
        self.assertEqual(features['y']['low'], {'contact_id': 23, 'fast_keV_equiv': None, 'flags': []})
        self.assertIsNone(features['y']['fast_ratio'])

    def test_fast_losses_are_channel_local(self):
        readout = pulse([channel(3, slow=100.), channel(24, slow=100.)],
                        [channel(2, flags=('fast_adc_saturation', 'slow_below_threshold')),
                         channel(4, flags=('fast_pileup', 'fast_window_truncated')),
                         channel(23, fast=5.), channel(25, fast=-5.)], single=100., flags=('fast_pileup',))
        features = _trigger_card(readout, self.neighbors)['single_pixel_features']
        self.assertEqual(features['x']['low'],
                         {'contact_id': 2, 'fast_keV_equiv': None, 'flags': ['fast_adc_saturation']})
        self.assertEqual(features['x']['high'], {'contact_id': 4, 'fast_keV_equiv': None,
                                                'flags': ['fast_pileup', 'fast_window_truncated']})
        self.assertIsNone(features['x']['fast_ratio'])
        self.assertEqual(features['y']['fast_ratio'], .1)

    def test_other_triggers_have_no_single_pixel_features(self):
        multi = pulse([channel(3, slow=80.), channel(4, slow=20.), channel(24, slow=100.)], [])
        card = _trigger_card(multi, self.neighbors)
        self.assertEqual(card['additional_multi_strip_energy_keV'], 100.)
        self.assertIsNone(card['single_pixel_features'])
        for unqualified in (pulse([channel(3, slow=100.), channel(24, slow=104.)], []),
                            pulse([channel(3, slow=100.), channel(24, slow=100.), channel(34, slow=10.)], [])):
            card = _trigger_card(unqualified, self.neighbors)
            self.assertIsNone(card['energy_keV'])
            self.assertIsNone(card['single_pixel_features'])


class TriggerProfileTests(unittest.TestCase):
    def test_profile_definition_and_input_validation(self):
        for name, threshold in (('standard', 5.), ('low-energy', 4.)):
            expected = {'id': name, 'coincidence_threshold_keV_per_sample': threshold,
                        'quiet_threshold_keV_per_sample': 3., 'sample_period_ns': 20}
            self.assertEqual(dual.gegi_pulse_stream.trigger_profile_definition(name), expected)
        with self.assertRaisesRegex(ValueError, 'standard or low-energy'):
            dual.run(('saved-a', 'saved-b'), (37000, 37000), .25, 1, 'unused.json', trigger_profile='other')

    def test_cli_defaults_to_standard_and_passes_selected_profile(self):
        arguments = ['gegi_dual_source', '--source-a', 'saved-a', '--source-b', 'saved-b', '--output', 'new.json']
        for options, name, capture in (([], 'standard', False),
                                       (['--trigger-profile', 'low-energy', '--capture-two-strip-adc'], 'low-energy', True)):
            profile = dual.gegi_pulse_stream.trigger_profile_definition(name)
            result = {'counts': {}, 'receipt': {'observed_result_sha256': 'abcd'},
                      'design': {'trigger_profile': profile}, 'exposure': {'qualified_adc_live_time_ns': 0}}
            with patch('sys.argv', arguments + options), patch.object(dual, 'run', return_value=result) as run:
                with redirect_stdout(StringIO()) as printed:
                    dual.main()
            self.assertEqual(run.call_args.args[0], (Path('saved-a'), Path('saved-b')))
            self.assertEqual(run.call_args.kwargs['trigger_profile'], name)
            self.assertEqual(run.call_args.kwargs['capture_two_strip_adc'], capture)
            self.assertEqual(json.loads(printed.getvalue())['trigger_profile'], profile)

    def test_report_and_window_archive_use_exclusive_publication(self):
        report = {'status': 'completed'}
        with tempfile.TemporaryDirectory() as tmp:
            import numpy as np

            path = Path(tmp)/'report.json'
            archive = path.with_name(dual.windows.ARCHIVE_NAME)
            arrays = dual.windows.context_arrays([], {}, np.zeros(34), 'a'*64)
            publish = dual._publish_artifact

            def report_write_failure(destination, writer):
                if destination == path:
                    raise OSError('Report publication failed')
                publish(destination, writer)

            with patch.object(dual, '_publish_artifact', side_effect=report_write_failure):
                with self.assertRaisesRegex(OSError, 'Report publication failed'):
                    dual._publish(report, path, adc_windows=arrays)
            self.assertFalse(path.exists())
            self.assertFalse(archive.exists())

            dual._publish(report, path, adc_windows=arrays)
            with np.load(archive, allow_pickle=False) as sidecar:
                self.assertEqual(sidecar['report_sha256'].item(), dual.sha(path.read_bytes()))
                self.assertEqual(sidecar['known_component_adc_sha256'].item(), 'a'*64)
                self.assertEqual(sidecar['adc_codes'].shape, (0, 34, 29))
            previous = archive.read_bytes()
            with self.assertRaises(FileExistsError):
                dual._publish({'status': 'different'}, path, adc_windows=arrays)
            self.assertEqual(archive.read_bytes(), previous)
            self.assertEqual(json.loads(path.read_bytes()), report)


if __name__ == '__main__':
    unittest.main()
