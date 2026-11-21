"""Profile saved absorption and fixed-line escape cones on identical measured trigger cohorts."""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy

import gegi_candidate_range as ranges
import gegi_interaction_hypothesis_controls as controls
import gegi_joint_imaging as imaging
import gegi_source_range as scores
import scenario_workflow as W


def measured_cohorts(saved, geometry, selection, peak_triggers):
    """Use original chronological ranks and measured windows, independent of photon truth."""
    measured = {row['original_trigger_id']: row for row in geometry['triggers']}
    original = {row['original_trigger_id']: row for row in saved['triggers']}
    for tid, row in measured.items():
        W.require(all(row[key] == original[tid][key] for key in (
            'trigger_time_ns', 'energy_keV', 'projected_mass', 'unresolved_mass', 'pairings')), f'Saved geometry differs for {tid}')
    masks = imaging.spectral_membership([imaging.Event((row['original_trigger_id'], 0), row['energy_keV'], (), 1.)
                                       for row in saved['triggers']], ranges.plane.LINE_ENERGIES_KEV)
    used, top_ids, result = set(), set(), {}
    for name, window in selection['windows'].items():
        ids = [row['original_trigger_id'] for row in window['sampled_triggers']]
        top = set(window['excluded_original_top5_trigger_ids'])
        members = [row for row, in_window in zip(saved['triggers'], masks[name], strict=True) if in_window]
        eligible = sorted((row for row in members if row['original_trigger_id'] not in top),
                          key=lambda row: (row['trigger_time_ns'], row['original_trigger_id']))
        W.require(len(members) == window['original_window_trigger_count'] and
                  len(eligible) == window['eligible_trigger_count'] and top <= {row['original_trigger_id'] for row in members} and
                  len(ids) == len(set(ids)) and not (used & set(ids)) and all(
                      0 <= row['eligible_rank_0'] < len(eligible) and
                      eligible[row['eligible_rank_0']]['original_trigger_id'] == row['original_trigger_id'] and
                      measured[row['original_trigger_id']]['trigger_time_ns'] == row['trigger_time_ns']
                      for row in window['sampled_triggers']), 'Original chronological selection differs')
        used.update(ids)
        top_ids.update(top)
        result[name] = dict(cohort='chronological_measured_window', selected_original_trigger_ids=ids,
                            original_window_trigger_count=window['original_window_trigger_count'],
                            eligible_chronological_trigger_count=window['eligible_trigger_count'])
    W.require(len(set(peak_triggers)) == len(peak_triggers) and set(peak_triggers) <= top_ids and
              set(peak_triggers) | used == measured.keys(), 'Measured geometry must cover the exact selection and named peak witnesses')
    for tid in peak_triggers:
        result[f'peak_witness_{tid}'] = dict(cohort='supplemental_peak_witness', selected_original_trigger_ids=[tid])
    return measured, result


def hypothesis_events(rows, settings, *, escape_line_keV=None):
    """Keep an event once, retaining unsupported order mass through the existing uniform term."""
    records, ledger = [], []
    for row in rows:
        tid = row['original_trigger_id']
        orders, candidates = [], []
        for pair in row['conditional_escape_pairings']:
            measured_pair = pair['original_plane_pairing']
            pair_mass = measured_pair['nominal_mass'] if measured_pair is not None else 0.
            for order in controls.paired_orders(pair):
                branch = order['absorption'] if escape_line_keV is None else next((answer for answer in order['resolved_escape']
                    if answer['incident_energy_keV'] == escape_line_keV), None)
                cone = branch['cone'] if branch is not None else None
                mass = pair_mass/2
                original_order = order['original_projection']
                orders.append(dict(pair_index=pair['pair_index'], cells=pair['cells'], order=order['site_index_order'],
                    original_nominal_pair_mass=pair_mass, diagnostic_precheck_order_mass=mass,
                    original_absorption_order=original_order, state='projectable' if cone is not None else
                    'energy_pairing_unavailable' if branch is None else 'unsupported_kinematics_or_geometry',
                    projected_mass=mass if cone is not None else 0., conditional_cone=cone))
                if cone is not None:
                    candidates.append(dict(cone, second_vertex_mm=cone['second_site_mm'], prior_weight=mass))
        record = dict(event_id=tid, energy_keV=row['energy_keV'], candidates=candidates)
        records.append(record)
        ledger.append(dict(original_trigger_id=tid, archive_record_sha256=row['archive_record_sha256'],
            official_projected_mass=row['projected_mass'], official_unresolved_mass=row['unresolved_mass'], orders=orders))
    events = imaging.prepare_events(records, settings)
    for event, entry in zip(events, ledger, strict=True):
        entry['diagnostic_projected_mass'] = math.fsum(cone.prior for cone in event.candidates)
        entry['diagnostic_unresolved_mass'] = event.unresolved_mass
    return events, ledger


def one_profile(rows, settings, radii, *, escape_line_keV, mode, directions, starts, score_drop):
    events, ledger = hypothesis_events(rows, settings, escape_line_keV=escape_line_keV)
    result = dict(escape_incident_line_keV=escape_line_keV, selected_trigger_count=len(events),
                  original_trigger_ids=[event.identity[0] for event in events], per_trigger_order_ledger=ledger,
                  triggers_with_geometry=sum(bool(event.candidates) for event in events),
                  projected_trigger_mass=math.fsum(cone.prior for event in events for cone in event.candidates),
                  unresolved_trigger_mass=math.fsum(event.unresolved_mass for event in events))
    if not result['triggers_with_geometry']:
        return dict(result, status='all_selected_triggers_unresolved', fit=None), None
    scorer = scores.AngularScore(events, [], settings, require_both_splits=False)
    W.require(math.isclose(result['unresolved_trigger_mass'] + result['projected_trigger_mass'], len(events), abs_tol=1e-12),
              'Conditional event mass does not close')
    fit = ranges.fit_profile(scorer, radii, mode=mode, directions=directions, starts=starts, score_drop=score_drop)
    return dict(result, status='conditional_profile_computed', kernel_parity_max_abs=scorer.validate(float(radii[0])), fit=fit), scorer


def fit_blind(saved_path, geometry_path, selection_path, *, peak_triggers, radius_min_mm, radius_max_mm, radial_points,
              directions, starts, background, score_drop):
    saved, plane_sha = controls.read(saved_path)
    measured_geo, geometry_sha = controls.read(geometry_path)
    selection, selection_sha = controls.read(selection_path)
    expected = dict(saved_plane=plane_sha, candidate_store=saved['input_sha256']['candidate_store'])
    W.require(measured_geo['input_sha256'] == expected, 'Measured geometry and saved reconstruction differ')
    W.require(radial_points >= 2 and 0 < radius_min_mm < radius_max_mm and 0 <= background < 1 and
              directions >= 1 and starts >= 1 and math.isfinite(score_drop) and score_drop > 0, 'Invalid conditional range settings')
    settings = imaging.ResponseSettings(strip_pitch_mm=saved['model']['strip_pitch_mm'],
        angular_nuisance_sigma_deg=saved['model']['angular_nuisance_sigma_deg'])
    radii = np.geomspace(radius_min_mm, radius_max_mm, radial_points)
    line_models = measured_geo['incident_line_configuration']['incident_energies_keV']
    measured, groups = measured_cohorts(saved, measured_geo, selection, peak_triggers)
    fits, scorers = {}, {}
    mode = (background, 'all')
    for label, group in groups.items():
        rows = [measured[tid] for tid in group['selected_original_trigger_ids']]
        comparison = {}
        for line in (None, *line_models):
            key = 'observed_sum_absorption' if line is None else f'resolved_escape_{line:g}_keV'
            comparison[key], scorers[label, key] = one_profile(rows, settings, radii, escape_line_keV=line, mode=mode,
                directions=directions, starts=starts, score_drop=score_drop)
        fits[label] = dict(group, hypotheses=comparison)
    source = (controls, imaging, ranges, scores)
    return dict(input_sha256={**expected, 'conditional_geometry': geometry_sha, 'chronological_selection': selection_sha},
                source_sha256={Path(module.__file__).name: W.sha(module.__file__) for module in source} |
                              {Path(__file__).name: W.sha(__file__)},
                software=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
                settings=dict(angular_response=asdict(settings), radial_search_mm=[radius_min_mm, radius_max_mm],
                    radial_points=radial_points, direction_domain='full sphere', directions=directions, starts=starts,
                    fixed_extra_uniform_angle_fraction=background, score_drop=score_drop, escape_incident_lines_keV=line_models,
                    diagnostic_order_mass='Retain original measured pairing mass; allocate it equally to both site orders '
                    'before the hypothesis-specific check. All unsupported mass remains uniform-angle, without renormalization. '
                    'Original absorption order masses and acquisition weights are retained.'),
                measured_groups=fits), scorers


def angle_between(a, b):
    cosine = np.dot(a, b) / (np.linalg.norm(a)*np.linalg.norm(b))
    return math.degrees(math.acos(np.clip(cosine, -1., 1.)))


def score_finished(blind, scorers, chronological_path, controls_path):
    """Evaluate only already-computed profiles at independent, verified source coordinates."""
    chronological, chronological_sha = controls.read(chronological_path)
    reference, reference_sha = controls.read(controls_path)
    provenance = chronological['local_replay']['input_sha256']
    W.require(reference['input_sha256']['chronological_origins'] == chronological_sha and
              provenance['selection'] == blind['input_sha256']['chronological_selection'] and
              provenance['saved_plane'] == blind['input_sha256']['saved_plane'] and
              provenance['candidate_store'] == blind['input_sha256']['candidate_store'],
              'Post-fit chronological and photon control receipts differ')
    origins = {row['original_trigger_id']: row for window in chronological['science']['windows'].values() for row in window['triggers']}
    controls_by_id = {row['original_trigger_id']: row for row in reference['rows']}
    hist = {}
    for label, group in blind['measured_groups'].items():
        ids = group['selected_original_trigger_ids']
        coords, unavailable, topologies = {}, [], Counter()
        for tid in ids:
            truth = controls_by_id[tid]
            measured_record = next(row for row in group['hypotheses']['observed_sum_absorption']['per_trigger_order_ledger']
                                   if row['original_trigger_id'] == tid)
            W.require(truth['original_archive_record_sha256'] == measured_record['archive_record_sha256'],
                      f'Post-fit truth identity differs for {tid}')
            topologies[truth['topology']] += 1
            if group['cohort'] == 'chronological_measured_window':
                original = origins[tid]
                W.require(original['measured_window'] == label and original['archive_record_sha256'] == measured_record['archive_record_sha256'],
                          f'Original chronological reference differs for {tid}')
                position = original.get('programmed_source_position_mm_for_scoring')
            else:
                photon = truth.get('photon_kinetics')
                position = photon['source_position_mm_for_scoring'] if photon else None
            if position is None:
                unavailable.append(tid)
            else:
                coords.setdefault(tuple(position), []).append(tid)
        evaluations = []
        for point, tids in sorted(coords.items()):
            comparison = {}
            for name, profile in group['hypotheses'].items():
                fit = profile['fit']
                if fit is None:
                    comparison[name] = None
                    continue
                value = float(scorers[label, name].score(np.array([point]), (blind['settings']['fixed_extra_uniform_angle_fraction'], 'all'))[0, 0])
                comparison[name] = dict(log_score_at_known_source=value, loss_from_fitted_score=fit['log_score']-value,
                    fitted_position_difference_mm=math.dist(fit['position_mm'], point),
                    fitted_direction_difference_deg=angle_between(fit['position_mm'], point),
                    fitted_center_distance_minus_known_mm=fit['center_distance_mm']-math.hypot(*point))
            evaluations.append(dict(known_source_position_mm=list(point), reference_trigger_ids=tids, hypotheses=comparison))
        hist[label] = dict(verified_photon_topology_counts=dict(topologies), unresolved_reference_trigger_ids=unavailable,
            single_known_reference_for_all_triggers=len(coords)==1 and not unavailable, source_reference_scores=evaluations)
    return dict(input_sha256=dict(chronological_origins=chronological_sha, exact_kinetic_controls=reference_sha),
                source_coordinates_used_for_fit=False, reference_composition_and_scores=hist)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('saved', 'geometry', 'selection', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--score-chronological-origins', type=Path)
    parser.add_argument('--score-exact-controls', type=Path)
    parser.add_argument('--peak-trigger-id', action='append', type=int, default=[])
    parser.add_argument('--radius-min-mm', type=float, default=20.)
    parser.add_argument('--radius-max-mm', type=float, default=10000.)
    parser.add_argument('--radial-points', type=int, default=25)
    parser.add_argument('--directions', type=int, default=96)
    parser.add_argument('--starts', type=int, default=3)
    parser.add_argument('--background', type=float, default=.25)
    parser.add_argument('--score-drop', type=float, default=2.)
    args = parser.parse_args()
    if args.output.exists() or bool(args.score_chronological_origins) != bool(args.score_exact_controls):
        parser.error('Choose a new output and supply both optional truth receipts together')
    begun = time.perf_counter()
    blind, scorers = fit_blind(args.saved, args.geometry, args.selection, peak_triggers=args.peak_trigger_id, radius_min_mm=args.radius_min_mm,
        radius_max_mm=args.radius_max_mm, radial_points=args.radial_points, directions=args.directions, starts=args.starts,
        background=args.background, score_drop=args.score_drop)
    blind_sha = hashlib.sha256(W.encoded(blind)).hexdigest()
    post = (score_finished(blind, scorers, args.score_chronological_origins, args.score_exact_controls)
            if args.score_chronological_origins else None)
    W.require(hashlib.sha256(W.encoded(blind)).hexdigest() == blind_sha, 'Post-fit scoring changed a measured fit')
    result = dict(kind='gegi_incident_line_conditional_range_controls_v1', blind_fit_sha256=blind_sha, measured_analysis=blind,
        post_fit_truth_scores=post, elapsed_seconds=time.perf_counter()-begun,
        interpretation='Each measured-window cohort is fit under a single hypothetical common location separately for each fixed model. '
                       'Merged and unsupported histories retain their original identities and denominators. '
                       'The conditional angular likelihood is normalized in observed angle; it does not include energy-line likelihood, '
                       'photon escape or detection acceptance, or calibrated probabilities of order, topology or source membership. '
                       'Radial profiles and peak witnesses do not establish physical range or support choosing a hypothesis by truth proximity.')
    with args.output.open('xb') as output:
        output.write(W.encoded(result)+b'\n')
    print(json.dumps(dict(blind_fit_sha256=blind_sha, measured_groups=len(blind['measured_groups']), elapsed_seconds=result['elapsed_seconds'])))


if __name__ == '__main__':
    main()
