"""Attribute saved conditional image peaks without refitting signals or using truth.

Uses the original candidate priors, conditional angular response and EM routine.
Peak-pixel responsibilities and fixed 8 mm neighbourhoods describe this fitted
mixture only; neither is a calibrated event assignment or a physical source count.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import time

if __name__ == '__main__':
    for _name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[_name] = '1'
import numpy as np
import gegi_joint_imaging as J


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def peak_tracking(peaks, references, radius_mm=8.):
    """Distances to displayed modes; matching radius is descriptive, not a gate."""
    return [{'reference_position_mm': p,
             'nearest_displayed_peak_distance_mm': min(
                 (math.dist(p, q['position_mm']) for q in peaks), default=None),
             'displayed_peak_within_radius': any(
                 math.dist(p, q['position_mm']) <= radius_mm for q in peaks)}
            for p in references]


def fit_summary(fit, points, references):
    peaks = J.blind_peaks(fit['source_mass'], points)
    history = fit['log_likelihood']
    return {'iterations': fit['iterations'], 'background_fraction': fit['background_fraction'],
            'conditional_log_likelihood': history[-1],
            'last_objective_increment': history[-1]-history[-2] if len(history) > 1 else None,
            'blind_peaks': peaks, 'peak_tracking': peak_tracking(peaks, references)}


def attribute_groups(records, events, response, points, fit, references, settings,
                     radius_mm=8.):
    """Keep candidate, unresolved and background responsibilities distinct."""
    mass = fit['source_mass']
    predicted = response @ mass + fit['background_fraction']*J.BACKGROUND_PER_RAD
    source_responsibility = response*mass[None, :]/predicted[:, None]
    background = fit['background_fraction']*J.BACKGROUND_PER_RAD/predicted
    np.testing.assert_allclose(source_responsibility.sum(axis=1)+background, 1., atol=2e-13)
    peak_indices, masks = [], []
    for peak in references:
        matches = np.flatnonzero(np.all(points == peak, axis=1))
        if len(matches) != 1:
            raise ValueError('Saved peak is not a unique baseline grid point')
        peak_indices.append(int(matches[0]))
        masks.append(np.linalg.norm(points-np.array(peak), axis=1) <= radius_mm)
    if len(masks) > 1 and np.max(np.sum(masks, axis=0)) > 1:
        raise ValueError('Peak neighbourhoods overlap; reduce descriptive radius')
    sums = response[:, peak_indices].sum(axis=0)
    rows = []
    max_candidate_closure = 0.
    for i, (raw, event) in enumerate(zip(records, events)):
        candidate_rows = []
        candidate_terms = []
        for index, (candidate, original) in enumerate(zip(event.candidates, raw['candidates'])):
            term = candidate.prior*J.candidate_response(candidate, points, settings)
            candidate_terms.append(term[peak_indices])
            alpha, _ = J.geometric_angle_and_variance(candidate, np.array(references))
            candidate_rows.append({
                'candidate_index': index, 'hypothesis_index': original.get('hypothesis_index'),
                'order': original.get('order'), 'prior_weight': candidate.prior,
                'site_separation_mm': candidate.separation,
                'peak_weighted_angular_density_per_rad': term[peak_indices].tolist(),
                'peak_conditional_candidate_probability': (term[peak_indices]/response[i, peak_indices]).tolist(),
                'peak_angular_residual_deg': np.degrees(alpha-candidate.theta).tolist(),
                'whole_map_candidate_responsibility': float(term @ mass/predicted[i])})
        terms = np.array(candidate_terms)
        unresolved = event.unresolved_mass*J.BACKGROUND_PER_RAD
        closure = float(np.max(abs(terms.sum(axis=0)+unresolved-response[i, peak_indices])))
        max_candidate_closure = max(max_candidate_closure, closure)
        if closure > 1e-12:
            raise AssertionError('Candidate/unresolved response does not close')
        peak_rows = []
        for k, (index, mask) in enumerate(zip(peak_indices, masks)):
            probabilities = terms[:, k]/response[i, index]
            unresolved_probability = unresolved/response[i, index]
            joint = np.r_[probabilities, unresolved_probability]
            entropy = -sum(float(p)*math.log(float(p)) for p in joint if p > 0)
            peak_rows.append({
                'position_mm': references[k], 'angular_density_per_rad': float(response[i, index]),
                'backprojection_share': float(response[i, index]/sums[k]),
                'peak_pixel_responsibility': float(source_responsibility[i, index]),
                'neighbourhood_responsibility': float(source_responsibility[i, mask].sum()),
                'unresolved_conditional_probability': float(unresolved_probability),
                'maximum_candidate_conditional_probability': float(probabilities.max()),
                'candidate_plus_unresolved_entropy_nats': entropy,
                'largest_candidate_index': int(np.argmax(probabilities))})
        hypotheses = [c.get('hypothesis_index') for c in raw['candidates']]
        rows.append({'campaign_initial_id': event.identity[0], 'pulse_group_id': event.identity[1],
                     'energy_keV': event.energy_keV, 'candidate_count': len(event.candidates),
                     'supported_energy_pairing_hypothesis_count': len(set(hypotheses)),
                     'candidate_counts_by_hypothesis': dict(Counter(map(str, hypotheses))),
                     'unresolved_prior_mass': event.unresolved_mass,
                     'fitted_background_responsibility': float(background[i]),
                     'fitted_unresolved_source_responsibility': float(unresolved*mass.sum()/predicted[i]),
                     'peak_2_vs_peak_1_log_response_ratio': math.log(response[i, peak_indices[1]]/response[i, peak_indices[0]]) if len(peak_indices) == 2 else None,
                     'peaks': peak_rows, 'candidates': candidate_rows})
    aggregates = []
    for k, (index, mask) in enumerate(zip(peak_indices, masks)):
        pixel = source_responsibility[:, index]
        local = source_responsibility[:, mask].sum(axis=1)
        rank = np.argsort(-local, kind='stable')
        aggregates.append({
            'position_mm': references[k], 'pixel_mass': float(mass[index]),
            'neighbourhood_mass': float(mass[mask].sum()),
            'neighbourhood_grid_points': int(mask.sum()),
            'summed_peak_pixel_responsibility': float(pixel.sum()),
            'summed_neighbourhood_responsibility': float(local.sum()),
            'neighbourhood_effective_contributing_group_count': float(local.sum()**2/(local @ local)),
            'top_five_neighbourhood_contributors': [
                {'campaign_initial_id': events[j].identity[0], 'pulse_group_id': events[j].identity[1],
                 'responsibility': float(local[j]), 'share_of_neighbourhood_responsibility': float(local[j]/local.sum())}
                for j in rank[:5]]})
    return rows, aggregates, {'maximum_candidate_response_closure_error_per_rad': max_candidate_closure,
                            'maximum_row_responsibility_closure_error': float(np.max(abs(source_responsibility.sum(axis=1)+background-1)))}


def diagnose(records, settings, grid, iterations, baseline_layer):
    events = J.prepare_events(records, settings)
    if len(events) < 2:
        raise ValueError('At least two groups required for omission diagnostics')
    _, points = J.plane_grid(grid['extent_mm'], grid['step_mm'], grid['assumed_z_mm'])
    response = J.response_matrix(events, points, settings)
    fit = J.fit_conditional_mixture(response, iterations=iterations)
    saved = np.asarray(baseline_layer['source_mass']).ravel()
    if saved.shape != fit['source_mass'].shape or not np.allclose(saved, fit['source_mass'], rtol=1e-12, atol=1e-14):
        raise ValueError('Baseline replay differs from the saved energy layer')
    if not math.isclose(fit['background_fraction'], baseline_layer['background_fraction'], rel_tol=1e-12, abs_tol=1e-14):
        raise ValueError('Baseline background differs from saved layer')
    peaks = J.blind_peaks(fit['source_mass'], points)
    if [p['position_mm'] for p in peaks] != [p['position_mm'] for p in baseline_layer['blind_peaks']]:
        raise ValueError('Baseline peak identities differ from saved layer')
    references = [p['position_mm'] for p in peaks]
    rows, contributions, closure = attribute_groups(records, events, response, points, fit, references, settings)
    omissions = []
    for i, event in enumerate(events):
        reduced = J.fit_conditional_mixture(np.delete(response, i, axis=0), iterations=iterations)
        omissions.append({'omitted_identity': list(event.identity), 'remaining_group_count': len(events)-1,
                          **fit_summary(reduced, points, references)})
    sensitivity = []
    for step in (2., 4., 8.):
        if step == grid['step_mm']:
            probe_points, probe_response = points, response
        else:
            _, probe_points = J.plane_grid(grid['extent_mm'], step, grid['assumed_z_mm'])
            probe_response = J.response_matrix(events, probe_points, settings)
        for count in (20, 40, 80, 160):
            probe = fit if step == grid['step_mm'] and count == iterations else J.fit_conditional_mixture(probe_response, iterations=count)
            sensitivity.append({'step_mm': step, 'requested_iterations': count,
                                'response_matrix_bytes': probe_response.nbytes,
                                **fit_summary(probe, probe_points, references)})
    stability = []
    for k, position in enumerate(references):
        distances = [r['peak_tracking'][k]['nearest_displayed_peak_distance_mm'] for r in omissions]
        stability.append({'position_mm': position,
                          'omissions_with_displayed_mode_within_8_mm': sum(r['peak_tracking'][k]['displayed_peak_within_radius'] for r in omissions),
                          'nearest_displayed_mode_distance_mm_min_max': [min(distances), max(distances)]})
    return {'group_count': len(events), 'candidate_count': sum(len(e.candidates) for e in events),
            'selected_original_ids': [list(e.identity) for e in events],
            'groups_with_multiple_candidate_sequences': sum(len(e.candidates) > 1 for e in events),
            'groups_with_multiple_supported_energy_pairings': sum(r['supported_energy_pairing_hypothesis_count'] > 1 for r in rows),
            'groups_with_nonzero_unresolved_mass': sum(e.unresolved_mass > 1e-12 for e in events),
            'unresolved_prior_mass_sum': math.fsum(e.unresolved_mass for e in events),
            'baseline': fit_summary(fit, points, references), 'peak_contributions': contributions,
            'baseline_replay_max_absolute_mass_difference': float(np.max(abs(saved-fit['source_mass']))),
            'closure_checks': closure, 'leave_one_group_out_summary': stability,
            'leave_one_group_out': omissions, 'grid_iteration_sensitivity': sensitivity}, rows


def run(input_dir, baseline_path, output_dir, center_keV=1332.492):
    started = time.perf_counter()
    input_dir, baseline_path, output_dir = map(Path, (input_dir, baseline_path, output_dir))
    if output_dir.exists():
        raise FileExistsError('Use a new derivative directory; preserve existing results')
    bindings = {'diagnostic_source_sha256': digest(__file__), 'imaging_source_sha256': digest(J.__file__),
                'baseline_report_sha256': digest(baseline_path)}
    baseline = json.loads(baseline_path.read_bytes())
    if bindings['imaging_source_sha256'] != baseline['provenance']['source_sha256']:
        raise ValueError('Imaging implementation differs from baseline provenance')
    settings = J.ResponseSettings(**baseline['uncertainty']['settings'])
    records, accounting = J.read_reconstructed(input_dir)
    if accounting['input_sha256'] != baseline['saved_signal_accounting']['input_sha256']:
        raise ValueError('Saved candidates differ from baseline input bindings')
    label = f'{center_keV:g}_keV'
    membership = J.spectral_membership(J.prepare_events(records, settings), (center_keV,))[label]
    selected = [r for r, keep in zip(records, membership) if keep]
    if len(selected) != baseline['spectral_layers'][label]['group_count']:
        raise ValueError('Saved layer census differs from candidate selection')
    report, rows = diagnose(selected, settings, baseline['grid'], baseline['em_iterations'], baseline['spectral_layers'][label])
    report.update(kind='gegi_saved_peak_diagnostic_v1', energy_center_keV=center_keV,
                  energy_halfwidth_keV=max(5., .02*center_keV),
                  grid={k: v for k, v in baseline['grid'].items() if k not in ('x_mm', 'y_mm')},
                  response_settings=baseline['uncertainty']['settings'],
                  original_initial_denominators=accounting['original_initial_denominators'],
                  saved_signal_census=accounting['counts'],
                  interpretation={
                      'peak_count_is_inferred_source_count': False,
                      'peak_tracking_and_neighbourhood_radius_mm': 8.,
                      'neighbourhood_definition': 'Disjoint closed 8 mm disks centred on the original displayed peaks; descriptive attribution only.',
                      'peak_pixel_responsibility': 'f_j L_ij / (b/pi + sum_k f_k L_ik); sum over neighbourhood pixels for neighbourhood responsibility.',
                      'candidate_conditional_probability': 'q_ih L_ih(x) / L_i(x); unresolved mass remains separate. Uncalibrated conditional model, not truth correctness.',
                      'backprojection_share': 'L_i(x) / sum_g L_g(x), before mixture fitting.',
                      'effective_contributing_group_count': '(sum responsibility)^2 / sum responsibility^2; descriptive concentration, not independent sample size.',
                      'leave_one_out': 'Refit the original 40-iteration model from uniform initialization after removing exactly one group; no replacement or candidate selection.',
                      'sensitivity': 'Fixed 2/4/8 mm cell-centred grids and 20/40/80/160 iteration budgets; original 120 mm half extent and z=40 mm. No optimum selected.',
                      'limits': ['Small selected conditional sample; no source-count, detector-resolution, calibrated uncertainty or range inference.',
                                 'Displayed modes retain the existing 20 mm separation/80 percent valley rule; losing a displayed mode need not remove all local support.',
                                 'Sensitivity is bounded, not a convergence or coverage proof. Peak pixel mass depends on cell area.',
                                 'Known source/interaction truth was not read by this diagnostic. No signal, calibration or candidate refit.']},
                  provenance={**bindings, 'saved_input_sha256': accounting['input_sha256'],
                              'python': platform.python_version(), 'numpy': np.__version__,
                              'truth_used': False, 'source_labels_used': False,
                              'random_draws': 0, 'new_transport_drift_fields_or_calibration': False,
                              'elapsed_seconds': time.perf_counter()-started})
    for path, expected in ((Path(__file__), bindings['diagnostic_source_sha256']),
                           (Path(J.__file__), bindings['imaging_source_sha256']),
                           (baseline_path, bindings['baseline_report_sha256']),
                           (input_dir/'COMPLETE.json', accounting['input_sha256']['COMPLETE.json'])):
        if digest(path) != expected:
            raise RuntimeError('Source or input seal changed during diagnostic')
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (output_dir/'group_details.jsonl').write_text(''.join(json.dumps(r, separators=(',', ':'), allow_nan=False)+'\n' for r in rows), encoding='utf-8')
    seal = {'status': 'complete_saved_candidate_diagnostic',
            'files': {name: digest(output_dir/name) for name in ('report.json', 'group_details.jsonl')},
            'source_sha256': bindings['diagnostic_source_sha256'], 'new_physics': False}
    (output_dir/'COMPLETE.json').write_text(json.dumps(seal, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--baseline-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.input, args.baseline_report, args.output)
    print(json.dumps({k: result[k] for k in ('group_count', 'candidate_count', 'leave_one_group_out_summary')}, indent=2))
