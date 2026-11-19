"""Evaluate measured GeGI event totals on the sealed 0.25 s exposure."""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import time

import gegi_event_energy as estimator
from gegi_event_store import encoded, sha
import gegi_exposure_stream as adc
from gegi_imaging import PAIR_ABS_KEV, PAIR_REL
import gegi_pulse_stream as pulse_stream
import gegi_source_exposure as exposure
import gegi_source_pileup as pileup


ROOT, LOCAL = exposure.ROOT, exposure.LOCAL
FROZEN = LOCAL / 'exposure.json'
FROZEN_SHA = 'adbe09e801d3ee8cd395e1fe4e4ad7cf84b0e285314752692a769a71b64c4664'
ENERGY_PARITY_TOL_KEV = 1e-9
REQUIRE = exposure.REQUIRE
SOURCE_LABELS = (*exposure.SOURCES, 'unassigned')


def prepare():
    frozen_hashes = {}
    saved = json.loads(pileup.bound_bytes(FROZEN, frozen_hashes, FROZEN_SHA))
    REQUIRE(saved['kind'] == 'gegi_saved_two_source_exposure_v1' and saved['status'] == 'completed'
            and saved['trigger_summary']['qualified_triggers'] == 864 and saved['trigger_summary']['qualified_slow_energies'] == 484,
            'Use the sealed continuous exposure baseline')
    for ref, digest in saved['source_sha256'].items():
        pileup.bound_bytes(ROOT / ref, frozen_hashes, digest)
    clock, _, _, rows, files, channels, hashes = exposure.inputs()
    REQUIRE(hashes == saved['input_sha256'], 'The underlying transport, waveform or clock inputs changed')
    components, unknown, cache, native_bytes = exposure.load_occurrences(clock, rows, files, channels)
    frozen_rows = saved['deposits']
    keys = ('source', 'occurrence_id', 'raw_event_id', 'group_id', 'first_ge_deposit_ns', 'last_ge_deposit_ns',
            'campaign_initial_id', 'native_status', 'native_available', 'arrival_class', 'metadata_sha256',
            'truth_edep_keV')
    REQUIRE(all(all(a[k] == b[k] for k in keys) for a, b in zip(rows, frozen_rows, strict=True)),
            'Per-occurrence identity differs from the sealed exposure')
    duration = saved['exposure']['clock_live_time_ns']
    REQUIRE(exposure.unseen_intervals(unknown, duration) == saved['exposure']['excluded_intervals_ns'],
            'Excluded analog-history intervals changed')
    return saved, components, cache, native_bytes, frozen_hashes


def compare_card(reference, actual, *, absolute_offset=0):
    card = {**pileup.pulse_card(actual), 'trigger_time_ns': actual['trigger_time_ns'] + absolute_offset}
    for key in ('trigger_time_ns', 'contact_ids', 'step_contact_ids', 'flags'):
        REQUIRE(card[key] == reference[key], f'Frozen trigger changed field {key}')
    if 'rise_end_ns' in reference:
        REQUIRE(actual['rise_end_ns'] + absolute_offset == reference['rise_end_ns'], 'Frozen activity end changed')
    a, b = reference['slow_energy_keV'], actual['slow_energy_keV']
    REQUIRE((a is None) == (b is None), 'Frozen single-pixel energy availability changed')
    if a is None:
        return 0.
    difference = abs(a - b)
    REQUIRE(difference <= ENERGY_PARITY_TOL_KEV, 'Frozen single-pixel slow energy changed')
    return difference


def geometry(result):
    x, y = result['x_contact_ids'], result['y_contact_ids']
    if result['guard_contact_ids']:
        return 'guard_collection'
    if not x or not y:
        return 'incomplete_strip_census'
    if len(x) == len(y) == 1:
        return 'single_pixel'
    return ('multi_strip_with_gap' if any(max(face) - min(face) + 1 > len(face) for face in (x, y))
            else 'multi_strip_contiguous')


def measured_card(pulse):
    measurement = estimator.estimate_event_energy(pulse)
    shape = geometry(measurement)
    additional = (pulse['slow_energy_keV'] is None and measurement['energy_keV'] is not None
                  and shape.startswith('multi_strip_'))
    if pulse['slow_energy_keV'] is not None:
        REQUIRE(measurement['energy_keV'] == pulse['slow_energy_keV'], 'New estimator altered a valid baseline energy')
    if measurement['energy_keV'] is not None:
        REQUIRE(measurement['status'] == 'qualified' and not measurement['guard_contact_ids'],
                'Guard or rejected estimate cannot enter the ADC spectrum')
    return {
        'geometry': shape, 'x_contact_ids': measurement['x_contact_ids'], 'y_contact_ids': measurement['y_contact_ids'],
        'guard_contact_ids': measurement['guard_contact_ids'],
        'estimate_status': measurement['status'], 'estimate_flags': measurement['flags'],
        'x_sum_keV': measurement['x_sum_keV'], 'y_sum_keV': measurement['y_sum_keV'],
        'x_minus_y_keV': measurement['x_minus_y_keV'],
        'closure_tolerance_keV': measurement['closure_tolerance_keV'],
        'baseline_energy_keV': pulse['slow_energy_keV'], 'event_energy_keV': measurement['energy_keV'],
        'additional_energy_keV': measurement['energy_keV'] if additional else None,
    }


def tolerance_match(a, b):
    return a is not None and b is not None and abs(a-b) <= max(PAIR_ABS_KEV, PAIR_REL*max(a, b))


def isolated_controls(saved, cache):
    """Use the already selected independent no-overlap control per unique waveform association."""
    checks, controls = [], {}
    for index, event in enumerate(saved['deposits']):
        if event['classification'] != 'unique_matched':
            continue
        key = event['source'], event['raw_event_id'], event['group_id']
        native, _, _ = cache[key]
        REQUIRE(native is not None, 'Unique scored deposit lost its complete native input')
        onset = event['first_ge_deposit_ns']
        phase_origin = math.floor(onset / exposure.DT_NS) * exposure.DT_NS
        times, codes = pulse_stream.acquire([(native, onset - phase_origin, 1.)])
        events = pulse_stream.reconstruct(times, codes)['events']
        parity = [compare_card(old, new, absolute_offset=phase_origin)
                  for old, new in zip(event['isolated_triggers'], events, strict=True)]
        receipt = {'deposit_index': index, 'source': event['source'], 'arrival_class': event['arrival_class'],
                   'isolated_trigger_count': len(events), 'baseline_max_delta_keV': max(parity, default=0.)}
        if len(events) == 1:
            estimate = measured_card(events[0])
            broad_energy = estimate['event_energy_keV']
            receipt.update(estimate, truth_edep_keV=event['truth_edep_keV'],
                           isolated_bias_vs_truth_keV=None if broad_energy is None else broad_energy - event['truth_edep_keV'],
                           within_truth_tolerance=tolerance_match(broad_energy, event['truth_edep_keV']))
            controls[index] = receipt
        checks.append(receipt)
    return checks, controls


def error(values):
    values = [v for v in values if v is not None]
    return {**exposure.metric(values), 'max_abs': max(map(abs, values)) if values else None}


def isolated_acceptance(checks):
    single_trigger = [row for row in checks if row['isolated_trigger_count'] == 1]
    available = [row for row in single_trigger if row['event_energy_keV'] is not None]
    additional = [row for row in available if row['additional_energy_keV'] is not None]
    return {
        'controls': len(checks), 'exactly_one_trigger': len(single_trigger),
        'trigger_multiplicity': dict(Counter(str(row['isolated_trigger_count']) for row in checks)),
        'baseline_energies': sum(row['baseline_energy_keV'] is not None for row in single_trigger),
        'qualified_event_energies': len(available),
        'additional_multi_strip_energies': len(additional),
        'additional_within_truth_tolerance': sum(row['within_truth_tolerance'] for row in additional),
        'additional_bias_vs_truth_keV': error(row['isolated_bias_vs_truth_keV'] for row in additional),
        'additional_x_minus_y_keV': error(row['x_minus_y_keV'] for row in additional),
        'baseline_control_max_delta_keV': max((row['baseline_max_delta_keV'] for row in checks), default=0.),
    }


def replay(saved, components):
    design = saved['design']
    adc_clock = adc.ADCExposure(components, live_time_ns=saved['exposure']['clock_live_time_ns'],
                                phase_ns=design['adc_phase_ns'], noise_seed=design['noise_seed'])
    reconstruction = adc.reconstruct_exposure(adc_clock, block_samples=design['block_samples'])
    mask = saved['exposure']['excluded_intervals_ns']
    live = saved['exposure']['clock_live_time_ns']
    retained = sorted((e for e in reconstruction['events'] if 0 <= e['trigger_time_ns'] < live
                       and not any(lo <= e['rise_end_ns'] and hi > e['trigger_time_ns'] for lo, hi in mask)),
                      key=lambda event: event['trigger_time_ns'])
    exact, worst = 0, 0.
    for old, new in zip(saved['triggers'], retained, strict=True):
        difference = compare_card(old, new)
        if old['slow_energy_keV'] is not None:
            exact += difference == 0.
            worst = max(worst, difference)
    REQUIRE(reconstruction['adc_samples_per_channel'] == saved['exposure']['total_live_adc_samples'],
            'Exposure sample count changed')
    return retained, {'trigger_identities_matched': len(retained), 'baseline_exact': exact,
                      'baseline_max_delta_keV': worst,
                      'baseline_tolerance_keV': ENERGY_PARITY_TOL_KEV,
                      'known_component_adc_sha256': reconstruction['adc_sha256'],
                      'identical_mask': True}


def evaluate(saved, pulses, controls):
    rows = []
    for i, (reference, pulse) in enumerate(zip(saved['triggers'], pulses, strict=True)):
        # Membership of the measured spectrum is complete at this point, with no source association supplied.
        row = measured_card(pulse)
        row.update(trigger_index=i, trigger_time_ns=pulse['trigger_time_ns'], baseline_flags=reference['flags'],
                   association=reference['association'], source='unassigned', arrival_class='unassigned',
                   truth_edep_keV=None, isolated_comparable=False, truth_bias_keV=None, isolated_bias_keV=None,
                   within_isolated_tolerance=None)
        if row['baseline_energy_keV'] is not None:
            # Retain the archived value if an operation order produced a sub-tolerance numerical difference.
            row['baseline_energy_keV'] = reference['slow_energy_keV']
        if reference['association'] == 'unique_matched':
            index = reference['deposit_index']
            mark = saved['deposits'][index]
            REQUIRE(mark['trigger_index'] == i, 'Frozen trigger belongs to a different deposit')
            row.update(source=mark['source'], arrival_class=mark['arrival_class'], raw_event_id=mark['raw_event_id'],
                       group_id=mark['group_id'], occurrence_id=mark['occurrence_id'])
            if row['additional_energy_keV'] is not None:
                measured = row['additional_energy_keV']
                row.update(truth_edep_keV=mark['truth_edep_keV'], truth_bias_keV=measured - mark['truth_edep_keV'])
                control = controls.get(index)
                if (control and control['event_energy_keV'] is not None
                        and all(row[f'{face}_contact_ids'] == control[f'{face}_contact_ids'] for face in 'xy')):
                    comparison = control['event_energy_keV']
                    row.update(isolated_comparable=True, isolated_bias_keV=measured - comparison,
                               within_isolated_tolerance=tolerance_match(measured, comparison))
        rows.append(row)
    return rows


def summary_row(rows, **labels):
    additional = [row for row in rows if row['additional_energy_keV'] is not None]
    baseline = sum(row['baseline_energy_keV'] is not None for row in rows)
    unmatched = sum(row['association'] not in ('unique_matched', 'merged') for row in additional)
    waveform_rejected = [r for r in rows if r['baseline_energy_keV'] is None and r['additional_energy_keV'] is None]
    return {
        **labels, 'qualified_triggers': len(rows), 'baseline_energies': baseline,
        'additional_energies': len(additional), 'combined_energies': baseline + len(additional),
        'additional_unique_matched': sum(r['association'] == 'unique_matched' for r in additional),
        'additional_merged': sum(r['association'] == 'merged' for r in additional),
        'additional_unassigned_other': unmatched,
        'remaining_without_energy': len(waveform_rejected),
        'additional_x_y_closure_keV': error(r['x_minus_y_keV'] for r in additional),
        'additional_bias_vs_truth_keV': error(r['truth_bias_keV'] for r in additional),
        'additional_bias_vs_isolated_keV': error(r['isolated_bias_keV'] for r in additional),
        'additional_within_isolated_tolerance': sum(r['within_isolated_tolerance'] is True for r in additional),
        'additional_without_comparable_isolated': sum(r['association'] == 'unique_matched' and not r['isolated_comparable']
                                                      for r in additional),
        'additional_baseline_flags': dict(Counter(f for row in additional for f in set(row['baseline_flags']))),
        'remaining_without_energy_flags': dict(Counter(f for row in waveform_rejected for f in set(row['estimate_flags']))),
    }


def aggregate(rows):
    groups = defaultdict(list)
    geometry_groups = defaultdict(list)
    for row in rows:
        for source in ('all', row['source']):
            for scope in ('all', row['arrival_class']):
                groups[source, scope].append(row)
        geometry_groups[row['geometry']].append(row)
    return (
        [summary_row(groups[source, scope], source=source, arrival_class=scope)
         for source in ('all', *SOURCE_LABELS) for scope in ('all', 'isolated', 'close', 'unassigned')
         if (source, scope) in groups],
        [summary_row(group, geometry=key) for key, group in sorted(geometry_groups.items())],
    )


def run(*, isolated_only=False):
    began = time.perf_counter()
    saved, components, cache, bytes_loaded, hashes = prepare()
    isolated_start = time.perf_counter()
    checks, controls = isolated_controls(saved, cache)
    accepted = isolated_acceptance(checks)
    isolated_wall = time.perf_counter() - isolated_start
    if isolated_only:
        return accepted
    replay_start = time.perf_counter()
    pulses, parity = replay(saved, components)
    replay_wall = time.perf_counter() - replay_start
    rows = evaluate(saved, pulses, controls)
    summary, geometry_summary = aggregate(rows)
    baseline = [row['baseline_energy_keV'] for row in rows if row['baseline_energy_keV'] is not None]
    additional = [row['additional_energy_keV'] for row in rows if row['additional_energy_keV'] is not None]
    REQUIRE(exposure.spectrum(baseline) == saved['slow_spectrum']
            and len(baseline) + len(additional) + summary[0]['remaining_without_energy'] == len(rows),
            'Event-energy and retained slow-spectrum census does not close')
    source_hashes = dict(saved['source_sha256'])
    for ref in ('tools/gegi_event_energy.py', 'tools/gegi_event_energy_study.py'):
        source_hashes[ref] = sha((ROOT / ref).read_bytes())
    return {
        'kind': 'gegi_saved_two_source_event_energy_v1', 'status': 'completed',
        'binding': {'exposure_sha256': hashes[FROZEN.relative_to(ROOT).as_posix()],
                    'source_sha256': source_hashes, 'input_sha256': saved['input_sha256']},
        'design': {'estimator': estimator.DEFINITION, 'qualified_adc_live_time_ns': saved['exposure']['qualified_adc_live_time_ns'],
                   'noise_seed': saved['design']['noise_seed'], 'adc_phase_ns': saved['design']['adc_phase_ns'],
                   'sample_period_ns': saved['design']['sample_period_ns'],
                   'spectrum_selection': 'Keep existing slow energy if present. A new entry requires an accepted '
                                         'waveform-only X/Y total and collecting-strip multiplicity on at least '
                                         'one face. This selection receives no simulation labels.',
                   'resolved_truth_scope': 'Truth and isolated errors are evaluated only on frozen unique '
                                           'trigger-to-group associations. A merged trigger may have one '
                                           'accepted total, with no inferred constituent energies or positions.',
                   'isolated_scope': 'No-overlap replay from the same saved charge response at its original ADC '
                                     'phase, without added noise. Exactly one trigger is required. Paired '
                                     'comparison requires equal X and Y collecting strip sets and an available '
                                     'isolated estimate. Threshold is max(2 keV, 2%) for engineering comparisons.',
                   'flags_scope': 'Flag counts may overlap. An event total does not establish strip pairing, '
                                  'position, Compton order or isotope assignment on an unknown trigger.',
                   'new_transport_calls': 0, 'new_drift_calls': 0},
        'baseline_parity': parity, 'isolated_acceptance': accepted,
        'summary': summary, 'geometry_summary': geometry_summary,
        'exposure_census': {'transport_deposits': len(saved['deposits']),
                            'native_unavailable': saved['summary'][0]['native_unavailable'],
                            'history_unqualified': saved['summary'][0]['history_unqualified'],
                            'history_boundary_unknown': saved['summary'][0]['history_boundary_unknown'],
                            'qualified_deposits': saved['summary'][0]['qualified_deposits'],
                            'missed': saved['summary'][0]['missed'],
                            'merged_deposits': saved['summary'][0]['merged'],
                            'merged_triggers': saved['trigger_summary']['merged']},
        'spectra': {'baseline': exposure.spectrum(baseline), 'additional': exposure.spectrum(additional),
                    'baseline_plus_additional': exposure.spectrum(baseline + additional)},
        'resources': {'isolated_replay_wall_s': isolated_wall, 'full_exposure_replay_wall_s': replay_wall,
                      'total_wall_s': time.perf_counter() - began, 'prepared_unique_native_array_bytes': bytes_loaded},
        'trigger_results': rows, 'isolated_checks': checks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-only', action='store_true')
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    if arguments.isolated_only:
        print(json.dumps(run(isolated_only=True), indent=2))
        return
    REQUIRE(arguments.output is not None, '--output is required for the complete study')
    output = arguments.output.resolve()
    REQUIRE(output.is_relative_to(LOCAL) and not output.exists(), 'Use a fresh report path below .local/gegi-source-clock')
    report = run()
    with output.open('xb') as file:
        file.write(encoded(report) + b'\n')
    print(json.dumps({key: report[key] for key in ('baseline_parity', 'isolated_acceptance', 'resources')}, indent=2))
    print(json.dumps(report['summary'][0], indent=2))


if __name__ == '__main__':
    main()
