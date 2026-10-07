# Explicit synthetic software checks only; no radiation, field solve or native drift.
include("workflow_sap18_response.jl")
using .WorkflowSap18Response, Test, JSON, SolidStateDetectors
const W=WorkflowSap18Response;const SP=Sap18Polarity
@testset "SAP18 immutable identity and synthetic fixed wiring" begin
 c=Dict("kind"=>"sap18_effective_model_v1","model_id"=>"SAP18_ring08_scenario","variant_id"=>"SAP18_ring08_scenario",
 "source_model_ref"=>"models/SAP18_ring08_scenario.yaml","source_model_sha256"=>Sap18Stream.MODEL_PINS["SAP18_ring08_scenario"],
 "effective_model_ref"=>"models/SAP18_ring08_scenario.yaml","effective_model_sha256"=>Sap18Stream.MODEL_PINS["SAP18_ring08_scenario"],
 "dependencies_sha256"=>Dict("models/ADLChargeDriftModel/drift_velocity_config.yaml"=>"642a2bd0df1dabd9da7c71d15950e8b84f491babfd4b4fb63abdb82162f97ce6"),
 "model_delta"=>nothing,"annealing_temperature_K"=>nothing,"annealing_time_minutes"=>nothing,
 "stored_temperature_K"=>78,"runtime_temperature_K"=>77,"readout_contact_id"=>1,"readout_contact_width_mm"=>.8,
 "geometry_unchanged"=>true,"contact_potentials_V"=>Dict("1"=>0,"2"=>-380))
 @test endswith(Sap18Stream.model_contract(c),"SAP18_ring08_scenario.yaml")
 for (key,value) in (("readout_contact_width_mm",2),("contact_potentials_V",Dict("1"=>0,"2"=>-370)),("runtime_temperature_K",78))
  bad=deepcopy(c);bad[key]=value;@test_throws ArgumentError Sap18Stream.model_contract(bad)
 end
 original=SolidStateDetectors.Simulation{Float64}(Sap18Stream.model_contract(c))
 @test original.detector.semiconductor.temperature==78
 @test Dict(x.id=>x.potential for x in original.detector.contacts)==Dict(1=>0,2=>-380)
 profile=W.P.load(joinpath(@__DIR__,"native_readout_profile.json"));cfg=profile.config
 # Synthetic injection validation is separate from the single actual-run calibration.
 injection=SP.negative_calibration(cfg,3.0,2.0)
 @test injection.calibration["raw_charge_C"]<0
 @test injection.calibration["charge_C"]==-injection.calibration["raw_charge_C"]
 @test injection.injection["wiring"]["model_id"]=="SAP18_ring08_scenario"
 @test injection.calibration["peak_V"]>0
 t=[0.,2.,4.];q=[0.,-250.,-500.]
 r=SP.process(t,q,cfg,3.0,injection.calibration,W.E.transition(cfg,2.0);horizon_ns=100000)
 @test r["wiring"]["factor"]==-1
 @test r["raw_native_final_charge_keV"]==-500
 @test r["current_balance"]["passed"]
 @test r["trace"]["raw_native_induced_charge_fC"]==-r["trace"]["induced_charge_fC"]
end
println(JSON.json(Dict("kind"=>"sap18_synthetic_software_tests","radiation_calls"=>0,"field_calls"=>0,"native_drift_calls"=>0)))
