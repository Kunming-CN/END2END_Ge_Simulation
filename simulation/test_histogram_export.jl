# Execute only actual exporter function bodies, with the existing Readout JSON/CSV
# utilities. No SSD module, geometry, field, transport or electronics is loaded.
# Args: exact legacy native_response.jl snapshot, NEW .local evidence output root.
using JSON, SHA, Test
include("readout.jl")
const ROOT=dirname(@__DIR__)
const LEGACY_SHA="814417d83d696c0cac51f4cb39fd1fd461989e93e90ca9e0b3e12ea9f07b7077"
length(ARGS)==2 || error("Provide the preserved legacy source snapshot and a new .local output root")
legacy_path=abspath(ARGS[1]);out=abspath(ARGS[2])
Readout.hashfile(legacy_path)==LEGACY_SHA || error("Wrong legacy exporter snapshot")
rel=relpath(out,joinpath(ROOT,".local"))
(!startswith(rel,"..") && !isabspath(rel) && !ispath(out)) || error("Use a new .local evidence output root")
mkpath(out)

module CurrentExporter
using ..Readout, JSON
const E=Readout;const R=Readout;const Q=(ROOT=dirname(@__DIR__),)
end
module LegacyExporter
using ..Readout, JSON
const E=Readout;const R=Readout
end
function functions(source,first)
    start=findfirst(first,source);stop=findfirst("function summary_html",source)
    start!==nothing && stop!==nothing || error("Exporter function boundaries changed")
    source[Base.first(start):prevind(source,Base.first(stop))]
end
current_path=joinpath(@__DIR__,"native_response.jl")
Base.include_string(CurrentExporter,functions(read(current_path,String),"function histogram_exact"),current_path)
Base.include_string(LegacyExporter,functions(read(legacy_path,String),"function export_hist"),legacy_path)
hist=Dict("deposited_per_decay"=>Dict(-1=>1,211=>2,1000=>2),"accepted_peak_ADC"=>Dict(211=>2))
counts=Dict{String,Any}("initial_primaries"=>5,"initial_decays"=>5,"line_photons"=>7,"accepted"=>2)
registry=JSON.parsefile(joinpath(ROOT,"scenarios","source-presets.json"))
presets=filter(p->get(p,"adapter",nothing)=="shared_decay_source_v1",registry["presets"])
checks=Dict{String,Any}()
@testset "Actual exporter: legacy byte identity and registered diagnostics" begin
    for (label,c) in (("cs137",counts),("zero_photons",merge(counts,Dict("line_photons"=>0,"accepted"=>0))),
                      ("unknown_gamma",merge(counts,Dict("initial_decays"=>nothing,"line_photons"=>nothing,"accepted"=>0))))
        old=mkdir(joinpath(out,label*"-legacy"));new=mkdir(joinpath(out,label*"-current"))
        LegacyExporter.export_hist(old,hist,c,nothing)
        CurrentExporter.export_hist(new,hist,c,nothing)
        for file in ("histograms.json","histograms.csv")
            @test read(joinpath(old,file))==read(joinpath(new,file))
        end
        checks[label]=Dict(file=>Readout.hashfile(joinpath(new,file)) for file in ("histograms.json","histograms.csv"))
    end
    # Explicit Cs metadata remains exactly identical to the default contract.
    cs=only(filter(p->p["id"]=="cs137_point_decay_v1",registry["presets"]))
    explicit=mkdir(joinpath(out,"explicit-cs137"))
    CurrentExporter.export_hist(explicit,hist,counts,nothing;source_id=cs["id"],source_contract=cs)
    for file in ("histograms.json","histograms.csv")
        @test read(joinpath(explicit,file))==read(joinpath(out,"cs137-legacy",file))
    end
    for p in presets, line_count in (7,0)
        leaf=mkdir(joinpath(out,p["id"]*"-"*string(line_count)))
        lines=Dict(x["name"]=>i==1 ? line_count : 0 for (i,x) in enumerate(p["diagnostic_lines"]))
        c=merge(counts,Dict("line_photons"=>line_count,"line_photon_counts"=>lines,"accepted"=>line_count==0 ? 0 : 2))
        CurrentExporter.export_hist(leaf,hist,c,nothing;source_id=p["id"],source_contract=p)
        h=JSON.parsefile(joinpath(leaf,"histograms.json"));normal=h["normalization"]
        @test h["schema_version"]==2
        @test normal["source_id"]==p["id"]
        @test normal["diagnostic_lines"]==p["diagnostic_lines"]
        @test normal["window_interval"]=="closed [lower, upper] keV"
        @test normal["aggregation"]=="sum_of_named_window_photon_counts"
        @test normal["source_registry_sha256"]==Readout.hashfile(joinpath(ROOT,"scenarios","source-presets.json"))
        @test all(!haskey(r,"per_emitted_660_663_keV_photon") for r in h["bins"])
        @test all(isequal(r["per_emitted_diagnostic_window_photon"],line_count==0 ? nothing : r["count"]/line_count) for r in h["bins"])
        @test !occursin("per_emitted_660_663_keV_photon",read(joinpath(leaf,"histograms.csv"),String))
        @test occursin("per_emitted_diagnostic_window_photon",read(joinpath(leaf,"histograms.csv"),String))
        changed=deepcopy(p);changed["diagnostic_lines"][1]["window_keV"][1]=660
        @test_throws ArgumentError CurrentExporter.histogram_normalization(p["id"],changed)
        bad=deepcopy(c);bad["line_photons"]+=1
        @test_throws ArgumentError CurrentExporter.export_hist(leaf,hist,bad,nothing;source_id=p["id"],source_contract=p)
        checks[basename(leaf)]=Dict(file=>Readout.hashfile(joinpath(leaf,file)) for file in ("histograms.json","histograms.csv"))
    end
    for ref in ("native_response.jl","batch_native_response.jl","catalog_native_response.jl","workflow_ring_response.jl")
        parsed=Meta.parseall(read(joinpath(@__DIR__,ref),String))
        @test !any(x->x isa Expr && x.head in (:error,:incomplete),parsed.args)
    end
end
Readout.save(joinpath(out,"COMPLETE.json"),Dict("kind"=>"actual_histogram_exporter_check_v1","status"=>"complete",
    "scope"=>"actual source function bodies and Readout serialization; no SSD or science calculation",
    "julia_version"=>string(VERSION),"science_calls"=>0,"legacy_source_sha256"=>LEGACY_SHA,
    "source_sha256"=>Dict("simulation/native_response.jl"=>Readout.hashfile(current_path),
        "simulation/readout.jl"=>Readout.hashfile(joinpath(@__DIR__,"readout.jl")),
        "simulation/test_histogram_export.jl"=>Readout.hashfile(@__FILE__)),"checks"=>checks))
