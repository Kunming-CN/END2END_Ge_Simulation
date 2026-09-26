"""CPU-only SSD quickstart. No private caches, CUDA, ParaView, or Geant4 required."""
module SSDQuickstart
using Dates, JSON, SHA, SolidStateDetectors, TOML, Unitful
const SSD = SolidStateDetectors
const ROOT = normpath(joinpath(@__DIR__, ".."))
const MODEL_ID = "BEGe_GD32B_reference"
const MODEL_DIR = joinpath(ROOT, "models")
const OUTPUT = joinpath(ROOT, ".local", "quickstart")

sha256file(file) = bytes2hex(sha256(read(file)))
function save_json(file, value)
    open(file, "w") do io
        JSON.print(io, value, 2)
        println(io)
    end
end

function verify_model_files()
    catalog = JSON.parsefile(joinpath(MODEL_DIR, "catalog.json"))
    for entry in catalog["detectors"]
        file = joinpath(MODEL_DIR, entry["model"])
        sha256file(file) == entry["model_sha256"] || error("Model checksum mismatch: " * entry["id"])
    end
    for dependency in catalog["dependencies"]
        file = joinpath(MODEL_DIR, dependency["path"])
        sha256file(file) == dependency["sha256"] || error("Include checksum mismatch: " * dependency["path"])
    end
    return catalog
end

function check_models()
    catalog = verify_model_files()
    files = [joinpath(MODEL_DIR, entry["model"]) for entry in catalog["detectors"]]
    results = Any[]
    for file in files
        sim = Simulation{Float32}(file)
        push!(results, Dict("model" => basename(file), "sha256" => sha256file(file),
            "contacts" => length(sim.detector.contacts), "status" => "parsed"))
        println(basename(file), ": parsed, ", length(sim.detector.contacts), " contacts")
    end
    return Dict("julia" => string(VERSION), "ssd" => string(pkgversion(SSD)),
        "scope" => "Model construction only; not a field solve or convergence test", "models" => results)
end

function solve_fields!(sim)
    options = (device_array_type=Array, use_nthreads=min(2, Threads.nthreads()),
        depletion_handling=true, convergence_limit=1e-6,
        refinement_limits=[0.2, 0.1, 0.05], min_tick_distance=0.25u"mm",
        max_tick_distance=2u"mm", max_n_iterations=10000,
        n_iterations_between_checks=250, verbose=false)
    calculate_electric_potential!(sim; options...)
    electric_update = SSD.update_till_convergence!(sim, SSD.ElectricPotential, 1e-6;
        device_array_type=Array, depletion_handling=true, max_n_iterations=3000,
        n_iterations_between_checks=250, verbose=false)
    bias = maximum(c.potential for c in sim.detector.contacts) -
           minimum(c.potential for c in sim.detector.contacts)
    isfinite(electric_update) && electric_update <= bias * 1e-6 ||
        error("Electric-potential iteration tolerance not reached.")
    calculate_electric_field!(sim; n_points_in_φ=36)
    calculate_weighting_potential!(sim, 1; options...)
    weighting_update = SSD.update_till_convergence!(sim, SSD.WeightingPotential, 1, 1e-6;
        device_array_type=Array, depletion_handling=true, max_n_iterations=3000,
        n_iterations_between_checks=250, verbose=false)
    isfinite(weighting_update) && weighting_update <= 1e-6 ||
        error("Weighting-potential iteration tolerance not reached.")
    return Dict("electric_last_update_V" => electric_update,
        "weighting_last_update" => weighting_update, "relative_tolerance" => 1e-6,
        "electric_grid" => collect(size(sim.electric_potential.data)),
        "weighting_grid" => collect(size(sim.weighting_potentials[1].data)),
        "min_tick_distance_mm" => 0.25, "refinement_limits" => [0.2, 0.1, 0.05],
        "note" => "Iteration checks only; no grid-convergence claim")
end

function save_waveform_svg(file, time_ns, charge_fraction)
    tmax = maximum(time_ns)
    tmax > 0 || error("The waveform has no time interval.")
    ymin, ymax = min(0.0, minimum(charge_fraction)), max(1.0, maximum(charge_fraction))
    points = join((string(70 + 790 * t / tmax, ",",
        295 - 225 * (q - ymin) / (ymax - ymin)) for (t, q) in zip(time_ns, charge_fraction)), " ")
    open(file, "w") do io
        println(io, "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 900 360\">")
        println(io, "<rect width=\"900\" height=\"360\" fill=\"white\"/>")
        println(io, "<g font-family=\"sans-serif\" font-size=\"15\" fill=\"black\">")
        println(io, "<text x=\"70\" y=\"28\">BEGe reference: CPU quickstart electrode signal</text>")
        println(io, "<text x=\"70\" y=\"52\">Synthetic 662 keV deposit; not a reconstructed energy spectrum</text>")
        println(io, "<path d=\"M70 65 V295 H860\" stroke=\"black\" fill=\"none\"/>")
        println(io, "<polyline points=\"$points\" fill=\"none\" stroke=\"black\" stroke-width=\"2\"/>")
        for fraction in (0.0, 0.5, 1.0)
            println(io, "<text x=\"$(70 + 790fraction)\" y=\"318\" text-anchor=\"middle\">$(round(tmax * fraction; digits=1))</text>")
            println(io, "<text x=\"58\" y=\"$(300 - 225fraction)\" text-anchor=\"end\">$(round(ymin + fraction * (ymax - ymin); digits=2))</text>")
        end
        println(io, "<text x=\"460\" y=\"346\" text-anchor=\"middle\">Time (ns)</text>")
        println(io, "<text transform=\"translate(18 180) rotate(-90)\" text-anchor=\"middle\">Signed induced charge fraction</text></g></svg>")
    end
end

function run_demo(output)
    ispath(output) && error("Output already exists: $output. Choose a new --output directory.")
    verify_model_files()
    model = joinpath(MODEL_DIR, MODEL_ID * ".yaml")
    model_hash = sha256file(model)
    started = time()
    sim = Simulation{Float32}(model)
    println("Solving ", MODEL_ID, " from YAML on CPU (no field cache)...")
    solver = solve_fields!(sim)
    point = CartesianPoint{Float32}(0.012, 0.005, 0.018) # metres: (12, 5, 18) mm
    point in sim.detector.semiconductor || error("The configured deposit is outside Ge.")
    event = Event([point], [662.0u"keV"])
    drift_charges!(event, sim; Δt=2u"ns", max_nsteps=20000,
        geometry_check=true, diffusion=false, self_repulsion=false, verbose=false)
    SSD.get_signal!(event, sim, 1; Δt=2u"ns", signal_unit=u"keV")
    waveform = event.waveforms[1]
    time_ns = Float64.(ustrip.(u"ns", waveform.time))
    equivalent_keV = Float64.(ustrip.(u"keV", waveform.signal))
    fraction = equivalent_keV ./ 662.0
    length(time_ns) > 2 && all(diff(time_ns) .> 0) || error("Invalid waveform times.")
    all(isfinite, equivalent_keV) || error("Non-finite signal.")
    0.98 <= abs(last(fraction)) <= 1.02 || error("Full-charge smoke check failed; inspect fields/transport.")
    endpoints = [Dict("species" => species, "samples" => length(trajectory),
        "contact_ids" => [c.id for c in sim.detector.contacts if last(trajectory) in c.geometry])
        for drift in event.drift_paths for (species, trajectory) in
            (("electron", drift.e_path), ("hole", drift.h_path))]
    all(endpoint["samples"] < 20000 for endpoint in endpoints) || error("Drift step limit reached.")
    sha256file(model) == model_hash || error("Model changed during the run.")
    mkpath(output)
    open(joinpath(output, "signal.csv"), "w") do io
        println(io, "time_ns,induced_equivalent_energy_keV,signed_charge_fraction")
        for row in zip(time_ns, equivalent_keV, fraction)
            println(io, join(row, ','))
        end
    end
    save_waveform_svg(joinpath(output, "waveform.svg"), time_ns, fraction)
    report = Dict("status" => "completed", "model" => MODEL_ID,
        "model_sha256" => model_hash, "julia_version" => string(VERSION),
        "ssd_version" => string(pkgversion(SSD)),
        "environment_manifest_sha256" => sha256file(joinpath(@__DIR__, "Manifest.toml")),
        "device" => "CPU", "threads" => min(2, Threads.nthreads()), "field_cache_used" => false,
        "deposited_energy_keV" => 662.0, "deposit_xyz_mm" => [12.0, 5.0, 18.0],
        "time_step_ns" => 2.0, "readout_contact_id" => 1, "waveform_samples" => length(time_ns),
        "last_time_ns" => last(time_ns), "final_signed_charge_fraction" => last(fraction),
        "endpoints" => endpoints, "solver" => solver, "runtime_seconds" => time() - started,
        "completed_utc" => string(now(UTC)),
        "limitations" => ["Illustrative dimension-based reference, not a calibrated detector replica.",
            "Quickstart grid settings do not reproduce the website's full numerical campaign.",
            "Synthetic isolated deposit; no radiation transport, Fano statistics, electronics or noise.",
            "Equivalent-energy signal units are not reconstructed event energy."])
    save_json(joinpath(output, "run.json"), report)
    println("Completed in ", round(report["runtime_seconds"]; digits=1), " seconds. Output: ", output)
    println("Final signed charge fraction: ", last(fraction))
    return report
end

function main(args=ARGS)
    if args == ["--help"]
        println("Usage: julia --project=simulation simulation/run.jl [--check-models | --output DIR]")
        println("Default: a cache-free BEGe reference example; outputs remain under .local/quickstart.")
        return
    end
    v"1.13" <= VERSION < v"1.14" || error("This lockfile is tested with Julia 1.13.x. Review upgrades separately.")
    pkgversion(SSD) == v"0.11.8" || error("Use the supplied SSD 0.11.8 environment.")
    realpath(Base.active_project()) == realpath(joinpath(@__DIR__, "Project.toml")) ||
        error("Start Julia with --project=simulation, not the global environment.")
    if args == ["--check-models"]
        report = check_models()
        mkpath(joinpath(ROOT, ".local"))
        save_json(joinpath(ROOT, ".local", "model-parse-check.json"), report)
    elseif isempty(args)
        run_demo(OUTPUT)
    elseif length(args) == 2 && args[1] == "--output"
        run_demo(abspath(args[2]))
    else
        error("Unknown arguments. Use --help; this is one bounded example, not an arbitrary batch runner.")
    end
end
end # module SSDQuickstart

if abspath(PROGRAM_FILE) == @__FILE__
    SSDQuickstart.main()
end
