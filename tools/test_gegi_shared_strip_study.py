"""Check two-site response allocation with three distinct collecting strips."""

import unittest

import numpy as np

import gegi_joint_two_site as joint
import gegi_shared_strip_study as shared


class SharedStripTests(unittest.TestCase):
    def test_unique_face_controls_partition_and_preserves_face_average_total(self):
        card = {'x_collecting_strips': [3], 'y_collecting_strips': [19, 25], 'guard_contact_ids': [],
                'x_sum_keV': 302., 'y_sum_keV': 300., 'energy_keV': 301.}
        observed = [{'contact_id': cid, 'slow_energy_keV': v} for cid, v in ((3, 302.), (19, 101.), (25, 199.))]
        candidate = shared.shared_pairing(card, observed)
        self.assertEqual(candidate['shared_contact_id'], 3)
        self.assertEqual(candidate['shared_axis'], 'x')
        self.assertAlmostEqual(sum(x['energy_keV'] for x in candidate['sites']), 301.)
        self.assertAlmostEqual(candidate['sites'][0]['energy_keV']/candidate['sites'][1]['energy_keV'], 101./199.)
        self.assertEqual([(s['x_contact_id'], s['y_contact_id']) for s in candidate['sites']], [(3, 19), (3, 25)])
        self.assertEqual(shared.shared_pairing(dict(card, energy_keV=None), observed)['status'], 'unqualified_strip_energy')

    def test_shared_y_is_one_observed_cfd_crossing_and_both_conditional_orders_remain(self):
        cells = ((3, 19), (8, 19))
        card = {'x_collecting_strips': [3, 8], 'y_collecting_strips': [19], 'guard_contact_ids': [],
                'x_sum_keV': 300., 'y_sum_keV': 300., 'energy_keV': 300.}
        seen = [{'contact_id': cid, 'slow_energy_keV': e, 'preamp_cfd50_ns': 40., 'low': None, 'high': None}
                for cid, e in ((3, 150.), (8, 150.), (19, 300.))]
        pairing = shared.shared_pairing(card, seen)
        templates = {}
        responses = []
        for i, (x, y) in enumerate(cells):
            response = np.zeros((34, len(joint.VOLTAGE_NS)))
            signal = joint.pulse._SLOW_GAIN * np.clip(joint.VOLTAGE_NS/80, 0, 1)
            response[[x-1, y-1]] = signal
            templates[x, y] = joint.Template((x, y), (i*4., 0.), 4., np.tile(response, (len(joint.DEPTH_MM), 1, 1)))
            responses.append(response)
        volts = joint.shifted_samples(sum(responses)*150., 0.)
        fitted = shared.shared_fit(pairing, seen, templates, volts)
        self.assertEqual(fitted['status'], 'scored')
        self.assertAlmostEqual(fitted['global_adc_rms_codes'], 0., places=7)
        self.assertEqual([r['contact_id'] for r in fitted['collector_timing']], [3, 8, 19])
        self.assertAlmostEqual(fitted['collector_timing'][-1]['modeled_cfd_ns'], 40., places=6)
        self.assertEqual(len(fitted['conditional_orders']), 2)


if __name__ == '__main__':
    unittest.main()
