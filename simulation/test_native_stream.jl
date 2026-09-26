using Test, JSON
include("native_stream.jl")
const S=NativeStream
function fixture()
    tr=Dict("definition"=>"x_global_mm=R*x_local_mm+t","rotation_local_to_global"=>[[1,0,0],[0,1,0],[0,0,1]],"translation_global_mm"=>[1.,2.,3.])
    v=Dict("raw_row_index"=>0,"evtid"=>0,"time"=>0.,"n_part"=>1)
    p=Dict("raw_row_index"=>0,"evtid"=>0,"particle"=>1000551370,"vertexid"=>0,"ekin"=>0.,"px"=>0.,"py"=>0.,"pz"=>0.)
    tracks=[Dict("raw_row_index"=>i-1,"evtid"=>0,"trackid"=>i,"parent_trackid"=>i-1,
        "particle"=>pdg,"ekin"=>ke,"time"=>t,"procid"=>i==1 ? -1 : 1) for (i,(pdg,ke,t)) in enumerate([(1000551370,0.,0.),(1000561370,0.,0.),(22,.661657,1e12)])]
    steps=Any[]
    for (i,(energy,t)) in enumerate([(0.,0.),(2000.,1e12),(2.,1e12+99999),(3.,1e12+100000)])
        raw=Dict{String,Any}("raw_row_index"=>i-1,"evtid"=>0,"trackid"=>3,"parent_trackid"=>2,"particle"=>22,"time"=>t,"edep"=>energy)
        for suffix in ("","_pre","_post"),(axis,value) in zip(("xloc","yloc","zloc"),(.004,.007,.009)); raw[axis*suffix]=value; end
        push!(steps,Dict("raw_row_index"=>i-1,"raw"=>raw,"energy_keV"=>energy,"time_ns"=>t,"track_id"=>3,"parent_track_id"=>2,"particle_pdg"=>22,
            "global_position_m"=>[.004,.007,.009],"position_mm"=>[3.,5.,6.],"pre_position_mm"=>[3.,5.,6.],"post_position_mm"=>[3.,5.,6.]))
    end
    photons=[Dict("raw_row_index"=>2,"track_id"=>3,"parent_track_id"=>2,"time_ns"=>1e12,"energy_keV"=>.661657*1000,"creation_process"=>"RadioactiveDecay")]
    e=Dict("global_decay_id"=>0,"event_id"=>0,"vtx"=>[v],"particles"=>[p],"tracks"=>tracks,"steps"=>steps,
        "material_energy_keV"=>Dict("G4_Ge"=>2005.),"decay_photons"=>photons,"decay_photon_count"=>1,"line_photon_count"=>1,
        "pulse_groups"=>S.groups(steps,100000.))
    tables=Dict(t=>Dict("rows"=>length(rows),"columns"=>Dict(k=>Dict() for k in keys(first(rows)) if k!="raw_row_index")) for (t,rows) in
        (("vtx",[v]),("particles",[p]),("tracks",tracks),("stp/germanium",[s["raw"] for s in steps])))
    m=Dict("coordinate_transform"=>tr,"raw_tables"=>tables,"processes"=>[Dict("procid"=>1,"name"=>"RadioactiveDecay")],"grouping_policy"=>Dict("horizon_ns"=>100000.),"primary_count"=>1)
    e,m
end
counters()=Dict(t=>0 for t in ("vtx","particles","tracks","stp/germanium"))
@testset "Ion clock, exact groups, raw provenance and mutation gates" begin
    e,m=fixture(); @test S.validate_record!(e,0,m,counters())===nothing
    g=e["pulse_groups"]
    @test length(g)==2 && g[1]["row_indices"]==[1,2] && g[2]["row_indices"]==[3]
    @test g[2]["boundary_split_within_horizon"] && g[2]["recovery_not_established"]
    @test g[1]["relative_times_ns"]==[0.,99999.] && g[2]["relative_times_ns"]==[0.]
    @test e["steps"][1]["energy_keV"]==0 && e["steps"][2]["energy_keV"]>663
    # No photon-energy ceiling on ion descendants; no absolute-delay waveform allocation.
    for mutate in (
        x->(x["event_id"]=1),x->(x["global_decay_id"]=1),
        x->push!(x["pulse_groups"][1]["row_indices"],3),
        x->(x["pulse_groups"][2]["origin_time_ns"]+=1),
        x->(x["pulse_groups"][2]["recovery_not_established"]=false),
        x->popfirst!(x["steps"]),x->(x["steps"][2]["raw_row_index"]=2),
        x->(x["steps"][2]["energy_keV"]+=1),x->(x["steps"][2]["time_ns"]+=1),
        x->(x["steps"][2]["pre_position_mm"][1]+=1),
        x->(x["steps"][2]["parent_track_id"]=1),
        x->(x["tracks"][3]["parent_trackid"]=3),x->pop!(x["tracks"]),
        x->delete!(x["tracks"][1],"procid"),
        x->(x["particles"][1]["particle"]=22),x->(x["tracks"][2]["time"]=1.),
        x->(x["decay_photons"][1]["energy_keV"]+=1),x->(x["line_photon_count"]=0))
        bad=deepcopy(e); mutate(bad); @test_throws ArgumentError S.validate_record!(bad,0,m,counters())
    end
    bad=deepcopy(m); bad["coordinate_transform"]["rotation_local_to_global"][1][1]=-1
    @test_throws ArgumentError S.transform(bad["coordinate_transform"])
    z=deepcopy(e); z["steps"]=Any[]; z["pulse_groups"]=Any[]
    @test S.validate_record!(z,0,m,counters())===nothing
    @test isempty(S.groups([e["steps"][1]],100000.))
end
@testset "Streaming hashes, complete census and rehashed mutations" begin
    mktempdir(joinpath(dirname(@__DIR__),".local")) do dir
        e,m=fixture(); path=joinpath(dir,"decays.jsonl")
        write(path,JSON.json(e)*"\n")
        m["chunks"]=[Dict("file"=>"decays.jsonl","count"=>1,"first_global_decay_id"=>0,"sha256"=>S.hashfile(path))]
        input=(path=joinpath(dir,"manifest.json"),manifest=m,pins=Dict(path=>S.hashfile(path)))
        seen=Any[]; @test S.foreach_decay(x->push!(seen,x),input)==1
        @test seen==[e]; @test S.recheck(input)===nothing
        write(path,JSON.json(e)*"\n\n")
        @test_throws ArgumentError S.foreach_decay(identity,input)
        # A maliciously rehashed changed group must still fail semantic validation.
        bad=deepcopy(e); bad["pulse_groups"][1]["row_indices"]=[1]
        write(path,JSON.json(bad)*"\n"); m["chunks"][1]["sha256"]=S.hashfile(path)
        @test_throws ArgumentError S.foreach_decay(identity,input)
        write(path,JSON.json(e)*"\n"); m["chunks"][1]["sha256"]=S.hashfile(path)
        m["raw_tables"]["stp/germanium"]["rows"]+=1
        @test_throws ArgumentError S.foreach_decay(identity,input)
        pins=Dict{String,String}(); @test S.pin!(pins,path,S.hashfile(path))==realpath(path)
        @test_throws ArgumentError S.pin!(pins,path,"0"^64)
        write(joinpath(dir,"incomplete.json"),JSON.json(Dict("kind"=>S.KIND,"status"=>"failed")))
        @test_throws ArgumentError S.inspect(joinpath(dir,"incomplete.json"))
    end
end

@testset "Prepared-source position and material ledger integration" begin
    mktempdir(joinpath(dirname(@__DIR__),".local")) do dir
        e,m=fixture()
        for (key,value) in zip(("xloc","yloc","zloc"),(.001,.002,.003))
            only(e["vtx"])[key]=value
            m["raw_tables"]["vtx"]["columns"][key]=Dict()
        end
        path=joinpath(dir,"decays.jsonl"); write(path,JSON.json(e)*"\n")
        m["chunks"]=[Dict("file"=>"decays.jsonl","count"=>1,"first_global_decay_id"=>0,"sha256"=>S.hashfile(path))]
        prepared=Dict("source_position_global_mm"=>[1.,2.,3.],"material_tables"=>Dict("stp/germanium"=>"G4_Ge"))
        input=(path=joinpath(dir,"manifest.json"),manifest=m,pins=Dict(path=>S.hashfile(path)),prepared=prepared)
        seen=Any[]; @test S.foreach_decay(x->push!(seen,x),input)==1
        @test seen==[e]
        bad=deepcopy(e); bad["material_energy_keV"]["G4_Ge"]+=1
        write(path,JSON.json(bad)*"\n"); m["chunks"][1]["sha256"]=S.hashfile(path)
        @test_throws ArgumentError S.foreach_decay(identity,input)
        write(path,JSON.json(e)*"\n"); m["chunks"][1]["sha256"]=S.hashfile(path)
        prepared["source_position_global_mm"][1]+=1
        @test_throws ArgumentError S.foreach_decay(identity,input)
    end
end
