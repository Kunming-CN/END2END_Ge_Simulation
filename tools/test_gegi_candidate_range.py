"""Finite-vertex radial inference and covariance checks, without a detector run."""
import unittest
from dataclasses import replace

import numpy as np
from scipy.optimize import minimize_scalar

import gegi_candidate_range as R
import gegi_joint_imaging as G
from test_gegi_joint_imaging import synthetic_events
from gegi_source_range import profiled_background


class CandidateRangeTests(unittest.TestCase):
    def test_general_covariance_batched_response_matches_kernel(self):
        settings = G.ResponseSettings()
        events = synthetic_events([32., -8., 47.], 8)
        events = [replace(event, candidates=tuple(replace(c,
            position_covariance=np.array([np.diag([.4, .8, .2]), np.diag([.2, .6, .5])]),
            energy_angle_variance=.0007) for c in event.candidates)) for event in events]
        scorer = R.AngularScore(events[:4], events[4:], settings)
        self.assertLess(scorer.validate(25.), 1e-10)

    def test_finite_vertices_recover_unprovided_source_and_close_profile(self):
        source = np.array([31., -13., 49.])
        events = synthetic_events(source, 24)
        settings = G.ResponseSettings(angular_nuisance_sigma_deg=1.)
        scorer = R.AngularScore(events[:12], events[12:], settings)
        result = R.fit_profile(scorer, [25., 40., 60., 90., 150.],
                               mode=(0., 'all'), directions=48, starts=2)
        self.assertLess(np.linalg.norm(np.array(result['position_mm'])-source), .05)
        self.assertFalse(result['at_radial_search_boundary'])
        self.assertEqual(result['profile_diagnostic']['status'], 'closed_profile_requires_independent_calibration')

    def test_centered_vertices_have_no_geometric_range_information(self):
        source = np.array([31., -13., 49.])
        events = synthetic_events(source, 16)
        events = [replace(event, candidates=tuple(replace(c, vertex=np.zeros(3))
                                                  for c in event.candidates)) for event in events]
        settings = G.ResponseSettings(angular_nuisance_sigma_deg=3.)
        scorer = R.AngularScore(events[:8], events[8:], settings)
        result = R.fit_profile(scorer, [30., 60., 150.], mode=(.25, 'all'), directions=32, starts=2)
        self.assertLess(np.ptp([row['log_score'] for row in result['radial_profile']]), 1e-7)
        self.assertTrue(result['profile_diagnostic']['lower_open'])
        self.assertTrue(result['profile_diagnostic']['upper_open'])
        self.assertTrue(result['profile_diagnostic']['far_field_supported'])

    def test_zero_background_preserves_tiny_gaussian_tail_in_log_space(self):
        events = synthetic_events([31., -13., 49.], 8)
        scorer = R.AngularScore(events[:4], events[4:], G.ResponseSettings(angular_nuisance_sigma_deg=.1))
        score = scorer.score(np.array([[-100., 130., -200.]]), (0., 'all'))[0, 0]
        self.assertTrue(np.isfinite(score))
        self.assertLess(score, -100000.)

    def test_profiled_background_matches_independent_scalar_fit_and_endpoints(self):
        response = np.array([[5., 2., .0001, .4], [2., 3., 4., 2.], [.1, .2, .5, .3]])
        values, fractions = profiled_background(np.log(response))
        for row, actual, fraction in zip(response, values, fractions, strict=True):
            objective = lambda b: -np.log((1-b)*row+b).sum()
            fit = minimize_scalar(objective, bounds=(0., 1.), method='bounded', options={'xatol': 1e-13})
            self.assertAlmostEqual(actual, -min(fit.fun, objective(0.), objective(1.)), places=10)
        self.assertEqual(fractions[1], 0.)
        self.assertEqual(fractions[2], 1.)

    def test_far_field_is_finite_vertex_limit_including_axis_uncertainty(self):
        events = synthetic_events([31., -13., 49.], 8)
        events = [replace(event, candidates=tuple(replace(c,
            position_covariance=np.array([np.diag([.4, .8, .2]), np.diag([.2, .6, .5])]))
            for c in event.candidates)) for event in events]
        scorer = R.AngularScore(events[:4], events[4:], G.ResponseSettings())
        units = np.vstack((R.direction(R.sphere_grid(9)), events[0].candidates[0].axis))
        exact = scorer.score(units, (.25, 'all'), far_field=True)
        finite = scorer.score(units*1e12, (.25, 'all'))
        np.testing.assert_allclose(exact, finite, rtol=1e-10, atol=1e-9)


if __name__ == '__main__':
    unittest.main()
