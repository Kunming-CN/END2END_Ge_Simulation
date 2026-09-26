# Radiation-deposit handoff; charge-only baseline, not a calibrated detector response.
isdefined(@__MODULE__, :SSDQuickstart) || include("run.jl")
module SSDReplay
using ..SSDQuickstart
using SolidStateDetectors, Unitful, JSON, LinearAlgebra
const Q = SSDQuickstart
const SSD = SolidStateDetectors
const MAX_SAMPLES = 500_000
check(ok, message) = ok ? nothing : throw(ArgumentError(message))
finite(x) = x isa Real && !(x isa Bool) && isfinite(x)
integer(x) = x isa Integer && !(x isa Bool)
vec3(v) = v isa AbstractVector && length(v) == 3 && all(finite, v)

function check_document(d)
    check(get(d, "schema_version", nothing) === 1, "Unsupported event schema")
    check(d["model_id"] in ("AK02", "SAP22"), "Only the reviewed AK02/SAP22 handoff is supported")
    entry = Q.model_entry(d["model_id"], Q.verify_model_files())
    check(d["model_sha256"] == entry["model_sha256"], "Model checksum mismatch")
    for key in ("model_sha256", "source_lh5_sha256", "geometry_sha256", "macro_sha256")
        check(d[key] isa String && occursin(r"^[0-9a-f]{64}$", d[key]), "Invalid checksum: " * key)
    end
    check(d["units"] == Dict("energy"=>"keV", "length"=>"mm", "time"=>"ns"), "Wrong handoff units")
    tr = d["coordinate_transform"]
    check(tr["definition"] == "x_global_mm=R*x_local_mm+t", "Unknown transform convention")
    rows = tr["rotation_local_to_global"]
    check(length(rows) == 3 && all(vec3, rows) && vec3(tr["translation_global_mm"]), "Invalid transform")
    R = reduce(vcat, [permutedims(Float64.(v)) for v in rows])
    shift = Float64.(tr["translation_global_mm"])
    check(isapprox(R' * R, Matrix{Float64}(I, 3, 3); atol=1e-12, rtol=0) && abs(det(R)-1) <= 1e-12, "Not a proper rotation")
    n = d["primary_count"]
    check(integer(n) && 0 < n <= 100_000 && length(d["events"]) == n, "Bad primary census")
    seen = Set{Int}(); energy = 0.0
    for (i, event) in enumerate(d["events"])
        check(integer(event["event_id"]) && event["event_id"] == i-1, "Event census/order mismatch")
        t0 = event["primary_time_ns"]
        check(finite(t0) && t0 >= 0, "Invalid primary time")
        check(length(event["steps"]) <= 100_000, "Unbounded event; reduce the test workload explicitly")
        for s in event["steps"]
            for key in ("raw_row_index", "track_id", "parent_track_id", "particle_pdg")
                check(integer(s[key]), "Noninteger " * key)
            end
            row = s["raw_row_index"]
            check(row >= 0 && !(row in seen) && s["track_id"] > 0 && s["parent_track_id"] >= 0, "Duplicate/invalid row or track")
            push!(seen, row)
            check(finite(s["energy_keV"]) && s["energy_keV"] >= 0, "Invalid deposited energy")
            check(finite(s["time_ns"]) && s["time_ns"] >= t0, "Deposit precedes its primary")
            for key in ("position_mm", "global_position_m", "pre_position_mm", "post_position_mm")
                check(vec3(s[key]), "Invalid position: " * key)
            end
            local_mm = R' * (1000 .* Float64.(s["global_position_m"]) .- shift)
            check(isapprox(local_mm, Float64.(s["position_mm"]); atol=1e-10, rtol=0), "Global/local coordinate mismatch")
            energy += s["energy_keV"]
        end
    end
    check(sort!(collect(seen)) == collect(0:length(seen)-1), "Missing raw row identity")
    check(finite(d["energy_sum_keV"]) && isapprox(energy, d["energy_sum_keV"]; rtol=1e-12, atol=1e-9), "Energy ledger mismatch")
    d
end

function setup_simulation(model; temperature=nothing)
    sim = Simulation{Float64}(joinpath(Q.MODEL_DIR, model * ".yaml"))
    original = sim.detector.semiconductor.temperature
    if temperature !== nothing
        check(finite(temperature) && 50 <= temperature <= 150, "Temperature override must be 50..150 K")
        config = deepcopy(sim.config_dict)
        sc = config["detectors"][1]["semiconductor"]
        sc["temperature"] = Float64(temperature)
        cdm = sc["charge_drift_model"]
        if haskey(cdm, "temperature")
            cdm["temperature"] = Float64(temperature)
        end
        sim = Simulation{Float64}(config)
    end
    check(temperature === nothing || sim.detector.semiconductor.temperature == temperature, "Temperature override did not take effect")
    cdm = sim.detector.semiconductor.charge_drift_model
    if hasproperty(cdm, :temperature)
        check(cdm.temperature == sim.detector.semiconductor.temperature, "Drift/semiconductor temperature mismatch")
    end
    sim, original
end

function validate_deposits(d, sim)
    count = 0
    for event in d["events"], s in event["steps"]
        s["energy_keV"] == 0 && continue
        point = CartesianPoint{Float64}((Float64.(s["position_mm"]) ./ 1000)...)
        check(point in sim.detector.semiconductor, "Positive-energy deposit outside SSD: row $(s["raw_row_index"])")
        check(!any(c -> point in c.geometry, sim.detector.contacts), "Positive-energy deposit starts on a contact: row $(s["raw_row_index"])")
        count += 1
    end
    count
end

# Each component is cumulative induced charge in keV-equivalent units.
# It is exactly zero before creation and held at its last simulated value afterwards.
function causal_sum(components, dt)
    check(finite(dt) && dt > 0, "Invalid signal step")
    for c in components
        check(finite(c.delay) && c.delay >= 0, "Negative/nonfinite deposition delay")
        check(length(c.times) >= 2 && length(c.times) == length(c.charge), "Invalid waveform dimensions")
        check(first(c.times) == 0 && all(finite, c.times) && all(diff(c.times) .> 0) && all(finite, c.charge), "Invalid waveform support")
    end
    stop = isempty(components) ? dt : maximum(c.delay + last(c.times) for c in components)
    check(finite(stop) && stop/dt <= MAX_SAMPLES-2, "Time span exceeds bounded waveform memory")
    times = collect(range(0.0; step=Float64(dt), length=max(2, ceil(Int, stop/dt)+1)))
    total = zeros(length(times))
    for c in components, (j, t) in enumerate(times)
        age = t - c.delay
        age < 0 && continue
        if age >= last(c.times)
            total[j] += last(c.charge)
        else
            k = searchsortedlast(c.times, age)
            f = (age-c.times[k]) / (c.times[k+1]-c.times[k])
            total[j] += (1-f)*c.charge[k] + f*c.charge[k+1]
        end
    end
    target = sum((last(c.charge) for c in components); init=0.0)
    check(isapprox(last(total), target; atol=1e-9, rtol=1e-12), "Causal sum changed final induced charge")
    times, total
end

function replay_event(event, sim, cfg)
    components = Any[]; outcomes = Any[]
    t0 = event["primary_time_ns"]
    for step in event["steps"]
        energy = step["energy_keV"]
        energy == 0 && continue # Kept in the raw input/census, produces no charge.
        xyz = Float64.(step["position_mm"]) ./ 1000
        point = CartesianPoint{Float64}(xyz...)
        evt = Event([point], [energy*u"keV"])
        drift_charges!(evt, sim; Δt=cfg.dt*u"ns", max_nsteps=cfg.max_steps,
            geometry_check=true, diffusion=false, self_repulsion=false,
            end_drift_when_no_field=true, verbose=false)
        stored = evt.locations[1][1]
        check((stored.x,stored.y,stored.z) == (point.x,point.y,point.z), "SSD moved an input deposition")
        SSD.get_signal!(evt, sim, cfg.contact; Δt=cfg.dt*u"ns", signal_unit=u"keV")
        w = evt.waveforms[cfg.contact]
        times = Float64.(ustrip.(u"ns", w.time))
        charge = Float64.(ustrip.(u"keV", w.signal))
        push!(components, (delay=Float64(step["time_ns"]-t0), times=times, charge=charge))
        push!(outcomes, Dict("raw_row_index"=>step["raw_row_index"],
            "deposition_delay_ns"=>step["time_ns"]-t0,
            "deposited_energy_keV"=>energy, "last_induced_equivalent_energy_keV"=>last(charge),
            "endpoints"=>Q.endpoint_report(evt, sim, cfg)))
    end
    times, total = causal_sum(components, cfg.dt)
    edep = sum((s["energy_keV"] for s in event["steps"]); init=0.0)
    limited = any(x -> any(e -> e["step_limit_reached"], x["endpoints"]), outcomes)
    stopped = any(x -> any(e -> e["status"] == "stopped_without_contact", x["endpoints"]), outcomes)
    status = edep == 0 ? "zero_deposit" : limited ? "step_limit" : stopped ? "stopped_without_contact" : "completed"
    report = Dict("event_id"=>event["event_id"], "primary_time_ns"=>t0,
        "status"=>status, "raw_rows"=>length(event["steps"]), "charge_deposits"=>length(components),
        "deposited_energy_keV"=>edep, "final_induced_equivalent_energy_keV"=>last(total),
        "signed_induced_fraction"=>edep == 0 ? nothing : last(total)/edep,
        "samples"=>length(times), "time_since_primary_end_ns"=>last(times), "steps"=>outcomes)
    (times=times, signal=total, report=report, components=components)
end

function validate_prepared_identity(d, meta)
    check(meta["model_id"] == d["model_id"] && meta["model_sha256"] == d["model_sha256"] && meta["primary_count"] == d["primary_count"], "Prepared identity mismatch")
    check(meta["coordinate_transform"] == d["coordinate_transform"], "Handoff transform does not match prepared geometry")
    tr = meta["coordinate_transform"]
    check(tr["rotation_local_to_global"] == [[1,0,0],[0,1,0],[0,0,1]] && tr["translation_global_mm"] == [0,0,0],
        "M2a runtime is identity-placed only; rotated geometry requires a separate validated producer")
    nothing
end

function load_input(filename)
    check(isfile(filename), "Input events.json does not exist")
    check(Q.childof(realpath(filename), joinpath(realpath(Q.ROOT), ".local")), "Input must be below project .local")
    check(filesize(filename) < 100_000_000, "Fixture is too large for this bounded JSON reader")
    d = check_document(JSON.parsefile(filename))
    directory = dirname(realpath(filename))
    for (name, hash) in (("truth.lh5",d["source_lh5_sha256"]), ("geometry.gdml",d["geometry_sha256"]), ("run.mac",d["macro_sha256"]),
                         ("prepared.json",d["provenance"]["prepared_sha256"]), ("run.json",d["provenance"]["run_sha256"]))
        f = joinpath(directory, name)
        check(isfile(f) && Q.childof(realpath(f), joinpath(realpath(Q.ROOT), ".local")) && Q.sha256file(f) == hash, "Input provenance mismatch: " * name)
    end
    meta = JSON.parsefile(joinpath(directory, "prepared.json"))
    validate_prepared_identity(d, meta)
    for event in d["events"]
        energy = sum((s["energy_keV"] for s in event["steps"]); init=0.0)
        check(energy <= meta["energy_keV"] + 1e-6, "Event deposits exceed the primary photon energy")
    end
    d, meta
end

function geometry_check(meta, sim)
    g = sim.detector.semiconductor.geometry
    expected = sort([Tuple(Float64.(p)) for p in meta["contour_rz_mm"]])
    actual = sort(collect(zip(1000 .* g.r, 1000 .* g.z)))
    check(length(actual) == length(expected) && all(isapprox.(first.(actual),first.(expected);atol=1e-10,rtol=0)) &&
          all(isapprox.(last.(actual),last.(expected);atol=1e-10,rtol=0)), "SSD contour differs from prepared geometry")
    for probe in meta["probes"]
        point = CartesianPoint{Float64}((Float64.(probe["position_mm"]) ./ 1000)...)
        check((point in sim.detector.semiconductor) == (probe["expected"] != "outside"), "SSD probe mismatch: " * probe["name"])
    end
    Dict("ssd_contour_matches"=>true, "ssd_probes_checked"=>length(meta["probes"]),
        "note"=>"SSD membership and contour only; Geant4 solid volume/probe check is separate")
end

const HELP = """
Usage: julia --startup-file=no --threads=2 --project=simulation simulation/replay.jl --input .local/RUN/events.json [options]
  --inspect                 Validate provenance, all deposits and SSD geometry, no field solve
  --output DIR              New directory under .local/ (required for a replay)
  --max-events N            First N primary event IDs, including zero-deposit events (default 10)
  --temperature-k K         Explicit run override; omitted means exact original 78 K model
  --dt-ns N                 Drift and output spacing (default 2 ns)
  --min-grid-mm N           Minimum refinement spacing (default 0.05 mm)
  --max-iterations N        Iteration budget per refinement (default 50000)
  --sor N                   Explicit relaxation factor, 1..1.85 (default 1)
  --device cpu|cuda         CPU default; CUDA requires --project=simulation/gpu
Only AK02/SAP22, Float64, one readout electrode, no diffusion/self-repulsion/electronics.
"""
function options(args)
    args == ["--help"] && return nothing
    values = Dict{String,String}(); inspect = false; i = 1
    allowed = ("--input","--output","--max-events","--temperature-k","--dt-ns","--min-grid-mm","--max-iterations","--sor","--device")
    while i <= length(args)
        key = args[i]
        if key == "--inspect"
            check(!inspect, "Duplicate --inspect"); inspect = true; i += 1; continue
        end
        check(key in allowed && i < length(args) && !haskey(values,key), "Invalid/duplicate option: " * key)
        values[key] = args[i+1]; i += 2
    end
    check(haskey(values,"--input"), "--input is required")
    check(inspect || haskey(values,"--output"), "--output is required for replay")
    values, inspect
end

function main(args=ARGS)
    opt = options(args)
    opt === nothing && return print(HELP)
    v, inspect = opt
    device = get(v,"--device","cpu")
    check(device in ("cpu","cuda"), "Unknown device")
    Q.environment(device)
    d, meta = load_input(abspath(v["--input"]))
    temperature = haskey(v,"--temperature-k") ? Q.finite_number(v["--temperature-k"], "temperature") : nothing
    sim, original_temperature = setup_simulation(d["model_id"]; temperature=temperature)
    geom = geometry_check(meta, sim)
    deposits = validate_deposits(d, sim)
    if inspect
        println(JSON.json(Dict("status"=>"validated_no_fields", "positive_deposits"=>deposits,
            "primary_count"=>d["primary_count"], "geometry"=>geom)))
        return
    end
    limit = Q.integer(get(v,"--max-events",string(min(10,d["primary_count"]))), "max events", 1, d["primary_count"])
    sor = Q.finite_number(get(v,"--sor","1"), "SOR")
    check(1 <= sor <= 1.85, "SOR must be 1..1.85")
    cfg = Q.parse_args(["--model",d["model_id"],"--position-mm","3,0,5","--precision","64",
        "--device",device,"--output",v["--output"],"--dt-ns",get(v,"--dt-ns","2"),
        "--min-grid-mm",get(v,"--min-grid-mm","0.05"),"--max-iterations",get(v,"--max-iterations","50000")])
    backend = Q.prepare_backend(device)
    output = Q.reserve_output(cfg.output)
    report = Dict{String,Any}("status"=>"running", "scope"=>"Bare-detector radiation-to-charge interface; not calibrated Li CCE or electronics",
        "model_id"=>d["model_id"], "model_sha256"=>d["model_sha256"],
        "source_code_sha256"=>Dict(name=>Q.sha256file(joinpath(@__DIR__,name)) for name in ("run.jl","replay.jl")),
        "input_sha256"=>Q.sha256file(v["--input"]), "source_lh5_sha256"=>d["source_lh5_sha256"],
        "source_provenance"=>d["provenance"], "primary_count"=>d["primary_count"], "selected_primary_count"=>limit,
        "stored_temperature_K"=>original_temperature, "effective_temperature_K"=>sim.detector.semiconductor.temperature,
        "temperature_override_K"=>temperature, "contact_potentials_V"=>[c.potential for c in sim.detector.contacts],
        "charge_drift_model"=>string(typeof(sim.detector.semiconductor.charge_drift_model)),
        "drift_temperature_model"=>hasproperty(sim.detector.semiconductor.charge_drift_model,:temperaturemodel) ? string(typeof(sim.detector.semiconductor.charge_drift_model.temperaturemodel)) : "model-specific mobility",
        "temperature_note"=>d["model_id"] == "SAP22" ? "The original ADL VacuumTemperatureModel does not rescale drift parameters; nominal 77/78 K runs use the same velocity parametrization." : "Semiconductor and InactiveLayer mobility temperatures are updated consistently; parameters remain uncalibrated inputs.",
        "charge_trapping_model"=>sim.config_dict["detectors"][1]["semiconductor"]["charge_trapping_model"],
        "ionisation_energy_eV"=>ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation),
        "geometry"=>geom, "sor_constant"=>sor, "precision_bits"=>64, "time_step_ns"=>cfg.dt,
        "diffusion"=>false, "self_repulsion"=>false, "end_drift_when_no_field"=>true,
        "events"=>Any[], "unselected_event_ids"=>[e["event_id"] for e in d["events"][limit+1:end]],
        "limitations"=>["Unresolved stopped/step-limit trajectories are retained, not diagnosed as physical trapping.",
          "Independent deposit superposition; not valid for interacting time-evolving charge clouds.",
          "Charge is zero before creation; after its last simulated point the cumulative signal is held constant.",
          "Coarse-grid interface test; zero-field termination prevents a neutral-layer diffusion interpretation.",
          "No Fano fluctuations, recombination/detrapping, preamplifier, shaping, ADC or reconstructed energy.",
          "Stored effective lifetimes and impurity profiles are inputs, not newly calibrated measurements."])
    merge!(report,Q.environment(device),backend.metadata)
    started = time()
    try
        println("Solving ",d["model_id"]," at ",sim.detector.semiconductor.temperature," K; explicit SOR=",sor)
        solver,timings = Base.invokelatest(Q.solve_fields!,sim,cfg,backend;sor_consts=sor,potential_rechecks=4)
        report["solver"] = solver; report["timings"] = timings
        first_plot = true
        open(joinpath(output,"signals.csv"),"w") do csv
            println(csv,"event_id,time_since_primary_ns,induced_equivalent_energy_keV")
            for event in d["events"][1:limit]
                result = Base.invokelatest(replay_event,event,sim,cfg)
                push!(report["events"],result.report)
                for (t,q) in zip(result.times,result.signal)
                    println(csv,event["event_id"],',',t,',',q)
                end
                if first_plot && result.report["deposited_energy_keV"] > 0
                    svg = joinpath(output,"waveform.svg")
                    Q.save_waveform_svg(svg,result.times,result.signal ./ result.report["deposited_energy_keV"])
                    text = replace(read(svg,String), "SSD electrode signal: synthetic isolated deposit" => "$(d["model_id"]) radiation event $(event["event_id"]): electrode signal")
                    write(svg,text); first_plot = false
                end
                println("Event ",event["event_id"],": ",result.report["status"],"; Edep=",result.report["deposited_energy_keV"]," keV")
            end
        end
        report["status"] = any(e->e["status"] in ("step_limit","stopped_without_contact"),report["events"]) ? "completed_with_transport_flags" : "completed"
    catch err
        report["status"] = "failed"
        report["error"] = sprint(showerror,err)
        rethrow()
    finally
        report["runtime_seconds"] = time()-started
        Q.save_json(joinpath(output,"run.json"),report)
    end
    Q.verify_model_files()
    println("Replay status: ",report["status"],"; output: ",output)
    report
end
end # module SSDReplay
if abspath(PROGRAM_FILE) == @__FILE__
    SSDReplay.main()
end
