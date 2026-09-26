# Native SSD Li diagnostics. No changes to the producer, models or physical closure.
isdefined(@__MODULE__, :CollectionDiagnostics) || include("diagnose_collection.jl")
module LithiumDiagnostics
using ..CollectionDiagnostics
using SolidStateDetectors, Unitful, LinearAlgebra, Random, Statistics, JSON, SHA
const C=CollectionDiagnostics
const Q=C.Q
const R=C.R
const SSD=C.SSD
const DEPTHS=[0.1,0.3,0.45,0.50,0.55,0.60,0.65,0.8,1.0]
const SEEDS=[2609261,2609262,2609263]
const GRID_CASES=[("baseline",0.05,4),("contrast50",0.05,8),("contrast25",0.025,8)]
const MODEL_PINS=Dict("AK02"=>"793de4cc598a3e26d375525e683be1bc2072e117d1c6b8003f6cdcffc9925dfa",
    "SAP22"=>"614c72f31a5a84b82c69b0b11f6f0657e87d94f746312c151f9a08cd00ba3dc3")
const PINNED=Dict("Project.toml"=>"11d7d3241bf3e11d2b01172523fbc3637a5748c2026893e596cc830c324f367e",
    "Manifest.toml"=>"14b1dc8cd127ffa0ec417939ba4abdf6b31fb2258290b6f5d922f4def8ade051")
const SDK_PINS=Dict("ChargeDrift/ChargeDrift.jl"=>"0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad",
    "Event/Event.jl"=>"5e5e411d890a409576a45b717e8235aedf294ec28cac133313a57fb30db8a15f",
    "Simulation/Simulation.jl"=>"382c6abb4d776decd9bbb64ade7111c63c69deef760f5ed8c8c40b23e72a9564")
require=C.require
region(o)=string(o["net_impurity_cm3"]>0 ? "n" : o["net_impurity_cm3"]<0 ? "p" : "compensated",
    o["nearest_grid_undepleted"] ? "-nearest-undepleted" : "-nearest-depleted",
    o["nearest_grid_inactive"] ? "-inactive-bit" : "-no-inactive-bit")
function flags(o, n, cap, stationary)
    Dict("geometric_contact"=>!isempty(o["geometric_contacts"]),"at_step_limit"=>n>=cap,
        "exactly_zero_E"=>o["field_exactly_zero"],"stationary"=>stationary,
        "n_type"=>o["net_impurity_cm3"]>0,"nearest_undepleted"=>o["nearest_grid_undepleted"])
end
function remainder(energy,we,wh)
    require(all(R.finite,(energy,we,wh))&&energy>0,"Invalid Ramo inputs")
    Dict("conditional_remainder_keV"=>energy*((1-wh)+we),"electron_component_keV"=>energy*we,
        "hole_component_keV"=>energy*(1-wh),"abs_electron_weighting"=>abs(we),
        "absolute_component_sum_keV"=>energy*(abs(1-wh)+abs(we)),
        "small_conditional_remainder"=>(abs(1-wh)+abs(we)<=1e-4),
        "weighting_out_of_range"=>!(0<=we<=1&&0<=wh<=1),"negative_remainder"=>(1-wh)+we<0)
end
function sample_stats(values,weights)
    require(!isempty(values)&&length(values)==length(weights)&&all(R.finite,values),"Invalid samples")
    require(all(w->R.finite(w)&&w>0,weights)&&all(==(first(weights)),weights)&&sum(weights)==1.0,"Lost or unequal parcel weights")
    Dict("mean"=>mean(values),"sem"=>length(values)==1 ? nothing : std(values)/sqrt(length(values)),
        "n"=>length(values),"minimum"=>minimum(values),"maximum"=>maximum(values),
        "outside_unit_range"=>count(x->!(0<=x<=1),values))
end
function parcel_seed(seed,j)
    require(seed in SEEDS&&1<=j<=32,"Invalid seed/parcel")
    1000seed+j # Same stream for corresponding parcels across depth, grid and time controls.
end
function time_config(dt,horizon)
    require(all(R.finite,(dt,horizon))&&dt in (2.0,4.0)&&horizon in (5000.0,10000.0),"Invalid fixed time case")
    (dt=Float64(dt),max_steps=round(Int,horizon/dt)+1,contact=1)
end
function check_times(t; cap=Inf)
    require(!isempty(t)&&all(R.finite,t)&&first(t)==0&&all(diff(t).>0)&&last(t)<=cap+1e-6,"Invalid actual timestamps")
end
unchanged(before,after)=require(isequal(before,after),"Input moved or energy weight changed")
function observe(sim,p,field,wp)
    o=C.observation(sim,p,field,wp)
    require(all(isfinite,vcat(o["position_mm"],o["field_V_per_cm"],
        [o[k] for k in ("weighting_potential","field_magnitude_V_per_cm","net_impurity_cm3","li_donor_cm3","nearest_grid_impurity_scale")],
        [d["distance_mm"] for d in o["contact_distances"]])),"Nonfinite observation")
    o["region"]=region(o); o
end
function options(args)
    require(iseven(length(args)),"Use --input ROOT --output .local/NEW [--phase audit|depth|all]")
    v=Dict{String,String}()
    for i in 1:2:length(args)
        require(args[i] in ("--input","--output","--phase")&&!haskey(v,args[i]),"Unknown/duplicate option")
        v[args[i]]=args[i+1]
    end
    require(haskey(v,"--input")&&haskey(v,"--output"),"Input and output are required")
    phase=get(v,"--phase","all"); require(phase in ("audit","depth","all"),"Unknown phase")
    input=realpath(v["--input"]); output=Q.validate_output(v["--output"])
    require(Q.childof(input,joinpath(realpath(Q.ROOT),".local"))&&!Q.childof(output,input),"Input/output must be separate .local roots")
    input,output,phase
end
function check_hashes(root,hashes)
    for (name,hash) in hashes
        file=joinpath(root,name)
        require(isfile(file)&&Q.childof(realpath(file),realpath(root))&&Q.sha256file(file)==hash,"Changed/escaped input: $name")
    end
end
function readout_config(root,manifest)
    binding=manifest["readout_config"]; n=manifest["settings"]["events_per_model"]
    require(binding["file"]=="readout-config.json"&&binding["allowed_changed_fields"]==["expected_primary_count"],"Invalid readout binding")
    require(binding["baseline_sha256"]==Q.sha256file(joinpath(@__DIR__,"readout_demo.json")),"Readout baseline changed")
    require(binding["effective_sha256"]==manifest["artifacts"]["readout-config.json"],"Readout hash mismatch")
    expected=JSON.parsefile(joinpath(@__DIR__,"readout_demo.json")); expected["expected_primary_count"]=n
    require(JSON.parsefile(joinpath(root,"readout-config.json"))==expected,"Readout changed beyond primary count")
end
function load_source(root)
    m=JSON.parsefile(joinpath(root,"run.json"))
    require(m["schema_version"]==2&&m["status"]=="complete"&&sort(m["models"])==["AK02","SAP22"],"Need completed schema-2 AK02/SAP22 pipeline")
    n=m["settings"]["events_per_model"]
    require(R.integer(n)&&1<=n<=100&&m["settings"]["temperature_K"]==77&&m["settings"]["device"]=="cpu","Unsupported input workload/temperature/device")
    env=Q.environment("cpu")
    require(env["project"]=="simulation/Project.toml"&&env["environment_manifest_sha256"]==PINNED["Manifest.toml"],"Use pinned CPU environment")
    check_hashes(@__DIR__,PINNED); check_hashes(dirname(pathof(SSD)),SDK_PINS)
    check_hashes(root,m["artifacts"]); check_hashes(Q.ROOT,m["sources"]); readout_config(root,m)
    for model in ("AK02","SAP22"), name in ("transport/events.json","charge/run.json","charge/signals.csv","readout/run.json")
        require(haskey(m["artifacts"],model*"/"*name),"Missing artifact binding: $model/$name")
    end
    check_hashes(Q.MODEL_DIR,Dict(model*".yaml"=>hash for (model,hash) in MODEL_PINS))
    for file in ("run.jl","replay.jl","readout.jl","readout_demo.json","Project.toml","Manifest.toml")
        require(m["sources"]["simulation/"*file]==Q.sha256file(joinpath(@__DIR__,file)),"Missing producer pin")
    end
    inputs=Dict{String,Any}()
    for model in ("AK02","SAP22")
        path=joinpath(root,model,"transport","events.json"); d,meta=R.load_input(path)
        q=JSON.parsefile(joinpath(root,model,"charge","run.json")); solver=q["solver"]
        require(d["model_id"]==q["model_id"]==model&&d["model_sha256"]==q["model_sha256"]==Q.model_entry(model)["model_sha256"]==MODEL_PINS[model],"Wrong model identity")
        require(q["status"] in ("completed","completed_with_transport_flags")&&q["input_sha256"]==Q.sha256file(path),"Incomplete/changed charge input")
        require(d["primary_count"]==q["selected_primary_count"]==q["primary_count"]==n==length(q["events"])&&isempty(q["unselected_event_ids"]),"Census changed")
        require(q["effective_temperature_K"]==q["temperature_override_K"]==77&&q["stored_temperature_K"]==78&&q["contact_potentials_V"]==[0,model=="AK02" ? 500 : 700],"Temperature/bias changed")
        require(q["precision_bits"]==64&&q["time_step_ns"]==2&&q["sor_constant"]==1&&!q["diffusion"]&&!q["self_repulsion"]&&q["end_drift_when_no_field"],"Producer drift settings changed")
        require(solver["min_tick_distance_mm"]==0.05&&solver["max_tick_distance_mm"]==2&&solver["potential_recheck_limit"]==4&&solver["max_iterations_per_refinement"]==50000,"Producer grid changed")
        require(q["environment_manifest_sha256"]==PINNED["Manifest.toml"]&&q["ssd_version"]==env["ssd_version"]&&q["julia_version"]==env["julia_version"],"Producer environment mismatch")
        check_hashes(@__DIR__,q["source_code_sha256"])
        steps=[s for e in d["events"] for s in e["steps"]]
        require(length(steps)<=20000&&count(s->s["energy_keV"]>0,steps)<=2048,"Fixed audit work cap exceeded")
        inputs[model]=(truth=d,meta=meta,charge=q)
    end
    m,inputs,env
end
function grid_snapshot(f)
    require(all(x->x isa Number ? isfinite(x) : all(isfinite,x),f.data),"Nonfinite field grid")
    require(all(a->all(isfinite,a),f.grid.axes),"Nonfinite grid ticks")
    Dict("shape"=>collect(size(f.data)),"ticks_internal"=>[collect(a) for a in f.grid.axes],
        "sha256_native_bytes"=>bytes2hex(sha256(reinterpret(UInt8,vec(f.data)))),"element_type"=>string(eltype(f.data)))
end
function solve(model,case,output,item)
    name,spacing,rechecks=case; println("Li diagnostic: ",model," / ",name," field solve"); flush(stdout)
    sim,_=R.setup_simulation(model;temperature=77.0)
    cfg=Q.parse_args(["--model",model,"--position-mm","3,0,5","--precision","64","--dt-ns","2",
        "--min-grid-mm",string(spacing),"--max-grid-mm","2","--max-iterations","50000","--output",joinpath(output,"unused")])
    merge!(item,Dict("model"=>model,"case"=>name,"status"=>"solving","min_grid_mm"=>spacing,"rechecks"=>rechecks,
        "model_sha256"=>Q.model_entry(model)["model_sha256"],"cfg"=>Dict(string(k)=>v for (k,v) in pairs(cfg) if k!=:output),"checks"=>Any[]))
    started=time()
    try
        item["solver"],item["timings"]=Q.solve_fields!(sim,cfg,Q.prepare_backend("cpu");sor_consts=1.0,potential_rechecks=rechecks,iteration_observer=x->push!(item["checks"],x))
    catch err
        item["status"]="solver_failed"; item["error"]=sprint(showerror,err); rethrow()
    finally
        item["field_attempt_wall_seconds"]=time()-started
    end
    item["grids"]=Dict("E"=>grid_snapshot(sim.electric_field),"potential"=>grid_snapshot(sim.electric_potential),"W"=>grid_snapshot(sim.weighting_potentials[1]))
    item["status"]="fields_ready"; sim,cfg
end
function endpoint(sim,path,times,field,wp,cap)
    check_times(times.*1e9)
    require(all(p->all(isfinite,C.xyz(p)),path)&&length(path)==length(times),"Invalid path")
    o=observe(sim,last(path),field,wp)
    tail=length(path); while tail>1&&C.xyz(path[tail-1])==C.xyz(last(path)); tail-=1; end
    stationary=tail<length(path)
    merge!(o,Dict("flags"=>flags(o,length(path),cap,stationary),"samples"=>length(path),"end_time_ns"=>last(times)*1e9,
        "last_displacement_mm"=>length(path)>1 ? 1000norm(path[end]-path[end-1]) : 0.0,
        "stationary_tail_samples"=>length(path)-tail+1,"stationary_tail_start_ns"=>stationary ? times[tail]*1e9 : nothing,
        "noncontact_outer_points"=>count(p->!(p in sim.detector.semiconductor)&&!any(c->p in c.geometry,sim.detector.contacts),path),
        "contact_2_gap_mm"=>only(filter(d->d["contact_id"]==2,o["contact_distances"]))["distance_mm"]))
    o
end
function deposit(sim,position,energy,cfg,field,wp; diffusion=false,stop=true)
    require(R.vec3(position)&&R.finite(energy)&&energy>0,"Invalid deposit")
    p=CartesianPoint{Float64}((Float64.(position)./1000)...)
    require(p in sim.detector.semiconductor&&!any(c->p in c.geometry,sim.detector.contacts),"Deposit outside/on contact")
    evt=Event([p],[energy*u"keV"]); before=deepcopy((evt.locations,evt.energies))
    drift_charges!(evt,sim;Δt=cfg.dt*u"ns",max_nsteps=cfg.max_steps,geometry_check=true,diffusion=diffusion,self_repulsion=false,end_drift_when_no_field=stop,verbose=false)
    unchanged(before,(evt.locations,evt.energies))
    require(evt.energies[1][1]==energy*1000,"Input energy conversion changed")
    drift=only(evt.drift_paths)
    ends=Dict(s=>endpoint(sim,p,t,field,wp,cfg.max_steps) for (s,p,t) in (("electron",drift.e_path,drift.timestamps_e),("hole",drift.h_path,drift.timestamps_h)))
    for t in (drift.timestamps_e,drift.timestamps_h); check_times(t.*1e9;cap=(cfg.max_steps-1)*cfg.dt); end
    SSD.get_signal!(evt,sim,1;Δt=cfg.dt*u"ns",signal_unit=u"keV"); wave=evt.waveforms[1]
    original=sim.detector
    ideal=try
        sim.detector=SSD.SolidStateDetector(original,SSD.NoChargeTrappingModel{Float64}())
        SSD.get_signal(sim,evt.drift_paths,[Float64(energy*1000)],1;Δt=cfg.dt*u"ns",signal_unit=u"keV")
    finally
        sim.detector=original
    end
    t=Float64.(ustrip.(u"ns",wave.time)); q=Float64.(ustrip.(u"keV",wave.signal)); qi=Float64.(ustrip.(u"keV",ideal.signal))
    check_times(t); require(all(isfinite,q)&&all(isfinite,qi)&&length(q)==length(qi)==length(t),"Nonfinite/misaligned signal")
    we=ends["electron"]["weighting_potential"]; wh=ends["hole"]["weighting_potential"]; error=last(qi)/energy-(wh-we)
    start=observe(sim,p,field,wp)
    row=Dict("energy_keV"=>energy,"start"=>start,"endpoints"=>ends,"original_endpoint_report"=>Q.endpoint_report(evt,sim,cfg),
        "original_final_keV"=>last(q),"no_trapping_final_keV"=>last(qi),"original_fraction"=>last(q)/energy,
        "no_trapping_fraction"=>last(qi)/energy,"ramo_error"=>error,"ramo_pass"=>abs(error)<=1e-10,
        "path_integrity_pass"=>all(e["noncontact_outer_points"]==0 for e in values(ends)))
    merge!(row,remainder(energy,we,wh)); row,t,q,qi
end
function audit!(item,sim,cfg,input,csv)
    started=time()
    R.geometry_check(input.meta,sim); R.validate_deposits(input.truth,sim)
    field=SSD.interpolated_vectorfield(sim.electric_field); wp=SSD.interpolated_scalarfield(sim.weighting_potentials[1])
    item["events"]=Any[]; item["differences"]=Any[]
    for (event,saved) in zip(input.truth["events"],input.charge["events"])
        item["active_event_id"]=event["event_id"]
        require(event["event_id"]==saved["event_id"]&&event["primary_time_ns"]==saved["primary_time_ns"],"Saved event identity changed")
        rows=Any[]; components=Any[]
        out=Dict("event_id"=>event["event_id"],"primary_time_ns"=>event["primary_time_ns"],"raw_steps"=>event["steps"],"source_charge_report"=>saved,"deposits"=>rows)
        push!(item["events"],out)
        for s in event["steps"]
            s["energy_keV"]==0&&continue
            item["active_raw_row_index"]=s["raw_row_index"]
            row,t,q,_=deposit(sim,s["position_mm"],s["energy_keV"],cfg,field,wp)
            row["raw_row_index"]=s["raw_row_index"]; push!(rows,row)
            old=only(filter(x->x["raw_row_index"]==s["raw_row_index"],saved["steps"]))
            delta=row["original_final_keV"]-old["last_induced_equivalent_energy_keV"]
            same=row["original_endpoint_report"]==old["endpoints"]&&abs(delta)<=1e-10&&old["deposited_energy_keV"]==s["energy_keV"]&&old["deposition_delay_ns"]==s["time_ns"]-event["primary_time_ns"]
            row["source_match"]=same; row["source_final_difference_keV"]=delta
            same||push!(item["differences"],Dict("event_id"=>event["event_id"],"raw_row_index"=>s["raw_row_index"],"delta_keV"=>delta,"endpoints_equal"=>row["original_endpoint_report"]==old["endpoints"]))
            push!(components,(delay=Float64(s["time_ns"]-event["primary_time_ns"]),times=t,charge=q))
            for species in ("electron","hole")
                e=row["endpoints"][species]; f=e["flags"]
                println(csv,join([item["model"],event["event_id"],s["raw_row_index"],species,s["energy_keV"],row["original_final_keV"],row["no_trapping_final_keV"],row["conditional_remainder_keV"],e["weighting_potential"],e["end_time_ns"],e["region"],f["geometric_contact"],f["at_step_limit"],f["exactly_zero_E"],f["stationary"],same],','))
            end
        end
        _,signal=R.causal_sum(components,cfg.dt)
        status=isempty(rows) ? "zero_deposit" : any(e["step_limit_reached"] for r in rows for e in r["original_endpoint_report"]) ? "step_limit" : any(e["status"]=="stopped_without_contact" for r in rows for e in r["original_endpoint_report"]) ? "stopped_without_contact" : "completed"
        out["conditional_remainder_keV"]=sum((r["conditional_remainder_keV"] for r in rows);init=0.0)
        out["absolute_component_sum_keV"]=sum((r["absolute_component_sum_keV"] for r in rows);init=0.0)
        out["no_trapping_final_keV"]=sum((r["no_trapping_final_keV"] for r in rows);init=0.0)
        out["original_final_keV"]=last(signal); out["replayed_status"]=status
        out["source_match"]=status==saved["status"]&&length(rows)==saved["charge_deposits"]==length(saved["steps"])&&length(event["steps"])==saved["raw_rows"]&&abs(last(signal)-saved["final_induced_equivalent_energy_keV"])<=1e-10
        out["source_match"]||push!(item["differences"],Dict("event_id"=>event["event_id"],"event_summary_mismatch"=>true))
    end
    rows=[r for e in item["events"] for r in e["deposits"]]; item["summary"]=endpoint_summary(rows)
    item["summary"]["primary_count"]=length(item["events"])
    item["summary"]["zero_deposit_primaries"]=count(e->isempty(e["deposits"]),item["events"])
    item["integrity_pass"]=isempty(item["differences"])&&all(r["ramo_pass"]&&r["path_integrity_pass"] for r in rows)
    item["status"]="audit_recorded"; item["audit_drift_signal_seconds"]=time()-started
end
function endpoint_summary(rows)
    residual=[abs(r["conditional_remainder_keV"])/r["energy_keV"] for r in rows]
    absolute=[r["absolute_component_sum_keV"]/r["energy_keV"] for r in rows]
    energy=sum((r["energy_keV"] for r in rows);init=0.0)
    Dict("deposits"=>length(rows),"max_abs_conditional_fraction"=>isempty(residual) ? nothing : maximum(residual),
        "median_abs_conditional_fraction"=>isempty(residual) ? nothing : median(residual),
        "small_noncancelling_remainder_count"=>count(<=(1e-4),absolute),
        "max_absolute_component_fraction"=>isempty(absolute) ? nothing : maximum(absolute),
        "energy_weighted_absolute_component_fraction"=>energy==0 ? nothing : sum(r["absolute_component_sum_keV"] for r in rows)/energy,
        "energy_keV"=>energy,"energy_weighted_conditional_fraction"=>energy==0 ? nothing : sum(r["conditional_remainder_keV"] for r in rows)/energy,
        "below_abs_fraction_counts"=>Dict(string(t)=>count(<(t),residual) for t in (1e-6,1e-4,1e-3)),
        "zero_E_and_stationary_counts"=>Dict(s=>count(r->r["endpoints"][s]["flags"]["exactly_zero_E"]&&r["endpoints"][s]["flags"]["stationary"],rows) for s in ("electron","hole")),
        "species_counts"=>Dict(s=>Dict(k=>count(r->r["endpoints"][s]["flags"][k],rows) for k in ("geometric_contact","at_step_limit","exactly_zero_E","stationary","n_type","nearest_undepleted")) for s in ("electron","hole")))
end
function profile!(sim,item,csv)
    field=SSD.interpolated_vectorfield(sim.electric_field); wp=SSD.interpolated_scalarfield(sim.weighting_potentials[1]); cdm=sim.detector.semiconductor.charge_drift_model
    density(d)=SSD.get_impurity_density(sim.detector.semiconductor.impurity_density_model,CartesianPoint{Float64}((12.65-d)/1000,0,0.0047))
    lo=0.0; hi=1.0; require(density(lo)>0&&density(hi)<0,"No compensation root in fixed interval")
    for _ in 1:60; mid=(lo+hi)/2; if density(mid)>0; lo=mid; else; hi=mid; end; end
    item["compensation_depth_mm"]=(lo+hi)/2; depths=collect(0:500).*0.002; fields=Float64[]
    for d in depths
        p=CartesianPoint{Float64}((12.65-d)/1000,0,0.0047); o=observe(sim,p,field,wp); push!(fields,o["field_magnitude_V_per_cm"])
        mu=[SSD.calculate_mobility(cdm,p,s) for s in (SSD.Electron,SSD.Hole)]; D=mu.*(77*1.380649e-23/1.602176634e-19)
        require(all(x->isfinite(x)&&x>0,vcat(mu,D)),"Invalid native mobility/diffusion")
        println(csv,join([item["case"],d,last(fields),o["weighting_potential"],o["li_donor_cm3"],o["net_impurity_cm3"],mu...,D...,o["nearest_grid_bits"],o["nearest_grid_impurity_scale"],region(o)],','))
    end
    item["field_brackets"]=map((0.0,1.0)) do threshold
        i=findfirst(>(threshold),fields)
        Dict("reporting_threshold_V_cm"=>threshold,"below_mm"=>isnothing(i)||i==1 ? nothing : depths[i-1],"above_mm"=>isnothing(i) ? nothing : depths[i])
    end
end
function mean_trace(traces,ideals,horizon)
    tt,qq=R.causal_sum(traces,2.0); ti,qi=R.causal_sum(ideals,2.0)
    require(tt==ti,"NoTrapping trace support changed")
    finals=(last(qq),last(qi)) # Exact final statistics precede display decimation.
    while last(tt)<horizon; push!(tt,last(tt)+2); push!(qq,last(qq)); push!(qi,last(qi)); end
    idx=unique(round.(Int,range(1,length(tt);length=min(300,length(tt)))))
    Dict("time_ns"=>tt[idx],"original_fraction"=>qq[idx],"no_trapping_fraction"=>qi[idx],"full_grid_ns"=>2.0,"terminal_charge_held"=>true),finals
end
function cloud!(item,sim,depth,dt,horizon,seed,csv; diffusion=true)
    cfg=time_config(dt,horizon); n=diffusion ? 32 : 1; weights=fill(1.0/n,n)
    field=SSD.interpolated_vectorfield(sim.electric_field); wp=SSD.interpolated_scalarfield(sim.weighting_potentials[1])
    rows=Any[]; traces=Any[]; ideals=Any[]; started=time()
    cloud=Dict("grid_case"=>item["case"],"depth_mm"=>depth,"dt_ns"=>dt,"horizon_ns"=>horizon,"seed"=>seed,"parcels"=>rows,
        "diffusion"=>diffusion,"end_drift_when_no_field"=>!diffusion,"self_repulsion"=>false,"total_energy_keV"=>1.0,"numerical_parcels"=>n)
    push!(item["clouds"],cloud)
    for j in 1:n
        cloud["active_parcel_id"]=j
        derived=parcel_seed(seed,j); Random.seed!(derived)
        row,t,q,qi=deposit(sim,[12.65-depth,0.0,4.7],weights[j],cfg,field,wp;diffusion=diffusion,stop=!diffusion)
        row["parcel_id"]=j; row["derived_seed"]=derived; push!(rows,row)
        # Two-ns mean trace, with terminal charge held, including the fixed requested horizon.
        push!(traces,(delay=0.0,times=t,charge=q)); push!(ideals,(delay=0.0,times=t,charge=qi))
    end
    cloud["original_stats"]=sample_stats([r["original_fraction"] for r in rows],weights)
    cloud["no_trapping_stats"]=sample_stats([r["no_trapping_fraction"] for r in rows],weights)
    cloud["summary"]=endpoint_summary(rows); cloud["integrity_pass"]=all(r["ramo_pass"]&&r["path_integrity_pass"] for r in rows)
    cloud["mean_trace"],finals=mean_trace(traces,ideals,horizon)
    require(abs(finals[1]-cloud["original_stats"]["mean"])<=1e-12&&abs(finals[2]-cloud["no_trapping_stats"]["mean"])<=1e-12,"Mean trace changed parcel weights")
    cloud["runtime_s"]=time()-started; a=cloud["original_stats"]; b=cloud["no_trapping_stats"]
    println("Li cloud ",item["case"]," depth=",depth," dt=",dt," horizon=",horizon," seed=",seed," Q=",a["mean"]," s=",round(cloud["runtime_s"];digits=2)); flush(stdout)
    println(csv,join([item["case"],depth,dt,horizon,seed,n,diffusion,a["mean"],a["sem"],b["mean"],b["sem"],cloud["integrity_pass"]],','))
    cloud
end
function sensitivities(items)
    clouds=[c for item in items for c in get(item,"clouds",[]) if c["diffusion"]]; comparisons=Any[]
    for b in clouds
        name=b["grid_case"]; grid=name=="contrast25"; control=name=="baseline"&&(b["dt_ns"]!=2||b["horizon_ns"]!=5000)
        (grid||control)||continue
        a=only(filter(c->c["grid_case"]==(grid ? "contrast50" : "baseline")&&c["depth_mm"]==b["depth_mm"]&&c["seed"]==b["seed"]&&c["dt_ns"]==2&&c["horizon_ns"]==5000,clouds))
        for key in ("original_stats","no_trapping_stats")
            x=a[key]; y=b[key]; gate=max(0.03,4sqrt(x["sem"]^2+y["sem"]^2)); delta=abs(x["mean"]-y["mean"])
            push!(comparisons,Dict("kind"=>grid ? "grid" : b["dt_ns"]==4 ? "time_step" : "horizon","depth_mm"=>b["depth_mm"],"seed"=>b["seed"],"signal"=>key,"absolute_difference"=>delta,"prospective_gate"=>gate,"passed"=>delta<=gate))
        end
    end
    comparisons
end
function main(args=ARGS)
    input,output,phase=options(args); output=Q.reserve_output(output); started=time()
    report=Dict{String,Any}("schema_version"=>1,"kind"=>"native_lithium_diagnostics","status"=>"running","stage"=>"input_validation","phase"=>phase,"cases"=>Any[],
        "units"=>Dict("energy"=>"keV","position"=>"mm","time"=>"ns","field"=>"V/cm","density"=>"cm^-3","grid_ticks"=>"m,rad,m","mobility"=>"m^2/(V s)","diffusion"=>"m^2/s"),
        "limitations"=>["Diagnostic only: no measured CCE, finite-conductivity or variable-D Ito-law validation.","Nearest grid bits and net doping labels are not continuous boundaries; 1 V/cm is only a reporting threshold.",
        "Conditional Ramo remainder assumes static weighting, eventual hole W=1/electron W=0 contacts and no further loss; not a physical CCE bound. Values are never clipped.",
        "Native lifetime trapping weights identical paths, not stochastic trajectory killing. A 1 us lifetime does not establish full collection at 5/10 us.",
        "SEM describes numerical Monte Carlo parcels only, not measured CCE uncertainty. Sensitivity failures remain unvalidated.","Runtime includes compilation; no warmed production timing claim."])
    ios=IO[]
    try
        report["input_run_sha256"]=Q.sha256file(joinpath(input,"run.json"))
        m,inputs,env=load_source(input); report["environment"]=env
        report["fixed_work"]=Dict("depths_mm"=>DEPTHS,"seeds"=>SEEDS,"grid_cases"=>GRID_CASES,"parcels_per_seed"=>32,"max_primaries_per_model"=>100,"max_positive_deposits_per_model"=>2048,
            "diffusive_clouds"=>63,"no_diffusion_controls"=>9,"default_dt_ns"=>2,"default_horizon_ns"=>5000,"sensitivity_formula"=>"abs(meanA-meanB) <= max(0.03,4*sqrt(semA^2+semB^2))")
        report["input_artifacts"]=m["artifacts"]; report["producer_sources"]=m["sources"]; report["sdk_source_pins"]=SDK_PINS
        report["source_hashes"]=Dict(n=>Q.sha256file(joinpath(@__DIR__,n)) for n in ("diagnose_lithium.jl","test_lithium.jl","diagnose_collection.jl"))
        for (name,header) in (("endpoint-audit.csv","model,event_id,raw_row_index,species,energy_keV,original_keV,no_trapping_keV,conditional_remainder_keV,endpoint_W,end_time_ns,region,geometric_contact,at_step_limit,exactly_zero_E,stationary,source_match"),
            ("depth-scan.csv","grid_case,depth_mm,dt_ns,horizon_ns,seed,n,diffusion,mean,sem,no_trapping_mean,no_trapping_sem,integrity_pass"),
            ("profiles.csv","grid_case,depth_mm,E_V_cm,W,donor_cm3,net_cm3,mu_e_m2_V_s,mu_h_m2_V_s,D_e_m2_s,D_h_m2_s,nearest_bits,impurity_scale,region"))
            io=open(joinpath(output,name),"w"); push!(ios,io); println(io,header)
        end
        baseline=nothing
        for model in (phase=="depth" ? ("AK02",) : ("AK02","SAP22"))
            item=Dict{String,Any}(); push!(report["cases"],item); report["stage"]="$model/baseline/solve"
            sim,cfg=solve(model,GRID_CASES[1],output,item)
            if model=="AK02"; baseline=sim; report["stage"]="AK02/baseline/profile"; profile!(sim,item,ios[3]); end
            if phase!="depth"; report["stage"]="$model/audit"; audit!(item,sim,cfg,inputs[model],ios[1]); end
        end
        require(all(get(i,"integrity_pass",true) for i in report["cases"]),"Source replay/Ramo/path integrity mismatch; see retained audit")
        if phase!="audit"
            for case in GRID_CASES
                report["stage"]="AK02/$(case[1])/solve"
                if case[1]=="baseline"; item=first(report["cases"]); sim=baseline
                else; item=Dict{String,Any}(); push!(report["cases"],item); sim,_=solve("AK02",case,output,item); profile!(sim,item,ios[3]); end
                item["clouds"]=Any[]; report["stage"]="AK02/$(case[1])/depth"
                if case[1]=="baseline"
                    for d in DEPTHS; cloud!(item,sim,d,2.0,5000.0,first(SEEDS),ios[2];diffusion=false); end
                    for d in DEPTHS, seed in SEEDS; cloud!(item,sim,d,2.0,5000.0,seed,ios[2]); end
                    for d in (0.3,0.55,0.8), seed in SEEDS, (dt,h) in ((4.0,5000.0),(2.0,10000.0)); cloud!(item,sim,d,dt,h,seed,ios[2]); end
                else
                    for d in (0.50,0.55,0.60), seed in SEEDS; cloud!(item,sim,d,2.0,5000.0,seed,ios[2]); end
                end
                item["status"]="recorded"
            end
            report["sensitivities"]=sensitivities(report["cases"])
            report["sensitivity_all_passed"]=all(c["passed"] for c in report["sensitivities"])
            require(all(c["integrity_pass"] for i in report["cases"] for c in get(i,"clouds",[])),"Ramo/path integrity failed; raw diagnostic records retained")
        end
        report["stage"]="final_input_verification"
        require(Q.sha256file(joinpath(input,"run.json"))==report["input_run_sha256"],"Input manifest changed during run")
        check_hashes(input,m["artifacts"]); check_hashes(Q.ROOT,m["sources"]); check_hashes(@__DIR__,report["source_hashes"])
        check_hashes(dirname(pathof(SSD)),SDK_PINS); Q.verify_model_files()
        check_hashes(Q.MODEL_DIR,Dict(model*".yaml"=>hash for (model,hash) in MODEL_PINS))
        report["status"]="completed_diagnostics_only"
    catch err
        report["status"]="failed"; report["error"]=sprint(showerror,err); rethrow()
    finally
        foreach(close,ios); report["runtime_s"]=time()-started
        Q.save_json(joinpath(output,"report.json"),report)
    end
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__; LithiumDiagnostics.main(); end
