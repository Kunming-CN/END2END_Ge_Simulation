using Test
include("diagnose_collection.jl")
const C=CollectionDiagnostics
@testset "explicit endpoint classification" begin
    @test C.stop_label([1],false,true,true)=="geometric_contact"
    @test C.stop_label(Int[],true,true,true)=="step_limit"
    @test C.stop_label(Int[],false,true,true)=="stationary_in_zero_field"
    @test C.stop_label(Int[],false,false,true)=="unresolved_stop"
    @test C.stop_label(Int[],false,true,false)=="unresolved_stop"
    @test all(>(0),C.DEPTHS_MM)
    @test issorted(C.DEPTHS_MM)
    @test length(unique(C.DEPTHS_MM))==length(C.DEPTHS_MM)
    @test_throws ArgumentError C.main(String[])
    @test_throws ArgumentError C.main(["--output","models/unsafe"])
    @test_throws ArgumentError C.one_point(nothing,[1.0,2.0,3.0],0.0,nothing,nothing)
    @test_throws ArgumentError C.one_point(nothing,[1.0,NaN,3.0],2.0,nothing,nothing)
end
@testset "completion guard" begin
    report=Dict("status"=>"running")
    @test_throws ErrorException C.mark_complete!(report;verify=()->error("injected checksum failure"))
    @test report["status"]=="running"
    C.mark_complete!(report;verify=()->nothing)
    @test report["status"]=="completed_diagnostics_only"
end
C.Q.verify_model_files()
