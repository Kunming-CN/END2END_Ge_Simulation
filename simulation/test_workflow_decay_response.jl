# Model/geometry/wiring admission only. No field solve, propagation or calibration.
using Test, JSON, SolidStateDetectors
include("workflow_decay_response.jl")
const W=WorkflowDecayResponse;const D=W.DS
function public_contract(id,ref)
    cat=JSON.parsefile(joinpath(D.ROOT,"models/catalog.json"));entry=only(filter(x->x["id"]==id,cat["detectors"]))
    deps=Dict("models/"*r=>only(filter(x->x["path"]==r,cat["dependencies"]))["sha256"] for r in entry["dependencies"])
    delta=id=="GeRC02" ? Dict("path"=>"detectors[0].semiconductor.impurity_density.lithium_annealing_time","from"=>"30minute","to"=>"50minute") : nothing
    Dict("kind"=>id in keys(D.CANONICAL_PINS) ? "canonical_effective_model_v1" : id in keys(D.RS.MODEL_PINS) ? "ring_effective_model_v1" : "sap18_effective_model_v1",
        "model_id"=>id,"variant_id"=>id=="GeRC02" ? "GeRC02_Li50min" : id,"source_model_ref"=>"models/"*id*".yaml",
        "source_model_sha256"=>entry["model_sha256"],"effective_model_ref"=>ref,"effective_model_sha256"=>D.hashfile(D.relative_file(ref)),
        "dependencies_sha256"=>deps,"model_delta"=>delta,"geometry_unchanged"=>true,"stored_temperature_K"=>78,"runtime_temperature_K"=>77,
        "annealing_temperature_K"=>id=="GeRC02" ? 553.15 : nothing,"annealing_time_minutes"=>id=="GeRC02" ? 50 : nothing,
        "readout_contact_id"=>1,"readout_contact_width_mm"=>id=="SAP18_ring08_scenario" ? .8 : nothing,
        "contact_potentials_V"=>Dict("1"=>0,"2"=>D.SIGNED_BIAS[id]))
end
function contour_text(path)
    body=read(path,String)
    match_axes=match(r"    geometry:\r?\n      polycone:\r?\n        r:\r?\n((?:        - [^\r\n]+\r?\n)+)        z:\r?\n((?:        - [^\r\n]+\r?\n)+)",body)
    match_axes===nothing && error("Frozen contour text changed")
    axes=[[parse(Float64,strip(line)[3:end]) for line in split(strip(match_axes[i]),'\n')] for i in (1,2)]
    [collect(x) for x in zip(axes...)]
end
@testset "Five independent detector admissions reuse their own original model" begin
    mktempdir(joinpath(D.ROOT,".local")) do dir
        for id in sort(collect(keys(D.SIGNED_BIAS)))
            original=joinpath(D.ROOT,"models",id*".yaml");ref="models/"*id*".yaml"
            if id=="GeRC02"
                body=replace(read(original,String),"lithium_annealing_time: 30minute"=>"lithium_annealing_time: 50minute";count=1)
                target=joinpath(dir,"GeRC02.yaml");write(target,body);ref=replace(relpath(target,D.ROOT),'\\'=>'/')
            end
            c=public_contract(id,ref);pins=Dict{String,String}();path=D.model_contract(c,pins)
            @test path==D.relative_file(ref)
            sim=Simulation{Float64}(path)
            @test sim.detector.semiconductor.temperature==78
            @test Dict(string(x.id)=>x.potential for x in sim.detector.contacts)==c["contact_potentials_V"]
            @test sim.electric_field===missing && sim.electric_potential===missing
            config=deepcopy(sim.config_dict);semi=config["detectors"][1]["semiconductor"];semi["temperature"]=77.0
            haskey(semi["charge_drift_model"],"temperature") && (semi["charge_drift_model"]["temperature"]=77.0)
            runtime=Simulation{Float64}(config);drift=runtime.detector.semiconductor.charge_drift_model
            @test runtime.detector.semiconductor.temperature==77 && (!hasproperty(drift,:temperature) || drift.temperature==77)
            @test Dict(string(x.id)=>x.potential for x in runtime.detector.contacts)==c["contact_potentials_V"]
            meta=Dict("contour_rz_mm"=>contour_text(original),"coordinate_transform"=>JSON.parsefile(joinpath(D.ROOT,D.ANCHORS_REF))["coordinate_transform"])
            @test W.NR.geometry(meta,sim,true)["ssd_contour_matches"]
            wrong=deepcopy(meta);wrong["contour_rz_mm"][1][1]+=.01
            @test_throws ArgumentError W.NR.geometry(wrong,sim,true)
            wrong=deepcopy(c);wrong["contact_potentials_V"]["2"]*=-1
            @test_throws ArgumentError D.model_contract(wrong)
            wrong=deepcopy(c);wrong["effective_model_sha256"]="0"^64
            @test_throws ArgumentError D.model_contract(wrong)
            @test D.WIRING[id]==(id in ("KMRC01_candidate","SAP18_ring08_scenario") ? -1 : 1)
            @test D.recheck((pins=pins,))===nothing
        end
    end
end
@testset "Shared stream/response syntax and preserved software defaults" begin
    function syntax_ok(x)
        !(x isa Expr) || (!(x.head in (:error,:incomplete)) && all(syntax_ok,x.args))
    end
    for name in ("decay_stream.jl","workflow_decay_response.jl","workflow_ring_response.jl")
        @test syntax_ok(Meta.parseall(read(joinpath(@__DIR__,name),String)))
    end
    @test D.WIRING["SAP22"]==1 && D.SIGNED_BIAS["SAP22"]==700
    @test D.WIRING["AK02"]==1 && D.SIGNED_BIAS["AK02"]==500
end
println("Five detector model/geometry/wiring checks passed; field solves 0, drift calls 0, calibration calls 0")
