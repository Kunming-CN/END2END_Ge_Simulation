# Catalog source admission reuses frozen raw-event validators; each event stays streamed.
isdefined(@__MODULE__, :DecayStream) || include("decay_stream.jl")
isdefined(@__MODULE__, :CatalogNativeModel) || include("catalog_native_model.jl")
module CatalogDecayStream
using ..DecayStream, ..CatalogNativeModel, JSON
const D=DecayStream;const S=D.S;const C=CatalogNativeModel;const ROOT=D.ROOT
const KIND="catalog_decay_stream_v1";const ADAPTER="catalog_source_v1"
const check=S.check;const recheck=S.recheck
function inspect(path)
    path=S.localfile(path);base=dirname(path);m=JSON.parsefile(path);pins=Dict(path=>S.hashfile(path))
    check(m["kind"]==KIND && m["status"]=="complete" && m["producer_adapter"]==ADAPTER,"Incomplete/wrong catalog source stream")
    n=m["primary_count"];check(S.integer(n) && n in (20,500) && m["global_decay_id_range"]==[0,n-1],"Wrong catalog source census")
    C.validate_model(m["model_contract"];require_placement=true)
    check(m["model_contract"]["model_id"]==m["model_id"] && m["model_contract"]["model_sha256"]==m["model_sha256"],"Changed catalog model binding")
    check(m["source_mode"] in ("cs137_legacy","registered_decay"),"Unknown source physics policy")
    if m["source_mode"]=="registered_decay";D.source_contract(m["source_id"],m["source_contract"],pins)
    else
        registry=D.relative_file(D.REGISTRY_REF);pins[registry]=S.hashfile(registry)
        p=only(filter(x->x["id"]=="cs137_point_decay_v1",JSON.parsefile(registry)["presets"]))
        check(m["source_id"]==p["id"] && D.exact_equal(m["source_contract"],p),"Changed Cs137 source contract")
    end
    check(m["units"]==Dict("energy"=>"keV","length"=>"mm","time"=>"ns") && m["raw_track_energy_unit"]=="MeV" && m["raw_position_unit"]=="m","Changed source units")
    S.transform(m["coordinate_transform"])
    check(m["source_lh5"]=="../truth.lh5" && m["clock_policy"]=="remage_initial_decay_secondaries_zero","Changed source raw/clock location")
    S.pin!(pins,joinpath(base,m["source_lh5"]),m["source_lh5_sha256"])
    for (name,key) in (("prepared.json","prepared_sha256"),("run.json","run_sha256"),("scenario.json","config_sha256"),("geometry.gdml","geometry_sha256"),("run.mac","macro_sha256"));S.pin!(pins,joinpath(base,"..",name),m[key]);end
    p=JSON.parsefile(joinpath(base,"..","prepared.json"));run=JSON.parsefile(joinpath(base,"..","run.json"))
    check(p["kind"]=="catalog_source_prepared_v1" && p["producer_adapter"]==ADAPTER && run["status"]=="complete" && run["prepared_sha256"]==m["prepared_sha256"] && run["source_lh5_sha256"]==m["source_lh5_sha256"],"Changed native preparation/transport authority")
    for k in ("model_id","model_sha256","model_contract","source_id","source_contract","source_mode","primary_count","coordinate_transform","clock_policy","grouping_policy")
        check(m[k]==p[k],"Catalog stream/prepared mismatch: "*k)
    end
    for (ref,h) in p["files_sha256"]
        check(ref isa String && !isabspath(ref) && !occursin('\\',ref) && !(".." in split(ref,'/')),"Unsafe native input reference")
        S.pin!(pins,joinpath(base,"..",split(ref,'/')...),h)
    end
    check(p["geometry_checks"]["overlaps_passed"]===true && p["geometry_checks"]["source_inside_fill"]===true,"Native cryostat/source geometry failed")
    policy=m["grouping_policy"];check(policy["name"]=="nominal_isolated_windows_v1" && policy["interval"]=="[origin, origin+horizon)" && policy["state_at_group_start"]=="reset" && policy["activity_live_time_pileup_claim"]===false,"Changed isolated-window grouping")
    S.groups(Any[],policy["horizon_ns"])
    check(m["ledger"]["kind"]=="recorded-only" && m["ledger"]["full_energy_closure"]===nothing,"Unsupported energy closure claim")
    tables=m["raw_tables"];check(Set(keys(tables))==union(Set(("vtx","particles","tracks","processes")),Set(keys(p["material_tables"]))),"Incomplete raw table census")
    for spec in values(tables);check(S.integer(spec["rows"]) && spec["rows"]>=0 && spec["columns"] isa AbstractDict && !isempty(spec["columns"]),"Invalid raw table descriptor");end
    check(length(m["processes"])==tables["processes"]["rows"],"Process census mismatch")
    for (i,row) in enumerate(m["processes"]);check(row["raw_row_index"]==i-1 && Set(keys(row))==union(Set(keys(tables["processes"]["columns"])),Set(["raw_row_index"])),"Changed raw process row");end
    expected=0;names=Set{String}()
    for c in m["chunks"]
        name=c["file"];check(basename(name)==name && !(name in names) && endswith(name,".jsonl"),"Unsafe/repeated chunk")
        check(S.integer(c["count"]) && 1<=c["count"]<=100 && c["first_global_decay_id"]==expected,"Changed source extraction chunk mapping")
        push!(names,name);S.pin!(pins,joinpath(base,name),c["sha256"]);expected+=c["count"]
    end
    check(expected==n,"Incomplete source ledger")
    (path=path,manifest=m,prepared=p,pins=pins)
end
function foreach_decay(f,input)
    (input.manifest["source_mode"]=="registered_decay" ? D : S).foreach_decay(f,input)
end
end
