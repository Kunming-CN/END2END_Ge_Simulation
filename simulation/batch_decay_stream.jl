# Batch-only stream admission; original Cs137/source readers and raw validators stay frozen.
isdefined(@__MODULE__, :DecayStream) || include("decay_stream.jl")
isdefined(@__MODULE__, :BatchNativeContract) || include("batch_native_contract.jl")
isdefined(@__MODULE__, :CatalogNativeModel) || include("catalog_native_model.jl")
module BatchDecayStream
using ..DecayStream, ..BatchNativeContract, ..CatalogNativeModel, JSON
const D=DecayStream;const S=D.S;const C=BatchNativeContract
const KIND="radioactive_decay_batch_stream_v1"
const ADAPTER="shared_decay_batch_source_v1"
const ROOT=D.ROOT
const check=S.check;const recheck=S.recheck;const relative_file=D.relative_file;const pin! =D.pin!
function model_contract(c,pins=Dict{String,String}())
    if get(c,"kind",nothing)=="catalog_detector_contract_v1"
        a=CatalogNativeModel.validate_model(c;require_placement=true)
        for (ref,h) in merge(c["dependencies_sha256"],Dict(c["model_ref"]=>c["model_sha256"],"models/catalog.json"=>c["catalog_sha256"]))
            pin!(pins,relative_file(ref),h)
        end
        return a.path
    end
    D.model_contract(c,pins)
end
function source(p,mode,pins=Dict{String,String}())
    check(mode in ("cs137_legacy","registered_decay"),"Unsupported batch source mode")
    if mode=="registered_decay"
        return D.source_contract(p["id"],p,pins)
    end
    registry=relative_file(D.REGISTRY_REF);pins[registry]=S.hashfile(registry)
    actual=only(filter(x->x["id"]==p["id"],JSON.parsefile(registry)["presets"]))
    check(p["id"]=="cs137_point_decay_v1" && D.exact_equal(p,actual),"Changed legacy Cs137 registry contract")
    p
end
function inspect(path)
    path=S.localfile(path);m=JSON.parsefile(path);pins=Dict(path=>S.hashfile(path));base=dirname(path)
    check(m["kind"]==KIND && m["status"]=="complete" && m["producer_adapter"]==ADAPTER,"Incomplete/wrong batch stream")
    b=C.descriptor(m["batch"]);n=b["primary_count"];o=b["global_initial_offset"]
    check(S.integer(m["primary_count"]) && m["primary_count"]==n && m["global_decay_id_range"]==[0,n-1] && m["global_initial_id_range"]==[o,o+n-1],"Incomplete batch identity range")
    storage=C.event_storage(m)
    storage!==nothing && C.initial_summary(m)
    preparedpath=relative_file(m["shared_prepared_ref"]);pin!(pins,preparedpath,m["shared_prepared_sha256"]);p=JSON.parsefile(preparedpath)
    check(p["kind"]=="batch_shared_transport_prepared_v1" && p["status"]=="complete" && p["source_mode"]==m["source_mode"],"Wrong shared transport preparation")
    pose=C.source_pose(p,p["checked_transport"]["selection"],S.hashfile(relative_file("scenarios/placement-anchors.json")))
    if pose===nothing
        check(!haskey(m,"source_pose"),"Legacy stream cannot carry an angular pose")
    else
        check(m["source_pose"]==pose && m["source_position_global_mm"]==pose["position_global_mm"],"Stream angular source pose differs from shared geometry")
    end
    source(m["source_contract"],m["source_mode"],pins)
    for k in ("source_id","source_contract","model_id","model_sha256","model_contract","coordinate_transform","clock_policy","grouping_policy")
        check(m[k]==p[k],"Batch/shared preparation mismatch: "*k)
    end
    model_contract(m["model_contract"],pins)
    check(p["geometry_checks"]["overlaps_passed"]===true && p["geometry_checks"]["source_inside_fill"]===true,"Unchecked shared cryostat/source geometry")
    policy=m["grouping_policy"]
    check(policy["name"]=="nominal_isolated_windows_v1" && policy["interval"]=="[origin, origin+horizon)" && policy["state_at_group_start"]=="reset" && policy["activity_live_time_pileup_claim"]===false,"Changed isolated-window grouping")
    S.groups(Any[],policy["horizon_ns"])
    check(m["units"]==Dict("energy"=>"keV","length"=>"mm","time"=>"ns") && m["raw_track_energy_unit"]=="MeV" && m["raw_position_unit"]=="m","Changed batch units")
    S.transform(m["coordinate_transform"])
    check(m["ledger"]["kind"]=="recorded-only" && m["ledger"]["full_energy_closure"]===nothing,"Unsupported energy closure claim")
    check(m["source_lh5"]=="../truth.lh5","Batch raw file belongs to a different location")
    S.pin!(pins,joinpath(base,m["source_lh5"]),m["source_lh5_sha256"])
    for (key,hashkey) in (("run_ref","run_sha256"),("macro_ref","macro_sha256"))
        pin!(pins,relative_file(m[key]),m[hashkey])
    end
    run=JSON.parsefile(relative_file(m["run_ref"]))
    check(run["kind"]=="batch_transport_run_v1" && run["status"]=="complete" && run["batch"]==b &&
        run["number_of_simulated_events"]==n && run["initial_ledger_count"]==n &&
        run["shared_prepared_sha256"]==m["shared_prepared_sha256"] && run["source_lh5_sha256"]==m["source_lh5_sha256"],"Incomplete/wrong raw transport receipt")
    for (ref,h) in p["files_sha256"];pin!(pins,relative_file(ref),h);end
    tables=m["raw_tables"]
    check(Set(keys(tables))==union(Set(("vtx","particles","tracks","processes")),Set(keys(p["material_tables"]))),"Raw table census mismatch")
    for spec in values(tables);check(S.integer(spec["rows"]) && spec["rows"]>=0 && spec["columns"] isa AbstractDict && !isempty(spec["columns"]),"Invalid raw table descriptor");end
    check(length(m["processes"])==tables["processes"]["rows"],"Process census mismatch")
    for (i,row) in enumerate(m["processes"])
        check(row["raw_row_index"]==i-1 && Set(keys(row))==union(Set(keys(tables["processes"]["columns"])),Set(["raw_row_index"])),"Changed process row")
    end
    expected=0;previous=-1;names=Set{String}()
    for chunk in m["chunks"]
        name=chunk["file"];check(basename(name)==name && !(name in names) && endswith(name,".jsonl"),"Unsafe/repeated batch chunk")
        firstid=chunk["first_global_decay_id"]
        check(S.integer(chunk["count"]) && 1<=chunk["count"]<=100 && S.integer(firstid) &&
            (storage===nothing ? firstid==expected : previous<firstid<n),"Changed extraction chunk mapping")
        push!(names,name);S.pin!(pins,joinpath(base,name),chunk["sha256"]);expected+=chunk["count"]
        previous=firstid
    end
    check(expected==(storage===nothing ? n : storage["nonzero_primaries"]),"Incomplete batch chunk census")
    (path=path,manifest=m,prepared=p,pins=pins)
end
function foreach_decay(f,input)
    # Reuse the original all-raw-row source validator, on one parsed record at a time.
    api=input.manifest["source_mode"]=="registered_decay" ? D : S
    b=input.manifest["batch"]
    C.event_storage(input.manifest)===nothing && return api.foreach_decay(e->begin C.identity(e,b);f(e);end,input)
    foreach_nonzero(f,input,api,b)
end
function foreach_nonzero(f,input,api,b)
    m=input.manifest;storage=C.event_storage(m);summary=C.initial_summary(m)
    previous=-1;stored=0;nextrow=Dict(t=>0 for t in ("vtx","particles","tracks","stp/germanium"))
    photons=0;lines=0;named=get(summary,"line_photon_counts",nothing);namedseen=named===nothing ? nothing : Dict(k=>0 for k in keys(named))
    for chunk in m["chunks"]
        path=joinpath(dirname(input.path),chunk["file"]);check(S.hashfile(path)==chunk["sha256"],"Sparse chunk changed after inspection");count=0
        open(path) do io
            for line in eachline(io)
                check(count<chunk["count"] && sizeof(line)<=100_000_000,"Extra/oversized sparse record")
                e=JSON.parse(line);ids=C.identity(e,b);eid=ids["event_id"]
                check(previous<eid && (count!=0 || eid==chunk["first_global_decay_id"]),"Reordered/repeated sparse initial identity")
                check(any(s->S.finite(s["energy_keV"]) && s["energy_keV"]>0,e["steps"]),"Sparse source retained zero deposition")
                # Omitted primaries create raw-row gaps. Within every retained event,
                # the original validator still requires exact contiguous original rows.
                counters=copy(nextrow)
                for table in keys(counters)
                    rows=table=="stp/germanium" ? [s["raw"] for s in e["steps"]] : e[table]
                    isempty(rows) && continue
                    firstrow=first(rows)["raw_row_index"]
                    check(S.integer(firstrow) && nextrow[table]<=firstrow && firstrow+length(rows)<=m["raw_tables"][table]["rows"],"Sparse raw row is repeated or outside original table")
                    table in ("vtx","particles") && check(firstrow==eid,"Sparse initial raw row changed")
                    counters[table]=firstrow
                end
                api.validate_record!(e,eid,m,counters);nextrow=counters
                p=input.prepared;v=only(e["vtx"])
                check(isapprox(1000 .* [v[a] for a in ("xloc","yloc","zloc")],Float64.(p["source_position_global_mm"]);rtol=0,atol=1e-10),"Changed sparse source anchor")
                materials=p["material_tables"]
                check(Set(keys(e["material_energy_keV"]))==Set(values(materials)),"Missing/extra sparse material sum")
                gemat=materials["stp/germanium"]
                if Base.count(==(gemat),values(materials))==1
                    ge=sum((s["energy_keV"] for s in e["steps"]);init=0.)
                    check(isapprox(ge,e["material_energy_keV"][gemat];atol=1e-9,rtol=1e-12),"Sparse Ge material/deposit ledger mismatch")
                end
                photons+=e["decay_photon_count"];lines+=e["line_photon_count"]
                namedseen!==nothing && foreach(k->namedseen[k]+=e["line_photon_counts"][k],keys(namedseen))
                f(e);previous=eid;stored+=1;count+=1
            end
        end
        check(count==chunk["count"] && S.hashfile(path)==chunk["sha256"],"Truncated/changed sparse chunk")
    end
    check(stored==storage["nonzero_primaries"] && photons<=summary["decay_photons"] && lines<=summary["line_photons"],"Sparse record/initial photon census mismatch")
    namedseen!==nothing && check(all(namedseen[k]<=named[k] for k in keys(named)),"Sparse named photons exceed initial census")
    # Complete raw rows are retained in the separately hash-bound original LH5.
    # Python extraction verifies this sparse selection and summary against that raw source.
    m["primary_count"]
end
end
