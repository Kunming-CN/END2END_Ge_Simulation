import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import gegi_candidate_trial_response as trial
import gegi_photon_continuation as photon
import scenario_workflow as W


class CandidateTrialResponseTests(unittest.TestCase):
    def test_trial_grid_covers_declared_radii_and_full_azimuth(self):
        radii, units, points = trial.trials(20., 80., 3, 12)
        np.testing.assert_allclose(radii, [20., 40., 80.])
        np.testing.assert_allclose(np.linalg.norm(units, axis=1), 1.)
        np.testing.assert_allclose(np.linalg.norm(points, axis=-1), radii[:, None]*np.ones(12))
        self.assertEqual(points.shape, (3, 12, 3))

    def test_positive_rate_interpolation_retains_anchors_and_bounds(self):
        lo = photon.PhotonRates(.16, .04, .08)
        hi = photon.PhotonRates(.04, .01, .02)
        rates_at, total = trial.rate_functions({100.:lo, 400.:hi})
        self.assertIs(rates_at(100.), lo)
        self.assertAlmostEqual(total(200.), .08)
        self.assertAlmostEqual(rates_at(200.).photoelectric_per_mm, .02)
        self.assertAlmostEqual(rates_at(200.).compton_per_mm, .04)
        with self.assertRaisesRegex(ValueError, 'outside'):
            rates_at(50.)
        queries = trial.required_knots(90., 350., {100.:lo, 400.:hi}, .2)
        self.assertIn(90., queries)
        self.assertNotIn(350., queries)
        e = sorted([100., 400., *queries])
        self.assertLessEqual(max(math.log(b/a) for a,b in zip(e[:-1],e[1:],strict=True)), .2)

    def test_fixed_measured_first_failure_does_not_gate_trial_response(self):
        compatible = dict(pair_index=0, measured_site_energies_keV=[500., 50.],
            fitted_vertices_mm=[[0., 0., 0.], [2., 0., 0.]], orders=[dict(site_index_order=[0, 1],
                lines=[dict(incident_line_keV=662., status='fixed_first_scatter_inadmissible')])])
        incompatible = dict(pair_index=1, measured_site_energies_keV=None, fitted_vertices_mm=None,
            orders=[dict(site_index_order=[0, 1], lines=[dict(incident_line_keV=662., status='original_strip_pairing_incompatible')])])
        measured = dict(input_sha256={}, scoped_cohorts={}, measured_triggers=[dict(original_trigger_id=7,
                        original_projected_mass=1., physical_topology_status='unidentified_by_two_site_response',
                        pairs=[compatible, incompatible])])
        table = {e:photon.PhotonRates(.08,.01,.04) for e in (100., 662.)}
        crystal = (np.vstack((np.eye(3), -np.eye(3))), np.full(6, 10.))
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            mf, pf = folder/'measured.json', folder/'plan.json'
            mf.write_text(json.dumps(measured), encoding='utf-8')
            pf.write_text(json.dumps(dict(kind=trial.PLAN_KIND, measured_plan_sha256=W.sha(mf), rate_basis={},
                sigma_first_keV=200., sigma_second_keV=20., selected_trials=[
                    dict(source_mm=[-4., 0., 0.], inside_ge=True), dict(source_mm=[0., 0., 0.], inside_ge=True)])), encoding='utf-8')
            with patch.object(trial,'retained_rates',return_value=(table,.1,{})), patch.object(
                    photon,'ge_halfspaces_from_gdml',return_value=crystal):
                result = trial.evaluate(pf, mf, folder, None, azimuth_samples=8, energy_order=16)
        self.assertEqual(result['measured_triggers'], measured['measured_triggers'])
        self.assertEqual(result['trial_state_counts'], {'conditional_factors_computed':1, 'trial_source_at_first_vertex':1,
                                                        'original_strip_pairing_incompatible':2})
        response = result['branches'][0]['trial_results'][0]['response']
        self.assertEqual(response['intermediate_keV'], 662.)
        self.assertEqual(response['expected_first_deposit_keV'], 0.)
        self.assertGreater(response['first_measurement_density_per_keV'], 0.)
        self.assertGreater(response['escape_per_mm3_observed_keV2'], 0.)


if __name__ == '__main__':
    unittest.main()
