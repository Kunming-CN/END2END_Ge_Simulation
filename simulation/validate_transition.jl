# Controlled transition-grid and mobility-diffusion verification; no calibrated CCE.
isdefined(@__MODULE__, :CollectionDiagnostics) || include("diagnose_collection.jl")
module TransitionValidation
using ..CollectionDiagnostics
using SolidStateDetectors, Unitful, LinearAlgebra, Random, Statistics, JSON
const C=CollectionDiagnostics
const Q=C.Q
const R=C.R
const SSD=SolidStateDetectors
const FIELD_CASES=[("min50",0.05,2.0),("min25",0.025,2.0),("min12p5",0.0125,2.0),("cap100",0.025,0.1),("cap50",0.0125,0.05),("cap25",0.0125,0.025)]
require(ok,msg)=ok ? nothing : throw(ArgumentError(msg))
function brackets(depths,values,threshold)
    require(length(depths)==length(values)&&all(diff(depths).>0),"Invalid profile axis")
    require(all(isfinite,values)&&isfinite(threshold),"Nonfinite profile")
    i=findfirst(v->v>threshold,values)
    isnothing(i) ? nothing : Dict("below_mm"=>i==1 ? nothing : depths[i-1],"above_mm"=>depths[i],"threshold_V_cm"=>threshold)
end
function pn_depth(sim)
    g=sim.detector.semiconductor.geometry
    radius=maximum(g.r); z=(minimum(g.z)+maximum(g.z))/2
    density(d)=SSD.get_impurity_density(sim.detector.semiconductor.impurity_density_model,CartesianPoint{Float64}(radius-d,0,z))
    lo=0.0; hi=0.002
    require(density(lo)>0&&density(hi)<0,"No pn root in prescribed diagnostic interval")
    for _ in 1:60
        mid=(lo+hi)/2
        if density(mid)>0; lo=mid; else; hi=mid; end
    end
    1000*(lo+hi)/2
end
function solve_case(output,min_grid,max_grid,item; rechecks=8)
    sim,_=R.setup_simulation("AK02";temperature=77.0)
    cfg=Q.parse_args(["--model","AK02","--position-mm","3,0,5","--precision","64",
        "--min-grid-mm",string(min_grid),"--max-grid-mm",string(max_grid),"--max-iterations","50000",
        "--output",joinpath(output,"unused")])
    item["potential_recheck_limit"]=rechecks
    item["continuation_checks"]=Any[]
    observer=x->push!(item["continuation_checks"],x)
    item["solver"],item["timings"]=Q.solve_fields!(sim,cfg,Q.prepare_backend("cpu");
        sor_consts=1.0,potential_rechecks=rechecks,iteration_observer=observer)
    sim,cfg
end
function field_profiles(output,report; cases=FIELD_CASES[1:end-1])
    simulations=Any[]
    depths=collect(250:2:850)./1000
    report["prescribed_case_names"]=[c[1] for c in cases]
    report["cases"]=Any[]
    open(joinpath(output,"profiles.csv"),"w") do csv
        println(csv,"case,depth_mm,field_V_cm,weighting,nearest_bits,nearest_r_mm,nearest_z_mm,impurity_scale,net_doping_cm3")
        for (name,min_grid,max_grid) in cases
            println("PROFILE ",name," min=",min_grid," max=",max_grid)
            item=Dict{String,Any}("name"=>name,"status"=>"running","min_grid_mm"=>min_grid,"max_grid_mm"=>max_grid)
            push!(report["cases"],item)
            sim,cfg=solve_case(output,min_grid,max_grid,item;rechecks=64)
            field=SSD.interpolated_vectorfield(sim.electric_field)
            wp=SSD.interpolated_scalarfield(sim.weighting_potentials[1])
            g=sim.detector.semiconductor.geometry; radius=1000 * maximum(g.r); z=500 * (minimum(g.z)+maximum(g.z))
            item["electric_r_ticks_mm"]=1000 .* collect(sim.electric_potential.grid.axes[1])
            item["electric_z_ticks_mm"]=1000 .* collect(sim.electric_potential.grid.axes[3])
            item["weighting_r_ticks_mm"]=1000 .* collect(sim.weighting_potentials[1].grid.axes[1])
            item["weighting_z_ticks_mm"]=1000 .* collect(sim.weighting_potentials[1].grid.axes[3])
            values=Float64[]; weights=Float64[]
            for depth in depths
                p=CartesianPoint{Float64}((radius-depth)/1000,0,z/1000)
                obs=C.observation(sim,p,field,wp)
                push!(values,obs["field_magnitude_V_per_cm"]); push!(weights,obs["weighting_potential"])
                idx=obs["nearest_grid_indices"]
                println(csv,join([name,depth,last(values),last(weights),obs["nearest_grid_bits"],
                    item["electric_r_ticks_mm"][idx[1]],item["electric_z_ticks_mm"][idx[3]],
                    obs["nearest_grid_impurity_scale"],obs["net_impurity_cm3"]],','))
            end
            item["pn_depth_mm_from_doping_only"]=pn_depth(sim)
            item["field_crossing_brackets"]=[brackets(depths,values,t) for t in (0.0,1e-6,1.0,10.0)]
            item["threshold_note"]="Reporting thresholds only: no field was clipped or changed; none is a measured FDD/FCCD"
            item["tracked_points"]=Any[]
            for depth in collect(450:10:650)./1000
                row=C.one_point(sim,[radius-depth,0.0,z],2.0,field,wp)
                row["depth_mm"]=depth; push!(item["tracked_points"],row)
            end
            item["status"]="completed"; push!(simulations,sim)
        end
    end
    # Cross-evaluate weighting only on fixed endpoints: deliberately hybrid diagnostics.
    report["fixed_endpoint_weighting_matrix"]=Any[]
    for depth in (0.5,0.6), (i,fromcase) in enumerate(report["cases"])
        row=only(filter(r->r["depth_mm"]==depth,fromcase["tracked_points"]))
        e=CartesianPoint{Float64}((row["endpoints"]["electron"]["position_mm"]./1000)...)
        h=CartesianPoint{Float64}((row["endpoints"]["hole"]["position_mm"]./1000)...)
        for (j,sim) in enumerate(simulations)
            wp=SSD.interpolated_scalarfield(sim.weighting_potentials[1])
            value=SSD.get_interpolation(wp,h,SSD.Cylindrical)-SSD.get_interpolation(wp,e,SSD.Cylindrical)
            require(isfinite(value),"Nonfinite hybrid weighting diagnostic")
            i==j&&require(isapprox(value,row["same_path_no_trapping_fraction"];atol=1e-10,rtol=0),"Diagonal Ramo check failed")
            push!(report["fixed_endpoint_weighting_matrix"],Dict("depth_mm"=>depth,"path_case"=>fromcase["name"],
                "weighting_case"=>report["cases"][j]["name"],"endpoint_difference"=>value))
        end
    end
    report["matrix_warning"]="Hybrid endpoint/weighting combinations isolate numerical dependence; they are not self-consistent detector predictions"
end

function frozen_model(cdm,point)
    constants=[SSD.ConstantImpurityDensity{Float64}(SSD.get_impurity_density(getproperty(cdm,k),point))
        for k in (:neutral_imp_model,:bulk_imp_model,:surface_imp_model)]
    SSD.InactiveLayerChargeDriftModel{Float64}(cdm.temperature,constants...)
end
function moments(delta,D,elapsed,n)
    require(n isa Integer && n>=2 && size(delta)==(n,3) && all(isfinite,delta),"Invalid moment samples")
    require(isfinite(D)&&D>0&&isfinite(elapsed)&&elapsed>0,"Invalid diffusion coefficient or duration")
    expected=2D*elapsed
    require(isfinite(expected)&&expected>0,"Invalid Einstein variance")
    means=vec(mean(delta;dims=1)); variances=vec(var(delta;dims=1))
    covariance=cov(delta;dims=1); covariance_gate=6expected/sqrt(n-1)
    require(all(abs(covariance[i,j])<=covariance_gate for i in 1:3 for j in 1:3 if i!=j),"Diffusion covariance gate failed")
    mean_gate=6sqrt(expected/n); variance_gate=6sqrt(2/(n-1))
    require(all(abs.(means).<=mean_gate)&&all(abs.(variances./expected .-1).<=variance_gate),"Diffusion moment gate failed")
    Dict("mean_m"=>means,"variance_m2"=>variances,"expected_variance_m2"=>expected,
        "mean_gate_m"=>mean_gate,"relative_variance_gate"=>variance_gate,
        "cross_covariances_m2"=>[covariance[1,2],covariance[1,3],covariance[2,3]],"covariance_gate_m2"=>covariance_gate)
end
function with_restored_state(work,sim,report)
    original_detector=sim.detector; original_field=sim.electric_field
    try
        work()
    finally
        sim.detector=original_detector; sim.electric_field=original_field
        report["restored_state"]=sim.detector===original_detector&&sim.electric_field===original_field
    end
end

function mobility_diffusion(output,report; n=2048)
    require(n isa Integer&&1024<=n<=8192,"Controlled parcel count must be1024..8192")
    report["setup"]=Dict{String,Any}("status"=>"running","stage"=>"potential_solve")
    sim,cfg=solve_case(output,0.05,2.0,report["setup"])
    report["setup"]["stage"]="sampling"
    original_detector=sim.detector; original_field=sim.electric_field
    original_cdm=original_detector.semiconductor.charge_drift_model
    report["samples"]=Any[]
    p=CartesianPoint{Float64}(0.010,0,0.0047)
    report["meaning"]="Controlled homogeneous-mobility clone of AK02 coefficients; numerical parcels, not an AK02 charge cloud or spatially varying diffusion validation"
    with_restored_state(sim,report) do
        sim.electric_field=SSD.ElectricField(fill(SSD.SVector{3,Float64}(0,0,0),size(original_field.data)),original_field.grid)
        for (index,depth) in enumerate((0.1,0.5,1.0)), dt in (1.0,2.0,4.0)
            dt_ns=dt; steps=round(Int,400/dt_ns)+1
            reference=CartesianPoint{Float64}((12.65-depth)/1000,0,0.0047)
            cdm=frozen_model(original_cdm,reference)
            sim.detector=SSD.SolidStateDetector(original_detector,cdm)
            for carrier in (SSD.Electron,SSD.Hole)
                require(hasmethod(SSD.calculate_mobility,Tuple{typeof(cdm),typeof(p),Type{carrier}}),"Mobility-tied branch unavailable")
                require(SSD.calculate_mobility(cdm,p,carrier)==SSD.calculate_mobility(original_cdm,reference,carrier),"Frozen coefficient differs")
            end
            Random.seed!(260926+10index+Int(dt_ns))
            event=Event([fill(p,n)],[fill((1.0/n)*u"keV",n)])
            drift_charges!(event,sim;Δt=dt_ns*u"ns",max_nsteps=steps,geometry_check=true,
                diffusion=true,self_repulsion=false,end_drift_when_no_field=false,verbose=false)
            for (species,carrier,attr,tattr) in (("electron",SSD.Electron,:e_path,:timestamps_e),("hole",SSD.Hole,:h_path,:timestamps_h))
                mu=SSD.calculate_mobility(cdm,p,carrier)
                D=mu*77.0*1.380649e-23/1.602176634e-19
                hop=sqrt(6D*dt_ns*1e-9)
                paths=[getproperty(d,attr) for d in event.drift_paths]
                require(all(length(v)==steps for v in paths),"Controlled path ended early")
                elapsed=last(getproperty(first(event.drift_paths),tattr))
                require(isapprox(elapsed,(steps-1)*dt_ns*1e-9;rtol=1e-12,atol=1e-18),"Controlled duration mismatch")
                clearance=SSD.ConstructiveSolidGeometry.distance_to_surface(p,sim.detector.semiconductor.geometry)
                excursion=maximum(norm(q-p) for v in paths for q in v)
                require(excursion+hop<clearance,"Cannot exclude boundary effects")
                require(all(isapprox(norm(v[k]-v[k-1]),hop;rtol=1e-8,atol=1e-14) for v in paths for k in 2:steps),"Mobility hop disagrees with Einstein coefficient")
                delta=reduce(vcat,[permutedims(C.xyz(last(v))-C.xyz(p)) for v in paths])
                measured=moments(delta,D,elapsed,n)
                merge!(measured,Dict("coefficient_depth_mm"=>depth,"species"=>species,"mu_m2_V_s"=>mu,"D_m2_s"=>D,
                    "seed"=>260926+10index+Int(dt_ns),"dt_ns"=>dt_ns,"parcels"=>n,"duration_ns"=>elapsed*1e9,"hop_m"=>hop,
                    "max_excursion_m"=>excursion,"surface_clearance_m"=>clearance,"all_hops_verified"=>true))
                push!(report["samples"],measured)
                println("MOBILITY ",depth," mm ",species," D=",D," m2/s; variance ratio=",measured["variance_m2"]./measured["expected_variance_m2"])
            end
        end
    end
    require(sim.detector===original_detector&&sim.electric_field===original_field,"Diagnostic state not restored")
    report["setup"]["status"]="completed"
    report["restored_state"]=true
end
function main(args=ARGS)
    length(args) in (4,6)&&args[1]=="--phase"&&args[3]=="--output"||throw(ArgumentError("Use --phase fields|fine|mobility --output .local/NEW [--parcels 2048]"))
    phase=args[2]; require(phase in ("fields","fine","mobility"),"Unknown phase")
    if length(args)==6
        require(phase=="mobility"&&args[5]=="--parcels","--parcels applies only to mobility")
    end
    parcels=length(args)==6 ? Q.integer(args[6],"parcels",1024,8192) : 2048
    Q.environment("cpu"); Q.verify_model_files(); output=Q.reserve_output(args[4])
    report=Dict{String,Any}("phase"=>phase,"status"=>"running","model"=>"AK02","temperature_K"=>77.0,
        "model_sha256"=>Q.model_entry("AK02")["model_sha256"],"environment"=>Q.environment("cpu"),
        "source_hashes"=>Dict(n=>Q.sha256file(joinpath(@__DIR__,n)) for n in ("run.jl","replay.jl","diagnose_collection.jl","validate_transition.jl")),
        "scope"=>"Numerical/mechanism diagnostics only; physical Li CCE and cryostat predictions remain blocked")
    started=time()
    try
        if phase=="fields"
            field_profiles(output,report)
        elseif phase=="fine"
            field_profiles(output,report;cases=FIELD_CASES[end:end])
        else
            mobility_diffusion(output,report;n=parcels)
        end
        Q.verify_model_files()
        report["status"]="completed_diagnostics_only"
    catch err
        report["status"]="failed"; report["error"]=sprint(showerror,err)
        if haskey(report,"setup") && report["setup"]["status"]=="running"
            report["setup"]["status"]="failed"
            report["setup"]["error"]=sprint(showerror,err)
        end
        if haskey(report,"cases") && !isempty(report["cases"]) && last(report["cases"])["status"]=="running"
            last(report["cases"])["status"]="failed"
            last(report["cases"])["error"]=sprint(showerror,err)
        end
        rethrow()
    finally
        report["runtime_s"]=time()-started
        Q.save_json(joinpath(output,"run.json"),report)
    end
    println("Completed diagnostic phase ",phase,"; output ",output)
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    TransitionValidation.main()
end
