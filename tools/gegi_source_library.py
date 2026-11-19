"""Portable sealed source-chunk inputs and configurable GeGI parent clocks."""

from collections import Counter
from contextlib import closing
from dataclasses import dataclass
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sqlite3
import zlib

import gegi_event_store as store


_STREAM = 'transport/stream/events.jsonl'
_MANIFEST = 'transport/stream/manifest.json'
_CLOCK = 'remage_initial_decay_secondaries_zero'
_COUNTS = ('initial_primaries', 'zero_deposit_primaries', 'nonzero_primaries', 'pulse_groups', 'positive_ge_rows')
_FIELD_KEYS = ('model_sha256', 'geometry_sha256', 'field_calibration_sha256', 'drift_dt_ns',
               'ionisation_energy_eV', 'coordinate_transform')

# The campaign calibration-admission receipt (SHA-256 c2d0c4527a95a52464b0cebf3e9122db8017d6268422525db259ff4c30ae1d0b)
# linked all three native request generations and the sealed depth table to the same saved Float32 cache.
_ADMITTED_MODEL_SHA256 = '4b6c71c178c81e68bc1fe093d491b59ab99f19aed5adaba5fc61bba74d445c04'
_ADMITTED_DEPTH_SHA256 = '61f59e2fcdd43aa0f04d6a49a6e59c448bc6059057207a8bcd80d46074d29694'
_ADMITTED_CACHE_SHA256 = 'f75280e7f21b1a1a06c2a6623aed62873065ca72db02bb1f93a61b9b853b90e8'
_ADMITTED_REQUESTS = frozenset({
    '06470249694b2c9e656f5ec6d8aa3be3f7e9b4dceb33d1ee2cca049a5c59bb83',
    '292c76b5d71f2ea3f40a135e6ea1e4c59168e622e2163e050a93f1c41a85b87d',
    'ae476cdc9349bddec75c36c87fb9538224cfdf8b848618d393aea983b663db29',
})


@dataclass(frozen=True)
class SourceLibrary:
    directory: Path
    database: Path
    metadata: dict
    channels: list
    marks: dict


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _file(folder, relative):
    path = folder / relative
    require(path.is_file() and path.resolve().is_relative_to(folder), f'Missing sealed chunk file: {relative}')
    return path


def _bound(folder, artifacts, relative):
    path = _file(folder, relative)
    expected = artifacts.get(relative) or {}
    require(path.stat().st_size == expected.get('bytes') and _hash(path) == expected.get('sha256'),
            f'Sealed chunk file changed: {relative}')
    return path


def _database(path):
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.execute('PRAGMA query_only=ON')
    return conn


def _is_sha256(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _requested_cache_sha256(folder, request_sha256, model_sha256):
    """Read only the optional, byte-matched request shipped with an imported chunk."""
    path = folder / 'native-request.json'
    try:
        if not path.is_file() or not path.resolve().is_relative_to(folder):
            return None
        raw = path.read_bytes()
        if store.sha(raw) != request_sha256:
            return None
        request = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(request, dict) or request.get('kind') != 'gegi_campaign_response_request_v1':
        return None
    numerics, field = request.get('numerics'), request.get('field_cache')
    if (request.get('model_sha256') == model_sha256
            and isinstance(numerics, dict) and numerics.get('field_policy') == 'reuse-only'
            and isinstance(field, dict) and field.get('model_sha256') == model_sha256
            and _is_sha256(field.get('sha256'))):
        return field['sha256']
    return None


def _field_identity(folder, identity, response):
    request = identity.get('native_request_sha256')
    model = identity['model_sha256']
    cache = None
    if not _is_sha256(request) or request != response.get('native_request_sha256'):
        request = None
    elif (model == _ADMITTED_MODEL_SHA256 and identity['calibration_sha256'] == _ADMITTED_DEPTH_SHA256
          and request in _ADMITTED_REQUESTS):
        cache = _ADMITTED_CACHE_SHA256
    else:
        cache = _requested_cache_sha256(folder, request, model)
    # The native request's fresh-solve precision setting does not describe an existing cache.
    precision = 32 if model == _ADMITTED_MODEL_SHA256 and cache == _ADMITTED_CACHE_SHA256 else None
    return {'native_request_sha256': request, 'field_cache_sha256': cache, 'field_precision_bits': precision}


def _source_inputs(path):
    folder = Path(path).resolve()
    if folder.is_file():
        require(folder.name == 'events.sqlite', 'Select a sealed chunk directory or its events.sqlite')
        folder = folder.parent
    done_bytes = _file(folder, 'DONE.json').read_bytes()
    done = json.loads(done_bytes)
    require(done.get('kind') == 'gegi_campaign_chunk_done_v1', 'Select a sealed GeGI response chunk')
    identity, artifacts, response = (done[k] for k in ('identity', 'artifacts', 'response'))
    done_sha = hashlib.sha256(done_bytes).hexdigest()
    if folder.parent.parent.name == 'chunks':
        complete_path = folder.parent.parent.parent/'COMPLETE.json'
        if complete_path.is_file():
            complete = json.loads(complete_path.read_bytes())
            require(complete.get('status') in ('completed', 'completed_with_native_failures')
                    and complete.get('chunks', {}).get(str(identity['chunk_index'])) == done_sha,
                    'Chunk seal differs from the campaign completion receipt')

    checked = json.loads(_bound(folder, artifacts, 'source-checked.json').read_bytes())
    manifest = json.loads(_bound(folder, artifacts, _MANIFEST).read_bytes())
    geometry_path = _bound(folder, artifacts, 'transport/geometry.gdml')
    macro = _bound(folder, artifacts, 'transport/run.mac').read_text(encoding='utf-8')
    database = _file(folder, 'events.sqlite')
    stream_relative = _STREAM + '.gz' if (folder/(_STREAM + '.gz')).is_file() else _STREAM
    _file(folder, stream_relative)

    contract, selection = manifest['source_contract'], checked['selection']
    primary, counts = identity['batch']['primary_count'], manifest['counts']
    base = identity['raw_initial_id_base']
    source, pdg = manifest['source_id'], manifest['source_pdg']
    position = contract['position_global_mm']
    model, geometry, calibration = (identity['model_sha256'], manifest['geometry_sha256'], identity['calibration_sha256'])
    recipe = response['readout_recipe']
    channels = recipe['channels']
    require(manifest['kind'] == 'gegi_event_stream_v1' and manifest['model_id'] == 'GeGI_3D'
            and selection['detector'] == manifest['model_id']
            and model == manifest['model_sha256'] == manifest['model_contract']['model_sha256']
            and geometry == artifacts[geometry_path.relative_to(folder).as_posix()]['sha256']
            and selection['cryostat'] == manifest['cryostat_contract']['id']
            and checked['coordinate_transform'] == manifest['coordinate_transform'],
            'Selected chunk detector geometry or transform is inconsistent')
    require(contract['id'] == source == selection['source'] == response['source_id']
            and pdg == contract['pdg'] and contract['particle'] == 'ion'
            and contract['initial_nuclei_per_primary'] == 1 and contract['kinetic_energy_keV'] == 0
            and contract['A'] == (pdg//10) % 1000 and contract['Z'] == (pdg//10000) % 1000
            and len(position) == 3 and all(math.isfinite(x) for x in position)
            and position == selection['source_position_mm'] == checked['source_contract']['position_global_mm'],
            'Source identity or position is inconsistent with the saved radioactive-decay geometry')
    require(type(primary) is int and primary > 0 and type(base) is int and base >= 0
            and identity['batch']['local_initial_primary_id_range'] == [base, base+primary-1]
            and manifest['seed'] == selection['seed'] == identity['batch']['radiation_seed']
            and manifest['primary_count'] == selection['primary_count'] == counts['initial_decays'] == counts['initial_primaries'] == primary
            and counts['nonzero_primaries'] + counts['zero_deposit_primaries'] == primary
            and manifest['event_storage']['kind'] == 'nonzero_deposit_v1'
            and manifest['event_storage']['efficiency_denominator'] == primary,
            'Original parent-decay denominator or primary roster is inconsistent')
    require(manifest['clock_policy'] == contract['clock_policy'] == _CLOCK and contract['time_ns'] == 0
            and manifest['grouping_policy']['horizon_ns'] == 100000
            and manifest['events_file'] == 'events.jsonl'
            and manifest['units'] == {'energy': 'keV', 'length': 'mm', 'time': 'ns'}
            and all(manifest['raw_tables'][table]['columns']['time']['units'] == 'ns'
                    for table in ('vtx', 'tracks', 'stp/germanium'))
            and all(manifest['raw_tables']['vtx']['columns'][axis]['units'] == 'm' for axis in ('xloc', 'yloc', 'zloc'))
            and {'/gps/time 0 ns', '/RMG/Processes/Stepping/ResetInitialDecayTime true'} <= set(macro.splitlines()),
            'The saved source does not establish a parent-decay origin and supported native timing')
    require(response.get('status') in ('completed', 'completed_with_native_failures')
            and response['input_manifest_sha256'] == artifacts[_MANIFEST]['sha256']
            and response['store_identity_sha256'] == store.sha(store.encoded(identity))
            and response['calibration_sha256'] == calibration and re.fullmatch('[0-9a-f]{64}', calibration)
            and response['readout_recipe_sha256'] == store.sha(store.encoded(recipe))
            and response['new_field_solve'] is False
            and all(response['counts'][key] == counts[key] for key in _COUNTS if key != 'positive_ge_rows'),
            'Saved response is unsealed or lacks its field and drift calibration binding')
    require(recipe['drift_dt_ns'] == 1. and math.isclose(recipe['ionisation_energy_eV'], 2.95, rel_tol=0, abs_tol=1e-6)
            and [row['id'] for row in channels] == list(range(1, 35))
            and all(row['wiring_factor'] == (1 if row['id'] <= 17 else -1)
                    and row['family'] == ('X' if row['id'] <= 17 else 'Y')
                    and row['guard'] == (row['id'] in (17, 34)) for row in channels),
            'Saved source is incompatible with nominal 34-channel GeGI readout')
    isotope = re.fullmatch(r'initial ([A-Z][a-z]?)-?(\d+) decays', contract['count_unit'])
    label = f'{isotope[1]}-{isotope[2]}' if isotope and int(isotope[2]) == contract['A'] else (
        f"Z={contract['Z']}, A={contract['A']}")
    meta = {'source_group': identity['source_group'], 'source_contract_id': source, 'isotope': label,
            'source_pdg': pdg, 'source_position_mm': position, 'coordinate_transform': manifest['coordinate_transform'],
            'model_sha256': model, 'geometry_sha256': geometry, 'field_calibration_sha256': calibration,
            **_field_identity(folder, identity, response),
            'drift_dt_ns': recipe['drift_dt_ns'], 'ionisation_energy_eV': recipe['ionisation_energy_eV'],
            'field_binding_scope': 'The sealed campaign response binds this calibration hash to its loaded field and drift numerics.',
            'chunk_sha256': done_sha, 'database_sha256': artifacts['events.sqlite']['sha256'],
            'transport_sha256': manifest['events_sha256'], 'chunk_index': identity['chunk_index'],
            'radiation_seed': manifest['seed'], 'original': {k: counts[k] for k in _COUNTS}}
    return folder, database, done, manifest, stream_relative, meta, channels


def describe_source_library(path):
    """Read bound sidecar metadata for discovery without opening native data."""
    return _source_inputs(path)[5]


def _validate_mark(event, metadata, process, identity):
    raw_id = event['initial_primary_id']
    pdg = metadata['source_pdg']
    require(event['event_id'] == event['global_decay_id'] == raw_id and event['vertex']['time'] == 0
            and event['source_id'] == metadata['source_contract_id'] and event['primary']['particle'] == pdg,
            'Saved parent identity or GPS time changed')
    roots = [t for t in event['tracks'] if t['parent_trackid'] == 0]
    require(len(roots) == 1 and roots[0]['particle'] == pdg and roots[0]['time'] == 0,
            'Missing zero-clock primary track')
    children = [t for t in event['tracks'] if t['parent_trackid'] == roots[0]['trackid']]
    require(children and all(t['time'] == 0 and t['procid'] == process for t in children),
            'Initial decay children do not establish the zero of the saved clock')
    steps = {step['raw_row_index']: step for step in event['steps']}
    groups, assigned = [], []
    for group in event['pulse_groups']:
        onset, end, rows = group['origin_time_ns'], group['last_deposit_time_ns'], group['row_indices']
        members = [steps[row] for row in rows]
        times = [step['time_ns'] for step in members]
        require(times and 0 <= onset <= end and end-onset < 100000
                and (not groups or groups[-1]['last_deposit_since_parent_ns'] < onset)
                and group['group_id'] == len(groups) and times == sorted(times)
                and times[0] == onset and times[-1] == end
                and [t-onset for t in times] == group['relative_times_ns']
                and all(math.isfinite(step['energy_keV']) and step['energy_keV'] > 0 for step in members),
                'Saved Ge pulse group does not match its original rows and times')
        assigned.extend(rows)
        groups.append({'group_id': group['group_id'], 'first_deposit_since_parent_ns': onset,
                       'last_deposit_since_parent_ns': end,
                       'positive_ge_energy_keV': math.fsum(step['energy_keV'] for step in members),
                       'raw_row_indices': rows})
    require(groups and len(assigned) == len(set(assigned)) == len(event['steps']) and set(assigned) == set(steps),
            'Ge pulse groups do not partition the positive deposit rows')
    first = groups[0]['first_deposit_since_parent_ns']
    for group in groups:
        group['first_deposit_since_first_group_ns'] = group['first_deposit_since_parent_ns'] - first
    ordinal = raw_id - identity['raw_initial_id_base']
    return {'ordinal': ordinal, 'raw_event_id': raw_id, 'initial_primary_id': raw_id, 'global_decay_id': raw_id,
            'campaign_initial_id': identity['campaign_initial_offset'] + ordinal, 'groups': groups}


def _load_marks(folder, done, manifest, stream_relative, metadata):
    path = _file(folder, stream_relative)
    artifacts = done['artifacts']
    archive = done.get('archives', {}).get(_STREAM)
    if stream_relative.endswith('.gz'):
        _bound(folder, artifacts, stream_relative)
        require(archive and archive['sha256'] == artifacts[stream_relative]['sha256']
                and archive['original_sha256'] == manifest['events_sha256'],
                'Compressed decay ledger lacks its original stream binding')
    elif _STREAM in artifacts:
        _bound(folder, artifacts, _STREAM)
    else:
        require(archive and path.stat().st_size == archive['original_bytes'], 'Original decay stream is unsealed')
    process, = (p['procid'] for p in manifest['processes'] if p['name'] == 'RadioactiveDecay')
    identity = done['identity']
    primary_count = metadata['original']['initial_primaries']
    base = identity['raw_initial_id_base']
    marks, digest, size = {}, hashlib.sha256(), 0
    opener = gzip.open if stream_relative.endswith('.gz') else open
    with opener(path, 'rb') as stream:
        for line in stream:
            digest.update(line)
            size += len(line)
            event = json.loads(line)
            require(all(math.isclose(1000*event['vertex'][axis], position, rel_tol=0, abs_tol=1e-9)
                        for axis, position in zip(('xloc', 'yloc', 'zloc'), metadata['source_position_mm'])),
                    'Saved source vertex differs from its published position')
            mark = _validate_mark(event, metadata, process, identity)
            ordinal = mark['ordinal']
            require(0 <= ordinal < primary_count and ordinal not in marks, 'Foreign or duplicate original primary')
            marks[ordinal] = mark
    require(digest.hexdigest() == metadata['transport_sha256']
            and (archive is None or size == archive['original_bytes']),
            'Original parent and deposit stream hash or size changed')
    groups = [g for mark in marks.values() for g in mark['groups']]
    require([i+base for i in marks] == manifest['counts']['nonzero_event_ids']
            and len(marks) == metadata['original']['nonzero_primaries']
            and len(groups) == metadata['original']['pulse_groups']
            and sum(len(g['raw_row_indices']) for g in groups) == metadata['original']['positive_ge_rows'],
            'Sealed parent, pulse-group or Ge row census changed')
    return marks


def load_source_library(path):
    """Open a sealed GeGI library relative to its selected chunk directory."""
    folder, database, done, manifest, ref, metadata, channels = _source_inputs(path)
    _bound(folder, done['artifacts'], 'events.sqlite')
    marks = _load_marks(folder, done, manifest, ref, metadata)
    keys = {(m['raw_event_id'], g['group_id']) for m in marks.values() for g in m['groups']}
    with closing(_database(database)) as conn:
        identity = conn.execute('SELECT body FROM identity WHERE singleton=1').fetchone()
        completion = conn.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        require(identity and json.loads(identity[0]) == {'kind': store.KIND, 'identity': done['identity']}
                and completion and json.loads(completion[0]) == done['response']
                and keys == set(conn.execute('SELECT primary_id, group_id FROM events')),
                'Native SQLite seal or native group census differs from the parent clock')
    metadata['raw_initial_id_base'] = done['identity']['raw_initial_id_base']
    return SourceLibrary(folder, database, metadata, channels, marks)


def validate_compatible(first, second):
    mismatched = [key for key in _FIELD_KEYS if first.metadata[key] != second.metadata[key]]
    if first.channels != second.channels:
        mismatched.append('native_channel_geometry_and_wiring')
    require(not mismatched, f"Saved source libraries are incompatible: {', '.join(mismatched)}")


def _parent_support(groups, duration):
    intervals = [(0., float(duration))]
    for group in groups:
        delay = group['first_deposit_since_parent_ns']
        intervals.append((-delay, duration-delay))
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _poisson(mean, rng):
    threshold, run, count = math.exp(-mean), 1., 0
    while True:
        run *= rng.random()
        if run <= threshold:
            return count
        count += 1


def _simulate(key, library, seed, duration, activity):
    # This draw order preserves the original seeded research acquisition.
    unique_seed = int.from_bytes(hashlib.sha256(f'{seed}:{key}'.encode()).digest()[:8], 'big')
    rng = random.Random(unique_seed)
    initial = library.metadata['original']['initial_primaries']
    rate = activity / initial / 1e9
    counts, occurrences = Counter(), []
    for ordinal in range(initial):
        mark = library.marks.get(ordinal)
        groups = [] if mark is None else mark['groups']
        for interval, (begin, end) in enumerate(_parent_support(groups, duration)):
            width = end - begin
            for i in range(_poisson(rate * width, rng)):
                offset = width * rng.random()
                parent = begin + offset
                in_live = 0 <= parent < duration
                if in_live:
                    counts['parents'] += 1
                    counts['marked_nonzero_parents' if groups else 'marked_zero_parents'] += 1
                if not groups:
                    continue
                timed = []
                for group in groups:
                    delay = group['first_deposit_since_parent_ns']
                    # Add the delay before the offset to retain sub-ns precision
                    # even when a daughter came from a parent far before time zero.
                    onset = (begin + delay) + offset
                    last = onset + (group['last_deposit_since_parent_ns'] - delay)
                    timed.append({'group_id': group['group_id'], 'first_ge_deposit_ns': onset,
                                  'last_ge_deposit_ns': last, 'onset_in_live_time': 0 <= onset < duration,
                                  'complete_deposits_in_live_time': 0 <= onset <= last < duration})
                occurrences.append({'occurrence_id': f'{ordinal}.{interval}.{i}', 'mark_ordinal': ordinal,
                                    'parent_decay_time_ns': parent, 'parent_in_live_time': in_live, 'groups': timed})
    occurrences.sort(key=lambda row: (row['parent_decay_time_ns'], row['occurrence_id']))
    return {'seed_uint64': unique_seed, 'activity_bq': activity, 'live_parent_census': dict(counts),
            'nonzero_mark_occurrences': occurrences}


def _schedule_clock(key, library, activity, duration, seed):
    largest_interval = max((end-start for mark in library.marks.values()
                            for start, end in _parent_support(mark['groups'], duration)), default=duration)
    mean = activity / library.metadata['original']['initial_primaries'] / 1e9 * largest_interval
    require(math.isfinite(mean), 'The expected parent count exceeds finite clock arithmetic')
    # The frozen sampler multiplies uniform draws down to exp(-mean). For
    # larger means, independent Poisson layers keep that product representable.
    layers = max(1, math.ceil(mean/500))
    if layers == 1:
        return _simulate(key, library, seed, duration, activity)
    counts, occurrences = Counter(), []
    for i in range(layers):
        clock = _simulate(f'{key}:layer:{i}', library, seed, duration, activity/layers)
        counts.update(clock['live_parent_census'])
        occurrences.extend({**row, 'occurrence_id': f"{i}:{row['occurrence_id']}"}
                           for row in clock['nonzero_mark_occurrences'])
    occurrences.sort(key=lambda row: (row['parent_decay_time_ns'], row['occurrence_id']))
    return {'clock_layers': layers, 'activity_bq': activity, 'seed_uint64': None,
            'live_parent_census': dict(counts), 'nonzero_mark_occurrences': occurrences}


def _group(library, row):
    mark = library.marks[row['raw_event_id']-library.metadata['raw_initial_id_base']]
    require(mark['campaign_initial_id'] == row['campaign_initial_id'], 'Clock row differs from the saved parent identity')
    return mark['groups'][row['group_id']]


def _add_group_energy(library, row):
    group = _group(library, row)
    return {**row, 'truth_edep_keV': group['positive_ge_energy_keV'],
            'original_deposit_span_ns': group['last_deposit_since_parent_ns']-group['first_deposit_since_parent_ns']}


def _clock_groups(key, library, clock, duration, include_prehistory):
    counts, eligible, censored = Counter(), [], []
    for occurrence in clock['nonzero_mark_occurrences']:
        in_live = occurrence['parent_in_live_time']
        if not (include_prehistory or in_live):
            continue
        mark = library.marks[occurrence['mark_ordinal']]
        counts['nonzero_mark_occurrences'] += 1
        counts['prehistory_nonzero_mark_occurrences'] += not in_live
        for group in occurrence['groups']:
            onset, last = group['first_ge_deposit_ns'], group['last_ge_deposit_ns']
            counts['group_onsets_in_live_time'] += group['onset_in_live_time']
            counts['group_onsets_right_censored_from_live_parents'] += in_live and onset >= duration
            if not group['onset_in_live_time']:
                continue
            complete = group['complete_deposits_in_live_time']
            counts['group_onsets_inside_with_last_deposit_censored'] += not complete
            row = {'source': key, 'occurrence_id': occurrence['occurrence_id'],
                   'raw_event_id': mark['raw_event_id'], 'campaign_initial_id': mark['campaign_initial_id'],
                   'group_id': group['group_id'], 'first_ge_deposit_ns': onset, 'last_ge_deposit_ns': last,
                   'parent_precedes_live_time': not in_live}
            (eligible if complete else censored).append(_add_group_energy(library, row))
    for rows in (eligible, censored):
        rows.sort(key=lambda group: (group['first_ge_deposit_ns'], group['occurrence_id'], group['group_id']))
    counts = {**clock['live_parent_census'], **counts, 'eligible_groups': len(eligible),
              'eligible_group_rate_per_s': len(eligible) / (duration / 1e9)}
    for name in ('parents', 'marked_zero_parents', 'marked_nonzero_parents', 'nonzero_mark_occurrences',
                 'prehistory_nonzero_mark_occurrences', 'group_onsets_in_live_time',
                 'group_onsets_right_censored_from_live_parents', 'group_onsets_inside_with_last_deposit_censored'):
        counts.setdefault(name, 0)
    require(counts['marked_zero_parents'] + counts['marked_nonzero_parents'] == counts['parents'],
            'Laboratory parent clock census does not close')
    return eligible, censored, counts


def schedule_sources(first, second, *, activities_bq, duration_ns, seed, include_prehistory=True):
    """Place two independent parent clocks on a common finite interval in ns."""
    validate_compatible(first, second)
    activities = tuple(activities_bq)
    require(len(activities) == 2 and all(not isinstance(x, bool) and math.isfinite(x) and x >= 0 for x in activities),
            'Supply two finite nonnegative source activities in Bq')
    require(not isinstance(duration_ns, bool) and math.isfinite(duration_ns) and duration_ns > 0,
            'Supply a finite positive acquisition duration in ns')
    require(type(seed) is int and 0 <= seed < 2**64, 'Supply a clock seed from 0 through 2^64−1')
    require(type(include_prehistory) is bool, 'Clock prehistory option must be boolean')
    libraries = (first, second)
    source_keys = [lib.metadata['source_group'] for lib in libraries]
    if source_keys[0] == source_keys[1]:
        source_keys = [f'{key}:{i+1}' for i, key in enumerate(source_keys)]
    results = {}
    for key, library, activity in zip(source_keys, libraries, activities):
        clock = _schedule_clock(key, library, activity, duration_ns, seed)
        eligible, censored, counts = _clock_groups(key, library, clock, duration_ns, include_prehistory)
        results[key] = {'metadata': library.metadata, 'clock': clock, 'counts': counts,
                        'eligible_groups': eligible, 'censored_groups': censored}
    return {'source_keys': source_keys, 'sources': results, 'duration_ns': duration_ns, 'clock_seed': seed,
            'include_prehistory': include_prehistory, **{
                field: sorted((row for source in results.values() for row in source[field]),
                              key=lambda row: row['first_ge_deposit_ns'])
                for field in ('eligible_groups', 'censored_groups')}}


def read_native(library, row, cache=None):
    """Read a scheduled group, preserving incomplete or missing native status."""
    from gegi_digital_readout import terminal_contacts_complete
    from gegi_pulse_stream import prepare_native

    primary, group_id = row['raw_event_id'], row['group_id']
    key = library.metadata['chunk_sha256'], primary, group_id
    if cache is not None and key in cache:
        return cache[key]
    group = _group(library, row)
    with closing(_database(library.database)) as conn:
        body, digest = conn.execute('SELECT metadata,metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                                    (primary, group_id)).fetchone()
        payload = zlib.decompress(body)
        require(store.sha(payload) == digest, 'Saved native metadata hash changed')
        event = json.loads(payload)
        base = library.metadata['raw_initial_id_base']
        require(event['event_id'] == primary and event['group_id'] == group_id
                and event['source_id'] == library.metadata['source_contract_id']
                and event['source_group'] == library.metadata['source_group']
                and event['campaign_initial_offset'] + primary-base == row['campaign_initial_id']
                and event['parent_primary_time_ns'] == 0
                and event['group_origin_time_ns'] == group['first_deposit_since_parent_ns']
                and event['pulse_group']['row_indices'] == group['raw_row_indices']
                and math.isclose(event['truth_edep_keV'], group['positive_ge_energy_keV'], rel_tol=0, abs_tol=1e-7),
                'Saved native group differs from its original Ge deposit record')
        prepared = None
        if terminal_contacts_complete(event):
            native = {}
            require(event['storage']['native_dtype'] == '<f8'
                    and event['storage']['native_units'] == {'time': 'ns', 'charge': 'keV'}
                    and event['native_signals'] is not None, 'Verified native group lacks its lossless charge arrays')
            for cid, fields in event['native_signals'].items():
                native[int(cid)] = {}
                for name, ref in fields.items():
                    values = conn.execute('SELECT count,value FROM arrays WHERE digest=?', (ref['sha256'],)).fetchone()
                    require(values and values[0] == ref['count'], 'Saved native waveform array is missing')
                    native[int(cid)][name] = store.unpack_array(ref['sha256'], *values)
            prepared = prepare_native(native, library.channels, terminal_complete=True)
            require(prepared.time_ns[-1] <= group['last_deposit_since_parent_ns']-group['first_deposit_since_parent_ns']+1001,
                    'Native sample support exceeds the sealed nominal drift duration')
    result = prepared, event['status'], digest
    if cache is not None:
        cache[key] = result
    return result
