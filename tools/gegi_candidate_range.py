"""Three-dimensional conditional source scores from retained candidate cones.

Direction is free on the sphere. The radial search is configurable and reported;
its endpoints are numerical search settings, not inferred physical boundaries.
Scores use the existing finite-vertex angular response, never a plane-normalized
image. Profile drops are diagnostics, not calibrated confidence intervals.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.optimize import minimize

import gegi_continuous_plane as plane
from gegi_source_range import AngularScore, profiled_background
from gegi_joint_imaging import ResponseSettings, spectral_membership


ESCAPE_RANGE_KIND = 'gegi_candidate_fixed_line_escape_range_v1'


def direction(angles):
    theta, phi = np.asarray(angles).T
    return np.array([np.sin(theta)*np.cos(phi), np.sin(theta)*np.sin(phi), np.cos(theta)]).T


def sphere_grid(count):
    """Equal-area Fibonacci directions; contains no source-position prior."""
    index = np.arange(count)
    return np.column_stack((np.arccos(1-2*(index+.5)/count), index*math.pi*(3-math.sqrt(5))))


def separated_starts(angles, scores, count):
    selected = []
    for i in np.argsort(-scores, kind='stable'):
        if all(direction(angles[i]) @ direction(angles[j]) < .95 for j in selected):
            selected.append(i)
        if len(selected) == count:
            break
    return [angles[i] for i in selected]


def background_at(scorer, points, mode, *, far_field=False):
    if mode[0] is not None:
        return np.full(len(points), mode[0])
    split = {'first': slice(None, scorer.first_informative),
             'second': slice(scorer.first_informative, None), 'all': slice(None)}[mode[1]]
    return np.concatenate([profiled_background(scorer.relative_log_response(
        batch, far_field=far_field)[:, split])[1] for batch in scorer.batches(points)])


def fit_far_field(scorer, mode, directions, starts):
    """Optimize the exact infinite-range limit, with no arbitrary far plane."""
    angles = sphere_grid(directions)
    values = scorer.score(direction(angles), mode, far_field=True)[:, 0]
    guesses = separated_starts(angles, values, starts)
    def objective(a):
        return -scorer.score(np.atleast_2d(direction(a)), mode, far_field=True)[0, 0]
    trials = [minimize(objective, guess, method='BFGS', options={'gtol': 1e-6}) for guess in guesses]
    best = min(trials, key=lambda result: result.fun)
    unit = direction(best.x)
    return dict(direction_unit_vector=unit.tolist(), log_score=-float(best.fun),
                uniform_angle_fraction=float(background_at(scorer, np.atleast_2d(unit), mode, far_field=True)[0]),
                optimizer_success=bool(best.success), optimizer_message=str(best.message))


def fit_profile(scorer, radii, *, mode=(.25, 'all'), directions=96, starts=3,
                score_drop=2.):
    """At every fixed center-distance reoptimize the two directional coordinates."""
    radii = np.asarray(radii, float)
    if (radii.ndim != 1 or len(radii) < 2 or not np.isfinite(radii).all()
            or np.any(radii <= 0) or np.any(np.diff(radii) <= 0)):
        raise ValueError('Specify increasing positive radial search points in mm')
    angles = sphere_grid(directions)
    coarse = np.array([scorer.score(radius*direction(angles), mode)[:, 0] for radius in radii])
    profile = []
    for radius, grid in zip(radii, coarse, strict=True):
        guesses = separated_starts(angles, grid, starts)
        if profile:
            guesses.append(np.array(profile[-1]['angles_rad']))
        def objective(a):
            return -scorer.score(np.atleast_2d(radius*direction(a)), mode)[0, 0]
        trials = [minimize(objective, guess, method='BFGS', options={'gtol': 1e-6}) for guess in guesses]
        best = min(trials, key=lambda result: result.fun)
        profile.append(dict(center_distance_mm=float(radius), position_mm=(radius*direction(best.x)).tolist(),
                            angles_rad=best.x.tolist(), log_score=-float(best.fun),
                            optimizer_success=bool(best.success), optimizer_message=str(best.message)))
    top = sorted(profile, key=lambda row: row['log_score'], reverse=True)[:starts]
    def objective(coordinate):
        point = math.exp(coordinate[2])*direction(coordinate[:2])
        return -scorer.score(np.atleast_2d(point), mode)[0, 0]
    trials = [minimize(objective, [*row['angles_rad'], math.log(row['center_distance_mm'])],
                       method='L-BFGS-B', bounds=[(None, None), (None, None),
                                                (math.log(radii[0]), math.log(radii[-1]))],
                       options={'ftol': 1e-11, 'gtol': 1e-6}) for row in top]
    best = min(trials, key=lambda result: result.fun)
    radius = math.exp(best.x[2]); position = radius*direction(best.x[:2]); value = -float(best.fun)
    # The best fixed-radius fit remains a valid candidate if a local 3D solve stalls.
    fixed = max(profile, key=lambda row: row['log_score'])
    if fixed['log_score'] > value:
        radius, position, value = fixed['center_distance_mm'], np.array(fixed['position_mm']), fixed['log_score']
        success, message = fixed['optimizer_success'], fixed['optimizer_message']
    else:
        success, message = bool(best.success), str(best.message)
    # Include the continuous optimum so a coarse mesh never reports empty
    # support around a narrow, finite maximum. Other disconnected modes remain.
    if not any(math.isclose(radius, row['center_distance_mm'], rel_tol=1e-10) for row in profile):
        profile.append(dict(center_distance_mm=float(radius), position_mm=position.tolist(),
                            angles_rad=[float(math.acos(np.clip(position[2]/radius, -1, 1))),
                                        float(math.atan2(position[1], position[0]))],
                            log_score=value, optimizer_success=success, optimizer_message=message))
        profile.sort(key=lambda row: row['center_distance_mm'])
    for row in profile:
        row['loss_from_best_score'] = value-row['log_score']
    supported = [row for row in profile if row['loss_from_best_score'] <= score_drop]
    lower_open = profile[0]['loss_from_best_score'] <= score_drop
    upper_open = profile[-1]['loss_from_best_score'] <= score_drop
    crossing_brackets = [[left['center_distance_mm'], right['center_distance_mm']]
                         for left, right in zip(profile, profile[1:])
                         if (left['loss_from_best_score'] <= score_drop) !=
                            (right['loss_from_best_score'] <= score_drop)]
    fractions = background_at(scorer, np.array([row['position_mm'] for row in profile]), mode)
    for row, fraction in zip(profile, fractions, strict=True):
        row['uniform_angle_fraction'] = float(fraction)
    far_field = fit_far_field(scorer, mode, directions, starts)
    far_field_supported = value-far_field['log_score'] <= score_drop
    return dict(position_mm=position.tolist(), center_distance_mm=float(radius), reference_origin_mm=[0., 0., 0.],
                log_score=value, optimizer_success=success, optimizer_message=message,
                uniform_angle_fraction=float(background_at(scorer, np.atleast_2d(position), mode)[0]),
                uniform_angle_fraction_profiled=mode[0] is None,
                far_field=far_field, score_gain_over_far_field=value-far_field['log_score'],
                at_radial_search_boundary=bool(np.isclose(radius, radii[0], rtol=1e-5)
                                              or np.isclose(radius, radii[-1], rtol=1e-5)),
                radial_profile=profile,
                profile_diagnostic=dict(score_drop=float(score_drop), calibrated_confidence_level=None,
                    lower_open=lower_open, upper_open=upper_open,
                    far_field_supported=far_field_supported,
                    score_drop_crossing_brackets_mm=crossing_brackets,
                    sampled_support_mm=None if not supported else [supported[0]['center_distance_mm'],
                                                                  supported[-1]['center_distance_mm']],
                    status='open_profile_distance_unidentified' if lower_open or upper_open or far_field_supported else
                           'closed_profile_requires_independent_calibration'))


def analyze_events(events, times_ns, live_time_ns, settings, radii, *, directions=96,
                   starts=3, background=.25, score_drop=2., profile_background=False):
    """No source truth/activities enter this interface."""
    groups = [[event for event, t in zip(events, times_ns, strict=True)
               if (t < live_time_ns/2) == is_first] for is_first in (True, False)]
    if any(not any(event.candidates for event in group) for group in groups):
        return dict(status='insufficient_geometry_for_clock_halves', selected_triggers=len(events))
    scorer = AngularScore(*groups, settings)
    parity = scorer.validate(float(radii[0]))
    modes = {'primary': (background, 'all'), 'no_extra_background': (0., 'all'),
             'first_clock_half': (background, 'first'), 'second_clock_half': (background, 'second')}
    if profile_background:
        modes['profiled_background'] = (None, 'all')
    fits = {label: fit_profile(scorer, radii, mode=mode, directions=directions,
                               starts=starts, score_drop=score_drop) for label, mode in modes.items()}
    return dict(status='conditional_scores_computed', accounting=scorer.accounting,
                selected_original_trigger_ids=[e.identity[0] for e in events],
                split_trigger_counts=[len(group) for group in groups],
                response_parity_max_abs=parity, fits=fits,
                split_position_difference_mm=math.dist(fits['first_clock_half']['position_mm'],
                                                       fits['second_clock_half']['position_mm']),
                background_position_difference_mm=math.dist(fits['primary']['position_mm'],
                                                            fits['no_extra_background']['position_mm']))


def prepare_escape_events(saved, bound_rows, settings, incident_energy_keV, selected_ids):
    """Apply the same fixed-line cone and precheck mass policy to saved fits."""
    from gegi_incident_geometry import pairing_geometry, hypotheses
    from gegi_joint_imaging import prepare_events

    lines = hypotheses.configuration([incident_energy_keV])['incident_energies_keV']
    receipt = saved['fit_receipt']
    position_model = receipt.get('position_model', 'center')
    records, ledger = [], []
    selected = set(selected_ids)
    for old, fitted, binding in zip(saved['triggers'], receipt['candidates'], bound_rows, strict=True):
        trigger_id = old['original_trigger_id']
        if trigger_id not in selected:
            continue
        original_pairs = {pair['index']: pair for pair in old['pairings']}
        cones, orders = [], []
        for slot in fitted['pairings']:
            original = original_pairs.get(slot['index'])
            pairing = pairing_geometry(slot, original, position_model, lines)
            kinematics = pairing['kinematics']
            branches = {tuple(row['site_index_order']): row for line in kinematics.get('incident_line_hypotheses', ())
                        for row in line['two_resolved_scatter_escape_orders']}
            pair_mass = original['nominal_mass'] if original is not None else 0.
            original_orders = {tuple(row['order']): row for row in original['orders']} if original is not None else {}
            for order in hypotheses.ORDERS:
                branch = branches.get(order)
                cone = branch['cone'] if branch is not None else None
                mass = pair_mass / 2
                if cone is not None:
                    cones.append(dict(cone, second_vertex_mm=cone['second_site_mm'], prior_weight=mass))
                orders.append(dict(pair_index=slot['index'], cells=slot['cells'], order=list(order),
                                   original_nominal_pair_mass=pair_mass, diagnostic_precheck_order_mass=mass,
                                   original_absorption_order=original_orders.get(order),
                                   state='projectable' if cone is not None else 'energy_pairing_unavailable' if branch is None
                                   else 'unsupported_kinematics_or_geometry',
                                   geometry_status=branch['geometry_status'] if branch is not None else kinematics['status'],
                                   projected_mass=mass if cone is not None else 0., conditional_cone=cone))
        records.append(dict(event_id=trigger_id, energy_keV=old['energy_keV'], candidates=cones))
        ledger.append(dict(original_trigger_id=trigger_id, trigger_time_ns=old['trigger_time_ns'],
                           archive_record_sha256=binding['archive_record_sha256'], archive_adc_sha256=binding['archive_adc_sha256'],
                           official_projected_mass=old['projected_mass'], official_unresolved_mass=old['unresolved_mass'], orders=orders))
    events = prepare_events(records, settings)
    for event, row in zip(events, ledger, strict=True):
        row['diagnostic_projected_mass'] = math.fsum(cone.prior for cone in event.candidates)
        row['diagnostic_unresolved_mass'] = event.unresolved_mass
    return events, ledger


def analyze_escape_events(events, settings, radii, *, directions, starts, background, score_drop, profile_background):
    ids = [event.identity[0] for event in events]
    result = dict(selected_original_trigger_ids=ids, fits={})
    if not any(event.candidates for event in events):
        return dict(result, status='all_selected_triggers_unresolved' if ids else 'no_selected_triggers',
                    accounting=dict(selected_triggers=len(events), triggers_with_geometry=0, allowed_saved_geometry_orders=0,
                                    projected_trigger_mass=0., unresolved_trigger_mass=float(len(events))))
    scorer = AngularScore(events, [], settings, require_both_splits=False)
    modes = {'primary': (background, 'all')}
    if profile_background:
        modes['profiled_background'] = (None, 'all')
    fits = {name: fit_profile(scorer, radii, mode=mode, directions=directions,
                              starts=starts, score_drop=score_drop) for name, mode in modes.items()}
    return dict(result, status='conditional_scores_computed', accounting=scorer.accounting,
                response_parity_max_abs=scorer.validate(float(radii[0])), fits=fits)


def run(path, *, radius_min_mm=20., radius_max_mm=10000., radial_points=49,
        directions=192, starts=6, background=.25, score_drop=2., output=None, archive=None,
        profile_background=False, escape_incident_energy_keV=None, trigger_ids=None):
    from gegi_candidate_records import events_from_saved
    begun = time.perf_counter(); path = Path(path)
    if output is not None and Path(output).exists():
        raise FileExistsError(output)
    escape = escape_incident_energy_keV is not None
    if trigger_ids is not None and not escape:
        raise ValueError('An explicit trigger subset is available only for the fixed-line escape diagnostic')
    raw = path.read_bytes(); saved = json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)
    settings = ResponseSettings(strip_pitch_mm=saved['model']['strip_pitch_mm'],
                                angular_nuisance_sigma_deg=saved['model']['angular_nuisance_sigma_deg'])
    archive = Path(archive) if archive else path.parent/'compton-candidates.sqlite'
    with archive.open('rb') as stream:
        archive_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    if archive_sha != saved['input_sha256']['candidate_store']:
        raise ValueError('Candidate archive differs from the saved imaging input')
    events, rows = events_from_saved(saved, archive, settings)
    times = np.array([row['trigger_time_ns'] for row in saved['triggers']])
    masks = spectral_membership(events, plane.LINE_ENERGIES_KEV)
    labels = [f'{energy:g}_keV' for energy in plane.LINE_ENERGIES_KEV]
    masks['cobalt_both_lines'] = masks[labels[1]] | masks[labels[2]]
    labels.append('cobalt_both_lines')
    radii = np.geomspace(radius_min_mm, radius_max_mm, radial_points)
    result = dict(kind='gegi_candidate_conditional_range_v1', input_sha256=hashlib.sha256(raw).hexdigest(),
        software=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
        input_bindings=saved['input_sha256'], acquisition_selection=saved['selection'],
        model=dict(response=asdict(settings), extra_uniform_angle_fraction=background,
                   background_profiling=profile_background,
                   direction_domain='full sphere; no known source side, plane, symmetry or activity',
                   radial_search_mm=[radius_min_mm, radius_max_mm], radial_points=radial_points,
                   directional_seeds=directions, optimized_starts=starts,
                   method='Finite-vertex per-trigger angular mixture; preserve order and unresolved mass. '
                          'Profile center distance while reoptimizing direction; optionally profile uniform-angle '
                          'fraction at each point. Compare the exact infinite-range limit. No finite-image normalization.',
                   uncertainty='Default strip quantization plus nominal angular width; depth and energy '
                               'uncertainties uncalibrated. Scores are not calibrated probabilities or intervals.'),
        fits={}, source_sha256={name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                               for name in (Path(__file__).name, 'gegi_joint_imaging.py',
                                            'gegi_source_range.py', 'gegi_candidate_records.py')})
    if escape:
        available_ids = [event.identity[0] for event in events]
        requested = available_ids if trigger_ids is None else tuple(trigger_ids)
        selected_set = set(requested)
        if (not requested or len(selected_set) != len(requested) or not selected_set <= set(available_ids)
                or any(type(i) is not int or i <= 0 for i in requested)):
            raise ValueError('Select distinct original two-strip trigger IDs from the saved map')
        keep = np.array([i in selected_set for i in available_ids], dtype=bool)
        selected_ids = [i for i, yes in zip(available_ids, keep, strict=True) if yes]
        escape_events, ledger = prepare_escape_events(saved, rows, settings, escape_incident_energy_keV, selected_ids)
        result['kind'] = ESCAPE_RANGE_KIND
        result['scope'] = dict(original_two_strip_triggers=len(available_ids), selected_original_trigger_ids=selected_ids,
                               omitted_original_trigger_count=len(available_ids)-len(selected_ids),
                               selected_outside_line_windows=[i for i, outside, yes in zip(
                                   available_ids, masks['other_energy'], keep, strict=True) if yes and outside])
        result['escape_trigger_order_ledger'] = ledger
        result['model'].update(fixed_incident_energy_keV=escape_incident_energy_keV,
            interaction_hypothesis='two_resolved_compton_scatters_then_escape',
            order_mass_policy='Diagnostic only. Split each original measured pairing mass equally over both orders before checking '
                              'escape support. Unsupported mass stays uniform in angle without renormalization. Original map weights stay fixed.',
            limitations='Each window fits one hypothetical common position from the conditional angular score. Energy-line likelihood, '
                        'escape and detection acceptance, and calibrated order, topology or source-membership probabilities are unavailable.')
        for name in ('gegi_incident_geometry.py', 'gegi_incident_hypotheses.py'):
            result['source_sha256'][name] = hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
    for label in labels:
        mask = masks[label]
        if escape:
            selected = [event for event, yes in zip(escape_events, mask[keep], strict=True) if yes]
            result['fits'][label] = analyze_escape_events(selected, settings, radii, directions=directions, starts=starts,
                background=background, score_drop=score_drop, profile_background=profile_background)
            result['fits'][label]['original_window_trigger_count'] = int(mask.sum())
        else:
            selected = [event for event, yes in zip(events, mask, strict=True) if yes]
            result['fits'][label] = analyze_events(selected, times[mask], saved['selection']['clock_live_time_ns'],
                settings, radii, directions=directions, starts=starts, background=background, score_drop=score_drop,
                profile_background=profile_background)
        result['elapsed_seconds'] = time.perf_counter()-begun
        result['status'] = 'complete' if len(result['fits']) == len(labels) else 'partial'
        if output:
            write_result(output, result)
        print(label + ': ' + json.dumps(result['fits'][label].get('fits', {}).get('primary', {}).get('position_mm')), flush=True)
    return result


def write_result(path, result):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--imaging', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive', type=Path, help='Candidate archive; defaults to the imaging file directory')
    parser.add_argument('--radius-min-mm', type=float, default=20.)
    parser.add_argument('--radius-max-mm', type=float, default=10000.)
    parser.add_argument('--radial-points', type=int, default=49)
    parser.add_argument('--directions', type=int, default=192)
    parser.add_argument('--starts', type=int, default=6)
    parser.add_argument('--background', type=float, default=.25)
    parser.add_argument('--profile-background', action='store_true',
                        help='Also optimize the uniform-angle fraction at every source position')
    parser.add_argument('--escape-incident-energy-keV', type=float, metavar='ENERGY',
                        help='Fit two resolved Compton scatters followed by escape at one supplied photon energy')
    parser.add_argument('--trigger-id', type=int, action='append', help='Repeat to select original trigger IDs for the escape diagnostic')
    parser.add_argument('--score-drop', type=float, default=2.)
    args = parser.parse_args()
    run(args.imaging, radius_min_mm=args.radius_min_mm, radius_max_mm=args.radius_max_mm,
        radial_points=args.radial_points, directions=args.directions, starts=args.starts,
        background=args.background, score_drop=args.score_drop, output=args.output, archive=args.archive,
        profile_background=args.profile_background, escape_incident_energy_keV=args.escape_incident_energy_keV,
        trigger_ids=args.trigger_id)


if __name__ == '__main__':
    main()
