include("native_contact_start_resilience.jl")
using Test, JSON
const X=NativeContactStartResilience
const C=NativeCheckpointBatch
const R=C.R
const ROOT=C.ROOT
function event(id)
    file=joinpath(ROOT,".local","cs137-1m-native","inputs","SAP22.jsonl")
    found=nothing
    open(file) do io
        for line in eachline(io)
            e=JSON.parse(line)
            if e["event_id"]==id; found=e; break; end
        end
    end
    found===nothing && error("event not found")
    found
end
bad=event(128042)
good=event(128040)
sim,_=R.setup_simulation("SAP22";temperature=77.0)
g=only(bad["pulse_groups"])
@testset "Contact-start fail-closed adapter" begin
    @test X.validate_event_allow_contact(bad,sim)==count(s->s["energy_keV"]>0,bad["steps"])
    rows=X.contact_rows(bad,g,sim)
    @test length(rows)==7
    @test all(r->r["contact_ids"]==[1],rows)
    @test isapprox(sum(r["energy_keV"] for r in rows),6.130805839620634;atol=1e-12)
    f=X.contact_failure("SAP22",bad,g,sim,"c","i")
    @test f["status"]=="native_failed" && f["accepted"]===false
    @test f["native"]===nothing && f["readout"]===nothing
    @test f["failure_class"]=="input_domain_compatibility"
    @test f["error"]["group_response_unknown"]===true
    @test f["event"]["ge_energy_keV"]==bad["ge_energy_keV"]
    @test f["group"]==g
    @test X.contact_failure("SAP22",good,only(good["pulse_groups"]),sim,"c","i")===nothing
    # A clean subset of the mixed group is not failed merely because another row in the event touches contact.
    clean=deepcopy(g); clean["row_indices"]=[2253]
    @test X.contact_failure("SAP22",bad,clean,sim,"c","i")===nothing
    # Outside-semiconductor is still fatal, even under compatibility validation.
    outside=deepcopy(bad)
    p=first(filter(s->s["energy_keV"]>0,outside["steps"]))
    p["position_mm"]=[100.0,0.0,0.0]
    @test_throws ArgumentError X.validate_event_allow_contact(outside,sim)
    # Contact failure returns before any cfg/readout object can be touched.
    early=X.response_or_contact_failure("SAP22",bad,g,sim,nothing,nothing,nothing,nothing,nothing,"c","i")
    @test early["status"]=="native_failed"
end
@testset "Source-pinned installation" begin
    runner=joinpath(@__DIR__,"native_checkpoint_batch.jl")
    before=C.hashfile(runner)
    patched=X.patched_main(read(runner,String))
    @test occursin("validate_event_allow_contact",patched)
    @test occursin("response_or_contact_failure",patched)
    @test X.install!()["kind"]=="saved_contact_start_fail_closed_v1"
    @test C.hashfile(runner)==before==X.ORIGINAL_RUNNER_SHA
    @test X.install!()["coordinates_modified"]===false
end
println("Actual failing event: ",bad["event_id"]," / group ",g["group_id"],
    "; full group Edep=",bad["ge_energy_keV"]," keV")
