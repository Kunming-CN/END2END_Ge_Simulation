"""Check depth availability and frozen candidate order in the GeGI CFD study."""

import unittest

from gegi_digital_pairs import compton_orders, energy_pairings
from gegi_two_site_cfd_study import conditional_estimates, measure_depth, score, topology


class TwoSiteDepthTests(unittest.TestCase):
    def setUp(self):
        self.curve = {'status': 'available', 'direction': -1, 'z_mm': [-5., 0., 5.],
                      'cfd_x_minus_y_ns': [10., 0., -10.]}

    def test_depth_abstains_outside_support_or_with_no_time(self):
        collectors = {3: {'preamp_cfd50_ns': 41.}, 24: {'preamp_cfd50_ns': 42.}}
        curves = {(3, 24): self.curve}
        measured = measure_depth((3, 24), collectors, curves)
        self.assertEqual((measured['cfd_x_minus_y_ns'], measured['estimated_z_mm']), (-1., .5))
        self.assertEqual(measure_depth((3, 25), collectors, curves)['depth_status'], 'collector_cfd_unavailable')
        collectors[24]['preamp_cfd50_ns'] = 60.
        outside = measure_depth((3, 24), collectors, curves)
        self.assertEqual((outside['depth_status'], outside['estimated_z_mm']), ('outside_calibrated_cfd_range', None))

    def test_preserves_both_pairings_and_orders_when_depth_unavailable(self):
        x, y = (3, 4), (23, 24)
        hits = dict.fromkeys(x+y, 331.)
        pairings = list(energy_pairings(x, y, hits))
        for pairing in pairings:
            pairing['compton_orders'] = compton_orders(pairing['sites'])
        card = {'collectors': [{'contact_id': cid, 'preamp_cfd50_ns': 40.} for cid in hits], 'pairings': pairings}
        geometry = {cid: {'strip_center_mm': float(cid)} for cid in hits}
        estimates = conditional_estimates(card, {(3, 23):self.curve, (4, 24):self.curve}, geometry)
        self.assertEqual([row['index'] for row in estimates], [0, 1])
        self.assertEqual([[order['site_index_order'] for order in row['orders']] for row in estimates], [
            [[0, 1], [1, 0]], [[0, 1], [1, 0]]])
        self.assertTrue(all(order['conditional_cone'] is not None for order in estimates[0]['orders']))
        self.assertTrue(all(order['conditional_cone'] is None for order in estimates[1]['orders']))
        self.assertEqual(topology([[3,23],[4,24]]), 'near')

    def test_scoring_maps_reference_energy_to_frozen_order(self):
        x, y = (3, 6), (23, 26)
        hits = {3:132.4, 6:529.6, 23:132.4, 26:529.6}
        pairings = list(energy_pairings(x, y, hits))
        for card in pairings:
            card['compton_orders'] = compton_orders(card['sites']) if card['energy_compatible'] else []
        card = {'collectors': [{'contact_id': cid, 'preamp_cfd50_ns': 40.} for cid in hits], 'pairings': pairings}
        geometry = {cid: {'strip_center_mm': float(cid)} for cid in hits}
        estimates = conditional_estimates(card, {(3, 23):self.curve, (6, 26):self.curve}, geometry)
        expected = [{'contact_ids':[6,26], 'xyz_mm':[6.,26.,0.]}, {'contact_ids':[3,23], 'xyz_mm':[3.,23.,0.]}]
        scored = score(estimates, expected, [None, None], [529.6,132.4], geometry)
        self.assertEqual(scored['truth_pair_index'], 0)
        self.assertEqual(scored['status'], 'compared')
        errors = {tuple(row['site_index_order']): row['half_angle_error_deg'] for row in scored['half_angle_errors']}
        self.assertEqual(errors, {(0,1):0., (1,0):None})
        self.assertAlmostEqual(scored['axis_error_deg']['candidate_depth_deg'], 0., places=5)


if __name__ == '__main__':
    unittest.main()
