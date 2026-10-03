# Electronics-only old6 replay: no SSD/native/radiation module is loaded.
include("readout_profiles.jl")
include("saved_collection_edge.jl")
using JSON, SHA, LinearAlgebra
const E=Readout;const P=ReadoutProfiles;const D=SavedCollectionEdge
const ROOT=dirname(@__DIR__)
function saved_gamma_replay(request,output)
    d=E.readjson(request);E.check(d["kind"]=="old_six_gamma_replay_v1","Old6 replay request")
    E.check(!ispath(output),"New local evidence directory required")
    E.check(VERSION==v"1.13.0" && Threads.nthreads()==1,"Recorded Julia/one thread")
    BLAS.set_num_threads(1)
    for (name,h) in d["pins"];E.check(E.hashfile(joinpath(ROOT,name))==h,"Replay input/source changed: "*name);end
    profile=P.load(joinpath(@__DIR__,"native_readout_profile.json")).profile;c=P.for_census(profile,20);M=E.transition(c,2.)
    output=E.reserve_output(output);results=Any[];started=time()
    for model in ("AK02","SAP22")
        md=d["models"][model];original=E.readjson(joinpath(ROOT,md["calibration_path"]))
        cal=original["calibration"];calstart=time();fresh=P.calibration(c,2.95,2.,M)
        E.check(D.exact_value(cal,fresh),"Original independent calibration semantic identity")
        cal_seconds=time()-calstart
        context_start=time();validated_dt=D.checked_context(c,2.95,cal,M);context_seconds=time()-context_start
        for item in md["events"]
            rec=E.readjson(joinpath(ROOT,item["path"]));wave=rec["charge_input"]
            t=Float64.(wave["time_since_initial_primary_ns"]);q=Float64.(wave["induced_equivalent_energy_keV"])
            rstart=time();replayed=P.process(t,q,c,2.95,cal,M);seconds=time()-rstart
            E.check(D.exact_value(replayed,rec["readout"]),"Old6 full numerical binary64/type/flag/trace parity failed")
            edge=D._collection_edge_trace(t,q,c,2.95,cal,M,validated_dt;stop_ns=item["stop_ns"],max_edge_points=10001)
            parity=D.retained_preamp_parity(edge,rec["readout"]["trace"])
            push!(results,Dict("model_id"=>model,"initial_primary_id"=>rec["initial_primary_id"],"original_sha256"=>item["sha256"],
                "scientific_comparison"=>"all typed values and binary64 bits including signed zero","passed"=>true,
                "processor_seconds"=>seconds,"model_calibration_validation_seconds"=>cal_seconds,
                "model_display_context_validation_seconds"=>context_seconds,"edge_parity"=>parity))
            E.save(joinpath(output,model*"-"*string(rec["initial_primary_id"])*"-edge.json"),edge)
        end
    end
    for (name,h) in d["pins"];E.check(E.hashfile(joinpath(ROOT,name))==h,"Replay changed input/source");end
    E.save(joinpath(output,"PARITY.json"),Dict("kind"=>"old_six_gamma_replay_v1","status"=>"passed","cases"=>results,
        "science_calls"=>Dict("radiation"=>0,"field"=>0,"native"=>0),"calibration_verification_calls"=>4,
        "full_processor_replay_calls"=>6,"replay_seconds"=>time()-started,
        "runtime"=>Dict("julia_version"=>string(VERSION),"threads"=>Threads.nthreads(),"blas_threads"=>BLAS.get_num_threads(),
            "blas_configuration"=>string(BLAS.get_config()),"readout_environment"=>E.environment(),"ssd_loaded"=>false),"pins"=>d["pins"]))
end
if abspath(PROGRAM_FILE)==@__FILE__
    length(ARGS)==4 && ARGS[1]=="--request" && ARGS[3]=="--output" || error("Usage: --request FILE --output NEW_LOCAL_DIR")
    saved_gamma_replay(ARGS[2],ARGS[4])
end
