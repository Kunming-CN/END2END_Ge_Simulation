"""Check alternate allocation closure and preservation of the original trigger ledger."""

import unittest
from unittest.mock import patch

import numpy as np

import gegi_adc_topology as core
import gegi_candidate_shared_topology as shared
import gegi_candidate_topology as cli
import gegi_incident_hypotheses as incident
import gegi_joint_two_site as joint


class CandidateTopologyTests(unittest.TestCase):
    def test_continuous_nonnegative_family_preserves_reconciled_strip_marginals(self):
        collectors = [{'contact_id': cid, 'slow_energy_keV': value}
                      for cid, value in ((3, 100.), (7, 200.), (18, 131.), (25, 170.))]
        _, flows, ledger, measured, tolerance, matching = core.matching_marginals(collectors)
        self.assertEqual(ledger['rank_deficient_supports'], 1)
        self.assertTrue(any(len(flow) == 3 for flow in flows))
        self.assertTrue(np.all(np.abs(matching - measured) <= tolerance))
        limits, allocate = core.energy_family(matching)
        for value in np.linspace(*limits, 7):
            matrix = allocate(value).reshape(2, 2)
            self.assertTrue(np.all(matrix >= 0.))
            np.testing.assert_allclose(matrix.sum(axis=0), matching[2:], rtol=0, atol=1e-12)
            np.testing.assert_allclose(matrix.sum(axis=1), matching[:2], rtol=0, atol=1e-12)

    def test_optional_subset_retains_original_trigger_order_and_rejects_unknown_ids(self):
        original = {'triggers': [{'original_trigger_id': i} for i in (3, 19, 221)],
                    'fit_receipt': {'candidates': [{}, {}, {}]}}
        selected = cli.population(original, [{}, {}, {}], [221, 3])
        self.assertEqual([row[0]['original_trigger_id'] for row in selected], [3, 221])
        with self.assertRaisesRegex(ValueError, 'distinct original trigger IDs'):
            cli.population(original, [{}, {}, {}], [9])
        with self.assertRaisesRegex(ValueError, 'distinct original trigger IDs'):
            cli.population(original, [{}, {}, {}], [3, 3])

    def test_excluded_window_retains_the_original_energy_and_unresolved_weight(self):
        projected_pairings = [{'index': 0, 'orders': [{'nominal_mass': .5, 'status': 'excluded_history'}]}]
        saved = {'original_trigger_id': 12, 'trigger_index': 8, 'two_strip_ordinal': 3, 'trigger_time_ns': 2000.,
                 'energy_keV': 550., 'projected_mass': 0., 'unresolved_mass': 1., 'pairings': projected_pairings}
        fitted = {'time_ns': 2000., 'window_status': 'excluded_history', 'pairings': []}
        joined = {'original_trigger_id': 12, 'archive_record_sha256': 'a'*64, 'archive_adc_sha256': 'b'*64}
        original = {'trigger_id': 12, 'trigger_time_ns': 2000., 'decision': 'candidate',
                    'card': {'energy_keV': 550., 'x_sum_keV': 550.1, 'y_sum_keV': 549.9,
                             'two_strip_pairings': {'pairings': []}}}
        with patch.object(cli.imaging, 'voltage_window', return_value=(None, 'excluded_history')):
            result = cli.analyze(saved, fitted, joined, original, {'excluded_intervals_ns': []}, {})
        self.assertEqual(result['original_measured_energy_keV'], 550.)
        self.assertEqual(result['original_unresolved_mass'], 1.)
        self.assertEqual(result['original_projected_pairings_and_orders'], projected_pairings)
        self.assertIsNone(result['alternative_fit_diagnostics'])

    def test_sampled_ties_preserve_model_identity_and_exclude_unconverged_alternatives(self):
        baseline = [{'pairing_index': 1, 'center_optimizer_success': True, 'center_global_adc_rms_codes': 10.}]
        alternatives = [{'kind': '3_corner_sparse', 'status': 'optimizer_unconverged', 'global_adc_rms_codes': 1.},
                        {'kind': '4_corner_continuum', 'status': 'scored',
                         'global_adc_rms_codes': 10. - .5*core.NEAR_TIE_ADC_CODES},
                        {'kind': '3_corner_weak_endpoint_lower', 'status': 'missing_center_template'}]
        self.assertEqual([(r['kind'], r['index']) for r in cli.near_ties(baseline, alternatives)],
                         [('saved_center_pairing', 1), ('4_corner_continuum', 1)])
        self.assertEqual(core.NEAR_TIE_ADC_CODES, joint.NEAR_TIE_RMS_INCREMENT * joint.NOISE_RMS_V / joint.digital._LSB_V)

    def test_shared_y_conserves_original_measured_energy_and_preserves_an_unqualified_candidate(self):
        card = {'x_collecting_strips': [3, 8], 'y_collecting_strips': [19], 'guard_contact_ids': [],
                'x_sum_keV': 300., 'y_sum_keV': 302., 'energy_keV': 301.}
        rows = [{'contact_id': cid, 'slow_energy_keV': e} for cid, e in ((3, 100.), (8, 200.), (19, 302.))]
        result = shared.split_energy(card, rows)
        self.assertEqual(result['shared_contact_id'], 19)
        self.assertEqual(result['cells'], [(3, 19), (8, 19)])
        self.assertEqual(sum(result['site_energies_keV']), 301.)
        self.assertAlmostEqual(result['site_energies_keV'][0] / result['site_energies_keV'][1], .5)
        unavailable = shared.split_energy(dict(card, energy_keV=None), rows)
        self.assertEqual(shared.availability(unavailable, 'captured', {}), 'unqualified_strip_energy')
        self.assertEqual(shared.availability(result, 'excluded_history', {}), 'excluded_history')

    def test_shared_x_cfd_matches_the_sum_crossing_and_keeps_distinct_strip_timings(self):
        cells = [(3, 19), (3, 25)]
        card = {'x_collecting_strips': [3], 'y_collecting_strips': [19, 25], 'guard_contact_ids': [],
                'x_sum_keV': 300., 'y_sum_keV': 300., 'energy_keV': 300.}
        collectors = [{'contact_id': cid, 'slow_energy_keV': e, 'preamp_cfd50_ns': cfd}
                      for cid, e, cfd in ((3, 300., 30.), (19, 150., 20.), (25, 150., None))]
        allocation = shared.split_energy(card, collectors)
        templates, pulses = {}, []
        for cell, rise_ns in zip(cells, (40., 120.), strict=True):
            response = np.zeros((34, len(joint.VOLTAGE_NS)))
            response[np.asarray(cell)-1] = joint.pulse._SLOW_GAIN * np.clip(joint.VOLTAGE_NS/rise_ns, 0, 1)
            templates[cell] = joint.Template(cell, (0., float(cell[1])), 4., np.tile(response, (len(joint.DEPTH_MM), 1, 1)))
            pulses.append(joint.shifted_samples(150.*response, 0.))
        all_adc = pulses[0] + pulses[1]
        fitted = shared.fit_shared(allocation, collectors, templates, all_adc)
        self.assertEqual(fitted['status'], 'scored')
        self.assertLess(fitted['global_adc_rms_codes'], 1e-5)
        timing = fitted['collector_timing']
        self.assertEqual([r['contact_id'] for r in timing], [3, 19, 25])
        self.assertEqual([r['is_shared_strip'] for r in timing], [True, False, False])
        np.testing.assert_allclose([r['modeled_cfd_ns'] for r in timing], [30., 20., 60.], atol=1e-6)
        self.assertNotAlmostEqual(timing[0]['modeled_cfd_ns'], (20.+60.)/2)
        self.assertIsNone(timing[2]['measured_minus_modeled_ns'])
        self.assertEqual(len(fitted['conditional_orders']), 2)


class IncidentHypothesisTests(unittest.TestCase):
    def test_distinguishes_resolved_escape_order_from_observed_sum_absorption(self):
        report = incident.evaluate([730., 90.], [1000., 750.])
        higher, lower = report['incident_line_hypotheses']
        self.assertEqual(report['measured_cell_sum_keV'], 820.)
        self.assertEqual(higher['escape_photon_energy_keV'], 180.)
        self.assertEqual(higher['observed_sum_minus_incident_keV'], -180.)
        forward, reverse = higher['two_resolved_scatter_escape_orders']
        self.assertEqual([s['outgoing_photon_keV'] for s in forward['scatters']], [270., 180.])
        self.assertTrue(forward['nominally_admissible'])
        self.assertFalse(reverse['nominally_admissible'])
        self.assertGreater(forward['incident_minus_minimum_keV'], 0.)
        self.assertLess(reverse['incident_minus_minimum_keV'], 0.)
        rejected = reverse['scatters'][1]
        self.assertLess(rejected['raw_cosine'], -1.)
        self.assertLess(rejected['backscatter_energy_margin_keV'], 0.)
        self.assertIsNone(rejected['scatter_angle_deg'])
        self.assertEqual(lower['observed_sum_minus_incident_keV'], 70.)
        self.assertFalse(lower['positive_escape_photon_energy'])
        self.assertIsNone(lower['two_resolved_scatter_escape_orders'][0]['scatters'][1]['raw_cosine'])
        absorbed = report['observed_sum_full_absorption_orders'][1]
        self.assertTrue(absorbed['first_scatter']['nominally_admissible'])
        self.assertEqual(absorbed['first_scatter']['incoming_photon_keV'], 820.)
        self.assertEqual(absorbed['absorbed_keV'], 730.)
        self.assertIsNone(report['unresolved_or_mixed']['direction'])

    def test_inverts_the_backscatter_bound_and_preserves_exact_line_closure(self):
        threshold = incident.minimum_incoming(1100.)
        before = incident.scatter(threshold - .001, 1100., threshold - .001 - 1100.)
        after = incident.scatter(threshold + .001, 1100., threshold + .001 - 1100.)
        self.assertFalse(before['nominally_admissible'])
        self.assertTrue(after['nominally_admissible'])
        self.assertAlmostEqual(incident.scatter(threshold, 1100., threshold - 1100.)['raw_cosine'], -1.)
        closed, = incident.evaluate([500., 150.], [650.])['incident_line_hypotheses']
        self.assertEqual(closed['observed_sum_minus_incident_keV'], 0.)
        self.assertTrue(all(not row['nominally_admissible'] for row in closed['two_resolved_scatter_escape_orders']))
        for energies in ([0.], [-1.], [float('inf')], [float('nan')], [1332., 1332.], [True]):
            with self.subTest(energies=energies), self.assertRaises(ValueError):
                incident.configuration(energies)

    def test_map_pairs_and_shared_allocations_keep_original_ambiguity(self):
        paired = [{'index': index, 'energy_compatible': index == 0, 'sites': [{'energy_keV': 90.}, {'energy_keV': 730.}]}
                  for index in (0, 1)]
        fitted = {'pairings': [dict(pair, cells=[[3, 19], [4, 20]], fit={'status': 'excluded_history'}) for pair in paired]}
        baseline = cli.baseline_scores({'pairings': paired}, fitted, {}, None)
        augmented = cli.baseline_scores({'pairings': paired}, fitted, {}, None, [1000.])
        for old, new in zip(baseline, augmented, strict=True):
            ledger = new['incident_line_diagnostics']
            self.assertEqual({k: v for k, v in new.items() if k != 'incident_line_diagnostics'}, old)
            self.assertEqual(ledger['status'], 'evaluated' if old['energy_compatible'] else 'energy_incompatible')
        shared_rows = [{'conditional_energy_allocation': {'status': 'energy_qualified', 'site_energies_keV': [90., 730.]},
                        'imaging_weight': None, 'physical_interaction_multiplicity': 'unidentified'},
                       {'conditional_energy_allocation': {'status': 'unqualified_strip_energy'}, 'imaging_weight': None}]
        cli.shared_incident_diagnostics({'triggers': shared_rows}, [1000.])
        self.assertEqual(shared_rows[0]['incident_line_diagnostics'], augmented[0]['incident_line_diagnostics'])
        invalid = shared_rows[1]['incident_line_diagnostics']
        self.assertEqual(invalid['status'], 'unqualified_strip_energy')
        self.assertIsNone(invalid['unresolved_or_mixed']['direction'])
        self.assertTrue(all(row['imaging_weight'] is None for row in shared_rows))


if __name__ == '__main__':
    unittest.main()
