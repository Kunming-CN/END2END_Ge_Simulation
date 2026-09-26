using Test, LinearAlgebra
include("verify_electrostatics.jl")
const A=AnalyticElectrostatics
@testset "annulus operator and error gates" begin
    cases=[A.solve_case(n) for n in (17,33,65)]
    @test A.enforce(cases)
    @test A.grid(17) == A.grid(33)[1:2:end]
    @test A.grid(33) == A.grid(65)[1:2:end]
    @test all(isapprox.(cases[1]["analytic_field_V_m"], -500 ./ (cases[1]["faces_m"].*log(3));rtol=1e-14))
    for c in cases
        @test c["boundary_error_V"] == 0
        @test c["relative_flux_error"] < 0.001
        @test all(c["numeric_field_V_m"].<0)
    end
    for mapping in (:quadratic,:log),value in (0.0,42.0)
        c=A.solve_case(33;mapping=mapping,va=value,vb=value)
        @test maximum(abs,c["numeric_potential_V"].-value)<1e-10
        @test c["absolute_face_field_error_V_m"]<1e-6
        @test c["relative_face_field_error"]===nothing
        @test c["normalized_algebraic_residual"]<1e-11
    end
    logcase=A.solve_case(33;mapping=:log)
    @test logcase["relative_voltage_error"] < 1e-12
    reversed=A.solve_case(33;va=500.0,vb=0.0)
    @test all(reversed["numeric_field_V_m"].>0)
    @test maximum(abs,reversed["numeric_potential_V"].+cases[2]["numeric_potential_V"].-500)<1e-9
    altered=deepcopy(cases)
    v=copy(altered[3]["numeric_potential_V"]);v[20]+=0.5
    altered[3]=A.metrics(altered[3]["radii_m"],v,0.0,500.0)
    @test_throws ArgumentError A.enforce(altered)
    altered=deepcopy(cases);altered[2]["boundary_error_V"]=1e-9
    @test_throws ArgumentError A.enforce(altered)
    altered=deepcopy(cases);altered[3]["relative_face_field_error"]=0.1
    @test_throws ArgumentError A.enforce(altered)
    @test_throws ArgumentError A.grid(2)
    @test_throws ArgumentError A.grid(true)
    @test_throws ArgumentError A.grid(17;a=0.0)
    @test_throws ArgumentError A.grid(17;mapping=:unknown)
    @test_throws ArgumentError A.system([0.01,0.009,0.015],0,500)
    @test_throws ArgumentError A.system([0.005,NaN,0.015],0,500)
    @test_throws ArgumentError A.output_path(joinpath(A.ROOT,"models","must-not-write"))
    @test_throws ArgumentError A.output_path(joinpath(A.ROOT,".local"))
end
