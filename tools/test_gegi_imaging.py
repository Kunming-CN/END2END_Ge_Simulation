"""Small analytic checks for cone direction, ambiguity, depth and event weights."""
import copy
import math
import unittest
import gegi_imaging as G


class ImagingTests(unittest.TestCase):
    def test_known_ninety_degree_scatter(self):
        outgoing = 662/(1+662/G.ELECTRON_REST_KEV)
        first = {'position_mm': [0, 0, 0], 'energy_keV': 662-outgoing}
        second = {'position_mm': [10, 0, 0], 'energy_keV': outgoing}
        c = G.cone(first, second)
        self.assertAlmostEqual(c['half_angle_deg'], 90)
        self.assertEqual(c['axis'], [-1, 0, 0])
        self.assertAlmostEqual(sum(a*b for a, b in zip(c['axis'], [0, 0, 1])), c['cos_theta'])

    def test_invalid_cosine_is_rejected_not_clamped(self):
        self.assertIsNone(G.cone({'position_mm': [0, 0, 0], 'energy_keV': 600},
                                 {'position_mm': [10, 0, 0], 'energy_keV': 1}))

    def test_depth_interpolation_and_out_of_range(self):
        t = {'depth_mm': [-5, 0, 5], 'ctd_ns': [50, 0, -50]}
        self.assertEqual(G.depth_from_timing(25, t), -2.5)
        self.assertIsNone(G.depth_from_timing(60, t))
        self.assertIsNone(G.depth_from_timing(10, {'depth_mm': [-5, 0, 5], 'ctd_ns': [50, 0, 25]}))

    def test_backprojection_preserves_event_weight(self):
        c = {'axis': [0, 0, 1], 'half_angle_deg': 60, 'weight': .5}
        result = G.backproject([c, c], step_deg=10)
        integral = sum(sum(row)*area for row, area in zip(result['values'], result['solid_angle_per_cell_sr_by_row']))
        self.assertAlmostEqual(integral, 1., places=10)

    @staticmethod
    def sample():
        meta = [{'id': i, 'wiring_factor': 1 if i <= 17 else -1} for i in range(1, 35)]
        chans = []
        for i, e, t in ((7, 200., 70.), (11, 462., 80.), (24, 200., 60.), (29, 462., 60.)):
            chans.append({'contact_id': i, 'accepted': True, 'collection_candidate': True, 'reconstructed_energy_keV': e,
                          'final_induced_keV': e*(1 if i <= 17 else -1), 't50_ns': t})
        return {'event_id': 44, 'status': 'completed', 'truth_edep_keV': 662, 'channels': chans}, meta

    def test_truth_and_source_pose_not_used(self):
        event, meta = self.sample()
        table = {'depth_mm': [-5, 0, 5], 'ctd_ns': [-50, 0, 50]}
        original = G.reconstruct_event(event, meta, table, 662)
        changed = copy.deepcopy(event)
        changed.update(truth_edep_keV=1, truth_positions_mm=[[900, 900, 900]], truth_first_site=999)
        self.assertEqual(G.reconstruct_event(changed, meta, table, 662), original)
        self.assertEqual(original['status'], 'accepted')
        self.assertEqual(sum(c['weight'] for c in original['cones']), 1.)
        self.assertAlmostEqual(sum(s['energy_keV'] for s in original['sites']), 662.)

    def test_pairing_ambiguity_retains_all_hypotheses_and_one_event_weight(self):
        event, meta = self.sample()
        for c in event['channels']:
            c['reconstructed_energy_keV'] = 331.
            c['final_induced_keV'] = 331.*(1 if c['contact_id'] <= 17 else -1)
        result = G.reconstruct_event(event, meta, {'depth_mm': [-5, 0, 5], 'ctd_ns': [-50, 0, 50]}, 662)
        self.assertEqual(result['status'], 'accepted')
        self.assertTrue(result['pairing_ambiguous'])
        self.assertTrue(result['ordering_ambiguous'])
        self.assertEqual(result['sites'], [])
        self.assertEqual(len(result['paired_site_hypotheses']), 2)
        self.assertEqual(len(result['cones']), 4)
        self.assertEqual(sum(c['weight'] for c in result['cones']), 1.)
        self.assertEqual({tuple(tuple(s[k] for k in ('x_contact', 'y_contact')) for s in h['sites'])
                          for h in result['paired_site_hypotheses']},
                         {((7, 24), (11, 29)), ((7, 29), (11, 24))})
        event['channels'].reverse()
        self.assertEqual(G.reconstruct_event(event, meta, {'depth_mm': [-5, 0, 5], 'ctd_ns': [-50, 0, 50]}, 662), result)
        image = G.backproject(result['cones'], step_deg=10)
        integral = sum(sum(row)*area for row, area in zip(image['values'], image['solid_angle_per_cell_sr_by_row']))
        self.assertAlmostEqual(integral, 1., places=10)

    @staticmethod
    def pixel_table():
        return {'kind': 'gegi_pixel_simulated_depth_v1', 'per_pixel_calibration': True,
                'timing_method': 'test_last_crossing_v2', 'pixels': {
                    '7:24': {'contact_ids': [7, 24], 'depth_mm': [-5, 0, 5], 'ctd_ns': [-50, 0, 50],
                             'status': 'available_model_approximation'},
                    '11:29': {'contact_ids': [11, 29], 'depth_mm': [-5, 0, 5], 'ctd_ns': [-40, 10, 60],
                              'status': 'available_model_approximation'}}}

    def test_per_pixel_depth_and_metadata_coordinates(self):
        event, meta = self.sample()
        for c in event['channels']:
            c['timing_method'] = 'test_last_crossing_v2'
        for c in meta:
            c['strip_center_mm'] = float(c['id'])
        result = G.reconstruct_event(event, meta, self.pixel_table(), 662)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual([s['position_mm'] for s in result['sites']], [[7., 24., 1.], [11., 29., 1.]])
        self.assertTrue(all(s['method'] == 'strip_centres_and_independent_pixel_timing' for s in result['sites']))

    def test_missing_pixel_never_falls_back(self):
        event, meta = self.sample()
        for c in event['channels']:
            c['timing_method'] = 'test_last_crossing_v2'
        table = self.pixel_table()
        table.update(depth_mm=[-5, 0, 5], ctd_ns=[-50, 0, 50])
        del table['pixels']['11:29']
        result = G.reconstruct_event(event, meta, table, 662)
        self.assertEqual(result['reason'], 'pixel_depth_calibration_missing')
        self.assertEqual(result['cones'], [])

    def test_uncalibrated_alternative_cannot_disambiguate_pairing(self):
        event, meta = self.sample()
        for c in event['channels']:
            c.update(reconstructed_energy_keV=331., timing_method='test_last_crossing_v2')
            c['final_induced_keV'] = 331.*(1 if c['contact_id'] <= 17 else -1)
        result = G.reconstruct_event(event, meta, self.pixel_table(), 662)
        self.assertEqual(result['reason'], 'pixel_depth_calibration_missing')
        self.assertEqual(result['cones'], [])

    def test_invalid_pixel_identity_status_depth_and_timing_are_rejected(self):
        event, meta = self.sample()
        for c in event['channels']:
            c['timing_method'] = 'test_last_crossing_v2'
        for field, value in (('contact_ids', [8, 24]), ('status', 'unavailable_nonmonotonic_or_incomplete'),
                             ('depth_mm', [-5, 0, -1]), ('ctd_ns', [-50, 10, 0])):
            with self.subTest(field=field):
                table = self.pixel_table()
                table['pixels']['7:24'][field] = value
                self.assertEqual(G.reconstruct_event(event, meta, table, 662)['reason'], 'invalid_pixel_depth_calibration')
        event['channels'][0]['timing_method'] = 'first_crossing_v1'
        self.assertEqual(G.reconstruct_event(event, meta, self.pixel_table(), 662)['reason'], 'depth_timing_method_mismatch')

    def test_terminal_collection_rejects_large_induction_peak(self):
        event, meta = self.sample()
        induced = copy.deepcopy(event['channels'][0])
        induced.update(contact_id=8, reconstructed_energy_keV=250., final_induced_keV=0., collection_candidate=False)
        event['channels'].append(induced)
        table = {'depth_mm': [-5, 0, 5], 'ctd_ns': [-50, 0, 50]}
        self.assertEqual(G.reconstruct_event(event, meta, table, 662)['status'], 'accepted')
        induced.update(collection_candidate=True, final_induced_keV=-250.)
        self.assertEqual(G.reconstruct_event(event, meta, table, 662)['status'], 'accepted')

    def test_failed_collecting_channel_cannot_be_silently_dropped(self):
        event, meta = self.sample()
        rejected = copy.deepcopy(event['channels'][0])
        rejected.update(contact_id=8, accepted=False, final_induced_keV=250., reconstructed_energy_keV=None)
        event['channels'].append(rejected)
        table = {'depth_mm': [-5, 0, 5], 'ctd_ns': [-50, 0, 50]}
        self.assertEqual(G.reconstruct_event(event, meta, table, 662)['reason'], 'collecting_strip_readout_rejected')
        rejected['contact_id'] = 17
        self.assertEqual(G.reconstruct_event(event, meta, table, 662)['reason'], 'guard_collection')

    def test_fixed_multiple_lines_use_measured_energy_only(self):
        event, meta = self.sample()
        table = {'depth_mm': [-5, 0, 5], 'ctd_ns': [-50, 0, 50]}
        windows = [{'line_energy_keV': 1173.228, 'half_width_keV': 23.46456},
                   {'line_energy_keV': 1332.492, 'half_width_keV': 26.64984}]
        event['truth_edep_keV'] = 1173.228
        event['emitted_energy_keV'] = 1173.228
        self.assertEqual(G.reconstruct_event(event, meta, table, windows)['reason'], 'outside_configured_photopeak_window')
        scale = 1173.228/662
        for c in event['channels']:
            c['reconstructed_energy_keV'] *= scale
            c['final_induced_keV'] *= scale
        result = G.reconstruct_event(event, meta, table, windows)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['photopeak_matches_keV'], [1173.228])
        self.assertEqual(sum(c['weight'] for c in result['cones']), 1.)
        payload = {'events': [event], 'channels': meta, 'depth_calibration': table, 'counts': {'initial_primaries': 100}}
        G.analyze(payload, {'photopeak_windows': windows, 'source_position_mm': [999, 999, 999]})
        self.assertEqual(payload['imaging']['selection']['photopeak_windows'], windows)
        self.assertEqual(payload['imaging']['initial_primaries'], 100)

    def test_invalid_or_empty_line_windows_fail_explicitly(self):
        for value in (None, [], 0, True, [{'line_energy_keV': 662, 'half_width_keV': -1}],
                      [{'line_energy_keV': 662, 'half_width_keV': 663}]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                G.photopeak_windows(value)


if __name__ == '__main__':
    unittest.main()
