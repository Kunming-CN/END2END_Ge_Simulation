# Opt-in, process-local safety patch for pinned SSD 0.11.8. No package-file edits.
module NativeBoundaryGuard
using SolidStateDetectors, SHA
const SSD=SolidStateDetectors
const EXPECTED="0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad"
const INSTALLED=Ref(false)
struct BoundaryStall <: Exception
    step::Int
    start_m::NTuple{3,Float64}
    last_valid_m::NTuple{3,Float64}
    rejected_m::NTuple{3,Float64}
end
Base.showerror(io::IO,e::BoundaryStall)=print(io,"Native floating-boundary projection exhausted; unwritten path row refused at step ",e.step)
xyz(p)=(Float64(p.x),Float64(p.y),Float64(p.z))
function patched_source(source::String)
    source=replace(source,"\r\n"=>"\n")
    body=match(r"function _check_and_update_position!\([\s\S]*?(?=\n\nfunction _drift_charge!\()",source)
    body===nothing && throw(ArgumentError("Pinned native function not found"))
    old="                if i == 1000\n"
    count(old,body.match)==1 || throw(ArgumentError("Native boundary branch changed"))
    replacement=old*"                    throw(Main.NativeBoundaryGuard.BoundaryStall(istep, Main.NativeBoundaryGuard.xyz(startpos[n]), Main.NativeBoundaryGuard.xyz(current_pos[n]), Main.NativeBoundaryGuard.xyz(next_pos)))\n"
    replace(body.match,old=>replacement;count=1)
end
function install!()
    INSTALLED[] && return provenance()
    path=joinpath(dirname(pathof(SSD)),"ChargeDrift","ChargeDrift.jl")
    bytes2hex(sha256(read(path)))==EXPECTED || throw(ArgumentError("Unsupported native drift source; no silent patch"))
    Base.include_string(SSD,patched_source(read(path,String)),"native-boundary-guard-v1")
    INSTALLED[]=true
    provenance()
end
function provenance()
    Dict("kind"=>"ssd_0_11_8_boundary_guard_v1","installed"=>INSTALLED[],"native_source_sha256"=>EXPECTED,
        "change"=>"Fail closed before native unwritten terminal row; no position/signal substitution",
        "package_files_modified"=>false)
end
function detail(e::BoundaryStall)
    Dict("type"=>"NativeBoundaryStall","message"=>sprint(showerror,e),"step"=>e.step,
        "start_position_m"=>collect(e.start_m),"last_valid_position_m"=>collect(e.last_valid_m),
        "rejected_position_m"=>collect(e.rejected_m),"charge_unknown"=>true)
end
function attempt(f)
    try
        (result=Base.invokelatest(f),error=nothing)
    catch e
        e isa BoundaryStall || rethrow()
        (result=nothing,error=detail(e))
    end
end
end
