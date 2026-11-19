"""Compare saved GeGI timing diagnostics against the independent simulation clock."""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import gzip
from io import BytesIO
import json
import math
from pathlib import Path
import random

import numpy as np

import gegi_digital_readout as digital
import gegi_dual_source as dual
from gegi_event_store import encoded, sha
import gegi_heldout_pairing_study as heldout
import gegi_pulse_stream as pulse
import gegi_source_exposure as association
import gegi_source_library as library
from gegi_trigger_windows import RELATIVE_NS


ROOT = heldout.ROOT
LOCAL = ROOT / '.local/gegi-joint-two-site'
EXPOSURE = LOCAL / 'independent-1s-exposure.json.gz'
MEASURED = LOCAL / 'independent-1s-measured-overlap.json'
OUTPUT = LOCAL / 'independent-1s-overlap-reference.json.gz'
ACQUISITIONS = ROOT / '.local/gegi-dual-source'
NEAR_NS = (300, 1000, association.NEAR_NS)
SUPPORTS = {
    'adc': (int(RELATIVE_NS[0]), int(RELATIVE_NS[-1])),
    'fast': (-(pulse._QUIET_SAMPLES - 1 + pulse._FAST_SAMPLES) * digital._DT, pulse._FAST_NS),
    'slow': (pulse._SLOW_NS[0] - (pulse._SLOW_LOOKBACK + 1) * digital._DT, pulse._SLOW_NS[1]),
}
REQUIRE = heldout.REQUIRE


def bound(path, hashes, expected=None):
    data = path.read_bytes()
    digest = sha(data)
    REQUIRE(expected is None or digest == expected, f'Input bytes differ from the exposure: {path.name}')
    hashes[path.relative_to(ROOT).as_posix()] = digest
    return data


def parent_times(pack, source, duration_ns, rows):
    """Recover discarded zero-mark times with the frozen single-layer draw order."""
    REQUIRE(source['clock_layers'] == 1, 'This study uses the saved single-layer clocks')
    rng = random.Random(source['scheduled_parent_seed'])
    size = pack.metadata['original']['initial_primaries']
    rate = source['activity_bq'] / size / 1e9
    parents, recovered, occurrence_times = [], {}, {}
    for ordinal in range(size):
        mark = pack.marks.get(ordinal)
        groups = mark['groups'] if mark else []
        for interval, (begin, end) in enumerate(library._parent_support(groups, duration_ns)):
            width = end - begin
            for i in range(library._poisson(rate * width, rng)):
                offset = width * rng.random()
                time = begin + offset
                if 0 <= time < duration_ns:
                    parents.append((time, bool(groups)))
                if not groups:
                    continue
                occurrence_id = f'{ordinal}.{interval}.{i}'
                occurrence_times[occurrence_id] = time
                for group in groups:
                    delay = group['first_deposit_since_parent_ns']
                    onset = (begin + delay) + offset
                    if 0 <= onset < duration_ns:
                        last = onset + (group['last_deposit_since_parent_ns'] - delay)
                        recovered[(occurrence_id, group['group_id'])] = (onset, last)
    REQUIRE(recovered == {(r['occurrence_id'], r['group_id']):
                          (r['first_ge_deposit_ns'], r['last_ge_deposit_ns']) for r in rows},
            'Recovered parent clock and canonical absolute Ge deposit times differ')
    REQUIRE(len(parents) == source['counts']['parents']
            and sum(marked for _, marked in parents) == source['counts']['marked_nonzero_parents'],
            'Recovered live parent census differs')
    for row in rows:
        row['parent_decay_time_ns'] = occurrence_times[row['occurrence_id']]
    return parents


def coverage(bounds, duration_ns, mask):
    lo, hi = bounds
    return 0 <= lo <= hi < duration_ns and all(hi < a or lo >= b for a, b in mask)


def other_status(indices, anchor, complete, unavailable=()):
    """Ask whether an extra group is supported even if the primary is uncertain."""
    if len(indices) >= 2 or (anchor is not None and any(i != anchor for i in indices)):
        return 'additional'
    if not complete:
        return 'incomplete'
    if unavailable:
        return 'native_unavailable'
    if indices and anchor is None:
        return 'anchor_unknown'
    return 'absent'


def native_comparison(bounds, times, rows, candidates, packs, cache, anchor, complete, collectors):
    lo, hi = bounds
    active, collector_active, code_swing, unavailable, evidence = [], [], [], [], []
    for i in candidates:
        row = rows[i]
        onset = row['first_ge_deposit_ns']
        if row['last_ge_deposit_ns'] + dual.NATIVE_DRIFT_CAP_NS + 1 <= lo:
            continue
        if not row['native_available']:
            unavailable.append(i)
            continue
        native, status, digest = library.read_native(packs[row['source']], row, cache)
        REQUIRE(native is not None and status == row['native_status'] and digest == row['metadata_sha256'],
                'Signed native pulse differs from the matched metadata')
        rel = native.time_ns + onset
        touching = (rel[:-1] < hi) & (rel[1:] > lo)
        contacts = np.flatnonzero(np.any(native.drive_V[0, :, :-1][:, touching] != 0, axis=1)) + 1
        if not contacts.size:
            continue
        voltage = np.zeros((len(digital.CONTACT_IDS), len(times)))
        inside = times >= onset
        voltage[:, inside] = pulse._sample_pulse(native, times[inside] - onset)
        peak_to_peak_codes = np.ptp(voltage, axis=1) / digital._LSB_V
        active.append(i)
        if collectors.intersection(contacts):
            collector_active.append(i)
        if peak_to_peak_codes.max() >= 1:
            code_swing.append(i)
        evidence.append(dict(group_index=i, active_contact_ids=contacts.tolist(),
                             maximum_preamp_swing_adc_codes=float(peak_to_peak_codes.max()),
                             maximum_collector_swing_adc_codes=max(float(peak_to_peak_codes[c-1]) for c in collectors)))
    return dict(
        native_current_adc=other_status(active, anchor, complete, unavailable),
        collector_native_current_adc=other_status(collector_active, anchor, complete, unavailable),
        preamp_one_code_swing_adc=other_status(code_swing, anchor, complete, unavailable),
        native_current_components=evidence, unavailable_native_group_indices=unavailable,
    )


def parent_totals(parent_arrivals, parent_clock, bounds, anchor_time=None):
    lo = bisect_left(parent_clock, bounds[0])
    hi = bisect_right(parent_clock, bounds[1])
    marked = sum(parent_arrivals[i][1] for i in range(lo, hi))
    totals = dict(all=hi-lo, archived_nonzero_mark=marked, archived_zero_mark=hi-lo-marked)
    if anchor_time is None:
        return totals
    index = bisect_left(parent_clock, anchor_time, lo, hi)
    anchor = int(index < hi and parent_clock[index] == anchor_time)
    REQUIRE(not anchor or parent_arrivals[index][1], 'The graph anchor parent has an inconsistent clock mark')
    return dict(all=hi-lo-anchor, archived_nonzero_mark=marked-anchor, archived_zero_mark=hi-lo-marked)


def trigger_reference(measured, trigger, link, rows, group_clock, parent_arrivals, parent_clock,
                      duration_ns, mask, packs, cache):
    time = trigger['trigger_time_ns']
    plausible = [i for i, onset in enumerate(group_clock) if association.related(onset, rows[i], trigger)]
    anchor = link.get('deposit_index')
    anchor_time = rows[anchor]['parent_decay_time_ns'] if anchor is not None else None
    REQUIRE(anchor is None or anchor in plausible, 'Timing assignment is outside its candidate graph')
    result = {key: measured[key] for key in ('block', 'trigger_index', 'trigger_time_ns', 'two_strip_ordinal',
                                            'energy_keV', 'energy_window', 'allowed_hypotheses', 'hypotheses',
                                            'projected_mass', 'unresolved_mass')}
    result.update(timing_association=link['association'], timing_link_scope=link['truth_link_scope'],
                  timing_anchor_group_index=anchor, plausible_group_indices=plausible)
    group_windows = {}
    for gate, (first, last) in SUPPORTS.items():
        bounds = (time + first, time + last)
        lo, hi = bisect_left(group_clock, bounds[0]), bisect_right(group_clock, bounds[1])
        indices = list(range(lo, hi))
        complete = coverage(bounds, duration_ns, mask)
        REQUIRE(complete == measured['supports'][gate]['fully_qualified'],
                f'Measured and reference {gate} time coverage differ')
        group_windows[gate] = dict(
            window_ns=bounds, qualified=complete, group_indices=indices,
            additional_onset=other_status(indices, anchor, complete),
            parent_marks=parent_totals(parent_arrivals, parent_clock, bounds),
            distinct_parent_marks=(parent_totals(parent_arrivals, parent_clock, bounds, anchor_time)
                                   if anchor_time is not None else None),
        )
    result['group_windows'] = group_windows
    adc = group_windows['adc']
    collectors = set(trigger['x_collecting_strips'] + trigger['y_collecting_strips'])
    candidates = range(bisect_right(group_clock, adc['window_ns'][1]))
    result.update(native_comparison(adc['window_ns'], time + RELATIVE_NS, rows, candidates, packs, cache,
                                    anchor, adc['qualified'], collectors))
    nearest = None
    if anchor is not None:
        a = rows[anchor]
        nearest = min(
            (max(0., row['first_ge_deposit_ns'] - a['last_ge_deposit_ns'],
                 a['first_ge_deposit_ns'] - row['last_ge_deposit_ns']), i)
            for i, row in enumerate(rows) if i != anchor
        )
    result['nearest_other_group'] = (
        dict(interval_gap_ns=nearest[0], group_index=nearest[1],
             same_parent=rows[nearest[1]]['source'] == rows[anchor]['source'] and
             rows[nearest[1]]['occurrence_id'] == rows[anchor]['occurrence_id'])
        if nearest else None
    )
    result['inclusive_half_widths'] = {str(width): dict(
        parent_marks=parent_totals(parent_arrivals, parent_clock, (time-width, time+width)),
        distinct_parent_marks=(parent_totals(parent_arrivals, parent_clock, (time-width, time+width), anchor_time)
                               if anchor_time is not None else None),
        group_indices=list(range(bisect_left(group_clock, time-width), bisect_right(group_clock, time+width))),
        live_clock_complete=0 <= time-width and time+width < duration_ns,
        anchored_gap_complete=anchor is not None and rows[anchor]['first_ge_deposit_ns'] >= width
        and rows[anchor]['last_ge_deposit_ns'] + width < duration_ns,
    ) for width in NEAR_NS}
    result['measured'] = {gate: measured['supports'][gate]['status'] for gate in SUPPORTS}
    result['measured']['secondary_adc_rise'] = measured['waveform']['secondary_rearmed_coincident_rise']
    return result


def compare_block(provenance, measured, hashes, source_hashes):
    folder = ACQUISITIONS / provenance['name']
    report = json.loads(bound(folder / 'report.json', hashes, provenance['report_sha256']))
    plane = json.loads(gzip.decompress(bound(folder / 'plane.json.gz', hashes, provenance['plane_sha256'])))
    exposure, receipt, triggers = (report[key] for key in ('exposure', 'receipt', 'triggers'))
    mask = exposure['excluded_intervals_ns']
    duration = exposure['clock_live_time_ns']
    REQUIRE(report['kind'] == dual.KIND and report['status'] == 'completed'
            and sha(encoded(dict(counts=report['counts'], spectra=report['spectra'], triggers=triggers,
                                 mask=mask))) == receipt['observed_result_sha256']
            and receipt['library_sha256'] == source_hashes['tools/gegi_source_library.py']
            and receipt['pulse_stream_sha256'] == source_hashes['tools/gegi_pulse_stream.py']
            and receipt['digital_profile_sha256'] == digital.PROFILE_SHA256
            and receipt['digital_timing_sha256'] == digital.TIMING_SHA256,
            'The frozen acquisition or its original clock and pulse sources differ')
    adc_data = bound(folder / 'two-strip-adc.npz', hashes, provenance['adc_windows_sha256'])
    expected = heldout.measured_candidates(report)
    with np.load(BytesIO(adc_data), allow_pickle=False) as adc:
        REQUIRE(adc['report_sha256'].item() == provenance['report_sha256']
                and adc['known_component_adc_sha256'].item() == receipt['known_component_adc_sha256']
                and adc['digital_profile_sha256'].item() == receipt['digital_profile_sha256']
                and adc['digital_timing_sha256'].item() == receipt['digital_timing_sha256']
                and np.array_equal(adc['relative_time_ns'], RELATIVE_NS)
                and adc['trigger_time_ns'].tolist() == [t['trigger_time_ns'] for t in expected.values()],
                'The saved ADC timing, report or two-strip roster differ')
        adc_statuses = adc['window_status'].tolist()

    sources = tuple((folder / s['input_directory']['relative_to_report_directory']).resolve() for s in report['sources'])
    rows, packs, derived_mask, _ = heldout.scheduled_inputs(report, sources, hashes)
    REQUIRE(derived_mask == mask, 'The original ADC history masks differ')
    group_clock = [r['first_ge_deposit_ns'] for r in rows]
    parents = sorted(p for source in report['sources'] for p in parent_times(
        packs[source['key']], source, duration, [r for r in rows if r['source'] == source['key']]))
    parent_clock = [p[0] for p in parents]
    links = heldout.link_groups(rows, triggers, mask)
    result, cache = [], {}
    for ordinal, ((i, candidate), row, saved, adc_status) in enumerate(
            zip(expected.items(), measured, plane['triggers'], adc_statuses, strict=True), 1):
        key = (i+1, candidate['trigger_time_ns'], ordinal, candidate['energy_keV'])
        fields = ('trigger_index', 'trigger_time_ns', 'two_strip_ordinal', 'energy_keV')
        REQUIRE(key == tuple(row[k] for k in fields) == tuple(saved[k] for k in fields)
                and candidate['rise_end_ns'] == row['rise_end_ns']
                and all(row[k] == saved[k] for k in ('allowed_hypotheses', 'hypotheses', 'projected_mass',
                                                      'unresolved_mass'))
                and (adc_status == 'captured') == row['supports']['adc']['fully_qualified'],
                'Report, measured diagnostic, ADC and plane trigger identities differ')
        result.append(trigger_reference(row, triggers[i], links[i], rows, group_clock, parents, parent_clock,
                                        duration, mask, packs, cache))
    return dict(provenance=provenance, counts=report['counts'], clock_live_time_ns=duration,
                qualified_adc_live_time_ns=exposure['qualified_adc_live_time_ns'],
                parents=parent_totals(parents, parent_clock, (0, duration)),
                scheduled_group_associations=dict(Counter(r['classification'] for r in rows)),
                all_trigger_associations=dict(Counter(r['association'] for r in links)),
                windows=summary(result, tuple(plane['layers'])),
                group_ledger=[{k: v for k, v in row.items() if k != 'isolated_triggers'} for row in rows],
                events=result)


def tabulate(events, measured, classify):
    table = {}
    for row in events:
        left, right = row['measured'][measured], classify(row)
        if isinstance(left, bool):
            left = 'recorded' if left else 'not_recorded'
        table.setdefault(left if left is not None else 'incomplete', Counter())[right] += 1
    return table


def row_summary(events):
    parent_keys = ('all', 'archived_nonzero_mark', 'archived_zero_mark')
    windows = {gate: dict(Counter(row['group_windows'][gate]['additional_onset'] for row in events))
               for gate in SUPPORTS}
    widths = {}
    for width in NEAR_NS:
        cards = [r['inclusive_half_widths'][str(width)] for r in events]
        qualified = [r for r, card in zip(events, cards, strict=True) if card['anchored_gap_complete']]
        near = [r['nearest_other_group'] for r in qualified if r['nearest_other_group']['interval_gap_ns'] <= width]
        widths[str(width)] = dict(
            anchored_gap_denominator=len(qualified), anchored_additional_groups=len(near),
            anchored_same_parent_nearest=sum(r['same_parent'] for r in near),
            live_clock_denominator=sum(card['live_clock_complete'] for card in cards),
            trigger_centered_two_or_more_group_onsets=sum(len(card['group_indices']) >= 2 for card in cards),
            trigger_centered_with_parent_marks={k: sum(card['parent_marks'][k] > 0 for card in cards)
                                                for k in parent_keys},
            trigger_centered_distinct_parent_denominator=sum(card['distinct_parent_marks'] is not None
                                                            and card['live_clock_complete'] for card in cards),
            trigger_centered_with_distinct_parent_marks={k: sum(
                card['distinct_parent_marks'] is not None and card['live_clock_complete']
                and card['distinct_parent_marks'][k] > 0 for card in cards) for k in parent_keys},
        )
    natives = ('native_current_adc', 'collector_native_current_adc', 'preamp_one_code_swing_adc')
    return dict(
        rows=len(events), projected_mass=math.fsum(r['projected_mass'] for r in events),
        unresolved_mass=math.fsum(r['unresolved_mass'] for r in events),
        timing_associations=dict(Counter(r['timing_association'] for r in events)),
        group_onset_adc=windows['adc'], group_onset_fast=windows['fast'], group_onset_slow=windows['slow'],
        adc_with_parent_marks={k: sum(r['group_windows']['adc']['parent_marks'][k] > 0 for r in events)
                               for k in parent_keys},
        adc_distinct_parent_denominator=sum(r['group_windows']['adc']['distinct_parent_marks'] is not None
                                            and r['group_windows']['adc']['qualified'] for r in events),
        adc_with_distinct_parent_marks={k: sum(r['group_windows']['adc']['distinct_parent_marks'] is not None
                                               and r['group_windows']['adc']['qualified']
                                               and r['group_windows']['adc']['distinct_parent_marks'][k] > 0
                                               for r in events) for k in parent_keys},
        native_adc={key: dict(Counter(r[key] for r in events)) for key in natives},
        inclusive_half_widths_ns=widths,
        crosstabs={**{f'{gate}_vs_group_onset': tabulate(
            events, gate, lambda r: r['group_windows'][gate]['additional_onset']) for gate in SUPPORTS},
            'secondary_rise_vs_group_onset': tabulate(events, 'secondary_adc_rise',
                                                    lambda r: r['group_windows']['adc']['additional_onset']),
            'secondary_rise_vs_native_current': tabulate(events, 'secondary_adc_rise',
                                                        lambda r: r['native_current_adc'])},
    )


def summary(events, labels):
    REQUIRE(all(row['energy_window'] in labels[1:] for row in events), 'Measured energy windows must partition the roster')
    return {name: row_summary(events if name == 'all' else [r for r in events if r['energy_window'] == name])
            for name in labels}


def view(blocks, labels):
    all_trigger_associations = Counter()
    for block in blocks:
        all_trigger_associations.update(block['all_trigger_associations'])
    return dict(qualified_triggers=sum(b['counts']['qualified_triggers'] for b in blocks),
                all_trigger_associations=dict(all_trigger_associations),
                qualified_adc_live_time_ns=math.fsum(b['qualified_adc_live_time_ns'] for b in blocks),
                clock_live_time_ns=math.fsum(b['clock_live_time_ns'] for b in blocks),
                initial_parents=sum(b['counts']['initial_parents_in_live_time'] for b in blocks),
                scheduled_ge_groups=sum(b['counts']['deposit_groups'] for b in blocks),
                unavailable_groups=sum(b['counts']['native_unavailable_groups'] for b in blocks),
                right_censored_groups=sum(b['counts']['right_censored_deposit_groups'] for b in blocks),
                excluded_history_groups=sum(b['counts']['prehistory_unqualified_groups'] for b in blocks),
                zero_deposit_parent_marks=sum(b['parents']['archived_zero_mark'] for b in blocks),
                windows=summary([row for b in blocks for row in b['events']], labels))


def run(measured_path):
    hashes = {}
    implementation_paths = (Path(__file__), *(
        ROOT / 'tools' / name for name in ('gegi_source_library.py', 'gegi_source_exposure.py',
        'gegi_heldout_pairing_study.py', 'gegi_trigger_windows.py', 'gegi_dual_source.py',
        'gegi_pulse_stream.py', 'gegi_digital_readout.py', 'gegi_event_store.py')))
    current_sources = lambda: {p.relative_to(ROOT).as_posix(): library._hash(p) for p in implementation_paths}
    sources = current_sources()
    exposure = json.loads(gzip.decompress(bound(EXPOSURE, hashes)))
    measured = json.loads(bound(measured_path, hashes))
    keys = ('name', 'report_sha256', 'plane_sha256', 'adc_windows_sha256', 'known_component_adc_sha256')
    REQUIRE(measured['kind'] == 'gegi_measured_shared_clock_overlap_v1'
            and measured['source_pool_sha256'] == hashes[EXPOSURE.relative_to(ROOT).as_posix()]
            and measured['definitions']['support_relative_ns'] == {key: list(v) for key, v in SUPPORTS.items()}
            and all(all(a[key] == b[key] for key in keys)
                    for a, b in zip(measured['inputs'], exposure['inputs'], strict=True)),
            'The measured study and simulated clock use different scopes or source receipts')
    blocks = [compare_block(provenance, [r for r in measured['events'] if r['block'] == provenance['name']],
                            hashes, sources) for provenance in exposure['inputs']]
    REQUIRE(len(blocks) == 4 and sum(len(b['events']) for b in blocks) == len(measured['events']),
            'The measured study must cover the four original blocks exactly once')
    labels = tuple(exposure['views']['full']['layers'])
    views = {key: view(items, labels) for key, items in (
             ('first_half', blocks[:2]), ('second_half', blocks[2:]), ('full', blocks))}
    for key, record in views.items():
        frozen = exposure['views'][key]
        REQUIRE(record['qualified_triggers'] == frozen['selection']['qualified_triggers']
                and all(row['rows'] == frozen['layers'][name]['triggers'] and
                        math.isclose(row['projected_mass'], frozen['layers'][name]['projected_mass'], abs_tol=1e-9) and
                        math.isclose(row['unresolved_mass'], frozen['layers'][name]['unresolved_mass'], abs_tol=1e-9)
                        for name, row in record['windows'].items()),
                'Reference population differs from the saved exposure and line windows')
    REQUIRE(sources == current_sources(), 'Implementation changed during reference calculation')
    return dict(kind='gegi_independent_clock_overlap_reference_v1', status='completed',
                design=dict(
                    clock='Each block uses its own saved lab clock in ns shared by both sources, ADC, and transport. '
                          'There is no comparison across reset block boundaries.',
                    in_window='Inclusive endpoints at the first and last absolute sample in each finite support. '
                              'Additional means at least two observed-in-simulation groups on that support, or one '
                              'distinct from the unique timing-graph candidate. A single candidate without a unique '
                              'match is uncertain. Ge groups include delayed daughters from earlier parents. '
                              'Exposure-start electronics reset and qualified history rules remain in force.',
                    near='Compare inclusive 300/1000/6000 ns neighboring scheduled Ge deposit-interval gaps around '
                         'a timing-graph anchor, and count parent marks and Ge group onsets in the same symmetric '
                         'widths around the absolute trigger stamp. All marks include the graph anchor’s parent '
                         'if present, while distinct marks exclude it.',
                    pulse='Check signed source-component current within the ADC window on all 34 contacts and separately '
                          'on the four collectors. For current-bearing components, measure preamp swing on the local '
                          'sample clock at the nominal analog gain. One code is an amplitude scale and supplies no ADC '
                          'detectability or trigger guarantee. Old free tails are outside the native-current definition.',
                    scope='Both association and extra-source statistics use saved simulation references. The measured '
                          'rearm and rise flags were frozen before comparison. No exclusions, threshold training, '
                          'new transport, new drift or full ADC replay. Distinct groups can have the same decay parent.',
                    supports_ns=SUPPORTS, inclusive_half_widths_ns=NEAR_NS, preamp_volts_per_code=digital._LSB_V),
                input_sha256=hashes, source_sha256=sources, views=views, blocks=blocks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measured', type=Path, default=MEASURED)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = run(args.measured.resolve())
    with args.output.open('xb') as target:
        target.write(gzip.compress(encoded(result) + b'\n', mtime=0))
    print(json.dumps(result['views']['full'], indent=2))


if __name__ == '__main__':
    main()
