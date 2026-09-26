# Pure streaming contract checks; no detector imports and no ion-as-gamma validator.
module NativeStream
using JSON, SHA, LinearAlgebra
const ROOT=dirname(@__DIR__)
const KIND="cs137_decay_stream_v1"
check(x,m)=x ? nothing : throw(ArgumentError(m))
finite(x)=x isa Real && !(x isa Bool) && isfinite(x)
integer(x)=x isa Integer && !(x isa Bool)
hashfile(p)=open(io->bytes2hex(sha256(io)),p)
function localfile(p)
    check(isfile(p),"Missing stream dependency: "*basename(p))
    p=realpath(p); r=relpath(p,realpath(joinpath(ROOT,".local")))
    check(!isabspath(r) && !(".." in splitpath(r)),"Stream dependency outside project .local")
    p
end
function pin!(pins,p,digest)
    p=localfile(p)
    check(digest isa String && occursin(r"^[0-9a-f]{64}$",digest) && hashfile(p)==digest,"Stream dependency checksum mismatch: "*basename(p))
    pins[p]=digest; p
end
function transform(tr)
    check(tr["definition"]=="x_global_mm=R*x_local_mm+t","Unknown transform definition")
    a=tr["rotation_local_to_global"]; shift=tr["translation_global_mm"]
    vec3(v)=v isa AbstractVector && length(v)==3 && all(finite,v)
    check(length(a)==3 && all(vec3,a) && vec3(shift),"Invalid transform dimensions")
    rot=reduce(vcat,[permutedims(Float64.(v)) for v in a])
    check(isapprox(rot'*rot,Matrix{Float64}(I,3,3);atol=1e-12,rtol=0) && abs(det(rot)-1)<=1e-12,"Improper rotation")
    rot,Float64.(shift)
end
function groups(steps,horizon)
    check(finite(horizon) && 0<horizon<=900000,"Invalid grouping horizon")
    rows=sort(filter(s->s["energy_keV"]>0,steps);by=s->(s["time_ns"],s["raw_row_index"]))
    out=Any[]
    for s in rows
        if isempty(out) || s["time_ns"]-last(out)["origin_time_ns"]>=horizon
            prev=isempty(out) ? nothing : last(out)
            push!(out,Dict{String,Any}("group_id"=>length(out),"origin_time_ns"=>s["time_ns"],
                "horizon_ns"=>horizon,"row_indices"=>Int[],"relative_times_ns"=>Float64[],
                "tail_truncated_possible"=>true,"recovery_not_established"=>prev!==nothing,
                "boundary_split_within_horizon"=>prev!==nothing && s["time_ns"]-prev["last_deposit_time_ns"]<horizon,
                "electronics_state"=>"reset_nominal_isolated_window"))
        end
        g=last(out); push!(g["row_indices"],s["raw_row_index"])
        push!(g["relative_times_ns"],s["time_ns"]-g["origin_time_ns"])
        g["last_deposit_time_ns"]=s["time_ns"]
    end
    out
end
function inspect(path)
    path=localfile(path); m=JSON.parsefile(path); base=dirname(path); pins=Dict{String,String}(path=>hashfile(path))
    check(m["kind"]==KIND && m["status"]=="complete","Incomplete/unsupported stream")
    n=m["primary_count"]
    check(integer(n) && 1<=n<=100000 && m["global_decay_id_range"]==[0,n-1],"Invalid decay census")
    check(m["model_id"] in ("AK02","SAP22"),"Unsupported model")
    model=joinpath(ROOT,"models",m["model_id"]*".yaml")
    catalog=JSON.parsefile(joinpath(ROOT,"models","catalog.json"))
    entry=only(filter(e->e["id"]==m["model_id"],catalog["detectors"]))
    check(m["model_sha256"]==entry["model_sha256"]==hashfile(model),"Unpinned model")
    check(m["units"]==Dict("energy"=>"keV","length"=>"mm","time"=>"ns") && m["raw_track_energy_unit"]=="MeV" && m["raw_position_unit"]=="m","Wrong stream units")
    transform(m["coordinate_transform"])
    check(m["clock_policy"]=="remage_initial_decay_secondaries_zero","Unknown conditional clock")
    check(m["source_lh5"]=="../truth.lh5","Unsupported raw location")
    pin!(pins,joinpath(base,m["source_lh5"]),m["source_lh5_sha256"])
    for (name,key) in (("prepared.json","prepared_sha256"),("run.json","run_sha256"),
        ("scenario.json","config_sha256"),("geometry.gdml","geometry_sha256"),("run.mac","macro_sha256"))
        pin!(pins,joinpath(base,"..",name),m[key])
    end
    prepared=JSON.parsefile(joinpath(base,"..","prepared.json")); run=JSON.parsefile(joinpath(base,"..","run.json"))
    check(prepared["kind"]=="cs137_prepared_v1" && prepared["source_pdg"]==1000551370,"Not the Cs137 ion contract")
    check(run["status"]=="complete" && run["prepared_sha256"]==m["prepared_sha256"] && run["source_lh5_sha256"]==m["source_lh5_sha256"],"Unmatched transport run")
    for key in ("model_id","model_sha256","primary_count","coordinate_transform","grouping_policy","clock_policy","source_sha256","decay_photon_line_window_keV")
        check(m[key]==prepared[key],"Prepared/stream mismatch: "*key)
    end
    check(m["decay_photon_line_window_keV"]==[660,663],"Unexpected photon counting window")
    for (name,digest) in prepared["files_sha256"]
        check(basename(name)==name && !(name in (".","..")),"Unsafe prepared filename")
        pin!(pins,joinpath(base,"..",name),digest)
    end
    expected_sources=Set(("cs137.py","cryostat_export.cc","cryostat_nominal.json","handoff.py","cryostat-source.json","pixi.toml","pixi.lock","CMakeLists.txt"))
    check(Set(keys(m["source_sha256"]))==expected_sources,"Incomplete producer source/config hashes")
    for (name,digest) in m["source_sha256"]
        p=joinpath(ROOT,"transport",name)
        check(hashfile(p)==digest,"Producer source/config changed: "*name); pins[p]=digest
    end
    upstream=JSON.parsefile(joinpath(ROOT,"transport","cryostat-source.json"))
    check(prepared["upstream_sha256"]==Dict(f["name"]=>f["sha256"] for f in upstream["files"]),"Upstream provenance changed")
    for (name,digest) in prepared["upstream_sha256"]
        pin!(pins,joinpath(ROOT,".local","transport","LBNL",name),digest)
    end
    policy=m["grouping_policy"]
    check(policy["name"]=="nominal_isolated_windows_v1" && policy["interval"]=="[origin, origin+horizon)" && policy["state_at_group_start"]=="reset" && policy["activity_live_time_pileup_claim"]===false,"Unsupported window convention")
    groups(Any[],policy["horizon_ns"])
    check(m["ledger"]["kind"]=="recorded-only" && m["ledger"]["full_energy_closure"]===nothing,"Unsupported energy-closure claim")
    tables=m["raw_tables"]
    check(Set(keys(tables))==union(Set(("vtx","particles","tracks","processes")),Set(keys(prepared["material_tables"]))),"Raw table census mismatch")
    for spec in values(tables)
        check(integer(spec["rows"]) && spec["rows"]>=0 && spec["columns"] isa AbstractDict && !isempty(spec["columns"]),"Invalid raw table descriptor")
    end
    check(length(m["processes"])==tables["processes"]["rows"],"Process-table census mismatch")
    for (i,p) in enumerate(m["processes"])
        check(p["raw_row_index"]==i-1 && Set(keys(p))==union(Set(keys(tables["processes"]["columns"])),Set(["raw_row_index"])),"Changed raw process table")
    end
    expected=0; names=Set{String}()
    for c in m["chunks"]
        name=c["file"]
        check(basename(name)==name && !(name in names) && endswith(name,".jsonl"),"Invalid/repeated chunk name")
        check(integer(c["count"]) && 1<=c["count"]<=100 && c["first_global_decay_id"]==expected,"Invalid chunk mapping")
        push!(names,name); pin!(pins,joinpath(base,name),c["sha256"]); expected+=c["count"]
    end
    check(expected==n,"Incomplete chunk census")
    (path=path,manifest=m,prepared=prepared,pins=pins)
end
function rawrows!(rows,table,eid,counters,m)
    spec=m["raw_tables"][table]
    for r in rows
        check(Set(keys(r))==union(Set(keys(spec["columns"])),Set(["raw_row_index"])),"Lost/extra raw scalar columns: "*table)
        check(integer(r["raw_row_index"]) && r["raw_row_index"]==counters[table],"Missing/repeated raw row: "*table)
        check(integer(r["evtid"]) && r["evtid"]==eid,"Foreign raw event ID")
        check(all(v->v isa String || v isa Bool || finite(v),values(r)),"Nonfinite/non-scalar raw column")
        counters[table]+=1
    end
end
function validate_record!(e,eid,m,counters)
    check(integer(e["event_id"]) && integer(e["global_decay_id"]) && e["event_id"]==e["global_decay_id"]==eid,"Noncontiguous decay ID")
    for table in ("vtx","particles","tracks"); rawrows!(e[table],table,eid,counters,m); end
    check(length(e["vtx"])==length(e["particles"])==1,"Missing/duplicate primary")
    v=only(e["vtx"]); p=only(e["particles"])
    check(v["time"]==0 && v["n_part"]==1 && p["particle"]==1000551370 && p["vertexid"]==0 && p["ekin"]==0 && all(p[a]==0 for a in ("px","py","pz")),"Wrong ion primary")
    tracks=Dict(t["trackid"]=>t for t in e["tracks"])
    check(length(tracks)==length(e["tracks"]),"Duplicate track ID")
    roots=filter(t->t["parent_trackid"]==0,e["tracks"])
    check(length(roots)==1 && only(roots)["particle"]==1000551370 && only(roots)["ekin"]==0,"Invalid Cs137 root")
    processes=Dict(p["procid"]=>p["name"] for p in m["processes"])
    check(length(processes)==length(m["processes"]),"Duplicate process ID")
    children=filter(t->t["parent_trackid"]==only(roots)["trackid"],e["tracks"])
    check(!isempty(children) && all(t->t["time"]==0,children),"Conditional clock was not reset")
    for t in e["tracks"]
        check(integer(t["trackid"]) && t["trackid"]>0 && integer(t["parent_trackid"]) && t["parent_trackid"]>=0 && t["time"]>=0 && t["ekin"]>=0,"Invalid track")
        check(t["parent_trackid"]==0 || haskey(processes,t["procid"]),"Unknown creation process")
        seen=Set([t["trackid"]]); parent=t["parent_trackid"]
        while parent!=0
            check(haskey(tracks,parent) && !(parent in seen),"Missing/cyclic parent")
            push!(seen,parent); parent=tracks[parent]["parent_trackid"]
        end
    end
    rot,shift=transform(m["coordinate_transform"])
    rawrows!([s["raw"] for s in e["steps"]],"stp/germanium",eid,counters,m)
    for s in e["steps"]
        r=s["raw"]
        for (key,rawkey) in (("raw_row_index","raw_row_index"),("energy_keV","edep"),("time_ns","time"),("track_id","trackid"),("parent_track_id","parent_trackid"),("particle_pdg","particle"))
            check(s[key]==r[rawkey],"Changed raw step field: "*key)
        end
        check(finite(s["energy_keV"]) && s["energy_keV"]>=0 && finite(s["time_ns"]) && s["time_ns"]>=0,"Invalid deposit")
        check(haskey(tracks,s["track_id"]),"Unknown deposit track")
        t=tracks[s["track_id"]]
        check(t["particle"]==s["particle_pdg"] && t["parent_trackid"]==s["parent_track_id"],"Deposit ancestry mismatch")
        for (suffix,key) in (("","position_mm"),("_pre","pre_position_mm"),("_post","post_position_mm"))
            global_m=[r[a*suffix] for a in ("xloc","yloc","zloc")]
            xyz=rot'*(1000 .* global_m .- shift)
            check(length(s[key])==3 && all(finite,s[key]) && isapprox(xyz,Float64.(s[key]);atol=1e-10,rtol=0),"Changed coordinate transform")
            suffix=="" && check(s["global_position_m"]==global_m,"Changed global position")
        end
    end
    photons=[Dict("raw_row_index"=>t["raw_row_index"],"track_id"=>t["trackid"],"parent_track_id"=>t["parent_trackid"],
        "time_ns"=>t["time"],"energy_keV"=>1000*t["ekin"],"creation_process"=>processes[t["procid"]]) for t in e["tracks"]
        if t["particle"]==22 && haskey(processes,t["procid"]) && occursin("radioactivedecay",lowercase(processes[t["procid"]]))]
    check(e["decay_photons"]==photons && e["decay_photon_count"]==length(photons) && e["line_photon_count"]==count(p->660<=p["energy_keV"]<=663,photons),"Photon census mismatch")
    check(all(x->finite(x) && x>=0,values(e["material_energy_keV"])),"Invalid recorded material ledger")
    check(e["pulse_groups"]==groups(e["steps"],m["grouping_policy"]["horizon_ns"]),"Changed pulse assignment or boundary flags")
    nothing
end
function foreach_decay(f,input)
    m=input.manifest; expected=0
    counters=Dict(t=>0 for t in ("vtx","particles","tracks","stp/germanium"))
    for c in m["chunks"]
        path=joinpath(dirname(input.path),c["file"])
        check(hashfile(path)==c["sha256"],"Chunk changed after inspection")
        count=0
        open(path) do io
            for line in eachline(io)
                check(count<c["count"] && sizeof(line)<=100_000_000,"Extra/oversized decay record")
                e=JSON.parse(line); validate_record!(e,expected,m,counters)
                if hasproperty(input,:prepared)
                    prepared=input.prepared
                    v=only(e["vtx"])
                    check(isapprox(1000 .* [v[a] for a in ("xloc","yloc","zloc")],Float64.(prepared["source_position_global_mm"]);rtol=0,atol=1e-10),"Wrong original source position")
                    materials=prepared["material_tables"]
                    check(Set(keys(e["material_energy_keV"]))==Set(values(materials)),"Missing/extra recorded material sum")
                    gemat=materials["stp/germanium"]
                    if Base.count(==(gemat),values(materials))==1
                        ge=sum((s["energy_keV"] for s in e["steps"]);init=0.)
                        check(isapprox(ge,e["material_energy_keV"][gemat];atol=1e-9,rtol=1e-12),"Ge material/step ledger mismatch")
                    end
                end
                f(e); count+=1; expected+=1
            end
        end
        check(count==c["count"] && hashfile(path)==c["sha256"],"Truncated/changed chunk")
    end
    check(expected==m["primary_count"],"Incomplete decay census")
    for (table,n) in counters; check(n==m["raw_tables"][table]["rows"],"Incomplete raw table: "*table); end
    expected
end
function recheck(input)
    for (p,h) in input.pins; check(hashfile(p)==h,"Dependency changed during consumption: "*basename(p)); end
end
end
