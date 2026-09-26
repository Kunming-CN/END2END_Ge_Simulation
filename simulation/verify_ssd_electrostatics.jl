# Synthetic SSD electrostatic verification, independent of AK02 and carrier transport.
module SSDElectrostatics
using SolidStateDetectors, SHA, JSON, LinearAlgebra, TOML
const SSD = SolidStateDetectors
include("verify_electrostatics.jl")
const A = AnalyticElectrostatics
const ROOT = A.ROOT
const INNER = 0.0051
const OUTER = 0.0349
const COUNTS = (17, 33, 65)
const EXAMPLE_HASH = "a62cb1e9105e8a6a1e65e2652135f96cc3d0971efd4977df985596fb262864a6"
# Prospective gates from both M2b4 reviewers. Boundary field errors are diagnostic.
const GATES = (voltage=1e-3, midpoint_field=1e-3, interior_field=1e-3,
    refinement_ratio=0.4, contact_V=1e-10, axial_V=1e-8,
    transverse_relative=1e-8, constant_V=1e-9, constant_field_V_m=1e-6,
    update_V=1e-12, continuation_V=1e-9, control_V=1e-8,
    control_field_V_m=1e-6, ratio_floor=1e-11)
const SOLVER = (relative_limit=1e-14, initial_iterations=49000,
    verification_iterations=1000, check_interval=100, threads=1)
check(ok, msg) = A.check(ok, msg)
hashfile(path) = bytes2hex(sha256(read(path)))

function annulus(n; a=INNER, b=OUTER, unit="m")
    check(unit == "m", "Coordinates must be in metres")
    check(n isa Integer && !(n isa Bool) && n in COUNTS, "Use 17/33/65 annular nodes")
    check(a == INNER && b == OUTER, "Contact faces must be 5.1 and 34.9 mm")
    A.grid(n; a, b)
end

function requested_ticks(n)
    # r=0 is required by SSD; electrode ticks resolve the 0.1 mm contacts.
    (r=vcat([0.0, 0.0025, 0.005, 0.00505], annulus(n), [0.03495, 0.035]),
     phi=[0.0], z=[-0.001, 0.001])
end

function validate_ticks(actual, requested)
    for key in (:r, :phi, :z)
        v = getproperty(actual, key)
        check(eltype(v) == Float64 && all(isfinite, v), "Invalid Float64 ticks: $key")
        check(all(diff(v) .> 0), "Non-increasing ticks: $key")
        check(v == getproperty(requested, key), "SSD changed requested ticks: $key")
    end
    true
end

ticks(grid) = (r=collect(grid.axes[1]), phi=collect(grid.axes[2]), z=collect(grid.axes[3]))
tickdict(t) = Dict(string(k)=>v for (k,v) in pairs(t))


# Match SSD.get_φ_SSDInterval: a collapsed phi interval is represented by
# reflecting/closed ends, which gives a full-azimuth integration weight.
function make_grid(n)
    t = requested_ticks(n)
    axes = (SSD.DiscreteAxis(0.0, 0.035, :r0, :infinite, :closed, :closed, t.r),
        SSD.DiscreteAxis(0.0, 0.0, :reflecting, :reflecting, :closed, :closed, t.phi),
        SSD.DiscreteAxis(-0.001, 0.001, :reflecting, :reflecting, :closed, :closed, t.z))
    grid = SSD.CylindricalGrid{Float64}(axes)
    SSD.check_grid(grid)
    grid
end

function validate_config(config)
    check(config["units"]["length"] == "mm" && config["units"]["potential"] == "V",
        "Unexpected example units")
    axes = config["grid"]["axes"]
    check(config["grid"]["coordinates"] == "cylindrical" && config["medium"] == "HPGe",
        "Unexpected coordinates or medium")
    check(axes["r"]["to"] == 35 && axes["r"]["boundaries"] == "inf", "Wrong radial domain")
    check(axes["phi"]["from"] == axes["phi"]["to"] == 0 &&
        axes["phi"]["boundaries"] == "periodic", "Wrong azimuthal boundary")
    check(axes["z"]["from"] == -1 && axes["z"]["to"] == 1 &&
        axes["z"]["boundaries"] == "reflecting", "Wrong axial boundary")
    contacts = only(config["detectors"])["contacts"]
    check(length(contacts) == 2, "Expected two contacts")
    for (c, id, lo, hi) in zip(contacts, (1,2), (5,34.9), (5.1,35))
        tube = c["geometry"]["tube"]
        check(c["id"] == id && tube["r"]["from"] == lo && tube["r"]["to"] == hi &&
            tube["h"] == 2 && isfinite(c["potential"]), "Wrong contact geometry/bias")
    end
    true
end

function validate_masks(r, bits)
    check(size(bits,1) == length(r), "Mask/grid shape mismatch")
    for i in eachindex(r)
        if INNER < r[i] < OUTER
            check(all(b -> b & SSD.update_bit != 0, bits[i,:,:]), "Free-annulus node fixed by contact mask")
        elseif 0.005 <= r[i] <= INNER || OUTER <= r[i] <= 0.035
            check(all(b -> b & SSD.update_bit == 0, bits[i,:,:]), "Contact node not fixed")
        end
    end
    true
end

function source_check(sim)
    imp, fix, dielectric = sim.q_eff_imp.data, sim.q_eff_fix.data, sim.ϵ_r.data
    check(all(iszero, imp) && all(iszero, fix), "Benchmark must have exactly zero source arrays")
    check(all(isfinite, dielectric) && minimum(dielectric)>0 &&
        maximum(dielectric)-minimum(dielectric) <= 1e-12, "Dielectric is not homogeneous")
    Dict("max_impurity_source"=>maximum(abs,imp), "max_fixed_source"=>maximum(abs,fix),
        "relative_permittivity_extrema"=>collect(extrema(dielectric)))
end

function project_field(data, phi)
    check(size(data,2) == length(phi), "Field/azimuth shape mismatch")
    er = zeros(size(data)); ep = similar(er); ez = similar(er)
    for idx in CartesianIndices(data)
        v = data[idx]; angle = phi[idx[2]]
        er[idx] = v[1]*cos(angle) + v[2]*sin(angle)
        ep[idx] = -v[1]*sin(angle) + v[2]*cos(angle)
        ez[idx] = v[3]
    end
    check(all(isfinite, er) && all(isfinite, ep) && all(isfinite, ez), "Nonfinite SSD field")
    (er=er, ep=ep, ez=ez)
end

function diagnostics(r, potentials, er, ep, ez, va, vb)
    check(r == annulus(length(r)), "Wrong annular coordinates or units")
    check(isfinite(va) && isfinite(vb), "Nonfinite bias")
    check(size(potentials,1) == length(r) && size(potentials,2) == 1 && size(potentials,3) == 2,
        "Wrong potential shape")
    check(size(er) == size(ep) == size(ez) && size(er,1) == length(r) && size(er,3) == 2,
        "Wrong field shape")
    check(all(isfinite,potentials) && all(isfinite,er) && all(isfinite,ep) && all(isfinite,ez),
        "Nonfinite evidence")
    span = abs(vb-va)
    ref = A.exact_potential(r, INNER, OUTER, va, vb)
    fieldref = A.exact_field(r, INNER, OUTER, va, vb)
    # Each axial slice is imported unchanged. Never average away axial differences.
    fv = [A.metrics(r, copy(potentials[:,1,k]), va, vb) for k in axes(potentials,3)]
    sys = A.system(r, va, vb)
    volumes = (sys.faces[2:end].^2 .- sys.faces[1:end-1].^2)./2
    for (k, m) in enumerate(fv)
        residual = sys.matrix*potentials[2:end-1,1,k]-sys.rhs
        m["reference_FV_integrated_residual_V"] = residual
        m["reference_FV_minus_laplacian_residual_V_m2"] = residual./volumes
        m["analytic_FV_minus_laplacian_residual_V_m2"] = (sys.matrix*ref[2:end-1]-sys.rhs)./volumes
        # This direct reference solve is diagnostic only, never an SSD initial condition.
        reference_solution = vcat(va, sys.matrix\sys.rhs, vb)
        m["SSD_minus_reference_FV_max_V"] = maximum(abs,potentials[:,1,k].-reference_solution)
    end
    err = abs.(er .- reshape(fieldref,:,1,1))
    relative = iszero(span) ? nothing : err ./ abs.(reshape(fieldref,:,1,1))
    # All free nodes are bulk; the two contact faces use SSD contact derivative rules.
    interior = 2:length(r)-1
    stencil = -(diff(ref)[1:end-1]./diff(r)[1:end-1] .+
        diff(ref)[2:end]./diff(r)[2:end])./2
    contact_stencil = [-first(diff(ref))/first(diff(r)), -last(diff(ref))/last(diff(r))]
    # Independent implementation of the documented radial reconstruction stencil.
    # Both contact faces have a constant-potential conductor on the other side.
    numeric_stencil = similar(potentials)
    for k in axes(potentials,3)
        slopes = -diff(potentials[:,1,k])./diff(r)
        numeric_stencil[1,1,k] = first(slopes)
        numeric_stencil[end,1,k] = last(slopes)
        numeric_stencil[2:end-1,1,k] = (slopes[1:end-1].+slopes[2:end])./2
    end
    reconstruction_error = abs.(er.-numeric_stencil)
    Dict{String,Any}("reference_FV"=>fv,
        "voltage_error_V"=>maximum(abs,potentials.-reshape(ref,:,1,1)),
        "voltage_error_over_span"=>iszero(span) ? nothing : maximum(abs,potentials.-reshape(ref,:,1,1))/span,
        "midpoint_relative_error"=>iszero(span) ? nothing : maximum(m["relative_face_field_error"] for m in fv),
        "midpoint_absolute_error_V_m"=>maximum(m["absolute_face_field_error_V_m"] for m in fv),
        "interior_field_relative_error"=>iszero(span) ? nothing : maximum(relative[interior,:,:]),
        "contact_adjacent_field_relative_errors"=>iszero(span) ? nothing : [maximum(relative[i,:,:]) for i in (2,length(r)-1)],
        "contact_face_field_relative_errors"=>iszero(span) ? nothing : [maximum(relative[i,:,:]) for i in (1,length(r))],
        "field_absolute_error_V_m"=>maximum(err),
        "exact_nodal_interior_stencil_error_V_m"=>maximum(abs,stencil.-fieldref[interior]),
        "SSD_minus_numeric_stencil_interior_max_V_m"=>maximum(reconstruction_error[interior,:,:]),
        "SSD_minus_numeric_stencil_contact_max_V_m"=>[maximum(reconstruction_error[i,:,:]) for i in (1,length(r))],
        "residual_sign"=>"Positive-diagonal FV matrix: residual/volume approximates minus the cylindrical Laplacian",
        "exact_nodal_contact_stencil_errors_V_m"=>abs.(contact_stencil.-fieldref[[1,end]]),
        "contact_error_V"=>max(maximum(abs,potentials[1,:,:].-va),maximum(abs,potentials[end,:,:].-vb)),
        "axial_spread_V"=>maximum(abs,potentials[:,1,1].-potentials[:,1,2]),
        "radial_field_symmetry_spread_V_m"=>maximum(maximum(er[i,:,:])-minimum(er[i,:,:]) for i in eachindex(r)),
        "max_Ephi_V_m"=>maximum(abs,ep), "max_Ez_V_m"=>maximum(abs,ez),
        "minimum_V"=>minimum(potentials), "maximum_V"=>maximum(potentials),
        "minimum_signed_voltage_step_V"=>minimum(sign(vb-va).*diff(potentials;dims=1)),
        "maximum_signed_Er_V_m"=>maximum(sign(vb-va).*er),
        "Escale_V_m"=>span/(INNER*log(OUTER/INNER)))
end

function enforce_diagnostics(m, va, vb; finest=false)
    check(m["contact_error_V"] <= GATES.contact_V, "Contact potential enforcement failed")
    check(m["axial_spread_V"] <= GATES.axial_V, "Axial potential symmetry failed")
    check(m["minimum_V"] >= min(va,vb)-GATES.constant_V &&
        m["maximum_V"] <= max(va,vb)+GATES.constant_V, "Maximum principle failed")
    if va == vb
        check(m["voltage_error_V"] <= GATES.constant_V &&
            m["field_absolute_error_V_m"] <= GATES.constant_field_V_m &&
            m["midpoint_absolute_error_V_m"] <= GATES.constant_field_V_m, "Constant-bias limit failed")
    else
        check(m["minimum_signed_voltage_step_V"] >= -GATES.contact_V, "Potential is not monotone")
        check(m["maximum_signed_Er_V_m"] < 0, "Wrong radial field polarity")
        if finest
            check(m["voltage_error_over_span"] <= GATES.voltage, "Voltage accuracy failed")
            check(m["midpoint_relative_error"] <= GATES.midpoint_field, "Midpoint field accuracy failed")
            check(m["interior_field_relative_error"] <= GATES.interior_field, "SSD interior field accuracy failed")
        end
    end
    transverse = va == vb ? GATES.constant_field_V_m : GATES.transverse_relative*m["Escale_V_m"]
    check(max(m["max_Ephi_V_m"],m["max_Ez_V_m"],m["radial_field_symmetry_spread_V_m"]) <= transverse,
        "Field symmetry failed")
    true
end

function enforce_refinement(cases)
    check([c["nodes"] for c in cases] == collect(COUNTS), "Wrong refinement sequence")
    ratios = Dict{String,Any}()
    for key in ("voltage_error_over_span", "midpoint_relative_error", "interior_field_relative_error")
        values = [c["diagnostics"][key] for c in cases]
        ratios[key] = [values[i-1] <= GATES.ratio_floor ? nothing : values[i]/values[i-1] for i in 2:3]
        for i in 2:3
            check(values[i] <= GATES.ratio_floor || (ratios[key][i-1] !== nothing &&
                ratios[key][i-1] <= GATES.refinement_ratio), "Refinement rate failed: $key")
        end
    end
    ratios
end

function write_profiles(io, name, sim)
    p = sim.electric_potential; f = sim.electric_field
    pt = ticks(p.grid); ft = ticks(f.grid); fields = project_field(f.data, ft.phi)
    for idx in CartesianIndices(p.data)
        i,j,k = Tuple(idx)
        println(io,join((name,"potential",pt.r[i],pt.phi[j],pt.z[k],p.data[idx],"","","",Int(sim.point_types.data[idx])),','))
    end
    for idx in CartesianIndices(f.data)
        i,j,k = Tuple(idx)
        println(io,join((name,"field",ft.r[i],ft.phi[j],ft.z[k],"",fields.er[idx],fields.ep[idx],fields.ez[idx],""),','))
    end
    flush(io)
end

function solve_case!(item, n, va, vb, config, io)
    item["nodes"]=n; item["Va_V"]=va; item["Vb_V"]=vb; item["stage"]="initialization"
    cfg = deepcopy(config)
    contacts = only(cfg["detectors"])["contacts"]
    contacts[1]["potential"]=va; contacts[2]["potential"]=vb
    sim = SSD.Simulation{Float64}(cfg)
    grid = make_grid(n)
    item["requested_ticks"]=tickdict(ticks(grid))
    SSD.apply_initial_state!(sim, SSD.ElectricPotential, grid;
        depletion_handling=false, paint_contacts=false, not_only_paint_contacts=true)
    item["sources"]=source_check(sim)
    item["initial_point_bits"]=vec(Int.(sim.point_types.data))
    validate_masks(ticks(grid).r, sim.point_types.data)
    scale = va == vb ? maximum(abs,sim.electric_potential.data) : abs(vb-va)
    item["effective_SSD_stop_V"]=SOLVER.relative_limit*scale
    common = (device_array_type=Array, use_nthreads=SOLVER.threads,
        depletion_handling=false, paint_contacts=false, not_only_paint_contacts=true,
        sor_consts=(1.4,1.85), n_iterations_between_checks=SOLVER.check_interval, verbose=false)
    item["stage"]="potential_solve"
    started = time_ns()
    # initialize=true is essential: SSD skips its first relaxation when false.
    # Reinitialization uses the same explicit grid and geometry-only contact values.
    SSD.calculate_electric_potential!(sim; common..., grid, initialize=true,
        refinement_limits=Float64[], convergence_limit=SOLVER.relative_limit,
        max_n_iterations=SOLVER.initial_iterations)
    before = copy(sim.electric_potential.data)
    update = SSD.update_till_convergence!(sim, SSD.ElectricPotential, SOLVER.relative_limit;
        common..., max_n_iterations=SOLVER.verification_iterations)
    item["potential_solve_seconds"]=(time_ns()-started)/1e9
    item["SSD_last_update_V"]=update
    item["verification_change_V"]=maximum(abs,sim.electric_potential.data.-before)
    SSD.mark_bits!(sim)
    item["final_ticks"]=tickdict(ticks(sim.electric_potential.grid))
    item["final_dimensions"]=collect(size(sim.electric_potential.data))
    item["final_point_bits"]=vec(Int.(sim.point_types.data))
    item["stage"]="field_and_diagnostics"
    SSD.calculate_electric_field!(sim; n_points_in_φ=8, use_nthreads=SOLVER.threads)
    item["field_ticks"]=tickdict(ticks(sim.electric_field.grid))
    write_profiles(io,item["name"],sim)
    validate_ticks(ticks(sim.electric_potential.grid), requested_ticks(n))
    ft = ticks(sim.electric_field.grid)
    check(ft.r == requested_ticks(n).r && ft.z == requested_ticks(n).z, "Field grid changed r/z ticks")
    validate_masks(ft.r,sim.point_types.data)
    item["final_sources"]=source_check(sim)
    contact_error = 0.0
    for (lo,hi,value) in ((0.005,INNER,va),(OUTER,0.035,vb))
        contact_indices=findall(r -> lo <= r <= hi, ft.r)
        contact_error=max(contact_error,maximum(abs,sim.electric_potential.data[contact_indices,:,:].-value))
    end
    item["all_contact_nodes_error_V"]=contact_error
    indices = findall(r -> INNER <= r <= OUTER, ft.r)
    fields = project_field(sim.electric_field.data,ft.phi)
    p = copy(sim.electric_potential.data[indices,:,:])
    er = fields.er[indices,:,:]; ep = fields.ep[indices,:,:]; ez = fields.ez[indices,:,:]
    item["diagnostics"]=diagnostics(ft.r[indices],p,er,ep,ez,va,vb)
    item["stage"]="gates"
    check(contact_error <= GATES.contact_V, "Electrode interior potential enforcement failed")
    check(isfinite(update) && update <= GATES.update_V && update <= SOLVER.relative_limit*scale,
        "SSD iteration gate failed (returned update is not a native residual)")
    check(item["verification_change_V"] <= GATES.continuation_V, "Continuation changed potential too much")
    enforce_diagnostics(item["diagnostics"],va,vb; finest=n==65)
    item["status"]="passed_case"
    (potential=p, er=er)
end

function provenance()
    check(v"1.13" <= VERSION < v"1.14", "Use the reviewed Julia 1.13.x environment")
    active = Base.active_project()
    check(active !== nothing && realpath(active) == realpath(joinpath(@__DIR__, "Project.toml")),
        "Use --project=simulation for this CPU verification")
    actual_manifest = Base.project_file_manifest_path(active)
    check(actual_manifest !== nothing && realpath(actual_manifest) == realpath(joinpath(@__DIR__, "Manifest.toml")),
        "The selected manifest differs from the reviewed CPU lockfile")
    check(pkgversion(SSD) == v"0.11.8", "SSD 0.11.8 required")
    example = SSD.SSD_examples[:InfiniteCoaxialCapacitor]
    check(hashfile(example) == EXAMPLE_HASH, "Upstream example hash changed")
    package = dirname(dirname(pathof(SSD)))
    files = Dict{String,String}()
    for (dir,_,names) in walkdir(joinpath(package,"src")), name in sort(names)
        path=joinpath(dir,name)
        files[replace(relpath(path,package),'\\'=>'/')]=hashfile(path)
    end
    tree = join([k*":"*files[k] for k in sort(collect(keys(files)))],"\n")
    manifest = TOML.parsefile(joinpath(@__DIR__,"Manifest.toml"))
    entry = only(manifest["deps"]["SolidStateDetectors"])
    check(entry["version"] == "0.11.8", "Manifest SSD version mismatch")
    Dict("julia_version"=>string(VERSION),"SSD_version"=>string(pkgversion(SSD)),
        "manifest_sha256"=>hashfile(joinpath(@__DIR__,"Manifest.toml")),
        "SSD_manifest_tree_sha1"=>entry["git-tree-sha1"], "example_sha256"=>hashfile(example),
        "SSD_source_inventory_sha256"=>bytes2hex(sha256(tree)), "SSD_source_files_sha256"=>files,
        "verifier_sha256"=>hashfile(@__FILE__),
        "reference_verifier_sha256"=>hashfile(joinpath(@__DIR__,"verify_electrostatics.jl")),
        "test_sha256"=>hashfile(joinpath(@__DIR__,"test_ssd_electrostatics.jl")))
end

function run(output)
    out=A.output_path(output); mkpath(out)
    report=Dict{String,Any}("status"=>"running", "cases"=>Any[],
        "scope"=>"Synthetic homogeneous source-free SSD annulus; no AK02, Li, CCE, electronics or experimental validation",
        "analytic_faces_m"=>[INNER,OUTER], "precision"=>"Float64", "backend"=>"CPU Array",
        "random_seed"=>nothing, "randomness"=>"none", "depletion_handling"=>false,
        "adaptive_refinement"=>false, "paint_contacts"=>false,
        "gates"=>Dict(string(k)=>v for (k,v) in pairs(GATES)),
        "solver"=>Dict(string(k)=>v for (k,v) in pairs(SOLVER)),
        "iteration_budget_note"=>"At most 49000 initial plus 1000 verification iterations per case; SSD does not return performed counts. No continuation retries.",
        "native_residual"=>nothing,
        "operator_interpretation"=>"SSD update is an iteration diagnostic, not a residual. Reference midpoint FV metrics import unchanged SSD nodal potentials; operator equivalence is not established and machine-zero FV gates are not imposed.",
        "field_mask"=>"Interior: all annular nodes excluding the two contact faces. Both faces reported separately. All axial slices and expanded azimuths retained.",
        "timing_note"=>"Potential and end-to-end wall time include first-use compilation; no production timing claim.")
    started=time_ns()
    try
        report["provenance"]=provenance()
        config=deepcopy(SSD.Simulation{Float64}(SSD.SSD_examples[:InfiniteCoaxialCapacitor]).config_dict)
        validate_config(config); report["example_config"]=config
        open(joinpath(out,"profiles.csv"),"w") do io
            println(io,"case,quantity,r_m,phi_rad,z_m,potential_V,Er_V_m,Ephi_V_m,Ez_V_m,point_bits")
            results=Dict{String,Any}()
            specs=[("grid$n",n,0.0,10.0) for n in COUNTS]
            append!(specs,[("zero",33,0.0,0.0),("equal",33,42.0,42.0),
                ("reversed",33,10.0,0.0),("offset",33,42.0,52.0)])
            for (name,n,va,vb) in specs
                item=Dict{String,Any}("name"=>name,"status"=>"running")
                push!(report["cases"],item)
                try
                    results[name]=solve_case!(item,n,va,vb,config,io)
                catch e
                    item["status"]="failed"; item["error"]=sprint(showerror,e)
                end
            end
            check(all(c["status"] == "passed_case" for c in report["cases"]), "One or more SSD cases failed; inspect retained evidence")
            report["refinement_ratios"]=enforce_refinement(report["cases"][1:3])
            base=results["grid33"]; reverse=results["reversed"]; offset=results["offset"]
            controls=Dict("reversal_V"=>maximum(abs,reverse.potential.+base.potential.-10),
                "reversal_field_V_m"=>maximum(abs,reverse.er.+base.er),
                "offset_V"=>maximum(abs,offset.potential.-base.potential.-42),
                "offset_field_V_m"=>maximum(abs,offset.er.-base.er))
            report["bias_controls"]=controls
            check(max(controls["reversal_V"],controls["offset_V"]) <= GATES.control_V &&
                max(controls["reversal_field_V_m"],controls["offset_field_V_m"]) <= GATES.control_field_V_m,
                "Bias reversal/offset covariance failed")
        end
        report["status"]="passed_synthetic_SSD_electrostatics_only"
    catch e
        report["status"]="failed"; report["error"]=sprint(showerror,e)
        rethrow()
    finally
        report["end_to_end_seconds"]=(time_ns()-started)/1e9
        open(io->JSON.print(io,report,2),joinpath(out,"run.json"),"w")
    end
    report
end

function main(args)
    check(length(args)==2 && args[1]=="--output",
        "Usage: julia --project=simulation simulation/verify_ssd_electrostatics.jl --output .local/NEW")
    run(args[2])
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    SSDElectrostatics.main(ARGS)
end
