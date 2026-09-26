using Test, Random, LinearAlgebra
include("validate_transition.jl")
const V=TransitionValidation
const Q=SSDQuickstart
@testset "transition reporting and coefficient guards" begin
    @test V.brackets([0.1,0.2,0.3],[0.0,0.0,2.0],1.0)==Dict("below_mm"=>0.2,"above_mm"=>0.3,"threshold_V_cm"=>1.0)
    @test isnothing(V.brackets([0.1,0.2],[0.0,0.0],1.0))
    @test isnothing(V.brackets([0.1,0.2],[1.0,2.0],0.0)["below_mm"])
    @test_throws ArgumentError V.brackets([0.2,0.1],[0.0,1.0],0.0)
    @test_throws ArgumentError V.brackets([0.1,0.2],[0.0,NaN],0.0)
    @test_throws ArgumentError Q.solve_fields!(nothing,nothing,nothing;potential_rechecks=0)
    @test_throws ArgumentError Q.solve_fields!(nothing,nothing,nothing;potential_rechecks=65)
    sim,_=V.R.setup_simulation("AK02";temperature=77.0)
    @test 0.70 < V.pn_depth(sim) < 0.72
    original=sim.detector
    for depth in (0.1,0.5,1.0)
        p=V.SSD.CartesianPoint{Float64}((12.65-depth)/1000,0,0.0047)
        cdm=original.semiconductor.charge_drift_model
        frozen=V.frozen_model(cdm,p)
        @test frozen.temperature==77
        for carrier in (V.SSD.Electron,V.SSD.Hole)
            actual=V.SSD.calculate_mobility(cdm,p,carrier)
            @test isfinite(actual)&&actual>0
            @test V.SSD.calculate_mobility(frozen,p,carrier)==actual
            shifted=V.SSD.CartesianPoint{Float64}(0.01,0,0.0047)
            @test V.SSD.calculate_mobility(frozen,shifted,carrier)==actual
        end
    end
    @test sim.detector===original
    state=Dict{String,Any}()
    field_before=sim.electric_field
    @test_throws ErrorException V.with_restored_state(sim,state) do
        sim.detector=V.SSD.SolidStateDetector(original,V.SSD.NoChargeTrappingModel{Float64}())
        error("injected after detector replacement")
    end
    @test state["restored_state"]
    @test sim.detector===original && sim.electric_field===field_before
    Random.seed!(401)
    n=2048;D=0.01;t=1e-7
    delta=sqrt(2D*t).*randn(n,3)
    @test V.moments(delta,D,t,n)["expected_variance_m2"]==2D*t
    @test_throws ArgumentError V.moments(delta,NaN,t,n)
    @test_throws ArgumentError V.moments(delta,D,-t,n)
    @test_throws ArgumentError V.moments(delta,D,t,n-1)
    @test_throws ArgumentError V.moments(fill(NaN,n,3),D,t,n)
    @test_throws ArgumentError V.moments(10 .*delta,D,t,n)
    correlated=hcat(delta[:,1],delta[:,1],delta[:,1])
    @test_throws ArgumentError V.moments(correlated,D,t,n)
    @test_throws ArgumentError V.main(["--phase","fields","--output",".local/unused","--parcels","8192"])
    @test_throws ArgumentError V.main(["--phase","mobility","--output",".local/unused","--parcels","0"])
    @test_throws ArgumentError V.main(["--phase","mobility","--output",".local/unused","--parcels","9000"])
    Q.verify_model_files()
end
