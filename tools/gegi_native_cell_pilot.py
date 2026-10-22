"""Prepare four fixed native-cell references; capture and compare only explicitly.

Reuses the frozen GeGI field cache, native calibration recorder and 300s launcher.
The saved-only comparison uses the existing independent calibration target.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import struct
import time

import numpy as np
import gegi_full34_pilot as P
import gegi_lateral_forward_comparison as L
import gegi_lateral_timing_comparison as T
from gegi_full34_pilot import ROOT, W

SOURCE = P.CALIBRATION+'/full34-lateral-pilot'
REQUEST = P.CALIBRATION+'/native-cell-pilot/request.json'
TARGET = 'validation/11-26/xy1-z3.json'
SUPPORT_SHA = '8091578765e0f02276727456a1671b0f4c923895976ea8fdc0c661c42dd3fb6f'
COMPLETE_SHA = '0843dd963ff851ab4c15c8abcb131521974832385d7ceeb2958fe41e2da18660'
KIND = 'gegi_fixed_four_native_cell_reference_request_v1'
CAPTURE_STATUS = 'completed_native_cell_capture'
LIMITS = {'maximum_new_drift_calls': 4, 'maximum_total_wall_seconds': 300,
          'julia_threads': 1, 'worker_processes': 1, 'automatic_retry': False}

JULIA_WORKER = P.JULIA_WORKER.split('function main(reqpath,out)',1)[0] + r'''
function main(reqpath,out)
    req=G.E.readjson(reqpath);requestsha=G.hashfile(reqpath)
    check(Threads.nthreads()==1 && length(req["points"])==4,"Fixed four points and one thread required")
    check(G.E.environment()==req["environment"]["native"],"Original native environment changed")
    pkgroot=dirname(dirname(pathof(SSD)))
    for (ref,digest) in req["environment"]["SSD_science_source_sha256"]
        check(G.hashfile(joinpath(pkgroot,"src",ref))==digest,"Installed SSD science source changed")
    end
    cfg=(; (Symbol(k)=>v for (k,v) in req["numerics"])...)
    report=Dict{String,Any}();tick=time()
    sim=G.load_fields(Dict("field_cache"=>req["field_cache"]),joinpath(G.ROOT,req["model_ref"]),out,cfg,report)
    check(report["fields"]["mode"]=="explicit_exact_model_cache" && report["fields"]["solve_seconds"]==0,"No field solve permitted")
    check(8sizeof(SSD.get_precision_type(sim))==32 &&
        sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel &&
        G.H.channel_metadata(sim.config_dict)==req["channels"],"Original field/contact state changed")
    fresh(joinpath(out,"startup.json"),Dict("field_load_seconds"=>time()-tick,"fields"=>report["fields"],
        "startup_seconds_including_worker_imports"=>time()-parse(Float64,ENV["GEGI_FULL34_STARTED_UNIX"]),
        "process_peak_rss_bytes"=>Sys.maxrss()))
    axesof(grid)=[Float64.(grid.axes[k].ticks) for k in 1:3]
    wpaxes=axesof(sim.weighting_potentials[1].grid);efaxes=axesof(sim.electric_field.grid)
    saved=G.E.readjson(joinpath(G.ROOT,req["saved_weighting_axes"]["ref"]))["grids"][1]
    wpchecks=[Dict("contact_id"=>id,"same_shape_and_every_axis_tick"=>
        axesof(sim.weighting_potentials[id].grid)==wpaxes) for id in 1:34]
    point(xyz)=SSD.CartesianPoint{Float32}((Float32.(xyz)./Float32(1000))...)
    coordinates(p)=[Float64(p.x),Float64(p.y),Float64(p.z)]
    corners=[begin
        p=point(item["position_mm"])
        Dict("point_index"=>i,"position_mm"=>item["position_mm"],"native_position_m"=>coordinates(p),
            "inside_semiconductor"=>p in sim.detector.semiconductor,
            "contact_ids"=>[c.id for c in sim.detector.contacts if p in c.geometry])
    end for (i,item) in enumerate(req["points"])]
    geometry_ok=all(c["inside_semiconductor"] && isempty(c["contact_ids"]) for c in corners)
    actual_native=[c["native_position_m"] for c in corners]
    expected_native=[p["native_position_m"] for p in req["points"]]
    axes_ok=all(v["same_shape_and_every_axis_tick"] for v in wpchecks) && wpaxes==saved["axis_ticks_m"] &&
        actual_native==expected_native
    targetnative=coordinates(point(req["target"]["position_mm"]))
    xi,yi=req["native_cell_lower_indices_zero_based"].+1
    ticks=Dict("x"=>wpaxes[1][xi:xi+1],"y"=>wpaxes[2][yi:yi+1])
    fractions=[(targetnative[k]-ticks[axis][1])/(ticks[axis][2]-ticks[axis][1]) for (k,axis) in enumerate(("x","y"))]
    fx,fy=fractions;weights=[(1-fx)*(1-fy),(1-fx)*fy,fx*(1-fy),fx*fy]
    expected_corners=[[x,y,0.] for x in ticks["x"] for y in ticks["y"]]
    axes_ok=axes_ok && actual_native==expected_corners && targetnative==req["target"]["native_position_m"] &&
        all(0 .< fractions .< 1) && isapprox(sum(weights),1.;atol=1e-15,rtol=0)
    fresh(joinpath(out,"preflight.json"),Dict("status"=>geometry_ok && axes_ok ? "accepted_zero_drifts" : "rejected_zero_drifts",
        "corners"=>corners,"all_corner_geometry_valid"=>geometry_ok,"saved_weighting_axes_and_corner_ticks_exact"=>axes_ok,
        "weighting_axes_m"=>wpaxes,"electric_field_axes_m"=>efaxes,"all34_weighting_grid_checks"=>wpchecks,
        "electric_field_vs_weighting_axis_exact"=>[efaxes[k]==wpaxes[k] for k in 1:3],
        "interpolation"=>Dict("target_native_position_m"=>targetnative,"cell_ticks_m"=>ticks,
            "fractions"=>fractions,"corner_weights"=>weights),"new_drift_calls"=>0))
    if !(geometry_ok && axes_ok)
        fresh(joinpath(out,"failure.json"),Dict("status"=>"preflight_rejected_zero_drifts","new_drift_calls"=>0,
            "error"=>"Fixed native-cell geometry or recorded axes mismatch; coordinates retained without relocation",
            "channel_signals"=>nothing,"endpoints"=>nothing,"automatic_retry"=>false))
        return false
    end
    rows=Any[];statuses=Dict{String,Int}()
    for (i,p) in enumerate(req["points"])
        check(time()<parse(Float64,ENV["GEGI_FULL34_DEADLINE_UNIX"]),"300 second budget reached before next injection")
        G.save(joinpath(out,"progress.json"),Dict("status"=>"injection_running","point_index"=>i,"completed_records"=>length(rows)))
        record=p["record_ref"];tick=time()
        row,reused=K.checkpoint_injection(sim,cfg,11,26,p["position_mm"],500.,joinpath(out,record),requestsha)
        check(!reused && row["status"]!="excluded_geometry","Preflight/capture geometry changed or prior attempt exists")
        captured=time()-tick;diagnostic=record*".diagnostic.json"
        fresh(joinpath(out,diagnostic),Dict("record_ref"=>record,"status"=>row["status"],"valid"=>row["valid"],
            "endpoint_identity"=>endpoint_identity(sim,row),"capture_and_checkpoint_seconds"=>captured,
            "native_injection_internal_seconds"=>row["execution_seconds"],"process_peak_rss_bytes"=>Sys.maxrss()))
        push!(rows,Dict("record_ref"=>record,"record_sha256"=>G.hashfile(joinpath(out,record)),
            "diagnostic_ref"=>diagnostic,"diagnostic_sha256"=>G.hashfile(joinpath(out,diagnostic)),
            "status"=>row["status"],"valid"=>row["valid"],"position_mm"=>p["position_mm"]))
        statuses[row["status"]]=get(statuses,row["status"],0)+1
    end
    fresh(joinpath(out,"COMPLETE.json"),Dict("status"=>"completed_native_cell_capture","request_sha256"=>requestsha,
        "preflight_sha256"=>G.hashfile(joinpath(out,"preflight.json")),"points"=>rows,"statuses"=>statuses,
        "new_drift_calls"=>4,"native_failures"=>get(statuses,"native_failed",0),
        "new_field_solves"=>0,"new_transport_calls"=>0,"automatic_retry"=>false,
        "scope"=>"Four independent deterministic 500keV references. Invalid/failed records retain null signals; processing completion is not physical validation."))
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


def native_position(xyz):
    f=lambda x: struct.unpack('<f',struct.pack('<f',x))[0]
    return [f(f(x)/f(1000)) for x in xyz]


def cell_weights(support):
    x,y=support['target']['x_cell'],support['target']['y_cell']
    fx=(x['native_coordinate_m']-x['lower_mm']/1000)/((x['upper_mm']-x['lower_mm'])/1000)
    fy=(y['native_coordinate_m']-y['lower_mm']/1000)/((y['upper_mm']-y['lower_mm'])/1000)
    weights=[(1-fx)*(1-fy),(1-fx)*fy,fx*(1-fy),fx*fy]
    W.require(0<fx<1 and 0<fy<1 and abs(sum(weights)-1)<1e-15,'Native-cell weight arithmetic changed.')
    return weights


def prepare():
    source=ROOT/SOURCE;results=source/'results';complete=W.read(results/'COMPLETE.json');old=W.read(source/'request.json')
    support=W.read(results/'grid-support.json')
    W.require(W.sha(results/'COMPLETE.json')==COMPLETE_SHA and W.sha(results/'grid-support.json')==SUPPORT_SHA and
        W.sha(source/'request.json')==complete['request_sha256'],'Frozen lateral support/request/completion changed.')
    target=next(p for p in complete['validation_records'] if p['record_ref']==TARGET)
    W.require(target['contact_ids']==[11,26] and target['position_mm']==support['target']['position_mm'] and
        target['lateral_offset_pitch_fraction']==[-.2,-.2] and target['position_mm'][2]==0.,'Fixed independent target changed.')
    for key,hashkey in (('record_ref','record_sha256'),('diagnostic_ref','diagnostic_sha256')):
        W.require(W.sha(results/target[key])==target[hashkey],'Independent target seal changed.')
    row=W.read(results/TARGET)['payload']
    W.require(row['status']=='completed' and row['valid'] is True and row['injection_energy_keV']==500. and
        row['signal_coverage']==L.R.ALL34_COVERAGE,'Independent full34 target unavailable.')
    axesbinding=support['input_bindings'][0];axes=W.read(ROOT/axesbinding['ref'])['grids'][0]['axis_ticks_m']
    W.require(W.sha(ROOT/axesbinding['ref'])==axesbinding['sha256'] and
        support['field_cache_sha256']==old['field_cache']['sha256'] and old['field_precision_bits']==32,'Saved native axes/cache changed.')
    xi=support['target']['x_cell']['lower_index_zero_based'];yi=support['target']['y_cell']['lower_index_zero_based']
    exact=[[x,y,0.] for x,y in itertools.product(axes[0][xi:xi+2],axes[1][yi:yi+2])]
    points=[{'record_ref':f'injections/corner-{i}.json','contact_ids':[11,26],'position_mm':xyz,
             'native_position_m':native_position(xyz)} for i,xyz in enumerate(support['four_native_XY_corners_mm'],1)]
    W.require(len(points)==4 and [p['native_position_m'] for p in points]==exact and
        len({tuple(p['position_mm']) for p in points})==4 and target['position_mm'] not in [p['position_mm'] for p in points],
        'Exactly four native-grid corners independent of target required.')
    sources={ref:digest for ref,digest in old['source_file_sha256'].items() if ref.startswith('simulation/')}
    W.require(all(W.sha(ROOT/ref)==digest for ref,digest in sources.items()),'Original native producer changed.')
    sources.update({ref:W.sha(ROOT/ref) for ref in ('tools/gegi_full34_pilot.py','tools/gegi_native_cell_pilot.py',
        'tools/gegi_lateral_forward_comparison.py','tools/gegi_lateral_timing_comparison.py',
        'tools/gegi_signal_reconstruction.py','tools/scenario_workflow.py')})
    refs=['request.json',*[f'results/{ref}' for ref in ('COMPLETE.json','identity.json','grid-support.json',TARGET,
        target['diagnostic_ref'],'forward-comparison.json','timing-comparison.json')]]
    inputs={ref:P.binding(source/ref) for ref in refs}
    req={k:old[k] for k in ('model_ref','model_sha256','field_cache','field_precision_bits','numerics','channels','environment')}
    req.update(kind=KIND,status='prepared_not_executed',limits=LIMITS,injection_energy_keV=500.,points=points,
        target={'record_ref':TARGET,'contact_ids':[11,26],'position_mm':target['position_mm'],
                'native_position_m':native_position(target['position_mm']),'lateral_offset_pitch_fraction':[-.2,-.2]},
        native_cell_lower_indices_zero_based=[xi,yi],expected_corner_weights=cell_weights(support),
        saved_weighting_axes=axesbinding,input_bindings=inputs,source_file_sha256=sources,
        worker_sha256=hashlib.sha256(JULIA_WORKER.encode()).hexdigest(),memory_policy='measure_only_not_a_launch_or_stop_condition',
        random_seed=None,randomness='Fixed deterministic point injections; no random draws',
        authorization='Owner resumed bounded repair 2026-10-22; supervisor launches frozen request separately.',
        scope='Four fixed native-grid corners; all geometry/axes checked before drift. Reuse-only original fields. No real-event/source inputs, new field solve, transport, fitting, gain correction or automatic retry.')
    path=ROOT/REQUEST;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():W.require(W.read(path)==req,'Existing native-cell request changed; preserve it.')
    else:
        with path.open('xb') as stream:stream.write(W.encoded(req)+b'\n')
    return {'status':'prepared_not_executed','request':str(path),'request_sha256':W.sha(path),
        'tool_sha256':W.sha(__file__),'worker_sha256':req['worker_sha256'],'points':points,'weights':req['expected_corner_weights']}


def checked_request(digest):
    path=ROOT/REQUEST;req=W.read(path)
    W.require(W.sha(path)==digest and req['kind']==KIND and req['limits']==LIMITS and
        req['worker_sha256']==hashlib.sha256(JULIA_WORKER.encode()).hexdigest(),'Frozen native-cell request changed.')
    for ref,sha in req['source_file_sha256'].items():W.require(W.sha(ROOT/ref)==sha,'Pinned source changed: '+ref)
    for binding in (*req['input_bindings'].values(),req['saved_weighting_axes']):
        W.require(W.sha(ROOT/binding['ref'])==binding['sha256'],'Pinned saved input changed: '+binding['ref'])
    return path,req


def execute(digest):
    path,req=checked_request(digest)
    W.require(W.sha(req['environment']['julia_executable'])==req['environment']['julia_executable_sha256'],'Pinned Julia changed.')
    return P.launch(path,req,digest,JULIA_WORKER,CAPTURE_STATUS)


def compare(digest):
    started=time.perf_counter();path,req=checked_request(digest);results=path.parent/'results';inputs={}
    def checked(file,sha=None):
        raw=file.read_bytes();actual=hashlib.sha256(raw).hexdigest()
        W.require(sha is None or actual==sha,'Capture artifact changed: '+str(file))
        inputs[file.relative_to(ROOT).as_posix()]=actual
        return json.loads(raw)
    complete=checked(results/'COMPLETE.json');preflight=checked(results/'preflight.json',complete['preflight_sha256'])
    W.require(complete['status']==CAPTURE_STATUS and complete['request_sha256']==digest and
        complete['new_drift_calls']==4 and preflight['status']=='accepted_zero_drifts' and len(complete['points'])==4,
        'Completed fixed four-corner capture required.')
    weights=preflight['interpolation']['corner_weights']
    W.require(np.allclose(weights,req['expected_corner_weights'],rtol=0,atol=1e-15),'Actual native-cell weights changed.')
    rows=[];values=[];diagnostics=[];unavailable=[]
    for item,point in zip(complete['points'],req['points']):
        record=checked(results/item['record_ref'],item['record_sha256']);row=record['payload']
        W.require(record['identity_sha256']==digest and item['record_ref']==point['record_ref'] and
            row['position_mm']==point['position_mm'] and row['contact_ids']==[11,26] and row['injection_energy_keV']==500.,
            'Captured fixed corner identity changed.')
        diag=checked(results/item['diagnostic_ref'],item['diagnostic_sha256']);wave,support=L.waveform(row)
        rows.append(row);values.append(wave);diagnostics.append(diag['endpoint_identity'])
        if wave is None:unavailable.append({'record_ref':item['record_ref'],**support})
    source=ROOT/SOURCE/'results';target=W.read(source/TARGET)['payload'];reference,support=L.waveform(target)
    report={'kind':'gegi_fixed_native_cell_forward_comparison_v1','request_sha256':digest,'input_sha256':inputs,
        'source_file_sha256':req['source_file_sha256'],'target':req['target'],'weights':weights,
        'status':'unsupported' if unavailable or reference is None else 'compared','unavailable_corners':unavailable,
        'reference_support':support,'corner_endpoint_identities':diagnostics,
        'target_endpoint_identity':W.read(source/(TARGET+'.diagnostic.json'))['endpoint_identity'],
        'new_drifts':0,'new_field_solves':0,'new_transport_calls':0,'new_fit_calls':0}
    if report['status']=='compared':
        prediction=sum(w*v for w,v in zip(weights,values));metrics=L.error_metrics(prediction,reference)
        forward=next(r for r in W.read(source/'forward-comparison.json')['records'] if r['reference_record_ref']==TARGET)
        timing=next(r for r in W.read(source/'timing-comparison.json')['records'] if r['reference_record_ref']==TARGET)
        baselines={mode:{'metrics':timing['metrics'][mode],'channels':forward[mode]['channels']}
            for mode in ('centre','trilinear')}
        baselines['timewarp']={'metrics':timing['metrics']['timewarp'],'channels':timing['timewarp_channel_errors']}
        terminal=sum(w*np.asarray([s['signed_induced_keV'][-1] for s in row['channel_signals']]) for w,row in zip(weights,rows))
        targetterminal=np.asarray([s['signed_induced_keV'][-1] for s in target['channel_signals']])
        compact=T.compact_metrics(metrics,[11,26]);delta=prediction-reference
        index,sample=np.unravel_index(int(np.argmax(np.abs(delta))),delta.shape)
        report.update(metrics=compact,channel_errors=metrics['channels'],baselines=baselines,
            differences_vs_baselines={mode:{key:compact[key]-base['metrics'][key] for key in compact} for mode,base in baselines.items()},
            max_absolute_terminal_error_keV=float(np.max(np.abs(terminal-targetterminal))),
            max_absolute_250ns_error_keV=float(np.max(np.abs(delta[:,-1]))),
            peak={'contact_id':int(index)+1,'kind':'collecting' if int(index)+1 in (11,26) else 'neighbor',
                  'time_ns':float(L.R.FIT_GRID_NS[sample]),'native_signed_error_keV':float(delta[index,sample])})
    report.update(elapsed_seconds=time.perf_counter()-started,
        definitions={'prediction':'Bilinear four-corner sum using actual native Float32 injection coordinates and weighting-grid ticks; no time warp or amplitude adjustment.',
            'support':'Unchanged fixed500keV and 0..250ns at2ns spacing; existing late-activity check and signed all34 metrics.',
            'evaluation':'One independent saved calibration target. Collectors11/26 and other32 neighbors reported separately. Endpoint algebra is diagnostic only.',
            'scope':'Saved-data forward comparison only; no fit, real-event truth, source reconstruction, imaging promotion or experimental validation.'})
    with (results/'comparison.json').open('xb') as stream:stream.write(W.encoded(report)+b'\n')
    return {'status':report['status'],'output':str(results/'comparison.json'),'sha256':W.sha(results/'comparison.json'),
        'metrics':report.get('metrics'),'elapsed_seconds':report['elapsed_seconds']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--execute',action='store_true');mode.add_argument('--compare',action='store_true')
    parser.add_argument('--request-sha256');args=parser.parse_args()
    result=execute(args.request_sha256) if args.execute else compare(args.request_sha256) if args.compare else prepare()
    print(json.dumps(result,indent=2));raise SystemExit(0 if result.get('returncode',0)==0 else 1)
