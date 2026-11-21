import math
import unittest

import numpy as np
from scipy.integrate import quad

import gegi_ideal_two_interaction_mass as mass
import gegi_trial_joint_photon_response as joint
from gegi_photon_continuation import exit_distance_mm


class JointPhotonMassTests(unittest.TestCase):
    def setUp(self):
        self.cube = np.vstack((np.eye(3),-np.eye(3))), np.full(6,10.)

    def test_joint_logs_multiply_units_without_filling_unavailable_states(self):
        first = np.array([math.log(.1), math.log(.2),np.nan,-1000.])
        second = np.array([math.log(.01),np.nan,math.log(.01),-900.])
        result = joint.join_density(first,second)
        self.assertAlmostEqual(math.exp(result[0]),.001)
        self.assertTrue(np.isnan(result[1:3]).all())
        self.assertEqual(result[-1],-1900.)

    def test_ray_intersection_matches_box_and_existing_internal_exit(self):
        starts, lengths = mass.ray_intervals(self.cube,np.array([-30.,0.,0.]),np.array([[1.,0.,0.],[0.,1.,0.],[-1.,0.,0.]]))
        np.testing.assert_array_equal(starts,[20.,0.,0.])
        np.testing.assert_array_equal(lengths,[20.,0.,0.])
        point = np.array([1.,2.,3.])
        d = np.array([[.6,.8,0.],[-.6,-.8,0.],[0.,0.,1.]])
        _, lengths = mass.ray_intervals(self.cube,point,d)
        np.testing.assert_allclose(lengths,exit_distance_mm(self.cube,point,d),rtol=0,atol=1e-13)

    def test_two_competing_interactions_integrate_to_slab_probability(self):
        total, scatter, photo, length = .1,.06,.02,20.
        def integrand(u):
            first, depth = mass.competing_ray(total,scatter,length,u)
            second, _ = mass.competing_ray(total,photo,length-depth,.5)
            return first*second

        actual, _ = quad(integrand,0.,1.)
        expected = scatter*photo/total**2 * (1-(1+total*length)*math.exp(-total*length))
        self.assertAlmostEqual(actual,expected,places=13)

    def test_emission_cone_geometry_and_exact_angle_convention(self):
        u = np.array([[0.,0.]+[.5]*6,[.5,.5]+[.5]*6])
        source = np.array([0.,0.,10000.])
        rays,fraction = mass.incoming_rays(self.cube,source,u)
        expected = (3*100/10000**2)/(2*(1+math.sqrt(1-3*100/10000**2)))
        self.assertAlmostEqual(fraction,expected,places=14)
        np.testing.assert_allclose(rays[0],[0.,0.,-1.],atol=1e-15)
        np.testing.assert_allclose(np.linalg.norm(rays,axis=1),1.,atol=1e-15)
        self.assertAlmostEqual(-rays[1,2],1-fraction)

    def test_material_gap_remains_bounded_even_though_it_may_be_unsampled(self):
        energy = 661.657
        minimum = mass.outgoing_energy(mass.outgoing_energy(energy,2.),2.)
        self.assertEqual(mass.missing_exit_mass_bound(energy,minimum-.01,.5,.8),0.)
        bound = mass.missing_exit_mass_bound(energy,minimum+.01,.5,.8)
        self.assertGreater(bound,0.)
        self.assertLess(bound,1e-4)


if __name__=='__main__':
    unittest.main()
