"""Pure saved-waveform time-warp contracts; no pilot or native calculation."""
import unittest
import numpy as np
import gegi_lateral_timing_comparison as T


def row(electron, hole):
    time = np.arange(max(electron, hole)+1, dtype=float)
    phase = np.interp(time, [0, min(electron, hole), max(electron, hole)], [0, 1, 2])
    return {'signal_coverage': T.R.ALL34_COVERAGE,
        'endpoints': [{'species': s, 'samples': t+1, 'status': 'contact', 'step_limit_reached': False}
                      for s, t in (('electron', electron), ('hole', hole))],
        'channel_signals': [{'contact_id': cid, 'time_ns': time.tolist(),
            'signed_induced_keV': ((phase if cid % 2 else phase*(2-phase)*(1-phase))*(cid if cid <= 17 else -cid)).tolist()}
            for cid in T.R.ALL34_IDS]}


class TimeWarpTests(unittest.TestCase):
    def test_identity_timewarp(self):
        times = {'electron': 10., 'hole': 30.}; grid = np.arange(251.)
        np.testing.assert_array_equal(T.mapped_times(times, times, grid), grid)
        native = row(10, 30); predicted, _, _ = T.predict([native], [1.], 1., grid)
        expected = np.asarray([np.interp(grid, s['time_ns'], s['signed_induced_keV']) for s in native['channel_signals']])
        np.testing.assert_array_equal(predicted, expected)

    def test_all_channels_share_the_same_warp_and_bipolar_terminal_is_retained(self):
        corners = [row(10, 30), row(20, 60)]; grid = np.arange(251.)
        predicted, meta, terminal = T.predict(corners, [.5, .5], 1., grid)
        self.assertEqual(meta['predicted_arrivals_ns'], {'electron': 15., 'hole': 45.})
        expected = np.zeros_like(predicted)
        for native, times in zip(corners, ({'electron': 10., 'hole': 30.}, {'electron': 20., 'hole': 60.})):
            shared = np.interp(grid, [0, 15, 45, 250], [0, times['electron'], times['hole'], 250])
            for i, signal in enumerate(native['channel_signals']):
                expected[i] += .5*np.interp(shared, signal['time_ns'], signal['signed_induced_keV'])
        np.testing.assert_array_equal(predicted, expected)
        self.assertEqual(terminal[1], 0.); self.assertEqual(predicted[1, -1], 0.)
        self.assertGreater(predicted[1].max(), 0.)
        self.assertLess(predicted[1].min(), 0.)

    def test_invalid_knots_and_order_flip_are_explicitly_unsupported(self):
        for times in ({'electron': 10., 'hole': 10.}, {'electron': 0., 'hole': 20.},
                      {'electron': 10., 'hole': 250.}, {'electron': float('nan'), 'hole': 20.}):
            with self.subTest(times=times), self.assertRaises(T.UnsupportedWarp):
                T.knots(times)
        with self.assertRaisesRegex(T.UnsupportedWarp, 'carrier_order_flips'):
            T.predict([row(10, 30), row(30, 10)], [.5, .5], 1.)


if __name__ == '__main__':
    unittest.main()
