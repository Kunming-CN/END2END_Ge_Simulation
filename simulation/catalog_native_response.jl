# One catalog response entry. Frozen SSD, drift, failure and readout kernels are reused.
include("workflow_decay_response.jl")
include("catalog_native_model.jl")
include("catalog_decay_stream.jl")
module CatalogResponse
using ..WorkflowDecayResponse, ..CatalogNativeModel, ..CatalogDecayStream, JSON, Unitful
const W=WorkflowDecayResponse;const C=CatalogNativeModel;const S=CatalogDecayStream
const NR=W.NR;const R=W.R;const Q=W.Q;const E=W.E;const P=W.P;const N=W.N
const SOURCES=Tuple(unique([W.SOURCES...,"catalog_native_model.jl","catalog_decay_stream.jl","catalog_native_response.jl"]))
const PRESERVED_LEGACY_MODELS=("AK02","SAP22","GeRC02","KMRC01_candidate","SAP18_ring08_scenario")
function request_options(args)
    inspect=length(args)==3 && args[1]=="--request" && args[3]=="--inspect"
    R.check(inspect || (length(args)==4 && args[1]=="--request" && args[3]=="--output"),"Use --request FILE --output NEW_DIRECTORY, or --request FILE --inspect")
    path=S.D.S.localfile(args[2]);R.check(filesize(path)<=2_000_000,"Oversized catalog response request")
    d=JSON.parsefile(path)
    R.check(Set(keys(d))==Set(("kind","configuration_sha256","selection","model_contract","profile_ref","profile_sha256","stream_ref","stream_sha256","source_sha256","numerics")) && d["kind"]=="catalog_native_request_v1","Wrong catalog response request")
    s=d["selection"];id=s["detector"]
    R.check(Set(keys(s))==Set(("name","cryostat","detector","source","pose","primary_count","seed","threads","electronics")) && !(id in PRESERVED_LEGACY_MODELS) && s["cryostat"]=="lbnl_modular_nominal_v1" && s["pose"]=="nominal" && s["primary_count"] in (20,500) && C.integer(s["primary_count"]),"Unsupported catalog execution selection")
    R.check(s["name"] isa String && occursin(r"^[A-Za-z0-9_-]{1,48}$",s["name"]) && C.integer(s["threads"]) && s["threads"] in (1,2) && Threads.nthreads()==s["threads"] && C.integer(s["seed"]) && 0<s["seed"]<2147483647,"Wrong catalog name/runtime/seed")
    C.validate_model(d["model_contract"];require_placement=true);mc=d["model_contract"]
    R.check(mc["model_id"]==id && mc["wiring_factor"]==1,"Wrong catalog model/fixed wiring selection")
    R.check(d["numerics"]==C.numerics(mc),"Wrong catalog native numerical settings")
    base=".local/runs/"*s["name"];profile=C.relative_file(d["profile_ref"]);input=C.relative_file(d["stream_ref"])
    R.check(d["profile_ref"]==base*"/electronics/profile.json" && d["stream_ref"]==base*"/transport/stream/manifest.json" && (inspect || abspath(args[4])==abspath(joinpath(C.ROOT,base,"response"))),"Catalog response inputs/output must share one run")
    R.check(E.hashfile(profile)==d["profile_sha256"] && E.hashfile(input)==d["stream_sha256"] && d["configuration_sha256"] isa String && occursin(r"^[0-9a-f]{64}$",d["configuration_sha256"]),"Changed catalog request input hashes")
    required=Set("simulation/"*n for n in SOURCES)
    R.check(d["source_sha256"] isa AbstractDict && issubset(required,Set(keys(d["source_sha256"]))),"Incomplete catalog native source authority")
    for (ref,h) in d["source_sha256"];R.check(E.hashfile(C.relative_file(ref))==h,"Catalog source changed: "*ref);end
    o=Dict("request"=>path,"input"=>input,"profile"=>profile,"output"=>inspect ? nothing : args[4],"inspect"=>inspect,"parcels"=>16,"seed"=>2609261,"native-failure-policy"=>"record")
    !inspect && Q.validate_output(args[4])
    o,d
end
function prepare(o,request;calibrate=true)
    input=S.inspect(o["input"]);d=input.manifest;s=request["selection"];mc=request["model_contract"]
    R.check(d["model_contract"]==mc && d["primary_count"]==s["primary_count"] && d["source_id"]==s["source"] && input.prepared["seed"]==s["seed"],"Prepared model/source/census differs from checked selection")
    a=C.simulation(mc);profile=P.load(o["profile"]);R.check(profile.profile["settings"]==s["electronics"],"Selected electronics differ from consumed profile")
    geometry=C.validate_probes(input.prepared,a.sim);P.window_config(profile.config,d["grouping_policy"]["horizon_ns"],N.DT)
    S.foreach_decay(e->R.validate_deposits(Dict("events"=>[e]),a.sim),input);S.recheck(input)
    matrix=E.transition(profile.config,N.DT);start=time();cal=calibrate ? P.calibration(profile.config,a.ionisation_energy_eV,N.DT,matrix) : nothing
    (stream=input,document=d,meta=input.prepared,sim=a.sim,profile=profile,geometry=geometry,matrix=matrix,calibration=cal,eion=a.ionisation_energy_eV,calibration_seconds=time()-start)
end
function progress(out,started,stage,status,counts,total)
    p=Dict("kind"=>"catalog_native_progress_v1","stage"=>stage,"status"=>status,"completed_primary_count"=>counts["initial_primaries"],"expected_primary_count"=>total,"elapsed_seconds"=>time()-started)
    pending=joinpath(out,"progress.json.pending-"*string(getpid()));write(pending,JSON.json(p));mv(pending,joinpath(out,"progress.json");force=true)
end
function run(o,a,request)
    d=a.document;mc=request["model_contract"];cfg=C.config(mc,o["output"]);c=P.for_census(a.profile.profile,d["primary_count"])
    out=Q.reserve_output(o["output"]);started=time();stage="field_solve";hist=Dict{String,Dict{Int,Int}}();handles=IO[]
    counts=Dict{String,Any}("initial_primaries"=>0,"initial_decays"=>0,"zero_deposit_primaries"=>0,"groups"=>0,"accepted"=>0,"rejected"=>0,"readout_rejected"=>0,"native_failed_groups"=>0,"saturated"=>0,"native_charge_samples"=>0,"analog_samples"=>0,"line_photons"=>0,"decay_photons"=>0)
    report=Dict{String,Any}("kind"=>"catalog_native_response_v1","status"=>"running","model_id"=>d["model_id"],"source_id"=>d["source_id"],"source_contract"=>d["source_contract"],"model_sha256"=>d["model_sha256"],"model_contract"=>mc,"source_lh5_sha256"=>d["source_lh5_sha256"],"input_sha256"=>E.hashfile(a.stream.path),"request_sha256"=>E.hashfile(o["request"]),"configuration_sha256"=>request["configuration_sha256"],"environment"=>Q.environment("cpu"),"readout_environment"=>E.environment(),"source_sha256"=>request["source_sha256"],"temperature_K"=>mc["runtime_temperature_K"],"stored_temperature_K"=>mc["stored_temperature_K"],"contact_potentials_V"=>mc["contact_potentials_V"],"readout_contact_id"=>mc["readout_contact_id"],"bias_V"=>mc["bias_span_V"],"signed_operating_bias_V"=>mc["wiring_factor"]*mc["bias_span_V"],"wiring_factor"=>mc["wiring_factor"],"geometry_checks"=>a.geometry,"counts"=>counts,"calibration"=>a.calibration,"independent_calibration_calls"=>1,"calibration_calls"=>1,"calibration_seconds"=>a.calibration_seconds,"profile"=>a.profile.profile,"profile_sha256"=>a.profile.sha256,"ionisation_energy_eV"=>a.eion,"new_field_solution"=>true,"numerics"=>request["numerics"],"parcels"=>16,"seed_family"=>2609261,"seed_rule"=>"legacy SHA256(seed/raw local event_id/raw_row_index/parcel_index), first8 bytes big-endian UInt64; single-run catalog contract","native_failure_policy"=>"record","diffusion"=>true,"end_drift_when_no_field"=>false,"self_repulsion"=>false,"drift_dt_ns"=>N.DT,"nominal_drift_cap_ns"=>N.HORIZON_NS,"units"=>Dict("charge"=>"fC","current"=>"nA","voltage"=>"V","energy"=>"keV","time"=>"ns"),"grouping_policy"=>d["grouping_policy"],"ledger"=>d["ledger"],"limitations"=>W.LIMITATIONS)
    files=["scalars.jsonl","scalars.csv","endpoints.jsonl","endpoints.csv","truth.jsonl","truth.csv","traces.jsonl","signals.csv"]
    try
        report["resource_preflight"]=C.resource_plan(a.sim,cfg)
        guard=W.G.install!();report["boundary_guard"]=guard
        cp(o["request"],joinpath(out,"request-input.json"));cp(o["profile"],joinpath(out,"profile-input.json"));E.save(joinpath(out,"profile.json"),a.profile.profile);E.save(joinpath(out,"readout-config.json"),c);report["config_sha256"]=E.hashfile(joinpath(out,"readout-config.json"))
        E.save(joinpath(out,"input-contract.json"),d);E.save(joinpath(out,"input-prepared.json"),a.meta);E.save(joinpath(out,"run.json"),report);progress(out,started,stage,"running",counts,d["primary_count"])
        solver,timing=Base.invokelatest(Q.solve_fields!,a.sim,cfg,Q.prepare_backend("cpu");sor_consts=1.0,potential_rechecks=4)
        report["solver"]=solver;report["field_timings"]=timing;report["field_fingerprint"]=C.field_fingerprint(a.sim,cfg.contact)
        stage="native_and_readout";replay_start=time();native_s=0.;electronics_s=0.
        for file in files;push!(handles,open(joinpath(out,file),"w"));end
        sj,sc,ej,ec,tj,tc,traces,signals=handles
        println(sc,join(NR.SCALAR_COLUMNS,','));println(ec,"event_id,global_decay_id,group_id,raw_row_index,parcel_index,seed_uint64,record_json");println(tc,"event_id,global_decay_id,record_json");println(signals,"event_id,global_decay_id,group_id,time_since_origin_ns,induced_equivalent_energy_keV")
        failures=Ref{Union{Nothing,IO}}(nothing)
        function consume(e)
            id=e["event_id"];globalid=e["global_decay_id"];gs=e["pulse_groups"];energy=sum((s["energy_keV"] for s in e["steps"]);init=0.)
            println(tj,JSON.json(e));println(tc,join(E.csvcell.((id,globalid,e)),','))
            counts["initial_primaries"]+=1;counts["initial_decays"]+=1;counts["zero_deposit_primaries"]+=energy==0;counts["line_photons"]+=e["line_photon_count"];counts["decay_photons"]+=e["decay_photon_count"]
            NR.scalar!(sj,sc,Dict("record_kind"=>"decay","event_id"=>id,"global_decay_id"=>globalid,"group_id"=>nothing,"deposited_energy_keV"=>energy,"pulse_count"=>length(gs),"zero_deposit"=>energy==0,"raw_row_indices"=>[s["raw_row_index"] for s in e["steps"]],"line_photon_count"=>e["line_photon_count"],"decay_photon_count"=>e["decay_photon_count"],"material_energy_keV"=>e["material_energy_keV"],"full_energy_closure"=>nothing));NR.addhist!(hist,"deposited_per_decay",energy)
            byrow=Dict(s["raw_row_index"]=>s for s in e["steps"])
            for g in gs
                gid=g["group_id"];origin=g["origin_time_ns"];steps=[byrow[i] for i in g["row_indices"]]
                event=Dict("event_id"=>id,"primary_time_ns"=>origin,"steps"=>steps);t0=time();attempt=W.guarded_attempt(()->N.native_event(event,a.sim,cfg,16,2609261),"record");native_s+=time()-t0
                if attempt.error!==nothing
                    rec=NR.failed_pulse(e,g,steps,o,attempt.error,d["source_lh5_sha256"])
                    if failures[]===nothing;failures[]=open(joinpath(out,"native-failures.jsonl"),"w");push!(handles,failures[]);push!(files,"native-failures.jsonl");end
                    println(failures[],JSON.json(Dict("record_kind"=>"native_failure_diagnostic","pulse"=>rec,"original_event"=>e,"original_group"=>g,"original_steps"=>steps,"settings"=>report)))
                    NR.scalar!(sj,sc,rec);counts["groups"]+=1;counts["native_failed_groups"]+=1;counts["rejected"]+=1;NR.group_hist!(hist,rec["deposited_energy_keV"],nothing,nothing,a.eion);continue
                end
                result=attempt.result;t,q=result.times,result.signal;R.check(all(isfinite,q) && first(q)==0,"Invalid native cumulative charge")
                t0=time();r=P.process(t,q,c,a.eion,a.calibration,a.matrix;horizon_ns=g["horizon_ns"]);electronics_s+=time()-t0;R.check(r["current_balance"]["passed"],"Current/charge balance failed")
                counts["groups"]+=1;counts[r["accepted"] ? "accepted" : "rejected"]+=1;counts["readout_rejected"]+=!r["accepted"];counts["saturated"]+=r["saturated"];counts["native_charge_samples"]+=length(t);counts["analog_samples"]+=r["original_sample_count"]
                println(traces,JSON.json(Dict("event_id"=>id,"global_decay_id"=>globalid,"group_id"=>gid,"origin_time_ns"=>origin,"trace"=>r["trace"])))
                for (time,value) in zip(t,q);println(signals,join(E.csvcell.((id,globalid,gid,time,value)),','));end
                for step in result.steps, endpoint in step["endpoints"]
                    row=step["raw_row_index"];rec=Dict("event_id"=>id,"global_decay_id"=>globalid,"group_id"=>gid,"raw_row_index"=>row,"source_lh5_sha256"=>d["source_lh5_sha256"],"raw_table"=>"stp/germanium","original_time_ns"=>byrow[row]["time_ns"],"origin_time_ns"=>origin,"deposition_delay_ns"=>step["deposition_delay_ns"],"deposited_energy_keV"=>step["deposited_energy_keV"],"parcel_weight_keV"=>step["parcel_weight_keV"],"step_final_induced_keV"=>step["final_induced_keV"],"parcel_index"=>endpoint["parcel_index"],"seed_uint64"=>string(N.parcel_seed(2609261,id,row,endpoint["parcel_index"])),"endpoint"=>endpoint)
                    NR.endpoint!(ej,ec,rec)
                end
                pop!(r,"trace");rec=Dict("record_kind"=>"pulse","event_id"=>id,"global_decay_id"=>globalid,"group_id"=>gid,"origin_time_ns"=>origin,"group"=>g,"deposited_energy_keV"=>sum(s["energy_keV"] for s in steps),"final_induced_keV"=>last(q),"raw_row_indices"=>g["row_indices"],"transport_flags"=>N.flags(result.steps),"readout"=>r,"accepted"=>r["accepted"],"rejection_reason"=>r["rejection_reason"],"trace_saved"=>true,"charge_end_ns"=>last(t),"native_any_negative_charge"=>any(x->x<0,q),"native_min_charge_keV"=>minimum(q),"native_max_charge_keV"=>maximum(q),"parcels"=>16,"seed_family"=>2609261)
                NR.scalar!(sj,sc,rec);NR.group_hist!(hist,rec["deposited_energy_keV"],q,r,a.eion)
            end
            progress(out,started,stage,"running",counts,d["primary_count"])
        end
        S.foreach_decay(consume,a.stream)
        for io in handles;close(io);end;empty!(handles)
        report["native_drift_and_charge_seconds"]=native_s;report["electronics_seconds"]=electronics_s;report["replay_readout_export_seconds"]=time()-replay_start
        stage="final_integrity";R.check(counts["initial_primaries"]==d["primary_count"] && counts["accepted"]+counts["rejected"]==counts["groups"] && counts["rejected"]==counts["native_failed_groups"]+counts["readout_rejected"],"Output census mismatch")
        R.check(C.field_fingerprint(a.sim,cfg.contact)==report["field_fingerprint"],"Response altered selected fields");S.recheck(a.stream);P.validate_resolved(JSON.parsefile(joinpath(out,"readout-config.json")),a.profile.profile,d["primary_count"])
        for (ref,h) in request["source_sha256"];R.check(E.hashfile(C.relative_file(ref))==h,"Consumer source changed");end
        R.check(E.hashfile(o["request"])==report["request_sha256"] && E.hashfile(o["profile"])==a.profile.sha256,"Request/profile changed during processing")
        NR.export_hist(out,hist,counts,a.calibration);append!(files,["request-input.json","profile.json","profile-input.json","readout-config.json","input-contract.json","input-prepared.json","histograms.json","histograms.csv"])
        report["status"]=counts["native_failed_groups"]>0 ? "completed_with_native_failures" : "completed_provisional_native_response";report["artifacts"]=Dict(f=>E.hashfile(joinpath(out,f)) for f in files)
        W.summary_html(out,report);report["artifacts"]["summary.html"]=E.hashfile(joinpath(out,"summary.html"));report["artifact_bytes"]=Dict(f=>filesize(joinpath(out,f)) for f in keys(report["artifacts"]));progress(out,started,"completed",report["status"],counts,d["primary_count"])
    catch err
        report["status"]="failed";report["failure_stage"]=stage;report["error_type"]=string(typeof(err));report["error"]=sprint(showerror,err);progress(out,started,stage,"failed",counts,d["primary_count"]);rethrow()
    finally
        for io in handles;isopen(io) && close(io);end
        report["solve_replay_readout_export_wall_seconds"]=time()-started;report["timing_scope"]="Measured native process work; excludes startup/preflight; serial original-model solve and streamed response";report["process_peak_rss_bytes"]=try Sys.maxrss() catch;nothing end
        E.save(joinpath(out,"run.json"),report)
    end
    println(JSON.json(Dict("status"=>report["status"],"counts"=>counts,"seconds"=>report["solve_replay_readout_export_wall_seconds"])));report
end
function main(args=ARGS)
    o,request=request_options(args);Q.environment("cpu");E.environment();start=time();a=prepare(o,request;calibrate=!o["inspect"])
    if o["inspect"];println(JSON.json(Dict("kind"=>"catalog_native_inspection_v1","status"=>"checked","model_id"=>a.document["model_id"],"primary_count"=>a.document["primary_count"],"science_calls"=>0,"calibration_calls"=>0,"seconds"=>time()-start)));return nothing;end
    report=run(o,a,request);report
end
end
if abspath(PROGRAM_FILE)==@__FILE__;CatalogResponse.main();end
