from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import gegi_substrip as S


SOURCE = {'model_sha256': '1' * 64, 'field_cache_sha256': '2' * 64, 'field_precision_bits': 32}
PROFILE = '3' * 64
TIMING = '4' * 64


def geometry():
    return [{'id': cid, 'family': family, 'guard': False, 'strip_center_mm': center}
            for family, ids in [('X', range(1, 6)), ('Y', range(18, 23))]
            for cid, center in zip(ids, (-10., -5., 0., 5., 10.))]


def cal():
    strips = {}
    for cid, sign in [(3, 1), (20, -1)]:
        strips[str(cid)] = {'ratio_direction': sign, 'oriented_ratio_edges': [i / 10 for i in range(10)],
                            'neighbor_contact_ids': [cid - 1, cid + 1], 'strip_pitch_mm': 5.,
                            'strip_center_mm': 0., 'slot_position_mm': [i / 3 for i in range(-4, 5)]}
    return {'kind': S.CALIBRATION_KIND, **SOURCE, 'digital_profile_sha256': PROFILE,
            'position_unit': 'mm', 'ratio_definition': S.RATIO_DEFINITION, 'reference_energy_keV': 500.,
            'slot_count': 9, 'sampled_contact_pairs': [[3, 20]], 'strips': strips}


def digital(x=.21, y=-.61, scale=1.):
    # The signed fast estimates can both be negative. Their difference is used.
    features = {2: (-2.0, None), 3: (0.1, 100.), 4: (-2.0 + 100 * x, None),
                19: (-3.0, None), 20: (0.2, 120.), 21: (-3.0 + 120 * y, None)}
    return {'profile_sha256': PROFILE, 'channels': [
        {'contact_id': cid, 'fast_signal_keV_equiv': fast * scale, 'slow_energy_keV': None if slow is None else slow * scale}
        for cid, (fast, slow) in features.items()]}


def depth_calibration():
    example = cal()
    increasing = [i / 10 for i in range(10)]
    decreasing = [-v for v in increasing]
    example['depth_cfd'] = {'definition': S.CFD_DIFFERENCE_DEFINITION, 'difference_unit': 'ns', 'depth_unit': 'mm',
                            'timing_sha256': TIMING, 'cfd_direction': -1, 'depth_knots_mm': [-1., 0., 1.],
                            'oriented_cfd_knots_ns': [-10., 0., 10.],
                            'ratio_edges_by_strip': {'3': [increasing, increasing, decreasing],
                                                      '20': [decreasing, decreasing, decreasing]}}
    return S.validate_calibration(example)


class SubstripTests(unittest.TestCase):
    def test_signed_normalization_and_slot_order(self):
        for scale in (1., 2.):
            with self.subTest(scale=scale):
                result = S.infer_position(cal(), 3, 20, digital(scale=scale), geometry(), source_identity=SOURCE)
                self.assertEqual(result['status'], 'estimated')
                self.assertEqual(result['calibration_source_status'], 'matching_saved_fields')
                self.assertEqual(result['calibration_pair_coverage'], 'simulated_pair')
                self.assertAlmostEqual(result['x']['ratio'], .21)
                self.assertAlmostEqual(result['y']['ratio'], -.61)
                self.assertEqual((result['x']['slot'], result['y']['slot']), (2, 6))
                self.assertEqual((result['x']['position_mm'], result['y']['position_mm']), (-2 / 3, 2 / 3))

    def test_boundaries_and_outside_have_no_extrapolation(self):
        result = S.infer_position(cal(), 3, 20, digital(.2, -.9), geometry(), source_identity=SOURCE)
        self.assertEqual((result['x']['slot'], result['y']['slot']), (2, 8))
        result = S.infer_position(cal(), 3, 20, digital(0., 0.), geometry(), source_identity=SOURCE)
        self.assertEqual((result['x']['slot'], result['y']['slot']), (0, 0))
        result = S.infer_position(cal(), 3, 20, digital(-.03, -.91), geometry(), source_identity=SOURCE)
        self.assertEqual(result['status'], 'unavailable')
        for axis in ('x', 'y'):
            self.assertEqual(result[axis]['status'], 'ratio_outside_calibration')
            self.assertIsNone(result[axis]['position_mm'])
            self.assertIsNotNone(result[axis]['ratio'])

    def test_transfer_is_labelled_and_mismatches_abstain(self):
        transfer = {**SOURCE, 'field_cache_sha256': None, 'field_precision_bits': 64}
        result = S.infer_position(cal(), 3, 20, digital(), geometry(), source_identity=transfer)
        self.assertEqual(result['calibration_source_status'], 'nominal_transfer')
        self.assertEqual(result['status'], 'estimated')
        self.assertTrue(S.compatible_source(cal(), transfer))
        result = S.infer_position(cal(), 3, 20, digital(), geometry(), source_identity=None)
        self.assertEqual(result['x']['status'], 'source_identity_mismatch')
        self.assertFalse(S.compatible_source(cal(), {'model_sha256': '0' * 64}))
        result = S.infer_position(cal(), 3, 20, {**digital(), 'profile_sha256': 'other'}, geometry(), source_identity=SOURCE)
        self.assertEqual(result['x']['status'], 'digital_profile_mismatch')
        changed = geometry()
        changed[2]['strip_center_mm'] = .001
        result = S.infer_position(cal(), 3, 20, digital(), changed, source_identity=SOURCE)
        self.assertEqual(result['x']['status'], 'strip_geometry_mismatch')
        self.assertEqual(result['status'], 'partial')

    def test_edge_missing_and_uncalibrated_strip_preserve_explicit_result(self):
        data = digital()
        data['channels'][0]['slow_energy_keV'] = 80.
        data['channels'].append({'contact_id': 1, 'fast_signal_keV_equiv': .1})
        result = S.infer_position(cal(), 2, 20, data, geometry(), source_identity=SOURCE)
        self.assertEqual(result['calibration_pair_coverage'], 'unverified_cross_strip_transfer')
        self.assertEqual(result['x']['status'], 'uncalibrated_strip')
        self.assertEqual(result['x']['strip_center_mm'], -5.)
        self.assertIsNotNone(result['x']['ratio'])
        self.assertIsNone(result['x']['position_mm'])
        result = S.infer_position(cal(), 1, 20, data, geometry(), source_identity=SOURCE)
        self.assertEqual(result['x']['status'], 'missing_adjacent_strip')
        result = S.infer_position(cal(), 3, 20, data, [c for c in geometry() if c['id'] != 2], source_identity=SOURCE)
        self.assertEqual(result['x']['status'], 'missing_adjacent_strip')
        data['channels'][2]['fast_signal_keV_equiv'] = None
        result = S.infer_position(cal(), 3, None, data, geometry(), source_identity=SOURCE)
        self.assertEqual(result['x']['status'], 'neighbor_or_collector_signal_unavailable')
        self.assertEqual(result['y']['status'], 'collector_unavailable')

    def test_loaded_digest_and_strict_edges(self):
        with TemporaryDirectory() as local:
            path = Path(local) / 'calibration.json'
            data = json.dumps(cal()).encode()
            path.write_bytes(data)
            self.assertEqual(S.load_calibration(path)['calibration_sha256'], hashlib.sha256(data).hexdigest())
        bad = deepcopy(cal())
        bad['strips']['3']['oriented_ratio_edges'][2] = .1
        with self.assertRaisesRegex(ValueError, 'Invalid GeGI substrip table'):
            S.validate_calibration(bad)

    def test_scalar_signed_integer_encoding_and_slot_lookup(self):
        for ratio, code in ((-.01, 100), (-.19, 99), (.01, 100), (.19, 101)):
            with self.subTest(ratio=ratio):
                self.assertEqual(S.encode_ratio(ratio, scale=10, offset=100), code)
        edges = tuple(range(95, 105))
        self.assertEqual(S.lookup_encoded_slot(95, edges), 0)
        self.assertEqual(S.lookup_encoded_slot(96, edges), 1)
        self.assertEqual(S.lookup_encoded_slot(104, edges), 8)
        self.assertIsNone(S.lookup_encoded_slot(94, edges))
        self.assertIsNone(S.lookup_encoded_slot(105, edges))
        with self.assertRaisesRegex(ValueError, 'ten increasing integer edges'):
            S.lookup_encoded_slot(100, edges[::-1])

    def test_measured_cfd_depth_and_conditioned_polarity_abstention(self):
        features = digital()
        features['timing_sha256'] = TIMING
        by_id = {c['contact_id']: c for c in features['channels']}
        by_id[3]['preamp_cfd50_ns'] = 50.
        by_id[20]['preamp_cfd50_ns'] = 55.
        result = S.infer_position(depth_calibration(), 3, 20, features, geometry(), source_identity=SOURCE,
                                  mode='cfd_conditioned')
        self.assertEqual(result['depth'], {'status': 'estimated', 'cfd_x_ns': 50., 'cfd_y_ns': 55.,
                                          'cfd_difference_ns': -5., 'position_mm': .5})
        self.assertEqual(result['x']['status'], 'ambiguous_depth_polarity')
        self.assertIsNone(result['x']['position_mm'])
        self.assertEqual(result['y']['slot'], 6)
        self.assertEqual(result['status'], 'partial')
        pooled = S.infer_position(depth_calibration(), 3, 20, features, geometry(), source_identity=SOURCE)
        self.assertEqual(pooled['status'], 'estimated')
        self.assertEqual(pooled['depth'], result['depth'])

    def test_depth_checks_timing_profile_and_never_extrapolates(self):
        features = digital()
        by_id = {c['contact_id']: c for c in features['channels']}
        by_id[3]['preamp_cfd50_ns'] = 50.
        by_id[20]['preamp_cfd50_ns'] = 65.
        result = S.infer_position(depth_calibration(), 3, 20, features, geometry(), source_identity=SOURCE,
                                  mode='cfd_conditioned')
        self.assertEqual(result['depth']['status'], 'digital_timing_profile_mismatch')
        features['timing_sha256'] = TIMING
        result = S.infer_position(depth_calibration(), 3, 20, features, geometry(), source_identity=SOURCE,
                                  mode='cfd_conditioned')
        self.assertEqual(result['depth']['status'], 'cfd_difference_outside_calibration')
        self.assertEqual(result['depth']['cfd_difference_ns'], -15.)
        self.assertIsNone(result['depth']['position_mm'])
        self.assertEqual(result['x']['status'], 'depth_condition_unavailable')


if __name__ == '__main__':
    unittest.main()
