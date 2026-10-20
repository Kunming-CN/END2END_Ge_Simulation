"""Relevant checkpoint integrity and absent-channel accounting checks; no simulation."""
import copy
import unittest

import gegi_calibration_inventory as C
import scenario_workflow as W


class Inventory(unittest.TestCase):
    def checkpoint(self, signals=True):
        row = {'position_mm': [2.0, 2.0, 0.0], 'contact_ids': [9, 26],
               'signals': {'X': {'time_ns': [0.0, 1.0], 'signed_induced_keV': [0.0, 2.0]},
                           'Y': {'time_ns': [0.0, 1.0], 'signed_induced_keV': [0.0, -2.0]}} if signals else None,
               'status': 'completed' if signals else 'excluded_geometry', 'valid': signals,
               'execution_seconds': 0.02}
        return {'kind': 'gegi_independent_injection_checkpoint_v1', 'identity_sha256': 'a'*64,
                'payload': row, 'payload_sha256': W.digest(row)}

    def test_selected_pair_preserves_signed_schema_and_channel_ids(self):
        result = C.inspect_checkpoint(self.checkpoint(), 'a'*64, 1.0)
        self.assertEqual(result['signal_samples_by_channel'], {'9': 2, '26': 2})

    def test_geometry_exclusion_remains_null(self):
        result = C.inspect_checkpoint(self.checkpoint(False), 'a'*64, 1.0)
        self.assertEqual(result['signal_samples_by_channel'], {})
        self.assertFalse(result['valid'])

    def test_tamper_and_rehashed_invalid_grid_refused(self):
        record = self.checkpoint()
        record['payload']['signals']['X']['time_ns'][1] = 2.0
        with self.assertRaisesRegex(W.ControlError, 'payload changed'):
            C.inspect_checkpoint(record, 'a'*64, 1.0)
        record['payload_sha256'] = W.digest(record['payload'])
        with self.assertRaisesRegex(W.ControlError, 'Invalid signed'):
            C.inspect_checkpoint(record, 'a'*64, 1.0)

    def test_full_response_cannot_be_inferred_from_metadata(self):
        record = self.checkpoint()
        record['payload']['signals']['guard'] = copy.deepcopy(record['payload']['signals']['X'])
        record['payload_sha256'] = W.digest(record['payload'])
        with self.assertRaisesRegex(W.ControlError, 'waveform schema'):
            C.inspect_checkpoint(record, 'a'*64, 1.0)


if __name__ == '__main__':
    unittest.main()
