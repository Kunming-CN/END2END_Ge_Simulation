using Test
include("gegi_signal_helpers.jl")
include("readout_profiles.jl")
const H=GeGISignalHelpers;const E=Readout;const P=ReadoutProfiles

@testset "GeGI charge timing and independent wiring" begin
    t=[0.,1.,2.,3.,4.];q=[0.,0.,2.,8.,10.]
    @test H.crossing_time(t,q) == 2.5
    @test H.crossing_time(t,7 .*q) == 2.5
    @test H.crossing_time(t,-q) === nothing
    @test H.crossing_time(t,zeros(5)) === nothing
    @test H.crossing_time(t,q,0.9) == 3.5
    # A mirror transient crosses early, falls back, then the collected charge
    # rises again. Its first crossing is not the stable-collection timing.
    recross_t=collect(0.:5.);recross_q=[0.,0.6,1.,0.2,0.6,1.]
    @test H.crossing_time(recross_t,recross_q) ≈ 3.75
    @test H.crossing_time(recross_t,10 .*recross_q) ≈ 3.75
    @test H.crossing_time(recross_t,recross_q,0.9) ≈ 4.75
    @test_throws ArgumentError H.crossing_time([0.,1.,1.],[0.,1.,2.])
    @test H.monotonic_depth_table([-1.,0.,1.],[9.,5.,1.])
    @test !H.monotonic_depth_table([-1.,0.,1.],[9.,9.,1.])
    @test !H.monotonic_depth_table([-1.,0.,1.],[9.,nothing,1.])
    @test !H.monotonic_depth_table([-1.,0.,1.],[1.,5.,3.])

    profile=P.load(joinpath(@__DIR__,"native_readout_profile.json"))
    config=profile.config;dt=1.;eion=2.95
    matrix=E.transition(config,dt);cal=P.calibration(config,eion,dt,matrix)
    positive=E.process_event(t,q,config,eion,cal,matrix)
    negative_input=-q
    wired=E.process_event(t,-negative_input,config,eion,cal,matrix)
    @test positive["accepted"] && wired["accepted"]
    @test positive["reconstructed_energy_keV"]==wired["reconstructed_energy_keV"]
    @test positive["current_balance"]["passed"] && wired["current_balance"]["passed"]
    @test negative_input[end] == -10. # Wiring does not alter retained signed charge.
    @test cal["energy_keV"]==500. # Independent calibration is not an event's truth.
end
