# Bounded M14b display adapter. Host first includes frozen readout_profiles.jl.
# Electronics-only display derivative, never recovery of unsaved original arrays.
# No CLI, file output, SSD, radiation, calibration fitting or readout-result edits.
module SavedCollectionEdge
using ..Readout, ..ReadoutProfiles
const E=Readout
const P=ReadoutProfiles
const KIND="saved_collection_edge_display_v1"
const MAX_EDGE_POINTS=10001 # Explicit display cap; never an electronics setting.
const SOURCE_PINS=Dict(
    "readout.jl"=>"dfc0bfcdafd2b26bf5b73135d372dde15d2509bd8d3c4b83fefdc2bf9a1ab3c0",
    "readout_profiles.jl"=>"3f4475fffb6a13fa54235191cba6f03a7cfcd8f759da7e08ecbc05c4fe7b0130",
    "readout_demo.json"=>"33eb64724736c78852795ea001889759152ffefc22de9c4db6815fd1aaf8ee9e",
    "native_readout_profile.json"=>"7556e6e77d6c21e76e1a4eabb69b2b26875517252c083c88b6eb6a80502ef6e6",
    "Project.toml"=>"11d7d3241bf3e11d2b01172523fbc3637a5748c2026893e596cc830c324f367e",
    "Manifest.toml"=>"14b1dc8cd127ffa0ec417939ba4abdf6b31fb2258290b6f5d922f4def8ade051")

# Compare scalar types and binary64 bits, including signed zero. Container types
# may differ after JSON parsing; their contents must retain exact typed values.
function exact_value(a,b)
    if a isa AbstractDict && b isa AbstractDict
        return Set(keys(a))==Set(keys(b)) && all(exact_value(a[k],b[k]) for k in keys(a))
    elseif a isa AbstractArray && b isa AbstractArray
        return size(a)==size(b) && all(exact_value(x,y) for (x,y) in zip(a,b))
    elseif a isa Float64 && b isa Float64
        return reinterpret(UInt64,a)==reinterpret(UInt64,b)
    else
        return typeof(a)===typeof(b) && isequal(a,b)
    end
end

function checked_context(c,eion,cal,M)
    source_file,_=Base.functionloc(first(methods(E.process_event)))
    source_dir=dirname(realpath(string(source_file)))
    E.check(basename(source_file)=="readout.jl", "Unexpected electronics source")
    for (name,pin) in SOURCE_PINS
        E.check(E.hashfile(joinpath(source_dir,name))==pin, "Frozen electronics dependency changed: "*name)
    end
    profile=E.readjson(joinpath(source_dir,"native_readout_profile.json"))
    E.check(c isa AbstractDict && cal isa AbstractDict, "Config/calibration must be saved objects")
    P.validate_resolved(c,profile,20)
    E.check(exact_value(c,P.for_census(profile,20)), "Resolved config typed values changed")
    E.check(c["trace_max_points"]===600, "Original trace_max_points must remain 600")
    E.validate_peak_config(c)
    E.check(E.finite(eion) && eion==2.95, "Require recorded 2.95 eV ionisation energy")
    E.check(haskey(cal,"time_step_ns") && E.finite(cal["time_step_ns"]) && cal["time_step_ns"]==2.0,
        "Require recorded 2 ns analog grid")
    dt=cal["time_step_ns"]
    E.check(M isa Matrix{Float64} && size(M)==(5,5) && all(isfinite,M), "Invalid five-state transition")
    E.check(exact_value(M,E.transition(c,dt)), "Transition differs from unchanged electronics")
    E.check(exact_value(cal,P.calibration(c,eion,dt,M)), "Independent injection calibration changed")
    dt
end

"""
Replay only a bounded prefix of the full saved signed charge on its original grid.
This narrowly scoped candidate accepts the frozen gamma profile with census 20.
The caller owns hash-bound response/charge/config/calibration/identity provenance
and must omit this derivative for native-failed/null-charge records.
"""
function collection_edge_trace(t,q,c,eion,cal,M;stop_ns,max_edge_points)
    dt=checked_context(c,eion,cal,M)
    _collection_edge_trace(t,q,c,eion,cal,M,dt;stop_ns=stop_ns,max_edge_points=max_edge_points)
end

# Trusted batch callers validate the exact unchanged context once, retain that
# same config/calibration/matrix, and use this internal prefix operation. It
# performs no calibration injection; browser requests cannot call this function.
function _collection_edge_trace(t,q,c,eion,cal,M,dt;stop_ns,max_edge_points)
    E.check(t isa AbstractVector{Float64} && q isa AbstractVector{Float64}, "Require binary64 saved time/charge arrays")
    E.validate_wave(t,q,dt,c["max_samples_per_event"])
    tail=ceil(Int,1000*c["tail_shaping_constants"]*c["shaping_tau_us"]/dt)
    n=length(t)+tail
    gated=get(c,"peak_gate_end_ns",nothing)!==nothing
    gated && (n=max(n,floor(Int,c["peak_gate_end_ns"]/dt)+1))
    E.check(n<=c["max_samples_per_event"] && (n-1)*dt<=c["max_window_ns"], "Natural readout exceeds original bounds")
    E.check(E.finite(stop_ns) && 0<=stop_ns<=(n-1)*dt, "Display stop exceeds natural readout window")
    E.check(isinteger(stop_ns/dt), "Display stop must lie exactly on the analog grid")
    E.check(E.integer(max_edge_points) && 1<=max_edge_points<=MAX_EDGE_POINTS, "Invalid explicit display point bound")
    edge_count=Int(stop_ns/dt)+1
    E.check(edge_count<=max_edge_points, "Dense edge exceeds display point bound; keep original sparse/full view")
    cf=c["feedback_capacitance_pF"]*1e-12; factor=E.charge_C(1.,eion)
    preamp=zeros(edge_count); x=zeros(5)
    for k in 2:edge_count
        dq=k<=length(q) ? (q[k]-q[k-1])*factor : 0.
        x[5]=dq/dt/cf; x=M*x
        preamp[k]=x[1]
    end
    E.check(all(isfinite,preamp), "Nonfinite electronics display response")
    Dict("schema_version"=>1,"kind"=>KIND,
        "origin"=>"same_electronics_replay_from_saved_signed_charge",
        "scope"=>"electronics-only display derivative; unsaved original analog arrays are not recovered",
        "time_origin"=>"time since initial primary; numerical analog grid, not waveform ADC",
        "time_step_ns"=>dt,"captured_start_ns"=>0.0,"captured_stop_ns"=>stop_ns,
        "captured_sample_count"=>edge_count,"max_edge_points"=>max_edge_points,
        "input_sample_count"=>length(t),"input_charge_end_ns"=>last(t),
        "natural_readout_end_ns"=>(n-1)*dt,"original_trace_max_points"=>c["trace_max_points"],
        "time_ns"=>collect(0:edge_count-1).*dt,"preamp_V"=>preamp)
end

# Acceptance hook for original retained preamp points. No interpolation, tolerance
# or decimal-rounding equality is allowed. This hook does not run old6 by itself.
function retained_preamp_parity(edge,trace)
    E.check(edge["kind"]==KIND, "Not a collection-edge derivative")
    dt=edge["time_step_ns"]; et=edge["time_ns"]; ep=edge["preamp_V"]
    t=trace["time_ns"]; pre=trace["preamp_V"]
    E.check(length(t)==length(pre) && !isempty(t) && all(E.finite,t) && all(E.finite,pre), "Invalid retained preamp trace")
    E.check(first(t)==0 && all(diff(t).>0), "Invalid retained primary-relative sample order")
    matched=0; negative_zero_points=0
    for (time,value) in zip(t,pre)
        time>edge["captured_stop_ns"] && continue
        E.check(isinteger(time/dt), "Retained point lies off original analog grid")
        k=Int(time/dt)+1
        E.check(1<=k<=length(et) && exact_value(et[k],time), "Retained time changed")
        E.check(exact_value(ep[k],value), "Retained preamp binary64 mismatch at ns="*string(time))
        matched+=1; negative_zero_points+=(iszero(value) && signbit(value))
    end
    E.check(matched>0, "No retained original points lie in captured prefix")
    Dict("comparison"=>"binary64_bits_including_signed_zero","matched_points"=>matched,
        "matched_negative_zero_points"=>negative_zero_points,"passed"=>true)
end
end
