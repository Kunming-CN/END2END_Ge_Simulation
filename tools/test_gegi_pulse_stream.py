import unittest

import numpy as np

import gegi_digital_readout as D
import gegi_pulse_stream as P
from test_gegi_digital_readout import CHANNELS, event_native


def pulse(pair=(3, 24), energy=120., neighbor=False):
    start = [0., energy, energy, energy]
    wired = {cid: start for cid in pair}
    if neighbor:
        wired.update({4: [0., -17., -17., 0.], 5: [0., 17., 17., 0.]})
    return event_native(wired)


def prepare(native):
    return P.prepare_native(native, CHANNELS, terminal_complete=True)


def single(prepared, **settings):
    return P.acquire([(prepared, 0., 1.)], **settings)


class PulseStreamTest(unittest.TestCase):
    def test_isolated_adc_parity_with_frozen_digitizer(self):
        native = pulse(neighbor=True)
        prepared = prepare(native)
        for noise_seed in (None, 393721):
            time, code = single(prepared, noise_seed=noise_seed)
            legacy = D.digital_event(native, CHANNELS, terminal_complete=True,
                                     noise_seed=noise_seed, include_traces=True)
            np.testing.assert_array_equal(time, legacy['channels'][0]['trace']['time_ns'])
            np.testing.assert_array_equal(code, [r['trace']['adc_code'] for r in legacy['channels']])
            measured = P.reconstruct(time, code)['events']
            self.assertEqual(len(measured), 1)
            self.assertEqual(measured[0]['trigger_time_ns'], 0.)
            self.assertEqual(measured[0]['contact_ids'], [3, 24])
            self.assertAlmostEqual(measured[0]['slow_energy_keV'], 120., delta=.1)
        _, adc = single(prepared)
        one = P.reconstruct(time, adc)['events'][0]
        self.assertLess(one['channels'][3]['fast_signal_keV_equiv'], 0.)
        self.assertGreater(one['channels'][4]['fast_signal_keV_equiv'], 0.)

    def test_fractional_delay_matches_frozen_shifted_native_knots(self):
        t0 = 37.5
        native = event_native({3: [0., 2.5, 97.], 24: [0., 3.5, 97.]}, (0., 17.2, 104.1))
        shifted = {cid: {'time_ns': [0., *(t + t0 for t in row['time_ns'])],
                         'signed_induced_keV': [0., *row['signed_induced_keV']]}
                   for cid, row in native.items()}
        legacy = D.digital_event(shifted, CHANNELS, terminal_complete=True, include_traces=True)
        component = [(prepare(native), t0, 1.)]
        t, adc = P.acquire(component, window_end_ns=3000.)
        np.testing.assert_array_equal(adc, [r['trace']['adc_code'] for r in legacy['channels']])
        t_phase, analog = P._analog_stream(component, 17.5, 60000.)
        self.assertGreater(analog[2, -1], 0.)
        np.testing.assert_allclose(analog[2, -1] / analog[2, -101], np.exp(-2000 / D._TAU), rtol=1e-12)
        np.testing.assert_allclose(np.mod(t_phase - t[0], D._DT), 17.5, atol=1e-10)

    def test_overlapping_analogs_receive_one_noise_draw_and_one_quantization(self):
        prepared = prepare(pulse(energy=17.18, neighbor=True))
        a, b = [(prepared, 0., 1.)], [(prepared, 14.3, 1.)]
        t, va = P._analog_stream(a, 4.3, 3500.)
        _, vb = P._analog_stream(b, 4.3, 3500.)
        actual_t, actual = P.acquire(a + b, phase_ns=4.3, noise_seed=84, window_end_ns=3500.)
        noise = np.array([np.random.Generator(np.random.PCG64([84, cid])).normal(
            0, D._PROFILE['optional_noise_rms_V'], len(t)) for cid in D.CONTACT_IDS])
        expected, _ = D._digitize(va + vb + noise)
        separate = D._digitize(va)[0] + D._digitize(vb + noise)[0]
        np.testing.assert_array_equal(t, actual_t)
        np.testing.assert_array_equal(actual, expected)
        self.assertGreater(np.count_nonzero(actual != separate), 0)

    def test_shared_and_disjoint_gates_at_equal_delay(self):
        first = prepare(pulse())
        for delay in (0., 400., 1400.):
            with self.subTest(delay=delay):
                shared = P.reconstruct(*P.acquire([(first, 0., 1.), (first, delay, .75)]))
                apart = prepare(pulse((12, 30), energy=90.))
                disjoint = P.reconstruct(*P.acquire([(first, 0., 1.), (apart, delay, 1.)]))
                if delay == 0:
                    self.assertEqual(len(shared['events']), 1)
                    self.assertAlmostEqual(shared['events'][0]['slow_energy_keV'], 210., delta=.1)
                    self.assertEqual(len(disjoint['events']), 1)
                    self.assertIsNone(disjoint['events'][0]['contact_ids'])
                    self.assertIsNone(disjoint['events'][0]['slow_energy_keV'])
                    continue
                self.assertEqual([e['contact_ids'] for e in disjoint['events']], [[3, 24], [12, 30]])
                self.assertEqual([e['trigger_time_ns'] for e in disjoint['events']], [0., delay])
                for event, energy in zip(disjoint['events'], (120., 90.)):
                    self.assertAlmostEqual(event['slow_energy_keV'], energy, delta=.15)
                self.assertEqual(len(shared['events']), 2)
                for event, energy in zip(shared['events'], (120., 90.)):
                    if delay == 400.:
                        self.assertIn('slow_pileup', event['channels'][2]['flags'])
                        self.assertIsNone(event['slow_energy_keV'])
                    else:
                        self.assertAlmostEqual(event['slow_energy_keV'], energy, delta=.15)

    def test_neighbor_transient_only_disables_affected_fast_observable(self):
        first = prepare(pulse())
        second = prepare(pulse((12, 30), energy=90., neighbor=True))
        stream = P.reconstruct(*P.acquire([(first, 0., 1.), (second, 220., 1.)]))
        self.assertEqual(len(stream['events']), 2)
        earlier = stream['events'][0]
        self.assertAlmostEqual(earlier['slow_energy_keV'], 120., delta=.15)
        self.assertIn('fast_pileup', earlier['channels'][3]['flags'])
        self.assertIsNone(earlier['channels'][3]['fast_signal_keV_equiv'])
        self.assertIsNotNone(earlier['channels'][2]['fast_signal_keV_equiv'])

    def test_rails_short_capture_and_unconfirmed_activity_remain_visible(self):
        first = prepare(pulse())
        both = P.acquire([(first, 0., 24.), (first, 0., 24.)])
        clipped = P.reconstruct(*both)
        self.assertIn('adc_saturation', clipped['flags'])
        self.assertEqual(clipped['saturated_contact_ids'], [3, 24])
        self.assertIsNone(clipped['events'][0]['slow_energy_keV'])
        self.assertIn('slow_adc_saturation', clipped['events'][0]['channels'][2]['flags'])
        cut = P.reconstruct(*single(first, window_end_ns=80.))
        self.assertEqual(len(cut['events']), 1)
        self.assertIn('slow_window_truncated', cut['events'][0]['flags'])
        self.assertIsNone(cut['events'][0]['slow_energy_keV'])
        one_face = prepare(event_native({3: [0., 100., 100., 100.]}))
        unconfirmed = P.reconstruct(*single(one_face))
        self.assertEqual(unconfirmed['events'], [])
        self.assertEqual(unconfirmed['unconfirmed_activity_count'], 1)
        for seed in range(5):
            blank = P.reconstruct(*P.acquire([], noise_seed=seed, window_end_ns=5000.))
            self.assertEqual(blank['events'], [])

    def test_replay_requires_verified_endpoints_and_all_signed_contacts(self):
        native = pulse()
        with self.assertRaisesRegex(ValueError, 'verified terminal'):
            P.prepare_native(native, CHANNELS, terminal_complete=False)
        del native[34]
        with self.assertRaisesRegex(ValueError, '34 signed'):
            prepare(native)


if __name__ == '__main__':
    unittest.main()
