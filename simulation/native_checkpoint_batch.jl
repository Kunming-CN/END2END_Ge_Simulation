# Native response only, per-group durable results; existing physics helpers unchanged.
include("native_bridge_pilot.jl")
include("native_boundary_guard.jl")
module NativeCheckpointBatch
using ..NativeBridgePilot, ..NativeBoundaryGuard, JSON, SHA, Serialization, Unitful, Dates
const V=NativeBridgePilot;const B=V.B;const N=B.N;const Q=B.Q;const R=B.R;const P=B.P;const E=B.E;const G=NativeBoundaryGuard
const ROOT=Q.ROOT
check(x,m)=x ? nothing : throw(ArgumentError(m))
hashfile(p)=open(io->bytes2hex(sha256(io)),p)
function durable(io)
    flush(io)
    result=Sys.iswindows() ? ccall((:_commit,"msvcrt"),Cint,(Cint,),Base.fd(io)) : ccall(:fsync,Cint,(Cint,),Base.fd(io))
    check(result==0,"File sync failed")
end
function atomic_write(f,path;replace=false)
    check(replace || !ispath(path),"Refuse to overwrite committed data")
    temp=path*".partial-$(getpid())-$(time_ns())"
    open(temp,"w") do io;f(io);durable(io);end
    Base.Filesystem.rename(temp,path)
end
save(path,obj;replace=false)=atomic_write(io->JSON.print(io,obj),path;replace)
function acquire(path)
    check(Sys.iswindows(),"This native launcher is tested on Windows only")
    name=transcode(UInt16,path*"\0")
    h=ccall((:CreateFileW,"kernel32"),Ptr{Cvoid},(Ptr{UInt16},UInt32,UInt32,Ptr{Cvoid},UInt32,UInt32,Ptr{Cvoid}),name,0xc0000000,0,C_NULL,4,0x80,C_NULL)
    check(h!=Ptr{Cvoid}(typemax(UInt)),"Another native worker holds the exclusive lock")
    h
end
release(h)=ccall((:CloseHandle,"kernel32"),Int32,(Ptr{Cvoid},),h)
check_environment(actual,expected)=check(actual==expected,"Selected Julia project/manifest differs from frozen environment")
function pins(c)
    for (name,h) in c["source_sha256"];check(hashfile(joinpath(ROOT,name))==h,"Source changed: "*name);end
    check(hashfile(joinpath(ROOT,c["original_census_path"]))==c["original_census_sha256"],"Original all-primary census changed")
end
key(model,e,g)=model*"_"*e["namespace"]*"_"*string(e["event_id"])*"_"*string(g["group_id"])
function recover(base,task,inputhash,confighash)
    file=joinpath(base,task*".jls");done=joinpath(base,task*".done.json")
    if !isfile(file)
        check(!isfile(done),"Committed result missing; refusing recomputation")
        return nothing
    end
    if isfile(done)
        d=JSON.parsefile(done)
        check(d["key"]==task && d["input_hash"]==inputhash && d["config_hash"]==confighash,"Checkpoint identity/configuration changed")
        check(hashfile(file)==d["result_hash"],"Checkpoint data corrupted")
        record=deserialize(file)
        check(record["key"]==task && record["input_hash"]==inputhash && record["config_hash"]==confighash,"Serialized checkpoint identity changed")
        check(record["status"]==d["status"] && record["accepted"]==d["accepted"],"Checkpoint summary differs from saved result")
        return d
    end
    # Atomic result exists but completion receipt was interrupted: validate, do not recompute.
    r=deserialize(file)
    check(r["key"]==task && r["input_hash"]==inputhash && r["config_hash"]==confighash,"Uncommitted result mismatch")
    d=Dict("key"=>task,"input_hash"=>inputhash,"config_hash"=>confighash,"result_hash"=>hashfile(file),"status"=>r["status"],"accepted"=>r["accepted"],"bytes"=>filesize(file),"recovered"=>true)
    save(done,d);d
end
function commit(base,record)
    file=joinpath(base,record["key"]*".jls")
    atomic_write(io->serialize(io,record),file)
    recover(base,record["key"],record["input_hash"],record["config_hash"])
end
function progress(out,status,done,total,failed,accepted,started,initial,current=nothing,error=nothing)
    elapsed=time()-started;rate=(done-initial)/max(elapsed,1.0)
    p=Dict("status"=>status,"completed_groups"=>done,"target_groups"=>total,"numerical_failures"=>failed,"accepted"=>accepted,"worker_pid"=>getpid(),"updated_utc"=>string(now(UTC)),"current"=>current,"error"=>error,"new_groups_per_second"=>rate,"eta_seconds"=>rate>0 ? (total-done)/rate : nothing)
    save(joinpath(out,"progress.json"),p;replace=true)
    page="<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'><meta http-equiv='refresh' content='10'><title>Native response progress</title><style>body{font:17px system-ui;max-width:900px;margin:auto;padding:20px}pre{white-space:pre-wrap}</style><h1>Native SSD and readout</h1><p>Completed groups: $done / $total. Numerical failures: $failed. ADC accepted: $accepted.</p><p>"*N.escape(status)*"</p><pre>"*N.escape(JSON.json(p,2))*"</pre><p>Closing this page does not stop computation. STOP_AFTER_GROUP requests safe pause. Original source transport is never rerun.</p>"
    atomic_write(io->write(io,page),joinpath(out,"progress.html");replace=true)
end
function response(model,e,g,sim,cfg,profile,cal,M,eion,confighash,linehash)
    byrow=Dict(s["raw_row_index"]=>s for s in e["steps"])
    event=Dict("event_id"=>e["seed_event_id"],"primary_time_ns"=>g["origin_time_ns"],"steps"=>[byrow[i] for i in g["row_indices"]])
    task=key(model,e,g)
    record=Dict{String,Any}("key"=>task,"input_hash"=>linehash,"config_hash"=>confighash,"event"=>e,"group"=>g,"guard"=>G.provenance(),"status"=>"native_failed","accepted"=>false,"native"=>nothing,"readout"=>nothing,"error"=>nothing)
    guarded=G.attempt(()->B.native_attempt(()->N.native_event(event,sim,cfg,16,2609261),"record"))
    error=guarded.error===nothing ? guarded.result.error : guarded.error
    if error!==nothing
        record["error"]=error
        return record
    end
    native=guarded.result.result;t,q=native.times,native.signal
    check(all(isfinite,q) && first(q)==0,"Invalid cumulative charge")
    r=P.process(t,q,profile.config,eion,cal,M;horizon_ns=g["horizon_ns"])
    check(r["current_balance"]["passed"],"Charge/current balance failed")
    record["status"]="native_completed";record["accepted"]=r["accepted"]
    record["native"]=native;record["readout"]=r;record["transport_flags"]=N.flags(native.steps)
    record
end
function main(out;max_new=typemax(Int))
    out=abspath(out);relative=relpath(out,joinpath(ROOT,".local"));check(!isabspath(relative) && !(".." in splitpath(relative)) && relative!=".","Output outside .local")
    check(Threads.nthreads()==2 && VERSION==v"1.13.0","Pinned two-thread Julia1.13 required")
    configfile=joinpath(out,"config.json");confighash=hashfile(configfile)
    check(strip(read(joinpath(out,"config.sha256"),String))==confighash,"Configuration corrupted")
    c=JSON.parsefile(configfile);pins(c);check(c["kind"]=="native_checkpoint_batch_v1","Wrong input kind")
    check(c["settings"]==Dict("parcels"=>16,"seed_family"=>2609261,"drift_dt_ns"=>2,"drift_cap_ns"=>10000,"temperature_K"=>77),"Unsupported settings")
    check_environment(Q.environment("cpu"),c["expected_environment"]);E.environment()
    check(hashfile(joinpath(out,"profile.json"))==c["profile_sha256"],"Profile mismatch")
    handle=acquire(joinpath(out,"worker.lock"));started=time();completed=0;failed=0;accepted=0;initial=0;new=0
    totals=c["target_groups"];donekeys=Set{String}();dest=joinpath(out,"results");mkpath(dest)
    try
        G.install!()
        # Validate all source rows and completed checkpoints before native work.
        for model in ("AK02","SAP22")
            m=c["models"][model];file=joinpath(out,m["events_file"])
            check(hashfile(file)==m["events_sha256"],"Event stream changed")
            rows=0;groups=0;seen=Set{Tuple{String,Int}}()
            for line in eachline(file)
                e=JSON.parse(line);V.validate_event(e,m["prepared"]);rows+=1
                id=(e["namespace"],e["event_id"]);check(!(id in seen),"Duplicate primary");push!(seen,id)
                lh=bytes2hex(sha256(line))
                for g in e["pulse_groups"]
                    groups+=1;task=key(model,e,g);d=recover(dest,task,lh,confighash)
                    if d!==nothing
                        push!(donekeys,task);completed+=1;failed+=d["status"]=="native_failed";accepted+=d["accepted"]
                    end
                end
            end
            check(rows==m["selected_primaries"] && groups==m["groups"],"Input census mismatch")
        end
        initial=completed;progress(out,"running",completed,totals,failed,accepted,started,initial)
        for model in ("AK02","SAP22")
            m=c["models"][model];cache=joinpath(out,m["cache_file"])
            check(hashfile(cache)==m["cache_sha256"],"Field cache corrupted")
            sim=deserialize(cache);check(N.field_fingerprint(sim)==m["expected_field_fingerprint"],"Cached fields differ from baseline")
            check(sim.detector.semiconductor.temperature==77,"Cached temperature changed")
            B.geometry(m["prepared"],sim,true)
            cfg=Q.parse_args(["--model",model,"--position-mm","3,0,5","--precision","64","--dt-ns","2","--min-grid-mm","0.05","--max-iterations","50000","--output",joinpath(out,"unused-"*model)])
            profile=P.load(joinpath(out,"profile.json"));eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation)
            M=E.transition(profile.config,2.0);cal=P.calibration(profile.config,eion,2.0,M)
            check(cal==m["expected_calibration"],"Injection calibration changed")
            for line in eachline(joinpath(out,m["events_file"]))
                e=JSON.parse(line);R.validate_deposits(Dict("events"=>[e]),sim);lh=bytes2hex(sha256(line))
                for g in e["pulse_groups"]
                    task=key(model,e,g);task in donekeys && continue
                    if new>=max_new || isfile(joinpath(out,"STOP_AFTER_GROUP"))
                        progress(out,"paused",completed,totals,failed,accepted,started,initial);return
                    end
                    progress(out,"running",completed,totals,failed,accepted,started,initial,task)
                    r=response(model,e,g,sim,cfg,profile,cal,M,eion,confighash,lh)
                    d=commit(dest,r);push!(donekeys,task);completed+=1;new+=1
                    failed+=d["status"]=="native_failed";accepted+=d["accepted"]
                    progress(out,"running",completed,totals,failed,accepted,started,initial)
                    println(task," ",d["status"]," ",completed,"/",totals);flush(stdout)
                end
            end
            check(N.field_fingerprint(sim)==m["expected_field_fingerprint"],"Native response mutated fields")
        end
        pins(c);check(hashfile(configfile)==confighash && completed==totals,"Final census/config mismatch")
        status=failed>0 ? "completed_with_native_failures" : "completed_native_response"
        final=Dict("status"=>status,"completed_groups"=>completed,"numerical_failures"=>failed,"accepted"=>accepted,"config_hash"=>confighash,"guard"=>G.provenance(),"finished_utc"=>string(now(UTC)))
        if !isfile(joinpath(out,"COMPLETE.json"));save(joinpath(out,"COMPLETE.json"),final);end
        progress(out,status,completed,totals,failed,accepted,started,initial)
    catch err
        progress(out,"failed",completed,totals,failed,accepted,started,initial,nothing,sprint(showerror,err));rethrow()
    finally
        release(handle)
    end
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    length(ARGS) in (1,2) || error("Usage: native_checkpoint_batch.jl OUTPUT [MAX_NEW_GROUPS]")
    NativeCheckpointBatch.main(ARGS[1];max_new=length(ARGS)==2 ? parse(Int,ARGS[2]) : typemax(Int))
end
