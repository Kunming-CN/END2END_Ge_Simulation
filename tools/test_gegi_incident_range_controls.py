"""Focused equal-denominator and shared-scoring checks for the diagnostic adapter."""

import json
import math
import unittest

import numpy as np

import gegi_incident_geometry as geometry
import gegi_incident_range_controls as controls
import gegi_joint_imaging as imaging
from gegi_source_range import AngularScore


class IncidentRangeTests(unittest.TestCase):
    def test_escape_can_use_an_order_excluded_by_observed_sum_absorption(self):
        positions = [[1., 2., 0.], [7., 8., 1.]]
        line = 1332.492
        kinematics = json.loads(json.dumps(geometry.escape_geometry([1000., 177.], [line], positions)))
        pair = dict(pair_index=0, cells=[[1,20],[2,21]], kinematics=kinematics, saved_waveform_positions_mm=positions,
                    original_plane_pairing=dict(nominal_mass=1., orders=[dict(order=[1, 0], nominal_mass=1.)]))
        rows = [dict(original_trigger_id=4891, energy_keV=1177., projected_mass=1., unresolved_mass=0.,
                     archive_record_sha256='frozen', conditional_escape_pairings=[pair])]
        settings = imaging.ResponseSettings()
        absorbed, old = controls.hypothesis_events(rows, settings)
        escaped, new = controls.hypothesis_events(rows, settings, escape_line_keV=line)
        self.assertEqual(absorbed[0].identity, escaped[0].identity)
        self.assertEqual((absorbed[0].unresolved_mass, escaped[0].unresolved_mass), (.5, .5))
        self.assertEqual(next(o['order'] for o in old[0]['orders'] if o['projected_mass']), [1, 0])
        self.assertEqual(next(o['order'] for o in new[0]['orders'] if o['projected_mass']), [0, 1])
        self.assertEqual(new[0]['orders'][1]['original_absorption_order']['nominal_mass'], 1.)

    def test_unsplit_score_equals_split_all_mode_and_reference_kernel(self):
        settings = imaging.ResponseSettings()
        cone = dict(vertex_mm=[0., 0., 1.], axis=[0., 1., 0.], site_separation_mm=3., half_angle_deg=55., prior_weight=.5)
        events = imaging.prepare_events([dict(event_id=20, candidates=[cone]), dict(event_id=21, candidates=[cone]),
                                         dict(event_id=22, candidates=[])], settings)
        split = AngularScore(events[:1], events[1:], settings)
        pooled = AngularScore(events, [], settings, require_both_splits=False)
        point = np.array([[3., 4., 12.]])
        np.testing.assert_allclose(split.score(point, (.25, 'all')), pooled.score(point, (.25, 'all')))
        expect = math.fsum(math.log(.75*math.pi*imaging.event_response(row, point, settings)[0]+.25) for row in events)
        self.assertAlmostEqual(pooled.score(point, (.25, 'all'))[0, 0], expect)
        self.assertEqual(pooled.accounting['unresolved_trigger_mass'], 2.)
        with self.assertRaisesRegex(ValueError, 'Both splits'):
            AngularScore(events, [], settings)


if __name__ == '__main__':
    unittest.main()
