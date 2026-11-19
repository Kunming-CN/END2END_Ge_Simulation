"""Publish the saved shared-clock timing comparison in the GeGI Results hub."""

import gzip
from hashlib import sha256
from html import escape
import json
from pathlib import Path
from struct import unpack_from


SUMMARY = Path('results/gegi-digital/shared-clock.json')
MERGED_IMAGE = SUMMARY.with_name('shared-clock-merged.png')
VIEWS = {'first_half': 'First half', 'second_half': 'Second half', 'full': 'Pooled'}
MEASURED_SHA256 = 'ddea3349304ada26bf6c7fed54b7ebfdc84781a3e79eeb7e81d191c4cf5aa9e1'
REFERENCE_SHA256 = '6cae1651ccc51c20eeef390ba945128584ac35220d8243b05457e3c869d2ce6f'
CONTROL_SHA256 = 'd0d93253b61b1fdedd2f20855542c21ac4110242612182a51f740115e0f773e5'
MERGED_SHA256 = '67b6cae7d4d1c3d48945c2f77c413dcc74024f9d1f8d521d4bb6e8350494cfdf'


def read_study(path, expected_sha256):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f'Unexpected checksum for saved GeGI timing input {path.name}')
    return json.loads(gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw)


def table(rows, headings, caption):
    header = ''.join(f'<th scope="col">{h}</th>' for h in headings)
    body = ''.join(f'<tr><th scope="row">{row[0]}</th>'
                   + ''.join(f'<td>{cell}</td>' for cell in row[1:]) + '</tr>' for row in rows)
    return f'''<div role="region" aria-label="{escape(caption)}" tabindex="0" style="overflow-x:auto">
<table><caption>{escape(caption)}</caption><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'''


def validate_plane_binding(data, plane):
    if (data['plane_study_sha256'] != plane['source_sha256']['study'] or data['windows'] != plane['windows']
            or data['views'].keys() != plane['views'].keys()):
        raise ValueError('GeGI timing study belongs to a different measured-plane comparison')
    for view_name, view in data['views'].items():
        baseline = plane['views'][view_name]
        if (view['selection'] != baseline['selection'] or view['layers'].keys() != baseline['layers'].keys()
                or any(layer['triggers'] != baseline['layers'][label]['triggers']
                       for label, layer in view['layers'].items())):
            raise ValueError('GeGI timing counts disagree with the measured-plane census')


def compact_layer(measured, reference, baseline):
    projection = {key: baseline[key] for key in ('triggers', 'triggers_with_geometry', 'allowed_hypotheses',
                                                'hypotheses', 'projected_mass', 'unresolved_mass')}
    total = projection['triggers']
    if (any(measured[key] != value for key, value in projection.items()) or reference['rows'] != total
            or any(reference[key] != projection[key] for key in ('projected_mass', 'unresolved_mass'))):
        raise ValueError('GeGI timing layer does not match its trigger and projection census')
    supports = measured['supports']
    for gate, counts in supports.items():
        if (sum(counts[key] for key in ('recorded_overlap', 'no_recorded_overlap', 'incomplete_coverage')) != total
                or sum(reference[f'group_onset_{gate}'].values()) != total):
            raise ValueError('GeGI timing flags do not close over all selected triggers')
    waveform = measured['waveform']
    if not 0 <= waveform['secondary_rearmed_coincident_rise'] <= waveform['evaluated'] == total - waveform['unavailable']:
        raise ValueError('GeGI waveform timing denominator does not close')
    ref = {key: value for key, value in reference.items() if key not in ('rows', 'projected_mass', 'unresolved_mass')}
    return dict(**projection, measured=supports, waveform=waveform, reference=ref,
                primary_rise_beyond_fast_gate=measured['primary_rise_beyond_fast_gate'],
                collector_neighbor_fast_quality_issues=measured['collector_neighbor_fast_quality_issues'])


def attach(site, sources):
    from gegi_digital_display import MEASURED_PLANE_FILE, READOUT_VALIDATION_SHA256

    report_hashes = {'recorded': MEASURED_SHA256, 'reference': REFERENCE_SHA256, 'control': CONTROL_SHA256,
                     'merged_windows': MERGED_SHA256}
    measured, reference, control, merged = (read_study(path, digest)
                                            for path, digest in zip(sources, report_hashes.values(), strict=True))
    plane = json.loads((site/MEASURED_PLANE_FILE).read_bytes())
    pool_sha = measured['source_pool_sha256']
    if (measured['kind'] != 'gegi_measured_shared_clock_overlap_v1'
            or reference['kind'] != 'gegi_independent_clock_overlap_reference_v1'
            or reference['status'] != 'completed'
            or not {pool_sha, MEASURED_SHA256}.issubset(reference['input_sha256'].values())
            or reference['design']['supports_ns'] != measured['definitions']['support_relative_ns']):
        raise ValueError('GeGI recorded and reference timing studies use different inputs or spans')

    fields = ('name', 'report_sha256', 'adc_windows_sha256', 'plane_sha256')
    blocks = [{key: row[key] for key in fields} for row in measured['inputs']]
    if len(blocks) != 4 or blocks != [{key: item['provenance'][key] for key in fields} for item in reference['blocks']]:
        raise ValueError('GeGI timing studies use different exposure blocks')

    source_hashes = {key: {'tools/' + name: digest for name, digest in report['source_sha256'].items()}
                     for key, report in (('recorded', measured), ('control', control))}
    source_hashes['reference'] = reference['source_sha256']
    source_hashes['merged_windows'] = merged['source_sha256']

    views = {}
    for key, baseline in plane['views'].items():
        actual, ref = measured['views'][key], reference['views'][key]
        selection = {field: actual['selection'][field] for field in baseline['selection']}
        if (actual['layers'].keys() != baseline['layers'].keys() or ref['windows'].keys() != baseline['layers'].keys()
                or any(ref[field] != selection[field] for field in ('qualified_triggers', 'clock_live_time_ns',
                                                                     'qualified_adc_live_time_ns'))):
            raise ValueError('GeGI recorded and reference timing groups disagree with the plane')
        layers = {name: compact_layer(actual['layers'][name], ref['windows'][name], layer)
                  for name, layer in baseline['layers'].items()}
        references = {field: ref[field] for field in ('initial_parents', 'scheduled_ge_groups', 'unavailable_groups',
                                                      'right_censored_groups', 'excluded_history_groups',
                                                      'zero_deposit_parent_marks', 'all_trigger_associations')}
        if sum(references['all_trigger_associations'].values()) != selection['qualified_triggers']:
            raise ValueError('GeGI timing associations do not close over the qualified trigger count')
        views[key] = dict(selection=selection, layers=layers, reference_census=references)

    activity = measured['representative_waveform']['activity']
    timing = dict(support_bounds_ns=measured['definitions']['support_relative_ns'],
                  **{key: activity[key] for key in ('sample_period_ns', 'quiet_samples', 'quiet_threshold_keV',
                                                   'coincidence_threshold_keV')})
    controls = compact_controls(control, READOUT_VALIDATION_SHA256['pileup'], timing)
    examples = compact_merged(merged, reference, timing)
    plot_merged(examples, site/MERGED_IMAGE)
    image = (site/MERGED_IMAGE).read_bytes()
    result = dict(kind='gegi_shared_clock_public_v1', plane_study_sha256=pool_sha, windows=plane['windows'],
                  reports_sha256=report_hashes, source_sha256=source_hashes, blocks=blocks, views=views,
                  merged_examples=examples, controls=controls,
                  merged_waveform_figure=dict(image_sha256=sha256(image).hexdigest(),
                                              image_size_px=unpack_from('>II', image, 16)),
                  definitions={'recorded': measured['definitions'], 'reference': reference['design']},
                  timing=timing)
    validate_plane_binding(result, plane)
    (site/SUMMARY).write_text(json.dumps(result, allow_nan=False, separators=(',', ':'))+'\n',
                              encoding='utf-8', newline='\n')


def measured_fraction(layer, support):
    counts = layer['measured'][support]
    text = f'{counts["recorded_overlap"]}/{layer["triggers"]}'
    missing = counts['incomplete_coverage']
    return f'{text} ({missing} unresolved)' if missing else text


def reference_fractions(layer):
    counts = layer['reference']['group_onset_adc']
    total = layer['triggers']
    unresolved = counts.get('anchor_unknown', 0) + counts.get('incomplete', 0)
    return f'{counts.get("additional", 0)}/{total}', f'{unresolved}/{total}'


def nearby_fraction(layer):
    near = layer['reference']['inclusive_half_widths_ns']['6000']
    return f'{near["anchored_additional_groups"]}/{near["anchored_gap_denominator"]}'


def compact_controls(report, original_hash, timing):
    design, rows = report['design'], report['by_delay_ns']
    if (report['kind'] != 'gegi_saved_window_activity_controls_v1'
            or report['original_study_sha256'] != original_hash
            or design['relative_adc_support_ns'] != timing['support_bounds_ns']['adc']
            or [int(delay) for delay in rows] != design['delays_ns']):
        raise ValueError('GeGI positive controls differ from the saved matched-pulse study or ADC span')
    for key, total in report['counts'].items():
        if key in next(iter(rows.values())) and sum(row[key] for row in rows.values()) != total:
            raise ValueError('GeGI positive control counts do not close over the delays')
    for sample in report['representative_waveforms'].values():
        activity = sample['activity']
        if any(value != activity[key] for key, value in timing.items() if key != 'support_bounds_ns'):
            raise ValueError('GeGI positive control activity uses a different trigger setting')
    eligible = [row for row in report['trials'] if row['first_trigger_would_capture_two_strip']]
    single_rise = sum(sum(group['coincident'] for group in row['activity_groups']) == 1 for row in eligible)
    if len(eligible) != report['counts']['first_trigger_would_capture_two_strip']:
        raise ValueError('GeGI positive control eligibility count differs from its trial records')
    return dict(original_study_sha256=original_hash, design=design, counts=report['counts'], by_delay_ns=rows,
                ordinary_two_strip_windows_with_one_rise=single_rise)


def compact_merged(report, reference, timing):
    blocks = {b['provenance']['name']: b for b in reference['blocks'] if b['all_trigger_associations'].get('merged')}
    if (report['kind'] != 'gegi_merged_trigger_windows_v1' or report['status'] != 'completed'
            or REFERENCE_SHA256 not in report['input_sha256'].values()
            or [r['block'] for r in report['examples']] != list(blocks)):
        raise ValueError('GeGI recovered waveform examples belong to a different clock result')
    start, stop = timing['support_bounds_ns']['adc']
    sample_times = list(range(start, stop + 1, timing['sample_period_ns']))
    examples = []
    for row in report['examples']:
        block = blocks[row['block']]
        provenance = block['provenance']
        trigger, waveform = row['original_trigger'], row['waveform']
        x, y = (len(trigger[f'{face}_collecting_strips']) for face in ('x', 'y'))
        rises = [rise for rise in waveform['groups'] if rise['coincident']]
        fields = ('source', 'occurrence_id', 'group_id', 'metadata_sha256', 'first_ge_deposit_ns', 'last_ge_deposit_ns')
        groups = [tuple(group[key] for key in fields) for group in block['group_ledger']
                  if group['classification'] == 'merged']
        components = row['components']
        if (any(row[key] != provenance[key] for key in ('report_sha256', 'known_component_adc_sha256'))
                or any(row[key] != trigger[key] for key in ('trigger_time_ns', 'rise_end_ns'))
                or row['trigger_index'] in {event['trigger_index'] for event in block['events']}
                or (x, y) == (2, 2) or len(rises) != 1 or len(groups) != 2
                or groups != [tuple(group[key] for key in fields) for group in components]
                or row['relative_time_ns'] != sample_times
                or any(value != waveform[key] for key, value in timing.items() if key != 'support_bounds_ns')
                or waveform['time_ns'] != sample_times[waveform['fast_support_samples']-1:]):
            raise ValueError('GeGI recovered waveform differs from the frozen report and timing reference')
        rise = rises[0]
        if rise['trigger_reference_ns'] != 0 or rise['last_active_ns'] != row['rise_end_ns'] - row['trigger_time_ns']:
            raise ValueError('GeGI recovered waveform does not reproduce its recorded rise')
        examples.append(dict(block=row['block'], trigger_index=row['trigger_index'], trigger_time_ns=row['trigger_time_ns'],
                             report_sha256=row['report_sha256'], known_component_adc_sha256=row['known_component_adc_sha256'],
                             x_collecting_strips=x, y_collecting_strips=y, energy_keV=trigger['energy_keV'],
                             flags=trigger['event_energy_flags'], waveform=waveform,
                             recorded_rise_offsets_ns=[rise['first_active_ns'], rise['last_active_ns']],
                             simulated_deposit_onset_offsets_ns=[c['ge_deposit_relative_ns'][0] for c in components],
                             native_current_gap_ns=row['native_current_gap_ns']))
    return examples


def plot_merged(examples, target):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(8, 5.5), layout='constrained')
    FigureCanvasAgg(figure)
    axes = figure.subplots(2, 1, sharex=True, sharey=True)
    for axis, example in zip(axes, examples, strict=True):
        activity = example['waveform']
        times = activity['time_ns']
        start, stop = example['recorded_rise_offsets_ns']
        axis.axvspan(start, stop, color='#697a8a', alpha=.12, label='One recorded rise')
        for i, onset in enumerate(example['simulated_deposit_onset_offsets_ns']):
            axis.axvline(onset, color='#24684f', ls='-.', lw=1.3,
                         label='Simulated Ge deposit onset' if i == 0 else None)
        axis.plot(times, activity['x_change_keV'], color='#1765a0', marker='o', markersize=3, label='X face')
        axis.plot(times, activity['y_change_keV'], color='#a24913', marker='x', markersize=4, label='Y face')
        axis.axhline(activity['coincidence_threshold_keV'], color='#3b4249', ls='--', lw=1,
                     label='Coincidence threshold')
        strips = f'{example["x_collecting_strips"]} X × {example["y_collecting_strips"]} Y'
        axis.set_title(f'Trigger {example["trigger_index"]} · {strips}', loc='left')
        axis.set_ylabel('Face change\n(keV equivalent)')
        axis.grid(axis='y', color='#dbe2ea', linewidth=.7)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, ncols=3, fontsize=9, loc='outside upper center')
    axes[-1].set_xlabel('Time from recorded trigger (ns)')
    figure.savefig(target, dpi=125, facecolor='white')


def control_section(control):
    rows = []
    for delay, counts in control['by_delay_ns'].items():
        mixtures, evaluated = counts['mixtures'], counts['evaluated_windows']
        rows.append((f'{delay} ns', f'{counts["second_input_onset_inside_adc"]}/{mixtures}',
                     f'{counts["secondary_rearmed_coincident_rise"]}/{evaluated}',
                     f'{counts["full_clock_two_recorded_triggers"]}/{mixtures}'))
    counts_table = table(rows, ('Input delay', 'Second input inside ADC window', 'Second rearmed rise in window',
                                'Two accepted triggers on full clock'), 'Outcomes / controlled mixtures at each delay')
    counts = control['counts']
    ordinary = counts['first_trigger_would_capture_two_strip']
    return f'''<h5>Checking the window method with known inputs</h5>
<p>Each test combines two 250 keV pulses. The six tests at each delay cover same, adjacent and far strip pairs at two
sampling phases. Each saved window is centered on the first accepted trigger, including cases with one collecting strip
per face. The ordinary two-strip selection would save {ordinary}/{counts['mixtures']} first-trigger windows.
Of those, {control['ordinary_two_strip_windows_with_one_rise']}/{ordinary} showed one coincident rise.</p>
<p>At 600 ns the full clock recorded both triggers in all six cases and the second input arrived after the saved
ADC window.</p>
{counts_table}'''


def merged_section(site, data):
    image = (site/MERGED_IMAGE).read_bytes()
    figure = data['merged_waveform_figure']
    if sha256(image).hexdigest() != figure['image_sha256']:
        raise ValueError('GeGI merged-trigger waveform figure differs from its public summary')
    width, height = figure['image_size_px']
    relative = MERGED_IMAGE.relative_to('results').as_posix()
    first, second = data['merged_examples']
    return f'''<figure style="margin:1rem 0"><a href="{relative}">
<img loading="lazy" style="width:100%;height:auto" width="{width}" height="{height}" src="{relative}"
alt="Two recovered waveform windows. Each has two simulated germanium deposit onsets and one recorded rise."></a>
<figcaption>Green lines mark the two simulated deposit onsets for each trigger. The shaded span marks its one
recorded rise. Trigger {first['trigger_index']} returned {first['energy_keV']:.2f} keV.
Trigger {second['trigger_index']} had guard-electrode activity and no accepted energy.</figcaption></figure>'''


def section(site, plane):
    from gegi_merged_component_display import section as component_section

    data = json.loads((site/SUMMARY).read_bytes())
    validate_plane_binding(data, plane)
    views = data['views']
    full = views['full']['layers']['all']
    by_view = []
    for key, name in VIEWS.items():
        layer = views[key]['layers']['all']
        by_view.append((name, *(measured_fraction(layer, support) for support in ('adc', 'fast', 'slow')),
                        *reference_fractions(layer), nearby_fraction(layer)))
    ref_headings = ('Extra group · ADC', 'Unresolved group · ADC', 'Another group within 6 µs')
    rise_headings = tuple(f'Additional recorded rise · {span}' for span in ('ADC', 'fast', 'slow'))
    exposure_table = table(by_view, ('Exposure', *rise_headings, *ref_headings),
                           'Timing flags / all selected two-strip triggers')

    by_line = []
    for label in data['windows']:
        for key, name in VIEWS.items():
            layer = views[key]['layers'][label]
            by_line.append((f'{float(label.removesuffix("_keV")):,.0f} keV · {name}',
                            measured_fraction(layer, 'adc'), *reference_fractions(layer), nearby_fraction(layer)))
    line_table = table(by_line, ('Measured line window', rise_headings[0], *ref_headings),
                       'Timing flags / two-strip triggers in each line window')

    total = full['triggers']
    observed = full['measured']['adc']['recorded_overlap']
    extra = full['reference']['group_onset_adc'].get('additional', 0)
    waveform = full['waveform']
    timing = data['timing']
    intervals = ', '.join(f'{support.upper() if support == "adc" else support} {start:+g} to {stop:+g} ns'
                          for support, (start, stop) in timing['support_bounds_ns'].items())
    extra_current = full['reference']['native_adc']['native_current_adc'].get('additional', 0)
    all_refs = views['full']['reference_census']['all_trigger_associations']
    qualified = views['full']['selection']['qualified_triggers']
    relative = SUMMARY.relative_to('results').as_posix()
    return f'''<h4 id="gegi-shared-clock">Comparing close pulses on the shared clock</h4>
<p>A separate recorded rise overlapped the saved preamplifier samples in <strong>{observed}/{total}</strong> two-strip triggers.
The simulation clock identified an additional group depositing energy in germanium within the same sampled span
for <strong>{extra}/{total}</strong> triggers.</p>
<p>The recorded check compares each sample span with separately registered rises in the acquisition. The reference check
uses each distinct simulated deposit group's onset. A single onset without a unique assignment, or incomplete clock
coverage without a confirmed extra onset, leaves the result unresolved. Close groups can produce one recorded rise.</p>
{exposure_table}
<p>The spans relative to the recorded trigger time are {intervals}. Rechecking the saved ADC voltages found
{waveform['secondary_rearmed_coincident_rise']}/{waveform['evaluated']} windows with a second coincident rise after the
trigger search had rearmed. Rearming requires {timing['quiet_samples']} quiet samples. Coincidence requires both faces
to reach a {timing['coincidence_threshold_keV']:g} keV-equivalent change per {timing['sample_period_ns']:g} ns sample.</p>
<p>In a broader simulation-clock check, {nearby_fraction(full)} triggers with a unique group assignment and full clock
coverage had another deposit interval within 6 µs of the assigned group's interval. The signed pulse-current reference
found an additional current component on the ADC span for {extra_current}/{total} triggers. Preamplifier tails can
extend beyond the sample spans and active current intervals.</p>
<details><summary>Counts by measured gamma line</summary>{line_table}</details>
<p>Across all {qualified:,} qualified triggers, simulation timing associated {all_refs['unique_matched']:,} with one deposit
group, left {all_refs['ambiguous']} ambiguous and linked {all_refs['merged']} to two depositing groups each. Both triggers with
two groups fell outside the two-strip selection. For each example, the recovered ADC stream's checksum matched the
original acquisition and the local filtered samples reproduced the recorded rise.</p>
{merged_section(site, data)}
{component_section(site, data)}
{control_section(data['controls'])}
<p><a href="{relative}">Open the timing counts, definitions and source hashes (JSON)</a>.</p>'''
