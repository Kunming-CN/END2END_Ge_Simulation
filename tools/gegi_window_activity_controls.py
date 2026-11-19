"""Check the saved GeGI ADC activity diagnostic on 24 bound pulse mixtures."""

import argparse
from itertools import product
import json
from pathlib import Path

import numpy as np

import gegi_digital_readout as digital
import gegi_dual_source as dual
import gegi_fast_pileup_study as pileup
import gegi_pulse_scan as scan
from gegi_exposure_stream import reconstruct_exposure
from gegi_pool_measured_planes import digest, require
from gegi_substrip import load_calibration
from gegi_trigger_windows import RELATIVE_NS, capture, capture_context, is_two_strip
from gegi_window_activity import analyze_window


PARENT = scan.ROOT/'.local/gegi-fast-pileup/study.json'
PARENT_SHA = '742b5263a9e7c1599b7f9e299c4c59bb8ece3d5564d7b187548c8cad17028118'
DELAYS = (0, 200, 300, 600)
PHASES = (0, 10)
ENERGIES = (250, 250)
NOISE_MODE = pileup.NOISE_MODES[1]
PROFILE = 'standard'


def observe(components, phase, seed, channels, neighbors):
    exposure = pileup.exposure(components, phase, seed)
    first_window = {}

    def record_first(event, offset, codes):
        if not first_window:
            t = event['trigger_time_ns']
            state, window = capture_context(exposure, t, [], offset, codes)
            first_window.update(time_ns=t, status=state, codes=window)

    result = reconstruct_exposure(exposure, trigger_profile=PROFILE, on_trigger=record_first)
    cards = [dual._trigger_card(event, neighbors, geometry=channels) for event in result['events']]
    if cards:
        require(first_window['time_ns'] == cards[0]['trigger_time_ns'], 'ADC window must use the first recorded trigger')
    return cards, first_window, result['acquisition_baseline_v'], result['adc_sha256']


def isolated_activity(component, phase, seed, reference, parent):
    window = capture(pileup.exposure([component], phase, seed), [reference], [])
    require(window['known_component_adc_sha256'] == parent['adc_sha256'],
            f'Original matched single-pulse ADC digest differs at control {parent["control_index"]}')
    require(window['window_status'][0] == 'captured' and parent['trigger_count'] == 1 and parent['card'],
            'This bound isolated control needs a single recorded trigger and complete ADC')
    require(parent['card']['trigger_time_ns']-reference in RELATIVE_NS,
            'The isolated control trigger is outside the aligned ADC window')
    baseline = window['acquisition_baseline_v']
    activity = analyze_window(window['adc_codes'][0], baseline, RELATIVE_NS, PROFILE)
    require(any(g['coincident'] and g['trigger_reference_ns'] == parent['card']['trigger_time_ns']-reference
                for g in activity['groups']), 'Aligned isolated window does not reproduce the isolated trigger')
    return activity, baseline


def evaluate(trial, sources, parent_controls, channels, neighbors, isolated_cache):
    delay, phase, seed = (trial[key] for key in ('delay_ns', 'phase_ns', 'noise_seed'))
    onsets = (pileup.FIRST_ONSET_NS, pileup.FIRST_ONSET_NS+delay)
    components = [(source['native'], onset, energy/source['native_energy_keV'])
                  for source, onset, energy in zip(sources, onsets, ENERGIES, strict=True)]
    cards, window, baseline, adc_sha = observe(components, phase, seed, channels, neighbors)
    trigger_times = [card['trigger_time_ns'] for card in cards]
    require((adc_sha, len(cards), trigger_times) ==
            (trial['adc_sha256'], trial['reconstructed_triggers'], trial['observed_trigger_times_ns']),
            'Recreated ADC digest or full-clock trigger census differs from original matched trial')
    cards = [{key: card[key] for key in ('trigger_time_ns', 'rise_end_ns', 'energy_keV', 'x_collecting_strips',
                                        'y_collecting_strips', 'event_energy_flags')} |
             {'would_capture_two_strip': is_two_strip(card)} for card in cards]
    state = window['status'] if cards else 'no_recorded_trigger'
    t = trigger_times[0] if cards else None
    second_offset = onsets[1]-t if cards else None
    second_within = int(RELATIVE_NS[0]) <= second_offset <= int(RELATIVE_NS[-1]) if cards else None
    row = {key: trial[key] for key in ('pair_id', 'topology', 'phase_ns', 'noise_mode', 'noise_seed', 'delay_ns')}
    control_indices = [pulse['isolated_control_index'] for pulse in trial['pulses']]
    row.update(
        input_onsets_ns=onsets, second_input_onset_offset_ns=second_offset, second_input_onset_inside_adc=second_within,
        adc_sha256=adc_sha, original_trial_status=trial['status'], full_clock_recorded_triggers=cards,
        full_clock_trigger_count=len(cards), first_trigger_would_capture_two_strip=cards[0]['would_capture_two_strip'] if cards else None,
        window_status=state, first_recorded_trigger_ns=t, secondary_rearmed_coincident_rise=None, activity_groups=None,
        original_isolated_control_indices=control_indices, aligned_first_input_only=None,
    )
    if state != 'captured':
        return row, None
    codes = window['codes']
    activity = analyze_window(codes, baseline, RELATIVE_NS, PROFILE)
    groups = activity['groups']
    primary = next((g for g in groups if g['coincident'] and g['rearm_visible'] and g['trigger_reference_ns'] == 0.), None)
    row['activity_groups'] = groups
    row['primary_reference_reproduced'] = primary is not None
    if primary is not None and not activity['saturated_contact_ids']:
        row['secondary_rearmed_coincident_rise'] = any(g is not primary and g['coincident'] and g['rearm_visible']
                                                     for g in groups)
    first_control = parent_controls[control_indices[0]]
    require((first_control['control_index'], first_control['noise_seed'], first_control['adc_phase_ns'],
             first_control['onset_ns'], first_control['energy_keV']) == (control_indices[0], seed, phase, onsets[0], ENERGIES[0]),
            'First-input comparison must use the original isolated ADC controls')
    cache_key = (control_indices[0], t)
    if cache_key not in isolated_cache:
        isolated_cache[cache_key] = isolated_activity(components[0], phase, seed, t, first_control)
    isolated, isolated_baseline = isolated_cache[cache_key]
    require(np.array_equal(baseline, isolated_baseline), 'Pulse mixture and isolated comparison must use the same preamble')
    row['aligned_first_input_only'] = dict(
        original_control_index=control_indices[0], adc_sha256=first_control['adc_sha256'],
        activity_groups=isolated['groups'],
        maximum_absolute_face_increment_difference_keV={
            axis: float(np.max(np.abs(np.subtract(activity[f'{axis}_change_keV'], isolated[f'{axis}_change_keV']))))
            for axis in ('x', 'y')})
    trace = dict(
        trial=row, relative_time_ns=RELATIVE_NS.tolist(), contact_ids=list(digital.CONTACT_IDS),
        volts_per_code=digital._LSB_V, acquisition_baseline_v=baseline.tolist(), adc_codes=codes.tolist(),
        activity=activity, aligned_first_input_only_activity=isolated,
    )
    return row, trace


def counts(rows):
    return dict(
        mixtures=len(rows), captured_windows=sum(r['window_status'] == 'captured' for r in rows),
        evaluated_windows=sum(r['secondary_rearmed_coincident_rise'] is not None for r in rows),
        second_input_onset_inside_adc=sum(r['second_input_onset_inside_adc'] is True for r in rows),
        secondary_rearmed_coincident_rise=sum(r['secondary_rearmed_coincident_rise'] is True for r in rows),
        full_clock_two_recorded_triggers=sum(r['full_clock_trigger_count'] == 2 for r in rows),
        first_trigger_would_capture_two_strip=sum(r['first_trigger_would_capture_two_strip'] is True for r in rows),
    )


def study():
    original_bytes = PARENT.read_bytes()
    require(digest(original_bytes) == PARENT_SHA, 'Saved matched-pileup grid changed')
    parent = json.loads(original_bytes)
    original_design = parent['design']
    require(parent['kind'] == 'gegi_saved_fast_pileup_study_v1' and original_design['noise_modes'][1] == NOISE_MODE
            and tuple(original_design['adc_phases_ns']) == PHASES and list(ENERGIES) in original_design['ordered_energies_keV']
            and set(DELAYS) <= set(original_design['delays_ns']) and original_design['live_time_ns'] == pileup.LIVE_TIME_NS
            and original_design['first_onset_ns'] == pileup.FIRST_ONSET_NS
            and parent['provenance']['profile_sha256'] == digital.PROFILE_SHA256
            and parent['provenance']['timing_sha256'] == digital.TIMING_SHA256, 'Unexpected original matched-pileup design')
    inputs = scan.Inputs()
    channels, identity, sources, pairs = scan.select(inputs, load_calibration())
    require(inputs.hashes == parent['provenance']['input_sha256'] and
            all(parent['provenance'][key] == value for key, value in identity.items()),
            'Original native scan or field provenance differs')
    neighbors = dual._strip_neighbors(channels)
    first_pairs = [next(p for p in pairs if p['topology'] == topology) for topology in scan.TOPOLOGIES]
    original = {(t['pair_id'], t['phase_ns'], t['delay_ns']): t for t in parent['trials'] if
                t['noise_mode'] == NOISE_MODE and tuple(p['preset_energy_keV'] for p in t['pulses']) == ENERGIES}
    rows, examples, isolated_cache = [], {}, {}
    for pair, phase, delay in product(first_pairs, PHASES, DELAYS):
        pair_id = pair['pair_id']
        source_ids = pair['components']
        trial = original[pair_id, phase, delay]
        require([p['component_id'] for p in trial['pulses']] == source_ids and
                all(scan.digest(scan.ROOT/sources[key]['record_ref']) == parent['components'][key]['record_sha256']
                    for key in source_ids), 'Original matched-pileup component identities differ')
        result, trace = evaluate(trial, [sources[key] for key in source_ids], parent['isolated_controls'],
                                 channels, neighbors, isolated_cache)
        rows.append(result)
        if pair_id == 'far_strips-1' and phase == 0 and delay in (0, 300):
            examples[str(delay)] = trace
    return dict(
        kind='gegi_saved_window_activity_controls_v1', original_study_sha256=PARENT_SHA,
        source_sha256={name: scan.digest(Path(__file__).with_name(name)) for name in
                       ('gegi_window_activity_controls.py', 'gegi_window_activity.py', 'gegi_exposure_stream.py',
                        'gegi_trigger_windows.py', 'gegi_pulse_scan.py')},
        design=dict(
            delays_ns=DELAYS, phases_ns=PHASES, energies_keV=ENERGIES, noise_mode=NOISE_MODE,
            pairs=first_pairs, trigger_profile=PROFILE, relative_adc_support_ns=[int(RELATIVE_NS[0]), int(RELATIVE_NS[-1])],
            window='Use the first accepted full-clock trigger as the ADC origin, including trials that Control would '
                   'not store as qualified two-strip windows. Where present, match the first isolated input to that ADC grid.',
            scope='Fixed saved simulated injections for a positive control. Report delay from scheduled injection onsets, '
                  'separately from measured rise grouping and full-clock trigger acceptance. No efficiency inference.',
        ),
        counts=counts(rows) | dict(unique_isolated_window_replays=len(isolated_cache), new_transport_calls=0, new_drift_calls=0),
        by_delay_ns={str(delay): counts([row for row in rows if row['delay_ns'] == delay]) for delay in DELAYS},
        trials=rows, representative_waveforms=examples,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = study()
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        json.dump(result, output, allow_nan=False, separators=(',', ':'))
        output.write('\n')


if __name__ == '__main__':
    main()
