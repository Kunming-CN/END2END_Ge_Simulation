"""Exact finite unknown-history qualification, using deterministic numeric inputs."""

import json
import random
import unittest

import gegi_dual_source as dual
from gegi_missing_history import HistoryOverflow, MissingHistory, native_support_ns
from gegi_streaming_readout import StreamingReadout
from test_gegi_pulse_stream import prepare, pulse


def original(rows, live):
    return dual._history_mask([{'first_ge_deposit_ns': a, 'last_ge_deposit_ns': b,
                               'positive_ge_energy_keV': e} for a, b, e in rows], live)


class MissingHistoryTests(unittest.TestCase):
    def test_native_support_is_bound_to_actual_drift_grid_and_checkpoint(self):
        self.assertEqual(native_support_ns({'drift_dt_ns': 1., 'drift_cap_ns': 1000.}), 1001.)
        self.assertEqual(native_support_ns({'drift_dt_ns': 2.5, 'drift_cap_ns': 1001.}), 1005.)
        history = MissingHistory(5e6, native_support_ns=1005.)
        history.add(10000., 10010., 662.)
        saved = history.checkpoint()
        self.assertEqual(saved['max_horizon_ns'], 11015.)
        self.assertEqual(MissingHistory.restore(saved, native_support_ns=1005.).checkpoint(), saved)
        with self.assertRaisesRegex(ValueError, 'response configuration'):
            MissingHistory.restore(saved, native_support_ns=1001.)
        for invalid in ({'drift_dt_ns': 0.}, {'drift_cap_ns': float('inf')}, {'drift_dt_ns': 2., 'drift_cap_ns': 1.}):
            with self.assertRaises(ValueError):
                native_support_ns(invalid)
    def test_exact_legacy_union_for_overlapping_horizons_and_recording_edges(self):
        rng = random.Random(20261120)
        live = 5e6+19.5
        for size in (0, 1, 2, 7, 31):
            rows = sorted((rng.uniform(0, live-20000), rng.uniform(0, 100000), 10**rng.uniform(-6, 5))
                          for _ in range(size))
            rows = [(first, first+span, energy) for first, span, energy in rows]
            history = MissingHistory(live)
            for i, row in enumerate(rows):
                history.add(*row)
                self.assertEqual(history.intervals(live), original(rows[:i+1], live))
            intervals = original(rows, live)
            self.assertEqual(history.intervals(), intervals)
            for t in [0., 5999., 6000., live-4001., live-4000., live-3999., live,
                      *(rng.uniform(0, live) for _ in range(50))]:
                for span in (0., 7500.):
                    start = max(0., t-span)
                    self.assertEqual(history.contains(t, trigger_time_ns=start),
                                     any(left <= t and right > start for left, right in intervals))

    def test_non_grid_final_edge_uses_original_sample_alignment(self):
        history = MissingHistory(200019.5)
        self.assertEqual(history.intervals(), [[0., 6000], [196000, 200019.5]])
        self.assertTrue(history.contains(196010.))
        self.assertFalse(history.contains(195999.))
        self.assertFalse(history.contains(200019.5))

    def test_checkpoint_resume_exact_zero_pruning_and_finite_recovery(self):
        rows = [(10000., 10100., 662.), (50000000., 50010000., 120.), (100000000., 100000100., 200.)]
        live = 200000000.
        history = MissingHistory(live)
        history.add(*rows[0])
        self.assertTrue(history.contains(20000.))
        self.assertFalse(history.contains(2000000.))
        saved = json.loads(json.dumps(history.checkpoint(), allow_nan=False))
        history = MissingHistory.restore(saved)
        for row in rows[1:]:
            history.add(*row)
        self.assertEqual(history.intervals(), original(rows, live))
        self.assertEqual(history.statistics()['active_failure_bounds'], 1)
        self.assertEqual(history.statistics()['failure_count'], 3)
        self.assertNotIn('raw_failures', history.checkpoint())

    def test_future_failure_requires_post_margin_before_candidate_callback(self):
        native = prepare(pulse())
        history = MissingHistory(5000000.)
        unsafe = []
        stream = StreamingReadout(live_time_ns=5000000., on_readout_context=lambda event, context: unsafe.append(event))
        stream.push(native, 87000.)
        stream.advance(89000.)
        self.assertEqual(len(unsafe), 1)
        self.assertFalse(history.contains(unsafe[0]['rise_end_ns'], trigger_time_ns=unsafe[0]['trigger_time_ns']))
        history.add(90000., 90000., 662.)
        self.assertTrue(history.contains(unsafe[0]['rise_end_ns'], trigger_time_ns=unsafe[0]['trigger_time_ns']))
        qualified = []
        safe_history = MissingHistory(5000000.)
        safe = StreamingReadout(live_time_ns=5000000., on_readout_context=lambda event, context: qualified.append(
            safe_history.contains(event['rise_end_ns'], trigger_time_ns=event['trigger_time_ns'])))
        safe.push(native, 87000.)
        safe.advance(90000.-dual.POST_NS)
        self.assertFalse(qualified)
        safe_history.add(90000., 90000., 662.)
        safe.advance(93000.)
        self.assertEqual(qualified, [True])

    def test_active_bound_halts_without_accepting_new_failure_and_restores(self):
        history = MissingHistory(5000000., max_active_failures=2)
        rows = [(10000., 10100., 200.), (11000., 11200., 300.), (12000., 12100., 400.)]
        history.add(*rows[0]); history.add(*rows[1])
        with self.assertRaises(HistoryOverflow) as caught:
            history.add(*rows[2])
        self.assertEqual(history.statistics()['failure_count'], 2)
        resumed = MissingHistory.restore(caught.exception.checkpoint_state, max_active_failures=3)
        resumed.add(*rows[2])
        self.assertEqual(resumed.intervals(), original(rows, 5000000.))
        wrong = resumed.checkpoint(); wrong['tail_source_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'implementation changed'):
            MissingHistory.restore(wrong)
        with self.assertRaises(ValueError):
            resumed.add(11999., 13000., 10.)
        with self.assertRaises(ValueError):
            resumed.intervals(6000000.)


if __name__ == '__main__':
    unittest.main()
