"""Deterministic scientific checks for finite-vertex conditional reconstruction."""
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

import gegi_joint_imaging as G


def candidate(first=(0, 0, 0), axis=(1, 0, 0), theta=math.pi/2, separation=20., prior=1., covariance=None):
    a = np.asarray(axis, float)
    a /= np.linalg.norm(a)
    result = {'vertex_mm': list(first), 'axis': a.tolist(), 'theta_rad': theta,
              'site_separation_mm': separation, 'prior_weight': prior}
    if covariance is not None:
        result['position_covariance_mm2'] = np.asarray(covariance).tolist()
    return result


def synthetic_events(source, count=48, start_id=0):
    """Exact, varied finite-vertex geometry; deterministic and not a detector MC."""
    source = np.asarray(source, float)
    result = []
    for i in range(count):
        first = np.array([12*math.cos(i*1.618), 11*math.sin(i*1.618), 3*math.sin(i*.81)])
        axis = np.array([math.cos(i*.719), math.sin(i*.719), .7*math.cos(i*.527)])
        axis /= np.linalg.norm(axis)
        ray = source-first
        ray /= np.linalg.norm(ray)
        theta = math.acos(np.clip(axis @ ray, -1, 1))
        c = candidate(first, axis, theta, covariance=np.zeros((2, 3, 3)))
        result.append({'event_id': start_id+i, 'pulse_group_id': 0, 'energy_keV': 662., 'candidates': [c]})
    return G.prepare_events(result)


class JointImagingTests(unittest.TestCase):
    def test_density_integrates_over_observed_angle_without_image_window(self):
        theta = np.linspace(0, math.pi, 15001)
        for alpha in (.01, .4, 1.4, math.pi-.01):
            for sigma in (.02, .3, 2., 1e5):
                values = np.array([G.angular_density(t, alpha, sigma) for t in theta])
                self.assertAlmostEqual(float(np.trapezoid(values, theta)), 1., delta=1e-5)

    def test_finite_vertex_not_origin_ray(self):
        source = np.array([[30., -10., 40.]])
        first = [15., 5., -4.]
        c = candidate(first, [1, 0, 0])
        prepared = G.prepare_candidate(c)
        angle, _ = G.geometric_angle_and_variance(prepared, source)
        ray = source[0]-first
        expected = math.acos(prepared.axis @ (ray/np.linalg.norm(ray)))
        far_field = math.acos(prepared.axis @ (source[0]/np.linalg.norm(source[0])))
        self.assertAlmostEqual(angle[0], expected, places=13)
        self.assertGreater(abs(angle[0]-far_field), .2)

    def test_position_covariance_matches_independent_finite_difference(self):
        first = np.array([3., -7., 2.])
        axis = np.array([.4, -.7, .2]); axis /= np.linalg.norm(axis)
        covariance = np.array([np.diag([.2, .4, .05]), np.diag([.3, .2, .07])])
        raw = candidate(first, axis, separation=17., covariance=covariance)
        prepared = G.prepare_candidate(raw)
        source = np.array([[32., 9., 42.]])
        _, actual = G.geometric_angle_and_variance(prepared, source)
        sites = np.concatenate((first, first-17*axis))
        def alpha(s):
            a = s[:3]-s[3:]; a /= np.linalg.norm(a)
            u = source[0]-s[:3]; u /= np.linalg.norm(u)
            return math.acos(a @ u)
        derivatives = []
        for i in range(6):
            d = np.zeros(6); d[i] = 1e-4
            derivatives.append((alpha(sites+d)-alpha(sites-d))/(2e-4))
        expected = sum(np.array(derivatives[k:k+3]) @ covariance[k//3] @ np.array(derivatives[k:k+3]) for k in (0, 3))
        self.assertAlmostEqual(actual[0], expected, delta=expected*1e-8)

    def test_rotation_and_translation_invariance(self):
        angle = .71
        rotation = np.array([[math.cos(angle), -math.sin(angle), 0], [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
        shift = np.array([80., -90., 33.])
        raw = candidate([2, 3, 4], [1, 2, -1], covariance=[np.diag([2., 3., .5])]*2)
        c1 = G.prepare_candidate(raw)
        points = np.array([[20, 30, 40], [-20, 10, 40]], float)
        raw2 = copy.deepcopy(raw)
        raw2['vertex_mm'] = (rotation @ c1.vertex+shift).tolist()
        raw2['axis'] = (rotation @ c1.axis).tolist()
        raw2['position_covariance_mm2'] = [rotation @ c @ rotation.T for c in c1.position_covariance]
        c2 = G.prepare_candidate(raw2)
        np.testing.assert_allclose(G.candidate_response(c1, points), G.candidate_response(c2, points @ rotation.T+shift), rtol=1e-12, atol=1e-14)

    def test_strip_pitch_broadens_short_lever_arms_and_poles_not_zero(self):
        points = np.array([[0., 30., 40.]])
        short = G.prepare_candidate(candidate(separation=5.))
        long = G.prepare_candidate(candidate(separation=30.))
        self.assertGreater(G.geometric_angle_and_variance(short, points)[1][0],
                           G.geometric_angle_and_variance(long, points)[1][0])
        pole = G.prepare_candidate(candidate(axis=(0, 0, 1)))
        self.assertGreater(G.geometric_angle_and_variance(pole, np.array([[0., 0., 40.]]))[1][0], 0)

    def test_field_of_view_overlap_exact_for_bad_cone(self):
        event = G.prepare_events([{'event_id': 7, 'candidates': [candidate(axis=(0, 0, -1), theta=.02)]}])[0]
        _, p1 = G.plane_grid(40, 4, 40)
        _, p2 = G.plane_grid(80, 4, 40)
        mask = (abs(p2[:, 0]) < 40) & (abs(p2[:, 1]) < 40)
        np.testing.assert_array_equal(G.event_response(event, p1), G.event_response(event, p2)[mask])
        self.assertLess(G.event_response(event, p1).max(), G.BACKGROUND_PER_RAD*1e-8)

    def test_candidate_marginalization_and_unresolved_mass(self):
        first = candidate(theta=.7, prior=.25)
        second = candidate(theta=1.4, prior=.5)
        events = G.prepare_events([{'event_id': 1, 'candidates': [first, second]}])
        p = np.array([[20., 30., 40.]])
        expected = .25*G.candidate_response(events[0].candidates[0], p)+.5*G.candidate_response(events[0].candidates[1], p)+.25/math.pi
        np.testing.assert_allclose(G.event_response(events[0], p), expected)
        self.assertEqual(events[0].unresolved_mass, .25)
        duplicated = {'event_id': 1, 'candidates': [candidate(prior=.6), candidate(prior=.6)]}
        with self.assertRaises(ValueError):
            G.prepare_events([duplicated])

    def test_truth_and_acquisition_labels_never_change_response(self):
        base = {'event_id': 44, 'energy_keV': 662., 'candidates': [candidate()]}
        changed = copy.deepcopy(base)
        changed.update(source_group='correct-answer', truth_position_mm=[90, 100, 40], truth_order=[9, 8], truth_edep_keV=1)
        points = np.array([[20, 30, 40]], float)
        np.testing.assert_array_equal(G.response_matrix(G.prepare_events([base]), points),
                                      G.response_matrix(G.prepare_events([changed]), points))

    def test_energy_and_coordinate_consistency_fail_closed(self):
        raw = candidate()
        raw['second_vertex_mm'] = [20., 0., 0.]
        with self.assertRaisesRegex(ValueError, 'axis'):
            G.prepare_candidate(raw)
        raw = candidate()
        raw.update(scatter_energy_keV=600., absorbed_energy_keV=62.)
        with self.assertRaisesRegex(ValueError, 'Energies'):
            G.prepare_candidate(raw)
        raw = candidate(covariance=[np.diag([-1, 1, 1])]*2)
        with self.assertRaisesRegex(ValueError, 'semidefinite'):
            G.prepare_candidate(raw)

    def test_energy_uncertainty_propagates_with_units(self):
        e1, e2 = 200., 462.
        cosine = 1-G.ELECTRON_REST_KEV*(1/e2-1/(e1+e2))
        raw = candidate(theta=math.acos(cosine))
        raw.update(scatter_energy_keV=e1, absorbed_energy_keV=e2, energy_sigma_keV=[2., 3.])
        c = G.prepare_candidate(raw)
        def theta(a, b):
            return math.acos(1-G.ELECTRON_REST_KEV*(1/b-1/(a+b)))
        d1 = (theta(e1+.001, e2)-theta(e1-.001, e2))/.002
        d2 = (theta(e1, e2+.001)-theta(e1, e2-.001))/.002
        self.assertAlmostEqual(c.energy_angle_variance, d1*d1*4+d2*d2*9, delta=1e-12)

    def test_conditional_em_monotonic_mass_conservation_and_outlier(self):
        a = np.array([[8., .001], [6., .002], [.002, 7.], [.001, 5.], [1e-40, 1e-40]])
        fit = G.fit_conditional_mixture(a, iterations=100)
        self.assertTrue(np.all(np.diff(fit['log_likelihood']) >= -1e-10))
        self.assertAlmostEqual(fit['background_fraction']+fit['source_mass'].sum(), 1.)
        self.assertGreater(fit['event_outlier_probability'][-1], .9999)
        self.assertTrue(np.all(fit['source_mass'] > .25))
        self.assertIsNone(fit['activity_bq'])

    def test_exact_two_source_geometry_localizes_both_without_labels(self):
        events = synthetic_events([-25, 0, 40], 48)+synthetic_events([25, 0, 40], 48, 100)
        ticks, points = G.plane_grid(50, 2, 40)
        settings = G.ResponseSettings(angular_nuisance_sigma_deg=2.)
        a = G.response_matrix(events, points, settings)
        fit = G.fit_conditional_mixture(a, iterations=70)
        peaks = G.blind_peaks(fit['source_mass'], points, 20)
        xs = sorted(p['position_mm'][0] for p in peaks)
        self.assertAlmostEqual(xs[0], -25, delta=2.)
        self.assertAlmostEqual(xs[1], 25, delta=2.)
        self.assertLess(fit['background_fraction'], .05)

    def test_common_apex_has_no_range_information(self):
        events = G.prepare_events([{'event_id': i, 'candidates': [candidate(axis=a, theta=.9+i*.2,
                     covariance=np.zeros((2, 3, 3)))]} for i, a in enumerate([(1, 0, 1), (1, 2, 0), (-1, 2, 1)])])
        points = np.array([[20, 0, 40], [-20, 0, 40], [0, 20, 40]], float)
        a, b = G.response_matrix(events, points), G.response_matrix(events, points*5)
        np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-14)
        self.assertAlmostEqual(G.fit_conditional_mixture(a)['log_likelihood'][-1],
                               G.fit_conditional_mixture(b)['log_likelihood'][-1], places=11)

    def test_spectral_layers_source_blind_and_no_count_equalization(self):
        records = [{'event_id': i, 'energy_keV': energy, 'candidates': []}
                   for i, energy in enumerate([662., 661., 1173., 1332., 800.])]
        masks = G.spectral_membership(G.prepare_events(records))
        self.assertEqual([int(m.sum()) for m in masks.values()], [2, 1, 1, 1])
        np.testing.assert_array_equal(sum(m.astype(int) for m in masks.values()), np.ones(5))

    def test_memory_bound_rejects_dense_overallocation(self):
        settings = G.ResponseSettings(maximum_matrix_bytes=16)
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            G.response_matrix(synthetic_events([0, 0, 40], 2), np.ones((4, 3)), settings)

    def test_blind_peak_reporting_does_not_invent_sources_from_flat_map_or_shoulder(self):
        _, points = G.plane_grid(60., 4., 40.)
        self.assertEqual(G.blind_peaks(np.ones(len(points)), points), [])
        gaussian = np.exp(-((points[:, 0]-2)**2+(points[:, 1]-2)**2)/(2*25**2))
        self.assertEqual(len(G.blind_peaks(gaussian, points)), 1)

    @staticmethod
    def make_derivative(root):
        root = Path(root)
        (root/'chunks').mkdir()
        records = []
        for i, energy in enumerate([662., 800., 1173., 1332., None]):
            records.append({'original_identity': {'campaign_initial_id': i+100, 'pulse_group_id': 0,
                                                   'source_group': 'untrusted-label'},
                            'native_status': 'native_failed' if energy is None else 'completed',
                            'reconstruction': {'energy_keV': energy, 'candidates': [] if energy is None else [candidate()]}})
        with gzip.open(root/'chunks/000.jsonl.gz', 'wt', encoding='utf-8') as stream:
            stream.write(''.join(json.dumps(row)+'\n' for row in records))
        def write(name, obj):
            path = root/name
            path.write_text(json.dumps(obj), encoding='utf-8')
            return hashlib.sha256(path.read_bytes()).hexdigest()
        digest = G._file_sha(root/'chunks/000.jsonl.gz')
        receipt_sha = write('chunks/000.json', {'sha256': digest, 'counts': {'pulse_groups': 5}})
        summary_sha = write('summary.json', {'counts': {'pulse_groups': 5},
                            'original_initial_denominators': {'independent_acquisition': {'initials': 1000}}, 'limitations': ['conditional']})
        identity_sha = write('identity.json', {'kind': 'fixture'})
        write('COMPLETE.json', {'status': 'completed_conditional_reconstruction',
                               'chunks': [{'chunk_index': 0, 'data_sha256': digest, 'receipt_sha256': receipt_sha}],
                               'summary_sha256': summary_sha, 'identity_sha256': identity_sha})

    def test_saved_derivative_adapter_uses_uniform_energy_windows_and_preserves_census(self):
        scratch = Path(__file__).resolve().parents[1]/'.local'
        with tempfile.TemporaryDirectory(prefix='joint-imaging-test-', dir=scratch) as folder:
            assert Path(folder).resolve().is_relative_to(scratch.resolve())
            self.make_derivative(folder)
            records, accounting = G.read_reconstructed(folder)
            self.assertEqual([r['campaign_initial_id'] for r in records], [100, 102, 103])
            self.assertEqual(accounting['counts']['nonzero_pulse_groups'], 5)
            self.assertEqual(accounting['counts']['candidate_groups_outside_measured_energy_windows'], 1)
            self.assertEqual(accounting['counts']['native_failed_groups'], 1)
            self.assertEqual(accounting['original_initial_denominators']['independent_acquisition']['initials'], 1000)
            self.assertTrue(all('source_group' not in r for r in records))
            self.assertFalse(accounting['selection']['selected_groups_are_validated_recovered_events'])

    def test_saved_derivative_adapter_rejects_changed_chunks(self):
        scratch = Path(__file__).resolve().parents[1]/'.local'
        with tempfile.TemporaryDirectory(prefix='joint-imaging-test-', dir=scratch) as folder:
            assert Path(folder).resolve().is_relative_to(scratch.resolve())
            self.make_derivative(folder)
            with (Path(folder)/'chunks/000.jsonl.gz').open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'Changed saved-signal chunk'):
                G.read_reconstructed(folder)


if __name__ == '__main__':
    unittest.main()
