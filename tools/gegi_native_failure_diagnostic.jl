# Retained-input diagnosis only. No transport, field solve, or shared-readout replay.
include(joinpath(@__DIR__,"..","simulation","gegi_response.jl"))
using JSON, Serialization, Unitful, LinearAlgebra, SHA
const G=GeGIResponse;const SSD=G.SSD
jsonnumber(value)=isfinite(value) ? value : string(value)
jsonsafe(value)=value
jsonsafe(value::AbstractFloat)=jsonnumber(value)
jsonsafe(value::AbstractArray)=jsonsafe.(value)
jsonsafe(value::AbstractDict)=Dict(key=>jsonsafe(v) for (key,v) in value)
function terminal_trial(sim,p,species,cfg)
    # Re-evaluate the existing SSD one-step operations at the saved endpoint;
    # this observation does not advance a carrier or change a response record.
    T=SSD.get_precision_type(sim)
    field=SSD.get_velocity_vector(SSD.interpolated_vectorfield(sim.electric_field),p)
    velocity=(species=="electron" ? SSD.getVe : SSD.getVh)(SSD.SVector{3,T}(field),sim.detector.semiconductor.charge_drift_model,p)
    step=SSD.CartesianVector{T}(velocity*T(ustrip(u"s",cfg.dt*u"ns")))
    step=SSD.modulate_driftvector(step,p,sim.detector.virtual_drift_volumes)
    candidate=p+step
    trial=Dict{String,Any}("field_V_m"=>Float64[field.x,field.y,field.z],
        "unconstrained_step_mm"=>Float64[step.x,step.y,step.z].*1000,
        "candidate_position_mm"=>Float64[candidate.x,candidate.y,candidate.z].*1000,
        "candidate_equals_endpoint"=>candidate==p,"candidate_inside"=>candidate in sim.detector.semiconductor,
        "candidate_contact_ids"=>[c.id for c in sim.detector.contacts if candidate in c.geometry])
    if candidate!=p && !(candidate in sim.detector.semiconductor && isempty(trial["candidate_contact_ids"]))
        crossing,kind,normal=SSD.get_crossing_pos(sim.detector,sim.point_types,p,candidate)
        trial["crossing_code"]=Int(kind);trial["crossing_position_mm"]=Float64[crossing.x,crossing.y,crossing.z].*1000
        trial["crossing_normal"]=Float64[normal.x,normal.y,normal.z]
        contact=any(c->crossing in c.geometry,sim.detector.contacts)
        trial["crossing_has_geometric_contact"]=contact
        if kind==SSD.CD_FLOATING_BOUNDARY || (kind==SSD.CD_ELECTRODE && !contact)
            projected=SSD.CartesianVector{T}(SSD.project_to_plane(step,normal))
            projected=SSD.modulate_surface_drift(projected)
            trial["projected_step_mm"]=Float64[projected.x,projected.y,projected.z].*1000
            trial["projected_candidate_equals_endpoint"]=(p+projected)==p
        end
    end
    trial
end

function diagnose_deposit(sim,step,cfg;drift_only=false)
    T=SSD.get_precision_type(sim);xyz=step["position_mm"]
    p=SSD.CartesianPoint{T}((T.(xyz)./T(1000))...)
    contacts=[c.id for c in sim.detector.contacts if p in c.geometry]
    row=Dict{String,Any}("raw_row_index"=>step["raw_row_index"],"position_mm"=>xyz,
        "stored_position_mm"=>Float64[p.x,p.y,p.z].*1000,"energy_keV"=>step["energy_keV"],
        "start_contact_ids"=>contacts,"start_inside"=>p in sim.detector.semiconductor)
    isempty(contacts) || return merge(row,Dict("status"=>"contact_start"))
    e=SSD.Event([p],[step["energy_keV"]*u"keV"])
    try
        Base.invokelatest(SSD.drift_charges!,e,sim;Δt=cfg.dt*u"ns",max_nsteps=cfg.max_steps,
            geometry_check=true,diffusion=false,self_repulsion=false,end_drift_when_no_field=true,verbose=true)
    catch err
        err isa G.NativeBoundaryGuard.BoundaryStall || rethrow()
        row["status"]="native_boundary_failure";row["boundary_failure"]=G.NativeBoundaryGuard.detail(err)
        point=SSD.CartesianPoint{T}(T.(err.last_valid_m)...)
        row["terminal_field_V_m"]=jsonnumber.(collect(Float64.(SSD.interpolated_vectorfield(sim.electric_field)(point.x,point.y,point.z))))
        rejected=SSD.CartesianPoint{T}(T.(err.rejected_m)...)
        if rejected!=point
            crossing,kind,normal=SSD.get_crossing_pos(sim.detector,sim.point_types,point,rejected)
            row["projected_segment_geometry"]=Dict("crossing_code"=>Int(kind),
                "crossing_equals_endpoint"=>crossing==point,"crossing_position_m"=>Float64[crossing.x,crossing.y,crossing.z],
                "crossing_normal"=>Float64[normal.x,normal.y,normal.z],
                "normal_dot_segment_m"=>dot(normal,rejected-point),"segment_length_m"=>norm(rejected-point))
        end
        return row
    end
    row["endpoints"]=G.Q.endpoint_report(e,sim,cfg)
    row["terminal_paths"]=[Dict("species"=>species,"position_mm"=>[[Float64(p.x)*1000,Float64(p.y)*1000,Float64(p.z)*1000] for p in path[max(1,end-2):end]],
        "time_ns"=>Float64.(times[max(1,end-2):end]).*1e9,
        "stationary_last_step"=>length(path)>=2 && path[end]==path[end-1],
        "terminal_trial"=>isempty([c.id for c in sim.detector.contacts if last(path) in c.geometry]) ? terminal_trial(sim,last(path),species,cfg) : nothing,
        "terminal_field_V_m"=>jsonnumber.(collect(Float64.(SSD.interpolated_vectorfield(sim.electric_field)(last(path).x,last(path).y,last(path).z)))))
        for drift in e.drift_paths for (species,path,times) in (("electron",drift.e_path,drift.timestamps_e),("hole",drift.h_path,drift.timestamps_h))]
    row["status"]=any(e->!(e["inside_semiconductor"]||!isempty(e["contact_ids"])),row["endpoints"]) ?
        "outside_endpoint" : any(e->e["step_limit_reached"],row["endpoints"]) ? "step_limit" :
        any(e->e["status"]=="stopped_without_contact",row["endpoints"]) ? "stopped_without_contact" : "completed"
    drift_only && return row
    for id in 1:34
        SSD.get_signal!(e,sim,id;Δt=cfg.dt*u"ns",signal_unit=u"keV")
        w=e.waveforms[id];q=Float64.(ustrip.(u"keV",w.signal)); t=Float64.(ustrip.(u"ns",w.time))
        bad=String[]
        length(q)>=2 || push!(bad,"sample_count_lt_2")
        all(isfinite,q) || push!(bad,"nonfinite_sample")
        isempty(q) || first(q)==0 || push!(bad,"initial_sample_nonzero")
        if !isempty(bad)
            row["status"]="invalid_signed_charge";row["contact_id"]=id;row["failed_invariants"]=bad
            row["native_charge_keV"]=jsonnumber.(q);row["native_time_ns"]=jsonnumber.(t)
            row["native_charge_float64_bits"]=bitstring.(q);return row
        end
    end
    row
end

function main(args=ARGS)
    length(args)>=3 || error("Usage: gegi_native_failure_diagnostic.jl REQUEST INPUTS_JSON OUTPUT_JSON [--promote-drift] [--analytic-boundary] [--native-groups|--drift-only]")
    flags=Set(args[4:end]);issubset(flags,Set(("--promote-drift","--analytic-boundary","--native-groups","--contact-census","--drift-only"))) || error("Unknown diagnostic option")
    ("--native-groups" in flags && "--drift-only" in flags) && error("Choose full native groups or per-deposit drift diagnosis")
    promote="--promote-drift" in flags;analytic="--analytic-boundary" in flags
    req=G.E.readjson(args[1]);cfg=G.numerics(req)
    cfg=merge(cfg,(analytic_boundary=analytic,))
    if "--contact-census" in flags
        model=G.pinned_input(req,"model_ref","model_sha256")
        s32=SSD.Simulation{Float32}(model);s64=SSD.Simulation{Float64}(model)
        rows=Any[]
        for example in G.E.readjson(args[2])
            contacts=Any[]
            for step in example["group"]["steps"]
                xyz=step["position_mm"]
                p32=SSD.CartesianPoint{Float32}((Float32.(xyz)./1000f0)...)
                p64=SSD.CartesianPoint{Float64}((Float64.(xyz)./1000.)...)
                ids32=[c.id for c in s32.detector.contacts if p32 in c.geometry]
                ids64=[c.id for c in s64.detector.contacts if p64 in c.geometry]
                isempty(ids32) || push!(contacts,Dict("raw_row_index"=>step["raw_row_index"],"position_mm"=>xyz,
                    "Float32_contact_ids"=>ids32,"Float64_contact_ids"=>ids64))
            end
            push!(rows,Dict("ordinal"=>example["ordinal"],"event_id"=>example["group"]["event_id"],"contact_rows"=>contacts))
        end
        G.save(args[3],Dict("kind"=>"gegi_retained_contact_start_census_v1","model_sha256"=>req["model_sha256"],
            "groups"=>length(rows),"groups_with_Float64_contact"=>count(r->any(c->!isempty(c["Float64_contact_ids"]),r["contact_rows"]),rows),
            "Float32_contact_rows"=>sum(length(r["contact_rows"]) for r in rows),
            "Float64_contact_rows"=>sum(count(c->!isempty(c["Float64_contact_ids"]),r["contact_rows"]) for r in rows),"results"=>rows))
        return
    end
    field=G.pinned_input(req["field_cache"],"ref","sha256");sim=deserialize(field)
    println("Loaded existing cache, precision ",8sizeof(SSD.get_precision_type(sim)));flush(stdout)
    if promote
        sim=G.promote_cached_drift(sim);GC.gc()
        println("Losslessly promoted cached samples; Float64 native drift");flush(stdout)
    end
    if "--native-groups" in flags
        out=args[3]*"-native";ispath(out) && error("Use a new native derivative output")
        mkpath(out);rows=Any[];channels=G.H.channel_metadata(sim.config_dict)
        started=time()
        for example in G.E.readjson(args[2])
            group=example["group"];stem=string(example["ordinal"])
            working=Dict("event_id"=>group["event_id"],"primary_time_ns"=>group["group_origin_time_ns"],"steps"=>group["steps"])
            path=joinpath(out,stem*"-signals.csv")
            event=try
                G.process_event(working,sim,cfg,channels,nothing,nothing,nothing,nothing,nothing,path;native_only=true)
            catch err
                err isa G.NativeResponseError || rethrow()
                Dict("status"=>"native_failed","native_domain_error"=>err.domain_error,"native_failure_diagnostic"=>err.diagnostic,
                    "signals_ref"=>nothing,"signals_sha256"=>nothing)
            end
            event["input_group"]=group;G.save(joinpath(out,stem*".json"),jsonsafe(event))
            push!(rows,Dict("ordinal"=>example["ordinal"],"event_id"=>group["event_id"],"old_status"=>example["old_status"],
                "status"=>event["status"],"native_domain_error"=>get(event,"native_domain_error",nothing),
                "transport_flags"=>get(event,"transport_flags",nothing),"event_ref"=>joinpath(out,stem*".json"),
                "signals_sha256"=>get(event,"signals_sha256",nothing)))
            println("Native group ",example["ordinal"],": ",event["status"]);flush(stdout)
            G.save(args[3],Dict("kind"=>"gegi_targeted_native_replay_v1","field_sha256"=>req["field_cache"]["sha256"],
                "source_sha256"=>G.hashfile(@__FILE__),"drift_precision_bits"=>8sizeof(SSD.get_precision_type(sim)),
                "analytic_semiconductor_boundary"=>analytic,"drift_dt_ns"=>cfg.dt,"max_steps"=>cfg.max_steps,
                "elapsed_seconds"=>time()-started,"results"=>rows))
        end
        return
    end
    model64=SSD.Simulation{Float64}(G.pinned_input(req,"model_ref","model_sha256"))
    analytic && G.NativeBoundaryGuard.install!(;analytic_semiconductor=true)
    results=Any[]
    for example in G.E.readjson(args[2])
        group=example["group"];rows=Any[]
        case_cfg=cfg
        if haskey(example,"drift_cap_ns")
            "--drift-only" in flags || error("Per-case drift caps are only numerical point diagnoses")
            case_req=deepcopy(req);case_req["numerics"]["drift_cap_ns"]=example["drift_cap_ns"]
            case_cfg=merge(G.numerics(case_req),(analytic_boundary=analytic,))
        end
        for step in group["steps"]
            selected=get(example,"selected_raw_rows",nothing)
            selected===nothing || step["raw_row_index"] in selected || continue
            row=diagnose_deposit(sim,step,case_cfg;drift_only="--drift-only" in flags)
            p64=SSD.CartesianPoint{Float64}((Float64.(step["position_mm"])./1000)...)
            row["Float64_start_contact_ids"]=[c.id for c in model64.detector.contacts if p64 in c.geometry]
            push!(rows,row)
            println("Ordinal ",example["ordinal"],", raw row ",step["raw_row_index"],": ",row["status"]);flush(stdout)
            if !("--drift-only" in flags) && !promote && example["old_status"]=="native_failed"
                row["status"] in ("contact_start","outside_endpoint","invalid_signed_charge") && break
            elseif !("--drift-only" in flags) && !promote && row["status"]==example["old_status"]
                break
            end
        end
        push!(results,Dict("ordinal"=>example["ordinal"],"event_id"=>group["event_id"],
            "old_status"=>example["old_status"],"old_domain_error"=>example["old_domain_error"],
            "diagnostic_group_json_sha256"=>bytes2hex(sha256(JSON.json(group))),
            "requested_drift_cap_ns"=>get(example,"drift_cap_ns",get(req["numerics"],"drift_cap_ns",1000.0)),
            "drift_dt_ns"=>case_cfg.dt,"max_steps"=>case_cfg.max_steps,
            "configured_native_support_ns"=>case_cfg.max_steps*case_cfg.dt,"deposits"=>rows))
        G.save(args[3],jsonsafe(Dict("kind"=>"gegi_retained_native_diagnosis_v1","field_sha256"=>req["field_cache"]["sha256"],
            "native_source_sha256"=>bytes2hex(sha256(read(joinpath(dirname(pathof(SSD)),"ChargeDrift","ChargeDrift.jl")))),
            "source_sha256"=>G.hashfile(@__FILE__),"drift_precision_bits"=>8sizeof(SSD.get_precision_type(sim)),
            "response_source_code_sha256"=>Dict(name=>G.hashfile(joinpath(G.ROOT,"simulation",name)) for name in G.SOURCES),
            "request_sha256"=>G.hashfile(args[1]),"inputs_sha256"=>G.hashfile(args[2]),
            "analytic_semiconductor_boundary"=>analytic,"drift_only"=>"--drift-only" in flags,
            "drift_dt_ns"=>cfg.dt,"baseline_max_steps"=>cfg.max_steps,"baseline_native_support_ns"=>cfg.max_steps*cfg.dt,
            "max_configured_native_support_ns"=>maximum([cfg.max_steps*cfg.dt;[r["configured_native_support_ns"] for r in results]]),
            "scope"=>"Per-deposit numerical diagnosis only; not full-group charge availability or shared readout recovery.","results"=>results)))
    end
end
if abspath(PROGRAM_FILE)==@__FILE__
    main()
end
