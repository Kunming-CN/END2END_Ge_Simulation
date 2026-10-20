import copy
import unittest
import numpy as np
import gegi_face_sum_readout as F


def recipe():
    return {'ionisation_energy_eV': 2.95, 'readout_config': {'calibration_energy_keV': 500.,
        'peak_policy': 'signed_input_positive_peak', 'feedback_tau_us': 50., 'pole_zero_tau_us': 50.,
        'shaping_tau_us': .5, 'tail_shaping_constants': 20., 'gain': 20., 'feedback_capacitance_pF': .6,
        'adc_bits': 14, 'adc_full_scale_V': 10., 'threshold_V': .001},
        'electronics_calibration': {'energy_keV': 500., 'time_step_ns': 1.,
            'volts_per_keV': .0004900136238587843, 'adc_lsb_V': .0006103515625}}


def observed(length=202):
    return {'status': 'completed', 'channels': [{'contact_id': cid, 'wiring_factor': 1 if cid <= 17 else -1,
                'accepted': False, 'collection_candidate': False} for cid in range(1, 35)],
            'native': {cid: {'time_ns': list(range(length)), 'signed_induced_keV': [0.]*length} for cid in range(1, 35)}}


class FaceSumTests(unittest.TestCase):
    def test_guards_included_without_collection_or_acceptance_selection(self):
        o = observed(); o['native'][17]['signed_induced_keV'][1:] = [10.]*201
        o['native'][34]['signed_induced_keV'][1:] = [-10.]*201
        r = F.face_sum_observables(o, recipe())
        self.assertTrue(r['accepted'])
        self.assertEqual(r['native_terminal_mean_keV'], 10.)
        self.assertEqual(r['face_difference_keV'], 0.)
        self.assertAlmostEqual(r['faces']['X']['analog_energy_keV'], 10., places=4)

    def test_signed_transients_cancel_before_peak_extraction(self):
        o = observed()
        o['native'][1]['signed_induced_keV'][1:101] = [100.]*100
        o['native'][1]['signed_induced_keV'][101:] = [10.]*101
        o['native'][2]['signed_induced_keV'][1:101] = [-90.]*100
        o['native'][18]['signed_induced_keV'][1:] = [-10.]*201
        result = F.face_sum_observables(o, recipe())
        individual = sum(F.C.matched_response(o['native'][cid]['time_ns'],
            o['native'][cid]['signed_induced_keV'], recipe())['analog_energy_keV'] for cid in (1, 2))
        self.assertAlmostEqual(result['faces']['X']['analog_energy_keV'], 10., places=4)
        self.assertGreater(individual, result['faces']['X']['analog_energy_keV']+1.)

    def test_unknown_native_keeps_null_instead_of_zero_face_waveforms(self):
        o = observed(); o.update(status='native_failed', native=None, channels=None)
        r = F.face_sum_observables(o, recipe())
        self.assertIsNone(r['faces']); self.assertIsNone(r['energy_keV'])
        self.assertFalse(r['accepted'])

    def test_missing_channel_and_wrong_wiring_raise(self):
        o = observed(); del o['native'][34]
        with self.assertRaisesRegex(ValueError, 'all34'):
            F.face_sum_observables(o, recipe())
        o = observed(); o['channels'][20]['wiring_factor'] = 1
        with self.assertRaisesRegex(ValueError, 'wiring'):
            F.face_sum_observables(o, recipe())

    def test_truth_labels_and_original_channel_flags_do_not_affect_scheme(self):
        o = observed(); o['native'][17]['signed_induced_keV'][1:] = [10.]*201
        o['native'][34]['signed_induced_keV'][1:] = [-10.]*201
        before = F.face_sum_observables(o, recipe())
        changed = copy.deepcopy(o); changed.update(truth_edep_keV=99999, source_position=[100, 200, 300])
        for c in changed['channels']:
            c.update(accepted=True, collection_candidate=True, reconstructed_energy_keV=12345)
        self.assertEqual(before, F.face_sum_observables(changed, recipe()))


if __name__ == '__main__':
    unittest.main()
