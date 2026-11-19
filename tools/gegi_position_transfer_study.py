"""Test a frozen family-level GeGI strip-position template on other pixels."""

import argparse
from collections import Counter
from itertools import product
import json
import math
from pathlib import Path
from statistics import median

import gegi_continuous_position_study as continuous
import gegi_digital_readout as digital
import gegi_pulse_scan as scan
import gegi_pulse_stream as stream
import gegi_substrip as substrip


CAPTURE = scan.ROOT / '.local/gegi-digital-v1/two-site-position/results'
CAPTURE_SHA256 = 'e239be0a97e7b0b99bc85842db9ee22b200bb0f43735fe743b9c0dc3dc2c708d'
EXPOSURES = ('cs18p5k-co74k-50ms', 'cs37k-co37k-250ms')
EXPOSURE_SHA256 = ('3cb7a68854a2526dbf88d62cc20883b26f1359bdc7166b8867b9d7a049763a5c',
                   '09cbc0e5a5821287b87acabe5d669fb0d7b1fccd8555b5b637479df82e2a99f7')
REFERENCE_PAIR = [9, 26]
ENERGY_KEV = 500.
SOURCES = (*continuous.SOURCES, 'gegi_position_transfer_study.py')


def interior(pair):
    return 2 <= pair[0] <= 15 and 19 <= pair[1] <= 32


def ledgers(inputs):
    counts = {}
    for name, digest in zip(EXPOSURES, EXPOSURE_SHA256, strict=True):
        path = scan.ROOT / '.local/gegi-dual-source' / name / 'report.json'
        report = inputs.read(path, digest)
        counts[name] = Counter(tuple(t['x_collecting_strips'] + t['y_collecting_strips'])
                               for t in report['triggers'] if t['single_pixel_energy_keV'] is not None)
    pairs = sorted(set().union(*counts.values()), key=lambda p: (-sum(c[p] for c in counts.values()), p))
    return [{'contact_ids': pair, 'interior': interior(pair), 'single_pixel_counts': {k: c[pair] for k, c in counts.items()}}
            for pair in pairs]


def identity_of(request):
    return {'model_sha256': request['model_sha256'], 'field_cache_sha256': request['field_cache']['sha256'],
            'field_precision_bits': request['field_precision_bits']}


def load_record(inputs, folder, point, manifest, request_identity, channels, group):
    ref = manifest['record_ref']
    checkpoint = inputs.read(folder / ref, manifest['record_sha256'])
    payload, _ = scan.qualify(checkpoint, point, manifest, request_identity, ENERGY_KEV)
    native = {s['contact_id']: s for s in payload['channel_signals']}
    return {'source_record': (folder / ref).relative_to(scan.ROOT).as_posix(),
            'source_sha256': manifest['record_sha256'], 'group': group,
            'truth_contact_ids': point['contact_ids'], 'truth_xyz_mm': point['position_mm'],
            'native': stream.prepare_native(native, channels, terminal_complete=True)}


def load_points(inputs, calibration):
    capture = inputs.read(CAPTURE / 'COMPLETE.json', CAPTURE_SHA256)
    capture_request = inputs.read(CAPTURE / 'bound-request.json', capture['request_sha256'])
    bank = inputs.read(scan.FULL / 'COMPLETE.json', scan.FULL_COMPLETE_SHA)
    bank_request = inputs.read(scan.FULL / 'bound-request.json', bank['request_sha256'])
    bank_identity = inputs.read(scan.FULL / 'identity.json', bank['bundle_identity_sha256'])
    channels, identity = capture_request['channels'], identity_of(capture_request)
    if (identity_of(bank_request) != identity or any(calibration[k] != v for k, v in identity.items())
            or bank_request['channels'] != channels
            or capture_request['injection_energy_keV'] != ENERGY_KEV
            or bank_request['injection_energy_keV'] != ENERGY_KEV):
        raise ValueError('Saved transfer banks differ from the frozen calibration model/field')
    fit_xyz = {tuple(row['position_mm']) for row in capture['records'] if row['role'] == 'fit'}
    off_pair = [row for row in capture['records'] if row['role'] == 'holdout' and interior(row['contact_ids'])]
    bank_points = [row for row in bank_request['grid'] if row['contact_ids'] == REFERENCE_PAIR
                   and row['target_ref'].startswith('diagnostic-injections/')]
    bank_manifests = inputs.validation(bank['validation_sha256'], {p['target_ref'] for p in bank_points})
    if len(off_pair) != 28 or len(bank_points) != 25 or any(tuple(p['position_mm']) in fit_xyz for p in off_pair):
        raise ValueError('Saved held-out transfer rosters changed')
    points = [load_record(inputs, CAPTURE, row, row, capture['request_sha256'], channels, 'cross_pixel_holdout')
              for row in off_pair]
    for p in bank_points:
        ref = p['target_ref']
        group = 'x09_y09_centers' if '/centre-' in ref else 'x09_y09_off_center'
        points.append(load_record(inputs, scan.FULL / 'bank', p, bank_manifests[ref],
                                  bank_identity['calibration_identity_sha256'], channels, group))
    if len({tuple(p['truth_xyz_mm']) for p in points}) != len(points):
        raise ValueError('Transfer validation positions must be distinct')
    return points, channels, identity


def family_template(calibration, geometry):
    depth = calibration['depth_cfd']
    families = {}
    for family in 'XY':
        strips = [cid for cid in sorted(calibration['strips']) if geometry[int(cid)]['family'] == family]
        template = []
        for layers in zip(*(depth['ratio_edges_by_strip'][cid] for cid in strips), strict=True):
            directions = {substrip._direction(a) for a in layers}
            template.append([median(values) for values in zip(*layers, strict=True)]
                            if len(directions) == 1 and None not in directions else None)
        families[family] = {'training_contacts': [int(cid) for cid in strips], 'ratio_edges': template}
    return {'depth_knots_mm': depth['depth_knots_mm'], 'families': families}


def transfer_axis(template, axis, feature, depth_mm):
    if feature['ratio'] is None or feature['strip_pitch_mm'] is None:
        return {'status': 'axis_measurement_unavailable', 'position_mm': None}
    bracket = substrip._bracket(depth_mm, template['depth_knots_mm']) if depth_mm is not None else None
    if bracket is None:
        return {'status': 'depth_outside_support', 'position_mm': None}
    lo, hi, fraction = bracket
    edges = template['families'][axis]['ratio_edges']
    left, right = edges[lo], edges[hi]
    if left is None or right is None or substrip._direction(left) != substrip._direction(right):
        return {'status': 'ambiguous_signed_polarity', 'position_mm': None}
    direction = substrip._direction(left)
    oriented = [direction * substrip._lerp(a, b, fraction) for a, b in zip(left, right, strict=True)]
    slot = substrip._lookup_slot(direction * feature['ratio'], oriented)
    if slot is None:
        return {'status': 'ratio_outside_support', 'position_mm': None}
    offset_pitch = -.4 + .8 * (slot + .5) / (len(oriented) - 1)
    return {'status': 'estimated', 'position_mm': feature['strip_center_mm'] + offset_pitch * feature['strip_pitch_mm'],
            'slot': slot}


def predict(template, point, result):
    measured = result['measurement']
    if measured is None or measured['calibration'] is None:
        return {'status': result['status'], 'axes': None, 'center_xy_mm': None, 'old_guarded_xy_mm': None}
    if measured['measured_contact_ids'] != point['truth_contact_ids']:
        return {'status': 'wrong_collecting_pair', 'axes': None, 'center_xy_mm': None, 'old_guarded_xy_mm': None}
    cal = measured['calibration']
    if cal['calibration_source_status'] != 'matching_saved_fields' or not interior(measured['measured_contact_ids']):
        return {'status': 'field_or_geometry_outside_support', 'axes': None, 'center_xy_mm': None,
                'old_guarded_xy_mm': None}
    centers = [cal[k]['strip_center_mm'] for k in 'xy']
    axes = {k: transfer_axis(template, k.upper(), cal[k], cal['depth']['position_mm']) for k in 'xy'}
    # The frozen production method guards on sampled pair coverage. Existing
    # strip-center fallback is its only XY output on newly tested pair IDs.
    old = [r['position_mm'] if r['position_mm'] is not None else center
           for center, r in zip(centers, (cal[k] for k in 'xy'), strict=True)
           ] if cal['calibration_pair_coverage'] == 'simulated_pair' else centers
    return {'status': 'scored', 'axes': axes, 'center_xy_mm': centers, 'old_guarded_xy_mm': old,
            'old_pair_coverage': cal['calibration_pair_coverage']}


def summarize(rows):
    all_errors, paired_errors = [[], [], []], [[], [], []]
    axes = {a: [[], []] for a in 'xy'}
    axis_status = {a: Counter() for a in 'xy'}
    for row in rows:
        truth = row['truth_xyz_mm'][:2]
        if row['status'] != 'scored':
            for a in axes:
                axis_status[a][row['status']] += 1
            continue
        center, old = row['center_xy_mm'], row['old_guarded_xy_mm']
        xy = [row['axes'][a]['position_mm'] for a in 'xy']
        for i, a in enumerate('xy'):
            axis_status[a][row['axes'][a]['status']] += 1
            if xy[i] is not None:
                axes[a][0].append(center[i] - truth[i])
                axes[a][1].append(xy[i] - truth[i])
        hybrid = [center[i] if coord is None else coord for i, coord in enumerate(xy)]
        for errors, result in zip(all_errors, (center, old, hybrid), strict=True):
            errors.append(math.dist(result, truth))
        if None not in xy:
            for errors, result in zip(paired_errors, (center, old, xy), strict=True):
                errors.append(math.dist(result, truth))
    labels = ('strip_center', 'old_guarded', 'transferred')
    return {'points': len(rows), 'readout_status': Counter(row['status'] for row in rows), 'axis_status': axis_status,
            'axis_on_supported_points': {a: {'strip_center': continuous.errors(e[0]), 'transferred': continuous.errors(e[1])}
                                         for a, e in axes.items()},
            'paired_xy': dict(zip(labels, map(continuous.errors, paired_errors), strict=True)),
            'all_scored_with_strip_center_fallback': dict(zip(labels, map(continuous.errors, all_errors), strict=True))}


def run():
    implementation = {f'tools/{name}': scan.digest(scan.ROOT / 'tools' / name) for name in SOURCES}
    inputs, calibration = scan.Inputs(), substrip.load_calibration()
    populations = ledgers(inputs)
    points, channels, identity = load_points(inputs, calibration)
    geometry = {c['id']: c for c in channels}
    template = family_template(calibration, geometry)
    summaries, cases = [], []
    for offset, seed in product(continuous.ONSET_OFFSETS_NS, (None, continuous.NOMINAL_SEED)):
        onsets = [continuous.FIRST_ONSET_NS + i * continuous.SPACING_NS + offset for i in range(len(points))]
        capture = continuous.replay([(p['native'], t, 1.) for p, t in zip(points, onsets, strict=True)], seed)
        events = capture['events']
        indices, extra = continuous.match_windows(onsets, events)
        rows = []
        for p, window in zip(points, indices, strict=True):
            result = continuous.evaluate_point(p, window, events, calibration, channels, identity)
            rows.append({k: v for k, v in p.items() if k != 'native'} | predict(template, p, result))
        cases.append({'offset_ns': offset, 'noise_seed': seed, 'adc_sha256': capture['adc_sha256'],
                      'triggers': len(events), 'unmatched_trigger_indices': extra, 'rows': rows})
        summaries.append({'offset_ns': offset, 'noise_seed': seed,
                          'by_group': {g: summarize([r for r in rows if r['group'] == g])
                                       for g in sorted({r['group'] for r in rows})},
                          'by_pair': {f'{x}:{y}': summarize([r for r in rows if r['truth_contact_ids'] == [x, y]])
                                      for x, y in sorted({tuple(r['truth_contact_ids']) for r in rows})}})
    if implementation != {ref: scan.digest(scan.ROOT / ref) for ref in implementation}:
        raise RuntimeError('Position transfer study source changed during replay')
    return {
        'kind': 'gegi_frozen_interior_position_transfer_study_v1', 'template': template,
        'design': {'energy_keV': ENERGY_KEV, 'nominal_noise_rms_v': digital._PROFILE['optional_noise_rms_V'],
                   'fit': 'The median of the two existing strip tables per face, retaining signed polarity at each '
                          'measured-CFD depth knot. No waveform from a withheld pixel changes the template.',
                   'support': 'Matching model and field, measured interior collecting pair, two available fast '
                              'neighbors, measured CFD within range and matching polarity on both bracketing planes. '
                              'Require an in-range signed ratio. Use original nine offset slots within ±0.4 pitch.',
                   'fallback': 'On measured pixels, use the measured strip center only for a missing axis. '
                               'The old guarded estimator has no full validation on the new strip pairs.',
                   'scope': 'Same-field isolated simulated pulses spaced on a continuous ADC clock. Strip-pair '
                            'counts identify target priorities and potential exposure support, without implying '
                            'validated coordinates for those measured hits.'},
        'counts': {'native_pulses': len(points), 'new_transport_calls': 0, 'new_drift_calls': 0, 'new_field_solves': 0},
        'provenance': {**identity, 'calibration_sha256': calibration['calibration_sha256'],
                       'input_sha256': inputs.hashes, 'source_sha256': implementation},
        'measured_pair_populations': populations, 'summaries': summaries, 'cases': cases,
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
    print(json.dumps(result['counts']))


if __name__ == '__main__':
    main()
