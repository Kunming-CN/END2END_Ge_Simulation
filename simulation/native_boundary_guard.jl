# Opt-in, process-local safety patch for pinned SSD 0.11.8. No package-file edits.
include("native_segment_crossing.jl")
module NativeBoundaryGuard
using SolidStateDetectors, SHA, LinearAlgebra
using ..NativeSegmentCrossing
const SSD=SolidStateDetectors
const EXPECTED="0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad"
const INSTALLED=Ref(false)
const ANALYTIC_SEMICONDUCTOR=Ref(false)
struct BoundaryStall <: Exception
    step::Int
    start_m::NTuple{3,Float64}
    last_valid_m::NTuple{3,Float64}
    rejected_m::NTuple{3,Float64}
    reason::String
end
BoundaryStall(step,start,last,rejected)=BoundaryStall(step,start,last,rejected,"native_linear_backoff_exhausted")
Base.showerror(io::IO,e::BoundaryStall)=print(io,"Native floating-boundary motion unavailable at step ",e.step," (",e.reason,")")
xyz(p)=(Float64(p.x),Float64(p.y),Float64(p.z))
function projected_surface_step(det,point_types,current,projected,istep,start)
    next=current+projected
    next in det.semiconductor && return next,one(typeof(current.x))
    # A projected step can meet a second face/contact before its full endpoint.
    # Reuse SSD's exact CSG segment crossing instead of a 0.001 backoff grid.
    crossing,kind,_=NativeSegmentCrossing.get_crossing_pos(det,point_types,current,next)
    denominator=dot(projected,projected)
    fraction=dot(crossing-current,projected)/denominator
    if kind==SSD.CD_OUTSIDE || !(isfinite(fraction) && 0<fraction<=1 && crossing in det.semiconductor)
        reason=kind==SSD.CD_OUTSIDE ? "no_projected_segment_crossing" :
            !(isfinite(fraction) && 0<fraction<=1) ? "no_positive_projected_motion" : "projected_crossing_outside_semiconductor"
        throw(BoundaryStall(istep,xyz(start),xyz(current),xyz(next),reason))
    end
    crossing,fraction
end
function patched_source(source::String;analytic_semiconductor=false)
    source=replace(source,"\r\n"=>"\n")
    body=match(r"function _check_and_update_position!\([\s\S]*?(?=\n\nfunction _drift_charge!\()",source)
    body===nothing && throw(ArgumentError("Pinned native function not found"))
    old="                if i == 1000\n"
    count(old,body.match)==1 || throw(ArgumentError("Native boundary branch changed"))
    replacement=old*"                    throw(Main.NativeBoundaryGuard.BoundaryStall(istep, Main.NativeBoundaryGuard.xyz(startpos[n]), Main.NativeBoundaryGuard.xyz(current_pos[n]), Main.NativeBoundaryGuard.xyz(next_pos)))\n"
    text=replace(body.match,old=>replacement;count=1)
    if analytic_semiconductor
        native_crossing="get_crossing_pos(det, point_types, copy(current_pos[n]), current_pos[n] + step_vectors[n])"
        count(native_crossing,text)==1 || throw(ArgumentError("Pinned native crossing call changed"))
        text=replace(text,native_crossing=>"Main.NativeSegmentCrossing."*native_crossing;count=1)
        native_projection="CartesianVector{T}(project_to_plane(step_vectors[n], surface_normal))"
        count(native_projection,text)==1 || throw(ArgumentError("Pinned native surface projection changed"))
        text=replace(text,native_projection=>"Main.NativeSegmentCrossing.surface_step(det, current_pos[n], step_vectors[n], surface_normal)";count=1)
        old="normal[n] = done[n] || _is_next_point_in_det(current_pos[n]+step_vectors[n], det, point_types)"
        count(old,text)==1 || throw(ArgumentError("Pinned native next-point admission changed"))
        text=replace(text,old=>"normal[n] = done[n] || ((current_pos[n]+step_vectors[n]) in det.semiconductor && !((current_pos[n]+step_vectors[n]) in det.contacts))";count=1)
        backoff=match(r"                next_pos::CartesianPoint\{T\} = current_pos\[n\] \+ projected_vector[\s\S]*?                current_pos\[n\] = next_pos",text)
        backoff===nothing && throw(ArgumentError("Pinned native projection backoff changed"))
        replacement="""                next_pos, fraction = Main.NativeBoundaryGuard.projected_surface_step(det, point_types, current_pos[n], projected_vector, istep, startpos[n])
                drift_path[n,istep] = next_pos
                step_vectors *= fraction
                Δt *= fraction
                done[n] = next_pos == current_pos[n]
                current_pos[n] = next_pos"""
        text=replace(text,backoff.match=>replacement;count=1)
    end
    text
end
function install!(;analytic_semiconductor=false)
    if INSTALLED[]
        ANALYTIC_SEMICONDUCTOR[]==analytic_semiconductor || throw(ArgumentError("Native boundary policy changed in a live process"))
        return provenance()
    end
    path=joinpath(dirname(pathof(SSD)),"ChargeDrift","ChargeDrift.jl")
    bytes2hex(sha256(read(path)))==EXPECTED || throw(ArgumentError("Unsupported native drift source; no silent patch"))
    Base.include_string(SSD,patched_source(read(path,String);analytic_semiconductor),"native-boundary-guard-v1")
    ANALYTIC_SEMICONDUCTOR[]=analytic_semiconductor
    INSTALLED[]=true
    provenance()
end
function provenance()
    Dict("kind"=>"ssd_0_11_8_boundary_guard_v1","installed"=>INSTALLED[],"native_source_sha256"=>EXPECTED,
        "change"=>"Fail closed before native unwritten terminal row; no position/signal substitution",
        "package_files_modified"=>false,"next_point_admission"=>ANALYTIC_SEMICONDUCTOR[] ? "analytic_semiconductor" : "native_grid_or_geometry",
        "floating_projection"=>ANALYTIC_SEMICONDUCTOR[] ? "analytic_projected_segment_crossing_v5_conditioned_rear_hit" : "native_linear_backoff_with_unwritten_row_guard")
end
function detail(e::BoundaryStall)
    Dict("type"=>"NativeBoundaryStall","message"=>sprint(showerror,e),"step"=>e.step,
        "reason"=>e.reason,
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
