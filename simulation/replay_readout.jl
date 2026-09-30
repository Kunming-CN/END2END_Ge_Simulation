# Additive electronics-only worker. The Python driver owns trusted completion.
include("readout_profiles.jl")
using JSON
const E=Readout
const P=ReadoutProfiles
const ROOT=dirname(@__DIR__)
function runtime()
    env=Dict{String,Any}(E.environment())
    E.check(VERSION==v"1.13.0", "Replay requires installed Julia 1.13.0")
    E.check(!any(p.name=="SolidStateDetectors" for p in keys(Base.loaded_modules)), "SSD must not be loaded")
    f=first(methods(P.process)); file,line=Base.functionloc(f)
    E.check(f.module===P && realpath(string(file))==realpath(joinpath(@__DIR__,"readout_profiles.jl")), "Unexpected loaded readout module")
    merge!(env,Dict("active_project"=>realpath(Base.active_project()),
        "executable"=>realpath(joinpath(Sys.BINDIR,Base.julia_exename())),
        "readout_module"=>string(P),"process_source"=>realpath(string(file)),"process_line"=>line,
        "ssd_loaded"=>false,"threads"=>Threads.nthreads(),
        "source_sha256"=>Dict(n=>E.hashfile(joinpath(@__DIR__,n)) for n in
            ("readout.jl","readout_profiles.jl","readout_demo.json","replay_readout.jl"))))
end
# The native exporter quotes numerical CSV cells. Support quoted/bare numeric
# cells only; embedded delimiters/escaped quotes are not a numerical field.
function signal_fields(line)
    fields=split(line,','); E.check(length(fields)==5,"Signal row schema")
    result=String[]
    for field in fields
        value=String(field)
        if startswith(value,"\"")
            E.check(length(value)>=2 && endswith(value,"\""),"Unclosed quoted signal field")
            value=value[2:prevind(value,lastindex(value))]
        end
        E.check(!occursin('"',value),"Invalid quote in numeric signal field")
        push!(result,value)
    end
    for j in 1:3
        E.check(occursin(r"^(0|[1-9][0-9]*)$",result[j]),"Strict signal identity")
    end
    result
end

function worker(path)
    E.check(isfile(path) && filesize(path)<=4*1024^2,"Missing/oversized request")
    req=JSON.parsefile(path); base=dirname(realpath(path))
    E.check(Set(keys(req))==Set(("schema_version","kind","detectors","source_sha256")),"Request keys")
    E.check(req["schema_version"]===1 && req["kind"]=="electronics_replay_request_v1","Request kind")
    for (name,h) in req["source_sha256"]
        E.check(!isabspath(name) && !occursin("..",name) && E.hashfile(joinpath(ROOT,name))==h,"Worker source changed")
    end
    out=joinpath(base,"worker"); E.check(!ispath(out),"Worker output exists"); mkdir(out)
    report=Dict{String,Any}("kind"=>"electronics_replay_worker_v1","status"=>"incomplete","detectors"=>Dict())
    try
        report["runtime"]=runtime(); total_charge=0; total_analog=0
        models=[d["model"] for d in req["detectors"]]
        E.check(1<=length(models)<=2 && length(unique(models))==length(models) && all(m->m in ("AK02","SAP22"),models),"Detector inventory")
        for d in req["detectors"]
            E.check(Set(keys(d))==Set(("model","profile","config","eion","dt","primary_count","input_sha256")),"Detector request keys")
            model=d["model"]; input=joinpath(base,"inputs",model)
            for (name,h) in d["input_sha256"]
                E.check(name in ("signals.csv","scalars.jsonl") && E.hashfile(joinpath(input,name))==h,"Input hash changed")
            end
            E.check(Set(keys(d["input_sha256"]))==Set(("signals.csv","scalars.jsonl")),"Input inventory")
            c=P.for_census(d["profile"],d["primary_count"]); P.validate_resolved(d["config"],d["profile"],d["primary_count"])
            E.check(d["dt"]==2 && d["eion"]==2.95,"Unsupported recorded grid/units")
            cal_started=time(); M=E.transition(c,d["dt"]); cal=P.calibration(c,d["eion"],d["dt"],M)
            calibration_seconds=time()-cal_started
            dest=joinpath(out,model); mkdir(dest)
            counts=Dict(k=>0 for k in ("initial_primaries","zero_deposit_primaries","groups","native_failed_groups","readout_rejected","accepted","rejected","saturated","native_charge_samples","analog_samples"))
            electronics=0.0
            open(joinpath(dest,"scalars.jsonl"),"w") do scalar
                open(joinpath(dest,"traces.jsonl"),"w") do traces
                    open(joinpath(input,"signals.csv")) do signals
                        E.check(E.readrow(signals)=="event_id,global_decay_id,group_id,time_since_origin_ns,induced_equivalent_energy_keV","Signals schema")
                        for line in eachline(joinpath(input,"scalars.jsonl"))
                            E.check(sizeof(line)<=2*1024^2,"Oversized scalar")
                            rec=JSON.parse(line)
                            if rec["record_kind"]=="decay"
                                E.check(rec["event_id"]===counts["initial_primaries"],"Primary ledger order")
                                counts["initial_primaries"]+=1; counts["zero_deposit_primaries"]+=rec["zero_deposit"]
                            else
                                E.check(rec["record_kind"]=="pulse","Scalar kind"); counts["groups"]+=1
                                if get(rec,"status",nothing)=="native_transport_failed"
                                    E.check(rec["readout"]===nothing && rec["accepted"]===false,"Native failure must remain null")
                                    counts["native_failed_groups"]+=1; counts["rejected"]+=1
                                else
                                    n=rec["readout"]["input_sample_count"]
                                    E.check(E.integer(n) && 2<=n<=500000,"Charge sample bound")
                                    total_charge+=n; E.check(total_charge<=2_000_000,"Total charge sample cap")
                                    t=Float64[]; q=Float64[]
                                    for k in 1:n
                                        E.check(!eof(signals),"Truncated charge")
                                        fields=signal_fields(E.readrow(signals))
                                        E.check([parse(Int,fields[j]) for j in 1:3]==[rec["event_id"],rec["global_decay_id"],rec["group_id"]],"Signal identity/order")
                                        push!(t,parse(Float64,fields[4])); push!(q,parse(Float64,fields[5]))
                                    end
                                    E.validate_wave(t,q,d["dt"],500000)
                                    E.check(last(t)==rec["charge_end_ns"] && last(q)==rec["final_induced_keV"],"Charge endpoint")
                                    E.check(rec["group"]["horizon_ns"]==100000 && rec["origin_time_ns"]==rec["group"]["origin_time_ns"],"Recorded isolated clock")
                                    total_analog+=50000; E.check(total_analog<=20_000_000,"Total analog sample cap")
                                    started=time(); r=P.process(t,q,c,d["eion"],cal,M;horizon_ns=rec["group"]["horizon_ns"]); electronics+=time()-started
                                    E.check(r["current_balance"]["passed"],"Charge/current balance")
                                    tr=pop!(r,"trace")
                                    println(traces,JSON.json(Dict("event_id"=>rec["event_id"],"global_decay_id"=>rec["global_decay_id"],"group_id"=>rec["group_id"],"origin_time_ns"=>rec["origin_time_ns"],"trace"=>tr)))
                                    rec["readout"]=r; rec["accepted"]=r["accepted"]; rec["rejection_reason"]=r["rejection_reason"]; rec["trace_saved"]=true
                                    counts[r["accepted"] ? "accepted" : "rejected"]+=1
                                    counts["readout_rejected"]+=!r["accepted"]; counts["saturated"]+=r["saturated"]
                                    counts["native_charge_samples"]+=n; counts["analog_samples"]+=r["original_sample_count"]
                                end
                            end
                            println(scalar,JSON.json(rec))
                        end
                        E.check(eof(signals),"Extra charge rows")
                    end
                end
            end
            E.check(counts["initial_primaries"]==d["primary_count"],"Primary census")
            report["detectors"][model]=Dict("counts"=>counts,"calibration"=>cal,"config"=>c,
                "electronics_seconds"=>electronics,"calibration_seconds"=>calibration_seconds)
        end
        for (name,h) in req["source_sha256"]; E.check(E.hashfile(joinpath(ROOT,name))==h,"Source changed during worker"); end
        report["status"]="worker_complete_untrusted"
        report["artifacts"]=Dict(m*"/"*n=>E.hashfile(joinpath(out,m,n)) for m in models for n in ("scalars.jsonl","traces.jsonl"))
    catch err
        report["status"]="failed"; report["error_type"]=string(typeof(err)); rethrow()
    finally
        E.save(joinpath(out,"report.json"),report)
    end
end
function main(args=ARGS)
    if args==["--probe"]
        println(JSON.json(runtime()))
    elseif length(args)==2 && args[1]=="--request"
        worker(args[2])
    else
        error("Only --probe or --request FILE is supported; the driver owns final completion")
    end
end
if abspath(PROGRAM_FILE)==@__FILE__; main(); end
