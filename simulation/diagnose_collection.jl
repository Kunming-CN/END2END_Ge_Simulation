# Bounded endpoint/depth diagnostics; no calibrated Li CCE or new carrier model.
isdefined(@__MODULE__, :SSDReplay) || include("replay.jl")
module CollectionDiagnostics
using ..SSDQuickstart, ..SSDReplay
using SolidStateDetectors, Unitful, LinearAlgebra, Random, Statistics, JSON
const SSD=SolidStateDetectors
const Q=SSDQuickstart
const R=SSDReplay
const DEPTHS_MM=[0.01,0.05,0.1,0.2,0.3,0.4,0.45,0.5,0.6,0.8,1.0,2.0]
xyz(p)=[p.x,p.y,p.z]
require(ok,msg)=ok ? nothing : throw(ArgumentError(msg))
function stop_label(contacts, at_limit, stationary, zero_field)
    !isempty(contacts) ? "geometric_contact" : at_limit ? "step_limit" :
        stationary && zero_field ? "stationary_in_zero_field" : "unresolved_stop"
end
function observation(sim, p, field, wp)
    e=SSD.get_velocity_vector(field,CylindricalPoint(p)) # This helper interpolates the input E, in V/m.
    bits=sim.point_types[p]
    idm=sim.detector.semiconductor.impurity_density_model
    net=SSD.get_impurity_density(idm,p)/1e6
    donor=hasproperty(idm,:surface_imp_model) ? SSD.get_impurity_density(idm.surface_imp_model,p)/1e6 : 0.0
    idx=SSD.find_closest_gridpoint(p,sim.point_types.grid)
    fraction=sim.imp_scale.data[idx...]
    distances=[Dict("contact_id"=>c.id,"distance_mm"=>1000*SSD.ConstructiveSolidGeometry.distance_to_surface(p,c.geometry)) for c in sim.detector.contacts]
    Dict("position_mm"=>1000 .* xyz(p),"field_V_per_cm"=>xyz(e)./100,
        "field_magnitude_V_per_cm"=>norm(e)/100,"field_exactly_zero"=>iszero(norm(e)),
        "weighting_potential"=>SSD.get_interpolation(wp,p,SSD.Cylindrical),
        "nearest_grid_indices"=>collect(idx),"nearest_grid_bits"=>Int(bits),
        "nearest_grid_undepleted"=>SSD.is_undepleted_point_type(bits),
        "nearest_grid_inactive"=>SSD.is_in_inactive_layer(bits),
        "nearest_grid_fixed"=>SSD.is_fixed_point_type(bits),"nearest_grid_impurity_scale"=>fraction,
        "net_impurity_cm3"=>net,"li_donor_cm3"=>donor,
        "doping_sign"=>net>0 ? "n" : net<0 ? "p" : "compensated",
        "geometric_contacts"=>[c.id for c in sim.detector.contacts if p in c.geometry],
        "contact_distances"=>distances)
end
function one_point(sim, position_mm, dt_ns, field, wp; horizon_ns=10000.0)
    require(all(isfinite,position_mm)&&isfinite(dt_ns)&&0<dt_ns<=horizon_ns,"Invalid point/time")
    p=CartesianPoint{Float64}((position_mm./1000)...)
    require(p in sim.detector.semiconductor && !any(c->p in c.geometry,sim.detector.contacts),"Invalid diagnostic deposit")
    maxsteps=ceil(Int,horizon_ns/dt_ns)+1
    evt=Event([p],[1.0u"keV"])
    drift_charges!(evt,sim;Δt=dt_ns*u"ns",max_nsteps=maxsteps,geometry_check=true,
        diffusion=false,self_repulsion=false,end_drift_when_no_field=true,verbose=false)
    require(xyz(evt.locations[1][1])==xyz(p),"Input point moved")
    SSD.get_signal!(evt,sim,1;Δt=dt_ns*u"ns",signal_unit=u"keV")
    actual=Float64(ustrip(u"keV",last(evt.waveforms[1].signal)))
    original=sim.detector
    ideal=NaN
    try
        sim.detector=SolidStateDetector(original,SSD.NoChargeTrappingModel{Float64}())
        idealwave=SSD.get_signal(sim,evt.drift_paths,[1000.0],1;Δt=dt_ns*u"ns",signal_unit=u"keV")
        ideal=Float64(ustrip(u"keV",last(idealwave.signal)))
    finally
        sim.detector=original
    end
    endpoints=Dict{String,Any}()
    drift=only(evt.drift_paths)
    for (species,path,times) in (("electron",drift.e_path,drift.timestamps_e),("hole",drift.h_path,drift.timestamps_h))
        obs=observation(sim,last(path),field,wp)
        stationary=length(path)>1 && xyz(path[end])==xyz(path[end-1])
        obs["last_displacement_mm"]=length(path)>1 ? 1000*norm(path[end]-path[end-1]) : 0.0
        obs["samples"]=length(path); obs["end_time_ns"]=last(times)*1e9
        obs["status"]=stop_label(obs["geometric_contacts"],length(path)>=maxsteps,stationary,obs["field_exactly_zero"])
        endpoints[species]=obs
    end
    analytic=endpoints["hole"]["weighting_potential"]-endpoints["electron"]["weighting_potential"]
    require(isfinite(actual)&&isfinite(ideal)&&abs(ideal-analytic)<1e-10,"No-trapping Ramo endpoint check failed")
    Dict("dt_ns"=>dt_ns,"horizon_ns"=>horizon_ns,"deposited_energy_keV"=>1.0,
        "start"=>observation(sim,p,field,wp),"endpoints"=>endpoints,
        "original_trapping_fraction"=>actual,"same_path_no_trapping_fraction"=>ideal,
        "ramo_endpoint_difference"=>analytic,"ramo_check_error"=>ideal-analytic,
        "same_path_trapping_difference"=>ideal-actual)
end
function mark_complete!(report; verify=Q.verify_model_files)
    verify()
    report["status"]="completed_diagnostics_only"
end
function diffusion_check(sim; n=2048, steps=201, dt_ns=2.0, seed=260926)
    require(n>=1024 && steps>=2,"Too few samples for the predefined statistical test")
    p=CartesianPoint{Float64}(0.010,0.0,0.005)
    require(p in sim.detector.semiconductor,"Synthetic diffusion origin outside detector")
    original_field=sim.electric_field
    require(!hasmethod(SSD.calculate_mobility,Tuple{typeof(sim.detector.semiconductor.charge_drift_model),typeof(p),Type{SSD.Electron}}),
        "This analytic diagnostic explicitly tests the material-De/Dh fallback only")
    results=Any[]
    try
        sim.electric_field=SSD.ElectricField(fill(SSD.SVector{3,Float64}(0,0,0),size(original_field.data)),original_field.grid)
        for stop in (true,false)
            Random.seed!(seed)
            event=Event([fill(p,n)],[fill((1.0/n)*u"keV",n)])
            drift_charges!(event,sim;Δt=dt_ns*u"ns",max_nsteps=steps,geometry_check=true,
                diffusion=true,self_repulsion=false,end_drift_when_no_field=stop,verbose=false)
            for (species,attr,timeattr,Dattr) in (("electron",:e_path,:timestamps_e,:De),("hole",:h_path,:timestamps_h,:Dh))
                paths=[getproperty(d,attr) for d in event.drift_paths]
                require(all(all(q->q in sim.detector.semiconductor,path) for path in paths),"Diffusion diagnostic hit a boundary")
                delta=reduce(vcat,[permutedims(xyz(last(path))-xyz(p)) for path in paths])
                elapsed=last(getproperty(first(event.drift_paths),timeattr))
                if stop
                    require(all(iszero,delta)&&all(length(path)==2 for path in paths),"Zero-field stop behavior changed")
                    push!(results,Dict("species"=>species,"stop_at_zero_field"=>true,"max_displacement_m"=>maximum(abs,delta),"samples_per_path"=>2))
                else
                    require(all(length(path)==steps for path in paths),"Unexpected early termination in diffusion test")
                    D=Float64(ustrip(u"m^2/s",getproperty(sim.detector.semiconductor.material,Dattr)))
                    hop=sqrt(6D*dt_ns*1e-9)
                    clearance=SSD.ConstructiveSolidGeometry.distance_to_surface(p,sim.detector.semiconductor.geometry)
                    radius=maximum(norm(q-p) for path in paths for q in path)
                    require(radius+hop<clearance,"Cannot exclude boundary interaction in the diffusion check")
                    require(all(isapprox(norm(path[k]-path[k-1]),hop;rtol=1e-10,atol=1e-14) for path in paths for k in 2:length(path)),
                        "Diffusion step projected, stopped or otherwise changed")
                    require(isapprox(elapsed,(steps-1)*dt_ns*1e-9;rtol=1e-12,atol=1e-18),"Diffusion duration changed")
                    expected=2D*elapsed
                    means=vec(mean(delta;dims=1)); variances=vec(var(delta;dims=1))
                    mean_gate=6sqrt(expected/n)
                    relative_variance_gate=6sqrt(2/(n-1))
                    require(all(abs.(means).<=mean_gate)&&all(abs.(variances./expected .-1).<=relative_variance_gate),
                        "Diffusion moments outside prospectively fixed six-standard-error gates")
                    push!(results,Dict("species"=>species,"stop_at_zero_field"=>false,"D_m2_s"=>D,
                        "duration_ns"=>elapsed*1e9,"samples_per_path"=>steps,
                        "initial_surface_clearance_m"=>clearance,"max_excursion_m"=>radius,"fixed_hop_m"=>hop,"all_hops_full"=>true,"mean_m"=>means,
                        "variance_m2"=>variances,"expected_per_axis_variance_m2"=>expected,
                        "mean_abs_gate_m"=>mean_gate,"relative_variance_gate"=>relative_variance_gate))
                end
            end
        end
    finally
        sim.electric_field=original_field
    end
    Dict("status"=>"passed","seed"=>seed,"carriers_per_species"=>n,"time_step_ns"=>dt_ns,"results"=>results,
        "scope"=>"Synthetic zero field, material De/Dh fallback in the unmodified drift algorithm; not AK02 mobility-tied or surface diffusion validation")
end
function main(args=ARGS)
    length(args)==2 && args[1]=="--output" || throw(ArgumentError("Usage: julia --project=simulation simulation/diagnose_collection.jl --output .local/NEW"))
    Q.environment("cpu"); Q.verify_model_files()
    output=Q.reserve_output(args[2])
    report=Dict{String,Any}("status"=>"running","cases"=>Any[],"temperature_K"=>77.0,
        "source_hashes"=>Dict(n=>Q.sha256file(joinpath(@__DIR__,n)) for n in ("run.jl","replay.jl","diagnose_collection.jl")),
        "environment"=>Q.environment("cpu"),"canonical_model_files_unchanged"=>true,"potential_recheck_limit"=>8,
        "limitations"=>["Radial mid-height synthetic point scans; not efficiency or measured CCE.",
          "Only two refinement settings and three time steps: sensitivity, not established convergence.",
          "No diffusion in depth scans; zero-field termination intentionally retained for endpoint diagnosis.",
          "No-trapping signal is recalculated on exactly the same paths; no geometrical collection is inferred.",
          "Grid flags and impurity scale are nearest-grid values, not exact continuous region boundaries.",
          "All model lifetimes, impurity and mobility assumptions remain uncalibrated inputs."])
    csv=nothing
    try
        csv=open(joinpath(output,"depth-scan.csv"),"w")
        println(csv,"model,min_grid_mm,depth_mm,dt_ns,start_field_V_cm,li_donor_cm3,net_impurity_cm3,original_fraction,no_trapping_fraction,e_status,e_distance_outer_mm,e_weighting,e_field_V_cm,h_status")
        for model in ("AK02","SAP22"), mingrid in (0.05,0.025)
            println("DIAGNOSING ",model," / minimum refinement ",mingrid," mm")
            sim,_=R.setup_simulation(model;temperature=77.0)
            cfg=Q.parse_args(["--model",model,"--position-mm","3,0,5","--precision","64","--min-grid-mm",string(mingrid),
                "--max-iterations","50000","--output",joinpath(output,"unused-solver-output")])
            item=Dict{String,Any}("model"=>model,"model_sha256"=>Q.model_entry(model)["model_sha256"],"min_grid_mm"=>mingrid,"status"=>"running","points"=>Any[])
            push!(report["cases"],item)
            item["continuation_checks"]=Any[]
            observer=check->push!(item["continuation_checks"],check)
            solver,times=Q.solve_fields!(sim,cfg,Q.prepare_backend("cpu");sor_consts=1.0,potential_rechecks=8,iteration_observer=observer)
            item["solver"]=solver; item["timings"]=times
            field=SSD.interpolated_vectorfield(sim.electric_field)
            wp=SSD.interpolated_scalarfield(sim.weighting_potentials[1])
            geometry=sim.detector.semiconductor.geometry
            radius=maximum(geometry.r)*1000
            midz=(minimum(geometry.z)+maximum(geometry.z))*500
            for depth in DEPTHS_MM, dt in (1.0,2.0,4.0)
                row=one_point(sim,[radius-depth,0.0,midz],dt,field,wp)
                row["depth_mm"]=depth; push!(item["points"],row)
                e=row["endpoints"]["electron"]; h=row["endpoints"]["hole"]; start=row["start"]
                distance=only(filter(x->x["contact_id"]==2,e["contact_distances"]))["distance_mm"]
                println(csv,join([model,mingrid,depth,dt,start["field_magnitude_V_per_cm"],start["li_donor_cm3"],start["net_impurity_cm3"],
                    row["original_trapping_fraction"],row["same_path_no_trapping_fraction"],e["status"],distance,e["weighting_potential"],e["field_magnitude_V_per_cm"],h["status"]],','))
            end
            item["status"]="completed"
            if model=="SAP22" && mingrid==0.05
                println("Testing synthetic zero-field diffusion switch and moments...")
                report["diffusion_test"]=diffusion_check(sim)
            end
        end
        mark_complete!(report)
    catch err
        report["status"]="failed"; report["error"]=sprint(showerror,err)
        if !isempty(report["cases"]) && last(report["cases"])["status"]=="running"
            last(report["cases"])["status"]="failed"
            last(report["cases"])["error"]=sprint(showerror,err)
        end
        rethrow()
    finally
        csv!==nothing && close(csv)
        Q.save_json(joinpath(output,"run.json"),report)
    end
    println("Diagnostics saved: ",output)
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    CollectionDiagnostics.main()
end
