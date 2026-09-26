# Interface/serialization tests only: no field solve or carrier run.
using Test, JSON
include("native_response.jl")
const A=NativeResponse; const N=A.N; const E=A.E
@testset "Native consumer identity and additive CLI" begin
    o=A.options(["--input","events.json","--inspect"])
    @test o["parcels"]==16 && o["seed"]==2609261 && o["trace-examples"]==4
    @test o["native-failure-policy"]=="abort"
    @test A.options(["--input","x","--inspect","--native-failure-policy","record"])["native-failure-policy"]=="record"
    @test_throws ArgumentError A.options(["--input","x","--inspect","--native-failure-policy","ignore"])
    @test A.options(["--input","manifest.json","--output",".local/new","--parcels","32"])["parcels"]==32
    for args in (["--input","x"],["--input","x","--inspect","--output","x"],
        ["--input","x","--inspect","--parcels","64"],["--input","x","--inspect","--seed","7"],
        ["--input","x","--inspect","--trace-examples","17"],["--input","x","--inspect","--input","y"])
        @test_throws ArgumentError A.options(args)
    end
    event=Dict("event_id"=>78,"primary_time_ns"=>12.,"steps"=>[Dict("raw_row_index"=>91,"energy_keV"=>0.),Dict("raw_row_index"=>92,"energy_keV"=>5.)])
    @test A.event_groups(event,false)==[Dict("group_id"=>0,"origin_time_ns"=>12.,"row_indices"=>[92])]
    zero=deepcopy(event); zero["steps"][2]["energy_keV"]=0
    @test isempty(A.event_groups(zero,false))
    ion=Dict("pulse_groups"=>Any[]); @test A.event_groups(ion,true)===ion["pulse_groups"]
    # Same raw/global identity regardless of arbitrary chunk or selected pulse position.
    seeds=[N.parcel_seed(2609261,78,92,p) for p in 1:32]
    @test seeds==vcat([N.parcel_seed(2609261,78,92,p) for p in 1:16],[N.parcel_seed(2609261,78,92,p) for p in 17:32])
    @test length(unique(seeds))==32
    @test N.parcel_seed(2609261,79,92,1)!=seeds[1]
    @test N.parcel_seed(2609261,78,93,1)!=seeds[1]
    @test length(N.cases())==14 && count(c->c.mode=="legacy",N.cases())==4
end
@testset "Strict native failure boundary (no solver)" begin
    success=(times=[0.,2.],signal=[0.,1.],steps=Any[])
    for policy in ("abort","record")
        attempt=A.native_attempt(()->success,policy)
        @test attempt.result===success && attempt.error===nothing
    end
    for msg in A.NATIVE_FAILURE_MESSAGES
        err=ArgumentError(msg)
        attempt=A.native_attempt(()->throw(err),"record")
        @test attempt.result===nothing
        @test attempt.error==Dict("type"=>"ArgumentError","message"=>msg,
            "exact_error"=>sprint(showerror,err),"stage"=>"NativeLiExample.native_event")
        caught=try A.native_attempt(()->throw(err),"abort") catch e; e end
        @test caught===err # strict default propagates the original exception
    end
    for err in (ArgumentError("Invalid waveform support: extra detail"),ArgumentError("Invalid native cumulative charge"),
        ErrorException("Noncontact endpoint outside crystal"),InterruptException())
        for policy in ("abort","record")
            caught=try A.native_attempt(()->throw(err),policy) catch e; e end
            @test caught===err
        end
    end
end
@testset "Failed pulse retains truth and null unknowns" begin
    o=A.options(["--input","x","--inspect","--native-failure-policy","record"])
    steps=[Dict("raw_row_index"=>912,"energy_keV"=>3.25,"time_ns"=>1e12+5,"raw"=>Dict("trackid"=>8)),
        Dict("raw_row_index"=>913,"energy_keV"=>7.5,"time_ns"=>1e12+50,"raw"=>Dict("trackid"=>9))]
    g=Dict("group_id"=>2,"origin_time_ns"=>1e12,"row_indices"=>[912,913],"horizon_ns"=>10000.)
    e=Dict("event_id"=>8432,"global_decay_id"=>8432,"primary_time_ns"=>0.,"steps"=>steps,"pulse_groups"=>[g])
    before=deepcopy(e)
    error=A.native_attempt(()->throw(ArgumentError("Noncontact endpoint outside crystal")),"record").error
    rec=A.failed_pulse(e,g,steps,o,error,"original-raw-hash")
    @test e==before
    @test rec["event_id"]==rec["global_decay_id"]==8432 && rec["group_id"]==2
    @test rec["group"]==g && rec["raw_row_indices"]==[912,913] && rec["deposition_delays_ns"]==[5.,50.]
    @test rec["deposited_energy_keV"]==10.75 && rec["seed_family"]==o["seed"] && rec["parcels"]==16
    @test rec["source_lh5_sha256"]=="original-raw-hash" && rec["native_error"]==error
    @test rec["status"]==rec["rejection_reason"]=="native_transport_failed"
    @test rec["accepted"]===false && rec["trace_saved"]===false
    for key in ("final_induced_keV","charge_end_ns","native_any_negative_charge","native_min_charge_keV",
        "native_max_charge_keV","transport_flags","endpoints","readout","current_nA","induced_charge_fC")
        @test haskey(rec,key) && rec[key]===nothing
    end
    @test occursin("does not expose rejected endpoint details",rec["endpoint_details_note"])
    j=IOBuffer(); csv=IOBuffer(); A.scalar!(j,csv,rec)
    @test JSON.parse(String(take!(j)))==rec
    text=String(take!(csv))
    @test occursin("\"10.75\",,\"false\",\"native_transport_failed\"",text)
    @test occursin("\"\"readout\"\":null",text) && E.csvcell(nothing)==""
end
@testset "Group histograms conserve failures without zero substitution" begin
    hist=Dict{String,Dict{Int,Int}}()
    r=Dict{String,Any}("final_charge_C"=>E.charge_C(3.,2.95),"preamp_peak_charge_equivalent_keV"=>2.8,
        "analog_energy_keV"=>2.7,"reconstructed_energy_keV"=>2.6)
    before=deepcopy(r)
    A.group_hist!(hist,4.,[0.,3.],r,2.95)
    @test r==before
    rejected=merge(r,Dict("reconstructed_energy_keV"=>nothing))
    A.group_hist!(hist,5.,[0.,-1.],rejected,2.95)
    A.group_hist!(hist,6.,nothing,nothing,2.95)
    @test sum(values(hist["deposited_per_group"]))==3
    for stage in ("native_terminal_charge","window_charge","preamp_charge_equivalent","analog_shaped_equivalent")
        @test sum(values(hist[stage]))==2
    end
    @test sum(values(hist["accepted_peak_ADC"]))==1
    failedonly=Dict{String,Dict{Int,Int}}(); A.group_hist!(failedonly,6.,nothing,nothing,2.95)
    @test Set(keys(failedonly))==Set(["deposited_per_group"])
    @test sum(values(failedonly["deposited_per_group"]))==1
end
@testset "Lossless scalar/endpoint payloads and bounded histograms" begin
    c=A.P.validate(JSON.parsefile(joinpath(@__DIR__,"native_readout_profile.json")))
    M=E.transition(c,2.); cal=A.P.calibration(c,2.95,2.,M)
    r=A.P.process([0.,2.,4.],[0.,-1.,500.],c,2.95,cal,M); delete!(r,"trace")
    rec=Dict("record_kind"=>"pulse","event_id"=>78,"global_decay_id"=>78,"group_id"=>2,
        "origin_time_ns"=>1e12,"readout"=>r,"transport_flags"=>Dict("step_limits"=>1))
    j=IOBuffer(); csv=IOBuffer(); A.scalar!(j,csv,rec)
    @test JSON.parse(String(take!(j)))==rec
    csvtext=String(take!(csv))
    for key in keys(r); @test occursin(replace(JSON.json(key),'"'=>"\"\""),csvtext); end
    @test occursin("input_activity_outside_peak_gate",csvtext)
    @test occursin("current_balance",csvtext) && occursin("negative_input",csvtext)
    endpoint=Dict("event_id"=>78,"global_decay_id"=>78,"group_id"=>2,"raw_row_index"=>92,
        "parcel_index"=>1,"seed_uint64"=>string(N.parcel_seed(2609261,78,92,1)),
        "endpoint"=>Dict("status"=>"stopped_without_contact","step_limit_reached"=>true,"contact_ids"=>Int[]))
    A.endpoint!(j,csv,endpoint); @test JSON.parse(String(take!(j)))==endpoint
    @test occursin("step_limit_reached",String(take!(csv)))
    hist=Dict{String,Dict{Int,Int}}()
    for x in (-1e9,-1000.,0.,661.657,4000.,1e9); A.addhist!(hist,"charge",x); end
    A.addhist!(hist,"charge",nothing)
    @test sum(values(hist["charge"]))==6 && hist["charge"][1000]==2 && hist["charge"][-1]==1
    @test_throws ArgumentError A.addhist!(hist,"charge",NaN)
end
