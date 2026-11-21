import math
import unittest

import numpy as np
from scipy.integrate import quad

import gegi_first_compton_arrival as arrival
from gegi_photon_continuation import PhotonRates


class FirstComptonArrivalTests(unittest.TestCase):
    def setUp(self):
        self.cube = (np.vstack((np.eye(3),-np.eye(3))), np.full(6,10.))
        self.rates = PhotonRates(.1,.02,.06)

    def test_external_ray_preserves_ge_depth_and_source_inverse_square(self):
        one = arrival.first_compton_arrival(self.cube,[-30.,0.,0.],[0.,0.,0.],self.rates)
        two = arrival.first_compton_arrival(self.cube,[-60.,0.,0.],[0.,0.,0.],self.rates)
        self.assertEqual(one['source_region'],'outside_ge')
        self.assertEqual(one['incoming_direction'],[1.,0.,0.])
        self.assertEqual(one['ge_path_start_mm'],[-10.,0.,0.])
        self.assertEqual(one['ge_path_to_first_mm'],10.)
        self.assertEqual(two['ge_path_to_first_mm'],10.)
        self.assertAlmostEqual(one['ge_no_interaction_survival'],math.exp(-1.))
        first = one['log_first_compton_per_emitted_photon_mm3']
        self.assertAlmostEqual(math.exp(first),.06*math.exp(-1.)/(4*math.pi*30**2))
        self.assertAlmostEqual(first-two['log_first_compton_per_emitted_photon_mm3'],math.log(4.))

    def test_interior_and_boundary_sources_use_the_emission_point(self):
        for source,region,length in (([-3.,0.,0.],'inside_ge',8.),([-10.,0.,0.],'ge_boundary',15.)):
            with self.subTest(source=source):
                nominal = arrival.first_compton_arrival(self.cube,source,[5.,0.,0.],self.rates)
                self.assertEqual(nominal['source_region'],region)
                self.assertEqual(nominal['ge_path_start_mm'],source)
                self.assertEqual(nominal['ge_path_to_first_mm'],length)
                self.assertAlmostEqual(nominal['ge_optical_depth'],.1*length)

    def test_oblique_ray_crosses_the_correct_convex_face(self):
        oblique = arrival.incoming_ge_path(self.cube,[-30.,-40.,0.],[0.,0.,0.])
        self.assertEqual(oblique['source_to_vertex_mm'],50.)
        np.testing.assert_allclose(oblique['incoming_direction'],[.6,.8,0.])
        np.testing.assert_allclose(oblique['ge_path_start_mm'],[-7.5,-10.,0.])
        self.assertAlmostEqual(oblique['ge_path_to_first_mm'],12.5)
        self.assertAlmostEqual(oblique['ge_path_to_first_mm'],
                               arrival.forward_clipped_length(self.cube,[-30.,-40.,0.],[0.,0.,0.]))

    def test_slab_ray_integral_has_competing_compton_fraction(self):
        def along_ray(depth):
            result = arrival.first_compton_arrival(self.cube,[-30.,0.,0.],[-10.+depth,0.,0.],self.rates)
            d = result['source_to_vertex_mm']
            return math.exp(result['log_first_compton_per_emitted_photon_mm3'])*4*math.pi*d*d

        mass, _ = quad(along_ray,0.,20.)
        self.assertAlmostEqual(mass,.06/.1*(1.-math.exp(-2.)),places=13)

    def test_unavailable_geometries_and_coefficients_remain_explicit(self):
        at_vertex = arrival.first_compton_arrival(self.cube,[0.,0.,0.],[0.,0.,0.],self.rates)
        outside = arrival.first_compton_arrival(self.cube,[0.,0.,0.],[15.,0.,0.],self.rates)
        missing_rate = arrival.first_compton_arrival(self.cube,[0.,0.,0.],[5.,0.,0.],None)
        zero_compton = arrival.first_compton_arrival(self.cube,[0.,0.,0.],[5.,0.,0.],PhotonRates(.1,.02,0.))
        for case,status in ((at_vertex,'source_at_first_vertex'),(outside,'first_vertex_outside_ge'),
                           (missing_rate,'incident_coefficients_unavailable'),(zero_compton,'zero_first_compton_rate')):
            self.assertEqual(case['density_status'],status)
            self.assertIsNone(case['log_first_compton_per_emitted_photon_mm3'])
        self.assertEqual(at_vertex['source_region'],'inside_ge')
        self.assertIsNone(at_vertex['incoming_direction'])
        self.assertEqual(missing_rate['ge_path_to_first_mm'],5.)


if __name__=='__main__':
    unittest.main()
