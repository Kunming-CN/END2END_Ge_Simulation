"""Meaningful saved-only four-case source and spectrum population checks."""
import json
from pathlib import Path
import tempfile
import unittest
import re
import zipfile
import os
import shutil
import subprocess

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
        members['traces.jsonl'] = b''.join((json.dumps({'event_id': 213+i, 'group_id': 0,
            'trace': {'time_ns': [0, 2], 'current_nA': [0, -1], 'induced_charge_fC': [0, -2],
                      'preamp_V': [0, 1], 'shaped_V': [0, 0.5]}}) + '\n').encode() for i in range(traces))
        members['scalars.jsonl'] = b''.join((json.dumps({'record_kind': 'pulse', 'event_id': 213+i,
            'group_id': 0, 'deposited_energy_keV': 2.0, 'final_induced_keV': -2.0,
            'raw_row_indices': [4], 'origin_time_ns': 0, 'readout': {'accepted': True,
            'reconstructed_energy_keV': 2.1, 'original_sample_count': 2,
            'peak_time_ns': 2, 'peak_V': 0.5}}) + '\n').encode() for i in range(traces))
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

    def test_selected_trace_files_are_exact_original_records_and_identity_is_explicit(self):
        case, _ = self.report_fixture('KMRC01_candidate', traces=231)
        body = R.saved_report(self.site, case)
        config = json.loads(re.search(r'<script id="saved-response-data" type="application/json">(.*?)</script>', body, re.S).group(1))
        self.assertEqual(config['variant'], 'KMRC01_candidate')
        self.assertEqual(len(config['traces']), 231)
        self.assertEqual(config['trace_keys'][0], [213, 0])
        with zipfile.ZipFile(self.site / case['base'] / 'response/ledgers.zip') as bundle:
            for line in bundle.open('traces.jsonl'):
                trace = json.loads(line); key = f'{trace["event_id"]}/{trace["group_id"]}'
                path = self.site / 'results/cs137-10k/KMRC01_candidate' / config['traces'][key]['path']
                self.assertEqual(R.gzip.decompress(path.read_bytes()), line)
                self.assertEqual(path.read_bytes(), R.gzip.compress(line, compresslevel=9, mtime=0))
                self.assertEqual(R.sha(path), config['traces'][key]['sha256'])
                self.assertEqual(path.stat().st_size, config['traces'][key]['bytes'])
                self.assertEqual(len(line), config['traces'][key]['uncompressed_bytes'])
                self.assertEqual(R.hashlib.sha256(line).hexdigest(), config['traces'][key]['uncompressed_sha256'])
        self.assertIn('No published full waveform for this exact primary', body)
        self.assertIn('Saved model examples · selecting one changes the primary and group', body)
        self.assertIn('saved.event_id!==event||saved.group_id!==group', body)
        with zipfile.ZipFile(self.site / case['base'] / 'response/ledgers.zip') as bundle:
            first_raw = next(iter(bundle.open('traces.jsonl')))
        legacy = self.site / 'results/cs137-10k/KMRC01_candidate/traces/213-0.json'
        legacy.write_bytes(first_raw)
        R.saved_report(self.site, case)
        self.assertFalse(legacy.exists())
        legacy.write_bytes(b'unrecognized retained failure evidence')
        with self.assertRaisesRegex(ValueError, 'Unrecognized earlier generated trace; preserved'):
            R.saved_report(self.site, case)
        self.assertEqual(legacy.read_bytes(), b'unrecognized retained failure evidence')

    def test_actual_primary_698_never_substitutes_trace_213_and_history_restores_selection(self):
        node = os.environ.get('TEACHING_NODE') or shutil.which('node')
        if not node:
            self.skipTest('Node runtime unavailable')
        root = Path(__file__).resolve().parents[1]
        with zipfile.ZipFile(root / 'docs/examples/cs137-10k/AK02/response/ledgers.zip') as archive:
            pulses = [p for line in archive.open('scalars.jsonl') if
                      (p := json.loads(line)).get('record_kind') == 'pulse' and p['event_id'] in (213, 698)]
            raw = next(line for line in archive.open('traces.jsonl') if json.loads(line)['event_id'] == 213)
        self.assertEqual({p['event_id'] for p in pulses}, {213, 698})
        packed = R.gzip.compress(raw, compresslevel=9, mtime=0)
        config = {'model': 'AK02', 'variant': 'AK02', 'pulses': pulses, 'trace_keys': [[213, 0]],
                  'scalar_url': 'scalar.csv', 'teaching': [[213, 0]],
                  'traces': {'213/0': {'path': 'traces/213-0.json.gz', 'sha256': R.hashlib.sha256(packed).hexdigest(),
                                     'bytes': len(packed), 'uncompressed_sha256': R.hashlib.sha256(raw).hexdigest(),
                                     'uncompressed_bytes': len(raw)}}}
        runtime = r'''
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),{webcrypto}=require('node:crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
class Element{constructor(){this.children=[];this.value='';this.textContent='';this.hidden=false;this.open=false;}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}removeAttribute(name){delete this[name];}}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};get('saved-response-data').textContent=JSON.stringify(input.config);
const location={pathname:'/results/cs137-10k/AK02/charge-readout.html',search:'?study=cs137-10k&model=AK02&variant=AK02&event=698&group=0',hash:''},listeners=new Map(),requests=[];
const move=url=>location.search=new URL(url,'https://test.invalid').search,history={replaceState:(_,__,url)=>move(url),pushState:(_,__,url)=>move(url)};
const c=vm.createContext({document:{getElementById:get,createElement:()=>new Element(),querySelectorAll:()=>[]},URLSearchParams,location,history,crypto:webcrypto,Uint8Array,TextDecoder,Blob,Response,DecompressionStream,
addEventListener:(name,fn)=>listeners.set(name,fn),fetch:async path=>{requests.push(path);const packed=Buffer.from(input.packed,'base64');return {ok:true,arrayBuffer:async()=>packed.buffer.slice(packed.byteOffset,packed.byteOffset+packed.byteLength)};},
SavedFocusPlots:{focusEnd:()=>10,shaperEnd:()=>20,draw:(host,panels)=>{host.children=panels;}}});
vm.runInContext(input.navigation,c);vm.runInContext(input.controller,c);
(async()=>{
 assert.match(get('selected-identity').textContent,/primary 698/);assert.match(get('selected-status').textContent,/No published full waveform/);assert.equal(requests.length,0);assert.equal(get('selected-plots').children.length,0);
 assert.equal(get('selected-summary').children[0].textContent,'Truth deposited energy: '+input.config.pulses.find(p=>p.event_id===698).deposited_energy_keV+' keV');assert.match(get('selected-3d').href,/event=698&group=0/);assert.equal(get('selected-teaching').hidden,true);
 location.search='?study=cs137-10k&model=AK02&variant=AK02&event=213&group=0';await listeners.get('popstate')();assert.match(get('selected-status').textContent,/Matching saved waveform: primary 213/);assert.equal(get('selected-plots').children.length,4);assert.equal(requests.length,1);
 get('selected-details').open=true;get('selected-details').ontoggle();const exact=JSON.parse(get('selected-record').textContent);assert.deepEqual(exact.saved_trace,JSON.parse(input.raw));assert.equal(exact.pulse.event_id,213);
 location.search='?study=cs137-10k&model=AK02&variant=AK02&event=698&group=0';await listeners.get('popstate')();assert.equal(get('selected-plots').children.length,0);assert.match(get('selected-status').textContent,/No published full waveform/);assert.equal(requests.length,1);assert.equal(JSON.parse(get('selected-record').textContent).saved_trace,null);
 location.search='?model=SAP22&event=213&group=0';await listeners.get('popstate')();assert.match(get('selected-status').textContent,/does not match this saved case/);assert.equal(get('selected-plots').children.length,0);assert.equal(requests.length,1);
 console.log('Actual AK02 primary698 scalar-only; primary213 exact matching trace; back restores698 without waveform; cross-case refused');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        import base64
        result = subprocess.run([node, '-e', runtime], input=json.dumps({'config': config,
            'raw': raw.decode(), 'packed': base64.b64encode(packed).decode('ascii'),
            'navigation': (root / 'tools/viewer_navigation.js').read_text(encoding='utf-8'),
            'controller': R.READOUT_CONTROLLER}), text=True, encoding='utf-8', capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
