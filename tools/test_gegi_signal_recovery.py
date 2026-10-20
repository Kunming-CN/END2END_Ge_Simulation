"""Signal-use contracts: no discarded guards, invented splits or altered gain."""
import copy
import unittest
import gegi_signal_recovery as U


def observed(ids=(4, 21), energies=(100., 100.)):
    channels = []
    for cid in range(1, 35):
        energy = energies[ids.index(cid)] if cid in ids else 0.
        wiring = 1 if cid <= 17 else -1
        channels.append({'contact_id': cid, 'wiring_factor': wiring,
            'accepted': cid in ids, 'collection_candidate': cid in ids,
            'final_induced_keV': energy*wiring,
            'reconstructed_energy_keV': energy if cid in ids else None})
    return {'event_id': 123, 'pulse_group_id': 2, 'status': 'completed', 'channels': channels}


class SignalUseTests(unittest.TestCase):
    def test_guard_energy_uses_fixed_gain_and_opposite_face_average(self):
        value = U.classify_observables(observed((4, 17, 21, 34), (80, 20, 70, 30)))
        self.assertEqual(value['spectroscopy']['energy_keV'], 100)
        self.assertEqual(value['guard']['collecting_ids'], [17, 34])
        self.assertEqual(value['category'], 'spectroscopy_only')
        self.assertFalse(value['supported_imaging'])

    def test_guard_transient_does_not_add_energy(self):
        data = observed()
        data['channels'][16].update(accepted=True, reconstructed_energy_keV=17.)
        reco = {'signed_signal_diagnostics': {'nonzero_channels': [
            {'contact_id': 17, 'minimum_wired_keV': -20, 'maximum_wired_keV': 30}]}}
        value = U.classify_observables(data, reco)
        self.assertEqual(value['guard']['transient_ids'], [17])
        self.assertEqual(value['spectroscopy']['energy_keV'], 100)

    def test_guard_below_imaging_threshold_still_retains_spectroscopy_collection(self):
        value = U.classify_observables(observed((17, 34), (3., 3.)))
        self.assertEqual(value['guard']['collecting_ids'], [17, 34])
        self.assertEqual(value['spectroscopy']['energy_keV'], 3.)
        self.assertEqual(value['strip_counts'], [0, 0])
        self.assertEqual(value['strip_threshold_keV'], 5.)

    def test_adjacent_strips_are_not_merged_or_promoted_to_interactions(self):
        data = observed((4, 5, 21), (40, 60, 100)); original = copy.deepcopy(data)
        value = U.classify_observables(data)
        self.assertEqual(value['adjacent_strip_pairs'], [[4, 5]])
        self.assertEqual(value['strip_counts'], [2, 1])
        self.assertEqual(data, original)
        self.assertEqual(value['photon_multiplicity'], 'unresolved')

    def test_failed_response_retains_null_energy(self):
        data = observed(); data.update(status='native_failed', channels=None)
        value = U.classify_observables(data)
        self.assertEqual(value['category'], 'failed_or_incomplete')
        self.assertIsNone(value['spectroscopy']['energy_keV'])

    def test_truth_source_and_candidates_do_not_change_spectroscopy(self):
        data = observed(); before = U.classify_observables(data)
        data.update(truth_edep_keV=999, source_position_mm=[999, 0, 0], input_steps=['secret'])
        after = U.classify_observables(data, {'candidates': [{'weight': 1}]})
        self.assertEqual(after['spectroscopy'], before['spectroscopy'])
        self.assertEqual(after['category'], 'ambiguous_imaging')
        self.assertEqual(after['same_pixel_multiplicity'], 'unidentifiable')
        self.assertFalse(after['supported_imaging'])

    def test_rejected_collector_cannot_be_replaced_by_terminal_charge(self):
        data = observed(); data['channels'][3].update(accepted=False, reconstructed_energy_keV=None)
        value = U.classify_observables(data)
        self.assertIsNone(value['spectroscopy']['energy_keV'])
        self.assertEqual(value['terminal_charge_diagnostic']['mean_keV_equivalent'], 100)
        self.assertEqual(value['category'], 'unresolved_signal')


if __name__ == '__main__':
    unittest.main()
