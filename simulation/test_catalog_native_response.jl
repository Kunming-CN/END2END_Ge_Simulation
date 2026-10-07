# Request-boundary software checks with a completed geometry-only receipt.
# No raw source, calibration, potential solve or drift is invoked.
using Test, JSON
include("catalog_native_response.jl")
const CR=CatalogResponse
const CM=CatalogNativeModel
length(ARGS)==1 || error("Supply one completed geometry-only prepared.json")
prepared=JSON.parsefile(ARGS[1]);contract=prepared["model_contract"]
@test CM.validate_probes(prepared,CM.simulation(contract).sim)["ssd_probe_membership_passed"]
name="catalog-native-schema-"*string(getpid());base=joinpath(CM.ROOT,".local/runs",name)
ispath(base) && error("Schema-test evidence already exists; retain it")
mkpath(joinpath(base,"electronics"));mkpath(joinpath(base,"transport/stream"))
profile=joinpath(base,"electronics/profile.json");cp(joinpath(@__DIR__,"native_readout_profile.json"),profile)
stream=joinpath(base,"transport/stream/manifest.json")
write(stream,JSON.json(Dict("synthetic_request_reader_fixture"=>true,"science_calls"=>0))*"\n")
selection=Dict("name"=>name,"cryostat"=>"lbnl_modular_nominal_v1","detector"=>contract["model_id"],"source"=>"cs137_point_decay_v1","pose"=>"nominal","primary_count"=>20,"seed"=>26092631,"threads"=>Threads.nthreads(),"electronics"=>JSON.parsefile(profile)["settings"])
request=Dict("kind"=>"catalog_native_request_v1","configuration_sha256"=>"a"^64,"selection"=>selection,"model_contract"=>contract,"profile_ref"=>".local/runs/"*name*"/electronics/profile.json","profile_sha256"=>CM.hashfile(profile),"stream_ref"=>".local/runs/"*name*"/transport/stream/manifest.json","stream_sha256"=>CM.hashfile(stream),"source_sha256"=>Dict("simulation/"*s=>CM.hashfile(joinpath(@__DIR__,s)) for s in CR.SOURCES),"numerics"=>CM.numerics(contract))
file=joinpath(base,"catalog-request.json");save(d)=write(file,JSON.json(d,2)*"\n")
save(request)
@testset "Native request uses canonical model and exact shared numerics" begin
    o,r=CR.request_options(["--request",file,"--inspect"])
    @test o["inspect"] && o["output"]===nothing && r==request
    cfg=CM.config(contract,joinpath(base,"response"))
    @test cfg.precision==64 && cfg.min_grid==0.25 && cfg.max_grid==2 && cfg.threads==Threads.nthreads()
    for key in ("min_spacing_mm","precision_bits","potential_rechecks")
        d=deepcopy(request);d["numerics"][key]+=1;save(d)
        @test_throws ArgumentError CR.request_options(["--request",file,"--inspect"])
    end
    for key in ("stored_temperature_K","readout_contact_id","wiring_factor")
        d=deepcopy(request);d["model_contract"][key]+=1;save(d)
        @test_throws ArgumentError CR.request_options(["--request",file,"--inspect"])
    end
    for key in ("primary_count","seed","threads")
        d=deepcopy(request);d["selection"][key]=true;save(d)
        @test_throws ArgumentError CR.request_options(["--request",file,"--inspect"])
    end
    d=deepcopy(request);d["selection"]["detector"]="SAP22";save(d)
    @test_throws ArgumentError CR.request_options(["--request",file,"--inspect"])
    d=deepcopy(request);delete!(d["source_sha256"],"simulation/catalog_native_response.jl");save(d)
    @test_throws ArgumentError CR.request_options(["--request",file,"--inspect"])
    d=deepcopy(request);d["stream_sha256"]="0"^64;save(d)
    @test_throws ArgumentError CR.request_options(["--request",file,"--inspect"])
    save(request);mkdir(joinpath(base,"response"))
    @test_throws ArgumentError CR.request_options(["--request",file,"--output",joinpath(base,"response")])
end
save(request)
write(joinpath(base,"SCHEMA-TEST.json"),JSON.json(Dict("kind"=>"catalog_native_request_software_test_v1","science_calls"=>0,"calibration_calls"=>0,"field_solves"=>0,"drift_calls"=>0,"prepared_sha256"=>CM.hashfile(ARGS[1]),"prepared_ref"=>replace(relpath(ARGS[1],CM.ROOT),'\\'=>'/'),"julia_threads"=>Threads.nthreads(),"scope"=>"Only request reader and native membership; synthetic stream stub is deliberately not a source ledger"),2)*"\n")
println("Complete response module and exact request tests passed; field solves 0; drift calls 0; calibration calls 0")
