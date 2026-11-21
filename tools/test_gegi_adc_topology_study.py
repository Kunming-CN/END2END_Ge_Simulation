"""Check reconciled energy conservation and all-contact ADC topology fitting."""

import unittest

import numpy as np

import gegi_adc_topology_study as topology
import gegi_joint_two_site as joint


class ADCTopologyTests(unittest.TestCase):
    def test_rank_deficient_family_preserves_measured_marginals(self):
        collectors = [{'contact_id': cid, 'slow_energy_keV': energy}
                      for cid, energy in ((3, 100.), (8, 200.), (19, 131.), (25, 170.))]
        cells, flows, ledger, measured, tolerances, marginals = topology.matching_marginals(collectors)
        self.assertEqual(cells, ((3, 19), (3, 25), (8, 19), (8, 25)))
        self.assertEqual(ledger['rank_deficient_supports'], 1)
        self.assertFalse(ledger['continuous_NxN_allocations_exhausted'])
        self.assertTrue(any(len(flow) == 3 for flow in flows))
        self.assertTrue(np.all(np.abs(marginals - measured) <= tolerances))
        bounds, allocate = topology.energy_family(marginals)
        for value in np.linspace(*bounds, 9):
            matrix = allocate(value).reshape(2, 2)
            self.assertTrue(np.all(matrix >= 0.))
            np.testing.assert_allclose(matrix.sum(axis=1), marginals[:2], rtol=0, atol=1e-12)
            np.testing.assert_allclose(matrix.sum(axis=0), marginals[2:], rtol=0, atol=1e-12)

    def test_nonnegative_continuum_can_resolve_free_corner_on_synthetic_windows(self):
        cells = ((3, 19), (3, 25), (8, 19), (8, 25))
        voltages = []
        templates = {}
        for i, cell in enumerate(cells):
            response = np.zeros((34, len(joint.VOLTAGE_NS)))
            response[i] = joint.pulse._SLOW_GAIN * np.clip(joint.VOLTAGE_NS / 80, 0, 1)
            templates[cell] = joint.Template(cell, (0., 0.), 4., np.tile(response, (len(joint.DEPTH_MM), 1, 1)))
            voltages.append(response)
        bounds, allocate = topology.energy_family([100., 200., 130., 170.])
        energies = allocate(60.)
        analog = sum(e * v for e, v in zip(energies, voltages, strict=True))
        adc = joint.shifted_samples(analog, 0.)
        fit = topology.fit_flow(cells, templates, adc, family=(bounds, allocate))
        self.assertEqual(fit['status'], 'scored')
        self.assertFalse(fit['fit']['at_energy_bound'])
        self.assertLess(fit['global_adc_rms_codes'], 1e-5)
        np.testing.assert_allclose(fit['fit']['energies_keV'], energies, rtol=0., atol=1e-7)

    def test_same_trial_summary_preserves_original_two_site_and_extended_rms_units(self):
        row = {'geometry': 'cross', 'status': 'pairings_measured',
               'original_center_waveform_alternatives': [{'all_adc_rms_codes': 12.}],
               'allocations': {'fits': [{'status': 'scored', 'global_adc_rms_codes': 10., 'kind': '4_corner_continuum',
                                         'fit': {'at_energy_bound': True}, 'truth_score': {'exact_ge_5_keV_cell_match': False}}]}}
        result = topology.summary([row])['cross']
        self.assertEqual(result['improvement_by_trial_codes'], [2.])
        self.assertEqual(result['four_corner_optimizer_at_energy_boundary'], 1)
        self.assertEqual(result['four_corner_exact_ge5kev_cell_matches'], 0)


if __name__ == '__main__':
    unittest.main()
