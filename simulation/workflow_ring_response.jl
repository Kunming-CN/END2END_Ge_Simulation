# Fresh Control ring orchestration; frozen M13 producers remain byte-exact.
# The run loop is copied from native_response.jl solely to inject the existing
# KM processor. Solver, native-event, grouping, failure and readout algorithms
# are called from their original modules; no numerical kernel is duplicated.
include("ring_response.jl")
include("ring_polarity.jl")
module WorkflowRingResponse
using ..RingResponse, ..RingPolarity, JSON, Unitful, SolidStateDetectors
const RR=RingResponse;const NR=RR.NR;const RP=RingPolarity
const RS=RR.RS;const S=RR.S;const R=RR.R;const Q=RR.Q;const E=RR.E;const P=RR.P;const N=RR.N
const SOURCES=(NR.SOURCES...,"ring_stream.jl","ring_response.jl","ring_polarity.jl","workflow_ring_response.jl")
const NATIVE_FAILURE_MESSAGES=NR.NATIVE_FAILURE_MESSAGES;const ENDPOINT_UNAVAILABLE=NR.ENDPOINT_UNAVAILABLE
const SCALAR_COLUMNS=NR.SCALAR_COLUMNS
const addhist! =NR.addhist!;const scalar! =NR.scalar!;const endpoint! =NR.endpoint!
const event_groups=NR.event_groups;const native_attempt=NR.native_attempt
const failed_pulse=NR.failed_pulse;const group_hist! =NR.group_hist!;const export_hist=NR.export_hist

function request_options(args)
    R.check(length(args)==4 && args[1]=="--request" && args[3]=="--output","Use --request FILE --output NEW_DIRECTORY")
    path=abspath(args[2])
    R.check(isfile(path) && !islink(path) && filesize(path)<=2_000_000 && Q.childof(realpath(path),realpath(Q.ROOT)),"Missing/oversized ring request")
    d=JSON.parsefile(path)
    R.check(Set(keys(d))==Set(("kind","configuration_sha256","selection","operating_model","profile_ref","profile_sha256","stream_ref","stream_sha256","source_sha256","numerics")) && d["kind"]=="workflow_ring_request_v1","Wrong ring request")
    s=d["selection"];model=s["detector"]
    R.check(Set(keys(s))==Set(("name","cryostat","detector","source","pose","primary_count","seed","threads","electronics")) && s["name"] isa String && occursin(r"^[A-Za-z0-9_-]{1,48}$",s["name"]),"Wrong ring selection fields/name")
    R.check(model in ("GeRC02","KMRC01_candidate") && s["cryostat"]=="lbnl_modular_nominal_v1" && s["source"]=="cs137_point_decay_v1" && s["pose"]=="nominal" && s["primary_count"] in (20,500),"Unsupported ring tuple")
    R.check(s["threads"] isa Integer && !(s["threads"] isa Bool) && s["threads"] in (1,2) && Threads.nthreads()==s["threads"] && s["primary_count"] isa Integer && !(s["primary_count"] isa Bool) && s["seed"] isa Integer && !(s["seed"] isa Bool) && 0<s["seed"]<2147483647,"Wrong ring runtime/count/seed")
    op=d["operating_model"]
    signed=model=="GeRC02" ? 240 : -370;factor=model=="GeRC02" ? 1 : -1
    R.check(op["signed_bias_V"]==signed && op["contact_potentials_V"]==Dict("1"=>0,"2"=>signed) && op["wiring_factor"]==factor && op["readout_contact_id"]==1,"Wrong signed operating bias or fixed wiring")
    R.check(d["numerics"]==Dict("parcels"=>16,"native_seed_family"=>2609261,"drift_dt_ns"=>2,"drift_cap_ns"=>10000,"stored_temperature_K"=>78,"runtime_temperature_K"=>77,"bias_V"=>model=="GeRC02" ? 240 : 370,"native_failure_policy"=>"record","models_serial"=>true,"stages_serial"=>true),"Wrong native ring settings")
    profile=RS.relative_file(d["profile_ref"]);input=RS.relative_file(d["stream_ref"])
    base=".local/runs/"*s["name"]
    R.check(d["profile_ref"]==base*"/electronics/profile.json" && d["stream_ref"]==base*"/transport/stream/manifest.json" && abspath(args[4])==abspath(joinpath(Q.ROOT,base,"response")),"Ring input/output must share the selected new run root")
    R.check(E.hashfile(profile)==d["profile_sha256"] && E.hashfile(input)==d["stream_sha256"],"Ring request/profile/stream binding changed")
    R.check(d["source_sha256"] isa AbstractDict && !isempty(d["source_sha256"]),"Missing ring source authority")
    required=union(Set("simulation/"*n for n in SOURCES),Set(("tools/ring_workflow.py","tools/ring_model_contract.py","tools/scenario_workflow.py","models/"*model*".yaml")))
    R.check(issubset(required,Set(keys(d["source_sha256"]))) && d["configuration_sha256"] isa String && occursin(r"^[0-9a-f]{64}$",d["configuration_sha256"]),"Incomplete fresh ring consumer authority")
    for (ref,h) in d["source_sha256"];RS.pin!(Dict{String,String}(),RS.relative_file(ref),h);end
    R.check(get(d["source_sha256"],"simulation/workflow_ring_response.jl",nothing)==E.hashfile(@__FILE__),"Wrong fresh ring consumer binding")
    o=NR.options(["--input",input,"--output",args[4],"--profile",profile,"--parcels","16","--seed","2609261","--trace-examples","16","--charge-csv","all","--native-failure-policy","record"])
    o["request"]=path
    o,d
end

function prepare(o,request)
    stream=RS.inspect(o["input"]);d=stream.manifest;meta=stream.prepared;c=d["model_contract"]
    selected=request["selection"];op=request["operating_model"]
    R.check(d["model_id"]==selected["detector"] && d["primary_count"]==selected["primary_count"] && meta["seed"]==selected["seed"],"Ring source selection differs from prepared stream")
    R.check(c["source_model_sha256"]==op["source_model_sha256"] && c["effective_model_sha256"]==op["effective_model_sha256"] && c["variant_id"]==op["variant_id"] && c["contact_potentials_V"]==op["contact_potentials_V"],"Ring effective model differs from checked selection")
    expected=selected["detector"]=="GeRC02" ? ".local/runs/"*selected["name"]*"/transport/effective-model/GeRC02.yaml" : "models/KMRC01_candidate.yaml"
    R.check(c["effective_model_ref"]==expected,"Ring model must belong to this new run")
    model=RS.model_contract(c,stream.pins)
    original=Simulation{Float64}(model);stored=original.detector.semiconductor.temperature
    R.check(stored==78,"Stored ring temperature must remain78K")
    config=deepcopy(original.config_dict);sc=config["detectors"][1]["semiconductor"];sc["temperature"]=77.0
    haskey(sc["charge_drift_model"],"temperature") && (sc["charge_drift_model"]["temperature"]=77.0)
    sim=Simulation{Float64}(config);cdm=sim.detector.semiconductor.charge_drift_model
    R.check(sim.detector.semiconductor.temperature==77 && (!hasproperty(cdm,:temperature) || cdm.temperature==77),"Explicit ring runtime temperature failed")
    contacts=Dict(string(x.id)=>x.potential for x in sim.detector.contacts)
    R.check(contacts==c["contact_potentials_V"]==op["contact_potentials_V"],"Loaded signed ring contacts differ")
    profile=P.load(o["profile"])
    R.check(profile.profile["settings"]==selected["electronics"],"Selected electronics differ from consumed profile")
    geom=NR.geometry(meta,sim,true);geom["model_contract"]=c;geom["field_cache_used"]=false
    P.window_config(profile.config,d["grouping_policy"]["horizon_ns"],N.DT)
    S.foreach_decay(e->R.validate_deposits(Dict("events"=>[e]),sim),stream);S.recheck(stream)
    eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation)
    matrix=E.transition(profile.config,N.DT);start=time()
    negative=d["model_id"]=="KMRC01_candidate" ? RP.negative_calibration(profile.config,eion,N.DT,matrix) : nothing
    cal=negative===nothing ? P.calibration(profile.config,eion,N.DT,matrix) : negative.calibration
    seconds=time()-start
    bias=maximum(x.potential for x in sim.detector.contacts)-minimum(x.potential for x in sim.detector.contacts)
    (input=stream.path,inputhash=E.hashfile(stream.path),ion=true,stream=stream,document=d,meta=meta,
        profile=profile,sim=sim,stored=stored,bias=bias,geometry=geom,matrix=matrix,calibration=cal,eion=eion,
        injection=negative===nothing ? nothing : negative.injection,calibration_seconds=seconds)
end

function process_ring(t,q,c,eion,cal,M,model;horizon_ns)
    r=model=="KMRC01_candidate" ? RP.process(t,q,c,eion,cal,M;horizon_ns=horizon_ns) : P.process(t,q,c,eion,cal,M;horizon_ns=horizon_ns)
    if model=="KMRC01_candidate"
        # Display the native signs while retaining the explicitly wired electronics
        # input arrays as separate trace fields. This fixed multiplication is the
        # inverse of the authorized -1 input wiring, never absolute value.
        trace=r["trace"]
        trace["raw_native_induced_charge_fC"]=RP.FACTOR .* trace["induced_charge_fC"]
        trace["raw_native_current_nA"]=RP.FACTOR .* trace["current_nA"]
    end
    r
end

function summary_html(out,report)
    R.check(report["status"] in ("completed_provisional_native_response","completed_with_native_failures"),"Export requires completed ring response")
    for (file,h) in report["artifacts"];R.check(E.hashfile(joinpath(out,file))==h,"Export artifact changed");end
    open(joinpath(out,"summary.html"),"w") do io
        print(io,"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Ring response</title><style>body{font:16px/1.5 system-ui;max-width:1000px;margin:auto;padding:20px;overflow-wrap:anywhere}svg{width:100%}pre{white-space:pre-wrap}summary{cursor:pointer}</style><h1>Ring detector response</h1><p>Synthetic isolated readout; native charge/current retain their original signs. Negative ring analog output uses fixed -1 input wiring. No physical-resolution, measured-waveform or calibrated Li CCE claim.</p>")
        print(io,"<pre>",N.escape(JSON.json(report["counts"],2)),"</pre><p><a href='run.json'>Settings and receipts</a> · <a href='scalars.csv'>All primaries and groups</a> · <a href='endpoints.csv'>Endpoints</a> · <a href='truth.jsonl'>Original truth</a> · <a href='histograms.csv'>Histograms</a></p>")
        open(joinpath(out,"traces.jsonl")) do traces
            for line in eachline(traces)
                r=JSON.parse(line);tr=r["trace"]
                print(io,"<details><summary>Event ",r["event_id"]," / group ",r["group_id"],"</summary>")
                for (k,label) in (("induced_charge_fC","Charge (fC)"),("current_nA","Original-bin current (nA)"),("preamp_V","Analog preamp (V)"),("shaped_V","Analog shaper (V)"))
                    raw=get(tr,"raw_native_"*k,nothing)
                    print(io,N.plot(tr["time_ns"],raw===nothing ? tr[k] : raw,label))
                end
                print(io,"<p>Bounded display samples; raw current belongs to original intervals in traces.jsonl. KM charge/current keep native signs; preamp/shaper follow fixed -1 wiring. Digital output is one peak ADC code.</p></details>")
            end
        end
    end
end
function progress(out,started,stage,status,counts,total)
    value=Dict("kind"=>"workflow_ring_progress_v1","stage"=>stage,"status"=>status,
        "completed_primary_count"=>counts["initial_primaries"],"expected_primary_count"=>total,
        "elapsed_seconds"=>time()-started)
    pending=joinpath(out,"progress.json.pending-"*string(getpid()))
    write(pending,JSON.json(value));mv(pending,joinpath(out,"progress.json");force=true)
end
function run(o,a,request; process_response=process_ring, source_names=SOURCES)
    env=Q.environment("cpu"); readout_env=E.environment()
    R.check(Threads.nthreads() in (1,2),"Use one or two Julia threads")
    d=a.document; sim=a.sim; c=P.for_census(a.profile.profile,d["primary_count"])
    cfg=Q.parse_args(["--model",d["model_id"],"--position-mm","3,0,5","--precision","64",
        "--dt-ns","2","--min-grid-mm","0.05","--max-iterations","50000","--output",o["output"]])
    sources=Dict(n=>E.hashfile(joinpath(@__DIR__,n)) for n in source_names)
    out=Q.reserve_output(cfg.output); started=time(); hist=Dict{String,Dict{Int,Int}}()
    counts=Dict{String,Any}("initial_primaries"=>0,"initial_decays"=>a.ion ? 0 : nothing,"zero_deposit_primaries"=>0,"groups"=>0,"accepted"=>0,
        "rejected"=>0,"readout_rejected"=>0,"native_failed_groups"=>0,"saturated"=>0,"native_charge_samples"=>0,"analog_samples"=>0,
        "line_photons"=>a.ion ? 0 : nothing,"decay_photons"=>a.ion ? 0 : nothing)
    report=Dict{String,Any}("kind"=>"workflow_ring_native_response_v1","status"=>"running","environment"=>env,
        "readout_environment"=>readout_env,"input_kind"=>a.ion ? S.KIND : "mono_gamma_json_v1",
        "input_sha256"=>a.inputhash,"source_lh5_sha256"=>d["source_lh5_sha256"],
        "model_id"=>d["model_id"],"model_sha256"=>d["model_sha256"],"temperature_K"=>77,
        "stored_temperature_K"=>a.stored,"bias_V"=>a.bias,"geometry_checks"=>a.geometry,
        "profile"=>a.profile.profile,"profile_sha256"=>a.profile.sha256,"source_sha256"=>sources,
        "parcels"=>o["parcels"],"seed_family"=>o["seed"],"seed_rule"=>"SHA256(seed/global_event_id/raw_row_index/parcel_index), first8 bytes big-endian UInt64; no chunk/group index",
        "diffusion"=>true,"end_drift_when_no_field"=>false,"self_repulsion"=>false,
        "drift_dt_ns"=>N.DT,"nominal_drift_cap_ns"=>N.HORIZON_NS,"counts"=>counts,
        "native_failure_policy"=>get(o,"native-failure-policy","abort"),
        "native_failure_allowlist"=>collect(NATIVE_FAILURE_MESSAGES),
        "rejection_accounting"=>"rejected = readout_rejected + native_failed_groups; all groups and initial primaries remain in the census",
        "field_settings"=>Dict("precision_bits"=>64,"min_spacing_mm"=>0.05,"max_spacing_mm"=>2,"sor"=>1,"potential_rechecks"=>4),
        "units"=>Dict("charge"=>"fC","current"=>"nA","voltage"=>"V","energy"=>"keV","time"=>"ns"),
        "limitations"=>["Synthetic electronics, no noise/Fano smearing, physical resolution or experimental fit.",
            "Native endpoints and signed charge retained; no Edep forcing or per-event calibration.",
            "Field iteration gates are not grid/PDE/CCE convergence; Li calibration remains unresolved.",
            "Cs137 uses finite nominal isolated windows with reset, possible tail loss and unestablished recovery; no activity/live-time/pileup claim.",
            "Material ledger is recorded-only; escape/neutrino/full energy closure is null."],
        "ledger"=>get(d,"ledger",Dict("kind"=>"recorded-only","full_energy_closure"=>nothing)))
    handles=IO[]; stage="field_solve"
    try
        report["configuration_sha256"]=request["configuration_sha256"]
        report["request_sha256"]=E.hashfile(o["request"])
        report["model_contract"]=a.document["model_contract"]
        report["signed_operating_bias_V"]=request["operating_model"]["signed_bias_V"]
        report["contact_potentials_V"]=a.document["model_contract"]["contact_potentials_V"]
        report["wiring_factor"]=request["operating_model"]["wiring_factor"]
        report["new_field_solution"]=true
        report["independent_calibration_calls"]=1
        report["calibration_seconds"]=a.calibration_seconds
        report["trace_signal_convention"]="Charge/current are raw signed native signals; Negative ring preamp/shaper follow fixed -1 wiring."
        cp(o["request"],joinpath(out,"request-input.json"))
        a.injection!==nothing && E.save(joinpath(out,"negative-injection.json"),a.injection)
        E.save(joinpath(out,"profile.json"),a.profile.profile)
        # Exact supplied bytes and resolved config are independently bound.
        cp(o["profile"],joinpath(out,"profile-input.json"))
        R.check(E.hashfile(joinpath(out,"profile-input.json"))==a.profile.sha256,"Copied profile bytes changed")
        E.save(joinpath(out,"readout-config.json"),c)
        E.save(joinpath(out,"input-contract.json"),Dict(k=>v for (k,v) in d if k!="events"))
        E.save(joinpath(out,"input-prepared.json"),a.meta)
        P.validate_resolved(JSON.parsefile(joinpath(out,"readout-config.json")),a.profile.profile,d["primary_count"])
        report["config_sha256"]=E.hashfile(joinpath(out,"readout-config.json"))
        report["grouping_policy"]=a.ion ? d["grouping_policy"] : Dict("name"=>"one_primary_one_response","state_at_group_start"=>"reset","time_origin"=>"original primary_time_ns")
        E.save(joinpath(out,"run.json"),report)
        progress(out,started,stage,"running",counts,d["primary_count"])
        solver,timing=Base.invokelatest(Q.solve_fields!,sim,cfg,Q.prepare_backend("cpu");sor_consts=1.0,potential_rechecks=4)
        report["solver"]=solver; report["field_timings"]=timing; report["field_fingerprint"]=N.field_fingerprint(sim)
        stage="native_and_readout"; replay_start=time(); native_s=0.; electronics_s=0.
        progress(out,started,stage,"running",counts,d["primary_count"])
        eion=a.eion; M=a.matrix; cal=a.calibration
        report["calibration"]=cal; report["ionisation_energy_eV"]=eion
        report["readout_contact_id"]=cfg.contact
        policy=o["charge-csv"]=="auto" ? (!a.ion && d["primary_count"]<=100 ? "all" : "examples") : o["charge-csv"]
        report["charge_csv_policy"]=policy; report["trace_selection"]="first $(o["trace-examples"]) pulse groups in original census order"
        files=("scalars.jsonl","scalars.csv","endpoints.jsonl","endpoints.csv","truth.jsonl","truth.csv","traces.jsonl","signals.csv")
        for name in files; push!(handles,open(joinpath(out,name),"w")); end
        sj,sc,ej,ec,tj,tc,traces,signals=handles
        failures=Ref{Union{Nothing,IO}}(nothing) # No extra artifact for a clean run.
        println(sc,join(SCALAR_COLUMNS,',')); println(ec,"event_id,global_decay_id,group_id,raw_row_index,parcel_index,seed_uint64,record_json")
        println(tc,"event_id,global_decay_id,record_json"); println(signals,"event_id,global_decay_id,group_id,time_since_origin_ns,induced_equivalent_energy_keV")
        function consume(e)
            id=e["event_id"]; globalid=a.ion ? e["global_decay_id"] : nothing
            println(tj,JSON.json(e)); println(tc,join(E.csvcell.((id,globalid,e)),','))
            energy=sum((s["energy_keV"] for s in e["steps"]);init=0.)
            gs=event_groups(e,a.ion)
            counts["initial_primaries"]+=1; counts["zero_deposit_primaries"]+=energy==0
            if a.ion; counts["initial_decays"]+=1; counts["line_photons"]+=e["line_photon_count"]; counts["decay_photons"]+=e["decay_photon_count"]; end
            scalar!(sj,sc,Dict("record_kind"=>a.ion ? "decay" : "primary","event_id"=>id,"global_decay_id"=>globalid,"group_id"=>nothing,
                "deposited_energy_keV"=>energy,"pulse_count"=>length(gs),"zero_deposit"=>energy==0,
                "raw_row_indices"=>[s["raw_row_index"] for s in e["steps"]],
                "line_photon_count"=>get(e,"line_photon_count",nothing),"decay_photon_count"=>get(e,"decay_photon_count",nothing),
                "material_energy_keV"=>get(e,"material_energy_keV",nothing),"full_energy_closure"=>nothing))
            addhist!(hist,a.ion ? "deposited_per_decay" : "deposited_per_primary",energy)
            if !a.ion && energy==0 && policy=="all"
                # Zero-charge primary trace, explicitly no pulse/group identity.
                for t in (0.,N.DT); println(signals,join(E.csvcell.((id,globalid,nothing,t,0.)),',')); end
            end
            byrow=Dict(s["raw_row_index"]=>s for s in e["steps"])
            for g in gs
                gid=g["group_id"]; origin=g["origin_time_ns"]; steps=[byrow[i] for i in g["row_indices"]]
                event=Dict("event_id"=>id,"primary_time_ns"=>origin,"steps"=>steps)
                t0=time()
                attempt=native_attempt(()->N.native_event(event,sim,cfg,o["parcels"],o["seed"]),report["native_failure_policy"])
                native_s+=time()-t0
                if attempt.error!==nothing
                    rec=failed_pulse(e,g,steps,o,attempt.error,d["source_lh5_sha256"])
                    if failures[]===nothing
                        failures[]=open(joinpath(out,"native-failures.jsonl"),"w"); push!(handles,failures[])
                    end
                    settings=Dict(k=>report[k] for k in ("model_id","model_sha256","input_sha256","source_sha256",
                        "temperature_K","bias_V","parcels","seed_family","seed_rule","diffusion","end_drift_when_no_field",
                        "self_repulsion","drift_dt_ns","nominal_drift_cap_ns","readout_contact_id","field_settings",
                        "field_fingerprint","profile_sha256","config_sha256","calibration","native_failure_policy"))
                    println(failures[],JSON.json(Dict("record_kind"=>"native_failure_diagnostic","pulse"=>rec,
                        "original_event"=>e,"original_group"=>g,"original_steps"=>steps,"settings"=>settings)))
                    scalar!(sj,sc,rec)
                    counts["groups"]+=1; counts["native_failed_groups"]+=1; counts["rejected"]+=1
                    group_hist!(hist,rec["deposited_energy_keV"],nothing,nothing,eion)
                    continue
                end
                result=attempt.result
                t,q=result.times,result.signal
                R.check(all(isfinite,q) && first(q)==0,"Invalid native cumulative charge")
                t0=time(); r=process_response(t,q,c,eion,cal,M,a.document["model_id"];horizon_ns=g["horizon_ns"]); electronics_s+=time()-t0
                R.check(r["current_balance"]["passed"],"Current/charge balance failed")
                counts["groups"]+=1; counts[r["accepted"] ? "accepted" : "rejected"]+=1; counts["saturated"]+=r["saturated"]
                counts["readout_rejected"]+= !r["accepted"]
                counts["native_charge_samples"]+=length(t); counts["analog_samples"]+=r["original_sample_count"]
                selected=counts["groups"]<=o["trace-examples"]
                if selected
                    println(traces,JSON.json(Dict("event_id"=>id,"global_decay_id"=>globalid,"group_id"=>gid,
                        "origin_time_ns"=>origin,"trace"=>r["trace"])))
                end
                if policy=="all" || (policy=="examples" && selected)
                    for (time,value) in zip(t,q); println(signals,join(E.csvcell.((id,globalid,gid,time,value)),',')); end
                end
                for step in result.steps
                    row=step["raw_row_index"]
                    for endpoint in step["endpoints"]
                        rec=Dict("event_id"=>id,"global_decay_id"=>globalid,"group_id"=>gid,"raw_row_index"=>row,
                            "source_lh5_sha256"=>d["source_lh5_sha256"],"raw_table"=>"stp/germanium",
                            "original_time_ns"=>byrow[row]["time_ns"],"origin_time_ns"=>origin,
                            "deposition_delay_ns"=>step["deposition_delay_ns"],"deposited_energy_keV"=>step["deposited_energy_keV"],
                            "parcel_weight_keV"=>step["parcel_weight_keV"],"step_final_induced_keV"=>step["final_induced_keV"],
                            "parcel_index"=>endpoint["parcel_index"],"seed_uint64"=>string(N.parcel_seed(o["seed"],id,row,endpoint["parcel_index"])),"endpoint"=>endpoint)
                        endpoint!(ej,ec,rec)
                    end
                end
                pop!(r,"trace") # every other readout diagnostic stays in BOTH scalar formats
                edep=sum(s["energy_keV"] for s in steps)
                rec=Dict("record_kind"=>"pulse","event_id"=>id,"global_decay_id"=>globalid,"group_id"=>gid,
                    "origin_time_ns"=>origin,"group"=>g,"deposited_energy_keV"=>edep,"final_induced_keV"=>last(q),
                    "raw_row_indices"=>g["row_indices"],"transport_flags"=>N.flags(result.steps),"readout"=>r,
                    "accepted"=>r["accepted"],"rejection_reason"=>r["rejection_reason"],"trace_saved"=>selected,
                    "charge_end_ns"=>last(t),"native_any_negative_charge"=>any(x->x<0,q),
                    "native_min_charge_keV"=>minimum(q),"native_max_charge_keV"=>maximum(q),
                    "parcels"=>o["parcels"],"seed_family"=>o["seed"])
                scalar!(sj,sc,rec)
                group_hist!(hist,edep,q,r,eion)
            end
            progress(out,started,stage,"running",counts,d["primary_count"])
        end
        if a.ion; S.foreach_decay(consume,a.stream)
        else; for e in d["events"]; consume(e); end
        end
        for io in handles; close(io); end; empty!(handles)
        report["native_drift_and_charge_seconds"]=native_s; report["electronics_seconds"]=electronics_s
        report["replay_readout_export_seconds"]=time()-replay_start
        stage="final_integrity"
        R.check(counts["initial_primaries"]==d["primary_count"] && counts["accepted"]+counts["rejected"]==counts["groups"],"Output census mismatch")
        R.check(counts["rejected"]==counts["native_failed_groups"]+counts["readout_rejected"],"Rejection census mismatch")
        R.check(N.field_fingerprint(sim)==report["field_fingerprint"],"Response changed shared fields")
        R.check(E.hashfile(a.input)==a.inputhash && E.hashfile(o["profile"])==a.profile.sha256,"Input/profile changed")
        P.validate_resolved(JSON.parsefile(joinpath(out,"readout-config.json")),a.profile.profile,d["primary_count"])
        R.check(E.hashfile(joinpath(out,"readout-config.json"))==report["config_sha256"],"Configuration bytes changed")
        a.ion ? S.recheck(a.stream) : R.load_input(a.input)
        R.check(all(E.hashfile(joinpath(@__DIR__,n))==h for (n,h) in sources),"Consumer source changed")
        Q.verify_model_files()
        export_hist(out,hist,counts,cal)
        report["status"]=counts["native_failed_groups"]>0 ? "completed_with_native_failures" : "completed_provisional_native_response"
        progress(out,started,"completed",report["status"],counts,d["primary_count"])
        names=vcat(collect(files),["request-input.json","profile.json","profile-input.json","readout-config.json","input-contract.json","input-prepared.json","histograms.json","histograms.csv"])
        a.injection!==nothing && push!(names,"negative-injection.json")
        failures[]!==nothing && push!(names,"native-failures.jsonl")
        report["artifacts"]=Dict(n=>E.hashfile(joinpath(out,n)) for n in names)
        summary_html(out,report); report["artifacts"]["summary.html"]=E.hashfile(joinpath(out,"summary.html"))
        report["artifact_bytes"]=Dict(n=>filesize(joinpath(out,n)) for n in keys(report["artifacts"]))
    catch err
        report["status"]="failed"; report["failure_stage"]=stage; report["error_type"]=string(typeof(err))
        progress(out,started,stage,"failed",counts,d["primary_count"]);rethrow()
    finally
        for io in handles; isopen(io) && close(io); end
        report["solve_replay_readout_export_wall_seconds"]=time()-started
        report["timing_scope"]="Measured in this process, excludes module startup/preflight; no warm-up subtraction or capacity extrapolation"
        rss=try Sys.maxrss() catch; nothing end
        report["process_peak_rss_bytes"]=rss===nothing || rss<=0 ? nothing : rss
        report["rss_scope"]="Process high-water mark including startup/preflight, platform-reported by Sys.maxrss"
        E.save(joinpath(out,"run.json"),report)
    end
    println(JSON.json(Dict("status"=>report["status"],"counts"=>counts,"seconds"=>report["solve_replay_readout_export_wall_seconds"])))
    report
end
function main(args=ARGS)
    o,request=request_options(args);Q.environment("cpu");E.environment()
    start=time();a=prepare(o,request);preflight=time()-start
    report=run(o,a,request)
    S.recheck(a.stream)
    for (ref,h) in request["source_sha256"];RS.pin!(Dict{String,String}(),RS.relative_file(ref),h);end
    R.check(E.hashfile(o["request"])==report["request_sha256"],"Ring request changed during execution")
    envelope=Dict("kind"=>"workflow_ring_response_v1","status"=>report["status"],"configuration_sha256"=>request["configuration_sha256"],
        "request_sha256"=>report["request_sha256"],"native_report_sha256"=>E.hashfile(joinpath(o["output"],"run.json")),
        "source_sha256"=>request["source_sha256"],"model_contract"=>a.document["model_contract"],
        "signed_operating_bias_V"=>report["signed_operating_bias_V"],"bias_magnitude_V"=>a.bias,
        "wiring_factor"=>report["wiring_factor"],"calibration"=>report["calibration"],"independent_calibration_calls"=>1,
        "new_field_solution"=>true,"preflight_seconds"=>preflight,"calibration_seconds"=>a.calibration_seconds,
        "counts"=>report["counts"],"processing_completion_is_not_validation"=>true)
    E.save(joinpath(o["output"],"workflow-ring-response.json"),envelope)
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__;WorkflowRingResponse.main();end
