# Additive charge-only session adapter. Original native producers stay unchanged.
include("native_checkpoint_batch.jl")
module NativeGroups
using ..NativeCheckpointBatch, JSON, SHA, Serialization, Unitful, LinearAlgebra
const L=NativeCheckpointBatch;const V=L.V;const B=L.B;const N=L.N;const Q=L.Q;const G=L.G
const ROOT=Q.ROOT
check=L.check
function runtime()
    check(Threads.nthreads()==2 && VERSION==v"1.13.0","Pinned two-thread Julia1.13.0 required")
    BLAS.set_num_threads(1)
    drift=joinpath(dirname(pathof(N.SSD)),"ChargeDrift","ChargeDrift.jl")
    Dict("environment"=>Q.environment("cpu"),"threads"=>Threads.nthreads(),"blas_threads"=>BLAS.get_num_threads(),
        "boundary_native_sha256"=>L.hashfile(drift),"worker_source"=>realpath(@__FILE__),
        "executable"=>realpath(joinpath(Sys.BINDIR,Base.julia_exename())))
end
function pins(plan)
    for (name,h) in plan["source_sha256"]
        check(!isabspath(name) && !(".." in splitpath(name)),"Unsafe source path")
        check(L.hashfile(joinpath(ROOT,name))==h,"Native source changed: "*name)
    end
    cache=joinpath(ROOT,plan["cache_file"])
    check(Q.childof(realpath(cache),realpath(joinpath(ROOT,".local"))),"Cache outside project local root")
    check(L.hashfile(cache)==plan["cache_sha256"],"Field cache changed")
end
function charge(sim,cfg,plan,g,loaded)
    e=plan["events"][g["event_index"]+1];group=g["group"];byrow=Dict(s["raw_row_index"]=>s for s in e["steps"])
    event=Dict("event_id"=>e["seed_event_id"],"primary_time_ns"=>group["origin_time_ns"],"steps"=>[byrow[i] for i in group["row_indices"]])
    settings=plan["settings"];started=time()
    # Same exact attempt boundary and original numerical helper as legacy batch.
    result=if settings["native_failure_policy"]=="record"
        guarded=G.attempt(()->B.native_attempt(()->N.native_event(event,sim,cfg,16,2609261),"record"))
        error=guarded.error===nothing ? guarded.result.error : guarded.error
        (native=error===nothing ? guarded.result.result : nothing,error=error)
    else
        (native=Base.invokelatest(N.native_event,event,sim,cfg,16,2609261),error=nothing)
    end
    native=result.native
    check(native===nothing || (all(isfinite,native.signal) && first(native.signal)==0),"Invalid cumulative charge")
    Dict("kind"=>"native_charge_group_v1","group"=>g,"runtime"=>loaded,
        "settings"=>settings,"cache_sha256"=>plan["cache_sha256"],"model_sha256"=>plan["model_sha256"],
        "readout_contact_id"=>cfg.contact,"units"=>plan["units"],"status"=>native===nothing ? "native_failed" : "native_completed",
        "native"=>native,"transport_flags"=>native===nothing ? nothing : N.flags(native.steps),
        "error"=>result.error,"readout"=>nothing,"native_seconds"=>time()-started,"field_solve_seconds"=>0)
end
function selection(plan,allow_primary_selection)
    ids=plan["selected_primary_ids"];events=plan["events"];groups=plan["groups"]
    check(plan["model"]=="AK02","Declared AK02 model")
    if !allow_primary_selection
        check(ids==[0,2594,3950] && !haskey(plan,"primary_selection_mode"),"Declared tiny AK02 cohort")
    elseif haskey(plan,"primary_selection_mode")
        check(plan["primary_selection_mode"]=="explicit","Explicit primary selection mode")
        check(!isempty(groups),"Zero-only selected native readout is unsupported")
    else
        check(ids==[0,2594,3950],"Declared default AK02 cohort")
    end
    integer(x)=x isa Integer && !(x isa Bool)
    check(1<=length(ids)<=8 && all(x->integer(x)&&0<=x<1000000,ids) &&
        length(unique(ids))==length(ids),"Unique bounded primary IDs")
    check(length(events)==length(ids) && [e["event_id"] for e in events]==ids,"Exact selected-event correspondence")
    check(length(groups)<=4 && sum((length(e["steps"]) for e in events);init=0)<=100,"Tiny complete-row/group caps")
    expected=[]
    for (index,e) in enumerate(events)
        check(e["namespace"]=="cs137-1m","Selected cs137-1m namespace")
        V.validate_event(e,plan["prepared"])
        for g in e["pulse_groups"];push!(expected,(index-1,e["event_id"],g));end
    end
    check(length(groups)==length(expected),"Full selected group census")
    for (g,(index,eid,pulse)) in zip(groups,expected)
        check(integer(g["event_index"]) && g["event_index"]==index && g["event_id"]==eid &&
            g["global_decay_id"]==eid && g["namespace"]=="cs137-1m" && g["group"]==pulse &&
            g["key"]=="AK02-e"*string(eid)*"-d"*string(eid)*"-g"*string(pulse["group_id"]),"Exact selected group/event correspondence")
    end
end
function session(file; output_base=joinpath(ROOT,".local","native-group-checkpoint-v1","implementation","outputs"),
        allow_primary_selection=false)
    check(isfile(file) && filesize(file)<=4*1024^2,"Bounded native session request")
    req=JSON.parsefile(file);check(req["kind"]=="native_charge_group_checkpoint_v1","Wrong native session kind")
    base=dirname(realpath(file));root=realpath(req["root"])
    check(Q.childof(base,joinpath(root,"attempts")) && Q.childof(root,output_base),"Native output boundary")
    plan=req["plan"];selection(plan,allow_primary_selection)
    pins(plan);loaded=runtime();check(loaded==req["runtime"],"Loaded runtime changed")
    expected=Dict("parcels"=>16,"seed_family"=>2609261,"drift_dt_ns"=>2,"drift_cap_ns"=>10000,
        "temperature_K"=>77,"diffusion"=>true,"end_drift_when_no_field"=>false,"self_repulsion"=>false,"geometry_check"=>true,
        "native_failure_policy"=>plan["settings"]["native_failure_policy"])
    check(plan["settings"]==expected && expected["native_failure_policy"] in ("abort","record"),"Frozen native settings")
    check(length(req["groups"])<=4 && all(g->g in plan["groups"],req["groups"]),"Unexpected native request groups")
    check(length(unique(g["key"] for g in req["groups"]))==length(req["groups"]),"Duplicate native request group")
    sim=deserialize(joinpath(ROOT,plan["cache_file"]))
    check(N.field_fingerprint(sim)==plan["expected_field_fingerprint"],"Cached field/grid differs")
    check(sim.detector.semiconductor.temperature==77,"Cached temperature changed")
    check(maximum(c.potential for c in sim.detector.contacts)-minimum(c.potential for c in sim.detector.contacts)==500,"Cached bias changed")
    B.geometry(plan["prepared"],sim,true)
    for e in plan["events"];B.R.validate_deposits(Dict("events"=>[e]),sim);end
    cfg=Q.parse_args(["--model","AK02","--position-mm","3,0,5","--precision","64","--dt-ns","2",
        "--min-grid-mm","0.05","--max-iterations","50000","--contact",string(plan["readout_contact_id"]),"--output",joinpath(base,"unused")])
    G.install!()
    for g in req["groups"]
        pins(plan);stage=joinpath(base,"charge-"*g["key"]);check(!ispath(stage),"Staged charge already exists");mkdir(stage)
        record=Base.invokelatest(charge,sim,cfg,plan,g,loaded)
        check(N.field_fingerprint(sim)==plan["expected_field_fingerprint"],"Native call mutated cached fields")
        L.save(joinpath(stage,"charge.json"),record)
        println(JSON.json(Dict("kind"=>"group_ready","key"=>g["key"],"directory"=>basename(stage))));flush(stdout)
        eof(stdin) && error("Driver closed before native commit acknowledgement; retained evidence")
        ack=JSON.parse(readline(stdin));check(ack==Dict("kind"=>"committed","key"=>g["key"]),"Bad native commit acknowledgement")
    end
    pins(plan);check(N.field_fingerprint(sim)==plan["expected_field_fingerprint"],"Final field fingerprint changed")
    println(JSON.json(Dict("kind"=>"session_done")));flush(stdout)
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    if ARGS==["--probe"];NativeGroups.JSON.print(stdout,NativeGroups.runtime());println()
    elseif length(ARGS)==2 && ARGS[1]=="--session";NativeGroups.session(ARGS[2])
    else;error("Usage: native_groups.jl --probe | --session FILE")
    end
end
