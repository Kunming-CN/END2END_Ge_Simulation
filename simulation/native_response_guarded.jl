# Opt-in guarded entry for new native-response campaigns; legacy entry remains unchanged.
include("native_boundary_guard.jl")
include("native_response.jl")
module GuardedNativeResponse
using ..NativeBoundaryGuard, ..NativeResponse, SHA
const G=NativeBoundaryGuard
const R=NativeResponse
const ROOT=R.Q.ROOT
hashfile(p)=open(io->bytes2hex(sha256(io)),p)

function guarded_attempt(f,policy)
    policy in ("abort","record") || throw(ArgumentError("Invalid native failure policy"))
    if policy=="abort"
        return (result=Base.invokelatest(f),error=nothing)
    end
    try
        guarded=G.attempt(f)
        return (result=guarded.result,error=guarded.error)
    catch err
        if err isa ArgumentError && err.msg in R.NATIVE_FAILURE_MESSAGES
            return (result=nothing,error=Dict("type"=>string(typeof(err)),"message"=>err.msg,
                "exact_error"=>sprint(showerror,err),"stage"=>"NativeLiExample.native_event"))
        end
        rethrow()
    end
end

function install_attempt!()
    @eval NativeResponse begin
        function native_attempt(f,policy)
            Main.GuardedNativeResponse.guarded_attempt(f,policy)
        end
    end
end
function main(args=ARGS)
    options=R.options(args)
    guard=G.install!()
    install_attempt!()
    result=Base.invokelatest(R.main,args)
    if result isa AbstractDict && !options["inspect"]
        out=abspath(options["output"])
        R.R.check(R.Q.childof(out,joinpath(ROOT,".local")),"Guarded output must remain below project .local")
        result["boundary_guard"]=guard
        result["guard_wrapper_sha256"]=hashfile(@__FILE__)
        result["guard_source_sha256"]=hashfile(joinpath(@__DIR__,"native_boundary_guard.jl"))
        result["source_sha256"]["native_response_guarded.jl"]=result["guard_wrapper_sha256"]
        result["source_sha256"]["native_boundary_guard.jl"]=result["guard_source_sha256"]
        R.E.save(joinpath(out,"run.json"),result)
    end
    result
end
end
if abspath(PROGRAM_FILE)==@__FILE__; GuardedNativeResponse.main(); end
