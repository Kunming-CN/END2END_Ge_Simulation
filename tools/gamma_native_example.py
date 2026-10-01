"""Finite saved-gamma -> frozen native/electronics adapter; no transport/field solve."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

import charge_check as C
import replay_readout as R

ROOT = Path(__file__).resolve().parents[1]
KIND = 'source_gamma_native_example_v1'
BASE = '.local/m11c-gamma-native-v1'
SOURCE = '.local/m11b-gamma20-v1'
SELECTION = SOURCE + '/M11C-SELECTED-COHORT-PLAN.json'
SELECTION_SHA = 'df20b232577c86cb865fc5a95e2dc4c14fb6cacf3e0b29de8333686090b891c2'
BATCH = '.local/cs137-1m-native/config.json'
BATCH_SHA = '64db8f79fa4fae393b0e1abbdfb5e2ed30d44b48cd814a40a7f1bdddb16933de'
PROFILE = 'simulation/native_readout_profile.json'
WORKER = 'simulation/gamma_native_example.jl'
JULIA_SHA = '2bc629c180111abcf63fe2cfb98dedef9b6b63fe251ec939636b6460667c2469'
DETECTORS = {
    'AK02': dict(ids=[0, 4, 5], rows=[1, 21, 54], bias=500,
        model='793de4cc598a3e26d375525e683be1bc2072e117d1c6b8003f6cdcffc9925dfa',
        cache='2d5102499d30531d8ef6d03a79dc0bfe2f3c57e784457dc8d5da02ed53a670ac',
        manifest='ffde9366d0a779beff7e537c27954449b8802e82c471fc2691e37b8bd4ebf101'),
    'SAP22': dict(ids=[0, 2, 3], rows=[2, 17, 9], bias=700,
        model='614c72f31a5a84b82c69b0b11f6f0657e87d94f746312c151f9a08cd00ba3dc3',
        cache='39e8e121fcc696fad0686bac31710c53f28a2c7bc4102fdb57c70f6cb12dd804',
        manifest='7353bafc7e1a5c471036d2b976c0b3e8445bbda3e5725bed424a6b0406ed8251')}
SETTINGS = dict(parcels=16, seed_family=2609261, drift_dt_ns=2, drift_cap_ns=10000,
    temperature_K=77, diffusion=True, end_drift_when_no_field=False,
    self_repulsion=False, geometry_check=True)
CODE = tuple('simulation/' + n for n in (
    'gamma_native_example.jl', 'native_response.jl', 'native_boundary_guard.jl',
    'native_li_example.jl', 'native_stream.jl', 'readout.jl', 'readout_profiles.jl',
    'replay.jl', 'run.jl', 'native_readout_profile.json', 'readout_demo.json',
    'Project.toml', 'Manifest.toml', 'test_gamma_native_example.jl')) + (
    'tools/gamma_native_example.py', 'tools/test_gamma_native_example.py',
    'tools/GAMMA_NATIVE_EXAMPLE.md', 'tools/charge_check.py', 'tools/replay_readout.py')
SIGNAL_COLUMNS = ['initial_primary_id', 'time_since_initial_primary_ns', 'induced_equivalent_energy_keV']
FAILURES = ('Noncontact endpoint outside crystal', 'Invalid waveform support')
LIMITATIONS = [
    'Low-statistics nominal engineering integration; selected3 of20 initial gammas per model, not a spectrum or efficiency prediction.',
    'Original78K models, explicit existing77K field-cache override; no new fields or numerical convergence claim.',
    'AK02 Li collection accuracy remains unresolved; SAP22 is a differently shaped non-Li cross-check, not a matched experimental control.',
    'Independent synthetic charge-injection calibration, not experimental detector/hardware calibration or calibrated Li CCE.',
    'Weighted diffusion parcels are numerical samples, not physical Fano/noise/resolution; finite caps and endpoint flags remain.',
    'Signed charge/current/preamp/shaper and peak-ADC rejection retained; no rectification, per-event truth gain or success filtering.',
    'Numerical analog time grid is not waveform-digitizing acquisition; isolated gamma electronics reset, no pileup/live-time model.',
    'Scored radiation STEP chords and Track births are not complete trajectories; unscored energy closure/activity remain null.']


def decode(text):
    # The old charge decoder intentionally treats identity-named keys as scalar
    # integers; raw gamma column descriptors also use those names as objects.
    # Keep that old contract strict and validate gamma identities at their seams.
    def pairs(items):
        result={}
        for key,value in items:
            C.require(key not in result,'duplicate gamma JSON key: '+key,'invalid_json');result[key]=value
        return result
    def floating(token):
        value=float(token);C.number(value,'gamma JSON float');return value
    return json.loads(text,object_pairs_hook=pairs,parse_float=floating,
        parse_constant=lambda token:C.require(False,'nonfinite gamma JSON: '+token,'invalid_json'))


class Reader(C.Reader):
    """Existing path/hash/stamp/resource checks, additive gamma JSON semantics."""
    def json(self,relative):
        digest=self.digest(relative);path=self.path(relative)
        C.require(path.stat().st_size<=C.MAX_JSON,'gamma JSON exceeds bounded reader')
        raw=path.read_bytes();C.require(hashlib.sha256(raw).hexdigest()==digest,'gamma JSON parsed bytes differ from hash','changed_during_read')
        return C.object_value(decode(raw.decode('utf-8-sig')),str(relative))

    def jsonl(self,relative):
        digest=self.digest(relative);raw=self.path(relative).read_bytes()
        C.require(hashlib.sha256(raw).hexdigest()==digest,'gamma JSONL parsed bytes differ from hash','changed_during_read')
        lines=raw.decode('utf-8-sig').splitlines();C.require(len(lines)<=C.MAX_ROWS,'gamma JSONL row bound')
        for line in lines:
            C.require(len(line)<=C.MAX_LINE,'gamma JSONL line bound');yield C.object_value(decode(line),str(relative))


def exact(a, b, label):
    """Original truth preservation includes binary64 bits, boolean/integer identity."""
    if isinstance(a, dict) and isinstance(b, dict):
        C.equal(set(a), set(b), label + ' keys')
        for k in a:
            exact(a[k], b[k], label + '.' + k)
    elif isinstance(a, list) and isinstance(b, list):
        C.equal(len(a), len(b), label + ' length')
        for x, y in zip(a, b):
            exact(x, y, label)
    elif type(a) is float and type(b) is float:
        C.require(struct.pack('>d', a) == struct.pack('>d', b), label + ' binary64 changed')
    else:
        C.require(type(a) is type(b) and a == b, label + ' scalar changed')


def save(path, value, replace=False):
    path = Path(path)
    pending = path.with_name(path.name + '.pending')
    C.require(replace or not path.exists(), 'output exists: ' + str(path))
    with pending.open('x', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')
        f.flush(); os.fsync(f.fileno())
    if replace:
        os.replace(pending, path)
    else:
        os.link(pending, path); pending.unlink()


def local(reader, name):
    C.require(str(name).replace('\\', '/').startswith('.local/'), 'input must be project local')
    return reader.path(name)


def validate_events(events, m, prepared):
    C.equal(len(events), 20, 'full gamma census')
    C.equal(m['units'], dict(energy='keV', length='mm', time='ns'), 'gamma derived units')
    C.equal([m['raw_track_energy_unit'], m['raw_position_unit']], ['MeV', 'm'], 'gamma raw units')
    tr = m['coordinate_transform']; rot = tr['rotation_local_to_global']; shift = tr['translation_global_mm']
    C.equal(rot, [[1, 0, 0], [0, 0, 1], [0, -1, 0]], 'accepted gamma rotation')
    C.equal(shift, [0, 1.45, 0.29], 'accepted gamma translation')
    counters = {k: 0 for k in ('vtx', 'particles', 'tracks', *m['material_tables'])}
    process_ids = {r['procid'] for r in m['processes']}
    for eid, e in enumerate(events):
        C.fields(e, 'event_id initial_primary_id vtx particles tracks material_rows steps truth_ge_edep_keV zero_ge material_energy_keV'.split(), 'gamma event')
        C.integer(e['event_id'], 'event ID', eid, eid); C.integer(e['initial_primary_id'], 'initial ID', eid, eid)
        C.equal(set(e['material_rows']), set(m['material_tables']), 'all physical materials retained')
        tables = dict(vtx=e['vtx'], particles=e['particles'], tracks=e['tracks'], **e['material_rows'])
        for table, rows in tables.items():
            spec = m['raw_tables'][table]
            for row in rows:
                C.fields(row, {*spec['columns'], 'raw_row_index'}, 'raw row columns')
                C.integer(row['raw_row_index'], 'raw index', counters[table], counters[table]); counters[table] += 1
                C.integer(row['evtid'], 'raw event', eid, eid)
                for name, descriptor in spec['columns'].items():
                    if descriptor['dtype'].startswith(('int', 'uint')):
                        C.require(type(row[name]) is int, 'raw integer identity')
                    else:
                        C.number(row[name], 'raw scalar')
        v, p = e['vtx'], e['particles']
        C.require(len(v) == len(p) == 1 and v[0]['n_part'] == 1 and p[0]['vertexid'] == 0, 'one initial gamma')
        C.equal(v[0]['time'], 0.0, 'gamma primary time zero'); C.equal(p[0]['particle'], 22, 'gamma PDG')
        for a, expected in zip(('px', 'py', 'pz'), (0.0, -0.662, 0.0)):
            C.close(p[0][a], expected, 'gamma direction/momentum', absolute=1e-12)
        C.close(p[0]['ekin'], 0.662, 'initial raw MeV', absolute=1e-12)
        for a, expected in zip(('xloc', 'yloc', 'zloc'), m['source_position_global_mm']):
            C.close(1000 * v[0][a], expected, 'initial source position', absolute=1e-10)
        tracks = {t['trackid']: t for t in e['tracks']}
        C.equal(len(tracks), len(e['tracks']), 'unique track IDs')
        roots = [t for t in e['tracks'] if t['parent_trackid'] == 0]
        C.require(len(roots) == 1 and roots[0]['time'] == 0 and roots[0]['particle'] == 22, 'gamma root identity/time')
        for t in e['tracks']:
            C.integer(t['trackid'], 'track ID', 1); C.integer(t['parent_trackid'], 'parent ID')
            C.require(t['time'] >= 0 and t['ekin'] >= 0 and (t['parent_trackid'] == 0 or t['procid'] in process_ids), 'track physics/creation process')
            parent = t['parent_trackid']; seen = {t['trackid']}
            while parent:
                C.require(parent in tracks and parent not in seen and t['time'] + 1e-12 >= tracks[parent]['time'], 'track ancestry/time')
                seen.add(parent); parent = tracks[parent]['parent_trackid']
        sums = {}
        for table, rows in e['material_rows'].items():
            material = m['material_tables'][table]
            sums.setdefault(material, [])
            for row in rows:
                C.require(row['trackid'] in tracks, 'material parent track missing')
                t = tracks[row['trackid']]
                C.equal([row['particle'], row['parent_trackid']], [t['particle'], t['parent_trackid']], 'material ancestry')
                C.require(row['edep'] >= 0 and row['time'] >= 0 and row['time'] + 1e-12 >= t['time'], 'deposit energy/birth time')
                sums.setdefault(material, []).append(row['edep'])
        C.equal(e['material_energy_keV'], {k: math.fsum(v) for k, v in sums.items()}, 'all material energy sums')
        C.require(math.fsum(e['material_energy_keV'].values()) <= 662 + 1e-7, 'recorded-only energy bound')
        raw_ge = e['material_rows']['stp/germanium']; C.equal(len(e['steps']), len(raw_ge), 'whole Ge rows, including zeros')
        for s, raw in zip(e['steps'], raw_ge):
            C.fields(s, 'raw_row_index energy_keV time_ns track_id parent_track_id particle_pdg global_position_m position_mm pre_position_mm post_position_mm boundary_classifications'.split(), 'derived Ge step')
            for alias, rawkey in (('raw_row_index', 'raw_row_index'), ('energy_keV', 'edep'), ('time_ns', 'time'),
                    ('track_id', 'trackid'), ('parent_track_id', 'parent_trackid'), ('particle_pdg', 'particle')):
                exact(s[alias], raw[rawkey], 'Ge raw alias')
            exact(s['global_position_m'], [raw[a] for a in ('xloc', 'yloc', 'zloc')], 'raw global position')
            for suffix, name in (('', 'position_mm'), ('_pre', 'pre_position_mm'), ('_post', 'post_position_mm')):
                global_mm = [1000 * raw[a + suffix] - shift[i] for i, a in enumerate(('xloc', 'yloc', 'zloc'))]
                expected = [sum(rot[j][i] * global_mm[j] for j in range(3)) for i in range(3)]
                C.equal(len(s[name]), 3, 'local position dimension')
                for x, y in zip(s[name], expected): C.close(x, y, 'raw to local mm', absolute=1e-10)
            C.require(set(s['boundary_classifications']) == {'deposit', '_pre', '_post'} and
                all(v in ('inside', 'surface') for v in s['boundary_classifications'].values()), 'retained Ge membership')
        energy = math.fsum(r['edep'] for r in raw_ge)
        exact(energy, e['truth_ge_edep_keV'], 'raw truth Ge energy')
        C.require(type(e['zero_ge']) is bool and e['zero_ge'] == (energy == 0), 'true zero semantics')
    for table, n in counters.items(): C.equal(n, m['raw_tables'][table]['rows'], 'complete raw table census')


def load_inputs(root=ROOT):
    reader = Reader(root)
    reader.digest(SELECTION, SELECTION_SHA); selection = reader.json(SELECTION)
    reader.digest(BATCH, BATCH_SHA); batch = reader.json(BATCH)
    C.equal(batch['settings'], {k: SETTINGS[k] for k in ('drift_cap_ns', 'drift_dt_ns', 'parcels', 'seed_family', 'temperature_K')}, 'exact cache settings')
    reader.digest(PROFILE, C.ES_DEFAULTS[PROFILE]); profile = reader.json(PROFILE)
    config = R.expected_config(reader, profile, 3)
    plans = []
    for model, spec in DETECTORS.items():
        prefix = SOURCE + '/' + model
        reader.digest(prefix + '/stream/manifest.json', spec['manifest']); m = reader.json(prefix + '/stream/manifest.json')
        C.equal([m['kind'], m['schema_version'], m['status'], m['primary_count'], m['initial_primary_id_range']],
            ['scenario_gamma_event_stream_v1', 1, 'complete', 20, [0, 19]], 'completed gamma stream')
        C.integer(m['schema_version'],'stream schema',1,1);C.integer(m['primary_count'],'radiation census',20,20)
        C.equal([m['model_id'], m['clock_policy'], m['source_count_unit']], [model, 'synthetic_primary_time_zero', 'initial synthetic gamma primaries'], 'gamma identity/clock/count unit')
        C.equal([m['stored_temperature_K'], m['stored_contacts'], m['readout_contact_id']],
            [78, [dict(id=1, potential_V=0), dict(id=2, potential_V=spec['bias'])], 1], 'original detector state')
        reader.digest('models/' + model + '.yaml', spec['model'])
        prepared = reader.json(prefix + '/prepared.json'); reader.digest(prefix + '/prepared.json', m['prepared_sha256'])
        run = reader.json(prefix + '/run.json'); reader.digest(prefix + '/run.json', m['run_sha256'])
        reader.digest(prefix + '/truth.lh5', m['source_lh5_sha256'])
        extract = reader.json(prefix + '/stream/extract-receipt.json')
        C.equal([run['kind'], run['status'], run['prepared_sha256'], run['source_lh5_sha256'], run['returncode']],
            ['scenario_gamma_transport_run_v1', 'complete', m['prepared_sha256'], m['source_lh5_sha256'], 0], 'completed gamma run')
        C.equal([extract['kind'], extract['status'], extract['run_sha256']], [m['kind'], 'complete', m['run_sha256']], 'completed gamma extraction')
        C.equal(m['assets'], prepared['assets'], 'source-aware assets'); C.equal(m['coordinate_transform'], prepared['coordinate_transform'], 'prepared transform')
        C.equal(m['transport_source_sha256'], run['transport_source_sha256'], 'gamma producer pins')
        C.equal(m['prepared_source_sha256'], prepared['source_sha256'], 'gamma preparation pins')
        source = m['assets']['source']
        C.equal([source['pdg'], source['kinetic_energy_keV'], source['direction_global'], source['time_ns'], source['clock_policy']],
            [22, 662, [0, -1, 0], 0, 'synthetic_primary_time_zero'], 'source assets')
        C.equal(m['assets']['detector']['model_sha256'], spec['model'], 'gamma model binding')
        for pins in (m['transport_source_sha256'], m['prepared_source_sha256']):
            for n, digest in pins.items(): reader.digest(n, digest)
        C.require(len(m['chunks']) == 1, 'one finite gamma chunk'); chunk = m['chunks'][0]
        C.equal([chunk['file'], chunk['count'], chunk['first_initial_primary_id']], ['events-00000000.jsonl', 20, 0], 'gamma chunk identity')
        chunkfile = prefix + '/stream/' + chunk['file']; reader.digest(chunkfile, chunk['sha256'])
        events = list(reader.jsonl(chunkfile)); validate_events(events, m, prepared)
        ids = [next(e['event_id'] for e in events if e['zero_ge']), *[e['event_id'] for e in events if not e['zero_ge']][:2]]
        C.equal(ids, spec['ids'], 'pre-outcome cohort')
        cohort = selection['cases'][model]
        C.equal([cohort['source_manifest_sha256'], cohort['source_chunk_sha256'], cohort['radiation_census'], cohort['selected_ids']],
            [spec['manifest'], chunk['sha256'], 20, ids], 'predeclared selection')
        C.equal([len(events[i]['steps']) for i in ids], spec['rows'], 'whole selected Ge row counts')
        C.equal(cohort['unprocessed_ids'], [i for i in range(20) if i not in ids], 'all remaining unprocessed')
        cache = '.local/cs137-1m-native/cache/' + model + '.jls'; reader.digest(cache, spec['cache'])
        C.equal(batch['models'][model]['cache_sha256'], spec['cache'], 'cache reference identity')
        plans.append(dict(kind=KIND, schema_version=1, model_id=model, model_sha256=spec['model'],
            source_manifest=m, prepared=prepared, events=events, selected_ids=ids, radiation_primary_count=20,
            source_temperature_K=78, cached_temperature_K=77, bias_V=spec['bias'], readout_contact_id=1,
            cache_file=cache, cache_sha256=spec['cache'], expected_field_fingerprint=batch['models'][model]['expected_field_fingerprint'],
            expected_calibration=batch['models'][model]['expected_calibration'], readout_config=config, settings=SETTINGS))
    for name in CODE: reader.digest(name)
    reader.recheck()
    return reader, plans


def julia_executable():
    # Same existing launcher path; exact recorded installed executable, no install.
    exe = Path(R.julia_executable())
    C.equal(hashlib.sha256(exe.read_bytes()).hexdigest(), JULIA_SHA, 'existing recorded Julia executable')
    return str(exe)


def child(arguments, cwd, threads):
    env = dict(os.environ, JULIA_NUM_THREADS=str(threads), OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
        MKL_NUM_THREADS='1', JULIA_PKG_OFFLINE='true', JULIA_LOAD_PATH='@;@stdlib' if os.name == 'nt' else '@:@stdlib',
        PYTHONDONTWRITEBYTECODE='1')
    started = time.perf_counter()
    p = subprocess.run(arguments, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=1800, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    C.require(len(p.stdout) <= 4 * 1024 * 1024, 'worker log exceeded bound')
    return dict(arguments=arguments, exit_code=p.returncode, wall_seconds=time.perf_counter()-started,
        output=p.stdout.decode('utf-8', errors='replace'))


def truth_ledger(plan, cases):
    byid = {c['initial_primary_id']: c for c in cases}
    return [dict(initial_primary_id=e['initial_primary_id'], selected=e['initial_primary_id'] in plan['selected_ids'],
        processing_status=byid[e['initial_primary_id']]['status'] if e['initial_primary_id'] in byid else 'unprocessed',
        source_truth=e, response=byid.get(e['initial_primary_id'])) for e in plan['events']]


def write_products(directory, plan, report):
    with (directory / 'truth-ledger.jsonl').open('x', encoding='utf-8', newline='\n') as f:
        for row in truth_ledger(plan, report['cases']): f.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
        f.flush(); os.fsync(f.fileno())
    with (directory / 'signals.csv').open('x', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, lineterminator='\n'); writer.writerow(SIGNAL_COLUMNS)
        for case in report['cases']:
            wave = case['charge_input']
            if wave is not None:
                for t, q in zip(wave['time_since_initial_primary_ns'], wave['induced_equivalent_energy_keV']):
                    writer.writerow([case['initial_primary_id'], t, q])
        f.flush(); os.fsync(f.fileno())
    save(directory / 'calibration.json', dict(calibration=report['calibration'], config=report['readout_config'],
        ionisation_energy_eV=report['ionisation_energy_eV'], calibration_calls=report['calibration_calls'],
        method_scope='one separate delta-charge injection for this detector, fixed across its three selected events'))


def inventory(directory):
    return {p.relative_to(directory).as_posix(): dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(), bytes=p.stat().st_size)
        for p in sorted(directory.rglob('*')) if p.is_file() and p.relative_to(directory).as_posix() not in ('COMPLETE.json', 'run.json')}


def verify_report(report, plan, threads):
    C.equal([report['kind'], report['schema_version'], report['model_id'], report['selected_ids']],
        [KIND, 1, plan['model_id'], plan['selected_ids']], 'gamma response identity')
    C.require(report['status'] in ('completed', 'completed_with_native_failures'), 'terminal gamma response')
    C.equal(report['settings'], SETTINGS, 'native settings')
    exact(report['readout_config'], plan['readout_config'], 'independent typed resolved config semantics')
    C.equal(report['calibration'], plan['expected_calibration'], 'independent injection identity')
    C.equal([report['calibration_calls'], report['native_calls'], report['field_solve_seconds']], [1, 2, 0.0], 'bounded actual calls')
    C.equal(report['field_fingerprint_before'], plan['expected_field_fingerprint'], 'cached initial fields')
    C.equal(report['field_fingerprint_after'], plan['expected_field_fingerprint'], 'cached final fields')
    runtime = report['runtime']; C.equal([runtime['threads'], runtime['blas_threads'], runtime['executable_sha256'], runtime['ssd_loaded']], [threads, 1, JULIA_SHA, True], 'actual gamma runtime')
    C.equal([runtime['environment']['julia_version'], runtime['environment']['ssd_version'], runtime['readout_environment']['json_version']], ['1.13.0', '0.11.8', '1.9.0'], 'actual versions')
    C.equal(report['guard']['native_source_sha256'], runtime['native_drift_sha256'], 'existing native guard/runtime identity')
    C.require(report['guard']['installed'] is True and report['guard']['package_files_modified'] is False, 'process-local native guard')
    C.equal([c['initial_primary_id'] for c in report['cases']], plan['selected_ids'], 'no outcome filtering')
    failed = 0; accepted = 0; rejected = 0
    for case in report['cases']:
        C.integer(case['initial_primary_id'],'response initial ID',0,19);C.integer(case['event_id'],'response event ID',0,19)
        e = plan['events'][case['initial_primary_id']]
        exact(case['truth_ge_edep_keV'], e['truth_ge_edep_keV'], 'truth response binding')
        C.equal(case['raw_row_indices'], [s['raw_row_index'] for s in e['steps']], 'all response input rows')
        exact(case['deposition_delays_ns'], [s['time_ns'] for s in e['steps']], 'initial-gamma deposition delays')
        C.equal([case['event_id'], case['primary_time_ns'], case['clock_policy'], case['zero_ge']], [e['event_id'], 0.0, 'synthetic_primary_time_zero', e['zero_ge']], 'response gamma clock/identity')
        C.require('global_decay_id' not in case, 'no fabricated decay ID')
        expected_seeds=[dict(raw_row_index=s['raw_row_index'],parcels=[dict(parcel_index=i,
            seed_uint64_decimal=str(int.from_bytes(hashlib.sha256(f"2609261/{e['event_id']}/{s['raw_row_index']}/{i}".encode()).digest()[:8],'big')))
            for i in range(1,17)]) for s in e['steps'] if s['energy_keV']>0]
        C.equal(case['parcel_seeds'],expected_seeds,'original independent parcel seeds')
        if case['status'] == 'native_failed':
            failed += 1; C.require(not e['zero_ge'] and report['native_failure_policy'] == 'record', 'declared recorded failure')
            C.require(case['error']['type'] == 'ArgumentError' and case['error']['message'] in FAILURES and
                case['error']['stage'] == 'NativeLiExample.native_event' and case['error']['exact_error'] == 'ArgumentError: ' + case['error']['message'], 'exact native-domain failure')
            for key in ('native', 'transport_flags', 'charge_input', 'final_induced_keV', 'charge_end_ns', 'readout'):
                C.require(case[key] is None, 'native failure unknown must remain null')
            continue
        C.require(case['error'] is None and case['charge_input'] is not None and case['readout'] is not None, 'completed known response')
        wave=case['charge_input']; t=wave['time_since_initial_primary_ns']; q=wave['induced_equivalent_energy_keV']
        C.require(len(t) == len(q) >= 2 and t[0] == q[0] == 0 and all(math.isfinite(x) for x in (*t, *q)), 'signed waveform support')
        C.require(all(math.isclose(b-a, 2, abs_tol=1e-9, rel_tol=0) for a,b in zip(t,t[1:])), 'native primary-relative grid')
        C.equal([case['charge_end_ns'], case['final_induced_keV']], [t[-1], q[-1]], 'terminal weighted charge')
        if e['zero_ge']:
            C.equal(case['status'], 'native_not_applicable_true_zero', 'truezero bypass status')
            C.require(case['native'] is case['transport_flags'] is None and t == [0.0, 2.0] and q == [0.0, 0.0], 'no fabricated zero drift/endpoints')
        else:
            C.equal(case['status'], 'native_completed', 'positive native status')
            exact(case['native']['times'], t, 'signed times'); exact(case['native']['signal'], q, 'signed charge')
            C.equal([s['raw_row_index'] for s in case['native']['steps']], [s['raw_row_index'] for s in e['steps'] if s['energy_keV'] > 0], 'all positive native rows')
            endpoints=[]
            for s in case['native']['steps']:
                raw=next(x for x in e['steps'] if x['raw_row_index']==s['raw_row_index'])
                C.equal([s['deposited_energy_keV'],s['deposition_delay_ns'],s['parcel_weight_keV']],
                    [raw['energy_keV'],raw['time_ns'],raw['energy_keV']/16],'unchanged native energy weights/delay')
                endpoints.extend(s['endpoints'])
                C.require(all(type(x['parcel_index']) is int and 1<=x['parcel_index']<=16 for x in s['endpoints']),'native parcel endpoint identity')
            C.equal(case['transport_flags'],dict(carrier_parcels=len(endpoints),
                geometric_contacts=sum(bool(x['contact_ids']) for x in endpoints),step_limits=sum(x['step_limit_reached'] for x in endpoints),
                stopped_without_contact=sum(x['status']=='stopped_without_contact' for x in endpoints)),'independent native endpoint/cap flags')
        r = case['readout']; C.require(type(r['accepted']) is bool and r['current_balance']['passed'] is True, 'electronics validity/current balance')
        C.equal(r['negative_input'], any(v < 0 for v in q), 'signed input flag')
        C.equal(r['input_sample_count'], len(t), 'all signed input samples')
        C.close(r['analog_energy_keV'], r['peak_V']/report['calibration']['volts_per_keV'], 'fixed injection slope')
        C.integer(r['adc_code'],'diagnostic peak ADC code',0,2**plan['readout_config']['adc_bits']-1)
        full=plan['readout_config']['adc_full_scale_V'];lsb=report['calibration']['adc_lsb_V']
        expected_code=0 if r['peak_V']<=0 else 2**plan['readout_config']['adc_bits']-1 if r['peak_V']>=full else math.floor(r['peak_V']/lsb)
        C.equal(r['adc_code'],expected_code,'retained diagnostic peak ADC code')
        if r['accepted']:
            accepted += 1; C.close(r['reconstructed_energy_keV'], (r['adc_code']+.5)*report['calibration']['adc_lsb_V']/report['calibration']['volts_per_keV'], 'fixed peak ADC energy')
        else:
            rejected += 1; C.require(r['reconstructed_energy_keV'] is None, 'rejected Erec null; diagnostic ADC code retained')
    C.equal(report['counts'], dict(radiation_primaries=20, selected_primaries=3, unprocessed_primaries=17,
        selected_true_zeros=1, native_calls=2, native_failed=failed, native_completed=2-failed,
        readout_completed=3-failed, readout_accepted=accepted, electronics_rejected=rejected), 'independent response census')
    C.equal(report['status'], 'completed_with_native_failures' if failed else 'completed', 'native-failure terminal status')


def run_example(output=BASE+'/example', threads=2, policy='abort', root=ROOT, runner=child, executable=julia_executable):
    C.require(type(threads) is int and threads in (1,2) and policy in ('abort','record'), 'bounded thread/policy choice')
    reader, plans = load_inputs(root); dest = local(reader, output)
    C.require(Path(output).parent.as_posix() == BASE and not dest.exists(), 'one new output root directly under '+BASE)
    exe = executable(); reader.recheck(); dest.mkdir() # exclusive reservation
    pins = {n: v[0] for n,v in reader.watched.items()}
    receipt = dict(kind=KIND, schema_version=1, status='running', threads=threads, native_failure_policy=policy,
        source_pins=pins, selection_sha256=SELECTION_SHA, limitations=LIMITATIONS, stages=[],
        python_runtime=dict(executable=sys.executable, version=sys.version, executable_sha256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()),
        field_solve_seconds=0.0, additional_radiation_calls=0)
    save(dest/'run.json', receipt); phase='initialize'; started=time.perf_counter()
    try:
        for plan in plans:
            model=plan['model_id']; directory=dest/model; directory.mkdir(); phase=model+'_request'
            request=dict(plan, pins=pins, threads=threads, native_failure_policy=policy, julia_executable_sha256=JULIA_SHA)
            save(directory/'request.json', request); reader.recheck()
            args=[exe,'--startup-file=no','--project='+str(Path(root)/'simulation'),'--threads='+str(threads),
                '--compiled-modules=existing',str(reader.path(WORKER)),'--request',str(directory/'request.json'),'--output',str(directory)]
            phase=model+'_worker'; call=runner(args,str(root),threads)
            (directory/'worker.log').write_text(call.pop('output'),encoding='utf-8'); save(directory/'child.json',call)
            receipt['stages'].append(dict(model_id=model,**call)); reader.recheck()
            C.equal(call['exit_code'],0,'gamma worker exit; failure artifacts retained')
            out=Reader(directory); report=out.json('report.json'); verify_report(report,plan,threads)
            phase=model+'_saved_products'; write_products(directory,plan,report)
            save(dest/'run.json',receipt,replace=True)
        reader.recheck(); receipt['status']='completed_with_native_failures' if any(Reader(dest/p['model_id']).json('report.json')['status']=='completed_with_native_failures' for p in plans) else 'completed'
        receipt['orchestration_seconds']=time.perf_counter()-started
        save(dest/'run.json',receipt,replace=True)
        verify_example(dest,root=root,require_complete=False)
        save(dest/'COMPLETE.json',dict(kind=KIND,schema_version=1,status=receipt['status'],artifacts=inventory(dest),
            run_sha256=hashlib.sha256((dest/'run.json').read_bytes()).hexdigest(),source_pins=pins,
            counts=dict(radiation_primaries=40,selected_primaries=6,unprocessed_primaries=34,native_calls=4,injection_calibrations=2)))
        return dict(status=receipt['status'],output=str(dest),native_calls=4,injection_calibrations=2)
    except BaseException as error:
        receipt.update(status='failed',failure_stage=phase,error=str(error),orchestration_seconds=time.perf_counter()-started)
        save(dest/'run.json',receipt,replace=True)
        raise


def verify_example(directory, root=ROOT, require_complete=True):
    reader, plans=load_inputs(root); directory=Path(directory).resolve(); out=Reader(directory)
    C.require(directory.parent == (Path(root)/BASE).resolve(), 'gamma saved output boundary')
    run=out.json('run.json'); C.require(run['status'] in ('completed','completed_with_native_failures'), 'gamma completed orchestration')
    C.equal([run['kind'],run['schema_version'],run['selection_sha256'],run['field_solve_seconds'],run['additional_radiation_calls']],
        [KIND,1,SELECTION_SHA,0.0,0], 'orchestration contract')
    C.require(type(run['threads']) is int and run['threads'] in (1,2) and run['native_failure_policy'] in ('abort','record'),'bounded recorded thread/policy')
    expected_pins={n:v[0] for n,v in reader.watched.items()}; C.equal(run['source_pins'],expected_pins,'all frozen input/source pins')
    if require_complete:
        complete=out.json('COMPLETE.json'); C.equal(complete['artifacts'],inventory(directory),'exact completed inventory')
        C.equal(complete['run_sha256'],out.digest('run.json'),'completed run binding'); C.equal(complete['source_pins'],expected_pins,'complete source pins')
        C.equal([complete['kind'],complete['schema_version'],complete['status'],complete['counts']],
            [KIND,1,run['status'],dict(radiation_primaries=40,selected_primaries=6,unprocessed_primaries=34,native_calls=4,injection_calibrations=2)],'completed census/identity')
    C.equal([s['model_id'] for s in run['stages']],list(DETECTORS),'serial detector stage order')
    any_failed=False
    for index,plan in enumerate(plans):
        model=plan['model_id']; prefix=model+'/'; request=out.json(prefix+'request.json')
        exact(request,dict(plan,pins=expected_pins,threads=run['threads'],native_failure_policy=run['native_failure_policy'],julia_executable_sha256=JULIA_SHA),'entire gamma request typed semantics')
        report=out.json(prefix+'report.json'); verify_report(report,plan,run['threads'])
        C.equal(report['native_failure_policy'],run['native_failure_policy'],'recorded worker policy')
        any_failed=any_failed or report['status']=='completed_with_native_failures'
        C.equal(report['request_sha256'],out.digest(prefix+'request.json'),'worker request provenance')
        for case in report['cases']: exact(out.json(prefix+'event-'+str(case['initial_primary_id'])+'.json'),case,'completed event evidence')
        exact(list(out.jsonl(prefix+'truth-ledger.jsonl')),truth_ledger(plan,report['cases']),'whole20 truth/status ledger')
        calibration=out.json(prefix+'calibration.json'); exact(calibration['config'],plan['readout_config'],'rehashed typed effective config gate')
        C.equal(calibration['calibration'],report['calibration'],'separate detector calibration binding'); C.equal(calibration['calibration_calls'],1,'one new independent injection')
        expected=[]
        for case in report['cases']:
            if case['charge_input'] is not None:
                w=case['charge_input']; expected.extend([case['initial_primary_id'],t,q] for t,q in zip(w['time_since_initial_primary_ns'],w['induced_equivalent_energy_keV']))
        actual=[[int(r[0]),float(r[1]),float(r[2])] for r in out.csv(prefix+'signals.csv',SIGNAL_COLUMNS)]
        exact(actual,expected,'all full signed charge samples/no failed waveform')
        stage=run['stages'][index]
        child_record=out.json(prefix+'child.json');C.equal(child_record,{k:v for k,v in stage.items() if k!='model_id'},'saved child/stage provenance')
        C.equal(child_record['exit_code'],0,'saved successful child')
        args=child_record['arguments'];C.equal(args[1:],['--startup-file=no','--project='+str(Path(root)/'simulation'),
            '--threads='+str(run['threads']),'--compiled-modules=existing',str(reader.path(WORKER)),
            '--request',str(directory/model/'request.json'),'--output',str(directory/model)],'exact native-only worker command')
        C.equal(hashlib.sha256(Path(args[0]).read_bytes()).hexdigest(),JULIA_SHA,'saved installed Julia executable')
    C.equal(run['status'],'completed_with_native_failures' if any_failed else 'completed','whole run failure accounting')
    reader.recheck();out.recheck()
    return dict(kind=KIND,status=run['status'],radiation_primaries=40,selected_primaries=6,unprocessed_primaries=34)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='mode',required=True)
    sub.add_parser('check'); run=sub.add_parser('run'); run.add_argument('--output',default=BASE+'/example')
    run.add_argument('--threads',type=int,choices=(1,2),default=2); run.add_argument('--native-failure-policy',choices=('abort','record'),default='abort')
    verify=sub.add_parser('verify'); verify.add_argument('output')
    args=parser.parse_args(argv)
    if args.mode=='check':
        _,plans=load_inputs(); result=dict(status='checked_no_execution',models=[p['model_id'] for p in plans],radiation_primaries=40,selected_primaries=6,native_calls=0,injection_calibrations=0)
    elif args.mode=='run': result=run_example(args.output,args.threads,args.native_failure_policy)
    else: result=verify_example(args.output)
    print(json.dumps(result,sort_keys=True));return result


if __name__=='__main__': main()
