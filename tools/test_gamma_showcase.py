"""Saved-byte/negative fixtures only; no original-data export or scientific calls."""
import copy
import csv
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import gamma_showcase as G


def sample_science():
    """Artificial values with the real census/shape; never actual M11c outputs."""
    models = []; csv_files = {}; artifacts = {}
    for ident in G.MODELS:
        cases = []
        for index, eid in enumerate(G.SELECTED[ident]):
            zero = index == 0
            count = 2 if zero else (5002 if ident == 'AK02' else (27 if index == 1 else 22))
            t = [float(i * 2) for i in range(count)]
            q = [0.0] * count if zero else [float(i) / 100 for i in range(count)]
            caps = (39 if index == 1 else 156) if ident == 'AK02' and not zero else 0
            endpoints = ([dict(status='contact'), dict(status='contact')] +
                         [dict(status='step_limit') for _ in range(caps)])
            native = None if zero else dict(times=t, signal=q, steps=[dict(endpoints=endpoints)])
            flags = None if zero else dict(carrier_parcels=len(endpoints), geometric_contacts=2,
                                           step_limits=caps, stopped_without_contact=0)
            rd = dict(input_sample_count=count, original_sample_count=count + 5000,
                      accepted=not zero, adc_code=0 if zero else 1,
                      reconstructed_energy_keV=None if zero else 1.0,
                      preamp_peak_charge_equivalent_keV=-0.0 if zero else 1.0,
                      trace={k: [0.0, -0.125, 0.0] for k in (
                          'time_ns', 'induced_charge_fC', 'current_nA', 'preamp_V',
                          'shaped_V', 'current_bin_start_ns', 'current_bin_end_ns')})
            cases.append(dict(initial_primary_id=eid, event_id=eid, zero_ge=zero,
                              status='native_not_applicable_true_zero' if zero else 'native_completed',
                              charge_input=dict(time_since_initial_primary_ns=t, induced_equivalent_energy_keV=q),
                              native=native, transport_flags=flags, readout=rd, error=None))
        rows = []
        for eid in range(20):
            case = next((c for c in cases if c['initial_primary_id'] == eid), None)
            truth = dict(event_id=eid, initial_primary_id=eid, truth_ge_edep_keV=0.0 if eid == 0 else 1.0,
                         zero_ge=eid == 0, steps=[], material_rows=[], particles=[], tracks=[], vtx=[], material_energy_keV={})
            rows.append(dict(initial_primary_id=eid, selected=case is not None,
                             processing_status='unprocessed' if case is None else case['status'], source_truth=truth, response=case))
        calibration = dict(energy_keV=500.0, volts_per_keV=0.001)
        report = dict(status='completed', selected_ids=G.SELECTED[ident], cases=cases,
                      calibration_calls=1, native_calls=2, calibration=calibration,
                      readout_config=copy.deepcopy(G.CONFIG))
        wrapper = dict(calibration=calibration, config=copy.deepcopy(G.CONFIG),
                       ionisation_energy_eV=2.95, calibration_calls=1, method_scope='synthetic fixture')
        model = dict(model_id=ident, truth_ledger=rows, report=report, calibration=wrapper,
                     source_manifest=dict(uid_aliases={'det017': '/stp/germanium'}), prepared_metadata={})
        models.append(model)
        stream = io.StringIO(newline=''); writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['initial_primary_id', 'time_since_initial_primary_ns', 'induced_equivalent_energy_keV'])
        for c in cases:
            writer.writerows((c['initial_primary_id'], t, q) for t, q in zip(
                c['charge_input']['time_since_initial_primary_ns'], c['charge_input']['induced_equivalent_energy_keV']))
        raw = stream.getvalue().encode('ascii'); csv_files[ident + '-signals.csv'] = raw
        artifacts[ident + '/signals.csv'] = dict(sha256=G.sha(raw), bytes=len(raw))
    run = dict(status='completed', threads=2, additional_radiation_calls=0, field_solve_seconds=0.0)
    source = dict(receipt_pins=G.PINS.copy(), counts=G.COUNTS.copy(), artifacts=artifacts)
    return dict(models=models, run=run, source=source), csv_files


class SavedGammaTests(unittest.TestCase):
    def setUp(self):
        parent = G.ROOT / G.ROUND
        parent.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix='synthetic-fixture-', dir=parent)
        self.root = Path(self.directory.name)
        self.assertTrue(self.root.resolve().is_relative_to(parent.resolve()))
        self.addCleanup(self.directory.cleanup)
        for name in G.SOURCE_FILES:
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('fixture ' + name + '\n').encode())
        (self.root / G.TEMPLATE).write_text('<!doctype html><script type="application/json">' + G.TOKEN + '</script>\n', encoding='utf-8')
        self.science, self.csv_files = sample_science()
        self.root_patch = patch.object(G, 'ROOT', self.root); self.root_patch.start(); self.addCleanup(self.root_patch.stop)
        self.digest_patch = patch.object(G, 'SCIENCE_SHA256', G.typed_digest(self.science)); self.digest_patch.start(); self.addCleanup(self.digest_patch.stop)
        self.bundle = self.root / 'fixture-bundle'

    def data(self):
        sources, _ = G.current_sources()
        return dict(kind='saved_gamma_native_showcase_v1', schema_version=1,
                    science=copy.deepcopy(self.science), science_sha256=G.SCIENCE_SHA256,
                    units=G.UNITS, limitations=list(G.LIMITATIONS),
                    presentation=dict(encoding=G.ENCODING, template_sha256=sources[G.TEMPLATE]['sha256'],
                                      exporter_sha256=sources['tools/gamma_showcase.py']['sha256'], current_sources=sources))

    def write_bundle(self, data=None):
        data = self.data() if data is None else data
        self.bundle.mkdir(exist_ok=True)
        payload = dict(self.csv_files, **{'data.json': G.canonical(data), 'gamma.html': G.render(data)})
        manifest = dict(kind='saved_gamma_publication_v1', status='completed', science_sha256=data['science_sha256'],
                        source=data['science']['source'], presentation=data['presentation'],
                        files={n: dict(sha256=G.sha(v), bytes=len(v)) for n, v in payload.items()})
        for name, raw in payload.items(): (self.bundle / name).write_bytes(raw)
        (self.bundle / 'publication.json').write_bytes(G.canonical(manifest))

    def saved_fixture(self):
        """Synthetic original receipts/archive; no real saved-data files copied."""
        def put(name, raw):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            return dict(sha256=G.sha(raw),bytes=len(raw))
        archived={}; source_pins={}; artifact_items={}
        for name in G.EXECUTED:
            raw=('frozen synthetic '+name+'\n').encode()
            if name=='simulation/readout_demo.json':
                demo={k:v for k,v in G.CONFIG.items() if k not in ('peak_policy','peak_gate_start_ns','peak_gate_end_ns')}
                demo.update(schema_version=1,expected_primary_count=100,max_total_samples=20000000)
                raw=G.canonical(demo)
            elif name=='simulation/native_readout_profile.json':
                raw=G.canonical({'settings':{k:G.CONFIG[k] for k in ('peak_policy','peak_gate_start_ns','peak_gate_end_ns')}})
            archived[name]=put(G.BASE+'/executed-code-v2/'+name,raw);source_pins[name]=G.sha(raw)
        old='C:/Users/fixture/project';julia='C:/Users/fixture/install/bin/julia.exe'
        run=dict(self.science['run'],python_runtime=dict(executable='C:/Users/fixture/python.exe'),stages=[],source_pins=source_pins)
        for model in self.science['models']:
            ident=model['model_id'];report=copy.deepcopy(model['report'])
            report['runtime']=dict(executable=julia,native_source=old+'/simulation/native_li_example.jl',
                readout_source=old+'/simulation/readout_profiles.jl',worker_source=old+'/simulation/gamma_native_example.jl')
            events=[r['source_truth'] for r in model['truth_ledger']]
            stream='.local/m11b-gamma20-v1/'+ident+'/stream/events-00000000.jsonl'
            stream_bytes=b''.join(G.canonical(e) for e in events);put(stream,stream_bytes);source_pins[stream]=G.sha(stream_bytes)
            request=dict(events=events,expected_calibration=report['calibration'],source_manifest=model['source_manifest'],prepared=model['prepared_metadata'])
            objects={'report.json':report,'request.json':request,'calibration.json':model['calibration'],'child.json':{}}
            objects.update({'event-'+str(c['initial_primary_id'])+'.json':c for c in report['cases']})
            raw={name:G.canonical(value) for name,value in objects.items()}
            raw.update({'truth-ledger.jsonl':b''.join(G.canonical(r) for r in model['truth_ledger']),
                        'signals.csv':self.csv_files[ident+'-signals.csv'],'worker.log':b''})
            for name,value in raw.items():artifact_items[ident+'/'+name]=put(G.BASE+'/example/'+ident+'/'+name,value)
            run['stages'].append(dict(model_id=ident,exit_code=0,arguments=[julia,'--startup-file=no',
                '--project='+old+'/simulation','--threads=2','--compiled-modules=existing',old+'/simulation/gamma_native_example.jl',
                '--request',old+'/'+G.BASE+'/example/'+ident+'/request.json','--output',old+'/'+G.BASE+'/example/'+ident]))
        run_bytes=G.canonical(run);put(G.BASE+'/example/run.json',run_bytes)
        complete=dict(status='completed',run_sha256=G.sha(run_bytes),source_pins=source_pins,artifacts=artifact_items,counts=G.COUNTS)
        complete_bytes=G.canonical(complete);put(G.BASE+'/example/COMPLETE.json',complete_bytes)
        records={'COMPLETE.json':dict(status='completed',science_complete_sha256=G.sha(complete_bytes)),
                 'example/COMPLETE.json':complete,'example/run.json':run,
                 'EXECUTED-CODE-ARCHIVE-v2.json':dict(archive='executed-code-v2',files=archived),
                 'SOURCE-FREEZE-v2.json':dict(status='synthetic_archived_freeze')}
        pins={}
        for name,value in records.items():
            raw=G.canonical(value);put(G.BASE+'/'+name,raw);pins[name]=G.sha(raw)
        return pins

    def test_complete_fixture_bundle_and_exact_signed_csv(self):
        self.write_bundle(); data = G.validate_bundle(self.bundle)
        self.assertEqual(sum(len(m['truth_ledger']) for m in data['science']['models']), 40)
        self.assertIn(b'-0.0', (self.bundle / 'data.json').read_bytes())
        for name, raw in self.csv_files.items(): self.assertEqual((self.bundle / name).read_bytes(), raw)

    def test_saved_reader_validates_old_archive_after_current_documentation_change(self):
        pins=self.saved_fixture()
        current=self.root/'tools/GAMMA_NATIVE_EXAMPLE.md';current.write_bytes(b'new current documentation\n')
        with patch.object(G,'PINS',pins):
            science,csv_files,_=G.read_saved_science(self.root)
        self.assertEqual(sum(len(m['truth_ledger']) for m in science['models']),40)
        self.assertEqual(csv_files,self.csv_files)
        self.assertEqual(science['models'][0]['report']['runtime']['native_source'],'simulation/native_li_example.jl')
        self.assertNotEqual(G.sha(current.read_bytes()),science['source']['executed_sources']['tools/GAMMA_NATIVE_EXAMPLE.md']['sha256'])

    def test_rehashed_changed_execution_archive_cannot_change_trusted_receipt(self):
        pins=self.saved_fixture();name='tools/GAMMA_NATIVE_EXAMPLE.md'
        path=self.root/G.BASE/'executed-code-v2'/name;path.write_bytes(b'changed archived science context\n')
        receipt_path=self.root/G.BASE/'EXECUTED-CODE-ARCHIVE-v2.json';receipt=G.decode(receipt_path.read_bytes())
        receipt['files'][name]=dict(sha256=G.sha(path.read_bytes()),bytes=path.stat().st_size)
        receipt_path.write_bytes(G.canonical(receipt))
        with patch.object(G,'PINS',pins):
            with self.assertRaisesRegex(ValueError,'Changed source'):G.read_saved_science(self.root)

    def test_rehashed_original_truth_artifact_cannot_change_trusted_completion(self):
        pins=self.saved_fixture();name='AK02/truth-ledger.jsonl'
        path=self.root/G.BASE/'example'/name;rows=[G.decode(line) for line in path.read_bytes().splitlines()]
        rows[1]['source_truth']['truth_ge_edep_keV']=2.0
        path.write_bytes(b''.join(G.canonical(row) for row in rows))
        complete_path=self.root/G.BASE/'example/COMPLETE.json';complete=G.decode(complete_path.read_bytes())
        complete['artifacts'][name]=dict(sha256=G.sha(path.read_bytes()),bytes=path.stat().st_size)
        complete_path.write_bytes(G.canonical(complete))
        with patch.object(G,'PINS',pins):
            with self.assertRaisesRegex(ValueError,'Changed source'):G.read_saved_science(self.root)

    def test_rehashed_scientific_edits_rejected(self):
        edits = [
            lambda s: s['models'][0]['truth_ledger'][1]['source_truth'].update(truth_ge_edep_keV=math.nextafter(1.0, 2.0)),
            lambda s: s['models'][0]['truth_ledger'][1].update(response=0),
            lambda s: s['models'][0]['report'].update(selected_ids=[0, 4, 6]),
            lambda s: s['models'][0]['report']['cases'][1]['transport_flags'].update(step_limits=38),
            lambda s: s['models'][0]['report']['cases'][0]['readout'].update(preamp_peak_charge_equivalent_keV=0.0),
            lambda s: s['models'][1]['report']['cases'][1]['readout'].update(reconstructed_energy_keV=1),
            lambda s: s['models'][0]['report']['cases'][1]['charge_input']['induced_equivalent_energy_keV'].__setitem__(1, -0.01),
            lambda s: s['models'][0]['report']['cases'][1]['readout']['trace']['preamp_V'].__setitem__(1, 0.125),
            lambda s: s['source']['receipt_pins'].update({'example/COMPLETE.json': '0' * 64})]
        for edit in edits:
            with self.subTest(edit=edits.index(edit)):
                data = self.data(); edit(data['science']); self.write_bundle(data)
                with self.assertRaises(ValueError): G.validate_bundle(self.bundle)

    def test_config_gain_rejected_independently_of_rehashed_science(self):
        bad = copy.deepcopy(self.science)
        for m in bad['models']:
            m['report']['readout_config']['gain'] = 21.0
            m['calibration']['config']['gain'] = 21.0
        with self.assertRaisesRegex(ValueError, 'configuration'): G.validate_semantics(bad)

    def test_null_zero_selection_and_cap_semantics(self):
        edits = [lambda s: s['models'][0]['truth_ledger'][1].update(response={}),
                 lambda s: s['models'][0]['truth_ledger'][0]['response'].update(native={}),
                 lambda s: s['models'][0]['report']['cases'][1]['transport_flags'].update(step_limits=0),
                 lambda s: s['models'][0]['truth_ledger'][1].update(selected=True)]
        for edit in edits:
            bad = copy.deepcopy(self.science); edit(bad)
            with self.assertRaises(ValueError): G.validate_semantics(bad)

    def test_types_binary64_negative_zero_and_seed_strings(self):
        value = dict(float=2.0, integer=2, boolean=True, zero=-0.0, seed='18446744073709551615', null=None)
        G.exact(value, G.decode(G.canonical(value)))
        for a, b in ((True, 1), (2.0, 2), (-0.0, 0.0), (1.0, math.nextafter(1.0, 2.0)), (None, 0)):
            with self.assertRaises(ValueError): G.exact(a, b)
            self.assertNotEqual(G.typed_digest(a), G.typed_digest(b))
        with self.assertRaises(ValueError): G.public_safe(2**53)

    def test_duplicate_and_nonfinite_json_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'NaN', b'Infinity', b'1e9999'):
            with self.assertRaises(ValueError): G.decode(raw)

    def test_specific_dataset_addresses_and_unknown_private_strings(self):
        G.public_safe({'source_manifest': {'uid_aliases': {'det017': '/stp/germanium'}}})
        for value in ('C:/Users/person/cache/value', '/home/person/data', '/stp/germanium',
                      'ghp_' + 'a' * 30, 'file:///private/value'):
            with self.assertRaises(ValueError): G.public_safe({'science_label': value})

    def test_script_closing_text_is_escaped_without_changing_data(self):
        data = {'label': '</ScRiPt><img src=x>&'}
        html = G.render(data, '<script>' + G.TOKEN + '</script>')
        self.assertNotIn(b'<img', html); self.assertIn(b'\\u003c/ScRiPt', html)
        self.assertIn(b'\\u0026', html)
        embedded = html[len(b'<script>'):-len(b'</script>')]; G.exact(G.decode(embedded), data)

    def test_read_buffer_recheck_detects_change_and_traversal(self):
        path = self.root / 'value.json'; path.write_bytes(b'{"x":1}')
        reader = G.Reader(self.root); reader.json('value.json', G.sha(path.read_bytes()))
        path.write_bytes(b'{"x":2}')
        with self.assertRaisesRegex(ValueError, 'Changed source'): reader.recheck()
        for name in ('../value.json', '/value.json', 'C:/value.json', 'a\\value.json'):
            with self.assertRaises(ValueError): G.relative(self.root, name)

    def test_partial_extra_changed_and_nonterminal_bundle_refused(self):
        self.bundle.mkdir()
        with self.assertRaises(ValueError): G.validate_bundle(self.bundle)
        self.write_bundle(); (self.bundle / 'extra.json').write_bytes(b'{}')
        with self.assertRaises(ValueError): G.validate_bundle(self.bundle)
        (self.bundle / 'extra.json').unlink()
        manifest = G.decode((self.bundle / 'publication.json').read_bytes()); manifest['status'] = 'running'
        (self.bundle / 'publication.json').write_bytes(G.canonical(manifest))
        with self.assertRaises(ValueError): G.validate_bundle(self.bundle)
        self.write_bundle(); (self.bundle / 'AK02-signals.csv').write_bytes(b'changed')
        with self.assertRaises(ValueError): G.validate_bundle(self.bundle)

    def test_rehashed_csv_bytes_still_bound_to_original(self):
        self.write_bundle()
        path = self.bundle / 'AK02-signals.csv'; path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        manifest = G.decode((self.bundle / 'publication.json').read_bytes())
        manifest['files'][path.name] = dict(sha256=G.sha(path.read_bytes()), bytes=path.stat().st_size)
        (self.bundle / 'publication.json').write_bytes(G.canonical(manifest))
        with self.assertRaisesRegex(ValueError, 'exact original bytes'): G.validate_bundle(self.bundle)

    def test_known_path_map_preserves_every_other_value(self):
        old = 'C:/Users/saved/project'; julia = 'C:/Users/saved/install/bin/julia.exe'
        run = dict(self.science['run'], python_runtime=dict(executable='C:/Users/saved/python.exe', executable_sha256='x'), stages=[])
        for m in G.MODELS:
            run['stages'].append(dict(model_id=m, exit_code=0, wall_seconds=-0.0, arguments=[
                julia, '--startup-file=no', '--project=' + old + '/simulation', '--threads=2', '--compiled-modules=existing',
                old + '/simulation/gamma_native_example.jl', '--request', old + '/' + G.BASE + '/example/' + m + '/request.json',
                '--output', old + '/' + G.BASE + '/example/' + m]))
        before = copy.deepcopy(run); portable, root, exe = G.portable_run(run)
        G.exact(run, before); self.assertEqual(root, old); self.assertEqual(exe, julia)
        for stage in portable['stages']: G.exact(stage['wall_seconds'], -0.0)
        G.public_safe(portable)
        report = dict(other=[-0.0, None, '18446744073709551615'], runtime=dict(executable=julia,
            native_source=old + '/simulation/native_li_example.jl', readout_source=old + '/simulation/readout_profiles.jl',
            worker_source=old + '/simulation/gamma_native_example.jl', executable_sha256='x'))
        mapped = G.portable_report(report, root, exe); G.exact(mapped['other'], report['other'])
        self.assertEqual(mapped['runtime']['native_source'], 'simulation/native_li_example.jl')
        report['runtime']['native_source'] = old + '/other.jl'
        with self.assertRaises(ValueError): G.portable_report(report, root, exe)

    def test_template_and_current_source_edits_refuse_stale_bundle(self):
        self.write_bundle(); (self.root / G.TEMPLATE).write_text('changed ' + G.TOKEN)
        with self.assertRaises(ValueError): G.validate_bundle(self.bundle)

    def test_unrelated_current_source_changes_preserve_saved_bundle(self):
        self.write_bundle()
        for name in ('tools/site_restructure.py','tools/check_site.py','tools/build_site.py',
                     'tools/test_site.py','tools/publish.mjs','tools/GAMMA_NATIVE_EXAMPLE.md','tools/MAINTENANCE.md'):
            (self.root/name).write_bytes(b'new unrelated compatible maintenance\n')
        G.validate_bundle(self.bundle)
        # Compatible exporter changes keep its historical generation identity too.
        (self.root/'tools/gamma_showcase.py').write_bytes(b'compatible validator maintenance\n')
        G.validate_bundle(self.bundle)

    def test_mutable_handoff_is_not_a_source_binding(self):
        before, _ = G.current_sources(); (self.root / 'PROGRESS.md').write_text('mutable handoff')
        after, _ = G.current_sources(); self.assertEqual(before, after)

    def test_freeze_exit_and_existing_destination_guards(self):
        round_root = self.root / G.ROUND; round_root.mkdir(parents=True)
        exited = dict(status='exited', science_calls=0)
        (round_root / 'WRITER-EXIT.json').write_bytes(G.canonical(exited))
        sources, _ = G.current_sources()
        frozen = dict(status='frozen_after_writer_exit', writer_exit_sha256=G.sha(G.canonical(exited)), files=sources)
        (round_root / 'SOURCE-FREEZE.json').write_bytes(G.canonical(frozen)); G.verify_freeze()
        frozen['files'][G.TEMPLATE]['sha256'] = '0' * 64
        (round_root / 'SOURCE-FREEZE.json').write_bytes(G.canonical(frozen))
        with self.assertRaises(ValueError): G.verify_freeze()
        (round_root / 'bundle').mkdir()
        with self.assertRaisesRegex(ValueError, 'new M11d bundle'): G.export_saved()


if __name__ == '__main__':
    unittest.main(verbosity=2)
