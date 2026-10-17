# Software-only boundary checks: no field loading, calibration injections or drift.
include(joinpath(@__DIR__,"..","simulation","gegi_campaign_response.jl"))
using Test
const C=GeGICampaignResponse
const K=GeGIPixelCalibration

@testset "Protocol replies preserve partial/completed/quit body types" begin
    bodies=(
        Dict("status"=>"partial","calibration_path"=>nothing,"calibration_sha256"=>nothing,"diagnostics_path"=>nothing),
        Dict("status"=>"completed","calibration_path"=>"calibration.json","calibration_sha256"=>"abc","diagnostics_path"=>"diagnostics.json"),
        Dict("status"=>"closed"))
    for (requestid,body) in enumerate(bodies)
        original=copy(body);io=IOBuffer()
        C.reply(io,body,requestid)
        line=String(take!(io));decoded=C.JSON.parse(line)
        @test endswith(line,"\n") && count(==('\n'),line)==1
        @test decoded["request_id"]===requestid
        @test decoded["protocol"]==C.PROTOCOL
        @test all(decoded[key]==value for (key,value) in body)
        @test body==original && !haskey(body,"request_id")
    end
end

if ARGS != ["--protocol-only"]
@testset "Half-open readout window retains unknown late timing" begin
    req=C.E.readjson(only(ARGS))
    config=req["readout_config"];dt=req["drift_dt_ns"];eion=req["ionisation_energy_eV"]
    matrix=C.E.transition(config,dt);cal=C.P.calibration(config,eion,dt,matrix)
    t=collect(0.:dt:100010.);q=[v>=100002. ? 100. : 0. for v in t]
    ch=[Dict("id"=>1,"wiring_factor"=>1)]
    native=Dict(1=>(times=t,charge=q))
    result=only(C.replay_channels(native,ch,config,eion,cal,matrix;horizon_ns=100000.))
    @test result["readout_end_ns"]<100000.
    @test result["charge_clipped_at_window"]===true
    @test result["untruncated_final_charge_keV"]==100.
    @test result["native_t50_ns"]>=100000.
    @test result["t50_ns"]===nothing
    @test result["t50_outside_window"]===true
    @test result["accepted"]===false
    @test result["current_balance"]["passed"]===true
    @test all(iszero,result["trace"]["signed_induced_charge_fC"])
end

@testset "Calibration checkpoint integrity and fixed pixel census" begin
    pixels=[(9,26);[(x,y) for x in 1:16 for y in 18:33 if (x,y)!=(9,26)]]
    @test length(pixels)==length(Set(pixels))==256
    @test first(pixels)==(9,26)
    @test length(K.DEPTHS)==11
    @test length(K.DIAGNOSTIC_PIXELS)*length(K.DIAGNOSTIC_DEPTHS)*length(K.DIAGNOSTIC_OFFSETS)==175
    mktempdir(joinpath(C.G.ROOT,".local")) do folder
        path=joinpath(folder,"checkpoint.json")
        payload=Dict("position_mm"=>[1.,2.,3.],"status"=>"excluded_geometry","ctd_ns"=>nothing)
        K.save_record(path,payload,"identity")
        @test K.read_record(path,"identity")==payload
        @test_throws ArgumentError K.read_record(path,"changed")
        record=C.E.readjson(path);record["payload"]["position_mm"][1]=4.
        C.G.save(path,record)
        @test_throws ArgumentError K.read_record(path,"identity")
    end
end
end
