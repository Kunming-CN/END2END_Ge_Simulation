include("native_progress_resilience.jl")
using Test, JSON
const P=NativeProgressResilience
const C=NativeCheckpointBatch
const DIR=mktempdir(joinpath(C.ROOT,".local","native-progress-recovery");prefix="display-test-",cleanup=false)
@testset "Display-only permission-error recovery" begin
    path=joinpath(DIR,"progress.html")
    before=C.hashfile(joinpath(@__DIR__,"native_checkpoint_batch.jl"))
    write(path,"old display")
    denied=(a,b)->throw(Base.IOError("synthetic sharing denial",Base.UV_EACCES))
    @test P.publish(io->write(io,"new display"),path;rename_file=denied,delays=(0.0,0.0))===false
    @test read(path,String)=="old display"
    @test P.publish(io->write(io,"new display"),path)===true
    @test read(path,String)=="new display"
    calls=Ref(0)
    transient=(a,b)->begin
        calls[]+=1
        calls[]<3 && throw(Base.IOError("synthetic busy file",Base.UV_EBUSY))
        Base.Filesystem.rename(a,b)
    end
    @test P.publish(io->write(io,"retry succeeded"),path;rename_file=transient,delays=(0.0,0.0))===true
    @test calls[]==3
    @test read(path,String)=="retry succeeded"
    @test_throws ArgumentError P.publish(io->nothing,joinpath(DIR,"result.jls"))
    broken=(a,b)->throw(ArgumentError("programming defect"))
    @test_throws ArgumentError P.publish(io->nothing,path;rename_file=broken)
    full=(a,b)->throw(Base.IOError("disk full",Base.UV_ENOSPC))
    @test_throws Base.IOError P.publish(io->nothing,path;rename_file=full)
    @test P.sharing_error(Base.IOError("denied",Base.UV_EACCES))
    @test !P.sharing_error(InterruptException())
    @test !P.sharing_error(ArgumentError("not IO"))
    P.install!()
    @test Base.invokelatest(C.progress,DIR,"running",2,10,0,2,time(),0)===true
    @test JSON.parsefile(joinpath(DIR,"progress.json"))["completed_groups"]==2
    @test occursin("Completed groups: 2 / 10",read(path,String))
    @test before==C.hashfile(joinpath(@__DIR__,"native_checkpoint_batch.jl"))==P.ORIGINAL_SHA
end
println("Display-only evidence retained: ",DIR)
