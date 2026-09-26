using Test, JSON
include("replay.jl")
const R=SSDReplay
const Q=SSDQuickstart
@testset "causal charge composition" begin
    c=(delay=3.5,times=[0.0,1.0,2.0],charge=[0.0,1.0,2.0])
    t,q=R.causal_sum([c],0.5)
    @test all(q[t .< 3.5] .== 0)
    @test q[findfirst(==(4.0),t)] == 0.5
    @test q[end] == 2
    c2=(delay=0.0,times=[0.0,1.0],charge=[0.0,-0.75])
    t,q=R.causal_sum([c,c2],0.5)
    @test q[end] == 1.25
    @test q[findfirst(==(3.0),t)] == -0.75
    @test R.causal_sum([c2,c],0.5) == (t,q)
    @test all(last(R.causal_sum(Any[],2.0)) .== 0)
    @test_throws ArgumentError R.causal_sum([merge(c,(delay=-1.0,))],0.5)
    @test_throws ArgumentError R.causal_sum([merge(c,(delay=1e12,))],0.5)
    @test_throws ArgumentError R.causal_sum([merge(c,(charge=[0.0,NaN,2.0],))],0.5)
    @test_throws ArgumentError R.causal_sum([merge(c,(times=[0.0,1.0,1.0],))],0.5)
end
function fixture()
    p=[3.0,0.0,5.0]
    s=Dict("raw_row_index"=>0,"energy_keV"=>1.0,"time_ns"=>101.0,
        "position_mm"=>p,"global_position_m"=>p./1000,"pre_position_mm"=>p,"post_position_mm"=>p,
        "track_id"=>2,"parent_track_id"=>1,"particle_pdg"=>11)
    Dict("schema_version"=>1,"model_id"=>"AK02","model_sha256"=>Q.model_entry("AK02")["model_sha256"],
        "source_lh5_sha256"=>"0"^64,"geometry_sha256"=>"0"^64,"macro_sha256"=>"0"^64,
        "units"=>Dict("energy"=>"keV","length"=>"mm","time"=>"ns"),
        "coordinate_transform"=>Dict("rotation_local_to_global"=>[[1,0,0],[0,1,0],[0,0,1]],
            "translation_global_mm"=>[0,0,0],"definition"=>"x_global_mm=R*x_local_mm+t"),
        "primary_count"=>2,"energy_sum_keV"=>1.0,
        "events"=>[Dict("event_id"=>0,"primary_time_ns"=>100.0,"steps"=>[s]),
                    Dict("event_id"=>1,"primary_time_ns"=>100.0,"steps"=>Any[])])
end
@testset "interchange and explicit temperature" begin
    d=fixture()
    @test R.check_document(d) === d
    @test d["events"][1]["steps"][1]["time_ns"]-d["events"][1]["primary_time_ns"] == 1
    x=deepcopy(d); x["units"]["length"]="m"; @test_throws ArgumentError R.check_document(x)
    x=deepcopy(d); x["events"][2]["event_id"]=0; @test_throws ArgumentError R.check_document(x)
    x=deepcopy(d); push!(x["events"][1]["steps"],deepcopy(x["events"][1]["steps"][1])); @test_throws ArgumentError R.check_document(x)
    x=deepcopy(d); x["events"][1]["steps"][1]["time_ns"]=99.0; @test_throws ArgumentError R.check_document(x)
    x=deepcopy(d); x["energy_sum_keV"]=2.0; @test_throws ArgumentError R.check_document(x)
    x=deepcopy(d); x["events"][1]["steps"][1]["global_position_m"][1]=100.0; @test_throws ArgumentError R.check_document(x)
    x=deepcopy(d); x["coordinate_transform"]["rotation_local_to_global"][1][1]=-1; @test_throws ArgumentError R.check_document(x)
    x=deepcopy(d)
    x["coordinate_transform"]["rotation_local_to_global"]=[[0,0,1],[0,1,0],[-1,0,0]]
    x["coordinate_transform"]["translation_global_mm"]=[20,30,40]
    x["events"][1]["steps"][1]["global_position_m"]=[0.025,0.03,0.037]
    @test R.check_document(x) === x # Unit transform only, not a rotated G4 test.
    meta=Dict(k=>deepcopy(d[k]) for k in ("model_id","model_sha256","primary_count","coordinate_transform"))
    @test R.validate_prepared_identity(d,meta) === nothing
    @test_throws ArgumentError R.validate_prepared_identity(x,meta)
    meta["coordinate_transform"]=deepcopy(x["coordinate_transform"])
    @test_throws ArgumentError R.validate_prepared_identity(x,meta)
    sap78,_=R.setup_simulation("SAP22")
    sap77,_=R.setup_simulation("SAP22";temperature=77.0)
    field=R.SSD.SVector{3,Float64}(100.0,200.0,300.0)
    @test R.SSD.getVe(field,sap78.detector.semiconductor.charge_drift_model) == R.SSD.getVe(field,sap77.detector.semiconductor.charge_drift_model)
    @test R.SSD.getVh(field,sap78.detector.semiconductor.charge_drift_model) == R.SSD.getVh(field,sap77.detector.semiconductor.charge_drift_model)

    for model in ("AK02","SAP22")
        s,original=R.setup_simulation(model;temperature=77.0)
        @test original == 78
        @test s.detector.semiconductor.temperature == 77
        @test R.validate_deposits(d,s) == 1
    end
    s,_=R.setup_simulation("AK02")
    bad=deepcopy(d); bad["events"][1]["steps"][1]["position_mm"]=[0.0,0.0,1.0]
    @test_throws ArgumentError R.validate_deposits(bad,s) # In the bore, do not move it into Ge.
    @test_throws ArgumentError R.setup_simulation("AK02";temperature=0.0)
    @test R.options(["--help"]) === nothing
    @test_throws ArgumentError R.options(["--unknown","x"])
end
@testset "actual handoff geometry/provenance" begin
    for directory in filter(!=("--linearity"), ARGS)
        d,meta=R.load_input(joinpath(directory,"events.json"))
        sim,_=R.setup_simulation(d["model_id"])
        @test R.geometry_check(meta,sim)["ssd_contour_matches"]
        @test R.validate_deposits(d,sim) >= 0
    end
end
Q.verify_model_files()

if "--linearity" in ARGS
    dirs=filter(!=("--linearity"),ARGS)
    length(dirs)==1 || error("--linearity requires exactly one prepared directory")
    d,meta=R.load_input(joinpath(only(dirs),"events.json"))
    sim,_=R.setup_simulation(d["model_id"])
    cfg=Q.parse_args(["--model",d["model_id"],"--position-mm","3,0,5","--precision","64",
        "--min-grid-mm","0.05","--max-iterations","50000","--output",joinpath(Q.ROOT,".local","linearity-unused")])
    Q.solve_fields!(sim,cfg,Q.prepare_backend("cpu");sor_consts=1.0,potential_rechecks=4)
    selected=deepcopy(first(filter(e->any(s->s["energy_keV"]>0,e["steps"]),d["events"])))
    for step in selected["steps"]
        step["time_ns"]=selected["primary_time_ns"] # Explicit synthetic simultaneous counterpart, not altered truth.
    end
    split=R.replay_event(selected,sim,cfg)
    positive=filter(s->s["energy_keV"]>0,selected["steps"])
    locations=[R.SSD.CartesianPoint{Float64}((Float64.(s["position_mm"])./1000)...) for s in positive]
    evt=R.SSD.Event(locations,[s["energy_keV"]*R.u"keV" for s in positive])
    R.SSD.drift_charges!(evt,sim;Δt=2 * R.u"ns",max_nsteps=cfg.max_steps,geometry_check=true,
        diffusion=false,self_repulsion=false,end_drift_when_no_field=true,verbose=false)
    R.SSD.get_signal!(evt,sim,1;Δt=2 * R.u"ns",signal_unit=R.u"keV")
    w=evt.waveforms[1]
    combined=(delay=0.0,times=Float64.(R.ustrip.(R.u"ns",w.time)),charge=Float64.(R.ustrip.(R.u"keV",w.signal)))
    _,difference=R.causal_sum([combined,(delay=0.0,times=split.times,charge=-split.signal)],cfg.dt)
    @testset "SSD simultaneous multi-deposit parity" begin
        @test maximum(abs,difference) <= 1e-8
        @test abs(last(difference)) <= 1e-8
    end
    println(JSON.json(Dict("linearity_model"=>d["model_id"],"deposits"=>length(positive),
        "maximum_difference_keV"=>maximum(abs,difference),"scope"=>"Synthetic simultaneous version of one real event; no interacting clouds")))
end
