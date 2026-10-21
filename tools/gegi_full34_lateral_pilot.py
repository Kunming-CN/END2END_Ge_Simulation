"""Prepare the fixed independent lateral-response pilot; never runs by default.

Four observable candidate pixels, 396 training records and 80 independent
validation records. Reuse 44 sealed centre responses; at most 432 new drifts.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json

import gegi_full34_pilot as P
from gegi_full34_pilot import W, ROOT

REQUEST = P.CALIBRATION+'/full34-lateral-pilot/request.json'
SOURCE = P.CALIBRATION+'/full34-bank/results'
SOURCE_COMPLETE_SHA = 'b107d0a1a715181c84f0313c1a311528c3e2efcd2ca3ccfbf928145348096821'
PIXELS = tuple(itertools.product((11,12),(24,26)))
TRAIN_XY = tuple(itertools.product((-.4,0.,.4),repeat=2))
VALID_XY = tuple(itertools.product((-.2,.2),repeat=2))
VALID_DEPTHS = (-4.5,-2.5,0.,2.5,4.5)
KIND = 'gegi_fixed_lateral_full34_reference_request_v1'
LIMITS = {'maximum_records':476,'training_records':396,'validation_records':80,
    'reused_centre_records':44,'maximum_new_checkpoint_attempts':432,'maximum_new_drift_calls':432,
    'maximum_total_wall_seconds':300,'julia_threads':1,'worker_processes':1,'automatic_retry':False}

# The same executed signal/endpoint helpers and bounded launcher as the pilot.
JULIA_WORKER = P.JULIA_WORKER.split('function main(reqpath,out)',1)[0] + r'''
function main(reqpath,out)
    req=G.E.readjson(reqpath);requestsha=G.hashfile(reqpath)
    check(Threads.nthreads()==1 && length(req["points"])==476,"Fixed lateral point/thread limit changed")
    check(G.E.environment()==req["environment"]["native"],"Original native environment changed")
    pkgroot=dirname(dirname(pathof(SSD)))
    for (ref,digest) in req["environment"]["SSD_science_source_sha256"]
        check(G.hashfile(joinpath(pkgroot,"src",ref))==digest,"Installed SSD science source changed")
    end
    cfg=(; (Symbol(k)=>v for (k,v) in req["numerics"])...)
    report=Dict{String,Any}();tick=time()
    sim=G.load_fields(Dict("field_cache"=>req["field_cache"]),joinpath(G.ROOT,req["model_ref"]),out,cfg,report)
    check(report["fields"]["mode"]=="explicit_exact_model_cache" && report["fields"]["solve_seconds"]==0,"No new field solve permitted")
    check(8sizeof(SSD.get_precision_type(sim))==req["field_precision_bits"] &&
        sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel &&
        G.H.channel_metadata(sim.config_dict)==req["channels"],"Original field/contact state changed")
    fresh(joinpath(out,"startup.json"),Dict("field_load_seconds"=>time()-tick,"fields"=>report["fields"],
        "startup_seconds_including_worker_imports"=>time()-parse(Float64,ENV["GEGI_FULL34_STARTED_UNIX"]),
        "process_peak_rss_bytes"=>Sys.maxrss()))
    fresh(joinpath(out,"identity.json"),Dict("kind"=>"gegi_full34_lateral_reference_identity_v1",
        "request_ref"=>req["request_ref"],"request_sha256"=>requestsha,"source_bank"=>req["source_bank"],
        "model_sha256"=>req["model_sha256"],"field_cache"=>req["field_cache"],"numerics"=>req["numerics"],
        "channels"=>req["channels"],"injection_energy_keV"=>500.,"signal_coverage"=>K.signal_coverage(),
        "point_plan_sha256"=>K.digest(req["points"]),"source_file_sha256"=>req["source_file_sha256"],
        "random_seed"=>nothing,"randomness"=>"Fixed independent deterministic injections; no random draws",
        "scope"=>"Independent lateral forward-reference pilot. All four observable pairings; no real-event truth position or energy input. No imaging/hardware validation."))
    identitysha=G.hashfile(joinpath(out,"identity.json"));train=Any[];validation=Any[]
    attempted=0;drifts=0;reused=0;statuses=Dict{String,Int}()
    for (i,p) in enumerate(req["points"])
        if time()>=parse(Float64,ENV["GEGI_FULL34_DEADLINE_UNIX"])
            fresh(joinpath(out,"PARTIAL.json"),Dict("status"=>"checkpointed_budget_stop","completed_records"=>i-1,
                "new_checkpoint_attempts"=>attempted,"new_drift_calls"=>drifts,"reused_records"=>reused,"automatic_retry"=>false))
            return false
        end
        path=joinpath(out,p["record_ref"]);tick=time()
        G.save(joinpath(out,"progress.json"),Dict("status"=>"record_running","point_index"=>i,
            "role"=>p["role"],"record_ref"=>p["record_ref"],"completed_records"=>i-1,"new_checkpoint_attempts"=>attempted))
        imported=haskey(p,"source_record")
        if imported
            source=p["source_record"]
            row=K.read_record(joinpath(G.ROOT,source["ref"]),req["source_bank"]["identity"]["sha256"])
            check(K.digest(row)==p["source_payload_sha256"] && row["status"]=="completed" && row["valid"] &&
                row["contact_ids"]==p["contact_ids"] && row["position_mm"]==p["position_mm"] &&
                row["signal_coverage"]==K.signal_coverage(),"Sealed centre response changed")
            row["response_origin"]=Dict("mode"=>"imported_saved_full34_response","source_record"=>source,
                "source_identity_sha256"=>req["source_bank"]["identity"]["sha256"],
                "source_payload_sha256"=>p["source_payload_sha256"],"source_complete"=>req["source_bank"]["complete"],
                "response_fields_unmodified"=>true,"cost_scope"=>"Original execution_seconds retained; this attempt performs no drift.")
            reused+=1
        else
            attempted+=1;check(attempted<=432,"New lateral attempt bound exceeded")
            row,was_reused=K.checkpoint_injection(sim,cfg,p["contact_ids"]...,p["position_mm"],500.,path,identitysha)
            check(!was_reused,"No existing lateral attempt may be silently reused or overwritten")
            drifts+=row["status"]!="excluded_geometry"
        end
        row["reference_role"]=p["role"];row["lateral_offset_pitch_fraction"]=p["lateral_offset_pitch_fraction"]
        K.save_record(path,row,identitysha)
        captured=time()-tick;diagnostic_started=time();endpoint=endpoint_identity(sim,row)
        diagnostic=p["record_ref"]*".diagnostic.json"
        fresh(joinpath(out,diagnostic),Dict("record_ref"=>p["record_ref"],"reference_role"=>p["role"],
            "status"=>row["status"],"valid"=>row["valid"],"reused_source"=>imported,"endpoint_identity"=>endpoint,
            "capture_and_store_seconds"=>captured,"endpoint_diagnostic_seconds"=>time()-diagnostic_started,
            "native_injection_seconds_this_attempt"=>imported ? 0. : row["execution_seconds"],
            "max_signal_time_ns"=>row["channel_signals"]===nothing ? nothing : maximum(last(s["time_ns"]) for s in row["channel_signals"]),
            "process_peak_rss_bytes"=>Sys.maxrss()))
        item=Dict("record_ref"=>p["record_ref"],"record_sha256"=>G.hashfile(path),"diagnostic_ref"=>diagnostic,
            "diagnostic_sha256"=>G.hashfile(joinpath(out,diagnostic)),"contact_ids"=>p["contact_ids"],
            "position_mm"=>p["position_mm"],"lateral_offset_pitch_fraction"=>p["lateral_offset_pitch_fraction"],
            "status"=>row["status"],"valid"=>row["valid"],"reused_source"=>imported)
        push!(p["role"]=="train" ? train : validation,item)
        statuses[row["status"]]=get(statuses,row["status"],0)+1
    end
    check(length(train)==396 && length(validation)==80 && reused==44 && attempted==432 && drifts<=432,"Lateral completion census changed")
    fresh(joinpath(out,"COMPLETE.json"),Dict("status"=>"completed_fixed_lateral_full34_reference_pilot",
        "request_ref"=>req["request_ref"],"request_sha256"=>requestsha,"identity_sha256"=>identitysha,
        "source_bank"=>req["source_bank"],"source_file_sha256"=>req["source_file_sha256"],
        "training_records"=>train,"validation_records"=>validation,"counts"=>Dict("training"=>396,"validation"=>80,
            "reused_records"=>reused,"new_checkpoint_attempts"=>attempted,"new_drift_calls"=>drifts,"statuses"=>statuses),
        "new_field_solves"=>0,"new_transport_calls"=>0,"automatic_retry"=>false,
        "scope"=>"Processing completion only. Per-record invalid/excluded/failed status and null quantities are preserved. Forward lateral references, not image recovery or detector validation."))
    true
end
check(length(ARGS)==2,"Pass request and new result directory")
try
    main(ARGS[1],ARGS[2]) || exit(2)
catch err
    fresh(joinpath(ARGS[2],"failure.json"),Dict("status"=>"failed_stop_preserve_partial","error"=>sprint(showerror,err),"automatic_retry"=>false))
    rethrow()
end
'''


def points(identity):
    channels=identity['channels'];rows=[]
    W.require(identity['depth_mm']==list(range(-5,6)), 'Original 11-depth reference grid changed.')
    for role,offsets,depths in (('train',TRAIN_XY,identity['depth_mm']),('validation',VALID_XY,VALID_DEPTHS)):
        for x,y in PIXELS:
            xc=channels[x-1]['strip_center_mm'];yc=channels[y-1]['strip_center_mm']
            px=channels[x]['strip_center_mm']-xc;py=channels[y]['strip_center_mm']-yc
            W.require(px>0 and py>0,'Original adjacent-strip pitches must be positive.')
            for oi,(fx,fy) in enumerate(offsets,1):
                for zi,z in enumerate(depths,1):
                    item={'role':role,'record_ref':f'{role}/{x}-{y}/xy{oi}-z{zi}.json','contact_ids':[x,y],
                        'position_mm':[xc+fx*px,yc+fy*py,z],'lateral_offset_pitch_fraction':[fx,fy],
                        'strip_pitch_mm':[px,py]}
                    if role=='train' and fx==fy==0.:item['source_centre_ref']=f'injections/{x}-{y}/z{zi}.json'
                    rows.append(item)
    train={tuple(p['position_mm']) for p in rows if p['role']=='train'}
    validation={tuple(p['position_mm']) for p in rows if p['role']=='validation'}
    W.require(len(rows)==476 and len(train)==396 and len(validation)==80 and not train&validation and
        sum('source_centre_ref' in p for p in rows)==44 and len({p['record_ref'] for p in rows})==476,
        'Fixed lateral census, centre reuse or independent validation changed.')
    return rows


def prepare():
    source=ROOT/SOURCE;bank=source/'bank';complete=W.read(source/'COMPLETE.json')
    verify=W.read(source/'verification.json');identity=W.read(bank/'identity.json');run=W.read(bank/'run.json')
    W.require(W.sha(source/'COMPLETE.json')==SOURCE_COMPLETE_SHA and
        complete['status']=='completed_original_grid_full34_bank' and complete['selected_pair_mismatches']==0 and
        verify['status']=='verified_original_grid_full34_bank' and verify['complete_sha256']==SOURCE_COMPLETE_SHA and
        verify['all_record_file_hashes_verified']==2991,'Verified source full34 bank changed.')
    W.require(W.sha(bank/'run.json')==complete['bank_run_sha256'] and
        W.sha(source/'identity.json')==complete['bundle_identity_sha256'] and
        W.sha(source/'validation.jsonl')==complete['validation_sha256'],'Source bank seal changed.')
    for ref in ('identity.json','depth-calibration.json','depth-diagnostics.json'):
        W.require(W.sha(bank/ref)==run['artifacts'][ref],'Sealed source bank artifact changed: '+ref)
    plan=points(identity);wanted={p['source_centre_ref'] for p in plan if 'source_centre_ref' in p};seals={}
    for line in (source/'validation.jsonl').read_text(encoding='utf-8').splitlines():
        value=json.loads(line)
        if value['record_ref'] in wanted:seals[value['record_ref']]=value['record_sha256']
    W.require(set(seals)==wanted,'Source centre records absent from sealed validation manifest.')
    for p in plan:
        if 'source_centre_ref' not in p:continue
        ref=p.pop('source_centre_ref');path=bank/ref;record=W.read(path);row=record['payload']
        W.require(W.sha(path)==seals[ref] and record['identity_sha256']==W.sha(bank/'identity.json') and
            row['position_mm']==p['position_mm'] and row['contact_ids']==p['contact_ids'] and
            row['injection_energy_keV']==500. and row['status']=='completed' and row['valid'] is True and
            row['signal_coverage']==identity['signal_coverage'] and
            [s['contact_id'] for s in row['channel_signals']]==list(range(1,35)), 'Sealed centre import changed: '+ref)
        p.update(source_record=P.binding(path),source_payload_sha256=record['payload_sha256'])
    original_request=source.parent/'request.json';native=W.read(original_request)
    W.require(W.sha(original_request)==complete['request_sha256'] and
        all(native[k]==identity[k] for k in ('field_cache','numerics','channels','field_precision_bits')),
        'Source bank inputs differ from its recorded request.')
    sources={ref:W.sha(ROOT/ref) for ref in native['input_file_sha256'] if ref.startswith('simulation/')}
    W.require(all(digest==native['input_file_sha256'][ref] for ref,digest in sources.items()),'Original native source changed.')
    sources.update({ref:W.sha(ROOT/ref) for ref in ('tools/gegi_full34_pilot.py','tools/gegi_full34_lateral_pilot.py')})
    source_bank={'root_ref':str(bank.relative_to(ROOT).as_posix()),'identity':P.binding(bank/'identity.json'),
        'complete':P.binding(source/'COMPLETE.json'),'verification':P.binding(source/'verification.json'),
        'validation_manifest':P.binding(source/'validation.jsonl'),'request':P.binding(original_request)}
    req={k:native[k] for k in ('model_ref','model_sha256','field_cache','field_precision_bits','numerics','channels','environment')}
    req.update(kind=KIND,request_ref=REQUEST,status='prepared_not_executed',limits=LIMITS,points=plan,
        source_bank=source_bank,source_file_sha256=sources,injection_energy_keV=500.,
        memory_policy='measure_only_not_a_launch_or_stop_condition',worker_sha256=hashlib.sha256(JULIA_WORKER.encode()).hexdigest(),
        authorization='Owner bounded repair autonomy; supervisor launches this exact request separately.',
        coordinate_rule='Fixed Cartesian observable candidates X11/X12 by Y24/Y26. Centre plus listed pitch fractions using each local next-strip centre spacing; no real-event truth position or energy input.',
        measured_scale_evidence={'verification':P.binding(source/'verification.json'),'new_drifts':2709,
            'total_seconds':verify['elapsed_seconds'],'qualification':'Existing full-bank measurement only; no runtime promise for this distinct fixed pilot.'},
        scope='Independent lateral forward-basis coverage for all four competing observable pairings; separate training/validation, not image recovery.')
    destination=W.safe_path(ROOT,REQUEST);destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():W.require(W.read(destination)==req,'Existing lateral request changed; preserve it.')
    else:
        with destination.open('xb') as stream:stream.write(W.encoded(req)+b'\n')
    return {'status':'prepared_not_executed','request':str(destination),'request_sha256':W.sha(destination),'limits':LIMITS}


def execute(digest):
    path=W.safe_path(ROOT,REQUEST);req=W.read(path)
    W.require(W.sha(path)==digest and req['kind']==KIND and req['limits']==LIMITS and
        req['worker_sha256']==hashlib.sha256(JULIA_WORKER.encode()).hexdigest() and
        req['memory_policy']=='measure_only_not_a_launch_or_stop_condition','Fixed lateral request/source/budget changed.')
    for ref,expected in req['source_file_sha256'].items():W.require(W.sha(ROOT/ref)==expected,'Pinned source changed: '+ref)
    for value in req['source_bank'].values():
        if isinstance(value,dict):W.require(W.sha(ROOT/value['ref'])==value['sha256'],'Pinned source-bank input changed.')
    for p in req['points']:
        if 'source_record' in p:
            value=p['source_record'];W.require(W.sha(ROOT/value['ref'])==value['sha256'],'Source centre record changed.')
    W.require(W.sha(req['environment']['julia_executable'])==req['environment']['julia_executable_sha256'],'Pinned Julia changed.')
    return P.launch(path,req,digest,JULIA_WORKER,'completed_fixed_lateral_full34_reference_pilot')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--request-sha256');args=parser.parse_args()
    result=execute(args.request_sha256) if args.execute else prepare()
    print(json.dumps(result,indent=2));raise SystemExit(0 if result.get('returncode',0)==0 else 1)
