# Saved-signal regression only. No fields/cache, transport, drift or calibration injection.
# Arguments: frozen-source directory, saved benchmark input.json, new result.json.
using Test, JSON, SHA, LinearAlgebra
const ROOT=normpath(joinpath(@__DIR__,".."))
include(joinpath(ROOT,"simulation","gegi_campaign_response.jl"))
const C=GeGICampaignResponse;const G=GeGIResponse
BLAS.set_num_threads(1)
Threads.nthreads()==1 || error("Use one Julia thread")
length(ARGS)==3 || error("Use FROZEN_SOURCE_DIR SAVED_INPUT NEW_RESULT")
const FROZEN=abspath(ARGS[1]);const INPUT=abspath(ARGS[2]);const OUTPUT=abspath(ARGS[3])
isfile(OUTPUT) && error("Preserve the existing regression result")

module FrozenReadout
const SSDQuickstart=Main.SSDQuickstart;const SSDReplay=Main.SSDReplay
const Readout=Main.Readout;const ReadoutProfiles=Main.ReadoutProfiles
const GeGISignalHelpers=Main.GeGISignalHelpers
const GeGIPixelCalibration=Main.GeGIPixelCalibration
end
function frozen_module(name,module_name,expected)
    path=joinpath(FROZEN,name);G.hashfile(path)==expected || error("Frozen source changed: "*name)
    source=replace(read(path,String),"\r\n"=>"\n")
    start=first(findfirst("module "*module_name*"\n",source))
    stop=first(findlast("\nif abspath(PROGRAM_FILE)",source))-1
    Base.include_string(FrozenReadout,source[start:stop],joinpath(ROOT,"simulation",name))
end
frozen_module("gegi_response.jl","GeGIResponse","b249bea43f855123f67dfab204eeb47562fefdf9a73294cc02cc203327bde495")
frozen_module("gegi_campaign_response.jl","GeGICampaignResponse","2a7113c06c8a9a6d565c954988e8d372635c45213e538430d74529c0830f49c1")
const OLD=FrozenReadout.GeGICampaignResponse

# A typed test dispatch supplies previously saved, already summed native signals.
# Production native_deposit and its generic method remain untouched.
struct SavedSignals
    waves::Dict{Int,Any}
    calls::Base.RefValue{Int}
end
for mod in (G,FrozenReadout.GeGIResponse)
    Core.eval(mod,quote
        function native_deposit(sim::Main.SavedSignals,xyz,energy,cfg;ids=1:34)
            sim.calls[]+=1
            sim.waves,[Dict("step_limit_reached"=>false,"status"=>"contact","contact_ids"=>[1])]
        end
    end)
end

function group_run(mod,folder,group,waves,recipe,cal,matrix)
    mkpath(folder);request=joinpath(folder,"request.json")
    G.save(request,Dict("purpose"=>"Saved native signal orchestration test; no new physics"))
    sim=SavedSignals(waves,Ref(0))
    ctx=(out=folder,n=1000000,sim=sim,cfg=(dt=cal["time_step_ns"],),channels=recipe["channels"],
        readout=recipe["readout_config"],cal=cal,matrix=matrix,eion=recipe["ionisation_energy_eV"],
        requestpath=request,requestsha=G.hashfile(request),sources=mod.sources())
    text=JSON.json(group);command=Dict("group_json"=>text,"input_sha256"=>bytes2hex(sha256(text)))
    receipt=mod.process_group(ctx,command)
    @test sim.calls[]==1
    event=G.E.readjson(receipt["event_path"]);csv=read(receipt["signals_path"])
    @test mod.process_group(ctx,command)==receipt && sim.calls[]==1
    event,csv
end

started=time();payload=JSON.parsefile(INPUT);checks=Any[]
@test G.hashfile(INPUT)=="4c7532ac963c94d0aded3722e751028f2cf287b66db783132c86f755a15f6378"
@testset "Saved 102-channel replay and group outputs match frozen producer" begin
    for raw in payload["groups"]
        recipe=raw["recipe"];cal=recipe["electronics_calibration"];config=recipe["readout_config"]
        matrix=G.E.transition(config,cal["time_step_ns"])
        waves=Dict{Int,Any}(parse(Int,k)=>(times=Float64.(v["time_ns"]),charge=Float64.(v["signed_induced_keV"]))
            for (k,v) in raw["native_signals"])
        id=raw["identity"]["campaign_initial_id"]
        for horizon in (nothing,100000.)
            old=OLD.replay_channels(waves,recipe["channels"],config,recipe["ionisation_energy_eV"],cal,matrix;horizon_ns=horizon)
            new=C.replay_channels(waves,recipe["channels"],config,recipe["ionisation_energy_eV"],cal,matrix;horizon_ns=horizon)
            @test isequal(old,new)
            if horizon==raw["original_horizon_ns"]
                @test all(isequal(row[key],saved[key]) for (row,saved) in zip(new,raw["saved_channels"]) for key in keys(saved))
            end
            group=Dict("event_id"=>id,"group_id"=>0,"primary_time_ns"=>7.,"group_origin_time_ns"=>10.,
                "horizon_ns"=>horizon,"source_id"=>"saved-signal-test","initial_primary_id"=>id,
                "steps"=>[Dict("energy_keV"=>1.,"position_mm"=>[0.,0.,0.],"time_ns"=>10.,"raw_row_index"=>23)])
            mktempdir(joinpath(ROOT,".local")) do folder
                before,csv_before=group_run(OLD,joinpath(folder,"old","spool"),group,waves,recipe,cal,matrix)
                after,csv_after=group_run(C,joinpath(folder,"new","spool"),group,waves,recipe,cal,matrix)
                @test isequal(before,after)
                @test csv_before==csv_after
                @test after["input_group"]==group && after["input_steps"]==group["steps"]
                @test after["readout_horizon_ns"]===horizon
            end
            push!(checks,Dict("campaign_initial_id"=>id,"horizon_ns"=>horizon,
                "original_horizon_ns"=>raw["original_horizon_ns"],"channels"=>length(new),
                "replay_deep_equal"=>true,"group_deep_equal"=>true,"native_csv_byte_equal"=>true))
        end
    end
end

@testset "Finite groups consume the event response without reopening its CSV" begin
    mktempdir(joinpath(ROOT,".local")) do folder
        request=joinpath(folder,"request.json");G.save(request,Dict("purpose"=>"Single response contract"))
        ctx=(out=folder,n=100,sim=nothing,cfg=nothing,channels=nothing,readout=nothing,cal=nothing,matrix=nothing,
            eion=nothing,requestpath=request,requestsha=G.hashfile(request),sources=C.sources())
        group=Dict("event_id"=>1,"group_id"=>0,"primary_time_ns"=>0.,"group_origin_time_ns"=>10.,
            "horizon_ns"=>100000.,"steps"=>[Dict("energy_keV"=>1.,"position_mm"=>[0.,0.,0.],"time_ns"=>10.)])
        text=JSON.json(group);command=Dict("group_json"=>text,"input_sha256"=>bytes2hex(sha256(text)))
        calls=Ref(0)
        processor=(event,args...)->begin
            calls[]+=1
            @test event["readout_horizon_ns"]===100000.
            # This is deliberately not a native CSV: process_group may hash it,
            # but must not reread/recalculate channels after the event response.
            open(last(args),"w") do io;print(io,"test-only completed signal artifact");end
            Dict{String,Any}("event_id"=>1,"status"=>"completed","channels"=>["retained event response"])
        end
        receipt=C.process_group(ctx,command;event_processor=processor)
        @test calls[]==1
        @test G.E.readjson(receipt["event_path"])["channels"]==["retained event response"]
    end
end

@testset "Half-open finite window retains late native timing and clips electronics" begin
    recipe=payload["groups"][1]["recipe"];config=recipe["readout_config"];cal=recipe["electronics_calibration"]
    matrix=G.E.transition(config,cal["time_step_ns"])
    t=collect(0.:cal["time_step_ns"]:100010.);q=[v>=100002. ? 100. : 0. for v in t]
    result=G.channel_response(t,q,Dict("id"=>1,"wiring_factor"=>1),config,
        recipe["ionisation_energy_eV"],cal,matrix;horizon_ns=100000.)
    @test result["readout_end_ns"]<100000.
    @test result["charge_clipped_at_window"]===true
    @test result["untruncated_final_charge_keV"]==100.
    @test result["native_t50_ns"]>=100000. && result["native_t90_ns"]>=100000.
    @test result["t50_ns"]===nothing && result["t90_ns"]===nothing
    @test result["t50_outside_window"]===true && result["t90_outside_window"]===true
    @test result["accepted"]===false && result["current_balance"]["passed"]===true
    @test all(iszero,result["trace"]["signed_induced_charge_fC"])
end
G.save(OUTPUT,Dict("kind"=>"gegi_single_pass_readout_regression_v1","status"=>"completed",
    "seconds"=>time()-started,"julia_version"=>string(VERSION),"julia_threads"=>Threads.nthreads(),
    "blas_threads"=>BLAS.get_num_threads(),"input_sha256"=>G.hashfile(INPUT),
    "test_sha256"=>G.hashfile(@__FILE__),"source_code_sha256"=>C.sources(),"checks"=>checks,
    "scope"=>"Saved 102-channel signals at finite and null horizons; native_deposit uses test-only saved-signal dispatch.",
    "new_science_calls"=>Dict("transport"=>0,"native_drift"=>0,"field_solve"=>0,"calibration_injection"=>0)))
