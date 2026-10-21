"""Fixed lateral-injection forward comparison; no event fitting or native calls."""
from __future__ import annotations
import argparse
from collections import Counter
import itertools
import json
from pathlib import Path
import time
import numpy as np
import gegi_signal_reconstruction as R
import scenario_workflow as W

ROOT = Path(__file__).resolve().parents[1]
PIXELS = ((11, 24), (11, 26), (12, 24), (12, 26))
TRAIN_AXES = ((-.4, 0., .4), (-.4, 0., .4), tuple(range(-5, 6)))
VALIDATION_AXES = ((-.2, .2), (-.2, .2), (-4.5, -2.5, 0., 2.5, 4.5))
ENERGY_KEV = 500.


def bracket(axis, value):
    axis = np.asarray(axis, dtype=float)
    if (len(axis) < 2 or not np.isfinite(axis).all() or not np.all(np.diff(axis) > 0)
            or not np.isfinite(value) or value < axis[0] or value > axis[-1]):
        raise ValueError('Interpolation requires finite increasing axes and an in-bounds point')
    high = min(int(np.searchsorted(axis, value, side='right')), len(axis)-1)
    low = high-1
    fraction = (value-axis[low])/(axis[high]-axis[low])
    return ((float(axis[low]), 1-fraction), (float(axis[high]), fraction))


def corner_weights(axes, point):
    """Eight tensor-product weights; zero-weight corners need no response."""
    if len(axes) != 3 or len(point) != 3:
        raise ValueError('Three interpolation axes and coordinates required')
    return {tuple(c[0] for c in corner): float(np.prod([c[1] for c in corner]))
            for corner in itertools.product(*(bracket(a, p) for a, p in zip(axes, point)))}


def interpolate(training, axes, point):
    values = []
    for corner, weight in corner_weights(axes, point).items():
        if weight == 0:
            continue
        if corner not in training:
            raise ValueError('Missing interpolation corner: '+str(corner))
        values.append(np.asarray(training[corner])*weight)
    return sum(values)


def describe(values):
    a = np.asarray(values, dtype=float)
    return ({'n': len(a), 'median': float(np.median(a)), 'p90': float(np.percentile(a, 90)),
             'max': float(a.max())} if len(a) else {'n': 0})


def waveform(row):
    """Native signed keV, fixed FIT_GRID; reject existing out-of-window activity."""
    signals = row.get('channel_signals')
    if signals is None:
        return None, {'reason': row['status'], 'late_activity_channels': [], 'late_max_deviation_keV': None}
    if (row.get('signal_coverage') != R.ALL34_COVERAGE
            or [s['contact_id'] for s in signals] != R.ALL34_IDS):
        raise ValueError('Complete native-signed34-channel coverage required')
    output = []; late = []; maximum = 0.
    for signal in signals:
        t, q = R._wave(signal)
        deviation = float(np.max(np.abs(q[t > R.FIT_GRID_NS[-1]]-q[-1]), initial=0.))
        maximum = max(maximum, deviation)
        # Same fixed support check as the saved-signal reconstruction.
        if deviation > max(1e-7, abs(q[-1])*1e-8):
            late.append(signal['contact_id'])
        output.append(np.interp(R.FIT_GRID_NS, t, q, left=0, right=q[-1]))
    reason = row['status'] if row['valid'] is not True else 'activity_beyond_250ns' if late else None
    return (np.asarray(output) if reason is None else None), {
        'reason': reason, 'late_activity_channels': late, 'late_max_deviation_keV': maximum}


def error_metrics(prediction, reference):
    error = prediction-reference
    rms = np.sqrt(np.mean(error**2, axis=1)); maximum = np.max(np.abs(error), axis=1)
    return {'max_channel_rms_keV': float(rms.max()), 'max_channel_normalized_rms': float(rms.max()/ENERGY_KEV),
        'max_absolute_error_keV': float(maximum.max()), 'max_rms_contact_id': int(np.argmax(rms))+1,
        'channels': [{'contact_id': cid, 'rms_error_keV': float(r), 'max_absolute_error_keV': float(m)}
                     for cid, r, m in zip(R.ALL34_IDS, rms, maximum)]}


def compare(results, request):
    """Read only a completed fixed pilot; write one new derivative report."""
    started = time.perf_counter(); results = Path(results).resolve(); request = Path(request).resolve()
    output = results/'forward-comparison.json'
    if output.exists():
        raise FileExistsError(output)
    sources = {ref: W.sha(ROOT/ref) for ref in (
        'tools/gegi_lateral_forward_comparison.py', 'tools/gegi_signal_reconstruction.py', 'tools/scenario_workflow.py')}
    bindings = {}

    def checked(path, expected=None):
        raw = path.read_bytes(); digest = R._sha(raw)
        if expected is not None and digest != expected:
            raise ValueError('Capture input hash changed: '+str(path))
        bindings[str(path)] = digest
        return json.loads(raw)

    complete = checked(results/'COMPLETE.json'); identity = checked(results/'identity.json', complete['identity_sha256'])
    req = checked(request, complete['request_sha256'])
    if (complete['status'] != 'completed_fixed_lateral_full34_reference_pilot'
            or identity['kind'] != 'gegi_full34_lateral_reference_identity_v1'
            or identity['request_sha256'] != complete['request_sha256']
            or (ROOT/identity['request_ref']).resolve() != request
            or identity['signal_coverage'] != R.ALL34_COVERAGE
            or identity['injection_energy_keV'] != ENERGY_KEV):
        raise ValueError('Fixed lateral-pilot identity changed')
    if ([c['id'] for c in identity['channels']] != R.ALL34_IDS
            or any(c['wiring_factor'] != (1 if c['id'] <= 17 else -1) for c in identity['channels'])):
        raise ValueError('Original fixed channel/wiring convention changed')
    points = {p['record_ref']: p for p in req['points']}
    lists = {'train': complete['training_records'], 'validation': complete['validation_records']}
    refs = [item['record_ref'] for records in lists.values() for item in records]
    if len(req['points']) != 476 or len(refs) != 476 or len(set(refs)) != 476 or set(refs) != set(points):
        raise ValueError('Fixed476-record capture is incomplete or duplicated')
    records = {}; status_counts = {}; endpoint_counts = {}
    for role, items in lists.items():
        expected = {(pixel, tuple(c)) for pixel in PIXELS for c in itertools.product(
            *(TRAIN_AXES if role == 'train' else VALIDATION_AXES))}
        actual = set(); statuses = Counter(); endpoint = Counter()
        for item in items:
            ref = item['record_ref']; point = points[ref]
            path = (results/ref).resolve(); diagpath = (results/item['diagnostic_ref']).resolve()
            if not path.is_relative_to(results) or not diagpath.is_relative_to(results):
                raise ValueError('Pilot record escaped results')
            checkpoint = checked(path, item['record_sha256']); diagnostic = checked(diagpath, item['diagnostic_sha256'])
            row = checkpoint['payload']
            if (checkpoint['kind'] != 'gegi_independent_injection_checkpoint_v1'
                    or checkpoint['identity_sha256'] != complete['identity_sha256']
                    or point['role'] != role or row['reference_role'] != role
                    or any(row[k] != point[k] or item[k] != point[k] for k in
                        ('contact_ids', 'position_mm', 'lateral_offset_pitch_fraction'))
                    or row['injection_energy_keV'] != ENERGY_KEV
                    or row['status'] != item['status'] or row['valid'] != item['valid']):
                raise ValueError('Fixed calibration coordinates/status/identity changed')
            coordinate = (*point['lateral_offset_pitch_fraction'], point['position_mm'][2])
            key = (tuple(point['contact_ids']), coordinate)
            if key in actual:
                raise ValueError('Duplicate lateral coordinate')
            actual.add(key); values, support = waveform(row); statuses[row['status']] += 1
            ep = diagnostic['endpoint_identity']
            endpoint['diagnostic_null' if ep is None else 'ideal_contact_unknown' if
                     ep['max_absolute_terminal_ideal_contact_error_keV'] is None else 'ideal_contact_known'] += 1
            compact_ep = None if ep is None else {k: ep[k] for k in (
                'max_absolute_terminal_identity_error_keV', 'max_absolute_terminal_ideal_contact_error_keV',
                'X_face_terminal_sum_minus_injection_keV', 'Y_face_terminal_sum_minus_injection_keV')}
            records[role, key] = {'record_ref': ref, 'values': values, 'support': support,
                'status': row['status'], 'valid': row['valid'], 'position_mm': row['position_mm'], 'endpoint_identity': compact_ep}
        if actual != expected:
            raise ValueError('Fixed train/validation grid changed or is incomplete')
        status_counts[role] = dict(statuses); endpoint_counts[role] = dict(endpoint)
    rows = []
    for pixel in PIXELS:
        training = {coord: row for (role, (p, coord)), row in records.items() if role == 'train' and p == pixel}
        for coordinate in itertools.product(*VALIDATION_AXES):
            reference = records['validation', (pixel, coordinate)]
            result = {'contact_ids': list(pixel), 'lateral_offset_pitch_fraction': list(coordinate[:2]),
                'position_mm': reference['position_mm'], 'reference_record_ref': reference['record_ref'],
                'reference_status': reference['status'], 'reference_valid': reference['valid'],
                'reference_support': reference['support'], 'endpoint_identity': reference['endpoint_identity']}
            for mode in ('centre', 'trilinear'):
                weights = ({(0., 0., z): w for z, w in bracket(TRAIN_AXES[2], coordinate[2])}
                           if mode == 'centre' else corner_weights(TRAIN_AXES, coordinate))
                used = [(c, w) for c, w in weights.items() if w != 0]
                excluded = [{'record_ref': training[c]['record_ref'], **training[c]['support']}
                            for c, _ in used if training[c]['values'] is None]
                if reference['values'] is None or excluded:
                    result[mode] = {'status': 'excluded', 'reason': 'reference_unavailable' if
                        reference['values'] is None else 'training_corner_unavailable', 'excluded_training': excluded}
                else:
                    prediction = sum(training[c]['values']*w for c, w in used)
                    result[mode] = {'status': 'compared', **error_metrics(prediction, reference['values']),
                        'training_weights': [{'record_ref': training[c]['record_ref'], 'weight': w} for c, w in used]}
            rows.append(result)
    paired = [r for r in rows if r['centre']['status'] == r['trilinear']['status'] == 'compared']
    metrics = {}
    for key in ('max_channel_rms_keV', 'max_channel_normalized_rms', 'max_absolute_error_keV'):
        a = [r['centre'][key] for r in paired]; b = [r['trilinear'][key] for r in paired]
        metrics[key] = {'centre': describe(a), 'trilinear': describe(b),
            'improved': sum(y < x for x, y in zip(a, b)), 'worse': sum(y > x for x, y in zip(a, b)),
            'tied': sum(y == x for x, y in zip(a, b))}
    for ref, expected in sources.items():
        if W.sha(ROOT/ref) != expected:
            raise ValueError('Comparison source changed')
    for path, expected in bindings.items():
        if W.sha(path) != expected:
            raise ValueError('Capture input changed')
    report = {'kind': 'gegi_fixed_lateral_forward_comparison_v1', 'source_sha256': sources,
        'input_sha256': bindings, 'capture_status': complete.get('status'), 'status_counts': status_counts,
        'endpoint_counts': endpoint_counts, 'validation_count': len(rows), 'paired_count': len(paired),
        'mode_counts': {mode: dict(Counter(r[mode]['status'] for r in rows)) for mode in ('centre', 'trilinear')},
        'mode_exclusion_reasons': {mode: dict(Counter(r[mode]['reason'] for r in rows
            if r[mode]['status'] == 'excluded')) for mode in ('centre', 'trilinear')},
        'reference_exclusion_reasons': dict(Counter(r['reference_support']['reason'] for r in rows
            if r['reference_support']['reason'] is not None)),
        'paired_metrics': metrics, 'records': rows, 'elapsed_seconds': time.perf_counter()-started,
        'new_fit_calls': 0, 'new_physics_calls': 0, 'new_calibration_calls': 0,
        'definitions': {'coordinates': 'Fixed independent calibration inputs only; fractional XY is affine to mm within each original pixel. No real-event positions or truth read.',
            'interpolation': 'Centre XY with linear Z versus bilinear XY plus linear Z (eight tensor-product corners). Training/validation coordinates are disjoint.',
            'signals': 'All34 native_signed_before_wiring keV; fixed500keV input, no per-channel/event gain adjustment. Errors are invariant under fixed X+1/Y-1 wiring.',
            'time_support': 'Original0..250ns FIT_GRID_NS,2ns spacing. Same existing post250ns plateau-activity check as reconstruction; unsupported records are excluded explicitly.',
            'normalization': 'Maximum per-channel time RMS divided by fixed500keV. This is forward approximation error, not a detector-resolution/confidence or acceptance threshold.',
            'denominators': 'All80 validation points retained; paired summaries require reference and both models available. Native/endpoint failure and support exclusions remain explicit.',
            'provenance': 'Exact checkpoint file SHA from completed capture, which verifies Julia payload SHA; Python does not recanonicalize Julia floating-point payloads.'}}
    W.write(output, report, fresh=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.results, args.request)
    print(json.dumps({k: result[k] for k in ('validation_count', 'paired_count', 'paired_metrics', 'elapsed_seconds')}, sort_keys=True))
