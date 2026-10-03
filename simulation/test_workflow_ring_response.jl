# Pure source-contract/syntax check. No scientific modules, solver, propagator
# or calibration is loaded or called. Actual ring execution follows source freeze.
using Test
root=dirname(@__DIR__)
text=read(joinpath(@__DIR__,"workflow_ring_response.jl"),String)
tree=Meta.parseall(text)
function syntax_ok(value)
    value isa Expr || return true
    !(value.head in (:error,:incomplete)) && all(syntax_ok,value.args)
end
@testset "Fresh ring source contract without science" begin
    @test syntax_ok(tree)
    @test occursin("NR.native_attempt",text)
    @test occursin("N.native_event(event,sim,cfg",text)
    @test occursin("RP.negative_calibration(profile.config,eion,N.DT,matrix)",text)
    @test occursin("RP.process(t,q,c,eion,cal,M;horizon_ns=horizon_ns)",text)
    @test occursin("profile.profile[\"settings\"]==selected[\"electronics\"]",text)
    @test occursin("contacts==c[\"contact_potentials_V\"]==op[\"contact_potentials_V\"]",text)
    @test occursin("trace[\"raw_native_current_nA\"]=RP.FACTOR .* trace[\"current_nA\"]",text)
    @test occursin("trace[\"raw_native_induced_charge_fC\"]=RP.FACTOR .* trace[\"induced_charge_fC\"]",text)
    @test !occursin("abs.",text)
    @test !occursin("RP.derive",text)
    @test !occursin("RP.load_saved",text)
    @test occursin("current_balance\"][\"passed\"]",text)
    @test occursin("counts[\"rejected\"]==counts[\"native_failed_groups\"]+counts[\"readout_rejected\"]",text)
end
println("Ring source parsed; protected native/solver/readout calls retained; science calls 0")
