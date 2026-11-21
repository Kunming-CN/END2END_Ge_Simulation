"""Reproduce GeGI trigger 12271's three-cell ADC boundary-response comparison."""

import argparse
from collections import defaultdict
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path

import numpy as np


import gegi_candidate_imaging as imaging
import gegi_candidate_storage as storage
import gegi_dual_source as dual
from gegi_exposure_stream import ADCExposure, reconstruct_exposure
import gegi_joint_calibration as calibration
import gegi_joint_two_site as joint
import gegi_pulse_stream as pulse
import scenario_workflow as workflow


TID = 12271
CONTACTS = joint.digital.CONTACT_IDS
Y28 = CONTACTS.index(28)
CELLS = ((2, 27), (3, 27), (3, 28))


def read(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def rms(observed, predicted):
    delta = (joint.remove_quiet_tail(predicted)-joint.remove_quiet_tail(observed))/joint.digital._LSB_V
    per_contact = np.sqrt(np.mean(delta**2, axis=1))
    y_raw = (predicted[Y28]-observed[Y28])/joint.digital._LSB_V
    return {'all34_adc_rms_codes': float(np.sqrt(np.mean(per_contact**2))),
            'y28_adc_rms_codes': float(per_contact[Y28]), 'per_contact_adc_rms_codes': per_contact.tolist(),
            'y28_before_quiet_tail_removal_rms_codes':float(np.sqrt(np.mean(y_raw**2)))}


def centers_for(templates, cells):
    return [center for center, _ in joint._interpolators([templates[cell] for cell in cells],
                                                         slice(None), (False,)*len(cells))]


def fit_voltage(observed, constant, *, center=None, center_energy=None):
    """Fit the same common onset and, for a center component, one supported depth."""
    joint._check_adc(observed)
    observed_tail_removed = joint.remove_quiet_tail(observed)
    left, right = joint.SHIFT_LIMIT_NS
    if center is None:
        bounds = ([left], [right])
        starts = [(-15.,), (5.,)]
        scales = np.asarray([20.])
    else:
        bounds = ([joint.DEPTH_MM[0], left], [joint.DEPTH_MM[-1], right])
        starts = [(z, t) for z in (-4., 0., 4.) for t in (-15., 5.)]
        scales = np.asarray([5., 20.])

    def predict(params):
        analog = constant if center is None else constant+center_energy*center([params[0]])[0]
        return joint.shifted_samples(analog, params[-1])

    def resid(params):
        return ((joint.remove_quiet_tail(predict(params))-observed_tail_removed)/joint.NOISE_RMS_V).ravel()

    selected = sorted(starts, key=lambda point: np.linalg.norm(resid(point)))[:3]
    result, _, diagnostic = joint._best_refinement(resid, selected, bounds, scales)
    return {'status': 'scored' if result.success else 'optimizer_unconverged',
            'onset_relative_to_trigger_ns': float(result.x[-1]),
            'fitted_center_depth_mm': float(result.x[0]) if center is not None else None,
            'optimizer': diagnostic, **rms(observed, predict(result.x))}


def native_point(payload, channels):
    endpoints = payload.get('endpoints') or []
    summary = [{k: endpoint.get(k) for k in ('species','status','step_limit_reached','contact_ids','position_mm','samples')}
               for endpoint in endpoints]
    complete = len(endpoints)==2 and all(e['status']=='contact' and e['step_limit_reached'] is False
                                          and e.get('contact_ids') for e in endpoints)
    status = payload['status']
    collected_cell = None
    if complete and all(len(e['contact_ids'])==1 for e in endpoints):
        ids = sorted(e['contact_ids'][0] for e in endpoints)
        by_id = {channel['id']:channel for channel in channels}
        if [by_id[c]['family'] for c in ids]==['X','Y'] and all(not by_id[c]['guard'] for c in ids):
            collected_cell = tuple(ids)
    nominal = tuple(payload['contact_ids']) if payload.get('contact_ids') else None
    if not complete:
        endpoint_class = 'terminal_unverified'
    elif collected_cell is None:
        endpoint_class = 'ambiguous_or_guard_endpoint'
    else:
        endpoint_class = 'nominal_cell' if nominal==collected_cell else 'other_complete_terminal_cell'
    # Migrating to the actual adjacent strip is supported, even if it differs from
    # a geometrically assigned strip. Incomplete or ambiguous endpoints stay unknown.
    provenance = {'native_status':status,'native_producer_valid':payload.get('valid'),
                  'native_nominal_cell':nominal,'terminal_collection_class':endpoint_class,
                  'complete_terminal_collection':complete,'terminal_endpoints':summary,'collected_cell':collected_cell}
    if collected_cell is None:
        return provenance | {'native':None,'unit_analog':None}
    traces = {row['contact_id']: row for row in payload['channel_signals']}
    native = pulse.prepare_native(traces,channels,terminal_complete=True)
    finals = {str(cid):pulse._WIRING[cid]*traces[cid]['signed_induced_keV'][-1] for cid in (2,3,27,28)}
    return provenance | {'native':native,'terminal_wired_charge_in_original_collectors_keV_equivalent':finals,
                         'unit_analog':pulse._sample_pulse(native,joint.VOLTAGE_NS)/payload['injection_energy_keV']}


def compare_event(observed, templates, points, baseline):
    candidates = baseline['hypotheses']
    saved, = [a for a in candidates if a['kind']=='3_corner_sparse'
              and tuple(map(tuple,a['cells']))==CELLS]
    z_profiles = centers_for(templates,CELLS)
    fitted = saved['fit']
    e_first,e_left,e_right = fitted['site_energies_keV']
    original_analog = sum(e*center([coords[2]])[0] for e,center,coords in
                          zip(fitted['site_energies_keV'],z_profiles,fitted['site_positions_mm'],strict=True))
    original_prediction = joint.shifted_samples(original_analog,fitted['onset_relative_to_trigger_ns'])
    baseline_rms = rms(observed,original_prediction)
    if not np.allclose(baseline_rms['per_contact_adc_rms_codes'],saved['per_contact_adc_rms_codes'],rtol=0.,atol=1e-9):
        raise ValueError('The saved 12271 three-center fit does not reproduce on its original ADC codes')
    training = defaultdict(list)
    for point in points:
        if point['unit_analog'] is not None and point['role'] in ('gap_sweep','first_vertex_response_anchor'):
            training[(point['role'], point['collected_cell'])].append(point)
    models = []
    for first in [None, *training[('first_vertex_response_anchor',CELLS[0])]]:
        for left in training[('gap_sweep',CELLS[1])]:
            for right in training[('gap_sweep',CELLS[2])]:
                total = e_left*left['unit_analog']+e_right*right['unit_analog']
                if first is None:
                    result = fit_voltage(observed,total,center=z_profiles[0],center_energy=e_first)
                else:
                    result = fit_voltage(observed,total+e_first*first['unit_analog'])
                models.append({'first_component': 'z_fit_at_cell_center' if first is None else first['point_index'],
                               'left_and_right_training_point_indices':[left['point_index'],right['point_index']],
                               'energy_allocation_keV':[e_first,e_left,e_right],**result})
    best = min((row for row in models if row['status']=='scored'),key=lambda row:row['all34_adc_rms_codes'],default=None)
    return {'unchanged_measured_cell_energy_allocation_keV':fitted['site_energies_keV'],
            'baseline_center_three_cell':baseline_rms | {'saved_fit':fitted},
            'model_status':'evaluated' if models else 'no_training_point_for_one_or_both_gap_collection_sides',
            'training_support_by_terminal_cell':[{'role':role,'cell':cell,'point_indices':[p['point_index'] for p in values]}
                                                 for (role,cell),values in training.items()],
            'sampled_models':models,'best_sampled_all34_model_index':models.index(best) if best is not None else None}


def holdout_replay(point, templates, training, channels, phase, reference_energy):
    if point['native'] is None:
        return {'status':'unusable_or_ambiguous_native_endpoint'}
    seed = 20261121+point['point_index']
    exposure = ADCExposure([(point['native'],1000.,1.)],live_time_ns=4000.,phase_ns=phase,noise_seed=seed)
    contexts = []

    def capture(event, context):
        contexts.append((event,dict(context,adc_codes=context['adc_codes'].copy())))

    replay = reconstruct_exposure(exposure,on_readout_context=capture)
    meta = {'noise_seed':seed,'adc_phase_ns':phase,'adc_sha256':replay['adc_sha256'],
            'readout_trigger_count':len(replay['events'])}
    if len(replay['events'])!=1 or len(contexts)!=1:
        return meta | {'status':'no_unique_synthetic_adc_trigger'}
    event, context = contexts[0]
    observed, status = imaging.voltage_window({'trigger_time_ns':event['trigger_time_ns'],'context':context},[])
    card = dual._trigger_card(event,dual._strip_neighbors(channels),geometry=channels)
    xs,ys = card['x_collecting_strips'],card['y_collecting_strips']
    measured = (xs[0],ys[0]) if len(xs)==len(ys)==1 and not card['guard_contact_ids'] else None
    energy = card['energy_keV']
    meta.update(measured_cell=measured,native_reference_energy_keV=reference_energy,measured_energy_keV=energy,adc_window_status=status)
    if observed is None or energy is None or measured not in templates:
        return meta | {'status':'no_qualified_measured_single_site'}
    center, = centers_for(templates,[measured])
    fit_center = fit_voltage(observed,np.zeros_like(point['unit_analog']),center=center,center_energy=energy)
    if fit_center['status']=='scored':
        position = [*templates[measured].origin_mm,fit_center['fitted_center_depth_mm']]
        fit_center.update(position_mm=position)
    alternatives=[]
    for p in training:
        if p['collected_cell']==measured:
            result = fit_voltage(observed,energy*p['unit_analog'])
            alternatives.append({'point_index':p['point_index'],'position_mm':p['position_mm'],**result})
    best = min((row for row in alternatives if row['status']=='scored'),key=lambda row:row['all34_adc_rms_codes'],default=None)
    for estimate in (fit_center, best):
        if estimate is not None and estimate['status']=='scored':
            pos = estimate['position_mm']
            estimate.update(position_error_xyz_mm=[a-b for a,b in zip(pos,point['position_mm'],strict=True)],
                            position_error_mm=math.dist(pos,point['position_mm']))
    return meta | {'status':'scored' if best is not None else 'no_successful_boundary_template_for_measured_cell',
                   'center':fit_center,'off_center_alternatives':alternatives,
                   'best_off_center_training_point_index':best['point_index'] if best is not None else None}


def load_points(capture_path, plan, plan_sha, channels):
    capture, capture_sha = read(capture_path)
    request, request_sha = read(capture_path.with_name('request.json'))
    identity, identity_sha = read(capture_path.with_name('identity.json'))
    geometry = plan['positions']
    if (capture['status']!='completed_declared_points' or capture['request_sha256']!=request_sha
            or capture['identity_sha256']!=identity_sha or identity['request_sha256']!=request_sha
            or request['plan_receipt']['sha256']!=plan_sha
            or not capture['plan_receipt']==identity['plan_receipt']==request['plan_receipt']
            or not capture['point_plan_sha256']==identity['point_plan_sha256']==request['point_plan_sha256']
            or request['model_sha256']!=plan['model_sha256']
            or request['field_cache']['sha256']!=plan['field_cache_sha256']
            or request['field_precision_bits']!=plan['field_precision_bits']
            or request['injection_energy_keV']!=plan['native_reference_energy_keV']
            or request['channels']!=channels
            or capture['new_field_solves']!=0 or capture['new_transport_calls']!=0
            or len(capture['records'])!=len(geometry)):
        raise ValueError('Boundary capture was generated for different positions, field or reference energy')
    points=[]
    for i,(source,declared,item) in enumerate(zip(geometry,request['points'],capture['records'],strict=True)):
        expected = source['xyz_mm']
        if not (item['role']==declared['role']==source['role'] and item['position_mm']==declared['position_mm']==expected
                and item['injection_id']==declared['injection_id']==i and item['record_ref']==declared['record_ref']):
            raise ValueError('Boundary training and holdout roles differ from the frozen plan')
        path = workflow.safe_path(capture_path.parent,item['record_ref'])
        checkpoint, sha = read(path)
        record = checkpoint['payload']
        if (sha!=item['record_sha256'] or checkpoint['kind']!='gegi_independent_injection_checkpoint_v1'
                or checkpoint['identity_sha256']!=identity_sha or record['request_sha256']!=request_sha
                or record['injection_id']!=i or record['role']!=declared['role'] or record['contact_ids']!=declared['contact_ids']
                or record['point_plan_sha256']!=request['point_plan_sha256'] or record['plan_receipt']!=request['plan_receipt']
                or record['position_mm']!=expected or record['injection_energy_keV']!=plan['native_reference_energy_keV']):
            raise ValueError('Boundary injection payload differs from its bound record')
        points.append({'point_index':i,'position_mm':expected,'role':source['role'],
                       'record_ref':item['record_ref'],'record_sha256':sha,**native_point(record,channels)})
    return points,{'boundary_native_capture':capture_sha,'boundary_native_request':request_sha,'boundary_native_identity':identity_sha}


def run(acquisition_path, archive, center_path, capture_path, allocation_path, plan_path):
    plan_record, plan_sha = read(plan_path)
    case, case_sha = read(allocation_path)
    run_report, run_sha = read(acquisition_path)
    if (case.get('kind')!='gegi_trigger_12271_two_vertex_charge_allocation_diagnostic_v1'
            or case.get('original_trigger_id')!=TID
            or plan_record.get('kind')!='gegi_same_event_exact_photon_kinetic_substitutions_v1'):
        raise ValueError('Supply the retained trigger 12271 charge-allocation and injection-plan receipts')
    native_plan = plan_record['response_coverage_trigger_12271']['next_injection_inputs']
    saved, = case['adc_allocation_report']['triggers']
    if (saved['original_trigger_id']!=TID or saved['original_projected_mass']!=0
            or saved['original_unresolved_mass']!=1):
        raise ValueError('The allocation receipt must preserve the original unresolved trigger')
    if run_sha!=case['provenance']['acquisition'] or workflow.sha(archive)!=case['provenance']['candidate_store']:
        raise ValueError('The original candidate acquisition differs from the allocation receipt')
    record = storage.load_candidate(archive,TID)
    with closing(storage._open_readonly(archive)) as db:
        channels = imaging._checkpoint(db,run_report['identity'])['channels']
    measured, adc_status = imaging.voltage_window(record,run_report['excluded_intervals_ns'])
    adc_sha = hashlib.sha256(record['context']['adc_codes'].tobytes()).hexdigest()
    if (adc_sha!=saved['archive_adc_sha256'] or adc_status!='captured'
            or record['trigger_id']!=TID or record['trigger_time_ns']!=saved['trigger_time_ns']
            or storage._record_digest({**record,'context':{k:v for k,v in record['context'].items() if k!='adc_codes'}},adc_sha)
            !=saved['archive_record_sha256']):
        raise ValueError('The original 12271 measurement differs from the allocation receipt')
    # Admitting a completed native bank precedes the larger baseline template load.
    points, capture_hashes = load_points(capture_path,native_plan,plan_sha,channels)
    meta,templates,_,center_sha = calibration.load(center_path)
    if meta['channels']!=channels or center_sha!=case['provenance']['calibration']:
        raise ValueError('Center templates use different geometry or field calibration')
    templates = {cell:templates[cell] for cell in CELLS}
    fit = compare_event(measured,templates,points,saved['alternative_fit_diagnostics'])
    measured_tail = (measured-joint.remove_quiet_tail(measured))/joint.digital._LSB_V
    tail = {'quiet_sample_times_ns':joint.SAMPLE_NS[joint.TAIL_QUIET].tolist(),
            'y28_quiet_adc_codes':(measured[Y28,joint.TAIL_QUIET]/joint.digital._LSB_V).tolist(),
            'estimated_y28_tail_at_trigger_codes':float(measured_tail[Y28,joint.TRIGGER_INDEX]),
            'scope':'The standard quiet-window free-decay subtraction estimates a baseline/tail. It does not identify earlier individual pulse contributions.'}
    training = [point for point in points if point['unit_analog'] is not None
                and point['role'] in ('gap_sweep','first_vertex_response_anchor')]
    holdouts = []
    for point in points:
        if point['role'] in ('independent_gap_holdout','independent_first_vertex_holdout'):
            holdouts.append({'point_index':point['point_index'],'role':point['role'],'injected_position_mm':point['position_mm'],
                             **holdout_replay(point,templates,training,channels,record['context']['adc_phase_ns'],
                                              native_plan['native_reference_energy_keV'])})
    return {'kind':'gegi_trigger_12271_boundary_adc_comparison_v1','original_trigger_id':TID,
            'input_sha256':{**capture_hashes,'exact_injection_plan':plan_sha,'original_allocation_receipt':case_sha,
                            'acquisition':run_sha,'candidate_archive':case['provenance']['candidate_store'],
                            'candidate_record':saved['archive_record_sha256'],'original_adc':adc_sha,'center_calibration':center_sha},
            'source_sha256':{Path(mod.__file__).name:workflow.sha(mod.__file__) for mod in (joint,pulse,imaging,storage)}
                            | {Path(__file__).name:workflow.sha(__file__)},
            'measured_adc_samples_relative_to_trigger_ns':joint.SAMPLE_NS.tolist(),'electrode_ids':list(CONTACTS),
            'original_projected_mass':saved['original_projected_mass'],'original_unresolved_mass':saved['original_unresolved_mass'],
            'observed_early_y28_baseline_tail':tail,
            'native_points':[{k:v for k,v in point.items() if k not in ('unit_analog','native')} for point in points],
            'original_12271_adc_comparison':fit,'independent_holdouts':holdouts,
            'method':'Retain the original strip-energy allocation. Sum supported single-point full-electrode responses, fit one common onset '
                     'and optionally the first center-component depth, and compare with the original ADC using the same quiet-tail removal. '
                     'Gap probes are selected by their complete terminal cell; no interpolation crosses a collection boundary.',
            'interpretation':'The off-center points describe alternative charge-component responses with zero imaging weight. '
                             'Observed electronic waveforms do not establish physical vertex count or carrier endpoints. '
                             'The local probe neighborhood was fixed from the replay geometry before the ADC comparison. '
                             'Holdout positions enter only after fitting their independent quantized ADC controls.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquisition',type=Path,required=True,help='Completed candidate-acquisition.json')
    parser.add_argument('--archive',type=Path,help='Candidate SQLite archive, next to the acquisition report by default')
    parser.add_argument('--center-calibration',type=Path,required=True,help='Center calibration .npz bound to the original fit')
    parser.add_argument('--capture',type=Path,required=True,help='Completed native boundary injection COMPLETE.json')
    parser.add_argument('--allocation',type=Path,required=True,help='Saved trigger 12271 charge allocation diagnostics')
    parser.add_argument('--plan',type=Path,required=True,help='Exact-kinetic controls receipt containing the frozen ten-point plan')
    parser.add_argument('--output',type=Path,required=True,help='New comparison JSON file')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new analysis output path')
    archive = args.archive or args.acquisition.parent/storage.ARCHIVE_NAME
    result = run(args.acquisition,archive,args.center_calibration,args.capture,args.allocation,args.plan)
    with args.output.open('xb') as stream:
        stream.write((json.dumps(result,indent=2,allow_nan=False)+'\n').encode())
    comparison = result['original_12271_adc_comparison']
    print(json.dumps({'model_status':comparison['model_status'],'models':len(comparison['sampled_models']),
                      'holdout_statuses':[row['status'] for row in result['independent_holdouts']]}))


if __name__ == '__main__':
    main()
