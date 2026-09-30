# M5a saved-charge worker. One Julia session; Python verifies and commits groups.
# Includes the existing electronics worker's parser/runtime, never a native module.
include("replay_readout.jl")

function group_runtime()
    r=runtime(); f=first(methods(process_group)); file,line=Base.functionloc(f)
    E.check(f.module===Main && realpath(string(file))==realpath(@__FILE__),"Loaded group worker identity")
    r["source_sha256"]["replay_groups.jl"]=E.hashfile(@__FILE__)
    merge!(r,Dict("group_process_module"=>string(f.module),"group_process_source"=>realpath(string(file)),"group_process_line"=>line))
end

function durable_json(path,value)
    E.check(!ispath(path),"Staged output exists")
    open(path,"w") do stream
        write(stream,JSON.json(value));write(stream,'\n');flush(stream)
    end
end

function notify_group(phase,key,directory)
    println(JSON.json(Dict("kind"=>"group_ready","phase"=>phase,"key"=>key,"directory"=>directory)));flush(stdout)
    E.check(!eof(stdin),"Driver disappeared before commit acknowledgement")
    ack=JSON.parse(readline(stdin));E.check(get(ack,"kind",nothing)=="committed","Invalid driver acknowledgement")
    E.check(Set(keys(ack))==Set(phase=="calibration" ? ("kind","calibration_sha256") : ("kind",)),"Acknowledgement keys")
    ack
end

function process_group(root,stage,g,d,cal,M,loaded)
    key=g["key"];input=joinpath(root,"charge",key)
    for (name,item) in g["files"]
        E.check(E.hashfile(joinpath(input,name))==item["sha256"] && filesize(joinpath(input,name))==item["bytes"],"Charge snapshot changed")
    end
    records=readlines(joinpath(input,"scalars.jsonl"));E.check(length(records)==1,"Single complete pulse required")
    rec=JSON.parse(only(records));E.check(rec["record_kind"]=="pulse","Pulse kind")
    for name in ("event_id","global_decay_id","group_id","origin_time_ns")
        E.check(rec[name]==g["identity"][name],"Group identity/clock")
    end
    counts=Dict(k=>0 for k in ("initial_primaries","zero_deposit_primaries","groups","native_failed_groups","readout_rejected","accepted","rejected","saturated","native_charge_samples","analog_samples"))
    counts["groups"]=1;elapsed=0.0;trace=nothing;c=d["config"]
    open(joinpath(input,"signals.csv")) do signals
        E.check(E.readrow(signals)=="event_id,global_decay_id,group_id,time_since_origin_ns,induced_equivalent_energy_keV","Signals schema")
        if get(rec,"status",nothing)=="native_transport_failed"
            E.check(rec["readout"]===nothing && rec["accepted"]===false && g["samples"]===0,"Native failure nulls")
            counts["native_failed_groups"]=1;counts["rejected"]=1
        else
            n=rec["readout"]["input_sample_count"]
            E.check(E.integer(n) && n==g["samples"] && 2<=n<=500000,"Full sample count")
            t=Float64[];q=Float64[]
            for k in 1:n
                E.check(!eof(signals),"Truncated saved charge"); fields=signal_fields(E.readrow(signals))
                E.check([parse(Int,fields[j]) for j in 1:3]==[rec["event_id"],rec["global_decay_id"],rec["group_id"]],"Signal group identity")
                push!(t,parse(Float64,fields[4]));push!(q,parse(Float64,fields[5]))
            end
            E.validate_wave(t,q,d["dt"],500000)
            E.check(last(t)==rec["charge_end_ns"] && last(q)==rec["final_induced_keV"],"Saved endpoint")
            E.check(rec["group"]["horizon_ns"]==100000 && rec["origin_time_ns"]==rec["group"]["origin_time_ns"],"Recorded isolated origin")
            started=time();r=P.process(t,q,c,d["eion"],cal["calibration"],M;horizon_ns=rec["group"]["horizon_ns"]);elapsed=time()-started
            E.check(r["current_balance"]["passed"],"Charge/current balance")
            tr=pop!(r,"trace");trace=Dict("event_id"=>rec["event_id"],"global_decay_id"=>rec["global_decay_id"],"group_id"=>rec["group_id"],"origin_time_ns"=>rec["origin_time_ns"],"trace"=>tr)
            rec["readout"]=r;rec["accepted"]=r["accepted"];rec["rejection_reason"]=r["rejection_reason"];rec["trace_saved"]=true
            counts[r["accepted"] ? "accepted" : "rejected"]=1;counts["readout_rejected"]=!r["accepted"];counts["saturated"]=r["saturated"]
            counts["native_charge_samples"]=n;counts["analog_samples"]=r["original_sample_count"]
        end
        E.check(eof(signals),"Extra charge samples")
    end
    durable_json(joinpath(stage,"scalars.jsonl"),rec)
    open(joinpath(stage,"traces.jsonl"),"w") do stream
        if trace!==nothing;println(stream,JSON.json(trace));end
    end
    # Python's receipt binds the exact calibration file; digest is supplied by
    # the driver ACK/request, never derived from differently ordered Julia JSON.
    durable_json(joinpath(stage,"result.json"),Dict("kind"=>"saved_charge_electronics_group_v1","key"=>key,"runtime"=>loaded,
        "config"=>c,"calibration_sha256"=>cal["binding_sha256"],"counts"=>counts,"electronics_seconds"=>elapsed))
end

function group_session(path)
    E.check(isfile(path) && filesize(path)<=4*1024^2,"Bounded session request")
    req=JSON.parsefile(path);base=dirname(realpath(path));root=req["root"]
    E.check(req["kind"]=="saved_charge_group_session_v1" && req["schema_version"]===1,"Session kind")
    E.check(Set(keys(req))==Set(("kind","schema_version","root","source_sha256","runtime","detectors","groups","calibration_bindings")),"Session keys")
    for (name,h) in req["source_sha256"]
        E.check(!isabspath(name) && !occursin("..",name) && E.hashfile(joinpath(ROOT,name))==h,"Pinned source changed")
    end
    loaded=group_runtime();E.check(loaded==req["runtime"],"Probe/session runtime changed")
    models=[d["model"] for d in req["detectors"]]
    E.check(1<=length(models)<=2 && length(unique(models))==length(models) && all(m->m in ("AK02","SAP22"),models),"Detector set")
    cals=Dict{String,Any}();matrices=Dict{String,Any}()
    for d in req["detectors"]
        m=d["model"];P.validate_resolved(d["config"],d["profile"],d["primary_count"])
        E.check(d["dt"]==2 && d["eion"]==2.95,"Recorded units/grid")
        M=E.transition(d["config"],d["dt"]);matrices[m]=M
        saved=joinpath(root,"calibration",m,"calibration.json")
        if isfile(saved)
            E.check(E.hashfile(saved)==req["calibration_bindings"][m]["file_sha256"],"Committed calibration changed")
            cal=JSON.parsefile(saved)
            canonical=req["calibration_bindings"][m]["canonical_sha256"]
        else
            started=time();cal=Dict("kind"=>"saved_charge_calibration_v1","model"=>m,"config"=>d["config"],"runtime"=>loaded,
                "calibration"=>P.calibration(d["config"],d["eion"],d["dt"],M),"calibration_seconds"=>time()-started)
            dir="calibration-"*m;stage=joinpath(base,dir);mkdir(stage);durable_json(joinpath(stage,"calibration.json"),cal)
            ack=notify_group("calibration",m,dir);canonical=ack["calibration_sha256"]
            E.check(isfile(saved),"Missing committed calibration after ACK")
        end
        E.check(cal["config"]==d["config"] && cal["runtime"]==loaded,"Fixed calibration configuration/runtime")
        cal["binding_sha256"]=canonical;cals[m]=cal
    end
    seen_keys=String[];charge=0;analog=0
    for g in req["groups"]
        key=g["key"];E.check(occursin(r"^(AK02|SAP22)-e[0-9]+-d[0-9]+-g[0-9]+$",key) && !(key in seen_keys),"Group key");push!(seen_keys,key)
        charge+=g["samples"];analog+=g["samples"]>0 ? 50000 : 0
        E.check(charge<=2_000_000 && analog<=20_000_000,"Session resource bound")
        d=only(filter(d->d["model"]==g["model"],req["detectors"]));dir="electronics-"*key;stage=joinpath(base,dir);mkdir(stage)
        process_group(root,stage,g,d,cals[d["model"]],matrices[d["model"]],loaded)
        notify_group("electronics",key,dir)
    end
    for (name,h) in req["source_sha256"];E.check(E.hashfile(joinpath(ROOT,name))==h,"Source changed during session");end
    println(JSON.json(Dict("kind"=>"session_done")));flush(stdout)
end

if abspath(PROGRAM_FILE)==@__FILE__
    if ARGS==["--probe"];println(JSON.json(group_runtime()))
    elseif length(ARGS)==2 && ARGS[1]=="--session";group_session(ARGS[2])
    else;error("Only --probe or --session FILE; public driver owns status/commits")
    end
end
