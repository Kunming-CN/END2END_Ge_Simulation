# E-only initialization/axis attribution; frozen native gates live in T.
using SHA
const TRANSITION_AXES_HELPERS=Dict{String,Any}(
    "diagnose_transition_grid.jl"=>"d86470afd235985b13a0bcdb365a4b613bbbd5c577e1a8d30d6db61ce4e33a0e",
    "test_transition_grid.jl"=>"2c4b2cb3c027ed8ebc3c4d2af356d47cdbaf578ebb27467d12001b14071badb4")
for (n,h) in TRANSITION_AXES_HELPERS
    bytes2hex(sha256(read(joinpath(@__DIR__,n))))==h || throw(ArgumentError("Changed helper: $n"))
end
isdefined(@__MODULE__, :TransitionGridDiagnostics) || include("diagnose_transition_grid.jl")
module TransitionAxesDiagnostics
using ..TransitionGridDiagnostics, LinearAlgebra, SHA, JSON
const T=TransitionGridDiagnostics; const Q=T.Q; const R=T.R; const SSD=T.SSD
const require=T.require
const SOURCES=merge(Dict{String,Any}(parentmodule(@__MODULE__).TRANSITION_AXES_HELPERS),
    Dict{String,Any}(n=>Q.sha256file(joinpath(@__DIR__,n)) for n in ("diagnose_transition_axes.jl","test_transition_axes.jl")))
function provenance()
    T.L.check_hashes(@__DIR__,SOURCES)
    Dict{String,Any}("sources"=>copy(SOURCES),"Tprovenance"=>T.provenance())
end
function options(args)
    require(length(args)==2 && args[1]=="--output","Use --output .local/NEW only")
    Q.validate_output(args[2])
end
function crossed_grid(rg,zg;cap=T.LIMITS.points)
    require(0<cap<=T.LIMITS.points && size(rg,1)*size(rg,2)*size(zg,3)<=cap,"Crossed point budget exceeded")
    require(collect(rg.axes[2])==collect(zg.axes[2])==[0.0] && iseven(size(zg,3)),"Axisymmetry/even-z required")
    require(all(SSD.get_boundary_types(rg.axes[i])==SSD.get_boundary_types(zg.axes[i]) && rg.axes[i].interval==zg.axes[i].interval for i in 1:3),"Crossed intervals differ")
    axes=ntuple(i->deepcopy(i==3 ? zg.axes[i] : rg.axes[i]),3)
    g=SSD.CylindricalGrid{Float64}(axes); SSD.check_grid(g); g
end
function identity(p)
    d=Dict{String,Any}(string(k)=>T.digest(getproperty(p,k)) for k in (:q_eff_imp,:q_eff_fix,:ϵ_r,:volume_weights,:sor_const,:point_types,:imp_scale))
    d["geom_weights"]=T.digest.(p.geom_weights)
    d["grid"]=T.gridinfo(p.grid); d["axis_bytes"]=T.digest.(T.axesof(p.grid)); d
end
identity_guard(a,b)=require(isequal(a,b),"Native coefficient/alpha/mask/grid identity changed")
update_mask(p)=(SSD.PointTypeArray(p).&SSD.update_bit).!=0
contacts_ok(item)=get(item,"E_accepted",false) && !isempty(item["E_geometric_contacts"]) && all(c["nodes"]>0 && c["max_error"]<=T.LIMITS.V for c in item["E_geometric_contacts"])
accepted(item)=get(item,"status","")=="accepted_fixed_grid"
budget_failure(err)=any(occursin(s,lowercase(sprint(showerror,err))) for s in ("elapsed limit exceeded","original q iteration gate failed","point budget exceeded"))
exitcode(report)=report["status"]=="invalid_source_or_runtime" ? 1 : report["status"]=="completed_attribution_diagnostics" ? 0 : 2
signedsum(a)=Dict("positive"=>sum(x->max(x,0.0),a;init=0.0),"negative"=>sum(x->min(x,0.0),a;init=0.0))
function finish_budget!(item, elapsed)
    require(isfinite(elapsed)&&elapsed>=0,"Invalid elapsed time")
    item["elapsed_seconds"]=elapsed
    item["within_cooperative_time_budget"]=elapsed<=T.LIMITS.seconds
    if accepted(item) && !item["within_cooperative_time_budget"]
        item["status"]="budget_failed"; item["budget_reason"]="Postprocessing exceeded cooperative case budget"
    end
    item
end
function state_identity(sim)
    Dict{String,Any}(string(k)=>ismissing(getproperty(sim,k)) ? nothing :
        Dict("data"=>T.digest(getproperty(sim,k).data),"axes"=>T.digest.(T.axesof(getproperty(sim,k).grid))) for k in T.STATE)
end
function independent_storage(a,b)
    for key in T.STATE
        x,y=getproperty(a,key),getproperty(b,key)
        (ismissing(x)||ismissing(y)) && continue
        require(!Base.mightalias(x.data,y.data),"Shared mutable state: $key")
    end
    for i in 1:3
        require(!Base.mightalias(a.electric_potential.grid.axes[i].ticks,b.electric_potential.grid.axes[i].ticks),"Shared candidate axis storage")
    end
    true
end
function accounting(sim,p)
    bits=SSD.PointTypeArray(p); update=update_mask(p)
    contact=[any(c->SSD.getpoint(p.grid,Tuple(i)) in c.geometry,sim.detector.contacts) || (bits[i]&SSD.inactive_contact_bit)!=0 for i in CartesianIndices(bits)]
    window=[0.01165<=p.grid.axes[1][i[1]]<=0.01265 && 0.0037<=p.grid.axes[3][i[3]]<=0.0057 for i in CartesianIndices(bits)] .& update
    qi=T.realarray(p,p.q_eff_imp); qf=T.realarray(p,p.q_eff_fix); a=SSD.ImpurityScaleArray(p)
    groups=Dict{String,Any}()
    for (name,mask) in (("update",update),("fixed",.!update),("contact",contact),("transition_update",window))
        groups[name]=Dict{String,Any}("nodes"=>count(mask),"mask_sha256"=>T.digest(Array{UInt8}(mask)),
            "q_imp_raw"=>signedsum(qi[mask]),"q_imp_alpha_scaled"=>signedsum((a.*qi)[mask]),"q_fix_raw"=>signedsum(qf[mask]),
            "q_total_raw"=>signedsum((qi.+qf)[mask]),"q_total_alpha_scaled"=>signedsum((a.*qi.+qf)[mask]))
    end
    Dict{String,Any}("groups"=>groups,"point_types_sha256"=>T.digest(bits),"grid"=>T.gridinfo(p.grid),"native_sources"=>T.sources(p),
        "window_mm"=>Dict{String,Any}("r"=>[11.65,12.65],"z"=>[3.7,5.7]),"unit"=>"q/epsilon_0 = V*m",
        "definition"=>"Real-node grid bookkeeping; q_eff already includes native dual volume. No second volume factor or geometric volume integral. Contact union: geometric members or inactive_contact_bit; overlaps fixed. Fixed means no update bit.")
end
function profile!(sim,item,stage,io)
    ef=SSD.interpolated_vectorfield(sim.electric_field); vf=SSD.interpolated_scalarfield(sim.electric_potential)
    ds=collect(0:2000).*0.0005; vectors=Vector{Float64}[]; es=Float64[]; local_sources=Float64[]
    for d in ds
        pos=SSD.CartesianPoint{Float64}((12.65-d)/1000,0,0.0047)
        e=SSD.get_velocity_vector(ef,SSD.CylindricalPoint(pos)); v=SSD.get_interpolation(vf,pos,SSD.Cylindrical)
        ev=Float64[e.x,e.y,e.z]./100; idx=SSD.find_closest_gridpoint(pos,sim.point_types.grid)
        a=sim.imp_scale.data[idx...]; bits=Int(sim.point_types.data[idx...]); net=SSD.get_impurity_density(sim.detector.semiconductor.impurity_density_model,pos)/1e6
        require(all(isfinite,vcat(ev,[v,a,net])),"Nonfinite E-only profile")
        push!(vectors,ev); push!(es,norm(ev)); push!(local_sources,a*net)
        println(io,join([item["case"],stage,d,ev...,es[end],v,a,bits,net],','))
    end
    onsets=Any[T.bracket(ds,es,t) for t in (0.,1.)]
    spacing=map((1,3),(0.01215,0.0047)) do axis,x
        a=sim.electric_potential.grid.axes[axis]; i=clamp(searchsortedlast(a,x),1,length(a)-1); (a[i+1]-a[i])*1e6
    end
    summary=Dict{String,Any}("coordinate"=>"r=(12.65-depth) mm; phi=0; z=4.7 mm; depth=0:0.0005:1 mm",
        "onsets_0_1_V_cm"=>onsets,"target_spacings_um"=>spacing,"E0.5_V_cm"=>es[1001],"samples"=>length(ds),"csv_stage"=>stage)
    item[stage*"_profile"]=summary; item["profile"]=summary; flush(io)
    Dict{String,Any}("depth_mm"=>ds,"vectors"=>vectors,"E"=>es,"onsets"=>onsets,"local_source_cm3"=>local_sources)
end
function compare(a,b;reference=b)
    require(a["depth_mm"]==b["depth_mm"] && length(a["vectors"])==length(b["vectors"])==length(a["depth_mm"]),"Profile support mismatch")
    require(reference["depth_mm"]==a["depth_mm"] && length(reference["vectors"])==length(a["depth_mm"]),"Normalization support mismatch")
    e=maximum(norm(y.-x)/max(1.,norm(r)) for (x,y,r) in zip(a["vectors"],b["vectors"],reference["vectors"]))
    valid=x->x!==nothing && !any(isnothing,x)
    shifts=Any[valid(x)&&valid(y) ? y.-x : nothing for (x,y) in zip(a["onsets"],b["onsets"])]
    x,y=a["onsets"][2],b["onsets"][2]; upper=valid(x)&&valid(y) ? max(abs(x[1]-y[2]),abs(x[2]-y[1])) : nothing
    Dict{String,Any}("normalized_E"=>e,"onset_bracket_shifts_mm"=>shifts,"onset1_separation_upper_mm"=>upper,
        "max_local_source_difference_cm3"=>maximum(abs,b["local_source_cm3"].-a["local_source_cm3"]),
        "source_definition"=>"Nearest alpha times point impurity density, not integrated charge or W",
        "passed"=>isfinite(e)&&e<=.01 && upper!==nothing && upper<=.002+1e-14)
end
function difference_location(a,b)
    grid=a.electric_potential.grid; dv=abs.(a.electric_potential.data.-b.electric_potential.data)
    sem=[SSD.getpoint(grid,Tuple(i)) in a.detector.semiconductor for i in CartesianIndices(dv)]
    require(any(sem),"No semiconductor-member nodes")
    idx=argmax(dv); point=SSD.CartesianPoint(SSD.getpoint(grid,Tuple(idx)))
    ca=T.classification.(a.imp_scale.data); cb=T.classification.(b.imp_scale.data)
    transitions=[Dict("from"=>x,"to"=>y,"nodes"=>count((ca.==x).&(cb.==y))) for x in 0:2 for y in 0:2 if x!=y]
    for dimension in (1,3)
        require(collect(a.electric_field.grid.axes[dimension])==collect(grid.axes[dimension]),"Field/potential coordinates differ")
    end
    phi=findfirst(iszero,collect(a.electric_field.grid.axes[2])); require(phi!==nothing,"No phi=0 field slice")
    fielddiff=[norm(a.electric_field.data[i[1],phi,i[3]].-b.electric_field.data[i[1],phi,i[3]])/100 for i in CartesianIndices(dv)]
    Dict{String,Any}("max_V_position_mm"=>Float64[point.x,point.y,point.z].*1000,
        "max_V_inside_semiconductor"=>sem[idx],"semiconductor_member_max_V"=>maximum(dv[sem]),
        "semiconductor_phi0_max_vector_difference_V_cm"=>maximum(fielddiff[sem]),
        "alpha_class_transitions"=>transitions,"definition"=>"Supplementary geometric-member and phi=0 localization; original whole-domain agreement gates unchanged")
end
function same_grid(a,b,pa,pb,ia,ib,coefficients_identical)
    require(T.gridinfo(a.electric_potential.grid)==T.gridinfo(b.electric_potential.grid),"Same-grid comparison grids differ")
    p,_=T.setup(a); mask=update_mask(p); require(any(mask),"Empty real update mask")
    maxv=maximum(abs,a.electric_potential.data.-b.electric_potential.data)
    av_array=abs.((a.imp_scale.data.-b.imp_scale.data).*T.realarray(p,p.q_eff_imp.*p.volume_weights))
    av=maximum(av_array); av_update=maximum(av_array[mask])
    require(T.gridinfo(a.electric_field.grid)==T.gridinfo(b.electric_field.grid),"Vector-field grids differ")
    full_field=maximum(norm.(a.electric_field.data.-b.electric_field.data))/100
    pc=compare(pa,pb); inputs=accepted(ia)&&accepted(ib)
    Dict{String,Any}("accepted_inputs"=>inputs,"coefficients_identical"=>coefficients_identical,"maxV"=>maxv,"alphavoltage"=>av,"alphavoltage_update_only"=>av_update,
        "whole_grid_vector_difference_V_cm"=>full_field,
        "classification_changes"=>count(T.classification.(a.imp_scale.data).!=T.classification.(b.imp_scale.data)),
        "difference_location"=>difference_location(a,b),"profilecomparison"=>pc,"inconclusive"=>!inputs,
        "passed"=>inputs&&coefficients_identical&&maxv<=T.LIMITS.V&&av<=T.LIMITS.V&&pc["passed"],
        "interpretation"=>"Disagreement despite native passes means native update tolerance is not a global solution error bound; no independent multiple-basin claim.")
end
function contrast_available(profiles,a,b)
    all(haskey(profiles,n) for n in (a,b,"g22_from50"))
end
function contrast_acceptance(items,a,b)
    Dict{String,Any}("accepted_endpoints"=>accepted(items[a])&&accepted(items[b]),
        "accepted_reference"=>accepted(items["g22_from50"]),
        "accepted_inputs"=>all(accepted(items[n]) for n in (a,b,"g22_from50")))
end
function factorial(profiles)
    p=[profiles[n] for n in ("g11","g12","g21","g22_from50")]
    require(all(x["depth_mm"]==p[1]["depth_mm"] for x in p),"Factorial supports differ")
    v=[p[4]["vectors"][k].-p[3]["vectors"][k].-p[2]["vectors"][k].+p[1]["vectors"][k] for k in eachindex(p[1]["depth_mm"])]
    s=p[4]["local_source_cm3"].-p[3]["local_source_cm3"].-p[2]["local_source_cm3"].+p[1]["local_source_cm3"]
    Dict{String,Any}("definition"=>"E22-E21-E12+E11 at common points; phi=0 radial component is Ex",
        "maxnorm_V_cm"=>maximum(norm,v),
        "normalized_interaction"=>maximum(norm(x)/max(1.0,norm(r)) for (x,r) in zip(v,p[4]["vectors"])),
        "normalization_reference"=>"g22_from50: pointwise max(1 V/cm, norm(E22))","signed_radial_profile_V_cm"=>first.(v),"depth_mm"=>p[1]["depth_mm"],
        "max_local_source_interaction_cm3"=>maximum(abs,s),"signed_local_source_interaction_cm3"=>s)
end
function main(args=ARGS)
    output=options(args); require(Threads.nthreads()==2,"Launch with --threads=2"); pins=provenance(); Q.reserve_output(output)
    started=time(); sims=Dict{String,Any}(); items=Dict{String,Any}(); profiles=Dict{String,Any}()
    report=Dict{String,Any}("schema_version"=>1,"kind"=>"AK02_transition_axes","status"=>"running","provenance"=>pins,
        "expected_case_count"=>7,"cases"=>Any[],"comparisons"=>Any[],"unavailable_comparisons"=>Any[],"same_grid"=>Dict{String,Any}("accepted_inputs"=>false,"coefficients_identical"=>false,"maxV"=>nothing,"alphavoltage"=>nothing,"profilecomparison"=>nothing,"passed"=>false,"inconclusive"=>true),"factorialsummary"=>nothing,
        "held_settings"=>Dict{String,Any}("temperature_K"=>77,"bias_V"=>500,"threads"=>2,"precision"=>"Float64","sor"=>1.,"fresh_sweeps"=>40000,"continuation_sweeps"=>20000,"case_seconds"=>900.,"node_cap"=>250000,"seed"=>"none: deterministic"),
        "limitations"=>["E only after baseline E/V/W hash parity; stale W never used.","Native fixed-point pass is not PDE/grid/CCE convergence. No spatial full convergence or multiple-basin claim.","Contact gates test member nodes, not between-node boundaries.","All crossed starts use accepted min50 V with fresh alpha; attribution exploratory if initialization agreement fails.","Adaptive baseline calls are not interruptible; budgets checked at call boundaries and after postprocessing, not a hard wall-time guarantee. Timings include compilation/diagnostics.","Rebuild guard checks identical independent native probes; use of the same solver setup relies on the pinned deterministic constructor."])
    checkpoint=()->Q.save_json(joinpath(output,"report.json"),report)
    io=open(joinpath(output,"profiles.csv"),"w"); co=open(joinpath(output,"comparisons.csv"),"w")
    println(io,"case,stage,depth_mm,Ex_V_cm,Ey_V_cm,Ez_V_cm,magnitude_V_cm,V,alpha,pointbits,netdensity_cm3")
    println(co,"reference,candidate,normalized_E,onset1_separation_upper_mm,max_local_source_difference_cm3,accepted_inputs,passed")
    function run_case(name,action)
        start=time(); sim,_=R.setup_simulation("AK02";temperature=77.); native=Dict{String,Any}("case"=>name)
        item=Dict{String,Any}("case"=>name,"nativeitem"=>native,"status"=>"running","checkpoints"=>Any[],"profile"=>nothing)
        push!(report["cases"],item); items[name]=item; sims[name]=sim
        cp=stage->begin
            push!(item["checkpoints"],Dict{String,Any}("stage"=>stage,"elapsed_seconds"=>time()-start,"source_ref"=>"provenance.sources"))
            println(name," ",stage); flush(stdout); checkpoint()
        end
        require([c.potential for c in sim.detector.contacts]==[0,500],"Bias changed")
        try
            action(sim,item,native,cp,start+T.LIMITS.seconds)
        catch err
            if budget_failure(err)
                item["status"]="budget_failed"; item["failure"]=sprint(showerror,err)
            else
                item["status"]="invalid_source_or_runtime"; rethrow()
            end
        finally
            finish_budget!(item,time()-start); checkpoint()
        end
    end
    function addcompare(a,b)
        d=compare(profiles[a],profiles[b];reference=profiles["g22_from50"]);
        d["normalization_reference"]="g22_from50: pointwise max(1 V/cm, norm(E22))"
        d["signed_radial_difference_V_cm"]=[y[1]-x[1] for (x,y) in zip(profiles[a]["vectors"],profiles[b]["vectors"])]; merge!(d,contrast_acceptance(items,a,b)); d["passed"] &= d["accepted_inputs"]
        merge!(d,Dict{String,Any}("reference"=>a,"candidate"=>b,"attribution"=>"exploratory_conditioned_on_initialization_test"))
        push!(report["comparisons"],d); println(co,join([a,b,d["normalized_E"],d["onset1_separation_upper_mm"],d["max_local_source_difference_cm3"],d["accepted_inputs"],d["passed"]],',')); flush(co)
    end
    function finish(sim,item,native)
        p,_=T.setup(sim); item["source_accounting"]=accounting(sim,p)
        item["status"]=contacts_ok(native) ? "accepted_fixed_grid" : "budget_failed"
        profiles[item["case"]]=profile!(sim,item,"final",io)
        sims[item["case"]]=deepcopy(sim)
        independent_storage(sim,sims[item["case"]])
    end
    try
        for (name,spacing,rechecks) in (("min50",.05,4),("min25",.025,8))
            run_case(name,(sim,item,native,cp,deadline)->begin
                item["min_grid_mm"]=spacing; item["rechecks"]=rechecks
                T.baseline!(sim,spacing,rechecks,native,cp,deadline); profile!(sim,item,"initial",io)
                T.relax!(sim,native,cp,deadline); finish(sim,item,native)
            end)
        end
        report["baseline_accepted"]=all(accepted(items[n]) for n in ("min50","min25"))
        if report["baseline_accepted"]
            g0=sims["min50"].electric_potential.grid; g1,c1=T.nested_grid(g0); g2,c2=T.nested_grid(g1)
            report["even_z_added_m"]=Any[c1,c2]
            grids=Dict{String,Any}("g11"=>g1,"g12"=>crossed_grid(g1,g2),"g21"=>crossed_grid(g2,g1),"g22_from50"=>g2,"g22_from25"=>g2)
            for name in ("g22_from50","g22_from25","g11","g12","g21")
                run_case(name,(sim,item,native,cp,deadline)->begin
                    parent=name=="g22_from25" ? "min25" : "min50"; item["initial_potential_source"]=parent
                    item["attribution"]="exploratory_conditioned_on_initialization_test"
                    item["parent_before"]=state_identity(sims[parent])
                    T.candidate!(sim,deepcopy(grids[name]),sims[parent]); independent_storage(sim,sims[parent]); require(all(==(1.),sim.imp_scale.data),"Fresh alpha not unity")
                    item["inputVhash"]=T.digest(sim.electric_potential.data)
                    p,paint=T.setup(sim;restore=false); require(!Base.mightalias(p.potential,sim.electric_potential.data),"Native setup aliases candidate")
                    item["initial_identity"]=identity(p); item["initial_repaint"]=paint
                    item["initial_source_accounting"]=accounting(sim,p)
                    if name=="g22_from25"
                        identity_guard(items["g22_from50"]["initial_identity"],item["initial_identity"])
                        v50=sims["min50"].electric_potential[grids[name]].data
                        report["same_grid"]["maxinitVdifference"]=maximum(abs,v50.-sim.electric_potential.data)
                    end
                    # T.relax! reconstructs this same setup; verify again at its first checkpoint, before any native update.
                    checked=Ref(false)
                    guarded=stage->begin
                        if !checked[]
                            rebuilt,_=T.setup(sim;restore=false); identity_guard(item["initial_identity"],identity(rebuilt))
                            require(native["E_grid"]==T.gridinfo(rebuilt.grid) && native["E_sources_initial"]==T.sources(rebuilt),"Helper reconstruction changed")
                            item["rebuild_identity_verified"]=true; checked[]=true
                        end
                        cp(stage)
                    end
                    cp("fresh/E"); T.relax!(sim,native,guarded,deadline;fresh=true); finish(sim,item,native)
                    item["parent_after"]=state_identity(sims[parent])
                    require(item["parent_before"]==item["parent_after"],"Candidate mutated parent state")
                    item["independent_parent_storage_verified"]=true
                end)
                if name=="g22_from25" && all(haskey(profiles,n) for n in ("g22_from50","g22_from25"))
                    initialdiff=report["same_grid"]["maxinitVdifference"]
                    report["same_grid"]=same_grid(sims["g22_from50"],sims[name],profiles["g22_from50"],profiles[name],items["g22_from50"],items[name],true)
                    report["same_grid"]["maxinitVdifference"]=initialdiff
                end
            end
            for (a,b) in (("g11","g21"),("g12","g22_from50"),("g11","g12"),("g21","g22_from50"))
                if contrast_available(profiles,a,b)
                    addcompare(a,b)
                else
                    push!(report["unavailable_comparisons"],Dict("reference"=>a,"candidate"=>b,"reason"=>"Missing endpoint or E22 normalization profile"))
                end
            end
            if all(haskey(profiles,n) for n in ("g11","g12","g21","g22_from50"))
                report["factorialsummary"]=factorial(profiles)
                report["factorialsummary"]["attribution"]="exploratory_conditioned_on_initialization_test"
                report["factorialsummary"]["initialization_test_passed"]=report["same_grid"]["passed"]
                report["factorialsummary"]["accepted_inputs"]=all(accepted(items[n]) for n in ("g11","g12","g21","g22_from50"))
            end
        else
            report["crosses_blocked_reason"]="Baseline native/contact gate failed; no accepted inputs for crossed grids"
        end
        report["status"]=length(items)==7 && all(accepted,values(items)) ? "completed_attribution_diagnostics" : "partial_cases"
    catch err
        report["status"]=budget_failure(err) ? "partial_cases" : "invalid_source_or_runtime"; report["failure"]=sprint(showerror,err)
    finally
        close(io); close(co)
        try
            require(provenance()==pins,"Sources changed during diagnostic"); report["final_sources_unchanged"]=true
        catch err
            report["status"]="invalid_source_or_runtime"; report["failure"]=sprint(showerror,err); report["final_sources_unchanged"]=false
        end
        report["artifacts"]=Dict{String,Any}(n=>Q.sha256file(joinpath(output,n)) for n in ("profiles.csv","comparisons.csv"))
        report["runtime_seconds"]=time()-started; checkpoint()
    end
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    try
        result=TransitionAxesDiagnostics.main(); println("Diagnostic status: ",result["status"]); exit(TransitionAxesDiagnostics.exitcode(result))
    catch err
        showerror(stderr,err); println(stderr); exit(1)
    end
end
