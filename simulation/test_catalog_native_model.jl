# Software-only exact descriptor/readout/placement refusal tests. No field, drift or calibration.
using Test, JSON, SolidStateDetectors
include("catalog_native_model.jl")
const C=CatalogNativeModel
function fixture(entry)
    cat=JSON.parsefile(joinpath(C.ROOT,"models/catalog.json"));path=joinpath(C.ROOT,"models",entry["model"]);doc=SolidStateDetectors.YAML.load_file(path);sc=doc["detectors"][1]["semiconductor"]
    contacts=Dict(string(x["id"])=>x["potential"] for x in doc["detectors"][1]["contacts"])
    nominal=JSON.parsefile(joinpath(C.ROOT,"transport/cryostat_nominal.json"));b=entry["bounds_mm"];t=nominal["crystal_in_vacuum_translation_mm"]
    occupied=[b[1]+t[1],b[2]+t[1],b[5]+t[2],b[6]+t[2],-b[4]+t[3],-b[3]+t[3]];envelope=[-20.574,20.574,-21.463,21.463,-29.21,29.21]
    fits=all(occupied[i]>=envelope[i]-1e-9 && occupied[i+1]<=envelope[i+1]+1e-9 for i in (1,3,5))
    cavity=Dict("kind"=>"unchanged_lbnl_cavity_screen_v1","scope"=>"necessary envelope screen; native full overlap/probes remain required","large_box_bounds_vacuum_mm"=>envelope,"maximum_front_z_mm"=>35.56,"crystal_in_vacuum_translation_mm"=>t,"coordinate_transform"=>nominal["coordinate_transform"],"upstream_sha256"=>Dict(name=>C.hashfile(joinpath(C.ROOT,".local/transport/LBNL",name)) for name in ("chamber.tg","shield.tg","stage.tg")),"nominal_sha256"=>C.hashfile(joinpath(C.ROOT,"transport/cryostat_nominal.json")))
    Dict("kind"=>"catalog_detector_contract_v1","schema_version"=>1,"model_id"=>entry["id"],"model_ref"=>"models/"*entry["model"],"model_sha256"=>entry["model_sha256"],"dependencies_sha256"=>Dict("models/"*name=>only(filter(x->x["path"]==name,cat["dependencies"]))["sha256"] for name in entry["dependencies"]),"catalog_sha256"=>C.hashfile(joinpath(C.ROOT,"models/catalog.json")),"coordinate_system"=>entry["coordinate_system"],"geometry"=>sc["geometry"],"bounds_mm"=>b,"contact_potentials_V"=>contacts,"readout_contact_id"=>entry["readout_contact_id"],"wiring_factor"=>C.wiring(contacts,entry["readout_contact_id"]),"bias_span_V"=>maximum(values(contacts))-minimum(values(contacts)),"stored_temperature_K"=>sc["temperature"],"runtime_temperature_K"=>sc["temperature"],"temperature_policy"=>"original YAML temperature retained","qualification"=>entry["status"],"assumptions"=>entry["assumptions"],"cavity"=>cavity,"placement"=>Dict("occupied_bounds_vacuum_mm"=>occupied,"fits_large_box_envelope"=>fits,"blocking_reasons"=>fits ? Any[] : Any["fixed dimensions"],"status"=>fits ? "native_overlap_check_required" : "blocked_by_fixed_dimensions"),"scope"=>"unchanged nominal LBNL engineering placement; no experimental detector identity, CCE or resolution claim")
end
catalog=JSON.parsefile(joinpath(C.ROOT,"models/catalog.json"));contracts=Dict(e["id"]=>fixture(e) for e in catalog["detectors"])
@testset "One native model loader retains all seventeen canonical inputs" begin
    for (id,c) in contracts
        @test C.validate_model(c).entry["id"]==id
        a=C.simulation(c;require_placement=false)
        @test a.sim.detector.semiconductor.temperature==c["stored_temperature_K"]
        @test Dict(string(x.id)=>x.potential for x in a.sim.detector.contacts)==c["contact_potentials_V"]
        @test a.sim.electric_potential===missing && a.sim.electric_field===missing
        @test C.integer(c["readout_contact_id"]) && any(x->x.id==c["readout_contact_id"],a.sim.detector.contacts)
    end
    @test contracts["GeGI_3D"]["stored_temperature_K"]==92.3 && contracts["GeGI_3D"]["readout_contact_id"]==9 && length(contracts["GeGI_3D"]["contact_potentials_V"])==34
    @test C.wiring(Dict("1"=>0,"2"=>-370),1)==-1
    @test_throws ArgumentError C.wiring(Dict("1"=>0,"2"=>-370,"3"=>100),1)
end
@testset "Rehashed descriptor/settings/fit edits do not change canonical admission" begin
    for key in ("stored_temperature_K","runtime_temperature_K","readout_contact_id","wiring_factor","bias_span_V")
        wrong=deepcopy(contracts["AK01"]);wrong[key]+=1
        @test_throws ArgumentError C.validate_model(wrong)
    end
    wrong=deepcopy(contracts["AK01"]);wrong["geometry"]["polycone"]["r"][2]+=.01
    @test_throws ArgumentError C.validate_model(wrong)
    wrong=deepcopy(contracts["KL01_3D"]);wrong["dependencies_sha256"][first(keys(wrong["dependencies_sha256"]))]="0"^64
    @test_throws ArgumentError C.validate_model(wrong)
    for id in ("BEGe_GD32B_reference","BEGe_reference","COAX_ANG2_reference","GeGI_3D","ICPC_48A_reference","ICPC_large_reference","PPC_PONaMa1_reference")
        @test_throws ArgumentError C.validate_model(contracts[id];require_placement=true)
        wrong=deepcopy(contracts[id]);wrong["placement"]["fits_large_box_envelope"]=true;empty!(wrong["placement"]["blocking_reasons"])
        @test_throws ArgumentError C.validate_model(wrong;require_placement=true)
        wrong["cavity"]["large_box_bounds_vacuum_mm"].*=10
        @test_throws ArgumentError C.validate_model(wrong;require_placement=true)
    end
end
@testset "Compatible 3D/cylindrical models share membership and initial-grid API" begin
    rows=Any[]
    for id in ("AK01","SAP16","SAP17","Bipolar_reference_3D","KL01_3D")
        c=contracts[id];a=C.simulation(c);point=[3.,0.,5.]
        meta=Dict("probes"=>[Dict("name"=>"fixed_bulk","position_mm"=>point,"expected"=>"inside"),Dict("name"=>"outside","position_mm"=>[100.,100.,100.],"expected"=>"outside")])
        @test C.validate_probes(meta,a.sim)["ssd_probe_membership_passed"]
        @test !any(x->SolidStateDetectors.CartesianPoint{Float64}((point./1000)...) in x.geometry,a.sim.detector.contacts)
        bad=deepcopy(meta);bad["probes"][1]["expected"]="outside"
        @test_throws ArgumentError C.validate_probes(bad,a.sim)
        out=joinpath(C.ROOT,".local/student-batches-v1/model-coverage","unused-grid-test-"*id)
        cfg=C.config(c,out);r=C.resource_plan(a.sim,cfg)
        @test cfg.min_grid==0.25 && cfg.max_grid==2 && cfg.precision==64
        @test C.numerics(c)["min_spacing_mm"]==0.25 && C.numerics(c)["max_spacing_mm"]==2
        @test r["refinement_spacing_envelopes"]["0.25"]["largest_grid_node_envelope"]<=r["refinement_spacing_envelopes"]["0.05"]["largest_grid_node_envelope"]
        @test r["initial_grid_guard_passed"] && r["largest_initial_grid_nodes"]>0
        @test_throws ArgumentError C.resource_plan(a.sim,cfg;free_bytes=0)
        @test a.sim.electric_potential===missing && a.sim.electric_field===missing
        push!(rows,merge(Dict("model_id"=>id),r))
    end
    if "--record-grid" in ARGS
        file=joinpath(C.ROOT,".local/student-batches-v1/model-coverage/ENGINEERING-GRID-ASSESSMENT.json");write(file,JSON.json(rows,2)*"\n")
    end
end
@testset "New source syntax remains parseable without executing science" begin
    function syntax_ok(x);!(x isa Expr) || (!(x.head in (:error,:incomplete)) && all(syntax_ok,x.args));end
    for name in ("catalog_native_model.jl","catalog_decay_stream.jl","catalog_native_response.jl")
        @test syntax_ok(Meta.parseall(read(joinpath(@__DIR__,name),String)))
    end
end
println("Catalog native tests complete: field solves 0; drift calls 0; calibration calls 0")
