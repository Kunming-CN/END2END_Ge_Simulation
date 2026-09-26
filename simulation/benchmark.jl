# Six fresh solves: one warm-up and two measured repeats per backend. No saved fields.
isdefined(@__MODULE__, :SSDQuickstart) || include("run.jl")
module SSDBenchmark
using ..SSDQuickstart
const Q = SSDQuickstart

# Fixed, prospective acceptance gates, not fitted to a particular GPU result.
# Potentials use bias (V) or unity (weighting); fields use peak CPU magnitude (V/m).
const GATES = Dict("electric_potential" => (max=1e-5, rms=3e-6),
    "weighting_potential" => (max=1e-5, rms=3e-6),
    "electric_field" => (max=1e-3, rms=1e-4),
    "waveform_fraction" => (max=1e-3, rms=2e-4))
const END_GATE = 1e-4

function differences(a, b, scale, gate)
    length(a) == length(b) || error("Comparison lengths differ.")
    delta = Float64.(a) .- Float64.(b)
    finite = !isempty(delta) && all(isfinite, delta) && isfinite(scale) && scale > 0
    maximum_error = finite ? maximum(abs, delta) : nothing
    rms_error = finite ? sqrt(sum(abs2, delta) / length(delta)) : nothing
    Dict("max_absolute" => maximum_error, "rms_absolute" => rms_error, "normalization_scale" => scale,
        "max_scaled_limit" => gate.max, "rms_scaled_limit" => gate.rms,
        "passed" => finite && maximum_error <= gate.max*scale && rms_error <= gate.rms*scale)
end
grid_info(grid) = Dict("type" => string(typeof(grid)), "ticks" => [Float64.(collect(a)) for a in grid.axes])
function compare_field(a, b, scale, gate; vectors=false)
    ga, gb = grid_info(a.grid), grid_info(b.grid)
    # Exact ticks, coordinate system and boundary metadata; never compare mismatched indices.
    matches = ga == gb && NamedTuple(a.grid) == NamedTuple(b.grid)
    if !matches
        return Dict("grid_matches" => false, "cpu_grid" => ga, "cuda_grid" => gb,
            "passed" => false, "reason" => "Different grids: elementwise comparison skipped; agreement unestablished.")
    end
    av = vectors ? [Float64(x) for v in a.data for x in v] : vec(a.data)
    bv = vectors ? [Float64(x) for v in b.data for x in v] : vec(b.data)
    merge(differences(av, bv, scale, gate), Dict("grid_matches" => true, "grid" => ga))
end

# Linear interpolation on the shared overlap only; no tail extrapolation or normalization.
function interpolate(times, values, common)
    [begin
        i = searchsortedlast(times, t)
        if i == length(times)
            values[end]
        else
            f = (t - times[i]) / (times[i+1] - times[i])
            (1-f)*values[i] + f*values[i+1]
        end
    end for t in common]
end
function compare_runs(cpu, gpu, cfg)
    sim = cpu.sim
    bias = maximum(c.potential for c in sim.detector.contacts) - minimum(c.potential for c in sim.detector.contacts)
    ep_scale = iszero(bias) ? max(maximum(abs, sim.electric_potential.data), eps(Float32)) : abs(bias)
    field_scale = max(maximum(v -> sqrt(sum(abs2, v)), sim.electric_field.data), eps(Float32))
    result = Dict{String,Any}(
        "electric_potential" => compare_field(sim.electric_potential, gpu.sim.electric_potential, ep_scale, GATES["electric_potential"]),
        "weighting_potential" => compare_field(sim.weighting_potentials[cfg.contact], gpu.sim.weighting_potentials[cfg.contact], 1.0, GATES["weighting_potential"]),
        "electric_field" => compare_field(sim.electric_field, gpu.sim.electric_field, field_scale, GATES["electric_field"]; vectors=true))
    lo, hi = max(first(cpu.time), first(gpu.time)), min(last(cpu.time), last(gpu.time))
    common = collect(lo:cfg.dt:hi)
    length(common) >= 2 || error("Insufficient waveform overlap for comparison.")
    result["waveform_fraction"] = differences(interpolate(cpu.time, cpu.fraction, common),
        interpolate(gpu.time, gpu.fraction, common), 1.0, GATES["waveform_fraction"])
    result["common_time_grid"] = Dict("start_ns" => first(common), "end_ns" => last(common), "step_ns" => cfg.dt,
        "samples" => length(common), "method" => "Linear interpolation on overlapping support; no extension of shorter waveform.",
        "cpu_end_ns" => last(cpu.time), "cuda_end_ns" => last(gpu.time))
    end_difference = abs(last(cpu.fraction) - last(gpu.fraction))
    endpoint_signature(r) = [(e["species"], e["contact_ids"], e["step_limit_reached"], e["status"]) for e in r.report["endpoints"]]
    result["end_charge"] = Dict("cpu_fraction" => last(cpu.fraction), "cuda_fraction" => last(gpu.fraction),
        "cpu_induced_equivalent_energy_keV" => last(cpu.equivalent), "cuda_induced_equivalent_energy_keV" => last(gpu.equivalent),
        "absolute_fraction_difference" => end_difference, "limit" => END_GATE,
        "passed" => end_difference <= END_GATE)
    result["endpoint_status_matches"] = endpoint_signature(cpu) == endpoint_signature(gpu)
    result["duration_matches_within_one_step"] = abs(last(cpu.time) - last(gpu.time)) <= cfg.dt
    result["passed"] = all(result[name]["passed"] for name in keys(GATES)) && result["end_charge"]["passed"] &&
        result["endpoint_status_matches"] && result["duration_matches_within_one_step"]
    result
end

function benchmark(cfg, cpu_backend, gpu_backend, output, setup_s)
    report = Dict{String,Any}("status" => "running", "runs" => Any[], "comparisons" => Any[],
        "backend_setup_seconds" => setup_s, "hardware" => merge(Dict("cpu" => Sys.CPU_NAME,
            "julia_threads" => Q.Threads.nthreads(), "solver_thread_limit" => cfg.threads), gpu_backend.metadata),
        "environment" => Q.environment("cuda"),
        "timing_scope" => "One first-call warm-up per backend, then two repeats; fresh Simulation each time. GPU synchronized around stages. Startup/package import excluded; setup separately recorded. Cold is process-local, not a cleared disk/kernel cache.",
        "threshold_scope" => "Prospective numerical parity gates, not grid convergence or agreement with experiment.")
    file = joinpath(output, "benchmark.json")
    try
        # Each round pairs identical parameters. The first pair warms both complete paths.
        for round in 0:2
            pair = Any[]
            for (device, backend) in (("cpu", cpu_backend), ("cuda", gpu_backend))
                println("Starting ", round == 0 ? "warm-up" : "repeat $round", " ", device, " for ", cfg.model, "...")
                local_cfg = merge(cfg, (device=device,))
                backend.synchronize()
                started = time_ns()
                result = Q.run_case(local_cfg, backend) # Constructs a fresh Simulation.
                backend.synchronize()
                result.report["timings"]["fresh_run_wall_seconds"] = (time_ns() - started)/1e9
                push!(report["runs"], Dict("phase" => round == 0 ? "cold_warmup" : "warm_repeat", "repeat" => round,
                    "run" => result.report))
                push!(pair, result)
                println(round == 0 ? "Warm-up" : "Repeat $round", " ", device, " completed.")
            end
            comparison = compare_runs(pair[1], pair[2], cfg)
            comparison["repeat"] = round
            push!(report["comparisons"], comparison)
            Q.save_json(file, report)
        end
        warm = filter(r -> r["phase"] == "warm_repeat", report["runs"])
        report["warm_speed_ratios_cpu_over_cuda"] = Dict(key => begin
            cpu = [r["run"]["timings"][key] for r in warm if r["run"]["device"] == "cpu"]
            gpu = [r["run"]["timings"][key] for r in warm if r["run"]["device"] == "cuda"]
            Dict("cpu_mean_seconds" => sum(cpu)/2, "cuda_mean_seconds" => sum(gpu)/2,
                "ratio" => sum(cpu)/sum(gpu), "paired_ratios" => cpu ./ gpu)
        end for key in ("potential_solve_seconds", "fresh_run_wall_seconds"))
        report["status"] = all(c["passed"] for c in report["comparisons"]) ? "passed" : "failed_comparison"
    catch err
        report["status"] = "failed_execution"
        report["error"] = sprint(showerror, err)
        rethrow()
    finally
        Q.save_json(file, report)
    end
    println("Benchmark report: ", file)
    report["status"] == "passed" || error("CPU/CUDA comparison failed; inspect benchmark.json (including possible grid mismatch).")
end
function main(args=ARGS)
    cfg = Q.parse_args(args; default_output=joinpath(Q.ROOT, ".local", "ssd-benchmark"))
    if cfg.action == :help
        println("benchmark.jl uses run.jl options; always compares CPU and CUDA in the GPU project.")
        println("BEGe default, Bipolar at 0,0,4.75 mm, or GeGI at 0,0,0 mm; one warm-up + two repeats each.")
        return print(Q.HELP)
    end
    cfg.action == :run || throw(ArgumentError("Use run.jl for model inspection."))
    (cfg.model == Q.MODEL_ID && cfg.position == (12.0, 5.0, 18.0) ||
        cfg.model == "Bipolar_reference_3D" && cfg.position == (0.0, 0.0, 4.75) ||
        cfg.model == "GeGI_3D" && cfg.position == (0.0, 0.0, 0.0)) ||
        throw(ArgumentError("Benchmark accepts only the documented BEGe, Bipolar or GeGI point."))
    cfg.min_grid >= 0.25 && cfg.max_grid >= 2 && cfg.max_steps <= 20000 ||
        throw(ArgumentError("Benchmark requires min grid >= 0.25 mm, max grid >= 2 mm, max steps <= 20000."))
    cfg.model == "GeGI_3D" && cfg.min_grid < 0.5 &&
        throw(ArgumentError("The bounded GeGI benchmark requires --min-grid-mm >= 0.5."))
    Q.environment("cuda")
    Q.prepare_simulation(cfg) # Geometry validation before CUDA initialization or any field solve.
    started = time_ns()
    cpu, gpu = Q.prepare_backend("cpu"), Q.prepare_backend("cuda")
    setup_s = (time_ns() - started)/1e9
    output = Q.reserve_output(cfg.output)
    Base.invokelatest(benchmark, cfg, cpu, gpu, output, setup_s)
end
end

if abspath(PROGRAM_FILE) == @__FILE__
    SSDBenchmark.main()
end
