import math
import unittest

import numpy as np

import gegi_normalized_source_diagnostic as analysis


class NormalizedSourceDiagnosticTests(unittest.TestCase):
    def test_two_topologies_and_order_weights_form_one_trigger_with_explicit_missing_mass(self):
        absorption = np.log([[.1,.1],[.2,.2]])
        escape = np.log([[.03,.03],[.05,.05]])
        escape[1,1] = np.nan
        density,mass = analysis.event_mixture([.5,.5],absorption,escape)
        self.assertAlmostEqual(math.exp(density[0]),.5*(.1+.03+.2+.05))
        self.assertEqual(mass.tolist(),[1.,.5])
        self.assertTrue(np.isnan(density[1]))

    def test_normalizer_is_applied_once_per_trigger_and_views_preserve_all_scores(self):
        def point(index, xyz, radial, region, normalizer, seed):
            estimate = lambda p:dict(known_topology_probability=p)
            seeds = [dict(seed=i,estimates=[dict(contained_photoelectric=x,known_compton_and_escape=0.)])
                     for i,x in zip((3100,3101),seed,strict=True)]
            return dict(grid_index=index,source_mm=xyz,radial_index=radial,direction_index=0,source_region=region,
                        lines=[dict(incident_keV=661.657,estimates=[estimate(normalizer)]*2, seed_results=seeds,
                            uninitialized_exit_mass_analytic_upper_bound=.01)])

        cases = [point(0,[0.,0.,20.],0,'inside_ge',.9,[.9,.9]),
                 point(2,[0.,0.,21.],1,'outside_ge',.5,[.8,.2]),
                 point(4,[0.,0.,100.],2,'outside_ge',.6,[.2,1.])]
        raw = np.array([4.,3.,3.5])
        result = analysis.compare_scores(cases,661.657,raw,2)
        expected = raw-2*np.log([.9,.5,.6])
        np.testing.assert_allclose(result['grid_scores']['normalized_known_mass_log_score'],expected)
        self.assertEqual(result['grid_scores']['grid_indices'],[0,2,4])
        self.assertEqual(result['highest_raw_grid_index'],0)
        self.assertEqual(result['seed_highest_grid_indices'],[4,2])
        external = result['external_geometric_view']
        self.assertEqual([p['grid_index'] for p in external['radial_profile']],[2,4])
        self.assertEqual(result['radial_profile'][0]['source_region'],'inside_ge')


if __name__=='__main__':
    unittest.main()
