"""Pure grid tests only; importing the pilot never imports or launches Julia."""
import unittest
import gegi_guard_grid_pilot as G


class GridTests(unittest.TestCase):
    def test_fixed_shapes_and_all_original_ticks(self):
        original = [G.float32(i/1000) for i in range(240)]
        endpoints = [.1202, .1204, .1208]
        for sub, expected in ((8, [256, 255, 88]), (16, [278, 277, 88])):
            x = G.graded_axis(original, endpoints, sub, negative_parity=True)
            y = G.graded_axis(original, endpoints, sub)
            self.assertEqual([len(x['ticks_m']), len(y['ticks_m']), 88], expected)
            self.assertTrue(set(original).issubset(x['ticks_m']))
            self.assertEqual(len(x['ticks_m']) % 2, 0)
            self.assertEqual(x['subdivisions_by_original_interval_zero_based']['120'], sub)
            self.assertEqual(x['subdivisions_by_original_interval_zero_based']['119'], sub//2)
            self.assertEqual(x['subdivisions_by_original_interval_zero_based']['121'], sub//2)
            self.assertLessEqual(expected[0]*expected[1]*expected[2], 7_000_000)

    def test_edge_taper_and_multicell_inputs_are_rejected(self):
        ticks = [float(i) for i in range(240)]
        with self.assertRaisesRegex(ValueError, 'leave original'):
            G.graded_axis(ticks, [.1, .2, .3], 16, negative_parity=True)
        with self.assertRaisesRegex(ValueError, 'share one'):
            G.graded_axis(ticks, [50.1, 51.1, 50.4], 8)

    def test_hash_is_float32_exact_and_axis_order_sensitive(self):
        x, y, z = [[G.float32(v) for v in values] for values in ([0, .1, 1], [0, .3, 1], [0, 1])]
        self.assertEqual(G.grid_hash([x, y, z]), G.grid_hash([list(x), list(y), list(z)]))
        self.assertNotEqual(G.grid_hash([x, y, z]), G.grid_hash([y, x, z]))
        x[1] = G.float32(.2)
        self.assertNotEqual(G.grid_hash([x, y, z]), G.grid_hash([[0, G.float32(.1), 1], y, z]))


if __name__ == '__main__':
    unittest.main()
