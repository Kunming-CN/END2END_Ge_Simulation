# Additive batch identity and checked byte-consumption rules; no science modules.
module BatchNativeContract
using SHA, Serialization
const SEED_RULE="native_global_initial_row_parcel_sha256_v1"
const MAX_SAFE_INTEGER=9_007_199_254_740_991
const MAX_CACHE_BYTES=512*1024^2
check(x,m)=x || throw(ArgumentError(m))
integer(x)=x isa Integer && !(x isa Bool)
const POSE_KIND="source_capsule_angular_pose_v1"
const POSE_CONVENTION="degrees from global +y toward +x about axis x=0,y=1.473mm; local +z follows outward radius; z fixed"
function angle(s)
    a=get(s,"angle_deg",0)
    check(a isa Real && !(a isa Bool) && isfinite(a) && -30<=a<=30,"Unsupported source angle; choose a finite number from -30 to +30 degrees")
    check(get(s,"source",nothing)!="mono_gamma_662_axis_v1" || a==0,"Legacy gamma source position is fixed")
    a
end
function source_pose(p,s,anchor_hash)
    a=angle(s)
    if a==0
        check(!haskey(p,"source_pose") && p["source_position_global_mm"]==[0,37.073,0.290],"Legacy nominal source pose changed")
        return nothing
    end
    pose=p["source_pose"]
    fields=Set(("kind","schema_version","angle_deg","position_global_mm","capsule_rotation_local_to_global","capsule_axis_global","coordinate_convention","anchors_sha256"))
    check(pose isa AbstractDict && Set(keys(pose))==fields && pose["kind"]==POSE_KIND && integer(pose["schema_version"]) && pose["schema_version"]==1 && angle(pose)==a && pose["anchors_sha256"]==anchor_hash && pose["coordinate_convention"]==POSE_CONVENTION,"Changed angular source identity/anchor/convention")
    sn=sin(deg2rad(a));cs=cos(deg2rad(a))
    position=[35.6sn,1.473+35.6cs,0.290];axis=[sn,cs,0.0];rotation=[[cs,0.0,sn],[-sn,0.0,cs],[0.0,-1.0,0.0]]
    vector_ok(x,y)=x isa AbstractVector && length(x)==length(y) && all(v->v isa Real && !(v isa Bool) && isfinite(v),x) && all(isapprox(u,v;rtol=0,atol=1e-12) for (u,v) in zip(x,y))
    matrix_ok(x,y)=x isa AbstractVector && length(x)==3 && all(vector_ok(u,v) for (u,v) in zip(x,y))
    check(vector_ok(pose["position_global_mm"],position) && vector_ok(pose["capsule_axis_global"],axis) && matrix_ok(pose["capsule_rotation_local_to_global"],rotation) && p["source_position_global_mm"]==pose["position_global_mm"],"Changed angular source position/rotation")
    checked=p["checked_transport"]
    check(checked["source_pose"]==pose && checked["angle_geometry_plan"]["source_pose"]==pose,"Angular preparation differs from checked pose")
    report=p["geometry_checks"]
    check(report["source_inside_fill"]===true && report["overlaps_passed"]===true,"Angular geometry is unchecked")
    for (name,material) in (("nominal_capsule","G4_Al"),("nominal_source_fill","G4_POLYETHYLENE"))
        nodes=filter(v->endswith(v["original_path"],"/"*name),report["volumes"])
        check(length(nodes)==1,"Angular capsule/fill identity is ambiguous")
        node=only(nodes)
        check(node["material"]==material && vector_ok(node["translation_global_mm"],position) && matrix_ok(node["rotation_local_to_global"],rotation),"Native angular capsule/fill placement differs")
    end
    pose
end
function descriptor(b)
    fields=Set(("batch_index","global_initial_offset","primary_count","local_initial_primary_id_range","global_initial_primary_id_range","radiation_seed"))
    check(b isa AbstractDict && Set(keys(b))==fields,"Wrong native batch descriptor fields")
    check(integer(b["batch_index"]) && 0<=b["batch_index"]<2_147_483_646,"Invalid batch index")
    check(integer(b["primary_count"]) && 1<=b["primary_count"]<=10000,"Invalid native batch count")
    o=b["global_initial_offset"];n=b["primary_count"]
    check(integer(o) && 0<=o<=MAX_SAFE_INTEGER-n,"Invalid global initial offset")
    ranges=(b["local_initial_primary_id_range"],b["global_initial_primary_id_range"])
    check(all(r->r isa AbstractVector && length(r)==2 && all(integer,r),ranges) &&
        ranges[1]==[0,n-1] && ranges[2]==[o,o+n-1],"Invalid native identity ranges")
    check(integer(b["radiation_seed"]) && 1<=b["radiation_seed"]<=2_147_483_646,"Invalid radiation seed")
    b
end
function identity(e,b)
    descriptor(b);localid=get(e,"event_id",nothing)
    check(integer(localid) && 0<=localid<b["primary_count"] && get(e,"global_decay_id",nothing)==localid,"Invalid raw local initial identity")
    expected=Dict("batch_index"=>b["batch_index"],"local_initial_id"=>localid,"global_initial_id"=>b["global_initial_offset"]+localid)
    check(all(get(e,k,nothing)==v && integer(get(e,k,nothing)) for (k,v) in expected),"Changed batch/global initial identity")
    merge(Dict("event_id"=>localid,"global_decay_id"=>localid),expected)
end
function parcel_seed(family,globalid,row,parcel)
    check(integer(family) && family==2609261 && integer(globalid) && 0<=globalid<=MAX_SAFE_INTEGER &&
        integer(row) && 0<=row<=MAX_SAFE_INTEGER && integer(parcel) && 1<=parcel<=16,"Invalid global native seed input")
    bytes=sha256(string(family,'/',globalid,'/',row,'/',parcel))
    foldl((value,b)->(value<<8)|UInt64(b),bytes[1:8];init=UInt64(0))
end
# Only this transient input's event_id is global. The original event is retained unchanged.
function native_event_input(e,g,b)
    ids=identity(e,b);byrow=Dict(s["raw_row_index"]=>s for s in e["steps"])
    Dict("event_id"=>ids["global_initial_id"],"primary_time_ns"=>g["origin_time_ns"],"steps"=>[byrow[i] for i in g["row_indices"]])
end
function verified_deserialize(raw,expected;deserialize_fn=deserialize)
    check(raw isa Vector{UInt8} && 0<length(raw)<=MAX_CACHE_BYTES,"Missing/oversized native state bytes")
    check(expected isa String && occursin(r"^[0-9a-f]{64}$",expected) && bytes2hex(sha256(raw))==expected,"Consumed native state hash mismatch")
    deserialize_fn(IOBuffer(raw))
end
end
