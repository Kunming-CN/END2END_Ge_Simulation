"""Measured fast feature receipts for GeGI acquisition triggers."""

import unittest

from gegi_dual_source import _strip_neighbors, _trigger_card


def channel(cid, *, slow=None, fast=None, flags=()):
    return {'contact_id': cid, 'slow_energy_keV': slow, 'fast_signal_keV_equiv': fast, 'flags': list(flags)}


def pulse(collectors, neighbors, *, single=None, flags=()):
    ids = [row['contact_id'] for row in collectors]
    return {'trigger_time_ns': 10000, 'rise_end_ns': 10080, 'channels': collectors + neighbors,
            'contact_ids': ids if single is not None else None, 'step_contact_ids': ids,
            'slow_energy_keV': single, 'flags': list(flags)}


class TriggerFeaturesTests(unittest.TestCase):
    def setUp(self):
        geometry = [dict(id=start + index, family=axis, guard=index == 16,
                         strip_center_mm=(index - 7.5) * 5 if index < 16 else None)
                    for axis, start in (('X', 1), ('Y', 18)) for index in range(17)]
        self.neighbors = _strip_neighbors(geometry[::-1])

    def test_collecting_energies_and_opposite_signed_ratios(self):
        readout = pulse([channel(3, slow=99.), channel(24, slow=101.)],
                        [channel(2, fast=11.), channel(4, fast=-4.),
                         channel(23, fast=-13.), channel(25, fast=2.)], single=100.)
        card = _trigger_card(readout, self.neighbors)
        self.assertEqual(card['single_pixel_energy_keV'], 100.)
        self.assertEqual(card['single_pixel_features'], {
            'x': {'contact_id': 3, 'slow_energy_keV': 99., 'fast_ratio': .15,
                  'low': {'contact_id': 2, 'fast_keV_equiv': 11., 'flags': []},
                  'high': {'contact_id': 4, 'fast_keV_equiv': -4., 'flags': []}},
            'y': {'contact_id': 24, 'slow_energy_keV': 101., 'fast_ratio': -.15,
                  'low': {'contact_id': 23, 'fast_keV_equiv': -13., 'flags': []},
                  'high': {'contact_id': 25, 'fast_keV_equiv': 2., 'flags': []}},
        })

    def test_edge_preserves_one_neighbor_on_each_face(self):
        edge_cases = [(16, 18, (15, None), (None, 19)), (1, 33, (None, 2), (32, None))]
        for x, y, x_neighbors, y_neighbors in edge_cases:
            with self.subTest(x=x, y=y):
                nearby = [channel(cid, fast=1.) for cid in (*x_neighbors, *y_neighbors, 17, 34) if cid is not None]
                readout = pulse([channel(x, slow=100.), channel(y, slow=100.)], nearby, single=100.)
                features = _trigger_card(readout, self.neighbors)['single_pixel_features']
                for axis, expected in (('x', x_neighbors), ('y', y_neighbors)):
                    face = features[axis]
                    adjacent = [face['low'], face['high']]
                    self.assertEqual([item['contact_id'] if item else None for item in adjacent], list(expected))
                    self.assertIsNone(face['fast_ratio'])

    def test_zero_and_missing_are_distinct(self):
        readout = pulse([channel(3, slow=100.), channel(24, slow=100.)],
                        [channel(2, fast=0., flags=('slow_below_threshold',)), channel(4, fast=0.),
                         channel(25, fast=5.)], single=100.)
        features = _trigger_card(readout, self.neighbors)['single_pixel_features']
        self.assertEqual(features['x']['low'], {'contact_id': 2, 'fast_keV_equiv': 0., 'flags': []})
        self.assertEqual(features['x']['fast_ratio'], 0.)
        self.assertEqual(features['y']['low'], {'contact_id': 23, 'fast_keV_equiv': None, 'flags': []})
        self.assertIsNone(features['y']['fast_ratio'])

    def test_fast_losses_are_channel_local(self):
        readout = pulse([channel(3, slow=100.), channel(24, slow=100.)],
                        [channel(2, flags=('fast_adc_saturation', 'slow_below_threshold')),
                         channel(4, flags=('fast_pileup', 'fast_window_truncated')),
                         channel(23, fast=5.), channel(25, fast=-5.)], single=100., flags=('fast_pileup',))
        features = _trigger_card(readout, self.neighbors)['single_pixel_features']
        self.assertEqual(features['x']['low'],
                         {'contact_id': 2, 'fast_keV_equiv': None, 'flags': ['fast_adc_saturation']})
        self.assertEqual(features['x']['high'], {'contact_id': 4, 'fast_keV_equiv': None,
                                                'flags': ['fast_pileup', 'fast_window_truncated']})
        self.assertIsNone(features['x']['fast_ratio'])
        self.assertEqual(features['y']['fast_ratio'], .1)

    def test_other_triggers_have_no_single_pixel_features(self):
        multi = pulse([channel(3, slow=80.), channel(4, slow=20.), channel(24, slow=100.)], [])
        card = _trigger_card(multi, self.neighbors)
        self.assertEqual(card['additional_multi_strip_energy_keV'], 100.)
        self.assertIsNone(card['single_pixel_features'])
        for unqualified in (pulse([channel(3, slow=100.), channel(24, slow=104.)], []),
                            pulse([channel(3, slow=100.), channel(24, slow=100.), channel(34, slow=10.)], [])):
            card = _trigger_card(unqualified, self.neighbors)
            self.assertIsNone(card['energy_keV'])
            self.assertIsNone(card['single_pixel_features'])


if __name__ == '__main__':
    unittest.main()
