# Reusable engineering response. Reuses the reviewed SSD helper and solver.
include("native_li_example.jl")
include("readout_profiles.jl")
include("native_stream.jl")
module NativeResponse
using ..NativeLiExample, ..ReadoutProfiles, ..NativeStream, JSON, SHA, Unitful
const N=NativeLiExample; const R=N.R; const Q=N.Q; const E=N.E
const P=ReadoutProfiles; const S=NativeStream
const SOURCES=("native_response.jl","native_stream.jl","readout_profiles.jl",
    "native_li_example.jl","readout.jl","replay.jl","run.jl","readout_demo.json",
    "Project.toml","Manifest.toml","test_readout_profiles.jl","test_native_stream.jl","test_native_response.jl")
const HELP="""
NativeResponse: provisional native SSD -> synthetic CSA -> analog shaper -> peak ADC.
  --input FILE       checked JSONv1 mono-gamma events OR completed Cs137 manifest
  --inspect          validate all input records/geometry/profile without field solve
  --output DIR       new .local directory (run only)
  --profile FILE     schema-2 profile (default simulation/native_readout_profile.json)
  --parcels 16|32    independent equal-energy parcels (default16)
  --seed 2609261|2609262  native helper seed family (default2609261)
  --trace-examples N  first N pulse groups, 0..16 (default4; stable across chunks)
  --charge-csv auto|all|examples|none (auto: all for <=100 mono primaries, examples otherwise)
  --native-failure-policy abort|record (default abort; exact native-domain allowlist only)
Use --startup-file=no --threads=1 or2 --project=simulation. No transport launch.
"""
function options(args)
    o=Dict{String,Any}("profile"=>joinpath(@__DIR__,"native_readout_profile.json"),
        "parcels"=>16,"seed"=>first(N.SEEDS),"trace-examples"=>4,"charge-csv"=>"auto","inspect"=>false,
        "native-failure-policy"=>"abort")
    seen=Set{String}(); i=1
    while i<=length(args)
        k=args[i]; R.check(startswith(k,"--"),"Expected option"); k=k[3:end]
        R.check(!(k in seen),"Duplicate option"); push!(seen,k)
        if k=="inspect"; o[k]=true; i+=1; continue; end
        R.check(k in ("input","output","profile","parcels","seed","trace-examples","charge-csv","native-failure-policy") && i<length(args),"Unknown/incomplete option")
        o[k]=k in ("parcels","seed","trace-examples") ? parse(Int,args[i+1]) : args[i+1]; i+=2
    end
    R.check(haskey(o,"input") && (o["inspect"] || haskey(o,"output")),"Required --input and --output (or --inspect)")
    R.check(!(o["inspect"] && haskey(o,"output")),"Inspect writes no run output")
    R.check(o["parcels"] in (16,32) && o["seed"] in N.SEEDS && 0<=o["trace-examples"]<=16,"Invalid parcel/seed/trace bound")
    R.check(o["charge-csv"] in ("auto","all","examples","none"),"Invalid charge CSV policy")
    R.check(o["native-failure-policy"] in ("abort","record"),"Invalid native failure policy")
    o
end
const NATIVE_FAILURE_MESSAGES=("Noncontact endpoint outside crystal","Invalid waveform support")
const ENDPOINT_UNAVAILABLE="Strict NativeLiExample.native_event does not expose rejected endpoint details; private supervisor diagnostics are separate."
function native_attempt(f,policy)
    R.check(policy in ("abort","record"),"Invalid native failure policy")
    try
        return (result=f(),error=nothing)
    catch err
        # Only the strict native helper call belongs inside this boundary.
        if policy=="record" && err isa ArgumentError && err.msg in NATIVE_FAILURE_MESSAGES
            return (result=nothing,error=Dict("type"=>string(typeof(err)),"message"=>err.msg,
                "exact_error"=>sprint(showerror,err),"stage"=>"NativeLiExample.native_event"))
        end
        rethrow()
    end
end
function failed_pulse(e,g,steps,o,error,source_hash)
    Dict{String,Any}("record_kind"=>"pulse","status"=>"native_transport_failed",
        "event_id"=>e["event_id"],"global_decay_id"=>get(e,"global_decay_id",nothing),"group_id"=>g["group_id"],
        "origin_time_ns"=>g["origin_time_ns"],"group"=>g,"raw_row_indices"=>g["row_indices"],
        "deposition_delays_ns"=>[s["time_ns"]-g["origin_time_ns"] for s in steps],
        "deposited_energy_keV"=>sum(s["energy_keV"] for s in steps),"source_lh5_sha256"=>source_hash,
        "raw_table"=>"stp/germanium","parcels"=>o["parcels"],"seed_family"=>o["seed"],
        "native_error"=>error,"endpoint_details_note"=>ENDPOINT_UNAVAILABLE,
        "accepted"=>false,"rejection_reason"=>"native_transport_failed","trace_saved"=>false,
        "final_induced_keV"=>nothing,"charge_end_ns"=>nothing,"native_any_negative_charge"=>nothing,
        "native_min_charge_keV"=>nothing,"native_max_charge_keV"=>nothing,
        "transport_flags"=>nothing,"endpoints"=>nothing,"readout"=>nothing,
        "current_nA"=>nothing,"induced_charge_fC"=>nothing)
end
function geometry(meta,sim,ion)
    !ion && return R.geometry_check(meta,sim)
    actual=sort(collect(zip(1000 .* sim.detector.semiconductor.geometry.r,1000 .* sim.detector.semiconductor.geometry.z)))
    expected=sort([Tuple(Float64.(v)) for v in meta["contour_rz_mm"]])
    R.check(length(actual)==length(expected) && all(isapprox.(first.(actual),first.(expected);rtol=0,atol=1e-10)) && all(isapprox.(last.(actual),last.(expected);rtol=0,atol=1e-10)),"SSD/prepared contour mismatch")
    S.transform(meta["coordinate_transform"])
    Dict("ssd_contour_matches"=>true,"proper_coordinate_transform"=>true,
        "scope"=>"Local SSD membership/contour; nominal Geant4 assembly checks are producer evidence")
end
function prepare(o)
    input=S.localfile(o["input"]); header=E.readjson(input)
    ion=get(header,"kind",nothing)==S.KIND
    if ion
        stream=S.inspect(input); d=stream.manifest; meta=stream.prepared
    else
        d,meta=R.load_input(input); stream=nothing
        R.check(d["primary_count"]<=100,"JSONv1 is the bounded <=100-primary comparison; use the decay stream for larger campaigns")
    end
    R.check(isfile(o["profile"]) && Q.childof(realpath(o["profile"]),realpath(Q.ROOT)),"Profile must be in this project")
    profile=P.load(o["profile"]); sim,stored=R.setup_simulation(d["model_id"];temperature=77.0)
    bias=maximum(c.potential for c in sim.detector.contacts)-minimum(c.potential for c in sim.detector.contacts)
    R.check(bias==(d["model_id"]=="AK02" ? 500 : 700),"Unexpected canonical bias")
    geom=geometry(meta,sim,ion)
    ion && P.window_config(profile.config,d["grouping_policy"]["horizon_ns"],N.DT)
    # Preflight every record before the expensive shared field solution.
    inspect_event(e)=R.validate_deposits(Dict("events"=>[e]),sim)
    if ion; S.foreach_decay(inspect_event,stream); S.recheck(stream)
    else; R.validate_deposits(d,sim)
    end
    eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation)
    matrix=E.transition(profile.config,N.DT); cal=P.calibration(profile.config,eion,N.DT,matrix)
    (input=input,inputhash=E.hashfile(input),ion=ion,stream=stream,document=d,meta=meta,
        profile=profile,sim=sim,stored=stored,bias=bias,geometry=geom,matrix=matrix,calibration=cal,eion=eion)
end
function event_groups(e,ion)
    ion && return e["pulse_groups"]
    rows=[s["raw_row_index"] for s in e["steps"] if s["energy_keV"]>0]
    isempty(rows) ? Any[] : [Dict("group_id"=>0,"origin_time_ns"=>e["primary_time_ns"],"row_indices"=>rows)]
end
const SCALAR_COLUMNS=("record_kind","event_id","global_decay_id","group_id","origin_time_ns",
    "deposited_energy_keV","final_induced_keV","accepted","rejection_reason","record_json")
function scalar!(jsonl,csv,record)
    println(jsonl,JSON.json(record))
    println(csv,join([E.csvcell(k=="record_json" ? record : get(record,k,nothing)) for k in SCALAR_COLUMNS],','))
end
function endpoint!(jsonl,csv,record)
    println(jsonl,JSON.json(record))
    keys=("event_id","global_decay_id","group_id","raw_row_index","parcel_index","seed_uint64","record_json")
    println(csv,join([E.csvcell(k=="record_json" ? record : get(record,k,nothing)) for k in keys],','))
end
function addhist!(hist,stage,x)
    x===nothing && return
    R.check(E.finite(x),"Nonfinite histogram value")
    # Fixed width, bounded memory; under/overflow remain explicit and counted.
    k=x< -1000 ? -1 : x>=4000 ? 1000 : floor(Int,(x+1000)/5)
    counts=get!(hist,stage,Dict{Int,Int}()); counts[k]=get(counts,k,0)+1
end
function group_hist!(hist,edep,q,r,eion)
    addhist!(hist,"deposited_per_group",edep)
    r===nothing && return # Failed native transport has no charge/readout histogram entry.
    for (label,value) in (("native_terminal_charge",last(q)),
        ("window_charge",r["final_charge_C"]/E.charge_C(1.,eion)),
        ("preamp_charge_equivalent",r["preamp_peak_charge_equivalent_keV"]),
        ("analog_shaped_equivalent",r["analog_energy_keV"]),("accepted_peak_ADC",r["reconstructed_energy_keV"]))
        addhist!(hist,label,value)
    end
end
function export_hist(out,hist,counts,cal)
    rows=Any[]
    for stage in sort!(collect(keys(hist))), bin in sort!(collect(keys(hist[stage])))
        n=hist[stage][bin]
        push!(rows,Dict("stage"=>stage,"bin"=>bin,"lower_keV"=>bin==-1 ? nothing : -1000+5bin,
            "upper_keV"=>bin==1000 ? nothing : -1000+5(bin+1),"count"=>n,
            "per_initial_primary"=>n/counts["initial_primaries"],
            "per_initial_decay"=>counts["initial_decays"]===nothing ? nothing : n/counts["initial_decays"],
            "per_emitted_660_663_keV_photon"=>counts["line_photons"]===nothing || counts["line_photons"]==0 ? nothing : n/counts["line_photons"],
            "per_accepted_pulse"=>counts["accepted"]==0 ? nothing : n/counts["accepted"]))
    end
    E.save(joinpath(out,"histograms.json"),Dict("bins"=>rows,"width_keV"=>5,"normalization_denominators"=>counts,
        "note"=>"Raw stage counts with distinct denominators, not efficiencies or physical resolution; Erec contains accepted pulses only."))
    open(joinpath(out,"histograms.csv"),"w") do io
        keys=("stage","bin","lower_keV","upper_keV","count","per_initial_primary","per_initial_decay","per_emitted_660_663_keV_photon","per_accepted_pulse")
        println(io,join(keys,',')); for r in rows; println(io,join([E.csvcell(r[k]) for k in keys],',')); end
    end
end
function summary_html(out,report)
    # Export from completed, hash-checked files only; no simulation from a browser.
    R.check(report["status"] in ("completed_provisional_native_response","completed_with_native_failures"),"Export requires a completed response")
    for (file,h) in report["artifacts"]; R.check(E.hashfile(joinpath(out,file))==h,"Export artifact changed"); end
    open(joinpath(out,"summary.html"),"w") do io
        print(io,"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Native response</title><style>body{font:16px/1.5 system-ui;max-width:1000px;margin:auto;padding:20px;overflow-wrap:anywhere}svg{width:100%}pre{white-space:pre-wrap}summary{cursor:pointer}</style><h1>Native SSD response engineering example</h1><p>Synthetic isolated electronics; no measured hardware, calibrated Li CCE, physical FWHM, pileup or activity claim. Numerical parcel variation is not physical resolution. Analog time samples are not waveform ADC samples.</p>")
        print(io,"<pre>",N.escape(JSON.json(report["counts"],2)),"</pre><p><a href='run.json'>Settings, hashes and gates</a> · <a href='scalars.csv'>All decays and pulses</a> · <a href='endpoints.csv'>All endpoints</a> · <a href='truth.jsonl'>Original truth</a> · <a href='histograms.csv'>Stage histograms</a></p>")
        if report["counts"]["native_failed_groups"]>0
            print(io,"<p><strong>completed_with_native_failures: native transport is unavailable for ",report["counts"]["native_failed_groups"]," groups.</strong> Truth energy remains; no charge or electronics result is substituted. <a href='native-failures.jsonl'>Failure diagnostics</a>. ",N.escape(ENDPOINT_UNAVAILABLE),"</p>")
        end
        open(joinpath(out,"traces.jsonl")) do traces
            for line in eachline(traces)
                r=JSON.parse(line); tr=r["trace"]
                print(io,"<details><summary>Event ",r["event_id"]," / group ",r["group_id"],"</summary>")
                for (k,label) in (("induced_charge_fC","Charge (fC)"),("current_nA","Original-bin current (nA)"),("preamp_V","Analog preamp (V)"),("shaped_V","Analog shaper (V)"))
                    print(io,N.plot(tr["time_ns"],tr[k],label))
                end
                print(io,"<p>Bounded display samples; current belongs to the original intervals in traces.jsonl. Digital output is a single peak ADC code, not a waveform digitizer.</p></details>")
            end
        end
    end
end
function run(o,a)
    env=Q.environment("cpu"); readout_env=E.environment()
    R.check(Threads.nthreads() in (1,2),"Use one or two Julia threads")
    d=a.document; sim=a.sim; c=P.for_census(a.profile.profile,d["primary_count"])
    cfg=Q.parse_args(["--model",d["model_id"],"--position-mm","3,0,5","--precision","64",
        "--dt-ns","2","--min-grid-mm","0.05","--max-iterations","50000","--output",o["output"]])
    sources=Dict(n=>E.hashfile(joinpath(@__DIR__,n)) for n in SOURCES)
    out=Q.reserve_output(cfg.output); started=time(); hist=Dict{String,Dict{Int,Int}}()
    counts=Dict{String,Any}("initial_primaries"=>0,"initial_decays"=>a.ion ? 0 : nothing,"zero_deposit_primaries"=>0,"groups"=>0,"accepted"=>0,
        "rejected"=>0,"readout_rejected"=>0,"native_failed_groups"=>0,"saturated"=>0,"native_charge_samples"=>0,"analog_samples"=>0,
        "line_photons"=>a.ion ? 0 : nothing,"decay_photons"=>a.ion ? 0 : nothing)
    report=Dict{String,Any}("kind"=>"native_response_v1","status"=>"running","environment"=>env,
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
        solver,timing=Base.invokelatest(Q.solve_fields!,sim,cfg,Q.prepare_backend("cpu");sor_consts=1.0,potential_rechecks=4)
        report["solver"]=solver; report["field_timings"]=timing; report["field_fingerprint"]=N.field_fingerprint(sim)
        stage="native_and_readout"; replay_start=time(); native_s=0.; electronics_s=0.
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
                t0=time(); r=P.process(t,q,c,eion,cal,M;horizon_ns=a.ion ? g["horizon_ns"] : nothing); electronics_s+=time()-t0
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
        names=vcat(collect(files),["profile.json","profile-input.json","readout-config.json","input-contract.json","input-prepared.json","histograms.json","histograms.csv"])
        failures[]!==nothing && push!(names,"native-failures.jsonl")
        report["artifacts"]=Dict(n=>E.hashfile(joinpath(out,n)) for n in names)
        summary_html(out,report); report["artifacts"]["summary.html"]=E.hashfile(joinpath(out,"summary.html"))
        report["artifact_bytes"]=Dict(n=>filesize(joinpath(out,n)) for n in keys(report["artifacts"]))
    catch err
        report["status"]="failed"; report["failure_stage"]=stage; report["error_type"]=string(typeof(err)); rethrow()
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
    args==["--help"] && return println(HELP)
    o=options(args); Q.environment("cpu"); E.environment()
    R.check(Threads.nthreads() in (1,2),"Use one or two Julia threads")
    a=prepare(o)
    if o["inspect"]
        return println(JSON.json(Dict("status"=>"inspected_no_field_solve","model_id"=>a.document["model_id"],
            "primary_count"=>a.document["primary_count"],"input_sha256"=>a.inputhash,"profile_sha256"=>a.profile.sha256,"geometry"=>a.geometry)))
    end
    run(o,a)
end
end
if abspath(PROGRAM_FILE)==@__FILE__; NativeResponse.main(); end
