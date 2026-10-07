# Public source-only fixtures: no milestone-private files, solver, drift or calibration.
using Test, JSON
include("decay_stream.jl")
const D=DecayStream
function fixture(source)
    tr=Dict("definition"=>"x_global_mm=R*x_local_mm+t","rotation_local_to_global"=>[[1,0,0],[0,1,0],[0,0,1]],"translation_global_mm"=>[1.,2.,3.])
    v=Dict("raw_row_index"=>0,"evtid"=>0,"time"=>0.,"n_part"=>1,"xloc"=>.001,"yloc"=>.002,"zloc"=>.003)
    p=Dict("raw_row_index"=>0,"evtid"=>0,"particle"=>source["pdg"],"vertexid"=>0,"ekin"=>0.,"px"=>0.,"py"=>0.,"pz"=>0.)
    line=first(source["diagnostic_lines"]);energy=sum(line["window_keV"])/2
    tracks=[Dict("raw_row_index"=>i-1,"evtid"=>0,"trackid"=>i,"parent_trackid"=>parent,
        "particle"=>pdg,"ekin"=>ke,"time"=>t,"procid"=>proc) for (i,(parent,pdg,ke,t,proc)) in enumerate([
        (0,source["pdg"],0.,1e20,-1),(1,source["ground_daughter_pdg"]+1,0.,0.,1),(2,22,energy/1000,1e12,1),(3,22,.001,1e12+1,2)])]
    steps=Any[]
    for (i,(e,t)) in enumerate([(0.,1e12),(2000.,1e12),(2.,1e12+99999),(3.,1e12+100000)])
        raw=Dict{String,Any}("raw_row_index"=>i-1,"evtid"=>0,"trackid"=>3,"parent_trackid"=>2,"particle"=>22,"time"=>t,"edep"=>e)
        for suffix in ("","_pre","_post"),(axis,value) in zip(("xloc","yloc","zloc"),(.004,.007,.009));raw[axis*suffix]=value;end
        push!(steps,Dict("raw_row_index"=>i-1,"raw"=>raw,"energy_keV"=>e,"time_ns"=>t,"track_id"=>3,"parent_track_id"=>2,"particle_pdg"=>22,
            "global_position_m"=>[.004,.007,.009],"position_mm"=>[3.,5.,6.],"pre_position_mm"=>[3.,5.,6.],"post_position_mm"=>[3.,5.,6.]))
    end
    processes=[Dict("procid"=>1,"name"=>"RadioactiveDecay"),Dict("procid"=>2,"name"=>"compt")]
    photons=[Dict("raw_row_index"=>t["raw_row_index"],"track_id"=>t["trackid"],"parent_track_id"=>t["parent_trackid"],
        "time_ns"=>t["time"],"energy_keV"=>t["ekin"]*1000,"creation_process"=>processes[t["procid"]]["name"]) for t in tracks if t["particle"]==22]
    lines=Dict{String,Any}(l["name"]=>count(p->l["window_keV"][1]<=p["energy_keV"]<=l["window_keV"][2],photons) for l in source["diagnostic_lines"])
    event=Dict("source_id"=>source["id"],"global_decay_id"=>0,"event_id"=>0,"vtx"=>[v],"particles"=>[p],"tracks"=>tracks,"steps"=>steps,
        "material_energy_keV"=>Dict("G4_Ge"=>2005.),"decay_photons"=>photons,"decay_photon_count"=>2,"line_photon_counts"=>lines,
        "line_photon_count"=>sum(values(lines)),"pulse_groups"=>D.groups(steps,100000.))
    tables=Dict(t=>Dict("rows"=>length(rows),"columns"=>Dict(k=>Dict() for k in keys(first(rows)) if k!="raw_row_index")) for (t,rows) in
        (("vtx",[v]),("particles",[p]),("tracks",tracks),("stp/germanium",[s["raw"] for s in steps])))
    manifest=Dict("source_id"=>source["id"],"source_contract"=>source,"coordinate_transform"=>tr,"raw_tables"=>tables,
        "processes"=>processes,"grouping_policy"=>Dict("horizon_ns"=>100000.),"primary_count"=>1)
    event,manifest
end
counters()=Dict(t=>0 for t in ("vtx","particles","tracks","stp/germanium"))
@testset "Registry-selected ion roots and all source-descendant photons" begin
    registry=JSON.parsefile(joinpath(D.ROOT,D.REGISTRY_REF))
    for source in filter(x->x["adapter"]==D.ADAPTER,registry["presets"])
        @test D.source_contract(source["id"],source)==source
        e,m=fixture(source);@test D.validate_record!(e,0,m,counters())===nothing
        @test length(e["decay_photons"])==2 && last(e["decay_photons"])["creation_process"]=="compt"
        @test e["steps"][2]["energy_keV"]==2000 && length(e["pulse_groups"])==2
        @test e["pulse_groups"][1]["relative_times_ns"]==[0.,99999.] && e["pulse_groups"][2]["relative_times_ns"]==[0.]
        @test e["pulse_groups"][2]["boundary_split_within_horizon"] && e["pulse_groups"][2]["recovery_not_established"]
        @test e["tracks"][1]["time"]==1e20 && e["tracks"][3]["time"]==1e12
        for mutate in (x->(x["source_id"]="foreign"),x->(x["particles"][1]["particle"]=22),
            x->(x["tracks"][1]["particle"]=22),x->(x["tracks"][2]["time"]=1.),x->(x["tracks"][3]["parent_trackid"]=3),
            x->(x["global_decay_id"]=1),x->delete!(x["tracks"][1],"procid"),x->(x["steps"][2]["energy_keV"]+=1),
            x->(x["tracks"][4]["time"]=1.),x->(x["steps"][2]["raw"]["time"]=0.;x["steps"][2]["time_ns"]=0.),
            x->(x["line_photon_counts"][first(keys(x["line_photon_counts"]))]=true),x->(x["steps"][2]["raw_row_index"]=9),x->(x["steps"][2]["pre_position_mm"][1]+=1),
            x->(x["decay_photons"][2]["creation_process"]="RadioactiveDecay"),x->pop!(x["decay_photons"]),
            x->(x["line_photon_count"]+=1),x->(x["line_photon_counts"][first(keys(x["line_photon_counts"]))]+=1),
            x->(x["pulse_groups"][2]["origin_time_ns"]+=1),x->(x["pulse_groups"][2]["recovery_not_established"]=false))
            bad=deepcopy(e);mutate(bad);@test_throws ArgumentError D.validate_record!(bad,0,m,counters())
        end
        wrong=deepcopy(e);wrong["tracks"][2]["particle"]=source["ground_daughter_pdg"]-10000
        @test_throws ArgumentError D.validate_record!(wrong,0,m,counters())
        late=deepcopy(e);late["tracks"][2]["particle"]=source["ground_daughter_pdg"]
        @test_throws ArgumentError D.validate_record!(late,0,m,counters())
        # Prompt photons can carry a ground-coded parent; no excitation is inferred from PDG suffix.
        prompt=deepcopy(late);prompt["tracks"][3]["time"]=100000.;prompt["decay_photons"][1]["time_ns"]=100000.
        @test D.validate_record!(prompt,0,m,counters())===nothing
        bad=deepcopy(source);bad["nuclear_policy"]["ground_secondary_lifetime_cap_ns"]=1;@test_throws ArgumentError D.source_contract(source["id"],bad)
        wrongtype=deepcopy(source);wrongtype["nuclear_policy"]["reset_initial_children_to_zero"]=1
        @test_throws ArgumentError D.source_contract(source["id"],wrongtype)
        zero=deepcopy(e);zero["steps"]=Any[];zero["pulse_groups"]=Any[];zero["material_energy_keV"]["G4_Ge"]=0
        @test D.validate_record!(zero,0,m,counters())===nothing
    end
    @test_throws ArgumentError D.source_contract("unregistered")
    @test_throws ArgumentError D.source_contract("cs137_point_decay_v1")
    @test_throws ArgumentError D.source_contract("mono_gamma_662_axis_v1")
end
@testset "Complete census, source anchor, zero records and rehashed mutations" begin
    source=first(filter(x->x["adapter"]==D.ADAPTER,JSON.parsefile(joinpath(D.ROOT,D.REGISTRY_REF))["presets"]))
    mktempdir(joinpath(D.ROOT,".local")) do dir
        e,m=fixture(source);path=joinpath(dir,"decays.jsonl");write(path,JSON.json(e)*"\n")
        m["chunks"]=[Dict("file"=>"decays.jsonl","count"=>1,"first_global_decay_id"=>0,"sha256"=>D.hashfile(path))]
        prepared=Dict("source_position_global_mm"=>[1.,2.,3.],"material_tables"=>Dict("stp/germanium"=>"G4_Ge"))
        input=(path=joinpath(dir,"manifest.json"),manifest=m,pins=Dict(path=>D.hashfile(path)),prepared=prepared)
        seen=Any[];@test D.foreach_decay(x->push!(seen,x),input)==1 && seen==[e];@test D.recheck(input)===nothing
        bad=deepcopy(e);bad["pulse_groups"][1]["row_indices"]=[1]
        write(path,JSON.json(bad)*"\n");m["chunks"][1]["sha256"]=D.hashfile(path);@test_throws ArgumentError D.foreach_decay(identity,input)
        write(path,JSON.json(e)*"\n");m["chunks"][1]["sha256"]=D.hashfile(path)
        prepared["source_position_global_mm"][1]+=1;@test_throws ArgumentError D.foreach_decay(identity,input)
        prepared["source_position_global_mm"][1]-=1;m["raw_tables"]["tracks"]["rows"]+=1;@test_throws ArgumentError D.foreach_decay(identity,input)
    end
end
println("Generic source stream fixtures passed; science calls 0")
