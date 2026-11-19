import unittest

import numpy as np

from gegi_window_activity import analyze_window


class WindowActivityTest(unittest.TestCase):
    def setUp(self):
        self.times = np.arange(-80, 481, 20)
        self.codes = np.zeros((34, len(self.times)), dtype=np.int16)
        self.baseline = np.zeros(34)

    def step(self, contacts, first_ns, codes):
        self.codes[np.ix_(contacts, self.times >= first_ns)] += codes

    def test_two_rearmed_coincident_groups_use_original_step_times(self):
        self.step([0, 17], 20, 1000)
        self.step([0, 17], 220, 1250)
        activity = analyze_window(self.codes, self.baseline, self.times, 'standard')
        self.assertEqual(activity['time_ns'], self.times[2:].tolist())
        self.assertEqual(activity['coincidence_threshold_keV'], 5.)
        self.assertEqual(activity['quiet_threshold_keV'], 3.)
        self.assertEqual(activity['quiet_samples'], 3)
        self.assertEqual([(g['trigger_reference_ns'], g['first_coincident_ns']) for g in activity['groups']],
                         [(0., 20.), (200., 220.)])
        self.assertTrue(all(g['rearm_visible'] and g['right_quiet_visible'] for g in activity['groups']))

    def test_single_face_activity_is_never_coincident(self):
        self.step([0], 20, 1000)
        activity = analyze_window(self.codes, self.baseline, self.times, 'low-energy')
        self.assertEqual(activity['coincidence_threshold_keV'], 4.)
        self.assertGreater(max(activity['x_change_keV']), activity['coincidence_threshold_keV'])
        self.assertEqual(max(activity['y_change_keV']), 0.)
        group, = activity['groups']
        self.assertFalse(group['coincident'])
        self.assertIsNone(group['first_coincident_ns'])

    def test_window_boundaries_can_hide_quiet_history(self):
        self.step([0, 17], -40, 1000)
        self.step([0, 17], 460, 1000)
        activity = analyze_window(self.codes, self.baseline, self.times, 'standard')
        first, last = activity['groups']
        self.assertEqual(first['first_active_ns'], activity['time_ns'][0])
        self.assertFalse(first['rearm_visible'])
        self.assertTrue(first['right_quiet_visible'])
        self.assertTrue(last['rearm_visible'])
        self.assertEqual(last['last_active_ns'], activity['time_ns'][-1])
        self.assertFalse(last['right_quiet_visible'])


if __name__ == '__main__':
    unittest.main()
