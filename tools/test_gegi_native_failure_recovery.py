import copy
from pathlib import Path
import tempfile
import unittest

import gegi_campaign_response as C
import gegi_event_store as S
from gegi_native_failure_recovery import inherit_complete
from test_gegi_native_signal_only import native_payload


class RecoveryInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-recovery-', dir=C.ROOT/'.local')
        self.addCleanup(self.temp.cleanup); root = Path(self.temp.name)
        self.prior = S.Store(root/'prior.sqlite', {'producer': 'original'}, create=True)
        self.current = S.Store(root/'current.sqlite', {'producer': 'corrected'}, create=True)
        self.addCleanup(self.prior.close); self.addCleanup(self.current.close)
        self.event, self.signals = native_payload()
        self.group = {'event_id': 27, 'group_id': 0, 'steps': [{'raw_row_index': 4, 'energy_keV': 4.}]}
        self.event['input_group'] = self.group
        self.event['input_steps'] = self.group['steps']
        self.event['steps'][0]['endpoints'] = [
            {'status': 'contact', 'step_limit_reached': False, 'contact_ids': [3]},
            {'status': 'contact', 'step_limit_reached': False, 'contact_ids': [24]}]
        self.digest = S.sha(S.encoded(self.group))
        self.binding = {'ref': 'prior', 'request_sha256': 'a'*64, 'producer_archive_sha256': 'b'*64}

    def test_exact_complete_inheritance_keeps_signed_bits_and_actual_producer(self):
        self.prior.append(27, 0, self.event, self.signals, self.digest)
        old = self.prior.read(27, 0, with_signals=True)
        result = inherit_complete(self.prior, self.binding, self.group, self.current)
        saved, signals = self.current.read(27, 0, with_signals=True)
        self.assertEqual(signals, self.signals)
        self.assertEqual(signals[2]['signed_induced_keV'], [0., .25, 0.])
        self.assertEqual(saved['native_recovery_inherited']['request_sha256'], 'a'*64)
        self.assertEqual(saved['native_recovery_inherited']['event_metadata_sha256'],
                         self.prior.db.execute('SELECT metadata_sha256 FROM events').fetchone()[0])
        self.assertEqual(result, saved)
        self.assertEqual(self.prior.read(27, 0, with_signals=True), old)

    def test_unfinished_prior_carrier_is_recomputed_and_changed_input_rejected(self):
        event = copy.deepcopy(self.event); event['status'] = 'step_limit'
        event['steps'][0]['endpoints'][0].update(status='step_limit', step_limit_reached=True, contact_ids=[])
        self.prior.append(27, 0, event, self.signals, self.digest)
        self.assertIsNone(inherit_complete(self.prior, self.binding, self.group, self.current))
        self.assertEqual(list(self.current.keys()), [])
        changed = copy.deepcopy(self.group); changed['steps'][0]['energy_keV'] = 5.
        with self.assertRaisesRegex(ValueError, 'input changed'):
            inherit_complete(self.prior, self.binding, changed, self.current)


if __name__ == '__main__':
    unittest.main()
