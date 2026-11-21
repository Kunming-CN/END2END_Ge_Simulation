include(joinpath(@__DIR__,"..","simulation","gegi_campaign_response.jl"))
using Test, Unitful
const C=GeGICampaignResponse;const G=C.G;const B=G.NativeBoundaryGuard

@testset "Configured drift duration has no artificial sample ceiling" begin
    req=Dict("selection"=>Dict("threads"=>1),"numerics"=>Dict("drift_dt_ns"=>1.,"drift_cap_ns"=>1000.))
    before=deepcopy(req)
    @test G.numerics(req).max_steps==1001
    @test req==before
    for (cap,steps) in ((5.,6),(1000.25,1002),(20000.,20001))
        candidate=deepcopy(req);candidate["numerics"]["drift_cap_ns"]=cap
        @test G.numerics(candidate).max_steps==steps
    end
    for (dt,cap) in ((0.,1000.),(NaN,1000.),(1.,Inf),(1.,1.),(1.,1e30))
        candidate=deepcopy(req);candidate["numerics"]["drift_dt_ns"]=dt;candidate["numerics"]["drift_cap_ns"]=cap
        @test_throws ArgumentError G.numerics(candidate)
    end
end

@testset "Native waveform errors identify exact signed samples" begin
    @test G.validate_native_charge([0.,-2.,0.],[0.,1.,2.],3)===nothing
    for (q,expected) in (([0.],["sample_count_lt_2"]),([0.,Inf],["nonfinite_signed_sample"]),
                         ([1.,2.],["initial_signed_sample_nonzero"]))
        t=collect(0.:length(q)-1)
        error=try G.validate_native_charge(q,t,24);nothing catch err;err end
        @test error isa G.NativeResponseError
        @test error.domain_error=="Invalid native signed charge"
        @test error.diagnostic["failed_invariants"]==expected
        @test error.diagnostic["contact_id"]==24
        @test error.diagnostic["sample_count"]==length(q)
        @test [row["signed_float64_bits"] for row in error.diagnostic["samples"]]==bitstring.(q)
        @test !isempty(C.JSON.json(error.diagnostic))
    end
end

@testset "A collected carrier at the last step is complete" begin
    p=G.SSD.CartesianPoint{Float64}(0.,0.,0.);contact=G.SSD.CartesianPoint{Float64}(0.,0.,0.0055)
    event=(drift_paths=[(e_path=[p,contact],h_path=[p,p])],)
    sim=(detector=(contacts=[(id=7,geometry=[contact])],semiconductor=[p,contact]),)
    endpoints=G.Q.endpoint_report(event,sim,(max_steps=2,))
    @test endpoints[1]["status"]=="contact" && !endpoints[1]["step_limit_reached"]
    @test endpoints[2]["status"]=="step_limit" && endpoints[2]["step_limit_reached"]
end

@testset "Domain failures retain original deposit and native detail" begin
    step=Dict("raw_row_index"=>77,"energy_keV"=>4.,"position_mm"=>[1.,2.,3.],"time_ns"=>100.)
    event=Dict("event_id"=>2,"primary_time_ns"=>100.,"steps"=>[step])
    error=try
        G.process_event(event,nothing,(dt=1.,),nothing,nothing,nothing,nothing,nothing,10,"unused.csv";
            native_only=true,deposit_processor=(args...)->G.validate_native_charge([0.,NaN],[0.,1.],8))
        nothing
    catch err;err end
    @test error isa G.NativeResponseError
    @test error.diagnostic["raw_row_index"]==77 && error.diagnostic["input_step_index"]==1
    @test error.diagnostic["input_position_mm"]==[1.,2.,3.]
    @test error.diagnostic["input_energy_keV"]==4.
    @test !isfile("unused.csv")
end

@testset "Promotion is exact; analytic admission is explicit" begin
    value=(grid=(knots=Float32[0.,0.001],endpoint=0.001f0*u"m"),values=Float32[1.,2.],flags=UInt8[1,2])
    promoted=G.promote_cached_value(value)
    @test eltype(promoted.values)==Float64 && promoted.values==value.values
    @test promoted.grid.knots==value.grid.knots && promoted.grid.endpoint==value.grid.endpoint
    @test promoted.flags===value.flags
    source=read(joinpath(dirname(pathof(G.SSD)),"ChargeDrift","ChargeDrift.jl"),String)
    old=B.patched_source(source);new=B.patched_source(source;analytic_semiconductor=true)
    @test occursin("_is_next_point_in_det(current_pos[n]+step_vectors[n], det, point_types)",old)
    @test !occursin("_is_next_point_in_det(current_pos[n]+step_vectors[n], det, point_types)",new)
    @test occursin("in det.semiconductor && !",new)
end
