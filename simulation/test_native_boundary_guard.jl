include("native_response.jl")
include("native_boundary_guard.jl")
using Test, JSON, SHA, Serialization
const B=NativeResponse; const N=B.N; const Q=B.Q; const G=NativeBoundaryGuard
const ROOT=Q.ROOT; const BASE=joinpath(ROOT,".local","native-response-fix")
function ev(d,id,ns)
    e=only(filter(e->e["event_id"]==id && e["namespace"]==ns,d["events"]))
    g=only(e["pulse_groups"]); rows=Dict(s["raw_row_index"]=>s for s in e["steps"])
    Dict("event_id"=>e["seed_event_id"],"primary_time_ns"=>g["origin_time_ns"],"steps"=>[rows[i] for i in g["row_indices"]])
end
function main()
    d=JSON.parsefile(joinpath(BASE,"..","native-bridge-pilot","contracts-v3","SAP22.json"))
    sim=deserialize(joinpath(BASE,"boundary-proof","SAP22-state.jls"))
    cfg=Q.parse_args(["--model","SAP22","--position-mm","3,0,5","--precision","64","--dt-ns","2","--min-grid-mm","0.05","--max-iterations","50000","--output",joinpath(BASE,"unused-guard-test")])
    bad=ev(d,8413,"cs10000-v2-diagnostic"); good=ev(d,3815,"cs137-1m")
    results=Any[];before=N.field_fingerprint(sim)
    @testset "Pinned boundary guard" begin
        p=joinpath(dirname(pathof(N.SSD)),"ChargeDrift","ChargeDrift.jl");h=bytes2hex(sha256(read(p)))
        @test h==G.EXPECTED
        patched=G.patched_source(read(p,String))
        @test count("throw(Main.NativeBoundaryGuard.BoundaryStall",patched)==1
        @test_throws ArgumentError G.patched_source("unrelated source")
        G.install!();@test G.provenance()["installed"]
        good0=G.attempt(()->N.native_event(good,sim,cfg,16,2609261))
        @test good0.error===nothing
        for k in 1:3
            junk=[fill(Float64(k),15003) for _ in 1:8]
            a=G.attempt(()->N.native_event(bad,sim,cfg,16,2609261));push!(results,a.error)
            @test a.result===nothing
            @test a.error["type"]=="NativeBoundaryStall"
            @test a.error["step"]==23
            @test a.error["charge_unknown"]===true
            empty!(junk);GC.gc(false)
        end
        @test results[1]==results[2]==results[3]
        good1=G.attempt(()->N.native_event(good,sim,cfg,16,2609261))
        @test good1.error===nothing
        @test good0.result.times==good1.result.times
        @test good0.result.signal==good1.result.signal
        @test good0.result.steps==good1.result.steps
        @test_throws ErrorException G.attempt(()->error("Unexpected errors must abort"))
        @test N.field_fingerprint(sim)==before
        @test bytes2hex(sha256(read(p)))==h
        file=joinpath(BASE,"guard-tests.json");@test !ispath(file)
        open(file,"w") do io
            JSON.print(io,Dict("status"=>"passed","failures"=>results,"success_control_id"=>3815,"success_signal_sha256"=>bytes2hex(sha256(reinterpret(UInt8,good0.result.signal)))),2)
        end
    end
end
main()
