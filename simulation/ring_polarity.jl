# Additive, fixed KM electronics wiring. No radiation, field or native module is loaded.
isdefined(@__MODULE__, :ReadoutProfiles) || include("readout_profiles.jl")
module RingPolarity
using ..Readout, ..ReadoutProfiles, JSON, SHA
const E=Readout; const P=ReadoutProfiles
const ROOT=dirname(@__DIR__)
const MODEL="KMRC01_candidate"
const MODEL_SHA="d4258a3b9f9c041b4da1998ded6b373833169ddcc76079f0a588785efe68b6b6"
const PROFILE_SHA="7556e6e77d6c21e76e1a4eabb69b2b26875517252c083c88b6eb6a80502ef6e6"
const FACTOR=-1.0
const SOURCE_PINS=Dict("readout.jl"=>"dfc0bfcdafd2b26bf5b73135d372dde15d2509bd8d3c4b83fefdc2bf9a1ab3c0",
    "readout_profiles.jl"=>"3f4475fffb6a13fa54235191cba6f03a7cfcd8f759da7e08ecbc05c4fe7b0130",
    "readout_demo.json"=>"33eb64724736c78852795ea001889759152ffefc22de9c4db6815fd1aaf8ee9e",
    "Project.toml"=>"11d7d3241bf3e11d2b01172523fbc3637a5748c2026893e596cc830c324f367e",
    "Manifest.toml"=>"14b1dc8cd127ffa0ec417939ba4abdf6b31fb2258290b6f5d922f4def8ade051")
const SIGNAL_HEADER="event_id,global_decay_id,group_id,time_since_origin_ns,induced_equivalent_energy_keV"
const ARTIFACTS=Set(("endpoints.csv","endpoints.jsonl","histograms.csv","histograms.json",
    "input-contract.json","input-prepared.json","profile-input.json","profile.json","readout-config.json",
    "scalars.csv","scalars.jsonl","signals.csv","summary.html","traces.jsonl","truth.csv","truth.jsonl"))
const HASH=r"^[0-9a-f]{64}$"
sha(bytes)=bytes2hex(sha256(bytes))
pulse_key(r)=(Int(r["event_id"]),Int(r["global_decay_id"]),Int(r["group_id"]))
function wiring(model=MODEL)
    E.check(model==MODEL,"Fixed inversion is authorized only for KMRC01_candidate")
    Dict("kind"=>"fixed_km_readout_wiring_v1","model_id"=>MODEL,"factor"=>FACTOR,
        "stage"=>"native signed induced charge -> electronics input",
        "input_unit"=>"signed induced-equivalent keV","output_unit"=>"electronics-input equivalent keV",
        "raw_signal_policy"=>"Original signed native charge/current, endpoints and truth are unchanged; no abs or event-dependent sign/gain")
end
function wired_charge(q,model=MODEL)
    wiring(model); E.check(all(E.finite,q),"Nonfinite signed charge")
    FACTOR .* q
end
function negative_calibration(c,eion,dt,M=E.transition(c,dt))
    E.check(c["calibration_energy_keV"]==500.0,"Use the independent fixed 500-keV injection")
    E.check(E.finite(eion) && eion>0 && E.finite(dt) && dt>0,"Invalid injection units/grid")
    n=ceil(Int,20_000*c["shaping_tau_us"]/dt)+1
    E.check(3<=n<=c["max_samples_per_event"] && (n-1)*dt<=c["max_window_ns"],"Injection exceeds bounds")
    # An actual NEGATIVE delta enters the fixed wiring before the unchanged CSA/RC propagator.
    raw=-E.charge_C(500.0,eion); adapted=FACTOR*raw
    x=[-adapted/(c["feedback_capacitance_pF"]*1e-12),0.,0.,0.,0.]
    pre=Float64[x[1]]; shaped=Float64[0.]; peak=0.; ip=0
    for k in 1:n-1
        x=M*x; v=-c["gain"]*x[4]; push!(pre,x[1]); push!(shaped,v)
        if v>peak; peak=v; ip=k; end
    end
    E.check(isfinite(peak) && peak>0 && ip<n-1,"Negative injection has no bounded positive peak")
    slope=peak/500.0; lsb=c["adc_full_scale_V"]/2^c["adc_bits"]
    cal=Dict{String,Any}("method"=>"independent negative delta-charge at t=0 through fixed -1 KM wiring; unchanged sampled analog transfer; one slope across all events",
        "energy_keV"=>500.0,"raw_charge_C"=>raw,"electronics_input_charge_C"=>adapted,
        "charge_C"=>adapted,"wiring_factor"=>FACTOR,"ionisation_energy_eV"=>eion,
        "peak_V"=>peak,"peak_time_ns"=>ip*dt,"volts_per_keV"=>slope,"time_step_ns"=>dt,
        "adc_lsb_V"=>lsb,"adc_half_lsb_energy_keV"=>lsb/2/slope,
        "adc_convention"=>"floor(V/LSB); reconstruct (code+0.5)*LSB; threshold inclusive; saturation at V>=$(c["adc_full_scale_V"]) V; $(c["adc_bits"])-bit peak ADC")
    injection=Dict("kind"=>"independent_negative_charge_injection_v1","wiring"=>wiring(),
        "raw_delta_charge_C"=>raw,"electronics_input_delta_charge_C"=>adapted,
        "energy_keV"=>500.0,"time_ns"=>collect(0:n-1).*dt,"preamp_V"=>pre,"shaped_V"=>shaped,
        "calibration"=>cal,"input_is_independent_of_event_truth"=>true)
    (calibration=cal,injection=injection)
end
function process(t,q,c,eion,cal,M;horizon_ns=nothing,model=MODEL)
    adapted=wired_charge(q,model)
    r=P.process(t,adapted,c,eion,cal,M;horizon_ns=horizon_ns)
    E.check(r["current_balance"]["passed"],"Adapted current/charge balance failed")
    # These are diagnostics of the unchanged raw input, separate from the electronics trace.
    r["wiring"]=wiring(model); r["raw_native_any_negative_charge"]=any(x->x<0,q)
    r["raw_native_final_charge_keV"]=last(q); r["raw_native_min_charge_keV"]=minimum(q)
    r["raw_native_max_charge_keV"]=maximum(q)
    r
end
function read_bound(path,expected;limit=1_000_000_000)
    E.check(expected isa String && occursin(HASH,expected),"Supply an external lowercase SHA256 authority")
    E.check(isfile(path) && !islink(path) && filesize(path)<=limit,"Missing/linked/oversized saved input")
    b=read(path); E.check(sha(b)==expected,"Saved input SHA256 mismatch: "*basename(path)); b
end
function check_sources()
    E.check(all(E.hashfile(joinpath(@__DIR__,n))==h for (n,h) in SOURCE_PINS),"Frozen readout dependency changed")
end
function checked_id(r,key)
    E.check(haskey(r,key) && E.integer(r[key]) && r[key]>=0,"Invalid discrete identity: "*key)
    Int(r[key])
end
function scalar_records(bytes,counts)
    records=[JSON.parse(line) for line in split(String(copy(bytes)),'\n') if !isempty(strip(line))]
    decays=Dict{Int,Any}(); pulses=Dict{Tuple{Int,Int,Int},Any}(); order=Tuple{Int,Int,Int}[]
    for r in records
        id=checked_id(r,"event_id"); globalid=checked_id(r,"global_decay_id")
        if r["record_kind"]=="decay"
            E.check(!haskey(decays,id) && r["group_id"]===nothing,"Duplicate/invalid initial decay")
            decays[id]=r
        else
            E.check(r["record_kind"]=="pulse","Unknown scalar record kind")
            gid=checked_id(r,"group_id"); key=(id,globalid,gid)
            E.check(!haskey(pulses,key),"Duplicate pulse identity"); pulses[key]=r; push!(order,key)
        end
    end
    n=counts["initial_primaries"]
    E.check(E.integer(n) && n>0 && Set(keys(decays))==Set(0:n-1),"Missing initial-decay census")
    E.check(length(Set(r["global_decay_id"] for r in values(decays)))==n,"Duplicate global decay identity")
    E.check(counts["initial_decays"]==n && length(pulses)==counts["groups"],"Scalar census differs from receipt")
    E.check(count(r->r["zero_deposit"]===true,values(decays))==counts["zero_deposit_primaries"],"Zero census differs")
    for (id,r) in decays
        own=[v for ((event,globalid,_),v) in pulses if event==id && globalid==r["global_decay_id"]]
        E.check(length(own)==r["pulse_count"] && r["zero_deposit"]==(r["deposited_energy_keV"]==0),"Decay/pulse census mismatch")
    end
    for ((id,globalid,_),r) in pulses
        E.check(haskey(decays,id) && decays[id]["global_decay_id"]==globalid,"Pulse has no matching primary")
        if get(r,"status",nothing)=="native_transport_failed"
            E.check(r["readout"]===nothing && r["final_induced_keV"]===nothing,"Failed native quantities must stay null")
        else
            E.check(r["readout"] isa AbstractDict && E.finite(r["final_induced_keV"]),"Unavailable successful native signal")
        end
    end
    E.check(count(r->get(r,"status",nothing)=="native_transport_failed",values(pulses))==counts["native_failed_groups"],"Native failure census differs")
    (records=records,pulses=pulses,order=order)
end
function signals(bytes,scalars,counts,dt)
    lines=split(String(copy(bytes)),'\n'); E.check(strip(first(lines))==SIGNAL_HEADER,"Unexpected signals CSV schema")
    waves=Dict{Tuple{Int,Int,Int},Tuple{Vector{Float64},Vector{Float64}}}(); order=Tuple{Int,Int,Int}[]
    current=nothing; sample_count=0
    for line in lines[2:end]
        isempty(strip(line)) && continue
        cells=split(strip(line),','); E.check(length(cells)==5,"Invalid signals CSV width")
        values=String[]
        for cell in cells
            E.check(occursin(r"^(\"[^\"]*\"|[^\",]*)$",cell),"Invalid numeric CSV cell")
            push!(values,startswith(cell,'"') ? cell[2:end-1] : cell)
        end
        E.check(all(v->occursin(r"^(0|[1-9][0-9]*)$",v),values[1:3]),"Invalid signal identity")
        key=Tuple(parse.(Int,values[1:3]))
        E.check(haskey(scalars.pulses,key) && scalars.pulses[key]["readout"]!==nothing,"Unknown/failed group has signals")
        if key!=current
            E.check(!haskey(waves,key),"Noncontiguous/repeated signal group")
            waves[key]=(Float64[],Float64[]); push!(order,key); current=key
        end
        t=parse(Float64,values[4]); q=parse(Float64,values[5]); E.check(E.finite(t) && E.finite(q),"Nonfinite signal sample")
        push!(waves[key][1],t); push!(waves[key][2],q); sample_count+=1
    end
    success=[k for k in scalars.order if scalars.pulses[k]["readout"]!==nothing]
    E.check(order==success && sample_count==counts["native_charge_samples"],"Incomplete/extra native signal coverage")
    for (key,(t,q)) in waves
        r=scalars.pulses[key]; E.validate_wave(t,q,dt,500000)
        E.check(length(t)==r["readout"]["input_sample_count"] && last(t)==r["charge_end_ns"] && last(q)==r["final_induced_keV"],"Native signal/scalar mismatch")
    end
    waves
end
function load_saved(input,run_sha,envelope_sha)
    check_sources(); input=realpath(input)
    localroot=realpath(joinpath(ROOT,".local"))
    E.check(startswith(input,localroot*(Sys.iswindows() ? "\\" : "/")),"Saved input must be inside project .local")
    rb=read_bound(joinpath(input,"run.json"),run_sha;limit=100_000_000); report=JSON.parse(String(rb))
    eb=read_bound(joinpath(input,"ring-response.json"),envelope_sha;limit=100_000_000); envelope=JSON.parse(String(eb))
    E.check(report["status"] in ("completed_provisional_native_response","completed_with_native_failures"),"Saved native stage is not terminal")
    E.check(envelope["kind"]=="ring_native_response_v1" && envelope["status"]==report["status"] && envelope["native_report_sha256"]==run_sha,"Ring envelope/report binding differs")
    contract=envelope["model_contract"]
    E.check(report["model_id"]==contract["model_id"]==MODEL && report["model_sha256"]==contract["effective_model_sha256"]==MODEL_SHA,"Fixed KM model identity differs")
    E.check(contract["contact_potentials_V"]==Dict("1"=>0,"2"=>-370) && report["readout_contact_id"]==1,"KM contact/bias differs")
    E.check(report["temperature_K"]==77 && report["stored_temperature_K"]==78,"KM recorded temperature policy differs")
    expected=copy(ARTIFACTS); report["counts"]["native_failed_groups"]>0 && push!(expected,"native-failures.jsonl")
    E.check(Set(keys(report["artifacts"]))==expected && Set(keys(report["artifact_bytes"]))==expected,"Incomplete/unknown artifact inventory")
    files=Dict{String,Vector{UInt8}}()
    for name in expected
        b=read_bound(joinpath(input,name),report["artifacts"][name]); E.check(length(b)==report["artifact_bytes"][name],"Saved artifact length differs")
        # Large endpoint/truth bytes are checked but not retained or deserialized.
        name in ("signals.csv","scalars.jsonl","profile.json","profile-input.json","readout-config.json") && (files[name]=b)
    end
    E.check(report["profile_sha256"]==PROFILE_SHA && sha(files["profile.json"])==PROFILE_SHA && files["profile.json"]==files["profile-input.json"],"Frozen profile bytes differ")
    profile=JSON.parse(String(copy(files["profile.json"]))); c=JSON.parse(String(copy(files["readout-config.json"])))
    P.validate_resolved(c,profile,report["counts"]["initial_primaries"])
    E.check(sha(files["readout-config.json"])==report["config_sha256"],"Resolved configuration binding differs")
    E.check(report["drift_dt_ns"]==2.0 && E.finite(report["ionisation_energy_eV"]) && report["ionisation_energy_eV"]>0,"Native signal units/grid differ")
    scalars=scalar_records(files["scalars.jsonl"],report["counts"])
    waves=signals(files["signals.csv"],scalars,report["counts"],report["drift_dt_ns"])
    (input=input,run_sha=run_sha,envelope_sha=envelope_sha,report=report,envelope=envelope,config=c,scalars=scalars,waves=waves)
end
function recheck(a)
    check_sources(); read_bound(joinpath(a.input,"run.json"),a.run_sha;limit=100_000_000)
    read_bound(joinpath(a.input,"ring-response.json"),a.envelope_sha;limit=100_000_000)
    for (name,h) in a.report["artifacts"]; read_bound(joinpath(a.input,name),h); end
    nothing
end
function derive(input,run_sha,envelope_sha,output)
    a=load_saved(input,run_sha,envelope_sha); environment=E.environment()
    output=abspath(output)
    E.check(dirname(output)==dirname(a.input) && !ispath(output),"Use a new sibling derivative leaf; never overwrite")
    own_sha=E.hashfile(@__FILE__); M=E.transition(a.config,a.report["drift_dt_ns"])
    calibration_started=time()
    injection=negative_calibration(a.config,a.report["ionisation_energy_eV"],a.report["drift_dt_ns"],M)
    calibration_seconds=time()-calibration_started
    recheck(a); mkdir(output)
    report=Dict{String,Any}("kind"=>"km_fixed_polarity_readout_derivative_v1","status"=>"running",
        "model_id"=>MODEL,"wiring"=>wiring(),"environment"=>environment,
        "source_native_report_sha256"=>a.run_sha,"source_ring_envelope_sha256"=>a.envelope_sha,
        "source_native_artifacts"=>a.report["artifacts"],"source_native_artifact_bytes"=>a.report["artifact_bytes"],
        "source_native_status"=>a.report["status"],"source_native_counts"=>a.report["counts"],
        "units"=>Dict("time"=>"ns","raw_native_equivalent_charge"=>"keV","electronics_input_equivalent_charge"=>"keV","charge"=>"fC","current"=>"nA","voltage"=>"V","energy"=>"keV"),
        "source_native_ref"=>replace(relpath(a.input,ROOT),'\\'=>'/'),
        "model_contract"=>a.envelope["model_contract"],"config"=>a.config,"calibration"=>injection.calibration,
        "source_sha256"=>merge(copy(SOURCE_PINS),Dict("ring_polarity.jl"=>own_sha)),
        "negative_injection_seconds"=>calibration_seconds,"native_calls"=>0,"field_calls"=>0,"radiation_calls"=>0,
        "scope"=>"Saved native signals through fixed linear wiring and unchanged ideal electronics; not experimental calibration, noise or Li CCE")
    started=time(); stage="readout"
    try
        E.save(joinpath(output,"negative-injection.json"),injection.injection)
        accepted=0; rejected=0; saturated=0; samples=0; rawrows=0
        open(joinpath(output,"scalars.jsonl"),"w") do scalario
          open(joinpath(output,"traces.jsonl"),"w") do traceio
           open(joinpath(output,"readout-input.csv"),"w") do signalio
            println(signalio,"event_id,global_decay_id,group_id,time_since_origin_ns,raw_native_charge_keV,electronics_input_charge_keV,raw_native_charge_fC,electronics_input_charge_fC,raw_native_current_nA,electronics_input_current_nA")
            for original in a.scalars.records
                r=deepcopy(original)
                if r["record_kind"]=="pulse"
                    if r["readout"]===nothing
                        rejected+=1 # native failure keeps its exact diagnostic/null record
                    else
                        key=pulse_key(r); t,q=a.waves[key]
                        result=process(t,q,a.config,a.report["ionisation_energy_eV"],injection.calibration,M;horizon_ns=r["group"]["horizon_ns"])
                        trace=pop!(result,"trace"); adapted=wired_charge(q); factor=E.charge_C(1.0,a.report["ionisation_energy_eV"])
                        for k in eachindex(t)
                            rawcurrent=k==1 ? 0. : (q[k]-q[k-1])*factor/(t[k]-t[k-1])*1e18
                            println(signalio,join(E.csvcell.((key...,t[k],q[k],adapted[k],q[k]*factor*1e15,adapted[k]*factor*1e15,rawcurrent,FACTOR*rawcurrent)),','));rawrows+=1
                        end
                        println(traceio,JSON.json(Dict("event_id"=>key[1],"global_decay_id"=>key[2],"group_id"=>key[3],"origin_time_ns"=>r["origin_time_ns"],
                            "trace"=>trace,"raw_native_induced_charge_fC"=>FACTOR .* trace["induced_charge_fC"],"raw_native_current_nA"=>FACTOR .* trace["current_nA"],"wiring"=>wiring())))
                        r["original_readout"]=r["readout"]; r["original_accepted"]=r["accepted"]; r["original_rejection_reason"]=r["rejection_reason"]
                        r["original_trace_saved"]=get(r,"trace_saved",false);r["trace_saved"]=true
                        r["readout"]=result; r["accepted"]=result["accepted"]; r["rejection_reason"]=result["rejection_reason"]
                        r["electronics_input_final_charge_keV"]=last(adapted); r["readout_wiring"]=wiring()
                        accepted+=result["accepted"]; rejected+=!result["accepted"]; saturated+=result["saturated"]; samples+=result["original_sample_count"]
                    end
                end
                println(scalario,JSON.json(r))
            end
           end
          end
        end
        stage="final_integrity"; recheck(a); E.check(E.hashfile(@__FILE__)==own_sha,"Adapter source changed")
        E.check(rawrows==a.report["counts"]["native_charge_samples"] && accepted+rejected==a.report["counts"]["groups"],"Derivative census differs")
        counts=merge(deepcopy(a.report["counts"]),Dict("accepted"=>accepted,"rejected"=>rejected,
            "readout_rejected"=>rejected-a.report["counts"]["native_failed_groups"],"saturated"=>saturated,"analog_samples"=>samples))
        report["counts"]=counts; report["all_saved_successful_group_signals_covered"]=true
        report["status"]=counts["native_failed_groups"]>0 ? "completed_with_native_failures" : "completed_readout_derivative"
        names=("negative-injection.json","scalars.jsonl","traces.jsonl","readout-input.csv")
        report["artifacts"]=Dict(n=>E.hashfile(joinpath(output,n)) for n in names)
        report["artifact_bytes"]=Dict(n=>filesize(joinpath(output,n)) for n in names)
    catch err
        report["status"]="failed";report["failure_stage"]=stage;report["error_type"]=string(typeof(err));rethrow()
    finally
        report["readout_derivation_seconds"]=time()-started
        report["timing_scope"]="Readout-only derivative after saved validation/injection; excludes startup and native/radiation/field computation"
        E.save(joinpath(output,"run.json"),report)
    end
    report
end
function main(args=ARGS)
    E.check(length(args)==8 && args[1]=="--input" && args[3]=="--source-run-sha256" && args[5]=="--source-envelope-sha256" && args[7]=="--output","Use --input DIR --source-run-sha256 SHA --source-envelope-sha256 SHA --output NEW_SIBLING_DIR")
    r=derive(args[2],args[4],args[6],args[8]);println(JSON.json(Dict("status"=>r["status"],"counts"=>r["counts"],"native_calls"=>0)))
end
end
if abspath(PROGRAM_FILE)==@__FILE__;RingPolarity.main();end
