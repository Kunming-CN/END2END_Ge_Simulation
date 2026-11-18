"""Build GeGI substrip coefficients and compare them on a separate saved scan."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
from statistics import fmean, median
import time

import gegi_digital_readout as D
import gegi_substrip as S


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / '.local/gegi-10m/signal-recovery-v1/calibration/full34-lateral-pilot/results'
ADDITIONAL = RESULTS.parent.parent / 'native-region-bank/results'
PAIRS = ((11, 24), (11, 26), (12, 24), (12, 26))
TRAIN = (-.4, 0., .4)
TRAIN_DEPTHS = tuple(range(-5, 6))
VALIDATION = (-.2, .2)
ADDITIONAL_OFFSETS = (-.3, .3)
ADDITIONAL_DEPTHS = (-4., -2., 1., 3., 4.)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_json(root, relative_path, expected):
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Saved lateral record escaped its source directory')
    raw = path.read_bytes()
    if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Saved lateral record hash changed: ' + relative_path)
    return json.loads(raw)


def digital_observation(row, channels):
    native = {c['contact_id']: c for c in row['channel_signals']}
    result = D.digital_event(native, channels, terminal_complete=True)
    if result['profile_sha256'] != D.PROFILE_SHA256 or result['timing_sha256'] != D.TIMING_SHA256:
        raise ValueError('Digital profile changed during measurement')
    return result


def saved_observations(results):
    complete = checked_json(results, 'COMPLETE.json', None)
    identity = checked_json(results, 'identity.json', complete['identity_sha256'])
    request = checked_json(results, 'bound-request.json', complete['request_sha256'])
    channels = identity['channels']
    energy = identity['injection_energy_keV']
    precision = request['field_precision_bits']
    if (complete['status'] != 'completed_fixed_lateral_full34_reference_pilot'
            or identity['kind'] != 'gegi_full34_lateral_reference_identity_v1'
            or identity['request_sha256'] != complete['request_sha256']
            or identity['model_sha256'] != request['model_sha256']
            or identity['field_cache'] != request['field_cache'] or channels != request['channels']
            or [c['id'] for c in channels] != list(range(1, 35)) or energy != 500. or precision != 32):
        raise ValueError('Saved lateral scan identity changed')
    source = {'model_sha256': identity['model_sha256'], 'field_cache_sha256': identity['field_cache']['sha256'],
              'field_precision_bits': precision}
    geometry = {c['id']: c for c in channels}
    requested = {p['record_ref']: p for p in request['points']}
    groups = {}
    for role, records, offsets, depths in (
            ('train', complete['training_records'], TRAIN, TRAIN_DEPTHS),
            ('validation', complete['validation_records'], VALIDATION, (-4.5, -2.5, 0., 2.5, 4.5))):
        observations = {}
        for item in records:
            ref = item['record_ref']
            point = requested[ref]
            checkpoint = checked_json(results, ref, item['record_sha256'])
            diagnostic = checked_json(results, item['diagnostic_ref'], item['diagnostic_sha256'])
            row = checkpoint['payload']
            endpoints = diagnostic['endpoint_identity']
            if (checkpoint['kind'] != 'gegi_independent_injection_checkpoint_v1'
                    or checkpoint['identity_sha256'] != complete['identity_sha256']
                    or item['valid'] is not True or row['valid'] is not True
                    or row['status'] != 'completed' or item['status'] != row['status']
                    or point['role'] != role or row['reference_role'] != role
                    or any(row[k] != point[k] or item[k] != point[k] for k in
                           ('contact_ids', 'position_mm', 'lateral_offset_pitch_fraction'))
                    or row['signal_coverage'] != identity['signal_coverage']
                    or row['injection_energy_keV'] != energy or endpoints['native_precision_bits'] != precision
                    or endpoints['max_absolute_terminal_ideal_contact_error_keV'] != 0):
                raise ValueError('Saved lateral record identity or endpoint completeness changed: ' + ref)
            digital = digital_observation(row, channels)
            features = {c['contact_id']: c for c in digital['channels']}
            pair = tuple(point['contact_ids'])
            offsets_xy = tuple(point['lateral_offset_pitch_fraction'])
            key = pair, (*offsets_xy, point['position_mm'][2])
            if key in observations:
                raise ValueError('Duplicate saved lateral scan point')
            axes = [S.substrip_axis_features(cid, family, features, geometry) for cid, family in zip(pair, 'XY')]
            for coordinate, offset, axis in zip(point['position_mm'], offsets_xy, axes):
                expected_position = axis['strip_center_mm'] + axis['strip_pitch_mm'] * offset
                if not math.isclose(coordinate, expected_position, abs_tol=1e-9, rel_tol=0):
                    raise ValueError('Saved lateral coordinate has an inconsistent strip pitch or center: ' + ref)
            observations[key] = {'record_ref': ref, 'contact_ids': list(pair), 'offsets_pitch_fraction': list(offsets_xy),
                                 'position_mm': point['position_mm'], 'axes': axes, 'digital': digital}
        expected = {(pair, point) for pair in PAIRS for point in itertools.product(offsets, offsets, depths)}
        if set(observations) != expected:
            raise ValueError('Saved lateral scan grid is incomplete or changed')
        groups[role] = list(observations.values())
    return source, energy, channels, groups, complete


def additional_observations(results, source, energy, channels, original_groups):
    complete = checked_json(results, 'COMPLETE.json', None)
    request = checked_json(results, 'bound-request.json', complete['request_sha256'])
    if (complete['status'] != 'completed_fixed_interior_native_region_bank'
            or request['kind'] != 'gegi_fixed_interior_native_region_request_v1'
            or request['model_sha256'] != source['model_sha256']
            or request['field_cache']['sha256'] != source['field_cache_sha256']
            or request['field_precision_bits'] != source['field_precision_bits']
            or request['injection_energy_keV'] != energy or request['channels'] != channels):
        raise ValueError('Independent native-grid scan does not match the calibration model')
    records = {p['record_ref']: p for p in complete['points']}
    geometry = {c['id']: c for c in channels}
    original = {tuple(p['position_mm']) for group in original_groups.values() for p in group}

    # Choose the points using geometry only. No waveform is read until the 80
    # evaluation references are fixed, and no previously imported record is eligible.
    selected = []
    for pair in PAIRS:
        axes = [S.substrip_axis_features(cid, family, {}, geometry) for cid, family in zip(pair, 'XY')]
        centers = [axis['strip_center_mm'] for axis in axes]
        pitches = [axis['strip_pitch_mm'] for axis in axes]
        eligible = {}
        for p in request['points']:
            ref = p['record_ref']
            coords = p['position_mm']
            if (p['expected_pixel_bindings'] != [list(pair)] or records[ref]['reused_source']
                    or not TRAIN_DEPTHS[0] <= coords[2] <= TRAIN_DEPTHS[-1]
                    or any(math.dist(coords, other) < 1e-5 for other in original)):
                continue
            offsets = [(x - center) / pitch for x, center, pitch in zip(coords, centers, pitches)]
            if all(TRAIN[0] <= offset <= TRAIN[-1] for offset in offsets):
                eligible[ref] = (coords, offsets)
        for dx, dy, z in itertools.product(ADDITIONAL_OFFSETS, ADDITIONAL_OFFSETS, ADDITIONAL_DEPTHS):
            target = (centers[0] + pitches[0] * dx, centers[1] + pitches[1] * dy, z)
            ref = min(eligible, key=lambda name: (math.dist(eligible[name][0], target), name))
            coords, offsets = eligible.pop(ref)
            selected.append({'record_ref': ref, 'contact_ids': list(pair), 'position_mm': coords,
                             'offsets_pitch_fraction': offsets, 'selection_target_mm': target})
    for point in selected:
        ref = point['record_ref']
        item = records[ref]
        checkpoint = checked_json(results, ref, item['record_sha256'])
        row = checkpoint['payload']
        endpoints = row['endpoints']
        if (checkpoint['kind'] != 'gegi_independent_injection_checkpoint_v1'
                or checkpoint['identity_sha256'] != complete['request_sha256']
                or item['valid'] is not True or row['valid'] is not True
                or row['status'] != 'completed' or row['status'] != item['status']
                or row['contact_ids'] != point['contact_ids'] or row['position_mm'] != point['position_mm']
                or row['injection_energy_keV'] != energy or len(endpoints) != 2
                or {tuple(e['contact_ids']) for e in endpoints} != {(cid,) for cid in point['contact_ids']}
                or any(e['status'] != 'contact' or e['step_limit_reached'] is not False for e in endpoints)):
            raise ValueError('Independent native-grid injection lost its verified identity or endpoint: ' + ref)
        point['digital'] = digital_observation(row, channels)
    return selected, complete['request_sha256']


def ratio_edges(levels):
    offsets = [TRAIN[0] + i * (TRAIN[-1] - TRAIN[0]) / S.SLOT_COUNT for i in range(S.SLOT_COUNT + 1)]
    edges = [levels[1] + abs(x / TRAIN[-1]) * (levels[0 if x < 0 else 2] - levels[1]) for x in offsets]
    edges[0], edges[-1] = levels[0], levels[-1]
    return offsets, edges


def fit_tables(training, source, energy):
    ratios = defaultdict(lambda: defaultdict(list))
    geometry = {}
    for point in training:
        for offset, axis in zip(point['offsets_pitch_fraction'], point['axes']):
            if axis['status'] != 'features_available':
                raise ValueError('A fixed calibration signal lacks compatible features: ' + point['record_ref'])
            cid = axis['contact_id']
            geometry[cid] = {k: axis[k] for k in ('strip_center_mm', 'strip_pitch_mm', 'neighbor_contact_ids')}
            ratios[cid][offset].append(axis['ratio'])
    calibration = {'kind': S.CALIBRATION_KIND, **source, 'digital_profile_sha256': D.PROFILE_SHA256,
                   'reference_energy_keV': energy, 'position_unit': 'mm', 'ratio_definition': S.RATIO_DEFINITION,
                   'slot_count': S.SLOT_COUNT, 'sampled_contact_pairs': [list(p) for p in PAIRS], 'strips': {},
                   'training_lateral_offsets_pitch_fraction': list(TRAIN), 'training_depths_mm': list(TRAIN_DEPTHS),
                   'training_injection_count': len(training),
                   'method': 'Per-strip median ratios at three known lateral offsets. Piecewise-linear ratio boundaries for nine equal widths over the scanned interval.',
                   'reference': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3178965/'}
    fit = {}
    for cid, grouped in sorted(ratios.items()):
        levels = [median(grouped[x]) for x in TRAIN]
        fit[str(cid)] = [{'offset_pitch_fraction': x, 'median_ratio': level, 'minimum_ratio': min(grouped[x]),
                          'maximum_ratio': max(grouped[x]), 'sample_count': len(grouped[x])}
                         for x, level in zip(TRAIN, levels)]
        direction = S._direction(levels)
        if direction is None:
            raise ValueError('Nonmonotonic calibration medians for contact ' + str(cid))
        # Interpolate the median forward response through three observed known coordinates.
        offsets, edges = ratio_edges([direction * v for v in levels])
        g = geometry[cid]
        positions = [g['strip_center_mm'] + g['strip_pitch_mm'] * (lo + hi) / 2 for lo, hi in zip(offsets, offsets[1:])]
        positions[S.SLOT_COUNT // 2] = g['strip_center_mm']
        calibration['strips'][str(cid)] = {**g, 'ratio_direction': direction, 'oriented_ratio_edges': edges,
                                           'slot_position_mm': positions}
    return S.validate_calibration(calibration), fit


def fit_depth(training, calibration):
    timing = defaultdict(list)
    lateral = defaultdict(list)
    for point in training:
        feature = {row['contact_id']: row['preamp_cfd50_ns'] for row in point['digital']['channels']}
        x, y = (feature[cid] for cid in point['contact_ids'])
        depth = point['position_mm'][2]
        if x is None or y is None:
            raise ValueError('A fixed training signal lacks collector CFD timing: ' + point['record_ref'])
        timing[depth].append(x - y)
        for axis, offset in zip(point['axes'], point['offsets_pitch_fraction']):
            lateral[axis['contact_id'], depth, offset].append(axis['ratio'])
    depths = sorted(timing)
    timing_medians = [median(timing[z]) for z in depths]
    direction = S._direction(timing_medians)
    if direction is None:
        raise ValueError('Training CFD medians are nonmonotonic across depth')
    strips = {cid: [ratio_edges([median(lateral[int(cid), z, x]) for x in TRAIN])[1] for z in depths]
              for cid in calibration['strips']}
    calibration['depth_cfd'] = {'definition': S.CFD_DIFFERENCE_DEFINITION, 'difference_unit': 'ns', 'depth_unit': 'mm',
                                'timing_sha256': D.TIMING_SHA256, 'depth_knots_mm': depths, 'cfd_direction': direction,
                                'oriented_cfd_knots_ns': [direction * value for value in timing_medians],
                                'ratio_edges_by_strip': strips,
                                'method': 'Piecewise-linear depth from training-plane CFD medians. Interpolate lateral ratio edges between depth planes with matching polarity.'}
    return S.validate_calibration(calibration)


def paired_errors(pairs):
    n = len(pairs)
    if not n:
        return {'compared': 0}
    baseline, substrip = zip(*pairs)
    return {'compared': n, 'center_mean_absolute_error_mm': fmean(baseline),
            'substrip_mean_absolute_error_mm': fmean(substrip), 'center_rmse_mm': math.sqrt(fmean(v*v for v in baseline)),
            'substrip_rmse_mm': math.sqrt(fmean(v*v for v in substrip)),
            'improved': sum(a > b for a, b in pairs), 'unchanged': sum(a == b for a, b in pairs),
            'worsened': sum(a < b for a, b in pairs)}


def evaluate(calibration, observations, channels, source, mode):
    rows = []
    for point in observations:
        estimate = S.infer_position(calibration, *point['contact_ids'], point['digital'], channels,
                                    source_identity=source, mode=mode)
        row = {k: v for k, v in point.items() if k not in ('axes', 'digital')}
        depth = estimate['depth']
        z = depth['position_mm']
        row['depth'] = {**depth, 'error_mm': None if z is None else abs(z - point['position_mm'][2])}
        for axis, truth in zip(('x', 'y'), point['position_mm']):
            result = estimate[axis]
            center = result['strip_center_mm']
            position = result['position_mm']
            row[axis] = {**result, 'center_error_mm': abs(center - truth),
                         'substrip_error_mm': None if position is None else abs(position - truth)}
        rows.append(row)
    return summarize(rows), rows


def summarize(rows):
    summary = {}
    for axis in ('x', 'y'):
        values = [r[axis] for r in rows]
        pairs = [(v['center_error_mm'], v['substrip_error_mm']) for v in values if v['substrip_error_mm'] is not None]
        summary[axis] = {**paired_errors(pairs), 'total': len(values), 'status_counts': dict(Counter(v['status'] for v in values)),
                         'all_points_strip_center_fallback': paired_errors([
                             (v['center_error_mm'], v['substrip_error_mm'] if v['substrip_error_mm'] is not None
                              else v['center_error_mm']) for v in values])}
    both = [r for r in rows if all(r[axis]['substrip_error_mm'] is not None for axis in ('x', 'y'))]
    summary['xy'] = {**paired_errors([(math.hypot(r['x']['center_error_mm'], r['y']['center_error_mm']),
                                      math.hypot(r['x']['substrip_error_mm'], r['y']['substrip_error_mm'])) for r in both]),
                     'total': len(rows)}
    summary['xy']['all_points_strip_center_fallback'] = paired_errors([
        (math.hypot(*(r[a]['center_error_mm'] for a in ('x', 'y'))),
         math.hypot(*(r[a]['substrip_error_mm'] if r[a]['substrip_error_mm'] is not None
                      else r[a]['center_error_mm'] for a in ('x', 'y')))) for r in rows])
    errors = [r['depth']['error_mm'] for r in rows if r['depth']['error_mm'] is not None]
    summary['depth'] = {'total': len(rows), 'compared': len(errors),
                        'status_counts': dict(Counter(r['depth']['status'] for r in rows))}
    if errors:
        summary['depth'].update(mean_absolute_error_mm=fmean(errors), rmse_mm=math.sqrt(fmean(e*e for e in errors)))
    return summary


def write_fresh(path, content):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(content, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=RESULTS)
    parser.add_argument('--additional-results', type=Path, default=ADDITIONAL)
    parser.add_argument('--coefficients', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    results = args.results.resolve()
    if args.coefficients.exists() or args.report.exists() or args.coefficients.resolve() == args.report.resolve():
        raise ValueError('Use separate new output paths and preserve existing evidence')
    started = time.perf_counter()
    sources = [Path(__file__), Path(D.__file__), Path(S.__file__)]
    code = {path.relative_to(ROOT).as_posix(): sha(path) for path in sources}
    source, energy, channels, groups, complete = saved_observations(results)
    calibration, fit = fit_tables(groups['train'], source, energy)
    calibration = fit_depth(groups['train'], calibration)
    additional_results = args.additional_results.resolve()
    additional, additional_request_hash = additional_observations(additional_results, source, energy, channels, groups)
    comparisons = {}
    for set_name, points in (('original_lateral_scan', groups['validation']), ('independent_native_grid', additional)):
        comparisons[set_name] = {}
        for mode in ('pooled', 'cfd_conditioned'):
            summary, rows = evaluate(calibration, points, channels, source, mode)
            comparisons[set_name][mode] = {'summary': summary, 'validation': rows}
    independent = comparisons['independent_native_grid']['cfd_conditioned']['summary']
    calibration['evaluation'] = {
        'kind': 'independent_same_model_saved_injection_check', 'mode': 'cfd_conditioned',
        'validation_injection_count': len(additional), 'matched_xy_count': independent['xy']['compared'],
        'matched_depth_count': independent['depth']['compared'],
        'strip_center_xy_rmse_mm': independent['xy'].get('center_rmse_mm'),
        'conditioned_xy_rmse_mm': independent['xy'].get('substrip_rmse_mm'),
        'depth_rmse_mm': independent['depth'].get('rmse_mm'),
    }
    if code != {path.relative_to(ROOT).as_posix(): sha(path) for path in sources}:
        raise ValueError('Calibration source changed while processing. Preserve inputs and retry after the code freezes.')
    write_fresh(args.coefficients, calibration)
    write_fresh(args.report, {'kind': 'gegi_substrip_saved_injection_evaluation_v1', **source,
        'coefficients_sha256': sha(args.coefficients), 'digital_profile_sha256': calibration['digital_profile_sha256'],
        'source_code_sha256': code, 'source_completion_sha256': sha(results / 'COMPLETE.json'),
        'source_identity_sha256': complete['identity_sha256'], 'source_request_sha256': complete['request_sha256'],
        'additional_completion_sha256': sha(additional_results / 'COMPLETE.json'),
        'additional_request_sha256': additional_request_hash,
        'reference_energy_keV': energy, 'training_records': len(groups['train']),
        'validation_records_original': len(groups['validation']), 'validation_records_additional': len(additional),
        'fit_diagnostics_by_contact': fit, 'paired_comparisons': comparisons,
        'additional_selection': {'target_offset_pitch_fractions': list(ADDITIONAL_OFFSETS),
                                 'target_depths_mm': list(ADDITIONAL_DEPTHS),
                                 'rule': 'Closest distinct nonreused, single-pair native-grid point in same scan bounds to each fixed target. Separate coordinates and waveforms were selected from geometry before feature extraction.'},
        'local_processing_seconds': time.perf_counter() - started,
        'scope': 'Same-model simulated point injections. Validation coordinates were excluded from both fits. The conditioned method was explored after reviewing pooled results on the original scan. The native-grid set is an additional independent same-model check. Known injection strip pairs isolate localization. Spatial resolution and hardware performance are unmeasured.'})
    for name, modes in comparisons.items():
        for mode, comparison in modes.items():
            summary = comparison['summary']
            print(name, mode, json.dumps({'xy': summary['xy'], 'depth': summary['depth']}))


if __name__ == '__main__':
    main()
