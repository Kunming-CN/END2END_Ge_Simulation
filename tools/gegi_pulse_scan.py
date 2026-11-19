"""Measure trigger, energy and lateral position recovery in saved GeGI double pulses."""

import argparse
from collections import Counter
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import platform

import numpy as np

import gegi_digital_readout as digital
import gegi_pulse_stream as stream
from gegi_native_pair_readout import complete_native
from gegi_substrip import load_calibration, substrip_axis_features


ROOT = Path(__file__).resolve().parents[1]
BANKS = ROOT / '.local/gegi-10m/signal-recovery-v1/calibration'
REGION = BANKS / 'native-region-bank/results'
FULL = BANKS / 'full34-bank/results'
LATERAL = BANKS / 'full34-lateral-pilot/results'
TOPOLOGIES = ('same_strips', 'adjacent_strips', 'far_strips')
DELAYS_NS = (0, 20, 40, 60, 100, 140, 200, 300, 400, 500, 600, 800, 1000, 1200, 1600, 2000, 3000, 4500, 6000)
PHASES_NS = (0, 10)
ENERGIES_KEV = ((250, 250), (250, 125), (125, 250))
NOISE_RMS_V = {'none': 0., 'nominal': digital._PROFILE['optional_noise_rms_V']}
NOISE_BASE_SEED = 20261118
WINDOW_END_NS = 7800
NOISY_EMPTY_REPETITIONS_PER_PHASE = 8
MATCH_TOLERANCE_NS = 60
ENERGY_TOLERANCE = .02
XY_TOLERANCE_MM = 1.
STABLE_SUFFIX_POINTS = 3
COORDINATE_TOLERANCE_MM = 1e-5
METRICS = (
    'trigger_offset_vs_truth_ns', 'trigger_offset_vs_isolated_ns', 'slow_bias_vs_isolated_keV', 'slow_bias_vs_truth_keV',
    'slow_bias_vs_isolated_relative', 'single_trigger_slow_bias_vs_pair_total_keV',
    'single_trigger_face_step_x_bias_vs_pair_total_keV', 'single_trigger_face_step_y_bias_vs_pair_total_keV',
    'xy_radial_vs_truth_mm', 'xy_radial_vs_isolated_mm',
    *(f'{axis}_bias_vs_{ref}_mm' for axis, ref in product('xy', ('truth', 'isolated'))),
    *(f'{axis}_fast_neighbor_ratio_delta_vs_{ref}'
      for axis, ref in product('xy', ('isolated', 'noiseless_isolated'))),
    *(f'{axis}_fast_collector_delta_vs_isolated_keV_equiv' for axis in 'xy'),
)
CRITERIA = ('two_distinct_triggers', 'both_energy_available', 'both_energy_within_tolerance',
            'both_xy_available', 'both_xy_within_tolerance', 'both_energy_and_xy_within_tolerance')
AVAILABILITY = ('matched_triggers', 'correct_pixel', 'energy_available', 'xy_available', 'x_available',
                'y_available', 'both_fast_ratios_available')
SOURCES = ('gegi_pulse_scan.py', 'gegi_pulse_stream.py', 'gegi_digital_readout.py', 'gegi_substrip.py',
           'gegi_substrip_calibration.json', 'gegi_event_store.py', 'gegi_native_pair_readout.py',
           'gegi_signal_reconstruction.py')
REGION_COMPLETE_SHA = '2a6f723eb9c93a92e4029bbc7112c15bae7c05e80e9109ddd6c6bdbebdf3fab1'
FULL_COMPLETE_SHA = 'b107d0a1a715181c84f0313c1a311528c3e2efcd2ca3ccfbf928145348096821'
LATERAL_COMPLETE_SHA = '0843dd963ff851ab4c15c8abcb131521974832385d7ceeb2958fe41e2da18660'
# Each vertex gives the saved pixel and (x offset/pitch, y offset/pitch, depth/mm).
# The remote pixels use saved strip-center sweeps from the same field, at positive/negative depth.
TARGETS = {
    'same_strips': (
        (((11, 24), (-.23, .16, -2.)), ((11, 24), (.24, -.16, 1.))),
        (((12, 26), (.20, .18, .5)), ((12, 26), (-.18, -.20, -1.5))),
    ),
    'adjacent_strips': (
        (((11, 24), (.22, -.18, 2.)), ((12, 24), (-.23, .19, -.5))),
        (((11, 26), (-.22, .18, -1.)), ((12, 24), (.22, -.19, 1.5))),
    ),
    'far_strips': (
        (((11, 24), (-.18, -.20, .5)), ((7, 21), (0., 0., -2.))),
        (((12, 26), (.18, -.21, -2.5)), ((6, 29), (0., 0., 2.))),
    ),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Inputs:
    def __init__(self):
        self.hashes = {}

    def read(self, path, expected):
        ref = path.relative_to(ROOT).as_posix()
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f'Sealed scan input changed: {ref}')
        self.hashes[ref] = expected
        return json.loads(raw)

    def validation(self, expected, refs):
        path = FULL / 'validation.jsonl'
        binding = hashlib.sha256()
        needles = tuple(json.dumps(ref).encode('ascii') for ref in refs)
        selected = {}
        with path.open('rb') as source:
            for line in source:
                binding.update(line)
                if any(needle in line for needle in needles):
                    row = json.loads(line)
                    if row['record_ref'] in refs:
                        selected[row['record_ref']] = row
        if binding.hexdigest() != expected or set(selected) != refs:
            raise ValueError('The verified full-34 bank roster changed')
        self.hashes[path.relative_to(ROOT).as_posix()] = expected
        return selected


def qualify(record, point, manifest, identity, energy):
    payload = record['payload']
    if (record['kind'] != 'gegi_independent_injection_checkpoint_v1'
            or record['identity_sha256'] != identity or payload['position_mm'] != point['position_mm']
            or payload['contact_ids'] != point['contact_ids'] or payload['injection_energy_keV'] != energy
            or not manifest['valid']
            or len(payload['endpoints']) != 2
            or {tuple(e['contact_ids']) for e in payload['endpoints']} != {(cid,) for cid in point['contact_ids']}):
        raise ValueError(f'Qualified saved single-point injection changed: {manifest["record_ref"]}')
    terminal = complete_native(payload)
    return payload, terminal


def select(inputs, calibration):
    region_complete = inputs.read(REGION / 'COMPLETE.json', REGION_COMPLETE_SHA)
    full_complete = inputs.read(FULL / 'COMPLETE.json', FULL_COMPLETE_SHA)
    lateral_complete = inputs.read(LATERAL / 'COMPLETE.json', LATERAL_COMPLETE_SHA)
    region = inputs.read(REGION / 'bound-request.json', region_complete['request_sha256'])
    full = inputs.read(FULL / 'bound-request.json', full_complete['request_sha256'])
    full_identity = inputs.read(FULL / 'identity.json', full_complete['bundle_identity_sha256'])
    energy = region['injection_energy_keV']
    channels = region['channels']
    identity = {'model_sha256': region['model_sha256'], 'field_cache_sha256': region['field_cache']['sha256'],
                'field_precision_bits': region['field_precision_bits']}
    if (region_complete['status'] != 'completed_fixed_interior_native_region_bank'
            or full_complete['status'] != 'completed_original_grid_full34_bank'
            or full_identity['request_sha256'] != full_complete['request_sha256']
            or any(full[k] != region[k] for k in ('channels', 'model_sha256', 'field_cache', 'field_precision_bits',
                                                 'injection_energy_keV', 'numerics'))
            or energy != calibration['reference_energy_keV']
            or any(calibration[k] != v for k, v in identity.items())
            or calibration['digital_profile_sha256'] != digital.PROFILE_SHA256):
        raise ValueError('Saved pulse sources and calibration require the same model, fields and profiles')

    training = np.asarray([r['position_mm'] for r in lateral_complete['training_records']])
    if len(training) != calibration['training_injection_count']:
        raise ValueError('Saved calibration training volume changed')
    calibration_pairs = {tuple(p) for p in calibration['sampled_contact_pairs']}
    far_pixels = {pixel for pair in TARGETS['far_strips'] for pixel, _ in pair if pixel not in calibration_pairs}
    far_refs = {p['target_ref'] for p in full['grid'] if tuple(p['contact_ids']) in far_pixels}
    validation = inputs.validation(full_complete['validation_sha256'], far_refs)
    region_manifest = {row['record_ref']: row for row in region_complete['points']}
    by_pixel = {}
    for point in region['points']:
        pixel = tuple(point['contact_ids'])
        manifest = region_manifest[point['record_ref']]
        if (manifest['status'] == 'completed' and manifest['valid'] and not manifest['reused_source']
                and point['expected_pixel_bindings'] == [list(pixel)]):
            by_pixel.setdefault(pixel, []).append((point, manifest))
    for point in full['grid']:
        pixel = tuple(point['contact_ids'])
        manifest = validation.get(point['target_ref'])
        if (manifest and manifest['status'] == 'completed' and manifest['valid']
                and manifest['endpoint_identity']['max_absolute_terminal_ideal_contact_error_keV'] == 0):
            by_pixel.setdefault(pixel, []).append((point, manifest))

    geometry = {c['id']: c for c in channels}
    sources, pairs, used = {}, [], []
    for topology, targets in TARGETS.items():
        for pair_index, pair in enumerate(targets, 1):
            pair_id = f'{topology}-{pair_index}'
            component_ids = []
            for site_index, (pixel, offsets) in enumerate(pair, 1):
                centers = [geometry[c]['strip_center_mm'] for c in pixel]
                pitches = [abs(geometry[c+1]['strip_center_mm'] - a) for c, a in zip(pixel, centers)]
                candidates = []
                for point, manifest in by_pixel[pixel]:
                    xyz = point['position_mm']
                    normalized = [(v - center) / pitch for v, center, pitch in zip(xyz, centers, pitches)] + xyz[2:]
                    if (any(abs(v) > bound for v, bound in zip(normalized, (.4, .4, 5.)))
                            or any(math.dist(xyz, previous) <= COORDINATE_TOLERANCE_MM for previous in used)
                            or np.any(np.linalg.norm(training - xyz, axis=1) <= COORDINATE_TOLERANCE_MM)):
                        continue
                    distance = sum(((v - aim) / bound)**2
                                   for v, aim, bound in zip(normalized, offsets, (.4, .4, 5.)))
                    candidates.append((distance, manifest['record_ref'], point, manifest))
                if not candidates:
                    raise ValueError(f'No qualifying saved point for {pair_id} at {pixel}')
                _, ref, point, manifest = min(candidates, key=lambda row: row[:2])
                if pixel in calibration_pairs:
                    path = REGION / ref
                    source_identity = region_complete['request_sha256']
                else:
                    path = FULL / 'bank' / ref
                    source_identity = full_identity['calibration_identity_sha256']
                record = inputs.read(path, manifest['record_sha256'])
                payload, terminal = qualify(record, point, manifest, source_identity, energy)
                used.append(point['position_mm'])
                component_id = f'{pair_id}-{site_index}'
                component_ids.append(component_id)
                sources[component_id] = {'position_mm': payload['position_mm'], 'contact_ids': list(pixel),
                                         'strip_names': [geometry[c]['name'] for c in pixel],
                                         'target_offsets_pitch_and_depth_mm': offsets,
                                         'record_ref': path.relative_to(ROOT).as_posix(),
                                         'record_sha256': manifest['record_sha256'],
                                         'endpoint_support': terminal,
                                         'native_energy_keV': energy}
                native = {s['contact_id']: s for s in payload['channel_signals']}
                sources[component_id]['native'] = stream.prepare_native(native, channels, terminal_complete=True)
            first, second = (sources[c] for c in component_ids)
            jumps = [abs(a - b) for a, b in zip(first['contact_ids'], second['contact_ids'])]
            valid_topology = ('same_strips' if jumps == [0, 0]
                              else 'adjacent_strips' if 1 in jumps
                              else 'far_strips' if min(jumps) >= 3 else None)
            if valid_topology != topology:
                raise ValueError(f'Strip topologies disagree at {pair_id}')
            pairs.append({'pair_id': pair_id, 'topology': topology, 'components': component_ids,
                          'collecting_strip_distance_xy': jumps})
    return channels, identity, sources, pairs


def noise_seed(noise, mode, *parts):
    if noise == 'none':
        return None
    label = json.dumps([NOISE_BASE_SEED, mode, *parts], separators=(',', ':')).encode('ascii')
    return int.from_bytes(hashlib.sha256(label).digest()[:8], 'big')


def observe(components, phase, seed, channels, calibration, identity):
    time, adc = stream.acquire(components, phase_ns=phase, noise_seed=seed, window_end_ns=WINDOW_END_NS)
    reco = stream.reconstruct(time, adc, channels=channels, calibration=calibration, source_identity=identity)
    geometry = {channel['id']: channel for channel in channels}
    events = []
    for event in reco['events']:
        pixel = event['contact_ids']
        position = event.get('position') or {}
        qualified_position = (position.get('calibration_source_status') == 'matching_saved_fields'
                              and position.get('calibration_pair_coverage') == 'simulated_pair')
        channel_rows = {row['contact_id']: row for row in event['channels']}
        axes = []
        for index, axis in enumerate('xy'):
            row = position.get(axis, {})
            collector = pixel[index] if pixel else None
            feature = channel_rows.get(collector, {})
            ratio = substrip_axis_features(collector, axis.upper(), channel_rows, geometry)
            status = ('trigger_pixel_or_energy_unavailable' if event['slow_energy_keV'] is None
                      else 'uncalibrated_pixel')
            axes.append({'position_mm': row.get('position_mm') if qualified_position else None,
                         'position_status': row.get('status', status),
                         'neighbor_ratio': ratio['ratio'], 'neighbor_ratio_status': ratio['status'],
                         'collector_fast_keV_equiv': feature.get('fast_signal_keV_equiv')})
        events.append({'trigger_time_ns': event['trigger_time_ns'], 'rise_end_ns': event['rise_end_ns'],
                       'contact_ids': pixel, 'step_contact_ids': event['step_contact_ids'],
                       'face_step_keV': event['face_step_keV'], 'slow_energy_keV': event['slow_energy_keV'],
                       'axes': axes, 'flags': event['flags'],
                       'pileup_by_contact': {label: [c['contact_id'] for c in channel_rows.values()
                                                    if any(label in flag and 'pileup' in flag for flag in c['flags'])]
                                             for label in ('slow', 'fast')}})
    acquisition = {key: reco[key] for key in ('flags', 'saturated_contact_ids', 'rejected_rises', 'unconfirmed_activity_count')}
    return events, acquisition


def match(anchors, events):
    """After reconstruction, find the largest chronological one-to-one timing match."""
    offsets = [[event['trigger_time_ns'] - anchor for event in events] for anchor in anchors]
    choices = [[None, *(i for i, delta in enumerate(row) if abs(delta) <= MATCH_TOLERANCE_NS)] for row in offsets]

    def rank(assignment):
        selected = [i for i in assignment if i is not None]
        if selected != sorted(set(selected)):
            return (1,)
        residual = sum(abs(offsets[site][i]) for site, i in enumerate(assignment) if i is not None)
        return (-len(selected), residual, tuple(len(events) if i is None else i for i in assignment))
    return min(product(*choices), key=rank)


def difference(current, reference):
    return None if current is None or reference is None else current - reference


def pulse_scores(event, reference, clean, source, energy):
    scores = {key: False for key in AVAILABILITY}
    comparisons = {}
    if event is None:
        return scores, comparisons
    scores['matched_triggers'] = True
    scores['correct_pixel'] = event['contact_ids'] == source['contact_ids']
    comparisons['trigger_offset_vs_truth_ns'] = event['trigger_time_ns']
    if clean is not None:
        comparisons['trigger_offset_vs_isolated_ns'] = event['trigger_time_ns'] - clean['trigger_time_ns']
    if not scores['correct_pixel']:
        return scores, comparisons

    observed = event['slow_energy_keV']
    iso_energy = reference['slow_energy_keV'] if reference is not None and reference['contact_ids'] == source['contact_ids'] else None
    scores['energy_available'] = observed is not None
    comparisons['slow_bias_vs_truth_keV'] = difference(observed, energy)
    comparisons['slow_bias_vs_isolated_keV'] = difference(observed, iso_energy)
    comparisons['slow_bias_vs_isolated_relative'] = (
        (observed - iso_energy) / iso_energy if observed is not None and iso_energy is not None and iso_energy > 0 else None)

    scores['both_fast_ratios_available'] = all(row['neighbor_ratio'] is not None for row in event['axes'])
    for index, axis in enumerate('xy'):
        values = event['axes'][index]
        ref_axis = reference['axes'][index] if reference is not None and reference['contact_ids'] == source['contact_ids'] else {}
        clean_axis = clean['axes'][index] if clean is not None and clean['contact_ids'] == source['contact_ids'] else {}
        scores[f'{axis}_available'] = values['position_mm'] is not None
        comparisons[f'{axis}_bias_vs_truth_mm'] = difference(values['position_mm'], source['position_mm'][index])
        comparisons[f'{axis}_bias_vs_isolated_mm'] = difference(values['position_mm'], ref_axis.get('position_mm'))
        comparisons[f'{axis}_fast_neighbor_ratio_delta_vs_isolated'] = difference(values['neighbor_ratio'], ref_axis.get('neighbor_ratio'))
        comparisons[f'{axis}_fast_neighbor_ratio_delta_vs_noiseless_isolated'] = difference(values['neighbor_ratio'], clean_axis.get('neighbor_ratio'))
        comparisons[f'{axis}_fast_collector_delta_vs_isolated_keV_equiv'] = difference(
            values['collector_fast_keV_equiv'], ref_axis.get('collector_fast_keV_equiv'))
    scores['xy_available'] = scores['x_available'] and scores['y_available']
    for ref in ('truth', 'isolated'):
        axes = [comparisons[f'{axis}_bias_vs_{ref}_mm'] for axis in 'xy']
        if all(value is not None for value in axes):
            comparisons[f'xy_radial_vs_{ref}_mm'] = math.hypot(*axes)
    return scores, {key: value for key, value in comparisons.items() if value is not None}


def isolate(sources, channels, calibration, identity):
    rows = {}
    for component_id, source in sources.items():
        for noise, phase, energy in product(NOISE_RMS_V, PHASES_NS, sorted({e for pair in ENERGIES_KEV for e in pair})):
            seed = noise_seed(noise, 'isolated', component_id, phase, energy)
            events, acquisition = observe([(source['native'], 0, energy / source['native_energy_keV'])],
                                          phase, seed, channels, calibration, identity)
            clean = matched_event(rows[(component_id, 'none', phase, energy)]) if noise != 'none' else None
            anchor = clean['trigger_time_ns'] if clean is not None else 0.
            index, = match([anchor], events)
            row = {'component_id': component_id, 'noise': noise, 'phase_ns': phase, 'energy_keV': energy,
                   'seed': seed, 'events': events, 'acquisition': acquisition, 'matched_event_index': index,
                   'unmatched_triggers': len(events) - (index is not None)}
            event = matched_event(row)
            row['availability'], row['metrics'] = pulse_scores(event, clean, clean, source, energy)
            rows[(component_id, noise, phase, energy)] = row
    return rows


def matched_event(reference):
    index = reference['matched_event_index']
    return None if index is None else reference['events'][index]


def empty_controls(channels, calibration, identity):
    rows = []
    for noise in NOISE_RMS_V:
        repeats = NOISY_EMPTY_REPETITIONS_PER_PHASE if noise == 'nominal' else 1
        events_by_phase = Counter()
        rejected_by_phase = Counter()
        for phase, repeat in product(PHASES_NS, range(repeats)):
            events, acquisition = observe([], phase, noise_seed(noise, 'empty', phase, repeat),
                                          channels, calibration, identity)
            events_by_phase[phase] += len(events)
            rejected_by_phase[phase] += len(acquisition['rejected_rises'])
        rows.append({'noise': noise, 'trials': repeats * len(PHASES_NS),
                     'trials_per_phase': repeats, 'false_triggers': sum(events_by_phase.values()),
                     'rejected_two_face_rises': sum(rejected_by_phase.values())})
    return rows


def scan_case(pair, sources, isolated, noise, phase, energies, delay, channels, calibration, identity):
    components = pair['components']
    truth = [sources[c] for c in components]
    onsets = (0, delay)
    # Every separation is a whole ADC tick, so the isolated references share the clock phase.
    clean_rows = [isolated[(c, 'none', phase, e)] for c, e in zip(components, energies)]
    clean = [matched_event(row) for row in clean_rows]
    reference = [matched_event(isolated[(c, noise, phase, e)]) for c, e in zip(components, energies)]
    seed = noise_seed(noise, 'paired', pair['pair_id'], phase, *energies)
    system_input = [(source['native'], onset, energy / source['native_energy_keV'])
                    for source, onset, energy in zip(truth, onsets, energies)]
    events, acquisition = observe(system_input, phase, seed, channels, calibration, identity)
    anchors = [onset + (event['trigger_time_ns'] if event is not None else 0.) for onset, event in zip(onsets, clean)]
    assignment = match(anchors, events)
    matched = sum(i is not None for i in assignment)
    usable = delay > 0 and len(events) == matched == 2
    comparisons, availability = [], []
    for index, source in enumerate(truth):
        observed = events[assignment[index]].copy() if assignment[index] is not None else None
        if observed is not None:
            observed['trigger_time_ns'] -= onsets[index]
        scores, metrics = pulse_scores(observed, reference[index], clean[index], source, energies[index])
        if not usable:
            # A merged or otherwise unresolved acquisition cannot qualify individual features.
            metrics = {key: value for key, value in metrics.items() if delay > 0 and key.startswith('trigger_')}
            scores = {key: value if key == 'matched_triggers' else False for key, value in scores.items()}
        availability.append(scores)
        comparisons.append(metrics)
    metrics = {}
    one_trigger = len(events) == 1 and matched > 0
    multiple_strips = False
    if one_trigger:
        event = events[0]
        if event['slow_energy_keV'] is not None:
            metrics['single_trigger_slow_bias_vs_pair_total_keV'] = event['slow_energy_keV'] - sum(energies)
        if event['face_step_keV'] is not None:
            for axis, step in zip('xy', event['face_step_keV']):
                metrics[f'single_trigger_face_step_{axis}_bias_vs_pair_total_keV'] = step - sum(energies)
        x_count = sum(cid <= 17 for cid in event['step_contact_ids'])
        multiple_strips = x_count > 1 or len(event['step_contact_ids']) - x_count > 1
    both_energy = usable and all(score['energy_available'] for score in availability)
    both_xy = usable and all(score['xy_available'] for score in availability)
    energy_pass = both_energy and all(abs(row.get('slow_bias_vs_isolated_relative', math.inf)) <= ENERGY_TOLERANCE
                                       for row in comparisons)
    xy_pass = both_xy and all(row.get('xy_radial_vs_isolated_mm', math.inf) <= XY_TOLERANCE_MM for row in comparisons)
    return {
        'pair_id': pair['pair_id'], 'topology': pair['topology'], 'noise': noise, 'delay_ns': delay,
        'phase_ns': phase, 'energies_keV': energies, 'seed': seed, 'events': events, 'acquisition': acquisition,
        'clean_anchors_available': [event is not None for event in clean],
        'match_anchors_ns': anchors, 'matched_event_indices': assignment, 'metrics': metrics,
        'pulse_metrics': comparisons, 'pulse_availability': availability,
        'two_distinct_triggers': usable, 'both_energy_available': both_energy,
        'both_energy_within_tolerance': energy_pass, 'both_xy_available': both_xy,
        'both_xy_within_tolerance': xy_pass, 'both_energy_and_xy_within_tolerance': energy_pass and xy_pass,
        'both_pixels_correct': usable and all(score['correct_pixel'] for score in availability),
        'both_fast_ratios_available': usable and all(score['both_fast_ratios_available'] for score in availability),
        'one_trigger_for_two': one_trigger, 'single_trigger_multiple_collecting_strips': multiple_strips,
        'missing_truth_pulses': 2 - matched,
        'unmatched_triggers': len(events) - matched, 'reconstructed_triggers': len(events),
        'no_matched_triggers': matched == 0,
    }


def stats(rows):
    result = {}
    for key in METRICS:
        data = [row[key] for row in rows if key in row]
        count = len(data)
        result[key] = {'n': count, 'mean': math.fsum(data) / count if count else None,
                       'rms': math.sqrt(math.fsum(v * v for v in data) / count) if count else None,
                       'max_abs': max(map(abs, data)) if count else None}
    return result


def aggregate(trials, isolated, pairs):
    topo_by_component = {c: pair['topology'] for pair in pairs for c in pair['components']}
    groups = {}
    for row in trials:
        groups.setdefault((row['topology'], row['noise'], row['delay_ns']), []).append(row)
    iso_groups = {}
    for row in isolated.values():
        iso_groups.setdefault((topo_by_component[row['component_id']], row['noise']), []).append(row)
    summary, isolated_summary, stability = [], [], []
    for topology, noise in product(TOPOLOGIES, NOISE_RMS_V):
        references = iso_groups[topology, noise]
        isolated_summary.append({
            'topology': topology, 'noise': noise, 'trials': len(references),
            **{key: sum(row['availability'][key] for row in references) for key in AVAILABILITY},
            'unmatched_triggers': sum(row['unmatched_triggers'] for row in references),
            'metrics': stats([row['metrics'] for row in references]),
        })
        scan = []
        for delay in DELAYS_NS:
            group = groups[topology, noise, delay]
            count_fields = (*CRITERIA, 'both_pixels_correct', 'both_fast_ratios_available', 'one_trigger_for_two',
                            'single_trigger_multiple_collecting_strips', 'missing_truth_pulses', 'unmatched_triggers',
                            'reconstructed_triggers', 'no_matched_triggers')
            out = {'topology': topology, 'noise': noise, 'delay_ns': delay, 'trials': len(group), 'truth_pulses': 2 * len(group),
                   **{key: sum(row[key] for row in group) for key in count_fields}}
            out['false_triggers'] = out['unmatched_triggers']
            event_rows = [event for row in group for event in row['events']]
            out['electrode_pileup'] = {
                branch: {
                    'events_with_channel_pileup': sum(bool(e['pileup_by_contact'][branch]) for e in event_rows),
                    'affected_event_channels': sum(len(e['pileup_by_contact'][branch]) for e in event_rows),
                    'affected_event_collecting_channels': sum(len(set(e['contact_ids'] or ()).intersection(
                        e['pileup_by_contact'][branch])) for e in event_rows),
                } for branch in ('slow', 'fast')
            }
            out['event_flags'] = dict(Counter(flag for e in event_rows for flag in e['flags']))
            out['rejected_two_face_rises'] = sum(len(row['acquisition']['rejected_rises']) for row in group)
            out['pulse_availability'] = {key: sum(score[key] for row in group for score in row['pulse_availability'])
                                         for key in AVAILABILITY}
            if (out['pulse_availability']['matched_triggers'] + out['missing_truth_pulses'] != out['truth_pulses']
                    or out['pulse_availability']['matched_triggers'] + out['unmatched_triggers'] != out['reconstructed_triggers']):
                raise ValueError('Trigger census does not close')
            out['metrics'] = stats([metrics for row in group for metrics in [row['metrics'], *row['pulse_metrics']]])
            scan.append(out)
        summary.extend(scan)
        for criterion in CRITERIA:
            passed = [row[criterion] == row['trials'] for row in scan]
            first = next((i for i, ok in enumerate(passed) if ok), None)
            stable = next((i for i in range(len(scan) - STABLE_SUFFIX_POINTS + 1) if all(passed[i:])), None)
            stability.append({
                'topology': topology, 'noise': noise, 'criterion': criterion,
                'stable_from_ns': DELAYS_NS[stable] if stable is not None else None,
                'first_full_pass_ns': DELAYS_NS[first] if first is not None else None,
                'regressions_after_first_full_pass_ns': [] if first is None else
                    [DELAYS_NS[i] for i in range(first + 1, len(scan)) if not passed[i]],
                'count_decrease_delays_ns': [b['delay_ns'] for a, b in zip(scan, scan[1:]) if b[criterion] < a[criterion]],
            })
    return summary, isolated_summary, stability


def by_pair(trials):
    grouped = {}
    for case in trials:
        grouped.setdefault((case['pair_id'], case['topology'], case['noise'], case['delay_ns']), []).append(case)
    fields = (*CRITERIA, 'one_trigger_for_two', 'single_trigger_multiple_collecting_strips', 'unmatched_triggers')
    return [{'pair_id': pair_id, 'topology': topology, 'noise': noise, 'delay_ns': delay, 'trials': len(rows),
             **{key: sum(row[key] for row in rows) for key in fields}}
            for (pair_id, topology, noise, delay), rows in grouped.items()]


def run():
    sources_before = {f'tools/{name}': digest(ROOT / 'tools' / name) for name in SOURCES}
    if any(delay % digital._DT for delay in DELAYS_NS):
        raise ValueError('Choose whole-tick separations to preserve the isolated ADC phase')
    inputs = Inputs()
    calibration = load_calibration()
    channels, identity, sources, pairs = select(inputs, calibration)
    isolated = isolate(sources, channels, calibration, identity)
    empty_summary = empty_controls(channels, calibration, identity)
    trials = [scan_case(pair, sources, isolated, noise, phase, energies, delay, channels, calibration, identity)
              for pair, noise, phase, energies, delay in product(pairs, NOISE_RMS_V, PHASES_NS, ENERGIES_KEV, DELAYS_NS)]
    summary, isolated_summary, stability = aggregate(trials, isolated, pairs)
    if sources_before != {ref: digest(ROOT / ref) for ref in sources_before}:
        raise ValueError('Scan source changed during replay. Recompute from frozen sources.')
    return {
        'kind': 'gegi_saved_double_pulse_scan_v1', 'status': 'completed',
        'counts': {'pairs': len(pairs), 'saved_components': len(sources), 'paired_trials': len(trials),
                   'isolated_trials': len(isolated), 'empty_control_trials': sum(row['trials'] for row in empty_summary),
                   'new_field_solves': 0, 'new_drift_calls': 0, 'new_transport_calls': 0},
        'design': {
            'delays_ns': DELAYS_NS, 'adc_phases_ns': PHASES_NS, 'ordered_energies_keV': ENERGIES_KEV,
            'noise_rms_V': NOISE_RMS_V, 'noise_base_seed': NOISE_BASE_SEED, 'record_end_ns': WINDOW_END_NS,
            'noise_seed_rule': 'First eight SHA-256 bytes, unsigned big endian, of compact ASCII JSON: '
                               '[base,"paired",pair_id,phase,E1,E2], [base,"isolated",component_id,phase,E], '
                               'or [base,"empty",phase,zero_based_repeat]. '
                               'The paired noise timeline is reused across delays for the same combination.',
            'match_tolerance_ns': MATCH_TOLERANCE_NS, 'relative_energy_tolerance': ENERGY_TOLERANCE,
            'xy_isolated_radial_tolerance_mm': XY_TOLERANCE_MM, 'minimum_stable_suffix_points': STABLE_SUFFIX_POINTS,
            'selection': 'Choose nearest eligible point to each fixed geometric target in units of '
                         '0.4 x pitch, 0.4 y pitch and 5 mm depth, ties by saved reference. No waveform '
                         'features enter selection. Qualified points have complete native endpoints and '
                         'distinct coordinates outside the training point set.',
            'source_coordinate_exclusion_mm': COORDINATE_TOLERANCE_MM,
            'matching': 'One-to-one chronological matching within ±60 ns of each arrival plus its phase- '
                        'and energy-matched noiseless isolated trigger offset. Maximize matched count, '
                        'minimize total absolute error, break ties in event order. If that reference is '
                        'missing, anchor to the physical onset. Strip IDs and energy never enter matching.',
            'trigger_success': 'Exactly two reconstructed triggers, both matched at a nonzero input delay. '
                               'An unmatched trigger is false under this scoring rule. A sole matched trigger '
                               'leaves two-to-one overlap or a suppressed trigger unresolved. A single merged '
                               'trigger can still include multiple collecting strips. Electrode-local pileup '
                               'uses the readout flags and is counted separately from the global trigger merge.',
            'feature_success': 'Require two distinct triggers and correct X/Y strip identities, then a '
                               'qualified slow energy or two calibrated lateral coordinates on each event. '
                               'Tolerance success further requires the corresponding isolated reference values. '
                               'Report truth bias independently of those relative tolerances.',
            'metric_denominators': 'Per-trial criteria use all preset paired windows. Axis and pulse counts '
                                   'use the two true pulses per paired window or one per isolated window. '
                                   'Bias summaries use only matched pulses with the stated observable and '
                                   'reference available. Energy, XY and fast feature biases require the '
                                   'correct collecting pixel and two resolved triggers in a paired window. '
                                   'Unresolved windows retain the trigger census and any single-trigger total bias.',
            'stability': 'Require complete success in every trial at the quoted delay and every later '
                         'sampled delay, for at least three sampled delays. This defines a finite-grid result.',
            'electronics': stream.DEFINITION,
            'scope': 'Fixed current superpositions of independently saved point injections in one nominal '
                     'field. ADC noise is synthetic Gaussian noise and does not represent instrument data. '
                     'Energy scaling uses linear native charge. Detector response and calibration use one '
                     'simulated model. Millimeter XY requires supported calibration, leaving remote coordinates '
                     'null. Fast observables compare to isolated waveforms, with no independent fast-area '
                     'truth. Depth is unscored.',
        },
        'provenance': {
            **identity, 'native_settings': {'base_injection_energy_keV': float(calibration['reference_energy_keV']),
                                            'native_point_random_seed': None},
            'digital_profile_sha256': digital.PROFILE_SHA256, 'digital_timing_sha256': digital.TIMING_SHA256,
            'substrip_calibration_sha256': calibration['calibration_sha256'],
            'source_sha256': sources_before, 'input_sha256': inputs.hashes,
            'python': platform.python_version(), 'numpy': np.__version__,
        },
        'pairs': pairs, 'components': {c: {k: v for k, v in source.items() if k != 'native'} for c, source in sources.items()},
        'empty_summary': empty_summary, 'isolated_summary': isolated_summary, 'summary': summary,
        'pair_summary': by_pair(trials), 'stability': stability,
        'isolated_trials': list(isolated.values()), 'trials': trials,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        json.dump(result, output, allow_nan=False, separators=(',', ':'))
        output.write('\n')
    print(json.dumps(result['counts'], indent=2))


if __name__ == '__main__':
    main()
