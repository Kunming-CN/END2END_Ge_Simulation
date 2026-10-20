# Include after gegi_response.jl. This module never loads/solves fields itself.
module GeGIPixelCalibration
using ..GeGIResponse
using JSON, SHA, Statistics
const G=GeGIResponse
const H=G.H
const SSD=G.SSD
const check=G.check
const TIMING_METHOD="ideal_charge_last_rising_constant_fraction_terminal_v2"
const SIGNAL_CONTACT_IDS=1:34
signal_coverage()=Dict("kind"=>"gegi_all34_signed_induced_v1",
    "contact_ids"=>collect(SIGNAL_CONTACT_IDS),"time_unit"=>"ns","signal_unit"=>"keV",
    "polarity"=>"native_signed_before_wiring")
const DEPTHS=collect(-5.0:1.0:5.0)
# Fixed before campaign data are read: centre, four axial edges and two cut corners.
const DIAGNOSTIC_PIXELS=((9,26),(1,26),(16,26),(9,18),(9,33),(3,20),(14,31))
const DIAGNOSTIC_DEPTHS=(-4.5,-2.5,0.0,2.5,4.5)
const DIAGNOSTIC_OFFSETS=(("centre",0.,0.),("x_minus",-0.25,0.),
    ("x_plus",0.25,0.),("y_minus",0.,-0.25),("y_plus",0.,0.25))

"""Stable JSON for checkpoint checksums, independent of dictionary iteration."""
function canonical(value)
    if value isa AbstractDict
        keys_sorted=sort!(collect(keys(value)))
        return "{"*join((JSON.json(k)*":"*canonical(value[k]) for k in keys_sorted),",")*"}"
    elseif value isa AbstractVector || value isa Tuple
        return "["*join(canonical.(value),",")*"]"
    end
    JSON.json(value)
end
digest(value)=bytes2hex(sha256(canonical(value)))

function source_hashes()
    names=unique([collect(G.SOURCES);"gegi_pixel_calibration.jl";"Project.toml";"Manifest.toml"])
    Dict(name=>G.hashfile(joinpath(@__DIR__,name)) for name in names)
end

function output_identity(out,identity)
    out=abspath(out)
    if ispath(out)
        check(isdir(out) && G.Q.childof(realpath(out),realpath(joinpath(G.ROOT,".local"))),
            "Calibration output must remain below project .local")
        path=joinpath(out,"identity.json")
        check(isfile(path) && G.E.readjson(path)==identity,
            "Calibration identity changed or destination is not an owned calibration")
    else
        G.Q.validate_output(out)
        mkpath(out)
        G.save(joinpath(out,"identity.json"),identity)
    end
    out,G.hashfile(joinpath(out,"identity.json"))
end

function save_record(path,payload,identity_sha256)
    mkpath(dirname(path))
    G.save(path,Dict("kind"=>"gegi_independent_injection_checkpoint_v1",
        "identity_sha256"=>identity_sha256,"payload_sha256"=>digest(payload),"payload"=>payload))
end

function read_record(path,identity_sha256)
    record=G.E.readjson(path)
    check(record["kind"]=="gegi_independent_injection_checkpoint_v1" &&
        record["identity_sha256"]==identity_sha256 && digest(record["payload"])==record["payload_sha256"],
        "Independent injection checkpoint changed: "*path)
    record["payload"]
end

function injection(sim,cfg,xid,yid,xyz,energy)
    T=SSD.get_precision_type(sim)
    point=SSD.CartesianPoint{T}((T.(xyz)./T(1000))...)
    row=Dict{String,Any}("position_mm"=>xyz,"contact_ids"=>[xid,yid],
        "injection_energy_keV"=>energy,"valid"=>false,"ctd_ns"=>nothing,
        "X_t50_ns"=>nothing,"Y_t50_ns"=>nothing,"endpoints"=>nothing,
        "X_final_induced_keV"=>nothing,"Y_final_induced_keV"=>nothing,
        "timing_method"=>TIMING_METHOD,"signals"=>nothing,
        "channel_signals"=>nothing,"signal_coverage"=>nothing)
    if !(point in sim.detector.semiconductor) || any(c->point in c.geometry,sim.detector.contacts)
        row["status"]="excluded_geometry"
        return row
    end
    waves,endpoints=G.native_deposit(sim,xyz,energy,cfg;ids=SIGNAL_CONTACT_IDS)
    check(Set(keys(waves))==Set(SIGNAL_CONTACT_IDS),"Incomplete GeGI 34-contact native response")
    tx=H.crossing_time(waves[xid].times,waves[xid].charge)
    ty=H.crossing_time(waves[yid].times,-waves[yid].charge)
    # With the frozen negative-X bias, holes collect on X and electrons on Y.
    complete=length(endpoints)==2 && all(e->!e["step_limit_reached"],endpoints) &&
        any(e->e["species"]=="hole" && e["contact_ids"]==[xid],endpoints) &&
        any(e->e["species"]=="electron" && e["contact_ids"]==[yid],endpoints)
    xfinal=last(waves[xid].charge);yfinal=last(waves[yid].charge)
    valid=complete && tx!==nothing && ty!==nothing && xfinal>0 && yfinal<0
    merge!(row,Dict("status"=>valid ? "completed" : "incomplete_collection_or_timing",
        "valid"=>valid,"ctd_ns"=>valid ? tx-ty : nothing,
        "X_t50_ns"=>tx,"Y_t50_ns"=>ty,"endpoints"=>endpoints,
        "X_final_induced_keV"=>xfinal,"Y_final_induced_keV"=>yfinal,
        "signal_coverage"=>signal_coverage(),
        "channel_signals"=>[Dict("contact_id"=>id,"time_ns"=>waves[id].times,
            "signed_induced_keV"=>waves[id].charge) for id in SIGNAL_CONTACT_IDS],
        "signals"=>Dict("X"=>Dict("time_ns"=>waves[xid].times,"signed_induced_keV"=>waves[xid].charge),
                        "Y"=>Dict("time_ns"=>waves[yid].times,"signed_induced_keV"=>waves[yid].charge))))
    row
end

function checkpoint_injection(sim,cfg,xid,yid,xyz,energy,path,identity_sha256)
    if isfile(path)
        row=read_record(path,identity_sha256)
        check(row["position_mm"]==xyz && row["contact_ids"]==[xid,yid] &&
            row["injection_energy_keV"]==energy,"Independent injection coordinates changed")
        check(row["status"]!="unexpected_failure","Prior unexpected injection failure retained at "*path)
        check(haskey(row,"channel_signals") && haskey(row,"signal_coverage"),
            "Checkpoint lacks full34 coverage metadata; retain the selected-X/Y original and use a new calibration directory")
        if row["signals"]===nothing
            check(row["channel_signals"]===nothing && row["signal_coverage"]===nothing,
                "Unavailable injection must retain null channel signals and coverage")
        else
            check(row["signal_coverage"]==signal_coverage() && row["channel_signals"] isa AbstractVector &&
                [s["contact_id"] for s in row["channel_signals"]]==collect(SIGNAL_CONTACT_IDS),
                "Checkpoint does not contain the full34 signed native response")
        end
        return row,true
    end
    started=time();rss_before=Sys.maxrss()
    row=try
        injection(sim,cfg,xid,yid,xyz,energy)
    catch err
        known=err isa ArgumentError && err.msg in ("Noncontact endpoint outside crystal","Invalid waveform support")
        failure=Dict("position_mm"=>xyz,"contact_ids"=>[xid,yid],"injection_energy_keV"=>energy,
            "status"=>known ? "native_failed" : "unexpected_failure","valid"=>false,
            "ctd_ns"=>nothing,"X_t50_ns"=>nothing,"Y_t50_ns"=>nothing,"endpoints"=>nothing,
            "X_final_induced_keV"=>nothing,"Y_final_induced_keV"=>nothing,"signals"=>nothing,
            "channel_signals"=>nothing,"signal_coverage"=>nothing,
            "timing_method"=>TIMING_METHOD,"error"=>sprint(showerror,err),"exception_type"=>string(typeof(err)),
            "execution_seconds"=>time()-started,"process_peak_rss_bytes_before"=>rss_before,
            "process_peak_rss_bytes_after"=>Sys.maxrss())
        save_record(path,failure,identity_sha256)
        known || rethrow()
        return failure,false
    end
    row["execution_seconds"]=time()-started
    row["process_peak_rss_bytes_before"]=rss_before
    row["process_peak_rss_bytes_after"]=Sys.maxrss()
    row["memory_measurement_scope"]="Process lifetime peak RSS, including loaded fields; not incremental allocation per injection."
    save_record(path,row,identity_sha256)
    row,false
end

function depth_from_timing(delta,table)
    H.finite(delta) || return nothing
    get(table,"status",nothing)=="available_model_approximation" || return nothing
    depths=table["depth_mm"];times=table["ctd_ns"]
    H.monotonic_depth_table(depths,times) || return nothing
    pairs=sort!(collect(zip(times,depths));by=first)
    first(pairs)[1]<=delta<=last(pairs)[1] || return nothing
    for ((t0,z0),(t1,z1)) in zip(pairs,pairs[2:end])
        t0<=delta<=t1 && return z0+(z1-z0)*(delta-t0)/(t1-t0)
    end
    nothing
end

function compact_row(row,ref)
    Dict("record_ref"=>ref,"z_mm"=>row["position_mm"][3],"status"=>row["status"],
        "valid"=>row["valid"],"ctd_ns"=>row["ctd_ns"],"X_t50_ns"=>row["X_t50_ns"],
        "Y_t50_ns"=>row["Y_t50_ns"],"X_final_induced_keV"=>row["X_final_induced_keV"],
        "Y_final_induced_keV"=>row["Y_final_induced_keV"])
end

function residual_summary(rows,key)
    values=Float64[r[key] for r in rows if get(r,key,nothing)!==nothing]
    isempty(values) && return Dict("count"=>0,"mean_mm"=>nothing,"median_absolute_mm"=>nothing,
        "min_mm"=>nothing,"max_mm"=>nothing,"max_absolute_mm"=>nothing)
    Dict("count"=>length(values),"mean_mm"=>mean(values),"median_absolute_mm"=>median(abs.(values)),
        "min_mm"=>minimum(values),"max_mm"=>maximum(values),"max_absolute_mm"=>maximum(abs.(values)))
end

"""
    build(sim, cfg, channels, out; field_cache, injection_energy_keV=500., stop_requested=()->false, max_new_injections=nothing)

Build a source-independent 16 x 16 pixel-centre timing map using already loaded
fields and GeGIResponse.native_deposit. `field_cache` is the exact checked cache
descriptor (`ref`, `sha256`, `model_sha256`) used to load `sim`; it is read-only.
No field solve, event data, source pose or campaign seed is used. Each successful
native response has a checksum-bound resumable record containing all 34 signed
contact signals/endpoints from one drift. `signals.X/Y` and timing retain the
selected pair; `channel_signals` stores explicit contact IDs, ns and signed keV
before wiring. Excluded/failed responses keep signals and actual coverage null.
Identity/table coverage declares the requested recording scope. Old selected-X/Y
records remain read-only originals; they cannot resume into this full34 writer.

Returns `(status, calibration, calibration_path, diagnostics_path)`. On a requested
stop, calibration is nothing; calling again with identical inputs resumes records.
The directory must be a new or matching owned directory under project .local.
`max_new_injections` bounds a measured pilot and is intentionally not part of the
physics identity. Budget exhaustion returns partial, never an accepted map. The
central pixel runs first; the same checkpoints resume into the full fixed map.
This API does not acquire the parent's supervisor lock: only one writer may call
it for a given directory. No existing central calibration is read or overwritten.
"""
function build(sim,cfg,channels,out;field_cache,injection_energy_keV=500.,stop_requested=()->false,max_new_injections=nothing)
    check(H.finite(injection_energy_keV) && injection_energy_keV>0,"Invalid independent injection energy")
    check(max_new_injections===nothing || (G.E.integer(max_new_injections) && max_new_injections>0),"Invalid calibration pilot bound")
    check(field_cache["model_sha256"]==G.MODEL_HASH,"Wrong GeGI field cache model")
    G.pinned_input(field_cache,"ref","sha256")
    check(G.hashfile(joinpath(G.ROOT,"models","GeGI_3D.yaml"))==G.MODEL_HASH,"Canonical GeGI model changed")
    check(channels==H.channel_metadata(sim.config_dict),"Calibration channel metadata changed")
    check(length(sim.weighting_potentials)>=34 && all(!ismissing(sim.weighting_potentials[i]) for i in 1:34),
        "Pixel calibration requires all frozen weighting potentials")
    check(!ismissing(sim.electric_field),"Pixel calibration requires the previously loaded native field")
    sources=source_hashes()
    pixel_order=[(9,26);[(x,y) for x in 1:16 for y in 18:33 if (x,y)!=(9,26)]]
    identity=Dict("kind"=>"gegi_pixel_calibration_identity_v1","model_sha256"=>G.MODEL_HASH,
        "field_cache"=>Dict(k=>field_cache[k] for k in ("ref","sha256","model_sha256")),
        "source_sha256"=>sources,"environment"=>G.E.environment(),"channels"=>channels,
        "numerics"=>Dict(string(k)=>getproperty(cfg,k) for k in propertynames(cfg)),
        "field_precision_bits"=>8sizeof(SSD.get_precision_type(sim)),"depth_mm"=>DEPTHS,
        "pixel_order"=>[collect(p) for p in pixel_order],
        "injection_energy_keV"=>Float64(injection_energy_keV),"timing_method"=>TIMING_METHOD,
        "signal_coverage"=>signal_coverage(),
        "diagnostic_pixels"=>[collect(p) for p in DIAGNOSTIC_PIXELS],
        "diagnostic_depth_mm"=>collect(DIAGNOSTIC_DEPTHS),
        "diagnostic_offsets_pitch_fraction"=>[collect(p) for p in DIAGNOSTIC_OFFSETS],
        "random_seed"=>nothing,"randomness"=>"Deterministic fixed independent injections; no random draws")
    out,identity_sha256=output_identity(out,identity)
    report=Dict{String,Any}("kind"=>"gegi_pixel_calibration_run_v1","identity_sha256"=>identity_sha256,
        "status"=>"running","completed_pixels"=>0,"new_injections"=>0,"reused_injections"=>0,
        "diagnostic_records"=>0)
    started=time()
    pixels=Dict{String,Any}();diagnostics=Any[]
    function run_injection(xid,yid,xyz,ref)
        row,reused=checkpoint_injection(sim,cfg,xid,yid,xyz,Float64(injection_energy_keV),joinpath(out,ref),identity_sha256)
        report[reused ? "reused_injections" : "new_injections"]+=1
        row
    end
    function stopped()
        if stop_requested()===true
            report["status"]="stopped"
            return true
        end
        if max_new_injections!==nothing && report["new_injections"]>=max_new_injections
            report["status"]="partial"
            return true
        end
        false
    end
    try
        G.save(joinpath(out,"run.json"),report)
        for (xid,yid) in pixel_order
            rows=Any[];ctd=Any[];x=channels[xid]["strip_center_mm"];y=channels[yid]["strip_center_mm"]
            for (zi,z) in enumerate(DEPTHS)
                stopped() && return (status=report["status"],calibration=nothing,calibration_path=nothing,diagnostics_path=nothing)
                ref="injections/$(xid)-$(yid)/z$(zi).json"
                row=run_injection(xid,yid,[x,y,z],ref)
                push!(ctd,row["ctd_ns"]);push!(rows,compact_row(row,ref))
            end
            valid=all(r->r["valid"],rows) && H.monotonic_depth_table(DEPTHS,ctd)
            pixels["$(xid):$(yid)"]=Dict("contact_ids"=>[xid,yid],"x_mm"=>x,"y_mm"=>y,
                "depth_mm"=>DEPTHS,"ctd_ns"=>ctd,"rows"=>rows,"timing_method"=>TIMING_METHOD,
                "status"=>valid ? "available_model_approximation" : "unavailable_nonmonotonic_incomplete_or_geometry")
            report["completed_pixels"]+=1
            G.save(joinpath(out,"run.json"),report)
        end
        pitchx=channels[10]["strip_center_mm"]-channels[9]["strip_center_mm"]
        pitchy=channels[27]["strip_center_mm"]-channels[26]["strip_center_mm"]
        check(pitchx>0 && pitchy>0,"Invalid strip pitch for independent diagnostics")
        central=pixels["9:26"]
        for (xid,yid) in DIAGNOSTIC_PIXELS,(label,dx,dy) in DIAGNOSTIC_OFFSETS,(zi,z) in enumerate(DIAGNOSTIC_DEPTHS)
            stopped() && return (status=report["status"],calibration=nothing,calibration_path=nothing,diagnostics_path=nothing)
            xyz=[channels[xid]["strip_center_mm"]+dx*pitchx,channels[yid]["strip_center_mm"]+dy*pitchy,z]
            ref="diagnostic-injections/$(xid)-$(yid)/$(label)-z$(zi).json"
            row=run_injection(xid,yid,xyz,ref)
            localz=row["valid"] ? depth_from_timing(row["ctd_ns"],pixels["$(xid):$(yid)"]) : nothing
            centralz=row["valid"] ? depth_from_timing(row["ctd_ns"],central) : nothing
            push!(diagnostics,Dict("record_ref"=>ref,"contact_ids"=>[xid,yid],"position_mm"=>xyz,
                "lateral_offset_label"=>label,"status"=>row["status"],"ctd_ns"=>row["ctd_ns"],
                "pixel_inferred_z_mm"=>localz,"central_inferred_z_mm"=>centralz,
                "pixel_residual_mm"=>localz===nothing ? nothing : localz-z,
                "central_residual_mm"=>centralz===nothing ? nothing : centralz-z))
            report["diagnostic_records"]+=1
        end
        check(source_hashes()==sources,"Calibration source changed during execution")
        table=Dict("kind"=>"gegi_pixel_simulated_depth_v1","per_pixel_calibration"=>true,
            "model_sha256"=>G.MODEL_HASH,"field_cache_sha256"=>field_cache["sha256"],
            "drift_numerics"=>identity["numerics"],"calibration_source_sha256"=>sources,
            "measured_calibration"=>false,"timing_method"=>TIMING_METHOD,"pixels"=>pixels,
            "signal_coverage"=>signal_coverage(),
            "identity_sha256"=>identity_sha256,"injection_energy_keV"=>Float64(injection_energy_keV),
            "depth_mm"=>DEPTHS,"method"=>"Independent fixed pixel-centre injections; CTD=t50_X-t50_Y; last rising 50% of terminal polarity-corrected induced charge",
            "limitations"=>["Pixel-centre simulated calibration, not hardware calibration or a depth-resolution measurement.",
                "Fixed existing native fields; no new solve or convergence claim.",
                "No depth extrapolation beyond -5..5 mm and no fallback from missing/unavailable pixels.",
                "Within-pixel offsets are independent diagnostics, not event corrections or uncertainty bounds.",
                "No diffusion, self-repulsion, measured timing noise, crosstalk or real timing circuit.",
                "Multiple interactions sharing a strip can distort aggregate timing and are not resolved by this map."])
        diagnostic=Dict("kind"=>"gegi_pixel_depth_diagnostics_v1","identity_sha256"=>identity_sha256,
            "rows"=>diagnostics,"total_fixed_injections"=>length(diagnostics),
            "pixel_residuals"=>residual_summary(diagnostics,"pixel_residual_mm"),
            "central_residuals"=>residual_summary(diagnostics,"central_residual_mm"),
            "scope"=>"Fixed independent injections only; no campaign truth used for fitting or selection. Residuals are a finite deterministic diagnostic, not resolution or a global error bound.")
        calibration_path=joinpath(out,"depth-calibration.json");diagnostics_path=joinpath(out,"depth-diagnostics.json")
        G.save(calibration_path,table);G.save(diagnostics_path,diagnostic)
        report["artifacts"]=Dict("depth-calibration.json"=>G.hashfile(calibration_path),
            "depth-diagnostics.json"=>G.hashfile(diagnostics_path),"identity.json"=>identity_sha256)
        report["available_pixels"]=count(p->p["status"]=="available_model_approximation",values(pixels))
        report["unavailable_pixels"]=length(pixels)-report["available_pixels"]
        report["status"]="completed"
        return (status="completed",calibration=table,calibration_path=calibration_path,diagnostics_path=diagnostics_path)
    catch err
        report["status"]="failed";report["error"]=sprint(showerror,err)
        rethrow()
    finally
        report["elapsed_seconds_this_call"]=time()-started
        report["process_peak_rss_bytes"]=Sys.maxrss()
        G.save(joinpath(out,"run.json"),report)
    end
end
end
