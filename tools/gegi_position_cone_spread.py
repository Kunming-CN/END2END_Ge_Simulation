"""Propagate matched GeGI ADC fit alternatives into conditional finite-vertex cones."""

import argparse
from collections import Counter
from itertools import combinations
import json
import math
from pathlib import Path

import numpy as np

import gegi_candidate_range as source_range
from gegi_event_store import encoded, sha
import gegi_imaging as imaging
import gegi_joint_imaging as response
import gegi_joint_two_site_study as study


COMPAT_SHA = 'da2c8da369b70564508827978c48665565d61859acc55f11764d84cbd6316fea'
UNCERTAINTY_SHA = '6accb91c8e3076b0b535e5d3a1fea662c951450aab9645b97a1c9ad79fcccd24'
MODELS = ('center', 'lateral')
RADII_MM = (50., 100., 300., 1000.)
DIRECTIONS = 96
SIGMA_DEG = response.ResponseSettings().angular_nuisance_sigma_deg


def bound(path, digest):
    raw = path.read_bytes()
    if sha(raw) != digest:
        raise ValueError(f'Saved input changed at {path.name}')
    return json.loads(raw)


def solutions(model):
    return [{'fit_role': 'best' if i == 0 else 'sampled_alternate',
             'positions_mm': row['positions_mm'], 'weighted_residual_rms': row['weighted_residual_rms'],
             'onset_relative_to_trigger_ns': row['parameters'][-1],
             'optimizer_success': row['optimizer_success'], 'parameter_boundaries': row['parameter_boundaries'],
             'site_separation_mm': math.dist(*row['positions_mm'])}
            for i, row in enumerate((model, *model['sampled_alternates']))]


def replay_differences(model, saved, energies):
    positions = model['positions_mm']
    axis = study.cfd.axis_between(*positions)
    saved_spread = max((study.cfd.angle_error(axis, study.cfd.axis_between(*row['positions_mm']))
                        for row in model['sampled_alternates']), default=0.)
    if saved['measured_site_energies_keV'] != energies:
        raise ValueError('Replay must use exactly the saved measured energies')
    return {'best_position_max_xyz_difference_mm': float(np.max(np.abs(np.asarray(positions)-saved['positions_mm']))),
            'best_all34_rms_difference_adc_codes': float(np.sqrt(np.mean(np.square(model['compatibility']['adc_rms_codes']))))
                                                    - saved['all_adc_rms_codes'],
            'near_tie_parameter_spread_difference_in_model_units': (
                np.asarray(model['sampled_near_tie_spread'])-saved['near_tie_parameter_spread']).tolist(),
            'near_tie_best_to_alternate_axis_spread_difference_deg': saved_spread-saved['near_tie_axis_spread_deg'],
            'archived_optimizer_success': saved['optimizer_success']}


def axis_angle(a, b):
    return math.degrees(math.atan2(np.linalg.norm(np.cross(a, b)), np.dot(a, b)))


def response_spread(candidates, points, radii):
    # Positions already vary explicitly through the joint samples. The fixed
    # kernel isolates this geometry comparison from any extra uncertainty term.
    alpha = np.array([response.geometric_angle_and_variance(candidate, points)[0] for candidate in candidates])
    density = np.array([response.angular_density(candidate.theta, angles, math.radians(SIGMA_DEG))
                        for candidate, angles in zip(candidates, alpha, strict=True)])
    angle = np.degrees(np.ptp(alpha, axis=0)).reshape(len(radii), -1)
    span = np.ptp(density, axis=0).reshape(angle.shape)
    return [{'radius_mm': radius, 'geometric_angle_span_rms_deg': float(np.sqrt(np.mean(a*a))),
             'geometric_angle_span_max_deg': float(np.max(a)),
             'fixed_kernel_response_span_rms_per_rad': float(np.sqrt(np.mean(d*d))),
             'fixed_kernel_response_span_max_per_rad': float(np.max(d))}
            for radius, a, d in zip(radii, angle, span, strict=True)]


def order_geometry(samples, energies, order, points, radii):
    """Retain joint positions and optimizer status without assigning sample mass."""
    i, j = order['site_index_order']
    rows = []
    for index, sample in enumerate(samples):
        positions = sample['positions_mm']
        first, second = (dict(position_mm=positions[k], energy_keV=energies[k]) for k in (i, j))
        candidate = None
        if not order['kinematically_allowed']:
            status = 'energy_order_inadmissible'
        else:
            candidate = imaging.cone(first, second)
            status = 'available_geometry' if candidate is not None else 'geometry_below_existing_separation_support'
        if candidate is not None and (not math.isclose(candidate['half_angle_deg'], order['half_angle_deg'],
                                                       rel_tol=0., abs_tol=1e-9)):
            raise ValueError('Angle from measured energies differs from the original order')
        rows.append({'solution_index': index, 'geometry_status': status, 'cone': candidate})
    # Convergence is recorded per sample. Any finite saved alternative can
    # describe conditional geometry; its optimizer status remains visible.
    cones = [row['cone'] for row in rows if row['cone'] is not None]
    result = {'status': 'available_geometry' if cones else (rows[0]['geometry_status'] if rows else 'no_saved_fit'),
              'solutions': rows, 'geometry_count': len(cones), 'axis_pairwise_span_max_deg': None,
              'converged_geometry_count': sum(row['cone'] is not None and sample['optimizer_success']
                                              for row, sample in zip(rows, samples, strict=True)),
              'site_separation_range_mm': None, 'finite_vertex_response_by_radius': []}
    if cones:
        axes = [c['axis'] for c in cones]
        distances = [c['site_separation_mm'] for c in cones]
        settings = response.ResponseSettings()
        candidates = [response.prepare_candidate(c | {'position_covariance_mm2': np.zeros((2, 3, 3))}, settings)
                      for c in cones]
        result.update(axis_pairwise_span_max_deg=max((axis_angle(a, b) for a, b in combinations(axes, 2)), default=0.),
                      site_separation_range_mm=[min(distances), max(distances)],
                      finite_vertex_response_by_radius=response_spread(candidates, points, radii))
    return result


def compare_trial(trial, archived, retained, points):
    trial_id = trial['trial_index']
    if trial_id != retained['trial'] or not trial['adc_sha256'] == retained['adc_sha256'] == archived['adc_sha256']:
        raise ValueError('Replay ADC differs from the saved control')
    pairs = []
    for fit, pair, previous in zip(trial['fits'], archived['measured_pairings'], retained['pairings'], strict=True):
        cells = [s['contact_ids'] for s in pair['sites']]
        energies = [s['energy_keV'] for s in pair['sites']]
        if (fit['status'] != previous['status'] or not fit['pairing_index'] == pair['index'] == previous['pairing_index']
                or not fit['contact_ids'] == cells == previous['cells']):
            raise ValueError('Original fitted pairing identity changed')
        models = {}
        deltas = {}
        for name in MODELS:
            model = fit.get('fits', {}).get('waveform_all', {}).get(name)
            lookup = previous['hypotheses'].get(f'waveform_all_{name}')
            if model is None and lookup is None:
                models[name] = []
            else:
                if model is None or lookup is None:
                    raise ValueError('Replay has different fit coverage')
                deltas[name] = replay_differences(model, lookup, energies)
                models[name] = solutions(model)
        orders = fit['order_hypotheses']
        if orders != [{k: v for k, v in order.items() if k != 'conditional_cone'} for order in pair['orders']]:
            raise ValueError('Original measured order hypotheses changed')
        geometry = [order | {'models': {m: order_geometry(models[m], energies, order, points, RADII_MM)
                                       for m in MODELS}} for order in orders]
        # Keep the original two-injection match as a separate post-fit score.
        if previous['match_label'] == 'true_two_site_assignment':
            truth = {tuple(s['contact_ids']): s['xyz_mm'] for s in retained['reference_sites']}
            for order in geometry:
                i, j = order['site_index_order']
                truth_axis = study.cfd.axis_between(truth[tuple(cells[i])], truth[tuple(cells[j])])
                for model in order['models'].values():
                    for sample in model['solutions']:
                        c = sample['cone']
                        sample['axis_to_injected_positions_deg'] = axis_angle(c['axis'], truth_axis) if c else None
        pairs.append({'pairing_index': pair['index'], 'cells': cells, 'pairing_status': fit['status'],
                      'measured_site_energies_keV': energies, 'energy_compatible': pair['energy_compatible'],
                      'models': models, 'orders': geometry, 'archived_fit_replay_differences': deltas,
                      'posthoc_cell_match': previous['match_label']})
    return {'trial_id': trial_id, 'holdout_group': retained['holdout_group'], 'adc_sha256': trial['adc_sha256'],
            'pairings': pairs}


def summarize(trials):
    pairs = [pair for trial in trials for pair in trial['pairings']]
    result = {'trial_count': len(trials), 'physical_layout_count': len({t['holdout_group'] for t in trials}),
              'pairing_status': dict(Counter(p['pairing_status'] for p in pairs)), 'models': {}}
    for name in MODELS:
        orders = [order['models'][name] for p in pairs for order in p['orders']]
        present = [o for o in orders if o['geometry_count']]
        deltas = [p['archived_fit_replay_differences'][name] for p in pairs if p['models'][name]]
        result['models'][name] = {'order_status': dict(Counter(o['status'] for o in orders)),
                                  'orders_with_multiple_sampled_geometries': sum(o['geometry_count'] > 1 for o in present),
                                  'orders_with_unconverged_sample_geometry': sum(o['geometry_count'] > o['converged_geometry_count']
                                                                                for o in present),
                                  'maximum_axis_pairwise_span_deg': max((o['axis_pairwise_span_max_deg'] for o in present), default=None),
                                  'maximum_archived_best_position_difference_mm': max(
                                      (d['best_position_max_xyz_difference_mm'] for d in deltas), default=None),
                                  'maximum_archived_axis_spread_difference_deg': max(
                                      (abs(d['near_tie_best_to_alternate_axis_spread_difference_deg']) for d in deltas), default=None),
                                  'maximum_finite_vertex_angle_span_deg_by_radius': [
                                      max((o['finite_vertex_response_by_radius'][i]['geometric_angle_span_max_deg']
                                           for o in present), default=None) for i in range(len(RADII_MM))]}
    return result


def run(compatibility_path, uncertainty_path):
    compatible = bound(compatibility_path, COMPAT_SHA)['controls']['general']
    saved = bound(uncertainty_path, UNCERTAINTY_SHA)
    original = bound(study.STUDY, study.STUDY_SHA)['trials']
    trial_ids = compatible['matched_comparisons']['waveform_all_center_to_waveform_all_lateral']['trial_ids']
    target_cases = {original[i]['case_index'] for i in trial_ids}
    replay = study.run(compatibility=True, case_indices=target_cases)
    if replay['input_sha256'] != compatible['input_sha256'] or [r['trial_index'] for r in replay['trials']] != trial_ids:
        raise ValueError('Replay differs from the original matched trial or calibration scope')
    retained = {t['trial']: t for t in saved['trials'] if t['cohort'] == 'general'}
    if any(compatible['trials'][i]['adc_sha256'] != retained[i]['adc_sha256'] for i in trial_ids):
        raise ValueError('Position control receipts do not bind to the same ADC')
    directions = source_range.direction(source_range.sphere_grid(DIRECTIONS))
    points = np.vstack([r*directions for r in RADII_MM])
    trials = [compare_trial(row, original[i], retained[i], points) for i, row in zip(trial_ids, replay['trials'], strict=True)]
    inputs = compatible['input_sha256'] | {'position_compatibility': COMPAT_SHA, 'position_uncertainty': UNCERTAINTY_SHA}
    module_paths = [Path(__file__), Path(imaging.__file__), Path(response.__file__), Path(source_range.__file__)]
    return {'kind': 'gegi_matched_position_cone_spread_v1', 'input_sha256': inputs,
            'archived_fit_source_sha256': compatible['source_sha256'],
            'source_sha256': replay['source_sha256'] | {p.name: sha(p.read_bytes()) for p in module_paths},
            'trial_selection': {'trial_ids': trial_ids, 'case_indices': sorted(target_cases),
                                'basis': 'Previously declared matched full-34 center and lateral controls'},
            'grid': {'origin_mm': [0., 0., 0.], 'radii_mm': RADII_MM, 'unit_directions': directions.tolist(),
                     'fixed_angular_kernel_sigma_deg': SIGMA_DEG},
            'summary': summarize(trials), 'trials': trials,
            'definition': 'The archived controls store spread summaries. Replaying the identical ADC and calibration recovers '
                          'the complete position pairs; differences from the archived numeric summaries are retained. '
                          'Each full joint position pair moves together under fixed measured energies and original orders. '
                          'Axis spans are pairwise maxima. Finite-vertex spans are ranges across sampled geometries at each '
                          'fixed grid point, aggregated by shell. Angular density uses the stated fixed kernel solely for shape '
                          'comparison. Optimizer statuses remain explicit. The deterministic samples do not establish '
                          'probabilities, confidence intervals, source position, or imaging weights.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compatibility', required=True, type=Path)
    parser.add_argument('--uncertainty', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output path')
    result = run(args.compatibility, args.uncertainty)
    data = encoded(result)+b'\n'
    with args.output.open('xb') as stream:
        stream.write(data)
    print(json.dumps({'sha256': sha(data), 'summary': result['summary']}))


if __name__ == '__main__':
    main()
