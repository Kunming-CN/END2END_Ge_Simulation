# AK02 native fixed-point audit and explicit nested-grid candidate. No transport/CCE claim.
isdefined(@__MODULE__, :LithiumDiagnostics) || include("diagnose_lithium.jl")
module TransitionGridDiagnostics
using ..LithiumDiagnostics, SolidStateDetectors, Unitful, SHA, JSON, LinearAlgebra
const L=LithiumDiagnostics; const Q=L.Q; const R=L.R; const SSD=L.SSD
const require=L.require
const LIMITS=(V=5e-6,W=1e-8,points=250000,extra=20000,initial=20000,seconds=900.0)
const STATE=(:electric_potential,:electric_field,:imp_scale,:point_types,:q_eff_imp,:q_eff_fix,:ϵ_r)
const SOURCE_PINS=Dict("run.jl"=>"c39a82f35d3772b2c700682d4fae7c06caba13703d45738fa612610646cde1e5",
    "replay.jl"=>"7ed14d7e0c1f8df9862c6c08e64f844388b57c900cf436d982a55eca15f92816",
    "diagnose_lithium.jl"=>"fc2c921a61ee208711d5ff795612ffbcd5f6a0c7719038cfc37d34fe980759b9",
    "diagnose_collection.jl"=>"8deb386f44e76571707cd8ec64ce71378f37eb3ef2ac440bc6ece22fc3243d4b")
const NATIVE_PINS=merge(L.SDK_PINS,Dict(
    "PotentialCalculation/PotentialCalculationSetup/PotentialCalculationSetupCylindrical.jl"=>"67709042b7a332a0d366236a35aaf57558983a88ee6a2cc0ee1dd2913fd5b873",
    "PotentialCalculation/SuccessiveOverRelaxation/CPU_innerloop.jl"=>"1a97b89063362dcd0ad6f73443fc8aac18dedbdea3a908a782b7ce89375b41aa",
    "PotentialCalculation/SuccessiveOverRelaxation/CPU_outerloop.jl"=>"f6e5c05b4f97918bee27aabecc156cc69a8bb803261603e953c62c3eb8ce13c9",
    "PotentialCalculation/SuccessiveOverRelaxation/CPU_update.jl"=>"e338db8125ae7d22238eac38c27965270493deb070db951a7786586bea75a0f0"))
# Extracted once from .local/m2c/results/report.json; no 38 MB report needed at runtime.
const HISTORICAL_REPORT_SHA="42b164eee8d4565e1161bf65c50756ef290ca201dbc45f949059649209d8eab0"
const NATIVE_TREE_SHA="aa89b7a86f26f244f3664394a6615c1b61d1ee20a34936cdd1ffd8c70da274d6"
const HISTORICAL=Dict("min50"=>("ba2e832ef4b1eabdbb6f93ae04581677d77075c9248c045c08e639311a9623d9","03f7c581c54233dc3e3ca13ab2b3a7b1163ec4998222e4d3be4c1613b033b4ed","ff059fab8e5c5c34bcc88de5a3ec208c3475fe60e550f91a2ca4c8a3df320e61"),
    "min25"=>("85919bc51fe7a22b9f416b503e652532b0e37aa687aa65c064a59feaf5de0eb7","7652291433e289bbfadb3b10a7ad24f02f2939bfb449a6c0c6532bc5442deba6","5829e9cae5aac4d9f305c5bb9d00c41bf9c7038118dd20a84f898750bb867ded"))
digest(a)=bytes2hex(sha256(reinterpret(UInt8,vec(a))))
axesof(g)=[collect(a) for a in g.axes]
gridinfo(g)=Dict("ticks_m_rad_m"=>axesof(g),"boundaries"=>[string.(SSD.get_boundary_types(a)) for a in g.axes],"shape"=>collect(size(g)))
function snapshot(sim)
    Dict(string(k)=>ismissing(getproperty(sim,k)) ? nothing : merge(L.grid_snapshot(getproperty(sim,k)),
        Dict("grid"=>gridinfo(getproperty(sim,k).grid))) for k in STATE)
end
function provenance()
    L.check_hashes(@__DIR__,merge(L.PINNED,SOURCE_PINS)); L.check_hashes(dirname(pathof(SSD)),NATIVE_PINS)
    root=dirname(pathof(SSD)); inventory=Dict{String,String}()
    for sub in ("PotentialCalculation","Grids","Axes","ScalarPotentials","ElectricField"), (dir,_,files) in walkdir(joinpath(root,sub)), file in files
        path=joinpath(dir,file); inventory[replace(relpath(path,root),'\\'=>'/')]=Q.sha256file(path)
    end
    tree=bytes2hex(sha256(join(sort!([n*" "*h for (n,h) in inventory]),'\n')))
    require(tree==NATIVE_TREE_SHA,"Native operator/grid inventory changed")
    Q.verify_model_files(); L.check_hashes(Q.MODEL_DIR,Dict("AK02.yaml"=>L.MODEL_PINS["AK02"]))
    env=Q.environment("cpu"); require(env["environment_manifest_sha256"]==L.PINNED["Manifest.toml"],"Wrong active environment")
    Dict("environment"=>env,"sources"=>merge(SOURCE_PINS,Dict(n=>Q.sha256file(joinpath(@__DIR__,n)) for n in ("diagnose_transition_grid.jl","test_transition_grid.jl"))),
        "native_sources"=>merge(NATIVE_PINS,inventory),"native_tree_sha256"=>tree,"model_sha256"=>L.MODEL_PINS["AK02"],"historical_report_sha256"=>HISTORICAL_REPORT_SHA,
        "historical_E_V_W_sha256"=>HISTORICAL)
end
function options(args)
    require(iseven(length(args)),"Use --output .local/NEW [--phase baseline|nested|all]")
    d=Dict{String,String}()
    for i in 1:2:length(args)
        require(args[i] in ("--output","--phase")&&!haskey(d,args[i]),"Unknown/duplicate option"); d[args[i]]=args[i+1]
    end
    require(haskey(d,"--output"),"Output required"); phase=get(d,"--phase","all")
    require(phase in ("baseline","nested","all"),"Invalid phase"); Q.validate_output(d["--output"]),phase
end
function aligned(sim)
    g=gridinfo(sim.electric_potential.grid)
    require(g==gridinfo(sim.imp_scale.grid)==gridinfo(sim.point_types.grid),"E/alpha/point-type grids misaligned")
end
function setup(sim; weighting=false,restore=true)
    aligned(sim); f=weighting ? sim.weighting_potentials[1] : sim.electric_potential
    v=copy(f.data); before=copy(v)
    p=SSD.PotentialCalculationSetup(sim.detector,f.grid,sim.medium,v,copy(sim.imp_scale.data);
        weighting_potential_contact_id=weighting ? 1 : missing, point_types=weighting ? deepcopy(sim.point_types) : missing,
        sor_consts=(1.0,1.0),use_nthreads=2)
    repaint=Dict{String,Any}("changed_nodes"=>count(before.!=v),"max_change"=>maximum(abs,before.-v),
        "point_type_changes"=>weighting ? nothing : count(SSD.PointTypeArray(p).!=sim.point_types.data))
    if !weighting
        repaint["source_arrays_equal"]=SSD.EffectiveChargeDensityArray(p)==sim.q_eff_imp.data && SSD.FixedEffectiveChargeDensityArray(p)==sim.q_eff_fix.data
        repaint["permittivity_equal"]=SSD.DielectricDistributionArray(p)==sim.ϵ_r.data
        require(repaint["source_arrays_equal"]&&repaint["permittivity_equal"],"Reconstructed electric coefficients differ from saved state")
    end
    if restore # Constructor contact painting is evidence, not permission to change the audited state.
        p.potential .= SSD.RBExtBy2Array(before,f.grid)
        for color in (true,false); SSD.apply_boundary_conditions!(p,Val(color),Val(true)); end
        if !weighting
            p.imp_scale .= SSD.RBExtBy2Array(sim.imp_scale.data,f.grid)
            p.point_types .= SSD.RBExtBy2Array(sim.point_types.data,f.grid)
            require(SSD.ImpurityScaleArray(p)==sim.imp_scale.data,"Saved alpha restoration failed")
        end
    end
    p,repaint
end
native_step!(p,w=false)=SSD.update!(p,nothing,nothing;use_nthreads=2,depletion_handling=Val(!w),is_weighting_potential=Val(w),only2d=Val(true))
classification(a)=a==0 ? 0 : a<1 ? 1 : 2
function change(p,before,alpha,mask)
    v=SSD.ElectricPotentialArray(p); a=SSD.ImpurityScaleArray(p)
    require(all(isfinite,v)&&all(isfinite,a),"Nonfinite native state")
    Dict{String,Any}("potential"=>maximum(abs.(v.-before)[mask];init=0.0),"alpha"=>maximum(abs.(a.-alpha)[mask];init=0.0),
        "alpha_class_changes"=>count((classification.(a).!=classification.(alpha)).&mask),
        "alpha_voltage"=>maximum(abs.((a.-alpha).*realarray(p,p.q_eff_imp.*p.volume_weights))[mask];init=0.0))
end
function frozen(p,mode)
    require(mode in (:clamp,:poisson,:weighting,:fullsource),"Invalid residual mode")
    v=SSD.ElectricPotentialArray(p); a=SSD.ImpurityScaleArray(p); mask=(SSD.PointTypeArray(p).&SSD.update_bit).!=0
    rows=map((true,false)) do color
        c=deepcopy(p) # Both colors see exactly the SAME frozen neighbors, never each other.
        mode==:poisson && (c.q_eff_imp .*= c.imp_scale)
        SSD.outerloop!(c,2,Val(color),Val(mode==:clamp),Val(mode==:weighting),Val(true))
        merge(change(c,v,a,mask),Dict("color_even"=>color))
    end
    Dict("max"=>maximum(r["potential"] for r in rows),"max_alpha"=>maximum(r["alpha"] for r in rows),
        "alpha_class_changes"=>sum(r["alpha_class_changes"] for r in rows),
        "max_alpha_voltage"=>maximum(r["alpha_voltage"] for r in rows),"colors"=>collect(rows))
end
function defects(p; weighting=false)
    v=SSD.ElectricPotentialArray(p); a=SSD.ImpurityScaleArray(p); mask=(SSD.PointTypeArray(p).&SSD.update_bit).!=0
    c=deepcopy(p); native_step!(c,weighting)
    full=change(c,v,a,mask)
    full["colors"]=[change(c,v,a,mask.&[iseven(sum(Tuple(i)))==color for i in CartesianIndices(mask)]) for color in (true,false)]
    Dict{String,Any}("frozen"=>frozen(p,weighting ? :weighting : :clamp),"poisson"=>weighting ? nothing : frozen(p,:poisson),"full_sweep"=>full)
end
function acceptable(d,w)
    tol=w ? LIMITS.W : LIMITS.V
    d["frozen"]["max"]<=tol && d["full_sweep"]["potential"]<=tol &&
        (w || (d["poisson"]["max"]<=tol && d["frozen"]["max_alpha_voltage"]<=tol && d["full_sweep"]["alpha_voltage"]<=tol))
end
next_streak(streak,good,within_budget)=good && within_budget ? streak+1 : 0
nested_gate(passes,coldmatch)=length(passes)==2 && all(passes) && coldmatch
# Select only real nodes: q_eff in PCS already includes dual volume / epsilon_0.
function realarray(p,a)
    [a[SSD.rbidx(z),f+1,r+1,iseven(r+f+z) ? SSD.rb_even : SSD.rb_odd] for r in 1:size(p.grid,1),f in 1:size(p.grid,2),z in 1:size(p.grid,3)]
end
signedsum(a)=Dict("positive"=>sum(x->max(x,0),a),"negative"=>sum(x->min(x,0),a))
function sources(p)
    q=realarray(p,p.q_eff_imp); a=SSD.ImpurityScaleArray(p)
    Dict("q_imp"=>signedsum(q),"alpha_q_imp"=>signedsum(a.*q),"q_fix"=>signedsum(realarray(p,p.q_eff_fix)),
        "unit"=>"C/epsilon_0 = V*m; native full-ring dual cells, no extra volume weighting",
        "alpha_classes"=>[count(==(k),classification.(a)) for k in 0:2],"permittivity_range"=>collect(extrema(p.ϵ_r)))
end
function copyback!(sim,p,w)
    g=p.grid
    if w; sim.weighting_potentials[1]=SSD.WeightingPotential(SSD.ElectricPotentialArray(p),g); return; end
    sim.electric_potential=SSD.ElectricPotential(SSD.ElectricPotentialArray(p),g)
    sim.imp_scale=SSD.ImpurityScale(SSD.ImpurityScaleArray(p),g)
    bits=SSD.PointTypeArray(p)
    bits .&= ~(SSD.bulk_bit | SSD.undepleted_bit | SSD.inactive_layer_bit)
    sim.point_types=SSD.PointTypes(bits,g,true)
    sim.q_eff_imp=SSD.EffectiveChargeDensity(SSD.EffectiveChargeDensityArray(p),g)
    sim.q_eff_fix=SSD.EffectiveChargeDensity(SSD.FixedEffectiveChargeDensityArray(p),g)
    sim.ϵ_r=SSD.DielectricDistribution(SSD.DielectricDistributionArray(p),SSD.get_extended_midpoints_grid(g))
    SSD.mark_bits!(sim); calculate_electric_field!(sim;n_points_in_φ=36,use_nthreads=2)
end
function relax!(sim,item,checkpoint,deadline; weighting=false,fresh=false)
    p,paint=setup(sim;weighting,restore=!fresh); key=weighting ? "W" : "E"
    item[key*"_grid"]=gridinfo(p.grid); item[key*"_repaint"]=paint
    require(prod(size(p.grid))<=LIMITS.points,"Point budget exceeded")
    item[key*"_sources_initial"]=sources(p)
    history=Any[]; item[key*"_checks"]=history; consecutive=0; passed=false; actual=0; started=time()
    for target in 0:500:(fresh ? LIMITS.initial+LIMITS.extra : LIMITS.extra)
        if target>0
            for n in 1:500
                time()<deadline || break
                native_step!(p,weighting); actual+=1
            end
        end
        d=defects(p;weighting); d["sweeps"]=actual; d["elapsed_seconds"]=time()-started
        consecutive=next_streak(consecutive,acceptable(d,weighting),time()<deadline)
        d["consecutive_passes"]=consecutive; push!(history,d); checkpoint(key*"/residual")
        if consecutive>=2; passed=true; break; end
        time()<deadline || break
    end
    item[key*"_sources_final"]=sources(p); copyback!(sim,p,weighting)
    require(gridinfo(p.grid)==item[key*"_grid"],"Continuation changed the fixed grid")
    item[key*"_final_native_hashes"]=Dict(string(k)=>digest(getproperty(p,k)) for k in (:potential,:imp_scale,:point_types,:q_eff_imp,:q_eff_fix,:ϵ_r))
    _,finalpaint=setup(sim;weighting); item[key*"_final_repaint"]=finalpaint
    contacts=contact_errors(sim,weighting); item[key*"_geometric_contacts"]=contacts
    tol=weighting ? LIMITS.W : LIMITS.V
    item[key*"_seconds"]=time()-started
    item[key*"_accepted"]=passed && (fresh || paint["max_change"]<=tol) && finalpaint["max_change"]<=tol && all(c["max_error"]<=tol for c in contacts)
    item[key*"_accepted"]
end
function contact_errors(sim,w)
    f=w ? sim.weighting_potentials[1] : sim.electric_potential
    [begin
        errors=[abs(f.data[i]-(w ? Float64(c.id==1) : c.potential)) for i in CartesianIndices(f.data) if SSD.getpoint(f.grid,Tuple(i)) in c.geometry]
        Dict("contact"=>c.id,"nodes"=>length(errors),"max_error"=>maximum(errors;init=0.0))
    end for c in sim.detector.contacts]
end
function bracket(depths,e,threshold)
    require(length(depths)==length(e)&&!isempty(e)&&all(isfinite,e)&&all(diff(depths).>0),"Invalid profile")
    k=findfirst(>(threshold),e); isnothing(k) ? nothing : [k==1 ? nothing : depths[k-1],depths[k]]
end
function profile!(sim,item,label,io)
    field=SSD.interpolated_vectorfield(sim.electric_field); wp=SSD.interpolated_scalarfield(sim.weighting_potentials[1])
    ds=collect(0:2000).*0.0005; es=Float64[]; ws=Float64[]; al=Float64[]; vectors=Vector{Float64}[]
    for d in ds
        o=L.observe(sim,CartesianPoint{Float64}((12.65-d)/1000,0,0.0047),field,wp)
        push!(es,o["field_magnitude_V_per_cm"]); push!(ws,o["weighting_potential"]); push!(al,o["nearest_grid_impurity_scale"]); push!(vectors,Float64.(o["field_V_per_cm"]))
        println(io,join([item["case"],label,d,es[end],ws[end],al[end],o["nearest_grid_bits"],o["net_impurity_cm3"]],','))
    end
    p=Dict("depth_mm"=>ds,"E"=>es,"vectors"=>vectors,"W"=>ws,"onsets"=>[bracket(ds,es,t) for t in (0.0,1.0)])
    item[label]=Dict{String,Any}("onsets_0_1_V_cm"=>p["onsets"],"samples"=>[Dict("depth_mm"=>ds[k],"E_V_cm"=>es[k],"W"=>ws[k]) for k in (1001,1101,1201)],
        "alpha_class_boundary_brackets_mm"=>[[ds[k-1],ds[k]] for k in 2:length(ds) if classification(al[k])!=classification(al[k-1])])
    item[label]["target_spacings_um"]=map((1,3),(0.01215,0.0047)) do axis,x
        a=sim.electric_potential.grid.axes[axis]; i=clamp(searchsortedlast(a,x),1,length(a)-1); (a[i+1]-a[i])*1e6
    end
    flush(io); p
end
function compare(a,b)
    require(a["depth_mm"]==b["depth_mm"],"Profile supports differ")
    require(length(a["vectors"])==length(b["vectors"])==length(a["E"]),"Missing field vectors")
    e=maximum(norm(y.-x)/max(1.0,norm(y)) for (x,y) in zip(a["vectors"],b["vectors"]))
    shifts=[isnothing(x)||isnothing(y)||any(isnothing,x)||any(isnothing,y) ? nothing : maximum(abs.(x.-y)) for (x,y) in zip(a["onsets"],b["onsets"])]
    x,y=a["onsets"][2],b["onsets"][2]
    conservative=isnothing(x)||isnothing(y)||any(isnothing,x)||any(isnothing,y) ? nothing : max(abs(x[1]-y[2]),abs(x[2]-y[1]))
    Dict("normalized_E"=>e,"onset_shifts_mm"=>shifts,"onset1_separation_upper_mm"=>conservative,
        "max_W"=>maximum(abs.(a["W"].-b["W"])),
        "comparison_definition"=>"Vector difference / max(1 V/cm, finer-field norm); only 1 V/cm onset is gated, including bracket uncertainty",
        "passed"=>e<=0.01 && conservative!==nothing && conservative<=0.002+1e-14)
end
function coldwarm(a,b,pa,pb)
    require(gridinfo(a.electric_potential.grid)==gridinfo(b.electric_potential.grid)&&gridinfo(a.weighting_potentials[1].grid)==gridinfo(b.weighting_potentials[1].grid),"Cold/warm grids differ")
    d=compare(pa,pb); d["max_V"]=maximum(abs,a.electric_potential.data.-b.electric_potential.data)
    d["max_W_grid"]=maximum(abs,a.weighting_potentials[1].data.-b.weighting_potentials[1].data)
    d["max_alpha"]=maximum(abs,a.imp_scale.data.-b.imp_scale.data)
    p,_=setup(a)
    d["alpha_voltage_difference"]=maximum(abs.((a.imp_scale.data.-b.imp_scale.data).*realarray(p,p.q_eff_imp.*p.volume_weights)))
    d["passed"] &= d["max_V"]<=LIMITS.V && d["max_W_grid"]<=LIMITS.W && d["alpha_voltage_difference"]<=LIMITS.V; d
end
function nested_ticks(t,bands; even=false)
    require(length(t)>=2&&all(isfinite,t)&&all(diff(t).>0),"Invalid ticks")
    require(all(b->length(b)==2&&first(t)<=b[1]<b[2]<=last(t),bands),"Invalid refinement bounds")
    v=sort!(unique(vcat(t,[(t[i]+t[i+1])/2 for i in 1:length(t)-1 if any(b->t[i]<=b[2]&&t[i+1]>=b[1],bands)])))
    correction=nothing
    if even && isodd(length(v))
        i=findfirst(i->all(b->v[i+1]<b[1]||v[i]>b[2],bands),1:length(v)-1)
        require(!isnothing(i),"No exterior interval for even-z correction")
        correction=(v[i]+v[i+1])/2; push!(v,correction); sort!(v)
    end
    require(all(in(v),t),"Lost coarse tick"); v,correction
end
function nested_grid(g; cap=LIMITS.points)
    require(axesof(g)[2]==[0.0]&&first(g.axes[1])==0&&last(g.axes[1])==0.015&&first(g.axes[3])==-0.002&&last(g.axes[3])==0.011,"Unexpected AK02 world")
    require(SSD.get_boundary_types(g.axes[1])==(:r0,:infinite,:closed,:closed)&&SSD.get_boundary_types(g.axes[2])==(:reflecting,:reflecting,:closed,:closed)&&SSD.get_boundary_types(g.axes[3])==(:infinite,:infinite,:closed,:closed),"Unexpected boundary types")
    r,_=nested_ticks(collect(g.axes[1]),[(0.01165,0.01265),(0.0073,0.0083)])
    z,c=nested_ticks(collect(g.axes[3]),[(-0.001,0.001),(0.0011,0.0031),(0.0084,0.0104)];even=true)
    require(0<cap<=LIMITS.points&&length(r)*length(z)<=cap,"Nested point budget exceeded before allocation: $(length(r)) r x $(length(z)) z = $(length(r)*length(z)); cap $cap")
    ticks=(r,collect(g.axes[2]),z); axes=ntuple(i->typeof(g.axes[i])(g.axes[i].interval,ticks[i]),3)
    next=SSD.CylindricalGrid{Float64}(axes); SSD.check_grid(next); next,c
end
function baseline!(sim,spacing,rechecks,item,checkpoint,deadline)
    common=(device_array_type=Array,use_nthreads=2,sor_consts=1.0,depletion_handling=true,n_iterations_between_checks=250,verbose=false)
    opts=(common...,convergence_limit=1e-6,refinement_limits=[0.2,0.1,0.05],min_tick_distance=spacing*u"mm",max_tick_distance=2u"mm",max_n_iterations=50000)
    checkpoint("initial/E"); stage_start=time(); calculate_electric_potential!(sim;opts...)
    item["native_initial_checks"]=Any[]
    for w in (false,true)
        if w
            stage_start=time()
            before=snapshot(sim); item["before_first_W"]=before; checkpoint("initial/W_init")
            wg=SSD.Grid(sim;for_weighting_potential=true,max_tick_distance=2u"mm",max_distance_ratio=5)
            SSD.apply_initial_state!(sim,SSD.WeightingPotential,1,wg;depletion_handling=true)
            item["after_first_W_init"]=snapshot(sim); require(before==item["after_first_W_init"],"W initialization changed E state")
            calculate_weighting_potential!(sim,1;opts...)
        end
        update=Inf
        for attempt in 1:rechecks
            time()<deadline || error("Case elapsed limit exceeded during adaptive initial solve")
            update=w ? SSD.update_till_convergence!(sim,SSD.WeightingPotential,1,1e-6;common...,max_n_iterations=3000) : SSD.update_till_convergence!(sim,SSD.ElectricPotential,1e-6;common...,max_n_iterations=3000)
            push!(item["native_initial_checks"],Dict("W"=>w,"attempt"=>attempt,"update"=>update)); checkpoint(w ? "initial/W" : "initial/E")
            isfinite(update)&&update<=(w ? 1e-6 : 500e-6) && break
        end
        require(isfinite(update)&&update<=(w ? 1e-6 : 500e-6),"Original Q iteration gate failed")
        item[w ? "initial_W_seconds" : "initial_E_potential_seconds"]=time()-stage_start
        if !w
            field_start=time(); SSD.mark_bits!(sim); calculate_electric_field!(sim;n_points_in_φ=36,use_nthreads=2)
            item["initial_field_seconds"]=time()-field_start
        else
            item["after_initial_W_solve"]=snapshot(sim); require(before==item["after_initial_W_solve"],"W solve changed E state")
        end
    end
    hashes=(digest(sim.electric_field.data),digest(sim.electric_potential.data),digest(sim.weighting_potentials[1].data))
    item["initial_E_V_W_sha256"]=hashes; require(hashes==HISTORICAL[item["case"]],"Initial fields differ from pinned M2c")
end
function candidate!(sim,g,previous)
    require(prod(size(g))<=LIMITS.points,"Candidate point budget exceeded")
    SSD.apply_initial_state!(sim,SSD.ElectricPotential,g;depletion_handling=true)
    if previous!==nothing
        sim.electric_potential.data .= previous.electric_potential[g].data
    end # alpha is freshly constructed; setup repaints warm-start contacts before updates.
end
function main(args=ARGS)
    output,phase=options(args); require(Threads.nthreads()==2,"Launch with --threads=2")
    pins=provenance(); Q.reserve_output(output); started=time()
    report=Dict{String,Any}("schema_version"=>1,"kind"=>"AK02_native_transition_grid","phase"=>phase,"status"=>"running","provenance"=>pins,
        "held_settings"=>Dict("temperature_K"=>77,"bias_V"=>500,"precision"=>"Float64","sor"=>1,"threads"=>2,"max_grid_mm"=>2,
            "limits"=>Dict(string(k)=>v for (k,v) in pairs(LIMITS)),"profile_relative_gate"=>0.01,"onset_gate_mm"=>0.002,"seed"=>"none: deterministic fields"),"cases"=>Any[],"comparisons"=>Any[],"grids"=>Dict(),
        "limitations"=>["Native fixed-point defects, not independent PDE discretization proof or physical Li CCE validation.","Nested strips refine whole tensor-product coordinate lines; geometry and SDK unchanged.","Adaptive baseline native calls are not interruptible; elapsed budget checked at call boundaries.","Phase nested still reproduces and gates both baselines; no saved field cache.","Timings include compilation, diagnostics and checkpoint IO; not production benchmarks. No drift or frozen-path cross-weighting in this entry."])
    checkpoint=()->Q.save_json(joinpath(output,"report.json"),report)
    profiles=open(joinpath(output,"profiles.csv"),"w"); comparisons=open(joinpath(output,"smallcomparisons.csv"),"w")
    println(profiles,"case,stage,depth_mm,E_V_cm,W,alpha,point_bits,net_impurity_cm3")
    println(comparisons,"reference,candidate,normalized_E,onset0_shift_mm,onset1_shift_mm,max_W,passed")
    saved=Dict(); baseline_ok=true
    function run_case(name,action)
        start=time(); item=Dict{String,Any}("case"=>name,"status"=>"running","failure"=>nothing,"checkpoints"=>Any[])
        push!(report["cases"],item)
        sim,_=R.setup_simulation("AK02";temperature=77.0)
        cp=stage->begin
            item["stage"]=stage; item["elapsed_seconds"]=time()-start
            refs=Dict{String,Any}()
            for (k,f) in (("E",sim.electric_potential),("E_vector",sim.electric_field),("W",sim.weighting_potentials[1]))
                if ismissing(f); refs[k]=nothing; continue; end
                info=gridinfo(f.grid); hash=bytes2hex(sha256(JSON.json(info))); report["grids"][hash]=info; refs[k]=hash
            end
            push!(item["checkpoints"],Dict("stage"=>stage,"elapsed_seconds"=>time()-start,"failure"=>item["failure"],"settings_ref"=>"held_settings","source_hashes_ref"=>"provenance","actual_axes_refs"=>refs))
            println(name," ",stage); flush(stdout); checkpoint()
        end
        try
            require([c.potential for c in sim.detector.contacts]==[0,500],"Bias changed")
            action(sim,item,cp,start+LIMITS.seconds)
        catch err
            item["status"]="failed"; item["failure"]=sprint(showerror,err); cp("failed/"*get(item,"stage","setup"))
        finally
            item["elapsed_seconds"]=time()-start; checkpoint()
        end
        sim,item
    end
    addcompare=(name1,name2,d)->begin
        push!(report["comparisons"],merge(Dict("reference"=>name1,"candidate"=>name2),d))
        println(comparisons,join([name1,name2,d["normalized_E"],d["onset_shifts_mm"]...,d["max_W"],d["passed"]],',')); flush(comparisons)
    end
    try
        for (name,spacing,rechecks) in (("min50",0.05,4),("min25",0.025,8))
            sim,item=run_case(name,(sim,item,cp,deadline)->begin
                item["min_grid_mm"]=spacing; item["rechecks"]=rechecks
                baseline!(sim,spacing,rechecks,item,cp,deadline); saved[name*"_initial"]=deepcopy(sim)
                original_w,_=setup(sim;weighting=true)
                item["initial_W_defects"]=defects(original_w;weighting=true); item["initial_W_projection"]=sources(original_w)
                cp("initial/native_W_audit")
                initial=profile!(sim,item,"initial",profiles); saved[name*"_initial_profile"]=initial
                e=relax!(sim,item,cp,deadline)
                before=snapshot(sim); item["before_W_continuation"]=before
                # Audit the original W with updated E projection, then continue on its own grid.
                w=relax!(sim,item,cp,deadline;weighting=true)
                item["after_W_continuation"]=snapshot(sim); require(before==item["after_W_continuation"],"W continuation changed E state")
                p=profile!(sim,item,"continued",profiles); addcompare(name*"_initial",name*"_continued",compare(initial,p))
                saved[name*"_profile"]=p; item["status"]=e&&w ? "accepted_fixed_grid" : "budget_failed"
            end)
            saved[name]=sim; baseline_ok &= item["status"]=="accepted_fixed_grid"
        end
        report["baseline_accepted"]=baseline_ok
        if all(haskey(saved,n*"_initial_profile") for n in ("min50","min25"))
            addcompare("min50_initial","min25_initial",compare(saved["min50_initial_profile"],saved["min25_initial_profile"]))
        end
        if baseline_ok; addcompare("min50_continued","min25_continued",compare(saved["min50_profile"],saved["min25_profile"])); end
        if phase!="baseline" && baseline_ok
            g=saved["min50"].electric_potential.grid; previous=saved["min50"]; priorprofile=nothing; passes=Bool[]; finest=nothing; finestprofile=nothing
            for level in 0:2
                correction=nothing
                if level>0; g,correction=nested_grid(g); end
                sim,item=run_case("nested$level",(sim,item,cp,deadline)->begin
                    item["even_z_added_m"]=correction; item["initial_guess"]="interpolated previous V/W; freshly computed alpha"
                    item["E_grid"]=gridinfo(g); cp("fixed_grid/initialize")
                    candidate!(sim,g,previous); e=relax!(sim,item,cp,deadline;fresh=true)
                    before=snapshot(sim); item["before_first_W"]=before; SSD.apply_initial_state!(sim,SSD.WeightingPotential,1,g;depletion_handling=true)
                    item["after_first_W_init"]=snapshot(sim); require(before==item["after_first_W_init"],"Candidate W initialization changed E state")
                    sim.weighting_potentials[1]=previous.weighting_potentials[1][g]
                    w=relax!(sim,item,cp,deadline;weighting=true,fresh=true); item["after_W_continuation"]=snapshot(sim); require(before==item["after_W_continuation"],"Candidate W changed E state")
                    p=profile!(sim,item,"final",profiles); saved["nested$(level)_profile"]=p
                    item["status"]=e&&w ? "accepted_fixed_grid" : "budget_failed"
                end)
                item["status"]=="accepted_fixed_grid" || break
                p=saved["nested$(level)_profile"]
                if level>0; d=compare(priorprofile,p); push!(passes,d["passed"]); addcompare("nested$(level-1)","nested$level",d); end
                previous=sim; priorprofile=p
                if level==2; finest=sim; finestprofile=p; end
            end
            coldmatch=false
            if finest!==nothing
                cold,item=run_case("nested2_cold",(sim,item,cp,deadline)->begin
                    item["initial_guess"]="zero plus contact paint; fresh alpha"
                    candidate!(sim,g,nothing); e=relax!(sim,item,cp,deadline;fresh=true)
                    before=snapshot(sim); item["before_first_W"]=before; SSD.apply_initial_state!(sim,SSD.WeightingPotential,1,g;depletion_handling=true)
                    item["after_first_W_init"]=snapshot(sim); require(before==item["after_first_W_init"],"Cold W initialization changed E state")
                    w=relax!(sim,item,cp,deadline;weighting=true,fresh=true); item["after_W_continuation"]=snapshot(sim); require(before==item["after_W_continuation"],"Cold W changed E state")
                    p=profile!(sim,item,"final",profiles); d=coldwarm(finest,sim,finestprofile,p)
                    coldmatch=e&&w&&d["passed"]; addcompare("nested2","nested2_cold",d); item["status"]=e&&w ? "accepted_fixed_grid" : "budget_failed"
                end)
            end
            report["nested_converged"]=nested_gate(passes,coldmatch)
            report["status"]=report["nested_converged"] ? "bounded_numerical_convergence" : "partial_nested_not_converged"
        else
            report["status"]=baseline_ok ? "baseline_only" : "nested_blocked_baseline_defects_or_failure"
        end
        require(provenance()==pins,"Sources changed during diagnostic")
    catch err
        report["status"]="blocked"; report["failure"]=sprint(showerror,err)
    finally
        close(profiles); close(comparisons); report["runtime_seconds"]=time()-started
        report["artifacts"]=Dict(n=>Q.sha256file(joinpath(output,n)) for n in ("profiles.csv","smallcomparisons.csv")); checkpoint()
    end
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    result=TransitionGridDiagnostics.main()
    println("Diagnostic status: ",result["status"])
    result["status"] in ("blocked","nested_blocked_baseline_defects_or_failure") && exit(1)
    result["status"]=="partial_nested_not_converged" && exit(2)
end
