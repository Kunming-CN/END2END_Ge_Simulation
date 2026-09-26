# Configuration compatibility only; no detector or radiation solve.
using Test
include("verify_readout.jl")
@testset "sampling verifier census-only configuration" begin
    baseline=R.config(joinpath(@__DIR__,"readout_demo.json"))
    @test verification_config("",Dict("schema_version"=>1))==baseline
    mktempdir(joinpath(R.ROOT,".local")) do dir
        file=joinpath(dir,"readout-config.json")
        for n in (1,10,20,100,500)
            cfg=deepcopy(baseline);cfg["expected_primary_count"]=n
            R.save(file,cfg)
            binding=Dict("file"=>"readout-config.json","allowed_changed_fields"=>["expected_primary_count"],
                "baseline_sha256"=>R.hashfile(joinpath(@__DIR__,"readout_demo.json")),"effective_sha256"=>R.hashfile(file))
            manifest=Dict("schema_version"=>2,"readout_config"=>binding,
                "settings"=>Dict("events_per_model"=>n),"artifacts"=>Dict("readout-config.json"=>R.hashfile(file)))
            @test verification_config(dir,manifest)==cfg
            changed=deepcopy(cfg);changed["gain"]=99.0;R.save(file,changed)
            binding["effective_sha256"]=R.hashfile(file)
            manifest["artifacts"]["readout-config.json"]=R.hashfile(file)
            @test_throws ArgumentError verification_config(dir,manifest)
        end
    end
    @test_throws ArgumentError verification_config("",Dict("schema_version"=>3))
end
