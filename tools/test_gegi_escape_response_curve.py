import math
import unittest
from unittest.mock import patch

import numpy as np

import gegi_escape_response_curve as curve
import gegi_photon_continuation as photon


class EscapeResponseCurveTests(unittest.TestCase):
    def test_factored_log_interpolation_preserves_extreme_gaussian_tails(self):
        nodes = np.linspace(200., 660., 25)
        held_out = (nodes[:-1]+nodes[1:])/2
        observed, sigma = 418., 2.

        def analytic(energy):
            return curve.log_tail_envelope(energy, observed, sigma)-.004*energy-6.

        fit = curve.EscapeResponseCurve(nodes, analytic(nodes), observed_keV=observed, sigma_keV=sigma)
        estimate = fit.log_density(held_out)
        np.testing.assert_allclose(estimate, analytic(held_out), rtol=0, atol=1e-10)
        self.assertLess(estimate[0], math.log(np.nextafter(0., 1.)))
        with self.assertRaisesRegex(ValueError, 'outside'):
            fit.log_density([200., 700.])
        with self.assertRaisesRegex(ValueError, 'finite logs'):
            curve.EscapeResponseCurve(nodes, np.full(nodes.shape, -np.inf), observed_keV=observed, sigma_keV=sigma)

    def test_extra_knots_cover_gaussian_endpoint_transition(self):
        observed, sigma = 127., 2.
        nodes = curve.response_nodes(210., 1300., observed, sigma, 25)
        deposit = 2*nodes**2/(photon.ELECTRON_REST_KEV+2*nodes)
        self.assertEqual([nodes[0],nodes[-1]], [210.,1300.])
        self.assertTrue(np.all(np.diff(nodes) > 0))
        self.assertTrue(any(np.isclose(deposit, observed, atol=1e-12, rtol=0)))

    def test_benchmark_validates_only_energies_absent_from_its_knots(self):
        def exact(energies, *args, **kwargs):
            for e in energies:
                log = float(curve.log_tail_envelope(e,418.,2.))-.003*e-5.
                yield dict(intermediate_keV=e, log_escape_density=log, log_quadrature_difference=0.,
                           raw_escape_density=math.exp(log), density_status='raw_density_underflow' if log < -745 else 'positive')

        with patch.object(curve, 'direct_logs', side_effect=exact):
            result = curve.benchmark_curve(np.linspace(185.,660.,2400), None, None, None,418.,None,None,
                sigma_keV=2.,azimuth_samples=256,energy_order=256,base_nodes=25,max_log_error=.01)
        fit_energies={r['intermediate_keV'] for r in result['nodes']}
        held_out={r['intermediate_keV'] for r in result['held_out']}
        self.assertEqual(len(held_out), len(fit_energies)-1)
        self.assertFalse(fit_energies & held_out)
        self.assertTrue(result['matches_log_target'])
        self.assertLess(result['max_absolute_log_error'],1e-9)
        self.assertGreater(result['max_absolute_log_error_without_envelope'],1.)

    def test_refinement_reuses_direct_points_and_tests_new_midpoints(self):
        queried = set()

        def exact(energies, *args, **kwargs):
            for e in energies:
                self.assertNotIn(e, queried)
                queried.add(e)
                value = float(curve.log_tail_envelope(e, 290., 2.)) + .08*math.sin((e-200.)/20.)-5.
                yield dict(intermediate_keV=float(e), log_escape_density=value, log_quadrature_difference=0.,
                           raw_escape_density=math.exp(value), density_status='supported')

        energies = np.linspace(200.,300.,200)
        settings = dict(sigma_keV=2., azimuth_samples=256, energy_order=256, base_nodes=3, max_log_error=.01)
        args = (energies, None, None, None, 290., None, None)
        with patch.object(curve, 'direct_logs', side_effect=exact):
            baseline = curve.benchmark_curve(*args, **settings)
            self.assertFalse(baseline['matches_log_target'])
            result = curve.benchmark_curve(*args, **settings, prior=baseline)
        self.assertTrue(result['matches_log_target'])
        self.assertGreater(result['new_direct_points'], 0)
        self.assertEqual(len(queried), result['new_direct_points']+result['retained_direct_points'])
        self.assertFalse({r['intermediate_keV'] for r in result['nodes']} &
                         {r['intermediate_keV'] for r in result['held_out']})


if __name__ == '__main__':
    unittest.main()
