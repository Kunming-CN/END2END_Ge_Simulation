"""Contracts for bounded calibration and held-out error accounting."""

import unittest

import gegi_pixel_cfd_depth_study as study


def measured(z, cfd):
    return dict(measurement_status='measured', injected_xyz_mm=[0, 0, z], cfd_x_minus_y_ns=cfd)


class DepthCurveTests(unittest.TestCase):
    def test_both_monotone_directions_and_exact_range(self):
        for direction in (-1, 1):
            with self.subTest(direction=direction):
                curve = study.fit_curve([measured(z, direction * t) for z, t in [(-2, 0), (0, 10), (1, 20)]])
                self.assertEqual(curve['direction'], direction)
                self.assertEqual(study.estimate_depth(curve, measured(9, direction * 5)), ('estimated', -1))
                self.assertEqual(study.estimate_depth(curve, measured(9, direction * 20)), ('estimated', 1))
                self.assertEqual(study.estimate_depth(curve, measured(9, direction * 21)),
                                 ('outside_calibrated_cfd_range', None))

    def test_missing_outer_knot_can_trim_but_internal_gap_withholds_curve(self):
        absent = {'measurement_status': 'native_record_unqualified'}
        rows = [measured(-1, 0), measured(0, 10), measured(1, 20)]
        trimmed = study.fit_curve([absent, *rows, absent])
        self.assertEqual(trimmed['z_mm'], [-1, 0, 1])
        self.assertEqual(study.fit_curve([rows[0], absent, *rows[1:]])['status'], 'interior_center_knots_missing')
        self.assertEqual(study.fit_curve(rows[:2])['status'], 'insufficient_center_knots')

    def test_reversal_or_quantized_tie_withholds_curve(self):
        for cfd in (0, 1):
            curve = study.fit_curve([measured(-1, 0), measured(0, 1), measured(1, cfd)])
            self.assertEqual(curve['status'], 'nonmonotonic_center_timing')
            self.assertEqual(study.estimate_depth(curve, measured(7, 0)), ('nonmonotonic_center_timing', None))

    def test_midplane_baseline_uses_the_paired_validation_population(self):
        rows = [dict(injected_xyz_mm=[1, 2, 2], estimated_z_mm=1.5, estimate_status='estimated'),
                dict(injected_xyz_mm=[1, 2, 5], estimated_z_mm=None, estimate_status='outside_calibrated_cfd_range')]
        summary = study.summarize(rows)
        self.assertEqual((summary['intended'], summary['estimated']), (2, 1))
        self.assertEqual((summary['paired_cfd_rms_mm'], summary['paired_midplane_rms_mm']), (.5, 2))
        self.assertEqual(summary['status_counts'], {'estimated': 1, 'outside_calibrated_cfd_range': 1})
        self.assertGreater(summary['all_midplane_rms_mm'], summary['paired_midplane_rms_mm'])


if __name__ == '__main__':
    unittest.main()
