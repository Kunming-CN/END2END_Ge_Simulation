"""Diagnose interpolation, energies, and sampled fit basins on sealed GeGI controls."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

import gegi_boundary_grid_study as grid


W = grid.workflow
J = grid.joint
CONTROL_ONSET_NS = 1000.


def fit_start(center):
    return ([p[2] for p in center['positions_mm']], center['onset_relative_to_trigger_ns'])


def response(times, analog):
    """Sample the existing one-nanosecond template grid with no extrapolation."""
    if max(times) >= analog.shape[1]-1:
        raise ValueError('Control sampling exceeds the bound template time support')
    return np.stack([np.interp(times,J.VOLTAGE_NS,trace,left=0.) for trace in analog])


def predictors(templates, cells, use_lateral=True):
    sites = [templates[cell] for cell in cells]
    support = tuple(use_lateral and t.lateral_correction_v_per_keV is not None for t in sites)
    models = J._interpolators(sites,slice(None),support)

    def component(i, position, energy, offset):
        x,y,z = position
        t = sites[i]
        center,lateral = models[i]
        xy = [(value-origin)/t.pitch_mm for value,origin in zip((x,y),t.origin_mm,strict=True)]
        lo,_,hi = J.LATERAL_FRACTION
        if lateral is not None and any(value<lo-1e-12 or value>hi+1e-12 for value in xy):
            raise ValueError('Geometry lies outside the supported lateral template')
        coords = (*np.clip(xy,lo,hi),z)
        analog = center([z])[0]+(lateral(coords) if lateral is not None else 0.)
        return response(J.SAMPLE_NS-offset,energy*analog)

    return component


def truth_waveforms(points, cells, templates, truth, energies, shift, reference_energy, observed):
    tau = J.SAMPLE_NS-shift
    true_wave = [energy/reference_energy*J.pulse._sample_pulse(p['native'], np.maximum(tau,0.))*(tau>=0.)
                 for p,energy in zip(points,energies,strict=True)]
    analog = sum(true_wave)
    _,noiseless_codes_volts = J.digital._digitize(analog)
    center = predictors(templates,cells,False)
    lateral = predictors(templates,cells)
    center_wave, lateral_wave, comparisons = [], [], []
    lo,_,hi = J.LATERAL_FRACTION
    for i,(cell,position,e,native) in enumerate(zip(cells,truth,energies,true_wave,strict=True)):
        t = templates[cell]
        host = [*t.origin_mm,position[2]]
        baseline = center(i,host,e,shift)
        bounded = [float(np.clip(value,c+lo*t.pitch_mm,c+hi*t.pitch_mm))
                   for value,c in zip(position[:2],t.origin_mm,strict=True)] + [position[2]]
        supported = t.lateral_correction_v_per_keV is not None
        inside = supported and bounded==position
        # Clamp only this diagnostic evaluation, preserving the outside-domain status.
        trial = lateral(i,bounded,e,shift) if supported else baseline
        comparisons.append({'cell':cell,'native_input_position_mm':position,
                            'center_at_true_depth_vs_native':grid.boundary.rms(native,baseline),
                            'lateral_truth_status':('at_known_position' if inside else
                                'outside_grid_evaluated_at_nearest_face' if supported else 'grid_unavailable'),
                            'evaluated_lateral_proxy_position_mm':bounded if supported else None,
                            'lateral_at_evaluated_position_vs_native':grid.boundary.rms(native,trial) if supported else None})
        center_wave.append(baseline)
        lateral_wave.append(trial)
    summed_lateral = sum(lateral_wave)
    return {'true_onset_relative_to_trigger_ns':shift,
            'comparison_at_known_positions':comparisons,
            'center_at_known_depth_sum_vs_native':grid.boundary.rms(analog,sum(center_wave)),
            'lateral_at_evaluated_coordinates_sum_vs_native':grid.boundary.rms(analog,summed_lateral),
            'lateral_at_evaluated_coordinates_sum_vs_noisy_adc':grid.boundary.rms(observed,summed_lateral),
            'noiseless_quantization_vs_native':grid.boundary.rms(analog,noiseless_codes_volts),
            'noisy_vs_noiseless_quantized_on_identical_clock':grid.boundary.rms(noiseless_codes_volts,observed)}, noiseless_codes_volts


def knot_diagnostic(fit, observed, templates, cells, energies, truth):
    coordinates = fit['positions_mm']
    onset = fit['onset_relative_to_trigger_ns']
    model = predictors(templates,cells)

    def objective(index,axis,value):
        requested = [list(p) for p in coordinates]
        requested[index][axis] = value
        predicted = sum(model(i,p,e,onset) for i,(p,e) in enumerate(zip(requested,energies,strict=True)))
        return grid.boundary.rms(observed,predicted)['all34_adc_rms_codes']

    rows = []
    for i,cell in enumerate(cells):
        template = templates[cell]
        steps = [0.01*template.pitch_mm,0.01*template.pitch_mm,0.05]
        nearest_z = min(J.DEPTH_MM[1:-1],key=lambda v:abs(v-coordinates[i][2]))
        for axis,(knot,step) in enumerate(zip((*template.origin_mm,float(nearest_z)),steps,strict=True)):
            rows.append({'cell':cell,'axis':'xyz'[axis],'nearest_internal_knot_mm':knot,
                         'fitted_minus_knot_mm':coordinates[i][axis]-knot,
                         'known_minus_knot_mm':truth[i][axis]-knot,
                         'conditional_probe_delta_mm':step,
                         'all34_adc_rms_codes_at_minus_knot_plus':
                            [objective(i,axis,where) for where in (knot-step,knot,knot+step)]})
    return rows


def fitted_control_error(fit, truth):
    if fit is not None and fit['status']=='scored':
        return [math.dist(a,b) for a,b in zip(fit['positions_mm'],truth,strict=True)]
    return None


def trial(prior, points, templates, request, phase, *, counterfactual):
    label = [p['injection_id'] for p in points]
    if any(p['role']=='fit' for p in points):
        raise ValueError('A saved control references a template point')
    if prior['status']!='evaluated' or any(p['native'] is None for p in points):
        return {'injection_ids':label,'prior_status':prior['status'],'status':'original_control_not_evaluable'}
    input_energies = prior['input_energies_keV']
    reference = request['injection_energy_keV']
    info,card,observed = grid.controlled_adc(points,input_energies,request['channels'],phase,reference,prior['noise_seed'])
    if card is None or observed is None or info['adc_sha256']!=prior['adc_sha256']:
        raise ValueError('The seeded held-out ADC control did not reproduce')
    cells = tuple(map(tuple,prior['measured_cells']))
    measured = prior['measured_energies_keV']
    by_cell = {p['collected_cell']:(p,e) for p,e in zip(points,input_energies,strict=True)}
    if len(by_cell)!=len(points) or set(by_cell)!=set(cells):
        return {'injection_ids':label,'prior_status':prior['status'],'status':'no_unique_control_cell_association'}
    ordered, energies = map(list,zip(*(by_cell[c] for c in cells),strict=True))
    actual = [p['position_mm'] for p in ordered]
    shift = CONTROL_ONSET_NS-card['trigger_time_ns']
    truth, noiseless = truth_waveforms(ordered,cells,templates,actual,energies,shift,reference,observed)
    old_center,old_lateral = prior['center'],prior['lateral']
    seeds = fit_start(old_center)
    exact_center = grid.fit_points(observed,templates,cells,energies,use_lateral=False)
    exact_lateral = grid.fit_points(observed,templates,cells,energies,use_lateral=True,center_seed=seeds)
    ties = old_lateral['sampled_near_ties_mm']
    reported = {'injection_ids':label,'roles':[p['role'] for p in points],'status':'evaluated','cells':cells,**info,
                'original_trigger_time_ns':card['trigger_time_ns'],'known_positions_mm_for_scoring':actual,
                'measured_energies_keV':measured,'configured_input_energies_keV':energies,
                'measured_minus_configured_energies_keV':[m-e for m,e in zip(measured,energies,strict=True)],
                'waveform_diagnostics':truth,
                'original_measured_energy_results':{'center':old_center,'lateral':old_lateral},
                'exact_energy_same_noisy_adc':{'center':exact_center,'lateral':exact_lateral,
                    'center_position_errors_mm':fitted_control_error(exact_center,actual),
                    'lateral_position_errors_mm':fitted_control_error(exact_lateral,actual),
                    'lateral_position_shift_vs_original_mm':[math.dist(a,b) for a,b in
                        zip(exact_lateral['positions_mm'],old_lateral['positions_mm'],strict=True)]},
                'original_sampled_near_tie_max_displacement_mm_by_cell':
                    [max((math.dist(fit,tie[i]) for tie in ties),default=0.) for i,fit in enumerate(old_lateral['positions_mm'])],
                'internal_knot_checks':knot_diagnostic(old_lateral,observed,templates,cells,measured,actual)}
    if counterfactual:
        without_noise = grid.fit_points(noiseless,templates,cells,energies,use_lateral=True,center_seed=seeds)
        reported['noiseless_quantized_same_clock_and_exact_energy'] = {
            'fit':without_noise,'position_errors_mm':fitted_control_error(without_noise,actual),
            'position_shift_vs_noisy_exact_energy_mm':[math.dist(a,b) for a,b in
                zip(without_noise['positions_mm'],exact_lateral['positions_mm'],strict=True)]}
    return reported


def run(comparison_path, request_path, capture, center, archive):
    original, original_sha = grid.boundary.read(comparison_path)
    hashes = original['input_sha256']
    request = grid.bound(request_path,hashes['point_request'])
    points, seal_sha = grid.capture_points(capture,request,hashes['point_request'])
    m, centers, _, center_sha = grid.calibration.load(center)
    if (seal_sha!=hashes['native_capture'] or center_sha!=hashes['center_calibration']
            or m['channels']!=request['channels'] or W.sha(archive)!=hashes['candidate_store']):
        raise ValueError('Use the exact capture, center calibration and archive in the scored study')
    trigger = grid.storage.load_candidate(archive,original['measured_scope']['trigger_id'])
    context = trigger['context']
    if hashlib.sha256(context['adc_codes'].tobytes()).hexdigest()!=hashes['original_adc']:
        raise ValueError('The original ADC clock and trigger no longer match the scored study')
    cells = tuple(map(tuple,request['measured_scope']['cells']))
    templates,coverage = grid.lateral_templates({c:centers[c] for c in cells},points)
    if not all(d['available'] for d in coverage):
        raise ValueError('The original study used three fully supported local grids')
    held = {p['injection_id']:p for p in points if p['role']!='fit'}
    results=[]
    for kind in ('independent_single_pulse_controls','independent_overlap_controls'):
        controls = original[kind]
        for i, saved in enumerate(controls):
            refs = saved['held_out_positions_for_scoring']
            native = [held[p['injection_id']] for p in refs]
            if any(p['role']!=r['role'] or p['position_mm']!=r['position_mm'] for p,r in zip(native,refs,strict=True)):
                raise ValueError('The held-out positions changed')
            results.append({'original_control_set':kind,'control_index':i,
                            **trial(saved,native,templates,request,context['adc_phase_ns'],
                                    counterfactual=kind=='independent_overlap_controls' and i==1)})
    return {'kind':'gegi_boundary_grid_cause_diagnostic_v1','input_sha256':hashes | {'original_comparison':original_sha},
            'source_sha256':{Path(p).name:W.sha(p) for p in (__file__,grid.__file__,J.__file__)},
            'scope':original['measured_scope'],
            'definition':[
                'Use the same per-control noise seed, ADC clock, and measured trigger; verify the ADC hash before scoring.',
                'Direct waveform comparisons use captured holdouts at their known coordinates and onset only for diagnostics. An outside-grid position is scored at the nearest supported face, without extrapolation.',
                'Energy-only substitutions fit the same noisy ADC with configured input energies. Lateral multistart uses the original measured-energy center-fit depths and onset.',
                'For the second overlap control only, quantize the same native waveform without noise on the original triggered clock and refit at exact energies.',
                'Knot probes perturb one coordinate of a measured-energy optimum and hold all other fitted coordinates, onset and energies fixed. Samples characterize local shape, with no acceptance cut.'
            ],'controls':results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for option in ('comparison','request','capture','center-calibration','archive','output'):
        p.add_argument('--'+option,type=Path,required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('Choose a new diagnostic JSON file')
    result = run(args.comparison,args.request,args.capture,args.center_calibration,args.archive)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(json.dumps({'controls':len(result['controls']),'sha256':W.sha(args.output)}))


if __name__=='__main__':
    main()
