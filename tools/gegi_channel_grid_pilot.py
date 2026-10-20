"""Fixed contacts17/20 on the existing level16 grid; shared native CPU helpers.

Executed only through gegi_guard_grid_pilot.py with an exact request SHA.
Importing this module prepares source text and performs no Julia calculation.
"""
from gegi_guard_grid_pilot import JULIA_HELPERS

JULIA_WORKER = JULIA_HELPERS + r'''
function main(reqpath,out)
    req=JSON.parsefile(reqpath);ids=req["contact_ids"]
    check(Threads.nthreads()==1 && ids==[17,20],"Fixed contacts17/20 and one thread only")
    check(length(req["levels"])==1 && only(req["levels"])["central_subdivisions"]==16,"Fixed level16 only")
    check([r["raw_row_index"] for r in req["path_rows"]]==[10191,10186,10185],"Fixed original three rows only")
    pkgroot=dirname(dirname(pathof(SSD)))
    for (ref,digest) in req["SSD_science_source_sha256"]
        check(hashfile(joinpath(pkgroot,"src",ref))==digest,"Installed science source changed")
    end
    cache=req["field_cache"]["absolute_ref"]
    check(hashfile(cache)==req["field_cache"]["sha256"],"Original cache changed")
    stage(out,"deserialize_original_cache",0);sim=deserialize(cache)
    check(SSD.get_precision_type(sim)==Float32 && SSD.get_coordinate_system(sim)==SSD.Cartesian,"Original state type changed")
    check(sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel,"Original no-trapping model changed")
    originals=copy(sim.weighting_potentials)
    fields(s)=(s.electric_potential,s.electric_field,s.point_types,s.imp_scale,s.q_eff_imp,s.q_eff_fix,s.ϵ_r)
    old_fields=fields(sim);recorded=Dict();baseline=Dict(string(cid)=>Dict() for cid in ids)
    # Only these six original-channel baselines are reconstructed, before either solve.
    for row in req["path_rows"]
        key=string(row["raw_row_index"]);recorded[key]=deserialize(row["paths_jls"])
        check(recorded[key].field_cache_sha256==req["field_cache"]["sha256"],"Original path-cache binding changed")
        for cid in ids
            native=JSON.parsefile(row["original_channel_json"][string(cid)])
            q=waveform(sim,recorded[key],cid)
            check(bits_equal(q,Float64.(native["signed_induced_keV"])),"Original selected-channel baseline not bitexact")
            baseline[string(cid)][key]=Dict("original_all_samples_bitexact"=>true,"time_ns"=>native["time_ns"],
                "waveform_keV"=>q,"potentials"=>path_values(sim,originals[cid],recorded[key];phi_key="phi"))
        end
    end
    save(joinpath(out,"baseline.json"),baseline);level=only(req["levels"]);completed=Any[]
    for cid in ids
        dir=joinpath(out,"channel-"*string(cid));mkdir(dir);original=originals[cid]
        check(size(original.data)==(240,240,88),"Original selected-channel grid changed")
        axes=level["axes_ticks_m"]
        check(Float32.(axes[3])==original.grid.axes[3].ticks,"Z refinement forbidden")
        for k in 1:3
            ticks=Float32.(axes[k])
            check(bytes2hex(sha256(reinterpret(UInt8,ticks)))==level["axis_float32_le_sha256"][k],"Axis hash changed")
            check(all(t->t in ticks,original.grid.axes[k].ticks),"Original ticks removed")
        end
        grid=SSD.CartesianGrid3D{Float32}((axis_copy(original.grid.axes[1],axes[1]),axis_copy(original.grid.axes[2],axes[2]),original.grid.axes[3]))
        SSD.check_grid(grid)
        check(prod(size(grid))<=7_000_000 && collect(size(grid))==level["shape"],"Fixed grid shape or node cap changed")
        check(grid_digest(axes)==level["grid_float32_le_sha256"],"Fixed grid hash changed")
        save(joinpath(dir,"grid.json"),level);stage(out,"resample_original_selected_WP",cid)
        sim.weighting_potentials[cid]=original[grid]
        serialize(joinpath(dir,"starting-WP"*string(cid)*".jls"),sim.weighting_potentials[cid])
        history=joinpath(dir,"update-history.jsonl");terminal=joinpath(dir,"terminal-WP"*string(cid)*".jls")
        stage(out,"CPU_solve_selected_WP",cid);started=time_ns()
        last_update=Inf32;iterations=0;stop_reason="unexpected_exception";native_update=Inf32;solve_seconds=nothing
        try
            last_update,iterations,stop_reason,native_update=update_native_history!(sim,history,
                parse(Float64,ENV["GEGI_WP34_DEADLINE_UNIX"]);contact_id=cid,budget_seconds=600)
            solve_seconds=(time_ns()-started)/1e9
        finally
            # Shared helper copies back the current PCS even on an iteration exception.
            serialize(terminal,sim.weighting_potentials[cid])
        end
        elapsed=(time_ns()-started)/1e9
        accepted=isfinite(last_update) && last_update<=1f-6
        receipt=Dict("contact_id"=>cid,"last_update"=>isfinite(last_update) ? Float64(last_update) : nothing,
            "last_update_raw"=>string(last_update),"last_update_gate_passed"=>accepted,"solve_seconds"=>solve_seconds,
            "solve_and_terminal_save_seconds"=>elapsed,
            "iterations_performed"=>iterations,"max_n_iterations"=>10000,"stop_reason"=>stop_reason,
            "native_half1_last_update"=>isfinite(native_update) ? Float64(native_update) : nothing,
            "absolute_full_max_limit"=>1e-6,"update_history_sha256"=>hashfile(history),
            "terminal_WP_sha256"=>hashfile(terminal),"initial_state"=>"Original own-contact WP independently resampled on fixed level16 grid",
            "scope"=>"Absolute native update diagnostic only; not global grid/PDE/detector validation")
        save(joinpath(dir,"solver.json"),receipt);rows=Dict()
        for row in req["path_rows"]
            key=string(row["raw_row_index"]);base=baseline[string(cid)][key];q=waveform(sim,recorded[key],cid)
            check(length(q)==length(base["waveform_keV"]),"Original waveform sample grid changed")
            rows[key]=Dict("contact_id"=>cid,"original_all_samples_bitexact"=>true,"time_ns"=>base["time_ns"],
                "signed_induced_keV"=>q,"minus_original_keV"=>q-base["waveform_keV"],
                "potentials"=>path_values(sim,sim.weighting_potentials[cid],recorded[key];phi_key="phi"))
        end
        save(joinpath(dir,"path-waveforms.json"),rows)
        check(all(a===b for (a,b) in zip(fields(sim),old_fields)) &&
            all(sim.weighting_potentials[i]===originals[i] for i in 1:34 if !(i in ids)),"Unrelated native field object changed")
        save(joinpath(dir,"COMPLETE.json"),Dict("status"=>accepted ? "completed_local_selected_WP_channel" : "unconverged_local_selected_WP_channel",
            "contact_id"=>cid,"solver"=>receipt,"terminal_WP_sha256"=>hashfile(terminal),
            "path_waveforms_sha256"=>hashfile(joinpath(dir,"path-waveforms.json"))))
        check(accepted,"Selected WP exceeded fixed absolute update gate; preserve terminal and stop without another solve")
        push!(completed,receipt);stage(out,"channel_completed",cid);GC.gc()
    end
    check(hashfile(cache)==req["field_cache"]["sha256"],"Original cache bytes changed")
    save(joinpath(out,"COMPLETE.json"),Dict("status"=>"completed_local_contacts17_20_level16_pilot","channels"=>completed,
        "request_sha256"=>hashfile(reqpath),"baseline_original_bitexact_waveforms"=>6,"global_validation"=>false,
        "new_drift_calls"=>0,"new_EP_or_Efield_solves"=>0,"new_calibration_calls"=>0))
end
check(length(ARGS)==2,"Pass bound request and new output root")
try
    main(ARGS[1],ARGS[2])
catch err
    save(joinpath(ARGS[2],"failure.json"),Dict("status"=>"failed_stop","error"=>sprint(showerror,err),"automatic_retry"=>false))
    rethrow()
end
'''
