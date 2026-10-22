"""Capture fixed interior native-grid support for X11/12 by Y24/26 footprints."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np
import gegi_calibration_admission as A
import gegi_native_cell_bank as B
from gegi_native_cell_bank import ROOT, W, P, N

REQUEST=P.CALIBRATION+'/native-region-bank/request.json'
SOURCE=P.CALIBRATION+'/native-cell-bank'
COVERAGE='.local/gegi-10m/signal-recovery-v1/validation/native-inverse-applicability/result.json'
COVERAGE_SHA='a019a603b00c4656c4365825f01ff896f839c304877d67274a942373b9ef81d3'
COMPLETE_SHA='9558d3533446380a82667cd8ad6dfec0fe0d12442553d97e42e8201ee787de73'
KIND='gegi_fixed_interior_native_region_request_v1'
STATUS='completed_fixed_interior_native_region_bank'
LIMITS={'maximum_records':5148,'reused_records':378,'maximum_new_drift_calls':4770,
        'maximum_total_wall_seconds':300,'julia_threads':1,'worker_processes':1,'automatic_retry':False}

# Reuse the executed fixed-bank worker. Imports retain the complete original
# payload, including earlier response_origin; provenance is in the new request.
_before,_after=B.JULIA_WORKER.split('            row["response_origin"]=Dict(',1)
_,_after=_after.split('            K.save_record(path,row,requestsha);imports+=1',1)
JULIA_WORKER=(_before+'            K.save_record(path,row,requestsha);imports+=1'+_after)
JULIA_WORKER=JULIA_WORKER.replace('length(req["points"])==378','length(req["points"])==5148')
JULIA_WORKER=JULIA_WORKER.replace('drifts<=374','drifts<=4770').replace('imports==4 && drifts==374','imports==378 && drifts==4770')
JULIA_WORKER=JULIA_WORKER.replace(B.STATUS,STATUS)
JULIA_WORKER=JULIA_WORKER.replace('geometry_ok=all(c["inside_semiconductor"] && isempty(c["contact_ids"]) for c in corners)',
    'geometry_ok=all(c["inside_semiconductor"] && isempty(c["contact_ids"]) && abs(c["native_position_m"][3])<req["strict_face_bound_m"] for c in corners)')


def geometry_plan(coverage,axes):
    face=N.native_position([5.5,0.,0.])[0]
    full_z=[i for i,z in enumerate(axes[2]) if -face<=z<=face]
    interior_z=[i for i in full_z if -face<axes[2][i]<face]
    points={};regions=[];full=set()
    for spec in coverage['by_pixel']:
        intervals=[];nodes=[]
        for axis,key in enumerate(('strip_footprint_x_mm','strip_footprint_y_mm')):
            low,high=spec[key];ticks=np.asarray(axes[axis])*1000
            indices=np.flatnonzero((ticks[:-1]<high)&(ticks[1:]>low)).tolist()
            intervals.append(indices);nodes.append(sorted(set(indices+[i+1 for i in indices])))
        regions.append({**spec,'x_node_indices_zero_based':nodes[0],'y_node_indices_zero_based':nodes[1],
            'x_interval_indices_zero_based':intervals[0],'y_interval_indices_zero_based':intervals[1]})
        full.update(itertools.product(*nodes,full_z))
        for index in itertools.product(*nodes,interior_z):
            desired=[axes[k][i] for k,i in enumerate(index)];parts=[B.native_axis(v) for v in desired]
            actual=tuple(p[1] for p in parts)
            if actual not in points:
                points[actual]={'grid_indices_zero_based':list(index),'requested_grid_position_m':desired,
                    'position_mm':[p[0] for p in parts],'native_position_m':list(actual),
                    'grid_deviation_m':[p[2] for p in parts],'grid_deviation_ulps':[p[3] for p in parts],
                    'exact_native_grid':all(p[2]==0 for p in parts),'expected_pixel_bindings':[]}
            points[actual]['expected_pixel_bindings'].append(spec['contact_ids'])
    W.require(len(full_z)==35 and len(interior_z)==33 and len(full)==5460 and len(points)==5148 and
        len(full)-len(points)==312,'Geometry-only region count differs from the authorized interior plan.')
    return points,regions,{'full_z_indices_zero_based':full_z,'interior_z_indices_zero_based':interior_z,
        'strict_face_bound_m':face,'omitted_contact_face_starts':312}


def prepare():
    source=ROOT/SOURCE;old=W.read(source/'request.json');complete=W.read(source/'results/COMPLETE.json')
    coverage=W.read(ROOT/COVERAGE)['next_coverage_count'];pre=W.read(source/'results/preflight.json')
    W.require(W.sha(ROOT/COVERAGE)==COVERAGE_SHA and W.sha(source/'results/COMPLETE.json')==COMPLETE_SHA and
        W.sha(source/'request.json')==complete['request_sha256'] and
        W.sha(source/'results/preflight.json')==complete['preflight_sha256'] and
        coverage['positive_terminal_strip_ids']==[11,12,24,26] and
        coverage['unique_strict_interior_corners']==5148 and coverage['new_strict_interior_corners_after_existing_imports']==4770,
        'Sealed source/geometry count changed.')
    points,regions,zplan=geometry_plan(coverage,pre['weighting_axes_m'])
    original_points={p['record_ref']:p for p in old['points']}
    for item in complete['points']:
        prior=original_points[item['record_ref']];point=points[tuple(prior['native_position_m'])]
        record=source/'results'/item['record_ref'];diag=source/'results'/item['diagnostic_ref'];checkpoint=W.read(record);row=checkpoint['payload']
        W.require(W.sha(record)==item['record_sha256'] and W.sha(diag)==item['diagnostic_sha256'] and
            row['position_mm']==point['position_mm'] and row['contact_ids'] in point['expected_pixel_bindings'] and
            checkpoint['identity_sha256']==complete['request_sha256'],'Sealed native support import changed.')
        point.update(source_record=P.binding(record),source_diagnostic=P.binding(diag),
            source_payload_sha256=checkpoint['payload_sha256'],contact_ids=row['contact_ids'])
    rows=[]
    for i,(_,point) in enumerate(sorted(points.items()),1):
        point['record_ref']=f'injections/point-{i:05}.json'
        point.setdefault('contact_ids',point['expected_pixel_bindings'][0]);rows.append(point)
    W.require(sum('source_record' in p for p in rows)==378,'Expected378 existing native support imports.')
    sources={ref:W.sha(ROOT/ref) for ref in old['source_file_sha256'] if ref.startswith('simulation/')}
    W.require(sources['simulation/gegi_pixel_calibration.jl']==old['source_file_sha256']['simulation/gegi_pixel_calibration.jl'],
        'Native calibration recorder changed.')
    saved_identity={key:old[key] for key in ('model_sha256','channels','field_cache','field_precision_bits','numerics')}
    saved_identity.update(environment=old['environment']['native'],source_sha256={Path(ref).name:sha for ref,sha in old['source_file_sha256'].items() if ref.startswith('simulation/')})
    dt=old['numerics']['dt'];view={'model_sha256':old['model_sha256'],'field_cache':old['field_cache'],
        'numerics':{'drift_dt_ns':dt,'drift_cap_ns':(old['numerics']['max_steps']-1)*dt}}
    bridge=A._match(saved_identity,view,old['channels'],field_precision=32,
        native_sources={Path(ref).name:sha for ref,sha in sources.items()},
        manifest_sha256=sources['simulation/Manifest.toml'],julia_version=old['environment']['native']['julia_version'])
    W.require(bridge is not None and W.sha(ROOT/old['model_ref'])==old['model_sha256'],'Expected exact readout-only source bridge/model.')
    sources.update({ref:W.sha(ROOT/ref) for ref in ('tools/gegi_full34_pilot.py','tools/gegi_native_cell_pilot.py',
        'tools/gegi_native_cell_bank.py','tools/gegi_native_region_bank.py','tools/gegi_calibration_admission.py','tools/scenario_workflow.py')})
    req={key:old[key] for key in ('model_ref','model_sha256','field_cache','field_precision_bits','numerics','channels','environment')}
    req.update(kind=KIND,status='prepared_not_executed',limits=LIMITS,points=rows,regions=regions,**zplan,
        source_native_request_sha256=complete['request_sha256'],source_compatibility_bridge=bridge,
        source_file_sha256=sources,input_bindings={name:P.binding(path) for name,path in {
            'source_request':source/'request.json','source_complete':source/'results/COMPLETE.json',
            'native_preflight':source/'results/preflight.json','coverage':ROOT/COVERAGE,'source_runtime':source/'results/runtime.json'}.items()},
        worker_sha256=hashlib.sha256(JULIA_WORKER.encode()).hexdigest(),injection_energy_keV=500.,
        random_seed=None,randomness='Fixed deterministic point injections; no random draws',memory_policy='measure_only_not_a_launch_or_stop_condition',
        coordinate_summary={'unique_points':5148,'exact_points':sum(p['exact_native_grid'] for p in rows),
            'rounded_points':sum(not p['exact_native_grid'] for p in rows),
            'max_absolute_offset_m':max(abs(v) for p in rows for v in p['grid_deviation_m']),
            'max_absolute_offset_ulps':max(abs(v) for p in rows for v in p['grid_deviation_ulps']),
            'multiple_expected_pixel_bindings':sum(len(p['expected_pixel_bindings'])>1 for p in rows)},
        measured_cost_scale={'startup_seconds_prior':24.886,'first_capture_seconds_prior':12.213,
            'warm_mean_capture_store_seconds_prior':.00766,'warm_scale4770_seconds':4770*.00766,
            'scope':'Prior measured bank timing scale; excludes additional endpoint/IO overhead and is not a runtime guarantee.'},
        authorization='Owner bounded repair autonomy; root authorized one4770-drift/300s interior region capture.',
        scope='Geometry-only observed X11/12 byY24/26 footprint coverage,33strict-interior z ticks;312face starts omitted. Recorder contact_ids are expected bindings, not measured collectors. Source payloads unchanged; actual endpoints, full34 waves and incomplete/null statuses retained.')
    path=ROOT/REQUEST;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():W.require(W.read(path)==req,'Existing region request changed; preserve it.')
    else:
        with path.open('xb') as stream:stream.write(W.encoded(req)+b'\n')
    return {'status':'prepared_not_executed','request_sha256':W.sha(path),'tool_sha256':W.sha(__file__),
        'worker_sha256':req['worker_sha256'],'limits':LIMITS,'coordinate_summary':req['coordinate_summary'],
        'measured_cost_scale':req['measured_cost_scale']}


def checked_request(digest):
    path=ROOT/REQUEST;req=W.read(path)
    W.require(W.sha(path)==digest and req['kind']==KIND and req['limits']==LIMITS and
        req['worker_sha256']==hashlib.sha256(JULIA_WORKER.encode()).hexdigest(),'Frozen region request changed.')
    for ref,sha in req['source_file_sha256'].items():W.require(W.sha(ROOT/ref)==sha,'Pinned source changed: '+ref)
    bindings=list(req['input_bindings'].values())
    bindings.extend(p[key] for p in req['points'] if 'source_record' in p for key in ('source_record','source_diagnostic'))
    for b in bindings:W.require(W.sha(ROOT/b['ref'])==b['sha256'],'Pinned saved input changed: '+b['ref'])
    return path,req


def execute(digest):
    path,req=checked_request(digest)
    W.require(W.sha(req['environment']['julia_executable'])==req['environment']['julia_executable_sha256'],'Pinned Julia changed.')
    return P.launch(path,req,digest,JULIA_WORKER,STATUS)


def summarize(digest):
    started=time.perf_counter();path,req=checked_request(digest);results=path.parent/'results';complete=W.read(results/'COMPLETE.json')
    W.require(complete['status']==STATUS and complete['request_sha256']==digest and len(complete['points'])==5148 and
        complete['new_drift_calls']==4770 and complete['reused_records']==378,'Completed fixed region bank required.')
    statuses=Counter();pairs=Counter();endpoint_states=Counter();matched=0;imports=0;channels=0;internal=0.;capture=0.;errors=[]
    maximum_identity=0.;maximum_ideal=0.;null_endpoints=0;null_signals=0
    for item,point in zip(complete['points'],req['points']):
        record=results/item['record_ref'];diagpath=results/item['diagnostic_ref'];checkpoint=W.read(record);row=checkpoint['payload'];diag=W.read(diagpath)
        W.require(item['record_ref']==point['record_ref'] and W.sha(record)==item['record_sha256'] and
            W.sha(diagpath)==item['diagnostic_sha256'] and checkpoint['identity_sha256']==digest and
            row['position_mm']==point['position_mm'] and row['contact_ids']==point['contact_ids'],'Captured point seal/identity changed.')
        if 'source_record' in point:
            W.require(checkpoint['payload_sha256']==point['source_payload_sha256'],'Imported source payload changed.')
            imports+=1
        statuses[row['status']]+=1;internal+=diag['native_injection_seconds_this_attempt'];capture+=diag['capture_and_store_seconds']
        if row['channel_signals'] is None:null_signals+=1
        else:
            W.require(row['signal_coverage']==B.L.R.ALL34_COVERAGE and [s['contact_id'] for s in row['channel_signals']]==list(range(1,35)),
                'Captured native coverage changed.')
            channels+=34
        if row['endpoints'] is None:null_endpoints+=1
        else:
            endpoints={e['species']:e for e in row['endpoints']}
            e=endpoints['electron'];h=endpoints['hole'];pairs[json.dumps([h['contact_ids'],e['contact_ids']],separators=(',',':'))]+=1
            matched+=any(h['contact_ids']==[x] and e['contact_ids']==[y] for x,y in point['expected_pixel_bindings'])
            for ep in endpoints.values():endpoint_states[ep['status']]+=1
        identity=diag['endpoint_identity']
        if identity is not None:
            maximum_identity=max(maximum_identity,identity['max_absolute_terminal_identity_error_keV'])
            if identity['max_absolute_terminal_ideal_contact_error_keV'] is not None:
                maximum_ideal=max(maximum_ideal,identity['max_absolute_terminal_ideal_contact_error_keV'])
        if row.get('error'):errors.append({'record_ref':item['record_ref'],'status':row['status'],'error':row['error']})
    result={'kind':'gegi_interior_native_region_summary_v1','status':'verified_completed_capture','request_sha256':digest,
        'complete_sha256':W.sha(results/'COMPLETE.json'),'runtime':W.read(results/'runtime.json'),
        'counts':{'records':5148,'imports_with_unchanged_payload_sha256':imports,'new_drifts':4770,'statuses':dict(statuses),
            'saved_signed_waveforms':channels,'null_signals':null_signals,'null_endpoints':null_endpoints,
            'actual_collectors_match_an_expected_binding':matched,'available_endpoints_with_no_binding_match':5148-null_endpoints-matched},
        'actual_collector_pairs_hole_then_electron':dict(pairs),'endpoint_status_counts':dict(endpoint_states),
        'max_absolute_terminal_endpoint_algebra_error_keV':maximum_identity,'max_absolute_terminal_ideal_contact_error_keV':maximum_ideal,
        'new_native_internal_seconds_sum':internal,'capture_store_diagnostic_seconds_sum':capture,
        'coordinate_summary':req['coordinate_summary'],'omitted_contact_face_starts':req['omitted_contact_face_starts'],
        'native_failures':errors,'verification_seconds':time.perf_counter()-started,
        'scope':'Capture and identity accounting only. Wrong-collector/incomplete native statuses retained. Interior grid stops before both detector faces; no inverse or experimental validation.'}
    with (results/'summary.json').open('xb') as stream:stream.write(W.encoded(result)+b'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--execute',action='store_true');mode.add_argument('--summarize',action='store_true')
    parser.add_argument('--request-sha256');args=parser.parse_args()
    result=execute(args.request_sha256) if args.execute else summarize(args.request_sha256) if args.summarize else prepare()
    print(json.dumps(result,indent=2));raise SystemExit(0 if result.get('returncode',0)==0 else 1)
