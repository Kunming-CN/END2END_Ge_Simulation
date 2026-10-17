# Resident, serial GeGI response. Diagnostics never share the JSON protocol stream.
redirect_stdout(stderr) do
    include("gegi_response.jl")
    include("gegi_pixel_calibration.jl")
end
module GeGICampaignResponse
using ..GeGIResponse, ..GeGIPixelCalibration
using JSON, SHA, Unitful, LinearAlgebra
const G=GeGIResponse;const K=GeGIPixelCalibration;const H=G.H;const E=G.E;const P=G.P
const check=G.check
const KIND="gegi_campaign_response_request_v1"
const PROTOCOL="gegi_campaign_response_protocol_v1"
const GROUP_HORIZON_NS=100000.0
const NATIVE_FAILURE_POLICY="gegi_campaign_native_domain_errors_v2"
# The contact-start precondition cannot provide a trustworthy charge response.
# Preserve the whole group as unknown; never move or discard its deposit rows.
const RECORDED_NATIVE_ARGUMENT_ERRORS=("Noncontact endpoint outside crystal",
    "Invalid waveform support","Deposit starts on a GeGI contact")

function sources()
    names=unique([collect(G.SOURCES);"gegi_pixel_calibration.jl";"gegi_campaign_response.jl";"Project.toml";"Manifest.toml"])
    Dict(n=>G.hashfile(joinpath(@__DIR__,n)) for n in names)
end
function emit(io,value)
    JSON.print(io,value);println(io);flush(io)
end
function reply(io,body,requestid)
    # Calibration/quit bodies can infer String-only value types. The protocol
    # adds an integer request ID, so widen only this transient reply envelope.
    response=Dict{String,Any}(body)
    response["request_id"]=requestid;response["protocol"]=PROTOCOL
    emit(io,response)
end
function owned_output(out,identity)
    out=abspath(out)
    if ispath(out)
        check(isdir(out) && G.Q.childof(realpath(out),realpath(joinpath(G.ROOT,".local"))),"Spool must remain under .local")
        path=joinpath(out,"native-identity.json")
        if isfile(path)
            check(E.readjson(path)==identity,"Resident worker spool identity changed")
        else
            # The Python adapter may already own its lock and diagnostic log.
            allowed=Set(("adapter-identity.json","resident.lock","worker-stderr.log","worker-process.json"))
            check(Set(readdir(out))<=allowed,"Unowned nonempty resident spool")
            G.save(path,identity)
        end
    else
        G.Q.reserve_output(out);G.save(joinpath(out,"native-identity.json"),identity)
    end
    out
end
function initialize(requestpath,out)
    requestpath=G.input_path(requestpath);req=E.readjson(requestpath)
    check(req["kind"]==KIND,"Unsupported campaign response request")
    check(get(get(req,"numerics",Dict()),"field_policy",nothing)=="reuse-only", "Campaign response requires reuse-only fields")
    check(get(req,"field_cache",nothing)!==nothing,"Campaign response requires an exact field cache; no solve fallback")
    check(get(req,"pulse_group_horizon_ns",GROUP_HORIZON_NS)==GROUP_HORIZON_NS,"Changed transport pulse-group horizon")
    model=G.pinned_input(req,"model_ref","model_sha256");profile=G.pinned_input(req,"profile_ref","profile_sha256")
    check(req["model_sha256"]==G.MODEL_HASH,"Frozen GeGI model changed")
    for (ref,digest) in req["source_sha256"]
        check(G.hashfile(G.input_path(ref))==digest,"Changed pinned source: "*ref)
    end
    cfg=G.numerics(req);n=req["selection"]["primary_count"]
    check(E.integer(n) && 1<=n<=10000000,"Invalid campaign primary identity bound")
    readout=P.load(profile).config
    readout["expected_primary_count"]=n # Metadata only; the pinned profile bytes and electronics settings remain unchanged.
    check(readout["peak_policy"]==E.SIGNED_PEAK_POLICY,"GeGI requires signed-input readout")
    tail=1000*readout["tail_shaping_constants"]*readout["shaping_tau_us"]
    check((cfg.max_steps-1)*cfg.dt+tail<GROUP_HORIZON_NS,"Native drift cap plus electronics tail exceeds pulse horizon")
    P.window_config(readout,GROUP_HORIZON_NS,cfg.dt)
    frozen=sources();requestsha=G.hashfile(requestpath)
    identity=Dict("kind"=>PROTOCOL,"request_sha256"=>requestsha,"source_code_sha256"=>frozen)
    out=owned_output(out,identity)
    env=G.Q.environment("cpu");E.environment();BLAS.set_num_threads(1)
    report=Dict{String,Any}()
    sim=G.load_fields(req,model,out,cfg,report)
    check(report["fields"]["mode"]=="explicit_exact_model_cache","Unexpected new field solve")
    channels=H.channel_metadata(sim.config_dict)
    eion=Float64(ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation))
    matrix=E.transition(readout,cfg.dt);cal=P.calibration(readout,eion,cfg.dt,matrix)
    ready=Dict("protocol"=>PROTOCOL,"status"=>"ready","request_sha256"=>requestsha,
        "source_code_sha256"=>frozen,"source_sha256"=>req["source_sha256"],"model_sha256"=>G.MODEL_HASH,
        "profile_sha256"=>req["profile_sha256"],
        "native_failure_policy"=>Dict("version"=>NATIVE_FAILURE_POLICY,
            "recorded_argument_errors"=>collect(RECORDED_NATIVE_ARGUMENT_ERRORS),
            "failed_group_response"=>"unknown/null; complete input rows retained","unexpected_errors"=>"abort"),
        "field_cache_sha256"=>req["field_cache"]["sha256"],"field_cache"=>req["field_cache"],
        "new_field_solve"=>false,"fields"=>report["fields"],"channels"=>channels,"readout_config"=>readout,
        "drift_numerics"=>Dict(string(k)=>getproperty(cfg,k) for k in propertynames(cfg)),
        "electronics_calibration"=>cal,"ionisation_energy_eV"=>eion,"drift_dt_ns"=>cfg.dt,
        "pulse_group_horizon_ns"=>GROUP_HORIZON_NS,"environment"=>env)
    (req=req,requestpath=requestpath,requestsha=requestsha,out=out,cfg=cfg,n=n,sim=sim,channels=channels,
        readout=readout,eion=eion,matrix=matrix,cal=cal,sources=frozen,ready=ready)
end

function read_native(path,channels)
    wiring=Dict(c["id"]=>c["wiring_factor"] for c in channels)
    native=Dict(i=>(times=Float64[],charge=Float64[]) for i in keys(wiring))
    open(path) do io
        check(readline(io)=="contact_id,time_ns,signed_induced_keV,wired_induced_keV","Unexpected native CSV schema")
        for line in eachline(io)
            parts=split(line,',');check(length(parts)==4,"Invalid native CSV row")
            id=parse(Int,parts[1]);check(haskey(native,id),"Unknown native channel")
            t,q,w=parse.(Float64,parts[2:4])
            check(all(isfinite,(t,q,w)) && w==wiring[id]*q,"Native signed/wiring identity changed")
            push!(native[id].times,t);push!(native[id].charge,q)
        end
    end
    native
end

"""Replay only the shared electronics/timing recipe from complete native inputs."""
function replay_channels(native,channels,readout,eion,cal,matrix;horizon_ns=nothing)
    rows=Any[]
    for ch in channels
        id=ch["id"];w=native[id];t=w.times;q=w.charge;wired=ch["wiring_factor"].*q
        result=P.process(t,wired,readout,eion,cal,matrix;horizon_ns=horizon_ns)
        check(result["current_balance"]["passed"],"Current/charge identity failed in electronics replay")
        collecting=last(wired)>=readout["threshold_V"]/cal["volts_per_keV"]
        tx=collecting ? H.crossing_time(t,wired,0.5) : nothing
        t90=collecting ? H.crossing_time(t,wired,0.9) : nothing
        result["contact_id"]=id;result["final_induced_keV"]=last(q)
        result["final_wired_induced_keV"]=last(wired);result["collection_candidate"]=collecting
        result["t50_ns"]=tx;result["t90_ns"]=t90
        result["timing_method"]=K.TIMING_METHOD
        if horizon_ns!==nothing
            result["native_t50_ns"]=tx;result["native_t90_ns"]=t90
            result["timing_window_ns"]=horizon_ns
            result["t50_outside_window"]=tx!==nothing && tx>=horizon_ns
            result["t90_outside_window"]=t90!==nothing && t90>=horizon_ns
            result["t50_outside_window"] && (result["t50_ns"]=nothing)
            result["t90_outside_window"] && (result["t90_ns"]=nothing)
        end
        trace=result["trace"]
        trace["wired_induced_charge_fC"]=trace["induced_charge_fC"]
        trace["signed_induced_charge_fC"]=ch["wiring_factor"].*trace["induced_charge_fC"]
        trace["charge_fC"]=trace["signed_induced_charge_fC"]
        trace["signed_induced_current_nA"]=ch["wiring_factor"].*trace["current_nA"]
        result["trace_conventions"]=Dict("charge_fC"=>"Raw signed SSD induced charge before fixed family wiring",
            "current_nA"=>"Current after fixed family wiring; original integration bin, not display-point interval",
            "preamp_V"=>"Signed preamplifier output driven by fixed-wiring current",
            "shaped_V"=>"Signed shaper voltage with configured electronics inversion",
            "wired_induced_charge_fC"=>"Charge after fixed X=+1/Y=-1 wiring")
        result["wiring_factor"]=ch["wiring_factor"]
        push!(rows,result)
    end
    rows
end

function replay_payload(req)
    readout=req["readout_config"];eion=req["ionisation_energy_eV"];dt=req["drift_dt_ns"]
    matrix=E.transition(readout,dt);cal=P.calibration(readout,eion,dt,matrix)
    check(cal==req["electronics_calibration"],"Frozen electronics injection calibration changed")
    channels=req["channels"]
    native=Dict(parse(Int,k)=>(times=Float64.(v["time_ns"]),charge=Float64.(v["signed_induced_keV"])) for (k,v) in req["native_signals"])
    check(Set(keys(native))==Set(c["id"] for c in channels),"Replay channel census changed")
    Dict("kind"=>"gegi_electronics_replay_v1","channels"=>replay_channels(native,channels,readout,eion,cal,matrix;
        horizon_ns=get(req,"horizon_ns",nothing)),"source_code_sha256"=>sources(),"drift_executed"=>false)
end

function process_group(ctx,command;event_processor=G.process_event)
    text=command["group_json"];digest=command["input_sha256"]
    check(digest==bytes2hex(sha256(text)) && occursin(r"^[0-9a-f]{64}$",digest),"Group transport bytes changed")
    group=JSON.parse(text);id=group["event_id"];gid=group["group_id"]
    check(E.integer(gid) && gid>=0,"Invalid original group ID")
    origin=group["group_origin_time_ns"];parenttime=group["primary_time_ns"]
    check(E.finite(origin)&&E.finite(parenttime)&&0<=parenttime<=origin,"Invalid group/parent time origin")
    check(!isempty(group["steps"]) && origin==minimum(s["time_ns"] for s in group["steps"]),"Group origin is not its actual first deposit")
    horizon=get(group,"horizon_ns",nothing)
    check(horizon===nothing || horizon==GROUP_HORIZON_NS,"Changed finite pulse-group horizon")
    if horizon!==nothing
        check(all(s->0<=s["time_ns"]-origin<horizon,group["steps"]),"Deposit outside original half-open group")
    end
    working=Dict("event_id"=>id,"primary_time_ns"=>origin,"steps"=>group["steps"])
    G.validate_event(working,ctx.n)
    stem="g-"*digest;eventpath=joinpath(ctx.out,stem*".json");signalpath=joinpath(ctx.out,stem*"-signals.csv")
    inputpath=joinpath(ctx.out,stem*"-input.json");receiptpath=joinpath(ctx.out,stem*"-receipt.json")
    if isfile(receiptpath)
        receipt=E.readjson(receiptpath)
        check(receipt["input_sha256"]==digest && G.hashfile(eventpath)==receipt["event_sha256"],"Completed spool receipt changed")
        receipt["signals_path"]===nothing || check(G.hashfile(signalpath)==receipt["signals_sha256"],"Completed native spool changed")
        return receipt
    end
    if isfile(inputpath)
        check(E.readjson(inputpath)==group,"Interrupted input group changed")
        check(!isfile(eventpath) && !isfile(signalpath),"Unreceipted native output retained; inspect before retry")
    else
        G.save(inputpath,group)
    end
    event=try
        value=event_processor(working,ctx.sim,ctx.cfg,ctx.channels,ctx.readout,ctx.cal,ctx.matrix,ctx.eion,ctx.n,signalpath)
        if horizon!==nothing
            native=read_native(signalpath,ctx.channels)
            value["channels"]=replay_channels(native,ctx.channels,ctx.readout,ctx.eion,ctx.cal,ctx.matrix;horizon_ns=horizon)
        end
        value
    catch err
        known=err isa ArgumentError && err.msg in RECORDED_NATIVE_ARGUMENT_ERRORS
        failure=Dict("event_id"=>id,"status"=>known ? "native_failed" : "unexpected_failure",
            "channels"=>nothing,"truth_edep_keV"=>sum(s["energy_keV"] for s in group["steps"]),
            "steps"=>group["steps"],"error"=>sprint(showerror,err),"exception_type"=>string(typeof(err)),
            "signals_ref"=>nothing,"signals_sha256"=>nothing,"transport_flags"=>nothing,
            "native_failure_policy"=>NATIVE_FAILURE_POLICY,"native_domain_error"=>known ? err.msg : nothing)
        if !known
            failure["input_group"]=group;G.save(eventpath,failure);rethrow()
        end
        failure
    end
    event["input_group"]=group;event["input_steps"]=group["steps"]
    event["group_id"]=gid;event["parent_primary_time_ns"]=parenttime;event["primary_time_ns"]=origin
    event["group_origin_time_ns"]=origin;event["input_event_sha256"]=digest
    event["time_convention"]="Native/electronics time_ns is relative to group_origin_time_ns; input_steps retain original absolute transport time_ns."
    event["readout_horizon_ns"]=horizon
    for k in ("source_id","global_decay_id","initial_primary_id","root","source_group","chunk_index","campaign_initial_offset","pulse_group")
        haskey(group,k) && (event[k]=group[k])
    end
    check(sources()==ctx.sources && G.hashfile(ctx.requestpath)==ctx.requestsha,"Resident response source/request changed")
    G.save(eventpath,event)
    good=event["status"]!="native_failed"
    receipt=Dict("status"=>"processed","event_id"=>id,"group_id"=>gid,"input_sha256"=>digest,
        "event_status"=>event["status"],"event_path"=>eventpath,"event_sha256"=>G.hashfile(eventpath),
        "signals_path"=>good ? signalpath : nothing,"signals_sha256"=>good ? G.hashfile(signalpath) : nothing,
        "input_path"=>inputpath,"receipt_path"=>receiptpath,
        "retained_failure_paths"=>good ? String[] : filter(isfile,[eventpath,inputpath,signalpath]))
    G.save(receiptpath,receipt)
    receipt
end

function serve(requestpath,out;input=stdin,output=stdout)
    ctx=redirect_stdout(stderr) do;initialize(requestpath,out);end
    emit(output,ctx.ready)
    for line in eachline(input)
        isempty(line) && continue
        requestid=nothing
        try
            check(sizeof(line)<=100000000,"Oversized protocol request")
            command=JSON.parse(line);requestid=command["request_id"];name=command["command"]
            response=redirect_stdout(stderr) do
                if name=="process"
                    process_group(ctx,command)
                elseif name=="calibrate"
                    stopfile=joinpath(ctx.out,"calibration-stop.request")
                    result=K.build(ctx.sim,ctx.cfg,ctx.channels,command["output"];field_cache=ctx.req["field_cache"],
                        injection_energy_keV=ctx.readout["calibration_energy_keV"],
                        max_new_injections=get(command,"max_new_injections",nothing),stop_requested=()->isfile(stopfile))
                    Dict("status"=>result.status,"calibration_path"=>result.calibration_path,
                        "calibration_sha256"=>result.calibration_path===nothing ? nothing : G.hashfile(result.calibration_path),
                        "diagnostics_path"=>result.diagnostics_path)
                elseif name=="replay"
                    path=G.pinned_input(command,"input_ref","input_sha256")
                    target=joinpath(ctx.out,"replay-"*command["input_sha256"]*".json")
                    value=replay_payload(E.readjson(path));G.save(target,value)
                    Dict("status"=>"replayed","output_path"=>target,"output_sha256"=>G.hashfile(target),"drift_executed"=>false)
                elseif name=="quit"
                    Dict("status"=>"closed")
                else
                    throw(ArgumentError("Unknown resident command"))
                end
            end
            reply(output,response,requestid)
            name=="quit" && return 0
        catch err
            emit(output,Dict("protocol"=>PROTOCOL,"request_id"=>requestid,"status"=>"error",
                "error"=>sprint(showerror,err),"fatal"=>true))
            return 1
        end
    end
    0
end

function main(args=ARGS)
    BLAS.set_num_threads(1)
    if length(args)==4 && args[1]=="--replay-only" && args[3]=="--output"
        E.environment()
        req=E.readjson(args[2]);out=abspath(args[4])
        check(!ispath(out) && G.Q.childof(realpath(dirname(out)),realpath(joinpath(G.ROOT,".local"))),"Replay output must be new and under .local")
        G.save(out,replay_payload(req));return 0
    end
    check(length(args)==4 && args[1]=="--request" && args[3]=="--spool","Use --request FILE --spool DIR")
    serve(args[2],args[4])
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    exit(GeGICampaignResponse.main())
end
