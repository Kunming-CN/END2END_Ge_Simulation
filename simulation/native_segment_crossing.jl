# Geometry correction for pinned SSD 0.11.8, used only in analytic boundary mode.
module NativeSegmentCrossing
using SolidStateDetectors, LinearAlgebra
const SSD=SolidStateDetectors
const CSG=SSD.ConstructiveSolidGeometry

function active_inward_normals(det,p::SSD.CartesianPoint{T}) where T
    tol=CSG.csg_default_tol(T);probe=T(5000)*tol
    normals=SSD.CartesianVector{T}[]
    for surface in CSG.surfaces(det.semiconductor.geometry)
        CSG.distance_to_surface(p,surface)<=tol || continue
        n=normalize(CSG.normal(surface,p))
        p+probe*n in det.semiconductor && !(p-probe*n in det.semiconductor) || continue
        n in normals || push!(normals,n)
    end
    normals
end

"""Nearest field step satisfying all active inward halfspaces at an intersection.

In three dimensions the closest feasible vector is either the original vector,
a projection onto one plane, a projection onto a pair's intersection line, or
zero. Enumerating those finite candidates avoids changing fields or timesteps.
Single-face motion retains SSD's exact operation. Contact classification is not
part of this projection; zero motion still cannot establish collection.
"""
function surface_step(det,p::SSD.CartesianPoint{T},step::SSD.CartesianVector{T},normal) where T
    original=SSD.CartesianVector{T}(SSD.project_to_plane(step,normal))
    normals=active_inward_normals(det,p)
    length(normals)>=2 && normal in normals || return original
    tol=CSG.csg_default_tol(T)
    feasible(v)=all(n->dot(n,v)>=-tol,normals)
    feasible(step) && return step
    feasible(original) && return original
    best=zero(step);retained=zero(T)
    candidates=SSD.CartesianVector{T}[step]
    append!(candidates,[SSD.CartesianVector{T}(SSD.project_to_plane(step,n)) for n in normals])
    for i in eachindex(normals),j in i+1:length(normals)
        direction=cross(normals[i],normals[j])
        iszero(norm(direction)) && continue
        direction=normalize(direction)
        push!(candidates,SSD.CartesianVector{T}(direction*dot(direction,step)))
    end
    for candidate in candidates
        feasible(candidate) || continue
        # Each candidate is an orthogonal projection of step. Maximizing its
        # retained norm is equivalent to minimizing the rejected norm, without
        # subtracting nearly equal normal components when tangent motion is tiny.
        candidate_retained=dot(candidate,candidate)
        if candidate_retained>retained
            best=candidate;retained=candidate_retained
        end
    end
    best
end

"""Retain native crossings except a tangent self-hit or a roundoff-sized rear hit.

Use the installed CSG tolerance in metres. Contact intersections, the native
single-normal membership probes, and point-type classification stay unchanged.
This returns geometry only: a zero-distance outward corner is not collection.
"""
function get_crossing_pos(det,point_types,a::SSD.CartesianPoint{T},b::SSD.CartesianPoint{T}) where T
    original=SSD.get_crossing_pos(det,point_types,a,b)
    p,kind,normal=original
    segment=b-a;distance=norm(segment);tol=CSG.csg_default_tol(T)
    tangent_self=kind==SSD.CD_FLOATING_BOUNDARY && norm(p-a)<=tol && abs(dot(normal,segment))<=tol
    (tangent_self || kind==SSD.CD_OUTSIDE) && distance>0 || return original

    # The native contact scan has already run. Revisit semiconductor surfaces
    # only; do not widen contact membership or change its priority.
    direction=normalize(segment);line=CSG.Line{T}(a,direction)
    best=(b,SSD.CD_OUTSIDE,zero(SSD.CartesianVector{T}))
    probe=T(5000)*tol # exact installed SSD single-normal membership convention
    for surface in CSG.surfaces(det.semiconductor.geometry)
        for hit in CSG.intersection(surface,line)
            n=normalize(CSG.normal(surface,hit))
            hit+probe*n in det.semiconductor && !(hit-probe*n in det.semiconductor) || continue
            delta=hit-a;signed=dot(delta,direction);length=norm(delta)
            normal_motion=dot(n,segment)
            length<=tol && abs(normal_motion)<=tol && continue
            if -tol<=signed<0 && length<=tol && normal_motion < -tol
                # A surface hit a few ulps behind an outward-moving boundary
                # start represents that start, not a backwards path increment.
                hit=a;signed=zero(T);length=zero(T)
            end
            if 0<=signed<=1 && length<norm(best[1]-a)
                type=point_types[hit] & SSD.update_bit==0 ? SSD.CD_ELECTRODE : SSD.CD_FLOATING_BOUNDARY
                best=(hit,type,n)
            end
        end
    end
    best[2]==SSD.CD_OUTSIDE ? original : best
end
end
