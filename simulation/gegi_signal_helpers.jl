# Numerical helpers shared by the GeGI worker and bounded tests; no field solve.
module GeGISignalHelpers
check(ok, msg) = ok ? nothing : throw(ArgumentError(msg))
finite(x) = x isa Real && !(x isa Bool) && isfinite(x)

"""Last rising constant-fraction crossing of a signed, polarity-corrected charge.
The terminal charge is the reference, not deposited truth energy. Null denotes
no positive terminal collection; callers independently impose channel thresholds.
An early transient can cross and then fall below the threshold. The last upward
crossing selects the final rise that stays above it through the recorded endpoint.
This is an ideal-charge estimator, not a calibrated hardware timing discriminator.
"""
function crossing_time(t, q, fraction=0.5)
    check(length(t)==length(q) && length(t)>=2, "Invalid timing samples")
    check(all(finite,t) && all(finite,q) && all(diff(t).>0), "Invalid timing support")
    check(0<fraction<1, "Timing fraction must be inside (0,1)")
    last(q)>0 || return nothing
    target=fraction*last(q)
    for k in length(t):-1:2
        if q[k-1]<target<=q[k]
            return t[k-1]+(target-q[k-1])/(q[k]-q[k-1])*(t[k]-t[k-1])
        end
    end
    nothing
end

function channel_metadata(config)
    contacts=config["detectors"][1]["contacts"]
    check(length(contacts)==34, "GeGI requires 32 strips and two guard contacts")
    channels=Dict{String,Any}[]
    for c in contacts
        id=c["id"]; name=c["name"]
        family=id<=17 ? "X" : "Y"
        strip=id<=16 ? id : 18<=id<=33 ? id-17 : nothing
        expected=strip===nothing ? family*"_guard" : family*lpad(string(strip),2,'0')
        check(name==expected, "Unexpected GeGI contact map")
        check(c["potential"]==(family=="X" ? -879.0 : 0.0), "GeGI canonical bias changed")
        origin=strip===nothing ? nothing : c["geometry"]["intersection"][2]["box"]["origin"]
        push!(channels,Dict("id"=>id,"name"=>name,"family"=>family,
            "strip_index"=>strip,"guard"=>strip===nothing,"potential_V"=>c["potential"],
            "wiring_factor"=>family=="X" ? 1 : -1,
            "strip_center_mm"=>origin===nothing ? nothing : origin[family=="X" ? 1 : 2],
            "face_z_mm"=>family=="X" ? 5.5 : -5.5))
    end
    check([c["id"] for c in channels]==collect(1:34), "GeGI contact IDs must be contiguous")
    channels
end

function monotonic_depth_table(depth, ctd)
    check(length(depth)==length(ctd) && length(depth)>=3, "Invalid depth calibration dimensions")
    check(all(finite,depth) && all(diff(depth).>0), "Invalid depth grid")
    all(finite,ctd) || return false
    delta=diff(ctd)
    all(delta.>0) || all(delta.<0)
end
end
