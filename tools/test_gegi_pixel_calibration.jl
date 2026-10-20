# Software-only recording contract. This replaces GeGIResponse with a fixture;
# SSD, field loading/solves, drift and physical calibration are never imported.
using Test, JSON, SHA
include(joinpath(@__DIR__,"..","simulation","gegi_signal_helpers.jl"))

module GeGIResponse
using JSON, SHA
using ..GeGISignalHelpers
const H=GeGISignalHelpers
const ROOT=dirname(@__DIR__)
const SOURCES=()
check=H.check
hashfile(path)=bytes2hex(sha256(read(path)))
const MODEL_HASH=hashfile(joinpath(ROOT,"models","GeGI_3D.yaml"))
module SSD
struct CartesianPoint{T}
    x::T
    y::T
    z::T
end
struct Region
    contains::Bool
end
Base.in(::CartesianPoint,region::Region)=region.contains
get_precision_type(sim)=Float64
end
module E
using JSON
readjson(path)=JSON.parsefile(path)
integer(x)=x isa Integer && !(x isa Bool)
environment()=Dict("software_only_test_fixture"=>true)
end
module Q
using ..GeGIResponse: ROOT,check
childof(path,parent)=path!=parent && !startswith(relpath(path,parent),"..")
function validate_output(path)
    check(!ispath(path) && childof(abspath(path),abspath(joinpath(ROOT,".local"))),"Invalid fixture output")
end
end
function save(path,value)
    open(path,"w") do io
        JSON.print(io,value);println(io)
    end
end
function pinned_input(value,key,hashkey)
    path=joinpath(ROOT,value[key]);check(hashfile(path)==value[hashkey],"Changed fixture input")
    path
end
const calls=Any[]
const mode=Ref(:complete)
function native_deposit(sim,xyz,energy,cfg;ids=1:34)
    push!(calls,(xyz=copy(xyz),energy=energy,ids=collect(ids)))
    mode[]==:known_failure && throw(ArgumentError("Invalid waveform support"))
    mode[]==:unexpected_failure && error("fixture unexpected failure")
    t=collect(0.:5.)
    waves=Dict{Int,Any}()
    for id in ids
        mode[]==:missing_channel && id==34 && continue
        q=id==9 ? energy.*[0.,0.6,1.,0.2,0.6,1.] :
          id==26 ? -energy.*[0.,0.1,0.4,0.6,0.9,1.] :
          [0.,id/10,-id/20,id/40,0.,-id/80]
        waves[id]=(times=copy(t),charge=q)
    end
    endpoints=[Dict("species"=>"hole","contact_ids"=>[9],"step_limit_reached"=>false),
        Dict("species"=>"electron","contact_ids"=>[26],"step_limit_reached"=>mode[]==:incomplete)]
    waves,endpoints
end
end

include(joinpath(@__DIR__,"..","simulation","gegi_pixel_calibration.jl"))
const K=GeGIPixelCalibration
const G=GeGIResponse
const H=GeGISignalHelpers
const CFG=(dt=1.,max_steps=1001)
function simulation_fixture(;bulk=true,contact=false)
    config=Dict("detectors"=>[Dict("contacts"=>[
        Dict("id"=>id,"name"=>id==17 ? "X_guard" : id==34 ? "Y_guard" :
             (id<=16 ? "X" : "Y")*lpad(string(id<=16 ? id : id-17),2,'0'),
             "potential"=>id<=17 ? -879. : 0.,
             "geometry"=>Dict("intersection"=>[nothing,Dict("box"=>Dict("origin"=>[Float64(id),Float64(id),0.]))]))
        for id in 1:34])])
    (detector=(semiconductor=G.SSD.Region(bulk),contacts=[(geometry=G.SSD.Region(contact),)]),
        config_dict=config,weighting_potentials=fill(:fixture_only,34),electric_field=:fixture_only)
end
reset(mode=:complete)=(empty!(G.calls);G.mode[]=mode)
const SIM=simulation_fixture()

@testset "One response records all 34 signed channels; selected timing is unchanged" begin
    reset()
    row=K.injection(SIM,CFG,9,26,[1.,2.,0.],500.)
    @test length(G.calls)==1
    @test only(G.calls).ids==collect(1:34)
    @test row["signal_coverage"]==K.signal_coverage()
    @test row["signal_coverage"]["contact_ids"]==collect(1:34)
    @test row["signal_coverage"]["time_unit"]=="ns"
    @test row["signal_coverage"]["signal_unit"]=="keV"
    @test row["signal_coverage"]["polarity"]=="native_signed_before_wiring"
    @test [s["contact_id"] for s in row["channel_signals"]]==collect(1:34)
    for (id,s) in enumerate(row["channel_signals"])
        @test s["time_ns"]==collect(0.:5.)
        if id!=9 && id!=26
            @test s["signed_induced_keV"]==[0.,id/10,-id/20,id/40,0.,-id/80]
        end
    end
    @test row["signals"]["X"]==Dict(k=>row["channel_signals"][9][k] for k in ("time_ns","signed_induced_keV"))
    @test row["signals"]["Y"]==Dict(k=>row["channel_signals"][26][k] for k in ("time_ns","signed_induced_keV"))
    @test row["X_t50_ns"]==3.75 && row["Y_t50_ns"]==2.5 && row["ctd_ns"]==1.25
    @test row["X_final_induced_keV"]==500. && row["Y_final_induced_keV"]== -500.
    @test row["timing_method"]=="ideal_charge_last_rising_constant_fraction_terminal_v2"
    @test row["valid"] && row["status"]=="completed"
    reset(:incomplete)
    incomplete=K.injection(SIM,CFG,9,26,[1.,2.,0.],500.)
    @test !incomplete["valid"] && incomplete["ctd_ns"]===nothing
    @test incomplete["status"]=="incomplete_collection_or_timing"
    @test incomplete["signals"]==row["signals"] && incomplete["channel_signals"]==row["channel_signals"]
end

@testset "Geometry exclusions and native failures have null responses" begin
    for sim in (simulation_fixture(bulk=false),simulation_fixture(contact=true))
        reset()
        row=K.injection(sim,CFG,9,26,[1.,2.,0.],500.)
        @test row["status"]=="excluded_geometry" && !row["valid"]
        @test isempty(G.calls)
        @test all(row[k]===nothing for k in ("signals","channel_signals","signal_coverage","endpoints","ctd_ns"))
    end
    mktempdir(joinpath(G.ROOT,".local")) do folder
        for mode in (:known_failure,:unexpected_failure,:missing_channel)
            reset(mode);path=joinpath(folder,string(mode)*".json")
            if mode==:known_failure
                row,reused=K.checkpoint_injection(SIM,CFG,9,26,[1.,2.,0.],500.,path,"identity")
                @test !reused && row["status"]=="native_failed"
                original=read(path)
                again,reused=K.checkpoint_injection(SIM,CFG,9,26,[1.,2.,0.],500.,path,"identity")
                @test reused && row==again && read(path)==original
            else
                @test_throws (mode==:missing_channel ? ArgumentError : ErrorException) K.checkpoint_injection(SIM,CFG,9,26,[1.,2.,0.],500.,path,"identity")
            end
            row=K.read_record(path,"identity")
            @test length(G.calls)==1 && !row["valid"]
            @test all(row[k]===nothing for k in ("signals","channel_signals","signal_coverage","endpoints","ctd_ns","X_t50_ns","Y_t50_ns"))
        end
    end
end

@testset "Full34 checkpoints are hash-bound; selected-only originals are refused intact" begin
    reset()
    mktempdir(joinpath(G.ROOT,".local")) do folder
        path=joinpath(folder,"checkpoint.json")
        row,reused=K.checkpoint_injection(SIM,CFG,9,26,[1.,2.,0.],500.,path,"identity")
        @test !reused
        again,reused=K.checkpoint_injection(SIM,CFG,9,26,[1.,2.,0.],500.,path,"identity")
        @test reused && again==row && length(G.calls)==1
        @test_throws ArgumentError K.checkpoint_injection(SIM,CFG,9,26,[1.,2.,0.],500.,path,"changed identity")
        record=G.E.readjson(path);record["payload"]["channel_signals"][34]["signed_induced_keV"][2]=99.
        G.save(path,record)
        @test_throws ArgumentError K.read_record(path,"identity")
        for change in (:legacy,:missing,:duplicate,:wrong_units)
            altered=deepcopy(row)
            if change==:legacy
                delete!(altered,"channel_signals");delete!(altered,"signal_coverage")
            elseif change==:missing
                pop!(altered["channel_signals"])
            elseif change==:duplicate
                altered["channel_signals"][34]["contact_id"]=33
            else
                altered["signal_coverage"]["time_unit"]="us"
            end
            K.save_record(path,altered,"identity");before=read(path)
            @test_throws ArgumentError K.checkpoint_injection(SIM,CFG,9,26,[1.,2.,0.],500.,path,"identity")
            @test read(path)==before && length(G.calls)==1
        end
    end
end

@testset "New build identity declares full34 and binds the recording source" begin
    reset()
    mktempdir(joinpath(G.ROOT,".local")) do folder
        field=joinpath(folder,"fixture-field.txt");write(field,"not a field; software-only fixture")
        cache=Dict("ref"=>relpath(field,G.ROOT),"sha256"=>G.hashfile(field),"model_sha256"=>G.MODEL_HASH)
        channels=H.channel_metadata(SIM.config_dict);out=joinpath(folder,"new-calibration")
        result=K.build(SIM,CFG,channels,out;field_cache=cache,max_new_injections=1)
        @test result.status=="partial" && result.calibration===nothing && length(G.calls)==1
        identity=G.E.readjson(joinpath(out,"identity.json"));idsha=G.hashfile(joinpath(out,"identity.json"))
        @test identity["signal_coverage"]==K.signal_coverage()
        @test identity["source_sha256"]["gegi_pixel_calibration.jl"]==G.hashfile(joinpath(@__DIR__,"..","simulation","gegi_pixel_calibration.jl"))
        row=K.read_record(joinpath(out,"injections","9-26","z1.json"),idsha)
        @test row["signal_coverage"]==identity["signal_coverage"] && length(row["channel_signals"])==34
        old=deepcopy(identity);delete!(old,"signal_coverage");G.save(joinpath(out,"identity.json"),old)
        before=read(joinpath(out,"identity.json"))
        @test_throws ArgumentError K.build(SIM,CFG,channels,out;field_cache=cache,max_new_injections=1)
        @test read(joinpath(out,"identity.json"))==before && length(G.calls)==1
    end
end
