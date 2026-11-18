"""Render the saved digital strip example in the Results hub."""
from collections import Counter
from hashlib import sha256
from html import escape
import json
import math
import re


DIGITAL_OBSERVABLES = {
    'pair_cfd': 'X–Y timing within each pair',
    'centered_cfd': 'Centered timing of four collecting strips',
    'fast': 'Signed fast area of nine strips',
    'fast_and_centered_cfd': 'Signed fast area + centered timing',
}


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
    card = f'''<section id="gegi" class="panel" data-dataset="gegi">
<h2>How neighboring GeGI strips sense a drifting charge</h2>
<p>During drift, both neighboring strips respond to the moving carriers. Their induced charge returns to zero, while their fast areas differ. The collecting strip supplies the slow energy signal.</p>
<figure style="margin:0"><img style="width:100%;height:auto" width="1450" height="870" src="gegi-digital/signals.png" alt="Induced charge and digital fast and slow signals on three adjacent strips">
<figcaption>Simulated primary {ex["event_id"]} · {ex["counts"]["initial_primaries"]:,} initial primaries, {ex["counts"]["nonzero_primaries"]} with a germanium deposit. Nominal digital readout.</figcaption></figure>
<div style="overflow-x:auto"><table><thead><tr><th>Strip</th><th>Largest |Q| (keV equivalent)</th><th>Final Q (keV equivalent)</th><th>Fast area (V·ns)</th><th>Slow energy (keV)</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
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
        card += energy_order_section(ex['energy_order_check'], ex['counts'])
    if 'pairing_benchmark' in ex:
        card += '<details><summary>Two-site strip-pairing benchmark</summary>' + pairing_section(ex['pairing_benchmark']) + '</details>'
    card += '</section>'
    page = site/'results/index.html'
    old = page.read_text(encoding='utf-8')
    updated, n = re.subn(r'<section id="gegi"[^>]*>.*?</section>', lambda m: card, old, flags=re.S)
    if n != 1:
        raise ValueError('Expected one GeGI panel in the generated results hub.')
    page.write_text(updated, encoding='utf-8', newline='\n')
