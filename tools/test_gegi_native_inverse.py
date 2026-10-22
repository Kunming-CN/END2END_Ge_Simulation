"""Small deterministic checks for the waveform-only native inverse contract."""
from dataclasses import replace
import inspect
import itertools
import unittest

import numpy as np

import gegi_native_inverse as N


class ForbiddenMetadata:
    def __getitem__(self, key):
        raise AssertionError('Fit accessed target/provenance metadata')


class WaveWithTruth(np.ndarray):
    pass


def fixture_bank():
    times = np.array([0., 20., 50., 100., 250.])
    cells = []
    for number, pixel in enumerate(((11, 24), (12, 26)), 1):
        corners = []
        for x, y in itertools.product((0., 1.), repeat=2):
            wave = np.zeros((34, len(times)))
            wave[pixel[0]-1] = [0., .25, .5, 1., 1.]
            wave[pixel[1]-1] = [0., -.25, -.5, -1., -1.]
            wave[0] = x*np.array([0., .4, .2, 0., 0.])
            wave[1] = y*np.array([0., .1, .5, 0., 0.])
            corners.append(N.Corner(str((number, x, y)), np.array([x, y, 0.]),
                times, wave, np.diff(wave, axis=1), {'electron': 20., 'hole': 100.}))
        cells.append(N.Cell(str(number), pixel, tuple(corners), np.zeros(3),
            np.array([1., 1., 0.]), (0, 1), np.array(list(itertools.product((False, True), repeat=2))), None))
    poison = ForbiddenMetadata()
    return N.Bank(tuple(cells), poison, poison, poison, poison, 0.)


class NativeInverseTests(unittest.TestCase):
    def test_truth_isolation_and_independent_energy(self):
        bank = fixture_bank()
        waveform = (N.unit_prediction(bank.cells[0], [.25, .75])*317.).view(WaveWithTruth)
        # Contradictory target labels must have no effect on a numeric waveform.
        waveform.true_contact_ids = [12, 26]
        waveform.true_position_mm = [999., -999., 42.]
        waveform.true_energy_keV = 12345.
        fit = N.fit_single(waveform, bank)
        best = fit['hypotheses'][0]
        self.assertEqual(best['contact_ids'], [11, 24])
        np.testing.assert_allclose(best['position_mm'], [.25, .75, 0.], atol=1e-12)
        self.assertAlmostEqual(best['energy_keV'], 317., places=10)
        self.assertEqual({tuple(h['contact_ids']) for h in fit['hypotheses']}, {(11, 24), (12, 26)})
        self.assertEqual(list(inspect.signature(N.fit_single).parameters), ['waveform', 'bank'])
        with self.assertRaises(TypeError):
            N.fit_single(waveform, bank, true_energy_keV=12345.)

    def test_boundary_weights_drop_zeros_and_preserve_affine_position(self):
        cell = fixture_bank().cells[0]
        indices, weights = N.weights_for(cell, [0., .375])
        self.assertEqual(len(indices), 2)
        self.assertTrue(all(w > 0 for w in weights))
        self.assertEqual(sum(weights), 1.)
        position = sum(w*cell.corners[i].position_mm for i, w in zip(indices, weights))
        np.testing.assert_array_equal(position, [0., .375, 0.])

    def test_carrier_order_flip_has_no_fallback(self):
        cell = replace(fixture_bank().cells[0], unsupported_reason='carrier_order_flips')
        with self.assertRaisesRegex(N.T.UnsupportedWarp, 'carrier_order_flips'):
            N.unit_prediction(cell, [.5, .5])
        bank = replace(fixture_bank(), cells=(cell,))
        result = N.fit_single(np.ones((34, len(N.R.FIT_GRID_NS))), bank)
        self.assertEqual(result['status'], 'unsupported')
        self.assertEqual(result['hypotheses'], [])
        self.assertEqual(result['unsupported_cells'][0]['reason'], 'carrier_order_flips')


if __name__ == '__main__':
    unittest.main()
