"""Analytic geometry and common-measure checks for the point-source primitive."""

import math
import unittest

import numpy as np

import gegi_photon_continuation as photon
import gegi_photon_observed_energy as measured
import gegi_point_source_response as model


class PointSourceResponseTests(unittest.TestCase):
    def setUp(self):
        self.crystal = (np.vstack((np.eye(3), -np.eye(3))), np.full(6, 12.))
        self.first = [0., 0., 0.]
        self.second = [2., 0., 0.]
        self.incident = 800.

    def test_forward_and_backward_compton_endpoints(self):
        forward = model.first_compton_state([-5., 0., 0.], self.first, self.second, self.incident)
        backward = model.first_compton_state([5., 0., 0.], self.first, self.second, self.incident)
        lower = self.incident/(1+2*self.incident/photon.ELECTRON_REST_KEV)
        self.assertEqual(forward['first_scatter_cosine'], 1.)
        self.assertEqual(forward['intermediate_keV'], self.incident)
        self.assertEqual(forward['expected_first_deposit_keV'], 0.)
        self.assertEqual(backward['first_scatter_cosine'], -1.)
        self.assertEqual(backward['intermediate_keV'], lower)
        self.assertAlmostEqual(backward['expected_first_deposit_keV'], self.incident-lower, places=12)

    def test_finite_vertex_incoming_ray_and_far_field_limit(self):
        first, second = [2., 1., 0.], [4., 1., 0.]
        near = model.first_compton_state([0., 0., 0.], first, second, self.incident)
        far = model.first_compton_state([-1e12, 0., 0.], first, second, self.incident)
        self.assertAlmostEqual(near['first_scatter_cosine'], 2/math.sqrt(5), places=14)
        self.assertAlmostEqual(far['first_scatter_cosine'], 1., places=14)
        self.assertGreater(near['expected_first_deposit_keV'], 100.)
        self.assertAlmostEqual(far['intermediate_keV'], self.incident, places=10)
        self.assertEqual(near['site_separation_mm'], far['site_separation_mm'])

    def test_absorption_and_escape_share_energy_measure_and_volume_conversion(self):
        rates = photon.PhotonRates(.15, .025, .1)
        table = measured.total_rate_interpolator({100.: rates, self.incident: rates})
        source = [0., -4., 0.]
        state = model.first_compton_state(source, self.first, self.second, self.incident)
        deposit, intermediate = state['expected_first_deposit_keV'], state['intermediate_keV']
        calls = []

        def rates_at(energy):
            calls.append(energy)
            return rates

        result = model.point_source_response(self.crystal, source, self.first, self.second, self.incident,
                                             deposit+1., 110., rates_at, table, sigma_first_keV=2.,
                                             sigma_second_keV=30., azimuth_samples=16, energy_order=48)
        self.assertEqual(calls, [intermediate])
        self.assertEqual(result['intermediate_keV'], intermediate)
        self.assertAlmostEqual(result['first_measurement_density_per_keV'], math.exp(-1/8)/(math.sqrt(2*math.pi)*2), places=14)
        kn_per_volume = photon.solid_angle_density_per_sr(self.incident, 0.)/4
        factor = kn_per_volume*result['first_measurement_density_per_keV']
        tail = result['second_site_response']
        for branch in ('absorption', 'escape'):
            with self.subTest(branch=branch):
                density = result[branch+'_per_mm3_observed_keV2']
                self.assertGreater(density, 0.)
                self.assertAlmostEqual(density, factor*tail['observations'][0][branch+'_per_mm_observed_keV'], places=15)
                self.assertAlmostEqual(result['energy_integrated_branch_density_per_mm3'][branch],
                                       kn_per_volume*tail['observed_integrated_mass_per_mm'][branch], places=14)
        photo = math.exp(-2*rates.total_per_mm)*rates.photoelectric_per_mm
        self.assertAlmostEqual(result['energy_integrated_branch_density_per_mm3']['absorption'], kn_per_volume*photo, places=14)

    def test_narrow_gaussians_use_geometry_and_keep_integrated_branch_mass(self):
        rate = photon.PhotonRates(.15, .025, 0.)

        def evaluate(second, observed_first, sigma):
            return model.point_source_response(self.crystal, [-4., 0., 0.], self.first, second, self.incident,
                                               observed_first, self.incident, lambda _: rate, lambda _: .15,
                                               sigma_first_keV=sigma, sigma_second_keV=sigma, azimuth_samples=4, energy_order=8)

        narrow = evaluate(self.second, 0., .001)
        broad = evaluate(self.second, 0., .01)
        displaced = evaluate(self.second, -.01, .001)
        longer = evaluate([4., 0., 0.], 0., .001)
        key = 'absorption_per_mm3_observed_keV2'
        self.assertAlmostEqual(narrow[key]/broad[key], 100., places=11)
        self.assertAlmostEqual(displaced[key]/narrow[key], math.exp(-50.), places=30)
        self.assertAlmostEqual(narrow[key]/longer[key], 4*math.exp(.3), places=11)
        self.assertEqual(displaced['intermediate_keV'], self.incident)
        self.assertEqual(narrow['energy_integrated_branch_density_per_mm3'], broad['energy_integrated_branch_density_per_mm3'])

    def test_coincident_points_and_invalid_widths_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'distinct source'):
            model.first_compton_state(self.first, self.first, self.second, self.incident)
        with self.assertRaisesRegex(ValueError, 'distinct interaction vertices'):
            model.first_compton_state(self.second, self.first, self.first, self.incident)
        for first, second in ((0., 1.), (1., 0.)):
            with self.assertRaisesRegex(ValueError, 'explicit positive Gaussian width'):
                model.point_source_response(self.crystal, [-4., 0., 0.], self.first, self.second, self.incident, 0., 800.,
                                            lambda _: photon.PhotonRates(.1, .04, .05), lambda _: .1,
                                            sigma_first_keV=first, sigma_second_keV=second)


if __name__ == '__main__':
    unittest.main()
