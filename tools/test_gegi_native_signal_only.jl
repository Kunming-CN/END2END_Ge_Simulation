# Synthetic native waves only: no fields, transport or carrier drift.
include(joinpath(@__DIR__,"..","simulation","gegi_campaign_response.jl"))
using Test
const C=GeGICampaignResponse
const G=C.G

@testset "Native-only mode preserves full signed CSV and endpoints; default unchanged" begin
    channels=[Dict("id"=>id,"wiring_factor"=>(id<=17 ? 1 : -1)) for id in 1:34]
    cfg=(dt=1.,)
    loaded=C.P.load(joinpath(G.ROOT,"simulation","native_readout_profile.json"))
    readout=loaded.config; matrix=C.E.transition(readout,cfg.dt)
    cal=C.P.calibration(readout,2.95,cfg.dt,matrix)
    event=Dict("event_id"=>2,"primary_time_ns"=>100.,"readout_horizon_ns"=>100000.,
        "steps"=>[Dict("raw_row_index"=>5,"energy_keV"=>5.,"position_mm"=>[0.,0.,0.],"time_ns"=>100.),
                  Dict("raw_row_index"=>9,"energy_keV"=>3.,"position_mm"=>[1.,0.,0.],"time_ns"=>103.)])
    calls=Ref(0); limited=Ref(false)
    fake=(sim,position,energy,cfg)->begin
        @test sim===nothing
        calls[]+=1
        waves=Dict(id=>(times=[0.,1.,2.],charge=(id==3 ? [0.,energy,energy] :
             id==24 ? [0.,-energy,-energy] : id==2 ? [0.,-energy/10,0.] : zeros(3))) for id in 1:34)
        endpoints=[Dict("status"=>(limited[] ? "stopped_without_contact" : "contact"),
                        "step_limit_reached"=>limited[],"contact_ids"=>[3])]
        waves,endpoints
    end
    mktempdir(joinpath(G.ROOT,".local")) do folder
        ordinary=G.process_event(event,nothing,cfg,channels,readout,cal,matrix,2.95,10,
            joinpath(folder,"default.csv");deposit_processor=fake)
        explicit=G.process_event(event,nothing,cfg,channels,readout,cal,matrix,2.95,10,
            joinpath(folder,"explicit.csv");native_only=false,deposit_processor=fake)
        # Native mode cannot accidentally invoke isolated electronics: all its
        # electronics inputs are nothing, while the same deposit/sum calls run.
        native=G.process_event(event,nothing,cfg,channels,nothing,nothing,nothing,nothing,10,
            joinpath(folder,"native.csv");native_only=true,deposit_processor=fake)
        @test calls[]==6
        @test read(joinpath(folder,"default.csv"))==read(joinpath(folder,"explicit.csv"))==read(joinpath(folder,"native.csv"))
        @test Dict(k=>v for (k,v) in ordinary if k!="signals_ref")==Dict(k=>v for (k,v) in explicit if k!="signals_ref")
        for key in ("event_id","primary_time_ns","truth_edep_keV","status","steps","transport_flags","signals_sha256")
            @test native[key]==ordinary[key]
        end
        @test native["response_mode"]==G.NATIVE_SIGNAL_ONLY
        @test native["readout_status"]=="shared_readout_pending" && native["readout_summary"]===nothing
        @test length(native["channels"])==34
        @test all(Set(keys(row))==Set(("contact_id","wiring_factor","final_induced_keV","final_wired_induced_keV")) for row in native["channels"])
        @test native["channels"][2]["final_induced_keV"]==0.
        waves=C.read_native(joinpath(folder,"native.csv"),channels)
        @test minimum(waves[2].charge)<0 && last(waves[2].charge)==0
        @test Set(keys(waves))==Set(1:34)
        limited[]=true
        flagged=G.process_event(event,nothing,cfg,channels,nothing,nothing,nothing,nothing,10,
            joinpath(folder,"flagged.csv");native_only=true,deposit_processor=fake)
        @test flagged["status"]=="step_limit"
        @test flagged["transport_flags"]==Dict("step_limits"=>2,"stopped_without_contact"=>2)
        @test all(step["endpoints"][1]["step_limit_reached"] for step in flagged["steps"])
    end
end

@testset "Resident opt-in request selects native mode without an isolated fallback" begin
    mktempdir(joinpath(G.ROOT,".local")) do folder
        group=Dict("event_id"=>2,"group_id"=>0,"primary_time_ns"=>0.,"group_origin_time_ns"=>100.,
            "steps"=>[Dict("raw_row_index"=>7,"energy_keV"=>2.,"position_mm"=>[0.,0.,0.],"time_ns"=>100.)],
            "horizon_ns"=>100000.,"source_id"=>"synthetic")
        text=C.JSON.json(group); digest=bytes2hex(C.sha256(text))
        request=joinpath(folder,"request.json");G.save(request,Dict("response_mode"=>G.NATIVE_SIGNAL_ONLY))
        ctx=(out=folder,n=10,sim=nothing,cfg=nothing,channels=nothing,readout=nothing,
             cal=nothing,matrix=nothing,eion=nothing,response_mode=G.NATIVE_SIGNAL_ONLY,
             requestpath=request,requestsha=G.hashfile(request),sources=C.sources())
        received=Ref(false)
        fake=(args...;native_only=false)->begin
            received[]=native_only
            write(args[end],"contact_id,time_ns,signed_induced_keV,wired_induced_keV\n")
            Dict{String,Any}("event_id"=>2,"status"=>"completed","channels"=>Any[],"steps"=>Any[])
        end
        receipt=C.process_group(ctx,Dict("group_json"=>text,"input_sha256"=>digest);event_processor=fake)
        event=C.E.readjson(receipt["event_path"])
        @test received[]
        @test event["response_mode"]==G.NATIVE_SIGNAL_ONLY
        @test event["readout_summary"]===nothing && event["readout_status"]=="shared_readout_pending"
        @test event["input_group"]==group && event["input_steps"]==group["steps"]
    end
end
