import copy
import unittest
from gegi_native_failure_diagnostic import endpoint_region, summarize_record, reconciled_recovery_rows


class NativeFailureDiagnosticTests(unittest.TestCase):
    def test_store_commit_without_timing_append_is_not_lost_or_invented(self):
        group = {'event_id': 2, 'group_id': 0, 'steps': [{'raw_row_index': 7}]}
        saved = {'status': 'completed', 'steps': [{'endpoints': [
            {'status': 'contact', 'step_limit_reached': False, 'contact_ids': [1]},
            {'status': 'contact', 'step_limit_reached': False, 'contact_ids': [18]}]}]}
        class Native:
            def has(self, primary, gid, digest): return (primary, gid) == (2, 0)
            def read(self, primary, gid): return saved, None
        row = list(reconciled_recovery_rows([(7, group, {'status': 'native_failed'})], Native(), []))[0]
        self.assertTrue(row['complete'])
        self.assertEqual(row['new_status'], 'completed')
        self.assertIsNone(row['elapsed_seconds'])
        self.assertEqual(row['timing_status'], 'no_retained_timing_entry')

    def test_contact_limit_does_not_hide_other_unfinished_carrier(self):
        contact = {'step_limit_reached': True, 'contact_ids': [1], 'status': 'contact', 'position_mm': [0, 0, 5.5]}
        moving = {'step_limit_reached': True, 'contact_ids': [], 'status': 'step_limit', 'position_mm': [0, 0, 5.]}
        record = {'group': {'steps': [{'raw_row_index': 7}]},
                  'event': {'status': 'step_limit', 'steps': [{'endpoints': [contact, moving]}]},
                  'native': {'1': {'signed_induced_keV': [0., -1., -2.]}}}
        before = copy.deepcopy(record)
        row = summarize_record(record)
        self.assertEqual(row['contact_at_limit'], 1)
        self.assertEqual(row['noncontact_at_limit'], 1)
        self.assertTrue(row['terminal_bin_moving'])
        self.assertEqual(record, before)

    def test_unavailable_waveform_stays_unknown_and_regions_are_geometric(self):
        record = {'group': {'steps': [1, 2]}, 'event': {'status': 'native_failed',
                  'steps': [dict(raw_row_index=7)], 'native_domain_error': 'Invalid native signed charge'}, 'native': None}
        row = summarize_record(record)
        self.assertIsNone(row['terminal_bin_moving'])
        self.assertFalse(row['native_available'])
        self.assertEqual(row['truth_rows'], 2)
        self.assertEqual(endpoint_region([-45.000012964, 16.8662, -3.54]), 'x_face')
        self.assertEqual(endpoint_region([0., 0., 0.]), 'interior')


if __name__ == '__main__':
    unittest.main()
