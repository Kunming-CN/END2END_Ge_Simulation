"""Compare measured-trigger and injection-onset fast gates on saved GeGI pulses."""

import argparse
import json
import math
from pathlib import Path
import platform

import numpy as np

import gegi_digital_readout as digital
import gegi_dual_source as dual
from gegi_event_store import sha
import gegi_pulse_scan as scan
import gegi_pulse_stream as stream
from gegi_substrip import load_calibration


PHASES_NS = (0, 5, 10, 15)
ONSET_NS = 1000
INJECTION_KEV = 250
GATE_STEPS = stream._FAST_NS // digital._DT
SOURCES = (*scan.SOURCES, 'gegi_dual_source.py', 'gegi_event_energy.py',
           'gegi_imaging.py', 'gegi_fast_gate_study.py')


def onset_sample(time_ns, onset_ns):
    """Choose the first ADC sample at or after the scheduled injection time."""
    return int(np.searchsorted(time_ns, onset_ns, side='left'))


def gate_areas(fast, trigger_index, onset_index):
    """Integrate both placements with the exact same trigger-baseline samples."""
    baseline_start = trigger_index + 1 - stream._QUIET_SAMPLES
    if min(baseline_start, onset_index) < 0 or max(trigger_index, onset_index) + GATE_STEPS >= fast.shape[-1]:
        raise ValueError('Both fast windows require the complete grid and trigger baseline')
    baseline = fast[..., baseline_start:trigger_index + 1].mean(axis=-1, keepdims=True)
    areas = []
    for start in (trigger_index, onset_index):
        samples = fast[..., start:start + GATE_STEPS + 1] - baseline
        areas.append((samples[..., :-1] + samples[..., 1:]).sum(axis=-1) * (digital._DT / 2))
    return areas


def evaluate_pulse(prepared, scale, expected_pair, neighbors, phase_ns):
    time, adc = stream.acquire([(prepared, ONSET_NS, scale)], phase_ns=phase_ns,
                               window_end_ns=scan.WINDOW_END_NS)
    observed = stream.reconstruct(time, adc)
    events = observed['events']
    row = {'adc_phase_ns': phase_ns, 'trigger_count': len(events), 'axes': {},
           'adc_int16_le_sha256': sha(adc.astype('<i2').tobytes()),
           'saturated_contact_ids': observed['saturated_contact_ids']}
    if len(events) != 1:
        return row | {'status': 'expected_one_trigger'}
    trigger = events[0]
    trigger_time = trigger['trigger_time_ns']
    trigger_index = int(np.searchsorted(time, trigger_time))
    onset_index = onset_sample(time, ONSET_NS)
    row.update(trigger_time_ns=trigger_time,
               trigger_minus_injection_ns=trigger_time - ONSET_NS,
               onset_grid_time_ns=float(time[onset_index]),
               trigger_minus_onset_grid_ns=float(trigger_time - time[onset_index]),
               measured_contact_ids=trigger['contact_ids'])
    if row['saturated_contact_ids']:
        return row | {'status': 'saturated_adc'}
    if trigger['contact_ids'] != list(expected_pair):
        return row | {'status': 'unexpected_collecting_pair'}
    card = dual._trigger_card(trigger, neighbors)
    features = card['single_pixel_features']
    if features is None:
        return row | {'status': 'unqualified_single_pixel_energy', 'flags': card['event_energy_flags']}

    energy = card['single_pixel_energy_keV']
    row['single_pixel_energy_keV'] = energy
    row['shared_baseline_grid_times_ns'] = time[trigger_index + 1 - stream._QUIET_SAMPLES:trigger_index + 1].tolist()
    rows = {channel['contact_id']: channel for channel in trigger['channels']}
    for axis, measured in features.items():
        if measured['fast_ratio'] is None:
            row['axes'][axis] = {'status': 'unqualified_trigger_fast_ratio'}
            continue
        lo, hi = (measured[side]['contact_id'] for side in ('low', 'high'))
        channel_ids = (lo, hi)
        fast = np.array([digital._filters(adc[cid - 1] * digital._LSB_V)[2] for cid in channel_ids])
        trigger_areas, onset_areas = gate_areas(fast, trigger_index, onset_index)
        for cid, area in zip(channel_ids, trigger_areas, strict=True):
            if not math.isclose(area, rows[cid]['fast_area_V_ns'], rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f'Trigger gate disagrees with production fast area for contact {cid}')
        onset_fast = onset_areas / stream._FAST_GAIN
        onset_ratio = float((onset_fast[0] - onset_fast[1]) / energy)
        row['axes'][axis] = {'status': 'compared', 'collector_contact_id': measured['contact_id'],
                            'neighbor_contact_ids_low_high': channel_ids,
                            'trigger_fast_keV_equiv_low_high': [measured[s]['fast_keV_equiv'] for s in ('low', 'high')],
                            'onset_fast_keV_equiv_low_high': onset_fast.tolist(),
                            'trigger_ratio': measured['fast_ratio'], 'onset_ratio': onset_ratio,
                            'trigger_minus_onset_ratio': measured['fast_ratio'] - onset_ratio}
    return row | {'status': 'measured'}


def statistics(values):
    return {'n': len(values), 'min': min(values, default=None), 'max': max(values, default=None),
            'rms': math.sqrt(math.fsum(v * v for v in values) / len(values)) if values else None,
            'max_abs': max(map(abs, values), default=None)}


def run():
    source_hashes = {f'tools/{name}': scan.digest(scan.ROOT / 'tools' / name) for name in SOURCES}
    inputs = scan.Inputs()
    calibration = load_calibration()
    channels, identity, sources, _ = scan.select(inputs, calibration)
    neighbors = dual._strip_neighbors(channels)
    rows = []
    for component_id, source in sources.items():
        scale = INJECTION_KEV / source['native_energy_keV']
        for phase in PHASES_NS:
            rows.append({'component_id': component_id} | evaluate_pulse(
                source['native'], scale, source['contact_ids'], neighbors, phase))
    compared = [(row, axis, result['trigger_minus_onset_ratio']) for row in rows
                for axis, result in row['axes'].items() if result['status'] == 'compared']
    measured_rows = [row for row in rows if 'trigger_minus_injection_ns' in row]
    if source_hashes != {ref: scan.digest(scan.ROOT / ref) for ref in source_hashes}:
        raise RuntimeError('Fast gate study source changed during replay')
    return {
        'kind': 'gegi_saved_fast_gate_reference_study_v1',
        'counts': {'unique_saved_pulses': len(sources), 'isolated_adc_windows': len(rows),
                   'measured_triggers': sum(row['trigger_count'] for row in rows),
                   'pulses_with_comparison': len({row['component_id'] for row, _, _ in compared}),
                   'triggers_with_comparison': sum(any(a['status'] == 'compared' for a in row['axes'].values())
                                                   for row in rows),
                   'axis_comparisons': len(compared), 'axis_attempts': 2 * len(rows),
                   'new_transport_calls': 0, 'new_field_solves': 0, 'new_drift_calls': 0},
        'design': {
            'adc_sample_period_ns': digital._DT, 'adc_phases_ns': PHASES_NS, 'noise_rms_V': 0,
            'injection_time_ns': ONSET_NS, 'linearly_scaled_injection_energy_keV': INJECTION_KEV,
            'adc_window_end_ns': scan.WINDOW_END_NS,
            'pulse_selection': 'The 12 verified, distinct interior point injections from the double-pulse scan.',
            'comparison': 'Both gates use identical ADC codes, the nominal fast filter and its signed fixed '
                          'pulser gain. The same three fast samples ending at the measured trigger set both '
                          'baselines. Only the integration window moves.',
            'injection_reference': 'First sample at or after injection. Grid offsets are 0, 5, 10 and 15 ns. '
                                   'This reference is available only in this simulation control.',
            'gate': f'Integrate from reference to reference + {stream._FAST_NS} ns. Include both endpoints at '
                    'half trapezoid weight and give internal samples full weight.',
            'ratio': '(lower-coordinate neighbor fast keV-equivalent − higher-coordinate neighbor fast '
                     'keV-equivalent) / measured single-pixel slow energy in keV. Both gates use the same '
                     'denominator, the mean of the qualified X and Y collecting-strip slow energies.',
            'scope': 'The phase cases repeat the same saved pulses. RMS is descriptive for this fixed '
                     'noiseless simulation sample. No position conversion is applied.',
        },
        'provenance': {**identity, 'digital_profile_sha256': digital.PROFILE_SHA256,
                       'digital_timing_sha256': digital.TIMING_SHA256, 'source_sha256': source_hashes,
                       'input_sha256': inputs.hashes, 'python': platform.python_version(), 'numpy': np.__version__},
        'summary': {'trigger_minus_injection_ns': statistics([r['trigger_minus_injection_ns'] for r in measured_rows]),
                    'trigger_minus_onset_grid_ns': statistics([r['trigger_minus_onset_grid_ns'] for r in measured_rows]),
                    'ratio_shift_both_axes': statistics([delta for _, _, delta in compared]),
                    'ratio_shift_by_axis': {a: statistics([d for _, axis, d in compared if a == axis]) for a in 'xy'},
                    'ratio_shift_by_phase_ns': {p: statistics([d for r, _, d in compared if r['adc_phase_ns'] == p])
                                                for p in PHASES_NS}},
        'components': {name: {k: v for k, v in source.items() if k != 'native'}
                       for name, source in sources.items()},
        'isolated_windows': rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = run()
    payload = json.dumps(result, allow_nan=False, separators=(',', ':')) + '\n'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        output.write(payload)
    print(json.dumps({'counts': result['counts'], 'summary': result['summary']}, indent=2))


if __name__ == '__main__':
    main()
