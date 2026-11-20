"""Saved-waveform parity, bounded retention and restart contracts; no physics."""

import copy
import json
import unittest

import numpy as np

import gegi_exposure_stream as legacy
import gegi_streaming_readout as streaming
from test_gegi_digital_readout import event_native
from test_gegi_pulse_stream import prepare, pulse


def components():
    first = prepare(pulse((3, 24), 190., neighbor=True))
    second = prepare(pulse((11, 26), 470.))
    third = prepare(pulse((12, 29), 160.))
    return [(third, 1577., 1.), (first, 2017., 1.), (second, 2017., 1.),
            (third, 2417., 1.), (third, 6007., 1.),
            (first, 69727., 1.), (second, 69727., 1.)]


def observer(rows):
    return lambda event, context: rows.append((copy.deepcopy(event), copy.deepcopy(context)))


class StreamingReadoutTests(unittest.TestCase):
    def legacy_result(self, inputs, live=70000., phase=7., seed=23):
        clock = legacy.ADCExposure(inputs, live_time_ns=live, phase_ns=phase, noise_seed=seed)
        rows = []
        result = legacy.reconstruct_exposure(clock, block_samples=41, on_readout_context=observer(rows))
        adc = np.concatenate([code for _, code in clock.blocks(41)], axis=1)
        return result, rows, adc

    def assert_rows(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for (event, context), (reference, saved) in zip(actual, expected):
            self.assertEqual(event, reference)
            self.assertEqual(context['readout_trigger_id'], saved['readout_trigger_id'])
            self.assertEqual(context['readout_rejection_reason'], saved['readout_rejection_reason'])
            self.assertEqual(context['first_sample_index'], saved['first_sample_index'])
            self.assertEqual(context['stop_sample_index'], saved['stop_sample_index'])
            np.testing.assert_array_equal(context['adc_codes'], saved['adc_codes'])
            self.assertEqual(legacy.replay_readout_context(context), reference)

    def test_exact_legacy_adc_context_and_all_electrode_readout_across_block_sizes(self):
        inputs = components()
        expected, saved, adc = self.legacy_result(inputs)
        digests = []
        for block in (1, 11, 41, 32768):
            with self.subTest(block=block):
                rows, codes = [], []
                out = streaming.StreamingReadout(noise_seed=23, phase_ns=7., live_time_ns=70000.,
                    block_samples=block, on_readout_context=observer(rows),
                    on_adc_block=lambda first, code: codes.append(code.copy()))
                for native, onset, scale in inputs:
                    out.push(native, onset, scale)
                result = out.finalize(70000.)
                np.testing.assert_array_equal(np.concatenate(codes, axis=1), adc)
                self.assert_rows(rows, saved)
                for key in ('activity_count', 'unconfirmed_activity_count', 'maximum_context_samples',
                            'saturated_adc_codes', 'saturated_contact_ids', 'flags'):
                    self.assertEqual(result[key], expected[key])
                self.assertEqual(result['coincident_rises'], len(saved))
                self.assertEqual(result['sample_frames_processed'], adc.shape[1]-legacy.PREAMBLE_SAMPLES)
                self.assertEqual(result['adc_digest']['pending_frames'], 0)
                self.assertGreater(result['adc_digest']['blocks'], 1)
                self.assertLessEqual(result['buffered_samples_peak'], block+4096)
                digests.append(result['adc_digest'])
        self.assertTrue(all(digest == digests[0] for digest in digests))

    def test_checkpoint_pending_pulse_and_candidate_with_partition_change(self):
        inputs = components()
        _, saved, adc = self.legacy_result(inputs)
        rows, codes = [], []
        out = streaming.StreamingReadout(noise_seed=23, phase_ns=7., live_time_ns=70000., block_samples=11,
            on_readout_context=observer(rows), on_adc_block=lambda first, code: codes.append(code.copy()))
        for native, onset, scale in inputs[:3]:
            out.push(native, onset, scale)
        out.advance(2093.)
        state = json.loads(json.dumps(out.checkpoint(), allow_nan=False))
        self.assertTrue(state['pulses'])
        self.assertTrue(state['groups'])
        out = streaming.StreamingReadout.restore(state, block_samples=17,
            on_readout_context=observer(rows), on_adc_block=lambda first, code: codes.append(code.copy()))
        for native, onset, scale in inputs[3:5]:
            out.push(native, onset, scale)
        for edge in (2551., 6200., 15500., 49013.):
            out.advance(edge)
        state = json.loads(json.dumps(out.checkpoint(), allow_nan=False))
        self.assertFalse(state['pulses'])
        self.assertLessEqual(state['buffer_samples'], 81)
        out = streaming.StreamingReadout.restore(state, block_samples=7,
            on_readout_context=observer(rows), on_adc_block=lambda first, code: codes.append(code.copy()))
        for native, onset, scale in inputs[5:]:
            out.push(native, onset, scale)
        result = out.finalize(70000.)
        self.assert_rows(rows, saved)
        np.testing.assert_array_equal(np.concatenate(codes, axis=1), adc)
        reference = streaming.StreamingReadout(noise_seed=23, phase_ns=7., block_samples=257)
        for native, onset, scale in inputs:
            reference.push(native, onset, scale)
        self.assertEqual(result['adc_digest'], reference.finalize(70000.)['adc_digest'])

    def test_unknown_length_stream_prefix_contexts_and_bounded_long_quiet_history(self):
        prepared = prepare(pulse(neighbor=True))
        inputs = [(prepared, 1000.+5000.*i, 1.) for i in range(20)]
        _, expected, _ = self.legacy_result(inputs, live=100000., phase=0., seed=None)
        rows = []
        out = streaming.StreamingReadout(block_samples=137, max_context_samples=256,
                                        max_active_components=2, on_readout_context=observer(rows))
        for native, onset, scale in inputs:
            out.push(native, onset, scale)
            out.advance(onset+2000.)
        result = out.finalize(100000.)
        self.assert_rows(rows, expected)
        self.assertEqual(result['activity_count'], 20)
        self.assertEqual(result['active_components_peak'], 1)
        self.assertEqual(result['active_components'], 0)
        self.assertLessEqual(result['buffered_samples_peak'], 256+137)
        self.assertLess(result['activities_peak'], 4)
        self.assertLessEqual(out.checkpoint()['buffer_samples'], 81)
        self.assertTrue(any(context['recording_length_scope'] == 'received_prefix' for _, context in rows))

    def test_explicit_window_overflow_preserves_restartable_data_without_truncation(self):
        native = prepare(event_native({3: [0., 1600., 1600.], 24: [0., 1600., 1600.]}, (0., 2000., 2020.)))
        inputs = [(native, 1000., 1.)]
        _, expected, adc = self.legacy_result(inputs, live=7000., phase=0., seed=61)
        rows, codes = [], []
        out = streaming.StreamingReadout(noise_seed=61, block_samples=17, max_context_samples=64,
            on_readout_context=observer(rows), on_adc_block=lambda first, code: codes.append(code.copy()))
        out.push(native, 1000.)
        with self.assertRaises(streaming.WindowOverflow) as caught:
            out.advance(5000.)
        state = json.loads(json.dumps(caught.exception.checkpoint_state, allow_nan=False))
        self.assertEqual(state['reason_end'], 'operational_bound_reached')
        self.assertGreater(state['buffer_samples'], 64)
        self.assertFalse(rows)
        out = streaming.StreamingReadout.restore(state, max_context_samples=512, block_samples=11,
            on_readout_context=observer(rows), on_adc_block=lambda first, code: codes.append(code.copy()))
        result = out.finalize(7000.)
        self.assert_rows(rows, expected)
        np.testing.assert_array_equal(np.concatenate(codes, axis=1), adc)
        self.assertGreater(result['maximum_context_samples'], 64)

    def test_component_bound_source_watermark_and_implementation_identity(self):
        native = prepare(pulse())
        out = streaming.StreamingReadout(max_active_components=1)
        out.push(native, 1000.)
        with self.assertRaises(streaming.WindowOverflow) as caught:
            out.push(native, 1100.)
        state = caught.exception.checkpoint_state
        self.assertEqual(len(state['pulses']), 1)
        resumed = streaming.StreamingReadout.restore(state, max_active_components=2)
        resumed.push(native, 1100.)
        resumed.advance(2000.)
        with self.assertRaisesRegex(ValueError, 'onset order'):
            resumed.push(native, 1999.)
        wrong = resumed.checkpoint()
        wrong['producer_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'implementation changed'):
            streaming.StreamingReadout.restore(wrong)
        with self.assertRaisesRegex(ValueError, 'do not silently censor'):
            future = streaming.StreamingReadout()
            future.push(native, 10000.)
            future.finalize(5000.)


if __name__ == '__main__':
    unittest.main()
