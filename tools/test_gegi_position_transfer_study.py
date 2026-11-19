import unittest
from itertools import product

import gegi_capture_position_target as target
import gegi_position_transfer_study as study


class PositionTransferStudyTest(unittest.TestCase):
    def test_slots_keep_coordinate_sign_and_refuse_out_of_range_values(self):
        edges = [-1. + .2 * i for i in range(11)]
        template = {'depth_knots_mm': [-4., 4.], 'families': {
            'X': {'ratio_edges': [edges, edges]}, 'Y': {'ratio_edges': [edges[::-1], edges[::-1]]}}}
        feature = {'ratio': .5, 'strip_center_mm': 20., 'strip_pitch_mm': 5.}
        self.assertGreater(study.transfer_axis(template, 'X', feature, 0.)['position_mm'], 20.)
        self.assertLess(study.transfer_axis(template, 'Y', feature, 0.)['position_mm'], 20.)
        beyond = study.transfer_axis(template, 'X', feature | {'ratio': 1.2}, 0.)
        self.assertEqual(beyond, {'status': 'ratio_outside_support', 'position_mm': None})

    def test_does_not_bridge_depth_planes_with_opposite_polarities(self):
        template = {'depth_knots_mm': [-1., 1.], 'families': {'Y': {'ratio_edges': [[-1., 1.], [1., -1.]]}}}
        feature = {'ratio': .2, 'strip_center_mm': 0., 'strip_pitch_mm': 5.}
        self.assertEqual(study.transfer_axis(template, 'Y', feature, 0.)['status'], 'ambiguous_signed_polarity')
        self.assertEqual(study.transfer_axis(template, 'Y', feature, 2.)['status'], 'depth_outside_support')

    def test_old_guard_and_unavailable_axis_share_the_same_point_baseline(self):
        rows = [{'truth_xyz_mm': [1., 2., 0.], 'status': 'scored', 'center_xy_mm': [0., 0.],
                 'old_guarded_xy_mm': [0., 0.],
                 'axes': {'x': {'status': 'estimated', 'position_mm': 1.},
                          'y': {'status': 'ambiguous_signed_polarity', 'position_mm': None}}}]
        actual = study.summarize(rows)
        self.assertEqual(actual['paired_xy']['transferred']['n'], 0)
        self.assertEqual(actual['all_scored_with_strip_center_fallback']['old_guarded']['rms_mm'], 5 ** .5)
        self.assertEqual(actual['all_scored_with_strip_center_fallback']['transferred']['rms_mm'], 2.)

    def test_target_holdouts_are_frozen_and_off_center(self):
        channels = [{'id': i, 'strip_center_mm': 3. * i} for i in range(1, 35)]
        points = target.positions(channels)
        self.assertEqual(len(points), 16)
        self.assertTrue(all(p['contact_ids'] == [15, 24] and p['role'] == 'holdout' for p in points))
        self.assertEqual({(*p['offsets_pitch_fraction'], p['position_mm'][2]) for p in points},
                         set(product((-.27, .27), (-.31, .31), (-4.2, -1.15, 1.85, 3.65))))
        self.assertTrue(all(p['position_mm'][:2] != [45., 72.] for p in points))


if __name__ == '__main__':
    unittest.main()
