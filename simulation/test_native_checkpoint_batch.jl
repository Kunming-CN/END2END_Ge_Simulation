include("native_checkpoint_batch.jl")
using Test, Serialization, JSON
const C=NativeCheckpointBatch
root=joinpath(C.ROOT,".local","native-response-fix");mkpath(root)
dir=mktempdir(root;prefix="checkpoint-unit-")
record(key)=Dict("key"=>key,"input_hash"=>"input","config_hash"=>"config","status"=>"native_failed","accepted"=>false,"native"=>nothing,"readout"=>nothing,"error"=>Dict("type"=>"test"))
@testset "Native durable checkpoint boundary" begin
    f=joinpath(dir,"test.json");C.save(f,Dict("n"=>1))
    @test JSON.parsefile(f)["n"]==1
    @test_throws ArgumentError C.save(f,Dict("n"=>2))
    @test JSON.parsefile(f)["n"]==1
    handle=C.acquire(joinpath(dir,"worker.lock"))
    @test_throws ArgumentError C.acquire(joinpath(dir,"worker.lock"))
    C.release(handle);handle=C.acquire(joinpath(dir,"worker.lock"));C.release(handle)
    d=C.commit(dir,record("one"));before=stat(joinpath(dir,"one.jls")).mtime
    @test C.recover(dir,"one","input","config")==d
    @test stat(joinpath(dir,"one.jls")).mtime==before
    @test_throws ArgumentError C.recover(dir,"one","different","config")
    C.atomic_write(io->serialize(io,record("two")),joinpath(dir,"two.jls"))
    @test !isfile(joinpath(dir,"two.done.json"))
    @test C.recover(dir,"two","input","config")["recovered"]
    @test isfile(joinpath(dir,"two.done.json"))
    rm(joinpath(dir,"two.jls")) # Deliberate corruption of this synthetic test fixture only.
    @test_throws ArgumentError C.recover(dir,"two","input","config")
    open(joinpath(dir,"one.jls"),"a") do io;write(io,UInt8(0));end
    @test_throws ArgumentError C.recover(dir,"one","input","config")
end
println("Synthetic evidence retained at ",dir)
@testset "Checkpoint identity and actual environment" begin
    C.commit(dir,record("swap"))
    original=joinpath(dir,"swap.jls");dpath=joinpath(dir,"swap.done.json")
    different=record("another-group")
    open(original,"w") do io;serialize(io,different);end
    d=JSON.parsefile(dpath);d["result_hash"]=C.hashfile(original)
    open(dpath,"w") do io;JSON.print(io,d);end
    @test_throws ArgumentError C.recover(dir,"swap","input","config")
    env=Dict("project"=>"simulation/Project.toml","manifest"=>"simulation/Manifest.toml","hash"=>"expected")
    @test C.check_environment(env,deepcopy(env))===nothing
    @test_throws ArgumentError C.check_environment(merge(env,Dict("project"=>"other/Project.toml")),env)
    @test_throws ArgumentError C.check_environment(merge(env,Dict("manifest"=>"simulation/Manifest-v1.13.toml")),env)
    @test_throws ArgumentError C.check_environment(merge(env,Dict("hash"=>"different")),env)
end
