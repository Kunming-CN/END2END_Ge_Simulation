# Software-only identity boundaries; synthetic deposits, no fields or drift.
include(joinpath(@__DIR__,"..","simulation","gegi_campaign_response.jl"))
using Test
const C=GeGICampaignResponse
const G=C.G

@testset "Streamed IDs are independent of nominal census; legacy stays finite" begin
    n=1110000
    req=Dict{String,Any}("selection"=>Dict("primary_count"=>n))
    @test C.event_id_bound(req)==n
    req["selection"]["primary_count"]=20000000
    @test C.event_id_bound(req)==20000000
    req["selection"]["primary_count"]=n
    req["event_id_policy"]=C.FINITE_EVENT_ID_POLICY
    @test C.event_id_bound(req)==n
    req["event_id_policy"]=C.STREAMING_EVENT_ID_POLICY
    bound=C.event_id_bound(req)
    @test bound===nothing && req["selection"]["primary_count"]==n
    event=Dict{String,Any}("event_id"=>n-1,"primary_time_ns"=>100.,"steps"=>[
        Dict("raw_row_index"=>3,"energy_keV"=>5.,"position_mm"=>[0.,0.,0.],"time_ns"=>100.)])
    @test G.validate_event(event,n)==(5.,100.)
    for id in (n-1,n,1110048)
        event["event_id"]=id
        @test G.validate_event(event,bound)==(5.,100.)
        id>=n && @test_throws ArgumentError G.validate_event(event,n)
    end
    for id in (-1,1.5,true,"1110048")
        event["event_id"]=id
        @test_throws ArgumentError G.validate_event(event,bound)
        @test_throws ArgumentError G.validate_event(event,n)
    end
    for policy in ("unknown",nothing,true)
        req["event_id_policy"]=policy
        @test_throws ArgumentError C.event_id_bound(req)
    end
    req["event_id_policy"]=C.STREAMING_EVENT_ID_POLICY
    req["selection"]["primary_count"]=0
    @test_throws ArgumentError C.event_id_bound(req)
    large=Dict("event_id"=>n-1,"steps"=>fill(event["steps"][1],100001),"primary_time_ns"=>100.)
    @test G.validate_event(large,n)==(500005.,100.)
    @test_throws ArgumentError G.validate_event(Dict("event_id"=>0,"steps"=>Any[]),n)

    channels=[Dict("id"=>id,"wiring_factor"=>(id<=17 ? 1 : -1)) for id in 1:34]
    fake=(sim,position,energy,cfg)->(
        Dict(id=>(times=[0.,1.,2.],charge=(id==3 ? [0.,energy,energy] : zeros(3))) for id in 1:34),
        [Dict("status"=>"contact","step_limit_reached"=>false,"contact_ids"=>[3])])
    mktempdir(joinpath(G.ROOT,".local")) do folder
        event["event_id"]=n-1
        ordinary=G.process_event(event,nothing,(dt=1.,),channels,nothing,nothing,nothing,nothing,n,
            joinpath(folder,"finite.csv");native_only=true,deposit_processor=fake)
        streamed=G.process_event(event,nothing,(dt=1.,),channels,nothing,nothing,nothing,nothing,bound,
            joinpath(folder,"streamed.csv");native_only=true,deposit_processor=fake)
        @test read(joinpath(folder,"finite.csv"))==read(joinpath(folder,"streamed.csv"))
        @test Dict(k=>v for (k,v) in ordinary if k!="signals_ref")==Dict(k=>v for (k,v) in streamed if k!="signals_ref")
        event["event_id"]=1110048
        @test_throws ArgumentError G.process_event(event,nothing,(dt=1.,),channels,nothing,nothing,nothing,nothing,n,
            joinpath(folder,"rejected.csv");native_only=true,deposit_processor=fake)
        accepted=G.process_event(event,nothing,(dt=1.,),channels,nothing,nothing,nothing,nothing,bound,
            joinpath(folder,"accepted.csv");native_only=true,deposit_processor=fake)
        @test accepted["event_id"]==1110048 && accepted["truth_edep_keV"]==5.

        group=Dict("event_id"=>1110048,"group_id"=>0,"primary_time_ns"=>90.,"group_origin_time_ns"=>100.,
            "steps"=>event["steps"],"horizon_ns"=>100000.,"source_id"=>"synthetic",
            "parent_event_metadata"=>Dict("parent_decay_id"=>nothing,"initial_daughter_id"=>488757))
        text=C.JSON.json(group);digest=bytes2hex(C.sha256(text));request=joinpath(folder,"request.json")
        G.save(request,Dict("event_id_policy"=>C.STREAMING_EVENT_ID_POLICY))
        ctx=(out=folder,n=bound,sim=nothing,cfg=(dt=1.,),channels=channels,readout=nothing,
            cal=nothing,matrix=nothing,eion=nothing,response_mode=G.NATIVE_SIGNAL_ONLY,
            requestpath=request,requestsha=G.hashfile(request),sources=C.sources())
        processor=(args...;kwargs...)->G.process_event(args...;kwargs...,deposit_processor=fake)
        receipt=C.process_group(ctx,Dict("group_json"=>text,"input_sha256"=>digest);event_processor=processor)
        saved=C.E.readjson(receipt["event_path"])
        @test saved["event_id"]==1110048 && saved["input_group"]==group
        @test saved["input_group"]["parent_event_metadata"]["parent_decay_id"]===nothing
        @test receipt["event_id"]==1110048
    end
end
