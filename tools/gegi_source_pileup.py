"""Replay the sealed two-source clock pilot's close arrivals with ADC history."""

import argparse
from collections import Counter
from itertools import product
import json
import math
from pathlib import Path

import numpy as np

import gegi_digital_readout as digital
from gegi_event_store import encoded, sha
from gegi_imaging import PAIR_ABS_KEV, PAIR_REL
import gegi_pulse_stream as stream
from gegi_signal_reconstruction import read_saved_group
from gegi_source_clock import CAMPAIGN, ROOT, bound_bytes, require


_VIEWS = ('fresh_source_start', 'equilibrated_mark_library')
_MEMBERS = ('cs137_left', 'co60_right')
_PRE_NS = 6000
_POST_NS = 3000
_MATCH_NS = 60
_CAP_NS = 1000
_TAIL_NS = 24 * digital._TAU
_MAX_UNSEEN_LSB = .25
_DT = digital._DT


def identity(row):
    return row['source'], row['occurrence_id'], row['group_id']


def mark_group(clock, row):
    source = clock['sources'][row['source']]
    mark = source['marked_nonzero_events'][str(row['raw_event_id'])]
    require(mark['campaign_initial_id'] == row['campaign_initial_id'], 'Original mark identity changed')
    group = next(g for g in mark['groups'] if g['group_id'] == row['group_id'])
    return group


def saved_inputs(clock, complete, hashes):
    files, recipes = {}, {}
    for name, source in clock['sources'].items():
        folder = CAMPAIGN / 'chunks' / name / 'b000000'
        done = json.loads(bound_bytes(folder/'DONE.json', hashes, complete['chunks'][str(source['chunk_index'])]))
        require(done['identity']['source_group'] == name and done['identity']['model_sha256'] == source['model_sha256'],
                'Native store and transport differ in source or model identity')
        files[name] = folder/'events.sqlite'
        bound_bytes(files[name], hashes, done['artifacts']['events.sqlite']['sha256'])
        recipes[name] = done['response']['readout_recipe']['channels']
    require(len(recipes) == 2 and recipes['cs137-left'] == recipes['co60-right'],
            'Both source stores must share the same electrode geometry and wiring')
    return files, recipes['cs137-left']


def native_record(row, group, files, channels, cache):
    key = row['source'], row['raw_event_id'], row['group_id']
    if key not in cache:
        event, native, digest = read_saved_group(files[row['source']], key[1], key[2])
        require(event['event_id'] == key[1] and event['group_id'] == key[2] and event['source_group'] == key[0]
                and event['event_id'] + event['campaign_initial_offset'] == row['campaign_initial_id']
                and event['group_origin_time_ns'] - event['parent_primary_time_ns'] == group['first_deposit_since_parent_ns']
                and event['pulse_group']['row_indices'] == group['raw_row_indices']
                and math.isclose(event['truth_edep_keV'], group['positive_ge_energy_keV'], abs_tol=1e-7, rel_tol=0),
                'Saved charge group differs from the original clock mark')
        pulse = None
        if native is not None and digital.terminal_contacts_complete(event):
            pulse = stream.prepare_native(native, channels, terminal_complete=True)
            span = event['pulse_group']['last_deposit_time_ns'] - event['group_origin_time_ns']
            require(pulse.time_ns[-1] <= span + _CAP_NS + 1, 'Verified native support exceeds campaign drift cap')
        cache[key] = (pulse, event['status'], digest)
    return cache[key]


def tail_bound_lsb(energy_keV, age_ns):
    """Bound both free poles after the declared nominal charge-input horizon."""
    coef = digital._TAU / (digital._TAU - digital._BANDWIDTH_TAU)
    # |Q| <= 2 Edep for ideal Ramo weighting fields in [0, 1]. Integration by
    # parts gives a bound of 2 max|Q| on each feedback/low-pass state.
    return 4 * energy_keV * digital._VOLTS_PER_KEV * coef / digital._LSB_V * (
        math.exp(-age_ns / digital._TAU) + math.exp(-age_ns / digital._BANDWIDTH_TAU))


def capture_plan(pairs):
    spans = []
    for i, pair in enumerate(pairs):
        members = [pair[key] for key in _MEMBERS]
        start = math.floor((min(x['first_ge_deposit_ns'] for x in members) - _PRE_NS) / _DT) * _DT
        stop = math.ceil((max(x['last_ge_deposit_ns'] for x in members) + _CAP_NS + _POST_NS) / _DT) * _DT
        spans.append((start, stop, i))
    merged = []
    for start, stop, index in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], stop)
            merged[-1][2].append(index)
        else:
            merged.append([start, stop, [index]])
    return merged


def capture(start, stop, ledger, clock, files, channels, cache):
    history, unknown, pulses = [], [], []
    omitted, omitted_lsb = 0, 0.
    for row in ledger:
        onset = row['first_ge_deposit_ns']
        if onset > stop:
            break
        group = mark_group(clock, row)
        # The exact Ge step timing is retained. The cap is a bound from the
        # nominal SSD configuration, including one final 1 ns resampling bin.
        age = start - (row['last_ge_deposit_ns'] + _CAP_NS + 1)
        energy = group['positive_ge_energy_keV']
        if age >= _TAIL_NS:
            omitted += 1
            omitted_lsb += tail_bound_lsb(energy, age)
            continue
        native, status, digest = native_record(row, group, files, channels, cache)
        entry = {**row, 'metadata_sha256': digest, 'native_status': status,
                 'truth_edep_keV': energy, 'native_support_ns': None}
        history.append(entry)
        if native is None:
            bound = tail_bound_lsb(energy, age) if age > 0 else None
            unknown.append({**entry, 'upper_bound_lsb': bound})
        else:
            entry['native_support_ns'] = float(native.time_ns[-1])
            pulses.append((native, onset))
    unknown_bound = None if any(item['upper_bound_lsb'] is None for item in unknown) else math.fsum(
        item['upper_bound_lsb'] for item in unknown)
    qualified = unknown_bound is not None and unknown_bound + omitted_lsb < _MAX_UNSEEN_LSB
    receipt = {'adc_real_interval_ns_inclusive': [start, stop], 'included_groups': history, 'unknown_native_groups': unknown,
               'qualification': 'nominal_bound_below_cutoff' if qualified else 'indeterminate_native_history',
               'unknown_native_tail_bound_lsb': unknown_bound, 'older_omitted_count': omitted,
               'older_omitted_tail_bound_lsb': omitted_lsb}
    if not qualified:
        return receipt, None, None
    time = np.arange(start, stop + _DT, _DT, dtype=float)
    voltage = np.zeros((len(channels), len(time)))
    for native, onset in pulses:
        skip = int(time.searchsorted(onset))
        voltage[:, skip:] += stream._sample_pulse(native, time[skip:] - onset)
    code, _ = digital._digitize(voltage)
    receipt.update(adc_sha256=sha(np.asarray(code, dtype='<i2').tobytes()),
                   initial_known_analog_max_abs_lsb=float(np.max(np.abs(voltage[:, 0])) / digital._LSB_V))
    return receipt, time, code


def continuous_features(time, code):
    # In this noiseless zero-offset study the baseline is known. The preamble
    # supplies that baseline to the frozen API, with only real samples after
    # it. The missing early pole-zero sum is an additive constant. Both arms
    # of any scored trapezoid and all fast references lie inside real samples,
    # where their differences cancel that constant.
    n_pre = digital._TRIGGER_INDEX
    baseline_time = time[0] + _DT * np.arange(-n_pre, 0)
    return stream.reconstruct(np.r_[baseline_time, time], np.pad(code, ((0, 0), (n_pre, 0))))


def pulse_card(event):
    return {key: event[key] for key in
            ('trigger_time_ns', 'contact_ids', 'step_contact_ids', 'slow_energy_keV', 'flags')}


def control(row, clock, files, channels, cache):
    pulse, status, _ = native_record(row, mark_group(clock, row), files, channels, cache)
    if pulse is None:
        return {'status': status, 'triggers': []}
    onset = row['first_ge_deposit_ns']
    zero = math.floor(onset/_DT) * _DT
    time, codes = stream.acquire([(pulse, onset - zero, 1.)])
    return {'status': status,
            'triggers': [pulse_card(e) for e in stream.reconstruct(time + zero, codes)['events']]}


def evaluate_pair(pair, reconstruction, clock, files, channels, cache):
    members = [pair[k] for k in _MEMBERS]
    controls = [control(member, clock, files, channels, cache) for member in members]
    result = {'isolated_controls_cs_then_co': controls, 'triggers': None, 'match_status': 'unavailable_capture',
              'both_usable_energies': None, 'matched_energy_comparison': None}
    if reconstruction is None:
        return result
    lo = min(x['first_ge_deposit_ns'] for x in members) - _MATCH_NS
    hi = max(x['last_ge_deposit_ns'] for x in members) + digital._TIMING['gate_ns'][1]
    observed = [pulse_card(e) for e in reconstruction['events'] if lo <= e['trigger_time_ns'] <= hi]
    result.update(trigger_search_interval_ns=[lo, hi], triggers=observed, both_usable_energies=False,
                  match_status='isolated_trigger_multiplicity')
    if any(len(c['triggers']) != 1 for c in controls):
        return result
    anchors = [c['triggers'][0] for c in controls]
    choices = [[i for i, event in enumerate(observed)
                if abs(event['trigger_time_ns'] - anchor['trigger_time_ns']) <= _MATCH_NS] for anchor in anchors]
    assignments = [(a, b) for a, b in product(*choices) if a != b]
    result['possible_trigger_assignments_cs_then_co'] = assignments
    if len(assignments) != 1:
        result['match_status'] = 'ambiguous_temporal_assignment' if assignments else 'two_temporal_matches_unavailable'
        return result
    comparisons = []
    for i, anchor in zip(assignments[0], anchors):
        event = observed[i]
        a, b = anchor['slow_energy_keV'], event['slow_energy_keV']
        energy_delta = b - a if a is not None and b is not None else None
        same_pair = event['contact_ids'] is not None and event['contact_ids'] == anchor['contact_ids']
        usable = (same_pair and energy_delta is not None
                  and abs(energy_delta) <= max(PAIR_ABS_KEV, PAIR_REL * max(a, b)))
        comparisons.append({'trigger_index': i, 'same_qualified_strip_pair': same_pair,
                            'observed_minus_isolated_keV': energy_delta, 'usable': usable})
    result.update(match_status='matched_two_with_extras' if len(observed) > 2 else 'matched_two',
                  matched_energy_comparison=comparisons,
                  both_usable_energies=len(observed) == 2 and all(x['usable'] for x in comparisons))
    return result


def guard_error(first, second):
    require(len(first['triggers']) == len(second['triggers'])
            and first['match_status'] == second['match_status']
            and first['both_usable_energies'] == second['both_usable_energies'],
            'Trigger count or assignment changed with a longer digital guard')
    worst = 0.
    for a, b in zip(first['triggers'], second['triggers']):
        energy_key = 'slow_energy_keV'
        require({k: v for k, v in a.items() if k != energy_key} ==
                {k: v for k, v in b.items() if k != energy_key},
                'Scored trigger or strip status changed with a longer digital guard')
        ea, eb = a[energy_key], b[energy_key]
        require((ea is None) == (eb is None), 'Scored slow energy validity changed with a longer guard')
        if ea is not None:
            worst = max(worst, abs(ea-eb))
    require(worst < 1e-8, 'Scored slow energy changed with a longer digital guard')
    return worst


def closest_unavailable_diagnostic(rows, clock, files, channels, cache):
    unavailable = [(i, row) for i, row in enumerate(rows) if row['triggers'] is None]
    if not unavailable:
        return None
    index, pair = min(unavailable, key=lambda item: item[1]['absolute_onset_gap_ns'])
    members = sorted((pair[key] for key in _MEMBERS), key=lambda row: row['first_ge_deposit_ns'])
    start, stop, _ = capture_plan([pair])[0]
    receipt, time, codes = capture(start, stop, members, clock, files, channels, cache)
    require(time is not None, 'Closest candidate-only diagnostic requires two qualifying native waveforms')
    result = evaluate_pair(pair, continuous_features(time, codes), clock, files, channels, cache)
    return {'candidate_index': index, 'absolute_onset_gap_ns': pair['absolute_onset_gap_ns'],
            'scope': 'Only the two candidate waveforms are represented. Their absolute timing and ADC phase are unchanged. The full-history ADC result remains indeterminate.',
            'adc_sha256': receipt['adc_sha256'], 'trigger_count': len(result['triggers']),
            'triggers': result['triggers'], 'match_status': result['match_status'],
            'both_usable_energies': result['both_usable_energies']}


def replay_view(view, clock, files, channels, cache):
    pairs = view['cross_source']['within_candidate_window']
    require(len(pairs) == view['cross_source']['onset_gap_counts']['6000'], 'Clock candidate census differs')
    ledger = sorted((row for source in view['sources'].values() for row in source['eligible_groups']),
                    key=lambda row: row['first_ge_deposit_ns'])
    occurrences = {identity(row): row for row in ledger}
    require(len(occurrences) == len(ledger) and all(occurrences.get(identity(pair[k])) == pair[k]
            for pair in pairs for k in _MEMBERS), 'Clock occurrence is duplicated or missing')
    captures, results, guard_errors = [], {}, []
    for start, stop, indices in capture_plan(pairs):
        require(start >= clock['design']['live_time_ns'][0] and stop < clock['design']['live_time_ns'][1],
                'Capture crosses a boundary of the available clock ledger')
        receipt, time, codes = capture(start, stop, ledger, clock, files, channels, cache)
        observed = None if time is None else continuous_features(time, codes)
        captures.append({**receipt, 'candidate_indices': indices,
                         'saturated_contact_ids': None if observed is None else observed['saturated_contact_ids']})
        measured = {i: evaluate_pair(pairs[i], observed, clock, files, channels, cache) for i in indices}
        results.update({i: {**pairs[i], **measured[i]} for i in indices})
        if observed is not None:
            _, alt_time, alt_code = capture(start - 2000, stop, ledger, clock, files, channels, cache)
            require(alt_time is not None, 'ADC prehistory validation requires a qualified longer guard')
            require(np.array_equal(alt_time[-len(time):], time) and np.array_equal(alt_code[:, -len(time):], codes),
                    'Absolute ADC grid or samples changed with a longer digital guard')
            alt = continuous_features(alt_time, alt_code)
            guard_errors.extend(guard_error(measured[i], evaluate_pair(pairs[i], alt, clock, files, channels, cache))
                                for i in indices)
    rows = [results[i] for i in range(len(pairs))]
    usable = [r for r in rows if r['triggers'] is not None]
    counts = Counter(len(r['triggers']) for r in usable)
    return {'source_clock_counts': {source: row['counts'] for source, row in view['sources'].items()},
            'onset_gap_counts': view['cross_source']['onset_gap_counts'],
            'candidate_windows': len(rows), 'captured_segments': len(captures),
            'distinct_candidate_members': len({identity(pair[k]) for pair in pairs for k in _MEMBERS}),
            'qualified_windows': len(usable), 'unavailable_windows': len(rows)-len(usable),
            'trigger_counts_qualified': {'zero': counts[0], 'one': counts[1], 'two': counts[2],
                                         'more_than_two': sum(v for n, v in counts.items() if n > 2)},
            'match_status_counts_qualified': dict(Counter(r['match_status'] for r in usable)),
            'qualified_windows_with_multistrip_trigger': sum(
                any('unresolved_strip_multiplicity' in e['flags'] for e in r['triggers']) for r in usable),
            'qualified_windows_with_guard_trigger': sum(
                any('guard_collection' in e['flags'] for e in r['triggers']) for r in usable),
            'both_usable_energy_windows': sum(r['both_usable_energies'] for r in usable),
            'captures': captures, 'candidates': rows,
            'closest_unavailable_candidate_only': closest_unavailable_diagnostic(rows, clock, files, channels, cache),
            'longer_guard_check': {'windows': len(guard_errors), 'longer_guard_ns': _PRE_NS + 2000,
                                   'adc_samples_identical': True, 'max_slow_energy_difference_keV': max(guard_errors)}
            if guard_errors else None}


def run(path):
    hashes = {}
    clock = json.loads(bound_bytes(path, hashes))
    require(clock['kind'] == 'gegi_saved_two_source_clock_pilot_v1' and clock['status'] == 'completed',
            'Use the completed two-source clock pilot')
    for ref, digest in (clock['input_sha256'] | clock['source_sha256']).items():
        bound_bytes(ROOT/ref, hashes, digest)
    complete = json.loads(bound_bytes(CAMPAIGN/'COMPLETE.json', hashes))
    files, channels = saved_inputs(clock, complete, hashes)
    cache = {}
    views = {key: replay_view(clock['views'][key], clock, files, channels, cache) for key in _VIEWS}
    sources = ('gegi_source_pileup.py', 'gegi_pulse_stream.py', 'gegi_digital_readout.py',
               'gegi_signal_reconstruction.py', 'gegi_event_store.py', 'gegi_source_clock.py')
    return {'kind': 'gegi_saved_two_source_pileup_pilot_v1', 'status': 'completed',
            'input_sha256': hashes, 'source_sha256': {f'tools/{name}': sha((ROOT/'tools'/name).read_bytes()) for name in sources},
            'design': {'candidate_scope': 'Fixed clock pairs with Ge onset separation <=6 us. Windows can share an acquisition.',
                       'clock_scope': 'The finite clock begins with zero front-end state and includes all eligible in-window Ge groups; source prehistory adds delayed deposits but pre-window Ge arrivals were not scheduled by the pilot.',
                       'sample_period_ns': _DT, 'adc_phase_ns': 0, 'noise_seed': None,
                       'noise_scope': 'No synthetic noise or DC offset in this first pass; voltages are summed before a single ADC quantization.',
                       'real_adc_guard_before_first_candidate_ns': _PRE_NS, 'post_native_support_ns': _POST_NS,
                       'native_support_scope': 'Unseen current is bounded only under the nominal simulation envelope of last Ge deposit + 1000 ns drift cap + 1 ns native grid bin, using ideal Ramo weighting bounds. Late physical charge beyond this envelope is unverified.',
                       'history_cutoff_after_nominal_support_ns': _TAIL_NS, 'maximum_total_unseen_voltage_lsb': _MAX_UNSEEN_LSB,
                       'digital_state': 'Known zero DC baseline, with real ADC guard samples and the continuous analog history of both poles. The old matched pole-zero accumulator contributes an additive constant that cancels in local gates.',
                       'match_tolerance_ns': _MATCH_NS, 'energy_match_absolute_keV': PAIR_ABS_KEV,
                       'energy_match_relative': PAIR_REL,
                       'both_usable_definition': 'Exactly two triggers uniquely match the two isolated times. Both collecting strip pairs agree with their isolated controls, and each slow energy is within the original face-pair tolerance of the isolated value.',
                       'conditioned_scope': 'The selected close arrivals do not estimate a full acquisition trigger rate, energy efficiency or hardware pile-up probability.',
                       'new_transport_calls': 0, 'new_drift_calls': 0},
            'digital_profile_sha256': digital.PROFILE_SHA256, 'views': views}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clock', type=Path, default=ROOT/'.local/gegi-source-clock/pilot.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    require(output.is_relative_to(ROOT/'.local') and not output.is_relative_to(CAMPAIGN),
            'Place the new report below project .local, outside the sealed campaign')
    report = run(args.clock.resolve())
    with output.open('xb') as handle:
        handle.write(encoded(report) + b'\n')
    print(json.dumps({key: {k: row[k] for k in ('candidate_windows', 'captured_segments', 'qualified_windows',
                      'unavailable_windows', 'trigger_counts_qualified', 'both_usable_energy_windows')}
                      for key, row in report['views'].items()}))


if __name__ == '__main__':
    main()
