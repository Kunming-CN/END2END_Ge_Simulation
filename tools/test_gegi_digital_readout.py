import copy
import json
import math
import unittest

import gegi_digital_readout as D
from gegi_event_store import encoded, sha


CHANNELS = [{'id': cid, 'wiring_factor': 1 if cid <= 17 else -1} for cid in range(1, 35)]


def event_native(wired=None, times=(0, 1, 80, 109)):
    wired = wired or {}
    return {c['id']: {'time_ns': list(times), 'signed_induced_keV': [
        c['wiring_factor'] * q for q in wired.get(c['id'], [0] * len(times))]} for c in CHANNELS}


class DigitalReadoutTest(unittest.TestCase):
    def test_signed_signal_and_fixed_pulser_gain(self):
        native = event_native({3: [0, 120, 120, 120], 29: [0, 120, 120, 120],
                               4: [0, -17, -17, 0], 28: [0, 17, 17, 0]})
        result = D.digital_event(native, CHANNELS, terminal_complete=True, include_traces=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['profile_sha256'], sha(encoded(result['profile'])))
        self.assertEqual(result['calibration']['pulser_energy_keV'], 500)
        rows = {c['contact_id']: c for c in result['channels']}
        self.assertEqual(len(rows), 34)
        self.assertAlmostEqual(rows[3]['slow_energy_keV'], 120, delta=.1)
        self.assertEqual(rows[3]['trace'], rows[29]['trace'])
        self.assertLess(rows[4]['fast_signal_keV_equiv'], 0)
        self.assertGreater(rows[28]['fast_signal_keV_equiv'], 0)
        self.assertAlmostEqual(rows[4]['fast_area_V_ns'], -rows[28]['fast_area_V_ns'], places=12)
        self.assertIsNone(rows[1]['slow_energy_keV'])
        self.assertEqual(rows[1]['fast_signal_keV_equiv'], 0)
        self.assertIn('slow_below_threshold', rows[1]['flags'])
        json.dumps(result, allow_nan=False)

    def test_short_record_needs_verified_endpoints_for_relaxation(self):
        native = event_native({3: [0, 120, 120, 120]})
        short = D.digital_event(native, CHANNELS, include_traces=True)
        self.assertEqual(short['status'], 'partial')
        self.assertEqual(short['window']['acquired_end_ns'], 100)
        self.assertIsNone(short['channels'][2]['slow_energy_keV'])
        self.assertIsNone(short['channels'][2]['fast_area_V_ns'])
        self.assertEqual(short['channels'][2]['flags'], ['fast_window_truncated', 'slow_window_truncated'])
        full = D.digital_event(native, CHANNELS, terminal_complete=True, include_traces=True)
        self.assertIn('terminal_preamplifier_relaxation', full['flags'])
        trace = full['channels'][2]['trace']
        post = dict(zip(trace['time_ns'], trace['preamp_V']))
        self.assertAlmostEqual(post[3000] / post[1000], math.exp(-(3000 - 1000) / 50000), places=14)
        cut = D.digital_event(native, CHANNELS, terminal_complete=True, horizon_ns=240)
        self.assertEqual(cut['window']['acquired_end_ns'], 220)
        self.assertFalse(cut['window']['fast_gate_complete'])
        fast_only = D.digital_event(native, CHANNELS, terminal_complete=True, horizon_ns=240.1)
        self.assertEqual(fast_only['channels'][2]['fast_area_V_ns'], full['channels'][2]['fast_area_V_ns'])
        self.assertIsNone(fast_only['channels'][2]['slow_energy_keV'])
        plateaus_only = D.digital_event(native, CHANNELS, terminal_complete=True, horizon_ns=981)
        self.assertEqual(plateaus_only['channels'][2]['slow_energy_keV'], full['channels'][2]['slow_energy_keV'])
        self.assertIsNone(plateaus_only['channels'][2]['slow_peak_V'])

    def test_exact_preamplifier_at_samples_between_native_knots(self):
        native = event_native({1: [0, 5, -10]}, times=(0., 5.1, 29.2))
        result = D.digital_event(native, CHANNELS, terminal_complete=True, include_traces=True)
        trace = result['channels'][0]['trace']
        analog = dict(zip(trace['time_ns'], trace['preamp_V']))
        tau_fb = result['profile']['feedback_tau_ns']
        tau_bw = result['profile']['analog_bandwidth_tau_ns']
        scale = 1000 * 1.602176634e-19 / (2.95 * 0.6e-12)
        def interval_response(tau):
            first = scale * 5 / 5.1 * tau * -math.expm1(-5.1 / tau)
            return first * math.exp(-14.9 / tau) + scale * (-15) / 24.1 * tau * -math.expm1(-14.9 / tau)
        expected = tau_fb / (tau_fb - tau_bw) * (interval_response(tau_fb) - interval_response(tau_bw))
        self.assertAlmostEqual(analog[20], expected, places=14)

    def test_rails_only_invalidate_affected_paths(self):
        native = event_native({1: [0, 5000, 5000, 5000], 2: [0, -5000, -5000, -5000],
                               3: [0, 0, 0, 5000]}, times=(0, 1, 260, 280))
        result = D.digital_event(native, CHANNELS, terminal_complete=True)
        for channel in result['channels'][:2]:
            self.assertEqual(channel['flags'], ['fast_adc_saturation', 'slow_adc_saturation'])
            self.assertIsNone(channel['slow_energy_keV'])
            self.assertIsNone(channel['fast_area_V_ns'])
        self.assertEqual(result['channels'][2]['flags'], ['slow_adc_saturation'])
        self.assertEqual(result['channels'][2]['fast_area_V_ns'], 0)

    def test_slow_plateau_rejects_transient_peaks_and_late_native_support(self):
        native = event_native({1: [0, 30, 30, 0], 2: [0, -30, -30, 0]})
        result = D.digital_event(native, CHANNELS, terminal_complete=True)
        for channel in result['channels'][:2]:
            self.assertGreater(channel['slow_peak_V'], result['calibration']['slow_V_per_keV'])
            self.assertAlmostEqual(channel['slow_plateau_V'], 0, delta=1e-5)
            self.assertIsNone(channel['slow_energy_keV'])
        late = event_native({1: [0, 60, 60, 60, 150]}, times=(0, 50, 100, 750, 850))
        result = D.digital_event(late, CHANNELS, terminal_complete=True)
        self.assertEqual(result['status'], 'completed')
        self.assertIn('slow_plateau_unsettled', result['channels'][0]['flags'])
        self.assertIsNone(result['channels'][0]['slow_energy_keV'])
        self.assertGreater(result['channels'][0]['fast_area_V_ns'], 0)

    def test_constant_charge_padding_leaves_digitized_features_invariant(self):
        short = event_native({1: [0, 45, 100, 150]})
        padded = event_native({1: [0, 45, 100, 150, 150, 150, 150, 150]},
                              times=(0, 1, 80, 109, 300, 400, 1000, 3000))
        first = D.digital_event(short, CHANNELS, terminal_complete=True, include_traces=True)['channels'][0]
        second = D.digital_event(padded, CHANNELS, include_traces=True)['channels'][0]
        first_trace = first.pop('trace')
        second_trace = second.pop('trace')
        for quantity in ('adc_code', 'digitized_preamp_V', 'slow_V', 'fast_V'):
            self.assertEqual(first_trace[quantity], second_trace[quantity])
        self.assertEqual(first, second)

    def test_cfd_timing_tracks_known_delay_and_requires_a_valid_plateau(self):
        time = (0, 20, 40, 80, 100)
        charge = [0, 0, 25, 110, 120]
        base = D.digital_event(event_native({3: charge}, time), CHANNELS, terminal_complete=True, include_traces=True)
        delayed = D.digital_event(event_native({3: [0] + charge}, (0, *(t + 40 for t in time))), CHANNELS,
                                  terminal_complete=True)['channels'][2]
        self.assertEqual(base['timing_sha256'], sha(encoded(base['timing'])))
        self.assertEqual(base['timing_sha256'], D.TIMING_SHA256)
        nominal = base['channels'][2]
        self.assertAlmostEqual(delayed['preamp_cfd50_ns'] - nominal['preamp_cfd50_ns'], 40, delta=.05)
        self.assertIsNone(base['channels'][0]['preamp_cfd50_ns'])
        cutoff = D.digital_event(event_native({3: charge}, time), CHANNELS, horizon_ns=480, terminal_complete=True)
        self.assertIsNone(cutoff['channels'][2]['preamp_cfd50_ns'])

    def test_terminal_completion_is_conservative(self):
        first = {'status': 'contact', 'step_limit_reached': False, 'contact_ids': [3]}
        last = {**first, 'contact_ids': [29]}
        event = {'status': 'completed', 'steps': [{'endpoints': [first, last]}]}
        self.assertTrue(D.terminal_contacts_complete(event))
        last['step_limit_reached'] = True
        self.assertFalse(D.terminal_contacts_complete(event))
        self.assertFalse(D.terminal_contacts_complete({'status': 'completed'}))

    def test_explicit_noise_seed_replays_without_changing_calibration(self):
        native = event_native()
        deterministic = D.digital_event(native, CHANNELS, terminal_complete=True, include_traces=True, noise_seed=3)
        replay = D.digital_event(native, CHANNELS, terminal_complete=True, include_traces=True, noise_seed=3)
        changed_seed = D.digital_event(native, CHANNELS, terminal_complete=True, include_traces=True, noise_seed=4)
        self.assertEqual(deterministic, replay)
        self.assertNotEqual(deterministic['channels'][0]['trace']['adc_code'], changed_seed['channels'][0]['trace']['adc_code'])
        self.assertNotEqual(deterministic['channels'][0]['trace']['adc_code'], deterministic['channels'][1]['trace']['adc_code'])
        self.assertEqual(deterministic['calibration'], changed_seed['calibration'])
        self.assertEqual(deterministic['channels'][0]['trace']['preamp_V'], changed_seed['channels'][0]['trace']['preamp_V'])

    def test_missing_native_signals_keep_unknown_channels(self):
        failed = D.digital_event(None, CHANNELS, include_traces=True)
        self.assertEqual(failed['status'], 'native_unavailable')
        self.assertEqual(len(failed['channels']), 34)
        self.assertTrue(all(c['slow_energy_keV'] is None and c['fast_area_V_ns'] is None
                            and c['preamp_cfd50_ns'] is None and 'trace' not in c
                            for c in failed['channels']))

    def test_refuses_changed_wiring_or_native_grid(self):
        channels = copy.deepcopy(CHANNELS)
        channels[-1]['wiring_factor'] = 1
        with self.assertRaisesRegex(ValueError, 'fixed wiring'):
            D.digital_event(event_native(), channels)
        native = event_native()
        native[34]['time_ns'][1] = 2
        with self.assertRaisesRegex(ValueError, 'common native time grid'):
            D.digital_event(native, CHANNELS)


if __name__ == '__main__':
    unittest.main()
