"""Checks of posterior bookkeeping and truth-blind diagnostic attribution."""
import copy
import unittest

import numpy as np
import gegi_joint_imaging as J
import gegi_peak_diagnostic as D


class PeakDiagnosticTests(unittest.TestCase):
    def fixture(self):
        raw = {'vertex_mm': [0., 0., 0.], 'axis': [1., 0., 0.],
               'site_separation_mm': 20., 'theta_rad': 1., 'prior_weight': .2,
               'hypothesis_index': 0, 'order': [0, 1]}
        alternative = {**raw, 'axis': [-1., 0., 0.], 'prior_weight': .3,
                       'order': [1, 0]}
        records = [{'campaign_initial_id': 8, 'pulse_group_id': 0, 'energy_keV': 1332.,
                    'candidates': [raw, alternative]},
                   {'campaign_initial_id': 9, 'pulse_group_id': 1, 'energy_keV': 1333.,
                    'candidates': [dict(raw, prior_weight=1.)]}]
        settings = J.ResponseSettings()
        events = J.prepare_events(records, settings)
        _, points = J.plane_grid(40., 4., 40.)
        response = J.response_matrix(events, points, settings)
        fit = J.fit_conditional_mixture(response, iterations=20)
        refs = [[-18., 2., 40.], [18., 2., 40.]]
        return records, events, response, points, fit, refs, settings

    def test_independent_responsibility_and_unresolved_bookkeeping(self):
        args = self.fixture()
        rows, aggregate, checks = D.attribute_groups(*args)
        records, events, response, points, fit, refs, settings = args
        for i, row in enumerate(rows):
            denominator = sum(float(response[i, j])*float(m) for j, m in enumerate(fit['source_mass'])) + fit['background_fraction']/np.pi
            candidate_sum = sum(c['whole_map_candidate_responsibility'] for c in row['candidates'])
            self.assertAlmostEqual(candidate_sum+row['fitted_unresolved_source_responsibility']+row['fitted_background_responsibility'], 1.)
            for k, peak in enumerate(refs):
                j = next(j for j, p in enumerate(points) if list(p) == peak)
                self.assertAlmostEqual(row['peaks'][k]['peak_pixel_responsibility'], fit['source_mass'][j]*response[i, j]/denominator)
                conditional = sum(c['peak_conditional_candidate_probability'][k] for c in row['candidates'])
                self.assertAlmostEqual(conditional+row['peaks'][k]['unresolved_conditional_probability'], 1.)
        self.assertEqual(rows[0]['unresolved_prior_mass'], .5)
        self.assertLess(checks['maximum_row_responsibility_closure_error'], 1e-12)
        for k in range(2):
            self.assertAlmostEqual(sum(r['peaks'][k]['backprojection_share'] for r in rows), 1.)

    def test_truth_and_acquisition_labels_do_not_change_attribution(self):
        args = list(self.fixture())
        expected = D.attribute_groups(*args)
        changed = copy.deepcopy(args[0])
        for r in changed:
            r.update(source_group='changed', true_source_mm=[999., 999., 999.], truth={'order': [3, 2, 1]})
            for c in r['candidates']:
                c['truth_selected'] = True
        args[0] = changed
        args[1] = J.prepare_events(changed, args[-1])
        self.assertEqual(expected, D.attribute_groups(*args))

    def test_mode_tracking_does_not_promote_nearby_shoulders_to_peaks(self):
        refs = [[38., -2., 40.], [46., 18., 40.]]
        actual = D.peak_tracking([{'position_mm': refs[0]}], refs)
        self.assertTrue(actual[0]['displayed_peak_within_radius'])
        self.assertFalse(actual[1]['displayed_peak_within_radius'])
        self.assertAlmostEqual(actual[1]['nearest_displayed_peak_distance_mm'], np.hypot(8., 20.))


if __name__ == '__main__':
    unittest.main()
