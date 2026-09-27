include("native_bridge_pilot.jl")
using Test, JSON
const V=NativeBridgePilot
const N=V.N
length(ARGS)==1 || error("Pass checked test-contract directory")
docs,receipt=V.load_contracts(ARGS[1];python_verify=false)
positive(d)=first(filter(e->e["namespace"]==V.MILLION && !e["zero_ge"],d["events"]))
@testset "selected native bridge semantic contract" begin
    @test length(docs)==2
    for d in docs
        @test V.validate_contract(d)===d
        a=V.prepare(d) # membership, pinned bias/profile/injection; no field solve
        @test a.bias==(d["model_id"]=="AK02" ? 500 : 700)
        @test d["nonselected_response"]===nothing
        @test count(e->e["zero_ge"],d["events"])==1
    end
    for mutate in (
        d->(d["model_id"]="SAP22"),
        d->(d["model_sha256"]="0"^64),
        d->(positive(d)["identity"]["local_primary_id"]=10000),
        d->(positive(d)["steps"][1]["position_mm"][1]+=0.1),
        d->(positive(d)["steps"][1]["global_position_m"][1]+=0.1),
        d->(positive(d)["steps"][1]["energy_keV"]+=1),
        d->(positive(d)["pulse_groups"][1]["relative_times_ns"][1]+=1),
        d->(positive(d)["zero_ge"]=true),
        d->(positive(d)["event_id"]+=1),
        d->(positive(d)["seed_event_id"]+=1),
        d->(positive(d)["steps"][1]["raw"]["evtid"]+=1),
        d->(positive(d)["steps"][1]["raw_row_index"]+=1),
        d->(positive(d)["namespace"]="mixed"),
        d->(d["omitted_census"]["initial_primaries"]-=1))
        d=deepcopy(first(docs)); mutate(d)
        @test_throws ArgumentError V.validate_contract(d)
    end
    d=deepcopy(last(docs)); e=only(filter(e->length(e["pulse_groups"])==2,d["events"]))
    @test [g["group_id"] for g in e["pulse_groups"]]==[0,1]
    @test isempty(intersect(e["pulse_groups"][1]["row_indices"],e["pulse_groups"][2]["row_indices"]))
    pop!(e["pulse_groups"]); @test_throws ArgumentError V.validate_contract(d)
    rows=[(e["event_id"],s["raw_row_index"]) for d in docs for e in d["events"] for s in e["steps"]]
    seeds(xs)=Dict(x=>N.parcel_seed(2609261,x[1],x[2],1) for x in xs)
    @test seeds(rows)==seeds(reverse(rows))
    @test N.parcel_seed(2609261,7,55,1)!=N.parcel_seed(2609261,10007,55,1)
    @test N.parcel_seed(2609261,8432,150,1)==UInt64(13733843045326248232) # independent Python SHA256 witness
    for d in docs
        e=only(filter(e->e["namespace"]==V.OLD,d["events"]))
        @test e["event_id"]==(d["model_id"]=="AK02" ? 8432 : 8413)
        g=only(e["pulse_groups"]); byrow=Dict(s["raw_row_index"]=>s for s in e["steps"])
        steps=[byrow[i] for i in g["row_indices"]]
        for msg in V.B.NATIVE_FAILURE_MESSAGES
            attempt=V.B.native_attempt(()->throw(ArgumentError(msg)),"record")
            @test attempt.result===nothing
            r=V.B.failed_pulse(e,g,steps,Dict("parcels"=>16,"seed"=>2609261),attempt.error,e["source_lh5_sha256"])
            for key in ("final_induced_keV","charge_end_ns","native_any_negative_charge","transport_flags","endpoints","readout","current_nA","induced_charge_fC")
                @test r[key]===nothing
            end
            @test r["raw_row_indices"]==g["row_indices"]
            @test r["native_error"]["message"]==msg
        end
        @test_throws ArgumentError V.B.native_attempt(()->throw(ArgumentError("unexpected")),"record")
        @test_throws ErrorException V.B.native_attempt(()->error("unexpected"),"record")
        @test_throws ArgumentError V.B.native_attempt(()->throw(ArgumentError(first(V.B.NATIVE_FAILURE_MESSAGES))),"abort")
    end
    bad=copy(receipt["input_sha256"]); bad[first(keys(bad))]="0"^64
    @test_throws ArgumentError V.pins!(bad)
end

@testset "pilot output reservation before solver parse" begin
    out=tempname(V.BASE)
    @test !ispath(out)
    cfgs=V.reserve_pilot_output(["AK02","SAP22"],out)
    try
        @test Set(keys(cfgs))==Set(["AK02","SAP22"])
        @test isdir(joinpath(out,"AK02")) && isdir(joinpath(out,"SAP22"))
        @test_throws ArgumentError V.reserve_pilot_output(["AK02","SAP22"],out)
        @test isdir(joinpath(out,"AK02")) && isdir(joinpath(out,"SAP22"))
    finally
        rm(out;recursive=true) # Only this test-created empty directory tree.
    end
end
