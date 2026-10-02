using Test, JSON
include("ring_polarity.jl")
const K=RingPolarity; const E=Readout; const P=ReadoutProfiles
const PROFILE=JSON.parsefile(joinpath(@__DIR__,"native_readout_profile.json"))
const C=P.for_census(PROFILE,2); const DT=2.; const EION=2.95; const M=E.transition(C,DT)

@testset "Negative independent injection, fixed linear wiring, unchanged transfer" begin
    check=K.negative_calibration(C,EION,DT,M); cal=check.calibration
    @test check.injection["raw_delta_charge_C"]<0<check.injection["electronics_input_delta_charge_C"]
    @test check.injection["electronics_input_delta_charge_C"] == -check.injection["raw_delta_charge_C"]
    @test check.injection["input_is_independent_of_event_truth"] === true
    @test check.injection["energy_keV"]==500 && cal["wiring_factor"]==-1
    @test maximum(check.injection["shaped_V"])==cal["peak_V"]>0
    @test minimum(check.injection["preamp_V"])<0
    # Independent negative injection after wiring agrees with the existing transfer's positive delta.
    old=P.calibration(C,EION,DT,M)
    for key in ("peak_V","peak_time_ns","volts_per_keV","adc_lsb_V","adc_half_lsb_energy_keV")
        @test cal[key]==old[key]
    end
    @test K.wired_charge([0.,-1.,2.,-3.])==[0.,1.,-2.,3.]
    @test K.wired_charge([0.,-1.])+K.wired_charge([0.,2.])==K.wired_charge([0.,1.])
    @test K.wired_charge([0.,3.].*[0.0,2.0])==2 .* K.wired_charge([0.,3.])
    @test_throws ArgumentError K.wired_charge([0.,NaN])
    @test_throws ArgumentError K.wired_charge([0.,-1.],"GeRC02")
    bad=deepcopy(C);bad["calibration_energy_keV"]=250.
    @test_throws ArgumentError K.negative_calibration(bad,EION,DT,M)
    t=[0.,2.,4.];q=[0.,-250.,-500.]; before=copy(q); cb=deepcopy(cal)
    original=P.process(t,q,C,EION,old,M;horizon_ns=100000.)
    corrected=K.process(t,q,C,EION,cal,M;horizon_ns=100000.)
    direct=P.process(t,-q,C,EION,cal,M;horizon_ns=100000.)
    @test q==before && cal==cb
    @test !original["accepted"] && original["reconstructed_energy_keV"]===nothing
    @test corrected["accepted"] && corrected["current_balance"]["passed"]
    @test corrected["raw_native_any_negative_charge"] && corrected["raw_native_final_charge_keV"]==-500.
    for key in ("trace","adc_code","reconstructed_energy_keV","current_balance","peak_V","isolated_horizon_ns")
        @test corrected[key]==direct[key]
    end
    @test corrected["trace"]["current_nA"][2]>0
    # Existing positive Ge processing is still the original function/config/calibration.
    @test P.process(t,-q,C,EION,old,M;horizon_ns=100000.)["peak_V"]==corrected["peak_V"]
    zero=K.process([0.,2.],[0.,0.],C,EION,cal,M;horizon_ns=100000.)
    @test zero["below_threshold"] && zero["reconstructed_energy_keV"]===nothing && zero["adc_code"]==0
    @test !K.process([0.,2.],[0.,500.],C,EION,cal,M;horizon_ns=100000.)["accepted"] # fixed wiring, no sign shopping
    @test K.process([0.,2.],[0.,-1e6],C,EION,cal,M;horizon_ns=100000.)["saturated"]
    @test K.process([0.,2.],[0.,-1e-9],C,EION,cal,M;horizon_ns=100000.)["below_threshold"]
end

# Deliberately rehashed saved-only fixtures exercise semantics separately from byte authority.
function fixture(dir;signal="\"0\",\"0\",\"0\",\"0.0\",\"0.0\"\n\"0\",\"0\",\"0\",\"2.0\",\"-250.0\"\n\"0\",\"0\",\"0\",\"4.0\",\"-500.0\"\n")
    input=joinpath(dir,"response");mkdir(input)
    decay=Dict("record_kind"=>"decay","event_id"=>0,"global_decay_id"=>0,"group_id"=>nothing,
        "zero_deposit"=>false,"deposited_energy_keV"=>550.,"pulse_count"=>1)
    zero=merge(decay,Dict("event_id"=>1,"global_decay_id"=>1,"zero_deposit"=>true,"deposited_energy_keV"=>0.,"pulse_count"=>0))
    old=P.process([0.,2.,4.],[0.,-250.,-500.],C,EION,P.calibration(C,EION,DT,M),M;horizon_ns=100000.);pop!(old,"trace")
    pulse=Dict("record_kind"=>"pulse","event_id"=>0,"global_decay_id"=>0,"group_id"=>0,"origin_time_ns"=>123456.,
        "group"=>Dict("horizon_ns"=>100000.,"origin_time_ns"=>123456.,"relative_times_ns"=>[0.,0.5],"row_indices"=>[7,9]),
        "deposited_energy_keV"=>550.,"raw_row_indices"=>[7,9],"transport_flags"=>Dict("example_cap"=>true),
        "final_induced_keV"=>-500.,"charge_end_ns"=>4.,"readout"=>old,"accepted"=>old["accepted"],"rejection_reason"=>old["rejection_reason"])
    for name in K.ARTIFACTS;write(joinpath(input,name),"");end
    write(joinpath(input,"scalars.jsonl"),join(JSON.json.([decay,pulse,zero]),'\n')*"\n")
    write(joinpath(input,"signals.csv"),K.SIGNAL_HEADER*"\n"*signal)
    cp(joinpath(@__DIR__,"native_readout_profile.json"),joinpath(input,"profile.json");force=true)
    cp(joinpath(@__DIR__,"native_readout_profile.json"),joinpath(input,"profile-input.json");force=true)
    E.save(joinpath(input,"readout-config.json"),C)
    counts=Dict("initial_primaries"=>2,"initial_decays"=>2,"zero_deposit_primaries"=>1,"groups"=>1,"native_failed_groups"=>0,
        "native_charge_samples"=>3,"accepted"=>0,"rejected"=>1,"readout_rejected"=>1,"analog_samples"=>50000,"saturated"=>0)
    report=Dict("status"=>"completed_provisional_native_response","model_id"=>K.MODEL,"model_sha256"=>K.MODEL_SHA,
        "counts"=>counts,"temperature_K"=>77,"stored_temperature_K"=>78,"readout_contact_id"=>1,"profile_sha256"=>K.PROFILE_SHA,
        "config_sha256"=>E.hashfile(joinpath(input,"readout-config.json")),"drift_dt_ns"=>DT,"ionisation_energy_eV"=>EION,
        "artifacts"=>Dict(n=>E.hashfile(joinpath(input,n)) for n in K.ARTIFACTS),"artifact_bytes"=>Dict(n=>filesize(joinpath(input,n)) for n in K.ARTIFACTS))
    E.save(joinpath(input,"run.json"),report);runsha=E.hashfile(joinpath(input,"run.json"))
    env=Dict("kind"=>"ring_native_response_v1","status"=>report["status"],"native_report_sha256"=>runsha,
        "model_contract"=>Dict("model_id"=>K.MODEL,"effective_model_sha256"=>K.MODEL_SHA,"contact_potentials_V"=>Dict("1"=>0,"2"=>-370)))
    E.save(joinpath(input,"ring-response.json"),env)
    (input=input,runsha=runsha,envelopesha=E.hashfile(joinpath(input,"ring-response.json")),pulse=pulse,zero=zero)
end

@testset "External SHA, rehashed coverage, identity, no-clobber and full ledger" begin
    E.environment()
    mktempdir(joinpath(dirname(@__DIR__),".local")) do dir
        f=fixture(dir);a=K.load_saved(f.input,f.runsha,f.envelopesha)
        @test length(a.waves)==1 && length(a.scalars.records)==3
        @test_throws ArgumentError K.load_saved(f.input,repeat("0",64),f.envelopesha)
        @test_throws ArgumentError K.load_saved(f.input,f.runsha,repeat("0",64))
        before=Dict(n=>E.hashfile(joinpath(f.input,n)) for n in readdir(f.input))
        out=joinpath(dir,"readout-inverted-v1");r=K.derive(f.input,f.runsha,f.envelopesha,out)
        @test r["native_calls"]==r["field_calls"]==r["radiation_calls"]==0
        @test r["counts"]["accepted"]==1 && r["counts"]["initial_primaries"]==2 && r["counts"]["zero_deposit_primaries"]==1
        @test r["status"]=="completed_readout_derivative" && r["all_saved_successful_group_signals_covered"]
        rows=JSON.parse.(readlines(joinpath(out,"scalars.jsonl")))
        @test rows[3]==f.zero && rows[2]["original_readout"]==f.pulse["readout"]
        for key in ("group","raw_row_indices","transport_flags","final_induced_keV","deposited_energy_keV","origin_time_ns")
            @test rows[2][key]==f.pulse[key]
        end
        @test rows[2]["final_induced_keV"]==-500 && rows[2]["electronics_input_final_charge_keV"]==500
        @test before==Dict(n=>E.hashfile(joinpath(f.input,n)) for n in readdir(f.input))
        @test_throws ArgumentError K.derive(f.input,f.runsha,f.envelopesha,out)
        @test_throws ArgumentError K.derive(f.input,f.runsha,f.envelopesha,joinpath(dirname(dir),"not-a-sibling"))
    end
    variants=(
        "\"0\",\"0\",\"0\",\"0\",\"0\"\n\"0\",\"0\",\"0\",\"2\",\"-500\"\n", # missing sample, rehashed
        "\"0\",\"0\",\"0\",\"0\",\"0\"\n\"0\",\"0\",\"1\",\"2\",\"-250\"\n\"0\",\"0\",\"0\",\"4\",\"-500\"\n", # unknown group
        "\"0\",\"0\",\"0\",\"0\",\"0\"\n\"0\",\"0\",\"0\",\"3\",\"-250\"\n\"0\",\"0\",\"0\",\"4\",\"-500\"\n", # changed grid
        "\"0\",\"0\",\"0\",\"0\",\"0\"\n\"0\",\"0\",\"0\",\"2\",\"NaN\"\n\"0\",\"0\",\"0\",\"4\",\"-500\"\n", # nonfinite
        "\"0\",\"0\",\"0\",\"0\",\"0\"\n\"0\",\"0\",\"0\",\"2\",\"-250\"\n\"0\",\"0\",\"0\",\"4\",\"-499\"\n") # scalar mismatch
    for signal in variants
        mktempdir(joinpath(dirname(@__DIR__),".local")) do dir
            f=fixture(dir;signal=signal);out=joinpath(dir,"refused")
            @test_throws ArgumentError K.derive(f.input,f.runsha,f.envelopesha,out)
            @test !ispath(out)
        end
    end
    mktempdir(joinpath(dirname(@__DIR__),".local")) do dir
        f=fixture(dir);records=JSON.parse.(readlines(joinpath(f.input,"scalars.jsonl")))
        failed=records[2];failed["status"]="native_transport_failed";failed["readout"]=nothing;failed["final_induced_keV"]=nothing
        failed["charge_end_ns"]=nothing;failed["accepted"]=false;failed["rejection_reason"]="native_transport_failed"
        failed["native_error"]=Dict("message"=>"Noncontact endpoint outside crystal","stage"=>"NativeLiExample.native_event")
        write(joinpath(f.input,"scalars.jsonl"),join(JSON.json.(records),'\n')*"\n")
        write(joinpath(f.input,"signals.csv"),K.SIGNAL_HEADER*"\n")
        write(joinpath(f.input,"native-failures.jsonl"),JSON.json(failed)*"\n")
        report=JSON.parsefile(joinpath(f.input,"run.json"));report["status"]="completed_with_native_failures"
        merge!(report["counts"],Dict("native_failed_groups"=>1,"native_charge_samples"=>0,"readout_rejected"=>0))
        for name in ("scalars.jsonl","signals.csv","native-failures.jsonl")
            report["artifacts"][name]=E.hashfile(joinpath(f.input,name));report["artifact_bytes"][name]=filesize(joinpath(f.input,name))
        end
        E.save(joinpath(f.input,"run.json"),report);runsha=E.hashfile(joinpath(f.input,"run.json"))
        env=JSON.parsefile(joinpath(f.input,"ring-response.json"));env["status"]=report["status"];env["native_report_sha256"]=runsha
        E.save(joinpath(f.input,"ring-response.json"),env);envsha=E.hashfile(joinpath(f.input,"ring-response.json"))
        out=joinpath(dir,"failed-native-preserved");r=K.derive(f.input,runsha,envsha,out)
        actual=JSON.parse.(readlines(joinpath(out,"scalars.jsonl")))
        @test actual[2]==failed && actual[2]["readout"]===nothing && actual[2]["final_induced_keV"]===nothing
        @test r["status"]=="completed_with_native_failures" && r["counts"]["native_failed_groups"]==1
        @test r["counts"]["accepted"]==r["counts"]["readout_rejected"]==0
        @test isempty(readlines(joinpath(out,"traces.jsonl")))
    end
    counts=Dict("initial_primaries"=>2,"initial_decays"=>2,"groups"=>0,"zero_deposit_primaries"=>2,"native_failed_groups"=>0)
    for id in (true,0.0)
        bytes=Vector{UInt8}(codeunits(JSON.json(Dict("record_kind"=>"decay","event_id"=>id,"global_decay_id"=>0,"group_id"=>nothing,"zero_deposit"=>true,"pulse_count"=>0,"deposited_energy_keV"=>0))))
        @test_throws ArgumentError K.scalar_records(bytes,counts)
    end
end
