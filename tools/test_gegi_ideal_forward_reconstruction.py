from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

import gegi_ideal_forward_fast_bank as fast
import gegi_ideal_forward_reconstruction as forward
import gegi_ideal_forward_score as score


class IdealForwardReconstructionTests(unittest.TestCase):
    def test_first_accepted_counts_preserve_pending_observations(self):
        events = [dict(attempt_id=i) for i in (29,104,251)]
        original = dict(kind=forward.OBSERVATIONS_KIND,cohorts=[dict(cohort_id='cohort-1',events=events)])
        scope = forward.selected_observations(original,2)['cohort-1']
        self.assertEqual([e['attempt_id'] for e in scope['first_accepted']],[29,104])
        self.assertEqual(scope['all_accepted_count'],3)
        self.assertEqual(scope['retained_for_expansion_count'],1)
        self.assertEqual(len(events),3)

    def test_two_label_orders_produce_one_event_and_unavailable_mass_remains(self):
        obs = dict(incident_keV=1173.228,sigma_site_keV=[2.,2.])
        cohorts = dict(case=dict(first_accepted=[dict(attempt_id=29),dict(attempt_id=104)],
                                 all_accepted_count=100,retained_for_expansion_count=98))
        branches = [dict(cohort_id='case',attempt_id=i,site_index_order=o) for i in (29,104) for o in forward.ORDERS]
        points = np.array([[0.,0.,20.],[20.,0.,0.]])
        probabilities = [dict(known_topology_probability=.05)]
        seeds = [dict(seed=s,estimates=[dict(contained_photoelectric=.02,known_compton_and_escape=.03)]) for s in (3100,3101)]
        cases = [dict(grid_index=i,source_mm=xyz.tolist(),radial_index=0,direction_index=i,source_region='outside_ge',
                      lines=[dict(incident_keV=1173.228,estimates=probabilities,seed_results=seeds,
                                  uninitialized_exit_mass_analytic_upper_bound=0.)]) for i,xyz in enumerate(points)]
        norm = dict(trial_scope='full_declared_grid',normalization_cases=cases)
        a = np.log([[.02,.03],[.01,.01],[.04,.02],[.01,.01]])
        e = np.log([[.04,.02],[.03,.04],[.02,.04],[.01,.01]])
        e[3,1] = np.nan
        before = score.compute_blind(obs,cohorts,points,branches,dict(absorption=a,escape=e),norm)
        after = score.compute_blind(obs,cohorts,points,branches,dict(absorption=a[[1,0,3,2]],escape=e[[1,0,3,2]]),norm)
        row = before['cohorts']['case']
        self.assertEqual(row['scored_attempt_ids'],[29])
        self.assertEqual(row['unknown_attempt_ids'],[104])
        self.assertEqual(row['selected_events'][1]['minimum_computed_order_mass'],.5)
        self.assertEqual(row['profile'],after['cohorts']['case']['profile'])
        np.testing.assert_allclose(row['profile']['grid_scores']['normalized_known_mass_log_score'],
                                   [0.,0.],atol=1e-15)

    def test_invalid_blind_digest_blocks_truth_access(self):
        targets = SimpleNamespace(blind=Path('blind.json'),truth=Path('truth.json'),output=Path('unused-score.json'))
        result = dict(kind=score.BLIND_KIND,measured_analysis={},blind_fit_sha256='changed')
        with patch.object(score.W,'read',return_value=result) as read:
            with self.assertRaisesRegex(score.W.ControlError,'before opening truth'):
                score.truth_score(targets)
        read.assert_called_once_with(targets.blind)

    def test_fast_reference_retains_both_numerical_orders(self):
        model = dict(first_fitted_mm=[0.,0.,0.],second_fitted_mm=[1.,0.,0.],sigma_second_keV=2.,
                     measured_second_site_keV=100.)
        def observed(*a,energy_order,**kw):
            return dict(log_escape_per_mm_observed_keV=-10.+1./energy_order,escape_per_mm_observed_keV=.1,
                        escape_density_status='positive_raw_density',spectrum_evaluations=energy_order)
        with patch.object(fast.gaussian,'observed_escape',side_effect=observed) as mocked:
            eval_one = fast.checked_evaluator(model,None,lambda _:None,None,256)
            result = eval_one(300.,32)
        self.assertEqual([c.kwargs['energy_order'] for c in mocked.call_args_list],[16,32])
        self.assertAlmostEqual(result['log_quadrature_difference'],1./32)
        self.assertEqual(result['spectrum_evaluations'],48)


if __name__=='__main__':
    unittest.main()
