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


def energy_order_section(check, counts):
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
    card = '<section id="gegi" class="panel" data-dataset="gegi">\n'
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
    if 'energy_order_check' in ex:
        orders = energy_order_section(ex['energy_order_check'], ex['counts'])
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
