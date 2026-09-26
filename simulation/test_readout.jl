# Run: julia --startup-file=no --project=simulation simulation/test_readout.jl
# No SSD import, field solve, measured data, or external process. Fixtures are
# temporary below .local and removed by mktempdir; existing evidence is untouched.
using Test, JSON, LinearAlgebra
include("readout.jl")
const R=Readout
const DEMO=joinpath(@__DIR__,"readout_demo.json")
const TEST_RECEIPT=Dict{String,Any}("environment"=>R.environment(),
    "source_sha256"=>Dict(f=>R.hashfile(joinpath(@__DIR__,f)) for f in ("readout.jl","test_readout.jl","readout_demo.json")))
const C=R.config(DEMO)
const EION=2.95 # Synthetic test fixture only; production reads replay metadata.
const TS=C["shaping_tau_us"]*1000
const TF=C["feedback_tau_us"]*1000
const CF=C["feedback_capacitance_pF"]*1e-12
const G=C["gain"]
const Q500=500e3/EION*1.602176634e-19
impulse(t,q=Q500)=t<0 ? 0. : G*q/CF*(t/TS)^2*exp(-t/TS)/2
gamma_cdf(t)=t<=0 ? 0. : 1-exp(-t/TS)*(1+t/TS+(t/TS)^2/2)
rectangle(t,duration,q=Q500)=G*q/CF*TS/duration*(gamma_cdf(t)-gamma_cdf(t-duration))

# Independently coded ODE and RK4: does not call transition or use its matrix.
function rhs(x)
    pre,z,r1,r2=x; u=pre+(TS/TF-1)*z
    [-pre/TF,(pre-z)/TS,(u-r1)/TS,(r1-r2)/TS]
end
function rk4_delta(dt, stop)
    x=[-Q500/CF,0.,0.,0.]; peak=0.; time=0.
    for k in 1:round(Int,stop/dt)
        a=rhs(x); b=rhs(x+dt/2*a); c=rhs(x+dt/2*b); d=rhs(x+dt*c)
        x += dt/6*(a+2b+2c+d)
        v=-G*x[4]; if v>peak; peak=v; time=k*dt; end
    end
    peak,time,x
end

@testset "delta CSA, matched shape and independent calibration" begin
    for dt in (1.,2.,4.)
        M=R.transition(C,dt); x=[-Q500/CF,0.,0.,0.,0.]
        values=Float64[]
        for k in 1:round(Int,6000/dt)
            x=M*x; t=k*dt
            @test isapprox(x[1],-Q500/CF*exp(-t/TF);rtol=1e-9,atol=1e-13)
            @test isapprox(-G*x[4],impulse(t);rtol=1e-9,atol=1e-12)
            push!(values,-G*x[4])
        end
        @test argmax(values)*dt == 2TS
        @test maximum(values) ≈ G*Q500/CF*2exp(-2) rtol=1e-9
        cal=R.calibration(C,EION,dt,M)
        @test cal["peak_V"] ≈ impulse(2TS) rtol=1e-9
        @test cal["peak_time_ns"]==2TS
        @test cal["charge_C"]==Q500
    end
    peak,t,_=rk4_delta(1.,6000.)
    @test peak ≈ impulse(2TS) rtol=1e-10
    @test t==2TS
    # Fixed calibration, independently varied charge and Eion; no truth refit.
    cal=R.calibration(C,EION,2.)
    @test R.calibration(C,3.1,2.)["volts_per_keV"]/cal["volts_per_keV"] ≈ EION/3.1
end

@testset "two exact delayed impulses on the original primary clock" begin
    # Impulses deliberately fall between the 2 ns observation samples. Apply
    # physical state jumps, never shift the event origin or recalibrate gain.
    arrivals=[3.5,1307.25]; amounts=[Q500,.4Q500]; j=1; previous=0.; x=zeros(5)
    matrices=Dict{Float64,Matrix{Float64}}()
    step(h)=get!(() -> R.transition(C,h),matrices,h)
    for t in 0.:2.:4000.
        while j<=length(arrivals) && arrivals[j]<=t
            x=step(arrivals[j]-previous)*x
            x[1]-=amounts[j]/CF; previous=arrivals[j]; j+=1
        end
        if t>previous; x=step(t-previous)*x; end
        previous=t
        @test -G*x[4] ≈ sum(impulse(t-a,q) for (a,q) in zip(arrivals,amounts)) rtol=1e-9 atol=1e-12
        @test x[1] ≈ sum(t<a ? 0. : -q/CF*exp(-(t-a)/TF) for (a,q) in zip(arrivals,amounts)) rtol=1e-9 atol=1e-12
    end
end

function waveform(q;dt=2.,cfg=C)
    t=collect(0.:dt:(length(q)-1)*dt)
    R.process_event(t,q,cfg,EION,R.calibration(cfg,EION,dt),R.transition(cfg,dt))
end
@testset "rectangle, causality, signed linearity, ballistic deficit" begin
    dt=2.; duration=1000.; q=collect(range(0.,500.;length=501))
    a=waveform(q); tr=a["trace"]
    @test maximum(abs.(tr["shaped_V"].-rectangle.(tr["time_ns"],duration))) < 1e-9*impulse(2TS)+1e-12
    @test a["peak_V"] < impulse(2TS)
    @test a["analog_energy_keV"] < 500
    @test a["final_charge_C"] ≈ Q500
    complete=waveform(collect(range(0.,500.;length=51));dt=20.)
    @test length(complete["trace"]["time_ns"])==complete["original_sample_count"]
    @test sum(complete["trace"]["current_nA"])*20e-18 ≈ Q500 rtol=1e-12
    # CSA rectangle integral, independent of the matrix construction.
    for (t,v) in zip(tr["time_ns"],tr["preamp_V"])
        expected=-Q500/duration/CF*TF*(exp(-max(0.,t-duration)/TF)-exp(-t/TF))
        @test v ≈ expected rtol=1e-9 atol=1e-12
    end
    b=waveform(2q); neg=waveform(-q)
    @test b["peak_V"] ≈ 2a["peak_V"] rtol=1e-12
    @test b["peak_time_ns"]==a["peak_time_ns"]
    @test neg["negative_input"] && !neg["accepted"] && neg["rejection_reason"]=="negative_input"
    @test neg["final_charge_C"] ≈ -Q500
    @test neg["reconstructed_energy_keV"]===nothing
    # Two separated charge packets remain one primary-relative event. The 2.5 ns
    # delay is represented exactly on this 0.5 ns grid, not reset as a trigger.
    dt=.5; times=collect(0.:dt:1603.)
    q=500 .* clamp.((times.-2.5)./20.,0.,1.) .+ 200 .* clamp.((times.-1502.5)./40.,0.,1.)
    delayed=waveform(q;dt=dt); tr=delayed["trace"]
    expected=[rectangle(t-2.5,20.)+rectangle(t-1502.5,40.,.4Q500) for t in tr["time_ns"]]
    @test maximum(abs.(tr["shaped_V"].-expected)) < 1e-9*impulse(2TS)+1e-12
    @test all(tr["shaped_V"][tr["time_ns"].<=2.5].==0)
    @test delayed["final_charge_C"] ≈ 1.4Q500
    @test delayed["input_sample_count"]==length(times)
    @test length(tr["time_ns"])<=600
    @test first(tr["time_ns"])==0 && last(tr["time_ns"])==delayed["readout_end_ns"]
    @test delayed["peak_time_ns"] in tr["time_ns"]
    @test maximum(tr["shaped_V"])==delayed["peak_V"]
    # Same continuous 1000 ns rectangle, peak sampled at 1/2/4 ns.
    peaks=[waveform(collect(range(0.,500.;length=round(Int,1000/dt)+1));dt=dt)["peak_V"] for dt in (1.,2.,4.)]
    @test maximum(peaks)-minimum(peaks) < C["adc_full_scale_V"]/2^14/4
    zero=waveform([0.,0.])
    @test zero["adc_code"]==0 && !zero["accepted"] && zero["reconstructed_energy_keV"]===nothing
    @test zero["rejection_reason"]=="below_threshold"
    @test all(iszero,zero["trace"]["shaped_V"])
end

@testset "trace support, original current bins and conservative signed policy" begin
    one=waveform([0.,500.]); tr=one["trace"]
    @test 2. in tr["time_ns"] && one["charge_end_ns"]==2.
    j=findfirst(==(2.),tr["time_ns"])
    @test tr["current_nA"][j] ≈ Q500/2*1e18
    @test tr["current_bin_start_ns"][j]==0. && tr["current_bin_end_ns"][j]==2.
    @test tr["current_bin_start_ns"][1]==tr["current_bin_end_ns"][1]==0.
    @test one["current_balance"]["passed"] && one["trace_preserves_all_current_runs"]
    @test one["current_balance"]["integrated_current_C"] ≈ Q500
    @test one["tail_window_ns"]==10_000. && !one["window_limited"]
    # Every original sample remains for short inputs, despite the much longer tail.
    short=waveform(vcat(zeros(100),fill(500.,200)))
    @test all(t->t in short["trace"]["time_ns"],0.:2.:598.)
    # Sparse narrow packets, including unequal pulses within one display bucket.
    # Nothing resets the primary clock, and no display-bin averaging is allowed.
    for bins in ((2,1900),(805,809))
        q=zeros(2000); q[bins[1]:end].+=300.; q[bins[2]:end].+=200.
        r=waveform(q); tr=r["trace"]
        @test r["trace_preserves_all_current_runs"] && length(tr["time_ns"])<=600
        @test r["charge_end_ns"] in tr["time_ns"]
        @test r["peak_time_ns"] in tr["time_ns"]
        @test tr["shaped_V"][findfirst(==(r["peak_time_ns"]),tr["time_ns"])]==r["peak_V"]
        for (k,energy) in zip(bins,(300.,200.))
            j=findfirst(==((k-1)*2.),tr["time_ns"])
            @test j!==nothing
            @test tr["current_nA"][j] ≈ R.charge_C(energy,EION)/2*1e18
            @test tr["current_bin_start_ns"][j]==(k-2)*2.
            @test tr["current_bin_end_ns"][j]==(k-1)*2.
            @test (k-2)*2. in tr["time_ns"] && k*2. in tr["time_ns"]
        end
        @test r["current_balance"]["integrated_current_C"] ≈ Q500
        @test waveform(q)["trace"]==tr # deterministic selection
    end
    # Full-grid sign reversal is observable on this <=600-point test waveform.
    q=collect(range(0.,500.;length=51)); pos=waveform(q;dt=20.); neg=waveform(-q;dt=20.)
    @test pos["trace"]["time_ns"]==neg["trace"]["time_ns"]
    for key in ("induced_charge_fC","current_nA","preamp_V","shaped_V")
        @test neg["trace"][key] ≈ -pos["trace"][key] rtol=1e-12 atol=1e-14
    end
    tiny=waveform([0.,-1e-100,500.])
    @test tiny["peak_V"]>C["threshold_V"] && tiny["negative_input"]
    @test !tiny["accepted"] && tiny["rejection_reason"]=="negative_input"
    @test tiny["reconstructed_energy_keV"]===nothing
    @test minimum(tiny["trace"]["induced_charge_fC"])<0
    # A finite display budget cannot retain thousands of separate packets.
    # Its deterministic envelope must still retain global extrema and anchors.
    current=zeros(14_000); current[2:2:10_000].=1.
    current[4320]=13.; current[6402]=-7.; q=cumsum(current[1:10_000])
    idx,allruns=R.trace_indices(q,current,14_000,11_000,600)
    @test !allruns && length(idx)<=600 && issorted(idx) && length(unique(idx))==length(idx)
    @test all(k->k in idx,(1,4320,6402,10_000,11_000,14_000))
    @test R.trace_indices(q,current,14_000,11_000,600)==(idx,allruns)
end

@testset "10 us to 20 us tail peak gate and actual boundary flag" begin
    extended=merge(C,Dict("tail_shaping_constants"=>40.))
    for q in ([0.,500.],collect(range(0.,500.;length=501)),vcat(zeros(50),fill(300.,100),fill(500.,100)))
        a=waveform(q); b=waveform(q;cfg=extended)
        @test a["tail_window_ns"]==10_000. && b["tail_window_ns"]==20_000.
        @test abs(a["peak_V"]-b["peak_V"]) < C["adc_full_scale_V"]/2^14/4
        @test !a["window_limited"] && !b["window_limited"]
    end
    # Deliberately bypass config loading only for an adversarial short-window
    # unit test: the public config still rejects tails shorter than 20 tau_s.
    short=merge(C,Dict("tail_shaping_constants"=>.1))
    boundary=waveform([0.,500.];cfg=short)
    @test boundary["window_limited"] && boundary["peak_time_ns"]==boundary["readout_end_ns"]
    @test !boundary["accepted"] && boundary["rejection_reason"]=="peak_at_window_end"
end

@testset "ADC threshold, code centres, overflow and half-LSB bound" begin
    cal=R.calibration(C,EION,2.); lsb=10/2^14
    @test !R.digitize(prevfloat(.001),C,cal)["accepted"]
    @test R.digitize(.001,C,cal)["accepted"]
    for v in (.001,lsb*2,lsb*2.5,lsb*511,1.,9.999,prevfloat(10.))
        d=R.digitize(v,C,cal)
        @test d["adc_code"]==floor(Int,v/lsb)
        @test d["accepted"]
        @test d["adc_midpoint_V"]==(d["adc_code"]+.5)*lsb
        @test abs(d["reconstructed_energy_keV"]-d["analog_energy_keV"]) <= cal["adc_half_lsb_energy_keV"]+1e-10
    end
    for v in (10.,10.1,1e100)
        d=R.digitize(v,C,cal)
        @test d["adc_code"]==16383 && d["saturated"] && !d["accepted"]
        @test d["rejection_reason"]=="saturated" && d["reconstructed_energy_keV"]===nothing
    end
    @test !R.digitize(.1,C,cal;window_limited=true)["accepted"]
    @test_throws ArgumentError R.digitize(NaN,C,cal)
end

function fixture(root)
    transport=mkdir(joinpath(root,"transport")); input=mkdir(joinpath(root,"charge"))
    hashes=Dict{String,Any}()
    for (f,k) in (("truth.lh5","source_lh5_sha256"),("geometry.gdml","geometry_sha256"),("run.mac","macro_sha256"),("prepared.json","prepared_sha256"),("run.json","run_sha256"))
        write(joinpath(transport,f),"synthetic fixture: "*f); hashes[k]=R.hashfile(joinpath(transport,f))
    end
    truth=Dict{String,Any}("schema_version"=>1,"model_id"=>"AK02",
        "model_sha256"=>R.hashfile(joinpath(R.ROOT,"models","AK02.yaml")),
        "units"=>Dict("energy"=>"keV","length"=>"mm","time"=>"ns"),"primary_count"=>3,"energy_sum_keV"=>1000.,
        "provenance"=>Dict{String,Any}(k=>hashes[k] for k in ("prepared_sha256","run_sha256")),
        "events"=>[Dict("event_id"=>i,"primary_time_ns"=>23.,"steps"=>i==1 ? [] : [Dict("energy_keV"=>500.)]) for i in 0:2])
    merge!(truth["provenance"],Dict("seed"=>12345,"versions"=>Dict("geant4"=>"11.3.2"),
        "extractor_versions"=>Dict("python"=>"3.13.15"),"lock_sha256"=>"0"^64))
    merge!(truth,Dict(k=>hashes[k] for k in ("source_lh5_sha256","geometry_sha256","macro_sha256")))
    truthfile=joinpath(transport,"events.json"); R.save(truthfile,truth)
    events=[Dict("event_id"=>i,"primary_time_ns"=>23.,"samples"=>2,"time_since_primary_end_ns"=>2.,
        "status"=>i==1 ? "zero_deposit" : i==0 ? "stopped_without_contact" : "step_limit",
        "deposited_energy_keV"=>i==1 ? 0. : 500.,"final_induced_equivalent_energy_keV"=>i==1 ? 0. : 400.,
        "steps"=>i==1 ? [] : [Dict("raw_row_index"=>i,"endpoints"=>[Dict("status"=>"stopped_without_contact","step_limit_reached"=>i==2)])]) for i in 0:2]
    report=Dict{String,Any}("status"=>"completed_with_transport_flags","model_id"=>"AK02","model_sha256"=>truth["model_sha256"],
        "input_sha256"=>R.hashfile(truthfile),"source_lh5_sha256"=>truth["source_lh5_sha256"],"source_provenance"=>truth["provenance"],
        "primary_count"=>3,"selected_primary_count"=>3,"unselected_event_ids"=>[],"events"=>events,
        "source_code_sha256"=>Dict(k=>R.hashfile(joinpath(@__DIR__,k)) for k in ("run.jl","replay.jl")),
        "environment_manifest_sha256"=>R.hashfile(joinpath(@__DIR__,"Manifest.toml")),
        "julia_version"=>string(VERSION),"ssd_version"=>"0.11.8",
        "ionisation_energy_eV"=>EION,"time_step_ns"=>2.)
    R.save(joinpath(input,"run.json"),report)
    csv="event_id,time_since_primary_ns,induced_equivalent_energy_keV\n0,0,0\n0,2,400\n1,0,0\n1,2,0\n2,0,0\n2,2,400\n"
    write(joinpath(input,"signals.csv"),csv)
    cfg=deepcopy(C); cfg["expected_primary_count"]=nothing
    configfile=joinpath(root,"config.json"); R.save(configfile,cfg)
    (;input,truthfile,configfile,report,truth,csv,cfg)
end
mktempdir(joinpath(R.ROOT,".local")) do root
    @testset "end-to-end tiny fixtures and source integrity" begin
        f=fixture(root); out=joinpath(root,"ok")
        result=R.run(f.input,f.truthfile,f.configfile,out)
        @test result["status"]=="completed"
        @test Set(readdir(out))==Set(["run.json","events.csv","spectrum.csv"])
        persisted=JSON.parsefile(joinpath(out,"run.json"))
        @test [e["event_id"] for e in persisted["events"]]==[0,1,2]
        @test persisted["summary"]["transport_flagged_count"]==2
        @test persisted["events"][2]["reconstructed_energy_keV"]===nothing
        @test persisted["events"][3]["flags"]["steps"][1]["endpoints"][1]["step_limit_reached"]
        @test persisted["provenance"]["truth_sha256"]==R.hashfile(f.truthfile)
        @test persisted["provenance"]["signals_sha256"]==R.hashfile(joinpath(f.input,"signals.csv"))
        @test persisted["provenance"]["source_lh5_sha256"]==f.truth["source_lh5_sha256"]
        @test persisted["provenance"]["transport"]["seed"]==12345
        @test persisted["provenance"]["readout_environment"]==R.environment()
        @test persisted["provenance"]["test_source_sha256"]==TEST_RECEIPT["source_sha256"]["test_readout.jl"]
        @test all(e->e["current_balance"]["passed"] && haskey(e,"window_limited"),persisted["events"])
        @test !occursin(R.ROOT,read(joinpath(out,"run.json"),String))
        before=R.hashfile(joinpath(out,"run.json"))
        @test_throws ArgumentError R.run(f.input,f.truthfile,f.configfile,out)
        @test R.hashfile(joinpath(out,"run.json"))==before
        @test_throws ArgumentError R.run(f.input,f.truthfile,f.configfile,joinpath(R.ROOT,"readout-test-forbidden"))
        @test !ispath(joinpath(R.ROOT,"readout-test-forbidden"))
        # Explicit first-N API leaves the complete unselected census.
        partial=deepcopy(f.report); partial["selected_primary_count"]=2; partial["events"]=partial["events"][1:2]; partial["unselected_event_ids"]=[2]
        R.save(joinpath(f.input,"run.json"),partial)
        write(joinpath(f.input,"signals.csv"),join(split(f.csv,'\n')[1:5],'\n')*"\n")
        cfg=deepcopy(f.cfg); cfg["require_all_events"]=false; R.save(f.configfile,cfg)
        p=R.run(f.input,f.truthfile,f.configfile,joinpath(root,"partial"))
        @test p["unselected_event_ids"]==[2] && length(p["events"])==2
        R.save(f.configfile,f.cfg); R.save(joinpath(f.input,"run.json"),f.report); write(joinpath(f.input,"signals.csv"),f.csv)
        # Every failure gets a new destination; no fixture outside root is modified.
        failures=[("nonuniform",replace(f.csv,"0,2,400"=>"0,3,400")),
            ("repeated_time",replace(f.csv,"0,2,400"=>"0,0,400")),
            ("mixed_id",replace(f.csv,"0,2,400"=>"1,2,400")),
            ("nonfinite",replace(f.csv,"0,2,400"=>"0,2,NaN")),
            ("nonzero_initial",replace(f.csv,"0,0,0"=>"0,0,1")),
            ("bad_header",replace(f.csv,"time_since_primary_ns"=>"time_us")),
            ("extra_rows",f.csv*"2,4,400\n"),
            ("endpoint_mismatch",replace(f.csv,"0,2,400"=>"0,2,399"))]
        for (name,csv) in failures
            write(joinpath(f.input,"signals.csv"),csv); dest=joinpath(root,name)
            @test_throws ArgumentError R.run(f.input,f.truthfile,f.configfile,dest)
            failure=JSON.parsefile(joinpath(dest,"run.json"))
            @test failure["status"]=="failed" && failure["failure_stage"]=="event_processing"
        end
        write(joinpath(f.input,"signals.csv"),f.csv)
        write(joinpath(f.input,"signals.csv"),replace(f.csv,"\n"=>"\r\n"))
        @test R.run(f.input,f.truthfile,f.configfile,joinpath(root,"crlf"))["status"]=="completed"
        write(joinpath(f.input,"signals.csv"),f.csv)
        for (name,mutate!) in [
            ("duplicate_ids", r->r["events"][2]["event_id"]=0),
            ("bad_hash",r->r["input_sha256"]="0"^64),
            ("bad_model",r->r["model_sha256"]="0"^64),
            ("bad_energy",r->r["events"][1]["deposited_energy_keV"]=499.),
            ("bad_status",r->r["status"]="failed"),
            ("bad_charge_source",r->r["source_code_sha256"]["replay.jl"]="0"^64),
            ("bad_charge_version",r->r["ssd_version"]="0.11.7"),
            ("bad_counts",r->r["events"][1]["samples"]=500001)]
            r=deepcopy(f.report); mutate!(r); R.save(joinpath(f.input,"run.json"),r); dest=joinpath(root,name)
            @test_throws ArgumentError R.run(f.input,f.truthfile,f.configfile,dest)
            @test JSON.parsefile(joinpath(dest,"run.json"))["failure_stage"]=="input_validation"
        end
        R.save(joinpath(f.input,"run.json"),f.report)
        raw=joinpath(dirname(f.truthfile),"truth.lh5"); original=read(raw)
        write(raw,"changed raw source")
        @test_throws ArgumentError R.run(f.input,f.truthfile,f.configfile,joinpath(root,"bad_raw_source"))
        write(raw,original)
        cfg=deepcopy(f.cfg); cfg["max_total_samples"]=6000; R.save(f.configfile,cfg)
        @test_throws ArgumentError R.run(f.input,f.truthfile,f.configfile,joinpath(root,"total_bound"))
        cfg=deepcopy(f.cfg); cfg["max_window_ns"]=100.; R.save(f.configfile,cfg)
        @test_throws ArgumentError R.run(f.input,f.truthfile,f.configfile,joinpath(root,"window_bound"))
        cfg=deepcopy(f.cfg); delete!(cfg,"pole_zero_tau_us"); cfg["feedback_tau_us"]=25.; R.save(f.configfile,cfg)
        @test R.config(f.configfile)["pole_zero_tau_us"]==25.
    end
end
@testset "test receipt bound to exact sources and pinned CPU environment" begin
    @test R.environment()==TEST_RECEIPT["environment"]
    for (f,digest) in TEST_RECEIPT["source_sha256"]
        @test R.hashfile(joinpath(@__DIR__,f))==digest
    end
end
TEST_RECEIPT["status"]="passed"
println("READOUT_TEST_RECEIPT ",JSON.json(TEST_RECEIPT))
