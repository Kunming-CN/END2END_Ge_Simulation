"""Selected saved-HDF5 pilot export. Never launches transport or native response."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import subprocess
import time

import h5py
import numpy as np
import analyze_million as A

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'transport'))
import cs137 as C
import handoff as H

BASE = ROOT / '.local/native-bridge-pilot'
ANALYSIS = ROOT / '.local/million-analysis/analysis-results'
KIND = 'selected_native_hdf5_pilot_v1'
MILLION = 'cs137-1m'
OLD = 'cs10000-v2-diagnostic'
OWN = ('tools/native_hdf5_bridge.py', 'tools/test_native_hdf5_bridge.py',
       'tools/NATIVE_BRIDGE.md', 'simulation/native_bridge_pilot.jl',
       'simulation/test_native_bridge_pilot.jl')
HELPERS = ('tools/analyze_million.py', 'tools/hit_event_view.py',
           'transport/cs137.py', 'transport/handoff.py')
require = A.require
sha = A.sha
read = A.read


def relative(path):
    p = Path(path).resolve()
    require(p.is_relative_to(ROOT), 'Dependency outside project')
    return p.relative_to(ROOT).as_posix()


def pin(pins, path, expected=None):
    digest = sha(path)
    require(expected is None or digest == expected, 'Source hash mismatch: '+relative(path))
    pins[relative(path)] = digest
    return digest


def check_pins(pins):
    for name, digest in pins.items():
        p = (ROOT/name).resolve()
        require(p.is_relative_to(ROOT), 'Escaping dependency')
        require(sha(p) == digest, 'Changed dependency: '+name)


def source_hashes():
    files = list(OWN)+list(HELPERS)
    # Freeze all small computation sources, including included helpers and model inputs.
    files += [relative(p) for folder in ('simulation', 'transport', 'models')
              for p in (ROOT/folder).glob('*') if p.is_file()]
    return {n: sha(ROOT/n) for n in sorted(set(files))}


def parcel_seed(event, row, parcel, seed=2609261):
    return int.from_bytes(hashlib.sha256(f'{seed}/{event}/{row}/{parcel}'.encode()).digest()[:8], 'big')


def step(raw, meta):
    coords = {s: [raw[a+s] for a in ('xloc', 'yloc', 'zloc')] for s in ('', '_pre', '_post')}
    local = {s: H.to_local(v, meta['coordinate_transform']).tolist() for s, v in coords.items()}
    labels = {s or 'deposit': H.membership(meta['contour_rz_mm'], v) for s, v in local.items()}
    require('outside' not in labels.values(), 'Ge row outside pinned contour')
    return dict(raw_row_index=raw['raw_row_index'], raw=raw,
                energy_keV=raw['edep'], time_ns=raw['time'], track_id=raw['trackid'],
                parent_track_id=raw['parent_trackid'], particle_pdg=raw['particle'],
                global_position_m=coords[''], position_mm=local[''],
                pre_position_mm=local['_pre'], post_position_mm=local['_post'],
                boundary_classifications=labels)


def validate_event(e, meta, namespace):
    """Independent aliases/ranges/group/zero checks, even on rehashed JSON."""
    require(namespace in (MILLION, OLD) and e['namespace'] == namespace, 'Wrong namespace')
    identity = e['identity']
    require(identity['model_id'] == meta['model_id'], 'Wrong model identity')
    for key in ('chunk_index', 'global_offset', 'local_primary_id', 'global_primary_id', 'chunk_count'):
        require(type(identity[key]) is int and identity[key] >= 0, 'Invalid integer identity: '+key)
    local, glob = identity['local_primary_id'], identity['global_primary_id']
    require(0 <= local < identity['chunk_count'] <= 10000 and
            glob == identity['global_offset']+local and
            identity['global_offset'] == identity['chunk_index']*10000, 'Primary range mapping')
    require(e['event_id'] == e['global_decay_id'] == glob and
            e['seed_event_id'] == glob and type(e['event_id']) is int, 'Changed event/seed ID')
    require(0 <= glob < (1000000 if namespace == MILLION else 10000), 'Global range')
    require(e['seed_family'] == 2609261, 'Changed native seed family')
    rows = [s['raw_row_index'] for s in e['steps']]
    require(rows == sorted(set(rows)) and all(type(i) is int and i >= 0 for i in rows), 'Raw row identity')
    for s in e['steps']:
        r = s['raw']
        require(r['evtid'] == local and type(r['evtid']) is int, 'Foreign raw primary')
        require(s == step(r, meta), 'Raw alias/coordinate/energy/time mismatch')
        require(math.isfinite(s['energy_keV']) and s['energy_keV'] >= 0 and
                math.isfinite(s['time_ns']) and s['time_ns'] >= 0, 'Invalid energy/time')
    energy = math.fsum(s['energy_keV'] for s in e['steps'])
    require(e['ge_energy_keV'] == energy and e['zero_ge'] is (energy == 0), 'Energy/zero mismatch')
    require(math.isclose(e['material_energy_keV']['G4_Ge'], energy, rel_tol=1e-12, abs_tol=1e-9), 'Material energy mismatch')
    C.validate_group_map(e['steps'], e['pulse_groups'], meta['grouping_policy']['horizon_ns'])
    require(bool(e['pulse_groups']) == (energy > 0), 'Zero/group mismatch')
    require(e['raw_table'] == 'stp/germanium' and len(e['source_lh5_sha256']) == 64, 'Raw provenance')
    return e


def extract_selected(path, plan, meta, raw_hash, selected):
    """Read selected rows only; retain every column and all zero-energy Ge rows."""
    n, start = plan['count'], plan['start']
    require(len(selected) == len(set(selected)) and all(type(i) is int and start <= i < start+n for i in selected), 'Selection range/duplicate')
    result = []
    with h5py.File(path, 'r') as f:
        require(f.attrs['kind'] == 'compact_cs137_transport_v1' and f.attrs['model_id'] == plan['model'] and
                f.attrs['primary_count'] == n and f.attrs['global_offset'] == start and f.attrs['raw_sha256'] == raw_hash,
                'Compact model/range/hash mismatch')
        require(json.loads(f.attrs['metadata_json']) == dict(meta, primary_count=n, seed=plan['seed']), 'Compact metadata mismatch')
        require(np.array_equal(f['events/local_event_id'][:], np.arange(n)) and
                np.array_equal(f['events/global_decay_id'][:], np.arange(start, start+n)), 'Compact primary census')
        energies = f['events/ge_energy_keV'][:]
        require(np.isfinite(energies).all() and (energies >= 0).all() and
                np.array_equal(f['events/has_ge_energy'][:], energies > 0), 'Compact zero semantics')
        mats = json.loads(f['events/material_energy_keV'].attrs['materials_json'])
        for key in ('ge_energy_keV', 'material_energy_keV'):
            require(f['events/'+key].attrs['units'] == 'keV', 'Scalar units')
        table = f['details/stp/germanium']; ids = table['evtid'][:]; maps = f['row_maps/stp/germanium'][:]
        require(ids.dtype.kind in 'iu' and ((ids >= 0) & (ids < n)).all() and
                (np.diff(ids.astype(np.int64)) >= 0).all(), 'Invalid Ge event IDs')
        require(np.array_equal(maps, np.arange(len(ids))) and all(len(ds) == len(ids) for ds in table.values()), 'Incomplete/ragged Ge map')
        for name, ds in table.items():
            unit = ('m' if name.startswith(('xloc', 'yloc', 'zloc', 'dist_to_surf')) else
                    'ns' if name == 'time' else 'keV' if name == 'edep' else None)
            require(unit is None or ds.attrs.get('units') == unit, 'Raw units: '+name)
        for glob in selected:
            local = glob-start
            indices = np.flatnonzero(ids == local)
            columns = {k: ds[indices] for k, ds in table.items()}
            raw = [dict(raw_row_index=int(maps[j]), **{k: A.scalar(v[i]) for k, v in columns.items()})
                   for i, j in enumerate(indices)]
            steps = [step(r, meta) for r in raw]
            e = dict(namespace=MILLION, event_id=glob, global_decay_id=glob, seed_event_id=glob, seed_family=2609261,
                     identity=dict(model_id=plan['model'], chunk_index=plan['index'], global_offset=start,
                                   local_primary_id=local, global_primary_id=glob, chunk_count=n, radiation_seed=plan['seed']),
                     source_lh5_sha256=raw_hash, raw_table='stp/germanium',
                     steps=steps, pulse_groups=C.group_deposits(steps, meta['grouping_policy']['horizon_ns']),
                     ge_energy_keV=float(energies[local]), zero_ge=bool(energies[local] == 0),
                     material_energy_keV=dict(zip(mats, map(float, f['events/material_energy_keV'][local]))),
                     decay_photon_count=int(f['events/decay_photons'][local]), line_photon_count=int(f['events/line_photons'][local]))
            # Primary source rows remain exact too; they prove ion/clock/source identity for zeros.
            for key in ('vtx', 'particles'):
                t = f['details/'+key]; mapping = f['row_maps/'+key]
                require(len(t['evtid']) == n and int(t['evtid'][local]) == local and int(mapping[local]) == local, 'Primary source identity')
                e[key] = [dict(raw_row_index=int(mapping[local]), **{k: A.scalar(ds[local]) for k, ds in t.items()})]
            require(e['vtx'][0]['time'] == 0 and e['particles'][0]['particle'] == C.ION, 'Ion/clock identity')
            validate_event(e, meta, MILLION)
            result.append(e)
    return result


def analysis_inputs(pins):
    complete = read(ANALYSIS/'COMPLETE.json')
    require(complete['status'] == 'verified_saved_data_analysis', 'Analysis incomplete')
    pin(pins, ANALYSIS/'COMPLETE.json')
    pin(pins, ANALYSIS/'summary.json', complete['summary_sha256'])
    summary = read(ANALYSIS/'summary.json')
    require(summary['status'] == 'completed_saved_data_analysis', 'Analysis status')
    for name in ('representative-events.json', 'positive-groups.csv.gz', 'provenance.json'):
        pin(pins, ANALYSIS/name, summary['files'][name]['sha256'])
    return summary, read(ANALYSIS/'representative-events.json'), read(ANALYSIS/'provenance.json')


def choose(representatives, explicit):
    if explicit is not None:
        require(set(explicit) == set(A.MODELS), 'Explicit selection needs both models')
        selected = {m: list(explicit[m]) for m in A.MODELS}
    else:
        selected = {m: [e['identity']['global_decay_id'] for e in representatives['models'][m]['events']] for m in A.MODELS}
        require(sum(map(len, selected.values())) == 20 and all(len(v) == len(set(v)) for v in selected.values()), 'Representative census changed')
        with gzip.open(ANALYSIS/'positive-groups.csv.gz', 'rt', encoding='utf-8', newline='') as stream:
            multi = [int(r['global_decay_id']) for r in csv.DictReader(stream) if r['model'] == 'SAP22' and int(r['group_id']) == 1]
        require(len(multi) == 1, 'Expected one saved SAP22 two-group primary')
        selected['SAP22'] += [i for i in multi if i not in selected['SAP22']]
        # Find actual zeros in first compact, rather than fabricating a no-hit record.
        for m in A.MODELS:
            done = read(A.CAMPAIGN/'chunks'/m/'0000/DONE.json')
            path = A.CAMPAIGN/'chunks'/m/'0000'/done['attempt']/'compact.h5'
            with h5py.File(path, 'r') as f:
                zero = int(np.flatnonzero(f['events/ge_energy_keV'][:] == 0)[0])
            selected[m].append(zero)
    for m, ids in selected.items():
        require(1 <= len(ids) <= 64 and len(ids) == len(set(ids)) and
                all(type(i) is int and 0 <= i < 1000000 for i in ids), 'Selection must contain 1..64 unique original global IDs/model')
        selected[m] = sorted(ids)
    return selected


def diagnostic(model, meta, pins):
    path = A.OLD/model/'response/native-failures.jsonl'
    pin(pins, path)
    records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    require(len(records) == 1, 'Historical failure census')
    record = records[0]; original = record['original_event']; settings = record['settings']
    require(settings['model_id'] == model and settings['seed_family'] == 2609261 and settings['parcels'] == 16 and
            settings['temperature_K'] == 77 and settings['bias_V'] == (500 if model == 'AK02' else 700), 'Historical settings mismatch')
    runpath = A.OLD/model/'response/run.json'; pin(pins, runpath)
    oldrun = read(runpath)
    require(oldrun['artifacts']['native-failures.jsonl'] == sha(path), 'Unbound historical failure')
    prepared = A.OLD/model/'transport/prepared.json'; pin(pins, prepared)
    oldmeta = read(prepared)
    require(all(oldmeta[k] == meta[k] for k in ('model_id', 'model_sha256', 'coordinate_transform', 'contour_rz_mm', 'grouping_policy')), 'Historical geometry differs')
    eid = original['event_id']
    byrow = {s['raw_row_index']: s for s in original['steps']}
    require(eid == (8432 if model == 'AK02' else 8413) and record['original_steps'] ==
            [byrow[i] for i in record['original_group']['row_indices']], 'Historical seed/row identity')
    e = dict(original, namespace=OLD, seed_event_id=eid, seed_family=2609261,
             identity=dict(model_id=model, chunk_index=0, global_offset=0, local_primary_id=eid,
                           global_primary_id=eid, chunk_count=10000, radiation_seed=oldmeta['seed']),
             ge_energy_keV=math.fsum(s['energy_keV'] for s in original['steps']),
             zero_ge=False, source_lh5_sha256=record['pulse']['source_lh5_sha256'], raw_table='stp/germanium',
             historical_record=relative(path), historical_record_sha256=sha(path),
             historical_error=record['pulse']['native_error'])
    validate_event(e, meta, OLD)
    return e


def validate_contract(d):
    require(d['kind'] == KIND and d['status'] == 'complete' and d['model_id'] in A.MODELS, 'Contract kind/model/status')
    m = d['model_id']; meta = d['prepared']
    require(meta['model_id'] == m and d['model_sha256'] == meta['model_sha256'] == H.PINNED[m], 'Wrong pinned model')
    require(d['units'] == {'raw_position': 'm', 'local_position': 'mm', 'time': 'ns', 'energy': 'keV'}, 'Contract units')
    require(meta == read(A.CAMPAIGN/'inputs'/m/'prepared.json'), 'Changed prepared geometry')
    H.validate_transform(meta['coordinate_transform'])
    seen = set()
    for e in d['events']:
        validate_event(e, meta, e['namespace'])
        key = (e['namespace'], e['event_id'])
        require(key not in seen, 'Duplicate namespaced primary'); seen.add(key)
    selected = [e for e in d['events'] if e['namespace'] == MILLION]
    diag = [e for e in d['events'] if e['namespace'] == OLD]
    require(1 <= len(selected) <= 64 and len(diag) == 1, 'Selected/diagnostic census')
    require(d['selected_global_primary_ids'] == [e['event_id'] for e in selected], 'Selection identity mismatch')
    pop, census = d['input_population_reference'], d['selected_census']
    totals = read(ANALYSIS/'summary.json')['models'][m]
    require(pop == dict(initial_primaries=totals['initial_decays'], zero_ge_primaries=totals['zero_ge_decays'],
                        positive_ge_primaries=totals['positive_ge_decays'], groups=totals['isolated_groups']), 'Changed population reference')
    require(pop['initial_primaries'] == 1000000 and pop['zero_ge_primaries']+pop['positive_ge_primaries'] == 1000000, 'Population reference census')
    expected = dict(initial_primaries=len(selected), zero_ge_primaries=sum(e['zero_ge'] for e in selected),
                    positive_ge_primaries=sum(not e['zero_ge'] for e in selected), groups=sum(len(e['pulse_groups']) for e in selected))
    require(census == expected and d['omitted_census'] == {k: pop[k]-v for k, v in expected.items()}, 'Selected/omitted census')
    require(d['nonselected_response'] is None and d['diagnostic_census'] == {'primaries': 1, 'groups': len(diag[0]['pulse_groups'])}, 'Invented nonselected response/diagnostic census')
    return d


def build(output, explicit=None):
    output = Path(output).absolute()
    require(output.parent == BASE.resolve() and not output.exists() and output == output.resolve(), 'Use new direct child of .local/native-bridge-pilot')
    frozen = source_hashes(); pins = {}
    config, complete, plans, metas = A.campaign_inputs(A.CAMPAIGN)
    require(config['events_per_model'] == 1000000 and config['chunk_size'] == 10000, 'Wrong source campaign')
    config_hash = pin(pins, A.CAMPAIGN/'config.json')
    pin(pins, A.CAMPAIGN/'config.sha256'); pin(pins, A.CAMPAIGN/'COMPLETE.json')
    summary, representatives, provenance = analysis_inputs(pins)
    require(provenance['config_sha256'] == config_hash and provenance['complete_sha256'] == sha(A.CAMPAIGN/'COMPLETE.json'), 'Analysis source binding')
    selected = choose(representatives, explicit)
    output.mkdir()
    A.write_json(output/'source-freeze.json', dict(source_sha256=frozen, python=platform.python_version(), numpy=np.__version__, h5py=h5py.__version__))
    documents = []
    for m in A.MODELS:
        meta = metas[m]; pin(pins, A.CAMPAIGN/'inputs'/m/'prepared.json')
        events, chunks = [], []
        for plan in plans:
            ids = [i for i in selected[m] if plan['model'] == m and plan['start'] <= i < plan['start']+plan['count']]
            if not ids: continue
            path, done, evidence = A.checkpoint(A.CAMPAIGN, plan, config_hash)
            pin(pins, path.parent.parent/'DONE.json')
            for name in ('compact.h5', 'transport.json', 'archive.json'):
                pin(pins, path.parent/name, done['files_sha256'][name])
            chunk = dict(evidence, compact_path=relative(path), done_path=relative(path.parent.parent/'DONE.json'))
            chunks.append(chunk)
            extracted = extract_selected(path, plan, meta, evidence['raw_sha256'], ids)
            for e in extracted:
                e['source_campaign_sha256'] = config_hash
                e['source_compact_path'] = relative(path)
                e['source_compact_sha256'] = sha(path)
                # Saved representative rows are a second exact witness, including every zero Ge row.
                rep = next((r for r in representatives['models'][m]['events'] if r['identity']['global_decay_id'] == e['event_id']), None)
                if rep is not None:
                    require([s['raw'] for s in e['steps']] == rep['event']['tables']['stp/germanium'], 'Representative Ge row round-trip')
                    require(rep['identity']['local_event_id'] == e['identity']['local_primary_id'] and
                            rep['identity']['chunk_index'] == plan['index'] and rep['provenance'] == evidence, 'Representative provenance mismatch')
            events += extracted
        selected_counts = dict(initial_primaries=len(events), zero_ge_primaries=sum(e['zero_ge'] for e in events),
                               positive_ge_primaries=sum(not e['zero_ge'] for e in events), groups=sum(len(e['pulse_groups']) for e in events))
        totals = summary['models'][m]
        population = dict(initial_primaries=totals['initial_decays'], zero_ge_primaries=totals['zero_ge_decays'],
                          positive_ge_primaries=totals['positive_ge_decays'], groups=totals['isolated_groups'])
        require(population['positive_ge_primaries'] == complete['models'][m]['ge_positive'], 'Population receipt mismatch')
        old = diagnostic(m, meta, pins)
        old['source_campaign_sha256'] = pin(pins, A.OLD/'run.json')
        events.append(old)
        d = dict(kind=KIND, status='complete', model_id=m, model_sha256=meta['model_sha256'], prepared=meta,
                 units=dict(raw_position='m', local_position='mm', time='ns', energy='keV'),
                 source_campaign_sha256=config_hash, selected_global_primary_ids=selected[m],
                 selection='explicit_original_global_ids' if explicit is not None else 'all20_representatives_plus_actual_zero_per_model_plus_SAP22_two_group',
                 input_population_reference=population, selected_census=selected_counts,
                 omitted_census={k: population[k]-v for k, v in selected_counts.items()},
                 diagnostic_census=dict(primaries=1, groups=len(old['pulse_groups'])), nonselected_response=None,
                 seed_rule='SHA256(2609261/original_global_primary_id/original_raw_row_index/parcel_index), first8 bytes big endian; separate namespace, no selection/chunk index',
                 chunks=chunks, events=events, source_sha256=frozen)
        validate_contract(d); documents.append(d)
    check_pins(pins); require(source_hashes() == frozen, 'Writer/source changed after freeze')
    for d in documents:
        d['input_sha256'] = pins
        A.write_json(output/(d['model_id']+'.json'), d)
    receipt = dict(kind=KIND, status='exported_checked_inputs', source_sha256=frozen, input_sha256=pins,
                   contracts={d['model_id']: dict(file=d['model_id']+'.json', sha256=sha(output/(d['model_id']+'.json')),
                              selected=d['selected_census'], diagnostic=d['diagnostic_census']) for d in documents})
    A.write_json(output/'EXPORT.json', receipt)
    verify(output)
    return receipt


def verify(output):
    output = Path(output); receipt = read(output/'EXPORT.json')
    require(receipt['status'] == 'exported_checked_inputs' and receipt['kind'] == KIND, 'Export receipt')
    check_pins(receipt['source_sha256']); check_pins(receipt['input_sha256'])
    for model, entry in receipt['contracts'].items():
        path = output/entry['file']; require(sha(path) == entry['sha256'], 'Contract hash mismatch')
        d = validate_contract(read(path)); require(d['model_id'] == model, 'Contract model mismatch')
        require(d['source_sha256'] == receipt['source_sha256'] and d['input_sha256'] == receipt['input_sha256'], 'Contract receipt pins')
        # Re-open selected HDF5 rows, never trust a rehashed alias-only contract.
        for chunk in d['chunks']:
            rows = [e for e in d['events'] if e['namespace'] == MILLION and e['identity']['chunk_index'] == chunk['plan']['index']]
            expected = extract_selected(ROOT/chunk['compact_path'], chunk['plan'], d['prepared'], chunk['raw_sha256'], [e['event_id'] for e in rows])
            for e, original in zip(rows, expected):
                require(all(e[k] == v for k, v in original.items()), 'Selected HDF5 round-trip mismatch')
        old = next(e for e in d['events'] if e['namespace'] == OLD)
        original = diagnostic(model, d['prepared'], {})
        require(all(old[k] == v for k, v in original.items()), 'Historical round-trip mismatch')
    return receipt


def run_pilot(input_path, output, julia):
    """One child, no retry; external wall deadline covers a stalled native call."""
    verify(input_path)
    output = Path(output).absolute()
    require(output.parent == BASE.resolve() and output == output.resolve() and not output.exists(), 'New pilot output required')
    logs = BASE/(output.name+'-launcher')
    require(not logs.exists() and Path(julia).is_file(), 'Launcher evidence exists or Julia unavailable')
    logs.mkdir()
    command = [str(julia), '--startup-file=no', '--threads=2', '--project=simulation',
               'simulation/native_bridge_pilot.jl', '--input', str(Path(input_path).absolute()), '--output', str(output)]
    env = dict(os.environ, JULIA_NUM_THREADS='2', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    started = time.time(); stopped = None
    with (logs/'stdout.log').open('x', encoding='utf-8') as stdout, (logs/'stderr.log').open('x', encoding='utf-8') as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        while child.poll() is None:
            clock = output/'compute-start.json'
            if clock.exists():
                try:
                    origin = read(clock)['unix_time']
                except (ValueError, KeyError):
                    # A partially written start receipt is transient, never a deadline reset.
                    origin = started
                if time.time()-origin >= 600: stopped = '600-second compute/export hard deadline'
            elif time.time()-started >= 180:
                stopped = '180-second startup/preflight stall limit'
            if stopped:
                child.kill(); child.wait(); break
            time.sleep(0.25)
        code = child.wait()
    terminal = read(output/'run.json') if (output/'run.json').exists() else None
    result = dict(command=command, returncode=code, launcher_wall_seconds=time.time()-started,
                  stopped=stopped, terminal_status=terminal['status'] if terminal else None,
                  status='completed' if code == 0 and terminal and terminal['status'].startswith('completed') else 'failed_or_incomplete')
    A.write_json(logs/'launcher.json', result)
    require(result['status'] == 'completed', 'Pilot failed/stalled; preserved '+relative(logs))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--export', type=Path); group.add_argument('--verify', type=Path)
    group.add_argument('--run-pilot', type=Path, metavar='EXPORTED_DIR')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--julia', type=Path, default=Path('C:/Users/kunmi/.julia/juliaup/julia-1.13.0+0.x64.w64.mingw32/bin/julia.exe'))
    parser.add_argument('--select', action='append', metavar='MODEL:ID,ID', help='Both models required; replaces default million selection; diagnostics retained')
    args = parser.parse_args(); explicit = None
    if args.run_pilot:
        require(args.output is not None and not args.select, 'Pilot needs output and already exported selection')
        print(json.dumps(run_pilot(args.run_pilot, args.output, args.julia)))
        return
    require(args.output is None, '--output only with --run-pilot')
    if args.select:
        require(args.export is not None, 'Selection only applies to export')
        explicit = {}
        for item in args.select:
            model, values = item.split(':', 1)
            require(model not in explicit, 'Repeated model selection')
            explicit[model] = [int(i) for i in values.split(',')]
    receipt = build(args.export, explicit) if args.export else verify(args.verify)
    print(json.dumps(dict(status=receipt['status'], contracts=receipt['contracts'])))


if __name__ == '__main__':
    main()
