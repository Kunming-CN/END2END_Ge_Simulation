"""Census one complete saved two-source clock through the nominal continuous GeGI ADC."""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.optimize import linear_sum_assignment

import gegi_exposure_stream as adc
import gegi_digital_readout as digital
from gegi_event_store import encoded, sha
from gegi_imaging import PAIR_ABS_KEV, PAIR_REL
import gegi_source_pileup as prior


ROOT, CAMPAIGN = prior.ROOT, prior.CAMPAIGN
LOCAL = ROOT / '.local/gegi-source-clock'
VIEW = 'equilibrated_mark_library'
NOISE_SEED = 120261118
PHASE_NS = 0
DT_NS = digital._DT
NEAR_NS = 6000
MATCH_NS = prior._MATCH_NS
SEARCH_END_NS = digital._TIMING['gate_ns'][1]
PRE_NS, POST_NS = 6000, 4000
BLOCK_SAMPLES = 32768
SPECTRUM_STEP_KEV, SPECTRUM_STOP_KEV = 20, 3000
SOURCES = ('cs137-left', 'co60-right')
REQUIRE = prior.require


def inputs():
    hashes = {}
    clock = json.loads(prior.bound_bytes(LOCAL / 'pilot.json', hashes))
    pilot = json.loads(prior.bound_bytes(LOCAL / 'pileup.json', hashes))
    REQUIRE(clock['kind'] == 'gegi_saved_two_source_clock_pilot_v1' and clock['status'] == 'completed'
            and pilot['kind'] == 'gegi_saved_two_source_pileup_pilot_v1' and pilot['status'] == 'completed',
            'Use the two completed clock and waveform receipts')
    for ref, digest in (clock['input_sha256'] | clock['source_sha256']).items():
        prior.bound_bytes(ROOT / ref, hashes, digest)
    REQUIRE(all(hashes.get(ref, digest) == digest for ref, digest in pilot['input_sha256'].items()),
            'Clock and waveform pilot were bound from different transport bytes')
    campaign = json.loads(prior.bound_bytes(CAMPAIGN / 'COMPLETE.json', hashes))
    files, channels = prior.saved_inputs(clock, campaign, hashes)
    view = clock['views'][VIEW]
    rows = sorted((row.copy() for source in SOURCES for row in view['sources'][source]['eligible_groups']),
                  key=lambda row: row['first_ge_deposit_ns'])
    REQUIRE(len({prior.identity(row) for row in rows}) == len(rows)
            and len(rows) == sum(src['counts']['eligible_groups'] for src in view['sources'].values()),
            'Every eligible occurrence must enter the exposure once')
    REQUIRE(clock['design']['live_time_ns'][0] == 0, 'Expected the declared time-zero ADC initialization')
    return clock, pilot, view, rows, files, channels, hashes


def pulse_cards(pulses, results):
    """Convert reconstruction to the close-window pilot's persisted card schema."""
    return [{**prior.pulse_card(pulse), 'trigger_time_ns': pulse['trigger_time_ns'] + results} for pulse in pulses]


def parity_check(clock, pilot, files, channels):
    original = pilot['views'][VIEW]
    saved = next(row for row in original['captures'] if row['qualification'] == 'nominal_bound_below_cutoff')
    start, stop = saved['adc_real_interval_ns_inclusive']
    indices = saved['candidate_indices']
    candidates = [original['candidates'][i] for i in indices]
    history, cache = [], {}
    components = []
    for row in saved['included_groups']:
        native, _, _ = prior.native_record(row, prior.mark_group(clock, row), files, channels, cache)
        if native is not None:
            history.append(row)
            components.append((native, row['first_ge_deposit_ns'], 1.))
    origin = math.floor(history[0]['first_ge_deposit_ns'] / DT_NS) * DT_NS
    exposure = adc.ADCExposure([(native, onset - origin, scale) for native, onset, scale in components],
                              live_time_ns=stop - origin + DT_NS, phase_ns=PHASE_NS)
    seen = []
    for index, block in exposure.blocks(block_samples=BLOCK_SAMPLES):
        lo = max(index, (start - origin) // DT_NS)
        hi = min(index + block.shape[1], (stop - origin) // DT_NS + 1)
        if lo < hi:
            seen.append(block[:, lo - index:hi - index])
    observed_codes = np.concatenate(seen, axis=1)
    REQUIRE(observed_codes.shape[1] == (stop-start)//DT_NS + 1
            and sha(np.asarray(observed_codes, dtype='<i2').tobytes()) == saved['adc_sha256'],
            'Continuous exposure differs from the saved noiseless analog capture')
    result = adc.reconstruct_exposure(exposure, block_samples=BLOCK_SAMPLES)
    trigger_cards = pulse_cards(result['events'], origin)
    worst = 0.
    for saved_pair in candidates:
        lo, hi = saved_pair['trigger_search_interval_ns']
        actual = [p for p in trigger_cards if lo <= p['trigger_time_ns'] <= hi]
        expected = saved_pair['triggers']
        REQUIRE(len(actual) == len(expected), 'Noiseless exposure pilot trigger multiplicity changed')
        for a, b in zip(actual, expected):
            v_a, v_b = a['slow_energy_keV'], b['slow_energy_keV']
            REQUIRE({k: v for k, v in a.items() if k != 'slow_energy_keV'} ==
                    {k: v for k, v in b.items() if k != 'slow_energy_keV'}
                    and (v_a is None) == (v_b is None), 'Noiseless exposure pilot changed trigger or energy status')
            if v_a is not None:
                worst = max(worst, abs(v_a - v_b))
    REQUIRE(worst < 1e-7, 'Noiseless exposure pilot changes the calibrated energy')
    return {'adc_codes_identical': True, 'candidate_windows': len(candidates),
            'absolute_interval_ns': [start, stop], 'simulated_prefix_ns': stop - origin + DT_NS,
            'same_trigger_and_energy_status': True, 'max_slow_energy_delta_keV': worst}


def load_occurrences(clock, rows, files, channels):
    cache, components, unknown = {}, [], []
    onsets = [row['first_ge_deposit_ns'] for row in rows]
    for i, row in enumerate(rows):
        near = (i > 0 and onsets[i] - onsets[i-1] <= NEAR_NS
                or i + 1 < len(rows) and onsets[i+1] - onsets[i] <= NEAR_NS)
        group = prior.mark_group(clock, row)
        native, status, digest = prior.native_record(row, group, files, channels, cache)
        onset = row['first_ge_deposit_ns']
        row.update(arrival_class='close' if near else 'isolated', native_status=status,
                   metadata_sha256=digest, truth_edep_keV=group['positive_ge_energy_keV'])
        if native is None:
            row['native_available'] = False
            unknown.append(row)
        else:
            row['native_available'] = True
            components.append((native, onset, 1.))
    floats_bytes = sum(pulse.time_ns.nbytes + pulse.drive_V.nbytes + pulse.knot_V.nbytes
                       for pulse, _, _ in cache.values() if pulse is not None)
    return components, unknown, cache, floats_bytes


def unseen_intervals(unknown, live):
    """Mask missing charge and a guard on either side of its remaining analog tail."""
    entries = [(0, PRE_NS), (live - POST_NS, live)]
    active = []
    for index, row in enumerate(unknown):
        onset = row['first_ge_deposit_ns']
        horizon = row['last_ge_deposit_ns'] + prior._CAP_NS + 1
        row['nominal_unknown_input_window_ns'] = [onset, horizon]
        active.append((horizon, row['truth_edep_keV']))
        next_onset = unknown[index + 1]['first_ge_deposit_ns'] if index + 1 < len(unknown) else live
        earliest = math.ceil(max(h for h, _ in active) / DT_NS)
        last = min(live // DT_NS, math.ceil(next_onset / DT_NS))
        # After the latest input horizon, the sum falls monotonically until the next arrival.
        if earliest < last:
            while earliest < last:
                mid = (earliest + last) // 2
                bound = math.fsum(prior.tail_bound_lsb(energy, mid * DT_NS - end) for end, energy in active)
                if bound > prior._MAX_UNSEEN_LSB:
                    earliest = mid + 1
                else:
                    last = mid
            end = min(next_onset, earliest * DT_NS)
        else:
            end = next_onset
        # Keep any feature or matcher whose context could touch a missing sample unscored.
        entries.append((onset - POST_NS, end + PRE_NS))
    intervals = []
    for start, stop in sorted(entries):
        start, stop = max(0, math.floor(start / DT_NS) * DT_NS), min(live, math.ceil(stop / DT_NS) * DT_NS)
        if start >= stop:
            continue
        if intervals and start <= intervals[-1][1]:
            intervals[-1][1] = max(intervals[-1][1], stop)
        else:
            intervals.append([start, stop])
    return intervals


def in_regions(t, intervals):
    index = bisect_right(intervals, [t, math.inf]) - 1
    return index >= 0 and intervals[index][0] <= t < intervals[index][1]


def reference_controls(rows, clock, files, channels, cache):
    for row in rows:
        if row['classification'] == 'awaiting_match':
            row['isolated_triggers'] = prior.control(row, clock, files, channels, cache)['triggers']


def strip_evidence(row, trigger):
    observed = set(trigger['step_contact_ids'])
    best = 0
    for anchor in row['isolated_triggers']:
        expected = set(anchor['step_contact_ids'])
        if anchor['contact_ids'] is not None and anchor['contact_ids'] == trigger['contact_ids']:
            best = max(best, 3)
        elif expected and expected <= observed:
            best = max(best, 2)
        elif any(c < 18 for c in expected & observed) and any(c >= 18 for c in expected & observed):
            best = max(best, 1)
    return best


def overlaps_activity(onset, trigger):
    return trigger['trigger_time_ns'] - MATCH_NS <= onset <= trigger['rise_end_ns'] + MATCH_NS


def related(onset, row, trigger):
    measured = trigger['trigger_time_ns']
    anchors = row.get('isolated_triggers') or []
    if overlaps_activity(onset, trigger):
        return True
    if anchors:
        return any(abs(a['trigger_time_ns'] - measured) <= MATCH_NS for a in anchors)
    return onset - MATCH_NS <= measured <= onset + SEARCH_END_NS


def component_matching(deposits, triggers, edges):
    """Maximize matched count and then strip support, exposing nonunique assignments."""
    n, m = len(deposits), len(triggers)
    if n > 1 and m == 1:
        return 'merged', []
    cardinality = 3 * min(n, m) + 1
    weight = np.full((n, m + n), -cardinality, dtype=int)
    weight[:, m:] = 0  # unmatched deposit
    for i, d in enumerate(deposits):
        for j, t in enumerate(triggers):
            if t in edges[d]:
                weight[i, j] = cardinality + edges[d][t]
    a, b = linear_sum_assignment(weight, maximize=True)
    optimum = weight[a, b].sum()
    accepted = [(i, j) for i, j in zip(a, b) if weight[i, j] > 0]
    for i, j in accepted:
        old = weight[i, j]
        weight[i, j] = -cardinality
        x, y = linear_sum_assignment(weight, maximize=True)
        ambiguous = weight[x, y].sum() == optimum
        weight[i, j] = old
        if ambiguous:
            return 'ambiguous', []
    return 'resolved', [(deposits[i], triggers[j]) for i, j in accepted]


def assign(rows, triggers, mask):
    trigger_times = [trigger['trigger_time_ns'] for trigger in triggers]
    edges, inverse = {}, defaultdict(list)
    for i, row in enumerate(rows):
        onset = row['first_ge_deposit_ns']
        # Any very long connected activity touching a missing-history interval is unscored.
        lo = bisect_left(trigger_times, onset - PRE_NS)
        hi = bisect_right(trigger_times, onset + SEARCH_END_NS + MATCH_NS)
        if row['classification'] != 'awaiting_match':
            for trigger in triggers[lo:hi]:
                if trigger['association'] == 'unmatched' and related(onset, row, trigger):
                    trigger['association'] = 'history_boundary_unknown'
            continue
        links = {j: strip_evidence(row, triggers[j]) for j in range(lo, hi)
                 if not in_regions(trigger_times[j], mask) and related(onset, row, triggers[j])}
        edges[i] = links
        for j in links:
            inverse[j].append(i)
    unseen = set(edges)
    while unseen:
        start = min(unseen)
        ds, ts, queue = {start}, set(), [start]
        while queue:
            for j in edges[queue.pop()]:
                if j not in ts:
                    ts.add(j)
                    new = set(inverse[j]) - ds
                    ds.update(new)
                    queue.extend(new)
        unseen.difference_update(ds)
        if not ts:
            rows[start]['classification'] = 'missed'
            continue
        if any(triggers[t]['association'] == 'history_boundary_unknown' for t in ts):
            for i in ds:
                rows[i]['classification'] = 'history_boundary_unknown'
            for t in ts:
                triggers[t]['association'] = 'history_boundary_unknown'
            continue
        status, accepted = component_matching(sorted(ds), sorted(ts), edges)
        if status != 'resolved':
            for i in ds:
                rows[i]['classification'] = status
            for j in ts:
                triggers[j]['association'] = status
            continue
        for i in ds:
            rows[i]['classification'] = 'missed'
        for i, j in accepted:
            rows[i].update(classification='unique_matched', trigger_index=j, strip_evidence=edges[i][j])
            triggers[j].update(association='unique_matched', deposit_index=i)


def measured_energy(row, trigger):
    measured = trigger['slow_energy_keV']
    isolated = [p for p in row['isolated_triggers'] if p['contact_ids'] is not None
                and p['contact_ids'] == trigger['contact_ids'] and p['slow_energy_keV'] is not None]
    reference = isolated[0]['slow_energy_keV'] if len(isolated) == 1 else None
    delta = measured - reference if measured is not None and reference is not None else None
    return {'slow_energy_keV': measured, 'slow_bias_vs_truth_keV': measured - row['truth_edep_keV'] if measured is not None else None,
            'reference_isolated_keV': reference, 'slow_bias_vs_isolated_keV': delta,
            'agrees_with_isolated': delta is not None and abs(delta) <= max(PAIR_ABS_KEV, PAIR_REL * max(measured, reference))}


def metric(values):
    values = [v for v in values if v is not None]
    n = len(values)
    return {'n': n, 'mean': math.fsum(values) / n if n else None,
            'rms': math.sqrt(math.fsum(x*x for x in values) / n) if n else None}


def summarize(rows, triggers):
    table = []
    for scope in ('all', *SOURCES):
        for relation in ('all', 'isolated', 'close'):
            group = [r for r in rows if (scope == 'all' or r['source'] == scope)
                     and (relation == 'all' or r['arrival_class'] == relation)]
            count = Counter(row['classification'] for row in group)
            matched = [r for r in group if r['classification'] == 'unique_matched']
            measured = [r['energy'] for r in matched]
            missing = [triggers[r['trigger_index']] for r in matched if r['energy']['slow_energy_keV'] is None]
            energy_flags = Counter(flag for t in missing for flag in set(t['flags']))
            qualified = count['unique_matched'] + count['missed'] + count['merged'] + count['ambiguous']
            REQUIRE(len(group) == qualified + count['native_unavailable'] + count['history_unqualified']
                    + count['history_boundary_unknown'], 'Exposure outcomes must partition all deposits')
            table.append({'source': scope, 'arrival_class': relation, 'deposits': len(group),
                          'native_unavailable': count['native_unavailable'], 'history_unqualified': count['history_unqualified'],
                          'history_boundary_unknown': count['history_boundary_unknown'], 'qualified_deposits': qualified,
                          'unique_matched': count['unique_matched'], 'missed': count['missed'], 'merged': count['merged'],
                          'ambiguous': count['ambiguous'],
                          'matched_energy_qualified': sum(m['slow_energy_keV'] is not None for m in measured),
                          'matched_energy_agrees': sum(m['agrees_with_isolated'] for m in measured),
                          'energy_bias_vs_truth_keV': metric([m['slow_bias_vs_truth_keV'] for m in measured]),
                          'energy_bias_vs_isolated_keV': metric([m['slow_bias_vs_isolated_keV'] for m in measured]),
                          'missing_energy_flags': dict(energy_flags)})
    return table


def spectrum(energies):
    edges = list(range(0, SPECTRUM_STOP_KEV + 1, SPECTRUM_STEP_KEV))
    counts = Counter(math.floor(energy / SPECTRUM_STEP_KEV) for energy in energies)
    return {'bin_edges_keV': edges, 'lower_inclusive_upper_exclusive': True,
            'counts': [counts[b] for b in range(len(edges) - 1)],
            'underflow': sum(v for k, v in counts.items() if k < 0),
            'overflow': sum(v for k, v in counts.items() if k >= len(edges) - 1),
            'exact_zero': sum(e == 0 for e in energies), 'entries': len(energies)}


def run(*, parity_only):
    began = time.perf_counter()
    clock, pilot, view, rows, files, channels, hashes = inputs()
    checked = parity_check(clock, pilot, files, channels)
    checked['elapsed_wall_s'] = time.perf_counter() - began
    if parity_only:
        return checked
    components, unknown, cache, native_bytes = load_occurrences(clock, rows, files, channels)
    prepared_s = time.perf_counter() - began
    live = clock['design']['live_time_ns'][1]
    exposure = adc.ADCExposure(components, live_time_ns=live, phase_ns=PHASE_NS, noise_seed=NOISE_SEED)
    start = time.perf_counter()
    reconstructed = adc.reconstruct_exposure(exposure, block_samples=BLOCK_SAMPLES)
    elapsed = time.perf_counter() - start
    mask = unseen_intervals(unknown, live)
    qualified_ns = live - sum(stop - start for start, stop in mask)
    for row in rows:
        row['classification'] = ('native_unavailable' if not row['native_available']
                                 else 'history_unqualified' if in_regions(row['first_ge_deposit_ns'], mask)
                                 else 'awaiting_match')
    reference_controls(rows, clock, files, channels, cache)
    triggers = []
    for pulse in reconstructed['events']:
        if not 0 <= pulse['trigger_time_ns'] < live:
            continue
        if any(lo <= pulse['rise_end_ns'] and hi > pulse['trigger_time_ns'] for lo, hi in mask):
            continue
        trigger = {**prior.pulse_card(pulse), 'rise_end_ns': pulse['rise_end_ns'], 'association': 'unmatched'}
        triggers.append(trigger)
    triggers.sort(key=lambda t: t['trigger_time_ns'])
    assign(rows, triggers, mask)
    for row in rows:
        if row['classification'] == 'unique_matched':
            row['energy'] = measured_energy(row, triggers[row['trigger_index']])
    counts = Counter(trigger['association'] for trigger in triggers)
    summary = summarize(rows, triggers)
    energy = [t['slow_energy_keV'] for t in triggers if t['slow_energy_keV'] is not None]
    REQUIRE(sum(counts.values()) == len(triggers) and counts['unique_matched'] == summary[0]['unique_matched'],
            'Trigger association must agree with deposit assignments')
    resource = {'preparation_wall_s': prepared_s, 'adc_and_trigger_wall_s': elapsed,
                'total_wall_s': time.perf_counter() - began, 'prepared_unique_native_array_bytes': native_bytes}
    sources = ('gegi_source_exposure.py', 'gegi_exposure_stream.py', 'gegi_source_pileup.py', 'gegi_source_clock.py',
               'gegi_pulse_stream.py', 'gegi_digital_readout.py', 'gegi_signal_reconstruction.py', 'gegi_event_store.py')
    return {
        'kind': 'gegi_saved_two_source_exposure_v1', 'status': 'completed', 'parity': checked,
        'design': {'clock_view': VIEW, 'source_activities_bq': {source: clock['sources'][source]['clock']['activity_bq']
                                                               for source in SOURCES},
                   'clock_seed': clock['design']['seed'], 'noise_seed': NOISE_SEED, 'adc_phase_ns': PHASE_NS,
                   'sample_period_ns': DT_NS, 'nominal_noise_rms_v': digital._PROFILE['optional_noise_rms_V'],
                   'block_samples': BLOCK_SAMPLES, 'any_source_close_neighbor_ns': NEAR_NS,
                   'scope': 'Fixed saved empirical exposure. The front end is reset at t=0 and admits Ge arrivals '
                            'beginning in the exposure. Pre-window Ge currents are outside this modeled acquisition, '
                            'even though delayed Ge deposits from earlier parents are retained.',
                   'unknown_mask': 'Unverified native responses are missing data. Mask their input support through '
                                   'the last Ge deposit plus the nominal 1000 ns drift cap and one native bin, and '
                                   'both exponential tails until their temporal sum is at most 0.25 ADC LSB. '
                                   'Extend by the full digital context. The residual bound assumes the nominal '
                                   'finite support and bounded Ramo weights. It does not certify identical ADC codes.',
                   'matching': 'Reconstruct triggers with no deposit times or counts. Associate afterwards using '
                               'time relative to isolated waveform controls or the bounded onset gate and '
                               'observed rise support. Maximize one-to-one match count, then compatible strip '
                               'evidence. A shared lone trigger is merged or unresolved. Equal-best assignments '
                               'stay ambiguous. Missing-energy flags can co-occur.',
                   'energy': 'ADC slow estimates retain the fixed pulser calibration. Truth bias uses Ge '
                             'deposited energy; isolated bias requires a single agreeing reference strip pair. '
                             'Depth and lateral position are unscored in this exposure.',
                   'remaining_limit': 'Full exposure trigger and energy efficiency are unidentified where '
                                      'native history is incomplete. Report measured qualified time and counts.',
                   'new_transport_calls': 0, 'new_drift_calls': 0},
        'exposure': {'clock_live_time_ns': live, 'qualified_adc_live_time_ns': qualified_ns,
                     'total_live_adc_samples': live // DT_NS, 'qualified_live_adc_samples': qualified_ns // DT_NS,
                     'excluded_intervals_ns': mask, 'masked_live_time_ns': live - qualified_ns,
                     'maximum_unseen_tail_lsb': prior._MAX_UNSEEN_LSB,
                     'sources': {source: data['counts'] for source, data in view['sources'].items()},
                     'absolute_whole_exposure_efficiency': None},
        'summary': summary,
        'trigger_summary': {'qualified_triggers': len(triggers), 'qualified_slow_energies': len(energy),
                            **{key: counts[key] for key in ('unique_matched', 'merged', 'ambiguous', 'unmatched',
                                                           'history_boundary_unknown')},
                            'qualified_trigger_rate_per_s': len(triggers) * 1e9 / qualified_ns,
                            'qualified_slow_energy_rate_per_s': len(energy) * 1e9 / qualified_ns,
                            'missing_energy_flags': dict(Counter(flag for t in triggers if t['slow_energy_keV'] is None
                                                                for flag in set(t['flags'])))},
        'slow_spectrum': spectrum(energy),
        'deposits': rows, 'triggers': triggers, 'resources': resource,
        'input_sha256': hashes, 'source_sha256': {f'tools/{name}': sha((ROOT / 'tools' / name).read_bytes()) for name in sources},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parity-only', action='store_true')
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    if arguments.parity_only:
        print(json.dumps(run(parity_only=True), indent=2))
        return
    REQUIRE(arguments.output is not None, '--output is required for the exposure')
    output = arguments.output.resolve()
    REQUIRE(output.is_relative_to(LOCAL) and not output.exists(), 'Use a new result path under .local/gegi-source-clock')
    report = run(parity_only=False)
    with output.open('xb') as handle:
        handle.write(encoded(report) + b'\n')
    print(json.dumps({k: report[k] for k in ('parity', 'trigger_summary', 'resources')}, indent=2))


if __name__ == '__main__':
    main()
