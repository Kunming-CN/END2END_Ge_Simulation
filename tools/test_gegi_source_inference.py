"""Targeted source-compatibility checks; synthetic histograms, no physics calls."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

import gegi_source_inference as G

ROOT = Path(__file__).resolve().parents[1]


def spectrum(peaks=(), background=5):
    counts = [background]*2000
    for energy in peaks:
        counts[int(energy//2)] += 200
    return {'edges_keV': [2.*i for i in range(2001)], 'counts': counts}


class SpectrumInference(unittest.TestCase):
    def test_binomial_tail_matches_small_exact_distribution(self):
        self.assertAlmostEqual(math.exp(G.log_binomial_upper_tail(8, 10, .5)), 56/1024, places=14)
        self.assertEqual(G.log_binomial_upper_tail(0, 0, .4), 0.)
        self.assertTrue(math.isfinite(G.log_binomial_upper_tail(4000, 4000, .4)))

    def test_flat_continuum_and_empty_spectrum_support_no_source(self):
        for background in (0, 5):
            result = G.infer_spectrum(spectrum(background=background))
            self.assertEqual(result['status'], 'inconclusive')
            self.assertEqual(result['candidate_components'], [])
            self.assertTrue(all(not x['supported'] for x in result['line_evidence']))

    def test_single_662_line_stays_ambiguous_and_ignores_source_metadata(self):
        data = spectrum([662.]); baseline = G.infer_spectrum(data)
        self.assertEqual(baseline['status'], 'single_line_ambiguous')
        for label in ('Cs137', 'Co60', 'unknown', None):
            altered = dict(data, source=label, truth_position_mm=[999, -7, 81], truth_energy_keV=1332.492)
            self.assertEqual(G.infer_spectrum(altered), baseline)
        self.assertIn('Monoenergetic', baseline['candidate_components'][0]['alternatives'][1])

    def test_co60_requires_both_lines_and_retains_mixed_ambiguity(self):
        single = G.infer_spectrum(spectrum([1173.228]))
        self.assertEqual(single['status'], 'inconclusive')
        doublet = G.infer_spectrum(spectrum([1173.228, 1332.492]))
        self.assertEqual(doublet['status'], 'doublet_compatibility')
        self.assertEqual(doublet['candidate_components'][0]['id'], 'co60_compatible')
        mixed = G.infer_spectrum(spectrum(G.LINES))
        self.assertEqual(mixed['status'], 'mixed_line_compatibility')
        self.assertEqual(len(mixed['candidate_components']), 2)

    def test_one_sided_continuum_edge_does_not_pass_both_sidebands(self):
        data = spectrum(background=0)
        for i in range(300, 334):
            data['counts'][i] = 100
        evidence = G.line_evidence(data, 661.657)
        self.assertTrue(evidence['sideband_comparisons']['right']['passes_screen'])
        self.assertFalse(evidence['sideband_comparisons']['left']['passes_screen'])
        self.assertFalse(evidence['supported'])

    def test_peak_must_match_reference_and_counts_cannot_be_negative(self):
        shifted = spectrum([667.])
        self.assertFalse(G.line_evidence(shifted, 661.657)['supported'])
        malformed = spectrum(); malformed['counts'][1] = -1
        with self.assertRaises(ValueError):
            G.infer_spectrum(malformed)
        malformed = spectrum(); malformed['edges_keV'][1] = 2.1
        with self.assertRaises(ValueError):
            G.infer_spectrum(malformed)

    def test_pooling_keeps_counts_and_never_rescales_for_source_yield(self):
        first, second = spectrum([662.]), spectrum([1173.228, 1332.492])
        pooled = G.pooled_spectrum([first, second])
        self.assertEqual(sum(pooled['counts']), sum(first['counts'])+sum(second['counts']))
        self.assertEqual(G.infer_spectrum(pooled)['status'], 'mixed_line_compatibility')

    def test_assumed_plane_peak_is_never_recovered_range(self):
        plane = {'plane_z_mm': 40., 'x_mm': [-1., 1.], 'y_mm': [-1., 1.]}
        result = G.distance_assessment({'plane': {'peaks': [{'row': 0, 'column': 1, 'x_mm': 1., 'y_mm': -1.}]}}, plane)
        self.assertIsNone(result['distance_mm'])
        self.assertTrue(result['plane_peak_boundary'])
        self.assertEqual(result['assumed_plane_z_mm'], 40.)


class SavedReport(unittest.TestCase):
    def setUp(self):
        scratch = ROOT/'.local/gegi-source-inference-tests'; scratch.mkdir(exist_ok=True, parents=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch); self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self):
        analysis = self.folder/'analysis'; analysis.mkdir()
        plan = self.folder/'plan.json'; criteria = {'plane_z_mm': 40.}
        plan.write_bytes(G.encoded({'analysis_criteria': criteria, 'truth_source': 'unused-secret'}))
        evaluations = {'direction': {'status': 'fail'}, 'plane': {'status': 'fail', 'peaks': [{'row': 0, 'column': 0}]}}
        plane = {'plane_z_mm': 40., 'x_mm': [-1., 1.], 'y_mm': [-1., 1.]}
        summary = {'plan_sha256': G.sha(plan), 'criteria': criteria, 'mixtures': {},
            'groups': {'not_a_source_label': {'spectrum': spectrum([1173.228, 1332.492]),
                       'evaluations': evaluations, 'counts': {'initial_primaries': 100, 'native_failed_groups': 1}}}}
        maps = {'criteria': criteria, 'groups': {'not_a_source_label': {'all': {'plane': plane}}}, 'mixtures': {}}
        (analysis/'summary.json').write_bytes(G.encoded(summary))
        (analysis/'maps.json').write_bytes(G.encoded(maps))
        (analysis/'cones.jsonl').write_bytes(b'')
        manifest = {'kind': 'gegi_campaign_analysis_v1', 'status': 'complete', 'plan_sha256': G.sha(plan),
            'files': {p.name: {'sha256': G.sha(p), 'bytes': p.stat().st_size} for p in analysis.iterdir()}}
        (analysis/'manifest.json').write_bytes(G.encoded(manifest))
        return analysis, plan

    def test_saved_report_preserves_inputs_binds_sources_and_keeps_failures(self):
        analysis, plan = self.fixture()
        before = {p: (G.sha(p), p.stat().st_mtime_ns) for p in [*analysis.iterdir(), plan]}
        output = self.folder/'diagnostic'
        report = G.build_report(analysis, plan, output)
        self.assertEqual(before, {p: (G.sha(p), p.stat().st_mtime_ns) for p in before})
        group = report['groups']['not_a_source_label']
        self.assertEqual(group['spectral_inference']['status'], 'doublet_compatibility')
        self.assertEqual(group['imaging_evaluation']['direction']['status'], 'fail')
        self.assertEqual(group['census']['native_failed_groups'], 1)
        self.assertIsNone(group['distance']['distance_mm'])
        seal = G.read(output/'manifest.json')
        self.assertEqual(seal['files']['report.json']['sha256'], G.sha(output/'report.json'))
        self.assertEqual(seal['provenance'], report['provenance'])
        self.assertNotIn(str(self.folder), json.dumps(report))
        with self.assertRaises(ValueError):
            G.build_report(analysis, plan, output)

    def test_changed_saved_data_fails_before_creating_derivative(self):
        analysis, plan = self.fixture()
        (analysis/'maps.json').write_bytes(b'changed')
        output = self.folder/'diagnostic'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            G.build_report(analysis, plan, output)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
