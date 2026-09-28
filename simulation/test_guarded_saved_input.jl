# Maintainer-only saved-positive regression. No radiation or field solving.
# The field-solver call is explicitly replaced IN THIS TEST PROCESS ONLY.
# This is not acceptance of an uninstrumented clean-machine end-to-end run.
include("native_response_guarded.jl")
using JSON, SHA, Serialization, Test
const B = NativeResponse
const Q = B.Q
const ROOT = Q.ROOT
const ACTIVE = Ref{Any}()
const CACHE_HASH = "64db8f79fa4fae393b0e1abbdfb5e2ed30d44b48cd814a40a7f1bdddb16933de"
const BASELINES = Dict("AK02"=>"dced56287f3d5c9ae3fe2e253778def9fe866bbf06c6cff7818c15b106b336d7",
    "SAP22"=>"97a8f97bdf61feae7aa1e5c9b060364d8c300714cbc7ef1319cab545b2a6d41e")
hashfile(p) = open(io->bytes2hex(sha256(io)),p)
require(ok,msg) = ok || error(msg)
function checked_json(path, expected)
    require(hashfile(path)==expected,"Pinned fixture changed: $path")
    JSON.parsefile(path)
end
function supply_saved_fields!(sim,cfg,backend; sor_consts=missing,
        potential_rechecks::Int=1,iteration_observer=nothing)
    a=ACTIVE[]; a["calls"]+=1
    require(a["calls"]==1,"Only one field-cache injection is allowed per model")
    require(sor_consts==1.0 && potential_rechecks==4,"Unexpected solve configuration")
    cached=a["sim"]
    require(typeof(sim)==typeof(cached),"Cached simulation type differs")
    require(sim.detector.semiconductor.temperature==77,"Requested temperature differs")
    require(cached.detector.semiconductor.temperature==77,"Cached temperature differs")
    require([c.potential for c in sim.detector.contacts]==[c.potential for c in cached.detector.contacts],"Cached bias differs")
    require(cfg.model==a["model"] && cfg.contact==a["contact"],"Unexpected model/contact")
    require(cfg.precision==64 && cfg.min_grid==0.05 && cfg.max_grid==2 && cfg.max_iterations==50000,"Unexpected field settings")
    require(cfg.dt==2 && cfg.threads==2 && Threads.nthreads()==2 && cfg.device=="cpu" && backend.array_type===Array,"Unexpected CPU/thread/time settings")
    require(iteration_observer===nothing,"Unexpected solver callback")
    require(sim.config_dict==cached.config_dict && sim.input_units==cached.input_units && sim.medium==cached.medium,"Cached physical configuration differs")
    solved_fields=(:q_eff_imp,:imp_scale,:q_eff_fix,Symbol("\u03f5_r"),:point_types,
                   :electric_potential,:weighting_potentials,:electric_field)
    for f in solved_fields
        require(hasfield(typeof(sim),f),"Unsupported cached-state field")
        setfield!(sim,f,deepcopy(getfield(cached,f)))
    end
    a["injected_sim"]=sim
    require(B.N.field_fingerprint(sim)==a["fingerprint"],"Injected fields differ")
    (Dict("kind"=>"test_only_verified_cache_injection","field_solves"=>0),Dict("test_only_cached_fields"=>true))
end
function files_under(dir)
    [joinpath(d,f) for (d,_,names) in walkdir(dir) for f in names]
end
function snapshot(paths)
    Dict(relpath(p,ROOT)=>Dict("sha256"=>hashfile(p),"bytes"=>filesize(p),"mtime"=>stat(p).mtime) for p in paths)
end
function run_saved_regression(output)
    out=abspath(output)
    require(B.Q.childof(out,joinpath(ROOT,".local")),"Output must be below project .local")
    require(!ispath(out),"Preserve existing acceptance outputs")
    cache_root=joinpath(ROOT,".local","cs137-1m-native")
    config_path=joinpath(cache_root,"config.json")
    config=checked_json(config_path,CACHE_HASH)
    require(Q.environment("cpu")==config["expected_environment"],"Pinned runtime/environment mismatch")
    require(Q.pathkey(realpath(Base.active_project()))==Q.pathkey(realpath(joinpath(ROOT,"simulation","Project.toml"))),"Wrong active project")
    Q.verify_model_files() # Includes are independently hash-checked before cache deserialization.
    old_root=joinpath(ROOT,".local","peak-native-delivery","cs500-v4")
    protected=files_under(old_root)
    append!(protected,[config_path,joinpath(cache_root,"COMPLETE.json")])
    for model in ("AK02","SAP22"); push!(protected,joinpath(cache_root,config["models"][model]["cache_file"])); end
    append!(protected,[joinpath(ROOT,"simulation",f) for f in B.SOURCES])
    append!(protected,[joinpath(ROOT,"simulation",f) for f in ("native_response_guarded.jl","native_boundary_guard.jl")])
    append!(protected,files_under(joinpath(ROOT,"models")))
    append!(protected,[joinpath(ROOT,"transport",f) for f in ("cs137.py","handoff.py","cryostat_export.cc","cryostat_nominal.json","cryostat-source.json","pixi.lock")])
    upstream=JSON.parsefile(joinpath(ROOT,"transport","cryostat-source.json"))
    append!(protected,[joinpath(ROOT,".local","transport","LBNL",f["name"]) for f in upstream["files"]])
    push!(protected,joinpath(dirname(pathof(NativeBoundaryGuard.SSD)),"ChargeDrift","ChargeDrift.jl"))
    push!(protected,@__FILE__)
    before=snapshot(unique(protected)); mkdir(out)
    B.E.save(joinpath(out,"preservation-before.json"),before)
    @eval Q function solve_fields!(sim,cfg,backend; sor_consts=missing,
            potential_rechecks::Int=1,iteration_observer=nothing)
        Main.supply_saved_fields!(sim,cfg,backend;sor_consts=sor_consts,
            potential_rechecks=potential_rechecks,iteration_observer=iteration_observer)
    end
    results=Dict{String,Any}()
    try
    @testset "Saved positive guarded entry (instrumented field cache)" begin
        for model in ("AK02","SAP22")
            old=joinpath(old_root,model,"response")
            baseline=checked_json(joinpath(old,"run.json"),BASELINES[model])
            for (file,h) in baseline["artifacts"]; require(hashfile(joinpath(old,file))==h,"Baseline artifact changed: $model/$file"); end
            for (file,h) in baseline["source_sha256"]; require(hashfile(joinpath(ROOT,"simulation",file))==h,"Baseline numerical source changed: $file"); end
            m=config["models"][model]; cache=joinpath(cache_root,m["cache_file"])
            require(hashfile(cache)==m["cache_sha256"],"Cached binary changed; refusing deserialization")
            cached=deserialize(cache); fp=B.N.field_fingerprint(cached)
            require(fp==m["expected_field_fingerprint"]==baseline["field_fingerprint"],"Baseline/cache fields differ")
            require(baseline["model_sha256"]==hashfile(joinpath(ROOT,"models",model*".yaml")),"Canonical model changed")
            B.geometry(JSON.parsefile(joinpath(old,"input-prepared.json")),cached,true)
            require(baseline["seed_family"]==2609261 && baseline["parcels"]==16 && baseline["drift_dt_ns"]==2 && baseline["nominal_drift_cap_ns"]==10000,"Unexpected native settings")
            require(JSON.parsefile(joinpath(old,"input-prepared.json"))["seed"]==26092631,"Unexpected radiation seed")
            require(baseline["environment"]==config["expected_environment"],"Baseline environment differs")
            ACTIVE[]=Dict("sim"=>cached,"calls"=>0,"fingerprint"=>fp,"model"=>model,"contact"=>baseline["readout_contact_id"])
            input=joinpath(old_root,model,"transport","stream","manifest.json")
            require(hashfile(input)==baseline["input_sha256"],"Saved input changed")
            dest=joinpath(out,model)
            args=["--input",input,"--output",dest,"--seed",string(baseline["seed_family"]),
                "--parcels",string(baseline["parcels"]),"--trace-examples","4","--charge-csv","examples","--native-failure-policy","record"]
            result=Base.invokelatest(GuardedNativeResponse.main,args)
            @test ACTIVE[]["calls"]==1
            @test result["counts"]==baseline["counts"]
            @test result["counts"]["groups"]==result["counts"]["accepted"]==4
            @test result["counts"]["initial_decays"]==500
            @test result["counts"]["zero_deposit_primaries"]==496
            @test result["boundary_guard"]["installed"] && !result["boundary_guard"]["package_files_modified"]
            for key in ("input_sha256","source_lh5_sha256","model_sha256","profile_sha256","config_sha256",
                        "field_fingerprint","calibration","seed_family","parcels","temperature_K","bias_V","grouping_policy")
                @test result[key]==baseline[key]
            end
            json_files=("histograms.json","profile.json","readout-config.json","input-contract.json","input-prepared.json")
            jsonl_files=("scalars.jsonl","truth.jsonl","endpoints.jsonl","traces.jsonl")
            for file in json_files
                @test JSON.parsefile(joinpath(dest,file))==JSON.parsefile(joinpath(old,file))
            end
            for file in jsonl_files
                @test [JSON.parse(s) for s in eachline(joinpath(dest,file))]==[JSON.parse(s) for s in eachline(joinpath(old,file))]
            end
            @test read(joinpath(dest,"signals.csv"))==read(joinpath(old,"signals.csv"))
            @test B.N.field_fingerprint(cached)==fp
            @test B.N.field_fingerprint(ACTIVE[]["injected_sim"])==fp
            @test result["environment"]==baseline["environment"]
            @test result["readout_environment"]==baseline["readout_environment"]
            results[model]=Dict("counts"=>result["counts"],"cache_sha256"=>m["cache_sha256"],
                "baseline_receipt_sha256"=>BASELINES[model],"field_solves"=>0,"solver_injections"=>1,
                "parsed_json_files_compared"=>collect(json_files),"parsed_jsonl_files_compared"=>collect(jsonl_files),
                "signal_csv_byte_exact"=>true,"arguments"=>args)
        end
    end
    finally
        after=snapshot(unique(protected)); B.E.save(joinpath(out,"preservation-after.json"),after)
        require(before==after,"Protected evidence changed, including during a failed test")
    end
    result=Dict("status"=>"passed_instrumented_saved_positive_regression","models"=>results,
        "protected_files"=>length(before),"new_geant4_runs"=>0,"new_field_solves"=>0,
        "scope"=>"GuardedNativeResponse.main CLI argument path with test-only verified cached solver replacement; NOT uninstrumented Run.cmd, cold installation or field-solver validation",
        "test_sha256"=>hashfile(@__FILE__))
    B.E.save(joinpath(out,"acceptance.json"),result)
    println("Saved-positive regression passed: 8 accepted groups, all 1000 initial decays retained; zero radiation/field solves.")
end
length(ARGS)==1 || error("Usage: julia --startup-file=no --threads=2 --project=simulation simulation/test_guarded_saved_input.jl .local/NEW_TEST_OUTPUT")
run_saved_regression(only(ARGS))
