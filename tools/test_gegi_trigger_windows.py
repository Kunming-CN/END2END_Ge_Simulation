import unittest

import numpy as np

import gegi_trigger_windows as windows


class TriggerWindowTests(unittest.TestCase):
    def test_cross_block_capture_preserves_raw_codes_and_original_ordinals(self):
        raw = np.arange(34 * 300, dtype=np.int16).reshape(34, 300)
        class Clock:
            phase_ns = 10
            live_samples = raw.shape[1]

            def sample_time_ns(self, index):
                return self.phase_ns + index * windows.SAMPLE_PERIOD_NS

            def blocks(self):
                yield -3, raw[:, :3]
                for first in range(0, self.live_samples, 29):
                    yield first, raw[:, first:first+29]

        clock = Clock()
        stop_ns = windows.digital._TIMING['gate_ns'][1]
        trigger = clock.sample_time_ns(60)
        second = clock.sample_time_ns(160)
        times = [10, trigger, second, clock.sample_time_ns(299)]
        mask = [[second + stop_ns, second + stop_ns + 1]]
        out = windows.capture(clock, times, mask)
        self.assertEqual(out['window_status'].tolist(),
                         ['outside_live_time', 'captured', 'excluded_history', 'outside_live_time'])
        self.assertEqual(out['two_strip_ordinal'].tolist(), [2])
        np.testing.assert_array_equal(out['adc_codes'][0], raw[:, 56:61+stop_ns//windows.SAMPLE_PERIOD_NS])
        digest = windows.sha256()
        for chunk in (raw[:, :3], raw):
            digest.update(chunk.T.astype('<i2').tobytes())
        self.assertEqual(digest.hexdigest(), out['known_component_adc_sha256'])
        captured = {time: windows.capture_context(clock, time, mask, 53, raw[:, 53:91]) for time in times}
        direct = windows.context_arrays(times, captured, out['acquisition_baseline_v'], digest.hexdigest())
        for key in out:
            np.testing.assert_array_equal(out[key], direct[key])


if __name__ == '__main__':
    unittest.main()
