"""Attach saved component readout controls to the shared-clock exhibit."""

from hashlib import sha256
from html import escape
import json
from pathlib import Path
from struct import unpack_from

from gegi_event_store import trace_hash
from gegi_shared_clock_display import MERGED_IMAGE, MERGED_SHA256, SUMMARY as CLOCK_SUMMARY, read_study, table


SUMMARY = Path('results/gegi-digital/shared-clock-components.json')
FIGURE = SUMMARY.with_suffix('.png')
STUDY_SHA256 = 'ce6c2960f88e904a52c76443b7ac1ed49ab3bc476e678ea12793191f694295f7'
NATIVE_SHA256 = '6c12ef11e90b24fdd382d30df2b3ae201cc33cadab4643a9f594f1486ee902d9'
VARIANTS = {'pair': 'Groups 1 + 2', 'component_1': 'Group 1 only', 'component_2': 'Group 2 only'}
CASE_KEYS = ('block', 'trigger_index', 'trigger_time_ns', 'report_sha256', 'known_component_adc_sha256')
REPORTS_SHA256 = {'component_controls': STUDY_SHA256, 'merged_windows': MERGED_SHA256, 'native_charge': NATIVE_SHA256}
GROUP_KEYS = ('source', 'occurrence_id', 'group_id', 'raw_event_id', 'campaign_initial_id', 'truth_edep_keV',
              'metadata_sha256', 'native_current_relative_ns')


def validate_binding(data, clock):
    if (data['kind'] != 'gegi_merged_component_controls_v1' or data['status'] != 'completed'
            or data['reports_sha256'] != REPORTS_SHA256
            or clock['reports_sha256']['merged_windows'] != MERGED_SHA256):
        raise ValueError('GeGI component controls belong to a different shared-clock study')
    counts = data['counts']
    cases = data['examples']
    if len(cases) != len(clock['merged_examples']) or counts['original_triggers'] != len(cases):
        raise ValueError('GeGI component controls differ from the original merged-trigger census')
    for case, original in zip(cases, clock['merged_examples'], strict=True):
        trigger = case['original_trigger']
        if (any(case[key] != original[key] for key in CASE_KEYS)
                or trigger['energy_keV'] != original['energy_keV']
                or trigger['event_energy_flags'] != original['flags']
                or case['original_activity'] != original['waveform']
                or case['original_adc_sha256'] != trace_hash(case['original_adc_codes'])
                or set(case['variants']) != set(VARIANTS)
                or case['variants']['pair']['adc_codes'] != case['original_adc_codes']
                or len(case['components']) != 2):
            raise ValueError('GeGI replay differs from the shared-clock trigger, original ADC or control set')
    if (counts['selected_native_components'] != sum(len(case['components']) for case in cases)
            or counts['paired_controls'] != len(cases) or counts['single_component_controls'] != 2 * len(cases)):
        raise ValueError('GeGI component controls do not close over the saved input groups')


def attach(site, study, recovered, charge):
    data = read_study(study, STUDY_SHA256)
    merged = read_study(recovered, MERGED_SHA256)
    native = read_study(charge, NATIVE_SHA256)
    clock = json.loads((site/CLOCK_SUMMARY).read_bytes())
    if (MERGED_SHA256 not in data['input_sha256'].values() or MERGED_SHA256 not in native['input_sha256'].values()
            or native['kind'] != 'gegi_merged_native_charge_v1' or native['status'] != 'completed'):
        raise ValueError('GeGI component controls or native charges lack the original merged-window binding')
    for case, original, endpoints in zip(data['examples'], merged['examples'], native['examples'], strict=True):
        expected_groups = [{k: v for k, v in group.items() if k != 'isolated_nominal_preamp_v'}
                           for group in original['components']]
        common = (*CASE_KEYS, 'original_trigger', 'rise_end_ns', 'clock_seed', 'noise_seed', 'relative_time_ns',
                  'contact_ids', 'baseline_v', 'volts_per_code', 'native_current_gap_ns')
        if (any(case[key] != original[key] for key in common) or case['components'] != expected_groups
                or case['original_adc_codes'] != original['adc_codes']):
            raise ValueError('GeGI component controls differ from archived group identities or recovered original ADCs')
        if (any(case[key] != endpoints[key] for key in ('block', 'trigger_index', 'trigger_time_ns'))
                or any(a[key] != b[key] for a, b in zip(expected_groups, endpoints['components'], strict=True)
                       for key in GROUP_KEYS)):
            raise ValueError('GeGI native charge report refers to different depositing groups')
        case['original_adc_sha256'] = trace_hash(original['adc_codes'])
        case['native_charge'] = endpoints
    del data['input_sha256']
    data['reports_sha256'] = REPORTS_SHA256
    data['native_source_sha256'] = native['source_sha256']
    data['native_design'] = native['design']
    validate_binding(data, clock)
    write_figure(site, data)


def write_figure(site, data):
    plot_controls(data['examples'], site/FIGURE)
    image = (site/FIGURE).read_bytes()
    data['figure'] = dict(sha256=sha256(image).hexdigest(), size_px=unpack_from('>II', image, 16))
    (site/SUMMARY).write_text(json.dumps(data, allow_nan=False, separators=(',', ':'))+'\n',
                              encoding='utf-8', newline='\n')


def consolidate_merged_figure(site):
    """Move the onset and rise markers onto the comparison figure in the staged site."""
    legacy = site/MERGED_IMAGE
    if not legacy.is_file() or not (site/SUMMARY).is_file():
        return
    clock = json.loads((site/CLOCK_SUMMARY).read_bytes())
    data = json.loads((site/SUMMARY).read_bytes())
    validate_binding(data, clock)
    previous = '9ae2d988b1e1c6d031a98d9063dff05577af83a3d136b6aa3f6b10f3b07d1772'
    if (legacy.is_symlink() or sha256(legacy.read_bytes()).hexdigest() != previous
            or sha256((site/FIGURE).read_bytes()).hexdigest() != data['figure']['sha256']):
        raise ValueError('The saved GeGI waveform figures differ from their publication.')
    write_figure(site, data)
    clock.pop('merged_waveform_figure', None)
    (site/CLOCK_SUMMARY).write_text(json.dumps(clock, separators=(',', ':'), allow_nan=False)+'\n',
                                    encoding='utf-8', newline='\n')
    legacy.unlink()


def plot_controls(cases, target):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(9, 6.2), layout='constrained')
    FigureCanvasAgg(figure)
    axes = figure.subplots(len(cases), 2, sharex=True, sharey='row', squeeze=False)
    for case, row in zip(cases, axes, strict=True):
        variants = case['variants']
        for axis, face in zip(row, ('x', 'y'), strict=True):
            original = case['original_activity']
            rise, = [group for group in original['groups'] if group['coincident']]
            axis.axvspan(rise['first_active_ns'], rise['last_active_ns'], color='#617482', alpha=.10,
                         label='Recorded rise')
            for i, group in enumerate(case['components']):
                axis.axvline(group['ge_deposit_relative_ns'][0], color='#6d4583', ls=':', lw=1.1,
                             label='Simulated deposit onset' if i == 0 else None)
            for source, label, color, linestyle in (
                (original, 'Original acquisition', '#161b22', '-'),
                (variants['pair']['activity'], VARIANTS['pair'], '#14639c', '--'),
                (variants['component_1']['activity'], VARIANTS['component_1'], '#216c48', ':'),
                (variants['component_2']['activity'], VARIANTS['component_2'], '#973e16', '-.'),
            ):
                axis.plot(source['time_ns'], source[f'{face}_change_keV'], color=color, ls=linestyle, lw=1.6,
                          label=label)
            axis.axhline(original['coincidence_threshold_keV'], color='#6b7178', lw=.8, label='Threshold per face')
            axis.grid(axis='y', color='#dbe2ea', linewidth=.7)
            axis.set_title(f'Trigger {case["trigger_index"]} · {face.upper()} face', loc='left')
        row[0].set_ylabel('Face change (keV equivalent)')
    handles, labels = axes[0][0].get_legend_handles_labels()
    figure.legend(handles, labels, loc='outside upper center', ncols=3, fontsize=9)
    figure.supxlabel('Time from original trigger (ns)')
    figure.savefig(target, dpi=135, facecolor='white')


def contact_name(cid):
    if cid in (17, 34):
        return 'X guard' if cid == 17 else 'Y guard'
    return f'X{cid:02d}' if cid < 17 else f'Y{cid-17:02d}'


def contacts(values):
    return ', '.join(contact_name(cid) for cid in values) or 'None'


def measure(value, *, signed=False):
    if value is None:
        return 'Unavailable'
    return format(value, '+.3f' if signed else '.3f')


def reasons(flags):
    labels = {'guard_collection': 'guard collection', 'face_energy_mismatch': 'X and Y energy sums disagree',
              'missing_face_strip_census': 'no collecting strip on one face',
              'no_persistent_coincident_charge_step': 'no persistent coincident charge step',
              'unresolved_strip_multiplicity': 'multiple collecting strips',
              'strip_energy_mismatch': 'X and Y strip energies disagree'}
    return ', '.join(escape(labels.get(flag, flag.replace('_', ' '))) for flag in flags)


def trigger_row(label, card, origin):
    flags = card['event_energy_flags'] or card['flags']
    outcome = measure(card['energy_keV'])
    if flags:
        outcome += f'<br>{reasons(flags)}'
    bounds = (f'{card["trigger_time_ns"] - origin:+g} to {card["rise_end_ns"] - origin:+g} ns')
    return (label, bounds, contacts(card['x_collecting_strips']), contacts(card['y_collecting_strips']),
            contacts(card['guard_contact_ids']), measure(card['x_sum_keV']), measure(card['y_sum_keV']), outcome)


def energy_table(case):
    origin = case['trigger_time_ns']
    rows = [trigger_row('Original acquisition', case['original_trigger'], origin)]
    for key, name in VARIANTS.items():
        control = case['variants'][key]
        cards = control['triggers']
        if not cards:
            missing = reasons(dict.fromkeys(rise['reason'] for rise in control['rejected_rises']))
            rows.append((name, 'No accepted trigger', 'Unavailable', 'Unavailable', 'Unavailable', 'Unavailable',
                         'Unavailable', f'Unavailable<br>{missing or "no coincident rise passed selection"}'))
        for index, card in enumerate(cards, 1):
            label = name if len(cards) == 1 else f'{name}, trigger {index}'
            rows.append(trigger_row(label, card, origin))
    return table(rows, ('Readout', 'Rise on original clock', 'X strips', 'Y strips', 'Guard collection',
                        'X sum (keV)', 'Y sum (keV)', 'Slow energy (keV)'),
                 f'Trigger {case["trigger_index"]} and all component control outcomes')


def neighbor_table(case):
    variants = case['variants']
    cards = [case['original_trigger'], *(t for v in variants.values() for t in v['triggers'])]
    collectors = {cid for card in cards for face in ('x', 'y') for cid in card[f'{face}_collecting_strips']}
    neighbors = sorted({n for cid in collectors for n in (cid-1, cid+1)
                        if (1 <= n <= 16 and 1 <= cid <= 16) or (18 <= n <= 33 and 18 <= cid <= 33)})
    channels = [case['original_fast_channels'], *(variants[key]['fixed_pair_reference_channels'] for key in VARIANTS),
                *(case['fixed_pair_reference_deltas'][key] for key in ('component_1', 'component_2'))]
    by_contact = [{row['contact_id']: row['fast_signal_keV_equiv'] for row in source} for source in channels]
    rows = [(contact_name(cid), *(measure(values[cid], signed=True) for values in by_contact)) for cid in neighbors]
    _, both, first, _, added_second, _ = by_contact
    strongest = max((cid for cid in neighbors if added_second[cid] is not None),
                    key=lambda cid: abs(added_second[cid]), default=None)
    highlight = '' if strongest is None else (
        f'<p>Adding group 2 changed {contact_name(strongest)} from {measure(first[strongest], signed=True)} to '
        f'{measure(both[strongest], signed=True)} keV equivalent, the largest change among the listed neighbors.</p>')
    return highlight + table(rows, ('Neighbor', 'Original', 'Groups 1 + 2', 'Group 1 only', 'Group 2 only',
                                   'Pair − group 1', 'Pair − group 2'),
                             'Signed fast area (keV equivalent) on the original gate')


def native_explanation(case, threshold):
    native = case['native_charge']
    first, second = native['components']
    a, b = first['endpoint_collections'], second['endpoint_collections']
    if len(a) == len(b) == 1 and a[0]['x_contact_id'] == b[0]['x_contact_id']:
        x, y1, y2 = (contact_name(cid) for cid in (a[0]['x_contact_id'], a[0]['y_contact_id'], b[0]['y_contact_id']))
        return (f'<p>In the native drift, both charge groups ended on {x}. Group 1 ended on {y1} and group 2 on {y2} '
                'on the opposite face. Neither group ended on a guard.</p>')
    guard = [pair for pair in b if (pair['x_contact_id'], pair['y_contact_id']) == (17, 34)]
    count = sum(len(pair['raw_row_indices']) for pair in guard)
    total = sum(len(pair['raw_row_indices']) for pair in b)
    strip_ids = second['threshold_summary']['faces']['Y']['above_threshold_strip_contact_ids']
    strips = [row for row in second['electrodes'] if row['contact_id'] in strip_ids
              and not row['endpoint_deposit_keV']]
    residuals = ' and '.join(f'{contact_name(row["contact_id"])} ({row["wired_final_induced_keV_equiv"]:.2f})'
                             for row in strips)
    sums = native['combined']['threshold_summary']['faces']
    energies = case['variants']['pair']['triggers'][0]['energy_estimate']
    capture = case['variants']['component_1']['triggers'][0]
    pairings = capture['two_strip_pairings']['compatible_pairing_count']
    return (f'<p>Group 2 sent carriers from {count}/{total} deposit rows to both guards. '
            f'{residuals} retained induced signals in keV equivalent at the end of the drift, with zero endpoint '
            f'deposits. Including strips at or above {threshold:g} keV equivalent, the combined native sums were '
            f'{sums["X"]["above_threshold_strip_keV_equiv"]:.2f} on X and '
            f'{sums["Y"]["above_threshold_strip_keV_equiv"]:.2f} on Y. '
            'The slow-electronics sums from the original acquisition appear in the table. '
            f'In the paired readout, the difference X minus Y was {energies["x_minus_y_keV"]:+.2f} keV, exceeding a '
            f'{energies["closure_tolerance_keV"]:.2f} keV tolerance in magnitude. Group 1 alone passed two-strip capture '
            f'with {pairings} energy-compatible X/Y pairing.</p>')


def section(site, clock):
    if not (site/SUMMARY).is_file():
        return ''
    data = json.loads((site/SUMMARY).read_bytes())
    validate_binding(data, clock)
    figure = data['figure']
    if sha256((site/FIGURE).read_bytes()).hexdigest() != figure['sha256']:
        raise ValueError('GeGI component control figure differs from its public summary')
    width, height = figure['size_px']
    image_path = FIGURE.relative_to('results').as_posix()
    json_path = SUMMARY.relative_to('results').as_posix()
    cases = []
    repeatability = []
    threshold = data['native_design']['native_terminal_threshold_keV_equiv']
    for case in data['examples']:
        timings = ' and '.join(f'{group["ge_deposit_relative_ns"][0]:+.2f}' for group in case['components'])
        adc = case['pair_vs_original']['adc']
        sensitivity = case['pair_vs_original']['sensitivity']
        repeatability.append((str(case['trigger_index']), f'{adc["unequal_codes"]}/{adc["compared_codes"]}',
                              *(f'{sensitivity[key]["unequal_codes"]}/{sensitivity[key]["compared_codes"]}'
                                for key in ('removing_history', 'removing_noise'))))
        cases.append(f'''<h6>Trigger {case['trigger_index']}</h6>
<p>The Ge groups started at {timings} ns relative to the original trigger at {case['trigger_time_ns']:,.0f} ns
on the clock of {escape(case['block'])}.</p>
{energy_table(case)}
{native_explanation(case, threshold)}
<details><summary>Signed fast signals on neighboring strips</summary>{neighbor_table(case)}</details>''')
    design = data['design']
    fast = ' to '.join(f'{t:+g}' for t in design['fast_gate_ns'])
    slow = ' to '.join(f'{t:+g}' for t in design['slow_gate_ns'])
    changes = table(repeatability, ('Trigger', 'Matched pair', 'Pair without history', 'Pair without noise'),
                    'ADC codes that changed relative to the original window')
    return f'''<h5 id="gegi-merged-components">Reading the two deposit groups separately</h5>
<p>For each original merged trigger, the controls replay the same two archived current signals together and one at a
time, at their original arrival times and ADC sampling phase. Both paired controls reproduce every original ADC code
in the saved window. To see the original slow energies and flags in Control, open the matching acquisition and expand
<strong>Inspect any recorded trigger</strong>.</p>
<figure style="margin:1rem 0"><a href="{image_path}"><img loading="lazy" style="width:100%;height:auto"
width="{width}" height="{height}" src="{image_path}"
alt="X and Y trigger-filter traces for both original merged triggers, their paired controls and each isolated group."></a>
<figcaption>Vertical purple lines mark the two simulated deposit onsets. The shaded span is the single recorded rise. Each panel uses the saved ADC window on the original clock.</figcaption></figure>
<p>The slow-energy table uses the {slow} ns flat-top gate after each accepted trigger. The fast-signal table uses the
same {fast} ns gate after the original trigger for all four inputs, so a change in the automatic trigger time cannot
move that comparison gate. The signed area is calibrated to an equivalent energy from a nominal pulser. The table
includes strips adjacent to any listed collecting strip.</p>
{''.join(cases)}
<details><summary>Matched noise and amplifier history</summary>
<p>The original continuous ADC includes the full exposure's amplifier history. All three replay controls use the same
original noise draws, ADC preamble baseline and known history within {design['history_cutoff_feedback_time_constants']}
feedback time constants of the focused slice. The diagnostics below remove one of these contributions from the paired replay.</p>
{changes}</details>
<p><a href="{json_path}">Open the component identities, ADC samples, all readout outcomes and source hashes (JSON)</a>.</p>'''
