"""Attach the saved weak-strip diagnostic and native comparison to GeGI Results."""

from collections import Counter
from hashlib import sha256
import json
from math import exp, fsum, isclose
from pathlib import Path
from struct import unpack_from

from gegi_shared_clock_display import (
    MEASURED_SHA256, REFERENCE_SHA256, SUMMARY as CLOCK_SUMMARY, VIEWS, read_study, table, validate_plane_binding,
)


SUMMARY = Path('results/gegi-digital/weak-strips.json')
FIGURE = SUMMARY.with_suffix('.png')
ADC_SHA256 = '6db46a83089af94fa9051ccc4aa3a4e287cf29fabbf4731e5d93cca6a16bfb9a'
ENDPOINT_SHA256 = '40ade04dfccdf33cf2d8593f255b2cc462a7194e73e957b6b4cc235d8da69319'
PAIRING_SHA256 = 'c271fec9aa7370c2a30e23b5ee3700cac0f08a9ca1b4d7561fa045aee5bbed5a'
ADC_KIND = 'gegi_independent_weak_strip_study_v1'
NATIVE_KIND = 'gegi_independent_weak_strip_endpoints_v1'
KINDS = ('energy_incompatible', 'energy_compatible_unique', 'energy_compatible_ambiguous')
POPULATIONS = {
    'all': 'All',
    'energy_incompatible': 'No compatible pairing',
    'energy_compatible': 'At least one compatible pairing',
    'energy_compatible_unique': 'One compatible pairing',
    'energy_compatible_ambiguous': 'Two compatible pairings',
}
MEASURED_SITE_FIELDS = ('x_contact_id', 'y_contact_id', 'x_energy_keV', 'y_energy_keV', 'energy_keV',
                        'x_minus_y_energy_keV', 'energy_tolerance_keV', 'energy_compatible')
EVENT_KEYS = ('block', 'trigger_index', 'two_strip_ordinal', 'trigger_time_ns', 'rise_end_ns', 'energy_keV',
              'energy_window', 'allowed_hypotheses', 'hypotheses', 'projected_mass', 'unresolved_mass',
              'allowed_order_mass', 'unassigned_without_pairing_mass', 'unassigned_without_allowed_order_mass',
              'unassigned_without_projection_mass', 'pairings')
BLOCK_KEYS = ('name', 'report_sha256', 'adc_windows_sha256', 'plane_sha256')


def require(condition, message):
    if not condition:
        raise ValueError(f'GeGI weak-strip study {message}')


def report_hashes():
    return dict(adc_study=ADC_SHA256, native_endpoints=ENDPOINT_SHA256, recorded_clock=MEASURED_SHA256,
                simulated_clock=REFERENCE_SHA256, ideal_endpoint_pairing=PAIRING_SHA256)


def validate_binding(data, plane, clock):
    validate_plane_binding(clock, plane)
    require(data['kind'] == 'gegi_weak_strips_public_v1' and data['reports_sha256'] == report_hashes()
            and data['plane_study_sha256'] == clock['plane_study_sha256'] and data['blocks'] == clock['blocks']
            and clock['reports_sha256']['recorded'] == MEASURED_SHA256
            and clock['reports_sha256']['reference'] == REFERENCE_SHA256,
            'belongs to a different acquisition, timing reference or projection')
    require(tuple(data['views']) == tuple(VIEWS), 'has different exposure partitions')
    for view_key, populations in data['views'].items():
        counts = populations['all']
        layer = clock['views'][view_key]['layers']['all']
        selection = plane['views'][view_key]['selection']
        require(
            counts['adc']['selected'] == layer['triggers'] == selection['two_strip_triggers']
            and counts['projection'] == {key: layer[key] for key in counts['projection']},
            f'census disagrees with the existing plane and shared-clock results in {view_key}',
        )


def exposure_rows(events, blocks):
    return {
        'first_half': [row for row in events if row['block'] in blocks[:2]],
        'second_half': [row for row in events if row['block'] in blocks[2:]],
        'full': events,
    }


def compact_event(original, adc, native):
    readout = adc['two_strip_pairings']
    expected_collectors = sorted(original['x_collecting_strips'] + original['y_collecting_strips'])
    require(all(adc[key] == original[key] for key in (*EVENT_KEYS, 'adc_window_status'))
            and sorted(adc['collectors']) == expected_collectors
            and readout['compatible_pairing_count'] == len(original['pairings'])
            and adc['pairing_class'] == KINDS[len(original['pairings'])]
            and all(native[key] == original[key] for key in EVENT_KEYS if key != 'pairings')
            and native['projection_pairings'] == original['pairings']
            and native['measured_pairings'] == readout
            and native['collector_contact_ids'] == expected_collectors
            and native['pairing_class'] == adc['pairing_class'],
            f'changes original trigger, pairing or projection at {original["block"]}/{original["trigger_index"]}')
    diagnosis = adc['adc_diagnostic']
    eligible = {row['contact_id']: row for row in diagnosis['contacts']}
    flags = {row['contact_id']: row for row in diagnosis['weak_strips']}
    comparisons = {row['contact_id']: row for row in native['contacts']}
    require(len(comparisons) == len(native['contacts']) and comparisons.keys() == eligible.keys()
            and native['adc_status'] == diagnosis['status'] and all(
                row['adc_step_keV_equiv'] == eligible[cid]['step_keV_equiv']
                and row['adc_status'] == eligible[cid]['status'] for cid, row in comparisons.items()),
            f'uses different ADC contacts in the native comparison at {original["block"]}/{original["trigger_index"]}')
    significant = [row for cid, row in comparisons.items() if cid in flags or row['endpoint_input_band'] == 'weak'
                   or row['adc_saturated']]
    group = native['native_group']
    return dict(
        **{key: original[key] for key in EVENT_KEYS},
        pairing_class=adc['pairing_class'],
        collectors=expected_collectors,
        pairing_flags=readout['flags'],
        measured_pairings=[dict(index=p['index'], energy_compatible=p['energy_compatible'],
                                sites=[{key: s[key] for key in MEASURED_SITE_FIELDS} for s in p['sites']],
                                compton_orders=p['compton_orders']) for p in readout['pairings']],
        adc={key: value for key, value in diagnosis.items() if key != 'contacts'},
        reference=dict(status=native['native_status'], timing_association=adc['timing_association'],
                       timing_anchor_group_index=native['timing_anchor_group_index'],
                       timing_link_scope=native['timing_link_scope'],
                       group={key: group[key] for key in ('source', 'occurrence_id', 'campaign_initial_id',
                                                          'group_id', 'raw_event_id', 'metadata_sha256')} if group else None,
                       endpoint_intersections=[{key: c[key] for key in ('x_contact_id', 'y_contact_id', 'deposit_keV')}
                                               for c in native['endpoint_collections']]
                       if native['endpoint_collections'] is not None else None),
        native_contacts=significant,
    )


def compare_counts(events, adc, native, measured, clock):
    views = {}
    for view, rows in exposure_rows(events, [row['name'] for row in clock['blocks']]).items():
        views[view] = {}
        for label in POPULATIONS:
            selected = [row for row in rows if label in ('all', row['pairing_class'])
                        or label == 'energy_compatible' and row['pairing_class'] != KINDS[0]]
            a, n = adc['views'][view][label], native['views'][view][label]
            flags = [row['adc']['weak_strips'] for row in selected]
            require(a['selected'] == n['triggers'] == len(selected)
                    and a['measured'] == sum(row['adc']['status'] == 'measured' for row in selected)
                    and a['unevaluable'] == len(selected) - a['measured']
                    and a['flagged_windows'] == n['triggers_with_adc_detection'] == sum(map(bool, flags))
                    and a['flagged_contacts'] == n['adc_detected_contacts'] == sum(map(len, flags))
                    and sum(n['native_status'].values()) == len(selected)
                    and sum(n['adc_status'].values()) == len(selected)
                    and sum(n['trigger_comparison'].values()) == len(selected)
                    and n['endpoint_collection_cell_counts'] == Counter(
                        str(len(r['reference']['endpoint_intersections'])) for r in selected
                        if r['reference']['endpoint_intersections'] is not None)
                    and n['expected_weak_contacts'] == n['expected_weak_evaluable_contacts']
                    + n['expected_weak_unevaluable_contacts']
                    and n['expected_weak_evaluable_contacts'] == sum(n['contact_comparison'].get(key, 0)
                                                                    for key in ('true_positive', 'false_negative')),
                    f'ADC and native denominators disagree in {view}/{label}')
            projection = {key: sum(row[key] for row in selected) for key in ('allowed_hypotheses', 'hypotheses')}
            projection['triggers_with_geometry'] = sum(row['hypotheses'] > 0 for row in selected)
            for key in ('projected_mass', 'unresolved_mass'):
                value = fsum(row[key] for row in selected)
                require(isclose(a[key], value, rel_tol=0, abs_tol=1e-12)
                        and isclose(n[key], value, rel_tol=0, abs_tol=1e-12),
                        f'projection weights disagree in {view}/{label}')
                projection[key] = value
            views[view][label] = dict(adc=a, native=n, projection=projection)
        selection = measured['views'][view]['selection']
        for label, field in ((KINDS[0], 'two_strip_triggers_without_compatible_pairing'),
                             (KINDS[2], 'two_strip_triggers_with_two_compatible_pairings')):
            require(views[view][label]['adc']['selected'] == selection[field],
                    f'pairing count disagrees with the recorded triggers in {view}/{label}')
    return views


def attach(site, adc_path, native_path, measured_path, pairing_path):
    from gegi_digital_display import MEASURED_PLANE_FILE
    from gegi_digital_pairs import energy_pairings
    from gegi_imaging import MIN_COLLECTED_KEV, PAIR_ABS_KEV, PAIR_REL

    adc = read_study(adc_path, ADC_SHA256)
    native = read_study(native_path, ENDPOINT_SHA256)
    measured = read_study(measured_path, MEASURED_SHA256)
    ideal = read_study(pairing_path, PAIRING_SHA256)
    plane = json.loads((site/MEASURED_PLANE_FILE).read_bytes())
    clock = json.loads((site/CLOCK_SUMMARY).read_bytes())
    blocks = [{key: row[key] for key in BLOCK_KEYS} for row in measured['inputs']]
    acquisition_hashes = {row[key] for row in blocks for key in BLOCK_KEYS[1:]}
    require(adc['kind'] == ADC_KIND and native['kind'] == NATIVE_KIND
            and ideal['kind'] == 'gegi_saved_endpoint_pairing_counterfactual_v1'
            and adc['status'] == native['status'] == ideal['status'] == 'completed'
            and acquisition_hashes.union({MEASURED_SHA256, REFERENCE_SHA256, measured['source_pool_sha256']})
            .issubset(adc['input_sha256'].values())
            and {ADC_SHA256, MEASURED_SHA256, REFERENCE_SHA256}.issubset(native['input_sha256'].values())
            and ENDPOINT_SHA256 in ideal['input_sha256'].values()
            and (ideal['design']['pairing_absolute_tolerance_keV'], ideal['design']['pairing_relative_tolerance'],
                 ideal['design']['reported_collector_threshold_keV']) == (PAIR_ABS_KEV, PAIR_REL, MIN_COLLECTED_KEV),
            'reports lack the bound ADC, plane or clock inputs')
    adc_by_id = {(row['block'], row['trigger_index']): row for row in adc['events']}
    native_by_id = {(row['block'], row['trigger_index']): row for row in native['events']}
    ideal_by_id = {(row['block'], row['trigger_index']): row for row in ideal['events']}
    require(len(adc_by_id) == len(adc['events']) == len(native_by_id) == len(native['events']) == len(ideal_by_id)
            == len(ideal['events']) == len(measured['events'])
            and adc_by_id.keys() == native_by_id.keys() == ideal_by_id.keys(),
            'reports do not cover the same original trigger identities exactly once')
    rows = []
    for original in measured['events']:
        key = (original['block'], original['trigger_index'])
        a, n = adc_by_id.pop(key), native_by_id.pop(key)
        row = compact_event(original, a, n)
        p = ideal_by_id.pop(key)
        xs, ys = original['x_collecting_strips'], original['y_collecting_strips']
        cells = n['endpoint_collections']
        sums = {cid: fsum(c['deposit_keV'] for c in cells if cid in (c['x_contact_id'], c['y_contact_id']))
                for cid in row['collectors']}
        passing = [pair['index'] for pair in energy_pairings(xs, ys, sums) if pair['energy_compatible']]
        occupied = sum(c['x_contact_id'] in xs and c['y_contact_id'] in ys for c in cells)
        require(p['native_input_group_sha256'] == n['native_input_group_sha256']
                and p['measured_compatible_indices'] == [pair['index'] for pair in original['pairings']]
                and p['collector_contact_ids'] == row['collectors']
                and p['ideal_strip_energy_keV'] == {str(cid): value for cid, value in sums.items()}
                and p['ideal_compatible_indices'] == passing and p['occupied_measured_cell_count'] == occupied
                and (p['endpoint_support'] == 'complete_on_measured_strips') == (occupied == len(cells)),
                f'ideal endpoint pairing differs from the original trigger at {key[0]}/{key[1]}')
        row['ideal_endpoint_pairing'] = {k: p[k] for k in ('ideal_compatible_indices', 'ideal_strip_energy_keV',
                                                          'occupied_measured_cell_count', 'endpoint_support')}
        rows.append(row)
    trace = representative_trace(adc['representative_waveforms']['holdout_target'], rows, adc['design'])
    ideal_summary = ideal['views']['full']
    require(ideal_summary['all']['exact_compatible_indices_matches'] == sum(
        r['ideal_endpoint_pairing']['ideal_compatible_indices'] == [p['index'] for p in r['pairings']] for r in rows),
        'ideal endpoint pairing counts disagree with the event records')
    result = dict(kind='gegi_weak_strips_public_v1', reports_sha256=report_hashes(),
                  plane_study_sha256=measured['source_pool_sha256'], blocks=blocks, events=rows,
                  source_sha256={'adc': adc['source_sha256'], 'native': native['source_sha256'],
                                 'ideal_endpoint_pairing': {Path(p).name: h for p, h in ideal['source_sha256'].items()}},
                  design={'adc': adc['design'], 'native': native['design'], 'ideal_endpoint_pairing': ideal['design']},
                  ideal_endpoint_pairing=ideal['views'],
                  views=compare_counts(rows, adc, native, measured, clock), representative_trace=trace)
    validate_binding(result, plane, clock)
    plot_trace(trace, adc['design'], site/FIGURE)
    image = (site/FIGURE).read_bytes()
    result['figure'] = dict(sha256=sha256(image).hexdigest(), size_px=unpack_from('>II', image, 16))
    (site/SUMMARY).write_text(json.dumps(result, allow_nan=False, separators=(',', ':')) + '\n',
                              encoding='utf-8', newline='\n')


def representative_trace(waveform, rows, design):
    keys = ('block', 'trigger_index', 'trigger_time_ns', 'two_strip_ordinal')
    row, = [row for row in rows if all(row[key] == waveform[key] for key in keys)]
    weak, = row['adc']['weak_strips']
    cid = weak['contact_id']
    times = waveform['relative_time_ns']
    index = waveform['contact_ids'].index(cid)
    codes, baseline = waveform['codes'][index], waveform['baseline_v'][index]
    volts_per_code = waveform['volts_per_code']
    require(times == design['relative_time_ns'] and volts_per_code == design['volts_per_code'],
            'illustrated ADC samples use different timing or voltage units')
    equivalent = [(code * volts_per_code - baseline) * exp(time/design['feedback_tau_ns'])
                  / design['tail_gain_v_per_kev'] for code, time in zip(codes, times, strict=True)]
    quiet = fsum(equivalent[times.index(t)] for t in design['quiet_reference_ns']) / len(design['quiet_reference_ns'])
    relative = [value - quiet for value in equivalent]
    step = fsum(relative[times.index(t)] for t in design['late_plateau_ns']) / len(design['late_plateau_ns'])
    require(isclose(step, weak['step_keV_equiv'], rel_tol=0, abs_tol=1e-12),
            'illustrated ADC samples do not reproduce the reported step')
    reference, = [contact for contact in row['native_contacts'] if contact['contact_id'] == cid]
    return dict(**{key: row[key] for key in keys}, rise_end_ns=row['rise_end_ns'], contact_id=cid, codes=codes,
                acquisition_baseline_v=baseline, relative_time_ns=times, corrected_keV_equiv=relative,
                step_keV_equiv=step, threshold_keV_equiv=row['adc']['threshold_keV_equiv'],
                native_contact=reference)


def plot_trace(trace, design, target):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(8, 3.2), layout='constrained')
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    times, signal = trace['relative_time_ns'], trace['corrected_keV_equiv']
    for key, caption, color in (('quiet_reference_ns', 'Quiet reference', '#78879b'),
                                ('late_plateau_ns', 'Late samples', '#3c8c69')):
        axis.axvspan(min(design[key]), max(design[key]), alpha=.18, color=color, label=caption)
    axis.plot(times, signal, 'o-', color='#155890', lw=1.4, markersize=4, label='Corrected ADC samples')
    axis.axhline(design['collection_threshold_keV'], color='#555', ls='--', lw=1, label='Step cutoff')
    axis.axhline(trace['step_keV_equiv'], xmin=.84, color='#24684f', lw=1.2, ls=':')
    axis.set_xlabel('Time from recorded trigger (ns)')
    axis.set_ylabel('Corrected preamp signal\n(keV equivalent)')
    axis.grid(axis='y', color='#dbe2ea', linewidth=.7)
    handles, names = axis.get_legend_handles_labels()
    figure.legend(handles, names, ncols=2, fontsize=9, loc='outside upper center')
    figure.savefig(target, dpi=125, facecolor='white')


def adc_table(views):
    rows = []
    for view, caption in VIEWS.items():
        for key in ('all', 'energy_incompatible', 'energy_compatible'):
            a = views[view][key]['adc']
            rows.append((caption, POPULATIONS[key], a['selected'], a['measured'], a['unevaluable'],
                         a['flagged_windows'], a['flagged_contacts']))
    return table(rows, ('Exposure', 'X/Y energy pairing', 'Windows', 'Evaluated', 'Unevaluable',
                        'Windows flagged', 'Strips flagged'), 'Weak-step diagnostic by exposure and pairing')


def native_table(views):
    rows = []
    for key in ('all', 'energy_incompatible', 'energy_compatible'):
        n = views['full'][key]['native']
        comp = n['contact_comparison']
        classes = n['adc_positive_with_native_classes']
        induced_only = classes.get('induced_only_terminal', 0) + classes.get('induced_only_transient', 0)
        rows.append((POPULATIONS[key], n['native_status'].get('measured', 0), sum(classes.values()),
                     n['expected_weak_evaluable_contacts'], comp.get('true_positive', 0),
                     comp.get('false_negative', 0), n['expected_weak_unevaluable_contacts'],
                     induced_only))
    return table(rows, ('X/Y energy pairing', 'Windows with native reference', 'Flagged strips compared',
                        'Comparable weak landings', 'Detected landings', 'Missed landings',
                        'Weak landings unevaluable by ADC', 'Induction only'),
                 'Comparison with the archived simulation endpoints in the pooled exposure')


def trace_section(data):
    trace, figure = data['representative_trace'], data['figure']
    width, height = figure['size_px']
    cid = trace['contact_id']
    name = f'X{cid:02d}' if cid <= 16 else f'Y{cid-17:02d}'
    block = [row['name'] for row in data['blocks']].index(trace['block']) + 1
    native = trace['native_contact']
    relative = FIGURE.relative_to('results').as_posix()
    return f'''<figure style="margin:1rem 0"><a href="{relative}"><img loading="lazy" style="width:100%;height:auto"
width="{width}" height="{height}" src="{relative}"
alt="Corrected preamplifier ADC samples for {name} of trigger {trace['trigger_index']}. The late samples show a sustained step."></a>
<figcaption>Block {block}, trigger {trace['trigger_index']}, strip {name}. The late mean was
{trace['step_keV_equiv']:.3f} keV equivalent. Deposits whose carriers ended on this strip sum to
{native['endpoint_input_keV']:.3f} keV. The final native induced signal was
{native['native_terminal_wired_keV_equiv']:.3f} keV equivalent.</figcaption></figure>'''


def endpoint_context(data):
    rows = data['events']
    native = data['views']['full']['all']['native']
    counts = native['contact_comparison']
    classes = native['adc_positive_with_native_classes']
    measured = native['adc_detected_contacts']
    collecting = classes.get('collection', 0) + classes.get('collection_with_terminal_residual', 0)
    outside = []
    for row in rows:
        for contact in row['native_contacts']:
            if contact['comparison'] == 'false_positive_below_endpoint_sensitivity':
                outside.append(f'{contact["endpoint_input_keV"]:.3f} keV at the carrier endpoint versus '
                               f'{contact["adc_step_keV_equiv"]:.3f} keV equivalent from the ADC')
    adc_floor = data['representative_trace']['threshold_keV_equiv']
    extra = (f' One strip crossed the {adc_floor:.3f} keV-equivalent detection floor with '
             f'{outside[0]}.' if len(outside) == 1 else '')
    return f'''<p>{collecting}/{measured} flags had at least one carrier landing in their matched group.
The diagnostic detected {counts.get('true_positive', 0)}/{native['expected_weak_evaluable_contacts']} comparable
landings inside the band, with {counts.get('false_negative', 0)} misses.{extra}
The {measured} flagged strip observations came from {native['distinct_native_groups_with_adc_detection']} distinct
archived groups and {native['distinct_native_group_contact_detections']} distinct group and strip combinations.</p>'''


def section(site, plane):
    data = json.loads((site/SUMMARY).read_bytes())
    clock = json.loads((site/CLOCK_SUMMARY).read_bytes())
    validate_binding(data, plane, clock)
    require(sha256((site/FIGURE).read_bytes()).hexdigest() == data['figure']['sha256'],
            'figure differs from its public summary')
    views = data['views']
    full = views['full']
    left, right = (full[key]['adc'] for key in ('energy_incompatible', 'energy_compatible'))
    ambiguous = full[KINDS[2]]['adc']
    left_cells, right_cells = (full[key]['native']['endpoint_collection_cell_counts']
                               for key in ('energy_incompatible', 'energy_compatible'))
    left_three, left_four = left_cells.get('3', 0), left_cells.get('4', 0)
    right_many = sum(count for cells, count in right_cells.items() if int(cells) >= 3)
    design = data['design']['adc']
    late_limit = data['events'][0]['adc']['late_difference_limit_keV_equiv']
    bounds = ' to '.join(f'{value:+g}' for value in
                         (design['late_plateau_ns'][0], design['late_plateau_ns'][-1]))
    relative = SUMMARY.relative_to('results').as_posix()
    proj = full['all']['projection']
    ideal = data['ideal_endpoint_pairing']['full']
    no_flag = ideal['energy_incompatible_unflagged']
    no_flag_cells = no_flag['measured_cell_counts']
    return f'''<h4 id="gegi-weak-strips">Weak strip signals in two-strip triggers</h4>
<p>The fixed late-step diagnostic flagged <strong>{left['flagged_windows']}/{left['measured']}</strong> evaluated
triggers with no energy-compatible X/Y pairing and <strong>{right['flagged_windows']}/{right['measured']}</strong>
with at least one. All {left['selected']} incompatible triggers had simulated carrier endpoints at three or four
strip intersections ({left_three} and {left_four}, respectively). Among the compatible triggers,
{right_many}/{right['selected']} occupied three or more intersections.</p>
<details><summary>Exposure counts, matched carrier evidence and ADC samples</summary>
{adc_table(views)}
<p>Among the compatible triggers, {ambiguous['flagged_windows']}/{ambiguous['measured']} with two allowed X/Y
assignments had a flag. The study retains both X/Y alternatives and the original weight of every trigger.
The plane comparison still accounts for {proj['projected_mass']:g} projected and {proj['unresolved_mass']:g} unresolved
trigger units.</p>
{native_table(views)}
{endpoint_context(data)}
<p>Summing the simulated deposits by the saved carrier endpoints and applying the original energy tolerance to the
same four strips reproduced the exact compatible X/Y alternatives for {ideal['all']['exact_compatible_indices_matches']}/{ideal['all']['triggers']}
triggers. Among the {no_flag['triggers']} incompatible triggers without a weak-step flag, the four measured strips
accounted for all endpoint charge, across {no_flag_cells.get('3', 0)} three-intersection and
{no_flag_cells.get('4', 0)} four-intersection patterns. These intersections come from simulated carrier endpoints.</p>
<p>A weak landing means that the total deposited energy of the rows with a saved carrier endpoint on that strip
is in the diagnostic amplitude band. The simulation also provides the signed induced signal. With no endpoint on
a strip, a terminal or transient signal can still arise from motion of carriers collected elsewhere.
The comparison requires one uniquely assigned group with usable saved native records and no additional native current
on the window. The table classifies induction-only flags at the modeled sensitivity scale.</p>
{trace_section(data)}
<p>The test uses the original {design['significance']:g}-sigma noise criterion and the
{design['collection_threshold_keV']:g} keV collection cutoff. It compares the mean of five late samples
({bounds} ns from the trigger) with the quiet reference after correcting for the nominal preamplifier decay.
The first late sample must follow the end of the recorded rise by at least {design['minimum_settling_ns']:g} ns.
The first and last pairs of late samples must have means within {late_limit:.3f} keV equivalent of each other.
These frequencies describe the simulated readout in the saved windows.</p>
<p><a href="{relative}">Open trigger identities, amplitudes, counts and source hashes (JSON)</a>.</p>
</details>'''
