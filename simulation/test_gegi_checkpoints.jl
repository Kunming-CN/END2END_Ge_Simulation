using Test
include("gegi_response.jl")
const G=GeGIResponse

@testset "GeGI atomic checkpoint persistence" begin
    parent=joinpath(G.ROOT,".local","gegi-integration")
    mkpath(parent)
    directory=mktempdir(parent;prefix="checkpoint-test-",cleanup=false)
    @test G.Q.childof(realpath(directory),realpath(parent))
    try
        path=joinpath(directory,"checkpoint.json")
        original="previous complete checkpoint"
        write(path,original)
        calls=Ref(0);delays=Float64[]
        function delayed_rename(src,dst)
            calls[]+=1
            if calls[]<=2
                @test read(dst,String)==original
                throw(Base.IOError("temporary cloud sync lock",Base.UV_EACCES))
            end
            Base.Filesystem.rename(src,dst)
        end
        payload=Dict("status"=>"complete","values"=>[1.,-2.,3.])
        G.save(path,payload;rename_file=delayed_rename,wait=d->push!(delays,d))
        @test calls[]==3 && delays==[0.1,0.2]
        @test G.JSON.parsefile(path)==payload
        @test read(path,String)==G.JSON.json(payload)*"\n"
        @test !isfile(path*".tmp")

        stable=read(path,String);calls[]=0;empty!(delays)
        function locked_rename(src,dst)
            calls[]+=1
            throw(Base.IOError("persistent cloud sync lock",Base.UV_EBUSY))
        end
        @test_throws Base.IOError G.save(path,Dict("new"=>true);rename_file=locked_rename,wait=d->push!(delays,d))
        @test calls[]==8 && length(delays)==7 && sum(delays)<=7.2
        @test read(path,String)==stable
        @test G.JSON.parsefile(path*".tmp")==Dict("new"=>true)
        @test G.transient_io(SystemError("opening checkpoint",Base.Libc.EACCES))
        calls[]=0
        @test_throws ArgumentError G.retry_checkpoint_io(;wait=d->nothing) do
            calls[]+=1;throw(ArgumentError("invalid content"))
        end
        @test calls[]==1

        event=Dict("event_id"=>7,"status"=>"completed","channels"=>[Dict("trace"=>fill(1.,5000))])
        report=Dict("kind"=>"gegi_multichannel_results_v1","status"=>"running",
            "counts"=>Dict("initial_primaries"=>100),"events"=>[event])
        compact=G.compact_run(report)
        @test compact["kind"]=="gegi_native_response_v1"
        @test !haskey(compact,"events") && compact["counts"]==report["counts"]
        @test compact["event_checkpoints"]==[Dict("event_id"=>7,"status"=>"completed","record_ref"=>"events/7.json")]
        @test report["events"]==[event] && length(event["channels"][1]["trace"])==5000
        @test sizeof(G.JSON.json(compact))<1000
        G.save_run(directory,report)
        @test G.JSON.parsefile(joinpath(directory,"run.json"))==compact
    finally
        # This directory was just created by this test; verify the absolute root
        # immediately before removing its owned synthetic files.
        @assert !islink(directory) && G.Q.childof(realpath(directory),realpath(parent))
        rm(directory;recursive=true)
    end
end
