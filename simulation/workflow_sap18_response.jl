# One additive SAP18 connector; all numerical kernels stay in existing SSD/readout modules.
include("workflow_ring_response.jl")
include("sap18_stream.jl")
include("sap18_polarity.jl")
module WorkflowSap18Response
using ..WorkflowRingResponse, ..Sap18Stream, ..Sap18Polarity, JSON, Unitful, SolidStateDetectors
const WR=WorkflowRingResponse;const RR=WR.RR;const NR=WR.NR;const RP=Sap18Polarity
const RS=Sap18Stream;const S=WR.S;const R=WR.R;const Q=WR.Q;const E=WR.E;const P=WR.P;const N=WR.N
const SOURCES=(WR.SOURCES...,"sap18_stream.jl","sap18_polarity.jl","workflow_sap18_response.jl")
function process_sap18(t,q,c,eion,cal,M,model;horizon_ns)
    R.check(model=="SAP18_ring08_scenario","Wrong SAP18 processing identity")
    RP.process(t,q,c,eion,cal,M;horizon_ns=horizon_ns)
end
function request_options(args)
    R.check(length(args)==4 && args[1]=="--request" && args[3]=="--output","Use --request FILE --output NEW_DIRECTORY")
    path=abspath(args[2])
    R.check(isfile(path) && !islink(path) && filesize(path)<=2_000_000 && Q.childof(realpath(path),realpath(Q.ROOT)),"Missing/oversized ring request")
    d=JSON.parsefile(path)
    R.check(Set(keys(d))==Set(("kind","configuration_sha256","selection","operating_model","profile_ref","profile_sha256","stream_ref","stream_sha256","source_sha256","numerics")) && d["kind"]=="workflow_sap18_request_v1","Wrong ring request")
    s=d["selection"];model=s["detector"]
    R.check(Set(keys(s))==Set(("name","cryostat","detector","source","pose","primary_count","seed","threads","electronics")) && s["name"] isa String && occursin(r"^[A-Za-z0-9_-]{1,48}$",s["name"]),"Wrong ring selection fields/name")
    R.check(model=="SAP18_ring08_scenario" && s["cryostat"]=="lbnl_modular_nominal_v1" && s["source"]=="cs137_point_decay_v1" && s["pose"]=="nominal" && s["primary_count"] in (20,500),"Unsupported ring tuple")
    R.check(s["threads"] isa Integer && !(s["threads"] isa Bool) && s["threads"] in (1,2) && Threads.nthreads()==s["threads"] && s["primary_count"] isa Integer && !(s["primary_count"] isa Bool) && s["seed"] isa Integer && !(s["seed"] isa Bool) && 0<s["seed"]<2147483647,"Wrong ring runtime/count/seed")
    op=d["operating_model"]
    signed=-380;factor=-1
    R.check(op["signed_bias_V"]==signed && op["contact_potentials_V"]==Dict("1"=>0,"2"=>signed) && op["wiring_factor"]==factor && op["readout_contact_id"]==1,"Wrong signed operating bias or fixed wiring")
    R.check(d["numerics"]==Dict("parcels"=>16,"native_seed_family"=>2609261,"drift_dt_ns"=>2,"drift_cap_ns"=>10000,"stored_temperature_K"=>78,"runtime_temperature_K"=>77,"bias_V"=>380,"native_failure_policy"=>"record","models_serial"=>true,"stages_serial"=>true),"Wrong native ring settings")
    profile=RS.relative_file(d["profile_ref"]);input=RS.relative_file(d["stream_ref"])
    base=".local/runs/"*s["name"]
    R.check(d["profile_ref"]==base*"/electronics/profile.json" && d["stream_ref"]==base*"/transport/stream/manifest.json" && abspath(args[4])==abspath(joinpath(Q.ROOT,base,"response")),"Ring input/output must share the selected new run root")
    R.check(E.hashfile(profile)==d["profile_sha256"] && E.hashfile(input)==d["stream_sha256"],"Ring request/profile/stream binding changed")
    R.check(d["source_sha256"] isa AbstractDict && !isempty(d["source_sha256"]),"Missing ring source authority")
    required=union(Set("simulation/"*n for n in SOURCES),Set(("tools/sap18_workflow.py","tools/scenario_workflow.py","transport/sap18_source.py","models/"*model*".yaml")))
    R.check(issubset(required,Set(keys(d["source_sha256"]))) && d["configuration_sha256"] isa String && occursin(r"^[0-9a-f]{64}$",d["configuration_sha256"]),"Incomplete fresh ring consumer authority")
    for (ref,h) in d["source_sha256"];RS.pin!(Dict{String,String}(),RS.relative_file(ref),h);end
    R.check(get(d["source_sha256"],"simulation/workflow_sap18_response.jl",nothing)==E.hashfile(@__FILE__),"Wrong fresh ring consumer binding")
    o=NR.options(["--input",input,"--output",args[4],"--profile",profile,"--parcels","16","--seed","2609261","--trace-examples","16","--charge-csv","all","--native-failure-policy","record"])
    o["request"]=path
    o,d
end

function prepare(o,request)
    stream=RS.inspect(o["input"]);d=stream.manifest;meta=stream.prepared;c=d["model_contract"]
    selected=request["selection"];op=request["operating_model"]
    R.check(d["model_id"]==selected["detector"] && d["primary_count"]==selected["primary_count"] && meta["seed"]==selected["seed"],"Ring source selection differs from prepared stream")
    R.check(c["source_model_sha256"]==op["source_model_sha256"] && c["effective_model_sha256"]==op["effective_model_sha256"] && c["variant_id"]==op["variant_id"] && c["contact_potentials_V"]==op["contact_potentials_V"],"Ring effective model differs from checked selection")
    expected="models/SAP18_ring08_scenario.yaml"
    R.check(c["effective_model_ref"]==expected,"Ring model must belong to this new run")
    model=RS.model_contract(c,stream.pins)
    original=Simulation{Float64}(model);stored=original.detector.semiconductor.temperature
    R.check(stored==78,"Stored ring temperature must remain78K")
    config=deepcopy(original.config_dict);sc=config["detectors"][1]["semiconductor"];sc["temperature"]=77.0
    haskey(sc["charge_drift_model"],"temperature") && (sc["charge_drift_model"]["temperature"]=77.0)
    sim=Simulation{Float64}(config);cdm=sim.detector.semiconductor.charge_drift_model
    R.check(sim.detector.semiconductor.temperature==77 && (!hasproperty(cdm,:temperature) || cdm.temperature==77),"Explicit ring runtime temperature failed")
    contacts=Dict(string(x.id)=>x.potential for x in sim.detector.contacts)
    R.check(contacts==c["contact_potentials_V"]==op["contact_potentials_V"],"Loaded signed ring contacts differ")
    profile=P.load(o["profile"])
    R.check(profile.profile["settings"]==selected["electronics"],"Selected electronics differ from consumed profile")
    geom=NR.geometry(meta,sim,true);geom["model_contract"]=c;geom["field_cache_used"]=false
    P.window_config(profile.config,d["grouping_policy"]["horizon_ns"],N.DT)
    S.foreach_decay(e->R.validate_deposits(Dict("events"=>[e]),sim),stream);S.recheck(stream)
    eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation)
    matrix=E.transition(profile.config,N.DT);start=time()
    negative=RP.negative_calibration(profile.config,eion,N.DT,matrix)
    cal=negative===nothing ? P.calibration(profile.config,eion,N.DT,matrix) : negative.calibration
    seconds=time()-start
    bias=maximum(x.potential for x in sim.detector.contacts)-minimum(x.potential for x in sim.detector.contacts)
    (input=stream.path,inputhash=E.hashfile(stream.path),ion=true,stream=stream,document=d,meta=meta,
        profile=profile,sim=sim,stored=stored,bias=bias,geometry=geom,matrix=matrix,calibration=cal,eion=eion,
        injection=negative===nothing ? nothing : negative.injection,calibration_seconds=seconds)
end

function main(args=ARGS)
    o,request=request_options(args);Q.environment("cpu");E.environment()
    start=time();a=prepare(o,request);preflight=time()-start
    report=WR.run(o,a,request;process_response=process_sap18,source_names=SOURCES)
    S.recheck(a.stream)
    for (ref,h) in request["source_sha256"];RS.pin!(Dict{String,String}(),RS.relative_file(ref),h);end
    R.check(E.hashfile(o["request"])==report["request_sha256"],"Ring request changed during execution")
    envelope=Dict("kind"=>"workflow_sap18_response_v1","status"=>report["status"],"configuration_sha256"=>request["configuration_sha256"],
        "request_sha256"=>report["request_sha256"],"native_report_sha256"=>E.hashfile(joinpath(o["output"],"run.json")),
        "source_sha256"=>request["source_sha256"],"model_contract"=>a.document["model_contract"],
        "signed_operating_bias_V"=>report["signed_operating_bias_V"],"bias_magnitude_V"=>a.bias,
        "wiring_factor"=>report["wiring_factor"],"calibration"=>report["calibration"],"independent_calibration_calls"=>1,
        "new_field_solution"=>true,"preflight_seconds"=>preflight,"calibration_seconds"=>a.calibration_seconds,
        "counts"=>report["counts"],"processing_completion_is_not_validation"=>true)
    E.save(joinpath(o["output"],"workflow-sap18-response.json"),envelope)
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__;WorkflowSap18Response.main();end
