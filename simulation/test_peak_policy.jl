using Test
include("readout.jl")
const E=Readout
const C=E.config(joinpath(@__DIR__,"readout_demo.json"))
const S=merge(C,Dict("peak_policy"=>E.SIGNED_PEAK_POLICY))
function wave(q,c=S)
    E.process_event(collect(0.:2.:(length(q)-1)*2),q,c,2.95,E.calibration(c,2.95,2.),E.transition(c,2.))
end
@testset "Explicit signed positive peak; unchanged analog signal" begin
    for q in ([0.,-1e-100,500.],[0.,-1.,500.])
        legacy=wave(q,C); signed=wave(q)
        @test legacy["rejection_reason"]=="negative_input"
        @test signed["accepted"] && signed["negative_input"]
        for key in ("trace","peak_V","analog_energy_keV","current_balance","final_charge_C","adc_code")
            @test signed[key]==legacy[key]
        end
        @test signed["current_balance"]["passed"]
        @test minimum(signed["trace"]["induced_charge_fC"])<0
    end
    for q in ([0.,-500.],[0.,0.])
        r=wave(q)
        @test !r["accepted"] && r["below_threshold"] && r["nonpositive_peak"]
        @test r["reconstructed_energy_keV"]===nothing
    end
    r=wave([0.,-1e-100,1e6])
    @test r["negative_input"] && r["saturated"] && !r["below_threshold"]
    @test r["rejection_reason"]=="saturated" && r["reconstructed_energy_keV"]===nothing
    cal=E.calibration(S,2.95,2.)
    for (peak,accepted) in ((prevfloat(S["threshold_V"]),false),(S["threshold_V"],true),(nextfloat(S["threshold_V"]),true))
        r=E.digitize(peak,S,cal;negative=true)
        @test r["accepted"]==accepted && r["below_threshold"]==!accepted && r["negative_input"]
    end
end
@testset "Finite gate, delayed input, independent flags" begin
    gate=merge(S,Dict("peak_gate_start_ns"=>0.,"peak_gate_end_ns"=>2000.))
    @test wave([0.,500.],gate)["accepted"]
    reference=wave([0.,500.],gate)
    for start_ns in (1.,2.)
        r=wave([0.,500.],merge(gate,Dict("peak_gate_start_ns"=>start_ns)))
        @test r["input_activity_outside_peak_gate"]
        for key in ("trace","current_balance","final_charge_C","peak_V")
            @test r[key]==reference[key]
        end
    end
    delayed=vcat(zeros(1500),fill(500.,2))
    r=wave(delayed,gate)
    @test r["below_threshold"] && !r["accepted"] && r["input_activity_outside_peak_gate"]
    @test r["final_charge_C"]==wave(delayed)["final_charge_C"]
    short=merge(gate,Dict("peak_gate_end_ns"=>500.))
    r=wave([0.,500.],short)
    @test r["gate_limited"] && !r["window_limited"] && !r["below_threshold"]
    @test r["rejection_reason"]=="peak_at_gate_boundary"
    r=wave([0.,-1e-100,1e6],short)
    @test r["negative_input"] && r["saturated"] && r["gate_limited"]
    start=merge(gate,Dict("peak_gate_start_ns"=>1500.))
    @test wave([0.,500.],start)["gate_limited"]
    @test_throws ArgumentError wave([0.,500.],merge(S,Dict("peak_policy"=>"rectify")))
    @test_throws ArgumentError wave([0.,500.],merge(S,Dict("peak_gate_start_ns"=>1.)))
    @test_throws ArgumentError wave([0.,500.],merge(gate,Dict("peak_gate_end_ns"=>0.)))
end
println("PEAK_POLICY_TEST_RECEIPT ", E.JSON.json(Dict("status"=>"passed","environment"=>E.environment(),
    "sources"=>Dict(f=>E.hashfile(joinpath(@__DIR__,f)) for f in ("readout.jl","test_peak_policy.jl","readout_demo.json")))))
