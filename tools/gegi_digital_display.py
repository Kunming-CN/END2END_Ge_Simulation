"""Render the saved digital strip example in the Results hub."""
from collections import Counter
from hashlib import sha256
from html import escape
import json
import math
from pathlib import Path
import re


DIGITAL_OBSERVABLES = {
    'pair_cfd': 'X–Y timing within each pair',
    'centered_cfd': 'Centered timing of four collecting strips',
    'fast': 'Signed fast area of nine strips',
    'fast_and_centered_cfd': 'Signed fast area + centered timing',
}

DOUBLE_PULSE_FILE = 'results/gegi-digital/double-pulse.json'
SOURCE_EXPOSURE_FILE = 'results/gegi-digital/source-exposure.json'
EVENT_ENERGY_FILE = 'results/gegi-digital/event-energy.json'
EDGE_POSITION_FILE = 'results/gegi-digital/edge-position.json'
DUAL_SOURCE_HIT_MAP_FILE = 'results/gegi-digital/dual-source-hit-map.json'
DUAL_SOURCE_REPORT_HASHES = (
    '09cbc0e5a5821287b87acabe5d669fb0d7b1fccd8555b5b637479df82e2a99f7',
    '3cb7a68854a2526dbf88d62cc20883b26f1359bdc7166b8867b9d7a049763a5c',
)
PULSE_TOPOLOGIES = {
    'same_strips': 'Same strips',
    'adjacent_strips': 'Adjacent strips',
    'far_strips': 'Far strips',
}
PULSE_OUTCOMES = {
    'two_distinct_triggers': 'Triggers',
    'both_energy_available': 'Energy',
    'both_xy_available': 'XY',
}
PULSE_NOISE = {'nominal': 'Nominal electronic noise', 'none': 'Without electronic noise'}
PULSE_STABILITY = {
    **PULSE_OUTCOMES,
    'both_energy_within_tolerance': 'Energy within tolerance',
    'both_xy_within_tolerance': 'XY within tolerance',
    'both_energy_and_xy_within_tolerance': 'Energy and XY within tolerance',
}
PULSE_DESIGN = (
    'delays_ns', 'adc_phases_ns', 'ordered_energies_keV', 'noise_rms_V', 'match_tolerance_ns',
    'relative_energy_tolerance', 'xy_isolated_radial_tolerance_mm', 'minimum_stable_suffix_points',
    'noise_base_seed', 'noise_seed_rule', 'record_end_ns', 'selection', 'source_coordinate_exclusion_mm',
    'matching', 'trigger_success', 'feature_success', 'metric_denominators', 'stability', 'electronics', 'scope',
)
PULSE_HASHES = ('digital_profile_sha256', 'digital_timing_sha256', 'substrip_calibration_sha256',
                'field_cache_sha256', 'model_sha256')


def attach_double_pulse(site, report_path):
    source = report_path.read_bytes()
    report = json.loads(source)
    if report.get('kind') != 'gegi_saved_double_pulse_scan_v1' or report.get('status') != 'completed':
        raise ValueError('Expected a completed GeGI double-pulse scan.')
    target = site/DOUBLE_PULSE_FILE
    if not (target.parent/'event.json').is_file():
        raise ValueError('The GeGI digital example must be installed to publish its double-pulse study.')
    design = {key: report['design'][key] for key in PULSE_DESIGN}
    groups = {(noise, topology) for noise in PULSE_NOISE for topology in PULSE_TOPOLOGIES}
    expected = {(noise, topology, delay) for noise, topology in groups for delay in design['delays_ns']}
    summary = report['summary']
    if len(summary) != len(expected) or {(r['noise'], r['topology'], r['delay_ns']) for r in summary} != expected:
        raise ValueError('The GeGI double-pulse scan is missing or duplicating a trial group.')
    fields = ('topology', 'noise', 'delay_ns', 'trials', *PULSE_STABILITY, 'both_pixels_correct',
              'both_fast_ratios_available', 'truth_pulses', 'missing_truth_pulses', 'unmatched_triggers',
              'one_trigger_for_two', 'single_trigger_multiple_collecting_strips', 'no_matched_triggers',
              'reconstructed_triggers', 'false_triggers', 'electrode_pileup', 'pulse_availability', 'metrics')
    public_summary = []
    for row in summary:
        n = row['trials']
        triggers = row['two_distinct_triggers']
        if (n <= 0 or not 0 <= row['both_energy_within_tolerance'] <= row['both_energy_available'] <= triggers <= n
                or not 0 <= row['both_xy_within_tolerance'] <= row['both_xy_available'] <= triggers):
            raise ValueError('GeGI double-pulse outcomes do not match their trial denominator.')
        public_summary.append({key: row[key] for key in fields})
    isolated_fields = ('topology', 'noise', 'trials', 'matched_triggers', 'energy_available',
                       'xy_available', 'correct_pixel', 'unmatched_triggers', 'x_available', 'y_available',
                       'both_fast_ratios_available', 'metrics')
    isolated = [{key: row[key] for key in isolated_fields} for row in report['isolated_summary']]
    if len(isolated) != len(groups) or {(r['noise'], r['topology']) for r in isolated} != groups:
        raise ValueError('The GeGI double-pulse scan is missing or duplicating isolated controls.')
    stable_fields = ('topology', 'noise', 'criterion', 'stable_from_ns', 'first_full_pass_ns',
                     'regressions_after_first_full_pass_ns', 'count_decrease_delays_ns')
    stability = [{key: row[key] for key in stable_fields} for row in report['stability']]
    if (len(stability) != len(groups)*len(PULSE_STABILITY)
            or {(r['noise'], r['topology'], r['criterion']) for r in stability}
            != {(noise, topology, key) for noise, topology in groups for key in PULSE_STABILITY}):
        raise ValueError('The GeGI double-pulse scan is missing or duplicating a stability outcome.')
    provenance = report['provenance']
    hashes = {key: provenance[key] for key in PULSE_HASHES}
    sources = provenance['source_sha256']
    project = Path(__file__).resolve().parents[1]
    for name, digest in sources.items():
        path = (project/name).resolve()
        if (Path(name).is_absolute() or not path.is_relative_to(project) or not path.is_file()
                or sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError(f'GeGI double-pulse source changed after the scan: {name}')
    counts = report['counts']
    if (sum(row['trials'] for row in public_summary) != counts['paired_trials']
            or sum(row['trials'] for row in isolated) != counts['isolated_trials']):
        raise ValueError('GeGI double-pulse trial counts do not match the scan totals.')
    data = dict(kind=report['kind'], status=report['status'], design=design, counts=counts, summary=public_summary,
                pairs=report['pairs'], pair_summary=report['pair_summary'], isolated_summary=isolated,
                empty_summary=report['empty_summary'], stability=stability,
                provenance=dict(**hashes, report_sha256=sha256(source).hexdigest(),
                                source_sha256=sources, input_sha256=sorted(provenance['input_sha256'].values()),
                                field_precision_bits=provenance['field_precision_bits'],
                                native_settings=provenance['native_settings'],
                                python=provenance['python'], numpy=provenance['numpy']))
    target.write_text(json.dumps(data, allow_nan=False, separators=(',', ':'))+'\n',
                      encoding='utf-8', newline='\n')


def pulse_table(scan, noise):
    grid = {(row['delay_ns'], row['topology']): row for row in scan['summary'] if row['noise'] == noise}
    delays = sorted({delay for delay, _ in grid})
    rows = []
    for delay in delays:
        cells = []
        for topology in PULSE_TOPOLOGIES:
            group = grid[delay, topology]
            n = group['trials']
            for key in PULSE_OUTCOMES:
                passed = group[key]
                shade = ' style="background:#ecf6f2"' if passed == n else ''
                cells.append(f'<td{shade}>{passed}/{n}</td>')
        rows.append(f'<tr><th scope="row">{delay:g}</th>{"".join(cells)}</tr>')
    group_headings = ''.join(f'<th colspan="3" scope="colgroup">{label}</th>'
                             for label in PULSE_TOPOLOGIES.values())
    headings = ''.join(f'<th scope="col">{label}</th>'
                       for _ in PULSE_TOPOLOGIES for label in PULSE_OUTCOMES.values())
    return f'''<div role="region" aria-label="{PULSE_NOISE[noise]} comparison" tabindex="0" style="overflow-x:auto">
<table style="min-width:670px;font-variant-numeric:tabular-nums">
<caption style="text-align:left;font-weight:600">{PULSE_NOISE[noise]} · successful trials / all trials</caption>
<colgroup span="1"></colgroup><colgroup span="3"></colgroup><colgroup span="3"></colgroup><colgroup span="3"></colgroup>
<thead><tr><th scope="col" rowspan="2">Delay (ns)</th>{group_headings}</tr><tr>{headings}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>'''


def pulse_controls(scan):
    isolated = {(r['noise'], r['topology']): r for r in scan['isolated_summary']}
    stability = {(r['noise'], r['topology'], r['criterion']): r['stable_from_ns'] for r in scan['stability']}
    empty = {row['noise']: row for row in scan['empty_summary']}
    isolated_rows, stable_rows = [], []
    for noise, condition in PULSE_NOISE.items():
        for topology, label in PULSE_TOPOLOGIES.items():
            row = isolated[noise, topology]
            start = f'<tr><th scope="row">{label}</th><td>{condition}</td>'
            cells = ''.join(f'<td>{row[key]}/{row["trials"]}</td>'
                            for key in ('matched_triggers', 'energy_available', 'xy_available', 'correct_pixel'))
            isolated_rows.append(f'{start}{cells}</tr>')
            delays = [stability[noise, topology, key] for key in PULSE_STABILITY]
            cells = ''.join(f'<td>{delay:g}</td>' if delay is not None else '<td>—</td>' for delay in delays)
            stable_rows.append(f'{start}{cells}</tr>')
    design = scan['design']
    return f'''<details><summary>Controls and stable scan ranges</summary>
<p>The controls replay each input pulse by itself. The paired-energy tolerance is
{design["relative_energy_tolerance"]:.1%} relative to the isolated energy estimate. The paired XY tolerance is
{design["xy_isolated_radial_tolerance_mm"]:g} mm radially from the isolated position estimate.</p>
<div style="overflow-x:auto"><table>
<caption style="text-align:left">Isolated pulse controls · successful trials / all trials</caption>
<thead><tr><th scope="col">Strip relation</th><th scope="col">Noise</th><th scope="col">Matched trigger</th>
<th scope="col">Energy</th><th scope="col">XY</th><th scope="col">Correct pixel</th></tr></thead>
<tbody>{''.join(isolated_rows)}</tbody></table></div>
<p>Empty controls had {empty["nominal"]["false_triggers"]} false triggers in {empty["nominal"]["trials"]} noisy windows
and {empty["none"]["false_triggers"]} in {empty["none"]["trials"]} noiseless windows.</p>
<p>A stable scan range starts when all trials pass at that delay and every subsequent sampled delay,
with at least {design["minimum_stable_suffix_points"]} sampled delays in the range. A dash marks a missing all-pass range.</p>
<div style="overflow-x:auto"><table>
<caption style="text-align:left">Start of the stable scan range (ns)</caption>
<thead><tr><th scope="col">Strip relation</th><th scope="col">Noise</th>
{''.join(f'<th scope="col">{name}</th>' for name in PULSE_STABILITY.values())}</tr></thead>
<tbody>{''.join(stable_rows)}</tbody></table></div></details>'''


def double_pulse_section(scan):
    design = scan['design']
    energies = ', '.join(' + '.join(f'{e:g}' for e in pair) for pair in design['ordered_energies_keV'])
    phases = ' and '.join(f'{phase:g}' for phase in design['adc_phases_ns'])
    starts = {(r['topology'], r['criterion']): r['stable_from_ns']
              for r in scan['stability'] if r['noise'] == 'nominal'}
    trigger = {starts[topology, 'two_distinct_triggers'] for topology in PULSE_TOPOLOGIES}
    nearby = {starts[topology, 'both_energy_and_xy_within_tolerance']
              for topology in ('same_strips', 'adjacent_strips')}
    far_energy = starts['far_strips', 'both_energy_within_tolerance']
    overview = ''
    if len(trigger) == len(nearby) == 1 and None not in trigger | nearby and far_energy is not None:
        overview = f'''<p>With nominal noise, all groups sustained two matched triggers from <strong>{trigger.pop():g} ns</strong>
on this scan. Same- and adjacent-strip groups met both energy and XY tolerances from <strong>{nearby.pop():g} ns</strong>.
Far-strip energy met its tolerance from <strong>{far_energy:g} ns</strong>.</p>'''
    return f'''<h2 id="gegi-double-pulse">When can GeGI resolve two close pulses?</h2>
{overview}
<p>Two simulated native charge responses were shifted in time and added before digitization. The same electronic
stream supplied the triggers, energies and strip positions. Same-strip pulses share both collecting strips.
Adjacent pulses differ by one X strip, and one adjacent pair shares a Y strip. Far pulses are separated by at
least three strip pitches on each face.</p>
<p><strong>Triggers</strong> requires exactly two reconstructed triggers at a nonzero delay, each within
±{design["match_tolerance_ns"]:g} ns of the expected trigger time. <strong>Energy</strong> and <strong>XY</strong>
also require the correct collecting strips for both pulses and a qualified energy or both calibrated lateral
coordinates, respectively. Each fraction uses all trials at that delay and strip relation.</p>
{pulse_table(scan, 'nominal')}
<details><summary>Compare without electronic noise</summary>{pulse_table(scan, 'none')}</details>
{pulse_controls(scan)}
<p>The {scan["counts"]["paired_trials"]:,} paired trials used ordered energies of {energies} keV with sampling phases of
{phases} ns. Nominal noise was
{design["noise_rms_V"]["nominal"]*1e6:g} µV RMS before analog-to-digital conversion. Far-strip pairs include a
location outside the position calibration. The sampled responses characterize the nominal simulated electronics.</p>
<p><a href="gegi-digital/double-pulse.json">Open double-pulse counts, errors and scan settings (JSON)</a>.</p>'''


def spectrum_series(histogram, label):
    counts = histogram['counts'].copy()
    counts[0] -= histogram['exact_zero']
    return dict(label=label, counts=counts, total=histogram['entries'],
                **{key: histogram[key] for key in ('underflow', 'overflow', 'exact_zero')})


def event_energy_section(study, trigger_summary):
    counts = next(row for row in study['summary'] if row['source'] == row['arrival_class'] == 'all')
    missing = counts['qualified_triggers'] - counts['baseline_energies']
    guards = counts['remaining_without_energy_flags'].get('guard_collection', 0)
    multiplicity = trigger_summary['missing_energy_flags'].get('unresolved_strip_multiplicity', 0)
    recovered = counts['additional_baseline_flags'].get('unresolved_strip_multiplicity', 0)
    bias = []
    for key, reference in (('additional_bias_vs_truth_keV', 'the simulated Ge deposit'),
                           ('additional_bias_vs_isolated_keV', 'the matched isolated replay')):
        error = counts[key]
        if error['n']:
            bias.append(f'Compared with {reference}, the mean energy difference was {error["mean"]:+.4f} keV '
                        f'and the root-mean-square difference was {error["rms"]:.3f} keV ({error["n"]:,} matches).')
    multiplicity_text = f' This recovers {recovered:,} of {multiplicity:,} triggers flagged for strip multiplicity.' if multiplicity else ''
    return f'''
<h3 id="gegi-event-energy">Slow energy from multiple collecting strips</h3>
<p><strong>{counts['combined_energies']:,}/{counts['qualified_triggers']:,} qualified triggers had a slow energy</strong>
after retaining the {counts['baseline_energies']:,} single-pixel values and recovering {counts['additional_energies']:,}
of {missing:,} triggers previously without an estimate.{multiplicity_text}</p>
<p>The method sums qualified collecting strips on each face and averages the two sums when they agree. Additional entries
require multiple collecting strips on at least one face. Guard collection was flagged in {guards:,} of the
{counts['remaining_without_energy']:,} triggers still without an energy. Position and Compton reconstruction require
a separate eligible strip pairing and any applicable position calibration.</p>
<p>The spectrum uses the ADC measurements, including {counts['additional_merged']:,} added merged-trigger totals.
Each merged trigger contributes one aggregate energy. The {counts['additional_unique_matched']:,} added entries with
a unique deposit match are eligible for per-deposit bias checks. {' '.join(bias)}</p>
<p><a href="gegi-digital/event-energy.json">Open the energy comparison, isolated controls and spectra (JSON)</a>.</p>'''


def dual_source_hit_map_section(data):
    counts, totals = data['counts'], data['totals']
    peak = max(map(max, counts))
    columns = ''.join(f'<th scope="col">X{x:02d}</th>' for x in data['axes']['x_contact_ids'])
    rows = []
    for y, row in reversed(list(zip(data['axes']['y_contact_ids'], counts, strict=True))):
        cells = []
        for count in row:
            background = f'hsl(186 70% {96-56*math.sqrt(count/peak):.1f}%)' if count else '#f6f8fa'
            cells.append(f'<td style="background:{background}">{count}</td>')
        rows.append(f'<tr><th scope="row">Y{y-17:02d}</th>{"".join(cells)}</tr>')
    return f'''<style>
.gegi-hit-map{{margin:1rem 0;max-width:760px}}
.gegi-hit-map th,.gegi-hit-map td{{padding:.28rem .34rem;min-width:2.15rem;text-align:center;font-variant-numeric:tabular-nums;color:#122126}}
.gegi-hit-map table{{font-size:.82rem;width:max-content;margin:0}}
.gegi-hit-map tbody th{{position:sticky;left:0;z-index:1;background:#fff}}
</style>
<h3 id="gegi-dual-source-hit-map">Measured detector hit map</h3>
<p><strong>{totals['mapped_single_pixel_triggers']:,} of {totals['qualified_triggers']:,}</strong> qualified triggers
gave a single-pixel slow energy and contribute one count at their X/Y strip intersection.
The other triggers gave {totals['multi_strip_energy_triggers']:,} multi-strip energy totals and
{totals['triggers_without_energy']:,} with no qualified energy.</p>
<figure class="gegi-hit-map">
<div role="region" aria-label="Detector hit map by X and Y strip" tabindex="0" style="overflow-x:auto">
<table><thead><tr><th scope="col">Y / X</th>{columns}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<figcaption>Positive detector X points right and positive Y points up. Darker cells indicate more triggers.
<a href="gegi-digital/dual-source-hit-map.json">Download map counts and settings (JSON)</a>.</figcaption></figure>'''


def _checked_dual_source_report(path, expected_sha):
    from gegi_pixel_map import project_pixel_map
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha:
        raise ValueError('Saved dual-source acquisition receipt changed.')
    report = json.loads(raw)
    projection = project_pixel_map(report)
    if projection['status'] != 'available':
        raise ValueError('Expected a measured single-pixel population in the saved acquisition.')
    return report, projection


def _dual_source_map_binding(exposure, energy):
    return {'source_exposure_sha256': exposure['provenance']['report_sha256'],
            'event_energy_sha256': energy['binding']['report_sha256']}


def public_dual_source_hit_map(site, report_paths):
    """Project the reference trigger census and validate the changed-activity acquisition."""
    if not all((site/ref).is_file() for ref in (SOURCE_EXPOSURE_FILE, EVENT_ENERGY_FILE)):
        raise ValueError('Publish the GeGI source exposure and event energy before the detector hit map.')
    exposure, energy = (json.loads((site/ref).read_bytes()) for ref in (SOURCE_EXPOSURE_FILE, EVENT_ENERGY_FILE))
    main, alternate = (_checked_dual_source_report(path, digest) for path, digest in
                       zip(report_paths, DUAL_SOURCE_REPORT_HASHES, strict=True))
    report, projection = main
    comparison, validation = alternate
    totals = projection['totals']
    source_design, acquisition = exposure['design'], report['design']
    if (report['receipt']['known_component_adc_sha256'] != energy['baseline_parity']['known_component_adc_sha256']
            or energy['binding']['exposure_sha256'] != exposure['provenance']['report_sha256']
            or any(report['exposure'][key] != exposure['exposure'][key] for key in
                   ('clock_live_time_ns', 'qualified_adc_live_time_ns', 'total_live_adc_samples', 'qualified_live_adc_samples'))
            or any(acquisition[key] != source_design[key] for key in
                   ('clock_seed', 'noise_seed', 'sample_period_ns', 'adc_phase_ns'))
            or acquisition['adc_noise_rms_v'] != source_design['nominal_noise_rms_v']
            or {s['key']: s['activity_bq'] for s in report['sources']} != source_design['source_activities_bq']
            or totals['qualified_triggers'] != exposure['trigger_summary']['qualified_triggers']
            or any(report['spectra'][new] != energy['spectra'][old] for new, old in
                   (('single_pixel', 'baseline'), ('additional_multi_strip', 'additional'),
                    ('combined', 'baseline_plus_additional')))):
        raise ValueError('The reference hit map differs from the published exposure or energy census.')
    return {
        'kind': 'gegi_dual_source_hit_map_public_v1',
        'axes': projection['axes'], 'counts': projection['counts'], 'totals': totals,
        'design': {'clock_live_time_ns': report['exposure']['clock_live_time_ns'],
                   'qualified_adc_live_time_ns': report['exposure']['qualified_adc_live_time_ns'],
                   'activities_bq': source_design['source_activities_bq'],
                   'selection': 'One count per qualified trigger with a single-pixel slow energy.',
                   'matrix_order': 'Rows Y01 through Y16 and columns X01 through X16. The chart places Y16 at top.'},
        'validation': {'clock_live_time_ns': comparison['exposure']['clock_live_time_ns'],
                       'activities_bq': {s['key']: s['activity_bq'] for s in comparison['sources']},
                       'totals': validation['totals']},
        'binding': {**_dual_source_map_binding(exposure, energy),
                    'reference_report_sha256': DUAL_SOURCE_REPORT_HASHES[0],
                    'validation_report_sha256': DUAL_SOURCE_REPORT_HASHES[1]},
    }


def attach_dual_source_hit_map(site, report_paths):
    result = public_dual_source_hit_map(site, report_paths)
    (site/DUAL_SOURCE_HIT_MAP_FILE).write_text(json.dumps(result, allow_nan=False, separators=(',', ':'))+'\n',
                                                encoding='utf-8', newline='\n')


def exposure_section(data, event_energy=None, hit_map=None):
    design = data['design']
    exposure = data['exposure']
    triggers = data['trigger_summary']
    totals = {row['arrival_class']: row for row in data['summary'] if row['source'] == 'all'}
    overall = totals['all']
    rows = []
    near = design['any_source_close_neighbor_ns']/1000
    for category, label in (('isolated', 'Isolated'), ('close', f'Another Ge group within {near:g} µs')):
        row = totals[category]
        n = row['qualified_deposits']
        rows.append(f'''<tr><th scope="row">{label}</th><td>{row['deposits']:,}</td><td>{n:,}</td>
<td>{row['unique_matched']:,}/{n:,}</td><td>{row['matched_energy_qualified']:,}/{n:,}</td></tr>''')
    from spectrum_plot import svg
    histogram = data['slow_spectrum']
    edges = histogram['bin_edges_keV']
    series = spectrum_series(histogram, 'Qualified trigger energy')
    view = dict(edges=edges, view=[edges[0], edges[-1]], series=[series],
                title='Slow-energy spectrum from qualified simulated triggers', xlabel='Slow energy (keV)')
    caption = '<strong>Qualified slow-energy spectrum</strong>'
    figure = '<figure style="margin:16px 0">'
    notes = f'''{sum(series['counts']):,} entries in {edges[1]-edges[0]:g} keV bins from {edges[0]:g} to {edges[-1]:g} keV,
with lower bin edges included. Underflow {series['underflow']:,}, overflow {series['overflow']:,}, exact zeros {series['exact_zero']:,}.
The spectrum includes every qualified trigger with a slow-energy estimate.'''
    energy_rule = 'A slow energy also requires a qualified collecting strip on each face and agreement between their energies.'
    comparison = ''
    if event_energy is not None:
        energy_rule = 'The baseline slow-energy route requires one qualified collecting strip on each face and agreement between their energies.'
        comparison = event_energy_section(event_energy, triggers)
        addition = spectrum_series(event_energy['spectra']['additional'], 'Additional face-summed energies')
        if addition['total']:
            series['label'] = 'Single-pixel baseline'
            view['series'].append(addition)
            view['title'] = 'Single-pixel and additional face-summed energies'
            figure = '<figure class="gegi-event-energy-spectrum" style="margin:16px 0">'
            caption += ' · <span style="color:#15745b">Single-pixel baseline (solid)</span>' \
                       ' · <span style="color:#72529a">Additional face sums (dashed)</span>'
            notes = f'''{sum(series['counts']):,} baseline and {sum(addition['counts']):,} additional entries in view.
Both use {edges[1]-edges[0]:g} keV bins from {edges[0]:g} to {edges[-1]:g} keV, with lower edges included.
Baseline underflow, overflow and exact zeros are {series['underflow']:,}, {series['overflow']:,} and {series['exact_zero']:,}.
Additional underflow, overflow and exact zeros are {addition['underflow']:,}, {addition['overflow']:,} and {addition['exact_zero']:,}.'''
    chart = svg(view, 'linear').replace('<svg ', '<svg style="display:block;width:100%;max-width:760px;height:auto" ', 1)
    if len(view['series']) > 1:
        chart = '<style>.gegi-event-energy-spectrum .spectrum-step+.spectrum-step{stroke:#72529a;stroke-dasharray:4 2}</style>' + chart
    activities = design['source_activities_bq']
    unknown = overall['history_unqualified'] + overall['history_boundary_unknown']
    map_section = dual_source_hit_map_section(hit_map) if hit_map is not None else ''
    return f'''<h2 id="gegi-source-exposure">One exposure with Cs-137 and Co-60</h2>
<p>In this {exposure['clock_live_time_ns']/1e9:g} s simulated exposure, {overall['unique_matched']:,} of
{overall['qualified_deposits']:,} qualified Ge deposit groups matched a unique trigger, and
{overall['matched_energy_qualified']:,} had a qualified slow energy.</p>
<p>Independent source clocks used example activities of {activities['cs137-left']/1000:g} kBq for Cs-137 and
{activities['co60-right']/1000:g} kBq for Co-60. Delayed deposits from earlier parent decays can enter the exposure.
The electronics start from zero with a {1000/design['sample_period_ns']:g} MS/s digitizer and
{design['nominal_noise_rms_v']*1e6:g} µV RMS synthetic noise.</p>
<p>Of {overall['deposits']:,} Ge deposit groups, {overall['native_unavailable']:,} lacked a usable native charge signal and
{unknown:,} more fell in or near gaps in the signal history. Among qualified groups,
{overall['missed']:,} were missed, {overall['merged']:,} shared {triggers['merged']:,} merged triggers and
{overall['ambiguous']:,} had ambiguous matches.</p>
<div role="region" aria-label="Exposure group comparison" tabindex="0" style="overflow-x:auto">
<table style="min-width:580px;font-variant-numeric:tabular-nums"><thead><tr><th scope="col">Arrival neighborhood</th>
<th scope="col">Ge groups</th><th scope="col">Qualified</th><th scope="col">Unique match</th>
<th scope="col">Matched slow energy</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>Over {exposure['qualified_adc_live_time_ns']/1e9:.6f} s of qualified ADC time, the readout returned
{triggers['qualified_triggers']:,} triggers and {triggers['qualified_slow_energies']:,} usable slow energies.
{triggers['unmatched']:,} triggers lacked a matching deposit. A trigger uses the coincident rise on both faces.
{energy_rule}</p>{map_section}{comparison}
{figure}<figcaption>{caption}</figcaption>
{chart}<p class="muted">{notes}</p></figure>
<p>Arrival neighborhoods use deposition times from both sources. These counts apply to the qualified portion of the
simulated exposure. The JSON includes the signal-history rules, matching criteria and the noiseless close-pair cross-check.
<a href="gegi-digital/source-exposure.json">Open the exposure census, spectrum and settings (JSON)</a>.</p>'''


def attach_source_exposure(site, report_path):
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    if report.get('kind') != 'gegi_saved_two_source_exposure_v1' or report.get('status') != 'completed':
        raise ValueError('Expected a completed GeGI two-source exposure.')
    path = site/SOURCE_EXPOSURE_FILE
    if not (path.parent/'event.json').is_file():
        raise ValueError('Install the GeGI digital example before publishing the source exposure.')
    sources = report['source_sha256']
    project = Path(__file__).resolve().parents[1]
    for name, digest in sources.items():
        source = (project/name).resolve()
        if not source.is_relative_to(project/'tools') or sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError(f'GeGI source exposure input code changed after replay: {name}')
    fields = ('deposits', 'native_unavailable', 'history_unqualified', 'history_boundary_unknown', 'qualified_deposits',
              'unique_matched', 'missed', 'merged', 'ambiguous', 'matched_energy_qualified', 'matched_energy_agrees')
    summary = report['summary']
    groups = {(source, category) for source in ('all', 'cs137-left', 'co60-right')
              for category in ('all', 'isolated', 'close')}
    if len(summary) != len(groups) or {(r['source'], r['arrival_class']) for r in summary} != groups:
        raise ValueError('GeGI source exposure is missing or duplicating a census population.')
    for row in summary:
        n = row['qualified_deposits']
        if (any(type(row[key]) is not int or row[key] < 0 for key in fields)
                or sum(row[key] for key in ('native_unavailable', 'history_unqualified', 'history_boundary_unknown')) + n != row['deposits']
                or sum(row[key] for key in ('unique_matched', 'missed', 'merged', 'ambiguous')) != n
                or not row['matched_energy_agrees'] <= row['matched_energy_qualified'] <= row['unique_matched']):
            raise ValueError('GeGI source exposure counts do not close.')
    census = {(r['source'], r['arrival_class']): r for r in summary}
    for source, category in groups:
        totals = census[source, category]
        if (source == 'all' and any(totals[key] != sum(census[s, category][key] for s in ('cs137-left', 'co60-right'))
                                    for key in fields)
                or category == 'all' and any(totals[key] != sum(census[source, c][key] for c in ('isolated', 'close'))
                                             for key in fields)):
            raise ValueError('GeGI source exposure group totals do not close.')
    trigger_counts = report['trigger_summary']
    if (sum(trigger_counts[key] for key in ('unique_matched', 'merged', 'ambiguous', 'unmatched', 'history_boundary_unknown'))
            != trigger_counts['qualified_triggers']
            or trigger_counts['unique_matched'] != census['all', 'all']['unique_matched']
            or not 0 <= report['slow_spectrum']['entries'] == trigger_counts['qualified_slow_energies'] <= trigger_counts['qualified_triggers']):
        raise ValueError('GeGI source exposure trigger and spectrum counts do not close.')
    data = {key: report[key] for key in ('kind', 'status', 'design', 'summary', 'trigger_summary', 'slow_spectrum')}
    data['exposure'] = {key: report['exposure'][key] for key in
                        ('clock_live_time_ns', 'qualified_adc_live_time_ns', 'total_live_adc_samples',
                         'qualified_live_adc_samples', 'masked_live_time_ns', 'maximum_unseen_tail_lsb',
                         'sources', 'absolute_whole_exposure_efficiency')}
    data['parity'] = {key: report['parity'][key] for key in ('adc_codes_identical', 'candidate_windows',
                      'same_trigger_and_energy_status', 'max_slow_energy_delta_keV')}
    data['provenance'] = dict(report_sha256=sha256(report_bytes).hexdigest(), source_sha256=sources,
                              input_sha256=sorted(report['input_sha256'].values()))
    path.write_text(json.dumps(data, allow_nan=False, separators=(',', ':'))+'\n', encoding='utf-8', newline='\n')


def attach_event_energy(site, report_path):
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    if report.get('kind') != 'gegi_saved_two_source_event_energy_v1' or report.get('status') != 'completed':
        raise ValueError('Expected a completed GeGI two-source event energy study.')
    exposure = json.loads((site/SOURCE_EXPOSURE_FILE).read_bytes())
    exposure_hash = report['binding']['exposure_sha256']
    if exposure_hash != exposure['provenance']['report_sha256']:
        raise ValueError('GeGI energy comparison belongs to a different source exposure.')
    spectra = report['spectra']
    baseline, additional, combined = (spectra[key] for key in ('baseline', 'additional', 'baseline_plus_additional'))
    edges = baseline['bin_edges_keV']
    if (baseline != exposure['slow_spectrum'] or any(h['bin_edges_keV'] != edges for h in (additional, combined))
            or combined['counts'] != [a+b for a, b in zip(baseline['counts'], additional['counts'], strict=True)]
            or any(combined[key] != baseline[key]+additional[key] for key in ('entries', 'underflow', 'overflow', 'exact_zero'))):
        raise ValueError('The GeGI event energy comparison does not retain and extend the published baseline spectrum.')
    from spectrum_plot import validate_spec
    validate_spec(dict(edges=edges, view=[edges[0], edges[-1]],
                       series=[spectrum_series(value, label) for label, value in spectra.items()]))
    sources = report['binding']['source_sha256']
    project = Path(__file__).resolve().parents[1]
    for name, digest in sources.items():
        source = (project/name).resolve()
        if not source.is_relative_to(project/'tools') or sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError(f'GeGI event energy input code changed after replay: {name}')
    overall = next(row for row in report['summary'] if row['source'] == row['arrival_class'] == 'all')
    triggers = exposure['trigger_summary']['qualified_triggers']
    parity = report['baseline_parity']
    if (overall['qualified_triggers'] != triggers or parity['trigger_identities_matched'] != triggers
            or parity['baseline_exact'] != baseline['entries'] or not parity['identical_mask']
            or any(overall[key] != spectrum['entries'] for key, spectrum in
                   zip(('baseline_energies', 'additional_energies', 'combined_energies'), (baseline, additional, combined), strict=True))
            or combined['entries'] + overall['remaining_without_energy'] != triggers
            or sum(overall[key] for key in ('additional_unique_matched', 'additional_merged', 'additional_unassigned_other')) != additional['entries']):
        raise ValueError('The GeGI event energy and trigger counts do not close.')
    data = {key: report[key] for key in ('status', 'design', 'exposure_census', 'summary', 'geometry_summary',
                                        'spectra', 'isolated_acceptance', 'baseline_parity')}
    data['kind'] = 'gegi_saved_two_source_event_energy_public_v1'
    data['binding'] = dict(exposure_sha256=exposure_hash, report_sha256=sha256(report_bytes).hexdigest(),
                           source_sha256=sources, input_sha256=sorted(report['binding']['input_sha256'].values()))
    (site/EVENT_ENERGY_FILE).write_text(json.dumps(data, allow_nan=False, separators=(',', ':'))+'\n',
                                        encoding='utf-8', newline='\n')


def attach_edge_position(site, report_path):
    source = report_path.read_bytes()
    report = json.loads(source)
    if report.get('kind') != 'gegi_edge_position_single_group_study_v1' or report.get('status') != 'completed':
        raise ValueError('Expected a completed GeGI 2950 strip-edge position study.')
    example = json.loads((site/'results/gegi-digital/event.json').read_bytes())
    provenance = report['provenance']
    if provenance['digital_profile_sha256'] != example['profile_sha256']:
        raise ValueError('The strip-edge study uses a different digital readout profile.')
    project = Path(__file__).resolve().parents[1]
    for name, digest in provenance['source_sha256'].items():
        path = (project/name).resolve()
        if not path.is_relative_to(project/'tools') or sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'GeGI edge study source changed after evaluation: {name}')

    context = report['event_2950_context']
    if context['event_id'] != 2950:
        raise ValueError('The strip-edge study must describe simulated primary 2950.')
    original = next(row for row in example['energy_order_check']['candidates'] if row['event_id'] == 2950)
    event_sites = []
    if [edge['site'] for edge in report['edges']] != ['A', 'B']:
        raise ValueError('Expected the two scanned strip edges from primary 2950.')
    for edge, ref, old_site, old_error in zip(report['edges'], context['sites'], original['sites'],
                                              original['fit_error_to_simulated_centroids_mm'], strict=True):
        label = [old_site['x_strip'], old_site['y_strip']]
        if (edge['site'] != ref['site'] or edge['edge_id'] != ref['edge_id']
                or edge['original_pair_ids'] != old_site['contact_ids'] or edge['original_strips'] != label
                or not math.isclose(ref['old_waveform_fit_xyz_error_mm'], old_error, abs_tol=1e-9)
                or ref['new_event_fit_mm'] is not None):
            raise ValueError('Strip-edge study targets differ from the published primary 2950 sites.')
        axis = edge['axis']
        gap = [edge['original_metal_edge_mm'], edge['neighbor_metal_edge_mm']]
        scan_position = ref['truth_energy_centroid_mm'][axis]
        event_sites.append(dict(site=edge['site'], strip_names=label, axis=edge['axis_name'].upper(),
                                centroid_mm=ref['truth_energy_centroid_mm'],
                                offset_pitch=ref['truth_centroid_signed_xy_offsets_pitch'][axis],
                                projected_into_gap=min(gap) <= scan_position <= max(gap), gap_edges_mm=gap))

    design = report['design']
    offsets, depths = design['holdout_offsets_pitch'], design['holdout_depths_mm']
    expected = {(site['site'], offset, depth) for site in event_sites for offset in offsets for depth in depths}
    holdout = []
    for raw in report['holdout']:
        xyz = raw['position_mm']
        offset = next((v for v in offsets if math.isclose(v, raw['offset_pitch_fraction_toward_neighbor'], abs_tol=1e-12)), None)
        key = raw['site'], offset, xyz[2]
        if key not in expected:
            raise ValueError('GeGI edge study duplicated or changed a held-out point.')
        expected.remove(key)
        status = raw['endpoints']['terminal_contact_status']
        readout = raw['readout']['readout_status']
        predictions = {k: {name: p[name] for name in ('position_mm', 'status')}
                       for k, p in raw['predictions'].items()}
        position = predictions['extended_fast']['position_mm']
        holdout.append(dict(site=raw['site'], offset_pitch=offset, depth_mm=xyz[2], position_mm=xyz,
                            target_axis=raw['target_axis'], true_target_mm=raw['true_target_mm'],
                            signed_xy_offsets_pitch=raw['signed_xy_offsets_from_original_centers_pitch'],
                            projected_geometry=raw['projected_geometry'], in_gap=raw['projected_geometry'] == 'projected_gap',
                            terminal_status=status, shared_charge=raw['endpoints']['verified_shared_charge'],
                            readout_status=readout, predictions=predictions,
                            error_mm=None if position is None else position-raw['true_target_mm']))
    if expected or len(holdout) != report['counts']['holdout']:
        raise ValueError('GeGI edge study did not retain every held-out point.')
    summary = {r['site']: r for r in report['summary']}
    if len(report['summary']) != 3 or set(summary) != {'all', 'A', 'B'}:
        raise ValueError('Missing GeGI strip-edge coverage summaries.')
    for label, row in summary.items():
        points = [p for p in holdout if label in ('all', p['site'])]
        if row['n'] != len(points) or any(metrics['denominator'] != len(points)
                or metrics['evaluated'] != sum(p['predictions'][key]['position_mm'] is not None for p in points)
                for key, metrics in row['methods'].items()):
            raise ValueError('GeGI edge summary coverage differs from the held-out records.')
    data = {key: report[key] for key in ('status', 'design', 'counts', 'edges', 'event_2950_context', 'summary')}
    data.update(kind='gegi_edge_position_public_v1', event_sites=event_sites, held_out=holdout,
                provenance={**provenance, 'report_sha256': sha256(source).hexdigest(),
                            'input_sha256': sorted(provenance['input_sha256'].values())})
    (site/EDGE_POSITION_FILE).write_text(json.dumps(data, allow_nan=False, separators=(',', ':'))+'\n',
                                         encoding='utf-8', newline='\n')


def edge_position_section(study):
    def rms(value):
        return f'{value:.3f}'

    sites = study['event_sites']
    coordinates = []
    for site in sites:
        xyz = ', '.join(f'{x:.3f}' for x in site['centroid_mm'])
        label = '/'.join(map(escape, site['strip_names']))
        gap = ' to '.join(f'{x:.3f}' for x in sorted(site['gap_edges_mm']))
        projection = 'within' if site['projected_into_gap'] else 'just outside'
        coordinates.append(f'<li><strong>Site {escape(site["site"])} · {label}</strong> ({xyz}) mm. '
                           f'The centroid projects {site["offset_pitch"]:+.3f} pitch from the strip centre on '
                           f'{escape(site["axis"])}, {projection} the modeled gap from {gap} mm.</li>')
    table = {(p['offset_pitch'], p['site'], p['depth_mm']): p for p in study['held_out']}
    depths = sorted({depth for _, _, depth in table})
    offsets = sorted({offset for offset, _, _ in table})
    columns = [f'<th scope="colgroup" colspan="{len(depths)}">Site {escape(site["site"])} · {escape(site["axis"])}</th>'
               for site in sites]
    labels = [f'<th scope="col">z = {depth:g} mm</th>' for site in sites for depth in depths]
    rows = []
    for offset in offsets:
        cells = []
        for site in sites:
            for depth in depths:
                point = table[offset, site['site'], depth]
                if point['error_mm'] is not None:
                    value = f'{point["error_mm"]:+.3f} mm'
                elif point['terminal_status'] == 'ambiguous_terminal_contact':
                    value = 'Ambiguous contact'
                elif point['terminal_status'] == 'terminal_unverified':
                    value = 'Incomplete collection'
                elif point['readout_status'] == 'multiple_positive_slow_strips':
                    value = 'Multiple readout strips'
                else:
                    reasons = {'outside_measured_feature_hull': 'Outside model support',
                               'fast_or_cfd_unavailable': 'Missing signal feature',
                               'measured_pair_unsupported': 'Unsupported strip pair'}
                    value = reasons.get(point['predictions']['extended_fast']['status'], 'Unavailable')
                shade = ' style="background:#fff2d7"' if point['in_gap'] else ''
                if point['terminal_status'] == 'migrated_to_target_neighbor':
                    value += ' · adjacent strip'
                if point['in_gap']:
                    value += ' · gap'
                cells.append(f'<td{shade}>{value}</td>')
        rows.append(f'<tr><th scope="row">{offset:.3f}</th>{"".join(cells)}</tr>')
    validation = next(row for row in study['summary'] if row['site'] == 'all')
    methods = validation['methods']
    compared = validation['inner_extended_common_support']
    common = compared['extended_fast']['evaluated']
    error_text = (f' On the {common} points covered by both calibrations, the one-axis RMS errors were '
                  f'{rms(compared["frozen_inner"]["rms_mm"])} and '
                  f'{rms(compared["extended_fast"]["rms_mm"])} mm, respectively.' if common else '')
    ablation = validation['extended_fast_cfd_common_support']
    matched = ablation['extended_fast']['evaluated']
    timing_text = (f' On the {matched} points shared with the timing-only comparison, RMS error was '
                   f'{rms(ablation["extended_fast"]["rms_mm"])} mm with both observables, '
                   f'{rms(ablation["extended_cfd_only"]["rms_mm"])} mm with timing alone, and '
                   f'{rms(ablation["gap_midpoint_prior"]["rms_mm"])} mm at the known gap midpoint.' if matched else '')
    timing = methods['extended_cfd_only']
    timing_all = (f' Timing alone returned {timing["evaluated"]}/{validation["n"]} positions with '
                  f'{rms(timing["rms_mm"])} mm RMS.' if timing['evaluated'] else '')
    migrated = validation['endpoint_counts'].get('migrated_to_target_neighbor', 0)
    single_pair = validation['readout_counts'].get('single_slow_strip_per_face', 0)
    return f'''<h3 id="gegi-edge-position">Position calibration at the strip edge</h3>
<p>Both simulated deposition centroids in primary 2950 lie beyond the earlier ±0.4-pitch position range along one
axis. The following detector-coordinate XYZ positions are the simulated deposited-energy centroids.</p>
<ul>{''.join(coordinates)}</ul>
<p>We compared two calibrations of the same interpolation using the signed neighboring-strip response
and the measured timing difference between faces. At {study['design']['injection_energy_keV']:g} keV,
training on the inner reference points gave a coordinate for {methods['frozen_inner']['evaluated']}/{validation['n']} held-out injections.
Adding the edge references raised coverage to {methods['extended_fast']['evaluated']}/{validation['n']}.{error_text}
{timing_text}{timing_all} The midpoint comparison uses advance knowledge of which gap was scanned.</p>
<div role="region" aria-label="Held-out edge positions" tabindex="0" style="overflow-x:auto"><table>
<caption style="text-align:left">Extended estimate minus reference along the tested coordinate. Shading marks the modeled gap.</caption>
<colgroup span="1"></colgroup>{'<colgroup span="'+str(len(depths))+'"></colgroup>'*len(sites)}
<thead><tr><th scope="col" rowspan="2">Offset toward neighbor (pitch)</th>{''.join(columns)}</tr>
<tr>{''.join(labels)}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>Terminal collection moved to the adjacent strip for {migrated}/{validation['n']} points. The slow branch returned a single strip on
each face for {single_pair}/{validation['n']}. The simulations hold the other strip coordinate at its centre and use isolated pulses with no added noise.
Carrier diffusion and self-repulsion are disabled. The two sites in primary 2950 still require a separate reconstruction.
<a href="gegi-digital/edge-position.json">Open the edge geometry, coverage and error data (JSON)</a>.</p>'''


def compact_pairing_study(study, source_hash, *, holdout=False):
    cases = []
    for case in study['cases']:
        modes = {}
        for mode in DIGITAL_OBSERVABLES:
            comparison = case['comparison'][mode]
            if holdout:
                known = case['true_hypothesis_index']
                scores = [h['score'][mode] for h in case['hypotheses']]
            else:
                known = comparison['truth_index']
                scores = [h['fit'][mode]['score'] for h in case['hypotheses']]
            modes[mode] = dict(known_pairing_score=scores[known],
                               alternative_pairing_score=scores[1-known],
                               raw_preference=comparison['raw_preference'],
                               control_scale_outcome=comparison['control_scale_outcome'])
        cases.append(dict(mixture_index=case['mixture_index'], energy_candidates=len(case['hypotheses']),
                          pairing_decision=case['pairing_decision'], observables=modes))
    summary = {
        mode: {key: dict(Counter(c['observables'][mode][key] for c in cases))
               for key in ('raw_preference', 'control_scale_outcome')}
        for mode in DIGITAL_OBSERVABLES
    }
    recorded = {mode: {field: {label: n for label, n in values.items() if n}
                       for field, values in results.items()}
                for mode, results in study['summary'].items()}
    counts = study['counts']
    if (len({c['mixture_index'] for c in cases}) != len(cases) or summary != recorded
            or sum(c['energy_candidates'] == 2 for c in cases) != counts['energy_ambiguous_cases']
            or sum(c['pairing_decision'] == 'unresolved' for c in cases) != counts['unresolved_cases']):
        raise ValueError('Pairing study case counts do not match its summary.')
    return dict(source_report_sha256=source_hash, cases=cases, summary=summary,
                energy_ambiguous_cases=counts['energy_ambiguous_cases'], unresolved_cases=counts['unresolved_cases'])


def attach_pairing_study(site, study_path, holdout_path=None):
    """Append the compact public counts and the case scores behind them."""
    event_path = site/'results/gegi-digital/event.json'
    event = json.loads(event_path.read_bytes())
    study_bytes = study_path.read_bytes()
    study = json.loads(study_bytes)
    if study['kind'] != 'gegi_saved_fixed8_digital_pairing_study_v1' or len(study['cases']) != 8:
        raise ValueError('Expected the saved fixed-eight GeGI pairing study.')
    if study['digital_profile_sha256'] != event['profile_sha256']:
        raise ValueError('Pairing study must use the published example’s digital profile.')
    study_hash = sha256(study_bytes).hexdigest()
    benchmark = compact_pairing_study(study, study_hash)
    counts = study['counts']
    benchmark.update(
        controls=counts['independent_control_mixtures'], training_injections=counts['regular_training_injections'],
        maximum_control_score=study['controls']['maximum_control_score'],
    )
    if holdout_path is not None:
        holdout_bytes = holdout_path.read_bytes()
        holdout = json.loads(holdout_bytes)
        if (holdout['kind'] != 'gegi_saved_digital_pairing_holdout_v1' or holdout['status'] != 'completed'
                or holdout['frozen_study_sha256'] != study_hash
                or holdout['fixed_control_limits'] != benchmark['maximum_control_score']):
            raise ValueError('Pairing holdout must be complete and use the original study’s control scale.')
        benchmark['holdout'] = compact_pairing_study(holdout, sha256(holdout_bytes).hexdigest(), holdout=True)
    event['pairing_benchmark'] = benchmark
    event_path.write_text(json.dumps(event, allow_nan=False, separators=(',', ':'))+'\n',
                          encoding='utf-8', newline='\n')


def pairing_section(benchmark):
    rows = []
    for mode, label in DIGITAL_OBSERVABLES.items():
        counts = benchmark['summary'][mode]
        ranking = counts['raw_preference']
        scale = counts['control_scale_outcome']
        cells = ([ranking.get(key, 0) for key in ('true', 'wrong', 'tie')]
                 + [scale.get(key, 0) for key in ('true_only', 'wrong_only', 'both', 'neither')])
        rows.append(f'<tr><th scope="row">{label}</th>' + ''.join(f'<td>{n}</td>' for n in cells) + '</tr>')
    n = len(benchmark['cases'])
    combined = benchmark['summary']['fast_and_centered_cfd']
    known = combined['raw_preference'].get('true', 0)
    only_known = combined['control_scale_outcome'].get('true_only', 0)
    both = combined['control_scale_outcome'].get('both', 0)
    holdout_text = ''
    if 'holdout' in benchmark:
        holdout = benchmark['holdout']
        sample_size = len(holdout['cases'])
        fast = holdout['summary']['fast']['control_scale_outcome']
        joint = holdout['summary']['fast_and_centered_cfd']['control_scale_outcome']
        holdout_text = f'''
<p>In {sample_size} separate mixtures at held-out positions, the same control scale left only the known pairing in
{fast.get('true_only', 0)}/{sample_size} using fast area alone and in {joint.get('true_only', 0)}/{sample_size} using both observables,
with both pairings within scale in {fast.get('both', 0)}/{sample_size} and {joint.get('both', 0)}/{sample_size}, respectively.</p>'''
    return f'''<h3>Pairing X and Y strips in two-site events</h3>
<p>Slow-branch energies left two possible X–Y pairings in {benchmark["energy_ambiguous_cases"]}/{n} fixed simulated mixtures.
The sites had equal energies and shared neighboring strips. Combining signed fast area with centered constant-fraction discriminator (CFD) times
ranked the known simulated pairing first in {known}/{n}. Within the control scale, {only_known}/{n} had only the known pairing
and {both}/{n} still had both. The reconstruction retains both alternatives in {benchmark["unresolved_cases"]}/{n} cases.</p>
<div style="overflow-x:auto"><table><colgroup span="1"></colgroup><colgroup span="3"></colgroup><colgroup span="4"></colgroup><thead>
<tr><th rowspan="2" scope="col">Digital observable</th><th colspan="3" scope="colgroup">Lower residual</th><th colspan="4" scope="colgroup">Within control scale</th></tr>
<tr><th scope="col">Known</th><th scope="col">Alternate</th><th scope="col">Tie</th><th scope="col">Known only</th><th scope="col">Alternate only</th><th scope="col">Both</th><th scope="col">Neither</th></tr>
</thead><tbody>{''.join(rows)}</tbody></table></div>
<p>The control scale is the largest residual at known positions in {benchmark["controls"]} separately composed simulated control
mixtures. The same model supplied {benchmark["training_injections"]} training injections. These fixed mixtures use nominal readout.
Experimental pairing accuracy remains unmeasured. <a href="gegi-digital/event.json">Case counts and fit scores</a>.</p>{holdout_text}'''


def energy_order_section(check, counts, *, edge_position=False):
    candidates = check['candidates']
    lines = {c['source_line']['energy_keV'] for c in candidates if c['source_line']}
    source = f' of {lines.pop():g} keV each' if len(lines) == 1 and all(c['source_line'] for c in candidates) else ''
    rows = []
    notes = []
    for c in candidates:
        cells = [f"{escape(s['x_strip'])}/{escape(s['y_strip'])} · {s['energy_keV']:.2f}" for s in c['sites']]
        orders = {tuple(o['site_index_order']): o for o in c['orders']}
        for order in ((0, 1), (1, 0)):
            o = orders[order]
            cells.append(f"{o['half_angle_deg']:.2f}°" if o['kinematically_allowed'] else 'Excluded')
        ref = c['transport_reference']
        sequence = ref['site_index_order']
        cells.append(' → '.join('AB'[i] for i in sequence) if sequence is not None
                     else f"{ref['significant_interactions']} significant interactions")
        rows.append(f"<tr><th scope=\"row\">{c['event_id']}</th><td>{c['deposited_keV']:.2f}</td>"
                    + ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr>')
        if (c['source_line'] and sequence is not None
                and math.isclose(c['deposited_keV'], c['source_line']['energy_keV'], abs_tol=1e-6)
                and not orders[tuple(sequence)]['kinematically_allowed']):
            notes.append(f"Primary {c['event_id']} deposited the full source energy in germanium. "
                         "The energy model excludes the order recorded by transport.")
            if 'fit_error_to_simulated_centroids_mm' in c:
                a, b = c['fit_error_to_simulated_centroids_mm']
                if edge_position and c['event_id'] == 2950:
                    notes.append(f'The earlier within-strip fit placed its two sites {a:.2f} and {b:.2f} mm from '
                                 'their simulated centroids. <a href="#gegi-edge-position">See the edge-position check</a>.')
                else:
                    notes.append(f"Its fitted sites lie {a:.2f} and {b:.2f} mm from their simulated charge-deposition centroids.")
    if 'position_study' in check:
        s = check['position_study']
        notes.append(f"Across {s['mixtures']} independent two-site mixtures, fitting positions within the strips "
                     f"changed lateral RMS error from {s['centre_xy_rms_mm']:.2f} to {s['lateral_xy_rms_mm']:.2f} mm.")
    extension = ''
    if 'two_source_check' in check:
        left, right = check['two_source_check']['sources']
        both = left['both_orders_allowed'] + right['both_orders_allowed']
        matched = left['full_deposit_cell_matches'] + right['full_deposit_cell_matches']
        extension = f'''<p>Two further runs used {left['initial_primaries']:,} photons at x = {left['source_position_mm'][0]:g} mm
and {right['initial_primaries']:,} at x = {right['source_position_mm'][0]:+g} mm. The runs yielded
{left['unique_pairings']} and {right['unique_pairings']} unique energy pairings, respectively. Of those,
{left['full_deposit_cell_matches']} and {right['full_deposit_cell_matches']} deposited the full photon energy in germanium and
matched the cells of both significant transport interactions. The energy model allowed both orders in {both}/{matched} matched events.</p>'''
    return f'''<h3>Which interaction could have happened first?</h3>
<p>The run started with {counts['initial_primaries']:,} simulated photons{source}. Of the {counts['nonzero_primaries']}
that deposited energy in germanium, {len(candidates)} had one energy-compatible pairing between faces.
The two angle columns assume scattering from a stationary free electron followed by full absorption.
The last column checks the inferred order against the simulated photon history. It uses parent interactions depositing at least 5 keV.</p>
<div style="overflow-x:auto"><table><thead><tr><th>Primary</th><th>Deposited in Ge (keV)</th><th>Site A (keV)</th>
<th>Site B (keV)</th><th>A → B</th><th>B → A</th><th>Transport reference</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>{' '.join(notes)}</p>{extension}'''


def render(site):
    data = site/'results/gegi-digital/event.json'
    if not data.exists():
        return
    ex = json.loads(data.read_bytes())
    rows = []
    for c in ex['channels']:
        slow = 'Below threshold' if 'slow_below_threshold' in c['flags'] else (
            'Unavailable' if c['slow_energy_keV'] is None else f'{c["slow_energy_keV"]:.2f}')
        rows.append(f'<tr><th scope="row">{escape(c["name"])}</th>'
                    f'<td>{max(abs(v) for v in c["signed_induced_keV"]):.2f}</td>'
                    f'<td>{c["signed_induced_keV"][-1]:.2f}</td><td>{c["fast_area_V_ns"]:.3f}</td><td>{slow}</td></tr>')
    pulse = site/DOUBLE_PULSE_FILE
    exposure = site/SOURCE_EXPOSURE_FILE
    event_energy = site/EVENT_ENERGY_FILE
    edge_position = site/EDGE_POSITION_FILE
    hit_map = site/DUAL_SOURCE_HIT_MAP_FILE
    card = '<section id="gegi" class="panel" data-dataset="gegi">\n'
    if exposure.is_file():
        data = json.loads(exposure.read_bytes())
        study = json.loads(event_energy.read_bytes()) if event_energy.is_file() else None
        if study and study['binding']['exposure_sha256'] != data['provenance']['report_sha256']:
            raise ValueError('GeGI energy comparison belongs to a different source exposure.')
        projection = json.loads(hit_map.read_bytes()) if hit_map.is_file() else None
        if projection and (not study or any(projection['binding'].get(key) != digest
                                            for key, digest in _dual_source_map_binding(data, study).items())):
            raise ValueError('The GeGI detector hit map belongs to a different publication.')
        card += exposure_section(data, study, projection)
    has_pulse = pulse.is_file()
    if has_pulse:
        card += double_pulse_section(json.loads(pulse.read_bytes()))
    heading = 'h3' if has_pulse else 'h2'
    strip_table = f'''<div style="overflow-x:auto"><table><thead><tr><th>Strip</th><th>Largest |Q| (keV equivalent)</th><th>Final Q (keV equivalent)</th><th>Fast area (V·ns)</th><th>Slow energy (keV)</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>'''
    if has_pulse:
        strip_table = f'<details><summary>Strip measurements for this event</summary>{strip_table}</details>'
    card += f'''<{heading}>How neighboring GeGI strips sense a drifting charge</{heading}>
<p>During drift, both neighboring strips respond to the moving carriers. Their induced charge returns to zero, while their fast areas differ. The collecting strip supplies the slow energy signal.</p>
<figure style="margin:0"><img style="width:100%;height:auto" width="1450" height="870" src="gegi-digital/signals.png" alt="Induced charge and digital fast and slow signals on three adjacent strips">
<figcaption>Simulated primary {ex["event_id"]} · {ex["counts"]["initial_primaries"]:,} initial primaries, {ex["counts"]["nonzero_primaries"]} with a germanium deposit. Nominal digital readout.</figcaption></figure>
{strip_table}
<p><a href="gegi-digital/event.json">Event samples and readout settings</a> · <a href="gegi-campaign/index.html">View the saved Compton study</a></p>'''
    benchmark = ex.get('position_benchmark')
    if benchmark:
        xy = benchmark['all_axes']
        card += f'''<h3>Position check on independent simulated points</h3>
<p>The time difference between the two collecting strips selects a depth-dependent calibration of the neighboring signals.
Training used {benchmark["trained"]} injected points on four strip pairs. On {benchmark["n"]} separate {benchmark["energy_keV"]:g} keV points,
{benchmark["both"]} returned both lateral coordinates. Using the strip center for each unavailable axis,
the radial XY RMS error changed from <strong>{xy["center_rmse_mm"]:.2f} to {xy["substrip_rmse_mm"]:.2f} mm</strong>.
The depth RMS error was {benchmark["z"]["rmse_mm"]:.2f} mm on {benchmark["z"]["compared"]} points.
These errors compare simulated coordinates within the sampled region.</p>'''
    if edge_position.is_file():
        card += edge_position_section(json.loads(edge_position.read_bytes()))
    if 'energy_order_check' in ex:
        orders = energy_order_section(ex['energy_order_check'], ex['counts'], edge_position=edge_position.is_file())
        card += f'<details><summary>Interaction ordering benchmark</summary>{orders}</details>' if has_pulse else orders
    if 'pairing_benchmark' in ex:
        card += '<details><summary>Two-site strip-pairing benchmark</summary>' + pairing_section(ex['pairing_benchmark']) + '</details>'
    card += '</section>'
    page = site/'results/index.html'
    old = page.read_text(encoding='utf-8')
    updated, n = re.subn(r'<section id="gegi"[^>]*>.*?</section>', lambda m: card, old, flags=re.S)
    if n != 1:
        raise ValueError('Expected one GeGI panel in the generated results hub.')
    page.write_text(updated, encoding='utf-8', newline='\n')
