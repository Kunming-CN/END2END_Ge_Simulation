import unittest
from unittest.mock import patch

import numpy as np

import gegi_digital_readout as digital
import gegi_exposure_stream as exposure
import gegi_pulse_stream as frozen
import gegi_trigger_windows as windows
from test_gegi_pulse_stream import prepare, pulse


class ExposureStreamTest(unittest.TestCase):
    def test_selectable_coincidence_matches_both_adc_reconstruction_paths(self):
        components = [(prepare(pulse(energy=13.)), 17., 1.)]
        clock = exposure.ADCExposure(components, live_time_ns=6000., noise_seed=61)
        t, code = frozen.acquire(components, noise_seed=61, window_end_ns=5999.99)
        standard = exposure.reconstruct_exposure(clock, block_samples=7)
        self.assertEqual(standard, exposure.reconstruct_exposure(clock, block_samples=7, trigger_profile='standard'))
        self.assertFalse(standard['events'])
        self.assertFalse(frozen.reconstruct(t, code)['events'])

        alternative = exposure.reconstruct_exposure(clock, block_samples=7, trigger_profile='low-energy')
        self.assertEqual(alternative['adc_sha256'], standard['adc_sha256'])
        self.assertEqual(len(alternative['events']), 1)
        continuous = alternative['events'][0]
        [short] = frozen.reconstruct(t, code, trigger_profile='low-energy')['events']
        self.assertEqual((continuous['trigger_time_ns'], continuous['contact_ids']),
                         (short['trigger_time_ns'], [3, 24]))
        self.assertAlmostEqual(continuous['slow_energy_keV'], short['slow_energy_keV'], places=9)
        self.assertEqual(exposure.reconstruct_exposure(clock, block_samples=7), standard)

    def test_global_adc_codes_match_one_acquisition_across_seams(self):
        a = prepare(pulse(neighbor=True))
        b = prepare(pulse((4, 21), energy=136.))
        components = [(a, 0., 1.), (b, 94.3, .8), (a, 1110.6, .5), (b, 2317., 1.)]
        clock = exposure.ADCExposure(components, live_time_ns=5000., phase_ns=11.5, noise_seed=271)
        time, expected = frozen.acquire(components, phase_ns=11.5, noise_seed=271, window_end_ns=4999.99)
        for block in (1, 5, 29, 256):
            with self.subTest(block=block):
                segments = list(clock.blocks(block))
                indices = [np.arange(first, first+code.shape[1]) for first, code in segments]
                np.testing.assert_array_equal(clock.sample_time_ns(np.concatenate(indices)), time)
                code = np.concatenate([row[1] for row in segments], axis=1)
                self.assertEqual(code.dtype, np.int16)
                np.testing.assert_array_equal(code, expected)

    def test_same_pass_capture_uses_existing_context_and_matches_adc_export(self):
        first, second = prepare(pulse((3, 24), energy=190.)), prepare(pulse((11, 26), energy=470.))
        components = [(first, 2017., 1.), (second, 2017., 1.)]
        clock = exposure.ADCExposure(components, live_time_ns=10000., phase_ns=7., noise_seed=23)
        captured = {}

        def save(event, offset, code):
            t = event['trigger_time_ns']
            captured[t] = windows.capture_context(clock, t, [], offset, code)

        with patch.object(clock, 'blocks', wraps=clock.blocks) as blocks:
            readout = exposure.reconstruct_exposure(clock, block_samples=11, on_trigger=save)
        self.assertEqual(blocks.call_count, 2)
        times = [row['trigger_time_ns'] for row in readout['events']]
        self.assertEqual(len(times), 1)
        direct = windows.context_arrays(times, captured, readout.pop('acquisition_baseline_v'), readout['adc_sha256'])
        self.assertEqual(readout, exposure.reconstruct_exposure(clock, block_samples=11))
        replay = windows.capture(clock, times, [])
        for key in replay:
            np.testing.assert_array_equal(direct[key], replay[key])

    def test_dsp_state_at_seams_and_true_last_sample(self):
        a = prepare(pulse((3, 24)))
        b = prepare(pulse((12, 29), energy=260.))
        d = prepare(pulse((11, 26), energy=160.))
        components = [(a, 0., 1.), (a, 1902.27, .7), (b, 5258.5, 1.),
                      (d, 5850.1, 1.), (b, 9820.1, 1.)]
        clock = exposure.ADCExposure(components, live_time_ns=10000., phase_ns=7., noise_seed=23)
        t, code = frozen.acquire(components, phase_ns=7., noise_seed=23, window_end_ns=9999.99)
        old = frozen.reconstruct(t, code)
        measured = exposure.reconstruct_exposure(clock, block_samples=41)
        self.assertEqual(measured, exposure.reconstruct_exposure(clock, block_samples=11))
        self.assertGreater(len(measured['events']), 2)
        self.assertGreater(sum(row['slow_energy_keV'] is not None for row in measured['events']), 1)
        self.assertEqual(len(measured['events']), len(old['events']))
        self.assertEqual(measured['unconfirmed_activity_count'], old['unconfirmed_activity_count'])
        self.assertIn('slow_window_truncated', measured['events'][-1]['flags'])
        numeric = ('slow_energy_keV', 'slow_plateau_span_keV', 'fast_signal_keV_equiv', 'preamp_cfd50_ns')
        for candidate, reference in zip(measured['events'], old['events']):
            for key in ('trigger_time_ns', 'rise_end_ns', 'flags', 'contact_ids', 'step_contact_ids'):
                self.assertEqual(candidate[key], reference[key])
            for x, y in zip(candidate['channels'], reference['channels']):
                self.assertEqual(x['flags'], y['flags'])
                for key in numeric:
                    if y[key] is None:
                        self.assertIsNone(x[key])
                    else:
                        self.assertAlmostEqual(x[key], y[key], places=9)

    def test_explicit_rails_and_free_decay_past_native_support(self):
        a = prepare(pulse())
        b = prepare(pulse((3, 24), 2500.))
        components = [(a, 0., 1.), (b, 22000.3, 1.3)]
        clock = exposure.ADCExposure(components, live_time_ns=150000., noise_seed=None)
        t, expected = frozen.acquire(components, window_end_ns=149999.9)
        codes = np.concatenate([row[1] for row in clock.blocks(977)], axis=1)
        np.testing.assert_array_equal(codes, expected)
        self.assertGreater(np.count_nonzero(codes[2] == digital._ADC_MAX), 0)
        self.assertGreater(abs(int(codes[2, -1])), 0)
        observed = exposure.reconstruct_exposure(clock, block_samples=977)
        self.assertEqual(observed['saturated_contact_ids'], [3, 24])
        self.assertEqual(observed['saturated_adc_codes'], int(np.count_nonzero(codes == digital._ADC_MAX)))


if __name__ == '__main__':
    unittest.main()
