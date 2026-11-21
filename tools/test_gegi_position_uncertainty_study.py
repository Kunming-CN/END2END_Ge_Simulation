"""Check signed response-error vectors and exact control identity semantics."""

import unittest

import numpy as np

import gegi_position_uncertainty_study as study


class PositionUncertaintyTests(unittest.TestCase):
    def test_reverse_cell_permutation_scores_in_independent_input_order(self):
        truth = [{'contact_ids': [2, 25], 'xyz_mm': [1., 2., 3.], 'energy_keV': 120.},
                 {'contact_ids': [3, 26], 'xyz_mm': [-1., -2., -3.], 'energy_keV': 200.}]
        self.assertEqual(study.exact_cell_order([[3, 26], [2, 25]], truth), [1, 0])
        self.assertIsNone(study.exact_cell_order([[2, 26], [3, 25]], truth))
        self.assertIsNone(study.exact_cell_order([[3, 26], [2, 25]], [*truth, truth[0]]))
        self.assertEqual(study.position_error([3., -1., 3.5], 115., truth[0]), [2., -3., .5, -5.])

    def test_covariance_retains_coupled_and_anticorrelated_site_channels(self):
        rows = [[1., -1., 0., 4., -1., 2., 0., -4.], [3., -1., 2., 8., 1., 0., 0., -8.]]
        result = study.summarize_errors(rows)
        self.assertEqual(result['n'], 2)
        np.testing.assert_array_equal(result['bias'], [2., -1., 1., 6., 0., 1., 0., -6.])
        self.assertAlmostEqual(result['sample_covariance'][3][7], -8.)
        self.assertIsNone(study.summarize_errors(rows[:1])['sample_covariance'])

    def test_unconverged_or_zero_lever_arm_models_cannot_project(self):
        fitness = {'optimizer_success': True, 'positions_mm': [[0., 0., 0.], [0., 0., 2.]]}
        orders = [{'site_index_order': [0, 1], 'kinematically_allowed': True},
                  {'site_index_order': [1, 0], 'kinematically_allowed': False}]
        self.assertEqual(study.available_cones(fitness, [350., 350.], orders), 1)
        self.assertEqual(study.available_cones(dict(fitness, optimizer_success=False), [350., 350.], orders), 0)
        self.assertEqual(study.available_cones(dict(fitness, positions_mm=[[0., 0., 0.]] * 2), [350., 350.], orders), 0)


if __name__ == '__main__':
    unittest.main()
