import unittest
from unittest.mock import patch

import gegi_continuous_position_study as study


def fixture_event():
    return {'trigger_time_ns': 1000., 'contact_ids': [11, 24], 'step_contact_ids': [11, 24],
            'slow_energy_keV': 100., 'flags': [],
            'channels': [{'contact_id': 11, 'slow_energy_keV': 99., 'preamp_cfd50_ns': 37.},
                         {'contact_id': 24, 'slow_energy_keV': 101., 'preamp_cfd50_ns': 118.}]}


def position(x=1., y=2., z=None, field='matching_saved_fields'):
    return {'calibration_source_status': field, 'calibration_pair_coverage': 'simulated_pair',
            'x': {'status': 'estimated' if x is not None else 'ratio_outside_calibration',
                  'position_mm': x, 'strip_center_mm': 0.},
            'y': {'status': 'estimated' if y is not None else 'ratio_outside_calibration',
                  'position_mm': y, 'strip_center_mm': 0.},
            'depth': {'status': 'estimated' if z is not None else 'collector_cfd_unavailable', 'position_mm': z}}


class ContinuousPositionStudyTest(unittest.TestCase):
    def test_scoring_windows_keep_missing_ambiguous_and_unmatched(self):
        events = [{'trigger_time_ns': t} for t in (400, 1060, 1990, 2010)]
        indices, extras = study.match_windows([1000, 2000, 3000], events)
        self.assertEqual(indices, [[1], [2, 3], []])
        self.assertEqual(extras, [0])
        baseline = dict(truth_contact_ids=[11, 24])
        for window, expected in (([], 'missing_trigger'), ([2, 3], 'multiple_triggers_in_window')):
            row = study.evaluate_point(baseline, window, events, {}, [], {})
            self.assertEqual(row['status'], expected)
            self.assertIsNone(row['measurement'])

    def test_estimator_uses_qualified_adc_pair_and_raw_signal_measurements(self):
        event, calibration, channels, identity = fixture_event(), {'frozen': True}, [], {'field': 'saved'}
        with patch.object(study, 'infer_position', return_value=position(z=3.)) as estimate:
            row = study.measure_trigger(event, calibration, channels, identity)
        estimate.assert_called_once_with(calibration, 11, 24, event, channels, source_identity=identity,
                                         mode='cfd_conditioned')
        self.assertEqual(row['collector_measurements'][0]['slow_energy_keV'], 99.)
        self.assertEqual(row['supported_xyz_mm'], [1., 2., 3.])
        with patch.object(study, 'infer_position', return_value=position(z=3., field='nominal_transfer')):
            unverified = study.measure_trigger(event, calibration, channels, identity)
        self.assertIsNone(unverified['supported_xyz_mm'])
        self.assertEqual(unverified['status'], 'calibration_transfer_unverified')
        event['slow_energy_keV'] = None
        with patch.object(study, 'infer_position') as blocked:
            row = study.measure_trigger(event, calibration, channels, identity)
        blocked.assert_not_called()
        self.assertIsNone(row['calibration'])

    def test_fallback_and_full_xyz_keep_their_separate_denominators(self):
        rows = [
            {'status': 'supported_calibration_pair', 'truth_xyz_mm': [1., 2., 3.],
             'measurement': {'calibration': position(y=None, z=3.)}},
            {'status': 'supported_calibration_pair', 'truth_xyz_mm': [1., 2., 3.],
             'measurement': {'calibration': position(z=3.)}},
            {'status': 'missing_trigger', 'truth_xyz_mm': [1., 2., 3.], 'measurement': None},
        ]
        summary = study.summarize(rows)
        self.assertEqual(summary['total_saved_points'], 3)
        self.assertEqual(summary['axis_status_counts']['y'],
                         {'estimated': 1, 'ratio_outside_calibration': 1, 'missing_trigger': 1})
        self.assertEqual(summary['xy_both_available']['substrip']['n'], 1)
        self.assertEqual(summary['supported_xyz']['estimate']['n'], 1)
        self.assertEqual(summary['axes']['depth']['estimate']['n'], 2)
        hybrid = summary['xy_with_measured_strip_center_fallback']['hybrid']
        self.assertEqual(hybrid['n'], 2)
        self.assertAlmostEqual(hybrid['rms_mm'], 2**.5)


if __name__ == '__main__':
    unittest.main()
