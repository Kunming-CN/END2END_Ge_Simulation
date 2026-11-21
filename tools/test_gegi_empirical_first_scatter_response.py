"""Targeted checks of the shared outgoing-energy integral."""

import math
import unittest

import numpy as np

import gegi_empirical_first_scatter_response as response
from gegi_escape_response_curve import log_tail_envelope
from gegi_photon_continuation import ELECTRON_REST_KEV, PhotonRates
from gegi_photon_observed_energy import observed_continuation
from gegi_point_source_response import first_compton_state, point_source_response


LOG_FACTOR = 'log_covered_factor_per_mm3_observed_keV2'
FACTOR = 'covered_factor_per_mm3_observed_keV2'


def verified_curve(energies, logs, observation, sigma):
    return dict(status='verified_heldout_curve', domain_keV=[energies[0], energies[-1]],
                model=dict(measured_second_site_keV=observation, sigma_second_keV=sigma),
                comparison=dict(nodes=[dict(intermediate_keV=e, log_escape_density=log)
                                       for e, log in zip(energies, logs, strict=True)]))


class EmpiricalFirstScatterResponseTests(unittest.TestCase):
    def setUp(self):
        self.rate = PhotonRates(.18, .03, .1)
        self.rates_at = lambda _: self.rate
        self.first = [0., 0., 0.]
        self.second = [2., 0., 0.]
        self.source = [0., -4., 0.]

    def test_both_observations_and_second_survival_follow_each_same_atom(self):
        energies = np.array([300., 500.])
        weights = np.array([.4, .6])
        observed, width = (300., 500.), (80., 100.)
        second_logs = [-7., -8.]
        curve = verified_curve(energies, second_logs, observed[1], width[1])
        calls = []

        def rates_at(energy):
            calls.append(energy)
            return PhotonRates(energy/1000, .03, .1)

        result = response.integrate_atoms(800., 2., observed, width, energies, weights, rates_at, (50., 800.), curve)
        self.assertEqual(calls, list(energies))
        g1 = np.exp(response.log_gaussian(observed[0], 800.-energies, width[0]))
        g2 = np.exp(response.log_gaussian(observed[1], energies, width[1]))*.03*np.exp(-2*energies/1000)
        for name, second in (('absorption', g2), ('escape', np.exp(second_logs))):
            actual = result[name]
            expected = weights @ (g1*second)/4
            self.assertAlmostEqual(actual[LOG_FACTOR], math.log(expected), places=13)
            self.assertAlmostEqual(actual[FACTOR], expected, places=18)
            self.assertGreater(abs(actual[FACTOR]-(weights @ g1)*(weights @ second)/4), expected/10)

    def test_delta_kernel_reproduces_legacy_with_first_angular_factor_removed(self):
        incident = 800.
        state = first_compton_state(self.source, self.first, self.second, incident)
        e = state['intermediate_keV']
        observation = (state['expected_first_deposit_keV']+1., 110.)
        widths = (2., 30.)
        crystal = (np.vstack((np.eye(3), -np.eye(3))), np.full(6, 12.))
        parameters = dict(azimuth_samples=8, energy_order=16, include_log=True)
        energies = [e-10., e, e+10.]
        logs = [observed_continuation(crystal, self.first, self.second, value, self.rate, lambda _: .18,
                                    [observation[1]], sigma_keV=widths[1], **parameters)
                ['observations'][0]['log_escape_per_mm_observed_keV'] for value in energies]
        curve = verified_curve(energies, logs, observation[1], widths[1])
        kernel = dict(incident_energies_keV=[incident], cosine_bin_centers=[0.],
                      native_metadata=dict(native_electron_rest_keV=ELECTRON_REST_KEV),
                      incident_groups=[dict(livermore_bins=[dict(development_residual_atoms=[0.])])])
        empirical = response.point_response(kernel, self.source, self.first, self.second, incident, observation, widths,
                                            self.rates_at, (50., 800.), curve)
        analytic = point_source_response(crystal, self.source, self.first, self.second, incident, *observation,
                                         self.rates_at, lambda _: .18, sigma_first_keV=widths[0],
                                         sigma_second_keV=widths[1], **parameters)
        self.assertEqual(empirical['outgoing_atoms'], 1)
        for name in response.BRANCHES:
            branch = empirical['branches'][name]
            self.assertEqual(branch['coverage_status'], 'full')
            self.assertAlmostEqual(branch[LOG_FACTOR], analytic['log_'+name+'_per_mm3_observed_keV2']
                                   -math.log(analytic['first_kn_density_per_sr']), places=12)

    def test_log_tail_retains_raw_underflow_separately_from_unavailable(self):
        e, obs, sigma = 338.1621626347227, 994.3512817206695, 2.
        nodes = [e, e+10.]
        curve = verified_curve(nodes, log_tail_envelope(nodes, obs, sigma)-4., obs, sigma)
        observed = (835.0658373652773, obs)
        result = response.integrate_atoms(1173.228, 2., observed, (2., sigma), [e], [1.],
                                           self.rates_at, (50., 1200.), curve)
        for name in response.BRANCHES:
            row = result[name]
            self.assertEqual(row['coverage_status'], 'full')
            self.assertEqual(row['covered_density_status'], 'underflow')
            self.assertEqual(row[FACTOR], 0.)
            self.assertTrue(math.isfinite(row[LOG_FACTOR]))
        unknown = response.integrate_atoms(1173.228, 2., observed, (2., sigma), [e], [1.],
                                            self.rates_at, (50., 1200.), None)['escape']
        self.assertEqual(unknown['uncovered_mass'], 1.)
        self.assertIsNone(unknown[LOG_FACTOR])
        self.assertIsNone(unknown[FACTOR])
        self.assertEqual(unknown['covered_density_status'], 'unavailable')
        absent_rate = response.integrate_atoms(1173.228, 2., observed, (2., sigma), [e], [1.],
                                                lambda _: PhotonRates(.1, 0., .09), (50., 1200.), None)['absorption']
        self.assertEqual(absent_rate['covered_mass'], 1.)
        self.assertEqual(absent_rate['covered_density_status'], 'physical_zero')
        self.assertIsNone(absent_rate[LOG_FACTOR])
        self.assertEqual(absent_rate[FACTOR], 0.)

    def test_uncovered_mass_partitions_by_support_and_never_renormalizes(self):
        nodes = [80., 120., 200., 300., 900.]
        weights = [.1, .2, .3, .1, .3]
        observation, widths = (800., 200.), (10., 10.)
        curve = verified_curve([180., 220.], [-9., -9.], observation[1], widths[1])
        result = response.integrate_atoms(1000., 2., observation, widths, nodes, weights,
                                           self.rates_at, (100., 800.), curve)
        a, e = result['absorption'], result['escape']
        self.assertEqual(a['coverage_status'], 'partial')
        self.assertAlmostEqual(a['covered_mass'], .6)
        self.assertAlmostEqual(a['uncovered_mass'], .4)
        self.assertEqual(e['coverage_status'], 'partial')
        self.assertEqual(e['covered_mass'], .3)
        self.assertAlmostEqual(e['uncovered_mass'], .7)
        self.assertEqual(set(e['node_accounting']), {response.COMPUTED, response.UNSUPPORTED_RATE,
                         'outgoing_coefficients_unavailable', 'outside_validated_curve_domain'})
        self.assertAlmostEqual(sum(x['mass'] for x in e['node_accounting'].values()), 1.)
        self.assertEqual(sum(x['nodes'] for x in e['node_accounting'].values()), len(nodes))
        delta = response.integrate_atoms(1000., 2., observation, widths, [200.], [1.],
                                          self.rates_at, (100., 800.), curve)['escape']
        self.assertAlmostEqual(e[LOG_FACTOR]-delta[LOG_FACTOR], math.log(.3), places=13)
        extension = response.coefficient_extension([{'branches': result}], {100.: self.rate, 800.: self.rate}, .07)
        for name, lower in (('absorption', 80.), ('escape', 80./(1+160./ELECTRON_REST_KEV))):
            gap = extension['branches'][name]
            self.assertEqual(gap['missing_endpoint_ranges_keV']['below_table_keV'][0], lower)
            self.assertEqual(gap['missing_endpoint_ranges_keV']['above_table_keV'], [900., 900.])
            below = [e for e in gap['suggested_query_energies_keV'] if e < 100.]
            above = [e for e in gap['suggested_query_energies_keV'] if e > 800.]
            self.assertEqual((below[0], above[-1]), (lower, 900.))
            for arr in (below+[100.], [800.]+above):
                self.assertLessEqual(float(np.diff(np.log(arr)).max()), .07)
        with self.assertRaisesRegex(ValueError, 'this second-site observation and width'):
            response.integrate_atoms(1000., 2., (800., 201.), widths, [200.], [1.],
                                     self.rates_at, (100., 800.), curve)

    def test_unrepresented_line_has_no_assigned_kernel_mass(self):
        kernel = dict(incident_energies_keV=[662.])
        result = response.point_response(kernel, self.source, self.first, self.second, 661.657, (200., 461.657),
                                         (2., 2.), self.rates_at, (100., 800.), None)
        self.assertEqual(result['status'], 'incident_energy_unrepresented')
        self.assertIsNone(result['kernel_mass'])
        for branch in result['branches'].values():
            self.assertIsNone(branch['covered_mass'])
            self.assertIsNone(branch['uncovered_mass'])


if __name__ == '__main__':
    unittest.main()
