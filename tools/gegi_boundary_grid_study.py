"""Prepare or score a measured-cell local GeGI lateral-response diagnostic."""

import argparse
from collections import Counter
from contextlib import closing
from dataclasses import replace
import hashlib
from itertools import product
import json
import math
from pathlib import Path

import numpy as np

import gegi_adc_topology as topology
import gegi_boundary_response_comparison as boundary
import gegi_candidate_imaging as imaging
import gegi_candidate_storage as storage
import gegi_dual_source as dual
from gegi_exposure_stream import ADCExposure, reconstruct_exposure
import gegi_joint_calibration as calibration
import gegi_joint_two_site as joint
import gegi_pixel_cfd_depth_study as depth
import gegi_pulse_scan as scan
import scenario_workflow as workflow


ROOT = workflow.ROOT
LATERAL_COORDINATES = tuple(product(joint.LATERAL_FRACTION, joint.LATERAL_FRACTION, joint.LATERAL_DEPTH_MM))
OFF_CENTER = tuple(c for c in LATERAL_COORDINATES if c[:2] != (0., 0.))
# Prior joint lateral controls used these interior off-template offsets and depths.
INTERIOR = ((-.23, -.27, -2.5), (.23, .27, 2.5))
START_OFFSETS = ((0., 0.), (.24, .24), (-.24, -.24), (.24, -.24), (-.24, .24))
BANK_KEYS = ('model_ref', 'model_sha256', 'field_cache', 'field_precision_bits', 'numerics',
             'channels', 'environment', 'injection_energy_keV')


def bound(path, expected):
    value, actual = boundary.read(path)
    if actual != expected:
        raise ValueError(f'Saved input hash differs at {path.name}')
    return value


def allocation_selection(case):
    selected, = case['adc_allocation_report']['triggers']
    alternatives = selected['alternative_fit_diagnostics']['hypotheses']
    sparse = [(index, row) for index, row in enumerate(alternatives)
              if row['kind'] == '3_corner_sparse' and row['status'] == 'scored']
    if selected['original_trigger_id'] != case['original_trigger_id'] or not sparse:
        raise ValueError('Expected one original trigger and a measured-only three-corner fit')
    index, winner = min(sparse, key=lambda item: item[1]['global_adc_rms_codes'])
    return selected, alternatives, index, winner


def point_design(cells, channels):
    by_id = {c['id']: c for c in channels}
    pitch = by_id[2]['strip_center_mm']-by_id[1]['strip_center_mm']
    family = {cell[1] for cell in cells}
    ys = sorted(family)
    if len(cells) != 3 or len(set(cells)) != 3 or len(ys) != 2 or ys[1]-ys[0] != 1:
        raise ValueError('This acceptance needs three measured cells spanning two adjacent Y strips')
    points = []
    for cell in cells:
        cx, cy = (by_id[c]['strip_center_mm'] for c in cell)
        boundary_side = 1 if cell[1] == ys[0] else -1
        gap = ((.23, boundary_side*.48, -2.5),)
        for role, coords in (('fit', OFF_CENTER), ('interior_holdout', INTERIOR), ('gap_holdout', gap)):
            for x, y, z in coords:
                points.append({'contact_ids': list(cell), 'role': role, 'coordinates_pitch_pitch_mm': [x, y, z],
                               'position_mm': [cx+x*pitch, cy+y*pitch, z]})
    if len({tuple(row['position_mm']) for row in points}) != len(points):
        raise ValueError('Template and holdout positions overlap')
    return points


def prior_capture(capture_path, original):
    """Use only hash-verified exact XYZ overlaps from the earlier capture."""
    if capture_path is None:
        return {}, None
    seal, seal_sha = boundary.read(capture_path)
    req = bound(capture_path.with_name('request.json'), seal['request_sha256'])
    identity = bound(capture_path.with_name('identity.json'), seal['identity_sha256'])
    if (seal['status'] != 'completed_declared_points' or identity['request_sha256'] != seal['request_sha256']
            or any(req[key] != original[key] for key in BANK_KEYS)):
        raise ValueError('The earlier capture does not use the same field, channels, and native settings')
    rows = {}
    for spec, row in zip(req['points'], seal['records'], strict=True):
        if any(row[k] != spec[k] for k in ('injection_id','role','position_mm','record_ref')):
            raise ValueError('The earlier capture changed its point roster')
        if row['status'] != 'completed' or not row['valid']:
            continue
        path = workflow.safe_path(capture_path.parent, row['record_ref'])
        rec = bound(path, row['record_sha256'])
        item = rec['payload']
        if (rec['identity_sha256'] != seal['identity_sha256'] or item['position_mm'] != spec['position_mm']
                or item['contact_ids'] != spec['contact_ids']):
            raise ValueError('The earlier point response differs from the sealed capture')
        if all(e['status']=='contact' and not e['step_limit_reached'] for e in item['endpoints']):
            key = tuple(spec['contact_ids']), tuple(spec['position_mm'])
            rows[key] = {'ref':path.relative_to(ROOT).as_posix(),'sha256':row['record_sha256'],
                         'identity_sha256':seal['identity_sha256']}
    return rows, seal_sha


def prepare(allocation_path, prior_capture_path):
    case, case_sha = boundary.read(allocation_path)
    trigger, alternatives, index, winner = allocation_selection(case)
    cells = tuple(map(tuple, winner['cells']))
    inputs = scan.Inputs()
    complete = inputs.read(scan.FULL/'COMPLETE.json', scan.FULL_COMPLETE_SHA)
    original = inputs.read(scan.FULL/'bound-request.json', complete['request_sha256'])
    design = point_design(cells, original['channels'])
    centers = [q for q in original['grid'] if q['target_ref'].startswith('injections/')
               and tuple(q['contact_ids']) in cells]
    manifest = depth.bank_manifest(inputs, complete, {q['target_ref'] for q in centers})
    verified_centers = []
    for cell in cells:
        points = [p for p in centers if tuple(p['contact_ids']) == cell]
        if sorted(p['position_mm'][2] for p in points) != joint.DEPTH_MM.tolist():
            raise ValueError(f'Missing original center depths for {cell}')
        for point in points:
            seal = manifest[point['target_ref']]
            path = scan.FULL/'bank'/seal['record_ref']
            if seal['status']!='completed' or not seal['valid'] or workflow.sha(path)!=seal['record_sha256']:
                raise ValueError(f'Original center response is unavailable at {cell}')
            verified_centers.append({'contact_ids':list(cell),'position_mm':point['position_mm'],
                                     'ref':path.relative_to(ROOT).as_posix(),'sha256':seal['record_sha256']})
    prior, prior_sha = prior_capture(prior_capture_path, original)
    missing, reused = [], []
    for spec in design:
        key = tuple(spec['contact_ids']), tuple(spec['position_mm'])
        if key in prior and spec['role']=='fit':
            reused.append(spec | prior[key])
        else:
            i = len(missing)
            missing.append(spec | {'injection_id':i,'record_ref':f'records/point-{i:02}.json'})
    # This request is directly consumable by the existing serial native point producer.
    source_request = scan.FULL/'bound-request.json'
    sources = ['simulation/'+name for name in ('gegi_response.jl','gegi_pixel_calibration.jl','gegi_signal_helpers.jl',
               'native_boundary_guard.jl','run.jl','replay.jl','readout.jl','readout_profiles.jl','readout_demo.json',
               'Project.toml','Manifest.toml')] + ['tools/gegi_native_point_injections.jl']
    return {**{key:original[key] for key in BANK_KEYS},
            'kind':'gegi_declared_point_response_request_v1',
            'plan_receipt':{'ref':allocation_path.resolve().relative_to(ROOT).as_posix(),'sha256':case_sha},
            'baseline_request':{'ref':source_request.relative_to(ROOT).as_posix(),'sha256':complete['request_sha256']},
            'points':missing,'point_plan_sha256':hashlib.sha256(workflow.encoded(missing)).hexdigest(),
            'source_file_sha256':{ref:workflow.sha(ROOT/ref) for ref in sources},
            'design_source_sha256':workflow.sha(__file__),
            'measured_scope':{'trigger_id':trigger['original_trigger_id'],'baseline_allocation_index':index,
                              'cells':cells,'all_original_allocation_cell_rosters':[row['cells'] for row in alternatives],
                              'original_projected_mass':trigger['original_projected_mass'],
                              'original_unresolved_mass':trigger['original_unresolved_mass']},
            'prior_exact_capture_sha256':prior_sha,'original_center_calibration_sha256':case['provenance']['calibration'],
            'reused_center_records':verified_centers,'reused_off_center_records':reused,
            'missing_by_role':dict(Counter(row['role'] for row in missing)),
            'scope':'Measured three-cell allocation, regular within-cell calibration grid, and separate interior and gap holdouts. '
                    'No candidate waveform, photon vertices, deposition coordinates or source location select injection positions.'}


def capture_points(folder, request, request_sha):
    seal, seal_sha = boundary.read(folder/'COMPLETE.json')
    identity = bound(folder/'identity.json', seal['identity_sha256'])
    if (seal['status'] != 'completed_declared_points' or seal['request_sha256'] != request_sha
            or identity['request_sha256'] != request_sha or seal['new_field_solves'] != 0 or seal['new_transport_calls'] != 0
            or seal['point_plan_sha256'] != request['point_plan_sha256']):
        raise ValueError('Expected the completed, exact declared point capture')
    points = []
    for spec, row in zip(request['points'], seal['records'], strict=True):
        if any(row[k] != spec[k] for k in ('injection_id','role','position_mm','record_ref')):
            raise ValueError('The captured template/holdout identities changed')
        entry = bound(workflow.safe_path(folder, row['record_ref']), row['record_sha256'])
        data = entry['payload']
        if (entry['identity_sha256'] != seal['identity_sha256'] or data['request_sha256'] != request_sha
                or any(data[k] != spec[k] for k in ('injection_id','role','position_mm','contact_ids'))
                or data['injection_energy_keV'] != request['injection_energy_keV']):
            raise ValueError('An injection payload differs from its bound input')
        points.append(spec | {'record_sha256':row['record_sha256']} | boundary.native_point(data, request['channels']))
    for row in request['reused_off_center_records']:
        entry = bound(ROOT/row['ref'], row['sha256'])
        data = entry['payload']
        if (entry['identity_sha256'] != row['identity_sha256'] or data['position_mm'] != row['position_mm']
                or data['contact_ids'] != row['contact_ids'] or data['injection_energy_keV'] != request['injection_energy_keV']):
            raise ValueError('A previously sealed point response changed')
        points.append(row | boundary.native_point(data, request['channels']))
    return points, seal_sha


def lateral_templates(centers, points):
    templates, coverage = {}, []
    for cell, center in centers.items():
        captures = {tuple(p['coordinates_pitch_pitch_mm']):p['unit_analog'] for p in points
                    if p['role']=='fit' and tuple(p['contact_ids'])==cell and p['collected_cell']==cell
                    and p['unit_analog'] is not None}
        missing = [coords for coords in OFF_CENTER if coords not in captures]
        coverage.append({'cell':cell,'available':not missing,'missing_or_alternate_endpoint_coordinates':missing})
        templates[cell] = center
        if missing:
            continue
        by_depth = dict(zip(joint.DEPTH_MM, center.center_v_per_keV, strict=True))
        # Same center-subtracted correction convention as the existing lateral Template.
        values = np.array([captures[x,y,z]-by_depth[z] if x or y else np.zeros_like(by_depth[z])
                           for x,y,z in LATERAL_COORDINATES])
        templates[cell] = replace(center,lateral_correction_v_per_keV=values.reshape(3,3,3,*values.shape[1:]))
    return templates, coverage


def fit_points(observed, templates, cells, energies, *, use_lateral, center_seed=None):
    joint._check_adc(observed)
    sites = [templates[c] for c in cells]
    support = tuple(use_lateral and t.lateral_correction_v_per_keV is not None for t in sites)
    interpolators = joint._interpolators(sites,slice(None),support)
    lo_xy, _, hi_xy = joint.LATERAL_FRACTION
    lo_z, hi_z = float(joint.DEPTH_MM[0]), float(joint.DEPTH_MM[-1])
    limits = [bound for active in support for bound in
              ([(lo_xy,hi_xy),(lo_xy,hi_xy),(lo_z,hi_z)] if active else [(lo_z,hi_z)])] + [joint.SHIFT_LIMIT_NS]
    scales = np.array([s for active in support for s in ((.4,.4,5.) if active else (5.,))] + [20.])
    measured = joint.remove_quiet_tail(observed)

    def coordinates(params):
        result, offset = [], 0
        for active in support:
            result.append(tuple(params[offset:offset+3]) if active else (0.,0.,params[offset]))
            offset += 3 if active else 1
        return result

    def predict(params):
        analog = sum(e*(center([z])[0]+(lateral((x,y,z)) if lateral else 0.))
                     for e,(center,lateral),(x,y,z) in zip(energies,interpolators,coordinates(params),strict=True))
        return joint.shifted_samples(analog,params[-1])

    def residual(params):
        return ((joint.remove_quiet_tail(predict(params))-measured)/joint.NOISE_RMS_V).ravel()

    if any(support):
        depths, onset = center_seed
        slots = [[(x,y,z) for x,y in START_OFFSETS] if active else [(z,)]
                 for z,active in zip(depths,support,strict=True)]
        starts = [np.array([q for xyz in combination for q in xyz]+[onset]) for combination in product(*slots)]
    else:
        starts = [np.array([*z,t]) for z in product((-4.,0.,4.),repeat=len(cells)) for t in (-15.,5.)]
    selected = sorted(starts,key=lambda p:np.linalg.norm(residual(p)))[:3]
    best, near, diagnostic = joint._best_refinement(residual,selected,tuple(zip(*limits)),scales)

    def points(params):
        return [[t.origin_mm[0]+x*t.pitch_mm,t.origin_mm[1]+y*t.pitch_mm,z]
                for t,(x,y,z) in zip(sites,coordinates(params),strict=True)]

    return {'status':'scored' if best.success else 'optimizer_unconverged','site_lateral_support':support,
            'positions_mm':points(best.x),'onset_relative_to_trigger_ns':float(best.x[-1]),
            'parameters_at_bounds':[i for i,(v,(a,b)) in enumerate(zip(best.x,limits,strict=True))
                                    if min(v-a,b-v)<=joint.BOUNDARY_TOLERANCE],
            'sampled_near_ties_mm':[points(r.x) for r in near if r is not best],
            'optimizer':diagnostic,**boundary.rms(observed,predict(best.x))}


def controlled_adc(points, energies, channels, phase, reference_energy, seed):
    traces = [(p['native'],1000.,e/reference_energy) for p,e in zip(points,energies,strict=True)]
    exposure = ADCExposure(traces,live_time_ns=4000.,phase_ns=phase,noise_seed=seed)
    contexts = []

    def retain(event, context):
        contexts.append((event,dict(context,adc_codes=context['adc_codes'].copy())))

    result = reconstruct_exposure(exposure,on_readout_context=retain)
    info = {'noise_seed':seed,'adc_sha256':result['adc_sha256'],'trigger_count':len(result['events'])}
    if len(contexts)!=1 or len(result['events'])!=1:
        return info,None,None
    event, context = contexts[0]
    card = dual._trigger_card(event,dual._strip_neighbors(channels),geometry=channels)
    volts, _ = imaging.voltage_window({'trigger_time_ns':event['trigger_time_ns'],'context':context},[])
    return info,card,volts


def score_holdout(points, energies, templates, phase, request, seed):
    """Simulate ADC from the independent inputs, then fit using measured signals alone."""
    refs = [{'contact_ids':p['contact_ids'],'position_mm':p['position_mm'],'role':p['role'],
             'injection_id':p['injection_id'],'terminal_cell':p['collected_cell']} for p in points]
    row = {'held_out_positions_for_scoring':refs,'input_energies_keV':energies}
    if any(p['native'] is None for p in points):
        return row | {'status':'unqualified_native_holdout'}
    info,card,volts = controlled_adc(points,energies,request['channels'],phase,request['injection_energy_keV'],seed)
    if card is None or volts is None:
        return row | info | {'status':'no_unique_measured_adc_window'}
    if len(points)==1:
        xs,ys = card['x_collecting_strips'],card['y_collecting_strips']
        cells = ((xs[0],ys[0]),) if len(xs)==len(ys)==1 and not card['guard_contact_ids'] else ()
        measured = [card['energy_keV']]
    else:
        group = card.get('two_strip_pairings')
        if group is None:
            return row | info | {'status':'measured_three_cell_allocation_unavailable'}
        _,flows,_,_,_,_ = topology.matching_marginals(group['collectors'])
        cells = tuple(map(tuple,request['measured_scope']['cells']))
        matches = [flow for flow in flows if {(x,y) for x,y,_ in flow} == set(cells)]
        if len(matches)!=1:
            return row | info | {'status':'measured_three_cell_allocation_unavailable'}
        by_cell = {(x,y):e for x,y,e in matches[0]}
        measured = [by_cell[cell] for cell in cells]
    if not cells or any(cell not in templates for cell in cells) or any(e is None or e<=0 for e in measured):
        return row | info | {'status':'unsupported_measured_holdout_cells','measured_cells':cells}
    center = fit_points(volts,templates,cells,measured,use_lateral=False)
    lateral = None
    if any(templates[c].lateral_correction_v_per_keV is not None for c in cells):
        seed_point = ([p[2] for p in center['positions_mm']],center['onset_relative_to_trigger_ns'])
        lateral = fit_points(volts,templates,cells,measured,use_lateral=True,center_seed=seed_point)
    truth = {p['collected_cell']:p['position_mm'] for p in points}
    for fit in (center,lateral):
        if fit is not None and fit['status']=='scored' and set(truth)==set(cells) and len(truth)==len(points):
            fit['position_errors_mm'] = [math.dist(p,truth[c]) for p,c in zip(fit['positions_mm'],cells,strict=True)]
    return row | info | {'status':'evaluated','measured_cells':cells,'measured_energies_keV':measured,
                         'center':center,'lateral':lateral}


def score(acquisition_path, archive, center_path, folder, allocation_path, request_path):
    request, request_sha = boundary.read(request_path)
    case = bound(allocation_path, request['plan_receipt']['sha256'])
    report = bound(acquisition_path, case['provenance']['acquisition'])
    selected, alternatives, index, winner = allocation_selection(case)
    cells = tuple(map(tuple,winner['cells']))
    tid = request['measured_scope']['trigger_id']
    positions = point_design(cells,request['channels'])
    planned = [(p['role'],p['position_mm'],p['contact_ids']) for p in positions]
    actual = [(p['role'],p['position_mm'],p['contact_ids']) for p in
              (*request['points'],*request['reused_off_center_records'])]
    if (tid!=selected['original_trigger_id'] or index!=request['measured_scope']['baseline_allocation_index']
            or cells!=tuple(map(tuple,request['measured_scope']['cells'])) or sorted(planned)!=sorted(actual)
            or hashlib.sha256(workflow.encoded(request['points'])).hexdigest()!=request['point_plan_sha256']
            or workflow.sha(archive)!=case['provenance']['candidate_store']):
        raise ValueError('Declared grid, original candidate, or measured cell roster changed')
    points, seal_sha = capture_points(folder,request,request_sha)
    for row in request['reused_center_records']:
        if workflow.sha(ROOT/row['ref'])!=row['sha256']:
            raise ValueError('A center template source response changed')
    record = storage.load_candidate(archive,tid)
    adc = hashlib.sha256(record['context']['adc_codes'].tobytes()).hexdigest()
    metadata = {**record,'context':{k:v for k,v in record['context'].items() if k!='adc_codes'}}
    if adc!=selected['archive_adc_sha256'] or storage._record_digest(metadata,adc)!=selected['archive_record_sha256']:
        raise ValueError('The measured ADC and card do not match the original allocation receipt')
    with closing(storage._open_readonly(archive)) as db:
        channels = imaging._checkpoint(db,report['identity'])['channels']
    package, center_templates, _, center_sha = calibration.load(center_path)
    if not package['channels']==request['channels']==channels or center_sha!=request['original_center_calibration_sha256']:
        raise ValueError('Original center templates, field or electrode details differ')
    templates, coverage = lateral_templates({cell:center_templates[cell] for cell in cells},points)
    observed, adc_status = imaging.voltage_window(record,report['excluded_intervals_ns'])
    if adc_status!='captured':
        raise ValueError('Original measured window does not match the saved center fit')
    baseline = boundary.compare_event(observed,center_templates,[],selected['alternative_fit_diagnostics'])['baseline_center_three_cell']
    energies = winner['fit']['site_energies_keV']
    seeds = ([p[2] for p in winner['fit']['site_positions_mm']],winner['fit']['onset_relative_to_trigger_ns'])
    active = [row['cell'] for row in coverage if row['available']]
    event_models = [{'allocation_index':i, 'cells':item['cells'],'original_status':item['status'],
                     'original_global_adc_rms_codes':item.get('global_adc_rms_codes'),
                     'cells_without_lateral_support':[cell for cell in item['cells'] if tuple(cell) not in active],
                     'diagnostic_status':('selected_for_local_grid' if i==index else 'original_alternative_retained')}
                    for i,item in enumerate(alternatives)]
    lateral = fit_points(observed,templates,cells,energies,use_lateral=True,center_seed=seeds) if active else None
    phase = record['context']['adc_phase_ns']
    held = [p for p in points if p['role']!='fit']
    holdouts = [score_holdout([p],[request['injection_energy_keV']],templates,phase,request,20261122+i)
                for i,p in enumerate(held)]
    by_cell = [[p for p in held if tuple(p['contact_ids'])==cell and p['role']=='interior_holdout'] for cell in cells]
    mixtures = [score_holdout(combination,energies,templates,phase,request,20261162+i)
                for i,combination in enumerate(zip(*by_cell,strict=True))]
    return {'kind':'gegi_measured_cell_boundary_grid_diagnostic_v1',
            'input_sha256':{'point_request':request_sha,'native_capture':seal_sha,'allocation':request['plan_receipt']['sha256'],
                            'acquisition':case['provenance']['acquisition'],'candidate_store':case['provenance']['candidate_store'],
                            'original_adc':adc,'center_calibration':center_sha},
            'source_sha256':{Path(module.__file__).name:workflow.sha(module.__file__) for module in (boundary,joint,topology)}
                            | {Path(__file__).name:workflow.sha(__file__)},
            'measured_scope':request['measured_scope'],'calibration_support':coverage,
            'captured_points':[{k:v for k,v in p.items() if k not in ('native','unit_analog')} for p in points],
            'original_adc':{'center':baseline,'within_cell_fit':lateral,'original_alternatives':event_models},
            'independent_single_pulse_controls':holdouts,'independent_overlap_controls':mixtures,
            'interpretation':'One bounded host-cell response fit uses observed charge allocation and identical ADC samples. '
                             'Alternate collection classes retain their endpoints and leave missing grid coordinates explicit. '
                             'The fitted cube covers offsets through 0.4 strip pitch. The separate gap holdouts lie outside this support. '
                             'Fitted charge-response positions do not identify photon vertices or change the original image.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    plan = commands.add_parser('prepare',help='Write the missing-point request without starting a worker')
    plan.add_argument('--prior-capture',type=Path,help='Existing exact point capture COMPLETE.json for reuse')
    consumer = commands.add_parser('score',help='Compare the sealed capture with original and independent quantized ADC')
    consumer.add_argument('--capture',type=Path,required=True,help='Directory containing native identity and COMPLETE.json')
    consumer.add_argument('--request',type=Path,help='Exact native request JSON, defaulting to request.json inside the capture directory')
    consumer.add_argument('--acquisition',type=Path,required=True)
    consumer.add_argument('--archive',type=Path)
    consumer.add_argument('--center-calibration',type=Path,required=True)
    for command in (plan,consumer):
        command.add_argument('--allocation',type=Path,required=True)
        command.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output path')
    if args.command=='prepare':
        value = prepare(args.allocation,args.prior_capture)
    else:
        archive = args.archive or args.acquisition.parent/storage.ARCHIVE_NAME
        request = args.request or args.capture/'request.json'
        value = score(args.acquisition,archive,args.center_calibration,args.capture,args.allocation,request)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(workflow.encoded(value)+b'\n')
    print(json.dumps({'sha256':workflow.sha(args.output),
                      'missing_by_role':value.get('missing_by_role'),
                      'reused_centers':len(value.get('reused_center_records',()))}))


if __name__ == '__main__':
    main()
