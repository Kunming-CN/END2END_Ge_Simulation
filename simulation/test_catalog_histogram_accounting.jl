# Actual catalog initializer, event accounting and exporter call, without SSD.
# Usage: --project=simulation simulation/test_catalog_histogram_accounting.jl NEW_LOCAL_ROOT
using JSON, Test
include("readout.jl")
const ROOT=dirname(@__DIR__)
length(ARGS)==1 || error("Provide a new .local evidence output root")
out=abspath(ARGS[1]);rel=relpath(out,joinpath(ROOT,".local"))
(!startswith(rel,"..") && !isabspath(rel) && !ispath(out)) || error("Use a new .local evidence output root")
mkpath(out)
module Exporter
using ..Readout, JSON
const E=Readout;const R=Readout;const Q=(ROOT=dirname(@__DIR__),)
end
module CatalogAccounting
using ..Exporter
const NR=Exporter
end
function slice(source,start_text,stop_text)
    start=findfirst(start_text,source);stop=findfirst(stop_text,source)
    start!==nothing && stop!==nothing && Base.first(start)<Base.first(stop) || error("Actual accounting boundaries changed")
    source[Base.first(start):prevind(source,Base.first(stop))]
end
native=joinpath(@__DIR__,"native_response.jl");catalog=joinpath(@__DIR__,"catalog_native_response.jl")
Base.include_string(Exporter,slice(read(native,String),"function histogram_exact","function summary_html"),native)
source=read(catalog,String)
init=slice(source,"    counts=Dict{String,Any}(","    report=Dict{String,Any}(")
inc=slice(source,"            counts[\"initial_primaries\"]+=1","            NR.scalar!(sj,sc,Dict(\"record_kind\"=>\"decay\"")
call=strip(only(filter(x->startswith(strip(x),"NR.export_hist(out,hist,counts,"),split(source,'\n'))))
call=first(split(call,");append!"))*")"
Base.include_string(CatalogAccounting,"function initial(d)\n"*init*"\ncounts\nend\nfunction account!(counts,e,energy)\n"*inc*
    "\ncounts\nend\nfunction finish(out,hist,counts,a,d)\n"*call*"\nend",catalog)
presets=JSON.parsefile(joinpath(ROOT,"scenarios","source-presets.json"))["presets"]
hist=Dict("deposited_per_decay"=>Dict(200=>1,202=>1));records=Any[]
@testset "Actual catalog caller accounting and histogram export" begin
    for p in filter(x->get(x,"adapter",nothing)=="shared_decay_source_v1",presets), photons in (true,false)
        d=Dict("source_id"=>p["id"],"source_contract"=>p,"source_mode"=>"registered_decay")
        counts=Base.invokelatest(CatalogAccounting.initial,d)
        names=[x["name"] for x in p["diagnostic_lines"]]
        expected=Dict(name=>0 for name in names)
        for (index,energy) in enumerate((0.,10.))
            lines=Dict(name=>!photons ? 0 : index==1 ? (i==1 ? 2 : 1) : (i==1 ? 0 : 3)
                for (i,name) in enumerate(names))
            e=Dict("line_photon_counts"=>lines,"line_photon_count"=>sum(values(lines)),"decay_photon_count"=>sum(values(lines)))
            Base.invokelatest(CatalogAccounting.account!,counts,e,energy)
            for (name,n) in lines;expected[name]+=n;end
        end
        @test counts["initial_primaries"]==counts["initial_decays"]==2
        @test counts["zero_deposit_primaries"]==1
        @test counts["line_photon_counts"]==expected
        @test counts["line_photons"]==sum(values(expected))
        leaf=mkdir(joinpath(out,p["id"]*(photons ? "-photons" : "-zero-photons")))
        Base.invokelatest(CatalogAccounting.finish,leaf,hist,counts,(calibration=nothing,),d)
        h=JSON.parsefile(joinpath(leaf,"histograms.json"))
        @test h["schema_version"]==2
        @test h["normalization"]["source_id"]==p["id"]
        @test h["normalization_denominators"]==counts
        @test all(isequal(row["per_emitted_diagnostic_window_photon"],photons ? row["count"]/sum(values(expected)) : nothing) for row in h["bins"])
        @test occursin("per_emitted_diagnostic_window_photon",read(joinpath(leaf,"histograms.csv"),String))
        push!(records,Dict("source_id"=>p["id"],"directory"=>basename(leaf),"counts"=>counts,
            "histogram_sha256"=>Readout.hashfile(joinpath(leaf,"histograms.json")),"csv_sha256"=>Readout.hashfile(joinpath(leaf,"histograms.csv"))))
    end
    cs=only(filter(x->x["id"]=="cs137_point_decay_v1",presets))
    d=Dict("source_id"=>cs["id"],"source_contract"=>cs,"source_mode"=>"cs137_legacy")
    counts=Base.invokelatest(CatalogAccounting.initial,d)
    original_keys=Set(("initial_primaries","initial_decays","zero_deposit_primaries","groups","accepted","rejected",
        "readout_rejected","native_failed_groups","saturated","native_charge_samples","analog_samples","line_photons","decay_photons"))
    @test Set(keys(counts))==original_keys
    for (energy,n) in ((0.,2),(10.,4))
        Base.invokelatest(CatalogAccounting.account!,counts,Dict("line_photon_count"=>n,"decay_photon_count"=>n),energy)
    end
    @test Set(keys(counts))==original_keys
    @test counts["line_photons"]==6
    @test counts["initial_primaries"]==2 && counts["zero_deposit_primaries"]==1
    leaf=mkdir(joinpath(out,"cs137"));Base.invokelatest(CatalogAccounting.finish,leaf,hist,counts,(calibration=nothing,),d)
    h=JSON.parsefile(joinpath(leaf,"histograms.json"))
    @test !haskey(h,"schema_version") && !haskey(h,"normalization")
    @test all(haskey(row,"per_emitted_660_663_keV_photon") for row in h["bins"])
    @test occursin("per_emitted_660_663_keV_photon",read(joinpath(leaf,"histograms.csv"),String))
    push!(records,Dict("source_id"=>cs["id"],"directory"=>basename(leaf),"counts"=>counts))
end
Readout.save(joinpath(out,"COMPLETE.json"),Dict("kind"=>"actual_catalog_accounting_export_check_v1","status"=>"complete",
    "scope"=>"actual catalog initializer, per-event counts and exporter call; existing Readout serialization; no SSD or science calculation",
    "science_calls"=>0,"julia_version"=>string(VERSION),"records"=>records,
    "source_sha256"=>Dict("simulation/catalog_native_response.jl"=>Readout.hashfile(catalog),
        "simulation/native_response.jl"=>Readout.hashfile(native),"simulation/readout.jl"=>Readout.hashfile(joinpath(@__DIR__,"readout.jl")),
        "simulation/test_catalog_histogram_accounting.jl"=>Readout.hashfile(@__FILE__))))
