# Ring adapter around the unchanged native diffusion/electronics implementation.
include("native_response.jl")
include("ring_stream.jl")
module RingResponse
using ..NativeResponse, ..RingStream, JSON, Unitful, SolidStateDetectors, Serialization
const NR=NativeResponse;const RS=RingStream;const S=NR.S;const R=NR.R;const Q=NR.Q;const E=NR.E;const P=NR.P;const N=NR.N
function prepare(o)
    stream=RS.inspect(o["input"]);d=stream.manifest;meta=stream.prepared;c=d["model_contract"]
    model=RS.model_contract(c,stream.pins)
    original=Simulation{Float64}(model);stored=original.detector.semiconductor.temperature
    R.check(stored==78,"Stored ring temperature must remain78K")
    config=deepcopy(original.config_dict);sc=config["detectors"][1]["semiconductor"]
    sc["temperature"]=77.0
    haskey(sc["charge_drift_model"],"temperature") && (sc["charge_drift_model"]["temperature"]=77.0)
    sim=Simulation{Float64}(config)
    R.check(sim.detector.semiconductor.temperature==77,"Explicit ring runtime temperature failed")
    cdm=sim.detector.semiconductor.charge_drift_model
    R.check(!hasproperty(cdm,:temperature) || cdm.temperature==77,"Ring drift-temperature mismatch")
    contacts=Dict(string(x.id)=>x.potential for x in sim.detector.contacts)
    R.check(contacts==c["contact_potentials_V"],"Loaded ring contacts/bias mismatch")
    R.check(isfile(o["profile"]) && Q.childof(realpath(o["profile"]),realpath(Q.ROOT)),"Profile must stay in project")
    profile=P.load(o["profile"]);geom=NR.geometry(meta,sim,true);geom["model_contract"]=c
    geom["field_cache_used"]=false
    P.window_config(profile.config,d["grouping_policy"]["horizon_ns"],N.DT)
    S.foreach_decay(e->R.validate_deposits(Dict("events"=>[e]),sim),stream);S.recheck(stream)
    eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation)
    matrix=E.transition(profile.config,N.DT);cal=P.calibration(profile.config,eion,N.DT,matrix)
    bias=maximum(x.potential for x in sim.detector.contacts)-minimum(x.potential for x in sim.detector.contacts)
    (input=stream.path,inputhash=E.hashfile(stream.path),ion=true,stream=stream,document=d,meta=meta,
        profile=profile,sim=sim,stored=stored,bias=bias,geometry=geom,matrix=matrix,calibration=cal,eion=eion)
end
function main(args=ARGS)
    o=NR.options(args);Q.environment("cpu");E.environment()
    R.check(Threads.nthreads() in (1,2),"Use one or two Julia threads")
    start=time();a=prepare(o);preflight=time()-start
    if o["inspect"]
        println(JSON.json(Dict("status"=>"inspected_no_field_solve","model_contract"=>a.document["model_contract"],"primary_count"=>a.document["primary_count"],"preflight_seconds"=>preflight,"geometry"=>a.geometry,"calibration"=>a.calibration)));return
    end
    sources=Dict(n=>E.hashfile(joinpath(@__DIR__,n)) for n in (NR.SOURCES...,"ring_stream.jl","ring_response.jl"))
    report=NR.run(o,a)
    R.check(all(E.hashfile(joinpath(@__DIR__,n))==h for (n,h) in sources),"Ring consumer changed during run")
    S.recheck(a.stream)
    # Separate adapter authority leaves the original native report format intact.
    envelope=Dict("kind"=>"ring_native_response_v1","status"=>report["status"],"model_contract"=>a.document["model_contract"],
        "input_sha256"=>a.inputhash,"native_report_sha256"=>E.hashfile(joinpath(o["output"],"run.json")),
        "profile_sha256"=>a.profile.sha256,"source_sha256"=>sources,"preflight_seconds"=>preflight,
        "source_model_sha256"=>a.document["model_sha256"],"effective_model_sha256"=>a.document["model_contract"]["effective_model_sha256"],
        "new_field_solution"=>true,"counts"=>report["counts"],"field_timings"=>report["field_timings"],
        "native_seconds"=>report["native_drift_and_charge_seconds"],"electronics_seconds"=>report["electronics_seconds"],
        "calibration"=>report["calibration"],"field_fingerprint"=>report["field_fingerprint"],
        "failure_policy"=>o["native-failure-policy"],"processing_completion_is_not_validation"=>true)
    E.save(joinpath(o["output"],"ring-response.json"),envelope)
    println(JSON.json(Dict("ring_status"=>envelope["status"],"variant"=>a.document["model_contract"]["variant_id"],"counts"=>report["counts"])))
end
end
if abspath(PROGRAM_FILE)==@__FILE__;RingResponse.main();end
