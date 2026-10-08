"""Meaningful saved-only four-case source and spectrum population checks."""
import json
from pathlib import Path
import tempfile
import unittest
import re
import zipfile

import ring_site as R
import spectrum_display as S


class RingSiteTests(unittest.TestCase):
    def setUp(self):
        root = R.Path(__file__).resolve().parents[1] / '.local/student-navigation-v2'
        root.mkdir(parents=True, exist_ok=True)
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

    def report_fixture(self, model='AK02', traces=4):
        base = (R.RING_FOLDER if model in R.RING_MODELS else 'examples/cs137-10k') + '/' + model
        case = dict(model=model, label=model, note='Frozen scientific fixture.', base=base,
                    counts=dict(initial_primaries=10000, initial_decays=10000, zero_deposit_primaries=9999,
                                groups=1, accepted=0, native_failed_groups=1, readout_rejected=0))
        folder = self.site / base / 'response'; folder.mkdir(parents=True, exist_ok=True)
        svg = "<svg role='img' viewBox='0 0 600 205'><polyline points='1,-2 3,0' stroke='currentColor'/><text>−2 fC</text></svg>"
        report = ("<!doctype html><html><head><meta charset='utf-8'><title>Frozen native report</title>"
                  "<style>body{padding:20px}svg{width:100%}pre{white-space:pre-wrap}</style>"
                  "<script id='source-data' type='application/json'>{\"signed\":-0.000123456789,\"unknown\":null,\"zero\":0,\"text\":\"href='unchanged'\"}</script>"
                  "<script src='chart.js'></script></head><body><h1 id='original-title'>Native report</h1>"
                  "<nav><a href='run.json'>Settings</a><a href='ledgers.zip'>Truth</a><a href='ledgers.zip'>Endpoints</a></nav>"
                  "<pre>{\"zero_deposit_primaries\":9999,\"native_failed_groups\":1,\"charge\":null}</pre>"
                  "<table id='original-errors'><tr><td>ArgumentError: Invalid waveform support</td><td>0</td><td>−0.1</td></tr></table>"
                  "<p>Failure is unknown. <a href='ledgers.zip'>Failure diagnostics</a>.</p>"
                  "<details id='event-213'><summary>Event 213 / group 0</summary><figure>" + svg + "</figure></details>"
                  "<img src='preview.png' poster='plot.png'><a href='run.json#calibration'>Calibration</a>"
                  "<a href='#event-213'>Same event</a><a href='https://example.invalid/ref'>Reference</a></body></html>")
        (folder / 'summary.html').write_bytes(report.encode('utf-8'))
        self.put(base + '/response/run.json', {'counts': case['counts']})
        members = {name: b'{}\n' for name in ('truth.jsonl', 'scalars.jsonl', 'endpoints.jsonl', 'histograms.json', 'run.json')}
        members['traces.jsonl'] = b'{}\n' * traces
        members['native-failures.jsonl'] = b'{"error":"ArgumentError: Invalid waveform support"}\n'
        with zipfile.ZipFile(folder / 'ledgers.zip', 'w') as bundle:
            for name, content in members.items(): bundle.writestr(name, content)
        self.put(base + '/response/native-failures.json', {'groups': 1, 'charge': None})
        if model == 'KMRC01_candidate':
            old = folder / 'original-native/summary.html'; old.parent.mkdir()
            old.write_bytes(b'<h1>Original response</h1><p>0 of 231 accepted; raw negative charge.</p>')
        return case, report

    def test_direct_report_preserves_science_scripts_ids_and_relative_resources(self):
        case, original = self.report_fixture()
        source = self.site / case['base'] / 'response/summary.html'; digest = R.sha(source)
        body = R.saved_report(self.site, case)
        for pattern in (r'<svg\b.*?</svg>', r'<table\b.*?</table>', r'<pre>.*?</pre>',
                        r'<script id=\x27source-data\x27.*?</script>'):
            self.assertEqual(re.findall(pattern, body, re.S), re.findall(pattern, original, re.S))
        prefix = '../../../' + case['base'] + '/response/'
        for resource in ('chart.js', 'preview.png', 'plot.png', 'run.json#calibration'):
            self.assertIn(prefix + resource, body)
        for unchanged in ("href='#event-213'", "href='https://example.invalid/ref'", "id='original-title'", "id='event-213'"):
            self.assertIn(unchanged, body)
        self.assertIn("<details id='event-213' open>", body)
        self.assertIn('4 saved trace records', body); self.assertIn('do not imply complete waveforms', body)
        self.assertIn('Independent saved native-failure diagnostics', body)
        self.assertEqual(body.count('href="' + prefix + 'ledgers.zip"'), 1)
        science = body.split('<section id="data-files"', 1)[0]
        self.assertNotIn('ledgers.zip', science)
        self.assertIn('Failure diagnostics (included in the complete response archive)', science)
        self.assertNotIn('<nav>', body); self.assertNotIn('<iframe', body)
        self.assertNotIn('body{padding:20px}', body)
        self.assertIn('.saved-response-report{padding:20px}', body)
        self.assertEqual(R.sha(source), digest)

    def test_km_current_trace_scope_and_original_zero_acceptance_archive_remain_separate(self):
        case, original = self.report_fixture('KMRC01_candidate', traces=231)
        old = self.site / case['base'] / 'response/original-native/summary.html'; digest = R.sha(old)
        body = R.saved_report(self.site, case)
        self.assertIn('231 saved trace records', body)
        self.assertIn('0/231 accepted (archive)', body); self.assertIn('fixed −1 wiring is a separate derivative', body)
        self.assertIn('/original-native/summary.html', body)
        self.assertEqual(R.sha(old), digest); self.assertNotIn('http-equiv="refresh"', old.read_text())
        self.assertIn('−2 fC', body)

    def test_archive_member_and_waveform_identity_checks_fail_without_science_changes(self):
        case, original = self.report_fixture('GeRC02')
        self.put(case['base'] + '/response/run.json', {'trace_examples': {'source_trace_records': 4, 'displayed_trace_keys': [[999, 0]]}})
        with self.assertRaisesRegex(ValueError, 'waveform display keys differ'):
            R.saved_report(self.site, case)
        with zipfile.ZipFile(self.site / case['base'] / 'response/ledgers.zip', 'w') as bundle:
            bundle.writestr('truth.jsonl', '{}\n')
        with self.assertRaisesRegex(ValueError, 'Incomplete response archive'):
            R.saved_report(self.site, case)
        self.assertEqual((self.site / case['base'] / 'response/summary.html').read_bytes(), original.encode('utf-8'))

    def test_case_cards_have_one_primary_report_action_and_studies_insert_after_geometry(self):
        case, _ = self.report_fixture()
        cards = R.cards([case], '../../')
        self.assertEqual(cards.count('<a '), 1)
        self.assertIn('results/cs137-10k/AK02/charge-readout.html', cards)
        self.assertNotIn('ledgers.zip', cards)
        page = self.site / 'detector.html'
        page.write_text('<main><section id="hero">Model</section><section id="current-ring-10k">old</section>'
                        '<figure>Geometry</figure><section id="saved-studies"><h2>Saved studies</h2><p>Original gallery</p></section></main>')
        block = '<section id="current-ring-10k"><h3>Cs137 10K</h3></section>'
        R.insert_section(page, 'current-ring-10k', block)
        first = page.read_bytes(); html = first.decode()
        self.assertEqual(html.count('id="current-ring-10k"'), 1)
        self.assertLess(html.index('Geometry'), html.index('saved-studies'))
        self.assertLess(html.index('Original gallery'), html.index('current-ring-10k'))
        R.insert_section(page, 'current-ring-10k', block)
        self.assertEqual(page.read_bytes(), first)


if __name__ == '__main__':
    unittest.main()
