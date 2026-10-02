"""Meaningful saved-only four-case source and spectrum population checks."""
import json
from pathlib import Path
import tempfile
import unittest

import ring_site as R
import spectrum_display as S


class RingSiteTests(unittest.TestCase):
    def setUp(self):
        root = R.Path(__file__).resolve().parents[1] / '.local/ring-delivery-v1'
        self.temp = tempfile.TemporaryDirectory(prefix='site-fixture-', dir=root)
        self.site = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def put(self, rel, value):
        path = self.site / rel; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + '\n', encoding='utf-8')
        return path

    def fixture(self):
        m = {'kind': 'ring_saved_publication_v1', 'status': 'complete', 'schema_version': 1,
             'models': {}, 'files': {}}
        for model in R.ALL_MODELS:
            ring = model in R.RING_MODELS
            base = (R.RING_FOLDER if ring else 'examples/cs137-10k') + '/' + model
            counts = {'initial_primaries': 10000, 'initial_decays': 10000, 'zero_deposit_primaries': 9997,
                      'groups': 3, 'accepted': 2, 'native_failed_groups': 1, 'readout_rejected': 0}
            self.put(base + '/response/run.json', {'current_counts' if ring else 'counts': counts})
            native_bin = 198 if model == 'KMRC01_candidate' else 202
            hist = {'width_keV': 5, 'bins': [
                {'stage': stage, 'bin': native_bin if stage=='native_terminal_charge' else 200,
                 'lower_keV': -1000+5*(native_bin if stage=='native_terminal_charge' else 200),
                 'upper_keV': -995+5*(native_bin if stage=='native_terminal_charge' else 200),
                 'count': 10000 if stage=='deposited_per_decay' else 3 if stage=='deposited_per_group' else 2}
                for stage,_ in S.STAGES]}
            self.put(base + '/response/histograms.json', hist)
            if not ring:
                continue
            entry = {'event_count': 10000, 'counts': counts}
            for field, filename in (('scene', 'scene.json'), ('selected', 'selected.json.gz'),
                                    ('response', 'response/summary.html'), ('response_report', 'response/run.json')):
                rel = model + '/' + filename
                path = self.site / R.RING_FOLDER / rel
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'{}\n')
                entry[field] = rel
                m['files'][rel] = {'sha256': R.sha(path), 'bytes': path.stat().st_size}
            m['models'][model] = entry
        self.put(R.RING_FOLDER + '/manifest.json', m)
        return m

    def test_absent_or_partial_never_enables_ring_pages(self):
        self.assertIsNone(R.ring_manifest(self.site)); self.assertEqual(R.cases(self.site), [])
        self.fixture(); m = R.read(self.site / R.RING_FOLDER / 'manifest.json'); m['status'] = 'pending'
        self.put(R.RING_FOLDER + '/manifest.json', m)
        with self.assertRaisesRegex(ValueError, 'complete two-ring'):
            R.cases(self.site)

    def test_rehashed_incomplete_count_and_changed_payload_refused(self):
        m = self.fixture(); m['models']['GeRC02']['event_count'] = 500
        self.put(R.RING_FOLDER + '/manifest.json', m)
        with self.assertRaisesRegex(ValueError, '10,000'):
            R.cases(self.site)
        m = self.fixture()
        (self.site / R.RING_FOLDER / m['models']['GeRC02']['selected']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            R.cases(self.site)

    def test_four_case_counts_and_all_stage_bins_are_exact(self):
        self.fixture(); cases = R.cases(self.site); specs = S.tenk_specs(self.site)
        self.assertEqual([c['model'] for c in cases], list(R.ALL_MODELS))
        self.assertEqual(len(specs), 20)
        self.assertEqual([s['series'][0]['total'] for s in specs], [10000,3,2,2,2]*4)
        negative = next(s for s in specs if s['key']=='tenk-KMRC01_candidate-native_terminal_charge')
        self.assertEqual(negative['series'][0]['counts'][198], 2)
        self.assertEqual(negative['edges'][198:200], [-10,-5])
        html = S.four_detector_spectra(self.site, specs)
        self.assertEqual(len(S.embedded_specs(html)), 20)
        self.assertEqual(html.count('id="spectrum-controls-script"'), 1)
        for model in R.ALL_MODELS:
            self.assertIn('id="tenk-'+model+'"', html)
        self.assertIn('fixed −1 electronics', html)

    def test_population_mismatch_refused_and_origin_sources_complete(self):
        self.fixture(); report = self.site / R.RING_FOLDER / 'GeRC02/response/run.json'
        o = R.read(report); o['current_counts']['accepted'] = 0; self.put(report.relative_to(self.site), o)
        m = R.read(self.site / R.RING_FOLDER / 'manifest.json'); rel='GeRC02/response/run.json'
        m['models']['GeRC02']['counts'] = o['current_counts'];m['files'][rel]={'sha256':R.sha(report),'bytes':report.stat().st_size}
        self.put(R.RING_FOLDER + '/manifest.json', m)
        with self.assertRaisesRegex(ValueError, 'accounting'):
            R.cases(self.site)
        self.fixture()
        self.assertEqual(len(R.source_files(self.site)), 3)
        self.assertEqual(set(S.source_inventory(self.site)), set(S.ROUTES)|set(S.DATA_SOURCES)|set(S.RECEIPTS)|set(R.source_files(self.site)))


if __name__ == '__main__':
    unittest.main()
