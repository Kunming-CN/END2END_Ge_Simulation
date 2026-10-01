# Imports and injected mocks only: no cache deserialization, native, fields,
# calibration or readout computation. Fresh entrypoint parsing is also exercised.
include("gamma_native_example.jl")
using Test
const A=GammaNativeExample
function mock_event(id=4;zero=false)
    Dict("initial_primary_id"=>id,"event_id"=>id,"truth_ge_edep_keV"=>zero ? 0.0 : 10.0,"zero_ge"=>zero,
        "steps"=>[Dict("raw_row_index"=>9,"energy_keV"=>zero ? 0.0 : 10.0,"time_ns"=>0.125,
            "position_mm"=>[1.,0.,2.])])
end
const MOCK_READOUT=(t,q)->Dict("current_balance"=>Dict("passed"=>true),"observed_times"=>copy(t),"observed_signal"=>copy(q))
@testset "gamma adapter mocked calculations only" begin
    called=Ref(0);zero=mock_event(0;zero=true)
    result=A.event_response(zero,"abort",()->(called[]+=1;error("zero must not drift")),MOCK_READOUT,x->nothing)
    @test called[]==0
    @test result["status"]=="native_not_applicable_true_zero"
    @test result["native"]===result["transport_flags"]===nothing
    @test result["readout"]["observed_times"]==[0.,2.]
    @test result["readout"]["observed_signal"]==[0.,0.]
    event=mock_event(); native=()->(times=[0.,2.,4.],signal=[0.,-.25,3.5],steps=[Dict("mock_endpoint"=>true)])
    result=A.event_response(event,"abort",native,MOCK_READOUT,x->Dict("mock"=>true))
    @test result["native"]["signal"]==[0.,-.25,3.5]
    @test result["readout"]["observed_signal"]==[0.,-.25,3.5]
    @test result["deposition_delays_ns"]==[.125]
    @test result["raw_row_indices"]==[9]
    @test result["parcel_seeds"][1]["parcels"][1]["seed_uint64_decimal"]==string(A.N.parcel_seed(2609261,4,9,1))
    for message in A.B.NATIVE_FAILURE_MESSAGES
        result=A.event_response(event,"record",()->throw(ArgumentError(message)),(t,q)->error("failure must not read out"),x->error("failure flags unknown"))
        @test result["status"]=="native_failed"
        @test all(result[k]===nothing for k in ("native","transport_flags","charge_input","final_induced_keV","charge_end_ns","readout"))
        @test result["error"]["message"]==message
        @test_throws ArgumentError A.event_response(event,"abort",()->throw(ArgumentError(message)),MOCK_READOUT,x->nothing)
    end
    @test_throws ArgumentError A.event_response(event,"record",()->throw(ArgumentError("unexpected domain")),MOCK_READOUT,x->nothing)
    @test_throws ErrorException A.event_response(event,"record",()->error("unexpected implementation"),MOCK_READOUT,x->nothing)
    @test_throws ErrorException A.event_response(event,"record",native,(t,q)->error("readout errors must abort"),x->nothing)
    # Resolve settings without running transition/calibration/process. Deliberate
    # independent hash changes cannot authorize modified electronics values.
    profile=A.P.load(joinpath(@__DIR__,"native_readout_profile.json"));config=A.P.for_census(profile.profile,3)
    @test A.P.validate_resolved(config,profile.profile,3)===nothing
    for key in ("gain","threshold_V","shaping_tau_us")
        changed=copy(config);changed[key]*=2
        @test_throws ArgumentError A.P.validate_resolved(changed,profile.profile,3)
    end
    changed=copy(config);changed["expected_primary_count"]=3.0
    @test !A.typed_equal(changed,config)
    changed=copy(config);changed["require_all_events"]=1
    @test !A.typed_equal(changed,config)
    @test !haskey(result,"global_decay_id")
    @test !occursin("solve_fields!",read(joinpath(@__DIR__,"gamma_native_example.jl"),String))
end
@testset "consumed request/cache byte and canonical-pin boundaries" begin
    raw=collect(codeunits("{\"kind\":\"first_consumed_bytes\"}"));reads=Ref(0)
    consumed=A.consumed_request("not-read-from-disk";byte_reader=(path,limit)->begin
        reads[]+=1;copy(raw)
    end)
    @test reads[]==1
    @test consumed.document["kind"]=="first_consumed_bytes"
    @test consumed.sha256==bytes2hex(A.sha256(raw))
    changed=collect(codeunits("{\"kind\":\"different_consumed_bytes\"}"))
    second=A.consumed_request("same-path-label";byte_reader=(path,limit)->copy(changed))
    @test second.sha256!=consumed.sha256
    @test second.document["kind"]=="different_consumed_bytes"
    @test_throws ArgumentError A.consumed_request("oversized";byte_reader=(path,limit)->zeros(UInt8,limit+1))
    @test_throws ArgumentError A.consumed_request("empty";byte_reader=(path,limit)->UInt8[])
    # Resolve mock paths only. No science cache is read or deserialized.
    resolve=path->normpath(abspath(path));calls=Ref(0);byte_reads=Ref(0)
    model="AK02";spec=A.DETECTOR_PINS[model];relative=".local/cs137-1m-native/cache/AK02.jls"
    request=Dict{String,Any}("model_id"=>model,"model_sha256"=>spec.model,"cache_file"=>relative,
        "cache_sha256"=>spec.cache,"pins"=>Dict(relative=>spec.cache,"models/AK02.yaml"=>spec.model))
    @test A.canonical_cache(request;resolve=resolve)==resolve(joinpath(A.ROOT,relative))
    for (field,value) in (("cache_file","../outside.jls"),("cache_file",".local/unpinned.jls"),
            ("cache_sha256",repeat("0",64)),("model_sha256",repeat("0",64)))
        bad=deepcopy(request);bad[field]=value
        @test_throws ArgumentError A.cache_from_request(bad;resolve=resolve,
            byte_reader=(path,limit)->(byte_reads[]+=1;UInt8[1]),deserialize_fn=io->(calls[]+=1))
    end
    for pin in (relative,"models/AK02.yaml")
        bad=deepcopy(request);delete!(bad["pins"],pin)
        @test_throws ArgumentError A.cache_from_request(bad;resolve=resolve,
            byte_reader=(path,limit)->(byte_reads[]+=1;UInt8[1]),deserialize_fn=io->(calls[]+=1))
        bad=deepcopy(request);bad["pins"][pin]=repeat("0",64)
        @test_throws ArgumentError A.cache_from_request(bad;resolve=resolve,
            byte_reader=(path,limit)->(byte_reads[]+=1;UInt8[1]),deserialize_fn=io->(calls[]+=1))
    end
    @test calls[]==byte_reads[]==0
    escape=path->endswith(path,"AK02.jls") ? normpath(joinpath(A.ROOT,"..","outside","AK02.jls")) : resolve(path)
    @test_throws ArgumentError A.cache_from_request(request;resolve=escape,
        byte_reader=(path,limit)->(byte_reads[]+=1;UInt8[1]),deserialize_fn=io->(calls[]+=1))
    @test calls[]==byte_reads[]==0
    @test_throws ArgumentError A.cache_from_request(request;resolve=resolve,
        byte_reader=(path,limit)->(byte_reads[]+=1;UInt8[1,2,3]),deserialize_fn=io->(calls[]+=1))
    @test byte_reads[]==1 && calls[]==0
    # A positive fixture proves the mock receives precisely the verified bytes.
    fixture=UInt8[3,1,4,1,5];expected=bytes2hex(A.sha256(fixture))
    observed=A.deserialize_verified(fixture,expected;deserialize_fn=io->(calls[]+=1;read(io)))
    @test observed==fixture && calls[]==1
    @test_throws ArgumentError A.deserialize_verified(UInt8[9,9],expected;deserialize_fn=io->(calls[]+=1))
    @test calls[]==1
    @test_throws ArgumentError A.deserialize_verified(UInt8[],expected;deserialize_fn=io->(calls[]+=1))
end
println("MOCK_SCOPE actual_native_calls=0 injection_calibrations=0 readout_calculations=0 field_solves=0 cache_deserializations=0")
