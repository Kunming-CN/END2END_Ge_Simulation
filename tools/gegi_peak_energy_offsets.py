"""Measure energy-offset dependence of saved GeGI peak-cell contributions."""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

import numpy as np

from gegi_event_store import encoded


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local/gegi-reconstruction-v1'
BASELINE = ROOT / '.local/gegi-candidate-runs/steady-five-seconds/candidate-imaging.json.gz'
ATTRIBUTION = LOCAL / 'five-second-edge-attribution.json.gz'
CONTROLS = LOCAL / 'position-uncertainty-controls.json'
CURVES = ROOT / '.local/gegi-pixel-cfd-depth/study.json'
SHA256 = {
    'baseline': '78124e398de1dbe41f2f4ca5d17269c9b213ae7f207d4c13b4943b8fc90e0863',
    'attribution': '3af3ba2f5e142176efd575544cd0bd8feb4ad8f47701bcc9387e650bf2fc2c56',
    'controls': '6accb91c8e3076b0b535e5d3a1fea662c951450aab9645b97a1c9ad79fcccd24',
    'curves': 'fbf5f9eb76bee6c82f256de3515c350df4c350539c8f5062a7fd0c965794a399',
}
CASE = '120_mm_uniform-area'
MASS_TOLERANCE = 1e-12


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_bound(path, key):
    raw = path.read_bytes()
    if digest(raw) != SHA256[key]:
        raise ValueError(f'Expected the verified original input {path.name}')
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def close_mass(a, b):
    return math.isclose(a, b, rel_tol=0, abs_tol=MASS_TOLERANCE)


def trace_orders(saved, attributed):
    contributions = {(part['pair_index'], tuple(part['order'])): part['peak_cell'] for part in attributed['orders']}
    retained = []
    for pair in saved['pairings']:
        orders = []
        for order in pair['orders']:
            key = (pair['index'], tuple(order['order']))
            available = order['status'] in ('projected', 'no_plane_response')
            if available != (key in contributions):
                raise ValueError('Original orders and attributed peak contributions differ')
            orders.append(dict(order, peak_cell_contribution=contributions.pop(key) if available else None))
        retained.append({'pairing_index': pair['index'], 'cells': pair['cells'],
                         'site_energies_keV': pair['site_energies_keV'],
                         'nominal_pairing_mass': pair['nominal_mass'], 'orders': orders})
    if contributions or not close_mass(math.fsum(order['peak_cell_contribution'] or 0.
                                                  for pair in retained for order in pair['orders']),
                                       attributed['support']['peak_cell']):
        raise ValueError('Original attributed orders fail peak-cell mass closure')
    return retained


def cumulative(rows, total):
    groups = defaultdict(list)
    for row in rows:
        groups[abs(row['offset_keV'])].append(row['attributed_peak_cell_contribution'])
    absolute, count, mass = [], 0, 0.
    for offset, weights in sorted(groups.items()):
        count += len(weights)
        mass += math.fsum(weights)
        absolute.append({'absolute_energy_offset_keV': offset, 'candidate_count': count, 'original_peak_cell_mass': mass,
                         'fraction_of_retained_candidates': count/len(rows), 'fraction_of_original_peak': mass/total})
    if not close_mass(mass, total):
        raise ValueError('Cumulative descriptive mass does not reproduce the fixed original peak')
    return absolute


def summarize(label, window, baseline, by_id):
    case = window['cases'][CASE]
    center, half = window['center_keV'], window['half_width_keV']
    layer = baseline['layers'][label]
    grid = baseline['grid']
    masses = np.asarray(layer['mass'], dtype=float)
    y, x = np.unravel_index(np.argmax(masses), masses.shape)
    point = [grid['x_mm'][x], grid['y_mm'][y], grid['assumed_z_mm']]
    height = float(masses[y, x])
    if point != case['peak']['position_mm'] or not close_mass(height, case['peak']['mass']) or height <= 0.:
        raise ValueError(f'{label} attribution is not the saved original peak cell')
    rows = []
    for prior, contribution in zip(window['original_triggers'], case['trigger_contributions'], strict=True):
        ident = contribution['original_trigger_id']
        old = by_id[ident]
        energy = old['energy_keV']
        if (prior['original_trigger_id'] != ident or prior['energy_keV'] != energy
                or prior['trigger_time_ns'] != old['trigger_time_ns'] or abs(energy-center) > half
                or not close_mass(prior['saved_projected_mass'], old['projected_mass'])
                or not close_mass(old['projected_mass'] + old['unresolved_mass'], 1.)):
            raise ValueError(f'Original ID, measured energy, selection or weight differs at trigger {ident}')
        rows.append({'original_trigger_id': ident, 'trigger_time_ns': old['trigger_time_ns'],
                     'measured_energy_keV': energy, 'offset_keV': energy-center,
                     'original_projected_mass': old['projected_mass'], 'original_unresolved_mass': old['unresolved_mass'],
                     'attributed_peak_cell_contribution': contribution['support']['peak_cell'],
                     'original_pairings': trace_orders(old, contribution)})
    total = math.fsum(row['attributed_peak_cell_contribution'] for row in rows)
    projected = math.fsum(row['original_projected_mass'] for row in rows)
    unresolved = math.fsum(row['original_unresolved_mass'] for row in rows)
    ids = [row['original_trigger_id'] for row in rows]
    if (len(rows) != layer['triggers'] or ids != sorted(set(ids)) or not close_mass(total, height)
            or not close_mass(projected, layer['projected_mass']) or not close_mass(unresolved, layer['unresolved_mass'])):
        raise ValueError('All original candidates, including zero peak contributors, must reconcile')
    for row in rows:
        row['original_peak_cell_share'] = row['attributed_peak_cell_contribution']/total
    cdf = cumulative(rows, total)
    dominant = sorted(rows, key=lambda row: (-row['original_peak_cell_share'], row['original_trigger_id']))[:5]
    sides = {}
    for side, predicate in [('below', lambda x: x < 0.), ('at_center', lambda x: x == 0.), ('above', lambda x: x > 0.)]:
        selected = [row for row in rows if predicate(row['offset_keV'])]
        sides[side] = {'candidate_count': len(selected),
                       'original_peak_cell_share': math.fsum(row['original_peak_cell_share'] for row in selected)}
    return {'window_center_keV': center, 'window_half_width_keV': half, 'original_peak_xyz_mm': point,
            'original_peak_on_edge': case['peak']['on_image_edge'], 'original_peak_cell_mass': height,
            'attributed_peak_cell_mass': total, 'original_projected_mass': projected, 'original_unresolved_mass': unresolved,
            'original_trigger_count': len(rows),
            'summary': {'median_absolute_offset_of_retained_candidates_keV': statistics.median(abs(r['offset_keV']) for r in rows),
                        'absolute_offset_at_half_original_peak_mass_keV': next(
                            p['absolute_energy_offset_keV'] for p in cdf if p['fraction_of_original_peak'] >= .5),
                        'peak_weighted_mean_signed_offset_keV': math.fsum(
                            r['offset_keV']*r['original_peak_cell_share'] for r in rows),
                        'side_of_window_center': sides,
                        'top_five_original_peak_contributors': [
                            {k: r[k] for k in ('original_trigger_id', 'measured_energy_keV', 'offset_keV', 'original_peak_cell_share')}
                            for r in dominant]},
            'triggers': rows, 'cumulative_by_absolute_offset': cdf}


def injection_control(baseline, controls, curves):
    identity = baseline['calibration_bundle']['identity']
    prior = curves['provenance']
    relative = CURVES.relative_to(ROOT).as_posix()
    if (any(prior[k] != value for k, value in identity.items())
            or controls['input_sha256'][relative] != SHA256['curves']):
        raise ValueError('Independent injection residuals differ in simulated detector/electronics identity')
    rows, summary = [], {}
    for row in controls['trials']:
        if row['cohort'] == 'negative_mixture':
            continue
        correct, = [pair for pair in row['pairings'] if pair['match_label'] == 'true_two_site_assignment']
        model = correct['hypotheses']['waveform_center']
        measured = model['measured_site_energies_keV']
        reference = [site['energy_keV'] for site in row['reference_sites']]
        total, truth = math.fsum(measured), math.fsum(reference)
        rows.append({'cohort': row['cohort'], 'physical_holdout_group': row['holdout_group'], 'trial': row['trial'],
                     'adc_sha256': row['adc_sha256'], 'measured_site_energies_keV': measured,
                     'injected_site_energies_keV': reference,
                     'measured_trigger_energy_keV': total, 'injected_total_keV': truth, 'energy_residual_keV': total-truth})
    for cohort in sorted({r['cohort'] for r in rows}):
        selected = [row for row in rows if row['cohort'] == cohort]
        errors = [row['energy_residual_keV'] for row in selected]
        summary[cohort] = {'conditions': len(errors),
                           'rms_energy_residual_keV': math.sqrt(math.fsum(x*x for x in errors)/len(errors)),
                           'median_energy_residual_keV': statistics.median(errors),
                           'minimum_energy_residual_keV': min(errors), 'maximum_energy_residual_keV': max(errors)}
    return {'study': 'Clean simultaneous two-point injection mixtures at the same nominal ADC calibration. Conditions repeat or share geometry.',
            'limits': 'These point-input residuals lack full-photon transport and the continuous acquisition background, so they supply '
                      'a readout-control scale. The original energy-window offsets can include escaped or mixed photon energy. '
                      'No detector energy resolution, reclassification, or new gate is inferred.',
            'shared_calibration_identity': identity, 'summary_by_control_cohort': summary, 'conditions': rows}


def figure(result, output):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import PercentFormatter

    canvas = Figure(figsize=(12.2, 6.8), layout='constrained')
    FigureCanvasAgg(canvas)
    axes = canvas.subplots(2, 3)
    for col, window in enumerate(result['windows'].values()):
        top, bottom = axes[:, col]
        rows, cdf = window['triggers'], window['cumulative_by_absolute_offset']
        half = window['window_half_width_keV']
        top.scatter([r['offset_keV'] for r in rows], [100*r['original_peak_cell_share'] for r in rows],
                    s=13, c='#1d6292', alpha=.55, edgecolors='none')
        lead = window['summary']['top_five_original_peak_contributors'][0]
        top.scatter([lead['offset_keV']], [100*lead['original_peak_cell_share']], c='#bb4a24',
                    s=45, marker='D', label='Largest contributor')
        height = 100*lead['original_peak_cell_share']
        top.annotate(f'#{lead["original_trigger_id"]}', (lead['offset_keV'], height), xytext=(
            -6 if lead['offset_keV'] > 0 else 6, 8), textcoords='offset points',
            ha='right' if lead['offset_keV'] > 0 else 'left', fontsize=9)
        top.set_ylim(bottom=-max(.01, height*.02), top=height*1.24)
        top.axvline(0., color='#73869a', alpha=.45, lw=1)
        top.set_xlim(-half, half)
        x, y, _ = window['original_peak_xyz_mm']
        top.set_title(f"{window['window_center_keV']:g} keV · peak ({x:g}, {y:g}) mm\n"
                      f"{len(rows):,} retained triggers", fontsize=11)
        top.set_xlabel('Measured energy minus window center (keV)')
        absolute = [0., *[p['absolute_energy_offset_keV'] for p in cdf], half]
        for field, label, color in [('fraction_of_original_peak', 'Original peak weight', '#1d6292'),
                                    ('fraction_of_retained_candidates', 'Retained trigger count', '#b85a32')]:
            bottom.step(absolute, [0., *[p[field] for p in cdf], 1.], where='post', color=color, lw=1.7, label=label)
        bottom.set_xlim(0., half)
        bottom.set_ylim(0., 1.025)
        bottom.yaxis.set_major_formatter(PercentFormatter(xmax=1.))
        bottom.set_xlabel('Absolute measured energy offset (keV)')
        if col == 0:
            top.set_ylabel('Share of fixed peak cell (%)')
            bottom.set_ylabel('Cumulative fraction')
            bottom.legend(loc='lower right', fontsize=8)
        for ax in (top, bottom):
            ax.grid(True, color='#dce4ea', linewidth=.7)
            ax.set_axisbelow(True)
    canvas.suptitle('GeGI five-second acquisition | energy offsets on the unchanged area-weighted maps', fontsize=15)
    canvas.savefig(output, dpi=155, facecolor='white')


def run():
    baseline = read_bound(BASELINE, 'baseline')
    attribution = read_bound(ATTRIBUTION, 'attribution')
    if (attribution['input_sha256']['saved_plane'] != SHA256['baseline']
            or any(attribution['input_sha256'][key] != value for key, value in baseline['input_sha256'].items())
            or attribution['saved_selection'] != baseline['selection']
            or baseline['model']['plane_prior'] != 'uniform-area'
            or (baseline['grid']['extent_mm'], baseline['grid']['step_mm'], baseline['grid']['assumed_z_mm']) != (120., 4., 40.)):
        raise ValueError('The attribution and original fixed map have different inputs or selection')
    by_id = {row['original_trigger_id']: row for row in baseline['triggers']}
    if len(by_id) != baseline['selection']['two_strip_triggers']:
        raise ValueError('Original triggers are missing or repeated')
    controls, curves = read_bound(CONTROLS, 'controls'), read_bound(CURVES, 'curves')
    return {'kind': 'gegi_original_peak_energy_offsets_v1', 'input_sha256': SHA256,
            'source_sha256': digest(Path(__file__).read_bytes()),
            'case': CASE, 'grid': baseline['grid'], 'full_map_selection': baseline['selection'],
            'scope': 'Every retained trigger in each original line window and every retained measured order. Offsets are measured energy '
                     'minus the window center. Cumulative curves reference the original fixed peak cell and include zero contributors. '
                     'Energy offsets do not choose isotope, photon identity, orders, or a new cut.',
            'injection_energy_control': injection_control(baseline, controls, curves),
            'windows': {label: summarize(label, window, baseline, by_id) for label, window in attribution['windows'].items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, default=LOCAL/'peak-energy-offsets.json.gz')
    parser.add_argument('--figure', type=Path, default=LOCAL/'peak-energy-offsets.png')
    args = parser.parse_args()
    if any(path.exists() or not path.resolve().is_relative_to(LOCAL) for path in (args.receipt, args.figure)):
        parser.error('Choose new derivative paths in the reconstruction evidence directory')
    report = run()
    figure(report, args.figure)
    report['figure_sha256'] = digest(args.figure.read_bytes())
    with args.receipt.open('xb') as raw, gzip.GzipFile(fileobj=raw, filename='', mode='wb', mtime=0) as dst:
        dst.write(encoded(report) + b'\n')
    print(json.dumps({label: window['summary'] for label, window in report['windows'].items()}, indent=2))


if __name__ == '__main__':
    main()
