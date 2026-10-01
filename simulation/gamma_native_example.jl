# Gamma adapter only: frozen native/electronics numerical helpers stay unchanged.
include("native_response.jl")
include("native_boundary_guard.jl")
module GammaNativeExample
using ..NativeResponse, ..NativeBoundaryGuard, JSON, SHA, Serialization, Unitful, LinearAlgebra
const B=NativeResponse; const N=B.N; const R=B.R; const Q=B.Q; const E=B.E; const P=B.P
const G=NativeBoundaryGuard; const ROOT=Q.ROOT
const KIND="source_gamma_native_example_v1"
const MAX_REQUEST_BYTES=4*1024^2
const MAX_CACHE_BYTES=32*1024^2
const DETECTOR_PINS=Dict(
    "AK02"=>(model="793de4cc598a3e26d375525e683be1bc2072e117d1c6b8003f6cdcffc9925dfa",
        cache="2d5102499d30531d8ef6d03a79dc0bfe2f3c57e784457dc8d5da02ed53a670ac"),
    "SAP22"=>(model="614c72f31a5a84b82c69b0b11f6f0657e87d94f746312c151f9a08cd00ba3dc3",
        cache="39e8e121fcc696fad0686bac31710c53f28a2c7bc4102fdb57c70f6cb12dd804"))
const SETTINGS=Dict("parcels"=>16,"seed_family"=>2609261,"drift_dt_ns"=>2,
    "drift_cap_ns"=>10000,"temperature_K"=>77,"diffusion"=>true,
    "end_drift_when_no_field"=>false,"self_repulsion"=>false,"geometry_check"=>true)
check=E.check

function bounded_bytes(path,limit)
    check(isfile(path) && 0<filesize(path)<=limit,"Missing/oversized gamma consumed input")
    raw=open(io->read(io,limit+1),path)
    check(0<length(raw)<=limit,"Gamma consumed input changed size or exceeded bound")
    raw
end
function consumed_request(path;byte_reader=bounded_bytes)
    raw=byte_reader(path,MAX_REQUEST_BYTES)
    check(raw isa Vector{UInt8} && 0<length(raw)<=MAX_REQUEST_BYTES,"Bounded request byte buffer required")
    digest=bytes2hex(sha256(raw))
    # Parse exactly the bytes used for the report SHA, with no second file read.
    (document=JSON.parse(String(copy(raw))),sha256=digest)
end
function canonical_cache(request;resolve=realpath)
    model=request["model_id"];check(haskey(DETECTOR_PINS,model),"Gamma canonical cache detector")
    spec=DETECTOR_PINS[model];relative=".local/cs137-1m-native/cache/"*model*".jls"
    check(request["cache_file"]==relative,"Gamma cache must use canonical model-relative path")
    check(request["cache_sha256"]==spec.cache && request["model_sha256"]==spec.model,"Gamma canonical cache/model SHA")
    check(get(request["pins"],relative,nothing)==spec.cache &&
        get(request["pins"],"models/"*model*".yaml",nothing)==spec.model,"Gamma canonical cache/model must be pinned")
    root=resolve(ROOT);expected=normpath(joinpath(root,relative));path=resolve(expected)
    cache_root=resolve(joinpath(root,".local","cs137-1m-native","cache"))
    check(Q.childof(cache_root,root) && Q.childof(path,cache_root) &&
        Q.pathkey(path)==Q.pathkey(expected) && dirname(path)==cache_root,"Gamma canonical cache resolved outside its project location")
    path
end
function deserialize_verified(raw,expected;deserialize_fn=deserialize)
    check(raw isa Vector{UInt8} && 0<length(raw)<=MAX_CACHE_BYTES,"Bounded cache byte buffer required")
    check(bytes2hex(sha256(raw))==expected,"Gamma consumed cache bytes differ from canonical SHA")
    # The verified buffer is the deserializer's sole input, never a pathname.
    deserialize_fn(IOBuffer(raw))
end
function cache_from_request(request;byte_reader=bounded_bytes,resolve=realpath,deserialize_fn=deserialize)
    path=canonical_cache(request;resolve=resolve)
    raw=byte_reader(path,MAX_CACHE_BYTES)
    deserialize_verified(raw,request["cache_sha256"];deserialize_fn=deserialize_fn)
end

function typed_equal(a,b)
    if a isa AbstractDict && b isa AbstractDict
        return Set(keys(a))==Set(keys(b)) && all(typed_equal(a[k],b[k]) for k in keys(a))
    elseif a isa AbstractVector && b isa AbstractVector
        return length(a)==length(b) && all(typed_equal(x,y) for (x,y) in zip(a,b))
    end
    typeof(a)===typeof(b) && isequal(a,b)
end

function pins(request)
    for (name,h) in request["pins"]
        check(!isabspath(name) && !(".." in splitpath(name)),"Unsafe gamma pin")
        path=realpath(joinpath(ROOT,name))
        check(Q.childof(path,realpath(ROOT)) && E.hashfile(path)==h,"Gamma input/source changed: "*name)
    end
end
function runtime()
    check(VERSION==v"1.13.0" && Threads.nthreads() in (1,2),"Existing Julia1.13.0 with one or two threads required")
    BLAS.set_num_threads(1) # this child only
    exe=realpath(joinpath(Sys.BINDIR,Base.julia_exename()))
    drift=joinpath(dirname(pathof(N.SSD)),"ChargeDrift","ChargeDrift.jl")
    nf=first(methods(N.native_event)); pf=first(methods(P.process))
    nfile,nline=Base.functionloc(nf); pfile,pline=Base.functionloc(pf)
    check(realpath(string(nfile))==realpath(joinpath(@__DIR__,"native_li_example.jl")) &&
        realpath(string(pfile))==realpath(joinpath(@__DIR__,"readout_profiles.jl")),"Unexpected loaded numerical helper")
    Dict("environment"=>Q.environment("cpu"),"readout_environment"=>E.environment(),
        "threads"=>Threads.nthreads(),"blas_threads"=>BLAS.get_num_threads(),
        "executable"=>exe,"executable_sha256"=>E.hashfile(exe),
        "ssd_loaded"=>true,"ssd_source_sha256"=>E.hashfile(pathof(N.SSD)),
        "json_source_sha256"=>E.hashfile(pathof(JSON)),"native_drift_sha256"=>E.hashfile(drift),
        "native_module"=>string(N),"native_source"=>realpath(string(nfile)),"native_line"=>nline,
        "readout_module"=>string(P),"readout_source"=>realpath(string(pfile)),"readout_line"=>pline,
        "worker_source"=>realpath(@__FILE__))
end
function validate_request(d)
    check(d["kind"]==KIND && d["schema_version"]===1,"Gamma request kind/version")
    check(d["settings"]==SETTINGS && d["native_failure_policy"] in ("abort","record"),"Frozen gamma native settings/policy")
    model=d["model_id"]; check(model in ("AK02","SAP22"),"Gamma detector")
    ids=model=="AK02" ? [0,4,5] : [0,2,3]
    check(d["selected_ids"]==ids && d["radiation_primary_count"]===20,"Gamma fixed cohort/radiation census")
    events=d["events"]; check(length(events)==20 && [e["event_id"] for e in events]==collect(0:19),"Gamma full census")
    check(all(e->e["initial_primary_id"]==e["event_id"],events),"Gamma initial identity")
    zero=findfirst(e->e["zero_ge"],events); positive=findall(e->!e["zero_ge"],events)
    check(zero!==nothing && length(positive)>=2 && [zero-1,positive[1]-1,positive[2]-1]==ids,"Gamma cohort selected before outcomes")
    check(d["source_manifest"]["kind"]=="scenario_gamma_event_stream_v1" &&
        d["source_manifest"]["clock_policy"]=="synthetic_primary_time_zero" &&
        d["source_manifest"]["model_id"]==model,"Gamma source contract")
    for e in events
        check(length(e["vtx"])==1 && e["vtx"][1]["time"]==0 &&
            length(e["particles"])==1 && e["particles"][1]["particle"]===22,"Gamma clock/particle")
        check(e["zero_ge"]==(e["truth_ge_edep_keV"]==0) &&
            isapprox(sum((s["energy_keV"] for s in e["steps"]);init=0.),e["truth_ge_edep_keV"];atol=1e-9,rtol=1e-12),"Gamma truth/zero")
    end
    check(sum(length(events[i+1]["steps"]) for i in ids)<=100,"Gamma bounded whole-row cohort")
    profile=P.load(joinpath(@__DIR__,"native_readout_profile.json"))
    check(profile.sha256=="7556e6e77d6c21e76e1a4eabb69b2b26875517252c083c88b6eb6a80502ef6e6" &&
        E.hashfile(joinpath(@__DIR__,"readout_demo.json"))=="33eb64724736c78852795ea001889759152ffefc22de9c4db6815fd1aaf8ee9e","Frozen electronics inputs")
    P.validate_resolved(d["readout_config"],profile.profile,3)
    check(typed_equal(d["readout_config"],P.for_census(profile.profile,3)),"Generated gamma readout configuration value types changed")
    check(d["source_temperature_K"]===78 && d["cached_temperature_K"]===77 &&
        d["readout_contact_id"]===1 && d["bias_V"]==(model=="AK02" ? 500 : 700),"Gamma detector settings")
    d
end

# Only native_fn is inside the reviewed two-ArgumentError boundary. Tests inject
# every calculation function; no cache, native drift or electronics is needed.
function event_response(event,policy,native_fn,process_fn,flags_fn)
    id=event["initial_primary_id"]
    base=Dict{String,Any}("initial_primary_id"=>id,"event_id"=>event["event_id"],
        "primary_time_ns"=>0.0,"clock_policy"=>"synthetic_primary_time_zero",
        "truth_ge_edep_keV"=>event["truth_ge_edep_keV"],"zero_ge"=>event["zero_ge"],
        "raw_row_indices"=>[s["raw_row_index"] for s in event["steps"]],
        "deposition_delays_ns"=>[s["time_ns"] for s in event["steps"]],
        "parcel_seed_rule"=>"sha256(seed_family/event_id/raw_row_index/parcel_index), first8bytes big-endian UInt64",
        "parcel_seeds"=>[Dict("raw_row_index"=>s["raw_row_index"],"parcels"=>[
            Dict("parcel_index"=>i,"seed_uint64_decimal"=>string(N.parcel_seed(2609261,id,s["raw_row_index"],i)))
            for i in 1:16]) for s in event["steps"] if s["energy_keV"]>0],
        "native"=>nothing,"transport_flags"=>nothing,"readout"=>nothing,"error"=>nothing,
        "native_seconds"=>0.0,"electronics_seconds"=>0.0,"field_solve_seconds"=>0.0)
    if event["zero_ge"]
        # Known absence of deposited charge; this is not an SSD drift waveform.
        base["status"]="native_not_applicable_true_zero"
        base["charge_input_origin"]="known_zero_deposited_charge_no_native_drift"
        t=[0.,2.]; q=[0.,0.]
    else
        started=time(); attempt=B.native_attempt(native_fn,policy);base["native_seconds"]=time()-started
        if attempt.error!==nothing
            base["status"]="native_failed";base["error"]=attempt.error
            base["endpoint_details_note"]=B.ENDPOINT_UNAVAILABLE
            base["charge_input_origin"]=nothing;base["charge_input"]=nothing
            base["final_induced_keV"]=nothing;base["charge_end_ns"]=nothing
            return base
        end
        native=attempt.result;t=native.times;q=native.signal
        check(all(isfinite,q) && first(q)==0,"Invalid gamma signed cumulative charge")
        base["status"]="native_completed";base["charge_input_origin"]="unchanged_native_weighted_signed_signal"
        base["native"]=Dict("times"=>t,"signal"=>q,"steps"=>native.steps)
        base["transport_flags"]=flags_fn(native.steps)
    end
    base["charge_input"]=Dict("time_since_initial_primary_ns"=>t,"induced_equivalent_energy_keV"=>q)
    base["final_induced_keV"]=last(q);base["charge_end_ns"]=last(t)
    started=time();base["readout"]=process_fn(t,q);base["electronics_seconds"]=time()-started
    check(base["readout"]["current_balance"]["passed"],"Gamma current/charge balance failed")
    base
end
function selected_response(request,sim,cfg,c,eion,cal,M; native_fn=N.native_event,
        process_fn=(t,q)->P.process(t,q,c,eion,cal,M),flags_fn=N.flags,after_native=()->nothing)
    cases=Any[]
    for id in request["selected_ids"]
        event=request["events"][id+1]
        native_input=Dict("event_id"=>id,"primary_time_ns"=>0.,"steps"=>event["steps"])
        response=event_response(event,request["native_failure_policy"],
            ()->Base.invokelatest(native_fn,native_input,sim,cfg,16,2609261),process_fn,flags_fn)
        after_native();push!(cases,response)
    end
    cases
end
function save(path,value)
    check(!ispath(path),"Gamma output already exists: "*path)
    E.save(path,value)
end
function worker(input,output)
    input=realpath(input);output=realpath(output)
    check(Q.childof(input,realpath(joinpath(ROOT,".local","m11c-gamma-native-v1"))) &&
        Q.childof(output,realpath(joinpath(ROOT,".local","m11c-gamma-native-v1"))) &&
        dirname(input)==output,"Gamma worker output boundary")
    consumed=consumed_request(input);d=validate_request(consumed.document)
    canonical_cache(d);pins(d);model=d["model_id"]
    report=Dict{String,Any}("kind"=>KIND,"schema_version"=>1,"status"=>"running",
        "model_id"=>model,"request_sha256"=>consumed.sha256,"settings"=>SETTINGS,
        "native_failure_policy"=>d["native_failure_policy"],"selected_ids"=>d["selected_ids"],
        "radiation_primary_count"=>20,"selected_readout_count"=>3,"cases"=>Any[],
        "calibration_calls"=>0,"native_calls"=>0,"field_solve_seconds"=>0.0)
    stage="runtime";started=time()
    try
        report["runtime"]=runtime();check(report["runtime"]["threads"]==d["threads"],"Gamma requested threads")
        check(report["runtime"]["executable_sha256"]==d["julia_executable_sha256"],"Gamma executable changed")
        stage="cache_validation";sim=cache_from_request(d)
        fingerprint=N.field_fingerprint(sim);check(fingerprint==d["expected_field_fingerprint"],"Gamma cached field/grid mismatch")
        check(sim.detector.semiconductor.temperature==77,"Gamma cached temperature")
        contacts=sort([Dict("id"=>c.id,"potential_V"=>c.potential) for c in sim.detector.contacts];by=c->c["id"])
        check(contacts==d["source_manifest"]["stored_contacts"],"Gamma cached contact potentials/IDs")
        report["geometry"]=B.geometry(d["prepared"],sim,true)
        R.validate_deposits(Dict("events"=>[d["events"][i+1] for i in d["selected_ids"]]),sim)
        report["field_fingerprint_before"]=fingerprint
        report["detector_settings"]=Dict(k=>d[k] for k in ("source_temperature_K","cached_temperature_K","bias_V","readout_contact_id","cache_sha256","model_sha256"))
        report["guard"]=G.install!()
        cfg=Q.parse_args(["--model",model,"--position-mm","3,0,5","--precision","64","--dt-ns","2",
            "--min-grid-mm","0.05","--max-iterations","50000","--contact","1","--output",joinpath(output,"unused")])
        c=d["readout_config"];eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation)
        check(eion==2.95,"Gamma ionisation energy changed");M=E.transition(c,2.)
        stage="independent_injection_calibration";calstart=time();report["calibration_calls"]+=1
        cal=P.calibration(c,eion,2.,M)
        check(cal==d["expected_calibration"],"Gamma independent injection calibration differs from frozen reference")
        report["calibration_seconds"]=time()-calstart;report["calibration"]=cal
        report["readout_config"]=c;report["ionisation_energy_eV"]=eion
        stage="native_and_electronics"
        native_fn=(event,sim,cfg,n,seed)->begin
            pins(d);report["native_calls"]+=1;N.native_event(event,sim,cfg,n,seed)
        end
        # Save each completed selected event so unexpected later failures retain
        # their original ledger and prior known results; no automatic retries.
        for id in d["selected_ids"]
            event=d["events"][id+1];native_input=Dict("event_id"=>id,"primary_time_ns"=>0.,"steps"=>event["steps"])
            rec=event_response(event,d["native_failure_policy"],
                ()->Base.invokelatest(native_fn,native_input,sim,cfg,16,2609261),
                (t,q)->P.process(t,q,c,eion,cal,M),N.flags)
            check(N.field_fingerprint(sim)==fingerprint,"Gamma native call mutated fields")
            pins(d);push!(report["cases"],rec);save(joinpath(output,"event-"*string(id)*".json"),rec)
        end
        stage="final_pins";pins(d);report["field_fingerprint_after"]=N.field_fingerprint(sim)
        check(report["field_fingerprint_after"]==fingerprint,"Gamma final field mutation")
        failed=count(r->r["status"]=="native_failed",report["cases"])
        report["counts"]=Dict("radiation_primaries"=>20,"selected_primaries"=>3,"unprocessed_primaries"=>17,
            "selected_true_zeros"=>1,"native_calls"=>report["native_calls"],"native_failed"=>failed,
            "native_completed"=>2-failed,"readout_completed"=>3-failed,
            "readout_accepted"=>count(r->r["readout"]!==nothing && r["readout"]["accepted"],report["cases"]),
            "electronics_rejected"=>count(r->r["readout"]!==nothing && !r["readout"]["accepted"],report["cases"]))
        report["status"]=failed>0 ? "completed_with_native_failures" : "completed"
    catch err
        report["status"]="failed";report["failure_stage"]=stage;report["error"]=sprint(showerror,err)
        rethrow()
    finally
        report["worker_seconds"]=time()-started
        save(joinpath(output,"report.json"),report)
    end
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    length(ARGS)==4 && ARGS[1]=="--request" && ARGS[3]=="--output" ||
        error("Usage: gamma_native_example.jl --request FILE --output EXISTING_OWNED_MODEL_DIR")
    GammaNativeExample.worker(ARGS[2],ARGS[4])
end
