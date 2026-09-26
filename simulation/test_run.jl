using Test
include("run.jl")
const Q = SSDQuickstart

@testset "inspection and parser" begin
    @test Q.parse_args(["--help"]).action == :help
    @test Q.parse_args(["--list-models"]).action == Symbol("list-models")
    @test Q.parse_args(["--check-models"]).action == Symbol("check-models")
    @test all(occursin("--" * name, Q.HELP) for name in ("model", "device", "position-mm", "energy-kev", "contact",
        "dt-ns", "max-steps", "threads", "min-grid-mm", "max-grid-mm", "output"))
    output = joinpath(Q.ROOT, ".local", "unit-parser-unused-output")
    base = ["--output", output]
    cfg = Q.parse_args(base)
    @test (cfg.model, cfg.device, cfg.position, cfg.energy, cfg.contact, cfg.dt, cfg.max_steps) ==
        (Q.MODEL_ID, "cpu", (12.0,5.0,18.0), 662.0, 1, 2.0, 20000)
    @test Q.parse_args(vcat(base, ["--device", "cuda"])).device == "cuda"
    for entry in Q.catalog()["detectors"]
        parsed = Q.parse_args(vcat(base, ["--model", entry["id"], "--position-mm", "0,0,4.75"]))
        @test parsed.model == entry["id"]
        @test parsed.contact == entry["readout_contact_id"]
    end
    for bad in (["--wat"], ["--help", "x"], ["--device", "metal"], ["--model", "missing"],
        ["--model", "Bipolar_reference_3D"], ["--position-mm", "1,2"], ["--position-mm", "NaN,0,0"],
        ["--position-mm", "1e100,0,0"], ["--precision", "16"], ["--precision", "33"], ["--contact", "0"], ["--contact", "99999"],
        ["--dt-ns", "Inf"], ["--dt-ns", "0"], ["--dt-ns", "1e-100"], ["--energy-kev", "-1"],
        ["--energy-kev", "no"], ["--energy-kev", "NaN"], ["--max-steps", "1"], ["--max-steps", "1000001"],
        ["--max-steps", "2.5"], ["--max-iterations", "0"], ["--max-iterations", "50001"], ["--threads", "0"], ["--threads", string(Threads.nthreads()+1)],
        ["--min-grid-mm", "0"], ["--max-grid-mm", "-1"], ["--min-grid-mm", "3", "--max-grid-mm", "2"],
        ["--device", "cpu", "--device", "cuda"])
        @test_throws ArgumentError Q.parse_args(vcat(base, bad))
    end
    @test length(Q.environment("cpu")["environment_manifest_sha256"]) == 64
    @test !isdefined(Q, :CUDA)
end

@testset "protected output (no writes)" begin
    for path in (Q.ROOT, joinpath(Q.ROOT, ".local"), joinpath(Q.ROOT, "models", "new"),
        joinpath(Q.ROOT, "simulation", "new"), joinpath(Q.ROOT, "tools", "new"),
        joinpath(Q.ROOT, "docs", "new"), joinpath(Q.ROOT, ".local", "..", "simulation", "new"),
        joinpath(dirname(Q.ROOT), "outside"), joinpath(Q.ROOT, ".local", "quickstart"), "")
        # Existing baseline is optional on a clean checkout.
        path == Q.OUTPUT && !ispath(path) && continue
        @test_throws ArgumentError Q.validate_output(path)
    end
    @test Q.validate_output(joinpath(Q.ROOT, ".local", "unit-parser-unused-output")) ==
        joinpath(Q.ROOT, ".local", "unit-parser-unused-output")
    @test !Q.childof(joinpath(Q.ROOT, ".local-other", "x"), joinpath(Q.ROOT, ".local"))
end

@testset "geometry validation without solves" begin
    base = ["--output", joinpath(Q.ROOT, ".local", "unit-parser-unused-output")]
    cfg = Q.parse_args(base)
    sim, point, entry = Q.prepare_simulation(cfg)
    @test point in sim.detector.semiconductor
    @test ismissing(sim.electric_potential)
    @test entry["id"] == Q.MODEL_ID
    @test_throws ArgumentError Q.prepare_simulation(merge(cfg, (position=(1e4,1e4,1e4),)))
    # The reference point contact spans r=0..7.5 mm, z=0 at the lower face.
    @test_throws ArgumentError Q.prepare_simulation(merge(cfg, (position=(0.0,0.0,0.0),)))
end

# Benchmark syntax is loaded without invoking its main or importing CUDA.
include("benchmark.jl")
@test !isdefined(SSDBenchmark.Q, :CUDA)
