# GeGI radiation deposits -> native SSD signals on all contacts -> shared readout.
# No CUDA import; optional local field reuse is exact-model/hash checked.
include("replay.jl")
include("readout_profiles.jl")
include("gegi_signal_helpers.jl")
module GeGIResponse
using ..SSDQuickstart, ..SSDReplay, ..Readout, ..ReadoutProfiles, ..GeGISignalHelpers
using SolidStateDetectors, Unitful, JSON, SHA, Serialization, LinearAlgebra
const Q=SSDQuickstart; const R=SSDReplay; const E=Readout; const P=ReadoutProfiles
const H=GeGISignalHelpers; const SSD=SolidStateDetectors
const ROOT=Q.ROOT
const MODEL_HASH="4b6c71c178c81e68bc1fe093d491b59ab99f19aed5adaba5fc61bba74d445c04"
const SOURCES=("gegi_response.jl","gegi_signal_helpers.jl","run.jl","replay.jl","readout.jl","readout_profiles.jl","readout_demo.json")
check=E.check
hashfile=E.hashfile
function transient_io(err)
    (err isa Base.IOError && err.code in (Base.UV_EACCES,Base.UV_EPERM,Base.UV_EBUSY)) ||
        (err isa SystemError && err.errnum in (Base.Libc.EACCES,Base.Libc.EPERM,Base.Libc.EBUSY))
end
function retry_checkpoint_io(f; wait=sleep)
    for attempt in 1:8
        try
            return f()
        catch err
            (!transient_io(err) || attempt==8) && rethrow()
            wait(min(0.1*2.0^(attempt-1),2.0))
        end
    end
end
function replace_checkpoint(temp,path; rename_file=Base.Filesystem.rename,wait=sleep)
    # Same-directory rename replaces atomically. Base.mv(force=true) first stats
    # the destination and can fall back to deletion/copy; neither is wanted for
    # a Google Drive checkpoint. A failed rename keeps the previous file intact.
    check(dirname(abspath(temp))==dirname(abspath(path)) && abspath(temp)!=abspath(path),
        "Checkpoint replacement requires distinct files in the same directory")
    retry_checkpoint_io(()->rename_file(temp,path);wait=wait)
end
function atomic_checkpoint(writer,path; rename_file=Base.Filesystem.rename,wait=sleep)
    temp=path*".tmp"
    retry_checkpoint_io(()->open(writer,temp,"w");wait=wait)
    # Keep a failed temporary file as evidence; never truncate the destination.
    replace_checkpoint(temp,path;rename_file=rename_file,wait=wait)
end
function save(path,value; kwargs...)
    atomic_checkpoint(path;kwargs...) do io
        JSON.print(io,value)
        println(io)
    end
end
function save_digest(path,digest)
    atomic_checkpoint(io->print(io,digest),path)
end
function compact_run(report)
    run=Dict(k=>v for (k,v) in report if k!="events")
    run["kind"]="gegi_native_response_v1"
    run["event_checkpoints"]=[Dict("event_id"=>e["event_id"],"status"=>e["status"],
        "record_ref"=>"events/"*string(e["event_id"])*".json") for e in report["events"]]
    run["event_data_storage"]="Full event records remain in events/<id>.json and final results.json; progress contains only their index."
    run
end
save_run(out,report)=save(joinpath(out,"run.json"),compact_run(report))
function input_path(ref)
    check(ref isa String && !isempty(ref), "Invalid input path")
    p=isabspath(ref) ? normpath(ref) : normpath(joinpath(ROOT,ref))
    check(isfile(p) && Q.childof(realpath(p),realpath(ROOT)), "Input must be an existing project file")
    p
end
function pinned_input(req,key,hashkey)
    path=input_path(req[key])
    check(hashfile(path)==req[hashkey], "Changed input: "*key)
    path
end
function numerics(req)
    n=get(req,"numerics",Dict())
    check(Set(keys(n))<=Set(("drift_dt_ns","drift_cap_ns","native_seed","precision_bits","diffusion","self_repulsion","field_policy","depth_calibration","scope","min_grid_mm","max_grid_mm","max_iterations")),"Unknown GeGI numerical setting")
    check(get(n,"diffusion",false)===false && get(n,"self_repulsion",false)===false,"This GeGI worker implements deterministic point-charge drift")
    check(get(n,"precision_bits",64)==64,"Fresh GeGI fields require Float64")
    dt=Float64(get(n,"drift_dt_ns",1.0)); cap=Float64(get(n,"drift_cap_ns",1000.0))
    check(E.finite(cap) && cap>dt,"Invalid drift cap")
    steps=ceil(Int,cap/dt)+1
    minspace=Float64(get(n,"min_grid_mm",0.5)); maxspace=Float64(get(n,"max_grid_mm",2.0))
    iterations=get(n,"max_iterations",50000); threads=req["selection"]["threads"]
    check(E.finite(dt) && 0.25<=dt<=10, "GeGI time step must be 0.25..10 ns")
    check(E.integer(steps) && 100<=steps<=20000, "GeGI drift steps must be 100..20000")
    check(E.finite(minspace) && E.finite(maxspace) && 0.05<=minspace<=maxspace<=5, "Invalid GeGI field grid bounds")
    check(E.integer(iterations) && 250<=iterations<=50000, "Invalid field iteration bound")
    check(E.integer(threads) && 1<=threads<=min(2,Threads.nthreads()),"Use one or two Julia threads")
    (dt=dt,max_steps=steps,min_grid=minspace,max_grid=maxspace,max_iterations=iterations,threads=threads,contact=1)
end
function load_fields(req,model,out,cfg,report)
    started=time()
    fresh=Simulation{Float32}(model)
    if get(req,"field_cache",nothing)!==nothing
        cache=req["field_cache"]
        check(cache["model_sha256"]==MODEL_HASH,"Field cache model receipt changed")
        path=pinned_input(cache,"ref","sha256")
        println("Load the hash-checked GeGI field state"); flush(stdout)
        sim=deserialize(path)
        check(sim.config_dict==fresh.config_dict,"Cached fields use a different model")
        report["fields"]=Dict("mode"=>"explicit_exact_model_cache","cache_sha256"=>cache["sha256"],
            "precision_bits"=>8sizeof(SSD.get_precision_type(sim)),"solve_seconds"=>0.0,
            "qualification"=>"Reuses saved numerical fields; no new convergence claim")
    else
        cache=joinpath(out,"fields.jls"); receipt=joinpath(out,"fields.json")
        if isfile(cache) && isfile(receipt)
            old=E.readjson(receipt)
            check(old["model_sha256"]==MODEL_HASH && old["numerics"]==get(req,"numerics",Dict()) && hashfile(cache)==old["sha256"],"Fresh field checkpoint changed")
            sim=deserialize(cache); check(sim.config_dict==fresh.config_dict,"Fresh cache model mismatch")
            report["fields"]=old["fields"]
        else
            sim=Simulation{Float64}(model)
            println("Calculate GeGI electric field and 34 weighting potentials on CPU");flush(stdout)
            solver,times=Q.solve_fields!(sim,cfg,Q.prepare_backend("cpu");sor_consts=1.7,potential_rechecks=4)
            checks=Any[Dict("contact_id"=>1,"last_update"=>solver["weighting_last_update"])]
            common=(device_array_type=Array,use_nthreads=cfg.threads,sor_consts=1.7,
                depletion_handling=true,n_iterations_between_checks=250,verbose=false)
            for id in 2:34
                println("Weighting potential ",id,"/34");flush(stdout)
                SSD.apply_initial_state!(sim,SSD.WeightingPotential,id,sim.electric_potential.grid;depletion_handling=true)
                update=SSD.update_till_convergence!(sim,SSD.WeightingPotential,id,1e-6;common...,max_n_iterations=cfg.max_iterations)
                check(isfinite(update) && update<=1e-6,"GeGI weighting-potential iteration limit: contact $(id), update $(update)")
                push!(checks,Dict("contact_id"=>id,"last_update"=>Float64(update)))
            end
            report["fields"]=Dict("mode"=>"fresh_cpu","precision_bits"=>64,"solver"=>solver,
                "weighting_checks"=>checks,"solve_seconds"=>time()-started,
                "qualification"=>"Iteration tolerances only; no grid-convergence or experimental claim")
            serialize(cache*".tmp",sim);replace_checkpoint(cache*".tmp",cache)
            save(receipt,Dict("model_sha256"=>MODEL_HASH,"numerics"=>get(req,"numerics",Dict()),
                "sha256"=>hashfile(cache),"fields"=>report["fields"]))
        end
    end
    check(length(sim.detector.contacts)==34 && all(!ismissing(sim.weighting_potentials[i]) for i in 1:34),"Missing GeGI contact weighting potentials")
    check(!ismissing(sim.electric_field) && !ismissing(sim.electric_potential),"Missing electric field")
    report["fields"]["load_or_solve_seconds"]=time()-started
    fresh=nothing;GC.gc()
    sim
end
function native_deposit(sim,xyz,energy,cfg; ids=1:34)
    T=SSD.get_precision_type(sim)
    point=SSD.CartesianPoint{T}((T.(xyz)./T(1000))...)
    check(point in sim.detector.semiconductor,"Positive deposit outside GeGI crystal")
    check(!any(c->point in c.geometry,sim.detector.contacts),"Deposit starts on a GeGI contact")
    event=SSD.Event([point],[energy*u"keV"])
    SSD.drift_charges!(event,sim;Δt=cfg.dt*u"ns",max_nsteps=cfg.max_steps,
        geometry_check=true,diffusion=false,self_repulsion=false,end_drift_when_no_field=true,verbose=false)
    stored=event.locations[1][1]
    check((stored.x,stored.y,stored.z)==(point.x,point.y,point.z),"SSD changed a deposited location")
    wave=Dict{Int,Any}()
    for id in ids
        SSD.get_signal!(event,sim,id;Δt=cfg.dt*u"ns",signal_unit=u"keV")
        w=event.waveforms[id]
        # SSD Float32 timestamps carry representation noise; the requested native
        # regular grid is exact by construction. Preserve its spacing in Float64.
        observed=Float64.(ustrip.(u"ns",w.time)); t=collect(0:length(observed)-1).*cfg.dt
        check(all(isapprox.(observed,t;rtol=2e-6,atol=max(1e-5,cfg.dt*2e-6))),"SSD changed the requested time grid")
        q=Float64.(ustrip.(u"keV",w.signal))
        check(length(q)>=2 && all(isfinite,q) && first(q)==0,"Invalid native signed charge")
        wave[id]=(times=t,charge=q)
    end
    endpoints=Q.endpoint_report(event,sim,cfg)
    check(all(e->e["inside_semiconductor"]||!isempty(e["contact_ids"]),endpoints),"Noncontact endpoint outside crystal")
    wave,endpoints
end
function depth_calibration(sim,cfg,channels,energy)
    x=channels[9]["strip_center_mm"]; y=channels[26]["strip_center_mm"]
    depths=collect(-5.0:1.0:5.0);ctd=Any[];rows=Any[]
    println("Independent central-pixel depth calibration: 11 fixed injections");flush(stdout)
    for z in depths
        waves,endpoints=native_deposit(sim,[x,y,z],energy,cfg;ids=(9,26))
        tx=H.crossing_time(waves[9].times,waves[9].charge)
        ty=H.crossing_time(waves[26].times,-waves[26].charge)
        complete=all(e->!isempty(e["contact_ids"])&&!e["step_limit_reached"],endpoints)
        valid=complete && tx!==nothing && ty!==nothing && last(waves[9].charge)>0 && last(waves[26].charge)<0
        delta=valid ? tx-ty : nothing
        push!(ctd,delta);push!(rows,Dict("z_mm"=>z,"X_t50_ns"=>tx,"Y_t50_ns"=>ty,
            "ctd_ns"=>delta,"valid"=>valid,"endpoints"=>endpoints,
            "X_final_induced_keV"=>last(waves[9].charge),"Y_final_induced_keV"=>last(waves[26].charge)))
    end
    valid=H.monotonic_depth_table(depths,ctd)
    Dict("kind"=>"gegi_central_pixel_simulated_depth_v1","status"=>valid ? "available_model_approximation" : "unavailable_nonmonotonic_or_incomplete",
        "depth_mm"=>depths,"ctd_ns"=>ctd,"rows"=>rows,"x_mm"=>x,"y_mm"=>y,
        "contact_ids"=>[9,26],"injection_energy_keV"=>energy,
        "method"=>"Last rising 50% of terminal polarity-corrected induced charge, after any earlier threshold recrossing; CTD=t50_X-t50_Y; piecewise linear inverse only inside monotonic calibrated envelope",
        "timing_method"=>"ideal_charge_last_rising_constant_fraction_terminal_v2",
        "measured_calibration"=>false,"per_pixel_calibration"=>false,
        "limitations"=>["Central-pixel simulated relation applied as a declared approximation to other strips.",
            "Timing uses ideal induced charge, not a measured GeGI timing circuit.",
            "No extrapolation beyond -5..5 mm; no measured depth or angular resolution assigned.",
            "Overlapping interactions on one strip cannot be resolved by this timing estimator."])
end
function validate_event(event,n)
    id=event["event_id"];check(E.integer(id)&&0<=id<n,"Invalid original primary ID")
    t0=get(event,"primary_time_ns",0.0);check(E.finite(t0)&&t0>=0,"Invalid primary time")
    steps=event["steps"];check(1<=length(steps)<=100000,"Invalid sparse positive event")
    total=0.0
    for s in steps
        check(E.finite(s["energy_keV"])&&s["energy_keV"]>=0,"Invalid deposit energy")
        check(R.vec3(s["position_mm"]),"Invalid local deposit coordinate")
        check(E.finite(s["time_ns"])&&s["time_ns"]>=t0,"Invalid deposition time")
        total+=s["energy_keV"]
    end
    check(total>0,"Zero primary belongs only in the sparse event census")
    total,Float64(t0)
end
"""Shared signed-channel electronics and timing, with an optional isolated horizon."""
function channel_response(t,q,ch,readout,eion,cal,matrix;horizon_ns=nothing)
    wired=ch["wiring_factor"].*q
    result=P.process(t,wired,readout,eion,cal,matrix;horizon_ns=horizon_ns)
    check(result["current_balance"]["passed"],"Current/charge identity failed")
    collecting=last(wired)>=readout["threshold_V"]/cal["volts_per_keV"]
    tx=collecting ? H.crossing_time(t,wired,0.5) : nothing
    t90=collecting ? H.crossing_time(t,wired,0.9) : nothing
    result["contact_id"]=ch["id"];result["final_induced_keV"]=last(q)
    result["final_wired_induced_keV"]=last(wired);result["collection_candidate"]=collecting
    result["t50_ns"]=tx;result["t90_ns"]=t90
    result["timing_method"]="ideal_charge_last_rising_constant_fraction_terminal_v2"
    if horizon_ns!==nothing
        result["native_t50_ns"]=tx;result["native_t90_ns"]=t90
        result["timing_window_ns"]=horizon_ns
        result["t50_outside_window"]=tx!==nothing && tx>=horizon_ns
        result["t90_outside_window"]=t90!==nothing && t90>=horizon_ns
        result["t50_outside_window"] && (result["t50_ns"]=nothing)
        result["t90_outside_window"] && (result["t90_ns"]=nothing)
    end
    trace=result["trace"]
    trace["wired_induced_charge_fC"]=trace["induced_charge_fC"]
    trace["signed_induced_charge_fC"]=ch["wiring_factor"].*trace["induced_charge_fC"]
    trace["charge_fC"]=trace["signed_induced_charge_fC"]
    trace["signed_induced_current_nA"]=ch["wiring_factor"].*trace["current_nA"]
    result["trace_conventions"]=Dict("charge_fC"=>"Raw signed SSD induced charge before fixed family wiring",
        "current_nA"=>"Current after fixed family wiring; original integration bin, not display-point interval",
        "preamp_V"=>"Signed preamplifier output driven by fixed-wiring current",
        "shaped_V"=>"Signed shaper voltage with configured electronics inversion",
        "wired_induced_charge_fC"=>"Charge after fixed X=+1/Y=-1 wiring")
    result["wiring_factor"]=ch["wiring_factor"]
    result
end
function process_event(event,sim,cfg,channels,readout,cal,matrix,eion,n,signalfile)
    energy,t0=validate_event(event,n);components=[Any[] for _ in 1:34];outcomes=Any[]
    for (idx,step) in enumerate(event["steps"])
        step["energy_keV"]==0 && continue
        waves,endpoints=native_deposit(sim,step["position_mm"],step["energy_keV"],cfg)
        for id in 1:34
            w=waves[id];push!(components[id],(delay=Float64(step["time_ns"]-t0),times=w.times,charge=w.charge))
        end
        push!(outcomes,Dict("input_step_index"=>idx,"raw_row_index"=>get(step,"raw_row_index",nothing),
            "energy_keV"=>step["energy_keV"],"position_mm"=>step["position_mm"],
            "deposition_delay_ns"=>step["time_ns"]-t0,"endpoints"=>endpoints))
    end
    rows=Any[];signalsha=nothing
    open(signalfile,"w") do io
        println(io,"contact_id,time_ns,signed_induced_keV,wired_induced_keV")
        for ch in channels
            id=ch["id"];t,q=R.causal_sum(components[id],cfg.dt)
            result=channel_response(t,q,ch,readout,eion,cal,matrix;
                horizon_ns=get(event,"readout_horizon_ns",nothing))
            for k in eachindex(t);println(io,id,',',t[k],',',q[k],',',ch["wiring_factor"]*q[k]);end
            push!(rows,result)
        end
    end
    signalsha=hashfile(signalfile)
    endpoints=[e for s in outcomes for e in s["endpoints"]]
    limited=any(e->e["step_limit_reached"],endpoints)
    stopped=any(e->e["status"]=="stopped_without_contact",endpoints)
    status=limited ? "step_limit" : stopped ? "stopped_without_contact" : "completed"
    Dict("event_id"=>event["event_id"],"primary_time_ns"=>t0,"truth_edep_keV"=>energy,
        "status"=>status,"steps"=>outcomes,"channels"=>rows,
        "transport_flags"=>Dict("step_limits"=>count(e->e["step_limit_reached"],endpoints),
            "stopped_without_contact"=>count(e->e["status"]=="stopped_without_contact",endpoints)),
        "signals_ref"=>replace(relpath(signalfile,dirname(dirname(signalfile))),'\\'=>'/'),"signals_sha256"=>signalsha)
end
function main(args=ARGS)
    args==["--help"] && return println("gegi_response.jl --request FILE --output DIR")
    check(length(args)==4 && args[1]=="--request" && args[3]=="--output","Use --request FILE --output DIR")
    env=Q.environment("cpu");E.environment();BLAS.set_num_threads(1)
    requestpath=abspath(args[2]);req=E.readjson(requestpath);requestsha=hashfile(requestpath)
    model=pinned_input(req,"model_ref","model_sha256");check(req["model_sha256"]==MODEL_HASH,"Frozen GeGI model changed")
    profile=pinned_input(req,"profile_ref","profile_sha256");manifestpath=pinned_input(req,"stream_ref","stream_sha256")
    manifest=E.readjson(manifestpath)
    check(manifest["events_file"]=="events.jsonl","Unexpected GeGI sparse events file")
    stream=input_path(joinpath(dirname(manifestpath),manifest["events_file"]))
    check(hashfile(stream)==manifest["events_sha256"],"Changed GeGI sparse events")
    check(req["kind"]=="gegi_native_request_v1","Unknown GeGI native request")
    for (ref,digest) in req["source_sha256"]
        check(hashfile(input_path(ref))==digest,"Changed GeGI source: "*ref)
    end
    cfg=numerics(req);loaded=P.load(profile);readout=loaded.config
    check(get(readout,"peak_policy","")==E.SIGNED_PEAK_POLICY,"GeGI requires the explicit signed-input readout profile")
    out=abspath(args[4]);check(Q.childof(out,joinpath(ROOT,".local")),"GeGI response output must be under .local")
    sources=Dict(n=>hashfile(joinpath(@__DIR__,n)) for n in SOURCES)
    identity=Dict("request_sha256"=>requestsha,"source_code_sha256"=>sources)
    if isdir(out)
        check(isfile(joinpath(out,"identity.json")) && E.readjson(joinpath(out,"identity.json"))==identity,"Existing output is not this exact resumable response")
    else
        Q.reserve_output(out);save(joinpath(out,"identity.json"),identity)
    end
    n=manifest["primary_count"];zero=manifest["zero_deposit_primaries"];nonzero=manifest["nonzero_primaries"]
    counts=Dict("initial_primaries"=>n,"zero_deposit_primaries"=>zero,"nonzero_primaries"=>nonzero)
    check(E.integer(n)&&1<=n<=100000&&E.integer(zero)&&E.integer(nonzero)&&zero>=0&&nonzero>=0&&zero+nonzero==n,"Invalid sparse census")
    readout["expected_primary_count"]=n
    report=Dict{String,Any}("schema_version"=>1,"kind"=>"gegi_multichannel_results_v1","status"=>"running",
        "configuration_sha256"=>req["configuration_sha256"],"request_sha256"=>requestsha,
        "model_sha256"=>MODEL_HASH,"source_sha256"=>req["source_sha256"],"stream_sha256"=>req["stream_sha256"],
        "profile_sha256"=>req["profile_sha256"],"selection"=>req["selection"],"counts"=>counts,
        "environment"=>env,"source_code_sha256"=>sources,"numerics"=>get(req,"numerics",Dict()),
        "units"=>Dict("energy"=>"keV","length"=>"mm","time"=>"ns","charge"=>"fC","current"=>"nA","voltage"=>"V"),
        "events"=>Any[],"readout_config"=>readout,"depth_calibration"=>nothing,
        "limitations"=>["Native point-charge drift without diffusion, self-repulsion, electronics noise, cross talk or Fano fluctuations.",
            "Original model temperature 92.3 K and -879/0 V biases are preserved assumptions.",
            "Each event's deposits are superposed at their own creation times; deposition time is not drift time.",
            "X and Y measure the same charge; never add both families to obtain event energy.",
            "Signals on guards and noncollecting strips remain signed; unknown failed responses remain null.",
            "Independently injected synthetic electronics and central-pixel depth calibration are not measured hardware calibration."])
    started=time();save_run(out,report)
    try
        sim=load_fields(req,model,out,cfg,report);channels=H.channel_metadata(sim.config_dict)
        report["channels"]=channels
        eion=Float64(ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation))
        matrix=E.transition(readout,cfg.dt);cal=P.calibration(readout,eion,cfg.dt,matrix)
        report["calibration"]=Dict("electronics"=>cal,"family_wiring"=>Dict("X"=>1,"Y"=>-1),
            "family_injections"=>Dict(f=>merge(copy(cal),Dict("signed_input_charge_C"=>sign*cal["charge_C"],"wiring_factor"=>sign)) for (f,sign) in (("X",1),("Y",-1))),
            "injection"=>"Independent same-energy delta charge in each fixed family wiring convention; shared readout transfer function")
        report["ionisation_energy_eV"]=eion
        depthpath=joinpath(out,"depth-calibration.json")
        if isfile(depthpath)
            check(isfile(depthpath*".sha256") && strip(read(depthpath*".sha256",String))==hashfile(depthpath),"Depth checkpoint changed")
            depth=E.readjson(depthpath)
        else
            depth=depth_calibration(sim,cfg,channels,readout["calibration_energy_keV"])
            save(depthpath,depth);save_digest(depthpath*".sha256",hashfile(depthpath))
        end
        report["depth_calibration"]=depth
        report["calibration"]["depth"]=depth
        eventdir=joinpath(out,"events");mkpath(eventdir);seen=Set{Int}()
        open(stream) do input
            for line in eachline(input)
                isempty(strip(line)) && continue
                event=JSON.parse(line);id=event["event_id"]
                check(!(id in seen),"Duplicate sparse primary ID");push!(seen,id)
                validate_event(event,n)
                eventpath=joinpath(eventdir,string(id)*".json");signals=joinpath(eventdir,string(id)*"-signals.csv")
                if isfile(eventpath)
                    check(isfile(eventpath*".sha256") && strip(read(eventpath*".sha256",String))==hashfile(eventpath),"Event checkpoint changed")
                    record=E.readjson(eventpath)
                    check(record["input_event_sha256"]==bytes2hex(sha256(line)),"Event checkpoint input changed")
                    record["status"]=="native_failed" || check(hashfile(signals)==record["signals_sha256"],"Event signal checkpoint changed")
                else
                    println("GeGI primary ",id,": ",length(event["steps"])," deposit rows, all 34 contacts");flush(stdout)
                    record=try
                        process_event(event,sim,cfg,channels,readout,cal,matrix,eion,n,signals)
                    catch err
                        if err isa ArgumentError && err.msg in ("Noncontact endpoint outside crystal","Invalid waveform support")
                            Dict("event_id"=>id,"primary_time_ns"=>get(event,"primary_time_ns",0),
                                "truth_edep_keV"=>sum(s["energy_keV"] for s in event["steps"]),
                                "status"=>"native_failed","steps"=>event["steps"],"channels"=>nothing,
                                "error"=>sprint(showerror,err),"signals_ref"=>nothing,"signals_sha256"=>nothing)
                        else
                            rethrow()
                        end
                    end
                    record["input_event_sha256"]=bytes2hex(sha256(line));save(eventpath,record)
                    save_digest(eventpath*".sha256",hashfile(eventpath))
                end
                push!(report["events"],record)
                report["processed_nonzero"]=length(seen);save_run(out,report)
            end
        end
        check(length(seen)==nonzero,"Sparse stream disagrees with primary census")
        check(hashfile(stream)==manifest["events_sha256"] && hashfile(manifestpath)==req["stream_sha256"] && hashfile(model)==MODEL_HASH && hashfile(profile)==req["profile_sha256"],"Input changed during response")
        check(all(hashfile(joinpath(@__DIR__,name))==value for (name,value) in sources),"Source changed during response")
        for (ref,digest) in req["source_sha256"]
            check(hashfile(input_path(ref))==digest,"Changed GeGI source: "*ref)
        end
        check(hashfile(requestpath)==requestsha,"Request changed during response")
        report["nonzero_event_ids"]=sort!(collect(seen))
        report["counts"]["native_failed_groups"]=count(e->e["status"]=="native_failed",report["events"])
        report["counts"]["native_flagged_groups"]=count(e->e["status"] in ("step_limit","stopped_without_contact"),report["events"])
        report["counts"]["processed_nonzero"]=length(seen)
        accepted=0
        for event in report["events"]
            event["channels"]===nothing && continue
            x=any(c->c["accepted"]&&c["collection_candidate"]&&1<=c["contact_id"]<=16,event["channels"])
            y=any(c->c["accepted"]&&c["collection_candidate"]&&18<=c["contact_id"]<=33,event["channels"])
            accepted+=x&&y
        end
        report["counts"]["accepted_nonzero_primaries"]=accepted
        report["counts"]["rejected_nonzero_primaries"]=nonzero-accepted-report["counts"]["native_failed_groups"]
        report["status"]=report["counts"]["native_failed_groups"]==0 ? "completed" : "completed_with_native_failures"
        report["seconds"]=time()-started
        save(joinpath(out,"results.json"),report)
        report["artifacts"]=Dict("results.json"=>hashfile(joinpath(out,"results.json")),
            "depth-calibration.json"=>hashfile(depthpath),"identity.json"=>hashfile(joinpath(out,"identity.json")))
        for event in report["events"]
            id=event["event_id"];ref="events/"*string(id)*".json"
            report["artifacts"][ref]=hashfile(joinpath(out,ref))
            event["signals_ref"]===nothing || (report["artifacts"][event["signals_ref"]]=event["signals_sha256"])
        end
    catch err
        report["status"]="failed";report["error"]=sprint(showerror,err);rethrow()
    finally
        report["seconds"]=time()-started
        save_run(out,report)
    end
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__;GeGIResponse.main();end
