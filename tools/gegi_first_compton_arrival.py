"""First-Compton density at a fixed Ge vertex per emitted isotropic photon.

The source emits uniformly in solid angle. The ray volume element is
dV = distance**2 * dOmega * ds. Ge survival uses the total coefficient in
inverse mm and the competing Compton process supplies its integrated rate.
See Yoneda et al. https://arxiv.org/html/2107.01846, equations 18–20,
and Geant4's Physics Reference Manual, True Step Length.
"""

import argparse
from collections import Counter
import math
from pathlib import Path
import time

import numpy as np

import gegi_candidate_trial_curve_bank as bank
import gegi_photon_continuation as photon
import scenario_workflow as W


def incoming_ge_path(crystal, source_mm, first_mm):
    """Trace the incoming segment in the existing convex, homogeneous Ge crystal."""
    vertices = np.asarray([source_mm, first_mm], dtype=float)
    if vertices.shape != (2, 3) or not np.isfinite(vertices).all():
        raise ValueError('Supply finite source and first-vertex XYZ positions in mm')
    source, first = vertices
    normals, offsets = crystal
    source_margin = float(np.min(offsets - normals @ source))
    region = ('outside_ge' if source_margin < -1e-9 else
              'ge_boundary' if source_margin <= 1e-9 else 'inside_ge')
    delta = first-source
    distance = math.hypot(*delta)
    result = dict(source_region=region, source_to_vertex_mm=distance, incoming_direction=None,
                  ge_path_start_mm=None, ge_path_to_first_mm=None)
    if float(np.min(offsets - normals @ first)) < -1e-9:
        return dict(result, geometry_status='first_vertex_outside_ge')
    if distance == 0.:
        return dict(result, geometry_status='source_at_first_vertex', ge_path_start_mm=source.tolist(),
                    ge_path_to_first_mm=0.)
    incoming = delta/distance
    back_exit = float(photon.exit_distance_mm(crystal, first, -incoming))
    length = min(distance, back_exit)
    start = source if length == distance else first-length*incoming
    return dict(result, geometry_status='ge_path_computed', incoming_direction=incoming.tolist(),
                ge_path_start_mm=start.tolist(), ge_path_to_first_mm=length)


def first_compton_arrival(crystal, source_mm, first_mm, rates):
    """Return ln of the first-Compton density in mm^-3 per emitted photon.

    `rates` holds Ge inverse-mm coefficients at the selected incident energy.
    Pass None for an unavailable coefficient. The outgoing angular density is
    a separate conditional factor, along with downstream measurement terms.
    """
    path = incoming_ge_path(crystal,source_mm,first_mm)
    status = path['geometry_status']
    result = dict(path, density_status=status, log_isotropic_spreading_per_mm2=None,
                  ge_no_interaction_survival=None, ge_optical_depth=None,
                  total_rate_per_mm=None, integrated_compton_rate_per_mm=None,
                  log_first_compton_per_emitted_photon_mm3=None)
    if status != 'ge_path_computed':
        return result
    spreading = -math.log(4*math.pi)-2*math.log(path['source_to_vertex_mm'])
    result['log_isotropic_spreading_per_mm2'] = spreading
    if rates is None:
        return dict(result, density_status='incident_coefficients_unavailable')
    depth = rates.total_per_mm*path['ge_path_to_first_mm']
    log_density = (spreading-depth+math.log(rates.compton_per_mm)) if rates.compton_per_mm else None
    return dict(result, density_status='computed' if log_density is not None else 'zero_first_compton_rate',
                ge_no_interaction_survival=math.exp(-depth), ge_optical_depth=depth,
                total_rate_per_mm=rates.total_per_mm, integrated_compton_rate_per_mm=rates.compton_per_mm,
                log_first_compton_per_emitted_photon_mm3=log_density)


def forward_clipped_length(crystal, source, first):
    """Independent forward segment check for the saved-geometry acceptance."""
    normals, offsets = crystal
    p, r = np.array(source), np.array(first)
    start = 0.
    for normal, wall in zip(normals, offsets, strict=True):
        outside = float(normal @ p - wall)
        if outside > 0:
            start = max(start, outside/float(normal @ (p-r)))
    return (1-start)*math.dist(source, first)


def analyze(measured_path, plan_path, probe, extension, exact_path):
    started = time.perf_counter()
    measured,plan,basis,rates,crystal,_ = bank.setup(measured_path,plan_path,probe,extension)
    exact = W.read(exact_path)
    prior = exact['measured_response']
    W.require(prior['trial_plan_sha256']==basis['trial_plan_sha256'] and prior['selected_trials']==plan['selected_trials']
              and prior['measured_triggers']==measured['measured_triggers'] and prior['coefficient_basis']==basis['original_rate_basis']
              and prior['new_rates']==basis['new_rate_binding'] and W.digest(prior)==exact['measured_response_sha256_before_truth'],
              'Use the identical preselected trial points, saved candidates and initialized rate basis')
    old = {(b['original_trigger_id'],b['pair_index'],tuple(b['site_index_order']),b['incident_line_keV']):b
           for b in prior['branches']}
    find_rate, _ = bank.trial.rate_functions(rates)
    lines = {}
    for incident in measured['incident_lines_keV']:
        if min(rates) <= incident <= max(rates):
            lines[incident] = find_rate(incident)
        else:
            lines[incident] = None
    coverage = [dict(incident_keV=e, status=('initialized_coefficient' if e in rates else
                'log_interpolated_initialized_coefficients' if rate is not None else 'incident_coefficients_unavailable'),
                bracketing_initialized_keV=[max(x for x in rates if x<=e),min(x for x in rates if x>=e)] if rate is not None else None)
                for e,rate in lines.items()]
    rows, statuses, regions = [], Counter(), Counter()
    path_error = cosine_error = 0.
    distances, lengths, logs = [], [], []
    compared = 0
    for tid,pair,order,state,geometry_status in bank.trial.scoped_branches(measured,crystal):
        energy = state['incident_line_keV']
        identity = (tid,pair['pair_index'],tuple(order['site_index_order']),energy)
        reference = old.pop(identity)
        W.require(reference['geometry_status']==geometry_status, 'A retained pair/order geometry status changed')
        row = dict(original_trigger_id=tid,pair_index=pair['pair_index'],site_index_order=order['site_index_order'],
                   incident_keV=energy, geometry_status=geometry_status, trial_results=[])
        rows.append(row)
        if geometry_status!='available_geometry':
            statuses[geometry_status] += len(plan['selected_trials'])
            continue
        i,j = order['site_index_order']
        first,second = (pair['fitted_vertices_mm'][k] for k in (i,j))
        axis = (np.asarray(second)-first)/math.dist(first,second)
        row['first_fitted_mm'] = first
        for selected,old_result in zip(plan['selected_trials'],reference['trial_results'],strict=True):
            source = selected['source_mm']
            result = first_compton_arrival(crystal,source,first,lines[energy])
            W.require((result['source_region']!='outside_ge')==selected['inside_ge'], 'Saved Ge trial status changed')
            statuses[result['density_status']] += 1
            regions[result['source_region']] += 1
            row['trial_results'].append(result)
            if result['geometry_status']=='ge_path_computed':
                distances.append(result['source_to_vertex_mm'])
                length = result['ge_path_to_first_mm']
                lengths.append(length)
                path_error = max(path_error,abs(length-forward_clipped_length(crystal,source,first)))
                if old_result['status']=='conditional_factors_computed':
                    cosine = float(np.dot(result['incoming_direction'],axis))
                    cosine_error = max(cosine_error,abs(cosine-old_result['response']['first_scatter_cosine']))
                    compared += 1
            if result['log_first_compton_per_emitted_photon_mm3'] is not None:
                logs.append(result['log_first_compton_per_emitted_photon_mm3'])
    W.require(not old and path_error<1e-9 and cosine_error<1e-12, 'Saved input path or angular convention disagrees')

    def extent(values):
        return [min(values),max(values)] if values else None

    return dict(kind='gegi_saved_first_compton_arrival_v1', basis=basis, direct_trial_receipt_sha256=W.sha(exact_path),
                trial_points=plan['selected_trials'], measured_triggers=measured['measured_triggers'], branch_rows=rows,
                incident_coefficient_coverage=coverage, state_counts=dict(statuses), source_region_counts=dict(regions),
                source_distance_span_mm=extent(distances), ge_path_span_mm=extent(lengths), log_density_span=extent(logs),
                acceptance=dict(angular_comparisons=compared,maximum_cosine_difference=cosine_error,
                                maximum_forward_clip_difference_mm=path_error),
                scope=dict(geometry='Saved homogeneous active Ge. Isotropic monoenergetic point trial.',
                           outgoing_angular_density='Separate normalized conditional factor.',
                           passive_attenuation='Unmodeled.',source_activity='Unspecified.',
                           selected_acquisition_normalization='Unmodeled.'),
                source_sha256=bank.producers() | {Path(__file__).name:W.sha(__file__)}, software=bank.software(),
                elapsed_seconds=time.perf_counter()-started)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('measured-plan','plan','probe','new-rates','exact','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args = p.parse_args()
    W.require(not args.output.exists(),'Select a new arrival receipt path')
    result = analyze(args.measured_plan,args.plan,args.probe,args.new_rates,args.exact)
    with args.output.open('xb') as out:
        out.write(W.encoded(result)+b'\n')
    print(dict(states=result['state_counts'],acceptance=result['acceptance']))


if __name__=='__main__':
    main()
