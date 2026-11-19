"""Measure fast-neighbor pileup on the nominal continuous GeGI ADC clock."""

import argparse
from collections import Counter
from itertools import product
import json
import math
from pathlib import Path
import platform

import numpy as np

import gegi_digital_readout as digital
import gegi_dual_source as dual
from gegi_exposure_stream import ADCExposure, reconstruct_exposure
import gegi_pulse_scan as scan
from gegi_substrip import load_calibration


DELAYS_NS = (0, 200, 300, 600, 800, 1000, 1200, 3000)
NOISE_MODES = ('none', 'nominal_a', 'nominal_b')
FIRST_ONSET_NS = 1000
LIVE_TIME_NS = FIRST_ONSET_NS + scan.WINDOW_END_NS
SOURCES = (*scan.SOURCES, 'gegi_dual_source.py', 'gegi_event_energy.py', 'gegi_imaging.py',
           'gegi_exposure_stream.py', 'gegi_fast_pileup_study.py')


def exposure(components, phase, seed):
    return ADCExposure(components, live_time_ns=LIVE_TIME_NS, phase_ns=phase, noise_seed=seed)


def observe(components, phase, seed, neighbors):
    result = reconstruct_exposure(exposure(components, phase, seed))
    cards = [dual._trigger_card(event, neighbors) for event in result['events']]
    return cards, result['adc_sha256']


def isolated_card(cards, anchor):
    index, = scan.match([anchor], cards)
    return cards[index] if len(cards) == 1 and index is not None else None


def isolated_features(card, expected_pair):
    if card and [*card['x_collecting_strips'], *card['y_collecting_strips']] == expected_pair:
        return card['single_pixel_features']
    return None


def compare_axis(paired, reference, noisy_energy, reference_energy):
    ratio = paired['fast_ratio']
    if ratio is None:
        neighbors = [paired[side] for side in ('low', 'high')]
        reasons = {flag for neighbor in neighbors if neighbor for flag in neighbor['flags']}
        if any(neighbor is None for neighbor in neighbors):
            reasons.add('missing_physical_neighbor')
        return {'status': 'paired_fast_unavailable', 'reasons': sorted(reasons)}
    if reference['fast_ratio'] is None:
        return {'status': 'isolated_fast_unavailable'}
    paired_fast = [paired[side]['fast_keV_equiv'] for side in ('low', 'high')]
    isolated_fast = [reference[side]['fast_keV_equiv'] for side in ('low', 'high')]
    paired_numerator = paired_fast[0] - paired_fast[1]
    isolated_numerator = isolated_fast[0] - isolated_fast[1]
    return {'status': 'compared', 'paired_fast_keV_equiv_low_high': paired_fast,
            'isolated_fast_keV_equiv_low_high': isolated_fast,
            'paired_ratio': ratio, 'isolated_ratio': reference['fast_ratio'],
            'paired_minus_isolated_ratio': ratio - reference['fast_ratio'],
            'fast_numerator_contribution': (paired_numerator - isolated_numerator) / reference_energy,
            'slow_denominator_contribution': paired_numerator * (1 / noisy_energy - 1 / reference_energy)}


def compare_pulse(card, reference, expected_pair):
    row = {'paired_trigger_ns': card['trigger_time_ns'], 'event_flags': card['flags'],
           'event_energy_flags': card['event_energy_flags'], 'axes': {},
           'paired_energy_keV': card['single_pixel_energy_keV'],
           'measured_contact_ids': [*card['x_collecting_strips'], *card['y_collecting_strips']]}
    if row['paired_energy_keV'] is None:
        return row | {'status': 'paired_single_pixel_energy_unavailable'}
    if row['measured_contact_ids'] != expected_pair:
        return row | {'status': 'different_collecting_pair'}
    paired = card['single_pixel_features']
    if paired is None:
        return row | {'status': 'paired_single_pixel_features_unavailable'}
    isolated = isolated_features(reference, expected_pair)
    if isolated is None:
        return row | {'status': 'isolated_single_pixel_features_unavailable'}
    row.update(status='compared_features', isolated_trigger_ns=reference['trigger_time_ns'],
               isolated_energy_keV=reference['single_pixel_energy_keV'])
    row['axes'] = {axis: compare_axis(paired[axis], isolated[axis], row['paired_energy_keV'],
                                     row['isolated_energy_keV']) for axis in 'xy'}
    return row


def compare_trial(cards, anchors, controls, expected_pairs, *, distinct_onsets):
    assignment = scan.match(anchors, cards)
    matched = sum(index is not None for index in assignment)
    if len(cards) == matched == 2 and distinct_onsets:
        status = 'two_distinct_triggers'
    elif len(cards) == matched == 2:
        status = 'coincident_pulses_with_multiple_triggers'
    elif len(cards) == matched == 1:
        status = 'one_trigger_for_two_pulses'
    elif len(cards) <= 1 and matched == 0:
        status = 'no_matched_triggers'
    else:
        status = 'unmatched_or_extra_triggers'
    pulses = [{'status': 'unresolved_triggers', 'axes': {}} for _ in expected_pairs]
    if status == 'two_distinct_triggers':
        pulses = [compare_pulse(cards[i], control, pair)
                  for i, control, pair in zip(assignment, controls, expected_pairs, strict=True)]
    return {'status': status, 'reconstructed_triggers': len(cards), 'matched_triggers': matched,
            'matched_event_indices': assignment, 'unmatched_triggers': len(cards) - matched,
            'observed_trigger_times_ns': [card['trigger_time_ns'] for card in cards], 'pulses': pulses}


def noise_variation(noisy, clean, expected_pair):
    measured, reference = [isolated_features(card, expected_pair) for card in (noisy, clean)]
    if measured is None or reference is None:
        return {}
    by_axis = {}
    for axis in 'xy':
        new, old = measured[axis]['fast_ratio'], reference[axis]['fast_ratio']
        if new is not None and old is not None:
            by_axis[axis] = new - old
    return by_axis


def metrics(values):
    data = np.abs(np.asarray(values, dtype=float))
    return {'n': len(data), 'rms': math.sqrt(np.mean(data**2)) if len(data) else None,
            'abs_p95': float(np.percentile(data, 95)) if len(data) else None,
            'max_abs': float(data.max()) if len(data) else None}


def summarize(trials, noise_by_energy):
    pulses = [pulse for trial in trials for pulse in trial['pulses']]
    axes = [(axis, result, pulse['preset_energy_keV']) for pulse in pulses for axis, result in pulse['axes'].items()]
    compared = [(axis, result, energy) for axis, result, energy in axes if result['status'] == 'compared']
    deltas = [(result['paired_minus_isolated_ratio'], energy) for _, result, energy in compared]
    return {'trials': len(trials), 'trial_status': Counter(t['status'] for t in trials),
            'pulse_status': Counter(p['status'] for p in pulses),
            'reconstructed_triggers': sum(t['reconstructed_triggers'] for t in trials),
            'matched_triggers': sum(t['matched_triggers'] for t in trials),
            'unmatched_triggers': sum(t['unmatched_triggers'] for t in trials),
            'axis_status': Counter(result['status'] for _, result, _ in axes),
            'axis_fast_unavailable_reasons': Counter(reason for _, result, _ in axes
                                                     for reason in result.get('reasons', [])),
            'axis_attempts': 2 * len(pulses), 'axes_blocked_upstream': 2 * len(pulses) - len(axes),
            'ratio_shift': metrics([delta for delta, _ in deltas]),
            'above_isolated_noise_abs_p95': sum(abs(delta) > noise_by_energy[energy]['abs_p95']
                                               for delta, energy in deltas),
            'above_3x_isolated_noise_abs_p95': sum(abs(delta) > 3 * noise_by_energy[energy]['abs_p95']
                                                  for delta, energy in deltas),
            'fast_numerator_contribution': metrics([r['fast_numerator_contribution'] for _, r, _ in compared]),
            'slow_denominator_contribution': metrics([r['slow_denominator_contribution'] for _, r, _ in compared])}


def run():
    implementations = {f'tools/{name}': scan.digest(scan.ROOT / 'tools' / name) for name in SOURCES}
    inputs = scan.Inputs()
    channels, identity, sources, pairs = scan.select(inputs, load_calibration())
    neighbors = dual._strip_neighbors(channels)
    trials, controls_by_key = [], {}

    def control(component_id, component, phase, energy, seed, anchor):
        key = (component_id, component[1], phase, energy, seed)
        if key not in controls_by_key:
            cards, digest = observe([component], phase, seed, neighbors)
            card = isolated_card(cards, anchor)
            controls_by_key[key] = {'component_id': component_id, 'onset_ns': component[1],
                                    'adc_phase_ns': phase, 'energy_keV': energy, 'noise_seed': seed,
                                    'control_index': len(controls_by_key), 'trigger_count': len(cards),
                                    'adc_sha256': digest, 'card': card}
        return controls_by_key[key]

    for pair, phase, energies, delay in product(pairs, scan.PHASES_NS, scan.ENERGIES_KEV, DELAYS_NS):
        ids = pair['components']
        native = [sources[c] for c in ids]
        expected_pairs = [source['contact_ids'] for source in native]
        onsets = (FIRST_ONSET_NS, FIRST_ONSET_NS + delay)
        components = [(source['native'], onset, energy / source['native_energy_keV'])
                      for source, onset, energy in zip(native, onsets, energies, strict=True)]
        clean = [control(c, component, phase, energy, None, onset)
                 for c, component, energy, onset in zip(ids, components, energies, onsets, strict=True)]
        anchors = [row['card']['trigger_time_ns'] if row['card'] else onset
                   for row, onset in zip(clean, onsets, strict=True)]
        for mode in NOISE_MODES:
            seed = (None if mode == 'none' else scan.noise_seed('nominal', 'matched_fast_pileup',
                                                              mode, pair['pair_id'], phase, *energies))
            controls = clean if seed is None else [control(c, component, phase, energy, seed, anchor)
                                                  for c, component, energy, anchor in
                                                  zip(ids, components, energies, anchors, strict=True)]
            cards, digest = observe(components, phase, seed, neighbors)
            trial = compare_trial(cards, anchors, [row['card'] for row in controls], expected_pairs,
                                  distinct_onsets=delay > 0)
            for pulse, c, e, measured, baseline in zip(trial['pulses'], ids, energies, controls, clean, strict=True):
                pulse.update(component_id=c, preset_energy_keV=e, isolated_control_index=measured['control_index'])
                if seed is not None:
                    measured['noise_only_ratio_variation'] = noise_variation(
                        measured['card'], baseline['card'], sources[c]['contact_ids'])
            trials.append(trial | {'pair_id': pair['pair_id'], 'topology': pair['topology'],
                                   'noise_mode': mode, 'noise_seed': seed, 'phase_ns': phase,
                                   'delay_ns': delay, 'anchor_times_ns': anchors, 'adc_sha256': digest})

    controls = list(controls_by_key.values())
    noise_by_energy = {energy: metrics([delta for row in controls if row['energy_keV'] == energy
                                       for delta in row.get('noise_only_ratio_variation', {}).values()])
                       for energy in sorted({e for pair in scan.ENERGIES_KEV for e in pair})}
    if any(not values['n'] for values in noise_by_energy.values()):
        raise ValueError('Matched isolated controls must measure nominal noise for both tested energies')
    if implementations != {ref: scan.digest(scan.ROOT / ref) for ref in implementations}:
        raise RuntimeError('Fast pileup study source changed during replay')
    by_group = []
    for condition, topology, delay in product(('noiseless', 'nominal'), scan.TOPOLOGIES, DELAYS_NS):
        group = [t for t in trials if t['topology'] == topology and t['delay_ns'] == delay
                 and (t['noise_mode'] == 'none') == (condition == 'noiseless')]
        by_group.append({'condition': condition, 'topology': topology, 'delay_ns': delay,
                         **summarize(group, noise_by_energy)})
    return {
        'kind': 'gegi_saved_fast_pileup_study_v1',
        'design': {'delays_ns': DELAYS_NS, 'adc_phases_ns': scan.PHASES_NS, 'adc_sample_period_ns': digital._DT,
                   'ordered_energies_keV': scan.ENERGIES_KEV, 'first_onset_ns': FIRST_ONSET_NS,
                   'live_time_ns': LIVE_TIME_NS, 'nominal_noise_rms_v': digital._PROFILE['optional_noise_rms_V'],
                   'noise_base_seed': scan.NOISE_BASE_SEED, 'noise_modes': NOISE_MODES,
                   'control': 'Pair and two isolated pulses use the same absolute onsets, ADC grid, reset, '
                              'one quantization and identical per-channel noise timeline when seeded.',
                   'matching': 'Match distinct chronological trigger times to phase-matched noiseless isolated '
                               'triggers within the existing 60 ns tolerance. The pilot requires exactly two '
                               'matches, distinct input onsets and no extra trigger for per-pulse claims. Pixel and energy do not '
                               'enter matching. Deposit identities are used only to score this simulation.',
                   'feature': 'Use the continuous acquisition single-pixel fast ratio. Subtract the higher '
                              'coordinate neighbor reading from the lower in signed keV-equivalent and divide '
                              'by measured single-pixel slow energy in keV. A comparison requires the same '
                              'qualified collecting pair and both neighbor signals in the two windows.',
                   'noise_reference': 'Descriptive pooled 95th percentile absolute seeded-minus-noiseless '
                                      'isolated ratio shift by preset energy. This is a comparison scale '
                                      'for the fixed sample, not a qualification threshold.',
                   'scope': 'Six saved point-injection pairs on one model and simulated field. Different '
                            'delays, phases and seeds reuse those pulses. No position conversion or hardware claim.'},
        'provenance': {**identity, 'source_sha256': implementations, 'input_sha256': inputs.hashes,
                       'profile_sha256': digital.PROFILE_SHA256, 'timing_sha256': digital.TIMING_SHA256,
                       'python': platform.python_version(), 'numpy': np.__version__},
        'counts': {'native_pulses': len(sources), 'pulse_pairs': len(pairs), 'paired_trials': len(trials),
                   'isolated_controls': len(controls), 'new_transport_calls': 0, 'new_drift_calls': 0,
                   'new_field_solves': 0},
        'isolated_noise_variation_by_energy_keV': noise_by_energy,
        'summary': {condition: summarize([t for t in trials if (t['noise_mode'] == 'none') ==
                                          (condition == 'noiseless')], noise_by_energy)
                    for condition in ('noiseless', 'nominal')},
        'by_delay_and_topology': by_group, 'trials': trials, 'isolated_controls': controls,
        'components': {name: {k: v for k, v in source.items() if k != 'native'}
                       for name, source in sources.items()},
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
    print(json.dumps({'counts': result['counts'], 'summary': result['summary']}, indent=2))


if __name__ == '__main__':
    main()
