# Additive serial-batch bridge; the preserved SSD and electronics kernels do the science.
include("catalog_native_response.jl")
include("batch_decay_stream.jl")
module BatchNativeResponse
using ..CatalogResponse, ..BatchDecayStream, ..BatchNativeContract, JSON, Unitful, Serialization
const CR=CatalogResponse;const W=CR.W;const C=CR.C;const S=BatchDecayStream;const B=BatchNativeContract
const NR=W.NR;const R=W.R;const Q=W.Q;const E=W.E;const P=W.P;const N=W.N;const D=S.D
const SOURCES=Tuple(unique([CR.SOURCES...,"batch_native_contract.jl","batch_decay_stream.jl","batch_native_response.jl"]))
const ADDED_MODELS=("AK01","SAP16","SAP17","Bipolar_reference_3D","KL01_3D")
const COMMON=Set(("kind","parent_configuration_sha256","selection","operating_model","numerics","source_sha256","shared_prepared_ref","shared_prepared_sha256","profile_ref","profile_sha256"))
const RESPONSE=Set(("batch","stream_ref","stream_sha256","native_preparation_ref","native_preparation_sha256"))
hash(x)=x isa String && occursin(r"^[0-9a-f]{64}$",x)
ref(path)=replace(relpath(path,Q.ROOT),'\\'=>'/')
catalog(d)=d["selection"]["detector"] in ADDED_MODELS
function expected_operating(mc)
    Dict("variant_id"=>mc["model_id"],"source_model_sha256"=>mc["model_sha256"],"effective_model_sha256"=>mc["model_sha256"],
        "signed_bias_V"=>mc["wiring_factor"]*mc["bias_span_V"],"contact_potentials_V"=>mc["contact_potentials_V"],
        "readout_contact_id"=>mc["readout_contact_id"],"wiring_factor"=>mc["wiring_factor"],"field_cache_used"=>false,
        "annealing_time_minutes"=>nothing,"qualification"=>mc["qualification"],"calibration"=>"independent 500 keV injection through recorded fixed wiring")
end
function validate_selection(s)
    R.check(s isa AbstractDict && Set(keys(s))==Set(("name","cryostat","detector","source","pose","primary_count","seed","threads","electronics")),"Wrong batch selection fields")
    R.check(s["name"] isa String && occursin(r"^[A-Za-z0-9_-]{1,48}$",s["name"]) && s["cryostat"]=="lbnl_modular_nominal_v1" && s["pose"]=="nominal","Unsupported batch run/cryostat/pose")
    R.check(s["detector"] in (keys(D.SIGNED_BIAS)...,ADDED_MODELS...) && B.integer(s["primary_count"]) && 1<=s["primary_count"]<=B.MAX_SAFE_INTEGER,"Unsupported batch model/count")
    R.check(B.integer(s["threads"]) && s["threads"] in (1,2) && Threads.nthreads()==s["threads"] && B.integer(s["seed"]) && 1<=s["seed"]<=2_147_483_646,"Wrong batch threads/seed")
end
function options(args)
    R.check(length(args)==4 && args[1]=="--request" && args[3] in ("--prepare","--respond"),"Use --request FILE --prepare NEW_DIRECTORY or --respond NEW_DIRECTORY")
    path=S.S.localfile(args[2]);R.check(filesize(path)<=2_000_000,"Oversized batch native request")
    d=JSON.parsefile(path);validate_selection(d["selection"]);s=d["selection"];prepare=args[3]=="--prepare"
    fields=union(COMMON,prepare ? Set{String}() : RESPONSE,catalog(d) ? Set(["model_contract"]) : Set{String}())
    R.check(Set(keys(d))==fields && d["kind"]=="batch_native_request_v1" && hash(d["parent_configuration_sha256"]),"Wrong versioned batch native request")
    base=".local/runs/"*s["name"];shared=S.relative_file(d["shared_prepared_ref"]);profile=S.relative_file(d["profile_ref"])
    R.check(d["shared_prepared_ref"]==base*"/shared/transport/prepared.json" && d["profile_ref"]==base*"/electronics/profile.json","Shared preparation/profile belongs to another parent")
    R.check(E.hashfile(shared)==d["shared_prepared_sha256"] && E.hashfile(profile)==d["profile_sha256"],"Changed shared preparation/profile")
    p=JSON.parsefile(shared);mc=p["model_contract"];op=d["operating_model"]
    R.check(p["kind"]=="batch_shared_transport_prepared_v1" && p["status"]=="complete" && p["producer_adapter"]==S.ADAPTER && p["model_id"]==s["detector"] && p["source_id"]==s["source"] && p["checked_transport"]["selection"]==s,"Shared transport selection differs")
    S.source(p["source_contract"],p["source_mode"])
    S.model_contract(mc);R.check(p["geometry_checks"]["overlaps_passed"]===true && p["geometry_checks"]["source_inside_fill"]===true,"Unchecked shared cryostat geometry")
    for (r,h) in p["files_sha256"];R.check(E.hashfile(S.relative_file(r))==h,"Changed shared transport file: "*r);end
    if catalog(d)
        R.check(mc==d["model_contract"] && op==expected_operating(mc) && d["numerics"]==C.numerics(mc),"Changed canonical catalog settings")
    else
        signed=D.SIGNED_BIAS[s["detector"]]
        R.check(op["signed_bias_V"]==signed && op["contact_potentials_V"]==Dict("1"=>0,"2"=>signed) && op["wiring_factor"]==D.WIRING[s["detector"]] && op["readout_contact_id"]==1,"Changed original operating bias/wiring")
        for k in ("variant_id","source_model_sha256","effective_model_sha256","contact_potentials_V","readout_contact_id")
            R.check(op[k]==mc[k],"Changed original model variant: "*k)
        end
        R.check(d["numerics"]==Dict("parcels"=>16,"native_seed_family"=>2609261,"drift_dt_ns"=>2,"drift_cap_ns"=>10000,"stored_temperature_K"=>78,"runtime_temperature_K"=>77,"bias_V"=>abs(signed),"native_failure_policy"=>"record","models_serial"=>true,"stages_serial"=>true),"Changed original native settings")
    end
    required=Set("simulation/"*n for n in SOURCES)
    R.check(d["source_sha256"] isa AbstractDict && issubset(required,Set(keys(d["source_sha256"]))),"Incomplete batch native source closure")
    for (r,h) in d["source_sha256"];R.check(hash(h) && E.hashfile(S.relative_file(r))==h,"Changed batch native source: "*r);end
    if prepare
        expected=joinpath(Q.ROOT,base,"shared/native")
        R.check(ref(path)==base*"/native-prepare-request.json","Prepare request belongs to another parent")
    else
        b=B.descriptor(d["batch"]);R.check(b["global_initial_offset"]+b["primary_count"]<=s["primary_count"],"Batch extends beyond parent census")
        batchbase=base*"/batches/b"*lpad(string(b["batch_index"]),10,'0')
        R.check(d["stream_ref"]==batchbase*"/transport/stream/manifest.json" && d["native_preparation_ref"]==base*"/shared/native/preparation.json" && ref(path)==batchbase*"/native-request.json","Response inputs belong to another parent/batch")
        for (r,h) in ((d["stream_ref"],d["stream_sha256"]),(d["native_preparation_ref"],d["native_preparation_sha256"]))
            R.check(E.hashfile(S.relative_file(r))==h,"Changed response input")
        end
        expected=joinpath(Q.ROOT,batchbase,"response")
    end
    R.check(abspath(args[4])==abspath(expected),"Native output belongs to another parent/batch");Q.validate_output(args[4])
    (request=path,document=d,shared=p,profile_path=profile,output=args[4],prepare=prepare)
end
function cfg(d,out)
    mc=d["operating_model"]
    Q.parse_args(["--model",d["selection"]["detector"],"--contact",string(mc["readout_contact_id"]),"--position-mm","3,0,5","--precision","64","--dt-ns","2","--min-grid-mm",catalog(d) ? "0.25" : "0.05","--max-iterations","50000","--output",out])
end
function configured_output(d,path)
    config=cfg(d,path) # The CLI parser requires the target to be nonexistent.
    (config=config,output=Q.reserve_output(path))
end
function simulation(o)
    mc=o.shared["model_contract"]
    catalog(o.document) && return C.simulation(mc).sim
    original=R.SSD.Simulation{Float64}(S.model_contract(mc));config=deepcopy(original.config_dict)
    R.check(original.detector.semiconductor.temperature==78,"Stored original temperature changed")
    sc=config["detectors"][1]["semiconductor"];sc["temperature"]=77.0
    haskey(sc["charge_drift_model"],"temperature") && (sc["charge_drift_model"]["temperature"]=77.0)
    sim=R.SSD.Simulation{Float64}(config);cdm=sim.detector.semiconductor.charge_drift_model
    R.check(sim.detector.semiconductor.temperature==77 && (!hasproperty(cdm,:temperature) || cdm.temperature==77),"Explicit runtime temperature failed")
    sim
end
function geometry(o,sim)
    catalog(o.document) ? C.validate_probes(o.shared,sim) : NR.geometry(o.shared,sim,true)
end
function bindings(o)
    d=o.document
    Dict{String,Any}("parent_configuration_sha256"=>d["parent_configuration_sha256"],"shared_prepared_sha256"=>d["shared_prepared_sha256"],
        "profile_sha256"=>d["profile_sha256"],"selection"=>d["selection"],"operating_model"=>d["operating_model"],"model_contract"=>o.shared["model_contract"],
        "numerics"=>d["numerics"],"source_sha256"=>d["source_sha256"],"environment"=>Q.environment("cpu"),"readout_environment"=>E.environment())
end
function unchanged(o)
    d=o.document
    R.check(E.hashfile(S.relative_file(d["shared_prepared_ref"]))==d["shared_prepared_sha256"] && E.hashfile(o.profile_path)==d["profile_sha256"],"Shared native inputs changed")
    for (r,h) in d["source_sha256"];R.check(E.hashfile(S.relative_file(r))==h,"Native source changed: "*r);end
    S.model_contract(o.shared["model_contract"])
    for (r,h) in o.shared["files_sha256"];R.check(E.hashfile(S.relative_file(r))==h,"Shared geometry changed");end
end
function prepare(o)
    d=o.document;reserved=configured_output(d,o.output);out=reserved.output;config=reserved.config;start=time();report=bindings(o)
    merge!(report,Dict("kind"=>"batch_native_preparation_v1","status"=>"running","request_sha256"=>E.hashfile(o.request),"independent_calibration_calls"=>0,"field_solution_calls"=>0))
    try
        sim=simulation(o);profile=P.load(o.profile_path);R.check(profile.profile["settings"]==d["selection"]["electronics"],"Selected electronics differ")
        geom=geometry(o,sim);P.window_config(profile.config,o.shared["grouping_policy"]["horizon_ns"],N.DT)
        report["resource_preflight"]=C.resource_plan(sim,config);report["geometry_checks"]=geom
        E.save(joinpath(out,"preparation.json"),report)
        solver,timings=Base.invokelatest(Q.solve_fields!,sim,config,Q.prepare_backend("cpu");sor_consts=1.0,potential_rechecks=4)
        report["solver"]=solver;report["field_timings"]=timings;report["field_solution_calls"]=1
        eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation);matrix=E.transition(profile.config,N.DT);t=time()
        model=d["selection"]["detector"]
        negative=model==W.SP.MODEL ? W.SP.negative_calibration(profile.config,eion,N.DT,matrix) : model=="KMRC01_candidate" ? W.WR.RP.negative_calibration(profile.config,eion,N.DT,matrix) : nothing
        cal=negative===nothing ? P.calibration(profile.config,eion,N.DT,matrix) : negative.calibration
        report["calibration_seconds"]=time()-t;report["independent_calibration_calls"]=1
        state=(sim=sim,matrix=matrix,calibration=cal,eion=eion,injection=negative===nothing ? nothing : negative.injection)
        statepath=joinpath(out,"state.bin");serialize(statepath,state);R.check(0<filesize(statepath)<=B.MAX_CACHE_BYTES,"Prepared native state exceeds bounded cache size")
        report["state_ref"]=ref(statepath);report["state_sha256"]=E.hashfile(statepath);report["state_bytes"]=filesize(statepath)
        report["field_fingerprint"]=C.field_fingerprint(sim,config.contact);report["calibration"]=cal;report["ionisation_energy_eV"]=eion
        report["state_scope"]="Owned fresh run-local Julia state only; pinned runtime/source and consumed-byte SHA verified before loading. Not an external import format."
        E.save(joinpath(out,"profile.json"),profile.profile);E.save(joinpath(out,"readout-config.json"),profile.config)
        negative!==nothing && E.save(joinpath(out,"negative-injection.json"),negative.injection)
        report["artifacts"]=Dict(n=>E.hashfile(joinpath(out,n)) for n in readdir(out) if n!="preparation.json")
        unchanged(o);R.check(E.hashfile(o.request)==report["request_sha256"],"Preparation request changed");report["status"]="complete"
    catch err
        report["status"]="failed";report["error"]=sprint(showerror,err);rethrow()
    finally
        report["seconds"]=time()-start;report["process_peak_rss_bytes"]=try Sys.maxrss() catch;nothing end
        E.save(joinpath(out,"preparation.json"),report)
    end
    report
end
function load_state(o)
    d=o.document;path=S.relative_file(d["native_preparation_ref"]);p=JSON.parsefile(path)
    R.check(p["kind"]=="batch_native_preparation_v1" && p["status"]=="complete" && p["independent_calibration_calls"]==1 && p["field_solution_calls"]==1,"Incomplete shared native preparation")
    for (k,v) in bindings(o);R.check(p[k]==v,"Prepared native binding changed: "*k);end
    expected=".local/runs/"*d["selection"]["name"]*"/shared/native/state.bin"
    R.check(p["state_ref"]==expected && dirname(S.relative_file(expected))==dirname(path),"Native state outside owned shared preparation")
    for (n,h) in p["artifacts"]
        R.check(basename(n)==n && E.hashfile(joinpath(dirname(path),n))==h,"Native preparation artifact changed")
    end
    statepath=S.relative_file(expected)
    R.check(B.integer(p["state_bytes"]) && 0<p["state_bytes"]<=B.MAX_CACHE_BYTES && filesize(statepath)==p["state_bytes"],"Native state file exceeds bounds/changed size")
    raw=read(statepath);R.check(length(raw)==p["state_bytes"] && p["artifacts"]["state.bin"]==p["state_sha256"],"Native state byte census changed")
    state=B.verified_deserialize(raw,p["state_sha256"]);empty!(raw)
    R.check(C.field_fingerprint(state.sim,d["operating_model"]["readout_contact_id"])==p["field_fingerprint"] && state.calibration==p["calibration"] && state.eion==p["ionisation_energy_eV"],"Prepared state content changed")
    contacts=Dict(string(c.id)=>c.potential for c in state.sim.detector.contacts)
    R.check(contacts==d["operating_model"]["contact_potentials_V"] && state.sim.detector.semiconductor.temperature==d["numerics"]["runtime_temperature_K"],"Cached native operating values changed")
    state,p
end
function response(o)
    d=o.document;stream=S.inspect(S.relative_file(d["stream_ref"]));m=stream.manifest;b=B.descriptor(d["batch"])
    R.check(m["batch"]==b && m["shared_prepared_sha256"]==d["shared_prepared_sha256"] && m["model_contract"]==o.shared["model_contract"],"Batch source/native preparation differs")
    state,prep=load_state(o);sim=state.sim;config=cfg(d,o.output);profile=P.load(o.profile_path);c=P.for_census(profile.profile,b["primary_count"])
    R.check(profile.profile["settings"]==d["selection"]["electronics"],"Response electronics differs")
    geometry(o,sim);S.foreach_decay(e->R.validate_deposits(Dict("events"=>[e]),sim),stream);S.recheck(stream)
    out=Q.reserve_output(o.output);start=time();report=bindings(o);counts=Dict{String,Any}(k=>0 for k in ("initial_primaries","initial_decays","zero_deposit_primaries","groups","accepted","rejected","readout_rejected","native_failed_groups","saturated","native_charge_samples","analog_samples","line_photons","decay_photons"))
    m["source_mode"]=="registered_decay" && (counts["line_photon_counts"]=Dict(x["name"]=>0 for x in m["source_contract"]["diagnostic_lines"]))
    merge!(report,Dict("kind"=>"batch_native_response_v1","status"=>"running","batch"=>b,"request_sha256"=>E.hashfile(o.request),"input_sha256"=>d["stream_sha256"],"source_lh5_sha256"=>m["source_lh5_sha256"],"native_preparation_sha256"=>d["native_preparation_sha256"],"state_sha256"=>prep["state_sha256"],"counts"=>counts,
        "model_id"=>m["model_id"],"model_sha256"=>m["model_sha256"],"source_id"=>m["source_id"],"source_contract"=>m["source_contract"],"grouping_policy"=>m["grouping_policy"],"ledger"=>m["ledger"],"calibration"=>state.calibration,"ionisation_energy_eV"=>state.eion,
        "new_field_solution"=>false,"field_solution_calls"=>0,"independent_calibration_calls"=>0,"calibration_calls"=>0,"shared_preparation_calibration_calls"=>1,"field_fingerprint"=>prep["field_fingerprint"],"original_field_timings"=>prep["field_timings"],"original_calibration_seconds"=>prep["calibration_seconds"],
        "seed_family"=>2609261,"seed_rule"=>B.SEED_RULE,"parcels"=>16,"native_failure_policy"=>"record","diffusion"=>true,"end_drift_when_no_field"=>false,"self_repulsion"=>false,"units"=>Dict("charge"=>"fC","current"=>"nA","voltage"=>"V","energy"=>"keV","time"=>"ns"),"limitations"=>W.LIMITATIONS))
    hist=Dict{String,Dict{Int,Int}}();handles=IO[];files=String[];native_s=0.;electronics_s=0.;stage="native_and_readout"
    function opened(name)
        push!(files,name);io=open(joinpath(out,name),"w");push!(handles,io);io
    end
    try
        report["boundary_guard"]=W.G.install!();E.save(joinpath(out,"readout-config.json"),c);E.save(joinpath(out,"profile.json"),profile.profile);report["config_sha256"]=E.hashfile(joinpath(out,"readout-config.json"));E.save(joinpath(out,"run.json"),report)
        sj=opened("scalars.jsonl");sc=opened("scalars.csv");ej=opened("endpoints.jsonl");ec=opened("endpoints.csv");tj=opened("truth.jsonl");traces=opened("traces.jsonl");signals=opened("signals.csv");failures=Ref{Union{Nothing,IO}}(nothing)
        println(sc,join(NR.SCALAR_COLUMNS,','));println(ec,"event_id,global_decay_id,group_id,raw_row_index,parcel_index,seed_uint64,record_json");println(signals,"event_id,global_decay_id,batch_index,local_initial_id,global_initial_id,group_id,time_since_origin_ns,induced_equivalent_energy_keV")
        function consume(e)
            ids=B.identity(e,b);energy=sum((x["energy_keV"] for x in e["steps"]);init=0.);gs=e["pulse_groups"]
            println(tj,JSON.json(e));counts["initial_primaries"]+=1;counts["initial_decays"]+=1;counts["zero_deposit_primaries"]+=energy==0
            counts["line_photons"]+=e["line_photon_count"];counts["decay_photons"]+=e["decay_photon_count"]
            if haskey(counts,"line_photon_counts")
                for (k,v) in e["line_photon_counts"];counts["line_photon_counts"][k]+=v;end
            end
            rec=merge(Dict("record_kind"=>"decay","group_id"=>nothing,"deposited_energy_keV"=>energy,"pulse_count"=>length(gs),"zero_deposit"=>energy==0,"raw_row_indices"=>[x["raw_row_index"] for x in e["steps"]],"line_photon_count"=>e["line_photon_count"],"decay_photon_count"=>e["decay_photon_count"],"material_energy_keV"=>e["material_energy_keV"],"full_energy_closure"=>nothing),ids)
            NR.scalar!(sj,sc,rec);NR.addhist!(hist,"deposited_per_decay",energy);byrow=Dict(x["raw_row_index"]=>x for x in e["steps"])
            for g in gs
                steps=[byrow[i] for i in g["row_indices"]];event=B.native_event_input(e,g,b);t0=time();attempt=W.guarded_attempt(()->N.native_event(event,sim,config,16,2609261),"record");native_s+=time()-t0
                counts["groups"]+=1
                if attempt.error!==nothing
                    rec=merge(NR.failed_pulse(e,g,steps,Dict("parcels"=>16,"seed"=>2609261),attempt.error,m["source_lh5_sha256"]),ids)
                    failures[]===nothing && (failures[]=opened("native-failures.jsonl"))
                    println(failures[],JSON.json(Dict("record_kind"=>"native_failure_diagnostic","pulse"=>rec,"original_event"=>e,"original_group"=>g,"original_steps"=>steps,"native_preparation_sha256"=>d["native_preparation_sha256"],"seed_rule"=>B.SEED_RULE)))
                    NR.scalar!(sj,sc,rec);counts["native_failed_groups"]+=1;counts["rejected"]+=1;NR.group_hist!(hist,rec["deposited_energy_keV"],nothing,nothing,state.eion);continue
                end
                result=attempt.result;t,q=result.times,result.signal;R.check(all(isfinite,q) && first(q)==0,"Invalid signed cumulative charge")
                t0=time();r=catalog(d) ? P.process(t,q,c,state.eion,state.calibration,state.matrix;horizon_ns=g["horizon_ns"]) : W.process_response(t,q,c,state.eion,state.calibration,state.matrix,m["model_id"];horizon_ns=g["horizon_ns"]);electronics_s+=time()-t0
                R.check(r["current_balance"]["passed"],"Current/charge balance failed");counts[r["accepted"] ? "accepted" : "rejected"]+=1;counts["readout_rejected"]+=!r["accepted"];counts["saturated"]+=r["saturated"];counts["native_charge_samples"]+=length(t);counts["analog_samples"]+=r["original_sample_count"]
                selected=counts["groups"]<=16
                selected && println(traces,JSON.json(merge(Dict("group_id"=>g["group_id"],"origin_time_ns"=>g["origin_time_ns"],"trace"=>r["trace"]),ids)))
                for (time,value) in zip(t,q);println(signals,join(E.csvcell.((ids["event_id"],ids["global_decay_id"],ids["batch_index"],ids["local_initial_id"],ids["global_initial_id"],g["group_id"],time,value)),','));end
                for step in result.steps, endpoint in step["endpoints"]
                    row=step["raw_row_index"];seed=B.parcel_seed(2609261,ids["global_initial_id"],row,endpoint["parcel_index"])
                    rec=merge(Dict("group_id"=>g["group_id"],"raw_row_index"=>row,"parcel_index"=>endpoint["parcel_index"],"seed_uint64"=>string(seed),"source_lh5_sha256"=>m["source_lh5_sha256"],"raw_table"=>"stp/germanium","original_time_ns"=>byrow[row]["time_ns"],"origin_time_ns"=>g["origin_time_ns"],"deposition_delay_ns"=>step["deposition_delay_ns"],"deposited_energy_keV"=>step["deposited_energy_keV"],"parcel_weight_keV"=>step["parcel_weight_keV"],"step_final_induced_keV"=>step["final_induced_keV"],"endpoint"=>endpoint),ids)
                    NR.endpoint!(ej,ec,rec)
                end
                pop!(r,"trace");edep=sum(x["energy_keV"] for x in steps)
                rec=merge(Dict("record_kind"=>"pulse","group_id"=>g["group_id"],"origin_time_ns"=>g["origin_time_ns"],"group"=>g,"deposited_energy_keV"=>edep,"final_induced_keV"=>last(q),"raw_row_indices"=>g["row_indices"],"transport_flags"=>N.flags(result.steps),"readout"=>r,"accepted"=>r["accepted"],"rejection_reason"=>r["rejection_reason"],"trace_saved"=>selected,"charge_end_ns"=>last(t),"native_any_negative_charge"=>any(x->x<0,q),"native_min_charge_keV"=>minimum(q),"native_max_charge_keV"=>maximum(q),"parcels"=>16,"seed_family"=>2609261),ids)
                NR.scalar!(sj,sc,rec);NR.group_hist!(hist,edep,q,r,state.eion)
            end
            W.progress(out,start,stage,"running",counts,b["primary_count"])
        end
        S.foreach_decay(consume,stream)
        for io in handles;close(io);end;empty!(handles)
        R.check(counts["initial_primaries"]==b["primary_count"] && counts["accepted"]+counts["rejected"]==counts["groups"] && counts["rejected"]==counts["native_failed_groups"]+counts["readout_rejected"],"Batch output census mismatch")
        P.validate_resolved(JSON.parsefile(joinpath(out,"readout-config.json")),profile.profile,b["primary_count"])
        R.check(C.field_fingerprint(sim,config.contact)==prep["field_fingerprint"],"Response modified shared native fields")
        unchanged(o);S.recheck(stream)
        R.check(E.hashfile(o.request)==report["request_sha256"] && E.hashfile(S.relative_file(d["native_preparation_ref"]))==d["native_preparation_sha256"],"Response request/preparation changed")
        NR.export_hist(out,hist,counts,state.calibration);append!(files,["histograms.json","histograms.csv","profile.json","readout-config.json"])
        report["artifacts"]=Dict(n=>E.hashfile(joinpath(out,n)) for n in files);report["artifact_bytes"]=Dict(n=>filesize(joinpath(out,n)) for n in files)
        report["status"]=counts["native_failed_groups"]>0 ? "completed_with_native_failures" : "completed_provisional_native_response"
        W.progress(out,start,"completed",report["status"],counts,b["primary_count"])
    catch err
        report["status"]="failed";report["failure_stage"]=stage;report["error"]=sprint(showerror,err);rethrow()
    finally
        for io in handles;isopen(io) && close(io);end
        report["native_drift_and_charge_seconds"]=native_s;report["electronics_seconds"]=electronics_s
        report["solve_replay_readout_export_wall_seconds"]=time()-start;report["process_peak_rss_bytes"]=try Sys.maxrss() catch;nothing end
        report["timing_scope"]="This batch process only; shared field/calibration original times are separate and never repeated as new work. Startup/preflight excluded."
        E.save(joinpath(out,"run.json"),report)
    end
    report
end
function main(args=ARGS)
    o=options(args);Q.environment("cpu");E.environment();result=o.prepare ? prepare(o) : response(o)
    println(JSON.json(Dict("kind"=>result["kind"],"status"=>result["status"],"counts"=>get(result,"counts",nothing))));result
end
end
if abspath(PROGRAM_FILE)==@__FILE__;BatchNativeResponse.main();end
