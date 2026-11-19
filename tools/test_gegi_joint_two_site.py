"""Check continuous feature modeling and assignment retention in the joint fit."""

import unittest

import numpy as np

import gegi_joint_two_site as joint


class JointTwoSiteTests(unittest.TestCase):
    def test_model_features_match_trigger_gate_on_same_signal(self):
        digital = joint.digital
        energy = np.array([100.,200.])
        volts = joint.pulse._SLOW_GAIN * energy[:,None] * np.clip(joint.SAMPLE_NS/80,0,1)
        fast, cfd, available = joint.modeled_features(volts,[0,1],energy)
        self.assertTrue(available.all())
        np.testing.assert_allclose(cfd,[40.,40.],atol=1e-10)
        padded = np.pad(volts,((0,0),(digital._TRIGGER_INDEX-joint.TRIGGER_INDEX,0)))
        expected_fast = [digital._fast_area(digital._filters(row)[2])/joint.pulse._FAST_GAIN for row in padded]
        np.testing.assert_allclose(fast,expected_fast,atol=1e-10)

    def test_quiet_tail_changes_only_the_matching_free_decay(self):
        signal = np.zeros((2,len(joint.SAMPLE_NS)))
        signal[:,joint.TRIGGER_INDEX+1:] = [[.011],[-.005]]
        with_tail = signal + np.array([[.002],[-.005]])*joint.TAIL_DECAY
        np.testing.assert_allclose(joint.remove_quiet_tail(with_tail),signal,atol=1e-15)

    def test_neighbors_are_deduplicated_and_signed(self):
        def channel(cid, reading):
            return {'contact_id':cid,'slow_energy_keV':100.,'preamp_cfd50_ns':10.,'low':reading,'high':None}
        neighbor = {'contact_id':5,'fast_keV_equiv':-2.,'flags':[]}
        _,_,fast = joint.feature_measurement([channel(6,neighbor),channel(4,neighbor)])
        self.assertEqual(fast,{5:-2.})
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            joint.feature_measurement([channel(6,neighbor),channel(4,dict(neighbor,fast_keV_equiv=2.))])

    def test_unavailable_pixel_keeps_the_measured_hypothesis_unfitted(self):
        pair = {'energy_compatible':True,'sites':[{'x_contact_id':3,'y_contact_id':19,'energy_keV':100.},
                                                 {'x_contact_id':5,'y_contact_id':25,'energy_keV':100.}]}
        self.assertEqual(joint.fit_pairing(pair,[],{},{}),{'status':'no_center_template_for_pixel'})
        self.assertEqual(joint.fit_pairing(dict(pair,energy_compatible=False),[],{},{}),{'status':'energy_incompatible'})


if __name__ == '__main__':
    unittest.main()
