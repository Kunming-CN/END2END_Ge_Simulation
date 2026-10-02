include("ring_stream.jl")
using .RingStream, Test, JSON, SHA
const RS=RingStream
root=dirname(@__DIR__)
@testset "Frozen rings and independently authorized Li delta" begin
    for (id,leaf) in (("GeRC02","geometry-GeRC02-corrected"),("KMRC01_candidate","geometry-KMRC01_candidate"))
        path=joinpath(root,".local/ring-delivery-v1",leaf,"prepared.json")
        meta=JSON.parsefile(path);c=meta["model_contract"];pins=Dict{String,String}()
        effective=RS.model_contract(c,pins)
        @test isfile(effective)
        @test RS.S.hashfile(effective)==c["effective_model_sha256"]
        @test c["source_model_sha256"]==RS.MODEL_PINS[id]
        @test all(RS.S.hashfile(p)==h for (p,h) in pins)
        for (key,value) in (("runtime_temperature_K",78),("stored_temperature_K",77),("readout_contact_id",2),("geometry_unchanged",false),("effective_model_sha256","0"^64))
            forged=deepcopy(c);forged[key]=value
            @test_throws ArgumentError RS.model_contract(forged)
        end
        forged=deepcopy(c);forged["contact_potentials_V"]["2"]*=-1
        @test_throws ArgumentError RS.model_contract(forged)
        if id=="GeRC02"
            @test c["effective_model_sha256"]=="13c5df22b4ce9134277dc6da04e03720dec3ca278bc8cd11866370abbee3ba44"
            forged=deepcopy(c);forged["annealing_time_minutes"]=30
            @test_throws ArgumentError RS.model_contract(forged)
            # A fresh hash cannot authorize a bias edit in the Li-time-only variant.
            fixture=joinpath(root,".local/ring-delivery-v1/forged-model-fixture")
            mkpath(fixture);bad=joinpath(fixture,"GeRC02-bias-edit.yaml")
            body=replace(read(effective,String),"potential: 240"=>"potential: 241";count=1)
            if isfile(bad)
                @test read(bad,String)==body
            else
                open(io->write(io,body),bad,"w")
            end
            forged=deepcopy(c);forged["effective_model_ref"]=replace(relpath(bad,root),'\\'=>'/');forged["effective_model_sha256"]=RS.S.hashfile(bad)
            @test_throws ArgumentError RS.model_contract(forged)
        else
            @test c["effective_model_sha256"]==c["source_model_sha256"]
            @test c["model_delta"]===nothing
            forged=deepcopy(c);forged["variant_id"]="KMRC01_Li50min"
            @test_throws ArgumentError RS.model_contract(forged)
        end
    end
end
if "--parse-native" in ARGS
    @testset "Additive native adapter parses" begin
        clean(x)=!(x isa Expr) || (!(x.head in (:error,:incomplete)) && all(clean,x.args))
        @test clean(Meta.parseall(read(joinpath(@__DIR__,"ring_response.jl"),String)))
    end
end
