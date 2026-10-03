# Additive completion of the exact original40 gamma inputs. No field solve/transport.
include("gamma_native_example.jl")
include("saved_collection_edge.jl")
module GammaCompleteExample
using ..GammaNativeExample, ..SavedCollectionEdge, JSON, Unitful
const G=GammaNativeExample;const E=G.E;const P=G.P;const N=G.N;const Q=G.Q;const B=G.B
const KIND="saved_gamma_complete_v1"
const OLD_IDS=Dict("AK02"=>[0,4,5],"SAP22"=>[0,2,3])
const NEW_NATIVE=Dict("AK02"=>[8,11,13,14],"SAP22"=>[8,9,12])
const BASE=joinpath(Q.ROOT,".local","gamma-complete-v1")
check=E.check

function display_stop(t,q)
    variation=abs.(diff(q));total=sum(variation)
    i=total==0 ? min(2,length(t)) : findfirst(>=(0.995total),cumsum(variation))+1
    edge=t[i];stop=2ceil((edge+max(10.,0.2edge))/2)
    min(stop,(length(t)+5000-1)*2.)
end

function validate_request(d)
    check(d["kind"]==KIND && d["schema_version"]===1,"Completion request kind/version")
    model=d["model_id"];check(haskey(OLD_IDS,model),"Completion model")
    profile=P.load(joinpath(@__DIR__,"native_readout_profile.json")).profile
    P.validate_resolved(d["readout_config"],profile,20)
    check(SavedCollectionEdge.exact_value(d["readout_config"],P.for_census(profile,20)),"Rehashed completion config changed beyond census")
    legacy=deepcopy(d);legacy["kind"]=G.KIND;legacy["selected_ids"]=OLD_IDS[model]
    legacy["readout_config"]=P.for_census(profile,3);G.validate_request(legacy)
    check(d["selected_ids"]==collect(0:19) && d["remaining_native_ids"]==NEW_NATIVE[model],"Full original IDs / seven native calls")
    check(sort(parse.(Int,collect(keys(d["reused_records"]))))==OLD_IDS[model],"Old6 reuse census")
    check([e["event_id"] for e in d["events"] if !e["zero_ge"] && !(e["event_id"] in OLD_IDS[model])]==NEW_NATIVE[model],"Remaining native truth census")
    G.canonical_cache(d);G.pins(d);d
end

function reused(d,id,output)
    source=d["reused_records"][string(id)];name=source["path"]
    check(startswith(name,".local/m11c-gamma-native-v1/example/"*d["model_id"]*"/event-"),"Exact original response role")
    check(get(d["pins"],name,nothing)==source["sha256"],"Old response must be externally pinned")
    path=realpath(joinpath(Q.ROOT,name));check(E.hashfile(path)==source["sha256"],"Old response bytes changed")
    target=joinpath(output,"event-"*string(id)*".json")
    check(E.hashfile(target)==source["sha256"],"Reused event copy is not byte exact")
    rec=E.readjson(path);check(rec["initial_primary_id"]===id && rec["event_id"]===id,"Old response identity")
    rec
end

function worker(input,output)
    input=realpath(input);output=realpath(output)
    check(Q.childof(input,realpath(BASE)) && Q.childof(output,realpath(BASE)) && dirname(input)==output,"Owned completion output boundary")
    consumed=G.consumed_request(input);d=validate_request(consumed.document);model=d["model_id"]
    report=Dict{String,Any}("kind"=>KIND,"schema_version"=>1,"status"=>"running","model_id"=>model,
        "request_sha256"=>consumed.sha256,"settings"=>G.SETTINGS,"native_failure_policy"=>d["native_failure_policy"],
        "selected_ids"=>collect(0:19),"radiation_primary_count"=>20,"selected_readout_count"=>20,"cases"=>Any[],
        "calibration_calls"=>0,"native_calls"=>0,"reused_ids"=>OLD_IDS[model],"field_solve_seconds"=>0.0)
    stage="runtime";started=time()
    try
        report["runtime"]=G.runtime();report["runtime"]["completion_worker_source"]=@__FILE__
        check(report["runtime"]["threads"]==d["threads"] && report["runtime"]["executable_sha256"]==d["julia_executable_sha256"],"Recorded runtime")
        stage="saved_cache";sim=G.cache_from_request(d);fingerprint=N.field_fingerprint(sim)
        check(fingerprint==d["expected_field_fingerprint"] && sim.detector.semiconductor.temperature==77,"Saved field fingerprint/temperature")
        contacts=sort([Dict("id"=>c.id,"potential_V"=>c.potential) for c in sim.detector.contacts];by=c->c["id"])
        check(contacts==d["source_manifest"]["stored_contacts"],"Saved contact bias/identity")
        report["field_fingerprint_before"]=fingerprint;report["geometry"]=B.geometry(d["prepared"],sim,true)
        report["detector_settings"]=Dict(k=>d[k] for k in ("source_temperature_K","cached_temperature_K","bias_V","readout_contact_id","cache_sha256","model_sha256"))
        G.R.validate_deposits(Dict("events"=>d["events"]),sim)
        report["guard"]=G.G.install!()
        cfg=Q.parse_args(["--model",model,"--position-mm","3,0,5","--precision","64","--dt-ns","2",
            "--min-grid-mm","0.05","--max-iterations","50000","--contact","1","--output",joinpath(output,"unused")])
        c=d["readout_config"];eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation)
        check(eion==2.95,"Recorded ionisation energy");M=E.transition(c,2.)
        stage="independent_injection";calstart=time();cal=P.calibration(c,eion,2.,M);report["calibration_calls"]=1
        check(SavedCollectionEdge.exact_value(cal,d["expected_calibration"]),"Independent injection changed")
        report["calibration_seconds"]=time()-calstart;report["calibration"]=cal
        report["readout_config"]=c;report["ionisation_energy_eV"]=eion
        validation_start=time();validated_dt=SavedCollectionEdge.checked_context(c,eion,cal,M)
        report["calibration_verification_calls"]=1;report["calibration_verification_seconds"]=time()-validation_start
        stage="remaining_native_and_electronics";display_seconds=0.0
        for id in 0:19
            if id in OLD_IDS[model]
                rec=reused(d,id,output)
            else
                event=d["events"][id+1];native_input=Dict("event_id"=>id,"primary_time_ns"=>0.,"steps"=>event["steps"])
                native_fn=()->begin
                    check(id in NEW_NATIVE[model],"Unplanned native call");G.pins(d);report["native_calls"]+=1
                    Base.invokelatest(N.native_event,native_input,sim,cfg,16,2609261)
                end
                rec=G.event_response(event,d["native_failure_policy"],native_fn,(t,q)->P.process(t,q,c,eion,cal,M),N.flags)
                G.save(joinpath(output,"event-"*string(id)*".json"),rec)
            end
            check(N.field_fingerprint(sim)==fingerprint,"Native call mutated saved fields");G.pins(d);push!(report["cases"],rec)
            if rec["charge_input"]!==nothing
                display_started=time()
                wave=rec["charge_input"];t=Float64.(wave["time_since_initial_primary_ns"]);q=Float64.(wave["induced_equivalent_energy_keV"])
                stop=display_stop(t,q)
                edge=SavedCollectionEdge._collection_edge_trace(t,q,c,eion,cal,M,validated_dt;stop_ns=stop,max_edge_points=10001)
                edge["retained_original_parity"]=SavedCollectionEdge.retained_preamp_parity(edge,rec["readout"]["trace"])
                edge["identity"]=Dict("model_id"=>model,"initial_primary_id"=>id,"group_id"=>rec["zero_ge"] ? nothing : 0)
                edge["case_sha256"]=E.hashfile(joinpath(output,"event-"*string(id)*".json"))
                edge["request_sha256"]=consumed.sha256;edge["original_readout_source_sha256"]=E.hashfile(joinpath(@__DIR__,"readout.jl"))
                edge["runtime"]=Dict("julia_version"=>string(VERSION),"readout_environment"=>E.environment(),"blas_configuration"=>string(G.BLAS.get_config()))
                G.save(joinpath(output,"collection-edge-"*string(id)*".json"),edge)
                display_seconds+=time()-display_started
            end
        end
        G.pins(d);report["field_fingerprint_after"]=N.field_fingerprint(sim)
        check(report["field_fingerprint_after"]==fingerprint && report["native_calls"]==length(NEW_NATIVE[model]),"Final native work/fields")
        failed=count(r->r["status"]=="native_failed",report["cases"]);positive=count(e->!e["zero_ge"],d["events"])
        report["counts"]=Dict("radiation_primaries"=>20,"selected_primaries"=>20,"unprocessed_primaries"=>0,
            "selected_true_zeros"=>20-positive,"native_calls"=>report["native_calls"],"native_reused"=>2,
            "native_failed"=>failed,"native_completed"=>positive-failed,"readout_completed"=>20-failed,
            "readout_accepted"=>count(r->r["readout"]!==nothing && r["readout"]["accepted"],report["cases"]),
            "zero_input_readouts"=>20-positive,
            "readout_not_accepted"=>count(r->r["readout"]!==nothing && !r["readout"]["accepted"],report["cases"]),
            "electronics_rejected"=>count(r->!r["zero_ge"] && r["readout"]!==nothing && !r["readout"]["accepted"],report["cases"]))
        report["status"]=failed>0 ? "completed_with_native_failures" : "completed"
        report["added_native_seconds"]=sum(r["native_seconds"] for r in report["cases"] if !(r["initial_primary_id"] in OLD_IDS[model]))
        report["added_readout_seconds"]=sum(r["electronics_seconds"] for r in report["cases"] if !(r["initial_primary_id"] in OLD_IDS[model]))
        report["display_prefix_and_parity_seconds"]=display_seconds
    catch err
        report["status"]="failed";report["failure_stage"]=stage;report["error"]=sprint(showerror,err);rethrow()
    finally
        report["worker_seconds"]=time()-started;G.save(joinpath(output,"report.json"),report)
    end
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    length(ARGS)==4 && ARGS[1]=="--request" && ARGS[3]=="--output" || error("Usage: --request FILE --output OWNED_MODEL_DIR")
    GammaCompleteExample.worker(ARGS[2],ARGS[4])
end
