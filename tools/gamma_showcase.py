"""Export only the pinned, completed M11c saved example; never run a producer.

Standard library only. `export` requires the M11d writer-exit/source-freeze
receipts. `validate BUNDLE` needs only public files and this reviewed source.
"""
from __future__ import annotations
import argparse
import copy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct

ROOT = Path(__file__).resolve().parents[1]
BASE = '.local/m11c-gamma-native-v1'
ROUND = '.local/m11d-gamma-showcase-v1'
TEMPLATE = 'tools/gamma_showcase.html'
TOKEN = '__GAMMA_SAVED_DATA_JSON__'
ENCODING = 'json-compact-sorted-ascii-lf-v1'
FILES = ('AK02-signals.csv', 'SAP22-signals.csv', 'data.json', 'gamma.html')
MODELS = ('AK02', 'SAP22')
SELECTED = {'AK02': [0, 4, 5], 'SAP22': [0, 2, 3]}
SOURCE_FILES = (
    'tools/gamma_showcase.py', 'tools/gamma_showcase.html',
    'tools/test_gamma_showcase.py', 'tools/build_site.py', 'tools/check_site.py',
    'tools/site_restructure.py', 'tools/test_site.py',
    'tools/test_site_restructure.py', 'tools/publish.mjs',
    'tools/GAMMA_NATIVE_EXAMPLE.md', 'tools/MAINTENANCE.md')
EXECUTED = tuple('simulation/' + n for n in (
    'gamma_native_example.jl', 'native_response.jl', 'native_boundary_guard.jl',
    'native_li_example.jl', 'native_stream.jl', 'readout.jl', 'readout_profiles.jl',
    'replay.jl', 'run.jl', 'native_readout_profile.json', 'readout_demo.json',
    'Project.toml', 'Manifest.toml', 'test_gamma_native_example.jl')) + (
    'tools/gamma_native_example.py', 'tools/test_gamma_native_example.py',
    'tools/GAMMA_NATIVE_EXAMPLE.md', 'tools/charge_check.py', 'tools/replay_readout.py')
PINS = {
    'COMPLETE.json': '7cc3c4582388866361afa4c5d4efbbfdaac13eebfb8765616b041a085e8de602',
    'example/COMPLETE.json': 'e65627146d4a9ef2427933e5bc8418f3de0673e827b82aa8a49070e481cf1261',
    'example/run.json': '36c12ead929dc5fbaa5a098dd18a2f8b9c9cdbf9326277ccad0484c09bd59ff2',
    'EXECUTED-CODE-ARCHIVE-v2.json': '362eb9d627ab15549cefa91475dcb78c083d1a926b82870f837d15d02c82fad6',
    'SOURCE-FREEZE-v2.json': '0cdb3c35d9d636417ec67a35e0f52baa77043f8bf21ffbb03a076e2678d71d30'}
# Derived once by reading the above original bytes, using typed_digest below.
# This trusted source constant also detects scientific edits with rehashed manifests.
SCIENCE_SHA256 = 'b3d3c078a914b4f1d1e8e96aef061d1909428603eb3e2741485994be83e976a4'
COUNTS = dict(radiation_primaries=40, selected_primaries=6,
              unprocessed_primaries=34, native_calls=4, injection_calibrations=2)
CONFIG = dict(schema_version=2, feedback_capacitance_pF=0.6,
              feedback_tau_us=50.0, pole_zero_tau_us=50.0, shaping_tau_us=0.5,
              gain=20.0, tail_shaping_constants=20.0, max_window_ns=1000000.0,
              max_samples_per_event=500000, trace_max_points=600, adc_bits=14,
              adc_full_scale_V=10.0, threshold_V=0.001,
              calibration_energy_keV=500.0, require_all_events=True,
              expected_primary_count=3, peak_policy='signed_input_positive_peak',
              peak_gate_start_ns=None, peak_gate_end_ns=None)
UNITS = dict(truth_energy='keV', native_induced_equivalent='keV',
             position='mm', time_since_initial_primary='ns', final_charge='C',
             trace_charge='fC', trace_current='nA', voltage='V',
             peak_adc='integer code', reconstructed_energy='keV',
             raw_track_energy='MeV', raw_position='m')
LIMITATIONS = (
    '40 initial synthetic gamma primaries in nominal geometry; only the fixed six-event cohort was processed. This is a small engineering example, not a spectrum or efficiency prediction.',
    'Original 78 K models, explicit existing 77 K field-cache override; AK02 +500 V and SAP22 +700 V. No new fields or numerical convergence claim.',
    'AK02 retains 195 capped carrier endpoints. ADC acceptance does not prove full collection or calibrated Li CCE. SAP22 is a differently shaped non-Li cross-check.',
    'Two separate 500 keV synthetic charge injections set fixed gains, not event truth or hardware calibration. Numerical diffusion parcels are not physical energy-resolution noise.',
    'All 10057 known signed charge-input samples are retained. Readout traces were already compacted to 599/600 points; full original analog arrays were not saved and are not reconstructed.',
    'Numerical analog grids are not waveform ADC acquisitions. Only the peak is digitized; isolated event electronics reset has no pileup/live-time model.',
    'Deposited energy, induced equivalent charge and reconstructed energy are different stages. Deposition time is not carrier drift time. Signed signals and all flags remain unchanged.',
    'Scored STEP chords and Track birth records are not complete trajectories. Unscored energy accounting, activity, as-built dimensions and experimental agreement remain unresolved.')
PRIVATE = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]|file://|\\\\|/(?:Users|home|mnt|tmp|private|var|opt|root|etc)/', re.I)
CREDENTIAL = re.compile(r'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}|sk-(?:proj-)?[A-Za-z0-9_-]{25,}')
MAX_BYTES = 16 * 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(',', ':')) + '\n').encode('ascii')


def decode(raw):
    def unique(pairs):
        value = {}
        for k, v in pairs:
            require(k not in value, 'Duplicate JSON key: ' + k)
            value[k] = v
        return value
    def finite(token):
        value = float(token)
        require(math.isfinite(value), 'Nonfinite JSON float')
        return value
    def invalid(token):
        raise ValueError('Nonfinite JSON token: ' + token)
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique,
                      parse_float=finite, parse_constant=invalid)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def exact(a, b, where='value'):
    require(type(a) is type(b), 'Changed type: ' + where)
    if type(a) is dict:
        require(a.keys() == b.keys(), 'Changed keys: ' + where)
        for k in a:
            exact(a[k], b[k], where + '/' + k)
    elif type(a) is list:
        require(len(a) == len(b), 'Changed list length: ' + where)
        for i, (x, y) in enumerate(zip(a, b)):
            exact(x, y, where + '/' + str(i))
    elif type(a) is float:
        require(math.isfinite(a) and math.isfinite(b) and
                struct.pack('>d', a) == struct.pack('>d', b), 'Changed binary64: ' + where)
    else:
        require(a == b, 'Changed value: ' + where)


def typed_digest(value):
    def typed(v):
        t = type(v)
        if t is dict:
            require(all(type(k) is str for k in v), 'Nonstring JSON key')
            return ['object', [[k, typed(v[k])] for k in sorted(v)]]
        if t is list:
            return ['array', [typed(x) for x in v]]
        if t is float:
            require(math.isfinite(v), 'Nonfinite scientific float')
            return ['binary64', struct.pack('>d', v).hex()]
        if t is int:
            return ['integer', str(v)]
        if t is bool:
            return ['boolean', v]
        if t is str:
            return ['string', v]
        require(v is None, 'Unsupported scientific type')
        return ['null']
    return sha(canonical(typed(value)))


def no_links(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode) and not
                (getattr(info, 'st_file_attributes', 0) & 0x400), 'Linked/reparse path refused')
    return path


def relative(base, name):
    require(type(name) is str and '\\' not in name and ':' not in name, 'Unsafe filename')
    p = PurePosixPath(name)
    require(not p.is_absolute() and p.parts and all(x not in ('.', '..') for x in p.parts)
            and str(p) == name, 'Unsafe relative filename')
    return no_links(Path(base).joinpath(*p.parts))


class Reader:
    def __init__(self, root):
        self.root = no_links(root)
        self.seen = {}

    def raw(self, name, digest=None, size=None):
        path = relative(self.root, name)
        require(path.is_file() and path.stat().st_size <= MAX_BYTES, 'Missing/oversize source: ' + name)
        raw = path.read_bytes()
        require(len(raw) <= MAX_BYTES, 'Source grew beyond bound')
        actual = sha(raw)
        require(digest is None or actual == digest, 'Changed source: ' + name)
        require(size is None or len(raw) == size, 'Changed source size: ' + name)
        require(name not in self.seen or self.seen[name] == actual, 'Source changed during read')
        self.seen[name] = actual
        return raw

    def json(self, name, digest=None):
        return decode(self.raw(name, digest))

    def jsonl(self, name, digest=None):
        lines = self.raw(name, digest).splitlines()
        require(len(lines) == 20 and all(lines), 'Expected twenty complete truth rows')
        return [decode(line) for line in lines]

    def recheck(self):
        for name, digest in list(self.seen.items()):
            self.raw(name, digest)


def public_safe(value, where='$'):
    if type(value) is dict:
        for k, v in value.items():
            public_safe(k, where + '/<key>')
            public_safe(v, where + '/' + k)
    elif type(value) is list:
        for i, v in enumerate(value):
            public_safe(v, where + '/' + str(i))
    elif type(value) is str:
        # These exact fields are LH5-internal dataset addresses, not host paths.
        dataset = (re.search(r'/source_manifest/uid_aliases/det[0-9]{3}$', where) and
                   re.fullmatch(r'/stp/(?:ledger_[1-9][0-9]*|germanium)', value))
        require(not PRIVATE.search(value) and (not value.startswith('/') or dataset) and
                not CREDENTIAL.search(value), 'Private path/credential in public string: ' + where)
    elif type(value) is float:
        require(math.isfinite(value), 'Nonfinite public value')
    elif type(value) is int:
        require(abs(value) <= 2**53 - 1, 'Scientific integer exceeds browser exact range; preserve as source string')


def portable_run(run):
    value = copy.deepcopy(run)
    require(len(value['stages']) == 2, 'Changed stage census')
    first = value['stages'][0]['arguments']
    require(len(first) == 10 and first[2].startswith('--project=') and
            first[2].replace('\\', '/').endswith('/simulation'), 'Unknown project argument')
    original_root = first[2][len('--project='):].replace('\\', '/')[:-len('/simulation')]
    julia = first[0]
    require(PRIVATE.search(julia) and julia.replace('\\', '/').endswith('/bin/julia.exe'), 'Unknown Julia executable role')
    python = value['python_runtime']['executable']
    require(PRIVATE.search(python) and python.replace('\\', '/').endswith('/python.exe'), 'Unknown Python executable role')
    value['python_runtime']['executable'] = '{PYTHON_EXECUTABLE}'
    for model, stage in zip(MODELS, value['stages']):
        require(stage['model_id'] == model and stage['exit_code'] == 0, 'Changed completed stage')
        expected = [julia.replace('\\', '/'), '--startup-file=no', '--project=' + original_root + '/simulation',
                    '--threads=2', '--compiled-modules=existing', original_root + '/simulation/gamma_native_example.jl',
                    '--request', original_root + '/' + BASE + '/example/' + model + '/request.json',
                    '--output', original_root + '/' + BASE + '/example/' + model]
        exact([s.replace('\\', '/') for s in stage['arguments']], expected, 'recorded command roles')
        stage['arguments'][0] = '{JULIA_EXECUTABLE}'
        stage['arguments'][2] = '--project=simulation'
        stage['arguments'][5] = 'simulation/gamma_native_example.jl'
        stage['arguments'][7] = '{SOURCE_EXAMPLE}/' + model + '/request.json'
        stage['arguments'][9] = '{SOURCE_EXAMPLE}/' + model
    return value, original_root, julia


def portable_report(report, original_root, julia):
    value = copy.deepcopy(report)
    runtime = value['runtime']
    exact(runtime['executable'], julia, 'reported executable role')
    runtime['executable'] = '{JULIA_EXECUTABLE}'
    for key, name in (('native_source', 'native_li_example.jl'),
                      ('readout_source', 'readout_profiles.jl'),
                      ('worker_source', 'gamma_native_example.jl')):
        require(runtime[key].replace('\\', '/') == original_root + '/simulation/' + name,
                'Unknown runtime source role: ' + key)
        runtime[key] = 'simulation/' + name
    return value


def check_csv(raw, report):
    rows = list(csv.DictReader(io.StringIO(raw.decode('ascii'), newline='')))
    expected = [(c['initial_primary_id'], t, q) for c in report['cases']
                for t, q in zip(c['charge_input']['time_since_initial_primary_ns'],
                                c['charge_input']['induced_equivalent_energy_keV'])]
    require(len(rows) == len(expected), 'Changed signed CSV sample census')
    for row, (eid, t, q) in zip(rows, expected):
        require(set(row) == {'initial_primary_id', 'time_since_initial_primary_ns', 'induced_equivalent_energy_keV'}, 'Changed CSV columns')
        exact(int(row['initial_primary_id']), eid, 'CSV initial ID')
        exact(float(row['time_since_initial_primary_ns']), t, 'CSV time')
        exact(float(row['induced_equivalent_energy_keV']), q, 'CSV signed charge')


def validate_semantics(science):
    exact(science['source']['counts'], COUNTS, 'saved counts')
    require(science['run']['status'] == 'completed' and science['run']['threads'] == 2 and
            science['run']['additional_radiation_calls'] == 0 and science['run']['field_solve_seconds'] == 0.0,
            'Changed completed engineering run')
    require([m['model_id'] for m in science['models']] == list(MODELS), 'Changed model census/order')
    totals = [0, 0, 0, 0]
    for model in science['models']:
        ident = model['model_id']; report = model['report']; ledger = model['truth_ledger']
        exact(report['readout_config'], CONFIG, 'census-only resolved configuration')
        exact(model['calibration']['config'], CONFIG, 'calibration configuration')
        exact(model['calibration']['calibration'], report['calibration'], 'independent injection')
        require(report['calibration_calls'] == 1 and report['native_calls'] == 2 and
                report['status'] == 'completed' and report['calibration']['energy_keV'] == 500.0,
                'Changed injection/native call accounting')
        exact(report['selected_ids'], SELECTED[ident], 'fixed cohort')
        require(len(ledger) == 20 and [r['initial_primary_id'] for r in ledger] == list(range(20)), 'Changed all-event ledger')
        cases = report['cases']
        require([c['initial_primary_id'] for c in cases] == SELECTED[ident], 'Changed response order')
        by_id = {c['initial_primary_id']: c for c in cases}
        samples = caps = 0
        for row in ledger:
            eid = row['initial_primary_id']; chosen = eid in SELECTED[ident]
            require(type(row['selected']) is bool and row['selected'] == chosen, 'Changed event selection')
            require(row['source_truth']['initial_primary_id'] == eid and row['source_truth']['event_id'] == eid, 'Changed truth identity')
            if not chosen:
                require(row['processing_status'] == 'unprocessed' and row['response'] is None, 'Unprocessed response must be null')
                continue
            case = by_id[eid]; exact(row['response'], case, 'selected saved response')
            require(row['processing_status'] == case['status'], 'Changed response status')
            t = case['charge_input']['time_since_initial_primary_ns']; q = case['charge_input']['induced_equivalent_energy_keV']
            require(len(t) == len(q) and len(t) >= 2, 'Changed charge input shape')
            samples += len(t); rd = case['readout']
            require(rd['input_sample_count'] == len(t), 'Changed input count')
            trace = rd['trace']; n = len(trace['time_ns'])
            require(1 <= n <= 600 and all(len(a) == n for a in trace.values()) and rd['original_sample_count'] > n, 'Changed compact trace convention')
            if case['zero_ge']:
                require(case['status'] == 'native_not_applicable_true_zero' and case['native'] is None and
                        case['transport_flags'] is None and rd['accepted'] is False and rd['adc_code'] == 0 and
                        rd['reconstructed_energy_keV'] is None, 'Changed true-zero bypass')
                exact(t, [0.0, 2.0], 'known zero input times'); exact(q, [0.0, 0.0], 'known zero input')
                totals[3] += 1
            else:
                require(case['status'] == 'native_completed' and rd['accepted'] is True and
                        type(rd['reconstructed_energy_keV']) is float and case['error'] is None, 'Changed positive saved response')
                exact(case['native']['times'], t, 'native input times'); exact(case['native']['signal'], q, 'signed native input')
                endpoints = [e for s in case['native']['steps'] for e in s['endpoints']]
                flags = dict(carrier_parcels=len(endpoints), geometric_contacts=sum(e['status'] == 'contact' for e in endpoints),
                             step_limits=sum(e['status'] == 'step_limit' for e in endpoints),
                             stopped_without_contact=sum(e['status'] == 'stopped_without_contact' for e in endpoints))
                exact(case['transport_flags'], flags, 'independent endpoint flags')
                caps += flags['step_limits']; totals[2] += 1
        require(samples == (10006 if ident == 'AK02' else 51), 'Changed original signed samples')
        require(caps == (195 if ident == 'AK02' else 0), 'Changed native cap accounting')
        totals[0] += len(ledger); totals[1] += len(cases)
    exact(totals, [40, 6, 4, 2], 'public engineering census')
    public_safe(science)


def read_saved_science(root=None):
    root = ROOT if root is None else root
    reader = Reader(root)
    local = lambda n: BASE + '/' + n
    receipts = {n: reader.json(local(n), pin) for n, pin in PINS.items()}
    parent = receipts['COMPLETE.json']; complete = receipts['example/COMPLETE.json']; run = receipts['example/run.json']
    require(parent['status'] == complete['status'] == run['status'] == 'completed', 'Nonterminal science authority')
    require(parent['science_complete_sha256'] == PINS['example/COMPLETE.json'] and
            complete['run_sha256'] == PINS['example/run.json'], 'Changed parent/run authority')
    exact(complete['source_pins'], run['source_pins'], 'original science source pins')
    expected_names = {m + '/' + n for m in MODELS for n in (
        'calibration.json', 'child.json', 'report.json', 'request.json', 'signals.csv', 'truth-ledger.jsonl', 'worker.log')}
    expected_names.update(m + '/event-' + str(e) + '.json' for m in MODELS for e in SELECTED[m])
    require(set(complete['artifacts']) == expected_names, 'Changed twenty-artifact inventory')
    raw = {name: reader.raw(local('example/' + name), item['sha256'], item['bytes'])
           for name, item in complete['artifacts'].items()}
    archive = receipts['EXECUTED-CODE-ARCHIVE-v2.json']
    require(archive['archive'] == 'executed-code-v2' and set(archive['files']) == set(EXECUTED), 'Changed executed snapshot census')
    archived_bytes = {}
    for name, item in archive['files'].items():
        require(complete['source_pins'][name] == item['sha256'], 'Executed source not pinned by science')
        archived_bytes[name] = reader.raw(local('executed-code-v2/' + name), item['sha256'], item['bytes'])
    baseline = decode(archived_bytes['simulation/readout_demo.json'])
    baseline.pop('max_total_samples')
    baseline.update(decode(archived_bytes['simulation/native_readout_profile.json'])['settings'])
    baseline.update(schema_version=2, expected_primary_count=3)
    exact(baseline, CONFIG, 'independent archived resolved configuration')
    # Current docs may legitimately change. Only archived execution bytes are checked above.
    portable, original_root, julia = portable_run(run)
    source = dict(original_commit='af0a1a093e61035b1f423870f7160aba331078b6',
                  receipt_pins=PINS.copy(), counts=complete['counts'], artifacts=complete['artifacts'],
                  source_pins=complete['source_pins'], executed_sources=archive['files'])
    science = dict(run=portable, source=source, models=[]); csv_files = {}
    for m in MODELS:
        report = decode(raw[m + '/report.json']); request = decode(raw[m + '/request.json'])
        ledger = [decode(line) for line in raw[m + '/truth-ledger.jsonl'].splitlines()]
        original_stream = '.local/m11b-gamma20-v1/' + m + '/stream/events-00000000.jsonl'
        events = reader.jsonl(original_stream, complete['source_pins'][original_stream])
        exact([r['source_truth'] for r in ledger], events, 'all original M11b truth')
        exact(request['events'], events, 'all request truth')
        exact(request['expected_calibration'], report['calibration'], 'saved expected injection')
        for case in report['cases']:
            exact(case, decode(raw[m + '/event-' + str(case['initial_primary_id']) + '.json']), 'original event artifact')
        csv_files[m + '-signals.csv'] = raw[m + '/signals.csv']; check_csv(csv_files[m + '-signals.csv'], report)
        science['models'].append(dict(model_id=m, truth_ledger=ledger,
            report=portable_report(report, original_root, julia), calibration=decode(raw[m + '/calibration.json']),
            source_manifest=request['source_manifest'], prepared_metadata=request['prepared']))
    validate_semantics(science)
    reader.recheck()
    return science, csv_files, reader


def current_sources(root=None):
    root = ROOT if root is None else root
    reader = Reader(root)
    values = {}
    for name in SOURCE_FILES:
        raw = reader.raw(name)
        values[name] = dict(sha256=sha(raw), bytes=len(raw))
    return values, reader


def verify_freeze(root=None):
    root = ROOT if root is None else root
    reader = Reader(root)
    exited = reader.json(ROUND + '/WRITER-EXIT.json')
    require(exited['status'] == 'exited' and exited['science_calls'] == 0, 'Writer has not exited')
    frozen = reader.json(ROUND + '/SOURCE-FREEZE.json')
    require(frozen['status'] == 'frozen_after_writer_exit' and
            frozen['writer_exit_sha256'] == reader.seen[ROUND + '/WRITER-EXIT.json'], 'Source freeze lacks writer exit')
    sources, source_reader = current_sources(root)
    for name, item in sources.items():
        exact(frozen['files'][name], item, 'frozen current source')
    reader.recheck()
    return sources, source_reader


def validate_data(data):
    require(set(data) == {'kind', 'schema_version', 'science', 'science_sha256', 'units', 'limitations', 'presentation'}, 'Changed public schema')
    require(data['kind'] == 'saved_gamma_native_showcase_v1' and data['schema_version'] == 1, 'Unsupported public example')
    exact(data['units'], UNITS, 'units'); exact(data['limitations'], list(LIMITATIONS), 'limitations')
    exact(data['science']['source']['receipt_pins'], PINS, 'immutable original authority')
    require(data['science_sha256'] == SCIENCE_SHA256 and typed_digest(data['science']) == SCIENCE_SHA256, 'Scientific payload differs from trusted saved values')
    validate_semantics(data['science'])
    binding = data['presentation']
    require(set(binding) == {'encoding', 'template_sha256', 'exporter_sha256', 'current_sources'} and
            binding['encoding'] == ENCODING and set(binding['current_sources']) == set(SOURCE_FILES), 'Changed historical source binding')
    for item in binding['current_sources'].values():
        require(set(item) == {'sha256', 'bytes'} and type(item['sha256']) is str and
                re.fullmatch(r'[0-9a-f]{64}', item['sha256']) and type(item['bytes']) is int and
                0 < item['bytes'] <= MAX_BYTES, 'Invalid historical source hash/size')
    require(binding['template_sha256'] == binding['current_sources'][TEMPLATE]['sha256'] and
            binding['exporter_sha256'] == binding['current_sources']['tools/gamma_showcase.py']['sha256'], 'Inconsistent generation source binding')
    # All eleven sources are checked at export/freeze. Historical nav/checker/test/
    # publisher/docs updates must not invalidate already-saved scientific bytes.
    template_reader = Reader(ROOT)
    template_reader.raw(TEMPLATE, binding['template_sha256'])
    template_reader.recheck(); public_safe(data)


def render(data, template=None):
    template = template if template is not None else relative(ROOT, TEMPLATE).read_bytes().decode('utf-8')
    require(template.count(TOKEN) == 1, 'Template placeholder census')
    embedded = canonical(data).decode('ascii').replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return template.replace(TOKEN, embedded).encode('utf-8')


def validate_bundle(directory):
    folder = no_links(directory)
    require(folder.is_dir() and {p.name for p in folder.iterdir()} == set(FILES) | {'publication.json'}, 'Partial/unexpected public inventory')
    reader = Reader(folder); manifest = reader.json('publication.json')
    require(set(manifest) == {'kind', 'status', 'science_sha256', 'source', 'presentation', 'files'}, 'Changed manifest schema')
    require(manifest['kind'] == 'saved_gamma_publication_v1' and manifest['status'] == 'completed' and
            set(manifest['files']) == set(FILES), 'Nonterminal/changed public manifest')
    require(all(set(item) == {'sha256', 'bytes'} for item in manifest['files'].values()), 'Changed file binding schema')
    public_safe(manifest)
    require(reader.raw('publication.json') == canonical(manifest), 'Noncanonical public manifest')
    payload = {n: reader.raw(n, item['sha256'], item['bytes']) for n, item in manifest['files'].items()}
    data = decode(payload['data.json']); validate_data(data)
    require(payload['data.json'] == canonical(data), 'Noncanonical public serialization')
    require(payload['gamma.html'] == render(data), 'HTML differs from frozen template and embedded data')
    exact(manifest['source'], data['science']['source'], 'public original provenance')
    exact(manifest['presentation'], data['presentation'], 'public presentation binding')
    require(manifest['science_sha256'] == SCIENCE_SHA256, 'Changed manifest scientific digest')
    for model in data['science']['models']:
        name = model['model_id'] + '-signals.csv'; check_csv(payload[name], model['report'])
        original = data['science']['source']['artifacts'][model['model_id'] + '/signals.csv']
        require(sha(payload[name]) == original['sha256'] and len(payload[name]) == original['bytes'], 'CSV is not exact original bytes')
    for raw in payload.values():
        require(not PRIVATE.search(raw.decode('utf-8')) and not CREDENTIAL.search(raw.decode('utf-8')), 'Private public bytes')
    reader.recheck()
    return data


def export_saved(output=None):
    output = no_links(output or ROOT / ROUND / 'bundle')
    require(output == no_links(ROOT / ROUND / 'bundle') and not output.exists(), 'Only a new M11d bundle destination is allowed')
    sources, source_reader = verify_freeze()
    science, csv_files, original_reader = read_saved_science()
    require(typed_digest(science) == SCIENCE_SHA256, 'Pinned saved science digest changed')
    data = dict(kind='saved_gamma_native_showcase_v1', schema_version=1, science=science,
                science_sha256=SCIENCE_SHA256, units=UNITS, limitations=list(LIMITATIONS),
                presentation=dict(encoding=ENCODING, template_sha256=sources[TEMPLATE]['sha256'],
                                  exporter_sha256=sources['tools/gamma_showcase.py']['sha256'], current_sources=sources))
    validate_data(data)
    payload = dict(csv_files, **{'data.json': canonical(data), 'gamma.html': render(data)})
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in payload.items():
        with relative(output, name).open('xb') as stream:
            stream.write(raw)
    original_reader.recheck(); source_reader.recheck(); verify_freeze()
    manifest = dict(kind='saved_gamma_publication_v1', status='completed', science_sha256=SCIENCE_SHA256,
                    source=science['source'], presentation=data['presentation'],
                    files={n: dict(sha256=sha(raw), bytes=len(raw)) for n, raw in sorted(payload.items())})
    with relative(output, 'publication.json').open('xb') as stream:
        stream.write(canonical(manifest))
    validate_bundle(output)
    return dict(status='completed_saved_export', events=40, selected=6, signed_samples=10057)


def assemble(source, target):
    source = no_links(source); target = no_links(target)
    validate_bundle(source)
    require(not target.exists(), 'Existing public gamma bundle requires explicit reconciliation')
    target.mkdir(parents=True)
    for name in (*FILES, 'publication.json'):
        shutil.copyfile(relative(source, name), relative(target, name))
    validate_bundle(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    sub.add_parser('export')
    check = sub.add_parser('validate'); check.add_argument('bundle', type=Path)
    args = parser.parse_args()
    if args.mode == 'export':
        result = export_saved()
    else:
        validate_bundle(args.bundle); result = dict(status='verified_saved_bundle', science_calls=0)
    print(json.dumps(result, sort_keys=True))
