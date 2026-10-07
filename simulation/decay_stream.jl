# Registry-driven decay stream authority. Frozen Cs137 readers remain unchanged.
isdefined(@__MODULE__, :RingStream) || include("ring_stream.jl")
isdefined(@__MODULE__, :Sap18Stream) || include("sap18_stream.jl")
module DecayStream
using ..NativeStream, ..RingStream, ..Sap18Stream, JSON
const S=NativeStream;const RS=RingStream;const SS=Sap18Stream;const ROOT=S.ROOT
const KIND="radioactive_decay_stream_v1"
const ADAPTER="shared_decay_source_v1"
const CANONICAL_PINS=Dict("AK02"=>"793de4cc598a3e26d375525e683be1bc2072e117d1c6b8003f6cdcffc9925dfa",
    "SAP22"=>"614c72f31a5a84b82c69b0b11f6f0657e87d94f746312c151f9a08cd00ba3dc3")
const SIGNED_BIAS=Dict("AK02"=>500,"SAP22"=>700,"GeRC02"=>240,"KMRC01_candidate"=>-370,"SAP18_ring08_scenario"=>-380)
const WIRING=Dict(id=>bias<0 ? -1 : 1 for (id,bias) in SIGNED_BIAS)
const REGISTRY_REF="scenarios/source-presets.json"
const ANCHORS_REF="scenarios/placement-anchors.json"
check(x,m)=S.check(x,m)
const hashfile=S.hashfile;const integer=S.integer;const finite=S.finite
const transform=S.transform;const groups=S.groups;const recheck=S.recheck
const relative_file=RS.relative_file;const pin! =RS.pin!
function exact_equal(a,b)
    if a isa AbstractDict && b isa AbstractDict
        return Set(keys(a))==Set(keys(b)) && all(exact_equal(a[k],b[k]) for k in keys(a))
    elseif a isa AbstractVector && b isa AbstractVector
        return length(a)==length(b) && all(exact_equal(x,y) for (x,y) in zip(a,b))
    end
    typeof(a)==typeof(b) && a==b
end
function source_contract(id,contract=nothing,pins=Dict{String,String}())
    path=relative_file(REGISTRY_REF);pins[path]=hashfile(path);registry=JSON.parsefile(path)
    presets=registry["presets"]
    matches=filter(x->x["id"]==id,presets)
    check(length(matches)==1,"Unknown/duplicate registered decay source")
    preset=only(matches)
    check(get(preset,"adapter",nothing)==ADAPTER,"Source uses a preserved legacy route, not the generic decay route")
    contract!==nothing && check(exact_equal(contract,preset),"Source contract differs from registry")
    check(integer(preset["Z"]) && integer(preset["A"]) && 1<=preset["Z"]<=118 && preset["Z"]<=preset["A"]<=400 &&
        integer(preset["ground_daughter_pdg"]) && preset["ground_daughter_pdg"]==1_000_000_000+10000*preset["daughter_Z"]+10*preset["daughter_A"] &&
        all(integer,preset["allowed_light_nuclear_pdgs"]),"Invalid registered nuclear identity")
    check(integer(preset["pdg"]) && preset["pdg"]==1_000_000_000+10000*preset["Z"]+10*preset["A"] &&
        preset["generator"]=="GPS_ion_at_rest" && preset["primary_excitation_keV"]==0 && preset["kinetic_energy_keV"]==0,"Invalid registered ion contract")
    check(exact_equal(preset["nuclear_policy"],Dict("primary_threshold_ns"=>1e27,"reset_initial_children_to_zero"=>true,"ground_secondary_lifetime_cap_ns"=>100000,"nucleus_limits"=>"unrestricted_default","initial_nucleus_count_per_event"=>1)),"Wrong registered nuclear lifetime/clock policy")
    names=Set{String}()
    for line in preset["diagnostic_lines"]
        name=line["name"];window=line["window_keV"]
        check(name isa String && !isempty(name) && !(name in names) && length(window)==2 && all(finite,window) && 0<=window[1]<=window[2],"Invalid diagnostic photon window")
        push!(names,name)
    end
    preset
end
function model_contract(c,pins=Dict{String,String}())
    check(c isa AbstractDict && get(c,"model_id",nothing) in keys(SIGNED_BIAS),"Unsupported detector contract")
    id=c["model_id"]
    id in keys(RS.MODEL_PINS) && return RS.model_contract(c,pins)
    id in keys(SS.MODEL_PINS) && return SS.model_contract(c,pins)
    check(c["kind"]=="canonical_effective_model_v1","Wrong canonical detector contract")
    ref="models/"*id*".yaml";model=relative_file(ref)
    check(c["source_model_ref"]==c["effective_model_ref"]==ref && c["source_model_sha256"]==c["effective_model_sha256"]==CANONICAL_PINS[id],"Canonical model bytes must remain unchanged")
    pin!(pins,model,CANONICAL_PINS[id])
    check(c["variant_id"]==id && c["model_delta"]===nothing && c["geometry_unchanged"]===true &&
        c["stored_temperature_K"]==78 && c["runtime_temperature_K"]==77 && c["readout_contact_id"]==1 &&
        c["contact_potentials_V"]==Dict("1"=>0,"2"=>SIGNED_BIAS[id]),"Canonical detector operating convention changed")
    catalog=JSON.parsefile(relative_file("models/catalog.json"))
    entry=only(filter(x->x["id"]==id,catalog["detectors"]))
    deps=Dict("models/"*r=>only(filter(x->x["path"]==r,catalog["dependencies"]))["sha256"] for r in entry["dependencies"])
    check(entry["model_sha256"]==CANONICAL_PINS[id] && c["dependencies_sha256"]==deps &&
        Dict(string(x["id"])=>x["potential_V"] for x in entry["contacts"])==c["contact_potentials_V"] && entry["readout_contact_id"]==1,"Canonical catalog/dependency/contact mismatch")
    for (ref,h) in deps;pin!(pins,relative_file(ref),h);end
    model
end
function inspect(path)
    path=S.localfile(path);base=dirname(path);m=JSON.parsefile(path);pins=Dict(path=>hashfile(path))
    check(m["kind"]==KIND && m["status"]=="complete" && m["producer_adapter"]==ADAPTER,"Incomplete/wrong shared decay stream")
    n=m["primary_count"];check(integer(n) && n in (20,500) && m["global_decay_id_range"]==[0,n-1],"Invalid source milestone census")
    preset=source_contract(m["source_id"],m["source_contract"],pins)
    check(m["model_id"] in keys(SIGNED_BIAS) && m["model_contract"]["model_id"]==m["model_id"] && m["model_contract"]["source_model_sha256"]==m["model_sha256"],"Wrong effective/source detector binding")
    model_contract(m["model_contract"],pins)
    check(m["units"]==Dict("energy"=>"keV","length"=>"mm","time"=>"ns") && m["raw_track_energy_unit"]=="MeV" && m["raw_position_unit"]=="m","Wrong shared stream units")
    transform(m["coordinate_transform"])
    check(m["clock_policy"]=="remage_initial_decay_secondaries_zero" && m["source_lh5"]=="../truth.lh5","Wrong conditional clock/raw location")
    S.pin!(pins,joinpath(base,m["source_lh5"]),m["source_lh5_sha256"])
    for (name,key) in (("prepared.json","prepared_sha256"),("run.json","run_sha256"),("scenario.json","config_sha256"),("geometry.gdml","geometry_sha256"),("run.mac","macro_sha256"))
        S.pin!(pins,joinpath(base,"..",name),m[key])
    end
    prepared=JSON.parsefile(joinpath(base,"..","prepared.json"));run=JSON.parsefile(joinpath(base,"..","run.json"))
    check(prepared["kind"]=="decay_source_prepared_v1" && prepared["producer_adapter"]==ADAPTER && prepared["source_pdg"]==preset["pdg"],"Wrong prepared registry ion")
    check(run["status"]=="complete" && run["prepared_sha256"]==m["prepared_sha256"] && run["source_lh5_sha256"]==m["source_lh5_sha256"],"Unmatched decay transport")
    for key in ("model_id","model_sha256","primary_count","coordinate_transform","grouping_policy","clock_policy","source_sha256","model_contract","source_id","source_contract")
        check(m[key]==prepared[key],"Prepared/shared-stream mismatch: "*key)
    end
    for (name,h) in prepared["files_sha256"]
        check(name isa String && !isabspath(name) && !occursin('\\',name) && !(".." in split(name,'/')),"Unsafe prepared file")
        S.pin!(pins,joinpath(base,"..",split(name,'/')...),h)
    end
    anchorpath=relative_file(ANCHORS_REF);pins[anchorpath]=hashfile(anchorpath);anchors=JSON.parsefile(anchorpath)
    check(anchors["kind"]=="nominal_placement_anchors_v1" && anchors["cryostat_id"]=="lbnl_modular_nominal_v1" && prepared["source_position_global_mm"]==preset["position_global_mm"]==anchors["source_pose"]["position_global_mm"] && m["coordinate_transform"]==anchors["coordinate_transform"],"Shared nominal source/detector anchors changed")
    for (refkey,hashkey) in (("original_geometry_ref","original_geometry_sha256"),("upstream_manifest_ref","upstream_manifest_sha256"));pin!(pins,relative_file(anchors[refkey]),anchors[hashkey]);end
    refs=m["source_sha256"];check(refs isa AbstractDict && !isempty(refs),"Missing shared producer provenance")
    for (ref,h) in refs;pin!(pins,relative_file(occursin('/',ref) ? ref : "transport/"*ref),h);end
    check(m["decay_source_sha256"]==prepared["generic_source_sha256"],"Prepared generic source authority differs")
    generic=m["decay_source_sha256"]
    check(issubset(Set((REGISTRY_REF,ANCHORS_REF,"transport/decay_source.py","tools/decay_workflow.py")),Set(keys(generic))),"Incomplete generic source authority")
    for (ref,h) in generic;pin!(pins,relative_file(ref),h);end
    upstream=JSON.parsefile(relative_file("transport/cryostat-source.json"))
    check(prepared["upstream_sha256"]==Dict(f["name"]=>f["sha256"] for f in upstream["files"]),"Upstream geometry provenance changed")
    for (name,h) in prepared["upstream_sha256"];S.pin!(pins,joinpath(ROOT,".local/transport/LBNL",name),h);end
    geometry=JSON.parsefile(joinpath(base,"..","geometry-report.json"))
    check(geometry["overlaps_passed"]===true && geometry["source_inside_fill"]===true,"Shared native geometry admission failed")
    ge=only(filter(v->v["name"]=="germanium",geometry["volumes"]));rotation,shift=transform(m["coordinate_transform"])
    actual=reduce(vcat,[permutedims(Float64.(v)) for v in ge["rotation_local_to_global"]])
    check(isapprox(actual,rotation;rtol=0,atol=1e-12) && isapprox(Float64.(ge["translation_global_mm"]),shift;rtol=0,atol=1e-10),"Native detector transform mismatch")
    check(isapprox(geometry["crystal_volume_mm3"],prepared["analytic_volume_mm3"];rtol=1e-10,atol=1e-9),"Independent/native crystal volume mismatch")
    policy=m["grouping_policy"]
    check(policy["name"]=="nominal_isolated_windows_v1" && policy["interval"]=="[origin, origin+horizon)" && policy["state_at_group_start"]=="reset" && policy["activity_live_time_pileup_claim"]===false,"Wrong isolated-window policy")
    groups(Any[],policy["horizon_ns"])
    check(m["ledger"]["kind"]=="recorded-only" && m["ledger"]["full_energy_closure"]===nothing,"Unsupported energy closure claim")
    tables=m["raw_tables"]
    check(Set(keys(tables))==union(Set(("vtx","particles","tracks","processes")),Set(keys(prepared["material_tables"]))),"Raw table census mismatch")
    for spec in values(tables);check(integer(spec["rows"]) && spec["rows"]>=0 && spec["columns"] isa AbstractDict && !isempty(spec["columns"]),"Invalid raw table descriptor");end
    check(length(m["processes"])==tables["processes"]["rows"],"Process census mismatch")
    for (i,p) in enumerate(m["processes"]);check(p["raw_row_index"]==i-1 && Set(keys(p))==union(Set(keys(tables["processes"]["columns"])),Set(["raw_row_index"])),"Changed process row");end
    expected=0;names=Set{String}()
    for c in m["chunks"]
        name=c["file"];check(basename(name)==name && !(name in names) && endswith(name,".jsonl"),"Invalid/repeated chunk")
        check(integer(c["count"]) && 1<=c["count"]<=100 && c["first_global_decay_id"]==expected,"Bad chunk mapping")
        push!(names,name);S.pin!(pins,joinpath(base,name),c["sha256"]);expected+=c["count"]
    end
    check(expected==n,"Incomplete source census")
    (path=path,manifest=m,prepared=prepared,pins=pins)
end
function validate_record!(e,eid,m,counters)
    source=m["source_contract"]
    check(e["source_id"]==m["source_id"]==source["id"],"Foreign source record")
    check(integer(e["event_id"]) && integer(e["global_decay_id"]) && e["event_id"]==e["global_decay_id"]==eid,"Noncontiguous initial identity")
    for table in ("vtx","particles","tracks");S.rawrows!(e[table],table,eid,counters,m);end
    check(length(e["vtx"])==length(e["particles"])==1,"Missing/duplicate primary")
    v=only(e["vtx"]);p=only(e["particles"])
    check(v["time"]==0 && v["n_part"]==1 && p["particle"]==source["pdg"] && p["vertexid"]==0 && p["ekin"]==0 && all(p[a]==0 for a in ("px","py","pz")),"Wrong registry-selected ion primary")
    tracks=Dict(t["trackid"]=>t for t in e["tracks"])
    check(length(tracks)==length(e["tracks"]),"Duplicate track ID")
    roots=filter(t->t["parent_trackid"]==0,e["tracks"])
    check(length(roots)==1 && only(roots)["particle"]==source["pdg"] && only(roots)["ekin"]==0,"Wrong registry-selected root")
    processes=Dict(p["procid"]=>p["name"] for p in m["processes"])
    check(length(processes)==length(m["processes"]),"Duplicate process ID")
    children=filter(t->t["parent_trackid"]==only(roots)["trackid"],e["tracks"])
    check(!isempty(children) && all(t->t["time"]==0,children),"Initial child clock was not reset")
    for t in e["tracks"]
        check(integer(t["trackid"]) && t["trackid"]>0 && integer(t["parent_trackid"]) && t["parent_trackid"]>=0 && integer(t["particle"]) && t["time"]>=0 && t["ekin"]>=0,"Invalid raw track")
        check(t["parent_trackid"]==0 || haskey(processes,t["procid"]),"Unknown creation process")
        parent=t["parent_trackid"]
        check(parent==0 || parent==only(roots)["trackid"] || (haskey(tracks,parent) && t["time"]>=tracks[parent]["time"]),"Descendant creation precedes its parent")
        seen=Set([t["trackid"]]);parent=t["parent_trackid"]
        while parent!=0
            check(haskey(tracks,parent) && !(parent in seen),"Missing/cyclic ancestry")
            push!(seen,parent);parent=tracks[parent]["parent_trackid"]
        end
    end
    # Nuclear family admission is data-driven. A suffix is never proof of excitation.
    families=Set((div(source["pdg"],10),div(source["ground_daughter_pdg"],10)))
    allowed=Set(source["allowed_light_nuclear_pdgs"])
    daughter_family=div(source["ground_daughter_pdg"],10)
    check(any(t->div(t["particle"],10)==daughter_family,children),"Missing intended first daughter family")
    for t in e["tracks"]
        pdg=t["particle"]
        if abs(pdg)>=1_000_000_000
            check(div(pdg,10) in families || pdg in allowed,"Unexpected descendant nuclear family")
        end
        parent=t["parent_trackid"]
        if parent!=0 && tracks[parent]["particle"]==source["ground_daughter_pdg"] && occursin("radioactivedecay",lowercase(processes[t["procid"]]))
            check(t["time"]<=source["nuclear_policy"]["ground_secondary_lifetime_cap_ns"],"Long-lived ground-daughter decay escaped lifetime cap")
        end
    end
    rot,shift=transform(m["coordinate_transform"])
    S.rawrows!([s["raw"] for s in e["steps"]],"stp/germanium",eid,counters,m)
    for s in e["steps"]
        r=s["raw"]
        for (key,rawkey) in (("raw_row_index","raw_row_index"),("energy_keV","edep"),("time_ns","time"),("track_id","trackid"),("parent_track_id","parent_trackid"),("particle_pdg","particle"))
            check(s[key]==r[rawkey],"Changed raw deposit field: "*key)
        end
        check(finite(s["energy_keV"]) && s["energy_keV"]>=0 && finite(s["time_ns"]) && s["time_ns"]>=0,"Invalid deposition energy/time")
        check(haskey(tracks,s["track_id"]),"Unknown deposit track");t=tracks[s["track_id"]]
        check(t["particle"]==s["particle_pdg"] && t["parent_trackid"]==s["parent_track_id"] && s["time_ns"]>=t["time"],"Deposit ancestry/creation-time mismatch")
        for (suffix,key) in (("","position_mm"),("_pre","pre_position_mm"),("_post","post_position_mm"))
            global_m=[r[a*suffix] for a in ("xloc","yloc","zloc")];xyz=rot'*(1000 .* global_m .- shift)
            check(length(s[key])==3 && all(finite,s[key]) && isapprox(xyz,Float64.(s[key]);atol=1e-10,rtol=0),"Changed coordinate transform")
            suffix=="" && check(s["global_position_m"]==global_m,"Changed global deposit position")
        end
    end
    # All source-descendant photons survive, including EM photons; windows are diagnostics only.
    photons=[Dict("raw_row_index"=>t["raw_row_index"],"track_id"=>t["trackid"],"parent_track_id"=>t["parent_trackid"],
        "time_ns"=>t["time"],"energy_keV"=>1000*t["ekin"],"creation_process"=>processes[t["procid"]]) for t in e["tracks"] if t["particle"]==22 && t["parent_trackid"]!=0]
    lines=Dict(line["name"]=>count(p->line["window_keV"][1]<=p["energy_keV"]<=line["window_keV"][2],photons) for line in source["diagnostic_lines"])
    check(e["decay_photons"]==photons && integer(e["decay_photon_count"]) && e["decay_photon_count"]==length(photons) &&
        all(integer,values(e["line_photon_counts"])) && e["line_photon_counts"]==lines && integer(e["line_photon_count"]) && e["line_photon_count"]==sum(values(lines);init=0),"Source photon census mismatch")
    check(all(x->finite(x) && x>=0,values(e["material_energy_keV"])),"Invalid recorded material ledger")
    check(e["pulse_groups"]==groups(e["steps"],m["grouping_policy"]["horizon_ns"]),"Changed pulse assignment/time origin/boundary flags")
    nothing
end
function foreach_decay(f,input)
    m=input.manifest;expected=0;counters=Dict(t=>0 for t in ("vtx","particles","tracks","stp/germanium"))
    for c in m["chunks"]
        path=joinpath(dirname(input.path),c["file"]);check(hashfile(path)==c["sha256"],"Chunk changed after inspection");n=0
        open(path) do io
            for line in eachline(io)
                check(n<c["count"] && sizeof(line)<=100_000_000,"Extra/oversized source record")
                e=JSON.parse(line);validate_record!(e,expected,m,counters)
                if hasproperty(input,:prepared)
                    p=input.prepared;v=only(e["vtx"])
                    check(isapprox(1000 .* [v[a] for a in ("xloc","yloc","zloc")],Float64.(p["source_position_global_mm"]);rtol=0,atol=1e-10),"Changed source anchor")
                    materials=p["material_tables"]
                    check(Set(keys(e["material_energy_keV"]))==Set(values(materials)),"Missing/extra material sum")
                    gemat=materials["stp/germanium"]
                    if count(==(gemat),values(materials))==1
                        ge=sum((s["energy_keV"] for s in e["steps"]);init=0.)
                        check(isapprox(ge,e["material_energy_keV"][gemat];atol=1e-9,rtol=1e-12),"Ge material/deposit ledger mismatch")
                    end
                end
                f(e);n+=1;expected+=1
            end
        end
        check(n==c["count"] && hashfile(path)==c["sha256"],"Truncated/changed chunk")
    end
    check(expected==m["primary_count"],"Incomplete initial census")
    for (table,n) in counters;check(n==m["raw_tables"][table]["rows"],"Incomplete raw table: "*table);end
    expected
end
end
