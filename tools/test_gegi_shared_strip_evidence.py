"""Focused check for independent availability of saved CFD observations and model times."""

import unittest

from gegi_shared_strip_evidence import diagnose


class SharedStripEvidenceTests(unittest.TestCase):
    def test_missing_crossings_preserve_available_contrasts_and_ambiguity(self):
        row = {'original_trigger_id': 13, 'trigger_time_ns': 800., 'archive_record_sha256': '1'*64,
               'archive_adc_sha256': '2'*64, 'original_x_collecting_strips': [3, 4],
               'original_y_collecting_strips': [29], 'original_face_totals_keV': [590., 600.],
               'original_measured_energy_keV': 595., 'original_event_energy_flags': [],
               'original_projection_status': 'outside_two_by_two_projection_scope', 'imaging_weight': None,
               'physical_interaction_multiplicity': 'unidentified', 'adc_window_status': 'captured',
               'collectors': [{'contact_id': cid, 'slow_energy_keV': energy, 'preamp_cfd50_ns': time}
                              for cid, energy, time in [(3, 440., None), (4, 150., 61.), (29, 600., 78.)]],
               'fit': {'status': 'scored', 'collector_timing': [
                   {'contact_id': cid, 'modeled_cfd_ns': time, 'modeled_crossing_valid': ok}
                   for cid, time, ok in [(3, 48., True), (4, 54., True), (29, None, False)]]}}
        result = diagnose(row)
        self.assertEqual(result['strip_pattern']['status'], 'adjacent_ambiguous')
        self.assertEqual(result['physical_interaction_multiplicity'], 'unidentified')
        self.assertIsNone(result['original_imaging_weight'])
        self.assertEqual(result['missing_measured_cfd_contact_ids'], [3])
        self.assertEqual(result['missing_modeled_cfd_contact_ids'], [29])
        comparison = result['timing']
        self.assertEqual(comparison['two_strip_minus_opposite'][1], {'contact_order': [4, 29],
            'measured_delta_ns': -17., 'modeled_delta_ns': None, 'measured_minus_modeled_ns': None})
        self.assertEqual(comparison['second_minus_first_same_face'], {'contact_order': [4, 3],
            'measured_delta_ns': None, 'modeled_delta_ns': 6., 'measured_minus_modeled_ns': None})
        self.assertEqual(result['energy']['opposite_minus_two_strip_face_keV'], 10.)
        self.assertAlmostEqual(result['energy']['smaller_strip_fraction'], 150/590)


if __name__ == '__main__':
    unittest.main()
