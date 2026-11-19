import unittest

from gegi_event_energy import estimate_event_energy
import gegi_pulse_stream as stream
from test_gegi_pulse_stream import prepare, pulse


def output(step_ids, energies, *, per_channel=None, flags=(), legacy=None, pair=None):
    per_channel = per_channel or {}
    return {'step_contact_ids': step_ids, 'contact_ids': pair, 'slow_energy_keV': legacy,
            'flags': flags, 'channels': [{'contact_id': cid, 'slow_energy_keV': energies.get(cid),
                                        'flags': per_channel.get(cid, [])} for cid in range(1, 35)]}


class EventEnergyTest(unittest.TestCase):
    def test_qualified_single_preserves_exact_nominal_mean(self):
        a, b = 120.00132583, 119.99312929
        e = (a + b) / 2
        result = estimate_event_energy(output([3, 24], {3: a, 24: b}, legacy=e, pair=[3, 24]))
        self.assertEqual(result['energy_keV'], e)
        self.assertTrue(result['retains_legacy_single'])
        self.assertEqual([result['x_sum_keV'], result['y_sum_keV']], [a, b])
        self.assertEqual([result['x_count'], result['y_count']], [1, 1])
        self.assertTrue(result['closure_passed'])

    def test_multi_strip_average_never_adds_both_faces(self):
        result = estimate_event_energy(output([2, 3, 18, 22, 23],
                                               {2: 45., 3: 55., 18: 50., 22: 30., 23: 20.},
                                               flags=['unresolved_strip_multiplicity']))
        self.assertEqual(result['status'], 'qualified')
        self.assertEqual(result['energy_keV'], 100.)
        self.assertEqual([result['x_count'], result['y_count']], [2, 3])
        self.assertEqual(result['x_minus_y_keV'], 0.)
        self.assertFalse(result['retains_legacy_single'])

    def test_guard_wired_step_and_raw_clipping_remain_unavailable(self):
        guard = estimate_event_energy(output([2, 17, 29], {2: 90., 17: 10., 29: 100.}))
        self.assertEqual(guard['guard_contact_ids'], [17])
        self.assertIn('guard_collection', guard['flags'])
        self.assertIsNone(guard['energy_keV'])
        clipped = estimate_event_energy(output([2, 29], {2: 100., 29: 100.}, flags=['step_adc_saturation']))
        self.assertIn('step_adc_saturation', clipped['flags'])
        self.assertIsNone(clipped['energy_keV'])

    def test_required_plateau_failures_withhold_the_whole_face(self):
        for why in ('slow_pileup', 'slow_adc_saturation', 'slow_window_truncated', 'slow_plateau_unsettled'):
            with self.subTest(flag=why):
                result = estimate_event_energy(output([2, 3, 29], {2: 45., 3: 55., 29: 100.},
                                                      per_channel={2: [why]}))
                self.assertIsNone(result['x_sum_keV'])
                self.assertEqual(result['x_usable_count'], 1)
                self.assertEqual(result['y_sum_keV'], 100.)
                self.assertIsNone(result['closure_passed'])
                self.assertIsNone(result['energy_keV'])
                self.assertEqual(result['missing_required_strips'], [{'contact_id': 2, 'reasons': [why]}])

    def test_other_rise_interference_and_unattributed_slow_hits(self):
        event = output([2, 3, 29], {2: 45., 3: 55., 29: 100.}, per_channel={21: ['slow_pileup']})
        result = estimate_event_energy(event)
        self.assertEqual(result['energy_keV'], 100.)
        self.assertEqual(result['uninvolved_slow_interference_contact_ids'], [21])
        unknown = estimate_event_energy(output([2, 3, 29], {2: 45., 3: 55., 29: 100., 21: 15.}))
        self.assertIsNone(unknown['energy_keV'])
        self.assertEqual(unknown['stray_slow_contact_ids'], [21])
        self.assertIn('unattributed_slow_hits', unknown['flags'])
        legacy = estimate_event_energy(output([2, 29], {2: 100., 29: 100., 21: 15.},
                                               legacy=100., pair=[2, 29]))
        self.assertEqual(legacy['energy_keV'], 100.)
        self.assertEqual(legacy['stray_slow_contact_ids'], [21])

    def test_threshold_face_closure_and_unavailable_channel(self):
        equal = estimate_event_energy(output([2, 3, 29], {2: 5., 3: 45., 29: 52.}))
        self.assertEqual(equal['energy_keV'], 51.)
        self.assertEqual(equal['closure_tolerance_keV'], 2.)
        small = estimate_event_energy(output([2, 3, 29], {2: 4.999, 3: 45., 29: 50.}))
        self.assertIn('slow_below_collection_threshold', small['flags'])
        mismatch = estimate_event_energy(output([2, 3, 29], {2: 5., 3: 45., 29: 52.001}))
        self.assertIn('face_energy_mismatch', mismatch['flags'])
        self.assertFalse(mismatch['closure_passed'])
        missing = output([2, 29], {2: 45., 29: 45.})
        missing['channels'] = [row for row in missing['channels'] if row['contact_id'] != 29]
        self.assertIn('slow_channel_unavailable', estimate_event_energy(missing)['flags'])

    def test_adc_merged_trigger_has_one_aggregate_energy(self):
        a = prepare(pulse((4, 20), 120.))
        b = prepare(pulse((8, 28), 90.))
        rows = stream.reconstruct(*stream.acquire([(a, 0., 1.), (b, 0., 1.)]))['events']
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['slow_energy_keV'])
        event = estimate_event_energy(rows[0])
        self.assertEqual([event['x_count'], event['y_count']], [2, 2])
        self.assertAlmostEqual(event['energy_keV'], 210., delta=.15)


if __name__ == '__main__':
    unittest.main()
