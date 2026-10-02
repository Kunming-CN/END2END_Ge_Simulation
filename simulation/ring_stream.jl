# Additive authority for ring campaigns; reuse the original complete-row validator.
isdefined(@__MODULE__, :NativeStream) || include("native_stream.jl")
module RingStream
using ..NativeStream, JSON, SHA
const S=NativeStream
const ROOT=dirname(@__DIR__)
const MODEL_PINS=Dict("GeRC02"=>"7a655caeb660c07df8fcd9af51cc0998daea15f16e31f9c6afcacb89daf39218",
    "KMRC01_candidate"=>"d4258a3b9f9c041b4da1998ded6b373833169ddcc76079f0a588785efe68b6b6")
const BASE_SOURCES=Set(("cs137.py","cryostat_export.cc","cryostat_nominal.json","handoff.py","cryostat-source.json","pixi.toml","pixi.lock","CMakeLists.txt"))
check(x,m)=S.check(x,m)
function relative_file(ref)
    check(ref isa String && !isempty(ref) && !occursin('\\',ref) && !isabspath(ref) && !(".." in split(ref,'/')),"Unsafe project file reference")
    p=joinpath(ROOT,split(ref,'/')...)
    check(isfile(p) && realpath(p)==abspath(p),"Missing/linked project file")
    p
end
function pin!(pins,p,digest)
    check(digest isa String && occursin(r"^[0-9a-f]{64}$",digest) && S.hashfile(p)==digest,"Ring dependency checksum mismatch: "*basename(p))
    pins[p]=digest;p
end
function model_contract(c,pins=Dict{String,String}())
    check(c isa AbstractDict && get(c,"kind",nothing)=="ring_effective_model_v1","Wrong ring model contract")
    id=c["model_id"];check(haskey(MODEL_PINS,id),"Unsupported ring identity")
    source=relative_file("models/"*id*".yaml")
    check(c["source_model_ref"]=="models/"*id*".yaml" && c["source_model_sha256"]==MODEL_PINS[id],"Wrong frozen ring identity")
    pin!(pins,source,MODEL_PINS[id]); original=read(source,String)
    expected=original
    if id=="GeRC02"
        token="lithium_annealing_time: 30minute"
        check(length(findall(token,original))==1 && !occursin("lithium_annealing_time: 50minute",original),"Nonunique Li-time delta")
        expected=replace(original,token=>"lithium_annealing_time: 50minute";count=1)
        check(c["variant_id"]=="GeRC02_Li50min" && c["model_delta"]==Dict("path"=>"detectors[0].semiconductor.impurity_density.lithium_annealing_time","from"=>"30minute","to"=>"50minute") && c["annealing_temperature_K"]==553.15 && c["annealing_time_minutes"]==50,"Wrong authorized Li variant")
        check(startswith(c["effective_model_ref"],".local/"),"Li variant must stay below .local")
    else
        check(c["variant_id"]==id && c["model_delta"]===nothing && c["annealing_temperature_K"]===nothing && c["annealing_time_minutes"]===nothing && c["effective_model_ref"]=="models/"*id*".yaml","KM model must stay unchanged")
    end
    effective=relative_file(c["effective_model_ref"])
    check(read(effective,String)==expected,"Unauthorized effective-model byte change")
    pin!(pins,effective,c["effective_model_sha256"])
    catalog=JSON.parsefile(joinpath(ROOT,"models/catalog.json"))
    entry=only(filter(x->x["id"]==id,catalog["detectors"]))
    deps=Dict("models/"*r=>only(filter(x->x["path"]==r,catalog["dependencies"]))["sha256"] for r in entry["dependencies"])
    check(c["dependencies_sha256"]==deps && entry["model_sha256"]==MODEL_PINS[id],"Ring dependency/catalog mismatch")
    for (ref,digest) in deps;pin!(pins,relative_file(ref),digest);end
    check(c["stored_temperature_K"]==78 && c["runtime_temperature_K"]==77 && c["readout_contact_id"]==1 && c["geometry_unchanged"]===true,"Ring operating convention changed")
    check(c["contact_potentials_V"]==Dict("1"=>0,"2"=>id=="GeRC02" ? 240 : -370),"Ring polarity/bias changed")
    effective
end
function inspect(path)
    path=S.localfile(path);base=dirname(path);m=JSON.parsefile(path);pins=Dict(path=>S.hashfile(path))
    check(m["kind"]==S.KIND && m["status"]=="complete" && m["producer_adapter"]=="ring_cs137_v1","Incomplete/non-ring stream")
    n=m["primary_count"];check(S.integer(n) && 1<=n<=100000 && m["global_decay_id_range"]==[0,n-1],"Invalid ring census")
    check(m["model_id"] in keys(MODEL_PINS) && m["model_sha256"]==MODEL_PINS[m["model_id"]],"Wrong source ring model")
    check(m["units"]==Dict("energy"=>"keV","length"=>"mm","time"=>"ns") && m["raw_track_energy_unit"]=="MeV" && m["raw_position_unit"]=="m","Wrong ring units")
    S.transform(m["coordinate_transform"])
    check(m["clock_policy"]=="remage_initial_decay_secondaries_zero" && m["source_lh5"]=="../truth.lh5","Wrong source/clock contract")
    S.pin!(pins,joinpath(base,m["source_lh5"]),m["source_lh5_sha256"])
    for (name,key) in (("prepared.json","prepared_sha256"),("run.json","run_sha256"),("scenario.json","config_sha256"),("geometry.gdml","geometry_sha256"),("run.mac","macro_sha256"))
        S.pin!(pins,joinpath(base,"..",name),m[key])
    end
    prepared=JSON.parsefile(joinpath(base,"..","prepared.json"));run=JSON.parsefile(joinpath(base,"..","run.json"))
    check(prepared["kind"]=="ring_cs137_prepared_v1" && prepared["producer_adapter"]=="ring_cs137_v1" && prepared["source_pdg"]==1000551370,"Wrong prepared ring ion contract")
    check(run["status"]=="complete" && run["prepared_sha256"]==m["prepared_sha256"] && run["source_lh5_sha256"]==m["source_lh5_sha256"],"Unmatched ring transport")
    for key in ("model_id","model_sha256","primary_count","coordinate_transform","grouping_policy","clock_policy","source_sha256","ring_source_sha256","model_contract","decay_photon_line_window_keV")
        check(m[key]==prepared[key],"Prepared/ring-stream mismatch: "*key)
    end
    check(m["model_contract"]["model_id"]==m["model_id"] && m["model_contract"]["source_model_sha256"]==m["model_sha256"],"Effective/source ring binding mismatch")
    model_contract(m["model_contract"],pins)
    for (name,digest) in prepared["files_sha256"]
        check(name isa String && !isabspath(name) && !occursin('\\',name) && !(".." in split(name,'/')),"Unsafe prepared relative name")
        S.pin!(pins,joinpath(base,"..",split(name,'/')...),digest)
    end
    check(Set(keys(m["source_sha256"]))==BASE_SOURCES,"Incomplete original producer bindings")
    for (name,digest) in m["source_sha256"];pin!(pins,relative_file("transport/"*name),digest);end
    check(Set(keys(m["ring_source_sha256"]))==Set(("transport/ring_cs137.py","transport/scenario_prepare.py","tools/ring_model_contract.py")),"Incomplete ring adapter bindings")
    for (ref,digest) in m["ring_source_sha256"];pin!(pins,relative_file(ref),digest);end
    upstream=JSON.parsefile(joinpath(ROOT,"transport/cryostat-source.json"))
    check(prepared["upstream_sha256"]==Dict(f["name"]=>f["sha256"] for f in upstream["files"]),"Upstream ring geometry provenance changed")
    for (name,digest) in prepared["upstream_sha256"];S.pin!(pins,joinpath(ROOT,".local/transport/LBNL",name),digest);end
    geometry=JSON.parsefile(joinpath(base,"..","geometry-report.json"))
    check(geometry["overlaps_passed"]===true && geometry["source_inside_fill"]===true,"Ring native geometry check failed")
    ge=only(filter(v->v["name"]=="germanium",geometry["volumes"]))
    rotation,shift=S.transform(m["coordinate_transform"])
    actual_rotation=reduce(vcat,[permutedims(Float64.(v)) for v in ge["rotation_local_to_global"]])
    check(isapprox(actual_rotation,rotation;rtol=0,atol=1e-12) && isapprox(Float64.(ge["translation_global_mm"]),shift;rtol=0,atol=1e-10),"Ring native transform mismatch")
    check(isapprox(geometry["crystal_volume_mm3"],prepared["analytic_volume_mm3"];rtol=1e-10,atol=1e-9),"Independent/native ring volume mismatch")
    policy=m["grouping_policy"]
    check(policy["name"]=="nominal_isolated_windows_v1" && policy["interval"]=="[origin, origin+horizon)" && policy["state_at_group_start"]=="reset" && policy["activity_live_time_pileup_claim"]===false,"Wrong finite-window convention")
    S.groups(Any[],policy["horizon_ns"])
    check(m["decay_photon_line_window_keV"]==[660,663] && m["ledger"]["kind"]=="recorded-only" && m["ledger"]["full_energy_closure"]===nothing,"Wrong ring counting/energy claim")
    tables=m["raw_tables"]
    check(Set(keys(tables))==union(Set(("vtx","particles","tracks","processes")),Set(keys(prepared["material_tables"]))),"Raw ring table census mismatch")
    for spec in values(tables);check(S.integer(spec["rows"]) && spec["rows"]>=0 && spec["columns"] isa AbstractDict && !isempty(spec["columns"]),"Invalid raw ring descriptor");end
    check(length(m["processes"])==tables["processes"]["rows"],"Ring process census mismatch")
    for (i,p) in enumerate(m["processes"]);check(p["raw_row_index"]==i-1 && Set(keys(p))==union(Set(keys(tables["processes"]["columns"])),Set(["raw_row_index"])),"Changed ring process row");end
    expected=0;names=Set{String}()
    for c in m["chunks"]
        name=c["file"];check(basename(name)==name && !(name in names) && endswith(name,".jsonl"),"Invalid/repeated ring chunk")
        check(S.integer(c["count"]) && 1<=c["count"]<=100 && c["first_global_decay_id"]==expected,"Bad ring chunk mapping")
        push!(names,name);S.pin!(pins,joinpath(base,name),c["sha256"]);expected+=c["count"]
    end
    check(expected==n,"Incomplete ring chunk census")
    (path=path,manifest=m,prepared=prepared,pins=pins)
end
end
