# Software-only boundary checks: no field loading, calibration injections or drift.
include(joinpath(@__DIR__,"..","simulation","gegi_campaign_response.jl"))
using Test
const C=GeGICampaignResponse
const K=GeGIPixelCalibration

if ARGS != ["--failure-policy-only"]
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
end

if ARGS != ["--protocol-only"]
@testset "Exact domain errors retain complete unknown groups; others abort" begin
    for error in (ArgumentError.(C.RECORDED_NATIVE_ARGUMENT_ERRORS)...,
                  ArgumentError("Positive deposit outside GeGI crystal"),
                  ErrorException("Deposit starts on a GeGI contact"))
        mktempdir(joinpath(C.G.ROOT,".local")) do folder
            steps=[Dict("raw_row_index"=>1339,"energy_keV"=>1.25,"position_mm"=>[0.,0.,0.],"time_ns"=>100.),
                   Dict("raw_row_index"=>1340,"energy_keV"=>2.5,"position_mm"=>[1.,0.,0.],"time_ns"=>105.)]
            group=Dict("event_id"=>1188,"group_id"=>0,"primary_time_ns"=>0.,"group_origin_time_ns"=>100.,
                "steps"=>steps,"horizon_ns"=>nothing,"source_id"=>"gamma","initial_primary_id"=>1188)
            text=C.JSON.json(group);digest=bytes2hex(C.sha256(text))
            command=Dict("group_json"=>text,"input_sha256"=>digest)
            request=joinpath(folder,"request.json");C.G.save(request,Dict("purpose"=>"software-only failure isolation test"))
            ctx=(out=folder,n=10000,sim=nothing,cfg=nothing,channels=nothing,readout=nothing,
                 cal=nothing,matrix=nothing,eion=nothing,requestpath=request,
                 requestsha=C.G.hashfile(request),sources=C.sources())
            calls=Ref(0)
            failing_processor=(args...)->begin
                calls[]+=1
                @test args[1]["steps"]==steps && args[1]["primary_time_ns"]==100.
                throw(error)
            end
            known=error isa ArgumentError && error.msg in C.RECORDED_NATIVE_ARGUMENT_ERRORS
            eventpath=joinpath(folder,"g-"*digest*".json")
            receiptpath=joinpath(folder,"g-"*digest*"-receipt.json")
            if known
                receipt=C.process_group(ctx,command;event_processor=failing_processor)
                event=C.E.readjson(eventpath)
                @test event["status"]=="native_failed" && receipt["event_status"]=="native_failed"
                @test event["input_group"]==group && event["input_steps"]==steps && event["steps"]==steps
                @test event["truth_edep_keV"]==3.75
                @test all(event[key]===nothing for key in ("channels","signals_ref","signals_sha256","transport_flags"))
                @test receipt["signals_path"]===nothing && receipt["signals_sha256"]===nothing
                @test event["native_failure_policy"]==C.NATIVE_FAILURE_POLICY && event["native_domain_error"]==error.msg
                @test event["error"]==sprint(showerror,error)
                @test isfile(receiptpath) && C.G.hashfile(eventpath)==receipt["event_sha256"]
                @test all(isfile,receipt["retained_failure_paths"])
                repeated=C.process_group(ctx,command;event_processor=failing_processor)
                @test repeated==receipt && calls[]==1
            else
                @test_throws typeof(error) C.process_group(ctx,command;event_processor=failing_processor)
                event=C.E.readjson(eventpath)
                @test event["status"]=="unexpected_failure" && event["input_group"]==group
                @test event["channels"]===nothing && event["native_domain_error"]===nothing
                @test !isfile(receiptpath) && calls[]==1
            end
            @test !isfile(joinpath(folder,"g-"*digest*"-signals.csv"))
        end
    end
end
end

if ARGS != ["--protocol-only"] && ARGS != ["--failure-policy-only"]
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
