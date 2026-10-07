# One detector-independent source response entry; existing SSD/readout kernels are reused.
include("workflow_ring_response.jl")
include("decay_stream.jl")
include("sap18_polarity.jl")
include("native_boundary_guard.jl")
module WorkflowDecayResponse
using ..WorkflowRingResponse, ..DecayStream, ..Sap18Polarity, ..NativeBoundaryGuard, JSON, Unitful, SolidStateDetectors
const WR=WorkflowRingResponse;const DS=DecayStream;const SP=Sap18Polarity;const G=NativeBoundaryGuard
const NR=WR.NR;const R=WR.R;const Q=WR.Q;const E=WR.E;const P=WR.P;const N=WR.N
const SOURCES=Tuple(unique([WR.SOURCES...,"decay_stream.jl","sap18_stream.jl","sap18_polarity.jl","native_boundary_guard.jl","workflow_decay_response.jl"]))
const LIMITATIONS=["Synthetic electronics; no noise/Fano smearing, physical resolution or experimental fit.",
    "Native endpoints and signed charge are retained; no truth normalization or per-event calibration.",
    "Source diagnostics count photons without filtering deposits; raw decay/recoil/EM ancestry and times remain available.",
    "Finite nominal isolated windows reset electronics with possible tail loss and unestablished recovery; no activity/live-time/pileup claim.",
    "Field iteration gates are not grid/PDE/CCE convergence; material ledger has no full energy closure.",
    "Registered detector/source compatibility is factorized; actual full-chain acceptance is disclosed separately."]
function request_options(args)
    inspect=length(args)==3 && args[1]=="--request" && args[3]=="--inspect"
    R.check(inspect || (length(args)==4 && args[1]=="--request" && args[3]=="--output"),"Use --request FILE --output NEW_DIRECTORY, or --request FILE --inspect")
    path=abspath(args[2]);R.check(isfile(path) && !islink(path) && filesize(path)<=2_000_000 && Q.childof(realpath(path),realpath(Q.ROOT)),"Missing/oversized decay request")
    d=JSON.parsefile(path)
    R.check(Set(keys(d))==Set(("kind","configuration_sha256","selection","operating_model","profile_ref","profile_sha256","stream_ref","stream_sha256","source_sha256","numerics","source_id","source_contract")) && d["kind"]=="workflow_decay_request_v1","Wrong shared decay request")
    s=d["selection"];model=s["detector"]
    R.check(Set(keys(s))==Set(("name","cryostat","detector","source","pose","primary_count","seed","threads","electronics")) && s["name"] isa String && occursin(r"^[A-Za-z0-9_-]{1,48}$",s["name"]),"Wrong shared selection fields/name")
    R.check(model in keys(DS.SIGNED_BIAS) && s["cryostat"]=="lbnl_modular_nominal_v1" && s["pose"]=="nominal" && DS.integer(s["primary_count"]) && s["primary_count"] in (20,500),"Unsupported detector/anchor/count")
    R.check(s["source"]==d["source_id"] && DS.source_contract(d["source_id"],d["source_contract"])==d["source_contract"],"Wrong selected source registry contract")
    R.check(DS.integer(s["threads"]) && s["threads"] in (1,2) && Threads.nthreads()==s["threads"] && DS.integer(s["seed"]) && 0<s["seed"]<2147483647,"Wrong runtime/seed")
    op=d["operating_model"];signed=DS.SIGNED_BIAS[model];factor=DS.WIRING[model]
    R.check(op["signed_bias_V"]==signed && op["contact_potentials_V"]==Dict("1"=>0,"2"=>signed) && op["wiring_factor"]==factor && op["readout_contact_id"]==1,"Source selection changed detector polarity/bias/wiring")
    R.check(d["numerics"]==Dict("parcels"=>16,"native_seed_family"=>2609261,"drift_dt_ns"=>2,"drift_cap_ns"=>10000,"stored_temperature_K"=>78,"runtime_temperature_K"=>77,"bias_V"=>abs(signed),"native_failure_policy"=>"record","models_serial"=>true,"stages_serial"=>true),"Wrong native detector settings")
    profile=DS.relative_file(d["profile_ref"]);input=DS.relative_file(d["stream_ref"]);base=".local/runs/"*s["name"]
    R.check(d["profile_ref"]==base*"/electronics/profile.json" && d["stream_ref"]==base*"/transport/stream/manifest.json" && (inspect || abspath(args[4])==abspath(joinpath(Q.ROOT,base,"response"))),"Inputs/output must share one new selected run root")
    R.check(E.hashfile(profile)==d["profile_sha256"] && E.hashfile(input)==d["stream_sha256"],"Decay request/profile/stream binding changed")
    required=union(Set("simulation/"*n for n in SOURCES),Set((DS.REGISTRY_REF,DS.ANCHORS_REF,"tools/decay_workflow.py","tools/scenario_workflow.py","transport/decay_source.py","models/"*model*".yaml")))
    R.check(d["source_sha256"] isa AbstractDict && issubset(required,Set(keys(d["source_sha256"]))) && d["configuration_sha256"] isa String && occursin(r"^[0-9a-f]{64}$",d["configuration_sha256"]),"Incomplete shared source/consumer authority")
    for (ref,h) in d["source_sha256"];DS.pin!(Dict{String,String}(),DS.relative_file(ref),h);end
    R.check(d["source_sha256"]["simulation/workflow_decay_response.jl"]==E.hashfile(@__FILE__),"Wrong shared response source binding")
    values=["--input",input,"--profile",profile,"--parcels","16","--seed","2609261","--trace-examples","16","--charge-csv","all","--native-failure-policy","record"]
    append!(values,inspect ? ["--inspect"] : ["--output",args[4]])
    o=NR.options(values);o["request"]=path;o,d
end
function prepare(o,request;calibrate=true)
    stream=DS.inspect(o["input"]);d=stream.manifest;meta=stream.prepared;c=d["model_contract"]
    s=request["selection"];op=request["operating_model"]
    R.check(d["model_id"]==s["detector"] && d["primary_count"]==s["primary_count"] && meta["seed"]==s["seed"] &&
        d["source_id"]==request["source_id"] && d["source_contract"]==request["source_contract"],"Prepared source/model/census differs from checked selection")
    for key in ("source_model_sha256","effective_model_sha256","variant_id","contact_potentials_V","readout_contact_id")
        R.check(c[key]==op[key],"Effective detector differs from checked selection: "*key)
    end
    expected=s["detector"]=="GeRC02" ? ".local/runs/"*s["name"]*"/transport/effective-model/GeRC02.yaml" : "models/"*s["detector"]*".yaml"
    R.check(c["effective_model_ref"]==expected,"Effective model belongs to a different run")
    model=DS.model_contract(c,stream.pins);original=Simulation{Float64}(model);stored=original.detector.semiconductor.temperature
    R.check(stored==78,"Stored model temperature must remain 78 K")
    config=deepcopy(original.config_dict);sc=config["detectors"][1]["semiconductor"];sc["temperature"]=77.0
    haskey(sc["charge_drift_model"],"temperature") && (sc["charge_drift_model"]["temperature"]=77.0)
    sim=Simulation{Float64}(config);cdm=sim.detector.semiconductor.charge_drift_model
    R.check(sim.detector.semiconductor.temperature==77 && (!hasproperty(cdm,:temperature) || cdm.temperature==77),"Explicit runtime temperature failed")
    contacts=Dict(string(x.id)=>x.potential for x in sim.detector.contacts)
    R.check(contacts==c["contact_potentials_V"]==op["contact_potentials_V"],"Loaded signed detector contacts differ")
    profile=P.load(o["profile"]);R.check(profile.profile["settings"]==s["electronics"],"Selected electronics differ from consumed profile")
    # The existing contour admission supports ICPC and rings; no ring contact/field assumptions enter it.
    geom=NR.geometry(meta,sim,true);geom["model_contract"]=c;geom["field_cache_used"]=false
    P.window_config(profile.config,d["grouping_policy"]["horizon_ns"],N.DT)
    DS.foreach_decay(e->R.validate_deposits(Dict("events"=>[e]),sim),stream);DS.recheck(stream)
    eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation);matrix=E.transition(profile.config,N.DT)
    start=time();negative=nothing;cal=nothing
    if calibrate
        negative=s["detector"]==SP.MODEL ? SP.negative_calibration(profile.config,eion,N.DT,matrix) :
            s["detector"]=="KMRC01_candidate" ? WR.RP.negative_calibration(profile.config,eion,N.DT,matrix) : nothing
        cal=negative===nothing ? P.calibration(profile.config,eion,N.DT,matrix) : negative.calibration
    end
    seconds=time()-start;bias=maximum(x.potential for x in sim.detector.contacts)-minimum(x.potential for x in sim.detector.contacts)
    R.check(bias==abs(DS.SIGNED_BIAS[s["detector"]]),"Loaded detector bias differs")
    (input=stream.path,inputhash=E.hashfile(stream.path),ion=true,stream=stream,document=d,meta=meta,
        profile=profile,sim=sim,stored=stored,bias=bias,geometry=geom,matrix=matrix,calibration=cal,eion=eion,
        injection=negative===nothing ? nothing : negative.injection,calibration_seconds=seconds)
end
function process_response(t,q,c,eion,cal,M,model;horizon_ns)
    R.check(model in keys(DS.SIGNED_BIAS),"Unknown detector response")
    model==SP.MODEL ? SP.process(t,q,c,eion,cal,M;horizon_ns=horizon_ns) : WR.process_ring(t,q,c,eion,cal,M,model;horizon_ns=horizon_ns)
end
function guarded_attempt(f,policy)
    policy=="abort" && return (result=Base.invokelatest(f),error=nothing)
    R.check(policy=="record","Wrong native failure policy")
    try
        G.attempt(f)
    catch err
        err isa ArgumentError && err.msg in NR.NATIVE_FAILURE_MESSAGES || rethrow()
        (result=nothing,error=Dict("type"=>string(typeof(err)),"message"=>err.msg,"exact_error"=>sprint(showerror,err),"stage"=>"NativeLiExample.native_event"))
    end
end
function progress(out,started,stage,status,counts,total)
    value=Dict("kind"=>"workflow_decay_progress_v1","stage"=>stage,"status"=>status,"completed_primary_count"=>counts["initial_primaries"],"expected_primary_count"=>total,"elapsed_seconds"=>time()-started)
    pending=joinpath(out,"progress.json.pending-"*string(getpid()));write(pending,JSON.json(value));mv(pending,joinpath(out,"progress.json");force=true)
end
function summary_html(out,report)
    R.check(report["status"] in ("completed_provisional_native_response","completed_with_native_failures"),"Export requires completed response")
    for (file,h) in report["artifacts"];R.check(E.hashfile(joinpath(out,file))==h,"Export artifact changed");end
    open(joinpath(out,"summary.html"),"w") do io
        print(io,"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Decay response</title><style>body{font:16px/1.5 system-ui;max-width:1000px;margin:auto;padding:20px;overflow-wrap:anywhere}svg{width:100%}pre{white-space:pre-wrap}</style><h1>",N.escape(report["model_id"])," · ",N.escape(report["source_id"]),"</h1><p>Synthetic isolated readout. Charge/current retain raw signs; preamp/shaper use the recorded detector wiring. Photon windows are diagnostic counts, with all deposits retained. No physical-resolution, experimental source-placement or calibrated CCE claim.</p><pre>",N.escape(JSON.json(report["counts"],2)),"</pre><p><a href='run.json'>Settings and receipts</a> · <a href='scalars.csv'>All initial primaries and groups</a> · <a href='endpoints.csv'>Endpoints</a> · <a href='truth.jsonl'>Original truth</a> · <a href='histograms.csv'>Histograms</a></p>")
        if report["counts"]["native_failed_groups"]>0;print(io,"<p>Native failures retain null charge/readout quantities. <a href='native-failures.jsonl'>Diagnostics</a>.</p>");end
        for line in eachline(joinpath(out,"traces.jsonl"))
            r=JSON.parse(line);tr=r["trace"];print(io,"<details><summary>Event ",r["event_id"]," / group ",r["group_id"],"</summary>")
            for (k,label) in (("induced_charge_fC","Charge (fC)"),("current_nA","Original-bin current (nA)"),("preamp_V","Analog preamp (V)"),("shaped_V","Analog shaper (V)"))
                print(io,N.plot(tr["time_ns"],get(tr,"raw_native_"*k,tr[k]),label))
            end
            print(io,"<p>Bounded display; raw current belongs to original intervals. Digital output is one peak ADC code.</p></details>")
        end
    end
end
function main(args=ARGS)
    o,request=request_options(args);Q.environment("cpu");E.environment();start=time();a=prepare(o,request;calibrate=!o["inspect"]);preflight=time()-start
    if o["inspect"]
        DS.recheck(a.stream)
        println(JSON.json(Dict("kind"=>"workflow_decay_inspection_v1","status"=>"checked","source_id"=>request["source_id"],"model_id"=>a.document["model_id"],"primary_count"=>a.document["primary_count"],"science_calls"=>0,"calibration_calls"=>0,"seconds"=>preflight)))
        return nothing
    end
    icpc=a.document["model_id"] in keys(DS.CANONICAL_PINS);guard=icpc ? G.install!() : nothing
    extra=Dict{String,Any}("source_id"=>request["source_id"],"source_contract"=>request["source_contract"],
        "source_label"=>request["source_contract"]["label"],"source_pdg"=>request["source_contract"]["pdg"],"normalization"=>request["source_contract"]["normalization"])
    guard!==nothing && (extra["boundary_guard"]=guard)
    report=WR.run(o,a,request;stream_api=DS,process_response=process_response,source_names=SOURCES,
        native_attempt_response=icpc ? guarded_attempt : NR.native_attempt,report_kind="workflow_decay_native_response_v1",
        summary_writer=summary_html,progress_writer=progress,report_extra=extra,source_limitations=LIMITATIONS,
        trace_signal_convention="Charge/current retain raw native signs; electronics input follows the fixed model-owned wiring factor.")
    DS.recheck(a.stream)
    for (ref,h) in request["source_sha256"];DS.pin!(Dict{String,String}(),DS.relative_file(ref),h);end
    R.check(E.hashfile(o["request"])==report["request_sha256"],"Request changed during execution")
    envelope=Dict("kind"=>"workflow_decay_response_v1","status"=>report["status"],"configuration_sha256"=>request["configuration_sha256"],
        "request_sha256"=>report["request_sha256"],"native_report_sha256"=>E.hashfile(joinpath(o["output"],"run.json")),
        "source_sha256"=>request["source_sha256"],"source_id"=>request["source_id"],"source_contract"=>request["source_contract"],"model_contract"=>a.document["model_contract"],
        "signed_operating_bias_V"=>report["signed_operating_bias_V"],"bias_magnitude_V"=>a.bias,"wiring_factor"=>report["wiring_factor"],
        "calibration"=>report["calibration"],"independent_calibration_calls"=>1,"new_field_solution"=>true,"preflight_seconds"=>preflight,
        "calibration_seconds"=>a.calibration_seconds,"counts"=>report["counts"],"processing_completion_is_not_validation"=>true)
    E.save(joinpath(o["output"],"workflow-decay-response.json"),envelope);report
end
end
if abspath(PROGRAM_FILE)==@__FILE__;WorkflowDecayResponse.main();end
