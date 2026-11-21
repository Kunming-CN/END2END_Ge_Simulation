"""Check continuous feature modeling and assignment retention in the joint fit."""

import unittest
from dataclasses import replace

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

    def test_retained_fit_reports_nonlocal_transient_and_timing_failure(self):
        response = np.zeros((len(joint.DEPTH_MM), 34, len(joint.VOLTAGE_NS)))
        response[:, [2, 18]] = joint.pulse._SLOW_GAIN * np.clip(joint.VOLTAGE_NS / 80, 0, 1)
        templates = {(3, 19): joint.Template((3, 19), (0., 0.), 4., response),
                     (5, 25): joint.Template((5, 25), (8., 24.), 4., np.zeros_like(response))}
        pairing = {'sites': [{'x_contact_id': 3, 'y_contact_id': 19, 'energy_keV': 100.},
                             {'x_contact_id': 5, 'y_contact_id': 25, 'energy_keV': 100.}]}
        collectors = [{'contact_id': cid, 'slow_energy_keV': 100., 'preamp_cfd50_ns': 40.,
                       'low': None, 'high': None} for cid in (3, 19, 5, 25)]
        fit = {'parameters': [-5., 0., 0.]}
        measured = joint.shifted_samples(response[0] * 100, 0)
        measured[33, 6] -= 7 * joint.digital._LSB_V
        report = joint.evaluate_waveform_compatibility(pairing, collectors, templates, fit, [3,19,5,25],
                                                       local_adc_volts=measured)
        self.assertEqual(report['contact_ids'], list(range(1, 35)))
        self.assertEqual(report['fitted_contact_ids'], [3,19,5,25])
        self.assertAlmostEqual(report['adc_peak_codes'][33], -7.)
        self.assertAlmostEqual(report['adc_peak_time_ns'][33], 40.)
        self.assertEqual(report['adc_rms_codes'][2], 0.)
        self.assertEqual(report['parameter_boundaries'], {'z1_mm': 'lower', 'z2_mm': None, 'onset_ns': None})
        self.assertEqual([r['modeled_crossing_valid'] for r in report['collector_timing']], [True, True, False, False])
        self.assertIsNone(report['collector_timing'][-1]['modeled_cfd_ns'])

    def test_all_contact_objective_keeps_local_fit_and_reports_near_ties(self):
        cells = ((3, 19), (8, 25))
        templates = {}
        collectors = []
        sites = []
        observed = np.zeros((34, len(joint.SAMPLE_NS)))
        for cell in cells:
            response = np.zeros((len(joint.DEPTH_MM), 34, len(joint.VOLTAGE_NS)))
            for cid in cell:
                response[:, cid-1] = joint.pulse._SLOW_GAIN * np.clip(joint.VOLTAGE_NS / 80, 0, 1)
                collectors.append({'contact_id': cid, 'slow_energy_keV': 100., 'preamp_cfd50_ns': 40.,
                                   'low': {'contact_id': cid-1, 'fast_keV_equiv': 0., 'flags': []}, 'high': None})
            templates[cell] = joint.Template(cell, (0., 0.), 4., response)
            sites.append({'x_contact_id': cell[0], 'y_contact_id': cell[1], 'energy_keV': 100.})
            observed += joint.shifted_samples(response[0] * 100, 0)
        observed[33, 6] -= 7 * joint.digital._LSB_V
        pairing = {'energy_compatible': True, 'sites': sites}
        scales = {'fast': 1., 'centered_cfd': 1.}
        original = joint.fit_pairing(pairing, collectors, templates, scales, local_adc_volts=observed)
        result = joint.fit_pairing(pairing, collectors, templates, scales, local_adc_volts=observed,
                                   compatibility=True, include_all_channels=True)
        local = result['fits']['waveform']['center']
        full = result['fits']['waveform_all']['center']
        self.assertEqual({k: local[k] for k in original['fits']['waveform']['center']},
                         original['fits']['waveform']['center'])
        self.assertNotIn(34, local['compatibility']['fitted_contact_ids'])
        self.assertEqual(full['compatibility']['fitted_contact_ids'], list(range(1, 35)))
        self.assertAlmostEqual(full['compatibility']['adc_peak_codes'][33], -7)
        self.assertTrue(local['sampled_alternates'])
        self.assertGreater(max(local['sampled_near_tie_spread'][:2]), 0)

        # Give just the second site an existing grid and give its x and y
        # isolated channel responses. All-contact fitting can recover both.
        correction = np.zeros((3, 3, 3, 34, len(joint.VOLTAGE_NS)))
        ramp = joint.pulse._SLOW_GAIN * np.clip(joint.VOLTAGE_NS / 80, 0, 1)
        for k, offset in enumerate(joint.LATERAL_FRACTION):
            correction[k, :, :, 15] = offset * ramp
            correction[:, k, :, 33] = offset * ramp
        templates[cells[1]] = replace(templates[cells[1]], lateral_correction_v_per_keV=correction)
        observed[33, 6] += 7 * joint.digital._LSB_V
        observed[[15, 33]] = joint.shifted_samples(np.array([.16, -.18])[:, None] * ramp * 100, 0)
        partial_result = joint.fit_pairing(pairing, collectors, templates, scales, local_adc_volts=observed,
                                          compatibility=True, include_all_channels=True, include_partial_lateral=True)
        partial = partial_result['fits']['waveform_all']['partial_lateral']
        self.assertEqual(partial['site_lateral_support'], [False, True])
        self.assertEqual(partial['positions_mm'][0][:2], [0., 0.])
        np.testing.assert_allclose(partial['positions_mm'][1][:2], [4 * .16, 4 * -.18], atol=1e-6)


if __name__ == '__main__':
    unittest.main()
