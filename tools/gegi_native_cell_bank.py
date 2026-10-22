"""Fixed native-grid support bank for the existing 80 independent GeGI targets.

Preparation only by default. Capture reuses four saved references and makes at
most 374 new deterministic drifts; comparison reads saved data only.
"""
from __future__ import annotations
import argparse
import bisect
from collections import Counter
from functools import cache
import hashlib
import itertools
import json
import time

import numpy as np
import gegi_native_cell_pilot as N
from gegi_native_cell_pilot import ROOT, W, P, L, T

REQUEST = P.CALIBRATION+'/native-cell-bank/request.json'
PILOT_COMPLETE_SHA = 'b90157215e58eb989feb1579a72a415911f14f77e357c46eab4f7f1f769aac25'
KIND = 'gegi_fixed80_native_grid_near_bank_request_v1'
STATUS = 'completed_fixed80_native_grid_near_bank'
LIMITS = {'maximum_records':378,'reused_records':4,'maximum_new_drift_calls':374,
          'maximum_total_wall_seconds':300,'julia_threads':1,'worker_processes':1,'automatic_retry':False}

JULIA_WORKER = P.JULIA_WORKER.split('function main(reqpath,out)',1)[0] + r'''
function main(reqpath,out)
    req=G.E.readjson(reqpath);requestsha=G.hashfile(reqpath)
    check(Threads.nthreads()==1 && length(req["points"])==378,"Fixed bank census/thread limit changed")
    check(G.E.environment()==req["environment"]["native"],"Original native environment changed")
    pkgroot=dirname(dirname(pathof(SSD)))
    for (ref,digest) in req["environment"]["SSD_science_source_sha256"]
        check(G.hashfile(joinpath(pkgroot,"src",ref))==digest,"Installed SSD science source changed")
    end
    cfg=(; (Symbol(k)=>v for (k,v) in req["numerics"])...)
    report=Dict{String,Any}();tick=time()
    sim=G.load_fields(Dict("field_cache"=>req["field_cache"]),joinpath(G.ROOT,req["model_ref"]),out,cfg,report)
    check(report["fields"]["mode"]=="explicit_exact_model_cache" && report["fields"]["solve_seconds"]==0 &&
        SSD.get_precision_type(sim)==Float32 && sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel &&
        G.H.channel_metadata(sim.config_dict)==req["channels"],"Original native field/contact state changed")
    fresh(joinpath(out,"startup.json"),Dict("field_load_seconds"=>time()-tick,"fields"=>report["fields"],
        "startup_seconds_including_worker_imports"=>time()-parse(Float64,ENV["GEGI_FULL34_STARTED_UNIX"]),
        "process_peak_rss_bytes"=>Sys.maxrss()))
    axesof(grid)=[Float64.(grid.axes[k].ticks) for k in 1:3]
    wpaxes=axesof(sim.weighting_potentials[1].grid);efaxes=axesof(sim.electric_field.grid)
    saved=G.E.readjson(joinpath(G.ROOT,req["input_bindings"]["native_preflight"]["ref"]))
    grids_ok=wpaxes==saved["weighting_axes_m"] && efaxes==saved["electric_field_axes_m"] &&
        all(axesof(sim.weighting_potentials[id].grid)==wpaxes for id in 1:34)
    corners=[begin
        p=SSD.CartesianPoint{Float32}((Float32.(item["position_mm"])./Float32(1000))...)
        actual=[Float64(p.x),Float64(p.y),Float64(p.z)]
        delta=actual.-item["requested_grid_position_m"]
        ulps=[d==0 ? 0. : d/Float64(eps(abs(Float32(v)))) for (d,v) in zip(delta,item["requested_grid_position_m"])]
        Dict("record_ref"=>item["record_ref"],"native_position_m"=>actual,
            "inside_semiconductor"=>p in sim.detector.semiconductor,
            "contact_ids"=>[c.id for c in sim.detector.contacts if p in c.geometry],
            "actual_matches_request"=>actual==item["native_position_m"] && delta==item["grid_deviation_m"] && ulps==item["grid_deviation_ulps"],
            "requested_ticks_in_original_grid"=>all(item["requested_grid_position_m"][k] in wpaxes[k] for k in 1:3))
    end for item in req["points"]]
    geometry_ok=all(c["inside_semiconductor"] && isempty(c["contact_ids"]) for c in corners)
    coordinates_ok=all(c["actual_matches_request"] && c["requested_ticks_in_original_grid"] for c in corners)
    accepted=grids_ok && geometry_ok && coordinates_ok
    fresh(joinpath(out,"preflight.json"),Dict("status"=>accepted ? "accepted_zero_drifts" : "rejected_zero_drifts",
        "original_grid_axes_exact"=>grids_ok,"all_actual_positions_match_request"=>coordinates_ok,
        "all_corner_geometry_valid"=>geometry_ok,"corners"=>corners,"weighting_axes_m"=>wpaxes,
        "electric_field_axes_m"=>efaxes,"new_drift_calls"=>0))
    if !accepted
        fresh(joinpath(out,"failure.json"),Dict("status"=>"preflight_rejected_zero_drifts","new_drift_calls"=>0,
            "error"=>"Fixed bank geometry, original grid or actual injected coordinates mismatch",
            "channel_signals"=>nothing,"endpoints"=>nothing,"automatic_retry"=>false))
        return false
    end
    rows=Any[];statuses=Dict{String,Int}();drifts=0;imports=0
    for (i,p) in enumerate(req["points"])
        if time()>=parse(Float64,ENV["GEGI_FULL34_DEADLINE_UNIX"])
            fresh(joinpath(out,"PARTIAL.json"),Dict("status"=>"checkpointed_budget_stop","completed_records"=>length(rows),
                "new_drift_calls"=>drifts,"reused_records"=>imports,"automatic_retry"=>false))
            return false
        end
        G.save(joinpath(out,"progress.json"),Dict("status"=>"record_running","point_index"=>i,
            "completed_records"=>length(rows),"new_drift_calls"=>drifts,"reused_records"=>imports))
        path=joinpath(out,p["record_ref"]);tick=time();imported=haskey(p,"source_record")
        if imported
            row=K.read_record(joinpath(G.ROOT,p["source_record"]["ref"]),req["source_native_request_sha256"])
            check(K.digest(row)==p["source_payload_sha256"] && row["position_mm"]==p["position_mm"] &&
                row["contact_ids"]==p["contact_ids"],"Saved native-corner import changed")
            row["response_origin"]=Dict("mode"=>"imported_saved_native_corner","source_record"=>p["source_record"],
                "source_payload_sha256"=>p["source_payload_sha256"],"source_identity_sha256"=>req["source_native_request_sha256"],
                "source_request"=>req["input_bindings"]["native_request"],"source_complete"=>req["input_bindings"]["native_complete"],
                "response_fields_unmodified"=>true,"cost_scope"=>"Original execution_seconds retained; no new drift")
            K.save_record(path,row,requestsha);imports+=1
            endpoint=G.E.readjson(joinpath(G.ROOT,p["source_diagnostic"]["ref"]))["endpoint_identity"]
        else
            drifts+=1;check(drifts<=374,"New drift bound exceeded")
            row,reused=K.checkpoint_injection(sim,cfg,p["contact_ids"]...,p["position_mm"],500.,path,requestsha)
            check(!reused && row["status"]!="excluded_geometry","Preflight/capture geometry changed or prior attempt exists")
            endpoint=endpoint_identity(sim,row)
        end
        diagnostic=p["record_ref"]*".diagnostic.json"
        fresh(joinpath(out,diagnostic),Dict("status"=>row["status"],"valid"=>row["valid"],"endpoint_identity"=>endpoint,
            "reused_source"=>imported,"capture_and_store_seconds"=>time()-tick,
            "native_injection_seconds_this_attempt"=>imported ? 0. : row["execution_seconds"],"process_peak_rss_bytes"=>Sys.maxrss()))
        push!(rows,Dict("record_ref"=>p["record_ref"],"record_sha256"=>G.hashfile(path),"diagnostic_ref"=>diagnostic,
            "diagnostic_sha256"=>G.hashfile(joinpath(out,diagnostic)),"status"=>row["status"],"valid"=>row["valid"],"reused_source"=>imported))
        statuses[row["status"]]=get(statuses,row["status"],0)+1
    end
    check(imports==4 && drifts==374,"Fixed bank import/drift census changed")
    fresh(joinpath(out,"COMPLETE.json"),Dict("status"=>"completed_fixed80_native_grid_near_bank","request_sha256"=>requestsha,
        "preflight_sha256"=>G.hashfile(joinpath(out,"preflight.json")),"points"=>rows,"statuses"=>statuses,
        "new_drift_calls"=>drifts,"reused_records"=>imports,"native_failures"=>get(statuses,"native_failed",0),
        "new_field_solves"=>0,"new_transport_calls"=>0,"automatic_retry"=>false,
        "scope"=>"Processing completion for fixed native-grid-near support; failures retain null signals. No imaging or detector validation."))
    true
end
check(length(ARGS)==2,"Pass request and new result directory")
try
    main(ARGS[1],ARGS[2]) || exit(2)
catch err
    fresh(joinpath(ARGS[2],"failure.json"),Dict("status"=>"failed_stop_preserve_partial","error"=>sprint(showerror,err),
        "exception_type"=>string(typeof(err)),"automatic_retry"=>false))
    rethrow()
end
'''


@cache
def native_axis(tick):
    """Use the existing mm interface; retain its nearest Float32 result and offset."""
    mm=float(tick)*1000;actual=N.native_position([mm,0.,0.])[0]
    offset=actual-tick;ulp=abs(float(np.spacing(np.float32(tick))))
    # Only affected coordinates need the adjacent-input check. Ties retain the
    # direct tick*1000 input; no target waveform enters this coordinate choice.
    if offset:
        m=np.float32(mm)
        neighbors=[np.nextafter(m,np.float32(direction)) for direction in (-np.inf,np.inf)]
        W.require(all(abs(float(v/np.float32(1000))-tick)>=abs(offset) for v in neighbors),
            'Direct millimetre input is not the nearest representable native coordinate.')
    return mm,actual,offset,offset/ulp


def plan(axes,validation,imports):
    points={};targets=[]
    for target in validation:
        native=N.native_position(target['position_mm']);bounds=[]
        for ticks,value in zip(axes,native):
            i=bisect.bisect_left(ticks,value)
            W.require(i<len(ticks) and (i>0 or ticks[i]==value),'Target outside original native grid.')
            requested=[value] if ticks[i]==value else ticks[i-1:i+1]
            actual=[native_axis(t)[1] for t in requested]
            if len(actual)==1:
                W.require(value==actual[0],'Exact target tick is not representable through the original interface.')
                bounds.append([(requested[0],actual[0],1.)])
            else:
                f=(value-actual[0])/(actual[1]-actual[0]);W.require(0<f<1,'Target outside actual support cell.')
                bounds.append([(requested[0],actual[0],1-f),(requested[1],actual[1],f)])
        weights=[]
        for corner in itertools.product(*bounds):
            requested=tuple(v[0] for v in corner);actual=tuple(v[1] for v in corner)
            parts=[native_axis(v) for v in requested]
            point={'contact_ids':target['contact_ids'],'position_mm':[v[0] for v in parts],
                'requested_grid_position_m':list(requested),'native_position_m':list(actual),
                'grid_deviation_m':[v[2] for v in parts],'grid_deviation_ulps':[v[3] for v in parts],
                'exact_native_grid':all(v[2]==0 for v in parts)}
            if actual in points:W.require(points[actual]==point,'Shared native support has inconsistent contact assignment.')
            else:points[actual]=point
            weights.append((actual,float(np.prod([v[2] for v in corner]))))
        w=np.array([v[1] for v in weights]);coords=np.array([v[0] for v in weights])
        W.require(np.all(w>0) and abs(w.sum()-1)<1e-15 and np.max(np.abs(w@coords-native))<1e-17,
            'Native support weights fail partition or affine reproduction.')
        targets.append({'reference_record_ref':target['record_ref'],'position_mm':target['position_mm'],
            'native_position_m':native,'contact_ids':target['contact_ids'],'lateral_offset_pitch_fraction':target['lateral_offset_pitch_fraction'],
            'source_record':{'ref':N.SOURCE+'/results/'+target['record_ref'],'sha256':target['record_sha256']},
            'source_diagnostic':{'ref':N.SOURCE+'/results/'+target['diagnostic_ref'],'sha256':target['diagnostic_sha256']},
            'support_kind':'exact_support' if all(points[v[0]]['exact_native_grid'] for v in weights) else 'rounded_support',
            '_weights':weights})
    rows=[];refs={}
    for i,(actual,point) in enumerate(sorted(points.items()),1):
        point['record_ref']=f'injections/point-{i:04}.json';refs[actual]=point['record_ref']
        if actual in imports:point.update(imports[actual])
        rows.append(point)
    for target in targets:
        target['training_weights']=[{'record_ref':refs[xyz],'weight':weight} for xyz,weight in target.pop('_weights')]
    return rows,targets


def prepare():
    native=(ROOT/N.REQUEST).parent;source=ROOT/N.SOURCE;results=source/'results'
    previous=W.read(native/'request.json');pre=W.read(native/'results/preflight.json');complete=W.read(native/'results/COMPLETE.json')
    old=W.read(source/'request.json');lateral=W.read(results/'COMPLETE.json')
    W.require(W.sha(native/'results/COMPLETE.json')==PILOT_COMPLETE_SHA and complete['request_sha256']==W.sha(native/'request.json') and
        W.sha(native/'results/preflight.json')==complete['preflight_sha256'] and pre['status']=='accepted_zero_drifts' and
        W.sha(results/'COMPLETE.json')==N.COMPLETE_SHA and W.sha(source/'request.json')==lateral['request_sha256'],
        'Completed native/lateral source seals changed.')
    imports={}
    for item in complete['points']:
        path=native/'results'/item['record_ref'];checkpoint=W.read(path);row=checkpoint['payload'];diagnostic=native/'results'/item['diagnostic_ref']
        W.require(W.sha(path)==item['record_sha256'] and W.sha(diagnostic)==item['diagnostic_sha256'] and
            row['status']=='completed' and row['valid'] is True,'Saved four-corner reference changed.')
        imports[tuple(N.native_position(row['position_mm']))]={'source_record':P.binding(path),
            'source_diagnostic':P.binding(diagnostic),'source_payload_sha256':checkpoint['payload_sha256']}
    validation=lateral['validation_records']
    W.require(len(validation)==80 and len({p['record_ref'] for p in validation})==80,'Fixed80 validation census changed.')
    points,targets=plan(pre['weighting_axes_m'],validation,imports)
    W.require(len(points)==378 and sum('source_record' in p for p in points)==4 and
        sum(not p['exact_native_grid'] for p in points)==54,'Unique support/reuse/rounding census changed.')
    sources={ref:sha for ref,sha in old['source_file_sha256'].items() if ref.startswith('simulation/')}
    W.require(all(W.sha(ROOT/ref)==sha for ref,sha in sources.items()),'Pinned native sources changed.')
    sources.update({ref:W.sha(ROOT/ref) for ref in ('tools/gegi_full34_pilot.py','tools/gegi_native_cell_pilot.py',
        'tools/gegi_native_cell_bank.py','tools/gegi_lateral_forward_comparison.py','tools/gegi_lateral_timing_comparison.py',
        'tools/gegi_signal_reconstruction.py','tools/scenario_workflow.py')})
    bindings={name:P.binding(path) for name,path in {
        'native_request':native/'request.json','native_preflight':native/'results/preflight.json','native_complete':native/'results/COMPLETE.json',
        'native_runtime':native/'results/runtime.json','lateral_request':source/'request.json','lateral_complete':results/'COMPLETE.json',
        'lateral_identity':results/'identity.json','lateral_runtime':results/'runtime.json',
        'forward_comparison':results/'forward-comparison.json','timing_comparison':results/'timing-comparison.json'}.items()}
    req={key:previous[key] for key in ('model_ref','model_sha256','field_cache','field_precision_bits','numerics','channels','environment')}
    req.update(kind=KIND,status='prepared_not_executed',limits=LIMITS,points=points,targets=targets,injection_energy_keV=500.,
        source_native_request_sha256=complete['request_sha256'],input_bindings=bindings,source_file_sha256=sources,
        worker_sha256=hashlib.sha256(JULIA_WORKER.encode()).hexdigest(),memory_policy='measure_only_not_a_launch_or_stop_condition',
        random_seed=None,randomness='Fixed deterministic point injections; no random draws',
        coordinate_summary={'unique_support':378,'exact_support_points':324,'rounded_support_points':54,
            'target_support_counts':dict(Counter(t['support_kind'] for t in targets)),
            'max_absolute_offset_m':max(abs(v) for p in points for v in p['grid_deviation_m']),
            'max_absolute_offset_ulps':max(abs(v) for p in points for v in p['grid_deviation_ulps'])},
        cost_scale={'new_drifts':374,'previous_comparable_drifts':432,
            'previous_comparable_total_seconds':W.read(results/'runtime.json')['elapsed_seconds'],
            'previous_four_corner_total_seconds':W.read(native/'results/runtime.json')['elapsed_seconds'],
            'scope':'Measured prior executions, not a bank runtime prediction. One300s worker; no automatic retry.'},
        authorization='Supervisor preparation under owner resumed bounded repair; execution separate after source freeze.',
        scope='Native-grid-near support:54points differ by1Float32ULP through unchanged production mm interface. Weights use actual coordinates. Same80 independent saved calibration targets; no waveform-derived coordinate choices, fitting or imaging promotion.')
    path=ROOT/REQUEST;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():W.require(W.read(path)==req,'Existing native support bank request changed; preserve it.')
    else:
        with path.open('xb') as stream:stream.write(W.encoded(req)+b'\n')
    return {'status':'prepared_not_executed','request':str(path),'request_sha256':W.sha(path),'tool_sha256':W.sha(__file__),
        'worker_sha256':req['worker_sha256'],'limits':LIMITS,'coordinate_summary':req['coordinate_summary'],'cost_scale':req['cost_scale']}


def checked_request(digest):
    path=ROOT/REQUEST;req=W.read(path)
    W.require(W.sha(path)==digest and req['kind']==KIND and req['limits']==LIMITS and
        req['worker_sha256']==hashlib.sha256(JULIA_WORKER.encode()).hexdigest(),'Frozen support-bank request changed.')
    for ref,sha in req['source_file_sha256'].items():W.require(W.sha(ROOT/ref)==sha,'Pinned source changed: '+ref)
    bindings=list(req['input_bindings'].values())
    bindings.extend(p[key] for p in req['points'] if 'source_record' in p for key in ('source_record','source_diagnostic'))
    for b in bindings:W.require(W.sha(ROOT/b['ref'])==b['sha256'],'Pinned saved input changed: '+b['ref'])
    return path,req


def execute(digest):
    path,req=checked_request(digest)
    W.require(W.sha(req['environment']['julia_executable'])==req['environment']['julia_executable_sha256'],'Pinned Julia changed.')
    return P.launch(path,req,digest,JULIA_WORKER,STATUS)


METRICS=('max_channel_rms_keV','max_channel_normalized_rms','max_absolute_error_keV','collecting_max_rms_keV',
         'neighbor_max_rms_keV','collecting_max_absolute_error_keV','neighbor_max_absolute_error_keV')


def summary(rows):
    paired=[row for row in rows if row['status']=='compared'];metrics={}
    for key in METRICS:
        item={mode:L.describe([r['metrics'][mode][key] for r in paired]) for mode in ('native_grid_near','centre','trilinear','timewarp')}
        for mode in ('centre','trilinear','timewarp'):
            differences=[r['metrics']['native_grid_near'][key]-r['metrics'][mode][key] for r in paired]
            item['versus_'+mode]={'improved':sum(v<0 for v in differences),'worse':sum(v>0 for v in differences),'tied':sum(v==0 for v in differences)}
        metrics[key]=item
    return {'total':len(rows),'paired':len(paired),'unavailable':len(rows)-len(paired),'paired_metrics':metrics,
        'max_absolute_terminal_error_keV':max((r['max_absolute_terminal_error_keV'] for r in paired),default=None),
        'max_absolute_250ns_error_keV':max((r['max_absolute_250ns_error_keV'] for r in paired),default=None)}


def compare(digest):
    started=time.perf_counter();path,req=checked_request(digest);results=path.parent/'results';inputs={}
    def checked(file,sha=None):
        raw=file.read_bytes();actual=hashlib.sha256(raw).hexdigest();W.require(sha is None or actual==sha,'Capture input changed: '+str(file))
        inputs[file.relative_to(ROOT).as_posix()]=actual
        return json.loads(raw)
    complete=checked(results/'COMPLETE.json');pre=checked(results/'preflight.json',complete['preflight_sha256'])
    W.require(complete['status']==STATUS and complete['request_sha256']==digest and complete['new_drift_calls']==374 and
        complete['reused_records']==4 and len(complete['points'])==378 and pre['status']=='accepted_zero_drifts','Completed fixed378 support bank required.')
    bank={};endpoints={}
    for item,point in zip(complete['points'],req['points']):
        record=checked(results/item['record_ref'],item['record_sha256']);row=record['payload']
        W.require(record['identity_sha256']==digest and item['record_ref']==point['record_ref'] and
            row['position_mm']==point['position_mm'] and row['contact_ids']==point['contact_ids'] and row['injection_energy_keV']==500.,
            'Fixed support coordinate/identity changed.')
        wave,support=L.waveform(row);diag=checked(results/item['diagnostic_ref'],item['diagnostic_sha256'])
        bank[item['record_ref']]={'row':row,'wave':wave,'support':support}
        ep=diag['endpoint_identity'];endpoints[item['record_ref']]=None if ep is None else {key:ep[key] for key in (
            'max_absolute_terminal_identity_error_keV','max_absolute_terminal_ideal_contact_error_keV',
            'X_face_terminal_sum_minus_injection_keV','Y_face_terminal_sum_minus_injection_keV')}
    timing=W.read(ROOT/req['input_bindings']['timing_comparison']['ref'])
    baseline={r['reference_record_ref']:r for r in timing['records']}
    rows=[]
    for target in req['targets']:
        source=target['source_record'];record=checked(ROOT/source['ref'],source['sha256']);reference=record['payload']
        values,support=L.waveform(reference);corners=[bank[w['record_ref']] for w in target['training_weights']]
        unavailable=[{'record_ref':w['record_ref'],**corner['support']} for w,corner in zip(target['training_weights'],corners) if corner['wave'] is None]
        result={key:target[key] for key in ('reference_record_ref','position_mm','native_position_m','contact_ids','lateral_offset_pitch_fraction','support_kind','training_weights')}
        result.update(status='unsupported' if unavailable or values is None else 'compared',reference_support=support,unavailable_corners=unavailable)
        diag=checked(ROOT/target['source_diagnostic']['ref'],target['source_diagnostic']['sha256'])
        ep=diag['endpoint_identity'];result['target_endpoint_identity']={key:ep[key] for key in (
            'max_absolute_terminal_identity_error_keV','max_absolute_terminal_ideal_contact_error_keV',
            'X_face_terminal_sum_minus_injection_keV','Y_face_terminal_sum_minus_injection_keV')}
        if result['status']=='compared':
            weights=[w['weight'] for w in target['training_weights']];prediction=sum(w*c['wave'] for w,c in zip(weights,corners))
            metric=L.error_metrics(prediction,values);compact=T.compact_metrics(metric,target['contact_ids']);delta=prediction-values
            terminal=sum(w*np.array([s['signed_induced_keV'][-1] for s in c['row']['channel_signals']]) for w,c in zip(weights,corners))
            terminal-=np.array([s['signed_induced_keV'][-1] for s in reference['channel_signals']])
            metrics={**baseline[target['reference_record_ref']]['metrics'],'native_grid_near':compact}
            result.update(metrics=metrics,channel_errors=[{**error,'terminal_error_keV':float(terminal[i]),
                'error_at250ns_keV':float(delta[i,-1])} for i,error in enumerate(metric['channels'])],
                differences_vs_baselines={mode:{key:compact[key]-metrics[mode][key] for key in METRICS} for mode in ('centre','trilinear','timewarp')},
                max_absolute_terminal_error_keV=float(np.max(np.abs(terminal))),max_absolute_250ns_error_keV=float(np.max(np.abs(delta[:,-1]))))
        rows.append(result)
    report={'kind':'gegi_fixed80_native_grid_near_forward_comparison_v1','request_sha256':digest,'input_sha256':inputs,
        'source_file_sha256':req['source_file_sha256'],'source_input_bindings':req['input_bindings'],
        'coordinate_summary':req['coordinate_summary'],'summary':summary(rows),
        'by_support_kind':{kind:summary([r for r in rows if r['support_kind']==kind]) for kind in ('exact_support','rounded_support')},
        'corner_endpoint_identities':endpoints,'records':rows,'elapsed_seconds':time.perf_counter()-started,
        'new_drifts':0,'new_field_solves':0,'new_transport_calls':0,'new_fit_calls':0,
        'definitions':{'coordinates':'Original grid ticks requested; actual injected Float32 mm/1000 positions retained.54support points have a1ULP X offset, quantified in request. No waveform-based coordinate choice.',
            'weights':'Trilinear tensor weights from actual injected bounds. Exact target axes use a single weight1 point; all weights fixed before reading validation waveforms.',
            'signals':'Same80 independent500keV injections; native signed all34 signals on unchanged0..250ns2ns grid and existing late-activity gate. No gain correction or time warp.',
            'evaluation':'All80 retained. Supported paired metrics include all/collecting/neighbor channels and terminal checks; unsupported references/corners remain explicit. Baseline errors are frozen saved centre/trilinear/timewarp outputs.',
            'scope':'Saved-data forward approximation only; no arbitrary acceptance threshold, fit, source truth input, imaging promotion or experimental validation.'}}
    with (results/'comparison.json').open('xb') as stream:stream.write(W.encoded(report)+b'\n')
    return {'output':str(results/'comparison.json'),'sha256':W.sha(results/'comparison.json'),'summary':report['summary'],
        'by_support_kind':report['by_support_kind'],'elapsed_seconds':report['elapsed_seconds']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--execute',action='store_true');mode.add_argument('--compare',action='store_true')
    parser.add_argument('--request-sha256');args=parser.parse_args()
    result=execute(args.request_sha256) if args.execute else compare(args.request_sha256) if args.compare else prepare()
    print(json.dumps(result,indent=2));raise SystemExit(0 if result.get('returncode',0)==0 else 1)
