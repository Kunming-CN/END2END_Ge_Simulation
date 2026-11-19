"""Compare recorded GeGI rise intervals and saved ADC windows on the shared clock."""

import argparse
from bisect import bisect_left, bisect_right
import gzip
import io
import json
from math import fsum, isclose
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import gegi_digital_readout as digital
import gegi_pulse_stream as pulse
from gegi_continuous_plane import LINE_ENERGIES_KEV
from gegi_joint_imaging import spectral_membership
from gegi_plane_footprint_study import ACQUISITIONS, V1_POOL, V1_POOL_SHA, VIEWS
from gegi_pool_measured_planes import LAYER_COUNTS, LAYER_MASS, SELECTION_COUNTS, digest, require
from gegi_trigger_windows import ARCHIVE_NAME, RELATIVE_NS, is_two_strip
from gegi_window_activity import analyze_window


DT = digital._DT
ADC = (int(RELATIVE_NS[0]), int(RELATIVE_NS[-1]))
FAST_GATE = digital._PROFILE['fast_area_gate_ns']
FAST = ((1-pulse._QUIET_SAMPLES-pulse._FAST_SAMPLES)*DT, FAST_GATE[1])
SLOW_GATE = digital._PROFILE['slow_plateau_gate_ns']
SLOW = (SLOW_GATE[0]-(pulse._SLOW_LOOKBACK+1)*DT, SLOW_GATE[1])
SUPPORTS = {'adc': ADC, 'fast': FAST, 'slow': SLOW}
CONE_ACCOUNTING = (*LAYER_COUNTS, *LAYER_MASS)
MASSES = ('allowed_order_mass', 'unassigned_without_pairing_mass', 'unassigned_without_allowed_order_mass',
          'unassigned_without_projection_mass')
STATUSES = ('recorded_overlap', 'no_recorded_overlap', 'incomplete_coverage')


def read_bytes(path, expected):
    data = path.read_bytes()
    require(digest(data) == expected, f'Bound input changed: {path.parent.name}/{path.name}')
    return data


def covered(first, last, exposure):
    # Supports have inclusive sample endpoints. Qualification masks are half-open.
    outside = first < 0 or last >= exposure['clock_live_time_ns']
    gaps = [[lo, hi] for lo, hi in exposure['excluded_intervals_ns'] if lo <= last and hi > first]
    return not (outside or gaps), outside, gaps


def rise_record(trigger_index, row, reference):
    start, end = row['trigger_time_ns'], row['rise_end_ns']
    return dict(trigger_index=trigger_index, trigger_time_ns=start, rise_end_ns=end,
                first_active_offset_ns=start+DT-reference, last_active_offset_ns=end-reference)


def support_record(extent, t0, exposure, roster, starts, ends, index):
    lo, hi = (t0+offset for offset in extent)
    complete, outside, gaps = covered(lo, hi, exposure)
    first, stop = bisect_left(ends, lo), bisect_right(starts, hi)
    rises = [rise_record(i+1, roster[i], t0) for i in range(first, stop) if i != index]
    return dict(status=STATUSES[0] if rises else STATUSES[1] if complete else STATUSES[2],
                fully_qualified=complete, outside_live_time=outside, intersecting_excluded_intervals_ns=gaps,
                other_recorded_rises=rises)


def cone_record(saved):
    pairs = saved['pairings']
    orders = [order for pair in pairs for order in pair['orders']]
    projected = [order for order in orders if order['status'] == 'projected']
    projected_mass = fsum(order['nominal_mass'] for order in projected)
    unassigned = (float(not pairs), fsum(pair['nominal_mass'] for pair in pairs if not pair['orders']),
                  fsum(order['nominal_mass'] for order in orders if order['status'] != 'projected'))
    require((len(orders), len(projected), projected_mass) ==
            tuple(saved[key] for key in ('allowed_hypotheses', 'hypotheses', 'projected_mass')) and
            isclose(fsum(unassigned), saved['unresolved_mass'], abs_tol=1e-12) and
            isclose(fsum((projected_mass, *unassigned)), 1., abs_tol=1e-12), 'Saved cone accounting does not close')
    return dict(
        **{key: saved[key] for key in ('allowed_hypotheses', 'hypotheses', *LAYER_MASS)},
        **dict(zip(MASSES, (fsum(order['nominal_mass'] for order in orders), *unassigned), strict=True)),
        pairings=[{key: pair[key] for key in ('index', 'cells', 'nominal_mass')} | dict(
            orders=[{key: order[key] for key in ('order', 'nominal_mass', 'status')} for order in pair['orders']])
            for pair in pairs],
    )


def event_record(name, index, row, saved, ordinal, label, window, exposure, roster, starts, ends):
    t0, end = row['trigger_time_ns'], row['rise_end_ns']
    waveform_usable = window is not None and not window['saturated_contact_ids']
    groups = window['groups'] if window is not None else []
    primary = next((g for g in groups if g['trigger_reference_ns'] == 0. and g['coincident']
                    and g['rearm_visible']), None)
    reproducible = waveform_usable and primary is not None
    full_primary = bool(reproducible and primary['last_active_ns'] == end-t0 and primary['right_quiet_visible'])
    secondary = (any(g is not primary and g['coincident'] and g['rearm_visible'] for g in groups)
                 if reproducible else None)
    pairings = row['two_strip_pairings']
    return dict(
        block=name, trigger_index=index+1, trigger_time_ns=t0, two_strip_ordinal=ordinal, rise_end_ns=end,
        energy_keV=row['energy_keV'], energy_window=label, **cone_record(saved),
        x_collecting_strips=row['x_collecting_strips'], y_collecting_strips=row['y_collecting_strips'],
        recorded_trigger_flags=row['flags'], pairing_flags=pairings['flags'],
        collector_neighbor_fast_quality_issue=any(
            c[side] is not None and bool(c[side]['flags']) for c in pairings['collectors'] for side in ('low', 'high')),
        nearest_recorded_rises={
            side: rise_record(i+1, roster[i], t0) if 0 <= i < len(roster) else None
            for side, i in (('previous', index-1), ('next', index+1))},
        supports={label: support_record(extent, t0, exposure, roster, starts, ends, index)
                  for label, extent in SUPPORTS.items()},
        waveform=dict(
            primary_reference_reproduced=reproducible, primary_interval_reproduced=full_primary,
            secondary_rearmed_coincident_rise=secondary, activity_groups=groups,
            saturated_contact_ids=None if window is None else window['saturated_contact_ids']),
    )


def read_block(item):
    name = item['name']
    folder = ACQUISITIONS/name
    report = json.loads(read_bytes(folder/'report.json', item['report_sha256']))
    plane = json.loads(gzip.decompress(read_bytes(folder/'plane.json.gz', item['plane_sha256'])))
    archive = read_bytes(folder/ARCHIVE_NAME, item['adc_windows_sha256'])
    receipt, exposure, design = (report[key] for key in ('receipt', 'exposure', 'design'))
    profile = design['trigger_profile']['id']
    require(report['status'] == 'completed' and design['adc_phase_ns'] == 0 and design['sample_period_ns'] == DT
            and exposure['clock_live_time_ns'] == 250_000_000 and design['trigger_profile'] == item['trigger_profile']
            == receipt['trigger_profile'] == pulse.trigger_profile_definition(profile)
            and receipt['digital_profile_sha256'] == item['digital_profile_sha256'] == digital.PROFILE_SHA256
            and receipt['digital_timing_sha256'] == item['digital_timing_sha256'] == digital.TIMING_SHA256,
            f'Unexpected recorded acquisition profile: {name}')
    require(plane['input_sha256']['acquisition'] == item['report_sha256']
            and plane['input_sha256'].get('adc_windows', item['adc_windows_sha256']) == item['adc_windows_sha256'],
            f'Plane bindings differ: {name}')
    roster = report['triggers']
    require(len(roster) == report['counts']['qualified_triggers'] == plane['selection']['qualified_triggers']
            and sum(row['energy_keV'] is not None for row in roster) == report['counts']['qualified_energies']
            == plane['selection']['qualified_energies'], f'Recorded census differs: {name}')
    starts = [row['trigger_time_ns']+DT for row in roster]
    ends = [row['rise_end_ns'] for row in roster]
    require(all(start <= end and start % DT == end % DT == 0 and covered(start-DT, end, exposure)[0]
                for start, end in zip(starts, ends, strict=True)) and
            all(end < start for end, start in zip(ends[:-1], starts[1:], strict=True)),
            f'Recorded rise intervals are invalid or overlap each other: {name}')
    selected = [(i, row) for i, row in enumerate(roster) if is_two_strip(row)]
    labels = spectral_membership([SimpleNamespace(energy_keV=row['energy_keV']) for _, row in selected], LINE_ENERGIES_KEV)
    require(tuple(plane['layers']) == ('all', *labels), f'Saved energy-window names differ: {name}')
    events, representative = [], None
    with np.load(io.BytesIO(archive), allow_pickle=False) as adc:
        require(adc['report_sha256'].item() == item['report_sha256'] and all(
            adc[key].item() == receipt[key] == item[key] for key in
            ('known_component_adc_sha256', 'digital_profile_sha256', 'digital_timing_sha256'))
            and np.array_equal(adc['relative_time_ns'], RELATIVE_NS)
            and np.array_equal(adc['contact_ids'], digital.CONTACT_IDS)
            and adc['volts_per_code'].item() == digital._LSB_V
            and np.array_equal(adc['trigger_time_ns'], [row['trigger_time_ns'] for _, row in selected]),
            f'ADC binding or sample convention differs: {name}')
        statuses, ordinals, codes = (adc[key] for key in ('window_status', 'two_strip_ordinal', 'adc_codes'))
        baseline = adc['acquisition_baseline_v']
        require(len(statuses) == len(selected) and np.array_equal(ordinals, np.flatnonzero(statuses == 'captured')+1)
                and codes.shape == (len(ordinals), len(digital.CONTACT_IDS), len(RELATIVE_NS)),
                f'ADC capture roster differs: {name}')
        captured = dict(zip(ordinals, codes, strict=True))
        for ordinal, ((i, row), saved, status) in enumerate(zip(selected, plane['triggers'], statuses, strict=True), 1):
            identities = ('trigger_index', 'two_strip_ordinal', 'trigger_time_ns', 'energy_keV')
            require(tuple(saved[key] for key in identities) == (i+1, ordinal, row['trigger_time_ns'], row['energy_keV'])
                    and saved.get('adc_window_status', status) == status, f'ADC, report and cone roster differ: {name}')
            label = next(label for label, mask in labels.items() if mask[ordinal-1])
            code = captured.get(ordinal)
            window = analyze_window(code, baseline, RELATIVE_NS, profile) if code is not None else None
            event = event_record(name, i, row, saved, ordinal, label, window, exposure, roster, starts, ends)
            event['adc_window_status'] = str(status)
            require((status == 'captured') == event['supports']['adc']['fully_qualified'],
                    f'ADC capture does not match qualified coverage: {name}')
            events.append(event)
            nearest_gap = min((max(0., r['first_active_offset_ns'], -r['last_active_offset_ns'])
                               for r in event['nearest_recorded_rises'].values() if r is not None), default=float('inf'))
            if window is not None and (representative is None or nearest_gap < representative['nearest_rise_gap_ns']):
                contacts = row['x_collecting_strips']+row['y_collecting_strips']
                representative = {key: event[key] for key in
                                  ('block', *identities, 'rise_end_ns', 'energy_window', 'nearest_recorded_rises')}
                representative.update(nearest_rise_gap_ns=nearest_gap, activity=window, contact_ids=contacts,
                                      relative_time_ns=RELATIVE_NS.tolist(), volts_per_code=digital._LSB_V,
                                      adc_codes=code[np.asarray(contacts)-1].tolist(),
                                      acquisition_baseline_v=baseline[np.asarray(contacts)-1].tolist())
    summary = {'layers': {}}
    for label, saved in plane['layers'].items():
        members = [row for row in events if label in ('all', row['energy_window'])]
        summary['layers'][label] = layer_summary(members, saved)
    summary['selection'] = {key: plane['selection'][key] for key in
                            (*SELECTION_COUNTS, 'clock_live_time_ns', 'qualified_adc_live_time_ns')}
    provenance = {key: item[key] for key in ('name', 'report_sha256', 'adc_windows_sha256', 'plane_sha256',
                                           'clock_seed', 'noise_seed', 'known_component_adc_sha256')}
    provenance.update(trigger_profile=design['trigger_profile'], excluded_intervals_ns=exposure['excluded_intervals_ns'],
                      qualified_live_adc_samples=exposure['qualified_live_adc_samples'])
    return dict(block=provenance, events=events, summary=summary, representative=representative)


def layer_summary(events, saved):
    summary = dict(triggers=len(events), triggers_with_geometry=sum(row['hypotheses'] > 0 for row in events),
                   **{key: sum(row[key] for row in events) for key in ('allowed_hypotheses', 'hypotheses')},
                   **{key: fsum(row[key] for row in events) for key in (*LAYER_MASS, *MASSES)})
    require(all(isclose(summary[key], saved[key], rel_tol=0., abs_tol=1e-12) for key in CONE_ACCOUNTING),
            'Measured overlap cohort does not reproduce the saved source-plane census')
    supports = {}
    for label in SUPPORTS:
        affected = [row for row in events if row['supports'][label]['status'] == 'recorded_overlap']
        supports[label] = {status: sum(row['supports'][label]['status'] == status for row in events) for status in STATUSES}
        supports[label].update(fully_qualified=sum(row['supports'][label]['fully_qualified'] for row in events),
                               overlap_projected_mass=fsum(row['projected_mass'] for row in affected),
                               overlap_unresolved_mass=fsum(row['unresolved_mass'] for row in affected))
    flags = [row['waveform']['secondary_rearmed_coincident_rise'] for row in events]
    summary.update(
        supports=supports,
        waveform=dict(evaluated=sum(value is not None for value in flags), unavailable=sum(value is None for value in flags),
                      secondary_rearmed_coincident_rise=sum(value is True for value in flags),
                      primary_interval_reproduced=sum(row['waveform']['primary_interval_reproduced'] for row in events),
                      captured_adc_windows=sum(row['adc_window_status'] == 'captured' for row in events)),
        primary_rise_beyond_fast_gate=sum(row['rise_end_ns']-row['trigger_time_ns'] > FAST_GATE[1] for row in events),
        collector_neighbor_fast_quality_issues=sum(row['collector_neighbor_fast_quality_issue'] for row in events),
    )
    return summary


def study():
    pool = json.loads(gzip.decompress(read_bytes(V1_POOL, V1_POOL_SHA)))
    blocks = [read_block(item) for item in pool['inputs']]
    views = {}
    for label, indices in VIEWS.items():
        events = [event for i in indices for event in blocks[i]['events']]
        saved = pool['views'][label]
        selection = {key: sum(blocks[i]['summary']['selection'][key] for i in indices) for key in saved['selection']}
        require(selection == saved['selection'], f'Original pooled acquisition census differs: {label}')
        views[label] = dict(selection=selection, layers={
            key: layer_summary([row for row in events if key in ('all', row['energy_window'])], saved_layer)
            for key, saved_layer in saved['layers'].items()})
    full = views['full']
    all_events = full['layers']['all']
    require((full['selection']['qualified_triggers'], all_events['triggers'], all_events['triggers_with_geometry'])
            == (3905, 324, 254), 'Unexpected bound four-block census')
    representative = min((b['representative'] for b in blocks if b['representative'] is not None),
                         key=lambda row: row['nearest_rise_gap_ns'], default=None)
    return dict(
        kind='gegi_measured_shared_clock_overlap_v1', source_pool_sha256=V1_POOL_SHA,
        source_sha256={name: digest(Path(__file__).with_name(name).read_bytes()) for name in
                       ('gegi_measured_overlap_study.py', 'gegi_window_activity.py', 'gegi_exposure_stream.py',
                        'gegi_digital_readout.py', 'gegi_pulse_stream.py')},
        definitions=dict(
            sample_period_ns=DT, support_relative_ns=SUPPORTS, fast_gate_relative_ns=FAST_GATE,
            slow_plateau_relative_ns=SLOW_GATE, cfd_gate_relative_ns=digital._TIMING['gate_ns'],
            energy_windows_keV={f'{center:g}_keV': [center-max(5., .02*center), center+max(5., .02*center)]
                               for center in LINE_ENERGIES_KEV},
            timing='Compare another recorded rise extent from reference plus one ADC sample through the last active sample. '
                   'These inclusive sample spans describe grouped activity. A reference alone is before the first active sample.',
            support='Fast and slow bounds are the acquisition readout support used for ADC rail checks, including the '
                    'quiet reference or trapezoid lookback and one leading correction margin. The preamplifier retains '
                    'analog history beyond these finite digital sample spans.',
            coverage='Use each block and its own half-open qualification gaps and live endpoints. No adjacency is inferred '
                     'across independently reset blocks. An incomplete support can still contain a recorded rise.',
            waveform='Use the all-34 signed face sums and the saved acquisition baseline. A potential second activity group '
                     'needs the recorded coincidence threshold and three contiguous quiet increments visible within the sidecar. '
                     'The first two ADC samples cannot yield a filtered increment. This test does not repeat persistent-step acceptance.',
            limitations='A single recorded or reproduced rise can contain several deposits or pulses. '
                        'The diagnostic cannot exclude activity in the same group, below threshold, or outside the saved ADC interval. '
                        'No simulated arrival labels enter the calculation, and no trigger or order was removed or reweighted.',
            representative='Use the captured two-strip window nearest another recorded rise by distance from its reference '
                           'to the other rise extent. Break ties in acquisition and trigger order.',
        ),
        inputs=[b['block'] for b in blocks], individual=[b['summary'] for b in blocks], views=views,
        representative_waveform=representative, events=[event for b in blocks for event in b['events']],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = study()
    with args.output.open('x', encoding='utf-8', newline='\n') as target:
        json.dump(result, target, allow_nan=False, separators=(',', ':'))
        target.write('\n')


if __name__ == '__main__':
    main()
