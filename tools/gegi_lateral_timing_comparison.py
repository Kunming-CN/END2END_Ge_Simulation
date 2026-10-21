"""Saved full34 forward candidate using one carrier-landmark time warp per corner."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import time
import numpy as np
import gegi_lateral_forward_comparison as L
import gegi_signal_reconstruction as R

ROOT = Path(__file__).resolve().parents[1]
COMPARISON_SHA256 = '62cf4f28b082a4f4cba8188b3fadb439220b81539b67e752da84f7cab21ad97e'


class UnsupportedWarp(ValueError):
    pass


def arrivals(row, dt_ns):
    endpoints = row.get('endpoints')
    if endpoints is None or len(endpoints) != 2 or {e['species'] for e in endpoints} != {'electron', 'hole'}:
        raise UnsupportedWarp('carrier_endpoints_unavailable')
    if any(e['step_limit_reached'] or e['status'] != 'contact' for e in endpoints):
        raise UnsupportedWarp('carrier_contact_incomplete')
    return {e['species']: (e['samples']-1)*dt_ns for e in endpoints}


def knots(times):
    electron, hole = times['electron'], times['hole']
    if electron == hole:
        raise UnsupportedWarp('equal_carrier_arrivals')
    result = np.asarray([0., min(electron, hole), max(electron, hole), 250.])
    if not np.isfinite(result).all() or not np.all(np.diff(result) > 0):
        raise UnsupportedWarp('nonincreasing_or_outside_window_knots')
    return result


def mapped_times(target, corner, grid):
    target_knots = knots(target); corner_knots = knots(corner)
    if (target['electron'] < target['hole']) != (corner['electron'] < corner['hole']):
        raise UnsupportedWarp('carrier_order_flips')
    return np.interp(grid, target_knots, corner_knots)


def predict(corners, weights, dt_ns, grid=R.FIT_GRID_NS):
    """Only training rows enter prediction; a shared warp acts on all34 channels."""
    if len(corners) != len(weights) or not len(corners) or any(w <= 0 for w in weights) or sum(weights) != 1:
        raise ValueError('Positive frozen spatial weights must sum to one')
    times = [arrivals(row, dt_ns) for row in corners]
    for item in times:
        knots(item)
    if len({t['electron'] < t['hole'] for t in times}) != 1:
        raise UnsupportedWarp('carrier_order_flips')
    target = {species: sum(w*t[species] for w, t in zip(weights, times)) for species in ('electron', 'hole')}
    target_knots = knots(target); prediction = np.zeros((34, len(grid)))
    terminal = np.zeros(34)
    for row, weight, corner in zip(corners, weights, times):
        query = mapped_times(target, corner, grid)  # Same vector for every channel.
        if row['signal_coverage'] != R.ALL34_COVERAGE or [s['contact_id'] for s in row['channel_signals']] != R.ALL34_IDS:
            raise ValueError('Original native signed34-channel coverage required')
        for index, signal in enumerate(row['channel_signals']):
            t, q = R._wave(signal)
            prediction[index] += weight*np.interp(query, t, q, left=0, right=q[-1])
            terminal[index] += weight*q[-1]
    return prediction, {'predicted_arrivals_ns': target, 'target_knots_ns': target_knots.tolist(),
        'corner_arrivals_ns': times, 'carrier_order': 'electron_first' if target['electron'] < target['hole'] else 'hole_first'}, terminal


def compact_metrics(metrics, pixel):
    result = {k: metrics[k] for k in ('max_channel_rms_keV', 'max_channel_normalized_rms', 'max_absolute_error_keV')}
    for kind, channels in (('collecting', [c for c in metrics['channels'] if c['contact_id'] in pixel]),
                           ('neighbor', [c for c in metrics['channels'] if c['contact_id'] not in pixel])):
        result[kind+'_max_rms_keV'] = max(c['rms_error_keV'] for c in channels)
        result[kind+'_max_absolute_error_keV'] = max(c['max_absolute_error_keV'] for c in channels)
    return result


def summary(rows):
    paired = [r for r in rows if r['status'] == 'compared']; metrics = {}
    for key in ('max_channel_rms_keV', 'max_channel_normalized_rms', 'max_absolute_error_keV',
                'collecting_max_rms_keV', 'neighbor_max_rms_keV', 'collecting_max_absolute_error_keV', 'neighbor_max_absolute_error_keV'):
        metrics[key] = {mode: L.describe([r['metrics'][mode][key] for r in paired]) for mode in ('centre', 'trilinear', 'timewarp')}
        for mode in ('centre', 'trilinear'):
            metrics[key]['versus_'+mode] = {direction: sum(compare(r['metrics']['timewarp'][key], r['metrics'][mode][key]) for r in paired)
                for direction, compare in (('improved', lambda a, b: a < b), ('worse', lambda a, b: a > b), ('tied', lambda a, b: a == b))}
    return {'total': len(rows), 'paired': len(paired), 'unsupported_reasons': dict(Counter(r['reason'] for r in rows if r['status'] != 'compared')),
        'paired_metrics': metrics, 'absolute_arrival_errors_ns': {species: L.describe([abs(r['posthoc_arrival_errors_ns'][species]) for r in paired]) for species in ('electron', 'hole')}}


def compare(results):
    started = time.perf_counter(); results = Path(results).resolve(); output = results/'timing-comparison.json'
    if output.exists():
        raise FileExistsError(output)
    reportpath = results/'forward-comparison.json'; report_raw = reportpath.read_bytes(); report = json.loads(report_raw)
    if R._sha(report_raw) != COMPARISON_SHA256:
        raise ValueError('Use the fixed completed80-point forward comparison')
    sources = {ref: L.W.sha(ROOT/ref) for ref in (*report['source_sha256'], 'tools/gegi_lateral_timing_comparison.py',
        'simulation/gegi_response.jl', 'simulation/run.jl')}
    if any(sources[ref] != digest for ref, digest in report['source_sha256'].items()):
        raise ValueError('Original comparison helpers changed')
    needed = {str((results/r['reference_record_ref']).resolve()) for r in report['records']}
    needed.update(str((results/w['record_ref']).resolve()) for r in report['records'] for mode in ('centre', 'trilinear') for w in r[mode].get('training_weights', []))
    raw_records = {}; bindings = {str(reportpath): R._sha(report_raw)}; complete = None; identity = None
    # Verify the already admitted report's exact input seals once, retaining only
    # needed checkpoint bytes. No second schema/admission framework or native run.
    for ref, expected in report['input_sha256'].items():
        path = Path(ref).resolve(); raw = path.read_bytes()
        if R._sha(raw) != expected:
            raise ValueError('Sealed comparison input changed: '+ref)
        bindings[str(path)] = expected
        if str(path) in needed:
            raw_records[str(path)] = raw
        if path == results/'COMPLETE.json':
            complete = json.loads(raw)
        if path == results/'identity.json':
            identity = json.loads(raw)
    if complete is None or identity is None or len(report['records']) != 80:
        raise ValueError('Completed fixed80 comparison required')
    for ref in ('simulation/gegi_response.jl', 'simulation/run.jl'):
        if sources[ref] != complete['source_file_sha256'][ref]:
            raise ValueError('Native timing producer changed')
    dt = identity['numerics']['dt']
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError('Positive native dt in ns required')
    cache = {}

    def load(ref):
        path = str((results/ref).resolve())
        if path not in cache:
            row = json.loads(raw_records.pop(path))['payload']
            values, support = L.waveform(row)
            cache[path] = (row, values, support)
        return cache[path]

    rows = []
    for original in report['records']:
        pixel = original['contact_ids']; row = {'reference_record_ref': original['reference_record_ref'], 'contact_ids': pixel,
            'position_mm': original['position_mm'], 'lateral_offset_pitch_fraction': original['lateral_offset_pitch_fraction']}
        reference, values, support = load(original['reference_record_ref'])
        if values is None or any(original[mode]['status'] != 'compared' for mode in ('centre', 'trilinear')):
            row.update(status='unsupported', reason='original_reference_or_comparison_unavailable', reference_support=support)
            rows.append(row); continue
        weights = original['trilinear']['training_weights']; training = [load(w['record_ref']) for w in weights]
        if any(item[1] is None for item in training):
            row.update(status='unsupported', reason='training_corner_unavailable'); rows.append(row); continue
        try:
            prediction, landmarks, terminal = predict([item[0] for item in training], [w['weight'] for w in weights], dt)
        except UnsupportedWarp as error:
            row.update(status='unsupported', reason=str(error)); rows.append(row); continue
        metrics = L.error_metrics(prediction, values); delta = prediction-values
        index, sample = np.unravel_index(int(np.argmax(np.abs(delta))), delta.shape)
        # Validation endpoints enter ONLY after the waveform prediction exists.
        actual_arrivals = arrivals(reference, dt)
        actual_terminal = np.asarray([s['signed_induced_keV'][-1] for s in reference['channel_signals']])
        row.update(status='compared', landmarks=landmarks, training_weights=weights,
            posthoc_actual_arrivals_ns=actual_arrivals,
            posthoc_arrival_errors_ns={species: landmarks['predicted_arrivals_ns'][species]-actual_arrivals[species] for species in ('electron', 'hole')},
            metrics={mode: compact_metrics(original[mode], pixel) for mode in ('centre', 'trilinear')},
            timewarp_channel_errors=metrics['channels'], max_absolute_terminal_error_keV=float(np.max(np.abs(terminal-actual_terminal))),
            max_absolute_250ns_error_keV=float(np.max(np.abs(delta[:, -1]))),
            peak={'contact_id': int(index)+1, 'kind': 'collecting' if int(index)+1 in pixel else 'neighbor',
                  'time_ns': float(R.FIT_GRID_NS[sample]), 'native_signed_error_keV': float(delta[index, sample])})
        row['metrics']['timewarp'] = compact_metrics(metrics, pixel); rows.append(row)
    for ref, digest in sources.items():
        if L.W.sha(ROOT/ref) != digest:
            raise ValueError('Comparison source changed during evaluation')
    result = {'kind': 'gegi_saved_common_carrier_timewarp_candidate_v1', 'source_sha256': sources, 'input_sha256': bindings,
        'original_comparison_paired_count': report['paired_count'], 'original_comparison_metrics': report['paired_metrics'],
        'summary': summary(rows), 'by_z': {str(z): summary([r for r in rows if r['position_mm'][2] == z]) for z in L.VALIDATION_AXES[2]},
        'records': rows, 'elapsed_seconds': time.perf_counter()-started, 'new_fit_calls': 0, 'new_physics_calls': 0, 'new_calibration_calls': 0,
        'definitions': {'candidate': 'Common all34-channel piecewise linear time warp per training corner, then unchanged spatial weighted sum; not physically exact while both carriers move.',
            'landmarks': 'Only training endpoint.samples and native dt predict electron/hole arrivals: (samples-1)*dt ns. Same carrier order required on every contributing corner. Target [0,early,late,250] maps to each corner knots.',
            'native_time_basis': 'Pinned G.native_deposit uses exact0:(length-1)*cfg.dt; Q.endpoint_report records path length. Root verified all476 waveform endpoints equal max carrier arrival; no new global census.',
            'signals': 'All34 native signed waveforms at mapped times; one shared query vector per corner, no channel-specific alignment or amplitude/gain correction. Fixed500keV independent injections.',
            'evaluation': 'Same80 independent calibration points, centre/trilinear frozen results retained. All/collecting/neighbor paired stats use the same supported subset; exclusions remain explicit. Validation endpoints only evaluate arrival error after prediction.',
            'scope': 'Saved-data forward candidate only; no real events, inverse search, new drift, field solve or production changes.'}}
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, sort_keys=True, separators=(',', ':'), allow_nan=False); stream.write('\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--results', type=Path, required=True)
    result = compare(parser.parse_args().results)
    print(json.dumps({'summary': result['summary'], 'elapsed_seconds': result['elapsed_seconds']}, sort_keys=True))
