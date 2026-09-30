# Existing-host tests of the additive worker; no SSD, transport or production.
using Test
include("replay_readout.jl")
@testset "Saved numeric CSV and loaded runtime" begin
    @test signal_fields("213,213,0,2.0,-1e-3")==["213","213","0","2.0","-1e-3"]
    @test signal_fields("\"213\",\"213\",\"0\",\"2.0\",\"-1e-3\"")==["213","213","0","2.0","-1e-3"]
    @test signal_fields("\"213\",213,\"0\",2.0,\"-1e-3\"")==["213","213","0","2.0","-1e-3"]
    @test signal_fields("0,0,0,0,0")==["0","0","0","0","0"]
    for bad in ("1,1,0,0", "1,1,0,0,0,0", "1.0,1,0,0,0", "-1,1,0,0,0", "01,1,0,0,0",
                "\"1,1,0,0,0", "1\",1,0,0,0", "\"\"1\"\",1,0,0,0", "\"\",1,0,0,0")
        @test_throws ArgumentError signal_fields(bad)
    end
    env=runtime()
    @test env isa Dict{String,Any}
    @test env["julia_version"]=="1.13.0"
    @test env["json_version"]=="1.9.0"
    @test env["ssd_loaded"]===false
    @test env["threads"]==2
    @test env["process_line"] isa Integer
    @test Set(keys(env["source_sha256"]))==Set(("readout.jl","readout_profiles.jl","readout_demo.json","replay_readout.jl"))
    @test realpath(env["active_project"])==realpath(joinpath(@__DIR__,"Project.toml"))
end
