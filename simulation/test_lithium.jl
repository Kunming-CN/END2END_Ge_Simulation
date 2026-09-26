# Pure helper/provenance tests only. No field solves, drift or diffusion runs.
using Test, JSON
include("diagnose_lithium.jl")
const L=LithiumDiagnostics
const Q=L.Q

@testset "Independent endpoint flags and grid labels" begin
    o=Dict("net_impurity_cm3"=>1.0,"nearest_grid_undepleted"=>true,
        "nearest_grid_inactive"=>true,"geometric_contacts"=>[2],"field_exactly_zero"=>true)
    original=deepcopy(o)
    @test L.region(o)=="n-nearest-undepleted-inactive-bit"
    f=L.flags(o,2501,2501,true)
    @test all(values(f)) # Contact, step limit and stationary zero E can coexist.
    @test o==original
    o["geometric_contacts"]=Int[]
    @test !L.flags(o,2501,2501,true)["geometric_contact"]
    @test L.flags(o,2501,2501,true)["at_step_limit"]
    o["net_impurity_cm3"]=-1.0; o["nearest_grid_undepleted"]=false
    @test L.region(o)=="p-nearest-depleted-inactive-bit"
    o["net_impurity_cm3"]=0.0; o["nearest_grid_inactive"]=false
    @test L.region(o)=="compensated-nearest-depleted-no-inactive-bit"
    @test !L.flags(o,2,2501,false)["n_type"]
end

@testset "Signed conditional Ramo accounting; no clipping" begin
    full=L.remainder(2.0,0.0,1.0)
    @test full["conditional_remainder_keV"]==0
    @test !full["weighting_out_of_range"]&&!full["negative_remainder"]
    partial=L.remainder(2.0,0.25,0.75)
    @test partial["conditional_remainder_keV"]==1.0
    @test 2*(0.75-0.25)+partial["conditional_remainder_keV"]==2.0
    negative=L.remainder(2.0,-0.1,1.2)
    @test negative["conditional_remainder_keV"]≈-0.6
    @test negative["electron_component_keV"]==-0.2
    @test negative["abs_electron_weighting"]==0.1
    @test negative["weighting_out_of_range"]&&negative["negative_remainder"]
    @test L.remainder(1.0,1.1,-0.2)["conditional_remainder_keV"]≈2.3
    for args in ((0.,0.,1.),(-1.,0.,1.),(1.,NaN,1.),(1.,0.,Inf))
        @test_throws ArgumentError L.remainder(args...)
    end
end

@testset "Numerical parcel statistics, input immutability and display" begin
    @test L.sample_stats(fill(0.5,32),fill(1/32,32))["sem"]==0
    s=L.sample_stats([1.,2.,3.,4.],fill(0.25,4))
    @test s["mean"]==2.5
    @test s["sem"]≈sqrt(5/12)
    @test s["outside_unit_range"]==3
    @test L.sample_stats([0.2],[1.0])["sem"]===nothing
    for (v,w) in (([1.,2.],[0.5,0.4]),([1.,2.],[0.2,0.8]),([Inf],[1.]),([1.],[-1.]),(Float64[],Float64[]))
        @test_throws ArgumentError L.sample_stats(v,w)
    end
    before=([[1.,2.,3.]],[[31.25]])
    @test L.unchanged(before,deepcopy(before))===nothing
    moved=deepcopy(before); moved[1][1][1]+=1
    @test_throws ArgumentError L.unchanged(before,moved)
    lost=deepcopy(before); lost[2][1][1]=0
    @test_throws ArgumentError L.unchanged(before,lost)
    @test_throws ArgumentError L.deposit(nothing,[NaN,0.,0.],1.,nothing,nothing,nothing)
    traces=[(delay=0.,times=[0.,2.,4.],charge=[0.,0.1,0.2]),(delay=0.,times=[0.,2.],charge=[0.,0.3])]
    old=deepcopy(traces); display,finals=L.mean_trace(traces,traces,5000.)
    @test traces==old
    @test finals==(0.5,0.5)
    @test length(display["time_ns"])<=300
    @test last(display["time_ns"])==5000
    @test last(display["original_fraction"])==0.5
    @test first(display["original_fraction"])==0
end

@testset "Fixed work, seeds, actual times and sensitivity" begin
    @test L.DEPTHS==[0.1,0.3,0.45,0.50,0.55,0.60,0.65,0.8,1.0]
    @test L.GRID_CASES==[("baseline",0.05,4),("contrast50",0.05,8),("contrast25",0.025,8)]
    @test L.parcel_seed(2609261,1)==2609261001
    @test length(unique([L.parcel_seed(s,j) for s in L.SEEDS for j in 1:32]))==96
    @test_throws ArgumentError L.parcel_seed(2609261,33)
    @test_throws ArgumentError L.parcel_seed(99,1)
    @test L.time_config(2.,5000.).max_steps==2501
    @test L.time_config(4.,5000.).max_steps==1251
    @test L.time_config(2.,10000.).max_steps==5001
    for pair in ((NaN,5000.),(2.,Inf),(0.,5000.),(2.,20000.),(1.,5000.))
        @test_throws ArgumentError L.time_config(pair...)
    end
    @test L.check_times([0.,0.5,2.];cap=2.)===nothing
    for times in ([0.,NaN],[0.,Inf],[0.,1.,1.],[0.,-1.],[1.,2.],Float64[])
        @test_throws ArgumentError L.check_times(times)
    end
    @test_throws ArgumentError L.check_times([0.,3.];cap=2.)
    stats(v)=Dict("mean"=>v,"sem"=>0.001)
    cloud(dt,v)=Dict("grid_case"=>"baseline","depth_mm"=>0.3,"seed"=>2609261,"diffusion"=>true,
        "dt_ns"=>dt,"horizon_ns"=>5000.,"original_stats"=>stats(v),"no_trapping_stats"=>stats(v))
    items=[Dict("clouds"=>[cloud(2.,0.5),cloud(4.,0.6)])]
    result=L.sensitivities(items)
    @test length(result)==2
    @test all(!r["passed"]&&r["prospective_gate"]==0.03 for r in result)
    @test items[1]["clouds"][2]["original_stats"]["mean"]==0.6 # Failed sensitivity is retained.
    grid=(data=reshape([0.,1.,2.,3.],2,1,2),grid=(axes=([0.,1.],[0.],[0.,1.]),))
    snap=L.grid_snapshot(grid)
    @test snap["shape"]==[2,1,2]
    grid.data[1]=NaN
    @test_throws ArgumentError L.grid_snapshot(grid)
end

@testset "Read-only source pins, model hashes, readout and output boundaries" begin
    @test L.check_hashes(@__DIR__,L.PINNED)===nothing
    @test L.check_hashes(dirname(pathof(L.SSD)),L.SDK_PINS)===nothing
    @test Q.verify_model_files() isa AbstractDict
    @test L.check_hashes(Q.MODEL_DIR,Dict(model*".yaml"=>hash for (model,hash) in L.MODEL_PINS))===nothing
    @test_throws ArgumentError Q.validate_output(joinpath(Q.ROOT,"models","unsafe"))
    @test_throws ArgumentError Q.validate_output(joinpath(Q.ROOT,".local","..","unsafe"))
    @test_throws ArgumentError L.options(String[])
    mkpath(joinpath(Q.ROOT,".local"))
    mktempdir(joinpath(Q.ROOT,".local")) do dir
        file=joinpath(dir,"readout-config.json"); baseline=joinpath(@__DIR__,"readout_demo.json")
        before=Q.sha256file(baseline); config=JSON.parsefile(baseline); config["expected_primary_count"]=7
        Q.save_json(file,config)
        binding=Dict("file"=>"readout-config.json","allowed_changed_fields"=>["expected_primary_count"],
            "baseline_sha256"=>before,"effective_sha256"=>Q.sha256file(file))
        m=Dict("readout_config"=>binding,"settings"=>Dict("events_per_model"=>7),"artifacts"=>Dict("readout-config.json"=>Q.sha256file(file)))
        @test L.readout_config(dir,m)===nothing
        @test L.check_hashes(dir,m["artifacts"])===nothing
        config["gain"]+=1; Q.save_json(file,config)
        @test_throws ArgumentError L.check_hashes(dir,m["artifacts"])
        binding["effective_sha256"]=m["artifacts"]["readout-config.json"]=Q.sha256file(file)
        @test_throws ArgumentError L.readout_config(dir,m) # Deliberately resealed physics edit.
        @test Q.sha256file(baseline)==before
        @test_throws ArgumentError Q.validate_output(dir)
        @test_throws ArgumentError L.check_hashes(dir,Dict("../escape"=>"0"^64))
        @test_throws ArgumentError L.options(["--input",dir,"--output",joinpath(dir,"nested")])
        @test_throws ArgumentError L.options(["--input",dir,"--output",joinpath(dir,"nested"),"--phase","unknown"])
    end
end

@testset "Noncancelling conditional completion budget" begin
    cancelled=L.remainder(1.0,-0.5,0.5)
    @test cancelled["conditional_remainder_keV"]==0
    @test cancelled["absolute_component_sum_keV"]==1
    @test !cancelled["small_conditional_remainder"]
    @test cancelled["weighting_out_of_range"]
    full=L.remainder(3.0,1e-9,1.0)
    @test full["small_conditional_remainder"]
    @test full["absolute_component_sum_keV"]≈3e-9
end
