# Synthetic electronics-only tests. Receipt/fixtures stay in the owned local root.
using Test, JSON, LinearAlgebra, SHA
const HERE=@__DIR__
const ROOT=dirname(HERE)
length(ARGS)==1 || error("Supply a new .local receipt directory")
const OUTPUT=abspath(ARGS[1])
startswith(OUTPUT,joinpath(ROOT,".local")*(Sys.iswindows() ? "\\" : "/")) || error("Local output required")
!ispath(OUTPUT) || error("Preserve existing test evidence")
mkpath(OUTPUT)
include(joinpath(ROOT,"simulation","readout_profiles.jl"))
include(joinpath(HERE,"saved_collection_edge.jl"))
const E=Readout; const P=ReadoutProfiles; const D=SavedCollectionEdge
BLAS.set_num_threads(1)
E.check(Threads.nthreads()==1 && BLAS.get_num_threads()==1, "Require one Julia/BLAS thread")
const ENVIRONMENT=E.environment()
E.check(VERSION==v"1.13.0", "Use existing Julia 1.13.0")
const PROFILE=JSON.parsefile(joinpath(ROOT,"simulation","native_readout_profile.json"))
const C=P.for_census(PROFILE,20)
const DT=2.0; const EION=2.95
const M=E.transition(C,DT)
cal_started=time_ns()
const CAL=P.calibration(C,EION,DT,M)
const CAL_SECONDS=(time_ns()-cal_started)/1e9
const RECEIPT=joinpath(OUTPUT,"synthetic-parity.json")
E.check(!ispath(RECEIPT), "Preserve existing synthetic receipt")
const BEFORE=(config=deepcopy(C),calibration=deepcopy(CAL),transition=copy(M))

const FIXTURES=Dict{String,Vector{Float64}}(
    "positive_single_bin"=>[0.,500.],
    "negative_single_bin"=>[0.,-500.],
    "signed_multibin"=>vcat(zeros(7),[-30.,150.,90.,530.],fill(530.,22)),
    "signed_zero_input"=>[0.,-0.,0.,-0.],
    "late_charge_after_zero_head"=>vcat(zeros(780),fill(662.,21)),
    "small_bipolar_charge"=>[0.,-2.0^-100,2.0^-101,0.])
dense=zeros(701)
for k in 2:length(dense)
    # Exact dyadic input increments, including signed withdrawal and quiet bins.
    dq=k%11==0 ? -0.125 : k%7==0 ? 0.5 : k%5==0 ? 0.0 : 1.0
    dense[k]=dense[k-1]+dq
end
FIXTURES["long_signed_multibin_sparse_retention"]=dense

# Separate compilation/warm-up from measured fixture operations.
warm_started=time_ns()
E.process_event([0.,2.],[0.,0.],C,EION,CAL,M)
D.collection_edge_trace([0.,2.],[0.,0.],C,EION,CAL,M;stop_ns=0.0,max_edge_points=1)
const WARMUP_SECONDS=(time_ns()-warm_started)/1e9
const CASE_RESULTS=Any[]
const REFUSALS=String[]
const PARITY_STARTED=time_ns()
@testset "synthetic retained-point binary64 equivalence" begin
    for name in sort!(collect(keys(FIXTURES)))
        q=FIXTURES[name]; t=collect(0:length(q)-1).*DT
        before_t=copy(t); before_q=copy(q)
        process_started=time_ns()
        original=E.process_event(t,q,C,EION,CAL,M)
        process_seconds=(time_ns()-process_started)/1e9
        natural=original["readout_end_ns"]
        stops=sort!(unique!([0.,2.,14.,80.,256.,min(last(t),2000.),min(last(t)+80.,natural),natural]))
        checks=Any[]
        for stop in stops
            count=Int(stop/DT)+1
            started=time_ns()
            edge=D.collection_edge_trace(t,q,C,EION,CAL,M;stop_ns=stop,max_edge_points=count)
            elapsed=(time_ns()-started)/1e9
            comparison=D.retained_preamp_parity(edge,original["trace"])
            @test comparison["passed"]
            @test edge["captured_sample_count"]==count
            @test length(edge["preamp_V"])==count
            @test edge["captured_stop_ns"]==stop
            @test edge["natural_readout_end_ns"]==natural
            @test edge["time_ns"]==collect(0:count-1).*DT
            @test reinterpret(UInt64,edge["preamp_V"][1])==reinterpret(UInt64,0.)
            if stop>=2. && name=="positive_single_bin"
                @test edge["preamp_V"][2]<0
            elseif stop>=2. && name=="negative_single_bin"
                @test edge["preamp_V"][2]>0
            elseif stop<=256. && name=="late_charge_after_zero_head"
                @test all(iszero,edge["preamp_V"])
            end
            push!(checks,merge(comparison,Dict("stop_ns"=>stop,"dense_samples"=>count,"seconds"=>elapsed)))
        end
        @test D.exact_value(t,before_t) && D.exact_value(q,before_q)
        @test D.exact_value(C,BEFORE.config) && D.exact_value(CAL,BEFORE.calibration) && D.exact_value(M,BEFORE.transition)
        # Prefix output must equal the longer replay at every binary64 sample.
        full=D.collection_edge_trace(t,q,C,EION,CAL,M;stop_ns=natural,max_edge_points=Int(natural/DT)+1)
        short=D.collection_edge_trace(t,q,C,EION,CAL,M;stop_ns=80.,max_edge_points=41)
        @test D.exact_value(short["preamp_V"],full["preamp_V"][1:41])
        push!(CASE_RESULTS,Dict("name"=>name,"time_ns"=>t,"signed_charge_keV"=>q,
            "charge_binary64_sha256"=>bytes2hex(sha256(reinterpret(UInt8,q))),
            "input_samples"=>length(q),"original_analog_samples"=>original["original_sample_count"],
            "retained_original_samples"=>length(original["trace"]["time_ns"]),
            "original_process_seconds"=>process_seconds,"checks"=>checks,
            "peak_V"=>original["peak_V"],"adc_code"=>original["adc_code"],
            "accepted"=>original["accepted"],"reconstructed_energy_keV"=>original["reconstructed_energy_keV"]))
    end
end
const PARITY_SECONDS=(time_ns()-PARITY_STARTED)/1e9

function refused(name,action)
    @test_throws ArgumentError action()
    push!(REFUSALS,name)
end
@testset "fail-closed input/display/calibration checks" begin
    t=[0.,2.,4.]; q=[0.,-20.,500.]
    edge(;stop=4.,limit=3,tt=t,qq=q,c=C,eion=EION,cal=CAL,mat=M)=
        D.collection_edge_trace(tt,qq,c,eion,cal,mat;stop_ns=stop,max_edge_points=limit)
    for stop in (-2.,1.,NaN,Inf,10006.)
        refused("stop_"*string(stop),()->edge(stop=stop))
    end
    # Reject a near-on-grid request as well; no tolerance-based crop or rounding.
    refused("near_grid_stop",()->edge(stop=nextfloat(4.)))
    for limit in (0,true,2,10002,3.0)
        refused("point_bound_"*string(limit),()->edge(limit=limit))
    end
    refused("wave_sample_count",()->edge(qq=[0.,1.]))
    refused("wave_nonzero_initial",()->edge(qq=[1.,2.,3.]))
    refused("wave_nan",()->edge(qq=[0.,NaN,3.]))
    refused("wave_inf",()->edge(qq=[0.,Inf,3.]))
    refused("wave_reversed",()->edge(tt=[0.,4.,2.]))
    refused("wave_nonuniform",()->edge(tt=[0.,2.,4.5]))
    refused("wave_non_binary64",()->edge(qq=[0,2,3]))
    refused("ionisation_energy",()->edge(eion=3.0))
    for key in ("volts_per_keV","peak_V","peak_time_ns","charge_C","energy_keV","adc_lsb_V")
        bad=deepcopy(CAL); bad[key]=nextfloat(Float64(bad[key]))
        refused("changed_calibration_"*key,()->edge(cal=bad))
    end
    bad=deepcopy(CAL); bad["time_step_ns"]=1.0
    refused("changed_calibration_grid",()->edge(cal=bad))
    bad=deepcopy(CAL); bad["invented"]=0.0
    refused("extra_calibration_key",()->edge(cal=bad))
    bad=copy(M); bad[1,1]=nextfloat(bad[1,1])
    refused("changed_transition",()->edge(mat=bad))
    bad=copy(M); bad[5,1]=-0.0
    refused("transition_signed_zero_change",()->edge(mat=bad))
    refused("transition_shape",()->edge(mat=zeros(4,4)))
    # Rehashed config mutants still fail semantic/typed equality; hashes alone
    # cannot authorize altering gain, trace density, threshold or census.
    mutant_dir=joinpath(OUTPUT,"rehashed-config-fixtures")
    E.check(!ispath(mutant_dir), "Preserve config-mutant evidence")
    mkdir(mutant_dir)
    for (key,value) in (("trace_max_points",599),("gain",21.0),("feedback_capacitance_pF",0.7),
            ("feedback_tau_us",40.0),("pole_zero_tau_us",40.0),("shaping_tau_us",0.7),
            ("adc_bits",12),("adc_full_scale_V",8.0),("threshold_V",0.002),
            ("peak_policy",E.LEGACY_PEAK_POLICY),("expected_primary_count",3),
            ("tail_shaping_constants",21.0),("max_window_ns",999998.0),
            ("max_samples_per_event",499999),("require_all_events",false))
        bad=deepcopy(C); bad[key]=value
        path=joinpath(mutant_dir,key*".json"); E.save(path,bad)
        # The newly calculated hash is deliberately accepted as file integrity;
        # the independent frozen-profile check must still reject its contents.
        hash=E.hashfile(path); loaded=E.readjson(path)
        @test hash==E.hashfile(path)
        refused("rehashed_config_"*key,()->edge(c=loaded))
    end
end

@testset "signed-zero comparator and retained-point corruption" begin
    @test !D.exact_value(0.,-0.)
    @test D.exact_value(-0.,-0.)
    @test !D.exact_value(1.,nextfloat(1.))
    q=[0.,-10.,500.]; t=[0.,2.,4.]
    original=E.process_event(t,q,C,EION,CAL,M)
    edge=D.collection_edge_trace(t,q,C,EION,CAL,M;stop_ns=80.,max_edge_points=41)
    bad=deepcopy(original["trace"]); bad["preamp_V"][1]=-0.0
    refused("retained_positive_zero_to_negative_zero",()->D.retained_preamp_parity(edge,bad))
    bad=deepcopy(original["trace"]); bad["preamp_V"][2]=nextfloat(bad["preamp_V"][2])
    refused("retained_preamp_one_ulp",()->D.retained_preamp_parity(edge,bad))
    bad=deepcopy(original["trace"]); bad["time_ns"][2]+=1.
    refused("retained_off_grid",()->D.retained_preamp_parity(edge,bad))
    # Explicit synthetic retained-negative-zero fixture verifies that the parity
    # hook matches negative-zero bits; it is not claimed as detector output.
    signed=deepcopy(edge); signed["preamp_V"][1]=-0.0
    trace=Dict("time_ns"=>[0.],"preamp_V"=>[-0.])
    checked=D.retained_preamp_parity(signed,trace)
    @test checked["matched_negative_zero_points"]==1
    @test checked["passed"]
end

E.check(!any(p.name=="SolidStateDetectors" for p in keys(Base.loaded_modules)), "SSD unexpectedly loaded")
report=Dict("kind"=>"m14b_private_synthetic_display_parity_v1","status"=>"passed",
    "environment"=>ENVIRONMENT,"julia_threads"=>Threads.nthreads(),"blas_threads"=>BLAS.get_num_threads(),
    "blas_configuration"=>string(BLAS.get_config()),"ssd_loaded"=>false,
    "candidate_sha256"=>E.hashfile(joinpath(HERE,"saved_collection_edge.jl")),
    "test_sha256"=>E.hashfile(@__FILE__),"readout_sha256"=>E.hashfile(joinpath(ROOT,"simulation","readout.jl")),
    "julia_executable_sha256"=>E.hashfile(joinpath(Sys.BINDIR,Base.julia_exename())),
    "time_step_ns"=>DT,"ionisation_energy_eV"=>EION,"random_seed"=>nothing,
    "randomness"=>"none; deterministic synthetic injections only",
    "calibration_seconds"=>CAL_SECONDS,"warmup_seconds"=>WARMUP_SECONDS,"fixture_parity_seconds"=>PARITY_SECONDS,
    "cases"=>CASE_RESULTS,"refusals"=>REFUSALS,
    "deferred"=>["old6 saved-charge replay/retained-original-point parity","all40 completion",
        "source/hash-bound derivative writer","UI integration/desktop/mobile/offline checks",
        "two scoped independent implementation reviews plus new strict reviewer"],
    "scope"=>"synthetic electronics algorithm equivalence only; no field, native, radiation, experimental or Li CCE validation")
E.save(RECEIPT,report)
println(JSON.json(Dict("status"=>"passed","synthetic_cases"=>length(CASE_RESULTS),
    "prefix_checks"=>sum(length(r["checks"]) for r in CASE_RESULTS),"refusals"=>length(REFUSALS),
    "calibration_seconds"=>CAL_SECONDS,"warmup_seconds"=>WARMUP_SECONDS,"fixture_parity_seconds"=>PARITY_SECONDS)))
