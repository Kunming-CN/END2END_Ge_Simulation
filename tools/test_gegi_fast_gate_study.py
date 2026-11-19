import unittest

import numpy as np

import gegi_fast_gate_study as study
import gegi_pulse_stream as stream
from test_gegi_digital_readout import CHANNELS, event_native


class FastGateStudyTest(unittest.TestCase):
    def test_onset_reference_uses_first_sample_at_or_after_injection(self):
        base = np.arange(940, 1080, 20)
        self.assertEqual(base[study.onset_sample(base, 1000)], 1000)
        for phase in (5, 10, 15):
            shifted = base + phase
            self.assertEqual(shifted[study.onset_sample(shifted, 1000)], 1000 + phase)

    def test_both_gates_use_same_baseline_and_half_weight_endpoints(self):
        fast = np.full(24, 5.)
        fast[3] = 11.
        fast[15] = 17.
        trigger_area, onset_area = study.gate_areas(fast, trigger_index=3, onset_index=2)
        # Both subtract 7 V. The 6 V excursion at sample 3 has half weight
        # on the trigger gate and full weight on the onset gate. Sample 15
        # has half weight on the trigger gate and is outside the onset gate.
        self.assertEqual(trigger_area, -300.)
        self.assertEqual(onset_area, -360.)

    def test_same_adc_gate_comparison_sign_and_normalization(self):
        pulse = event_native({3: [0., 120., 120., 120.], 24: [0., 120., 120., 120.],
                              2: [0., 15., 15., 0.], 4: [0., -13., -13., 0.]})
        prepared = stream.prepare_native(pulse, CHANNELS, terminal_complete=True)
        for phase in (0, 10):
            with self.subTest(phase=phase):
                row = study.evaluate_pulse(prepared, 1., (3, 24), {3: (2, 4), 24: (23, 25)}, phase)
                self.assertEqual(row['status'], 'measured')
                self.assertEqual(row['onset_grid_time_ns'], study.ONSET_NS + phase)
                self.assertEqual(row['trigger_minus_onset_grid_ns'], row['trigger_minus_injection_ns'] - phase)
                axis = row['axes']['x']
                low, high = axis['trigger_fast_keV_equiv_low_high']
                self.assertGreater(low, 0.)
                self.assertLess(high, 0.)
                self.assertAlmostEqual(axis['trigger_ratio'], (low - high) / row['single_pixel_energy_keV'])
                onset_low, onset_high = axis['onset_fast_keV_equiv_low_high']
                self.assertAlmostEqual(axis['onset_ratio'], (onset_low - onset_high) / row['single_pixel_energy_keV'])
                if phase == 0:
                    self.assertEqual(row['trigger_minus_onset_grid_ns'], 0.)
                    self.assertAlmostEqual(axis['trigger_minus_onset_ratio'], 0.)


if __name__ == '__main__':
    unittest.main()
