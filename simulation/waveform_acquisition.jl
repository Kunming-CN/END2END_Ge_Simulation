#= Additive synthetic preamp acquisition; no SSD, transport or old peak ADC run.

Reuse Readout.transition for its signed full-resolution frontend. A causal RC
acquisition pole is driven analytically by the same constant-current native bins.
ADC samples must align to that native grid. Finite native support is never padded.
CLI: julia --project=simulation waveform_acquisition.jl --request FILE --output FILE
=#
include("readout_profiles.jl")
module WaveformAcquisition
using ..Readout, ..ReadoutProfiles, JSON, SHA, LinearAlgebra
const E=Readout
const KIND="saved_waveform_acquisition_v1"
const NOISE_PREFIX="waveform-acquisition-noise-v1"
const PROFILE_KEYS=("kind","schema_version","name","sampling_rate_Hz","adc","record_window_ns","trigger","bandwidth","noise","measurement_polarity","calibration")
function profile(p)
    E.check(Set(keys(p))==Set(PROFILE_KEYS),"Unknown/missing acquisition profile field")
    E.check(p["kind"]=="synthetic_waveform_acquisition_profile_v1" && p["schema_version"]===1,"Unsupported acquisition profile")
    E.check(p["name"] isa String && occursin(r"^[A-Za-z0-9_.-]{1,80}$",p["name"]),"Invalid acquisition profile name")
    rate=p["sampling_rate_Hz"]; bw=p["bandwidth"]
    E.check(E.finite(rate) && 1e5<=rate<=1e9,"Sampling rate outside bounded example")
    E.check(Set(keys(bw))==Set(("kind","cutoff_Hz")) && bw["kind"]=="causal_single_pole_lowpass" &&
        E.finite(bw["cutoff_Hz"]) && 0<bw["cutoff_Hz"]<rate/2,"Acquisition cutoff must be below Nyquist; no ideal alias-free guarantee")
    a=p["adc"]; E.check(Set(keys(a))==Set(("bits","minimum_V","maximum_V")) && E.integer(a["bits"]) &&
        2<=a["bits"]<=24 && E.finite(a["minimum_V"]) && E.finite(a["maximum_V"]) && a["minimum_V"]<0<a["maximum_V"],"Invalid bipolar waveform ADC")
    w=p["record_window_ns"]; step=1e9/rate
    E.check(w isa Vector && length(w)==2 && all(E.finite,w) && -1e6<=w[1]<=0<w[2]<=1e6,"Invalid acquisition window")
    E.check(all(x->isapprox(x/step,round(x/step);rtol=0,atol=1e-8),w) && (w[2]-w[1])/step+1<=200000,"Window must align to bounded uniform ADC grid")
    tr=p["trigger"]; E.check(tr==Dict("kind"=>"external_group_origin","offset_ns"=>0.0,"prehistory"=>"isolated_reset_zero_before_group_origin"),"Only declared external group-origin reset trigger is supported")
    noise=p["noise"]; E.check(Set(keys(noise))==Set(("kind","rms_V","root_seed_uint64")) && noise["kind"]=="postfilter_sampled_iid_gaussian_voltage" &&
        E.finite(noise["rms_V"]) && 0<=noise["rms_V"]<=(a["maximum_V"]-a["minimum_V"])/10 &&
        noise["root_seed_uint64"] isa String && occursin(r"^(0|[1-9]\d{0,19})$",noise["root_seed_uint64"]),"Invalid sampled noise model/seed")
    parse(UInt64,noise["root_seed_uint64"])
    E.check(p["measurement_polarity"]===-1,"Preamp measurement requires fixed -1 polarity; signed samples remain unchanged")
    ca=p["calibration"]; E.check(Set(keys(ca))==Set(("kind","energy_keV")) && ca["kind"]=="independent_delta_charge_injection" &&
        E.finite(ca["energy_keV"]) && ca["energy_keV"]>0,"Invalid independent acquisition injection")
    p
end

function seed(p,pid,gid)
    text="$NOISE_PREFIX/$(p["noise"]["root_seed_uint64"])/$pid/$gid"
    string(parse(UInt64,bytes2hex(sha256(text))[1:16];base=16))
end
function normal(seed_string,index)
    digest=bytes2hex(sha256("$NOISE_PREFIX/$seed_string/$index"))
    a=parse(UInt64,digest[1:16];base=16)>>11; b=parse(UInt64,digest[17:32];base=16)>>11
    u=(Float64(a)+0.5)/9007199254740992.; v=(Float64(b)+0.5)/9007199254740992.
    sqrt(-2log(u))*cos(2pi*v)
end

# y'= (vpre-y)/tb; vpre'= -vpre/tf-u. Exact within original
# constant-current charge bins, with the same native E.transition front end.
function filter_step(p0,y0,u,tf,tb,dt)
    eb=exp(-dt/tb); ef=exp(-dt/tf); steady=-u*tf
    kernel=tf==tb ? (dt/tb)*eb : (ef-eb)/(1-tb/tf)
    y0*eb+steady*(-expm1(-dt/tb))+(p0-steady)*kernel
end
function frontend(t,q,c,eion,cutoff; initial_preamp=0.0)
    dt=t[2]-t[1]; E.validate_wave(t,q,dt,c["max_samples_per_event"])
    E.check(last(t)<=c["max_window_ns"],"Native support exceeds original frontend bound")
    M=E.transition(c,dt); tf=c["feedback_tau_us"]*1000.; tb=1e9/(2pi*cutoff)
    cf=c["feedback_capacitance_pF"]*1e-12; factor=E.charge_C(1.,eion)
    pre=zeros(length(t)); filtered=zeros(length(t)); x=zeros(5); x[1]=initial_preamp; pre[1]=initial_preamp
    for k in 2:length(t)
        u=(q[k]-q[k-1])*factor/dt/cf
        filtered[k]=filter_step(x[1],filtered[k-1],u,tf,tb,dt)
        x[5]=u; x=M*x; pre[k]=x[1]
    end
    E.check(all(isfinite,pre) && all(isfinite,filtered),"Nonfinite acquisition response")
    pre,filtered
end
function adc(v,a)
    lsb=(a["maximum_V"]-a["minimum_V"])/2^a["bits"]
    lastcode=2^a["bits"]-1
    code=v<a["minimum_V"] ? 0 : v>=a["maximum_V"] ? lastcode : clamp(floor(Int,(v-a["minimum_V"])/lsb),0,lastcode)
    code,a["minimum_V"]+(code+0.5)*lsb,v<a["minimum_V"],v>=a["maximum_V"]
end
function sampled(t,pre,filtered,p,derived_seed; noise_rms=p["noise"]["rms_V"])
    dt=t[2]-t[1]; step=1e9/p["sampling_rate_Hz"]
    E.check(isapprox(step/dt,round(step/dt);rtol=0,atol=1e-8) && step>=dt,"ADC interval must be an integer multiple of native grid")
    w=p["record_window_ns"]; stop=min(w[2],floor(last(t)/step)*step)
    times=collect(w[1]:step:stop); pv=Float64[]; fv=Float64[]; nv=Float64[]; noisy=Float64[]; codes=Int[]; centers=Float64[]
    lower=false; upper=false
    for (i,time) in enumerate(times)
        k=time<0 ? 0 : round(Int,time/dt)+1
        a=k==0 ? 0. : pre[k]; b=k==0 ? 0. : filtered[k]
        noise=noise_rms==0 ? 0. : noise_rms*normal(derived_seed,i-1); value=b+noise
        code,center,lo,hi=adc(value,p["adc"]); lower|=lo; upper|=hi
        push!(pv,a); push!(fv,b); push!(nv,noise); push!(noisy,value); push!(codes,code); push!(centers,center)
    end
    trace=Dict("time_since_origin_ns"=>times,"signed_preamp_V"=>pv,"bandwidth_limited_preamp_V"=>fv,"noise_V"=>nv,
        "noisy_voltage_V"=>noisy,"adc_code"=>codes,"adc_center_V"=>centers)
    flags=Dict("adc_lower_clipped"=>lower,"adc_upper_clipped"=>upper,"record_exceeds_native_support"=>w[2]>last(t),
        "record_truncates_native_window"=>w[2]<last(t),"pretrigger_is_assumed_reset_zero"=>w[1]<0,
        "finite_native_support"=>true,"residual_aliasing_possible"=>true)
    trace,flags
end
function calibration(c,eion,dt,p)
    energy=p["calibration"]["energy_keV"]; charge=E.charge_C(energy,eion); initial=-charge/(c["feedback_capacitance_pF"]*1e-12)
    stop=p["record_window_ns"][2]; E.check(isapprox(stop/dt,round(stop/dt);rtol=0,atol=1e-8),"Injection window must align to native grid")
    t=collect(0.:dt:stop); q=zeros(length(t)); pre,filtered=frontend(t,q,c,eion,p["bandwidth"]["cutoff_Hz"];initial_preamp=initial)
    trace,flags=sampled(t,pre,filtered,p,"0";noise_rms=0.)
    post=findall(>=(0),trace["time_since_origin_ns"]); values=-trace["bandwidth_limited_preamp_V"][post]
    peak,j=findmax(values); i=post[j]
    E.check(peak>0 && j>1 && j<length(post) && !flags["adc_lower_clipped"] && !flags["adc_upper_clipped"],"Injection calibration peak/window/range invalid")
    lsb=(p["adc"]["maximum_V"]-p["adc"]["minimum_V"])/2^p["adc"]["bits"]
    Dict("method"=>"independent delta-charge injection into reset original CSA at group origin; noiseless acquisition-filter sampled analog peak; one fixed gain per frontend",
        "energy_keV"=>energy,"charge_C"=>charge,"ionisation_energy_eV"=>eion,"volts_per_keV"=>peak/energy,"peak_V"=>peak,
        "peak_time_ns"=>trace["time_since_origin_ns"][i],"noise_rms_V"=>0.,"adc_lsb_V"=>lsb,
        "quantization_half_lsb_energy_keV"=>lsb/(2peak/energy),"hardware_calibrated"=>false)
end
function acquire(g,c,eion,p,cal)
    t=Float64.(g["time_since_origin_ns"]); q=Float64.(g["induced_equivalent_energy_keV"])
    pre,filtered=frontend(t,q,c,eion,p["bandwidth"]["cutoff_Hz"])
    derived=seed(p,g["global_initial_id"],g["group_id"]); trace,flags=sampled(t,pre,filtered,p,derived)
    post=findall(>=(0),trace["time_since_origin_ns"]); baseline=adc(0.,p["adc"])[2]
    amplitudes=baseline.-trace["adc_center_V"][post]; peak,j=findmax(amplitudes); i=post[j]
    flags["peak_at_record_boundary"]=j==1 || j==length(post)
    reasons=String.(g["source_selection_reasons"])
    for key in ("adc_lower_clipped","adc_upper_clipped","record_exceeds_native_support","record_truncates_native_window","peak_at_record_boundary")
        flags[key] && push!(reasons,key)
    end
    peak<=0 && push!(reasons,"nonpositive_acquisition_peak")
    reasons=unique(reasons); energy=peak/cal["volts_per_keV"]
    Dict("status"=>"acquired","trace"=>trace,"flags"=>flags,"selection"=>Dict("valid"=>isempty(reasons),"reasons"=>reasons),
        "acquisition_energy_keV"=>isempty(reasons) ? energy : nothing,
        "observed"=>Dict("provisional"=>!isempty(reasons),"peak_adc_excursion_V"=>peak,"peak_time_since_origin_ns"=>trace["time_since_origin_ns"][i],
            "acquisition_energy_keV"=>energy,"baseline_adc_center_V"=>baseline),
        "metadata"=>Dict("native_time_step_ns"=>t[2]-t[1],"native_window_end_ns"=>last(t),"input_sample_count"=>length(t),
            "input_final_charge_keV"=>last(q),"trigger_origin_time_ns"=>g["origin_time_ns"],"derived_noise_seed_uint64"=>derived,
            "measurement_polarity"=>-1,"calibration_id"=>g["batch_index"]))
end
function run(request)
    p=profile(request["profile"]); software=E.environment()
    E.check(Threads.nthreads()==1 && BLAS.get_num_threads()==1,"Use one child Julia/BLAS thread")
    groups=Any[]; calibrations=Any[]
    for batch in request["batches"]
        c=batch["frontend_config"]; ReadoutProfiles.validate_resolved(c,batch["original_frontend_profile"],c["expected_primary_count"])
        eion=batch["ionisation_energy_eV"]; dt=batch["native_time_step_ns"]
        cal=calibration(c,eion,dt,p)
        push!(calibrations,Dict("batch_index"=>batch["batch_index"],"frontend_config"=>c,"original_frontend_profile"=>batch["original_frontend_profile"],
            "ionisation_energy_eV"=>eion,"time_step_ns"=>dt,"calibration"=>cal))
        for g in batch["groups"]
            push!(groups,Dict("global_initial_id"=>g["global_initial_id"],"group_id"=>g["group_id"],"acquisition"=>acquire(g,c,eion,p,cal)))
        end
    end
    Dict("kind"=>KIND,"schema_version"=>1,"profile"=>p,"calibrations"=>calibrations,"groups"=>groups,
        "software"=>merge(software,Dict("julia_threads"=>Threads.nthreads(),"blas_threads"=>BLAS.get_num_threads(),
            "frontend_source_sha256"=>E.hashfile(joinpath(@__DIR__,"readout.jl")),"acquisition_source_sha256"=>E.hashfile(@__FILE__))))
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    if length(ARGS)==4 && ARGS[1]=="--request" && ARGS[3]=="--output"
        Readout.check(!ispath(ARGS[4]),"Acquisition numerical output exists; preserve it")
        result=WaveformAcquisition.run(Readout.readjson(ARGS[2])); Readout.save(ARGS[4],result)
    else
        error("Usage: waveform_acquisition.jl --request FILE --output FILE")
    end
end
