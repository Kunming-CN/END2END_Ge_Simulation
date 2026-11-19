import unittest

import numpy as np

import gegi_fast_pileup_study as study
import gegi_pulse_stream as stream
from test_gegi_digital_readout import CHANNELS, event_native


def fixture_pulse():
    native = event_native({3: [0., 120., 120., 120.], 24: [0., 120., 120., 120.],
                           2: [0., 15., 15., 0.], 4: [0., -13., -13., 0.]})
    return stream.prepare_native(native, CHANNELS, terminal_complete=True)


class FastPileupStudyTest(unittest.TestCase):
    def test_seeded_controls_are_aligned_in_absolute_adc_time(self):
        pulse = fixture_pulse()
        first, second = (pulse, 1000, 1.), (pulse, 2000, .5)
        windows = [study.exposure(c, 10, 42) for c in ((first, second), (first,), (second,))]
        pair, alone_first, alone_second = [list(window.blocks()) for window in windows]
        np.testing.assert_array_equal(pair[0][1], alone_first[0][1])
        np.testing.assert_array_equal(pair[0][1], alone_second[0][1])
        time = windows[0].sample_time_ns(np.arange(windows[0].live_samples))
        np.testing.assert_array_equal(pair[1][1][:, time < 2000], alone_first[1][1][:, time < 2000])
        np.testing.assert_array_equal(pair[1][1][8], alone_first[1][1][8])
        np.testing.assert_array_equal(pair[1][1][8], alone_second[1][1][8])

    def test_unflagged_ratio_difference_is_measured_and_attributed(self):
        paired = {'low': {'fast_keV_equiv': 2., 'flags': []},
                  'high': {'fast_keV_equiv': -2., 'flags': []}, 'fast_ratio': .032}
        control = {'low': {'fast_keV_equiv': 2., 'flags': []},
                   'high': {'fast_keV_equiv': -1., 'flags': []}, 'fast_ratio': .03}
        result = study.compare_axis(paired, control, 125., 100.)
        self.assertEqual(result['status'], 'compared')
        self.assertAlmostEqual(result['paired_minus_isolated_ratio'], .002)
        self.assertAlmostEqual(result['fast_numerator_contribution'], .01)
        self.assertAlmostEqual(result['slow_denominator_contribution'], -.008)
        paired.update(fast_ratio=None, high={'fast_keV_equiv': None, 'flags': ['fast_pileup']})
        self.assertEqual(study.compare_axis(paired, control, 125., 100.),
                         {'status': 'paired_fast_unavailable', 'reasons': ['fast_pileup']})

    def test_resolved_and_merged_observations_use_production_triggers(self):
        pulse = fixture_pulse()
        neighbors = {3: (2, 4), 24: (23, 25)}
        first = (pulse, 1000, 1.)
        for second_onset in (1000, 4000):
            with self.subTest(second_onset=second_onset):
                second = (pulse, second_onset, .75)
                isolated = [study.observe([component], 10, 42, neighbors)[0][0]
                            for component in (first, second)]
                cards, _ = study.observe([first, second], 10, 42, neighbors)
                anchors = [c['trigger_time_ns'] for c in isolated]
                result = study.compare_trial(cards, anchors, isolated, [[3, 24], [3, 24]],
                                             distinct_onsets=second_onset > 1000)
                if second_onset == 1000:
                    self.assertEqual(result['status'], 'one_trigger_for_two_pulses')
                    self.assertTrue(all(p['axes'] == {} for p in result['pulses']))
                else:
                    self.assertEqual(result['status'], 'two_distinct_triggers')
                    self.assertTrue(all(p['axes']['x']['status'] == 'compared' for p in result['pulses']))


if __name__ == '__main__':
    unittest.main()
