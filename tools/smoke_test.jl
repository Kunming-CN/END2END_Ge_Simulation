# Bounded migration smoke test: existing cache + one deterministic SSD event.
using SolidStateDetectors, Serialization, Unitful, SHA
const SSD = SolidStateDetectors
const ROOT = normpath(joinpath(@__DIR__, ".."))
const VIS = joinpath(ROOT, "Additional_Simulations", "Visualization_3D")
catalog = SSD.JSON.parsefile(joinpath(VIS, "catalog.json"))
for entry in catalog["detectors"]
    @assert isfile(entry["model"])
    @assert bytes2hex(sha256(read(entry["model"]))) == entry["model_sha256"]
    @assert entry["cache"] === nothing || isfile(entry["cache"])
end
entry = only(filter(e -> e["id"] == "AK01", catalog["detectors"]))
sim = deserialize(entry["cache"])
fresh = Simulation{Float32}(entry["model"])
@assert sim.config_dict == fresh.config_dict
reference = SSD.JSON.parsefile(joinpath(VIS, "detectors", "AK01", "runs", "20260922_suite_v3", "events", "fixed", "event.json"))
points = [CartesianPoint{Float32}((p ./ 1000)...) for p in reference["sites_xyz_mm"]]
@assert all(p in sim.detector.semiconductor for p in points)
evt = Event(points, Float64.(reference["site_energies_keV"]) .* u"keV")
dt = reference["dt_ns"] * u"ns"
drift_charges!(evt, sim; Δt=dt, max_nsteps=40000, geometry_check=true, verbose=false)
SSD.get_signal!(evt, sim, reference["readout_contact_id"]; Δt=dt, signal_unit=u"keV")
q = Float64.(ustrip.(u"keV", evt.waveforms[reference["readout_contact_id"]].signal)) ./ reference["energy_keV"] .* reference["signal_polarity"]
@assert all(isfinite, q)
@assert length(q) == length(reference["signal"]["Q_total"])
maxdiff = maximum(abs.(q .- reference["signal"]["Q_total"]))
@assert maxdiff < 1e-5
report = Dict("model_hash_checks"=>17, "detector"=>"AK01", "samples"=>length(q), "max_waveform_difference"=>maxdiff, "Q_final"=>last(q), "julia"=>string(VERSION), "ssd"=>string(pkgversion(SSD)), "scope"=>"One deterministic event replay; not all-model numerical validation")
open(io -> SSD.JSON.print(io, report, 2), joinpath(ROOT, ".local", "ssd-smoke.json"), "w")
println(report)
