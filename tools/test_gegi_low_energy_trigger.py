"""Checks for the bounded GeGI threshold study."""

import math
import unittest

import numpy as np

import gegi_exposure_stream as adc
import gegi_low_energy_trigger as study
from test_gegi_pulse_stream import prepare, pulse


class TriggerStudyTests(unittest.TestCase):
    def test_nominal_activity_and_trigger_parity_across_small_blocks(self):
        acquisition = adc.ADCExposure([(prepare(pulse()), 17.0, 1.)], live_time_ns=8000, noise_seed=17)
        block_size = 7
        baseline, peaks, digest = study.scan(acquisition, block_size)
        _, nominal_groups, _, nominal_digest = adc._find_activity(acquisition, block_size)
        self.assertEqual(digest, nominal_digest)
        self.assertEqual([(a, b, peak >= study.NOMINAL) for a, b, peak in peaks], nominal_groups)
        nominal = adc.reconstruct_exposure(acquisition, block_samples=block_size)
        observed, rejected = study.reconstruct(acquisition, block_size, baseline, peaks, study.NOMINAL)
        self.assertEqual(observed, nominal['events'])
        self.assertEqual(len(observed), 1)
        self.assertEqual(len(rejected), len(nominal['rejected_rises']))

    def test_cross_block_peak_uses_the_smaller_face_increment(self):
        groups = []
        study.register_changes(groups, 0, np.array([[9., 0., 6.], [3.2, 0., 4.2]]))
        study.register_changes(groups, 3, np.array([[0., 4.3, 0.], [0., 8., 0.]]))
        self.assertEqual(groups, [(-1, 4, 4.3)])
        self.assertEqual(study.missed_reason([(0, 4.3)], set(), set()), 'below_coincident_increment_threshold')
        self.assertEqual(study.missed_reason([(0, 5.3)], set(), {0}), 'persistent_face_step_rejected')

    def test_matching_respects_parent_split_and_energy_caliper(self):
        source = 'cs137-left'

        def row(event, kev, group=0):
            return {'source': source, 'raw_event_id': event, 'group_id': group, 'truth_edep_keV': kev}

        missed = row(1, 25.)
        subset = study.partition(missed)
        same = [i for i in range(2, 40) if study.partition(row(i, 0.)) == subset]
        other = next(i for i in range(2, 40) if study.partition(row(i, 0.)) != subset)
        detected = [(1, row(1, 25., group=1)), (2, row(other, 25.)),
                    (3, row(same[0], 25.5)), (4, row(same[1], 36.))]
        self.assertEqual(study.partition(missed), study.partition(detected[0][1]))
        self.assertEqual(study.matched_controls([(0, missed)], detected), {0: 3})
        self.assertEqual(study.matched_controls([(0, missed)], detected[:2] + detected[3:]), {})

    def test_zero_accidentals_does_not_establish_zero_rate(self):
        self.assertAlmostEqual(study.upper_rate(0, .2), -math.log(.05) / .2)
        self.assertGreater(study.upper_rate(1, .2), study.upper_rate(0, .2))


if __name__ == '__main__':
    unittest.main()
