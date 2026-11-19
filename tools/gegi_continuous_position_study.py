"""Test the frozen GeGI position calibration on withheld continuous ADC replay."""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from itertools import product
import json
import math
from pathlib import Path
import platform

import numpy as np

import gegi_digital_readout as digital
from gegi_event_energy import estimate_event_energy
from gegi_exposure_stream import ADCExposure, reconstruct_exposure
import gegi_pulse_scan as scan
import gegi_pulse_stream as stream
from gegi_substrip import infer_position, load_calibration


REFERENCE = scan.ROOT / '.local/gegi-digital-v1/calibration/conditioned-validation.json'
REFERENCE_SHA256 = '6756fb372c754224bbd97f7c7b267f0ac93a1f9e7da30c5a3bd7099bbf4a8b75'
ENERGIES_KEV = (250, 500, 662)
ONSET_OFFSETS_NS = (0, 10)
SPACING_NS = 20_000
FIRST_ONSET_NS = 1_000
TAIL_NS = 3_000
NOMINAL_SEED = 20261119
SPOT_INDICES = (0, 25, 45, 65)
SOURCES = (*scan.SOURCES, 'gegi_imaging.py', 'gegi_event_energy.py', 'gegi_exposure_stream.py',
           'gegi_continuous_position_study.py')


def load_inputs(inputs, calibration):
    reference = inputs.read(REFERENCE, REFERENCE_SHA256)
    completion = inputs.read(scan.REGION / 'COMPLETE.json', reference['additional_completion_sha256'])
    request = inputs.read(scan.REGION / 'bound-request.json', reference['additional_request_sha256'])
    training = inputs.read(scan.LATERAL / 'COMPLETE.json', reference['source_completion_sha256'])
    channels = request['channels']
    energy = request['injection_energy_keV']
    identity = {'model_sha256': request['model_sha256'], 'field_cache_sha256': request['field_cache']['sha256'],
                'field_precision_bits': request['field_precision_bits']}
    if (reference['coefficients_sha256'] != calibration['calibration_sha256']
            or reference['digital_profile_sha256'] != digital.PROFILE_SHA256
            or energy != calibration['reference_energy_keV']
            or completion['request_sha256'] != reference['additional_request_sha256']
            or training['request_sha256'] != reference['source_request_sha256']
            or any(calibration[k] != v or reference[k] != v for k, v in identity.items())):
        raise ValueError('The frozen calibration, independent roster and saved field differ')
    original = reference['paired_comparisons']['independent_native_grid']['cfd_conditioned']
    counts = Counter(tuple(row['contact_ids']) for row in original['validation'])
    if (reference['validation_records_additional'] != 80
            or counts != {tuple(pair): 20 for pair in calibration['sampled_contact_pairs']}):
        raise ValueError('Expected 20 independent saved records per calibrated strip pair')
    training_coordinates = [row['position_mm'] for row in training['training_records']]
    records = {point['record_ref']: point for point in completion['points']}
    points = []
    for row in original['validation']:
        ref = row['record_ref']
        manifest = records[ref]
        if manifest['reused_source'] or any(math.dist(row['position_mm'], xyz) < 1e-5 for xyz in training_coordinates):
            raise ValueError('Independent evaluation overlaps training at ' + ref)
        checkpoint = inputs.read(scan.REGION / ref, manifest['record_sha256'])
        payload, _ = scan.qualify(checkpoint, row, manifest, completion['request_sha256'], energy)
        native = {signal['contact_id']: signal for signal in payload['channel_signals']}
        points.append({'record_ref': ref, 'record_sha256': manifest['record_sha256'],
                       'truth_contact_ids': row['contact_ids'], 'truth_xyz_mm': row['position_mm'],
                       'frozen_isolated_xyz_mm': [row[a]['position_mm'] for a in ('x', 'y', 'depth')],
                       'native': stream.prepare_native(native, channels, terminal_complete=True)})
    if len({point['record_ref'] for point in points}) != 80:
        raise ValueError('Duplicate independent saved injection')
    return channels, energy, identity, points, original['summary']


def match_windows(onsets, events):
    """Score a wide-spaced replay after production trigger finding."""
    times = [pulse['trigger_time_ns'] for pulse in events]
    tol = scan.MATCH_TOLERANCE_NS
    if any(right - left <= 2 * tol for left, right in zip(onsets, onsets[1:])):
        raise ValueError('Pulse scoring windows must be disjoint')
    windows = [list(range(bisect_left(times, onset - tol), bisect_right(times, onset + tol)))
               for onset in onsets]
    matched = {i for indices in windows for i in indices}
    return windows, sorted(set(range(len(events))) - matched)


def measure_trigger(trigger, calibration, channels, identity):
    event = estimate_event_energy(trigger)
    row = {'trigger_time_ns': trigger['trigger_time_ns'],
           'measured_contact_ids': event['x_contact_ids'] + event['y_contact_ids'],
           'single_pixel_energy_keV': trigger['slow_energy_keV'],
           'pulse_flags': trigger['flags'], 'event_energy_flags': event['flags'],
           'calibration': None, 'supported_xyz_mm': None}
    if not event['retains_legacy_single']:
        return row | {'status': 'single_pixel_energy_unavailable'}
    position = infer_position(calibration, *row['measured_contact_ids'], trigger, channels,
                              source_identity=identity, mode='cfd_conditioned')
    row['calibration'] = position
    if (position['calibration_source_status'] != 'matching_saved_fields'
            or position['calibration_pair_coverage'] != 'simulated_pair'):
        return row | {'status': 'calibration_transfer_unverified'}
    coordinates = [position[a]['position_mm'] for a in ('x', 'y', 'depth')]
    if all(v is not None for v in coordinates):
        row['supported_xyz_mm'] = coordinates
    collector_ids = set(row['measured_contact_ids'])
    row['collector_measurements'] = [
        {'contact_id': c['contact_id'], 'slow_energy_keV': c['slow_energy_keV'],
         'preamp_cfd50_ns': c['preamp_cfd50_ns']}
        for c in trigger['channels'] if c['contact_id'] in collector_ids]
    return row | {'status': 'supported_calibration_pair'}


def evaluate_point(point, indices, events, calibration, channels, identity):
    if len(indices) != 1:
        return {'status': 'missing_trigger' if not indices else 'multiple_triggers_in_window',
                'trigger_indices': indices, 'measurement': None}
    measurement = measure_trigger(events[indices[0]], calibration, channels, identity)
    status = measurement['status']
    if measurement['measured_contact_ids'] != point['truth_contact_ids'] and status == 'supported_calibration_pair':
        status = 'different_collecting_pair'
    return {'status': status, 'trigger_indices': indices, 'measurement': measurement}


def errors(values):
    n = len(values)
    return {'n': n, 'rms_mm': math.sqrt(math.fsum(v * v for v in values) / n) if n else None,
            'mae_mm': math.fsum(abs(v) for v in values) / n if n else None,
            'max_abs_mm': max(map(abs, values), default=None)}


def summarize(rows):
    axis_status = {axis: Counter() for axis in ('x', 'y', 'depth')}
    axis_errors = {axis: [[], []] for axis in axis_status}
    xy, xy_all, xyz = [[], []], [[], []], [[], []]
    for row in rows:
        status = row['status']
        if status != 'supported_calibration_pair':
            for counts in axis_status.values():
                counts[status] += 1
            continue
        estimate = row['measurement']['calibration']
        truth = row['truth_xyz_mm']
        pos = [estimate[a]['position_mm'] for a in axis_status]
        centers = [estimate[a]['strip_center_mm'] for a in 'xy']
        for i, axis in enumerate(axis_status):
            axis_status[axis][estimate[axis]['status']] += 1
            if pos[i] is not None:
                axis_errors[axis][0].append((centers[i] if i < 2 else 0.) - truth[i])
                axis_errors[axis][1].append(pos[i] - truth[i])
        xy_all[0].append(math.dist(centers, truth[:2]))
        hybrid = [p if p is not None else c for p, c in zip(pos[:2], centers, strict=True)]
        xy_all[1].append(math.dist(hybrid, truth[:2]))
        if all(p is not None for p in pos[:2]):
            xy[0].append(xy_all[0][-1])
            xy[1].append(xy_all[1][-1])
        if all(p is not None for p in pos):
            xyz[0].append(math.dist([*centers, 0.], truth))
            xyz[1].append(math.dist(pos, truth))
    return {'total_saved_points': len(rows), 'status_counts': Counter(r['status'] for r in rows),
            'axis_status_counts': axis_status,
            'axes': {a: {'paired_static_baseline': errors(vals[0]), 'estimate': errors(vals[1])}
                     for a, vals in axis_errors.items()},
            'xy_both_available': {'strip_center': errors(xy[0]), 'substrip': errors(xy[1])},
            'xy_with_measured_strip_center_fallback': {'strip_center': errors(xy_all[0]), 'hybrid': errors(xy_all[1])},
            'supported_xyz': {'strip_center_and_midplane': errors(xyz[0]), 'estimate': errors(xyz[1])}}


def replay(components, seed):
    end_ns = components[-1][1] + TAIL_NS
    return reconstruct_exposure(ADCExposure(components, live_time_ns=end_ns, phase_ns=0, noise_seed=seed))


def run():
    implementations = {f'tools/{name}': scan.digest(scan.ROOT / 'tools' / name) for name in SOURCES}
    inputs = scan.Inputs()
    calibration = load_calibration()
    channels, reference_energy, identity, points, frozen_summary = load_inputs(inputs, calibration)
    comparisons, isolated_spots = [], []
    metadata = [{k: v for k, v in point.items() if k != 'native'} for point in points]
    for energy, offset, seed in product(ENERGIES_KEV, ONSET_OFFSETS_NS, (None, NOMINAL_SEED)):
        onsets = [FIRST_ONSET_NS + i * SPACING_NS + offset for i in range(len(points))]
        components = [(p['native'], onset, energy / reference_energy)
                      for p, onset in zip(points, onsets, strict=True)]
        acquisition = replay(components, seed)
        events = acquisition['events']
        windows, unmatched = match_windows(onsets, events)
        rows = [ref | {'injection_time_ns': onset} | evaluate_point(
            point, indices, events, calibration, channels, identity) for point, ref, onset, indices in zip(
                points, metadata, onsets, windows, strict=True)]
        comparisons.append({'injection_energy_keV': energy, 'injection_offset_ns': offset, 'noise_seed': seed,
                            'adc_sha256': acquisition['adc_sha256'], 'trigger_count': len(events),
                            'unmatched_trigger_times_ns': [events[i]['trigger_time_ns'] for i in unmatched],
                            'saturated_contact_ids': acquisition['saturated_contact_ids'],
                            'summary': summarize(rows), 'points': rows})
        if energy == reference_energy and offset == 0:
            for i in SPOT_INDICES:
                isolated = replay([components[i]], seed)
                matches, extras = match_windows([onsets[i]], isolated['events'])
                result = evaluate_point(points[i], matches[0], isolated['events'], calibration, channels, identity)
                isolated_spots.append({'record_ref': points[i]['record_ref'], 'noise_seed': seed,
                                       'adc_sha256': isolated['adc_sha256'], 'extra_triggers': len(extras),
                                       'isolated': result, 'spaced': rows[i]})
    if implementations != {ref: scan.digest(scan.ROOT / ref) for ref in implementations}:
        raise RuntimeError('Continuous position study source changed during replay')
    return {
        'kind': 'gegi_continuous_position_transfer_study_v1',
        'counts': {'independent_native_pulses': len(points), 'exposures': len(comparisons),
                   'isolated_spot_checks': len(isolated_spots), 'new_transport_calls': 0,
                   'new_field_solves': 0, 'new_drift_calls': 0},
        'design': {'adc_sample_period_ns': digital._DT, 'adc_phase_ns': 0,
                   'injection_offsets_ns': ONSET_OFFSETS_NS, 'spaced_pulse_interval_ns': SPACING_NS,
                   'energies_keV': ENERGIES_KEV, 'native_reference_energy_keV': reference_energy,
                   'nominal_noise_rms_v': digital._PROFILE['optional_noise_rms_V'],
                   'nominal_noise_seed': NOMINAL_SEED, 'match_radius_ns': scan.MATCH_TOLERANCE_NS,
                   'scope': 'The same original 80 independent positions on the matching saved field. Energy '
                            'scaling is linear in native induced charge. Every condition uses the same roster.',
                   'measurement': 'The ADC trigger, qualified collecting pair and raw per-collector slow, signed '
                                  'neighbor fast and CFD channels feed the frozen position estimator. Truth '
                                  'only scores the resulting measurements after reconstruction.',
                   'acknowledged_limits': 'No calibration fit, geometry changes, pileup stress or hardware '
                                          'resolution claim. Promotion requires the original model/field and '
                                          'sampled pair guards. Strip-center fallback is scored only in XY. '
                                          'The static depth benchmark is the detector midplane, z = 0 mm.'},
        'provenance': {**identity, 'calibration_sha256': calibration['calibration_sha256'],
                       'digital_profile_sha256': digital.PROFILE_SHA256, 'digital_timing_sha256': digital.TIMING_SHA256,
                       'source_sha256': implementations, 'input_sha256': inputs.hashes,
                       'python': platform.python_version(), 'numpy': np.__version__},
        'frozen_isolated_reference_summary': frozen_summary, 'continuous_exposures': comparisons,
        'isolated_spot_checks': isolated_spots,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    path = parser.parse_args().output
    if path.exists():
        raise FileExistsError(path)
    result = run()
    payload = json.dumps(result, allow_nan=False, separators=(',', ':')) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as output:
        output.write(payload)
    print(json.dumps({'counts': result['counts'], 'exposures': [
        {'injection_energy_keV': e['injection_energy_keV'], 'injection_offset_ns': e['injection_offset_ns'],
         'noise_seed': e['noise_seed'], 'xy': e['summary']['xy_with_measured_strip_center_fallback'],
         'depth': e['summary']['axes']['depth']['estimate'], 'xyz': e['summary']['supported_xyz']['estimate']}
        for e in result['continuous_exposures']]}, indent=2))


if __name__ == '__main__':
    main()
