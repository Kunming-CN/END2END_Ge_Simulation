# Separate saved-Control Ge context. Electronics-only; no producer/SSD imports.
include("readout_profiles.jl")
include("saved_collection_edge.jl")
using JSON, LinearAlgebra
const E=Readout;const P=ReadoutProfiles;const D=SavedCollectionEdge
const ROOT=dirname(@__DIR__)
function control_context(d)
    for (n,h) in D.SOURCE_PINS
        E.check(E.hashfile(joinpath(@__DIR__,n))==h,"Original frozen electronics dependency changed: "*n)
    end
    E.check(d["kind"]=="saved_control_edge_request_v1" && d["model_id"]=="GeRC02","Separate saved Ge context")
    E.check(d["wiring_factor"]==1.0 && d["ionisation_energy_eV"]==2.95,"Original Ge signal convention")
    c=d["config"];profile=d["profile"];n=d["primary_count"]
    expected=P.for_census(profile,n);comparable=deepcopy(c)
    # Only the established PowerShell/Julia real-value spelling equivalence is
    # admitted. Actual consumed configuration is never normalized for replay.
    for k in ("calibration_energy_keV","max_window_ns","tail_shaping_constants")
        E.check(E.finite(c[k]) && c[k]==expected[k],"Changed real readout constant")
        comparable[k]=expected[k]
    end
    E.check(D.exact_value(comparable,expected),"Saved selected profile/config differs")
    E.check(c["trace_max_points"]===600,"Original trace limit")
    E.validate_peak_config(c);cal=d["calibration"];dt=cal["time_step_ns"]
    E.check(dt==2.0 && cal["ionisation_energy_eV"]==2.95,"Recorded analog grid/pair energy")
    M=E.transition(c,dt);started=time();fresh=P.calibration(c,2.95,dt,M)
    E.check(D.exact_value(fresh,cal),"Actual independent injection calibration changed")
    (config=c,calibration=cal,matrix=M,dt=dt,calibration_validation_seconds=time()-started)
end
function control_edge(t,q,context,readout;stop_ns,max_edge_points=10001)
    c=context.config;dt=context.dt;M=context.matrix
    E.validate_wave(t,q,dt,c["max_samples_per_event"])
    E.check(readout["isolated_horizon_ns"]==100000 && readout["readout_end_ns"]==99998.0,"Exact finite ring window")
    stop=P.window_config(c,readout["isolated_horizon_ns"],dt)
    keep=searchsortedlast(t,stop)
    E.check(readout["charge_clipped_at_window"]==(keep<length(t)) && readout["untruncated_charge_end_ns"]==last(t) &&
        readout["untruncated_final_charge_keV"]==last(q) && readout["input_sample_count"]==keep,"Original finite window/charge flags")
    E.check(E.finite(stop_ns) && 0<=stop_ns<=stop && isinteger(stop_ns/dt),"On-grid bounded display range")
    count=Int(stop_ns/dt)+1;E.check(E.integer(max_edge_points) && 1<=max_edge_points<=10001 && count<=max_edge_points,"Explicit dense point bound")
    # Ge has +1 input wiring. KM uses its already-dense saved head camera;
    # this adapter does not accept KM or move inversion after differencing.
    cf=c["feedback_capacitance_pF"]*1e-12;factor=E.charge_C(1.,2.95);pre=zeros(count);x=zeros(5)
    for k in 2:count
        dq=k<=keep ? (q[k]-q[k-1])*factor : 0.
        x[5]=dq/dt/cf;x=M*x;pre[k]=x[1]
    end
    E.check(all(isfinite,pre),"Finite saved-electronics prefix")
    Dict("kind"=>D.KIND,"schema_version"=>1,"origin"=>"same_electronics_replay_from_saved_signed_charge",
        "scope"=>"separate checked saved-Control Ge finite-window electronics context; unsaved original arrays are not recovered",
        "time_step_ns"=>dt,"captured_start_ns"=>0.0,"captured_stop_ns"=>stop_ns,"captured_sample_count"=>count,
        "time_ns"=>collect(0:count-1).*dt,"preamp_V"=>pre,"original_readout_end_ns"=>stop,
        "original_isolated_horizon_ns"=>readout["isolated_horizon_ns"],"max_edge_points"=>max_edge_points)
end
function control_worker(request,output)
    d=E.readjson(request);name=d["name"]
    E.check(name isa String && occursin(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$",name),"Closed run name")
    base=joinpath(ROOT,".local","product-delivery-v1","display-derived",name)
    E.check(realpath(dirname(request))==realpath(base) && abspath(output)==joinpath(base,"traces.json"),"Fixed external sidecar root")
    E.check(!ispath(output),"Preserve existing derived output")
    E.check(VERSION==v"1.13.0" && Threads.nthreads()==1,"Original Julia / one display thread")
    BLAS.set_num_threads(1)
    for (n,h) in d["source_pins"];E.check(E.hashfile(joinpath(ROOT,n))==h,"Frozen display/electronics source changed");end
    for (n,h) in d["input_pins"];E.check(E.hashfile(joinpath(ROOT,n))==h,"Saved terminal input changed");end
    context=control_context(d);edges=Any[];started=time()
    for group in d["groups"]
        t=Float64.(group["time_ns"]);q=Float64.(group["charge_keV"])
        edge=control_edge(t,q,context,group["readout"];stop_ns=group["stop_ns"])
        edge["identity"]=group["identity"];edge["raw_row_indices"]=group["raw_row_indices"]
        edge["retained_original_parity"]=group["original_trace"]===nothing ?
            Dict("passed"=>nothing,"matched_points"=>0,"status"=>"original_trace_not_saved_no_original_parity_claim") :
            D.retained_preamp_parity(edge,group["original_trace"])
        push!(edges,edge)
    end
    for (n,h) in d["input_pins"];E.check(E.hashfile(joinpath(ROOT,n))==h,"Saved input changed during replay");end
    E.save(output,Dict("kind"=>"saved_control_edge_bundle_v1","status"=>"completed","name"=>name,
        "request_sha256"=>E.hashfile(request),"configuration_sha256"=>d["configuration_sha256"],"complete_sha256"=>d["complete_sha256"],
        "edges"=>edges,"calibration_validation_seconds"=>context.calibration_validation_seconds,"prefix_seconds"=>time()-started,
        "runtime"=>Dict("julia_version"=>string(VERSION),"threads"=>Threads.nthreads(),"blas_threads"=>BLAS.get_num_threads(),
            "blas_configuration"=>string(BLAS.get_config()),"ssd_loaded"=>false,"readout_environment"=>E.environment()),
        "science_calls"=>Dict("radiation"=>0,"field"=>0,"native"=>0)))
end
if abspath(PROGRAM_FILE)==@__FILE__
    length(ARGS)==4 && ARGS[1]=="--request" && ARGS[3]=="--output" || error("Usage: --request FILE --output FIXED_SIDECAR_TRACES_JSON")
    control_worker(ARGS[2],ARGS[4])
end
