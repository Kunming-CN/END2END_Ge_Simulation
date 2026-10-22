"""Deterministic tests of the exact2-column nonnegative energy profile."""
import inspect
from dataclasses import replace
import unittest

import numpy as np

import gegi_native_pair_inverse as P
from test_gegi_native_inverse import fixture_bank, WaveWithTruth


class PairEnergyTests(unittest.TestCase):
    def test_waveform_only_fit_recovers_unequal_unknown_energies(self):
        single = fixture_bank()
        second = single.cells[1]
        corners = []
        for corner in second.corners:
            wave = corner.unit_wave.copy()
            wave[2:4] = wave[0:2]
            wave[0:2] = 0.
            corners.append(replace(corner, unit_wave=wave, unit_delta=np.diff(wave, axis=1)))
        second = replace(second, corners=tuple(corners))
        single = replace(single, cells=(single.cells[0], second))
        bank = P.prepare_bank(single)
        waveform = (117.*P.N.unit_prediction(single.cells[0], [.25, .75])
                    +283.*P.N.unit_prediction(second, [.75, .25])).view(WaveWithTruth)
        waveform.true_energies_keV = [250., 250.]
        waveform.true_positions_mm = [[999., 999., 999.], [-999., -999., -999.]]
        result = P.fit_two(waveform, bank)
        sites = result['refined_hypotheses'][0]['sites']
        np.testing.assert_allclose([s['energy_keV'] for s in sites], [117., 283.], atol=1e-9)
        np.testing.assert_allclose([s['position_mm'] for s in sites], [[.25, .75, 0.], [.75, .25, 0.]], atol=1e-12)
        self.assertLess(result['refined_hypotheses'][0]['rms_keV'], 1e-10)
        with self.assertRaises(TypeError):
            P.fit_two(waveform, bank, true_energies_keV=[250., 250.])

    def test_correlated_interior_basis(self):
        a = np.array([1., .5, .2]); b = np.array([.8, .6, -.3])
        waveform = 17.*a+31.*b
        x, y, cost, active = P.nnls2(a@a, a@b, b@b, a@waveform, b@waveform, waveform@waveform)
        np.testing.assert_allclose([x, y], [17., 31.], atol=1e-12)
        self.assertAlmostEqual(float(cost), 0., places=10)
        self.assertEqual(int(active), 0)

    def test_negative_unconstrained_solution_uses_boundary(self):
        a = np.array([1., 0.]); b = np.array([.8, .6]); waveform = 2.*a-b
        x, y, cost, active = P.nnls2(a@a, a@b, b@b, a@waveform, b@waveform, waveform@waveform)
        self.assertAlmostEqual(float(x), 1.2)
        self.assertEqual(float(y), 0.)
        self.assertAlmostEqual(float(cost), .36)
        self.assertEqual(int(active), 1)

    def test_batch_zero_and_degenerate_columns(self):
        x, y, cost, active = P.nnls2([1., 1.], [1., 0.], [1., 1.], [3., -2.], [3., -1.], [9., 5.])
        np.testing.assert_allclose(x, [3., 0.])
        np.testing.assert_allclose(y, [0., 0.])
        np.testing.assert_allclose(cost, [0., 5.])
        np.testing.assert_array_equal(active, [1, 1])
        self.assertEqual(list(inspect.signature(P.fit_two).parameters), ['waveform', 'bank'])


if __name__ == '__main__':
    unittest.main()
