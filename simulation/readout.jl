"""
Independent, deterministic engineering readout; no SSD import or detector solve.
CLI: julia --project=simulation simulation/readout.jl --input CHARGE_DIR
     --truth TRANSPORT/events.json --config simulation/readout_demo.json --output .local/NEW

Output schema_version=1: run.json holds config, calibration, provenance, summary,
all selected events and explicit unselected_event_ids. Each event has the ledger,
flags, peak/ADC result and trace {time_ns,induced_charge_fC,current_nA,preamp_V,
shaped_V}. original_sample_count includes the zero-current tail; input_sample_count
is the charge CSV count. Traces preserve endpoints, charge_end_ns and the exact
sampled peak. At the default 600-point bound, all <=300 original charge samples
are kept; longer charge windows get ~75% of the budget, sparse pulse boundaries
and extrema, then deterministic bucket current/charge minima and maxima.
Dense features cannot all fit: trace_preserves_all_current_runs reports whether
every nonzero-current run's boundaries/extrema were retained. Tail samples use
the remaining budget. current_nA[k] is the ORIGINAL bin value on
(current_bin_start_ns[k],current_bin_end_ns[k]], not an integral or average
between adjacent display timestamps. The initial zero has the empty bin [0,0].
current_balance is computed on the full original grid, never the display trace.
By default any negative cumulative charge, however tiny, is rejected. Explicit
peak_policy="signed_input_positive_peak" retains the negative_input flag while
accepting otherwise valid positive peaks. Signed charge/current/preamp/shaped
voltages are never rectified. Optional finite peak gates use primary-relative ns.
Events reset at the primary time, with no pretrigger or cross-event state.
events.csv is the scalar ledger (flags are JSON in a quoted field). spectrum.csv
is a sparse histogram of ACCEPTED peak ADC codes, with bin-centre energy and counts.
Only these three files are exported; failure leaves run.json with failure_stage.
An existing destination is never touched; pre-reservation errors only reach stderr.
"""
module Readout
using JSON, SHA, LinearAlgebra, TOML
const ROOT = dirname(@__DIR__)
const ELECTRON_C = 1.602176634e-19
check(ok, message) = ok ? nothing : throw(ArgumentError(message))
finite(x) = x isa Real && !(x isa Bool) && isfinite(x)
integer(x) = x isa Integer && !(x isa Bool)
hashfile(p) = open(p) do io; bytes2hex(sha256(io)); end
save(p, x) = open(io -> print(io, JSON.json(x, 2), '\n'), p, "w")
near(a,b) = finite(a) && finite(b) && isapprox(a,b; rtol=1e-10, atol=1e-9)
function readjson(p)
    check(isfile(p) && filesize(p) <= 100_000_000, "Missing/oversized JSON input")
    JSON.parsefile(p)
end
function environment()
    active=Base.active_project(); project=joinpath(@__DIR__,"Project.toml")
    check(active!==nothing && realpath(active)==realpath(project), "Use the pinned simulation CPU project")
    selected=Base.project_file_manifest_path(active); manifestfile=joinpath(@__DIR__,"Manifest.toml")
    check(selected!==nothing && realpath(selected)==realpath(manifestfile), "Use the canonical CPU Manifest.toml")
    manifest=TOML.parsefile(selected)
    check(v"1.13"<=VERSION<v"1.14" && Base.pkgversion(JSON)==v"1.9.0", "Use pinned Julia 1.13.x / JSON 1.9.0")
    check(only(manifest["deps"]["JSON"])["version"]=="1.9.0" &&
          only(manifest["deps"]["SolidStateDetectors"])["version"]=="0.11.8", "Unexpected pinned package versions")
    Dict("project"=>"simulation/Project.toml","manifest"=>"simulation/Manifest.toml",
        "project_sha256"=>hashfile(project),"manifest_sha256"=>hashfile(selected),
        "julia_version"=>string(VERSION),"pinned_julia_version"=>manifest["julia_version"],
        "json_version"=>string(Base.pkgversion(JSON)),"json_source_sha256"=>hashfile(pathof(JSON)))
end
function config(p)
    c = readjson(p); defaults = readjson(joinpath(@__DIR__, "readout_demo.json"))
    check(issubset(Set(keys(c)),union(Set(keys(defaults)),Set(("peak_policy","peak_gate_start_ns","peak_gate_end_ns")))), "Unknown config key")
    # Omitted PZ follows feedback, even when feedback differs from the demo.
    c = merge(defaults, c)
    supplied = readjson(p)
    haskey(supplied,"pole_zero_tau_us") || (c["pole_zero_tau_us"] = c["feedback_tau_us"])
    check(c["schema_version"] === 1, "Unsupported config schema")
    for k in ("feedback_capacitance_pF","feedback_tau_us","pole_zero_tau_us","shaping_tau_us","gain",
              "tail_shaping_constants","max_window_ns","adc_full_scale_V","calibration_energy_keV")
        check(finite(c[k]) && c[k] > 0, "Invalid positive config value: " * k)
    end
    check(c["tail_shaping_constants"] >= 20, "Require at least 20 shaping constants of tail")
    for (k,lo,hi) in (("max_samples_per_event",3,500_000),("max_total_samples",3,20_000_000),("trace_max_points",12,600))
        check(integer(c[k]) && lo <= c[k] <= hi, "Invalid sample limit: " * k)
    end
    check(c["adc_bits"] === 14 && c["adc_full_scale_V"] == 10, "Demo ADC is 14 bit, 0..10 V")
    check(finite(c["threshold_V"]) && 0 < c["threshold_V"] < c["adc_full_scale_V"], "Invalid threshold")
    check(c["require_all_events"] isa Bool, "Invalid selection policy")
    n=c["expected_primary_count"]
    check(n === nothing || (integer(n) && 0 < n <= 100_000), "Invalid expected census")
    validate_peak_config(c)
    c
end

const LEGACY_PEAK_POLICY = "legacy_reject_negative_input"
const SIGNED_PEAK_POLICY = "signed_input_positive_peak"
function validate_peak_config(c)
    check(get(c,"peak_policy",LEGACY_PEAK_POLICY) in (LEGACY_PEAK_POLICY,SIGNED_PEAK_POLICY), "Unknown peak policy")
    start=get(c,"peak_gate_start_ns",nothing); stop=get(c,"peak_gate_end_ns",nothing)
    check((start===nothing)==(stop===nothing), "Supply both peak gate bounds")
    if start!==nothing
        check(finite(start) && finite(stop) && 0<=start<stop<=c["max_window_ns"], "Invalid finite primary-relative peak gate")
    end
    c
end

# States [vpre,z,r1,r2,I/Cf]. Time is ns, so last state is V/ns.
# vpre'=-vpre/tf-I/Cf; z'=(vpre-z)/ts;
# u=vpre+(ts/tpz-1)z; r1'=(u-r1)/ts; r2'=(r1-r2)/ts.
# shaped=-gain*r2 is the explicit polarity inversion. No additional CR stage.
function transition(c, dt)
    check(finite(dt) && dt > 0, "Invalid time step")
    tf,ts,tpz = 1000 .* [c["feedback_tau_us"],c["shaping_tau_us"],c["pole_zero_tau_us"]]
    A=zeros(5,5); A[1,1]=-1/tf; A[1,5]=-1
    A[2,1]=1/ts; A[2,2]=-1/ts
    A[3,1]=1/ts; A[3,2]=(ts/tpz-1)/ts; A[3,3]=-1/ts
    A[4,3]=1/ts; A[4,4]=-1/ts
    M=exp(A*dt); check(all(isfinite,M), "Nonfinite propagator"); M
end
charge_C(keV, eion) = keV * 1000 / eion * ELECTRON_C
function calibration(c, eion, dt, M=transition(c,dt))
    check(finite(eion) && eion > 0, "Invalid recorded ionisation energy")
    n=ceil(Int,20_000*c["shaping_tau_us"]/dt)+1
    check(3 <= n <= c["max_samples_per_event"] && (n-1)*dt <= c["max_window_ns"], "Calibration exceeds window/sample bound")
    q=charge_C(c["calibration_energy_keV"],eion); cf=c["feedback_capacitance_pF"]*1e-12
    x=[-q/cf,0.,0.,0.,0.]; peak=0.; ip=0
    for k in 1:n-1
        x=M*x; v=-c["gain"]*x[4]
        if v>peak; peak=v; ip=k; end
    end
    check(isfinite(peak) && peak > 0 && ip < n-1, "Invalid pulser peak/window")
    slope=peak/c["calibration_energy_keV"]
    Dict("method"=>"single delta-charge injection at t=0; sampled analog peak; fixed across events",
        "energy_keV"=>c["calibration_energy_keV"],"charge_C"=>q,"ionisation_energy_eV"=>eion,
        "peak_V"=>peak,"peak_time_ns"=>ip*dt,"volts_per_keV"=>slope,
        "time_step_ns"=>dt,"adc_convention"=>"floor(V/LSB); reconstruct (code+0.5)*LSB; threshold inclusive; saturation at V>=10 V",
        "adc_lsb_V"=>c["adc_full_scale_V"]/2^c["adc_bits"],
        "adc_half_lsb_energy_keV"=>c["adc_full_scale_V"]/2^c["adc_bits"]/2/slope)
end
function digitize(peak, c, cal; negative=false, window_limited=false, gate_limited=false)
    check(finite(peak), "Nonfinite peak")
    lsb=cal["adc_lsb_V"]; full=c["adc_full_scale_V"]
    code=peak <= 0 ? 0 : peak >= full ? 2^c["adc_bits"]-1 : floor(Int,peak/lsb)
    policy=get(c,"peak_policy",LEGACY_PEAK_POLICY)
    check(policy in (LEGACY_PEAK_POLICY,SIGNED_PEAK_POLICY), "Unknown peak policy")
    reason=negative && policy==LEGACY_PEAK_POLICY ? "negative_input" : peak >= full ? "saturated" :
        window_limited ? "peak_at_window_end" : gate_limited ? "peak_at_gate_boundary" :
        peak < c["threshold_V"] ? "below_threshold" : nothing
    Dict{String,Any}("adc_code"=>code,"accepted"=>reason === nothing,"rejection_reason"=>reason,
        "adc_midpoint_V"=>(code+0.5)*lsb,"saturated"=>peak >= full,
        "peak_policy"=>policy,"negative_input"=>negative,"below_threshold"=>peak<c["threshold_V"],
        "nonpositive_peak"=>peak<=0,"adc_lower_clipped"=>peak<0,
        "window_limited"=>window_limited,"gate_limited"=>gate_limited,
        "analog_energy_keV"=>peak/cal["volts_per_keV"],
        "reconstructed_energy_keV"=>reason === nothing ? (code+0.5)*lsb/cal["volts_per_keV"] : nothing)
end
function validate_wave(t,q,dt,limit)
    check(finite(dt) && dt>0, "Invalid waveform step")
    check(2 <= length(t) <= limit && length(t)==length(q), "Invalid sample count")
    check(all(finite,t) && all(finite,q) && first(t)==0 && first(q)==0, "Invalid samples/initial charge")
    check(all(diff(t).>0), "Repeated/reversed times")
    check(all(k -> isapprox(t[k],(k-1)*dt; rtol=0,atol=max(1e-9,dt*1e-8)), eachindex(t)), "Nonuniform/noncausal times")
end
function trace_indices(q,current,n,ip,limit)
    n<=limit && return (collect(1:n),true)
    m=length(q); budget=min(m,floor(Int,.75*(limit-3)))
    head=Set([1,m,argmin(@view current[1:m]),argmax(@view current[1:m]),argmin(q),argmax(q)])
    allruns=true
    if m<=300 && m<=budget
        union!(head,1:m)
    else
        # Sparse pulses retain both original-bin support edges and extrema,
        # including unequal pulses in the same bucket. Bound auxiliary storage.
        runs=copy(head); k=2
        while k<=m
            if iszero(current[k]); k+=1; continue; end
            firstbin=k
            while k<m && !iszero(current[k+1]); k+=1; end
            block=@view current[firstbin:k]
            union!(runs,(firstbin-1,firstbin,k,min(m,k+1),
                firstbin-1+argmin(block),firstbin-1+argmax(block)))
            if length(runs)>budget÷2; allruns=false; break; end
            k+=1
        end
        allruns && union!(head,runs)
        buckets=(budget-length(head))÷4
        for b in 1:buckets
            lo=1+fld((b-1)*m,buckets); hi=fld(b*m,buckets)
            for a in (current,q)
                block=@view a[lo:hi]
                union!(head,(lo-1+argmin(block),lo-1+argmax(block)))
            end
        end
        for k in round.(Int,range(1,m;length=budget))
            length(head)>=budget && break
            push!(head,k)
        end
    end
    idx=sort!(unique!(vcat(collect(head),ip,
        round.(Int,range(m+1,n;length=limit-length(head)-1)))))
    check(length(idx)<=limit, "Trace selection exceeded display bound")
    idx,allruns
end
function process_event(t,q,c,eion,cal,M)
    validate_peak_config(c)
    dt=cal["time_step_ns"]; validate_wave(t,q,dt,c["max_samples_per_event"])
    tail=ceil(Int,1000*c["tail_shaping_constants"]*c["shaping_tau_us"]/dt)
    n=length(t)+tail
    gated=get(c,"peak_gate_end_ns",nothing)!==nothing
    gated && (n=max(n,floor(Int,c["peak_gate_end_ns"]/dt)+1))
    check(n <= c["max_samples_per_event"] && (n-1)*dt <= c["max_window_ns"], "Readout window/sample bound exceeded")
    cf=c["feedback_capacitance_pF"]*1e-12; factor=charge_C(1.,eion)
    pre=zeros(n); shaped=zeros(n); current=zeros(n); x=zeros(5)
    for k in 2:n
        dq=k<=length(q) ? (q[k]-q[k-1])*factor : 0.
        current[k]=dq/dt*1e18 # C/ns -> nA
        x[5]=dq/dt/cf; x=M*x
        pre[k]=x[1]; shaped[k]=-c["gain"]*x[4]
    end
    check(all(isfinite,pre) && all(isfinite,shaped) && all(isfinite,current), "Nonfinite electronics response")
    lo=gated ? ceil(Int,c["peak_gate_start_ns"]/dt)+1 : 1
    hi=gated ? floor(Int,c["peak_gate_end_ns"]/dt)+1 : n
    check(1<=lo<hi<=n,"Peak gate must contain at least two analog samples")
    peak,relative_ip=findmax(@view shaped[lo:hi]); ip=lo+relative_ip-1
    gate_limited=gated && peak>0 && (ip==lo || ip==hi)
    idx,allruns=trace_indices(q,current,n,ip,c["trace_max_points"])
    trace=Dict("time_ns"=>(idx.-1).*dt,"induced_charge_fC"=>[q[min(k,length(q))]*factor*1e15 for k in idx],
        "current_bin_start_ns"=>max.(0,idx.-2).*dt,"current_bin_end_ns"=>(idx.-1).*dt,
        "current_nA"=>current[idx],"preamp_V"=>pre[idx],"shaped_V"=>shaped[idx])
    integrated=sum(current)*dt*1e-18; delta=(last(q)-first(q))*factor
    tolerance=64eps(Float64)*sum(abs,current)*dt*1e-18
    balance=Dict{String,Any}("integrated_current_C"=>integrated,"charge_change_C"=>delta,
        "residual_C"=>integrated-delta,"tolerance_C"=>tolerance,
        "passed"=>abs(integrated-delta)<=tolerance)
    # Diagnostic only: neither normalizes charge nor changes pulse acceptance.
    negative=any(x->x<0,q)
    result=digitize(peak,c,cal;negative=negative,window_limited=ip==n,gate_limited=gate_limited)
    merge!(result,Dict("peak_V"=>peak,"peak_time_ns"=>(ip-1)*dt,"trace"=>trace,
        "input_sample_count"=>length(t),"original_sample_count"=>n,"readout_end_ns"=>(n-1)*dt,
        "charge_end_ns"=>last(t),"tail_window_ns"=>(n-length(t))*dt,"window_limited"=>ip==n,
        "current_balance"=>balance,"trace_preserves_all_current_runs"=>allruns,
        "negative_input"=>negative,"final_charge_C"=>last(q)*factor))
    merge!(result,Dict("explicit_peak_gate"=>gated,"peak_gate_start_ns"=>(lo-1)*dt,
        "peak_gate_end_ns"=>(hi-1)*dt,"gate_limited"=>gate_limited,
        "input_activity_outside_peak_gate"=>gated && any(k->current[k]!=0 && (max(0,k-2)*dt<c["peak_gate_start_ns"] || (k-1)*dt>c["peak_gate_end_ns"]),eachindex(current)),
        "analog_above_adc_range"=>any(v->v>=c["adc_full_scale_V"],shaped),
        "analog_below_adc_range"=>any(v->v<0,shaped)))
    result
end

function load_inputs(input,truth,c)
    r=readjson(joinpath(input,"run.json")); d=readjson(truth)
    check(r["status"] in ("completed","completed_with_transport_flags"), "Charge run did not complete")
    check(d["schema_version"] === 1 && d["units"] == Dict("energy"=>"keV","length"=>"mm","time"=>"ns"), "Invalid truth schema/units")
    check(d["model_id"] in ("AK02","SAP22") && r["model_id"]==d["model_id"], "Model ID mismatch")
    catalog=readjson(joinpath(ROOT,"models","catalog.json"))
    entry=only(filter(e->e["id"]==d["model_id"],catalog["detectors"]))
    check(r["model_sha256"]==d["model_sha256"]==entry["model_sha256"]==hashfile(joinpath(ROOT,"models",d["model_id"]*".yaml")), "Model hash mismatch")
    check(r["input_sha256"]==hashfile(truth), "Truth hash mismatch")
    check(r["source_lh5_sha256"]==d["source_lh5_sha256"], "Raw source identity mismatch")
    for name in ("run.jl","replay.jl")
        check(r["source_code_sha256"][name]==hashfile(joinpath(@__DIR__,name)), "Replay source hash mismatch: "*name)
    end
    check(r["ssd_version"]=="0.11.8" && v"1.13"<=VersionNumber(r["julia_version"])<v"1.14", "Unreviewed charge software versions")
    check(occursin(r"^[0-9a-f]{64}$",r["environment_manifest_sha256"]), "Invalid charge environment hash")
    for (file,key) in (("truth.lh5","source_lh5_sha256"),("geometry.gdml","geometry_sha256"),("run.mac","macro_sha256"))
        check(hashfile(joinpath(dirname(truth),file))==d[key], "Transport source hash mismatch: "*file)
    end
    for (file,key) in (("prepared.json","prepared_sha256"),("run.json","run_sha256"))
        check(hashfile(joinpath(dirname(truth),file))==d["provenance"][key]==r["source_provenance"][key], "Transport provenance mismatch: "*file)
    end
    n=d["primary_count"]; sel=r["selected_primary_count"]
    check(integer(n) && 0<n<=100_000 && n==r["primary_count"]==length(d["events"]), "Invalid primary census")
    check(integer(sel) && 0<sel<=n && sel==length(r["events"]), "Invalid selected census")
    check(c["expected_primary_count"]===nothing || n==c["expected_primary_count"], "Unexpected demo census")
    check(!c["require_all_events"] || sel==n, "Demo requires all primaries")
    ids=[e["event_id"] for e in d["events"]]
    check(all(integer,ids) && ids==collect(0:n-1), "Truth IDs must be the replay primary census")
    check([e["event_id"] for e in r["events"]]==ids[1:sel] && r["unselected_event_ids"]==ids[sel+1:end], "Selected/unselected IDs mismatch")
    check(all(e->integer(e["event_id"]),r["events"]) && all(integer,r["unselected_event_ids"]), "Noninteger replay IDs")
    total=0.; flagged=false
    for (i,event) in enumerate(d["events"])
        check(all(s->finite(s["energy_keV"]) && s["energy_keV"]>=0,event["steps"]), "Invalid truth energy")
        energy=sum((s["energy_keV"] for s in event["steps"]);init=0.)
        total+=energy
        i>sel && continue
        e=r["events"][i]
        check(near(e["deposited_energy_keV"],energy), "Charge/truth energy mismatch")
        check(e["status"] in ("completed","zero_deposit","stopped_without_contact","step_limit"), "Unknown charge status")
        limited=any(s->any(x->x["step_limit_reached"]===true,s["endpoints"]),e["steps"])
        stopped=any(s->any(x->x["status"]=="stopped_without_contact",s["endpoints"]),e["steps"])
        expected=energy==0 ? "zero_deposit" : limited ? "step_limit" : stopped ? "stopped_without_contact" : "completed"
        check(e["status"]==expected, "Endpoint flags/status mismatch")
        check((energy==0)==(e["status"]=="zero_deposit"), "Zero-deposit status mismatch")
        check(near(event["primary_time_ns"],e["primary_time_ns"]), "Primary time mismatch")
        check(integer(e["samples"]) && 2<=e["samples"]<=c["max_samples_per_event"], "Bad reported sample count")
        flagged |= e["status"] in ("stopped_without_contact","step_limit")
    end
    check(near(total,d["energy_sum_keV"]), "Truth energy ledger mismatch")
    check((r["status"]=="completed_with_transport_flags")==flagged, "Inconsistent run flags")
    check(finite(r["ionisation_energy_eV"]) && r["ionisation_energy_eV"]>0 && finite(r["time_step_ns"]) && r["time_step_ns"]>0, "Invalid charge units/time step")
    r,d,entry
end
function readrow(io)
    b=IOBuffer()
    while !eof(io)
        v=read(io,UInt8); v==0x0a && break
        check(position(b)<256, "Oversized CSV row"); write(b,v)
    end
    line=String(take!(b)); endswith(line,"\r") ? chop(line;tail=1) : line
end
function read_wave(io,e,r,c)
    t=Float64[]; q=Float64[]
    for _ in 1:e["samples"]
        check(!eof(io), "Missing CSV rows")
        line=readrow(io)
        f=split(line,','); check(length(f)==3, "Bad CSV row schema")
        check(parse(Int,f[1])==e["event_id"], "Mixed/repeated/out-of-order CSV IDs")
        push!(t,parse(Float64,f[2])); push!(q,parse(Float64,f[3]))
    end
    validate_wave(t,q,r["time_step_ns"],c["max_samples_per_event"])
    check(near(last(t),e["time_since_primary_end_ns"]) && near(last(q),e["final_induced_equivalent_energy_keV"]), "Charge endpoint/report mismatch")
    check(e["status"]!="zero_deposit" || all(iszero,q), "Zero-deposit event has charge")
    t,q
end
function reserve_output(output)
    path=abspath(output); parent=dirname(path); localroot=realpath(joinpath(ROOT,".local"))
    check(!ispath(path) && !islink(path) && isdir(parent), "Output must be new with an existing parent")
    relative=relpath(realpath(parent),localroot)
    check(!isabspath(relative) && !any(==(".."),splitpath(relative)), "Output must be under project .local")
    mkdir(path); path
end
const COLUMNS=("event_id","deposited_energy_keV","final_induced_equivalent_energy_keV","charge_status",
    "peak_V","peak_time_ns","adc_code","analog_energy_keV","reconstructed_energy_keV","accepted","rejection_reason","flags")
csvcell(x)=x===nothing ? "" : "\""*replace(x isa AbstractDict || x isa AbstractVector ? JSON.json(x) : string(x),'"'=>"\"\"")*"\""
function export_tables(output,events,cal)
    open(joinpath(output,"events.csv"),"w") do io
        println(io,join(COLUMNS,','))
        for e in events; println(io,join([csvcell(e[k]) for k in COLUMNS],',')); end
    end
    counts=Dict{Int,Int}()
    for e in events; e["accepted"] && (counts[e["adc_code"]]=get(counts,e["adc_code"],0)+1); end
    open(joinpath(output,"spectrum.csv"),"w") do io
        println(io,"adc_code,energy_center_keV,accepted_count")
        for k in sort!(collect(keys(counts))); println(io,k,',',(k+.5)*cal["adc_lsb_V"]/cal["volts_per_keV"],',',counts[k]); end
    end
end
function run(input,truth,configfile,output)
    output=reserve_output(output)
    report=Dict{String,Any}("schema_version"=>1,"status"=>"running","events"=>Any[])
    stage="environment"
    try
        env=environment(); stage="config"; c=config(configfile)
        stage="input_validation"; r,d,entry=load_inputs(input,truth,c)
        signalfile=joinpath(input,"signals.csv")
        check(filesize(signalfile)<=1_000_000_000, "Oversized signals CSV")
        sources=Dict{String,Any}("charge_run_sha256"=>hashfile(joinpath(input,"run.json")),"signals_sha256"=>hashfile(signalfile),
            "truth_sha256"=>hashfile(truth),"model_sha256"=>d["model_sha256"],"source_lh5_sha256"=>d["source_lh5_sha256"],
            "geometry_sha256"=>d["geometry_sha256"],"macro_sha256"=>d["macro_sha256"],
            "prepared_sha256"=>d["provenance"]["prepared_sha256"],"transport_run_sha256"=>d["provenance"]["run_sha256"],
            "model_catalog_sha256"=>hashfile(joinpath(ROOT,"models","catalog.json")),
            "readout_source_sha256"=>hashfile(@__FILE__),"config_sha256"=>hashfile(configfile),
            "test_source_sha256"=>hashfile(joinpath(@__DIR__,"test_readout.jl")),"readout_environment"=>env,
            "manifest_sha256"=>hashfile(joinpath(@__DIR__,"Manifest.toml")),
            "charge_source_sha256"=>Dict(k=>r["source_code_sha256"][k] for k in ("run.jl","replay.jl")),
            "charge_manifest_sha256"=>r["environment_manifest_sha256"])
        stage="calibration"; dt=r["time_step_ns"]; M=transition(c,dt)
        cal=calibration(c,r["ionisation_energy_eV"],dt,M)
        transport_meta=Dict{String,Any}(k=>d["provenance"][k] for k in ("seed","versions","extractor_versions","lock_sha256"))
        check(integer(transport_meta["seed"]) && transport_meta["seed"]>0, "Invalid recorded transport seed")
        check(occursin(r"^[0-9a-f]{64}$",transport_meta["lock_sha256"]), "Invalid transport lock hash")
        for versions in (transport_meta["versions"],transport_meta["extractor_versions"],
                         Dict("julia"=>r["julia_version"],"ssd"=>r["ssd_version"]))
            check(all(v->v isa AbstractString && occursin(r"^[A-Za-z0-9_.+ -]{1,100}$",v),values(versions)) &&
                  all(k->occursin(r"^[A-Za-z0-9_.+-]{1,50}$",k),keys(versions)), "Invalid version metadata")
        end
        sources["transport"]=transport_meta
        sources["charge_versions"]=Dict("julia"=>r["julia_version"],"ssd"=>r["ssd_version"])
        merge!(report,Dict("model_id"=>r["model_id"],"config"=>c,"calibration"=>cal,"provenance"=>sources,
            "julia_version"=>string(VERSION),"json_version"=>string(Base.pkgversion(JSON)),
            "pinned_julia_version"=>env["pinned_julia_version"],"random_seed"=>nothing,
            "readout_contact_id"=>entry["readout_contact_id"],"contact_provenance"=>"replay default from versioned model catalog",
            "units"=>Dict("time"=>"ns","charge"=>"fC","current"=>"nA","voltage"=>"V","energy"=>"keV"),
            "time_step_ns"=>dt,"time_origin"=>"time since each primary; numerical analog grid, not waveform ADC",
            "polarity"=>"positive induced charge gives negative CSA; shaped=-gain*r2",
            "supported_waveform_policy"=>"Reject any negative cumulative charge sample, however tiny; conservative domain restriction, not general polarity classification. Signed signals remain unchanged.",
            "trace_current_convention"=>"Sampled original-bin current on (current_bin_start_ns,current_bin_end_ns]; initial bin [0,0]. Never integrate over gaps between display timestamps.",
            "unselected_event_ids"=>r["unselected_event_ids"],"limitations"=>[
                "Synthetic finite-feedback CSA and compensated RC cascade; not a manufacturer exact Gaussian network.",
                "The 0.5 us selected RC pole is not an ORTEC panel shaping-time calibration.",
                "No noise, Fano, pileup, BLR, hardware calibration or validated Li CCE; at most one pulse per primary.",
                "Incomplete charge trajectories are retained. Constant terminal charge implies zero tail current, not completed collection.",
                "Fixed ideal delta pulser calibration; finite-duration ballistic deficit is not corrected.",
                "Peak is sampled on the analog numerical grid; traces are decimated display data.",
                "The display budget cannot preserve arbitrarily dense current structure; trace_preserves_all_current_runs marks sparse-run support/extrema preservation.",
                "Any negative cumulative charge is conservatively rejected, including arbitrarily tiny excursions; this is a supported-waveform restriction."] ))
        if get(c,"peak_policy",LEGACY_PEAK_POLICY)==SIGNED_PEAK_POLICY
            report["supported_waveform_policy"]="Signed input is preserved; accept an otherwise valid positive sampled peak. Negative input is an independent diagnostic."
            report["limitations"][end]="Signed-input acceptance is an engineering policy, not a physical charge-collection or noise-validation claim."
        end
        stage="event_processing"; samples=0
        open(signalfile) do io
            check(readrow(io)=="event_id,time_since_primary_ns,induced_equivalent_energy_keV", "Invalid CSV header")
            for e in r["events"]
                predicted=e["samples"]+ceil(Int,1000*c["tail_shaping_constants"]*c["shaping_tau_us"]/dt)
                get(c,"peak_gate_end_ns",nothing)!==nothing && (predicted=max(predicted,floor(Int,c["peak_gate_end_ns"]/dt)+1))
                samples+=predicted; check(samples<=c["max_total_samples"], "Total sample budget exceeded")
                t,q=read_wave(io,e,r,c); result=process_event(t,q,c,r["ionisation_energy_eV"],cal,M)
                flags=Dict("charge_status"=>e["status"],"steps"=>[Dict("raw_row_index"=>s["raw_row_index"],
                    "endpoints"=>s["endpoints"]) for s in e["steps"]])
                merge!(result,Dict("event_id"=>e["event_id"],"deposited_energy_keV"=>e["deposited_energy_keV"],
                    "final_induced_equivalent_energy_keV"=>e["final_induced_equivalent_energy_keV"],
                    "charge_status"=>e["status"],"flags"=>flags,"primary_time_ns"=>e["primary_time_ns"]))
                push!(report["events"],result)
            end
            check(eof(io), "Extra/repeated CSV rows")
        end
        stage="export"; events=report["events"]
        check(hashfile(signalfile)==sources["signals_sha256"] && hashfile(joinpath(input,"run.json"))==sources["charge_run_sha256"] && hashfile(truth)==sources["truth_sha256"], "Inputs changed during readout")
        report["summary"]=Dict("primary_count"=>d["primary_count"],"selected_primary_count"=>length(events),
            "accepted_count"=>count(e->e["accepted"],events),"rejected_count"=>count(e->!e["accepted"],events),
            "zero_deposit_count"=>count(e->e["charge_status"]=="zero_deposit",events),
            "transport_flagged_count"=>count(e->e["charge_status"] in ("step_limit","stopped_without_contact"),events),
            "total_original_samples"=>samples,"spectrum_selection"=>"accepted pulses only; every event retained in ledger")
        export_tables(output,events,cal); report["status"]="completed"
    catch err
        report["status"]="failed"; report["failure_stage"]=stage
        # Exception text may contain private paths; retain type/stage in export, detail on stderr.
        report["error_type"]=string(typeof(err)); rethrow()
    finally
        save(joinpath(output,"run.json"),report)
    end
    report
end
function main(args=ARGS)
    args==["--help"] && return println(@doc Readout)
    check(length(args)==8, "Required options: --input --truth --config --output")
    opt=Dict{String,String}()
    for i in 1:2:length(args)
        k=args[i]; check(k in ("--input","--truth","--config","--output") && !haskey(opt,k), "Unknown/duplicate option")
        opt[k]=args[i+1]
    end
    run(opt["--input"],opt["--truth"],opt["--config"],opt["--output"])
end
end
if abspath(PROGRAM_FILE)==@__FILE__; Readout.main(); end
