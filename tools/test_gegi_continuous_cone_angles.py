import math
import unittest

from gegi_continuous_cone_angles import angular_residual, fitted_cones
from gegi_digital_pairs import compton_orders
from gegi_joint_acquisition_study import scores


class ContinuousConeTests(unittest.TestCase):
    def test_position_methods_preserve_both_orders_and_compute_signed_angle(self):
        sites = [{'energy_keV': 331.}, {'energy_keV': 331.}]
        pair = dict(index=1, sites=sites, compton_orders=compton_orders(sites))
        models = {support: dict(optimizer_success=True, positions_mm=xyz) for support, xyz in [
            ('center', [[2., 0., 0.], [0., 0., 0.]]), ('lateral', [[2., 1., 0.], [0., 1., 0.]])]}
        cones = list(fitted_cones(pair, {'fits': {'waveform': models}}))
        self.assertEqual([(c['support'], c['order']) for c in cones],
                         [('center', [0, 1]), ('center', [1, 0]), ('lateral', [0, 1]), ('lateral', [1, 0])])
        for candidate in cones:
            angle = math.radians(candidate['half_angle_deg'])
            vertex, axis = candidate['vertex_mm'], candidate['axis']
            source = [vertex[0] + 10 * axis[0] * math.cos(angle), vertex[1] + 10 * math.sin(angle), 0.]
            self.assertAlmostEqual(angular_residual(candidate, source), 0., places=10)
        self.assertLess(angular_residual(cones[0], [10., 0., 0.]), 0.)

    def test_truth_pair_with_incompatible_energy_does_not_enter_position_denominator(self):
        self.assertIsNone(scores(dict(index=0, energy_compatible=False),
                                 {'comparison': {'truth_pairing_index': 0}}, {}))


if __name__ == '__main__':
    unittest.main()
