# Additive profile contract. The schema-1 loader and frozen demo are unchanged.
isdefined(@__MODULE__, :Readout) || include("readout.jl")
module ReadoutProfiles
using ..Readout, JSON, SHA
const E=Readout
const KIND="native_readout_profile_v1"
const SETTINGS=("feedback_capacitance_pF","feedback_tau_us","pole_zero_tau_us",
    "shaping_tau_us","gain","adc_bits","adc_full_scale_V","threshold_V",
    "peak_policy","peak_gate_start_ns","peak_gate_end_ns")
function validate(p)
    E.check(Set(keys(p))==Set(("schema_version","kind","name","settings")),"Unknown/missing profile field")
    E.check(p["schema_version"]===2 && p["kind"]==KIND,"Unsupported profile version")
    E.check(p["name"] isa String && occursin(r"^[A-Za-z0-9_.-]{1,80}$",p["name"]),"Invalid profile name")
    s=p["settings"]
    E.check(s isa AbstractDict && Set(keys(s))==Set(SETTINGS),"Supply every profile setting exactly")
    for k in ("feedback_capacitance_pF","feedback_tau_us","pole_zero_tau_us","shaping_tau_us","gain","adc_full_scale_V")
        E.check(E.finite(s[k]) && s[k]>0,"Invalid positive profile value: "*k)
    end
    E.check(E.integer(s["adc_bits"]) && 2<=s["adc_bits"]<=24,"ADC bits must be 2..24")
    E.check(E.finite(s["threshold_V"]) && 0<s["threshold_V"]<s["adc_full_scale_V"],"Invalid threshold")
    c=merge(E.config(joinpath(@__DIR__,"readout_demo.json")),s)
    # Schema 2 is for this entry only, never routed through the legacy loader.
    c["schema_version"]=2; c["expected_primary_count"]=nothing
    delete!(c,"max_total_samples") # schema2 streams groups; only per-group memory is bounded
    E.validate_peak_config(c)
    c
end
function load(path)
    p=E.readjson(path); c=validate(p)
    (profile=p,config=c,sha256=E.hashfile(path))
end
function for_census(p,n)
    E.check(E.integer(n) && 1<=n<=100000,"Invalid profile primary census")
    c=validate(p); c["expected_primary_count"]=n; c
end
function validate_resolved(c,p,n)
    E.check(c==for_census(p,n),"Generated readout configuration differs from profile beyond expected primary count")
    nothing
end
function calibration(c,eion,dt,M=E.transition(c,dt))
    cal=E.calibration(c,eion,dt,M)
    cal["adc_convention"]="floor(V/LSB); reconstruct (code+0.5)*LSB; threshold inclusive; saturation at V>=$(c["adc_full_scale_V"]) V; $(c["adc_bits"])-bit peak ADC"
    cal
end
function window_config(c,horizon_ns,dt)
    E.check(E.finite(dt) && dt>0 && E.finite(horizon_ns) && dt<horizon_ns<=c["max_window_ns"],"Invalid isolated horizon")
    stop=(ceil(Int,horizon_ns/dt)-1)*dt # strictly before the half-open end
    E.check(stop/dt+1<=c["max_samples_per_event"],"Isolated window exceeds sample bound")
    if get(c,"peak_gate_end_ns",nothing)!==nothing
        E.check(c["peak_gate_end_ns"]<=stop,"Peak gate extends beyond isolated numerical window")
    end
    stop
end
# Clip only at the declared isolated-window boundary. Native endpoints and the
# untruncated terminal charge remain separate output fields; never force Edep.
function process(t,q,c,eion,cal,M; horizon_ns=nothing)
    if horizon_ns===nothing
        return E.process_event(t,q,c,eion,cal,M)
    end
    stop=window_config(c,horizon_ns,cal["time_step_ns"])
    keep=searchsortedlast(t,stop)
    E.check(keep>=2,"Insufficient charge samples in isolated window")
    r=E.process_event(t[1:keep],q[1:keep],c,eion,cal,M; finite_window_ns=stop)
    merge!(r,Dict("isolated_horizon_ns"=>horizon_ns,"charge_clipped_at_window"=>keep<length(t),
        "untruncated_charge_end_ns"=>last(t),"untruncated_final_charge_keV"=>last(q),
        "electronics_state"=>"reset_nominal_isolated_window","tail_truncated_possible"=>true))
    r
end
end
