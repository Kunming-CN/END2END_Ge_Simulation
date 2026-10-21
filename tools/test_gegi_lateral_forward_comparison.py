"""Pure interpolation contracts; no capture, campaign, fitting or physics."""
import itertools
import unittest
import numpy as np
import gegi_lateral_forward_comparison as L


class InterpolationTests(unittest.TestCase):
    axes = ((-1., 0., 1.), (-2., 0., 2.), (-4., 0., 4.))

    @staticmethod
    def function(x, y, z):
        base = np.arange(34*7).reshape(34, 7)
        return base+x+2*y+3*z+4*x*y+5*x*z+6*y*z+7*x*y*z

    def training(self):
        return {p: self.function(*p) for p in itertools.product(*self.axes)}

    def test_multilinear_waveforms_interpolate_exactly(self):
        point = (-.5, 1., 2.)
        np.testing.assert_array_equal(L.interpolate(self.training(), self.axes, point), self.function(*point))
        self.assertEqual(sum(L.corner_weights(self.axes, point).values()), 1.)
        for point in ((-1., -2., -4.), (1., 2., 4.), (0., 0., 0.)):
            np.testing.assert_array_equal(L.interpolate(self.training(), self.axes, point), self.function(*point))

    def test_out_of_bounds_and_missing_corner_rejected(self):
        with self.assertRaisesRegex(ValueError, 'in-bounds'):
            L.interpolate(self.training(), self.axes, (1.01, 0., 0.))
        training = self.training(); del training[-1., 0., 0.]
        with self.assertRaisesRegex(ValueError, 'Missing interpolation corner'):
            L.interpolate(training, self.axes, (-.5, 1., 2.))


if __name__ == '__main__':
    unittest.main()
