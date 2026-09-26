using Test, JSON
include("readout_profiles.jl")
const P=ReadoutProfiles; const E=Readout
const PROFILE=JSON.parsefile(joinpath(@__DIR__,"native_readout_profile.json"))
@testset "Additive profile and legacy contract" begin
    legacy=E.config(joinpath(@__DIR__,"readout_demo.json")); c=P.validate(PROFILE)
    @test legacy["schema_version"]==1 && c["schema_version"]==2
    @test legacy["adc_bits"]==c["adc_bits"]==14
    @test c["peak_policy"]==E.SIGNED_PEAK_POLICY
    p=deepcopy(PROFILE); p["settings"]["adc_bits"]=12; p["settings"]["adc_full_scale_V"]=4.0
    p["settings"]["feedback_capacitance_pF"]=1.0; p["settings"]["feedback_tau_us"]=35.
    p["settings"]["pole_zero_tau_us"]=30.; p["settings"]["shaping_tau_us"]=0.8; p["settings"]["gain"]=10.
    c=P.validate(p); M=E.transition(c,2.); cal=P.calibration(c,2.95,2.,M)
    @test cal["adc_lsb_V"]==4/4096
    @test occursin("4.0 V",cal["adc_convention"]) && occursin("12-bit",cal["adc_convention"])
    oldcal=E.calibration(legacy,2.95,2.)
    @test oldcal["adc_convention"]=="floor(V/LSB); reconstruct (code+0.5)*LSB; threshold inclusive; saturation at V>=10 V"
    for (key,value) in (("adc_bits",true),("adc_bits",1),("adc_bits",25),("adc_bits",14.0),
        ("adc_full_scale_V",Inf),("threshold_V",0),("threshold_V",4.),("gain",NaN),
        ("feedback_tau_us",-1.),("feedback_capacitance_pF",0.),("pole_zero_tau_us",0.),
        ("shaping_tau_us",false),("peak_policy","rectify"),("peak_gate_start_ns",0.))
        bad=deepcopy(p); bad["settings"][key]=value
        @test_throws ArgumentError P.validate(bad)
    end
    bad=deepcopy(p); bad["settings"]["unknown"]=1; @test_throws ArgumentError P.validate(bad)
    bad=deepcopy(p); delete!(bad["settings"],"pole_zero_tau_us"); @test_throws ArgumentError P.validate(bad)
    bad=deepcopy(p); bad["schema_version"]=1; @test_throws ArgumentError P.validate(bad)
    # Rehashed custom legacy ADC remains forbidden by the legacy loader.
    mktempdir(joinpath(dirname(@__DIR__),".local")) do dir
        path=joinpath(dir,"legacy.json"); E.save(path,merge(legacy,Dict("adc_bits"=>12)))
        @test_throws ArgumentError E.config(path)
        resolved=P.for_census(p,20); @test P.validate_resolved(resolved,p,20)===nothing
        E.save(path,resolved); original=E.hashfile(path)
        resolved["gain"]+=1; E.save(path,resolved)
        @test E.hashfile(path)!=original # even if this new hash is deliberately accepted
        @test_throws ArgumentError P.validate_resolved(JSON.parsefile(path),p,20)
        @test_throws ArgumentError P.for_census(p,true)
    end
end
@testset "Separate calibration, signed/zero/saturated/delayed and gate edges" begin
    c=P.validate(PROFILE); M=E.transition(c,2.); cal=P.calibration(c,2.95,2.,M); before=deepcopy(cal)
    zero=P.process([0.,2.],[0.,0.],c,2.95,cal,M)
    @test !zero["accepted"] && zero["below_threshold"] && zero["reconstructed_energy_keV"]===nothing
    @test zero["preamp_peak_charge_equivalent_keV"]==0
    signed=P.process([0.,2.,4.],[0.,-1.,500.],c,2.95,cal,M)
    @test signed["negative_input"] && signed["accepted"] && signed["current_balance"]["passed"]
    saturated=P.process([0.,2.],[0.,1e6],c,2.95,cal,M)
    @test saturated["saturated"] && !saturated["accepted"] && saturated["analog_above_adc_range"]
    low=P.process([0.,2.],[0.,1e-9],c,2.95,cal,M)
    @test low["below_threshold"] && !low["accepted"]
    # Calibration depends only on independent injection and electronics, never truth/ADC/gate.
    c2=deepcopy(c); c2["calibration_energy_keV"]=250.
    @test P.calibration(c2,2.95,2.,M)["volts_per_keV"]≈cal["volts_per_keV"]
    for start in (1.,2.)
        gate=merge(c,Dict("peak_gate_start_ns"=>start,"peak_gate_end_ns"=>2000.))
        r=P.process([0.,2.],[0.,500.],gate,2.95,cal,M)
        @test r["input_activity_outside_peak_gate"] && r["current_balance"]["passed"]
        @test P.calibration(gate,2.95,2.,M)==cal
    end
    gate=merge(c,Dict("peak_gate_start_ns"=>0.,"peak_gate_end_ns"=>100.))
    boundary=P.process([0.,2.],[0.,500.],gate,2.95,cal,M)
    @test boundary["gate_limited"] && !boundary["accepted"]
    gate=merge(c,Dict("peak_gate_start_ns"=>2000.,"peak_gate_end_ns"=>3000.))
    boundary=P.process([0.,2.],[0.,500.],gate,2.95,cal,M)
    @test boundary["gate_limited"] && boundary["peak_time_ns"]==2000.
    delayed=P.process([0.,2.,4.],[0.,0.,500.],c,2.95,cal,M;horizon_ns=4.)
    @test delayed["charge_clipped_at_window"] && delayed["readout_end_ns"]==2.
    @test !delayed["accepted"] && delayed["untruncated_final_charge_keV"]==500.
    @test delayed["tail_truncated_possible"] && delayed["electronics_state"]=="reset_nominal_isolated_window"
    longt=collect(0.:2.:4000.); longq=collect(range(0.,500.;length=length(longt)))
    clipped=P.process(longt,longq,c,2.95,cal,M;horizon_ns=2000.)
    @test clipped["readout_end_ns"]==1998. && length(clipped["trace"]["time_ns"])<=600
    @test last(clipped["trace"]["time_ns"])==1998. && clipped["charge_clipped_at_window"]
    @test P.window_config(c,100000.,2.)==99998.
    @test P.window_config(c,100001.,2.)==100000.
    @test_throws ArgumentError P.window_config(c,Inf,2.)
    @test_throws ArgumentError P.process([0.,2.],[0.,500.],gate,2.95,cal,M;horizon_ns=2000.)
    @test cal==before
    # Absent finite-window keyword is identical for schema1; new diagnostics never leak in.
    legacy=E.config(joinpath(@__DIR__,"readout_demo.json")); lc=E.calibration(legacy,2.95,2.)
    a=E.process_event([0.,2.],[0.,500.],legacy,2.95,lc,E.transition(legacy,2.))
    b=E.process_event([0.,2.],[0.,500.],legacy,2.95,lc,E.transition(legacy,2.);finite_window_ns=nothing)
    @test a==b && !haskey(a,"preamp_min_V")
end
