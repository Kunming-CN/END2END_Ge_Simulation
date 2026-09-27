# Additive display-I/O recovery. The checkpointed numerical runner stays byte-identical.
include("native_checkpoint_batch.jl")
module NativeProgressResilience
using ..NativeCheckpointBatch, SHA
const C=NativeCheckpointBatch
const ORIGINAL_SHA="7e5bdafe6767501b01c0bd10afd9a5840f1cdd7e03b1377b4001ec6bc14818a5"
const INSTALLED=Ref(false)
const WARNINGS=Dict{String,Float64}()
sharing_error(e)=e isa Base.IOError && e.code in (Base.UV_EACCES,Base.UV_EPERM,Base.UV_EBUSY)
function note(path,error,temp)
    now=time(); last=get(WARNINGS,path,-Inf)
    if now-last>=60
        @warn "Progress display update deferred; scientific checkpoints remain authoritative" path error=sprint(showerror,error) temporary=temp
        WARNINGS[path]=now
    end
    false
end
function publish(f,path;rename_file=Base.Filesystem.rename,delays=(0.05,0.15))
    basename(path) in ("progress.json","progress.html") || throw(ArgumentError("Display-only writer refuses scientific artifacts"))
    temp=path*".display-$(getpid())-$(time_ns())"
    try
        open(temp,"w") do io; f(io); C.durable(io); end
    catch err
        sharing_error(err) || rethrow()
        return note(path,err,temp)
    end
    for attempt in 1:length(delays)+1
        try
            rename_file(temp,path)
            return true
        catch err
            sharing_error(err) || rethrow()
            attempt>length(delays) && return note(path,err,temp)
            sleep(delays[attempt])
        end
    end
end
function install!()
    INSTALLED[] && return
    file=joinpath(@__DIR__,"native_checkpoint_batch.jl")
    C.hashfile(file)==ORIGINAL_SHA || error("Unsupported runner source; original must remain unchanged")
    source=replace(read(file,String),"\r\n"=>"\n")
    found=match(r"function progress\([\s\S]*?(?=\nfunction response\()",source)
    found===nothing && error("Progress function not found")
    body=found.match
    old="save(joinpath(out,\"progress.json\"),p;replace=true)"
    count(old,body)==1 || error("Unexpected JSON progress writer")
    body=replace(body,old=>"Main.NativeProgressResilience.publish(io->JSON.print(io,p),joinpath(out,\"progress.json\"))")
    old="atomic_write(io->write(io,page),joinpath(out,\"progress.html\");replace=true)"
    count(old,body)==1 || error("Unexpected HTML progress writer")
    body=replace(body,old=>"Main.NativeProgressResilience.publish(io->write(io,page),joinpath(out,\"progress.html\"))")
    # Only progress() is replaced. commit/recover/atomic_write and all physics stay strict.
    Base.include_string(C,body,"native-progress-resilience-v1")
    INSTALLED[]=true
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    length(ARGS) in (1,2) || error("Usage: native_progress_resilience.jl OUTPUT [MAX_NEW_GROUPS]")
    NativeProgressResilience.install!()
    println("Progress-only resilience active; original numerical/checkpoint runner unchanged.");flush(stdout)
    Base.invokelatest(NativeCheckpointBatch.main,ARGS[1];max_new=length(ARGS)==2 ? parse(Int,ARGS[2]) : typemax(Int))
end
