"""Fresh, bounded Cs137/Co60 transport on one immutable parent-decay clock.

The input file contains both nuclei, positions and times before beamOn. remage
forces the initial decay and resets its children to zero to avoid year-scale
floating-point clocks; absolute daughter/deposit time is parent time + delay.
No saved radiation history or waveform library is sampled by this generator.
"""
from __future__ import annotations
import argparse
import itertools
import json
import math
from pathlib import Path
import random
import re
import subprocess
import time

import gegi_source as S

h = S.h
KIND = 'gegi_fresh_mixed_source_v1'
SOURCE = 'cs137_co60_fresh_joint_v1'
INITIAL_STATE = {'policy': 'new_parent_decays_empty_daughters_at_start',
                 'acquisition_start_ns': 0, 'initial_daughter_populations': {},
                 'pre_acquisition_history': 'none',
                 'scope': 'startup acceptance, not secular equilibrium'}


def default_config(primary_count=100, seed=20261120, acquisition_id='fresh100'):
    return {'kind': KIND, 'acquisition_id': acquisition_id,
            'primary_count': primary_count, 'seed': seed, 'clock_seed': seed,
            'initial_state': dict(INITIAL_STATE),
            'sources': [{'id': S.CS137, 'activity_Bq': 185000.,
                         'position_global_mm': [-40., 0., 40.]},
                        {'id': S.CO60, 'activity_Bq': 37000.,
                         'position_global_mm': [40., 0., 40.]}]}


def validate_config(config):
    h.require(type(config) is dict and set(config) == set(default_config())
              and config['kind'] == KIND, 'Unsupported mixed-source configuration')
    h.require(type(config['acquisition_id']) is str and
              re.fullmatch(r'[A-Za-z0-9_-]{1,64}', config['acquisition_id']), 'Invalid acquisition ID')
    h.require(type(config['primary_count']) is int and 1 <= config['primary_count'] <= 500,
              'Fresh acceptance is bounded to 1–500 parents, not production')
    h.require(all(type(config[k]) is int and 0 < config[k] < 2147483647
                  for k in ('seed', 'clock_seed')), 'Invalid fixed random seed')
    h.require(config['initial_state'] == INITIAL_STATE, 'Define a supported source startup state explicitly')
    h.require(type(config['sources']) is list and len(config['sources']) == 2 and
              [s.get('id') for s in config['sources']] == [S.CS137, S.CO60],
              'Both Cs137 and Co60 definitions are required before the first parent')
    cryostat = S.G.load_cryostat()
    for source in config['sources']:
        h.require(set(source) == {'id', 'activity_Bq', 'position_global_mm'} and
                  type(source['activity_Bq']) in (int, float) and
                  math.isfinite(source['activity_Bq']) and source['activity_Bq'] > 0,
                  'Invalid point-source activity')
        S.G.source_screen(source['position_global_mm'], cryostat)
    return config


def parent_schedule(config):
    """A marked Poisson process; fixed-count pilot ends at its Nth arrival."""
    validate_config(config)
    rng = random.Random(config['clock_seed'])
    total = math.fsum(s['activity_Bq'] for s in config['sources'])
    probability = config['sources'][0]['activity_Bq']/total
    clock = 0.
    for eid in range(config['primary_count']):
        clock += rng.expovariate(total)*1e9
        source = config['sources'][int(rng.random() >= probability)]
        preset = S.registered_preset(source['id'])
        yield {'acquisition_id': config['acquisition_id'], 'parent_decay_id': eid,
               'event_id': eid, 'source_id': source['id'], 'isotope': preset['isotope'],
               'source_pdg': S.cs.ION if source['id'] == S.CS137 else preset['pdg'],
               'source_position_global_mm': source['position_global_mm'],
               'absolute_parent_time_ns': clock}


def json_lines(rows):
    return ''.join(json.dumps(r, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n' for r in rows)


def write_primaries(path, parents):
    """The installed remage combined position/kinematics LH5 input contract."""
    import h5py
    with h5py.File(path, 'x') as raw:
        raw.attrs['datatype'] = 'struct{vtx}'
        vertex = raw.create_group('vtx'); vertex.attrs['datatype'] = 'struct{kin}'
        table = vertex.create_group('kin')
        columns = {'g4_pid': ('i4', '', [p['source_pdg'] for p in parents]),
                   'n_part': ('i4', '', [1]*len(parents)),
                   'time': ('f8', 'ns', [p['absolute_parent_time_ns'] for p in parents]),
                   'ekin': ('f8', 'keV', [0.]*len(parents)),
                   'px': ('f8', '', [0.]*len(parents)), 'py': ('f8', '', [0.]*len(parents)),
                   'pz': ('f8', '', [1.]*len(parents))}
        columns.update({axis+'loc': ('f8', 'm', [p['source_position_global_mm'][j]/1000 for p in parents])
                        for j, axis in enumerate(('x', 'y', 'z'))})
        table.attrs['datatype'] = 'table{'+','.join(sorted(columns))+'}'
        for key, (dtype, units, values) in columns.items():
            column = table.create_dataset(key, data=values, dtype=dtype)
            column.attrs['datatype'] = 'array<1>{real}'
            if units: column.attrs['units'] = units


def checked(config):
    validate_config(config)
    runtime = S.runtime_snapshot(); cryostat = S.G.load_cryostat()
    sources = []
    for source in config['sources']:
        contract = S.source_contract({'source': source['id'],
                                     'source_position_mm': source['position_global_mm']}, cryostat)
        contract.update(activity_Bq=source['activity_Bq'], daughter_lifetime_limit_ns=-1)
        sources.append({'contract': contract, 'decay_data': S.isotope_data(contract, runtime)})
    return {'kind': KIND, 'config': config, 'model_contract': S.G.load_model(),
            'cryostat_contract': cryostat, 'sources': sources, 'runtime': runtime,
            'source_sha256': {**S.source_pins(),
                             'transport/gegi_mixed_source.py': h.sha256(Path(__file__))}}


def macro(plan, geometry_only=False):
    geometry = {'selection': {'source': S.SOURCE, 'seed': plan['config']['seed'],
                             'primary_count': plan['config']['primary_count'],
                             'source_position_mm': plan['config']['sources'][0]['position_global_mm']},
                'cryostat_contract': plan['cryostat_contract']}
    text = S.macro(geometry, True)
    if geometry_only: return text
    lines = [line for line in text.splitlines() if not line.startswith('/geometry/test/')]
    lines += ['/process/had/rdm/thresholdForVeryLongDecayTime 1e27 ns',
              '/RMG/Processes/Stepping/ResetInitialDecayTime true',
              '/RMG/Processes/Stepping/DaughterNucleusMaxLifetime -1 ns',
              '/RMG/Processes/Stepping/LargeGlobalTimeUncertaintyWarning 0.001 ns',
              # FromFile uses FindParticle(PDG), so instantiate both ion species
              # before switching generators. No GPS event is generated.
              '/gps/particle ion', '/gps/ion 55 137', '/gps/ion 27 60',
              '/RMG/Generator/Select FromFile',
              '/RMG/Generator/FromFile/IncludePosition true',
              '/RMG/Generator/FromFile/FileName primaries.lh5',
              '/run/beamOn '+str(plan['config']['primary_count'])]
    return '\n'.join(lines)+'\n'


def command(config, geometry_only=False):
    return ['remage', '--flat-output', '-t', '1', '--rand-seed', str(config['seed']),
            '-o', 'geometry-check.lh5' if geometry_only else 'truth.lh5', '-g', 'geometry.gdml',
            '--', 'geometry.mac' if geometry_only else 'run.mac']


def prepare(config, output):
    plan = checked(config); parents = list(parent_schedule(config))
    directory = h.local_path(output)
    h.require(not directory.exists(), 'Preserve previous mixed-source attempts; use a fresh output')
    directory.mkdir(parents=True)
    receipt = {'kind': KIND, 'status': 'failed', 'stage': 'prepare'}
    try:
        h.publish_json(directory/'checked-plan.json', plan)
        h.write_new(directory/'parents.jsonl', json_lines(parents))
        write_primaries(directory/'primaries.lh5', parents)
        h.write_new(directory/'geometry.gdml', S.G.gdml_text(plan['model_contract'], plan['cryostat_contract']))
        h.write_new(directory/'geometry.mac', macro(plan, True))
        h.write_new(directory/'run.mac', macro(plan))
        prefix = Path(plan['runtime']['prefix'])
        emlow = Path(S.os.environ.get('G4LEDATA', '/missing')).resolve()
        h.require(emlow.is_relative_to(prefix), 'EMLOW outside locked runtime')
        h.publish_json(directory/'emlow-data.json', S.T.emlow_manifest(
            emlow, prefix/plan['runtime']['packages']['geant4-data-emlow']['metadata_ref']))
        cmd = command(config, True); started = time.perf_counter()
        with (directory/'geometry.log').open('x', encoding='utf-8') as log:
            result = subprocess.run(cmd, cwd=directory, stdout=log, stderr=subprocess.STDOUT, check=False)
        receipt.update(command=cmd, returncode=result.returncode,
                       native_geometry_wall_s=time.perf_counter()-started)
        h.require(result.returncode == 0, 'Mixed-source geometry check failed; preserve log')
        S.geometry_log_check(directory, plan)
        h.require(checked(config) == plan, 'Mixed-source inputs changed during preparation')
        meta = {'kind': KIND, 'status': 'complete', 'checked': plan,
                'primary_count': config['primary_count'], 'model_id': S.G.MODEL,
                'model_sha256': S.G.MODEL_SHA, 'model_contract': plan['model_contract'],
                'cryostat_contract': plan['cryostat_contract'], 'coordinate_transform': S.G.TRANSFORM,
                'source_id': SOURCE, 'seed': config['seed'], 'random_engine': 'CLHEP::HepJamesRandom',
                'source_sha256': plan['source_sha256'],
                'material_tables': S.material_tables(plan['cryostat_contract']),
                'files_sha256': {p.name: h.sha256(p) for p in directory.iterdir() if p.is_file()}}
        h.publish_json(directory/'prepared.json', meta)
        receipt['status'] = 'complete'
        return meta
    except BaseException as error:
        receipt['error'] = str(error); raise
    finally:
        h.publish_json(directory/'prepare-receipt.json', receipt)


def read_prepared(directory):
    directory = h.local_path(directory); meta = S.load(directory/'prepared.json')
    h.require(meta['kind'] == KIND and meta['status'] == 'complete', 'Incomplete mixed-source preparation')
    plan = meta['checked']; validate_config(plan['config'])
    for ref, digest in meta['files_sha256'].items():
        h.require(h.sha256(S.P.safe_path(directory, ref, True)) == digest, 'Prepared mixed-source bytes changed: '+ref)
    for ref, digest in plan['source_sha256'].items():
        h.require(h.sha256(h.ROOT/ref) == digest, 'Source changed after mixed preparation: '+ref)
    h.require((directory/'parents.jsonl').read_text() == json_lines(parent_schedule(plan['config'])) and
              (directory/'run.mac').read_text() == macro(plan), 'Mixed schedule or macro semantics changed')
    receipt = S.load(directory/'prepare-receipt.json')
    h.require(receipt['status'] == 'complete' and receipt['returncode'] == 0, 'Native geometry incomplete')
    S.geometry_log_check(directory, plan)
    return directory, meta


def events(path, meta):
    config = meta['checked']['config']; parents = list(parent_schedule(config))
    contracts = {s['contract']['id']: s['contract'] for s in meta['checked']['sources']}
    def for_event(eid):
        parent = parents[eid]
        return {**meta, 'source_id': parent['source_id'],
                'source_contract': contracts[parent['source_id']],
                'source_position_global_mm': parent['source_position_global_mm'],
                'primary_vertex_time_ns': parent['absolute_parent_time_ns']}
    for event in S.events(path, meta, event_metadata=for_event):
        parent = parents[event['event_id']]; origin = parent['absolute_parent_time_ns']
        event.update(parent, initial_primary_id=event['event_id'],
                     primary_time_ns=origin, parent_clock_policy='immutable_pre_transport_marked_poisson_v1')
        for step in event['steps']:
            step.update(deposit_id=[config['acquisition_id'], event['event_id'], step['raw_row_index']],
                        absolute_time_ns=origin+step['time_ns'])
        for photon in event['decay_photons']:
            photon['absolute_time_ns'] = origin+photon['time_ns']
        # Legacy pulse_groups are drift-input row partitions only. Their stored
        # isolated-readout annotations do not define this acquisition's electronics.
        event['pulse_group_use'] = 'drift_partition_only; absolute shared readout never resets here'
        yield event


def census(path, meta):
    counts = {'initial_primaries': 0, 'zero_deposit_primaries': 0, 'nonzero_primaries': 0,
              'positive_ge_rows': 0, 'pulse_groups': 0, 'by_source': {}}
    for event in events(path, meta):
        row = counts['by_source'].setdefault(event['source_id'], {'parents': 0, 'zero': 0, 'nonzero': 0})
        counts['initial_primaries'] += 1; row['parents'] += 1
        nonzero = bool(event['steps']); row['nonzero' if nonzero else 'zero'] += 1
        counts['nonzero_primaries' if nonzero else 'zero_deposit_primaries'] += 1
        counts['positive_ge_rows'] += len(event['steps']); counts['pulse_groups'] += len(event['pulse_groups'])
    h.require(counts['initial_primaries'] == meta['primary_count'], 'Mixed parent census mismatch')
    return counts


def run(directory):
    directory, meta = read_prepared(directory)
    h.require(not any((directory/n).exists() for n in ('truth.lh5', 'run.log', 'run.json')),
              'Retain previous radiation attempt; never restart it implicitly')
    config = meta['checked']['config']; cmd = command(config)
    receipt = {'kind': KIND, 'status': 'failed', 'command': cmd,
               'prepared_sha256': h.sha256(directory/'prepared.json')}
    started = time.perf_counter()
    try:
        with (directory/'run.log').open('x', encoding='utf-8') as log:
            result = subprocess.run(cmd, cwd=directory, stdout=log, stderr=subprocess.STDOUT, check=False)
        receipt.update(returncode=result.returncode, remage_wall_s=time.perf_counter()-started)
        h.require(result.returncode == 0 and not re.search(S.DIAGNOSTIC,
                  (directory/'run.log').read_text(errors='replace'), re.I), 'Mixed transport failed; retain log and raw output')
        receipt.update(source_lh5_sha256=h.sha256(directory/'truth.lh5'), counts=census(directory/'truth.lh5', meta))
        read_prepared(directory)
        receipt['status'] = 'complete'
        return receipt
    except BaseException as error:
        receipt['error'] = str(error); raise
    finally:
        receipt['total_wall_s'] = time.perf_counter()-started
        h.publish_json(directory/'run.json', receipt)


def extract(directory):
    directory, meta = read_prepared(directory); receipt = S.load(directory/'run.json')
    h.require(receipt['status'] == 'complete' and receipt['returncode'] == 0 and
              receipt['prepared_sha256'] == h.sha256(directory/'prepared.json') and
              receipt['source_lh5_sha256'] == h.sha256(directory/'truth.lh5'), 'Mixed transport not complete or changed')
    dest = directory/'stream'; h.require(not dest.exists(), 'Retain existing mixed extraction'); dest.mkdir()
    with (dest/'events.jsonl').open('x', encoding='utf-8', newline='\n') as out:
        for event in events(directory/'truth.lh5', meta):
            if event['steps']: out.write(json_lines([event]))
    config = meta['checked']['config']; parents = list(parent_schedule(config))
    manifest = {'kind': 'gegi_event_stream_v1', 'source_kind': KIND, 'status': 'complete',
                'model_id': S.G.MODEL, 'model_sha256': S.G.MODEL_SHA, 'source_id': SOURCE,
                'source_contract': config, 'source_sha256': meta['source_sha256'],
                'coordinate_transform': S.G.TRANSFORM, 'primary_count': meta['primary_count'],
                'seed': config['seed'], 'clock_seed': config['clock_seed'], 'counts': receipt['counts'],
                'zero_deposit_primaries': receipt['counts']['zero_deposit_primaries'],
                'nonzero_primaries': receipt['counts']['nonzero_primaries'],
                'events_file': 'events.jsonl', 'events_sha256': h.sha256(dest/'events.jsonl'),
                'parents_file': '../parents.jsonl', 'parents_sha256': h.sha256(directory/'parents.jsonl'),
                'source_lh5_sha256': receipt['source_lh5_sha256'],
                'transport_duration_ns': parents[-1]['absolute_parent_time_ns'],
                'clock_policy': 'Raw vertices are scheduled absolute times; child/step time_ns is native delay after forced parent decay; absolute_time_ns adds the immutable parent clock.',
                'pulse_group_policy': 'Legacy finite groups partition drift inputs only; they do not reset acquisition electronics.',
                'initial_state': config['initial_state'],
                'limitations': ['Fixed-count bounded startup acceptance, not a 60-second production acquisition.',
                                'No pre-start daughter inventory; delayed emissions beyond the parent-clock end remain retained.',
                                'Unencapsulated point sources and existing nominal cryostat; full transport energy closure is not scored.']}
    h.publish_json(dest/'manifest.json', manifest)
    verify(directory)
    return manifest


def verify(directory):
    directory, meta = read_prepared(directory); receipt = S.load(directory/'run.json')
    h.require(receipt['status'] == 'complete' and receipt['source_lh5_sha256'] == h.sha256(directory/'truth.lh5') and
              receipt['counts'] == census(directory/'truth.lh5', meta), 'Mixed transport changed')
    manifest = S.load(directory/'stream/manifest.json')
    h.require(manifest['events_sha256'] == h.sha256(directory/'stream/events.jsonl'), 'Mixed sparse bytes changed')
    original = (e for e in events(directory/'truth.lh5', meta) if e['steps'])
    with (directory/'stream/events.jsonl').open(encoding='utf-8') as stream:
        for raw, saved in itertools.zip_longest(original, (S.decode(line) for line in stream)):
            h.require(raw == saved, 'Mixed extraction lost original identity, energy or time')
    return {'status': 'verified', 'counts': receipt['counts']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('default-config', 'prepare', 'run', 'extract', 'verify'))
    parser.add_argument('--config'); parser.add_argument('--output'); parser.add_argument('--directory')
    S.P.project_root_argument(parser, required=False)
    args = parser.parse_args(argv)
    if args.windows_root: S.P.project_identity(args.windows_root)
    if args.action == 'default-config': value = default_config()
    elif args.action == 'prepare': value = prepare(S.load(args.config), args.output)
    else: value = globals()[args.action](args.directory)
    print(json.dumps(value, sort_keys=True, allow_nan=False))


if __name__ == '__main__': main()
