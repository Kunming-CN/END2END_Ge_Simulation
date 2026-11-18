import json
import unittest
from unittest.mock import patch

import gegi_digital_pairs as P
from gegi_digital_readout import digital_event


CHANNELS = [{'id': cid, 'family': 'X' if cid <= 17 else 'Y', 'guard': cid in (17, 34),
             'wiring_factor': 1 if cid <= 17 else -1, 'strip_center_mm': float(cid * 5)}
            for cid in range(1, 35)]


def outcomes(hits, invalid=()):
    return {'channels': [{'contact_id': cid, 'slow_energy_keV': hits.get(cid),
                          'flags': (['slow_adc_saturation'] if cid in invalid else
                                    [] if cid in hits else ['slow_below_threshold'])}
                         for cid in range(1, 35)]}


def evaluated_calibration():
    return {'calibration_sha256': '0' * 64,
            'evaluation': {'kind': 'independent_same_model_saved_injection_check',
                           'mode': 'cfd_conditioned'}}


def estimated(x, y, *, depth=1.0, field_status='matching_saved_fields'):
    return {'calibration_source_status': field_status, 'calibration_pair_coverage': 'simulated_pair',
            'x': {'status': 'estimated', 'position_mm': float(x) * 5},
            'y': {'status': 'estimated', 'position_mm': float(y) * 5},
            'depth': {'status': 'estimated' if depth is not None else 'collector_cfd_unavailable',
                      'position_mm': depth}}


class DigitalPairingTest(unittest.TestCase):
    def test_unique_crossed_pairing_retains_incompatible_permutation(self):
        replay = outcomes({3: 110, 9: 210, 20: 211, 26: 111})
        result = P.two_site_pairings(replay, CHANNELS)
        self.assertEqual(result['status'], 'unique_energy_pairing')
        self.assertEqual(result['compatible_pairing_count'], 1)
        self.assertEqual(result['energy_keV'], 321)
        first, second = result['pairings']
        self.assertFalse(first['energy_compatible'])
        self.assertTrue(second['energy_compatible'])
        self.assertEqual([(s['x_contact_id'], s['y_contact_id']) for s in second['sites']], [(3, 26), (9, 20)])
        self.assertEqual(second['sites'][0]['energy_tolerance_keV'], 2.22)
        self.assertEqual(second['sites'][0]['x_minus_y_energy_keV'], -1)
        self.assertEqual(second['sites'][0]['energy_keV'], 110.5)
        self.assertIn('missing_z', result['flags'])
        self.assertEqual(second['cones'], [])
        json.dumps(result, allow_nan=False)

    def test_equal_energies_preserve_both_assignments_when_neighborhoods_overlap(self):
        replay = outcomes({11: 200, 12: 200, 24: 200, 26: 200})
        with patch.object(P, 'infer_position') as infer:
            result = P.two_site_pairings(replay, CHANNELS, calibration=evaluated_calibration())
        infer.assert_not_called()
        self.assertEqual(result['status'], 'ambiguous_energy_pairing')
        self.assertEqual(result['compatible_pairing_count'], 2)
        self.assertEqual(result['flags'], ['overlapping_x_neighborhoods', 'overlapping_y_neighborhoods'])
        self.assertEqual([p['cones'] for p in result['pairings']], [[], []])
        self.assertTrue(all(p['energy_compatible'] for p in result['pairings']))

    def test_bright_induction_transient_does_not_become_a_slow_collector(self):
        wired = {3: [0, 100, 100, 100], 9: [0, 210, 210, 210], 20: [0, 100, 100, 100],
                 26: [0, 210, 210, 210], 8: [0, 650, 650, 0]}
        native = {c['id']: {'time_ns': [0, 10, 85, 109], 'signed_induced_keV': [
            q * c['wiring_factor'] for q in wired.get(c['id'], [0, 0, 0, 0])]} for c in CHANNELS}
        replay = digital_event(native, CHANNELS, terminal_complete=True)
        bright = replay['channels'][7]
        self.assertGreater(bright['fast_signal_keV_equiv'], 100)
        self.assertGreater(bright['slow_peak_V'] / replay['calibration']['slow_V_per_keV'], 5)
        self.assertIsNone(bright['slow_energy_keV'])
        result = P.two_site_pairings(replay, CHANNELS)
        self.assertEqual(result['status'], 'unique_energy_pairing')
        self.assertEqual(result['collecting_contact_ids'], [3, 9, 20, 26])

    def test_reason_retains_guard_and_unknown_slow_channels(self):
        hits = {3: 200, 9: 200, 20: 200, 26: 200}
        result = P.two_site_pairings(outcomes({**hits, 17: 6}), CHANNELS)
        self.assertEqual(result['reason'], 'guard_collection')
        self.assertEqual(result['pairings'], [])
        result = P.two_site_pairings(outcomes(hits, invalid=(13,)), CHANNELS)
        self.assertEqual(result['reason'], 'invalid_slow_channels')
        self.assertEqual(result['invalid_slow_contact_ids'], [13])
        self.assertEqual(result['pairings'], [])

    def test_unknown_and_inexact_depth_do_not_generate_cones(self):
        replay = outcomes({3: 200, 9: 250, 20: 200, 26: 250})
        for second, flag in ((estimated(9, 26, depth=None), 'missing_z'),
                             (estimated(9, 26, field_status='nominal_transfer'), 'position_calibration_fields_not_exact')):
            with self.subTest(second=second), patch.object(P, 'infer_position', side_effect=[estimated(3, 20), second]):
                result = P.two_site_pairings(replay, CHANNELS, calibration=evaluated_calibration())
            first = result['pairings'][0]
            self.assertEqual(first['sites'][0]['position_mm'], [15, 100, 1])
            self.assertIsNone(first['sites'][1]['position_mm'])
            self.assertEqual(first['flags'], [flag])
            self.assertEqual(first['cones'], [])
        with patch.object(P, 'infer_position') as infer:
            result = P.two_site_pairings(replay, CHANNELS, calibration={'calibration_sha256': '0' * 64})
        infer.assert_not_called()
        self.assertIn('position_calibration_not_evaluated', result['flags'])

    def test_evaluated_nonoverlapping_3d_positions_check_both_orders(self):
        replay = outcomes({3: 100, 9: 400, 20: 100, 26: 400})
        with patch.object(P, 'infer_position', side_effect=[estimated(3, 20), estimated(9, 26)]) as infer:
            result = P.two_site_pairings(replay, CHANNELS, calibration=evaluated_calibration())
        self.assertEqual(infer.call_count, 2)
        self.assertTrue(all(call.kwargs['mode'] == 'cfd_conditioned' for call in infer.call_args_list))
        pairing = result['pairings'][0]
        self.assertEqual(pairing['flags'], [])
        self.assertEqual([c['site_index_order'] for c in pairing['cones']], [[0, 1]])
        self.assertEqual([c['site_index_order'] for c in pairing['rejected_orders']], [[1, 0]])
        self.assertEqual(pairing['cones'][0]['vertex_mm'], [15, 100, 1])


if __name__ == '__main__':
    unittest.main()
