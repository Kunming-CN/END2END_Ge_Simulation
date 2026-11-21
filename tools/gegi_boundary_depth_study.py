"""Refine only the depth axis of the measured-cell GeGI lateral response."""

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
from itertools import product
import json
import math
from pathlib import Path

import numpy as np
from scipy.interpolate import RegularGridInterpolator

import gegi_boundary_grid_cause as cause
import gegi_boundary_grid_study as grid


W = grid.workflow
J = grid.joint
DENSE_DEPTHS = tuple(J.DEPTH_MM.tolist())
COARSE_DEPTHS = tuple(J.LATERAL_DEPTH_MM)
FRESH = ((-.17,.31,-1.75),(.17,-.31,1.75))
CONTROL_ONSET_NS = 1000.


def retained(prior_request, prior_capture, comparison):
    scored, scored_sha = grid.boundary.read(comparison)
    request = grid.bound(prior_request,scored['input_sha256']['point_request'])
    points, seal_sha = grid.capture_points(prior_capture,request,scored['input_sha256']['point_request'])
    if seal_sha!=scored['input_sha256']['native_capture'] or request['measured_scope']!=scored['measured_scope']:
        raise ValueError('Use the exact original blind-grid capture and comparison')
    return scored, scored_sha, request, points, seal_sha


def point_request(original, old_points):
    cells = tuple(map(tuple,original['measured_scope']['cells']))
    geometry = {c['id']:c['strip_center_mm'] for c in original['channels']}
    pitch = geometry[2]-geometry[1]
    prior = {(tuple(p['contact_ids']),tuple(p['coordinates_pitch_pitch_mm'])):p
             for p in old_points if p['role']=='fit' and p['unit_analog'] is not None
             and p['collected_cell']==tuple(p['contact_ids'])}
    expected = {(cell,coord) for cell in cells for coord in grid.OFF_CENTER}
    if set(prior)!=expected:
        raise ValueError('The original 72 compatible noncenter responses must be retained')
    reused_xyz = {tuple(p['position_mm']) for p in old_points}
    points = []
    for cell in cells:
        required = [(x,y,z) for x,y,z in product(J.LATERAL_FRACTION,J.LATERAL_FRACTION,DENSE_DEPTHS)
                    if (x or y) and (cell,(x,y,z)) not in prior]
        for role, coords in (('fit',required), ('fresh_interior_holdout',FRESH)):
            for x,y,z in coords:
                pos = [geometry[cell[0]]+pitch*x,geometry[cell[1]]+pitch*y,z]
                if tuple(pos) in reused_xyz:
                    raise ValueError('A new template or independent control repeats a retained location')
                i = len(points)
                points.append({'contact_ids':list(cell),'role':role,'position_mm':pos,
                               'coordinates_pitch_pitch_mm':[x,y,z],'injection_id':i,'record_ref':f'records/point-{i:03}.json'})
                reused_xyz.add(tuple(pos))
    return points, list(prior.values())


def prepare(prior_request, prior_capture, comparison):
    scored, comparison_sha, original, old_points, seal_sha = retained(prior_request,prior_capture,comparison)
    points, fit = point_request(original,old_points)
    sources = original['source_file_sha256']
    if any(W.sha(W.ROOT/ref)!=digest for ref,digest in sources.items()):
        raise ValueError('Pinned native producer differs from the original capture')
    centers = original['reused_center_records']
    if (len(centers)!=33 or any(W.sha(W.ROOT/p['ref'])!=p['sha256'] for p in centers)):
        raise ValueError('Original center responses differ from the verified reference bank')
    return {**{key:original[key] for key in grid.BANK_KEYS},
            'kind':'gegi_declared_point_response_request_v1','source_file_sha256':sources,
            'plan_receipt':{'ref':comparison.resolve().relative_to(W.ROOT).as_posix(),'sha256':comparison_sha},
            'baseline_request':original['baseline_request'],
            'prior_point_request_sha256':scored['input_sha256']['point_request'],'prior_native_capture_sha256':seal_sha,
            'point_plan_sha256':hashlib.sha256(W.encoded(points)).hexdigest(),'points':points,
            'measured_scope':original['measured_scope'],'lateral_depth_axis_mm':DENSE_DEPTHS,
            'lateral_xy_axis_pitch_fraction':J.LATERAL_FRACTION,
            'reused_fit_records':[{'injection_id':p['injection_id'],'contact_ids':p['contact_ids'],'position_mm':p['position_mm'],
                                  'ref':(prior_capture/p['record_ref']).resolve().relative_to(W.ROOT).as_posix(),
                                  'sha256':p['record_sha256']} for p in fit],
            'reused_center_records':centers,'reused_off_center_records':[],
            'missing_by_role':dict(Counter(p['role'] for p in points)),
            'design_source_sha256':W.sha(__file__),
            'scope':'Same measured cells, center responses, XY support and native configuration. '
                    'Only new lateral depth knots and six independent predeclared validation points are captured.'}


def templates_on_depths(centers, coarse, calibration_points, depths):
    coords = tuple(product(J.LATERAL_FRACTION,J.LATERAL_FRACTION,depths))
    output, axes, coverage = {}, {}, []
    for cell,t in centers.items():
        samples = {tuple(p['coordinates_pitch_pitch_mm']):p['unit_analog']
                   for p in calibration_points if p['role']=='fit' and tuple(p['contact_ids'])==cell
                   and p['collected_cell']==cell and p['unit_analog'] is not None}
        missing = [xyz for xyz in coords if any(xyz[:2]) and xyz not in samples]
        if missing:
            output[cell], axes[cell] = coarse[cell], COARSE_DEPTHS
        else:
            center = dict(zip(J.DEPTH_MM,t.center_v_per_keV,strict=True))
            corrections = np.array([samples[x,y,z]-center[z] if x or y else np.zeros_like(center[z])
                                    for x,y,z in coords])
            output[cell] = replace(t,lateral_correction_v_per_keV=corrections.reshape(3,3,len(depths),*corrections.shape[1:]))
            axes[cell] = tuple(depths)
        coverage.append({'cell':cell,'applied_depth_axis_mm':axes[cell],
                         'missing_or_migrated_depth_grid_coords':missing})
    return output, axes, coverage


def make_predictor(templates, axes, cells, energies):
    """Use the established center response and change only lateral depth knots."""
    sites = [templates[cell] for cell in cells]
    centers = grid.boundary.centers_for(templates,cells)
    corrections = [RegularGridInterpolator((J.LATERAL_FRACTION,J.LATERAL_FRACTION,axes[cell]),
                                            t.lateral_correction_v_per_keV)
                   for cell,t in zip(cells,sites,strict=True)]

    def components(coords):
        return [e*(center([z])[0]+correction((x,y,z)))
                for e,center,correction,(x,y,z) in zip(energies,centers,corrections,coords,strict=True)]

    return components


def fit_depth_points(volts, templates, axes, cells, energies, center_seed):
    # Same lateral multistart grid, float bounds, quiet-tail and all-channel
    # objective as gegi_boundary_grid_study.fit_points; custom depth axes only.
    J._check_adc(volts)
    components = make_predictor(templates,axes,cells,energies)
    depths,onset = center_seed
    lo,_,hi = J.LATERAL_FRACTION
    z_bounds = (float(J.DEPTH_MM[0]),float(J.DEPTH_MM[-1]))
    limits = [(lo,hi),(lo,hi),z_bounds]*len(cells)+[J.SHIFT_LIMIT_NS]
    scale = np.array([.4,.4,5.]*len(cells)+[20.])
    observed = J.remove_quiet_tail(volts)

    def coordinates(point):
        return point[:-1].reshape(-1,3)

    def predict(point):
        return J.shifted_samples(sum(components(coordinates(point))),point[-1])

    def residual(point):
        return ((J.remove_quiet_tail(predict(point))-observed)/J.NOISE_RMS_V).ravel()

    slots = [[(x,y,z) for x,y in grid.START_OFFSETS] for z in depths]
    starts = [np.array([q for xyz in ps for q in xyz]+[onset]) for ps in product(*slots)]
    selected = sorted(starts,key=lambda p:np.linalg.norm(residual(p)))[:3]
    best, near, diagnostic = J._best_refinement(residual,selected,tuple(zip(*limits)),scale)

    def positions(point):
        return [[t.origin_mm[0]+x*t.pitch_mm,t.origin_mm[1]+y*t.pitch_mm,z]
                for t,(x,y,z) in zip((templates[c] for c in cells),coordinates(point),strict=True)]

    return {'status':'scored' if best.success else 'optimizer_unconverged',
            'positions_mm':positions(best.x),'onset_relative_to_trigger_ns':float(best.x[-1]),
            'parameters_at_bounds':[i for i,(x,(a,b)) in enumerate(zip(best.x,limits,strict=True))
                                    if min(x-a,b-x)<=J.BOUNDARY_TOLERANCE],
            'sampled_near_ties_mm':[positions(p.x) for p in near if p is not best], 'optimizer':diagnostic,
            **grid.boundary.rms(volts,predict(best.x))}


def measured_inputs(scored, request, capture_points, acquisition, archive, center):
    hashes = scored['input_sha256']
    report = grid.bound(acquisition,hashes['acquisition'])
    meta,loaded,_,center_sha = grid.calibration.load(center)
    if W.sha(archive)!=hashes['candidate_store'] or center_sha!=hashes['center_calibration'] or meta['channels']!=request['channels']:
        raise ValueError('The original ADC or center calibration differs from the blind-grid comparison')
    cells = tuple(map(tuple,request['measured_scope']['cells']))
    centers = {c:loaded[c] for c in cells}
    coarse, coverage = grid.lateral_templates(centers,capture_points)
    if not all(item['available'] for item in coverage):
        raise ValueError('All original coarse grids are required for a matched comparison')
    record = grid.storage.load_candidate(archive,request['measured_scope']['trigger_id'])
    context = record['context']
    volts,status = grid.imaging.voltage_window(record,report['excluded_intervals_ns'])
    if status!='captured' or hashlib.sha256(context['adc_codes'].tobytes()).hexdigest()!=hashes['original_adc']:
        raise ValueError('The ADC window differs from the saved comparison')
    return centers, coarse, volts, context['adc_phase_ns']


def existing_controls(scored, old_points):
    held = {p['injection_id']:p for p in old_points if p['role']!='fit'}
    for category in ('independent_single_pulse_controls','independent_overlap_controls'):
        for i,row in enumerate(scored[category]):
            refs = row['held_out_positions_for_scoring']
            points = [held[p['injection_id']] for p in refs]
            if any(p['role']!=ref['role'] or p['position_mm']!=ref['position_mm'] for p,ref in zip(points,refs,strict=True)):
                raise ValueError('A retained control coordinate changed')
            yield category, i, row, points


def control_adc(saved, points, phase, request):
    meta,card,volts = grid.controlled_adc(points,saved['input_energies_keV'],request['channels'],phase,
                                           request['injection_energy_keV'],saved['noise_seed'])
    if card is None or volts is None or meta['adc_sha256']!=saved['adc_sha256']:
        raise ValueError('A control ADC clock or digest changed')
    return card,volts


def compare_fit(actual, prior):
    keys = ('positions_mm','sampled_near_ties_mm','onset_relative_to_trigger_ns','all34_adc_rms_codes',
            'y28_adc_rms_codes','per_contact_adc_rms_codes')
    if (actual['status']!=prior['status'] or actual['parameters_at_bounds']!=prior['parameters_at_bounds']
            or any(not np.allclose(actual[k],prior[k],rtol=0.,atol=1e-9) for k in keys)):
        raise ValueError('Custom-axis fitter does not reproduce the original coarse fit')
    return max((float(np.max(np.abs(np.asarray(actual[k])-np.asarray(prior[k])))) for k in keys
                if np.asarray(prior[k]).size),default=0.)


def verify_coarse(scored, request, old_points, coarse, volts, phase):
    cells = tuple(map(tuple,request['measured_scope']['cells']))
    axes = dict.fromkeys(cells,COARSE_DEPTHS)
    center = scored['original_adc']['center']['saved_fit']
    e = center['site_energies_keV']
    seed = ([xyz[2] for xyz in center['site_positions_mm']],center['onset_relative_to_trigger_ns'])
    diffs = [compare_fit(fit_depth_points(volts,coarse,axes,cells,e,seed),scored['original_adc']['within_cell_fit'])]
    for _,_,row,held in existing_controls(scored,old_points):
        if row['status']!='evaluated' or row['lateral'] is None:
            continue
        _,window = control_adc(row,held,phase,request)
        measured = tuple(map(tuple,row['measured_cells']))
        best = fit_depth_points(window,coarse,axes,measured,row['measured_energies_keV'],cause.fit_start(row['center']))
        diffs.append(compare_fit(best,row['lateral']))
    return {'compare_count':len(diffs),'maximum_absolute_serialized_numeric_delta':max(diffs)}


def waveform_error(points, cells, templates, axes, energies, shift, reference):
    """Score template waveform accuracy at independently known control locations."""
    by_cell = {p['collected_cell']:(p,e) for p,e in zip(points,energies,strict=True)}
    if len(by_cell)!=len(points) or set(cells)!=set(by_cell):
        return {'status':'no_unique_cell_correspondence'}
    tau = J.SAMPLE_NS-shift
    ordered = [by_cell[cell] for cell in cells]
    lo,_,hi = J.LATERAL_FRACTION
    coords, native = [], []
    within = []
    for cell,(point,e) in zip(cells,ordered,strict=True):
        t = templates[cell]
        x,y,z = point['position_mm']
        xy = np.array([(x-t.origin_mm[0])/t.pitch_mm,(y-t.origin_mm[1])/t.pitch_mm])
        support = bool(np.all((lo<=xy)&(xy<=hi)))
        within.append(support)
        coords.append((*np.clip(xy,lo,hi),z))
        native.append(e/reference*J.pulse._sample_pulse(point['native'],np.maximum(tau,0.))*(tau>=0.))
    predict = make_predictor(templates,axes,cells,[e for _,e in ordered])
    model = [cause.response(tau,analog) for analog in predict(coords)]
    return {'status':'at_known_position' if all(within) else 'outside_xy_domain_at_nearest_face',
            'component_inside_xy_support':within,
            'all34_native_rms_codes':grid.boundary.rms(sum(native),sum(model))['all34_adc_rms_codes']}


def compare_control(old, points, phase, request, coarse, templates, axes):
    if old['status']!='evaluated' or old['lateral'] is None:
        return {'coarse':old,'refined':None,'status':'no_matched_control_fit'}
    card,volts = control_adc(old,points,phase,request)
    cells = tuple(map(tuple,old['measured_cells']))
    refined = fit_depth_points(volts,templates,axes,cells,old['measured_energies_keV'],cause.fit_start(old['center']))
    truth = {p['collected_cell']:p['position_mm'] for p in points}
    if refined['status']=='scored' and len(truth)==len(points) and set(truth)==set(cells):
        refined['position_errors_mm'] = [math.dist(p,truth[c]) for p,c in zip(refined['positions_mm'],cells,strict=True)]
    delta = CONTROL_ONSET_NS-card['trigger_time_ns']
    energy = old['input_energies_keV']
    reference = request['injection_energy_keV']
    return {'status':'paired_adc','coarse':old,'refined':refined,
            'waveforms_at_known_control_positions':{
                'coarse':waveform_error(points,cells,coarse,dict.fromkeys(cells,COARSE_DEPTHS),energy,delta,reference),
                'refined':waveform_error(points,cells,templates,axes,energy,delta,reference)}}


def score(scored_path, prior_request, prior_capture, acquisition, archive, center, request_path, capture):
    scored, original_sha, original, old_points, prior_seal = retained(prior_request,prior_capture,scored_path)
    request, request_sha = grid.boundary.read(request_path)
    expected,fit = point_request(original,old_points)
    if (request['plan_receipt']['sha256']!=original_sha or request['prior_native_capture_sha256']!=prior_seal
            or any(request[k]!=original[k] for k in grid.BANK_KEYS)
            or request['points']!=expected or tuple(request['lateral_depth_axis_mm'])!=DENSE_DEPTHS
            or request['point_plan_sha256']!=hashlib.sha256(W.encoded(expected)).hexdigest()
            or len(fit)!=len(request['reused_fit_records'])):
        raise ValueError('The signed depth-only design differs from the frozen prior capture')
    for point,reused in zip(fit,request['reused_fit_records'],strict=True):
        if (point['record_sha256']!=reused['sha256'] or point['position_mm']!=reused['position_mm']
                or point['contact_ids']!=reused['contact_ids'] or point['injection_id']!=reused['injection_id']):
            raise ValueError('Retained fit-point identity changed')
    new_points, seal_sha = grid.capture_points(capture,request,request_sha)
    centers,coarse,volts,phase = measured_inputs(scored,request,old_points,acquisition,archive,center)
    parity = verify_coarse(scored,original,old_points,coarse,volts,phase)
    templates,axes,coverage = templates_on_depths(centers,coarse,[*fit,*new_points],DENSE_DEPTHS)
    cells = tuple(map(tuple,request['measured_scope']['cells']))
    old_center = scored['original_adc']['center']['saved_fit']
    seed = ([p[2] for p in old_center['site_positions_mm']],old_center['onset_relative_to_trigger_ns'])
    refined = fit_depth_points(volts,templates,axes,cells,old_center['site_energies_keV'],seed)
    old = [{'control_set':category,'control_index':i,**compare_control(row,points,phase,original,coarse,templates,axes)}
           for category,i,row,points in existing_controls(scored,old_points)]
    fresh = []
    for p in new_points:
        if p['role']=='fresh_interior_holdout':
            independent = grid.score_holdout([p],[request['injection_energy_keV']],coarse,phase,request,20261190+p['injection_id'])
            fresh.append({'injection_id':p['injection_id'],**compare_control(independent,[p],phase,request,coarse,templates,axes)})
    return {'kind':'gegi_boundary_depth_refinement_v1','measured_scope':request['measured_scope'],
            'input_sha256':{**scored['input_sha256'],'prior_comparison':original_sha,
                            'depth_point_request':request_sha,'depth_native_capture':seal_sha},
            'source_sha256':{Path(file).name:W.sha(file) for file in (__file__,grid.__file__,J.__file__,cause.__file__)},
            'coarse_fitter_parity':parity,'calibration_support':coverage,
            'native_outcomes':[{'injection_id':p['injection_id'],'role':p['role'],'position_mm':p['position_mm'],
                                'status':p['native_status'],'terminal_cell':p['collected_cell'],
                                'terminal_endpoints':p['terminal_endpoints'],'sha256':p['record_sha256']} for p in new_points],
            'capture_counts':{'new_points':len(new_points),'reused_fit_points':len(fit),
                              'reused_center_points':len(request['reused_center_records'])},
            'original_adc':{'coarse':scored['original_adc'],'refined_lateral_fit':refined},
            'existing_development_controls':old,'independent_fresh_interior_controls':fresh,
            'interpretation':'Change only the depth axis of the lateral correction. Unavailable dense grids keep original coarse support. '
                             'Previously used holdouts are development controls; fresh controls are local validation. '
                             'Near-gap coordinates remain outside XY support. Original image weights are preserved.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    prepare_args = sub.add_parser('prepare',help='Write only the missing-point request')
    parity_args = sub.add_parser('verify-coarse',help='Reproduce all original three-depth fits on saved ADC')
    score_args = sub.add_parser('score',help='Compare the exact captured depth refinement')
    for command in (prepare_args,parity_args,score_args):
        for name in ('comparison','prior-request','prior-capture'):
            command.add_argument('--'+name,type=Path,required=True)
    for command in (parity_args,score_args):
        for name in ('acquisition','center-calibration'):
            command.add_argument('--'+name,type=Path,required=True)
        command.add_argument('--archive',type=Path)
    for command in (prepare_args,score_args):
        command.add_argument('--output',type=Path,required=True)
    for name in ('request','capture'):
        score_args.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if hasattr(args,'output') and args.output.exists():
        parser.error('Choose a new JSON output')
    if args.command=='prepare':
        value = prepare(args.prior_request,args.prior_capture,args.comparison)
    else:
        archive = args.archive or args.acquisition.parent/grid.storage.ARCHIVE_NAME
        if args.command=='verify-coarse':
            old,_,req,points,_ = retained(args.prior_request,args.prior_capture,args.comparison)
            _,coarse,volts,phase = measured_inputs(old,req,points,args.acquisition,archive,args.center_calibration)
            print(json.dumps(verify_coarse(old,req,points,coarse,volts,phase)))
            return
        value = score(args.comparison,args.prior_request,args.prior_capture,args.acquisition,archive,
                      args.center_calibration,args.request,args.capture)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(value)+b'\n')
    print(json.dumps({'sha256':W.sha(args.output),'missing_by_role':value.get('missing_by_role')}))


if __name__=='__main__':
    main()
