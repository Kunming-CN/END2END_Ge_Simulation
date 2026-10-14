# Bounded synthetic CSA/acquisition checks; one child Julia/BLAS thread only.
include("waveform_acquisition.jl")
using Test, LinearAlgebra
const A=WaveformAcquisition
const E=Readout
BLAS.set_num_threads(1)
@test Threads.nthreads()==1
p=A.profile(E.readjson(joinpath(@__DIR__,"../tools/waveform_acquisition_profile.json")))
original=E.readjson(joinpath(@__DIR__,"native_readout_profile.json"))
c=ReadoutProfiles.for_census(original,4)
@testset "signed native CSA equals independent analytical current response" begin
    dt=2.; t=collect(0.:dt:1000.); q=t.*0.01; eion=2.95
    pre,filt=A.frontend(t,q,c,eion,p["bandwidth"]["cutoff_Hz"])
    u=E.charge_C(.01,eion)/(c["feedback_capacitance_pF"]*1e-12)
    tf=c["feedback_tau_us"]*1000.
    expected=[-u*tf*(-expm1(-time/tf)) for time in t]
    @test isapprox(pre,expected;rtol=1e-10,atol=1e-14)
    @test minimum(pre)<0 && maximum(pre)==0
    neg,_=A.frontend(t,-q,c,eion,p["bandwidth"]["cutoff_Hz"])
    @test neg≈-pre
    @test all(isfinite,filt)
    @test_throws ArgumentError A.frontend([0.,2.,5.],[0.,1.,2.],c,eion,1e7)
end
@testset "causal pole impulse/step and finite frequency attenuation" begin
    tf=50000.; tb=1e9/(2pi*1e7); dt=2.; y=0.
    for k in 1:100
        # Constant vpre=-1 is an exact equilibrium when u=1/tf.
        y=A.filter_step(-1.,y,1/tf,tf,tb,dt)
        @test isapprox(y,-1+exp(-k*dt/tb);rtol=1e-12,atol=1e-14)
    end
    # Transfer from integrating the causal impulse exp(-t/tb)/tb.
    for f in (1e6,1e7,5e7)
        h=1/(1+2pi*im*f*tb/1e9)
        @test isapprox(abs(h),1/sqrt(1+(f/1e7)^2);rtol=1e-14)
    end
    @test isapprox(abs(1/(1+im)),1/sqrt(2);rtol=1e-14)
    @test abs(1/(1+5im))>0 # Nyquist residual is not removed.
    @test isapprox(A.filter_step(-1.,0.,0.,tb,tb,dt),-(dt/tb)*exp(-dt/tb);rtol=1e-14)
end
@testset "ADC floor centres signed clipping and uniform native support" begin
    a=Dict("bits"=>3,"minimum_V"=>-1.,"maximum_V"=>1.)
    @test A.adc(0.,a)==(4,.125,false,false)
    @test A.adc(-.5,a)==(2,-.375,false,false)
    @test A.adc(-1.,a)==(0,-.875,false,false)
    @test A.adc(-1.01,a)==(0,-.875,true,false)
    @test A.adc(1.,a)==(7,.875,false,true)
    @test A.adc(prevfloat(p["adc"]["maximum_V"]),p["adc"])[1]==2^p["adc"]["bits"]-1
    @test !A.adc(prevfloat(p["adc"]["maximum_V"]),p["adc"])[4]
    t=collect(0.:2.:1000.); q=zeros(length(t)); q[2:end].=10.
    pre,filt=A.frontend(t,q,c,2.95,1e7)
    small=deepcopy(p);small["record_window_ns"]=[-100.,1000.]
    trace,flags=A.sampled(t,pre,filt,small,"7")
    @test trace["time_since_origin_ns"]==collect(-100.:10.:1000.)
    @test trace["signed_preamp_V"][1:10]==zeros(10)
    @test !flags["record_exceeds_native_support"] && !flags["record_truncates_native_window"]
    long=deepcopy(small);long["record_window_ns"][2]=1100.
    shorter,fl=A.sampled(t,pre,filt,long,"7")
    @test last(shorter["time_since_origin_ns"])==1000. && fl["record_exceeds_native_support"]
    bad=deepcopy(small);bad["sampling_rate_Hz"]=1e9/3
    @test_throws ArgumentError A.sampled(t,pre,filt,bad,"7")
end
@testset "fixed independent pulser and noise counter independence" begin
    cal=A.calibration(c,2.95,2.,p)
    @test 0<cal["peak_V"]<.1
    @test 0<cal["peak_time_ns"]<p["record_window_ns"][2]
    double=deepcopy(p); double["calibration"]["energy_keV"]=1000.
    cal2=A.calibration(c,2.95,2.,double)
    @test isapprox(cal2["volts_per_keV"],cal["volts_per_keV"];rtol=1e-12)
    lower=deepcopy(p); lower["calibration"]["energy_keV"]=100.
    @test isapprox(A.calibration(c,2.95,2.,lower)["volts_per_keV"],cal["volts_per_keV"];rtol=1e-12)
    @test A.seed(p,188,0)==A.seed(p,188,0)
    @test A.seed(p,188,0)!=A.seed(p,203,0)
    @test A.seed(p,188,0)!=A.seed(p,188,1)
    numbers=[A.normal(A.seed(p,188,0),i) for i in 0:4095]
    @test abs(sum(numbers)/length(numbers))<.05
    @test .9<sum(abs2,numbers)/length(numbers)<1.1
    @test A.normal(A.seed(p,188,0),10)==numbers[11]
    # No loop-order/counter mutation can alter an original sample.
    @test [A.normal(A.seed(p,188,0),i) for i in (9,0,10)]==numbers[[10,1,11]]
end
println("WAVEFORM_ACQUISITION_SYNTHETIC_PASS")
