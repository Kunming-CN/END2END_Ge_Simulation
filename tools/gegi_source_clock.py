"""Schedule the preserved Cs137-left and Co60-right decay marks on one lab clock."""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import gzip
import hashlib
from heapq import nsmallest
import json
import math
from pathlib import Path
import platform
import random


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / '.local/gegi-10m/campaign'
SOURCES = {'cs137-left': (40, 'cs137_point_decay_v1', 1000551370),
           'co60-right': (70, 'co60_point_decay_v1', 1000270600)}
ACTIVITY_BQ = 37_000
LIVE_NS = 250_000_000
SEED = 20261118
WINDOWS_NS = (300, 1000, 6000)
CLOSEST_COUNT = 8
REMANUAL = 'https://remage.readthedocs.io/en/stable/manual/generators.html'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bound_bytes(path, hashes, expected=None):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    require(expected is None or digest == expected, f'Saved hash changed: {path.name}')
    hashes[path.relative_to(ROOT).as_posix()] = digest
    return data


def validate_mark(event, source_id, pdg, decay_process, identity):
    raw_id = event['initial_primary_id']
    require(event['event_id'] == event['global_decay_id'] == raw_id
            and event['source_id'] == source_id and event['vertex']['time'] == 0
            and event['primary']['particle'] == pdg, 'Changed source event identity or GPS time')
    roots = [t for t in event['tracks'] if t['parent_trackid'] == 0]
    require(len(roots) == 1 and roots[0]['particle'] == pdg and roots[0]['time'] == 0,
            'Missing zero-clock primary Track')
    root = roots[0]
    children = [t for t in event['tracks'] if t['parent_trackid'] == root['trackid']]
    require(children and all(t['time'] == 0 and t['procid'] == decay_process for t in children),
            'Direct initial decay children do not bind the zero of the saved clock')
    ordinal = raw_id - identity['raw_initial_id_base']
    steps = {step['raw_row_index']: step for step in event['steps']}
    group_rows, groups = [], []
    for group in event['pulse_groups']:
        onset, end = group['origin_time_ns'], group['last_deposit_time_ns']
        rows = group['row_indices']
        members = [steps[row] for row in rows]
        times = [step['time_ns'] for step in members]
        require(group['group_id'] == len(groups) and 0 <= onset <= end
                and (not groups or groups[-1]['last_deposit_since_parent_ns'] < onset)
                and times == sorted(times) and times[0] == onset and times[-1] == end
                and [t - onset for t in times] == group['relative_times_ns']
                and all(step['energy_keV'] > 0 for step in members), 'Changed Ge row or time-group mapping')
        group_rows.extend(rows)
        groups.append({'group_id': group['group_id'], 'first_deposit_since_parent_ns': onset,
                       'last_deposit_since_parent_ns': end,
                       'positive_ge_energy_keV': math.fsum(step['energy_keV'] for step in members),
                       'raw_row_indices': rows})
    require(groups and len(group_rows) == len(set(group_rows)) == len(steps)
            and set(group_rows) == set(steps), 'Ge pulse groups do not partition the positive deposit rows')
    first = groups[0]['first_deposit_since_parent_ns']
    for group in groups:
        group['first_deposit_since_first_group_ns'] = group['first_deposit_since_parent_ns'] - first
    return {'ordinal': ordinal, 'raw_event_id': event['event_id'], 'initial_primary_id': raw_id,
            'global_decay_id': event['global_decay_id'], 'campaign_initial_id': identity['campaign_initial_offset'] + ordinal,
            'groups': groups}


def timing_example(event, mark):
    group = mark['groups'][0]
    row = group['raw_row_indices'][0]
    first_step = next(step for step in event['steps'] if step['raw_row_index'] == row)
    tracks = {t['trackid']: t for t in event['tracks']}
    photons = {p['track_id']: p for p in event['decay_photons'] if p['creation_process'] == 'RadioactiveDecay'}
    ancestry = []
    track = tracks[first_step['track_id']]
    while True:
        ancestry.append({'track_id': track['trackid'], 'parent_track_id': track['parent_trackid'],
                         'particle_pdg': track['particle'], 'birth_since_parent_decay_ns': track['time']})
        if track['parent_trackid'] == 0:
            break
        track = tracks[track['parent_trackid']]
    gamma = next((photons[t['track_id']] for t in ancestry if t['track_id'] in photons), None)
    return {'raw_event_id': mark['raw_event_id'], 'group_id': group['group_id'], 'raw_ge_row_index': row,
            'first_deposit_since_parent_ns': group['first_deposit_since_parent_ns'],
            'deposit_track_ancestry': ancestry, 'ancestral_radioactive_gamma_birth': gamma,
            'birth_to_first_ge_deposit_ns': None if gamma is None else first_step['time_ns'] - gamma['time_ns']}


def load_marks(source, complete, hashes):
    chunk_index, source_id, pdg = SOURCES[source]
    folder = CAMPAIGN / 'chunks' / source / 'b000000'
    done = json.loads(bound_bytes(folder / 'DONE.json', hashes, complete['chunks'][str(chunk_index)]))
    identity, artifacts = done['identity'], done['artifacts']

    def read(relative):
        return bound_bytes(folder / relative, hashes, artifacts[relative]['sha256'])

    checked = json.loads(read('source-checked.json'))
    manifest = json.loads(read('transport/stream/manifest.json'))
    macro = read('transport/run.mac').decode()
    count = identity['batch']['primary_count']
    counts = manifest['counts']
    require(identity['chunk_index'] == chunk_index and identity['source_group'] == source
            and identity['batch']['batch_index'] == 0 and identity['raw_initial_id_base'] == 0
            and identity['batch']['local_initial_primary_id_range'] == [0, count - 1]
            and manifest['source_id'] == checked['selection']['source'] == source_id
            and manifest['source_pdg'] == pdg and manifest['model_sha256'] == identity['model_sha256']
            and manifest['seed'] == identity['batch']['radiation_seed']
            and manifest['primary_count'] == counts['initial_decays'] == counts['initial_primaries'] == count
            and counts['nonzero_primaries'] + counts['zero_deposit_primaries'] == count
            and manifest['event_storage']['kind'] == 'nonzero_deposit_v1',
            'Unexpected source chunk, clock roster or denominator')
    require(manifest['clock_policy'] == 'remage_initial_decay_secondaries_zero'
            and all(manifest['raw_tables'][table]['columns']['time']['units'] == 'ns'
                    for table in ('vtx', 'tracks', 'stp/germanium'))
            and {'/gps/time 0 ns', '/RMG/Processes/Stepping/ResetInitialDecayTime true'} <= set(macro.splitlines()),
            'Cannot bind the saved time origin to the initial parent decay')
    process, = (p['procid'] for p in manifest['processes'] if p['name'] == 'RadioactiveDecay')
    ref = 'transport/stream/events.jsonl.gz'
    archive = done['archives'][ref[:-3]]
    compressed = read(ref)
    require(hashlib.sha256(compressed).hexdigest() == archive['sha256'], 'Compressed stream binding changed')
    raw = gzip.decompress(compressed)
    require(len(raw) == archive['original_bytes']
            and hashlib.sha256(raw).hexdigest() == archive['original_sha256'] == manifest['events_sha256'],
            'Decompressed stream binding changed')
    marks, example = {}, None
    for line in raw.splitlines():
        event = json.loads(line)
        mark = validate_mark(event, source_id, pdg, process, identity)
        ordinal = mark['ordinal']
        require(0 <= ordinal < count and ordinal not in marks, 'Foreign or duplicate original primary')
        marks[ordinal] = mark
        if example is None:
            example = timing_example(event, mark)
    all_groups = [group for mark in marks.values() for group in mark['groups']]
    require(list(marks) == counts['nonzero_event_ids'] and len(marks) == counts['nonzero_primaries']
            and len(all_groups) == counts['pulse_groups']
            and sum(len(g['raw_row_indices']) for g in all_groups) == counts['positive_ge_rows'],
            'Original sparse census changed')
    rollup = {key: counts[key] for key in ('initial_primaries', 'zero_deposit_primaries', 'nonzero_primaries',
                                           'pulse_groups', 'positive_ge_rows')}
    return {'original': rollup, 'source_contract_id': source_id, 'chunk_index': chunk_index,
            'model_sha256': manifest['model_sha256'], 'geometry_sha256': manifest['geometry_sha256'],
            'source_position_mm': checked['selection']['source_position_mm'], 'raw_truth_stream_ref':
                (folder / ref).relative_to(ROOT).as_posix(),
            'radiation_seed': manifest['seed'], 'transport_clock': manifest['clock_policy'],
            'remage_version': checked['runtime']['executables']['remage']['version_output'],
            'transport_daughter_lifetime_limit_ns': manifest['daughter_lifetime_limit_ns'],
            'first_group_delay_range_ns': [
                min(mark['groups'][0]['first_deposit_since_parent_ns'] for mark in marks.values()),
                max(mark['groups'][0]['first_deposit_since_parent_ns'] for mark in marks.values()),
            ],
            'clock_example': example, 'marked_nonzero_events': marks}


def parent_support(groups, live_ns):
    """Union of parent times yielding a live parent or a live group onset."""
    intervals = [(0., float(live_ns))]
    for group in groups:
        delay = group['first_deposit_since_parent_ns']
        intervals.append((-delay, live_ns - delay))
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def poisson(mean, rng):
    """Small-mean direct Poisson sampling for single transport marks."""
    threshold, run, count = math.exp(-mean), 1., 0
    while True:
        run *= rng.random()
        if run <= threshold:
            return count
        count += 1


def simulate(source, loaded, seed, live_ns=LIVE_NS, activity_bq=ACTIVITY_BQ):
    unique_seed = int.from_bytes(hashlib.sha256(f'{seed}:{source}'.encode()).digest()[:8], 'big')
    rng = random.Random(unique_seed)
    marks = loaded['marked_nonzero_events']
    initial = loaded['original']['initial_primaries']
    rate_per_mark_per_ns = activity_bq / initial / 1e9
    census = Counter()
    occurrences = []
    for ordinal in range(initial):
        mark = marks.get(ordinal)
        groups = mark['groups'] if mark is not None else []
        for interval_number, (begin, end) in enumerate(parent_support(groups, live_ns)):
            width = end - begin
            for number in range(poisson(rate_per_mark_per_ns * width, rng)):
                offset = width * rng.random()
                parent = begin + offset
                parent_live = 0 <= parent < live_ns
                if parent_live:
                    census['parents'] += 1
                    census['marked_nonzero_parents' if groups else 'marked_zero_parents'] += 1
                if not groups:
                    continue
                epoch = f'{ordinal}.{interval_number}.{number}'
                timed_groups = []
                for group in groups:
                    # Add the original transport delay to the interval origin before adding its sampled offset.
                    # This avoids losing sub-ns precision when a late daughter places the parent far before t=0.
                    onset = (begin + group['first_deposit_since_parent_ns']) + offset
                    last = onset + (group['last_deposit_since_parent_ns'] - group['first_deposit_since_parent_ns'])
                    timed_groups.append({'group_id': group['group_id'], 'first_ge_deposit_ns': onset,
                                         'last_ge_deposit_ns': last, 'onset_in_live_time': 0 <= onset < live_ns,
                                         'complete_deposits_in_live_time': 0 <= onset <= last < live_ns})
                occurrences.append({'occurrence_id': epoch, 'mark_ordinal': ordinal, 'parent_decay_time_ns': parent,
                                    'parent_in_live_time': parent_live, 'groups': timed_groups})
    require(census['marked_zero_parents'] + census['marked_nonzero_parents'] == census['parents'],
            'Laboratory parent clock census does not close')
    occurrences.sort(key=lambda row: (row['parent_decay_time_ns'], row['occurrence_id']))
    return {'seed_uint64': unique_seed, 'activity_bq': activity_bq, 'live_parent_census': dict(census),
            'nonzero_mark_occurrences': occurrences}


def view(source, loaded, clock, live_ns, include_prehistory):
    eligible, counts = [], Counter()
    for occurrence in clock['nonzero_mark_occurrences']:
        live_parent = occurrence['parent_in_live_time']
        if not live_parent and not include_prehistory:
            continue
        mark = loaded['marked_nonzero_events'][occurrence['mark_ordinal']]
        counts['nonzero_mark_occurrences'] += 1
        counts['prehistory_nonzero_mark_occurrences'] += not live_parent
        for group in occurrence['groups']:
            counts['group_onsets_in_live_time'] += group['onset_in_live_time']
            counts['group_onsets_right_censored_from_live_parents'] += live_parent and group['first_ge_deposit_ns'] >= live_ns
            counts['group_onsets_inside_with_last_deposit_censored'] += (
                group['onset_in_live_time'] and not group['complete_deposits_in_live_time'])
            if group['complete_deposits_in_live_time']:
                eligible.append({'source': source, 'occurrence_id': occurrence['occurrence_id'],
                                 'raw_event_id': mark['raw_event_id'], 'campaign_initial_id': mark['campaign_initial_id'],
                                 'group_id': group['group_id'], 'first_ge_deposit_ns': group['first_ge_deposit_ns'],
                                 'last_ge_deposit_ns': group['last_ge_deposit_ns'], 'parent_precedes_live_time': not live_parent})
    eligible.sort(key=lambda group: (group['first_ge_deposit_ns'], group['occurrence_id'], group['group_id']))
    counts['eligible_groups'] = len(eligible)
    return eligible, {**clock['live_parent_census'], **counts,
                      'eligible_group_rate_per_s': len(eligible) / (live_ns / 1e9)}


def crossings(left, right):
    right_times = [group['first_ge_deposit_ns'] for group in right]
    candidates, nearby = [], []
    for a in left:
        t = a['first_ge_deposit_ns']
        i = bisect_left(right_times, t)
        close = range(max(0, i - CLOSEST_COUNT), min(len(right), i + CLOSEST_COUNT))
        lo, hi = bisect_left(right_times, t - max(WINDOWS_NS)), bisect_right(right_times, t + max(WINDOWS_NS))
        for j in sorted(set(close).union(range(lo, hi))):
            delta = right_times[j] - t
            row = (abs(delta), a['occurrence_id'], a['group_id'], right[j]['occurrence_id'], right[j]['group_id'],
                   {'cs137_left': a, 'co60_right': right[j], 'co_minus_cs_onset_ns': delta, 'absolute_onset_gap_ns': abs(delta)})
            if abs(delta) <= max(WINDOWS_NS):
                candidates.append(row)
            if j in close:
                nearby.append(row)
    return {'closest_pairs': [row[-1] for row in nsmallest(CLOSEST_COUNT, nearby)],
            'within_candidate_window': [row[-1] for row in sorted(candidates)],
            'onset_gap_counts': {str(window): sum(row[0] <= window for row in candidates) for window in WINDOWS_NS}}


def run(seed):
    hashes = {}
    complete = json.loads(bound_bytes(CAMPAIGN / 'COMPLETE.json', hashes))
    require(complete['status'] in ('completed', 'completed_with_native_failures'), 'Campaign lacks a terminal receipt')
    loaded = {source: load_marks(source, complete, hashes) for source in SOURCES}
    require(len({record['model_sha256'] for record in loaded.values()}) == 1
            and len({record['geometry_sha256'] for record in loaded.values()}) == 1,
            'Saved sources do not share the modeled detector geometry')
    clocks = {source: simulate(source, record, seed) for source, record in loaded.items()}
    views = {}
    for label, prehistory in (('fresh_source_start', False), ('equilibrated_mark_library', True)):
        selections = {source: view(source, record, clocks[source], LIVE_NS, prehistory)
                      for source, record in loaded.items()}
        views[label] = {'sources': {source: {'counts': counts, 'eligible_groups': groups}
                                   for source, (groups, counts) in selections.items()},
                        'cross_source': crossings(*(groups for groups, _ in selections.values()))}
    return {
        'kind': 'gegi_saved_two_source_clock_pilot_v1', 'status': 'completed',
        'design': {
            'live_time_ns': [0, LIVE_NS], 'interval_convention': 'inclusive start, exclusive end',
            'activity_scope': 'Independent hypothetical homogeneous 37 kBq parent-decay rates per source.',
            'seed': seed, 'python': platform.python_version(), 'generator': 'Python random.Random/MT19937',
            'source_seed_rule': 'First eight SHA-256 bytes, unsigned big endian, of ASCII "{seed}:{source}".',
            'scheduling': 'Each original transport ordinal is a mark of rate activity/original initial count, '
                          'including zero marks. A mark may be sampled repeatedly. On the union of the live time '
                          'and its translations by negative group onset delays, sample each disjoint interval '
                          'with a Poisson count and independent uniform parent times. Add the original delay to '
                          'each occurrence; all deposits under one occurrence share the same parent clock.',
            'fresh_source_start': 'Same realization restricted to parents decaying at or after time zero. '
                                  'Delayed deposits beyond the acquisition are right-censored. Counts include all '
                                  'live parents and are not hardware efficiency estimates.',
            'equilibrated_mark_library': 'Stationary independent parent clocks on the real line for this empirical '
                                         'transport library, with just the parent times affecting the finite window '
                                         'sampled. Group eligibility requires onset and last deposit inside live time. '
                                         'Analog memory and groups beginning before the window are outside this onset study.',
            'cross_source_candidate_gaps_ns': WINDOWS_NS, 'closest_pair_count_limit': CLOSEST_COUNT,
            'candidate_scope': 'Absolute difference of earliest positive Ge deposition times, distinct sources. '
                               'A window is a candidate for later readout replay and does not establish analog overlap, '
                               'successful triggering, or event identity in real data.',
            'excluded_work': {'new_transport_calls': 0, 'new_drift_calls': 0, 'adc_replays': 0},
        },
        'transport_time_evidence': {
            'manual': REMANUAL, 'configuration': ['/gps/time 0 ns', '/RMG/Processes/Stepping/ResetInitialDecayTime true'],
            'field_units': {'vertex.time': 'ns', 'tracks[].time': 'ns', 'decay_photons[].time_ns': 'ns',
                            'steps[].time_ns': 'ns', 'pulse_groups[].origin_time_ns': 'ns',
                            'pulse_groups[].last_deposit_time_ns': 'ns', 'pulse_groups[].relative_times_ns': 'ns'},
            'scope': 'Zero-time direct children identify initial parent decay on this reset clock. Track and '
                     'decay-photon fields are birth times; Ge step times are absorption/deposition, and group onset '
                     'is the first positive Ge deposit. Add only the saved delay since the parent decay to the '
                     'laboratory timestamp, preserving late daughters and within-parent correlations.',
        },
        'input_sha256': hashes, 'source_sha256': {Path(__file__).relative_to(ROOT).as_posix():
                                                  hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        'sources': {source: {**record, 'clock': clocks[source]} for source, record in loaded.items()},
        'views': views,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(arguments.output)
    result = run(arguments.seed)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open('x', encoding='utf-8', newline='\n') as target:
        json.dump(result, target, allow_nan=False, separators=(',', ':'))
        target.write('\n')
    print(json.dumps({view: {'sources': {source: row['counts'] for source, row in data['sources'].items()},
                            'cross_source': data['cross_source']['onset_gap_counts']}
                      for view, data in result['views'].items()}, indent=2))


if __name__ == '__main__':
    main()
