# Capture an explicitly specified set of deterministic all34 point responses.
using JSON, LinearAlgebra
include(joinpath(@__DIR__,"..","simulation","gegi_response.jl"))
include(joinpath(@__DIR__,"..","simulation","gegi_pixel_calibration.jl"))
const G=GeGIResponse; const K=GeGIPixelCalibration; const SSD=G.SSD
const check=G.check
BLAS.set_num_threads(1)

function main(reqpath,out)
    req=G.E.readjson(reqpath); requestsha=G.hashfile(reqpath)
    check(Threads.nthreads()==1,"Point response capture uses one Julia thread")
    for (ref,digest) in req["source_file_sha256"]
        check(G.hashfile(joinpath(G.ROOT,ref))==digest,"Point response producer changed: "*ref)
    end
    check(G.E.environment()==req["environment"]["native"],"Native environment changed")
    pkgroot=dirname(dirname(pathof(SSD)))
    for (ref,digest) in req["environment"]["SSD_science_source_sha256"]
        check(G.hashfile(joinpath(pkgroot,"src",ref))==digest,"Installed SSD source changed: "*ref)
    end
    cfg=(; (Symbol(k)=>v for (k,v) in req["numerics"])...)
    report=Dict{String,Any}(); started=time()
    sim=G.load_fields(req,joinpath(G.ROOT,req["model_ref"]),out,cfg,report)
    check(report["fields"]["solve_seconds"]==0 &&
        8sizeof(SSD.get_precision_type(sim))==req["field_precision_bits"],"Unexpected field solve or precision")
    check(G.H.channel_metadata(sim.config_dict)==req["channels"],"Contact metadata changed")
    identity=Dict("kind"=>"gegi_declared_point_response_identity_v1",
        "request_sha256"=>requestsha,"point_plan_sha256"=>req["point_plan_sha256"],
        "plan_receipt"=>req["plan_receipt"],"baseline_request"=>req["baseline_request"],
        "model_sha256"=>req["model_sha256"],"field_cache"=>req["field_cache"],
        "field_precision_bits"=>req["field_precision_bits"],"numerics"=>req["numerics"],
        "source_file_sha256"=>req["source_file_sha256"],"signal_coverage"=>K.signal_coverage(),
        "random_seed"=>nothing,"randomness"=>"Deterministic independent point drift; no random draws")
    G.save(joinpath(out,"identity.json"),identity); identitysha=G.hashfile(joinpath(out,"identity.json"))
    G.save(joinpath(out,"startup.json"),Dict("field_load_seconds"=>time()-started,
        "fields"=>report["fields"],"native_boundary_policy"=>"unchanged Float32 grid-or-geometry admission; guarded upstream floating projection",
        "process_peak_rss_bytes"=>Sys.maxrss()))
    records=Any[]
    for p in req["points"]
        path=joinpath(out,p["record_ref"])
        check(!ispath(path),"Preserve existing point response: "*path)
        G.save(joinpath(out,"progress.json"),Dict("status"=>"point_running",
            "injection_id"=>p["injection_id"],"completed_points"=>length(records)))
        tick=time()
        row=try
            K.injection(sim,cfg,p["contact_ids"]...,p["position_mm"],req["injection_energy_keV"])
        catch err
            known=err isa G.NativeResponseError ||
                (err isa ArgumentError && err.msg in ("Noncontact endpoint outside crystal","Invalid waveform support"))
            known || rethrow()
            Dict{String,Any}("status"=>"native_failed","valid"=>false,
                "position_mm"=>p["position_mm"],"contact_ids"=>p["contact_ids"],
                "injection_energy_keV"=>req["injection_energy_keV"],"endpoints"=>nothing,
                "signals"=>nothing,"channel_signals"=>nothing,"signal_coverage"=>nothing,
                "error"=>sprint(showerror,err),"exception_type"=>string(typeof(err)),
                "native_failure_diagnostic"=>err isa G.NativeResponseError ? err.diagnostic : nothing)
        end
        merge!(row,Dict("injection_id"=>p["injection_id"],"role"=>p["role"],
            "point_plan_sha256"=>req["point_plan_sha256"],"plan_receipt"=>req["plan_receipt"],
            "request_sha256"=>requestsha,"execution_seconds"=>time()-tick,
            "process_peak_rss_bytes"=>Sys.maxrss()))
        K.save_record(path,row,identitysha)
        check(K.read_record(path,identitysha)==row,"Point checkpoint readback changed")
        push!(records,Dict("injection_id"=>p["injection_id"],"role"=>p["role"],
            "position_mm"=>p["position_mm"],"record_ref"=>p["record_ref"],
            "record_sha256"=>G.hashfile(path),"status"=>row["status"],"valid"=>row["valid"]))
    end
    G.save(joinpath(out,"COMPLETE.json"),Dict("kind"=>"gegi_declared_point_responses_v1",
        "status"=>"completed_declared_points","request_sha256"=>requestsha,
        "identity_sha256"=>identitysha,"point_plan_sha256"=>req["point_plan_sha256"],
        "plan_receipt"=>req["plan_receipt"],"records"=>records,"new_field_solves"=>0,
        "new_transport_calls"=>0,"execution_seconds"=>time()-started,
        "process_peak_rss_bytes"=>Sys.maxrss(),
        "scope"=>"Per-point terminal states and native signed signals; no ADC, trigger, imaging or population requalification"))
end
check(length(ARGS)==2,"Pass request and new output directory")
main(ARGS...)
