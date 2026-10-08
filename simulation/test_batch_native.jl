# Focused software contracts only; no fields, drift, radiation or external cache load.
using Test, SHA, Serialization
include("batch_native_response.jl")
const BN=BatchNativeResponse;const B=BatchNativeContract;const N=BN.N
function batch(offset=10000;index=1,count=2)
    Dict("batch_index"=>index,"global_initial_offset"=>offset,"primary_count"=>count,
        "local_initial_primary_id_range"=>[0,count-1],"global_initial_primary_id_range"=>[offset,offset+count-1],"radiation_seed"=>260926)
end
@testset "Native configuration validates before exclusive output reservation" begin
    # This executes the actual prepare boundary, without loading or solving a model.
    parent=joinpath(BN.Q.ROOT,".local/student-batches-v1/execution-v1")
    mktempdir(parent) do testroot
        d=Dict("selection"=>Dict("detector"=>"AK01"),"operating_model"=>Dict("readout_contact_id"=>1))
        path=joinpath(testroot,"native")
        reserved=BN.configured_output(d,path)
        @test isdir(path) && reserved.output==abspath(path)
        @test reserved.config.output==abspath(path) && reserved.config.min_grid==0.25
        @test_throws ArgumentError BN.configured_output(d,path)
        @test isempty(readdir(path))
    end
end
@testset "Raw local IDs and global native seeds cross boundaries" begin
    for offset in (0,9999,10000,19999,20000,B.MAX_SAFE_INTEGER-2)
        b=batch(offset);e=Dict{String,Any}("event_id"=>1,"global_decay_id"=>1,"batch_index"=>1,"local_initial_id"=>1,"global_initial_id"=>offset+1,
            "steps"=>[Dict("raw_row_index"=>19,"time_ns"=>345.0,"energy_keV"=>4.0),Dict("raw_row_index"=>28,"time_ns"=>500.0,"energy_keV"=>0.0)],
            "tracks"=>[Dict("particle"=>1000561371,"time"=>153.0)])
        original=deepcopy(e);g=Dict("origin_time_ns"=>345.0,"row_indices"=>[19]);input=B.native_event_input(e,g,b)
        @test input["event_id"]==offset+1
        @test input["primary_time_ns"]==345.0 && input["steps"]==[e["steps"][1]]
        @test e==original # raw delayed daughters and the complete zero-row ledger survive
        @test B.parcel_seed(2609261,offset+1,19,16)==N.parcel_seed(2609261,offset+1,19,16)
        @test B.parcel_seed(2609261,offset+1,19,16)!=B.parcel_seed(2609261,offset+1,19,15)
        bad=deepcopy(e);bad["global_initial_id"]+=1
        @test_throws ArgumentError B.identity(bad,b)
    end
    a=batch();c=batch(20000;index=2)
    @test B.parcel_seed(2609261,a["global_initial_offset"],0,1)!=B.parcel_seed(2609261,c["global_initial_offset"],0,1)
    for edit in (("primary_count",true),("primary_count",10001),("global_initial_offset",-1),("global_initial_offset",B.MAX_SAFE_INTEGER),("radiation_seed",0),("local_initial_primary_id_range",Any[false,1]))
        bad=batch();bad[edit[1]]=edit[2];@test_throws ArgumentError B.descriptor(bad)
    end
    @test_throws ArgumentError B.parcel_seed(2609262,1,0,1)
    @test_throws ArgumentError B.parcel_seed(2609261,1,0,17)
end
@testset "Consumed cache bytes precede decode" begin
    io=IOBuffer();serialize(io,(calibration=Dict("volts_per_keV"=>0.25),));raw=take!(io);h=bytes2hex(sha256(raw));calls=Ref(0)
    decode(io)=(calls[]+=1;deserialize(io))
    @test B.verified_deserialize(raw,h;deserialize_fn=decode).calibration["volts_per_keV"]==0.25
    @test calls[]==1
    changed=copy(raw);changed[end]⊻=0x01
    @test_throws ArgumentError B.verified_deserialize(changed,h;deserialize_fn=decode)
    @test_throws ArgumentError B.verified_deserialize(UInt8[],h;deserialize_fn=decode)
    @test_throws ArgumentError B.verified_deserialize(raw,uppercase(h);deserialize_fn=decode)
    @test calls[]==1
end
@testset "Versioned count admission and preserved operating configuration" begin
    s=Dict("name"=>"batch-test","cryostat"=>"lbnl_modular_nominal_v1","detector"=>"AK01","source"=>"cs137_point_decay_v1","pose"=>"nominal","primary_count"=>25001,"seed"=>1,"threads"=>Threads.nthreads(),"electronics"=>Dict())
    @test BN.validate_selection(s)===nothing
    for value in (false,0,-1,1.0,B.MAX_SAFE_INTEGER+1)
        bad=copy(s);bad["primary_count"]=value;@test_throws ArgumentError BN.validate_selection(bad)
    end
    profile=BN.P.load(joinpath(@__DIR__,"native_readout_profile.json"))
    for n in (1,499,500,9999,10000)
        c=BN.P.for_census(profile.profile,n);@test c["expected_primary_count"]==n
        bad=deepcopy(c);bad["gain"]*=2;@test_throws ArgumentError BN.P.validate_resolved(bad,profile.profile,n)
    end
    e=Dict("event_id"=>0,"global_decay_id"=>0,"batch_index"=>0,"local_initial_id"=>0,"global_initial_id"=>0)
    g=Dict("group_id"=>0,"origin_time_ns"=>0.0,"row_indices"=>[9])
    failure=BN.NR.failed_pulse(e,g,[Dict("energy_keV"=>2.0,"time_ns"=>0.0)],Dict("parcels"=>16,"seed"=>2609261),Dict("message"=>"Noncontact endpoint outside crystal"),"a"^64)
    @test failure["final_induced_keV"]===nothing && failure["readout"]===nothing && failure["endpoints"]===nothing
end
