# Configuration validation and injected adapter functions only; no physics.
include("scenario_response.jl")
using Test
const S=ScenarioResponse;const G=S.G

function gamma_fixture(;energy=1000,pose="nominal",ids=[2,17])
    source=Dict("id"=>"mono_gamma_662_axis_v1","pdg"=>22,"kinetic_energy_keV"=>662,
        "direction_global"=>[0,-1,0],"time_ns"=>0,"clock_policy"=>"synthetic_primary_time_zero")
    canonical=Dict("id"=>"mono_gamma_662_axis_v1","version"=>1,"ref"=>"scenarios/assets/mono_gamma_662_axis_v1.json",
        "sha256"=>"b9c3990f835fe094d6482e2fe8b6cfb13e2419e3abe5b7f6902cd28f340fc6e9")
    position=pose=="nominal" ? [0,37.073,.290] : [0,42.073,.290]
    marker=Dict("kind"=>"portable_gamma_source_configuration_v1","schema_version"=>1,"canonical_preset"=>canonical,
        "energy_keV"=>energy,"source_pose"=>pose,"position_global_mm"=>position,"direction_global"=>[0,-1,0],"time_ns"=>0,
        "units"=>Dict("energy"=>"keV","length"=>"mm","time"=>"ns","direction"=>"dimensionless"))
    policy=G.B.storage_descriptor(Dict("initial_primaries"=>20,"zero_deposit_primaries"=>20-length(ids)))
    assets=Dict("source"=>source,"detector"=>Dict("model_sha256"=>G.DETECTOR_PINS["SAP22"].model))
    transform=Dict("rotation_local_to_global"=>[[1,0,0],[0,0,1],[0,-1,0]],"translation_global_mm"=>[0,1.45,.29])
    manifest=Dict("kind"=>"scenario_gamma_event_stream_v1","status"=>"complete","model_id"=>"SAP22","primary_count"=>20,
        "assets"=>assets,"coordinate_transform"=>transform,"source_position_global_mm"=>position,
        "clock_policy"=>"synthetic_primary_time_zero","stored_temperature_K"=>78,"gamma_source_configuration"=>marker,"event_storage"=>policy,
        "initial_summary"=>Dict("initial_primaries"=>20,"initial_gamma_primaries"=>20,"zero_deposit_primaries"=>20-length(ids),"nonzero_primaries"=>length(ids)))
    prepared=Dict("assets"=>assets,"coordinate_transform"=>transform,"source_position_global_mm"=>position,
        "instance"=>Dict("source"=>canonical,"source_pose"=>pose),"gamma_source_configuration"=>marker)
    events=[Dict("event_id"=>id,"initial_primary_id"=>id,"zero_ge"=>false,"truth_ge_edep_keV"=>10.,
        "vtx"=>[Dict("time"=>0.,"xloc"=>0.,"yloc"=>position[2]/1000,"zloc"=>position[3]/1000)],
        "particles"=>[Dict("particle"=>22,"ekin"=>energy/1000,"px"=>0.,"py"=>-energy/1000,"pz"=>0.)],
        "steps"=>[Dict("raw_row_index"=>id,"energy_keV"=>10.,"time_ns"=>.125)],"material_rows"=>Dict("stp/germanium"=>[Dict()])) for id in ids]
    profile=G.P.load(joinpath(@__DIR__,"native_readout_profile.json")).profile
    Dict("kind"=>"local_scenario_gamma_request_v1","model_id"=>"SAP22","source_manifest"=>manifest,"prepared"=>prepared,
        "gamma_source_configuration"=>marker,"event_storage"=>policy,"threads"=>Threads.nthreads(),"events"=>events,
        "readout_config"=>G.P.for_census(profile,20),"profile"=>profile,"pins"=>Dict())
end

@testset "effective gamma source and sparse original IDs" begin
    d=gamma_fixture();@test S.validate(d)===d
    @test G.effective_gamma_source(d["source_manifest"],d["prepared"])==1000
    @test [event["event_id"] for event in d["events"]]==[2,17]
    @test d["event_storage"]["efficiency_denominator"]==20
    @test d["source_manifest"]["assets"]["source"]["kinetic_energy_keV"]==662
    empty=gamma_fixture(ids=Int[]);@test S.validate(empty)===empty
    for mutate in (
        d->(d["source_manifest"]["gamma_source_configuration"]["energy_keV"]=true),
        d->(d["source_manifest"]["gamma_source_configuration"]["source_pose"]="free"),
        d->(d["events"][1]["particles"][1]["ekin"]=.662),
        d->(d["events"][1]["event_id"]=true),
        d->reverse!(d["events"]),
        d->(d["event_storage"]["efficiency_denominator"]=2),
        d->(d["events"][1]["zero_ge"]=true),
    )
        bad=gamma_fixture();mutate(bad);@test_throws ArgumentError S.validate(bad)
    end
end

@testset "new sparse adapter keeps signed rejection and null failure" begin
    event=Dict("event_id"=>17,"initial_primary_id"=>17,"truth_ge_edep_keV"=>10.,"zero_ge"=>false,
        "steps"=>[Dict("raw_row_index"=>9,"energy_keV"=>10.,"time_ns"=>.125)])
    native=()->(times=[0.,2.,4.],signal=[0.,-.25,-.5],steps=Any[])
    process=(t,q)->Dict("accepted"=>false,"current_balance"=>Dict("passed"=>true),"observed_signed_signal"=>q)
    result=G.event_response(event,"record",native,process,x->Dict();allow_zero=false)
    @test result["native"]["signal"]==[0.,-.25,-.5]
    @test result["readout"]["accepted"]===false
    @test result["parcel_seeds"][1]["parcels"][1]["seed_uint64_decimal"]==string(G.N.parcel_seed(2609261,17,9,1))
    failed=G.event_response(event,"record",()->throw(ArgumentError(first(G.B.NATIVE_FAILURE_MESSAGES))),
        (t,q)->error("failure must not read out"),x->error("unknown flags");allow_zero=false)
    @test failed["status"]=="native_failed"
    @test all(failed[key]===nothing for key in ("native","transport_flags","charge_input","final_induced_keV","charge_end_ns","readout"))
    zero=deepcopy(event);zero["zero_ge"]=true;zero["truth_ge_edep_keV"]=0.
    @test_throws ArgumentError G.event_response(zero,"record",native,process,x->Dict();allow_zero=false)
end
println("MOCK_SCOPE native/calibration/readout/field/transport calculations=0; original gamma files unchanged")
