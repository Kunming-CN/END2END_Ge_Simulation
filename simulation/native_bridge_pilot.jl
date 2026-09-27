# Selected HDF5 adapter only. All physics and readout remain in unchanged helpers.
include("native_response.jl")
module NativeBridgePilot
using ..NativeResponse, JSON, SHA, Unitful
const B=NativeResponse; const N=B.N; const R=B.R; const Q=B.Q; const E=B.E; const P=B.P; const S=B.S
const ROOT=dirname(@__DIR__)
const KIND="selected_native_hdf5_pilot_v1"
const MILLION="cs137-1m"
const OLD="cs10000-v2-diagnostic"
const BASE=joinpath(ROOT,".local","native-bridge-pilot")
const PVPYTHON=raw"C:\Program Files\ParaView 6.1.1\bin\pvpython.exe"
check=R.check
function projectfile(name)
    p=realpath(joinpath(ROOT,name))
    check(Q.childof(p,realpath(ROOT)),"Dependency escapes project")
    p
end
function pins!(pins)
    for (name,h) in pins
        check(E.hashfile(projectfile(name))==h,"Dependency hash mismatch: "*name)
    end
end
function identity(e)
    Dict(k=>e[k] for k in ("namespace","identity","event_id","global_decay_id","seed_event_id",
        "seed_family","source_campaign_sha256","source_lh5_sha256","raw_table"))
end
function validate_event(e,meta)
    ns=e["namespace"]; check(ns in (MILLION,OLD),"Unknown namespace")
    i=e["identity"]; check(i["model_id"]==meta["model_id"],"Wrong model")
    for k in ("chunk_index","global_offset","local_primary_id","global_primary_id","chunk_count")
        check(S.integer(i[k]) && i[k]>=0,"Invalid identity integer")
    end
    check(0<=i["local_primary_id"]<i["chunk_count"]<=10000 &&
        i["global_offset"]==10000*i["chunk_index"] &&
        i["global_primary_id"]==i["global_offset"]+i["local_primary_id"],"Range mapping")
    check(S.integer(e["event_id"]) && e["event_id"]==e["global_decay_id"]==e["seed_event_id"]==i["global_primary_id"] &&
        0<=e["event_id"]<(ns==MILLION ? 1000000 : 10000) && e["seed_family"]==2609261,"Seed/global ID")
    rows=[s["raw_row_index"] for s in e["steps"]]
    check(all(x->S.integer(x)&&x>=0,rows) && rows==sort(unique(rows)),"Raw row identity")
    rot,shift=S.transform(meta["coordinate_transform"])
    for s in e["steps"]
        raw=s["raw"]; check(S.integer(raw["evtid"]) && raw["evtid"]==i["local_primary_id"],"Foreign raw primary")
        for (key,rkey) in (("raw_row_index","raw_row_index"),("energy_keV","edep"),("time_ns","time"),
            ("track_id","trackid"),("parent_track_id","parent_trackid"),("particle_pdg","particle"))
            check(s[key]==raw[rkey],"Changed retained alias: "*key)
        end
        check(S.finite(s["energy_keV"]) && s["energy_keV"]>=0 && S.finite(s["time_ns"]) && s["time_ns"]>=0,"Invalid deposit")
        for (suffix,key) in (("","position_mm"),("_pre","pre_position_mm"),("_post","post_position_mm"))
            global_m=[raw[a*suffix] for a in ("xloc","yloc","zloc")]
            xyz=rot'*(1000 .* global_m .- shift)
            check(length(s[key])==3 && all(S.finite,s[key]) && isapprox(xyz,Float64.(s[key]);rtol=0,atol=1e-10),"Changed coordinate transform")
            suffix=="" && check(s["global_position_m"]==global_m,"Changed global position")
        end
        check(all(x->x in ("inside","surface"),values(s["boundary_classifications"])),"Outside Ge source row")
    end
    energy=sum((s["energy_keV"] for s in e["steps"]);init=0.)
    check(isapprox(e["ge_energy_keV"],energy;atol=1e-9,rtol=1e-12) &&
        e["zero_ge"] isa Bool && e["zero_ge"]==(energy==0),"Energy/zero semantics")
    check(isapprox(e["material_energy_keV"]["G4_Ge"],energy;atol=1e-9,rtol=1e-12),"Material energy")
    check(e["pulse_groups"]==S.groups(e["steps"],meta["grouping_policy"]["horizon_ns"]),"Changed group/delay map")
    check(isempty(e["pulse_groups"])==(energy==0),"Zero group assignment")
    check(e["raw_table"]=="stp/germanium" && occursin(r"^[0-9a-f]{64}$",e["source_lh5_sha256"]),"Missing raw provenance")
    if ns==OLD
        check(e["event_id"]==(meta["model_id"]=="AK02" ? 8432 : 8413),"Wrong historical ID")
    end
    nothing
end
function validate_contract(d)
    check(d["kind"]==KIND && d["status"]=="complete" && d["model_id"] in ("AK02","SAP22"),"Contract kind/model/status")
    model=d["model_id"]; meta=d["prepared"]
    check(meta["model_id"]==model && d["model_sha256"]==meta["model_sha256"]==E.hashfile(joinpath(ROOT,"models",model*".yaml")),"Model hash")
    check(meta==JSON.parsefile(joinpath(ROOT,".local","cs137-1m","inputs",model,"prepared.json")),"Changed prepared geometry")
    check(d["units"]==Dict("raw_position"=>"m","local_position"=>"mm","time"=>"ns","energy"=>"keV"),"Wrong units")
    seen=Set{Tuple{String,Int}}()
    for e in d["events"]
        validate_event(e,meta)
        key=(e["namespace"],e["event_id"]); check(!(key in seen),"Duplicate namespaced primary"); push!(seen,key)
        if e["namespace"]==MILLION
            check(e["source_campaign_sha256"]==d["source_campaign_sha256"],"Campaign identity")
            chunks=filter(c->c["plan"]["index"]==e["identity"]["chunk_index"],d["chunks"])
            check(length(chunks)==1,"Missing/repeated source chunk")
            c=only(chunks); plan=c["plan"]
            check(plan["model"]==model && plan["start"]==e["identity"]["global_offset"] &&
                plan["count"]==e["identity"]["chunk_count"] && plan["seed"]==e["identity"]["radiation_seed"],"Chunk identity")
            check(e["source_lh5_sha256"]==c["raw_sha256"] && e["source_compact_path"]==c["compact_path"] &&
                e["source_compact_sha256"]==c["files_sha256"]["compact.h5"],"Chunk/raw binding")
        else
            original=JSON.parse(only(readlines(projectfile(e["historical_record"]))))
            check(E.hashfile(projectfile(e["historical_record"]))==e["historical_record_sha256"],"Historical hash")
            check(all(e[k]==v for (k,v) in original["original_event"]),"Changed historical event")
            check(original["settings"]["seed_family"]==e["seed_family"],"Historical seed")
        end
    end
    selected=filter(e->e["namespace"]==MILLION,d["events"]); old=filter(e->e["namespace"]==OLD,d["events"])
    check(1<=length(selected)<=64 && length(old)==1,"Selection bounds/namespaces")
    check(d["selected_global_primary_ids"]==[e["event_id"] for e in selected],"Selection ID mapping")
    census=Dict("initial_primaries"=>length(selected),"zero_ge_primaries"=>count(e->e["zero_ge"],selected),
        "positive_ge_primaries"=>count(e->!e["zero_ge"],selected),"groups"=>sum(length(e["pulse_groups"]) for e in selected))
    pop=d["input_population_reference"]
    totals=JSON.parsefile(joinpath(ROOT,".local","million-analysis","analysis-results","summary.json"))["models"][model]
    check(pop==Dict("initial_primaries"=>totals["initial_decays"],"zero_ge_primaries"=>totals["zero_ge_decays"],
        "positive_ge_primaries"=>totals["positive_ge_decays"],"groups"=>totals["isolated_groups"]),"Changed population reference")
    check(pop["initial_primaries"]==1000000 && pop["zero_ge_primaries"]+pop["positive_ge_primaries"]==1000000,"Population census")
    check(d["selected_census"]==census && d["omitted_census"]==Dict(k=>pop[k]-v for (k,v) in census),"Selected/omitted census")
    check(d["nonselected_response"]===nothing && d["diagnostic_census"]==Dict("primaries"=>1,"groups"=>length(only(old)["pulse_groups"])),"Invented response")
    d
end
function load_contracts(input;python_verify=true)
    input=realpath(input); check(Q.childof(input,realpath(BASE)),"Input outside pilot root")
    receipt=JSON.parsefile(joinpath(input,"EXPORT.json"))
    check(receipt["kind"]==KIND && receipt["status"]=="exported_checked_inputs" && Set(keys(receipt["contracts"]))==Set(("AK02","SAP22")),"Incomplete exporter")
    pins!(receipt["source_sha256"]); pins!(receipt["input_sha256"])
    if python_verify
        check(isfile(PVPYTHON),"ParaView Python unavailable; no fallback/install")
        run(`$PVPYTHON --disable-registry --no-mpi -B $(joinpath(ROOT,"tools","native_hdf5_bridge.py")) --verify $input`)
    end
    docs=Any[]
    for model in ("AK02","SAP22")
        entry=receipt["contracts"][model]; check(entry["file"]==model*".json","Contract filename")
        path=joinpath(input,entry["file"]); check(E.hashfile(path)==entry["sha256"],"Contract hash mismatch")
        d=validate_contract(JSON.parsefile(path))
        check(d["model_id"]==model && d["source_sha256"]==receipt["source_sha256"] && d["input_sha256"]==receipt["input_sha256"],"Contract pin/model mismatch")
        push!(docs,d)
    end
    docs,receipt
end
function prepare(d)
    sim,stored=R.setup_simulation(d["model_id"];temperature=77.0)
    bias=maximum(c.potential for c in sim.detector.contacts)-minimum(c.potential for c in sim.detector.contacts)
    check(bias==(d["model_id"]=="AK02" ? 500 : 700),"Canonical bias changed")
    geom=B.geometry(d["prepared"],sim,true)
    R.validate_deposits(d,sim) # Every selected positive row, before either field solve.
    profile=P.load(joinpath(@__DIR__,"native_readout_profile.json"))
    check(profile.profile["name"]=="synthetic-signed-14bit-v1","Unexpected profile")
    P.window_config(profile.config,d["prepared"]["grouping_policy"]["horizon_ns"],N.DT)
    eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation)
    matrix=E.transition(profile.config,N.DT); cal=P.calibration(profile.config,eion,N.DT,matrix)
    (sim=sim,stored=stored,bias=bias,geometry=geom,profile=profile,eion=eion,matrix=matrix,calibration=cal)
end
function newcounts()
    Dict("primaries"=>0,"zero_ge_primaries"=>0,"groups"=>0,"native_success"=>0,"accepted"=>0,
        "readout_rejected"=>0,"native_failed"=>0,"groups_with_step_limits"=>0,"step_limits"=>0,"stopped_without_contact"=>0)
end
function deadline!(started)
    check(time()-started<600,"Bounded pilot exceeded 600-second solve/native/readout/export budget")
end
function reserve_pilot_output(models,out)
    check(dirname(out)==realpath(BASE) && !ispath(out),"Use new pilot output under dedicated root")
    # The existing solver parser refuses existing outputs. Validate before mkdir.
    cfgs=Dict(model=>Q.parse_args(["--model",model,"--position-mm","3,0,5","--precision","64","--dt-ns","2",
        "--min-grid-mm","0.05","--max-iterations","50000","--output",joinpath(out,model)]) for model in models)
    mkdir(out)
    for model in models; mkdir(joinpath(out,model)); end
    cfgs
end
function run_model(d,a,out,started,receipt,cfg)
    model=d["model_id"]; sim=a.sim
    counts=Dict(ns=>newcounts() for ns in (MILLION,OLD))
    report=Dict{String,Any}("kind"=>KIND,"status"=>"running","model_id"=>model,"counts"=>counts,
        "temperature_K"=>77,"stored_temperature_K"=>a.stored,"bias_V"=>a.bias,"parcels"=>16,"seed_family"=>2609261,
        "diffusion"=>true,"end_drift_when_no_field"=>false,"self_repulsion"=>false,
        "dt_ns"=>2,"nominal_drift_cap_ns"=>10000,"native_failure_policy"=>"record",
        "native_failure_allowlist"=>collect(B.NATIVE_FAILURE_MESSAGES),"seed_rule"=>d["seed_rule"],
        "source_sha256"=>receipt["source_sha256"],"input_sha256"=>receipt["input_sha256"],
        "input_population_reference"=>d["input_population_reference"],"selected_census"=>d["selected_census"],
        "omitted_census"=>d["omitted_census"],"diagnostic_census"=>d["diagnostic_census"],"nonselected_response"=>nothing,
        "environment"=>Q.environment("cpu"),"readout_environment"=>E.environment(),"geometry"=>a.geometry,
        "profile_sha256"=>a.profile.sha256,"calibration"=>a.calibration,"ionisation_energy_eV"=>a.eion,
        "field_settings"=>Dict("min_spacing_mm"=>0.05,"max_spacing_mm"=>2,"max_iterations"=>50000,"sor"=>1,"potential_rechecks"=>4),
        "limitations"=>["Selected engineering pilot, not a full million response, spectrum, efficiency, calibrated Li CCE or physical resolution.",
            "Signed signals, finite caps and independent geometry/collection/readout flags remain; numerical parcels are not physical noise.",
            "Synthetic injection calibration; analog grid samples are not waveform ADC acquisition.",
            "Nominal isolated windows; no pileup/live-time model. No resumable full-production adapter is claimed."])
    model_start=time(); native_s=0.; electronics_s=0.; handles=IO[]
    try
        deadline!(started)
        println("FIELD_START ",model); flush(stdout)
        solver,timing=Base.invokelatest(Q.solve_fields!,sim,cfg,Q.prepare_backend("cpu");sor_consts=1.0,potential_rechecks=4)
        report["solver"]=solver; report["field_timings"]=timing; report["field_fingerprint_before"]=N.field_fingerprint(sim)
        deadline!(started)
        streams=Dict{String,Dict{String,IO}}()
        for ns in (MILLION,OLD)
            dir=joinpath(out,ns); mkdir(dir)
            streams[ns]=Dict(name=>open(joinpath(dir,name),"w") for name in
                ("scalars.jsonl","endpoints.jsonl","traces.jsonl","signals.csv","native-failures.jsonl"))
            append!(handles,values(streams[ns]))
            println(streams[ns]["signals.csv"],"namespace,model_id,source_campaign_sha256,chunk_index,local_primary_id,global_primary_id,event_id,group_id,source_lh5_sha256,raw_row_indices,time_since_origin_ns,induced_equivalent_energy_keV")
        end
        for e in d["events"]
            ns=e["namespace"]; c=counts[ns]; io=streams[ns]; id=identity(e)
            c["primaries"]+=1; c["zero_ge_primaries"]+=e["zero_ge"]
            if e["zero_ge"]; println("EVENT ",model," ",ns," ",e["event_id"]," zero_ge=true groups=0"); flush(stdout); end
            println(io["scalars.jsonl"],JSON.json(merge(id,Dict("record_kind"=>"primary","zero_ge"=>e["zero_ge"],
                "deposited_energy_keV"=>e["ge_energy_keV"],"pulse_count"=>length(e["pulse_groups"]),
                "raw_row_indices"=>[s["raw_row_index"] for s in e["steps"]],"readout"=>nothing))))
            byrow=Dict(s["raw_row_index"]=>s for s in e["steps"])
            config=JSON.parsefile(joinpath(out,ns*"-readout-config.json"))
            P.validate_resolved(config,a.profile.profile,ns==MILLION ? d["selected_census"]["initial_primaries"] : 1)
            for g in e["pulse_groups"]
                deadline!(started); c["groups"]+=1
                steps=[byrow[i] for i in g["row_indices"]]
                event=Dict("event_id"=>e["seed_event_id"],"primary_time_ns"=>g["origin_time_ns"],"steps"=>steps)
                t0=time()
                attempt=B.native_attempt(()->N.native_event(event,sim,cfg,16,e["seed_family"]),"record")
                native_s+=time()-t0; deadline!(started)
                if attempt.error!==nothing
                    rec=merge(B.failed_pulse(e,g,steps,Dict("parcels"=>16,"seed"=>e["seed_family"]),attempt.error,e["source_lh5_sha256"]),id)
                    println(io["scalars.jsonl"],JSON.json(rec))
                    println(io["native-failures.jsonl"],JSON.json(Dict("pulse"=>rec,"original_event"=>e,"original_group"=>g,"original_steps"=>steps)))
                    c["native_failed"]+=1
                    println("EVENT ",model," ",ns," ",e["event_id"]," group=",g["group_id"]," native_failed: ",attempt.error["message"]); flush(stdout)
                    continue
                end
                result=attempt.result; t,q=result.times,result.signal
                check(all(isfinite,q) && first(q)==0,"Invalid signed native charge")
                t0=time(); r=P.process(t,q,config,a.eion,a.calibration,a.matrix;horizon_ns=g["horizon_ns"]); electronics_s+=time()-t0
                check(r["current_balance"]["passed"],"Charge/current imbalance")
                flags=N.flags(result.steps); c["native_success"]+=1; c[r["accepted"] ? "accepted" : "readout_rejected"]+=1
                c["groups_with_step_limits"]+=flags["step_limits"]>0; c["step_limits"]+=flags["step_limits"]; c["stopped_without_contact"]+=flags["stopped_without_contact"]
                println(io["traces.jsonl"],JSON.json(merge(id,Dict("group_id"=>g["group_id"],"origin_time_ns"=>g["origin_time_ns"],
                    "raw_row_indices"=>g["row_indices"],"trace"=>pop!(r,"trace")))))
                for (tm,value) in zip(t,q)
                    ident=e["identity"]
                    vals=(ns,model,e["source_campaign_sha256"],ident["chunk_index"],ident["local_primary_id"],ident["global_primary_id"],
                        e["event_id"],g["group_id"],e["source_lh5_sha256"],g["row_indices"],tm,value)
                    println(io["signals.csv"],join(E.csvcell.(vals),','))
                end
                for st in result.steps, endpoint in st["endpoints"]
                    row=st["raw_row_index"]
                    rec=merge(id,Dict("group_id"=>g["group_id"],"raw_row_index"=>row,"original_time_ns"=>byrow[row]["time_ns"],
                        "origin_time_ns"=>g["origin_time_ns"],"deposition_delay_ns"=>st["deposition_delay_ns"],
                        "deposited_energy_keV"=>st["deposited_energy_keV"],"parcel_weight_keV"=>st["parcel_weight_keV"],
                        "step_final_induced_keV"=>st["final_induced_keV"],"parcel_index"=>endpoint["parcel_index"],
                        "seed_uint64"=>string(N.parcel_seed(e["seed_family"],e["seed_event_id"],row,endpoint["parcel_index"])),"endpoint"=>endpoint))
                    println(io["endpoints.jsonl"],JSON.json(rec))
                end
                rec=merge(id,Dict("record_kind"=>"pulse","status"=>"native_completed","group_id"=>g["group_id"],"group"=>g,
                    "raw_row_indices"=>g["row_indices"],"deposited_energy_keV"=>sum(s["energy_keV"] for s in steps),
                    "final_induced_keV"=>last(q),"charge_end_ns"=>last(t),"native_any_negative_charge"=>any(x->x<0,q),
                    "native_min_charge_keV"=>minimum(q),"native_max_charge_keV"=>maximum(q),"transport_flags"=>flags,
                    "readout"=>r,"accepted"=>r["accepted"],"rejection_reason"=>r["rejection_reason"],"trace_saved"=>true))
                println(io["scalars.jsonl"],JSON.json(rec))
                println("EVENT ",model," ",ns," ",e["event_id"]," group=",g["group_id"]," accepted=",r["accepted"]," caps=",flags["step_limits"]," induced_keV=",last(q)); flush(stdout)
            end
        end
        for ns in (MILLION,OLD)
            c=counts[ns]; check(c["groups"]==c["native_success"]+c["native_failed"] && c["native_success"]==c["accepted"]+c["readout_rejected"],"Response census")
            check(c["primaries"]==(ns==MILLION ? d["selected_census"]["initial_primaries"] : 1),"Lost primary")
        end
        report["field_fingerprint_after"]=N.field_fingerprint(sim)
        check(report["field_fingerprint_before"]==report["field_fingerprint_after"],"Shared fields changed")
        pins!(receipt["source_sha256"]); pins!(receipt["input_sha256"]); Q.verify_model_files()
        report["status"]=any(c["native_failed"]>0 for c in values(counts)) ? "completed_with_native_failures" : "completed_provisional_native_response"
    catch err
        report["status"]="failed"; report["error"]=sprint(showerror,err); rethrow()
    finally
        for io in handles; close(io); end
        report["native_drift_and_charge_seconds"]=native_s; report["electronics_seconds"]=electronics_s
        report["solve_replay_readout_export_wall_seconds"]=time()-model_start
        report["artifacts"]=Dict(relpath(joinpath(dir,f),out)=>E.hashfile(joinpath(dir,f)) for (dir,_,files) in walkdir(out) for f in files if f!="run.json")
        report["artifact_bytes"]=sum(filesize(joinpath(out,n)) for n in keys(report["artifacts"]))
        E.save(joinpath(out,"run.json"),report)
    end
    report
end
function main(args=ARGS)
    check(length(args)==4 && args[1]=="--input" && args[3]=="--output","Usage: --input EXPORTED_DIR --output NEW_PILOT_DIR")
    check(Threads.nthreads()==2,"Use Julia --startup-file=no --threads=2 --project=simulation")
    docs,receipt=load_contracts(args[2]); prepared=[prepare(d) for d in docs]
    out=abspath(args[4]); check(dirname(out)==realpath(BASE) && !ispath(out),"Use new pilot output under dedicated root")
    configs=reserve_pilot_output([d["model_id"] for d in docs],out)
    # Every input/config is exported and revalidated before either detector solve.
    cp(joinpath(realpath(args[2]),"EXPORT.json"),joinpath(out,"input-export.json"))
    for (d,a) in zip(docs,prepared)
        dir=joinpath(out,d["model_id"])
        cp(joinpath(realpath(args[2]),d["model_id"]*".json"),joinpath(dir,"input-contract.json"))
        cp(joinpath(@__DIR__,"native_readout_profile.json"),joinpath(dir,"profile-input.json"))
        for ns in (MILLION,OLD)
            n=ns==MILLION ? d["selected_census"]["initial_primaries"] : 1
            c=P.for_census(a.profile.profile,n); P.validate_resolved(c,a.profile.profile,n)
            E.save(joinpath(dir,ns*"-readout-config.json"),c)
        end
    end
    started=time(); E.save(joinpath(out,"compute-start.json"),Dict("unix_time"=>started,"limit_seconds"=>600))
    reports=Any[]; terminal=Dict{String,Any}("status"=>"running","scope"=>"selected pilot; old diagnostics separate")
    try
        for (d,a) in zip(docs,prepared)
            push!(reports,run_model(d,a,joinpath(out,d["model_id"]),started,receipt,configs[d["model_id"]]))
        end
        load_contracts(args[2];python_verify=false)
        terminal["status"]=any(r["status"]=="completed_with_native_failures" for r in reports) ? "completed_with_native_failures" : "completed_provisional_native_response"
    catch err
        terminal["status"]="failed"; terminal["error"]=sprint(showerror,err); rethrow()
    finally
        terminal["compute_export_seconds"]=time()-started
        terminal["models"]=Dict(r["model_id"]=>Dict("status"=>r["status"],"counts"=>r["counts"],"artifact_bytes"=>r["artifact_bytes"],
            "native_seconds"=>r["native_drift_and_charge_seconds"],"field_timings"=>r["field_timings"]) for r in reports)
        terminal["timing_scope"]="Serial field solve/native/electronics/export interval; module startup/preflight excluded; no warm-up subtraction"
        E.save(joinpath(out,"run.json"),terminal)
        write(joinpath(out,"summary.html"),"<!doctype html><meta charset='utf-8'><title>Selected native bridge pilot</title><h1>Selected engineering pilot</h1><p>Not a million-event response, calibrated CCE, physical resolution or measured spectrum. Old diagnostic namespaces remain separate. Full signed signals, bounded traces and endpoint flags are retained per model. Nonselected responses are unknown.</p><pre>"*N.escape(JSON.json(terminal,2))*"</pre><p><a href='run.json'>Terminal receipt</a> | <a href='AK02/run.json'>AK02 report</a> | <a href='SAP22/run.json'>SAP22 report</a></p>")
        println(JSON.json(terminal)); flush(stdout)
    end
end
end
if abspath(PROGRAM_FILE)==@__FILE__; NativeBridgePilot.main(); end
