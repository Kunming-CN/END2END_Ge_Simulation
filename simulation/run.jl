"""Cache-free SSD example. CUDA is optional and used only for potential iteration."""
module SSDQuickstart
using Dates, JSON, SHA, SolidStateDetectors, TOML, Unitful
const SSD = SolidStateDetectors
const ROOT = normpath(joinpath(@__DIR__, ".."))
const MODEL_ID = "BEGe_GD32B_reference"
const MODEL_DIR = joinpath(ROOT, "models")
const OUTPUT = joinpath(ROOT, ".local", "quickstart")
const HELP = """
Usage: julia --startup-file=no --threads=2 --project=simulation simulation/run.jl [options]
  --help | --list-models | --check-models     Standalone inspection commands
  --model ID                  Catalog ID (default BEGe_GD32B_reference)
  --device cpu|cuda           Default cpu; cuda requires --project=simulation/gpu
  --precision 32|64           Floating-point precision (default 32)
  --position-mm x,y,z         Cartesian deposit; default 12,5,18 for BEGe only
  --energy-kev N              Positive deposited energy (default 662)
  --contact N                 Contact ID (default catalog readout_contact_id)
  --dt-ns N                   Positive drift/signal time step (default 2)
  --max-steps N               Drift sample cap, 2..1000000 (default 20000)
  --max-iterations N          Potential iterations per refinement, 250..50000 (default 10000)
  --threads N                 Solver threads, <= Julia startup threads (default min(2, available))
  --min-grid-mm N             Positive minimum refinement spacing (default 0.25)
  --max-grid-mm N             Initial maximum spacing, >= minimum (default 2)
  --output DIR                New directory under project .local/ (default .local/quickstart)
GPU accelerates electric/weighting potential iteration only. No diffusion or self-repulsion.
"""

sha256file(file) = bytes2hex(sha256(read(file)))
catalog() = JSON.parsefile(joinpath(MODEL_DIR, "catalog.json"))
function model_entry(id, cat=catalog())
    i = findfirst(e -> e["id"] == id, cat["detectors"])
    isnothing(i) && throw(ArgumentError("Unknown model: $id. Use --list-models."))
    cat["detectors"][i]
end
function save_json(file, value)
    open(file, "w") do io
        JSON.print(io, value, 2)
        println(io)
    end
end

# Resolve the existing ancestor, so a symlink/junction cannot redirect generated files.
pathkey(p) = Sys.iswindows() ? lowercase(normpath(p)) : normpath(p)
function childof(path, parent)
    parts = splitpath(relpath(pathkey(path), pathkey(parent)))
    !isempty(parts) && first(parts) != ".." && !isabspath(relpath(pathkey(path), pathkey(parent))) && pathkey(path) != pathkey(parent)
end
function validate_output(path)
    isempty(strip(path)) && throw(ArgumentError("Output must not be empty."))
    output = abspath(path)
    localroot = joinpath(realpath(ROOT), ".local")
    childof(output, joinpath(ROOT, ".local")) || throw(ArgumentError("Output must be a new directory below project .local/."))
    (ispath(output) || islink(output)) && throw(ArgumentError("Output already exists: $output"))
    ancestor, tail = output, String[]
    while !ispath(ancestor)
        islink(ancestor) && throw(ArgumentError("Dangling output ancestor."))
        pushfirst!(tail, basename(ancestor))
        ancestor = dirname(ancestor)
    end
    isdir(ancestor) || throw(ArgumentError("Output ancestor is not a directory."))
    resolved = joinpath(realpath(ancestor), tail...)
    childof(resolved, localroot) || throw(ArgumentError("Output resolves outside project .local/."))
    output
end
function reserve_output(path)
    output = validate_output(path)
    mkpath(dirname(output))
    validate_output(output)
    mkdir(output) # Exclusive: a concurrent run cannot overwrite this directory.
    output
end

function finite_number(text, name; scale=1.0, positive=true)
    x = tryparse(Float64, text)
    isnothing(x) && throw(ArgumentError("$name requires a number."))
    y = Float32(x * scale)
    isfinite(x) && isfinite(y) && (!positive || (x > 0 && y > 0)) ||
        throw(ArgumentError("$name must be finite, representable in Float32, and positive where required."))
    x
end
function integer(text, name, lo, hi)
    x = tryparse(Int, text)
    !isnothing(x) && lo <= x <= hi || throw(ArgumentError("$name must be an integer in $lo..$hi."))
    x
end
function parse_args(args; default_output=OUTPUT)
    if length(args) == 1 && args[1] in ("--help", "--list-models", "--check-models")
        return (action=Symbol(args[1][3:end]),)
    end
    names = ("model", "device", "precision", "position-mm", "energy-kev", "contact", "dt-ns", "max-steps", "max-iterations", "threads", "min-grid-mm", "max-grid-mm", "output")
    values = Dict{String,String}()
    iseven(length(args)) || throw(ArgumentError("Options require values; use --help."))
    for i in 1:2:length(args)
        key = args[i]
        startswith(key, "--") && key[3:end] in names || throw(ArgumentError("Unknown option: $key"))
        haskey(values, key[3:end]) && throw(ArgumentError("Duplicate option: $key"))
        values[key[3:end]] = args[i+1]
    end
    id = get(values, "model", MODEL_ID)
    entry = model_entry(id)
    id == MODEL_ID || haskey(values, "position-mm") || throw(ArgumentError("Non-default models require --position-mm."))
    device = get(values, "device", "cpu")
    device in ("cpu", "cuda") || throw(ArgumentError("--device must be cpu or cuda."))
    precision_text = get(values, "precision", "32")
    precision_text in ("32", "64") || throw(ArgumentError("--precision must be 32 or 64."))
    precision = parse(Int, precision_text)
    xyz = split(get(values, "position-mm", "12,5,18"), ',')
    length(xyz) == 3 || throw(ArgumentError("--position-mm requires x,y,z."))
    position = Tuple(finite_number(x, "--position-mm"; scale=1e-3, positive=false) for x in xyz)
    energy = finite_number(get(values, "energy-kev", "662"), "--energy-kev"; scale=1e3)
    dt = finite_number(get(values, "dt-ns", "2"), "--dt-ns"; scale=1e-9)
    steps = integer(get(values, "max-steps", "20000"), "--max-steps", 2, 1_000_000)
    isfinite(Float32(dt * 1e-9 * steps)) || throw(ArgumentError("Drift duration overflows Float32."))
    iterations = integer(get(values, "max-iterations", "10000"), "--max-iterations", 250, 50000)
    threads = integer(get(values, "threads", string(min(2, Threads.nthreads()))), "--threads", 1, Threads.nthreads())
    contact = integer(get(values, "contact", string(entry["readout_contact_id"])), "--contact", 1, typemax(Int))
    any(c -> c["id"] == contact, entry["contacts"]) || throw(ArgumentError("Unknown contact ID for $id."))
    mingrid = finite_number(get(values, "min-grid-mm", "0.25"), "--min-grid-mm"; scale=1e-3)
    maxgrid = finite_number(get(values, "max-grid-mm", "2"), "--max-grid-mm"; scale=1e-3)
    mingrid <= maxgrid || throw(ArgumentError("--min-grid-mm must be <= --max-grid-mm."))
    (action=:run, model=id, device=device, precision=precision, position=position, energy=energy, contact=contact,
        dt=dt, max_steps=steps, max_iterations=iterations, threads=threads, min_grid=mingrid, max_grid=maxgrid,
        output=validate_output(get(values, "output", default_output)))
end

function verify_model_files()
    cat = catalog()
    for entry in cat["detectors"]
        sha256file(joinpath(MODEL_DIR, entry["model"])) == entry["model_sha256"] || error("Model checksum mismatch: " * entry["id"])
    end
    for dep in cat["dependencies"]
        sha256file(joinpath(MODEL_DIR, dep["path"])) == dep["sha256"] || error("Include checksum mismatch: " * dep["path"])
    end
    cat
end
function check_models()
    cat = verify_model_files()
    for entry in cat["detectors"]
        sim = Simulation{Float32}(joinpath(MODEL_DIR, entry["model"]))
        println(entry["id"], ": parsed, ", length(sim.detector.contacts), " contacts")
    end
    println("All ", length(cat["detectors"]), " models loaded; no field solves.")
end
function environment(device)
    v"1.13" <= VERSION < v"1.14" || error("Use Julia 1.13.x with the reviewed lockfiles.")
    pkgversion(SSD) == v"0.11.8" || error("Use SSD 0.11.8.")
    active = Base.active_project()
    isnothing(active) && error("An explicit project is required.")
    cpu, gpu = joinpath(@__DIR__, "Project.toml"), joinpath(@__DIR__, "gpu", "Project.toml")
    known = [p for p in (cpu, gpu) if isfile(p)]
    realpath(active) in realpath.(known) || error("Use --project=simulation or --project=simulation/gpu.")
    device == "cuda" && realpath(active) != realpath(gpu) && error("CUDA requires --project=simulation/gpu.")
    # Prefer Julia's actual manifest selection, including version-specific manifests.
    manifest = Base.project_file_manifest_path(active)
    isnothing(manifest) && error("The active project has no Manifest.")
    Dict("project" => replace(relpath(active, ROOT), '\\' => '/'),
        "manifest" => replace(relpath(manifest, ROOT), '\\' => '/'),
        "environment_manifest_sha256" => sha256file(manifest),
        "julia_version" => string(VERSION), "ssd_version" => string(pkgversion(SSD)))
end

function cuda_backend()
    pkgversion(CUDA) == v"6.4.0" || error("Use the prepared CUDA 6.4.0 environment.")
    CUDA.functional() || error("CUDA.functional() is false; no CPU fallback.")
    device = CUDA.device()
    # CUDA 6.4 exposes NVML through CUDATools; keep reports free of environment/path dumps.
    driver = CUDA.CUDATools.has_nvml() ? string(CUDA.CUDATools.NVML.driver_version()) : "unavailable (NVML absent)"
    (array_type=CUDA.CuArray, synchronize=() -> CUDA.synchronize(),
        metadata=Dict("potential_backend" => "CUDA.CuArray", "gpu" => CUDA.name(device),
            "gpu_memory_bytes" => CUDA.totalmem(device), "cuda_version" => string(pkgversion(CUDA)),
            "cuda_driver_api_version" => string(CUDA.driver_version()),
            "cuda_runtime_version" => string(CUDA.runtime_version()), "nvidia_driver_version" => driver))
end
function prepare_backend(device)
    environment(device)
    if device == "cuda"
        @eval import CUDA
        return Base.invokelatest(cuda_backend)
    end
    (array_type=Array, synchronize=() -> nothing, metadata=Dict("potential_backend" => "Array (CPU)"))
end

function prepare_simulation(cfg)
    entry = model_entry(cfg.model, verify_model_files())
    T = cfg.precision == 64 ? Float64 : Float32
    sim = Simulation{T}(joinpath(MODEL_DIR, entry["model"]))
    any(c -> c.id == cfg.contact, sim.detector.contacts) || error("Contact absent from SSD model.")
    point = CartesianPoint{T}((T.(cfg.position .* 1e-3))...)
    point in sim.detector.semiconductor || throw(ArgumentError("Deposit is outside the semiconductor."))
    any(c -> point in c.geometry, sim.detector.contacts) && throw(ArgumentError("Deposit starts in/on a contact."))
    sim, point, entry
end
function timed(f, backend)
    backend.synchronize()
    started = time_ns()
    value = f()
    backend.synchronize()
    value, (time_ns() - started) / 1e9
end
function solve_fields!(sim, cfg, backend; sor_consts=missing, potential_rechecks::Int=1, iteration_observer=nothing)
    1 <= potential_rechecks <= 8 || throw(ArgumentError("Potential rechecks must be 1..8"))
    electric_updates = Float64[]
    weighting_updates = Float64[]
    bias = maximum(c.potential for c in sim.detector.contacts) - minimum(c.potential for c in sim.detector.contacts)
    common = (device_array_type=backend.array_type, use_nthreads=cfg.threads, sor_consts=sor_consts,
        depletion_handling=true, n_iterations_between_checks=250, verbose=false)
    options = (common..., convergence_limit=1e-6, refinement_limits=[0.2, 0.1, 0.05],
        min_tick_distance=cfg.min_grid*u"mm", max_tick_distance=cfg.max_grid*u"mm", max_n_iterations=cfg.max_iterations)
    electric_update, electric_s = timed(backend) do
        calculate_electric_potential!(sim; options...)
        # A depleted/neutral boundary may trigger SSD's plateau stop before its update tolerance.
        update = Inf
        for attempt in 1:potential_rechecks
            update = SSD.update_till_convergence!(sim, SSD.ElectricPotential, 1e-6; common..., max_n_iterations=3000)
            push!(electric_updates, Float64(update))
            gate = (iszero(bias) ? maximum(abs, sim.electric_potential.data) : abs(bias)) * 1e-6
            iteration_observer !== nothing && iteration_observer(Dict("potential"=>"electric", "attempt"=>attempt, "update"=>Float64(update), "limit"=>Float64(gate), "unit"=>"V"))
            isfinite(update) && update <= gate && break
        end
        update
    end
    bias = maximum(c.potential for c in sim.detector.contacts) - minimum(c.potential for c in sim.detector.contacts)
    scale = iszero(bias) ? maximum(abs, sim.electric_potential.data) : abs(bias)
    isfinite(electric_update) && electric_update <= scale * 1e-6 || error("Electric iteration tolerance not reached: last update $(electric_update) V, required <= $(scale*1e-6) V; grid $(size(sim.electric_potential.data)); limit $(cfg.max_iterations) per refinement.")
    # The extra relaxation rebuilds point_types; restore bulk/depletion/inactive bits.
    SSD.mark_bits!(sim)
    _, field_s = timed(backend) do
        calculate_electric_field!(sim; n_points_in_φ=36, use_nthreads=cfg.threads)
    end
    weighting_update, weighting_s = timed(backend) do
        calculate_weighting_potential!(sim, cfg.contact; options...)
        update = Inf
        for attempt in 1:potential_rechecks
            update = SSD.update_till_convergence!(sim, SSD.WeightingPotential, cfg.contact, 1e-6; common..., max_n_iterations=3000)
            push!(weighting_updates, Float64(update))
            iteration_observer !== nothing && iteration_observer(Dict("potential"=>"weighting", "attempt"=>attempt, "update"=>Float64(update), "limit"=>1e-6, "unit"=>"dimensionless"))
            isfinite(update) && update <= 1e-6 && break
        end
        update
    end
    isfinite(weighting_update) && weighting_update <= 1e-6 || error("Weighting iteration tolerance not reached: last update $(weighting_update), required <= 1e-6; limit $(cfg.max_iterations) per refinement.")
    solver = Dict("electric_update_history_V" => electric_updates, "potential_recheck_limit" => potential_rechecks, "weighting_update_history" => weighting_updates, "electric_last_update_V" => electric_update, "weighting_last_update" => weighting_update,
        "relative_tolerance" => 1e-6, "electric_grid" => collect(size(sim.electric_potential.data)),
        "weighting_grid" => collect(size(sim.weighting_potentials[cfg.contact].data)),
        "min_tick_distance_mm" => cfg.min_grid, "max_tick_distance_mm" => cfg.max_grid,
        "refinement_limits" => [0.2, 0.1, 0.05], "max_iterations_per_refinement" => cfg.max_iterations, "note" => "Iteration checks only; no grid-convergence claim")
    solver, Dict("electric_solve_seconds" => electric_s, "weighting_solve_seconds" => weighting_s,
        "potential_solve_seconds" => electric_s + weighting_s, "cpu_field_seconds" => field_s)
end

function endpoint_report(event, sim, cfg)
    [begin
        endpoint = last(path)
        contacts = [c.id for c in sim.detector.contacts if endpoint in c.geometry]
        at_limit = length(path) >= cfg.max_steps
        Dict("species" => species, "samples" => length(path), "position_mm" => Float64[endpoint.x, endpoint.y, endpoint.z] .* 1000,
            "contact_ids" => contacts, "step_limit_reached" => at_limit,
            "inside_semiconductor" => endpoint in sim.detector.semiconductor,
            "status" => !isempty(contacts) ? "contact" : at_limit ? "step_limit" : "stopped_without_contact")
    end for drift in event.drift_paths for (species, path) in (("electron", drift.e_path), ("hole", drift.h_path))]
end

"""Fresh Simulation for every invocation; caller enters latest world after optional CUDA import."""
function run_case(cfg, backend; prepared=prepare_simulation(cfg))
    started = time_ns()
    sim, point, entry = prepared
    solver, timings = solve_fields!(sim, cfg, backend)
    event = Event([point], [cfg.energy*u"keV"])
    _, timings["cpu_drift_seconds"] = timed(backend) do
        drift_charges!(event, sim; Δt=cfg.dt*u"ns", max_nsteps=cfg.max_steps,
            geometry_check=true, diffusion=false, self_repulsion=false, verbose=false)
    end
    _, timings["cpu_signal_seconds"] = timed(backend) do
        SSD.get_signal!(event, sim, cfg.contact; Δt=cfg.dt*u"ns", signal_unit=u"keV")
    end
    waveform = event.waveforms[cfg.contact]
    times = Float64.(ustrip.(u"ns", waveform.time))
    equivalent = Float64.(ustrip.(u"keV", waveform.signal))
    fraction = equivalent ./ cfg.energy # Dimensionless; never divide by final charge.
    !isempty(times) && all(isfinite, times) && all(diff(times) .> 0) || error("Invalid waveform times.")
    all(isfinite, equivalent) && all(isfinite, fraction) || error("Non-finite signal.")
    endpoints = endpoint_report(event, sim, cfg)
    verify_model_files()
    timings["run_seconds"] = (time_ns() - started) / 1e9
    report = Dict{String,Any}("status" => "completed", "model" => cfg.model,
        "model_sha256" => entry["model_sha256"], "model_status" => entry["status"], "model_assumptions" => entry["assumptions"],
        "device" => cfg.device, "precision_bits" => cfg.precision, "field_drift_signal_backend" => "CPU", "cpu" => Sys.CPU_NAME,
        "julia_threads" => Threads.nthreads(), "cpu_logical_threads" => Sys.CPU_THREADS, "solver_thread_limit" => cfg.threads,
        "thread_note" => "SSD may choose fewer SOR threads; geometry setup may use the full Julia pool.",
        "field_cache_used" => false, "deposited_energy_keV" => cfg.energy, "deposit_xyz_mm" => collect(cfg.position),
        "time_step_ns" => cfg.dt, "max_steps" => cfg.max_steps, "readout_contact_id" => cfg.contact,
        "waveform_samples" => length(times), "last_time_ns" => last(times), "final_signed_charge_fraction" => last(fraction),
        "final_induced_equivalent_energy_keV" => last(equivalent), "endpoints" => endpoints, "solver" => solver,
        "timings" => timings, "completed_utc" => string(now(UTC)), "random_seed" => "not applicable: deterministic, no random draws",
        "diffusion" => false, "self_repulsion" => false,
        "limitations" => ["Synthetic isolated deposit; no radiation transport, Fano statistics, electronics or noise.",
            "Equivalent-energy induced signal is not reconstructed energy; fraction is signal divided by deposited energy.",
            "Partial/trapped events are retained; endpoint status alone cannot diagnose trapping or collection efficiency.",
            "Original charge-trapping model is retained; no recombination model is added.",
            "Coarse example grids are not a convergence study, full website campaign or experimental validation."])
    merge!(report, environment(cfg.device), backend.metadata)
    (sim=sim, time=times, equivalent=equivalent, fraction=fraction, report=report)
end

function save_waveform_svg(file, times, fraction)
    tmax = max(last(times), 1.0)
    ymin, ymax = min(0.0, minimum(fraction)), max(1.0, maximum(fraction))
    points = join((string(70 + 790*t/tmax, ",", 295 - 225*(q-ymin)/(ymax-ymin)) for (t,q) in zip(times, fraction)), " ")
    open(file, "w") do io
        println(io, """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 360">
        <rect width="900" height="360" fill="white"/>
        <g font-family="sans-serif" font-size="15" fill="black">
        <text x="70" y="28">SSD electrode signal: synthetic isolated deposit</text>
        <text x="70" y="52">Signed induced signal / deposited energy; not reconstructed energy</text>
        <path d="M70 65 V295 H860" stroke="black" fill="none"/>
        <polyline points="$points" fill="none" stroke="black" stroke-width="2"/>""")
        for f in (0.0, 0.5, 1.0)
            println(io, "<text x=\"$(70+790*f)\" y=\"318\" text-anchor=\"middle\">$(round(tmax*f; digits=1))</text>")
            println(io, "<text x=\"58\" y=\"$(300-225*f)\" text-anchor=\"end\">$(round(ymin+f*(ymax-ymin); digits=2))</text>")
        end
        println(io, """<text x="460" y="346" text-anchor="middle">Time (ns)</text>
        <text transform="translate(18 180) rotate(-90)" text-anchor="middle">Signed induced charge fraction</text></g></svg>""")
    end
end
function write_result(result, output)
    open(joinpath(output, "signal.csv"), "w") do io
        println(io, "time_ns,induced_equivalent_energy_keV,signed_charge_fraction")
        for row in zip(result.time, result.equivalent, result.fraction)
            println(io, join(row, ','))
        end
    end
    save_waveform_svg(joinpath(output, "waveform.svg"), result.time, result.fraction)
    save_json(joinpath(output, "run.json"), result.report)
end
function main(args=ARGS)
    cfg = parse_args(args)
    cfg.action == :help && return print(HELP)
    environment(cfg.action == :run ? cfg.device : "cpu")
    if cfg.action == Symbol("list-models")
        for e in verify_model_files()["detectors"]
            println(e["id"], " | ", e["status"], " | readout ", e["readout_contact_id"])
        end
    elseif cfg.action == Symbol("check-models")
        check_models()
    else
        prepared = prepare_simulation(cfg) # Reject invalid points before CUDA initialization/solving.
        backend = prepare_backend(cfg.device)
        output = reserve_output(cfg.output)
        println("Solving ", cfg.model, " with ", backend.metadata["potential_backend"], "...")
        result = Base.invokelatest(run_case, cfg, backend; prepared=prepared)
        write_result(result, output)
        println("Output: ", output, "; final signed charge fraction: ", last(result.fraction))
    end
end
end # module

if abspath(PROGRAM_FILE) == @__FILE__
    SSDQuickstart.main()
end
